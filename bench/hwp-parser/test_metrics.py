import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import char_accuracy, count_tables, normalize, strip_markdown, word_f1  # noqa: E402


def test_strip_markdown():
    md = '## 제목\n\n<table><tr><td><strong>가</strong></td></tr></table>\n![](<a/b.png>)\n> **OCR:** 나'
    assert normalize(strip_markdown(md)) == '제목가나'


def test_strip_markdown_vlm_prefix_links_entities_and_gfm_pipes():
    md = ('<!-- note -->\n> **VLM (groq):** 다\n[라](http://x)\n'
          '| 마 | 바 |\n| --- | --- |\n| A&amp;B | **사** |')
    assert normalize(strip_markdown(md)) == '다라마바A&B사'


def test_char_accuracy_identity_and_typo():
    assert char_accuracy('시상식', '시상식') == 1.0
    assert char_accuracy('시상식', '시장식') == pytest.approx(2 / 3, abs=1e-4)


def test_char_accuracy_floors_at_zero_and_ignores_whitespace():
    assert char_accuracy('가', '나다라마') == 0.0
    assert char_accuracy('가 나', '가나') == 1.0


def test_word_f1_order_insensitive():
    assert word_f1('가 나 다', '다 나 가') == 1.0


def test_word_f1_multiset():
    # ref has 가 twice; hyp once -> precision 1, recall 2/3
    assert word_f1('가 가 나', '가 나') == pytest.approx(0.8)
    assert word_f1('가', '') == 0.0


def test_count_tables():
    md = ('<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>\n\n'
          '<table><tr><td>y</td></tr></table>')
    assert count_tables(md) == 2


def test_count_tables_gfm():
    md = '| a | b |\n| --- | --- |\n| 1 | 2 |\n\ntext\n\n|x|\n|:-:|\n|y|\n'
    assert count_tables(md) == 2
