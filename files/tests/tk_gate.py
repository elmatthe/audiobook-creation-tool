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
import sys

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
    try:
        yield root
    finally:
        if before_destroy is not None:
            before_destroy()
        _reset_root(root)
