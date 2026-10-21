# Error codes

`kipris_api.py` reports errors in two ways. Messages are fixed English text; they never
contain the key, a URL, a path or any part of a KIPRIS response.

- **Whole-command failure** (exit 2): nothing useful was produced. The last stderr line is
  `{"status":"failed","error":CODE,"message":...}`, and stdout is empty.
- **Per-right failure** (`search` only, exit 1): stdout carries the normal JSON with
  `"status":"partial"` and `"ok":false`; each failed entry of `results` is
  `{"ok":false,"right":...,"error":CODE,"message":...}` and has no `total` or `records`.
  Entries with `"ok":true` are valid results: report them, say which rights failed, and never
  call the search complete. `partial` is used whenever at least one right failed, also when
  every requested right failed.

No error is ever zero results. Only an entry with `"ok":true` and `"total":0` means "no
results for these conditions". The helper never retries; rerunning the same command spends
another call.

## Command line and local setup (exit 2)

| Code | Meaning | What to do |
| --- | --- | --- |
| `USAGE_ERROR` | Invalid arguments: unknown command or flag, a `--right` value outside the choices, a non-integer `--page` / `--size`. | Check the command against `kipris_api.py search --help` or the Run section of SKILL.md. |
| `INVALID_SEARCH_ARGUMENTS` | No non-blank search condition, `--page` below 1, or `--size` outside 1–500. Nothing was sent. | Give at least one of `--query`, `--applicant`, `--application-number`, `--registration-number`, and valid paging. |
| `INTERRUPTED` | The command was stopped with Ctrl-C. | Rerun it if still needed. |
| `CONFIGURE_NEEDS_TTY` | `configure` was run without an interactive terminal (for example by the agent). Nothing was saved. | The user runs `configure` in a terminal they opened themselves. Never ask for the key in the chat. |
| `HIDDEN_INPUT_UNAVAILABLE` | The terminal cannot hide typed input, so the key was not read. | Run `configure` in a normal local terminal. |
| `KEY_INPUT_INVALID` | The typed key was empty, contained whitespace or was over 4096 characters. Nothing was saved. | Run `configure` again and paste the key exactly as issued. |
| `KEY_DIR_UNSAFE` | `~/.config/kipris-search` is a symbolic link. Nothing was saved. | The user replaces it with a regular folder, then runs `configure`. |
| `LOCAL_SETUP_FAILED` | The local key setup or input failed (end of input, a file-system or encoding error). | Check that `~/.config` is writable and run `configure` again. |
| `KEY_NOT_CONFIGURED` | No key file. Nothing was sent. | Use the browser route ([browser-search.md](browser-search.md)), or the user registers a key ([api.md](api.md#registering-the-key)). |
| `KEY_FILE_UNREADABLE` | The key file could not be opened; a symbolic link is refused. | The user removes the link or fixes the file and runs `configure` again. |
| `KEY_FILE_UNSAFE` | The key file is not a regular file owned by the user with mode 600 (for example readable by others). | The user runs `configure` again, which rewrites it with mode 600, or `chmod 600` it. Never `cat` the file. |
| `KEY_INVALID` | The stored key is empty, contains whitespace or is too long. | The user runs `configure` again. |

`status` never fails on a key problem: it reports `"configured": false` instead. Use a
search's error code to learn why.

## Per-right failures (inside `results`, exit 1)

| Code | Meaning | What to do |
| --- | --- | --- |
| `KIPRIS_NETWORK_ERROR` | KIPRIS could not be reached, or 30 s passed. Not retried. | Report the right as unverified. Retry once later, or use the browser. |
| `KIPRIS_HTTP_ERROR` | KIPRIS answered with an HTTP error. The actual code carries the status: `KIPRIS_HTTP_<status>`, e.g. `KIPRIS_HTTP_403`; all share this message. A redirect is never followed and also ends here (`KIPRIS_HTTP_301` / `302`). | 4xx: check the key and the product permission at KIPRISPlus. 5xx: KIPRIS trouble; retry later or use the browser. |
| `RESPONSE_TOO_LARGE` | The response exceeded 8 MiB. | Request a smaller `--size`. |
| `RESPONSE_DTD_OR_ENTITY_FORBIDDEN` | The response declares a DTD or XML entities; rejected for safety. | Report the right as unverified; use the browser. |
| `RESPONSE_MALFORMED` | Not a KIPRIS XML response (for example an HTML error page). | Not zero results. Retry later or use the browser. |
| `KIPRIS_API_ERROR` | KIPRIS returned an API result code other than `00`. The actual code carries it: `KIPRIS_API_<2-digit code>`, e.g. `KIPRIS_API_30`; a missing or non-numeric result code stays `KIPRIS_API_ERROR`. All share this message. | Usually the key, the product permission or its period, or the call limit. Check the result code in the official KIPRISPlus specification and tell the user; never read it as zero results. |
| `KIPRIS_REQUEST_FAILED` | The response says `successYN` = `N`. | Report the right as unverified. |
| `RESPONSE_COUNT_MISSING` | The response has no total count or page information. | Not zero results; report the right as unverified. |
| `RESPONSE_PAGE_MISMATCH` | The counts or page in the response do not match the request (another page, more items than the page size or the total). | Report the right as unverified; do not use those records. |
| `RESPONSE_ITEMS_MISSING` | The response has no item list, or none while the total says there should be some. | Not zero results; report the right as unverified. |
| `CREDENTIAL_ECHOED` | The response contained the key, so its results were withheld. | Report the right as unverified. Do not rerun repeatedly; tell the user. |

## Unexpected errors

Any other code (for example `ValueError`) is the name of an unexpected Python exception,
with the message `Unexpected internal error.` (exit 2). Report it as a bug with the code and
the command flags, never with the key.
