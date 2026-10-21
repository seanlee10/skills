# Benchmark samples

Three public Korean documents used to benchmark `hwp-parser`.

| Sample | Original filename |
| --- | --- |
| `prospectus.*` | `투자설명서(자본화금융비용포함v2.hwp` |
| `pharma-disclosure.*` | `★제약바이오 기업 공시 모범사례('26.8월).hwp` |
| `youth-rfp.*` | `2024년 청년도전 성장 시상식 행사 제안요청서(0806).hwp` |

## Sources

- `prospectus.*`: a real-estate investment company's draft prospectus (투자설명서(안));
  the issuer is named in the document.
  Source URL: <https://www.kait.com/reits1/?mod=document&uid=4959&kboard_id=50>
- `pharma-disclosure.*`: a best-practice guide for disclosures by pharmaceutical and
  biotech companies in their business reports, with the August 2026 revisions
  (제약·바이오 기업 공시 모범사례), published on DART by the Financial Supervisory
  Service (금융감독원).
  Source URL: <https://dart.fss.or.kr/info/searchGuide02.do>
- `youth-rfp.*`: a request for proposals for the 2024 award ceremony of the youth
  challenge and youth growth programmes, issued by 고용노동부 (Ministry of Employment
  and Labor).
  Source URL: <https://www.moel.go.kr/news/notice/noticeView.do?bbs_seq=20240800369>

## Provenance and copyright

- These are public documents. Copyright remains with the issuing organisations; they are
  included here unmodified for evaluation purposes only.
- `*.hwp` is the original file as published.
- `*.pdf` was produced from the `.hwp` with Hancom Docs "Save as PDF".
- `*.llamaparse.md` is LlamaParse cloud output for the same document. It is a
  comparison baseline, not ground truth.
