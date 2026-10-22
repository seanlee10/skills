import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'copy-html.sh'


def test_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111


@pytest.mark.parametrize('args', [[], ['missing.html'], ['a.html', 'b.html']])
def test_usage_error_leaves_clipboard_alone(args, tmp_path):
    # Runs before osascript is reached, so the clipboard is never touched.
    result = subprocess.run([str(SCRIPT), *args], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'usage:' in result.stderr
