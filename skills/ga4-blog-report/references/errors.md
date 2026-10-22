# Error codes

`ga4_report.py` exits 2 on any failure, with nothing on stdout and the last stderr line
`{"status":"failed","error":CODE,"message":...}`. Messages are fixed English text; they
never contain the key, an access token, a path or any part of a Google response. The script
never retries, and no error means zero traffic.

## Command line

| Code | Meaning | What to do |
| --- | --- | --- |
| `USAGE_ERROR` | Unknown command or flag, or a missing `--key` / `--property` for `configure`. | Check the command against the Run section of SKILL.md or `--help`. |
| `INVALID_DATE` | A date is not `YYYY-MM-DD`, `today`, `yesterday` or `NdaysAgo`, or `--start` is after `--end`. Nothing was sent. | Fix the dates. |
| `INVALID_PREFIX` | `--prefix` does not start with `/` or contains whitespace. Nothing was sent. | Use a path such as `/blog/`, or `/` for the whole site. |
| `INTERRUPTED` | The command was stopped with Ctrl-C. | Rerun it if still needed. |

## Configure

| Code | Meaning | What to do |
| --- | --- | --- |
| `KEY_SOURCE_MISSING` | The `--key` path does not exist or is not a regular file. Nothing was saved. | Check the path of the downloaded JSON key. |
| `KEY_INVALID` | The file is not a service account JSON key (for example an OAuth client file, or a key whose `token_uri` is not Google's). Nothing was saved. | Download a new JSON key for the service account ([setup.md](setup.md#2-create-a-service-account-and-a-json-key)). |
| `PROPERTY_ID_INVALID` | The property ID is not digits only. Nothing was saved. | Copy the Property ID from **Admin → Property details** ([setup.md](setup.md#4-find-the-property-id)). |
| `MEASUREMENT_ID_GIVEN` | A measurement ID (`G-…`) was given instead of the property ID. Nothing was saved. | Use the numeric Property ID. |
| `CONFIG_DIR_UNSAFE` | `~/.config/ga4-blog-report` is a symbolic link or a file. | Replace it with a regular folder, then run `configure`. |
| `LOCAL_SETUP_FAILED` | The key or settings could not be written. | Check that `~/.config` is writable and run `configure` again. |

## Stored settings

| Code | Meaning | What to do |
| --- | --- | --- |
| `NOT_CONFIGURED` | No stored key or property ID. Nothing was sent. | Walk the user through [setup.md](setup.md), then run `configure`. |
| `KEY_FILE_UNSAFE` | A stored file is not a regular file owned by the user with mode 600, or is a symbolic link. | Run `configure` again, which rewrites both files with mode 600. Never `cat` the key. |
| `CONFIG_INVALID` | The stored key or settings are unreadable, or the private key cannot be loaded. | Run `configure` again with a fresh key. |

`status` never fails on these: it reports `"configured": false` instead. Use a report's
error code to learn why.

## Google

| Code | Meaning | What to do |
| --- | --- | --- |
| `NETWORK_ERROR` | `oauth2.googleapis.com` or `analyticsdata.googleapis.com` could not be reached, or timed out. | Check the connection. If the agent's sandbox blocks these hosts, tell the user and have them run the command in their own terminal. |
| `AUTH_REJECTED` | Google rejected the signed key (`invalid_grant`): the key was deleted or disabled, the service account was deleted, or the system clock is off by minutes. | Check the clock; otherwise create a new key and run `configure` again. |
| `AUTH_FAILED` | Any other failure to obtain or use an access token. | Run the report again once; if it persists, create a new key. |
| `API_DISABLED` | The Google Analytics Data API is not enabled in the service account's project (or was enabled only minutes ago). | Enable it in that project ([setup.md](setup.md#1-enable-the-google-analytics-data-api)) and wait a few minutes. |
| `PROPERTY_ACCESS_DENIED` | The service account is not a user of the property, or the property ID is wrong. | Add the service account's email (from `status`) as Viewer ([setup.md](setup.md#3-give-the-service-account-read-access-in-ga4)) and check the ID. |
| `QUOTA_EXHAUSTED` | The property's Data API quota is used up (HTTP 429). | Wait (hourly quotas reset within the hour, daily ones the next day) and use a shorter period. |
| `REQUEST_INVALID` | The Data API rejected the request (HTTP 400), for example a date before the property was created. | Adjust the dates. |
| `GA4_HTTP_ERROR` | Any other HTTP error from the Data API. | Try again later. |
| `RESPONSE_TOO_LARGE` | A response exceeded 32 MiB. | Use a shorter period or a narrower prefix. |
| `RESPONSE_MALFORMED` | A response was not the expected JSON. | Try again later; never report it as zero traffic. |

## Output

| Code | Meaning | What to do |
| --- | --- | --- |
| `OUTPUT_EXISTS` | The `--out` file exists and `--force` was not given. Nothing was sent. | Choose another `--out`, or pass `--force` if replacing it is intended. |
| `OUTPUT_UNWRITABLE` | The CSV could not be written. | Choose a writable folder. |
