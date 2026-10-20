import json
import subprocess
import sys
import zipfile

import pytest

from conftest import NS, PNG, SAMPLES, SKILL

SCRIPT = SKILL / 'scripts' / 'hwp2md.py'
EMPTY_SEC = f'<hs:sec {NS}><hp:p id="1"><hp:run><hp:t></hp:t></hp:run></hp:p></hs:sec>'


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=300)


def error(proc):
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert err['status'] == 'failed' and isinstance(err['message'], str) and err['message']
    return err['error']


def test_converts_synthetic_hwpx(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서 1.hwpx')
    proc = run(src)
    assert proc.returncode == 0, proc.stderr
    md = (tmp_path / '문서 1.md').read_text(encoding='utf-8')
    assert '<td colspan="2">' in md
    assert '![](<문서 1_assets/a0.png>)' in md
    assert (tmp_path / '문서 1_assets' / 'a0.png').read_bytes() == PNG
    summary = json.loads(proc.stdout)
    assert summary['status'] == 'ok'
    assert summary['markdown'] == str(tmp_path / '문서 1.md')
    assert summary['assets_dir'] == str(tmp_path / '문서 1_assets')
    assert summary['tables'] == 2 and summary['images'] == 1
    assert summary['paths'] == ['direct']
    assert isinstance(summary['warnings'], list)


def test_refuses_existing_then_force(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx')
    assert run(src).returncode == 0
    assert error(run(src)) == 'OUTPUT_ALREADY_EXISTS'
    stale = tmp_path / '문서_assets' / 'stale.png'
    stale.write_bytes(b'old')
    proc = run(src, '--force')
    assert proc.returncode == 0, proc.stderr
    assert not stale.exists()
    assert (tmp_path / '문서_assets' / 'a0.png').read_bytes() == PNG
    assert sorted(p.name for p in tmp_path.iterdir()) == ['문서.hwpx', '문서.md', '문서_assets']


def test_refuses_when_only_assets_dir_exists(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx')
    (tmp_path / '문서_assets').mkdir()
    assert error(run(src)) == 'OUTPUT_ALREADY_EXISTS'
    assert not (tmp_path / '문서.md').exists()


def test_relative_input_other_cwd(make_hwpx, tmp_path):
    make_hwpx(tmp_path / '문서.hwpx')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    proc = run('../문서.hwpx', cwd=elsewhere)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / '문서.md').is_file()
    assert (tmp_path / '문서_assets' / 'a0.png').is_file()
    assert list(elsewhere.iterdir()) == []


def test_out_dir(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx')
    proc = run(src, '--out-dir', tmp_path / 'out')
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / 'out' / '문서.md').is_file()
    assert (tmp_path / 'out' / '문서_assets' / 'a0.png').read_bytes() == PNG
    assert not (tmp_path / '문서.md').exists()


def test_no_assets_dir_without_assets(make_hwpx, tmp_path):
    sec2 = f'<hs:sec {NS}><hp:p id="2"><hp:run><hp:t>본문</hp:t></hp:run></hp:p></hs:sec>'
    full = make_hwpx(tmp_path / 'full.zip', {'Contents/section2.xml': sec2})
    src = tmp_path / '문서.hwpx'
    with zipfile.ZipFile(full) as zin, zipfile.ZipFile(src, 'w') as zout:
        for name in zin.namelist():
            if not name.startswith('BinData/'):
                zout.writestr(name, zin.read(name))
    full.unlink()
    proc = run(src)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / '문서_assets').exists()
    assert json.loads(proc.stdout)['assets_dir'] is None


def test_no_text_fails(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '빈.hwpx', {'Contents/section2.xml': EMPTY_SEC,
                                          'Contents/section10.xml': EMPTY_SEC})
    proc = run(src)
    assert error(proc) == 'NO_EXTRACTABLE_TEXT'
    assert '--ocr' in json.loads(proc.stderr)['message']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['빈.hwpx']


def test_failure_leaves_nothing(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / 'slip.hwpx', {'../escape.xml': '<bad/>'})
    assert error(run(src)) == 'UNSAFE_PACKAGE_PATH'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['slip.hwpx']


def test_missing_input(tmp_path):
    assert error(run(tmp_path / 'nope.hwpx')) == 'MISSING_OR_OVERSIZE_INPUT'


def test_vlm_without_key_fails_cleanly(make_hwpx, tmp_path):
    import os
    src = make_hwpx(tmp_path / '문서.hwpx')
    env = {k: v for k, v in os.environ.items() if k not in ('GROQ_API_KEY', 'XAI_API_KEY')}
    proc = subprocess.run([sys.executable, str(SCRIPT), str(src), '--vlm', 'groq'],
                          capture_output=True, text=True, env=env, cwd=tmp_path, timeout=300)
    assert error(proc) == 'GROQ_API_KEY_MISSING'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['문서.hwpx']


def test_usage_error_is_json(tmp_path):
    assert error(run()) == 'USAGE_ERROR'
    assert error(run(tmp_path / 'a.hwpx', '--vlm', 'other')) == 'USAGE_ERROR'


def test_stderr_has_no_document_text(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / 'doc.hwpx')
    assert run(src).returncode == 0
    again = run(src)
    assert error(again) == 'OUTPUT_ALREADY_EXISTS'
    bad = make_hwpx(tmp_path / 'bad.hwpx', {'Contents/section2.xml': '<unclosed>'})
    broken = run(bad)
    assert error(broken) == 'MALFORMED_XML'
    for proc in (again, broken):
        assert '합성' not in proc.stderr
        assert 'Traceback' not in proc.stderr


def test_messages_cover_every_failure_code():
    import re
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPT.parent))
    import hwp2md
    source = SCRIPT.read_text(encoding='utf-8')
    for module in ('extract.py', 'ocr.py', 'convert.py', 'vlm.py'):
        source += (SCRIPT.parent / 'hwp_parser' / module).read_text(encoding='utf-8')
    codes = set(re.findall(r"Failure\('([A-Z0-9_]+)'\)", source))
    assert codes and codes <= set(hwp2md.MESSAGES)
    assert {'OUTPUT_ALREADY_EXISTS', 'NO_EXTRACTABLE_TEXT'} <= set(hwp2md.MESSAGES)
    assert 'FEATURE_NOT_AVAILABLE' not in hwp2md.MESSAGES and 'FEATURE_NOT_AVAILABLE' not in source
    # Provider HTTP failures are dynamic codes (<PROVIDER>_HTTP_<status>) with one shared message.
    for code in ('GROQ_HTTP_401', 'XAI_HTTP_503'):
        assert hwp2md.message_for(code) == hwp2md.MESSAGES['VLM_HTTP_ERROR']
    assert hwp2md.message_for('GROQ_HTTP_X') == hwp2md.GENERIC_MESSAGE
    from hwp_parser import ocr, vlm
    for _, _, key_name in vlm.PROVIDERS.values():  # built as f'{key_name}_MISSING'
        assert f'{key_name}_MISSING' in hwp2md.MESSAGES
    assert hwp2md.annotate_hooks == [ocr.hook, vlm.hook]


@pytest.mark.parametrize('name', ['prospectus', 'pharma-disclosure', 'youth-rfp'])
def test_samples_convert(tmp_path, name):
    proc = run(SAMPLES / (name + '.hwp'), '--out-dir', tmp_path)
    assert proc.returncode == 0, proc.stderr
    md = (tmp_path / (name + '.md')).read_text(encoding='utf-8')
    assert '<table' in md
    if name == 'youth-rfp':
        assert '시상식' in md
