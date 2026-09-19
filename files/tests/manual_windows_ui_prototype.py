#!/usr/bin/env python3
"""Developer-only visual fixture for the v0.6.0 Windows UI prototype.

**This is not part of the product and not part of the test suite.**

v0.6.4 Phase 10: the Metadata Editor is now the shared multi-Book workspace
panel, so the canned states drive the *production* model (one Book per file,
frozen source observations, blank Shared) and the *shared* job UI seams; the
Summary / Details specimen sheet below predates the shared log region and is
kept as the visual reference it always was.

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
    """Load canned Books through the panel's own model, touching no disk.

    v0.6.4 Phase 10: the panel is the shared multi-Book workspace, so the
    canned files become Books through the Phase 7 ``import_folder`` projection
    with the tag and chapter readers injected — the real one-file-per-Book
    model, the real observation store, the real Shared/Book rendering, and no
    file is opened. Shared starts blank exactly as it does in production, even
    though every canned source agrees on Author and Album.
    """
    from pathlib import PurePath

    from mp3_tools import m4b_metadata_workflow as wf
    from shared.importing import ImportRoot, ImportedFile, ImportedFileSnapshot, Revision

    folder = Path.home() / "Audiobooks" / "Samples"
    tags_by_path = {folder / name: tags for name, tags in _FAKE_BOOKS}

    def canned_reader(path):
        found = dict(tags_by_path[Path(path)])
        found.setdefault("has_cover", True)
        found.setdefault("series_source", "freeform:com.apple.iTunes")
        found.setdefault("series_part_source", "freeform:com.apple.iTunes")
        return found

    def canned_chapters(_path):
        return _FAKE_CHAPTERS.splitlines()

    root = ImportRoot(root_id="fixture-root", path=folder, order=0)
    entries = tuple(
        ImportedFile(f"fixture-occ-{index}", path, root, PurePath(path.name),
                     wf.EDITOR_TYPE.type_id, f"fixture-id-{index}")
        for index, path in enumerate(tags_by_path, start=1))
    result = wf.import_folder(ui.workspace, ImportedFileSnapshot(Revision(1), entries),
                              id_factory=ui._ids, store=ui.store,
                              reader=canned_reader, chapters=canned_chapters)
    ui._receive(result)


def _make_busy(ui) -> None:
    """Freeze the panel in a controlled mid-run presentation.

    Only the shared job UI's own public methods are used — the lock group
    applying the RUNNING matrix, the control bar and the shared progress
    indicator — so what is on screen is the real active-run presentation, not
    a mock of it. No run is started and no file is touched.
    """
    from shared.job_control import JobState

    ui.lock_group.apply(JobState.RUNNING)
    ui.jobs.controls.apply(JobState.RUNNING)
    ui.jobs.status.indicator.update(2, 3)
    ui.log.divider("──── Save Tags — M4B-Metadata-1 (fixture)")
    ui.log.append("[book-1] Sample Audiobook - Book 1.m4b: ✓ Sample Audiobook - Book 1.m4b")
    ui.log.append("[book-2] Sample Audiobook - Book 2.m4b: writing title, series")


def _make_idle(ui) -> None:
    """Undo :func:`_make_busy` through the same shared seams."""
    from shared.job_control import JobState

    ui.lock_group.apply(JobState.IDLE)
    ui.jobs.controls.apply(JobState.IDLE)
    ui.jobs.status.indicator.reset()


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
