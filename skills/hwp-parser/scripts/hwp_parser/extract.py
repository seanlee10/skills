"""Local HWP5/HWPX extraction into an ordered Document; no network, no rendering, no decryption."""
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

from defusedxml import DefusedXmlException, ElementTree as ET

from .model import Asset, Cell, Document, Image, Paragraph, Run, Table
from .styles import StyleTable

MAX_INPUT = 128 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 4096

UNINTERPRETED = ('ole', 'OLE', 'equation', 'Equation', 'ShapeOLE', 'BinDataLink')
MAGIC = [
    ((b'\x89PNG\r\n\x1a\n',), 'image/png', '.png'),
    ((b'\xff\xd8\xff',), 'image/jpeg', '.jpg'),
    ((b'GIF87a', b'GIF89a'), 'image/gif', '.gif'),
    ((b'BM',), 'image/bmp', '.bmp'),
    ((b'II*\x00', b'MM\x00*'), 'image/tiff', '.tiff'),
]


class Failure(Exception):
    """Raised with a stable error code as its message."""


def local(e):
    return e.tag.rsplit('}', 1)[-1]


def safe_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise Failure('UNSAFE_PACKAGE_PATH')
    return name


def xml(data):
    try:
        return ET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise Failure('XML_DTD_OR_ENTITY_FORBIDDEN') from None
    except ET.ParseError:
        raise Failure('MALFORMED_XML') from None


def integer(value):
    return int(value) if value is not None else None


def inflate(data, warnings):
    d = zlib.decompressobj(-15)
    value = d.decompress(data, MAX_MEMBER + 1)
    if len(value) > MAX_MEMBER or d.unconsumed_tail or not d.eof:
        raise Failure('INVALID_OR_OVERSIZE_DEFLATE')
    if d.unused_data:
        warnings.append('DEFLATE_TRAILING_BYTES_IGNORED')
    return value


def add_asset(doc, data):
    if len(data) > MAX_MEMBER:
        raise Failure('ASSET_TOO_LARGE')
    media_type, ext = next(((m, x) for heads, m, x in MAGIC if data.startswith(heads)),
                           ('application/octet-stream', '.bin'))
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        media_type, ext = 'image/webp', '.webp'
    aid = 'a' + str(len(doc.assets))
    doc.assets[aid] = Asset(id=aid, data=data, ext=ext, media_type=media_type)
    if ext == '.bin':
        doc.warnings.append('UNINTERPRETED_BINARY:' + aid)
    return aid


class Builder:
    """Turns a section/body XML tree into blocks in XML reading order."""

    def __init__(self, mode, idmap, warnings, styles):
        self.mode, self.idmap, self.warnings, self.styles = mode, idmap, warnings, styles
        if mode == 'hwpx':
            self.ptag, self.ttag, self.ctag, self.texttag = 'p', 'tbl', 'tc', 't'
        else:
            self.ptag, self.ttag, self.ctag, self.texttag = 'Paragraph', 'TableControl', 'TableCell', 'Text'

    def blocks(self, e):
        """Blocks found under e (excluding e itself), outside any paragraph."""
        out = []
        for child in e:
            tag = local(child)
            if tag == self.ptag:
                out.extend(self.paragraph(child))
            elif tag == self.ttag:
                out.extend(self.table(child))
            elif self.is_image(tag):
                out.extend(self.image(child))
            else:
                self.note(tag)
                out.extend(self.blocks(child))
        return out

    def paragraph(self, p):
        out, runs = [], []
        emitted = False
        heading = self.styles.heading_level(p.get('styleIDRef' if self.mode == 'hwpx' else 'style-id'))

        def flush():
            nonlocal runs, emitted, heading
            if runs:
                # Only the first fragment of a split heading paragraph is the heading.
                out.append(Paragraph(runs=runs, heading=heading))
                runs, emitted, heading = [], True, None

        def visit(n, char=None):
            nonlocal emitted
            for child in n:
                tag = local(child)
                if tag == self.texttag:
                    bold, underline = self.styles.run_style(char if self.mode == 'hwpx' else child.get('charshape-id'))
                    runs.append(Run(text=self.content(child), bold=bold, underline=underline))
                elif tag == 'ControlChar':
                    code = child.get('code')
                    if code in ('9', '10'):
                        runs.append(Run(text='\t' if code == '9' else '\n'))
                    elif code in ('30', '31'):
                        runs.append(Run(text=' '))
                elif tag == self.ttag:
                    flush()
                    out.extend(self.table(child))
                    emitted = True
                elif self.is_image(tag):
                    flush()
                    found = self.image(child)
                    out.extend(found)
                    emitted = emitted or bool(found)
                elif tag == self.ptag:
                    # Paragraphs nested in text boxes, headers or notes keep their position.
                    flush()
                    out.extend(self.paragraph(child))
                    emitted = True
                else:
                    self.note(tag)
                    visit(child, child.get('charPrIDRef', char) if tag == 'run' else char)

        visit(p)
        flush()
        if not emitted:
            out.append(Paragraph(runs=[]))
        return out

    def content(self, n):
        # HWPX text has inline tab/lineBreak/fwSpace/nbSpace nodes; preserve their tail text.
        s = n.text or ''
        for child in n:
            kind = local(child)
            if kind == 'tab':
                s += '\t'
            elif kind in ('lineBreak', 'br'):
                s += '\n'
            elif kind in ('fwSpace', 'nbSpace'):  # 고정폭 빈칸 / 묶음 빈칸, like HWP 5 codes 30/31
                s += ' '
            else:
                s += self.content(child)
            s += child.tail or ''
        return s

    def table(self, t):
        """[Table, *blocks outside its cells (captions etc.), emitted right after it]."""
        cells, extra = [], []

        def find(n):
            for child in n:
                tag = local(child)
                if tag == self.ctag:
                    cells.append(self.cell(child))
                elif tag == self.ptag:
                    extra.extend(self.paragraph(child))
                elif tag == self.ttag:
                    extra.extend(self.table(child))
                elif self.is_image(tag):
                    extra.extend(self.image(child))
                else:
                    self.note(tag)
                    find(child)

        find(t)
        return [Table(cells=cells), *extra]

    def cell(self, e):
        if self.mode == 'hwpx':
            addr = next((x for x in e if local(x) == 'cellAddr'), None)
            span = next((x for x in e if local(x) == 'cellSpan'), None)
            row = integer(addr.get('rowAddr')) if addr is not None else None
            col = integer(addr.get('colAddr')) if addr is not None else None
            rowspan = integer(span.get('rowSpan')) if span is not None else None
            colspan = integer(span.get('colSpan')) if span is not None else None
        else:
            row, col, rowspan, colspan = (integer(e.get(k)) for k in ('row', 'col', 'rowspan', 'colspan'))
        header = e.get('header') in ('1', 'true')
        if row is None or col is None:
            self.warnings.append('CELL_ADDRESS_MISSING')
        return Cell(row=row, col=col, rowspan=rowspan or 1, colspan=colspan or 1,
                    blocks=self.blocks(e), header=header)

    @staticmethod
    def is_image(tag):
        return tag in ('img', 'PictureInfo')

    def image(self, e):
        bid = e.get('binaryItemIDRef') if self.mode == 'hwpx' else e.get('bindata-id')
        aid = self.idmap.get(bid)
        if aid is None:
            self.warnings.append('UNRESOLVED_IMAGE_REFERENCE')
            return []
        return [Image(asset_id=aid)]

    def note(self, tag):
        if tag in UNINTERPRETED:
            self.warnings.append('UNINTERPRETED_OBJECT:' + tag)


def hwpx(path, doc):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(infos) > MAX_FILES or len(set(names)) != len(names):
            raise Failure('DUPLICATE_OR_TOO_MANY_MEMBERS')
        if sum(i.file_size for i in infos) > MAX_TOTAL or any(i.file_size > MAX_MEMBER for i in infos):
            raise Failure('PACKAGE_TOO_LARGE')
        for i in infos:
            safe_name(i.filename)
            if i.flag_bits & 1:
                raise Failure('ENCRYPTED_PACKAGE')
        if 'mimetype' not in names or z.read('mimetype').strip() != b'application/hwp+zip':
            raise Failure('NOT_HWPX_MIMETYPE')
        roots = {}
        for n in names:
            if n.lower().endswith(('.xml', '.hpf')):
                root = xml(z.read(n))
                if any('encryption' in local(e).lower() for e in root.iter()):
                    raise Failure('ENCRYPTED_PACKAGE')
                roots[n] = root
        if 'Contents/content.hpf' not in roots:
            raise Failure('MISSING_PACKAGE_SPINE')
        package = roots['Contents/content.hpf']
        manifest = {}
        for e in package.iter():
            if local(e) == 'item':
                bid, href = e.get('id'), e.get('href', '')
                # Hancom packages use root-relative hrefs; also support OPF-relative paths.
                if not bid or bid in manifest:
                    raise Failure('INVALID_MANIFEST_ID')
                safe_name(href)
                candidates = [href, posixpath.normpath('Contents/' + href)]
                target = next((v for v in candidates if v in names), None)
                manifest[bid] = target
                if target is None:
                    doc.warnings.append('MISSING_MANIFEST_TARGET:' + bid)
        sections = []
        for e in package.iter():
            if local(e) == 'itemref':
                target = manifest.get(e.get('idref'))
                if target is None:
                    raise Failure('BROKEN_SPINE_REFERENCE')
                if re.fullmatch(r'Contents/section\d+\.xml', target):
                    sections.append(target)
        if not sections or len(set(sections)) != len(sections):
            raise Failure('MISSING_OR_DUPLICATE_SECTIONS')
        all_sections = {n for n in names if re.fullmatch(r'Contents/section\d+\.xml', n)}
        if all_sections != set(sections):
            raise Failure('SECTION_SPINE_MISMATCH')
        idmap = {}
        for name in names:
            if name.startswith('BinData/') and not name.endswith('/'):
                ids = [key for key, value in manifest.items() if value == name]
                aid = add_asset(doc, z.read(name))
                idmap.update({key: aid for key in ids})
        builder = Builder('hwpx', idmap, doc.warnings, StyleTable.from_hwpx(roots.get('Contents/header.xml')))
        for section in sections:
            doc.blocks.extend(builder.blocks(roots[section]))
        if any(n.startswith('Scripts/') for n in names):
            doc.warnings.append('SCRIPTS_PRESENT_NOT_EXECUTED')
        for n, root in roots.items():
            if n not in sections and any(local(e) == 't' for e in root.iter()):
                doc.warnings.append('TEXT_OUTSIDE_SECTIONS_REQUIRES_REVIEW:' + n)


def hwp_child_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TOTAL, MAX_TOTAL))
    # Address-space limits work on Linux; macOS Python/lxml uses large mappings.
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def hwp5_xml(path):
    """Run pyhwp's hwp5proc in a resource-limited child; raw XML lives only in a temp dir."""
    proc = Path(sys.executable).parent / ('hwp5proc.exe' if os.name == 'nt' else 'hwp5proc')
    if not proc.is_file():
        raise Failure('INSTALL_PYHWP_REQUIREMENTS_IN_THIS_PYTHON')
    with tempfile.TemporaryDirectory(prefix='hwp-extract-') as td:
        raw = Path(td) / 'hwp5.xml'
        with raw.open('wb') as f:
            try:
                completed = subprocess.run([str(proc), 'xml', str(path)], stdout=f,
                    stderr=subprocess.DEVNULL, timeout=90,
                    preexec_fn=hwp_child_limits if os.name == 'posix' else None)
            except subprocess.TimeoutExpired:
                raise Failure('PYHWP_XML_FAILED') from None
        if completed.returncode or raw.stat().st_size > MAX_TOTAL:
            raise Failure('PYHWP_XML_FAILED')
        return xml(raw.read_bytes())


def hwp(path, doc):
    import olefile
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists('FileHeader'):
            raise Failure('NOT_HWP5')
        header = ole.openstream('FileHeader').read(256)
        if len(header) < 40 or header[:32] != b'HWP Document File'.ljust(32, b'\x00') or header[35] != 5:
            raise Failure('UNSUPPORTED_HWP_VERSION')
        flags = struct.unpack_from('<I', header, 36)[0]
        if flags & 2:
            raise Failure('PASSWORD_PROTECTED_HWP')
        if flags & 4:
            raise Failure('DISTRIBUTION_HWP_REQUIRES_AUTHORIZED_CONVERSION')
        if flags & ((1 << 4) | (1 << 8) | (1 << 10)):
            raise Failure('DRM_OR_CERTIFICATE_ENCRYPTED_HWP')
        if flags & ((1 << 7) | (1 << 9)):
            doc.warnings.append('SIGNATURE_NOT_VALIDATED')
        if flags & (1 << 6):
            doc.warnings.append('DOCUMENT_HISTORY_NOT_EXTRACTED')
        streams = ole.listdir(streams=True, storages=False)
        if len(streams) > MAX_FILES or sum(ole.get_size(s) for s in streams) > MAX_TOTAL:
            raise Failure('OLE_TOO_LARGE')
        root = hwp5_xml(path)
        bindata = [e for e in root.iter() if local(e) == 'BinData']
        spec = {}
        for i, e in enumerate(bindata, 1):
            child = next(iter(e), None)
            if child is not None and local(child) == 'BinDataEmbedding':
                name = 'BinData/' + child.get('storage-id', '') + '.' + child.get('ext', '')
                spec.setdefault(name.lower(), []).append((str(i), e.get('compression', 'storage_default')))
            elif e.get('storage') == 'link':
                doc.warnings.append('EXTERNAL_BINDATA_LINK_NOT_FETCHED')
        idmap = {}
        expanded = 0
        for parts in streams:
            if parts[0] != 'BinData':
                continue
            name = '/'.join(parts)
            if ole.get_size(parts) > MAX_MEMBER:
                raise Failure('ASSET_TOO_LARGE')
            data = ole.openstream(parts).read()
            entries = spec.get(name.lower(), [])
            policies = {compression for _, compression in entries}
            if len(policies) > 1:
                raise Failure('CONFLICTING_BINDATA_COMPRESSION')
            policy = next(iter(policies), 'storage_default')
            if policy == 'yes' or (policy == 'storage_default' and flags & 1):
                data = inflate(data, doc.warnings)
            expanded += len(data)
            if expanded > MAX_TOTAL:
                raise Failure('ASSETS_TOO_LARGE')
            aid = add_asset(doc, data)
            idmap.update({key: aid for key, _ in entries})
        doc.blocks.extend(Builder('hwp', idmap, doc.warnings, StyleTable.from_hwp5(root)).blocks(root))
        doc.warnings.append('PYHWP_EXPERIMENTAL_COVERAGE')
        if flags & 8:
            doc.warnings.append('SCRIPTS_PRESENT_NOT_EXECUTED')


def extract(path):
    """Parse an .hwp (HWP 5) or .hwpx file into a Document, entirely in memory."""
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise Failure('MISSING_OR_OVERSIZE_INPUT')
    with path.open('rb') as source:
        head = source.read(8)
    mode = 'hwpx' if zipfile.is_zipfile(path) else 'hwp' if head == bytes.fromhex('d0cf11e0a1b11ae1') else None
    if mode is None:
        raise Failure('UNSUPPORTED_SIGNATURE_HWP3_OR_OTHER')
    doc = Document(format=mode, blocks=[], assets={}, warnings=[])
    (hwpx if mode == 'hwpx' else hwp)(path, doc)
    if not any(r.text.strip() for b in walk(doc.blocks) if isinstance(b, Paragraph) for r in b.runs):
        doc.warnings.append('NO_EXTRACTABLE_TEXT')
    doc.warnings = sorted(set(doc.warnings))
    return doc


def walk(blocks):
    """Yield every block, descending into table cells."""
    for b in blocks:
        yield b
        if isinstance(b, Table):
            for c in b.cells:
                yield from walk(c.blocks)
