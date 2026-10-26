# /// script
# requires-python = "==3.11.*"
# dependencies = []
# ///
"""Search Pexels videos and photos and download one file by ID (stdlib only). Print JSON to stdout.

Usage: uv run pexels.py search --query TEXT [--type video|photo] [--orientation portrait|landscape|square|any]
                               [--min-duration S] [--max-duration S] [--min-width PX] [--min-height PX]
                               [--per-page N] [--page N]
       uv run pexels.py download --id N [--type video|photo] [--min-width PX] [--min-height PX]
                                 [--output-dir DIR] [--force]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.pexels.com'
USER_AGENT = 'seanlee10-skills-pexels-search/0.1'
LICENSE = 'Pexels License: free to use, attribution appreciated; see https://www.pexels.com/license/'
DEFAULT_OUTPUT = Path('~/Downloads/pexels').expanduser()
TIMEOUT = 60
MAX_RETRY_WAIT = 60


def fetch_json(url, key):
    request = urllib.request.Request(url, headers={'Authorization': key, 'User-Agent': USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt == 0:
                wait = error.headers.get('Retry-After', '5')
                time.sleep(min(int(wait) if wait.isdigit() else 5, MAX_RETRY_WAIT))
                continue
            if error.code == 401:
                raise ValueError('Pexels rejected the API key (HTTP 401). Check PEXELS_API_KEY.') from None
            if error.code == 404:
                raise ValueError('Pexels has no item with that ID (HTTP 404).') from None
            if error.code == 429:
                raise ValueError('Pexels rate limit reached (HTTP 429). Try again later.') from None
            raise ValueError(f'Pexels API error: HTTP {error.code}') from None


def fetch_file(url, target):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(target, 'wb') as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)


def check_media_url(url):
    parsed = urllib.parse.urlparse(url or '')
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or not (host == 'pexels.com' or host.endswith('.pexels.com')):
        raise ValueError(f'Refusing to download from a non-Pexels URL: {url}')


def video_files(item):
    files = [f for f in item.get('video_files', [])
             if f.get('file_type') == 'video/mp4' and f.get('width') and f.get('height') and f.get('link')]
    return sorted(files, key=lambda f: (f['width'] * f['height'], f.get('fps') or 0))


def summarize(item, kind):
    if kind == 'video':
        return {'id': item['id'], 'type': 'video', 'width': item['width'], 'height': item['height'],
                'duration': item['duration'], 'url': item['url'], 'preview_image': item.get('image'),
                'author': item['user']['name'], 'author_url': item['user']['url'],
                'files': [{key: f.get(key) for key in ('quality', 'width', 'height', 'fps')}
                          for f in video_files(item)]}
    return {'id': item['id'], 'type': 'photo', 'width': item['width'], 'height': item['height'],
            'url': item['url'], 'preview_image': item['src'].get('medium'), 'author': item['photographer'],
            'author_url': item['photographer_url'], 'alt': item.get('alt'), 'avg_color': item.get('avg_color')}


def search(query, key, kind='video', orientation='portrait', min_duration=None, max_duration=None,
           min_width=None, min_height=None, per_page=15, page=1):
    if not query.strip():
        raise ValueError('Provide a non-empty --query')
    if not 1 <= per_page <= 80:
        raise ValueError('--per-page must be between 1 and 80')
    if page < 1:
        raise ValueError('--page must be 1 or more')
    if kind == 'photo' and (min_duration or max_duration):
        raise ValueError('Duration filters apply to videos only')
    params = {'query': query.strip(), 'per_page': per_page, 'page': page}
    if orientation != 'any':
        params['orientation'] = orientation
    path = '/videos/search' if kind == 'video' else '/v1/search'
    data = fetch_json(f'{API}{path}?{urllib.parse.urlencode(params)}', key)
    items = data.get('videos' if kind == 'video' else 'photos', [])

    def keep(item):
        return ((not min_width or item['width'] >= min_width)
                and (not min_height or item['height'] >= min_height)
                and (not min_duration or item['duration'] >= min_duration)
                and (not max_duration or item['duration'] <= max_duration))

    results = [summarize(item, kind) for item in items if keep(item)]
    return {'query': params['query'], 'type': kind, 'orientation': orientation, 'page': page,
            'per_page': per_page, 'total_results': data.get('total_results'),
            'has_next_page': bool(data.get('next_page')), 'returned': len(results),
            'filtered_out': len(items) - len(results), 'results': results}


def choose_video_file(item, min_width, min_height):
    files = video_files(item)
    if not files:
        raise ValueError(f'Video {item["id"]} has no downloadable MP4 file')
    fitting = [f for f in files if f['width'] >= min_width and f['height'] >= min_height]
    return (fitting[0], True) if fitting else (files[-1], False)


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def download(item_id, key, kind='video', min_width=720, min_height=1280, output_dir=DEFAULT_OUTPUT, force=False):
    path = f'/videos/videos/{int(item_id)}' if kind == 'video' else f'/v1/photos/{int(item_id)}'
    item = fetch_json(API + path, key)
    if kind == 'video':
        chosen, meets = choose_video_file(item, min_width, min_height)
        link, width, height, suffix = chosen['link'], chosen['width'], chosen['height'], '.mp4'
    else:
        link, width, height = item['src']['original'], item['width'], item['height']
        meets = width >= min_width and height >= min_height
        suffix = Path(urllib.parse.urlparse(link).path).suffix.lower() or '.jpg'
    check_media_url(link)

    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f'pexels-{kind}-{item["id"]}{suffix}'
    sidecar = output_dir / f'pexels-{kind}-{item["id"]}.source.json'
    info = summarize(item, kind)
    record = {'id': item['id'], 'type': kind, 'url': info['url'], 'author': info['author'],
              'author_url': info['author_url'], 'file_url': link, 'width': width, 'height': height,
              'meets_minimum': meets, 'license': LICENSE}
    if kind == 'video':
        record['duration'] = item['duration']

    if not force and target.is_file() and sidecar.is_file():
        try:
            previous = json.loads(sidecar.read_text(encoding='utf-8'))
        except ValueError:
            previous = {}
        if previous.get('file_url') == link and previous.get('sha256') == file_hash(target):
            return {'path': str(target), **record, 'sha256': previous['sha256'], 'size_bytes': target.stat().st_size,
                    'cached': True}

    handle, temporary = tempfile.mkstemp(dir=output_dir, prefix='.pexels-', suffix=suffix)
    os.close(handle)
    try:
        fetch_file(link, temporary)
        if os.path.getsize(temporary) == 0:
            raise ValueError(f'Pexels returned an empty file for {kind} {item["id"]}')
        record['sha256'] = file_hash(temporary)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'path': str(target), **record, 'size_bytes': target.stat().st_size, 'cached': False}


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    find = commands.add_parser('search')
    find.add_argument('--query', required=True)
    find.add_argument('--type', choices=('video', 'photo'), default='video')
    find.add_argument('--orientation', choices=('portrait', 'landscape', 'square', 'any'), default='portrait')
    find.add_argument('--min-duration', type=int)
    find.add_argument('--max-duration', type=int)
    find.add_argument('--min-width', type=int)
    find.add_argument('--min-height', type=int)
    find.add_argument('--per-page', type=int, default=15)
    find.add_argument('--page', type=int, default=1)
    save = commands.add_parser('download')
    save.add_argument('--id', type=int, required=True)
    save.add_argument('--type', choices=('video', 'photo'), default='video')
    save.add_argument('--min-width', type=int, default=720)
    save.add_argument('--min-height', type=int, default=1280)
    save.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    save.add_argument('--force', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    key = os.environ.get('PEXELS_API_KEY', '').strip()
    if not key:
        print('error: set PEXELS_API_KEY (free key from https://www.pexels.com/api/).', file=sys.stderr)
        return 1
    try:
        if args.command == 'search':
            result = search(args.query, key, args.type, args.orientation, args.min_duration, args.max_duration,
                            args.min_width, args.min_height, args.per_page, args.page)
        else:
            result = download(args.id, key, args.type, args.min_width, args.min_height, args.output_dir, args.force)
    except (ValueError, OSError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
