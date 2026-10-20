### hwp-parser accuracy benchmark

3 public HWP 5 documents; reference = Hancom Docs PDF text layer (extracted with LiteParse 2.14.6, no OCR); LlamaParse output supplied by the repository author, generation settings unknown. Running headers and page numbers present only in the PDF lower both metrics for every system. This is a small, specific comparison, not a general claim.

| Document | System | char_accuracy | word_f1 | tables | seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| prospectus | hwp-parser | 0.877 | 0.861 | 32 | 0.7 |
| prospectus | hwp-parser --ocr | 0.818 | 0.825 | 32 | 2.7 |
| prospectus | LlamaParse (cloud) | 0.787 | 0.826 | 32 | — |
| prospectus | hwp-parser --vlm groq | not measured | | | |
| pharma-disclosure | hwp-parser | 0.793 | 0.837 | 31 | 0.5 |
| pharma-disclosure | hwp-parser --ocr | 0.793 | 0.837 | 31 | 0.7 |
| pharma-disclosure | LlamaParse (cloud) | 0.745 | 0.794 | 28 | — |
| pharma-disclosure | hwp-parser --vlm groq | not measured | | | |
| youth-rfp | hwp-parser | 0.768 | 0.806 | 17 | 0.5 |
| youth-rfp | hwp-parser --ocr | 0.768 | 0.806 | 17 | 0.5 |
| youth-rfp | LlamaParse (cloud) | 0.756 | 0.771 | 9 | — |
| youth-rfp | hwp-parser --vlm groq | not measured | | | |
| **Mean** | hwp-parser | **0.813** | **0.835** | 26.7 | 0.6 |
| **Mean** | hwp-parser --ocr | **0.793** | **0.823** | 26.7 | 1.3 |
| **Mean** | LlamaParse (cloud) | **0.763** | **0.797** | 23.0 | — |
| **Mean** | hwp-parser --vlm groq | not measured | | | |

char_accuracy = max(0, 1 − Levenshtein distance / reference length) after NFC and removing all whitespace; word_f1 = multiset F1 over whitespace tokens. Markdown/HTML syntax is stripped from each output before scoring. Values are fractions in [0, 1], rounded to 3 decimals; `tables` counts top-level HTML and GFM tables in the output; `seconds` is wall time of one hwp2md subprocess (— for LlamaParse, which was not run here). "not measured": `--vlm groq` runs only with `--with-vlm` and `GROQ_API_KEY` set.

Date 2026-10-20 · git 14e1a40 · Python 3.11.15 · lit 2.14.6 · pyhwp 0.1b15 · rapidfuzz 3.14.6 · reproduce with `uv run bench/hwp-parser/run.py`.
