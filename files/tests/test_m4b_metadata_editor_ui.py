"""The M4B Metadata Editor production panel — v0.6.4 Phase 10.

``mp3_tools/m4b_metadata_editor.py`` is now a thin Tk composition/orchestration
adapter over the completed Editor layers: the shared Plan 6 workspace and its
adapters (``BookNavigator`` with the Editor's action subset,
``SharedMetadataSurface``), the Plan 3 importer and job adapters, the Phase 6
artwork control, the Phase 7 model, the Phase 8 planner and the Phase 9
``EditorRun``. No business rule lives in a widget: every edit asks a model
operation and renders the result; each of the three actions freezes one plan
and hands it to one ``EditorRun``; Retry Failed re-runs that frozen run.

What this file keeps from the v0.6.0 Drop 1 suite it replaces: the panel still
carries only ``ACT.*`` styles on the Windows bundle, leaves the generic ttk
styles alone, themes its classic Tk widgets through ``style_tk_widget``, keeps
its launcher contract, and the developer-only visual fixture still drives the
real panel offline. What changed by design: the batch-global form, the
whole-form ``Canvas`` scroller, the private worker and its busy flag are gone.

Media are the Phase 7 fixtures (real tiny FFmpeg-built containers); every
processing test proves the sources are never written.
"""

from __future__ import annotations

import ast
import sys
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import job_ui, metadata, output_paths, ui_theme  # noqa: E402
from shared.book_workspace import BookDisposition  # noqa: E402
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface  # noqa: E402
from shared.job_control import JobAction, JobState  # noqa: E402

from mp3_tools import m4b_artwork_ui, m4b_metadata_editor as editor  # noqa: E402
from mp3_tools import m4b_metadata_batch as batch  # noqa: E402
from mp3_tools import m4b_metadata_plan as mp  # noqa: E402
from mp3_tools import m4b_metadata_workflow as wf  # noqa: E402
from mp3_tools.m4b_metadata_plan import EditorAction  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_metadata_processing import (  # noqa: E402,F401 - fixtures by import
    audio_md5, container, png, sha,
)
from test_m4b_metadata_workflow import m4b, vendor_series  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py"
FIXTURE_PATH = Path(__file__).with_name("manual_windows_ui_prototype.py")

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT design system only applies on win32")

#: Generic styles the unconverted panels render with. Building the Editor
#: must not disturb one of them.
GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TLabelframe", "TLabelframe.Label",
    "TCheckbutton", "Vertical.TScrollbar", "Horizontal.TProgressbar",
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def windows_theme(tk_root):
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style, platform="win32")
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    base = tmp_path / "Outputs"
    monkeypatch.setattr(output_paths, "resolve_output_base", lambda effective=None: base)
    return base


@pytest.fixture
def make_panel(tk_root, windows_theme, monkeypatch, output_base):
    """A real ``M4BMetadataEditorUI`` on the Windows bundle with deterministic seams."""
    made: list[editor.M4BMetadataEditorUI] = []
    dialogs: list[tuple[str, str]] = []

    def build(**kwargs):
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
        monkeypatch.setattr(editor.messagebox, "showerror",
                            lambda title, message, **kw: dialogs.append(("error", message)))
        monkeypatch.setattr(editor.messagebox, "showwarning",
                            lambda title, message, **kw: dialogs.append(("warning", message)))
        panel = editor.M4BMetadataEditorUI(tk_root, **kwargs)
        made.append(panel)
        return panel

    build.dialogs = dialogs  # type: ignore[attr-defined]
    yield build
    for panel in made:
        panel.close()
        try:
            panel.destroy()
        except tk.TclError:
            pass


def library(container: Path, root: Path) -> Path:
    """Two tagged M4Bs in one directory and one M4A in a subfolder."""
    m4b(container, root / "Alpha.m4b", title="Alpha", artist="Ann", series="Saga",
        series_part="1", genre="Old")
    m4b(container, root / "Beta.m4b", title="Beta", artist="Ann", series="Saga",
        series_part="2", genre="Old")
    m4b(container, root / "More" / "Gamma.m4a", title="Gamma", artist="Ann")
    return root


def import_folder(panel, root: Path):
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    panel._pump.tick()
    return panel.workspace


def add_files(panel, *paths: Path):
    panel._choose_files = lambda: tuple(str(p) for p in paths)
    panel.add_files()
    return panel.workspace


def run_action(panel, method: str = "save") -> bool:
    started = getattr(panel, method)()
    panel._pump.tick()
    return started


def widgets_of(widget, kind) -> list:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found += widgets_of(child, kind)
    return found


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _style_of(widget) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:
        return ""


def _snapshot_generic(style: ttk.Style) -> dict:
    out = {}
    for name in GENERIC_STYLES:
        try:
            layout = style.layout(name)
        except tk.TclError:
            layout = None
        out[name] = (layout, style.configure(name), style.lookup(name, "background"),
                     style.lookup(name, "foreground"), style.map(name))
    return out


def observation(panel):
    return panel.store.for_book(panel.workspace.current)


def source_hashes(panel) -> dict[str, str]:
    return {book.book_id: sha(wf.source_of(book).path) for book in panel.workspace.books
            if wf.source_of(book) is not None}


def parked_threads():
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    return RecordingThreads(kind=Parked)


# --------------------------------------------------------------------------- #
# The workspace replaces the raw file list: one occurrence = one Book
# --------------------------------------------------------------------------- #


def test_the_panel_starts_with_one_pristine_book_blank_shared_and_editor_actions_only(
        make_panel):
    panel = make_panel()
    assert panel.workspace.count == 1 and panel.workspace.current.is_empty
    assert panel.workspace.shared.values == {}
    assert not hasattr(panel, "files"), "the raw list is gone; the Books are the list"
    assert isinstance(panel.navigator, BookNavigator)
    assert isinstance(panel.surface, SharedMetadataSurface)
    assert panel.navigator.actions == (BookNavigator.REMOVE,)
    assert BookNavigator.ADD not in panel.navigator.buttons
    assert BookNavigator.DUPLICATE not in panel.navigator.buttons
    assert panel.navigator.position_text == "Book 1 of 1"
    assert panel.book_status_text() == editor.STATUS_READY
    assert "M4B-Metadata-Outputs" in panel.var_outdir.get()
    assert panel.last_plan is None and panel.run is None


def test_import_folder_makes_one_book_per_file_even_in_one_directory(make_panel, container,
                                                                    tmp_path):
    panel = make_panel()
    space = import_folder(panel, library(container, tmp_path / "Library"))
    assert space.count == 3
    assert [wf.source_of(book).path.name for book in space.books] == [
        "Alpha.m4b", "Beta.m4b", "Gamma.m4a"]
    assert all(book.file_count == 1 for book in space.books)
    assert panel.navigator.position_text == "Book 1 of 3"
    assert panel.book_value("title") == "Alpha"
    assert "Alpha.m4b" in panel.source_text()


def test_add_files_appends_independent_pages_and_skips_a_source_already_held(
        make_panel, container, tmp_path):
    root = library(container, tmp_path / "Library")
    panel = make_panel()
    import_folder(panel, root)
    extra = m4b(container, tmp_path / "Elsewhere" / "Delta.m4b", title="Delta")
    space = add_files(panel, extra, root / "Alpha.m4b")
    assert space.count == 4
    assert wf.source_of(space.current).path.name == "Delta.m4b", "the added Book is current"
    assert panel.book_value("title") == "Delta"
    assert any("already" in line for line in panel.log.summary)


def test_navigation_and_remove_are_the_shared_operations(make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    ids = [book.book_id for book in panel.workspace.books]
    panel.on_next()
    assert panel.workspace.current.book_id == ids[1]
    panel.on_previous()
    assert panel.workspace.current.book_id == ids[0]
    panel.on_select(ids[2])
    assert panel.workspace.current.book_id == ids[2]
    assert panel.navigator.position_text == "Book 3 of 3"
    panel.on_remove(True)      # the confirm seam says yes
    assert panel.workspace.count == 2
    assert [book.book_id for book in panel.workspace.books] == ids[:2]
    assert not hasattr(panel, "on_add") and not hasattr(panel, "on_duplicate")


def test_removing_a_meaningful_book_asks_and_a_refusal_keeps_it(make_panel, container,
                                                                tmp_path):
    asked: list[str] = []
    panel = make_panel(confirm=lambda title, message: asked.append(title) or False)
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert asked and panel.workspace.count == 3


def test_edits_chapters_and_artwork_survive_navigation_independently(make_panel, container,
                                                                     tmp_path):
    art = png(tmp_path / "art.png")
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.set_book_field("title", "Alpha Edited")
    panel.type_chapter_titles("\nThe End")
    panel._choose_artwork = lambda: str(art)
    panel.choose_book_artwork()
    panel.on_next()
    assert panel.book_value("title") == "Beta"
    assert panel.chapter_titles_text() == "Opening\nClosing"
    assert panel.book_artwork.path == ""
    panel.on_previous()
    assert panel.book_value("title") == "Alpha Edited"
    assert panel.chapter_titles_text() == "\nThe End"
    assert panel.book_artwork.path == str(art)
    first = panel.workspace.books[0].configuration
    assert first == {"title": "Alpha Edited", "chapter_titles": "\nThe End", "artwork": str(art)}
    assert panel.workspace.books[1].configuration == {}


# --------------------------------------------------------------------------- #
# Source prefill is display; edit intent is the model's
# --------------------------------------------------------------------------- #


def test_source_prefill_displays_without_entering_book_configuration(make_panel, container,
                                                                     tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    assert panel.book_value("title") == "Alpha" and panel.book_value("artist") == "Ann"
    assert panel.book_value("series") == "Saga"
    for _ in range(3):
        panel.on_next()
        panel.on_previous()
        panel.render()
    assert all(book.configuration == {} for book in panel.workspace.books)
    for book in panel.workspace.books:
        assert wf.explicit_edits(panel.workspace.shared, book, panel.store) == {}


def test_blank_changed_and_equal_book_values_follow_the_model(make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    space, store = panel.workspace, panel.store
    panel.surface.set_book_text("title", "")
    assert panel.workspace.current.configuration == {"title": ""}
    assert wf.edit_intent(panel.workspace.shared, panel.workspace.current, store, "title") is None
    panel.surface.set_book_text("title", "New Title")
    assert wf.edit_intent(panel.workspace.shared, panel.workspace.current, store,
                          "title") == "New Title"
    panel.surface.set_book_text("title", "Alpha")
    assert panel.workspace.current.configuration["title"] == "Alpha"
    assert wf.edit_intent(panel.workspace.shared, panel.workspace.current, store, "title") is None
    assert store.for_book(panel.workspace.current).title == "Alpha", "the observation is untouched"
    assert space is not panel.workspace


def test_vendor_series_is_readback_and_display_and_never_an_implicit_edit(make_panel, container,
                                                                          tmp_path):
    vendor = vendor_series(m4b(container, tmp_path / "Src" / "V.m4b", album="Alb"),
                           name="Tone Saga", part="3")
    panel = make_panel()
    add_files(panel, vendor)
    assert panel.book_value("series") == "Tone Saga"
    assert panel.series_readback_text() == wf.series_readback(observation(panel))
    assert "com.pilabor.tone" in panel.series_readback_text()
    assert "3" in panel.facts_text()
    panel.on_next()
    panel.render()
    assert panel.workspace.current.configuration == {}
    assert wf.explicit_edits(panel.workspace.shared, panel.workspace.current, panel.store) == {}
    panel.surface.set_book_text("series", "Tone Saga")
    assert wf.explicit_edits(panel.workspace.shared, panel.workspace.current, panel.store) == {}


def test_an_album_implied_series_is_readback_only(make_panel, container, tmp_path):
    implied = m4b(container, tmp_path / "Src" / "I.m4b", album="Grouped", series_part="2")
    panel = make_panel()
    add_files(panel, implied)
    seen = observation(panel)
    assert seen.series_name_implied
    assert panel.book_value("series") == ""
    assert "Album: 'Grouped'" in panel.series_readback_text()


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #


def test_shared_starts_blank_even_when_every_source_agrees(make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    assert all(book.configuration == {} for book in panel.workspace.books)
    assert panel.workspace.shared.values == {}
    assert all(panel.surface.shared_value(name) == "" for name in panel.surface.fields)
    assert panel.shared_artwork.path == ""


def test_populated_shared_overrides_and_disables_and_clearing_restores(make_panel, container,
                                                                       tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.set_book_field("genre", "Mine")
    panel.surface.set_shared_text("genre", "Shared G")
    assert panel.workspace.shared.raw("genre") == "Shared G"
    assert panel.book_field_enabled("genre") is False
    assert panel.book_value("genre") == "Shared G", "the page shows the effective value"
    assert wf.explicit_edits(panel.workspace.shared, panel.workspace.current,
                             panel.store)["genre"] == "Shared G"
    panel.surface.set_shared_text("genre", "")
    assert panel.book_field_enabled("genre") is True
    assert panel.book_value("genre") == "Mine"
    assert panel.workspace.current.configuration["genre"] == "Mine"
    panel.on_next()
    assert panel.book_value("genre") == "Old", "the next Book shows its own prefill again"


def test_shared_artwork_overrides_the_book_control_and_clearing_restores_it(make_panel,
                                                                            container, tmp_path):
    shared_art, book_art = png(tmp_path / "s.png"), png(tmp_path / "b.png")
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel._choose_artwork = lambda: str(book_art)
    panel.choose_book_artwork()
    panel._choose_artwork = lambda: str(shared_art)
    panel.choose_shared_artwork()
    assert panel.shared_artwork.path == str(shared_art)
    assert not panel.book_artwork.enabled
    assert wf.artwork_intent(panel.workspace.shared, panel.workspace.current) == str(shared_art)
    panel.clear_shared_artwork()
    assert panel.book_artwork.enabled and panel.book_artwork.path == str(book_art)
    assert wf.artwork_intent(panel.workspace.shared, panel.workspace.current) == str(book_art)
    assert isinstance(panel.shared_artwork, m4b_artwork_ui.ArtworkControl)
    assert isinstance(panel.book_artwork, m4b_artwork_ui.ArtworkControl)


def test_series_part_is_not_a_shared_or_book_text_field(make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    assert panel.surface.fields == wf.TEXT_FIELDS
    assert "series_part" not in panel.shared_field_keys()
    assert "series_part" not in panel.book_field_keys()
    assert "Series Part: 1" in panel.facts_text()
    with pytest.raises(wf.EditorContractError):
        panel.set_book_field("series_part", "9")


# --------------------------------------------------------------------------- #
# Chapters, artwork and read-back
# --------------------------------------------------------------------------- #


def test_chapter_buffers_show_the_source_titles_and_stay_independent_by_book(
        make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    assert panel.chapter_titles_text() == "Opening\nClosing"
    assert "chapter_titles" not in panel.workspace.current.configuration, "display, not an edit"
    panel.type_chapter_titles("Opening\nThe End")
    assert wf.chapter_edits(panel.workspace.current, observation(panel)) == (None, "The End")
    panel.on_next()
    assert panel.chapter_titles_text() == "Opening\nClosing"
    assert "chapter_titles" not in panel.workspace.current.configuration
    assert "Chapters: 2" in panel.facts_text()


def test_blank_positional_lines_are_kept_and_never_collapsed(make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.type_chapter_titles("\nRenamed")
    assert panel.workspace.current.configuration["chapter_titles"] == "\nRenamed"
    assert wf.chapter_edits(panel.workspace.current, observation(panel)) == (None, "Renamed")
    panel.type_chapter_titles("\n\nExtra")
    assert wf.chapter_edits(panel.workspace.current, observation(panel)) == (None, None)


def test_readback_lines_come_from_the_model_and_show_the_source_artwork_state(
        make_panel, container, tmp_path):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    seen = observation(panel)
    assert panel.series_readback_text() == wf.series_readback(seen)
    assert "Detected on file: Saga #1" in panel.series_readback_text()
    assert "Artwork: on file" in panel.facts_text()
    assert str(seen.path.parent) in panel.source_text() or seen.path.name in panel.source_text()
    assert "readable" in panel.source_text()


def test_artwork_replacement_uses_the_shared_adapter_and_leaves_the_source_untouched(
        make_panel, container, tmp_path):
    art = png(tmp_path / "new.png")
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    before = source_hashes(panel)
    refused: list[str] = []
    panel._choose_artwork = lambda: str(tmp_path / "missing.png")
    panel._artwork_error = refused.append
    panel.choose_book_artwork()
    assert refused and panel.workspace.current.configuration.get("artwork", "") == ""
    panel._choose_artwork = lambda: str(art)
    panel.choose_book_artwork()
    assert panel.workspace.current.configuration["artwork"] == str(art)
    assert panel.book_artwork.has_preview
    assert wf.artwork_intent(panel.workspace.shared, panel.workspace.current) == str(art)
    assert source_hashes(panel) == before
    assert observation(panel).has_cover, "the source's own cover is still a read-back fact"
    panel.clear_book_artwork()
    assert wf.artwork_intent(panel.workspace.shared, panel.workspace.current) is None


def test_an_unreadable_source_is_a_visible_book_with_unavailable_readback(make_panel, tmp_path):
    bad = tmp_path / "Src" / "bad.m4b"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not an mp4")
    panel = make_panel()
    add_files(panel, bad)
    assert panel.workspace.count == 1 and wf.source_of(panel.workspace.current) is not None
    assert not observation(panel).readable
    assert "unavailable" in panel.series_readback_text()
    assert "could not be read" in panel.source_text()
    assert panel.book_value("title") == ""


# --------------------------------------------------------------------------- #
# The three actions: flush, freeze, reserve once, one EditorRun
# --------------------------------------------------------------------------- #


def test_save_refuses_an_empty_workspace_and_a_bad_start_part_before_reserving(
        make_panel, container, tmp_path, output_base):
    panel = make_panel()
    assert panel.save() is False
    assert make_panel.dialogs[-1][0] == "warning"
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.var_auto_number.set(True)
    panel.var_start_part.set("zero")
    assert panel.save() is False
    assert make_panel.dialogs[-1][0] == "error" and "Start Part" in make_panel.dialogs[-1][1]
    assert not output_base.exists(), "nothing was reserved"
    assert panel.last_plan is None


def test_save_freezes_the_plan_reserves_one_run_and_runs_every_book(make_panel, container,
                                                                    tmp_path, output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    before = source_hashes(panel)
    panel.surface.set_shared_text("genre", "Shared G")
    panel.set_book_field("title", "Alpha Edited")
    panel.type_chapter_titles("\nThe End")
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert isinstance(plan, mp.RunPlan) and plan.action is EditorAction.SAVE_TAGS
    assert plan.run_directory == output_base / "M4B-Metadata-Outputs" / "M4B-Metadata-1"
    assert dict(plan.books[0].writes) == {"title": "Alpha Edited", "genre": "Shared G"}
    assert dict(plan.books[1].writes) == {"genre": "Shared G"}
    assert plan.books[0].chapter_edits == (None, "The End")
    assert isinstance(panel.run, batch.EditorRun) and len(panel.run.attempts) == 1
    workers = [b for b in panel._thread_factory.bodies if getattr(b, "__name__", "") == "run"]
    assert len(workers) == 1
    # Editing after Start reaches nothing the run reads.
    panel.set_book_field("title", "Changed")
    panel.surface.set_shared_text("artist", "Late")
    assert dict(plan.books[0].writes) == {"title": "Alpha Edited", "genre": "Shared G"}
    result = panel.last_result
    assert result is not None and result.state is JobState.SUCCEEDED
    assert sorted(p.name for p in plan.run_directory.iterdir() if p.is_file()) == [
        "Alpha.m4b", "Beta.m4b", "Gamma.m4a"]
    tags = metadata.read_m4b_tags(plan.books[0].published)
    assert tags["title"] == "Alpha Edited" and tags["genre"] == "Shared G"
    assert tags["artist"] == "Ann" and tags["series"] == "Saga", "unedited tags preserved"
    assert metadata.read_chapter_titles(plan.books[0].published) == ["Opening", "The End"]
    assert audio_md5(plan.books[0].published) == audio_md5(plan.books[0].source)
    assert [panel.book_status_for(b.book_id) for b in panel.workspace.books] == [
        editor.STATUS_COMPLETED] * 3
    assert not panel.is_running
    assert len(list((output_base / "M4B-Metadata-Outputs").iterdir())) == 1, "one reservation"
    assert source_hashes(panel) == before
    assert panel.var_outdir.get() == str(plan.run_directory)


def test_clear_all_asks_then_freezes_the_clear_action_without_converting_prefill(
        make_panel, container, tmp_path, output_base):
    asked: list[str] = []
    answers = {"value": False}
    panel = make_panel(confirm=lambda title, message: asked.append(message) or answers["value"])
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.set_book_field("title", "Kept Title")
    assert run_action(panel, "on_clear_all_tags") is False
    assert asked and "never modified" in asked[-1] and "copies" in asked[-1].lower()
    assert "chapters" in asked[-1].lower()
    assert not output_base.exists(), "declining reserves nothing"
    answers["value"] = True
    assert run_action(panel, "on_clear_all_tags") is True
    plan = panel.last_plan
    assert plan.action is EditorAction.CLEAR_ALL_TAGS
    assert dict(plan.books[0].writes) == {"title": "Kept Title"}
    assert dict(plan.books[1].writes) == {}, "prefill is not a write"
    assert panel.last_result.state is JobState.SUCCEEDED
    kept = metadata.read_m4b_tags(plan.books[0].published)
    assert kept["title"] == "Kept Title" and not kept.get("artist") and not kept.get("series")
    assert kept["has_cover"] is False
    assert metadata.read_chapter_titles(plan.books[0].published) == ["Opening", "Closing"]
    cleared = metadata.read_m4b_tags(plan.books[1].published)
    assert not cleared.get("title") and not cleared.get("artist")


def test_remove_series_numbering_freezes_the_action_alone(make_panel, container, tmp_path,
                                                          output_base):
    art = png(tmp_path / "art.png")
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.set_book_field("title", "Pending")
    panel.surface.set_shared_text("artist", "Pending Artist")
    panel._choose_artwork = lambda: str(art)
    panel.choose_book_artwork()
    panel.type_chapter_titles("\nPending Chapter")
    panel.var_auto_number.set(True)
    panel.var_start_part.set("7")
    assert run_action(panel, "on_remove_series_numbering") is True
    plan = panel.last_plan
    assert plan.action is EditorAction.REMOVE_SERIES_NUMBERING
    assert plan.auto_number is False and panel.run.numbers is None
    for entry in plan.books:
        assert dict(entry.writes) == {} and entry.artwork is None and entry.chapter_edits == ()
    assert panel.last_result.state is JobState.SUCCEEDED
    tags = metadata.read_m4b_tags(plan.books[0].published)
    assert tags["title"] == "Alpha" and tags["artist"] == "Ann"
    assert tags["series"] == "Saga" and not tags.get("series_part")
    assert tags["has_cover"] is True
    assert metadata.read_chapter_titles(plan.books[0].published) == ["Opening", "Closing"]


def test_auto_number_is_success_only_through_the_shared_allocator(make_panel, container,
                                                                  tmp_path, output_base,
                                                                  monkeypatch):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.surface.set_shared_text("genre", "G")
    panel.var_auto_number.set(True)
    panel.var_start_part.set("5")
    target = None
    real = metadata.write_m4b_tags

    def broken(path, tags, total=None):
        if target is not None and Path(path) == target:
            raise RuntimeError("tag write refused")
        return real(path, tags, total=total)

    monkeypatch.setattr(metadata, "write_m4b_tags", broken)
    # The plan is frozen before the worker runs; break the second Book's staged path.
    original_start = panel._start_attempt

    def start_and_break(begin, label):
        nonlocal target
        target = panel.last_plan.books[1].staged
        original_start(begin, label)

    panel._start_attempt = start_and_break
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert plan.auto_number and plan.start_part == 5
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    parts = [metadata.read_m4b_tags(b.published).get("series_part") for b in plan.books
             if b.published.exists()]
    assert parts == ["5", "6"], "the failed Book consumed no number"
    assert panel.run.numbers.consumed == 2
    assert [panel.book_status_for(b.book_id) for b in panel.workspace.books] == [
        editor.STATUS_COMPLETED, editor.STATUS_FAILED, editor.STATUS_COMPLETED]
    assert any("Series Part" in line for line in panel.log.details)


def test_an_unreadable_source_is_skipped_invalid_and_stays_visible(make_panel, container,
                                                                   tmp_path, output_base):
    root = library(container, tmp_path / "Library")
    bad = root / "bad.m4b"
    bad.write_bytes(b"not an mp4")
    panel = make_panel()
    import_folder(panel, root)
    assert panel.workspace.count == 4
    panel.surface.set_shared_text("genre", "G")
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert len(plan.books) == 3
    result = panel.last_result
    assert result.state is JobState.SUCCEEDED
    bad_id = next(b.book_id for b in panel.workspace.books
                  if wf.source_of(b).path.name == "bad.m4b")
    assert result.disposition_for(bad_id) is BookDisposition.SKIPPED_INVALID
    assert panel.book_status_for(bad_id) == editor.STATUS_SKIPPED
    assert panel.workspace.count == 4, "the skipped Book is still on its page"
    assert any("skipped" in line.lower() for line in panel.log.summary)


def test_no_custom_destination_ui_exists(make_panel):
    panel = make_panel()
    texts = []
    for widget in _walk(panel):
        try:
            texts.append(str(widget.cget("text")).lower())
        except tk.TclError:
            continue
    assert not any("custom destination" in text for text in texts)
    assert not hasattr(panel, "custom_destination") and not hasattr(panel, "chk_custom_dest")


# --------------------------------------------------------------------------- #
# Job architecture: one run, one controller per attempt, one worker
# --------------------------------------------------------------------------- #


def test_retry_failed_reruns_only_the_failed_book_from_the_frozen_run(make_panel, container,
                                                                       tmp_path, output_base,
                                                                       monkeypatch):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.surface.set_shared_text("genre", "G")
    real = metadata.write_m4b_tags
    broken_for = {"path": None}

    def broken(path, tags, total=None):
        if broken_for["path"] is not None and Path(path) == broken_for["path"]:
            raise RuntimeError("tag write refused")
        return real(path, tags, total=total)

    monkeypatch.setattr(metadata, "write_m4b_tags", broken)
    original_start = panel._start_attempt

    def start_and_break(begin, label):
        broken_for["path"] = panel.last_plan.books[1].staged
        original_start(begin, label)

    panel._start_attempt = start_and_break
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert panel.last_result.state is JobState.COMPLETED_WITH_FAILURES
    assert panel.jobs.controls.availability()[JobAction.RETRY_FAILED] is True
    published_a = plan.books[0].published
    before = (sha(published_a), published_a.stat().st_mtime_ns)
    # Repair, then edit the workspace every way there is.
    panel._start_attempt = original_start
    broken_for["path"] = None
    panel.set_book_field("title", "Renamed")
    panel.surface.set_shared_text("genre", "Other")
    panel.on_remove(True)
    assert panel.retry_failed() is True
    assert panel.last_plan is plan and len(panel.run.attempts) == 2
    assert [b.book_id for b in panel.run.attempts[1].books] == [plan.books[1].book_id]
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.SUCCEEDED
    assert plan.books[1].published.is_file()
    assert metadata.read_m4b_tags(plan.books[1].published)["genre"] == "G", "the frozen intent"
    assert (sha(published_a), published_a.stat().st_mtime_ns) == before
    assert len(list((output_base / "M4B-Metadata-Outputs").iterdir())) == 1, "no new run"


def test_pause_resume_and_cancel_reach_the_shared_controller(make_panel, container, tmp_path,
                                                             output_base):
    calls: list[str] = []

    class Recording(batch.EditorRun):
        def pause(self):
            calls.append("pause")
            super().pause()

        def resume(self):
            calls.append("resume")
            super().resume()

        def cancel(self):
            calls.append("cancel")
            super().cancel()

    panel = make_panel(run_factory=Recording)
    import_folder(panel, library(container, tmp_path / "Library"))
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    assert panel.is_running
    controller = panel.job_controller
    panel.pause()
    assert controller.state is JobState.PAUSE_REQUESTED
    panel.resume()
    assert controller.state is JobState.RUNNING
    panel.cancel()
    assert controller.state is JobState.CANCEL_REQUESTED
    assert calls == ["pause", "resume", "cancel"]
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert [d for _i, d in result.dispositions] == [BookDisposition.NOT_ATTEMPTED] * 3
    assert panel.book_status_for(panel.workspace.books[0].book_id) == editor.STATUS_NOT_ATTEMPTED
    assert not any(panel.last_plan.run_directory.iterdir()), "nothing published"


def test_the_ui_locks_through_the_shared_matrix_while_running(make_panel, container, tmp_path,
                                                              output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    assert panel.lock_group.last_applied
    for button in (panel.btn_save, panel.btn_clear_tags, panel.btn_remove_numbering,
                   panel.btn_import_folder, panel.btn_add_files, panel.check_auto_number,
                   panel.navigator.buttons[BookNavigator.REMOVE]):
        assert "disabled" in button.state(), button
    assert panel.book_field_enabled("title") is False
    assert not panel.book_artwork.enabled and not panel.shared_artwork.enabled
    assert str(panel.chapter_text.cget("state")) == "disabled"
    panel._pump.tick()      # the run's first events reach the shared bar
    assert panel.jobs.controls.availability()[JobAction.CANCEL] is True
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    for button in (panel.btn_save, panel.btn_import_folder, panel.btn_add_files):
        assert "disabled" not in button.state(), button
    assert panel.book_field_enabled("title") is True


def test_the_worker_body_reaches_no_tk(make_panel, container, tmp_path, output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    body = panel._thread_factory.bodies[0]
    raised: list[BaseException] = []

    def run():
        try:
            body()
        except BaseException as exc:  # noqa: BLE001
            raised.append(exc)

    worker = threading.Thread(target=run, name="editor-ui-test")
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive() and not raised
    panel._pump.tick()
    assert panel.last_result is not None and panel.last_result.state is JobState.SUCCEEDED


def test_a_second_action_is_refused_while_one_runs(make_panel, container, tmp_path, output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    assert panel.on_remove_series_numbering() is False
    assert panel.save() is False
    assert len(panel.run.attempts) == 1
    assert len(list((output_base / "M4B-Metadata-Outputs").iterdir())) == 1
    panel._thread_factory.bodies[0]()
    panel._pump.tick()


# --------------------------------------------------------------------------- #
# Log, layout and presentation
# --------------------------------------------------------------------------- #


def test_one_summary_detailed_region_and_no_whole_form_scrollbar(make_panel):
    panel = make_panel()
    assert isinstance(panel.log, job_ui.SummaryDetailsView)
    assert len(widgets_of(panel, tk.Text)) == 3, "chapter box, Summary, Detailed"
    assert widgets_of(panel, tk.Canvas) == [], "the whole-form canvas scroller is retired"
    assert len(widgets_of(panel, ttk.Scrollbar)) == 3, "chapter titles, Summary, Detailed"
    assert len(widgets_of(panel, ttk.Notebook)) == 1
    assert not hasattr(panel, "log_write")


def test_the_windows_minimum_geometry_keeps_every_region_reachable(tk_root, make_panel):
    """Deiconified: ``winfo_ismapped`` on a withdrawn toplevel says nothing."""
    panel = make_panel()
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        tk_root.geometry("920x600")
        for _ in range(6):
            tk_root.update_idletasks()
            tk_root.update()
        height, width = tk_root.winfo_height(), tk_root.winfo_width()
        top, left = tk_root.winfo_rooty(), tk_root.winfo_rootx()
        assert width >= 920 and height >= 600
        for widget in (panel.btn_save, panel.btn_clear_tags, panel.btn_remove_numbering,
                       panel.jobs.controls.frame, panel.log.frame, panel.navigator.frame,
                       panel.btn_import_folder, panel.btn_add_files, panel.check_auto_number,
                       panel.entry_start_part, panel.chapter_text,
                       panel.book_artwork.btn_choose, panel.shared_artwork.btn_choose,
                       panel.readback_label, panel.status_label,
                       panel.navigator.buttons[BookNavigator.REMOVE]):
            assert widget.winfo_ismapped(), widget
            bottom = widget.winfo_rooty() - top + widget.winfo_height()
            right = widget.winfo_rootx() - left + widget.winfo_width()
            assert bottom <= height + 1, (widget, bottom, height)
            assert right <= width + 1, (widget, right, width)
    finally:
        panel.pack_forget()
        tk_root.withdraw()


@windows_only
def test_the_shared_book_band_fits_the_padded_windows_minimum(tk_root, make_panel):
    """The seven-field Shared/Book band must fit inside the padded 920.

    A pixel budget of the accepted Windows composition, so Windows only: the
    Windows bundle asked for through the theme seam on a Mac still draws with
    native aqua entries and fonts (``clam`` + the system font, no Segoe UI),
    where the same band asks for ~1066 px — a number that describes the host's
    metrics, not the composition. The reachability proof above stays
    unconditional; the aqua composition has its own gate in
    ``test_m4b_layout.py`` (v0.6.4 Phase 13).
    """
    panel = make_panel()
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        tk_root.geometry("920x600")
        for _ in range(6):
            tk_root.update_idletasks()
            tk_root.update()
        assert panel.surface.frame.winfo_reqwidth() <= 900, panel.surface.frame.winfo_reqwidth()
    finally:
        panel.pack_forget()
        tk_root.withdraw()


def test_aqua_uses_the_stacked_hints_through_the_existing_seam(tk_root):
    aqua = {"mode": "aqua", "geometry": ui_theme.DEFAULT_GEOMETRY,
            "min_size": ui_theme.AQUA_MIN_SIZE,
            "metrics": {"navigator_layout": "stacked", "actions_layout": "stacked",
                        "artwork_buttons": "natural", "content_pad": 12}}
    panel = editor.M4BMetadataEditorUI(tk_root, theme=aqua, effective_config=make_config(),
                                       thread_factory=RecordingThreads(),
                                       choose_files=lambda: (), choose_folder=lambda: ())
    try:
        assert panel.navigator.layout == "stacked"
        assert str(panel.btn_save.cget("style")) == ""
        assert [str(w) for w in _walk(panel) if _style_of(w).startswith("ACT.")] == []
        assert str(panel.book_artwork.btn_choose.cget("width")) in ("", "0")
        # Without the Phase 13 hints the composition is the Windows one.
        assert panel.btn_open_out.master is panel.btn_import_folder.master
        assert panel.surface.field_lines == 1 and panel.surface.field_columns == 7
        assert panel.btn_clear_log.grid_info()["row"] == 3
        assert panel.btn_clear_log.grid_info()["column"] == 0
        assert panel.facts_label.master.grid_info()["row"] == 2
        assert int(panel.chapter_text.cget("height")) == 3
    finally:
        panel.close()
        panel.destroy()


def test_the_phase_13_aqua_hints_fold_the_composition_through_the_same_seam(tk_root):
    """v0.6.4 Phase 13 (macOS parity): the real aqua bundle's hints, read with
    the Windows values as defaults. Measured in the real shell by
    ``test_m4b_layout.py``; pinned here as the seam's contract on any host."""
    aqua = {"mode": "aqua", "geometry": ui_theme.AQUA_GEOMETRY,
            "min_size": ui_theme.AQUA_MIN_SIZE,
            "metrics": {"navigator_layout": "stacked", "actions_layout": "stacked",
                        "artwork_buttons": "natural", "content_pad": 12,
                        "import_band_layout": "compact", "group_pad": 4, "field_gap": 6,
                        "field_columns": 4, "actions_columns": 2,
                        "navigator_layout_one_action": "row",
                        "readback_layout": "compact", "note_wrap": 740,
                        "chapter_rows": 2}}
    panel = editor.M4BMetadataEditorUI(tk_root, theme=aqua, effective_config=make_config(),
                                       thread_factory=RecordingThreads(),
                                       choose_files=lambda: (), choose_folder=lambda: ())
    try:
        # The one-action navigator takes the one-line layout the theme allows it.
        assert panel.navigator.layout == "row"
        # Import band: the status bar keeps its width, the hint yields.
        top = panel.btn_import_folder.master
        assert int(top.grid_columnconfigure(3)["weight"]) == 0
        assert int(top.grid_columnconfigure(4)["weight"]) == 1
        assert panel.output_label.grid_info()["sticky"] == "ew"
        assert panel.import_status.frame.grid_info()["sticky"] == "w"
        # Open Output Folder is the same control with the same command, in
        # the actions block, beneath the two destructive actions.
        assert panel.btn_open_out.master is panel.btn_save.master
        assert str(panel.btn_open_out.cget("text")) == "Open Output Folder"
        assert panel.btn_open_out.grid_info()["row"] == 2
        assert panel.btn_open_out.grid_info()["column"] == 1
        assert (panel.btn_save.grid_info()["row"], panel.btn_save.grid_info()["column"]) == (0, 0)
        assert (panel.btn_clear_log.grid_info()["row"],
                panel.btn_clear_log.grid_info()["column"]) == (1, 0)
        assert (panel.btn_clear_tags.grid_info()["row"],
                panel.btn_clear_tags.grid_info()["column"]) == (0, 1)
        assert (panel.btn_remove_numbering.grid_info()["row"],
                panel.btn_remove_numbering.grid_info()["column"]) == (1, 1)
        # Seven fields fold 4 + 3; the artwork spans the field rows only and
        # the read-back runs the full width beneath, facts on the series line.
        assert panel.surface.field_columns == 4 and panel.surface.field_lines == 2
        assert panel.shared_artwork.frame.grid_info()["rowspan"] == 4
        assert panel.book_artwork.frame.grid_info()["rowspan"] == 4
        readback = panel.readback_label.master
        assert readback.grid_info()["row"] == 4
        assert readback.grid_info()["columnspan"] == 5
        assert panel.facts_label.master.grid_info()["row"] == 1
        assert panel.facts_label.master.grid_info()["column"] == 1
        assert int(panel.hint_label.cget("wraplength")) == 740
        assert int(panel.chapter_text.cget("height")) == 2
        # Every control and caption is still there; nothing is platform-named.
        assert str(panel.hint_label.cget("text")) == editor.PRESERVE_HINT
        assert [str(w) for w in _walk(panel) if _style_of(w).startswith("ACT.")] == []
    finally:
        panel.close()
        panel.destroy()


def test_the_panel_asks_for_act_styles_and_declares_no_colour_or_platform_branch(make_panel):
    panel = make_panel()
    assert str(panel.btn_save.cget("style")).startswith("ACT.")
    assert str(panel.navigator.frame.cget("style")).startswith("ACT.")
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for hexish in literals:
        assert not (hexish.startswith("#") and len(hexish) in (4, 7)), hexish
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "platform" not in names and "sys.platform" not in literals
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not any(c.endswith("theme_use") or c.endswith("Style().configure") for c in calls)


@windows_only
def test_windows_editor_uses_only_namespaced_styles_and_leaves_generic_styles_alone(
        tk_root, make_panel):
    style = ttk.Style(tk_root)
    ui_theme.apply_theme(tk_root, style)
    before = _snapshot_generic(style)
    panel = make_panel()
    tk_root.update_idletasks()
    after = _snapshot_generic(style)
    assert [n for n in GENERIC_STYLES if before[n] != after[n]] == []
    s = panel.theme["styles"]
    assert str(panel.cget("style")) == s["window"]
    used = {_style_of(w) for w in _walk(panel)} - {""}
    assert used and all(name.startswith("ACT.") for name in used), sorted(used)
    stragglers = [str(w) for w in _walk(panel)
                  if isinstance(w, ttk.Widget) and not _style_of(w)]
    assert stragglers == [], stragglers
    assert str(panel.btn_save.cget("style")) == s["primary_button"]
    assert str(panel.btn_clear_tags.cget("style")) == s["danger_button"]
    assert str(panel.btn_remove_numbering.cget("style")) == s["danger_button"]


@windows_only
def test_windows_editor_themes_its_classic_tk_widgets(make_panel):
    panel = make_panel()
    c = panel.theme["colors"]
    assert panel.chapter_text.cget("background") == c["field"]
    for text in (panel.log.summary_text, panel.log.details_text):
        assert text.cget("background") in (c["elevated"], c["field"], c["window"])


# --------------------------------------------------------------------------- #
# Structure: thin adapter, the four layers, one framework
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_editor_layers_and_defines_no_business_rule():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for required in ("shared.book_workspace", "shared.book_workspace_ui", "shared.job_ui",
                     "shared.job_control", "shared.import_coordination", "shared.importing",
                     "mp3_tools.m4b_metadata_workflow", "mp3_tools.m4b_metadata_plan",
                     "mp3_tools.m4b_metadata_batch", "mp3_tools.m4b_artwork_ui"):
        assert required in modules, required
    for banned in ("shared.metadata", "mutagen", "shared.ffmpeg_utils", "shared.cancellation",
                   "shutil", "tempfile", "mp3_tools.m4b_metadata_processing",
                   "mp3_tools.m4b_staging", "mp3_tools.m4b_maker",
                   "mp3_tools.m4b_maker_workflow", "mp3_tools.m4b_maker_plan",
                   "mp3_tools.m4b_maker_batch", "mp3_tools.mp3_workflow",
                   "mp3_tools.mp3_plan", "mp3_tools.mp3_processing", "mp3_tools.mp3_tool"):
        assert banned not in modules, banned
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for gone in ("_save_worker", "_remove_numbering_worker", "_pump_queue", "_finish_idle",
                 "disable_inputs", "_collect_tags", "_shared_tags", "_refresh_mode",
                 "_tags_for", "_series_readback_text", "_autonumber_start", "_start_job",
                 "log_write", "clear_list", "remove_selected", "_chap_prev", "_chap_next"):
        assert gone not in declared, gone
    for owned_elsewhere in ("BookNavigator", "SharedMetadataSurface", "ArtworkControl",
                            "JobController", "JobAdapter", "EditorRun", "Attempt",
                            "ImportedFileManager", "ImportCoordinator", "plan_run",
                            "DestinationPlanner", "SuccessNumbers", "observe_source",
                            "edit_intent", "page_values", "series_readback", "chapter_edits"):
        assert owned_elsewhere not in declared, owned_elsewhere
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("rmtree", "replace", "unlink", "write_bytes", "Popen", "run", "copy2",
                  "write_m4b_tags", "clear_metadata_keep_chapters", "clear_series_numbering",
                  "apply_chapter_titles", "read_m4b_tags", "read_chapter_titles"):
        assert write not in calls, write
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for private in ("_busy", "_cancel_event", "_log_q", "_tag_cache", "_chap_buffers"):
        assert private not in names, private
    built = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ast.unparse(node.func).endswith(("EditorRun", "_run_factory"))]
    assert len(built) == 1, "one EditorRun construction site, through the injectable seam"
    canvases = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("Canvas")]
    assert canvases == [], "no whole-form canvas"


def test_the_public_surface_the_launcher_expects_is_intact(tk_root):
    from shared import paths

    assert callable(editor.build_ui) and callable(editor.main)
    assert editor.TOOL_KEY == "m4b_metadata"
    assert editor.SLUG == paths.TOOL_SLUGS["m4b_metadata"] == "M4B-Metadata"
    assert editor.KEY_INPUT_DIR == "m4b_metadata.input_dir"
    assert editor.KEY_COVER_DIR == "m4b_metadata.cover_dir"
    ui = editor.build_ui(ttk.Frame(tk_root))
    try:
        assert isinstance(ui, editor.M4BMetadataEditorUI)
        assert ui.winfo_manager() == "pack"
    finally:
        ui.close()
        ui.master.destroy()


def test_the_launcher_still_exposes_exactly_six_tools_with_the_editor_among_them():
    import launcher

    assert len(launcher.TOOLS) == 6
    assert [spec.key for spec in launcher.TOOLS].count("m4b_metadata") == 1
    spec = next(spec for spec in launcher.TOOLS if spec.key == "m4b_metadata")
    assert spec.module == "mp3_tools.m4b_metadata_editor"


def test_the_editor_panel_is_now_an_adopter_and_its_hash_pin_is_retired():
    from test_plan3_boundaries import ADOPTED, UNADOPTED_PANELS
    from test_plan6_boundaries import PHASE0_PANEL_HASHES

    assert "mp3_tools/m4b_metadata_editor.py" in ADOPTED
    assert "mp3_tools/m4b_metadata_editor.py" not in UNADOPTED_PANELS
    assert "mp3_tools/m4b_metadata_editor.py" not in PHASE0_PANEL_HASHES


# --------------------------------------------------------------------------- #
# The developer-only visual fixture still drives the real panel, offline
# --------------------------------------------------------------------------- #


def test_manual_fixture_is_developer_only_and_unreachable_at_runtime():
    import launcher

    assert FIXTURE_PATH.exists()
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    assert not FIXTURE_PATH.name.startswith("test_")
    assert "def " + "test_" not in source
    assert all("manual_windows_ui_prototype" not in spec.module for spec in launcher.TOOLS)
    scripts_root = FIXTURE_PATH.parents[2] / "scripts"
    assert not list(scripts_root.rglob("manual_windows_ui_prototype.py"))
    assert "from shared import ui_theme" in source
    assert "from mp3_tools import m4b_metadata_editor" in source


def test_manual_fixture_states_are_deterministic_and_offline(make_panel):
    """Its canned states drive the real panel through the model, touching no file."""
    import manual_windows_ui_prototype as fixture

    note = fixture.SPECIMEN_NOTE
    assert "VISUAL SPECIMEN" in note

    panel = make_panel()
    fixture._populate(panel)
    assert panel.workspace.count == 3
    assert panel.navigator.position_text == "Book 1 of 3"
    assert panel.book_value("artist") == "A. Sample Author"
    assert panel.book_value("title") == "The First Sample"
    assert panel.workspace.shared.values == {}, "Shared starts blank even when sources agree"
    assert all(book.configuration == {} for book in panel.workspace.books)
    assert "Sample Chronicles #1" in panel.series_readback_text()
    assert panel.chapter_titles_text().startswith("Prologue")
    assert not any(wf.source_of(book).path.exists() for book in panel.workspace.books), \
        "the fixture must stay offline"

    fixture._make_busy(panel)
    assert "disabled" in panel.btn_save.state()
    assert panel.jobs.controls.availability()[JobAction.CANCEL] is True
    assert panel.jobs.status.indicator.label.cget("text") == "2/3  67%"
    fixture._make_idle(panel)
    assert "disabled" not in panel.btn_save.state()


@windows_only
def test_manual_fixture_specimen_builds_from_production_primitives(tk_root):
    import manual_windows_ui_prototype as fixture

    top = tk.Toplevel(tk_root)
    top.withdraw()
    try:
        theme = ui_theme.apply_theme(top, ttk.Style(top))
        fixture._build_specimen(top, theme)
        top.update_idletasks()
        used = {_style_of(w) for w in _walk(top)} - {""}
        assert used and all(n.startswith("ACT.") for n in used), sorted(used)
        notebooks = [w for w in _walk(top) if isinstance(w, ttk.Notebook)]
        assert len(notebooks) == 1
        commanded = [str(w) for w in _walk(top)
                     if isinstance(w, ttk.Button) and str(w.cget("command"))]
        assert commanded == [], commanded
    finally:
        top.destroy()
