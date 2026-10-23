# /// script
# requires-python = "==3.11.*"
# dependencies = [
#     "yt-dlp[default]==2026.10.21",
# ]
# ///
"""Download one YouTube video as a validated H.264/AAC MP4. Print JSON to stdout."""
import argparse
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse


def canonical_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("Provide a YouTube video URL")
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "youtu.be" and len(parts) == 1:
        video_id = parts[0]
    elif parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in ("shorts", "embed", "live"):
            video_id = parts[1]
        else:
            raise ValueError("Provide a single video URL, not a playlist or channel")
    else:
        raise ValueError("Only youtube.com and youtu.be video URLs are supported")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid YouTube video ID")
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_media(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not math.isfinite(duration) or duration <= 0 or not video:
        raise ValueError("File has no video or no positive duration")
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    return {"duration": duration, "video": video, "audio": audio,
            "format": info["format"]["format_name"]}


def inspect_mp4(path):
    info = inspect_media(path)
    if ("mp4" not in info["format"].split(",") or info["video"].get("codec_name") != "h264"
            or info["video"].get("pix_fmt") != "yuv420p"
            or (info["audio"] and info["audio"].get("codec_name") != "aac")):
        raise ValueError("File is not a compatible H.264/AAC MP4")
    return info


def convert_mp4(source, target, timeout):
    info = inspect_media(source)
    video = info["video"]
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?"]
    if video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p":
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
    if info["audio"]:
        args += (["-c:a", "copy"] if info["audio"].get("codec_name") == "aac"
                 else ["-c:a", "aac", "-b:a", "192k"])
    args += ["-movflags", "+faststart", str(target)]
    subprocess.run(args, stdout=sys.stderr, stderr=sys.stderr, check=True, timeout=timeout)
    return inspect_mp4(target)


def download(url, output_dir, force=False, timeout=3600, max_height=None):
    url, video_id = canonical_url(url)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive and finite")
    if max_height is not None and max_height <= 0:
        raise ValueError("Maximum height must be positive")
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise RuntimeError(f"Install {binary} first (macOS: brew install ffmpeg)")
    runtime = next((r for r in ("deno", "node") if shutil.which(r)), None)
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{video_id}.mp4"
    metadata = output_dir / f"{video_id}.source.json"
    with (output_dir / f".{video_id}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("This video is already being downloaded") from None
        if not force and (target.exists() or metadata.exists()):
            if target.is_file() and metadata.is_file():
                data = json.loads(metadata.read_text(encoding="utf-8"))
                if (data.get("source_url") == url and data.get("max_height") == max_height
                        and data.get("sha256") == sha256(target)):
                    inspect_mp4(target)
                    return {**data, "video_path": str(target), "cached": True}
            raise ValueError("Existing output does not match; choose another directory or use --force")
        if not runtime:
            raise RuntimeError("Install a supported JavaScript runtime, Deno or Node, before downloading")
        with tempfile.TemporaryDirectory(prefix=".youtube-", dir=output_dir) as temporary:
            work = Path(temporary)
            formats = "bv*+ba/b"
            if max_height is not None:
                formats = f"bv*[height<={max_height}]+ba/b[height<={max_height}]"
            args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                    "--no-progress", "--no-simulate", "--socket-timeout", "30", "--retries", "2",
                    "--fragment-retries", "2", "--match-filters", "!is_live & !is_upcoming",
                    "--js-runtimes", runtime, "-f", formats, "-S", "res,vcodec:h264,acodec:aac",
                    "--merge-output-format", "mkv", "--remux-video", "mkv", "--write-info-json",
                    "-o", str(work / "source.%(ext)s"), "--", url]
            subprocess.run(args, stdout=sys.stderr, stderr=sys.stderr, check=True, timeout=timeout)
            source = work / "source.mkv"
            if not source.is_file():
                raise RuntimeError("No video produced; live/upcoming or unavailable video may have been skipped")
            info = json.loads((work / "source.info.json").read_text(encoding="utf-8"))
            video = work / "video.mp4"
            media = convert_mp4(source, video, timeout)
            data = {"source_url": url, "video_id": video_id, "title": info.get("title"),
                    "channel": info.get("channel"), "duration": media["duration"],
                    "width": media["video"]["width"], "height": media["video"]["height"],
                    "size_bytes": video.stat().st_size, "max_height": max_height,
                    "video_path": str(target), "sha256": sha256(video)}
            saved_metadata = work / "source.json"
            saved_metadata.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            video.replace(target)
            saved_metadata.replace(metadata)
            return {**data, "cached": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads" / "youtube")
    parser.add_argument("--max-height", type=int, help="Limit source video height, for example 1080")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=float, default=3600,
                        help="Seconds allowed for download and conversion, separately (default: 3600)")
    args = parser.parse_args()
    try:
        result = download(args.url, args.output_dir, args.force, args.timeout, args.max_height)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Video download failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
