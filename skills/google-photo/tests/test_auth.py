import base64
import hashlib
import http.server
import io
import json
import stat
import threading
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from gphoto import auth
from gphoto.errors import Failure, MESSAGES, message_for

SECRET = 'client-secret-value'
CLIENT = {
    'client_id': 'id.apps.googleusercontent.com',
    'client_secret': SECRET,
    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
    'token_uri': 'https://oauth2.googleapis.com/token',
}
# A proxy-less opener, so the fake browser always reaches the loopback server directly.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url):
    try:
        _LOCAL.open(url, timeout=5).read()
    except OSError:
        pass


@pytest.fixture
def tmp_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(tmp_path / 'cfg'))
    monkeypatch.delenv('GOOGLE_PHOTO_CLIENT_SECRET', raising=False)
    return tmp_path / 'cfg'


@pytest.fixture
def client():
    return dict(CLIENT)


class _Resp(io.BytesIO):
    status = 200


class FakeHTTP:
    """Stands in for auth._open: answers from a queue and records every request."""

    def __init__(self):
        self.requests = []
        self.replies = []

    def reply(self, body=None, status=200, raw=None):
        data = raw if raw is not None else (b'' if body is None else json.dumps(body).encode())
        self.replies.append((status, data))

    def __call__(self, request, timeout):
        self.requests.append(request)
        if not self.replies:
            raise AssertionError('unexpected HTTP call')
        status, data = self.replies.pop(0)
        if status >= 300:
            raise urllib.error.HTTPError(request.full_url, status, 'err', {}, io.BytesIO(data))
        return _Resp(data)

    def form(self, i=-1):
        return {k: v[0] for k, v in parse_qs(self.requests[i].data.decode()).items()}


@pytest.fixture
def fake(monkeypatch):
    f = FakeHTTP()
    monkeypatch.setattr(auth, '_open', f)
    return f


def _redirect(query_for):
    """A fake browser that GETs the loopback redirect_uri with the query query_for(q) builds."""
    seen = {}

    def browser(url):
        q = parse_qs(urlparse(url).query)
        seen.update(q)
        query = query_for(q)
        if query is not None:
            threading.Thread(target=_get, args=(q['redirect_uri'][0] + '?' + query,)).start()
    return browser, seen


def _write_token(cfg, **tok):
    cfg.mkdir(mode=0o700, exist_ok=True)
    (cfg / 'token.json').write_text(json.dumps(tok), encoding='utf-8')


def test_messages_for_new_codes():
    for code in ('AUTH_REQUIRED', 'AUTH_DENIED', 'AUTH_TIMEOUT', 'AUTH_STATE_MISMATCH',
                 'NETWORK_ERROR', 'BAD_RESPONSE'):
        assert code in MESSAGES
    assert message_for('GOOGLE_HTTP_500') == MESSAGES['GOOGLE_HTTP_ERROR']


def test_sign_in_pkce_and_saves_token(tmp_cfg, client, fake, capsys):
    browser, seen = _redirect(lambda q: 'code=C0DE&state=' + q['state'][0])
    fake.reply({'access_token': 'A-tok', 'refresh_token': 'R-tok', 'expires_in': 3599,
                'scope': auth.SCOPE, 'token_type': 'Bearer'})
    assert auth.sign_in(client, timeout=5, open_browser=browser) is None
    assert seen['scope'] == [auth.SCOPE] and seen['code_challenge_method'] == ['S256']
    assert seen['redirect_uri'][0].startswith('http://127.0.0.1:')
    assert seen['access_type'] == ['offline'] and seen['prompt'] == ['consent']
    assert seen['response_type'] == ['code'] and seen['client_id'] == [CLIENT['client_id']]
    assert len(seen['state'][0]) >= 32 and len(seen['code_challenge'][0]) == 43
    tok = json.loads((tmp_cfg / 'token.json').read_text())
    assert set(tok) == {'refresh_token', 'access_token', 'expires_at', 'scope'}
    assert tok['refresh_token'] == 'R-tok' and tok['access_token'] == 'A-tok'
    assert stat.S_IMODE((tmp_cfg / 'token.json').stat().st_mode) == 0o600
    req = fake.requests[-1]
    assert req.full_url == CLIENT['token_uri'] and req.get_method() == 'POST'
    form = fake.form()
    assert form['grant_type'] == 'authorization_code' and form['code'] == 'C0DE'
    assert form['redirect_uri'] == seen['redirect_uri'][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest())
    assert challenge.rstrip(b'=').decode() == seen['code_challenge'][0]  # PKCE S256
    captured = capsys.readouterr()
    assert captured.out == ''
    lines = captured.err.splitlines()
    assert len(lines) == 1  # only the notice: the loopback server logs nothing
    notice = json.loads(lines[0])
    assert notice['notice'] == 'open this URL to sign in' and notice['url'].startswith(CLIENT['auth_uri'])
    assert 'C0DE' not in captured.err and SECRET not in captured.err and 'R-tok' not in captured.err


def test_sign_in_wrong_state_rejected(tmp_cfg, client, fake):
    browser, _ = _redirect(lambda q: 'code=C0DE&state=x')
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=1, open_browser=browser)
    assert e.value.code == 'AUTH_STATE_MISMATCH'
    assert fake.requests == [] and not (tmp_cfg / 'token.json').exists()


def test_sign_in_accepts_first_matching_state(tmp_cfg, client, fake):
    def browser(url):
        q = parse_qs(urlparse(url).query)
        base = q['redirect_uri'][0]

        def go():
            _get(base + 'favicon.ico')
            _get(base + '?code=BAD&state=x')
            _get(base + '?code=GOOD&state=' + q['state'][0])
        threading.Thread(target=go).start()
    fake.reply({'access_token': 'A', 'refresh_token': 'R', 'expires_in': 3599, 'scope': auth.SCOPE})
    auth.sign_in(client, timeout=5, open_browser=browser)
    assert fake.form()['code'] == 'GOOD'


def test_sign_in_denied(tmp_cfg, client, fake):
    browser, _ = _redirect(lambda q: 'error=access_denied&state=' + q['state'][0])
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=5, open_browser=browser)
    assert e.value.code == 'AUTH_DENIED' and fake.requests == []


def test_sign_in_timeout(tmp_cfg, client, fake):
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=0.5, open_browser=lambda url: None)
    assert e.value.code == 'AUTH_TIMEOUT'


def test_sign_in_browser_failure_still_waits(tmp_cfg, client, fake):
    def browser(url):
        raise RuntimeError('no browser')
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=0.5, open_browser=browser)
    assert e.value.code == 'AUTH_TIMEOUT'


def test_sign_in_bad_token_response(tmp_cfg, client, fake):
    browser, _ = _redirect(lambda q: 'code=C&state=' + q['state'][0])
    fake.reply({'access_token': 'A', 'expires_in': 3599})  # no refresh token
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=5, open_browser=browser)
    assert e.value.code == 'BAD_RESPONSE' and not (tmp_cfg / 'token.json').exists()


def test_sign_in_scope_not_granted(tmp_cfg, client, fake):
    browser, _ = _redirect(lambda q: 'code=C&state=' + q['state'][0])
    fake.reply({'access_token': 'A', 'refresh_token': 'R', 'expires_in': 3599, 'scope': 'openid'})
    with pytest.raises(Failure) as e:
        auth.sign_in(client, timeout=5, open_browser=browser)
    assert e.value.code == 'AUTH_DENIED' and not (tmp_cfg / 'token.json').exists()


def test_access_token_cached(tmp_cfg, client, fake):
    _write_token(tmp_cfg, refresh_token='R', access_token='A', expires_at=1000 + 600, scope=auth.SCOPE)
    assert auth.access_token(client, now=lambda: 1000) == 'A'
    assert fake.requests == []


def test_access_token_refresh(tmp_cfg, client, fake):
    _write_token(tmp_cfg, refresh_token='R', access_token='A', expires_at=1000 + 10, scope=auth.SCOPE)
    fake.reply({'access_token': 'A2', 'expires_in': 3599, 'scope': auth.SCOPE})
    assert auth.access_token(client, now=lambda: 1000) == 'A2'
    form = fake.form()
    assert form['grant_type'] == 'refresh_token' and form['refresh_token'] == 'R'
    assert form['client_id'] == CLIENT['client_id'] and form['client_secret'] == SECRET
    assert fake.requests[0].full_url == CLIENT['token_uri']
    tok = json.loads((tmp_cfg / 'token.json').read_text())
    assert tok == {'refresh_token': 'R', 'access_token': 'A2', 'expires_at': 1000 + 3599, 'scope': auth.SCOPE}
    assert stat.S_IMODE((tmp_cfg / 'token.json').stat().st_mode) == 0o600
    assert auth.access_token(client, now=lambda: 1000) == 'A2' and len(fake.requests) == 1


def test_access_token_refresh_rotated(tmp_cfg, client, fake):
    _write_token(tmp_cfg, refresh_token='R', access_token='A', expires_at=0, scope=auth.SCOPE)
    fake.reply({'access_token': 'A2', 'refresh_token': 'R2', 'expires_in': 3599})
    assert auth.access_token(client, now=lambda: 1000) == 'A2'
    assert json.loads((tmp_cfg / 'token.json').read_text())['refresh_token'] == 'R2'


def test_invalid_grant_removes_token(tmp_cfg, client, fake):
    _write_token(tmp_cfg, refresh_token='R', access_token='A', expires_at=0, scope=auth.SCOPE)
    fake.reply({'error': 'invalid_grant', 'error_description': 'Token has been expired or revoked.'},
               status=400)
    with pytest.raises(Failure) as e:
        auth.access_token(client, now=lambda: 1000)
    assert e.value.code == 'AUTH_REQUIRED'
    assert not (tmp_cfg / 'token.json').exists()
    assert auth.token_state() == 'missing'


def test_refresh_other_error_keeps_token(tmp_cfg, client, fake):
    _write_token(tmp_cfg, refresh_token='R', access_token='A', expires_at=0, scope=auth.SCOPE)
    fake.reply({'error': 'server_error'}, status=503)
    with pytest.raises(Failure) as e:
        auth.access_token(client, now=lambda: 1000)
    assert e.value.code == 'GOOGLE_HTTP_503'
    assert (tmp_cfg / 'token.json').exists()


def test_no_token_is_auth_required(tmp_cfg, client, fake):
    with pytest.raises(Failure) as e:
        auth.access_token(client)
    assert e.value.code == 'AUTH_REQUIRED' and fake.requests == []


def test_malformed_token_is_auth_required(tmp_cfg, client, fake):
    tmp_cfg.mkdir(mode=0o700)
    (tmp_cfg / 'token.json').write_text('{}', encoding='utf-8')
    with pytest.raises(Failure) as e:
        auth.access_token(client)
    assert e.value.code == 'AUTH_REQUIRED' and fake.requests == []
    assert (tmp_cfg / 'token.json').exists()  # not ours to delete when it was never valid


def test_token_state(tmp_cfg):
    assert auth.token_state() == 'missing'
    _write_token(tmp_cfg, refresh_token='R')
    assert auth.token_state() == 'present'


def test_http_error_never_echoes_body(fake):
    fake.reply(raw=b'{"error":"boom","leak":"R-secret-tok"}', status=500)
    with pytest.raises(Failure) as e:
        auth.http_json('POST', 'https://oauth2.googleapis.com/token', token='A-bearer', body={'x': 'y'})
    assert e.value.code == 'GOOGLE_HTTP_500'
    text = str(e.value) + repr(e.value) + ''.join(map(str, e.value.args))
    assert 'R-secret-tok' not in text and 'A-bearer' not in text and 'boom' not in text
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_http_json_request_shape(fake):
    fake.reply({'ok': 1})
    assert auth.http_json('POST', 'https://photospicker.googleapis.com/v1/sessions',
                          token='TOK', body={'a': 1}) == {'ok': 1}
    req = fake.requests[0]
    assert req.get_method() == 'POST' and json.loads(req.data) == {'a': 1}
    assert req.get_header('Authorization') == 'Bearer TOK'
    assert req.get_header('Content-type') == 'application/json'
    fake.reply(raw=b'')
    assert auth.http_json('DELETE', 'https://photospicker.googleapis.com/v1/sessions/1') == {}
    assert fake.requests[1].get_method() == 'DELETE' and fake.requests[1].get_header('Authorization') is None
    fake.reply({})
    auth.http_json('POST', 'https://oauth2.googleapis.com/token', body={'k': 'v w'}, form=True)
    assert fake.requests[2].get_header('Content-type') == 'application/x-www-form-urlencoded'
    assert fake.form() == {'k': 'v w'}


@pytest.mark.parametrize('raw', [b'not json', b'[1, 2]', b'\xff\xfe'])
def test_http_json_bad_response(fake, raw):
    fake.reply(raw=raw)
    with pytest.raises(Failure) as e:
        auth.http_json('GET', 'https://photospicker.googleapis.com/v1/x')
    assert e.value.code == 'BAD_RESPONSE'


@pytest.mark.parametrize('exc', [urllib.error.URLError('dns R-secret'), TimeoutError('t'),
                                 ConnectionResetError('c')])
def test_http_json_network_error(monkeypatch, exc):
    def boom(request, timeout):
        raise exc
    monkeypatch.setattr(auth, '_open', boom)
    with pytest.raises(Failure) as e:
        auth.http_json('GET', 'https://photospicker.googleapis.com/v1/x')
    assert e.value.code == 'NETWORK_ERROR' and 'R-secret' not in str(e.value)


def test_http_json_refuses_non_https(fake):
    with pytest.raises(Failure) as e:
        auth.http_json('GET', 'http://photospicker.googleapis.com/v1/x')
    assert e.value.code == 'BAD_RESPONSE'
    assert fake.requests == []


def test_real_open_does_not_follow_redirects(monkeypatch):
    """The real seam, against a throwaway server on 127.0.0.1 (no outside network)."""
    # the import-time opener read proxy settings from the environment; rebuild it without
    # proxies (still with _NoRedirect) so the request cannot leave the machine
    monkeypatch.setattr(auth, '_OPENER', urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                                      auth._NoRedirect))
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/elsewhere')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(('127.0.0.1', 0), H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/start')
        with pytest.raises(urllib.error.HTTPError) as e:
            auth._open(req, 5)
        assert e.value.code == 302 and hits == ['/start']
    finally:
        server.shutdown()
        server.server_close()


def test_cli_auth_stdout_has_no_secrets(cli, tmp_cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, 'remote_reason', lambda *a, **k: None)
    tmp_cfg.mkdir(mode=0o700)
    (tmp_cfg / 'client_secret.json').write_text(json.dumps({'installed': CLIENT}), encoding='utf-8')
    calls = []

    def fake_sign_in(client, *a, **k):
        calls.append(client)
        _write_token(tmp_cfg, refresh_token='R-tok', access_token='A-tok', expires_at=0, scope=auth.SCOPE)
    monkeypatch.setattr(cli.auth, 'sign_in', fake_sign_in)
    assert cli.main(['auth']) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {'status': 'ok', 'signed_in': True}
    for s in ('A-tok', 'R-tok', SECRET):
        assert s not in captured.out and s not in captured.err
    assert calls[0]['client_id'] == CLIENT['client_id']
    assert cli.main(['check']) == 0
    assert json.loads(capsys.readouterr().out)['token'] == 'present'


def test_cli_auth_failure_and_check_uses_token_state(cli, tmp_cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, 'remote_reason', lambda *a, **k: None)
    assert cli.main(['auth']) == 2
    assert json.loads(capsys.readouterr().err)['error'] == 'CLIENT_SECRET_MISSING'
    monkeypatch.setattr(cli.auth, 'token_state', lambda: 'present')
    assert cli.main(['check']) == 0
    assert json.loads(capsys.readouterr().out)['token'] == 'present'


def test_loopback_server_handler_errors_are_silent(monkeypatch, capsys):
    server = auth._loopback_server('state')

    def broken(self):
        raise BrokenPipeError(32, 'Broken pipe')
    monkeypatch.setattr(server.RequestHandlerClass, 'do_GET', broken)
    port = server.server_port

    def client():
        import socket
        with socket.create_connection(('127.0.0.1', port), timeout=5) as s:
            s.sendall(b'GET /?code=x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
            try:
                s.recv(10)
            except OSError:
                pass
    t = threading.Thread(target=client, daemon=True)
    t.start()
    try:
        server.timeout = 5
        server.handle_request()
    finally:
        server.server_close()
        t.join(5)
    captured = capsys.readouterr()
    assert captured.err == '' and captured.out == ''
    assert server.result is None
