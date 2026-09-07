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

import ast
import hashlib
import os
import sys
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------- #
# D. The stamp guard is content-aware, not just metadata-aware
#
# (size, mtime_ns) caught the accidental writer that was actually found, because
# rewriting the stamp moves its timestamp. It is not a content-integrity proof:
# a stamp falsified in place -- a different requirements_sha256 of the same
# length, with the timestamp put back -- is byte-different and metadata-identical.
# That is the shape a *false* success stamp would have, which is the thing this
# guard exists to catch, so the single-file fingerprint hashes content.
#
# The directory fingerprint deliberately does not hash: it covers the real logs
# directory, checked once per session, where anything written necessarily changes
# a size or a timestamp.
# --------------------------------------------------------------------------- #
def test_a_same_size_rewrite_with_a_restored_timestamp_is_still_caught(tmp_path):
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"requirements_sha256": "aaaa"}', encoding="utf-8")
    before_stat = stamp.stat()
    before = conftest._fingerprint(stamp)

    # Same length, different content -- a falsified stamp.
    stamp.write_text('{"requirements_sha256": "bbbb"}', encoding="utf-8")
    # ...and the timestamp put back, so metadata alone learns nothing.
    os.utime(stamp, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))

    after = conftest._fingerprint(stamp)

    assert stamp.stat().st_size == before_stat.st_size
    assert stamp.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert after != before, "a same-size, same-mtime content change slipped past"


def test_the_file_fingerprint_carries_a_content_hash(tmp_path):
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"a": 1}', encoding="utf-8")

    size, mtime_ns, digest = conftest._fingerprint(stamp)

    assert size == stamp.stat().st_size
    assert mtime_ns == stamp.stat().st_mtime_ns
    assert digest == hashlib.sha256(stamp.read_bytes()).hexdigest()


def test_identical_content_fingerprints_identically(tmp_path):
    """The guard must not cry wolf on a rewrite that changed nothing."""
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"a": 1}', encoding="utf-8")
    before = conftest._fingerprint(stamp)
    stat = stamp.stat()

    stamp.write_text('{"a": 1}', encoding="utf-8")
    os.utime(stamp, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert conftest._fingerprint(stamp) == before


def test_the_directory_fingerprint_stays_metadata_only(tmp_path):
    """Cost boundary: no hashing of the log tree."""
    watched = tmp_path / "logs"
    watched.mkdir()
    (watched / "setup.log").write_text("x", encoding="utf-8")

    entries = conftest._fingerprint(watched)

    assert entries == (("setup.log", 1, (watched / "setup.log").stat().st_mtime_ns),)


def test_the_guard_watches_the_real_import_proof():
    assert (REPO_ROOT / ".venv" / ".import-proof.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_both_venv_records_are_checked_around_every_test():
    """Per-test attribution for the two small files; the log tree is per-session."""
    per_test = set(conftest._PER_TEST_GUARDED)
    assert "the real requirements stamp" in per_test
    assert "the real import proof" in per_test
    assert "the real setup log directory" not in per_test


# --------------------------------------------------------------------------- #
# F. PRE-PLAN-6 Phase 6, row 17 — the FFmpeg state the guard used to miss
#
# Phases 3 to 5 gave the suite three more ways to write production state: the
# runtime pin, an installed build under files/bin, and the staging tree. None of
# them was guarded. That was not hypothetical — an intermediate Phase-5 run
# created files/runtime-data/ffmpeg-staging/9.0.1 and the suite did not notice;
# it was found by hand afterwards. The absence of those two trees is what
# Phase 7's real acceptance runs against, so absence is the thing protected.
# --------------------------------------------------------------------------- #
def test_the_guard_watches_the_real_ffmpeg_pin():
    assert (REPO_ROOT / "files" / "runtime-data" / "ffmpeg-state.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_installed_build():
    assert (REPO_ROOT / "files" / "bin") in set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_staging_tree():
    assert (REPO_ROOT / "files" / "runtime-data" / "ffmpeg-staging") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_ffmpeg_paths_are_attributed_to_the_test_that_touched_them():
    """Per-test, not per-session: a pin or a build has one culprit worth naming.

    Affordable because on a machine in the preserved condition both trees are
    absent, so the check is a single failed stat.
    """
    per_test = set(conftest._PER_TEST_GUARDED)
    assert "the real FFmpeg pin" in per_test
    assert "the real installed FFmpeg build" in per_test
    assert "the real FFmpeg staging tree" in per_test


def test_a_path_appearing_where_there_was_none_is_detected(tmp_path):
    """Absence is a value, not a gap. Creating the tree must compare unequal.

    This is the exact shape of the Phase-5 leak: nothing existed, then a
    directory did.
    """
    absent = tmp_path / "ffmpeg-staging"
    before = conftest._fingerprint(absent)
    assert before is None

    (absent / "9.0.1").mkdir(parents=True)

    assert conftest._fingerprint(absent) != before


def test_a_path_disappearing_is_detected(tmp_path):
    """The other direction: a guard that only catches writes is half a guard."""
    present = tmp_path / "bin"
    (present / "ffmpeg" / "9.0.1" / "bin").mkdir(parents=True)
    (present / "ffmpeg" / "9.0.1" / "bin" / "ffmpeg.exe").write_text(
        "x", encoding="utf-8")
    before = conftest._fingerprint(present)
    assert before is not None

    import shutil
    shutil.rmtree(present)

    assert conftest._fingerprint(present) != before


def test_a_change_deep_in_a_versioned_tree_cannot_hide(tmp_path):
    """``files/bin`` is ``ffmpeg/<version>/bin/ffmpeg.exe`` — three levels down.

    A single-level listing of ``files/bin`` would report the same tuple whether
    or not a whole FFmpeg build had appeared underneath it, because only the
    ``ffmpeg`` directory name is visible at the top. That is why the fingerprint
    recurses.
    """
    root = tmp_path / "bin"
    (root / "ffmpeg" / "9.0.1" / "bin").mkdir(parents=True)
    before = conftest._fingerprint(root)

    (root / "ffmpeg" / "9.0.1" / "bin" / "ffmpeg.exe").write_text(
        "binary", encoding="utf-8")

    assert conftest._fingerprint(root) != before, \
        "a build appearing three directories down was invisible to the guard"


def test_an_emptied_directory_does_not_look_like_an_absent_one(tmp_path):
    """Removing the only file must not fingerprint the same as never existing."""
    root = tmp_path / "staging"
    (root / "9.0.1").mkdir(parents=True)
    (root / "9.0.1" / "part").write_text("x", encoding="utf-8")
    populated = conftest._fingerprint(root)

    (root / "9.0.1" / "part").unlink()
    emptied = conftest._fingerprint(root)

    assert emptied != populated
    assert emptied is not None, "an existing empty tree read as absent"


def test_a_nested_empty_directory_is_itself_recorded(tmp_path):
    """A staging tree is created before anything lands in it, and that counts."""
    root = tmp_path / "staging"
    root.mkdir()
    before = conftest._fingerprint(root)

    (root / "9.0.1").mkdir()

    assert conftest._fingerprint(root) != before


def test_the_guard_reads_the_real_filesystem_not_a_patched_one(monkeypatch,
                                                               tmp_path):
    """A test that fakes ``os.scandir`` must not also fake what the guard sees.

    ``conftest`` captures the real ``os.scandir``/``os.stat`` at import, before
    any test can replace them. Without that, a module proving some walk
    tolerates a vanishing file would blind the guard for the duration.
    """
    target = tmp_path / "tree"
    target.mkdir()
    (target / "a").write_text("x", encoding="utf-8")
    expected = conftest._fingerprint(target)

    def exploding(*args, **kwargs):
        raise AssertionError("the guard used the monkeypatched os.scandir")

    monkeypatch.setattr(os, "scandir", exploding)

    assert conftest._fingerprint(target) == expected


# --------------------------------------------------------------------------- #
#  PRE-PLAN-6 Phase 7 — a fixture must not outlive itself
#
#  Phase 7 spent the preserved missing-FFmpeg condition, and two test-only
#  defects that the absence had been hiding turned red the moment a real pair
#  existed. Both are the same shape as the production-state defects above: state
#  that is process-wide, written by one test, and never given back.
#
#  1. ``test_m4b_probe_encoding`` sandboxed its whole module with a
#     ``pytestmark``, so the three tests whose entire purpose is to run a REAL
#     ffmpeg against a REAL generated book were handed a stub text file instead.
#  2. ``configure_pydub()`` writes into pydub's own module globals. Nothing
#     restored them, so a test that pinned a sandbox pair left pydub pointing
#     inside its ``tmp_path`` — which pytest then deleted — and the next consumer
#     to call ``AudioSegment.export`` inherited it. That consumer was
#     ``kokoro_synth``, which never calls ``configure_pydub()`` itself.
# --------------------------------------------------------------------------- #

PROBE_ENCODING = Path(__file__).parent / "test_m4b_probe_encoding.py"

#: The tests in that module that must run against the REAL proved pair.
REAL_MEDIA_TESTS = frozenset({
    "test_the_generated_book_really_defeats_the_ansi_codepage",
    "test_the_production_probe_reads_a_real_book_with_unicode_titles",
    "test_a_real_unicode_book_is_usable_rather_than_refused",
})


def _probe_encoding_tree() -> ast.Module:
    return ast.parse(PROBE_ENCODING.read_text(encoding="utf-8"))


def _sandbox_marks(node: ast.FunctionDef) -> list[str]:
    """Decorators on *node* that apply the sandbox pair, however they spell it.

    AST rather than substring matching, per the Phase-6 rule: the module-level
    alias means the mark can legitimately appear as a bare ``@sandboxed`` or as
    the full ``@pytest.mark.usefixtures("pinned_ffmpeg")``, and a docstring that
    merely mentions either is not a decorator.
    """
    found = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "sandboxed":
            found.append("sandboxed")
        elif isinstance(decorator, ast.Call):
            args = [a.value for a in decorator.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if "pinned_ffmpeg" in args:
                found.append(ast.unparse(decorator.func))
    return found


def test_the_probe_module_does_not_sandbox_itself_wholesale():
    """No module-level mark may apply the sandbox pair to every test in the file.

    This is the defect exactly: a ``pytestmark`` cannot be opted out of, so every
    real-media test added to that module afterwards is silently captured.
    """
    offenders = []
    for node in _probe_encoding_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "pytestmark" not in names:
            continue
        if "pinned_ffmpeg" in ast.unparse(node.value):
            offenders.append(ast.unparse(node))
    assert offenders == [], (
        "test_m4b_probe_encoding applies the sandbox pair module-wide again: "
        f"{offenders}")


def _module_level_sandbox() -> list[str]:
    """Any module-level ``pytestmark`` that applies the sandbox pair.

    Counted as applying to *every* test in the file, because that is what pytest
    does with it — which is the whole reason the original defect was invisible.
    """
    marks = []
    for node in _probe_encoding_tree().body:
        if (isinstance(node, ast.Assign)
                and any(t.id == "pytestmark" for t in node.targets
                        if isinstance(t, ast.Name))
                and "pinned_ffmpeg" in ast.unparse(node.value)):
            marks.append(ast.unparse(node))
    return marks


def test_the_real_media_tests_are_not_handed_a_stub():
    """The three generated-media tests must not receive the sandbox pair.

    Checked against both routes it can arrive by — a decorator on the test, and a
    module-level mark that reaches it without naming it.
    """
    captured = {}
    module_wide = _module_level_sandbox()
    for node in ast.walk(_probe_encoding_tree()):
        if isinstance(node, ast.FunctionDef) and node.name in REAL_MEDIA_TESTS:
            marks = _sandbox_marks(node) + module_wide
            if marks:
                captured[node.name] = marks
    assert captured == {}, (
        f"generated-media tests were handed the sandbox pair: {captured}")


def test_every_real_media_test_is_actually_present():
    """Guards the guard: a rename must not silently empty the set above."""
    defined = {node.name for node in ast.walk(_probe_encoding_tree())
               if isinstance(node, ast.FunctionDef)}
    missing = REAL_MEDIA_TESTS - defined
    assert missing == set(), f"REAL_MEDIA_TESTS names tests that no longer exist: {missing}"


def test_the_command_building_tests_still_get_a_pinned_pair():
    """Narrowing the scope must not have removed the pair the others need.

    ``probe_source`` builds its argv from ``ffprobe_cmd()`` before it consults an
    injected runner, so every test that reaches it needs *a* pinned pair even
    though it executes nothing. Those must still opt in explicitly.
    """
    unsandboxed = []
    for node in ast.walk(_probe_encoding_tree()):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_") or node.name in REAL_MEDIA_TESTS:
            continue
        calls = {sub.func.attr for sub in ast.walk(node)
                 if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)}
        if "probe_source" in calls and not _sandbox_marks(node):
            unsandboxed.append(node.name)
    assert unsandboxed == [], (
        "these build a probe command line but were left without a pinned pair: "
        f"{unsandboxed}")


def test_the_runtime_trust_boundary_is_still_pinned_only():
    """Narrowing fixture scope must not have reopened a bare-name fallback."""
    from shared import ffmpeg_utils as trust

    source = ast.parse(Path(trust.__file__).read_text(encoding="utf-8"))
    pair = next(node for node in ast.walk(source)
                if isinstance(node, ast.FunctionDef) and node.name == "_executable_pair")
    called = {sub.func.attr for sub in ast.walk(pair)
              if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)}
    assert "pinned_pair" in called
    assert "which" not in called and "discover_pairs" not in called


# --- the pydub guard, proved behaviourally ---------------------------------- #

_SANDBOX_SEEN: dict = {}


def _pydub_now() -> dict:
    from pydub import AudioSegment
    from pydub import utils as pydub_utils

    return {name: getattr(AudioSegment, name, None)
            for name in ("converter", "ffmpeg", "ffprobe")} | {
        "prober": pydub_utils.get_prober_name()}


def test_a_sandbox_pair_is_authoritative_while_its_fixture_is_active(pinned_ffmpeg):
    """Ordered first on purpose: it pollutes, the next test proves the cleanup."""
    from shared import ffmpeg_utils as trust

    _SANDBOX_SEEN["dir"] = str(Path(pinned_ffmpeg))
    trust.configure_pydub()
    assert Path(trust.ffmpeg_cmd()).parent == Path(pinned_ffmpeg)
    assert all(_SANDBOX_SEEN["dir"] in str(v) for v in _pydub_now().values())


def test_no_authority_still_points_into_the_torn_down_sandbox():
    """The whole defect, in one assertion, for both authorities at once."""
    from shared import ffmpeg_utils as trust

    sandbox = _SANDBOX_SEEN.get("dir")
    assert sandbox, "the polluting test above must run first"

    resolved = trust.ffmpeg_path()
    assert resolved is None or sandbox not in resolved, (
        f"ffmpeg_utils still resolves the torn-down sandbox: {resolved}")

    stale = {k: v for k, v in _pydub_now().items() if v and sandbox in str(v)}
    assert stale == {}, f"pydub still points into the torn-down sandbox: {stale}"


def test_the_pydub_guard_restores_absence_as_well_as_values(tmp_path):
    """Driving the guard directly, so it cannot pass by luck of ordering.

    ``AudioSegment.ffprobe`` does not exist until ``configure_pydub()`` creates
    it, so a guard that only reassigns attributes would leave it behind. Absence
    has to round-trip as its own answer — the same rule the production-state
    fingerprint above follows.
    """
    from pydub import AudioSegment

    guard = conftest._restore_pydub_configuration.__wrapped__
    had_ffprobe = hasattr(AudioSegment, "ffprobe")
    if had_ffprobe:
        del AudioSegment.ffprobe
    before = AudioSegment.converter
    try:
        generator = guard()
        next(generator)
        AudioSegment.converter = str(tmp_path / "bin" / "ffmpeg.exe")
        AudioSegment.ffprobe = str(tmp_path / "bin" / "ffprobe.exe")
        with pytest.raises(StopIteration):
            next(generator)
        assert AudioSegment.converter == before
        assert not hasattr(AudioSegment, "ffprobe"), (
            "the guard reassigns but never removes, so an attribute a test "
            "invented survives it")
    finally:
        AudioSegment.converter = before
        if had_ffprobe:
            AudioSegment.ffprobe = before


def test_the_pydub_guard_is_autouse_so_no_test_has_to_remember_it():
    """A guard every test must opt into is a guard someone will forget."""
    fixture = conftest._restore_pydub_configuration
    # pytest 8 exposes the marker on a FixtureFunctionDefinition; older releases
    # attached it to the function itself. Ask for both rather than pin a version.
    marker = getattr(fixture, "_fixture_function_marker",
                     getattr(fixture, "_pytestfixturefunction", None))
    assert marker is not None, "the pydub guard is no longer a pytest fixture"
    assert marker.autouse is True
    assert marker.scope == "function"


def test_a_stand_in_pydub_is_left_alone():
    """Some fixtures inject a fake pydub; the guard must no-op for those."""
    sentinel = object()
    saved = sys.modules.get("pydub.utils")
    sys.modules["pydub.utils"] = sentinel  # type: ignore[assignment]
    try:
        assert conftest._pydub_modules() is None
        assert conftest._pydub_snapshot() is None
    finally:
        if saved is None:
            del sys.modules["pydub.utils"]
        else:
            sys.modules["pydub.utils"] = saved
