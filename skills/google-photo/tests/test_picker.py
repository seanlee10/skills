import io
import json
import socket
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from gphoto import auth, picker
from gphoto.errors import Failure, MESSAGES, message_for

BODY = b'\xff\xd8 image bytes ' * 1000
BASE = 'https://lh3.googleusercontent.com/abc'
TOKEN = 'A-tok-secret'


class _Resp(io.BytesIO):
    status = 200

    def __init__(self, data, headers=None, fail_after=None):
        super().__init__(data)
        self.headers = headers or {}
        self._fail_after = fail_after

    def read(self, n=-1):
        if self._fail_after is not None and self.tell() >= self._fail_after:
            raise ConnectionResetError('reset')
        if self._fail_after is not None and n != -1:
            n = min(n, self._fail_after - self.tell()) or 1
        return super().read(n)


class FakeHTTP:
    """Stands in for auth._open: answers from a queue and records every request."""

    def __init__(self):
        self.requests = []
        self.replies = []

    def reply(self, body=None, status=200, raw=None, headers=None, fail_after=None):
        data = raw if raw is not None else (b'' if body is None else json.dumps(body).encode())
        self.replies.append((status, data, headers or {}, fail_after))

    def fail(self, exc):
        self.replies.append(exc)

    def __call__(self, request, timeout):
        self.requests.append(request)
        if not self.replies:
            raise AssertionError('unexpected HTTP call')
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, data, headers, fail_after = item
        if status >= 300:
            raise urllib.error.HTTPError(request.full_url, status, 'err', headers, io.BytesIO(data))
        return _Resp(data, headers, fail_after)

    @property
    def last_url(self):
        return self.requests[-1].full_url

    def query(self, i=-1):
        return {k: v[0] for k, v in parse_qs(urlsplit(self.requests[i].full_url).query).items()}


@pytest.fixture
def fake(monkeypatch):
    f = FakeHTTP()
    monkeypatch.setattr(auth, '_open', f)
    return f


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(picker, '_sleep', calls.append)
    return calls


def _no_leak(exc):
    text = str(exc) + repr(exc.args)
    assert 'googleusercontent' not in text and TOKEN not in text and 'http' not in text


def test_messages_for_new_codes():
    for code in ('BASEURL_EXPIRED', 'SESSION_EXPIRED'):
        assert message_for(code) == MESSAGES[code]
        assert 'http' not in MESSAGES[code]


# --- sessions ---------------------------------------------------------------------------------

def test_create_session_body(fake):
    session = {'id': 'S1', 'pickerUri': 'https://photos.google.com/picker/x',
               'expireTime': '2026-10-21T10:00:00Z', 'pollingConfig': {'pollInterval': '5s'}}
    fake.reply(session)
    assert picker.create_session(TOKEN) == session
    req = fake.requests[0]
    assert picker.API == 'https://photospicker.googleapis.com/v1'
    assert req.get_method() == 'POST' and req.full_url == picker.API + '/sessions'
    assert json.loads(req.data) == {'pickingConfig': {'maxItemCount': '2000'}}
    assert req.get_header('Authorization') == 'Bearer ' + TOKEN


def test_create_session_max_items(fake):
    fake.reply({'id': 'S1', 'pickerUri': 'https://photos.google.com/picker/x'})
    picker.create_session(TOKEN, max_items=50)
    assert json.loads(fake.requests[0].data) == {'pickingConfig': {'maxItemCount': '50'}}


def test_create_session_bad_reply(fake):
    fake.reply({'pickerUri': 'https://photos.google.com/picker/x'})  # no id
    with pytest.raises(Failure) as e:
        picker.create_session(TOKEN)
    assert e.value.code == 'BAD_RESPONSE'


def test_get_session(fake):
    fake.reply({'id': 'S/1', 'mediaItemsSet': True})
    assert picker.get_session(TOKEN, 'S/1')['mediaItemsSet'] is True
    req = fake.requests[0]
    assert req.get_method() == 'GET' and req.full_url == picker.API + '/sessions/S%2F1'
    assert req.get_header('Authorization') == 'Bearer ' + TOKEN


@pytest.mark.parametrize('status,body', [
    (404, {'error': {'code': 404, 'status': 'NOT_FOUND'}}),
    (400, {'error': {'code': 400, 'status': 'FAILED_PRECONDITION'}}),
])
def test_get_session_expired(fake, status, body):
    fake.reply(body, status=status)
    with pytest.raises(Failure) as e:
        picker.get_session(TOKEN, 'S1')
    assert e.value.code == 'SESSION_EXPIRED'


def test_get_session_other_400_kept(fake):
    fake.reply({'error': {'code': 400, 'status': 'INVALID_ARGUMENT'}}, status=400)
    with pytest.raises(Failure) as e:
        picker.get_session(TOKEN, 'S1')
    assert e.value.code == 'GOOGLE_HTTP_400'


def test_delete_session(fake):
    fake.reply({})
    assert picker.delete_session(TOKEN, 'S1') is None
    req = fake.requests[0]
    assert req.get_method() == 'DELETE' and req.full_url == picker.API + '/sessions/S1'


def test_delete_session_404_ignored(fake):
    fake.reply({'error': {'code': 404}}, status=404)
    assert picker.delete_session(TOKEN, 'S1') is None


def test_delete_session_other_error_raised(fake):
    fake.reply(status=500)
    with pytest.raises(Failure) as e:
        picker.delete_session(TOKEN, 'S1')
    assert e.value.code == 'GOOGLE_HTTP_500'


# --- list_items -------------------------------------------------------------------------------

def test_list_items_paginates(fake):
    fake.reply({'mediaItems': [{'id': '1'}, {'id': '2'}], 'nextPageToken': 'T'})
    fake.reply({'mediaItems': [{'id': '3'}]})
    assert [m['id'] for m in picker.list_items(TOKEN, 'S1')] == ['1', '2', '3']
    assert len(fake.requests) == 2
    first, second = fake.query(0), fake.query(1)
    assert urlsplit(fake.requests[0].full_url).path == '/v1/mediaItems'
    assert first == {'sessionId': 'S1', 'pageSize': '100'}
    assert second == {'sessionId': 'S1', 'pageSize': '100', 'pageToken': 'T'}
    assert all(r.get_header('Authorization') == 'Bearer ' + TOKEN for r in fake.requests)


def test_list_items_empty(fake):
    fake.reply({})
    assert picker.list_items(TOKEN, 'S1') == []


def test_list_items_loop_guard(fake):
    fake.reply({'mediaItems': [{'id': '1'}], 'nextPageToken': 'T'})
    fake.reply({'mediaItems': [{'id': '2'}], 'nextPageToken': 'T'})
    with pytest.raises(Failure) as e:
        picker.list_items(TOKEN, 'S1')
    assert e.value.code == 'BAD_RESPONSE' and len(fake.requests) == 2


def test_list_items_bad_shape(fake):
    fake.reply({'mediaItems': {'id': '1'}})
    with pytest.raises(Failure) as e:
        picker.list_items(TOKEN, 'S1')
    assert e.value.code == 'BAD_RESPONSE'


def test_list_items_expired(fake):
    fake.reply({'error': {'code': 400, 'status': 'FAILED_PRECONDITION'}}, status=400)
    with pytest.raises(Failure) as e:
        picker.list_items(TOKEN, 'S1')
    assert e.value.code == 'SESSION_EXPIRED'


# --- download ---------------------------------------------------------------------------------

@pytest.mark.parametrize('kind,suffix', [('photo', '=d'), ('video', '=dv'), ('thumb', '=w512-h512')])
def test_download_suffix_and_atomic(fake, tmp_path, kind, suffix):
    fake.reply(raw=BODY)
    n = picker.download(TOKEN, BASE, kind, tmp_path / 'x.jpg')
    assert n == len(BODY)
    assert fake.last_url == BASE + suffix and (tmp_path / 'x.jpg').read_bytes() == BODY
    assert fake.requests[0].get_header('Authorization') == 'Bearer ' + TOKEN
    assert not list(tmp_path.glob('*.part'))


def test_download_unknown_kind(fake, tmp_path):
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'raw', tmp_path / 'x.jpg')
    assert e.value.code == 'BAD_RESPONSE' and fake.requests == []


@pytest.mark.parametrize('base', [
    'http://lh3.googleusercontent.com/abc',      # not https
    'https://lh3.example/abc',                   # not a Google host
    'https://evilgoogleusercontent.com/abc',     # suffix without the dot
    'https://lh3.googleusercontent.com.evil.example/abc',
    'https://user@lh3.googleusercontent.com/abc',
    'file:///etc/passwd',
])
def test_download_refuses_untrusted_base(fake, tmp_path, base):
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, base, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'BAD_RESPONSE' and fake.requests == []
    _no_leak(e.value)
    assert list(tmp_path.iterdir()) == []


def test_download_retries_5xx_then_ok(fake, tmp_path, sleeps):
    fake.reply(status=503)
    fake.reply(status=503)
    fake.reply(raw=BODY)
    assert picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg') == len(BODY)
    assert len(fake.requests) == 3 and sleeps == [1, 2]
    assert (tmp_path / 'x.jpg').read_bytes() == BODY


def test_download_5xx_exhausted(fake, tmp_path, sleeps):
    for _ in range(3):
        fake.reply(status=500)
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'GOOGLE_HTTP_500' and len(fake.requests) == 3 and sleeps == [1, 2]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('status', [401, 403, 404])
def test_download_403_is_expired_no_retry(fake, tmp_path, sleeps, status):
    fake.reply(status=status)
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'BASEURL_EXPIRED' and len(fake.requests) == 1 and sleeps == []
    _no_leak(e.value)
    assert list(tmp_path.iterdir()) == []


def test_download_failure_leaves_no_part(fake, tmp_path, sleeps):
    fake.fail(urllib.error.URLError('down'))
    fake.fail(socket.timeout('timed out'))
    fake.reply(raw=BODY, fail_after=100)  # connection reset mid-body
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'NETWORK_ERROR' and len(fake.requests) == 3 and sleeps == [1, 2]
    assert e.value.__cause__ is None
    assert e.value.__context__ is None or e.value.__suppress_context__
    _no_leak(e.value)
    assert list(tmp_path.iterdir()) == []


def test_download_mid_body_failure_then_ok(fake, tmp_path):
    fake.reply(raw=BODY, fail_after=100)
    fake.reply(raw=BODY)
    assert picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg') == len(BODY)
    assert (tmp_path / 'x.jpg').read_bytes() == BODY and len(fake.requests) == 2


def test_download_short_body_is_retried(fake, tmp_path):
    fake.reply(raw=BODY[:10], headers={'Content-Length': str(len(BODY))})
    fake.reply(raw=BODY, headers={'Content-Length': str(len(BODY))})
    assert picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg') == len(BODY)
    assert len(fake.requests) == 2


def test_download_empty_body(fake, tmp_path):
    fake.reply(raw=b'')
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'BAD_RESPONSE' and list(tmp_path.iterdir()) == []


# --- redirects (R2) ---------------------------------------------------------------------------

def test_download_follows_google_redirects(fake, tmp_path):
    fake.reply(status=302, headers={'Location': 'https://video.google.com/v1'})
    fake.reply(status=307, headers={'Location': '/v2'})  # relative to the redirecting host
    fake.reply(raw=BODY)
    assert picker.download(TOKEN, BASE, 'video', tmp_path / 'x.mp4') == len(BODY)
    urls = [r.full_url for r in fake.requests]
    assert urls == [BASE + '=dv', 'https://video.google.com/v1', 'https://video.google.com/v2']
    assert all(r.get_header('Authorization') == 'Bearer ' + TOKEN for r in fake.requests)


@pytest.mark.parametrize('location', [
    'https://evil.example/steal',
    'http://lh3.googleusercontent.com/abc',
    'https://googleusercontent.com.evil.example/x',
    '',
])
def test_download_refuses_untrusted_redirect(fake, tmp_path, sleeps, location):
    fake.reply(status=302, headers={'Location': location} if location else {})
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'BAD_RESPONSE' and len(fake.requests) == 1 and sleeps == []
    _no_leak(e.value)
    assert list(tmp_path.iterdir()) == []


def test_download_redirect_limit(fake, tmp_path):
    for i in range(4):
        fake.reply(status=302, headers={'Location': f'https://lh{i}.googleusercontent.com/r'})
    with pytest.raises(Failure) as e:
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    assert e.value.code == 'BAD_RESPONSE' and len(fake.requests) == 4  # initial + 3 redirects
    assert list(tmp_path.iterdir()) == []


def test_download_never_prints(fake, tmp_path, capsys):
    fake.reply(status=403)
    with pytest.raises(Failure):
        picker.download(TOKEN, BASE, 'photo', tmp_path / 'x.jpg')
    out = capsys.readouterr()
    assert out.out == '' and out.err == ''
