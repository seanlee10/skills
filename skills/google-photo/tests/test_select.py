import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from gphoto import config, curate
from gphoto.errors import MESSAGES, Failure, message_for

T0 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone(timedelta(hours=9)))


class Year:
    """A year folder with media files and a minimal curation/candidates.json."""

    def __init__(self, tmp_path, monkeypatch, cli, capsys):
        self.cli, self.capsys = cli, capsys
        self.out_root = tmp_path / 'lib'
        self.folder = self.out_root / 'Mia' / '2026'
        monkeypatch.setenv('GOOGLE_PHOTO_CONFIG_DIR', str(tmp_path / 'cfg'))
        monkeypatch.setattr(config, 'remote_reason', lambda *a, **k: None)
        (self.folder / 'media').mkdir(parents=True)
        (self.folder / 'curation').mkdir()
        self.candidates = []
        for i in range(1, 4):
            self.add(f'C{i:03d}', f'p{i}', f'photo {i}.jpg', 'PHOTO', i)
        self.add('V001', 'v1', 'clip.mp4', 'VIDEO', 5)
        self.write_candidates()

    def add(self, ref, item_id, name, kind, day):
        (self.folder / 'media' / name).write_bytes(f'bytes of {name}'.encode())
        self.candidates.append({
            'ref': ref, 'id': item_id, 'file': f'media/{name}', 'type': kind,
            'local_time': (T0 + timedelta(days=day)).isoformat(),
            'sharpness': 10.0 if kind == 'PHOTO' else None,
            'brightness': 100.0 if kind == 'PHOTO' else None, 'group_size': 1})

    def write_candidates(self, data=None):
        data = data if data is not None else {
            'target': 5, 'video_target': 2, 'candidates': self.candidates, 'dropped': {}, 'sheets': []}
        (self.folder / 'curation' / 'candidates.json').write_text(json.dumps(data))

    def write_picks(self, picks, path=None):
        path = path or self.folder / 'curation' / 'picks.json'
        path.write_text(json.dumps(picks) if not isinstance(picks, str) else picks)
        return path

    def run(self, *extra):
        code = self.cli.main(['select', '--subject', 'Mia', '--year', '2026',
                              '--out-root', str(self.out_root), *extra])
        out, err = self.capsys.readouterr()
        return code, (json.loads(out) if out else None), (json.loads(err) if err else None)

    def pick(self, *refs, **kw):
        self.write_picks({'items': [{'ref': r, 'reason': f'because {r}'} for r in refs]})
        return self.run(*kw.get('extra', ()))

    @property
    def selected(self):
        return self.folder / 'selected'

    def selected_names(self):
        return sorted(p.name for p in self.selected.iterdir())


@pytest.fixture
def year(tmp_path, monkeypatch, cli, capsys):
    return Year(tmp_path, monkeypatch, cli, capsys)


def media_snapshot(folder):
    media = folder / 'media'
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(media.iterdir())}


def test_select_writes_ranked_links(year):
    code, out, err = year.pick('C002', 'V001', 'C001')
    assert code == 0, err
    selected = year.selected.resolve()
    assert out == {'status': 'ok', 'selected': 3, 'photos': 2, 'videos': 1, 'folder': str(selected),
                   'selection': str(year.folder.resolve() / 'selection.json'), 'warnings': []}
    assert year.selected_names() == ['001_photo 2.jpg', '002_clip.mp4', '003_photo 1.jpg']
    for name, media in (('001_photo 2.jpg', 'photo 2.jpg'), ('002_clip.mp4', 'clip.mp4')):
        linked, original = year.selected / name, year.folder / 'media' / media
        assert not linked.is_symlink()
        assert os.path.samefile(linked, original) or linked.read_bytes() == original.read_bytes()

    data = json.loads((year.folder / 'selection.json').read_text())
    assert set(data) == {'subject', 'year', 'created', 'items'}
    assert data['subject'] == 'Mia' and data['year'] == 2026
    assert datetime.fromisoformat(data['created']).utcoffset() is not None
    assert [i['rank'] for i in data['items']] == [1, 2, 3]
    first = data['items'][0]
    assert set(first) == {'rank', 'ref', 'id', 'type', 'file', 'local_time', 'reason', 'selected_file'}
    assert first == {'rank': 1, 'ref': 'C002', 'id': 'p2', 'type': 'PHOTO', 'file': 'media/photo 2.jpg',
                     'local_time': (T0 + timedelta(days=2)).isoformat(), 'reason': 'because C002',
                     'selected_file': 'selected/001_photo 2.jpg'}
    assert [i['ref'] for i in data['items']] == ['C002', 'V001', 'C001']
    assert not list(year.folder.glob('.candidates-*')) and not list(year.folder.glob('*.tmp'))


def test_select_copy_fallback(year, monkeypatch):
    def no_links(src, dst, **kw):
        raise OSError(18, 'Invalid cross-device link')
    monkeypatch.setattr(curate.os, 'link', no_links)
    code, out, err = year.pick('C003')
    assert code == 0, err
    copied = year.selected / '001_photo 3.jpg'
    assert copied.read_bytes() == (year.folder / 'media' / 'photo 3.jpg').read_bytes()
    assert not os.path.samefile(copied, year.folder / 'media' / 'photo 3.jpg')


def test_select_rerun_replaces_previous(year):
    assert year.pick('C002', 'V001', 'C001')[0] == 0
    code, out, err = year.pick('C003')
    assert code == 0, err
    assert out['selected'] == 1 and out['warnings'] == []
    assert year.selected_names() == ['001_photo 3.jpg']
    data = json.loads((year.folder / 'selection.json').read_text())
    assert [i['ref'] for i in data['items']] == ['C003']


def test_select_rerun_same_pick_is_stable(year):
    assert year.pick('C001')[0] == 0
    code, out, err = year.pick('C001', 'C002')
    assert code == 0, err
    assert year.selected_names() == ['001_photo 1.jpg', '002_photo 2.jpg']


def test_select_keeps_foreign_files(year):
    year.selected.mkdir()
    (year.selected / 'notes.txt').write_text('mine')
    (year.selected / '001_photo 1.jpg').write_text('user file with a skill-like name')
    code, out, err = year.pick('C001', 'C002')
    assert code == 0, err
    assert out['warnings'] == ['SELECTED_FOLDER_HAS_OTHER_FILES']
    assert (year.selected / 'notes.txt').read_text() == 'mine'
    assert (year.selected / '001_photo 1.jpg').read_text() == 'user file with a skill-like name'
    data = json.loads((year.folder / 'selection.json').read_text())
    first = data['items'][0]['selected_file']
    assert first != 'selected/001_photo 1.jpg' and first.startswith('selected/001_')
    assert (year.folder / first).read_bytes() == (year.folder / 'media' / 'photo 1.jpg').read_bytes()

    # the next run removes only its own files; the user's stay
    code, out, err = year.pick('C003')
    assert code == 0 and out['warnings'] == ['SELECTED_FOLDER_HAS_OTHER_FILES']
    assert year.selected_names() == ['001_photo 1.jpg', '001_photo 3.jpg', 'notes.txt']


def test_select_ignores_unsafe_previous_entries(year, tmp_path):
    outside = tmp_path / '001_outside.jpg'
    outside.write_text('keep')
    year.selected.mkdir()
    (year.selected / '002_sub').mkdir()
    (year.folder / 'selection.json').write_text(json.dumps({'items': [
        {'selected_file': str(outside)}, {'selected_file': 'selected/../media/photo 1.jpg'},
        {'selected_file': 'selected/002_sub'}, {'selected_file': 'selected/notes.txt'}, 'junk']}))
    (year.selected / 'notes.txt').write_text('mine')
    before = media_snapshot(year.folder)
    code, out, err = year.pick('C002')
    assert code == 0, err
    assert outside.read_text() == 'keep' and (year.selected / '002_sub').is_dir()
    assert (year.selected / 'notes.txt').read_text() == 'mine'
    assert media_snapshot(year.folder) == before
    assert out['warnings'] == ['SELECTED_FOLDER_HAS_OTHER_FILES']


def test_select_keeps_symlink_not_target(year, tmp_path):
    target = tmp_path / 'precious.jpg'
    target.write_text('precious')
    assert year.pick('C001')[0] == 0
    link = year.selected / '001_photo 1.jpg'
    link.unlink()
    link.symlink_to(target)
    code, out, err = year.pick('C002')
    assert code == 0, err
    assert target.read_text() == 'precious' and link.is_symlink()
    assert out['warnings'] == ['SELECTED_FILE_KEPT:001_photo 1.jpg', 'SELECTED_FOLDER_HAS_OTHER_FILES']
    assert year.selected_names() == ['001_photo 1.jpg', '001_photo 2.jpg']


def _safe_save(path, data):
    """Replace `path` the way macOS safe-save does: a new inode moved over the old name."""
    tmp = path.with_name('.tmp-edit')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def test_select_keeps_edited_hard_link(year):
    assert year.pick('C001', 'C002', 'C003')[0] == 0
    edited = year.selected / '003_photo 3.jpg'
    _safe_save(edited, b'my edit')
    code, out, err = year.pick('C003', 'C001')
    assert code == 0, err
    assert edited.read_bytes() == b'my edit'
    assert out['warnings'] == ['SELECTED_FILE_KEPT:003_photo 3.jpg', 'SELECTED_FOLDER_HAS_OTHER_FILES']
    assert year.selected_names() == ['001_photo 3.jpg', '002_photo 1.jpg', '003_photo 3.jpg']
    assert (year.folder / 'media' / 'photo 3.jpg').read_bytes() == b'bytes of photo 3.jpg'


def test_select_kept_name_is_not_reused(year):
    assert year.pick('C001')[0] == 0
    _safe_save(year.selected / '001_photo 1.jpg', b'my edit')
    code, out, err = year.pick('C001')
    assert code == 0, err
    assert (year.selected / '001_photo 1.jpg').read_bytes() == b'my edit'
    data = json.loads((year.folder / 'selection.json').read_text())
    assert data['items'][0]['selected_file'] == 'selected/001_photo 1_2.jpg'
    assert out['warnings'][0] == 'SELECTED_FILE_KEPT:001_photo 1.jpg'


def test_select_copy_rerun_removes_own_keeps_edited(year, monkeypatch):
    def no_links(src, dst, **kw):
        raise OSError(18, 'Invalid cross-device link')
    monkeypatch.setattr(curate.os, 'link', no_links)
    assert year.pick('C001', 'C002')[0] == 0
    (year.selected / '002_photo 2.jpg').write_bytes(b'edited in place, new size')
    code, out, err = year.pick('C003')
    assert code == 0, err
    # the untouched copy was the skill's own and is gone; the edited one is kept
    assert year.selected_names() == ['001_photo 3.jpg', '002_photo 2.jpg']
    assert (year.selected / '002_photo 2.jpg').read_bytes() == b'edited in place, new size'
    assert out['warnings'] == ['SELECTED_FILE_KEPT:002_photo 2.jpg', 'SELECTED_FOLDER_HAS_OTHER_FILES']


def test_select_copy_same_size_new_mtime_is_kept(year, monkeypatch):
    monkeypatch.setattr(curate.os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError(18, 'x')))
    assert year.pick('C001')[0] == 0
    copy = year.selected / '001_photo 1.jpg'
    size, st = copy.stat().st_size, copy.stat()
    copy.write_bytes(b'X' * size)
    os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    code, out, err = year.pick('C002')
    assert code == 0, err
    assert copy.read_bytes() == b'X' * size
    assert out['warnings'][0] == 'SELECTED_FILE_KEPT:001_photo 1.jpg'


def test_select_corrupt_previous_selection(year):
    year.selected.mkdir()
    (year.folder / 'selection.json').write_text('not json')
    code, out, err = year.pick('C001')
    assert code == 0, err
    assert year.selected_names() == ['001_photo 1.jpg']


@pytest.mark.parametrize('picks', [
    {'items': []},
    {'items': [{'ref': 'C999', 'reason': 'x'}]},
    {'items': [{'ref': 'C001', 'reason': 'a'}, {'ref': 'C001', 'reason': 'b'}]},
    {'items': [{'ref': 'C001', 'reason': ''}]},
    {'items': [{'ref': 'C001', 'reason': '   '}]},
    {'items': [{'ref': 'C001', 'reason': 'x' * 201}]},
    {'items': [{'ref': 'C001'}]},
    {'items': [{'ref': 1, 'reason': 'x'}]},
    {'items': [{'ref': 'C001', 'reason': 5}]},
    {'items': ['C001']},
    {'items': {'ref': 'C001'}},
    {'picks': []},
    [],
    'not json',
])
def test_invalid_picks(year, picks):
    year.write_picks(picks)
    before = media_snapshot(year.folder)
    code, out, err = year.run()
    assert code == 2 and out is None and err['error'] == 'INVALID_PICKS'
    assert not year.selected.exists() and not (year.folder / 'selection.json').exists()
    assert media_snapshot(year.folder) == before


def test_invalid_picks_api(year):
    with pytest.raises(Failure) as e:
        curate.apply_picks(year.folder, {'items': [{'ref': 'C001', 'reason': 'a'}] * 5})
    assert e.value.code == 'INVALID_PICKS'  # more picks than candidates


def test_reason_is_cleaned(year):
    year.write_picks({'items': [{'ref': 'C001', 'reason': '  big\n smile\x07\t '},
                                {'ref': 'C002', 'reason': 'x' * 200}]})
    code, _, err = year.run()
    assert code == 0, err
    items = json.loads((year.folder / 'selection.json').read_text())['items']
    assert items[0]['reason'] == 'big smile' and len(items[1]['reason']) == 200


def test_picked_file_must_stay_in_media(year, tmp_path):
    (tmp_path / 'secret.jpg').write_text('secret')
    (year.folder / 'manifest.json').write_text('{}')
    year.candidates[0]['file'] = '../../../secret.jpg'
    year.candidates[1]['file'] = 'manifest.json'          # inside the year folder but not media/
    year.candidates[2]['file'] = 'media/gone.jpg'         # not on disk
    year.write_candidates()
    for ref in ('C001', 'C002', 'C003'):
        code, _, err = year.pick(ref)
        assert code == 2 and err['error'] == 'INVALID_PICKS'
    assert not year.selected.exists()


def test_custom_picks_path(year, tmp_path):
    path = year.write_picks({'items': [{'ref': 'V001', 'reason': 'motion'}]}, tmp_path / 'mine.json')
    code, out, err = year.run('--picks', str(path))
    assert code == 0, err
    assert out['videos'] == 1 and year.selected_names() == ['001_clip.mp4']


def test_missing_picks_file(year):
    code, _, err = year.run()
    assert code == 2 and err['error'] == 'INVALID_PICKS'


def test_nothing_to_curate(year):
    (year.folder / 'curation' / 'candidates.json').unlink()
    year.write_picks({'items': [{'ref': 'C001', 'reason': 'x'}]})
    code, _, err = year.run()
    assert code == 2 and err['error'] == 'NOTHING_TO_CURATE'


@pytest.mark.parametrize('data', ['not json', '[]', '{"candidates": "x"}'])
def test_corrupt_candidates(year, data):
    (year.folder / 'curation' / 'candidates.json').write_text(data)
    code, _, err = year.pick('C001')
    assert code == 2 and err['error'] == 'CANDIDATES_CORRUPT'


def test_refuses_unsafe_selected_folder(year, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    year.selected.symlink_to(elsewhere)
    code, _, err = year.pick('C001')
    assert code == 2 and err['error'] == 'SELECTED_DIR_UNSAFE'
    assert list(elsewhere.iterdir()) == []
    year.selected.unlink()
    year.selected.write_text('a file')
    code, _, err = year.pick('C001')
    assert code == 2 and err['error'] == 'SELECTED_DIR_UNSAFE'


def test_refuses_symlinked_curation(year, tmp_path):
    real = year.folder / 'curation'
    moved = tmp_path / 'moved'
    real.rename(moved)
    real.symlink_to(moved)
    code, _, err = year.pick('C001')
    assert code == 2 and err['error'] == 'CURATION_DIR_UNSAFE'


def test_originals_untouched(year):
    before = media_snapshot(year.folder)
    assert year.pick('C002', 'V001', 'C001')[0] == 0
    assert year.pick('C003')[0] == 0
    assert media_snapshot(year.folder) == before


def test_select_after_real_curate(year, monkeypatch):
    from PIL import Image
    import random
    monkeypatch.setattr(curate.shutil, 'which', lambda name: None)
    items = {}
    for i in range(3):
        rnd = random.Random(i)
        img = Image.effect_noise((96, 96), 60 + 20 * i).convert('RGB')
        img = img.rotate(rnd.randrange(360))
        img.save(year.folder / 'media' / f'r{i}.jpg', 'JPEG')
        when = T0 + timedelta(days=30 * i)
        items[f'r{i}'] = {'file': f'media/r{i}.jpg', 'type': 'PHOTO', 'local_time': when.isoformat(),
                          'thumb': None}
    (year.folder / 'manifest.json').write_text(json.dumps({'version': 1, 'items': items}))
    code = year.cli.main(['curate', '--subject', 'Mia', '--year', '2026', '--out-root', str(year.out_root)])
    out = json.loads(year.capsys.readouterr().out)
    assert code == 0 and out['candidates'] >= 1
    code, out, err = year.pick('C001')
    assert code == 0, err
    assert len(year.selected_names()) == 1 and year.selected_names()[0].startswith('001_r')


def test_select_bad_args(year):
    assert year.cli.main(['select', '--subject', '..', '--year', '2026', '--out-root', str(year.out_root)]) == 2
    assert json.loads(year.capsys.readouterr().err)['error'] == 'UNSAFE_SUBJECT'
    assert year.cli.main(['select', '--year', '2026']) == 2
    assert json.loads(year.capsys.readouterr().err)['error'] == 'USAGE_ERROR'


def test_select_error_messages():
    for code in ('INVALID_PICKS', 'PICKS_OUTDATED', 'CANDIDATES_CORRUPT', 'SELECTED_DIR_UNSAFE'):
        assert message_for(code) == MESSAGES[code]
        assert 'http' not in MESSAGES[code] and '/' not in MESSAGES[code]


def test_failed_placement_rolls_back(year, monkeypatch):
    real, calls = curate._place, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(28, 'No space left on device')
        real(src, dst)
    monkeypatch.setattr(curate, '_place', flaky)
    code, _, err = year.pick('C001', 'C002')
    assert code == 2 and err['error'] == 'OSError'
    assert year.selected_names() == [] and not (year.folder / 'selection.json').exists()


def test_failed_rerun_leaves_no_stale_selection(year, monkeypatch):
    assert year.pick('C001', 'C002')[0] == 0
    real, calls = curate._place, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(28, 'No space left on device')
        real(src, dst)
    monkeypatch.setattr(curate, '_place', flaky)
    code, _, err = year.pick('C003', 'V001')
    assert code == 2 and err['error'] == 'OSError'
    assert year.selected_names() == [] and not (year.folder / 'selection.json').exists()


def test_outdated_picks_refused(year):
    picks = year.write_picks({'items': [{'ref': 'C001', 'reason': 'x'}]})
    cand = year.folder / 'curation' / 'candidates.json'
    st = cand.stat()
    os.utime(picks, ns=(st.st_atime_ns, st.st_mtime_ns - 1_000_000_000))  # curate ran after the picks
    code, out, err = year.run()
    assert code == 2 and out is None
    assert err == {'status': 'failed', 'error': 'PICKS_OUTDATED', 'message': MESSAGES['PICKS_OUTDATED']}
    assert not year.selected.exists() and not (year.folder / 'selection.json').exists()
    picks.touch()  # rewritten after the latest curate
    assert year.run()[0] == 0


def test_outdated_custom_picks_refused(year, tmp_path):
    picks = year.write_picks({'items': [{'ref': 'C001', 'reason': 'x'}]}, tmp_path / 'mine.json')
    st = (year.folder / 'curation' / 'candidates.json').stat()
    os.utime(picks, ns=(st.st_atime_ns, st.st_mtime_ns - 1))
    code, _, err = year.run('--picks', str(picks))
    assert code == 2 and err['error'] == 'PICKS_OUTDATED'
