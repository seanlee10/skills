import base64
import sys
import zipfile
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
REPO = SKILL.parent.parent
SAMPLES = REPO / 'bench' / 'hwp-parser' / 'samples'
sys.path.insert(0, str(SKILL / 'scripts'))

# 1x1 PNG used as the embedded image in synthetic HWPX packages.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
NS = ('xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"')


def write_hwpx(path, extra=None):
    """Synthetic HWPX: spine order s10 then s2; merged + nested table; one image."""
    sec10 = f'<hs:sec {NS}><hp:p id="10"><hp:run><hp:t>합성 문서<hp:tab/>첫 구역</hp:t></hp:run></hp:p></hs:sec>'
    sec2 = (f'<hs:sec {NS}><hp:p id="20"><hp:run><hp:t>표 앞</hp:t>'
            '<hp:tbl rowCnt="1" colCnt="2"><hp:tr><hp:tc><hp:subList>'
            '<hp:p id="21"><hp:run><hp:t>병합 셀</hp:t>'
            '<hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:subList>'
            '<hp:p id="22"><hp:run><hp:t>중첩</hp:t></hp:run></hp:p></hp:subList>'
            '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="1"/></hp:tc></hp:tr></hp:tbl>'
            '</hp:run></hp:p></hp:subList>'
            '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="2"/></hp:tc></hp:tr></hp:tbl>'
            '<hp:t>표 뒤</hp:t><hp:pic><hc:img binaryItemIDRef="img1"/></hp:pic></hp:run></hp:p></hs:sec>')
    package = ('<opf:package xmlns:opf="http://www.idpf.org/2007/opf"><opf:manifest>'
               '<opf:item id="s2" href="Contents/section2.xml"/>'
               '<opf:item id="s10" href="Contents/section10.xml"/>'
               '<opf:item id="img1" href="BinData/image1.png"/></opf:manifest>'
               '<opf:spine><opf:itemref idref="s10"/><opf:itemref idref="s2"/></opf:spine></opf:package>')
    contents = {'mimetype': b'application/hwp+zip', 'Contents/content.hpf': package,
                'Contents/section2.xml': sec2, 'Contents/section10.xml': sec10, 'BinData/image1.png': PNG}
    contents.update(extra or {})
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr(name, data)
    return Path(path)


@pytest.fixture
def make_hwpx():
    """Factory fixture: make_hwpx(path, extra=None) writes a synthetic HWPX and returns its path."""
    return write_hwpx
