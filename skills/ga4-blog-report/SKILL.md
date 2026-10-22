---
name: ga4-blog-report
description: "Report a website blog's Google Analytics 4 (GA4) traffic with the GA4 Data API: pageviews and sessions per post, top traffic sources, and visits referred by AI assistants such as ChatGPT, Perplexity, Gemini, Copilot and Claude. Use when the user asks how their blog posts are doing in Google Analytics / GA4 (구글 애널리틱스), where blog traffic comes from, or how much traffic AI engines send."
---

# ga4-blog-report

Fetches a GA4 property's traffic for pages under a path prefix (default `/blog/`) with the
GA4 Data API (`runReport`), writes the raw rows to a CSV, and prints a JSON summary the
agent turns into a report. Answer in the user's language (often Korean); keep page paths,
source names and GA4 field names exactly as they appear.

## When to use

- Per-post performance of a blog or any site section in GA4: pageviews, sessions, ranking.
- Where the traffic comes from: Google, Naver, LinkedIn, direct, and so on.
- How much traffic AI assistants and answer engines send (ChatGPT, Perplexity, Gemini,
  Copilot, Claude, DeepSeek, Grok and others), in total and per post.
- Not for Universal Analytics (UA) properties, GA4 configuration changes, or real-time data.

## Before the first report

Run `status`. If it says `"configured": false`, stop and walk the user through
[references/setup.md](references/setup.md). They do these steps once, by hand, in the Google
Cloud console and GA4 Admin; no command can do them:

1. Pick or create a Google Cloud project and **enable the Google Analytics Data API** in it.
2. Create a service account in that project and download a JSON key.
3. In GA4 **Admin → Property access management**, add the service account's email as
   **Viewer**.
4. Note the numeric **property ID** from **Admin → Property details** (not the `G-…`
   measurement ID).

Then run `configure --key <downloaded key> --property <ID>`. It copies the key to
`~/.config/ga4-blog-report/` with mode 600 and prints the service account's `client_email`,
which is the address for step 3. Never open, print, quote or copy the key's contents
anywhere else; refer to it only by its path. After `configure` succeeds, suggest the user
delete the downloaded copy.

Do not try `gcloud auth application-default login` or the user's own Google sign-in:
gcloud's default credentials lack the Analytics scope, and Google blocks gcloud's built-in
OAuth app from requesting it.

## Run

```sh
uv run <this skill's folder>/scripts/ga4_report.py status
uv run <this skill's folder>/scripts/ga4_report.py configure --key FILE --property ID
uv run <this skill's folder>/scripts/ga4_report.py report [--start 28daysAgo] [--end today] [--prefix /blog/] [--out FILE.csv] [--force]
```

In Claude Code the skill folder is `${CLAUDE_SKILL_DIR}`:

```sh
uv run "${CLAUDE_SKILL_DIR}/scripts/ga4_report.py" report --start 2026-10-01 --end 2026-10-21 --out ga4-blog-oct.csv
```

Requires [`uv`](https://docs.astral.sh/uv/). Dates are `YYYY-MM-DD`, `today`, `yesterday`
or `NdaysAgo`; the default is the last 28 days. `--out` defaults to `ga4-blog-report.csv`
in the current folder and is never overwritten without `--force`. Every command exits 0
with JSON on stdout. Any failure exits 2 with the last stderr line
`{"status":"failed","error":CODE,"message":...}`: look the code up in
[references/errors.md](references/errors.md) and tell the user the remedy. The script never
retries, and an error is never zero traffic.

## Reading the summary

`report` makes two requests and keeps them apart:

- `pages` comes from page × source rows. A session that viewed several posts counts once
  for each post, so per-post sessions do not add up to `totals.sessions`.
- `totals`, `top_sources` and `ai` come from source rows without the page dimension, so
  each session counts once and every `share` is a fraction of `totals.sessions`.
- `ai.pages` lists, per AI engine, the posts it sent sessions to (page × source counting).

Report from these numbers only; never estimate or recompute from memory. Use the CSV for
follow-up questions (a specific post, a medium, the full source list).

## Reporting

1. **Per-post performance:** posts by pageviews, most first, with sessions. Show up to 20
   and say how many there are in total.
2. **Traffic sources:** the top 10 sources with sessions and share (`google`, `naver`,
   `linkedin.com`, `(direct)` and so on).
3. **AI engine traffic:** sessions and share per engine, the AI total as a share of all
   sessions, and the posts each engine sent visitors to. If `ai.sessions` is 0, say plainly
   that there were no AI-referred sessions in the period.

Always state the property ID, the period and the prefix. Also:

- `includes_today: true` → today's numbers are incomplete in GA4; call them provisional.
- `truncated: true` → more than 250,000 rows; the report covers only part of the data.
  Suggest a shorter period or a narrower prefix.
- `other_row: true` → GA4 grouped rare rows into `(other)`; say so.
- AI detection matches referral hosts in the script's `AI_SOURCES` list. Visits from AI
  apps that send no referrer show up as `(direct)` and cannot be attributed. If an
  unlisted AI host appears among the sources, point it out and suggest adding it to
  `AI_SOURCES`.
