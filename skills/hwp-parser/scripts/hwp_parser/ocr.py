"""Local OCR through the LiteParse `lit` CLI with the skill's bundled tessdata.

Never contacts an OCR server: `--ocr-server-url` is never passed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from .convert import hwp_to_pdf, run_group
from .extract import MAX_INPUT, Failure, walk
from .model import Document, Paragraph, Run

TESSDATA = Path(__file__).resolve().parents[2] / 'tessdata'
RASTER = {'.png', '.jpg', '.gif', '.bmp', '.tiff', '.webp'}
TIMEOUT = 180
# A rendered page is appended only when less than this share of its text is already in the direct text.
PAGE_SHARED_LIMIT = 0.5


def lit_path() -> Path:
    exe = 'lit.exe' if sys.platform == 'win32' else 'lit'
    beside = Path(sys.executable).parent / exe
    if beside.is_file():
        return beside
    found = shutil.which('lit')
    if found:
        return Path(found)
    raise Failure('LITEPARSE_NOT_AVAILABLE')


def _parse(path: Path, language: str, dpi: int) -> list[str]:
    """Run `lit parse` with OCR on and return the text of each page."""
    for lang in language.split('+'):
        if not (TESSDATA / f'{lang}.traineddata').is_file():
            raise Failure('TESSDATA_NOT_AVAILABLE')
    lit = lit_path()
    with tempfile.TemporaryDirectory(prefix='hwp2md-lit-') as tmp:
        out = Path(tmp) / 'out.json'
        cmd = [str(lit), 'parse', str(Path(path).resolve()), '--format', 'json',
               '--ocr-language', language, '--tessdata-path', str(TESSDATA),
               '--dpi', str(int(dpi)), '-o', str(out)]
        try:
            code = run_group(cmd, timeout=TIMEOUT, cwd=tmp)
        except (subprocess.TimeoutExpired, OSError):
            raise Failure('LITEPARSE_OCR_FAILED') from None
        if code != 0 or not out.is_file():
            raise Failure('LITEPARSE_OCR_FAILED')
        try:
            data = json.loads(out.read_text(encoding='utf-8'))
            pages = sorted(data['pages'], key=lambda p: p['page'])
            return [str(p.get('text') or '') for p in pages]
        except (ValueError, KeyError, TypeError):
            raise Failure('LITEPARSE_OCR_FAILED') from None


def _clean(text: str) -> str:
    """Collapse LiteParse's layout padding: single spaces inside lines, no blank lines."""
    lines = (re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.split('\n'))
    return '\n'.join(line for line in lines if line)


def ocr_image(path: Path, language: str = 'kor+eng', dpi: int = 200) -> str:
    return _clean('\n'.join(_parse(path, language, dpi)))


def ocr_pdf(path: Path, language: str = 'kor+eng', dpi: int = 200) -> list[str]:
    return [_clean(page) for page in _parse(path, language, dpi)]


def annotate(doc: Document, workdir: Path) -> dict[str, list[tuple[str, str]]]:
    """OCR every raster asset; returns notes keyed by asset id."""
    notes: dict[str, list[tuple[str, str]]] = {}
    for aid, asset in doc.assets.items():
        if asset.ext not in RASTER:
            continue
        path = Path(workdir) / f'{aid}{asset.ext}'
        path.write_bytes(asset.data)
        try:
            text = ocr_image(path)
        except Failure as e:
            if str(e) != 'LITEPARSE_OCR_FAILED':
                raise
            doc.warnings.append(f'OCR_FAILED:{aid}')
            continue
        finally:
            path.unlink(missing_ok=True)
        if text.strip():
            notes[aid] = [('ocr', text.strip())]
        else:
            doc.warnings.append(f'OCR_EMPTY:{aid}')
    return notes


def _normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace())


def trigrams(text: str) -> set[str]:
    t = _normalize(text)
    return {t[i:i + 3] for i in range(len(t) - 2)}


def shared_fraction(page: str, direct: str | set[str]) -> float:
    # Share = fraction of the page's distinct character 3-grams (NFKC, whitespace removed) found among the direct text's 3-grams.
    want = trigrams(page)
    if not want:
        return 1.0  # under 3 characters (e.g. a page number): too short to judge, never appended
    have = direct if isinstance(direct, set) else trigrams(direct)
    return len(want & have) / len(want)


def _direct_text(doc: Document) -> str:
    return '\n'.join(r.text for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs)


def append_pages(doc: Document, pages: list[str]) -> int:
    """Append OCR pages whose text is missing from the direct extraction; returns how many."""
    direct = trigrams(_direct_text(doc))
    missing = [(n, text.strip()) for n, text in enumerate(pages, 1)
               if _normalize(text) and shared_fraction(text, direct) < PAGE_SHARED_LIMIT]
    if not missing:
        return 0
    doc.blocks.append(Paragraph([Run('OCR (rendered pages)')], heading=1))
    for n, text in missing:
        doc.blocks.append(Paragraph([Run(f'Page {n}')], heading=2))
        doc.blocks.append(Paragraph([Run(text)]))
    return len(missing)


def _pdf_input(pdf: Path) -> Path:
    path = Path(pdf).resolve()
    try:
        ok = path.is_file() and path.stat().st_size <= MAX_INPUT
        if ok:
            with path.open('rb') as f:
                ok = f.read(5) == b'%PDF-'
    except OSError:
        ok = False
    if not ok:
        raise Failure('INVALID_PDF_INPUT')
    return path


def hook(doc: Document, input: Path, ocr: bool = False, pdf: Path | str | None = None,
         vlm: str | None = None, **_):
    """hwp2md annotation hook for --ocr and --pdf; returns ('ocr', notes), or None if OCR added nothing."""
    if not ocr and pdf is None:
        return None
    notes: dict[str, list[tuple[str, str]]] = {}
    with tempfile.TemporaryDirectory(prefix='hwp2md-ocr-') as tmp:
        workdir = Path(tmp)
        if pdf is not None:
            if isinstance(pdf, str) and pdf == 'auto':
                if doc.format != 'hwp':
                    raise Failure('HWPX_PDF_CONVERSION_UNSUPPORTED')
                pdf_path = hwp_to_pdf(Path(input), workdir)
                doc.warnings.append('EXPERIMENTAL_PDF_CONVERSION')
            else:
                pdf_path = _pdf_input(Path(pdf))
            pages = ocr_pdf(pdf_path)
        if ocr:
            notes = annotate(doc, workdir)
        appended = append_pages(doc, pages) if pdf is not None else 0
    return ('ocr', notes) if notes or appended else None
