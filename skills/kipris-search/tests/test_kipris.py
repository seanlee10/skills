import contextlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

import kipris_api as api

KEY = 'TEST-KEY-SECRET-NOT-REAL'
KEY_FILE = '~/.config/kipris-search/api-key'


def response(item='', total=0, page=1, size=10, code='00', success=None):
    success = '' if success is None else f'<successYN>{success}</successYN>'
    return (f'<response><header><resultCode>{code}</resultCode>{success}</header>'
            f'<body><items>{item}</items></body><count><totalCount>{total}</totalCount>'
            f'<pageNo>{page}</pageNo><numOfRows>{size}</numOfRows></count></response>').encode()


def cli(*args):
    """Run main() in-process; return (exit code, parsed JSON, raw stdout, raw stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = api.main(list(args))
    stdout, stderr = out.getvalue(), err.getvalue()
    assert KEY not in stdout + stderr
    for quoted in (urllib.parse.quote(KEY, safe=''), urllib.parse.quote_plus(KEY)):
        assert quoted not in stdout + stderr
    if code == 2:
        assert stdout == ''
        lines = stderr.strip().splitlines()
        return code, json.loads(lines[-1]), stdout, stderr
    assert stderr == ''
    return code, json.loads(stdout), stdout, stderr


def failure(*args):
    """Run a command that must fail as a whole; return its error code after checking the shape."""
    code, data, _, _ = cli(*args)
    assert code == 2
    assert set(data) == {'status', 'error', 'message'} and data['status'] == 'failed'
    assert data['message'] == api.message_for(data['error'])
    return data['error']


def configure(key=KEY):
    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', return_value=key):
        return cli('configure')


def no_fetch():
    return mock.patch.object(api, 'fetch', side_effect=AssertionError('unexpected network'))


# --- configure and status -------------------------------------------------------------------

def test_configuration_and_status_are_private_and_network_free():
    with no_fetch():
        code, data, _, _ = cli('status')
        assert (code, data) == (0, {'status': 'ok', 'configured': False,
                                    'remote_validation': 'not_performed', 'key_file': KEY_FILE})
        code, data, _, _ = configure()
        assert (code, data) == (0, {'status': 'ok', 'configured': True,
                                    'remote_validation': 'not_performed', 'key_file': KEY_FILE})
        assert api.load_key() == KEY
        assert stat.S_IMODE(api.key_path().stat().st_mode) == 0o600
        assert stat.S_IMODE(api.key_path().parent.stat().st_mode) == 0o700
        assert cli('status')[1]['configured'] is True


def test_key_lives_under_the_patched_home(home):
    assert api.key_path() == home / '.config' / 'kipris-search' / 'api-key'


def test_configure_replaces_the_existing_key():
    configure()
    configure('SECOND-TEST-KEY')
    assert api.load_key() == 'SECOND-TEST-KEY'
    assert [p.name for p in api.key_path().parent.iterdir()] == ['api-key']  # no temp file left


def test_configure_requires_an_interactive_terminal():
    with mock.patch('sys.stdin.isatty', return_value=False), \
            mock.patch.object(api.getpass, 'getpass', side_effect=AssertionError('prompted')):
        assert failure('configure') == 'CONFIGURE_NEEDS_TTY'
    assert not api.key_path().exists()


def test_configure_refuses_echoed_input():
    def echoing(prompt=''):
        import warnings
        warnings.warn('Can not control echo on the terminal.', api.getpass.GetPassWarning)
        return KEY

    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', side_effect=echoing):
        assert failure('configure') == 'HIDDEN_INPUT_UNAVAILABLE'
    assert not api.key_path().exists()


@pytest.mark.parametrize('typed', ['', '   ', 'two words', 'x' * 4097])
def test_configure_rejects_empty_or_whitespace_keys(typed):
    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', return_value=typed):
        assert failure('configure') == 'KEY_INPUT_INVALID'
    assert not api.key_path().exists()


def test_configure_refuses_a_symlinked_key_folder(home, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (home / '.config').mkdir()
    (home / '.config' / 'kipris-search').symlink_to(elsewhere)
    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', return_value=KEY):
        assert failure('configure') == 'KEY_DIR_UNSAFE'
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize('error', [EOFError(), OSError('disk'), UnicodeError()])
def test_configure_local_input_errors(error):
    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', side_effect=error):
        assert failure('configure') == 'LOCAL_SETUP_FAILED'


def test_interrupt_is_reported():
    with mock.patch('sys.stdin.isatty', return_value=True), \
            mock.patch.object(api.getpass, 'getpass', side_effect=KeyboardInterrupt):
        assert failure('configure') == 'INTERRUPTED'


def test_broad_permissions_and_symlinks_are_rejected(tmp_path):
    configure()
    api.key_path().chmod(0o644)
    assert cli('status')[1]['configured'] is False
    with no_fetch():
        assert failure('search', '--right', 'trademark', '--query', '커피') == 'KEY_FILE_UNSAFE'
    api.key_path().unlink()
    target = tmp_path / 'target'
    target.write_text(KEY)
    target.chmod(0o600)
    api.key_path().symlink_to(target)
    assert cli('status')[1]['configured'] is False
    with no_fetch():
        assert failure('search', '--right', 'trademark', '--query', '커피') == 'KEY_FILE_UNREADABLE'


def test_malformed_key_file_is_rejected():
    configure()
    api.key_path().write_text('two words\n')
    with no_fetch():
        assert failure('search', '--right', 'trademark', '--query', '커피') == 'KEY_INVALID'


def test_search_without_a_key_does_not_touch_the_network():
    with no_fetch():
        assert failure('search', '--right', 'trademark', '--query', '커피') == 'KEY_NOT_CONFIGURED'


# --- search ---------------------------------------------------------------------------------

def test_search_preserves_numbers_and_normalizes_fields():
    configure()
    payload = response('<item><applicationNumber>001234</applicationNumber>'
                       '<inventionTitle>전지</inventionTitle><registerStatus>등록</registerStatus>'
                       '<applicantName>가</applicantName><applicantName>나</applicantName>'
                       '<ipcNumber></ipcNumber></item>', total=12)
    with mock.patch.object(api, 'fetch', return_value=payload) as fetch:
        code, data, _, _ = cli('search', '--right', 'patent', '--query', '이차전지')
    assert code == 0
    assert (data['status'], data['ok']) == ('ok', True)
    assert fetch.call_count == 1
    params = fetch.call_args.args[1]
    assert (params['patent'], params['utility'], params['word']) == ('true', 'false', '이차전지')
    assert (params['pageNo'], params['numOfRows']) == ('1', '10')
    result = data['results'][0]
    assert (result['ok'], result['right']) == (True, 'patent')
    assert (result['total'], result['returned'], result['has_more']) == (12, 1, True)
    assert (result['page'], result['page_size']) == (1, 10)
    assert result['retrieved_at'].endswith('+00:00')
    record = result['records'][0]
    assert record['application_number'] == '001234'
    assert record['applicant'] == ['가', '나']
    assert record['title'] == '전지'
    assert record['ipc'] == ''
    assert record['registration_number'] is None


def test_utility_only_and_number_filters():
    configure()
    with mock.patch.object(api, 'fetch', return_value=response(page=3, size=500)) as fetch:
        code, _, _, _ = cli('search', '--right', 'utility', '--application-number', '0020140061596',
                            '--registration-number', ' 1014426360000 ', '--applicant', '삼성전자',
                            '--page', '3', '--size', '500')
    assert code == 0
    params = fetch.call_args.args[1]
    assert (params['patent'], params['utility']) == ('false', 'true')
    assert params['applicationNumber'] == '0020140061596'
    assert params['registerNumber'] == '1014426360000'
    assert params['applicant'] == '삼성전자'
    assert (params['pageNo'], params['numOfRows']) == ('3', '500')


def test_all_rights_are_three_calls_and_partial_failure_is_explicit():
    configure()
    side_effect = [response(), api.Failure('KIPRIS_API_20'), response()]
    with mock.patch.object(api, 'fetch', side_effect=side_effect) as fetch:
        code, data, _, _ = cli('search', '--right', 'all', '--query', '의자')
    assert code == 1
    assert (data['status'], data['ok']) == ('partial', False)
    assert fetch.call_count == 3
    assert [r['right'] for r in data['results']] == ['patent-utility', 'trademark', 'design']
    assert [r['ok'] for r in data['results']] == [True, False, True]
    failed = data['results'][1]
    assert failed == {'ok': False, 'right': 'trademark', 'error': 'KIPRIS_API_20',
                      'message': api.MESSAGES['KIPRIS_API_ERROR']}
    calls = fetch.call_args_list
    assert calls[0].args[1]['word'] == '의자'
    assert calls[1].args[1]['trademarkName'] == '의자'
    assert calls[1].args[1]['internationalMark'] == 'true'
    assert calls[2].args[1]['articleName'] == '의자'
    assert calls[2].args[1]['cancle'] == 'true'


def test_single_right_failure_is_reported_in_results():
    configure()
    with mock.patch.object(api, 'fetch', side_effect=api.Failure('KIPRIS_HTTP_503')):
        code, data, _, _ = cli('search', '--right', 'design', '--query', '의자')
    assert code == 1
    assert data['status'] == 'partial'
    assert data['results'] == [{'ok': False, 'right': 'design', 'error': 'KIPRIS_HTTP_503',
                                'message': api.MESSAGES['KIPRIS_HTTP_ERROR']}]


@pytest.mark.parametrize('extra', [
    [], ['--query', '   '], ['--query', '전지', '--size', '501'], ['--query', '전지', '--size', '0'],
    ['--query', '전지', '--page', '0'],
])
def test_invalid_search_inputs_do_not_consume_calls(extra):
    configure()
    with no_fetch():
        assert failure('search', '--right', 'patent-utility', *extra) == 'INVALID_SEARCH_ARGUMENTS'


@pytest.mark.parametrize('args', [
    [], ['search'], ['search', '--right', 'everything', '--query', '커피'],
    ['search', '--right', 'trademark', '--query', '커피', '--page', 'two'], ['nonsense'],
    ['search', '--right', 'trademark', '--query', KEY, '--bogus'],
])
def test_usage_errors_never_echo_arguments(args):
    with no_fetch():
        assert failure(*args) == 'USAGE_ERROR'


def test_choices_and_services_are_unchanged():
    assert list(api.SERVICES) == ['patent-utility', 'trademark', 'design']
    assert api.SERVICES['patent-utility'].name == 'patUtiModInfoSearchSevice'
    assert api.SERVICES['trademark'].name == 'trademarkInfoSearchService'
    assert api.SERVICES['design'].name == 'designInfoSearchService'
    assert 'cancle' in api.SERVICES['design'].flags
    assert len(api.SERVICES['trademark'].flags) == 30


# --- response parsing -----------------------------------------------------------------------

def test_zero_matches_are_a_result_not_an_error():
    result = api.parse_page(response(), api.SERVICES['trademark'], 1)
    assert (result['total'], result['returned'], result['has_more'], result['records']) == (0, 0, False, [])


@pytest.mark.parametrize('payload,code', [
    (response(code='30'), 'KIPRIS_API_30'),
    (response(code='99'), 'KIPRIS_API_99'),
    (response(code=KEY), 'KIPRIS_API_ERROR'),
    (b'<response><header></header></response>', 'KIPRIS_API_ERROR'),
    (response(success='N'), 'KIPRIS_REQUEST_FAILED'),
    (b'<html>server error</html>', 'RESPONSE_MALFORMED'),
    (b'not xml at all', 'RESPONSE_MALFORMED'),
    (b'<response/>', 'RESPONSE_MALFORMED'),
    (b'<!DOCTYPE x><response/>', 'RESPONSE_DTD_OR_ENTITY_FORBIDDEN'),
    (b'<?xml version="1.0"?><!ENTITY a "b"><response/>', 'RESPONSE_DTD_OR_ENTITY_FORBIDDEN'),
    (response().replace(b'<totalCount>0</totalCount>', b''), 'RESPONSE_COUNT_MISSING'),
    (response(page=2), 'RESPONSE_PAGE_MISMATCH'),
    (response(size=0), 'RESPONSE_PAGE_MISMATCH'),
    (response('<item/><item/>', total=1), 'RESPONSE_PAGE_MISMATCH'),
    (response(total=10), 'RESPONSE_ITEMS_MISSING'),
    (response(total=0).replace(b'<items></items>', b''), 'RESPONSE_ITEMS_MISSING'),
])
def test_errors_and_invalid_envelopes_are_not_zero_results(payload, code):
    with pytest.raises(api.Failure) as caught:
        api.parse_page(payload, api.SERVICES['trademark'], 1)
    assert caught.value.code == code
    assert KEY not in str(caught.value)


def test_api_error_code_reaches_the_results():
    configure()
    with mock.patch.object(api, 'fetch', return_value=response(code='30')):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert code == 1
    assert data['results'][0]['error'] == 'KIPRIS_API_30'
    assert 'total' not in data['results'][0] and 'records' not in data['results'][0]


def test_credential_echo_is_not_printed():
    configure()
    for title in (KEY, urllib.parse.quote(KEY, safe='')):
        payload = response(f'<item><title>{title}</title></item>', total=1)
        with mock.patch.object(api, 'fetch', return_value=payload):
            code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
        assert code == 1
        assert data['results'][0]['error'] == 'CREDENTIAL_ECHOED'
        assert 'records' not in data['results'][0]
    with mock.patch.object(api, 'fetch', return_value=response(code=KEY)):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert code == 1 and data['results'][0]['error'] == 'KIPRIS_API_ERROR'


# --- transport ------------------------------------------------------------------------------

def _opener(**behaviour):
    opener = mock.Mock()
    if 'error' in behaviour:
        opener.open.side_effect = behaviour['error']
    else:
        body = mock.MagicMock()
        body.__enter__.return_value.read.side_effect = lambda n: behaviour['payload'][:n]
        opener.open.return_value = body
    return opener


def test_transport_uses_official_https_and_suppresses_raw_errors():
    configure()
    opener = _opener(error=urllib.error.HTTPError(
        'https://other.example/?ServiceKey=' + KEY, 403, KEY, {}, None))
    with mock.patch.object(api.urllib.request, 'build_opener', return_value=opener) as build:
        code, data, _, _ = cli('search', '--right', 'design', '--query', '의자')
    assert code == 1
    assert data['results'][0]['error'] == 'KIPRIS_HTTP_403'
    opener.open.assert_called_once()
    assert opener.open.call_args.kwargs['timeout'] == 30
    url = urllib.parse.urlsplit(opener.open.call_args.args[0])
    assert (url.scheme, url.hostname, url.port) == ('https', 'plus.kipris.or.kr', None)
    assert url.path == '/kipo-api/kipi/designInfoSearchService/getAdvancedSearch'
    assert urllib.parse.parse_qs(url.query)['ServiceKey'] == [KEY]
    handlers = build.call_args.args
    proxy = next(h for h in handlers if isinstance(h, api.urllib.request.ProxyHandler))
    assert proxy.proxies == {}
    assert any(isinstance(h, api.NoRedirect) for h in handlers)
    assert api.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example/') is None


@pytest.mark.parametrize('error', [urllib.error.URLError('down ' + KEY), TimeoutError(), OSError(KEY)])
def test_network_errors_are_reported_without_detail(error):
    configure()
    with mock.patch.object(api.urllib.request, 'build_opener', return_value=_opener(error=error)):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert code == 1
    assert data['results'][0]['error'] == 'KIPRIS_NETWORK_ERROR'


def test_odd_http_status_falls_back_to_the_generic_code():
    configure()
    error = urllib.error.HTTPError('https://plus.kipris.or.kr/', 0, '', {}, None)
    with mock.patch.object(api.urllib.request, 'build_opener', return_value=_opener(error=error)):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert data['results'][0]['error'] == 'KIPRIS_HTTP_ERROR'


def test_oversized_response_is_refused():
    configure()
    payload = b'x' * (8 * 1024 * 1024 + 1)
    with mock.patch.object(api.urllib.request, 'build_opener', return_value=_opener(payload=payload)):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert code == 1
    assert data['results'][0]['error'] == 'RESPONSE_TOO_LARGE'


def test_successful_transport_round_trip():
    configure()
    payload = response('<item><title>커피</title><applicationNumber>4020260000001</applicationNumber></item>',
                       total=1)
    with mock.patch.object(api.urllib.request, 'build_opener', return_value=_opener(payload=payload)):
        code, data, _, _ = cli('search', '--right', 'trademark', '--query', '커피')
    assert code == 0
    assert data['results'][0]['records'][0]['application_number'] == '4020260000001'


# --- error contract -------------------------------------------------------------------------

def test_every_raised_code_has_a_message():
    source = Path(api.__file__).read_text(encoding='utf-8')
    raised = set(re.findall(r"Failure\('([A-Z_0-9]+)'\)", source))
    assert raised, 'no Failure codes found'
    assert raised <= set(api.MESSAGES), sorted(raised - set(api.MESSAGES))


def test_messages_are_fixed_english_without_secrets_or_urls():
    for code, message in api.MESSAGES.items():
        assert re.fullmatch(r'[A-Z][A-Z0-9_]+', code), code
        assert message.isascii() and message.strip() == message and message.endswith('.'), code
        assert '://' not in message and 'ServiceKey' not in message, code


@pytest.mark.parametrize('code,base', [
    ('KIPRIS_HTTP_403', 'KIPRIS_HTTP_ERROR'), ('KIPRIS_HTTP_503', 'KIPRIS_HTTP_ERROR'),
    ('KIPRIS_API_30', 'KIPRIS_API_ERROR'), ('KIPRIS_API_ERROR', 'KIPRIS_API_ERROR'),
    ('KEY_NOT_CONFIGURED', 'KEY_NOT_CONFIGURED'),
])
def test_message_for_dynamic_codes(code, base):
    assert api.message_for(code) == api.MESSAGES[base]


def test_unknown_codes_get_the_generic_message():
    assert api.message_for('KIPRIS_API_3') == api.GENERIC_MESSAGE
    assert api.message_for('KIPRIS_HTTP_40') == api.GENERIC_MESSAGE
    assert api.message_for('ValueError') == api.GENERIC_MESSAGE


def test_unexpected_exceptions_are_reported_by_type_only():
    configure()
    with mock.patch.object(api, 'search_page', side_effect=ValueError(KEY)):
        assert failure('search', '--right', 'trademark', '--query', '커피') == 'ValueError'


def test_script_runs_standalone_and_writes_no_bytecode(script, home):
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONDONTWRITEBYTECODE'}
    env['HOME'] = str(home)
    proc = subprocess.run([sys.executable, str(script), 'status'], capture_output=True, text=True,
                          env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {'status': 'ok', 'configured': False,
                                       'remote_validation': 'not_performed', 'key_file': KEY_FILE}
    assert not (script.parent / '__pycache__').exists()
    proc = subprocess.run([sys.executable, str(script), 'search', '--right', 'trademark'],
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 2 and proc.stdout == ''
    assert json.loads(proc.stderr.strip().splitlines()[-1])['error'] == 'INVALID_SEARCH_ARGUMENTS'
