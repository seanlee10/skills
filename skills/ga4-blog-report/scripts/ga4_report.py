# /// script
# requires-python = "==3.11.*"
# dependencies = [
#     "cryptography==50.0.2",
# ]
# ///
"""Report a GA4 property's blog traffic (pages, sources, AI engines) with the GA4 Data API.

Usage: uv run ga4_report.py configure --key FILE --property ID
       uv run ga4_report.py status             (no network; never prints the key)
       uv run ga4_report.py report [--start D] [--end D] [--prefix /blog/] [--out FILE] [--force]

Exit 0: JSON on stdout. Exit 2: {"status":"failed","error":CODE,"message":str} on stderr.
"""
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside the skill folder

import argparse
import base64
import csv
import json
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

TOKEN_URI = 'https://oauth2.googleapis.com/token'
API_HOST = 'analyticsdata.googleapis.com'
SCOPE = 'https://www.googleapis.com/auth/analytics.readonly'
TIMEOUT = 60
MAX_RESPONSE = 32 * 1024 * 1024
PAGE_SIZE = 25000
MAX_ROWS = 250000
TOP_SOURCES = 10
CONFIG_DISPLAY = '~/.config/ga4-blog-report'

# Referral hosts of AI assistants and answer engines. A source matches a host exactly or as a
# subdomain of it ("www." is ignored). Extend this when an unlisted AI host shows up.
AI_SOURCES = {
    'chatgpt.com': 'ChatGPT', 'chat.openai.com': 'ChatGPT', 'chatgpt': 'ChatGPT',
    'perplexity.ai': 'Perplexity', 'perplexity': 'Perplexity',
    'gemini.google.com': 'Gemini', 'bard.google.com': 'Gemini',
    'copilot.microsoft.com': 'Copilot', 'copilot.com': 'Copilot',
    'claude.ai': 'Claude',
    'chat.deepseek.com': 'DeepSeek',
    'grok.com': 'Grok',
    'meta.ai': 'Meta AI',
    'chat.mistral.ai': 'Mistral',
    'you.com': 'You.com',
}

# Fixed English message per error code. A message never contains the key, a token, a path or
# any part of a Google response. Every code is documented in references/errors.md.
MESSAGES = {
    # command line
    'USAGE_ERROR': 'Invalid command-line arguments. Usage: ga4_report.py {configure,status,report} ...; see --help.',
    'INVALID_DATE': 'Dates must be YYYY-MM-DD, today, yesterday or NdaysAgo, and --start must not be after --end; nothing was sent.',
    'INVALID_PREFIX': '--prefix must start with "/" and contain no whitespace; nothing was sent.',
    'INTERRUPTED': 'The command was interrupted before it finished.',
    # configure
    'KEY_SOURCE_MISSING': 'The --key file does not exist or is not a regular file; nothing was saved.',
    'KEY_INVALID': 'The key file is not a Google service account JSON key (type, client_email, private_key, token_uri); nothing was saved.',
    'PROPERTY_ID_INVALID': 'The GA4 property ID must be digits only (Admin -> Property details); nothing was saved.',
    'MEASUREMENT_ID_GIVEN': 'That is a measurement ID (G-...), not the numeric property ID shown in Admin -> Property details; nothing was saved.',
    'CONFIG_DIR_UNSAFE': 'The config folder is a symbolic link or not a folder; use a regular folder. Nothing was saved.',
    'LOCAL_SETUP_FAILED': 'The key or settings could not be written to the config folder.',
    # stored settings
    'NOT_CONFIGURED': 'No service account key and property ID are configured; run configure first (see references/setup.md).',
    'KEY_FILE_UNSAFE': 'The stored key must be a regular file owned by the user with mode 600; run configure again.',
    'CONFIG_INVALID': 'The stored settings or key are unreadable or invalid; run configure again.',
    # transport and Google responses
    'NETWORK_ERROR': 'Google could not be reached or timed out; nothing was retried.',
    'AUTH_REJECTED': 'Google rejected the service account key (deleted or disabled key, or a wrong system clock).',
    'AUTH_FAILED': 'The access token could not be obtained from Google.',
    'API_DISABLED': 'The Google Analytics Data API is not enabled in the service account\'s Cloud project.',
    'PROPERTY_ACCESS_DENIED': 'The service account has no access to this GA4 property, or the property ID is wrong.',
    'QUOTA_EXHAUSTED': 'The GA4 Data API quota for this property is used up; try again later.',
    'REQUEST_INVALID': 'The GA4 Data API rejected the request (for example a date before the property existed).',
    'GA4_HTTP_ERROR': 'The GA4 Data API answered with an unexpected HTTP error.',
    'RESPONSE_TOO_LARGE': 'A Google response exceeded the 32 MiB limit.',
    'RESPONSE_MALFORMED': 'A Google response was not the expected JSON; do not read it as zero traffic.',
    # output
    'OUTPUT_EXISTS': 'The --out file already exists; choose another path or pass --force. Nothing was sent.',
    'OUTPUT_UNWRITABLE': 'The --out file could not be written.',
}
GENERIC_MESSAGE = 'Unexpected internal error.'


class Failure(Exception):
    """A failure with a fixed error code; the code is the only payload."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def message_for(code):
    return MESSAGES.get(code, GENERIC_MESSAGE)


# --- settings ---------------------------------------------------------------------------------

def config_dir():
    override = os.environ.get('GA4_BLOG_REPORT_CONFIG_DIR')
    return Path(override) if override else Path.home() / '.config' / 'ga4-blog-report'


def _key_path():
    return config_dir() / 'service-account.json'


def _settings_path():
    return config_dir() / 'settings.json'


def _parse_key(data):
    """Return the service account dict if data looks like a usable key, else raise KEY_INVALID."""
    if not isinstance(data, dict) or data.get('type') != 'service_account':
        raise Failure('KEY_INVALID')
    for field in ('client_email', 'private_key'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise Failure('KEY_INVALID')
    # The key file chooses where the signed assertion goes, so it is pinned to Google's endpoint.
    if data.get('token_uri', TOKEN_URI) != TOKEN_URI:
        raise Failure('KEY_INVALID')
    if '-----BEGIN PRIVATE KEY-----' not in data['private_key']:
        raise Failure('KEY_INVALID')
    return data


def _parse_property(value):
    value = (value or '').strip()
    if value.upper().startswith('G-'):
        raise Failure('MEASUREMENT_ID_GIVEN')
    value = value.removeprefix('properties/')
    if not re.fullmatch(r'\d{1,20}', value):
        raise Failure('PROPERTY_ID_INVALID')
    return value


def _write_private(path, text):
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def configure(key_file, property_id):
    prop = _parse_property(property_id)
    source = Path(key_file).expanduser()
    if not source.is_file():
        raise Failure('KEY_SOURCE_MISSING')
    try:
        data = json.loads(source.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Failure('KEY_INVALID') from None
    key = _parse_key(data)
    folder = config_dir()
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise Failure('CONFIG_DIR_UNSAFE')
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        _write_private(_key_path(), json.dumps(key))
        _write_private(_settings_path(), json.dumps({'property_id': prop}))
    except OSError:
        raise Failure('LOCAL_SETUP_FAILED') from None
    return {'status': 'ok', 'configured': True, 'property_id': prop,
            'client_email': key['client_email'], 'config_dir': CONFIG_DISPLAY,
            'remote_validation': 'not_performed'}


def _read_private_json(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise Failure('NOT_CONFIGURED') from None
    except OSError:
        raise Failure('KEY_FILE_UNSAFE') from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Failure('KEY_FILE_UNSAFE')
        stream = os.fdopen(descriptor, 'r', encoding='utf-8')
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        try:
            return json.loads(stream.read())
        except (UnicodeError, ValueError):
            raise Failure('CONFIG_INVALID') from None


def load_settings():
    """Return (service account dict, property ID) from the config folder."""
    if config_dir().is_symlink():
        raise Failure('CONFIG_DIR_UNSAFE')
    key = _read_private_json(_key_path())
    settings = _read_private_json(_settings_path())
    try:
        return _parse_key(key), _parse_property(settings.get('property_id'))
    except (Failure, AttributeError):
        raise Failure('CONFIG_INVALID') from None


def status():
    try:
        key, prop = load_settings()
    except Failure:
        return {'status': 'ok', 'configured': False, 'config_dir': CONFIG_DISPLAY}
    return {'status': 'ok', 'configured': True, 'property_id': prop,
            'client_email': key['client_email'], 'config_dir': CONFIG_DISPLAY,
            'remote_validation': 'not_performed'}


# --- Google calls -----------------------------------------------------------------------------

def _post(url, body, headers):
    """POST and return (HTTP status, raw body). The only function that touches the network."""
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        return error.code, error.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, OSError, ValueError):
        raise Failure('NETWORK_ERROR') from None


def _json(raw):
    if len(raw) > MAX_RESPONSE:
        raise Failure('RESPONSE_TOO_LARGE')
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise Failure('RESPONSE_MALFORMED') from None
    if not isinstance(data, dict):
        raise Failure('RESPONSE_MALFORMED')
    return data


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def _assertion(key, now):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {'alg': 'RS256', 'typ': 'JWT'}
    if key.get('private_key_id'):
        header['kid'] = key['private_key_id']
    claims = {'iss': key['client_email'], 'scope': SCOPE, 'aud': TOKEN_URI,
              'iat': now, 'exp': now + 3600}
    signing_input = b'.'.join(_b64(json.dumps(part, separators=(',', ':')).encode())
                              for part in (header, claims))
    try:
        private = serialization.load_pem_private_key(key['private_key'].encode(), password=None)
        signature = private.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, TypeError):
        raise Failure('CONFIG_INVALID') from None
    return (signing_input + b'.' + _b64(signature)).decode()


def access_token(key):
    body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                   'assertion': _assertion(key, int(time.time()))}).encode()
    code, raw = _post(TOKEN_URI, body, {'Content-Type': 'application/x-www-form-urlencoded'})
    if code == 400 and b'invalid_grant' in raw[:4096]:
        raise Failure('AUTH_REJECTED')
    if code != 200:
        raise Failure('AUTH_FAILED')
    token = _json(raw).get('access_token')
    if not isinstance(token, str) or not token:
        raise Failure('RESPONSE_MALFORMED')
    return token


def _api_failure(code, raw):
    try:
        error = json.loads(raw[:MAX_RESPONSE]).get('error', {})
        reasons = {d.get('reason') for d in error.get('details', []) if isinstance(d, dict)}
        text = str(error.get('message', ''))
    except (AttributeError, UnicodeDecodeError, ValueError):
        reasons, text = set(), ''
    if code == 403 and ('SERVICE_DISABLED' in reasons or 'has not been used' in text
                        or 'is disabled' in text):
        return Failure('API_DISABLED')
    if code == 401:
        return Failure('AUTH_FAILED')
    if code in (403, 404):
        return Failure('PROPERTY_ACCESS_DENIED')
    if code == 429:
        return Failure('QUOTA_EXHAUSTED')
    if code == 400:
        return Failure('REQUEST_INVALID')
    return Failure('GA4_HTTP_ERROR')


def run_report(token, prop, body):
    """Run one report, following offsets; returns (rows, row_count, truncated, other_row)."""
    url = f'https://{API_HOST}/v1beta/properties/{prop}:runReport'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    rows, offset, row_count, other_row = [], 0, 0, False
    while True:
        page = dict(body, limit=PAGE_SIZE, offset=offset)
        code, raw = _post(url, json.dumps(page).encode(), headers)
        if code != 200:
            raise _api_failure(code, raw)
        data = _json(raw)
        row_count = data.get('rowCount', 0)
        batch = data.get('rows', [])
        if not isinstance(row_count, int) or not isinstance(batch, list):
            raise Failure('RESPONSE_MALFORMED')
        other_row = other_row or bool((data.get('metadata') or {}).get('dataLossFromOtherRow'))
        for row in batch:
            try:
                rows.append(([d['value'] for d in row['dimensionValues']],
                             [m['value'] for m in row['metricValues']]))
            except (KeyError, TypeError):
                raise Failure('RESPONSE_MALFORMED') from None
        offset += len(batch)
        if not batch or offset >= row_count or offset >= MAX_ROWS:
            return rows, row_count, offset < row_count, other_row


# --- report -----------------------------------------------------------------------------------

_DATE = re.compile(r'today|yesterday|\d{1,4}daysAgo|\d{4}-\d{2}-\d{2}')


def _resolve(value):
    """Return a comparable date for a GA4 date string, or raise INVALID_DATE."""
    if not _DATE.fullmatch(value):
        raise Failure('INVALID_DATE')
    today = date.today().toordinal()
    if value == 'today':
        return today
    if value == 'yesterday':
        return today - 1
    if value.endswith('daysAgo'):
        return today - int(value[:-7])
    try:
        return date.fromisoformat(value).toordinal()
    except ValueError:
        raise Failure('INVALID_DATE') from None


def check_dates(start, end):
    first, last = _resolve(start), _resolve(end)
    if first > last:
        raise Failure('INVALID_DATE')
    return last >= date.today().toordinal()


def ai_engine(source):
    host = source.strip().lower().removeprefix('www.')
    while host:
        if host in AI_SOURCES:
            return AI_SOURCES[host]
        _, dot, host = host.partition('.')
        if not dot:
            return ''
    return ''


def _filter(prefix):
    return {'filter': {'fieldName': 'pagePath',
                       'stringFilter': {'matchType': 'BEGINS_WITH', 'value': prefix}}}


def _num(value, kind=int):
    try:
        return kind(value)
    except (TypeError, ValueError):
        raise Failure('RESPONSE_MALFORMED') from None


def report(start, end, prefix, out, force, fetch=None):
    includes_today = check_dates(start, end)
    if not prefix.startswith('/') or any(c.isspace() for c in prefix):
        raise Failure('INVALID_PREFIX')
    out = Path(out)
    if out.exists() and not force:
        raise Failure('OUTPUT_EXISTS')
    key, prop = load_settings()
    if fetch is None:
        token = access_token(key)
        fetch = lambda body: run_report(token, prop, body)  # noqa: E731
    base = {'dateRanges': [{'startDate': start, 'endDate': end}], 'dimensionFilter': _filter(prefix)}
    # Page x source rows: a session that viewed several posts counts once per post.
    page_rows, page_count, page_cut, page_other = fetch(dict(
        base, dimensions=[{'name': 'pagePath'}, {'name': 'sessionSource'}, {'name': 'sessionMedium'}],
        metrics=[{'name': 'screenPageViews'}, {'name': 'sessions'}, {'name': 'averageSessionDuration'}]))
    # Source rows without pagePath: each session counts once, so shares add up to 100%.
    source_rows, _, source_cut, source_other = fetch(dict(
        base, dimensions=[{'name': 'sessionSource'}, {'name': 'sessionMedium'}],
        metrics=[{'name': 'sessions'}, {'name': 'screenPageViews'}]))

    pages, ai_pages = {}, {}
    try:
        with out.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['pagePath', 'source', 'medium', 'ai_engine', 'pageviews', 'sessions',
                             'avg_session_sec'])
            for (path, source, medium), (views, sessions, duration) in page_rows:
                views, sessions = _num(views), _num(sessions)
                engine = ai_engine(source)
                writer.writerow([path, source, medium, engine, views, sessions,
                                 round(_num(duration, float), 1)])
                page = pages.setdefault(path, {'path': path, 'pageviews': 0, 'sessions': 0})
                page['pageviews'] += views
                page['sessions'] += sessions
                if engine:
                    entry = ai_pages.setdefault((engine, path), {'engine': engine, 'path': path,
                                                                 'sessions': 0, 'pageviews': 0})
                    entry['sessions'] += sessions
                    entry['pageviews'] += views
    except OSError:
        raise Failure('OUTPUT_UNWRITABLE') from None

    sources, engines, total_sessions, total_views = {}, {}, 0, 0
    for (source, medium), (sessions, views) in source_rows:
        sessions, views = _num(sessions), _num(views)
        total_sessions += sessions
        total_views += views
        sources[source] = sources.get(source, 0) + sessions
        engine = ai_engine(source)
        if engine:
            engines[engine] = engines.get(engine, 0) + sessions
    ai_sessions = sum(engines.values())

    def share(n):
        return round(n / total_sessions, 4) if total_sessions else 0.0

    return {
        'status': 'ok', 'property_id': prop, 'start': start, 'end': end, 'prefix': prefix,
        'includes_today': includes_today,
        'totals': {'sessions': total_sessions, 'pageviews': total_views},
        'pages': sorted(pages.values(), key=lambda p: (-p['pageviews'], p['path'])),
        'top_sources': [{'source': s, 'sessions': n, 'share': share(n)} for s, n in
                        sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SOURCES]],
        'source_count': len(sources),
        'ai': {'sessions': ai_sessions, 'share': share(ai_sessions),
               'engines': [{'engine': e, 'sessions': n, 'share': share(n)} for e, n in
                           sorted(engines.items(), key=lambda kv: (-kv[1], kv[0]))],
               'pages': sorted(ai_pages.values(),
                               key=lambda p: (p['engine'], -p['sessions'], p['path']))},
        'truncated': page_cut or source_cut, 'other_row': page_other or source_other,
        'rows': len(page_rows), 'row_count': page_count, 'csv': str(out),
    }


# --- command line -----------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure('USAGE_ERROR')


def _parser():
    parser = _Parser(prog='ga4_report.py', description='GA4 blog traffic report.')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    setup = commands.add_parser('configure', help='store a service account key and property ID')
    setup.add_argument('--key', required=True, help='service account JSON key file')
    setup.add_argument('--property', required=True, help='numeric GA4 property ID')
    commands.add_parser('status', help='show the stored settings (no network)')
    run = commands.add_parser('report', help='fetch the report, write a CSV, print a JSON summary')
    run.add_argument('--start', default='28daysAgo')
    run.add_argument('--end', default='today')
    run.add_argument('--prefix', default='/blog/')
    run.add_argument('--out', default='ga4-blog-report.csv')
    run.add_argument('--force', action='store_true', help='overwrite --out')
    return parser


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        if args.command == 'configure':
            result = configure(args.key, args.property)
        elif args.command == 'status':
            result = status()
        else:
            result = report(args.start, args.end, args.prefix, args.out, args.force)
    except Failure as failure:
        code = failure.code
    except KeyboardInterrupt:
        code = 'INTERRUPTED'
    except SystemExit as exit_:
        if exit_.code == 0:  # --help
            return 0
        code = 'USAGE_ERROR'
    else:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps({'status': 'failed', 'error': code, 'message': message_for(code)}),
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
