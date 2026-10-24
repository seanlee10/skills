**English** | [한국어](README.ko.md)

# seanlee10/skills

Agent skills by Sean Lee for Korean documents, Korean IP search, Google Photos, email drafts, GA4
blog reports, YouTube downloads, domain searches and Naver-based topic planning, packaged
as one plugin (`seanlee10-skills`) for Claude Code, Codex, Devin and Hermes, and installable
into other agents with `npx skills`.

## Install

<details>
<summary><strong>Claude Code</strong></summary>

Inside Claude Code:

```
/plugin marketplace add seanlee10/skills
/plugin install seanlee10-skills@seanlee10
```

Or from a shell:

```sh
claude plugin marketplace add seanlee10/skills
claude plugin install seanlee10-skills@seanlee10
```

</details>

<details>
<summary><strong>Codex</strong></summary>

```sh
codex plugin marketplace add seanlee10/skills
codex plugin add seanlee10-skills@seanlee10
```

</details>

<details>
<summary><strong>Devin</strong></summary>

```sh
devin plugins install seanlee10/skills
```

</details>

<details>
<summary><strong>Hermes</strong></summary>

```sh
hermes plugins install seanlee10/skills --enable
```

Restart running sessions after installing. Plugin skills are namespaced, so a skill is
expected to load as e.g. `seanlee10-skills:hwp-parser` (unverified until a real Hermes
install). Hermes does not list plugin skills in the system prompt, so name the skill in
your request (e.g. "Use the hwp-parser skill to convert ~/Downloads/보고서.hwp").

</details>

<details>
<summary><strong>Other agents (npx skills)</strong></summary>

```sh
npx skills@latest add seanlee10/skills -a <agent>
```

Replace `<agent>` with your agent's identifier (see `npx skills@latest --help`).

> **Install one way only.** If you install the plugin (above) *and* run `npx skills` for the
> same agent, the skills are registered twice.

</details>

Only the local Claude Code install has been verified so far; the Codex, Devin, Hermes and
`npx skills` installs are verified only after publication. The Python skills run their scripts
with [`uv`](https://docs.astral.sh/uv/) (see [Requirements](#requirements)).

Once installed, just ask your agent; it picks the skill from your request (in Hermes, name
the skill). To run a script yourself, clone the repository and use the commands in the
skill's SKILL.md "Run" section, with `skills/<skill>` as the skill's folder, e.g.
`uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp"`.

## Skills

| Skill | What it does | You need | Network |
| --- | --- | --- | --- |
| [hwp-parser](skills/hwp-parser/SKILL.md) | Converts `.hwp` / `.hwpx` documents to Markdown with HTML tables and images. | Nothing | None by default; Groq or xAI only with `--vlm` |
| [google-photo](skills/google-photo/SKILL.md) | Collects a person's, event's or year's photos and videos from Google Photos and curates a highlight set. | One-time Google Cloud setup | Google |
| [kipris-search](skills/kipris-search/SKILL.md) | Searches KIPRIS for Korean patents, utility models, trademarks and designs. | Nothing; optional KIPRISPlus key | KIPRIS |
| [email-draft](skills/email-draft/SKILL.md) | Drafts customer and partner emails in a consistent business style and copies them to the clipboard as Gmail-ready rich text. | macOS | None |
| [ga4-blog-report](skills/ga4-blog-report/SKILL.md) | Reports a blog's Google Analytics 4 traffic per post and per source, including visits from AI assistants such as ChatGPT and Perplexity. | One-time Google Cloud and GA4 setup | Google |
| [youtube-download](skills/youtube-download/SKILL.md) | Saves a YouTube video or Short as a local H.264/AAC MP4. | FFmpeg and Deno or Node | YouTube |
| [domain-search](skills/domain-search/SKILL.md) | Checks domain availability, alternatives and registration or renewal costs with Route 53, with optional GoDaddy and RDAP/WHOIS lookups. | An authenticated AWS CLI profile | AWS; optional GoDaddy and registration directories |
| [naver-research](skills/naver-research/SKILL.md) | Compares blog ideas with Naver search trends and shopping clicks, then proposes priorities and publication dates. | Naver MCP credentials and Google Sheets access | Naver and Google |

### hwp-parser

Converts Korean HWP 5 (`.hwp`) and HWPX (`.hwpx`) documents (Hangul, 한글, 한컴) into one
Markdown file plus a folder of embedded images: text, bold/underline, outline headings, and
tables as HTML with merged cells. Output goes next to the input and is never overwritten
without `--force`. Not for HWP 3 or older, PDFs or Word files; no decryption.

- `이 한글 파일 마크다운으로 바꿔줘: ~/Downloads/보고서.hwp`
- `What is the budget in "~/Downloads/2024년 사업계획.hwp"?`
- `Convert scan.hwp; the pages are scanned images, so use OCR.`

Options the agent adds when you ask:

- `--ocr`: read text inside embedded images with local OCR (bundled Korean/English data).
- `--pdf FILE` (or experimental `--pdf auto`, HWP 5 only, via LibreOffice): add text that
  direct extraction missed from a PDF rendering of the same document.
- `--vlm groq` / `--vlm xai`: experimental; a vision model describes the embedded images.

**Before first use:** nothing beyond `uv`. `--pdf auto` needs LibreOffice; `--vlm` needs
`GROQ_API_KEY` or `XAI_API_KEY` exported in the shell that starts your agent, never pasted
into the chat ([ocr-vlm.md](skills/hwp-parser/references/ocr-vlm.md)).

**What leaves your machine:** nothing, except with `--vlm`. Conversion, `--ocr` and `--pdf`
are offline (only the first `uv run` downloads the pinned packages from PyPI). With `--vlm`
only the embedded images, not the text, go to the one provider you chose; the agent uses it
only when you ask, and asks first for a non-public document.

Docs: [SKILL.md](skills/hwp-parser/SKILL.md) ·
[output format and limits](skills/hwp-parser/references/format.md) ·
[OCR and VLM](skills/hwp-parser/references/ocr-vlm.md) ·
[error codes](skills/hwp-parser/references/errors.md)

**Accuracy** on three public HWP 5 documents, against the text layer of a Hancom Docs PDF.
Method, caveats, a sample conversion and how to reproduce:
[bench/hwp-parser/README.md](bench/hwp-parser/README.md).

<!-- bench:start -->
### hwp-parser accuracy benchmark

3 public HWP 5 documents; reference = Hancom Docs PDF text layer (extracted with LiteParse 2.14.6, no OCR); LlamaParse output supplied by the repository author, generation settings unknown. Running headers and page numbers present only in the PDF lower both metrics for every system. This is a small, specific comparison, not a general claim.

| Document | System | char_accuracy | word_f1 | tables | seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| prospectus | hwp-parser | 0.877 | 0.861 | 32 | 0.7 |
| prospectus | hwp-parser --ocr | 0.818 | 0.825 | 32 | 2.5 |
| prospectus | LlamaParse (cloud) | 0.787 | 0.826 | 32 | — |
| prospectus | hwp-parser --vlm groq | not measured | | | |
| pharma-disclosure | hwp-parser | 0.793 | 0.837 | 31 | 0.6 |
| pharma-disclosure | hwp-parser --ocr | 0.793 | 0.837 | 31 | 0.7 |
| pharma-disclosure | LlamaParse (cloud) | 0.745 | 0.794 | 28 | — |
| pharma-disclosure | hwp-parser --vlm groq | not measured | | | |
| youth-rfp | hwp-parser | 0.768 | 0.806 | 17 | 0.4 |
| youth-rfp | hwp-parser --ocr | 0.768 | 0.806 | 17 | 0.5 |
| youth-rfp | LlamaParse (cloud) | 0.756 | 0.771 | 9 | — |
| youth-rfp | hwp-parser --vlm groq | not measured | | | |
| **Mean** | hwp-parser | **0.813** | **0.835** | 26.7 | 0.6 |
| **Mean** | hwp-parser --ocr | **0.793** | **0.823** | 26.7 | 1.2 |
| **Mean** | LlamaParse (cloud) | **0.763** | **0.797** | 23.0 | — |
| **Mean** | hwp-parser --vlm groq | not measured | | | |

char_accuracy = max(0, 1 − Levenshtein distance / reference length) after NFC and removing all whitespace; word_f1 = multiset F1 over whitespace tokens. Markdown/HTML syntax is stripped from each output before scoring. Values are fractions in [0, 1], rounded to 3 decimals; `tables` counts top-level HTML and GFM tables in the output; `seconds` is wall time of one hwp2md subprocess (— for LlamaParse, which was not run here). "not measured": `--vlm groq` runs only with `--with-vlm` and `GROQ_API_KEY` set.

Date 2026-10-21 · git 64c3ade · Python 3.11.15 · lit 2.14.6 · pyhwp 0.1b15 · rapidfuzz 3.14.6 · reproduce with `uv run bench/hwp-parser/run.py`.
<!-- bench:end -->

### google-photo

Collects the photos and videos of a person, event or year from your Google Photos into a
local folder (one per subject per year, by default under `~/Pictures/google-photo/`), then
curates a ranked highlight set, by default about 75 photos and 8 clips. You pick in Google's
own **Picker** page: the agent gives you the link and the exact search text (a person's
name finds Google's face group for them), you tick each day's select-all box and press
Done, and the skill downloads exactly what you picked, at full resolution.

- `Collect all photos and videos of Mia from 2026 from Google Photos.`
- `Get the photos of our Lisbon trip from Google Photos, only 2026-05-01 to 2026-05-10.`
- `Curate the best of Mia's 2026 photos for a highlight video.`

**Before first use:** about 10 minutes, once, in Google Cloud: a project (no billing),
the Photos Picker API, a consent screen with you as test user, and a Desktop app OAuth
client (the file that lets the skill ask for your permission on Google's sign-in page);
then sign in with `auth`. Apps left in Testing must sign in again every 7 days. Step by
step: [setup.md](skills/google-photo/references/setup.md).

**What leaves your machine:** full-size files go only from Google to your disk; no other
service, no telemetry, read-only Picker permission only. During curation your agent views
small contact-sheet thumbnails (at most 256 px per tile), so those go to your agent's model
provider (e.g. Anthropic for Claude Code); it never opens the full-size files. The client
file and saved sign-in stay in `~/.config/google-photo/`, are never printed and must never
be pasted into the chat. Runs only on your own computer: refused over SSH, in a container or
on headless Linux.

Docs: [SKILL.md](skills/google-photo/SKILL.md) ·
[setup](skills/google-photo/references/setup.md) ·
[curation and picks.json](skills/google-photo/references/curation.md) ·
[error codes](skills/google-photo/references/errors.md)

### kipris-search

Searches [KIPRIS](https://www.kipris.or.kr/khome/main.do), the official Korean IP database,
for patents, utility models, trademarks and designs, and reports the queries run, the total
count and the confirmed numbers, dates, applicants, holders and legal status. It keeps
application, publication and registration numbers apart, never reads "0 results" as "the
right does not exist", and gives no opinion on registrability or infringement.

- `KIPRIS에서 '커피' 상표 검색해줘`
- `Find Korean patents on 이차전지 (secondary batteries) filed by 삼성전자.`
- `What is the status of Korean patent application 1020140061596?`

**Before first use:** nothing; the agent searches the public KIPRIS website with its own
browser tool. Optionally get a [KIPRISPlus](https://plus.kipris.or.kr/) API key and apply
there for each product you need (patent/utility, trademark, design); each product has its
own permission and period. Register the key yourself in your own terminal
with `uv run <skill folder>/scripts/kipris_api.py configure` (hidden input; ask your agent
for the full path), never in the chat. The agent then uses the API helper for list searches
([api.md](skills/kipris-search/references/api.md#registering-the-key)).

**What leaves your machine:** the API helper talks only to `plus.kipris.or.kr` over HTTPS,
with your key and the search conditions; the key stays in `~/.config/kipris-search/` and
never appears in output. The browser route visits the public KIPRIS website as you would;
logins and CAPTCHAs are handed to you.

Docs: [SKILL.md](skills/kipris-search/SKILL.md) ·
[API helper](skills/kipris-search/references/api.md) ·
[browser search](skills/kipris-search/references/browser-search.md) ·
[error codes](skills/kipris-search/references/errors.md)

### email-draft

Drafts a customer or partner email (meeting recap, follow-up, next steps, support reply) and
puts it on the clipboard as rich text, so Cmd+V into Gmail keeps the bold headers, bullets
and numbered steps instead of pasting literal `**` and `-`. The agent replies with the
subject line and a plain-text preview, and keeps its own notes out of the email. The style
is fixed: numbered Title Case sections, one requirement per sentence, full-sentence bullets
with bold action verbs, and a short help-offer sign-off.

- `Draft a recap email to Alex and Jordan from today's call: we agreed on a 50-case pilot.`
- `Rework this email so it sounds less blunt: <pasted email>`
- `Write a follow-up to the vendor asking for the revised quote by Friday.`

**Before first use:** nothing; macOS only (the clipboard step uses `osascript`). Elsewhere
the agent leaves the HTML file and gives you its path.

**What leaves your machine:** nothing beyond what you already send your agent's model
provider; the script only writes to the local clipboard.

Docs: [SKILL.md](skills/email-draft/SKILL.md)

### ga4-blog-report

Reports the Google Analytics 4 (GA4) traffic of a blog, or any site section under a path
prefix (default `/blog/`), through the GA4 Data API: pageviews and sessions per post, the top
traffic sources, and how many visits AI assistants and answer engines (ChatGPT, Perplexity,
Gemini, Copilot, Claude and others) sent, in total and per post. The raw rows go to a CSV;
the agent reports from totals the script computes, never from estimates.

- `How did my blog posts do in GA4 over the last 28 days?`
- `이번 달 블로그 유입 중에 ChatGPT나 퍼플렉시티에서 온 게 얼마나 돼?`
- `Which sources sent the most traffic to /blog/ from 2026-10-01 to 2026-10-21?`

**Before first use:** about 10 minutes, once, by hand. No command can do these steps:

1. In a Google Cloud project (no billing needed), **enable the Google Analytics Data API**
   ([console](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com), or
   `gcloud services enable analyticsdata.googleapis.com --project <project ID>`).
2. In the same project, create a service account and download a JSON key.
3. In GA4 **Admin → Property access management**, add the service account's email as
   **Viewer** (you must be an Administrator of the property).
4. Copy the numeric **Property ID** from **Admin → Property details** (not the `G-…`
   measurement ID).

Then have the agent run `configure` with the key file's path and the property ID, and delete
the downloaded key. Your own Google sign-in and gcloud's default credentials do not work for
GA4. Step by step: [setup.md](skills/ga4-blog-report/references/setup.md).

**What leaves your machine:** the script talks only to `oauth2.googleapis.com` (to exchange
the signed key for a read-only token) and `analyticsdata.googleapis.com`. The key stays in
`~/.config/ga4-blog-report/` with mode 600 and is never printed. The report's numbers, page
paths and source names go to your agent's model provider when the agent reads them.

Docs: [SKILL.md](skills/ga4-blog-report/SKILL.md) ·
[setup](skills/ga4-blog-report/references/setup.md) ·
[error codes](skills/ga4-blog-report/references/errors.md)

### youtube-download

Downloads one YouTube video as an MP4 with H.264 video and AAC audio. Accepts watch,
Shorts, Music, embed and youtu.be links. Files go to `~/Downloads/youtube/` by default,
with the video ID as the filename and a small source metadata JSON alongside it.
Compatible streams are copied; other codecs are converted with FFmpeg. Existing matching
files are reused after hash and media validation.

- `Download this YouTube video as an MP4: https://www.youtube.com/watch?v=VIDEO_ID`
- `이 유튜브 쇼츠 MP4로 저장해줘: <YouTube URL>`
- `Save this video in ~/Movies at up to 1080p: <YouTube URL>`

**Before first use:** install FFmpeg and a supported JavaScript runtime, Deno or Node.
On macOS, `brew install ffmpeg deno`. `uv` fetches the pinned yt-dlp dependency.
Supports macOS and Linux; Windows requires WSL. Downloads one complete video per link;
does not expand playlists or capture active live streams.

**What leaves your machine:** yt-dlp contacts YouTube and its media servers. The helper
does not load browser cookies or upload the downloaded video to another service.

Docs: [SKILL.md](skills/youtube-download/SKILL.md)

### domain-search

Finds domain names with Route 53 Domains using the existing AWS CLI profile. Checks
availability, suggests alternatives, and compares standard registration and renewal
prices. It distinguishes standard TLD rates from domain-specific premium pricing and
reports a price as unverified when the installed client cannot retrieve it.
GoDaddy is an optional registrar comparison; RDAP or WHOIS supplies existing registration
details. Missing lookup data never becomes a claim that a domain is available.

- `Find a short .com or .io domain for my Korean language-learning app.`
- `Check these domains in Route 53 and compare first-year and renewal costs: <domains>`
- `이 도메인 등록 정보와 만료일을 RDAP이나 WHOIS로 확인해줘: <domain>`

**Before first use:** authenticate your own AWS CLI profile with the required read
permissions. No extra SDK, custom credential store, or API key in chat is needed.
For a GoDaddy API comparison, configure a separate scoped PAT locally. Its integration
is based on current documentation and has not been account-tested.

**What leaves your machine:** candidate names go to AWS and any comparison or lookup
provider used. The skill searches only; it does not buy domains, create hosted zones,
or change DNS records or account settings.

Docs: [SKILL.md](skills/domain-search/SKILL.md) ·
[AWS setup and pricing limits](skills/domain-search/references/route53.md) ·
[GoDaddy, RDAP and WHOIS](skills/domain-search/references/providers.md)

### naver-research

Reads unpublished ideas from a Google Sheets content plan, groups related keywords, and
compares relative Naver search interest, recent momentum and seasonal timing. Shopping
category clicks provide separate supporting evidence. Every search batch includes the
same anchor group so independently scaled responses can be compared. Partial weeks,
missing data and schedules that cannot meet the target publication window are flagged.

- `Use Naver DataLab to prioritize the ideas in my plan sheet.`
- `다음에 뭐 쓰지? 데이터랩으로 관심도와 시즌을 비교하고 발행일을 제안해줘.`

**Before first use:** connect the external MIT-licensed
[naver-search-mcp](https://github.com/isnow890/naver-search-mcp), provide credentials in
its server environment, and connect Google Sheets. New credentials come from NAVER API
HUB. Keep the spreadsheet ID and blog URL in a local profile, outside the public skill.

**What leaves your machine:** keyword groups and filters go to Naver; plan rows are read
through Google Sheets. A recommendation is read-only. Only after approval does the skill
update the selected dates, status and content type. DataLab reports relative interest,
not absolute search counts or AI citation performance.

Docs: [SKILL.md](skills/naver-research/SKILL.md) ·
[setup](skills/naver-research/references/setup.md) ·
[comparison and scheduling rules](skills/naver-research/references/methodology.md).

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` or
  `brew install uv`). It fetches Python 3.11 and the pinned dependencies on first run.
- hwp-parser: optional LibreOffice (`--pdf auto`); optional `GROQ_API_KEY` / `XAI_API_KEY`
  (`--vlm`).
- google-photo: a Google account and a one-time Google Cloud project with your own Desktop
  OAuth client ([setup](skills/google-photo/references/setup.md)); optional `ffmpeg`, for
  video frames on the contact sheets.
- kipris-search: nothing beyond `uv` (standard library only); optional KIPRISPlus API key.
- email-draft: macOS for the clipboard step; no `uv` or Python needed.
- ga4-blog-report: a GA4 property you administer and a Google Cloud project with the
  Analytics Data API enabled and a service account key
  ([setup](skills/ga4-blog-report/references/setup.md)).
- youtube-download: FFmpeg with ffprobe, plus Deno or Node for YouTube extraction.
- domain-search: an authenticated AWS CLI profile with Route 53 Domains read permissions;
  optional GoDaddy PAT for registrar comparisons, or `whois` for legacy lookups.
- naver-research: connected Naver MCP with search-trend and shopping-insight access, plus
  Google Sheets access. Node.js and npx run the external MCP server.

Tested on macOS with Python 3.11. Windows and Linux are not yet verified.

## License

MIT, see [LICENSE](LICENSE). Third-party components (bundled Tesseract language data under
Apache-2.0; pyhwp, AGPL-3.0, downloaded at runtime and not bundled) are listed in
[NOTICE](NOTICE). The benchmark samples are public documents whose copyright remains with
the issuing agencies; see [bench/hwp-parser/samples/README.md](bench/hwp-parser/samples/README.md).
