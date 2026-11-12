"""The journeys' real file dialogs cannot write the owner's Windows dialog history (v0.7.2 Phase 3 acceptance closeout, Task A).

Windows records every path its file dialog opens under the owner's own ``HKCU\\...\\Explorer\\ComDlg32`` and Explorer's folder-view state;
the Phase 3 gate left 94 such values there. ``adapters/windows/containment.py`` starts the application under test at Low integrity, so
Windows refuses it write access to all of that, and the session refuses to drive a dialog otherwise.

Nothing here writes the owner's registry. The checks *open* keys for writing, which writes nothing (a granted handle is closed unused),
and read. No dialog is shown: the real dialog is proved in the gate's acceptance stage, under this same containment.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows integrity levels")

sys.path.insert(0, str(GATE_DIR))
from adapters.windows import containment  # noqa: E402

sys.path.remove(str(GATE_DIR))

SOURCE = GATE_DIR / "adapters" / "windows" / "containment.py"


def _low_python(tmp_path: Path, code: str, name: str = "child") -> tuple[int, str]:
    out = tmp_path / f"{name}.log"
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONSTARTUP")}
    process = containment.spawn_low([sys.executable, "-I", "-B", "-c", code], cwd=tmp_path, env=env, output=out, suspended=False)
    code_ = process.wait(60)
    return code_, out.read_text(encoding="utf-8", errors="replace")


def test_a_process_started_low_is_low_and_this_one_is_not(tmp_path):
    containment.label_low(tmp_path)
    probe = f"import sys; sys.path.insert(0, {str(SOURCE.parent)!r}); import containment as c; print(hex(c.integrity_of()))"
    status, output = _low_python(tmp_path, probe)
    assert status == 0, output
    assert output.strip().splitlines()[-1] == hex(containment.LOW_RID)
    assert containment.integrity_of() > containment.LOW_RID


def test_the_preflight_finds_every_dialog_history_key_refused(tmp_path):
    facts = containment.preflight(tmp_path / "pre")
    assert facts["verdict"] == "contained" and int(facts["integrity"], 16) == containment.LOW_RID
    assert set(facts["keys"]) == {key or "<root>" for key in containment.DIALOG_STATE_KEYS} | {"<classes root>"}
    assert all(status in (containment.ERROR_ACCESS_DENIED, containment.ERROR_FILE_NOT_FOUND) for status in facts["keys"].values()), facts
    assert facts["keys"][r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU"] == containment.ERROR_ACCESS_DENIED
    assert "LW" in facts["scratch_label"]


def test_the_same_probe_at_this_processs_level_is_granted_so_the_check_can_tell():
    """The no-change control: opened from a Medium process the same keys are writable, so "refused" above is a real measurement."""
    keys = containment._probe_here()["keys"]
    assert keys[r"Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU"] == 0
    assert keys["<root>"] == 0 and keys["<classes root>"] == 0


def test_the_preflight_refuses_when_the_child_is_not_low(tmp_path, monkeypatch):
    """A negative control: the same preflight with the child started at this process's own level must refuse."""

    def spawn_medium(argv, *, cwd, env, output, suspended=True):
        sink = open(output, "ab")
        try:
            return subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        finally:
            sink.close()

    with monkeypatch.context() as patch:
        patch.setattr(containment, "spawn_low", spawn_medium)
        with pytest.raises(containment.ContainmentUnavailable, match="not Low"):
            containment.preflight(tmp_path / "medium")


def test_require_low_refuses_a_process_above_low():
    with pytest.raises(containment.ContainmentUnavailable, match="not Low integrity"):
        containment.require_low([os.getpid()], "this test")
    with pytest.raises(containment.ContainmentUnavailable, match="no live process"):
        containment.require_low([], "nothing")


def test_a_low_process_writes_its_labelled_scratch_and_nothing_beside_it(tmp_path):
    scratch, beside = tmp_path / "scratch", tmp_path / "beside"
    (scratch / "in").mkdir(parents=True)
    beside.mkdir()
    earlier = scratch / "in" / "made-before-the-label.txt"
    earlier.write_text("before", encoding="utf-8")
    containment.label_low(scratch)
    later = scratch / "in" / "made-after-the-label.txt"
    later.write_text("after", encoding="utf-8")
    code = ("import json, sys\nfrom pathlib import Path\nresult = {}\n"
            f"for name, path in (('earlier', {str(earlier)!r}), ('later', {str(later)!r}), ('new', {str(scratch / 'new.txt')!r}),"
            f" ('beside', {str(beside / 'x.txt')!r})):\n"
            "    try:\n        open(path, 'a').write('low'); result[name] = 'written'\n"
            "    except OSError as exc:\n        result[name] = f'refused {type(exc).__name__}'\n"
            "print(json.dumps(result))\n")
    status, output = _low_python(scratch, code)
    assert status == 0, output
    result = json.loads(output.strip().splitlines()[-1])
    assert result == {"earlier": "written", "later": "written", "new": "written", "beside": "refused PermissionError"}, result


def test_the_session_refuses_a_file_dialog_before_any_input_unless_contained(tmp_path, monkeypatch):
    sys.path.insert(0, str(GATE_DIR))
    try:
        from adapters.windows import app_session, native_input as native
    finally:
        sys.path.remove(str(GATE_DIR))
    typed: list = []
    session = app_session.AppSession(tmp_path / "evidence", tmp_path / "work")
    with monkeypatch.context() as patch:
        patch.setattr(session, "wait_for_dialog", lambda **_: {"hwnd": 1, "title": "Select MP3 files"})
        patch.setattr(native, "type_text", lambda *a, **k: typed.append(a))
        patch.setattr(native, "key_tap", lambda *a, **k: typed.append(a))
        patch.setattr(native, "click_at", lambda *a, **k: typed.append(a))
        with pytest.raises(containment.ContainmentUnavailable, match="never established"):
            session.file_dialog(tmp_path / "a.mp3")
        session.containment, session.pid = {"scratch_label": "S:(ML;OICI;NW;;;LW)"}, os.getpid()  # this process: Medium
        with pytest.raises(containment.ContainmentUnavailable, match="not Low integrity"):
            session.file_dialog(tmp_path / "a.mp3")
        with pytest.raises(containment.ContainmentUnavailable, match="not Low integrity"):
            session.folder_dialog(tmp_path)
    assert typed == [], "input was sent to a dialog that was not contained"


def test_the_runner_refuses_every_scenario_when_containment_is_unavailable(tmp_path, monkeypatch):
    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner
        from helpers import media_fixtures, media_oracle

        class Tools:
            def record(self):
                return {"stub": True}

        def refuse(_work, **_):
            raise containment.ContainmentUnavailable("stub: a Low process may write these dialog-history keys")

        with monkeypatch.context() as patch:
            patch.setattr(media_oracle, "pinned_toolchain", lambda _root: Tools())
            patch.setattr(media_fixtures, "load_manifest", lambda _path: {})
            patch.setattr(containment, "preflight", refuse)
            report = tmp_path / "acceptance.json"
            code = acceptance_runner.main(["--report", str(report), "--token", "t", "--evidence", str(tmp_path / "ev"),
                                           "--scratch", str(tmp_path / "scratch"), "--only", "cover.center-crop"])
    finally:
        sys.path.remove(str(GATE_DIR))
    written = json.loads(report.read_text(encoding="utf-8"))
    assert code == 2 and written["blocked"].startswith("ContainmentUnavailable") and written["scenarios"] == [], written
    assert not (tmp_path / "ev" / "cover.center-crop").exists()


def test_history_added_sees_new_and_changed_entries_and_not_the_owner_pushing_old_ones_out():
    before = {"k\\1": "a", "k\\2": "b", "k\\3": "c"}
    assert containment.history_added(before, {"k\\1": "a"}) == {}
    assert containment.history_added(before, {"k\\1": "a", "k\\2": "B", "k\\4": "d"}) == {"k\\2": "B", "k\\4": "d"}


def test_the_oracle_sees_values_that_name_the_needle():
    """Read-only. The owner's history already holds Phase 3's entries, so the oracle has something real to find; whatever it finds is a
    dict of digests, never data. A needle no path contains finds nothing."""
    assert containment.history_references(needle="act-gate-needle-that-names-nothing-0f3a") == {}
    found = containment.history_references()
    assert all(len(digest) == 64 for digest in found.values())


def test_nothing_in_containment_can_write_the_registry():
    """Static: the module may open keys and read them. No call that sets, creates, deletes, saves, restores or loads a key or value."""
    forbidden = {"SetValue", "SetValueEx", "CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx", "DeleteValue", "SaveKey", "RestoreKey",
                 "LoadKey", "RegSetValueExW", "RegSetValueW", "RegCreateKeyExW", "RegCreateKeyW", "RegDeleteKeyW", "RegDeleteKeyExW",
                 "RegDeleteValueW", "RegDeleteTreeW", "RegSaveKeyW", "RegRestoreKeyW", "RegLoadKeyW", "RegLoadAppKeyW", "RegReplaceKeyW",
                 "RegOverridePredefKey", "RegSetKeySecurity", "RegCopyTreeW", "RegRenameKey"}
    names = {node.attr for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))) if isinstance(node, ast.Attribute)}
    assert not names & forbidden, sorted(names & forbidden)
    assert "KEY_READ" in names and "RegOpenKeyExW" in names
