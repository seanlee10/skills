import json
import os
import random
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from gphoto import config, curate
from gphoto.errors import MESSAGES, message_for

T0 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone(timedelta(hours=9)))


# ---- synthetic images --------------------------------------------------------------------

def checkerboard(size=256, cell=16):
    img = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(img)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if (x // cell + y // cell) % 2 == 0:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=255)
    return img.convert('RGB')


def scene(seed, size=128):
    """A random but deterministic picture: coloured rectangles on a mid-grey ground."""
    rnd = random.Random(seed)
    img = Image.new('RGB', (size, size), (128, 128, 128))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rnd.randrange(size), rnd.randrange(size)
        x1, y1 = x0 + rnd.randrange(8, size // 2), y0 + rnd.randrange(8, size // 2)
        d.rectangle([x0, y0, x1, y1], fill=tuple(rnd.randrange(60, 256) for _ in range(3)))
    return img


def save(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, 'JPEG', quality=95)
    return path


def photo_entry(i, when, dhash=0, sharpness=100.0, brightness=128.0):
    return {'id': f'p{i}', 'file': f'media/p{i}.jpg', 'type': 'PHOTO', 'local_time': when.isoformat(),
            'dhash': dhash, 'sharpness': sharpness, 'brightness': brightness}


def video_entry(i, when):
    return {'id': f'v{i}', 'file': f'media/v{i}.mp4', 'type': 'VIDEO', 'local_time': when.isoformat()}


def flip_bits(value, n):
    """`value` with its lowest `n` bits flipped (hamming distance n)."""
    return value ^ ((1 << n) - 1)


# ---- features ----------------------------------------------------------------------------

def test_constants():
    assert (curate.BURST_GAP_S, curate.BURST_HAMMING, curate.DUP_HAMMING) == (20, 12, 5)
    assert (curate.BLUR_RATIO, curate.DARK_LUMA, curate.CANDIDATE_FACTOR) == (0.35, 40, 4)
    assert (curate.VIDEO_CAP, curate.TILE, curate.GRID) == (30, 256, (5, 4))
    assert (curate.DEFAULT_TARGET, curate.DEFAULT_VIDEO_TARGET) == (75, 8)


def test_hamming():
    assert curate.hamming(0, 0) == 0
    assert curate.hamming(0b1011, 0b0001) == 2
    assert curate.hamming(0, (1 << 64) - 1) == 64


def test_features_sharp_vs_blurred(tmp_path):
    sharp = save(checkerboard(), tmp_path / 'sharp.jpg')
    blurred = save(checkerboard().filter(ImageFilter.GaussianBlur(4)), tmp_path / 'blur.jpg')
    fs, fb = curate.features(sharp), curate.features(blurred)
    assert set(fs) == {'dhash', 'sharpness', 'brightness'}
    assert isinstance(fs['dhash'], int) and 0 <= fs['dhash'] < 1 << 64
    assert fs['sharpness'] > 5 * fb['sharpness']
    assert 100 < fs['brightness'] < 160


def test_features_dark(tmp_path):
    f = curate.features(save(Image.new('RGB', (64, 64), (0, 0, 0)), tmp_path / 'black.jpg'))
    assert f['brightness'] < curate.DARK_LUMA


def test_features_same_scene_same_hash(tmp_path):
    a = curate.features(save(scene(1), tmp_path / 'a.jpg'))
    b = curate.features(save(scene(1).resize((200, 200)), tmp_path / 'b.jpg'))
    c = curate.features(save(scene(2), tmp_path / 'c.jpg'))
    assert curate.hamming(a['dhash'], b['dhash']) <= curate.DUP_HAMMING
    assert curate.hamming(a['dhash'], c['dhash']) > curate.BURST_HAMMING


def test_features_undecodable_raises(tmp_path):
    bad = tmp_path / 'x.jpg'
    bad.write_bytes(b'not an image at all')
    with pytest.raises(curate.Undecodable):
        curate.features(bad)


def test_features_decompression_bomb_is_undecodable(tmp_path, monkeypatch):
    path = save(Image.new('RGB', (100, 100), (90, 90, 90)), tmp_path / 'big.jpg')
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 6000)  # 10 000 px: Pillow's warning band, made an error
    with pytest.raises(curate.Undecodable):
        curate.features(path)


# ---- shortlist ---------------------------------------------------------------------------

def test_burst_keeps_sharpest():
    entries = [photo_entry(i, T0 + timedelta(seconds=2 * i), dhash=flip_bits(0xABCDEF, i),
                           sharpness=50.0 + (40 if i == 3 else i)) for i in range(5)]
    cands, dropped = curate.shortlist(entries, target=10, video_target=0)
    assert [c['id'] for c in cands] == ['p3']
    assert cands[0]['group_size'] == 5
    assert dropped['near_duplicate'] == 4


def test_far_apart_similar_kept_unless_identical():
    base = 0x0F0F0F0F0F0F0F0F
    two_h = [photo_entry(0, T0, dhash=base), photo_entry(1, T0 + timedelta(hours=2), dhash=flip_bits(base, 8))]
    cands, dropped = curate.shortlist(two_h, target=10, video_target=0)
    assert len(cands) == 2 and dropped['near_duplicate'] == 0
    same = [photo_entry(0, T0, dhash=base), photo_entry(1, T0 + timedelta(hours=2), dhash=base, sharpness=200)]
    cands, dropped = curate.shortlist(same, target=10, video_target=0)
    assert [c['id'] for c in cands] == ['p1'] and dropped['near_duplicate'] == 1


def test_burst_needs_both_time_and_similarity():
    base = 0
    close_different = [photo_entry(0, T0, dhash=base),
                       photo_entry(1, T0 + timedelta(seconds=3), dhash=flip_bits(base, 30))]
    assert len(curate.shortlist(close_different, 10, 0)[0]) == 2
    slow_similar = [photo_entry(0, T0, dhash=base),
                    photo_entry(1, T0 + timedelta(seconds=21), dhash=flip_bits(base, 10))]
    assert len(curate.shortlist(slow_similar, 10, 0)[0]) == 2


def distinct_hash(i):
    """Hashes far apart from each other (pairwise hamming > DUP_HAMMING)."""
    return random.Random(i).getrandbits(64)


def test_blurry_and_dark_dropped():
    entries = [photo_entry(i, T0 + timedelta(minutes=i), dhash=distinct_hash(i), sharpness=100.0)
               for i in range(6)]
    entries[1]['sharpness'] = 20.0          # < 0.35 * median 100
    entries[2]['brightness'] = 10.0         # < DARK_LUMA
    entries[3]['sharpness'] = 40.0          # >= 35: kept
    cands, dropped = curate.shortlist(entries, 10, 0)
    assert sorted(c['id'] for c in cands) == ['p0', 'p3', 'p4', 'p5']
    assert dropped['blurry'] == 1 and dropped['dark'] == 1


def test_month_balance():
    entries = []
    for i in range(200):
        entries.append(photo_entry(i, datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(hours=3 * i),
                                   dhash=distinct_hash(i), sharpness=100.0 + i))
    for m, month in enumerate((1, 6, 9)):
        for j in range(10):
            i = 1000 + 10 * m + j
            entries.append(photo_entry(i, datetime(2026, month, 2 + j, tzinfo=timezone.utc),
                                       dhash=distinct_hash(i), sharpness=100.0))
    cands, dropped = curate.shortlist(entries, target=10, video_target=0)
    assert len(cands) == 40 and dropped['month_cap'] == 230 - 40
    months = {}
    for c in cands:
        months.setdefault(c['local_time'][:7], []).append(c)
    assert set(months) == {'2026-01', '2026-03', '2026-06', '2026-09'}
    # one slot per month first, then the other 36 by sqrt: March 36 * 14.14 / 23.63 = 21.5,
    # others 4.82 each -> floors 21/4/4/4, the 3 left go to the larger remainders (.82 > .54)
    assert len(months['2026-03']) == 1 + 21
    assert sorted(len(months[m]) for m in ('2026-01', '2026-06', '2026-09')) == [6, 6, 6]
    march = sorted(c['sharpness'] for c in months['2026-03'])
    assert march[0] == 100.0 + 200 - 22  # sharpest first within a month


def test_allocate_never_starves_a_month():
    counts = {'2026-03': 3000, **{f'2026-{m:02d}': 1 for m in (1, 2, 5, 7, 9, 11)}}
    quota = curate._allocate(counts, 40)
    assert sum(quota.values()) == 40 and all(quota[m] >= 1 for m in counts)
    assert quota['2026-03'] == 34
    quota = curate._allocate({'03': 10000, '01': 1, '05': 1, '08': 1, '10': 1}, 20)
    assert quota == {'03': 16, '01': 1, '05': 1, '08': 1, '10': 1}


def test_allocate_properties():
    rnd = random.Random(7)
    for _ in range(300):
        counts = {f'm{i}': rnd.choice([1, 1, 2, 5, 30, 400, 5000]) for i in range(rnd.randint(1, 12))}
        cap = rnd.randint(0, 120)
        quota = curate._allocate(counts, cap)
        assert set(quota) == set(counts)
        assert sum(quota.values()) == min(cap, sum(counts.values()))
        assert all(0 <= quota[m] <= counts[m] for m in counts)
        if len(counts) <= cap:
            assert all(quota[m] >= 1 for m in counts)


def test_month_floor_in_shortlist():
    entries = [photo_entry(i, datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                           dhash=distinct_hash(i)) for i in range(300)]
    for m in (1, 2, 5, 7, 9, 11):
        entries.append(photo_entry(1000 + m, datetime(2026, m, 15, tzinfo=timezone.utc),
                                   dhash=distinct_hash(1000 + m)))
    cands, _ = curate.shortlist(entries, target=10, video_target=0)
    assert len(cands) == 40
    assert {c['local_time'][:7] for c in cands} == {f'2026-{m:02d}' for m in (1, 2, 3, 5, 7, 9, 11)}


def test_small_month_keeps_all_when_its_share_exceeds_it():
    entries = [photo_entry(i, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                           dhash=distinct_hash(i)) for i in range(100)]
    entries.append(photo_entry(500, datetime(2026, 2, 1, tzinfo=timezone.utc), dhash=distinct_hash(500)))
    cands, _ = curate.shortlist(entries, target=5, video_target=0)
    assert len(cands) == 20 and 'p500' in {c['id'] for c in cands}


def test_videos_capped_and_spread():
    videos = []
    for i in range(50):
        month = 1 + i % 5 if i < 45 else 12
        videos.append(video_entry(i, datetime(2026, month, 1 + i // 5, tzinfo=timezone.utc)))
    cands, dropped = curate.shortlist(videos, target=10, video_target=8)
    assert len(cands) == curate.VIDEO_CAP and dropped['video_cap'] == 20
    assert {c['local_time'][:7] for c in cands} == {f'2026-{m:02d}' for m in (1, 2, 3, 4, 5, 12)}
    assert all(c['type'] == 'VIDEO' and c['group_size'] == 1 for c in cands)


def test_refs_in_time_order():
    entries = [photo_entry(0, T0 + timedelta(days=3), dhash=distinct_hash(0)),
               video_entry(1, T0 + timedelta(days=5)),
               photo_entry(2, T0, dhash=distinct_hash(2)),
               video_entry(3, T0 + timedelta(days=1)),
               photo_entry(4, T0 + timedelta(days=1), dhash=distinct_hash(4))]
    cands, _ = curate.shortlist(entries, 10, 8)
    refs = {c['ref']: c['id'] for c in cands}
    assert refs == {'C001': 'p2', 'C002': 'p4', 'C003': 'p0', 'V001': 'v3', 'V002': 'v1'}
    assert [c['ref'] for c in cands] == ['C001', 'C002', 'C003', 'V001', 'V002']


# ---- contact sheets ----------------------------------------------------------------------

def sheet_candidates(tmp_path, n_photos, n_videos=0):
    out = []
    for i in range(n_photos):
        out.append({'ref': f'C{i + 1:03d}', 'type': 'PHOTO', 'local_time': (T0 + timedelta(hours=i)).isoformat(),
                    'image': save(scene(i, 300 if i % 2 else 120), tmp_path / f'p{i}.jpg')})
    for i in range(n_videos):
        out.append({'ref': f'V{i + 1:03d}', 'type': 'VIDEO', 'local_time': T0.isoformat(),
                    'image': save(scene(100 + i), tmp_path / f'vt{i}.jpg'), 'video': tmp_path / f'v{i}.mp4'})
    return out


def test_contact_sheets_layout(tmp_path):
    sheets_dir = tmp_path / 'curation' / 'sheets'
    paths = curate.contact_sheets(sheet_candidates(tmp_path, 23), sheets_dir, ffmpeg=None)
    assert [p.name for p in paths] == ['sheet-01.jpg', 'sheet-02.jpg']
    for p in paths:
        with Image.open(p) as img:
            assert img.format == 'JPEG'
            assert img.width <= 5 * curate.TILE
            assert img.height <= 4 * (curate.TILE + curate.LABEL_H)
    with Image.open(paths[1]) as img:  # 3 tiles on the last sheet: one row
        assert img.height == curate.TILE + curate.LABEL_H


def test_contact_sheets_remove_stale(tmp_path):
    sheets_dir = tmp_path / 'sheets'
    curate.contact_sheets(sheet_candidates(tmp_path, 45), sheets_dir, ffmpeg=None)
    assert len(list(sheets_dir.glob('sheet-*.jpg'))) == 3
    (sheets_dir / 'notes.txt').write_text('mine')
    paths = curate.contact_sheets(sheet_candidates(tmp_path, 4), sheets_dir, ffmpeg=None)
    assert sorted(p.name for p in sheets_dir.iterdir()) == ['notes.txt', 'sheet-01.jpg']
    assert paths == [sheets_dir / 'sheet-01.jpg']


def test_contact_sheets_without_ffmpeg(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError('no subprocess without ffmpeg')
    monkeypatch.setattr(curate.subprocess, 'run', boom)
    warnings = []
    paths = curate.contact_sheets(sheet_candidates(tmp_path, 2, 2), tmp_path / 's', ffmpeg=None,
                                  warnings=warnings)
    assert len(paths) == 1 and warnings == []


def fake_tools(tmp_path, frame_ok=True):
    """Fake ffprobe/ffmpeg executables: they log their argv and print a duration / a JPEG frame."""
    frame = tmp_path / 'frame.jpg'
    save(Image.new('RGB', (64, 36), (200, 30, 30)), frame)
    log = tmp_path / 'argv.log'
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    probe = bindir / 'ffprobe'
    probe.write_text('#!/bin/sh\n'
                     f'printf "%s\\n" "ffprobe $*" >> "{log}"\n'
                     'echo 12.5\n')
    body = f'cat "{frame}"\n' if frame_ok else 'exit 1\n'
    mpeg = bindir / 'ffmpeg'
    mpeg.write_text('#!/bin/sh\n'
                    f'printf "%s\\n" "ffmpeg $*" >> "{log}"\n' + body)
    for p in (probe, mpeg):
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(mpeg), str(probe), log


def test_contact_sheets_ffmpeg_frames(tmp_path):
    ffmpeg, ffprobe, log = fake_tools(tmp_path)
    cands = sheet_candidates(tmp_path, 1, 1)
    video = cands[1]['video'] = tmp_path / '-v0.mp4'  # a name that looks like an option
    video.write_bytes(b'\0')
    warnings = []
    curate.contact_sheets(cands, tmp_path / 's', ffmpeg=ffmpeg, ffprobe=ffprobe, warnings=warnings)
    lines = log.read_text().splitlines()
    assert warnings == []
    assert len([ln for ln in lines if ln.startswith('ffprobe ')]) == 1
    calls = [ln for ln in lines if ln.startswith('ffmpeg ')]
    assert len(calls) == 4
    seeks = [float(ln.split('-ss ')[1].split()[0]) for ln in calls]
    assert seeks == pytest.approx([1.25, 4.375, 7.5, 10.625])
    for ln in lines:
        assert f'file:{video.resolve()}' in ln and ' -v0.mp4' not in ln.replace(f'file:{video.resolve()}', '')
    assert all('-nostdin' in ln for ln in calls)


def test_contact_sheets_ffmpeg_failure_falls_back(tmp_path):
    ffmpeg, ffprobe, _ = fake_tools(tmp_path, frame_ok=False)
    cands = sheet_candidates(tmp_path, 0, 1)
    cands[0]['video'].write_bytes(b'\0')
    warnings = []
    paths = curate.contact_sheets(cands, tmp_path / 's', ffmpeg=ffmpeg, ffprobe=ffprobe, warnings=warnings)
    assert len(paths) == 1 and warnings == ['VIDEO_FRAMES_FAILED:V001']


# ---- CLI ---------------------------------------------------------------------------------

class Lib:
    def __init__(self, tmp_path, monkeypatch, cli, capsys):
        self.cli, self.capsys = cli, capsys
        self.out_root = tmp_path / 'lib'
        self.folder = self.out_root / 'Mia' / '2026'
        monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(tmp_path / 'cfg'))
        monkeypatch.setattr(config, 'remote_reason', lambda *a, **k: None)
        monkeypatch.setattr(curate.shutil, 'which', lambda name: None)  # no ffmpeg in CLI tests
        self.items = {}

    def add(self, item_id, when, kind='PHOTO', image=None, thumb=None, original=True, name=None):
        name = name or f'{item_id}.{"mp4" if kind == "VIDEO" else "jpg"}'
        media = self.folder / 'media' / name
        media.parent.mkdir(parents=True, exist_ok=True)
        if original:
            if kind == 'PHOTO' and image is not None:
                save(image, media)
            else:
                media.write_bytes(b'\0garbage')
        thumb_rel = None
        if thumb is not None:
            thumb_rel = f'.thumbs/{item_id}.jpg'
            save(thumb, self.folder / thumb_rel)
        self.items[item_id] = {
            'file': f'media/{name}', 'filename': name, 'type': kind, 'mime': 'image/jpeg',
            'create_time': when.astimezone(timezone.utc).isoformat(), 'local_time': when.isoformat(),
            'width': 100, 'height': 100, 'camera_make': None, 'camera_model': None, 'fps': None,
            'thumb': thumb_rel, 'session': 's1'}

    def write_manifest(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / 'manifest.json').write_text(json.dumps(
            {'version': 1, 'subject': 'Mia', 'year': 2026, 'tz': 'Asia/Seoul', 'items': self.items}))

    def run(self, *extra):
        code = self.cli.main(['curate', '--subject', 'Mia', '--year', '2026',
                              '--out-root', str(self.out_root), *extra])
        out, err = self.capsys.readouterr()
        return code, (json.loads(out) if out else None), (json.loads(err) if err else None)


@pytest.fixture
def lib(tmp_path, monkeypatch, cli, capsys):
    return Lib(tmp_path, monkeypatch, cli, capsys)


def snapshot(folder):
    out = {}
    for p in sorted(folder.rglob('*')):
        rel = p.relative_to(folder).as_posix()
        if rel == 'curation' or rel.startswith('curation/'):
            continue
        out[rel] = (p.is_dir(), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
    return out


def test_heic_uses_thumb(lib):
    lib.add('h1', T0, name='x.heic', thumb=scene(5), original=True)  # garbage original bytes
    lib.write_manifest()
    code, out, _ = lib.run()
    assert code == 0 and out['candidates'] == 1 and out['photos'] == 1
    assert out['warnings'] == []  # no videos: missing ffmpeg does not matter


@pytest.mark.parametrize('missing', ['ffmpeg', 'ffprobe', None])
def test_curate_warns_when_video_tools_missing(lib, tmp_path, monkeypatch, missing):
    ffmpeg, ffprobe, _ = fake_tools(tmp_path)
    tools = {'ffmpeg': ffmpeg, 'ffprobe': ffprobe}
    monkeypatch.setattr(curate.shutil, 'which', lambda name: None if name == missing else tools.get(name))
    lib.add('p0', T0, image=scene(0), thumb=scene(0))
    lib.add('v1', T0 + timedelta(days=1), kind='VIDEO', thumb=scene(50))
    lib.write_manifest()
    code, out, err = lib.run()
    assert code == 0, err
    assert out['videos'] == 1
    assert ('VIDEO_FRAMES_UNAVAILABLE' in out['warnings']) == (missing is not None)


def test_curate_cli_outputs(lib):
    for i in range(6):
        lib.add(f'p{i}', T0 + timedelta(days=i), image=scene(i, 200), thumb=scene(i))
    lib.add('p6', T0 + timedelta(days=7), image=scene(6, 200))                     # no thumb: original
    lib.add('dark', T0 + timedelta(days=8), thumb=Image.new('RGB', (64, 64), 0))
    lib.add('gone', T0 + timedelta(days=9), thumb=scene(9), original=False)        # missing on disk
    lib.add('broken', T0 + timedelta(days=10), image=None)                         # garbage, no thumb
    lib.add('v1', T0 + timedelta(days=2), kind='VIDEO', thumb=scene(50))
    lib.add('v2', T0 + timedelta(days=1), kind='VIDEO')                            # no thumb at all
    lib.items['escape'] = dict(lib.items['p0'], file='../../../etc/passwd', thumb='../outside.jpg')
    lib.items['junk'] = 'not a dict'
    lib.write_manifest()
    (lib.folder / 'selected').mkdir()
    (lib.folder / 'selected' / 'keep.jpg').write_bytes(b'mine')
    (lib.folder / 'selection.json').write_text('{}')
    before = snapshot(lib.folder)

    code, out, err = lib.run('--target', '5', '--video-target', '2')
    assert code == 0, err
    assert set(out) == {'status', 'candidates', 'photos', 'videos', 'dropped', 'sheets', 'picks_file',
                        'target', 'video_target', 'warnings'}
    assert out['status'] == 'ok' and out['target'] == 5 and out['video_target'] == 2
    assert (out['photos'], out['videos'], out['candidates']) == (7, 2, 9)
    assert out['dropped']['missing'] == 2  # 'gone' + 'escape' (a file outside the year folder)
    assert out['dropped']['dark'] == 1 and out['dropped']['undecodable'] == 1  # 'broken'
    assert out['dropped']['invalid_entry'] == 1
    assert out['warnings'] == ['VIDEO_FRAMES_UNAVAILABLE']  # videos, but no ffmpeg in CLI tests
    curation = (lib.folder / 'curation').resolve()
    assert out['picks_file'] == str(curation / 'picks.json')
    assert not (curation / 'picks.json').exists()
    assert out['sheets'] == [str(curation / 'sheets' / 'sheet-01.jpg')]
    assert all(os.path.isabs(p) and Path(p).is_file() for p in out['sheets'])

    data = json.loads((curation / 'candidates.json').read_text())
    assert set(data) == {'target', 'video_target', 'candidates', 'dropped', 'sheets'}
    assert [c['ref'] for c in data['candidates']] == ['C001', 'C002', 'C003', 'C004', 'C005', 'C006', 'C007',
                                                        'V001', 'V002']
    for c in data['candidates']:
        assert set(c) == {'ref', 'id', 'file', 'type', 'local_time', 'sharpness', 'brightness', 'group_size'}
    by_ref = {c['ref']: c for c in data['candidates']}
    assert by_ref['V001']['id'] == 'v2' and by_ref['V001']['sharpness'] is None
    assert by_ref['C001']['file'] == 'media/p0.jpg'
    assert snapshot(lib.folder) == before  # only curation/ touched

    # a second run replaces its own outputs and keeps the agent's picks file
    (curation / 'picks.json').write_text('{"picks": []}')
    (curation / 'sheets' / 'sheet-07.jpg').write_bytes(b'stale')
    code, out2, _ = lib.run()
    assert code == 0 and out2['target'] == curate.DEFAULT_TARGET and out2['video_target'] == 8
    assert sorted(p.name for p in (curation / 'sheets').iterdir()) == ['sheet-01.jpg']
    assert (curation / 'picks.json').read_text() == '{"picks": []}'


def test_curate_naive_local_time_is_invalid(lib):
    lib.add('p0', T0, image=scene(0), thumb=scene(0))
    lib.add('p1', T0 + timedelta(days=1), image=scene(1), thumb=scene(1))
    lib.items['p1']['local_time'] = '2026-04-19T10:00:00'  # no offset: cannot sort with aware times
    lib.write_manifest()
    code, out, err = lib.run()
    assert code == 0, err
    assert out['candidates'] == 1 and out['dropped']['invalid_entry'] == 1


def test_curate_nothing(lib):
    code, out, err = lib.run()
    assert code == 2 and out is None and err['error'] == 'NOTHING_TO_CURATE'
    assert not lib.folder.exists()
    lib.add('gone', T0, thumb=scene(1), original=False)
    lib.write_manifest()
    code, _, err = lib.run()
    assert code == 2 and err['error'] == 'NOTHING_TO_CURATE'
    assert not (lib.folder / 'curation').exists()


def test_curate_bad_args(lib):
    assert lib.run('--target', '0')[2]['error'] == 'USAGE_ERROR'
    assert lib.run('--video-target', '-1')[2]['error'] == 'USAGE_ERROR'
    code = lib.cli.main(['curate', '--subject', '..', '--year', '2026', '--out-root', str(lib.out_root)])
    assert code == 2 and json.loads(lib.capsys.readouterr().err)['error'] == 'UNSAFE_SUBJECT'


def test_curate_refuses_symlinked_curation(lib, tmp_path):
    lib.add('p0', T0, image=scene(0), thumb=scene(0))
    lib.write_manifest()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (lib.folder / 'curation').symlink_to(elsewhere)
    code, _, err = lib.run()
    assert code == 2 and err['error'] == 'CURATION_DIR_UNSAFE'
    assert list(elsewhere.iterdir()) == []


def test_curate_error_messages():
    for code in ('NOTHING_TO_CURATE', 'CURATION_DIR_UNSAFE'):
        assert message_for(code) == MESSAGES[code]
        assert 'http' not in MESSAGES[code] and '/' not in MESSAGES[code]
