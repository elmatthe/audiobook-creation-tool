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


class FakeInterp:
    """The ``root.tk`` handle, enough of it for the reset to be observable."""

    def __init__(self, owner):
        self.owner = owner

    def call(self, *args):
        if args[:2] == ("after", "info"):
            return tuple(self.owner.pending)
        return ""


class FakeChild:
    def __init__(self, owner):
        self.owner = owner
        self.destroyed = False

    def destroy(self):
        self.destroyed = True
        if self in self.owner.children:
            self.owner.children.remove(self)


class FakeTk:
    """A tkinter stand-in whose root constructor does whatever a test needs.

    It doubles as the *root* it hands back, and carries enough of a root's
    surface for :func:`tk_gate._reset_root` to be observed rather than guessed
    at: pending ``after`` ids, bindings, children, the protocol handler and the
    geometry all record what was done to them.
    """

    TclError = FakeTclError

    def __init__(self, raises=None):
        self._raises = raises
        self.destroyed = False
        self.withdrawn = False
        self.tk = FakeInterp(self)
        self.pending = []
        self.cancelled = []
        self.all_bindings = []
        self.own_bindings = []
        self.unbound = []
        self.children = []
        self.protocols = []
        self.geometries = []
        self.updated = 0

    def Tk(self):                                    # noqa: N802 - mirrors tkinter
        if self._raises is not None:
            raise self._raises
        return self

    def withdraw(self):
        self.withdrawn = True

    def destroy(self):
        self.destroyed = True

    # -- the surface the reset touches ---------------------------------- #

    def after_cancel(self, identifier):
        self.cancelled.append(identifier)
        if identifier in self.pending:
            self.pending.remove(identifier)

    def bind_all(self, *args):
        return tuple(self.all_bindings)

    def bind(self, *args):
        return tuple(self.own_bindings)

    def unbind_all(self, sequence):
        self.unbound.append(sequence)
        if sequence in self.all_bindings:
            self.all_bindings.remove(sequence)

    def unbind(self, sequence):
        self.unbound.append(sequence)
        if sequence in self.own_bindings:
            self.own_bindings.remove(sequence)

    def winfo_children(self):
        return list(self.children)

    def protocol(self, name, handler):
        self.protocols.append((name, handler))

    def geometry(self, value):
        self.geometries.append(value)

    def update_idletasks(self):
        self.updated += 1


@pytest.fixture(autouse=True)
def _no_shared_root_leaks():
    """No stand-in root may survive into another test, or into the real suite."""
    tk_gate._SHARED_ROOT = None
    yield
    tk_gate._SHARED_ROOT = None


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


def test_the_session_hides_the_root_and_resets_it_afterwards(monkeypatch):
    """**A deliberate progression.** The scope no longer destroys the root.

    It used to, and that was the defect: creating a Tcl interpreter, destroying
    it and creating another inside a pytest process fails on Windows. So the
    interpreter is now created once and *reset* around each scope instead. What
    a scope gets is still a pristine hidden root; what it no longer gets is a
    brand-new interpreter.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    session = tk_gate.tk_root_session(fake)
    root = next(session)
    assert root is fake and fake.withdrawn and not fake.destroyed
    with pytest.raises(StopIteration):
        next(session)
    assert not fake.destroyed, "the one interpreter outlives the scope"
    assert fake.withdrawn, "and is hidden again"


def test_the_scope_end_takes_back_everything_the_scope_left(monkeypatch):
    """A shared interpreter is only safe if the reset is total."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    session = tk_gate.tk_root_session(fake)
    root = next(session)

    root.pending.extend(["after#1", "after#2"])
    root.all_bindings.append("<<Global>>")
    root.own_bindings.append("<Key>")
    child = FakeChild(root)
    root.children.append(child)

    with pytest.raises(StopIteration):
        next(session)

    assert root.cancelled == ["after#1", "after#2"], "a stray callback cannot fire later"
    assert set(root.unbound) == {"<<Global>>", "<Key>"}
    assert child.destroyed and root.children == []
    assert ("WM_DELETE_WINDOW", "") in root.protocols
    assert "" in root.geometries, "the next scope sizes its own window"


def test_the_same_interpreter_serves_every_scope(monkeypatch):
    """One Tcl interpreter per process is the whole point of the change."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    first = next(tk_gate.tk_root_session(fake))
    second = next(tk_gate.tk_root_session(fake))
    assert first is second is fake
    assert not fake.destroyed


def test_the_shared_root_is_destroyed_once_at_process_exit(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    assert tk_gate.shared_root(fake) is fake
    tk_gate._close_shared_root()
    assert fake.destroyed, "the interpreter is not leaked at exit"
    tk_gate._close_shared_root()
    assert tk_gate._SHARED_ROOT is None, "and closing twice is harmless"


def test_the_session_resets_the_root_even_when_a_test_explodes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake = FakeTk()
    session = tk_gate.tk_root_session(fake)
    root = next(session)
    child = FakeChild(root)
    root.children.append(child)
    root.pending.append("after#3")

    with pytest.raises(RuntimeError):
        session.throw(RuntimeError("a test blew up"))

    assert child.destroyed, "teardown still runs when the body raises"
    assert root.cancelled == ["after#3"]
    assert not fake.destroyed, "but the interpreter still survives"


def test_the_pre_destroy_hook_runs_while_tk_is_still_alive(monkeypatch):
    """The dialog modules finalise their Tk variables before anything is taken away.

    Strictly safer than before: the hook used to run just ahead of the root's
    destruction, and now it runs while an interpreter that is not going anywhere
    is still fully alive.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    fake, order = FakeTk(), []
    session = tk_gate.tk_root_session(fake, before_destroy=lambda: order.append("hook"))
    root = next(session)
    child = FakeChild(root)
    child.destroy = lambda: order.append("reset")
    root.children.append(child)

    with pytest.raises(StopIteration):
        next(session)

    assert order == ["hook", "reset"], "the hook runs before the reset"
    assert not fake.destroyed


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
    # v0.6.2: was function-scoped, which built and tore down one Tcl
    # interpreter per live-Tk test in that module. Now module-scoped like every
    # other GUI module in this suite.
    ("test_bootstrap_setup_dialog_fit", "module"),
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


def test_the_gate_never_retries_sleeps_or_swallows_a_failure():
    """The one thing this file exists to prevent, pinned structurally.

    A shared interpreter makes it tempting to "just try again" when one will not
    open. That would put the silent-skip hole straight back, so the gate must
    contain no retry, no backoff, no sleep and no place where a ``TclError`` on a
    required platform turns into anything but a failure.
    """
    source = (TESTS_DIR / "tk_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # AST, not substring: prose about lifecycles legitimately contains the word
    # "while", and a guard that cannot tell a docstring from a loop is not a
    # guard. What matters is that the module calls nothing that waits, and that
    # the *decision* to open a root is made once rather than in a loop.
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for waiting in ("sleep", "wait", "retry", "backoff"):
        assert waiting not in called, waiting

    opener_node = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "open_tk_root")
    loops = [node for node in ast.walk(opener_node)
             if isinstance(node, (ast.While, ast.For))]
    assert loops == [], "opening a root is one attempt, never a loop"

    opener = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "open_tk_root")
    handlers = [node for node in ast.walk(opener) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 1, "one classification point, not a ladder of rescues"
    calls = {node.func.attr for node in ast.walk(opener)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "fail" in calls and "skip" in calls, "both verdicts still reachable"


def test_the_reset_swallows_nothing_that_belongs_to_a_test():
    """``_reset_root`` is tolerant on purpose; ``open_tk_root`` is not.

    The reset runs during teardown, where a widget that has already gone is
    ordinary rather than exceptional. That tolerance must not have spread to the
    part that decides whether a run is allowed to continue.
    """
    source = (TESTS_DIR / "tk_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    opener = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "open_tk_root")
    for handler in (node for node in ast.walk(opener)
                    if isinstance(node, ast.ExceptHandler)):
        assert handler.type is not None, "open_tk_root never catches bare Exception"
        assert getattr(handler.type, "attr", "") == "TclError", (
            "only a TclError is classified")


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
