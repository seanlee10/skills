# /// script
# requires-python = "==3.11.*"
# dependencies = ["beautifulsoup4==4.15.0", "requests==2.34.2"]
# ///
"""Prepare a rich-text draft for the Naver Blog editor on macOS."""

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
import tomllib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

DATA_DIR = Path.home() / ".config" / "naver-post"
USER_AGENT = "Mozilla/5.0 (naver-post)"
KEEP = {"p", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody", "tr",
        "th", "td", "blockquote", "a", "img", "strong", "em", "b", "i", "br", "pre", "code",
        "figure", "figcaption"}
DROP = {"script", "style", "nav", "aside", "svg", "button", "form", "noscript", "template", "iframe", "footer"}
ATTRS = {"a": {"href"}, "img": {"src", "alt"}}
STYLES = {
    "h2": "font-size:24px;font-weight:700;color:#15213c",
    "h3": "font-size:19px;font-weight:700;color:#15213c",
    "p": "font-size:16px;color:#455067;line-height:1.9",
    "li": "font-size:16px;color:#455067;line-height:1.9",
}


def web_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and parts.username is None


@dataclass(frozen=True)
class Config:
    source_url: str
    blog_id: str
    history_path: Path
    article_selector: str | None

    def article_url(self, value: str) -> str:
        base = urlsplit(self.source_url)
        parts = urlsplit(value)
        path = unquote(parts.path)
        root = unquote(base.path).rstrip("/")
        if (not web_url(value) or parts.scheme != base.scheme or parts.netloc.lower() != base.netloc.lower()
                or not (path == root or path.startswith(root + "/"))
                or ".." in path.split("/") or "\\" in path):
            raise ValueError(f"설정한 원본 블로그 범위를 벗어난 주소입니다: {value}")
        return parts._replace(fragment="", netloc=parts.netloc.lower()).geturl()


def read_config(path: Path) -> Config:
    if not path.is_file():
        raise ValueError(f"{path}에 source_url과 blog_id를 설정하세요. SKILL.md의 설정 예시를 참고하세요.")
    with path.open("rb") as f:
        raw = tomllib.load(f)
    source = raw.get("source_url")
    if not isinstance(source, str) or not web_url(source) or urlsplit(source).query or urlsplit(source).fragment:
        raise ValueError("source_url에는 쿼리와 프래그먼트 없는 HTTP(S) 블로그 주소가 필요합니다")
    blog_id = raw.get("blog_id")
    if not isinstance(blog_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", blog_id):
        raise ValueError("blog_id에는 네이버 블로그 주소의 계정 ID를 입력하세요")
    history = raw.get("history_path", "history.sqlite3")
    selector = raw.get("article_selector")
    if not isinstance(history, str) or not history.strip():
        raise ValueError("history_path에는 발행 기록 파일 경로가 필요합니다")
    if selector is not None and (not isinstance(selector, str) or not selector.strip()):
        raise ValueError("article_selector에는 본문 CSS 선택자가 필요합니다")
    return Config(source, blog_id, path.parent / Path(history).expanduser(), selector)


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    url: str
    html: str
    cover: str | None


def utm_link(url: str, slug: str) -> str:
    parts = urlsplit(url)
    utm = {"utm_source": "naver", "utm_medium": "naver-blog", "utm_campaign": slug, "utm_content": f"h-{slug}-1"}
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in utm]
    return urlunsplit(parts._replace(query=urlencode(query + list(utm.items()))))


def asset_url(base: str, value: str) -> str | None:
    full = urljoin(base, value.strip())
    return full if value.strip() and web_url(full) else None


def extract_post(page_html: str, url: str, selector: str | None = None) -> Post:
    soup = BeautifulSoup(page_html, "html.parser")
    prose = None
    for candidate in ([selector] if selector else ["article.prose", "[itemprop=articleBody]", ".entry-content", "article", "main"]):
        matches = soup.select(candidate)
        if len(matches) > 1:
            raise ValueError("본문 후보가 여러 개입니다. 글 주소와 article_selector를 확인하세요")
        if matches:
            prose = matches[0]
            break
    if prose is None:
        raise ValueError("본문을 찾지 못했습니다. article_selector에 본문 CSS 선택자를 지정하세요")
    og = soup.find("meta", property="og:title")
    heading = prose.find("h1") or soup.find("h1") or soup.title
    title = (og or {}).get("content") or (heading.get_text(" ", strip=True) if heading else "")
    title = title.split(" | ")[0].strip()
    if not title:
        raise ValueError("글 제목을 찾지 못했습니다")
    cover_meta = soup.find("meta", property="og:image")
    base_tag = soup.find("base", href=True)
    base = (asset_url(url, base_tag["href"]) if base_tag else None) or url
    cover = asset_url(base, cover_meta.get("content", "")) if cover_meta else None
    for tag in prose.find_all(DROP):
        tag.decompose()
    for h1 in prose.find_all("h1"):
        if h1.get_text(" ", strip=True) == title:
            h1.decompose()
        else:
            h1.name = "h2"
    for tag in prose.find_all(True):
        if tag.name not in KEEP:
            tag.unwrap()
            continue
        if tag.name == "img":
            tag["src"] = tag.get("data-src") or tag.get("src", "")
        keep = ATTRS.get(tag.name, set())
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep}
        for attr in ("src", "href"):
            if attr in tag.attrs:
                resolved = asset_url(base, tag[attr])
                if resolved:
                    tag[attr] = resolved
                else:
                    del tag[attr]
        if tag.name == "img" and not tag.has_attr("src"):
            tag.decompose()
    if not prose.get_text(strip=True) and not prose.find("img"):
        raise ValueError("선택한 본문이 비어 있습니다")
    parts = urlsplit(url)
    slug = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]) or "post"
    if parts.query:
        slug += "-" + hashlib.sha256(parts.query.encode()).hexdigest()[:10]
    return Post(slug, title, url, prose.decode_contents().strip(), cover)


def fetch_post(url: str, config: Config) -> Post:
    url = config.article_url(url)
    for _ in range(10):
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=False)
        if response.is_redirect:
            url = config.article_url(urljoin(url, response.headers["Location"]))
            continue
        response.raise_for_status()
        # Let the HTML parser inspect the page's charset when HTTP omits one.
        data = response.text if "charset=" in response.headers.get("Content-Type", "").lower() else response.content
        return extract_post(data, url, config.article_selector)
    raise ValueError("원본 URL의 리디렉션이 너무 많습니다")


def build_body(post: Post, intro: str) -> str:
    if not intro.strip():
        raise ValueError("네이버용 도입부가 비어 있습니다")
    soup = BeautifulSoup(post.html, "html.parser")
    first = next((p for p in soup.find_all("p") if p.get_text(strip=True)), None)
    opening = soup.new_tag("p")
    opening.string = intro.strip()
    if first:
        for img in first.find_all("img"):
            first.insert_before(img.extract())
        first.replace_with(opening)
    else:
        soup.insert(0, opening)
    footer = soup.new_tag("p")
    link = soup.new_tag("a", href=utm_link(post.url, post.slug))
    link.string = "원문 보기"
    footer.append(link)
    soup.append(footer)
    for tag in soup.find_all(STYLES):
        tag["style"] = STYLES[tag.name]
    return str(soup)


def copy_html(body: str, path: Path) -> None:
    path.write_text(body, encoding="utf-8")
    script = 'on run argv\nset the clipboard to (read (POSIX file (item 1 of argv)) as «class HTML»)\nend run'
    subprocess.run(["osascript", "-e", script, str(path)], check=True)


def cmd_clip(args: argparse.Namespace, config: Config) -> None:
    post = fetch_post(args.url, config)
    body = build_body(post, args.intro)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="draft-", dir=DATA_DIR))
    cover = None
    warning = None
    if post.cover:
        try:
            response = requests.get(post.cover, headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
            suffix = extensions.get(response.headers.get("Content-Type", "").partition(";")[0].strip().lower())
            if suffix:
                cover = folder / ("cover" + suffix)
                cover.write_bytes(response.content)
            else:
                warning = "커버 파일 형식을 확인할 수 없습니다"
        except requests.RequestException as exc:
            warning = f"커버를 다운로드하지 못했습니다: {exc}"
    clip = folder / "clip.html"
    copy_html(body, clip)
    print(json.dumps({"title": post.title, "images": body.count("<img"), "tables": body.count("<table"),
                      "cover": str(cover) if cover else None, "warning": warning, "link": utm_link(post.url, post.slug),
                      "write_url": f"https://blog.naver.com/{config.blog_id}/postwrite", "clipboard": str(clip)},
                     ensure_ascii=False, indent=2))


def post_number(url: str, blog_id: str) -> str:
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.netloc.lower() in {"blog.naver.com", "m.blog.naver.com"}:
        match = re.fullmatch(rf"/{re.escape(blog_id)}/([0-9]+)/?", parts.path)
        if match:
            return match[1]
        if parts.path == "/PostView.naver":
            query = dict(parse_qsl(parts.query))
            number = query.get("logNo", "")
            if query.get("blogId") == blog_id and re.fullmatch(r"[0-9]+", number):
                return number
    raise ValueError(f"{blog_id} 계정의 네이버 게시글 URL을 입력하세요")


def history_command(args: argparse.Namespace, config: Config) -> None:
    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(config.history_path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS published (
            blog_id TEXT NOT NULL, source_url TEXT NOT NULL, posted_url TEXT NOT NULL,
            PRIMARY KEY (blog_id, source_url))""")
        if args.cmd == "log":
            source = config.article_url(args.url)
            number = post_number(args.posted_url, config.blog_id)
            posted = f"https://blog.naver.com/{config.blog_id}/{number}"
            db.execute("""INSERT INTO published VALUES (?, ?, ?)
                       ON CONFLICT(blog_id, source_url) DO UPDATE SET posted_url=excluded.posted_url""",
                       (config.blog_id, source, posted))
            print(posted)
        else:
            candidates = [config.article_url(url) for url in args.urls]
            for source in candidates:
                if not db.execute("SELECT 1 FROM published WHERE blog_id=? AND source_url=?",
                                  (config.blog_id, source)).fetchone():
                    print(source)
                    return
            print("모든 후보가 이미 발행되었습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="naver")
    parser.add_argument("--config", type=Path, default=DATA_DIR / "config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    clip = sub.add_parser("clip", help="네이버용 본문을 클립보드에 넣음")
    clip.add_argument("url", help="원본 블로그 글 URL")
    clip.add_argument("--intro", required=True, help="네이버용으로 새로 쓴 도입부")
    log = sub.add_parser("log", help="수동 발행이 끝난 글을 기록")
    log.add_argument("url", help="준비할 때 입력한 원본 URL")
    log.add_argument("posted_url", help="네이버 게시글 URL")
    sub.add_parser("next", help="후보 중 발행 기록이 없는 첫 URL").add_argument("urls", nargs="+")
    args = parser.parse_args()
    try:
        config = read_config(args.config.expanduser())
        if args.cmd == "clip":
            cmd_clip(args, config)
        else:
            history_command(args, config)
    except (ValueError, SelectorSyntaxError, OSError, requests.RequestException, sqlite3.Error, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"naver: {exc}\n")


if __name__ == "__main__":
    main()
