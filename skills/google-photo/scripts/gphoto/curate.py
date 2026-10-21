"""`curate`, stage 1: a local pre-filter of the year folder and contact sheets for the agent.

Photos are analysed through their small `.thumbs/` JPEG (so HEIC/RAW originals need no
decoder); only an item without a thumb is opened from its original. Near-duplicates and
bursts collapse to their sharpest shot, blurry and dark shots are dropped, and the rest is
capped per month. The survivors get refs (`C001…` photos, `V001…` videos) and are laid out
on contact sheets of small labelled tiles.

Writes only inside `<year>/curation/`: `candidates.json` and `sheets/sheet-NN.jpg`. The
agent's `curation/picks.json` is never created or deleted here.

`select`, stage 2 (`apply_picks`): the agent's ranked picks become `<year>/selection.json`
and `<year>/selected/NNN_<media filename>` hard links (or copies) of the media files.
`media/` is never changed, and only files listed in the previous `selection.json` are
removed from `selected/`.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import warnings as _warnings
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from . import library
from .errors import Failure

BURST_GAP_S = 20
BURST_HAMMING = 12
DUP_HAMMING = 5
BLUR_RATIO = 0.35
DARK_LUMA = 40
CANDIDATE_FACTOR = 4
VIDEO_CAP = 30
TILE = 256
GRID = (5, 4)
DEFAULT_TARGET = 75
DEFAULT_VIDEO_TARGET = 8

LABEL_H = 20                     # label strip under each tile's image
CURATION_DIR = 'curation'
SHEETS_DIR = 'sheets'
CANDIDATES = 'candidates.json'
PICKS = 'picks.json'
ANALYSIS_MAX = 512
FFMPEG_TIMEOUT = 30
FRAME_POINTS = (0.10, 0.35, 0.60, 0.85)
DROP_REASONS = ('invalid_entry', 'missing', 'undecodable', 'near_duplicate', 'blurry', 'dark',
                'month_cap', 'video_cap')
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], 1, 128)
_SHEET_NAME = re.compile(r'sheet-\d+\.jpg')
_NOT_ASCII = re.compile(r'[^\x20-\x7e]')
_BG, _FG, _PAD = (24, 24, 24), (235, 235, 235), (48, 48, 48)
_CANDIDATE_KEYS = ('ref', 'id', 'file', 'type', 'local_time', 'sharpness', 'brightness', 'group_size')
SELECTED_DIR = 'selected'
SELECTION = 'selection.json'
REASON_MAX = 200
_SELECTED_NAME = re.compile(r'\d{3}_.+')
_CONTROLS = re.compile(r'[\x00-\x1f\x7f-\x9f]+')


class Undecodable(Exception):
    """An image Pillow cannot (or must not, e.g. a decompression bomb) decode."""


# ---- decoding ----------------------------------------------------------------------------

def _decode(source, mode: str, box: int) -> Image.Image:
    """Open `source` (a path or a file object), upright, in `mode`, fitting in `box`×`box`.

    Pillow's decompression-bomb warning is raised as an error and `Image.MAX_IMAGE_PIXELS`
    applies; any decoding failure becomes Undecodable.
    """
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(source) as img:
                img.draft(mode, (box, box))  # JPEG: decode at a reduced scale
                upright = ImageOps.exif_transpose(img)
                out = upright.convert(mode)
                out.thumbnail((box, box))
                return out
    except Exception:  # Pillow raises many types for broken input; none may crash curate
        raise Undecodable() from None


def features(path: Path) -> dict:
    """{"dhash": 64-bit int, "sharpness": Laplacian variance, "brightness": mean luma 0–255}."""
    gray = _decode(path, 'L', ANALYSIS_MAX)
    small = gray.resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    dhash = 0
    for row in range(8):
        for col in range(8):
            dhash = (dhash << 1) | (small[row * 9 + col] > small[row * 9 + col + 1])
    sharpness = ImageStat.Stat(gray.filter(_LAPLACIAN)).var[0]
    brightness = ImageStat.Stat(gray).mean[0]
    return {'dhash': dhash, 'sharpness': float(sharpness), 'brightness': float(brightness)}


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# ---- shortlist ---------------------------------------------------------------------------

def _when(entry: dict) -> datetime:
    return datetime.fromisoformat(entry['local_time'])


def _month(entry: dict) -> str:
    return _when(entry).strftime('%Y-%m')


def _allocate(counts: dict[str, int], cap: int) -> dict[str, int]:
    """Split `cap` over months: never above a month's count, total == min(cap, all items).

    When there are at least as many slots as months, every month first gets one slot (so a
    month with photos is never starved by a much larger one); the remaining slots are split
    proportionally to √count with the largest-remainder rule.
    """
    if sum(counts.values()) <= cap:
        return dict(counts)
    quota = {m: 0 for m in counts}
    room = cap
    if len(counts) <= cap:
        quota = {m: 1 for m in counts}
        room -= len(counts)
    limit = {m: counts[m] - quota[m] for m in counts}
    rest = {m for m in counts if limit[m] > 0}
    shares: dict[str, float] = {}
    while rest:  # months whose share covers all their remaining items take them; re-split the rest
        total = sum(math.sqrt(counts[m]) for m in rest)
        shares = {m: room * math.sqrt(counts[m]) / total for m in rest}
        full = [m for m in rest if shares[m] >= limit[m]]
        if not full:
            break
        for m in full:
            quota[m] += limit[m]
            room -= limit[m]
            rest.discard(m)
    floors = {m: int(shares[m]) for m in rest}
    order = sorted(rest, key=lambda m: (floors[m] - shares[m], m))  # largest remainder first
    for m in order[:room - sum(floors.values())]:
        floors[m] += 1
    for m in rest:
        quota[m] += floors[m]
    return quota


def _by_month(items: list[dict]) -> dict[str, list[dict]]:
    months: dict[str, list[dict]] = {}
    for item in items:
        months.setdefault(_month(item), []).append(item)
    return months


def _groups(photos: list[dict]) -> list[list[dict]]:
    """Burst / near-duplicate groups of time-sorted `photos` (union-find)."""
    parent = list(range(len(photos)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    times = [_when(p).timestamp() for p in photos]
    for i in range(len(photos) - 1):
        if (times[i + 1] - times[i] <= BURST_GAP_S
                and hamming(photos[i]['dhash'], photos[i + 1]['dhash']) <= BURST_HAMMING):
            union(i, i + 1)
    for i in range(len(photos)):
        for j in range(i + 1, len(photos)):
            if hamming(photos[i]['dhash'], photos[j]['dhash']) <= DUP_HAMMING:
                union(i, j)
    groups: dict[int, list[dict]] = {}
    for i, p in enumerate(photos):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())


def shortlist(entries: list[dict], target: int, video_target: int) -> tuple[list[dict], dict[str, int]]:
    """Candidates (copies of `entries` with `ref` and `group_size`) and the dropped counts.

    Photo entries need `local_time`, `dhash`, `sharpness`, `brightness`; video entries need
    `local_time`. Photos are capped at `target × CANDIDATE_FACTOR`, videos at
    `max(VIDEO_CAP, video_target)`.
    """
    dropped = {k: 0 for k in DROP_REASONS if k not in ('invalid_entry', 'missing', 'undecodable')}
    photos = sorted((e for e in entries if e.get('type') == 'PHOTO'), key=lambda e: (_when(e), e.get('id', '')))
    videos = sorted((e for e in entries if e.get('type') == 'VIDEO'), key=lambda e: (_when(e), e.get('id', '')))

    keepers = []
    for group in _groups(photos):
        best = max(group, key=lambda p: (p['sharpness'], p['brightness']))
        keepers.append(dict(best, group_size=len(group)))
        dropped['near_duplicate'] += len(group) - 1
    median = statistics.median(p['sharpness'] for p in keepers) if keepers else 0.0
    good = []
    for p in keepers:
        if p['brightness'] < DARK_LUMA:
            dropped['dark'] += 1
        elif p['sharpness'] < BLUR_RATIO * median:
            dropped['blurry'] += 1
        else:
            good.append(p)

    chosen_photos = []
    months = _by_month(good)
    quota = _allocate({m: len(v) for m, v in months.items()}, target * CANDIDATE_FACTOR)
    for m, items in months.items():
        best = sorted(items, key=lambda p: (-p['sharpness'], _when(p)))[:quota[m]]
        chosen_photos.extend(best)
        dropped['month_cap'] += len(items) - len(best)

    chosen_videos = []
    months = _by_month(videos)
    quota = _allocate({m: len(v) for m, v in months.items()}, max(VIDEO_CAP, video_target))
    for m, items in months.items():
        n, k = len(items), quota[m]
        picked = [items[int((j + 0.5) * n / k)] for j in range(k)]  # evenly spread in time
        chosen_videos.extend(dict(v, group_size=1) for v in picked)
        dropped['video_cap'] += n - k

    candidates = []
    for prefix, chosen in (('C', chosen_photos), ('V', chosen_videos)):
        chosen.sort(key=lambda e: (_when(e), e.get('id', '')))
        for i, c in enumerate(chosen, 1):
            candidates.append(dict(c, ref=f'{prefix}{i:03d}'))
    return candidates, dropped


# ---- contact sheets ----------------------------------------------------------------------

def _run(argv: list[str]) -> bytes | None:
    """stdout of `argv` (no shell, stdin closed, 30 s timeout), or None on any failure."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=FFMPEG_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return done.stdout if done.returncode == 0 and done.stdout else None


def _video_frames(ffmpeg: str, ffprobe: str, video: Path) -> list[Image.Image] | None:
    """Four frames at 10/35/60/85 % of the duration, or None if anything fails."""
    src = f'file:{Path(video).resolve()}'  # absolute and prefixed: never read as an option
    out = _run([ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', src])
    try:
        duration = float(out.decode('ascii', 'replace').strip().splitlines()[0]) if out else math.nan
    except (ValueError, IndexError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    frames = []
    half = TILE // 2
    for point in FRAME_POINTS:
        data = _run([ffmpeg, '-nostdin', '-v', 'error', '-ss', f'{duration * point:.3f}', '-i', src,
                     '-frames:v', '1', '-vf', f'scale={half}:{half}:force_original_aspect_ratio=decrease',
                     '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'])
        if data is None:
            return None
        try:
            frames.append(_decode(io.BytesIO(data), 'RGB', half))
        except Undecodable:
            return None
    return frames


def _label(candidate: dict) -> str:
    day = str(candidate.get('local_time', ''))[:10]
    return _NOT_ASCII.sub('?', f'{candidate.get("ref", "")} {day}')


def _tile(candidate: dict, ffmpeg: str | None, ffprobe: str | None, warnings: list[str]) -> Image.Image:
    tile = Image.new('RGB', (TILE, TILE + LABEL_H), _BG)
    frames = None
    if candidate.get('type') == 'VIDEO' and ffmpeg and ffprobe and candidate.get('video'):
        frames = _video_frames(ffmpeg, ffprobe, candidate['video'])
        if frames is None:
            warnings.append(f'VIDEO_FRAMES_FAILED:{candidate.get("ref")}')
    if frames:
        half = TILE // 2
        for i, frame in enumerate(frames):
            x, y = (i % 2) * half, (i // 2) * half
            tile.paste(frame, (x + (half - frame.width) // 2, y + (half - frame.height) // 2))
    else:
        image = None
        if candidate.get('image'):
            try:
                image = ImageOps.contain(_decode(candidate['image'], 'RGB', TILE), (TILE, TILE))
            except Undecodable:
                warnings.append(f'TILE_UNREADABLE:{candidate.get("ref")}')
        if image is None:
            ImageDraw.Draw(tile).rectangle([0, 0, TILE - 1, TILE - 1], fill=_PAD)
        else:
            tile.paste(image, ((TILE - image.width) // 2, (TILE - image.height) // 2))
    ImageDraw.Draw(tile).text((4, TILE + 4), _label(candidate), fill=_FG, font=ImageFont.load_default())
    return tile


def _save_jpeg(img: Image.Image, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.sheet-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            img.save(f, 'JPEG', quality=85)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def contact_sheets(candidates: list[dict], sheets_dir: Path, ffmpeg: str | None,
                   ffprobe: str | None = None, warnings: list[str] | None = None) -> list[Path]:
    """Write `sheet-01.jpg…` (GRID tiles of TILE px, labelled `ref YYYY-MM-DD`) into `sheets_dir`.

    Candidates need `ref`, `type`, `local_time` and `image` (the picture or Google thumb to
    show, or None); videos may carry `video` (the file) for ffmpeg frames. `ffprobe` defaults
    to the `ffprobe` next to `ffmpeg`. Earlier `sheet-*.jpg` files are removed first.
    """
    warnings = [] if warnings is None else warnings
    if ffmpeg and ffprobe is None:
        ffprobe = str(Path(ffmpeg).with_name('ffprobe'))
    sheets_dir = Path(sheets_dir)
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for p in sheets_dir.iterdir():
        if _SHEET_NAME.fullmatch(p.name) and (p.is_symlink() or p.is_file()):
            p.unlink()
    cols, rows = GRID
    per_sheet = cols * rows
    paths = []
    for start in range(0, len(candidates), per_sheet):
        chunk = candidates[start:start + per_sheet]
        used_rows = math.ceil(len(chunk) / cols)
        sheet = Image.new('RGB', (cols * TILE, used_rows * (TILE + LABEL_H)), _BG)
        for i, candidate in enumerate(chunk):
            sheet.paste(_tile(candidate, ffmpeg, ffprobe, warnings),
                        ((i % cols) * TILE, (i // cols) * (TILE + LABEL_H)))
        path = sheets_dir / f'sheet-{start // per_sheet + 1:02d}.jpg'
        _save_jpeg(sheet, path)
        paths.append(path)
    return paths


# ---- the curate command ------------------------------------------------------------------

def _valid_time(value) -> bool:
    """An ISO 8601 time with a UTC offset (naive and aware times cannot be ordered together)."""
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except (TypeError, ValueError):
        return False


def _load_entries(folder: Path, manifest: dict, dropped: dict) -> tuple[list[dict], int]:
    """Analysable entries and the number of items whose media file is on disk."""
    entries, on_disk = [], 0
    for item_id, e in sorted(manifest['items'].items()):
        if (not isinstance(e, dict) or e.get('type') not in ('PHOTO', 'VIDEO')
                or not _valid_time(e.get('local_time')) or not isinstance(e.get('file'), str)):
            dropped['invalid_entry'] += 1
            continue
        file = library.inside(folder, e['file'])  # R8: the manifest is user-editable
        if file is None or not file.is_file():
            dropped['missing'] += 1
            continue
        on_disk += 1
        thumb = library.inside(folder, e.get('thumb'))
        thumb = thumb if thumb is not None and thumb.is_file() else None
        rec = {'id': item_id, 'file': e['file'], 'type': e['type'], 'local_time': e['local_time'],
               'sharpness': None, 'brightness': None, 'image': thumb, 'video': None}
        if e['type'] == 'VIDEO':
            rec['video'] = file
        else:
            source = thumb or file  # never the full-size original when a thumb exists
            try:
                rec.update(features(source))
            except Undecodable:
                dropped['undecodable'] += 1
                continue
            rec['image'] = source
        entries.append(rec)
    return entries, on_disk


def _curation_dir(folder: Path) -> Path:
    """`<year>/curation/sheets`, created; a symlink or non-folder there is refused."""
    curation = folder / CURATION_DIR
    for path in (curation, curation / SHEETS_DIR):
        if path.is_symlink() or (os.path.lexists(path) and not path.is_dir()):
            raise Failure('CURATION_DIR_UNSAFE')
        path.mkdir(exist_ok=True)
    return curation


def _write_json(path: Path, data: dict, prefix: str = '.candidates-') -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _public(candidate: dict) -> dict:
    out = {k: candidate.get(k) for k in _CANDIDATE_KEYS}
    for k in ('sharpness', 'brightness'):
        if out[k] is not None:
            out[k] = round(out[k], 2)
    return out


def run_curate(subject: str, year: int, out_root=None, target: int = DEFAULT_TARGET,
               video_target: int = DEFAULT_VIDEO_TARGET) -> dict:
    """Pre-filter the year folder and write `curation/candidates.json` and contact sheets."""
    subject = library.check_subject(subject)
    for value, low in ((year, 1), (target, 1), (video_target, 0)):
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            raise Failure('USAGE_ERROR')
    if year > 9999:
        raise Failure('USAGE_ERROR')
    root = Path(out_root).expanduser() if out_root else library.DEFAULT_OUT_ROOT.expanduser()
    folder = root.absolute() / subject / str(year)
    manifest = library.load_manifest(folder)
    dropped = {k: 0 for k in DROP_REASONS}
    entries, on_disk = _load_entries(folder, manifest, dropped)
    if on_disk == 0:
        raise Failure('NOTHING_TO_CURATE')
    candidates, more = shortlist(entries, target, video_target)
    for k, v in more.items():
        dropped[k] += v

    curation = _curation_dir(folder)
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    warnings: list[str] = []
    if not (ffmpeg and ffprobe) and any(c['type'] == 'VIDEO' for c in candidates):
        warnings.append('VIDEO_FRAMES_UNAVAILABLE')  # clips are judged from Google's thumbnail
    sheets = contact_sheets(candidates, curation / SHEETS_DIR, ffmpeg if ffprobe else None,
                            ffprobe, warnings)
    _write_json(curation / CANDIDATES, {
        'target': target, 'video_target': video_target,
        'candidates': [_public(c) for c in candidates], 'dropped': dropped,
        'sheets': [f'{SHEETS_DIR}/{p.name}' for p in sheets],
    })
    base = curation.resolve()
    return {
        'status': 'ok', 'candidates': len(candidates),
        'photos': sum(c['type'] == 'PHOTO' for c in candidates),
        'videos': sum(c['type'] == 'VIDEO' for c in candidates),
        'dropped': dropped, 'sheets': [str(base / SHEETS_DIR / p.name) for p in sheets],
        'picks_file': str(base / PICKS), 'target': target, 'video_target': video_target,
        'warnings': warnings,
    }


# ---- the select command ------------------------------------------------------------------

def _year_folder(subject: str, year: int, out_root=None) -> Path:
    subject = library.check_subject(subject)
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        raise Failure('USAGE_ERROR')
    root = Path(out_root).expanduser() if out_root else library.DEFAULT_OUT_ROOT.expanduser()
    return root.absolute() / subject / str(year)


def _load_candidates(folder: Path) -> dict[str, dict]:
    """Candidates of `curation/candidates.json` by ref (only well-formed entries)."""
    curation = folder / CURATION_DIR
    if curation.is_symlink() or (os.path.lexists(curation) and not curation.is_dir()):
        raise Failure('CURATION_DIR_UNSAFE')
    path = curation / CANDIDATES
    if not os.path.lexists(path):
        raise Failure('NOTHING_TO_CURATE')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Failure('CANDIDATES_CORRUPT') from None
    if not isinstance(data, dict) or not isinstance(data.get('candidates'), list):
        raise Failure('CANDIDATES_CORRUPT')
    return {c['ref']: c for c in data['candidates']
            if isinstance(c, dict) and isinstance(c.get('ref'), str) and c.get('type') in ('PHOTO', 'VIDEO')}


def load_picks(path: Path) -> dict:
    """The picks file as parsed JSON; a missing or unreadable one is INVALID_PICKS."""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Failure('INVALID_PICKS') from None


def _reason(value) -> str:
    """The reason with control characters turned into spaces and stripped; INVALID_PICKS if
    it is not a string, or empty or over REASON_MAX characters after that."""
    if not isinstance(value, str):
        raise Failure('INVALID_PICKS')
    text = _CONTROLS.sub(' ', value).strip()
    text = re.sub(r' {2,}', ' ', text)
    if not text or len(text) > REASON_MAX:
        raise Failure('INVALID_PICKS')
    return text


def _validate(folder: Path, picks, candidates: dict[str, dict]) -> list[tuple[dict, str, Path]]:
    """(candidate, reason, media file) per pick in rank order, or INVALID_PICKS.

    Every picked media file must be on disk inside the year's `media/` folder (R8: both
    files are user/agent-editable).
    """
    items = picks.get('items') if isinstance(picks, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= len(candidates):
        raise Failure('INVALID_PICKS')
    media_dir = (folder / library.MEDIA_DIR).resolve()
    out, seen = [], set()
    for item in items:
        ref = item.get('ref') if isinstance(item, dict) else None
        if not isinstance(ref, str) or ref not in candidates or ref in seen:
            raise Failure('INVALID_PICKS')
        seen.add(ref)
        reason = _reason(item.get('reason'))
        candidate = candidates[ref]
        media = library.inside(folder, candidate.get('file'))
        if media is None or media.parent != media_dir or not media.is_file():
            raise Failure('INVALID_PICKS')
        out.append((candidate, reason, media))
    return out


def _selected_dir(folder: Path) -> Path:
    selected = folder / SELECTED_DIR
    if selected.is_symlink() or (os.path.lexists(selected) and not selected.is_dir()):
        raise Failure('SELECTED_DIR_UNSAFE')
    selected.mkdir(exist_ok=True)
    return selected


def _previous_entries(folder: Path) -> dict[str, object]:
    """`NNN_…` file name -> media `file` for each entry the previous selection.json put in
    `selected/` (bad entries ignored)."""
    try:
        data = json.loads((folder / SELECTION).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    items = data.get('items') if isinstance(data, dict) else None
    entries = {}
    for item in items if isinstance(items, list) else ():
        rel = item.get('selected_file') if isinstance(item, dict) else None
        if not isinstance(rel, str):
            continue
        head, sep, name = rel.partition('/')
        if (head == SELECTED_DIR and sep and '/' not in name and '\\' not in name
                and _SELECTED_NAME.fullmatch(name)):
            entries[name] = item.get('file')
    return entries


def _still_ours(folder: Path, path: Path, media_rel) -> bool:
    """True if `path` is still the link or copy the skill placed for `media_rel`: the same
    file (hard link), or a copy with the original's size and modification time (copies keep
    them). A symlink, or a file the user replaced or edited, is not."""
    media = library.inside(folder, media_rel)
    if media is None or path.is_symlink() or not path.is_file() or not media.is_file():
        return False
    try:
        if os.path.samefile(path, media):
            return True
        a, b = path.stat(), media.stat()
    except OSError:
        return False
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


def _clear_previous(folder: Path, selected: Path) -> list[str]:
    """Remove the previous run's own files from `selected/` and its selection.json; return
    `SELECTED_FILE_KEPT:<name>` warnings for listed files that changed since (kept)."""
    warnings = []
    for name, media_rel in sorted(_previous_entries(folder).items()):
        path = selected / name
        if _still_ours(folder, path, media_rel):
            path.unlink()
        elif path.is_symlink() or path.is_file():
            warnings.append(f'SELECTED_FILE_KEPT:{name}')
    selection = folder / SELECTION
    if selection.is_symlink() or selection.is_file():
        selection.unlink()  # no stale hand-off file if placing the new selection fails
    return warnings


def _free_name(selected: Path, name: str) -> str:
    """`name`, or `stem_2.ext`, `stem_3.ext`… if a file the skill must keep holds it."""
    if not os.path.lexists(selected / name):
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.lexists(selected / f'{stem}_{n}{ext}'):
        n += 1
    return f'{stem}_{n}{ext}'


def _place(src: Path, dst: Path) -> None:
    """Hard link `src` at `dst`, else copy it there; never overwrites an existing path."""
    try:
        os.link(src, dst)
        return
    except FileExistsError:
        raise
    except OSError:
        pass  # cross-device or a file system without hard links
    with open(src, 'rb') as fin, open(dst, 'xb') as fout:
        shutil.copyfileobj(fin, fout)
    shutil.copystat(src, dst)


def apply_picks(year_dir: Path, picks: dict) -> dict:
    """Validate the agent's ranked picks and rebuild `selected/` and `selection.json`."""
    folder = Path(year_dir)
    chosen = _validate(folder, picks, _load_candidates(folder))
    selected = _selected_dir(folder)
    warnings = _clear_previous(folder, selected)
    items, placed = [], []
    try:
        for rank, (candidate, reason, media) in enumerate(chosen, 1):
            name = _free_name(selected, f'{rank:03d}_{media.name}')
            _place(media, selected / name)
            placed.append(selected / name)
            items.append({'rank': rank, 'ref': candidate['ref'], 'id': candidate.get('id'),
                          'type': candidate['type'], 'file': candidate.get('file'),
                          'local_time': candidate.get('local_time'), 'reason': reason,
                          'selected_file': f'{SELECTED_DIR}/{name}'})
        _write_json(folder / SELECTION, {
            'subject': folder.parent.name, 'year': int(folder.name) if folder.name.isdigit() else None,
            'created': datetime.now().astimezone().isoformat(timespec='seconds'), 'items': items,
        }, prefix='.selection-')
    except BaseException:
        for path in placed:  # files no selection.json lists would be stranded as "other files"
            try:
                path.unlink()
            except OSError:
                pass
        raise
    ours = {i['selected_file'].partition('/')[2] for i in items}
    if any(p.name not in ours for p in selected.iterdir()):
        warnings.append('SELECTED_FOLDER_HAS_OTHER_FILES')
    base = folder.resolve()
    return {
        'status': 'ok', 'selected': len(items),
        'photos': sum(i['type'] == 'PHOTO' for i in items),
        'videos': sum(i['type'] == 'VIDEO' for i in items),
        'folder': str(base / SELECTED_DIR), 'selection': str(base / SELECTION), 'warnings': warnings,
    }


def run_select(subject: str, year: int, out_root=None, picks_file=None) -> dict:
    """`select`: load the picks file (default `curation/picks.json`) and apply it."""
    folder = _year_folder(subject, year, out_root)
    if not folder.is_dir():
        raise Failure('NOTHING_TO_CURATE')
    _load_candidates(folder)  # NOTHING_TO_CURATE / CURATION_DIR_UNSAFE before the picks file
    path = Path(picks_file).expanduser() if picks_file else folder / CURATION_DIR / PICKS
    picks = load_picks(path)
    try:
        outdated = path.stat().st_mtime_ns < (folder / CURATION_DIR / CANDIDATES).stat().st_mtime_ns
    except OSError:
        raise Failure('INVALID_PICKS') from None
    if outdated:  # refs were renumbered by a later curate; they would name other photos
        raise Failure('PICKS_OUTDATED')
    return apply_picks(folder, picks)
