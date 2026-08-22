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


def tk_root_session(tk, *, before_destroy=None):
    """The shared fixture body: one hidden root, destroyed when the scope ends.

    Used as ``yield from tk_gate.tk_root_session(tk)`` so each module keeps
    ownership of its own fixture name and scope. *before_destroy* runs while the
    interpreter still owns a live Tk, which is what the dialog modules need in
    order to finalise their Tk variables safely.
    """
    root = open_tk_root(tk)
    root.withdraw()
    try:
        yield root
    finally:
        if before_destroy is not None:
            before_destroy()
        root.destroy()
