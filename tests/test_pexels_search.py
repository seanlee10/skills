import importlib.util
import io
import json
from pathlib import Path
import urllib.error

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/pexels-search/scripts/pexels.py'
spec = importlib.util.spec_from_file_location('pexels', SCRIPT)
pexels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pexels)


def video(id_, width=1080, height=1920, duration=12, files=None):
    return {
        'id': id_, 'width': width, 'height': height, 'duration': duration,
        'url': f'https://www.pexels.com/video/clip-{id_}/', 'image': f'https://images.pexels.com/videos/{id_}/a.jpg',
        'user': {'name': 'Jane Doe', 'url': 'https://www.pexels.com/@jane'},
        'video_files': files if files is not None else [
            {'id': 1, 'quality': 'hd', 'file_type': 'video/mp4', 'width': 1080, 'height': 1920, 'fps': 30,
             'link': f'https://videos.pexels.com/video-files/{id_}/1080.mp4'},
            {'id': 2, 'quality': 'hd', 'file_type': 'video/mp4', 'width': 720, 'height': 1280, 'fps': 30,
             'link': f'https://videos.pexels.com/video-files/{id_}/720.mp4'},
            {'id': 3, 'quality': 'sd', 'file_type': 'video/mp4', 'width': 360, 'height': 640, 'fps': 25,
             'link': f'https://videos.pexels.com/video-files/{id_}/360.mp4'},
            {'id': 4, 'quality': 'hls', 'file_type': 'video/hls', 'width': None, 'height': None, 'fps': None,
             'link': f'https://player.vimeo.com/external/{id_}.m3u8'},
        ],
    }


def photo(id_, width=3000, height=4000):
    return {
        'id': id_, 'width': width, 'height': height, 'url': f'https://www.pexels.com/photo/p-{id_}/',
        'photographer': 'John Roe', 'photographer_url': 'https://www.pexels.com/@john',
        'alt': 'City at night', 'avg_color': '#203040',
        'src': {'original': f'https://images.pexels.com/photos/{id_}/pexels-photo-{id_}.jpeg',
                'medium': f'https://images.pexels.com/photos/{id_}/pexels-photo-{id_}.jpeg?h=350'},
    }


@pytest.fixture
def api(monkeypatch):
    calls = []
    routes = {}

    def fake(url, key):
        calls.append(url)
        for prefix, body in routes.items():
            if url.startswith(prefix):
                return body
        raise AssertionError(url)

    monkeypatch.setattr(pexels, 'fetch_json', fake)
    return routes, calls


@pytest.fixture
def files(monkeypatch):
    served = {}

    def fake(url, target):
        Path(target).write_bytes(served.setdefault(url, url.encode()))

    monkeypatch.setattr(pexels, 'fetch_file', fake)
    return served


def test_search_videos_defaults_to_portrait_and_drops_short_clips(api):
    routes, calls = api
    routes['https://api.pexels.com/videos/search'] = {
        'total_results': 2, 'next_page': 'x', 'videos': [video(1, duration=12), video(2, duration=3)]}
    out = pexels.search('rainy street', key='k', min_duration=5)
    assert 'orientation=portrait' in calls[0] and 'query=rainy+street' in calls[0] and 'per_page=15' in calls[0]
    assert [r['id'] for r in out['results']] == [1]
    assert out['filtered_out'] == 1 and out['has_next_page'] is True
    result = out['results'][0]
    assert result['preview_image'].endswith('a.jpg') and result['author'] == 'Jane Doe'
    assert [(f['width'], f['height']) for f in result['files']] == [(360, 640), (720, 1280), (1080, 1920)]


def test_search_photos_filters_resolution(api):
    routes, calls = api
    routes['https://api.pexels.com/v1/search'] = {'total_results': 2, 'photos': [photo(5), photo(6, 800, 600)]}
    out = pexels.search('city', key='k', kind='photo', orientation='any', min_width=1000, min_height=1000)
    assert 'orientation' not in calls[0]
    assert [r['id'] for r in out['results']] == [5] and out['filtered_out'] == 1
    assert out['results'][0]['author'] == 'John Roe' and 'duration' not in out['results'][0]


@pytest.mark.parametrize('kwargs', [{'query': ' '}, {'per_page': 81}, {'page': 0},
                                    {'kind': 'photo', 'min_duration': 5}])
def test_search_rejects_bad_arguments(api, kwargs):
    with pytest.raises(ValueError):
        pexels.search(**{'query': 'x', 'key': 'k', **kwargs})


def test_download_picks_smallest_file_meeting_minimum(api, files, tmp_path):
    routes, _ = api
    routes['https://api.pexels.com/videos/videos/7'] = video(7)
    out = pexels.download(7, key='k', output_dir=tmp_path)
    assert Path(out['path']) == tmp_path / 'pexels-video-7.mp4'
    assert (out['width'], out['height'], out['meets_minimum'], out['cached']) == (720, 1280, True, False)
    sidecar = json.loads((tmp_path / 'pexels-video-7.source.json').read_text())
    assert sidecar['author'] == 'Jane Doe' and sidecar['sha256'] == out['sha256']
    assert 'Pexels' in sidecar['license']


def test_download_falls_back_to_largest_and_reuses_cache(api, files, tmp_path):
    routes, _ = api
    routes['https://api.pexels.com/videos/videos/8'] = video(8)
    first = pexels.download(8, key='k', output_dir=tmp_path, min_width=2160, min_height=3840)
    assert (first['width'], first['meets_minimum']) == (1080, False)
    again = pexels.download(8, key='k', output_dir=tmp_path, min_width=2160, min_height=3840)
    assert again['cached'] is True and again['sha256'] == first['sha256']
    (tmp_path / 'pexels-video-8.mp4').write_bytes(b'tampered')
    assert pexels.download(8, key='k', output_dir=tmp_path, min_width=2160, min_height=3840)['cached'] is False


def test_download_photo_original(api, files, tmp_path):
    routes, _ = api
    routes['https://api.pexels.com/v1/photos/5'] = photo(5)
    out = pexels.download(5, key='k', kind='photo', output_dir=tmp_path)
    assert Path(out['path']).name == 'pexels-photo-5.jpeg' and 'duration' not in out


def test_download_rejects_non_pexels_media_host(api, tmp_path):
    routes, _ = api
    bad = video(9, files=[{'quality': 'hd', 'file_type': 'video/mp4', 'width': 720, 'height': 1280,
                           'link': 'https://evil.example/x.mp4'}])
    routes['https://api.pexels.com/videos/videos/9'] = bad
    with pytest.raises(ValueError):
        pexels.download(9, key='k', output_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_fetch_json_retries_once_after_rate_limit(monkeypatch):
    attempts, sleeps = [], []

    def opener(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, 'Too Many', {'Retry-After': '2'}, io.BytesIO())
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(pexels.urllib.request, 'urlopen', opener)
    monkeypatch.setattr(pexels.time, 'sleep', sleeps.append)
    assert pexels.fetch_json('https://api.pexels.com/v1/search?query=x', 'secret') == {'ok': True}
    assert sleeps == [2] and attempts[0].get_header('Authorization') == 'secret'


def test_missing_key_message(monkeypatch, capsys):
    monkeypatch.delenv('PEXELS_API_KEY', raising=False)
    assert pexels.main(['search', '--query', 'x']) == 1
    assert 'PEXELS_API_KEY' in capsys.readouterr().err
