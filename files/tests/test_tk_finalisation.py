"""PRE-PLAN-6 Phase 6, row 18 (L2) — Tk objects are finalised on the main thread.

**The defect.** ``tk_gate._reset_root`` returns the shared interpreter to a
pristine state between modules: it cancels ``after`` callbacks, unbinds events
and destroys every child widget. What it never touched was ``tkinter.Variable``.
A variable is not owned by the widget that used it, so destroying a frame leaves
its variables alive, each still holding a reference to the live interpreter and
each carrying a ``__del__`` that calls into Tcl.

Measured at ``b59f562`` over three UI modules, **90 variables were still armed**
at the end of the run. Nothing decides when their finalisers execute. Reference
counting would run them on whichever thread dropped the last reference — the
main one, in a test — but these variables sit inside reference cycles, so it is
the *cyclic* collector that finalises them, on whichever thread happens to
allocate enough to trigger a collection. That can be a worker thread, and a
worker calling into Tcl is an ignored ``RuntimeError`` here and a stall on the
interpreter lock on a Tk built with threading. The suite has already paid for
it: a bounded five-second thread-start wait in ``test_job_ui.py`` timed out when
an unrelated change shifted *when* collection happened to run.

**Phase 1 avoided provoking it. That is not the fix.** Reducing allocation churn
makes a bad landing less likely; it does not make it impossible. The fix is
:func:`tk_gate.finalise_tk_objects`: at every module boundary, on the main
thread, do what each finaliser would have done and then clear the attribute that
arms it — ``Variable._tk``, ``Image.name``. ``Variable.__del__`` opens with
``if self._tk is None: return``, so afterwards there is no longer a finaliser
that *can* reach Tcl, whichever thread later collects the cycle.

Everything here is bounded. The historical hazard is reproduced in a child
process with a hard timeout, so a regression in the fix cannot strand the run.
"""

from __future__ import annotations

import gc
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
#: Long enough that a slow machine is not called a stall, short enough that a
#: real stall cannot hold the phase. Never raised to make a test pass.
BOUND = 15.0


@pytest.fixture
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def leftover_variable(root):
    """A Tk variable trapped in a cycle, exactly as a UI test leaves one.

    The cycle is the point. Without it the variable dies by refcount on this
    thread the moment the last name goes out of scope, which is the safe case
    and not the one that ever hurt anybody.
    """
    variable = tk.StringVar(master=root, value="x")

    class Holder:
        pass

    first, second = Holder(), Holder()
    first.other, second.other = second, first
    first.variable = variable
    return variable


# --------------------------------------------------------------------------- #
# A. The boundary itself
# --------------------------------------------------------------------------- #
def test_the_boundary_refuses_to_run_off_the_main_thread():
    """It is a main-thread guarantee, so it says so rather than hoping.

    A boundary that quietly did its work on a worker would be performing the
    exact Tcl call from the exact wrong thread that it exists to prevent.
    """
    outcome: list = []

    def worker():
        try:
            tk_gate.finalise_tk_objects(tk)
            outcome.append("ran")
        except RuntimeError as exc:
            outcome.append(f"refused: {exc}")

    thread = threading.Thread(target=worker, name="not-main")
    thread.start()
    thread.join(BOUND)

    assert not thread.is_alive(), "the guard itself stalled"
    assert outcome and outcome[0].startswith("refused"), outcome
    assert "main thread" in outcome[0]


def test_a_leftover_variable_is_finalised_and_disarmed(tk_root):
    variable = leftover_variable(tk_root)
    assert variable._tk is not None
    assert variable in tk_gate.armed_tk_objects(tk)

    disarmed = tk_gate.finalise_tk_objects(tk)

    assert disarmed >= 1
    assert variable._tk is None, "the variable can still reach the interpreter"
    assert variable._tclCommands is None
    assert variable not in tk_gate.armed_tk_objects(tk)


def test_the_tcl_variable_is_actually_unset_not_merely_forgotten(tk_root):
    """Disarming must not leak the Tcl-side name; it finalises, then severs."""
    variable = leftover_variable(tk_root)
    name = variable._name
    assert tk_root.tk.getboolean(tk_root.tk.call("info", "exists", name))

    tk_gate.finalise_tk_objects(tk)

    assert not tk_root.tk.getboolean(tk_root.tk.call("info", "exists", name))


def test_a_leftover_image_is_disarmed_too(tk_root):
    """``Image.__del__`` calls into Tcl for the same reason and is treated alike."""
    image = tk.PhotoImage(master=tk_root, width=1, height=1)
    assert image.name

    tk_gate.finalise_tk_objects(tk)

    assert not image.name
    assert image not in tk_gate.armed_tk_objects(tk)


# --------------------------------------------------------------------------- #
# B. The hazard itself — bounded
# --------------------------------------------------------------------------- #
def test_a_disarmed_finaliser_is_a_no_op_on_a_worker_thread(tk_root):
    """The guarantee, exercised where it matters: off the main thread.

    ``Variable.__del__`` opens with ``if self._tk is None: return``, so once the
    boundary has cleared that attribute the finaliser cannot reach Tcl at all.
    Run it deliberately on a worker — the thread that used to run it by accident
    — and it must complete immediately and silently.
    """
    variable = leftover_variable(tk_root)
    tk_gate.finalise_tk_objects(tk)
    assert variable._tk is None

    finished = threading.Event()
    failures: list = []

    def worker():
        try:
            variable.__del__()
        except BaseException as exc:            # noqa: BLE001 - this is the test
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            finished.set()

    thread = threading.Thread(target=worker, name="finaliser-worker", daemon=True)
    thread.start()

    assert finished.wait(BOUND), "a disarmed finaliser still blocked on Tcl"
    assert failures == [], failures


def test_cyclic_collection_on_a_worker_finds_nothing_armed(tk_root):
    """The actual failure shape, run deliberately instead of waited for.

    Build the cycles, cross the boundary, then force a cyclic collection **on a
    worker thread** — the thing that used to happen by accident at an unlucky
    moment. It has to complete well inside the bound.
    """
    for _ in range(25):
        leftover_variable(tk_root)
    tk_gate.finalise_tk_objects(tk)
    assert tk_gate.armed_tk_objects(tk) == []

    finished = threading.Event()
    failures: list = []

    def worker():
        try:
            gc.collect()
        except BaseException as exc:            # noqa: BLE001 - this is the test
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            finished.set()

    thread = threading.Thread(target=worker, name="gc-worker", daemon=True)
    thread.start()

    assert finished.wait(BOUND), "the worker stalled inside a Tk finaliser"
    assert failures == []


def test_the_module_boundary_leaves_nothing_armed():
    """End to end through the fixture every UI module actually uses."""
    generator = tk_gate.tk_root_session(tk)
    root = next(generator)
    for _ in range(5):
        leftover_variable(root)
    assert tk_gate.armed_tk_objects(tk), "the scenario did not arm anything"

    with pytest.raises(StopIteration):
        next(generator)                          # runs the fixture teardown

    assert tk_gate.armed_tk_objects(tk) == []


def test_the_reset_cancels_a_ttk_timer_whose_script_is_a_tcl_list(tk_root):
    """v0.6.3 Phase 10: the reported order-dependent failure, reproduced.

    ``test_job_ui`` followed by ``test_book_workspace_ui::
    test_no_scheduled_callback_is_left_behind`` failed because three
    ``ttk::progressbar::Autoincrement`` timers survived the module boundary.
    ``_reset_root`` cancelled through ``tkinter.Misc.after_cancel``, which
    reads the timer's script and calls ``deletecommand`` on it -- and for a
    ttk timer that script is a Tcl *list*, so ``deletecommand`` raises
    ``TypeError``, which ``after_cancel`` does not catch, so ``after cancel``
    never runs. The reset then swallowed the error and moved on with the
    timer still pending. The boundary must cancel where the timer lives.
    """
    from tkinter import ttk

    holder = ttk.Frame(tk_root)
    bar = ttk.Progressbar(holder, mode="indeterminate")
    bar.pack()
    bar.start(60)
    holder.destroy()
    pending = tk_root.tk.call("after", "info")
    assert pending, "the destroyed bar's animation timer is still scheduled"
    tk_gate._reset_root(tk_root)
    assert tk_root.tk.call("after", "info") == "", (
        "the boundary left a ttk timer pending for the next module to find")


# --------------------------------------------------------------------------- #
# B2. v0.6.3 Phase 10: the boundary is every *test*, not only every module
#
# The reported order-dependent failure had a second cause. ``test_job_ui``
# followed by ``test_suite_isolation`` stalled ``test_cancel_import_stops_the_
# scan_and_touches_no_job_controller`` for its whole five-second bound: the
# faulthandler dump showed the scan worker inside ``tkinter.Variable.__del__``
# -- a variable an *earlier test in the same module* had left in a cycle,
# finalised by the cyclic collector on the worker thread, calling into Tcl
# while the main thread sat in ``Event.wait``. The module boundary disarms
# nothing between two tests of one module, and which test the collector picks
# depends on allocation history -- which is why merely collecting another
# module changed the outcome.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def module_root():
    """A module-scoped root, as every real UI module holds one.

    This module's own ``tk_root`` is function-scoped, so its teardown already
    finalises after every test here; the pair below must run under the scope
    the UI modules actually use, where nothing between two tests of one
    module finalised anything before Phase 10.
    """
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture(scope="module")
def automatic_collection_paused():
    """Model the hazard's precondition: the cycle has not been collected yet.

    A small young cycle would otherwise be swept by the next automatic
    generation-0 collection between two tests, on the main thread, which is
    the harmless case. In the real failure the cycle had aged past that and
    was collected later, on a worker. Pausing automatic collection makes
    "not yet collected" a fact rather than a matter of allocation counts; the
    explicit ``gc.collect`` inside the boundary is unaffected by it.
    """
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def test_an_earlier_test_leaves_an_armed_variable_behind(
        module_root, automatic_collection_paused):
    """The first half of a two-test pair: leave exactly what a UI test leaves."""
    leftover_variable(module_root)
    assert tk_gate.armed_tk_objects(tk), "the cycle is armed and uncollected"


def test_the_next_test_in_the_module_starts_its_worker_with_nothing_armed(
        module_root, automatic_collection_paused):
    """The second half. Definition order is execution order within a module,
    so this runs immediately after the test above, with its leftover still
    armed; the boundary at ``Thread.start`` makes it inert before the worker
    exists, so no collection on that worker can ever reach Tcl."""
    assert tk_gate.armed_tk_objects(tk), "the earlier test's leftover is still armed"
    worker = threading.Thread(target=lambda: None, name="boundary-probe")
    worker.start()
    worker.join(BOUND)
    assert tk_gate.armed_tk_objects(tk) == [], (
        "an armed Tk variable survived into a test that started a worker")


def test_the_shared_root_is_not_destroyed_by_the_boundary(tk_root):
    """Deliberately narrow: one interpreter per process is a load-bearing rule.

    ``tk_gate`` creates a single root and reuses it because creating and
    destroying Tcl interpreters inside pytest fails on Windows. Finalising
    leftovers must not become root churn by the back door.
    """
    tk_gate.finalise_tk_objects(tk)

    assert tk_root.winfo_exists()
    assert tk_gate.shared_root(tk) is tk_root


# --------------------------------------------------------------------------- #
# C. The historical hazard, in a bounded child process
# --------------------------------------------------------------------------- #
#: The scenario, as a child program. ``build`` is a function on purpose: the
#: cycle has to become unreachable when it returns, or the collector never
#: finalises anything and the reproduction proves nothing.
_CHILD = textwrap.dedent(
    """
    import gc, sys, threading, tkinter as tk
    root = tk.Tk(); root.withdraw()

    def build(disarm):
        var = tk.StringVar(master=root, value="x")
        class H: pass
        a, b = H(), H()
        a.other, b.other = b, a
        a.var = var
        if disarm:
            var._tk.globalunsetvar(var._name)
            var._tclCommands = None
            var._tk = None

    build({disarm})
    gc.disable()
    finished = threading.Event()
    def worker():
        gc.collect()          # the cyclic collection, on a NON-main thread
        finished.set()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    sys.exit(0 if finished.wait(10) else 3)
    """
)


def _run_child(*, disarm: bool):
    return subprocess.run(
        [sys.executable, "-c", _CHILD.format(disarm=disarm)],
        capture_output=True, text=True, timeout=BOUND * 3, cwd=REPO_ROOT)


def test_the_unfixed_shape_is_reproduced_in_a_bounded_child():
    """An armed variable really is finalised off the main thread, and complains.

    Run in a child with a hard timeout so a build where this *stalls* — the
    worse form of the same defect, on a Tk compiled with threading — cannot
    strand the phase.

    **Reported honestly:** on this machine (CPython 3.12.10, Tcl/Tk 8.6)
    ``_tkinter`` guards the call and raises ``RuntimeError: main thread is not
    in main loop``, which the interpreter swallows as *Exception ignored*. It
    does not hang here. The finaliser is still being run from the wrong thread,
    which is the defect; the consequence is build-dependent, and the fix removes
    the cause rather than relying on the guard.
    """
    result = _run_child(disarm=False)

    assert result.returncode == 0, f"the child stalled: {result.stderr[-800:]}"
    assert "Variable.__del__" in result.stderr, (
        "the child did not reach a Tk finaliser off the main thread, so this "
        f"no longer reproduces the hazard: {result.stderr[-800:]}")


def test_the_same_shape_is_silent_once_disarmed():
    """The identical scenario, with only the boundary's severing applied."""
    result = _run_child(disarm=True)

    assert result.returncode == 0, result.stderr[-800:]
    assert "Variable.__del__" not in result.stderr, result.stderr[-800:]
    assert "Exception ignored" not in result.stderr, result.stderr[-800:]


# --------------------------------------------------------------------------- #
# D. The invariant across a real UI module, in a bounded child pytest
# --------------------------------------------------------------------------- #
_CENSUS_PLUGIN = textwrap.dedent(
    """
    import gc
    def pytest_sessionfinish(session, exitstatus):
        import sys
        if "tkinter" not in sys.modules:
            print("ARMED=0")
            return
        import tkinter as tk
        armed = 0
        for obj in gc.get_objects():
            if isinstance(obj, tk.Variable) and getattr(obj, "_tk", None) is not None:
                armed += 1
            elif isinstance(obj, tk.Image) and getattr(obj, "name", None):
                armed += 1
        print(f"ARMED={armed}")
    """
)


def test_a_real_ui_module_leaves_nothing_armed(tmp_path):
    """The measurement that was 90 before the fix, run against a real module.

    A child pytest so the census sees a whole session's teardown, bounded so it
    cannot hang this one.
    """
    plugin = tmp_path / "census_plugin.py"
    plugin.write_text(_CENSUS_PLUGIN, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "files/tests/test_ui_theme.py",
         "-q", "--no-header", "--tb=no", "-p", "no:randomly",
         "-p", "census_plugin"],
        capture_output=True, text=True, timeout=BOUND * 20, cwd=REPO_ROOT,
        env={**__import__("os").environ,
             "PYTHONPATH": str(tmp_path)})

    assert "ARMED=" in result.stdout, result.stdout[-2000:]
    armed = int(result.stdout.split("ARMED=")[1].split()[0])
    assert armed == 0, (
        f"{armed} Tk objects survived the run still able to call into Tcl "
        "from a finaliser on an arbitrary thread")
