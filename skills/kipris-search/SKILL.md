---
name: kipris-search
description: "Search KIPRIS, the official Korean IP database, for patents, utility models, trademarks and designs and confirm application, publication and registration numbers, applicants, rights holders, legal status and source documents; optional KIPRISPlus API helper for list searches. Use when the user asks for a KIPRIS (키프리스) lookup, a trademark name search, a prior-art search, or a specific Korean application or registration number."
---

# kipris-search

Looks up the requested rights in the official [KIPRIS](https://www.kipris.or.kr/khome/main.do)
service and reports reproducible search conditions together with the bibliographic data
actually confirmed. Answer in the user's language (often Korean); keep Korean search terms,
KIPRIS screen labels and official field names exactly as they appear.

## When to use

- The user wants Korean patents, utility models (실용신안), trademarks (상표) or designs
  (디자인) searched in KIPRIS: by keyword, brand name, applicant or number.
- A prior-art check, a trademark clearance pre-check, or the status of a given
  application, publication or registration number.
- Not for legal opinions: finding identical or similar rights is not a judgment on
  registrability or infringement (see [Reporting](#reporting)).

## Choosing the route

- If a local KIPRISPlus API key is configured (`status` says `"configured": true`), prefer
  the API helper for Korean list searches. If not, use the public KIPRIS website in a
  browser. Do not ask for a key first.
- Search the rights the request needs. `--right all` queries all three products
  (patent/utility, trademark, design). KIPRISPlus licenses each product separately: a right
  whose product the key is not licensed for fails on its own (`"ok": false` in `results`)
  while the others continue. Report that right as unverified and, if it matters, check it
  in the browser.
- Web search may be used to find official documentation. Dynamic result lists and detail
  pages must be confirmed in a browser. Never report a KIPRIS lookup as done from search
  engine snippets alone.
- Before operating a browser read
  [references/browser-search.md](references/browser-search.md). Use whatever browser tool
  the agent has and read its documentation first; follow the current tool docs and the
  actual screen.
- For API setup and searches read [references/api.md](references/api.md) and use
  `scripts/kipris_api.py`. `status` never prints the key and never uses an API call. The
  user registers the key themselves, with hidden input in their own local terminal. Never
  write the key anywhere except the protected local credential file: not in answers,
  outputs, repositories, logs or command arguments.
- Keep three things apart: a key issued and stored locally, a product the key may use, and
  a request that succeeded. The helper covers Korean list searches only. Full text, images,
  claims, current-holder checks and foreign searches need the browser, or an official API
  specification you have checked separately.

## Run

```sh
uv run <this skill's folder>/scripts/kipris_api.py status
uv run <this skill's folder>/scripts/kipris_api.py search --right patent-utility|patent|utility|trademark|design|all [--query TEXT] [--applicant NAME] [--application-number N] [--registration-number N] [--page P] [--size S]
```

In Claude Code the skill folder is `${CLAUDE_SKILL_DIR}`:

```sh
uv run "${CLAUDE_SKILL_DIR}/scripts/kipris_api.py" search --right trademark --query '커피'
```

`configure` is run by the user, not the agent (see [references/api.md](references/api.md#registering-the-key)).
Requires [`uv`](https://docs.astral.sh/uv/); the helper uses the Python standard library
only. `status` and `configure` exit 0 with JSON on stdout. `search` exits 0 when every
requested right succeeded, and 1 (`"status":"partial"`) when at least one right failed:
read each entry of `results`. Any whole-command failure exits 2 with the last stderr line
`{"status":"failed","error":CODE,"message":...}`: look the code up in
[references/errors.md](references/errors.md) and tell the user the remedy.

## Scoping the search

Settle the right type, search target, country, period and status conditions from the
request. Fill missing conditions with reasonable defaults and state them in the answer.
Without a country, search Korean (domestic) records.

- With a number, tell application, publication and registration numbers apart and search
  the matching number field first. Keep the original number. If separators must be
  removed, do so only in the search input; never drop leading zeros or document-kind codes.
- A brand name points to trademarks, an invention or technology to patents/utility models,
  a product's appearance to designs.
- If the right type is unclear, run separate preliminary searches per tab. Never add up
  counts of different rights and present them as one search result.
- Ask one key question only when the search cannot be run at all without it. If a
  trademark name alone is enough to start, search first, then narrow by goods and services.
- For a broad search without a requested count, summarise at most 10 relevant candidates
  first. Keep the total count and the number actually reviewed apart. This limit does not
  apply when an exhaustive search is requested.

## Running the search

1. Choose the right type and domestic or foreign scope. For a number, use the matching
   number field in the advanced search.
2. Search the keyword exactly as given first. Then expand as the purpose requires: Korean
   and English forms, spacing variants, abbreviations and full names, synonyms. Record
   every query and filter run.
3. For compound searches, check the operators in the current search help or combine the
   advanced-search fields. Do not copy query syntax from other sites or APIs.
4. Confirm that the real result list and count have loaded. After changing a tab, country,
   filter or sort order, confirm the change was applied.
5. Open the detail view of each main candidate you will report and check its number, title
   and applicant. Distinguish a laid-open publication (출원공개) from a registration
   gazette (등록공보).
6. Record the displayed legal status exactly. When the current state of the right is the
   point of the question, also check the registration particulars and the prosecution
   history. Leave anything you could not access as unverified.

### Trademarks

Search the identical spelling first, then add Korean and English spellings and
pronunciation variants. Check the Nice class, the designated goods and services, and the
similar-group codes (유사군코드) together. Take classes and codes from the current screen or
official classification material; never present a guessed value as confirmed.

Keep the applicant and the current rights holder apart. When the mark's image matters, look
at the actual image; never judge the similarity of a figurative mark without seeing it. The
same name can come with different goods, services and status, so list each record
separately.

### Patents and utility models

Break the invention into its key elements and search the fields needed: title, abstract,
claims. Use IPC/CPC codes confirmed on relevant documents to find further candidates; never
invent classification codes.

Screen relevance from abstracts, but when explaining a technical correspondence, read the
actual claims and description. Never summarise claims you have not read. Keep priority
date, filing date and publication date apart. For a prior-art search with a cut-off date,
check the publication date and whether the document was published at all; never include a
document on its priority date alone.

Mark documents of the same family or application as related, but never drop their
different numbers. Count unique inventions only when asked, and then state the grouping
rule.

### Designs

Find candidates by article name and classification, then look at the actual drawings and
images. Never conclude that appearances are identical or similar from text results alone.
Record relationships such as related designs (관련디자인) when they are shown.

## Reporting

Start with a short conclusion, then give the date and time of the search with its time
zone, the right type and country, the queries, filters and sort order actually run, the
total result count and how many were reviewed. For a "latest" request, confirm which date
the sort uses and that it is descending.

For several records make a table of the confirmed items below; a few number lookups can be
answered in prose.

- Title, right type, application number, publication or registration number.
- Applicant, current rights holder, filing date, publication or registration date.
- The legal status as displayed, the reason for relevance, the source link.
- As needed: for trademarks the class, main designated goods/services and similar-group
  codes; for patents IPC/CPC and the basis in the claims you read.

Write "unverified" (`미확인`) for a value you could not confirm and "not shown"
(`표시 없음`) for one that is empty in the source, in the user's language. Never fill in a
title, number or status by guessing. Use only an official detail URL or DOI obtained from
the actual screen. If none can be obtained, give the application number, the KIPRIS start
page and the conditions to reproduce the search, and say that no individual source link
was secured.

Keep finding identical or similar candidates apart from any judgment on registrability or
infringement. A past registration decision is not the same fact as a currently valid right.
Zero results means "no results for these conditions" (`해당 조건에서 조회된 결과 없음`):
never turn it into "no such right exists" or "you can file or use it".

## When access fails

Never read an empty search form, a loading screen, a server error or a login prompt as
zero results. Look at the new screen before retrying, and instead of repeating the same
failure, tell the user which route failed and what was confirmed.

Steps that need a login or a CAPTCHA follow the browser tool's confirmation and hand-off
rules: hand them to the user. Never bypass a restriction. Continue with whatever the public
search allows. If no browser is available, find candidates through a web search of official
sources, but state that the direct KIPRIS lookup was not completed (`KIPRIS 직접 조회 미완료`).

A lookup request alone never justifies a sign-up, a paid API application, or registering
search-query mailings or alerts.

## References

- [references/api.md](references/api.md): KIPRISPlus key setup, the helper's commands, output fields and implementation scope.
- [references/browser-search.md](references/browser-search.md): the public KIPRIS website flow, detail panel and citable links.
- [references/errors.md](references/errors.md): every helper error code, per-right failures and their remedies.
