import json
import os
import subprocess
import sys

import pytest

SECRET_VALUE = 'cli-test-secret-value'
_REMOTE_VARS = ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY')


@pytest.fixture
def run(script):
    """Run gphoto.py in a subprocess as a local desktop session with its own config folder."""
    def _run(*args, cfg, env=None):
        full = {k: v for k, v in os.environ.items()
                if k not in _REMOTE_VARS and not k.startswith('GOOGLE_PHOTO_')}
        full.update({'GOOGLE_PHOTO_CONFIG_DIR': str(cfg), 'DISPLAY': ':0'}, **(env or {}))
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                              env=full, timeout=60)
    return _run


def error(proc):
    assert proc.returncode == 2 and proc.stdout == ''
    err = json.loads(proc.stderr)
    assert err['status'] == 'failed' and err['message'] and err['message'] != err['error']
    return err['error']


def test_check_reports_without_secrets(tmp_path, run):
    cfg = tmp_path / 'cfg'
    cfg.mkdir(mode=0o700)
    (cfg / 'client_secret.json').write_text(json.dumps({'installed': {
        'client_id': 'id', 'client_secret': SECRET_VALUE,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token'}}), encoding='utf-8')
    proc = run('check', cfg=cfg)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out == {'status': 'ok', 'local': True, 'client_secret': 'present', 'token': 'missing',
                   'ffmpeg': out['ffmpeg'], 'config_dir': str(cfg)}
    assert out['ffmpeg'] in ('present', 'missing')
    assert proc.stderr == '' and SECRET_VALUE not in proc.stdout


def test_check_missing_secret_present_token(tmp_path, run):
    cfg = tmp_path / 'cfg'
    proc = run('check', cfg=cfg)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['client_secret'] == 'missing'
    assert cfg.is_dir()
    (cfg / 'token.json').write_text('{}', encoding='utf-8')
    assert json.loads(run('check', cfg=cfg).stdout)['token'] == 'present'


def test_remote_refused(tmp_path, run):
    cfg = tmp_path / 'cfg'
    p = run('check', cfg=cfg, env={'SSH_CONNECTION': 'x'})
    assert error(p) == 'REMOTE_ENVIRONMENT_REFUSED'
    assert not cfg.exists()  # refused before any file work


def test_help_allowed_when_remote(tmp_path, run):
    p = run('--help', cfg=tmp_path / 'cfg', env={'SSH_CONNECTION': 'x'})
    assert p.returncode == 0 and 'check' in p.stdout


def test_usage_error_hides_args(tmp_path, run):
    p = run('bogus-cmd', 'secret-ish', cfg=tmp_path / 'cfg')
    assert error(p) == 'USAGE_ERROR'
    assert 'secret-ish' not in p.stderr and 'bogus-cmd' not in p.stderr
    assert error(run(cfg=tmp_path / 'cfg')) == 'USAGE_ERROR'
    assert error(run('check', '--secret-ish', cfg=tmp_path / 'cfg')) == 'USAGE_ERROR'


def test_main_in_process(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(tmp_path / 'cfg'))
    monkeypatch.delenv('GOOGLE_PHOTO_CLIENT_SECRET', raising=False)
    monkeypatch.setattr(cli.config, 'remote_reason', lambda *a, **k: None)
    assert set(cli.COMMANDS) >= {'check'}
    assert cli.main(['check']) == 0
    assert json.loads(capsys.readouterr().out)['client_secret'] == 'missing'


def test_unexpected_exception_is_generic(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, 'remote_reason', lambda *a, **k: None)

    def boom(args):
        raise RuntimeError('/private/path token=abc')
    monkeypatch.setitem(cli.COMMANDS, 'check', boom)
    assert cli.main(['check']) == 2
    captured = capsys.readouterr()
    err = json.loads(captured.err)
    assert err == {'status': 'failed', 'error': 'RuntimeError', 'message': cli.errors.GENERIC_MESSAGE}
    assert captured.out == ''


def test_keyboard_interrupt_is_json_failure(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, 'remote_reason', lambda *a, **k: None)

    def interrupted(args):
        raise KeyboardInterrupt
    monkeypatch.setitem(cli.COMMANDS, 'check', interrupted)
    assert cli.main(['check']) == 2
    captured = capsys.readouterr()
    assert captured.out == '' and 'Traceback' not in captured.err
    assert json.loads(captured.err) == {'status': 'failed', 'error': 'INTERRUPTED',
                                        'message': cli.errors.MESSAGES['INTERRUPTED']}
