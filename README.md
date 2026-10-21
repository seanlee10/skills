# seanlee10/skills

Agent skills by Sean Lee, packaged as one plugin (`seanlee10-skills`) for Claude Code,
Codex, Devin and Hermes, and installable into other agents with `npx skills`.

The first skill, **hwp-parser**, converts Korean HWP / HWPX (Hangul, 한글, 한컴) documents
into clean Markdown: text, bold/underline, outline headings, tables (as HTML, with merged
cells) and embedded images. It runs locally; nothing leaves your machine unless you ask for
`--vlm`.

The second skill, **google-photo**, collects photos and videos of a person, event or year
from Google Photos (through Google's official Picker) into a local folder and curates them
into a ranked highlight set. It runs only on your own computer.

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

Restart running sessions after installing. Plugin skills are namespaced, so the skill is
expected to load as `seanlee10-skills:hwp-parser` (unverified until a real Hermes install).
Hermes does not list plugin skills in the system prompt, so ask for the `hwp-parser` skill
by name (e.g. "Use the hwp-parser skill to convert ~/Downloads/보고서.hwp").

</details>

<details>
<summary><strong>Other agents (npx skills)</strong></summary>

```sh
npx skills@latest add seanlee10/skills -a <agent>
```

Replace `<agent>` with your agent's identifier (see `npx skills@latest --help`).

> **Install one way only.** If you install the plugin (above) *and* run `npx skills` for the
> same agent, the skill is registered twice.

</details>

Only the local Claude Code install has been verified so far; the Codex, Devin, Hermes and
`npx skills` installs are verified only after publication.

All skills run their scripts with [`uv`](https://docs.astral.sh/uv/); see
[Requirements](#requirements).

## Skills

| Skill | What it does |
| --- | --- |
| [hwp-parser](skills/hwp-parser/SKILL.md) | `.hwp` (HWP 5) / `.hwpx` to Markdown with HTML tables and extracted images. Optional local OCR, and optional Groq/xAI vision enrichment. |
| [google-photo](skills/google-photo/SKILL.md) | Collect a person's, event's or year's photos and videos from Google Photos through the official Picker into a local folder, then curate a ranked highlight set from small contact sheets. |

## hwp-parser usage

### Ask your agent

Once the plugin is installed, just ask. In Claude Code the agent picks the skill from your
request; in Hermes, name the `hwp-parser` skill in the request (see
[Install](#install)). The agent runs the converter and reads the Markdown for you.

- `이 한글 파일 마크다운으로 바꿔줘: ~/Downloads/보고서.hwp`
- `~/Documents/제안요청서.hwpx 내용 요약해줘` (the agent converts first, then reads the Markdown)
- `Convert ~/Downloads/report.hwp to Markdown and put it in ~/notes.`
- `What is the budget in "~/Downloads/2024년 사업계획.hwp"?`
- `Convert scan.hwp; the pages are scanned images, so use OCR.`
- `Convert brochure.hwp and describe the charts with Groq.` (only an explicit request like
  this makes the agent use `--vlm`; it sends the images to Groq)

### Run it yourself

The skill is a single script run by `uv`. From a clone of this repository:

```sh
git clone https://github.com/seanlee10/skills
cd skills
uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp"
```

(Inside Claude Code the script lives at `${CLAUDE_SKILL_DIR}/scripts/hwp2md.py`.) The first
run creates an isolated Python 3.11 environment with pinned dependencies; nothing is
installed into your own Python or into the skill folder. Always quote paths: Korean names and
spaces are common.

```
uv run skills/hwp-parser/scripts/hwp2md.py INPUT [--out-dir DIR] [--force] [--ocr] [--pdf FILE|auto] [--vlm groq|xai]
uv run skills/hwp-parser/scripts/hwp2md.py --check-vlm groq|xai
```

### Flags

| Flag | Effect | Network |
| --- | --- | --- |
| *(none)* | Direct extraction of text, tables and images. | No |
| `--out-dir DIR` | Write output into `DIR` instead of next to the input. | No |
| `--force` | Replace an existing `<stem>.md` / `<stem>_assets/`. Without it the run refuses to overwrite. | No |
| `--ocr` | Local OCR of embedded raster images (LiteParse + bundled Korean/English Tesseract data). | No |
| `--pdf FILE` | OCR a PDF rendering of the same document and append pages whose text direct extraction missed. | No |
| `--pdf auto` | Experimental, HWP 5 only: render the PDF locally with LibreOffice, then as `--pdf FILE`. | No |
| `--vlm groq` / `--vlm xai` | Experimental — xAI checked live once, Groq not yet. Send embedded images to a vision LLM and add its reading under each image; BMP/GIF/TIFF/WebP are converted to PNG in memory first. | **Yes** |
| `--check-vlm groq` / `--check-vlm xai` | Key preflight, used alone (no INPUT): prints `{"status":"ok","provider":…,"key_env":…,"key_present":true\|false}`, exits 0, never prints the key. | No |

Examples:

```sh
# Default: writes ~/Downloads/보고서.md (+ ~/Downloads/보고서_assets/ if it has images)
uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp"

# Write somewhere else
uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp" --out-dir "$HOME/notes"

# Overwrite a previous conversion
uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp" --force

# OCR text that only exists inside embedded images (offline)
uv run skills/hwp-parser/scripts/hwp2md.py scan.hwp --ocr

# Add text from a Hancom-exported PDF that direct extraction missed (offline)
uv run skills/hwp-parser/scripts/hwp2md.py brochure.hwpx --pdf brochure.pdf

# Same, but render the PDF locally with LibreOffice (experimental, HWP 5 only)
uv run skills/hwp-parser/scripts/hwp2md.py brochure.hwp --pdf auto

# Describe embedded images with a vision LLM (sends images to Groq or xAI).
# Experimental: xAI checked live once, Groq not yet.
uv run skills/hwp-parser/scripts/hwp2md.py brochure.hwp --vlm groq
uv run skills/hwp-parser/scripts/hwp2md.py brochure.hwp --vlm xai

# Flags combine; each image then gets one note per source
uv run skills/hwp-parser/scripts/hwp2md.py brochure.hwp --ocr --pdf brochure.pdf --out-dir out --force
```

`--vlm` is experimental. One live run against xAI (`grok-4.3`) on a dense Korean diagram read every number correctly but misread several proper nouns (company and fund names), so check names against the source. Groq has not been run live yet. BMP, GIF, TIFF and WebP images (and PNG/JPEG over 3 MiB) are converted to PNG or JPEG in memory first, long side capped at 2048 px; the saved asset is unchanged. Images that cannot be decoded (e.g. WMF/EMF drawings, OLE objects) are skipped with `VLM_SKIPPED`.

Details: [skills/hwp-parser/references/ocr-vlm.md](skills/hwp-parser/references/ocr-vlm.md).

### Output

```
~/Downloads/
├── 보고서.hwp            # input (unchanged)
├── 보고서.md             # the Markdown
└── 보고서_assets/        # only if the document embeds files
    ├── a0.png
    └── a1.jpg
```

Output goes next to the input (or into `--out-dir`), never into the current directory. It is
staged in a temporary folder and moved into place, so a failed run leaves nothing behind.

On success (exit 0) stdout is one JSON summary:

```json
{"status": "ok", "markdown": "/abs/보고서.md", "assets_dir": "/abs/보고서_assets",
 "tables": 3, "images": 2, "paths": ["direct"], "warnings": ["PYHWP_EXPERIMENTAL_COVERAGE"]}
```

On failure (exit 2) the last stderr line is `{"status":"failed","error":CODE,"message":...}`.
On the first run `uv` may also print install/progress lines to stderr before the script's own JSON lines.

Markdown conventions: headings only from outline styles (`개요 1` becomes `##`), tables as
HTML `<table>` with `rowspan`/`colspan`, images as `![](<보고서_assets/a0.png>)` (or `<img>`
inside table cells), OCR/VLM notes as a blockquote under the image. Full reference:
[skills/hwp-parser/references/format.md](skills/hwp-parser/references/format.md).

### Example: a real conversion

The start of `bench/hwp-parser/samples/youth-rfp.hwp` (a public request for proposals),
converted with no flags:

```markdown
<table><tr><td>2024년 청년도전지원사업·청년성장프로젝트 공모전 시상식 대행 용역 제안요청서</td></tr></table>

**2024. 8.**

**고용노동부**

<table><tr><td><strong>Ⅰ</strong></td><td>개요</td></tr></table>

**1. 과업개요**

ㅇ 과업명: 청년도전지원사업‧청년성장프로젝트 우수사례 공모전 시상식

ㅇ 과업목적: 위탁자가 주최하는 ’청년도전지원사업‧청년성장프로젝트 우수사례 공모전 시상식 행사‘의 기획, 제작, 행사의 운영, 진행 등 위탁

ㅇ 예  산: 70,000,000원(부가가치세 포함)

ㅇ 과업기간: 계약일로부터 2024년 12월 15일까지
```

and, later in the same file, a form with merged cells:

```markdown
**&lt;붙임 10&gt;**

<table><tr><td colspan="4"><strong>가  격  입  찰  서</strong></td></tr><tr><td>입찰 공고 번호</td><td></td><td>입찰일자</td><td>년  월  일</td></tr><tr><td>입  찰  건  명</td><td colspan="3"></td></tr><tr><td>입  찰  금  액</td><td colspan="3"></td></tr><tr><td>완 료 년 월 일</td><td colspan="3"></td></tr><tr><td colspan="4">본인은 국가를 당사자로 하는 계약에 관한 법률 시행규칙에 의한 용역 입찰     유의서에 따라 응찰하여 이 입찰이 귀 기관에 의하여 수락되면 용역계약    일반조건․동 특수조건에 따라 위의 입찰금액으로 완료기한 내에 용역을    완성할 것을 확약하며 입찰서를 제출합니다.<br />별 첨 : 세부예산 산출 내역 1부.<br />2024년    월     일<br />상 호  또는 명 칭 :<br />주             소 :                       전화번호 :<br />대표자       성명 :                       (인)<br />주민(법인)등록번호 :<br /><strong>고용노동부장관 귀하</strong></td></tr></table>
```

### API keys (only for `--vlm`)

Keys are read only from environment variables, never from `.env` files or the command line.
Set them in the environment that starts your agent:

```sh
export GROQ_API_KEY=...   # for --vlm groq
export XAI_API_KEY=...    # for --vlm xai
```

Never paste a key into the chat. A missing key fails before anything is sent
(`GROQ_API_KEY_MISSING` / `XAI_API_KEY_MISSING`). Check without sending anything:

```sh
uv run skills/hwp-parser/scripts/hwp2md.py --check-vlm groq   # {"status":"ok",...,"key_present":true}
```

When you ask for VLM enrichment the agent runs this check first; if the key is missing it
asks you to export it in your shell and restart the session (or continue without `--vlm`).

### Network only with `--vlm`

Everything is local except `--vlm`. Direct extraction, `--ocr`, `--pdf FILE` and
`--pdf auto` never open a network connection (the first `uv run` downloads the pinned
packages from PyPI; conversions themselves are offline). With `--vlm groq` only Groq is
contacted, with `--vlm xai` only xAI; only embedded images (as PNG/JPEG of at most 3 MiB each) are
sent, not the document text. The agent is instructed never to pass `--vlm` unless you ask,
and to confirm first for a non-public document.

### Common errors

| Code | Meaning | Remedy |
| --- | --- | --- |
| `MISSING_OR_OVERSIZE_INPUT` | Input missing, not a regular file, or over 128 MiB. | Check the path (absolute, quoted). |
| `UNSUPPORTED_SIGNATURE_HWP3_OR_OTHER` | Neither HWP 5 nor HWPX (e.g. HWP 3, PDF, a renamed file). | Re-save HWP 3 files as HWP/HWPX in Hancom Office. |
| `PASSWORD_PROTECTED_HWP` | The HWP is password protected. | Remove the password in Hancom Office and save an unprotected copy. |
| `OUTPUT_ALREADY_EXISTS` | `<stem>.md` or `<stem>_assets/` already exists. | Rerun with `--force`, or choose another `--out-dir`. |
| `NO_EXTRACTABLE_TEXT` | No text in the body (likely scanned images). | Retry with `--ocr` (and/or `--pdf FILE`). |
| `GROQ_API_KEY_MISSING` / `XAI_API_KEY_MISSING` | The provider's key is not set. Nothing was sent. | Set the env var (see above). |

Every error and warning code: [skills/hwp-parser/references/errors.md](skills/hwp-parser/references/errors.md).

### Supported formats and limits

- **Supported:** HWPX (`application/hwp+zip` packages) and HWP 5 (OLE compound files, read
  through pyhwp in a sandboxed child process).
- **Not supported:** HWP 2/3, standalone HWPML XML, PDFs, Word files.
- **No decryption:** password-protected, distribution, DRM and certificate-encrypted
  documents fail with an explicit code.
- **Text in images** is extracted only with `--ocr` / `--pdf`; OCR output can contain errors.
- **Reading order** follows the file, not the visual layout: multi-column pages and floating
  text boxes may come out of order; captions come after their table.
- **Headings** come only from outline paragraph styles, never from font size.
- **Resource limits:** input 128 MiB; each package member / embedded asset 64 MiB; expanded
  totals 256 MiB; at most 4096 ZIP members; pyhwp 90 s timeout. ZIP path escapes, DTDs and
  XML entities are rejected.

More: [format.md](skills/hwp-parser/references/format.md#limits).

## Accuracy

Methodology: three public HWP 5 documents (in
[bench/hwp-parser/samples](bench/hwp-parser/samples/README.md)) are converted by hwp-parser
with and without `--ocr`, and compared, together with a LlamaParse cloud output of the same
documents, against a reference text: the text layer of a PDF exported from Hancom Docs,
extracted with LiteParse without OCR. Each output has its Markdown/HTML syntax stripped and is
scored by character accuracy (Levenshtein, whitespace removed) and word F1. Reproduce with
`uv run bench/hwp-parser/run.py`.

Caveats:

- **3 documents, not a general claim.** All three are HWP 5; there is no HWPX document in the
  benchmark.
- The reference is the Hancom Docs PDF text layer, which contains running headers and page
  numbers that no converter emits; this lowers every system's score.
- The LlamaParse output was supplied by the repository author (generation settings unknown). It is a
  baseline, not ground truth.
- `--ocr` scores lower on `prospectus` because it adds text read from images, which is not in
  the PDF text layer, so the drop reflects text the reference lacks. This benchmark does not
  measure whether the OCR text itself is correct.
- `--vlm` is not measured. It runs only with `--with-vlm` and `GROQ_API_KEY` set.

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

## google-photo usage

**google-photo** collects the photos and videos of a person, event or year from your Google
Photos into a local folder (one per subject per year), then curates them down to a ranked
highlight set, by default about 75 photos and 8 clips, enough for a 2–3 minute video.

Google no longer lets apps read a Photos library directly, so the skill uses the official
**Google Photos Picker**: it gives you a link to Google's own picker page, you search (for
example a person's name: the picker finds Google's face group for them) and select, using
the select-all checkbox next to each day, and press Done. The skill downloads exactly what
you picked, at full resolution.

### Ask your agent

Once the plugin is installed, just ask. In Claude Code the agent picks the skill from your
request; in Hermes, name the `google-photo` skill in the request.

- `Collect all photos and videos of Mia from 2026 from Google Photos.`
- `Get the photos of our Lisbon trip from Google Photos, only 2026-05-01 to 2026-05-10.`
- `Curate the best of Mia's 2026 photos for a highlight video.`
- `Add the photos of Mia I just found to her 2026 folder.` (only new items are downloaded)

The agent runs `check`, signs you in if needed, sends you the picker link and tells you
exactly what to type in the picker's search box, waits for you to press Done, downloads,
then curates and reports every count (downloaded, already present, filtered out, skipped).

### One-time setup

The skill signs in with your own OAuth client in your own Google Cloud project (about 10
minutes, once):

1. `gcloud projects create <id>` and
   `gcloud services enable photospicker.googleapis.com --project=<id>`.
2. In the web console: the consent screen (Google Auth Platform → Get started, Audience
   **External**, then add your Gmail address as a **test user**) and a **Desktop app**
   OAuth client (Download JSON).
3. Save the JSON as `~/.config/google-photo/client_secret.json` (or point
   `GOOGLE_PHOTO_CLIENT_SECRET` at it).
4. `gphoto.py auth`: sign in in the browser; "Google hasn't verified this app" is expected
   for your own app (Continue).

Apps left in Testing get refresh tokens that expire after 7 days; then the skill asks you to
run `auth` again. Step by step, with console links:
[skills/google-photo/references/setup.md](skills/google-photo/references/setup.md).

### Run it yourself

```sh
uv run skills/google-photo/scripts/gphoto.py check
uv run skills/google-photo/scripts/gphoto.py auth
uv run skills/google-photo/scripts/gphoto.py start --subject Mia --year 2026
#   -> the picker opens in the browser (or open picker_uri): search "Mia", select each day, press Done
uv run skills/google-photo/scripts/gphoto.py fetch            # repeat while "status":"waiting"
uv run skills/google-photo/scripts/gphoto.py curate --subject Mia --year 2026
#   -> the agent reads the contact sheets and writes curation/picks.json
uv run skills/google-photo/scripts/gphoto.py select --subject Mia --year 2026
```

(Inside Claude Code the script lives at `${CLAUDE_SKILL_DIR}/scripts/gphoto.py`.)

| Command | What it does | Network |
| --- | --- | --- |
| `check` | Is this machine ready: client file, sign-in, ffmpeg. | No |
| `auth` | Browser sign-in; saves a refresh token (mode 0600). | Google |
| `start --subject NAME --year YYYY [--search TEXT] [filters]` | Creates a picking session, opens the picker link in the default browser (skip with `--no-browser`; `BROWSER_NOT_OPENED` in `warnings` if it could not) and prints the link. Filters, applied after picking: `--from/--to YYYY-MM-DD` (inside the year), `--type photo\|video\|all`, `--camera TEXT`, `--orientation portrait\|landscape`, `--min-side PX`; also `--tz ZONE`, `--out-root DIR`. | Google |
| `fetch [--session ID] [--wait SECONDS]` | Waits up to `--wait` (default 540 s) for Done, then downloads the picked items; the download itself is not bounded by `--wait` and can take much longer. If it is killed (e.g. by a timeout), or stopped by Ctrl-C or a failure while waiting for Done or listing, run `fetch` again; after Ctrl-C or a failure while downloading, the session is closed: run `start` and pick again. Finished items are kept either way. | Google |
| `curate --subject NAME --year YYYY [--target N] [--video-target N]` | Local pre-filter (near-duplicates, blurry, dark, month balance) and contact sheets. Defaults: 75 photos, 8 videos. | No |
| `select --subject NAME --year YYYY [--picks FILE]` | Applies the ranked picks: `selected/` and `selection.json`. | No |

A session holds at most 2,000 items; for more, or for a second search, run another
`start` / `fetch` pair with the same subject and year. Items already downloaded are never
downloaded twice.

### Output

```
~/Pictures/google-photo/          # default --out-root
└── Mia/2026/
    ├── manifest.json             # every downloaded item: file, capture time, type, size, camera…
    ├── media/                    # full-size originals (never deleted by the skill)
    ├── .thumbs/                  # small Google thumbnails, used for curation
    ├── curation/
    │   ├── candidates.json       # pre-filtered candidates
    │   ├── sheets/sheet-01.jpg…  # contact sheets the agent looks at
    │   └── picks.json            # the agent's ranked picks
    ├── selection.json            # the final ranked selection with a reason per item
    └── selected/                 # 001_<file>, 002_<file>… in rank order
```

Files in `selected/` are hard links to the originals in `media/` (copies where hard links
are not possible): editing one in place edits the original, so copy them before editing. A
`.DS_Store` in `selected/` triggers the harmless `SELECTED_FOLDER_HAS_OTHER_FILES` warning.

### Privacy

- **Local only.** The skill runs only on your own computer. Over SSH, in a container or on
  headless Linux it refuses (`REMOTE_ENVIRONMENT_REFUSED`) before signing in or
  downloading anything.
- **Full-size files go only from Google to your disk.** No other service, no telemetry. Only
  the read-only Picker permission is requested, so the skill sees only what you pick.
- **Thumbnails go to your agent's model during curation.** The agent looks at the contact
  sheets (tiles of at most 256 px) to choose shots, so those small thumbnails are sent to
  your agent's own model provider (e.g. Anthropic for Claude Code). It never opens the
  full-size files.
- **Never paste tokens** or the client secret into the chat. They stay in
  `~/.config/google-photo/` and the skill never prints them.

The API returns no location, people or description, so there is no place filter and the
skill cannot check who is in a photo: who is pictured is decided by your search in the
picker. Every error and warning code:
[skills/google-photo/references/errors.md](skills/google-photo/references/errors.md).
Curation rubric: [skills/google-photo/references/curation.md](skills/google-photo/references/curation.md).

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` or
  `brew install uv`). It fetches Python 3.11 and the pinned dependencies on first run.
- Optional: LibreOffice, only for `--pdf auto`.
- Optional: a `GROQ_API_KEY` or `XAI_API_KEY`, only for `--vlm`.
- google-photo: a Google account and a one-time Google Cloud project with your own Desktop
  OAuth client ([setup](skills/google-photo/references/setup.md)); optional `ffmpeg`, for
  video frames on the contact sheets.

Tested on macOS with Python 3.11. Windows and Linux are not yet verified.

## License

MIT, see [LICENSE](LICENSE). Third-party components (bundled Tesseract language data under
Apache-2.0; pyhwp, AGPL-3.0, downloaded at runtime and not bundled) are listed in
[NOTICE](NOTICE). The benchmark samples are public documents whose copyright remains with
the issuing agencies; see [bench/hwp-parser/samples/README.md](bench/hwp-parser/samples/README.md).
