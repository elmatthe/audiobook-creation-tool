"""v0.8.2 Phase 1A-1 R2: accounting obligations, explained termination and the reviewed launch profiles (GATE.md).

The regression matrix of the R2 remediation: the ledger-format-3 reader is total; a required participant is accounted only
by its own end record or by an explained stop that meets every D-R2-1 condition (positive and negative controls here, in
ledgers built row by row, and live); a bootstrapped child carries effective restrictions; startup customization, shells,
native process creation and multiprocessing run only in their reviewed forms, and a substituted source never inherits a
profile; a direct run's collection reconciles in memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import routine_effects as effects
from gate_locator import GATE_DIR, REPO_ROOT

context = effects.context
fixtures = effects.fixtures()
TESTS = REPO_ROOT / "files" / "tests"
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")
SESSION_ROLES = {"gate", "routine-pytest", "guarded-pytest", "raw-pytest"}


# --------------------------------------------------------------------------- #
#  Ledgers built row by row
# --------------------------------------------------------------------------- #
OWNER, CHILD, GRANDCHILD = "100-aaaa0000", "200-bbbb0000", "300-cccc0000"
LAUNCH, INNER = "0123456789abcdef0123", "fedcba9876543210fedc"


def _start(participant, role, *, launch=None, parent=None, pid=None, ppid=0):
    return {"kind": "start", "pid": pid or int(participant.split("-")[0]), "ppid": ppid, "role": role,
            "participant": participant, "launch": launch, "parent": parent, "executable": "python", "created": None}


MARK = {"kind": "mark", "event": "accounting-initialized"}

#: A child that could reach an effect (it imports os), so it is bootstrapped and owes a participant; an inert
#: sleeper would run under the exact inert profile instead (D-R2-8).
EFFECT_CAPABLE_SLEEPER = "import os, time; time.sleep(60)"


def _end(exit_status=0, refusals=0, unexpected=0):
    return {"kind": "end", "exit": exit_status, "refusals": refusals, "unexpected": unexpected, "accounting": "ok",
            "how": "exit"}


def _reservation(ledger: Path, launch: str, parent: str, parent_pid: int, *, stops=(), codes=(), expect="routine-child"):
    (ledger / f"r-{launch}.json").write_text(json.dumps({
        "format": context.RESERVATION_FORMAT, "launch": launch, "parent": parent, "parent_pid": parent_pid, "expect": expect,
        "stage": "", "identity": "x", "roots": [], "lifecycle": {"stops": sorted(stops), "codes": sorted(codes)},
        "created": 0.0, "note": ""}), encoding="utf-8")


def _write(ledger: Path, participant: str, rows) -> None:
    (ledger / f"p{participant}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _killed_child(tmp_path: Path, *, stops=("terminate-process",), child_rows=None, parent_middle=None, grandchild=None):
    """An owner that reserved, spawned, stopped (Popen.kill: exit 1) and then observed a child that never wrote its end."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger = effects.new_ledger(tmp_path / "l", owner="routine-pytest")
    _reservation(ledger, LAUNCH, OWNER, 100, stops=stops)
    middle = parent_middle if parent_middle is not None else [
        {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-process", "pid": 200, "code": 1, "tree": False, "ok": True},
        {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}]
    _write(ledger, OWNER, [_start(OWNER, "routine-pytest"), MARK,
                           {"kind": "reserve", "launch": LAUNCH, "expect": "routine-child", "ledger": ""},
                           {"kind": "spawned", "launch": LAUNCH, "pid": 200, "executable": "python", "redirector": False,
                            "via": "direct", "created": None}, *middle, _end()])
    _write(ledger, CHILD, child_rows if child_rows is not None else
           [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK])
    if grandchild is not None:
        _reservation(ledger, INNER, CHILD, 200)
        rows = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK,
                {"kind": "reserve", "launch": INNER, "expect": "routine-child", "ledger": ""},
                {"kind": "spawned", "launch": INNER, "pid": 300, "executable": "python", "redirector": False,
                 "via": "direct", "created": None}]
        _write(ledger, CHILD, rows)
        _write(ledger, GRANDCHILD, [_start(GRANDCHILD, "routine-child", launch=INNER, parent=CHILD, ppid=200), MARK])
        if grandchild == "gone":
            with open(ledger / f"p{OWNER}.jsonl", "r+", encoding="utf-8") as handle:
                lines = handle.read().splitlines(keepends=True)
                gone = json.dumps({"kind": "observed", "launch": INNER, "exit": None, "how": "gone", "pid": 300}) + "\n"
                handle.seek(0)
                handle.write("".join(lines[:-1] + [gone, lines[-1]]))
    return ledger


def _judge(ledger: Path) -> dict:
    return effects.read_ledger(ledger, require_role="routine-pytest")


def test_d_r2_1_an_explained_stop_accounts_for_a_participant_that_left_no_end_record(tmp_path):
    verdict = _judge(_killed_child(tmp_path))
    assert verdict["status"] == "PASS" and verdict["explained_stops"] == [LAUNCH], verdict["problems"]


@pytest.mark.parametrize("case, needle", [
    ("missing-init", "never initialized its accounting"),
    ("unexpected-termination", "expected a normal end"),
    ("wrong-identity", "not one its reservation expected"),
    ("post-hoc", "not one its reservation expected"),
    ("failed-action", "not one its reservation expected"),
    ("outcome-disagrees", "not one its reservation expected"),
    ("other-mechanism", "not one its reservation expected"),
    ("unresolved-descendant", "is not accounted"),
    ("no-observation", "not one its reservation expected"),
], ids=lambda value: value if isinstance(value, str) and " " not in value else "")
def test_d_r2_1_every_condition_of_an_explained_stop_is_required(tmp_path, case, needle):
    stop = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-process", "pid": 200, "code": 1, "tree": False, "ok": True}
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}
    kwargs = {}
    if case == "missing-init":
        kwargs["child_rows"] = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100)]
    elif case == "unexpected-termination":
        kwargs["stops"] = ()
    elif case == "wrong-identity":
        kwargs["parent_middle"] = [{**stop, "pid": 999}, seen]
    elif case == "post-hoc":
        kwargs["parent_middle"] = [seen, stop]  # observed first: an explanation written afterwards explains nothing
    elif case == "failed-action":
        kwargs["parent_middle"] = [{**stop, "ok": False}, seen]
    elif case == "outcome-disagrees":
        kwargs["parent_middle"] = [stop, {**seen, "exit": 0}]
    elif case == "other-mechanism":
        kwargs["parent_middle"] = [{**stop, "mechanism": "terminate-job"}, seen]
    elif case == "unresolved-descendant":
        kwargs["grandchild"] = "running"
    else:
        kwargs["parent_middle"] = [stop]
    verdict = _judge(_killed_child(tmp_path, **kwargs))
    assert verdict["status"] == "FAIL" and any(needle in problem for problem in verdict["problems"]), verdict["problems"]


def test_d_r2_1_a_tree_stop_accounts_for_a_descendant_observed_gone(tmp_path):
    stop = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-job", "pid": 200, "code": 1, "tree": True, "ok": True}
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}
    verdict = _judge(_killed_child(tmp_path, stops=("terminate-job",), parent_middle=[stop, seen], grandchild="gone"))
    assert verdict["status"] == "PASS" and sorted(verdict["explained_stops"]) == sorted([LAUNCH, INNER]), verdict["problems"]


def test_d_r2_1_an_explained_stop_never_waives_an_unexpected_refusal_before_it(tmp_path):
    refusal = {"kind": "refusal", "effect": "real-engine", "detail": "x", "origin": "o", "pid": 200, "expected": False}
    rows = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK, refusal]
    verdict = _judge(_killed_child(tmp_path, child_rows=rows))
    assert verdict["status"] == "FAIL" and len(verdict["unexpected"]) == 1 and verdict["explained_stops"] == [LAUNCH]


LEAF = "aaaabbbbccccddddeeee"


@pytest.mark.parametrize("case, passes", [
    ("held-by-its-job", True),
    ("not-held", False),
    ("held-by-someone-else", False),
    ("still-running", False),
    ("holder-not-explained", False),
])
def test_r2_recovery_a_descendant_held_by_an_explained_participants_job_is_accounted_only_with_that_evidence(tmp_path, case,
                                                                                                           passes):
    """A participant killed outright (not a tree stop) whose own kill-on-close Job holds its child: the kernel ends the
    child with it. That child is accounted only when the participant recorded placing it in such a Job (``contained``),
    the participant's own end is an explained stop, and the child was then observed gone."""
    ledger = _killed_child(tmp_path, grandchild="gone", stops=() if case == "holder-not-explained" else ("terminate-process",))
    holder = {"held-by-its-job": CHILD, "still-running": CHILD, "holder-not-explained": CHILD,
              "held-by-someone-else": OWNER}.get(case)
    if holder is not None:
        with open(ledger / f"p{holder}.jsonl", "r+", encoding="utf-8") as handle:
            lines = handle.read().splitlines(keepends=True)
            row = json.dumps({"kind": "contained", "launch": INNER}) + "\n"
            index = len(lines) - (1 if holder == OWNER else 0)  # the owner's record ends with its end row
            handle.seek(0)
            handle.write("".join(lines[:index] + [row] + lines[index:]))
    if case == "still-running":
        text = (ledger / f"p{OWNER}.jsonl").read_text(encoding="utf-8").replace('"how": "gone"', '"how": "running"')
        (ledger / f"p{OWNER}.jsonl").write_text(text, encoding="utf-8")
    verdict = _judge(ledger)
    assert (verdict["status"] == "PASS") == passes, verdict["problems"]


@pytest.mark.parametrize("case, passes", [
    ("gone-after-its-parents-explained-stop", True),
    ("seen-before-the-stop", False),
    ("parent-not-explained", False),
])
def test_r2_recovery_a_leaf_of_an_explained_parent_is_accounted_only_when_seen_gone_after_the_stop(tmp_path, case, passes):
    """A participant killed outright before it could observe its own finished leaf (a git read the killed gate made): the
    leaf is accounted when the owner, after its explained stop of that participant, observed the leaf's process gone."""
    stop = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-process", "pid": 200, "code": 1, "tree": False, "ok": True}
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}
    gone = {"kind": "observed", "launch": LEAF, "exit": None, "how": "gone", "pid": 400}
    middle = [gone, stop, seen] if case == "seen-before-the-stop" else [stop, seen, gone]
    leaf_rows = [{"kind": "profiled", "launch": LEAF, "profile": "git-read", "identity": "x"},
                 {"kind": "spawned", "launch": LEAF, "pid": 400, "executable": "git", "redirector": False,
                  "via": "direct", "created": None}]
    rows = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK, *leaf_rows]
    stops = () if case == "parent-not-explained" else ("terminate-process",)
    verdict = _judge(_killed_child(tmp_path, stops=stops, parent_middle=middle, child_rows=rows))
    leaf_problems = [problem for problem in verdict["problems"] if LEAF in problem]
    assert (not leaf_problems) == passes, verdict["problems"]


@pytest.mark.parametrize("case, passes", [
    ("gone-after-tree-stop", True),
    ("observed-by-its-parent", True),
    ("never-observed", False),
    ("post-hoc", False),
    ("not-a-tree-stop", False),
    ("still-running", False),
    ("another-process", False),
    ("failed-stop", False),
])
def test_r2_recovery_a_profiled_leaf_of_a_stopped_tree_is_accounted_only_when_seen_gone_after_the_stop(tmp_path, case,
                                                                                                        passes):
    """An inert leaf whose parent was stopped first (or ended and left it to the Job) is accounted by its owner's
    observation of its own process gone after the owner's successful tree stop of that chain, as a descendant participant
    is (D-R2-1); its parent's own observation still suffices, and nothing else does."""
    stop = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-job", "pid": 200, "code": 1, "tree": True, "ok": True}
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}
    gone = {"kind": "observed", "launch": LEAF, "exit": None, "how": "gone", "pid": 400}
    middle = [stop, seen, gone]
    leaf_rows = [{"kind": "profiled", "launch": LEAF, "profile": "inert-python-stand-in", "identity": "x"},
                 {"kind": "spawned", "launch": LEAF, "pid": 400, "executable": "python", "redirector": False,
                  "via": "direct", "created": None}]
    if case == "observed-by-its-parent":
        middle = [stop, seen]
        leaf_rows.append({"kind": "observed", "launch": LEAF, "exit": 0, "how": "exited", "pid": 400})
    elif case == "never-observed":
        middle = [stop, seen]
    elif case == "post-hoc":
        middle = [gone, stop, seen]
    elif case == "not-a-tree-stop":
        middle = [{**stop, "tree": False}, seen, gone]
    elif case == "still-running":
        middle = [stop, seen, {**gone, "how": "running"}]
    elif case == "another-process":
        middle = [stop, seen, {**gone, "pid": 999}]
    elif case == "failed-stop":
        middle = [{**stop, "ok": False}, seen, gone]
    rows = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK, *leaf_rows]
    if case == "not-a-tree-stop":
        rows.append(_end(0))  # the parent ended first: a later stop that is not a tree stop cannot have ended its leaf
    verdict = _judge(_killed_child(tmp_path, stops=("terminate-job",), parent_middle=middle, child_rows=rows))
    leaf_problems = [problem for problem in verdict["problems"] if LEAF in problem]
    assert (not leaf_problems) == passes, verdict["problems"]


@pytest.mark.parametrize("case, passes", [
    ("explained", True),
    ("undeclared", False),
    ("other-code", False),
    ("post-hoc", False),
    ("failed-action", False),
    ("other-process", False),
    ("no-stop", False),
])
def test_r2_recovery_a_stop_landing_after_the_end_record_explains_only_its_own_code(tmp_path, case, passes):
    """The supervisor's Job kill can land after its worker wrote its own end record (exit 0) but before the process ended
    (exit 1). Only the evidence of an explained stop (D-R2-1) accounts for that difference; anything else stays a problem."""
    stop = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-job", "pid": 200, "code": 1, "tree": True, "ok": True}
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}
    middle, stops = [stop, seen], ("terminate-job",)
    if case == "undeclared":
        stops = ()
    elif case == "other-code":
        middle = [stop, {**seen, "exit": 3}]
    elif case == "post-hoc":
        middle = [seen, stop]
    elif case == "failed-action":
        middle = [{**stop, "ok": False}, seen]
    elif case == "other-process":
        middle = [{**stop, "pid": 999}, seen]
    elif case == "no-stop":
        middle = [seen]
    rows = [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK, _end(0)]
    verdict = _judge(_killed_child(tmp_path, stops=stops, parent_middle=middle, child_rows=rows))
    assert (verdict["status"] == "PASS") == passes, verdict["problems"]
    if not passes:
        assert any("but its participant reported 0" in problem for problem in verdict["problems"]), verdict["problems"]


@pytest.mark.parametrize("mechanism", ["native-crash", "abrupt-exit"])
def test_d_r2_1_a_crash_fixture_is_explained_only_by_a_declared_exit_code(tmp_path, mechanism):
    """A crash fixture, or a fixture that ends itself with os._exit (low_memory_probe), writes no end record: only an
    observed exit among the codes its reservation declared explains it."""
    seen = {"kind": "observed", "launch": LAUNCH, "exit": 7, "how": "exited", "pid": 200}
    assert _judge(_killed_child(tmp_path, stops=(mechanism,), parent_middle=[seen]))["status"] == "FAIL", \
        "no code declared"
    ledger = _killed_child(tmp_path / "b", stops=(mechanism,), parent_middle=[seen])
    reservation = json.loads((ledger / f"r-{LAUNCH}.json").read_text(encoding="utf-8"))
    reservation["lifecycle"]["codes"] = [7]
    (ledger / f"r-{LAUNCH}.json").write_text(json.dumps(reservation), encoding="utf-8")
    assert _judge(ledger)["status"] == "PASS"
    reservation["lifecycle"]["codes"] = [9]
    (ledger / f"r-{LAUNCH}.json").write_text(json.dumps(reservation), encoding="utf-8")
    assert _judge(ledger)["status"] == "FAIL"


def test_m2_r1_03_a_required_child_that_never_wrote_its_first_record_keeps_its_obligation(tmp_path):
    ledger = _killed_child(tmp_path, parent_middle=[{"kind": "observed", "launch": LAUNCH, "exit": 2, "how": "exited",
                                                     "pid": 200}])
    (ledger / f"p{CHILD}.jsonl").unlink()
    verdict = _judge(ledger)
    assert verdict["status"] == "FAIL" and any("never recorded its accounting" in problem for problem in verdict["problems"])
    ledger = _killed_child(tmp_path / "unspawned", parent_middle=[])
    for name in (f"p{CHILD}.jsonl",):
        (ledger / name).unlink()
    rows = [json.loads(line) for line in (ledger / f"p{OWNER}.jsonl").read_text(encoding="utf-8").splitlines()]
    _write(ledger, OWNER, [row for row in rows if row["kind"] != "spawned"])
    verdict = _judge(ledger)
    assert any("unresolved" in problem for problem in verdict["problems"]), verdict["problems"]


@pytest.mark.parametrize("line", ['{"kind": ["start"]}', '{"kind": {"a": 1}}', "[]", "7", "null", '"text"',
                                  '{"kind": "spawned", "launch": "0123456789abcdef0123", "pid": "2"}',
                                  '{"kind": "end", "exit": true, "refusals": 0, "unexpected": 0, "accounting": "ok", "how": "exit"}'])
def test_m2_r1_04_a_malformed_row_is_a_controlled_failure_never_an_exception(tmp_path, line):
    ledger = _killed_child(tmp_path)
    with open(ledger / f"p{OWNER}.jsonl", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    verdict = _judge(ledger)
    assert verdict["status"] == "FAIL" and verdict["problems"], verdict


def test_m2_a_reservation_and_its_reserving_row_must_agree(tmp_path):
    ledger = _killed_child(tmp_path)
    reservation = json.loads((ledger / f"r-{LAUNCH}.json").read_text(encoding="utf-8"))
    (ledger / f"r-{LAUNCH}.json").write_text(json.dumps({**reservation, "expect": "routine-pytest"}), encoding="utf-8")
    assert any("does not reserve it so" in problem for problem in _judge(ledger)["problems"])
    (ledger / f"r-{LAUNCH}.json").unlink()
    verdict = _judge(ledger)
    assert verdict["status"] == "FAIL" and any("no reservation" in problem for problem in verdict["problems"])


def test_m2_a_foreign_or_duplicate_participant_is_never_clean(tmp_path):
    ledger = _killed_child(tmp_path)
    _write(ledger, "400-dddd0000", [_start("400-dddd0000", "routine-child"), MARK, _end()])
    assert any("foreign" in problem for problem in _judge(ledger)["problems"])
    (ledger / "p400-dddd0000.jsonl").unlink()
    _write(ledger, "500-eeee0000", [_start("500-eeee0000", "routine-child", launch=LAUNCH, parent=OWNER), MARK, _end()])
    assert any("duplicate" in problem for problem in _judge(ledger)["problems"])


def test_m2_a_historical_ledger_reads_back_but_never_satisfies_the_current_contract(tmp_path):
    ledger = tmp_path / "v2"
    ledger.mkdir()
    (ledger / context.LEDGER_HEADER).write_text(json.dumps({"format": "act-effect-ledger/2", "owner": "gate", "stage": "",
                                                            "token": ""}), encoding="utf-8")
    verdict = effects.read_ledger(ledger)
    assert verdict["status"] == "FAIL" and any("historical" in problem for problem in verdict["problems"])


# --------------------------------------------------------------------------- #
#  Live: the explained stop and its negative, through the real boundary
# --------------------------------------------------------------------------- #
def _wait_initialized(launch: str, ledger: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        verdict = effects.read_ledger(ledger, live=True)
        if any(entry.get("launch") == launch and entry.get("initialized") for entry in verdict["participants"].values()):
            return
        time.sleep(0.05)
    raise AssertionError("the child never initialized its accounting")


def test_d_r2_1_live_a_reserved_expected_stop_is_explained(tmp_path):
    ledger = os.environ[effects.LEDGER_ENV]
    with effects.expected_termination("terminate-process"):
        child = subprocess.Popen([sys.executable, "-c", EFFECT_CAPABLE_SLEEPER])
        launch = child._act_launch
        try:
            _wait_initialized(launch, ledger)
        finally:
            child.kill()
            child.wait(timeout=60)
    verdict = effects.read_ledger(ledger, open_roles=SESSION_ROLES)
    assert verdict["launches"][launch]["state"] == "explained-stop", [p for p in verdict["problems"] if launch in p]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
def test_r2_recovery_live_closing_a_kill_on_close_job_records_its_stop():
    """Closing the last handle of a kill-on-close Job ends its members: the close is recorded as their stop (the Job's
    limits are read with the exact structure; a larger buffer is refused, which used to leave such a stop unrecorded)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class Extended(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32),
                    ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    ledger = os.environ[effects.LEDGER_ENV]
    job = kernel32.CreateJobObjectW(None, None)
    assert job
    limits = Extended()
    limits.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    with effects.expected_termination("close-job"):
        child = subprocess.Popen([sys.executable, "-c", EFFECT_CAPABLE_SLEEPER])
        launch = child._act_launch
        try:
            assert kernel32.AssignProcessToJobObject(job, int(child._handle))
            _wait_initialized(launch, ledger)
        finally:
            assert kernel32.CloseHandle(job)
            child.wait(timeout=60)
    effects.observe_children()
    verdict = effects.read_ledger(ledger, open_roles=SESSION_ROLES)
    assert verdict["launches"][launch]["state"] == "explained-stop", [p for p in verdict["problems"] if launch in p]


def test_d_r2_1_live_an_unexpected_stop_is_never_explained(tmp_path):
    private = effects.new_ledger(tmp_path / "private")
    with effects.expected_refusals(accounting="report") as scope:
        child = subprocess.Popen([sys.executable, "-c", EFFECT_CAPABLE_SLEEPER],
                                 env={**os.environ, effects.LEDGER_ENV: str(private)})
        try:
            _wait_initialized(child._act_launch, str(private))
        finally:
            child.kill()
            child.wait(timeout=60)
    verdict = scope.ledgers[str(private)]
    assert verdict["status"] == "FAIL" and any("expected a normal end" in problem for problem in verdict["problems"]), verdict


def test_d_r2_1_a_lifecycle_is_never_established_after_the_launch(tmp_path):
    private = effects.new_ledger(tmp_path / "late")
    with effects.expected_refusals(accounting="report") as scope:
        child = subprocess.Popen([sys.executable, "-c", EFFECT_CAPABLE_SLEEPER],
                                 env={**os.environ, effects.LEDGER_ENV: str(private)})
        try:
            _wait_initialized(child._act_launch, str(private))
            with effects.expected_termination("terminate-process"):  # opened after the launch: explains nothing
                child.kill()
        finally:
            child.wait(timeout=60)
    assert any("expected a normal end" in problem for problem in scope.ledgers[str(private)]["problems"])


# --------------------------------------------------------------------------- #
#  H2/H3: a bootstrapped child carries effective restrictions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code, effect", [
    ("import socket; socket.getaddrinfo('example.invalid', 80)", "external-network"),
    ("import os; os.system('winget --version')", "install"),
    ("import subprocess, sys; subprocess.run(['winget', '--version'])", "install"),
    ("import os; os.startfile('book.m4b')" if os.name == "nt" else "import os; os.fork()", "native-desktop"
     if os.name == "nt" else "real-app-launch"),
])
def test_h2_a_python_child_refuses_what_its_parent_would_refuse(tmp_path, code, effect):
    private = effects.new_ledger(tmp_path / "child")
    with effects.expected_refusals(effect, accounting="report") as scope:
        done = subprocess.run([sys.executable, "-c", code], env={**os.environ, effects.LEDGER_ENV: str(private)},
                              capture_output=True, text=True, timeout=120)
    verdict = scope.ledgers[str(private)]
    assert done.returncode != 0 and "refused in routine verification" in done.stderr, done.stderr[-1500:]
    assert [row["effect"] for row in verdict["refusals"]] == [effect] and verdict["problems"] == [], verdict


def test_h2_the_child_runs_the_program_exactly_as_the_unprepared_command_would(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text("import json, os, sys\nprint(json.dumps({'argv': sys.argv, 'path0': sys.path[0], 'main': __name__,\n"
                      "      'file': __file__, 'flags': [sys.flags.isolated, sys.flags.dont_write_bytecode],\n"
                      "      'pythonpath': os.environ.get('PYTHONPATH'), 'launch': os.environ.get('ACT_ROUTINE_LAUNCH')}))\n",
                      encoding="utf-8")
    extra = tmp_path / "extra"
    extra.mkdir()
    done = subprocess.run([sys.executable, "-B", str(script), "a", "b"], capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PYTHONPATH": str(extra)}, cwd=tmp_path)
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert seen["argv"] == [str(script), "a", "b"] and seen["main"] == "__main__" and seen["file"] == str(script)
    assert os.path.normcase(seen["path0"]) == os.path.normcase(str(tmp_path)) and seen["flags"] == [0, 1]
    assert seen["pythonpath"] == str(extra) and seen["launch"] is None, seen
    module = subprocess.run([sys.executable, "-c", "import sys; print(sys.argv)", "x"], capture_output=True, text=True,
                            timeout=120)
    assert module.stdout.strip() == "['-c', 'x']"


def test_h2_a_shell_cannot_carry_a_python_child_past_its_envelope():
    for command in (["cmd", "/c", f'"{sys.executable}" -c "print(1)"'], ["cmd", "/c", "python", "-c", "print(1)"],
                    ["powershell", "-Command", f"& '{sys.executable}' -c 'print(1)'"]):
        assert effects.classify_launch(command, cwd=REPO_ROOT) is not None, command


# --------------------------------------------------------------------------- #
#  D-R2-2 / D-R2-3: startup measurements, by their exact reviewed profiles only
# --------------------------------------------------------------------------- #
def _shim(tmp_path: Path, text: str) -> dict:
    shim = tmp_path / "shim"
    shim.mkdir(parents=True, exist_ok=True)
    (shim / "sitecustomize.py").write_text(text, encoding="utf-8")
    return {**os.environ, "PYTHONPATH": str(shim), "ACT_HANG_PID_FILE": str(tmp_path / "hung.pid")}


def _constant(module: str, name: str) -> str:
    import ast

    tree = ast.parse((TESTS / module).read_text(encoding="utf-8"))
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", None) == name)


def test_d_r2_2_the_tk_proof_faults_get_their_profiles_and_a_substitute_does_not(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from shared import bootstrap

    probe = [sys.executable, "-c", bootstrap._VENV_PROBE]
    broken = effects.decide_launch(probe, env=_shim(tmp_path / "a", _constant("test_tk_proof.py", "BREAK_TK")))
    assert broken.outcome == effects.BOOTSTRAP and broken.profile == "tk-proof-break-tk" and broken.keep_pythonpath
    hang = effects.decide_launch(probe, env=_shim(tmp_path / "b", _constant("test_tk_proof.py", "HANG")))
    assert hang.outcome == effects.PROFILE and hang.profile == "tk-proof-hang", hang
    other_code = effects.decide_launch([sys.executable, "-c", "print(1)"],
                                       env=_shim(tmp_path / "c", _constant("test_tk_proof.py", "HANG")))
    assert other_code.refused, "the hang profile binds the production probe"
    substituted = effects.decide_launch(probe, env=_shim(tmp_path / "d", _constant("test_tk_proof.py", "HANG") + "# x\n"))
    assert substituted.refused and "sitecustomize" in substituted.reason, substituted
    for name in ("usercustomize.py", "sitecustomize.py"):
        folder = tmp_path / f"arbitrary-{name}"
        folder.mkdir()
        (folder / name).write_text("print('runs before the envelope')\n", encoding="utf-8")
        assert effects.decide_launch(probe, env={**os.environ, "PYTHONPATH": str(folder)}).refused, name
    for variable in ("PYTHONHOME", "PYTHONINSPECT"):
        assert effects.decide_launch(probe, env={**os.environ, variable: str(tmp_path)}).refused, variable


def test_d_r2_3_the_footprint_probe_runs_unchanged_only_in_its_exact_form(tmp_path):
    base = getattr(sys, "_base_executable", "") or sys.executable
    scripts = str(REPO_ROOT / "scripts")
    exact = fixtures.PRE_VENV_PROBE.format(scripts=scripts, extra="")
    assert effects.decide_launch([base, "-I", "-S", "-c", exact], cwd=tmp_path).profile == "pre-venv-import-footprint"
    for command, where in (([base, "-I", "-S", "-c", exact + "import ctypes\n"], tmp_path),
                           ([base, "-I", "-S", "-c", fixtures.PRE_VENV_PROBE.format(scripts=str(tmp_path), extra="")], tmp_path),
                           ([base, "-I", "-c", exact], tmp_path), ([base, "-I", "-S", "-c", exact], REPO_ROOT)):
        decision = effects.decide_launch(command, cwd=where)
        assert decision.profile != "pre-venv-import-footprint", (command[1:3], where, decision)


# --------------------------------------------------------------------------- #
#  D-R2-4: native, shell and multiprocessing mechanisms
# --------------------------------------------------------------------------- #
@WINDOWS
def test_d_r2_4_the_fake_ffmpeg_wrapper_is_reviewed_only_with_its_exact_script(tmp_path):
    script, wrapper = tmp_path / "fake_ffmpeg.py", tmp_path / "fake_ffmpeg.cmd"
    script.write_text(_constant("test_qwen3_synth.py", "FAKE_FFMPEG"), encoding="utf-8")
    wrapper.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    assert effects.decide_launch([str(wrapper), "-i", "a.wav", str(tmp_path / "o.mp3")]).profile == "fake-ffmpeg-wrapper"
    script.write_text(_constant("test_qwen3_synth.py", "FAKE_FFMPEG") + "import os\n", encoding="utf-8")
    assert effects.decide_launch([str(wrapper), "-i", "a.wav", str(tmp_path / "o.mp3")]).refused


@WINDOWS
def test_d_r2_4_a_taskkill_reaches_only_a_process_this_session_owns():
    assert effects.classify_launch(["taskkill", "/PID", str(os.getpid()), "/F"], cwd=REPO_ROOT) is not None
    assert effects.classify_launch(["taskkill", "/IM", "python.exe", "/F"], cwd=REPO_ROOT) is not None


@WINDOWS
def test_d_r2_4_unreviewed_native_process_creation_is_refused_and_the_low_integrity_profile_is_exact(tmp_path):
    import ctypes

    with effects.expected_refusals("real-app-launch"):
        with pytest.raises(effects.EffectRefused):
            ctypes.WinDLL("kernel32").CreateProcessW
        sys.path.insert(0, str(GATE_DIR))
        try:
            from adapters.windows import containment
        finally:
            sys.path.remove(str(GATE_DIR))
        with pytest.raises(effects.EffectRefused, match="Low-integrity"):
            containment.spawn_low([sys.executable, "-I", "-B", "-c", "print('not the reviewed probe')"], cwd=tmp_path,
                                  env=dict(os.environ), output=tmp_path / "o.log", suspended=False)


def test_d_r2_4_a_multiprocessing_spawn_child_is_bootstrapped_and_accounted():
    import multiprocessing

    process = multiprocessing.get_context("spawn").Process(target=int)
    process.start()
    process.join(120)
    assert process.exitcode == 0
    launch = next(entry.launch for entry in list(effects._launches.values()) if entry.pid == process.pid)
    effects.observe_children()
    verdict = effects.read_ledger(os.environ[effects.LEDGER_ENV], open_roles=SESSION_ROLES)
    assert verdict["launches"][launch]["state"] == "accounted", [p for p in verdict["problems"] if launch in p]


def test_r2_recovery_a_test_that_replaces_builtins_open_cannot_redirect_the_envelopes_own_evidence(monkeypatch):
    """test_fatal_diagnostics replaces ``builtins.open`` with a stub; the envelope's ledger reads use the original open
    captured at import, so its verdicts stay true (before: "the ledger could not be reconciled (AttributeError)")."""
    import builtins
    import io

    ledger = os.environ[effects.LEDGER_ENV]
    before = effects.read_ledger(ledger, open_roles=SESSION_ROLES)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", lambda *args, **kwargs: io.StringIO())
        during = effects.read_ledger(ledger, open_roles=SESSION_ROLES)
    assert not [problem for problem in during["problems"] if "could not be reconciled" in problem], during["problems"]
    assert during["processes"] >= before["processes"] > 0


def test_r2_recovery_a_bootstrapped_child_loads_no_module_its_program_did_not_ask_for():
    """The envelope's multiprocessing wrapper is applied when the program loads multiprocessing, never eagerly: an eager
    import put socket, select, selectors and multiprocessing into every bootstrapped child (import-footprint tests)."""
    code = ("import json, sys; print(json.dumps(sorted(m for m in ('socket', 'select', 'selectors', 'multiprocessing',"
            " 'multiprocessing.spawn') if m in sys.modules)))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and json.loads(done.stdout.strip().splitlines()[-1]) == [], done.stdout + done.stderr


# --------------------------------------------------------------------------- #
#  R2 recovery: D-R2-9 (scrubbed guarded workers), D-R2-7 (worker network-guard measurements), launch families
# --------------------------------------------------------------------------- #
def _v3_env(root: Path, **changes) -> dict:
    env = {"SystemRoot": fixtures._windows_directory(), "TEMP": str(root), "TMP": str(root), "TMPDIR": str(root),
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    env.update(changes)
    return {key: value for key, value in env.items() if value is not None}


def _copy_scripts(scripts: Path, *relatives: str) -> None:
    for relative in relatives:
        target = scripts / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / "scripts" / relative).read_bytes())


@WINDOWS
def test_d_r2_9_the_supervisor_fake_worker_runs_unchanged_only_exactly_as_reviewed(tmp_path):
    root = tmp_path / "fake-run"
    root.mkdir()
    script = root / "fake_worker.py"
    script.write_text(fixtures._module_string(fixtures.V3_SUPERVISOR, "_FAKE_PROGRAM"), encoding="utf-8")
    argv = [sys.executable, "-I", "-B", "-S", str(script), "ok"]
    exact = effects.decide_launch(argv, cwd=str(root), env=_v3_env(root))
    assert exact.outcome == effects.PROFILE and exact.profile == "v3-supervisor-fake-worker", exact
    for env in (_v3_env(root, EXTRA="1"), _v3_env(root, TEMP=str(tmp_path)), _v3_env(root, HF_HUB_OFFLINE=None),
                _v3_env(root, SystemRoot=str(tmp_path))):
        assert effects.decide_launch(argv, cwd=str(root), env=env).refused, sorted(env)
    assert effects.decide_launch(argv[:4] + [str(script), "--grandchild"], cwd=str(root), env=_v3_env(root)).refused
    assert effects.decide_launch(argv, cwd=str(tmp_path), env=_v3_env(root)).refused, "another working directory"
    script.write_text(fixtures._module_string(fixtures.V3_SUPERVISOR, "_FAKE_PROGRAM") + "# changed\n", encoding="utf-8")
    assert effects.decide_launch(argv, cwd=str(root), env=_v3_env(root)).refused, "a changed program"


@WINDOWS
def test_d_r2_9_the_planning_workers_run_unchanged_only_over_the_marked_sources(tmp_path):
    root = tmp_path / "run"
    scripts = root / "app" / "scripts"
    _copy_scripts(scripts, "tts/__init__.py", "shared/__init__.py", "tts/optional_setup_planning_worker_v3.py")
    readonly = fixtures._module_string(fixtures.V3_READONLY, "_BOOTSTRAP")
    tokens = ["a" * 32, "b" * 32]

    def decide(code):
        return effects.decide_launch([sys.executable, "-I", "-B", "-S", "-c", code, *tokens], cwd=str(scripts),
                                     env=_v3_env(root))

    assert decide(readonly).profile == "v3-readonly-planning-worker"
    adapter = scripts / "_planning_fixture.py"
    prefix = fixtures._module_string(fixtures.V3_ADAPTER_SOURCE, "FIXTURE_ADAPTER")
    adapter.write_bytes((prefix + "\nSTATE = 1\n").encode())
    planning = fixtures._module_string(fixtures.V3_BRIDGE, "_BOOTSTRAP")
    assert decide(planning).profile == "v3-planning-worker"
    worker = scripts / "tts" / "optional_setup_planning_worker_v3.py"
    worker.write_bytes(worker.read_bytes() + b"\n# replaced\n")  # the module-pin control's exact inert form
    assert decide(planning).profile == "v3-planning-worker"
    worker.write_bytes(worker.read_bytes() + b"x = 1\n")  # any other change is not the reviewed worker
    assert decide(planning).refused
    _copy_scripts(scripts, "tts/optional_setup_planning_worker_v3.py")
    adapter.write_bytes(b"import socket\n" + (prefix + "\n").encode())  # code before the reviewed containment prefix
    assert decide(planning).refused
    adapter.write_bytes(prefix.encode())
    assert decide(readonly).refused, "the read-only worker's import root holds no adapter"
    adapter.unlink()
    (scripts / "tts" / "__init__.py").write_bytes(b"import os\n")
    assert decide(readonly).refused, "a changed source"
    assert decide(readonly + "\nimport os").refused, "a changed program"


@WINDOWS
def test_d_r2_7_the_stand_in_stack_is_a_network_guard_measurement_only_exactly(tmp_path):
    folder = tmp_path / "stack-run"
    stack = folder / "stack"
    for name, constant in (("torch", "FAKE_TORCH"), ("omnivoice", "FAKE_OMNIVOICE")):
        (stack / name).mkdir(parents=True)
        (stack / name / "__init__.py").write_text(fixtures._module_string(fixtures.OV_SYNTH_TESTS, constant),
                                                  encoding="utf-8")
    (stack / "omnivoice_worker.py").write_bytes(fixtures.OV_WORKER.read_bytes())
    launcher = folder / "launch_worker.py"
    launcher.write_text(fixtures._module_string(fixtures.OV_SYNTH_TESTS, "STACK_LAUNCHER"), encoding="utf-8")
    job = folder / "job.json"
    outputs = {"out_dir": str(folder / "chunks"), "cancel_file": str(folder / "cancel"),
               "engine_lock": str(folder / "engine.lock")}
    job.write_text(json.dumps(outputs), encoding="utf-8")
    argv = [sys.executable, "-I", str(launcher), str(job)]
    exact = effects.decide_launch(argv, cwd=str(folder))
    assert exact.outcome == effects.BOOTSTRAP and exact.measurement == "network-guard", exact
    job.write_text(json.dumps({**outputs, "out_dir": str(REPO_ROOT / "files" / "elsewhere")}), encoding="utf-8")
    assert effects.decide_launch(argv, cwd=str(folder)).measurement is None, "an output outside the disposable roots"
    job.write_text(json.dumps(outputs), encoding="utf-8")
    (stack / "numpy").mkdir()
    assert effects.decide_launch(argv, cwd=str(folder)).measurement is None, "an unreviewed stand-in"
    (stack / "numpy").rmdir()
    (stack / "omnivoice_worker.py").write_bytes(fixtures.OV_WORKER.read_bytes() + b"\n")
    assert effects.decide_launch(argv, cwd=str(folder)).measurement is None, "a changed worker"
    (stack / "omnivoice_worker.py").write_bytes(fixtures.OV_WORKER.read_bytes())
    assert effects.decide_launch([sys.executable, str(launcher), str(job)], cwd=str(folder)).measurement is None
    probe = tmp_path / "probe.py"
    probe.write_text(fixtures.OV_REFERENCE_HEAD + repr(str(fixtures.OV_WORKER.parent)) + fixtures.OV_REFERENCE_TAIL,
                     encoding="utf-8")
    assert effects.decide_launch([sys.executable, "-I", str(probe)]).measurement == "network-guard"
    probe.write_text(fixtures.OV_REFERENCE_HEAD + repr(str(tmp_path)) + fixtures.OV_REFERENCE_TAIL, encoding="utf-8")
    assert effects.decide_launch([sys.executable, "-I", str(probe)]).measurement is None, "another worker folder"


def test_d_r2_7_the_measured_guard_refuses_first_and_the_envelope_refuses_what_it_lets_through(tmp_path):
    """Live, in a bootstrapped child: with the measurement deferred, the program's own audit hook decides first (its
    exception, no envelope refusal); a guard that lets a remote lookup through is still refused before anything
    resolves, and that refusal is recorded (so the measuring test fails)."""
    program = ("import json, socket, sys\nimport routine_effects\nroutine_effects._defer_network()\n"
               "class Refused(Exception):\n    pass\n"
               "GUARD = sys.argv[1] == 'guard'\n"
               "def guard(event, args):\n"
               "    if GUARD and event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost'):\n"
               "        raise Refused(args[0])\n"
               "sys.addaudithook(guard)\nresult = {}\n"
               "for host in ('example.invalid', 'example.invalid'):\n"
               "    try:\n        socket.getaddrinfo(host, 443)\n        result[host] = 'resolved'\n"
               "    except Refused:\n        result[host] = 'guard'\n"
               "    except routine_effects.EffectRefused:\n        result[host] = 'envelope'\n"
               "print(json.dumps(result))\n")
    for mode, expected, refusals in (("guard", "guard", 0), ("broken", "envelope", 2)):  # two lookups each
        private = effects.new_ledger(tmp_path / mode)
        with effects.expected_refusals(*(("external-network",) if refusals else ()), accounting="report") as scope:
            done = subprocess.run([sys.executable, "-c", program, mode], capture_output=True, text=True, timeout=120,
                                  env={**os.environ, effects.LEDGER_ENV: str(private)})
        assert done.returncode == 0, done.stderr[-1500:]
        assert json.loads(done.stdout.strip().splitlines()[-1]) == {"example.invalid": expected}, done.stdout
        verdict = scope.ledgers[str(private)]
        assert len(verdict["refusals"]) == refusals and verdict["problems"] == [], (mode, verdict)
        if refusals:
            assert "not refused by the measured guard" in verdict["refusals"][0]["detail"]


@pytest.mark.parametrize("code, inert", [
    ("import time;time.sleep(60)", True),
    ("import sys,time;\nfor _ in range(6):\n  sys.stdout.buffer.write(b'x'*(1<<20));sys.stdout.buffer.flush();time.sleep(0.3)",
     True),
    ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ok', flush=True); time.sleep(60)", True),
    ("import time\nwhile True:\n    time.sleep(1)", True),
    ("pass", True),
    ("import os; os.system('x')", False),
    ("import time; open('x', 'w')", False),
    ("import time, socket", False),
    ("import sys; sys.modules['os'].system('x')", False),
    ("import time; time.sleep(__import__('os').getpid())", False),
    ("exec('import os')", False),
    ("import sys; sys.stdout.write(sys.argv[0])", False),
    ("import sys as s; s.exit(0)", False),
    ("import time\nfor i in range(3):\n    time.sleep(i)", False),
])
def test_d_r2_8_only_an_inert_stand_in_runs_unchanged(code, inert):
    decision = effects.decide_launch([sys.executable, "-I", "-c", code])
    assert (decision.profile == "inert-python-stand-in") == inert, decision
    if not inert:
        assert decision.outcome != effects.PROFILE, decision


def test_d_r2_8_an_inert_stand_in_needs_no_startup_customization_and_this_interpreter(tmp_path):
    code = "import time;time.sleep(60)"
    plain = {name: value for name, value in os.environ.items() if not name.startswith("PYTHON")}
    assert effects.decide_launch([sys.executable, "-c", code], env=plain).profile == "inert-python-stand-in"
    assert effects.decide_launch([sys.executable, "-c", code], env={**plain, "PYTHONSTARTUP": "x.py"}).profile \
        == "inert-python-stand-in", "read only by an interactive session, which a -c program is not"
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONINSPECT", "PYTHONUSERBASE", "PYTHONEXECUTABLE"):
        assert effects.decide_launch([sys.executable, "-c", code], env={**plain, name: str(tmp_path)}).profile \
            != "inert-python-stand-in", name
    assert effects.decide_launch([sys.executable, "-i", "-c", code], env=plain).profile != "inert-python-stand-in"
    assert effects.decide_launch([sys.executable, "-I", "-c", code],
                                 env={**os.environ, "PYTHONPATH": str(tmp_path)}).profile == "inert-python-stand-in"
    assert effects.decide_launch([sys.executable, "-c", code, "arg"]).profile != "inert-python-stand-in"


def test_d_r2_8_a_stand_in_cancelled_inside_its_startup_leaves_the_ledger_clean():
    """The fast-cancellation shape (killed before any Python could have initialized): an inert stand-in owes no
    participant, so the parent's spawn, stop and observed end are its whole record and nothing is unexplained."""
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(60)"])
    child.kill()
    child.wait(timeout=60)
    effects.observe_children()
    verdict = effects.read_ledger(os.environ[effects.LEDGER_ENV], open_roles=SESSION_ROLES)
    launch = child._act_launch
    assert not [problem for problem in verdict["problems"] if launch in problem], verdict["problems"]


def test_r2_recovery_git_init_is_reviewed_only_for_a_disposable_repository(tmp_path):
    exact = effects.decide_launch(["git", "init", "-q", "--template=", str(tmp_path / "repo")], cwd=str(REPO_ROOT))
    assert exact.profile == "git-disposable-repository", exact
    for argv, cwd in ((["git", "init", "-q", "-b", "main"], tmp_path),
                      (["git", "init", "--initial-branch=main", str(tmp_path / "repo")], REPO_ROOT)):
        assert effects.decide_launch(argv, cwd=str(cwd)).profile == "git-disposable-repository", argv
    for argv in (["git", "init", "-q", str(REPO_ROOT / "not-disposable")],
                 ["git", "init", "-q", f"--template={REPO_ROOT}", str(tmp_path / "repo")],
                 ["git", "init", "--separate-git-dir=x", str(tmp_path / "repo")],
                 ["git", "init", "-q", "-b", "main", str(REPO_ROOT / "not-disposable")],
                 ["git", "init", "-q", "-b", "--bad", str(tmp_path / "repo")],
                 ["git", "init", "-q", "-b"],
                 ["git", "init", "-q"]):
        assert effects.decide_launch(argv, cwd=str(REPO_ROOT)).refused, argv


@WINDOWS
def test_r2_recovery_only_the_reviewed_nvidia_queries_have_a_profile():
    program = fixtures._system32("nvidia-smi.exe")
    for arguments, reviewed in ((fixtures.NVIDIA_QUERY, True), (["--query-gpu=name,compute_cap", "--format=csv,noheader"], True),
                                (["--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"], False),
                                (["-pm", "1"], False), ([], False)):
        argv = ["nvidia-smi", *arguments]
        found = fixtures.recognize(effects.facts_for(argv, program, str(REPO_ROOT), {}, None))
        assert (found is not None and found["profile"] == "gpu-query") == reviewed, arguments


@WINDOWS
def test_r2_recovery_the_low_integrity_scratch_probe_is_exact(tmp_path):
    scratch = tmp_path / "scratch"
    paths = {"earlier": str(scratch / "in" / "made-before-the-label.txt"),
             "later": str(scratch / "in" / "made-after-the-label.txt"), "new": str(scratch / "new.txt"),
             "beside": str(tmp_path / "beside" / "x.txt")}
    frames = [(str(fixtures.CONTAINMENT), "spawn_low"), (str(TESTS / "test_dialog_containment.py"), "_low_python")]
    argv = [sys.executable, "-I", "-B", "-c", fixtures.LOW_SCRATCH_PROBE.format(**paths)]
    assert fixtures.native_launch_reviewed(argv, scratch, frames, effects.disposable) == "low-integrity-scratch-probe"
    moved = {**paths, "beside": str(REPO_ROOT / "x.txt")}
    assert fixtures.native_launch_reviewed(argv[:4] + [fixtures.LOW_SCRATCH_PROBE.format(**moved)], scratch, frames,
                                           effects.disposable) is None
    assert fixtures.native_launch_reviewed(argv, scratch, [frames[0], (frames[1][0], "other")], effects.disposable) is None
    assert fixtures.native_launch_reviewed(argv[:4] + [argv[4] + "import os\n"], scratch, frames, effects.disposable) is None


# --------------------------------------------------------------------------- #
#  M1: a direct run's collection reconciles in memory
# --------------------------------------------------------------------------- #
def test_m1_a_test_dropped_without_deselection_fails_a_direct_run(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_two.py").write_text("def test_kept():\n    pass\n\ndef test_dropped():\n    pass\n", encoding="utf-8")
    (suite / "dropper.py").write_text(textwrap.dedent("""
        def pytest_collection_modifyitems(items):
            items[:] = [item for item in items if not item.name.endswith("dropped")]
    """), encoding="utf-8")
    private = effects.new_ledger(tmp_path / "l")
    command = [sys.executable, "-u", str(TESTS / "routine_pytest.py"), str(suite), "-q", "-p", "no:cacheprovider", "-p",
               "conftest", "-p", "dropper", f"--basetemp={tmp_path / 'b'}", "--rootdir", str(suite)]
    with effects.expected_refusals(accounting="report") as scope:
        done = subprocess.run(command, cwd=TESTS, capture_output=True, text=True, timeout=300,
                              env={**os.environ, effects.LEDGER_ENV: str(private), "PYTHONPATH": str(suite)})
    assert scope.ledgers[str(private)]["problems"] == [], scope.ledgers[str(private)]["problems"]
    assert done.returncode == 1 and "1 passed" in done.stdout and "does not reconcile" in done.stderr, \
        (done.stdout[-1500:], done.stderr[-1500:])


# --------------------------------------------------------------------------- #
#  v0.8.2 Phase 1A-1 R3 (independent R2 review): launch evidence, stop attribution, startup and admission, recipes
# --------------------------------------------------------------------------- #
def _completed(tmp_path: Path, *, parent_rows=None, child_end=0) -> Path:
    """An owner that reserved a child which completed with its own end record; ``parent_rows`` replaces the owner's spawn and
    observation (default: one spawn, one exited observation agreeing with the child)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger = effects.new_ledger(tmp_path / "l", owner="routine-pytest")
    _reservation(ledger, LAUNCH, OWNER, 100)
    middle = parent_rows if parent_rows is not None else [
        {"kind": "spawned", "launch": LAUNCH, "pid": 200, "executable": "python", "redirector": False, "via": "direct",
         "created": None},
        {"kind": "observed", "launch": LAUNCH, "exit": child_end, "how": "exited", "pid": 200}]
    _write(ledger, OWNER, [_start(OWNER, "routine-pytest"), MARK,
                           {"kind": "reserve", "launch": LAUNCH, "expect": "routine-child", "ledger": ""}, *middle, _end()])
    _write(ledger, CHILD, [_start(CHILD, "routine-child", launch=LAUNCH, parent=OWNER, ppid=100), MARK, _end(child_end)])
    return ledger


_SPAWN = {"kind": "spawned", "launch": LAUNCH, "pid": 200, "executable": "python", "redirector": False, "via": "direct",
          "created": None}
_EXIT0 = {"kind": "observed", "launch": LAUNCH, "exit": 0, "how": "exited", "pid": 200}


@pytest.mark.parametrize("case, rows, needle", [
    ("missing-parent-spawn", [_EXIT0], "never recorded its spawn"),
    ("missing-independent-observation", [_SPAWN], "never independently observed"),
    ("child-only-clean-record", [], "never recorded its spawn"),
    ("duplicate-observation", [_SPAWN, _EXIT0, dict(_EXIT0)], "observed 2 times"),
    ("mismatched-observation", [_SPAWN, {**_EXIT0, "pid": 999}], "not the spawned process"),
    ("running-look-only", [_SPAWN, {**_EXIT0, "how": "running", "exit": None}], "never independently observed"),
])
def test_r3_03_a_completed_launch_needs_its_parents_own_spawn_and_one_terminal_observation(tmp_path, case, rows, needle):
    """R3-03 (independent reproduction: parent spawn and observation removed, read_ledger still PASS): every completed
    reserved launch needs exactly one spawn and one terminal observation by its reserving parent; the child's own clean
    record never substitutes for them."""
    verdict = _judge(_completed(tmp_path, parent_rows=rows))
    assert verdict["status"] == "FAIL" and any(needle in problem for problem in verdict["problems"]), verdict["problems"]


def test_r3_03_the_same_completed_launch_with_its_parent_evidence_passes(tmp_path):
    verdict = _judge(_completed(tmp_path))
    assert verdict["status"] == "PASS", verdict["problems"]


def _stopped(tmp_path, *, stops=("terminate-process",), codes=(), middle, grandchild_rows=None) -> Path:
    return _killed_child(tmp_path, stops=stops, parent_middle=middle, grandchild=grandchild_rows)


_KILL = {"kind": "stop", "launch": LAUNCH, "mechanism": "terminate-process", "pid": 200, "code": 1, "tree": False, "ok": True}
_EXIT1 = {"kind": "observed", "launch": LAUNCH, "exit": 1, "how": "exited", "pid": 200}


@pytest.mark.parametrize("case, stops, middle", [
    ("failed-taskkill", ("taskkill",), [{**_KILL, "mechanism": "taskkill", "tree": True, "ok": False}, _EXIT1]),
    ("intent-without-successful-action", ("terminate-process",), [{**_KILL, "ok": False}, _EXIT1]),
    ("incorrect-process-identity", ("terminate-process",), [{**_KILL, "pid": 999}, _EXIT1]),
    ("reused-pid-creation-time", ("terminate-process",), [{**_KILL, "created": 7}, _EXIT1]),
    ("wrong-stop-chronology", ("terminate-process",), [_EXIT1, _KILL]),
    ("code-less-close-job-wrong-exit", ("close-job",), [{**_KILL, "mechanism": "close-job", "code": None, "tree": True},
                                                       {**_EXIT1, "exit": 3}]),
    ("exit-not-the-stops-code", ("terminate-job",), [{**_KILL, "mechanism": "terminate-job", "code": 9, "tree": True},
                                                     _EXIT1]),
])
def test_r3_03_an_explained_stop_binds_one_successful_action_to_the_owned_process_and_its_exact_outcome(tmp_path, case,
                                                                                                          stops, middle):
    """R3-03: a stop explains a missing end record only when ONE successful action, recorded by the reserving parent for this
    launch's own process (pid and creation time), precedes that parent's observation of exactly the code it leaves."""
    if case == "reused-pid-creation-time":
        ledger = _killed_child(tmp_path, stops=stops, parent_middle=middle)
        rows = [json.loads(line) for line in (ledger / f"p{OWNER}.jsonl").read_text().splitlines()]
        for row in rows:
            if row["kind"] == "spawned":
                row["created"] = 5  # the action reached a process created at 7: another process now holding pid 200
        _write(ledger, OWNER, rows)
    else:
        ledger = _killed_child(tmp_path, stops=stops, parent_middle=middle)
    verdict = _judge(ledger)
    assert verdict["status"] == "FAIL" and LAUNCH not in verdict.get("explained_stops", []), verdict


@pytest.mark.parametrize("mechanism, code, exit_status", [("close-job", None, 0), ("terminate-job", 9, 9),
                                                          ("taskkill", 1, 1), ("terminate-process", 1, 1)])
def test_r3_03_each_stop_mechanism_explains_exactly_the_outcome_it_leaves(tmp_path, mechanism, code, exit_status):
    """The positive side: a kill-on-close Job's close ends its members with 0 (measured), TerminateJobObject with its code,
    taskkill /F and Popen.kill with 1."""
    middle = [{**_KILL, "mechanism": mechanism, "code": code, "tree": mechanism != "terminate-process"},
              {**_EXIT1, "exit": exit_status}]
    verdict = _judge(_killed_child(tmp_path, stops=(mechanism,), parent_middle=middle))
    assert verdict["status"] == "PASS" and verdict["explained_stops"] == [LAUNCH], verdict["problems"]


def _gone_row(position_after_stop: bool):
    return {"kind": "observed", "launch": INNER, "exit": None, "how": "gone", "pid": 300}


@pytest.mark.parametrize("case", ["unrelated-tree-flag", "descendant-gone-before-the-stop"])
def test_r3_03_a_descendant_is_accounted_only_through_the_one_proved_tree_stop_and_after_it(tmp_path, case):
    """R3-03: the explaining stop's own tree flag (never another record's), and the descendant's disappearance observed by
    that stop's writer after it."""
    if case == "unrelated-tree-flag":
        # A successful tree stop the reservation never expected (another record), then the single-process kill that is
        # the one expected, explaining action: R2 took the tree flag from the first and the descendant as explained.
        middle = [{**_KILL, "mechanism": "terminate-job", "code": 1, "tree": True}, _KILL, _EXIT1]
        stops = ("terminate-process",)
    else:
        middle = [_gone_row(False), {**_KILL, "mechanism": "terminate-job", "code": 1, "tree": True}, _EXIT1]
        stops = ("terminate-job",)
    ledger = _killed_child(tmp_path, stops=stops, parent_middle=middle, grandchild="kept")
    if case == "unrelated-tree-flag":
        with open(ledger / f"p{OWNER}.jsonl", "r+", encoding="utf-8") as handle:
            lines = handle.read().splitlines(keepends=True)
            handle.seek(0)
            handle.write("".join(lines[:-1] + [json.dumps(_gone_row(True)) + "\n", lines[-1]]))
    verdict = _judge(ledger)
    assert verdict["status"] == "FAIL" and any("descendant" in problem or INNER in problem
                                               for problem in verdict["problems"]), verdict["problems"]


def test_r3_03_the_tree_stop_that_explains_the_parent_accounts_for_a_descendant_gone_after_it(tmp_path):
    middle = [{**_KILL, "mechanism": "terminate-job", "code": 1, "tree": True}, _EXIT1, _gone_row(True)]
    verdict = _judge(_killed_child(tmp_path, stops=("terminate-job",), parent_middle=middle, grandchild="kept"))
    assert verdict["status"] == "PASS", verdict["problems"]


def test_r3_03_a_crash_expectation_reaches_only_the_thread_that_opened_it_and_the_threads_it_starts():
    """R3-03: a test's lifecycle marker no longer stamps every launch prepared anywhere in the process while it is open."""
    import threading

    decision = effects.LaunchDecision(effects.BOOTSTRAP, "x", expect="routine-child")
    seen: dict[str, object] = {}
    ready, go, done = threading.Event(), threading.Event(), threading.Event()

    def unrelated():
        ready.set()
        go.wait(30)
        seen["unrelated"] = effects._lifecycle_now(decision)
        done.set()

    bystander = threading.Thread(target=unrelated)
    bystander.start()  # already running before the expectation opens: an unrelated concurrent launcher
    ready.wait(30)
    with effects.expected_termination("native-crash", codes=(3,)):
        seen["opener"] = effects._lifecycle_now(decision)
        worker = threading.Thread(target=lambda: seen.__setitem__("worker", effects._lifecycle_now(decision)))
        worker.start()
        worker.join(30)
        go.set()
        done.wait(30)
    bystander.join(30)
    seen["after"] = effects._lifecycle_now(decision)
    assert seen["opener"] == {"stops": ["native-crash"], "codes": [3]} and seen["worker"] == seen["opener"]
    assert seen["unrelated"] is None and seen["after"] is None, seen


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskkill")
def test_r3_03_live_a_taskkill_stop_is_recorded_from_its_actual_result_before_the_end_it_explains():
    """R3-03: no taskkill stop is recorded before the tool ran; once it succeeded, its stop precedes the observed exit and
    explains it."""
    ledger = os.environ[effects.LEDGER_ENV]
    with effects.expected_termination("taskkill"):
        child = subprocess.Popen([sys.executable, "-c", EFFECT_CAPABLE_SLEEPER])
        launch = child._act_launch
        try:
            _wait_initialized(launch, ledger)
            killer = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"), "/PID",
                      str(child.pid), "/T", "/F"]
            done = subprocess.run(killer, capture_output=True, text=True, timeout=60)
        finally:
            child.wait(timeout=60)
    assert done.returncode == 0, done.stderr
    verdict = effects.read_ledger(ledger, open_roles=SESSION_ROLES)
    assert verdict["launches"][launch]["state"] == "explained-stop", [p for p in verdict["problems"] if launch in p]
    rows = [json.loads(line) for path in Path(ledger).glob("p*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]
    mine = [row for row in rows if row.get("launch") == launch and row["kind"] in ("stop", "observed")]
    assert [row["kind"] for row in mine][:2] == ["stop", "observed"] and mine[0]["mechanism"] == "taskkill"         and mine[0]["ok"] is True and mine[0]["created"] is not None, mine


# --- R3-01: startup before the envelope, the inert profile's import path, and the admitted invocation ---------------------
def test_r3_01_a_nested_runner_never_starts_with_startup_code_ahead_of_its_bootstrap(tmp_path):
    """Independent reproduction: a replacement PYTHONPATH holding a sitecustomize ran before routine_effects existed and the
    inner session still passed. The same startup check now judges a nested runner as every Python child."""
    startup = tmp_path / "startup"
    startup.mkdir()
    (startup / "sitecustomize.py").write_text("print('BEFORE_ENVELOPE')\n", encoding="utf-8")
    private = effects.new_ledger(tmp_path / "private")
    args = [sys.executable, "-B", str(TESTS / "routine_pytest.py"), str(tmp_path / "test_ok.py"), "-q"]
    env = {**os.environ, effects.LEDGER_ENV: str(private), "PYTHONPATH": str(startup)}
    with effects.expected_refusals("real-app-launch", accounting="report"):
        decision = effects.decide_launch(args, env=env)
    assert decision.refused and "sitecustomize" in decision.reason, decision
    benign = tmp_path / "benign"
    benign.mkdir()
    with effects.expected_refusals(accounting="report"):
        decision = effects.decide_launch(args, env={**env, "PYTHONPATH": str(benign)})
    assert decision.profile == "nested-verification", decision  # a benign PYTHONPATH still runs, moved past the bootstrap


def test_r3_01_a_benign_nested_runner_restores_its_pythonpath_only_after_its_envelope(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "helper_mod.py").write_text("VALUE = 7\n", encoding="utf-8")
    (suite / "test_uses_path.py").write_text(textwrap.dedent("""
        import os, sys
        def test_path_is_restored_after_the_envelope():
            import helper_mod
            assert helper_mod.VALUE == 7 and "routine_effects" in sys.modules
            assert os.environ.get("ACT_ROUTINE_PYTHONPATH") is None
    """), encoding="utf-8")
    private = effects.new_ledger(tmp_path / "private")
    command = [sys.executable, "-B", str(TESTS / "routine_pytest.py"), str(suite / "test_uses_path.py"), "-q",
               "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'inner'}"]
    with effects.expected_refusals(accounting="report") as scope:
        done = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=300,
                              env={**os.environ, effects.LEDGER_ENV: str(private), "PYTHONPATH": str(suite)})
    assert done.returncode == 0 and "1 passed" in done.stdout, (done.stdout[-1500:], done.stderr[-1500:])
    assert scope.ledgers[str(private)]["status"] == "PASS", scope.ledgers[str(private)]["problems"]


def test_r3_01_an_inert_profile_never_imports_from_a_shadowing_working_directory(tmp_path):
    """Independent reproduction: ``import signal`` under the unchanged inert profile ran a disposable cwd's signal.py. The
    profile now needs a trusted import path: -I/-P, or no shadowing module where -c looks first."""
    code = "import signal, time; time.sleep(0)"
    clean = tmp_path / "clean"
    clean.mkdir()
    assert effects.decide_launch([sys.executable, "-c", code], cwd=clean).profile == "inert-python-stand-in"
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "signal.py").write_text("print('INERT_SIGNAL_IMPORT')\n", encoding="utf-8")
    decision = effects.decide_launch([sys.executable, "-c", code], cwd=shadow)
    assert decision.profile != "inert-python-stand-in" and decision.outcome == effects.BOOTSTRAP, decision
    assert effects.decide_launch([sys.executable, "-I", "-c", code], cwd=shadow).profile == "inert-python-stand-in"
    assert effects.decide_launch([sys.executable, "-c", "import time; time.sleep(0)"], cwd=shadow).profile == \
        "inert-python-stand-in"  # time is built in: nothing on the path can stand for it


def test_r3_01_an_inert_fast_cancellation_stand_in_keeps_its_unchanged_behaviour(tmp_path):
    """D-R2-8 retained: the inert sleeper runs unchanged (no bootstrap, no participant) and is stopped and observed."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
    try:
        assert effects._launches[child._act_launch].decision.profile == "inert-python-stand-in"
    finally:
        child.kill()
        child.wait(30)


@pytest.mark.parametrize("change", ["executable", "cwd", "environment-value", "arguments"])
def test_r3_01_the_admitted_process_creation_is_the_prepared_invocation_in_every_fact(tmp_path, change):
    """R3-01: the final admission compares the program the platform starts, the complete arguments, the working directory
    and the effective environment's values with what was prepared -- not environment object identity and an argument tail."""
    env = dict(os.environ)
    prepared = effects._Prepared(effects.decide_launch([sys.executable, "-c", "import os"], cwd=tmp_path, env=env),
                                 "x", [sys.executable, "-c", "import os"], None, env, False)
    prepared.extra["env_view"] = effects._env_view(env)
    prepared.extra["original"] = (prepared.args, tmp_path, env)
    assert effects._binding_problem(prepared, None, prepared.args, tmp_path, env) is None
    other = tmp_path / "other"
    other.mkdir()
    args, cwd, executable = list(prepared.args), tmp_path, None
    if change == "executable":
        executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe") \
            if os.name == "nt" else "/bin/sh"
    elif change == "cwd":
        cwd = other
    elif change == "environment-value":
        env["ACT_R3_SENTINEL"] = "changed after preparation"
    else:
        args = [*args[:-1], "import sys"]
    assert effects._binding_problem(prepared, executable, args, cwd, env) is not None


# --- R3-02: the recipe's actual destinations and identifiers ---------------------------------------------------------------
@pytest.mark.parametrize("args, ok", [
    (["--report", "{tree}/r.json", "--evidence", "{tree}/ev", "--token", "t", "--only", "journey-1"], True),
    (["--report", "{outside}/r.json", "--evidence", "{tree}/ev", "--only", "journey-1"], False),
    (["--report", "{tree}/r.json", "--evidence", "{tree}/ev", "--only", "../unexpected"], False),
    (["--report", "{tree}/r.json", "--evidence", "{tree}/ev", "--only", "a/b"], False),
    (["--report", "{tree}/../r.json", "--evidence", "{tree}/ev"], False),
    (["--rep", "{tree}/r.json"], False),  # an argparse abbreviation the recipe would accept: outside the exact contract
    (["--report", "{tree}/r.json", "--report", "{outside}/r.json"], False),
    (["--report", "{tree}/linked/r.json"], False),
])
def test_r3_02_a_recipe_writes_only_inside_its_fixture_tree_and_names_only_plain_identifiers(tmp_path, args, ok):
    tree, outside = tmp_path / "tree", tmp_path / "outside"
    tree.mkdir()
    outside.mkdir()
    if any("linked" in arg for arg in args):
        if os.name != "nt":
            os.symlink(outside, tree / "linked")
        else:
            subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"), "/c",
                            "mklink", "/J", str(tree / "linked"), str(outside)], check=True, capture_output=True)
    filled = [arg.format(tree=tree, outside=outside) for arg in args]
    problem = effects.context.stand_in_arguments_problem("scripted-acceptance-runner", filled, tree)
    assert (problem is None) == ok, problem


def test_r3_02_a_gate_operation_admits_a_stand_in_only_for_the_exact_command_it_supervises(tmp_path, monkeypatch):
    """The operation check is bound to the actual supervised argv: without it, or with a different program or a different
    interpreter, a declared stand-in is never admitted there."""
    calls = []
    monkeypatch.setattr(effects.context, "synthetic_stand_in", lambda tree, rel, environ=None, args=None:
                        calls.append(args) or args == ["--report", "r"])
    monkeypatch.setattr(effects.context, "record_refusal", lambda *a, **k: True)
    target = tmp_path / effects.context.GATE / "acceptance_runner.py"
    good = [sys.executable, "-I", "-B", "-u", str(target), "--report", "r"]
    effects.context.check_operation("native-desktop", "x", root=tmp_path, stand_in=effects.context.GATE +
                                    "acceptance_runner.py", argv=good)
    for bad in (None, [*good[:-1], "elsewhere"], ["python.exe", *good[1:]],
                [sys.executable, "-I", str(tmp_path / "other.py"), "--report", "r"]):
        with pytest.raises(PermissionError):
            effects.context.check_operation("native-desktop", "x", root=tmp_path, stand_in=effects.context.GATE +
                                            "acceptance_runner.py", argv=bad)


# --- R3-05: the exact bounded Qwen3 selfcheck, with simulated installed-interpreter resolution ---------------------------
def _qwen3(tmp_path, monkeypatch, **changes):
    fixtures = effects.fixtures()
    exe = str(fixtures.QWEN3_INTERPRETER)
    monkeypatch.setattr(effects, "_search", lambda text, cwd=None, env=None: exe)  # simulated installed interpreter
    effects.own_disposable(tmp_path)
    cache = {name: str(tmp_path / name.lower()) for name in fixtures.QWEN3_WRITABLE}
    env = {**os.environ, **cache, "HF_HUB_OFFLINE": "1", **changes.pop("env", {})}
    argv = [exe, "-I", "-B", str(fixtures.QWEN3_TOOLS), "selfcheck", str(fixtures.QWEN3_MODELS / "inert-base")]
    for index, value in changes.pop("argv", {}).items():
        argv[index] = value
    return effects.decide_launch(argv, cwd=tmp_path, env=env)


def test_r3_05_the_exact_read_only_qwen3_selfcheck_runs_under_its_reviewed_profile(tmp_path, monkeypatch):
    """R3-05 (independent reproduction: R1 allowed this exact selfcheck, R2 refused it as real-engine, hidden by the
    environment skip). The launch decision alone is proved here, with the installed interpreter simulated; the installed
    library's own proof stays an environment obligation."""
    decision = _qwen3(tmp_path, monkeypatch)
    assert decision.outcome == effects.PROFILE and decision.profile == "qwen3-calm-selfcheck", decision


@pytest.mark.parametrize("change", [
    {"argv": {4: "generate"}}, {"argv": {1: "-B"}}, {"argv": {5: "C:/elsewhere/model"}},
    {"argv": {3: "C:/copy/qwen3_calm_venv_tools.py"}}, {"env": {"HF_HUB_OFFLINE": "0"}},
    {"env": {"HF_HOME": "C:/Users/someone/.cache/huggingface"}},
])
def test_r3_05_every_other_engine_interpreter_launch_stays_refused(tmp_path, monkeypatch, change):
    decision = _qwen3(tmp_path, monkeypatch, **change)
    assert decision.refused and decision.effect == "real-engine", decision
