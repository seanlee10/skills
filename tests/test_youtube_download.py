import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/youtube-download/scripts/download_video.py'
spec = importlib.util.spec_from_file_location('download_video', SCRIPT)
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)
VIDEO_ID = 'BaW_jenozKc'
URL = f'https://www.youtube.com/watch?v={VIDEO_ID}'


@pytest.mark.parametrize('url', [
    URL + '&list=PLexample&t=5',
    f'https://youtu.be/{VIDEO_ID}?t=5',
    f'https://www.youtube.com/shorts/{VIDEO_ID}',
    f'https://music.youtube.com/watch?v={VIDEO_ID}',
    f'https://m.youtube.com/embed/{VIDEO_ID}',
    f'https://www.youtube.com/live/{VIDEO_ID}',
])
def test_video_urls(url):
    assert video.canonical_url(url) == (URL, VIDEO_ID)


@pytest.mark.parametrize('url', [
    'https://www.youtube.com/playlist?list=PLexample',
    'https://www.youtube.com/@channel',
    f'https://youtube.com.evil.example/watch?v={VIDEO_ID}',
    f'https://youtube.com@evil.example/watch?v={VIDEO_ID}',
    f'file:///watch?v={VIDEO_ID}',
    'https://youtu.be/too-short',
])
def test_invalid_urls_leave_no_output(tmp_path, url):
    with pytest.raises(ValueError):
        video.download(url, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


@pytest.fixture
def source(tmp_path):
    if not all(shutil.which(binary) for binary in ('ffmpeg', 'ffprobe')):
        pytest.skip('FFmpeg and ffprobe are required for media integration tests')
    path = tmp_path / 'fixture.mkv'
    subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
        'testsrc=size=160x90:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440',
        '-t', '0.5', '-c:v', 'libvpx-vp9', '-c:a', 'libopus', str(path),
    ], check=True, timeout=30)
    return path


def test_conversion_and_stream_copy(source, tmp_path):
    first = tmp_path / 'first.mp4'
    media = video.convert_mp4(source, first, 30)
    assert media['video']['codec_name'] == 'h264'
    assert media['audio']['codec_name'] == 'aac'
    assert (media['video']['width'], media['video']['height']) == (160, 90)
    assert 0.4 < media['duration'] < 0.8
    second = tmp_path / 'second.mp4'
    video.convert_mp4(first, second, 30)

    def stream_hashes(path):
        return subprocess.run([
            'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0', '-c', 'copy',
            '-f', 'streamhash', '-hash', 'sha256', '-',
        ], capture_output=True, text=True, check=True, timeout=30).stdout

    assert stream_hashes(first) == stream_hashes(second)
    with pytest.raises(ValueError, match='compatible'):
        video.inspect_mp4(source)


def test_download_cache_and_protected_output(source, tmp_path, monkeypatch):
    real_run = video.subprocess.run
    downloads = []

    def fake_run(args, **kwargs):
        if args[1:3] == ['-m', 'yt_dlp']:
            downloads.append(args)
            template = Path(args[args.index('-o') + 1])
            shutil.copyfile(source, template.parent / 'source.mkv')
            (template.parent / 'source.info.json').write_text(json.dumps({'title': '테스트 영상'}))
            return subprocess.CompletedProcess(args, 0)
        return real_run(args, **kwargs)

    monkeypatch.setattr(video.subprocess, 'run', fake_run)
    real_which = video.shutil.which
    monkeypatch.setattr(video.shutil, 'which', lambda name: '/mock/node' if name == 'node' else real_which(name))
    output = tmp_path / 'output'
    result = video.download(URL + '&list=PLignored&t=5', output, max_height=720)
    assert result['title'] == '테스트 영상' and result['cached'] is False
    target = Path(result['video_path'])
    assert target.is_file() and result['sha256'] == video.sha256(target)
    assert json.loads((output / f'{VIDEO_ID}.source.json').read_text())['source_url'] == URL
    assert video.download(URL, output, max_height=720)['cached'] is True
    assert len(downloads) == 1
    with pytest.raises(ValueError, match='Existing output'):
        video.download(URL, output, max_height=1080)
    target.write_bytes(b'existing modified file')
    with pytest.raises(ValueError, match='Existing output'):
        video.download(URL, output, max_height=720)

    def failed_run(args, **kwargs):
        if args[1:3] == ['-m', 'yt_dlp']:
            raise subprocess.CalledProcessError(1, args)
        return real_run(args, **kwargs)

    monkeypatch.setattr(video.subprocess, 'run', failed_run)
    with pytest.raises(subprocess.CalledProcessError):
        video.download(URL, output, force=True, max_height=720)
    assert target.read_bytes() == b'existing modified file'
    monkeypatch.setattr(video.subprocess, 'run', fake_run)
    assert video.download(URL, output, force=True, max_height=720)['cached'] is False
    video.inspect_mp4(target)


def test_live_or_upcoming_skip_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(video.shutil, 'which', lambda name: f'/mock/{name}')
    monkeypatch.setattr(video.subprocess, 'run', lambda args, **kwargs: subprocess.CompletedProcess(args, 0))
    with pytest.raises(RuntimeError, match='No video produced'):
        video.download(URL, tmp_path)
    assert not list(tmp_path.glob('*.mp4'))


def test_cli_failure_has_no_success_json(tmp_path):
    result = subprocess.run([
        'python3', str(SCRIPT), '--url', 'https://example.com/video', '--output-dir', str(tmp_path),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and result.stdout == ''
    assert 'Only youtube.com and youtu.be' in result.stderr
