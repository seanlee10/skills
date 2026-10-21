"""The local library: subject/year folders, the manifest, item filters and time zones.

Layout (ruling R6: `media/` and `.thumbs/` are skill-owned):

    <out_root>/<subject>/<year>/manifest.json
    <out_root>/<subject>/<year>/media/<unique filename>
    <out_root>/<subject>/<year>/.thumbs/<sha256(id)[:16]>.jpg

Item ids from Google are opaque and never used as paths. The manifest never holds tokens or
`baseUrl`s.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import Failure

DEFAULT_OUT_ROOT = Path('~/Pictures/google-photo')
MANIFEST = 'manifest.json'
MANIFEST_VERSION = 1
MEDIA_DIR = 'media'
THUMBS_DIR = '.thumbs'
_LOCALTIME = Path('/etc/localtime')
_SUBJECT_MAX = 100
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_FRACTION = re.compile(r'(\.\d{6})\d+')
_TYPES = {'photo': frozenset({'PHOTO'}), 'video': frozenset({'VIDEO'}), 'all': frozenset({'PHOTO', 'VIDEO'})}
_ORIENTATIONS = ('portrait', 'landscape')
_NAME_MAX_BYTES = 200  # leaves room for a _N suffix under the usual 255-byte limit
_EXT_MAX = 16


# ---- subject and folders -----------------------------------------------------------------

def check_subject(subject: str) -> str:
    """Return the stripped subject if it is safe as one folder name, else UNSAFE_SUBJECT."""
    s = subject.strip() if isinstance(subject, str) else ''
    if (not s or s in ('.', '..') or '/' in s or '\\' in s or _CONTROL.search(s)
            or len(s) > _SUBJECT_MAX):
        raise Failure('UNSAFE_SUBJECT')
    return s


def year_dir(out_root: Path, subject: str, year: int) -> Path:
    """`out_root/subject/year`, created with its skill-owned `media/` and `.thumbs/` folders."""
    path = Path(out_root).expanduser() / check_subject(subject) / str(int(year))
    (path / MEDIA_DIR).mkdir(parents=True, exist_ok=True)
    (path / THUMBS_DIR).mkdir(exist_ok=True)
    return path


def inside(folder: Path, rel) -> Path | None:
    """`folder/rel` resolved, if `rel` is a string that stays inside `folder` (R8), else None.

    Manifest paths are user-editable, so every one is checked before it is opened.
    """
    if not isinstance(rel, str) or not rel:
        return None
    try:
        base = Path(folder).resolve()
        path = (base / rel).resolve()
    except (OSError, ValueError, RuntimeError):  # NUL bytes, symlink loops
        return None
    return path if base in path.parents else None


# ---- time zones --------------------------------------------------------------------------

def _zone(name: str) -> ZoneInfo | None:
    if not name or name.startswith('/') or '..' in name.split('/'):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _localtime_name() -> str | None:
    """The zone name from the /etc/localtime symlink target (…/zoneinfo/<Area>/<City>)."""
    try:
        target = os.readlink(_LOCALTIME)
    except OSError:
        return None  # missing, unreadable or a plain copied file
    _, sep, name = target.rpartition('zoneinfo/')
    if not sep:
        return None
    for prefix in ('posix/', 'right/'):
        name = name.removeprefix(prefix)
    return name or None


def resolve_tz(name: str | None) -> tuple[ZoneInfo, str]:
    """(zone, name): explicit name, else $TZ, else /etc/localtime, else UTC ('UTC (fallback)').

    A bad explicit name fails with UNKNOWN_TIME_ZONE; an unusable $TZ or /etc/localtime is
    skipped, since the user did not type it here.
    """
    if name is not None:
        zone = _zone(name)
        if zone is None:
            raise Failure('UNKNOWN_TIME_ZONE')
        return zone, name
    for candidate in (os.environ.get('TZ', '').removeprefix(':'), _localtime_name()):
        zone = _zone(candidate) if candidate else None
        if zone is not None:
            return zone, candidate
    return ZoneInfo('UTC'), 'UTC (fallback)'


def local_time(create_time: str, tz) -> datetime:
    """Parse an RFC 3339 `createTime` (0–9 fractional digits) into an aware time in `tz`."""
    try:
        parsed = datetime.fromisoformat(_FRACTION.sub(r'\1', create_time))
    except (TypeError, ValueError):
        raise Failure('BAD_RESPONSE') from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(tz)


# ---- filters -----------------------------------------------------------------------------

def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise Failure('USAGE_ERROR') from None


@dataclass(frozen=True)
class Filters:
    date_from: date
    date_to: date
    types: frozenset[str]
    camera: str | None
    orientation: str | None
    min_side: int | None

    @classmethod
    def for_year(cls, year: int, date_from=None, date_to=None, type='all', camera=None,
                 orientation=None, min_side=None) -> 'Filters':
        """Validated filters; the date range must lie within `year` (inclusive both ends)."""
        start = _as_date(date_from) if date_from is not None else date(year, 1, 1)
        end = _as_date(date_to) if date_to is not None else date(year, 12, 31)
        if start.year != year or end.year != year or start > end:
            raise Failure('DATE_RANGE_OUTSIDE_YEAR')
        if type not in _TYPES or orientation not in (None, *_ORIENTATIONS):
            raise Failure('USAGE_ERROR')
        if camera is not None:
            camera = camera.strip()
            if not camera:
                raise Failure('USAGE_ERROR')
        if min_side is not None and (isinstance(min_side, bool) or not isinstance(min_side, int)
                                     or min_side < 1):
            raise Failure('USAGE_ERROR')
        return cls(start, end, _TYPES[type], camera, orientation, min_side)

    def to_json(self) -> dict:
        return {'date_from': self.date_from.isoformat(), 'date_to': self.date_to.isoformat(),
                'types': sorted(self.types), 'camera': self.camera, 'orientation': self.orientation,
                'min_side': self.min_side}

    @classmethod
    def from_json(cls, data: dict) -> 'Filters':
        return cls(date.fromisoformat(data['date_from']), date.fromisoformat(data['date_to']),
                   frozenset(data['types']), data.get('camera'), data.get('orientation'),
                   data.get('min_side'))


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_reason(item: dict, f: Filters, tz) -> str | None:
    """Why `item` is filtered out ('out_of_range', 'type', 'camera', 'orientation',
    'resolution'; first match wins), or None if it passes.

    Missing metadata fails only the filters that need it (e.g. no camera → 'camera' when a
    camera filter is set); an item without a usable createTime is 'out_of_range'.
    """
    try:
        day = local_time(item.get('createTime'), tz).date()
    except Failure:
        return 'out_of_range'
    if not f.date_from <= day <= f.date_to:
        return 'out_of_range'
    if item.get('type') not in f.types:
        return 'type'
    meta = (item.get('mediaFile') or {}).get('mediaFileMetadata') or {}
    if f.camera is not None:
        camera = ' '.join(str(meta[k]) for k in ('cameraMake', 'cameraModel') if meta.get(k))
        if f.camera.casefold() not in camera.casefold():
            return 'camera'
    width, height = _int(meta.get('width')), _int(meta.get('height'))
    if f.orientation is not None:
        if width is None or height is None:
            return 'orientation'
        if f.orientation == 'portrait' and not height > width:
            return 'orientation'
        if f.orientation == 'landscape' and not width > height:
            return 'orientation'
    if f.min_side is not None and (width is None or height is None or min(width, height) < f.min_side):
        return 'resolution'
    return None


# ---- names -------------------------------------------------------------------------------

def _clip(text: str, max_bytes: int) -> str:
    return text.encode('utf-8')[:max_bytes].decode('utf-8', 'ignore')


def _name_key(name: str) -> str:
    """How a default APFS volume compares names: Unicode-normalised and case-insensitive."""
    return unicodedata.normalize('NFC', unicodedata.normalize('NFC', name).casefold())


def unique_name(media_dir: Path, filename: str, used: set[str]) -> str:
    """A safe, unused basename for `filename` inside `media_dir`.

    Directories are dropped, control characters become `_`, an empty name becomes `item`.
    A name taken by an existing entry (even a dangling symlink) or in `used` (compared
    case-insensitively and NFC-normalised, as on default macOS volumes) gets `_2`, `_3`… before the extension.
    """
    base = re.split(r'[/\\]', filename or '')[-1]
    base = _CONTROL.sub('_', base).strip()
    if base in ('', '.', '..'):
        base = 'item'
    stem, ext = os.path.splitext(base)
    if len(ext) > _EXT_MAX:
        stem, ext = base, ''
    stem = _clip(stem, _NAME_MAX_BYTES - len(ext.encode('utf-8'))) or 'item'
    taken = {_name_key(name) for name in used}
    candidate, n = stem + ext, 1
    while _name_key(candidate) in taken or os.path.lexists(Path(media_dir) / candidate):
        n += 1
        candidate = f'{stem}_{n}{ext}'
    return candidate


def thumb_name(item_id: str) -> str:
    return hashlib.sha256(item_id.encode('utf-8')).hexdigest()[:16] + '.jpg'


# ---- manifest ----------------------------------------------------------------------------

def load_manifest(directory: Path) -> dict:
    """The year folder's manifest; a missing one is empty, an unreadable one MANIFEST_CORRUPT."""
    path = Path(directory) / MANIFEST
    if not os.path.lexists(path):
        return {'version': MANIFEST_VERSION, 'items': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Failure('MANIFEST_CORRUPT') from None
    if (not isinstance(data, dict) or data.get('version') != MANIFEST_VERSION
            or not isinstance(data.get('items'), dict)):
        raise Failure('MANIFEST_CORRUPT')
    return data


def save_manifest(directory: Path, manifest: dict) -> None:
    """Write the manifest atomically (temp file in the same folder, fsync, os.replace)."""
    directory = Path(directory)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.manifest-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, directory / MANIFEST)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
