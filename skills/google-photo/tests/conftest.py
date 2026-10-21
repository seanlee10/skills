import importlib.util
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / 'scripts' / 'gphoto.py'
sys.path.insert(0, str(SKILL / 'scripts'))


@pytest.fixture
def script():
    """Path to scripts/gphoto.py, for subprocess contract tests."""
    return SCRIPT


@pytest.fixture
def cli():
    """scripts/gphoto.py imported in-process (call cli.main([...]) and patch its modules).

    `import gphoto` resolves to the package scripts/gphoto/, which shadows the script of the
    same name, so the script is loaded from its path under the module name `gphoto_cli`.
    """
    if 'gphoto_cli' not in sys.modules:
        spec = importlib.util.spec_from_file_location('gphoto_cli', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules['gphoto_cli'] = module
        spec.loader.exec_module(module)
    return sys.modules['gphoto_cli']


@pytest.fixture(autouse=True)
def browser_calls(monkeypatch):
    """No test may open a real browser: every `webbrowser` entry point records its URL instead."""
    import webbrowser

    calls = []

    def record(url, *args, **kwargs):
        calls.append(url)
        return True

    for name in ('open', 'open_new', 'open_new_tab'):
        monkeypatch.setattr(webbrowser, name, record)
    monkeypatch.setattr(webbrowser, 'get', lambda *a, **k: pytest.fail('webbrowser.get in a test'))
    return calls
