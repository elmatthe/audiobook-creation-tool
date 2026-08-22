"""v0.6.1 Plan 4 Phase 12 remediation — the first-run setup dialog must fit.

The maintainer's real 1920x1080 / 100%-scaling screenshot showed the first-run
dialog cutting off its own explanatory text. The cause was structural, not
cosmetic: the two option descriptions were long single-line ``ttk.Checkbutton``
labels, and **ttk.Checkbutton has no ``wraplength`` option** — only ``ttk.Label``
and the classic ``tk`` widgets do. There was therefore nothing that could make
those strings fold, and a fixed 640-pixel window simply clipped them.

Widening the window would only have moved the cut, so the fix keeps the
checkbutton labels short and moves every long string into a real wrapped
``ttk.Label`` whose ``wraplength`` follows the window.

These are structural assertions plus one live Tk geometry check. The Tk check
skips on a headless machine rather than failing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared import bootstrap  # noqa: E402
import tk_gate  # noqa: E402

SRC = Path(bootstrap.__file__).read_text(encoding="utf-8")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_with_gui_source() -> str:
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_with_gui")
    return ast.get_source_segment(SRC, fn)


# --------------------------------------------------------------------------- #
# A. Structural — nothing long may live on an unwrappable widget
# --------------------------------------------------------------------------- #
def test_no_checkbutton_carries_an_unwrappable_paragraph():
    """The exact defect: a >90-character label on a widget that cannot wrap."""
    body = _run_with_gui_source()
    tree = ast.parse(body.strip())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None)
        if name != "Checkbutton":
            continue
        for kw in node.keywords:
            if kw.arg == "text" and isinstance(kw.value, ast.Constant):
                if len(kw.value.value) > 90:
                    offenders.append(kw.value.value)
    assert not offenders, (
        "ttk.Checkbutton cannot wrap; move this text to a wrapped ttk.Label: "
        f"{offenders}")


def test_the_dialog_wraps_its_long_labels_responsively():
    body = _run_with_gui_source()
    assert "wraplength" in body
    assert "<Configure>" in body


def test_both_option_descriptions_survived_the_rewrite():
    """Meaning must be retained — only the widget rendering it changed."""
    body = _run_with_gui_source()
    assert "auto-downloads on first synthesis" in body
    assert "the model downloads on first use instead" in body
    assert "~300 MB" in body and "~3.9 GB" in body


def test_the_action_buttons_are_still_present():
    body = _run_with_gui_source()
    assert "Begin Setup" in body
    assert "Cancel" in body


def test_chatterbox_stays_unchecked_and_kokoro_keeps_its_default():
    body = _run_with_gui_source()
    assert '"download_chatterbox": tk.BooleanVar(value=False)' in body
    assert '"download_kokoro": tk.BooleanVar(value=not skip_kokoro_default)' in body


def test_the_window_is_not_merely_made_enormous():
    """A fixed-size sledgehammer would not survive a smaller display."""
    body = _run_with_gui_source()
    geometry = next(line for line in body.splitlines() if "root.geometry(" in line)
    width, height = (int(v) for v in
                     geometry.split('"')[1].split("x"))
    assert width <= 900 and height <= 760, (width, height)


# --------------------------------------------------------------------------- #
# B. Live Tk — the text actually fits at the shipped size
# --------------------------------------------------------------------------- #
@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    yield from tk_gate.tk_root_session(tk)


def test_a_wrapped_label_reports_a_height_greater_than_one_line(tk_root):
    """Proof the wrap mechanism works on this Tk, not just in the source text."""
    from tkinter import ttk

    frame = ttk.Frame(tk_root)
    frame.pack(fill="both", expand=True)
    long_text = ("Optional — leave this unchecked unless you plan to use the "
                 "cloned voices; the model downloads on first use instead.")
    unwrapped = ttk.Label(frame, text=long_text)
    wrapped = ttk.Label(frame, text=long_text, wraplength=400, justify="left")
    unwrapped.pack()
    wrapped.pack()
    tk_root.update_idletasks()

    assert unwrapped.winfo_reqwidth() > 400, "fixture text is not long enough"
    assert wrapped.winfo_reqwidth() <= 420
    assert wrapped.winfo_reqheight() > unwrapped.winfo_reqheight()


def test_checkbutton_really_has_no_wraplength_option(tk_root):
    """Pins the reason for the fix, so nobody 'simplifies' it back."""
    from tkinter import ttk

    check = ttk.Checkbutton(tk_root, text="x")
    assert "wraplength" not in check.keys()
