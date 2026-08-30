"""Retry Failed — Plan 5, Phase 13: a new attempt at the *same* frozen run.

What this phase actually had to settle
--------------------------------------
The drop's §11.2 called a preflight-unusable item "typed, **retryable**, nothing
written", and §21 said Retry Failed "re-executes the frozen ``ConversionPlan``
for failed items only, reusing the destinations planned at the original Start".
Those two cannot both be honoured: a source refused during preflight has **no**
``ItemPlan``, **no** frozen ``SegmentPlan``, **no** frozen destination, and once
Start-time planning is over the run's collision planner is gone. Retrying it in
place could only proceed by re-probing it, rebuilding the plan, or planning it a
destination after Start — each of which §7/§8 forbid.

The maintainer corrected the contract (Option A):

* a preflight/structural failure stays **typed**, stays **visible**, stays
  **non-fatal**, writes nothing — and is **not** a Retry Failed candidate;
* an execution failure, which by definition *has* an executable plan entry and
  frozen destinations, stays retryable;
* a corrected source comes back through a **new run**, which probes and plans it
  normally.

So the load-bearing invariant of this module is one line:

    result.retryable_ids ⊆ {item.occurrence_id for item in plan.items}

Everything else follows from it. A retry never decides anything: it re-executes
frozen answers at frozen names, and folds what happened into what the run already
knew.

Determinism and safety
----------------------
No test sleeps. The worker is run explicitly — inline for almost everything, and
on real joinable threads for the pause/cancel/close races, which wait only on
real signals with a bounded timeout so a run that never arrives fails loudly
rather than hanging. Clocks are injected. Every ``.m4b`` outside the generated
media section is a placeholder under ``tmp_path`` and every media seam is stubbed;
the generated-media section builds its own tiny sources with a real ffmpeg and
reads the results back with a real ffprobe. No repository media, no private
fixtures, and ffmpeg's absence **fails** rather than skips.
"""

from __future__ import annotations

import ast
import hashlib
import threading
import unittest.mock as mock
from pathlib import Path

import pytest

# Imported outright rather than through ``importorskip``: Plan 5 is fail-loud.
import tkinter as tk

from shared import job_control as jc
from shared import output_paths

from mp3_tools import m4b_converter, m4b_execution
from mp3_tools.m4b_chapters import ProbeStatus
from mp3_tools.m4b_execution import ProcessResult
from mp3_tools.m4b_metadata import MetadataMode
from mp3_tools.m4b_plan import ConversionMode
from mp3_tools.m4b_probe import ArtworkProblem

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
from test_m4b_converter_importing import add_files, books  # noqa: E402
from test_m4b_execution import _probe, _tags, media  # noqa: E402,F401
from test_m4b_numbering import (  # noqa: E402
    _ThreadShim, track_for, track_of, tracks_written,
)
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py"
PLAN_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_plan.py"

#: Every wait here is bounded, so a deadlock fails rather than hangs.
WAIT = 5.0

RealThread = threading.Thread


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class Clock:
    def __init__(self, step: float = 1.0):
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class Silent:
    """Stands in for the one session logger, so no log file is opened."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def make_panel(tk_root):
    made: list[m4b_converter.M4BConverterUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", Clock())
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("bridge", jc.LoggerBridge(logger=Silent()))
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


def start(panel):
    panel.start_convert()
    assert StubThread.started, "the worker was never handed a run"
    return StubThread.started[-1].args[0]


def work(panel, tmp_path, run_env):
    """Start a run, execute its worker inline, then drain the pump once."""
    params = start(panel)
    with mock.patch.object(output_paths, "reserve_run_directory",
                           side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return params


def retry(panel):
    """Press the **shared** Retry Failed control and run the attempt inline.

    ``reserve_run_directory`` is replaced by something that raises rather than by
    a working stub: a retry that reserved a directory would be a retry that had
    started planning again, and that must fail the test rather than pass quietly.
    """
    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True, (
        "Retry Failed was not available")
    params = StubThread.started[-1].args[0]
    with mock.patch.object(
            output_paths, "reserve_run_directory",
            side_effect=AssertionError("a retry reserved a run directory")):
        panel.convert_worker(params)
    panel._pump.tick()
    return params


def available(panel) -> bool:
    return panel.jobs.controls.availability()[jc.JobAction.RETRY_FAILED]


def whole(panel, *sources, start_number=1, auto=True, split=False,
          metadata=MetadataMode.PRESERVE):
    add_files(panel, *sources)
    panel.var_auto_num.set(auto)
    panel.var_start_num.set(start_number)
    panel.var_metadata_mode.set(metadata.value)
    if split:
        panel.var_mode.set(ConversionMode.SPLIT.value)
    return panel


def ids(panel) -> dict:
    """Occurrence id by source file name, for readable assertions."""
    return {entry.path.name: entry.occurrence_id
            for entry in panel.run_snapshot.files.files}


def parse_panel() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))


def function(name: str) -> ast.FunctionDef:
    for node in ast.walk(parse_panel()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in the panel")


def named(tree: ast.AST) -> set[str]:
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    return found


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def destinations_written(run_env) -> list:
    """The **final** path every built command was heading for, in order.

    Phase 11 never writes to a final name: each pass writes a temporary sibling
    called ``.act-tmp-<stem>-<token><suffix>`` in the destination's own folder and
    installs it afterwards. Only the token varies, so the frozen name is
    recovered by dropping the prefix and the token -- which is what lets these
    tests assert the destination a retry aimed at, not merely the one it hit.
    """
    found = []
    for argv in run_env["commands"]:
        path = Path(argv[-1])
        name = path.name
        if name.startswith(output_paths.TEMP_SIBLING_PREFIX):
            stem = name[len(output_paths.TEMP_SIBLING_PREFIX):]
            if stem.endswith(path.suffix):
                stem = stem[:-len(path.suffix)]
            name = stem.rsplit("-", 1)[0] + path.suffix
        found.append(path.with_name(name))
    return found


def sources_read(run_env) -> list:
    """The source each built command was given, in order."""
    return [Path(argv[argv.index("-i") + 1]) for argv in run_env["commands"]
            if "-i" in argv]


# --------------------------------------------------------------------------- #
# The corrected contract: what is retryable, and what is not
# --------------------------------------------------------------------------- #


UNUSABLE_CASES = {
    "probe_failed": dict(status=ProbeStatus.PROBE_FAILED, duration=None),
    "no_duration": dict(status=ProbeStatus.NO_DURATION, duration=None),
    "no_audio": dict(status=ProbeStatus.NO_AUDIO, duration=None),
    "duplicate_starts": dict(duration=600.0, chapter_list=chapters(0.0, 100.0, 100.0)),
    "non_monotonic": dict(duration=600.0, chapter_list=chapters(0.0, 300.0, 100.0)),
    "negative_start": dict(duration=600.0, chapter_list=chapters(-5.0, 100.0)),
    "start_past_duration": dict(duration=600.0, chapter_list=chapters(0.0, 900.0)),
    # Phase 6 fails closed on several embedded covers rather than choosing one.
    # It reaches ``plan.unusable`` through its own branch, which is exactly why
    # it is asserted here rather than assumed to follow from the chapter cases.
    "artwork_ambiguous": dict(
        duration=600.0,
        artwork=ArtworkProblem(message="This file has more than one cover.",
                               detail="2 attached pictures")),
}


@pytest.fixture(params=sorted(UNUSABLE_CASES))
def unusable(request):
    """One preflight-unusable shape per parameter, named by what is wrong."""
    return request.param, UNUSABLE_CASES[request.param]


def test_every_preflight_unusable_reason_is_typed_and_not_retryable(
        make_panel, tmp_path, run_env, unusable):
    """**The Phase 13 contract correction, proved reason by reason.**

    Not one representative case: every branch that can produce an ``ItemFailure``
    is driven separately, because "retryable" arriving through a different branch
    is exactly how one of these would have stayed a retry candidate.
    """
    name, shape = unusable
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "Good.m4b", "Bad.m4b"))
    run_env["reports"]["Bad.m4b"] = report(**shape)
    work(panel, tmp_path, run_env)

    plan = panel.run_plan
    result = panel.run_result
    bad = ids(panel)["Bad.m4b"]

    refused = [entry for entry in plan.unusable if entry.occurrence_id == bad]
    assert len(refused) == 1, f"{name} did not produce one typed failure"
    assert refused[0].reason, "the failure is typed"
    assert refused[0].retryable is False
    # Present, not swallowed: it is reported and it is not a success.
    assert result.failures.for_item(bad) is not None
    assert result.failures.for_item(bad).retryable is False
    assert bad not in result.completed_ids
    # Non-fatal: the other book still converted, and the run is not FAILED.
    assert result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert result.succeeded_count == 1
    # No executable entry, and therefore never a retry candidate.
    assert bad not in {item.occurrence_id for item in plan.items}
    assert bad not in result.retryable_ids


def test_a_source_that_was_never_probed_is_also_not_retryable(
        make_panel, tmp_path, run_env):
    """The defensive ``NOT_PROBED`` branch reaches the same classification.

    It is not reachable through the panel, so it is driven through the pure plan
    seam — the point being that it produces an ``ItemFailure`` like the others and
    must not acquire a different answer merely by entering another way.
    """
    from mp3_tools import m4b_plan
    from test_m4b_conversion_plan import direct

    entries = direct(book(tmp_path / "src", "A.m4b"))
    plan = m4b_plan.assemble_plan(
        snapshot_id="m4b-run-1", entries=entries, reports={},
        options=m4b_plan.PlanOptions(),
        reserve=lambda: (tmp_path / "run", None))
    assert plan.items == ()
    assert plan.unusable[0].reason == m4b_plan.NOT_PROBED
    assert plan.unusable[0].retryable is False


def test_the_default_is_the_safe_answer():
    """``ItemFailure`` cannot be constructed retryable by forgetting to say so."""
    from mp3_tools.m4b_plan import ItemFailure

    entry = ItemFailure(occurrence_id="occ-1", source=Path("A.m4b"),
                        reason="probe_failed", message="no")
    assert entry.retryable is False


def test_an_execution_failure_is_retryable(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    record = panel.run_result.failures.for_item(ids(panel)["B.m4b"])
    assert record.stage == m4b_converter.STAGE_CONVERT
    assert record.retryable is True


def test_the_note_helper_has_no_retryable_default():
    """**Structural.** One helper, two stages, and it may not guess between them.

    A default here is precisely how a preflight failure came to be stamped with
    the execution stage's answer, so the parameter is keyword-only and required.
    """
    worker = function("convert_worker")
    note = next(node for node in ast.walk(worker)
                if isinstance(node, ast.FunctionDef) and node.name == "note")
    assert [arg.arg for arg in note.args.kwonlyargs] == ["retryable"]
    assert note.args.kw_defaults == [None], "retryable must not have a default"


def test_no_retryability_is_inferred_from_error_text():
    """Nothing decides retryability by reading a message after the fact."""
    worker = function("convert_worker")
    for node in ast.walk(worker):
        if isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            rendered = ast.dump(node)
            assert "retryable" not in rendered, ast.dump(node)


# --------------------------------------------------------------------------- #
# The invariant that makes Retry Failed executable at all
# --------------------------------------------------------------------------- #


def test_every_retryable_id_has_an_executable_plan_entry(
        make_panel, tmp_path, run_env):
    """``retryable_ids`` ⊆ the frozen plan's executable items. Pinned mechanically.

    Driven over a queue holding both kinds of failure at once, because the whole
    point is that the two are told apart.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    run_env["fail"] = ("B.m4b",)
    run_env["reports"]["C.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    plan = panel.run_plan
    executable = {item.occurrence_id for item in plan.items}
    assert set(panel.run_result.retryable_ids) <= executable
    # And it is not vacuous: something really was retryable, and something really
    # failed without being one.
    assert panel.run_result.retryable_ids == (ids(panel)["B.m4b"],)
    assert panel.run_result.failed_count == 2


def test_every_retryable_id_also_has_a_frozen_destination(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    plan = panel.run_plan
    for item_id in panel.run_result.retryable_ids:
        item = plan.item_for(item_id)
        assert item is not None
        assert item.segments, "a retryable item has segments to re-execute"
        for segment in item.segments:
            assert segment.destination is not None


# --------------------------------------------------------------------------- #
# Retry request authority
# --------------------------------------------------------------------------- #


def test_the_request_is_built_from_the_shared_result(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)

    request = panel.run_result.retry()
    assert isinstance(request, jc.RetryRequest)
    # The exact original object, not a copy and not a rebuild.
    assert request.snapshot is panel.run_snapshot
    assert request.snapshot_id == panel.run_snapshot.snapshot_id
    assert request.item_ids == (ids(panel)["B.m4b"], ids(panel)["C.m4b"])


def test_the_request_never_contains_a_preflight_failure(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    run_env["fail"] = ("B.m4b",)
    run_env["reports"]["C.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    request = panel.run_result.retry()
    assert request.item_ids == (ids(panel)["B.m4b"],)
    assert ids(panel)["C.m4b"] not in request.item_ids


def test_the_retry_worker_is_given_the_frozen_snapshot_object(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    frozen = panel.run_snapshot

    params = retry(panel)
    assert params["snapshot"] is frozen
    assert params["run_id"] == frozen.snapshot_id
    assert params["retry_ids"] == (ids(panel)["B.m4b"],)


def test_no_second_capture_run_and_no_new_snapshot_id(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    before = panel.run_snapshot

    with mock.patch.object(m4b_converter, "capture_run",
                           side_effect=AssertionError("a retry captured a new run")):
        retry(panel)
    assert panel.run_snapshot is before


def test_the_retry_callback_reads_no_capture_and_no_planner():
    """**Structural.** The names a second planning pass would need are absent."""
    body = named(function("retry_failed"))
    for banned in ("capture_run", "read_options", "snapshot", "probe_source",
                   "assemble_plan", "reserve_run_directory", "DestinationPlanner",
                   "plan_flat", "plan_mirrored", "plan_multi_root", "planner"):
        assert banned not in body, banned


# --------------------------------------------------------------------------- #
# The defensive executable-plan check
# --------------------------------------------------------------------------- #


def test_a_retryable_id_with_no_plan_entry_is_refused_truthfully(
        make_panel, tmp_path, run_env, monkeypatch):
    """A future regression must fail loudly, not be repaired behind the contract.

    The result is rebuilt by hand so that a **preflight** failure claims to be
    retryable — exactly the state the corrected contract makes impossible. The
    retry must refuse: not re-probe it, not plan it a destination, not silently
    drop it from the request.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["reports"]["B.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    bad = ids(panel)["B.m4b"]
    broken = jc.RunResult.settle(
        panel.run_snapshot,
        jc.FailureLog(snapshot_id=panel.run_snapshot.snapshot_id, records=(
            jc.FailureRecord(item_id=bad, stage=m4b_converter.STAGE_PREFLIGHT,
                             display_message="it went wrong", technical_detail="",
                             retryable=True,
                             snapshot_id=panel.run_snapshot.snapshot_id),)),
        completed_ids=(ids(panel)["A.m4b"],))
    panel._settle(broken)

    shown: list = []
    monkeypatch.setattr(m4b_converter.messagebox, "showerror",
                        lambda title, message: shown.append((title, message)))
    probed_before = len(run_env["probed"])
    started_before = len(StubThread.started)

    assert available(panel) is True, "the broken result really did offer a retry"
    with mock.patch.object(
            output_paths, "reserve_run_directory",
            side_effect=AssertionError("a refused retry reserved a directory")):
        panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)

    assert len(StubThread.started) == started_before, "no retry was launched"
    assert len(run_env["probed"]) == probed_before, "nothing was re-probed"
    assert shown and shown[0][1] == m4b_converter.RETRY_INVARIANT_MESSAGE
    assert "new run" in m4b_converter.RETRY_INVARIANT_MESSAGE


def test_the_refusal_diagnostic_is_bounded():
    """**Structural.** A diagnostic naming every id would be unbounded.

    A queue of a thousand books must not produce a thousand-name message, so the
    ids are sliced before they are rendered. The slice is what is pinned, not the
    wording around it.
    """
    sliced = [node for node in ast.walk(function("retry_failed"))
              if isinstance(node, ast.Subscript)
              and isinstance(node.slice, ast.Slice)]
    assert sliced, "the refused ids are rendered unbounded"
    upper = {node.slice.upper.value for node in sliced
             if isinstance(node.slice.upper, ast.Constant)}
    assert upper and max(upper) <= 5, upper


# --------------------------------------------------------------------------- #
# The frozen plan, and the frozen destinations
# --------------------------------------------------------------------------- #


def test_a_retry_reuses_the_exact_plan_object(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    frozen = panel.run_plan

    params = retry(panel)
    assert params["plan"] is frozen
    assert panel.run_plan is frozen


def test_a_retry_probes_nothing(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    probed = len(run_env["probed"])

    run_env["fail"] = ()
    retry(panel)
    assert len(run_env["probed"]) == probed, "a retry re-read a source"


def test_a_retry_reserves_no_second_run_directory(make_panel, tmp_path, run_env):
    """``retry`` raises from ``reserve_run_directory``, so reaching it fails here."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    directory = panel.run_plan.run_directory

    run_env["fail"] = ()
    retry(panel)
    assert panel.run_plan.run_directory == directory
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == ["run-1", "src"]


def test_the_retried_book_lands_at_its_original_destination(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    planned = panel.run_plan.item_for(ids(panel)["B.m4b"]).segments[0].destination

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert destinations_written(run_env) == [planned]
    assert planned.exists(), "the retried book landed at its frozen name"


def test_a_collision_suffix_survives_the_failure_that_created_it(
        make_panel, tmp_path, run_env):
    """**Phase 8's accepted behaviour, and Phase 13 depends on it.**

    Two books share a name. The first reserves ``Same.mp3`` and fails; the second
    is planned ``Same-1.mp3`` and succeeds. The failed book keeps its reservation
    — releasing it, or compacting the survivor's name, would leave the retry with
    no destination to return to.
    """
    first = book(tmp_path / "one", "Same.m4b")
    second = book(tmp_path / "two", "Same.m4b")
    panel = make_panel()
    whole(panel, first, second)
    run_env["fail"] = (str(first),)
    work(panel, tmp_path, run_env)

    names = [item.segments[0].destination.name for item in panel.run_plan.items]
    assert names == ["Same.mp3", "Same-1.mp3"]
    assert (panel.run_plan.run_directory / "Same-1.mp3").exists()
    assert not (panel.run_plan.run_directory / "Same.mp3").exists()

    run_env["fail"] = ()
    run_env["commands"].clear()
    retry(panel)
    assert destinations_written(run_env) == [
        panel.run_plan.run_directory / "Same.mp3"]
    assert (panel.run_plan.run_directory / "Same.mp3").exists()
    # The survivor was not renamed or compacted by the retry.
    assert (panel.run_plan.run_directory / "Same-1.mp3").exists()


# --------------------------------------------------------------------------- #
# Only the failed executable items run
# --------------------------------------------------------------------------- #


def test_a_retry_runs_only_the_failed_book(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert [path.name for path in sources_read(run_env)] == ["B.m4b"]


def test_a_retry_skips_successes_preflight_failures_and_the_unattempted(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    run_env["fail"] = ("B.m4b",)
    run_env["reports"]["C.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    run_env["commands"].clear()
    run_env["fail"] = ()
    params = retry(panel)
    assert params["retry_ids"] == (ids(panel)["B.m4b"],)
    joined = " ".join(" ".join(argv) for argv in run_env["commands"])
    for absent in ("A.m4b", "C.m4b", "D.m4b"):
        assert absent not in joined, absent


def test_occurrence_identity_is_the_authority_for_duplicates(
        make_panel, tmp_path, run_env):
    """Two occurrences of the same path; only the one that failed is retried."""
    source = book(tmp_path / "src", "Twice.m4b")
    panel = make_panel()
    panel.importer.options.set_allow_duplicates(True)
    whole(panel, source, source)

    # The two occurrences share a source, so a source name cannot tell them
    # apart. Their *destinations* can: the collision planner gave the second one
    # ``Twice-1.mp3``, and that is the one made to fail.
    def outcome(joined):
        if any("Twice-1" in part for part in joined):
            return ProcessResult(1, detail="ffmpeg said no")
        return None

    run_env["outcome"] = outcome
    work(panel, tmp_path, run_env)
    run_env["outcome"] = None
    plan = panel.run_plan
    assert len(plan.items) == 2, "two deliberate occurrences of one path"
    second = plan.items[1]
    assert second.segments[0].destination.name == "Twice-1.mp3", (
        "the two occurrences were planned distinct destinations")
    assert panel.run_result.succeeded_count == 1
    assert panel.run_result.retryable_ids == (second.occurrence_id,)

    run_env["commands"].clear()
    params = retry(panel)
    assert params["retry_ids"] == (second.occurrence_id,)
    assert destinations_written(run_env) == [second.segments[0].destination]
    assert plan.items[0].occurrence_id not in params["retry_ids"]


# --------------------------------------------------------------------------- #
# Same run, new attempt
# --------------------------------------------------------------------------- #


def test_the_attempt_number_rises_and_everything_else_is_the_same_run(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    first = work(panel, tmp_path, run_env)

    second = retry(panel)
    assert second["attempt"] == first["attempt"] + 1
    assert second["run_id"] == first["run_id"]
    assert second["snapshot"] is first["snapshot"]
    assert second["plan"] is panel.run_plan


def test_the_attempt_gets_fresh_controls_and_a_fresh_estimate(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    old_adapter = panel.jobs
    old_controller = panel.job_controller
    old_estimator = panel.job_estimator

    retry(panel)
    assert panel.jobs is not old_adapter
    assert panel.job_controller is not old_controller
    assert panel.job_estimator is not old_estimator
    assert old_controller.is_terminal, "the retired controller was already finished"


def test_one_pump_one_drain_one_scheduled_callback(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel._pump.drain_count == 2

    retry(panel)
    assert panel._pump.drain_count == 2, "the retired adapter's drain was not dropped"
    assert panel._pump.pending is not None, "one outstanding after() callback"
    assert panel._pump.scheduled_count == 0, "and no one-shot timer beside it"


def test_a_late_sample_from_the_previous_attempt_is_inert(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    first = work(panel, tmp_path, run_env)
    retry(panel)

    stale = m4b_converter.TimingSample(
        run_id=first["run_id"], attempt=first["attempt"],
        category=m4b_converter.ETA_CATEGORY, duration=9.0)
    assert panel._record_timing(stale) is False
    current = m4b_converter.TimingSample(
        run_id=first["run_id"], attempt=panel._attempt,
        category=m4b_converter.ETA_CATEGORY, duration=9.0)
    assert panel._record_timing(current) is True


def test_the_retired_stream_cannot_reach_the_new_controls(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    old = panel.jobs

    retry(panel)
    assert panel.jobs.stream is not old.stream
    assert old.stream.events, "the previous attempt really did produce events"
    assert old.closed is True, "the retired adapter was closed, not merely dropped"
    # Draining the retired adapter changes nothing in the live one.
    before = len(panel.jobs.stream.events)
    old.drain()
    assert len(panel.jobs.stream.events) == before
    assert panel._pump.drain_count == 2


# --------------------------------------------------------------------------- #
# The cumulative result
# --------------------------------------------------------------------------- #


def test_a_retried_success_joins_the_earlier_ones(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.run_result.succeeded_count == 2

    run_env["fail"] = ()
    retry(panel)
    result = panel.run_result
    assert result.succeeded_count == 3
    assert result.failed_count == 0
    assert result.not_attempted_count == 0, "no earlier success became an absence"
    assert result.state is jc.JobState.SUCCEEDED
    assert result.has_retryable is False


def test_the_mixed_case_end_to_end(make_panel, tmp_path, run_env):
    """§17: A succeeds, B fails retryably, C is refused by preflight, D succeeds.

    The whole corrected contract in one run: the retry offers B alone, and when B
    succeeds the run is still ``COMPLETED_WITH_FAILURES`` because C is still
    failed — but there is nothing left to retry. Non-retryable does not mean
    hidden, ignored, or magically successful.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    run_env["fail"] = ("B.m4b",)
    run_env["reports"]["C.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)

    by_name = ids(panel)
    result = panel.run_result
    assert result.outcome_for(by_name["A.m4b"]).status is jc.ItemStatus.SUCCEEDED
    assert result.outcome_for(by_name["B.m4b"]).status is jc.ItemStatus.FAILED
    assert result.outcome_for(by_name["C.m4b"]).status is jc.ItemStatus.FAILED
    assert result.outcome_for(by_name["D.m4b"]).status is jc.ItemStatus.SUCCEEDED
    assert result.retryable_ids == (by_name["B.m4b"],)
    assert available(panel) is True

    run_env["fail"] = ()
    retry(panel)

    result = panel.run_result
    assert result.outcome_for(by_name["A.m4b"]).status is jc.ItemStatus.SUCCEEDED
    assert result.outcome_for(by_name["B.m4b"]).status is jc.ItemStatus.SUCCEEDED
    assert result.outcome_for(by_name["C.m4b"]).status is jc.ItemStatus.FAILED
    assert result.outcome_for(by_name["D.m4b"]).status is jc.ItemStatus.SUCCEEDED
    assert result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert result.has_retryable is False
    assert available(panel) is False
    # C kept its own reason; nothing overwrote it with the retry's story.
    assert result.failures.for_item(by_name["C.m4b"]).stage == (
        m4b_converter.STAGE_PREFLIGHT)


def test_a_repeated_failure_replaces_its_record_and_stays_offered(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    first = panel.run_result.failures.for_item(ids(panel)["B.m4b"])

    retry(panel)
    again = panel.run_result.failures.for_item(ids(panel)["B.m4b"])
    assert again is not first, "the record describes the attempt that just happened"
    assert again.retryable is True
    assert panel.run_result.failed_count == 1, "not two records for one book"
    assert available(panel) is True

    run_env["fail"] = ()
    retry(panel)
    assert panel.run_result.failed_count == 0
    assert panel.run_result.succeeded_count == 2
    assert available(panel) is False


def test_merge_keeps_a_prior_failure_the_attempt_never_reached(
        make_panel, tmp_path, run_env):
    """A cancelled retry invents nothing for the books it did not get to.

    Their previous failure is still the true and only known reason they were retry
    candidates, so it stands. Fabricating a new one would report a failure that
    did not happen.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)
    by_name = ids(panel)
    original = panel.run_result.failures.for_item(by_name["C.m4b"])

    # Cancel as soon as the first retried book has been handled.
    def outcome(joined):
        panel._cancel_event.set()
        return None

    run_env["outcome"] = outcome
    run_env["fail"] = ()
    retry(panel)

    result = panel.run_result
    assert result.cancelled is True
    assert result.failures.for_item(by_name["C.m4b"]) is original
    assert result.outcome_for(by_name["A.m4b"]).status is jc.ItemStatus.SUCCEEDED


def test_merge_attempt_is_pure_and_reads_no_filesystem():
    """**Structural.** The cumulative rule is arithmetic over immutable values."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    merge = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "merge_attempt")
    body = named(merge)
    for banned in ("open", "Path", "iterdir", "exists", "unlink", "tk", "self",
                   "probe_source", "measured_duration", "ffmpeg_cmd", "glob"):
        assert banned not in body, banned


def test_the_cumulative_result_is_built_from_public_shared_types():
    """No shared production was extended to express a multi-attempt run."""
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    merge = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "merge_attempt")
    constructed = {node.func.id for node in ast.walk(merge)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "FailureLog" in constructed
    called = {node.func.attr for node in ast.walk(merge)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "settle" in called


# --------------------------------------------------------------------------- #
# Whole-book success numbering across attempts
# --------------------------------------------------------------------------- #


def test_a_retry_continues_the_sequence(make_panel, tmp_path, run_env):
    """§18's worked example: A=1, B fails, C=2, then a retried B is **3**."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert track_for(run_env, "A.m4b") == 1
    assert track_for(run_env, "C.m4b") == 2, "B consumed nothing when it failed"

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert tracks_written(run_env) == [3], "the retry continued, not restarted"


def test_a_retry_that_fails_again_still_consumes_nothing(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    run_env["commands"].clear()
    retry(panel)
    assert tracks_written(run_env) == [3], "it was offered 3"

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert tracks_written(run_env) == [3], (
        "and 3 was still on offer, because the failed attempt never took it")


def test_a_non_default_start_number_carries_across_a_retry(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"),
          start_number=7)
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert track_for(run_env, "A.m4b") == 7
    assert track_for(run_env, "C.m4b") == 8

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert tracks_written(run_env) == [9]


def test_the_next_number_is_derived_from_the_result_not_the_filesystem():
    """**Structural.** Nothing reads a name, a tag or a directory to find it."""
    worker = function("convert_worker")
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "prior.completed_ids" in source
    body = named(worker)
    for banned in ("iterdir", "glob", "listdir", "scandir", "stat"):
        assert banned not in body, banned


def test_auto_number_off_still_writes_no_sequential_track_on_retry(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"), auto=False)
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert tracks_written(run_env) == []


def test_split_retry_uses_no_success_allocator(make_panel, tmp_path, run_env):
    """Split tracks are structural, so a retry cannot renumber them."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"), split=True,
          start_number=7)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    run_env["commands"].clear()
    run_env["fail"] = ()
    retry(panel)
    assert tracks_written(run_env) == [1, 2, 3], (
        "structural, restarting for each book, untouched by Start #")


# --------------------------------------------------------------------------- #
# Split retry is item-level
# --------------------------------------------------------------------------- #


def test_a_failed_split_book_leaves_no_partial_and_is_fully_rebuilt(
        make_panel, tmp_path, run_env):
    """One segment fails, so the **item** failed; the retry re-runs all of them."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b"), split=True)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    seen: list = []

    def outcome(joined):
        line = " ".join(joined)
        seen.append(line)
        # The third segment of the book fails, after two were finalised.
        return ProcessResult(1, detail="ffmpeg said no") if len(seen) == 3 else None

    run_env["outcome"] = outcome
    work(panel, tmp_path, run_env)

    plan = panel.run_plan
    frozen = [segment.destination for segment in plan.items[0].segments]
    assert len(frozen) == 3
    assert not any(path.exists() for path in frozen), "the partial book was taken back"

    run_env["outcome"] = None
    run_env["commands"].clear()
    retry(panel)
    assert destinations_written(run_env) == frozen, (
        "every frozen segment, in frozen order, at its original name")
    assert all(path.exists() for path in frozen)


def test_split_retry_keeps_the_structural_tracks_and_names(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b"), split=True)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)
    plan = panel.run_plan
    before = [(s.destination.name, s.track, s.start, s.end)
              for s in plan.items[0].segments]

    run_env["fail"] = ()
    run_env["commands"].clear()
    retry(panel)
    after = [(s.destination.name, s.track, s.start, s.end)
             for s in panel.run_plan.items[0].segments]
    assert after == before, "the plan is the same object and nothing re-derived it"
    assert tracks_written(run_env) == [1, 2, 3]


# --------------------------------------------------------------------------- #
# The unknown occupant
# --------------------------------------------------------------------------- #


def test_a_retry_never_deletes_an_unknown_file_at_its_destination(
        make_panel, tmp_path, run_env):
    """§11: no ownership token exists, so an occupant is left alone and the retry fails.

    Phase 11 already removes the temporary candidate and any earlier finalised
    segments before a failed item settles, so a settled failure leaves no partial
    behind. Anything sitting at the frozen name afterwards is therefore *not*
    ours, and clearing the slot to make room would destroy a stranger's file.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    source = tmp_path / "src" / "B.m4b"
    source_before = digest(source)

    def claim(joined):
        if "B.m4b" in " ".join(joined):
            planned = tmp_path / "run-1" / "B.mp3"
            planned.parent.mkdir(parents=True, exist_ok=True)
            planned.write_text("something else got here first", encoding="utf-8")
        return None

    run_env["outcome"] = claim
    work(panel, tmp_path, run_env)
    occupant = tmp_path / "run-1" / "B.mp3"
    occupied_digest = digest(occupant)
    assert panel.run_result.failed_count == 1

    # The occupant is still there when the retry runs, and must survive it.
    run_env["outcome"] = None
    retry(panel)

    assert occupant.exists(), "the retry deleted a file it did not own"
    assert digest(occupant) == occupied_digest, "the retry overwrote it"
    assert digest(source) == source_before, "the source was touched"
    record = panel.run_result.failures.for_item(ids(panel)["B.m4b"])
    assert record is not None and record.retryable is True
    assert available(panel) is True


# --------------------------------------------------------------------------- #
# The Retry Failed control
# --------------------------------------------------------------------------- #


def test_retry_is_unavailable_before_any_run(make_panel):
    panel = make_panel()
    assert jc.JobAction.RETRY_FAILED in panel.jobs.controls.buttons
    assert available(panel) is False


def test_retry_is_unavailable_while_a_run_is_going(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b"))
    start(panel)
    assert available(panel) is False


def test_retry_is_unavailable_after_a_clean_success(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    work(panel, tmp_path, run_env)
    assert panel.run_result.state is jc.JobState.SUCCEEDED
    assert available(panel) is False


def test_retry_is_unavailable_after_preflight_failures_only(
        make_panel, tmp_path, run_env):
    """The case the corrected contract exists for."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["reports"]["B.m4b"] = report(status=ProbeStatus.PROBE_FAILED, duration=None)
    work(panel, tmp_path, run_env)
    assert panel.run_result.state is jc.JobState.COMPLETED_WITH_FAILURES
    assert panel.run_result.failed_count == 1
    assert panel.run_result.has_retryable is False
    assert available(panel) is False


def test_retry_is_unavailable_while_a_retry_is_active(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    assert available(panel) is False, "offered again while its own attempt runs"
    params = StubThread.started[-1].args[0]
    panel.convert_worker(params)
    panel._pump.tick()


def test_pressing_retry_launches_exactly_one_attempt(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    before = len(StubThread.started)

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    assert len(StubThread.started) == before + 1
    # A second press while it is running does nothing at all.
    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    assert len(StubThread.started) == before + 1
    panel.convert_worker(StubThread.started[-1].args[0])
    panel._pump.tick()


def test_there_is_exactly_one_retry_control(make_panel):
    panel = make_panel()
    buttons = [action for action in panel.jobs.controls.buttons
               if action is jc.JobAction.RETRY_FAILED]
    assert len(buttons) == 1
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert source.count("on_retry=") == 1


def test_nothing_sets_the_retry_button_state_by_hand():
    """**Structural.** Availability is derived by the shared bar, never asserted."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "RETRY_FAILED" not in source
    assert "JobAction" not in source


def test_a_retry_locks_the_same_inputs_as_a_run(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert str(panel.btn_convert.cget("state")) == "normal"

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    assert str(panel.btn_convert.cget("state")) == "disabled"
    assert str(panel.entry_quality.cget("state")) == "disabled"
    assert str(panel.chk_auto_num.cget("state")) == "disabled"

    panel.convert_worker(StubThread.started[-1].args[0])
    panel._pump.tick()
    assert str(panel.btn_convert.cget("state")) == "normal"


def test_pause_and_cancel_are_available_during_a_retry(make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    panel._pump.tick()
    availability = panel.jobs.controls.availability()
    assert availability[jc.JobAction.PAUSE] is True
    assert availability[jc.JobAction.CANCEL] is True
    panel.convert_worker(StubThread.started[-1].args[0])
    panel._pump.tick()


# --------------------------------------------------------------------------- #
# The live UI is irrelevant to a retry
# --------------------------------------------------------------------------- #


def test_everything_the_user_changed_afterwards_is_ignored(
        make_panel, tmp_path, run_env):
    """§23: the panel is mutated in every way that could matter, then retried."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"), start_number=1)
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    frozen_snapshot = panel.run_snapshot
    frozen_plan = panel.run_plan
    frozen = dict(mode=frozen_plan.mode, metadata=frozen_plan.metadata_mode,
                  quality=frozen_plan.quality, auto=frozen_plan.auto_number,
                  start=frozen_plan.start_number,
                  destinations=[s.destination for item in frozen_plan.items
                                for s in item.segments])

    # Every live thing a retry might be tempted to read.
    panel._manager.clear()
    add_files(panel, *books(tmp_path / "later", "Z.m4b"))
    panel.var_mode.set(ConversionMode.SPLIT.value)
    panel.var_metadata_mode.set(MetadataMode.STRIP.value)
    panel.var_quality.set(9)
    panel.var_auto_num.set(False)
    panel.var_start_num.set(42)
    panel.title_entry.delete(0, tk.END)
    panel.title_entry.insert(0, "A Different Title")
    panel.importer.options.set_include_subfolders(False)

    run_env["fail"] = ()
    run_env["commands"].clear()
    params = retry(panel)

    assert params["snapshot"] is frozen_snapshot
    assert params["plan"] is frozen_plan
    assert frozen_plan.mode is frozen["mode"]
    assert frozen_plan.metadata_mode is frozen["metadata"]
    assert frozen_plan.quality == frozen["quality"]
    assert frozen_plan.auto_number is frozen["auto"]
    assert frozen_plan.start_number == frozen["start"]
    assert [s.destination for item in frozen_plan.items
            for s in item.segments] == frozen["destinations"]
    # And what it actually ran is the frozen book, at the frozen name.
    retried = frozen_plan.item_for(params["retry_ids"][0])
    assert destinations_written(run_env) == [retried.segments[0].destination]
    assert [path.name for path in sources_read(run_env)] == ["B.m4b"]


def test_the_retry_worker_reads_no_widget():
    """**Structural.** The same two attributes the run worker was allowed."""
    worker = function("convert_worker")
    reached = {node.attr for node in ast.walk(worker)
               if isinstance(node, ast.Attribute)
               and isinstance(node.value, ast.Name) and node.value.id == "self"}
    assert reached <= {"_cancel_event", "_log_q"}, sorted(reached)


# --------------------------------------------------------------------------- #
# Progress and the retry denominator
# --------------------------------------------------------------------------- #


def test_the_retry_denominator_describes_only_the_retry(
        make_panel, tmp_path, run_env):
    """A split run of three books, one retried: the bar counts *its* segments."""
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"), split=True)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)
    assert panel.run_plan.total_segments == 9

    run_env["fail"] = ()
    retry(panel)
    totals = {entry.total for entry in panel.jobs.stream.events
              if entry.total is not None}
    assert totals == {3}, "the retry counted only its own segments"
    last = [entry for entry in panel.jobs.stream.events
            if entry.total is not None][-1]
    assert last.completed == last.total, "a complete retry fills the bar"


def test_a_retry_of_everything_uses_the_whole_plans_total(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("A.m4b", "B.m4b")
    work(panel, tmp_path, run_env)

    run_env["fail"] = ()
    retry(panel)
    totals = {entry.total for entry in panel.jobs.stream.events
              if entry.total is not None}
    assert totals == {panel.run_plan.total_segments}


# --------------------------------------------------------------------------- #
# Pause, cancel and close during a retry — real threads
# --------------------------------------------------------------------------- #


def test_cancel_during_a_retry_settles_only_after_cleanup(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)
    survivor = panel.run_plan.item_for(ids(panel)["A.m4b"]).segments[0].destination
    assert survivor.exists()

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    params = StubThread.started[-1].args[0]
    # The retry is allowed to succeed, so what stops it is the cancellation and
    # nothing else. Leaving these failing would prove the merge for the wrong
    # reason.
    run_env["fail"] = ()

    entered, release = threading.Event(), threading.Event()
    seen: list = []
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        seen.append(list(argv))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT), "the first retried encode was never released"
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-retry-cancel")
        worker.start()
        assert entered.wait(WAIT), "the retry never began"
        panel.cancel()
        release.set()
        worker.join(WAIT)
        assert not worker.is_alive()

    panel._pump.tick()
    assert panel.job_controller.state is jc.JobState.CANCELLED
    assert len(seen) == 1, "no later retried book started after the cancellation"
    assert survivor.exists(), "a completed output from before was left alone"
    result = panel.run_result
    assert result.cancelled is True
    # No unattempted retry item was fabricated into a new failure.
    assert result.failed_count == 2
    assert result.outcome_for(ids(panel)["A.m4b"]).status is jc.ItemStatus.SUCCEEDED


def test_pause_during_a_retry_stops_at_a_segment_boundary(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    params = StubThread.started[-1].args[0]
    run_env["fail"] = ()

    entered, release = threading.Event(), threading.Event()
    seen: list = []
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        seen.append(list(argv))
        if len(seen) == 1:
            entered.set()
            assert release.wait(WAIT), "the first retried encode was never released"
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-retry-pause")
        worker.start()
        assert entered.wait(WAIT), "the retry never began"
        panel.pause()
        # The encode in hand is indivisible, so nothing may claim it stopped.
        assert panel.job_controller.state is jc.JobState.PAUSE_REQUESTED
        release.set()

        waiter = threading.Event()
        for _ in range(int(WAIT * 200)):
            if panel.job_controller.state is jc.JobState.PAUSED:
                break
            waiter.wait(0.005)
        assert panel.job_controller.state is jc.JobState.PAUSED
        assert len(seen) == 1, "no later book started while paused"

        panel.resume()
        worker.join(WAIT)
        assert not worker.is_alive(), "resume did not wake the retry"
        assert len(seen) == 2

    panel._pump.tick()
    assert panel.run_result.succeeded_count == 3


def test_closing_during_a_retry_stops_it_and_leaves_nothing_scheduled(
        make_panel, tmp_path, run_env):
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)

    panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED)
    params = StubThread.started[-1].args[0]

    entered = threading.Event()
    seen: list = []
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        """Hold the first retried encode until the panel asks it to stop.

        ``close()`` touches Tk and so must run on the thread that owns it, which
        is this one -- and it *joins* the worker. So the encode has to be woken by
        the closing itself rather than by the test, which is exactly the real
        shape: the latch ``close()`` sets is the latch a running child is polled
        against.
        """
        seen.append(list(argv))
        if len(seen) == 1:
            entered.set()
            for _ in range(int(WAIT * 200)):
                if panel._cancel_event.is_set():
                    break
                threading.Event().wait(0.005)
            else:
                raise AssertionError("close never reached the running encode")
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated):
        worker = RealThread(target=panel.convert_worker, args=(params,),
                            name="m4b-retry-close")
        worker.start()
        assert entered.wait(WAIT), "the retry never began"
        panel.close()
        worker.join(WAIT)
        assert not worker.is_alive(), "close left the retry worker running"

    assert panel._pump.closed is True
    assert panel._pump.scheduled_count == 0
    assert len(seen) == 1, "no later book started after the close"
    assert panel.job_controller.state is jc.JobState.CANCELLED


# --------------------------------------------------------------------------- #
# Structural boundaries
# --------------------------------------------------------------------------- #


def test_the_retry_path_contains_no_planning_vocabulary():
    """Nothing on the retry route may produce a new answer."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    worker = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "convert_worker")
    # The worker still plans -- for a *first* attempt. What matters is that the
    # planning it does is behind the "not retrying" guard, which the retry tests
    # above prove dynamically. Here we pin that the retry callback itself is clean.
    callback = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "retry_failed")
    assert "assemble_plan" in named(worker), "the first attempt still plans"
    assert "assemble_plan" not in named(callback)


def test_no_shared_production_module_knows_about_this_phase():
    """Risk gate #9 was not reached: the cumulative rule is Converter-local.

    The shared values expressed it as they already stood -- an immutable
    ``FailureLog`` and ``RunResult.settle`` -- so nothing shared had to learn what
    a Converter attempt is. If a future change moved the merge into shared code,
    this is where that would have to be argued rather than slipped in.
    """
    shared = REPO_ROOT / "scripts" / "Universal" / "shared"
    for name in ("job_control.py", "job_ui.py", "output_paths.py", "importing.py",
                 "subprocess_utils.py", "metadata.py"):
        tree = ast.parse((shared / name).read_text(encoding="utf-8"))
        # Structural, not prose: a docstring in ``metadata.py`` legitimately
        # mentions the Converter by name, and a substring guard would fail on
        # that sentence while missing a real import.
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "mp3_tools" not in imported, name
        for banned in ("merge_attempt", "ConversionPlan", "ItemPlan", "SegmentPlan"):
            assert banned not in named(tree), (name, banned)
    assert any(node.name == "merge_attempt" for node in ast.walk(parse_panel())
               if isinstance(node, ast.FunctionDef))


def test_the_executor_and_the_allocator_know_nothing_about_retry():
    """Phase 11 and Phase 12 are untouched by Phase 13."""
    for name in ("m4b_execution.py", "m4b_numbering.py"):
        text = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / name).read_text(
            encoding="utf-8")
        tree = ast.parse(text)
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        for banned in ("retry", "retry_failed", "merge_attempt", "RetryRequest"):
            assert banned not in defined, (name, banned)


def test_the_plan_holds_no_attempt_state():
    """A retry re-reads the plan, so nothing about an attempt may live in it."""
    from mp3_tools.m4b_plan import ConversionPlan, ItemPlan, SegmentPlan

    for kind in (ConversionPlan, ItemPlan, SegmentPlan):
        for field in kind.__dataclass_fields__:
            for banned in ("attempt", "retry", "counter", "allocator", "planner",
                           "reservation"):
                assert banned not in field, (kind, field)
    text = PLAN_SOURCE.read_text(encoding="utf-8")
    assert "merge_attempt" not in text and "RetryRequest" not in text


# --------------------------------------------------------------------------- #
# Generated media — the retry that really happens, on real files
# --------------------------------------------------------------------------- #


def real_panel(make_panel, monkeypatch, *sources, **kwargs):
    """A panel wired to the real executor: only the thread is stubbed."""
    StubThread.started = []
    monkeypatch.setattr(m4b_converter, "threading", _ThreadShim())
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", lambda t: None)
    panel = make_panel()
    whole(panel, *sources, start_number=kwargs.get("start_number", 1),
          split=kwargs.get("split", False))
    return panel


def real_work(panel, tmp_path, failing=()):
    """Run for real, failing the named sources at the process seam only.

    Everything else -- the command shapes, the temporary siblings, the drift
    check, the finalisation, the artwork pass -- is the production executor
    against a real ffmpeg. Only the exit status of the named books is decided
    here, and only on this attempt.
    """
    params = start(panel)
    real = m4b_execution.run_argv

    def gated(argv, **kwargs):
        line = " ".join(str(part) for part in argv)
        if any(name in line for name in failing):
            return ProcessResult(1, detail="ffmpeg said no")
        return real(argv, **kwargs)

    with mock.patch.object(m4b_execution, "run_argv", gated), \
            mock.patch.object(output_paths, "reserve_run_directory",
                              side_effect=_reservation(tmp_path)):
        panel.convert_worker(params)
    panel._pump.tick()
    return params


def real_retry(panel):
    """Press Retry Failed and run the attempt with the executor fully real."""
    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    params = StubThread.started[-1].args[0]
    with mock.patch.object(
            output_paths, "reserve_run_directory",
            side_effect=AssertionError("a retry reserved a run directory")):
        panel.convert_worker(params)
    panel._pump.tick()
    return params


def test_real_retry_continues_the_track_sequence(media, tmp_path, make_panel,
                                                 monkeypatch):
    """§29: A=1, B fails, C=2 — then a retried B is really written as **3**."""
    a, b, c = media["plain"], media["preroll"], media["cover"]
    before = {path: digest(path) for path in (a, b, c)}
    panel = real_panel(make_panel, monkeypatch, a, b, c)
    real_work(panel, tmp_path, failing=(b.name,))

    plan = panel.run_plan
    destinations = {item.source.name: item.segments[0].destination
                    for item in plan.items}
    assert track_of(destinations[a.name]) == 1
    assert track_of(destinations[c.name]) == 2
    assert not destinations[b.name].exists(), "the failed book wrote nothing"
    survivors = {path: digest(path) for path in
                 (destinations[a.name], destinations[c.name])}

    real_retry(panel)

    assert destinations[b.name].exists(), "the retried book was written"
    assert track_of(destinations[b.name]) == 3
    # The other two are byte-identical: a retry touched nothing it did not run.
    for path, value in survivors.items():
        assert digest(path) == value, path
    # And every source is untouched by all of it.
    for path, value in before.items():
        assert digest(path) == value, path
    assert panel.run_result.succeeded_count == 3
    assert panel.run_result.has_retryable is False


def test_real_retry_from_a_non_default_start_number(media, tmp_path, make_panel,
                                                    monkeypatch):
    a, b, c = media["plain"], media["preroll"], media["cover"]
    panel = real_panel(make_panel, monkeypatch, a, b, c, start_number=7)
    real_work(panel, tmp_path, failing=(b.name,))
    destinations = {item.source.name: item.segments[0].destination
                    for item in panel.run_plan.items}
    assert [track_of(destinations[a.name]), track_of(destinations[c.name])] == [7, 8]

    real_retry(panel)
    assert track_of(destinations[b.name]) == 9


def test_real_repeated_retry_reaches_the_right_number(media, tmp_path, make_panel,
                                                      monkeypatch):
    """Fail, fail again, then succeed: the number waited rather than drifting."""
    a, b, c = media["plain"], media["preroll"], media["cover"]
    panel = real_panel(make_panel, monkeypatch, a, b, c)
    real_work(panel, tmp_path, failing=(b.name,))
    destinations = {item.source.name: item.segments[0].destination
                    for item in panel.run_plan.items}

    # Attempt two also fails.
    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    params = StubThread.started[-1].args[0]
    real = m4b_execution.run_argv
    with mock.patch.object(
            m4b_execution, "run_argv",
            lambda argv, **kw: ProcessResult(1, detail="again")):
        panel.convert_worker(params)
    panel._pump.tick()
    assert not destinations[b.name].exists()
    assert panel.run_result.has_retryable is True

    # Attempt three succeeds, and takes 3 rather than 4.
    assert m4b_execution.run_argv is real
    real_retry(panel)
    assert track_of(destinations[b.name]) == 3


def test_real_split_retry_rebuilds_every_segment_with_its_cover(
        media, tmp_path, make_panel, monkeypatch):
    """§20 and §21: the whole book again, at frozen names, artwork intact."""
    cover = media["cover"]
    source_before = digest(cover)
    panel = real_panel(make_panel, monkeypatch, cover, split=True)
    real_work(panel, tmp_path, failing=(cover.name,))

    frozen = [segment.destination for segment in panel.run_plan.items[0].segments]
    assert len(frozen) > 1, "a real chaptered split produces several segments"
    assert not any(path.exists() for path in frozen), "no partial book remained"

    real_retry(panel)

    assert all(path.exists() for path in frozen), "every frozen segment came back"
    for index, path in enumerate(frozen, start=1):
        assert track_of(path) == index, "structural tracks, unchanged by the retry"
        streams = _probe(path, "-show_streams")["streams"]
        assert any(stream.get("codec_type") == "video" for stream in streams), (
            f"{path.name} lost its cover")
    assert digest(cover) == source_before


def test_real_retry_writes_nothing_outside_the_original_run_directory(
        media, tmp_path, make_panel, monkeypatch):
    a, b = media["plain"], media["preroll"]
    panel = real_panel(make_panel, monkeypatch, a, b)
    real_work(panel, tmp_path, failing=(b.name,))
    directory = panel.run_plan.run_directory

    real_retry(panel)
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        item.segments[0].destination.name for item in panel.run_plan.items)
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == ["run-1"]


def test_a_retried_split_book_reuses_its_frozen_book_folder(
        make_panel, tmp_path, run_env):
    """Phase 16: the container is frozen with the rest of the plan.

    A failed split book keeps its folder reservation rather than releasing it,
    so the retry writes to the identical paths it was planned for. Releasing and
    re-planning would let the retry drift into a ``-1`` folder beside the empty
    original, which is exactly the scattering the per-book container exists to
    prevent.
    """
    panel = make_panel()
    whole(panel, *books(tmp_path / "src", "A.m4b"), split=True)
    run_env["default_report"] = report(duration=600.0,
                                       chapter_list=chapters(0.0, 200.0, 400.0))
    run_env["fail"] = ("A.m4b",)
    work(panel, tmp_path, run_env)
    run = panel.run_plan.run_directory
    planned = [s.destination for s in panel.run_plan.items[0].segments]
    assert {d.parent for d in planned} == {run / "A"}, planned

    run_env["fail"] = ()
    run_env["commands"].clear()
    retry(panel)
    again = [s.destination for s in panel.run_plan.items[0].segments]
    assert again == planned, "the retry used the frozen paths, folder and all"

    produced = sorted(run.rglob("*.mp3"))
    assert {d.parent for d in produced} == {run / "A"}
    assert len(produced) == len(planned)
