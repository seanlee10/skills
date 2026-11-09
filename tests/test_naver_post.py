import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit
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
    soup = naver.BeautifulSoup(html, "html.parser")
    assert soup.find_all("p")[-1].a["href"] == naver.utm_link(URL, "supplements-best5")


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
    assert p.cover == "https://aeobot.ai/blog/_astro/cover.jpg"
    assert "cover.jpg" not in naver.build_body(p, "도입부")


def test_article_without_a_prose_body_is_rejected():
    with pytest.raises(ValueError):
        naver.extract_post('<html><head><title>x</title></head><body></body></html>', URL)


def test_without_cover_or_paragraph_retains_body_and_source_query():
    url = "https://example.org/?p=42&utm_source=old"
    post = naver.extract_post("<article><h1>Story</h1><ul><li>본문</li></ul></article>", url)
    body = naver.BeautifulSoup(naver.build_body(post, "새 도입부"), "html.parser")
    assert (post.title, post.cover) == ("Story", None)
    assert body.p.string == "새 도입부"
    assert body.li.string == "본문"
    query = parse_qs(urlsplit(body.a["href"]).query)
    assert query["p"] == ["42"] and query["utm_source"] == ["naver"]


@pytest.fixture
def blog():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/notes/go":
                self.send_response(302)
                self.send_header("Location", "/notes/story.html")
                self.end_headers()
                return
            page = """<title>Story</title><div class="copy"><p>Old intro</p>
            <p>둘째 문단 <a href="details">Details</a></p><img src="pic.png"></div>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/notes"
        finally:
            server.shutdown()
            thread.join()


def test_configured_cli_prepares_selects_and_records(blog, tmp_path, monkeypatch, capsys):
    profile = tmp_path / "profile.toml"
    profile.write_text(f'source_url = "{blog}/"\nblog_id = "writer"\nhistory_path = "records/posts.db"\n'
                       'article_selector = ".copy"\n')
    url = f"{blog}/go"
    other = f"{blog}/second"
    monkeypatch.setattr(naver, "DATA_DIR", tmp_path / "drafts")
    clipboard_calls = []
    monkeypatch.setattr(naver.subprocess, "run", lambda args, check: clipboard_calls.append(args))

    def cli(*args):
        monkeypatch.setattr(sys, "argv", ["naver", "--config", str(profile), *args])
        naver.main()
        return capsys.readouterr().out.strip()

    result = json.loads(cli("clip", url, "--intro", "New intro"))
    assert result["write_url"] == "https://blog.naver.com/writer/postwrite"
    assert result["cover"] is None
    assert result["images"] == 1 and result["title"] == "Story"
    assert result["link"].startswith(f"{blog}/story.html?utm_source=naver")
    assert clipboard_calls[0][0] == "osascript" and clipboard_calls[0][-1] == result["clipboard"]
    body = Path(result["clipboard"]).read_text()
    assert "New intro" in body and "Old intro" not in body and "둘째 문단" in body
    assert f'{blog}/pic.png' in body and f'{blog}/details' in body
    assert not (tmp_path / "records/posts.db").exists()
    assert cli("next", url, other) == url
    posted = "https://m.blog.naver.com/writer/42"
    cli("log", url, posted)
    cli("log", url, posted)
    assert (tmp_path / "records/posts.db").is_file()
    assert cli("next", url, other) == other
    profile.write_text(profile.read_text().replace('"writer"', '"other"'))
    assert cli("next", url) == url
    with pytest.raises(SystemExit):
        cli("log", url, posted)


@pytest.mark.parametrize("url", ["https://example.org.evil.com/blog/post", "https://example.org/blogs/post",
                                 "https://example.org/blog/../private", "https://example.org/blog/%2e%2e/private"])
def test_scope_rejects_unconfigured_articles(url, tmp_path):
    config = naver.Config("https://example.org/blog/", "writer", tmp_path / "history.db", None)
    with pytest.raises(ValueError):
        config.article_url(url)
