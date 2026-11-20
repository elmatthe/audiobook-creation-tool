"""v0.8.x P5-I-R3, remediation 7: the two gaps the (content-filtered, verdict-less) review of 8ea3de5 named.

1. A child announced right after fork has not run ``setsid()`` yet: a group signal by its pid then finds no group
   (``ESRCH``) and signalled nothing -- in the owner (``signal_if_same(group=True)``, used by the orderly end and a
   run's settlement for a stalled start) and in the guardian. The process itself is now signalled, identity-checked.
2. A contained stop of a cancelled run's child began a fresh SIGTERM grace from when the stop was asked for, so a
   Cancel noticed late ran past C2's 4 s from the click. The grace is now cut to what C2 leaves.
macOS only.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from shared import child_guardian as cg
from shared import child_ownership as co
from shared import subprocess_utils as sp
from shared.job_control import JobController

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")


def until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    return predicate()


def _not_a_group_leader():
    """A child still in this process's group: ``killpg`` by its pid finds no such group, as before its setsid()."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    assert until(lambda: co.process_start_time(child.pid) is not None)
    return child, co.process_start_time(child.pid)


def test_a_group_signal_to_a_child_not_yet_leading_its_group_reaches_the_child():
    child, start = _not_a_group_leader()
    try:
        assert co.signal_if_same(child.pid, start, signal.SIGKILL, group=True) is True
        assert child.wait(3) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(3)


def test_the_guardian_ends_a_registered_child_not_yet_leading_its_group():
    child, start = _not_a_group_leader()
    try:
        cg._end_leaders({child.pid: start})
        assert child.wait(3) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(3)


def test_a_group_signal_never_reaches_a_process_that_is_no_longer_the_recorded_one():
    child, start = _not_a_group_leader()
    try:
        assert co.signal_if_same(child.pid, (start[0] - 100, start[1]), signal.SIGKILL, group=True) is False
        time.sleep(0.2)
        assert child.poll() is None
    finally:
        child.kill()
        child.wait(3)


def test_a_late_noticed_cancel_never_starts_a_grace_past_c2(tmp_path):
    program = tmp_path / "ffmpeg"
    program.write_text("#!/bin/sh\ntrap '' TERM\nexec /bin/sleep 30\n")  # ignores SIGTERM: only the SIGKILL ends it
    program.chmod(0o700)
    clicked = time.monotonic() - 3.0  # the click was 3 s ago: C2 leaves 1 s
    ctl = JobController("late", cancel_clock=lambda: clicked)
    ctl.start()
    owner = co.Owner()
    try:
        with patch.object(sp, "_owner", owner):
            proc = owner.popen_external([str(program)], owner_run=ctl.cancel_check)
            ctl.request_cancel()
            began = time.monotonic()
            reaped = sp.stop_child(proc, 5.0)  # a caller's own 5 s grace
            took = time.monotonic() - began
        assert reaped and proc.returncode == -signal.SIGKILL
        assert time.monotonic() - clicked < sp.CANCEL_STEP_S, f"stopped {time.monotonic() - clicked:.3f}s after the click"
        assert took < 1.5, f"{took:.3f}s"
    finally:
        owner.shutdown()


def test_a_stop_without_a_cancel_keeps_its_callers_grace(tmp_path):
    program = tmp_path / "ffmpeg"
    program.write_text("#!/bin/sh\ntrap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n")
    program.chmod(0o700)
    ctl = JobController("plain", cancel_clock=time.monotonic)
    ctl.start()
    owner = co.Owner()
    try:
        with patch.object(sp, "_owner", owner):
            proc = owner.popen_external([str(program)], owner_run=ctl.cancel_check)
            assert sp._grace_inside_c2(owner, proc, 5.0) == 5.0
            assert sp.stop_child(proc, 5.0)
        assert proc.returncode == 0, "it got its SIGTERM and its grace"
    finally:
        owner.shutdown()
