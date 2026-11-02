---
name: naver-post
description: Use when the user wants an aeobot blog post (https://aeobot.ai/blog/<slug>/) cross-posted to the 네이버 블로그 (blog.naver.com/aeobot), asks 네이버에 올려줘, or asks for the next article to move to Naver.
---

# Naver blog post

Puts one aeobot blog article on the clipboard as a Naver blog body. Naver has no posting API and the user presses 발행 themselves. Claude in Chrome cannot open blog.naver.com (blocked as a safety restriction), so do not try to drive the editor.

## Pacing

One article a day. Bulk verbatim posting reads as spam, so a request for "all posts" still means today's one article. Pick the next from `data/ledger.csv` in clone-loop: skip slugs already on `naver-blog`, then take the highest i-boss views.

## Steps

Requires macOS (the clipboard step uses `osascript`) and [`uv`](https://docs.astral.sh/uv/). In Claude Code the skill folder is `${CLAUDE_SKILL_DIR}`.

1. **Write the intro.** Read the article, then write 2 to 3 new sentences for Naver: only numbers that are in the article, no free-check offer, no guarantee of exposure. It replaces the article's first paragraph.
2. **Build.** `uv run <this skill's folder>/scripts/naver.py clip <blog-url> --intro "<intro>"`
   Prints JSON with `title`, `images`, `tables`, `cover`, `link`, `write_url`, `clipboard`.
3. **Hand over.** Tell the user to open `write_url`, type the printed `title`, upload the printed `cover` file as the first image (a hotlinked cover leaves the post with no 대표 이미지), click below it, press Cmd+V, and press 발행. Give them the title, cover path and image count.
4. **Verify the posted URL** the user sends. Fetch `https://m.blog.naver.com/aeobot/<post-id>` and check the `images` count, that `og:image` is on pstatic.net and not the default `og_270x270.png`, and that the `utm_source=naver` link is present. Images stay hotlinked to aeobot.ai because the editor drops pasted data URIs, so a rebuilt asset hash on the blog would break them.
5. **Log it** from the clone-loop repo root:
   `uv run python -m loop log --channel naver-blog --kind post --url <posted-url> --hook h-<slug>-1 --campaign <slug>`

The loop cannot read Naver stats, so the scorecard shows this channel as 측정 안 됨.
