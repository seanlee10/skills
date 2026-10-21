"""Config folder, OAuth client file and the local-only guard."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .errors import Failure

_CLIENT_KEYS = ('client_id', 'client_secret', 'auth_uri', 'token_uri')
# The client file chooses the OAuth endpoints, so they are pinned to Google's hosts.
_ENDPOINT_HOSTS = {'auth_uri': 'accounts.google.com', 'token_uri': 'oauth2.googleapis.com'}
_SSH_VARS = ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY')
_CONTAINER_MARKERS = ('/.dockerenv', '/run/.containerenv')


def config_dir() -> Path:
    """Return the config folder, creating it with mode 0700 if it does not exist."""
    override = os.environ.get('GOOGLE_PHOTO_CONFIG_DIR')
    path = Path(override) if override else Path.home() / '.config' / 'google-photo'
    if not path.is_dir():
        path.mkdir(mode=0o700, parents=True)
        path.chmod(0o700)  # mkdir's mode is masked by the umask
    return path


def client_secret_path() -> Path:
    override = os.environ.get('GOOGLE_PHOTO_CLIENT_SECRET')
    return Path(override) if override else config_dir() / 'client_secret.json'


def load_client() -> dict:
    """Read the Desktop app OAuth client; returns client_id, client_secret, auth_uri, token_uri."""
    path = client_secret_path()
    if not path.is_file():
        raise Failure('CLIENT_SECRET_MISSING')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Failure('CLIENT_SECRET_INVALID') from None
    installed = data.get('installed') if isinstance(data, dict) else None
    if not isinstance(installed, dict):
        raise Failure('CLIENT_SECRET_INVALID')  # e.g. a "web" client, which cannot use loopback
    client = {key: installed.get(key) for key in _CLIENT_KEYS}
    if not all(isinstance(v, str) and v for v in client.values()):
        raise Failure('CLIENT_SECRET_INVALID')
    for key, host in _ENDPOINT_HOSTS.items():
        url = urlsplit(client[key])
        if url.scheme != 'https' or url.hostname != host:
            raise Failure('CLIENT_SECRET_INVALID')
    return client


def remote_reason(env=os.environ, platform=sys.platform, exists=os.path.exists) -> str | None:
    """Why this machine counts as remote ('ssh', 'container', 'no-display'), or None if local."""
    if any(var in env for var in _SSH_VARS):
        return 'ssh'
    if platform.startswith('linux'):
        if any(exists(marker) for marker in _CONTAINER_MARKERS):
            return 'container'
        if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
            return 'no-display'
    return None


def ensure_local() -> None:
    if remote_reason(os.environ, sys.platform, os.path.exists) is not None:
        raise Failure('REMOTE_ENVIRONMENT_REFUSED')
