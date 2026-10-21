"""`start` (create a picking session) and `fetch` (wait for Done, then download the picked items).

A pending session is remembered in `config_dir()/sessions/<id>.json` (mode 0600) between the
two commands. Session ids are opaque: one is used as a file name only after it matched
`_SESSION_ID`. `baseUrl`s and tokens are never written anywhere or printed.

Accounting invariant of an `ok` summary:
`picked == downloaded + already_present + sum(filtered_out) + sum(skipped)`.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from . import config, library, picker
from .errors import Failure
from .library import Filters

_SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,200}')
_DURATION = re.compile(r'(\d+(?:\.\d+)?)s')
_DEFAULT_POLL = 5.0
_POLL_RANGE = (1.0, 60.0)
_TYPE_ARG = {frozenset({'PHOTO'}): 'photo', frozenset({'VIDEO'}): 'video',
             frozenset({'PHOTO', 'VIDEO'}): 'all'}
_PENDING_KEYS = {'session', 'subject', 'year', 'out_root', 'tz', 'filters', 'created'}
INSTRUCTIONS = ('Open picker_uri in a browser signed in to Google Photos. Type the search text into '
                'the Google Photos search box, use the select-all checkbox next to each day to pick '
                'that day\'s photos and videos, then press Done. Then run the fetch command.')


# ---- pending session files ---------------------------------------------------------------

def _sessions_dir() -> Path:
    path = config.config_dir() / 'sessions'
    if not path.is_dir():
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    return path


def _write_pending(data: dict) -> None:
    directory = _sessions_dir()
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.pending-', suffix='.tmp')  # mode 0600
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / f'{data["session"]}.json')
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _remove_pending(session_id: str) -> None:
    (_sessions_dir() / f'{session_id}.json').unlink(missing_ok=True)


def _pending_id(session_id: str | None) -> str:
    """The id of the pending session to fetch: the given one, or the only one there is."""
    directory = _sessions_dir()
    if session_id is not None:
        if not _SESSION_ID.fullmatch(session_id):
            raise Failure('USAGE_ERROR')
        if not (directory / f'{session_id}.json').is_file():
            raise Failure('NO_PENDING_SESSION')
        return session_id
    ids = sorted(p.stem for p in directory.glob('*.json') if _SESSION_ID.fullmatch(p.stem) and p.is_file())
    if not ids:
        raise Failure('NO_PENDING_SESSION')
    if len(ids) > 1:
        raise Failure('AMBIGUOUS_PENDING_SESSION')
    return ids[0]


def _load_pending(session_id: str) -> dict:
    """The pending state, re-validated (the file is user-editable); PENDING_SESSION_CORRUPT if bad."""
    try:
        data = json.loads((_sessions_dir() / f'{session_id}.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != _PENDING_KEYS or data['session'] != session_id:
            raise ValueError
        year, out_root, tz_name = data['year'], data['out_root'], data['tz']
        if isinstance(year, bool) or not isinstance(year, int) or not isinstance(out_root, str) \
                or not os.path.isabs(out_root) or not isinstance(tz_name, str):
            raise ValueError
        subject = library.check_subject(data['subject'])
        zone, _ = library.resolve_tz(tz_name)
        raw = Filters.from_json(data['filters'])
        filters = Filters.for_year(year, raw.date_from, raw.date_to, _TYPE_ARG[frozenset(raw.types)],
                                   raw.camera, raw.orientation, raw.min_side)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, Failure):
        raise Failure('PENDING_SESSION_CORRUPT') from None
    return {'session': session_id, 'subject': subject, 'year': year, 'out_root': Path(out_root),
            'tz': zone, 'tz_name': tz_name, 'filters': filters}


# ---- start -------------------------------------------------------------------------------

def run_start(subject: str, year: int, token_fn, date_from=None, date_to=None, type='all',
              camera=None, orientation=None, min_side=None, tz=None, out_root=None, search=None,
              now=time.time, open_browser=None, browser=True) -> dict:
    """Validate everything, create a picking session, remember it as pending, open the link.

    `open_browser` defaults to `webbrowser.open`, looked up at call time. Opening is best effort:
    an exception or a False return only adds the warning BROWSER_NOT_OPENED (the agent then
    relays `picker_uri`, which is always printed). `browser=False` (`--no-browser`) skips it.
    """
    subject = library.check_subject(subject)
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        raise Failure('USAGE_ERROR')
    filters = Filters.for_year(year, date_from, date_to, type, camera, orientation, min_side)
    zone, _ = library.resolve_tz(tz)
    root = Path(out_root).expanduser() if out_root else library.DEFAULT_OUT_ROOT.expanduser()
    root = root.absolute()
    search = search.strip() if isinstance(search, str) and search.strip() else subject
    session = picker.create_session(token_fn())
    session_id = session['id']
    if not _SESSION_ID.fullmatch(session_id) or not session.get('pickerUri'):
        try:  # best effort: do not leave an unusable session open
            picker.delete_session(token_fn(), session_id)
        except Failure:
            pass
        raise Failure('BAD_RESPONSE')  # never used as a file name unless it is plainly safe
    _write_pending({
        'session': session_id, 'subject': subject, 'year': year, 'out_root': str(root),
        'tz': zone.key, 'filters': filters.to_json(),
        'created': datetime.fromtimestamp(now(), timezone.utc).isoformat(timespec='seconds'),
    })
    warnings = []
    if browser:
        opener = open_browser if open_browser is not None else webbrowser.open
        try:
            opened = opener(session['pickerUri'])
        except Exception:
            opened = False
        if opened is False:
            warnings.append('BROWSER_NOT_OPENED')
    expires = session.get('expireTime')
    return {'status': 'ok', 'session': session_id, 'picker_uri': session['pickerUri'], 'search': search,
            'expires': expires if isinstance(expires, str) else None, 'instructions': INSTRUCTIONS,
            'warnings': warnings}


# ---- polling -----------------------------------------------------------------------------

def _seconds(value) -> float | None:
    """A protobuf Duration string such as '5s' or '1799.5s' in seconds, else None."""
    m = _DURATION.fullmatch(value) if isinstance(value, str) else None
    return float(m.group(1)) if m else None


def _expired(session: dict, now: float) -> bool:
    timeout_in = _seconds((session.get('pollingConfig') or {}).get('timeoutIn'))
    if timeout_in is not None and timeout_in <= 0:
        return True
    try:
        expire = library.local_time(session.get('expireTime'), timezone.utc).timestamp()
    except Failure:
        return False
    return now >= expire


def _wait_for_done(token_fn, session_id: str, wait: float, now, sleep) -> bool:
    """True once the user pressed Done; False if `wait` seconds passed first.

    A token is obtained for every poll: the wait can outlast the cached access token.
    """
    deadline = now() + wait
    while True:
        session = picker.get_session(token_fn(), session_id)
        if session.get('mediaItemsSet') is True:
            return True
        if _expired(session, now()):
            raise Failure('SESSION_EXPIRED')
        remaining = deadline - now()
        if remaining <= 0:
            return False
        interval = _seconds((session.get('pollingConfig') or {}).get('pollInterval')) or _DEFAULT_POLL
        sleep(min(max(interval, _POLL_RANGE[0]), _POLL_RANGE[1], remaining))


# ---- the library folder ------------------------------------------------------------------

_inside = library.inside  # R8: manifest paths must stay inside the year folder


def _remove_stale_parts(folder: Path) -> None:
    """Delete `*.part` leftovers of interrupted downloads (skill-owned temp files, R6)."""
    for sub in (library.MEDIA_DIR, library.THUMBS_DIR):
        directory = folder / sub
        if not directory.is_dir() or directory.is_symlink():
            continue
        for p in directory.iterdir():
            if p.name.endswith('.part') and p.is_file() and not p.is_symlink():
                p.unlink(missing_ok=True)


def _fresh_path(directory: Path, filename: str, used: set[str]) -> Path:
    """A path in `directory` that does not exist right now (R7): never download onto a file."""
    while True:
        name = library.unique_name(directory, filename, used)
        used.add(name)
        path = directory / name
        if not os.path.lexists(path):
            return path


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry(item: dict, file: str, thumb: str | None, session_id: str, tz) -> dict:
    media = item.get('mediaFile') or {}
    meta = media.get('mediaFileMetadata') or {}
    video = meta.get('videoMetadata') or {}
    return {
        'file': file, 'filename': media.get('filename'), 'type': item.get('type'),
        'mime': media.get('mimeType'), 'create_time': item.get('createTime'),
        'local_time': library.local_time(item.get('createTime'), tz).isoformat(),
        'width': _int(meta.get('width')), 'height': _int(meta.get('height')),
        'camera_make': meta.get('cameraMake'), 'camera_model': meta.get('cameraModel'),
        'fps': video.get('fps'), 'thumb': thumb, 'session': session_id,
    }


def _ready_video(item: dict) -> bool:
    meta = (item.get('mediaFile') or {}).get('mediaFileMetadata') or {}
    return (meta.get('videoMetadata') or {}).get('processingStatus') == 'READY'


# ---- fetch -------------------------------------------------------------------------------

def run_fetch(session_id: str | None, wait: float, token_fn, now=time.time, sleep=time.sleep) -> dict:
    """Wait up to `wait` seconds for Done, then download every new picked item; see module doc."""
    session_id = _pending_id(session_id)
    pending = _load_pending(session_id)
    folder = Path(pending['out_root']) / pending['subject'] / str(pending['year'])
    summary = {
        'status': 'waiting', 'session': session_id, 'subject': pending['subject'],
        'year': pending['year'], 'folder': str(folder), 'picked': 0, 'downloaded': 0,
        'already_present': 0, 'filtered_out': {},
        'skipped': {'video_not_ready': 0, 'download_failed': 0}, 'warnings': [],
    }
    manifest = library.load_manifest(folder)  # a corrupt manifest fails before the session is used
    _remove_stale_parts(folder)
    try:
        done = _wait_for_done(token_fn, session_id, wait, now, sleep)
    except Failure as e:
        if e.code == 'SESSION_EXPIRED':
            _remove_pending(session_id)
        raise
    if not done:
        return summary  # session kept for the next fetch; nothing written
    try:
        items = picker.list_items(token_fn(), session_id)
    except Failure as e:
        if e.code == 'SESSION_EXPIRED':
            _remove_pending(session_id)
        raise
    try:
        _download_all(items, pending, folder, manifest, summary, token_fn)
    finally:
        _remove_pending(session_id)
        try:
            picker.delete_session(token_fn(), session_id)
        except Failure:
            summary['warnings'].append('SESSION_NOT_DELETED')
    summary['status'] = 'ok'
    return summary


def _download_all(items: list[dict], pending: dict, folder: Path, manifest: dict, summary: dict,
                  token_fn) -> None:
    session_id, tz, filters = pending['session'], pending['tz'], pending['filters']
    summary['picked'] = len(items)
    library.year_dir(pending['out_root'], pending['subject'], pending['year'])
    media, thumbs = folder / library.MEDIA_DIR, folder / library.THUMBS_DIR
    manifest.setdefault('subject', pending['subject'])
    manifest.setdefault('year', pending['year'])
    manifest.setdefault('tz', pending['tz_name'])
    entries = manifest['items']
    used = {Path(e['file']).name for e in entries.values() if isinstance(e, dict) and isinstance(e.get('file'), str)}
    used_thumbs: set[str] = set()
    base_urls = {}
    relisted: set[str] = set()

    for item in items:
        item_id = item.get('id')
        media_file = item.get('mediaFile') if isinstance(item.get('mediaFile'), dict) else {}
        filename = media_file.get('filename') if isinstance(media_file.get('filename'), str) else ''
        if not isinstance(item_id, str) or not item_id:
            summary['skipped']['download_failed'] += 1
            summary['warnings'].append(f'BAD_ITEM:{filename}')
            continue
        old = entries.get(item_id)
        old_file = _inside(folder, old.get('file')) if isinstance(old, dict) else None
        if old_file is not None and old_file.is_file():
            summary['already_present'] += 1
            continue
        reason = library.filter_reason(item, filters, tz)
        if reason is not None:
            summary['filtered_out'][reason] = summary['filtered_out'].get(reason, 0) + 1
            continue
        is_video = item.get('type') == 'VIDEO'
        if is_video and not _ready_video(item):
            summary['skipped']['video_not_ready'] += 1
            continue
        base_urls.setdefault(item_id, media_file.get('baseUrl'))

        dest = None
        while True:
            dest = _fresh_path(media, filename, used)
            try:
                picker.download(token_fn(), base_urls[item_id], 'video' if is_video else 'photo', dest)
                break
            except Failure as e:
                if e.code == 'BASEURL_EXPIRED' and item_id not in relisted:
                    relisted.add(item_id)
                    for fresh in picker.list_items(token_fn(), session_id):
                        fresh_media = fresh.get('mediaFile') if isinstance(fresh.get('mediaFile'), dict) else {}
                        if isinstance(fresh.get('id'), str):
                            base_urls[fresh['id']] = fresh_media.get('baseUrl')
                    continue
                summary['skipped']['download_failed'] += 1
                summary['warnings'].append(f'{e.code}:{filename}')
                dest = None
                break
        if dest is None:
            continue

        thumb_path = _fresh_path(thumbs, library.thumb_name(item_id), used_thumbs)
        try:
            picker.download(token_fn(), base_urls[item_id], 'thumb', thumb_path)
            thumb = f'{library.THUMBS_DIR}/{thumb_path.name}'
        except Failure:
            thumb = None
            summary['warnings'].append(f'THUMB_MISSING:{filename}')
        entries[item_id] = _entry(item, f'{library.MEDIA_DIR}/{dest.name}', thumb, session_id, tz)
        library.save_manifest(folder, manifest)  # after every item: an interrupt loses at most one
        summary['downloaded'] += 1
