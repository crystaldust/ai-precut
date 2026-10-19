"""pipeline/pyver：项目要求 Python ≥3.11；入口一开始就拒绝旧解释器（审查修复 1 / KI-82）。"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import pyver

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = {"aicut.py": ["list"], "gui/server.py": ["--help"], "app/main.py": []}


class FakeProc:
    def __init__(self, code, out):
        self.returncode, self.stdout, self.stderr = code, out, ""


def test_require_supported_rejects_old_python_with_chinese_message():
    with pytest.raises(SystemExit) as exc:
        pyver.require_supported_python((3, 9, 6), "/usr/bin/python3")
    msg = str(exc.value.code)
    assert "3.11" in msg and "3.9" in msg and "/usr/bin/python3" in msg and "uv run" in msg


def test_require_supported_accepts_current_python():
    pyver.require_supported_python((3, 11, 0), "x")
    pyver.require_supported_python()


def test_supports_safe_path_for_running_interpreter():
    assert pyver.supports_safe_path(sys.executable) is (sys.version_info >= (3, 11))


@pytest.mark.parametrize("proc_result,expected", [(FakeProc(0, "True\n"), True),
                                                  (FakeProc(0, "False\n"), False),
                                                  (FakeProc(1, ""), False)])
def test_supports_safe_path_probes_other_interpreters(proc_result, expected):
    seen = []

    def runner(cmd, **kw):
        seen.append(cmd)
        return proc_result
    assert pyver.supports_safe_path("/other/python", runner=runner) is expected
    assert seen[0][0] == "/other/python"


def test_supports_safe_path_false_when_interpreter_missing():
    def runner(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    assert pyver.supports_safe_path("/nope/python", runner=runner) is False


@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_entry_checks_python_before_importing_project_code(entry):
    src = (ROOT / entry).read_text(encoding="utf-8")
    check = src.index("require_supported_python()")
    first_project_import = re.search(r"^from (pipeline|gui) import", src, re.M).start()
    assert check < first_project_import, entry


def _old_python() -> str | None:
    for py in ("/usr/bin/python3",):
        if not Path(py).exists():
            continue
        r = subprocess.run([py, "-c", "import sys; print(sys.version_info < (3, 11))"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip() == "True":
            return py
    return None


@pytest.mark.skipif(_old_python() is None, reason="需要一个 <3.11 的 Python（如 macOS 自带 3.9）")
@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_entry_refuses_old_python(entry, tmp_path):
    r = subprocess.run([_old_python(), str(ROOT / entry), *ENTRIES[entry]],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Python 3.11" in r.stderr and "Traceback" not in r.stderr
