[English](README.md) | **한국어**

# seanlee10/skills

Sean Lee가 만든 에이전트 스킬 모음입니다. 한글 문서 변환, 한국 특허·상표 검색, Google 포토
정리를 다룹니다. Claude Code, Codex, Devin, Hermes용 플러그인 하나(`seanlee10-skills`)로
묶여 있고, 그 밖의 에이전트에는 `npx skills`로 설치할 수 있습니다.

## 설치

<details>
<summary><strong>Claude Code</strong></summary>

Claude Code 안에서:

```
/plugin marketplace add seanlee10/skills
/plugin install seanlee10-skills@seanlee10
```

또는 셸에서:

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

설치한 뒤에는 실행 중인 세션을 다시 시작하세요. 플러그인 스킬은 네임스페이스가 붙어
`seanlee10-skills:hwp-parser` 같은 이름으로 로드될 것으로 예상합니다(실제 Hermes 설치로는
아직 확인하지 못했습니다). Hermes는 시스템 프롬프트에 플러그인 스킬을 나열하지 않으므로,
요청할 때 스킬 이름을 직접 말해 주세요(예: "hwp-parser 스킬로 ~/Downloads/보고서.hwp 변환해줘").

</details>

<details>
<summary><strong>기타 에이전트 (npx skills)</strong></summary>

```sh
npx skills@latest add seanlee10/skills -a <agent>
```

`<agent>` 자리에는 사용하는 에이전트의 식별자를 넣습니다(`npx skills@latest --help` 참고).

> **설치는 한 가지 방법으로만 하세요.** 위의 플러그인을 설치하고 같은 에이전트에 `npx skills`까지
> 실행하면 스킬이 두 번 등록됩니다.

</details>

지금까지 검증한 것은 로컬 Claude Code 설치뿐입니다. Codex, Devin, Hermes, `npx skills` 설치는
저장소를 공개한 뒤에 검증합니다. 모든 스킬은 [`uv`](https://docs.astral.sh/uv/)로 스크립트를
실행합니다([요구 사항](#요구-사항) 참고).

설치가 끝나면 에이전트에게 그냥 요청하면 됩니다. 에이전트가 요청을 보고 알맞은 스킬을 고릅니다
(Hermes에서는 스킬 이름을 말해 주세요). 스크립트를 직접 실행하려면 저장소를 clone한 뒤, 각
스킬 SKILL.md의 "Run" 절에 있는 명령에서 스킬 폴더 자리에 `skills/<스킬>`을 넣어 실행합니다.
예: `uv run skills/hwp-parser/scripts/hwp2md.py "$HOME/Downloads/보고서.hwp"`.

## 스킬

| 스킬 | 하는 일 | 준비물 | 네트워크 |
| --- | --- | --- | --- |
| [hwp-parser](skills/hwp-parser/SKILL.md) | `.hwp` / `.hwpx` 문서를 HTML 표와 이미지가 포함된 Markdown으로 변환 | 없음 | 기본은 사용 안 함, `--vlm`을 쓸 때만 Groq 또는 xAI |
| [google-photo](skills/google-photo/SKILL.md) | Google 포토에서 특정 인물·행사·연도의 사진과 동영상을 모으고 하이라이트를 골라 줌 | Google Cloud 1회 설정 | Google |
| [kipris-search](skills/kipris-search/SKILL.md) | KIPRIS에서 한국 특허·실용신안·상표·디자인 검색 | 없음 (KIPRISPlus 키는 선택) | KIPRIS |

### hwp-parser

한글(HWP 5, `.hwp`)과 HWPX(`.hwpx`) 문서를 Markdown 파일 하나와 내장 이미지 폴더로
변환합니다. 본문, 굵게·밑줄, 개요 스타일 제목, 셀 병합까지 살린 HTML 표를 그대로 옮깁니다.
결과는 입력 파일 옆에 만들어지고, `--force` 없이는 기존 파일을 덮어쓰지 않습니다. HWP 3 이하,
PDF, Word 파일은 지원하지 않으며 암호 해제도 하지 않습니다.

- `이 한글 파일 마크다운으로 바꿔줘: ~/Downloads/보고서.hwp`
- `"~/Downloads/2024년 사업계획.hwp"에서 예산이 얼마야?`
- `scan.hwp 변환해줘. 스캔한 이미지 문서라서 OCR 써야 해.`

요청하면 에이전트가 붙이는 옵션:

- `--ocr`: 내장 이미지 속 글자를 로컬 OCR로 읽습니다(한국어·영어 데이터 포함).
- `--pdf FILE` (또는 실험 기능 `--pdf auto`, HWP 5 전용, LibreOffice 사용): 같은 문서를
  PDF로 렌더링한 결과에서, 직접 추출로 놓친 텍스트를 덧붙입니다.
- `--vlm groq` / `--vlm xai`: 실험 기능. 비전 모델이 내장 이미지를 읽고 설명을 붙입니다.

**처음 쓰기 전에:** `uv` 말고는 필요 없습니다. `--pdf auto`에는 LibreOffice가, `--vlm`에는
에이전트를 실행하는 셸에 export한 `GROQ_API_KEY` 또는 `XAI_API_KEY`가 필요합니다. 키를
채팅에 붙여 넣지 마세요([ocr-vlm.md](skills/hwp-parser/references/ocr-vlm.md)).

**내 컴퓨터 밖으로 나가는 것:** `--vlm`을 쓸 때를 빼면 없습니다. 변환, `--ocr`, `--pdf`는 모두
오프라인입니다(처음 `uv run`할 때만 고정된 패키지를 PyPI에서 내려받습니다). `--vlm`을 쓰면
본문은 빼고 내장 이미지만 고른 제공자 한 곳으로 보냅니다. 에이전트는 사용자가 요청할 때만
`--vlm`을 쓰고, 공개되지 않은 문서라면 먼저 확인을 받습니다.

문서: [SKILL.md](skills/hwp-parser/SKILL.md) ·
[출력 형식과 제한](skills/hwp-parser/references/format.md) ·
[OCR과 VLM](skills/hwp-parser/references/ocr-vlm.md) ·
[오류 코드](skills/hwp-parser/references/errors.md) (모두 영어)

**정확도:** 공개된 HWP 5 문서 세 개를 한컴독스에서 내보낸 PDF의 텍스트 레이어와 비교했습니다.
아래 표는 벤치마크가 영어로 자동 생성합니다. 측정 방법, 한계, 변환 예시, 재현 방법:
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

Google 포토에서 특정 인물·행사·연도의 사진과 동영상을 로컬 폴더(대상별·연도별 한 폴더, 기본
위치 `~/Pictures/google-photo/`)로 모은 뒤, 순위를 매긴 하이라이트 묶음(기본 사진 약 75장,
영상 8개)을 골라 줍니다. 사진은 Google이 제공하는 **Picker** 페이지에서 직접 고릅니다.
에이전트가 링크와 검색창에 입력할 말을 알려 주면(인물 이름을 넣으면 Google이 묶어 둔 얼굴
그룹이 나옵니다), 날짜별 전체 선택 상자를 체크하고 완료를 누르면 됩니다. 스킬은 고른 항목만
원본 해상도로 내려받습니다.

- `Google 포토에서 2026년 Mia 사진이랑 동영상 전부 모아줘.`
- `Google 포토에서 리스본 여행 사진 가져와줘. 2026-05-01부터 2026-05-10까지만.`
- `Mia 2026년 사진 중에서 하이라이트 영상용으로 베스트 골라줘.`

**처음 쓰기 전에:** Google Cloud에서 한 번, 10분쯤 걸리는 설정이 필요합니다. 프로젝트(결제
계정 불필요)를 만들고, Photos Picker API를 켜고, 본인을 테스트 사용자로 넣은 동의 화면과
데스크톱 앱 OAuth 클라이언트(Google 로그인 화면에서 스킬이 권한을 요청할 수 있게 해 주는
파일)를 만든 뒤 `auth`로 로그인합니다. 앱을 테스트 상태로 두면 7일마다 다시 로그인해야
합니다. 단계별 안내(영어): [setup.md](skills/google-photo/references/setup.md).

**내 컴퓨터 밖으로 나가는 것:** 원본 사진과 영상은 Google에서 내 디스크로만 옵니다. 다른
서비스나 원격 측정은 없고, 읽기 전용 Picker 권한만 요청합니다. 다만 고르는 단계에서 에이전트가
작은 썸네일 모음(타일당 최대 256 px)을 보기 때문에, 이 썸네일은 에이전트의 모델 제공자(예:
Claude Code라면 Anthropic)로 전달됩니다. 원본 파일은 열지 않습니다. 클라이언트 파일과 저장된
로그인 정보는 `~/.config/google-photo/`에만 있고 출력되지 않으니, 채팅에 붙여 넣지 마세요.
내 컴퓨터에서만 동작하며 SSH, 컨테이너, 화면 없는 Linux에서는 실행을 거부합니다.

문서: [SKILL.md](skills/google-photo/SKILL.md) ·
[설정](skills/google-photo/references/setup.md) ·
[선별 기준과 picks.json](skills/google-photo/references/curation.md) ·
[오류 코드](skills/google-photo/references/errors.md) (모두 영어)

### kipris-search

한국 공식 지식재산 데이터베이스인 [KIPRIS](https://www.kipris.or.kr/khome/main.do)에서 특허,
실용신안, 상표, 디자인을 검색하고, 실행한 검색식과 전체 건수, 확인한 번호·날짜·출원인·권리자·
법적 상태를 알려 줍니다. 출원번호, 공개번호, 등록번호를 구분하고, "0건"을 "그런 권리가 없다"로
해석하지 않으며, 등록 가능성이나 침해 여부에 대한 의견은 내지 않습니다.

- `KIPRIS에서 '커피' 상표 검색해줘`
- `삼성전자가 출원한 이차전지 특허 찾아줘.`
- `특허 출원 1020140061596 지금 상태가 어때?`

**처음 쓰기 전에:** 필요한 것은 없습니다. 에이전트에 있는 브라우저 도구로 공개 KIPRIS
웹사이트를 검색합니다. 원하면 [KIPRISPlus](https://plus.kipris.or.kr/)에서 API 키를
발급받고, 필요한 상품(특허·실용, 상표, 디자인)마다 따로 신청하세요. 상품마다 권한과 이용
기간이 따로 있습니다. 키는 직접 연 터미널에서
`uv run <스킬 폴더>/scripts/kipris_api.py configure`로 등록하세요(입력은 화면에 보이지 않고,
전체 경로는 에이전트에게 물어보면 됩니다). 채팅에는 붙여 넣지 마세요. 그러면 에이전트가
목록 검색에 API 도우미를 씁니다
([api.md](skills/kipris-search/references/api.md#registering-the-key), 영어).

**내 컴퓨터 밖으로 나가는 것:** API 도우미는 HTTPS로 `plus.kipris.or.kr`에만 접속해 키와 검색
조건을 보냅니다. 키는 `~/.config/kipris-search/`에 저장되고 출력에 나오지 않습니다. 브라우저
경로는 사람이 하듯 공개 KIPRIS 웹사이트를 방문하며, 로그인이나 CAPTCHA는 사용자에게 넘깁니다.

문서: [SKILL.md](skills/kipris-search/SKILL.md) ·
[API 도우미](skills/kipris-search/references/api.md) ·
[브라우저 검색](skills/kipris-search/references/browser-search.md) ·
[오류 코드](skills/kipris-search/references/errors.md) (모두 영어)

## 요구 사항

- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` 또는
  `brew install uv`). 처음 실행할 때 Python 3.11과 고정된 의존성을 알아서 받아 옵니다.
- hwp-parser: LibreOffice(`--pdf auto`에만 필요, 선택), `GROQ_API_KEY` / `XAI_API_KEY`
  (`--vlm`에만 필요, 선택).
- google-photo: Google 계정, 그리고 본인 데스크톱 OAuth 클라이언트가 있는 Google Cloud
  프로젝트(한 번만 설정, [설정](skills/google-photo/references/setup.md)). 썸네일 모음에
  동영상 장면을 넣으려면 `ffmpeg`(선택).
- kipris-search: `uv` 말고는 없음(표준 라이브러리만 사용). KIPRISPlus API 키는 선택.

macOS와 Python 3.11에서 테스트했습니다. Windows와 Linux는 아직 검증하지 않았습니다.

## 라이선스

MIT, [LICENSE](LICENSE) 참고. 서드파티 구성 요소(번들된 Tesseract 언어 데이터는 Apache-2.0,
pyhwp는 AGPL-3.0이며 번들하지 않고 실행 시 내려받음)는 [NOTICE](NOTICE)에 정리되어 있습니다.
벤치마크 샘플은 공개 문서이며 저작권은 각 발행 기관에 있습니다.
[bench/hwp-parser/samples/README.md](bench/hwp-parser/samples/README.md)를 참고하세요.
