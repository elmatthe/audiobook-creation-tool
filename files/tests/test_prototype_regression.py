"""v0.6.0 Drop 1 Phase 4 — regression hardening for the Windows prototype,
re-pointed at v0.6.4 Phase 10.

Phases 1-3 of that drop proved the theme contract, the launcher lifecycle, the
editor's public surface and the style isolation. This file added what those
did not cover, favouring *behaviour* contracts over appearance:

- the copy-only output contract and the read-only-original safeguard;
- the cooperative-cancellation contract, including what happens to the file
  that was already in flight;
- one build serving every theme bundle with the same surface;
- the generic ttk styles surviving a *whole launcher build*;
- what the shipped panel does and does not contain, and no new persisted
  settings.

v0.6.4 Phase 10 replaced the panel's private workers with the shared job
architecture over the Phase 9 engine, so every behavioural contract above is
now proved **through the production panel end to end** on real tiny
containers rather than through a worker stub — the originals are still never
written, cancellation still travels through the shared primitive (raised by
the controller's checkpoint, never by the panel), and the one build fork
serves Windows, classic and aqua bundles alike. The "negative half" of the
old scope inverted by design: the Summary / Detailed log, Retry Failed,
Pause / Resume and the per-Book workspace are the product now, and this file
proves they arrived whole and that nothing meaningless (Add Book, Duplicate
Book, a dead button) came with them.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from mp3_tools import m4b_metadata_batch as batch
from mp3_tools import m4b_metadata_editor as editor
from shared import paths
from shared.book_workspace import BookDisposition
from shared.job_control import JobEventKind, JobState

from test_m4b_metadata_editor_ui import (  # noqa: F401 - fixtures by import
    audio_md5, container, import_folder, library, make_panel, output_base, parked_threads,
    run_action, sha, tk_root, windows_theme, add_files,
)
from test_m4b_metadata_workflow import m4b

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the ACT design system only applies on win32"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"


def _digest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Copy-only output and the read-only-original safeguard, through the panel
# ---------------------------------------------------------------------------


def test_save_writes_only_copies_and_never_the_originals(make_panel, container, tmp_path,
                                                          output_base):
    root = library(container, tmp_path / "Library")
    before = _digest(root)
    panel = make_panel()
    import_folder(panel, root)
    panel.surface.set_shared_text("artist", "X")
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert panel.last_result.state is JobState.SUCCEEDED
    # Every original is byte-identical, and every write landed on a copy in the run.
    assert _digest(root) == before
    outputs = sorted(p.name for p in plan.run_directory.iterdir() if p.is_file())
    assert outputs == ["Alpha.m4b", "Beta.m4b", "Gamma.m4a"]
    assert plan.run_directory.parent.parent == output_base
    for entry in plan.books:
        assert entry.published.parent == plan.run_directory
        assert entry.published != entry.source
        assert audio_md5(entry.published) == audio_md5(entry.source), "a copy, not a re-encode"
    assert not (plan.run_directory / editor.mp.WORK_DIRNAME).exists()


def test_outputs_never_collide_with_each_other_or_with_an_input(make_panel, container,
                                                                 tmp_path, output_base):
    """Two same-named sources from different folders stay two whole outputs."""
    one = m4b(container, tmp_path / "one" / "Book.m4b", title="One")
    two = m4b(container, tmp_path / "two" / "Book.m4b", title="Two")
    before = (sha(one), sha(two))
    panel = make_panel()
    add_files(panel, one, two)
    panel.surface.set_shared_text("album", "Y")
    assert run_action(panel, "save") is True
    plan = panel.last_plan
    assert [entry.filename for entry in plan.books] == ["Book.m4b", "Book-1.m4b"]
    assert all(entry.published != entry.source for entry in plan.books)
    assert (sha(one), sha(two)) == before, "an original was overwritten"
    assert panel.last_result.state is JobState.SUCCEEDED


def test_remove_numbering_is_copy_only_too(make_panel, container, tmp_path, output_base):
    root = library(container, tmp_path / "Library")
    before = _digest(root)
    panel = make_panel()
    import_folder(panel, root)
    assert run_action(panel, "on_remove_series_numbering") is True
    assert panel.last_result.state is JobState.SUCCEEDED
    assert _digest(root) == before
    plan = panel.last_plan
    assert sorted(p.name for p in plan.run_directory.iterdir()) == [
        "Alpha.m4b", "Beta.m4b", "Gamma.m4a"]


# ---------------------------------------------------------------------------
# Cooperative cancellation, through the shared controller
# ---------------------------------------------------------------------------


def test_cancel_before_the_first_book_writes_nothing(make_panel, container, tmp_path,
                                                      output_base):
    root = library(container, tmp_path / "Library")
    before = _digest(root)
    panel = make_panel()
    import_folder(panel, root)
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    panel.cancel()                              # before the worker body runs
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert [d for _i, d in result.dispositions] == [BookDisposition.NOT_ATTEMPTED] * 3
    assert _digest(root) == before
    assert list(panel.last_plan.run_directory.iterdir()) == []


def test_cancel_mid_run_finishes_the_current_book_and_stops_the_rest(make_panel, container,
                                                                      tmp_path, output_base):
    """The documented semantics: the in-flight Book completes, later Books stop."""
    root = library(container, tmp_path / "Library")
    before = _digest(root)
    panel = make_panel()
    import_folder(panel, root)
    panel._thread_factory = parked_threads()
    assert panel.save() is True
    published: list[str] = []

    def on_event(event):
        # The run folder's own OUTPUT_LOCATION was published before this
        # listener existed; from here one arrives per finished Book, and the
        # user presses Cancel as Book 2 is the one just done.
        if event.kind is JobEventKind.OUTPUT_LOCATION:
            published.append(event.message)
            if len(published) == 2:
                panel.cancel()

    panel.run.add_listener(on_event)
    panel._thread_factory.bodies[0]()
    panel._pump.tick()
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert [d for _i, d in result.dispositions] == [
        BookDisposition.SUCCEEDED, BookDisposition.SUCCEEDED, BookDisposition.NOT_ATTEMPTED]
    assert _digest(root) == before
    plan = panel.last_plan
    outputs = sorted(p.name for p in plan.run_directory.iterdir() if p.is_file())
    assert outputs == ["Alpha.m4b", "Beta.m4b"], "only finished Books reached the run"
    for entry in plan.books[:2]:
        assert audio_md5(entry.published) == audio_md5(entry.source), "each is whole"
    assert not plan.books[2].staging_dir.exists()


def test_cancellation_uses_the_shared_primitive_raised_by_the_controller_not_the_panel():
    """The panel forwards the request; the runner and the engine honour the primitive."""
    panel = (UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py").read_text(encoding="utf-8")
    tree = ast.parse(panel)
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    assert "shared.cancellation" not in modules
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for private in ("_cancel_event", "Event", "ConversionCancelled", "raise_if_cancelled"):
        assert private not in names, private
    # The panel's Cancel forwards to the run, which asks its controller; the
    # only ``request_cancel`` the panel makes itself is the import scan's.
    cancel = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "cancel")
    assert {ast.unparse(node.func) for node in ast.walk(cancel)
            if isinstance(node, ast.Call)} == {"self.run.cancel"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)                 and node.func.attr == "request_cancel":
            assert ast.unparse(node.func.value) == "self._coordinator"
    runner = (UNIVERSAL / "mp3_tools" / "m4b_metadata_batch.py").read_text(encoding="utf-8")
    assert "from shared.cancellation import ConversionCancelled" in runner
    assert callable(getattr(batch.EditorRun, "cancel"))


# ---------------------------------------------------------------------------
# One build, every bundle, the same surface
# ---------------------------------------------------------------------------

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import ui_theme  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_import_coordination import RecordingThreads  # noqa: E402


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _style_of(widget) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:
        return ""


#: The controls the shared lock matrix reaches. Every bundle must supply all of
#: them, or a run would silently leave a control live on one platform.
GUARDED = (
    "btn_import_folder", "btn_add_files", "btn_save", "btn_clear_tags",
    "btn_remove_numbering", "check_auto_number", "entry_start_part", "chapter_text",
    "navigator", "surface", "shared_artwork", "book_artwork", "jobs", "log",
)


def _classic_bundle(base: dict) -> dict:
    """A non-Windows bundle, without lying to sys.platform for a whole build."""
    out = dict(base)
    out["mode"] = "classic"
    out["colors"] = None
    out["metrics"] = None
    out["styles"] = None        # only the Windows branch publishes ACT styles
    return out


def _panel(parent, theme):
    return editor.M4BMetadataEditorUI(
        parent, theme=theme, effective_config=make_config(),
        thread_factory=RecordingThreads(), choose_files=lambda: (), choose_folder=lambda: ())


@windows_only
def test_one_build_serves_the_windows_and_classic_bundles_with_the_same_surface(fresh_root):
    style = ttk.Style(fresh_root)
    win_theme = ui_theme.apply_theme(fresh_root, style)
    win = _panel(ttk.Frame(fresh_root), win_theme)
    classic = _panel(ttk.Frame(fresh_root), _classic_bundle(win_theme))
    fresh_root.update_idletasks()
    try:
        for name in GUARDED:
            a, b = getattr(win, name, None), getattr(classic, name, None)
            assert a is not None and b is not None, name
            assert type(a) is type(b), f"{name}: {type(a)} vs {type(b)}"
        assert str(win.btn_save.cget("style")).startswith("ACT.")
        assert [str(w) for w in _walk(classic) if _style_of(w).startswith("ACT.")] == []
        # The run lock reaches the same controls on both, through the shared group.
        for ui in (win, classic):
            ui.lock_group.apply(JobState.RUNNING)
            assert all("disabled" in getattr(ui, n).state()
                       for n in ("btn_save", "btn_clear_tags", "btn_remove_numbering",
                                 "btn_import_folder", "btn_add_files"))
            ui.lock_group.apply(JobState.IDLE)
            assert all("disabled" not in getattr(ui, n).state()
                       for n in ("btn_save", "btn_import_folder"))
    finally:
        win.close()
        classic.close()


def test_an_aqua_bundle_builds_the_same_panel_natively(fresh_root):
    """macOS takes no separate fork — the check is on mode, not platform."""
    style = ttk.Style(fresh_root)
    base = ui_theme.apply_theme(fresh_root, style)
    aqua = dict(base)
    aqua["mode"] = "aqua"
    aqua["styles"] = None       # only the Windows branch publishes ACT styles
    ui = _panel(ttk.Frame(fresh_root), aqua)
    try:
        assert [str(w) for w in _walk(ui) if _style_of(w).startswith("ACT.")] == []
        assert str(ui.cget("style")) == ""
        for name in GUARDED:
            assert getattr(ui, name, None) is not None, name
    finally:
        ui.close()


# ---------------------------------------------------------------------------
# Isolation across a whole launcher build
# ---------------------------------------------------------------------------


def _canonical(value):
    """A ttk style value, compared by what it *is* rather than how Tcl spelt it.

    ``style.configure("TNotebook")`` answers ``{'tabmargins': '2 2 2 0'}`` while
    no notebook has ever existed in the interpreter and
    ``{'tabmargins': [2, 2, 2, 0]}`` once one has — the identical padding,
    returned as a Tcl string one moment and a converted list the next. Comparing
    the raw values therefore reports a "leak" the first time any panel uses a
    widget class the snapshot named, which is a property of Tcl's lazy option
    conversion and not of anything a panel did.

    Collapsing both spellings to one keeps the guard measuring what it claims to
    measure: a real change of colour, layout or state map still differs here.
    """
    if isinstance(value, dict):
        return tuple(sorted((str(key), _canonical(item))
                            for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        parts = tuple(_canonical(item) for item in value)
        if all(isinstance(part, str) for part in parts):
            return " ".join(parts)
        return parts
    return str(value)


@windows_only
def test_building_the_whole_app_leaves_the_generic_styles_untouched(
    fresh_root, monkeypatch
):
    """The strongest form of the isolation claim: theme + shell + all six panels.

    Phase 1 snapshotted across theme application and Phase 3 across one panel.
    This snapshots across the entire application coming up, which is what a
    user actually does.
    """
    import launcher

    generic = ("TFrame", "TLabel", "TButton", "TEntry", "TCombobox",
               "TCheckbutton", "TRadiobutton", "TLabelframe",
               "TLabelframe.Label", "TNotebook", "TNotebook.Tab", "Treeview",
               "Treeview.Heading", "Horizontal.TProgressbar",
               "Vertical.TScrollbar", "TSeparator")

    style = ttk.Style(fresh_root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    def snapshot():
        return {n: _canonical((style.layout(n), style.configure(n),
                               style.lookup(n, "background"),
                               style.lookup(n, "foreground"),
                               style.lookup(n, "fieldbackground"),
                               style.map(n))) for n in generic}

    before = snapshot()

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kw):
            store[key] = value

    monkeypatch.setattr(launcher, "app_settings", _Settings)

    app = launcher.LauncherApp(fresh_root)
    for spec in app._available_tools():
        app.select_tool(spec.key)
    fresh_root.update_idletasks()

    after = snapshot()
    changed = [n for n in generic if before[n] != after[n]]
    assert not changed, f"building the app leaked into generic styles: {changed}"
    assert style.theme_use() == "vista"

    # Only the converted panels opted in: the editor (Plan 1, redone at v0.6.4
    # Phase 10), the MP3 Tool (focused MP3 plan Phase 4) and, since v0.6.4
    # Phase 6, the M4B Maker. The other three still use none.
    per_panel = {
        key: sorted({_style_of(w) for w in _walk(cont)
                     if _style_of(w).startswith("ACT.")})
        for key, cont in app.containers.items()
    }
    for converted in ("m4b_metadata", "mp3_tool", "m4b_maker"):
        assert per_panel.pop(converted), f"the converted {converted} uses no ACT style"
    assert all(v == [] for v in per_panel.values()), per_panel


# ---------------------------------------------------------------------------
# What the shipped panel contains — the inverted half of the old scope
# ---------------------------------------------------------------------------

#: Words the shared job and workspace controls carry; all of them must be
#: reachable in the shipped panel now. Matched on word boundaries.
REQUIRED_TEXT = ("summary", "detailed", "retry failed", "pause", "resume", "cancel",
                 "remove book", "previous", "next", "save tags", "clear all tags",
                 "remove series numbering", "import folder", "add files")

#: Words that would betray a meaningless control for a one-file-per-Book tool.
FORBIDDEN_TEXT = ("add book", "duplicate book", "custom destination")


@windows_only
def test_the_runtime_editor_carries_the_shared_controls_and_no_dead_or_meaningless_button(
        fresh_root):
    style = ttk.Style(fresh_root)
    theme = ui_theme.apply_theme(fresh_root, style)
    ui = _panel(ttk.Frame(fresh_root), theme)
    fresh_root.update_idletasks()
    try:
        notebooks = [w for w in _walk(ui) if isinstance(w, ttk.Notebook)]
        assert len(notebooks) == 1, "exactly one Summary / Detailed region"
        texts = []
        for widget in _walk(ui):
            try:
                texts.append(str(widget.cget("text")).lower())
            except tk.TclError:
                continue
        for i in range(notebooks[0].index("end")):
            texts.append(str(notebooks[0].tab(i, "text")).lower())
        joined = "\n".join(texts)
        for word in REQUIRED_TEXT:
            assert re.search(rf"\b{re.escape(word)}\b", joined), word
        for word in FORBIDDEN_TEXT:
            assert not re.search(rf"\b{re.escape(word)}\b", joined), word
        # Exactly the three text areas: chapter titles and the two log panes.
        assert set(w for w in _walk(ui) if isinstance(w, tk.Text)) == {
            ui.chapter_text, ui.log.summary_text, ui.log.details_text}
        assert [w for w in _walk(ui) if isinstance(w, tk.Canvas)] == []
        # Every control is wired to something real — no placeholder actions.
        dead = [str(b.cget("text")) for b in _walk(ui)
                if isinstance(b, ttk.Button) and not str(b.cget("command"))]
        assert dead == [], dead
    finally:
        ui.close()


def test_shared_metadata_now_overrides_and_disables_the_book_control(make_panel, container,
                                                                     tmp_path):
    """The inversion the plan asked for: a populated Shared value is an override."""
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    panel.surface.set_shared_text("artist", "Shared")
    assert panel.book_field_enabled("artist") is False
    assert panel.book_value("artist") == "Shared"
    assert panel.book_field_enabled("title") is True, "only the matching control"
    panel.surface.set_shared_text("artist", "")
    assert panel.book_field_enabled("artist") is True
    assert panel.book_value("artist") == "Ann"


def test_no_new_persisted_settings_arrived_with_the_new_presentation():
    """The panel still writes only its two historical dialog-location keys."""
    source = Path(editor.__file__).read_text(encoding="utf-8")
    assert editor.KEY_INPUT_DIR == "m4b_metadata.input_dir"
    assert editor.KEY_COVER_DIR == "m4b_metadata.cover_dir"

    written = {line.split("settings.set(")[1].split(",")[0].strip()
               for line in source.splitlines() if "settings.set(" in line}
    assert written == {"KEY_INPUT_DIR", "KEY_COVER_DIR"}, written
    # The output folder is still deliberately not persisted.
    assert "settings.set(\"m4b_metadata.output" not in source
    assert paths.TOOL_SLUGS["m4b_metadata"] == "M4B-Metadata"
