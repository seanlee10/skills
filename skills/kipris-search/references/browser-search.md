# KIPRIS in the browser

The flow below was checked on the official site on 2026-10-15. The screen language and UI
can change, so the current screen comes first. Do not assemble URLs from the old `kportal`
paths or from URL parameters you have not observed.

## Official entry points

- [KIPRIS home](https://www.kipris.or.kr/khome/main.do).
- [KIPRIS search screen](https://www.kipris.or.kr/khome/search/searchResult.do). The search
  terms may travel in the session, so sharing this address alone may not reproduce the
  same result.
- [KIPRISPlus](https://plus.kipris.or.kr/). Only for checking API products and permissions.
- [KIPRISPlus official developer guide](https://plus.kipris.or.kr/portal/bbs/view.do?bbsId=B0000001&nttId=1060).
  It is the 2024 guide; check the latest product specification before calling an API.

## Searching from the home page

Use whatever browser tool the agent has, and read its documentation first. Operate the
controls taken from the current page state and read the new state after each action. Never
reuse element references from an earlier run.

1. Type the keyword into the home search box and press the search button. When checked, the
   home input's DOM ID was `inputQuery`.
2. On the search screen, check the selected right tab and country. The result screen's
   search input had the ID `queryText`.
3. Confirm that the loaded count and result titles have actually appeared. The result count
   area had the ID `resultTotal`.
4. Select the tab that fits the request: 특허·실용신안 (patent/utility), 디자인 (design) or
   상표 (trademark). The initial selection may be patent/utility.
5. For numbers, applicants and periods choose the matching field in the advanced search
   (상세검색). Application number (출원번호), registration number (등록번호) and
   publication number (공개번호) are separate fields. Title (명칭), abstract (요약), claims
   (청구범위), IPC/CPC, applicant (출원인) and registered holder (등록권자) fields are
   also offered.

If the screen is in English, use the names currently shown, such as `Patent·Utility`,
`Design`, `Trademark`, `Advanced Search`, `Application No.`, `Registration No.`,
`Applicant`, `Rights Holder`. You can search without changing the language setting.

When `Search within Results` / `결과 내 재검색` is selected, the previous search scope is
kept. For an independent new search check this state and any filters left over. The count
for domestic records and the count on a right tab that includes foreign records can differ,
so use the result count of the scope currently selected.

## Checking the details

Clicking a title may open a detail panel on the same screen instead of a new page. When
checked, the panel ID was `mainResultDetail`. The details can be read even though the URL
does not change.

Check title, numbers, dates, applicant and legal status in the bibliographic data
(서지정보). The current rights holder may be a separate item. Open registration particulars
(등록사항), prosecution history (행정처리), claims (청구항) and the full gazette (공보전문)
when needed. Never write that you reviewed the full text after reading only the abstract in
the list.

A source link can be obtained from the detail screen's new-window or DOI function. A button
whose `href` is `#` or `javascript:` is not a citable document address. Use the real
address of the new window or the copied DOI. Before copying a DOI, never read or print what
is already on the clipboard. If no address can be obtained, give the number and the
conditions to reproduce the search.

Downloading the list, saving queries and My Folder (마이폴더) may be member features. Do not
add them as required steps of an ordinary lookup. Unless a separate file is requested, a
table in the answer is enough.

## A public lookup actually performed

From the home page `휴대폰케이스` (phone case) was searched, and in the domestic
patent/utility results `휴대폰케이스용 융착기` was opened. The details showed application
number `1020140061596`, registration number `1014426360000`, legal status `등록`
(registered) and the claims. This verifies the browser flow; it is not test data that fixes
any future status or result count.

When re-verifying, check that a keyword search loads the list and that the number in the
details matches the selected candidate. Trademarks and designs, number-specific advanced
searches, API calls and downloads were not exercised in this run. When you use them,
confirm them against the actual screen or response.
