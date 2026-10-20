from defusedxml import ElementTree as ET

from conftest import NS, SAMPLES
from hwp_parser.extract import extract, walk
from hwp_parser.model import Paragraph, Run, Table
from hwp_parser.styles import StyleTable

HEAD = ('<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><hh:refList>'
        '<hh:charProperties itemCnt="3">'
        '<hh:charPr id="0"><hh:underline type="NONE"/></hh:charPr>'
        '<hh:charPr id="1"><hh:bold/><hh:underline type="NONE"/></hh:charPr>'
        '<hh:charPr id="2"><hh:underline type="BOTTOM"/></hh:charPr>'
        '</hh:charProperties><hh:styles itemCnt="2">'
        '<hh:style id="0" type="PARA" name="바탕글" engName="Normal"/>'
        '<hh:style id="2" type="PARA" name="개요 2" engName="Outline 2"/>'
        '</hh:styles></hh:refList></hh:head>')
SEC = (f'<hs:sec {NS}>'
       '<hp:p id="1" styleIDRef="2"><hp:run charPrIDRef="0"><hp:t>제목</hp:t></hp:run></hp:p>'
       '<hp:p id="2" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>보통 </hp:t></hp:run>'
       '<hp:run charPrIDRef="1"><hp:t>굵게</hp:t></hp:run>'
       '<hp:run charPrIDRef="2"><hp:t>밑줄</hp:t></hp:run></hp:p></hs:sec>')


def styled(make_hwpx, tmp_path):
    path = make_hwpx(tmp_path / 's.hwpx', extra={'Contents/header.xml': HEAD, 'Contents/section10.xml': SEC})
    return [b for b in extract(path).blocks if isinstance(b, Paragraph)]


def test_hwpx_bold_underline(make_hwpx, tmp_path):
    runs = {r.text: r for p in styled(make_hwpx, tmp_path) for r in p.runs}
    assert runs['굵게'] == Run(text='굵게', bold=True, underline=False)
    assert runs['밑줄'] == Run(text='밑줄', bold=False, underline=True)
    assert runs['보통 '] == Run(text='보통 ')


def test_hwpx_heading_from_style(make_hwpx, tmp_path):
    paras = {''.join(r.text for r in p.runs): p for p in styled(make_hwpx, tmp_path)}
    assert paras['제목'].heading == 2
    assert paras['보통 굵게밑줄'].heading is None


def test_hwp5_sample_has_bold():
    doc = extract(SAMPLES / 'prospectus.hwp')
    runs = [r for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs]
    assert any(r.bold and '회 사 명' in r.text for r in runs)


def build(make_hwpx, tmp_path, body):
    sec = f'<hs:sec {NS}>{body}</hs:sec>'
    path = make_hwpx(tmp_path / 's.hwpx', extra={'Contents/header.xml': HEAD, 'Contents/section10.xml': sec})
    return extract(path).blocks


def test_hwpx_unknown_or_missing_char_ref(make_hwpx, tmp_path):
    body = ('<hp:p id="1"><hp:run charPrIDRef="99"><hp:t>모름</hp:t></hp:run>'
            '<hp:run><hp:t>없음</hp:t></hp:run></hp:p>')
    runs = {r.text: r for b in walk(build(make_hwpx, tmp_path, body)) if isinstance(b, Paragraph) for r in b.runs}
    assert (runs['모름'].bold, runs['모름'].underline) == (False, False)
    assert (runs['없음'].bold, runs['없음'].underline) == (False, False)


def test_hwpx_cell_header(make_hwpx, tmp_path):
    body = ('<hp:p id="1"><hp:run><hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc header="1"><hp:subList>'
            '<hp:p id="2"><hp:run><hp:t>머리</hp:t></hp:run></hp:p></hp:subList>'
            '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="1"/>'
            '</hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')
    table = next(b for b in build(make_hwpx, tmp_path, body) if isinstance(b, Table))
    assert table.cells[0].header is True


def test_hwp5_style_table_from_fragment():
    root = ET.fromstring(
        '<HwpDoc><DocInfo><IdMappings>'
        '<CharShape bold="0" underline="none"/>'
        '<CharShape bold="1" underline="line_through"/>'
        '<CharShape bold="0" underline="underline"/>'
        '<Style local-name="바탕글" name="Normal"/>'
        '<Style local-name="개요 3" name=""/>'
        '</IdMappings></DocInfo></HwpDoc>')
    styles = StyleTable.from_hwp5(root)
    assert styles.heading_level('1') == 3
    assert styles.heading_level('0') is None
    assert styles.run_style('1') == (True, False)  # strikethrough is not underline
    assert styles.run_style('2') == (False, True)


def test_hwpx_strikethrough_types_not_underline():
    root = ET.fromstring(
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
        '<hh:charPr id="5"><hh:underline type="TOP"/></hh:charPr>'
        '<hh:charPr id="6"><hh:underline type="BOTTOM"/></hh:charPr></hh:head>')
    styles = StyleTable.from_hwpx(root)
    assert styles.run_style('5') == (False, False)
    assert styles.run_style('6') == (False, True)


def test_split_heading_only_first_fragment(make_hwpx, tmp_path):
    body = ('<hp:p id="1" styleIDRef="2"><hp:run charPrIDRef="0"><hp:t>앞 제목</hp:t>'
            '<hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:subList>'
            '<hp:p id="2"><hp:run><hp:t>셀</hp:t></hp:run></hp:p></hp:subList>'
            '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="1"/>'
            '</hp:tc></hp:tr></hp:tbl><hp:t>뒤 조각</hp:t></hp:run></hp:p>')
    paras = {''.join(r.text for r in b.runs): b for b in build(make_hwpx, tmp_path, body)
             if isinstance(b, Paragraph)}
    assert paras['앞 제목'].heading == 2
    assert paras['뒤 조각'].heading is None
