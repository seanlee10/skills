"""Experimental local HWP 5 -> ODT (pyhwp) -> PDF (LibreOffice) conversion.

The layout is approximate; use the result only as an OCR source, never as a faithful rendering.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import zipfile
from pathlib import Path

from .extract import Failure, hwp_child_limits

OLE_MAGIC = bytes.fromhex('d0cf11e0a1b11ae1')
MACOS_SOFFICE = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
# pyhwp's hwp5odt CLI always RelaxNG-validates and rejects real documents; build the package
# with validation off instead (relaxng_compile=False skips the validator).
ODT_CHILD = '''import sys
from contextlib import closing
from hwp5.hwp5odt import ODTTransform, open_odtpkg
from hwp5.xmlmodel import Hwp5File
transform = ODTTransform(relaxng_compile=False)
with closing(Hwp5File(sys.argv[1])) as hwp, open_odtpkg(sys.argv[2]) as pkg:
    transform.transform_hwp5_to_package(hwp, pkg)
'''


def run_group(cmd: list[str], timeout: float, cwd: Path | str | None = None, preexec_fn=None) -> int:
    """Run cmd silently in its own session; on timeout kill the whole process group and re-raise."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=preexec_fn)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, 'killpg'):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
        proc.wait()
        raise


def _soffice(soffice: str | None) -> str:
    found = soffice or shutil.which('soffice') or shutil.which('libreoffice')
    if not found and Path(MACOS_SOFFICE).is_file():
        found = MACOS_SOFFICE
    if not found or not Path(found).is_file():
        raise Failure('LOCAL_LIBREOFFICE_NOT_AVAILABLE')
    return found


def hwp_to_odt(src: Path, odt: Path) -> Path:
    """pyhwp HWP 5 -> ODT in a resource-limited child (90 s)."""
    if importlib.util.find_spec('hwp5') is None:
        raise Failure('INSTALL_PYHWP_REQUIREMENTS_IN_THIS_PYTHON')
    try:
        code = run_group([sys.executable, '-I', '-B', '-c', ODT_CHILD, str(src), str(odt)], timeout=90,
                         cwd=odt.parent, preexec_fn=hwp_child_limits if os.name == 'posix' else None)
    except (subprocess.TimeoutExpired, OSError):
        raise Failure('ODT_CONVERSION_FAILED') from None
    if code != 0 or not odt.is_file():
        raise Failure('ODT_CONVERSION_FAILED')
    try:
        with zipfile.ZipFile(odt) as z:
            names = set(z.namelist())
            if (z.read('mimetype') != b'application/vnd.oasis.opendocument.text'
                    or not {'content.xml', 'styles.xml'} <= names):
                raise Failure('INVALID_ODT_OUTPUT')
    except (zipfile.BadZipFile, KeyError):
        raise Failure('INVALID_ODT_OUTPUT') from None
    return odt


def hwp_to_pdf(src: Path, workdir: Path, soffice: str | None = None) -> Path:
    """Convert an HWP 5 file to workdir/converted.pdf and return that path."""
    src, workdir = Path(src).resolve(), Path(workdir).resolve()
    with src.open('rb') as f:
        if f.read(8) != OLE_MAGIC:
            raise Failure('HWPX_PDF_CONVERSION_UNSUPPORTED')
    office = _soffice(soffice)
    odt = hwp_to_odt(src, workdir / 'converted.odt')
    profile = workdir / 'lo-profile'
    try:
        code = run_group([office, '-env:UserInstallation=' + profile.as_uri(), '--headless',
                          '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(workdir), str(odt)],
                         timeout=120, cwd=workdir)
    except (subprocess.TimeoutExpired, OSError):
        raise Failure('PDF_CONVERSION_FAILED') from None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    pdf = workdir / 'converted.pdf'
    if code != 0 or not pdf.is_file():
        raise Failure('PDF_CONVERSION_FAILED')
    with pdf.open('rb') as f:
        if f.read(5) != b'%PDF-':
            raise Failure('PDF_CONVERSION_FAILED')
    return pdf
