# Error and warning codes

On failure `gphoto.py` exits 2 and the last stderr line is
`{"status":"failed","error":CODE,"message":...}`. Messages are fixed English text; they never
contain paths, tokens, URLs or personal data. Warnings never fail a run; they are listed in
the `warnings` array of the success summary.

Files are written atomically, so a failure never leaves a half-written manifest, sheet or
selection. Items downloaded before a `fetch` failure stay in the manifest and are counted as
`already_present` next time.

## Setup and environment

| Code | Meaning | What to do |
| --- | --- | --- |
| `USAGE_ERROR` | Invalid command-line arguments (unknown flag, missing `--subject` / `--year`, bad number, negative `--wait`). | Check the command against `gphoto.py <command> --help` or the Run section of SKILL.md. |
| `REMOTE_ENVIRONMENT_REFUSED` | The machine looks remote: an SSH session, a container, or Linux without a display. Nothing was done. | Run the skill on the user's own computer, in a local terminal or local agent session. Do not try to work around it. |
| `CLIENT_SECRET_MISSING` | No OAuth client file at `~/.config/google-photo/client_secret.json` (or at `GOOGLE_PHOTO_CLIENT_SECRET`). | Do the one-time setup in [setup.md](setup.md), steps 1–5 (or 3–5 if the project already exists). |
| `CLIENT_SECRET_INVALID` | The file is not a Google **Desktop app** client JSON (for example a "Web application" client, or an edited file). | Create a Desktop app client and download its JSON again ([setup.md](setup.md), step 4). Never paste the file into the chat. |

## Sign-in

| Code | Meaning | What to do |
| --- | --- | --- |
| `AUTH_REQUIRED` | No saved sign-in, or it expired or was revoked. Apps in Testing get refresh tokens that expire after 7 days. | Run `auth` and sign in again, then rerun the command. |
| `AUTH_DENIED` | Sign-in was cancelled, or the Google Photos permission box was unticked. | Run `auth` again; sign in with the photo account (a test user) and grant the Google Photos permission. "Access blocked" means the account is not a test user ([setup.md](setup.md), step 3). |
| `AUTH_TIMEOUT` | Sign-in was not finished in the browser within 5 minutes. | Run `auth` again, in the background. If no browser opened, read the `{"notice":...,"url":...}` stderr line while that `auth` is still running and give the user its URL; a URL from an earlier `auth` run is never valid. |
| `AUTH_STATE_MISMATCH` | A sign-in redirect arrived that did not belong to this attempt (an old tab, a second `auth`). It was ignored. | Close old sign-in tabs and run `auth` once. |

## Google and the network

| Code | Meaning | What to do |
| --- | --- | --- |
| `NETWORK_ERROR` | Google could not be reached (offline, DNS, timeout); each download is tried up to 3 times first. | Check the connection and rerun. For `fetch`: a failure while waiting for Done or while listing keeps the pending session, so run `fetch` again; a failure while downloading closes it, so run `start` and pick again (already downloaded items are kept and counted as `already_present`). |
| `BAD_RESPONSE` | Google answered with something the skill cannot use (malformed JSON, a redirect to a non-Google host, an empty file). | Rerun once; if it repeats, start a new session. |
| `GOOGLE_HTTP_ERROR` | Google rejected a request. The actual code carries the HTTP status: `GOOGLE_HTTP_<status>`, e.g. `GOOGLE_HTTP_403`; all share this message. | `GOOGLE_HTTP_403`: the Photos Picker API is probably not enabled in the project ([setup.md](setup.md), step 2), or the permission was not granted (run `auth`). `GOOGLE_HTTP_429`: quota; wait a few minutes. `GOOGLE_HTTP_5xx`: Google trouble; retry later. `GOOGLE_HTTP_400` / `GOOGLE_HTTP_401` from `auth` or any command's token refresh: the client file is wrong or the client was deleted; download it again. |
| `SESSION_EXPIRED` | The picking session expired (see `expires` in the `start` output) or was closed. The pending session is forgotten. | Run `start` again and send the user the new link. |
| `BASEURL_EXPIRED` | A picked item's download link expired (Google's links last about an hour) and refreshing it failed. As a failure it is rare; usually it appears as a warning (below). | Run another `start` / `fetch` pair and pick again; items already downloaded are skipped. |

## Library folder

| Code | Meaning | What to do |
| --- | --- | --- |
| `UNSAFE_SUBJECT` | `--subject` cannot be a folder name: empty, `.` or `..`, contains `/` or `\` or a control character, or over 100 characters. | Use a short plain name, e.g. `Mia` or `Wedding`. |
| `UNKNOWN_TIME_ZONE` | `--tz` is not an IANA zone name. | Use a name like `Asia/Seoul`, `Europe/Berlin`, `America/New_York`, or leave `--tz` out to use the machine's zone. |
| `DATE_RANGE_OUTSIDE_YEAR` | `--from` / `--to` are not both inside `--year`, or `--from` is after `--to`. | Use dates within the year (`YYYY-MM-DD`). For a range across years run one session per year. |
| `MANIFEST_CORRUPT` | `<year>/manifest.json` cannot be read (edited by hand, damaged). Nothing was changed. | Restore the file from a backup, or move it aside (the media files stay; a new manifest would download them again under new names). Do not delete `media/`. |

## Pending sessions

| Code | Meaning | What to do |
| --- | --- | --- |
| `NO_PENDING_SESSION` | `fetch` found no pending session (none started, already fetched, expired, or a wrong `--session`). | Run `start` first. |
| `AMBIGUOUS_PENDING_SESSION` | More than one session is pending. | Run `fetch --session <ID>` with the `session` value from the matching `start` output. |
| `PENDING_SESSION_CORRUPT` | The saved state of the pending session (in `~/.config/google-photo/sessions/`) cannot be read. | Run `start` again. |

## Curation and selection

| Code | Meaning | What to do |
| --- | --- | --- |
| `NOTHING_TO_CURATE` | `curate`: the year folder has no manifest, or none of its files are on disk. `select`: no `curation/candidates.json` yet. | Run `fetch` first (check `--subject`, `--year`, `--out-root`), then `curate`, then `select`. |
| `CURATION_DIR_UNSAFE` | `<year>/curation/` or its `sheets/` is a symbolic link or a file. Nothing was written. | Ask the user to move it aside, then rerun. |
| `CANDIDATES_CORRUPT` | `curation/candidates.json` cannot be read. | Run `curate` again, then rewrite `picks.json` from the new sheets. |
| `INVALID_PICKS` | `picks.json` is missing or invalid: no `items` list, too many entries, an unknown or repeated `ref`, an empty or over-200-character `reason`, or a picked file no longer in `media/`. Nothing was changed. | Fix the file ([curation.md](curation.md#the-picks-file)) and rerun `select`. If `curate` ran again since, refs changed: rewrite it from the new sheets. |
| `PICKS_OUTDATED` | `select`: the picks file is older than `curation/candidates.json`, so `curate` ran after it and its refs may now name other photos. Nothing was changed. | Read the new sheets and write `picks.json` again, then rerun `select`. |
| `SELECTED_DIR_UNSAFE` | `<year>/selected/` is a symbolic link or a file. Nothing was written. | Ask the user to move it aside, then rerun `select`. |

## Interruption

| Code | Meaning | What to do |
| --- | --- | --- |
| `INTERRUPTED` | The command was stopped with Ctrl-C (a keyboard interrupt) before it finished. Files are written atomically, so nothing is half-written. A `fetch` interrupted while waiting for Done or while listing keeps its pending session; one interrupted while downloading closes it. | Rerun the command. For `fetch`: interrupted before downloading began, run `fetch` again; interrupted while downloading, run `start` and pick again (items already downloaded are kept and counted as `already_present`). |

## Unexpected errors

Any other code (for example `OSError` or `PermissionError`) is the name of an unexpected
Python exception, with the message `Unexpected internal error.`. Common causes: a full
disk, no write permission on the output folder, or a file being changed during the run.
Check free space and permissions of `--out-root` (default `~/Pictures/google-photo`) and
rerun.

## Warnings

Warnings appear in the summary's `warnings` list; the run still succeeded. `<file>` is the
original file name as Google reports it; `<ref>` a candidate ref.

| Warning | From | Meaning | What to do |
| --- | --- | --- | --- |
| `BASEURL_EXPIRED:<file>` | `fetch` | The item's download link expired even after a fresh listing; counted in `skipped.download_failed`. | Run another `start` / `fetch` pair and pick it again (or pick everything again: present items are skipped). |
| `NETWORK_ERROR:<file>`, `BAD_RESPONSE:<file>`, `GOOGLE_HTTP_<status>:<file>` | `fetch` | That item's download failed after retries; counted in `skipped.download_failed`. | As above; mention the count to the user. |
| `BAD_ITEM:<file>` | `fetch` | Google listed an item without an id; it cannot be downloaded. Counted in `skipped.download_failed`. | Usually nothing; if it matters, pick it again in a new session. |
| `THUMB_MISSING:<file>` | `fetch` | The original was downloaded but its small thumbnail was not. | Nothing: `curate` then analyses the original locally instead (formats Pillow cannot decode, such as HEIC, are then counted as `undecodable`). |
| `BROWSER_NOT_OPENED` | `start` | The picker link could not be opened in a browser automatically (no default browser, or opening it failed). The session was created and is pending. | Give the user `picker_uri` verbatim to open themselves; then run `fetch` as usual. |
| `SESSION_NOT_DELETED` | `fetch` | The downloads finished but closing the session at Google failed. | Nothing; Google expires it on its own. |
| `VIDEO_FRAMES_FAILED:<ref>` | `curate` | ffmpeg could not extract frames from that video; its tile shows Google's thumbnail (or is blank). | Judge the clip from that tile and its date, or leave it out. |
| `VIDEO_FRAMES_UNAVAILABLE` | `curate` | There are videos among the candidates but ffmpeg or ffprobe is not installed; video tiles show Google's thumbnail (or are blank) instead of four frames. | Judge clips from that tile and their dates; optionally ask the user to install ffmpeg (which includes ffprobe) and rerun `curate`. |
| `TILE_UNREADABLE:<ref>` | `curate` | The image for that tile could not be decoded; the tile is blank. | Leave it out unless the user asks for it. |
| `SELECTED_FILE_KEPT:<name>` | `select` | A file the previous `select` placed in `selected/` was edited, replaced or turned into a link since; it was kept and its name not reused (a new file that needs the name gets `_2`). | Nothing; tell the user their edited file was kept. It also triggers `SELECTED_FOLDER_HAS_OTHER_FILES`. |
| `SELECTED_FOLDER_HAS_OTHER_FILES` | `select` | `selected/` contains files the skill did not put there (often a harmless macOS `.DS_Store`). They were kept. | Nothing; mention it only if the files are not `.DS_Store`. |

Not warnings, but counted in the `fetch` summary: `skipped.video_not_ready` (Google is still
processing the video; pick it again later) and `filtered_out` by reason (`out_of_range`,
`type`, `camera`, `orientation`, `resolution`). Counted in the `curate` summary under
`dropped`: `invalid_entry`, `missing`, `undecodable`, `near_duplicate`, `blurry`, `dark`,
`month_cap`, `video_cap`.
