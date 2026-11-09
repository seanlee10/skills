---
name: naver-post
description: Prepare a public HTML blog article for manual publishing to the user's 네이버 블로그 (Naver Blog). Use for requests to move a post to Naver, prepare the next unpublished article, or record its published URL.
---

# Naver Blog drafts

## First use

Ask for the source blog's base URL and the destination Naver blog ID (the segment after `blog.naver.com/`) if they are unknown. Save the user's values in `~/.config/naver-post/config.toml`. Create the parent directory as needed. For another profile, pass `--config /path/to/profile.toml` before the subcommand.

```toml
source_url = "https://example.org/articles/"
blog_id = "my_blog"
history_path = "history.sqlite3"
# article_selector = ".post-content"
```

`source_url` scopes articles to that origin and path. Use the site's final address after redirects. Set it to the site root for blogs with query-based article URLs. The history is a local SQLite file, created on first use of `next` or `log`. The default is `history.sqlite3` beside the config. Relative paths resolve from the config directory. Point it to a new SQLite file when migrating from a CSV ledger. To carry over earlier posts, run `log` once per known source/published URL pair.

## Prepare and publish

Run the following commands with `uv run <skill-folder>/scripts/naver.py`. The rich-text clipboard step requires macOS.

1. Use the requested article URL. If the user asks for the next post, read their candidate list or find article links on the configured blog's public index. Order them by the user's preference or keep the index order. Run `next <article-url> [<article-url> ...]` to find the first unrecorded candidate for this Naver account. If the index has no article links, ask for candidate URLs.
2. Read the article and write a short opening for Naver readers using facts from the source. Run `clip <article-url> --intro "<new opening>"`. The script reads the page's HTML and looks for a semantic article or main body. If it selects the wrong region, inspect the source HTML and set `article_selector` to a CSS selector matching the article body once. Pages whose text loads only after running JavaScript need a server-rendered article URL.
3. Give the user the returned title and editor URL. If a cover file is available, have them upload it as the first image and place the cursor below it. Report any cover warning. The user pastes the formatted body with Cmd+V, reviews it, and presses 발행. Inline images link to the source site's assets.
4. When the user supplies the published URL, check the public Naver page for the expected source link and images (including the uploaded cover, if applicable). If you cannot verify them, report what you could check. Once publication is confirmed, run `log <original-input-url> <published-naver-url>` using the same source URL as for `next`. Preparing a draft alone leaves the publication history untouched.
