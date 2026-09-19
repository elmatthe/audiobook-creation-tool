"""``Clear All Imports`` — the maintainer-directed v0.6.4 Phase 12 amendment.

One destructive workspace action, with one label, one confirmation philosophy
and one styling authority, on all three shared multi-Book tools: the MP3 Tool,
the M4B Maker and the M4B Metadata Editor. It returns the tool to the exact
pristine state it has when freshly opened — through that tool's own
``new_workspace()`` reset authority, never a parallel Tk list — and touches
nothing else: no source file, no output already written, no log line, no
setting, no run in progress (the shared lock matrix keeps it disabled while a
run owns the workspace).

"Meaningful work" is the shared vocabulary composed, not a fourth definition:
any Book with imported files or configuration (``has_meaningful_work``) or any
populated Shared field (``SharedMetadata.populated_fields``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import output_paths, ui_theme  # noqa: E402
from shared.book_workspace import has_meaningful_work  # noqa: E402
from shared.job_control import JobState  # noqa: E402

from mp3_tools import m4b_maker, m4b_metadata_editor as editor, mp3_tool  # noqa: E402
from mp3_tools import m4b_maker_workflow as maker_wf  # noqa: E402
from mp3_tools import m4b_metadata_workflow as editor_wf  # noqa: E402
from mp3_tools import mp3_workflow  # noqa: E402

from test_import_coordination import RecordingThreads  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_m4b_maker_ui import (  # noqa: E402,F401 - fixtures by import
    make_panel as make_maker, output_base, tk_root, windows_theme, tone,
)
from test_m4b_metadata_editor_ui import (  # noqa: E402,F401
    library as editor_library, make_panel as make_editor,
)
from test_m4b_metadata_processing import container, png, sha  # noqa: E402,F401
from test_mp3_tool_ui import make_panel as make_mp3, tagged, tracks  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
LABEL = "Clear All Imports"


def import_folder(panel, root: Path):
    panel._choose_folder = lambda: (str(root),)
    panel.import_folder()
    panel._pump.tick()
    return panel.workspace


def parked_threads():
    import test_import_coordination as tic

    class Parked(tic.InlineThread):
        def start(self):
            pass

    return RecordingThreads(kind=Parked)


def hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}


def pristine_shape(panel, workflow) -> None:
    """The exact startup shape, compared against the tool's own reset authority."""
    fresh = workflow.new_workspace(id_factory=panel._ids)
    space = panel.workspace
    assert space.count == 1 and space.current.is_empty
    assert space.current.configuration == {} == fresh.current.configuration
    assert space.shared.fields == fresh.shared.fields
    assert space.shared.values == {} == fresh.shared.values
    # Exactly what a freshly opened panel holds: the one pristine Book, numbered 1.
    assert panel.book_numbers == {space.current.book_id: 1}
    assert panel.last_plan is None
    assert panel.navigator.position_text == "Book 1 of 1"
    assert all(panel.surface.shared_value(name) == "" for name in panel.surface.fields)
    assert all(panel.surface.book_value(name) == "" for name in panel.surface.fields)
    assert panel.shared_artwork.path == "" and panel.book_artwork.path == ""
    assert panel.chapter_titles_text() == ""


# --------------------------------------------------------------------------- #
# Population helpers: several Books, Shared, a Book edit, chapters, artwork
# --------------------------------------------------------------------------- #


def populate_maker(panel, tmp_path):
    root = tmp_path / "Library"
    tone(root / "A" / "01.mp3")
    tone(root / "B" / "01.mp3")
    import_folder(panel, root)
    panel.on_shared_change("album", "Shared Album")
    panel.set_book_field("title", "Alpha")
    panel.type_chapter_titles("One")
    panel._choose_artwork = lambda: str(png(tmp_path / "art.png"))
    panel.choose_book_artwork()
    panel.on_duplicate()
    panel._choose_files = lambda: (str(tone(tmp_path / "extra" / "x.mp3")),)
    panel.add_files()
    return root


def populate_editor(panel, container, tmp_path):
    root = editor_library(container, tmp_path / "Library")
    import_folder(panel, root)
    panel.surface.set_shared_text("genre", "Shared G")
    panel.set_book_field("title", "Alpha Edited")
    panel.type_chapter_titles("\nThe End")
    panel._choose_artwork = lambda: str(png(tmp_path / "art.png"))
    panel.choose_book_artwork()
    return root


def populate_mp3(panel, tmp_path):
    root = tmp_path / "Library"
    tagged(tracks(root / "A", "01.mp3")[0], title="Alpha")
    tracks(root / "B", "01.mp3")
    import_folder(panel, root)
    panel.on_shared_change("album", "Shared Album")
    panel.set_book_field("artist", "Alpha Edited")
    panel.type_chapter_titles("One")
    panel._choose_artwork = lambda: str(png(tmp_path / "art.png"))
    panel.choose_book_artwork()
    panel.on_add()
    return root


# --------------------------------------------------------------------------- #
# The reset, on all three tools
# --------------------------------------------------------------------------- #


def test_maker_clear_all_imports_returns_the_pristine_startup_state(make_maker, tmp_path,
                                                                     output_base):
    panel = make_maker()
    root = populate_maker(panel, tmp_path)
    assert panel.workspace.count == 3
    panel.on_previous()
    panel.on_previous()
    assert panel.build() is True          # outputs on disk before the reset
    panel._pump.tick()
    plan = panel.last_plan
    outputs = hashes(plan.root)
    assert outputs
    before = hashes(root)
    summary_before = tuple(panel.log.summary)
    asked: list[str] = []
    panel._confirm = lambda title, message: asked.append(message) or True
    assert panel.clear_all_imports() is True
    assert asked and "not deleted or modified" in asked[-1]
    pristine_shape(panel, maker_wf)
    assert panel.run is None and panel.book_status_text() == m4b_maker.STATUS_READY
    assert panel.track_list.size() == 0
    assert hashes(root) == before and hashes(plan.root) == outputs
    assert tuple(panel.log.summary)[:len(summary_before)] == summary_before, "log kept"
    assert any(LABEL in line for line in panel.log.summary)
    assert panel.var_outdir.get() == output_paths.destination_hint(m4b_maker.TOOL_KEY)


def test_editor_clear_all_imports_returns_the_pristine_startup_state(make_editor, container,
                                                                      tmp_path, output_base):
    panel = make_editor()
    root = populate_editor(panel, container, tmp_path)
    assert panel.workspace.count == 3 and panel.store.entries
    assert panel.save() is True
    panel._pump.tick()
    plan = panel.last_plan
    outputs = hashes(plan.run_directory)
    assert outputs
    before = hashes(root)
    summary_before = tuple(panel.log.summary)
    asked: list[str] = []
    panel._confirm = lambda title, message: asked.append(message) or True
    assert panel.clear_all_imports() is True
    assert asked and "not deleted or modified" in asked[-1]
    pristine_shape(panel, editor_wf)
    assert panel.store.entries == {} and panel.run is None
    assert panel.book_status_text() == editor.STATUS_READY
    assert panel.source_text().startswith("No source")
    assert hashes(root) == before and hashes(plan.run_directory) == outputs
    assert tuple(panel.log.summary)[:len(summary_before)] == summary_before
    assert any(LABEL in line for line in panel.log.summary)


def test_mp3_clear_all_imports_returns_the_pristine_startup_state(make_mp3, tmp_path,
                                                                   output_base):
    panel = make_mp3()
    root = populate_mp3(panel, tmp_path)
    assert panel.workspace.count == 3
    kept = output_base / "MP3-Tool-Outputs" / "MP3-Tool-1" / "earlier.mp3"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"an output from an earlier run")
    before = hashes(root)
    panel.log.append("a line from before the reset")
    summary_before = tuple(panel.log.summary)
    asked: list[str] = []
    panel._confirm = lambda title, message: asked.append(message) or True
    assert panel.clear_all_imports() is True
    assert asked and "not deleted or modified" in asked[-1]
    pristine_shape(panel, mp3_workflow)
    assert panel.store.entries == {} if hasattr(panel.store, "entries") else True
    assert panel.book_status_text() == mp3_tool.STATUS_READY
    assert hashes(root) == before
    assert kept.read_bytes() == b"an output from an earlier run"
    assert tuple(panel.log.summary)[:len(summary_before)] == summary_before
    assert any(LABEL in line for line in panel.log.summary)


# --------------------------------------------------------------------------- #
# Confirmation philosophy: pristine asks nothing; meaningful asks; No changes nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", ["maker", "editor", "mp3"])
def test_pristine_asks_nothing_meaningful_asks_and_declining_changes_nothing(
        tool, make_maker, make_editor, make_mp3, container, tmp_path, output_base):
    asked: list[str] = []
    answers = {"value": False}
    confirm = lambda title, message: asked.append(message) or answers["value"]  # noqa: E731
    if tool == "maker":
        panel = make_maker(confirm=confirm)
    elif tool == "editor":
        panel = make_editor(confirm=confirm)
    else:
        panel = make_mp3(confirm=confirm)
    # Pristine: no dialog, still pristine.
    assert panel.clear_all_imports() is True
    assert asked == []
    assert panel.workspace.count == 1 and panel.workspace.current.is_empty
    # A Shared value alone is meaningful work (the shared vocabulary, composed).
    panel.on_shared_change(panel.surface.fields[0], "only shared")
    assert not any(has_meaningful_work(b) for b in panel.workspace.books)
    assert panel.workspace.shared.populated_fields
    assert panel.clear_all_imports() is False
    assert len(asked) == 1 and panel.workspace.shared.populated_fields
    panel.on_shared_change(panel.surface.fields[0], "")
    # Populated: asked; declining changes nothing at all.
    if tool == "maker":
        populate_maker(panel, tmp_path)
    elif tool == "editor":
        populate_editor(panel, container, tmp_path)
    else:
        populate_mp3(panel, tmp_path)
    space = panel.workspace
    numbers = dict(panel.book_numbers)
    assert panel.clear_all_imports() is False
    assert len(asked) == 2 and "unsaved" in asked[-1]
    assert panel.workspace is space and panel.book_numbers == numbers
    answers["value"] = True
    assert panel.clear_all_imports() is True
    assert panel.workspace.count == 1 and panel.workspace.current.is_empty


# --------------------------------------------------------------------------- #
# Locked through the shared matrix while a run owns the workspace
# --------------------------------------------------------------------------- #


def test_maker_and_editor_clear_all_imports_are_locked_during_a_run(
        make_maker, make_editor, container, tmp_path, output_base):
    maker = make_maker()
    tone(tmp_path / "Library" / "A" / "01.mp3")
    import_folder(maker, tmp_path / "Library")
    maker._thread_factory = parked_threads()
    assert maker.build() is True
    assert "disabled" in maker.btn_clear_imports.state()
    assert maker.clear_all_imports() is False and maker.workspace.count == 1
    assert not maker.workspace.current.is_empty, "the live workspace was not touched"
    maker._thread_factory.bodies[0]()
    maker._pump.tick()
    assert "disabled" not in maker.btn_clear_imports.state()

    ed = make_editor()
    import_folder(ed, editor_library(container, tmp_path / "EditorLib"))
    ed._thread_factory = parked_threads()
    assert ed.save() is True
    assert "disabled" in ed.btn_clear_imports.state()
    assert ed.clear_all_imports() is False and ed.workspace.count == 3
    ed._thread_factory.bodies[0]()
    ed._pump.tick()
    assert "disabled" not in ed.btn_clear_imports.state()
    assert ed.last_result.state is JobState.SUCCEEDED, "the run was never interfered with"


def test_mp3_clear_all_imports_is_locked_by_the_shared_group(make_mp3, tmp_path):
    panel = make_mp3()
    populate_mp3(panel, tmp_path)
    panel.lock_group.apply(JobState.RUNNING)
    assert str(panel.btn_clear_imports.cget("state")) == "disabled"
    panel.lock_group.apply(JobState.IDLE)
    assert str(panel.btn_clear_imports.cget("state")) == "normal"


# --------------------------------------------------------------------------- #
# The Editor keeps two unmistakable actions
# --------------------------------------------------------------------------- #


def test_editor_clear_all_imports_and_clear_all_tags_are_distinct_actions(
        make_editor, container, tmp_path, output_base):
    panel = make_editor()
    assert str(panel.btn_clear_imports.cget("text")) == LABEL
    assert str(panel.btn_clear_tags.cget("text")).startswith("Clear All Tags")
    assert panel.btn_clear_imports is not panel.btn_clear_tags
    populate_editor(panel, container, tmp_path)
    # Clear All Imports reserves no run and writes nothing.
    assert panel.clear_all_imports() is True
    assert not output_base.exists()
    # Clear All Tags never resets the workspace.
    populate_editor(panel, container, tmp_path)
    assert panel.on_clear_all_tags() is True
    panel._pump.tick()
    assert panel.workspace.count == 3 and panel.last_plan is not None
    tree = ast.parse((UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    calls = lambda fn: {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}  # noqa: E731
    assert "self._start_action" not in calls(functions["clear_all_imports"])
    assert "self._reserve_run" not in calls(functions["clear_all_imports"])
    assert "wf.new_workspace" in calls(functions["clear_all_imports"])
    assert "wf.new_workspace" not in calls(functions["on_clear_all_tags"])


# --------------------------------------------------------------------------- #
# Placement, styling authority, layout
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", ["maker", "editor", "mp3"])
def test_the_button_sits_in_the_import_band_with_the_destructive_style(
        tool, make_maker, make_editor, make_mp3, tk_root):
    panel = {"maker": make_maker, "editor": make_editor, "mp3": make_mp3}[tool]()
    button = panel.btn_clear_imports
    assert str(button.cget("text")) == LABEL
    assert button.master is panel.btn_import_folder.master, "the import band"
    styles = panel.theme["styles"]
    assert str(button.cget("style")) == styles["danger_button"]
    assert str(button.cget("command")), "wired"
    assert panel.import_status.frame.master is button.master


def test_the_button_asks_the_style_authority_and_names_no_colour():
    for relative in ("mp3_tools/mp3_tool.py", "mp3_tools/m4b_maker.py",
                     "mp3_tools/m4b_metadata_editor.py"):
        tree = ast.parse((UNIVERSAL / relative).read_text(encoding="utf-8"))
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        assert LABEL in literals, relative
        assert not any(v.startswith("#") and len(v) in (4, 7) for v in literals), relative
        assert "shared.book_workspace.has_meaningful_work" in {
            f"{n.module}.{a.name}" for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) for a in n.names}, relative


def test_aqua_builds_the_button_natively(tk_root):
    aqua = {"mode": "aqua", "geometry": ui_theme.DEFAULT_GEOMETRY,
            "min_size": ui_theme.AQUA_MIN_SIZE,
            "metrics": {"navigator_layout": "stacked", "actions_layout": "stacked",
                        "artwork_buttons": "natural", "content_pad": 12}}
    for module, cls in ((m4b_maker, "M4BMakerUI"), (editor, "M4BMetadataEditorUI"),
                        (mp3_tool, "MP3ToolUI")):
        panel = getattr(module, cls)(tk_root, theme=aqua, effective_config=make_config(),
                                     thread_factory=RecordingThreads(),
                                     choose_files=lambda: (), choose_folder=lambda: ())
        try:
            assert str(panel.btn_clear_imports.cget("style")) == ""
            assert str(panel.btn_clear_imports.cget("text")) == LABEL
        finally:
            panel.close()
            panel.destroy()


@pytest.mark.parametrize("tool", ["maker", "editor", "mp3"])
def test_the_button_is_reachable_at_the_windows_minimum(tool, make_maker, make_editor,
                                                        make_mp3, tk_root):
    panel = {"maker": make_maker, "editor": make_editor, "mp3": make_mp3}[tool]()
    tk_root.deiconify()
    try:
        panel.pack(fill="both", expand=True)
        tk_root.geometry("920x600")
        for _ in range(6):
            tk_root.update_idletasks()
            tk_root.update()
        height, width = tk_root.winfo_height(), tk_root.winfo_width()
        top, left = tk_root.winfo_rooty(), tk_root.winfo_rootx()
        for widget in (panel.btn_clear_imports, panel.btn_import_folder,
                       panel.navigator.frame, panel.log.frame):
            assert widget.winfo_ismapped(), widget
            assert widget.winfo_rooty() - top + widget.winfo_height() <= height + 1
            assert widget.winfo_rootx() - left + widget.winfo_width() <= width + 1
        assert not any(isinstance(w, tk.Canvas) for w in panel.winfo_children())
    finally:
        panel.pack_forget()
        tk_root.withdraw()
