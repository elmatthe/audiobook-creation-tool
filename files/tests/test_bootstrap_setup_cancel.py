"""v0.6.1 Plan 4 Phase 12 remediation — Cancel is not a failed setup.

The maintainer opened the genuine first-run dialog to check the layout fix,
clicked **Cancel**, and the terminal answered:

    Setup did not complete successfully (exit code 1).
    See the log under files\\runtime-data\\logs\\ for details.

That is untrue and alarming. The cause is one line: ``run_with_gui`` ended with
``return 0 if state["ok"] else 1``, and ``state["ok"]`` is only ever set by a
*completed* install. There was no third state, so "the user chose not to install"
and "the install broke" collapsed into the same exit code, and the ``.bat`` — which
correctly treats any non-zero as failure — printed the failure text.

The fix adds one distinct code, :data:`bootstrap.EXIT_SETUP_CANCELLED`, returned
only when the dialog closes **without setup ever having been started**. Everything
else keeps its old meaning:

======================================  ==========================
outcome                                  exit code
======================================  ==========================
setup completed                          0
user cancelled before starting           EXIT_SETUP_CANCELLED (2)
setup ran and failed                     1
window closed mid-install                1  (genuinely incomplete)
======================================  ==========================

Nothing here launches Tk or installs anything: ``run_with_gui`` is driven through
its own seams.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from shared import bootstrap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BAT = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
SRC = Path(bootstrap.__file__).read_text(encoding="utf-8")


def _run_with_gui_source() -> str:
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    return ast.get_source_segment(SRC, fn)


# --------------------------------------------------------------------------- #
# A. A distinct, non-colliding cancellation code exists
# --------------------------------------------------------------------------- #
def test_a_dedicated_cancellation_exit_code_exists():
    assert isinstance(bootstrap.EXIT_SETUP_CANCELLED, int)


def test_cancellation_is_not_confused_with_success_or_failure():
    """It must be its own value — 0 would hide it, 1 is the failure code."""
    assert bootstrap.EXIT_SETUP_CANCELLED not in (0, 1)


# --------------------------------------------------------------------------- #
# B. The four outcomes map to the four codes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "started,done,ok,expected",
    [
        (True, True, True, 0),                                   # completed
        (False, False, False, "cancelled"),                      # Cancel / closed
        (True, True, False, 1),                                  # ran and failed
        (True, False, False, 1),                                 # closed mid-install
    ],
)
def test_the_exit_code_matches_the_outcome(started, done, ok, expected):
    want = bootstrap.EXIT_SETUP_CANCELLED if expected == "cancelled" else expected
    assert bootstrap.setup_exit_code(
        started=started, done=done, ok=ok) == want


def test_cancelling_before_starting_is_never_reported_as_failure():
    assert bootstrap.setup_exit_code(started=False, done=False, ok=False) != 1


def test_a_genuine_failure_is_still_a_failure():
    """Do not turn every non-zero result into success."""
    assert bootstrap.setup_exit_code(started=True, done=True, ok=False) == 1


def test_success_is_still_zero():
    assert bootstrap.setup_exit_code(started=True, done=True, ok=True) == 0


# --------------------------------------------------------------------------- #
# C. The dialog is wired to it
# --------------------------------------------------------------------------- #
def test_run_with_gui_returns_through_the_shared_mapping():
    body = _run_with_gui_source()
    assert "setup_exit_code(" in body
    assert "return 0 if state[\"ok\"] else 1" not in body


def test_the_dialog_tracks_whether_setup_was_ever_started():
    body = _run_with_gui_source()
    assert '"started"' in body


def test_cancel_and_the_window_close_both_leave_setup_unstarted():
    """Neither route may set ``started``; only Begin Setup does."""
    body = _run_with_gui_source()
    begin = body[body.index("def begin()"):]
    assert 'state["started"] = True' in begin
    cancel_line = next(line for line in body.splitlines()
                       if "text=\"Cancel\"" in line)
    assert "started" not in cancel_line


# --------------------------------------------------------------------------- #
# D. Cancelling installs nothing and records nothing
# --------------------------------------------------------------------------- #
def test_cancelling_never_writes_a_requirements_stamp(monkeypatch, tmp_path):
    """A cancelled setup must not look like a reconciled environment."""
    venv = tmp_path / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("pillow==12.2.0\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", reqs)

    # The cancel path returns without ever entering run_setup.
    assert bootstrap.setup_exit_code(started=False, done=False, ok=False) == \
        bootstrap.EXIT_SETUP_CANCELLED
    assert not bootstrap.requirements_state_path().exists()
    assert bootstrap.requirements_are_current() is False


def test_the_stamp_is_only_written_from_a_path_that_just_succeeded():
    """Proves no dialog path can stamp an environment.

    Exactly two writers are correct and intended: ``run_setup`` stamps after
    ``validate_installed_packages``, and ``ensure_requirements_current`` stamps
    after a successful pip + validate. Neither is reachable from a cancelled
    dialog, because Cancel never starts either one.
    """
    enclosing = sorted(
        n.name for n in ast.walk(ast.parse(SRC))
        if isinstance(n, ast.FunctionDef)
        and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "record_requirements_state"
                for c in ast.walk(n))
    )
    assert enclosing == ["ensure_requirements_current", "run_setup"]
    assert "record_requirements_state" not in _run_with_gui_source()


def test_setup_only_starts_from_the_begin_button():
    """Opening the dialog must not install anything on its own."""
    body = _run_with_gui_source()
    starts = [line for line in body.splitlines() if "threading.Thread(" in line]
    assert len(starts) == 1
    begin = body[body.index("def begin()"):body.index("begin_btn.configure")]
    assert "threading.Thread(" in begin


# --------------------------------------------------------------------------- #
# E. The launcher tells the truth
# --------------------------------------------------------------------------- #
def _bat_text() -> str:
    return BAT.read_text(encoding="utf-8", errors="replace")


def test_the_bat_handles_the_cancellation_code_separately():
    text = _bat_text()
    assert str(bootstrap.EXIT_SETUP_CANCELLED) in text


def test_the_bat_does_not_call_a_cancellation_a_failed_setup():
    """The exact string the maintainer saw must not be reachable for Cancel."""
    text = _bat_text()
    failure_idx = text.index("Setup did not complete successfully")
    cancel_idx = text.index(f'"%RC%"=="{bootstrap.EXIT_SETUP_CANCELLED}"')
    assert cancel_idx < failure_idx, (
        "the cancellation branch must be taken before the failure message")


def test_the_bat_still_reports_a_real_failure():
    text = _bat_text()
    assert "Setup did not complete successfully" in text
    assert "%errorlevel%" in text


def test_the_bat_says_setup_was_cancelled():
    assert re.search(r"Setup (was )?cancell?ed", _bat_text(), re.IGNORECASE)


# --------------------------------------------------------------------------- #
# F. Everything else about the launcher is untouched
# --------------------------------------------------------------------------- #
def test_the_daily_fast_path_is_unchanged():
    text = _bat_text()
    assert 'if exist ".venv\\Scripts\\pythonw.exe"' in text
    assert "--launch-only" in text


def test_first_run_defaults_are_unchanged():
    body = _run_with_gui_source()
    assert '"download_chatterbox": tk.BooleanVar(value=False)' in body
    assert '"download_kokoro": tk.BooleanVar(value=not skip_kokoro_default)' in body
