import json
import stat

import pytest

from gphoto import config
from gphoto.errors import Failure, message_for, MESSAGES, GENERIC_MESSAGE

INSTALLED = {
    'client_id': 'id.apps.googleusercontent.com',
    'client_secret': 'not-a-real-secret',
    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'project_id': 'demo',
    'redirect_uris': ['http://localhost'],
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(tmp_path / 'cfg'))
    monkeypatch.delenv('GOOGLE_PHOTO_CLIENT_SECRET', raising=False)
    return tmp_path / 'cfg'


def _write_secret(cfg, data):
    cfg.mkdir(mode=0o700, exist_ok=True)
    (cfg / 'client_secret.json').write_text(json.dumps(data), encoding='utf-8')


@pytest.mark.parametrize('env,platform,dockerenv,reason', [
    ({'SSH_CONNECTION': '1 2 3 4'}, 'darwin', False, 'ssh'),
    ({'SSH_CLIENT': '1 2 3'}, 'darwin', False, 'ssh'),
    ({'SSH_TTY': '/dev/ttys001'}, 'darwin', False, 'ssh'),
    ({'SSH_TTY': '/dev/pts/0', 'DISPLAY': ':0'}, 'linux', False, 'ssh'),
    ({}, 'linux', False, 'no-display'),
    ({'DISPLAY': ':0'}, 'linux', True, 'container'),
    ({'DISPLAY': ':0'}, 'linux', False, None),
    ({'WAYLAND_DISPLAY': 'wayland-0'}, 'linux', False, None),
    ({}, 'darwin', False, None),
    ({}, 'win32', False, None),
])
def test_remote_reason(env, platform, dockerenv, reason):
    assert config.remote_reason(env, platform, lambda p: dockerenv and p == '/.dockerenv') == reason


def test_remote_reason_podman():
    assert config.remote_reason({'DISPLAY': ':0'}, 'linux', lambda p: p == '/run/.containerenv') == 'container'


def test_ensure_local(monkeypatch):
    monkeypatch.setattr(config, 'remote_reason', lambda *a, **k: 'ssh')
    with pytest.raises(Failure) as e:
        config.ensure_local()
    assert e.value.code == 'REMOTE_ENVIRONMENT_REFUSED'
    monkeypatch.setattr(config, 'remote_reason', lambda *a, **k: None)
    assert config.ensure_local() is None


def test_config_dir_mode(cfg):
    d = config.config_dir()
    assert d == cfg
    assert d.is_dir() and stat.S_IMODE(d.stat().st_mode) == 0o700


def test_config_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv('GOOGLE_PHOTO_CONFIG_DIR', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))
    assert config.config_dir() == tmp_path / '.config' / 'google-photo'


def test_client_secret_path(cfg, tmp_path, monkeypatch):
    assert config.client_secret_path() == cfg / 'client_secret.json'
    monkeypatch.setenv('GOOGLE_PHOTO_CLIENT_SECRET', str(tmp_path / 'other.json'))
    assert config.client_secret_path() == tmp_path / 'other.json'


def test_load_client_desktop(cfg):
    _write_secret(cfg, {'installed': INSTALLED})
    assert config.load_client() == {k: INSTALLED[k] for k in ('client_id', 'client_secret', 'auth_uri', 'token_uri')}


def test_load_client_missing(cfg):
    with pytest.raises(Failure) as e:
        config.load_client()
    assert e.value.code == 'CLIENT_SECRET_MISSING'


@pytest.mark.parametrize('data', [
    {'web': INSTALLED},
    {'installed': {k: v for k, v in INSTALLED.items() if k != 'client_secret'}},
    {'installed': {**INSTALLED, 'client_id': ''}},
    {'installed': {**INSTALLED, 'token_uri': 'https://evil.example/token'}},
    {'installed': {**INSTALLED, 'auth_uri': 'http://accounts.google.com/o/oauth2/auth'}},
    {'installed': 'x'},
    ['installed'],
])
def test_load_client_invalid(cfg, data):
    _write_secret(cfg, data)
    with pytest.raises(Failure) as e:
        config.load_client()
    assert e.value.code == 'CLIENT_SECRET_INVALID'


def test_load_client_not_json(cfg):
    cfg.mkdir(mode=0o700)
    (cfg / 'client_secret.json').write_bytes(b'\xff not json')
    with pytest.raises(Failure) as e:
        config.load_client()
    assert e.value.code == 'CLIENT_SECRET_INVALID'


def test_messages():
    for code in ['USAGE_ERROR', 'REMOTE_ENVIRONMENT_REFUSED', 'CLIENT_SECRET_MISSING', 'CLIENT_SECRET_INVALID']:
        assert message_for(code) == MESSAGES[code]
    assert message_for('GOOGLE_HTTP_403') == MESSAGES['GOOGLE_HTTP_ERROR']
    assert message_for('GOOGLE_HTTP_4031') == GENERIC_MESSAGE
    assert message_for('KeyError') == GENERIC_MESSAGE
    assert Failure('USAGE_ERROR').code == 'USAGE_ERROR'
