import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/naver-post/scripts/naver.py'
spec = importlib.util.spec_from_file_location('naver', SCRIPT)
naver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(naver)

URL = "https://aeobot.ai/blog/supplements-best5/"
PAGE = """<html><head><meta property="og:title" content="영양제 글 | AEOBOT 인사이트">
<meta property="og:image" content="/blog/_astro/cover.jpg"></head><body>
<article class="prose"><p>블로그 도입부입니다.</p><h2>제목</h2><p>둘째 문단 <b>강조</b></p>
<img src="/blog/_astro/chart.svg"></article></body></html>"""


def post():
    return naver.extract_post(PAGE, URL)


def test_link_carries_naver_utm():
    assert naver.utm_link(URL, "supplements-best5") == (
        f"{URL}?utm_source=naver&utm_medium=naver-blog&utm_campaign=supplements-best5"
        "&utm_content=h-supplements-best5-1")


def test_body_ends_with_the_naver_utm_link():
    html = naver.build_body(post(), "네이버용 도입부")
    assert html.count("utm_source=naver") == 2  # href and visible text
    assert "원문과 측정 방법:" in html


def test_intro_replaces_the_first_paragraph_of_text():
    html = naver.build_body(post(), "네이버용 도입부 <A&B>")
    assert "블로그 도입부입니다." not in html
    assert "네이버용 도입부 &lt;A&amp;B&gt;" in html
    assert "둘째 문단" in html


def test_intro_is_required():
    with pytest.raises(ValueError):
        naver.build_body(post(), "  ")


def test_body_carries_the_styles_the_naver_editor_keeps():
    html = naver.build_body(post(), "도입부")
    assert '<h2 style="font-size:24px;font-weight:700;color:#15213c">' in html
    assert '<p style="font-size:16px;color:#455067;line-height:1.9">' in html


def test_images_stay_urls_because_the_editor_drops_data_uris():
    html = naver.build_body(post(), "도입부")
    assert "data:" not in html
    assert 'src="https://aeobot.ai/blog/_astro/chart.svg"' in html


def test_cover_leaves_the_body_as_a_file_to_upload():
    p = post()
    assert naver.cover_src(p) == "https://aeobot.ai/blog/_astro/cover.jpg"
    assert "cover.jpg" not in naver.build_body(p, "도입부")


def test_article_without_a_prose_body_is_rejected():
    with pytest.raises(ValueError):
        naver.extract_post('<html><head><title>x</title></head><body></body></html>', URL)


def test_only_aeobot_blog_urls_are_fetched():
    with pytest.raises(SystemExit):
        naver.fetch_post('https://example.com/blog/post/')
