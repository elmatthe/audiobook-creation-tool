"""v0.6.0 Drop 2 Phase 4 — the six tools on the shared output service.

Every test injects a temporary output base through the configuration snapshot
and redirects the settings layer at a throwaway file, so nothing here resolves
or writes the maintainer's real Downloads folder, settings, outputs, logs,
``.venv``, model cache, binaries or media. Fixtures are generated, never
copied from the repository's local media.

The through-line: **a run directory exists only because a validated operation
started.** Building a panel, importing, browsing, switching tools or failing
validation must all leave the filesystem untouched.
"""

from __future__ import annotations

import ast
import importlib
import sys
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import config, output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

TOOL_MODULES = {
    "tts": "tts.epub2tts_gui",
    "m4b_converter": "mp3_tools.m4b_converter",
    "mp3_tool": "mp3_tools.mp3_tool",
    "m4b_maker": "mp3_tools.m4b_maker",
    "cover": "mp3_tools.cover_resizer",
    "m4b_metadata": "mp3_tools.m4b_metadata_editor",
}
EXPECTED_PARENTS = {
    "tts": "TTS-Audiobook-Outputs",
    "m4b_converter": "M4B-Converter-Outputs",
    "mp3_tool": "MP3-Tool-Outputs",
    "m4b_maker": "M4B-Maker-Outputs",
    "cover": "Cover-Image-Outputs",
    "m4b_metadata": "M4B-Metadata-Outputs",
}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    """Point the whole application at a temporary output base."""
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    base = tmp_path / "OutputBase"
    snapshot = _snapshot(tmp_path, base)
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    config.invalidate()
    try:
        yield base
    finally:
        app_settings.use_path(None)
        config.invalidate()


def _snapshot(tmp_path: Path, base: Path):
    root = tmp_path / "fakerepo"
    entry = root / "scripts" / "Universal" / "launcher.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("#\n", encoding="utf-8")
    (root / "config.toml").write_text(
        "[project]\n"
        f'version = "{config.DEFAULTS["project.version"]}"\n'
        "[output]\n"
        f'base_directory = "{base.as_posix()}"\n',
        encoding="utf-8",
    )
    return config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)


def mp3_fixture(path: Path) -> Path:
    """A tiny file that stands in for imported media. Never real audio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 64)
    return path


def digest(paths):
    return {p: p.read_bytes() for p in paths}


def tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


# --------------------------------------------------------------------------- #
# Cross-tool: nothing is created before a validated operation starts
# --------------------------------------------------------------------------- #


def test_launcher_startup_creates_no_output_directory(fresh_root, output_base):
    import launcher

    launcher.LauncherApp(fresh_root)
    assert not output_base.exists(), tree(output_base)


@pytest.mark.parametrize("tool_key", sorted(TOOL_MODULES))
def test_building_a_panel_creates_no_output_directory(fresh_root, output_base, tool_key):
    module = importlib.import_module(TOOL_MODULES[tool_key])
    module.build_ui(ttk.Frame(fresh_root))
    fresh_root.update_idletasks()
    assert not output_base.exists(), f"{tool_key} created {tree(output_base)}"


def test_building_every_panel_in_turn_creates_no_output_directory(fresh_root, output_base):
    for name in TOOL_MODULES.values():
        importlib.import_module(name).build_ui(ttk.Frame(fresh_root))
    fresh_root.update_idletasks()
    assert not output_base.exists(), tree(output_base)


def test_switching_tools_repeatedly_creates_no_output_directory(fresh_root, output_base):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    for _ in range(2):
        for spec in app._available_tools():
            app.select_tool(spec.key)
    assert not output_base.exists(), tree(output_base)


def test_opening_preferences_creates_no_output_directory(fresh_root, output_base):
    import launcher

    app = launcher.LauncherApp(fresh_root)
    app.open_preferences()
    assert not output_base.exists(), tree(output_base)


@pytest.mark.parametrize("tool_key", sorted(TOOL_MODULES))
def test_no_panel_promises_an_unreserved_run_number(fresh_root, output_base, tool_key):
    """The display names the tool folder, never a numbered run."""
    module = importlib.import_module(TOOL_MODULES[tool_key])
    ui = module.build_ui(ttk.Frame(fresh_root))
    var = getattr(ui, "var_outdir", None)
    shown = var.get() if var is not None else op.destination_hint(tool_key)
    assert shown.endswith(EXPECTED_PARENTS[tool_key]), shown
    assert not shown.rstrip("/\\").split("-")[-1].isdigit()


# --------------------------------------------------------------------------- #
# Cross-tool: reservation behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool_key", sorted(TOOL_MODULES))
def test_each_tool_reserves_under_its_own_stable_parent(output_base, tool_key):
    reservation = op.reserve_run_directory(tool_key)
    assert reservation.run_directory.parent.name == EXPECTED_PARENTS[tool_key]
    assert reservation.run_directory.parent.parent == output_base
    assert reservation.run_directory.name.endswith("-1")


def test_sequential_operations_reserve_increasing_runs(output_base):
    numbers = [op.reserve_run_directory("cover").run_number for _ in range(3)]
    assert numbers == [1, 2, 3]


def test_concurrent_operations_reserve_distinct_runs(output_base):
    results, errors = [], []
    barrier = threading.Barrier(6)

    def worker():
        try:
            barrier.wait(timeout=10)
            results.append(op.reserve_run_directory("mp3_tool").run_directory)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert len(set(results)) == 6


def test_an_operation_keeps_its_captured_snapshot(output_base, tmp_path):
    reservation = op.reserve_run_directory("tts")
    captured = reservation.config_snapshot

    moved = tmp_path / "MovedLater"
    later = _snapshot(tmp_path, moved)
    assert op.resolve_output_base(later) == moved
    # The running operation still points where it started.
    assert op.resolve_output_base(captured) == output_base
    assert reservation.run_directory.parent.parent == output_base


def test_changing_preferences_affects_only_later_operations(output_base, tmp_path, monkeypatch):
    first = op.reserve_run_directory("cover")
    moved = tmp_path / "Moved"
    monkeypatch.setattr(config, "get_effective", lambda: _snapshot(tmp_path, moved))
    second = op.reserve_run_directory("cover")

    assert first.run_directory.parent.parent == output_base
    assert second.run_directory.parent.parent == moved
    assert first.run_directory.exists(), "the earlier run must not move or vanish"


def test_an_unknown_tool_identifier_is_still_rejected(output_base):
    with pytest.raises(op.UnknownToolError):
        op.reserve_run_directory("not_a_tool")


# --------------------------------------------------------------------------- #
# M4B Converter
# --------------------------------------------------------------------------- #


def test_converter_plans_every_output_inside_the_reserved_run(output_base, tmp_path):
    reservation = op.reserve_run_directory("m4b_converter")
    planner = reservation.planner()
    sources = [mp3_fixture(tmp_path / "a" / "Book.m4b"),
               mp3_fixture(tmp_path / "b" / "Book.m4b")]
    plans = [planner.plan(f"{s.stem}.mp3") for s in sources]

    assert [p.name for p in plans] == ["Book.mp3", "Book-1.mp3"]
    for p in plans:
        assert op.assert_contained(reservation.run_directory, p)


def test_converter_duplicate_stems_from_different_folders_do_not_collide(output_base, tmp_path):
    reservation = op.reserve_run_directory("m4b_converter")
    planner = reservation.planner()
    names = [planner.plan("Book.mp3").name for _ in range(3)]
    assert names == ["Book.mp3", "Book-1.mp3", "Book-2.mp3"]


def test_converter_respects_an_existing_destination(output_base):
    reservation = op.reserve_run_directory("m4b_converter")
    (reservation.run_directory / "Book.mp3").write_bytes(b"already here")
    assert reservation.planner().plan("Book.mp3").name == "Book-1.mp3"


def test_converter_module_reserves_only_at_start(output_base):
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_converter.py").read_text(
        encoding="utf-8"
    )
    assert "reserve_run_directory(TOOL_KEY)" in source
    before, after = source.split("def start_convert", 1)
    assert "reserve_run_directory" not in before, "reservation must not happen at build time"


# --------------------------------------------------------------------------- #
# MP3 Tool — four output-producing actions
# --------------------------------------------------------------------------- #


def test_mp3_tool_has_a_single_reservation_seam(output_base):
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py").read_text(
        encoding="utf-8"
    )
    assert source.count("def _reserve_run") == 1
    # Combine, time edit and ID3 each go through it.
    assert source.count("self._reserve_run()") == 3


def test_mp3_tool_combine_stages_inside_its_own_run(output_base, tmp_path):
    reservation = op.reserve_run_directory("mp3_tool")
    build_dir = reservation.run_directory / "build"
    build_dir.mkdir(parents=True)
    assert op.assert_contained(reservation.run_directory, build_dir / "inputs.txt")
    assert build_dir.parent == reservation.run_directory


def test_mp3_tool_time_edit_and_id3_plan_distinct_destinations(output_base, tmp_path):
    reservation = op.reserve_run_directory("mp3_tool")
    planner = reservation.planner()
    sources = [mp3_fixture(tmp_path / "x" / "Track.mp3"),
               mp3_fixture(tmp_path / "y" / "Track.mp3")]
    plans = [planner.plan(s.name) for s in sources]
    assert [p.name for p in plans] == ["Track.mp3", "Track-1.mp3"]
    for plan, src in zip(plans, sources):
        op.assert_not_input(plan, sources)
        assert plan != src


def test_mp3_tool_time_only_through_write_id3_is_preserved():
    """Entering only a time value must still run through Write ID3 Tags."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "mp3_tool.py").read_text(
        encoding="utf-8"
    )
    assert "abs(delta) > 1e-9" in source, "the time-only branch must remain"
    assert "add_silence_to_mp3" in source and "trim_from_end_mp3" in source


def test_mp3_tool_retired_its_local_run_folder_helper():
    from mp3_tools import mp3_tool

    assert not hasattr(mp3_tool, "next_available_folder")
    assert not hasattr(mp3_tool, "BASE_OUTPUT_DIRNAME")


# --------------------------------------------------------------------------- #
# M4B Maker
# --------------------------------------------------------------------------- #


def test_maker_output_name_is_centrally_sanitised(output_base):
    reservation = op.reserve_run_directory("m4b_maker")
    planned = reservation.planner().plan('My<Book>:Title.m4b')
    assert planned.name == "My_Book__Title.m4b"
    assert op.assert_contained(reservation.run_directory, planned)


def test_maker_collides_safely_against_an_existing_build(output_base):
    reservation = op.reserve_run_directory("m4b_maker")
    (reservation.run_directory / "audiobook.m4b").write_bytes(b"earlier")
    assert reservation.planner().plan("audiobook.m4b").name == "audiobook-1.m4b"


def test_maker_staging_stays_inside_its_run(output_base):
    reservation = op.reserve_run_directory("m4b_maker")
    staging = reservation.run_directory / "build"
    staging.mkdir()
    assert op.assert_contained(reservation.run_directory, staging / "chapters.ffmeta.txt")


def test_maker_has_no_output_base_bypass():
    """Phase 5 added the custom destination; the base-bypassing browse stays gone."""
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_maker.py").read_text(
        encoding="utf-8"
    )
    assert "choose_outdir" not in source, "the old output-folder browse must stay removed"
    assert "Choose custom destination" in source


# --------------------------------------------------------------------------- #
# Cover Image — Option A placeholder plus standard output
# --------------------------------------------------------------------------- #


def test_cover_source_side_toggle_is_off_on_a_fresh_build(fresh_root, output_base):
    """Phase 5 replaced the disabled placeholder with a real, safe-by-default toggle."""
    from mp3_tools import cover_resizer

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    assert ui.chk_source_side.cget("text") == cover_resizer.SOURCE_SIDE_LABEL
    assert ui.var_source_side.get() is False
    assert ui.var_source_action.get() == cover_resizer.ACTION_NUMBERED
    assert ui.effective_mode() == cover_resizer.MODE_STANDARD


def test_cover_choices_are_disabled_until_the_mode_is_enabled(fresh_root, output_base):
    from mp3_tools import cover_resizer

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    assert str(ui.rb_numbered.cget("state")) == "disabled"
    assert str(ui.rb_replace.cget("state")) == "disabled"

    ui.var_source_side.set(True)
    ui._on_source_side_change()
    assert str(ui.rb_numbered.cget("state")) == "normal"
    assert str(ui.rb_replace.cget("state")) == "normal"


def test_cover_turning_the_mode_off_discards_a_replace_selection(fresh_root, output_base):
    from mp3_tools import cover_resizer

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    ui.var_source_side.set(True)
    ui._on_source_side_change()
    ui.var_source_action.set(cover_resizer.ACTION_REPLACE)
    assert ui.effective_mode() == cover_resizer.ACTION_REPLACE

    ui.var_source_side.set(False)
    ui._on_source_side_change()
    assert ui.var_source_action.get() == cover_resizer.ACTION_NUMBERED
    assert ui.effective_mode() == cover_resizer.MODE_STANDARD


def test_cover_rebuilding_the_panel_never_restores_replacement(fresh_root, output_base):
    from mp3_tools import cover_resizer

    first = cover_resizer.build_ui(ttk.Frame(fresh_root))
    first.var_source_side.set(True)
    first.var_source_action.set(cover_resizer.ACTION_REPLACE)

    second = cover_resizer.build_ui(ttk.Frame(fresh_root))
    assert second.var_source_side.get() is False
    assert second.var_source_action.get() == cover_resizer.ACTION_NUMBERED
    assert second.effective_mode() == cover_resizer.MODE_STANDARD


def test_cover_replacement_is_not_persisted_as_a_preference(fresh_root, output_base):
    from mp3_tools import cover_resizer

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    ui.var_source_side.set(True)
    ui.var_source_action.set(cover_resizer.ACTION_REPLACE)
    stored = app_settings.all_settings()
    assert not any("replace" in str(k).lower() or "replace" in str(v).lower()
                   for k, v in stored.items())


def test_cover_standard_output_goes_only_into_the_reserved_run(output_base, tmp_path):
    reservation = op.reserve_run_directory("cover")
    planner = reservation.planner()
    sources = [mp3_fixture(tmp_path / "shoot1" / "cover.jpg"),
               mp3_fixture(tmp_path / "shoot2" / "cover.jpg")]
    plans = [planner.plan(s.name) for s in sources]

    assert [p.name for p in plans] == ["cover.jpg", "cover-1.jpg"]
    for plan, src in zip(plans, sources):
        assert plan.parent == reservation.run_directory
        assert plan.parent != src.parent, "no output beside an imported source"


def test_cover_leaves_imported_originals_untouched(output_base, tmp_path):
    from mp3_tools import cover_resizer

    sources = [mp3_fixture(tmp_path / "src" / "a.jpg"), mp3_fixture(tmp_path / "src" / "b.jpg")]
    before = digest(sources)

    reservation = op.reserve_run_directory("cover")
    planner = reservation.planner()
    for s in sources:
        planned = planner.plan(s.name)
        planned.write_bytes(b"resized")          # stands in for the PIL write

    for path, payload in before.items():
        assert path.read_bytes() == payload
    assert sorted(p.name for p in (tmp_path / "src").iterdir()) == ["a.jpg", "b.jpg"]
    assert cover_resizer.next_version_path  # dormant legacy helper still importable


def _import_into_cover(ui, *paths):
    """Put *paths* into the Cover panel the way the panel itself does.

    v0.6.1 Plan 4 Phase 2 retired the panel's own ``files`` list; the shared
    :class:`~shared.importing.ImportedFileManager` is now the only authority on
    what is imported. Driving the adapter's own dialog seam keeps these tests
    exercising the real direct-file path rather than reaching past it.
    """
    ui.importer._choose_files = lambda: tuple(paths)
    ui.importer.add_files()
    assert ui.imported_files() == list(paths)
    return ui


def test_cover_replacement_requires_all_three_gates(fresh_root, output_base, tmp_path):
    """The Phase 4 "unreachable" guard becomes the Phase 5 three-gate guard."""
    from mp3_tools import cover_resizer

    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "src" / "cover.jpg"
    src.parent.mkdir(parents=True)
    Image.new("RGB", (80, 40), (10, 20, 30)).save(src)

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    _import_into_cover(ui, src)

    # Gate 1 closed: the radio alone is inert.
    ui.var_source_action.set(cover_resizer.ACTION_REPLACE)
    assert ui.effective_mode() == cover_resizer.MODE_STANDARD

    # Gate 2 closed: the toggle alone yields numbered copies.
    ui.var_source_side.set(True)
    ui.var_source_action.set(cover_resizer.ACTION_NUMBERED)
    assert ui.effective_mode() == cover_resizer.ACTION_NUMBERED

    # Both open: still only *reaches* the confirmation, which gate 3 owns.
    ui.var_source_action.set(cover_resizer.ACTION_REPLACE)
    assert ui.effective_mode() == cover_resizer.ACTION_REPLACE


def test_cover_declining_confirmation_starts_nothing(fresh_root, output_base, tmp_path,
                                                     monkeypatch):
    from mp3_tools import cover_resizer

    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "src" / "cover.jpg"
    src.parent.mkdir(parents=True)
    Image.new("RGB", (80, 40), (10, 20, 30)).save(src)
    before = src.read_bytes()

    ui = cover_resizer.build_ui(ttk.Frame(fresh_root))
    _import_into_cover(ui, src)
    ui.var_source_side.set(True)
    ui.var_source_action.set(cover_resizer.ACTION_REPLACE)
    monkeypatch.setattr(ui, "confirm_replacement", lambda count: False)

    ui.start_resize()
    assert src.read_bytes() == before
    assert not output_base.exists(), "declining must not reserve a run"
    strays = [p.name for p in src.parent.iterdir()]
    assert strays == ["cover.jpg"], strays


# --------------------------------------------------------------------------- #
# M4B Metadata Editor
# --------------------------------------------------------------------------- #


def test_metadata_editor_reserves_per_action(output_base):
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_metadata_editor.py"
              ).read_text(encoding="utf-8")
    assert source.count("def _reserve_run") == 1
    assert source.count("self._reserve_run()") == 2   # save/clear share one path


def test_metadata_editor_plans_before_copying(output_base, tmp_path):
    """The plan is made first, so two same-named imports cannot collide."""
    reservation = op.reserve_run_directory("m4b_metadata")
    planner = reservation.planner()
    sources = [mp3_fixture(tmp_path / "one" / "Book.m4b"),
               mp3_fixture(tmp_path / "two" / "Book.m4b")]
    plans = [planner.plan(s.name) for s in sources]
    assert [p.name for p in plans] == ["Book.m4b", "Book-1.m4b"]
    assert len(set(plans)) == 2


def test_metadata_editor_never_targets_an_imported_path(output_base, tmp_path):
    reservation = op.reserve_run_directory("m4b_metadata")
    sources = [mp3_fixture(tmp_path / "in" / "Book.m4b")]
    planned = reservation.planner().plan("Book.m4b")
    op.assert_not_input(planned, sources)
    assert planned != sources[0]
    assert planned.parent == reservation.run_directory


def test_metadata_editor_workers_take_the_batch_planner():
    source = (REPO_ROOT / "scripts" / "Universal" / "mp3_tools" / "m4b_metadata_editor.py"
              ).read_text(encoding="utf-8")
    assert "def _save_worker(" in source and "planner," in source
    assert "def _remove_numbering_worker(self, files: list, outdir: Path, planner)" in source
    assert "planner.plan(f.name)" in source
    assert "avoid_input_overwrite" not in source


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #


def test_tts_reserves_only_after_input_validation():
    source = (REPO_ROOT / "scripts" / "Universal" / "tts" / "epub2tts_gui.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def run_job", 1)[1]
    validation = body.index('messagebox.showwarning("Missing input"')
    reservation = body.index("reserve_run_directory(TOOL_KEY)")
    assert validation < reservation, "validation must come first"


def test_tts_mirroring_uses_the_shared_planner_contract(output_base, tmp_path):
    """One declared root, relative parents preserved, same stems kept apart."""
    reservation = op.reserve_run_directory("tts")
    root = tmp_path / "Library"
    sources = [mp3_fixture(root / "Book A" / "ch1.txt"),
               mp3_fixture(root / "Book B" / "ch1.txt")]
    plan = op.plan_mirrored(reservation.run_directory, sources, root,
                            rename=lambda p: p.stem + ".mp3")
    relatives = [str(i.relative).replace("\\", "/") for i in plan.items]
    assert relatives == ["Book A/ch1.mp3", "Book B/ch1.mp3"]
    assert len(set(plan.destinations)) == 2


def test_tts_flat_single_file_lands_in_the_run_root(output_base, tmp_path):
    # v0.6.1 Plan 4 Phase 5: the fixture was ``novel.epub``. EPUB is no longer an
    # accepted TTS input, so the same flat-placement coverage now runs on a PDF.
    reservation = op.reserve_run_directory("tts")
    source = mp3_fixture(tmp_path / "books" / "novel.pdf")
    plan = op.plan_flat(reservation.run_directory, [source],
                        rename=lambda p: p.stem + ".mp3")
    assert plan.items[0].destination == reservation.run_directory / "novel.mp3"


def test_tts_no_longer_offers_an_output_browse_control():
    source = (REPO_ROOT / "scripts" / "Universal" / "tts" / "epub2tts_gui.py").read_text(
        encoding="utf-8"
    )
    assert "_browse_dir" not in source
    assert 'state="readonly"' in source


# --------------------------------------------------------------------------- #
# Safety, scope and regression
# --------------------------------------------------------------------------- #


def test_no_planned_destination_ever_equals_an_input(output_base, tmp_path):
    sources = [mp3_fixture(tmp_path / "src" / f"f{i}.mp3") for i in range(3)]
    for tool_key in TOOL_MODULES:
        reservation = op.reserve_run_directory(tool_key)
        planner = reservation.planner()
        for s in sources:
            planned = planner.plan(s.name)
            op.assert_not_input(planned, sources)
            assert op.assert_contained(reservation.run_directory, planned)


def test_a_failed_reservation_leaves_no_run_directory(output_base, monkeypatch):
    def refuse(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    with pytest.raises(op.OutputPathError):
        op.reserve_run_directory("cover")
    assert not output_base.exists()


def test_release_if_empty_never_removes_a_sibling_run(output_base):
    first = op.reserve_run_directory("cover")
    (first.run_directory / "produced.jpg").write_bytes(b"out")
    second = op.reserve_run_directory("cover")

    assert op.release_if_empty(second) is True
    assert first.run_directory.exists(), "an unrelated run must survive"
    assert first.run_directory.parent.exists(), "the tool parent must survive"
    assert output_base.exists(), "the output base must survive"


def test_no_tool_reserves_output_outside_an_operation_start():
    """Every reservation sits in an action handler, never in a builder.

    The behavioural proof is above (building a panel creates nothing); this is
    the structural guard that keeps it that way. Attribution is to the
    *innermost* enclosing function, because TTS's ``run_job`` is a closure
    defined inside ``build_ui`` and blaming the builder would be backwards.
    """
    import ast

    starters = {
        "start_convert", "combine_mp3s", "time_edit", "write_id3", "build",
        "start_resize", "convert", "save", "on_clear_all_tags",
        "on_remove_series_numbering", "run_job", "_reserve_run",
    }

    def innermost_reservers(tree_):
        """Names of functions that call reserve_run_directory directly."""
        found = set()
        for node in ast.walk(tree_):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)) and inner is not node:
                    continue  # counted when that nested function is visited
                if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "reserve_run_directory"
                        and _enclosing(tree_, inner) is node):
                    found.add(node.name)
        return found

    for relative in TOOL_MODULES.values():
        path = REPO_ROOT / "scripts" / "Universal" / (relative.replace(".", "/") + ".py")
        tree_ = ast.parse(path.read_text(encoding="utf-8"))
        names = innermost_reservers(tree_)
        assert names, f"{relative} never reserves a run"
        for name in names:
            assert name in starters, f"{relative}: reserved inside {name}"
        assert "build_ui" not in names and "__init__" not in names, relative


def _enclosing(tree_, target):
    """The innermost function definition containing *target*."""
    import ast

    best = None
    for node in ast.walk(tree_):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(child is target for child in ast.walk(node)):
            if best is None or node.lineno > best.lineno:
                best = node
    return best


def test_preferences_still_reserves_no_output():
    """Preferences may now *read* the output service, but never materialise.

    Phase 8's remediation gave Preferences one job in ``output_paths``: telling
    already-built panels that the base changed. That is a display refresh, so the
    old "the name ``output_paths`` must not appear" check no longer expresses the
    rule. This states the actual rule instead, which is strictly stronger: the
    only member Preferences may touch is the refresh helper, and it may not call
    anything that reserves, creates or plans a destination.
    """
    import ast

    from shared import preferences_ui

    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    assert preferences_ui.CLEANUP_PLACEHOLDER_TEXT

    tree = ast.parse(source)
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "output_paths"
    }
    assert used == {"refresh_destination_hints"}, used

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for materialising in ("reserve_run_directory", "ensure_output_base",
                          "ensure_tool_parent", "mkdir", "makedirs", "touch",
                          "plan_destination", "destination_hint"):
        assert materialising not in called, materialising


def test_no_cleanup_coordinator_or_post_exit_behaviour_exists():
    """Phase 6 builds a request; Phase 7 owns everything that acts on one.

    ``preferences_ui`` is exempted from the name check because it now names the
    request type it hands off — the exemption is paid for by the stricter
    behavioural check below, which requires the fail-closed handler.
    """
    for relative in ("shared/output_paths.py", "launcher.py", "shared/bootstrap.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(encoding="utf-8")
        for phase_six_or_seven in ("cleanup_request", "CleanupRequest", "post_exit",
                                   "clear_downloaded_data", "maintenance"):
            assert phase_six_or_seven not in source, f"{relative}: {phase_six_or_seven}"


def test_the_cleanup_handoff_still_fails_closed(tmp_path):
    """A helper that cannot be started must never look like a scheduled cleanup.

    Behavioural rather than textual: the handoff runs against a disposable fake
    root with a spawn that refuses, and must report failure, withdraw its own
    request and leave the tree byte-identical.
    """
    from shared import cleanup_state, maintenance, preferences_ui

    root = tmp_path / "fake-repo"
    (root / "files" / "runtime-data" / "logs").mkdir(parents=True)
    (root / "files" / "runtime-data" / "logs" / "s.log").write_bytes(b"l" * 20)
    before = {p.relative_to(root).as_posix(): p.read_bytes()
              for p in root.rglob("*") if p.is_file()}

    def refuse(_command):
        raise OSError("no such interpreter")

    outcome = cleanup_state.start_cleanup(
        maintenance.build_request(["application_logs"]), root,
        python=Path(sys.executable), spawn=refuse, sleep=lambda _s: None,
    )
    assert bool(outcome) is False
    assert not cleanup_state.request_path(root).exists()
    assert {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()} == before

    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    assert "CLEANUP_FAILED_MESSAGE" in source
    assert "CLEANUP_SCHEDULED_MESSAGE" in source


#: The two tool modules v0.6.1 Plan 4 authorized to adopt the Plan 3 foundation.
#: Written as dotted module paths because that is what ``TOOL_MODULES`` holds; the
#: authoritative list is ``test_plan3_boundaries.ADOPTED``, and the test below
#: proves the two spellings agree rather than trusting that they do.
PLAN3_ADOPTERS = ("mp3_tools.cover_resizer", "tts.epub2tts_gui")


def _tool_path(relative: str) -> Path:
    return REPO_ROOT / "scripts" / "Universal" / (relative.replace(".", "/") + ".py")


def test_no_unadopted_tool_reached_for_the_plan3_foundation():
    """Replaces ``test_no_plan_three_importing_behaviour_arrived`` (Phase 11).

    **Mechanism changed: substring → AST.** The retired version scanned every
    tool's source text for UI wording — ``Cancel Import``, ``Retry Failed``,
    ``Pause/Resume``, ``rolling ETA``, ``Include subfolders`` — and asserted none
    of it had appeared. That was never proof of anything. A label is not
    adoption: Cover and TTS have adopted the foundation and get all five of those
    controls from ``shared/job_ui.py``, so their own sources still contain none
    of those strings and the old guard went on passing while the thing it was
    guarding stopped being true. Equally, a module could have grown its own
    private copy of the whole foundation without ever writing one of those words.

    What replaces it asks the structural question instead, over ``Import`` /
    ``ImportFrom`` / ``Name`` / ``Attribute`` / ``Call`` nodes: does this tool
    import a Plan 3 module, name one of its types, or construct one of its
    objects? Comments and docstrings are invisible to it in both directions.

    The two authorized adopters are excluded by name and checked separately, so
    the guard narrowed rather than weakened: the other four tools are held to
    exactly the boundary Plan 3 approved.
    """
    from test_plan3_boundaries import ADOPTED, assert_no_plan3_adoption

    assert set(PLAN3_ADOPTERS) == {
        entry.removesuffix(".py").replace("/", ".") for entry in ADOPTED
    }, "the two spellings of the adopter list have drifted apart"

    checked = []
    for relative in TOOL_MODULES.values():
        if relative in PLAN3_ADOPTERS:
            continue
        tree = ast.parse(_tool_path(relative).read_text(encoding="utf-8"))
        assert_no_plan3_adoption(tree, relative)
        checked.append(relative)

    assert sorted(checked) == [
        "mp3_tools.m4b_converter",
        "mp3_tools.m4b_maker",
        "mp3_tools.m4b_metadata_editor",
        "mp3_tools.mp3_tool",
    ], checked


def test_both_authorized_adopters_really_did_adopt():
    """The other half of the narrowing, so the exclusion cannot be free.

    Excluding a module from the guard above is only honest if that module has
    genuinely adopted. If Cover or TTS ever stopped importing the foundation,
    the exclusion would be hiding an unchecked panel — so it fails here instead.
    """
    from test_plan3_boundaries import imports_the_plan3_foundation

    for relative in PLAN3_ADOPTERS:
        tree = ast.parse(_tool_path(relative).read_text(encoding="utf-8"))
        assert imports_the_plan3_foundation(tree), relative


def test_the_window_constants_are_unchanged():
    from shared import ui_theme

    assert ui_theme.MIN_SIZE == (920, 600)
    assert ui_theme.DEFAULT_GEOMETRY == "1024x720"


def test_the_version_is_unchanged():
    from shared.version import VERSION

    # v0.6.1 Plan 4 Phase 15 closeout: the bump from 0.5.1 happened here and
    # nowhere else. This guard now pins the approved closeout version.
    assert VERSION == "0.6.1"


# --------------------------------------------------------------------------- #
# Real workers on generated fixtures
# --------------------------------------------------------------------------- #
#
# The planner tests above prove the *destinations*; these run the actual worker
# bodies. A Phase 4 regression that left an orphaned `stem` reference in the
# converter passed every planner test and was only caught by driving the real
# worker — so that path is covered here from now on.

from shared import ffmpeg_utils  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment"
)


def _tone(path: Path, seconds: float = 1.0, freq: int = 440, codec=None) -> Path:
    """A tiny generated audio file. Never repository media."""
    from shared import subprocess_utils as sp

    path.parent.mkdir(parents=True, exist_ok=True)
    args = [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-ac", "2", "-ar", "44100"]
    if codec:
        args += ["-c:a", codec, "-b:a", "64k"]
    args.append(str(path))
    sp.run(args, check=True)
    return path


class _Q:
    """Minimal worker host: a cancel event and a queue, like the real panels."""

    def __init__(self):
        self._cancel_event = threading.Event()
        self._log_q: "queue.Queue" = __import__("queue").Queue()

    def drain(self):
        out = []
        while True:
            try:
                out.append(self._log_q.get_nowait())
            except Exception:
                return out


@needs_ffmpeg
def test_the_converter_worker_actually_writes_into_its_run(output_base, tmp_path):
    from mp3_tools import m4b_converter

    source = _tone(tmp_path / "src" / "Book.m4b", 1.0, 300, codec="aac")
    before = source.read_bytes()
    reservation = op.reserve_run_directory("m4b_converter")

    host = _Q()
    host.progress = type("P", (), {"update": lambda *a: None})()
    params = {
        "quality": 5, "write_tags": True, "title": "", "artist": "", "album_artist": "",
        "album": "", "do_track": False, "start_num": 1, "files": [source],
        "planner": reservation.planner(),
    }
    m4b_converter.M4BConverterUI.convert_worker(host, reservation.run_directory, params)

    produced = sorted(p.name for p in reservation.run_directory.iterdir() if p.is_file())
    assert produced == ["Book.mp3"], host.drain()
    assert source.read_bytes() == before, "the source m4b was modified"


@needs_ffmpeg
def test_the_converter_worker_numbers_duplicate_stems(output_base, tmp_path):
    from mp3_tools import m4b_converter

    a = _tone(tmp_path / "one" / "Book.m4b", 1.0, 300, codec="aac")
    b = _tone(tmp_path / "two" / "Book.m4b", 1.0, 500, codec="aac")
    reservation = op.reserve_run_directory("m4b_converter")

    host = _Q()
    host.progress = type("P", (), {"update": lambda *a: None})()
    params = {
        "quality": 5, "write_tags": False, "title": "", "artist": "", "album_artist": "",
        "album": "", "do_track": False, "start_num": 1, "files": [a, b],
        "planner": reservation.planner(),
    }
    m4b_converter.M4BConverterUI.convert_worker(host, reservation.run_directory, params)

    produced = sorted(p.name for p in reservation.run_directory.iterdir() if p.is_file())
    assert produced == ["Book-1.mp3", "Book.mp3"], host.drain()


@needs_ffmpeg
def test_the_time_edit_worker_writes_copies_into_its_run(output_base, tmp_path):
    from mp3_tools import mp3_tool

    sources = [_tone(tmp_path / "src" / "A.mp3", 1.0, 440),
               _tone(tmp_path / "nested" / "A.mp3", 1.0, 660)]
    before = digest(sources)
    reservation = op.reserve_run_directory("mp3_tool")

    host = _Q()
    host.progress = type("P", (), {"update": lambda *a: None})()
    mp3_tool.MP3ToolUI._time_edit_worker(host, {
        "files": sources, "delta": 0.25,
        "outdir": reservation.run_directory, "planner": reservation.planner(),
    })

    produced = sorted(p.name for p in reservation.run_directory.iterdir() if p.is_file())
    assert produced == ["A-1.mp3", "A.mp3"], host.drain()
    for path, payload in before.items():
        assert path.read_bytes() == payload, "an imported original was modified"


@needs_ffmpeg
def test_the_cover_worker_writes_only_into_its_run(output_base, tmp_path):
    from mp3_tools import cover_resizer

    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "shoot"
    src.mkdir(parents=True)
    (src / "sub").mkdir()
    a = src / "cover.jpg"
    b = src / "sub" / "cover.jpg"
    Image.new("RGB", (200, 400), (200, 30, 30)).save(a)
    Image.new("RGB", (400, 200), (30, 200, 30)).save(b)
    before = digest([a, b])

    reservation = op.reserve_run_directory("cover")
    host = _Q()
    cover_resizer.CoverResizerUI.resize_worker(host, {
        "size": 64, "letterbox": True, "mode": cover_resizer.MODE_STANDARD,
        "files": [a, b], "run_dir": reservation.run_directory,
        "planner": reservation.planner(), "source_planner": None,
    })

    produced = sorted(p.name for p in reservation.run_directory.iterdir() if p.is_file())
    assert produced == ["cover-1.jpg", "cover.jpg"], host.drain()
    for path, payload in before.items():
        assert path.read_bytes() == payload, "an imported original was modified"
    assert sorted(p.name for p in src.iterdir()) == ["cover.jpg", "sub"], \
        "nothing may be written beside a source in Phase 4"
    with Image.open(reservation.run_directory / "cover.jpg") as img:
        assert img.size == (64, 64)
