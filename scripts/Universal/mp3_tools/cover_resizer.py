#!/usr/bin/env python3
"""Cover Image Resizer — batch resize cover art to a square (letterbox or crop).

Refactored for the unified launcher: the UI is built by :func:`build_ui` into
any parent frame, so it can live inside the launcher's content panel. Running
this file directly still opens it in its own window via :func:`main`.

Phase 5: Cancel button (cooperative, checked between images) and a remembered
input folder via shared.settings (default = home).

v0.6.0 Drop 2 Phase 4 moved standard output off the source folder: a validated
resize reserves one run under ``<output base>/Cover-Image-Outputs/Cover-Image-N/``
and writes there.

v0.6.0 Drop 2 Phase 5 adds the two source-side modes of Decision 10A, behind
three independent gates. Replacement happens only when **all** of these hold:

1. ``Save beside source images`` is enabled (off on every fresh build);
2. ``Replace original files`` is selected (``Create numbered copies`` is the
   default, and switching the toggle off resets to it);
3. the per-run confirmation is accepted — Cancel is the focused default, Escape
   and closing the window cancel, and nothing about it can be remembered.

Numbered-copy mode writes ``stem-1.ext`` beside each source, never the
unnumbered name, because that name *is* the source. Replacement writes a
complete temporary sibling, validates the finished image, and only then
installs it with a single atomic ``os.replace`` — never delete-then-rename. A
failure before that boundary leaves the original byte-for-byte unchanged and
removes only this operation's own temporary file.

v0.6.1 Plan 4 Phase 2 replaced this panel's hand-written imported-file list with
the shared Plan 3 importing foundation, making the ``ImportedFileManager`` the
one authority on which files are imported and in what order.

v0.6.1 Plan 4 Phase 3 adds Decision 17A's three ways to look at that list —
Details, List and Medium Thumbnails — as :class:`CoverBrowser`. All three are
projections of the same manager snapshot, keyed by occurrence id; previews are
decoded off the main thread for visible tiles only and held in one bounded
cache.

v0.6.1 Plan 4 Phase 4 moves the run itself onto the shared job-control
foundation. One run is frozen once by ``capture_run``; a ``JobController`` owns
its cooperative pause, resume and cancel; a ``JobAdapter`` renders its whole
event stream — controls, progress, the estimate, Summary and Details — and the
shared lock matrix decides what a running job takes ownership of. Standard
output is planned before the worker starts, through ``planning_groups`` and the
three Plan 2 planners, so every occurrence has one collision-free destination
that a later retry re-uses rather than re-invents. The two source-side modes and
their four-gate destructive contract are unchanged.
"""

import gc
import io
import math
import queue
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import appearance
from shared import config as shared_config
from shared import image_capabilities
from shared import job_control
from shared import job_ui
from shared import output_paths
from shared import paths
from shared import settings
from shared.cancellation import ConversionCancelled
from shared.import_coordination import ImportCoordinator
from shared.importing import (
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
    planning_groups,
)
from shared.job_control import (
    FailureLog,
    FailureRecord,
    JobState,
    RunResult,
    capture_run,
)
from shared.output_paths import plan_flat, plan_mirrored, plan_multi_root

from PIL import Image  # needs: pip install pillow

# HEIC/HEIF is optional and is now *probed*, not assumed (Decision 54A). The
# shared seam imports pillow-heif once, registers its Pillow plugin once, and
# reports decode and encode capability separately (Decision 3A). It never
# raises, so a machine without the codec still builds this panel and still
# handles JPG/JPEG/PNG exactly as before. Called here rather than lazily so the
# registration still happens at import, as it did when this was a bare
# try/except.
image_capabilities.heif_capability()

APP_TITLE = "Audiobook Cover Resizer v1.1"
TARGET_SIZE = 1024  # default square size for covers

# settings.json keys (Phase 5)
SOURCE_SIDE_LABEL = "Save beside source images"
MODE_STANDARD = "standard"
ACTION_NUMBERED = "numbered"
ACTION_REPLACE = "replace"

#: Extensions the writer can round-trip in place. Anything else is written as
#: .jpg, so it cannot be replaced under its own name and is refused before the
#: confirmation dialog rather than surprising the user mid-run.
REPLACEABLE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})

TOOL_KEY = "cover"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

KEY_INPUT_DIR = "cover_resizer.input_dir"


# ---------- helpers ----------


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def build_catalog() -> SupportedTypeCatalog:
    """The image types this machine can actually import.

    JPG/JPEG and PNG are always offered — Pillow provides them unconditionally
    and no probe can take them away. HEIC/HEIF is offered only when the
    centralized capability seam says this machine can *decode* it.

    **Decode is the right question here, and only decode.** A build that reads
    HEIC but cannot write it may still import one; the output side refuses
    separately at write time rather than silently substituting a JPEG
    (Decision 3A). Collapsing the two would either hide importable files or
    promise an output this machine cannot produce.

    Decision 16A supplies the rest: one control per type, every offered type
    selected by default — which is what ``ImportOptions.for_catalog`` does with
    ``default_selection()``.
    """
    offered = set(image_capabilities.decodable_suffixes())
    types = [
        SupportedType("jpg", "JPEG image", (".jpg", ".jpeg")),
        SupportedType("png", "PNG image", (".png",)),
    ]
    heif = tuple(s for s in image_capabilities.HEIF_SUFFIXES if s in offered)
    if heif:
        types.append(SupportedType("heic", "HEIC / HEIF image", heif))
    return SupportedTypeCatalog(tuple(types))


def _image_filetypes() -> list[tuple[str, str]]:
    """The import dialog's filter, following the probe rather than a fixed list.

    Offering ``*.heic`` on a machine that cannot decode HEIC is exactly the
    untruthfulness the centralized probe removes: the user picks a file the
    tool then fails to open. JPG/JPEG/PNG are always present.
    """
    patterns = " ".join(f"*{s}" for s in image_capabilities.decodable_suffixes())
    return [("Images", patterns), ("All files", "*.*")]


def written_suffix(suffix: str) -> str:
    """The extension :func:`resize_for_audiobook` will actually write.

    It falls back to ``.jpg`` for anything it cannot encode, so a caller that
    plans a destination has to plan the *written* name, not the source's.
    """
    lowered = (suffix or "").lower()
    return lowered if lowered in REPLACEABLE_SUFFIXES else ".jpg"


def next_version_path(p: Path) -> Path:
    """Return first available Name-1.ext, Name-2.ext, ... in same folder.

    .. deprecated:: v0.6.0 Drop 2 Phase 5

       Superseded by ``output_paths.SourceSidePlanner``, which tracks planned
       names as well as existing ones and keeps separate sequences per source
       directory. Retained only because the standalone entry point and older
       tests still import it; no production path calls it.
    """
    stem = p.stem
    suffix = p.suffix
    parent = p.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


#: Title of the per-run replacement confirmation.
REPLACEMENT_TITLE = "Confirm replacement of original images"


def replacement_message(count: int) -> str:
    """The approved confirmation wording, with singular/plural grammar.

    Kept as a function so the dialog and the suite read the *same* text — a
    test that restates the wording would let the two drift apart, and this is
    the one message a user relies on before an irreversible action.
    """
    plural = "" if count == 1 else "s"
    return (
        f"You selected Replace original files for {count} image{plural}.\n\n"
        "This will permanently replace the selected source image files. "
        "Audiobook Creation Tool cannot undo this action.\n\n"
        "Each replacement is written to a temporary file first and installed "
        "only after successful processing. Files already replaced before a "
        "later failure or cancellation remain replaced.\n\n"
        "Continue?"
    )


def replacement_button_label(count: int) -> str:
    """The destructive button's label — never a bare "OK"."""
    return ("Replace 1 Original File" if count == 1
            else f"Replace {count} Original Files")


def build_replacement_dialog(parent, title: str, message: str, confirm_label: str,
                             theme: dict | None = None):
    """Build the confirmation window and return it, without waiting on it.

    Separated from :func:`_ask_replacement` purely so the suite can inspect the
    wording, the focused widget and each button's effect without driving a
    modal event loop, which is unreliable headlessly. The window carries its own
    ``result`` dict, so a test reads the same answer the modal caller would.

    ``theme`` is the v0.6.6 compact appearance bundle. This is an app-owned
    dialog under the frozen contract, so it follows Light/Dark like the rest of
    the panel that opens it; a raw ``Toplevel``'s own background is the one
    thing a ttk style-name mutation cannot reach, so it is set directly here
    rather than left to repaint itself later.
    """
    answer = {"ok": False}
    win = tk.Toplevel(parent)
    win.title(title)
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    win.resizable(False, False)
    colors = (theme or {}).get("colors") or {}
    if colors:
        try:
            win.configure(background=colors["window"])
        except tk.TclError:
            pass

    body = ttk.Frame(win, padding=16, style=job_ui.style_name(theme, "window"))
    body.pack(fill=tk.BOTH, expand=True)
    label = ttk.Label(body, text=message, wraplength=460, justify="left",
                      style=job_ui.style_name(theme, "label"))
    label.pack(anchor="w")
    win.label_message = label

    actions = ttk.Frame(body, style=job_ui.style_name(theme, "window"))
    actions.pack(anchor="e", pady=(16, 0))

    def cancel(*_a):
        answer["ok"] = False
        win.destroy()

    def confirm(*_a):
        answer["ok"] = True
        win.destroy()

    btn_cancel = ttk.Button(actions, text="Cancel", command=cancel,
                            style=job_ui.style_name(theme, "button"))
    btn_cancel.pack(side=tk.RIGHT)
    btn_confirm = ttk.Button(actions, text=confirm_label, command=confirm,
                             style=job_ui.style_name(theme, "danger_button"))
    btn_confirm.pack(side=tk.RIGHT, padx=(0, 8))
    # Exposed so a headless test can drive the dialog without a display server.
    win.btn_cancel = btn_cancel
    win.btn_confirm = btn_confirm
    win.result = answer

    win.protocol("WM_DELETE_WINDOW", cancel)
    win.bind("<Escape>", cancel)
    win.cancel = cancel
    # Cancel is the initial focus, so Return activates the safe answer. Recorded
    # explicitly as well: Tk defers focus on an unmapped window, so the intent
    # has to be inspectable without a mapped display.
    win.default_widget = btn_cancel
    btn_cancel.focus_set()
    return win


def _ask_replacement(parent, title: str, message: str, confirm_label: str,
                     theme: dict | None = None) -> bool:
    """A modal confirm whose safe answer is the default and holds focus.

    Deliberately not ``messagebox.askyesno``: the destructive action needs its
    own explicit label ("Replace 3 Original Files"), and Cancel must hold focus
    so a stray Enter cannot start a replacement. Escape and the window close
    both cancel, and the window is rebuilt for every run — there is nothing to
    remember, suppress or reuse.
    """
    win = build_replacement_dialog(parent, title, message, confirm_label, theme=theme)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return bool(win.result["ok"])


# ---------- image logic ----------


def resize_for_audiobook(in_path: Path, out_path: Path, size: int, letterbox: bool):
    """
    Always keep full image visible when letterbox=True:
      - Scale so the LONG side == size
      - Paste on a square canvas with bars if needed.
    """
    img = Image.open(in_path).convert("RGB")
    w, h = img.size

    if letterbox:
        scale = size / max(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGB", (size, size), color=(0, 0, 0))
        offset_x = (size - new_w) // 2
        offset_y = (size - new_h) // 2
        canvas.paste(img, (offset_x, offset_y))
        img = canvas
    else:
        scale = size / min(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - size) // 2
        upper = (new_h - size) // 2
        right = left + size
        lower = upper + size
        img = img.crop((left, upper, right, lower))

    ext = out_path.suffix.lower()
    save_kwargs = {}

    if ext in [".jpg", ".jpeg"]:
        save_kwargs = {"format": "JPEG", "quality": 95}
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "compress_level": 6}
    elif ext in image_capabilities.HEIF_SUFFIXES:
        # Decision 3A: HEIC/HEIF in, HEIC/HEIF out. If this machine cannot
        # encode HEIF the item fails here with a truthful message; it is never
        # quietly written as a .jpg. Under source-side replacement that
        # substitution would silently change an original's format, so the
        # refusal has to happen before anything is written.
        image_capabilities.require_encoder(ext)
        save_kwargs = {"format": "HEIF", "quality": 95}
    else:
        out_path = out_path.with_suffix(".jpg")
        save_kwargs = {"format": "JPEG", "quality": 95}

    img.save(out_path, **save_kwargs)
    return out_path


# ---------- the imported-image browser (Decision 17A) ----------
#
# Three ways to look at one list. Details is the default because Decision 17A
# made thumbnails opt-in: decoding a large import is slow, so the view that
# costs nothing is the one a user lands on.
#
# Everything below is *presentation*. The ImportedFileManager that Phase 2 made
# the single source of truth stays the single source of truth: every view reads
# its snapshot, every row and tile is keyed by occurrence id, and no view sorts,
# filters or caches a rival copy of the list.


VIEW_DETAILS = "details"
VIEW_LIST = "list"
VIEW_THUMBNAILS = "thumbnails"

#: (view id, button label), in the order the switch offers them. Details first.
BROWSER_VIEWS = (
    (VIEW_DETAILS, "Details"),
    (VIEW_LIST, "List"),
    (VIEW_THUMBNAILS, "Medium Thumbnails"),
)
VIEW_IDS = tuple(view for view, _label in BROWSER_VIEWS)
DEFAULT_VIEW = VIEW_DETAILS

#: (column key, heading, width). The five fields Decision 17A names, in order.
DETAILS_COLUMNS = (
    ("filename", "Filename", 160),
    ("dimensions", "Dimensions", 85),
    ("format", "Format", 60),
    ("size", "File size", 70),
    ("folder", "Folder", 160),
)

#: "Medium", in pixels: the long side of a preview tile's image.
THUMBNAIL_SIZE = 128
#: Space around a tile's image, and room under it for the filename.
THUMBNAIL_PADDING = 10
THUMBNAIL_LABEL_HEIGHT = 18

#: The cache's explicit, finite bound — the number of decoded previews held at
#: once, not a byte budget, because eviction has to be deterministic and a byte
#: budget would depend on the images a user happened to import. At 128px RGB
#: that is a few megabytes, and it is deliberately larger than one screenful so
#: scrolling back up does not re-decode.
THUMBNAIL_CACHE_LIMIT = 96

#: The hard cap on how many items one refresh may ask the decoder for. It is
#: what makes "visible only" true rather than merely intended: an unmapped or
#: freshly built widget honestly answers "all of it" for its own scroll extent,
#: and without this cap a 5,000-image import would decode 5,000 previews.
MAX_VISIBLE_ITEMS = 60

#: How long :meth:`CoverBrowser.close` waits for one decoder batch to finish.
#: Bounded rather than indefinite, and bounded rather than abandoned: a thread
#: left running past teardown outlives the widgets it was decoding for.
WORKER_JOIN_TIMEOUT = 5.0

PENDING_TEXT = "…"
UNAVAILABLE_TEXT = "Unavailable"

FACTS_PENDING = "pending"
FACTS_READY = "ready"
FACTS_UNAVAILABLE = "unavailable"

#: Selection modifiers. ``toggle`` is Ctrl on Windows and Linux and Command on
#: macOS; ``extend`` is Shift.
SELECT_REPLACE = "replace"
SELECT_TOGGLE = "toggle"
SELECT_EXTEND = "extend"

#: Keyboard actions, and the sequences that raise them in every view.
KEY_BINDINGS = (
    ("<Up>", "up"),
    ("<Down>", "down"),
    ("<Left>", "up"),
    ("<Right>", "down"),
    ("<Shift-Up>", "extend_up"),
    ("<Shift-Down>", "extend_down"),
    ("<Shift-Left>", "extend_up"),
    ("<Shift-Right>", "extend_down"),
    ("<Home>", "home"),
    ("<End>", "end"),
    ("<Control-a>", "select_all"),
    ("<Command-a>", "select_all"),
)

#: Click sequences, and the modifier each one means.
CLICK_BINDINGS = (
    ("<Button-1>", SELECT_REPLACE),
    ("<Control-Button-1>", SELECT_TOGGLE),
    ("<Command-Button-1>", SELECT_TOGGLE),
    ("<Shift-Button-1>", SELECT_EXTEND),
)


def format_file_size(size: object) -> str:
    """A human file size, or a truthful ``Unavailable`` for anything unusable."""
    try:
        value = int(size)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return UNAVAILABLE_TEXT
    if value < 0:
        return UNAVAILABLE_TEXT
    if value < 1024:
        return f"{value} B"
    scaled = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        scaled /= 1024.0
        if scaled < 1024.0 or unit == "TB":
            return f"{scaled:.1f} {unit}"
    return UNAVAILABLE_TEXT  # pragma: no cover - the loop always returns


@dataclass(frozen=True)
class ImageFacts:
    """The five Details fields for one occurrence, and how much of it is real.

    ``filename`` and ``folder`` come from the path and are therefore always
    truthful, even for a file that cannot be opened. The other three are read
    from disk, so they carry a state: pending until the decoder answers, then
    either ready or unavailable. Nothing here ever guesses.
    """

    filename: str
    folder: str
    dimensions: str = PENDING_TEXT
    image_format: str = PENDING_TEXT
    size: str = PENDING_TEXT
    state: str = FACTS_PENDING
    detail: str = ""

    @property
    def columns(self) -> tuple[str, str, str, str, str]:
        """The Details row, in :data:`DETAILS_COLUMNS` order."""
        return (self.filename, self.dimensions, self.image_format,
                self.size, self.folder)


def path_facts(path: Path) -> ImageFacts:
    """What a path alone knows: the name and the folder. The rest is pending."""
    resolved = Path(path)
    return ImageFacts(filename=resolved.name, folder=str(resolved.parent))


def read_image_facts(path: Path) -> ImageFacts:
    """Read one image's Details fields. Never raises, and never writes.

    Runs on the decoder thread, so it touches no Tk object. A file that has
    been deleted, replaced by a directory, truncated or was never an image at
    all comes back marked unavailable with the reason kept for the log — it is
    never dropped from the list and never repaired.
    """
    resolved = Path(path)
    filename, folder = resolved.name, str(resolved.parent)
    try:
        size_text = format_file_size(resolved.stat().st_size)
    except OSError as exc:
        return ImageFacts(filename, folder, UNAVAILABLE_TEXT, UNAVAILABLE_TEXT,
                          UNAVAILABLE_TEXT, FACTS_UNAVAILABLE, str(exc))
    try:
        with Image.open(resolved) as img:
            width, height = img.size
            fmt = (img.format or "").upper() or UNAVAILABLE_TEXT
    except Exception as exc:  # noqa: BLE001 - any decoder failure is the same answer
        return ImageFacts(filename, folder, UNAVAILABLE_TEXT, UNAVAILABLE_TEXT,
                          size_text, FACTS_UNAVAILABLE, str(exc))
    return ImageFacts(filename, folder, f"{width} × {height}", fmt, size_text,
                      FACTS_READY)


def encode_thumbnail(path: Path, size: int) -> bytes | None:
    """A medium preview as PNG bytes, or ``None`` if the image cannot be read.

    PNG bytes rather than a Tk image on purpose: this runs on a worker thread,
    and plain bytes are the only thing allowed to cross the queue. ``draft``
    lets the JPEG decoder skip most of the work for a preview this small.
    """
    try:
        with Image.open(path) as img:
            img.draft("RGB", (size, size))
            preview = img.convert("RGB")
            preview.thumbnail((size, size), Image.LANCZOS)
            buffer = io.BytesIO()
            preview.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception:  # noqa: BLE001 - an unreadable image is a placeholder, not a crash
        return None


@dataclass(frozen=True)
class PreviewRequest:
    """One item's metadata, and optionally its preview, asked for at a revision."""

    occurrence_id: str
    path: Path
    revision: int
    want_image: bool
    size: int = THUMBNAIL_SIZE


@dataclass(frozen=True)
class PreviewResult:
    """What the decoder answers. Plain data only — no widget, no Tk image."""

    occurrence_id: str
    revision: int
    facts: ImageFacts
    image_data: bytes | None = None


def decode_previews(requests, publish) -> None:
    """The decoder body. Reads images, publishes plain data, creates no Tk object.

    Kept a module-level function rather than a method so the thing that runs off
    the main thread cannot reach a widget even by accident: it is handed the
    requests and a publisher and has no other collaborator.
    """
    for request in requests:
        facts = read_image_facts(request.path)
        data = None
        if request.want_image and facts.state == FACTS_READY:
            data = encode_thumbnail(request.path, request.size)
        publish(PreviewResult(request.occurrence_id, request.revision, facts, data))


def run_previews_in_thread(requests, publish) -> threading.Thread:
    """The production runner: one short-lived daemon thread per batch.

    Batches are already capped at :data:`MAX_VISIBLE_ITEMS`, so this cannot
    accumulate threads the way a per-item thread would, and each one ends when
    its batch does.
    """
    thread = threading.Thread(
        target=decode_previews, args=(tuple(requests), publish),
        name="cover-previews", daemon=True)
    thread.start()
    return thread


def resolve_selection(order, selected, anchor, target, modifier):
    """Compute a new selection and anchor. Pure, and ordered by *order*.

    The whole point of doing this here rather than leaving it to each widget is
    that all three views then behave identically, and that ranges and anchors
    follow **manager order** rather than whatever order a widget happens to hold
    its rows in. A target that is no longer in the list changes nothing.
    """
    positions = {occurrence: index for index, occurrence in enumerate(order)}
    current = set(selected)
    if target not in positions:
        return tuple(o for o in order if o in current), anchor

    if modifier == SELECT_TOGGLE:
        if target in current:
            current.discard(target)
        else:
            current.add(target)
        new_anchor = target
    elif modifier == SELECT_EXTEND:
        start = positions[anchor] if anchor in positions else positions[target]
        stop = positions[target]
        low, high = (start, stop) if start <= stop else (stop, start)
        current = set(order[low:high + 1])
        new_anchor = anchor if anchor in positions else target
    else:
        current = {target}
        new_anchor = target
    return tuple(o for o in order if o in current), new_anchor


def resolve_key(order, selected, anchor, cursor, action):
    """Keyboard navigation over *order*. Returns (selection, anchor, cursor).

    The cursor is the item the keyboard is standing on; plain arrows move it and
    replace the selection, Shift-arrows move it and extend from the anchor, and
    nothing wraps at either end.
    """
    if not order:
        return (), anchor, cursor
    positions = {occurrence: index for index, occurrence in enumerate(order)}
    if action == "select_all":
        return (tuple(order),
                anchor if anchor in positions else order[0],
                cursor if cursor in positions else order[-1])

    index = positions.get(cursor)
    if index is None:
        index = positions.get(selected[-1], 0) if selected else 0
    if action in ("up", "extend_up"):
        index = max(0, index - 1)
    elif action in ("down", "extend_down"):
        index = min(len(order) - 1, index + 1)
    elif action == "home":
        index = 0
    elif action == "end":
        index = len(order) - 1
    else:
        raise ValueError(f"unknown key action {action!r}")

    target = order[index]
    modifier = (SELECT_EXTEND if action in ("extend_up", "extend_down")
                else SELECT_REPLACE)
    selection, new_anchor = resolve_selection(order, selected, anchor, target, modifier)
    return selection, new_anchor, target


def visible_span(first, last, count, *, maximum=MAX_VISIBLE_ITEMS):
    """Turn a pair of Tk scroll fractions into an index range, hard-capped.

    The cap is the load-bearing part. A widget that has not been mapped reports
    that all of its content is visible, which is true of its own extent and
    useless as a decoding budget, so the range is clamped to *maximum* items no
    matter what the widget says.
    """
    if count <= 0:
        return (0, 0)
    start = max(0, min(count - 1, int(math.floor(float(first) * count))))
    stop = max(start + 1, min(count, int(math.ceil(float(last) * count))))
    return (start, min(stop, start + max(1, int(maximum))))


class ThumbnailCache:
    """A bounded, least-recently-used cache of Tk images, keyed by occurrence id.

    It is the **only** owner of a decoded preview. Nothing else keeps a
    reference, so dropping an entry here is what releases the underlying Tk
    image — which is why eviction, :meth:`retain` and :meth:`clear` are the
    whole lifetime story and there is no second place to look.
    """

    __slots__ = ("_limit", "_items", "_evicted")

    def __init__(self, *, limit: int = THUMBNAIL_CACHE_LIMIT) -> None:
        bound = int(limit)
        if bound < 1:
            raise ValueError(f"a thumbnail cache needs a positive bound, got {limit!r}")
        self._limit = bound
        self._items: "OrderedDict[str, object]" = OrderedDict()
        self._evicted = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def evicted(self) -> int:
        """How many entries have been dropped to stay inside the bound."""
        return self._evicted

    @property
    def keys(self) -> tuple[str, ...]:
        """Least recently used first, so eviction order is inspectable."""
        return tuple(self._items)

    def peek(self, occurrence_id: str):
        """Read without promoting — for rendering, which must not reorder use."""
        return self._items.get(occurrence_id)

    def get(self, occurrence_id: str):
        image = self._items.get(occurrence_id)
        if image is not None:
            self._items.move_to_end(occurrence_id)
        return image

    def put(self, occurrence_id: str, image: object) -> tuple[str, ...]:
        """Store *image*, returning whatever had to be evicted to make room."""
        self._items.pop(occurrence_id, None)
        self._items[occurrence_id] = image
        evicted = []
        while len(self._items) > self._limit:
            key, _dropped = self._items.popitem(last=False)
            evicted.append(key)
            self._evicted += 1
        return tuple(evicted)

    def discard(self, occurrence_id: str) -> bool:
        return self._items.pop(occurrence_id, None) is not None

    def retain(self, occurrence_ids) -> tuple[str, ...]:
        """Drop every entry that is not in *occurrence_ids*. Returns what went."""
        keep = set(occurrence_ids)
        dropped = tuple(key for key in self._items if key not in keep)
        for key in dropped:
            self._items.pop(key, None)
        return dropped

    def clear(self) -> None:
        self._items.clear()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ThumbnailCache(size={len(self._items)}, limit={self._limit})"


class CoverBrowser:
    """Decision 17A's three views of the imported list.

    Details is the default and shows filename, dimensions, format, file size and
    folder. List is the same occurrences as plain paths. Medium Thumbnails draws
    them as tiles. Switching between them is presentation and nothing else: it
    reads the manager again, so order and selection survive by construction
    rather than by being copied across.

    Three rules hold everywhere:

    * **the manager decides.** Rows and tiles are keyed by occurrence id, the
      snapshot supplies the order, and a click ends up in ``manager.select``.
      Two deliberate duplicates of one path are two independently selectable
      rows because they are two occurrence ids.
    * **decoding is lazy and bounded.** Only the visible span is asked for, that
      span is capped, previews are decoded off the main thread, and the images
      live in one bounded cache that is their only owner.
    * **nothing schedules itself.** :meth:`drain` is registered on the panel's
      existing pump. There is no second ``after`` chain here.
    """

    def __init__(
        self,
        parent: tk.Misc,
        manager: ImportedFileManager,
        *,
        pump: job_ui.MainThreadPump,
        thread_id: int | None = None,
        runner=None,
        viewport=None,
        thumbnail_size: int = THUMBNAIL_SIZE,
        cache_limit: int | None = None,
        max_visible: int = MAX_VISIBLE_ITEMS,
        height: int = 8,
        on_selection_change=None,
        theme: dict | None = None,
    ) -> None:
        self._guard = job_ui.MainThreadGuard(thread_id)
        self._manager = manager
        self._pump = pump
        self._theme = theme
        self._colors = (theme or {}).get("colors") or {}
        self._runner = run_previews_in_thread if runner is None else runner
        self._viewport = viewport
        self._thumbnail_size = int(thumbnail_size)
        self._max_visible = max(1, int(max_visible))
        self._on_selection_change = on_selection_change

        self._closed = False
        self._locked = False
        self._view = DEFAULT_VIEW
        self._order: tuple[str, ...] = ()
        self._sources: dict[str, Path] = {}
        self._facts: dict[str, ImageFacts] = {}
        self._inflight: set[str] = set()
        self._results: queue.Queue = queue.Queue()
        self._rendered_revision = -1
        self._rendered_selection: tuple[str, ...] = ()
        #: Last span hydrated, so repeated scroll callbacks are near-free.
        self._rendered_span: tuple[int, int] | None = None
        #: Re-entrancy guard: repainting tiles re-fires ``yscrollcommand``.
        self._scrolling = False
        self._anchor: str | None = None
        self._cursor: str | None = None
        self._tiles: tuple[str, ...] = ()
        self._tile_selection: tuple[str, ...] = ()
        self._workers: list[threading.Thread] = []

        self.cache = ThumbnailCache(
            limit=THUMBNAIL_CACHE_LIMIT if cache_limit is None else cache_limit)

        # --- widgets ------------------------------------------------------- #
        # A plain frame, not a bordered box of its own: since v0.6.6 the browser
        # lives inside the panel's "1. Sources" section, and TTS -- the visual
        # reference -- never nests one bordered section inside another.
        self.frame = ttk.Frame(parent, style=job_ui.style_name(theme, "surface"))

        switch = ttk.Frame(self.frame, style=job_ui.style_name(theme, "surface"))
        switch.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        # The three labelled choices name themselves; a separate "View:"
        # caption would only make this row -- and so Sources -- wider.
        self.var_view = tk.StringVar(value=DEFAULT_VIEW)
        self.view_buttons: dict[str, ttk.Radiobutton] = {}
        for index, (view_id, label) in enumerate(BROWSER_VIEWS):
            button = ttk.Radiobutton(
                switch, text=label, value=view_id, variable=self.var_view,
                command=lambda chosen=view_id: self.set_view(chosen),
                style=job_ui.style_name(theme, "radiobutton"))
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 10, 0))
            self.view_buttons[view_id] = button

        self.body = ttk.Frame(self.frame, style=job_ui.style_name(theme, "surface"))
        self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)

        self._pages: dict[str, ttk.Frame] = {}
        self.details = self._treeview(
            VIEW_DETAILS,
            [key for key, _heading, _width in DETAILS_COLUMNS], height)
        for key, heading, width in DETAILS_COLUMNS:
            self.details.heading(key, text=heading)
            self.details.column(key, width=width, stretch=(key == "folder"))

        self.simple = self._treeview(VIEW_LIST, ["path"], height)
        self.simple.heading("path", text="File")
        self.simple.column("path", width=300, stretch=True)

        self.canvas = self._tile_canvas(VIEW_THUMBNAILS)

        for widget in (self.details, self.simple, self.canvas):
            self._bind_surface(widget)

        self._pages[DEFAULT_VIEW].tkraise()
        self._pump.add_drain(self.drain)
        self.placeholder = self._build_placeholder()
        self.refresh()

    # -- construction helpers ---------------------------------------------- #

    def _page(self, view_id: str) -> ttk.Frame:
        page = ttk.Frame(self.body, style=job_ui.style_name(self._theme, "surface"))
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        self._pages[view_id] = page
        return page

    def _treeview(self, view_id: str, columns, height: int) -> ttk.Treeview:
        """A row view. ``selectmode="none"`` because selection is decided here.

        Letting Tk own it would give three views three sets of rules and would
        anchor ranges on widget order; one engine gives all three the same
        behaviour, anchored on the manager.
        """
        page = self._page(view_id)
        tree = ttk.Treeview(page, columns=list(columns), show="headings",
                            selectmode="none", height=height,
                            style=job_ui.style_name(self._theme, "treeview"))
        tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(page, orient="vertical", command=tree.yview,
                            style=job_ui.style_name(self._theme, "vscrollbar"))
        bar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=self._scroll_reporter(bar))
        return tree

    def _tile_canvas(self, view_id: str) -> tk.Canvas:
        page = self._page(view_id)
        canvas = tk.Canvas(page, highlightthickness=0, takefocus=True)
        job_ui.style_tk_widget(canvas, self._theme, "field")
        canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview,
                            style=job_ui.style_name(self._theme, "vscrollbar"))
        bar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=self._scroll_reporter(bar))
        # ``ttk.Treeview`` gets <MouseWheel> from its Tk *class* bindings, which is
        # why Details and List always scrolled. ``tk.Canvas`` has no such class
        # binding, so without this the wheel did nothing over the thumbnail
        # viewport while the scrollbar worked — exactly the Block 1 report. Bound
        # on the canvas itself, never with ``bind_all``: a global binding would
        # steal the wheel from every other panel in the launcher. The tiles are
        # canvas *items*, not child widgets, so this one binding covers the whole
        # viewport including the images and their labels.
        canvas.bind("<MouseWheel>", self._wheel_handler(canvas), add="+")
        for button, direction in (("<Button-4>", -1), ("<Button-5>", 1)):
            canvas.bind(button, self._wheel_handler(canvas, units=direction),
                        add="+")
        return canvas

    def _scroll_reporter(self, bar):
        """Keep the scrollbar in step, and tell the browser the viewport moved.

        Hooking ``yscrollcommand`` catches **every** way a view can scroll — the
        wheel, dragging the scrollbar, keyboard navigation, a programmatic
        ``yview`` — from one place per view, instead of chasing each input.
        """
        def report(first, last):
            bar.set(first, last)
            self.notify_scrolled()
        return report

    def _wheel_handler(self, canvas, units: int | None = None):
        def handle(event):
            if units is not None:
                step = units
            else:
                # Windows reports multiples of 120; macOS reports small integers.
                delta = int(event.delta)
                step = -(delta // 120) if abs(delta) >= 120 else -delta
            if step:
                canvas.yview_scroll(step, "units")
            return "break"
        return handle

    def _build_placeholder(self) -> tk.PhotoImage:
        """One shared image for everything that cannot be decoded.

        Built once and held for the browser's life, so a hundred unreadable
        files cost one Tk image between them rather than a hundred.
        """
        side = self._thumbnail_size
        canvas = Image.new("RGB", (side, side), (232, 232, 232))
        mark = Image.new("RGB", (side // 3, side // 3), (176, 176, 176))
        canvas.paste(mark, (side // 3, side // 3))
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return tk.PhotoImage(data=buffer.getvalue(), master=self.frame)

    def _bind_surface(self, widget) -> None:
        for sequence, modifier in CLICK_BINDINGS:
            widget.bind(sequence, self._click_handler(widget, modifier), add="+")
        for sequence, action in KEY_BINDINGS:
            widget.bind(sequence, self._key_handler(action), add="+")

    def _click_handler(self, widget, modifier):
        def handle(event):
            self._focus_active()
            occurrence_id = self._locate(widget, event)
            if occurrence_id is not None:
                self.click(occurrence_id, modifier)
            return "break"
        return handle

    def _focus_active(self) -> None:
        """Give the keyboard to whichever view was just clicked."""
        try:
            self.surface(self._view).focus_set()
        except tk.TclError:  # pragma: no cover - a destroyed widget
            pass

    def _key_handler(self, action: str):
        def handle(_event):
            self.key(action)
            return "break"
        return handle

    def _locate(self, widget, event) -> str | None:
        """Which occurrence the pointer is over, in whichever view it landed in."""
        if widget is self.canvas:
            return self._tile_at(event.x, self.canvas.canvasy(event.y))
        row = widget.identify_row(event.y)
        return row or None

    # -- reading ------------------------------------------------------------ #

    @property
    def guard(self) -> job_ui.MainThreadGuard:
        return self._guard

    @property
    def manager(self) -> ImportedFileManager:
        return self._manager

    @property
    def view(self) -> str:
        return self._view

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def order(self) -> tuple[str, ...]:
        """The occurrence ids this browser is projecting, in manager order."""
        return self._order

    @property
    def selection(self) -> tuple[str, ...]:
        return self._manager.selection

    def surface(self, view_id: str):
        """The widget that draws *view_id*. Exposed so a test can inspect bindings."""
        return {VIEW_DETAILS: self.details, VIEW_LIST: self.simple,
                VIEW_THUMBNAILS: self.canvas}[view_id]

    def facts_for(self, occurrence_id: str) -> ImageFacts | None:
        return self._facts.get(occurrence_id)

    def details_row(self, occurrence_id: str) -> tuple[str, ...]:
        """The five values the Details view is showing for one occurrence."""
        try:
            return tuple(str(value) for value in self.details.item(occurrence_id, "values"))
        except tk.TclError:
            return ()

    def rendered_ids(self) -> tuple[str, ...]:
        """What the active view has actually laid out.

        For the two row views that is every occurrence. For tiles it is the
        visible band, because drawing five thousand tiles to show twenty is the
        cost Decision 17A was avoiding.
        """
        if self._closed:
            return ()
        if self._view == VIEW_THUMBNAILS:
            return self._tiles
        widget = self.surface(self._view)
        try:
            return tuple(widget.get_children(""))
        except tk.TclError:  # pragma: no cover - a destroyed widget
            return ()

    def painted_selection(self) -> tuple[str, ...]:
        """The selection the active view is actually showing, in manager order."""
        if self._closed:
            return ()
        if self._view == VIEW_THUMBNAILS:
            shown = set(self._tile_selection)
        else:
            try:
                shown = set(self.surface(self._view).selection())
            except tk.TclError:  # pragma: no cover - a destroyed widget
                return ()
        return tuple(o for o in self._order if o in shown)

    def tile_image(self, occurrence_id: str):
        """The image a tile is showing: its decoded preview, or the placeholder."""
        cached = self.cache.peek(occurrence_id)
        return self.placeholder if cached is None else cached

    def visible_range(self) -> tuple[int, int]:
        """Which indices the active view is showing, capped."""
        count = len(self._order)
        if self._viewport is not None:
            first, last = self._viewport(self._view, count)
        else:
            first, last = self._scroll_fractions()
        return visible_span(first, last, count, maximum=self._max_visible)

    # -- rendering ---------------------------------------------------------- #

    def set_view(self, view_id: str) -> str:
        """Show a different view. Presentation only — the manager is not touched."""
        self._guard.require("set_view")
        if view_id not in VIEW_IDS:
            raise ValueError(f"unknown view {view_id!r}; expected one of {VIEW_IDS}")
        if self._closed:
            return self._view
        self._view = view_id
        if self.var_view.get() != view_id:
            self.var_view.set(view_id)
        self._pages[view_id].tkraise()
        self.refresh()
        return self._view

    def refresh(self) -> tuple[str, ...]:
        """Rebuild the active view from the manager, and ask for what is visible."""
        self._guard.require("refresh")
        if self._closed:
            return ()
        snapshot = self._manager.snapshot()
        self._order = snapshot.occurrence_ids
        self._sources = {entry.occurrence_id: entry.path for entry in snapshot.files}
        self._rendered_revision = snapshot.revision.value
        live = set(self._order)
        # A removed occurrence releases its image and its metadata here, which is
        # the only place either is dropped for that reason.
        self.cache.retain(self._order)
        self._facts = {key: value for key, value in self._facts.items() if key in live}
        if self._anchor not in live:
            self._anchor = None
        if self._cursor not in live:
            self._cursor = None

        self._render_rows(snapshot)
        self._rendered_selection = self._manager.selection
        self._paint_selection()
        self._rendered_span = self.visible_range()
        self.request_visible()
        self._consume()
        return self._order

    def apply_appearance(self, theme: dict | None) -> None:
        """Re-color the raw ``Canvas`` in place, and redraw its tiles.

        Every ``ttk``-styled widget above (the ``Radiobutton``\\ s, the
        ``Treeview``\\ s, the frames) already repainted itself the moment
        ``shared.appearance`` reconfigured the ``Compact.*`` styles the
        constructor named. The thumbnail canvas is classic Tk and its tile
        colors are baked into each ``create_rectangle``/``create_text`` call at
        draw time, so both need this explicit call.
        """
        self._guard.require("apply_appearance")
        self._theme = theme
        self._colors = (theme or {}).get("colors") or {}
        if self._closed:
            return
        job_ui.style_tk_widget(self.canvas, theme, "field")
        self._render_tiles()

    def _render_rows(self, snapshot) -> None:
        if self._view == VIEW_THUMBNAILS:
            self._render_tiles()
            return
        tree = self.surface(self._view)
        try:
            tree.delete(*tree.get_children(""))
            for entry in snapshot.files:
                facts = self._facts.get(entry.occurrence_id) or path_facts(entry.path)
                values = (facts.columns if self._view == VIEW_DETAILS
                          else (str(entry.path),))
                tree.insert("", "end", iid=entry.occurrence_id, values=values)
        except tk.TclError:  # pragma: no cover - a destroyed widget
            return

    def _render_one(self, occurrence_id: str) -> None:
        """Update one row or tile in place, after its facts or preview arrived."""
        if self._view == VIEW_THUMBNAILS:
            self._render_tiles()
            return
        if self._view != VIEW_DETAILS:
            return
        facts = self._facts.get(occurrence_id)
        if facts is None:
            return
        try:
            self.details.item(occurrence_id, values=facts.columns)
        except tk.TclError:  # pragma: no cover - a destroyed widget
            pass

    def _tile_geometry(self) -> tuple[int, int, int]:
        cell = self._thumbnail_size + THUMBNAIL_PADDING * 2
        height = cell + THUMBNAIL_LABEL_HEIGHT
        try:
            width = max(1, int(self.canvas.winfo_width()))
        except tk.TclError:  # pragma: no cover - a destroyed widget
            width = cell
        return (max(1, width // cell), cell, height)

    def _render_tiles(self) -> None:
        columns, cell, cell_height = self._tile_geometry()
        try:
            self.canvas.delete("all")
        except tk.TclError:  # pragma: no cover - a destroyed widget
            return
        start, stop = self.visible_range()
        visible = self._order[start:stop]
        selected = set(self._manager.selection)
        painted: list[str] = []
        for offset, occurrence_id in enumerate(visible):
            index = start + offset
            row, column = divmod(index, columns)
            left = column * cell
            top = row * cell_height
            if occurrence_id in selected:
                self.canvas.create_rectangle(
                    left + 2, top + 2, left + cell - 2, top + cell_height - 2,
                    fill=self._colors.get("selection", "#cde3f7"),
                    outline=self._colors.get("accent", "#3b7dd8"),
                    tags=("tile", occurrence_id))
                painted.append(occurrence_id)
            self.canvas.create_image(
                left + cell // 2, top + cell // 2,
                image=self.tile_image(occurrence_id),
                tags=("tile", occurrence_id))
            source = self._sources.get(occurrence_id)
            if source is not None:
                self.canvas.create_text(
                    left + cell // 2, top + cell_height - THUMBNAIL_LABEL_HEIGHT // 2,
                    text=source.name, width=cell - 6, tags=("tile", occurrence_id),
                    fill=self._colors.get("text", "black"))
        self._tiles = tuple(visible)
        self._tile_selection = tuple(painted)
        rows = math.ceil(len(self._order) / columns) if self._order else 0
        self.canvas.configure(
            scrollregion=(0, 0, columns * cell, max(1, rows * cell_height)))

    def _tile_at(self, x: float, y: float) -> str | None:
        columns, cell, cell_height = self._tile_geometry()
        if x < 0 or y < 0:
            return None
        column, row = int(x // cell), int(y // cell_height)
        if column >= columns:
            return None
        index = row * columns + column
        if 0 <= index < len(self._order):
            return self._order[index]
        return None

    def _paint_selection(self) -> None:
        selected = tuple(
            o for o in self._order if o in set(self._manager.selection))
        if self._view == VIEW_THUMBNAILS:
            self._render_tiles()
            return
        widget = self.surface(self._view)
        try:
            widget.selection_set(selected)
        except tk.TclError:  # pragma: no cover - a destroyed widget
            pass

    # -- selection ---------------------------------------------------------- #

    def click(self, occurrence_id: str, modifier: str = SELECT_REPLACE):
        """The one selection entry point every binding in every view goes through."""
        self._guard.require("click")
        if self._closed or self._locked:
            return self._manager.selection
        selection, anchor = resolve_selection(
            self._order, self._manager.selection, self._anchor, occurrence_id, modifier)
        self._anchor = anchor
        if occurrence_id in set(self._order):
            self._cursor = occurrence_id
        return self._commit_selection(selection)

    def key(self, action: str):
        """Keyboard navigation and selection, identical in all three views."""
        self._guard.require("key")
        if self._closed or self._locked:
            return self._manager.selection
        selection, anchor, cursor = resolve_key(
            self._order, self._manager.selection, self._anchor, self._cursor, action)
        self._anchor, self._cursor = anchor, cursor
        return self._commit_selection(selection)

    def _commit_selection(self, selection):
        """The manager records it; the widget only shows it."""
        applied = self._manager.select(selection)
        self._rendered_selection = applied
        self._paint_selection()
        if self._on_selection_change is not None:
            self._on_selection_change(applied)
        return applied

    def set_locked(self, locked: bool) -> None:
        """Lock selection while a resize runs. Switching view stays available.

        Looking is not mutating: a view switch reads the manager and changes
        nothing, so blinding the user during a run would buy no safety.
        """
        self._guard.require("set_locked")
        self._locked = bool(locked)
        # The row views also *look* locked, so a click that does nothing is not
        # mistaken for a click that failed.
        flag = "disabled" if self._locked else "!disabled"
        for widget in (self.details, self.simple):
            try:
                widget.state([flag])
            except tk.TclError:  # pragma: no cover - a destroyed widget
                pass

    # -- the decoder, and the one pump -------------------------------------- #

    def notify_scrolled(self) -> bool:
        """The viewport moved: hydrate whatever is now on screen.

        Before this existed, ``request_visible()`` was reachable only from
        ``refresh()`` — construction, a view switch, or a manager *revision*
        change. Scrolling is none of those, so the visible span was computed once
        and never again: with 34 images the first screenful hydrated and every row
        below it kept its ``…`` for good, and the thumbnail canvas showed blank
        space because ``_render_tiles`` paints only the visible span while sizing
        ``scrollregion`` for every row.

        Cheap on the common path. The span is compared against the last one
        rendered and an unchanged span returns immediately, so the many
        ``yscrollcommand`` callbacks a single drag produces cost one tuple compare
        each. Already-decoded occurrences are skipped by ``request_visible``
        itself, so hydration stays lazy and nothing is decoded twice.

        Returns True when this call actually did something.
        """
        if self._closed or not self._order:
            return False
        # Re-entrancy: repainting tiles reconfigures ``scrollregion``, which fires
        # ``yscrollcommand`` again. Without this guard that is an endless loop.
        if self._scrolling:
            return False
        span = self.visible_range()
        if span == self._rendered_span:
            return False
        self._scrolling = True
        try:
            self._rendered_span = span
            if self._view == VIEW_THUMBNAILS:
                self._render_tiles()
            self.request_visible()
            self._consume()
        finally:
            self._scrolling = False
        return True

    def request_visible(self) -> tuple[str, ...]:
        """Ask the decoder for whatever the visible span still needs, and no more."""
        if self._closed or not self._order:
            return ()
        start, stop = self.visible_range()
        want_image = self._view == VIEW_THUMBNAILS
        wanted = []
        for occurrence_id in self._order[start:stop]:
            if occurrence_id in self._inflight:
                continue
            facts = self._facts.get(occurrence_id)
            if want_image:
                if facts is not None and self.cache.peek(occurrence_id) is not None:
                    continue
            elif facts is not None:
                continue
            source = self._sources.get(occurrence_id)
            if source is None:  # pragma: no cover - order and sources move together
                continue
            wanted.append(PreviewRequest(
                occurrence_id, source, self._rendered_revision, want_image,
                self._thumbnail_size))
        if not wanted:
            return ()
        self._inflight.update(request.occurrence_id for request in wanted)
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        started = self._runner(tuple(wanted), self._results.put)
        if isinstance(started, threading.Thread):
            self._workers.append(started)
        return tuple(request.occurrence_id for request in wanted)

    def drain(self) -> int:
        """Consume finished previews and follow the manager. Runs on the panel's pump.

        Registered once with ``add_drain``; it schedules nothing and owns no
        callback, so the panel still has exactly one ``after`` chain.
        """
        if self._closed:
            return 0
        applied = self._consume()
        self._sync_if_stale()
        return applied

    def _consume(self) -> int:
        applied = 0
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            self._inflight.discard(result.occurrence_id)
            if self._accept(result):
                applied += 1
        return applied

    def _accept(self, result: PreviewResult) -> bool:
        """Take one result, or drop it inertly if the world moved on.

        Three ways a result is late: its occurrence was removed, the manager
        moved to a newer revision while it was decoding, or the browser closed.
        None of them is an error and none of them loses anything permanently —
        the next refresh asks again for whatever is still visible.
        """
        if self._closed:
            return False
        if result.occurrence_id not in set(self._order):
            return False
        if result.revision != self._rendered_revision:
            return False
        self._facts[result.occurrence_id] = result.facts
        if result.image_data is not None:
            try:
                image = tk.PhotoImage(data=result.image_data, master=self.frame)
            except tk.TclError:  # pragma: no cover - a destroyed interpreter
                image = None
            if image is not None:
                self.cache.put(result.occurrence_id, image)
        self._render_one(result.occurrence_id)
        return True

    def _sync_if_stale(self) -> bool:
        """Follow the manager without reaching into the shared adapter.

        Every mutation the importer offers — Remove, Clear, Move Up, Move Down,
        a committed import — advances the manager's revision, and every
        selection change shows in ``manager.selection``. Comparing those two on
        the tick this browser already rides keeps the projection honest without
        a second callback chain and without monkey-patching a private hook.
        """
        revision = self._manager.revision.value
        if revision != self._rendered_revision:
            self.refresh()
            return True
        selection = self._manager.selection
        if selection != self._rendered_selection:
            self._rendered_selection = selection
            self._paint_selection()
            return True
        return False

    # -- teardown ----------------------------------------------------------- #

    def close(self) -> None:
        """Release every image, drop the drain, and make later results inert.

        Idempotent. Afterwards the cache is empty, the placeholder is released,
        the pump no longer calls back into here, and no decoder thread is still
        running: each is joined within a bounded timeout, the way the import
        coordinator joins its own worker. A batch is capped at
        :data:`MAX_VISIBLE_ITEMS`, so the wait is short and finite.
        """
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        self._pump.remove_drain(self.drain)
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.join(WORKER_JOIN_TIMEOUT)
        try:
            self.canvas.delete("all")
        except tk.TclError:  # pragma: no cover - already destroyed
            pass
        self.cache.clear()
        self.placeholder = None
        self._facts.clear()
        self._inflight.clear()
        self._tiles = ()
        self._tile_selection = ()
        self._rendered_span = None
        self._on_selection_change = None
        while True:
            try:
                self._results.get_nowait()
            except queue.Empty:
                break

    def _scroll_fractions(self) -> tuple[float, float]:
        """What the active widget says it is showing, as (first, last) fractions.

        An unmapped widget has no real viewport — Tk answers from a size it has
        not been given yet, which is neither "everything" nor anything useful.
        Saying "assume it is all visible" is the honest answer there, and it is
        safe precisely because :func:`visible_span` caps the result at
        :data:`MAX_VISIBLE_ITEMS`.
        """
        widget = self.surface(self._view)
        try:
            if not widget.winfo_ismapped():
                return (0.0, 1.0)
            first, last = widget.yview()
        except (tk.TclError, ValueError):  # pragma: no cover - a destroyed widget
            return (0.0, 1.0)
        return (float(first), float(last))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"CoverBrowser(view={self._view}, count={len(self._order)}, "
                f"cached={self.cache.size}, closed={self._closed})")


# ---------- one run: freezing it, and planning where it writes ----------
#
# Everything below is plain data and pure functions. It decides *what* a run is
# and *where* its outputs go, on the main thread, before a worker exists — which
# is what makes a run frozen in the sense Decision 9A means, and what lets a
# later retry land exactly where the original attempt would have.


#: The one stage name this tool reports. An identifier, because that is what the
#: shared event vocabulary accepts.
STAGE_RESIZE = "resize"

#: The estimator's work category. One image is one comparable unit of work; the
#: estimate is thrown away rather than mixed if that ever stops being true.
ETA_CATEGORY = "image"

#: The run id the controls carry before anything has been started. Every real run
#: uses its own frozen snapshot id instead.
IDLE_RUN_ID = "cover-idle"

#: The queue message that hands a settled run back to the main thread. It travels
#: on the panel's existing worker queue beside "log", "progress" and "done"; it is
#: not a second event vocabulary, because the run's *events* go through the shared
#: stream and nothing here duplicates them.
RESULT_MESSAGE = "result"

#: The queue message that carries one finished image's measured duration, on that
#: same queue. See :class:`TimingSample` for why timing travels as a message.
TIMING_MESSAGE = "timing"


@dataclass(frozen=True)
class TimingSample:
    """How long one finished image actually took, as plain immutable data.

    The estimate itself lives in one :class:`~shared.job_control.EtaEstimator`
    that the shared job adapter reads, and that object is compound mutable state
    belonging to the thread that owns the widgets. So the worker does not touch
    it. It measures a duration with the run's injected clock and sends *this* —
    four immutable fields and nothing live — through the queue the main thread
    already drains, and the main thread is the only place a sample is ever
    recorded.

    ``run_id`` and ``attempt`` are what make a late sample inert. The run id
    alone is not enough: a retry re-runs the *same* frozen snapshot and therefore
    carries the same id, so the attempt number is what tells one attempt's
    leftovers from the attempt now running.
    """

    run_id: str
    attempt: int
    category: str
    duration: float


def written_name(source: Path) -> str:
    """The filename :func:`resize_for_audiobook` will actually write for *source*.

    A destination has to be planned under the name that will exist, not under the
    source's own: a ``.webp`` is written as ``.jpg``, so planning ``art.webp``
    would reserve a name nothing ever occupies and leave the real one unchecked.
    """
    resolved = Path(source)
    return resolved.stem + written_suffix(resolved.suffix)


def _identity_buckets(snapshot):
    """Split a snapshot's occurrence ids the way :func:`planning_groups` splits paths.

    Returns ``(direct_ids, grouped_ids)`` — individually added occurrences in list
    order, then folder-derived occurrences grouped by root and ordered by the root
    order the user imported in, which is exactly the shared function's own rule.
    The caller cross-checks the two against each other, so this cannot quietly
    drift into a second grouping.
    """
    direct: list[str] = []
    buckets: dict[str, list[str]] = {}
    order: list[tuple[int, str]] = []
    for entry in snapshot.files:
        if entry.mirroring_root is None:
            direct.append(entry.occurrence_id)
            continue
        key = entry.source_root.root_id
        if key not in buckets:
            buckets[key] = []
            order.append((entry.source_root.order, key))
        buckets[key].append(entry.occurrence_id)
    order.sort()
    return tuple(direct), tuple(tuple(buckets[key]) for _order, key in order)


def _pair(occurrence_ids, plan, sources, lookup) -> dict:
    """Attach one planned destination to each occurrence, or refuse.

    The two walks above are independent, so they are verified against each other
    rather than trusted: if the ids and the paths ever stopped lining up, a run
    would write one occurrence's image to another's destination, and that has to
    be a loud error rather than a quiet mix-up.
    """
    if len(occurrence_ids) != len(plan.items):
        raise output_paths.UnsafePathError(
            "the output plan does not cover every imported image",
            f"{len(occurrence_ids)} occurrences, {len(plan.items)} planned outputs",
        )
    mapping = {}
    for occurrence_id, item, source in zip(occurrence_ids, plan.items, sources):
        if lookup[occurrence_id] != source:
            raise output_paths.UnsafePathError(
                "an imported image was matched to another image's destination",
                f"{lookup[occurrence_id]} vs {source}",
            )
        mapping[occurrence_id] = item.destination
    return mapping


def plan_destinations(snapshot, run_root: Path, *, planner=None) -> dict:
    """Where every occurrence of *snapshot* writes inside *run_root*.

    :func:`~shared.importing.planning_groups` is the only bridge from an imported
    list to Plan 2, and the three approved planners are the only things that
    decide a destination: individually chosen files land flat (Decision 31A), one
    folder root mirrors its relative parents (Decision 7A), and several roots each
    get their own collision-safe container (Decision 41A). Direct files are
    planned first and the roots follow, which is the order the shared grouping
    presents them in.

    All of them share one :class:`~shared.output_paths.DestinationPlanner`, so a
    flat file and a mirrored file can never be planned onto the same path, and
    ``Cover.jpg`` twice becomes ``Cover.jpg`` and ``Cover-1.jpg``. Nothing is
    created here: this reserves no directory and opens no file.
    """
    root = Path(run_root)
    tracker = output_paths.DestinationPlanner(root) if planner is None else planner
    groups = planning_groups(snapshot)
    direct_ids, grouped_ids = _identity_buckets(snapshot)
    lookup = {entry.occurrence_id: entry.path for entry in snapshot.files}

    mapping: dict = {}
    if groups.direct:
        plan = plan_flat(root, groups.direct, planner=tracker, rename=written_name)
        mapping.update(_pair(direct_ids, plan, groups.direct, lookup))
    if groups.grouped:
        if groups.needs_multi_root:
            plan = plan_multi_root(
                root, groups.grouped, planner=tracker, rename=written_name)
        else:
            source_root, sources = groups.grouped[0]
            plan = plan_mirrored(
                root, sources, source_root, planner=tracker, rename=written_name)
        flattened_ids = tuple(entry for group in grouped_ids for entry in group)
        flattened_sources = tuple(
            entry for _root, sources in groups.grouped for entry in sources)
        mapping.update(_pair(flattened_ids, plan, flattened_sources, lookup))
    return mapping


def freeze_cover_options(size: int, letterbox: bool, mode: str) -> dict:
    """Everything about a run that changes its output, as plain frozen values.

    Deliberately small and deliberately opaque to the shared foundation: Plan 2
    stays the only owner of what a destination *means*, so a mode travels here as
    a word and is turned into paths by this module alone.
    """
    return {"size": int(size), "letterbox": bool(letterbox), "mode": str(mode)}


# ---------- GUI ----------

#: Spacing, identical to the TTS panel's own layout constants:
#: the maintainer's 2026-09-27 ruling makes TTS the exact visual reference, so
#: these numbers are copied rather than re-chosen. Pixels.
OUTER_PAD = 10
COLUMN_GAP = 10
SECTION_GAP = 8
SECTION_PADDING = (10, 6, 10, 8)

#: The Output & Run caption's wrap width, so prose can never be what decides
#: how wide the section must be (TTS's own rule for its captions).
OUTPUT_NOTE_WRAP = 200

#: Wrap width for status lines that change during a session (import status,
#: run stage/status), so a long message adds a line rather than a column.
STATUS_WRAP = 190

#: Rows the source browser asks for at its natural size, and the rows it keeps
#: however small the window gets. It is Sources' flexible region.
BROWSER_ROWS = 8
BROWSER_FLOOR_ROWS = 2

#: The browser height an arrangement with Sources on top must leave: one full
#: Medium Thumbnails row (image, padding and filename) plus the view switch.
BROWSER_COMFORT_HEIGHT = 200

#: The width the browser *asks* for. Its three views grow with the window, so
#: their many columns never decide how wide Sources must be.
BROWSER_REQ_WIDTH = 230

#: The shared importer's own list is withdrawn from view (the browser is the
#: list), so its requested height is irrelevant; kept small regardless.
IMPORTER_LIST_HEIGHT = 2

#: The Activity log: natural size in lines/characters, the lines it keeps at
#: the smallest window, and the history cap shared with the sibling tools.
LOG_HEIGHT = 12
LOG_WIDTH_CHARS = 40
LOG_FLOOR_LINES = 3
LOG_LIMIT = 400

#: The narrowest Activity column worth putting beside the workflow. Below this
#: the log would be a sliver, so the panel stacks Activity underneath instead.
ACTIVITY_MIN_WIDTH = 150

#: The Activity caption's wrap width at its narrowest; it follows the column.
ACTIVITY_NOTE_MIN_WRAP = 60

#: Share of the panel the workflow column takes on a wide window, when that is
#: more than its measured natural width -- the frozen contract's 32-35%.
WORKFLOW_SHARE = 0.34

#: The shared status view's progress bar defaults to 240 px; that alone would
#: decide how wide Output & Run must be. Narrower reads the same.
PROGRESS_BAR_LENGTH = 110


class CoverResizerUI(ttk.Frame):
    """The Cover Resizer tool as an embeddable frame.

    v0.6.1 Plan 4 Phase 2 replaced this panel's own imported-file list — a
    ``list[Path]``, a ``tk.Listbox`` and three hand-written buttons — with the
    shared Plan 3 importing foundation. The
    :class:`~shared.importing.ImportedFileManager` is now the **only**
    authority on which files are imported, in what order, and which are
    selected; nothing here keeps a parallel copy.

    Every keyword below is a **seam with a production default**, present so the
    suite can drive a real panel deterministically — a fake dialog, a stub
    thread factory, an injected clock, an in-memory configuration — without a
    display server, a real home directory or a real broad filesystem root. The
    launcher passes none of them.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        effective_config: object | None = None,
        clock=None,
        id_factory=None,
        scanner=None,
        thread_factory=None,
        home: object | None = None,
        choose_files=None,
        choose_folder=None,
        confirm_broad_root=None,
        confirm_large_result=None,
        preview_runner=None,
        viewport=None,
        cache_limit=None,
        job_runner=None,
        appearance_bundle: dict | None = None,
    ):
        # v0.6.6 Phase 2 (remediated per the maintainer's 2026-09-27 ruling —
        # see Decisions.md): this whole panel's *interior* now uses the compact
        # Compact.* control language every widget below is built with, the same
        # visual language TTS is the reference for -- not only the two shared
        # job_ui components a first pass limited itself to. That first pass left
        # every other widget here classic/native, which is coherent in Light but
        # leaves large unstyled light regions inside an otherwise-Dark panel; the
        # ruling is explicit that no app-owned tool interior may do that. Full
        # Family-A *layout* reorganization is still Phase 5's job -- nothing
        # below moves a grid position, only what each widget is styled with.
        # ``appearance_bundle`` is a seam like every other keyword above: the
        # production default reads the real remembered setting, and the suite
        # may inject an exact Light or Dark bundle to check coherence
        # deterministically, without touching real settings state.
        if appearance_bundle is None:
            appearance_bundle = appearance.build_bundle(
                ttk.Style(parent), appearance.get_appearance(),
                root=parent.winfo_toplevel())
        self.appearance_bundle = appearance_bundle
        super().__init__(parent, style=job_ui.style_name(self.appearance_bundle, "window"))
        appearance.register_listener(self._on_appearance_changed)

        self._closed = False

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern). This
        # event belongs to the *processing* run and to nothing else: `Cancel
        # Import` goes to the coordinator and never reaches it.
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # --- one run at a time, frozen once ------------------------------- #
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None else effective_config)
        self._job_runner = job_runner
        self._worker = None
        self._run_count = 0
        # Every acceptance of a run, first attempt or retry. A retry re-uses the
        # original snapshot id, so this — not the run id — is what tells a
        # retired attempt's late timing sample from the one now running.
        self._attempt = 0
        self._snapshot = None
        self._controller = None
        self._reporter = None
        self._estimator = None
        self._result = None
        self._destinations: dict = {}
        self._event_q: queue.Queue = queue.Queue()

        # Where the next run will go, shown read-only. The numbered run folder
        # is reserved when a validated resize starts, so building this panel
        # creates nothing. The base is changed in Preferences & Data.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        # Preferences & Data can change the base while this panel is alive; the
        # shared registry re-points this display the moment that happens.
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)
        self._last_run_dir = None

        # --- the shared importing foundation ------------------------------ #
        # One pump owns this panel's whole scheduled-callback chain: the import
        # poller rides its `schedule` seam and the processing worker's queue is
        # registered as a drain. There is no second `after` loop.
        self._pump = job_ui.MainThreadPump(self)
        self.import_catalog = build_catalog()
        self._manager = ImportedFileManager(id_factory=id_factory)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=id_factory,
            # Handed to the coordinator rather than the adapter deliberately:
            # the coordinator asks it *before* it creates a thread, so a decline
            # starts no worker at all.
            confirm_broad_root=(self._confirm_broad_root if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )
        # ---- layout: the Family-A workflow, TTS's own composition --------- #
        # v0.6.6 Phase 2 remediation (maintainer sequencing override, see
        # Decisions.md 2026-09-27): Cover adopts the frozen contract's Family-A
        # layout now, rather than in Phase 5, with the TTS panel as the exact
        # visual reference:
        #
        #   1. Sources         -- the source browser (the panel's list), the six
        #                         import actions, the import options, Cancel Import
        #   2. Resize Options  -- every resize/source-side control, no scrolling
        #   3. Output & Run    -- destination, Resize Covers, the shared controls
        #   Activity           -- the one Summary | Detailed log, on the right
        #
        # 1-3 are the workflow, read top to bottom. How they sit depends only on
        # the panel's size (_choose_layout), from the sections' own measured
        # sizes -- never a whole-panel scrollbar, never a scrolling options form:
        #
        #   wide     1 over 2 over 3 on the left, Activity on the right
        #   split    1 over (2 beside 3) on the left, Activity on the right --
        #            the 920x600 minimum, where the vertical column is too tall
        #   stacked  the same workflow above Activity; a last resort only for a
        #            panel too narrow to put anything beside the workflow
        #
        # Only the browser's views and the log scroll, and each keeps a measured
        # floor so neither collapses.
        bundle = self.appearance_bundle
        self._needs: dict | None = None
        self._layout_mode: str | None = None
        self.workflow = ttk.Frame(self, style=job_ui.style_name(bundle, "window"))
        self.sources_section = ttk.LabelFrame(
            self.workflow, text="1. Sources", padding=SECTION_PADDING,
            style=job_ui.style_name(bundle, "labelframe"))
        self.options_section = ttk.LabelFrame(
            self.workflow, text="2. Resize Options", padding=SECTION_PADDING,
            style=job_ui.style_name(bundle, "labelframe"))
        self.run_section = ttk.LabelFrame(
            self.workflow, text="3. Output & Run", padding=SECTION_PADDING,
            style=job_ui.style_name(bundle, "labelframe"))
        self.activity = ttk.LabelFrame(
            self, text="Activity", padding=SECTION_PADDING,
            style=job_ui.style_name(bundle, "labelframe"))

        # ---- 1. Sources --------------------------------------------------- #
        sources = self.sources_section
        sources.columnconfigure(0, weight=1)
        sources.rowconfigure(0, weight=1)
        self.importer = job_ui.ImportAdapter(
            sources,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            theme=bundle,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=self._choose_files if choose_files is None else choose_files,
            choose_folder=self._choose_folder if choose_folder is None else choose_folder,
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            list_height=IMPORTER_LIST_HEIGHT,
        )
        # The browser *is* this panel's list (the frozen contract's
        # "[list/browser]" convention): it projects the very manager the
        # importer's actions mutate, and every selection it makes is written to
        # that manager and mirrored into the importer (_on_browser_selection).
        # So the importer's own duplicate listbox is withdrawn from view --
        # never destroyed, and still kept in step -- while its count line, its
        # six actions, its options and Cancel Import stay exactly where the
        # shared component puts them.
        self.browser = CoverBrowser(
            sources,
            self._manager,
            pump=self._pump,
            runner=preview_runner,
            viewport=viewport,
            cache_limit=cache_limit,
            height=BROWSER_ROWS,
            on_selection_change=self._on_browser_selection,
            theme=bundle,
        )
        self.browser.frame.grid(row=0, column=0, sticky="nsew")
        self.importer.frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        imported = self.importer.list
        imported.listbox.grid_remove()
        imported.scrollbar.grid_remove()
        imported.frame.rowconfigure(1, weight=0)
        self.importer.frame.rowconfigure(0, weight=0)
        imported.count_label.grid_configure(pady=(0, 4))
        # A long status ("... files need confirmation, which is not available
        # here. Nothing was added.") wraps onto a second line instead of
        # widening Sources mid-session, which would squeeze Activity.
        imported.count_label.configure(wraplength=STATUS_WRAP)
        self.importer.status.label.configure(wraplength=STATUS_WRAP)
        self._arrange_import_controls()
        # §4's keyboard contract on the three views, routed to the same guarded
        # actions the buttons call. Select-all keeps the browser's own anchored
        # behaviour, which it already bound on every view.
        for view in (self.browser.details, self.browser.simple, self.browser.canvas):
            job_ui.bind_list_shortcuts(
                view,
                on_select_all=lambda: self.browser.key("select_all"),
                on_move_up=imported.move_up,
                on_move_down=imported.move_down,
                on_remove=imported.remove_selected,
            )

        # ---- 2. Resize Options -------------------------------------------- #
        # The form itself is unchanged -- same controls, same variables, same
        # enable/disable relationships -- and is now simply always visible:
        # no canvas, no scrollbar of its own.
        options = self.options_section
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Target size (square, px)",
                  style=job_ui.style_name(bundle, "label")).grid(
            row=0, column=0, sticky="w")
        self.var_size = tk.IntVar(value=TARGET_SIZE)
        self.entry_size = ttk.Spinbox(
            options, from_=256, to=4096, textvariable=self.var_size, width=6,
            increment=64, style=job_ui.style_name(bundle, "spinbox"),
        )
        self.entry_size.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.var_letterbox = tk.BooleanVar(value=True)
        self.chk_letterbox = ttk.Checkbutton(
            options,
            text="Keep full image\n(letterbox into square, no cropping)",
            variable=self.var_letterbox,
            style=job_ui.style_name(bundle, "checkbutton"),
        )
        self.chk_letterbox.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Separator(options, orient=tk.HORIZONTAL,
                      style=job_ui.style_name(bundle, "separator")).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 3))

        # --- source-side mode (Decision 10A) ---------------------------------
        # Off by default, and the safe numbered-copy action is preselected.
        # Replacement needs all three of: this toggle on, that radio chosen,
        # and the per-run confirmation accepted.
        self.var_source_side = tk.BooleanVar(value=False)
        self.chk_source_side = ttk.Checkbutton(
            options,
            text=SOURCE_SIDE_LABEL,
            variable=self.var_source_side,
            command=self._on_source_side_change,
            style=job_ui.style_name(bundle, "checkbutton"),
        )
        self.chk_source_side.grid(row=3, column=0, columnspan=2, sticky="w")

        self.var_source_action = tk.StringVar(value=ACTION_NUMBERED)
        self.rb_numbered = ttk.Radiobutton(
            options,
            text="Create numbered copies",
            variable=self.var_source_action,
            value=ACTION_NUMBERED,
            style=job_ui.style_name(bundle, "radiobutton"),
        )
        self.rb_numbered.grid(row=4, column=0, columnspan=2, sticky="w", padx=(20, 0))
        self.rb_replace = ttk.Radiobutton(
            options,
            text="Replace original files",
            variable=self.var_source_action,
            value=ACTION_REPLACE,
            style=job_ui.style_name(bundle, "radiobutton"),
        )
        self.rb_replace.grid(row=5, column=0, columnspan=2, sticky="w", padx=(20, 0))
        self._on_source_side_change()

        # ---- 3. Output & Run ---------------------------------------------- #
        run = self.run_section
        run.columnconfigure(1, weight=1)
        ttk.Label(run, text="Output", style=job_ui.style_name(bundle, "label")).grid(
            row=0, column=0, sticky="w")
        self.entry_outdir = ttk.Entry(
            run, textvariable=self.var_outdir, state="readonly", width=24,
            style=job_ui.style_name(bundle, "entry"),
        )
        self.entry_outdir.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.output_note = ttk.Label(
            run,
            text="Each resize gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
            style=job_ui.style_name(bundle, "secondary_label"),
            justify=tk.LEFT,
            wraplength=OUTPUT_NOTE_WRAP,
        )
        self.output_note.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Separator(run, orient=tk.HORIZONTAL,
                      style=job_ui.style_name(bundle, "separator")).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 4))

        # Resize Covers is the primary action: it leads the run row and is the
        # panel's default button, exactly as TTS's Start is. Pause, Resume,
        # Cancel and Retry Failed belong to the shared control bar beside it,
        # which offers each of them exactly when the approved availability
        # rules say it is meaningful.
        self.run_row = ttk.Frame(run, style=job_ui.style_name(bundle, "surface"))
        self.run_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.run_row.columnconfigure(0, weight=1)
        self.btn_convert = ttk.Button(
            self.run_row, text="Resize Covers", command=self.start_resize,
            default="active", width=14, style=job_ui.style_name(bundle, "button"))
        self.btn_convert.grid(row=0, column=0, sticky="w")
        # The shared run controls and status view (progress, stage, ETA),
        # directly beneath the primary action. The adapter is rebuilt for each
        # run -- one run, one event stream, one estimate -- so this container
        # holds its place in the layout.
        self.job_area = ttk.Frame(self.run_row, style=job_ui.style_name(bundle, "surface"))
        self.job_area.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.job_area.columnconfigure(0, weight=1)

        # ---- Activity: the one Summary | Detailed log --------------------- #
        # Built once and handed to every run's JobAdapter, so a fresh adapter's
        # empty first render can never drop an earlier run's lines -- the same
        # contract TTS, MP3 Tool, M4B Maker and M4B Metadata Editor share. The
        # worker's own transcript goes to Detailed (log_write), never Summary.
        act = self.activity
        act.columnconfigure(0, weight=1)
        act.rowconfigure(1, weight=1)
        bar = ttk.Frame(act, style=job_ui.style_name(bundle, "surface"))
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        bar.columnconfigure(0, weight=1)
        self.activity_note = ttk.Label(
            bar,
            text="Summary: progress and results.  Detailed: every step.",
            style=job_ui.style_name(bundle, "secondary_label"),
            justify=tk.LEFT,
            wraplength=ACTIVITY_NOTE_MIN_WRAP,
        )
        self.activity_note.grid(row=0, column=0, sticky="w")
        self.btn_clear_log = ttk.Button(
            bar, text="Clear Log", command=self.clear_log,
            style=job_ui.style_name(bundle, "button"))
        self.btn_clear_log.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.log = job_ui.SummaryDetailsView(
            act, theme=bundle, height=LOG_HEIGHT, width=LOG_WIDTH_CHARS,
            details_label="Detailed", limit=LOG_LIMIT)
        self.log.frame.grid(row=1, column=0, sticky="nsew")

        self.bind("<Configure>", self._on_panel_configure, add="+")

        # The worker->GUI queue is a drain on the one pump, not a second chain.
        self._pump.add_drain(self._drain_worker_queue)
        self._install_jobs(IDLE_RUN_ID, ())
        # Measured once everything exists, then placed; the first <Configure>
        # of a mapped panel re-decides the arrangement for the real size.
        self._measure_layout()
        self._apply_layout("columns")
        self._pump.start()

    # ------- the imported list (owned by the shared manager) -------

    @property
    def manager(self) -> ImportedFileManager:
        """The single authority on the imported list. Read it; never shadow it."""
        return self._manager

    def imported_files(self) -> list[Path]:
        """The imported paths, in list order, from the manager's snapshot.

        Main thread only, and the list it returns is a plain copy: what a run
        freezes is this value, so a later import mutates the manager and never
        a run that has already started.
        """
        return [imported.path for imported in self._manager.snapshot().files]

    def _on_browser_selection(self, occurrence_ids) -> None:
        """Keep the shared list showing the selection the browser just made.

        The manager already has it — the browser wrote there first. This only
        repaints the importer's own rows so the two views of one selection do
        not disagree on screen.
        """
        self.importer.list.select(occurrence_ids)

    # ------- the run: what it is, and who is driving it -------

    @property
    def run_snapshot(self):
        """The frozen configuration of the current or most recent run, if any."""
        return self._snapshot

    @property
    def run_result(self):
        """How the most recent run was settled, or ``None`` before the first."""
        return self._result

    @property
    def job_controller(self):
        """The cooperative controller of the current run, or ``None``."""
        return self._controller

    @property
    def job_estimator(self):
        """The current run's rolling estimate, or ``None`` before the first run."""
        return self._estimator

    def destinations(self) -> dict:
        """Occurrence id to planned destination, for the frozen standard run.

        Empty for the two source-side modes, which place each output beside its
        own source at the moment it is written and therefore have no plan to
        make in advance.
        """
        return dict(self._destinations)

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared run controls at one run. Main thread only.

        A run owns its event stream and its estimate, and neither can be rebound,
        so a new run gets a new adapter in the same container. The retired one is
        closed first, which is what drops its drain — the pump keeps exactly one
        job drain however many runs a session performs.
        """
        previous = getattr(self, "jobs", None)
        if previous is not None:
            previous.close()
            previous.frame.destroy()
        self._event_q = queue.Queue()
        self._estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        bundle = self.appearance_bundle
        self.jobs = job_ui.JobAdapter(
            self.job_area,
            run_id=run_id,
            pump=self._pump,
            theme=bundle,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            item_ids=item_ids,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel,
            on_retry=self.retry_failed,
            # The panel's one persistent Summary/Detailed log in Activity, not a
            # fresh view per adapter: the adapter renders into it, and neither
            # places nor closes it.
            views=self.log,
        )
        self.jobs.frame.grid(row=0, column=0, sticky="nsew")
        # One progress model, not two: the panel's indicator *is* the shared
        # status view's, so nothing can draw a second, disagreeing bar.
        self.progress = self.jobs.status.indicator
        # Per-instance restyling only, the way MP3 Tool and the M4B Metadata
        # Editor do it: the shared indicator stays generic for every panel that
        # has not adopted the compact system, but inside this one an unstyled
        # native frame would be a light island in Dark. On aqua every name
        # below is "" -- native, exactly as before.
        self.progress.frame.configure(style=job_ui.style_name(bundle, "card"))
        self.progress.bar.configure(style=job_ui.style_name(bundle, "progressbar"),
                                    length=PROGRESS_BAR_LENGTH)
        self.progress.label.configure(style=job_ui.style_name(bundle, "secondary_label"))
        # Same rule as the import status: long run text wraps, never widens.
        # The status line sits on the section surface, so it takes the same
        # secondary-label style as its neighbours rather than the shared
        # view's window-toned status style (a visible sliver otherwise).
        for label in (self.jobs.status.label_stage, self.jobs.status.label_status):
            label.configure(wraplength=STATUS_WRAP)
        self.jobs.status.label_status.configure(
            style=job_ui.style_name(bundle, "secondary_label"))
        self._arrange_job_controls()
        self.jobs.register_inputs(self.importer, self.browser)
        self.jobs.register_options(self)
        self.jobs.render()

    def _publish(self, event) -> None:
        """Hand one produced event to the queue the shared adapter drains.

        Called from whichever thread produced it — the worker for progress and
        failures, the main thread for a button press that moved the controller.
        A queue is the only thing that crosses that boundary.
        """
        self._event_q.put(event)

    def _on_state(self, snapshot) -> None:
        """The controller's listener: copy its state into the event stream.

        The reporter mints the event *from this snapshot*, so the UI can never
        show a state the controller did not actually reach.
        """
        reporter = self._reporter
        if reporter is not None:
            reporter.state_changed(snapshot)

    def pause(self) -> None:
        """Ask the run to pause at its next boundary between images."""
        controller = self._controller
        if controller is not None:
            controller.request_pause()

    def resume(self) -> None:
        """Return a paused run to running and wake its worker."""
        controller = self._controller
        if controller is not None:
            controller.resume()

    def retry_failed(self):
        """Re-run only the retryable failures, against the exact original run.

        Everything comes from the settled :class:`~shared.job_control.RunResult`:
        the snapshot the run was accepted with, the failures it actually
        recorded, and the destinations that run planned. Nothing is read from the
        imported list, the widgets or the configuration as they stand now — which
        is what keeps a retried item landing where it would originally have
        landed, and what stops it overwriting an output that already succeeded.
        """
        result = self._result
        if result is None or self._busy.is_set() or not result.has_retryable:
            return None
        request = result.retry()
        return self._launch(request.snapshot, request.item_ids)

    def set_locked(self, locked: bool) -> None:
        """The shared lock matrix's hook onto this panel's own option controls."""
        self.disable_inputs(bool(locked))

    # ------- dialogs and confirmations, all on the owner thread -------

    def _choose_files(self) -> tuple[str, ...]:
        """The Add Files dialog. Order is the dialog's, and it is preserved."""
        chosen = tuple(filedialog.askopenfilenames(
            parent=self,
            title="Select cover images",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=_image_filetypes(),
        ) or ())
        if chosen:
            settings.set(KEY_INPUT_DIR, str(Path(chosen[0]).parent))
        return chosen

    def _choose_folder(self) -> tuple[str, ...]:
        """The Add Folder dialog. One root, returned as the tuple the seam wants."""
        chosen = filedialog.askdirectory(
            parent=self,
            title="Select a folder of cover images",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            mustexist=True,
        )
        if not chosen:
            return ()
        settings.set(KEY_INPUT_DIR, str(chosen))
        return (str(chosen),)

    def _confirm_broad_root(self, roots) -> bool:
        """Asked before a scan thread exists, so declining starts no worker."""
        listed = "\n".join(str(entry) for entry in roots)
        return job_ui.ask_confirm(
            self,
            "Scan a very broad folder?",
            "This covers a whole drive or your home folder:\n\n"
            f"{listed}\n\nScanning it can take a long time. Continue?",
        )

    def _confirm_large_result(self, outcome) -> bool:
        """Answered after the scan and before anything is committed."""
        return job_ui.ask_confirm(
            self,
            "Add a large number of images?",
            f"{outcome.proposed_count:,} images are ready to be added.\n\n"
            "Adding this many at once can make the list slow to work with. "
            "Add them?",
        )

    # ------- UI callbacks -------

    def _on_source_side_change(self):
        """Enable the two choices only while source-side mode is on.

        Turning the mode off also resets the action to numbered copies, so a
        Replace selection can never survive as a hidden active mode.
        """
        on = bool(self.var_source_side.get())
        if not on:
            self.var_source_action.set(ACTION_NUMBERED)
        state = tk.NORMAL if on else tk.DISABLED
        for widget in (self.rb_numbered, self.rb_replace):
            widget.configure(state=state)

    def effective_mode(self) -> str:
        """The route this panel would actually take right now.

        Replacement requires the toggle *and* the radio; either alone yields a
        safe mode, so a stale radio value behind a switched-off toggle is inert.
        """
        if not self.var_source_side.get():
            return MODE_STANDARD
        return (ACTION_REPLACE if self.var_source_action.get() == ACTION_REPLACE
                else ACTION_NUMBERED)

    def _validated_replacement_sources(self, files):
        """Every source proved replaceable, or raise before anything happens."""
        validated = []
        for src in files:
            resolved = output_paths.validate_source_for_replacement(src)
            if resolved.suffix.lower() not in REPLACEABLE_SUFFIXES:
                raise output_paths.UnsafePathError(
                    f"{resolved.name} cannot be replaced in place because its "
                    f"format is written as .jpg; use numbered copies instead",
                    f"unsupported suffix {resolved.suffix!r}",
                )
            validated.append(resolved)
        if not validated:
            raise output_paths.UnsafePathError(
                "no image could be replaced", "empty validated source list"
            )
        return validated

    def confirm_replacement(self, count: int) -> bool:
        """The approved strong confirmation. Required once per replace run.

        Cancel is the default and holds focus, Escape and the window close both
        cancel, and there is no remembered or suppressible path — the dialog is
        rebuilt for every run.
        """
        return _ask_replacement(
            self,
            REPLACEMENT_TITLE,
            replacement_message(count),
            replacement_button_label(count),
            theme=self.appearance_bundle,
        )

    def _gate_replacement(self, files):
        """The complete replacement chain, or ``None`` if it does not open.

        Every source is validated *before* the dialog, so the count shown is the
        count that can actually be processed and a rejected import can never
        reach the replacement boundary. Both a first run and a retry come through
        here, which is why the confirmation is asked for from exactly one place
        and a retry can never inherit an earlier answer.
        """
        try:
            validated = self._validated_replacement_sources(files)
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Cannot replace originals", exc.message)
            return None
        if not self.confirm_replacement(len(validated)):
            self._log_q.put(("log", "\nReplacement cancelled. Nothing was changed.\n"))
            return None
        return validated

    def start_resize(self):
        if self._busy.is_set():
            return
        # The manager's snapshot is the input, captured here on the main thread.
        # Everything below works on this frozen copy.
        files = self.imported_files()
        if not files:
            messagebox.showwarning("No files", "Please import images first.")
            return

        try:
            size = int(self.var_size.get() or TARGET_SIZE)
        except Exception:
            messagebox.showerror("Bad size", "Target size must be a number.")
            return

        if size <= 0:
            messagebox.showerror("Bad size", "Target size must be positive.")
            return

        mode = self.effective_mode()
        self._run_count += 1
        # Decision 9A, in one call: the imported list, the catalog, the import
        # options, the effective configuration and every output-affecting setting
        # are copied here, on the main thread, and never consulted again.
        snapshot = capture_run(
            snapshot_id=f"cover-run-{self._run_count}",
            files=self._manager,
            catalog=self.import_catalog,
            import_options=self.importer.options.options(),
            effective_config=self._effective_config,
            tool_options=freeze_cover_options(size, self.var_letterbox.get(), mode),
            created_at=float(self._clock()),
        )

        destinations: dict = {}
        if mode == MODE_STANDARD:
            # Only the standard route reserves a run; an exception-mode
            # operation must not leave an unused numbered folder behind.
            try:
                reservation = output_paths.reserve_run_directory(TOOL_KEY)
                destinations = plan_destinations(
                    snapshot.files, reservation.run_directory,
                    planner=reservation.planner())
            except output_paths.OutputPathError as exc:
                messagebox.showerror("Output folder", exc.message)
                return
            self.var_outdir.set(str(reservation.run_directory))
            self._last_run_dir = reservation.run_directory
            self._log_q.put(("log", f"\nOutput folder: {reservation.run_directory}\n"))
        else:
            where = ("beside each source image"
                     if mode == ACTION_NUMBERED else "over each original")
            self._log_q.put(("log", f"\nWriting {where}.\n"))

        return self._launch(snapshot, snapshot.item_ids, destinations=destinations)

    def _launch(self, snapshot, item_ids, *, destinations=None):
        """Accept one run — first attempt or retry — and hand it to a worker.

        The frozen snapshot decides everything: which occurrences run, in which
        order, at what size, in which mode, and where each output goes. A retry
        re-uses the destinations its original run planned, so a retried item
        lands exactly where it would have landed and cannot take a name an
        earlier success already occupies.
        """
        wanted = tuple(item_ids)
        sources = {entry.occurrence_id: entry.path for entry in snapshot.files.files}
        files = [sources[occurrence_id] for occurrence_id in wanted]
        mode = snapshot.tool_options["mode"]

        if mode == ACTION_REPLACE:
            validated = self._gate_replacement(files)
            if validated is None:
                return None
            files = validated

        if destinations is not None:
            self._destinations = dict(destinations)
        self._snapshot = snapshot
        self._result = None
        self._attempt += 1
        self._controller = job_control.JobController(
            snapshot.snapshot_id, listener=self._on_state)
        self._install_jobs(snapshot.snapshot_id, snapshot.item_ids)
        self._reporter = job_control.JobReporter.for_run(
            snapshot, clock=self._clock, publish=self._publish)

        params = {
            "size": snapshot.tool_options["size"],
            "letterbox": snapshot.tool_options["letterbox"],
            "mode": mode,
            "files": files,
            "run_dir": self._last_run_dir if mode == MODE_STANDARD else None,
            "planner": None,
            "source_planner": (None if mode == MODE_STANDARD
                               else output_paths.SourceSidePlanner()),
            "item_ids": wanted,
            "destinations": dict(self._destinations),
            "snapshot": snapshot,
            "controller": self._controller,
            "reporter": self._reporter,
            # Timing travels back as data, never as a shared estimator: the
            # worker is handed the clock and the two labels it needs to stamp a
            # measurement, and nothing it can mutate.
            "clock": self._clock,
            "run_id": snapshot.snapshot_id,
            "attempt": self._attempt,
        }

        self._busy.set()
        self._cancel_event.clear()
        self._controller.start()
        if mode == MODE_STANDARD and self._last_run_dir is not None:
            self._reporter.output_location(self._last_run_dir)
        self._reporter.progress(0, len(files), stage=STAGE_RESIZE)
        self.disable_inputs(True)

        runner = self._job_runner
        self._worker = (self.run_resize_in_thread(params) if runner is None
                        else runner(self, params))
        return self._worker

    def run_resize_in_thread(self, params: dict):
        """Start the processing worker. The one place a resize thread is made."""
        worker = threading.Thread(target=self.resize_worker, args=(params,),
                                  daemon=True, name="cover-resize")
        worker.start()
        return worker

    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        controller = self._controller
        if controller is not None:
            # Cooperative, and it wakes a worker already waiting at a paused
            # checkpoint. Nothing is suspended or killed.
            controller.request_cancel()
        self._log_q.put(("log", "Cancelling… will stop after the current image.\n"))

    def disable_inputs(self, state: bool):
        """Lock or unlock this panel's inputs and processing options.

        Which states lock is not decided here — the shared matrix decided it, and
        the shared lock group calls this through :meth:`set_locked` whenever a
        run moves. It stays callable directly because locking is also what stops
        a *new* import starting mid-resize.
        """
        # The imported list and the import options lock as one unit through the
        # adapter. The import *status* bar deliberately does not: a scan that was
        # already running when a resize started can still be cancelled, and that
        # cancellation reaches the coordinator only — never this panel's
        # processing cancel event.
        self.importer.set_locked(state)
        # The browser locks its selection with them; changing *view* stays
        # available, because looking at the queue mutates nothing.
        self.browser.set_locked(state)
        widgets = [
            self.entry_size,
            self.chk_letterbox,
            self.btn_convert,
        ]
        widgets.append(self.chk_source_side)
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)
        # The two source-side choices follow the toggle, not the busy state, so
        # they never come back enabled while the mode is off.
        if state:
            for w in (self.rb_numbered, self.rb_replace):
                w.configure(state=tk.DISABLED)
        else:
            self._on_source_side_change()
        # The destination display is never typeable; it only greys out.
        self.entry_outdir.configure(state=tk.DISABLED if state else "readonly")

    def log_write(self, text: str, *, summary: bool = False) -> None:
        """Add the worker's own transcript text to the Activity log.

        Detailed only by default -- the per-image transcript is technical
        detail, and Summary is the shared adapter's own projection of the run.
        ``summary=True`` puts a line in both panes; the run's closing line uses
        it, so "All done." / "Cancelled." is visible without switching tabs.
        Blank lines the worker uses as spacing are dropped: each view line is
        already its own row.
        """
        lines = [line for line in str(text).splitlines() if line.strip()]
        if self._closed or not lines:
            return
        if summary:
            for line in lines:
                self.log.append(line)
        else:
            self.log.append_detail(lines)

    def clear_log(self) -> None:
        """Clear the visible Summary + Detailed text only. The run's own event
        stream, the session log and any settled result are untouched."""
        if not self._closed:
            self.log.clear()

    # ------- worker -> GUI queue drain (main thread, on the one pump) -------

    def _drain_worker_queue(self):
        """Drain the processing worker's queue. Registered once, on the pump.

        This is the same body the panel's own ``after(150, ...)`` chain used to
        run; what changed is that it no longer reschedules itself. The single
        :class:`~shared.job_ui.MainThreadPump` calls it on every tick, alongside
        the import poller, so exactly one Tk callback is ever outstanding.
        """
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log_write(payload)
                elif kind == "progress":
                    try:
                        self.progress.update(*payload)
                    except tk.TclError:  # pragma: no cover - a destroyed indicator
                        pass
                elif kind == TIMING_MESSAGE:
                    self._record_timing(payload)
                elif kind == RESULT_MESSAGE:
                    self._settle(payload)
                elif kind == "done":
                    self.log_write(payload, summary=True)
                    self._finish_idle()
        except queue.Empty:
            pass

    def _record_timing(self, sample: TimingSample) -> bool:
        """Apply one measured duration to this run's estimate. Main thread only.

        Reached only from the drain above, which the one pump calls on the thread
        that owns the widgets — so this is the single place any estimator is ever
        mutated, and the worker never holds one at all.

        A sample is dropped, inertly, if the panel has closed, if it belongs to a
        run this panel has moved on from, or if it belongs to an earlier attempt
        of the same run. None of those is an error: the sample simply describes
        work whose estimate no longer exists.
        """
        if self._closed:
            return False
        estimator = self._estimator
        if estimator is None:
            return False
        if sample.run_id != estimator.run_id or sample.attempt != self._attempt:
            return False
        return estimator.record(sample.category, sample.duration) is not None

    def _settle(self, result) -> None:
        """Take the settled run and let the shared controls offer what it allows.

        The result is the only authority on what failed and what may be retried;
        this panel keeps no rival list beside it.
        """
        self._result = result
        jobs = getattr(self, "jobs", None)
        if jobs is not None and not jobs.closed:
            jobs.set_result(result)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)

    def _on_appearance_changed(self, bundle: dict) -> None:
        """Re-color every raw Tk widget a ttk style-name mutation cannot reach.

        v0.6.6 Phase 2 remediation (2026-09-27 maintainer ruling — see
        Decisions.md): this panel's entire interior is now built from
        ``self.appearance_bundle``, so almost everything below already
        repainted itself the moment ``shared.appearance`` reconfigured the
        ``Compact.*`` styles in place — that includes every ``Radiobutton``,
        ``Checkbutton``, ``Entry``, ``Spinbox``, ``Labelframe``, ``Treeview``
        and ``Button`` this class or :class:`CoverBrowser` built with a style
        name. Only the classic Tk widgets that were colored directly rather
        than through a ttk style need this explicit call: the importer's
        withdrawn-but-live ``Listbox``; the browser's thumbnail ``Canvas``
        (:meth:`CoverBrowser.apply_appearance`, which also redraws its tiles'
        baked-in selection/text colors); and the Activity log's two ``Text``
        panes. Nothing is rebuilt, so no import, selection, view, setting,
        log line or run state moves.
        """
        self.appearance_bundle = bundle
        if self._closed:
            return
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.list.apply_appearance(bundle)
        browser = getattr(self, "browser", None)
        if browser is not None and not browser.closed:
            browser.apply_appearance(bundle)
        log = getattr(self, "log", None)
        if log is not None:
            log.apply_appearance(bundle)

    # ------- layout: measured, responsive, never a whole-panel scrollbar -------

    def _arrange_import_controls(self, narrow: bool = False) -> None:
        """Place the shared importer's actions and options compactly.

        Only grid positions change -- the same six buttons, the same options,
        the same commands and variables, and nothing of the importer's state.
        The six actions keep the frozen §4 order (Add Files, Add Folder, Move
        Up, Move Down, Remove, Clear All), three per row -- or two per row when
        Sources is its own narrow column (``narrow``). The import options take
        TTS's own two-row arrangement -- the file types with Include
        subfolders, then Include hidden folders with Allow duplicate files --
        or, narrow, one option per row beneath the file types.
        """
        per_row = 2 if narrow else 3
        for index, key in enumerate(key for key, _label in job_ui.ImportedFileList.ACTIONS):
            row, column = divmod(index, per_row)
            self.importer.list.buttons[key].grid_configure(
                row=row, column=column, padx=(0 if column == 0 else 4, 0),
                pady=(0 if row == 0 else 4, 0), sticky="ew")
        options = self.importer.options
        types = list(options.type_buttons.values())
        count = len(types)
        if narrow:
            # File types two to a row, then one option per row.
            for index, button in enumerate(types):
                row, column = divmod(index, 2)
                button.grid_configure(row=row, column=column, columnspan=1, sticky="w",
                                      padx=(0 if column == 0 else 8, 0),
                                      pady=(0 if row == 0 else 2, 0))
            first = (count + 1) // 2
            for row, check in enumerate((options.check_subfolders, options.check_hidden,
                                         options.check_duplicates), start=first):
                check.grid_configure(row=row, column=0, columnspan=2, sticky="w",
                                     padx=0, pady=(2, 0))
        else:
            for column, button in enumerate(types):
                button.grid_configure(row=0, column=column, columnspan=1, sticky="w",
                                      padx=(0 if column == 0 else 8, 0), pady=0)
            options.check_subfolders.grid_configure(
                row=0, column=count, columnspan=1, sticky="w", padx=(14, 0), pady=0)
            options.check_hidden.grid_configure(
                row=1, column=0, columnspan=count, sticky="w", padx=0, pady=(2, 0))
            options.check_duplicates.grid_configure(
                row=1, column=count, columnspan=1, sticky="w", padx=(14, 0), pady=(2, 0))
        options.frame.grid_configure(pady=(4, 0))
        self.importer.status.frame.grid_configure(pady=(4, 0))

    def _arrange_job_controls(self) -> None:
        """Pause | Resume above Cancel | Retry Failed: two compact rows, so Output
        & Run stays narrow enough to share a column with Resize Options at the
        920x600 minimum. Grid positions only -- the shared bar still decides
        which of them is available."""
        for index, button in enumerate(self.jobs.controls.buttons.values()):
            row, column = divmod(index, 2)
            button.grid_configure(row=row, column=column,
                                  padx=(0 if column == 0 else 4, 0),
                                  pady=(0 if row == 0 else 4, 0), sticky="ew")
        self.jobs.status.frame.grid_configure(pady=(4, 0))

    def _measure_layout(self) -> None:
        """Measure each section's natural size and each flexible region's floor.

        Every threshold :meth:`_choose_layout` uses comes from the live widgets,
        so the breakpoints follow the platform's real fonts and scaling rather
        than pixel constants. The browser asks for BROWSER_REQ_WIDTH and its
        natural rows; the log for its natural lines; each keeps a floor.
        """
        tree = self.browser.details
        self.update_idletasks()
        body = self.browser.body
        body.configure(width=BROWSER_REQ_WIDTH, height=max(1, tree.winfo_reqheight()))
        body.grid_propagate(False)
        style = ttk.Style(self)
        try:
            row_px = int(float(style.lookup(str(tree.cget("style")) or "Treeview",
                                            "rowheight") or 0))
        except (tk.TclError, ValueError):
            row_px = 0
        if row_px <= 0:
            row_px = int(tkfont.nametofont("TkDefaultFont").metrics("linespace")) + 4
        browser_give = row_px * (BROWSER_ROWS - BROWSER_FLOOR_ROWS)
        line = int(tkfont.Font(font=self.log.summary_text.cget("font")).metrics("linespace"))
        log_give = line * (LOG_HEIGHT - LOG_FLOOR_LINES)
        needs: dict = {}
        for narrow in (True, False):
            self._arrange_import_controls(narrow)
            self.update_idletasks()
            key = "sources_narrow" if narrow else "sources"
            needs[key] = (self.sources_section.winfo_reqwidth(),
                          self.sources_section.winfo_reqheight() - browser_give)
        needs["options"] = (self.options_section.winfo_reqwidth(),
                            self.options_section.winfo_reqheight())
        needs["run"] = (self.run_section.winfo_reqwidth(), self.run_section.winfo_reqheight())
        needs["browser_floor"] = max(0, self.browser.frame.winfo_reqheight() - browser_give)
        needs["log_floor"] = max(0, self.log.frame.winfo_reqheight() - log_give)
        needs["activity_floor"] = self.activity.winfo_reqheight() - log_give
        self._needs = needs
        self._arrange_import_controls(self._layout_mode == "columns")

    def _workflow_needs(self, mode: str) -> tuple[int, int]:
        """The workflow's natural width and its floor height in *mode*.

        ``sources`` heights are already floors: the browser at BROWSER_FLOOR_ROWS.
        """
        n = self._needs
        options, run = n["options"], n["run"]
        if mode == "columns":
            sources = n["sources_narrow"]
            return (sources[0] + SECTION_GAP + max(options[0], run[0]),
                    max(sources[1], options[1] + SECTION_GAP + run[1]))
        sources = n["sources"]
        if mode == "split":
            return (max(sources[0], options[0] + SECTION_GAP + run[0]),
                    sources[1] + SECTION_GAP + max(options[1], run[1]))
        return (max(sources[0], options[0], run[0]),
                sources[1] + 2 * SECTION_GAP + options[1] + run[1])

    def _browser_height(self, mode: str, height: int) -> int:
        """How tall the source browser would be in *mode* at this panel height."""
        _, flow_floor = self._workflow_needs(mode)
        room_h = height - 2 * OUTER_PAD
        if mode == "columns":
            fixed = self._needs["sources_narrow"][1] - self._needs["browser_floor"]
        else:
            fixed = flow_floor - self._needs["browser_floor"]
        return room_h - fixed

    def _choose_layout(self, width: int, height: int) -> str:
        """Pick the arrangement for a panel of this size. A pure function of it.

        Activity stays on the right whenever the workflow fits beside a usable
        log. Sources on top of the other two sections -- one vertical column
        (``wide``), or Resize Options beside Output & Run beneath it
        (``split``) -- is used only while the source browser, Sources'
        flexible region, still gets BROWSER_COMFORT_HEIGHT: a browser squeezed
        to a sliver would defeat the point of the layout. Otherwise Sources
        takes its own full-height column beside Resize Options over Output &
        Run (``columns`` -- the default and minimum windows). Only a panel too
        small for all three puts Activity underneath (``stacked``).
        """
        room_w = width - 2 * OUTER_PAD
        room_h = height - 2 * OUTER_PAD
        activity_floor = self._needs["activity_floor"]
        for mode in ("wide", "split", "columns"):
            flow_w, flow_floor = self._workflow_needs(mode)
            fits = (flow_w + COLUMN_GAP + ACTIVITY_MIN_WIDTH <= room_w
                    and max(flow_floor, activity_floor) <= room_h)
            comfortable = (mode == "columns"
                           or self._browser_height(mode, height) >= BROWSER_COMFORT_HEIGHT)
            if fits and comfortable:
                return mode
        return "stacked"

    def _left_width(self, width: int) -> int:
        """The workflow's width beside Activity: its natural width, or -- one
        vertical column on a wide window -- WORKFLOW_SHARE of the panel when
        that is more, never leaving Activity less than ACTIVITY_MIN_WIDTH."""
        mode = self._layout_mode or "columns"
        flow_w, _ = self._workflow_needs(mode)
        if mode != "wide":
            return flow_w
        room_w = width - 2 * OUTER_PAD
        share = int(room_w * WORKFLOW_SHARE)
        return max(flow_w, min(share, room_w - COLUMN_GAP - ACTIVITY_MIN_WIDTH))

    def _grid_workflow(self, mode: str) -> None:
        flow = self.workflow
        for index in (0, 1, 2, 3):
            flow.rowconfigure(index, weight=0, minsize=0)
        for index in (0, 1):
            flow.columnconfigure(index, weight=0, minsize=0)
        self._arrange_import_controls(mode == "columns")
        if mode == "columns":
            self.sources_section.grid(row=0, column=0, rowspan=3, columnspan=1,
                                      sticky="nsew", padx=(0, SECTION_GAP), pady=0)
            self.options_section.grid(row=0, column=1, columnspan=1, sticky="nsew",
                                      padx=0, pady=0)
            self.run_section.grid(row=1, column=1, columnspan=1, sticky="nsew",
                                  padx=0, pady=(SECTION_GAP, 0))
            flow.columnconfigure(0, weight=1)
            flow.rowconfigure(2, weight=1)
        else:
            self.sources_section.grid(row=0, column=0, rowspan=1, columnspan=2,
                                      sticky="nsew", padx=0, pady=0)
            flow.rowconfigure(0, weight=1, minsize=self._needs["sources"][1])
            if mode == "split":
                self.options_section.grid(row=1, column=0, columnspan=1, sticky="nsew",
                                          padx=(0, SECTION_GAP), pady=(SECTION_GAP, 0))
                self.run_section.grid(row=1, column=1, columnspan=1, sticky="nsew",
                                      padx=0, pady=(SECTION_GAP, 0))
                flow.columnconfigure(0, weight=1)
                flow.columnconfigure(1, weight=1)
            else:
                self.options_section.grid(row=1, column=0, columnspan=2, sticky="nsew",
                                          padx=0, pady=(SECTION_GAP, 0))
                self.run_section.grid(row=2, column=0, columnspan=2, sticky="nsew",
                                      padx=0, pady=(SECTION_GAP, 0))
                flow.columnconfigure(0, weight=1)
        # The browser is Sources' flexible region; everything else in the
        # section keeps its requested height.
        self.sources_section.rowconfigure(0, weight=1, minsize=self._needs["browser_floor"])
        self.sources_section.rowconfigure(1, weight=0)

    def _apply_layout(self, mode: str) -> None:
        """Grid the workflow and Activity for one arrangement, then set floors."""
        if self._needs is None:
            return
        self._grid_workflow(mode)
        for index in (0, 1):
            self.columnconfigure(index, weight=0, minsize=0)
            self.rowconfigure(index, weight=0, minsize=0)
        half = COLUMN_GAP // 2
        self.activity.rowconfigure(1, weight=1, minsize=self._needs["log_floor"])
        if mode == "stacked":
            self.workflow.grid(row=0, column=0, sticky="nsew",
                               padx=OUTER_PAD, pady=(OUTER_PAD, half))
            self.activity.grid(row=1, column=0, sticky="nsew",
                               padx=OUTER_PAD, pady=(COLUMN_GAP - half, OUTER_PAD))
            self.columnconfigure(0, weight=1)
            self.rowconfigure(0, weight=1)
            self.rowconfigure(1, weight=1, minsize=self._needs["activity_floor"])
        else:
            self.workflow.grid(row=0, column=0, sticky="nsew",
                               padx=(OUTER_PAD, half), pady=OUTER_PAD)
            self.activity.grid(row=0, column=1, sticky="nsew",
                               padx=(COLUMN_GAP - half, OUTER_PAD), pady=OUTER_PAD)
            self.columnconfigure(1, weight=1)
            self.rowconfigure(0, weight=1)
        self._layout_mode = mode
        self._size_columns()

    def _size_columns(self) -> None:
        """Beside Activity, fix the workflow column's width from the layout math
        -- never from ``grid`` weights, so the log, not the controls, takes the
        room a wider window adds."""
        if self._layout_mode in (None, "stacked") or self._needs is None:
            return
        minsize = self._left_width(self.winfo_width()) + OUTER_PAD + COLUMN_GAP // 2
        if int(self.grid_columnconfigure(0)["minsize"]) != minsize:
            self.columnconfigure(0, weight=0, minsize=minsize)

    def _rewrap(self) -> None:
        """Wrap the two prose captions to the width their section actually has,
        so a wide window shows them on one line and the minimum on several --
        never letting a caption decide a column's width (TTS's rule)."""
        if self._needs is None or self._layout_mode is None:
            return
        width = self.winfo_width()
        if width <= 1:
            return
        room_w = width - 2 * OUTER_PAD
        if self._layout_mode == "stacked":
            activity = room_w
        else:
            activity = room_w - COLUMN_GAP - self._left_width(width)
        button = self.btn_clear_log.winfo_reqwidth()
        note_wrap = max(ACTIVITY_NOTE_MIN_WRAP, activity - button - 40)
        if int(float(str(self.activity_note.cget("wraplength")) or 0)) != note_wrap:
            self.activity_note.configure(wraplength=note_wrap)
        if self._layout_mode == "wide":
            output_wrap = max(OUTPUT_NOTE_WRAP, self._left_width(width) - 30)
        else:
            output_wrap = OUTPUT_NOTE_WRAP
        if int(float(str(self.output_note.cget("wraplength")) or 0)) != output_wrap:
            self.output_note.configure(wraplength=output_wrap)

    def _reflow(self, force: bool = False) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1 or height <= 1 or self._needs is None:
            return
        mode = self._choose_layout(width, height)
        if force or mode != self._layout_mode:
            self._apply_layout(mode)
        else:
            self._size_columns()
        self._rewrap()

    def _on_panel_configure(self, event) -> None:
        if event.widget is self and not self._closed:
            self._reflow()

    @property
    def layout_mode(self) -> str | None:
        """The arrangement currently applied: ``wide``, ``split`` or ``stacked``."""
        return self._layout_mode

    # ------- teardown -------

    def close(self):
        """Close the import side and stop the pump. Idempotent, and safe late.

        A processing run is asked to stop first, which is what makes closing a
        *paused* run safe: the request wakes a worker waiting at a checkpoint, so
        the bounded join below finds a thread that is already unwinding rather
        than one that will never be woken.

        Closing the adapter cancels any running scan, joins its worker within
        the coordinator's bounded timeout and makes every later event inert;
        closing the browser releases every cached Tk image and drops its drain;
        closing the job adapter drops its drain and makes every later event
        inert; closing the pump cancels the outstanding callback and forgets
        every drain. Nothing is left scheduled and no image is left held.
        """
        if self._closed:
            return
        self._closed = True
        controller = self._controller
        if controller is not None and not controller.is_terminal:
            self._cancel_event.set()
            controller.request_cancel()
        worker = self._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(WORKER_JOIN_TIMEOUT)
        self._worker = None
        jobs = getattr(self, "jobs", None)
        if jobs is not None:
            jobs.close()
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.close()
        browser = getattr(self, "browser", None)
        if browser is not None:
            browser.close()
        pump = getattr(self, "_pump", None)
        if pump is not None:
            pump.close()

    def destroy(self):
        """Tear the panel down, and finish the teardown on this thread.

        The explicit collection is not tidiness. Destroying the shared job
        widgets leaves Tk variables in reference cycles, so they survive
        ``destroy`` and are freed later by the cyclic collector — which runs on
        whichever thread happens to cross its threshold. A Tk variable finalized
        off the main thread raises "main thread is not in main loop", and it
        surfaces in whatever unrelated code was running at the time. Collecting
        here, on the thread that owns the widgets, is the same discipline
        Phase 3 applied to its decoder threads: finish deterministically rather
        than leave it to chance.
        """
        self.close()
        super().destroy()
        gc.collect()

    # ------- worker (thread) -------

    def resize_worker(self, params: dict):
        """Resize every frozen item, cooperatively, on a worker thread.

        Touches no widget, no Tk variable and no object the main thread also
        mutates: everything it needs arrived in *params*, and everything it says
        goes out through the panel's queue and the run's reporter. **The
        estimator is deliberately not among its inputs** — it measures a duration
        and sends the number, because an estimator is mutable state that belongs
        to one thread. The job-control keys are all optional, so the same body
        still runs a plain, unreported batch when it is handed one.
        """
        files = params["files"]
        size = params["size"]
        letterbox = params["letterbox"]
        mode = params["mode"]
        planner = params["planner"]
        source_planner = params["source_planner"]
        item_ids = params.get("item_ids") or (None,) * len(files)
        destinations = params.get("destinations") or {}
        controller = params.get("controller")
        reporter = params.get("reporter")
        snapshot = params.get("snapshot")
        clock = params.get("clock")
        run_id = params.get("run_id")
        attempt = params.get("attempt", 0)
        timed = clock is not None and run_id is not None
        total = len(files)
        cancelled = False
        replaced = 0
        completed: list = []
        failures: list = []

        for idx, (item_id, in_file) in enumerate(zip(item_ids, files), start=1):
            # The one cooperative boundary, and it sits between images: a pause
            # asked for during a resize or a save is honoured here, not there.
            if controller is not None:
                if self._cancel_event.is_set():
                    controller.request_cancel()
                try:
                    controller.checkpoint()
                except ConversionCancelled:
                    cancelled = True
                    break
            elif self._cancel_event.is_set():
                cancelled = True
                break

            temp_out = None
            succeeded = False
            if reporter is not None and item_id is not None:
                reporter.current_item(item_id, f"Resizing {in_file.name}")
            # The measurement brackets this image's own work and nothing else —
            # planning its destination, writing it, and for a replacement
            # validating and installing it. Time the message then spends waiting
            # in the queue is outside the bracket, so a slow drain can never be
            # mistaken for a slow image.
            started = clock() if timed else None
            try:
                planned_name = in_file.stem + written_suffix(in_file.suffix)
                if mode == ACTION_REPLACE:
                    # A complete sibling is written first; the original stays
                    # untouched until the atomic install below succeeds.
                    temp_out = output_paths.temporary_sibling(
                        in_file, suffix=written_suffix(in_file.suffix)
                    )
                    final_out = in_file
                elif mode == ACTION_NUMBERED:
                    final_out = source_planner.plan_beside(in_file, name=planned_name)
                    output_paths.assert_not_input(final_out, files)
                elif item_id is not None and item_id in destinations:
                    # The destination this run planned before it started, which
                    # is also the one a retry of this item will use.
                    final_out = destinations[item_id]
                    output_paths.assert_not_input(final_out, files)
                    final_out.parent.mkdir(parents=True, exist_ok=True)
                else:
                    final_out = planner.plan(planned_name)
                    output_paths.assert_not_input(final_out, files)

                self._log_q.put(("log", f"\n[{idx}/{total}] Resizing:\n {in_file}\n -> {final_out}\n"))

                written = resize_for_audiobook(
                    in_file,
                    temp_out if temp_out is not None else final_out,
                    size=size,
                    letterbox=letterbox,
                )

                if mode == ACTION_REPLACE:
                    # Validate the finished image before installing it, so a
                    # truncated or unreadable write never reaches the original.
                    with Image.open(written) as check:
                        check.load()
                        if check.size != (size, size):
                            raise ValueError(
                                f"resized image is {check.size}, expected {(size, size)}"
                            )
                    output_paths.atomic_replace(written, final_out)
                    temp_out = None       # ownership transferred by the replace
                    replaced += 1

                self._log_q.put(("log", " ✓ Done\n"))
                succeeded = True
                if item_id is not None:
                    completed.append(item_id)

            except Exception as e:
                # Remove only this operation's own temporary artifact. The
                # original is byte-for-byte untouched, because the replacement
                # boundary was never crossed.
                try:
                    output_paths.discard_temporary(temp_out)
                except output_paths.OutputPathError:
                    pass
                self._log_q.put(("log", f" ✗ Error: {e}\n"))
                trouble = f"{in_file.name} could not be resized."
                detail = f"{type(e).__name__}: {e}"
                if snapshot is not None and item_id is not None:
                    failures.append(FailureRecord(
                        item_id=item_id, stage=STAGE_RESIZE,
                        display_message=trouble, technical_detail=detail,
                        retryable=True, snapshot_id=snapshot.snapshot_id))
                if reporter is not None and item_id is not None:
                    reporter.failure(trouble, detail, item_id=item_id,
                                     stage=STAGE_RESIZE)

            finally:
                # Read once, first, so nothing this block does is counted as
                # work. A unit that did not honestly complete is not history and
                # sends nothing at all.
                ended = clock() if timed else None
                if succeeded and started is not None:
                    self._log_q.put((TIMING_MESSAGE, TimingSample(
                        run_id=run_id, attempt=attempt, category=ETA_CATEGORY,
                        duration=float(ended) - float(started))))
                if reporter is None:
                    self._log_q.put(("progress", (idx, total)))
                else:
                    reporter.progress(idx, total, item_id=item_id, stage=STAGE_RESIZE)

        # Truthful about a partial batch: anything already installed stays
        # installed, and cancellation never rolls a completed replacement back.
        tail = ""
        if mode == ACTION_REPLACE:
            tail = (f"{replaced} of {total} original(s) replaced; "
                    "any not reached are unchanged.\n")

        if snapshot is not None:
            log = FailureLog(snapshot_id=snapshot.snapshot_id, records=tuple(failures))
            settled = RunResult.settle(snapshot, log, completed_ids=tuple(completed),
                                       cancelled=cancelled)
            if controller is not None:
                if cancelled:
                    final = controller.finish_cancelled()
                elif settled.state is JobState.COMPLETED_WITH_FAILURES:
                    final = controller.complete_with_failures()
                else:
                    final = controller.succeed()
                if reporter is not None:
                    if cancelled:
                        reporter.cancelled(final)
                    else:
                        reporter.completed(final)
            self._log_q.put((RESULT_MESSAGE, settled))

        if cancelled:
            self._log_q.put(("done", "\nCancelled. " + tail))
        else:
            self._log_q.put(("done", "\nAll done. " + tail))


def build_ui(parent: tk.Misc) -> CoverResizerUI:
    """Build the Cover Resizer UI into ``parent`` and return the frame."""
    ui = CoverResizerUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("900x640")
    root.minsize(900, 640)
    ui = build_ui(root)

    def _close():
        ui.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()


if __name__ == "__main__":
    main()
