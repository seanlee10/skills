---
name: pexels-search
description: Search Pexels for free stock videos and photos by description, filter by orientation, duration and resolution, and download a chosen item with attribution metadata. Use for B-roll, stock footage, or stock images, such as real-footage scenes for a vertical short.
---

# Pexels search

Find stock footage or photos on Pexels and save the chosen ones locally. This skill searches and downloads only.
The calling agent decides which results fit and where each file goes; it does not edit, trim, or place clips in a project.

## Run

Run [scripts/pexels.py](scripts/pexels.py) relative to this skill's directory. It needs `PEXELS_API_KEY` in the environment.
If it is missing, tell the user to create a free key at https://www.pexels.com/api/ and export it. Never request the key in chat.

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

Errors go to stderr with exit status 1. The helper retries once after an HTTP 429 rate limit and then stops.
Report the actual error; do not loop or switch to scraping pexels.com pages.
Media downloads are accepted only from `pexels.com` hosts, and the API key is sent only to `api.pexels.com`.

Pexels content is free to use under the Pexels License; attribution is appreciated but not required.
Keep the sidecar so credits can be added later, and do not present clips as the user's own footage.
Return clickable absolute file links with duration and resolution.
