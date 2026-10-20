from hwp_parser.markdown import asset_filename, render
from hwp_parser.model import Asset, Cell, Document, Image, Paragraph, Run, Table

PNG_ASSET = Asset(id='a0', data=b'\x89PNG', ext='.png', media_type='image/png')


def doc(*blocks, assets=None):
    return Document(format='hwpx', blocks=list(blocks), assets=assets or {}, warnings=[])


def para(text, **kw):
    return Paragraph([Run(text)], **kw)


def cell(row, col, *blocks, rowspan=1, colspan=1, header=False):
    return Cell(row=row, col=col, rowspan=rowspan, colspan=colspan, blocks=list(blocks), header=header)


def test_paragraphs_and_heading():
    out = render(doc(para('제목', heading=1), para('본문')), 'x_assets')
    assert out == '## 제목\n\n본문\n'


def test_bold_underline_merge():
    p = Paragraph([Run('가', bold=True), Run('나', bold=True), Run('다', underline=True)])
    assert render(doc(p), 'x_assets') == '**가나**<u>다</u>\n'


def test_hard_line_break_inside_paragraph():
    assert render(doc(para('첫 줄\n둘째 줄')), 'x_assets') == '첫 줄  \n둘째 줄\n'


def test_merged_cell_table():
    t = Table([cell(0, 0, para('A'), colspan=2), cell(1, 0, para('B')), cell(1, 1, para('C'))])
    out = render(doc(t), 'x_assets')
    assert '<td colspan="2">' in out
    assert 'rowspan="1"' not in out and 'colspan="1"' not in out
    assert out == '<table><tr><td colspan="2">A</td></tr><tr><td>B</td><td>C</td></tr></table>\n'


def test_nested_table_inside_cell():
    inner = Table([cell(0, 0, para('안'))])
    outer = Table([cell(0, 0, para('밖'), inner)])
    out = render(doc(outer), 'x_assets')
    assert '<td>밖<br /><table><tr><td>안</td></tr></table></td>' in out


def test_header_cells():
    t = Table([cell(0, 0, para('머리'), header=True), cell(1, 0, para('값'))])
    out = render(doc(t), 'x_assets')
    assert '<th>머리</th>' in out and '<td>값</td>' in out


def test_cell_paragraph_styles_and_breaks():
    c = cell(0, 0, Paragraph([Run('굵게', bold=True), Run('밑줄', underline=True)]), para('둘째'))
    out = render(doc(Table([c])), 'x_assets')
    assert '<td><strong>굵게</strong><u>밑줄</u><br />둘째</td>' in out


def test_image_link_with_korean_space_name():
    out = render(doc(Image('a0'), assets={'a0': PNG_ASSET}), '보고서 v2_assets')
    assert out == '![](<보고서 v2_assets/a0.png>)\n'


def test_image_in_cell_uses_img_tag():
    t = Table([cell(0, 0, Image('a0'))])
    out = render(doc(t, assets={'a0': PNG_ASSET}), '보고서_assets')
    assert '<img src="보고서_assets/a0.png" />' in out
    table = out[out.index('<table>'):out.rindex('</table>')]
    assert '![' not in table


def test_escaping():
    out = render(doc(para('# 아님 <b> & *별*')), 'x_assets')
    assert out == '\\# 아님 &lt;b&gt; &amp; \\*별\\*\n'
    out = render(doc(Table([cell(0, 0, para('a|b<c'))])), 'x_assets')
    assert 'a|b&lt;c' in out


def test_no_double_blank_lines():
    blocks = [para('a'), *(Paragraph([]) for _ in range(3)), para(''), para('  '), para('b')]
    assert render(doc(*blocks), 'x_assets') == 'a\n\nb\n'
    assert '\n\n\n' not in render(doc(para('a\n\n\nb')), 'x_assets')


def test_notes_rendered():
    out = render(doc(Image('a0'), assets={'a0': PNG_ASSET}), 'x_assets',
                 notes={'a0': [('ocr', '인감'), ('vlm:groq', '도장 이미지')]})
    assert '> **OCR:** 인감' in out
    assert '> **VLM (groq):** 도장 이미지' in out
    assert '\n\n\n' not in out and out.endswith('\n') and not out.endswith('\n\n')


def test_asset_filename():
    assert asset_filename(PNG_ASSET) == 'a0.png'


def test_tilde_escaped():
    assert render(doc(para('1~3월 및 5~6월')), 'x_assets') == '1\\~3월 및 5\\~6월\n'


def test_bold_next_to_punctuation_uses_strong():
    p = Paragraph([Run('삼성'), Run('(주)', bold=True), Run('은')])
    assert render(doc(p), 'x_assets') == '삼성<strong>(주)</strong>은\n'
    # A plain letter-bounded bold run keeps the Markdown markers.
    p = Paragraph([Run('가 '), Run('굵게', bold=True), Run(' 나')])
    assert render(doc(p), 'x_assets') == '가 **굵게** 나\n'
    # Escaped content starting with an entity/backslash counts as punctuation.
    p = Paragraph([Run('가'), Run('<표>', bold=True), Run('나')])
    assert render(doc(p), 'x_assets') == '가<strong>&lt;표&gt;</strong>나\n'


def test_bold_merges_across_underline():
    p = Paragraph([Run('가 '), Run('a', bold=True), Run('b', bold=True, underline=True), Run(' 나')])
    out = render(doc(p), 'x_assets')
    assert '****' not in out
    assert out == '가 **a<u>b</u>** 나\n'


def test_image_notes_inside_cell():
    t = Table([cell(0, 0, Image('a0'))])
    out = render(doc(t, assets={'a0': PNG_ASSET}), 'x_assets',
                 notes={'a0': [('ocr', '인감 <직인>'), ('vlm:xai', '도장')]})
    assert ('<img src="x_assets/a0.png" /><br /><blockquote><strong>OCR:</strong> 인감 &lt;직인&gt;</blockquote>'
            '<blockquote><strong>VLM (xai):</strong> 도장</blockquote>') in out
    assert '> **' not in out


def test_row_covered_by_rowspan_keeps_tr():
    t = Table([cell(0, 0, para('A'), rowspan=2), cell(0, 1, para('B'), rowspan=2), cell(2, 0, para('C'))])
    out = render(doc(t), 'x_assets')
    assert out == ('<table><tr><td rowspan="2">A</td><td rowspan="2">B</td></tr><tr></tr>'
                   '<tr><td>C</td></tr></table>\n')


def test_asset_dir_special_characters():
    assets = {'a0': PNG_ASSET}
    out = render(doc(Image('a0'), assets=assets), '보고서 #1?50%_assets')
    assert out == '![](<보고서 %231%3F50%25_assets/a0.png>)\n'
    out = render(doc(Table([cell(0, 0, Image('a0'))]), assets=assets), 'a b"c&d#_assets')
    assert '<img src="a b&quot;c&amp;d%23_assets/a0.png" />' in out


def test_setext_line_and_heading_closing_hash():
    assert render(doc(para('위\n---\n===')), 'x_assets') == '위  \n\\---  \n\\===\n'
    assert render(doc(para('번호 #', heading=1)), 'x_assets') == '## 번호 \\#\n'
