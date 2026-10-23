---
name: youtube-download
description: Download a single YouTube video URL as a local MP4 with H.264 video and AAC audio. Use for YouTube video downloads, saving Shorts, or converting a YouTube link to MP4.
---

# YouTube download

Download one complete video to a local MP4. Use this skill independently of any editing or video-generation project.

## Run

Run [scripts/download_video.py](scripts/download_video.py) relative to this skill's directory:

```sh
uv run <skill folder>/scripts/download_video.py --url 'YOUTUBE_VIDEO_URL'
```

Use the user's destination with `--output-dir /absolute/path`. Otherwise use the default `~/Downloads/youtube/`.
Files are named `<video-id>.mp4` and `<video-id>.source.json` so titles cannot create invalid filenames.
Pass the complete URL as one argument. The helper accepts watch, Shorts, Music, embed, live-archive, and youtu.be links.
Playlist and time parameters on a video link are ignored. Playlist-only links, channels, live streams, and upcoming videos are rejected.
For several explicitly supplied video links, run the helper once per link. Do not expand playlists or channels.

Use `--max-height 1080` when the user requests a resolution limit. Otherwise the helper selects the best available resolution.
It merges separate video and audio streams, copies compatible H.264/AAC streams, and converts other codecs with FFmpeg.
The result uses an MP4 container, H.264 with yuv420p, AAC when audio exists, and fast-start metadata.
Re-encoding does not improve source quality. Do not trim, upscale, generate a new video, or launch a paid service for a download request.

## Dependencies and failures

`uv` fetches Python 3.11 and the pinned `yt-dlp[default]` dependency on first run.
Install FFmpeg with ffprobe and a supported JavaScript runtime, Deno or Node, if missing.
On macOS, `brew install ffmpeg deno` provides both. On Linux use the platform's package manager and the runtime's official installer.
The helper uses a Unix file lock and supports macOS and Linux. Windows requires WSL.
JavaScript runtime requirements are maintained in the [yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

If an extraction error indicates that yt-dlp is outdated, retry once with the current dependency:

```sh
uv run --no-project --python 3.11 --with 'yt-dlp[default]' python <skill folder>/scripts/download_video.py --url 'YOUTUBE_VIDEO_URL'
```

Report unresolved failures with the actual error. Do not loop indefinitely.
Do not automatically load browser cookies or bypass login, payment, private-video, or regional access restrictions.
For blocked access, request an accessible source or a local file.

Existing files are reused only when the source URL, resolution option, hash, and MP4 validation match.
Use `--force` only when the user requests replacement. Failed downloads or conversions leave existing files intact.
The default timeout is 3600 seconds for the download and another 3600 for conversion. Increase `--timeout` for a long video if needed.

## Return the result

Progress goes to stderr. On success stdout is one JSON object with `video_path`, `source_url`, `title`, `duration`,
`width`, `height`, `size_bytes`, `sha256`, and `cached`, plus source metadata.
The helper checks the container, codecs, pixel format, and positive duration with ffprobe before returning success.
Return a clickable absolute file link, duration, and resolution. Report success only after the helper succeeds.
