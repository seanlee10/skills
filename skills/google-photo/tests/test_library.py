import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gphoto import library
from gphoto.errors import Failure, MESSAGES, message_for
from gphoto.library import Filters

SEOUL = ZoneInfo('Asia/Seoul')
UTC = ZoneInfo('UTC')


def _item(create='2026-04-18T10:38:58.676Z', type='PHOTO', **meta):
    if not meta:
        meta = {'width': 4000, 'height': 3000, 'cameraMake': 'Apple', 'cameraModel': 'iPhone 15 Pro'}
    return {'id': 'abc', 'createTime': create, 'type': type,
            'mediaFile': {'filename': 'IMG_0001.jpg', 'mimeType': 'image/jpeg', 'mediaFileMetadata': meta}}


# ---- error codes -------------------------------------------------------------------------

def test_new_codes_have_messages():
    for code in ('UNSAFE_SUBJECT', 'UNKNOWN_TIME_ZONE', 'DATE_RANGE_OUTSIDE_YEAR', 'MANIFEST_CORRUPT'):
        assert message_for(code) == MESSAGES[code]
        assert 'http' not in MESSAGES[code] and '~' not in MESSAGES[code]


# ---- time zones and filters --------------------------------------------------------------

def test_new_year_uses_local_time():
    tz, _ = library.resolve_tz('Asia/Seoul')
    item = {'createTime': '2025-12-31T15:30:00Z', 'type': 'PHOTO',
            'mediaFile': {'mediaFileMetadata': {'width': 4000, 'height': 3000}}}
    assert library.filter_reason(item, Filters.for_year(2026), tz) is None
    assert library.filter_reason(item, Filters.for_year(2025), tz) == 'out_of_range'


def test_date_range_inclusive():
    f = Filters.for_year(2026, date_to=date(2026, 6, 30))
    # 2026-06-30 23:59 and 2026-07-01 00:00 in Seoul (UTC+9)
    assert library.filter_reason(_item('2026-06-30T14:59:00Z'), f, SEOUL) is None
    assert library.filter_reason(_item('2026-06-30T15:00:00Z'), f, SEOUL) == 'out_of_range'
    g = Filters.for_year(2026, date_from='2026-03-01')
    assert library.filter_reason(_item('2026-02-28T15:00:00Z'), g, SEOUL) is None  # 03-01 00:00 local
    assert library.filter_reason(_item('2026-02-28T14:59:59Z'), g, SEOUL) == 'out_of_range'


def test_local_time_formats():
    for stamp in ('2026-04-18T10:38:58Z', '2026-04-18T10:38:58.676Z',
                  '2026-04-18T10:38:58.676123Z', '2026-04-18T10:38:58.676123456Z'):
        t = library.local_time(stamp, SEOUL)
        assert t.tzinfo is not None
        assert (t.year, t.month, t.day, t.hour, t.minute, t.second) == (2026, 4, 18, 19, 38, 58)
    assert library.local_time('2026-04-18T10:38:58.676123456Z', UTC).microsecond == 676123
    with pytest.raises(Failure) as e:
        library.local_time('not a time', UTC)
    assert e.value.code == 'BAD_RESPONSE'


def test_type_camera_orientation_resolution():
    assert library.filter_reason(_item(type='VIDEO'), Filters.for_year(2026, type='photo'), UTC) == 'type'
    assert library.filter_reason(_item(type='PHOTO'), Filters.for_year(2026, type='video'), UTC) == 'type'
    assert library.filter_reason(_item(type='VIDEO'), Filters.for_year(2026, type='all'), UTC) is None
    assert library.filter_reason(_item(), Filters.for_year(2026, camera='pixel'), UTC) == 'camera'
    assert library.filter_reason(_item(), Filters.for_year(2026, camera='IPHONE 15'), UTC) is None
    assert library.filter_reason(_item(), Filters.for_year(2026, camera='apple iphone'), UTC) is None
    assert library.filter_reason(_item(), Filters.for_year(2026, orientation='portrait'), UTC) == 'orientation'
    assert library.filter_reason(_item(), Filters.for_year(2026, orientation='landscape'), UTC) is None
    tall = _item(width=3000, height=4000)
    assert library.filter_reason(tall, Filters.for_year(2026, orientation='portrait'), UTC) is None
    assert library.filter_reason(tall, Filters.for_year(2026, orientation='landscape'), UTC) == 'orientation'
    assert library.filter_reason(_item(), Filters.for_year(2026, min_side=3001), UTC) == 'resolution'
    assert library.filter_reason(_item(), Filters.for_year(2026, min_side=3000), UTC) is None


def test_reason_order():
    f = Filters.for_year(2026, type='video', camera='pixel', orientation='portrait', min_side=9999)
    assert library.filter_reason(_item('2025-01-01T00:00:00Z'), f, UTC) == 'out_of_range'
    assert library.filter_reason(_item(), f, UTC) == 'type'
    assert library.filter_reason(_item(type='VIDEO'), f, UTC) == 'camera'


def test_missing_metadata_is_filtered_only_when_filtered_on():
    bare = _item(type='VIDEO', fps=30)  # no width, height or camera (as live videos)
    assert library.filter_reason(bare, Filters.for_year(2026), UTC) is None
    assert library.filter_reason(bare, Filters.for_year(2026, camera='apple'), UTC) == 'camera'
    assert library.filter_reason(bare, Filters.for_year(2026, orientation='landscape'), UTC) == 'orientation'
    assert library.filter_reason(bare, Filters.for_year(2026, min_side=1), UTC) == 'resolution'
    no_file = {'id': 'x', 'createTime': '2026-01-02T00:00:00Z', 'type': 'PHOTO'}
    assert library.filter_reason(no_file, Filters.for_year(2026), UTC) is None
    assert library.filter_reason(no_file, Filters.for_year(2026, min_side=1), UTC) == 'resolution'
    undated = {'id': 'x', 'type': 'PHOTO'}
    assert library.filter_reason(undated, Filters.for_year(2026), UTC) == 'out_of_range'


def test_width_height_as_strings():
    # The API may serialise int64 fields as strings.
    item = _item(width='4000', height='3000')
    assert library.filter_reason(item, Filters.for_year(2026, orientation='landscape', min_side=3000), UTC) is None


def test_square_matches_no_orientation():
    square = _item(width=3000, height=3000)
    assert library.filter_reason(square, Filters.for_year(2026, orientation='portrait'), UTC) == 'orientation'
    assert library.filter_reason(square, Filters.for_year(2026, orientation='landscape'), UTC) == 'orientation'
    assert library.filter_reason(square, Filters.for_year(2026), UTC) is None


def test_date_range_outside_year():
    for kwargs in ({'date_from': date(2025, 12, 31)}, {'date_to': date(2027, 1, 1)},
                   {'date_from': '2026-05-01', 'date_to': '2026-04-30'}):
        with pytest.raises(Failure) as e:
            Filters.for_year(2026, **kwargs)
        assert e.value.code == 'DATE_RANGE_OUTSIDE_YEAR'


@pytest.mark.parametrize('kwargs', [{'type': 'gif'}, {'orientation': 'square'}, {'min_side': 0},
                                    {'date_from': '2026-13-01'}, {'camera': '  '}])
def test_filter_usage_errors(kwargs):
    with pytest.raises(Failure) as e:
        Filters.for_year(2026, **kwargs)
    assert e.value.code == 'USAGE_ERROR'


def test_filters_json_roundtrip():
    f = Filters.for_year(2026, date_from='2026-02-01', date_to=date(2026, 3, 1), type='photo',
                         camera='Pixel', orientation='portrait', min_side=1080)
    data = json.loads(json.dumps(f.to_json()))
    assert data['types'] == ['PHOTO'] and data['date_from'] == '2026-02-01'
    assert Filters.from_json(data) == f
    default = Filters.for_year(2026)
    assert default.types == frozenset({'PHOTO', 'VIDEO'})
    assert (default.date_from, default.date_to) == (date(2026, 1, 1), date(2026, 12, 31))
    assert Filters.from_json(default.to_json()) == default


def test_resolve_tz_explicit_and_env(monkeypatch):
    assert library.resolve_tz('Asia/Seoul') == (SEOUL, 'Asia/Seoul')
    monkeypatch.setenv('TZ', 'Europe/Berlin')
    assert library.resolve_tz(None) == (ZoneInfo('Europe/Berlin'), 'Europe/Berlin')
    monkeypatch.setenv('TZ', ':America/New_York')
    assert library.resolve_tz(None)[1] == 'America/New_York'
    with pytest.raises(Failure) as e:
        library.resolve_tz('Mars/Olympus')
    assert e.value.code == 'UNKNOWN_TIME_ZONE'
    for bad in ('../../etc/passwd', '/etc/localtime', ''):
        with pytest.raises(Failure) as e:
            library.resolve_tz(bad)
        assert e.value.code == 'UNKNOWN_TIME_ZONE'


def test_resolve_tz_localtime_symlink(monkeypatch, tmp_path):
    monkeypatch.delenv('TZ', raising=False)
    link = tmp_path / 'localtime'
    link.symlink_to('/var/db/timezone/zoneinfo/Asia/Seoul')  # target need not exist
    monkeypatch.setattr(library, '_LOCALTIME', link)
    assert library.resolve_tz(None) == (SEOUL, 'Asia/Seoul')


def test_resolve_tz_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv('TZ', raising=False)
    monkeypatch.setattr(library, '_LOCALTIME', tmp_path / 'missing')
    assert library.resolve_tz(None) == (UTC, 'UTC (fallback)')
    plain = tmp_path / 'plain'
    plain.write_bytes(b'TZif')  # a copied file, not a symlink: no name to read
    monkeypatch.setattr(library, '_LOCALTIME', plain)
    assert library.resolve_tz(None) == (UTC, 'UTC (fallback)')
    monkeypatch.setenv('TZ', 'Not/AZone')  # unusable TZ falls through to /etc/localtime
    assert library.resolve_tz(None) == (UTC, 'UTC (fallback)')


# ---- subject and folders -----------------------------------------------------------------

@pytest.mark.parametrize('bad', ['', '.', '..', 'a/b', 'a\\b', 'a\x01', 'x' * 101, '   ', 'a\x7fb', 'a\nb'])
def test_check_subject_rejects(bad):
    with pytest.raises(Failure) as e:
        library.check_subject(bad)
    assert e.value.code == 'UNSAFE_SUBJECT'


def test_check_subject_allows_unicode():
    assert library.check_subject('미아') == '미아'
    assert library.check_subject('Mia Park') == 'Mia Park'
    assert library.check_subject('  Mia Park  ') == 'Mia Park'
    assert library.check_subject('x' * 100) == 'x' * 100


def test_year_dir_creates_owned_folders(tmp_path):
    d = library.year_dir(tmp_path, 'Mia Park', 2026)
    assert d == tmp_path / 'Mia Park' / '2026'
    assert (d / 'media').is_dir() and (d / '.thumbs').is_dir()
    assert library.year_dir(tmp_path, 'Mia Park', 2026) == d  # idempotent
    with pytest.raises(Failure) as e:
        library.year_dir(tmp_path, '../x', 2026)
    assert e.value.code == 'UNSAFE_SUBJECT'


def test_year_dir_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    d = library.year_dir(library.DEFAULT_OUT_ROOT, 'kid', 2026)
    assert d == tmp_path / 'Pictures' / 'google-photo' / 'kid' / '2026'
    assert library.DEFAULT_OUT_ROOT == Path('~/Pictures/google-photo')


# ---- names -------------------------------------------------------------------------------

def test_unique_name_collisions(tmp_path):
    (tmp_path / 'IMG_0001.jpg').write_bytes(b'x')
    used = set()
    a = library.unique_name(tmp_path, 'IMG_0001.jpg', used); used.add(a)
    b = library.unique_name(tmp_path, 'IMG_0001.jpg', used)
    assert (a, b) == ('IMG_0001_2.jpg', 'IMG_0001_3.jpg')
    assert library.unique_name(tmp_path, 'fresh.mp4', set()) == 'fresh.mp4'


def test_unique_name_case_insensitive(tmp_path):
    # Default macOS volumes are case-insensitive: IMG.JPG and img.jpg are the same file.
    assert library.unique_name(tmp_path, 'img.jpg', {'IMG.JPG'}) == 'img_2.jpg'


def test_unique_name_unicode_normalisation(tmp_path):
    # APFS treats NFC and NFD spellings as one file name (Korean names arrive in either form).
    import unicodedata
    nfc = unicodedata.normalize('NFC', '미아.jpg')
    nfd = unicodedata.normalize('NFD', nfc)
    assert nfc != nfd
    assert library.unique_name(tmp_path, nfd, {nfc}) == unicodedata.normalize('NFD', '미아_2.jpg')
    assert library.unique_name(tmp_path, nfc, {nfd.upper()}) == '미아_2.jpg'


def test_unique_name_dangling_symlink_counts(tmp_path):
    (tmp_path / 'a.jpg').symlink_to(tmp_path / 'nowhere')
    assert library.unique_name(tmp_path, 'a.jpg', set()) == 'a_2.jpg'


def test_unique_name_strips_paths(tmp_path):
    assert library.unique_name(tmp_path, '../../etc/passwd', set()) == 'passwd'
    assert library.unique_name(tmp_path, '..\\..\\win.ini', set()) == 'win.ini'
    assert library.unique_name(tmp_path, 'a\x00b.jpg', set()) == 'a_b.jpg'
    assert library.unique_name(tmp_path, '', set()) == 'item'
    assert library.unique_name(tmp_path, '..', set()) == 'item'
    assert library.unique_name(tmp_path, 'dir/', set()) == 'item'
    long = library.unique_name(tmp_path, '가' * 200 + '.jpg', set())
    assert long.endswith('.jpg') and len(long.encode()) <= 255


def test_thumb_name():
    name = library.thumb_name('AF1Qip/../x')
    assert name.endswith('.jpg') and len(name) == 20 and '/' not in name
    assert name == library.thumb_name('AF1Qip/../x')
    assert name != library.thumb_name('AF1Qip/../y')


# ---- manifest ----------------------------------------------------------------------------

def _entry():
    return {'file': 'media/IMG_0001.jpg', 'filename': 'IMG_0001.jpg', 'type': 'PHOTO', 'mime': 'image/jpeg',
            'create_time': '2026-04-18T10:38:58.676Z', 'local_time': '2026-04-18T19:38:58.676000+09:00',
            'width': 4000, 'height': 3000, 'camera_make': 'Apple', 'camera_model': 'iPhone 15 Pro',
            'fps': None, 'thumb': '.thumbs/0123456789abcdef.jpg', 'session': 's1'}


def test_manifest_missing_is_empty(tmp_path):
    assert library.load_manifest(tmp_path) == {'version': 1, 'items': {}}


def test_manifest_roundtrip_atomic(tmp_path):
    m = {'version': 1, 'subject': '미아', 'year': 2026, 'tz': 'Asia/Seoul', 'items': {'abc': _entry()}}
    library.save_manifest(tmp_path, m)
    assert library.load_manifest(tmp_path) == m
    assert sorted(p.name for p in tmp_path.iterdir()) == ['manifest.json']
    assert '미아' in (tmp_path / 'manifest.json').read_text(encoding='utf-8')
    m['items']['def'] = _entry()
    library.save_manifest(tmp_path, m)
    assert library.load_manifest(tmp_path) == m
    assert sorted(p.name for p in tmp_path.iterdir()) == ['manifest.json']


def test_manifest_save_failure_leaves_old_file(tmp_path, monkeypatch):
    m = {'version': 1, 'subject': 's', 'year': 2026, 'tz': 'UTC', 'items': {}}
    library.save_manifest(tmp_path, m)

    def boom(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(library.os, 'replace', boom)
    with pytest.raises(OSError):
        library.save_manifest(tmp_path, {**m, 'items': {'abc': _entry()}})
    assert library.load_manifest(tmp_path) == m
    assert sorted(p.name for p in tmp_path.iterdir()) == ['manifest.json']


@pytest.mark.parametrize('content', [b'{', b'[]', b'\xff\xfe', b'{"version": 2, "items": {}}',
                                     b'{"version": 1, "items": []}', b'{"version": 1}'])
def test_manifest_corrupt(tmp_path, content):
    (tmp_path / 'manifest.json').write_bytes(content)
    with pytest.raises(Failure) as e:
        library.load_manifest(tmp_path)
    assert e.value.code == 'MANIFEST_CORRUPT'


def test_manifest_unreadable(tmp_path):
    (tmp_path / 'manifest.json').mkdir()  # exists but cannot be read as a file
    with pytest.raises(Failure) as e:
        library.load_manifest(tmp_path)
    assert e.value.code == 'MANIFEST_CORRUPT'
