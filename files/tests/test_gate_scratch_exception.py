"""The conditions of the owner's %TEMP%\\act-gate exception (Decisions.md, v0.7.2 Phase 3), proved on real folders.

Ownership comes from a record or from a run's evidence, never from a name that looks right; another process's scratch is
never reported as disposable; the audit changes nothing; a failing test's folder reaches the repository's evidence, and a
link in it is not followed out of the scratch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, load_gate

sys.path.insert(0, str(GATE_DIR))
from helpers import scratch  # noqa: E402

sys.path.remove(str(GATE_DIR))


def _child(root: Path, name: str, payload: bytes = b"x") -> Path:
    child = root / name
    (child / "o").mkdir(parents=True)
    (child / "o" / "file.bin").write_bytes(payload)
    return child


def _state(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["name"] == name)


def test_a_name_that_looks_right_proves_nothing(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    _child(root, "abcd")
    row = _state(scratch.audit(root, outputs), "abcd")
    assert row["state"] == "unproven" and row["owner"] is None


def test_a_child_whose_owner_process_still_runs_is_active_and_one_whose_owner_ended_is_abandoned(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    scratch.write_owner(_child(root, "aaaa"), "run-live", "nonce")
    assert _state(scratch.audit(root, outputs), "aaaa")["state"] == "active"
    # The negative control: the same record, but the process it names has really ended.
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    child = _child(root, "bbbb")
    record = {"kind": scratch.OWNER_KIND, "run_id": "run-old", "nonce": "n", "pid": ended.pid, "process_created": 1}
    (child / scratch.OWNER_NAME).write_text(json.dumps(record), encoding="utf-8")
    assert _state(scratch.audit(root, outputs), "bbbb")["state"] == "abandoned"


def test_a_reused_pid_does_not_make_an_ended_owner_look_alive(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    child = _child(root, "cccc")
    record = {"kind": scratch.OWNER_KIND, "run_id": "run", "nonce": "n", "pid": os.getpid(), "process_created": 1}
    (child / scratch.OWNER_NAME).write_text(json.dumps(record), encoding="utf-8")
    assert _state(scratch.audit(root, outputs), "cccc")["state"] == "abandoned"


def test_a_run_that_names_the_child_in_its_evidence_owns_it(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    _child(root, "dddd")
    run = outputs / "2026-11-06_000000_full_dddd"
    run.mkdir(parents=True)
    (run / "results.json").write_text(json.dumps({"status": "FAIL", "cleanup": {"scratch": str(root / "dddd")}}), encoding="utf-8")
    row = _state(scratch.audit(root, outputs), "dddd")
    assert row["state"] == "abandoned" and row["owner"]["run_id"] == run.name


@pytest.mark.skipif(sys.platform != "win32", reason="an exclusive open is how Windows reports a holder")
def test_something_holding_a_file_open_keeps_the_child_out_of_the_disposable_set(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    child = _child(root, "eeee")
    run = outputs / "run"
    run.mkdir(parents=True)
    (run / "results.json").write_text(json.dumps({"status": "FAIL", "cleanup": {"scratch": str(root / "eeee")}}), encoding="utf-8")
    with open(child / "o" / "file.bin", "rb"):
        assert _state(scratch.audit(root, outputs), "eeee")["state"] == "active"
    assert _state(scratch.audit(root, outputs), "eeee")["state"] == "abandoned"  # the control: nothing holds it now


def test_the_audit_changes_nothing(tmp_path):
    root, outputs = tmp_path / "act-gate", tmp_path / "outputs"
    _child(root, "ffff", b"keep")
    before = scratch.tree_digest(root)
    scratch.audit_lines(scratch.audit(root, outputs))
    assert scratch.tree_digest(root) == before


def test_the_gate_command_reports_and_removes_nothing(tmp_path, monkeypatch, capsys):
    gate = load_gate("act_verify_scratch")
    root = tmp_path / "act-gate"
    _child(root, "abab", b"keep")
    monkeypatch.setattr(gate, "SCRATCH_ROOT", root)
    monkeypatch.setattr(gate, "OUTPUTS_ROOT", tmp_path / "outputs")
    assert gate.main(["--audit-scratch"]) == 0
    assert any("unproven" in line and "abab" in line for line in capsys.readouterr().out.splitlines())
    assert (root / "abab" / "o" / "file.bin").read_bytes() == b"keep"


def test_a_failing_tests_folder_is_copied_and_a_passing_one_is_not(tmp_path):
    base = tmp_path / "b"
    (base / "test_bad0" / "nested").mkdir(parents=True)
    (base / "test_bad0" / "nested" / "evidence.txt").write_text("why", encoding="utf-8")
    (base / "test_good0").mkdir()
    (base / "test_good0" / "other.txt").write_text("no", encoding="utf-8")
    (base / "test_bad_also0").mkdir()
    destination = tmp_path / "failed"
    record = scratch.preserve_failed(base, ["files/tests/test_x.py::test_bad"], destination)
    assert record["copied"] == ["test_bad0"]
    assert (destination / "test_bad0" / "nested" / "evidence.txt").read_text(encoding="utf-8") == "why"
    assert not (destination / "test_good0").exists() and not (destination / "test_bad_also0").exists()


def test_a_large_failure_is_listed_as_left_out_rather_than_taken_for_complete(tmp_path):
    base = tmp_path / "b"
    (base / "test_big0").mkdir(parents=True)
    (base / "test_big0" / "huge.bin").write_bytes(b"0" * 2048)
    (base / "test_big0" / "small.txt").write_bytes(b"1")
    destination = tmp_path / "failed"
    record = scratch.preserve_failed(base, ["t.py::test_big"], destination, per_test=1024)
    assert (destination / "test_big0" / "small.txt").is_file() and not (destination / "test_big0" / "huge.bin").exists()
    assert any("huge.bin" in item for item in record["left_out"])


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is the Windows link available without privilege")
def test_a_junction_in_a_failing_tests_folder_is_not_followed_out_of_scratch(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")
    base = tmp_path / "b"
    (base / "test_bad0").mkdir(parents=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(base / "test_bad0" / "escape"), str(outside)], check=True,
                   capture_output=True)
    destination = tmp_path / "failed"
    record = scratch.preserve_failed(base, ["t.py::test_bad"], destination)
    assert record["links_not_followed"] == 1 and not (destination / "test_bad0" / "escape").exists()
    assert (outside / "private.txt").read_text(encoding="utf-8") == "private"
