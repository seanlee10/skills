"""OAuth sign-in (loopback redirect + PKCE), token storage and refresh, and the one HTTP seam.

Every network call in the skill goes through `_open`. Tokens, codes, the client secret and
response bodies never reach an exception message, stdout or stderr.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import json
import os
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from . import config
from .errors import Failure

SCOPE = 'https://www.googleapis.com/auth/photospicker.mediaitems.readonly'
_REFRESH_MARGIN = 60  # seconds of validity an access token must still have to be reused
_OAUTH_ERROR = re.compile(r'[a-z_]{1,64}')
_API_STATUS = re.compile(r'[A-Z_]{1,64}')
_PAGE = (b'<!doctype html><meta charset="utf-8"><title>Google Photos sign-in</title>'
         b'<p>You can close this tab and return to the terminal.</p>')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx surfaces as HTTPError instead of being followed


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(request: urllib.request.Request, timeout: float):
    """The single network seam (patched in tests). Never follows redirects."""
    return _OPENER.open(request, timeout=timeout)


class HttpFailure(Failure):
    """GOOGLE_HTTP_<status>.

    `oauth_error` is the OAuth `error` identifier if the body had one; `api_status` is the
    Google API `error.status` (e.g. FAILED_PRECONDITION) if the body had one.
    """

    def __init__(self, status: int, oauth_error: str | None = None, api_status: str | None = None):
        super().__init__(f'GOOGLE_HTTP_{status}' if 100 <= status <= 999 else 'GOOGLE_HTTP_ERROR')
        self.status = status
        self.oauth_error = oauth_error
        self.api_status = api_status


def _error_ids(raw: bytes) -> tuple[str | None, str | None]:
    """(OAuth `error` string, API `error.status` string) from an error body, each if well-formed."""
    try:
        err = json.loads(raw).get('error')
    except (ValueError, AttributeError):
        return None, None
    if isinstance(err, str):
        return (err if _OAUTH_ERROR.fullmatch(err) else None), None
    status = err.get('status') if isinstance(err, dict) else None
    return None, (status if isinstance(status, str) and _API_STATUS.fullmatch(status) else None)


def http_json(method: str, url: str, token: str | None = None, body: dict | None = None,
              form: bool = False, timeout: float = 60) -> dict:
    """Send one request and return the JSON object reply ({} for an empty body)."""
    if urlsplit(url).scheme != 'https':
        raise Failure('BAD_RESPONSE')
    headers = {'Accept': 'application/json'}
    data = None
    if body is not None:
        if form:
            data = urlencode(body).encode('ascii')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    failure = None
    try:
        with _open(request, timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            raw_err = e.read(65536)
        except Exception:
            raw_err = b''
        finally:
            e.close()
        failure = HttpFailure(e.code, *_error_ids(raw_err))
    except (OSError, ValueError, http.client.HTTPException):  # URLError, timeouts, resets
        failure = Failure('NETWORK_ERROR')
    if failure is not None:
        raise failure from None  # no chained exception carrying the URL or body
    if not raw.strip():
        return {}
    try:
        reply = json.loads(raw.decode('utf-8'))
    except ValueError:  # includes UnicodeDecodeError
        raise Failure('BAD_RESPONSE') from None
    if not isinstance(reply, dict):
        raise Failure('BAD_RESPONSE')
    return reply


# --- token file -------------------------------------------------------------------------------

def _token_path() -> Path:
    return config.config_dir() / 'token.json'


def token_state() -> str:
    """'present' or 'missing'; no network and no read of the file's contents."""
    return 'present' if _token_path().is_file() else 'missing'


def _save(token: dict) -> None:
    path = _token_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.token-', suffix='.tmp')  # mode 0600
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(token, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load() -> dict:
    try:
        token = json.loads(_token_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise Failure('AUTH_REQUIRED') from None
    if not isinstance(token, dict) or not isinstance(token.get('refresh_token'), str) \
            or not token['refresh_token']:
        raise Failure('AUTH_REQUIRED')
    return token


def _token_fields(reply: dict, now: float) -> tuple[str, float]:
    access, expires_in = reply.get('access_token'), reply.get('expires_in')
    if not isinstance(access, str) or not access or isinstance(expires_in, bool) \
            or not isinstance(expires_in, (int, float)):
        raise Failure('BAD_RESPONSE')
    return access, now + expires_in


# --- sign-in ----------------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


class _QuietServer(http.server.HTTPServer):
    def handle_error(self, request, client_address):
        pass  # a browser closing the connection early (BrokenPipe, reset) is not worth a traceback


def _loopback_server(expected_state: str) -> http.server.HTTPServer:
    """A one-shot server on 127.0.0.1 that keeps the first callback whose state matches."""

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 10  # a client that connects and stalls cannot hold the sign-in forever

        def do_GET(self):
            server = self.server
            query = parse_qs(urlsplit(self.path).query)
            if server.result is None and ('code' in query or 'error' in query):
                state = query.get('state', [''])[0]
                if secrets.compare_digest(state.encode(), expected_state.encode()):
                    server.result = query
                else:
                    server.mismatch = True
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(_PAGE)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(_PAGE)

        def log_message(self, format, *args):
            pass  # request lines carry the authorization code

    server = _QuietServer(('127.0.0.1', 0), Handler)
    server.result = None
    server.mismatch = False
    return server


def sign_in(client: dict, timeout: float = 300, open_browser=None) -> None:
    """Run the browser sign-in and save the token; raises Failure on denial, timeout or bad state."""
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    server = _loopback_server(state)
    try:
        redirect_uri = f'http://127.0.0.1:{server.server_port}/'
        url = client['auth_uri'] + '?' + urlencode({
            'client_id': client['client_id'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': SCOPE,
            'code_challenge': _b64url(hashlib.sha256(verifier.encode('ascii')).digest()),
            'code_challenge_method': 'S256',
            'state': state,
            'access_type': 'offline',
            'prompt': 'consent',
        })
        sys.stderr.write(json.dumps({'notice': 'open this URL to sign in', 'url': url}) + '\n')
        sys.stderr.flush()
        try:
            (open_browser if open_browser is not None else webbrowser.open)(url)  # looked up per call
        except Exception:
            pass  # the user can still open the printed URL
        deadline = time.monotonic() + timeout
        while server.result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure('AUTH_STATE_MISMATCH' if server.mismatch else 'AUTH_TIMEOUT')
            server.timeout = min(remaining, 0.25)
            server.handle_request()
        result = server.result
    finally:
        server.server_close()
    if 'error' in result:
        raise Failure('AUTH_DENIED')
    code = result['code'][0]
    now = time.time()
    reply = http_json('POST', client['token_uri'], form=True, body={
        'code': code,
        'client_id': client['client_id'],
        'client_secret': client['client_secret'],
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
        'code_verifier': verifier,
    })
    access, expires_at = _token_fields(reply, now)
    refresh = reply.get('refresh_token')
    if not isinstance(refresh, str) or not refresh:
        raise Failure('BAD_RESPONSE')
    scope = reply.get('scope', SCOPE)
    if not isinstance(scope, str) or SCOPE not in scope.split():
        raise Failure('AUTH_DENIED')  # the user unticked the Photos permission
    _save({'refresh_token': refresh, 'access_token': access, 'expires_at': expires_at, 'scope': scope})


def access_token(client: dict, now=time.time) -> str:
    """A valid access token: the cached one if it has > 60 s left, else a refreshed one."""
    token = _load()
    cached, expires_at = token.get('access_token'), token.get('expires_at')
    if isinstance(cached, str) and cached and isinstance(expires_at, (int, float)) \
            and not isinstance(expires_at, bool) and expires_at - now() > _REFRESH_MARGIN:
        return cached
    started = now()
    try:
        reply = http_json('POST', client['token_uri'], form=True, body={
            'client_id': client['client_id'],
            'client_secret': client['client_secret'],
            'refresh_token': token['refresh_token'],
            'grant_type': 'refresh_token',
        })
    except HttpFailure as e:
        if e.oauth_error == 'invalid_grant':  # expired or revoked: a fresh sign-in is needed
            _token_path().unlink(missing_ok=True)
            raise Failure('AUTH_REQUIRED') from None
        raise
    access, new_expires_at = _token_fields(reply, started)
    refresh = reply.get('refresh_token')
    scope = reply.get('scope')
    _save({
        'refresh_token': refresh if isinstance(refresh, str) and refresh else token['refresh_token'],
        'access_token': access,
        'expires_at': new_expires_at,
        'scope': scope if isinstance(scope, str) else token.get('scope', SCOPE),
    })
    return access
