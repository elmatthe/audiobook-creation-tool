"""The Tk gate itself — v0.6.1 Plan 4 Phase 14C.

Phase 14 caught a full-suite run reporting success while forty-nine Chatterbox
integration tests never ran: their Tk root failed to open and the fixture called
``pytest.skip``. The gate in :mod:`tk_gate` is what makes that impossible on a
platform where the GUI is expected to work, so the gate needs its own proof.

Nothing here opens a real display except the one test that asks for a live root.
The failure paths are driven by a stand-in tkinter whose constructor raises on
demand, so the fail-loud behaviour is proved deterministically rather than by
waiting for a real Tcl/Tk to break.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import tk_gate  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent


class FakeTclError(Exception):
    """Stands in for ``tkinter.TclError`` without importing a display."""


class FakeTk:
    """A tkinter stand-in whose root constructor does whatever a test needs."""

    TclError = FakeTclError

    def __init__(self, raises=None):
        self._raises = raises
        self.destroyed = False
        self.withdrawn = False

    def Tk(self):                                    # noqa: N802 - mirrors tkinter
        if self._raises is not None:
            raise self._raises
        return self

    def withdraw(self):
        self.withdrawn = True

    def destroy(self):
        self.destroyed = True


# --------------------------------------------------------------------------- #
# Which environments owe us a working Tk
# --------------------------------------------------------------------------- #


def test_windows_requires_a_display(monkeypatch):
    """The desktop is the platform there: a broken Tk is a defect, not absence."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert tk_gate.display_is_required() is True


@pytest.mark.parametrize("platform", ["darwin", "linux", "freebsd"])
def test_other_platforms_still_tolerate_a_missing_display(monkeypatch, platform):
    """A POSIX box really can have no display server, and CI often does not."""
    monkeypatch.setattr(sys, "platform", platform)
    assert tk_gate.display_is_required() is False


def test_this_machine_answers_for_its_own_platform():
    """No monkeypatching: the gate must classify the real runner correctly."""
    assert tk_gate.display_is_required() == (sys.platform == "win32")


# --------------------------------------------------------------------------- #
# The three outcomes of asking for a root
# --------------------------------------------------------------------------- #


def test_a_working_tk_is_handed_back_untouched(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    assert tk_gate.open_tk_root(fake) is fake


def test_a_failure_where_a_display_is_required_fails_the_run(monkeypatch):
    """The whole point: this must not become a skip on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk(raises=FakeTclError('invalid command name "tcl_findLibrary"'))
    with pytest.raises(pytest.fail.Exception) as failure:
        tk_gate.open_tk_root(fake)
    assert not isinstance(failure.value, pytest.skip.Exception), (
        "a required display must never be reported as a skip")


def test_the_failure_message_keeps_the_original_error(monkeypatch):
    """Whoever reads the report needs the real Tcl error, not a summary."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk(raises=FakeTclError('invalid command name "tcl_findLibrary"'))
    with pytest.raises(pytest.fail.Exception) as failure:
        tk_gate.open_tk_root(fake)
    message = str(failure.value)
    assert 'invalid command name "tcl_findLibrary"' in message
    assert "FakeTclError" in message, "the exception type survives too"


def test_a_failure_where_a_display_is_optional_still_skips(monkeypatch):
    """Headless POSIX keeps exactly the behaviour it had before Phase 14C."""
    monkeypatch.setattr(sys, "platform", "linux")
    fake = FakeTk(raises=FakeTclError("no display name and no DISPLAY variable"))
    with pytest.raises(pytest.skip.Exception) as skipped:
        tk_gate.open_tk_root(fake)
    assert "no display name" in str(skipped.value)


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_an_unrelated_exception_is_never_relabelled_headless(monkeypatch, platform):
    """A test-code defect must surface as itself, on either kind of platform."""
    monkeypatch.setattr(sys, "platform", platform)
    fake = FakeTk(raises=AttributeError("someone renamed a helper"))
    with pytest.raises(AttributeError):
        tk_gate.open_tk_root(fake)


# --------------------------------------------------------------------------- #
# The shared fixture body
# --------------------------------------------------------------------------- #


def test_the_session_hides_the_root_and_destroys_it_afterwards(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    session = tk_gate.tk_root_session(fake)
    root = next(session)
    assert root is fake and fake.withdrawn and not fake.destroyed
    with pytest.raises(StopIteration):
        next(session)
    assert fake.destroyed, "the root is destroyed when the scope ends"


def test_the_session_destroys_the_root_even_when_a_test_explodes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    session = tk_gate.tk_root_session(fake)
    next(session)
    with pytest.raises(RuntimeError):
        session.throw(RuntimeError("a test blew up"))
    assert fake.destroyed, "teardown still runs when the body raises"


def test_the_pre_destroy_hook_runs_while_tk_is_still_alive(monkeypatch):
    """The dialog modules finalise their Tk variables before the root goes."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake, order = FakeTk(), []
    fake.destroy = lambda: order.append("destroy")
    session = tk_gate.tk_root_session(fake, before_destroy=lambda: order.append("hook"))
    next(session)
    with pytest.raises(StopIteration):
        next(session)
    assert order == ["hook", "destroy"]


def test_a_failed_session_never_yields_a_root(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    session = tk_gate.tk_root_session(FakeTk(raises=FakeTclError("broken")))
    with pytest.raises(pytest.fail.Exception):
        next(session)


# --------------------------------------------------------------------------- #
# The live root, and the scopes its users depend on
# --------------------------------------------------------------------------- #


def test_a_real_root_can_still_be_opened_and_destroyed():
    """The gate must not have broken the ordinary path on this machine."""
    tk = pytest.importorskip("tkinter")
    root = tk_gate.open_tk_root(tk)
    try:
        assert root.winfo_exists()
    finally:
        root.destroy()


@pytest.mark.parametrize("module_name, scope", [
    ("test_tts_importing", "module"),
    ("test_cover_browser", "module"),
    ("test_plan4_lifecycle_races", "module"),
    ("test_bootstrap_setup_dialog_fit", "function"),
])
def test_the_repaired_fixtures_keep_the_scope_their_users_expect(module_name, scope):
    """Sharing one root per module is a performance contract, not an accident."""
    module = pytest.importorskip(module_name)
    marker = module.tk_root._fixture_function_marker
    assert marker.scope == scope, f"{module_name}.tk_root changed scope"


# --------------------------------------------------------------------------- #
# No module may reopen the hole
# --------------------------------------------------------------------------- #


def _raw_tk_root_calls(path: Path) -> list[int]:
    """Line numbers where a collected test builds a Tk root without the gate."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Tk"]


def test_no_collected_test_module_opens_a_tk_root_outside_the_gate():
    """Structural, not textual: a new module cannot quietly bring back the skip."""
    offenders = {
        path.name: lines
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if (lines := _raw_tk_root_calls(path))
    }
    assert offenders == {}, (
        "these modules call tk.Tk() directly instead of tk_gate.open_tk_root(); "
        f"an unexpected Tk failure there would silently skip coverage: {offenders}")
