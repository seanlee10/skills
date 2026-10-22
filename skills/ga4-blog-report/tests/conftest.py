import json
import sys
import urllib.request
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / 'scripts' / 'ga4_report.py'
sys.path.insert(0, str(SKILL / 'scripts'))


@pytest.fixture
def script():
    """Path to scripts/ga4_report.py, for subprocess contract tests."""
    return SCRIPT


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    """Every test gets its own config folder, so the real ~/.config is never read or written."""
    folder = tmp_path / 'config'
    monkeypatch.setenv('GA4_BLOG_REPORT_CONFIG_DIR', str(folder))
    return folder


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach the network: a real opener fails the test; tests patch _post."""
    def refuse(*args, **kwargs):
        pytest.fail('network access in a test')

    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', refuse)
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)


@pytest.fixture(scope='session')
def private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem


@pytest.fixture
def key_file(tmp_path, private_key):
    path = tmp_path / 'downloaded-key.json'
    path.write_text(json.dumps({
        'type': 'service_account', 'project_id': 'demo', 'private_key_id': 'abc123',
        'private_key': private_key[1], 'client_email': 'reporter@demo.iam.gserviceaccount.com',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }), encoding='utf-8')
    return path
