"""PRE-PLAN-6 Phase 1 — the suite must not write real production state.

**What went wrong.** Running the gate rewrote the developer's real
``.venv/.requirements-state.json``. Traced mechanically rather than guessed:
three tests drove ``run_setup`` with every install step stubbed but left
``bootstrap.VENV_DIR`` pointing at the real checkout, so the stamp written at the
end of setup landed in the real environment. Separately, ``bootstrap`` opened the
dated setup log at *import* time, and ``shared.logging_setup`` wrote a real
``session_*.log`` whenever a test built the launcher.

**Why it mattered.** The stamp write was harmless only because the fingerprint
happened to match. A suite that can write the real stamp can write a **false**
one — an environment recorded as reconciled when it is not — which is exactly the
invariant the requirements work exists to protect. And a production log
interleaving pytest temp paths with real runs is worth less when a user sends it
in to diagnose a real failure.

**The fix has three parts**, all in ``conftest.py`` and the culprit tests, plus
one production change (``SetupLog`` opens its file on first use, not at
construction). This module proves the guard is real and still armed — a guard
that has quietly become a no-op is worse than none, because it reads as coverage.
"""

from __future__ import annotations

from pathlib import Path

from shared import bootstrap, paths

import conftest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# A. The guard watches the right things
# --------------------------------------------------------------------------- #
def test_the_guard_watches_the_real_requirements_stamp():
    assert (REPO_ROOT / ".venv" / ".requirements-state.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_setup_log_directory():
    assert (REPO_ROOT / "files" / "runtime-data" / "logs") in \
        set(conftest._GUARDED_PATHS.values())


# --------------------------------------------------------------------------- #
# B. The guard can actually detect a change
# --------------------------------------------------------------------------- #
def test_a_rewritten_file_changes_its_fingerprint(tmp_path):
    target = tmp_path / "stamp.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    before = conftest._fingerprint(target)

    target.write_text('{"a": 22}', encoding="utf-8")

    assert conftest._fingerprint(target) != before


def test_a_new_file_changes_a_watched_directorys_fingerprint(tmp_path):
    watched = tmp_path / "logs"
    watched.mkdir()
    before = conftest._fingerprint(watched)

    (watched / "setup_2026-09-03.log").write_text("run", encoding="utf-8")

    assert conftest._fingerprint(watched) != before


def test_a_missing_path_fingerprints_as_nothing_rather_than_raising(tmp_path):
    """A checkout with no .venv must not be a special case."""
    assert conftest._fingerprint(tmp_path / "not-here") is None


# --------------------------------------------------------------------------- #
# C. Isolation is actually in force during this very test
# --------------------------------------------------------------------------- #
def test_setup_logging_is_redirected_away_from_the_real_logs_directory():
    real = REPO_ROOT / "files" / "runtime-data" / "logs"
    assert bootstrap.LOGS_DIR != real
    assert paths.LOGS_DIR != real


def test_writing_a_setup_log_line_lands_in_the_sandbox():
    """Behavioural: the shared logger writes, and not into the real tree.

    The autouse guard re-checks the real log directory when this test ends, so
    if the redirect ever stopped working this test fails twice over.
    """
    bootstrap.LOG.line("phase-1 isolation probe")

    assert bootstrap.LOG.path.is_relative_to(bootstrap.LOGS_DIR)
    assert bootstrap.LOG.path.exists()
    assert "phase-1 isolation probe" in bootstrap.LOG.path.read_text(encoding="utf-8")


def test_importing_bootstrap_creates_no_log_file_of_its_own(tmp_path, monkeypatch):
    """The production half: constructing a SetupLog must touch no filesystem.

    This is what made every test that merely imported ``bootstrap`` append to the
    production log.
    """
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")

    log = bootstrap.SetupLog()

    assert not (tmp_path / "logs").exists()
    log.line("now it may exist")
    assert (tmp_path / "logs").is_dir()


def test_the_header_is_still_the_first_thing_written(tmp_path, monkeypatch):
    """Deferring the open must not reorder what a user reads in the log."""
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    log = bootstrap.SetupLog()

    log.line("first real line")

    text = log.path.read_text(encoding="utf-8")
    assert "===== Setup run" in text
    assert text.index("===== Setup run") < text.index("first real line")
    assert text.index("Repo root:") < text.index("first real line")


def test_the_run_header_is_written_once_per_logger(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    log = bootstrap.SetupLog()

    log.line("a")
    log.line("b")

    assert log.path.read_text(encoding="utf-8").count("===== Setup run") == 1
