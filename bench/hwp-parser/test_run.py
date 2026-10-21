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


def test_readmes_are_english_and_korean():
    assert [p.name for p in run.READMES] == ['README.md', 'README.ko.md']
    assert all(p.parent == run.REPO for p in run.READMES)


def test_main_update_readme_fails_before_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, 'READMES', (tmp_path / 'README.md', tmp_path / 'README.ko.md'))
    monkeypatch.setattr(run, 'run_bench', lambda **_: pytest.fail('bench must not run'))
    assert run.main(['--update-readme']) == 1
    assert 'README.md not found' in capsys.readouterr().err


def test_main_update_readme_checks_every_readme_first(tmp_path, monkeypatch, capsys):
    en, ko = tmp_path / 'README.md', tmp_path / 'README.ko.md'
    en.write_text('<!-- bench:start -->\nold\n<!-- bench:end -->\n', encoding='utf-8')
    monkeypatch.setattr(run, 'READMES', (en, ko))
    monkeypatch.setattr(run, 'run_bench', lambda **_: pytest.fail('bench must not run'))
    assert run.main(['--update-readme']) == 1
    assert 'README.ko.md not found' in capsys.readouterr().err
    assert en.read_text(encoding='utf-8') == '<!-- bench:start -->\nold\n<!-- bench:end -->\n'


def test_main_update_readme_updates_both(tmp_path, monkeypatch):
    en, ko = tmp_path / 'README.md', tmp_path / 'README.ko.md'
    en.write_text('# EN\n<!-- bench:start -->\nold\n<!-- bench:end -->\nen tail\n', encoding='utf-8')
    ko.write_text('# KO\n<!-- bench:start -->\n예전\n<!-- bench:end -->\nko tail\n', encoding='utf-8')
    monkeypatch.setattr(run, 'READMES', (en, ko))
    monkeypatch.setattr(run, 'RESULTS_JSON', tmp_path / 'results.json')
    monkeypatch.setattr(run, 'RESULTS_MD', tmp_path / 'results.md')
    monkeypatch.setattr(run, 'run_bench', lambda **_: {'stub': True})
    monkeypatch.setattr(run, 'render_md', lambda data: '| new |\n')
    assert run.main(['--update-readme']) == 0
    assert en.read_text(encoding='utf-8') == '# EN\n<!-- bench:start -->\n| new |\n<!-- bench:end -->\nen tail\n'
    assert ko.read_text(encoding='utf-8') == '# KO\n<!-- bench:start -->\n| new |\n<!-- bench:end -->\nko tail\n'


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
