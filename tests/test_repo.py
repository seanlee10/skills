import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_marketplace_manifest():
    m = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
    assert m['name'] == 'seanlee10' and m['owner']['name']
    assert len(m['plugins']) == 1
    plugin = m['plugins'][0]
    assert isinstance(plugin.get('description'), str) and plugin['description'].strip()
    assert plugin == {'name': 'seanlee10-skills', 'source': './', 'description': plugin['description']}
    assert isinstance(m.get('description'), str) and m['description'].strip()


def test_plugin_manifest():
    p = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
    assert p['name'] == 'seanlee10-skills' and p['version'] == '0.1.0'
    assert 'skills' not in p or p['skills'] == './skills/'


def test_gitignore_blocks_secrets():
    ignored = (ROOT / '.gitignore').read_text().split()
    for pat in ['.env*', '.venv/', '.runtime/', '__pycache__/', '*.pyc', '*.pptx', '.DS_Store', 'bench/hwp-parser/out/', '.superpowers/']:
        assert pat in ignored


def _pep723(path):
    import re
    import tomllib
    m = re.search(r'^# /// script\n((?:#.*\n)+?)^# ///$', path.read_text(encoding='utf-8'), re.M)
    assert m, 'missing PEP 723 block'
    return tomllib.loads(''.join(line[2:] if line.startswith('# ') else line[1:]
                                 for line in m.group(1).splitlines(keepends=True)))


@pytest.mark.parametrize('skill,script', [('hwp-parser', 'hwp2md.py'), ('google-photo', 'gphoto.py'),
                                          ('kipris-search', 'kipris_api.py'),
                                          ('ga4-blog-report', 'ga4_report.py'),
                                          ('youtube-download', 'download_video.py')])
def test_pep723_pins_match_requirements(skill, script):
    scripts = ROOT / 'skills' / skill / 'scripts'
    meta = _pep723(scripts / script)
    reqs = [line.strip() for line in (scripts / 'requirements.txt').read_text().splitlines()
            if line.strip() and not line.strip().startswith('#')]
    assert meta['requires-python'] == '==3.11.*'
    assert meta['dependencies'] == reqs


SKILLS = sorted(p.parent for p in ROOT.glob('skills/*/SKILL.md'))
SKILL_IDS = [skill.name for skill in SKILLS]
KEYWORDS = {'domain-search': ['domain', 'Route 53', 'WHOIS'],
            'email-draft': ['email', 'Gmail', 'rich text'],
            'ga4-blog-report': ['GA4', 'Google Analytics', 'AI'], 'hwp-parser': ['HWP', 'HWPX', 'Markdown'], 'google-photo': ['Google Photos', 'Picker'],
            'kipris-search': ['KIPRIS', 'patent', 'trademark'],
            'youtube-download': ['YouTube', 'MP4', 'download']}


def test_skill_set():
    assert SKILL_IDS == ['domain-search', 'email-draft', 'ga4-blog-report', 'google-photo', 'hwp-parser', 'kipris-search',
                         'youtube-download']


def _frontmatter(path):
    import re
    m = re.match(r'^---\n(.*?)\n---\n', path.read_text(encoding='utf-8'), re.S)
    assert m, 'missing frontmatter'
    fields = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(':')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


@pytest.mark.parametrize('skill', SKILLS, ids=SKILL_IDS)
def test_skill_frontmatter(skill):
    meta = _frontmatter(skill / 'SKILL.md')
    assert meta['name'] == skill.name
    description = meta['description']
    assert description.strip() and len(description) <= 1024
    for word in KEYWORDS[skill.name]:
        assert word in description


@pytest.mark.parametrize('skill,module', [
    ('hwp-parser', 'hwp2md'),
    ('google-photo', 'gphoto.errors'),
    ('kipris-search', 'kipris_api'),
    ('ga4-blog-report', 'ga4_report'),
])
def test_errors_reference_complete(skill, module):
    import importlib
    import sys
    sys.path.insert(0, str(ROOT / 'skills' / skill / 'scripts'))
    messages = importlib.import_module(module).MESSAGES
    errors = (ROOT / 'skills' / skill / 'references/errors.md').read_text(encoding='utf-8')
    missing = [code for code in messages if f'`{code}`' not in errors]
    assert not missing, missing


@pytest.mark.parametrize('skill', SKILLS, ids=SKILL_IDS)
def test_skill_links_resolve(skill):
    import re
    skill_md = skill / 'SKILL.md'
    docs = [skill_md, *sorted((skill / 'references').glob('*.md'))]
    for doc in docs:
        text = re.sub(r'```.*?```|`[^`\n]*`', '', doc.read_text(encoding='utf-8'), flags=re.S)
        for target in re.findall(r'\]\(([^)\s]+)\)', text):
            if re.match(r'[a-z]+:', target) or target.startswith('#'):
                continue
            path = (doc.parent / target.split('#')[0].strip('<>')).resolve()
            assert path.exists(), f'{doc.name}: {target}'


def _load_hermes_plugin():
    import importlib.util
    spec = importlib.util.spec_from_file_location('seanlee10_hermes_plugin', ROOT / '.hermes-plugin/__init__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCtx:
    def __init__(self):
        self.calls = []

    def register_skill(self, name, path, description=''):
        self.calls.append((name, path, description))


def test_hermes_plugin_manifest():
    lines = (ROOT / '.hermes-plugin/plugin.yaml').read_text(encoding='utf-8').splitlines()
    fields = dict(line.split(':', 1) for line in lines if line.strip() and not line.startswith('#'))
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    assert fields['name'] == 'seanlee10-skills' and fields['version'] == '0.1.0'
    assert fields['description']
    assert 'provides_hooks' not in fields


def test_hermes_register():
    import pathlib
    ctx = _FakeCtx()
    _load_hermes_plugin().register(ctx)
    assert [name for name, _, _ in ctx.calls] == ['domain-search', 'email-draft', 'ga4-blog-report', 'google-photo', 'hwp-parser',
                                                'kipris-search', 'youtube-download']
    for (name, path, description), skill in zip(ctx.calls, SKILLS):
        assert name == skill.name
        assert isinstance(path, pathlib.Path) and path == skill / 'SKILL.md' and path.is_file()
        assert description.strip() and description == _frontmatter(skill / 'SKILL.md')['description']


def test_hermes_register_frontmatter_edge_cases(tmp_path):
    import pathlib
    cases = {
        'plain': '---\nname: plain\ndescription: Plain value: with colon\n---\nbody\n',
        'single': "---\nname: single\ndescription: 'Single quoted'\n---\n",
        'double': '---\nname: double\ndescription: "Double quoted"\n---\n',
        'nofront': '# no frontmatter here\n',
        'bom': '\ufeff---\nname: bom\ndescription: With BOM\n---\nbody\n',
        'eof': '---\nname: eof\ndescription: Closing fence at EOF\n---',
        'empty': '---\nname: empty\ndescription: \n---\n',
        'nodesc': '---\nname: nodesc\n---\n',
    }
    for folder, text in cases.items():
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'SKILL.md').write_text(text, encoding='utf-8')
    ctx = _FakeCtx()
    _load_hermes_plugin().register_skills(ctx, tmp_path)
    assert all(isinstance(p, pathlib.Path) for _, p, _ in ctx.calls)
    assert [(n, d) for n, _, d in ctx.calls] == [
        ('bom', 'With BOM'),
        ('double', 'Double quoted'),
        ('eof', 'Closing fence at EOF'),
        ('plain', 'Plain value: with colon'),
        ('single', 'Single quoted'),
    ]


def test_descriptions_name_every_skill():
    marketplace = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
    plugin = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
    hermes = (ROOT / '.hermes-plugin/plugin.yaml').read_text(encoding='utf-8')
    hermes_description = next(line.split(':', 1)[1] for line in hermes.splitlines()
                              if line.startswith('description:'))
    assert ': ' not in hermes_description.strip()
    for name in SKILL_IDS:
        for text in (marketplace['description'], marketplace['plugins'][0]['description'],
                     plugin['description'], hermes_description):
            assert name in text, name
    for path in READMES:
        readme = path.read_text(encoding='utf-8')
        for name in SKILL_IDS:
            assert f'| [{name}](skills/{name}/SKILL.md) |' in readme, (path.name, name)
            assert f'\n### {name}\n' in readme, (path.name, name)


README = ROOT / 'README.md'
README_KO = ROOT / 'README.ko.md'
READMES = [README, README_KO]
README_IDS = [p.name for p in READMES]


def _bench_block(text):
    start, end = '<!-- bench:start -->', '<!-- bench:end -->'
    assert text.count(start) == 1 and text.count(end) == 1 and text.find(start) < text.find(end)
    return text[text.find(start) + len(start):text.find(end)]


@pytest.mark.parametrize('readme', READMES, ids=README_IDS)
def test_readme_bench_in_sync(readme):
    block = _bench_block(readme.read_text(encoding='utf-8'))
    results = (ROOT / 'bench/hwp-parser/results.md').read_text(encoding='utf-8')
    assert block.strip('\n') == results.strip('\n')


def test_readme_language_switch():
    assert README.read_text(encoding='utf-8').splitlines()[0] == '**English** | [한국어](README.ko.md)'
    assert README_KO.read_text(encoding='utf-8').splitlines()[0] == '[English](README.md) | **한국어**'


def _slug(heading):
    import re
    return re.sub(r'[^\w\- ]', '', heading.strip().lower()).replace(' ', '-')


def _anchors(path):
    import re
    text = re.sub(r'^```.*?^```', '', path.read_text(encoding='utf-8'), flags=re.S | re.M)
    return {_slug(m) for m in re.findall(r'^#{1,6} (.+)$', text, re.M)}


@pytest.mark.parametrize('doc', [README, README_KO, ROOT / 'bench/hwp-parser/README.md'],
                         ids=['README.md', 'README.ko.md', 'bench-README.md'])
def test_readme_links_resolve(doc):
    import re
    text = re.sub(r'```.*?```|`[^`\n]*`', '', doc.read_text(encoding='utf-8'), flags=re.S)
    targets = re.findall(r'\]\(([^)\s]+)\)', text)
    assert targets
    for target in targets:
        if re.match(r'[a-z]+:', target):
            continue
        file_part, _, anchor = target.strip('<>').partition('#')
        path = (doc.parent / file_part).resolve() if file_part else doc
        assert path.exists(), f'{doc.name}: {target}'
        if anchor and path.suffix == '.md':
            assert anchor in _anchors(path), f'{doc.name}: {target}'


@pytest.mark.parametrize('readme', READMES, ids=README_IDS)
def test_readme_install_commands(readme):
    text = readme.read_text(encoding='utf-8')
    for command in [
        '/plugin marketplace add seanlee10/skills',
        '/plugin install seanlee10-skills@seanlee10',
        'codex plugin marketplace add seanlee10/skills',
        'codex plugin add seanlee10-skills@seanlee10',
        'devin plugins install seanlee10/skills',
        'hermes plugins install seanlee10/skills --enable',
        'npx skills@latest add seanlee10/skills -a <agent>',
    ]:
        assert command in text, command


_BINARY_SUFFIXES = {'.hwp', '.hwpx', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.traineddata'}


def _scanned_files():
    import subprocess
    # Tracked files plus untracked, non-ignored ones (so a new README is scanned before commit).
    names = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split('\0')
    for name in filter(None, names):
        if name.startswith(('bench/hwp-parser/samples/', 'skills/hwp-parser/tessdata/')):
            continue
        if Path(name).suffix.lower() in _BINARY_SUFFIXES:
            continue
        yield name


# The denylist is stored as SHA-256 digests of lowercased tokens so the names it guards
# against are never published, not even in this test.
_DENYLIST = {
    'f951d12b528d04dfc074a463e72871cccf2c5adb965fdfedfc2c567dbb80518b',
    '9e06e62fc54810d53d163875090d6154251a958bac0d623d991e52772fcc4c2f',
    '62a88e9c7af9f09da30271316f8cc165b8252524fefd7e6710607cdded35ca02',
    '95640109ddd9cb801caf47c841d80a95ee2ff1a1083257146f4f41dd808751e9',
    '24a9fd4373701b85f8e7a488fe416a3ab760aff1ca2d08448e5fecbc1cc43032',
}


def _denied(text):
    """Return True when any token of text hashes into _DENYLIST.

    Checked per token: every sub-token split on / \\ . _ -, every prefix (3+ chars) of those
    sub-tokens, and every pair of adjacent path segments (split on / or \\) joined by '/'.
    """
    import hashlib
    import re
    # The public yt-dlp dependency contains a token otherwise blocked by this check.
    for package in ('yt-dlp', 'yt_dlp'):
        text = re.sub(rf'(?<![a-z0-9_]){re.escape(package)}(?![a-z0-9_])', '', text, flags=re.I)
    candidates = set()
    for token in set(re.findall(r'[a-z0-9_./\\-]+', text.lower())):
        parts = [p for p in re.split(r'[/\\._-]+', token) if p]
        for part in parts:
            candidates.update(part[:n] for n in range(3, len(part) + 1))
        segments = [seg.strip('.') for seg in re.split(r'[/\\]', token)]
        candidates.update(f'{a}/{b}' for a, b in zip(segments, segments[1:]) if a and b)
    return any(hashlib.sha256(c.encode()).hexdigest() in _DENYLIST for c in candidates)


def test_public_youtube_dependency_names_are_allowed():
    assert not _denied('yt-dlp[default]==2026.10.21 yt_dlp https://github.com/yt-dlp/yt-dlp')
    assert not _denied('yt-dlp를 사용합니다.')


def test_no_internal_strings():
    import re
    import subprocess
    api_key = re.compile(r'(gsk_|xai-)[A-Za-z0-9]{20,}')
    files = list(_scanned_files())
    assert 'README.md' in files and 'tests/test_repo.py' in files
    texts = {name: (ROOT / name).read_text(encoding='utf-8') for name in files}
    texts['git log 61564dd..HEAD'] = subprocess.run(
        ['git', 'log', '--format=%B', '61564dd..HEAD'],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    hits = [name for name, text in texts.items() if _denied(text) or api_key.search(text)]
    assert not hits, hits
