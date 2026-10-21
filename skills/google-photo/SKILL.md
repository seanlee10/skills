---
name: google-photo
description: "Collect photos and videos from Google Photos with the official Google Photos Picker API: the user searches and selects in Google's own picker, the skill downloads the originals into a local folder per subject and year with a manifest, then pre-filters them locally and lets the agent curate a ranked highlight set from small contact sheets. Use when the user wants to collect, download, filter or curate photos/videos of a person, event or year from Google Photos."
---

# google-photo

Pulls photos and videos out of Google Photos into a local folder, one folder per subject
per year (e.g. `~/Pictures/google-photo/Mia/2026/`), and curates them down to a ranked
highlight set (about 75 photos and 8 clips by default, enough for a 2–3 minute video).

Google no longer lets apps read a library directly. The only way in is the **Picker**: the
skill creates a picking session, the user opens Google's own picker page, searches (a
person's name, a place, "birthday") and selects, then presses Done. The skill downloads
exactly what was selected. The skill never sees who is in a photo: the people filter is
the user's search in the picker. The API returns no location, people or description.

## When to use

- The user wants to collect, download, back up, filter or curate photos/videos of a
  person, event or year from their Google Photos.
- The user wants a "best of the year" set chosen for them (curation).
- **Not** for remote machines: the skill runs only on the user's own computer, where their
  browser and files are. Over SSH, in a container or on headless Linux every command fails
  with `REMOTE_ENVIRONMENT_REFUSED`.
- **Not** for unattended or scheduled runs: a human must select in the picker every time.
- Not for uploading, editing, deleting, sharing or making albums in Google Photos.

## Run

```sh
uv run <this skill's folder>/scripts/gphoto.py check
uv run <this skill's folder>/scripts/gphoto.py auth
uv run <this skill's folder>/scripts/gphoto.py start --subject NAME --year YYYY [--search TEXT] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--type photo|video|all] [--camera TEXT] [--orientation portrait|landscape] [--min-side PX] [--tz ZONE] [--out-root DIR] [--no-browser]
uv run <this skill's folder>/scripts/gphoto.py fetch [--session ID] [--wait SECONDS]
uv run <this skill's folder>/scripts/gphoto.py curate --subject NAME --year YYYY [--target N] [--video-target N] [--out-root DIR]
uv run <this skill's folder>/scripts/gphoto.py select --subject NAME --year YYYY [--picks FILE] [--out-root DIR]
```

In Claude Code the skill folder is `${CLAUDE_SKILL_DIR}`:

```sh
uv run "${CLAUDE_SKILL_DIR}/scripts/gphoto.py" check
```

Requires [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`
or `brew install uv`); the first run creates an isolated Python 3.11 environment with the
pinned dependency (Pillow). Optional: `ffmpeg` and `ffprobe` on `PATH`, for video frames on
the contact sheets. Always quote paths and subject names.

Every command prints one JSON object on stdout and exits 0. On failure it exits 2 and the
last stderr line is `{"status":"failed","error":CODE,"message":...}`: look the code up in
[references/errors.md](references/errors.md) and tell the user the remedy.

## The sequence

1. **`check`.** Prints `{"status":"ok","local":true,"client_secret":"present|missing",
   "token":"present|missing","ffmpeg":"present|missing","config_dir":...}`. If
   `client_secret` is `missing`, walk the user through the one-time Google Cloud setup in
   [references/setup.md](references/setup.md) (about 10 minutes, mostly in the web
   console) and run `check` again.
2. **`auth`** (only if `token` is `missing`, or a later command failed with
   `AUTH_REQUIRED`). Opens the browser for Google sign-in and waits up to 5 minutes for
   the user. Tell the user first: sign in with the account that owns the photos; the
   "Google hasn't verified this app" page is expected for their own app (Continue); grant
   the Google Photos permission. Run `auth` **in the background** (or with output streamed
   to you), not as a blocking foreground command: right away it writes a stderr line
   `{"notice":"open this URL to sign in","url":...}`. If the browser did not open, read
   that line **while `auth` is still running** and give the user the URL then. The URL
   works only for the running `auth`; one from an earlier run is never valid. When `auth`
   exits it prints `{"status":"ok","signed_in":true}`.
3. **`start`** creates a picking session. `--subject` is the folder name (who or what),
   `--year` the year; `--search` is the text the user types in the picker (default: the
   subject). Filters (`--from/--to` within the year, `--type`, `--camera`, `--orientation`,
   `--min-side`) are applied after picking: items outside them are not downloaded and are
   counted. It then opens `picker_uri` in the user's default browser, the way `auth` opens
   the sign-in page (`--no-browser` skips that, e.g. when the user will pick on another
   device). Prints `session`, `picker_uri`, `search`, `expires`, `instructions` and
   `warnings`; `BROWSER_NOT_OPENED` there means no browser tab was opened. With a
   non-default `--out-root`, pass the same `--out-root` to `curate` and `select` later
   (`fetch` remembers it from `start`).
4. **Relay the link.** The picker usually opens in the browser on its own, but always give
   the user `picker_uri` **verbatim** as well (never shorten or rewrite it): the browser may
   not have opened (`BROWSER_NOT_OPENED`), may be signed in to another account, or the user
   may pick on another device. Tell them, in your own words:
   - use the tab that opened, or open the link in a browser signed in to the same Google
     account;
   - type exactly `<search>` (the `search` value) into the picker's search box: a
     person's name finds Google's face group for them;
   - use the **select-all checkbox next to each day** instead of tapping single photos;
   - at most 2,000 items per session; then press **Done**.
5. **`fetch`** waits for Done (up to `--wait` seconds, default 540), then downloads every
   picked item at full resolution. `--wait` bounds only the waiting: downloading hundreds
   or up to 2,000 full-size items after Done can take much longer (many minutes to hours).
   Run `fetch` **in the background**, without a tight command timeout (in Claude Code: a
   background Bash command), and wait for it to finish. There is no poll-only mode: a
   `fetch` that sees Done starts downloading right away, in the foreground. If your agent
   can only run short foreground commands, keep re-running `fetch` (e.g. `--wait 60`) until
   it returns `"status":"ok"`; a run killed by the command timeout loses nothing already
   downloaded.
   - Killed by a timeout (or any hard kill): run `fetch` again. The pending session
     survives, the manifest is saved after every item, partial downloads are cleaned up,
     and finished items count as `already_present`. (If the session has expired meanwhile,
     `SESSION_EXPIRED`: run `start` again and pick again; nothing downloaded is lost.)
   - Interrupted (Ctrl-C, `INTERRUPTED`) or failed **while waiting for Done or while
     listing the picked items**: the pending session is kept; just run `fetch` again.
   - Interrupted or failed **while downloading**: the session is closed, so run `start`
     and pick again; items already downloaded are kept and counted as `already_present`.
     (`SESSION_EXPIRED` at any point also forgets the session: run `start` again.)
   - `"status":"waiting"`: the user has not pressed Done yet. No media written, manifest
     unchanged; the session stays pending. Run `fetch` again (ask the user how it is going
     if it repeats).
   - `"status":"ok"`: the downloads are done and the session is closed.
   - More than 2,000 items, or another search (a second person, a missed month): run
     another `start` / relay / `fetch` pair with the same `--subject` and `--year`. Items
     already downloaded are counted as `already_present`, never downloaded twice.
6. **`curate`** (no network) groups bursts and near-duplicates and keeps the sharpest,
   drops blurry and dark shots, balances the months, and draws contact sheets. Prints
   `candidates`, `photos`, `videos`, `dropped`, `sheets` (absolute paths of
   `sheet-NN.jpg`), `picks_file`, `target`, `video_target` and `warnings`.
7. **Read every sheet image** in `sheets`, in order. Each sheet is a grid of up to 20 tiles
   of at most 256 px, each labelled `<ref> <YYYY-MM-DD>` (`C001…` photos, `V001…` videos;
   a video tile shows four frames when ffmpeg is present). Optionally read
   `curation/candidates.json` (the folder above `sheets/`) for each ref's date, sharpness and
   `group_size` (how many similar shots it stood for).
8. **Write `picks_file`** (`<year>/curation/picks.json`) following the rubric in
   [references/curation.md](references/curation.md): about `target` photos and
   `video_target` videos, ranked, one short reason each.
9. **`select`** validates the picks and rebuilds `<year>/selected/` (`001_<file>`,
   `002_<file>`… in rank order) and `<year>/selection.json`. On `INVALID_PICKS` fix the
   file and run `select` again. Picks must be written after the latest `curate`:
   `select` refuses an older picks file with `PICKS_OUTDATED`.
10. **Report** to the user (see below).

## Agent rules

- Relay `picker_uri` verbatim, together with the exact search text and the per-day
  select-all tip. Apart from the tab `start` opens itself, never open the picker or Google
  Photos yourself (no browser tools).
- For curation look **only at the contact sheets**. Never open, read or view the full-size
  files in `media/`, and never ask to.
- Never print, paste, read or ask for tokens, the client secret, or the contents of
  `client_secret.json` / `token.json`. Never ask the user to paste them into the chat.
- Never delete, move or edit anything in `media/`; it holds the user's originals.
- Re-running `curate` renumbers the refs: after it, write `picks.json` again from the new
  sheets before `select` (an older picks file is refused with `PICKS_OUTDATED`).
- `--subject` becomes a folder name: use the user's word for the person or event
  (e.g. `Mia`), not a sentence.

## Report

After `fetch`, report every count, including what was not downloaded:
`picked`, `downloaded`, `already_present`, `filtered_out` (by reason: `out_of_range`,
`type`, `camera`, `orientation`, `resolution`), `skipped` (`video_not_ready`: Google is
still processing the video; `download_failed`), the `folder`, and the `warnings`
(see [references/errors.md](references/errors.md#warnings)). An `ok` summary always adds up:
`picked = downloaded + already_present + filtered_out + skipped`.

After `curate`, report the candidate counts and `dropped` (near-duplicates, blurry, dark,
month cap, missing or undecodable files). After `select`, report `selected`, `photos`,
`videos` and the `folder`, and mention that files in `selected/` are hard links to the
originals: editing one in place edits the original, so copy them before editing.

## Output

```
~/Pictures/google-photo/          # default --out-root
└── <subject>/<year>/
    ├── manifest.json             # every downloaded item and its metadata
    ├── media/                    # full-size originals (never deleted by the skill)
    ├── .thumbs/                  # small Google thumbnails, used for curation
    ├── curation/
    │   ├── candidates.json       # the pre-filtered candidates (refs C001…, V001…)
    │   ├── sheets/sheet-01.jpg…  # contact sheets for the agent
    │   └── picks.json            # written by the agent
    ├── selection.json            # the ranked selection with reasons
    └── selected/                 # 001_<file>, 002_<file>… hard links (or copies)
```

`manifest.json` maps each Google item id to `file`, `filename`, `type`, `mime`,
`create_time` (UTC), `local_time`, `width`, `height`, `camera_make`, `camera_model`, `fps`,
`thumb` and `session`. Re-running `fetch` for the same subject and year adds only new items
and re-downloads an item whose file was deleted from `media/`.

## Privacy

- Full-size photos and videos go only from Google to the user's disk. There is no
  telemetry and no other service.
- During curation the agent views the small contact-sheet thumbnails (tiles of at most
  256 px). Those thumbnails therefore go to the agent's own model provider (e.g. Anthropic
  for Claude Code). Tell the user this before curating if they have not heard it.
- Only the read-only Picker permission is requested. Tokens stay in
  `~/.config/google-photo/` (mode 0600) and are never printed.

## References

- [references/setup.md](references/setup.md): one-time Google Cloud project, consent screen and Desktop OAuth client.
- [references/curation.md](references/curation.md): the picking rubric and the `picks.json` format.
- [references/errors.md](references/errors.md): every error and warning code with its remedy.
