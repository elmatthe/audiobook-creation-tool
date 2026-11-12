"""Optional-voice notices at the supported sizes -- v0.7.2 Phase 5, ACT72-007.

With a Kokoro voice selected and its model files absent, the panel stacked two
messages: the "not installed, choose Install & Continue" status line under an
older notice still promising that "the first Kokoro run may download ~300 MB"
-- untrue since v0.7.0, when model files stopped being downloaded on first use.
At the 920x600 Windows minimum the two together pushed Start out of the window
(reproduced at ``fa9d3c3`` by the absent-Kokoro cases below; it passed on a
machine with Kokoro installed only because the status line never appeared).

Every state here is set explicitly through the panel's own seams -- installed
and absent, for Kokoro, Chatterbox and Qwen3 -- so the result never depends on
what this machine happens to have installed. These fake only asset *health*:
nothing here loads an engine, synthesises audio or qualifies one, and nothing
is downloaded. The window is the real launcher shell at real sizes.
"""

from __future__ import annotations

import pytest

from shared import ui_theme
from shared.job_control import JobAction
from tts import epub2tts_gui as panel_module

from test_tts_appearance import (  # noqa: F401 - fixtures are used by name
    CHATTERBOX,
    KOKORO,
    MINIMUM,
    _assert_on_screen,
    _fresh_shell,
    _inside,
    _required_controls,
    _settled,
    _tear_down_shell,
    fake_settings,
    output_base,
    tk_root,
)

QWEN3 = "Qwen3 - Aiden"
KOKORO_ABSENT = ("The Kokoro voices are not installed on this computer yet. Choose Install & Continue to review the "
                 "download and install them; Edge voices work meanwhile.")
KOKORO_SPACY_ABSENT = ("Kokoro's English pronunciation model is not installed yet. Choose Install & Continue to "
                       "review the download and install it.")
CHATTERBOX_ABSENT = ("The Chatterbox Turbo model is not installed on this computer yet. Choose Install & Continue "
                     "to review the download and install it.")
QWEN3_ABSENT = ("The Qwen3 Base model (4.5 GB) is not installed. Choose \"Install / repair Qwen3 voices\" to install "
                "it; nothing is downloaded until you ask.")
#: The longest real disclosure ``qwen3_runtime.hardware_summary`` can give.
QWEN3_CPU_NOTE = ("No NVIDIA GPU was detected, so Qwen3 will run on the CPU, which is much slower and uses about 6 GB "
                  "of memory. On the tested Ryzen 7 9800X3D it took about 2.2 times as long as the audio; "
                  "your computer may be slower.")
#: The other shape ``hardware_summary`` gives, with a long real adapter name.
QWEN3_GPU_NOTE = ("Runs on your NVIDIA GPU (NVIDIA GeForce RTX 5070, 12 GB). Speed depends on the computer: on the "
                  "RTX 5070 it was tested on, narration took about 1.4 to 1.9 times as long as the audio it produced.")
QWEN3_UNSUPPORTED = "Qwen3 voices are not yet available on this platform. Every other voice is unaffected."

STATES = {
    "kokoro-installed": (KOKORO, (True, "")),
    "kokoro-absent": (KOKORO, (False, KOKORO_ABSENT)),
    "kokoro-pronunciation-absent": (KOKORO, (False, KOKORO_SPACY_ABSENT)),
    "chatterbox-absent": (CHATTERBOX, (False, CHATTERBOX_ABSENT)),
    "qwen3-installed": (QWEN3, (True, "ok")),
    "qwen3-absent": (QWEN3, (False, QWEN3_ABSENT)),
}


def _edge_label() -> str:
    labels = [label for label in panel_module.display_labels()
              if panel_module.get_voice(label) and panel_module.get_voice(label).backend == "edge"]
    return labels[0]


def _set_state(panel, voice: str, status: tuple[bool, str], *, note: str = QWEN3_CPU_NOTE,
               offered: bool = True) -> None:
    """The panel's own seams, answering for asset health and nothing else."""
    panel._local_assets = lambda backend, voice_id: status
    panel._chatterbox_status = lambda voice_id: (True, "")
    panel._qwen3_status = lambda voice_id: status
    panel._qwen3_hardware = lambda: note
    panel._qwen3_setup_offered = lambda: offered
    panel.selected_voice_label.set(voice)
    panel._on_voice_selected()


def _visible_messages(panel) -> list[str]:
    shown = []
    for label, variable in ((panel.kokoro_notice_lbl, panel.kokoro_notice_var),
                            (panel.voice_status_lbl, panel.voice_status_var)):
        if label.winfo_ismapped():
            shown.append(variable.get())
    return shown


def _boxes_apart(a, b) -> bool:
    ax, ay, bx, by = a.winfo_rootx(), a.winfo_rooty(), b.winfo_rootx(), b.winfo_rooty()
    return (ax + a.winfo_width() <= bx or bx + b.winfo_width() <= ax
            or ay + a.winfo_height() <= by or by + b.winfo_height() <= ay)


#: Every state is required at both sizes. Qwen3 at 920x600 was ACT72-058 until v0.7.2 Phase 6: its hardware and speed
#: disclosure (Decisions Q3/Q7) and its Install / repair button needed 10 px (installed) to 63 px (absent) more than
#: either column had at its floors. The owner approved a compact presentation there (see the tests at the end).
CASES = tuple((state, geometry) for geometry in (MINIMUM, ui_theme.DEFAULT_GEOMETRY) for state in STATES)


@pytest.mark.parametrize(("state", "geometry"), CASES)
def test_every_optional_voice_state_keeps_start_and_cancel_on_screen(
        fake_settings, output_base, tk_root, state, geometry):
    voice, status = STATES[state]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, voice, status)
        _settled(tk_root)
        where = f"{state} at {geometry}"
        _assert_on_screen(app, panel, where)
        start = panel.go_btn
        cancel = panel.jobs.controls.buttons[JobAction.CANCEL]
        for name, widget in (("Start", start), ("Cancel", cancel)):
            assert widget.winfo_ismapped() and _inside(widget, app.content), f"{name} is off screen: {where}"
        shown = [label for label in (panel.kokoro_notice_lbl, panel.voice_status_lbl, panel.qwen3_setup_btn,
                                     panel.qwen3_details_btn)
                 if label.winfo_ismapped()]
        for index, widget in enumerate(shown):
            assert _inside(widget, app.content), f"{widget} is clipped: {where}"
            for other in shown[index + 1:]:
                assert _boxes_apart(widget, other), f"two voice messages overlap: {where}"
        if not status[0]:
            assert status[1] in _visible_messages(panel), f"the reason is not shown: {where}"
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("state", ("kokoro-absent", "kokoro-pronunciation-absent"))
def test_an_absent_kokoro_shows_one_message_that_says_what_to_do(fake_settings, output_base, tk_root, state):
    voice, status = STATES[state]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, voice, status)
        _settled(tk_root)
        assert _visible_messages(panel) == [status[1]], "the setup line must stand alone, not under a second notice"
    finally:
        _tear_down_shell(tk_root, existing)


def test_an_installed_kokoro_notice_promises_no_download(fake_settings, output_base, tk_root):
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["kokoro-installed"])
        _settled(tk_root)
        shown = _visible_messages(panel)
        assert len(shown) == 1, shown
        notice = shown[0].lower()
        assert "runs locally" in notice or "run locally" in notice
        assert "download" not in notice and "300 mb" not in notice, (
            "since v0.7.0 nothing is downloaded on a first run; the notice must not say otherwise")
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("geometry", (MINIMUM, ui_theme.DEFAULT_GEOMETRY))
def test_changing_voice_while_idle_leaves_no_stale_message_and_start_reachable(
        fake_settings, output_base, tk_root, geometry):
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["tts"].winfo_children()[0]
        sequence = ("kokoro-absent", "qwen3-absent", "chatterbox-absent", "kokoro-installed", "qwen3-installed",
                    "kokoro-absent", "qwen3-installed")
        for state in sequence:
            _set_state(panel, *STATES[state])
            _settled(tk_root)
            _assert_on_screen(app, panel, f"after choosing {state} at {geometry}")
            if not state.startswith("qwen3"):
                assert not panel.qwen3_details_btn.winfo_ismapped(), f"a Qwen3 control left behind by {state}"
        _set_state(panel, _edge_label(), (True, ""))
        _settled(tk_root)
        assert _visible_messages(panel) == [], "an Edge voice needs no notice and no setup line"
        assert not panel.qwen3_setup_btn.winfo_ismapped()
        assert not panel.qwen3_details_btn.winfo_ismapped()
        assert not panel.qwen3_actions.winfo_ismapped(), "the empty Qwen3 actions row must take no height"
        _assert_on_screen(app, panel, "back on an Edge voice")
    finally:
        _tear_down_shell(tk_root, existing)


def test_resizing_and_the_appearance_toggle_keep_an_absent_kokoro_usable(fake_settings, output_base, tk_root):
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["kokoro-absent"])
        _settled(tk_root)
        for geometry in (ui_theme.DEFAULT_GEOMETRY, "1920x1009", MINIMUM):
            tk_root.geometry(geometry)
            _settled(tk_root)
            _assert_on_screen(app, panel, f"kokoro-absent resized to {geometry}")
        app._toggle_appearance()
        _settled(tk_root)
        _assert_on_screen(app, panel, "kokoro-absent after the appearance toggle")
        assert _visible_messages(panel) == [KOKORO_ABSENT]
        app._toggle_appearance()
        _settled(tk_root)
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_kokoro_notice_returns_when_the_voice_becomes_installed(fake_settings, output_base, tk_root):
    """Start and Install & Continue ask the status again; the one message follows the answer."""
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["kokoro-absent"])
        _settled(tk_root)
        assert _visible_messages(panel) == [KOKORO_ABSENT]
        panel._local_assets = lambda backend, voice_id: (True, "")
        panel._refresh_voice_status(panel_module.get_voice(KOKORO))
        panel._content_changed()  # what Start and the install route both do next
        _settled(tk_root)
        shown = _visible_messages(panel)
        assert len(shown) == 1 and "run locally" in shown[0], shown
        _assert_on_screen(app, panel, "kokoro installed after being absent")
    finally:
        _tear_down_shell(tk_root, existing)


# --------------------------------------------------------------------------- #
# ACT72-058 (v0.7.2 Phase 6): a Qwen3 voice at the 920x600 minimum
#
# The owner approved a compact presentation of the hardware and speed disclosure
# at the minimum size, with the complete text one press away through a clearly
# labelled, keyboard-reachable details control. The full disclosure stays at
# every size where it fits. Nothing is hidden for good, no action is removed, the
# minimum size is not raised and the queue and the log keep their floors. Every
# judgement below reads actual Tk geometry (winfo_root*/winfo_height), not
# requested sizes.
# --------------------------------------------------------------------------- #
DETAILS_LABEL = "Hardware and speed..."
QWEN3_NOTES = {"cpu": QWEN3_CPU_NOTE, "gpu": QWEN3_GPU_NOTE}


def _floors_hold(panel, where: str) -> None:
    """The queue and the Summary log keep their established floors, in real pixels."""
    import tkinter.font as tkfont

    listbox = panel.importer.list.listbox
    rows = (panel_module.IMPORTER_SPLIT_FLOOR_ROWS if panel._layout_mode[0] == "split"
            else panel_module.IMPORTER_FLOOR_ROWS)
    assert listbox.winfo_height() >= int(rows * panel._needs["list_row_px"]), f"queue below its floor: {where}"
    log = panel.log.summary_text
    line = tkfont.Font(font=log.cget("font")).metrics("linespace")
    assert log.winfo_height() >= panel_module.LOG_FLOOR_LINES * line, f"log below its floor: {where}"


def _start_and_cancel_on_screen(app, panel, where: str) -> None:
    for name, widget in (("Start", panel.go_btn), ("Cancel", panel.jobs.controls.buttons[JobAction.CANCEL])):
        assert widget.winfo_ismapped() and _inside(widget, app.content), f"{name} is off screen: {where}"


def _presentation(panel) -> str:
    """Which presentation of the Qwen3 disclosure is on screen: full, compact, or none."""
    full, compact = panel.kokoro_notice_lbl.winfo_ismapped(), panel.qwen3_details_btn.winfo_ismapped()
    assert not (full and compact), "the full disclosure and its compact control must never show together"
    return "full" if full else "compact" if compact else "none"


@pytest.mark.parametrize("hardware", sorted(QWEN3_NOTES))
@pytest.mark.parametrize("state", ("qwen3-installed", "qwen3-absent"))
def test_a_qwen3_voice_at_the_minimum_is_compact_and_keeps_every_action_on_screen(
        fake_settings, output_base, tk_root, state, hardware):
    voice, status = STATES[state]
    note = QWEN3_NOTES[hardware]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, voice, status, note=note)
        _settled(tk_root)
        where = f"{state} ({hardware}) at {MINIMUM}"
        assert panel._layout_mode == ("split", "narrow"), f"the panel stacked: {where}"
        _assert_on_screen(app, panel, where)
        _start_and_cancel_on_screen(app, panel, where)
        _floors_hold(panel, where)
        assert _presentation(panel) == "compact", where
        details, install = panel.qwen3_details_btn, panel.qwen3_setup_btn
        assert str(details.cget("text")) == DETAILS_LABEL
        for widget in (details, install):
            assert widget.winfo_ismapped() and _inside(widget, app.content), f"{widget} is off screen: {where}"
            assert _inside(widget, panel.voice_section), f"{widget} left Voice & Audio: {where}"
            assert widget.winfo_height() >= 20 and widget.winfo_width() >= widget.winfo_reqwidth(), (
                f"{widget} is squeezed: {where}")
        assert _boxes_apart(details, install), where
        assert abs(details.winfo_rooty() - install.winfo_rooty()) <= 2, "the two actions share one row"
        assert panel.kokoro_notice_var.get() == note, "the complete disclosure is kept, never cut"
        if not status[0]:
            assert status[1] in _visible_messages(panel), f"the model's state is not shown: {where}"
    finally:
        _tear_down_shell(tk_root, existing)


def test_the_details_control_is_reachable_by_keyboard_and_shows_the_complete_disclosure(
        fake_settings, output_base, tk_root, monkeypatch):
    shown = []
    monkeypatch.setattr(panel_module.messagebox, "showinfo",
                        lambda title, message, **kwargs: shown.append((title, message, kwargs.get("parent"))))
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["qwen3-absent"])
        _settled(tk_root)
        details = panel.qwen3_details_btn
        assert panel.qwen3_setup_btn.tk_focusNext() is details, "Tab goes from Install / repair to the details"
        details.focus_force()
        _settled(tk_root)
        details.event_generate("<Key-space>")
        _settled(tk_root)
        assert shown == [(panel_module.QWEN3_DETAILS_TITLE, QWEN3_CPU_NOTE, panel)], shown
        details.invoke()
        assert len(shown) == 2 and shown[1][1] == QWEN3_CPU_NOTE
    finally:
        _tear_down_shell(tk_root, existing)


@pytest.mark.parametrize("geometry", (ui_theme.DEFAULT_GEOMETRY, "1920x1009"))
@pytest.mark.parametrize("state", ("qwen3-installed", "qwen3-absent"))
def test_larger_windows_keep_the_full_qwen3_disclosure(fake_settings, output_base, tk_root, state, geometry):
    voice, status = STATES[state]
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, geometry)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, voice, status)
        _settled(tk_root)
        where = f"{state} at {geometry}"
        assert _presentation(panel) == "full", where
        assert _inside(panel.kokoro_notice_lbl, app.content), where
        assert QWEN3_CPU_NOTE in _visible_messages(panel), where
        assert panel.qwen3_setup_btn.winfo_ismapped() and _inside(panel.qwen3_setup_btn, app.content), where
        _assert_on_screen(app, panel, where)
    finally:
        _tear_down_shell(tk_root, existing)


def test_resizing_and_the_appearance_toggle_move_between_compact_and_full_disclosure(
        fake_settings, output_base, tk_root):
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["qwen3-absent"])
        _settled(tk_root)
        expected = {MINIMUM: "compact", ui_theme.DEFAULT_GEOMETRY: "full", "1920x1009": "full"}
        for geometry in (MINIMUM, ui_theme.DEFAULT_GEOMETRY, MINIMUM, "1920x1009", MINIMUM):
            tk_root.geometry(geometry)
            _settled(tk_root)
            where = f"qwen3-absent resized to {geometry}"
            assert _presentation(panel) == expected[geometry], where
            _assert_on_screen(app, panel, where)
            _start_and_cancel_on_screen(app, panel, where)
            _floors_hold(panel, where)
            assert QWEN3_ABSENT in _visible_messages(panel), where
        for _ in range(2):
            app._toggle_appearance()
            _settled(tk_root)
            assert _presentation(panel) == "compact", "after the appearance toggle"
            _assert_on_screen(app, panel, "qwen3-absent after the appearance toggle")
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_qwen3_voice_becoming_installed_or_missing_at_the_minimum_stays_usable(fake_settings, output_base, tk_root):
    """The install route and Start ask the status again; the panel follows the answer at the minimum size."""
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, *STATES["qwen3-absent"])
        _settled(tk_root)
        for answer in ((True, "ok"), (False, QWEN3_ABSENT), (True, "ok")):
            panel._qwen3_status = lambda voice_id, answer=answer: answer
            panel._on_qwen3_setup_changed()  # what closing the install / repair dialog does
            _settled(tk_root)
            where = f"qwen3 now {'installed' if answer[0] else 'absent'}"
            assert (QWEN3_ABSENT in _visible_messages(panel)) is (not answer[0]), where
            assert _presentation(panel) == "compact", where
            _assert_on_screen(app, panel, where)
            _start_and_cancel_on_screen(app, panel, where)
            assert panel.qwen3_setup_btn.winfo_ismapped() and _inside(panel.qwen3_setup_btn, app.content), where
    finally:
        _tear_down_shell(tk_root, existing)


def test_a_platform_without_qwen3_shows_its_reason_and_no_disclosure_at_the_minimum(fake_settings, output_base, tk_root):
    """``hardware_summary`` is empty where the voices are not yet available, and no install is offered."""
    existing = set(tk_root.winfo_children())
    try:
        app = _fresh_shell(tk_root, MINIMUM)
        panel = app.containers["tts"].winfo_children()[0]
        _set_state(panel, QWEN3, (False, QWEN3_UNSUPPORTED), note="", offered=False)
        _settled(tk_root)
        assert _presentation(panel) == "none"
        assert not panel.qwen3_setup_btn.winfo_ismapped()
        assert _visible_messages(panel) == [QWEN3_UNSUPPORTED]
        _assert_on_screen(app, panel, "qwen3 unsupported at the minimum")
    finally:
        _tear_down_shell(tk_root, existing)
