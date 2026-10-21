# hwp-parser accuracy benchmark

A small, reproducible comparison of [hwp-parser](../../skills/hwp-parser/SKILL.md) against a
cloud baseline on three public Korean documents. The current numbers are in
[results.md](results.md) (machine-readable: [results.json](results.json)); the same table is
copied into the repository's [README.md](../../README.md#hwp-parser-accuracy-benchmark) and
[README.ko.md](../../README.ko.md#hwp-parser-accuracy-benchmark).

## Method

- **Samples.** Three public HWP 5 documents in [samples/](samples/README.md): a prospectus,
  a pharma disclosure guide and a request for proposals.
- **Systems.** hwp-parser with no flags, hwp-parser `--ocr`, and a LlamaParse cloud output of
  the same documents (`samples/<doc>.llamaparse.md`). `hwp-parser --vlm groq` is listed but
  measured only on request (see below).
- **Reference.** The text layer of a PDF exported from Hancom Docs ("Save as PDF"),
  extracted with LiteParse without OCR (`lit parse <doc>.pdf --no-ocr --format text`).
- **Scoring.** Each output has its Markdown/HTML syntax stripped, then:
  - `char_accuracy` = max(0, 1 − Levenshtein distance / reference length), after NFC
    normalisation and removing all whitespace;
  - `word_f1` = multiset F1 over whitespace-separated tokens;
  - `tables` = top-level HTML and GFM tables in the output;
  - `seconds` = wall time of one `hwp2md` subprocess (none for LlamaParse, which is read
    from a file, not run).

  Values are fractions in [0, 1], rounded to 3 decimals.

## Caveats

- **3 documents, not a general claim.** All three are HWP 5; there is no HWPX document in
  the benchmark.
- The reference is the Hancom Docs PDF text layer, which contains running headers and page
  numbers that no converter emits; this lowers every system's score.
- The LlamaParse output was supplied by the repository author (generation settings
  unknown). It is a baseline, not ground truth.
- `--ocr` scores lower on `prospectus` because it adds text read from images, which is not
  in the PDF text layer, so the drop reflects text the reference lacks. This benchmark does
  not measure whether the OCR text itself is correct.
- `--vlm` is not measured by default. It runs only with `--with-vlm` and `GROQ_API_KEY`
  set, and then sends the documents' embedded images to Groq.

## Reproduce

From a clone of the repository:

```sh
uv run bench/hwp-parser/run.py                  # run everything, write results.json and results.md
uv run bench/hwp-parser/run.py --update-readme  # also refresh the table in README.md and README.ko.md
uv run bench/hwp-parser/run.py --check          # write nothing; exit 1 if any hwp-parser char_accuracy
                                                # dropped more than 0.01 below results.json
uv run bench/hwp-parser/run.py --with-vlm       # also measure --vlm groq (needs GROQ_API_KEY; network)
```

Converted outputs go to `bench/hwp-parser/out/` (git-ignored). `--update-readme` replaces
the text between the `<!-- bench:start -->` and `<!-- bench:end -->` markers in both READMEs
and checks both markers exist before the (slow) run starts. The repository tests check that
both README tables match `results.md`.

## Sample output

The start of `samples/youth-rfp.hwp` (a public request for proposals), converted with no
flags:

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

The Markdown conventions behind this (headings, escaping, tables, images) are in
[format.md](../../skills/hwp-parser/references/format.md#markdown-conventions).
