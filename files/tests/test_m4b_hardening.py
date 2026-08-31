"""Structural and regression hardening — v0.6.2 Plan 5, Phase 14.

This module deliberately does **not** restate Phases 1–13. Their coverage was
audited first, and everything already proved there is left where it is: the
importer adoption in ``test_m4b_converter_importing``, the frozen plan in
``test_m4b_conversion_plan``, the run in ``test_m4b_converter_jobs``, the
execution lifecycle in ``test_m4b_execution``, numbering in
``test_m4b_numbering``, retry in ``test_m4b_retry``, the shared recursion
contract in ``test_import_recursion``, and the Plan 3 boundary in
``test_plan3_boundaries``. What is here is the remainder — the seams those
phases left standing on a caller's good behaviour rather than on a mechanism.

Four of them are worth naming.

**The attempt boundary.** ``merge_attempt`` advertised ``retried_ids`` and did
not read it. It was correct only because its one caller happened to hand it a
matching subset, which is a property of the caller and not of the seam. Phase 14
makes the argument load-bearing: the attempt speaks for the books it was asked
to repeat and for nothing else, so a stray completion or a stray failure record
for an untouched book cannot reach the cumulative result. The tests below supply
exactly those stray values on purpose.

**Locking through a retry.** Phase 7B proved the controls lock for a *run*. A
retry is a second attempt at the same run and locks through the same call, but
nothing asserted it, so nothing would have noticed if it stopped.

**Freezing an option per import.** Recursion is frozen into each import
operation. That was proved for the shared scanner; what was not proved is that
two consecutive imports on one live panel can disagree about it.

**The two adoption tuples.** ``ADOPTED`` and ``UNCONVERTED_PANELS`` deliberately
disagree about ``m4b_converter.py``, because Plan 3 adoption is not Plan 1
visual conversion. That disagreement is load-bearing and is pinned here so a
future phase cannot "tidy" one tuple into agreement with the other.

Determinism and safety
----------------------
No test sleeps and no test converts real media: every source is a generated
placeholder under ``tmp_path`` and the one child-spawning function is stubbed,
exactly as the other panel modules do it. Nothing here reads the repository
tree except the two AST guards, which parse sources and never execute them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Imported outright rather than through ``importorskip``: Plan 5 is fail-loud.
import tkinter as tk

from shared import job_control as jc
from shared.import_coordination import OutcomeStatus

from mp3_tools import m4b_converter

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_conversion_plan import (  # noqa: E402
    StubThread,
    install_conversion_stubs,
)
from test_m4b_converter_importing import (  # noqa: E402
    add_files,
    add_folder,
    books,
    names,
    planned_of,
    planned_run,
)
from test_m4b_retry import work  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py"


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


class Silent:
    """Stands in for the one session logger, so no log file is opened."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture()
def make_panel(tk_root):
    made: list[m4b_converter.M4BConverterUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
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


# ``captured_run`` under the name the imported importing-module helpers expect.
captured_run = run_env


def parse_panel() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))


def function(name: str) -> ast.FunctionDef:
    for node in ast.walk(parse_panel()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in the panel")


def loaded(tree: ast.AST) -> set[str]:
    """Every bare name the body actually **reads**.

    ``ast.Name`` with a ``Load`` context only, so a parameter that is merely
    declared -- which is the whole defect this phase looked at -- does not count
    as being used.
    """
    return {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}


def reached(tree: ast.AST) -> set[str]:
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    return found


def ids(panel) -> dict:
    """Occurrence id by source file name, for readable assertions."""
    return {entry.path.name: entry.occurrence_id
            for entry in panel.run_snapshot.files.files}


def failure(snapshot, item_id, message="ffmpeg said no", retryable=True):
    """A well-formed record the shared contract will accept without complaint.

    The point of these tests is that a *valid* record for the *wrong* occurrence
    is refused by the merge, so nothing here may be rejected earlier for being
    malformed.
    """
    return jc.FailureRecord(
        item_id=item_id,
        stage=m4b_converter.STAGE_CONVERT,
        display_message=message,
        technical_detail="",
        retryable=retryable,
        snapshot_id=snapshot.snapshot_id,
    )


def status_of(result) -> dict:
    """Every occurrence's cumulative status, keyed by occurrence id."""
    return {entry.item_id: entry.status for entry in result.outcomes}


@pytest.fixture()
def mixed(make_panel, tmp_path, run_env):
    """One settled run: A succeeded, B and C failed in execution.

    Returned as the real objects a retry would be given, so the adversarial
    tests below drive the production merge with production values and change
    only the one thing under test.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    run_env["fail"] = ("B.m4b", "C.m4b")
    work(panel, tmp_path, run_env)

    prior = panel.run_result
    snapshot = panel.run_snapshot
    key = ids(panel)
    assert prior.succeeded_count == 1
    assert set(prior.retryable_ids) == {key["B.m4b"], key["C.m4b"]}
    return panel, prior, snapshot, key


# --------------------------------------------------------------------------- #
# The attempt boundary — ``merge_attempt(..., retried_ids=...)``
# --------------------------------------------------------------------------- #


def test_the_attempt_boundary_argument_is_actually_read():
    """**Structural.** The defect this section exists for, pinned.

    ``retried_ids`` was a parameter the body never loaded, so the boundary it
    named was enforced by the caller alone. A future edit that stops reading it
    would restore exactly that, silently, and this is what refuses to let it.
    """
    body = function("merge_attempt")
    assert "retried_ids" in {arg.arg for arg in body.args.kwonlyargs}
    assert "retried_ids" in loaded(body), (
        "merge_attempt declares an attempt boundary it does not read")


def test_a_stray_completion_cannot_clear_an_unretried_failure(mixed):
    """The headline case: C was not retried, so C is still failed.

    The attempt claims both B **and** C succeeded. Only B was asked for.
    """
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"],),
        completed=(key["B.m4b"], key["C.m4b"]),
        records=(), cancelled=False)

    status = status_of(merged)
    assert status[key["C.m4b"]] is jc.ItemStatus.FAILED
    assert key["C.m4b"] not in merged.completed_ids
    assert merged.failures.for_item(key["C.m4b"]) is not None
    # And the book that really was retried still succeeded.
    assert status[key["B.m4b"]] is jc.ItemStatus.SUCCEEDED


def test_a_stray_failure_cannot_undo_an_earlier_success(mixed):
    """A succeeded on the first attempt and was never a retry candidate."""
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"],),
        completed=(key["B.m4b"],),
        records=(failure(snapshot, key["A.m4b"], "invented"),),
        cancelled=False)

    assert status_of(merged)[key["A.m4b"]] is jc.ItemStatus.SUCCEEDED
    assert key["A.m4b"] in merged.completed_ids
    assert merged.failures.for_item(key["A.m4b"]) is None


def test_a_stray_record_cannot_replace_an_unretried_failure(mixed):
    """C keeps the reason it actually failed, not one this attempt invented."""
    _panel, prior, snapshot, key = mixed
    was = prior.failures.for_item(key["C.m4b"])
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"],),
        completed=(),
        records=(failure(snapshot, key["C.m4b"], "a different story"),),
        cancelled=False)

    assert merged.failures.for_item(key["C.m4b"]) is was


def test_an_empty_attempt_changes_nothing_at_all(mixed):
    """Nothing was retried, so nothing the attempt reports may be adopted."""
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(),
        completed=(key["B.m4b"], key["C.m4b"]),
        records=(failure(snapshot, key["A.m4b"]),),
        cancelled=False)

    assert status_of(merged) == status_of(prior)
    assert merged.completed_ids == prior.completed_ids
    assert merged.state is prior.state


def test_the_boundary_does_not_suppress_a_real_retry(mixed):
    """The control. Enforcing the boundary must not break the ordinary path."""
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"], key["C.m4b"]),
        completed=(key["B.m4b"],),
        records=(failure(snapshot, key["C.m4b"], "failed again"),),
        cancelled=False)

    status = status_of(merged)
    assert status[key["A.m4b"]] is jc.ItemStatus.SUCCEEDED
    assert status[key["B.m4b"]] is jc.ItemStatus.SUCCEEDED
    assert status[key["C.m4b"]] is jc.ItemStatus.FAILED
    assert merged.failures.for_item(key["C.m4b"]).display_message == "failed again"
    assert merged.state is jc.JobState.COMPLETED_WITH_FAILURES


def test_a_fatal_record_is_still_carried_across_the_boundary(mixed):
    """A job-level failure is about the **run**, so it has no occurrence to be
    outside the attempt of. Filtering item records must not swallow it."""
    _panel, prior, snapshot, key = mixed
    fatal = jc.FailureRecord(
        item_id=None, stage=m4b_converter.STAGE_PREFLIGHT,
        display_message="the run itself broke", technical_detail="",
        retryable=False, snapshot_id=snapshot.snapshot_id)
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"],),
        completed=(), records=(fatal,), cancelled=False)

    assert merged.state is jc.JobState.FAILED
    assert fatal in merged.failures.fatal


def test_the_frozen_order_survives_the_boundary(mixed):
    """Ordering is the snapshot's, whatever order the attempt reported in."""
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["C.m4b"], key["B.m4b"]),
        completed=(),
        records=(failure(snapshot, key["C.m4b"]), failure(snapshot, key["B.m4b"])),
        cancelled=False)

    assert [entry.item_id for entry in merged.failures.records] == [
        key["B.m4b"], key["C.m4b"]]


def test_a_cancelled_attempt_keeps_what_it_never_reached(mixed):
    """Both were retried; the attempt was cancelled before either finished.

    Nothing is invented for them and nothing is cleared: the previous failures
    are still the true and only known reason they were candidates.
    """
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"], key["C.m4b"]),
        completed=(), records=(), cancelled=True)

    assert merged.state is jc.JobState.CANCELLED
    assert merged.failures.for_item(key["B.m4b"]) is prior.failures.for_item(
        key["B.m4b"])
    assert merged.failures.for_item(key["C.m4b"]) is prior.failures.for_item(
        key["C.m4b"])
    assert key["A.m4b"] in merged.completed_ids


def test_the_boundary_holds_for_an_occurrence_outside_the_run_entirely(mixed):
    """A record naming an id the snapshot never had is not a way in either."""
    _panel, prior, snapshot, key = mixed
    merged = m4b_converter.merge_attempt(
        prior, snapshot,
        retried_ids=(key["B.m4b"],),
        completed=("not-an-occurrence",),
        records=(failure(snapshot, "also-not-an-occurrence"),),
        cancelled=False)

    assert "not-an-occurrence" not in merged.completed_ids
    assert [entry.item_id for entry in merged.failures.records] == [
        key["B.m4b"], key["C.m4b"]]


# --------------------------------------------------------------------------- #
# No second authoritative queue — the retry half
# --------------------------------------------------------------------------- #


def test_the_retry_callback_reads_no_queue_of_any_kind():
    """**Structural.** A retry that consulted the manager would be a new run.

    ``test_m4b_retry`` bans the names a second *planning* pass would need. This
    bans the names a second *queue* would need, which is the Phase 14 invariant
    and a different set.
    """
    body = reached(function("retry_failed"))
    for banned in ("manager", "_manager", "importer", "imported_files",
                   "build_catalog", "catalog", "list", "snapshot"):
        assert banned not in body, banned


def test_a_retry_after_the_queue_is_emptied_still_runs_the_frozen_book(
        make_panel, tmp_path, run_env):
    """The strongest form: there is no live queue left to read at all."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    frozen = panel.run_snapshot
    panel.manager.clear()
    assert panel.manager.count == 0

    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    params = StubThread.started[-1].args[0]
    assert params["snapshot"] is frozen
    assert [entry.path.name for entry in params["imported_files"]] == [
        "A.m4b", "B.m4b"]


def test_start_order_is_the_committed_manager_order_after_reordering(
        make_panel, tmp_path, captured_run):
    """Start freezes what the list *shows*, which is the manager's order."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    listing.select((listing.order[2],))
    listing.move_up()
    assert names(panel) == ["A.m4b", "C.m4b", "B.m4b"]

    panel.start_convert()
    params = StubThread.started[-1].args[0]
    assert [entry.path.name for entry in params["imported_files"]] == [
        "A.m4b", "C.m4b", "B.m4b"]


# --------------------------------------------------------------------------- #
# Decision 14A — the rest of the control surface
# --------------------------------------------------------------------------- #


def test_a_multi_row_selection_removes_exactly_those_rows(make_panel, tmp_path):
    """Extended selection was proved to *exist*; this proves it acts."""
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b", "D.m4b"))
    listing = panel.importer.list
    a, b, _c, d = listing.order

    listing.select((b, d))
    assert listing.selected_count == 2
    listing.remove_selected()

    assert names(panel) == ["A.m4b", "C.m4b"]
    assert listing.order[0] == a, "the survivors keep their occurrence ids"
    assert panel.manager.snapshot().occurrence_ids == listing.order


def test_a_multi_row_selection_moves_as_a_block(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    a, b, c = listing.order

    listing.select((b, c))
    listing.move_up()

    assert names(panel) == ["B.m4b", "C.m4b", "A.m4b"]
    assert listing.order == (b, c, a), "identity survives a block move"
    assert set(listing.selection) == {b, c}


def test_every_control_locks_for_a_retry_and_unlocks_after_it(
        make_panel, tmp_path, run_env):
    """A retry is a second attempt at one run, and it locks like the first.

    Nothing asserted this: the retry path calls the same ``disable_inputs`` the
    run does, so it worked, but a future edit could drop the call and only a
    person driving the window would notice.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b", "B.m4b"))
    run_env["fail"] = ("B.m4b",)
    work(panel, tmp_path, run_env)

    listing, options = panel.importer.list, panel.importer.options
    assert listing.locked is False, "the finished run unlocked the panel"

    assert panel.jobs.controls.invoke(jc.JobAction.RETRY_FAILED) is True
    assert listing.locked is True and options.locked is True
    for key in ("add_files", "add_folder", "move_up", "move_down",
                "remove", "clear"):
        assert str(listing.buttons[key].cget("state")) == "disabled", key

    panel._finish_idle()
    assert listing.locked is False and options.locked is False


def test_clear_all_is_transactional_and_leaves_no_stale_selection(
        make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    listing.select(listing.order[:2])

    listing.clear()

    assert panel.manager.count == 0
    assert listing.order == () and listing.selection == ()
    assert panel.imported_files() == []
    # And the panel is usable again straight afterwards.
    add_files(panel, *books(tmp_path / "again", "D.m4b"))
    assert names(panel) == ["D.m4b"]


# --------------------------------------------------------------------------- #
# Decision 16A — one supported type, under mutation
# --------------------------------------------------------------------------- #


def test_disabling_the_type_declines_new_imports_without_emptying_the_queue(
        make_panel, tmp_path):
    """Turning the type off is a filter on what may *enter*, not a purge.

    Silently dropping what a person already queued would be the worst possible
    reading of an unchecked box.
    """
    panel = make_panel()
    add_files(panel, *books(tmp_path / "first", "Kept.m4b"))
    panel.importer.options.set_types(())

    outcome = add_files(panel, *books(tmp_path / "second", "Refused.m4b"))
    assert outcome.status is OutcomeStatus.NO_TYPES_SELECTED
    assert names(panel) == ["Kept.m4b"], "the existing queue survived"

    panel.importer.options.set_types(("m4b",))
    add_files(panel, *books(tmp_path / "third", "Later.m4b"))
    assert names(panel) == ["Kept.m4b", "Later.m4b"]


def test_a_disabled_type_still_lets_the_frozen_run_finish(
        make_panel, tmp_path, run_env):
    """The catalog governs importing. It cannot reach a run already frozen."""
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    params = None
    panel.start_convert()
    params = StubThread.started[-1].args[0]

    panel.importer.options.set_types(())
    assert [entry.path.name for entry in params["imported_files"]] == ["A.m4b"]


def test_the_input_extension_is_named_once_and_only_by_the_catalog():
    """**Structural.** The catalog is the single filter.

    A second literal ``".m4b"`` compared anywhere else in the panel would be a
    second, unversioned answer to "what may this tool open" -- which is exactly
    how a single-type contract quietly becomes two. So the guard is not that the
    string is absent, but that it appears **once**, inside ``build_catalog``,
    where Decision 16A put it.
    """
    tree = parse_panel()
    everywhere = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and node.value == ".m4b"]
    assert len(everywhere) == 1, f"{len(everywhere)} places name the input type"

    declaration = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "build_catalog")
    assert any(node is everywhere[0] for node in ast.walk(declaration)), (
        "the input extension is named outside build_catalog")
    assert m4b_converter.build_catalog().extensions == (".m4b",)


# --------------------------------------------------------------------------- #
# Recursion — frozen per import, and reflected in the output
# --------------------------------------------------------------------------- #


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Library"
    books(root, "Top.m4b")
    books(root / "Series", "Nested.m4b")
    return root


def test_two_imports_on_one_panel_may_disagree_about_recursion(
        make_panel, library, tmp_path):
    """Each import freezes the value that was set when *it* started.

    The shared contract proves the scanner reads its own frozen request. This
    proves the live panel really can produce two such requests in a row, which
    is what a person does when they toggle the box between folders.
    """
    other = tmp_path / "Other"
    books(other, "Root.m4b")
    books(other / "Deep", "Buried.m4b")

    panel = make_panel()
    add_folder(panel, library)
    assert sorted(names(panel)) == ["Nested.m4b", "Top.m4b"]

    panel.importer.options.set_include_subfolders(False)
    add_folder(panel, other)

    assert sorted(names(panel)) == ["Nested.m4b", "Root.m4b", "Top.m4b"]
    assert "Buried.m4b" not in names(panel), (
        "the second import used the first import's recursion")


def test_re_enabling_recursion_applies_to_the_next_import_only(
        make_panel, library, tmp_path):
    panel = make_panel()
    panel.importer.options.set_include_subfolders(False)
    add_folder(panel, library)
    assert names(panel) == ["Top.m4b"]

    deeper = tmp_path / "Deeper"
    books(deeper, "Root.m4b")
    books(deeper / "Inner", "Found.m4b")
    panel.importer.options.set_include_subfolders(True)
    add_folder(panel, deeper)

    assert sorted(names(panel)) == ["Found.m4b", "Root.m4b", "Top.m4b"]


def test_a_shallow_import_mirrors_only_what_it_imported(
        make_panel, library, tmp_path, captured_run):
    """Output mirroring follows the frozen snapshot, not the folder on disk.

    ``Series/`` exists under the chosen root, and a mirrored planner that read
    the filesystem rather than the provenance it was given would create it.
    """
    panel = make_panel()
    panel.importer.options.set_include_subfolders(False)
    add_folder(panel, library)
    plan = planned_run(panel, tmp_path, captured_run)

    assert planned_of(plan, "Top.m4b") == [plan.run_directory / "Top.mp3"]
    assert len(plan.items) == 1
    every = [segment.destination for item in plan.items for segment in item.segments]
    assert not any("Series" in part for path in every for part in path.parts)


# --------------------------------------------------------------------------- #
# Occurrence identity through the whole run
# --------------------------------------------------------------------------- #


def test_a_refresh_restores_the_rows_by_identity(make_panel, tmp_path):
    panel = make_panel()
    add_files(panel, *books(tmp_path, "A.m4b", "B.m4b", "C.m4b"))
    listing = panel.importer.list
    before = listing.order
    listing.select((before[1],))

    listing.refresh(selection=(before[1],))

    assert listing.order == before
    assert listing.selection == (before[1],)
    assert names(panel) == ["A.m4b", "B.m4b", "C.m4b"]


def test_duplicate_occurrences_stay_distinct_in_the_settled_result(
        make_panel, tmp_path, run_env):
    """One path, two occurrences, two different outcomes.

    A result keyed on the path could report only one of these, and whichever it
    chose would be wrong for the other. This is the collapse Phase 14 refuses.

    **Why the failure is selected by a full prefix and not by a substring.**
    This test used to fail whichever command merely *contained* ``"Twice-1"``.
    Each encode writes to ``.act-tmp-<stem>-<token>``, and ``mkstemp`` draws that
    token from ``abcdefghijklmnopqrstuvwxyz0123456789_`` — so roughly one run in
    thirty-seven the *first* occurrence's own temporary file was called
    ``.act-tmp-Twice-1a2b3c4d.mp3``, matched too, and was failed as well. The
    test then reported both occurrences FAILED and looked like a duplicate-
    identity defect; production was correct every time. ``-`` is not in that
    alphabet, so requiring the trailing separator names the second occurrence's
    output and nothing else.
    """
    source, = books(tmp_path / "src", "Twice.m4b")
    panel = make_panel()
    panel.importer.options.set_allow_duplicates(True)
    add_files(panel, source)
    add_files(panel, source)
    assert panel.manager.count == 2

    second_output = ".act-tmp-Twice-1-"

    def outcome(joined):
        if any(Path(part).name.startswith(second_output) for part in joined):
            return m4b_converter.m4b_execution.ProcessResult(
                1, detail="ffmpeg said no")
        return None

    run_env["outcome"] = outcome
    work(panel, tmp_path, run_env)

    first, second = panel.run_plan.items
    status = status_of(panel.run_result)

    # The invariant: one physical book, two identities, two destinations, two
    # separately settled outcomes. None of this depends on which occurrence the
    # collision suffix lands on.
    assert first.source == second.source, "the same physical book"
    assert first.occurrence_id != second.occurrence_id, "the identities collapsed"
    assert len(status) == 2, "a result keyed on the path would report one"
    assert set(status) == {first.occurrence_id, second.occurrence_id}

    places = {i.occurrence_id: [s.destination for s in i.segments]
              for i in panel.run_plan.items}
    every = [d for paths in places.values() for d in paths]
    assert len(set(every)) == len(every), f"two occurrences shared a path: {every}"
    assert {d.name for d in every} == {"Twice.mp3", "Twice-1.mp3"}

    # Exactly one of them failed, and it is the one whose output was refused.
    failed = [occ for occ, state in status.items() if state is jc.ItemStatus.FAILED]
    succeeded = [occ for occ, state in status.items()
                 if state is jc.ItemStatus.SUCCEEDED]
    assert len(failed) == 1 and len(succeeded) == 1, status
    assert places[failed[0]][0].name == "Twice-1.mp3"
    assert places[succeeded[0]][0].name == "Twice.mp3"


# --------------------------------------------------------------------------- #
# Plan 3 adoption bookkeeping
# --------------------------------------------------------------------------- #


def test_the_two_adoption_tuples_disagree_about_the_converter_on_purpose():
    """``ADOPTED`` is Plan 3; ``UNCONVERTED_PANELS`` is Plan 1. Not the same axis.

    The Converter has adopted the Plan 3 foundation and has **not** had its Plan
    1 visual conversion, so it belongs in both tuples at once. Written down here
    because the natural instinct on finding one name in two "opposite" lists is
    to remove it from one of them, and doing that would either weaken a live
    guard or claim a visual conversion Plan 5 never performed.
    """
    from test_plan3_boundaries import ADOPTED
    from test_preferences_maintenance_ui import UNCONVERTED_PANELS

    assert "mp3_tools/m4b_converter.py" in ADOPTED
    assert "mp3_tools/m4b_converter.py" in UNCONVERTED_PANELS
    assert set(UNCONVERTED_PANELS) == {
        "mp3_tools/cover_resizer.py", "mp3_tools/m4b_converter.py",
        "mp3_tools/m4b_maker.py", "mp3_tools/mp3_tool.py", "tts/epub2tts_gui.py",
    }


def test_the_converter_local_modules_that_adopted_are_exactly_these():
    """Three Converter modules touch Plan 3, and the rest must not start.

    ``test_plan3_boundaries`` measures ``ADOPTED`` against the whole tree. This
    says which of the Converter's **own** modules are entitled to be in it, so
    that a later phase cannot quietly let the executor, the numbering allocator
    or the probe reach for shared job control.
    """
    from test_plan3_boundaries import ADOPTED

    converter_local = {name for name in ADOPTED if name.startswith("mp3_tools/m4b_")}
    assert converter_local == {
        "mp3_tools/m4b_converter.py",
        "mp3_tools/m4b_destinations.py",
        "mp3_tools/m4b_plan.py",
    }


@pytest.mark.parametrize("relative", [
    "m4b_execution.py", "m4b_numbering.py", "m4b_probe.py",
    "m4b_commands.py", "m4b_metadata.py", "m4b_chapters.py",
])
def test_the_pure_converter_modules_import_nothing_shared_and_no_tk(relative):
    """The pure layer stays pure: no Tk, no job control, no importer.

    These are the modules the Converter can test without a window, and that
    property is worth a guard rather than a habit.
    """
    source = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / relative
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for banned in ("tkinter", "shared.job_control", "shared.job_ui",
                   "shared.importing", "shared.import_coordination"):
        assert banned not in imported, (relative, banned)
