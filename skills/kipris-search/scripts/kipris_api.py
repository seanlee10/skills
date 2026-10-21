# /// script
# requires-python = "==3.11.*"
# dependencies = []
# ///
"""Store a KIPRISPlus API key privately and run bounded KIPRISPlus list searches (stdlib only).

Usage: uv run kipris_api.py configure          (local terminal only; hidden input)
       uv run kipris_api.py status             (no network; never prints the key)
       uv run kipris_api.py search --right {patent-utility,patent,utility,trademark,design,all}
                                   [--query T] [--applicant T] [--application-number N]
                                   [--registration-number N] [--page P] [--size S]

Exit 0: JSON on stdout. Exit 1 (search only): JSON on stdout with "status":"partial", at least
one right failed. Exit 2: {"status":"failed","error":CODE,"message":str} on stderr.
"""
import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside the skill folder

import argparse
import getpass
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Service:
    name: str
    keyword: str
    applicant: str
    registration: str
    flags: tuple
    fields: dict


COMMON_FIELDS = {
    'application_number': 'applicationNumber', 'application_date': 'applicationDate',
    'publication_number': 'publicationNumber', 'publication_date': 'publicationDate',
    'applicant': 'applicantName',
}
# The single definition of service names, input/output fields and default flags. The official
# spellings (patUtiModInfoSearchSevice, cancle) are intentional.
SERVICES = {
    'patent-utility': Service(
        'patUtiModInfoSearchSevice', 'word', 'applicant', 'registerNumber',
        ('patent', 'utility'),
        dict(COMMON_FIELDS, title='inventionTitle', status='registerStatus',
             registration_number='registerNumber', registration_date='registerDate',
             open_number='openNumber', open_date='openDate', ipc='ipcNumber',
             abstract='astrtCont', image_url='drawing')),
    'trademark': Service(
        'trademarkInfoSearchService', 'trademarkName', 'applicantName', 'registerNumber',
        tuple(('application registration refused expiration withdrawal publication cancel '
               'abandonment trademark serviceMark businessEmblem collectiveMark geoOrgMark '
               'trademarkServiceMark certMark geoCertMark internationalMark character figure '
               'compositionCharacter figureComposition fragrance sound color colorMixed '
               'dimension hologram invisible motion visual').split()),
        dict(COMMON_FIELDS, title='title', status='applicationStatus',
             registration_number='registrationNumber', registration_date='registrationDate',
             owner='regPrivilegeName', classification='classificationCode',
             vienna_code='viennaCode', image_url='drawing')),
    'design': Service(
        'designInfoSearchService', 'articleName', 'applicantName', 'registrationNumber',
        tuple(('open rejection destroy cancle notice registration invalid abandonment '
               'simi part etc').split()),
        dict(COMMON_FIELDS, title='articleName', status='applicationStatus',
             registration_number='registrationNumber', registration_date='registrationDate',
             classification='designMainClassification', inventor='inventorName',
             open_number='openNumber', open_date='openDate', image_url='imagePath')),
}

HOST = 'plus.kipris.or.kr'
MAX_RESPONSE = 8 * 1024 * 1024
TIMEOUT = 30
KEY_FILE_DISPLAY = '~/.config/kipris-search/api-key'

# Fixed English message per error code. A message never contains the key, a URL, a path or
# any part of a KIPRIS response. Every code is documented in references/errors.md.
MESSAGES = {
    # command line
    'USAGE_ERROR': 'Invalid command-line arguments. Usage: kipris_api.py {configure,status,search} ...; see --help.',
    'INVALID_SEARCH_ARGUMENTS': 'A search needs at least one non-blank search condition, --page of 1 or more and --size from 1 to 500; nothing was sent.',
    'INTERRUPTED': 'The command was interrupted before it finished.',
    # configure
    'CONFIGURE_NEEDS_TTY': 'configure must be run by the user in a local interactive terminal; never paste the key into a chat.',
    'HIDDEN_INPUT_UNAVAILABLE': 'This terminal cannot hide typed input, so the key was not read; run configure in a normal local terminal.',
    'KEY_INPUT_INVALID': 'The key was empty, contained whitespace or was over 4096 characters; nothing was saved.',
    'KEY_DIR_UNSAFE': 'The key folder is a symbolic link; use a regular folder. Nothing was saved.',
    'LOCAL_SETUP_FAILED': 'The local key setup or input could not be completed.',
    # key file
    'KEY_NOT_CONFIGURED': 'No KIPRISPlus API key is configured; the user runs configure in a local terminal.',
    'KEY_FILE_UNREADABLE': 'The key file could not be opened (it may be a symbolic link or unreadable); run configure again.',
    'KEY_FILE_UNSAFE': 'The key file must be a regular file owned by the user with mode 600.',
    'KEY_INVALID': 'The stored key is empty, contains whitespace or is too long; run configure again.',
    # transport
    'KIPRIS_NETWORK_ERROR': 'KIPRIS could not be reached or timed out; nothing was retried.',
    # Dynamic codes KIPRIS_HTTP_<status> (e.g. KIPRIS_HTTP_403) all map to this message; see message_for().
    'KIPRIS_HTTP_ERROR': 'KIPRIS answered with an HTTP error; the error code carries the HTTP status.',
    'RESPONSE_TOO_LARGE': 'The KIPRIS response exceeded the 8 MiB limit; request a smaller --size.',
    # response
    'RESPONSE_DTD_OR_ENTITY_FORBIDDEN': 'The KIPRIS response declares a DTD or entities and was rejected.',
    'RESPONSE_MALFORMED': 'The response is not a KIPRIS XML response; do not read it as zero results.',
    # Dynamic codes KIPRIS_API_<2-digit result code> (e.g. KIPRIS_API_30) all map to this message.
    'KIPRIS_API_ERROR': 'KIPRIS returned an API error; check the key, the product permission and its period, and the call limit.',
    'KIPRIS_REQUEST_FAILED': 'KIPRIS reported that the request failed.',
    'RESPONSE_COUNT_MISSING': 'The KIPRIS response has no total count or page information.',
    'RESPONSE_PAGE_MISMATCH': 'The counts or page information in the KIPRIS response do not match the request.',
    'RESPONSE_ITEMS_MISSING': 'The KIPRIS response is missing its result items; do not read it as zero results.',
    'CREDENTIAL_ECHOED': 'The KIPRIS response contained the credential, so its results were withheld.',
}
GENERIC_MESSAGE = 'Unexpected internal error.'
_HTTP_CODE = re.compile(r'KIPRIS_HTTP_\d{3}')
_API_CODE = re.compile(r'KIPRIS_API_\d{2}')


class Failure(Exception):
    """A failure with a fixed error code; the code is the only payload."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def message_for(code):
    if code in MESSAGES:
        return MESSAGES[code]
    if _HTTP_CODE.fullmatch(code):
        return MESSAGES['KIPRIS_HTTP_ERROR']
    if _API_CODE.fullmatch(code):
        return MESSAGES['KIPRIS_API_ERROR']
    return GENERIC_MESSAGE


def key_path():
    return Path.home() / '.config' / 'kipris-search' / 'api-key'


def _valid_key(key):
    return bool(key) and len(key) <= 4096 and not any(c.isspace() for c in key)


def load_key():
    path = key_path()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise Failure('KEY_NOT_CONFIGURED') from None
    except OSError:
        raise Failure('KEY_FILE_UNREADABLE') from None
    with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Failure('KEY_FILE_UNSAFE')
        try:
            key = stream.read(4097).strip()
        except UnicodeError:
            raise Failure('KEY_INVALID') from None
    if not _valid_key(key):
        raise Failure('KEY_INVALID')
    return key


def _configured_summary(configured):
    return {'status': 'ok', 'configured': configured, 'remote_validation': 'not_performed',
            'key_file': KEY_FILE_DISPLAY}


def configure():
    if not sys.stdin.isatty():
        raise Failure('CONFIGURE_NEEDS_TTY')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('KIPRISPlus API key (input hidden): ').strip()
    except getpass.GetPassWarning:
        raise Failure('HIDDEN_INPUT_UNAVAILABLE') from None
    if not _valid_key(key):
        raise Failure('KEY_INPUT_INVALID')
    path = key_path()
    if path.parent.is_symlink():
        raise Failure('KEY_DIR_UNSAFE')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(key + '\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return _configured_summary(True)


def status():
    try:
        load_key()  # validates the file; the key value is never printed
        return _configured_summary(True)
    except Failure:
        return _configured_summary(False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(service, params, key):
    endpoint = f'https://{HOST}/kipo-api/kipi/{service.name}/getAdvancedSearch'
    url = endpoint + '?' + urllib.parse.urlencode(dict(params, ServiceKey=key))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=TIMEOUT) as response:
            payload = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        status_code = error.code if isinstance(error.code, int) and 100 <= error.code <= 599 else None
        raise Failure(f'KIPRIS_HTTP_{status_code}' if status_code else 'KIPRIS_HTTP_ERROR') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Failure('KIPRIS_NETWORK_ERROR') from None
    if len(payload) > MAX_RESPONSE:
        raise Failure('RESPONSE_TOO_LARGE')
    return payload


def parse_page(payload, service, requested_page):
    if re.search(br'<!\s*(DOCTYPE|ENTITY)', payload, re.I):
        raise Failure('RESPONSE_DTD_OR_ENTITY_FORBIDDEN')
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise Failure('RESPONSE_MALFORMED') from None
    if root.tag != 'response' or root.find('./header') is None:
        raise Failure('RESPONSE_MALFORMED')
    code = (root.findtext('./header/resultCode') or '').strip()
    if code != '00':
        # Only a 2-digit code is put into the error code; anything else could echo response text.
        raise Failure(f'KIPRIS_API_{code}' if re.fullmatch(r'\d{2}', code) else 'KIPRIS_API_ERROR')
    if (root.findtext('./header/successYN') or '').strip().upper() == 'N':
        raise Failure('KIPRIS_REQUEST_FAILED')
    try:
        total = int(root.findtext('./count/totalCount', ''))
        page = int(root.findtext('./count/pageNo', ''))
        size = int(root.findtext('./count/numOfRows', ''))
    except ValueError:
        raise Failure('RESPONSE_COUNT_MISSING') from None
    items = root.findall('./body/items/item')
    if total < 0 or page != requested_page or size < 1 or len(items) > size or len(items) > total:
        raise Failure('RESPONSE_PAGE_MISMATCH')
    if root.find('./body/items') is None or (not items and total > (page - 1) * size):
        raise Failure('RESPONSE_ITEMS_MISSING')
    records = []
    for item in items:
        record = {}
        for field, tag in service.fields.items():
            values = [''.join(node.itertext()).strip() for node in item.findall(tag)]
            record[field] = None if not values else values[0] if len(values) == 1 else values
        records.append(record)
    return {'total': total, 'page': page, 'page_size': size, 'returned': len(records),
            'has_more': page * size < total, 'records': records}


def search_page(right, filters, page, size, key):
    spec_right = 'patent-utility' if right in ('patent', 'utility') else right
    service = SERVICES[spec_right]
    params = dict.fromkeys(service.flags, 'true')
    if right == 'patent':
        params['utility'] = 'false'
    if right == 'utility':
        params['patent'] = 'false'
    mapping = {'query': service.keyword, 'applicant': service.applicant,
               'application_number': 'applicationNumber', 'registration_number': service.registration}
    params.update({mapping[name]: value for name, value in filters.items() if value})
    params.update(pageNo=str(page), numOfRows=str(size))
    result = {'ok': True, 'right': right}
    result.update(parse_page(fetch(service, params, key), service, page))
    result.update(filters=filters, retrieved_at=datetime.now(timezone.utc).isoformat())
    serialized = json.dumps(result, ensure_ascii=False)
    if any(secret in serialized for secret in (key, urllib.parse.quote(key, safe=''), urllib.parse.quote_plus(key))):
        raise Failure('CREDENTIAL_ECHOED')
    return result


def search(args):
    filters = {field: getattr(args, field) for field in
               ('query', 'applicant', 'application_number', 'registration_number')}
    filters = {field: value.strip() for field, value in filters.items() if value and value.strip()}
    if not filters or args.page < 1 or not 1 <= args.size <= 500:
        raise Failure('INVALID_SEARCH_ARGUMENTS')
    key = load_key()
    rights = list(SERVICES) if args.right == 'all' else [args.right]
    results = []
    for right in rights:  # one request per right, one page each; no retry, no next page
        try:
            results.append(search_page(right, filters, args.page, args.size, key))
        except Failure as error:
            results.append({'ok': False, 'right': right, 'error': error.code,
                            'message': message_for(error.code)})
    ok = all(result['ok'] for result in results)
    return {'status': 'ok' if ok else 'partial', 'ok': ok, 'results': results}


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse's message may echo arguments; keep it out of stderr
        raise Failure('USAGE_ERROR')


def _parser():
    parser = _Parser(prog='kipris_api.py', description='Private KIPRISPlus key setup and bounded list searches.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('configure', help='save the key from hidden input in a local terminal')
    commands.add_parser('status', help='check the local setup without the network or printing the key')
    found = commands.add_parser('search', help='request one page for the chosen right(s)')
    found.add_argument('--right', choices=[*SERVICES, 'patent', 'utility', 'all'], required=True)
    for field in ('query', 'applicant', 'application-number', 'registration-number'):
        found.add_argument('--' + field)
    found.add_argument('--page', type=int, default=1)
    found.add_argument('--size', type=int, default=10)
    return parser


def _fail(code):
    sys.stderr.write(json.dumps({'status': 'failed', 'error': code, 'message': message_for(code)},
                                ensure_ascii=False) + '\n')
    return 2


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        if args.command == 'configure':
            output = configure()
        elif args.command == 'status':
            output = status()
        else:
            output = search(args)
    except Failure as error:
        return _fail(error.code)
    except KeyboardInterrupt:
        return _fail('INTERRUPTED')
    except (OSError, UnicodeError, EOFError):
        return _fail('LOCAL_SETUP_FAILED')
    except Exception as error:  # never print tracebacks, the key or response text
        return _fail(type(error).__name__)
    sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    return 0 if output.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
