# /// script
# requires-python = "==3.11.*"
# dependencies = [
#     "defusedxml==0.7.1",
#     "olefile==0.47",
#     "pyhwp==0.1b15",
#     "six==1.17.0",
#     "lxml==6.1.3",
#     "liteparse==2.14.6",
#     "rapidfuzz==3.14.6",
# ]
# ///
"""Reproducible accuracy benchmark for hwp-parser.

Usage: uv run bench/hwp-parser/run.py [--check] [--update-readme] [--with-vlm]

  (default)        run every system on every sample, write results.json and results.md
  --check          run again, write nothing, exit 1 if any hwp-parser char_accuracy is below
                   the committed results.json value minus 0.01
  --update-readme  after writing the results, replace the text between
                   <!-- bench:start --> and <!-- bench:end --> in README.md with results.md
  --with-vlm       also measure `hwp-parser --vlm groq` (needs GROQ_API_KEY; sends images to Groq)

Reference text = `lit parse <sample>.pdf --no-ocr --format text` (Hancom Docs PDF text layer).
Each hwp2md run is a separate subprocess of this interpreter, so `seconds` is per run.
Converted outputs go to bench/hwp-parser/out/ (gitignored).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import datetime
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = REPO / 'skills' / 'hwp-parser' / 'scripts'
HWP2MD = SCRIPTS / 'hwp2md.py'
SAMPLES = HERE / 'samples'
OUT = HERE / 'out'
RESULTS_JSON = HERE / 'results.json'
RESULTS_MD = HERE / 'results.md'
README = REPO / 'README.md'

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

from metrics import char_accuracy, count_tables, strip_markdown, word_f1  # noqa: E402

DOCS = ['prospectus', 'pharma-disclosure', 'youth-rfp']
LLAMAPARSE = 'LlamaParse (cloud)'
VLM = 'hwp-parser --vlm groq'
# name -> (hwp2md arguments, output folder); LlamaParse is read from samples/.
HWP_SYSTEMS = {
    'hwp-parser': ([], 'direct'),
    'hwp-parser --ocr': (['--ocr'], 'ocr'),
    VLM: (['--vlm', 'groq'], 'vlm-groq'),
}
SYSTEMS = ['hwp-parser', 'hwp-parser --ocr', LLAMAPARSE, VLM]
METRICS = ('char_accuracy', 'word_f1', 'tables', 'seconds')
START, END = '<!-- bench:start -->', '<!-- bench:end -->'
TOLERANCE = 0.01
RUN_TIMEOUT = 1800


class BenchError(Exception):
    pass


# ---------------------------------------------------------------- helpers (unit-tested)

def _readme_text(readme: Path) -> str:
    if not readme.is_file():
        raise BenchError(f'{readme.name} not found at {readme}; cannot --update-readme')
    text = readme.read_text(encoding='utf-8')
    start, end = text.find(START), text.find(END)
    if start < 0 or end < 0 or end < start:
        raise BenchError(f'{readme.name} lacks the {START} ... {END} markers; cannot --update-readme')
    return text


def check_readme(readme: Path) -> None:
    """Fail early (before the slow run) if --update-readme cannot succeed."""
    _readme_text(Path(readme))


def update_readme(readme: Path, block: str) -> None:
    """Replace the text between the bench markers in `readme` with `block`."""
    readme = Path(readme)
    text = _readme_text(readme)
    head = text[:text.find(START) + len(START)]
    readme.write_text(head + '\n' + block.rstrip('\n') + '\n' + text[text.find(END):], encoding='utf-8')


def regressions(committed: dict, current: dict) -> list[tuple[str, str, float, float]]:
    """(doc, system, current, committed) for each hwp-parser char_accuracy below committed - 0.01."""
    found = []
    for doc, systems in committed.get('results', {}).items():
        for system, row in systems.items():
            if not system.startswith('hwp-parser'):
                continue
            old = (row or {}).get('char_accuracy')
            if old is None:
                continue
            new = ((current.get('results', {}).get(doc) or {}).get(system) or {}).get('char_accuracy')
            if new is None or new < round(old - TOLERANCE, 6):
                found.append((doc, system, new, old))
    return found


# ---------------------------------------------------------------- running

def _lit() -> Path:
    from hwp_parser.ocr import lit_path
    return lit_path()


def _git_sha() -> str:
    try:
        sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=REPO,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'
    return sha + ('-dirty' if dirty else '')


def _versions() -> dict:
    lit = subprocess.run([str(_lit()), '--version'], capture_output=True, text=True).stdout.strip()
    pkgs = {name: importlib.metadata.version(name) for name in ('liteparse', 'pyhwp', 'rapidfuzz')}
    return {'python': platform.python_version(), 'lit': lit, **pkgs}


def reference_text(pdf: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(_lit()), 'parse', str(pdf), '--no-ocr', '--format', 'text', '-o', str(dest), '-q']
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0 or not dest.is_file():
        raise BenchError(f'lit parse failed for {pdf.name} (exit {proc.returncode})')
    return dest.read_text(encoding='utf-8')


def run_hwp2md(hwp: Path, out_dir: Path, args: list[str]) -> tuple[str | None, float, str | None]:
    """Convert with hwp2md in a fresh subprocess; returns (markdown, seconds, error code)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(HWP2MD), str(hwp), '--out-dir', str(out_dir), '--force', *args]
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return None, time.perf_counter() - t0, 'TIMEOUT'
    seconds = time.perf_counter() - t0
    if proc.returncode != 0:
        try:
            code = json.loads(proc.stderr.strip().splitlines()[-1])['error']
        except (ValueError, KeyError, IndexError, TypeError):
            code = f'EXIT_{proc.returncode}'
        return None, seconds, code
    summary = json.loads(proc.stdout)
    return Path(summary['markdown']).read_text(encoding='utf-8'), seconds, None


def score(ref: str, md: str, seconds: float | None) -> dict:
    text = strip_markdown(md)
    return {
        'status': 'ok',
        'char_accuracy': round(char_accuracy(ref, text), 3),
        'word_f1': round(word_f1(ref, text), 3),
        'tables': count_tables(md),
        'seconds': None if seconds is None else round(seconds, 3),
    }


def _not_measured(status: str, seconds: float | None = None) -> dict:
    return {'status': status, 'char_accuracy': None, 'word_f1': None, 'tables': None,
            'seconds': None if seconds is None else round(seconds, 3)}


def run_bench(with_vlm: bool = False) -> dict:
    vlm_on = with_vlm and bool(os.environ.get('GROQ_API_KEY'))
    results: dict[str, dict] = {}
    for doc in DOCS:
        hwp, pdf = SAMPLES / f'{doc}.hwp', SAMPLES / f'{doc}.pdf'
        ref = reference_text(pdf, OUT / 'reference' / f'{doc}.txt')
        row: dict[str, dict] = {}
        for system in SYSTEMS:
            if system == LLAMAPARSE:
                md = (SAMPLES / f'{doc}.llamaparse.md').read_text(encoding='utf-8')
                row[system] = score(ref, md, None)
                continue
            if system == VLM and not vlm_on:
                row[system] = _not_measured('not measured')
                continue
            args, folder = HWP_SYSTEMS[system]
            sys.stderr.write(f'[bench] {doc}: {system}\n')
            md, seconds, error = run_hwp2md(hwp, OUT / folder, args)
            row[system] = score(ref, md, seconds) if error is None else _not_measured(f'failed: {error}', seconds)
        results[doc] = row
    mean = {}
    for system in SYSTEMS:
        rows = [results[d][system] for d in DOCS]
        mean[system] = {m: (round(sum(r[m] for r in rows) / len(rows), 3)
                            if all(r[m] is not None for r in rows) else None) for m in METRICS}
    return {
        'date': datetime.date.today().isoformat(),
        'git_sha': _git_sha(),
        'versions': _versions(),
        'reference': 'Hancom Docs PDF text layer: lit parse <pdf> --no-ocr --format text',
        'rounding': 'fractions in [0, 1] rounded to 3 decimals; seconds rounded to 3 decimals',
        'docs': DOCS,
        'systems': SYSTEMS,
        'results': results,
        'mean': mean,
    }


# ---------------------------------------------------------------- reporting

def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return '—'
    return f'{value:.{digits}f}' if isinstance(value, float) else str(value)


def render_md(data: dict) -> str:
    v = data['versions']
    lines = [
        '### hwp-parser accuracy benchmark',
        '',
        f'3 public HWP 5 documents; reference = Hancom Docs PDF text layer (extracted with LiteParse '
        f'{v["liteparse"]}, no OCR); LlamaParse output supplied by the repository author, generation settings unknown. '
        'Running headers and page numbers present only in the PDF lower both metrics for every system. '
        'This is a small, specific comparison, not a general claim.',
        '',
        '| Document | System | char_accuracy | word_f1 | tables | seconds |',
        '| --- | --- | ---: | ---: | ---: | ---: |',
    ]
    for doc in data['docs']:
        for system in data['systems']:
            r = data['results'][doc][system]
            if r['status'] != 'ok':
                lines.append(f'| {doc} | {system} | {r["status"]} | | | |')
                continue
            lines.append(f'| {doc} | {system} | {_fmt(r["char_accuracy"])} | {_fmt(r["word_f1"])} | '
                         f'{_fmt(r["tables"])} | {_fmt(r["seconds"], 1)} |')
    for system in data['systems']:
        m = data['mean'][system]
        if m['char_accuracy'] is None:
            status = {data['results'][d][system]['status'] for d in data['docs']}
            lines.append(f'| **Mean** | {system} | {", ".join(sorted(status))} | | | |')
            continue
        lines.append(f'| **Mean** | {system} | **{_fmt(m["char_accuracy"])}** | **{_fmt(m["word_f1"])}** | '
                     f'{_fmt(m["tables"], 1)} | {_fmt(m["seconds"], 1)} |')
    lines += [
        '',
        'char_accuracy = max(0, 1 − Levenshtein distance / reference length) after NFC and removing all '
        'whitespace; word_f1 = multiset F1 over whitespace tokens. Markdown/HTML syntax is stripped from '
        'each output before scoring. Values are fractions in [0, 1], rounded to 3 decimals; `tables` counts '
        'top-level HTML and GFM tables in the output; `seconds` is wall time of one hwp2md subprocess '
        '(— for LlamaParse, which was not run here). "not measured": `--vlm groq` runs only with '
        '`--with-vlm` and `GROQ_API_KEY` set.',
        '',
        f'Date {data["date"]} · git {data["git_sha"]} · Python {v["python"]} · {v["lit"]} · '
        f'pyhwp {v["pyhwp"]} · rapidfuzz {v["rapidfuzz"]} · reproduce with `uv run bench/hwp-parser/run.py`.',
    ]
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='hwp-parser accuracy benchmark')
    p.add_argument('--check', action='store_true',
                   help='re-run and fail if hwp-parser char_accuracy regressed by more than 0.01')
    p.add_argument('--update-readme', action='store_true',
                   help='replace the README.md bench block with results.md')
    p.add_argument('--with-vlm', action='store_true',
                   help='also measure --vlm groq (requires GROQ_API_KEY; sends images to Groq)')
    args = p.parse_args(argv)
    try:
        if args.update_readme:
            check_readme(README)
        committed = None
        if args.check:
            if not RESULTS_JSON.is_file():
                raise BenchError('results.json not found; run without --check first')
            committed = json.loads(RESULTS_JSON.read_text(encoding='utf-8'))
        if args.with_vlm and not os.environ.get('GROQ_API_KEY'):
            sys.stderr.write('[bench] --with-vlm given but GROQ_API_KEY is not set: VLM not measured\n')
        data = run_bench(with_vlm=args.with_vlm)
        if committed is not None:
            bad = regressions(committed, data)
            for doc, system, new, old in bad:
                sys.stderr.write(f'[bench] REGRESSION {doc} / {system}: {_fmt(new)} < {old:.3f} - {TOLERANCE}\n')
            if bad:
                return 1
            sys.stderr.write('[bench] check passed: no hwp-parser char_accuracy regression\n')
            return 0
        RESULTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        md = render_md(data)
        RESULTS_MD.write_text(md, encoding='utf-8')
        sys.stdout.write(md)
        if args.update_readme:
            update_readme(README, md)
            sys.stderr.write('[bench] README.md updated\n')
    except BenchError as e:
        sys.stderr.write(f'[bench] error: {e}\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
