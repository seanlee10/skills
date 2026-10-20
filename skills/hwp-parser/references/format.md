# Output format, inputs, limits and validation

## Supported inputs

- **HWPX**: a ZIP package with `mimetype` = `application/hwp+zip`, a manifest/spine in
  `Contents/content.hpf`, and the body sections (`Contents/sectionN.xml`) the spine
  references. Root-relative and safe package-relative hrefs are resolved. Mis-cased paths,
  non-standard section names and external URIs are not repaired.
- **HWP 5**: an OLE compound file with the HWP 5 signature and a supported version, read
  through `pyhwp` 0.1b15 (XML conversion in a sandboxed child process) and `olefile`.
- Not supported: HWP 2/3, standalone HWPML XML, other OWPML packaging variants.
- No unlocking. Password-protected, distribution, DRM and certificate-encrypted documents
  fail with an explicit code; digital signatures are not validated (warning
  `SIGNATURE_NOT_VALIDATED`).

Resource limits (any breach fails with a code, see [errors.md](errors.md)): input 128 MiB;
each package member / embedded asset 64 MiB; expanded ZIP total, OLE streams and assets
256 MiB each; at most 4096 ZIP members. ZIP path escapes, duplicate members, DTDs and XML
entities are rejected. The pyhwp child process has a 90 s timeout and, on POSIX, CPU and
file-size rlimits. These limits are defence in depth, not a full sandbox.

## Output files

For `INPUT` = `dir/<stem>.hwp` (or `.hwpx`):

```
<target>/<stem>.md
<target>/<stem>_assets/a0.png, a1.jpg, …   (only if the document embeds files)
```

`<target>` is `--out-dir` if given, else the input's own folder (never the current
directory). If either path exists the run fails with `OUTPUT_ALREADY_EXISTS` unless
`--force` is passed. Output is written to a temporary folder in `<target>` and renamed into
place, so a failed run leaves nothing behind.

Assets are named `a<N>` in document order. JPEG, PNG, GIF, BMP, TIFF and WebP are
recognised by signature; any other embedded bytes (WMF/EMF/OLE objects, …) are kept as
`.bin` with warning `UNINTERPRETED_BINARY:<id>`. Asset bytes are the original embedded
bytes; crops, rotation and other display effects are not applied. Linked external images
are not fetched.

## stdout / stderr contract

- Exit 0: stdout holds exactly one JSON object:

  ```json
  {"status": "ok", "markdown": "/abs/doc.md", "assets_dir": "/abs/doc_assets",
   "tables": 3, "images": 2, "paths": ["direct", "ocr"], "warnings": ["OCR_EMPTY:a1"]}
  ```

  `assets_dir` is `null` when there are no assets. `tables` / `images` count all tables and
  images, nested ones included. `paths` lists what contributed: `direct` always, `ocr` when
  OCR added text, `vlm:groq` / `vlm:xai` when images were sent.
- stderr carries only the script's JSON lines, but on the first run `uv` may print
  install/progress lines to stderr before them.
- Exit 2: the last stderr line is `{"status":"failed","error":CODE,"message":...}`.
  Messages are fixed English strings: they never contain document text, file paths, keys or
  tracebacks.
- `--check-vlm <provider>` (used alone) prints exactly one JSON object on stdout,
  `{"status":"ok","provider":"groq","key_env":"GROQ_API_KEY","key_present":true}`, and exits 0
  whether or not the key is set. It makes no network call and never prints the key.
- With `--vlm`, a line `{"notice":"sending N image(s) to <provider>"}` is written to stderr
  before the first request.

## Markdown conventions

- **Paragraphs** are separated by one blank line; never more than one consecutive blank
  line. Line breaks inside a paragraph become a Markdown hard break (two spaces + newline).
- **Bold** runs become `**…**` (or `<strong>…</strong>` where `**` would not parse next to
  punctuation; always `<strong>` inside tables). **Underlined** runs become `<u>…</u>`, in
  Markdown and in table HTML alike.
- **Headings** come only from outline paragraph styles named `개요 N`, `Outline N` or
  `Heading N`: level N becomes `#` × (N + 1), capped at `######` (so `개요 1` is `##`).
  Headings are never inferred from font size or numbering.
- **Escaping** outside tables: `` \ ` * _ ~ [ ] `` are always backslash-escaped; `&`, `<`,
  `>` become `&amp;`, `&lt;`, `&gt;` (so `&lt;` in the output is a `<` in the document); `#`
  is escaped only at the start of a line; a line made only of `-` / `=` is escaped so it
  cannot become a rule or setext heading, and trailing `#`s in a heading are escaped so they
  are not dropped. Inside tables, text is HTML-escaped (`&`, `<`, `>`).
- **Tables** are HTML `<table>` with `rowspan` / `colspan` for merged cells and `<th>` for
  header cells. Nested tables stay nested. Paragraphs in a cell are joined with `<br />`.
- **Images** outside tables: `![](<stem_assets/a0.png>)` (angle brackets so spaces and
  Korean names work). Inside a table cell: `<img src="stem_assets/a0.png" />`, because
  Markdown image syntax does not render inside HTML.
- **OCR / VLM notes** go right under their image: `> **OCR:** …` or `> **VLM (groq):** …`
  as a blockquote; inside a table cell as `<blockquote><strong>OCR:</strong> …</blockquote>`.
- **Rendered-page OCR** (`--pdf`) is appended at the end under `## OCR (rendered pages)`
  with one `### Page N` per appended page. See [ocr-vlm.md](ocr-vlm.md).

## Limits

- Text inside images is not extracted without `--ocr` / `--pdf`. A document whose body has
  no text fails with `NO_EXTRACTABLE_TEXT` unless OCR is requested.
- Order is the XML order of the file, not the visual reading order: multi-column layouts,
  floating text boxes and anchored objects may come out of visual order. Captions are
  emitted after their table.
- Headings only from outline styles (above). Documents styled by hand have no headings.
- Empty paragraphs, page breaks, most character styling, fonts and colours are dropped.
  Footnotes, memos, fields, equations, change history and hidden text are not guaranteed to
  be complete (warning `DOCUMENT_HISTORY_NOT_EXTRACTED` when history is present).
- HWPX background images, master pages and header/footer objects may not all be linked.
  Text found in package parts outside the body sections is reported with
  `TEXT_OUTSIDE_SECTIONS_REQUIRES_REVIEW:<part>`, not converted.
- HWP 5 coverage depends on pyhwp; every HWP 5 conversion carries
  `PYHWP_EXPERIMENTAL_COVERAGE`.
- Scripts embedded in the document are never executed (`SCRIPTS_PRESENT_NOT_EXECUTED`).
- No decryption, no HWP 3.

## Validation record

What has been checked, as of the first release (2026-10-20, macOS, Python 3.11.15):

- **Self-test**: the skill's test suite (`skills/hwp-parser/tests/`) and the repository
  checks (`tests/test_repo.py`) pass. They cover synthetic HWPX fixtures (section order,
  Korean text and tabs, nested and merged tables, images in cells, Markdown/HTML
  metacharacters, blank-line runs, paths with spaces and Korean characters), every HWPX
  rejection path (path escape, DTD/entities, encryption flag, wrong mimetype, broken
  XML/spine, missing sections, existing output), synthetic HWP 5 protection flags, local OCR
  on a Korean test image, `--pdf` page de-duplication, and the Groq/xAI request contract
  against a mocked network.
- **Public samples**: three public Korean HWP 5 documents in `bench/hwp-parser/samples/`
  (a prospectus, a pharma disclosure guide, a request for proposals), each with a Hancom
  Docs PDF and a LlamaParse baseline. They convert end to end, with and without `--ocr`.
- **Accuracy**: character accuracy, word F1 and table counts against the PDF text layer are
  in the benchmark report,
  [bench/hwp-parser/results.md](https://github.com/seanlee10/skills/blob/main/bench/hwp-parser/results.md)
  (reproduce with `uv run bench/hwp-parser/run.py` in the repository). It is a small,
  specific comparison, not a general accuracy claim.

Not verified:

- `--pdf auto` with a real LibreOffice installation (only the code path with a stubbed
  converter and the "LibreOffice missing" failure were tested). LibreOffice rendering is
  not equivalent to Hancom rendering; Korean glyphs may be lost without suitable fonts.
- Live Groq and xAI calls (no keys in the test environment); response quality is unmeasured.
- Installs in Codex, Devin and Hermes, until the repository is published.
- Real encrypted/DRM documents (only synthetic header flags), Hancom HWPX→PDF export,
  Windows and Linux runs, broad document compatibility.
