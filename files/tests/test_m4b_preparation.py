"""The M4B Maker's and the M4B Metadata Editor's preparation phase — v0.8.2 Checkpoint 2 (large-job responsiveness).

Through v0.8.2 Checkpoint 1 both M4B tools still reserved their output and planned every Book inside the Start button's
own Tk callback, and both planners checked each Book's published and staged path against every source by resolving
every source again: 2·B·N path resolutions for the Maker (126,253 at 250 one-track Books, 18.4 s; 4.7 s at 2,341
tracks in seven Books) and 2N² for the Editor (113,404 at 250 files, 15.2 s), all with "Ready" painted. Checkpoint 2
plans from an input index built once (``shared.output_paths.InputIndex``) and moves reserving -- and, for a custom
Maker build, validating the folder and making its owned work area -- and planning onto one preparation worker per
press (``m4b.m4b_preparation``), as Checkpoint 1 did for the MP3 Tool.

What this module proves:

- the planners do linear work (counted, at 250 / 2,341 / 5,000), plan exactly what they planned before, honour a
  checkpoint and refuse a capture that is not of the workspace being planned;
- the shared hand-off decides offer / adopt / withdraw once each, releases what it reserved before its one ending,
  and throttles progress;
- through each real panel, on a real Tk event loop: the press returns at once with "Preparing job…" and Cancel, the
  heartbeat keeps going, and the run starts only once the plan is adopted; Cancel, Close, stale and duplicate
  endings, repeated presses, refusals, faults, a job area that cannot be built or retired and a processing worker
  that cannot start all leave the panel usable, the previous Retry Failed intact until ownership changes hands, and
  nothing reserved behind; no preparation or processing worker ever calls into Tk;
- what the user typed -- a Chapter Titles paste no key release reported included -- is what the plan freezes, the
  output preferences are the ones in force at the press, and Remove Series Numbering still freezes no pending edit.

Synthetic placeholders under ``tmp_path`` only (the planners and the preparation read no media); the engines are
replaced where media would start. Real FFmpeg output is covered by the migrated end-to-end panel tests.
"""

from __future__ import annotations

import ast
import json
import sys
import threading
import time
import types
from dataclasses import replace
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import config as shared_config  # noqa: E402
from shared import importing as imp  # noqa: E402
from shared import job_ui, output_paths  # noqa: E402
from shared.book_workspace import SharedMetadata, select_book, set_shared_metadata  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from m4b import m4b_preparation as prep  # noqa: E402
from m4b.maker import m4b_maker, m4b_maker_plan as mkp, m4b_maker_workflow as mkw  # noqa: E402
from m4b.metadata import m4b_metadata_editor as editor  # noqa: E402
from m4b.metadata import m4b_metadata_plan as edp, m4b_metadata_workflow as edw  # noqa: E402

import test_import_coordination as tic  # noqa: E402
from test_import_coordination import RealThreads, RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_maker_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    SIDE_THREADS,
    output_base,
    processing_workers,
    tk_root,
    wait_until_prepared,
    windows_theme,
)

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


# --------------------------------------------------------------------------- #
# Synthetic workspaces (no media is read)
# --------------------------------------------------------------------------- #


def maker_library(root: Path, tracks_total: int, books: int = 7) -> Path:
    """*tracks_total* empty placeholder MP3s dealt round-robin into *books* Book folders."""
    for number in range(tracks_total):
        folder = root / f"Book {number % books + 1:05d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{number:05d} Chapter.mp3").write_bytes(b"")
    return root


def _scan(root: Path, catalog, ids):
    effective = make_config()
    options = imp.ImportOptions.for_catalog(catalog, include_subfolders=True)
    request = imp.ScanRequest("scan", (imp.ImportRoot("root", root, 0),), catalog, options, effective)
    return imp.ImportedFileSnapshot(imp.Revision(1), imp.scan_roots(request, id_factory=ids).files)


def maker_workspace(root: Path, ids: imp.IdFactory):
    space = mkw.import_folder(mkw.new_workspace(id_factory=ids), _scan(root, mkw.MAKER_CATALOG, ids),
                              id_factory=ids).workspace
    return set_shared_metadata(space, SharedMetadata(
        mkw.SHARED_FIELDS, {**space.shared.values, "artist": "Shared Narrator"})).workspace


def editor_library(root: Path, files: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for number in range(files):
        (root / f"Book {number:05d}.m4b").write_bytes(b"")
    return root


def editor_workspace(root: Path, ids: imp.IdFactory, *, chapters: int = 12, unreadable_every: int = 10):
    """One Book per file; every *unreadable_every*-th source unreadable; *chapters* titles per readable source."""
    def reader(path):
        number = int(path.stem.split()[-1])
        if unreadable_every and number % unreadable_every == unreadable_every - 1:
            raise ValueError("synthetic unreadable source")
        return {"title": f"Title {number}", "artist": "Narrator", "album": "Album", "series": "Saga",
                "series_part": str(number + 1), "has_cover": True}

    titles = tuple(f"Chapter {n + 1}" for n in range(chapters))
    received = edw.import_folder(edw.new_workspace(id_factory=ids), _scan(root, edw.EDITOR_CATALOG, ids),
                                 id_factory=ids, store=edw.ObservationStore(), reader=reader,
                                 chapters=lambda _path: titles)
    space = set_shared_metadata(received.mutation.workspace, SharedMetadata(
        edw.SHARED_FIELDS, {**received.mutation.workspace.shared.values, "genre": "Shared Genre"})).workspace
    return space, received.store


class Counted:
    """Counts path normalisations, one-shot input guards and index lookups while active."""

    def __init__(self, monkeypatch) -> None:
        self.normalise = self.one_shot = self.lookups = 0
        real_normalise, real_guard = output_paths._normalise, output_paths.assert_not_input
        real_lookup = output_paths.InputIndex.assert_not_input

        def normalise(path):
            self.normalise += 1
            return real_normalise(path)

        def guard(destination, inputs):
            self.one_shot += 1
            return real_guard(destination, inputs)

        def lookup(index, destination):
            self.lookups += 1
            return real_lookup(index, destination)

        monkeypatch.setattr(output_paths, "_normalise", normalise)
        monkeypatch.setattr(output_paths, "assert_not_input", guard)
        monkeypatch.setattr(output_paths.InputIndex, "assert_not_input", lookup)


def _reservation(tmp_path: Path, name: str) -> output_paths.RunReservation:
    run = tmp_path / "Outputs" / name
    run.mkdir(parents=True)
    return output_paths.RunReservation(tool_key="test", base_directory=tmp_path / "Outputs",
                                       tool_directory=tmp_path / "Outputs", run_directory=run, run_number=1)


def plan_maker(space, ids, destination, **kwargs):
    return mkp.plan_run(space, options=mkp.MakerRunOptions(), destination=destination,
                        catalog=mkw.MAKER_CATALOG, import_options=imp.ImportOptions.for_catalog(mkw.MAKER_CATALOG),
                        effective_config=make_config(), id_factory=ids, **kwargs)


def plan_editor(space, store, ids, reservation, action=edp.EditorAction.SAVE_TAGS, **kwargs):
    return edp.plan_run(space, store, action=action, options=edp.EditorRunOptions(), reservation=reservation,
                        catalog=edw.EDITOR_CATALOG, import_options=imp.ImportOptions.for_catalog(edw.EDITOR_CATALOG),
                        effective_config=make_config(), id_factory=ids, **kwargs)


# --------------------------------------------------------------------------- #
# The planners: linear work, the same plans, cancellable, a capture of this workspace only
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tracks_total, books", [(250, 7), (250, 250), (2341, 7), (5000, 7)],
                         ids=["250-in-7", "250-one-track-books", "2341-in-7", "5000-in-7"])
def test_the_maker_plan_normalises_each_source_once(tmp_path, monkeypatch, tracks_total, books):
    """ffd1621: 3,538 / 126,253 / 32,812 / 70,038 normalisations (2·B·N + N), measured by the CP2 harness."""
    ids = imp.IdFactory("m-")
    space = maker_workspace(maker_library(tmp_path / "Library", tracks_total, books), ids)
    destination = mkp.standard_destination(_reservation(tmp_path, "M4B-Maker-1"))
    counted = Counted(monkeypatch)
    started = time.perf_counter()
    plan = plan_maker(space, ids, destination)
    seconds = time.perf_counter() - started
    print("CP2MEASURE " + json.dumps({"tool": "maker", "n": tracks_total, "books": books, "plan_s": round(seconds, 3),
                                      "normalise": counted.normalise, "lookups": counted.lookups}))
    assert len(plan.books) == books and sum(len(b.sources) for b in plan.books) == tracks_total
    assert counted.one_shot == 0, "no per-output scan of every source is left"
    assert counted.lookups == 2 * books, "each Book's published and staged path is one lookup"
    # One normalisation per source occurrence (the index), one per Book folder and the run (the outside-trees
    # check), and a few per Book for its two planned paths (the lookups and the planner's own containment checks):
    # N + 5B + a constant, measured N + 5B + 3 or less. ffd1621 was 2·B·N + N.
    assert counted.normalise <= tracks_total + 5 * books + 8, counted.normalise


@pytest.mark.parametrize("files", [250, 2341, 5000], ids=["250-files", "2341-files", "5000-files"])
def test_the_editor_plan_normalises_each_source_once(tmp_path, monkeypatch, files):
    """ffd1621: 113,404 normalisations at 250 files (2N² minus the unreadable), 15.2 s."""
    ids = imp.IdFactory("e-")
    space, store = editor_workspace(editor_library(tmp_path / "Library", files), ids, chapters=200)
    counted = Counted(monkeypatch)
    started = time.perf_counter()
    plan = plan_editor(space, store, ids, _reservation(tmp_path, "M4B-Metadata-1"))
    seconds = time.perf_counter() - started
    print("CP2MEASURE " + json.dumps({"tool": "editor", "n": files, "plan_s": round(seconds, 3),
                                      "normalise": counted.normalise, "lookups": counted.lookups}))
    readable = files - files // 10
    assert len(plan.books) == readable and len(plan.capture.skipped) == files - readable
    assert counted.one_shot == 0
    assert counted.lookups == 2 * readable
    # One per source (the index), a few per attempted Book for its two planned paths: N + 4R + 4, measured exactly.
    assert counted.normalise <= files + 4 * readable + 8, counted.normalise


def test_a_maker_plan_from_a_capture_is_the_plan_it_always_was(tmp_path):
    """The panel now takes the capture on Tk and plans on a worker; the plan must not change by it."""
    root = maker_library(tmp_path / "Library", 40, books=5)
    space = maker_workspace(root, imp.IdFactory("m-"))
    space = mkw.set_book_field(space, "chapter_titles", "One\n\nThree").workspace
    reservation = _reservation(tmp_path, "M4B-Maker-1")
    for destination in (mkp.standard_destination(reservation),
                        mkp.custom_destination(root, work_root=tmp_path / "op-work" / "staging")):
        direct = plan_maker(space, imp.IdFactory("p-"), destination)
        capture = mkp.capture_for_run(space, catalog=mkw.MAKER_CATALOG,
                                      import_options=imp.ImportOptions.for_catalog(mkw.MAKER_CATALOG),
                                      effective_config=make_config(), id_factory=imp.IdFactory("p-"))
        prepared = mkp.plan_run(space, options=mkp.MakerRunOptions(), destination=destination, capture=capture)
        assert prepared.books == direct.books and prepared.capture == direct.capture
        assert prepared.books[0].chapter_titles[:2] == ("One", "Three"), "blank lines keep no slot; defaults follow"


@pytest.mark.parametrize("action", list(edp.EditorAction), ids=lambda action: action.value)
def test_an_editor_plan_from_a_capture_is_the_plan_it_always_was(tmp_path, action):
    space, store = editor_workspace(editor_library(tmp_path / "Library", 30), imp.IdFactory("e-"))
    space = edw.set_book_field(space, "chapter_titles", "Renamed\n\nThird").workspace
    space = edw.set_book_field(space, "album", "Edited").workspace
    reservation = _reservation(tmp_path, "M4B-Metadata-1")
    direct = plan_editor(space, store, imp.IdFactory("p-"), reservation, action)
    capture = edp.capture_for_run(space, store, catalog=edw.EDITOR_CATALOG,
                                  import_options=imp.ImportOptions.for_catalog(edw.EDITOR_CATALOG),
                                  effective_config=make_config(), id_factory=imp.IdFactory("p-"))
    prepared = edp.plan_run(space, store, action=action, options=edp.EditorRunOptions(), reservation=reservation,
                            capture=capture)
    assert prepared.books == direct.books and prepared.capture == direct.capture
    assert prepared.capture.skipped_book_ids == direct.capture.skipped_book_ids != ()
    first = prepared.books[0]
    if action is edp.EditorAction.REMOVE_SERIES_NUMBERING:
        assert first.chapter_edits == () and dict(first.book_edits) == {} and first.artwork is None
    else:
        assert first.chapter_edits[0] == "Renamed" and first.book_edits["album"] == "Edited"


def test_a_maker_capture_of_another_workspace_is_refused(tmp_path):
    root = maker_library(tmp_path / "Library", 12, books=3)
    ids = imp.IdFactory("m-")
    space = maker_workspace(root, ids)
    capture = mkp.capture_for_run(space, catalog=mkw.MAKER_CATALOG,
                                  import_options=imp.ImportOptions.for_catalog(mkw.MAKER_CATALOG),
                                  effective_config=make_config(), id_factory=ids)
    destination = mkp.standard_destination(_reservation(tmp_path, "M4B-Maker-1"))
    first = space.books[0]
    moved = mkw.move_tracks(space, (first.files.files[1].occurrence_id,), mkw.UP).workspace
    edited = set_shared_metadata(space, SharedMetadata(mkw.SHARED_FIELDS, {"artist": "Someone Else"})).workspace
    silenced = mkw.set_book_field(space, "silence", "2.5").workspace
    for changed in (moved, edited, silenced):
        with pytest.raises(mkp.PlanError):
            mkp.plan_run(changed, options=mkp.MakerRunOptions(), destination=destination, capture=capture)
    assert mkp.plan_run(space, options=mkp.MakerRunOptions(), destination=destination, capture=capture).books


def test_an_editor_capture_of_another_workspace_or_store_is_refused(tmp_path):
    ids = imp.IdFactory("e-")
    space, store = editor_workspace(editor_library(tmp_path / "Library", 6), ids, unreadable_every=0)
    capture = edp.capture_for_run(space, store, catalog=edw.EDITOR_CATALOG,
                                  import_options=imp.ImportOptions.for_catalog(edw.EDITOR_CATALOG),
                                  effective_config=make_config(), id_factory=ids)
    reservation = _reservation(tmp_path, "M4B-Metadata-1")
    source = edw.source_of(space.books[2])
    unreadable = store.with_observations([edw.SourceObservation(occurrence_id=source.occurrence_id,
                                                                path=source.path, readable=False, error="gone")])
    edited = set_shared_metadata(space, SharedMetadata(edw.SHARED_FIELDS, {"genre": "Other"})).workspace
    for workspace, observed in ((space, unreadable), (edited, store)):
        with pytest.raises(edp.PlanError):
            edp.plan_run(workspace, observed, action=edp.EditorAction.SAVE_TAGS, options=edp.EditorRunOptions(),
                         reservation=reservation, capture=capture)


def test_both_planners_stop_at_a_checkpoint(tmp_path):
    calls = {"n": 0}

    def checkpoint():
        calls["n"] += 1
        if calls["n"] > 25:
            raise ConversionCancelled("stop")

    ids = imp.IdFactory("m-")
    space = maker_workspace(maker_library(tmp_path / "M", 200, books=7), ids)
    with pytest.raises(ConversionCancelled):
        plan_maker(space, ids, mkp.standard_destination(_reservation(tmp_path, "M4B-Maker-1")),
                   checkpoint=checkpoint)
    calls["n"] = 0
    space, store = editor_workspace(editor_library(tmp_path / "E", 200), imp.IdFactory("e-"))
    with pytest.raises(ConversionCancelled):
        plan_editor(space, store, imp.IdFactory("e2-"), _reservation(tmp_path, "M4B-Metadata-1"),
                    checkpoint=checkpoint)


# --------------------------------------------------------------------------- #
# The shared hand-off (Tk-free)
# --------------------------------------------------------------------------- #


def test_offer_adopt_and_withdraw_are_one_decision_each():
    first = prep.Preparation(label="Build", inputs=None, number=1)
    assert first.offer("plan") is True and first.offer("again") is False, "a replayed body cannot replace it"
    assert first.adopt() == "plan" and first.adopt() is None
    second = prep.Preparation(label="Build", inputs=None, number=2)
    assert second.offer("plan") is True
    assert second.withdraw() == "plan", "the caller releases what was offered"
    assert second.adopt() is None and second.offer("late") is False
    with pytest.raises(ConversionCancelled):
        second.checkpoint()


@pytest.mark.parametrize("ending", ["prepared", "refused", "fault", "cancelled", "offer-refused", "reserve-refused"])
def test_the_worker_releases_what_it_reserved_before_its_one_ending(ending):
    preparation = prep.Preparation(label="Save Tags", inputs=None, number=1)
    events: list = []

    def reserve():
        if ending == "reserve-refused":
            raise prep.Refusal("The output folder cannot be created.", "denied")
        events.append("reserved")
        return "run"

    def build(holding, progress):
        progress(0, 2)
        progress(1, 2)
        progress(2, 2)
        if ending == "refused":
            raise ValueError("two Books would write the same file")
        if ending == "fault":
            raise RuntimeError("broken")
        if ending == "cancelled":
            raise ConversionCancelled("stop")
        if ending == "offer-refused":
            preparation.withdraw()
        return "plan"

    prep.prepare(preparation, lambda message: events.append(message), reserve=reserve, build=build,
                 release=lambda holding: events.append(f"released {holding}"),
                 refusal=lambda exc: prep.Refusal(f"Save Tags: {exc}") if isinstance(exc, ValueError) else None)
    endings = [event for event in events if isinstance(event, prep.PreparationMessage) and event.kind != prep.PROGRESS]
    assert len(endings) == 1 and events[-1] is endings[0], "exactly one ending, and it is the last message"
    expected = {"prepared": prep.PREPARED, "refused": prep.REFUSED, "fault": prep.FAULT,
                "cancelled": prep.CANCELLED, "offer-refused": prep.CANCELLED, "reserve-refused": prep.REFUSED}
    assert endings[0].kind == expected[ending]
    released = [event for event in events if event == "released run"]
    if ending == "prepared":
        assert released == [] and preparation.adopt() == "plan"
    elif ending == "reserve-refused":
        assert released == [] and endings[0].text == "The output folder cannot be created."
    else:
        assert released == ["released run"] and events.index("released run") < events.index(endings[0])
    if ending == "refused":
        assert endings[0].text == "Save Tags: two Books would write the same file"
    if ending == "fault":
        assert "could not be prepared" in endings[0].text and endings[0].detail == "RuntimeError: broken"


def test_progress_is_throttled_but_the_first_and_last_always_arrive(monkeypatch):
    preparation = prep.Preparation(label="Build", inputs=None, number=1)
    posted: list = []

    def build(_holding, progress):
        for done in range(5001):
            progress(done, 5000)
        return "plan"

    prep.prepare(preparation, posted.append, reserve=lambda: None, build=build, release=lambda _h: None,
                 refusal=lambda _e: None)
    progress = [(m.done, m.total) for m in posted if m.kind == prep.PROGRESS]
    assert progress[0] == (0, 5000) and progress[-1] == (5000, 5000)
    assert len(progress) < 100, len(progress)


def test_the_worker_waits_for_the_paint_only_briefly_and_never_once_withdrawn(monkeypatch):
    """CP2: the worker lets Tk paint the press before planning competes with it for the GIL (5,000 Editor files:
    the repaint took 105-117 ms with the worker already planning, 12-32 ms once it waited). The wait is bounded,
    ends at once on Cancel or Close, and never happens on the main thread (an inline body would wait on itself)."""

    def run(preparation, events):
        prep.prepare(preparation, events.append, reserve=lambda: events.append("reserved"),
                     build=lambda _holding, _progress: "plan", release=lambda _h: events.append("released"),
                     refusal=lambda _e: None)

    def on_worker(preparation, events):
        worker = threading.Thread(target=run, args=(preparation, events), name="prep-test")
        worker.start()
        return worker

    monkeypatch.setattr(prep, "PAINT_WAIT", 20.0)
    painted, events = prep.Preparation(label="Build", inputs=None, number=1), []
    worker = on_worker(painted, events)
    time.sleep(0.2)
    assert events == [], "nothing is reserved before Tk has painted the press"
    painted.painted.set()
    worker.join(10.0)
    assert not worker.is_alive() and events[0] == "reserved" and events[-1].kind == prep.PREPARED

    withdrawn, events = prep.Preparation(label="Build", inputs=None, number=2), []
    worker = on_worker(withdrawn, events)
    time.sleep(0.1)
    started = time.monotonic()
    withdrawn.withdraw()
    worker.join(10.0)
    assert not worker.is_alive() and time.monotonic() - started < 5.0
    assert [event.kind for event in events] == [prep.CANCELLED], "withdrawn while waiting: nothing reserved"

    monkeypatch.setattr(prep, "PAINT_WAIT", 0.05)
    unpainted, events = prep.Preparation(label="Build", inputs=None, number=3), []
    worker = on_worker(unpainted, events)
    worker.join(10.0)
    assert not worker.is_alive() and events[-1].kind == prep.PREPARED, "the wait is bounded"

    monkeypatch.setattr(prep, "PAINT_WAIT", 20.0)
    inline, events = prep.Preparation(label="Build", inputs=None, number=4), []
    started = time.monotonic()
    run(inline, events)
    assert time.monotonic() - started < 5.0 and events[-1].kind == prep.PREPARED, "never waits on the main thread"


def test_the_hand_off_and_the_worker_side_name_no_tk_and_no_panel_state():
    """Static half of the Tk boundary (the dynamic half is the profiler test below)."""
    shared = ast.parse((SCRIPTS / "m4b" / "m4b_preparation.py").read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(shared) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(shared) if isinstance(node, ast.ImportFrom)}
    assert not any("tkinter" in name or "job_ui" in name for name in imported), imported
    for relative, workers in (("m4b/maker/m4b_maker.py",
                               ("_reserve_destination", "_release_destination", "_plan_build", "_build_refusal")),
                              ("m4b/metadata/m4b_metadata_editor.py",
                               ("_reserve_run", "_release_run", "_plan_action", "_action_refusal"))):
        tree = ast.parse((SCRIPTS / relative).read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in workers:
            names = {node.id for node in ast.walk(functions[name]) if isinstance(node, ast.Name)}
            assert not names & {"self", "tk", "ttk", "messagebox"}, (relative, name, names)
        panel = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name in ("M4BMakerUI", "M4BMetadataEditorUI"))
        body = next(node for node in panel.body if isinstance(node, ast.FunctionDef) and node.name == "_prepare")
        reached = {ast.unparse(node) for node in ast.walk(body)
                   if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"}
        assert reached == {"self._prep_q"}, (relative, reached)


# --------------------------------------------------------------------------- #
# The real panels
# --------------------------------------------------------------------------- #


class Tool:
    """One panel under test: how to make it, load a synthetic workspace into it, press it and hold its engine."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.maker = name.startswith("maker")
        self.custom = name == "maker-custom"
        self.module = m4b_maker if self.maker else editor
        self.press_name = {"maker-standard": "build", "maker-custom": "build", "editor-save": "save",
                           "editor-clear": "on_clear_all_tags",
                           "editor-remove": "on_remove_series_numbering"}[name]
        self.prepare_prefix = "m4b-maker-prepare-" if self.maker else "m4b-metadata-prepare-"
        self.release_prefix = "m4b-maker-release-" if self.maker else "m4b-metadata-release-"
        self.start_button = "btn_build" if self.maker else "btn_save"
        self.plan_module = self.module.mp

    def press(self, panel):
        return getattr(panel, self.press_name)()


MAKER_TOOLS = ["maker-standard", "maker-custom"]
EDITOR_TOOLS = ["editor-save", "editor-clear", "editor-remove"]
ALL_TOOLS = MAKER_TOOLS + EDITOR_TOOLS


@pytest.fixture
def panels(tk_root, windows_theme, monkeypatch, output_base, tmp_path):
    """Makes real panels on the shared root with every dialog seam injected; closes them afterwards."""
    made: list = []
    dialogs: list[tuple[str, str]] = []
    import tkinter.messagebox as messagebox

    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: dialogs.append(("error", message)))
    monkeypatch.setattr(messagebox, "showwarning", lambda title, message, **kw: dialogs.append(("warning", message)))
    # The press reads Preferences once; pin them to an in-memory configuration.
    pinned = make_config()
    monkeypatch.setattr(shared_config, "get_effective", lambda *a, **k: pinned)

    def make(tool: Tool, **kwargs):
        kwargs.setdefault("theme", windows_theme)
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("choose_artwork", lambda: "")
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: True)
        kwargs.setdefault("confirm", lambda title, message: True)
        if tool.maker:
            kwargs.setdefault("choose_destination", lambda: "")
            panel = m4b_maker.M4BMakerUI(tk_root, **kwargs)
        else:
            panel = editor.M4BMetadataEditorUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    make.dialogs = dialogs  # type: ignore[attr-defined]
    yield make
    for panel in made:
        panel.close()
        try:
            panel.destroy()
        except tk.TclError:
            pass


def load(tool: Tool, panel, tmp_path: Path, size: int = 21, *, books: int = 7) -> None:
    """A synthetic workspace straight into the panel (what an import commits), then one render."""
    ids = panel._ids
    if tool.maker:
        root = maker_library(tmp_path / f"Library-{size}", size, books)
        panel.workspace = maker_workspace(root, ids)
        if tool.custom:
            chosen = tmp_path / "Chosen"
            chosen.mkdir(exist_ok=True)
            panel.var_custom_dest.set(True)
            panel.var_custom_path.set(str(chosen))
    else:
        panel.workspace, panel.store = editor_workspace(editor_library(tmp_path / f"Library-{size}", size), ids)
    panel.render()


class Engine:
    """Stands in for one tool's per-Book staging: records each Book it is handed, then holds (honouring Cancel at
    its checkpoint, as the real engines do), fails retryably, or fails outright -- so no media is ever made."""

    def __init__(self, monkeypatch, tool: Tool, *, mode: str = "fail") -> None:
        self.books: list = []
        self.started = threading.Event()
        self.mode = mode
        self.threads: list = []
        batch = tool.module.batch
        stage = "encode" if tool.maker else "tags"

        def stage_book(book, *, checkpoint=None, **_kwargs):
            self.books.append(book)
            self.threads.append(threading.current_thread())
            self.started.set()
            while self.mode == "hold":
                checkpoint()
                time.sleep(0.005)
            if self.mode == "retryable":
                return types.SimpleNamespace(cancelled=False, succeeded=False, failure_stage=stage,
                                             failure_message="synthetic failure", failure_detail="for the test")
            raise RuntimeError("the test engine processes nothing")

        monkeypatch.setattr(batch.proc, "stage_book", stage_book)


class PrepareGate:
    """Holds the preparation worker inside planning, at its first checkpoint, until released."""

    def __init__(self, monkeypatch, tool: Tool) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        real = tool.plan_module.plan_run

        def gated(*args, checkpoint, **kwargs):
            def held():
                if not self.entered.is_set():
                    self.entered.set()
                    self.release.wait(20.0)
                checkpoint()
            return real(*args, checkpoint=held, **kwargs)

        monkeypatch.setattr(tool.plan_module, "plan_run", gated)


def pump_until(panel, predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        panel._pump.tick()
        time.sleep(0.005)


def join_all(panel) -> None:
    for thread in panel._thread_factory.made:
        if isinstance(thread, threading.Thread):
            thread.join(20.0)
            assert not thread.is_alive(), thread.name


def runs_left(output_base: Path) -> list[Path]:
    """Every run folder under the standard output base (``<base>/<Tool>-Outputs/<Tool>-N``)."""
    return sorted(run for tool in output_base.glob("*-Outputs") for run in tool.iterdir())


def start_enabled(tool: Tool, panel) -> bool:
    return "disabled" not in getattr(panel, tool.start_button).state()


def take_the_suites_thread_start_collection() -> None:
    """Take the suite's once-per-test thread-start boundary now, outside any timed callback.

    ``tk_gate.finalise_before_thread`` (the suite's ``Thread.start`` hook; production has none) runs one full
    ``gc.collect`` on the main thread at a test's first thread start. Late in a long focused run that collection
    alone took 0.4-0.55 s inside a timed press or Cancel, and 0.8-0.9 s with 1.5 M objects on the heap
    (``files/dev-work/v0.8.2-cp2-evidence/heap_slow_release.py``); taken first, the same press took milliseconds.
    """
    boundary = threading.Thread(target=lambda: None, name="cp2-gate-boundary")
    boundary.start()
    boundary.join()


class TkCallsFromWorkers:
    """The dynamic half of the Tk boundary: every Tcl call and every tkinter-level Python call made on a thread
    other than the main one is recorded, through a profiler set for every thread started while active."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self._main = threading.main_thread()

    def _profile(self, frame, event, arg):
        if threading.current_thread() is self._main:
            return
        if event == "c_call":
            owner = getattr(arg, "__self__", None)
            if owner is not None and type(owner).__name__ == "tkapp":
                self.violations.append(f"{threading.current_thread().name}: Tcl {getattr(arg, '__name__', arg)}")
        elif event == "call" and "/tkinter/" in frame.f_code.co_filename.replace("\\", "/"):
            self.violations.append(f"{threading.current_thread().name}: {frame.f_code.co_name}")

    def __enter__(self):
        threading.setprofile(self._profile)
        return self

    def __exit__(self, *exc):
        threading.setprofile(None)


# -- responsiveness on a real Tk event loop ------------------------------------------------------------------------ #


@pytest.mark.parametrize("tool_name, size, books", [
    ("maker-standard", 2341, 7), ("maker-standard", 250, 250), ("maker-standard", 5000, 7),
    ("maker-custom", 2341, 7), ("editor-save", 250, 0), ("editor-save", 2341, 0), ("editor-save", 5000, 0),
    ("editor-remove", 2341, 0)],
    ids=["maker-2341-in-7", "maker-250-one-track-books", "maker-5000-in-7", "maker-custom-2341",
         "editor-save-250", "editor-save-2341", "editor-save-5000", "editor-remove-2341"])
def test_the_press_returns_at_once_and_tk_keeps_its_heartbeat_while_the_job_is_prepared(
        panels, tmp_path, monkeypatch, tk_root, tool_name, size, books):
    """ffd1621 blocked the press for the whole plan: 4.7 s (Maker, 2,341 in seven Books), 18.4 s (Maker, 250
    one-track Books), 15.2 s (Editor, 250 files). The heartbeat is a real ``after`` chain and the panel's own pump
    adopts the plan, so Tk's event loop drives everything here. The bounds are generous on purpose; the measured
    figures are printed (CP2MEASURE) and recorded in the Handoff."""
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool, mode="hold")
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, size, books=books or 7)
    tk_root.update()
    take_the_suites_thread_start_collection()

    gaps: list[tuple[float, float]] = []
    press: dict = {}
    state = {"last": time.perf_counter(), "beating": True}

    def beat():
        now = time.perf_counter()
        gaps.append((now, now - state["last"]))
        state["last"] = now
        if state["beating"]:
            state["after"] = tk_root.after(20, beat)

    def press_start():
        press["at"] = time.perf_counter()
        press["accepted"] = tool.press(panel)
        press["returned"] = time.perf_counter()
        press["status"] = panel.status.status_text
        press["cancel"] = panel.controls.availability()[JobAction.CANCEL]
        press["pause"] = str(panel.controls.buttons[JobAction.PAUSE].cget("state"))
        press["locked"] = panel.navigator.locked

    state["after"] = tk_root.after(20, beat)
    tk_root.after(60, press_start)
    deadline = time.monotonic() + 180.0
    while not engine.started.is_set():
        assert time.monotonic() < deadline, "the prepared plan was never adopted"
        tk_root.update()
        time.sleep(0.002)
    adopted = time.perf_counter()
    state["beating"] = False
    tk_root.after_cancel(state["after"])
    window = sorted(gap for at, gap in gaps if press["at"] <= at <= adopted)
    panel.cancel()
    pump_until(panel, lambda: not panel.is_running)
    engine.mode = "fail"
    join_all(panel)
    measure = {"tool": tool_name, "n": size, "books": books or None,
               "press_ms": round((press["returned"] - press["at"]) * 1000, 2),
               "press_to_adoption_s": round(adopted - press["at"], 3), "beats": len(window),
               "max_gap_ms": round(window[-1] * 1000, 1) if window else None,
               "p95_gap_ms": round(window[min(len(window) - 1, int(0.95 * len(window)))] * 1000, 1) if window else None}
    print("CP2MEASURE " + json.dumps(measure))
    assert press["accepted"] is True
    assert press["returned"] - press["at"] < 0.5, measure
    assert press["status"] == tool.module.STATUS_PREPARING and press["cancel"] is True and press["locked"] is True
    assert press["pause"] == "disabled", "a preparation has no Pause"
    assert window and window[-1] < 1.0, measure
    names = [thread.name for thread in panel._thread_factory.made]
    assert [name for name in names if name.startswith(tool.prepare_prefix)] == [f"{tool.prepare_prefix}1"]
    assert len(processing_workers(panel)) == 1, "one processing worker, started only after adoption"
    assert panel.last_result.state is JobState.CANCELLED


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-save"])
def test_the_worker_plans_only_after_tk_has_painted_the_press(panels, tmp_path, monkeypatch, tk_root, tool_name):
    """The press schedules ``painted`` as an idle callback, after the redraws it queued itself."""
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    gate = PrepareGate(monkeypatch, tool)
    monkeypatch.setattr(prep, "PAINT_WAIT", 20.0)
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 35)
    tk_root.update()

    assert tool.press(panel) is True
    preparation = panel._preparing
    assert not gate.entered.wait(0.3), "planning waits until Tk has painted the press"
    assert not preparation.painted.is_set()
    tk_root.update_idletasks()
    assert preparation.painted.is_set()
    assert gate.entered.wait(20.0), "then it plans at once"
    panel.cancel()
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    assert engine.books == [] and panel.navigator.locked is False and start_enabled(tool, panel)


# -- Cancel, Close, stale and duplicate endings --------------------------------------------------------------------- #


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
def test_cancel_during_preparation_starts_nothing_and_keeps_the_workspace(
        panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    gate = PrepareGate(monkeypatch, tool)
    owned: list = []
    if tool.custom:
        real_new_folder = m4b_maker.work_area.new_folder

        def recording_new_folder(kind):
            folder = real_new_folder(kind)
            owned.append(folder.path)
            return folder

        monkeypatch.setattr(m4b_maker.work_area, "new_folder", recording_new_folder)
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 35)
    before, numbers = panel.workspace, dict(panel.book_numbers)
    chosen_before = sorted((tmp_path / "Chosen").iterdir()) if tool.custom else None

    assert tool.press(panel) is True
    assert gate.entered.wait(20.0)
    assert panel.is_running and panel.is_preparing
    assert panel.navigator.locked is True and not start_enabled(tool, panel)
    assert panel.controls.availability()[JobAction.CANCEL] is True
    panel.cancel()
    assert panel.status.status_text == tool.module.STATUS_CANCELLING_PREPARATION
    assert panel.controls.availability()[JobAction.CANCEL] is False
    panel.cancel()  # a second press changes nothing
    gate.release.set()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)

    assert engine.books == [] and processing_workers(panel) == [], "nothing was started"
    assert panel.job_controller is None and panel.last_plan is None and panel.last_result is None
    assert runs_left(output_base) == [], "the empty run it reserved is released"
    if tool.custom:
        assert owned and not any(path.exists() for path in owned), "the owned work-area entry is closed"
        assert sorted((tmp_path / "Chosen").iterdir()) == chosen_before, "the chosen folder is untouched"
    assert panel.workspace is before and panel.book_numbers == numbers
    assert panel.status.status_text == tool.module.STATUS_PREPARATION_CANCELLED
    assert panel.log.summary[-1].endswith("cancelled before anything was started; the workspace is unchanged.")
    assert panel.navigator.locked is False and start_enabled(tool, panel)


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
def test_a_plan_offered_just_before_cancel_is_never_adopted(panels, tmp_path, monkeypatch, output_base, tool_name):
    """The worker finished and offered its plan; Cancel lands before the pump reads it. Nothing may start, and the
    release goes to a short-lived worker so Cancel never waits on the storage."""
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    threads = RecordingThreads()
    panel = panels(tool, thread_factory=threads)  # inline: the whole preparation runs inside the press
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    assert panel.is_preparing
    if not tool.custom:
        assert len(runs_left(output_base)) == 1
    panel.cancel()
    assert runs_left(output_base) == [], "taken back and released at Cancel"
    assert any(thread.name.startswith(tool.release_prefix) for thread in threads.made)
    pump_until(panel, lambda: not panel.is_running)
    assert engine.books == [] and panel.last_plan is None and panel.job_controller is None
    assert panel.status.status_text == tool.module.STATUS_PREPARATION_CANCELLED


class _InlineExceptReleases:
    """Preparations (and everything else) inline; release workers on real threads."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.made: list = []

    def __call__(self, target, name):
        thread = (threading.Thread(target=target, name=name, daemon=False) if name.startswith(self.prefix)
                  else tic.InlineThread(target, name))
        self.made.append(thread)
        return thread


@pytest.mark.parametrize("tool_name", ["maker-standard", "maker-custom", "editor-save"])
def test_a_slow_release_never_makes_cancel_or_close_wait(panels, tmp_path, monkeypatch, output_base, tool_name):
    """Codex measured 240.77 ms of Cancel on Tk for the MP3 Tool before CP1 R1-5; the same here with 0.4 s of
    injected storage latency, for Cancel and for Close after the plan was offered."""
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    slow: list = []
    real_release, real_close = output_paths.release_if_empty, m4b_maker.work_area.OwnedFolder.close

    def slow_release(reservation):
        slow.append(threading.current_thread())
        time.sleep(0.4)
        return real_release(reservation)

    def slow_close(folder):
        slow.append(threading.current_thread())
        time.sleep(0.4)
        return real_close(folder)

    monkeypatch.setattr(output_paths, "release_if_empty", slow_release)
    monkeypatch.setattr(m4b_maker.work_area.OwnedFolder, "close", slow_close)
    take_the_suites_thread_start_collection()
    callbacks = {}
    for ending in ("cancel", "close"):
        panel = panels(tool, thread_factory=_InlineExceptReleases(tool.release_prefix))
        load(tool, panel, tmp_path / ending, 14)
        assert tool.press(panel) is True and panel.is_preparing  # the plan is offered and waits for the pump
        began = time.perf_counter()
        getattr(panel, ending)()
        callbacks[ending] = time.perf_counter() - began
        if ending == "cancel":
            pump_until(panel, lambda: not panel.is_running)
        join_all(panel)
        assert engine.books == [] and processing_workers(panel) == []
    print("CP2MEASURE " + json.dumps({"tool": tool_name, "injected_s": 0.4,
                                      **{f"{k}_callback_ms": round(v * 1000, 2) for k, v in callbacks.items()}}))
    assert max(callbacks.values()) < 0.2, callbacks
    assert slow and all(thread is not threading.main_thread() for thread in slow)
    assert runs_left(output_base) == []


@pytest.mark.parametrize("tool_name", ["maker-standard", "maker-custom", "editor-save"])
def test_closing_during_preparation_starts_nothing_and_releases_the_run(
        panels, tmp_path, monkeypatch, output_base, tk_root, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    gate = PrepareGate(monkeypatch, tool)
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 21)
    assert tool.press(panel) is True
    assert gate.entered.wait(20.0)
    panel.close()
    gate.release.set()
    join_all(panel)
    assert engine.books == [] and runs_left(output_base) == []
    panel.destroy()
    tk_root.update()
    assert not [entry for entry in tk_root.tk.call("after", "info")]


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-clear"])
def test_closing_after_the_plan_was_offered_releases_it_unadopted(panels, tmp_path, monkeypatch, output_base,
                                                                  tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    assert len(runs_left(output_base)) == 1
    panel.close()
    assert engine.books == [] and runs_left(output_base) == []


class _PrepareTwice:
    """Starts every preparation worker twice (a replayed ending); every other worker once, inline."""

    def __init__(self) -> None:
        self.made: list = []

    def __call__(self, target, name):
        thread = tic.InlineThread(target, name)
        if name.startswith(("m4b-maker-prepare-", "m4b-metadata-prepare-")):
            def twice():
                target()
                target()
            thread = tic.InlineThread(twice, name)
        self.made.append(thread)
        return thread


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-save"])
def test_a_duplicate_preparation_ending_is_never_acted_on(panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    reserved: list = []
    real = output_paths.reserve_run_directory

    def recording(tool_key, **kwargs):
        reserved.append(real(tool_key, **kwargs))
        return reserved[-1]

    monkeypatch.setattr(output_paths, "reserve_run_directory", recording)
    panel = panels(tool, thread_factory=_PrepareTwice())
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    assert len(reserved) == 2, "the replayed body reserved a second run"
    assert not reserved[1].run_directory.exists(), "a second offer is refused, so its own worker released it"
    pump_until(panel, lambda: not panel.is_running)
    assert len(processing_workers(panel)) == 1
    assert {book.staged.parent.parent.parent for book in engine.books} == {reserved[0].run_directory}


def test_a_stale_preparations_offered_plan_is_released_and_never_run(panels, tmp_path, monkeypatch, output_base):
    """A message from a preparation that is no longer current (it was cancelled, a new one began) is never acted on;
    a plan it offered is taken back and its empty run released."""
    tool = Tool("editor-save")
    engine = Engine(monkeypatch, tool)
    held: list = []

    class Hold(tic.InlineThread):
        def start(self):
            if self.name.startswith(tool.prepare_prefix):
                held.append(self.target)
            else:
                super().start()

    panel = panels(tool, thread_factory=RecordingThreads(kind=Hold))
    load(tool, panel, tmp_path, 7)
    assert tool.press(panel) is True
    stale = panel._preparing
    panel.cancel()  # nothing offered yet: the ending will come from the held body
    held[0]()  # the worker runs to its end after Cancel: the offer is refused and it releases its own run
    pump_until(panel, lambda: not panel.is_running)
    assert runs_left(output_base) == [] and engine.books == []
    # Now a stale message that does carry an offered plan reaches the pump of a panel preparing something else.
    assert tool.press(panel) is True
    current = panel._preparing
    stale_plan = types.SimpleNamespace(reservation=output_paths.reserve_run_directory(
        editor.TOOL_KEY, effective=shared_config.get_effective()))
    stale._offered = stale_plan
    panel._prep_q.put(prep.PreparationMessage(stale, prep.PREPARED))
    held[1]()
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    assert current is not stale
    assert not stale_plan.reservation.run_directory.exists(), "the stale plan's run was released, never run"
    assert len(processing_workers(panel)) == 1


@pytest.mark.parametrize("tool_name", ["maker-custom", "editor-remove"])
def test_repeated_presses_while_preparing_make_exactly_one_run(panels, tmp_path, monkeypatch, output_base,
                                                               tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    gate = PrepareGate(monkeypatch, tool)
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    assert gate.entered.wait(20.0)
    for _ in range(3):
        assert tool.press(panel) is False
    assert panel.retry_failed() is False and panel.clear_all_imports() is False
    gate.release.set()
    pump_until(panel, lambda: not panel.is_preparing)
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    names = [thread.name for thread in panel._thread_factory.made]
    assert [name for name in names if name.startswith(tool.prepare_prefix)] == [f"{tool.prepare_prefix}1"]
    assert len(processing_workers(panel)) == 1 and len(engine.books) == 1


# -- refusals, faults, and the previous run's Retry Failed --------------------------------------------------------- #


def _completed_with_failures(tool: Tool, panel, monkeypatch, engine: Engine):
    """A real (engine-stubbed) run whose Books failed retryably: Retry Failed is offered."""
    engine.mode = "retryable"
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    pump_until(panel, lambda: not panel.is_running)
    panel._pump.tick()
    assert panel.last_result.state is JobState.COMPLETED_WITH_FAILURES
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    return panel.jobs, panel.run, panel.last_plan


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
@pytest.mark.parametrize("failure", ["refused", "fault", "reserve-refused"])
def test_a_failed_preparation_keeps_the_previous_runs_retry_and_a_new_start_then_works(
        panels, tmp_path, monkeypatch, output_base, tool_name, failure):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 14)
    jobs, run, plan = _completed_with_failures(tool, panel, monkeypatch, engine)
    runs_before = runs_left(output_base)
    real_plan, real_reserve = tool.plan_module.plan_run, output_paths.reserve_run_directory

    def broken_plan(*args, **kwargs):
        if failure == "refused":
            raise tool.plan_module.PlanError("two Books would write the same file")
        raise RuntimeError("a bug in planning")

    def broken_reserve(tool_key, **kwargs):
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    def broken_folder(directory):
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    real_folder = output_paths.validate_custom_destination
    if failure == "reserve-refused" and tool.custom:
        monkeypatch.setattr(output_paths, "validate_custom_destination", broken_folder)
    elif failure == "reserve-refused":
        monkeypatch.setattr(output_paths, "reserve_run_directory", broken_reserve)
    else:
        monkeypatch.setattr(tool.plan_module, "plan_run", broken_plan)
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    kind, text = panels.dialogs[-1]
    assert kind == "error"
    if failure == "refused":
        assert text.endswith(": two Books would write the same file"), text
    elif failure == "fault":
        assert "could not be prepared" in text, text
    else:
        assert text == "The output folder cannot be created.", text
    assert panel.jobs is jobs and panel.run is run and panel.last_plan is plan, "nothing changed hands"
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True, "Retry Failed is still offered"
    assert panel.status.status_text == tool.module.STATUS_PREPARATION_FAILED
    assert panel.navigator.locked is False and start_enabled(tool, panel)
    assert runs_left(output_base) == runs_before, "what the failed press reserved is released"
    # The failure is repaired; the next press starts a new run, replacing the old one.
    monkeypatch.setattr(tool.plan_module, "plan_run", real_plan)
    monkeypatch.setattr(output_paths, "reserve_run_directory", real_reserve)
    monkeypatch.setattr(output_paths, "validate_custom_destination", real_folder)
    engine.mode = "fail"
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    pump_until(panel, lambda: not panel.is_running)
    assert panel.run is not run and panel.last_plan is not plan and panel.jobs is not jobs
    assert panel.last_result.state is JobState.FAILED


@pytest.mark.parametrize("tool_name", ["maker-standard", "maker-custom", "editor-save"])
def test_a_job_area_that_cannot_be_built_changes_nothing(panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 14)
    jobs, run, plan = _completed_with_failures(tool, panel, monkeypatch, engine)
    runs_before = runs_left(output_base)
    real_init = job_ui.JobAdapter.__init__

    def broken_init(self, *args, **kwargs):
        raise RuntimeError("the job area could not be built")

    monkeypatch.setattr(job_ui.JobAdapter, "__init__", broken_init)
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    monkeypatch.setattr(job_ui.JobAdapter, "__init__", real_init)
    pump_until(panel, lambda: len([t for t in panel._thread_factory.made if t.name.startswith(tool.release_prefix)])
               >= 1, timeout=5)
    assert panels.dialogs[-1][0] == "error" and "could not be started" in panels.dialogs[-1][1]
    assert panel.jobs is jobs and panel.run is run and panel.last_plan is plan
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    assert panel.navigator.locked is False and start_enabled(tool, panel)
    assert runs_left(output_base) == runs_before, "the unadopted plan's empty run is released"
    # And Retry Failed itself, with a job area that cannot be built, changes nothing either.
    monkeypatch.setattr(job_ui.JobAdapter, "__init__", broken_init)
    assert panel.retry_failed() is False
    monkeypatch.setattr(job_ui.JobAdapter, "__init__", real_init)
    assert panel.jobs is jobs and panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    assert panel.retry_failed() is True
    pump_until(panel, lambda: not panel.is_running)


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-save"])
def test_a_previous_job_area_that_cannot_be_retired_does_not_stop_the_new_run(
        panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 14)
    old = panel.jobs

    def refuse_destroy():
        raise tk.TclError("can't destroy this frame")

    old.frame.destroy = refuse_destroy
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    pump_until(panel, lambda: not panel.is_running)
    pump_until(panel, lambda: not panel.navigator.locked, timeout=5)  # the terminal event, drained by the new area
    assert panel.jobs is not old and engine.books, "the new run ran"
    assert any("could not be fully removed" in line for line in panel.log.summary)
    assert panel.navigator.locked is False and start_enabled(tool, panel)
    assert not old.frame.winfo_manager(), "the frame that would not go is out of the layout"
    del old.frame.destroy
    old.frame.destroy()


@pytest.mark.parametrize("tool_name", ["maker-standard", "maker-custom", "editor-save"])
def test_a_processing_worker_that_cannot_start_fails_the_run_and_frees_the_panel(
        panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool)
    inline = RecordingThreads()

    def factory(target, name):
        if name.startswith("m4b-") and not name.startswith(SIDE_THREADS):
            raise RuntimeError("can't start new thread")
        return inline(target, name)

    factory.made = inline.made  # type: ignore[attr-defined]
    panel = panels(tool, thread_factory=factory)
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    pump_until(panel, lambda: not panel.is_running, timeout=10)
    panel._pump.tick()
    assert engine.books == [], "nothing was processed"
    assert panel.last_result is not None and panel.last_result.state is JobState.FAILED
    assert panel.navigator.locked is False and start_enabled(tool, panel)
    assert any("could not be started" in line for line in panel.log.details)


# -- what is frozen ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-save"])
def test_the_run_uses_the_output_preferences_in_force_at_the_press(panels, tmp_path, monkeypatch, output_base,
                                                                   tool_name):
    tool = Tool(tool_name)
    Engine(monkeypatch, tool)
    first = replace(make_config(), output=replace(make_config().output, base_directory=tmp_path / "At Press"))
    later = replace(make_config(), output=replace(make_config().output, base_directory=tmp_path / "Changed Later"))
    monkeypatch.setattr(output_paths, "resolve_output_base",
                        lambda effective=None: (tmp_path / "Hint" if effective is None
                                                else Path(effective.output.base_directory)))
    held: list = []

    class Hold(tic.InlineThread):
        def start(self):
            if self.name.startswith(tool.prepare_prefix):
                held.append(self.target)
            else:
                super().start()

    preferences = {"now": first}
    monkeypatch.setattr(shared_config, "get_effective", lambda *a, **k: preferences["now"])
    panel = panels(tool, thread_factory=RecordingThreads(kind=Hold))
    load(tool, panel, tmp_path, 7)
    assert tool.press(panel) is True
    preferences["now"] = later  # Preferences saved while the press waits to be prepared
    held[0]()
    pump_until(panel, lambda: not panel.is_running)
    root = panel.last_plan.root if tool.maker else panel.last_plan.run_directory
    assert root.is_relative_to(tmp_path / "At Press"), root
    assert not (tmp_path / "Changed Later").exists()
    snapshot = panel.last_plan.books[0].snapshot
    assert snapshot.effective_config is first, "the run's snapshots record the configuration of the press"


def _paste(panel, text: str) -> None:
    """A change that reaches the box without a key release: what a mouse paste or an input method does."""
    panel.chapter_text.winfo_id()
    panel.chapter_text.delete("1.0", "end")
    panel.chapter_text.insert("1.0", text)


@pytest.mark.parametrize("tool_name", ["maker-standard", "editor-save"])
def test_a_pasted_chapter_edit_survives_a_redraw_and_navigation_and_reaches_the_plan(
        panels, tmp_path, monkeypatch, output_base, tool_name):
    tool = Tool(tool_name)
    Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 14)
    first = panel.workspace.current.book_id
    _paste(panel, "Pasted One\nPasted Two")
    # A Shared edit redraws the whole page from the model: the paste must not be painted over.
    if tool.maker:
        panel.on_shared_change("album", "Shared Album")
    else:
        panel.on_shared_change("genre", "Another Genre")
    assert panel.chapter_titles_text() == "Pasted One\nPasted Two"
    _paste(panel, "Pasted One\nPasted Two\nPasted Three")
    panel.on_next()  # navigation commits it to the Book it was typed for, not to the next one
    second = panel.workspace.current
    assert "chapter_titles" not in second.configuration
    assert panel.workspace.books[0].configuration["chapter_titles"] == "Pasted One\nPasted Two\nPasted Three"
    try:
        panel.chapter_text.edit_undo()  # the repaint is not undoable into another Book's titles
    except tk.TclError:
        pass
    panel.on_chapter_edit()
    assert "chapter_titles" not in panel.workspace.current.configuration
    panel.on_select(first)
    assert panel.chapter_titles_text() == "Pasted One\nPasted Two\nPasted Three"
    _paste(panel, "Final One\nFinal Two")
    assert tool.press(panel) is True  # the press commits a paste nothing has reported yet
    wait_until_prepared(panel)
    book = panel.last_plan.book_for(first)
    if tool.maker:
        assert book.chapter_titles[:2] == ("Final One", "Final Two")
    else:
        assert book.chapter_edits[:2] == ("Final One", "Final Two")


def test_remove_series_numbering_commits_a_paste_but_freezes_no_pending_edit(panels, tmp_path, monkeypatch,
                                                                             output_base):
    tool = Tool("editor-remove")
    Engine(monkeypatch, tool)
    panel = panels(tool)
    load(tool, panel, tmp_path, 7)
    panel.set_book_field("title", "Edited Title")
    _paste(panel, "Pasted Chapter")
    assert tool.press(panel) is True
    wait_until_prepared(panel)
    assert panel.workspace.current.configuration["chapter_titles"] == "Pasted Chapter", "the paste is kept"
    for book in panel.last_plan.books:
        assert book.chapter_edits == () and dict(book.book_edits) == {} and dict(book.shared_overrides) == {}
        assert book.artwork is None and not book.writes


def test_the_custom_build_never_stages_in_the_chosen_folder_or_an_unowned_temporary(
        panels, tmp_path, monkeypatch, output_base):
    tool = Tool("maker-custom")
    engine = Engine(monkeypatch, tool)
    owned: list = []
    real_new_folder = m4b_maker.work_area.new_folder

    def recording_new_folder(kind):
        folder = real_new_folder(kind)
        owned.append(folder)
        return folder

    monkeypatch.setattr(m4b_maker.work_area, "new_folder", recording_new_folder)
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 14)
    assert tool.press(panel) is True
    pump_until(panel, lambda: not panel.is_running)
    join_all(panel)
    plan = panel.last_plan
    assert plan.mode is mkp.DestinationMode.CUSTOM and plan.root == tmp_path / "Chosen"
    assert len(owned) == 1 and plan.work_root == owned[0].path / m4b_maker.CUSTOM_STAGING_NAME
    assert all(book.staging_dir.parent == plan.work_root for book in engine.books)
    assert list((tmp_path / "Chosen").iterdir()) == [], "nothing staged among the user's files"
    assert runs_left(output_base) == [], "no standard run was reserved"
    panel.close()
    assert not owned[0].path.exists(), "the owned entry is closed with the tool"


@pytest.mark.skipif(sys.platform != "win32", reason="the worker-to-Tk profiler is exercised on the Windows host")
@pytest.mark.parametrize("tool_name", ["maker-custom", "editor-clear"])
def test_no_preparation_release_or_processing_worker_calls_into_tk(panels, tmp_path, monkeypatch, output_base,
                                                                   tool_name):
    tool = Tool(tool_name)
    engine = Engine(monkeypatch, tool, mode="retryable")
    panel = panels(tool, thread_factory=RealThreads())
    load(tool, panel, tmp_path, 28)
    with TkCallsFromWorkers() as tk_calls:
        assert tool.press(panel) is True
        pump_until(panel, lambda: not panel.is_running)
        assert panel.retry_failed() is True
        pump_until(panel, lambda: not panel.is_running)
        assert tool.press(panel) is True  # a new run replacing a kept one: the release worker runs too
        pump_until(panel, lambda: not panel.is_running)
        join_all(panel)
    names = [thread.name for thread in panel._thread_factory.made]
    assert any(name.startswith(tool.release_prefix) for name in names), names
    assert engine.books and all(thread is not threading.main_thread() for thread in engine.threads)
    assert tk_calls.violations == [], tk_calls.violations[:10]
