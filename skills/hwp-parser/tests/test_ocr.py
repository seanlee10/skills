import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import NS, PNG, SAMPLES, SKILL

SCRIPT = SKILL / 'scripts' / 'hwp2md.py'
OCR_PNG = Path(__file__).resolve().parent / 'data' / 'ocr-ko.png'
EMPTY_SEC = f'<hs:sec {NS}><hp:p id="1"><hp:run><hp:t></hp:t></hp:run></hp:p></hs:sec>'
IMAGE_ONLY_SEC = (f'<hs:sec {NS}><hp:p id="1"><hp:run><hp:pic><hc:img binaryItemIDRef="img1"/>'
                  '</hp:pic></hp:run></hp:p></hs:sec>')


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=600)


def error(proc):
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert err['status'] == 'failed' and err['message']
    return err['error']


def test_tessdata_present():
    from hwp_parser import ocr
    assert ocr.TESSDATA == SKILL / 'tessdata'
    for lang in ('kor', 'eng'):
        assert (ocr.TESSDATA / f'{lang}.traineddata').stat().st_size > 1024 * 1024


def test_lit_path_found():
    from hwp_parser import ocr
    assert ocr.lit_path().is_file()


def test_lit_path_missing(monkeypatch, tmp_path):
    from hwp_parser import ocr
    from hwp_parser.extract import Failure
    monkeypatch.setattr(ocr.sys, 'executable', str(tmp_path / 'python'))
    monkeypatch.setattr(ocr.shutil, 'which', lambda name: None)
    with pytest.raises(Failure, match='LITEPARSE_NOT_AVAILABLE'):
        ocr.lit_path()


def test_ocr_image_reads_korean():
    from hwp_parser import ocr
    text = ocr.ocr_image(OCR_PNG)
    assert sum(token in text for token in ('한글', 'OCR', '시험')) >= 2


def test_annotate_skips_non_raster(monkeypatch, tmp_path):
    from hwp_parser import ocr
    from hwp_parser.model import Asset, Document
    calls = []

    def fake(path, *a, **k):
        calls.append(Path(path).suffix)
        return '인식된 글자' if Path(path).suffix == '.png' else ''
    monkeypatch.setattr(ocr, 'ocr_image', fake)
    doc = Document('hwpx', [], {
        'a0': Asset('a0', PNG, '.png', 'image/png'),
        'a1': Asset('a1', b'\x00\x01', '.bin', 'application/octet-stream'),
    }, [])
    notes = ocr.annotate(doc, tmp_path)
    assert calls == ['.png']
    assert notes == {'a0': [('ocr', '인식된 글자')]}


def test_annotate_empty_result_warns(monkeypatch, tmp_path):
    from hwp_parser import ocr
    from hwp_parser.model import Asset, Document
    monkeypatch.setattr(ocr, 'ocr_image', lambda *a, **k: '  \n ')
    doc = Document('hwpx', [], {'a0': Asset('a0', PNG, '.png', 'image/png')}, [])
    assert ocr.annotate(doc, tmp_path) == {}
    assert 'OCR_EMPTY:a0' in doc.warnings


def test_cli_ocr_flag(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx', {'BinData/image1.png': OCR_PNG.read_bytes()})
    proc = run(src, '--ocr')
    assert proc.returncode == 0, proc.stderr
    md = (tmp_path / '문서.md').read_text(encoding='utf-8')
    assert '> **OCR:**' in md
    assert json.loads(proc.stdout)['paths'] == ['direct', 'ocr']


def test_cli_ocr_rescues_image_only_document(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '스캔.hwpx', {'Contents/section2.xml': IMAGE_ONLY_SEC,
                                            'Contents/section10.xml': EMPTY_SEC,
                                            'BinData/image1.png': OCR_PNG.read_bytes()})
    assert error(run(src)) == 'NO_EXTRACTABLE_TEXT'
    proc = run(src, '--ocr')
    assert proc.returncode == 0, proc.stderr
    assert 'OCR' in (tmp_path / '스캔.md').read_text(encoding='utf-8')


def test_cli_ocr_without_any_text_still_fails(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '빈.hwpx', {'Contents/section2.xml': IMAGE_ONLY_SEC,
                                          'Contents/section10.xml': EMPTY_SEC})
    assert error(run(src, '--ocr')) == 'NO_EXTRACTABLE_TEXT'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['빈.hwpx']


def test_pdf_pages_appended_only_when_missing(monkeypatch, make_hwpx, tmp_path):
    import hwp2md
    from hwp_parser import ocr
    src = make_hwpx(tmp_path / '문서.hwpx')
    pdf = tmp_path / '문서.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%%EOF\n')
    monkeypatch.setattr(ocr, 'ocr_pdf', lambda *a, **k: ['합성 문서 첫 구역', '완전히 새로운 페이지'])
    summary = hwp2md.convert(src, None, False, False, pdf, None)
    assert summary['paths'] == ['direct', 'ocr']
    md = (tmp_path / '문서.md').read_text(encoding='utf-8')
    head, sep, tail = md.partition('## OCR (rendered pages)')
    assert sep and '### Page 2' in tail and '완전히 새로운 페이지' in tail
    assert '### Page 1' not in md
    assert md.count('합성 문서') == 1


def test_pdf_shared_fraction():
    from hwp_parser import ocr
    assert ocr.shared_fraction('가나다라', '가나 다 라마') == 1.0
    assert ocr.shared_fraction('가나다라', '가나다') == 0.5
    assert ocr.shared_fraction('다라가나', '가나다라') == 0.0  # same characters, different order
    assert ocr.shared_fraction('12', '가') == 1.0  # too short to judge
    assert ocr.shared_fraction('', '가') == 1.0


@pytest.mark.parametrize('name', ['youth-rfp', 'prospectus', 'pharma-disclosure'])
def test_pdf_shared_fraction_is_selective_on_real_text(name):
    from hwp_parser import ocr
    from hwp_parser.extract import extract
    from hwp_parser.model import Paragraph
    doc = extract(SAMPLES / f'{name}.hwp')
    direct = ocr.trigrams(ocr._direct_text(doc))
    assert ocr.shared_fraction('오늘 저녁 메뉴는 김치찌개와 계란말이로 정했습니다', direct) < 0.5
    assert ocr.shared_fraction('The quick brown fox jumps over the lazy dog', direct) < 0.5
    paragraph = max((''.join(r.text for r in b.runs) for b in doc.blocks if isinstance(b, Paragraph)), key=len)
    assert len(paragraph) > 40
    assert ocr.shared_fraction(paragraph, direct) >= 0.5


def test_pdf_nothing_missing_adds_no_path(monkeypatch, make_hwpx, tmp_path):
    import hwp2md
    from hwp_parser import ocr
    src = make_hwpx(tmp_path / '문서.hwpx')
    pdf = tmp_path / '문서.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%%EOF\n')
    monkeypatch.setattr(ocr, 'ocr_pdf', lambda *a, **k: ['합성 문서 첫 구역 표 앞'])
    summary = hwp2md.convert(src, None, False, False, pdf, None)
    assert summary['paths'] == ['direct']
    assert 'OCR (rendered pages)' not in (tmp_path / '문서.md').read_text(encoding='utf-8')


def test_ocr_only_text_replaces_no_text_warning(monkeypatch, make_hwpx, tmp_path):
    import hwp2md
    from hwp_parser import ocr
    src = make_hwpx(tmp_path / '스캔.hwpx', {'Contents/section2.xml': IMAGE_ONLY_SEC,
                                            'Contents/section10.xml': EMPTY_SEC})
    monkeypatch.setattr(ocr, 'ocr_image', lambda *a, **k: '스캔된 글자')
    summary = hwp2md.convert(src, None, False, True, None, None)
    assert summary['paths'] == ['direct', 'ocr']
    assert 'OCR_ONLY_TEXT' in summary['warnings']
    assert 'NO_EXTRACTABLE_TEXT' not in summary['warnings']


def test_annotate_ocr_failure_warns(monkeypatch, tmp_path):
    from hwp_parser import ocr
    from hwp_parser.extract import Failure
    from hwp_parser.model import Asset, Document

    def boom(*a, **k):
        raise Failure('LITEPARSE_OCR_FAILED')
    monkeypatch.setattr(ocr, 'ocr_image', boom)
    doc = Document('hwpx', [], {'a0': Asset('a0', PNG, '.png', 'image/png')}, [])
    assert ocr.annotate(doc, tmp_path) == {}
    assert 'OCR_FAILED:a0' in doc.warnings
    assert list(tmp_path.iterdir()) == []


def test_lit_argv_is_local_only(monkeypatch):
    from hwp_parser import ocr
    from hwp_parser.extract import Failure
    seen = []

    def fake_run(cmd, timeout, cwd=None, preexec_fn=None):
        seen.append((cmd, timeout))
        return 1
    monkeypatch.setattr(ocr, 'run_group', fake_run)
    with pytest.raises(Failure, match='LITEPARSE_OCR_FAILED'):
        ocr.ocr_image(OCR_PNG)
    with pytest.raises(Failure, match='LITEPARSE_OCR_FAILED'):
        ocr.ocr_pdf(SAMPLES / 'youth-rfp.pdf')
    assert len(seen) == 2
    for cmd, timeout in seen:
        assert timeout == 180
        assert not any('server' in arg for arg in cmd)
        assert cmd[cmd.index('--tessdata-path') + 1] == str(ocr.TESSDATA)
        assert cmd[cmd.index('--ocr-language') + 1] == 'kor+eng'


def test_run_group_kills_on_timeout(tmp_path):
    import time
    from hwp_parser.convert import run_group
    marker = tmp_path / 'late'
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_group(['/bin/sh', '-c', f'sleep 1; touch "{marker}"'], timeout=0.2)
    assert time.monotonic() - start < 1
    time.sleep(1.3)
    assert not marker.exists()  # the whole group was killed, child shell included


def test_pdf_auto_success_path(monkeypatch, tmp_path):
    import hwp2md
    from hwp_parser import ocr
    calls = []

    def fake_hwp_to_pdf(src, workdir, soffice=None):
        calls.append(('convert', Path(src).name))
        pdf = Path(workdir) / 'converted.pdf'
        pdf.write_bytes(b'%PDF-1.4\n')
        return pdf

    def fake_ocr_pdf(path, *a, **k):
        calls.append(('ocr_pdf', Path(path).name))
        return ['완전히 새로운 페이지 내용입니다']
    monkeypatch.setattr(ocr, 'hwp_to_pdf', fake_hwp_to_pdf)
    monkeypatch.setattr(ocr, 'ocr_pdf', fake_ocr_pdf)
    summary = hwp2md.convert(SAMPLES / 'youth-rfp.hwp', tmp_path, False, False, 'auto', None)
    assert calls == [('convert', 'youth-rfp.hwp'), ('ocr_pdf', 'converted.pdf')]
    assert 'EXPERIMENTAL_PDF_CONVERSION' in summary['warnings']
    assert summary['paths'] == ['direct', 'ocr']
    assert '### Page 1' in (tmp_path / 'youth-rfp.md').read_text(encoding='utf-8')


FAKE_SOFFICE = '''#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--outdir" ]; then out="$2"; shift; fi
  shift
done
[ -n "$FAIL" ] && exit 3
printf '%%PDF-1.4\n' > "$out/converted.pdf"
'''


@pytest.mark.parametrize('name', ['youth-rfp', 'prospectus', 'pharma-disclosure'])
def test_hwp_to_pdf_real_odt_step(monkeypatch, tmp_path, name):
    import zipfile
    from hwp_parser.convert import hwp_to_pdf
    soffice = tmp_path / 'soffice'
    soffice.write_text(FAKE_SOFFICE)
    soffice.chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    pdf = hwp_to_pdf(SAMPLES / f'{name}.hwp', work, soffice=str(soffice))
    assert pdf == work / 'converted.pdf' and pdf.read_bytes().startswith(b'%PDF-')
    with zipfile.ZipFile(work / 'converted.odt') as z:
        assert z.read('mimetype') == b'application/vnd.oasis.opendocument.text'
        assert len(z.read('content.xml')) > 10000
    assert not (work / 'lo-profile').exists()


def test_hwp_to_pdf_soffice_failure(monkeypatch, tmp_path):
    from hwp_parser.convert import hwp_to_pdf
    from hwp_parser.extract import Failure
    soffice = tmp_path / 'soffice'
    soffice.write_text(FAKE_SOFFICE)
    soffice.chmod(0o755)
    monkeypatch.setenv('FAIL', '1')
    with pytest.raises(Failure, match='PDF_CONVERSION_FAILED'):
        hwp_to_pdf(SAMPLES / 'youth-rfp.hwp', tmp_path, soffice=str(soffice))


def test_pdf_missing_file(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx')
    assert error(run(src, '--pdf', tmp_path / 'none.pdf')) == 'INVALID_PDF_INPUT'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['문서.hwpx']


def test_pdf_auto_rejects_hwpx(make_hwpx, tmp_path):
    src = make_hwpx(tmp_path / '문서.hwpx')
    assert error(run(src, '--pdf', 'auto')) == 'HWPX_PDF_CONVERSION_UNSUPPORTED'


@pytest.mark.skipif(bool(shutil.which('soffice') or shutil.which('libreoffice')
                         or Path('/Applications/LibreOffice.app').exists()),
                    reason='LibreOffice is installed')
def test_pdf_auto_without_libreoffice(tmp_path):
    proc = run(SAMPLES / 'youth-rfp.hwp', '--pdf', 'auto', '--out-dir', tmp_path)
    assert error(proc) == 'LOCAL_LIBREOFFICE_NOT_AVAILABLE'
    assert list(tmp_path.iterdir()) == []


def test_hwp_to_pdf_rejects_hwpx(make_hwpx, tmp_path):
    from hwp_parser.convert import hwp_to_pdf
    from hwp_parser.extract import Failure
    src = make_hwpx(tmp_path / '문서.hwpx')
    with pytest.raises(Failure, match='HWPX_PDF_CONVERSION_UNSUPPORTED'):
        hwp_to_pdf(src, tmp_path, soffice='/nonexistent/soffice')


def test_pdf_real_sample(tmp_path):
    # Text-layer PDF of an HWP sample: nearly every page is already in the direct text.
    proc = run(SAMPLES / 'youth-rfp.hwp', '--pdf', SAMPLES / 'youth-rfp.pdf', '--out-dir', tmp_path)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary['paths'] == ['direct', 'ocr']
    md = (tmp_path / 'youth-rfp.md').read_text(encoding='utf-8')
    assert md.count('### Page ') <= 3


def test_pdf_dot_slash_auto_is_a_path(make_hwpx, tmp_path, monkeypatch):
    import hwp2md
    src = make_hwpx(tmp_path / '문서.hwpx')
    seen = []

    def capture(doc, pdf=None, **_):
        seen.append(pdf)
    monkeypatch.setattr(hwp2md, 'annotate_hooks', [capture])
    monkeypatch.chdir(tmp_path)
    assert hwp2md.main([str(src), '--pdf', './auto', '--out-dir', 'a']) == 0
    assert hwp2md.main([str(src), '--pdf', 'auto', '--out-dir', 'b']) == 0
    assert seen[0] == (tmp_path / 'auto').resolve() and isinstance(seen[0], Path)
    assert seen[1] == 'auto'
