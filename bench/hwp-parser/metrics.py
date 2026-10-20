"""Text metrics for the hwp-parser benchmark.

Every system's Markdown goes through `strip_markdown` before scoring, so Markdown/HTML
syntax is not counted as content. The reference is plain text and is scored as is.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter

from rapidfuzz.distance import Levenshtein

_COMMENT = re.compile(r'<!--.*?-->', re.S)
_IMAGE = re.compile(r'!\[[^\]]*\]\((?:<[^>]*>|[^)\s]*)(?:\s+"[^"]*")?\)')
_LINK = re.compile(r'(?<!\\)\[([^\]]*)\]\((?:<[^>]*>|[^)\s]*)(?:\s+"[^"]*")?\)')
# Block-level tags separate words; inline tags (strong, u, em, span, ...) do not.
_BLOCK_TAG = re.compile(r'(?<!\\)</?(?:table|thead|tbody|tfoot|tr|td|th|caption|br|p|div|li|ul|ol|'
                        r'blockquote|h[1-6]|img|hr)\b[^>]*>', re.I)
_TAG = re.compile(r'(?<!\\)</?[A-Za-z][^>]*>')
_NOTE_PREFIX = re.compile(r'^>\s*\*\*(?:OCR|VLM \([^)]*\)):\*\*[ \t]*', re.M)
_QUOTE = re.compile(r'^[ \t]*>[ \t]?', re.M)
_HEADING = re.compile(r'^[ \t]*#{1,6}[ \t]+', re.M)
_BULLET = re.compile(r'^[ \t]*[*+][ \t]+', re.M)
_GFM_RULE = re.compile(r'^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$', re.M)
_PIPE = re.compile(r'(?<!\\)\|')
_ESCAPE = re.compile(r'\\([\\`*_{}\[\]()#+\-.!|<>])')


def strip_markdown(md: str) -> str:
    """Remove Markdown/HTML syntax, keeping the text content."""
    s = _COMMENT.sub(' ', md)
    s = _IMAGE.sub(' ', s)
    s = _LINK.sub(r'\1', s)
    s = _BLOCK_TAG.sub('\n', s)
    s = _TAG.sub('', s)
    s = _NOTE_PREFIX.sub('', s)
    s = _QUOTE.sub('', s)
    s = _HEADING.sub('', s)
    s = _BULLET.sub('', s)
    s = s.replace('**', '')
    s = _GFM_RULE.sub('', s)
    s = _PIPE.sub(' ', s)
    s = _ESCAPE.sub(r'\1', s)
    return html.unescape(s)


def normalize(s: str) -> str:
    """NFC, then remove all whitespace."""
    return ''.join(c for c in unicodedata.normalize('NFC', s) if not c.isspace())


def char_accuracy(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 1.0 if not h else 0.0
    return max(0.0, 1 - Levenshtein.distance(r, h) / len(r))


def word_f1(ref: str, hyp: str) -> float:
    """Bag-of-words F1 over whitespace tokens (NFC), counting repeats."""
    r = Counter(unicodedata.normalize('NFC', ref).split())
    h = Counter(unicodedata.normalize('NFC', hyp).split())
    common = sum((r & h).values())
    if not common:
        return 1.0 if not r and not h else 0.0
    precision = common / sum(h.values())
    recall = common / sum(r.values())
    return 2 * precision * recall / (precision + recall)


_TABLE_OPEN = re.compile(r'<table\b', re.I)
_TABLE_CLOSE = re.compile(r'</table\s*>', re.I)
_GFM_SEP = re.compile(r'^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$')


def count_tables(md: str) -> int:
    """Top-level HTML tables plus GFM tables (header row followed by a separator row)."""
    count = 0
    depth = 0
    for m in re.finditer(r'<table\b|</table\s*>', md, re.I):
        if _TABLE_OPEN.match(m.group()):
            if depth == 0:
                count += 1
            depth += 1
        elif depth:
            depth -= 1
    lines = _COMMENT.sub('', md).split('\n')
    for prev, line in zip(lines, lines[1:]):
        if '|' in prev and '|' in line and '-' in line and _GFM_SEP.match(line):
            count += 1
    return count
