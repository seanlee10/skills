"""Hermes Agent plugin: register every skills/<name>/SKILL.md with Hermes."""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / 'skills'

# Optional UTF-8 BOM; the closing fence may end the file without a newline.
_FRONTMATTER = re.compile(r'\A\ufeff?---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', re.S)


def _frontmatter(text):
    """Parse a flat `key: value` frontmatter block (stdlib only, no YAML).

    Returns None when the file has no frontmatter block.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(':')
        if not sep or not key.strip() or line[:1].isspace():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def register_skills(ctx, skills_dir):
    for skill_md in sorted(Path(skills_dir).glob('*/SKILL.md')):
        try:
            meta = _frontmatter(skill_md.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError):
            continue
        if not meta:
            continue
        description = meta.get('description', '').strip()
        if not description:
            continue  # Hermes cannot route to a skill without a description
        name = meta.get('name') or skill_md.parent.name
        # Hermes needs a pathlib.Path here; a str disables the whole plugin.
        ctx.register_skill(name, skill_md, description=description)


def register(ctx):
    register_skills(ctx, SKILLS_DIR)
