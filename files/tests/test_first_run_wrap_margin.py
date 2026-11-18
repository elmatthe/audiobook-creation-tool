"""v0.8.0 P5-F-R1 -- the first-run window wraps every description to the width it really has.

Found natively on a Mac (P5-F): ``run_with_gui._wrap_to_width`` wrapped every label to the container's width less 48, but the container
pads 18 px on each side and each option's description is indented a further 22 px, so a description has the container's width less
58, and Tk lets a wrapped line run up to 4 px past its wraplength (measured), so a margin of 62 is the smallest that never short-changes
a label (P5-F-R1; the proposed 60 still cut 2 px at some widths: 710 wide with the Mac's roster, 820, 860 and 900 with Windows'). Its widest line could be given a few pixels less than it asked for and lose its last letters at the right edge: at the window's own
minimum (660x600) the OmniVoice licence line lost "ll" of "full" (9 px), at 700x640 12 px. The picture review cannot see it (a wrapped
label is judged on height only), so this test compares what each label asked for with what it got.

  * A. Structural: the margin in the source is at least what the layout takes (read from the source, so a changed padding or indent
    changes the requirement with it).
  * B. Live Tk: the real window, at four widths and both rosters (the Mac's two choices, Windows' five), every label has the width and
    height its text asked for, no control or description overlaps another, and the choices and defaults are untouched.

Windows: the live check runs on this machine's Tk and fonts, with Windows' five-choice roster. It proves the arithmetic and the layout
of the shared code; it is NOT a native Windows GUI verification (Windows' fonts and scaling are its own).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

from shared import bootstrap  # noqa: E402
import tk_gate  # noqa: E402

SRC = Path(bootstrap.__file__).read_text(encoding="utf-8")


def _run_with_gui_source() -> str:
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    return ast.get_source_segment(SRC, fn)


# --------------------------------------------------------------------------- #
# A. Structural: the margin covers the padding and the indent
# --------------------------------------------------------------------------- #
#: How far Tk lets a wrapped line run past its wraplength (4 px measured, Tk 9 on macOS).
TK_OVERSHOOT = 4


def _layout() -> tuple[int, int, int]:
    """(container padding per side, a description's left indent, the margin subtracted from the container's width), from the source."""
    body = _run_with_gui_source()
    padding = int(re.search(r"container = ttk\.Frame\(root, padding=(\d+)\)", body).group(1))
    indent = int(re.search(r"_note = ttk\.Label\(intro, text=note, justify=\"left\"\)\s*_note\.pack\([^)]*padx=\((\d+), 0\)", body).group(1))
    margin = int(re.search(r"target = max\(\d+, width - (\d+)\)", body).group(1))
    return padding, indent, margin


def test_the_wrap_margin_covers_the_containers_padding_and_a_descriptions_indent():
    padding, indent, margin = _layout()
    assert (padding, indent) == (18, 22), "the layout this test reasons about changed: re-derive the margin"
    assert margin >= 2 * padding + indent + TK_OVERSHOOT, (
        f"a description has the container's width less {2 * padding + indent}, and a wrapped line may run {TK_OVERSHOOT} px past its "
        f"wraplength; it is wrapped to less {margin}")
    assert margin == 62, "the smallest margin at which the sweep below finds no label short-changed"


def test_the_wrap_target_still_follows_the_window_and_keeps_its_floor():
    body = _run_with_gui_source()
    assert 'container.bind("<Configure>", _wrap_to_width)' in body
    assert re.search(r"target = max\(320, width - 62\)", body)
    assert "width = container.winfo_width()" in body and "if width <= 1" in body


def test_the_corrected_margin_is_the_only_wrapping_change():
    """No new wrapping mechanism: one list of wrapped labels, one handler, notes still appended to it."""
    body = _run_with_gui_source()
    assert body.count("_wrapped.append(") >= 2 and body.count("def _wrap_to_width") == 1
    assert body.count("wraplength=target") == 1


# --------------------------------------------------------------------------- #
# B. Live Tk
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def tk_root():
    tk = pytest.importorskip("tkinter")
    yield from tk_gate.tk_root_session(tk)


from test_setup_log_follow import descendants, native_theme, run_as_toplevel, settle, setup_log  # noqa: E402,F401

ESTIMATES = {"kokoro": "344.7 MB", "chatterbox": "4.9 GB", "qwen3-customvoice": "4.0 GB", "qwen3-base": "4.0 GB", "omnivoice": "3.5 GB"}
#: The four sizes the native journey shows, and a sweep every 10 px from the minimum to 1000 px (the margin was short at 34 of the
#: widths from 660 to 1400 before the correction).
WIDTHS = ((660, 600), (700, 640), (760, 680), (900, 700)) + tuple((w, 700) for w in range(660, 1001, 10))


def _boxes(window, cls):
    return [w for w in descendants(window) if w.winfo_class() == cls and w.winfo_viewable()]


def _overlaps(a, b) -> bool:
    ax, ay, bx, by = a.winfo_rootx(), a.winfo_rooty(), b.winfo_rootx(), b.winfo_rooty()
    return (min(ax + a.winfo_width(), bx + b.winfo_width()) - max(ax, bx) > 1
            and min(ay + a.winfo_height(), by + b.winfo_height()) - max(ay, by) > 1)


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_no_description_loses_text_or_overlaps_at_any_supported_width(monkeypatch, tk_root, setup_log, native_theme, platform):
    choices = bootstrap.optional_choices_for(platform)
    monkeypatch.setattr(bootstrap, "OPTIONAL_CHOICES", choices)
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: dict(ESTIMATES))
    monkeypatch.setattr(bootstrap, "run_setup", lambda *a, **k: pytest.fail("a layout test started setup"))
    monkeypatch.setattr(bootstrap, "launch_gui", lambda *a, **k: pytest.fail("a layout test launched the app"))
    seen: dict = {}

    def script(window):
        settle(window)
        for width, height in WIDTHS:
            window.geometry(f"{width}x{height}")
            for _ in range(6):
                settle(window)
            labels = _boxes(window, "TLabel")
            controls = _boxes(window, "TCheckbutton") + _boxes(window, "TButton")
            cut = [(str(l.cget("text"))[:30], l.winfo_reqwidth() - l.winfo_width(), l.winfo_reqheight() - l.winfo_height())
                   for l in labels if l.winfo_reqwidth() - l.winfo_width() > 1 or l.winfo_reqheight() - l.winfo_height() > 1]
            items = labels + controls
            collisions = [(str(a.cget("text"))[:20], str(b.cget("text"))[:20]) for i, a in enumerate(items) for b in items[i + 1:] if _overlaps(a, b)]
            top, bottom = window.winfo_rooty(), window.winfo_rooty() + window.winfo_height()
            outside = [str(w.cget("text"))[:24] for w in items if w.winfo_rooty() < top or w.winfo_rooty() + w.winfo_height() > bottom
                       or w.winfo_rootx() + w.winfo_width() > window.winfo_rootx() + window.winfo_width()]
            seen[(width, height)] = {"size": (window.winfo_width(), window.winfo_height()), "cut": cut, "collisions": collisions,
                                     "outside": outside, "buttons": sorted(str(b.cget("text")) for b in _boxes(window, "TButton"))}
        checks = _boxes(window, "TCheckbutton")
        seen["labels"] = [str(c.cget("text")) for c in checks]
        seen["values"] = [bool(window.getvar(str(c.cget("variable")))) for c in checks]
        seen["texts"] = " ".join(str(l.cget("text")) for l in _boxes(window, "TLabel"))
        window.destroy()

    run_as_toplevel(monkeypatch, tk_root, script)
    assert bootstrap.run_with_gui() == bootstrap.EXIT_SETUP_CANCELLED, "closing before Begin Setup is still the cancellation status"
    assert len([k for k in seen if isinstance(k, tuple)]) >= 30, "the sweep ran"
    for size, found in ((k, v) for k, v in seen.items() if isinstance(k, tuple)):
        assert found["size"] == size, (size, found["size"])
        assert not found["cut"], f"{platform} at {size}: a label got less than it asked for: {found['cut']}"
        assert not found["collisions"], f"{platform} at {size}: {found['collisions']}"
        assert not found["outside"], f"{platform} at {size}: {found['outside']}"
        assert found["buttons"] == ["Begin Setup", "Cancel"], (size, found["buttons"])
    # The roster, its defaults and its consent text are untouched.
    assert [c[1] for c in choices] == [label.split(" (up to")[0] for label in seen["labels"]]
    assert seen["values"] == [default for _c, _l, default, _n in choices]
    assert all(note in seen["texts"] for _c, _l, _d, note in choices), "every description is still shown, whole"
    if platform == "darwin":
        assert [c[0] for c in choices] == ["kokoro", "omnivoice"] and "NON-COMMERCIAL" in seen["texts"] and "CC-BY-NC" in seen["texts"]
    else:
        assert [c[0] for c in choices] == ["kokoro", "chatterbox", "qwen3-customvoice", "qwen3-base", "omnivoice"]
        assert seen["values"] == [True, False, False, False, False]
