#!/usr/bin/env python3
"""Developer-only visual fixture for the v0.6.0 Windows UI prototype.

**This is not part of the product and not part of the test suite.**

- pytest never collects it: the filename is not ``test_*`` and it declares no
  test functions.
- The launcher cannot reach it: it is not registered in ``launcher.TOOLS``, it
  lives under ``files/`` (the developer tree) rather than ``scripts/`` (the
  shipped tree), and nothing in the product imports it.
- It adds no behaviour. It imports the *production* theme primitives and the
  *production* editor, then drives them into states that are otherwise slow or
  non-deterministic to reach by hand, so they can be looked at and photographed.

Why it exists: the Phase 5 screenshot matrix needs a populated editor, a
mid-run editor, and the Summary/Details specimen. A real batch run finishes far
too quickly to photograph, and a populated batch would otherwise require real
audiobooks on the machine taking the screenshots. Every state below is reached
by calling the editor's own public methods with canned data — no runtime code
path is altered, patched or bypassed.

Usage (from the repository root, with the repo venv):

    .venv\\Scripts\\python.exe files/tests/manual_windows_ui_prototype.py empty
    .venv\\Scripts\\python.exe files/tests/manual_windows_ui_prototype.py populated
    .venv\\Scripts\\python.exe files/tests/manual_windows_ui_prototype.py active-run
    .venv\\Scripts\\python.exe files/tests/manual_windows_ui_prototype.py specimen

No file on disk is read or written by any of these states.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "Universal"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from mp3_tools import m4b_metadata_editor  # noqa: E402
from shared import ui_theme  # noqa: E402

#: Shown on the specimen sheet itself, so a screenshot of it can never be
#: mistaken for shipped functionality.
SPECIMEN_NOTE = (
    "VISUAL SPECIMEN — presentation only. This sheet shows the proposed Summary / "
    "Details visual relationship using the production theme primitives. It is not "
    "wired to anything: there is no filtering, no separate log buffers, no "
    "technical-log routing, no job snapshot, no ETA, no Retry Failed and no "
    "Pause/Resume. That behaviour belongs to a later plan and does not exist in "
    "the product today."
)

#: Canned tag reads. Title and Series Part differ across the batch; everything
#: else is identical, which is what the editor's existing shared-value detection
#: reports as pre-filled vs "(varies)".
_FAKE_BOOKS: list[tuple[str, dict]] = [
    ("Sample Audiobook - Book 1.m4b", {
        "title": "The First Sample", "artist": "A. Sample Author",
        "album": "Sample Chronicles", "year": "2021", "genre": "Audiobook",
        "comment": "Demonstration data only.",
        "series": "Sample Chronicles", "series_part": "1",
        "series_atom": "----:com.apple.iTunes:SERIES",
        "series_part_atom": "----:com.apple.iTunes:SERIES-PART",
    }),
    ("Sample Audiobook - Book 2.m4b", {
        "title": "The Second Sample", "artist": "A. Sample Author",
        "album": "Sample Chronicles", "year": "2021", "genre": "Audiobook",
        "comment": "Demonstration data only.",
        "series": "Sample Chronicles", "series_part": "2",
        "series_atom": "----:com.apple.iTunes:SERIES",
        "series_part_atom": "----:com.apple.iTunes:SERIES-PART",
    }),
    ("Sample Audiobook - Book 3.m4b", {
        "title": "The Third Sample", "artist": "A. Sample Author",
        "album": "Sample Chronicles", "year": "2021", "genre": "Audiobook",
        "comment": "Demonstration data only.",
        "series": "Sample Chronicles", "series_part": "3",
        "series_atom": "----:com.apple.iTunes:SERIES",
        "series_part_atom": "----:com.apple.iTunes:SERIES-PART",
    }),
]

_FAKE_CHAPTERS = (
    "Prologue\nChapter One\nChapter Two\nChapter Three\nChapter Four\nEpilogue"
)


def _populate(ui) -> None:
    """Load canned books through the editor's own state, touching no disk.

    Seeding ``_tag_cache`` and ``_chap_counts`` is what keeps this deterministic
    and offline: ``_refresh_mode`` then runs the real shared-value detection and
    the real chapter pager over them.
    """
    folder = Path.home() / "Audiobooks" / "Samples"
    for name, tags in _FAKE_BOOKS:
        path = folder / name
        ui.files.append(path)
        ui._tag_cache[path] = tags
        ui._chap_counts[path] = 6
        ui._chap_buffers[path] = _FAKE_CHAPTERS
        ui.listbox.insert(tk.END, str(path))
    ui._refresh_mode()
    ui.var_cover_path.set(str(folder / "cover.jpg"))


def _make_busy(ui) -> None:
    """Freeze the editor in a controlled mid-run state.

    Only the editor's own public busy-state methods are used — the same ones
    the real worker drives through its queue — so what is on screen is the real
    active-run presentation, not a mock of it.
    """
    ui._busy.set()  # nothing may start a real job from this window
    ui.progress.update(2, len(ui.files))
    ui.disable_inputs(True)
    ui.btn_cancel.configure(state=tk.NORMAL)
    ui.log_write(
        "\nWriting tags to 3 copy(ies) in C:\\Users\\you\\Downloads\\M4B-Metadata-1…\n"
        "Auto-numbering Series Part from #1 (list order).\n"
        "[1/3] Copied Sample Audiobook - Book 1.m4b → M4B-Metadata-1\n"
        "[1/3] Applied typed tag fields (Series Part #1)\n"
        "[1/3] Applied imported chapter titles\n"
        "[1/3] \u2713 Sample Audiobook - Book 1.m4b\n"
        "[2/3] Copied Sample Audiobook - Book 2.m4b → M4B-Metadata-1\n"
        "[2/3] Applied typed tag fields (Series Part #2)\n"
    )


def _build_specimen(root: tk.Tk, theme: dict) -> None:
    """The Summary / Details component sheet, built from production styles."""
    s, m, f = theme["styles"], theme["metrics"], theme["fonts"]
    root.configure(background=theme["colors"]["window"])

    page = ttk.Frame(root, style=s["window"], padding=m["content_pad"])
    page.pack(fill="both", expand=True)

    ttk.Label(page, text="Summary / Details — component specimen",
              style=s["title"]).pack(anchor="w")
    note = ttk.Label(page, text=SPECIMEN_NOTE, style=s["status_label"],
                     justify="left", wraplength=820)
    note.pack(anchor="w", pady=(m["gap_xs"], m["gap_lg"]))

    card = ttk.Labelframe(page, text="Run output", style=s["labelframe"])
    card.pack(fill="both", expand=True)

    book = ttk.Notebook(card, style=s["notebook"])
    book.pack(fill="both", expand=True)

    summary = ttk.Frame(book, style=s["card"], padding=m["card_pad"])
    book.add(summary, text="Summary")
    for icon, text, style_key in (
        ("\u2713", "3 of 3 files written to Downloads\\M4B-Metadata-1", "success_label"),
        ("\u2713", "Series Parts #1–#3 applied in list order", "success_label"),
        ("!", "1 file had no existing cover art — none was added", "warning_label"),
        ("\u2022", "Originals were not modified", "secondary_label"),
    ):
        line = ttk.Frame(summary, style=s["card"])
        line.pack(fill="x", pady=m["gap_xs"])
        ttk.Label(line, text=icon, style=s[style_key]).pack(
            side="left", padx=(0, m["gap_sm"]))
        ttk.Label(line, text=text, style=s["label"]).pack(side="left")

    details = ttk.Frame(book, style=s["card"], padding=m["card_pad"])
    book.add(details, text="Details")
    log = tk.Text(details, height=10, wrap="none", font=f["mono"])
    ui_theme.style_tk_widget(log, theme, "log")
    log.pack(side="left", fill="both", expand=True)
    bar = ttk.Scrollbar(details, orient="vertical", style=s["vscrollbar"],
                        command=log.yview)
    bar.pack(side="right", fill="y")
    log.configure(yscrollcommand=bar.set)
    log.insert("1.0", (
        "[1/3] Copied Sample Audiobook - Book 1.m4b\n"
        "[1/3] Applied typed tag fields (Series Part #1)\n"
        "[1/3] Applied imported chapter titles\n"
        "[1/3] \u2713 Sample Audiobook - Book 1.m4b\n"
        "[2/3] Copied Sample Audiobook - Book 2.m4b\n"
        "[2/3] Applied typed tag fields (Series Part #2)\n"
        "[2/3] \u2713 Sample Audiobook - Book 2.m4b\n"
        "[3/3] Copied Sample Audiobook - Book 3.m4b\n"
        "[3/3] Applied typed tag fields (Series Part #3)\n"
        "[3/3] \u2713 Sample Audiobook - Book 3.m4b\n"
        "Done. 3 saved, 0 failed.\n"
    ))
    log.configure(state=tk.DISABLED)

    # Action hierarchy and states, for the same design review.
    swatch = ttk.Frame(page, style=s["window"])
    swatch.pack(fill="x", pady=(m["gap_lg"], 0))
    for label, key, states in (
        ("Primary", "primary_button", ()),
        ("Secondary", "button", ()),
        ("Danger", "danger_button", ()),
        ("Ghost", "ghost_button", ()),
        ("Disabled", "primary_button", ("disabled",)),
    ):
        btn = ttk.Button(swatch, text=label, style=s[key])
        btn.pack(side="left", padx=(0, m["gap_sm"]))
        if states:
            btn.state(list(states))


def _open_editor(root: tk.Tk, state: str) -> None:
    ui = m4b_metadata_editor.build_ui(root)
    if state in ("populated", "active-run"):
        _populate(ui)
    if state == "active-run":
        _make_busy(ui)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    state = (argv[0] if argv else "populated").lower()
    valid = {"empty", "populated", "active-run", "specimen"}
    if state not in valid:
        print(f"unknown state {state!r}; expected one of {sorted(valid)}")
        return 2

    root = tk.Tk()
    root.title(f"ACT visual fixture — {state} (developer-only)")
    root.geometry(ui_theme.DEFAULT_GEOMETRY)
    root.minsize(*ui_theme.MIN_SIZE)

    if state == "specimen":
        theme = ui_theme.apply_theme(root, ttk.Style(root))
        _build_specimen(root, theme)
    else:
        _open_editor(root, state)

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
