"""Windows long paths and the app's folder -- v0.8.0 (owner requirement of 2026-11-13).

What is proved here, without ever raising Windows' elevation prompt or writing the registry (``conftest`` shuts that
door for every test; these tests inject the elevated runner and the registry reader):

* the setting is read with a read-only handle, and "on", "off", "absent" and "unreadable" are told apart;
* the app's real folder length is compared with the tested limits for both Windows configurations, at their exact
  boundaries, for the app and for the OmniVoice engine;
* a change is offered only where the setting is off AND switching it on would be enough; a folder too long even then is
  told to move, and is still refused by the depth rule afterwards;
* the elevated helper is Windows' own ``reg.exe`` from the system directory with one constant command line, and every
  refusal -- the person declining, the prompt cancelled, a standard account with no administrator, a managed computer,
  a failing or reverted registry write -- comes back as a sentence with nothing retried and nothing else changed;
* a registry value of 1 is not proof: setup goes on only after a fresh process shows that long paths work, says
  "restart Windows" when they do not yet, and starts again in a new process after a successful change;
* the README's path-length section says what the code enforces.

The first-run window is the real one (``run_with_gui``), run as a Toplevel of the suite's interpreter as
``test_first_run_setup_close.py`` does. The probe itself runs for real once, in the test's own folder.
"""

from __future__ import annotations

import inspect
import os
import queue
import subprocess
import sys
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import bootstrap  # noqa: E402
from shared import long_paths as lp  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402

from test_setup_log_follow import (  # noqa: E402,F401  (fixtures are collected by name)
    descendants,
    native_theme,
    pump_until,
    run_as_toplevel,
    settle,
    setup_log,
    tk_root,
)

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text(encoding="utf-8")
APP = lp.limits_from(bootstrap.DEEPEST_NATIVE_LIBRARY_CHARS, bootstrap.DEEPEST_FILE_CHARS)
OMNI = lp.OMNIVOICE_LIMITS
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows long paths exist on Windows only")


def folder(length: int) -> str:
    return "C:\\" + "a" * (length - 3)


# --------------------------------------------------------------------------- the limits themselves
def test_the_tested_limits_are_the_ones_the_installer_enforces_and_one_set_of_numbers():
    """87/123 for the app and 83/119 with OmniVoice: derived from the depth rules, never typed a second time."""
    assert (APP.default, APP.long_paths) == (87, 123)
    assert (OMNI.default, OMNI.long_paths) == (83, 119)
    assert bootstrap.app_path_limits() == APP
    assert lp.WINDOWS_MAX_PATH == bootstrap.WINDOWS_MAX_PATH == ov.WINDOWS_MAX_PATH == 259
    # this module may not import tts, so the OmniVoice depths are held equal here
    assert lp.OMNIVOICE_DEEPEST_NATIVE_LIBRARY_CHARS == ov.DEEPEST_NATIVE_LIBRARY_CHARS
    assert lp.OMNIVOICE_DEEPEST_FILE_CHARS == ov.DEEPEST_FILE_CHARS
    # measured 2026-11-13 on HOME-PC and on a cold install: the deepest native library the app-wide rule must cover
    # is Qwen3's (132 below the app's folder), OmniVoice's own is 136, and the deepest files are 165 and 169
    assert bootstrap.DEEPEST_NATIVE_LIBRARY_CHARS >= 132 and bootstrap.DEEPEST_FILE_CHARS >= 165
    assert ov.DEEPEST_NATIVE_LIBRARY_CHARS >= 136 and ov.DEEPEST_FILE_CHARS >= 169


@pytest.mark.parametrize("length, enabled, app_fits, omnivoice_fits, app_offer, omnivoice_offer", [
    (83, False, True, True, False, False),     # everything fits as Windows comes
    (84, False, True, False, False, True),     # only OmniVoice is too deep; long paths would be enough for it
    (87, False, True, False, False, True),
    (88, False, False, False, True, False),    # the app itself is too deep; long paths would be enough
    (119, False, False, False, True, False),
    (120, False, False, False, True, False),   # ...for the app, though not for OmniVoice
    (123, False, False, False, True, False),
    (124, False, False, False, False, False),  # too long even with long paths: nothing to offer
    (200, False, False, False, False, False),
    (88, True, True, True, False, False),      # long paths on: nothing is offered, the limits are the long ones
    (119, True, True, True, False, False),
    (120, True, True, False, False, False),
    (123, True, True, False, False, False),
    (124, True, False, False, False, False),
    (88, None, False, False, False, False),    # a setting that cannot be read counts as off and is never changed
])
def test_the_folder_is_compared_with_both_configurations_at_their_exact_boundaries(
        length, enabled, app_fits, omnivoice_fits, app_offer, omnivoice_offer):
    found = lp.assess(folder(length), APP, enabled=enabled)
    assert found.length == length and found.folder == folder(length)
    assert (found.app_fits, found.omnivoice_fits) == (app_fits, omnivoice_fits)
    assert (found.app_offer, found.omnivoice_offer) == (app_offer, omnivoice_offer)
    assert found.needs_long_paths is (length > APP.default)
    # the offer never contradicts the depth rules: it exists only where the rule refuses now and accepts with long paths
    if app_offer:
        assert bootstrap.install_path_problem(folder(length), long_paths=False)
        assert bootstrap.install_path_problem(folder(length), long_paths=True) == ""
    if omnivoice_offer:
        assert ov.install_depth_problem(folder(length), long_paths=False)
        assert ov.install_depth_problem(folder(length), long_paths=True) == ""


def test_a_folder_too_long_even_with_long_paths_is_told_to_move_and_never_offered_the_change(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    too_long = folder(APP.long_paths + 1)
    message = bootstrap.install_path_problem(too_long, long_paths=False)
    assert "would not be enough" in message and lp.SHORT_FOLDER_EXAMPLE in message
    assert "Or switch on Windows long paths" not in message
    assert not lp.assess(too_long, APP, enabled=False).app_offer
    # ...and it is still refused once long paths ARE on: enabling them is never a way round the rule
    assert bootstrap.install_path_problem(too_long, long_paths=True)
    within = bootstrap.install_path_problem(folder(APP.long_paths), long_paths=False)
    assert "Or switch on Windows long paths" in within and lp.README_SECTION in within
    assert "would not be enough" not in within
    assert "long paths" not in bootstrap.install_path_problem(too_long, long_paths=True).lower().replace(
        "too long for windows", "")


def test_the_omnivoice_refusal_names_the_manual_way_only_where_it_would_help():
    helped = ov.install_depth_problem(folder(OMNI.default + 1), long_paths=False)
    assert "Or switch on Windows long paths" in helped and lp.README_SECTION in helped and str(OMNI.long_paths) in helped
    assert "Or switch on" not in ov.install_depth_problem(folder(OMNI.long_paths + 1), long_paths=False)
    assert "Or switch on" not in ov.install_depth_problem(folder(OMNI.long_paths + 1), long_paths=True)


# --------------------------------------------------------------------------- reading the setting
class FakeRegistry:
    """Stands in for ``winreg``. It has no function that writes, so a write attempt is an AttributeError."""

    HKEY_LOCAL_MACHINE, KEY_READ, REG_DWORD, REG_SZ = "HKLM", 0x20019, 4, 1

    def __init__(self, value=None, kind=4, *, key_error=None):
        self.value, self.kind, self.key_error, self.opened = value, kind, key_error, []

    def OpenKey(self, hive, path, reserved=0, access=None):  # noqa: N802 - winreg's own name
        self.opened.append((hive, path, access))
        if self.key_error:
            raise self.key_error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def QueryValueEx(self, key, name):  # noqa: N802
        assert name == "LongPathsEnabled"
        if self.value is None:
            raise FileNotFoundError(2, "value not found")
        return self.value, self.kind


@pytest.mark.parametrize("registry, expected", [
    (FakeRegistry(1), True),
    (FakeRegistry(0), False),
    (FakeRegistry(None), False),                       # the value is not there: Windows' default, off
    (FakeRegistry(2), False),                          # only 1 means on
    (FakeRegistry("1", kind=1), False),                # only a DWORD counts
    (FakeRegistry(key_error=PermissionError(5, "denied")), None),   # unreadable: not "off", and never changed
])
def test_the_setting_is_read_with_a_read_only_handle_and_on_off_absent_unreadable_are_told_apart(
        monkeypatch, registry, expected):
    monkeypatch.setattr(lp.sys, "platform", "win32")
    monkeypatch.setattr(lp, "_winreg", lambda: registry)
    assert lp.read_setting() is expected
    assert registry.opened == [("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem", FakeRegistry.KEY_READ)]


def test_off_windows_there_is_no_setting_and_nothing_to_enable(monkeypatch):
    monkeypatch.setattr(lp.sys, "platform", "linux")
    assert lp.read_setting() is None
    assert lp.enable(run_elevated=lambda *a, **k: pytest.fail("ran")).state == lp.UNSUPPORTED


@windows_only
def test_this_computer_s_setting_can_be_read_and_reading_it_changes_nothing():
    before = lp.read_setting()
    assert before in (True, False)
    assert lp.read_setting() is before


# --------------------------------------------------------------------------- the elevated helper
def test_the_elevated_command_is_one_constant_and_nothing_can_be_passed_into_it():
    assert lp.ELEVATED_ARGUMENTS == ("add", r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem", "/v",
                                     "LongPathsEnabled", "/t", "REG_DWORD", "/d", "1", "/f")
    assert lp.elevated_parameters() == (r"add HKLM\SYSTEM\CurrentControlSet\Control\FileSystem /v LongPathsEnabled "
                                        "/t REG_DWORD /d 1 /f")
    assert list(inspect.signature(lp.elevated_parameters).parameters) == []
    # the public entry takes a window handle and test seams only: no command, no path, no value
    assert set(inspect.signature(lp.enable).parameters) == {"window", "read", "run_elevated", "reg_exe"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in inspect.signature(lp.enable).parameters.values())


@windows_only
def test_reg_exe_comes_from_the_system_directory_windows_reports_never_from_path_or_the_environment(
        monkeypatch, tmp_path):
    (tmp_path / "reg.exe").write_bytes(b"not the real one")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setenv("windir", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    found = lp.system_reg_exe()
    assert found is not None and found.name.lower() == "reg.exe" and found.is_file()
    assert tmp_path not in found.parents and found.parent.name.lower() == "system32"


class Elevation:
    """A stand-in for Windows' consent prompt and the elevated ``reg.exe``: records every start it is asked for."""

    def __init__(self, outcome, *, sets=None, registry=None):
        self.outcome, self.sets, self.registry, self.calls = outcome, sets, registry, []

    def __call__(self, executable, parameters, *, window=0):
        self.calls.append((executable, parameters, window))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.sets is not None:
            self.registry["value"] = self.sets
        return self.outcome


def change(outcome, *, before=False, sets=None, reg=Path(r"C:\Windows\System32\reg.exe")):
    registry = {"value": before}
    elevation = Elevation(outcome, sets=sets, registry=registry)
    result = lp.enable(window=77, read=lambda: registry["value"], run_elevated=elevation, reg_exe=lambda: reg)
    return result, elevation, registry


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(lp.sys, "platform", "win32")


def test_a_setting_that_is_already_on_is_reported_and_nothing_is_run(on_windows):
    result, elevation, registry = change(("ran", 0), before=True)
    assert result.state == lp.ALREADY_ENABLED and elevation.calls == [] and registry == {"value": True}


def test_an_approved_change_runs_exactly_the_constant_command_once_and_is_read_back(on_windows):
    result, elevation, registry = change(("ran", 0), sets=True)
    assert result.state == lp.ENABLED and registry == {"value": True}
    assert elevation.calls == [(r"C:\Windows\System32\reg.exe", lp.elevated_parameters(), 77)]


@pytest.mark.parametrize("outcome, state, words", [
    (("cancelled", 1223), lp.CANCELLED, "declined or closed"),          # the person said No, or closed the prompt
    (("refused", 5), lp.DENIED, "administrator"),                       # a standard account with no administrator
    (("refused", 1260), lp.DENIED, "organisation"),                     # elevation blocked by an organisation's policy
    (("refused", 740), lp.DENIED, "administrator"),
    (("ran", 1), lp.FAILED, "reported an error"),                       # the registry refused the write
    (("ran", 0), lp.NOT_CHANGED, "put it back"),                        # written, and reverted (a managed computer)
    (("timeout", 0), lp.FAILED, "did not finish"),
    (OSError(87, "the parameter is incorrect"), lp.FAILED, "could not start"),
])
def test_every_refusal_is_a_sentence_with_nothing_retried_and_the_setting_left_as_it_was(
        on_windows, outcome, state, words):
    result, elevation, registry = change(outcome)
    assert result.state == state and words in result.message
    assert registry == {"value": False}, "nothing was changed"
    assert len(elevation.calls) == 1, "asked once: never retried, never another route"
    assert elevation.calls[0][:2] == (r"C:\Windows\System32\reg.exe", lp.elevated_parameters())
    assert "changed" in result.message or "touched" in result.message or "still off" in result.message


def test_a_setting_that_cannot_be_read_or_a_missing_reg_exe_is_never_changed(on_windows):
    result, elevation, _registry = change(("ran", 0), before=None)
    assert result.state == lp.FAILED and "could not be read" in result.message and elevation.calls == []
    result, elevation, registry = change(("ran", 0), reg=None)
    assert result.state == lp.FAILED and "reg.exe" in result.message and elevation.calls == []
    assert registry == {"value": False}


def test_a_registry_tool_that_fails_but_whose_value_reads_on_is_judged_by_the_value(on_windows):
    result, _elevation, registry = change(("ran", 1), sets=True)
    assert result.state == lp.ENABLED and registry == {"value": True}


def test_the_real_elevated_runner_is_shut_for_the_whole_suite(on_windows):
    """The guard in conftest: reaching the real ShellExecuteExW from a test fails loudly instead of prompting."""
    with pytest.raises(AssertionError, match="real Windows elevation prompt"):
        lp.enable(read=lambda: False, reg_exe=lambda: Path(r"C:\Windows\System32\reg.exe"))


# --------------------------------------------------------------------------- proving it in a fresh process
WORKS = {"process_long_paths": True, "file": {"ok": True}, "pip": {"ok": True}, "native": {"ok": True}}


def proof(tmp_path, facts, *, setting=True, deepest_file=176, deepest_native=136, root=None):
    seen = []

    def spawn(python, base, file_chars, native_chars, timeout_s):
        seen.append((python, base, file_chars, native_chars))
        Path(base).mkdir(parents=True)            # what a real probe leaves when it is interrupted
        (Path(base) / "left-behind.txt").write_text("x", encoding="utf-8")
        return facts

    root = root or tmp_path
    result = lp.verify_runtime(root, deepest_file=deepest_file, deepest_native=deepest_native, python="base-python",
                               spawn=spawn, read=lambda: setting)
    return result, seen


def test_the_proof_asks_a_new_process_at_the_installation_s_real_depth_and_removes_what_it_made(tmp_path):
    result, seen = proof(tmp_path, dict(WORKS))
    assert result.ok and not result.restart_needed
    (python, base, file_chars, native_chars), = seen
    assert python == "base-python"
    assert Path(base).parent == tmp_path / "files" / "runtime-data" and Path(base).name.startswith(lp.PROBE_PREFIX)
    assert (file_chars, native_chars) == (len(str(tmp_path)) + 176, len(str(tmp_path)) + 136)
    assert list((tmp_path / "files" / "runtime-data").iterdir()) == [], "its own folder is removed again"


def test_the_proof_removes_only_the_one_folder_it_made(tmp_path):
    """An earlier check's leftover, and everything else in runtime-data, is none of its business."""
    data = tmp_path / "files" / "runtime-data"
    earlier = data / (lp.PROBE_PREFIX + "earlier0")
    earlier.mkdir(parents=True)
    (earlier / "somebody-elses.txt").write_text("keep", encoding="utf-8")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    result, _seen = proof(tmp_path, dict(WORKS))
    assert result.ok and (earlier / "somebody-elses.txt").read_text(encoding="utf-8") == "keep"
    assert sorted(entry.name for entry in data.iterdir()) == [lp.PROBE_PREFIX + "earlier0", "settings.json"]


def test_a_probe_that_made_nothing_leaves_nothing_to_remove_and_nothing_is_attempted(tmp_path, monkeypatch):
    """With no folder made (the suite's stand-in probe, or a probe that never started), no deletion is even tried."""
    monkeypatch.setattr(lp, "_remove_tree", lambda path: pytest.fail(f"tried to remove {path}"))
    result = lp.verify_runtime(tmp_path, deepest_file=176, deepest_native=136, python="p",
                               spawn=lambda *a: dict(WORKS), read=lambda: True)
    assert result.ok and not (tmp_path / "files").exists()


def test_a_value_of_1_that_new_processes_do_not_have_yet_means_restart_windows(tmp_path):
    facts = dict(WORKS, process_long_paths=False, file={"ok": False, "error": "FileNotFoundError"})
    result, _seen = proof(tmp_path, facts, setting=True, root=folder(100))
    assert not result.ok and result.restart_needed
    assert result.message == lp.RESTART_MESSAGE and "Restart Windows" in result.message
    assert "Nothing was installed" in result.message


def test_a_setting_that_reads_off_again_is_not_a_restart_question(tmp_path):
    """A managed computer put it back: the new process has no long paths and the value reads off."""
    facts = dict(WORKS, process_long_paths=False, file={"ok": False})
    result, _seen = proof(tmp_path, facts, setting=False, root=folder(100))
    assert not result.ok and not result.restart_needed
    assert "not switched on" in result.message and lp.SHORT_FOLDER_EXAMPLE in result.message


@pytest.mark.parametrize("broken, words", [
    ("file", "a file could not be written"),
    ("pip", "a package could not be installed"),
    ("native", "a program library could not be loaded"),
])
def test_long_paths_that_are_on_but_do_not_work_for_files_packages_or_libraries_stop_setup(tmp_path, broken, words):
    facts = dict(WORKS)
    facts[broken] = {"ok": False, "error": "WinError 206"}
    result, _seen = proof(tmp_path, facts, root=folder(100))
    assert not result.ok and words in result.message and "WinError 206" in result.message
    assert "Nothing was installed" in result.message


def test_a_probe_that_cannot_run_or_answer_is_a_refusal_not_a_pass(tmp_path):
    result, _seen = proof(tmp_path, {"error": "the check gave no answer (exit 1)"}, root=folder(100))
    assert not result.ok and "could not check" in result.message


def test_where_the_depth_stays_within_windows_ordinary_limit_long_paths_are_not_demanded(tmp_path):
    facts = dict(WORKS, process_long_paths=False)
    result, _seen = proof(tmp_path, facts, setting=False, root=folder(60), deepest_file=172)
    assert result.ok, "60 + 172 is within 259: nothing here needs long paths"


@windows_only
def test_the_real_probe_writes_installs_and_loads_at_the_asked_depth_in_its_own_folder(tmp_path):
    """The probe's own code, for real, in the test's folder: a file, a pip-installed package and a native library at an
    exact path length. Past Windows' ordinary limit the file and the package need long paths in THIS process and must
    say so truthfully either way; a native library is only asked for within the limit, where it must load."""
    base = str(tmp_path / "p")
    within = min(lp.WINDOWS_MAX_PATH, len(base) + 110)
    facts = lp._probe(base, within, within)
    assert facts["file"] == {"ok": True, "chars": within}
    assert facts["pip"] == {"ok": True, "chars": within}, facts["pip"]
    assert facts["native"]["ok"] is True and facts["native"]["chars"] == within, facts["native"]
    assert not os.path.exists(base), "the probe removes its own folder"

    beyond = lp.WINDOWS_MAX_PATH + 30
    facts = lp._probe(base, beyond, within)
    assert facts["file"]["chars"] == beyond
    assert facts["file"]["ok"] is facts["process_long_paths"], "true to what this process can really do"
    assert facts["pip"]["ok"] is facts["process_long_paths"], facts["pip"]
    assert not os.path.exists(base)


@windows_only
def test_the_probe_runs_as_a_program_in_a_new_process_and_prints_its_facts(tmp_path):
    base = str(tmp_path / "q")
    within = min(lp.WINDOWS_MAX_PATH, len(base) + 110)
    done = subprocess.run([sys.executable, "-I", "-B", lp.__file__, "--probe", base, str(within), str(within)],
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr
    import json
    facts = json.loads(done.stdout.splitlines()[-1])
    assert facts["file"]["ok"] and facts["pip"]["ok"] and facts["native"]["ok"], facts
    assert set(facts) >= {"python", "process_long_paths", "file", "pip", "native"}


@pytest.mark.parametrize("total", [5, 40, 41, 42, 100, 141, 142, 143, 260, 300, 505])
def test_a_probe_path_is_exactly_as_long_as_asked(total):
    base = "C:\\some\\base"
    made = lp.path_of_length(base, total, "leaf.pyd")
    shortest = len(base) + 1 + len("leaf.pyd")
    assert len(made) == max(total, shortest) and made.startswith(base + "\\") and made.endswith("leaf.pyd")
    assert all(0 < len(part) <= 100 for part in made[len(base) + 1:].split("\\")[:-1])


# --------------------------------------------------------------------------- setup and repair: the preflight
class Lines:
    def __init__(self):
        self.lines = []

    def line(self, text):
        self.lines.append(text)


def test_a_folder_that_does_not_need_long_paths_is_never_probed(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(lp, "_spawn_probe", lambda *a: pytest.fail("probed a folder that needs no long paths"))
    assert bootstrap.long_path_runtime_problem(Lines(), folder(APP.default)) == ""
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    assert bootstrap.long_path_runtime_problem(Lines(), folder(120)) == ""


def test_a_folder_that_needs_long_paths_is_proved_at_the_installation_s_depth_before_setup_goes_on(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    asked = []

    def spawn(python, base, file_chars, native_chars, timeout_s):
        asked.append((python, file_chars, native_chars))
        return dict(WORKS)

    monkeypatch.setattr(lp, "_spawn_probe", spawn)
    log = Lines()
    deep = folder(APP.default + 1)
    assert bootstrap.long_path_runtime_problem(log, deep) == ""
    assert asked == [(sys.executable, len(deep) + max(bootstrap.DEEPEST_FILE_CHARS, ov.DEEPEST_FILE_CHARS),
                      len(deep) + bootstrap.DEEPEST_NATIVE_LIBRARY_CHARS)]
    assert any("checked in a new process and working" in line for line in log.lines)


def test_setup_and_repair_stop_before_touching_anything_when_long_paths_do_not_really_work(monkeypatch):
    """The registry says "on", the depth rule therefore passes, and a new process cannot use long paths: both setup
    and repair refuse with the restart sentence, before the engine lease, before any environment is touched."""
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "REPO_ROOT", Path(folder(100)))
    monkeypatch.setattr(bootstrap, "windows_long_paths_enabled", lambda: True)
    monkeypatch.setattr(lp, "read_setting", lambda: True)
    monkeypatch.setattr(lp, "_spawn_probe", lambda *a: dict(WORKS, process_long_paths=False, file={"ok": False}))
    monkeypatch.setattr(lp, "_remove_tree", lambda path: None)
    monkeypatch.setattr(bootstrap, "_take_engine_lease", lambda *a, **k: pytest.fail("setup went ahead"))
    log = Lines()
    assert bootstrap.install_path_problem() == "", "the depth rule itself accepts this folder with long paths on"
    assert bootstrap.run_setup(lambda *a: None, log) == (False, lp.RESTART_MESSAGE)
    assert bootstrap.repair_venv(log, headless=True) == (False, lp.RESTART_MESSAGE)
    assert any("NOT working" in line for line in log.lines)


def test_the_depth_rule_is_asked_first_and_its_refusal_is_never_softened_by_the_probe(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    monkeypatch.setattr(bootstrap, "REPO_ROOT", Path(folder(APP.long_paths + 1)))
    monkeypatch.setattr(bootstrap, "windows_long_paths_enabled", lambda: True)
    monkeypatch.setattr(lp, "_spawn_probe", lambda *a: pytest.fail("the probe was asked about a refused folder"))
    monkeypatch.setattr(bootstrap, "_take_engine_lease", lambda *a, **k: pytest.fail("setup went ahead"))
    ok, message = bootstrap.run_setup(lambda *a: None, Lines())
    assert ok is False and "too long for Windows" in message


# --------------------------------------------------------------------------- the first-run window
def labels(window) -> str:
    return "\n".join(str(w.cget("text")) for w in descendants(window) if isinstance(w, ttk.Label) and w.winfo_ismapped())


def button(window, text):
    return next((w for w in descendants(window) if isinstance(w, ttk.Button) and str(w.cget("text")) == text
                 and w.winfo_ismapped()), None)


def checkbox(window, starts):
    return next(w for w in descendants(window) if isinstance(w, ttk.Checkbutton) and str(w.cget("text")).startswith(starts))


@pytest.fixture
def window_at(monkeypatch, tk_root, setup_log, native_theme):
    """Run the real first-run window for an app folder of a given length and long-path setting; *script* drives it."""
    def run(length, enabled, script, *, change=None, proof_result=None):
        real_assess = lp.assess
        seen = {"setup": [], "relaunch": 0, "changes": 0, "proofs": 0, "exit": None}
        monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
        monkeypatch.setattr(lp, "assess", lambda root, app, **k: real_assess(folder(length), app, enabled=enabled))

        def fake_enable(*, window=0):
            seen["changes"] += 1
            return change

        def fake_proof(root=None):
            seen["proofs"] += 1
            return proof_result

        def fake_setup(progress, log):
            seen["setup"].append(True)
            return False, "stopped by the test"

        monkeypatch.setattr(lp, "enable", fake_enable)
        monkeypatch.setattr(bootstrap, "prove_long_paths", fake_proof)
        monkeypatch.setattr(bootstrap, "run_setup", fake_setup)
        monkeypatch.setattr(bootstrap, "relaunch_setup", lambda: seen.__setitem__("relaunch", seen["relaunch"] + 1) or 0)
        monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
        from tkinter import messagebox
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
        run_as_toplevel(monkeypatch, tk_root, script)
        seen["exit"] = bootstrap.run_with_gui()
        return seen

    return run


def test_a_folder_too_deep_for_default_windows_is_shown_the_two_ways_forward_before_anything_else(window_at):
    shown = {}

    def script(window):
        settle(window)
        shown["text"] = labels(window)
        shown["begin"] = button(window, "Begin Setup")
        shown["buttons"] = [button(window, "Close - I will move the app"), button(window, "Switch on Windows long paths...")]
        shown["skip"] = button(window, "Continue without OmniVoice")
        shown["buttons"][0].invoke()        # A: I will move the app

    seen = window_at(100, False, script)
    text = shown["text"]
    assert "too long for Windows as it is set up" in text and "100 characters" in text and folder(100) in text
    assert f"{APP.default} characters or fewer" in text and f"limit of {APP.long_paths}" in text
    assert "A. Move the app to a shorter folder (recommended)" in text and lp.SHORT_FOLDER_EXAMPLE in text
    assert "B. Switch on Windows long paths" in text and "for the whole computer" in text
    assert "administrator's approval" in text and "restart" in text
    assert "No packages or voices have been downloaded" in text
    assert shown["begin"] is None, "the welcome page is not shown: nothing can be started from here"
    assert all(shown["buttons"]) and shown["skip"] is None
    assert text.index("A. Move") < text.index("B. Switch on")
    assert seen["changes"] == 0 and seen["setup"] == [] and seen["relaunch"] == 0, "choosing A changes nothing"
    assert seen["exit"] == bootstrap.setup_exit_code(started=False, done=False, ok=False)


def test_between_the_two_limits_the_page_says_omnivoice_still_cannot_be_installed_here(window_at):
    shown = {}

    def script(window):
        settle(window)
        shown["text"] = labels(window)
        button(window, "Close - I will move the app").invoke()

    window_at(OMNI.long_paths + 1, False, script)
    assert "Even with long paths on, the OmniVoice voices cannot be installed in this folder" in shown["text"]
    assert f"{OMNI.long_paths} characters or fewer" in shown["text"]


@pytest.mark.parametrize("length, enabled", [
    (APP.long_paths + 1, False),     # too long even with long paths: no ineffective offer; setup's own rule refuses it
    (APP.default, False),            # fits as Windows comes
    (100, True),                     # long paths already on
    (100, None),                     # the setting cannot be read: never offered a change
])
def test_where_a_change_could_not_help_or_is_not_needed_the_welcome_page_is_shown_and_nothing_is_offered(
        window_at, length, enabled):
    shown = {}

    def script(window):
        settle(window)
        shown["offer"] = button(window, "Switch on Windows long paths...")
        shown["begin"] = button(window, "Begin Setup")
        window.destroy()

    seen = window_at(length, enabled, script)
    assert shown["offer"] is None and shown["begin"] is not None
    assert seen["changes"] == 0 and seen["relaunch"] == 0


@pytest.mark.parametrize("state, message", [
    (lp.CANCELLED, "The Windows permission prompt was declined or closed, so nothing was changed."),
    (lp.DENIED, "Windows did not allow the change (error 5): it needs an administrator's approval."),
    (lp.NOT_CHANGED, "The change was made, but Windows still shows the setting as off"),
    (lp.FAILED, "Windows' registry tool reported an error (1) and the setting is still off."),
])
def test_a_declined_denied_or_failed_change_leaves_setup_where_it_was_and_both_ways_open(window_at, state, message):
    shown = {}

    def script(window):
        settle(window)
        button(window, "Switch on Windows long paths...").invoke()
        pump_until(window, lambda: message in labels(window), "the result is shown")
        shown["text"] = labels(window)
        shown["again"] = button(window, "Switch on Windows long paths...")
        shown["move"] = button(window, "Close - I will move the app")
        shown["states"] = (str(shown["again"].cget("state")), str(shown["move"].cget("state")))
        shown["begin"] = button(window, "Begin Setup")
        shown["move"].invoke()

    seen = window_at(100, False, script, change=lp.EnableResult(state, message, 5))
    assert "You can still move the app to a shorter folder (A)." in shown["text"]
    assert shown["states"] == ("normal", "normal") and shown["begin"] is None
    assert seen["changes"] == 1 and seen["proofs"] == 0, "nothing to prove: nothing changed"
    assert seen["setup"] == [] and seen["relaunch"] == 0, "setup did not go on"
    assert seen["exit"] == bootstrap.setup_exit_code(started=False, done=False, ok=False)


def test_a_change_that_reads_back_and_works_in_a_new_process_restarts_setup_in_a_new_process(window_at):
    def script(window):
        settle(window)
        button(window, "Switch on Windows long paths...").invoke()
        pump_until(window, lambda: not window.winfo_exists() or "Setup starts again" in labels(window), "the result")

    seen = window_at(100, False, script, change=lp.EnableResult(lp.ENABLED, "Windows long paths are now switched on."),
                     proof_result=lp.ProbeResult(True, False, "Long paths work in this folder."))
    assert (seen["changes"], seen["proofs"], seen["relaunch"]) == (1, 1, 1)
    assert seen["setup"] == [], "this process, which cannot see the new setting, installs nothing itself"
    assert seen["exit"] == 0, "the new process's exit code is this one's"


def test_a_change_that_reads_back_but_does_not_work_yet_asks_for_a_restart_and_goes_no_further(window_at):
    shown = {}

    def script(window):
        settle(window)
        button(window, "Switch on Windows long paths...").invoke()
        pump_until(window, lambda: "Restart Windows" in labels(window), "the restart sentence")
        shown["text"] = labels(window)
        shown["again"] = next(w for w in descendants(window) if isinstance(w, ttk.Button)
                              and str(w.cget("text")) == "Switch on Windows long paths...")
        shown["state"] = str(shown["again"].cget("state"))
        shown["begin"] = button(window, "Begin Setup")
        button(window, "Close").invoke()

    seen = window_at(100, False, script, change=lp.EnableResult(lp.ENABLED, "Windows long paths are now switched on."),
                     proof_result=lp.ProbeResult(False, True, lp.RESTART_MESSAGE))
    assert lp.RESTART_MESSAGE in shown["text"]
    assert shown["state"] == "disabled", "the setting is on: offering it again would mean nothing"
    assert shown["begin"] is None
    assert seen["relaunch"] == 0 and seen["setup"] == [], "setup does not continue until long paths really work"
    assert seen["exit"] == bootstrap.setup_exit_code(started=False, done=False, ok=False)


def test_where_only_omnivoice_is_too_deep_the_question_comes_when_omnivoice_is_chosen_and_setup_can_go_on_without_it(
        window_at):
    shown = {}

    def script(window):
        settle(window)
        shown["first"] = button(window, "Switch on Windows long paths...")
        box = checkbox(window, "OmniVoice")
        box.invoke()
        assert "selected" in box.state()
        button(window, "Begin Setup").invoke()
        settle(window)
        shown["text"] = labels(window)
        shown["skip"] = button(window, "Continue without OmniVoice")
        shown["skip"].invoke()
        pump_until(window, lambda: bool(shown.get("done")) or not window.winfo_exists()
                   or button(window, "Close") is not None, "setup started and reported")
        shown["still_chosen"] = "selected" in box.state()

    seen = window_at(OMNI.default + 1, False, script)
    assert shown["first"] is None, "the app fits: nothing is asked until OmniVoice is chosen"
    assert "OmniVoice needs a shorter folder, or Windows long paths" in shown["text"]
    assert f"the OmniVoice voices need a folder path of {OMNI.default} characters or fewer" in shown["text"]
    assert shown["skip"] is not None and shown["still_chosen"] is False
    assert seen["setup"] == [True], "setup went on, without OmniVoice"
    assert seen["changes"] == 0 and seen["relaunch"] == 0


def test_without_omnivoice_chosen_that_folder_is_set_up_with_no_question_at_all(window_at):
    def script(window):
        settle(window)
        button(window, "Begin Setup").invoke()
        pump_until(window, lambda: button(window, "Close") is not None, "setup started and reported")
        assert button(window, "Switch on Windows long paths...") is None

    seen = window_at(OMNI.default + 1, False, script)
    assert seen["setup"] == [True] and seen["changes"] == 0


def test_the_worker_of_the_page_reports_through_a_queue_and_proves_only_a_change_that_reads_back():
    results: "queue.Queue" = queue.Queue()
    proofs = []
    good = lp.ProbeResult(True, False, "ok")
    lp._change_and_prove(lambda window: lp.EnableResult(lp.CANCELLED, "no"), lambda: proofs.append(1) or good, 5, results)
    assert results.get_nowait() == (lp.EnableResult(lp.CANCELLED, "no"), None) and proofs == []
    lp._change_and_prove(lambda window: lp.EnableResult(lp.ENABLED, "yes"), lambda: proofs.append(1) or good, 5, results)
    assert results.get_nowait() == (lp.EnableResult(lp.ENABLED, "yes"), good) and proofs == [1]

    def explode(window):
        raise RuntimeError("boom")

    lp._change_and_prove(explode, None, 5, results)
    result, found = results.get_nowait()
    assert result.state == lp.FAILED and "boom" in result.message and found is None


def test_setup_started_again_runs_this_same_program_with_the_same_arguments_and_returns_its_exit_code(monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap.subprocess, "call", lambda command, **k: calls.append((command, k)) or 7)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--skip-kokoro-download"])
    assert bootstrap.relaunch_setup() == 7
    (command, options), = calls
    assert command == [sys.executable, str(Path(bootstrap.__file__).resolve()), "--skip-kokoro-download"]
    assert options == {"cwd": str(bootstrap.REPO_ROOT)}


# --------------------------------------------------------------------------- the README says what the code does
def section() -> str:
    start = README.index("### " + lp.README_SECTION)
    return README[start:README.index("First run opens a setup window", start)]


def test_the_readme_has_the_path_length_section_under_download_install_before_the_first_run_instructions():
    assert README.count(lp.README_SECTION) == 1
    assert README.index("## Download / Install") < README.index("### " + lp.README_SECTION) \
        < README.index("First run opens a setup window") < README.index("## In development: v0.8.0")


def test_the_readme_states_the_limits_the_installer_enforces_for_both_windows_configurations():
    text = section()
    assert f"| Default Windows (long paths off) | {APP.default} characters or fewer | {OMNI.default} characters or fewer |" \
        in text
    assert f"| \"Enable Win32 long paths\" switched on | {APP.long_paths} characters or fewer | " \
           f"{OMNI.long_paths} characters or fewer |" in text
    assert "this app's own tested limits" in text and "not general Windows limits" in text
    assert "checks the folder before it downloads the app's packages or any voice" in text
    assert "Only the app's own Python, about 46 MB, may already have been fetched" in text


def test_the_readme_recommends_a_short_folder_first_and_explains_the_optional_setting_plainly():
    text = section()
    assert text.index("`C:\\AudiobookTool`") < text.index("Enable Win32 long paths")
    assert "recommended way to install" in text and "without changing any Windows setting" in text
    assert "does not guarantee that every Python package or program library works at any length" in text
    for step in ("gpedit.msc", "Computer Configuration", "Administrative Templates", "System", "Filesystem",
                 "**Enable Win32 long paths**", "**Enabled**"):
        assert step in text, step
    assert "Windows Home" in text and "managed by an organisation" in text and "administrator permission" in text
    assert "`HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\FileSystem`" in text
    assert "`LongPathsEnabled` (DWORD) set to `1`" in text and "comfortable administering Windows" in text
    assert "Restart Windows after changing the setting, before relying on it." in text
    assert "Do not move an app folder that is already set up" in text and "extract a fresh copy" in text
    assert "existing `.venv` folder by hand" in text
    assert "never changes the setting silently" in text


def test_the_readme_gives_no_command_or_script_that_changes_the_setting_and_does_not_announce_a_release():
    lowered = README.lower()
    for command in ("reg add", "reg.exe add", "set-itemproperty", "new-itemproperty", ".reg file", "regedit /s"):
        assert command not in lowered, command
    assert "there is no v0.8.0 download" in README and "v0.8.0, in development" in section()
    assert "AudiobookTool-Windows-v0.8.0" not in README
