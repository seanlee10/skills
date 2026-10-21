"""Error codes and their fixed English messages.

A message never contains paths, tokens, URLs or user data. Every code is documented in
references/errors.md.
"""
from __future__ import annotations

import re

MESSAGES = {
    # gphoto.py
    'INTERRUPTED': 'The command was interrupted before it finished.',
    'USAGE_ERROR': 'Invalid command-line arguments. Usage: gphoto.py {check,auth,start,fetch,curate,select} ...; see --help.',
    # config.py
    'REMOTE_ENVIRONMENT_REFUSED': 'This skill runs only on a local desktop (not over SSH, in a container or without a display); nothing was done.',
    'CLIENT_SECRET_MISSING': 'No OAuth client file was found; save the Desktop app client JSON as client_secret.json in the config folder.',
    'CLIENT_SECRET_INVALID': 'The OAuth client file is not a valid Google Desktop app client (it needs an "installed" section with Google endpoints).',
    # auth.py
    'AUTH_REQUIRED': 'Not signed in, or the sign-in expired or was revoked; run the auth command to sign in again.',
    'AUTH_DENIED': 'Google sign-in was cancelled or the Google Photos permission was not granted.',
    'AUTH_TIMEOUT': 'Sign-in was not completed in the browser in time; run the auth command again.',
    'AUTH_STATE_MISMATCH': 'The sign-in redirect did not match this sign-in attempt and was ignored; run the auth command again.',
    'NETWORK_ERROR': 'Could not reach Google (network error or timeout).',
    'BAD_RESPONSE': 'Google returned a response the skill could not use.',
    # picker.py
    'SESSION_EXPIRED': 'The Google Photos picking session expired or was closed; start a new one with the start command.',
    'BASEURL_EXPIRED': 'The download link for a picked item expired or was refused; list the session again or start a new one.',
    # library.py
    'UNSAFE_SUBJECT': 'The subject name cannot be used as a folder name (empty, ".", "..", a path separator, a control character or over 100 characters).',
    'UNKNOWN_TIME_ZONE': 'The time zone is not a known IANA zone name (for example Asia/Seoul or Europe/Berlin).',
    'DATE_RANGE_OUTSIDE_YEAR': 'The date range must lie within the chosen year and start on or before its end.',
    'MANIFEST_CORRUPT': 'The library manifest in the year folder could not be read; nothing was changed.',
    # fetch.py
    'NO_PENDING_SESSION': 'There is no pending picking session to fetch; run the start command first.',
    'AMBIGUOUS_PENDING_SESSION': 'Several picking sessions are pending; choose one with --session.',
    'PENDING_SESSION_CORRUPT': 'The saved state of the pending picking session could not be read; run the start command again.',
    # curate.py
    'NOTHING_TO_CURATE': 'There is nothing to curate: the year folder has no manifest or none of its files are on disk; run the fetch command first.',
    'CURATION_DIR_UNSAFE': 'The curation folder (or its sheets folder) is a symbolic link or not a folder; nothing was written.',
    'INVALID_PICKS': 'The picks file is missing or invalid: it needs an "items" list of 1 to as many entries as there are candidates, each a distinct candidate ref with a short non-empty reason (at most 200 characters) and its media file on disk; nothing was changed.',
    'CANDIDATES_CORRUPT': 'The candidates file in the curation folder could not be read; run the curate command again.',
    'PICKS_OUTDATED': 'The picks file is older than the latest curate run, whose refs may name other photos; write the picks again from the new contact sheets. Nothing was changed.',
    'SELECTED_DIR_UNSAFE': 'The selected folder is a symbolic link or not a folder; nothing was written.',
    # Dynamic codes GOOGLE_HTTP_<status> (e.g. GOOGLE_HTTP_403) all map to this message; see message_for().
    'GOOGLE_HTTP_ERROR': 'Google rejected the request; the error code carries the HTTP status.',
}
GENERIC_MESSAGE = 'Unexpected internal error.'
_HTTP_CODE = re.compile(r'GOOGLE_HTTP_\d{3}')


class Failure(Exception):
    """A failure with a fixed error code; the code is the only payload."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def message_for(code: str) -> str:
    if code in MESSAGES:
        return MESSAGES[code]
    if _HTTP_CODE.fullmatch(code):
        return MESSAGES['GOOGLE_HTTP_ERROR']
    return GENERIC_MESSAGE
