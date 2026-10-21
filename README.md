**English** | [한국어](README.ko.md)

# seanlee10/skills

Agent skills by Sean Lee for Korean documents, Korean IP search and Google Photos, packaged
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
`npx skills` installs are verified only after publication. Every skill runs its script with
[`uv`](https://docs.astral.sh/uv/) (see [Requirements](#requirements)).

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
- `--pdf FILE` (or experimental `--pdf auto`, via LibreOffice): add text that direct
  extraction missed from a PDF rendering of the same document.
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
browser tool.
Optionally get a [KIPRISPlus](https://plus.kipris.or.kr/) API key (apply there for each
product: patent/utility, trademark, design) and register it yourself in your own terminal
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

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` or
  `brew install uv`). It fetches Python 3.11 and the pinned dependencies on first run.
- hwp-parser: optional LibreOffice (`--pdf auto`); optional `GROQ_API_KEY` / `XAI_API_KEY`
  (`--vlm`).
- google-photo: a Google account and a one-time Google Cloud project with your own Desktop
  OAuth client ([setup](skills/google-photo/references/setup.md)); optional `ffmpeg`, for
  video frames on the contact sheets.
- kipris-search: nothing beyond `uv` (standard library only); optional KIPRISPlus API key.

Tested on macOS with Python 3.11. Windows and Linux are not yet verified.

## License

MIT, see [LICENSE](LICENSE). Third-party components (bundled Tesseract language data under
Apache-2.0; pyhwp, AGPL-3.0, downloaded at runtime and not bundled) are listed in
[NOTICE](NOTICE). The benchmark samples are public documents whose copyright remains with
the issuing agencies; see [bench/hwp-parser/samples/README.md](bench/hwp-parser/samples/README.md).
