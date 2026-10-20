"""Bold/underline and outline-heading lookup from HWP 5 (pyhwp XML) and HWPX header.xml."""
import re

HEADING = re.compile(r'^(개요|Outline|Heading)\s*(\d)$')


def _local(e):
    return e.tag.rsplit('}', 1)[-1]


def _level(names):
    for name in names:
        m = HEADING.match((name or '').strip())
        if m:
            return min(max(int(m.group(2)), 1), 6)
    return None


class StyleTable:
    """Maps character-shape ids to (bold, underline) and paragraph-style ids to heading levels."""

    def __init__(self, chars=None, headings=None):
        self.chars = chars or {}        # char id -> (bold, underline)
        self.headings = headings or {}  # style id -> level or None

    def run_style(self, char_id):
        return self.chars.get(char_id, (False, False))

    def heading_level(self, style_id):
        return self.headings.get(style_id)

    @classmethod
    def from_hwp5(cls, root):
        """CharShape / Style elements are indexed by document order."""
        chars, headings = {}, {}
        shapes = [e for e in root.iter() if _local(e) == 'CharShape']
        for i, e in enumerate(shapes):
            # 'line_through' / 'upperline' are strikethrough/overline, not underline.
            chars[str(i)] = (e.get('bold') == '1', e.get('underline') == 'underline')
        styles = [e for e in root.iter() if _local(e) == 'Style']
        for i, e in enumerate(styles):
            headings[str(i)] = _level([e.get('local-name'), e.get('name')])
        return cls(chars, headings)

    @classmethod
    def from_hwpx(cls, header_root):
        """hh:charPr@id and hh:style@id from Contents/header.xml; None gives an empty table."""
        chars, headings = {}, {}
        for e in header_root.iter() if header_root is not None else ():
            tag = _local(e)
            if tag == 'charPr' and e.get('id') is not None:
                kids = {_local(c): c for c in e}
                line = kids.get('underline')
                underline = line is not None and line.get('type') == 'BOTTOM'  # TOP/CENTER are not underline
                chars[e.get('id')] = ('bold' in kids, underline)
            elif tag == 'style' and e.get('id') is not None:
                headings[e.get('id')] = _level([e.get('name'), e.get('engName')])
        return cls(chars, headings)
