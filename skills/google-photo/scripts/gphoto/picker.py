"""Google Photos Picker API client: sessions, picked items and byte downloads.

JSON calls go through `auth.http_json` (no redirects). `download` streams through `auth._open`
and follows at most `_MAX_REDIRECTS` redirects, only to https Google hosts. URLs (including
`baseUrl`s), tokens and bodies never reach an exception message, stdout or stderr.
"""
from __future__ import annotations

import http.client
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

from . import auth
from .errors import Failure

API = 'https://photospicker.googleapis.com/v1'
PAGE_SIZE = 100
_SUFFIX = {'photo': '=d', 'video': '=dv', 'thumb': '=w512-h512'}
_TRUSTED_SUFFIXES = ('.googleusercontent.com', '.google.com')
_MAX_REDIRECTS = 3
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_EXPIRED_STATUS = {401, 403, 404}
_ATTEMPTS = 3
_BACKOFF = (1, 2)  # seconds slept before the 2nd and 3rd attempts
_CHUNK = 1 << 20
_TIMEOUT = 60
_sleep = time.sleep  # patched in tests


# --- sessions ---------------------------------------------------------------------------------

def _session_url(session_id: str) -> str:
    return f'{API}/sessions/{quote(session_id, safe="")}'


def _session_call(method: str, url: str, token: str) -> dict:
    """A session-scoped call; a gone or closed session becomes SESSION_EXPIRED."""
    try:
        return auth.http_json(method, url, token=token)
    except auth.HttpFailure as e:
        if e.status == 404 or (e.status == 400 and e.api_status == 'FAILED_PRECONDITION'):
            raise Failure('SESSION_EXPIRED') from None
        raise


def create_session(token: str, max_items: int = 2000) -> dict:
    """Create a picking session; returns it (`id`, `pickerUri`, `expireTime`, `pollingConfig`)."""
    session = auth.http_json('POST', f'{API}/sessions', token=token,
                             body={'pickingConfig': {'maxItemCount': str(max_items)}})
    if not isinstance(session.get('id'), str) or not session['id'] \
            or not isinstance(session.get('pickerUri'), str):
        raise Failure('BAD_RESPONSE')
    return session


def get_session(token: str, session_id: str) -> dict:
    return _session_call('GET', _session_url(session_id), token)


def delete_session(token: str, session_id: str) -> None:
    """Delete a session; one that is already gone (404) is not an error."""
    try:
        auth.http_json('DELETE', _session_url(session_id), token=token)
    except auth.HttpFailure as e:
        if e.status != 404:
            raise


def list_items(token: str, session_id: str) -> list[dict]:
    """Every picked media item of the session, across all pages."""
    items: list[dict] = []
    seen: set[str] = set()
    page_token = None
    while True:
        query = {'sessionId': session_id, 'pageSize': PAGE_SIZE}
        if page_token:
            query['pageToken'] = page_token
        reply = _session_call('GET', f'{API}/mediaItems?{urlencode(query)}', token)
        page = reply.get('mediaItems', [])
        if not isinstance(page, list) or not all(isinstance(m, dict) for m in page):
            raise Failure('BAD_RESPONSE')
        items.extend(page)
        page_token = reply.get('nextPageToken')
        if not page_token:
            return items
        if not isinstance(page_token, str) or page_token in seen:
            raise Failure('BAD_RESPONSE')  # a repeated token would loop forever
        seen.add(page_token)


# --- download ---------------------------------------------------------------------------------

def _trusted(url: str) -> bool:
    """https on a Google host (…googleusercontent.com / …google.com), no userinfo, default port."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or '').lower()
    return (parts.scheme == 'https' and port in (None, 443) and parts.username is None
            and parts.password is None and host.endswith(_TRUSTED_SUFFIXES))


class _Retry(Exception):
    """A transient failure (network error, 5xx, truncated body) carrying the final code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fetch_once(token: str, url: str, part: Path) -> int:
    """One attempt: follow trusted redirects and stream the body into `part`."""
    for _ in range(_MAX_REDIRECTS + 1):
        if not _trusted(url):
            raise Failure('BAD_RESPONSE')  # never contact (or send the token to) another host
        request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        try:
            resp = auth._open(request, _TIMEOUT)
        except urllib.error.HTTPError as e:
            status, location = e.code, (e.headers.get('Location') if e.headers else None)
            e.close()
            if status in _REDIRECT_STATUS:
                if not location:
                    raise Failure('BAD_RESPONSE') from None
                url = urljoin(url, location)
                continue
            if status in _EXPIRED_STATUS:
                raise Failure('BASEURL_EXPIRED') from None
            code = auth.HttpFailure(status).code
            if 500 <= status <= 599:
                raise _Retry(code) from None
            raise Failure(code) from None
        except (OSError, ValueError, http.client.HTTPException):
            raise _Retry('NETWORK_ERROR') from None
        try:
            with resp, open(part, 'wb') as f:
                length = resp.headers.get('Content-Length') if resp.headers else None
                total = 0
                while chunk := resp.read(_CHUNK):
                    f.write(chunk)
                    total += len(chunk)
                f.flush()
                os.fsync(f.fileno())
        except (OSError, ValueError, http.client.HTTPException):
            raise _Retry('NETWORK_ERROR') from None
        if length is not None and length.isdigit() and int(length) != total:
            raise _Retry('NETWORK_ERROR')  # truncated body
        if total == 0:
            raise Failure('BAD_RESPONSE')
        return total
    raise Failure('BAD_RESPONSE')  # too many redirects


def download(token: str, base_url: str, kind: str, dest: Path) -> int:
    """Download a picked item's bytes to `dest` atomically; returns the byte count.

    `kind` is 'photo', 'video' or 'thumb'. The caller chooses a `dest` the skill owns.
    """
    if kind not in _SUFFIX or not isinstance(base_url, str):
        raise Failure('BAD_RESPONSE')
    url = base_url + _SUFFIX[kind]
    if not _trusted(url):
        raise Failure('BAD_RESPONSE')
    dest = Path(dest)
    part = dest.with_name(dest.name + '.part')
    try:
        for attempt in range(_ATTEMPTS):
            if attempt:
                _sleep(_BACKOFF[attempt - 1])
            try:
                n = _fetch_once(token, url, part)
            except _Retry as e:
                code = e.code
                continue
            os.replace(part, dest)
            return n
        raise Failure(code)
    finally:
        part.unlink(missing_ok=True)
