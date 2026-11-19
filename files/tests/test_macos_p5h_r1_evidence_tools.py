"""v0.8.x P5-H-R1: the two MEDIUM findings of the independent Codex review of P5-H (``7b1b309``), both in evidence tools.

* MEDIUM 1. ``files/dev-tools/macos_p2_qualify.py`` returned 0 on the Downloads guard alone, so a failed chapter or a DIFFERENT
  E-B2 comparison exited 0. The exit status is now the command's own outcome (4 when it failed), with the Downloads guard (3)
  kept distinct and the JSON record unchanged apart from its ``problems`` and ``outcome``. Stubbed runs, every mapping.
* MEDIUM 2. ``files/dev-tools/macos_p4b_omnivoice_qualify.py``'s KX-1 drill sent SIGKILL to the owner with no check that the
  worker it was timing was still live, and with a raw ``os.kill`` on an owner the polling may already have reaped. The kill
  boundary now requires the same owner and the same live worker in its group (kernel start times), signals only through
  ``child_ownership.signal_if_same``, and fails on surviving processes of the drill. Real processes stand in for the owner and
  worker; the negative control is a worker that exits before the signal.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "files" / "dev-tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"p5h_r1_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- MEDIUM 1


@pytest.fixture()
def p2(monkeypatch, tmp_path):
    module = _load("macos_p2_qualify")
    monkeypatch.setattr(module, "downloads_fingerprint", lambda: {"exists": True, "entries": 0, "digest": "same"})
    return module


def _main(p2, monkeypatch, tmp_path, *argv) -> tuple[int, dict]:
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["macos_p2_qualify.py", *argv, "--out", str(out)])
    status = p2.main()
    record = json.loads((out / f"{argv[0]}.json").read_text(encoding="utf-8"))
    return status, record


def _chapter_row(tmp_path, *, state="succeeded", finished=True, output=True, problems=()):
    produced = tmp_path / "chapter.mp3"
    if output:
        produced.write_bytes(b"audio")
    return {"row": {"voice": "af_heart", "text": "D", "finished": finished, "state": state, "output": str(produced),
                    "screen": {"problems": list(problems)}}}


@pytest.mark.parametrize("case,expected", [
    (dict(), 0),
    (dict(state="failed"), 4),
    (dict(state="cancelled"), 4),
    (dict(finished=False), 4),
    (dict(output=False), 4),
    (dict(problems=["clipping"]), 4),
])
def test_the_chapter_command_exits_on_its_own_result(p2, monkeypatch, tmp_path, case, expected):
    monkeypatch.setattr(p2, "cmd_chapter", lambda out, **kw: _chapter_row(tmp_path, **case))
    status, record = _main(p2, monkeypatch, tmp_path, "chapter")
    assert status == expected
    assert record["run"]["outcome"] == ("PASS" if expected == 0 else "FAIL")
    assert bool(record["run"]["problems"]) == bool(expected)
    assert record["row"]["state"] == case.get("state", "succeeded"), "the record itself is kept as it was"


@pytest.mark.parametrize("verdict,expected", [("IDENTICAL", 0), ("DIFFERENT", 4), (None, 4)])
def test_the_eb2_comparison_exits_on_its_verdict(p2, monkeypatch, tmp_path, verdict, expected):
    monkeypatch.setattr(p2, "cmd_eb2_compare", lambda first, second: {"texts": {}, "verdict": verdict})
    status, record = _main(p2, monkeypatch, tmp_path, "eb2-compare", "--first", "a.json", "--second", "b.json")
    assert status == expected and record["verdict"] == verdict


def test_the_downloads_guard_stays_distinct_and_wins(p2, monkeypatch, tmp_path):
    readings = iter([{"digest": "before"}, {"digest": "after"}])
    monkeypatch.setattr(p2, "downloads_fingerprint", lambda: next(readings))
    monkeypatch.setattr(p2, "cmd_chapter", lambda out, **kw: _chapter_row(tmp_path))
    status, record = _main(p2, monkeypatch, tmp_path, "chapter")
    assert status == 3 and record["run"]["downloads_unchanged"] is False and record["run"]["outcome"] == "PASS"


def test_voices_and_the_edge_load_fail_on_any_failed_file(p2, monkeypatch, tmp_path):
    good = _chapter_row(tmp_path)["row"]
    assert p2.command_problems("voices", {"rows": [good, good]}) == []
    assert p2.command_problems("voices", {"rows": [good, {**good, "state": "failed"}]})
    assert p2.command_problems("voices", {"rows": []}), "nothing run is not a pass"
    load = {"E-A3-4": {"finished": True, "state": "succeeded", "published": 4, "files": 4, "screens": {"a.mp3": {"problems": []}}}}
    assert p2.command_problems("edge-load", load) == []
    assert p2.command_problems("edge-load", {"E-A3-4": {**load["E-A3-4"], "published": 3}})
    assert p2.command_problems("edge-load", {"E-A3-4": {**load["E-A3-4"], "screens": {"a.mp3": {"problems": ["silence"]}}}})


def test_eb1_fails_on_its_own_checks(p2):
    good = {"imports": {"returncode": 0}, "espeak_fallback": {"all_spoken": True}, "worker": {"finite": True}}
    assert p2.command_problems("eb1", good) == []
    assert p2.command_problems("eb1", {**good, "imports": {"returncode": 1}})
    assert p2.command_problems("eb1", {**good, "espeak_fallback": {"all_spoken": False}})
    assert p2.command_problems("eb1", {**good, "worker": {"finite": False}})


# --------------------------------------------------------------------------- MEDIUM 2


OWNER = r"""
import json, os, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from shared import child_ownership
worker = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read(); " + sys.argv[3]],
                          stdin=subprocess.PIPE, start_new_session=True)
report = {"worker_pid": worker.pid, "worker_pgid": os.getpgid(worker.pid),
          "worker_start": child_ownership.process_start_time(worker.pid)}
open(sys.argv[2] + ".tmp", "w").write(json.dumps(report)); os.replace(sys.argv[2] + ".tmp", sys.argv[2])
worker.stdin.close()  # the worker now does its part: exits at once, or lives on
if sys.argv[4] == "worker-gone":
    worker.wait()
    open(sys.argv[2] + ".gone", "w").write("1")
time.sleep(60)
"""


@pytest.fixture()
def kx(tmp_path):
    if sys.platform != "darwin":
        pytest.skip("the KX-1 drill and its kernel start times are macOS's")
    module = _load("macos_p4b_omnivoice_qualify")
    started = []

    def start(mode: str, worker_code: str):
        report = tmp_path / f"{mode}.json"
        owner = subprocess.Popen([sys.executable, "-I", "-B", "-c", OWNER, str(REPO / "scripts"), str(report), worker_code,
                                  mode], start_new_session=True)
        started.append(owner)
        deadline = time.monotonic() + 20
        while not report.exists() or (mode == "worker-gone" and not Path(f"{report}.gone").exists()):
            assert time.monotonic() < deadline and owner.poll() is None, "the stand-in owner did not report"
            time.sleep(0.02)
        data = json.loads(report.read_text())
        started.append(data)
        return owner, module.child_ownership.process_start_time(owner.pid), data

    yield module, start
    for item in started:
        if isinstance(item, dict):
            try:
                os.killpg(item["worker_pgid"], signal.SIGKILL)
            except OSError:
                pass
        else:
            item.kill()
            item.wait(10)


def test_a_live_worker_passes_the_kill_boundary_and_the_signal_goes_through_the_identity_check(kx):
    module, start = kx
    owner, birth, worker = start("live", "import time; time.sleep(60)")
    assert module.kill_boundary(owner, birth, worker) == []
    assert module.child_ownership.signal_if_same(owner.pid, birth, signal.SIGKILL)
    owner.wait(10)
    assert module.attributable([f"{worker['worker_pid']} {worker['worker_pgid']} python worker",
                                f"{owner.pid} {owner.pid} python owner", "1 1 launchd"], worker, owner.pid) == [
        f"{worker['worker_pid']} {worker['worker_pgid']} python worker", f"{owner.pid} {owner.pid} python owner"]


def test_negative_control_a_worker_gone_before_the_signal_is_refused(kx):
    module, start = kx
    owner, birth, worker = start("worker-gone", "pass")
    refused = module.kill_boundary(owner, birth, worker)
    assert refused and "worker" in refused[0], refused
    assert owner.poll() is None, "the owner was not signalled: the drill refuses before it"


def test_negative_control_an_owner_already_reaped_is_refused(kx):
    module, start = kx
    owner, birth, worker = start("live", "import time; time.sleep(60)")
    owner.kill()
    owner.wait(10)
    refused = module.kill_boundary(owner, birth, worker)
    assert any("owner" in reason for reason in refused), refused
    assert not module.child_ownership.signal_if_same(owner.pid, None, signal.SIGKILL), "no identity: no signal"


# --------------------------------------------------------------------------- re-review: the real oracles, end to end


def _capture(rows: dict) -> dict:
    return {"packages": {"kokoro": {"version": "0.9.4"}}, "texts": rows}


def _row(prepared: str = "p", phonemes: str = "ph") -> dict:
    return {"prepared_sha256": prepared, "phonemes_sha256": phonemes,
            "chunks": [{"segments": [{"graphemes": "g", "phonemes": phonemes}]}]}


ALL_ROWS = [f"{n}-{l}" for n in ("A", "B", "C") for l in ("a", "b")]


@pytest.mark.parametrize("first,second,expected", [
    ({k: _row() for k in ALL_ROWS}, {k: _row() for k in ALL_ROWS}, "IDENTICAL"),
    ({}, {}, "DIFFERENT"),                                                          # two empty captures
    ({k: _row() for k in ALL_ROWS[:-1]}, {k: _row() for k in ALL_ROWS[:-1]}, "DIFFERENT"),  # a row missing on both
    ({k: _row() for k in ALL_ROWS}, {**{k: _row() for k in ALL_ROWS}, "C-b": _row(prepared="other")}, "DIFFERENT"),
    ({k: _row() for k in ALL_ROWS}, {**{k: _row() for k in ALL_ROWS}, "A-a": _row(phonemes="other")}, "DIFFERENT"),
], ids=["identical", "empty", "missing-row", "other-input-same-phonemes", "other-phonemes"])
def test_the_real_eb2_comparator_passes_only_a_complete_identical_comparison(p2, monkeypatch, tmp_path, first, second,
                                                                            expected):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(_capture(first)))
    b.write_text(json.dumps(_capture(second)))
    status, record = _main(p2, monkeypatch, tmp_path, "eb2-compare", "--first", str(a), "--second", str(b))
    assert record["verdict"] == expected and status == (0 if expected == "IDENTICAL" else 4)


# Ends once its owner has died (reparented to launchd), whenever it began to look: it cannot miss an owner that died first.
FOLLOWER = "import os, time\nwhile os.getppid() != 1:\n    time.sleep(0.05)\n"


def test_the_kx1_drill_passes_a_worker_live_at_the_signal_that_retires_with_its_owner(kx, tmp_path):
    module, start = kx
    owner, birth, worker = start("live", FOLLOWER)  # a worker that ends when its owner does, as a guarded one must
    status, result = module.drill(owner, birth, worker, tmp_path / "never.mp3")
    assert status == 0, json.dumps(result, default=str)
    assert result["live_at_kill"] and result["owner_returncode"] == -signal.SIGKILL and result["survivors"] == []


def test_negative_control_the_kx1_drill_fails_on_a_worker_gone_before_the_signal(kx, tmp_path):
    module, start = kx
    owner, birth, worker = start("worker-gone", "pass")
    status, result = module.drill(owner, birth, worker, tmp_path / "never.mp3")
    assert status == 1 and not result["live_at_kill"] and "worker" in result["refused"][0], result


def test_negative_control_the_kx1_drill_fails_on_a_worker_that_ends_between_the_check_and_the_signal(kx, tmp_path,
                                                                                                    monkeypatch):
    """The reviewer's case: the worker retired after the liveness check and before the owner's signal; ``live_at_kill``
    was recorded true and the drill exited 0. Now the worker must still be present just after the signal."""
    module, start = kx
    owner, birth, worker = start("live", FOLLOWER)
    real = module.child_ownership.signal_if_same

    ended = []

    def worker_ends_first(pid, start_time, sig, **kwargs):
        if pid == owner.pid and not ended:  # the drill's own signal only, not its cleanup's
            ended.append(1)
            os.killpg(worker["worker_pgid"], signal.SIGKILL)
            deadline = time.monotonic() + 5
            while module.worker_present(worker) and time.monotonic() < deadline:
                time.sleep(0.01)
        return real(pid, start_time, sig, **kwargs)

    monkeypatch.setattr(module.child_ownership, "signal_if_same", worker_ends_first)
    assert module.kill_boundary(owner, birth, worker) == [], "it passed the check before the signal"
    status, result = module.drill(owner, birth, worker, tmp_path / "never.mp3")
    assert status == 1 and not result["live_at_kill"] and "just after the signal" in result["refused"][0], result
