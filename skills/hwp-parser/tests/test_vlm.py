import base64
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import PNG, SKILL

sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / 'scripts'))

import hwp2md  # noqa: E402
from hwp_parser import vlm  # noqa: E402
from hwp_parser.extract import Failure  # noqa: E402
from hwp_parser.model import Asset, Document, Image  # noqa: E402

KEYS = {'GROQ_API_KEY': 'groq-test-key', 'XAI_API_KEY': 'xai-test-key'}
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 16


def reply(content, raw=None):
    """A fake HTTP response object as returned by opener.open(...).__enter__()."""
    if raw is None:
        raw = json.dumps({'model': 'm', 'choices': [{'message': {'content': content}}]})
    return io.BytesIO(raw.encode('utf-8') if isinstance(raw, str) else raw)


def mock_opener(opener, content='{"text": "도장"}', raw=None):
    opener.return_value.open.return_value.__enter__.return_value = reply(content, raw)
    return opener


def sent_request(opener):
    return opener.return_value.open.call_args.args[0]


def image_doc(*assets):
    return Document('hwpx', [Image(a.id) for a in assets], {a.id: a for a in assets}, [])


@pytest.mark.parametrize('provider', ['groq', 'xai'])
def test_request_contract(provider, tmp_path):
    model, endpoint, key_name = vlm.PROVIDERS[provider]
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    body = vlm.build_request(provider, img)
    assert body['model'] == model
    assert body['response_format'] == {'type': 'json_object'}
    assert body['stream'] is False
    content = body['messages'][0]['content']
    prompt = content[0]['text']
    assert '"text"' in prompt and 'uncertain_regions' in prompt
    url = content[1]['image_url']['url']
    assert url == 'data:image/png;base64,' + base64.b64encode(PNG).decode('ascii')
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener)
        assert vlm.describe(provider, img) == '도장'
    req = sent_request(opener)
    assert req.full_url == endpoint and req.get_method() == 'POST'
    assert req.get_header('Authorization') == 'Bearer ' + KEYS[key_name]
    assert json.loads(req.data) == body
    assert opener.return_value.open.call_args.kwargs['timeout'] == 90
    handler = opener.call_args.args[0]
    assert issubclass(handler, urllib.request.HTTPRedirectHandler)
    assert handler().redirect_request(None, None, 302, 'Found', {}, endpoint + '/x') is None
    assert opener.return_value.open.call_count == 1  # one POST, no retries


def test_jpeg_data_url(tmp_path):
    img = tmp_path / 'a.jpg'
    img.write_bytes(JPEG)
    url = vlm.build_request('groq', img)['messages'][0]['content'][1]['image_url']['url']
    assert url.startswith('data:image/jpeg;base64,')


def test_missing_key_sends_nothing(tmp_path, capsys):
    doc = image_doc(Asset('a0', PNG, '.png', 'image/png'))
    with patch.dict(vlm.os.environ, {}, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        with pytest.raises(Failure) as e:
            vlm.annotate(doc, tmp_path, 'groq')
        assert str(e.value) == 'GROQ_API_KEY_MISSING'
        assert opener.call_count == 0
        with pytest.raises(Failure) as e:
            vlm.annotate(doc, tmp_path, 'xai')
        assert str(e.value) == 'XAI_API_KEY_MISSING'
        assert opener.call_count == 0
    assert 'sending' not in capsys.readouterr().err


def test_blank_key_is_missing(tmp_path):
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    with patch.dict(vlm.os.environ, {'GROQ_API_KEY': '   '}, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        with pytest.raises(Failure) as e:
            vlm.describe('groq', img)
    assert str(e.value) == 'GROQ_API_KEY_MISSING' and opener.call_count == 0


def test_does_not_read_dotenv(make_hwpx, tmp_path, monkeypatch, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')
    planted = [tmp_path / '.env', SKILL / '.env', SKILL / 'scripts' / '.env']
    assert not any(p.exists() for p in planted[1:])  # never clobber a real file
    monkeypatch.chdir(tmp_path)
    try:
        for p in planted:
            p.write_text('GROQ_API_KEY=x\n', encoding='utf-8')
        with patch.dict(vlm.os.environ, {}, clear=True), \
             patch.object(vlm.urllib.request, 'build_opener') as opener:
            assert hwp2md.main([str(src), '--vlm', 'groq']) == 2
            assert opener.call_count == 0
    finally:
        for p in planted[1:]:
            p.unlink(missing_ok=True)
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err['error'] == 'GROQ_API_KEY_MISSING'
    assert err['message'] == hwp2md.MESSAGES['GROQ_API_KEY_MISSING']
    assert not (tmp_path / '문서.md').exists()


def test_provider_isolation(make_hwpx, tmp_path, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener)
        assert hwp2md.main([str(src), '--vlm', 'xai']) == 0
    req = sent_request(opener)
    assert req.full_url == vlm.PROVIDERS['xai'][1]
    assert req.get_header('Authorization') == 'Bearer xai-test-key'
    assert 'groq-test-key' not in json.dumps(dict(req.header_items())) + req.data.decode()
    assert json.loads(req.data)['model'] == 'grok-4.3'
    out = capsys.readouterr()
    assert json.loads(out.out)['paths'] == ['direct', 'vlm:xai']
    md = (tmp_path / '문서.md').read_text(encoding='utf-8')
    assert '> **VLM (xai):** 도장' in md
    for text in (out.out, out.err, md):
        assert 'xai-test-key' not in text and 'groq-test-key' not in text


def test_cli_vlm_notes(make_hwpx, tmp_path, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')
    with patch.dict(vlm.os.environ, {'GROQ_API_KEY': 'groq-test-key'}, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener)
        assert hwp2md.main([str(src), '--vlm', 'groq']) == 0
    assert opener.return_value.open.call_count == 1
    md = (tmp_path / '문서.md').read_text(encoding='utf-8')
    assert '> **VLM (groq):** 도장' in md
    out = capsys.readouterr()
    assert json.loads(out.err.strip()) == {'notice': 'sending 1 image(s) to groq'}
    summary = json.loads(out.out)
    assert summary['paths'] == ['direct', 'vlm:groq']
    assert 'groq-test-key' not in out.out + out.err + md


def test_no_network_without_flag(make_hwpx, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError('network used without --vlm')
    monkeypatch.setattr(urllib.request, 'build_opener', boom)
    monkeypatch.setattr(urllib.request, 'urlopen', boom)
    src = make_hwpx(tmp_path / '문서.hwpx')
    assert hwp2md.main([str(src)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)['paths'] == ['direct']
    assert 'notice' not in out.err


def test_note_text_includes_tables(tmp_path):
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    content = json.dumps({'text': '제목', 'tables': [{'rows': [['구분', '금액'], ['합계', '100']]}],
                          'uncertain_regions': []}, ensure_ascii=False)
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener, content)
        assert vlm.describe('groq', img) == '제목\n구분 | 금액\n합계 | 100'


def test_annotate_skips_unsupported_and_oversize(tmp_path, capsys):
    big = b'\x89PNG\r\n\x1a\n' + b'\x00' * (3 * 1024 * 1024)
    doc = image_doc(Asset('a0', PNG, '.png', 'image/png'), Asset('a1', b'GIF89a', '.gif', 'image/gif'),
                    Asset('a2', big, '.png', 'image/png'), Asset('a3', b'\x00\x01', '.bin', 'application/octet-stream'),
                    Asset('a4', JPEG, '.jpg', 'image/jpeg'))
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        opener.return_value.open.return_value.__enter__.side_effect = \
            lambda: reply('{"text": "글자"}')
        notes = vlm.annotate(doc, tmp_path, 'groq')
    assert notes == {'a0': [('vlm:groq', '글자')], 'a4': [('vlm:groq', '글자')]}
    assert opener.return_value.open.call_count == 2
    assert {'VLM_SKIPPED:a1', 'VLM_SKIPPED:a2', 'VLM_SKIPPED:a3'} <= set(doc.warnings)
    assert json.loads(capsys.readouterr().err.strip()) == {'notice': 'sending 2 image(s) to groq'}
    assert list(tmp_path.iterdir()) == []  # temp image copies removed


def test_empty_text_warns(tmp_path):
    doc = image_doc(Asset('a0', PNG, '.png', 'image/png'))
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener, '{"text": "  "}')
        assert vlm.annotate(doc, tmp_path, 'groq') == {}
    assert 'VLM_EMPTY:a0' in doc.warnings


def test_hook_without_eligible_images_sends_nothing(tmp_path, capsys):
    doc = image_doc(Asset('a1', b'GIF89a', '.gif', 'image/gif'))
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        assert vlm.hook(doc, input=tmp_path / 'x.hwpx', vlm='groq') is None
    assert opener.call_count == 0 and 'notice' not in capsys.readouterr().err
    assert vlm.hook(doc, input=tmp_path / 'x.hwpx') is None  # flag off: no-op


@pytest.mark.parametrize('provider,status', [('groq', 401), ('xai', 429), ('groq', 500)])
def test_http_error_code(provider, status, make_hwpx, tmp_path, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        opener.return_value.open.side_effect = urllib.error.HTTPError(
            vlm.PROVIDERS[provider][1], status, 'nope', {}, io.BytesIO(b'SECRET BODY groq-test-key'))
        assert hwp2md.main([str(src), '--vlm', provider]) == 2
    assert opener.return_value.open.call_count == 1
    err_text = capsys.readouterr().err
    err = json.loads(err_text.strip().splitlines()[-1])
    assert err['error'] == f'{provider.upper()}_HTTP_{status}'
    assert err['message'] != hwp2md.GENERIC_MESSAGE
    assert 'SECRET' not in err_text and 'test-key' not in err_text and 'Traceback' not in err_text
    assert sorted(p.name for p in tmp_path.iterdir()) == ['문서.hwpx']


def test_network_error_code(tmp_path):
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    for exc in (urllib.error.URLError('down'), TimeoutError('slow')):
        with patch.dict(vlm.os.environ, KEYS, clear=True), \
             patch.object(vlm.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = exc
            with pytest.raises(Failure) as e:
                vlm.describe('groq', img)
        assert str(e.value) == 'VLM_NETWORK_ERROR'


@pytest.mark.parametrize('raw', [
    'not json at all',
    '{"choices": []}',
    '{"choices": [{"message": {"content": "not json"}}]}',
    '{"choices": [{"message": {"content": "[1, 2]"}}]}',
    '{"choices": [{"message": {"content": "{\\"text\\": 5}"}}]}',
    '{"choices": [{"message": {}}]}',
    '[]',
])
def test_bad_response(raw, make_hwpx, tmp_path, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener, raw=raw)
        assert hwp2md.main([str(src), '--vlm', 'groq']) == 2
    err_text = capsys.readouterr().err
    assert json.loads(err_text.strip().splitlines()[-1])['error'] == 'VLM_BAD_RESPONSE'
    assert 'not json' not in err_text and 'Traceback' not in err_text


def test_oversize_response_is_bad(tmp_path):
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        mock_opener(opener, raw=b'{' + b' ' * vlm.MAX_RESPONSE + b'}')
        with pytest.raises(Failure) as e:
            vlm.describe('groq', img)
    assert str(e.value) == 'VLM_BAD_RESPONSE'


def test_build_request_rejects_non_image(tmp_path):
    img = tmp_path / 'a.gif'
    img.write_bytes(b'GIF89a')
    with pytest.raises(Failure) as e:
        vlm.build_request('groq', img)
    assert str(e.value) == 'VLM_UNSUPPORTED_IMAGE'


def test_incomplete_read_is_network_error(tmp_path):
    import http.client
    img = tmp_path / 'a.png'
    img.write_bytes(PNG)
    with patch.dict(vlm.os.environ, KEYS, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.side_effect = http.client.IncompleteRead(b'')
        with pytest.raises(Failure) as e:
            vlm.describe('groq', img)
    assert str(e.value) == 'VLM_NETWORK_ERROR'


def test_vlm_key_checked_before_ocr(make_hwpx, tmp_path, monkeypatch, capsys):
    src = make_hwpx(tmp_path / '문서.hwpx')

    def ocr_hook(*a, **k):
        raise AssertionError('OCR ran before the VLM key check')
    monkeypatch.setattr(hwp2md, 'annotate_hooks', [ocr_hook, vlm.hook])
    with patch.dict(vlm.os.environ, {}, clear=True):
        assert hwp2md.main([str(src), '--ocr', '--vlm', 'groq']) == 2
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert err['error'] == 'GROQ_API_KEY_MISSING'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['문서.hwpx']


@pytest.mark.parametrize('provider', ['groq', 'xai'])
@pytest.mark.parametrize('value, present', [('k-SECRET-123', True), (None, False), ('   ', False),
                                            ('k-SECRET\r\nX', False)])
def test_check_vlm(provider, value, present, capsys):
    env_name = vlm.PROVIDERS[provider][2]
    env = {} if value is None else {env_name: value}
    with patch.dict(vlm.os.environ, env, clear=True), \
         patch.object(vlm.urllib.request, 'build_opener') as opener:
        assert hwp2md.main(['--check-vlm', provider]) == 0
        assert opener.call_count == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {'status': 'ok', 'provider': provider, 'key_env': env_name,
                               'key_present': present}
    assert 'SECRET' not in out + err


def test_check_vlm_usage(tmp_path, capsys):
    assert hwp2md.main([]) == 2  # INPUT still required without --check-vlm
    assert hwp2md.main(['--check-vlm', 'other']) == 2
    assert hwp2md.main([str(tmp_path / 'a.hwpx'), '--check-vlm', 'groq']) == 2  # query only
    errors = [json.loads(line)['error'] for line in capsys.readouterr().err.splitlines()]
    assert errors == ['USAGE_ERROR'] * 3
