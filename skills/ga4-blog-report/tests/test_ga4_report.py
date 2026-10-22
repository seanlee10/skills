import base64
import csv
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import date, timedelta

import pytest

import ga4_report as g


def code_of(excinfo):
    return excinfo.value.code


# --- settings ---------------------------------------------------------------------------------

def test_configure_stores_private_copy(key_file, config, private_key):
    result = g.configure(str(key_file), '123456789')
    assert result['configured'] and result['property_id'] == '123456789'
    assert result['client_email'] == 'reporter@demo.iam.gserviceaccount.com'
    assert private_key[1] not in json.dumps(result)
    for name in ('service-account.json', 'settings.json'):
        assert (config / name).stat().st_mode & 0o777 == 0o600
    assert config.stat().st_mode & 0o777 == 0o700
    assert g.status()['configured'] is True


@pytest.mark.parametrize('value,expected', [
    ('G-ABC123', 'MEASUREMENT_ID_GIVEN'), ('g-abc', 'MEASUREMENT_ID_GIVEN'),
    ('12a4', 'PROPERTY_ID_INVALID'), ('', 'PROPERTY_ID_INVALID')])
def test_configure_rejects_bad_property(key_file, value, expected):
    with pytest.raises(g.Failure) as excinfo:
        g.configure(str(key_file), value)
    assert code_of(excinfo) == expected


def test_property_prefix_accepted(key_file):
    assert g.configure(str(key_file), 'properties/42')['property_id'] == '42'


@pytest.mark.parametrize('change', [
    {'type': 'authorized_user'}, {'client_email': ''}, {'private_key': 'not a key'},
    {'token_uri': 'https://evil.example/token'}])
def test_configure_rejects_non_service_account(key_file, change, config):
    data = json.loads(key_file.read_text())
    data.update(change)
    key_file.write_text(json.dumps(data))
    with pytest.raises(g.Failure) as excinfo:
        g.configure(str(key_file), '1')
    assert code_of(excinfo) == 'KEY_INVALID'
    assert not config.exists()


def test_configure_missing_and_garbage(tmp_path):
    with pytest.raises(g.Failure) as excinfo:
        g.configure(str(tmp_path / 'nope.json'), '1')
    assert code_of(excinfo) == 'KEY_SOURCE_MISSING'
    (tmp_path / 'bad.json').write_text('{')
    with pytest.raises(g.Failure) as excinfo:
        g.configure(str(tmp_path / 'bad.json'), '1')
    assert code_of(excinfo) == 'KEY_INVALID'


def test_configure_refuses_symlinked_dir(key_file, config, tmp_path):
    (tmp_path / 'elsewhere').mkdir()
    config.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(g.Failure) as excinfo:
        g.configure(str(key_file), '1')
    assert code_of(excinfo) == 'CONFIG_DIR_UNSAFE'


def test_status_unconfigured():
    assert g.status() == {'status': 'ok', 'configured': False, 'config_dir': g.CONFIG_DISPLAY}
    with pytest.raises(g.Failure) as excinfo:
        g.load_settings()
    assert code_of(excinfo) == 'NOT_CONFIGURED'


def test_loose_permissions_refused(key_file, config):
    g.configure(str(key_file), '1')
    os.chmod(config / 'service-account.json', 0o644)
    with pytest.raises(g.Failure) as excinfo:
        g.load_settings()
    assert code_of(excinfo) == 'KEY_FILE_UNSAFE'
    assert g.status()['configured'] is False


# --- dates and sources ------------------------------------------------------------------------

@pytest.mark.parametrize('start,end', [('28daysAgo', 'today'), ('2026-01-01', '2026-01-31'),
                                       ('yesterday', 'yesterday')])
def test_valid_dates(start, end):
    g.check_dates(start, end)


@pytest.mark.parametrize('start,end', [('last week', 'today'), ('2026-02-30', 'today'),
                                       ('today', '7daysAgo'), ('2026-1-1', 'today')])
def test_invalid_dates(start, end):
    with pytest.raises(g.Failure) as excinfo:
        g.check_dates(start, end)
    assert code_of(excinfo) == 'INVALID_DATE'


def test_includes_today():
    assert g.check_dates('7daysAgo', 'today') is True
    assert g.check_dates('7daysAgo', 'yesterday') is False
    assert g.check_dates('2020-01-01', (date.today() + timedelta(days=3)).isoformat()) is True


@pytest.mark.parametrize('source,engine', [
    ('chatgpt.com', 'ChatGPT'), ('ChatGPT.com', 'ChatGPT'), ('chat.openai.com', 'ChatGPT'),
    ('www.perplexity.ai', 'Perplexity'), ('gemini.google.com', 'Gemini'),
    ('copilot.microsoft.com', 'Copilot'), ('claude.ai', 'Claude'),
    ('google', ''), ('google.com', ''), ('(direct)', ''), ('naver', ''), ('openai.com', ''),
    ('notchatgpt.com', '')])
def test_ai_engine(source, engine):
    assert g.ai_engine(source) == engine


# --- Google calls -----------------------------------------------------------------------------

def _b64decode(part):
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


def test_access_token_signs_valid_jwt(monkeypatch, key_file, private_key):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    seen = {}

    def fake_post(url, body, headers):
        seen['url'], seen['body'] = url, body
        return 200, b'{"access_token":"tok","expires_in":3599}'

    monkeypatch.setattr(g, '_post', fake_post)
    g.configure(str(key_file), '1')
    key, _ = g.load_settings()
    assert g.access_token(key) == 'tok'
    assert seen['url'] == 'https://oauth2.googleapis.com/token'
    form = urllib.parse.parse_qs(seen['body'].decode())
    assert form['grant_type'] == ['urn:ietf:params:oauth:grant-type:jwt-bearer']
    header, claims, signature = form['assertion'][0].split('.')
    assert json.loads(_b64decode(header)) == {'alg': 'RS256', 'typ': 'JWT', 'kid': 'abc123'}
    claims_data = json.loads(_b64decode(claims))
    assert claims_data['scope'] == 'https://www.googleapis.com/auth/analytics.readonly'
    assert claims_data['iss'] == 'reporter@demo.iam.gserviceaccount.com'
    assert claims_data['exp'] - claims_data['iat'] == 3600
    private_key[0].public_key().verify(_b64decode(signature), f'{header}.{claims}'.encode(),
                                       padding.PKCS1v15(), hashes.SHA256())


@pytest.mark.parametrize('status,body,expected', [
    (400, b'{"error":"invalid_grant","error_description":"Invalid JWT Signature."}', 'AUTH_REJECTED'),
    (401, b'{}', 'AUTH_FAILED'), (500, b'oops', 'AUTH_FAILED')])
def test_access_token_failures(monkeypatch, key_file, status, body, expected):
    monkeypatch.setattr(g, '_post', lambda *a: (status, body))
    g.configure(str(key_file), '1')
    key, _ = g.load_settings()
    with pytest.raises(g.Failure) as excinfo:
        g.access_token(key)
    assert code_of(excinfo) == expected


def _error(code, status, message='', reason=None):
    details = [{'@type': 'type.googleapis.com/google.rpc.ErrorInfo', 'reason': reason}] if reason else []
    return json.dumps({'error': {'code': code, 'status': status, 'message': message,
                                 'details': details}}).encode()


@pytest.mark.parametrize('status,body,expected', [
    (403, _error(403, 'PERMISSION_DENIED', 'Google Analytics Data API has not been used in project 1',
                 'SERVICE_DISABLED'), 'API_DISABLED'),
    (403, _error(403, 'PERMISSION_DENIED', 'API is disabled'), 'API_DISABLED'),
    (403, _error(403, 'PERMISSION_DENIED', 'User does not have sufficient permissions'),
     'PROPERTY_ACCESS_DENIED'),
    (404, _error(404, 'NOT_FOUND'), 'PROPERTY_ACCESS_DENIED'),
    (401, _error(401, 'UNAUTHENTICATED'), 'AUTH_FAILED'),
    (429, _error(429, 'RESOURCE_EXHAUSTED'), 'QUOTA_EXHAUSTED'),
    (400, _error(400, 'INVALID_ARGUMENT'), 'REQUEST_INVALID'),
    (503, b'<html>', 'GA4_HTTP_ERROR')])
def test_api_failures(monkeypatch, status, body, expected):
    monkeypatch.setattr(g, '_post', lambda *a: (status, body))
    with pytest.raises(g.Failure) as excinfo:
        g.run_report('tok', '1', {})
    assert code_of(excinfo) == expected


def _row(dims, mets):
    return {'dimensionValues': [{'value': d} for d in dims],
            'metricValues': [{'value': str(m)} for m in mets]}


def test_run_report_follows_offsets(monkeypatch):
    calls = []

    def fake_post(url, body, headers):
        page = json.loads(body)
        calls.append((url, page['offset'], headers['Authorization']))
        rows = [_row(['/blog/a'], [1])] * (2 if page['offset'] == 0 else 1)
        return 200, json.dumps({'rowCount': 3, 'rows': rows}).encode()

    monkeypatch.setattr(g, '_post', fake_post)
    monkeypatch.setattr(g, 'PAGE_SIZE', 2)
    rows, count, truncated, other = g.run_report('tok', '42', {'x': 1})
    assert len(rows) == 3 and count == 3 and not truncated and not other
    assert [c[1] for c in calls] == [0, 2]
    assert calls[0][0] == 'https://analyticsdata.googleapis.com/v1beta/properties/42:runReport'
    assert calls[0][2] == 'Bearer tok'


def test_run_report_empty_and_truncated(monkeypatch):
    monkeypatch.setattr(g, '_post', lambda *a: (200, b'{"kind":"analyticsData#runReport"}'))
    assert g.run_report('tok', '1', {}) == ([], 0, False, False)
    monkeypatch.setattr(g, 'MAX_ROWS', 1)
    monkeypatch.setattr(g, '_post', lambda *a: (200, json.dumps({
        'rowCount': 5, 'rows': [_row(['x'], [1])], 'metadata': {'dataLossFromOtherRow': True}}).encode()))
    assert g.run_report('tok', '1', {})[2:] == (True, True)


@pytest.mark.parametrize('body', [b'not json', b'[1]', b'{"rows":[{"bad":1}],"rowCount":1}',
                                  b'{"rows":"x"}'])
def test_run_report_malformed(monkeypatch, body):
    monkeypatch.setattr(g, '_post', lambda *a: (200, body))
    with pytest.raises(g.Failure) as excinfo:
        g.run_report('tok', '1', {})
    assert code_of(excinfo) == 'RESPONSE_MALFORMED'


# --- report -----------------------------------------------------------------------------------

PAGE_ROWS = [
    (['/blog/a', 'google', 'organic'], ['100', '80', '42.25']),
    (['/blog/a', 'chatgpt.com', 'referral'], ['10', '8', '60']),
    (['/blog/b', 'chatgpt.com', 'referral'], ['5', '5', '30']),
    (['/blog/b', 'perplexity.ai', 'referral'], ['4', '3', '10']),
    (['/blog/c', '(direct)', '(none)'], ['50', '40', '5']),
]
SOURCE_ROWS = [
    (['google', 'organic'], ['78', '100']),
    (['chatgpt.com', 'referral'], ['12', '15']),
    (['perplexity.ai', 'referral'], ['3', '4']),
    (['(direct)', '(none)'], ['37', '50']),
]


def fake_fetch(requests):
    def fetch(body):
        requests.append(body)
        dims = [d['name'] for d in body['dimensions']]
        return (PAGE_ROWS, len(PAGE_ROWS), False, False) if 'pagePath' in dims else \
            (SOURCE_ROWS, len(SOURCE_ROWS), False, False)
    return fetch


def test_report_summary_and_csv(key_file, tmp_path):
    g.configure(str(key_file), '99')
    requests = []
    out = tmp_path / 'r.csv'
    summary = g.report('2026-10-01', '2026-10-07', '/blog/', str(out), False, fetch=fake_fetch(requests))
    assert all(r['dimensionFilter']['filter']['stringFilter'] ==
               {'matchType': 'BEGINS_WITH', 'value': '/blog/'} for r in requests)
    assert requests[0]['dateRanges'] == [{'startDate': '2026-10-01', 'endDate': '2026-10-07'}]
    assert summary['property_id'] == '99' and summary['includes_today'] is False
    assert summary['totals'] == {'sessions': 130, 'pageviews': 169}
    assert [p['path'] for p in summary['pages']] == ['/blog/a', '/blog/c', '/blog/b']
    assert summary['pages'][0] == {'path': '/blog/a', 'pageviews': 110, 'sessions': 88}
    assert summary['top_sources'][0] == {'source': 'google', 'sessions': 78, 'share': 0.6}
    assert summary['ai']['sessions'] == 15 and summary['ai']['share'] == round(15 / 130, 4)
    assert summary['ai']['engines'] == [
        {'engine': 'ChatGPT', 'sessions': 12, 'share': round(12 / 130, 4)},
        {'engine': 'Perplexity', 'sessions': 3, 'share': round(3 / 130, 4)}]
    assert [(p['engine'], p['path'], p['sessions']) for p in summary['ai']['pages']] == [
        ('ChatGPT', '/blog/a', 8), ('ChatGPT', '/blog/b', 5), ('Perplexity', '/blog/b', 3)]
    rows = list(csv.reader(out.open(encoding='utf-8')))
    assert rows[0] == ['pagePath', 'source', 'medium', 'ai_engine', 'pageviews', 'sessions', 'avg_session_sec']
    assert rows[1] == ['/blog/a', 'google', 'organic', '', '100', '80', '42.2']
    assert rows[2][3] == 'ChatGPT' and len(rows) == 6


def test_report_no_traffic(key_file, tmp_path):
    g.configure(str(key_file), '1')
    summary = g.report('7daysAgo', 'today', '/blog/', str(tmp_path / 'r.csv'), False,
                       fetch=lambda body: ([], 0, False, False))
    assert summary['totals'] == {'sessions': 0, 'pageviews': 0}
    assert summary['ai'] == {'sessions': 0, 'share': 0.0, 'engines': [], 'pages': []}
    assert summary['includes_today'] is True


def test_report_refuses_overwrite_before_network(key_file, tmp_path):
    g.configure(str(key_file), '1')
    out = tmp_path / 'r.csv'
    out.write_text('keep')
    with pytest.raises(g.Failure) as excinfo:
        g.report('7daysAgo', 'today', '/blog/', str(out), False, fetch=lambda b: pytest.fail('fetched'))
    assert code_of(excinfo) == 'OUTPUT_EXISTS' and out.read_text() == 'keep'
    g.report('7daysAgo', 'today', '/blog/', str(out), True, fetch=lambda b: ([], 0, False, False))
    assert out.read_text().startswith('pagePath,')


@pytest.mark.parametrize('prefix', ['blog/', '/my blog/', ''])
def test_report_invalid_prefix(prefix, tmp_path):
    with pytest.raises(g.Failure) as excinfo:
        g.report('7daysAgo', 'today', prefix, str(tmp_path / 'r.csv'), False)
    assert code_of(excinfo) == 'INVALID_PREFIX'


def test_report_not_configured(tmp_path):
    with pytest.raises(g.Failure) as excinfo:
        g.report('7daysAgo', 'today', '/blog/', str(tmp_path / 'r.csv'), False)
    assert code_of(excinfo) == 'NOT_CONFIGURED'


# --- command line -----------------------------------------------------------------------------

def _run(script, *args):
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True,
                          env=dict(os.environ))


@pytest.mark.parametrize('args', [[], ['bogus'], ['configure'], ['report', '--nope']])
def test_cli_usage_error(script, args):
    result = _run(script, *args)
    assert result.returncode == 2 and result.stdout == ''
    assert json.loads(result.stderr.splitlines()[-1]) == {
        'status': 'failed', 'error': 'USAGE_ERROR', 'message': g.MESSAGES['USAGE_ERROR']}


def test_cli_configure_status_and_report_failure(script, key_file, private_key):
    result = _run(script, 'configure', '--key', str(key_file), '--property', '7')
    assert result.returncode == 0 and private_key[1].splitlines()[1] not in result.stdout
    status = json.loads(_run(script, 'status').stdout)
    assert status['configured'] is True and status['property_id'] == '7'
    failed = _run(script, 'report', '--start', 'someday')
    assert failed.returncode == 2
    assert json.loads(failed.stderr.splitlines()[-1])['error'] == 'INVALID_DATE'


def test_cli_help(script):
    assert _run(script, '--help').returncode == 0


def test_messages_never_empty():
    assert all(m.strip() and len(m) < 200 for m in g.MESSAGES.values())
