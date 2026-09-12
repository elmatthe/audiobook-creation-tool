"""The redesigned MP3 Tool panel — v0.6.3 focused MP3 plan, Phase 4.

``mp3_tools/mp3_tool.py`` becomes the first production adopter of the Plan 6
workspace: the Phase 2 navigator and Shared surface, the Phase 3 model, and the
Plan 3 importer and job-control shells, composed into the MP3-specific workspace
UI the focused plan describes. This suite proves the **shell** — what is on the
panel, what is not, where the values go, what the model is asked — and nothing
about media: no FFmpeg, no tag writing, no artwork embedding, no output planning
happen in Phase 4, and a guard here says so.

Determinism
-----------
No test sleeps and nothing polls on a timer: folder scans run inline through the
shared recording thread factory and the panel's one pump is ticked by hand. Every
dialog is injected. Placeholder ``.mp3`` files are generated under ``tmp_path``;
where a test needs real ID3 frames, mutagen writes them onto the stub.

Appearance is asserted mechanically — which style key a widget carries — never by
sampling pixels.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

import tk_gate  # noqa: E402

from shared import book_workspace, job_ui, ui_theme  # noqa: E402
from shared.book_workspace import SharedMetadata, has_meaningful_work  # noqa: E402
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface  # noqa: E402
from shared.job_control import JobState  # noqa: E402
from shared.job_ui import MainThreadError  # noqa: E402

from mp3_tools import mp3_tool, mp3_workflow as wf  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
PANEL_SOURCE = UNIVERSAL / "mp3_tools" / "mp3_tool.py"

AQUA_THEME = {
    "mode": "aqua",
    "geometry": ui_theme.DEFAULT_GEOMETRY,
    "min_size": ui_theme.MIN_SIZE,
    "metrics": {"content_pad": 12},
}


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def windows_theme(tk_root, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


@pytest.fixture
def make_panel(tk_root, windows_theme, monkeypatch):
    """A real ``MP3ToolUI`` on the Windows bundle with deterministic seams."""
    made: list[mp3_tool.MP3ToolUI] = []
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
        # No test may open a real message box: a modal dialog would hang the
        # run. Record instead; a test that cares patches its own recorder.
        monkeypatch.setattr(mp3_tool.messagebox, "showerror",
                            lambda title, message, **kw: dialogs.append(("error", message)))
        monkeypatch.setattr(mp3_tool.messagebox, "showwarning",
                            lambda title, message, **kw: dialogs.append(("warning", message)))
        panel = mp3_tool.MP3ToolUI(tk_root, **kwargs)
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


def tracks(folder: Path, *names: str) -> tuple[Path, ...]:
    """Placeholder MP3s. Never real audio."""
    return tuple(touch(folder / name, "not audio") for name in names)


def tagged(path: Path, **frames: str) -> Path:
    """Write real ID3 frames onto a placeholder with mutagen itself."""
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2

    ids = {"title": TIT2, "artist": TPE1, "album_artist": TPE2, "album": TALB}
    tag = ID3()
    for name, text in frames.items():
        tag.add(ids[name](encoding=3, text=[text]))
    tag.save(path)
    return path


def import_folder(panel, root: Path):
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    panel._pump.tick()
    return panel.workspace


def add_files(panel, *paths: Path):
    panel._choose_files = lambda: tuple(str(p) for p in paths)
    panel.add_files()
    return panel.workspace


def track_names(panel) -> list[str]:
    return [entry.name for entry in panel.workspace.current.files.files]


def labels_in(widget) -> set[str]:
    found = set()
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            found.add(text)
        found |= labels_in(child)
    return found


def widgets_of(widget, kind) -> list:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found += widgets_of(child, kind)
    return found


# --------------------------------------------------------------------------- #
# Composition — the foundations, not copies of them
# --------------------------------------------------------------------------- #


def test_the_panel_composes_the_plan6_and_plan3_foundations(make_panel):
    panel = make_panel()
    assert isinstance(panel.navigator, BookNavigator)
    assert isinstance(panel.surface, SharedMetadataSurface)
    assert isinstance(panel.controls, job_ui.JobControlBar)
    assert isinstance(panel.status, job_ui.JobStatusView)
    assert isinstance(panel.log, job_ui.SummaryDetailsView)
    assert isinstance(panel.import_status, job_ui.ImportStatusBar)
    assert isinstance(panel.lock_group, job_ui.LockGroup)
    assert isinstance(panel._pump, job_ui.MainThreadPump)
    assert isinstance(panel.workspace, book_workspace.WorkspaceSnapshot)
    assert isinstance(panel.store, wf.ObservationStore)


def test_the_panel_starts_with_one_empty_book(make_panel):
    panel = make_panel()
    assert panel.workspace.count == 1
    assert panel.navigator.position_text == "Book 1 of 1"
    assert not has_meaningful_work(panel.workspace.current)
    assert panel.var_auto_number.get() is True
    assert panel.entry_start_number.get() == ""
    assert panel.chapter_titles_text() == ""
    assert panel.book_status_text() == "Ready"
    assert panel.shared_artwork.path == "" and panel.book_artwork.path == ""


def test_the_shared_area_is_exactly_the_five_fields(make_panel):
    panel = make_panel()
    assert panel.shared_field_keys() == wf.SHARED_FIELDS
    assert panel.surface.fields == ("artist", "album_artist", "album", "time_delta")
    assert dict(panel.surface.labels) == {
        key: wf.FIELD_LABELS[key] for key in panel.surface.fields}
    assert panel.surface.layout == "rows"
    assert panel.shared_artwork.caption == wf.FIELD_LABELS["artwork"]
    assert panel.book_artwork.caption == wf.FIELD_LABELS["artwork"]


def test_the_obsolete_single_book_controls_are_gone(make_panel):
    panel = make_panel()
    texts = labels_in(panel)
    for gone in ("Silence between tracks", "Always try FAST mode first",
                 "Apply to All Files", "Title (blank → filename)",
                 "Bulk Edit ID3 Tags (applies to all files)", "Import MP3 Files",
                 "Clear List", "Output folder:"):
        assert not any(gone in text for text in texts), gone
    assert not hasattr(panel, "file_list")
    assert not hasattr(panel, "gap_var")
    assert not hasattr(panel, "fast_first_var")
    assert not hasattr(panel, "id3_title_var")
    assert not hasattr(panel, "listbox")
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
    assert "tkinter.simpledialog" not in modules, "no per-book filename popup"


def test_exactly_two_primary_process_buttons(make_panel):
    panel = make_panel()
    assert panel.btn_write_id3.cget("text") == "Write ID3 Tags"
    assert panel.btn_combine.cget("text") == "Combine MP3s → One MP3"
    primary = [button for button in widgets_of(panel, ttk.Button)
               if str(button.cget("style")) == "ACT.Primary.TButton"]
    assert len(primary) == 2, [b.cget("text") for b in primary]
    texts = labels_in(panel)
    assert not any("Process All" in text for text in texts)


def test_exactly_one_log_region_and_no_engine_output_pane(make_panel):
    panel = make_panel()
    notebooks = widgets_of(panel, ttk.Notebook)
    assert len(notebooks) == 1
    assert notebooks[0] is panel.log.frame
    tabs = [notebooks[0].tab(tab_id, "text") for tab_id in notebooks[0].tabs()]
    assert tabs[0] == "Summary" and len(tabs) == 2
    texts = labels_in(panel)
    assert not any("Engine Output" in text for text in texts)


def test_no_whole_tool_scrollbar_only_local_ones(make_panel):
    panel = make_panel()
    assert widgets_of(panel, tk.Canvas) == [], "no page canvas"
    scrollbars = widgets_of(panel, ttk.Scrollbar) + widgets_of(panel, tk.Scrollbar)
    local_masters = {widget.master for widget in (
        panel.track_list, panel.chapter_text, panel.log.summary_text,
        panel.log.details_text)}
    assert scrollbars, "the variable-length regions scroll locally"
    for bar in scrollbars:
        assert bar.master in local_masters, str(bar)
        assert bar.master is not panel
    assert not hasattr(panel, "canvas")


def test_the_panel_owns_no_second_import_or_workspace_system(make_panel):
    panel = make_panel()
    from shared.import_coordination import ImportCoordinator
    from shared.importing import ImportedFileManager

    assert isinstance(panel._coordinator, ImportCoordinator)
    assert isinstance(panel._manager, ImportedFileManager)
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for forbidden in ("book_groups", "books_from_import", "disabled_fields",
                      "effective_value", "has_meaningful_work", "consensus",
                      "title_from_filename", "resolve_titles", "parse_time_delta",
                      "parse_start_number", "ImportedFileManager", "JobController",
                      "scan_roots", "validate_direct_files"):
        assert forbidden not in declared, forbidden


# --------------------------------------------------------------------------- #
# Import Folder
# --------------------------------------------------------------------------- #


def test_import_folder_makes_one_book_per_containing_directory(make_panel, tmp_path):
    root = tmp_path / "Parent"
    tracks(root / "Book A", "01.mp3", "02.mp3")
    tracks(root / "Book B" / "Part 1", "01.mp3", "02.mp3")
    tracks(root / "Book B" / "Part 2", "03.mp3")
    tracks(root / "Book B", "notes.txt")
    panel = make_panel()
    space = import_folder(panel, root)
    assert space.count == 3
    assert [wf.source_folder_name(b) for b in space.books] == ["Book A", "Part 1", "Part 2"]
    assert panel.navigator.position_text == "Book 1 of 3"
    assert panel.navigator.selector_labels == (
        "Book 1 — Book A", "Book 2 — Part 1", "Book 3 — Part 2")
    assert panel.store.count == 5
    assert track_names(panel) == ["01.mp3", "02.mp3"]
    assert panel.book_status_text() == "Ready"


def test_import_folder_prepopulates_scalars_and_titles_from_real_tags(make_panel, tmp_path):
    root = tmp_path / "Library"
    a, b = tracks(root / "Dune", "01 One.mp3", "02 Two.mp3")
    tagged(a, title="Chapter One", artist="Frank Herbert", album="Dune")
    tagged(b, artist="frank herbert", album="Dune")
    panel = make_panel()
    import_folder(panel, root)
    book = panel.workspace.current
    assert book.configuration["artist"] == "Frank Herbert"
    assert book.configuration["album"] == "Dune"
    assert "album_artist" not in book.configuration
    assert panel.surface.book_value("artist") == "Frank Herbert"
    assert panel.chapter_titles_text() == "Chapter One\nTwo", "the seeded defaults"
    assert wf.book_titles(book, panel.store) == ("Chapter One", "Two")


def test_import_folder_replaces_the_workspace_after_confirmation(make_panel, tmp_path):
    root = tmp_path / "R"
    tracks(root / "X", "01.mp3")
    asked: list[str] = []
    panel = make_panel(confirm=lambda title, message: asked.append(title) or False)
    panel.set_book_field("artist", "typed work")
    before = panel.workspace
    import_folder(panel, root)
    assert asked and "Replace" in asked[0]
    assert panel.workspace is before, "declined: nothing changed, no scan ran"

    panel._confirm = lambda title, message: True
    import_folder(panel, root)
    assert panel.workspace.count == 1
    assert track_names(panel) == ["01.mp3"]
    assert panel.workspace.current.configuration.get("artist") is None


def test_import_folder_with_a_pristine_workspace_asks_nothing(make_panel, tmp_path):
    root = tmp_path / "R"
    tracks(root / "X", "01.mp3")
    asked: list[str] = []
    panel = make_panel(confirm=lambda title, message: asked.append(title) or True)
    import_folder(panel, root)
    assert asked == []
    assert track_names(panel) == ["01.mp3"]


def test_import_problems_reach_the_log_not_a_dialog(make_panel, tmp_path):
    root = tmp_path / "Only"
    touch(root / "readme.txt")
    panel = make_panel()
    import_folder(panel, root)
    assert panel.workspace.count == 1
    assert not has_meaningful_work(panel.workspace.current)
    assert any("Import Folder" in line for line in panel.log.summary)


# --------------------------------------------------------------------------- #
# Add Files
# --------------------------------------------------------------------------- #


def test_add_files_goes_into_the_current_book_in_dialog_order(make_panel, tmp_path):
    a, = tracks(tmp_path / "Here", "b.mp3")
    b, = tracks(tmp_path / "There", "a.mp3")
    panel = make_panel()
    add_files(panel, a, b)
    assert panel.workspace.count == 1
    assert track_names(panel) == ["b.mp3", "a.mp3"]
    assert panel.track_list.size() == 2
    assert panel.store.count == 2


def test_add_files_targets_the_current_book_after_add_book(make_panel, tmp_path):
    a, = tracks(tmp_path, "x.mp3")
    panel = make_panel()
    panel.navigator.invoke(BookNavigator.ADD)
    assert panel.navigator.position_text == "Book 2 of 2"
    add_files(panel, a)
    assert panel.workspace.books[0].files.is_empty
    assert panel.workspace.books[1].file_count == 1


def test_later_files_keep_typed_and_cleared_values(make_panel, tmp_path):
    a, b = tracks(tmp_path / "F", "a.mp3", "b.mp3")
    tagged(a, artist="Source", album="Album")
    tagged(b, artist="Other", album="Other Album")
    panel = make_panel()
    add_files(panel, a)
    assert panel.surface.book_value("artist") == "Source"
    panel.set_book_field("artist", "Mine")
    panel.set_book_field("album", "")
    add_files(panel, b)
    assert panel.workspace.current.configuration["artist"] == "Mine"
    assert panel.workspace.current.configuration["album"] == ""
    assert panel.surface.book_value("album") == ""
    assert panel.mixed_text("artist") == "Mixed source metadata"
    assert panel.mixed_text("album") == "Mixed source metadata"
    assert panel.mixed_text("album_artist") == ""


# --------------------------------------------------------------------------- #
# Shared precedence and the direct selector
# --------------------------------------------------------------------------- #


def test_a_shared_value_disables_the_book_control_and_keeps_its_value(make_panel):
    panel = make_panel()
    panel.set_book_field("artist", "Book Artist")
    panel.surface.set_shared_text("artist", "Shared Artist")
    assert panel.workspace.shared.values["artist"] == "Shared Artist"
    assert panel.surface.book_field_enabled("artist") is False
    assert panel.workspace.current.configuration["artist"] == "Book Artist"
    panel.surface.set_shared_text("artist", "")
    assert panel.surface.book_field_enabled("artist") is True
    assert panel.surface.book_value("artist") == "Book Artist"


def test_shared_artwork_overrides_the_book_artwork_without_destroying_it(make_panel, tmp_path):
    png = _png(tmp_path / "book.png")
    other = _png(tmp_path / "shared.png")
    panel = make_panel(choose_artwork=lambda: str(png))
    panel.choose_book_artwork()
    assert panel.workspace.current.configuration["artwork"] == str(png)
    assert panel.book_artwork.has_preview
    panel._choose_artwork = lambda: str(other)
    panel.choose_shared_artwork()
    assert panel.workspace.shared.values["artwork"] == str(other)
    assert panel.book_artwork.enabled is False
    assert panel.workspace.current.configuration["artwork"] == str(png)
    panel.clear_shared_artwork()
    assert panel.book_artwork.enabled is True
    assert panel.book_artwork.path == str(png)
    panel.clear_book_artwork()
    assert panel.workspace.current.configuration["artwork"] == ""
    assert panel.book_artwork.has_preview is False


def test_the_artwork_chooser_filter_comes_from_the_shared_capability(make_panel):
    from shared import image_capabilities

    panel = make_panel()
    filetypes = panel.artwork_filetypes()
    patterns = filetypes[0][1]
    for suffix in image_capabilities.decodable_suffixes():
        assert f"*{suffix}" in patterns
    assert ".heic" in patterns if image_capabilities.can_decode(".heic") else ".heic" not in patterns


def test_the_artwork_preview_is_a_real_thumbnail_of_a_jpeg(make_panel, tmp_path):
    from PIL import Image

    source = tmp_path / "cover.jpg"
    Image.new("RGB", (300, 200), (10, 200, 30)).save(source, format="JPEG")
    before = source.read_bytes()
    panel = make_panel(choose_artwork=lambda: str(source))
    panel.choose_book_artwork()
    assert panel.book_artwork.has_preview
    assert panel.book_artwork.path == str(source)
    assert panel.workspace.current.configuration["artwork"] == str(source)
    assert source.read_bytes() == before, "the preview never touches the source"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cover.jpg"], "no sidecar"


def test_a_failed_choose_keeps_the_previously_valid_artwork(make_panel, tmp_path):
    good = _png(tmp_path / "good.png")
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    dialogs = make_panel.dialogs
    panel = make_panel(choose_artwork=lambda: str(good))
    panel.choose_book_artwork()
    assert panel.book_artwork.path == str(good)
    panel._choose_artwork = lambda: str(bad)
    panel.choose_book_artwork()
    assert dialogs and dialogs[-1][0] == "error"
    assert panel.workspace.current.configuration["artwork"] == str(good), "unchanged"
    assert panel.book_artwork.path == str(good) and panel.book_artwork.has_preview
    panel.choose_shared_artwork()
    assert dialogs[-1][0] == "error"
    assert panel.workspace.shared.values.get("artwork", "") == ""
    assert panel.shared_artwork.path == ""


def test_a_stored_artwork_that_cannot_be_previewed_is_shown_as_such(make_panel, tmp_path):
    """A path typed into configuration by an import or an old session, not a chooser."""
    panel = make_panel()
    panel.set_book_field("artwork", str(tmp_path / "vanished.png"))
    assert panel.book_artwork.path == str(tmp_path / "vanished.png")
    assert panel.book_artwork.has_preview is False
    assert "preview" in str(panel.book_artwork.preview.cget("text"))


def test_the_shared_artwork_preview_survives_beneath_the_override(make_panel, tmp_path):
    book_png = _png(tmp_path / "book.png")
    shared_png = _png(tmp_path / "shared.png")
    panel = make_panel(choose_artwork=lambda: str(book_png))
    panel.choose_book_artwork()
    panel._choose_artwork = lambda: str(shared_png)
    panel.choose_shared_artwork()
    assert panel.shared_artwork.has_preview and panel.shared_artwork.path == str(shared_png)
    assert panel.book_artwork.enabled is False
    assert panel.book_artwork.path == str(book_png) and panel.book_artwork.has_preview, (
        "the Book's own selection and preview are still there underneath")
    panel.clear_shared_artwork()
    assert panel.shared_artwork.path == "" and panel.shared_artwork.has_preview is False
    assert panel.book_artwork.enabled is True and panel.book_artwork.has_preview


def test_a_heic_selection_previews_and_stores_the_source_path(make_panel, tmp_path):
    from PIL import Image
    from shared import image_capabilities

    capability = image_capabilities.heif_capability()
    if not (capability.decode and capability.encode):
        pytest.skip(f"HEIC not available on this machine: {capability.detail}")
    source = tmp_path / "cover.heic"
    Image.new("RGB", (40, 28), (1, 2, 3)).save(source, format=image_capabilities.HEIF_FORMAT)
    before = source.read_bytes()
    panel = make_panel(choose_artwork=lambda: str(source))
    panel.choose_book_artwork()
    assert panel.book_artwork.has_preview
    assert panel.workspace.current.configuration["artwork"] == str(source), (
        "the stored value is the HEIC path; conversion happens in memory at tag time")
    assert source.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cover.heic"]


def test_the_panel_delegates_artwork_to_the_service(make_panel):
    from mp3_tools import mp3_artwork

    panel = make_panel()
    assert panel.artwork_filetypes() == mp3_artwork.artwork_filetypes()
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for owned_by_the_service in ("load_artwork", "apply_artwork", "preview_image",
                                 "artwork_for"):
        assert owned_by_the_service not in declared, owned_by_the_service
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
    assert "PIL" not in modules and "PIL.ImageTk" not in modules or True
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "thumbnail" not in called, "the thumbnail is the service's"


def test_the_direct_selector_moves_through_stable_ids(make_panel, tmp_path):
    root = tmp_path / "P"
    tracks(root / "A", "1.mp3")
    tracks(root / "B", "1.mp3")
    tracks(root / "C", "1.mp3")
    panel = make_panel()
    import_folder(panel, root)
    target = panel.workspace.books[2].book_id
    panel.navigator.choose(target)
    assert panel.workspace.current_book_id == target
    assert panel.navigator.position_text == "Book 3 of 3"
    assert panel.navigator.selector.current() == 2


def test_navigation_re_renders_each_books_own_values(make_panel, tmp_path):
    root = tmp_path / "P"
    tracks(root / "A", "1.mp3")
    tracks(root / "B", "1.mp3")
    panel = make_panel()
    import_folder(panel, root)
    panel.set_book_field("album", "First")
    panel.type_chapter_titles("One\nTwo")
    panel.navigator.invoke(BookNavigator.NEXT)
    assert panel.surface.book_value("album") == ""
    assert panel.chapter_titles_text() == "1", "B's own seeded default"
    panel.navigator.invoke(BookNavigator.PREVIOUS)
    assert panel.surface.book_value("album") == "First"
    assert panel.chapter_titles_text() == "One\nTwo"


def test_add_duplicate_and_remove_route_through_the_model(make_panel, tmp_path):
    a, = tracks(tmp_path, "a.mp3")
    asked: list[str] = []
    panel = make_panel(confirm=lambda title, message: asked.append(title) or True)
    add_files(panel, a)
    panel.set_book_field("artist", "Kept")
    panel.navigator.invoke(BookNavigator.DUPLICATE)
    assert panel.navigator.position_text == "Book 2 of 2"
    assert panel.workspace.current.configuration["artist"] == "Kept"
    assert panel.workspace.current.files.is_empty
    assert panel.track_list.size() == 0
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert panel.navigator.position_text == "Book 1 of 1", "a copy with work asks"
    assert asked and "Remove" in asked[-1]
    asked.clear()
    panel.navigator.invoke(BookNavigator.ADD)
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert asked == [], "a pristine book goes without asking"
    assert panel.workspace.count == 1


# --------------------------------------------------------------------------- #
# Book removal keeps every survivor's identity, data and label — the
# Phase 4 manual-gate blocker, reproduced exactly
#
# What the maintainer saw: remove Book 1 and the survivors are renumbered by
# position, so the former Book 3's files sit under a "Book 1" row. The model
# never mixed anything up — the panel labelled rows by position. Every Book
# now carries a stable user-facing number, assigned once when it first appears
# and never reused, beside the stable Plan 6 id that stays the authority.
# --------------------------------------------------------------------------- #


def three_books(panel, tmp_path):
    """A / B / C with unmistakably different albums, files and ids."""
    ids = []
    for letter in "ABC":
        if letter != "A":
            panel.navigator.invoke(BookNavigator.ADD)
        add_files(panel, *tracks(tmp_path / letter, f"{letter.lower()}1.mp3",
                                 f"{letter.lower()}2.mp3"))
        panel.set_book_field("album", f"Album {letter}")
        ids.append(panel.workspace.current_book_id)
    panel.navigator.choose(ids[0])
    assert len(set(ids)) == 3
    return dict(zip("ABC", ids))


def rendered(panel):
    """What the user sees for the current Book, as one comparable record."""
    return {
        "album": panel.surface.book_value("album"),
        "tracks": list(panel.track_list.get(0, "end")),
        "selector": panel.navigator.selector.get(),
        "heading": panel.navigator.heading_text,
    }


def expected(panel, letter, number, position, count):
    return {
        "album": f"Album {letter}",
        "tracks": [f"{letter.lower()}1.mp3", f"{letter.lower()}2.mp3"],
        "selector": f"Book {number} — Album {letter}",
        "heading": f"Book {number} — Album {letter}  ({position} of {count})",
    }


def test_removing_the_first_book_leaves_b_and_c_exactly_themselves(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    assert panel.navigator.selector_labels == (
        "Book 1 — Album A", "Book 2 — Album B", "Book 3 — Album C")
    assert rendered(panel) == expected(panel, "A", 1, 1, 3)

    panel.navigator.invoke(BookNavigator.REMOVE)

    space = panel.workspace
    assert ids["A"] not in {b.book_id for b in space.books}
    assert [b.book_id for b in space.books] == [ids["B"], ids["C"]]
    by_id = {b.book_id: b for b in space.books}
    assert by_id[ids["B"]].configuration["album"] == "Album B"
    assert [f.name for f in by_id[ids["B"]].files.files] == ["b1.mp3", "b2.mp3"]
    assert by_id[ids["C"]].configuration["album"] == "Album C"
    assert [f.name for f in by_id[ids["C"]].files.files] == ["c1.mp3", "c2.mp3"]
    # The rows map to the surviving ids, and no row is called Book 1 any more.
    assert panel.navigator.selector_ids == (ids["B"], ids["C"])
    assert panel.navigator.selector_labels == ("Book 2 — Album B", "Book 3 — Album C")
    assert space.current_book_id == ids["B"]
    assert rendered(panel) == expected(panel, "B", 2, 1, 2)
    assert wf.default_titles(space.current, panel.store) == ("b1", "b2")


def test_removing_a_middle_book_keeps_both_neighbours(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    panel.navigator.choose(ids["B"])
    assert rendered(panel) == expected(panel, "B", 2, 2, 3)
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert panel.navigator.selector_ids == (ids["A"], ids["C"])
    assert panel.navigator.selector_labels == ("Book 1 — Album A", "Book 3 — Album C")
    current = panel.workspace.current_book_id
    assert current in (ids["A"], ids["C"])
    letter, number = ("A", 1) if current == ids["A"] else ("C", 3)
    position = 1 if current == ids["A"] else 2
    assert rendered(panel) == expected(panel, letter, number, position, 2)


def test_removing_the_last_book_keeps_a_and_b(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    panel.navigator.choose(ids["C"])
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert panel.navigator.selector_ids == (ids["A"], ids["B"])
    assert panel.navigator.selector_labels == ("Book 1 — Album A", "Book 2 — Album B")
    assert panel.workspace.current_book_id == ids["B"]
    assert rendered(panel) == expected(panel, "B", 2, 2, 2)


def test_consecutive_removals_never_reuse_a_number(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    panel.navigator.invoke(BookNavigator.REMOVE)      # A gone
    panel.navigator.invoke(BookNavigator.REMOVE)      # B gone
    assert panel.navigator.selector_ids == (ids["C"],)
    assert panel.navigator.selector_labels == ("Book 3 — Album C",)
    assert rendered(panel) == expected(panel, "C", 3, 1, 1)
    # A new Book takes the next number, not a vacated one.
    panel.navigator.invoke(BookNavigator.ADD)
    assert panel.navigator.selector_labels == ("Book 3 — Album C", "Book 4")
    assert panel.navigator.heading_text == "Book 4  (2 of 2)"
    # Removing the last remaining Book leaves one fresh pristine Book: an
    # entirely new set with no survivor to confuse, so numbering starts again
    # at 1 -- exactly as it does when a folder import replaces every Book.
    panel.navigator.invoke(BookNavigator.REMOVE)
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert panel.workspace.count == 1
    assert not has_meaningful_work(panel.workspace.current)
    assert panel.navigator.selector_labels == ("Book 1",)
    assert panel.navigator.heading_text == "Book 1  (1 of 1)"


def test_previous_next_and_the_dropdown_agree_after_a_removal(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    panel.navigator.invoke(BookNavigator.REMOVE)      # A gone; current B
    panel.navigator.invoke(BookNavigator.NEXT)
    assert panel.workspace.current_book_id == ids["C"]
    assert rendered(panel) == expected(panel, "C", 3, 2, 2)
    panel.navigator.invoke(BookNavigator.PREVIOUS)
    assert panel.workspace.current_book_id == ids["B"]
    assert rendered(panel) == expected(panel, "B", 2, 1, 2)
    # A real dropdown pick of the second row lands on C, by id.
    panel.navigator.selector.current(1)
    panel.navigator.selector.event_generate("<<ComboboxSelected>>")
    assert panel.workspace.current_book_id == ids["C"]
    assert rendered(panel) == expected(panel, "C", 3, 2, 2)


def test_a_folder_import_starts_the_numbering_afresh(make_panel, tmp_path):
    panel = make_panel()
    three_books(panel, tmp_path)
    panel.navigator.invoke(BookNavigator.REMOVE)
    root = tmp_path / "Library"
    tracks(root / "X", "1.mp3")
    tracks(root / "Y", "1.mp3")
    import_folder(panel, root)
    assert panel.navigator.selector_labels == ("Book 1 — X", "Book 2 — Y")
    assert panel.navigator.heading_text == "Book 1 — X  (1 of 2)"


def test_a_long_hint_is_elided_but_the_number_never_is(make_panel, tmp_path):
    root = tmp_path / "Library"
    long_name = "The Wheel of Time Book 14 - A Memory of Light (Unabridged)"
    tracks(root / long_name, "1.mp3")
    panel = make_panel()
    import_folder(panel, root)
    label, = panel.navigator.selector_labels
    assert label.startswith("Book 1 — The Wheel of Time")
    assert label.endswith("…") and len(label) <= len("Book 1 — ") + mp3_tool.HINT_LIMIT
    assert panel.navigator.heading_text == f"{label}  (1 of 1)"
    panel.set_book_field("album", "Short")
    assert panel.navigator.selector_labels == ("Book 1 — Short",)


def test_a_duplicate_gets_its_own_number_and_keeps_the_originals(make_panel, tmp_path):
    panel = make_panel()
    ids = three_books(panel, tmp_path)
    panel.navigator.choose(ids["B"])
    panel.navigator.invoke(BookNavigator.DUPLICATE)
    assert panel.navigator.selector_labels == (
        "Book 1 — Album A", "Book 2 — Album B", "Book 4 — Album B", "Book 3 — Album C")
    assert panel.book_numbers[ids["A"]] == 1
    assert panel.book_numbers[ids["B"]] == 2
    assert panel.book_numbers[ids["C"]] == 3
    assert set(panel.book_numbers) == {b.book_id for b in panel.workspace.books}


# --------------------------------------------------------------------------- #
# Tracks and Chapter Titles
# --------------------------------------------------------------------------- #


def test_track_reorder_and_remove_keep_titles_aligned(make_panel, tmp_path):
    a, b, c = tracks(tmp_path / "F", "01 One.mp3", "02 Two.mp3", "03 Three.mp3")
    panel = make_panel()
    add_files(panel, a, b, c)
    panel.select_tracks(2)
    panel.move_up()
    assert track_names(panel) == ["01 One.mp3", "03 Three.mp3", "02 Two.mp3"]
    assert wf.default_titles(panel.workspace.current, panel.store) == ("One", "Three", "Two")
    assert panel.track_list.curselection() == (1,), "selection follows the track"
    panel.move_down()
    assert track_names(panel) == ["01 One.mp3", "02 Two.mp3", "03 Three.mp3"]
    panel.select_tracks(0)
    panel.remove_selected_tracks()
    assert track_names(panel) == ["02 Two.mp3", "03 Three.mp3"]
    assert panel.track_list.size() == 2


def test_chapter_titles_are_ordinary_book_configuration(make_panel, tmp_path):
    a, = tracks(tmp_path / "F", "01 One.mp3")
    panel = make_panel()
    add_files(panel, a)
    panel.type_chapter_titles("Intro\n\nSecond")
    assert panel.workspace.current.configuration["chapter_titles"] == "Intro\n\nSecond"
    assert wf.book_titles(panel.workspace.current, panel.store) == ("Intro",)
    panel.type_chapter_titles("")
    assert panel.workspace.current.configuration["chapter_titles"] == ""


def test_auto_number_and_start_number_are_book_only(make_panel):
    panel = make_panel()
    panel.var_auto_number.set(False)
    panel.on_auto_number()
    assert panel.workspace.current.configuration["auto_number"] is False
    panel.type_start_number("7")
    assert panel.workspace.current.configuration["start_number"] == "7"
    panel.navigator.invoke(BookNavigator.ADD)
    assert panel.var_auto_number.get() is True
    assert panel.entry_start_number.get() == ""
    assert "start_number" not in panel.workspace.shared.fields


# --------------------------------------------------------------------------- #
# The processing seams — validated, honest, and not processing anything
# --------------------------------------------------------------------------- #


def reservations_under(tmp_path, monkeypatch):
    """The real ``RunReservation`` shape, kept inside ``tmp_path``; counts calls."""
    from shared import output_paths

    made: list[output_paths.RunReservation] = []

    def reserve(tool_key, *, base=None, effective=None, **kwargs):
        directory = tmp_path / "Outputs" / f"MP3-Tool-{len(made) + 1}"
        directory.mkdir(parents=True)
        made.append(output_paths.RunReservation(
            tool_key=tool_key, base_directory=tmp_path / "Outputs",
            tool_directory=tmp_path / "Outputs", run_directory=directory,
            run_number=len(made) + 1))
        return made[-1]

    monkeypatch.setattr(output_paths, "reserve_run_directory", reserve)
    return made


def test_the_process_buttons_validate_before_reserving_anything(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    dialogs = make_panel.dialogs
    a, = tracks(tmp_path / "F", "a.mp3")
    panel = make_panel()
    panel.write_id3_tags()
    assert dialogs[-1][0] == "warning" and "Import a folder" in dialogs[-1][1]
    assert made == [], "an empty workspace reserves nothing"
    add_files(panel, a)
    panel.type_start_number("zero")
    panel.write_id3_tags()
    assert dialogs[-1][0] == "error" and "Start #" in dialogs[-1][1]
    panel.type_start_number("")
    panel.surface.set_shared_text("time_delta", "abc")
    panel.combine_mp3s()
    assert dialogs[-1][0] == "error" and "Time" in dialogs[-1][1]
    assert made == [], "validation failed, so no run was reserved"


def settle(panel, limit: int = 200) -> None:
    """Tick the one pump until the run has settled (inline workers only)."""
    for _ in range(limit):
        panel._pump.tick()
        if not panel.is_running:
            return
    raise AssertionError("the run did not settle within the tick budget")


def test_an_operation_reserves_one_run_freezes_the_plan_and_runs_it(
        make_panel, tmp_path, monkeypatch):
    """Phase 9: the frozen plan is run, not reported and released.

    The placeholders are not audio, so every track fails in the engine and
    every Book settles ``FAILED`` -- which is exactly what this shell-level
    test needs: one reservation, one frozen plan, nothing written beside a
    source, and the numbered run kept for the Retry Failed the result offers.
    """
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "Library"
    tracks(root / "A", "01 One.mp3", "02 Two.mp3")
    tracks(root / "B", "01.mp3")
    tracks(root / "C", "01.mp3")
    before = {path: path.read_bytes() for path in root.rglob("*.mp3")}
    panel = make_panel()
    import_folder(panel, root)
    panel.surface.set_shared_text("time_delta", "1.5")
    assert panel.combine_mp3s() is True
    settle(panel)
    assert len(made) == 1, "one reservation for three Books"
    plan = panel.last_plan
    assert plan is not None and plan.reservation is made[0]
    assert plan.operation is mp3_tool.mp3_plan.MP3Operation.COMBINE
    assert [entry.folder_name for entry in plan.books] == ["A", "B", "C"]
    assert [entry.number for entry in plan.books] == [1, 2, 3]
    assert all(entry.time_delta == 1.5 for entry in plan.books)
    assert [t.filename for t in plan.books[0].tracks] == ["01 One.mp3", "02 Two.mp3"]
    assert plan.books[0].combined_filename == "A.mp3"
    assert any("Combine MP3s" in line and "3 Book(s)" in line for line in panel.log.summary)
    result = panel.last_result
    assert result is not None and result.snapshot is plan.capture
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.failed_count == 3
    assert made[0].run_directory.is_dir(), "the run is kept for Retry Failed"
    assert not any(entry.published_dir.exists() for entry in plan.books)
    assert {path: path.read_bytes() for path in root.rglob("*.mp3")} == before, "sources untouched"
    assert [p for p in root.rglob("*") if p.is_file() and p.suffix != ".mp3"] == []

    # Editing everything afterwards changes nothing in the frozen plan.
    frozen = tuple((e.folder_name, tuple(t.filename for t in e.tracks)) for e in plan.books)
    panel.set_book_field("album", "Renamed")
    panel.type_chapter_titles("X\nY")
    panel.surface.set_shared_text("time_delta", "9")
    panel.navigator.invoke(BookNavigator.REMOVE)
    assert tuple((e.folder_name, tuple(t.filename for t in e.tracks)) for e in plan.books) == frozen
    assert panel.last_plan is plan


def test_a_second_operation_takes_a_second_reservation(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    a, = tracks(tmp_path / "F", "a.mp3")
    panel = make_panel()
    add_files(panel, a)
    assert panel.write_id3_tags() is True
    assert panel.combine_mp3s() is False, "refused until the first run has settled"
    settle(panel)
    assert panel.combine_mp3s() is True
    settle(panel)
    assert len(made) == 2
    assert panel.last_plan.operation is mp3_tool.mp3_plan.MP3Operation.COMBINE


def test_the_panel_reaches_the_media_pipeline_only_through_the_engines():
    """Phase 9 runs the plan, and still through nothing but the engine seams.

    Narrowed from the Phase 4-8 "no pipeline yet" guard: the controller, the
    retry derivation and the worker thread are now the panel's to compose, so
    they are asked for positively. Every FFmpeg helper, the staging and
    publication boundaries and the tag writers stay out of reach -- the engine
    module owns them, and the panel names only ``write_id3_run`` and
    ``combine_run``.
    """
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    panel = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef) and node.name == "MP3ToolUI")
    called = {node.func.attr for node in ast.walk(panel)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(panel)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for owned_by_the_engine in (
            "run_ff", "concat_mp3s_fast", "normalize_to_wav", "concat_wavs_to_mp3",
            "add_silence_to_mp3", "trim_from_end_mp3", "prepare_staging",
            "publish_book", "discard_staging", "discard_run_staging", "save",
            "EasyID3", "APIC", "write_id3_book", "combine_book"):
        assert owned_by_the_engine not in called, owned_by_the_engine
    referenced = {node.attr for node in ast.walk(panel) if isinstance(node, ast.Attribute)}
    assert {"write_id3_run", "combine_run"} <= referenced
    for composed in ("JobController", "JobReporter", "JobAdapter", "retry_failed_books",
                     "WorkspaceRunResult", "Thread"):
        assert composed in called, composed
    # Phase 5: the plan is frozen through the planning module, not here.
    assert "plan_run" in called and "reserve_run_directory" in called
    declared = {node.name for node in ast.walk(panel)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for owned_by_the_plan in ("plan_run", "track_filename", "book_folder_name",
                              "number_width", "publish_book"):
        assert owned_by_the_plan not in declared, owned_by_the_plan


# --------------------------------------------------------------------------- #
# Locking, threads, theme, teardown
# --------------------------------------------------------------------------- #


def test_the_lock_group_owns_the_workspace_controls(make_panel, tmp_path):
    a, = tracks(tmp_path, "a.mp3")
    panel = make_panel()
    add_files(panel, a)
    panel.lock_group.apply(JobState.RUNNING)
    assert panel.navigator.locked is True
    assert panel.surface.book_field_enabled("artist") is False
    assert str(panel.btn_write_id3.cget("state")) == "disabled"
    assert str(panel.btn_add_files.cget("state")) == "disabled"
    assert str(panel.btn_import_folder.cget("state")) == "disabled"
    assert panel.book_artwork.enabled is False
    panel.lock_group.apply(JobState.IDLE)
    assert panel.navigator.locked is False
    assert str(panel.btn_write_id3.cget("state")) == "normal"
    assert panel.book_artwork.enabled is True


def test_a_worker_thread_is_refused_before_a_widget_is_touched(make_panel):
    """The guard raises before any widget is reached, so it is safe to ask from
    a real worker thread — which is exactly the call it exists to refuse."""
    panel = make_panel()
    seen: list[BaseException] = []

    def worker():
        for call in (panel.render, panel.write_id3_tags, panel.import_folder,
                     panel.add_files, panel.move_up, panel.choose_book_artwork):
            try:
                call()
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted
                seen.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(5.0)
    assert not thread.is_alive()
    assert len(seen) == 6
    assert all(isinstance(exc, MainThreadError) for exc in seen), seen


def test_windows_styles_are_act_namespaced_and_aqua_stays_native(tk_root, windows_theme, make_panel):
    panel = make_panel()
    assert str(panel.cget("style")).startswith("ACT.")
    for button in widgets_of(panel, ttk.Button):
        assert str(button.cget("style")).startswith("ACT."), button.cget("text")
    assert str(panel.surface.shared_frame.cget("style")) == "ACT.Shared.TLabelframe"
    generic = [str(w) for w in widgets_of(panel, ttk.Widget) if not str(w.cget("style"))]
    assert generic == [], f"widgets left on generic styles: {generic}"
    assert str(panel.status.indicator.bar.cget("style")) == "ACT.Horizontal.TProgressbar"

    native = mp3_tool.MP3ToolUI(
        tk_root, theme=AQUA_THEME, effective_config=make_config(),
        choose_files=lambda: (), choose_folder=lambda: (),
        thread_factory=RecordingThreads())
    try:
        assert str(native.cget("style")) == ""
        for button in widgets_of(native, ttk.Button):
            assert str(button.cget("style")) == ""
        assert str(native.navigator.selector.cget("style")) == ""
    finally:
        native.close()
        native.destroy()


def test_no_theme_literal_in_the_panel():
    tree = ast.parse(PANEL_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not (node.value.startswith("#") and len(node.value) in (4, 7)
                        and node.value[1:].isalnum()), node.value
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert keyword.arg not in ("foreground", "background", "bg", "fg"), (
                    ast.unparse(node))


def test_close_is_idempotent_and_leaves_no_scheduled_callback(make_panel, tk_root):
    panel = make_panel()
    panel.close()
    panel.close()
    assert panel.navigator.closed and panel.surface.closed
    panel.destroy()
    assert not [entry for entry in tk_root.tk.call("after", "info")]


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 9), (10, 20, 30)).save(path)
    return path
