import sys
import urllib.request
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / 'scripts' / 'kipris_api.py'
sys.path.insert(0, str(SKILL / 'scripts'))


@pytest.fixture
def script():
    """Path to scripts/kipris_api.py, for subprocess contract tests."""
    return SCRIPT


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own home folder, so the real ~/.config is never read or written."""
    folder = tmp_path / 'home'
    folder.mkdir()
    monkeypatch.setenv('HOME', str(folder))
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: folder))
    return folder


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach the network: a real opener fails the test; tests patch the transport."""
    def refuse(*args, **kwargs):
        pytest.fail('network access in a test')

    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', refuse)
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
