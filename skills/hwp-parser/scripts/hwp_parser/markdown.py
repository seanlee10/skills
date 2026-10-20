"""Render a Document as Markdown, with tables as inline HTML.

render() is pure: it builds a string and never touches the filesystem.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Callable

from .model import Asset, Cell, Document, Image, Paragraph, Run, Table

Notes = dict[str, list[tuple[str, str]]]

# Characters that can start Markdown syntax anywhere in a line.
_MD_INLINE = re.compile(r'([\\`*_~\[\]])')
# A line of only '-'/'=' (with spaces) is a setext underline or thematic break.
_SETEXT = re.compile(r'[-=][-= \t]*')
# Trailing '#'s after a space are an ATX closing sequence and would be dropped.
_ATX_CLOSE = re.compile(r'(\s)(#+)$')
# Upper bound on rows filled in for a table (guards corrupt row addresses).
_MAX_ROWS = 10000


def asset_filename(asset: Asset) -> str:
    return asset.id + asset.ext


def render(doc: Document, assets_dir: str, notes: Notes | None = None) -> str:
    ctx = _Ctx(doc, assets_dir, notes or {})
    parts: list[str] = []
    for block in doc.blocks:
        if isinstance(block, Paragraph):
            text = _paragraph(block)
        elif isinstance(block, Table):
            text = _table(block, ctx)
        elif isinstance(block, Image):
            text = _image(block, ctx)
        else:
            text = ''
        if text:
            parts.append(text)
    return '\n\n'.join(parts) + '\n'


class _Ctx:
    def __init__(self, doc: Document, assets_dir: str, notes: Notes):
        self.doc, self.assets_dir, self.notes = doc, assets_dir, notes

    def path(self, img: Image) -> str | None:
        asset = self.doc.assets.get(img.asset_id)
        if asset is None:
            return None
        path = f'{self.assets_dir}/{asset_filename(asset)}'
        # Keep spaces and Korean raw, but these three would end or alter the path.
        return path.replace('%', '%25').replace('#', '%23').replace('?', '%3F')


# ---------------------------------------------------------------- shared

def _lines(runs: list[Run]) -> list[list[Run]]:
    """Split runs on '\\n', merge adjacent same-style runs, drop blank lines."""
    lines: list[list[Run]] = [[]]
    for run in runs:
        for i, piece in enumerate(run.text.split('\n')):
            if i:
                lines.append([])
            if not piece:
                continue
            line = lines[-1]
            if line and (line[-1].bold, line[-1].underline) == (run.bold, run.underline):
                line[-1] = Run(line[-1].text + piece, run.bold, run.underline)
            else:
                line.append(Run(piece, run.bold, run.underline))
    out = []
    for line in lines:
        if not ''.join(r.text for r in line).strip():
            continue
        # Trim the line ends so indentation cannot turn into a code block.
        while not line[0].text.strip():
            line.pop(0)
        while not line[-1].text.strip():
            line.pop()
        line[0] = Run(line[0].text.lstrip(), line[0].bold, line[0].underline)
        line[-1] = Run(line[-1].text.rstrip(), line[-1].bold, line[-1].underline)
        out.append(line)
    return out


def _split_ws(text: str) -> tuple[str, str, str]:
    core = text.strip()
    if not core:
        return text, '', ''
    lead = text[:len(text) - len(text.lstrip())]
    return lead, core, text[len(lead) + len(core):]


def _segments(line: list[Run], escape: Callable[[str, bool], str]) -> list[tuple[bool, str]]:
    """Escape runs, wrap underline, and merge adjacent runs by bold state.

    Returns (bold, text) pairs where bold text has no edge whitespace and is
    never adjacent to another bold segment.
    """
    merged: list[list] = []
    for i, run in enumerate(line):
        text = escape(run.text, i == 0)
        if run.underline:
            lead, core, trail = _split_ws(text)
            text = lead + (f'<u>{core}</u>' if core else '') + trail
        if merged and merged[-1][0] == run.bold:
            merged[-1][1] += text
        else:
            merged.append([run.bold, text])
    out: list[tuple[bool, str]] = []
    for bold, text in merged:
        lead, core, trail = _split_ws(text)
        if bold and core:
            out += [(False, lead), (True, core), (False, trail)]
        else:
            out.append((False, text))
    return [(b, t) for b, t in out if t]


def _punct(c: str) -> bool:
    return unicodedata.category(c)[0] in 'PS'


def _flanks(outer: str | None, inner: str) -> bool:
    """CommonMark rule: '**' next to inner punctuation needs space/punct/edge outside."""
    return not _punct(inner) or outer is None or outer.isspace() or _punct(outer)


# ---------------------------------------------------------------- Markdown

def _escape_md(text: str, line_start: bool) -> str:
    text = _MD_INLINE.sub(r'\\\1', text)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if line_start and text.startswith('#'):
        text = '\\' + text
    return text


def _md_line(line: list[Run]) -> str:
    segs = _segments(line, _escape_md)
    out = []
    for i, (bold, text) in enumerate(segs):
        if not bold:
            out.append(text)
            continue
        before = segs[i - 1][1][-1] if i else None
        after = segs[i + 1][1][0] if i + 1 < len(segs) else None
        if _flanks(before, text[0]) and _flanks(after, text[-1]):
            out.append(f'**{text}**')
        else:
            out.append(f'<strong>{text}</strong>')
    result = ''.join(out)
    if _SETEXT.fullmatch(result):
        result = '\\' + result
    return result


def _paragraph(p: Paragraph) -> str:
    lines = [_md_line(line) for line in _lines(p.runs)]
    if not lines:
        return ''
    if p.heading:
        level = min(max(p.heading, 1) + 1, 6)
        return '#' * level + ' ' + _ATX_CLOSE.sub(r'\1\\\2', ' '.join(lines))
    return '  \n'.join(lines)


def _image(img: Image, ctx: _Ctx) -> str:
    path = ctx.path(img)
    if path is None:
        return ''
    dest = re.sub(r'([\\<>&])', r'\\\1', path)
    out = [f'![](<{dest}>)']
    for source, text in ctx.notes.get(img.asset_id, []):
        lines = [_md_line(line) for line in _lines([Run(text)])]
        if lines:
            out.append(f'> **{_note_label(source)}:** ' + '  \n> '.join(lines))
    return '\n\n'.join(out)


def _note_label(source: str) -> str:
    if source == 'ocr':
        return 'OCR'
    if source.startswith('vlm:'):
        return f'VLM ({source[4:]})'
    return source


# ---------------------------------------------------------------- HTML

def _escape_html(text: str, line_start: bool) -> str:
    return html.escape(text, quote=False)


def _html_lines(runs: list[Run]) -> list[str]:
    return [''.join(f'<strong>{t}</strong>' if b else t for b, t in _segments(line, _escape_html))
            for line in _lines(runs)]


def _html_image(img: Image, ctx: _Ctx) -> str:
    path = ctx.path(img)
    if path is None:
        return ''
    out = f'<img src="{html.escape(path)}" />'
    quotes = []
    for source, text in ctx.notes.get(img.asset_id, []):
        lines = _html_lines([Run(text)])
        if lines:
            quotes.append(f'<blockquote><strong>{html.escape(_note_label(source))}:</strong> '
                          + '<br />'.join(lines) + '</blockquote>')
    if quotes:
        out += '<br />' + ''.join(quotes)
    return out


def _cell_content(cell: Cell, ctx: _Ctx) -> str:
    parts = []
    for block in cell.blocks:
        if isinstance(block, Paragraph):
            text = '<br />'.join(_html_lines(block.runs))
        elif isinstance(block, Table):
            text = _table(block, ctx)
        elif isinstance(block, Image):
            text = _html_image(block, ctx)
        else:
            text = ''
        if text:
            parts.append(text)
    return '<br />'.join(parts)


def _rows(table: Table) -> list[list[Cell]]:
    if table.cells and all(c.row is not None and c.row >= 0 for c in table.cells):
        by_row: dict[int, list[Cell]] = {}
        for cell in table.cells:
            by_row.setdefault(cell.row, []).append(cell)
        last = max(by_row)
        if last < _MAX_ROWS:
            # Rows wholly covered by a rowspan from above still need a <tr>.
            return [by_row.get(r, []) for r in range(last + 1)]
        return [by_row[r] for r in sorted(by_row)]
    # Without full addresses, group by first appearance; a cell without a
    # row address stays in the row of the cell before it.
    rows: dict[int | None, list[Cell]] = {}
    current = None
    for cell in table.cells:
        if cell.row is not None or not rows:
            current = cell.row
        rows.setdefault(current, []).append(cell)
    return list(rows.values())


def _table(table: Table, ctx: _Ctx) -> str:
    out = ['<table>']
    for cells in _rows(table):
        out.append('<tr>')
        for cell in cells:
            tag = 'th' if cell.header else 'td'
            attrs = ''
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            out.append(f'<{tag}{attrs}>{_cell_content(cell, ctx)}</{tag}>')
        out.append('</tr>')
    out.append('</table>')
    return ''.join(out)
