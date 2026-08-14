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

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

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


def build_replacement_dialog(parent, title: str, message: str, confirm_label: str):
    """Build the confirmation window and return it, without waiting on it.

    Separated from :func:`_ask_replacement` purely so the suite can inspect the
    wording, the focused widget and each button's effect without driving a
    modal event loop, which is unreliable headlessly. The window carries its own
    ``result`` dict, so a test reads the same answer the modal caller would.
    """
    answer = {"ok": False}
    win = tk.Toplevel(parent)
    win.title(title)
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    win.resizable(False, False)

    body = ttk.Frame(win, padding=16)
    body.pack(fill=tk.BOTH, expand=True)
    label = ttk.Label(body, text=message, wraplength=460, justify="left")
    label.pack(anchor="w")
    win.label_message = label

    actions = ttk.Frame(body)
    actions.pack(anchor="e", pady=(16, 0))

    def cancel(*_a):
        answer["ok"] = False
        win.destroy()

    def confirm(*_a):
        answer["ok"] = True
        win.destroy()

    btn_cancel = ttk.Button(actions, text="Cancel", command=cancel)
    btn_cancel.pack(side=tk.RIGHT)
    btn_confirm = ttk.Button(actions, text=confirm_label, command=confirm)
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


def _ask_replacement(parent, title: str, message: str, confirm_label: str) -> bool:
    """A modal confirm whose safe answer is the default and holds focus.

    Deliberately not ``messagebox.askyesno``: the destructive action needs its
    own explicit label ("Replace 3 Original Files"), and Cancel must hold focus
    so a stray Enter cannot start a replacement. Escape and the window close
    both cancel, and the window is rebuilt for every run — there is nothing to
    remember, suppress or reuse.
    """
    win = build_replacement_dialog(parent, title, message, confirm_label)
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
    ("filename", "Filename", 220),
    ("dimensions", "Dimensions", 110),
    ("format", "Format", 80),
    ("size", "File size", 90),
    ("folder", "Folder", 300),
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
    ) -> None:
        self._guard = job_ui.MainThreadGuard(thread_id)
        self._manager = manager
        self._pump = pump
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
        self._anchor: str | None = None
        self._cursor: str | None = None
        self._tiles: tuple[str, ...] = ()
        self._tile_selection: tuple[str, ...] = ()
        self._workers: list[threading.Thread] = []

        self.cache = ThumbnailCache(
            limit=THUMBNAIL_CACHE_LIMIT if cache_limit is None else cache_limit)

        # --- widgets ------------------------------------------------------- #
        self.frame = ttk.LabelFrame(parent, text="Imported images")

        switch = ttk.Frame(self.frame)
        switch.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(4, 2))
        ttk.Label(switch, text="View:").pack(side=tk.LEFT)
        self.var_view = tk.StringVar(value=DEFAULT_VIEW)
        self.view_buttons: dict[str, ttk.Radiobutton] = {}
        for view_id, label in BROWSER_VIEWS:
            button = ttk.Radiobutton(
                switch, text=label, value=view_id, variable=self.var_view,
                command=lambda chosen=view_id: self.set_view(chosen))
            button.pack(side=tk.LEFT, padx=(8, 0))
            self.view_buttons[view_id] = button

        self.body = ttk.Frame(self.frame)
        self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
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
        self.simple.column("path", width=700, stretch=True)

        self.canvas = self._tile_canvas(VIEW_THUMBNAILS)

        for widget in (self.details, self.simple, self.canvas):
            self._bind_surface(widget)

        self._pages[DEFAULT_VIEW].tkraise()
        self._pump.add_drain(self.drain)
        self.placeholder = self._build_placeholder()
        self.refresh()

    # -- construction helpers ---------------------------------------------- #

    def _page(self, view_id: str) -> ttk.Frame:
        page = ttk.Frame(self.body)
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
                            selectmode="none", height=height)
        tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(page, orient="vertical", command=tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=bar.set)
        return tree

    def _tile_canvas(self, view_id: str) -> tk.Canvas:
        page = self._page(view_id)
        canvas = tk.Canvas(page, highlightthickness=0, takefocus=True,
                           background="white")
        canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=bar.set)
        return canvas

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
        self.request_visible()
        self._consume()
        return self._order

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
                    fill="#cde3f7", outline="#3b7dd8", tags=("tile", occurrence_id))
                painted.append(occurrence_id)
            self.canvas.create_image(
                left + cell // 2, top + cell // 2,
                image=self.tile_image(occurrence_id),
                tags=("tile", occurrence_id))
            source = self._sources.get(occurrence_id)
            if source is not None:
                self.canvas.create_text(
                    left + cell // 2, top + cell_height - THUMBNAIL_LABEL_HEIGHT // 2,
                    text=source.name, width=cell - 6, tags=("tile", occurrence_id))
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
    ):
        super().__init__(parent)

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
        self.importer = job_ui.ImportAdapter(
            self,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            # No theme bundle: this panel stays classic on Windows. Converting
            # it to the namespaced design system belongs to Plan 9, and an empty
            # style name is exactly what ttk means by "draw this the way the
            # platform draws it".
            theme=None,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=self._choose_files if choose_files is None else choose_files,
            choose_folder=self._choose_folder if choose_folder is None else choose_folder,
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            list_height=6,
        )
        self.importer.frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        # --- the three browser views (Decision 17A) ------------------------ #
        # A projection of the same manager, not a second list: the importer above
        # still owns Add, Remove, Clear and Move, and this shows what they did.
        # It rides the same pump — its drain is registered below, and it
        # schedules nothing of its own.
        self.browser = CoverBrowser(
            self,
            self._manager,
            pump=self._pump,
            runner=preview_runner,
            viewport=viewport,
            cache_limit=cache_limit,
            on_selection_change=self._on_browser_selection,
        )
        self.browser.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                                padx=10, pady=(0, 6))

        # Options
        options = ttk.LabelFrame(self, text="Resize Options (applies to all images)")
        options.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10, ipady=4)

        row = 0

        ttk.Label(options, text="Target size (square, px):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        self.var_size = tk.IntVar(value=TARGET_SIZE)
        self.entry_size = ttk.Spinbox(
            options, from_=256, to=4096, textvariable=self.var_size, width=6, increment=64
        )
        self.entry_size.grid(row=row, column=1, sticky="w", padx=8, pady=4)

        row += 1
        self.var_letterbox = tk.BooleanVar(value=True)
        self.chk_letterbox = ttk.Checkbutton(
            options,
            text="Keep full image (letterbox into square, no cropping)",
            variable=self.var_letterbox,
        )
        self.chk_letterbox.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4)
        )

        # --- source-side mode (Decision 10A) ---------------------------------
        # Off by default, and the safe numbered-copy action is preselected.
        # Replacement needs all three of: this toggle on, that radio chosen,
        # and the per-run confirmation accepted.
        row += 1
        self.var_source_side = tk.BooleanVar(value=False)
        self.chk_source_side = ttk.Checkbutton(
            options,
            text=SOURCE_SIDE_LABEL,
            variable=self.var_source_side,
            command=self._on_source_side_change,
        )
        self.chk_source_side.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2)
        )

        row += 1
        self.var_source_action = tk.StringVar(value=ACTION_NUMBERED)
        self.rb_numbered = ttk.Radiobutton(
            options,
            text="Create numbered copies",
            variable=self.var_source_action,
            value=ACTION_NUMBERED,
        )
        self.rb_numbered.grid(row=row, column=0, columnspan=3, sticky="w",
                              padx=(28, 8), pady=(0, 1))
        row += 1
        self.rb_replace = ttk.Radiobutton(
            options,
            text="Replace original files",
            variable=self.var_source_action,
            value=ACTION_REPLACE,
        )
        self.rb_replace.grid(row=row, column=0, columnspan=3, sticky="w",
                             padx=(28, 8), pady=(0, 8))
        self._on_source_side_change()

        row += 1
        ttk.Label(options, text="Output folder:").grid(
            row=row, column=0, sticky="e", padx=8, pady=(2, 2)
        )
        self.entry_outdir = ttk.Entry(
            options, textvariable=self.var_outdir, state="readonly"
        )
        self.entry_outdir.grid(row=row, column=1, columnspan=2, sticky="we",
                               padx=8, pady=(2, 2))
        row += 1
        ttk.Label(
            options,
            text="Each resize gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
        ).grid(row=row, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        # Start. Pause, Resume, Cancel and the retry control belong to the shared
        # control bar below, which offers each of them exactly when the approved
        # availability rules say it is meaningful.
        action = ttk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 6))
        self.btn_convert = ttk.Button(action, text="Resize Covers", command=self.start_resize)
        self.btn_convert.pack(side=tk.LEFT)

        # The shared run controls, progress, estimate and Summary/Details live
        # here. The adapter is rebuilt for each run — one run, one event stream,
        # one estimate — so this container holds its place in the layout.
        self.job_area = ttk.Frame(self)
        self.job_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        # The panel's own run log, unchanged. It is the raw transcript of what the
        # worker did; Summary and Details above are the shared projections of the
        # run's events, and neither is a copy of the other.
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))

        self.log = tk.Text(logf, height=4, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        # The worker->GUI queue is a drain on the one pump, not a second chain.
        self._pump.add_drain(self._drain_worker_queue)
        self._install_jobs(IDLE_RUN_ID, ())
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
        self.jobs = job_ui.JobAdapter(
            self.job_area,
            run_id=run_id,
            pump=self._pump,
            # No theme bundle: this panel stays classic on Windows until Plan 9.
            theme=None,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            item_ids=item_ids,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel,
            on_retry=self.retry_failed,
            details_height=6,
        )
        self.jobs.frame.pack(fill=tk.BOTH, expand=True)
        # One progress model, not two: the panel's indicator *is* the shared
        # status view's, so nothing can draw a second, disagreeing bar.
        self.progress = self.jobs.status.indicator
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
            "estimator": self._estimator,
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

    def log_write(self, text: str):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)

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
                elif kind == RESULT_MESSAGE:
                    self._settle(payload)
                elif kind == "done":
                    self.log_write(payload)
                    self._finish_idle()
        except queue.Empty:
            pass

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

        Touches no widget and no Tk variable: everything it needs arrived in
        *params*, and everything it says goes out through the panel's queue and
        the run's reporter. The four job-control keys are optional, so the same
        body still runs a plain, unreported batch when it is handed one.
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
        estimator = params.get("estimator")
        snapshot = params.get("snapshot")
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
            if estimator is not None:
                estimator.begin(ETA_CATEGORY)
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
                if estimator is not None:
                    # A unit that did not honestly complete is not history.
                    if succeeded:
                        estimator.complete()
                    else:
                        estimator.discard()
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
