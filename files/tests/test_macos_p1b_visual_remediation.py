"""v0.8.x P1B visual remediation: ACT72-078 (text and regions cut at the Aqua minimum), ACT72-079 (``Calculating…`` with
nothing being estimated), the sidebar heading's contrast and the content card's focus outline.

Found by the P1B closeout's real window pictures (``macos-visual``) and their eye review, at the Aqua minimum 1120 x 800:

* the TTS toolbar subtitle cut at the right edge; the TTS panel fell back to its "stacked" arrangement, where Sources showed
  two rows and Activity lay below the window;
* the MP3 Tool's and M4B Maker's Book counter cut to "(1 of" beside a long title; the Maker's run status cut mid-word;
* the M4B Metadata Editor's Source line cut (path and status lost); its Chapter Titles box one line tall;
* the output-folder hint losing the end of its last glyph (the label's own padding was counted as room for text);
* Cover's Details tree showing two of its five columns and a sliver, with no way to reach the rest;
* the content card's hairline drawn in its focus colour (black or white around the whole panel) whenever a field had focus;
* the sidebar's "TOOLS" heading at a contrast of 4.31 (WCAG AA for normal text is 4.5).

Each test builds the real launcher at a real size, as ``test_m4b_layout.py`` does, and reads live geometry. **Aqua only** for
the geometry: the remedies are aqua hints read with the Windows values as defaults, and Windows keeps its accepted layouts
(``test_ui_theme`` pins that the Windows bundle carries none of these hints). The idle-estimate check runs anywhere Tk does.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

import pytest

import tk_gate  # noqa: E402
from shared import paths  # noqa: E402,F401  (the log sandbox redirects only modules already imported)
from shared import appearance, job_control, ui_theme  # noqa: E402

MINIMUM = "1120x800"
LARGER = "1440x900"
APPEARANCES = ("light", "dark")
LONG_TITLE = "A Very Long Book Title That Should Wrap Or Truncate Gracefully — Volume One of the Collected Works"
LONG_NAME = "The Extraordinarily Long Chapter Title That Keeps Going — Café Ünïcode Édition (plain).m4b"
LONG_FOLDER = Path("/Users/someone/Desktop/Coding_Repositories/MyProjects/MacOS/Audiobook-Creation-Tool/files/dev-work/"
                   "verification-gate/outputs/2026-11-15_190628_qualification_d99c/qualification/w/s05/in")
TOOLS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


def _is_aqua(root) -> bool:
    return root.tk.call("tk", "windowingsystem") == "aqua"


@pytest.fixture
def fake_settings(monkeypatch):
    """In-memory settings for the launcher and the appearance store: nothing touches settings.json."""
    import launcher

    store: dict = {}

    class _Settings:
        @staticmethod
        def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        def set(key, value, **_kwargs):
            store[key] = value
            return True

    monkeypatch.setattr(launcher, "app_settings", _Settings)
    monkeypatch.setattr(appearance, "app_settings", _Settings)
    return store


def _settled(root, times: int = 8) -> None:
    for _ in range(times):
        root.update_idletasks()
        root.update()


@pytest.fixture
def shell(fake_settings, tk_root):
    """``shell(geometry, tool, look)``: the real launcher at *geometry*, *tool* selected, the app in *look*."""
    built = []
    existing = set(tk_root.winfo_children())

    def make(geometry: str, tool: str, look: str = "light"):
        import launcher

        fake_settings[appearance.SETTINGS_KEY] = look
        tk_root.deiconify()
        app = launcher.LauncherApp(tk_root)
        tk_root.geometry(geometry)
        _settled(tk_root)
        app.select_tool(tool)
        _settled(tk_root)
        built.append(app)
        return app, app.containers[tool].winfo_children()[0]

    yield make
    for child in list(tk_root.winfo_children()):
        if child not in existing:
            child.destroy()
    try:
        tk_root.protocol("WM_DELETE_WINDOW", "")
    except tk.TclError:  # pragma: no cover
        pass
    _settled(tk_root)
    tk_root.withdraw()


def _aqua_only(root) -> None:
    if not _is_aqua(root):
        pytest.skip("Aqua geometry regression: native macOS metrics only")


def _font_of(label):
    described = ttk.Style(label).lookup(str(label.cget("style")) or "TLabel", "font")
    return tkfont.Font(font=described or "TkDefaultFont")


def _fits(label) -> bool:
    """The label's shown text fits the room it really has for text (its width less its padding)."""
    font = _font_of(label)
    return font.measure(str(label.cget("text"))) <= ui_theme.text_room(label, font.measure)


def _inside(inner, outer) -> bool:
    a = (inner.winfo_rootx(), inner.winfo_rooty(), inner.winfo_rootx() + inner.winfo_width(),
         inner.winfo_rooty() + inner.winfo_height())
    b = (outer.winfo_rootx(), outer.winfo_rooty(), outer.winfo_rootx() + outer.winfo_width(),
         outer.winfo_rooty() + outer.winfo_height())
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def _lines(widget) -> float:
    font = tkfont.Font(root=widget, font=widget.cget("font"))
    return widget.winfo_height() / max(1, font.metrics("linespace"))


# --------------------------------------------------------------------------- #
# ACT72-079 — every idle panel estimates nothing (any windowing system)
# --------------------------------------------------------------------------- #
def test_no_idle_panel_says_calculating(shell):
    """Before any run, all six panels showed "Calculating…" beside an empty bar. Nothing is being estimated."""
    app, _panel = shell(MINIMUM, "tts")
    for tool in TOOLS:
        app.select_tool(tool)
        panel = app.containers[tool].winfo_children()[0]
        panel.jobs.render()
        assert panel.jobs.state is job_control.JobState.IDLE, tool
        assert panel.jobs.status.eta_text == "", tool


# --------------------------------------------------------------------------- #
# ACT72-078 — the TTS panel at the Aqua minimum and above
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("look", APPEARANCES)
@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
def test_tts_keeps_sources_and_activity_on_screen(shell, tk_root, geometry, look):
    _aqua_only(tk_root)
    app, panel = shell(geometry, "tts", look)
    assert panel._layout_mode[0] in ("split", "wide"), (
        f"at {geometry} Activity stays beside the workflow; 'stacked' put it below the window")
    assert _inside(panel.activity, panel), "Activity lies inside the panel"
    assert _lines(panel.log.summary_text) >= 3, "the log shows readable lines"
    listbox = panel.importer.list.listbox
    assert listbox.winfo_height() / (listbox.winfo_reqheight() / int(listbox.cget("height"))) >= 3 - 0.1, (
        "the Sources list shows at least three rows")
    desc = app._toolbar_desc
    assert desc.winfo_reqheight() <= desc.winfo_height() + 1 and desc.winfo_reqwidth() <= desc.winfo_width() + 1, (
        "the toolbar subtitle wraps inside the toolbar instead of being cut at the right edge")


# --------------------------------------------------------------------------- #
# ACT72-078 — the Book counter beside a long title (MP3 Tool, Maker, Editor)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("look", APPEARANCES)
@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
@pytest.mark.parametrize("tool", ["mp3_tool", "m4b_maker", "m4b_metadata"])
def test_the_book_counter_is_never_cut_beside_a_long_title(shell, tk_root, geometry, look, tool):
    _aqua_only(tk_root)
    _app, panel = shell(geometry, tool, look)
    nav = panel.navigator
    nav._label_for = lambda _book, position: f"Book {position} — {LONG_TITLE}"
    nav.render(panel.workspace)
    _settled(tk_root)
    assert nav.heading_text == f"Book 1 — {LONG_TITLE}  (1 of 1)", "the whole heading is kept"
    shown = nav.heading_shown
    assert shown.endswith("  (1 of 1)"), shown
    assert _fits(nav.label), shown
    if shown != nav.heading_text:
        assert ui_theme.ELLIPSIS in shown, "a shortened title says so"


# --------------------------------------------------------------------------- #
# ACT72-078 — the Metadata Editor's Source line and Chapter Titles
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("look", APPEARANCES)
@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
def test_the_metadata_source_line_fits_and_keeps_its_status(shell, tk_root, geometry, look):
    _aqua_only(tk_root)
    _app, panel = shell(geometry, "m4b_metadata", look)
    for status in ("readable", "the file's tags could not be read: the container's metadata box is truncated"):
        panel._set_source(LONG_FOLDER / LONG_NAME, status)
        _settled(tk_root)
        full = panel.source_text()
        assert full == f"Source: {LONG_NAME}  ({LONG_FOLDER})  — {status}", "the full value is kept"
        shown = panel.source_shown
        assert _fits(panel.source_label), shown
        assert shown.endswith(f"— {status}"), "what reading the file said is never cut"
        assert shown.startswith("Source: "), shown
        if shown != full:
            assert ui_theme.ELLIPSIS in shown
            assert panel._source_hover.text() == full, "the whole line is available on hover"
        else:
            assert panel._source_hover.text() == "", "nothing to add when the whole line is shown"


@pytest.mark.parametrize("look", APPEARANCES)
@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
def test_the_chapter_titles_box_keeps_three_rows(shell, tk_root, geometry, look):
    _aqua_only(tk_root)
    _app, panel = shell(geometry, "m4b_metadata", look)
    assert _lines(panel.chapter_text) >= 3 - 0.1, f"{panel.density}: {_lines(panel.chapter_text):.2f} rows"
    assert _lines(panel.log.summary_text) >= 1 - 0.1, "Activity keeps its floor"
    assert _inside(panel.activity, panel), "nothing is pushed below the panel"


# --------------------------------------------------------------------------- #
# Found by the eye review of the pictures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
@pytest.mark.parametrize("tool", ["mp3_tool", "m4b_maker", "m4b_metadata"])
def test_the_output_folder_hint_never_cuts_its_last_glyph(shell, tk_root, geometry, tool):
    _aqua_only(tk_root)
    _app, panel = shell(geometry, tool)
    panel.var_outdir.set(str(LONG_FOLDER.parent / "out" / "M4B-Maker-Outputs"))
    _settled(tk_root)
    assert panel.output_hint_text.endswith("M4B-Maker-Outputs")
    assert _fits(panel.output_label), panel.output_hint_text


@pytest.mark.parametrize("geometry", [MINIMUM, LARGER])
def test_the_makers_run_status_fits_one_line(shell, tk_root, geometry):
    _aqua_only(tk_root)
    _app, panel = shell(geometry, "m4b_maker")
    status = panel.jobs.status
    long_status = f"Book 1: {LONG_NAME} — building the M4B with 23 chapters and artwork"
    status.set_status(long_status)
    _settled(tk_root)
    assert status.status_text == long_status, "the whole line is kept (it is also the Summary's last line)"
    if panel.density == "tight":
        assert _fits(status.label_status), status.status_shown
        assert status.status_shown.endswith(ui_theme.ELLIPSIS) or status.status_shown == long_status


def test_coverss_details_columns_can_be_scrolled_into_view(shell, tk_root):
    _aqua_only(tk_root)
    _app, panel = shell(MINIMUM, "cover")
    details = panel.browser.details
    assert panel.browser.details_xbar is not None
    assert str(details.cget("xscrollcommand")), "the five columns scroll sideways"
    assert panel.browser.details_xbar.winfo_manager() == "grid"


@pytest.mark.parametrize("look", APPEARANCES)
def test_the_content_card_outline_never_takes_a_focus_colour(shell, tk_root, look):
    """With any field focused, Aqua drew the card's hairline in its focus colour around the whole panel."""
    _aqua_only(tk_root)
    app, panel = shell(MINIMUM, "mp3_tool", look)
    card = app._content_card
    assert str(card.cget("highlightcolor")) == str(card.cget("highlightbackground"))
    assert not int(card.cget("takefocus") or 0)


@pytest.mark.parametrize("look", APPEARANCES)
def test_the_sidebar_heading_meets_aa_contrast(shell, tk_root, look):
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "tts", look)
    sidebar = app.sidebar_rows["tts"][0].master
    heading = next(w for w in sidebar.winfo_children() if w.winfo_class() == "Label" and w.cget("text") == "TOOLS")

    def hexed(colour):
        return "#%02x%02x%02x" % tuple(value >> 8 for value in heading.winfo_rgb(colour))

    ratio = ui_theme.contrast_ratio(hexed(heading.cget("fg")), hexed(heading.cget("bg")))
    assert ratio >= ui_theme.MIN_TEXT_CONTRAST, f"TOOLS at {ratio:.2f}"
