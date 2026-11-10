---
name: pexels-search
description: Search the public Pexels website for free stock videos and photos by description, filter by orientation, duration and resolution, and download a chosen item with attribution metadata. Use for B-roll, stock footage, or stock images, such as real-footage scenes for a vertical short.
---

# Pexels search

Find stock footage or photos on Pexels and save the chosen ones locally. This skill searches and downloads only.
The calling agent decides which results fit and where each file goes; it does not edit, trim, or place clips in a project.

## Run

Run [scripts/pexels.py](scripts/pexels.py) with `uv` on a desktop with Google Chrome installed. The helper opens a temporary browser window on the public Pexels site. No API key or account setup is required.

```sh
uv run <skill folder>/scripts/pexels.py search --query 'rainy city street at night'
uv run <skill folder>/scripts/pexels.py download --id 1234567
```

## Search

`search` defaults to portrait videos and 15 results. Write a concrete visual query: subject, setting, light, motion.
Options: `--type video|photo`, `--orientation portrait|landscape|square|any`, `--min-duration` and `--max-duration` in seconds,
`--min-width` and `--min-height` in pixels of the source, `--per-page` up to 80, and `--page`.
Duration and resolution filters run locally after Pexels returns a page; `filtered_out` counts what was dropped.
If few results remain, try `--page 2`, a broader query, or `--orientation any` before relaxing hard requirements.

Stdout is one JSON object with `results`. Each result has `id`, `type`, `width`, `height`, `url`, `preview_image`,
`author`, and `author_url`. Videos add `duration` and their MP4 renditions under `files`; photos add `alt` and `avg_color`.
Choose by metadata first: orientation, duration against the scene length, resolution, and the Pexels page slug in `url`.
When metadata cannot separate candidates, view `preview_image` before downloading.

## Download

`download --id N` fetches one item. For videos, it saves the smallest MP4 at least `--min-width` × `--min-height`
(default 720 × 1280). If none is large enough it saves the largest and reports `meets_minimum: false`.
For photos, use `--type photo`; it saves the original file.

Files go to `~/Downloads/pexels/` unless `--output-dir /absolute/path` is given. Names are `pexels-<type>-<id>.<ext>`,
with a `pexels-<type>-<id>.source.json` sidecar holding the author, Pexels page, file URL, size, hash, and license note.
An existing file is reused when its sidecar's file URL and SHA-256 match (`cached: true`). Use `--force` only to replace it.
For several clips, run `download` once per ID.

Stdout is one JSON object with `path`, `width`, `height`, `duration` for videos, `meets_minimum`, `sha256`, `size_bytes`,
`cached`, `author`, `author_url`, `url`, and `license`.

## Failures and licensing

Search results store the candidate's media links and credits under `~/.cache/pexels-search/` (or `$XDG_CACHE_HOME/pexels-search/`). A download by ID can reuse that metadata for 24 hours. For an unseen ID the helper opens its public detail page. Downloads follow HTTPS links on Pexels hosts.

If Chrome is unavailable or Pexels returns a site check, report the specific CLI error. With an interactive browser available, continue the task on the public Pexels website. Use its Photos or Videos search and orientation filter, open the selected item, and check dimensions and duration in the details. Use the size menu and **Download Selected Size** for video, or **Free download** for the original photo. Capture the browser's saved file path, keep the page URL and creator alongside the file, and report the actual size chosen. If the site requires a human check, use the browser's normal handoff. The helper retries a rate-limited page once if the wait is at most 60 seconds. If HTTP 429 reaches the caller, stop and report the rate limit.

Pexels content is free to use under the Pexels License; attribution is appreciated but not required.
Keep the sidecar so credits can be added later, and do not present clips as the user's own footage.
Return clickable absolute file links with duration and resolution.
