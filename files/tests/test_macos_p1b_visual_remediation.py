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
* the sidebar's "TOOLS" heading at a contrast of 4.31 (WCAG AA for normal text is 4.5);
* ACT72-081 (found by the final eye review, in every Light-look window picture): the footer's two native buttons each sat in
  a light-grey box on the dark footer. Those tests read the real picture of the launcher window (the window server's image of
  this process's own window, as the gate takes it) and compare the colour Aqua fills each button's rectangle with to the
  footer's own colour beside it.

Each test builds the real launcher at a real size, as ``test_m4b_layout.py`` does, and reads live geometry. **Aqua only** for
the geometry: the remedies are aqua hints read with the Windows values as defaults, and Windows keeps its accepted layouts
(``test_ui_theme`` pins that the Windows bundle carries none of these hints). The idle-estimate check runs anywhere Tk does.
"""

from __future__ import annotations

import importlib.util
import time
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


# --------------------------------------------------------------------------- #
# ACT72-081 — the footer's native buttons sit on the footer's own colour
# --------------------------------------------------------------------------- #
#: Aqua fills a native button's rectangle in exactly the window colour of the window's appearance (0 measured); the slack
#: only allows for colour management. ACT72-081 measured 186 (a 236 grey box on a 50 grey footer).
BOX_TOLERANCE = 6
_GATE_MODULES: dict = {}


def _gate_module(name: str, relative: str):
    """A gate module the darwin picture pipeline uses, loaded from its file (the gate is not on the application's path)."""
    if name not in _GATE_MODULES:
        from gate_locator import GATE_DIR

        spec = importlib.util.spec_from_file_location(f"act_gate_{name}", GATE_DIR / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _GATE_MODULES[name] = module
    return _GATE_MODULES[name]


def _native_ui():
    """The gate's imaging of this process's own window (``CGWindowListCreateImage``; an own window needs no privacy grant)."""
    return _gate_module("native_ui", "adapters/macos/native_ui.py")


def _footer(app) -> dict:
    """The darwin footer as the shell built it, found from the two native buttons it holds."""
    inner = app.appearance_button.master
    outer = inner.master
    labels = [widget for widget in inner.winfo_children() if widget.winfo_class() == "Label"]
    return {"outer": outer, "inner": inner,
            "separator": next(widget for widget in outer.winfo_children() if widget is not inner),
            "status": next(widget for widget in labels if str(widget.cget("textvariable")) == str(app.status_var)),
            "link": next(widget for widget in labels if widget.cget("text") == "Open log folder")}


def _resolved(widget, option: str) -> str:
    return "#%02x%02x%02x" % tuple(value >> 8 for value in widget.winfo_rgb(str(widget.cget(option))))


def _run_event_loop(root, seconds: float) -> None:
    """Let Tk's real event loop run for a while, as the application's does (``time.sleep`` would stop AppKit drawing)."""
    done = tk.IntVar(root, value=0)
    root.after(int(seconds * 1000), done.set, 1)
    root.wait_variable(done)


def _picture(root, path: Path):
    """The window server's picture of the launcher window, as the gate takes it; a reader of points in Tk's coordinates.

    The window server's image can be out of register with the window for an instant (the gate measured it; here, just
    after the shared root is resized for a test). As the gate does, such a take is kept beside the picture, retaken a
    bounded number of times, and never read: a picture still out of register fails."""
    from PIL import Image

    native_ui = _native_ui()
    review = _gate_module("visual_review", "helpers/visual_review.py")
    for attempt in range(25):
        _settled(root, 2)
        _run_event_loop(root, 0.25 if attempt == 0 else review.RETAKE_PAUSE)
        window = native_ui.window_for(str(root.wm_title()), (root.winfo_width(), root.winfo_height()))
        assert window is not None, "the launcher window is on screen"
        shot = native_ui.capture(window["number"], path)
        assert shot["captured"], shot
        with Image.open(path) as opened:
            bands = review.edge_bands(opened.getchannel("A")) if "A" in opened.getbands() else {}
            image = opened.convert("RGB")
        expected = tuple(round(value * float(window["scale"])) for value in window["frame"][2:])
        # A take of the wrong size is the window imaged mid-animation (seen while the desktop was in use), not the window.
        if max(bands.values(), default=0) < review.REGISTER_BAND_PX and image.size == expected:
            break
        path.replace(path.with_name(f"{path.stem}.out-of-register-{attempt + 1}.png"))
    else:
        pytest.fail(f"{path.name}: the window server's image stayed out of register with the window: {bands}, "
                    f"{image.size} against {expected}")
    scale = float(window["scale"])
    title_bar = image.height - round(root.winfo_height() * scale)

    def at(widget, dx: float, dy: float) -> tuple:
        x = widget.winfo_rootx() - root.winfo_rootx() + dx
        y = widget.winfo_rooty() - root.winfo_rooty() + dy
        return tuple(image.getpixel((round(x * scale), title_bar + round(y * scale))))

    return at, window, shot


def _boxes(app, root, path: Path) -> dict:
    """Per footer button, from the real picture: the colour Aqua fills its rectangle with (a point just inside the
    rectangle's corner, outside the rounded bezel) and the footer's colour just beside it."""
    at, window, _shot = _picture(root, path)
    found = {"native": window["appearance"], "buttons": {},
             "registration": {"appkit_frame": window["frame"], "tk_size": [root.winfo_width(), root.winfo_height()],
                              "button_x": [b.winfo_rootx() - root.winfo_rootx() for b in (app.appearance_button,
                                                                                          app.preferences_button)]}}
    for button in (app.appearance_button, app.preferences_button):
        found["buttons"][str(button.cget("text"))] = {"rectangle": at(button, 1, 1),
                                                      "footer": at(button, -4, button.winfo_height() // 2)}
    return found


def _gap(first, second) -> int:
    return max(abs(int(a) - int(b)) for a, b in zip(first, second))


def _assert_no_box(app, found: dict) -> None:
    footer = tuple(int(_resolved(_footer(app)["inner"], "bg")[i:i + 2], 16) for i in (1, 3, 5))
    for name, item in found["buttons"].items():
        assert _gap(item["footer"], footer) <= BOX_TOLERANCE, f"the point beside {name!r} is not the footer: {item}, {footer}, {found['registration']}"
        assert _gap(item["rectangle"], item["footer"]) <= BOX_TOLERANCE, (
            f"{name!r} sits in a box of another colour on the footer ({found['native']}): {item}")


@pytest.mark.parametrize("look", APPEARANCES)
def test_the_footer_buttons_sit_on_the_footers_own_colour(shell, tk_root, look, tmp_path):
    """In the real picture each native button's rectangle is the footer's own colour, in the appearance the app is set to.

    ACT72-081: in Light, Aqua filled each rectangle light grey (236) on the footer the shell had resolved Dark at start (50)."""
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "mp3_tool", look)
    found = _boxes(app, tk_root, tmp_path / f"{look}.png")
    assert ("Dark" in found["native"]) == (look == "dark"), found["native"]
    _assert_no_box(app, found)


def test_dark_keeps_the_footer_it_had(shell, tk_root):
    """In Dark the footer is the shell's own Dark palette, as before ACT72-081: surfaces, separator, status and link.

    The shell resolves its palette from the window's appearance when it is built (the system's, in the application); the
    shared test root is put in Dark first, as a Dark system would have it, so the comparison does not depend on test order."""
    _aqua_only(tk_root)
    tk_root.tk.call("tk::unsupported::MacWindowStyle", "appearance", str(tk_root), "darkaqua")
    app, _panel = shell(MINIMUM, "mp3_tool", "dark")
    colors = app.theme["colors"]
    assert colors["is_dark"], colors
    footer = _footer(app)
    assert _resolved(footer["outer"], "bg") == _resolved(footer["inner"], "bg") == colors["window"]
    assert _resolved(footer["separator"], "bg") == colors["separator"]
    assert (_resolved(footer["status"], "bg"), _resolved(footer["status"], "fg")) == (colors["window"], colors["secondary"])
    assert (_resolved(footer["link"], "bg"), _resolved(footer["link"], "fg")) == (colors["window"], colors["link"])


@pytest.mark.parametrize("look", APPEARANCES)
def test_switching_appearance_recolours_the_footer_in_place(shell, tk_root, look, tmp_path):
    """Light to Dark and Dark to Light, without a restart: the same footer widgets, recoloured, never a box."""
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "mp3_tool", look)
    built = {key: (str(widget), widget.winfo_id()) for key, widget in _footer(app).items()}
    other = "dark" if look == "light" else "light"
    for step, expected in enumerate((other, look, other)):
        app.appearance_button.invoke()
        assert app.appearance_bundle["appearance"] == expected
        found = _boxes(app, tk_root, tmp_path / f"{step}-{expected}.png")
        assert ("Dark" in found["native"]) == (expected == "dark"), found["native"]
        _assert_no_box(app, found)
        assert {key: (str(widget), widget.winfo_id()) for key, widget in _footer(app).items()} == built


def test_repeated_switching_adds_no_widget_binding_or_listener(shell, tk_root, tmp_path):
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "mp3_tool", "light")

    def census() -> dict:
        def walk(widget) -> list:
            return [widget] + [found for child in widget.winfo_children() for found in walk(child)]

        return {"widgets": [str(widget) for widget in walk(tk_root)],
                "root bindings": {sequence: tk_root.bind(sequence) for sequence in tk_root.bind()},
                "all bindings": {sequence: tk_root.bind_class("all", sequence) for sequence in tk_root.bind_class("all")},
                "listeners": len(appearance._listeners)}

    first = census()
    for _ in range(6):
        app.appearance_button.invoke()
        _settled(tk_root, 2)
    assert census() == first
    assert app.appearance_bundle["appearance"] == "light"
    _assert_no_box(app, _boxes(app, tk_root, tmp_path / "after-six.png"))


def test_status_and_preferences_keep_working_through_appearance_changes(shell, tk_root, tmp_path):
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "mp3_tool", "light")
    footer = _footer(app)
    app.appearance_button.invoke()
    assert app.status_var.get() == "Appearance: Dark."
    assert str(footer["status"].cget("textvariable")) == str(app.status_var)
    app.preferences_button.invoke()
    _settled(tk_root)
    dialog = app.preferences_dialog
    assert dialog is not None and dialog.winfo_exists()
    assert app.status_var.get() == "Preferences & Data."
    app.appearance_button.invoke()  # Light, with Preferences open
    _assert_no_box(app, _boxes(app, tk_root, tmp_path / "light-preferences-open.png"))
    dialog.close()
    _settled(tk_root)
    assert not dialog.winfo_exists()
    app.appearance_button.invoke()  # Dark, after Preferences closed
    _assert_no_box(app, _boxes(app, tk_root, tmp_path / "dark-preferences-closed.png"))
    app.preferences_button.invoke()
    _settled(tk_root)
    assert app.preferences_dialog.winfo_exists() and app.preferences_dialog is not dialog
    app.preferences_dialog.close()
    _settled(tk_root)
    assert tk_root.bind_class("all", "<Command-comma>"), "Cmd+, still opens Preferences"
    assert tk_root.tk.call("info", "commands", "::tk::mac::Quit"), "Cmd+Q still reaches the launcher"
    assert tk_root.tk.call("info", "commands", "::tk::mac::ShowPreferences")


@pytest.mark.parametrize("look", APPEARANCES)
def test_the_footer_is_on_screen_readable_and_reachable_by_keyboard_at_the_minimum(shell, tk_root, look):
    _aqua_only(tk_root)
    app, _panel = shell(MINIMUM, "mp3_tool", look)
    footer = _footer(app)
    buttons = (app.appearance_button, app.preferences_button)
    for widget in (footer["status"], footer["link"], *buttons):
        assert widget.winfo_viewable() and _inside(widget, tk_root), str(widget)
    for label in (footer["status"], footer["link"]):
        ratio = ui_theme.contrast_ratio(_resolved(label, "fg"), _resolved(label, "bg"))
        assert ratio >= ui_theme.MIN_TEXT_CONTRAST, f"{label.cget('text') or 'status'!r} at {ratio:.2f} in {look}"

    def reaches(start, goal) -> bool:
        widget = start
        for _ in range(500):
            widget = widget.tk_focusNext()
            if widget is None or widget is start:
                return False
            if widget is goal:
                return True
        return False

    for button in buttons:
        assert button.instate(["!disabled"]) and int(button.cget("takefocus"))
    assert reaches(buttons[0], buttons[1]) and reaches(buttons[1], buttons[0]), "Tab reaches both footer buttons"


@pytest.mark.parametrize("look", APPEARANCES)
def test_the_gates_review_of_a_real_picture_finds_no_footer_box(shell, tk_root, look, tmp_path):
    """The machine review the gate gives every picture (Tk's audit at that moment, then ``visual_review``) passes the real
    footer. Before ACT72-081 was found it had no way to see the box; it now compares each native button's rectangle with
    the classic surface it sits on.

    The shared root is returned to the system's appearance first, as the application's root is when the shell resolves its
    palette. Where the system's appearance is not the look under test, the shell's chrome is in the other appearance, and
    the review's whole-picture "shows the appearance it was set to" check (a luminance mean) is not about the footer: only
    then is that one check allowed to fail."""
    _aqua_only(tk_root)
    tk_root.tk.call("tk::unsupported::MacWindowStyle", "appearance", str(tk_root), "auto")
    app, _panel = shell(MINIMUM, "mp3_tool", look)
    at, window, shot = _picture(tk_root, tmp_path / f"{look}.png")
    audit = _gate_module("layout_audit", "adapters/macos/layout_audit.py").audit(tk_root)
    surrounds = {item["path"]: item for item in audit["surrounds"]}
    for button in (app.appearance_button, app.preferences_button):
        assert str(button) in surrounds, f"the audit names the surface under {button.cget('text')!r}"
        assert "#%02x%02x%02x" % tuple(surrounds[str(button)]["rgb"]) == _resolved(button.master, "bg")
    review = _gate_module("visual_review", "helpers/visual_review.py")
    record = {"captured": True, "subject": "window", "width_px": shot["width_px"], "height_px": shot["height_px"],
              "window": {key: value for key, value in window.items() if key != "ptr"}, "layout": audit,
              "appearance": {"app": look, "native": window["appearance"]}}
    verdict = review.review(tmp_path / f"{look}.png", record)
    boxes = [line for line in verdict["defects"] if "box" in line]
    assert not boxes, boxes
    assert not verdict["defects"], verdict["defects"]
    mixed = app.theme["colors"]["is_dark"] != (look == "dark")
    failed = [item["name"] for item in verdict["checks"] if not item["ok"]
              and not (mixed and item["name"] == f"shows the {look} appearance it was set to")]
    assert not failed, verdict["reason"]


def test_other_shells_keep_their_status_bars(fake_settings, tk_root, monkeypatch):
    """The correction is the darwin footer's alone. The classic shell (Linux) keeps its status bar exactly as built through
    appearance changes; the Windows shell has its own ACT styles (``test_launcher_smoke``, win32) and ``ui_theme`` and
    ``appearance`` are unchanged by ACT72-081.

    The classic shell is built here without a tool panel: on an Aqua Tk a panel laid out with Aqua metrics inside the
    classic shell never settles (measured), a combination no platform ships. The status bar is what this test is about."""
    import launcher

    real = ui_theme.apply_theme
    monkeypatch.setattr(launcher.ui_theme, "apply_theme", lambda root, style: real(root, style, platform="linux"))
    monkeypatch.setattr(launcher.LauncherApp, "select_tool", lambda self, key: None)
    existing = set(tk_root.winfo_children())
    fake_settings[appearance.SETTINGS_KEY] = "light"
    app = launcher.LauncherApp(tk_root)
    try:
        _check_classic_status_bar(app, tk_root)
    finally:
        for child in list(tk_root.winfo_children()):
            if child not in existing:
                child.destroy()
        tk_root.protocol("WM_DELETE_WINDOW", "")
        _settled(tk_root, 2)


def _check_classic_status_bar(app, tk_root) -> None:
    assert app.theme["mode"] == "classic"
    bar = app.appearance_button.master

    def snapshot() -> list:
        found = []
        for widget in bar.winfo_children():
            options = {}
            for option in ("background", "foreground", "style"):
                try:
                    options[option] = str(widget.cget(option))
                except tk.TclError:
                    pass
            found.append((str(widget), widget.winfo_class(), options))
        return found

    built = snapshot()
    for _ in range(2):
        app.appearance_button.invoke()
        _settled(tk_root, 2)
    assert snapshot() == built
