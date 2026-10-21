import json
import os
import stat

import pytest

from gphoto import auth, config, fetch, library, picker
from gphoto.errors import Failure, MESSAGES, message_for

TOKEN = 'ya29.fetch-test-access-token'
PICKER_URI = 'https://photos.google.com/picker/abc123'


def photo(item_id, create, filename, w=4000, h=3000):
    return {'id': item_id, 'createTime': create, 'type': 'PHOTO',
            'mediaFile': {'filename': filename, 'mimeType': 'image/jpeg', 'mediaFileMetadata': {
                'width': w, 'height': h, 'cameraMake': 'Apple', 'cameraModel': 'iPhone 15',
                'photoMetadata': {}}}}


def video(item_id, create, filename, status='READY'):
    return {'id': item_id, 'createTime': create, 'type': 'VIDEO',
            'mediaFile': {'filename': filename, 'mimeType': 'video/mp4', 'mediaFileMetadata': {
                'width': 1920, 'height': 1080, 'cameraMake': 'Apple', 'cameraModel': 'iPhone 15',
                'videoMetadata': {'fps': 30, 'processingStatus': status}}}}


class Env:
    def __init__(self, tmp_path, monkeypatch, cli, capsys):
        self.cli, self.capsys = cli, capsys
        self.cfg = tmp_path / 'cfg'
        self.out_root = tmp_path / 'lib'
        self.folder = self.out_root / 'Mia' / '2026'
        self.media = self.folder / 'media'
        self.thumbs = self.folder / '.thumbs'
        monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(self.cfg))
        monkeypatch.delenv('GOOGLE_PHOTO_CLIENT_SECRET', raising=False)
        monkeypatch.delenv('TZ', raising=False)
        monkeypatch.setattr(config, 'remote_reason', lambda *a, **k: None)
        monkeypatch.setattr(config, 'load_client', lambda: {'client_secret': 'client-secret-xyz'})
        monkeypatch.setattr(auth, 'access_token', lambda client, now=None: TOKEN)
        self.n_sessions = 0
        self.session = None
        self.items = {}           # session id -> picked items
        self.items_set = {}       # session id -> mediaItemsSet
        self.generation = 0       # bumps on every list_items (fresh baseUrls)
        self.list_calls = 0
        self.downloads = []       # (kind, dest name, base_url)
        self.deleted_sessions = []
        self.on_download = None   # hook(kind, base_url, dest) that may raise
        self.get_session_error = None
        monkeypatch.setattr(picker, 'create_session', self._create)
        monkeypatch.setattr(picker, 'get_session', self._get)
        monkeypatch.setattr(picker, 'list_items', self._list)
        monkeypatch.setattr(picker, 'delete_session', self._delete)
        monkeypatch.setattr(picker, 'download', self._download)

    # --- fake picker --------------------------------------------------------------------------
    def _create(self, token, max_items=2000):
        assert token == TOKEN
        self.n_sessions += 1
        sid = f'sess-{self.n_sessions}'
        self.items[sid], self.items_set[sid] = [], False
        return {'id': sid, 'pickerUri': PICKER_URI, 'expireTime': '2099-01-01T00:00:00Z',
                'pollingConfig': {'pollInterval': '5s', 'timeoutIn': '1799s'}}

    def _get(self, token, sid):
        assert token == TOKEN
        if self.get_session_error:
            raise Failure(self.get_session_error)
        return {'id': sid, 'mediaItemsSet': self.items_set[sid], 'expireTime': '2099-01-01T00:00:00Z',
                'pollingConfig': {'pollInterval': '5s', 'timeoutIn': '1799s'}}

    def _list(self, token, sid):
        assert token == TOKEN and self.items_set[sid]
        self.list_calls += 1
        self.generation += 1
        out = []
        for item in self.items[sid]:
            item = json.loads(json.dumps(item))
            item['mediaFile']['baseUrl'] = f'https://lh3.googleusercontent.com/{item["id"]}-g{self.generation}'
            out.append(item)
        return out

    def _delete(self, token, sid):
        self.deleted_sessions.append(sid)

    def _download(self, token, base_url, kind, dest):
        assert token == TOKEN and not os.path.lexists(dest)
        self.downloads.append((kind, dest.name, base_url))
        if self.on_download:
            self.on_download(kind, base_url, dest)
        dest.write_bytes(f'{kind}:{base_url}'.encode())
        return 10

    # --- helpers ------------------------------------------------------------------------------
    def run(self, *argv):
        code = self.cli.main(list(argv))
        captured = self.capsys.readouterr()
        self.last_out, self.last_err = captured.out, captured.err
        if code == 0:
            assert captured.err == ''
            return json.loads(captured.out)
        assert captured.out == ''
        err = json.loads(captured.err)
        assert err['message'] == message_for(err['error'])
        return err['error']

    def start(self, *extra):
        out = self.run('start', '--subject', 'Mia', '--year', '2026', '--out-root', str(self.out_root),
                       '--tz', 'Asia/Seoul', *extra)
        assert isinstance(out, dict), out
        self.session = out['session']
        return out

    def pick(self, items, sid=None):
        sid = sid or self.start()['session']
        self.items[sid], self.items_set[sid] = list(items), True
        return sid

    def fetch(self, *extra):
        s = self.run('fetch', '--wait', '0', *extra)
        if isinstance(s, dict) and s['status'] == 'ok':
            accounted = (s['downloaded'] + s['already_present'] + sum(s['filtered_out'].values())
                         + sum(s['skipped'].values()))
            assert s['picked'] == accounted
        return s

    def pending_files(self):
        d = self.cfg / 'sessions'
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def manifest(self):
        return json.loads((self.folder / 'manifest.json').read_text(encoding='utf-8'))


@pytest.fixture
def env(tmp_path, monkeypatch, cli, capsys):
    return Env(tmp_path, monkeypatch, cli, capsys)


A = photo('a', '2026-04-18T10:38:58Z', 'IMG.jpg')
B_OLD = photo('b', '2025-06-01T00:00:00Z', 'OLD.jpg')
C_PROC = video('c', '2026-05-24T06:12:52Z', 'V.mp4', status='PROCESSING')
D = photo('d', '2026-08-15T05:51:27Z', 'IMG.jpg')
E = photo('e', '2026-09-01T03:00:00Z', 'E.jpg')


# ---- error codes -------------------------------------------------------------------------

def test_new_codes_have_messages():
    for code in ('NO_PENDING_SESSION', 'AMBIGUOUS_PENDING_SESSION', 'PENDING_SESSION_CORRUPT'):
        assert message_for(code) == MESSAGES[code]


# ---- start -------------------------------------------------------------------------------

def test_start_writes_pending_0600_and_prints_link(env):
    out = env.start('--from', '2026-03-01', '--camera', 'iphone')
    assert out['status'] == 'ok' and out['picker_uri'] == PICKER_URI and out['search'] == 'Mia'
    assert out['session'] == 'sess-1' and out['expires'] == '2099-01-01T00:00:00Z'
    assert 'select-all' in out['instructions'] and 'Done' in out['instructions']
    assert TOKEN not in env.last_out
    path = env.cfg / 'sessions' / 'sess-1.json'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    pending = json.loads(path.read_text(encoding='utf-8'))
    assert set(pending) == {'session', 'subject', 'year', 'out_root', 'tz', 'filters', 'created'}
    assert (pending['session'], pending['subject'], pending['year'], pending['tz']) == \
        ('sess-1', 'Mia', 2026, 'Asia/Seoul')
    assert pending['out_root'] == str(env.out_root)
    assert pending['filters']['date_from'] == '2026-03-01' and pending['filters']['camera'] == 'iphone'
    assert TOKEN not in path.read_text(encoding='utf-8')
    assert not env.folder.exists()  # start writes nothing into the library


def test_start_opens_picker_link_after_pending_written(env, monkeypatch):
    import webbrowser
    seen = []

    def opener(url):
        seen.append((url, env.pending_files()))
        return True

    monkeypatch.setattr(webbrowser, 'open', opener)
    out = env.start()
    assert seen == [(PICKER_URI, ['sess-1.json'])]  # once, exact link, pending file already there
    assert out['warnings'] == [] and out['picker_uri'] == PICKER_URI


def test_start_no_browser_skips_opening(env, browser_calls):
    out = env.start('--no-browser')
    assert browser_calls == [] and out['warnings'] == [] and out['picker_uri'] == PICKER_URI


@pytest.mark.parametrize('result', ['raise', False])
def test_start_browser_failure_is_a_warning(env, monkeypatch, result):
    import webbrowser

    def opener(url):
        if result == 'raise':
            raise webbrowser.Error('no browser')
        return result

    monkeypatch.setattr(webbrowser, 'open', opener)
    out = env.start()  # exit 0
    assert out['status'] == 'ok' and out['warnings'] == ['BROWSER_NOT_OPENED']
    assert out['picker_uri'] == PICKER_URI and env.pending_files() == ['sess-1.json']


def test_start_failure_opens_no_browser(env, monkeypatch, browser_calls):
    monkeypatch.setattr(picker, 'create_session',
                        lambda token, max_items=2000: {'id': '../evil', 'pickerUri': PICKER_URI})
    assert env.run('start', '--subject', 'H', '--year', '2026') == 'BAD_RESPONSE'
    assert browser_calls == []


def test_run_start_uses_injected_opener(env, browser_calls):
    seen = []
    out = fetch.run_start('Mia', 2026, lambda: TOKEN, out_root=str(env.out_root), tz='Asia/Seoul',
                          open_browser=lambda url: seen.append(url) or True)
    assert seen == [PICKER_URI] and browser_calls == [] and out['warnings'] == []
    out = fetch.run_start('Mia', 2026, lambda: TOKEN, out_root=str(env.out_root), tz='Asia/Seoul',
                          open_browser=lambda url: pytest.fail('opened'), browser=False)
    assert out['warnings'] == []


def test_start_in_tests_never_reaches_real_browser(env, browser_calls):
    env.start()
    assert browser_calls == [PICKER_URI]  # the autouse recorder, not the real webbrowser.open


def test_start_custom_search(env):
    assert env.start('--search', 'Mia Park')['search'] == 'Mia Park'


def test_start_validates_before_network(env):
    assert env.run('start', '--subject', '..', '--year', '2026') == 'UNSAFE_SUBJECT'
    assert env.run('start', '--subject', 'H', '--year', '2026', '--from', '2025-01-01') == \
        'DATE_RANGE_OUTSIDE_YEAR'
    assert env.run('start', '--subject', 'H', '--year', '2026', '--tz', 'Mars/Base') == 'UNKNOWN_TIME_ZONE'
    assert env.run('start', '--subject', 'H', '--year', '2026', '--type', 'gif') == 'USAGE_ERROR'
    assert env.n_sessions == 0


def test_start_rejects_unsafe_session_id(env, monkeypatch):
    monkeypatch.setattr(picker, 'create_session',
                        lambda token, max_items=2000: {'id': '../evil', 'pickerUri': PICKER_URI})
    assert env.run('start', '--subject', 'H', '--year', '2026') == 'BAD_RESPONSE'
    assert env.pending_files() == []
    assert env.deleted_sessions == ['../evil']  # best effort: the unusable session is closed
    monkeypatch.setattr(picker, 'create_session',
                        lambda token, max_items=2000: {'id': 'ok-id', 'pickerUri': ''})
    assert env.run('start', '--subject', 'H', '--year', '2026') == 'BAD_RESPONSE'
    assert env.pending_files() == [] and env.deleted_sessions == ['../evil', 'ok-id']


# ---- fetch -------------------------------------------------------------------------------

def test_fetch_downloads_and_accounts(env):
    env.pick([A, B_OLD, C_PROC, D])
    s = env.fetch()
    assert s['status'] == 'ok' and s['picked'] == 4 and s['downloaded'] == 2
    assert s['filtered_out'] == {'out_of_range': 1} and s['skipped'] == {'video_not_ready': 1, 'download_failed': 0}
    assert s['already_present'] == 0 and s['warnings'] == []
    assert (s['session'], s['subject'], s['year'], s['folder']) == ('sess-1', 'Mia', 2026, str(env.folder))
    assert sorted(p.name for p in env.media.iterdir()) == ['IMG.jpg', 'IMG_2.jpg']
    assert env.deleted_sessions == [env.session] and not env.pending_files()
    m = env.manifest()
    assert set(m['items']) == {'a', 'd'}
    a = m['items']['a']
    assert a['file'] == 'media/IMG.jpg' and a['filename'] == 'IMG.jpg' and a['type'] == 'PHOTO'
    assert a['thumb'] == '.thumbs/' + library.thumb_name('a') and (env.folder / a['thumb']).is_file()
    assert a['local_time'].startswith('2026-04-18T19:38:58') and a['create_time'] == '2026-04-18T10:38:58Z'
    assert (a['width'], a['height'], a['camera_make'], a['camera_model'], a['session']) == \
        (4000, 3000, 'Apple', 'iPhone 15', 'sess-1')
    assert set(a) == {'file', 'filename', 'type', 'mime', 'create_time', 'local_time', 'width', 'height',
                      'camera_make', 'camera_model', 'fps', 'thumb', 'session'}
    assert m['items']['d']['file'] == 'media/IMG_2.jpg'
    assert (m['subject'], m['year'], m['tz']) == ('Mia', 2026, 'Asia/Seoul')
    kinds = sorted(k for k, _, _ in env.downloads)
    assert kinds == ['photo', 'photo', 'thumb', 'thumb']


def test_fetch_ready_video_downloads_as_video(env):
    env.pick([video('v', '2026-05-24T06:12:52Z', 'V.mp4')])
    s = env.fetch()
    assert s['downloaded'] == 1
    assert [k for k, _, _ in env.downloads] == ['video', 'thumb']
    assert env.manifest()['items']['v']['fps'] == 30


def test_fetch_filters_from_start(env):
    env.pick([A, D], sid=env.start('--to', '2026-06-30')['session'])
    s = env.fetch()
    assert s['downloaded'] == 1 and s['filtered_out'] == {'out_of_range': 1}


def test_fetch_rerun_adds_only_new(env):
    env.pick([A])
    assert env.fetch()['downloaded'] == 1
    env.pick([A, E])
    s = env.fetch()
    assert (s['already_present'], s['downloaded'], s['session']) == (1, 1, 'sess-2')
    assert sorted(p.name for p in env.media.iterdir()) == ['E.jpg', 'IMG.jpg']
    assert env.manifest()['items']['a']['session'] == 'sess-1'


def test_fetch_redownloads_missing_file(env):
    env.pick([A])
    env.fetch()
    (env.media / 'IMG.jpg').unlink()
    env.pick([A])
    s = env.fetch()
    assert (s['already_present'], s['downloaded']) == (0, 1)
    assert (env.folder / env.manifest()['items']['a']['file']).is_file()


def test_fetch_manifest_path_escape_is_missing(env, tmp_path):
    # The manifest is user-editable: an entry pointing outside the year folder is not trusted.
    outside = tmp_path / 'outside.jpg'
    outside.write_bytes(b'user file')
    env.pick([A])
    env.fetch()
    m = env.manifest()
    m['items']['a']['file'] = '../../../outside.jpg'
    m['items']['a']['thumb'] = '/etc/passwd'
    m['items']['x'] = {'file': 'media/\u0000bad', 'thumb': None}
    (env.folder / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
    env.pick([A])
    s = env.fetch()
    assert (s['already_present'], s['downloaded']) == (0, 1)
    entry = env.manifest()['items']['a']
    assert entry['file'].startswith('media/') and (env.folder / entry['file']).is_file()
    assert outside.read_bytes() == b'user file'


def test_fetch_never_overwrites_existing_file(env, monkeypatch):
    # A file appearing between name choice and download is never written over.
    real_unique = library.unique_name
    calls = []

    def racy_unique(media_dir, filename, used):
        name = real_unique(media_dir, filename, used)
        if not calls:
            (media_dir / name).write_bytes(b'user')  # appears right after the name was chosen
        calls.append(name)
        return name
    monkeypatch.setattr(library, 'unique_name', racy_unique)
    env.pick([A])
    s = env.fetch()
    assert s['downloaded'] == 1
    assert (env.media / 'IMG.jpg').read_bytes() == b'user'
    assert env.manifest()['items']['a']['file'] == 'media/IMG_2.jpg'


def test_fetch_waiting_keeps_session(env):
    sid = env.start()['session']
    env.items[sid] = [A]
    s = env.fetch()
    assert s['status'] == 'waiting' and s['session'] == sid and s['picked'] == 0
    assert env.pending_files() == [f'{sid}.json'] and env.deleted_sessions == []
    assert not env.folder.exists() and env.list_calls == 0


def test_fetch_polls_until_done(env):
    sid = env.start()['session']
    env.items[sid] = [A]
    clock = [1000.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
        if len(sleeps) == 2:
            env.items_set[sid] = True
    s = fetch.run_fetch(None, 60, lambda: TOKEN, now=lambda: clock[0], sleep=sleep)
    assert s['status'] == 'ok' and s['downloaded'] == 1 and sleeps == [5, 5]


def test_fetch_wait_elapses_with_injected_clock(env):
    env.start()
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds
    s = fetch.run_fetch(None, 12, lambda: TOKEN, now=lambda: clock[0], sleep=sleep)
    assert s['status'] == 'waiting' and clock[0] == 12


def test_fetch_zero_items(env):
    env.pick([])
    s = env.fetch()
    assert s['status'] == 'ok' and s['picked'] == 0 and s['downloaded'] == 0
    assert env.deleted_sessions == [env.session] and not env.pending_files()
    assert env.folder.is_dir() and not (env.folder / 'manifest.json').exists()
    assert list(env.media.iterdir()) == []


def test_fetch_session_expired(env):
    env.start()
    env.get_session_error = 'SESSION_EXPIRED'
    assert env.fetch() == 'SESSION_EXPIRED'
    assert not env.pending_files()


def test_fetch_session_expire_time_passed(env, monkeypatch):
    env.start()
    monkeypatch.setattr(picker, 'get_session', lambda token, sid: {
        'id': sid, 'mediaItemsSet': False, 'expireTime': '2001-01-01T00:00:00Z'})
    assert env.fetch() == 'SESSION_EXPIRED'
    assert not env.pending_files()


def test_fetch_other_poll_failure_keeps_pending(env):
    env.start()
    env.get_session_error = 'NETWORK_ERROR'
    assert env.fetch() == 'NETWORK_ERROR'
    assert env.pending_files() == ['sess-1.json']


def test_fetch_baseurl_expired_relists_once(env):
    env.pick([A])

    def hook(kind, base_url, dest):
        if base_url.endswith('-g1'):
            raise Failure('BASEURL_EXPIRED')
    env.on_download = hook
    s = env.fetch()
    assert env.list_calls == 2 and s['downloaded'] == 1 and s['warnings'] == []
    assert [b for k, _, b in env.downloads if k == 'photo'][-1].endswith('-g2')


def test_fetch_baseurl_expired_twice_skips(env):
    env.pick([A, E])

    def hook(kind, base_url, dest):
        if '/a-' in base_url and kind == 'photo':
            raise Failure('BASEURL_EXPIRED')
    env.on_download = hook
    s = env.fetch()
    assert s['skipped'] == {'video_not_ready': 0, 'download_failed': 1}
    assert s['downloaded'] == 1 and s['warnings'] == ['BASEURL_EXPIRED:IMG.jpg']
    assert set(env.manifest()['items']) == {'e'}
    assert env.deleted_sessions == [env.session]


def test_fetch_thumb_failure_keeps_original(env):
    env.pick([A])

    def hook(kind, base_url, dest):
        if kind == 'thumb':
            raise Failure('NETWORK_ERROR')
    env.on_download = hook
    s = env.fetch()
    assert s['downloaded'] == 1 and s['warnings'] == ['THUMB_MISSING:IMG.jpg']
    entry = env.manifest()['items']['a']
    assert entry['thumb'] is None and (env.folder / entry['file']).is_file()


def test_fetch_failure_after_listing_deletes_session(env, monkeypatch):
    env.pick([A])
    monkeypatch.setattr(library, 'save_manifest', lambda d, m: (_ for _ in ()).throw(OSError('disk full')))
    assert env.fetch() == 'OSError'
    assert env.deleted_sessions == [env.session] and not env.pending_files()


def test_fetch_interrupted_then_resumed(env):
    env.pick([A, E])

    def hook(kind, base_url, dest):
        if '/e-' in base_url and kind == 'photo':
            dest.with_name(dest.name + '.part').write_bytes(b'half')  # left behind by a hard kill
            raise KeyboardInterrupt
    env.on_download = hook
    assert env.fetch() == 'INTERRUPTED'  # Ctrl-C: a JSON failure, no traceback
    assert 'Traceback' not in env.last_err
    assert set(env.manifest()['items']) == {'a'}
    assert env.deleted_sessions == [env.session] and not env.pending_files()
    env.on_download = None
    env.downloads.clear()
    env.pick([A, E])
    s = env.fetch()
    assert not [p for p in env.media.iterdir() if p.name.endswith('.part')]
    assert (s['already_present'], s['downloaded']) == (1, 1)
    assert [n for k, n, _ in env.downloads if k == 'photo'] == ['E.jpg']
    assert set(env.manifest()['items']) == {'a', 'e'}


def test_fetch_removes_stale_part_files_at_start(env):
    env.pick([A])
    env.fetch()
    (env.media / 'x.jpg.part').write_bytes(b'half')
    (env.thumbs / 'y.jpg.part').write_bytes(b'half')
    env.start()  # nothing picked yet: the fetch only waits
    assert env.fetch()['status'] == 'waiting'
    assert not (env.media / 'x.jpg.part').exists() and not (env.thumbs / 'y.jpg.part').exists()
    assert (env.media / 'IMG.jpg').is_file()


def test_fetch_ambiguous_and_none(env):
    assert env.fetch() == 'NO_PENDING_SESSION'
    env.start()
    env.start()
    assert env.fetch() == 'AMBIGUOUS_PENDING_SESSION'
    env.items_set['sess-2'] = True
    s = env.fetch('--session', 'sess-2')
    assert s['status'] == 'ok' and s['session'] == 'sess-2'
    assert env.pending_files() == ['sess-1.json']
    assert env.fetch('--session', 'sess-9') == 'NO_PENDING_SESSION'
    assert env.fetch('--session', '../x') == 'USAGE_ERROR'


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(filters={'date_from': 'nope'}),
    lambda p: p.update(filters={'date_from': '2026-01-01', 'date_to': '2026-12-31', 'types': ['GIF']}),
    lambda p: p.update(filters=None),
    lambda p: p.update(subject='../x'),
    lambda p: p.update(year='2026'),
    lambda p: p.update(tz='Mars/Base'),
    lambda p: p.update(out_root=None),
    lambda p: p.update(session='other'),
    lambda p: p.clear(),
])
def test_fetch_corrupt_pending(env, mutate):
    env.start()
    path = env.cfg / 'sessions' / 'sess-1.json'
    pending = json.loads(path.read_text(encoding='utf-8'))
    mutate(pending)
    path.write_text(json.dumps(pending), encoding='utf-8')
    assert env.fetch() == 'PENDING_SESSION_CORRUPT'


def test_fetch_pending_not_json(env):
    env.start()
    (env.cfg / 'sessions' / 'sess-1.json').write_text('{', encoding='utf-8')
    assert env.fetch() == 'PENDING_SESSION_CORRUPT'


def test_fetch_corrupt_manifest_keeps_session(env):
    env.pick([A])
    env.folder.mkdir(parents=True)
    (env.folder / 'manifest.json').write_text('{', encoding='utf-8')
    assert env.fetch() == 'MANIFEST_CORRUPT'
    assert env.pending_files() == ['sess-1.json'] and env.list_calls == 0


def test_summary_has_no_urls_or_tokens(env):
    env.pick([A, D, video('v', '2026-05-24T06:12:52Z', 'V.mp4')])

    def hook(kind, base_url, dest):
        if kind == 'thumb' and '/v-' in base_url:
            raise Failure('BASEURL_EXPIRED')
    env.on_download = hook
    s = env.fetch()
    assert s['downloaded'] == 3
    text = env.last_out + env.last_err + (env.folder / 'manifest.json').read_text(encoding='utf-8')
    text += ''.join((env.cfg / 'sessions' / f).read_text() for f in env.pending_files())
    for needle in ('lh3.', 'googleusercontent', TOKEN, 'client-secret-xyz', 'baseUrl'):
        assert needle not in text


def test_inside_rejects_escapes(tmp_path):
    (tmp_path / 'media').mkdir()
    (tmp_path / 'media' / 'ok.jpg').write_bytes(b'x')
    assert fetch._inside(tmp_path, 'media/ok.jpg') == (tmp_path / 'media' / 'ok.jpg').resolve()
    for bad in ('../x.jpg', '/etc/passwd', 'media/\x00bad', '', None, 3, '.'):
        assert fetch._inside(tmp_path, bad) is None


def test_fetch_gets_fresh_token_for_every_call(env, monkeypatch):
    # A long wait can outlast the cached access token, so every call asks token_fn again and
    # the fake Picker accepts only the most recently issued token.
    sid = env.start()['session']
    env.items[sid] = [A]
    issued = []

    def token_fn():
        issued.append(f'tok-{len(issued) + 1}')
        return issued[-1]
    calls = []

    def accept(name, token):
        assert token == issued[-1], f'{name} got a stale token'
        calls.append(name)
    polls = [0]

    def get_session(token, s):
        accept('get_session', token)
        polls[0] += 1
        return {'id': s, 'mediaItemsSet': polls[0] >= 3,
                'pollingConfig': {'pollInterval': '5s', 'timeoutIn': '1799s'}}

    def list_items(token, s):
        accept('list_items', token)
        env.items_set[s] = True
        return env._list(TOKEN, s)

    def download(token, base_url, kind, dest):
        accept('download', token)
        return env._download(TOKEN, base_url, kind, dest)
    monkeypatch.setattr(picker, 'get_session', get_session)
    monkeypatch.setattr(picker, 'list_items', list_items)
    monkeypatch.setattr(picker, 'download', download)
    monkeypatch.setattr(picker, 'delete_session', lambda token, s: accept('delete_session', token))
    clock = [0.0]
    s = fetch.run_fetch(None, 60, token_fn, now=lambda: clock[0],
                        sleep=lambda sec: clock.__setitem__(0, clock[0] + sec))
    assert s['status'] == 'ok' and s['downloaded'] == 1
    assert calls == ['get_session'] * 3 + ['list_items', 'download', 'download', 'delete_session']
    assert len(issued) == len(calls)
