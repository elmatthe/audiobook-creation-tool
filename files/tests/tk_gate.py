"""Whether a missing Tk is an absence to tolerate or a defect to report.

Every live-Tk module in this suite used to open its own root like this::

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk cannot open a display here: {exc}")

That is right on a headless POSIX box, where no display server is a fact about
the environment rather than a fault. It is wrong on Windows, where the desktop
*is* the platform: there ``tk.Tk()`` failing means Tk is broken, and turning
that into a skip let a whole module of GUI coverage vanish from a run that still
reported success. Phase 14 measured exactly that — one full-suite invocation
silently dropped forty-nine Chatterbox integration tests and still exited zero.

So the classification is made once, here, from the platform rather than from the
text of the error, and the two answers are kept apart:

* where a windowing system is part of the platform, a failed root **fails** the
  run and carries the original exception with it;
* where a display is genuinely optional, it still **skips**, exactly as before.

Only ``TclError`` is classified. Anything else a fixture manages to raise is a
defect in the test code and is left to propagate as itself, because labelling a
programming error "headless" is how the coverage went missing in the first
place.
"""

from __future__ import annotations

import atexit
import gc
import sys
import threading

import pytest


def display_is_required() -> bool:
    """True where the platform always provides a windowing system.

    Windows has no headless desktop session in the X11 sense: an interactive
    login always owns a window station, so tkinter importing but refusing to
    open a root is a broken Tcl/Tk installation, not an absent display. macOS
    and Linux keep the tolerant answer — a display server really can be absent
    there, and no repository authority requires one.
    """
    return sys.platform == "win32"


def open_tk_root(tk):
    """A live Tk root, or a loud verdict on why there isn't one.

    *tk* is the caller's already-imported ``tkinter`` module, so a module that
    must tolerate tkinter itself being absent can keep its own
    ``pytest.importorskip`` and still share this rule.
    """
    try:
        return tk.Tk()
    except tk.TclError as exc:
        if display_is_required():
            pytest.fail(
                "Tk could not initialise on a platform where the GUI suite is "
                "required, so this run would otherwise have dropped its live-Tk "
                f"coverage and still reported success: {type(exc).__name__}: {exc}",
                pytrace=False,
            )
        pytest.skip(f"Tk cannot open a display here: {exc}")


#: The one Tcl interpreter this process uses. See :func:`tk_root_session`.
_SHARED_ROOT = None


def _reset_root(root) -> None:
    """Return the shared root to the state a freshly created one would be in.

    Everything a module can leave behind is taken away here, in the order that
    makes each step safe: pending ``after`` callbacks first, because one firing
    into a half-dismantled window is exactly the class of defect this file
    exists to prevent; then bindings, then widgets, then the window itself.

    Deliberately explicit rather than "close enough". A shared interpreter is
    only safe if the reset is total, and anything this misses would show up as
    one module quietly passing because of another.
    """
    try:
        for callback in root.tk.call("after", "info"):
            try:
                root.after_cancel(callback)
            except Exception:
                pass
    except Exception:
        pass

    for sequence in list(root.bind_all()):
        try:
            root.unbind_all(sequence)
        except Exception:
            pass
    for sequence in list(root.bind()):
        try:
            root.unbind(sequence)
        except Exception:
            pass

    for child in list(root.winfo_children()):
        try:
            child.destroy()
        except Exception:
            pass

    try:
        root.protocol("WM_DELETE_WINDOW", "")
    except Exception:
        pass
    try:
        root.geometry("")
        root.withdraw()
        root.update_idletasks()
    except Exception:
        pass


#: Tk types whose ``__del__`` calls into Tcl, and the attribute that arms it.
#: Widgets are absent on purpose — ``Misc`` has no finaliser, and ``_reset_root``
#: already destroys every child.
_ARMED_ATTRIBUTE = {"Variable": "_tk", "Image": "name"}


def _disarm_variable(variable) -> bool:
    """Do what ``Variable.__del__`` would do, here, and then make it a no-op.

    The unset and the trace-command deletion happen on **this** thread, which is
    the main one; then ``_tk`` is cleared. ``Variable.__del__`` starts with
    ``if self._tk is None: return``, so once that reference is gone the object
    is inert no matter which thread the cyclic collector later runs it on. That
    is the whole guarantee: not "the finaliser will probably run somewhere
    safe", but "there is no longer a finaliser that can call into Tcl at all".
    """
    interpreter = getattr(variable, "_tk", None)
    if interpreter is None:
        return False
    name = getattr(variable, "_name", None)
    try:
        if name and interpreter.getboolean(
                interpreter.call("info", "exists", name)):
            interpreter.globalunsetvar(name)
    except Exception:
        # A variable whose interpreter has already gone is exactly the case
        # this exists to make harmless; there is nothing left to clean up.
        pass
    for command in tuple(getattr(variable, "_tclCommands", None) or ()):
        try:
            interpreter.deletecommand(command)
        except Exception:
            pass
    variable._tclCommands = None
    variable._tk = None
    return True


def _disarm_image(image) -> bool:
    """The same for ``Image``: delete the Tcl image here, then clear ``name``.

    ``Image.__del__`` is guarded by ``if self.name``, so clearing it disarms the
    object the same way.
    """
    name = getattr(image, "name", None)
    if not name:
        return False
    try:
        image.tk.call("image", "delete", name)
    except Exception:
        pass
    image.name = None
    return True


def _live_types(tk):
    """``(Variable, Image)`` for a real tkinter, or ``None`` for a stand-in.

    Several modules hand their fixtures a fake ``tkinter`` — a ``FakeTk`` with
    just the attributes that module needs — and the boundary must be a no-op for
    those rather than an AttributeError. It has nothing to finalise there
    anyway: a fake never created a Tcl interpreter.
    """
    variable = getattr(tk, "Variable", None)
    image = getattr(tk, "Image", None)
    if not isinstance(variable, type) or not isinstance(image, type):
        return None
    return variable, image


def _instances_of(types):
    """Live objects of the given types, tolerating whatever else is on the heap.

    ``isinstance`` is deliberately **not** used. ``gc.get_objects()`` returns
    everything, dead ``weakref.proxy`` objects included, and ``isinstance`` on a
    proxy whose referent has gone raises ``ReferenceError`` — which is how the
    first version of this boundary turned a thousand unrelated tests into setup
    errors. ``type(obj)`` never dereferences anything, so asking whether that
    type is a subclass is both equivalent here (neither class defines
    ``__instancecheck__``) and safe on any object at all.
    """
    for obj in gc.get_objects():
        if issubclass(type(obj), types):
            yield obj


def finalise_tk_objects(tk) -> int:
    """Finalise every leftover Tk variable and image **on the main thread**.

    **The defect (L2).** ``_reset_root`` destroys widgets, cancels ``after``
    callbacks and unbinds events, but a ``tkinter.Variable`` is not owned by the
    widget that used it: destroying a frame leaves its variables alive, still
    holding a reference to the shared interpreter. Measured before this fix, one
    short run of three UI modules ended with **90 live variables still armed**
    and a live root. Each of those carries a ``__del__`` that calls into Tcl.

    Nothing decides when that finaliser runs. Reference counting would run it
    on whichever thread dropped the last reference — the main one, in a test —
    but these variables sit inside reference cycles, so it is the **cyclic**
    collector that eventually finalises them, on whichever thread happens to
    allocate enough to trigger a collection. That can be a worker thread, and a
    worker calling into Tcl is at best an ignored ``RuntimeError`` and at worst
    a stall on the interpreter lock. The suite has already paid for this once:
    a bounded five-second thread-start wait in ``test_job_ui.py`` timed out when
    an unrelated change shifted when collection ran.

    **The fix is not to avoid provoking it.** Phase 1 reduced the allocation
    churn so collection was less likely to land badly, which is a smaller
    probability rather than an invariant. This makes it deterministic: every
    surviving Tk object is finalised *here*, at a module boundary, on the main
    thread, and then disarmed — so any later cyclic collection, wherever it
    runs, finds nothing that can call into Tcl.

    Returns how many objects were disarmed, so a regression can assert on it.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "the Tk finalisation boundary must run on the main thread; "
            f"it was called from {threading.current_thread().name!r}")

    types = _live_types(tk)
    if types is None:
        return 0
    variable_type, image_type = types

    # Collect first, so what is severed below is genuinely what survives rather
    # than objects that were already unreachable and about to go anyway. This
    # collection is on the main thread, which is the point.
    gc.collect()

    disarmed = 0
    for obj in list(_instances_of(types)):
        if issubclass(type(obj), variable_type):
            disarmed += _disarm_variable(obj)
        elif issubclass(type(obj), image_type):
            disarmed += _disarm_image(obj)

    # And again, so the now-inert cycles are cleared here rather than left for
    # an arbitrary thread to trip over later.
    gc.collect()
    return disarmed


def armed_tk_objects(tk) -> list:
    """Every live Tk object that could still call into Tcl from a finaliser.

    The measurement the regression asserts on, kept beside the fix so the two
    cannot describe different things.
    """
    types = _live_types(tk)
    if types is None:
        return []
    variable_type, image_type = types

    armed = []
    for obj in _instances_of(types):
        if issubclass(type(obj), variable_type):
            if getattr(obj, "_tk", None) is not None:
                armed.append(obj)
        elif getattr(obj, "name", None):
            armed.append(obj)
    return armed


def shared_root(tk):
    """The one live root for this process, created on first use.

    **Why one interpreter and not one per module.** Creating a Tcl interpreter,
    destroying it and creating another inside a pytest process fails on Windows:
    measured at Phase 10 HEAD, a throwaway root followed by a second root failed
    5 of 5 times, and the same churn across module boundaries turned the GUI gate
    into a coin flip — the "missing" ``init.tcl`` / ``scrlbar.tcl`` / ``sizegrip.tcl``
    it reported are all physically present and readable. Outside pytest the same
    churn is harmless, which is why it only ever surfaced as flakiness.

    So the interpreter is created once and reused. It is **not** shared state:
    :func:`_reset_root` returns it to a pristine condition around every module,
    so a module still gets a root with no widgets, no bindings, no scheduled
    callbacks and no geometry of anyone else's.

    Creation still goes through :func:`open_tk_root`, so a Windows Tk that
    genuinely cannot start still fails the run loudly. Nothing here retries,
    sleeps, skips or swallows a ``TclError``.
    """
    global _SHARED_ROOT
    if _SHARED_ROOT is None:
        root = open_tk_root(tk)
        root.withdraw()
        _SHARED_ROOT = root
        atexit.register(_close_shared_root)
    return _SHARED_ROOT


def _close_shared_root() -> None:
    """Destroy the one interpreter, once, when the process ends."""
    global _SHARED_ROOT
    root, _SHARED_ROOT = _SHARED_ROOT, None
    if root is not None:
        try:
            root.destroy()
        except Exception:
            pass


def tk_root_session(tk, *, before_destroy=None):
    """The shared fixture body: one hidden root, reset around every scope.

    Used as ``yield from tk_gate.tk_root_session(tk)`` so each module keeps
    ownership of its own fixture name and scope. *before_destroy* runs while the
    interpreter still owns a live Tk, which is what the dialog modules need in
    order to finalise their Tk variables safely — and now it always does, which
    makes that hook strictly safer than it was.

    The root itself is the process-wide one (see :func:`shared_root`) and is
    destroyed once at exit rather than at the end of every scope. What each
    scope gets is a *pristine* root, not a new interpreter.
    """
    root = shared_root(tk)
    _reset_root(root)
    finalise_tk_objects(tk)
    try:
        yield root
    finally:
        if before_destroy is not None:
            before_destroy()
        _reset_root(root)
        # Widgets are gone by now; their variables are not, because a variable
        # is not owned by the widget that used it. Finalise them here, on the
        # main thread, rather than leaving them for whichever thread the cyclic
        # collector next runs on. See :func:`finalise_tk_objects`.
        finalise_tk_objects(tk)
