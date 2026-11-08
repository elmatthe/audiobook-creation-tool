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


def _set_state(panel, voice: str, status: tuple[bool, str]) -> None:
    """The panel's own seams, answering for asset health and nothing else."""
    panel._local_assets = lambda backend, voice_id: status
    panel._chatterbox_status = lambda voice_id: (True, "")
    panel._qwen3_status = lambda voice_id: status
    panel._qwen3_hardware = lambda: QWEN3_CPU_NOTE
    panel._qwen3_setup_offered = lambda: True
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


#: A Qwen3 voice at 920x600 is ACT72-058, recorded rather than fixed here: its owner-required hardware and speed
#: disclosure (Decisions Q3/Q7) and its Install / repair button need more height than either column of the minimum
#: window has left at its floors, so what gives way there is the owner's call. Every other state is required at both
#: sizes, and the Qwen3 states are required at the default size.
CASES = tuple((state, geometry) for geometry in (MINIMUM, ui_theme.DEFAULT_GEOMETRY) for state in STATES
              if not (geometry == MINIMUM and state.startswith("qwen3")))


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
        shown = [label for label in (panel.kokoro_notice_lbl, panel.voice_status_lbl, panel.qwen3_setup_btn)
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
                    "kokoro-absent")
        if geometry == MINIMUM:  # ACT72-058, see CASES
            sequence = tuple(state for state in sequence if not state.startswith("qwen3"))
        for state in sequence:
            _set_state(panel, *STATES[state])
            _settled(tk_root)
            _assert_on_screen(app, panel, f"after choosing {state} at {geometry}")
        _set_state(panel, _edge_label(), (True, ""))
        _settled(tk_root)
        assert _visible_messages(panel) == [], "an Edge voice needs no notice and no setup line"
        assert not panel.qwen3_setup_btn.winfo_ismapped()
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
