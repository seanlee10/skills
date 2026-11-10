import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/pexels-search/scripts/pexels.py'
spec = importlib.util.spec_from_file_location('pexels', SCRIPT)
pexels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pexels)


def video(id_, width=1080, height=1920, duration=12, files=None):
    return {
        'id': id_, 'width': width, 'height': height, 'duration': duration,
        'slug': 'clip', 'user': {'first_name': 'Jane', 'last_name': 'Doe', 'slug': 'jane'},
        'video': {'thumbnail': {'medium': f'https://images.pexels.com/videos/{id_}/a.jpg'},
                  'video_files': files if files is not None else [
            {'id': 1, 'quality': 'hd', 'file_type': 'video/mp4', 'width': 1080, 'height': 1920, 'fps': 30,
             'link': f'https://videos.pexels.com/video-files/{id_}/1080.mp4'},
            {'id': 2, 'quality': 'hd', 'file_type': 'video/mp4', 'width': 720, 'height': 1280, 'fps': 30,
             'link': f'https://videos.pexels.com/video-files/{id_}/720.mp4'},
            {'id': 3, 'quality': 'sd', 'file_type': 'video/mp4', 'width': 360, 'height': 640, 'fps': 25,
             'link': f'https://videos.pexels.com/video-files/{id_}/360.mp4'},
            {'id': 4, 'quality': 'hls', 'file_type': 'video/hls', 'width': None, 'height': None, 'fps': None,
             'link': f'https://player.vimeo.com/external/{id_}.m3u8'},
        ]},
    }


def photo(id_, width=3000, height=4000):
    return {
        'id': id_, 'width': width, 'height': height, 'slug': 'city',
        'user': {'first_name': 'John', 'last_name': 'Roe', 'slug': 'john'},
        'alt': 'City at night', 'main_color': [32, 48, 64],
        'image': {'download_link': f'https://images.pexels.com/photos/{id_}/pexels-photo-{id_}.jpeg',
                'medium': f'https://images.pexels.com/photos/{id_}/pexels-photo-{id_}.jpeg?h=350'},
    }


def results_page(kind, items, total, number=1, pages=1):
    return {'initialData': {'data': [{'type': kind, 'attributes': item} for item in items],
                            'pagination': {'total_results': total, 'current_page': number, 'total_pages': pages}}}


@pytest.fixture
def website(monkeypatch, tmp_path):
    calls = []
    routes = {}

    def read(url):
        calls.append(url)
        return routes[url]

    monkeypatch.setattr(pexels, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(pexels, 'page_props', read)
    return routes, calls


@pytest.fixture
def files(monkeypatch):
    served = {}

    def fake(url, target):
        Path(target).write_bytes(served.setdefault(url, url.encode()))

    monkeypatch.setattr(pexels, 'fetch_file', fake)
    return served


def test_search_videos_defaults_to_portrait_and_drops_short_clips(website):
    routes, calls = website
    url = 'https://www.pexels.com/search/videos/rainy%20street/?orientation=portrait'
    routes[url] = results_page('video', [video(1, duration=12), video(2, duration=3)], 3, pages=2)
    out = pexels.search('rainy street', min_duration=5, per_page=2)
    assert calls == [url]
    assert [r['id'] for r in out['results']] == [1]
    assert out['filtered_out'] == 1 and out['has_next_page'] is True
    result = out['results'][0]
    assert result['preview_image'].endswith('a.jpg') and result['author'] == 'Jane Doe'
    assert [(f['width'], f['height']) for f in result['files']] == [(360, 640), (720, 1280), (1080, 1920)]


def test_search_photos_filters_resolution(website):
    routes, calls = website
    routes['https://www.pexels.com/search/city/'] = results_page('photo', [photo(5), photo(6, 800, 600)], 2)
    out = pexels.search('city', kind='photo', orientation='any', min_width=1000, min_height=1000)
    assert 'orientation' not in calls[0]
    assert [r['id'] for r in out['results']] == [5] and out['filtered_out'] == 1
    assert out['results'][0]['author'] == 'John Roe' and 'duration' not in out['results'][0]


@pytest.mark.parametrize('kwargs', [{'query': ' '}, {'per_page': 81}, {'page': 0},
                                    {'kind': 'photo', 'min_duration': 5}])
def test_search_rejects_bad_arguments(website, kwargs):
    with pytest.raises(ValueError):
        pexels.search(**{'query': 'x', **kwargs})


def test_download_picks_smallest_file_meeting_minimum(website, files, tmp_path):
    routes, _ = website
    routes['https://www.pexels.com/video/7/'] = {'medium': {'type': 'video', 'id': '7', 'attributes': video(7)}}
    out = pexels.download(7, output_dir=tmp_path)
    assert Path(out['path']) == tmp_path / 'pexels-video-7.mp4'
    assert (out['width'], out['height'], out['meets_minimum'], out['cached']) == (720, 1280, True, False)
    sidecar = json.loads((tmp_path / 'pexels-video-7.source.json').read_text())
    assert sidecar['author'] == 'Jane Doe' and sidecar['sha256'] == out['sha256']
    assert 'Pexels' in sidecar['license']


def test_download_falls_back_to_largest_and_reuses_cache(website, files, tmp_path):
    routes, _ = website
    routes['https://www.pexels.com/video/8/'] = {'medium': {'type': 'video', 'id': '8', 'attributes': video(8)}}
    first = pexels.download(8, output_dir=tmp_path, min_width=2160, min_height=3840)
    assert (first['width'], first['meets_minimum']) == (1080, False)
    again = pexels.download(8, output_dir=tmp_path, min_width=2160, min_height=3840)
    assert again['cached'] is True and again['sha256'] == first['sha256']
    (tmp_path / 'pexels-video-8.mp4').write_bytes(b'tampered')
    assert pexels.download(8, output_dir=tmp_path, min_width=2160, min_height=3840)['cached'] is False


def test_download_photo_original(website, files, tmp_path):
    routes, _ = website
    routes['https://www.pexels.com/photo/5/'] = {'medium': {'type': 'photo', 'id': '5', 'attributes': photo(5)}}
    out = pexels.download(5, kind='photo', output_dir=tmp_path)
    assert Path(out['path']).name == 'pexels-photo-5.jpeg' and 'duration' not in out


def test_download_rejects_non_pexels_media_host(website, tmp_path):
    routes, _ = website
    bad = video(9, files=[{'quality': 'hd', 'file_type': 'video/mp4', 'width': 720, 'height': 1280,
                           'link': 'https://evil.example/x.mp4'}])
    routes['https://www.pexels.com/video/9/'] = {'medium': {'type': 'video', 'id': '9', 'attributes': bad}}
    with pytest.raises(ValueError):
        pexels.download(9, output_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_search_and_download_without_credentials(website, files, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('PEXELS_API_KEY', raising=False)
    routes, calls = website
    url = 'https://www.pexels.com/search/videos/rain/?orientation=portrait'
    routes[url] = results_page('video', [video(1), video(2)], 4, pages=2)
    routes[url + '&page=2'] = results_page('video', [video(3), video(4)], 4, number=2, pages=2)
    assert pexels.main(['search', '--query', 'rain', '--page', '2', '--per-page', '3']) == 0
    result = json.loads(capsys.readouterr().out)
    assert [r['id'] for r in result['results']] == [4] and not result['has_next_page']
    assert pexels.main(['download', '--id', '4', '--output-dir', str(tmp_path)]) == 0
    assert Path(json.loads(capsys.readouterr().out)['path']).is_file()
    assert calls == [url, url + '&page=2']


def test_media_redirect_rejects_non_pexels_host():
    with pytest.raises(ValueError, match='non-Pexels'):
        pexels.MediaRedirect().redirect_request(None, None, 302, '', {}, 'https://example.org/asset.mp4')
