# /// script
# requires-python = "==3.11.*"
# dependencies = ["playwright==1.65.0"]
# ///
"""Search Pexels videos and photos and download one file by ID using the public website. Print JSON to stdout.

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
import urllib.parse
import urllib.request

SITE = 'https://www.pexels.com'
CACHE = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'pexels-search'
USER_AGENT = 'seanlee10-skills-pexels-search/0.1'
LICENSE = 'Pexels License: free to use, attribution appreciated; see https://www.pexels.com/license/'
DEFAULT_OUTPUT = Path('~/Downloads/pexels').expanduser()
TIMEOUT = 60
CACHE_SECONDS = 86400


def page_props(url):
    """Read media metadata published with the public page in an isolated Chrome window."""
    from playwright.sync_api import Error, sync_playwright

    try:
        with sync_playwright() as playwright, playwright.chromium.launch(channel='chrome', headless=False) as browser:
            page = browser.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=TIMEOUT * 1000)
            if response and response.status == 429:
                after = response.headers.get('retry-after', '5')
                if after.isdigit() and int(after) <= TIMEOUT:
                    time.sleep(int(after))
                    response = page.reload(wait_until='domcontentloaded', timeout=TIMEOUT * 1000)
            if response is None or not response.ok:
                status = response.status if response else 'no response'
                raise ValueError(f'Pexels returned {status}. Open the public page in your browser: {url}')
            data = page.locator('script#__NEXT_DATA__')
            if not data.count():
                raise ValueError(f'Pexels page metadata is unavailable: {url}')
            return data.evaluate("""node => {
                const {initialData, medium} = JSON.parse(node.textContent).props.pageProps;
                return {initialData, medium};
            }""")
    except Error as exc:
        raise ValueError(f'Could not open the Pexels page in desktop Google Chrome: {url} ({exc})') from None


def website_item(attrs, kind):
    person = attrs['user']
    name = ' '.join(filter(None, [person.get('first_name'), person.get('last_name')])) or person['slug']
    item_id = int(attrs['id'])
    slug = attrs.get('slug')
    item = {'id': item_id, 'width': attrs['width'], 'height': attrs['height'],
            'url': f"{SITE}/{kind}/{slug + '-' if slug else ''}{item_id}/"}
    profile = f"{SITE}/@{person['slug']}/"
    if kind == 'video':
        video = attrs['video']
        item.update(duration=attrs['duration'], image=video['thumbnail'].get('medium'),
                    user={'name': name, 'url': profile}, video_files=video['video_files'])
    else:
        image = attrs['image']
        rgb = attrs.get('main_color')
        color = '#%02x%02x%02x' % tuple(rgb) if isinstance(rgb, list) and len(rgb) == 3 else rgb
        item.update(photographer=name, photographer_url=profile, alt=attrs.get('alt') or attrs.get('description'),
                    avg_color=color, src={'medium': image.get('medium'), 'original': image['download_link']})
    return item


def write_json(path, value):
    handle, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.write('\n')
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def item_by_id(item_id, kind):
    cache = CACHE / f'{kind}-{item_id}.json'
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        try:
            item = json.loads(cache.read_text(encoding='utf-8'))
            if item['id'] == item_id:
                return item
        except (KeyError, ValueError, TypeError):
            pass
    url = f'{SITE}/{kind}/{item_id}/'
    props = page_props(url)
    medium = props.get('medium') or {}
    if medium.get('type') == kind and str(medium.get('id')) == str(item_id):
        return website_item(medium['attributes'], kind)
    raise ValueError(f'No matching {kind} metadata on {url}. Open the item in the browser to download it.')


class MediaRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_file(url, target):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    opener = urllib.request.build_opener(MediaRedirect())
    with opener.open(request, timeout=TIMEOUT) as response, open(target, 'wb') as out:
        if response.headers.get_content_type() == 'text/html':
            raise ValueError('Pexels returned a web page instead of the selected media')
        while chunk := response.read(1 << 20):
            out.write(chunk)


def check_media_url(url):
    parsed = urllib.parse.urlparse(url or '')
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username is not None or not (host == 'pexels.com' or host.endswith('.pexels.com')):
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


def search(query, kind='video', orientation='portrait', min_duration=None, max_duration=None,
           min_width=None, min_height=None, per_page=15, page=1):
    if not query.strip():
        raise ValueError('Provide a non-empty --query')
    if not 1 <= per_page <= 80:
        raise ValueError('--per-page must be between 1 and 80')
    if page < 1:
        raise ValueError('--page must be 1 or more')
    if kind == 'photo' and (min_duration or max_duration):
        raise ValueError('Duration filters apply to videos only')
    section = 'search/videos' if kind == 'video' else 'search'
    term = urllib.parse.quote(query.strip(), safe='')
    url = f'{SITE}/{section}/{term}/'
    params = {'orientation': orientation} if orientation != 'any' else {}

    def get_page(number):
        options = dict(params)
        if number > 1:
            options['page'] = number
        page_url = url + ('?' + urllib.parse.urlencode(options) if options else '')
        data = page_props(page_url).get('initialData')
        if not isinstance(data, dict) or not isinstance(data.get('data'), list):
            raise ValueError(f'No search results metadata on {page_url}')
        return data

    data = get_page(1)
    pagination = data['pagination']
    total = pagination['total_results']
    start = (page - 1) * per_page
    end = min(start + per_page, total)
    site_size = len(data['data'])
    items = []
    if site_size and start < end:
        first = start // site_size
        last = min((end - 1) // site_size, pagination['total_pages'] - 1)
        for index in range(first, last + 1):
            if index:
                data = get_page(index + 1)
                if data['pagination']['current_page'] != index + 1:
                    raise ValueError('Pexels returned a different results page than requested')
            base = index * site_size
            rows = data['data'][max(0, start - base):end - base]
            items.extend(website_item(row['attributes'], kind) for row in rows if row['type'] == kind)

    def keep(item):
        width, height = item['width'], item['height']
        shape = 'square' if width == height else ('portrait' if width < height else 'landscape')
        return (orientation in ('any', shape)
                and (not min_width or item['width'] >= min_width)
                and (not min_height or item['height'] >= min_height)
                and (not min_duration or item['duration'] >= min_duration)
                and (not max_duration or item['duration'] <= max_duration))

    matches = [item for item in items if keep(item)]
    if matches:
        CACHE.mkdir(parents=True, exist_ok=True)
    for item in matches:
        write_json(CACHE / f"{kind}-{item['id']}.json", item)
    results = [summarize(item, kind) for item in matches]
    return {'query': query.strip(), 'type': kind, 'orientation': orientation, 'page': page,
            'per_page': per_page, 'total_results': total,
            'has_next_page': start + per_page < total, 'returned': len(results),
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


def download(item_id, kind='video', min_width=720, min_height=1280, output_dir=DEFAULT_OUTPUT, force=False):
    item = item_by_id(int(item_id), kind)
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
    write_json(sidecar, record)
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
    try:
        if args.command == 'search':
            result = search(args.query, args.type, args.orientation, args.min_duration, args.max_duration,
                            args.min_width, args.min_height, args.per_page, args.page)
        else:
            result = download(args.id, args.type, args.min_width, args.min_height, args.output_dir, args.force)
    except KeyError as error:
        print(f'error: missing field on the public Pexels page: {error}', file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
