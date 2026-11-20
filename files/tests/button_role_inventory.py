"""The owner-approved v0.8.1 button-role inventory (Roadmap Appendix A, 146 controls).

A helper, not a test module: ``test_button_roles`` pins the table itself, and each
surface's own test file builds the real widgets and hands them to :func:`audit`.

Role letters: A red outline, B green outline, C yellow outline, D blue outline,
E normal. The ten owner-screenshot blue departures are the Book Previous / Next /
Add / Duplicate rows of the MP3 Tool and the M4B Maker and the Previous / Next rows
of M4B Metadata. A row's label is the approved name ("as shown or conditional
action"); the live widget's own text may differ slightly (``◀ Previous`` is shown
for "◀ Previous Book"), so the audit is keyed by the row, never by widget text.
"""

from __future__ import annotations

from tkinter import ttk

from shared import appearance

_LIST = [  # the shared imported-file list and import status (TTS, Converter, Cover)
    ("Add Files…", "E"), ("Add Folder…", "E"), ("Move Up", "E"),
    ("Move Down", "E"), ("Remove", "A"), ("Clear All", "A"),
    ("Cancel Import", "A"),
]
_JOB = [  # the shared job control bar
    ("Pause", "C"), ("Resume", "C"), ("Cancel", "A"), ("Retry Failed", "C"),
]
_BOOKS = [  # the Book tools' import band, navigator, artwork and track list
    ("Import Folder", "E"), ("Cancel Import", "A"), ("Clear All Imports", "A"),
    ("◀ Previous Book", "D"), ("Next Book ▶", "D"),
]
_ARTWORK = [
    ("Shared Artwork — Choose…", "E"), ("Shared Artwork — Clear", "A"),
    ("Book Artwork — Choose…", "E"), ("Book Artwork — Clear", "A"),
]
_TRACKS = [
    ("Add Files", "E"), ("Move Up", "E"), ("Move Down", "E"),
    ("Remove Selected", "A"),
]

INVENTORY: dict[str, list[tuple[str, str]]] = {
    "tts": _LIST + [("Start", "B")] + _JOB + [
        ("Open Output Folder", "E"), ("Clear Log", "A"),
        ("Install / repair Qwen3 voices…", "D"), ("Qwen3 details / disclosure", "E"),
    ],
    "converter": _LIST + [("Convert M4Bs → MP3s", "B")] + _JOB + [
        ("Open Output Folder", "E"), ("Clear Log", "A"),
    ],
    "mp3": _BOOKS + [("Add Book", "D"), ("Duplicate Book", "D"),
                     ("Remove Book", "A")] + _ARTWORK + _TRACKS + [
        ("Write ID3 Tags", "B"), ("Combine MP3s → One MP3", "B"),
    ] + _JOB + [("Clear Log", "A")],
    "maker": _BOOKS + [("Add Book", "D"), ("Duplicate Book", "D"),
                       ("Remove Book", "A")] + _ARTWORK + _TRACKS + [
        ("Custom Destination — Browse…", "E"), ("Build M4B(s)", "B"),
    ] + _JOB + [("Clear Log", "A")],
    "cover": _LIST + [("Resize Covers", "B")] + _JOB + [("Clear Log", "A")],
    "metadata": [
        ("Import Folder", "E"), ("Add Files", "E"), ("Cancel Import", "A"),
        ("Clear All Imports", "A"), ("◀ Previous Book", "D"), ("Next Book ▶", "D"),
        ("Remove Book", "A"),
    ] + _ARTWORK + [
        ("Save Tags", "B"), ("Clear All Tags (keep chapters)", "A"),
        ("Remove Series Numbering", "A"), ("Open Output Folder", "E"),
    ] + _JOB + [("Clear Log", "A")],
    "preferences": [
        ("Output Location — Browse…", "E"), ("Save", "B"),
        ("Reset Preferences…", "A"), ("Clear Downloaded Data", "A"),
        ("Repair App Environment…", "D"), ("Close", "E"),
    ],
    "navigation": [
        ("TTS Audiobook navigation", "E"), ("M4B Converter navigation", "E"),
        ("MP3 Tool navigation", "E"), ("M4B Maker navigation", "E"),
        ("Cover Image navigation", "E"), ("M4B Metadata navigation", "E"),
        ("Light / Dark toggle", "E"), ("Preferences & Data…", "E"),
        ("Open log folder", "E"),
    ],
    # The conditional setup and dialog controls, grouped by the surface that builds them.
    "setup": [
        ("Install & Continue", "B"), ("Install Selected Components", "B"),
        ("Skip optional installation", "E"), ("View licence terms", "E"),
        ("Open licence document", "E"), ("Cancel setup / installation", "A"),
        ("Continue setup", "E"), ("Continue without components", "E"),
        ("Try again", "C"),
    ],
    "qwen3": [
        ("Qwen3 — Install CustomVoice", "B"), ("Qwen3 — Install Base", "B"),
        ("Qwen3 — Install Both", "B"), ("Qwen3 — Check and repair", "D"),
        ("Qwen3 — Developer tools", "D"), ("Qwen3 — Cancel install", "A"),
        ("Qwen3 — Close", "E"),
    ],
    "cleanup": [
        ("Cleanup — Review Selection", "D"), ("Cleanup — Cancel", "A"),
        ("Cleanup — Confirm deletion", "A"), ("Cleanup — Continue", "E"),
    ],
    "cover_replacement": [
        ("Cover replacement — Confirm replace", "A"),
        ("Cover replacement — Cancel", "A"),
    ],
}

#: Appendix A's own per-surface totals; the grand total is 146.
APPROVED_COUNTS = {
    "tts": 16, "converter": 14, "mp3": 23, "maker": 23, "cover": 13,
    "metadata": 20, "preferences": 6, "navigation": 9,
    "setup": 9, "qwen3": 7, "cleanup": 4, "cover_replacement": 2,
}

#: The ten owner-approved blue Book controls (surface, row label).
BLUE_BOOK_CONTROLS = (
    ("mp3", "◀ Previous Book"), ("mp3", "Next Book ▶"), ("mp3", "Add Book"),
    ("mp3", "Duplicate Book"),
    ("maker", "◀ Previous Book"), ("maker", "Next Book ▶"), ("maker", "Add Book"),
    ("maker", "Duplicate Book"),
    ("metadata", "◀ Previous Book"), ("metadata", "Next Book ▶"),
)


def role_name(letter: str) -> str:
    return appearance.BUTTON_ROLE_LETTERS[letter]


def expected_style(bundle: dict, letter: str) -> str:
    """The style name a row's letter must resolve to in *bundle*."""
    return bundle["styles"][appearance.BUTTON_ROLE_STYLE_KEYS[role_name(letter)]]


def buttons_under(widget) -> list:
    """Every ``ttk.Button`` at or below *widget* (not into other Toplevels)."""
    found = []
    stack = [widget]
    while stack:
        current = stack.pop()
        if isinstance(current, ttk.Button):
            found.append(current)
        for child in current.winfo_children():
            if child.winfo_class() != "Toplevel":
                stack.append(child)
    return found


def audit(surface: str, bundle: dict, widgets: dict, *, container=None,
          extras: dict | None = None, own_normal: dict | None = None) -> None:
    """Prove *widgets* (row label -> live button) is exactly the approved surface.

    * the labels are exactly the inventory's rows for *surface*: none missing,
      none invented;
    * each button draws the style its row's letter names, in *bundle*;
    * when *container* is given, every other button under it must be listed in
      *extras* (text -> reason) and still be plain ``button`` styled: a control the
      inventory does not classify stays normal until the maintainer classifies it;
    * *own_normal* (row -> style name) gives the shell's own normal style for an E row
      the application shell draws itself (its navigation uses ``ACT.*``, not ``Compact.*``).
    """
    rows = dict(INVENTORY[surface])
    missing = sorted(set(rows) - set(widgets))
    invented = sorted(set(widgets) - set(rows))
    assert not missing and not invented, (surface, "missing", missing, "invented", invented)
    for label, widget in widgets.items():
        want = (own_normal or {}).get(label) or expected_style(bundle, rows[label])
        if label in (own_normal or {}):
            assert rows[label] == "E", f"{surface}: {label!r} is not a normal control"
        got = str(widget.cget("style"))
        assert got == want, f"{surface}: {label!r} is {got!r}, approved role {rows[label]} is {want!r}"
    if container is not None:
        claimed = {id(widget) for widget in widgets.values()}
        allowed = dict(extras or {})
        plain = bundle["styles"]["button"]
        strays = [button for button in buttons_under(container) if id(button) not in claimed]
        unknown = [str(button.cget("text")) for button in strays
                   if str(button.cget("text")) not in allowed]
        assert not unknown, f"{surface}: buttons the inventory does not classify: {unknown}"
        for button in strays:
            assert str(button.cget("style")) == plain, (surface, str(button.cget("text")))
