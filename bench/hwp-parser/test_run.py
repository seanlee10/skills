import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run  # noqa: E402


def test_update_readme_replaces_between_markers(tmp_path):
    readme = tmp_path / 'README.md'
    readme.write_text('# T\n\n<!-- bench:start -->\nold\n<!-- bench:end -->\n\ntail\n', encoding='utf-8')
    run.update_readme(readme, '| a |\n')
    assert readme.read_text(encoding='utf-8') == (
        '# T\n\n<!-- bench:start -->\n| a |\n<!-- bench:end -->\n\ntail\n')


def test_update_readme_missing_file(tmp_path):
    with pytest.raises(run.BenchError, match='README.md not found'):
        run.update_readme(tmp_path / 'README.md', 'x')


@pytest.mark.parametrize('body', ['no markers\n', '<!-- bench:start -->\nonly start\n',
                                  '<!-- bench:end -->\n<!-- bench:start -->\n'])
def test_update_readme_missing_markers(tmp_path, body):
    readme = tmp_path / 'README.md'
    readme.write_text(body, encoding='utf-8')
    with pytest.raises(run.BenchError, match='markers'):
        run.update_readme(readme, 'x')
    assert readme.read_text(encoding='utf-8') == body


def test_main_update_readme_fails_before_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, 'README', tmp_path / 'README.md')
    monkeypatch.setattr(run, 'run_bench', lambda **_: pytest.fail('bench must not run'))
    assert run.main(['--update-readme']) == 1
    assert 'README.md not found' in capsys.readouterr().err


def _res(**acc):
    return {'results': {'doc': {s: {'char_accuracy': a} for s, a in acc.items()}}}


def test_regressions_only_hwp_parser_beyond_tolerance():
    committed = _res(**{'hwp-parser': 0.90, 'hwp-parser --ocr': 0.90, 'LlamaParse (cloud)': 0.90})
    current = _res(**{'hwp-parser': 0.895, 'hwp-parser --ocr': 0.85, 'LlamaParse (cloud)': 0.10})
    assert run.regressions(committed, current) == [('doc', 'hwp-parser --ocr', 0.85, 0.90)]


def test_regressions_skip_unmeasured():
    committed = _res(**{'hwp-parser --vlm groq': None})
    current = _res(**{'hwp-parser --vlm groq': None})
    assert run.regressions(committed, current) == []
