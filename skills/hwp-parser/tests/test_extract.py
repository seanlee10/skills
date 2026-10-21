import shutil
import struct

import pytest

from conftest import NS, PNG, SAMPLES
from hwp_parser.extract import Failure, extract, walk
from hwp_parser.model import Image, Paragraph, Table


def text(p):
    return ''.join(r.text for r in p.runs)


def test_spine_order_and_text(make_hwpx, tmp_path):
    doc = extract(make_hwpx(tmp_path / 's.hwpx'))
    assert doc.format == 'hwpx'
    texts = [text(b) for b in doc.blocks if isinstance(b, Paragraph)]
    assert texts[0].startswith('합성 문서\t첫 구역')
    assert texts.index('합성 문서\t첫 구역') < texts.index('표 앞')  # section10 before section2


def test_table_with_merged_and_nested(make_hwpx, tmp_path):
    doc = extract(make_hwpx(tmp_path / 's.hwpx'))
    blocks = doc.blocks
    i = next(n for n, b in enumerate(blocks) if isinstance(b, Paragraph) and text(b) == '표 앞')
    table = blocks[i + 1]
    assert isinstance(table, Table)
    first = table.cells[0]
    assert first.colspan == 2 and first.rowspan == 1 and (first.row, first.col) == (0, 0)
    assert any(isinstance(b, Paragraph) and text(b) == '병합 셀' for b in first.blocks)
    nested = [b for b in first.blocks if isinstance(b, Table)]
    assert len(nested) == 1
    assert [text(b) for b in walk(nested[0].cells[0].blocks) if isinstance(b, Paragraph)] == ['중첩']
    assert isinstance(blocks[i + 2], Paragraph) and text(blocks[i + 2]) == '표 뒤'
    rest = blocks[i + 3:]
    images = [n for n, b in enumerate(rest) if isinstance(b, Image)]
    assert images and rest[images[0]] == Image(asset_id='a0')
    assert doc.assets['a0'].data == PNG
    assert doc.assets['a0'].ext == '.png'
    assert doc.assets['a0'].media_type == 'image/png'


def test_no_duplicate_text(make_hwpx, tmp_path):
    doc = extract(make_hwpx(tmp_path / 's.hwpx'))
    all_text = ''.join(r.text for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs)
    assert all_text.count('중첩') == 1



def test_hwpx_special_spaces_become_spaces(make_hwpx, tmp_path):
    # Fixed-width (고정폭 빈칸) and non-breaking (묶음 빈칸) spaces are empty elements in HWPX.
    sec2 = (f'<hs:sec {NS}><hp:p id="1"><hp:run><hp:t>제2026<hp:fwSpace/>-<hp:fwSpace/>432호'
            '<hp:nbSpace/>공고</hp:t></hp:run></hp:p></hs:sec>')
    doc = extract(make_hwpx(tmp_path / 'sp.hwpx', {'Contents/section2.xml': sec2}))
    assert '제2026 - 432호 공고' in [text(b) for b in doc.blocks if isinstance(b, Paragraph)]


def test_table_caption_kept(make_hwpx, tmp_path):
    sec2 = (f'<hs:sec {NS}><hp:p id="1"><hp:run><hp:tbl rowCnt="1" colCnt="1">'
            '<hp:caption side="BOTTOM"><hp:subList><hp:p id="2"><hp:run><hp:t>CAPTION</hp:t></hp:run></hp:p>'
            '</hp:subList></hp:caption><hp:tr><hp:tc><hp:subList><hp:p id="3"><hp:run><hp:t>CELL</hp:t>'
            '</hp:run></hp:p></hp:subList><hp:cellAddr rowAddr="0" colAddr="0"/>'
            '<hp:cellSpan rowSpan="1" colSpan="1"/></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>')
    doc = extract(make_hwpx(tmp_path / 'c.hwpx', {'Contents/section2.xml': sec2}))
    i = next(n for n, b in enumerate(doc.blocks) if isinstance(b, Table))
    table, after = doc.blocks[i], doc.blocks[i + 1]
    assert len(table.cells) == 1
    assert [text(b) for b in table.cells[0].blocks] == ['CELL']
    assert isinstance(after, Paragraph) and text(after) == 'CAPTION'
    all_text = ''.join(r.text for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs)
    assert all_text.count('CAPTION') == 1

BAD_CASES = {
    'slip': {'../escape.xml': '<bad/>'},
    'xxe': {'Contents/section2.xml': '<!DOCTYPE doc [<!ENTITY x SYSTEM "file:///etc/passwd">]><doc>&x;</doc>'},
    'encrypted': {'META-INF/manifest.xml': '<manifest><encryption-data/></manifest>'},
    'mimetype': {'mimetype': 'application/zip'},
    'spine': {'Contents/content.hpf': '<package><spine><itemref idref="missing"/></spine></package>'},
    'brokenxml': {'Contents/section2.xml': '<unclosed>'},
    'missingsection': {'Contents/section99.xml': '<sec/>'},
}


@pytest.mark.parametrize('label', BAD_CASES)
def test_rejects_bad_packages(make_hwpx, tmp_path, label):
    path = make_hwpx(tmp_path / (label + '.hwpx'), BAD_CASES[label])
    with pytest.raises(Failure):
        extract(path)


def test_rejects_unknown_signature(tmp_path):
    path = tmp_path / 'plain.hwp'
    path.write_text('not a document')
    with pytest.raises(Failure) as e:
        extract(path)
    assert str(e.value) == 'UNSUPPORTED_SIGNATURE_HWP3_OR_OTHER'


@pytest.mark.parametrize('name,tables,assets', [
    ('prospectus', 32, 3), ('pharma-disclosure', 31, 1), ('youth-rfp', 17, 0)])
def test_hwp5_samples(name, tables, assets):
    doc = extract(SAMPLES / (name + '.hwp'))
    assert doc.format == 'hwp'
    assert sum(isinstance(b, Table) for b in walk(doc.blocks)) == tables
    assert len(doc.assets) == assets
    images = [b for b in walk(doc.blocks) if isinstance(b, Image)]
    assert all(b.asset_id in doc.assets for b in images)


@pytest.mark.parametrize('flag', [2, 4, 16, 256, 1024])
def test_hwp5_protected_flags(tmp_path, flag):
    import olefile
    protected = tmp_path / ('protected-%d.hwp' % flag)
    shutil.copyfile(SAMPLES / 'prospectus.hwp', protected)
    with olefile.OleFileIO(str(protected), write_mode=True) as ole:
        header = bytearray(ole.openstream('FileHeader').read())
        struct.pack_into('<I', header, 36, struct.unpack_from('<I', header, 36)[0] | flag)
        ole.write_stream('FileHeader', bytes(header))
    with pytest.raises(Failure) as e:
        extract(protected)
    assert any(x in str(e.value) for x in ('PROTECTED', 'DISTRIBUTION', 'DRM'))
