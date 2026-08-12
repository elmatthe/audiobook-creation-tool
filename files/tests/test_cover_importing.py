"""Cover's adoption of the shared importing foundation — v0.6.1 Plan 4, Phase 2.

Plan 3 built the importing foundation and adopted it nowhere. This is the first
production panel to consume it, so what these tests prove is **composition**:
that Cover reaches for the shared manager, coordinator, poller and adapter
rather than growing its own second copy of any of them, and that the one thing
Phase 2 was allowed to change — where the imported list lives — did not disturb
anything else.

Determinism
-----------
**No test sleeps.** Scans run inline through the approved Phase 4 thread factory,
and the pump is ticked by hand rather than by a real event loop. The three tests
that are genuinely about threads gate on :class:`threading.Event` and join within
a bounded timeout, so a deadlock fails loudly instead of hanging the suite.

Safety
------
Every fixture is generated under ``tmp_path``. Nothing scans the repository, the
real home directory, Downloads, an output base, runtime data or real media.
Nothing opens a dialog — the panel takes its dialogs as callbacks and every test
passes a fake one. Nothing resizes an image, reserves an output, starts a worker
process, or writes a setting outside the panel's own seams.

Scope
-----
Phase 2 changes importing only. Processing still runs on Cover's existing worker
and queue, and the tests below assert that rather than assume it. Nothing here
touches Phase 3's browser views or Phase 4's job control.
"""

from __future__ import annotations

import ast
import sys
import threading
from pathlib import Path, PurePath

import pytest

tk = pytest.importorskip("tkinter")

from shared import image_capabilities as caps  # noqa: E402
from shared.import_coordination import (  # noqa: E402
    ImportCoordinator,
    OutcomeStatus,
)
from shared.importing import (  # noqa: E402
    ImportedFile,
    ProblemCategory,
    ScanOutcome,
    ScanResult,
    scan_roots,
)

from mp3_tools import cover_resizer  # noqa: E402

from test_import_coordination import (  # noqa: E402
    ControlledScanner,
    RecordingThreads,
    cancelled_result,
)
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PANEL_SOURCE = REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "cover_resizer.py"

#: Every wait here is bounded so a deadlock fails rather than hangs.
WAIT = 5.0


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def _clean_capability_cache():
    """The catalog is built from the probe, so no test may inherit a cached one."""
    caps.reset_cache()
    yield
    caps.reset_cache()


def pin_heif(*, decode: bool, encode: bool) -> None:
    """Pin the centralized capability answer to a hypothetical machine."""
    caps.reset_cache()

    def probe():
        return caps.FormatCapability(
            "heif", caps.HEIF_SUFFIXES, decode, encode,
            "" if decode and encode else "pinned by a test")

    caps.heif_capability(probe=probe)


@pytest.fixture()
def make_panel(tk_root):
    """Build a real ``CoverResizerUI`` with deterministic seams, and close it."""
    made: list[cover_resizer.CoverResizerUI] = []

    def build(**kwargs):
        kwargs.setdefault("effective_config", make_config())
        kwargs.setdefault("clock", lambda: 0.0)
        kwargs.setdefault("home", None)
        kwargs.setdefault("thread_factory", RecordingThreads())
        kwargs.setdefault("choose_files", lambda: ())
        kwargs.setdefault("choose_folder", lambda: ())
        kwargs.setdefault("confirm_broad_root", lambda roots: False)
        kwargs.setdefault("confirm_large_result", lambda outcome: False)
        panel = cover_resizer.CoverResizerUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    yield build
    for panel in made:
        panel.close()
        panel.destroy()


def images(folder: Path, *names: str) -> tuple[Path, ...]:
    """Generated placeholder files. Never real media, never repository content."""
    return tuple(touch(folder / name, "not an image") for name in names)


class RecordingScanner:
    """Delegates to the real scanner and keeps every request and result."""

    def __init__(self):
        self.requests = []
        self.results = []

    def __call__(self, request, **kwargs):
        self.requests.append(request)
        result = scan_roots(request, **kwargs)
        self.results.append(result)
        return result


def synthetic_result(request, count: int) -> ScanResult:
    """A completed result of *count* files, built without touching a disk.

    Used only where the interesting number is large: creating a thousand real
    files to exercise one comparison would make the suite slow and prove
    nothing extra.
    """
    root = request.roots[0]
    base = root.path
    files = tuple(
        ImportedFile(
            occurrence_id=f"occ-{index}",
            path=base / f"{index:05d}.jpg",
            source_root=root,
            relative_path=PurePath(f"{index:05d}.jpg"),
            supported_type_id="jpg",
            identity=f"identity-{index}",
        )
        for index in range(count)
    )
    return ScanResult(
        request_id=request.request_id,
        outcome=ScanOutcome.COMPLETED,
        discovered_count=count,
        files=files,
        problems=(),
        completed_at=0.0,
    )


def panel_tree() -> ast.Module:
    return ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"), filename=str(PANEL_SOURCE))


def method_named(name: str, *, owner: str = "CoverResizerUI") -> ast.AST:
    """One method of *owner*, by name. Nested helpers elsewhere cannot match."""
    for node in panel_tree().body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"{owner}.{name} is not defined in cover_resizer.py")


# --------------------------------------------------------------------------- #
# The supported-type catalog follows Phase 1's capability seam
# --------------------------------------------------------------------------- #


def test_the_catalog_always_offers_jpg_jpeg_and_png():
    for decode, encode in ((True, True), (True, False), (False, True), (False, False)):
        pin_heif(decode=decode, encode=encode)
        catalog = cover_resizer.build_catalog()
        by_id = {entry.type_id: entry for entry in catalog.types}
        assert by_id["jpg"].extensions == (".jpg", ".jpeg")
        assert by_id["png"].extensions == (".png",)


def test_heic_is_offered_only_when_the_probe_says_this_machine_can_decode_it():
    pin_heif(decode=True, encode=True)
    assert "heic" in cover_resizer.build_catalog().type_ids

    pin_heif(decode=False, encode=False)
    assert "heic" not in cover_resizer.build_catalog().type_ids
    assert cover_resizer.build_catalog().extensions == (".jpg", ".jpeg", ".png")


def test_a_decode_only_machine_still_offers_heic_for_import():
    """Decode and encode stay separate: readable now, refused at write time."""
    pin_heif(decode=True, encode=False)
    catalog = cover_resizer.build_catalog()
    assert "heic" in catalog.type_ids
    assert catalog.type_for("heic").extensions == (".heic", ".heif")
    # And the output side still refuses, rather than substituting a JPEG.
    with pytest.raises(caps.UnsupportedImageFormat):
        caps.require_encoder(".heic")


def test_every_offered_type_is_selected_by_default(make_panel):
    """Decision 16A: one control per type, all enabled."""
    pin_heif(decode=True, encode=True)
    panel = make_panel()
    assert set(panel.importer.options.selected_type_ids()) == set(
        panel.import_catalog.type_ids)
    assert set(panel.import_catalog.type_ids) == {"jpg", "png", "heic"}


def test_the_panel_reintroduces_no_local_heif_import_or_registration():
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "pillow_heif" not in source
    assert "register_heif_opener" not in source
    imported = {
        alias.name
        for node in ast.walk(panel_tree())
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "pillow_heif" not in imported


# --------------------------------------------------------------------------- #
# The manager is the single source of truth
# --------------------------------------------------------------------------- #


def test_the_panel_keeps_no_parallel_imported_file_list():
    """The `self.files` list, the Listbox and their three buttons are gone."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for retired in ("self.files", "self.listbox", "self.count_var",
                    "def add_files", "def remove_selected", "def clear_list",
                    "def update_count"):
        assert retired not in source, retired
    assigned = {
        target.attr
        for node in ast.walk(panel_tree())
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert "files" not in assigned
    assert "listbox" not in assigned


def test_imported_files_reads_the_manager_snapshot(make_panel, tmp_path):
    chosen = images(tmp_path, "b.jpg", "a.png")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    assert panel.imported_files() == list(chosen)
    assert panel.manager.count == 2
    assert [f.path for f in panel.manager.snapshot().files] == list(chosen)


def test_remove_clear_and_move_all_go_through_the_manager(make_panel, tmp_path):
    chosen = images(tmp_path, "1.jpg", "2.jpg", "3.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    listing = panel.importer.list
    order = panel.manager.snapshot().occurrence_ids

    listing.select((order[2],))
    listing.buttons["move_up"].invoke()
    assert [p.name for p in panel.imported_files()] == ["1.jpg", "3.jpg", "2.jpg"]

    listing.select((order[0],))
    listing.buttons["remove"].invoke()
    assert [p.name for p in panel.imported_files()] == ["3.jpg", "2.jpg"]
    assert panel.manager.count == 2

    listing.select((panel.manager.snapshot().occurrence_ids[0],))
    listing.buttons["move_down"].invoke()
    assert [p.name for p in panel.imported_files()] == ["2.jpg", "3.jpg"]

    listing.buttons["clear"].invoke()
    assert panel.manager.count == 0
    assert panel.imported_files() == []


def test_selection_survives_a_move_because_it_is_kept_by_occurrence_id(
    make_panel, tmp_path
):
    chosen = images(tmp_path, "1.jpg", "2.jpg", "3.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    listing = panel.importer.list
    third = panel.manager.snapshot().occurrence_ids[2]

    listing.select((third,))
    listing.buttons["move_up"].invoke()
    assert listing.selection == (third,), "the same occurrence, at a new row"
    assert panel.manager.snapshot().occurrence_ids.index(third) == 1
    # Never an index and never a path: the row that moved is still selected.
    assert listing.rows()[1].endswith("3.jpg")


def test_removing_a_row_never_touches_the_file_it_points_at(make_panel, tmp_path):
    chosen = images(tmp_path, "keep.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.importer.list.select(panel.manager.snapshot().occurrence_ids)
    panel.importer.list.buttons["clear"].invoke()
    assert chosen[0].exists(), "clearing the list is not a delete"


# --------------------------------------------------------------------------- #
# Add Files: the shared direct-file path
# --------------------------------------------------------------------------- #


def test_add_files_goes_through_the_shared_direct_file_validation(
    make_panel, tmp_path, monkeypatch
):
    """Cover must not grow its own copy of ``validate_direct_files``."""
    import shared.import_coordination as coordination

    seen: list[tuple] = []
    real = coordination.validate_direct_files

    def spy(paths, **kwargs):
        seen.append(tuple(paths))
        return real(paths, **kwargs)

    monkeypatch.setattr(coordination, "validate_direct_files", spy)
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    outcome = panel.importer.add_files()

    assert seen == [chosen], "the shared validator saw the dialog's paths"
    assert outcome.status is OutcomeStatus.COMMITTED
    assert "validate_direct_files" not in PANEL_SOURCE.read_text(encoding="utf-8")


def test_add_files_preserves_the_order_the_dialog_returned(make_panel, tmp_path):
    chosen = images(tmp_path, "10.jpg", "01.jpg", "02.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    assert [p.name for p in panel.imported_files()] == ["10.jpg", "01.jpg", "02.jpg"]
    assert panel.importer.list.rows() == ("1. 10.jpg", "2. 01.jpg", "3. 02.jpg")


def test_a_cancelled_file_dialog_imports_nothing(make_panel):
    panel = make_panel(choose_files=lambda: ())
    assert panel.importer.add_files() is None
    assert panel.manager.count == 0


def test_the_add_files_button_is_wired_to_the_shared_action(make_panel, tmp_path):
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.list.buttons["add_files"].invoke()
    assert panel.manager.count == 1


# --------------------------------------------------------------------------- #
# Add Folder: the coordinator and the shared scanner
# --------------------------------------------------------------------------- #


def test_add_folder_runs_through_the_coordinator_and_the_shared_scanner(
    make_panel, tmp_path
):
    root = tmp_path / "Covers"
    images(root, "01.jpg", "02.png")
    scanner = RecordingScanner()
    threads = RecordingThreads()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=threads)

    panel.importer.list.buttons["add_folder"].invoke()
    panel._pump.tick()

    assert isinstance(panel.importer.coordinator, ImportCoordinator)
    assert len(scanner.requests) == 1, "one request, through the shared scanner"
    assert scanner.requests[0].roots[0].path == root
    assert len(threads.made) == 1, "the coordinator owns the worker, not the panel"
    assert sorted(p.name for p in panel.imported_files()) == ["01.jpg", "02.png"]


def test_folder_import_recurses_and_filters_by_the_catalog(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "top.jpg", "notes.txt")
    images(root / "Disc 1", "inner.png")
    panel = make_panel(choose_folder=lambda: (root,))
    panel.importer.add_folder()
    panel._pump.tick()
    assert sorted(p.name for p in panel.imported_files()) == ["inner.png", "top.jpg"]


def test_a_cancelled_folder_dialog_starts_nothing(make_panel):
    threads = RecordingThreads()
    panel = make_panel(choose_folder=lambda: (), thread_factory=threads)
    assert panel.importer.add_folder() is None
    assert threads.made == []
    assert panel.manager.count == 0


# --------------------------------------------------------------------------- #
# The broad-root warning happens before any worker
# --------------------------------------------------------------------------- #


def test_the_broad_root_warning_is_answered_before_any_worker_starts(
    make_panel, tmp_path
):
    asked: list[tuple] = []
    threads = RecordingThreads()
    images(tmp_path, "01.jpg")
    panel = make_panel(
        home=tmp_path, choose_folder=lambda: (tmp_path,), thread_factory=threads,
        confirm_broad_root=lambda roots: bool(asked.append(roots)))

    panel.importer.add_folder()

    assert asked == [(tmp_path,)], "asked exactly once, on this thread"
    assert threads.made == [], "declining creates no scan worker at all"
    assert panel.importer.coordinator.is_active is False
    assert panel.manager.count == 0


def test_a_declined_broad_root_leaves_the_existing_list_untouched(make_panel, tmp_path):
    already = images(tmp_path / "Existing", "keep.jpg")
    threads = RecordingThreads()
    panel = make_panel(
        home=tmp_path, choose_files=lambda: already,
        choose_folder=lambda: (tmp_path,), thread_factory=threads,
        confirm_broad_root=lambda roots: False)

    panel.importer.add_files()
    revision = panel.manager.revision
    panel.importer.add_folder()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision, "nothing was committed"
    assert threads.made == []


def test_an_accepted_broad_root_goes_on_to_scan(make_panel, tmp_path):
    images(tmp_path, "01.jpg")
    panel = make_panel(home=tmp_path, choose_folder=lambda: (tmp_path,),
                       confirm_broad_root=lambda roots: True)
    panel.importer.add_folder()
    panel._pump.tick()
    assert panel.manager.count == 1


# --------------------------------------------------------------------------- #
# The captured large-result threshold
# --------------------------------------------------------------------------- #


def test_the_configured_threshold_is_captured_onto_the_request(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    scanner = RecordingScanner()
    panel = make_panel(effective_config=make_config(7), choose_folder=lambda: (root,),
                       scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()
    assert scanner.requests[0].large_result_warning_threshold == 7


def test_the_shipped_default_threshold_is_still_one_thousand():
    """The number the next two tests are about, read from the committed file."""
    from shared import config as shared_config

    effective = shared_config.get_effective()
    assert effective.importing.large_result_warning_threshold == 1000


def test_a_result_over_one_thousand_asks_for_confirmation(make_panel, tmp_path):
    from shared import config as shared_config

    root = tmp_path / "Covers"
    root.mkdir()
    asked: list[int] = []
    panel = make_panel(
        effective_config=shared_config.get_effective(),
        choose_folder=lambda: (root,),
        scanner=lambda request, **kw: synthetic_result(request, 1001),
        confirm_large_result=lambda outcome: bool(asked.append(outcome.proposed_count)))

    panel.importer.add_folder()
    panel._pump.tick()

    assert asked == [1001]
    assert panel.manager.count == 0, "a declined confirmation commits nothing"


def test_a_result_exactly_at_the_threshold_does_not_ask(make_panel, tmp_path):
    """§6.7: equal to the threshold is not over it."""
    from shared import config as shared_config

    root = tmp_path / "Covers"
    root.mkdir()
    asked: list[int] = []
    panel = make_panel(
        effective_config=shared_config.get_effective(),
        choose_folder=lambda: (root,),
        scanner=lambda request, **kw: synthetic_result(request, 1000),
        confirm_large_result=lambda outcome: bool(asked.append(outcome.proposed_count)))

    panel.importer.add_folder()
    panel._pump.tick()

    assert asked == [], "exactly at the threshold is committed without a prompt"
    assert panel.manager.count == 1000


def test_accepting_the_confirmation_commits_the_whole_transaction_at_once(
    make_panel, tmp_path
):
    root = tmp_path / "Covers"
    images(root, *[f"{index:02d}.jpg" for index in range(5)])
    panel = make_panel(effective_config=make_config(3), choose_folder=lambda: (root,),
                       confirm_large_result=lambda outcome: True)

    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.manager.count == 5, "all five, or none — never a partial commit"
    panel._pump.tick()
    assert panel.manager.count == 5, "draining again must not commit a second time"


def test_declining_the_confirmation_leaves_the_previous_list_unchanged(
    make_panel, tmp_path
):
    already = images(tmp_path / "Existing", "keep.jpg")
    root = tmp_path / "Covers"
    images(root, *[f"{index:02d}.jpg" for index in range(5)])
    panel = make_panel(effective_config=make_config(3), choose_files=lambda: already,
                       choose_folder=lambda: (root,),
                       confirm_large_result=lambda outcome: False)

    panel.importer.add_files()
    revision = panel.manager.revision
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision


# --------------------------------------------------------------------------- #
# An import that does not finish changes nothing
# --------------------------------------------------------------------------- #


def _panel_with_existing(make_panel, tmp_path, **kwargs):
    already = images(tmp_path / "Existing", "keep.jpg")
    panel = make_panel(choose_files=lambda: already, **kwargs)
    panel.importer.add_files()
    return panel, already


def test_a_failed_scan_leaves_the_previous_list_unchanged(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")

    def exploding(request, **kwargs):
        raise OSError("the volume went away")

    panel, already = _panel_with_existing(
        make_panel, tmp_path, choose_folder=lambda: (root,), scanner=exploding)
    revision = panel.manager.revision
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision


def test_a_cancelled_scan_leaves_the_previous_list_unchanged(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    panel, already = _panel_with_existing(
        make_panel, tmp_path, choose_folder=lambda: (root,),
        scanner=lambda request, **kw: cancelled_result(request, 1))
    revision = panel.manager.revision
    panel.importer.add_folder()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision


def test_closing_the_panel_mid_import_commits_nothing(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel, already = _panel_with_existing(
        make_panel, tmp_path, choose_folder=lambda: (root,), scanner=scanner,
        thread_factory=None)          # a real thread: this test is about closing
    revision = panel.manager.revision

    panel.importer.add_folder()
    assert started.wait(WAIT), "the scanner never started"
    panel.close()
    release.set()
    panel._pump.tick()

    assert panel.imported_files() == list(already)
    assert panel.manager.revision == revision
    assert panel.importer.closed and panel._pump.closed
    assert panel._pump.pending is None, "no callback survived the close"


def test_a_list_that_changed_under_a_held_transaction_keeps_what_was_there(
    make_panel, tmp_path
):
    """The conflict case: confirming late must not lose earlier occurrences."""
    already = images(tmp_path / "Existing", "keep.jpg")
    extra = images(tmp_path / "Existing", "late.jpg")
    root = tmp_path / "Covers"
    images(root, *[f"{index:02d}.jpg" for index in range(5)])

    state: dict[str, object] = {}

    def confirm(outcome):
        # A main-thread mutation while the transaction is held.
        panel = state["panel"]
        panel.manager.commit(panel.manager.plan(
            _direct_result(panel, extra), options=panel.importer.options.options(),
            transaction_id="txn-late"))
        return True

    panel = make_panel(effective_config=make_config(3), choose_files=lambda: already,
                       choose_folder=lambda: (root,), confirm_large_result=confirm)
    state["panel"] = panel
    panel.importer.add_files()
    panel.importer.add_folder()
    panel._pump.tick()

    names = [p.name for p in panel.imported_files()]
    assert names[:2] == ["keep.jpg", "late.jpg"], "nothing earlier was lost"


def _direct_result(panel, paths):
    """A committed-shaped result for *paths*, through the shared validator."""
    from shared.import_coordination import validate_direct_files
    from shared.importing import ImportRoot, RootKind

    root = ImportRoot(root_id="root-late", path=None, order=0,
                      kind=RootKind.DIRECT_FILES)
    return validate_direct_files(
        paths, request_id="req-late", root=root, catalog=panel.import_catalog,
        options=panel.importer.options.options())


# --------------------------------------------------------------------------- #
# Deduplication and deliberate duplicates
# --------------------------------------------------------------------------- #


def test_the_same_file_added_twice_is_not_added_again_by_default(make_panel, tmp_path):
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    outcome = panel.importer.add_files()

    assert panel.manager.count == 1
    assert outcome.added_count == 0
    assert outcome.problems, "the duplicate is reported, not silently dropped"
    assert any(problem.category is ProblemCategory.DUPLICATE
               for problem in outcome.problems)


def test_deduplication_uses_the_shared_identity_contract(make_panel, tmp_path):
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    identity = panel.manager.snapshot().files[0].identity
    assert identity, "every occurrence carries the shared identity"
    panel.importer.add_files()
    assert panel.manager.snapshot().identities == (identity,)


def test_a_deliberate_duplicate_stays_a_separate_selectable_occurrence(
    make_panel, tmp_path
):
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()

    snapshot = panel.manager.snapshot()
    assert snapshot.count == 2
    first, second = snapshot.occurrence_ids
    assert first != second, "two occurrences, not one row counted twice"
    assert snapshot.identities[0] == snapshot.identities[1]
    panel.importer.list.select((second,))
    assert panel.importer.list.selection == (second,), "each is selectable alone"
    assert panel.imported_files() == [chosen[0], chosen[0]]


# --------------------------------------------------------------------------- #
# Truthful reporting, and links that are never followed
# --------------------------------------------------------------------------- #


def test_unsupported_entries_are_reported_and_not_imported(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg", "notes.txt", "clip.mp3")
    scanner = RecordingScanner()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()

    result = scanner.results[0]
    unsupported = result.problems_of(ProblemCategory.UNSUPPORTED_TYPE)
    assert len(unsupported) == 2
    assert {Path(problem.path).name for problem in unsupported} == {
        "notes.txt", "clip.mp3"}
    assert [p.name for p in panel.imported_files()] == ["01.jpg"]


def test_an_unreadable_root_is_reported_rather_than_imported(make_panel, tmp_path):
    missing = tmp_path / "not-there"
    scanner = RecordingScanner()
    panel = make_panel(choose_folder=lambda: (missing,), scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()

    problems = scanner.results[0].problems
    assert problems, "a root that cannot be read is reported"
    assert panel.manager.count == 0


def _make_link(link: Path, target: Path) -> bool:
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            return False
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def test_a_directory_link_is_never_followed(make_panel, tmp_path):
    root = tmp_path / "Covers"
    real = root / "Real"
    images(real, "01.jpg")
    if not _make_link(root / "Link", real):
        pytest.skip("this environment cannot create a directory link or junction")

    scanner = RecordingScanner()
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner)
    panel.importer.add_folder()
    panel._pump.tick()

    assert [p.name for p in panel.imported_files()] == ["01.jpg"], "imported once"
    assert scanner.results[0].problems_of(ProblemCategory.LINK), "the link is reported"


# --------------------------------------------------------------------------- #
# Cancel Import is separate from processing cancellation
# --------------------------------------------------------------------------- #


def test_cancel_import_requests_cancellation_through_the_coordinator(
    make_panel, tmp_path
):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT), "the scanner never started"
    assert panel.importer.cancel_import() is True
    assert panel.importer.coordinator.cancel_requested is True

    release.set()
    panel._pump.tick()
    assert panel.manager.count == 0


def test_cancel_import_never_touches_the_processing_cancel_event(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT)
    panel.importer.cancel_import()
    release.set()
    panel._pump.tick()

    assert panel._cancel_event.is_set() is False, "the resize cancel is untouched"
    assert panel._busy.is_set() is False


def test_the_processing_cancel_never_touches_the_import(make_panel, tmp_path):
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT)
    # A resize is running at the same time; cancelling it must not reach the scan.
    panel._busy.set()
    panel.cancel()
    assert panel._cancel_event.is_set() is True
    assert panel.importer.coordinator.cancel_requested is False

    release.set()
    panel._pump.tick()
    assert panel.manager.count == 1, "the import completed on its own terms"
    panel._busy.clear()


def test_a_running_import_can_still_be_cancelled_while_inputs_are_locked(
    make_panel, tmp_path
):
    """The two coexist: locking the inputs for a resize does not disarm the scan.

    ``disable_inputs`` locks the imported list and the import options as one
    unit, which is what stops a *new* import starting mid-resize. It
    deliberately leaves the import status bar alone, so a scan that was already
    running can still be cancelled — and that cancellation reaches the
    coordinator only.
    """
    root = tmp_path / "Covers"
    images(root, "01.jpg")
    started, release = threading.Event(), threading.Event()
    scanner = ControlledScanner(counts=(1,), started=started, release=release)
    panel = make_panel(choose_folder=lambda: (root,), scanner=scanner,
                       thread_factory=None)

    panel.importer.add_folder()
    assert started.wait(WAIT), "the scanner never started"

    panel._busy.set()
    panel.disable_inputs(True)
    assert panel.importer.list.locked is True
    assert panel.importer.options.locked is True
    assert panel.importer.status.cancel_enabled is True, "the scan is still cancellable"

    assert panel.importer.cancel_import() is True
    assert panel.importer.coordinator.cancel_requested is True
    assert panel._cancel_event.is_set() is False, "the resize cancel stayed clear"

    release.set()
    panel._pump.tick()
    panel._busy.clear()
    panel.disable_inputs(False)
    assert panel.importer.list.locked is False


def test_locking_the_inputs_blocks_a_new_import_from_starting(make_panel, tmp_path):
    chosen = images(tmp_path, "a.jpg")
    panel = make_panel(choose_files=lambda: chosen)
    panel.disable_inputs(True)
    panel.importer.list.buttons["add_files"].invoke()
    panel.importer.list.buttons["add_folder"].invoke()
    assert panel.manager.count == 0, "a locked list starts no import"


def test_the_two_cancellations_are_different_objects(make_panel):
    panel = make_panel()
    assert isinstance(panel._cancel_event, threading.Event)
    cancel_body = ast.unparse(method_named("cancel"))
    assert "_cancel_event" in cancel_body
    assert "importer" not in cancel_body and "coordinator" not in cancel_body


# --------------------------------------------------------------------------- #
# One pump, one owner thread, no worker touching Tk
# --------------------------------------------------------------------------- #


def test_exactly_one_pump_owns_the_panels_scheduled_callbacks(make_panel):
    panel = make_panel()
    assert panel._pump.running is True
    # Phase 3 added the browser's preview drain to this same chain. Two drains,
    # still one pump: the count is what changed, the guarantee below is not.
    assert panel._pump.drain_count == 2, (
        "the processing worker queue and the browser both drain on the one pump")
    assert panel.importer.poller is not None

    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "self.after(" not in source, "the panel's own after-chain is retired"
    assert source.count("MainThreadPump(") == 1


def test_the_old_recurring_after_loop_is_gone_from_the_source():
    """``_pump_queue`` rescheduled itself; its replacement does not."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    assert "_pump_queue" not in source
    drain = method_named("_drain_worker_queue")
    calls = {
        node.func.attr for node in ast.walk(drain)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "after" not in calls, "a drain must never reschedule itself"


def test_the_drain_still_delivers_log_progress_and_done(make_panel):
    panel = make_panel()
    panel._busy.set()
    panel._log_q.put(("log", "hello\n"))
    panel._log_q.put(("progress", (1, 2)))
    panel._log_q.put(("done", "\nAll done. "))
    panel._pump.tick()

    assert "hello" in panel.log.get("1.0", "end")
    assert panel._busy.is_set() is False, "done still returns the panel to idle"


def test_every_import_entry_point_is_fenced_to_the_owner_thread(make_panel):
    panel = make_panel()
    failures: list[Exception] = []

    def offend():
        for action in (panel.importer.add_files, panel.importer.add_folder,
                       panel.importer.cancel_import):
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - the point of the test
                failures.append(exc)

    worker = threading.Thread(target=offend, name="offending-worker")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive()
    assert len(failures) == 3
    assert all(isinstance(exc, __import__("shared.job_ui", fromlist=["x"]).MainThreadError)
               for exc in failures)


def test_the_processing_worker_reads_no_tk_variable_and_no_widget():
    """The Phase 4 crash class this project already paid for once."""
    worker = method_named("resize_worker")
    attributes = {
        node.attr for node in ast.walk(worker) if isinstance(node, ast.Attribute)
    }
    for forbidden in ("var_size", "var_letterbox", "var_source_side",
                      "var_source_action", "var_outdir", "importer", "listbox",
                      "log", "progress", "manager"):
        assert forbidden not in attributes, forbidden
    assert "_log_q" in attributes, "it still reports through the queue"


# --------------------------------------------------------------------------- #
# Processing is unchanged and still frozen at start
# --------------------------------------------------------------------------- #


def test_a_later_import_cannot_mutate_a_run_that_already_started(
    make_panel, tmp_path
):
    first = images(tmp_path, "a.jpg")
    second = images(tmp_path, "b.jpg")
    panel = make_panel(choose_files=lambda: first)
    panel.importer.add_files()

    frozen = panel.imported_files()          # what a run would capture
    panel.importer._choose_files = lambda: second
    panel.importer.add_files()

    assert frozen == list(first), "the captured list is a copy, not a live view"
    assert len(panel.imported_files()) == 2, "the manager did move on"


def test_starting_a_resize_with_an_empty_list_warns_and_starts_nothing(
    make_panel, monkeypatch
):
    from tkinter import messagebox

    warned: list[tuple] = []
    monkeypatch.setattr(messagebox, "showwarning",
                        lambda *a, **k: warned.append(a))
    panel = make_panel()
    panel.start_resize()
    assert warned, "the empty-list warning is unchanged"
    assert panel._busy.is_set() is False


def test_the_processing_worker_and_its_queue_protocol_are_unchanged():
    """Phase 2 changed importing only — nothing about how a resize runs."""
    source = PANEL_SOURCE.read_text(encoding="utf-8")
    for kept in ("def resize_worker", "def start_resize", "def cancel",
                 "def disable_inputs", "def _finish_idle",
                 "threading.Thread(target=self.resize_worker",
                 "output_paths.reserve_run_directory", "SourceSidePlanner",
                 "temporary_sibling", "atomic_replace",
                 "validate_source_for_replacement", "REPLACEABLE_SUFFIXES"):
        assert kept in source, kept
    # And none of Phase 4's vocabulary arrived early.
    for later in ("JobController", "JobAdapter", "capture_run", "RetryRequest",
                  "plan_mirrored", "plan_multi_root", "planning_groups"):
        assert later not in source, later


def test_the_start_of_a_resize_still_reserves_only_after_validation():
    """The run directory is created on a validated start, never at panel build."""
    start = method_named("start_resize")
    body = ast.unparse(start)
    assert body.index("showwarning") < body.index("reserve_run_directory")
    build = method_named("__init__")
    assert "reserve_run_directory" not in ast.unparse(build)
