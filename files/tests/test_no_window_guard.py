"""Every child process the application starts on Windows has no console window, its own or a library's (v0.7.2 Phase 4).

``ACT.SHARED.HIDDEN-CONSOLE`` had no automated check: the inventory found it. ``install_no_window_guard`` replaces ``subprocess.Popen``
process-wide, so it is exercised in a child interpreter, never in this one. There a recorder stands where the real ``Popen`` stands, as a
library's own ``from subprocess import Popen`` binds to it, and records the arguments each start would be made with. It starts nothing:
a start without the guard would flash a console window on the owner's desktop.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

PROBE = r'''
import json, subprocess, sys
sys.path.insert(0, sys.argv[1])
seen = []

class Recorded(Exception):
    pass

class Recorder(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        startupinfo = kwargs.get("startupinfo")
        seen.append({"creationflags": kwargs.get("creationflags"),
                     "hidden_window": startupinfo is not None and bool(startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
                                      and startupinfo.wShowWindow == subprocess.SW_HIDE})
        self._child_created = False  # so Popen's own finaliser has nothing to clean up
        raise Recorded()

subprocess.Popen = Recorder
if sys.argv[2] == "guard":
    from shared import subprocess_utils
    subprocess_utils.install_no_window_guard()
    subprocess_utils.install_no_window_guard()
for extra in ({}, {"creationflags": 0x00000200}):
    try:
        subprocess.Popen([sys.executable, "-c", "pass"], **extra)
    except Recorded:
        pass
print(json.dumps({"seen": seen, "wrappers": [k.__name__ for k in subprocess.Popen.__mro__].count("_NoWindowPopen")}))
'''


def _probe(mode: str) -> dict:
    done = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, str(SCRIPTS), mode], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is a no-op off Windows by design")
def test_every_child_starts_hidden_and_a_callers_own_flags_survive():
    reading = _probe("guard")
    first, second = reading["seen"]
    assert first["creationflags"] & CREATE_NO_WINDOW and first["hidden_window"], first
    assert second["creationflags"] & CREATE_NO_WINDOW and second["creationflags"] & CREATE_NEW_PROCESS_GROUP, \
        "the caller's own flag is kept and the hidden-window flag added to it"
    assert reading["wrappers"] == 1, "installing twice wraps once"


def test_the_no_change_control_without_the_guard_nothing_hides_the_window():
    """The control the test above needs: the same starts without the guard carry no hidden-window flag, so the flag seen there is the guard's."""
    first, second = _probe("none")["seen"]
    assert not (first["creationflags"] or 0) & CREATE_NO_WINDOW and not first["hidden_window"]
    assert second["creationflags"] == CREATE_NEW_PROCESS_GROUP


def test_the_launcher_installs_the_guard_before_it_imports_or_starts_anything():
    """The guard must be in place before pydub or edge-tts bind Popen, so it is the first thing launcher.main does."""
    tree = ast.parse((SCRIPTS / "launcher.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    statements = [node for node in main.body if not isinstance(node, ast.Global)]
    first = statements[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call) and ast.unparse(first.value.func) == "sp.install_no_window_guard"
