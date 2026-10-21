# KIPRISPlus API helper

`scripts/kipris_api.py` (Python standard library only, run with `uv run`) searches Korean
patent/utility-model, trademark and design lists through KIPRISPlus. Key setup and calls go
through this helper so the credential and the request URL never appear in tool output.

## Registering the key

1. The user gets a KIPRISPlus API key at [KIPRISPlus](https://plus.kipris.or.kr/) and
   applies there for each product they need (patent/utility, trademark, design). Each
   product has its own permission and period. Do not apply for paid products or alerts on
   the user's behalf.
2. Ask the user to run this in a local terminal they opened themselves. Never ask them to
   paste the key into the chat, a tool argument or a shell command. The agent never runs
   `configure` and never types the key for them.

```sh
uv run <this skill's folder>/scripts/kipris_api.py configure
```

Give the user this command with the resolved absolute path of `kipris_api.py` in place of
`<this skill's folder>` (in Claude Code, the expanded value of `${CLAUDE_SKILL_DIR}`), so
they can paste it into their terminal as is; the placeholder itself does not run.

The input is hidden. The key is stored in plain text in `~/.config/kipris-search/api-key`
with file mode 600 in a folder of mode 700: a file private to the user, outside the
repository and the skill folder. `configure` refuses to run without an interactive
terminal, refuses a terminal that cannot hide input, and refuses a symlinked key folder.
If the user needs the key stored encrypted in the OS keychain instead, do not register it
with this file method; change the storage to meet that requirement.

Running `configure` again replaces the stored key. It does not call the API, so it does not
check the key or any product permission.

Check the local setup with `status`. Look only at `configured`; never `cat` the key file
and never print the environment.

```sh
uv run <this skill's folder>/scripts/kipris_api.py status
```

```json
{"status": "ok", "configured": true, "remote_validation": "not_performed", "key_file": "~/.config/kipris-search/api-key"}
```

`status` reads and validates the key file (regular file, owned by the user, mode 600, not a
symlink) but never prints the key and never touches the network.

## List searches

```sh
uv run <this skill's folder>/scripts/kipris_api.py search --right trademark --query '커피'
uv run <this skill's folder>/scripts/kipris_api.py search --right patent-utility --query '이차전지' --size 10
uv run <this skill's folder>/scripts/kipris_api.py search --right design --query '의자'
uv run <this skill's folder>/scripts/kipris_api.py search --right all --applicant '삼성전자'
uv run <this skill's folder>/scripts/kipris_api.py search --right patent --application-number 1020140061596
```

`--right` is one of `patent-utility`, `patent`, `utility`, `trademark`, `design`, `all`;
the CLI's choices are authoritative. `all` sends one request each to patent/utility,
trademark and design: three requests in total. Totals stay per right. The keyword
(`--query`) searches free text for patents, the trademark name for trademarks and the
article name for designs: the same keyword does not mean the same search scope.

`--query`, `--applicant`, `--application-number` and `--registration-number` can be
combined; at least one is required. Numbers are passed with their leading zeros intact;
check the number format the API expects against the official specification. This command
filters a list by the given number; it is not a bibliographic detail lookup.

The default is page 1 with 10 records. `--page` is 1 or more, `--size` 1 to 500. One command
requests exactly one page: no automatic retry, no next page, no detail call. When an
exhaustive search is requested, check `has_more` and the page information in the response
and request the next page explicitly. If the same page or content comes back again, stop
and report that the exhaustive collection is incomplete.

## Reading the result

stdout carries one JSON object with top-level `status` (`ok` or `partial`), `ok` and the
per-right `results` list. Each successful entry has `ok: true`, `right`, `total`,
`returned`, `page`, `page_size`, `has_more`, `records`, `filters` and `retrieved_at`. The
time is UTC; tell the user the time zone or convert it to their local time.

`records` normalises common fields: title, numbers, dates, applicant, status. Patents also
give abstract and IPC, trademarks class and registered owner (`owner`), designs class and
creator (`inventor`). A tag missing from the API response is `null`; an empty tag is an
empty string. Repeated tags are kept as an array. The holder value in a list does not
verify the currently valid rights holder: never write that it does. Never cite an image URL
as the document's detail link.

Read counts and lists only from entries with `ok: true`. An entry with `ok: false` carries
`error` (a code) and `message` (fixed text) and has no `total` or `records`. When some
products fail, keep the results of the rights that succeeded, but never say the whole
search is complete. A search with any failed right exits 1 with `"status": "partial"`, even
when every right failed: decide from `ok` and from each entry of `results`, never from
`partial` alone. Never turn an HTTP error, an API error or a permission or call
limit problem into zero results. Codes: [errors.md](errors.md).

For a first key check, run one small list search only. Check all three services with `all`
only when the user wants to confirm their permission for every product. Never apply for a
paid product or an alert just because a key exists.

## Official specification and implementation scope

On 2026-10-15 the **항목별검색 > 전체검색** (item search > full search) specification and the
official sample responses were checked for these products. Some plain word searches are
marked as due for retirement, so the helper uses `getAdvancedSearch`.

- [Patent/utility laid-open gazette (특허·실용 공개공보)](https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do).
- [Design gazette (디자인 공보)](https://plus.kipris.or.kr/portal/data/service/DBII_000000000000008/view.do).
- [Trademark application bulletin (상표 출원 속보)](https://plus.kipris.or.kr/portal/data/service/DBII_000000000000012/view.do).

Requests go only to the official host `plus.kipris.or.kr` over HTTPS, with no redirects
followed, no proxies, a 30 s timeout and an 8 MiB response cap; responses declaring a DTD or
entities are rejected. The authentication parameter is this API family's `ServiceKey`; do
not mix it up with `accessKey` of the other `/openapi/rest/` family. `SERVICES` inside the
helper is the single definition of service names, input/output fields and default flags.
It keeps the official spellings, such as `patUtiModInfoSearchSevice` and the design flag
`cancle`. If the response contains the key, the helper withholds that right's results
(`CREDENTIAL_ECHOED`).

The trademark status, trademark-type and mark-composition flags each need at least one
`true` per group; a general search sets every flag to `true`. The helper does not yet expose
status, class, period, sort or goods-scope filters. A search that needs such a restriction
either extends the helper after checking the official specification, or uses the browser's
advanced search; report the conditions actually applied.

Automated tests, from a clone of the repository:

```sh
uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q -p no:cacheprovider skills/kipris-search/tests
```

The tests use synthetic responses shaped like the official sample XML, patch the transport
and never touch the network or the real `~/.config`. Remote authentication, product
permission and the shape of current live responses must be verified separately, after the
user has registered a real key.
