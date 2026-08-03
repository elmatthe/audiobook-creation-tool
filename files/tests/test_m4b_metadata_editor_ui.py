"""v0.6.0 Drop 1 Phase 3 — the converted Windows M4B Metadata Editor.

The editor is the only tool panel this drop may convert, so these tests carry
two jobs at once:

1. **Nothing was traded for appearance.** Every control, callback, Tk variable
   and busy/idle transition the panel had before the layout was recomposed is
   still there, and the shared-value / "(varies)" detection still behaves
   identically when driven through a real widget tree.
2. **The conversion stayed inside its namespace.** On Windows every ttk widget
   in the panel names an ``ACT.*`` style, no generic style was touched, and the
   classic Tk widgets (Listbox / Text / Canvas) were coloured through the shared
   ``style_tk_widget`` helper rather than panel-local literals. On every other
   platform the historical layout is built and carries no namespaced style at
   all.

``files/tests/test_m4b_metadata_editor_shared.py`` still owns the display-free
shared-value semantics; this file never re-tests metadata rules, because the
drop adds none.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from mp3_tools import m4b_metadata_editor as editor  # noqa: E402
from shared import ui_theme  # noqa: E402

FIXTURE_PATH = Path(__file__).with_name("manual_windows_ui_prototype.py")

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the ACT design system only applies on win32",
)

#: Generic styles the five unconverted panels render with. Building the
#: converted editor must not disturb one of them.
GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TLabelframe", "TLabelframe.Label",
    "TCheckbutton", "Vertical.TScrollbar", "Horizontal.TProgressbar",
)

#: Public surface the launcher, the workers and the busy-state code rely on.
REQUIRED_WIDGETS = (
    "btn_add", "btn_add_folder", "btn_remove", "btn_clear", "btn_save",
    "btn_clear_tags", "btn_remove_numbering", "btn_cancel", "btn_cover",
    "btn_cover_clear", "btn_browse_out", "btn_open_out", "btn_chap_prev",
    "btn_chap_next", "chk_autonumber", "entry_cover", "entry_outdir",
    "listbox", "chap_text", "log", "progress", "lbl_mode",
    "lbl_series_readback", "lbl_autonumber_hint",
)

REQUIRED_CALLBACKS = (
    "add_files", "add_folder", "remove_selected", "clear_list", "choose_cover",
    "choose_outdir", "open_outdir", "output_dir", "save", "on_clear_all_tags",
    "on_remove_series_numbering", "cancel", "disable_inputs", "log_write",
    "_shared_tags", "_refresh_mode", "_chap_prev", "_chap_next",
    "_collect_tags", "_start_job", "_save_worker", "_remove_numbering_worker",
    "_pump_queue", "_finish_idle",
)


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless box with no display
        pytest.skip(f"Tk cannot open a display here: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def host(tk_root):
    """A throwaway container, so each editor build starts from nothing."""
    frame = ttk.Frame(tk_root)
    yield frame
    frame.destroy()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _style_of(widget) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:  # a classic tk widget has no -style option
        return ""


def _snapshot_generic(style: ttk.Style) -> dict:
    out = {}
    for name in GENERIC_STYLES:
        try:
            layout = style.layout(name)
        except tk.TclError:
            layout = None
        out[name] = (layout, style.configure(name),
                     style.lookup(name, "background"),
                     style.lookup(name, "foreground"),
                     style.map(name))
    return out


# ---------------------------------------------------------------------------
# Preserved contract — every platform
# ---------------------------------------------------------------------------

def test_editor_builds_and_keeps_its_public_contract(host):
    """build_ui(parent) still returns a fully wired panel on this platform."""
    ui = editor.build_ui(host)

    assert isinstance(ui, editor.M4BMetadataEditorUI)
    assert ui.winfo_manager() == "pack"

    for name in REQUIRED_WIDGETS:
        assert getattr(ui, name, None) is not None, f"missing widget {name}"
    for name in REQUIRED_CALLBACKS:
        assert callable(getattr(ui, name, None)), f"missing callback {name}"

    # One Tk variable per editable field, and the entries line up with them.
    for _key, attr, _label in editor._FIELDS:
        assert isinstance(getattr(ui, attr), tk.StringVar), attr
    assert len(ui._field_widgets) == len(editor._FIELDS)
    for widget, (_key, attr, _label) in zip(ui._field_widgets, editor._FIELDS):
        assert str(widget.cget("textvariable")) == str(getattr(ui, attr))

    # Idle starting state.
    assert ui.files == []
    assert ui._busy.is_set() is False
    assert str(ui.btn_cancel.cget("state")) == "disabled"
    assert ui.mode_var.get() == "No files loaded."
    assert ui.chap_pager_var.get() == "No files loaded."
    assert ui.var_outdir.get()  # a fresh Downloads/<slug>-N was decided
    assert "not written" in ui.autonumber_hint_var.get()

    # The pager arrows start disabled, as they did before the recomposition.
    assert str(ui.btn_chap_prev.cget("state")) == "disabled"
    assert str(ui.btn_chap_next.cget("state")) == "disabled"


def test_busy_state_disables_every_input_and_returns_to_idle(host):
    """The busy/idle transition still reaches all of the same widgets."""
    ui = editor.build_ui(host)
    guarded = [ui.btn_add, ui.btn_add_folder, ui.btn_remove, ui.btn_clear,
               ui.btn_save, ui.btn_clear_tags, ui.btn_remove_numbering,
               ui.btn_cover, ui.btn_cover_clear, ui.entry_cover,
               ui.entry_outdir, ui.btn_browse_out, ui.chap_text,
               ui.chk_autonumber, *ui._field_widgets]

    ui.disable_inputs(True)
    for widget in guarded:
        assert str(widget.cget("state")) == "disabled", str(widget)

    ui._finish_idle()
    for widget in guarded:
        assert str(widget.cget("state")) != "disabled", str(widget)
    assert str(ui.btn_cancel.cget("state")) == "disabled"
    assert ui._busy.is_set() is False


def test_shared_value_detection_survives_the_layout_refactor(host):
    """Driven through the real widgets, the batch prefill is unchanged.

    The display-free semantics live in test_m4b_metadata_editor_shared.py; this
    only proves the recomposed form is still wired to them.
    """
    ui = editor.build_ui(host)
    a, b = Path("a.m4b"), Path("b.m4b")
    ui.files = [a, b]
    ui._tag_cache = {
        a: {"artist": "Shared Author", "album": "Shared Album", "title": "One"},
        b: {"artist": "Shared Author", "album": "Shared Album", "title": "Two"},
    }
    ui._chap_counts = {a: 0, b: 0}
    ui._refresh_mode()

    assert ui.var_artist.get() == "Shared Author"
    assert ui.var_album.get() == "Shared Album"
    assert ui.var_title.get() == ""          # varies -> left blank
    assert "Batch mode: 2 files" in ui.mode_var.get()
    assert "Author / Artist" in ui.mode_var.get()
    assert ui.series_readback_var.get() == "Detected across files: no shared series name"
    # Blank fields are still not collected, and series_part is still owned by
    # the auto-number toggle rather than the form.
    assert ui._collect_tags() == {"artist": "Shared Author", "album": "Shared Album"}


def test_non_windows_theme_builds_the_unconverted_layout(tk_root, monkeypatch):
    """macOS/Linux keep the historical panel: no namespaced style anywhere."""
    style = ttk.Style(tk_root)
    restore = style.theme_use()
    monkeypatch.setattr(sys, "platform", "linux")
    classic = ui_theme.apply_theme(tk_root, style)
    assert classic["mode"] == "classic" and classic["colors"] is None

    frame = ttk.Frame(tk_root)
    try:
        ui = editor.build_ui(frame, theme=classic)
        assert ui._windows is False
        namespaced = [str(w) for w in _walk(ui) if _style_of(w).startswith("ACT.")]
        assert namespaced == [], namespaced
        # …and it is still a complete panel.
        for name in REQUIRED_WIDGETS:
            assert getattr(ui, name, None) is not None, name
    finally:
        frame.destroy()
        try:
            style.theme_use(restore)
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# The converted Windows presentation
# ---------------------------------------------------------------------------

@windows_only
def test_windows_editor_uses_only_namespaced_styles(host):
    ui = editor.build_ui(host)
    s = ui.theme["styles"]
    assert ui._windows is True
    assert str(ui.cget("style")) == s["window"]

    used = {_style_of(w) for w in _walk(ui)} - {""}
    assert used, "the converted editor applied no styles at all"
    assert all(name.startswith("ACT.") for name in used), sorted(used)

    # No ttk widget was left behind on a generic style.
    stragglers = [str(w) for w in _walk(ui)
                  if isinstance(w, ttk.Widget) and not _style_of(w)]
    assert stragglers == [], stragglers

    # The action hierarchy is expressed, not just recoloured.
    assert str(ui.btn_save.cget("style")) == s["primary_button"]
    assert str(ui.btn_clear_tags.cget("style")) == s["danger_button"]
    assert str(ui.btn_remove_numbering.cget("style")) == s["danger_button"]
    assert str(ui.btn_cancel.cget("style")) == s["button"]

    # ProgressIndicator is restyled per instance; the shared class stays
    # generic because five unconverted panels build their own from it.
    assert str(ui.progress.bar.cget("style")) == s["progressbar"]
    fresh = ui_theme.ProgressIndicator(host)
    assert str(fresh.bar.cget("style")) == ""
    fresh.frame.destroy()


@windows_only
def test_windows_editor_leaves_the_generic_styles_alone(tk_root, host):
    """Building the converted panel must not change what the other five use."""
    style = ttk.Style(tk_root)
    ui_theme.apply_theme(tk_root, style)
    before = _snapshot_generic(style)
    editor.build_ui(host)
    tk_root.update_idletasks()
    after = _snapshot_generic(style)

    changed = [n for n in GENERIC_STYLES if before[n] != after[n]]
    assert not changed, f"the converted editor leaked into generic styles: {changed}"


@windows_only
def test_windows_editor_themes_its_classic_tk_widgets(host):
    """Listbox / Text / Canvas go through style_tk_widget, not local literals."""
    ui = editor.build_ui(host)
    c = ui.theme["colors"]

    assert ui.listbox.cget("background") == c["field"]
    assert ui.listbox.cget("selectbackground") == c["selection"]
    assert ui.chap_text.cget("background") == c["field"]
    assert ui.log.cget("background") == c["elevated"]

    canvases = [w for w in _walk(ui) if isinstance(w, tk.Canvas)]
    assert len(canvases) == 1, "the scroll region should still be one canvas"
    assert canvases[0].cget("background") == c["window"]

    # The scroll region and its scoped wheel binding are unchanged.
    wrap = canvases[0].master
    assert "<Enter>" in wrap.bind() and "<Leave>" in wrap.bind()
    assert "%d" in wrap.bind("<Leave>")


@windows_only
def test_windows_shared_metadata_surface_is_distinct_and_complete(host):
    """Every batch-wide field lives inside the Shared Metadata surface."""
    ui = editor.build_ui(host)
    s = ui.theme["styles"]

    shared = [w for w in _walk(ui)
              if isinstance(w, ttk.Labelframe)
              and str(w.cget("style")) == s["shared_labelframe"]]
    assert len(shared) == 1, "there must be exactly one Shared Metadata surface"
    card = shared[0]
    assert str(card.cget("text")) == "Shared Metadata"

    inside = {str(w) for w in _walk(card)}
    for widget, (_key, _attr, label) in zip(ui._field_widgets, editor._FIELDS):
        assert str(widget) in inside, f"{label} is outside Shared Metadata"
    for widget in (ui.entry_cover, ui.chk_autonumber, ui.lbl_mode,
                   ui.lbl_series_readback, ui.lbl_autonumber_hint):
        assert str(widget) in inside, str(widget)

    # The surface is visually distinct from an ordinary card, and its toggle
    # sits on the shared background rather than the card background.
    assert str(ui.chk_autonumber.cget("style")) == s["shared_checkbutton"]
    style = ttk.Style(ui)
    assert style.lookup(s["shared_labelframe"], "background") \
        != style.lookup(s["labelframe"], "background")

    # Presentation only: no field is disabled or overridden by the grouping.
    for widget in ui._field_widgets:
        assert "disabled" not in widget.state()


@windows_only
def test_windows_primary_actions_and_log_are_outside_the_scroll_region(host):
    """Save/Cancel/progress/log must never scroll away (plan §7.3)."""
    ui = editor.build_ui(host)
    canvas = next(w for w in _walk(ui) if isinstance(w, tk.Canvas))
    scrolled = {str(w) for w in _walk(canvas)}

    for widget in (ui.btn_save, ui.btn_clear_tags, ui.btn_remove_numbering,
                   ui.btn_cancel, ui.progress.bar, ui.progress.label, ui.log):
        assert str(widget) not in scrolled, f"{widget} can scroll out of view"

    # The long form, the file list and the chapter pages do scroll.
    for widget in (ui.listbox, ui.chap_text, ui.entry_outdir,
                   *ui._field_widgets):
        assert str(widget) in scrolled, f"{widget} is not in the scroll region"


# ---------------------------------------------------------------------------
# The developer-only visual fixture
# ---------------------------------------------------------------------------

def test_manual_fixture_is_developer_only_and_unreachable_at_runtime():
    import launcher

    assert FIXTURE_PATH.exists()
    source = FIXTURE_PATH.read_text(encoding="utf-8")

    # pytest cannot collect it: wrong filename, and it declares nothing to run.
    assert not FIXTURE_PATH.name.startswith("test_")
    assert "def " + "test_" not in source

    # The product cannot reach it: not a registered tool, and not in the
    # shipped scripts/ tree.
    assert all("manual_windows_ui_prototype" not in spec.module
               for spec in launcher.TOOLS)
    scripts_root = FIXTURE_PATH.parents[2] / "scripts"
    assert not list(scripts_root.rglob("manual_windows_ui_prototype.py"))

    # It renders the real thing rather than a mock of it.
    assert "from shared import ui_theme" in source
    assert "from mp3_tools import m4b_metadata_editor" in source


def test_manual_fixture_states_are_deterministic_and_offline(host):
    """Its canned states drive the real editor without touching any file."""
    import manual_windows_ui_prototype as fixture

    # The specimen labels itself as presentation-only, in the strongest terms
    # the plan requires: none of the Plan 3 behaviour is implied.
    note = fixture.SPECIMEN_NOTE
    assert "VISUAL SPECIMEN" in note
    for absent in ("filtering", "ETA", "Retry Failed", "Pause/Resume"):
        assert absent in note

    ui = editor.build_ui(host)
    fixture._populate(ui)
    assert len(ui.files) == 3
    assert ui.listbox.size() == 3
    assert ui.var_artist.get() == "A. Sample Author"   # shared across the batch
    assert ui.var_title.get() == ""                    # varies across the batch
    assert "File 1 of 3" in ui.chap_pager_var.get()
    assert not any(p.exists() for p in ui.files), "the fixture must stay offline"

    fixture._make_busy(ui)
    assert ui._busy.is_set()
    assert str(ui.btn_save.cget("state")) == "disabled"
    assert str(ui.btn_cancel.cget("state")) == "normal"
    assert ui.progress.label.cget("text") == "2/3  67%"
    ui._busy.clear()


@windows_only
def test_manual_fixture_specimen_builds_from_production_primitives(tk_root):
    """The Summary/Details sheet uses ACT styles and adds no product control."""
    import manual_windows_ui_prototype as fixture

    top = tk.Toplevel(tk_root)
    top.withdraw()
    try:
        theme = ui_theme.apply_theme(top, ttk.Style(top))
        fixture._build_specimen(top, theme)
        top.update_idletasks()

        used = {_style_of(w) for w in _walk(top)} - {""}
        assert used and all(n.startswith("ACT.") for n in used), sorted(used)
        assert theme["styles"]["notebook"] in used
        notebooks = [w for w in _walk(top) if isinstance(w, ttk.Notebook)]
        assert len(notebooks) == 1
        assert [notebooks[0].tab(i, "text") for i in range(notebooks[0].index("end"))] \
            == ["Summary", "Details"]

        # It is a sheet, not a feature: nothing in it has a command bound.
        commanded = [str(w) for w in _walk(top)
                     if isinstance(w, ttk.Button) and str(w.cget("command"))]
        assert commanded == [], commanded
    finally:
        top.destroy()
