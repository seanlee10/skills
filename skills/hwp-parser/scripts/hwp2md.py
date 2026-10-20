# /// script
# requires-python = "==3.11.*"
# dependencies = [
#     "defusedxml==0.7.1",
#     "olefile==0.47",
#     "pyhwp==0.1b15",
#     "six==1.17.0",
#     "lxml==6.1.3",
#     "liteparse==2.14.6",
# ]
# ///
"""Convert an .hwp / .hwpx document to Markdown with an assets folder.

Usage: uv run hwp2md.py INPUT [--out-dir DIR] [--force] [--ocr] [--pdf PDF|auto] [--vlm {groq,xai}]
       uv run hwp2md.py --check-vlm {groq,xai}   (key preflight: no network, no INPUT)

Exit 0: JSON summary on stdout. Exit 2: {"status":"failed","error":CODE,"message":str} on stderr.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside the skill folder

import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path

from hwp_parser import ocr as _ocr
from hwp_parser import vlm as _vlm
from hwp_parser.extract import Failure, extract, walk
from hwp_parser.markdown import asset_filename, render
from hwp_parser.model import Image, Paragraph, Table

# Fixed English message per error code. Never include document text, paths or tracebacks.
MESSAGES = {
    # extract.py: input and container
    'MISSING_OR_OVERSIZE_INPUT': 'The input file does not exist, is not a regular file, or exceeds 128 MiB.',
    'UNSUPPORTED_SIGNATURE_HWP3_OR_OTHER': 'The input is neither HWP 5 nor HWPX (HWP 3 and other formats are not supported).',
    # extract.py: HWPX package
    'UNSAFE_PACKAGE_PATH': 'The HWPX package contains an unsafe member path.',
    'XML_DTD_OR_ENTITY_FORBIDDEN': 'The document XML declares a DTD or entities, which are not allowed.',
    'MALFORMED_XML': 'The document XML is malformed.',
    'INVALID_OR_OVERSIZE_DEFLATE': 'A compressed stream is invalid or expands beyond the size limit.',
    'ASSET_TOO_LARGE': 'An embedded asset exceeds the 64 MiB limit.',
    'DUPLICATE_OR_TOO_MANY_MEMBERS': 'The HWPX package has duplicate members or more than 4096 members.',
    'PACKAGE_TOO_LARGE': 'The HWPX package expands beyond the 256 MiB limit.',
    'ENCRYPTED_PACKAGE': 'The HWPX package is encrypted.',
    'NOT_HWPX_MIMETYPE': 'The ZIP file does not declare the HWPX mimetype.',
    'MISSING_PACKAGE_SPINE': 'The HWPX package has no readable manifest or spine.',
    'INVALID_MANIFEST_ID': 'The HWPX manifest has an invalid or duplicate item id.',
    'BROKEN_SPINE_REFERENCE': 'The HWPX spine references a missing manifest item.',
    'MISSING_OR_DUPLICATE_SECTIONS': 'The HWPX package has missing or duplicate body sections.',
    'SECTION_SPINE_MISMATCH': 'The HWPX body sections do not match the spine.',
    # extract.py: HWP 5
    'INSTALL_PYHWP_REQUIREMENTS_IN_THIS_PYTHON': 'pyhwp is not installed in this Python; run through uv so the pinned requirements are used.',
    'PYHWP_XML_FAILED': 'pyhwp could not convert the HWP 5 document (failed, timed out or hit a resource limit).',
    'NOT_HWP5': 'The OLE file is not an HWP 5 document.',
    'UNSUPPORTED_HWP_VERSION': 'This HWP 5 version is not supported.',
    'PASSWORD_PROTECTED_HWP': 'The HWP document is password protected.',
    'DISTRIBUTION_HWP_REQUIRES_AUTHORIZED_CONVERSION': 'The HWP document is a distribution document; convert it with an authorized viewer first.',
    'DRM_OR_CERTIFICATE_ENCRYPTED_HWP': 'The HWP document is DRM or certificate encrypted.',
    'OLE_TOO_LARGE': 'The HWP document streams exceed the size limit.',
    'CONFLICTING_BINDATA_COMPRESSION': 'The HWP document has conflicting compression flags for embedded data.',
    'ASSETS_TOO_LARGE': 'The embedded assets together exceed the 256 MiB limit.',
    # hwp2md.py
    'USAGE_ERROR': 'Invalid command-line arguments. Usage: hwp2md.py INPUT [--out-dir DIR] [--force] [--ocr] [--pdf PDF|auto] [--vlm {groq,xai}] | hwp2md.py --check-vlm {groq,xai}',
    'OUTPUT_ALREADY_EXISTS': 'The output Markdown file or assets folder already exists; pass --force to replace it.',
    'NO_EXTRACTABLE_TEXT': 'The document has no extractable text (it may be scanned images); retry with --ocr.',
    'UNSAFE_ASSET_NAME': 'An embedded asset has an unsafe file name.',
    # ocr.py
    'LITEPARSE_NOT_AVAILABLE': 'The LiteParse `lit` command was not found; run through uv so the pinned requirements are used.',
    'TESSDATA_NOT_AVAILABLE': 'The bundled OCR language data (tessdata) is missing from the skill folder.',
    'LITEPARSE_OCR_FAILED': 'LiteParse OCR failed or timed out.',
    'INVALID_PDF_INPUT': 'The --pdf file does not exist, exceeds 128 MiB, or is not a PDF.',
    # convert.py (--pdf auto)
    'HWPX_PDF_CONVERSION_UNSUPPORTED': '--pdf auto supports HWP 5 only; export a PDF from Hancom and pass it with --pdf.',
    'LOCAL_LIBREOFFICE_NOT_AVAILABLE': '--pdf auto needs a local LibreOffice (soffice); install it or pass an exported PDF with --pdf.',
    'ODT_CONVERSION_FAILED': 'pyhwp could not convert the HWP 5 document to ODT for --pdf auto.',
    'INVALID_ODT_OUTPUT': 'The intermediate ODT produced for --pdf auto is invalid.',
    'PDF_CONVERSION_FAILED': 'LibreOffice could not convert the document to PDF for --pdf auto.',
    # vlm.py (--vlm groq|xai)
    'GROQ_API_KEY_MISSING': '--vlm groq needs the GROQ_API_KEY environment variable; nothing was sent.',
    'XAI_API_KEY_MISSING': '--vlm xai needs the XAI_API_KEY environment variable; nothing was sent.',
    # Dynamic codes <PROVIDER>_HTTP_<status> (e.g. GROQ_HTTP_401) all map to this message; see message_for().
    'VLM_HTTP_ERROR': 'The VLM provider rejected the request; the error code carries the HTTP status.',
    'VLM_NETWORK_ERROR': 'The VLM provider could not be reached or timed out.',
    'VLM_BAD_RESPONSE': 'The VLM provider returned a malformed or oversized response.',
    'VLM_UNSUPPORTED_IMAGE': 'Only PNG or JPEG images of at most 3 MiB can be sent to the VLM provider.',
}
GENERIC_MESSAGE = 'Unexpected internal error during conversion.'
_HTTP_CODE = re.compile(r'(GROQ|XAI)_HTTP_\d{1,3}')

# Annotation hooks (OCR / VLM). Each is called as hook(doc, input=..., ocr=..., pdf=..., vlm=...)
# and returns None or (path_name, notes) where notes maps asset id -> [(source, text), ...].
# Hooks run on every conversion and check their own flag. --pdf may be a path or 'auto'.
annotate_hooks: list = [_ocr.hook, _vlm.hook]


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse's message may echo arguments; keep it out of stderr
        raise Failure('USAGE_ERROR')


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog='hwp2md.py', description='Convert .hwp/.hwpx to Markdown.')
    p.add_argument('input', type=Path, nargs='?')  # required unless --check-vlm
    p.add_argument('--out-dir', type=Path)
    p.add_argument('--force', action='store_true')
    p.add_argument('--ocr', action='store_true')
    p.add_argument('--pdf')  # a PDF path, or exactly 'auto' (experimental, HWP 5 only)
    p.add_argument('--vlm', choices=['groq', 'xai'])
    p.add_argument('--check-vlm', choices=['groq', 'xai'])  # key preflight only
    return p


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _has_text(doc, notes: dict) -> bool:
    if any(text.strip() for items in notes.values() for source, text in items if source == 'ocr'):
        return True
    return any(r.text.strip() for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs)


def convert(input: Path, out_dir: Path | None, force: bool, ocr: bool,
            pdf: Path | str | None, vlm: str | None) -> dict:
    if pdf is not None and not (isinstance(pdf, str) and pdf == 'auto'):
        pdf = Path(pdf).resolve()  # only the exact string 'auto' is the keyword; './auto' is a path
    src = Path(input).resolve()
    target_dir = Path(out_dir).resolve() if out_dir is not None else src.parent
    stem = src.stem
    md_path = target_dir / f'{stem}.md'
    assets_name = f'{stem}_assets'
    assets_path = target_dir / assets_name
    if not force and (_exists(md_path) or _exists(assets_path)):
        raise Failure('OUTPUT_ALREADY_EXISTS')

    doc = extract(src)
    use_ocr = ocr or pdf is not None
    if 'NO_EXTRACTABLE_TEXT' in doc.warnings and not use_ocr:
        raise Failure('NO_EXTRACTABLE_TEXT')
    if vlm is not None:
        _vlm.check(vlm)  # a missing key fails before any OCR or LibreOffice work
    paths = ['direct']
    notes: dict = {}
    for hook in annotate_hooks:
        result = hook(doc, input=src, ocr=ocr, pdf=pdf, vlm=vlm)
        if result:
            name, extra = result
            paths.append(name)
            for aid, items in extra.items():
                notes.setdefault(aid, []).extend(items)
    if 'NO_EXTRACTABLE_TEXT' in doc.warnings:
        if not _has_text(doc, notes):
            raise Failure('NO_EXTRACTABLE_TEXT')  # OCR (notes or rendered pages) found nothing either
        doc.warnings = [w for w in doc.warnings if w != 'NO_EXTRACTABLE_TEXT'] + ['OCR_ONLY_TEXT']
    doc.warnings = sorted(set(doc.warnings))

    names = {}
    for aid, asset in doc.assets.items():
        name = asset_filename(asset)
        if not name or Path(name).name != name or name in ('.', '..') or name in names.values():
            raise Failure('UNSAFE_ASSET_NAME')
        names[aid] = name
    text = render(doc, assets_name, notes)

    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.hwp2md-', suffix='.tmp', dir=target_dir))
    try:
        (tmp / md_path.name).write_text(text, encoding='utf-8')
        if doc.assets:
            (tmp / assets_name).mkdir()
            for aid, asset in doc.assets.items():
                (tmp / assets_name / names[aid]).write_bytes(asset.data)
        if force:
            _remove(md_path)
            _remove(assets_path)
        elif _exists(md_path) or _exists(assets_path):
            raise Failure('OUTPUT_ALREADY_EXISTS')
        if doc.assets:
            (tmp / assets_name).rename(assets_path)
        (tmp / md_path.name).rename(md_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    blocks = list(walk(doc.blocks))
    return {
        'status': 'ok',
        'markdown': str(md_path),
        'assets_dir': str(assets_path) if doc.assets else None,
        'tables': sum(isinstance(b, Table) for b in blocks),
        'images': sum(isinstance(b, Image) for b in blocks),
        'paths': paths,
        'warnings': list(doc.warnings),
    }


def message_for(code: str) -> str:
    if code in MESSAGES:
        return MESSAGES[code]
    if _HTTP_CODE.fullmatch(code):
        return MESSAGES['VLM_HTTP_ERROR']
    return GENERIC_MESSAGE


def _fail(code: str) -> int:
    message = message_for(code)
    sys.stderr.write(json.dumps({'status': 'failed', 'error': code, 'message': message},
                                ensure_ascii=False) + '\n')
    return 2


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.check_vlm is not None:
            # A query, not a conversion: only --check-vlm may be given, and the result is exit 0.
            others = (args.input, args.out_dir, args.pdf, args.vlm)
            if any(v is not None for v in others) or args.force or args.ocr:
                raise Failure('USAGE_ERROR')
            summary = _vlm.key_status(args.check_vlm)
        elif args.input is None:
            raise Failure('USAGE_ERROR')
        else:
            summary = convert(args.input, args.out_dir, args.force, args.ocr, args.pdf, args.vlm)
    except Failure as e:
        return _fail(str(e))  # codes are fixed identifiers; unknown ones get GENERIC_MESSAGE
    except Exception as e:  # never print tracebacks or document text
        return _fail(type(e).__name__)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
