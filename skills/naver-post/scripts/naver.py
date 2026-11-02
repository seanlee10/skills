# /// script
# requires-python = "==3.11.*"
# dependencies = ["beautifulsoup4==4.15.0", "requests==2.34.2"]
# ///
"""Build an aeobot blog article as a Naver blog body and put it on the macOS clipboard.

Naver has no posting API (the blog open API was shut down), so the user pastes and presses 발행.

    uv run naver.py clip <blog-url> --intro "네이버용 도입부"
"""

import argparse
import html as htmllib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SHOTS = Path.home() / ".config" / "naver-post"
CHANNEL = "naver-blog"  # clone-loop ledger channel
WRITE_URL = "https://blog.naver.com/aeobot/postwrite"
USER_AGENT = "Mozilla/5.0 (naver-post)"
KEEP = {"p", "h2", "h3", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
        "blockquote", "a", "img", "strong", "em", "b", "i", "br", "code", "figure", "figcaption"}
DROP = {"script", "style", "nav", "aside", "svg", "button", "form", "noscript"}
ATTRS = {"a": {"href"}, "img": {"src", "alt"}}
STYLES = {  # same look as a copy from the rendered blog page; the editor keeps inline styles only
    "h2": "font-size:24px;font-weight:700;color:#15213c",
    "h3": "font-size:19px;font-weight:700;color:#15213c",
    "p": "font-size:16px;color:#455067;line-height:1.9",
    "li": "font-size:16px;color:#455067;line-height:1.9",
}


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    url: str
    html: str


def utm_link(url: str, slug: str) -> str:
    q = urlencode({"utm_source": "naver", "utm_medium": CHANNEL, "utm_campaign": slug, "utm_content": f"h-{slug}-1"})
    return f"{url}?{q}"


def cover_url(page_html: str, url: str) -> str | None:
    meta = BeautifulSoup(page_html, "html.parser").find("meta", property="og:image")
    return urljoin(url, meta["content"]) if meta and meta.get("content") else None


def extract_post(page_html: str, url: str) -> Post:
    soup = BeautifulSoup(page_html, "html.parser")
    og = soup.find("meta", property="og:title")
    title = (og["content"] if og else soup.title.get_text()).split(" | ")[0].strip()
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    prose = soup.select_one("article.prose")
    if prose is None:
        raise ValueError("블로그 본문(article.prose)을 찾지 못했습니다")
    for tag in prose.find_all(DROP):
        tag.decompose()
    for tag in prose.find_all(True):
        if tag.name not in KEEP:
            tag.unwrap()
            continue
        keep = ATTRS.get(tag.name, set())
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep}
        if tag.name == "img" and tag.get("src"):
            tag["src"] = urljoin(url, tag["src"])
        if tag.name == "a" and tag.get("href"):
            tag["href"] = urljoin(url, tag["href"])
    body = prose.decode_contents().strip()
    if cover := cover_url(page_html, url):
        body = f'<p><img src="{cover}" alt="{htmllib.escape(title)}"></p>\n{body}'
    link = utm_link(url, slug)
    footer = f'<p>원문과 측정 방법: <a href="{link}">{link}</a></p>'
    return Post(slug, title, url, f"{body}\n{footer}")


def fetch_post(url: str) -> Post:
    if not re.match(r"^https://aeobot\.ai/blog/[\w-]+/?$", url):
        raise SystemExit(f"aeobot 블로그 글 URL이 아닙니다: {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return extract_post(r.text, url if url.endswith("/") else url + "/")


def fetch_image(src: str) -> bytes:
    r = requests.get(src, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.content


def copy_html(html: str, path: Path) -> None:
    """Put HTML on the macOS clipboard as rich text, so Cmd+V in the editor keeps images and links."""
    path.write_text(html, encoding="utf-8")
    script = f'set the clipboard to (read (POSIX file "{path}") as «class HTML»)'
    subprocess.run(["osascript", "-e", script], check=True)


def cover_src(post: Post) -> str:
    return BeautifulSoup(post.html, "html.parser").find("img")["src"]


def build_body(post: Post, intro: str) -> str:
    """The article with its opening rewritten, so the Naver post is not a verbatim copy of the other channels."""
    if not intro.strip():
        raise ValueError("네이버용 도입부가 비어 있습니다")
    soup = BeautifulSoup(post.html, "html.parser")
    soup.find("img").parent.decompose()  # a hotlinked cover leaves the post with no 대표 이미지; the user uploads it
    first = next(p for p in soup.find_all("p") if p.get_text(strip=True))
    first.string = intro.strip()
    for tag in soup.find_all(STYLES):
        tag["style"] = STYLES[tag.name]
    return str(soup)


def cmd_clip(a: argparse.Namespace) -> None:
    post = fetch_post(a.url)
    html = build_body(post, a.intro)  # images stay URLs: the Naver editor drops pasted data URIs
    SHOTS.mkdir(parents=True, exist_ok=True)
    clip = SHOTS / f"{post.slug}-clip.html"
    copy_html(html, clip)
    cover = SHOTS / f"{post.slug}-cover{Path(urlparse(cover_src(post)).path).suffix}"
    cover.write_bytes(fetch_image(cover_src(post)))
    print(json.dumps({"title": post.title, "images": html.count("<img"), "tables": html.count("<table"),
                      "cover": str(cover), "link": utm_link(post.url, post.slug), "write_url": WRITE_URL, "clipboard": str(clip)},
                     ensure_ascii=False, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(prog="naver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cp = sub.add_parser("clip", help="네이버용 본문을 클립보드에 넣음")
    cp.add_argument("url", help="aeobot 블로그 글 URL (https://aeobot.ai/blog/<slug>/)")
    cp.add_argument("--intro", required=True, help="네이버용으로 새로 쓴 도입부")
    cp.set_defaults(fn=cmd_clip)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
