"""Numbering — Plan 5, Phase 12.

Decision 5 says three numbers appear in a run and they are not one counter. Two
are structural and were frozen into the plan long before anything was written: a
split output's filename prefix and its ``track`` are both its position inside
its own book. The third is the only one that interacts with success — the
sequential ``track`` a **whole book** carries when *Auto-number tracks* is on —
and Phase 12 is where it stops being positional and starts being earned.

What these tests are actually protecting
----------------------------------------
1. **No gaps (28A).** Three books, the middle one fails: the third is number
   **2**. The transitional Phase 11 behaviour would have made it 3.
2. **Nothing is consumed by a failure**, a drift breach, an occupied
   destination, a cancellation, or an item preflight already refused.
3. **Asking is free.** The number must exist before ffmpeg runs, because it is
   written into the file — but reading it may not advance anything. Proposing
   and committing are separate calls, and committing twice is an error rather
   than a quietly skipped number.
4. **The other two numbers never move.** A book that fails cannot renumber
   another book's chapters, and ``Start #`` and *Auto-number* have no effect on
   a split run at all.
5. **Split mode is excluded by the run's mode, not by the item's shape.** A
   chapterless book in split mode is planned as a single non-fragment output, so
   an implementation keyed off ``item.fragment`` would number it. This one keys
   off ``plan.mode``, and that difference is tested directly.

Determinism
-----------
No test sleeps. Runs go through the production worker with the process seam
stubbed, so the real executor still builds real commands and finalises real
files; the generated-media section then reads the tracks back out of actual
MP3s with ffprobe.

Safety
------
No repository media and no private fixtures. ffmpeg's absence **fails** rather
than skips.
"""

from __future__ import annotations

import ast
import unittest.mock as mock
from pathlib import Path

import pytest

import tkinter as tk

from shared import job_control as jc
from shared import output_paths

from mp3_tools import m4b_converter, m4b_execution, m4b_numbering
from mp3_tools.m4b_execution import ProcessResult
from mp3_tools.m4b_metadata import MetadataMode, SourceTags
from mp3_tools.m4b_numbering import NumberingError, SuccessNumbers, Tentative
from mp3_tools.m4b_plan import ConversionMode

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    _reservation,
    book,
    chapters,
    install_conversion_stubs,
    report,
)
from test_m4b_execution import _probe, _tags, media  # noqa: E402,F401
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal" / "mp3_tools"
PANEL_SOURCE = UNIVERSAL / "m4b_converter.py"
NUMBERING_SOURCE = UNIVERSAL / "m4b_numbering.py"
PLAN_SOURCE = UNIVERSAL / "m4b_plan.py"


# --------------------------------------------------------------------------- #
# The pure allocator
# --------------------------------------------------------------------------- #


def test_it_starts_exactly_where_it_was_told_to():
    for start in (1, 7, 100):
        assert SuccessNumbers(start).next_number == start
        assert SuccessNumbers(start).consumed == 0


def test_proposing_advances_nothing():
    """The whole reason the API has two calls."""
    numbers = SuccessNumbers(1)
    assert numbers.propose().number == 1
    assert numbers.propose().number == 1
    assert numbers.propose().number == 1
    assert numbers.next_number == 1 and numbers.consumed == 0


def test_committing_advances_exactly_once():
    numbers = SuccessNumbers(1)
    assert numbers.commit(numbers.propose()) == 1
    assert numbers.next_number == 2 and numbers.consumed == 1


def test_an_abandoned_proposal_costs_nothing():
    """A failure is simply a proposal nobody confirmed."""
    numbers = SuccessNumbers(1)
    numbers.propose()          # the book that failed
    numbers.propose()          # and the next one asks again
    assert numbers.next_number == 1
    assert numbers.commit(numbers.propose()) == 1


def test_the_same_tentative_cannot_be_confirmed_twice():
    numbers = SuccessNumbers(1)
    tentative = numbers.propose()
    numbers.commit(tentative)
    with pytest.raises(NumberingError):
        numbers.commit(tentative)
    assert numbers.next_number == 2, "the refused commit moved nothing"


def test_a_number_this_counter_never_offered_is_refused():
    numbers = SuccessNumbers(5)
    with pytest.raises(NumberingError):
        numbers.commit(Tentative(9))
    assert numbers.next_number == 5


def test_commit_takes_the_token_not_a_bare_number():
    numbers = SuccessNumbers(1)
    with pytest.raises(TypeError):
        numbers.commit(1)


def test_a_start_that_is_not_an_int_is_refused():
    for bad in ("1", 1.5, None, True):
        with pytest.raises(TypeError):
            SuccessNumbers(bad)


def test_the_start_is_not_re_clamped_here():
    """What counts as a usable Start # was decided when the run was frozen.

    Re-deciding it in a second place is how two answers to one question appear,
    so this takes what it is given.
    """
    assert SuccessNumbers(0).next_number == 0
    assert SuccessNumbers(-3).next_number == -3


def test_the_worked_sequence_from_the_decision(tmp_path):
    """A succeeds -> 1 · B fails -> nothing · C succeeds -> 2. No gap."""
    numbers = SuccessNumbers(1)
    a = numbers.commit(numbers.propose())
    numbers.propose()                       # B is attempted and fails
    c = numbers.commit(numbers.propose())
    assert (a, c) == (1, 2)
    assert numbers.consumed == 2


def test_a_later_retry_could_continue_from_the_consumed_count():
    """Phase 13's rule is expressible; it is deliberately **not** wired here.

    A succeeds -> 1, B fails, C succeeds -> 2, and a later retry of B would take
    3. This proves the counter can continue, and nothing in this phase connects
    it to a real Retry Failed run.
    """
    numbers = SuccessNumbers(1)
    numbers.commit(numbers.propose())       # A
    numbers.propose()                       # B fails
    numbers.commit(numbers.propose())       # C
    assert numbers.commit(numbers.propose()) == 3



def test_the_allocator_is_pure():
    """AST, not substring: prose about retries legitimately says "retry"."""
    tree = ast.parse(NUMBERING_SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "dataclasses"}, roots

    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for forbidden in ("Tk", "StringVar", "Path", "open", "run", "popen",
                      "ConversionPlan", "SegmentPlan", "ItemPlan",
                      "whole_book_tags", "segment_tags", "ffmpeg_cmd"):
        assert forbidden not in named, forbidden

def test_no_mutable_numbering_state_lives_in_the_plan():
    """The plan is immutable and is what a retry re-reads; a counter is not."""
    from mp3_tools.m4b_plan import ConversionPlan, ItemPlan, SegmentPlan

    for kind in (ConversionPlan, ItemPlan, SegmentPlan):
        for field in kind.__dataclass_fields__:
            assert "counter" not in field and "allocator" not in field, (kind, field)
    assert "SuccessNumbers" not in PLAN_SOURCE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Panel fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def make_panel(tk_root):
    made: list = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("bridge", jc.LoggerBridge(logger=_Silent()))
        panel = m4b_converter.M4BConverterUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


@pytest.fixture()
def run_env(monkeypatch):
    return install_conversion_stubs(monkeypatch, {})


def add(panel, *paths: Path):
    panel.importer._choose_files = lambda: tuple(str(p) for p in paths)
    return panel.importer.add_files()


def start(panel):
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def convert(panel, tmp_path):
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return panel.run_plan


def tracks_written(run_env) -> list:
    """The ``track=`` value in every command the executor actually built."""
    found = []
    for argv in run_env["commands"]:
        if "-metadata" in argv:
            for position, part in enumerate(argv):
                if part.startswith("track="):
                    found.append(int(part.split("=", 1)[1]))
    return found


def track_for(run_env, source_name: str):
    """The track written for the command that reads *source_name*, or None."""
    for argv in run_env["commands"]:
        if source_name not in " ".join(argv):
            continue
        for part in argv:
            if part.startswith("track="):
                return int(part.split("=", 1)[1])
        return None
    raise AssertionError(f"{source_name} was never converted")


def whole_panel(make_panel, tmp_path, run_env, *names, start_number=1,
                auto=True, metadata=MetadataMode.PRESERVE):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", name) for name in names])
    panel.var_auto_num.set(auto)
    panel.var_start_num.set(start_number)
    panel.var_metadata_mode.set(metadata.value)
    run_env["default_report"] = report(duration=600.0, tags=SourceTags())
    return panel


def fail_sources(run_env, *names):
    """Make exactly the commands reading *names* fail."""
    def outcome(joined):
        line = " ".join(joined)
        return (ProcessResult(1, detail="ffmpeg said no")
                if any(name in line for name in names) else None)
    run_env["outcome"] = outcome


# --------------------------------------------------------------------------- #
# Whole-book runs: the sequences the decision names
# --------------------------------------------------------------------------- #


def test_a_clean_whole_run_numbers_consecutively(make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1, 2, 3]
    assert panel.run_result.succeeded_count == 3


def test_a_failure_in_the_middle_leaves_no_gap(make_panel, tmp_path, run_env):
    """**The whole point of Phase 12.** A -> 1, B fails, C -> 2, not 3."""
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")
    fail_sources(run_env, "B.m4b")
    convert(panel, tmp_path)

    assert track_for(run_env, "A.m4b") == 1
    assert track_for(run_env, "B.m4b") == 2, "B was attempted with the next number"
    assert track_for(run_env, "C.m4b") == 2, "and C reuses it because B consumed nothing"
    assert panel.run_result.succeeded_count == 2
    assert panel.run_result.failed_count == 1

    plan = panel.run_plan
    survivors = sorted(p.name for p in plan.run_directory.iterdir())
    assert survivors == ["A.mp3", "C.mp3"], "B left no output at all"


def test_failures_first_still_start_at_the_start_number(make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")
    fail_sources(run_env, "A.m4b", "B.m4b")
    convert(panel, tmp_path)
    assert track_for(run_env, "C.m4b") == 1, "the first success takes Start #"
    assert panel.run_result.succeeded_count == 1


def test_consecutive_failures_create_no_gaps(make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env,
                        "A.m4b", "B.m4b", "C.m4b", "D.m4b", "E.m4b")
    fail_sources(run_env, "B.m4b", "C.m4b")
    convert(panel, tmp_path)
    assert track_for(run_env, "A.m4b") == 1
    assert track_for(run_env, "D.m4b") == 2
    assert track_for(run_env, "E.m4b") == 3


def test_a_non_default_start_number_is_honoured(make_panel, tmp_path, run_env):
    """Start # 7 -> 7, B fails, C -> 8, D -> 9."""
    panel = whole_panel(make_panel, tmp_path, run_env,
                        "A.m4b", "B.m4b", "C.m4b", "D.m4b", start_number=7)
    fail_sources(run_env, "B.m4b")
    convert(panel, tmp_path)
    assert track_for(run_env, "A.m4b") == 7
    assert track_for(run_env, "C.m4b") == 8
    assert track_for(run_env, "D.m4b") == 9


def test_an_unusable_item_never_receives_or_consumes_a_number(
        make_panel, tmp_path, run_env):
    """Preflight refused it, so it is not an attempt at all."""
    from mp3_tools.m4b_chapters import ProbeStatus

    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")
    run_env["reports"]["B.m4b"] = report(status=ProbeStatus.PROBE_FAILED,
                                         duration=None)
    convert(panel, tmp_path)
    assert track_for(run_env, "A.m4b") == 1
    assert track_for(run_env, "C.m4b") == 2
    assert not any("B.m4b" in " ".join(argv) for argv in run_env["commands"])


def test_a_drift_breach_consumes_nothing(make_panel, tmp_path, run_env,
                                         monkeypatch):
    """A file that was written but failed validation is not a success."""
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")
    # Only B measures wrong, so only B breaches the 3% guard.
    seen: list = []

    def measure(path):
        seen.append(Path(path))
        return 1.0 if len(seen) == 2 else None

    monkeypatch.setattr(m4b_converter, "measured_duration", measure)
    convert(panel, tmp_path)

    assert track_for(run_env, "C.m4b") == 2, "the discarded book consumed nothing"
    assert panel.run_result.failed_count == 1
    assert sorted(p.name for p in panel.run_plan.run_directory.iterdir()) == [
        "A.mp3", "C.mp3"]



def test_an_occupied_destination_consumes_nothing(make_panel, tmp_path, run_env):
    """The destination has to be taken *after* planning, or the planner sidesteps it.

    Creating the file up front does not exercise this path at all: the shared
    planner sees it during preflight and plans ``B-1.mp3`` instead, which is the
    collision guard doing its job. So the name is claimed while the run is
    already under way, which is the only way the finalisation guard is reached.
    """
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")

    def outcome(joined):
        if "B.m4b" in " ".join(joined):
            planned = tmp_path / "run-1" / "B.mp3"
            planned.parent.mkdir(parents=True, exist_ok=True)
            planned.write_text("something else got here first", encoding="utf-8")
        return None

    run_env["outcome"] = outcome
    convert(panel, tmp_path)

    assert track_for(run_env, "C.m4b") == 2, "the refused book consumed nothing"
    assert panel.run_result.failed_count == 1
    assert (tmp_path / "run-1" / "B.mp3").read_text(encoding="utf-8") == (
        "something else got here first")

def test_an_earlier_success_keeps_its_number_when_a_later_book_fails(
        make_panel, tmp_path, run_env):
    """No batch rollback: a consumed number is never given back."""
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    fail_sources(run_env, "B.m4b")
    convert(panel, tmp_path)
    assert track_for(run_env, "A.m4b") == 1
    assert (panel.run_plan.run_directory / "A.mp3").exists()


# --------------------------------------------------------------------------- #
# Auto-number off, and the metadata modes
# --------------------------------------------------------------------------- #


def test_auto_number_off_introduces_no_sequential_track(make_panel, tmp_path,
                                                        run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", auto=False)
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [], "nothing sequential was written"
    assert panel.run_result.succeeded_count == 2


def test_auto_number_off_does_not_strip_a_preserved_source_track(
        make_panel, tmp_path, run_env):
    """Phase 12 owns the sequential override, not source-tag policy."""
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", auto=False)
    run_env["default_report"] = report(duration=600.0,
                                       tags=SourceTags(album="A", track=5))
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [5], "the source's own track survived"


def test_auto_number_on_overrides_a_preserved_source_track(make_panel, tmp_path,
                                                           run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b")
    run_env["default_report"] = report(duration=600.0,
                                       tags=SourceTags(album="A", track=5))
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1]


def test_replace_carries_the_sequential_track(make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b",
                        metadata=MetadataMode.REPLACE)
    panel.album_entry.insert(0, "Chosen")
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1, 2]


def test_strip_is_never_given_a_track(make_panel, tmp_path, run_env):
    """Truly empty stays truly empty, whatever the allocator would have said."""
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b",
                        metadata=MetadataMode.STRIP)
    convert(panel, tmp_path)
    assert tracks_written(run_env) == []
    for argv in run_env["commands"]:
        assert "-metadata" not in argv


# --------------------------------------------------------------------------- #
# Split: the two structural numbers, untouched
# --------------------------------------------------------------------------- #


def split_panel(make_panel, tmp_path, run_env, *names, start_number=1, auto=True):
    panel = make_panel()
    add(panel, *[book(tmp_path / "src", name) for name in names])
    panel.var_mode.set(ConversionMode.SPLIT.value)
    panel.var_auto_num.set(auto)
    panel.var_start_num.set(start_number)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    return panel


def test_split_tracks_are_structural_and_restart_per_book(make_panel, tmp_path,
                                                          run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1, 2, 3, 1, 2, 3]


def test_the_start_number_has_no_effect_on_a_split_run(make_panel, tmp_path,
                                                       run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", start_number=7)
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1, 2, 3]


def test_auto_number_has_no_effect_on_a_split_run(make_panel, tmp_path, run_env):
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", auto=False)
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1, 2, 3], (
        "structural tracks are not the auto-number feature")


def test_another_books_failure_cannot_renumber_a_split_books_chapters(
        make_panel, tmp_path, run_env):
    """19A/47A: a failure elsewhere never touches an item's internal order."""
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    fail_sources(run_env, "A.m4b")
    convert(panel, tmp_path)

    written = [argv for argv in run_env["commands"] if "B.m4b" in " ".join(argv)]
    numbers = [int(p.split("=", 1)[1]) for argv in written for p in argv
               if p.startswith("track=")]
    assert numbers == [1, 2, 3]



def test_split_filenames_keep_their_structural_prefix(make_panel, tmp_path,
                                                      run_env):
    """Phase 12 is metadata only: no output is renamed by success or failure.

    The surviving book's names carry a ``-1`` because the failed book's names
    were planned first in the run's one shared collision domain -- that is
    Phase 8 behaviour and it is deliberately left alone. What matters here is
    that the **structural order prefix** is untouched: 01, 02, 03, in order.
    """
    panel = split_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    fail_sources(run_env, "A.m4b")
    plan = convert(panel, tmp_path)

    produced = sorted(p.name for p in plan.run_directory.iterdir())
    assert len(produced) == 3
    assert [name[:2] for name in produced] == ["01", "02", "03"]
    assert all("Chapter" in name for name in produced), produced

def test_whole_filenames_are_never_prefixed_with_the_success_number(
        make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b")
    plan = convert(panel, tmp_path)
    assert sorted(p.name for p in plan.run_directory.iterdir()) == [
        "A.mp3", "B.mp3"]


# --------------------------------------------------------------------------- #
# The chapterless split fallback — excluded by the run's mode
# --------------------------------------------------------------------------- #


def test_a_chapterless_split_item_gets_no_whole_run_success_number(
        make_panel, tmp_path, run_env):
    """The case an ``item.fragment`` test would have got wrong.

    A chapterless book in split mode is planned as **one non-fragment** output,
    so keying eligibility off the item would number it. Auto-numbering does not
    apply in split mode, so the run's mode is what decides.
    """
    panel = make_panel()
    add(panel, book(tmp_path / "src", "Quiet.m4b"))
    panel.var_mode.set(ConversionMode.SPLIT.value)
    panel.var_auto_num.set(True)
    panel.var_start_num.set(1)
    run_env["default_report"] = report(duration=600.0)      # no chapters at all

    plan = convert(panel, tmp_path)
    item = plan.items[0]
    assert item.fragment is False, "the Phase 10 shape is unchanged"
    assert len(item.segments) == 1
    assert item.segments[0].destination.name == "Quiet.mp3"
    assert tracks_written(run_env) == [], "no whole-run sequence number was applied"


def test_a_chapterless_whole_item_does_get_one(make_panel, tmp_path, run_env):
    """The mirror image, so the previous test cannot pass for the wrong reason."""
    panel = whole_panel(make_panel, tmp_path, run_env, "Quiet.m4b")
    convert(panel, tmp_path)
    assert tracks_written(run_env) == [1]


# --------------------------------------------------------------------------- #
# Cancellation and frozen configuration
# --------------------------------------------------------------------------- #


def test_a_cancelled_item_consumes_nothing(make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b", "C.m4b")

    def outcome(joined):
        if "B.m4b" in " ".join(joined):
            panel.cancel()
            return ProcessResult(None, cancelled=True)
        return None

    run_env["outcome"] = outcome
    convert(panel, tmp_path)

    assert track_for(run_env, "A.m4b") == 1
    assert track_for(run_env, "B.m4b") == 2, "attempted with the next number"
    assert panel.job_controller.state is jc.JobState.CANCELLED
    # A kept its number; B consumed nothing and left no output.
    assert sorted(p.name for p in panel.run_plan.run_directory.iterdir()) == ["A.mp3"]


def test_editing_the_widgets_after_start_cannot_change_allocation(
        make_panel, tmp_path, run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", "B.m4b",
                        start_number=3)
    params = start(panel)

    panel.var_start_num.set(99)
    panel.var_auto_num.set(False)

    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()

    assert tracks_written(run_env) == [3, 4], "the run used its frozen copy"
    assert params["options"].start_number == 3
    assert params["options"].auto_number is True


def test_the_allocator_is_built_from_the_frozen_plan(make_panel, tmp_path,
                                                     run_env):
    panel = whole_panel(make_panel, tmp_path, run_env, "A.m4b", start_number=4)
    plan = convert(panel, tmp_path)
    assert plan.start_number == 4 and plan.auto_number is True
    assert tracks_written(run_env) == [4]


# --------------------------------------------------------------------------- #
# Generated media — the tracks that are really written into the files
# --------------------------------------------------------------------------- #


def real_panel(make_panel, monkeypatch, tmp_path, *sources, **kwargs):
    """A panel wired to the real executor: only the thread is stubbed."""
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda t: None)
    panel = make_panel()
    add(panel, *sources)
    panel.var_auto_num.set(kwargs.get("auto", True))
    panel.var_start_num.set(kwargs.get("start_number", 1))
    panel.var_metadata_mode.set(kwargs.get("metadata", MetadataMode.PRESERVE).value)
    if kwargs.get("split"):
        panel.var_mode.set(ConversionMode.SPLIT.value)
    return panel


class _ThreadShim:
    """``threading`` with only ``Thread`` replaced; everything else is real."""

    Thread = StubThread

    def __getattr__(self, name):
        import threading
        return getattr(threading, name)


def track_of(path: Path):
    """The bare track number ffprobe reads back from a produced MP3."""
    tags = {key.lower(): value for key, value in _tags(path).items()}
    raw = tags.get("track")
    return None if raw in (None, "") else int(str(raw).split("/")[0])


def test_real_whole_outputs_carry_their_sequential_tracks(media, tmp_path,
                                                          make_panel, monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path,
                       media["plain"], media["cover"])
    plan = convert(panel, tmp_path)
    produced = sorted(plan.run_directory.iterdir())
    assert len(produced) == 2
    assert [track_of(p) for p in produced] == [1, 2]



def test_a_real_failure_leaves_no_gap_in_the_produced_files(
        media, tmp_path, make_panel, monkeypatch):
    """The canonical A/B/C sequence, read back off real MP3s.

    The middle book is a file that is not media at all, so preflight refuses it
    and it never becomes an attempt -- which is the strongest form of "consumes
    nothing".
    """
    broken = tmp_path / "src" / "Broken.m4b"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("this is not an audiobook", encoding="utf-8")

    panel = real_panel(make_panel, monkeypatch, tmp_path,
                       media["plain"], broken, media["cover"])
    plan = convert(panel, tmp_path)

    produced = {p.name: track_of(p) for p in plan.run_directory.iterdir()}
    assert set(produced) == {"NoCover.mp3", "WithCover.mp3"}, produced
    assert sorted(produced.values()) == [1, 2], produced
    assert 3 not in produced.values(), "no successful output carries a gapped number"
    assert not (plan.run_directory / "Broken.mp3").exists()
    assert panel.run_result.failed_count == 1

def test_a_real_non_default_start_number_is_written(media, tmp_path, make_panel,
                                                    monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path,
                       media["plain"], media["cover"], start_number=7)
    plan = convert(panel, tmp_path)
    assert sorted(track_of(p) for p in plan.run_directory.iterdir()) == [7, 8]


def test_real_auto_number_off_writes_no_sequential_track(media, tmp_path,
                                                         make_panel, monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path, media["plain"],
                       auto=False)
    plan = convert(panel, tmp_path)
    produced = list(plan.run_directory.iterdir())
    assert len(produced) == 1
    # The generated fixture carries track 3/9; Preserve keeps the 3 and the
    # total is discarded, exactly as Phase 6 settled it.
    assert track_of(produced[0]) == 3


def test_real_strip_output_carries_no_track_at_all(media, tmp_path, make_panel,
                                                   monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path, media["plain"],
                       metadata=MetadataMode.STRIP)
    plan = convert(panel, tmp_path)
    produced = list(plan.run_directory.iterdir())
    assert len(produced) == 1
    assert track_of(produced[0]) is None


def test_real_replace_output_carries_the_sequential_track(media, tmp_path,
                                                          make_panel, monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path, media["plain"],
                       media["cover"], metadata=MetadataMode.REPLACE)
    panel.album_entry.insert(0, "Chosen Album")
    plan = convert(panel, tmp_path)
    assert sorted(track_of(p) for p in plan.run_directory.iterdir()) == [1, 2]


def test_real_split_fragments_carry_structural_tracks(media, tmp_path, make_panel,
                                                      monkeypatch):
    panel = real_panel(make_panel, monkeypatch, tmp_path, media["cover"],
                       split=True, start_number=7)
    plan = convert(panel, tmp_path)
    produced = sorted(plan.run_directory.iterdir())
    assert [p.name for p in produced] == [
        "01 - Ch One.mp3", "02 - Ch Two.mp3", "03 - Ch Three.mp3"]
    assert [track_of(p) for p in produced] == [1, 2, 3], (
        "Start # 7 must not reach a split book's chapters")


# --------------------------------------------------------------------------- #
# Boundaries
# --------------------------------------------------------------------------- #


def test_the_positional_allocation_is_gone():
    """**A deliberate progression.** Phase 11 numbered by position on purpose.

    That transitional branch produced a gap whenever an earlier book failed, and
    Phase 12 is the phase authorized to retire it. The guard is turned around
    rather than deleted: it now proves the positional form is absent *and* that
    the success-only allocator is present.
    """
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "start_number + index" not in source
    tree = ast.parse(source)
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    named |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "SuccessNumbers" in named
    assert "propose" in named and "commit" in named


def test_the_allocator_is_only_created_for_a_whole_run():
    """Eligibility is the run's mode, never the item's shape."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    call = next(node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "SuccessNumbers")
    guard = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.IfExp)
                 and any(inner is call for inner in ast.walk(node)))
    condition = ast.unparse(guard.test)
    assert "plan.auto_number" in condition
    assert "plan.split" in condition
    assert "fragment" not in condition, (
        "a chapterless split item is non-fragment and must not be numbered")



def test_retry_failed_is_still_not_wired():
    """Structural on both files: the panel wires nothing, the allocator calls nothing."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "set_result" not in called
    keywords = {keyword.arg for node in ast.walk(tree)
                if isinstance(node, ast.Call) for keyword in node.keywords}
    assert "on_retry" not in keywords

    numbering = ast.parse(NUMBERING_SOURCE.read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(numbering)
               if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("retry", "retry_failed", "RetryRequest", "resume"):
        assert banned not in defined, banned

def test_phase_twelve_touched_no_execution_contract():
    """Numbering is a narrow layer around one metadata value."""
    execution = (UNIVERSAL / "m4b_execution.py").read_text(encoding="utf-8")
    assert "SuccessNumbers" not in execution
    assert "m4b_numbering" not in execution
    assert "auto_number" not in execution and "start_number" not in execution
