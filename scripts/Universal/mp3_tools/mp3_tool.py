#!/usr/bin/env python3
"""MP3 Tool — a multi-book MP3 metadata editor and processor.

v0.6.3 focused MP3 redesign, Phase 4: the workspace UI. This is the first
production panel to adopt the shared Plan 6 multi-book workspace, composed with
the Plan 3 importer and job-control adapters and the Phase 3 MP3 model:

- ``Import Folder`` scans one parent directory through the shared
  ``ImportCoordinator`` and projects the committed snapshot into **one Book per
  directory that directly contains MP3s** (``mp3_workflow.import_folder``);
  ``Add Files`` puts every chosen MP3 into the **current** Book in dialog order
  (``mp3_workflow.add_files``). The panel owns no second list of paths — every
  track shown is the current Book's immutable ``ImportedFileSnapshot``.
- Previous / Next / ``Book X of Y`` / the direct selector / Add / Duplicate /
  Remove are the shared ``BookNavigator``; every press is routed to the Plan 6
  model operation and the result is rendered back. Book identity is the stable
  Plan 6 id; the visible number is a position.
- The Shared area is exactly five fields — Artist / Author, Album Artist /
  Author, Album, Add/Remove Time at End of Each Track (seconds), Book Artwork.
  The four text fields are the shared ``SharedMetadataSurface`` in its compact
  ``rows`` layout; artwork is this panel's own Choose / Clear / preview control,
  once for Shared and once for the Book. A populated Shared value disables the
  matching Book control and leaves the Book's stored value intact — the disabled
  set is ``book_workspace.disabled_fields``, asked, never recomputed here.
- Per Book: the same fields, Auto-number, Start #, a Chapter Titles box (one
  title per line), the track list with Add Files / Move Up / Move Down / Remove
  Selected, per-field *Mixed source metadata* markers and a compact status.
- Exactly two processing actions — **Write ID3 Tags** and **Combine MP3s → One
  MP3** — beside the shared Pause / Resume / Cancel / Retry Failed bar, one
  global progress view and one Summary / Details log region.

What this phase does **not** do: no FFmpeg is run, no tag is written, no artwork
is embedded, no run directory is reserved, no run is frozen and nothing is
retried. The two processing buttons validate the workspace (Start #, signed
Time) and say plainly that processing is not available yet. The proven FFmpeg
helpers below (concat lists, FAST/Safe concat, WAV normalisation, signed-time
append/trim, timestamp text) are kept verbatim for the processing phases; the
panel does not call them.

Removed with the single-book form, as the focused plan directs: the global file
list, the Book-level Title field, ``Silence between tracks``, the FAST checkbox,
the standalone ``Apply to All Files`` time action, the combined-filename popup
and the ad-hoc status queue.

Presentation: on Windows every widget asks ``job_ui.style_name`` for the
approved ``ACT.*`` design-system style; on macOS and the classic branch the same
lookup returns ``""`` and the panel is drawn natively. No colour, font or metric
is declared here. Nothing scrolls the whole tool: the track list, the Chapter
Titles box and the log scroll locally and give up height first.
"""

import shlex
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/mp3_tool.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import ffmpeg_utils
from shared import image_capabilities
from shared import job_ui
from shared import output_paths
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared import ui_theme
from shared.book_workspace import (
    SharedMetadata,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    has_meaningful_work,
    next_book,
    previous_book,
    remove_book,
    select_book,
    set_shared_metadata,
)
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface
from shared.import_coordination import (
    TERMINAL_STATUSES,
    ImportCoordinator,
    ImportOutcome,
    ImportPoller,
    OutcomeStatus,
    StartOutcome,
)
from shared.importing import (
    IdFactory,
    ImportOptions,
    ImportRoot,
    ImportedFileManager,
    RootKind,
    ScanRequest,
)
from shared.job_control import ControlKind, JobState
from shared.job_ui import LockGroup, MainThreadGuard, MainThreadPump, style_name
from mp3_tools import mp3_workflow as wf

# Optional dependency for the artwork preview, exactly as the M4B Maker treats it.
try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - Pillow is a pinned requirement
    Image = ImageTk = None

APP_TITLE = "MP3 Tool"

# Auto-named output folder slug (v0.1.1): every processing run lands in
# <output base>/MP3-Tool-Outputs/MP3-Tool-N through the shared service. The
# imported MP3s are read-only.
TOOL_KEY = "mp3_tool"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json key (input dir only remembers the dialog location; the output
# folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
KEY_INPUT_DIR = "mp3_tool.input_dir"

#: The artwork preview is a display-only thumbnail: the selected file is never
#: resized, cropped or rewritten, and what is embedded later is the file itself.
PREVIEW_MAX = (56, 56)

#: The compact status shown for the current Book. Phase 4 has no run, so every
#: Book is ready; later phases derive Processing / Completed / Failed / Skipped
#: from the frozen run result rather than from a second state machine.
STATUS_READY = "Ready"

MIXED_MARK = "Mixed source metadata"

#: Characters of Album / folder hint shown after ``Book N`` before eliding.
HINT_LIMIT = 40

#: How many Summary and Details lines the log region keeps visible.
LOG_LIMIT = 400


# ---------------------------
# Utilities
# ---------------------------


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def ensure_ffmpeg_available() -> bool:
    """True only when a proved, pinned pair is active.

    Every FFmpeg-backed operation in this tool -- concat, duration probing,
    normalisation, silence generation, time edits -- is gated on this. A merely
    discovered pair is not enough: it was never executed.
    """
    return ffmpeg_utils.verified_ffmpeg()


def run_ff(args: List[str]) -> Tuple[int, str, str]:
    """Run ffmpeg/ffprobe and return (code, stdout, stderr) as text."""
    try:
        from subprocess import PIPE

        p = sp.run(args, stdout=PIPE, stderr=PIPE, text=True)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 999, "", f"Subprocess failed: {e}"


def save_error_log(folder: Path, title: str, args: List[str], stderr: str):
    """Write (append) a minimal ffmpeg_log.txt only on error."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "ffmpeg_log.txt"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {title} ---\n")
            f.write("CMD: " + " ".join(shlex.quote(a) for a in args) + "\n")
            if stderr:
                f.write(stderr.strip() + "\n")
    except Exception:
        pass


def ffmpeg_escape_listfile_path(p: Path) -> str:
    """Serialise one path as a concat-demuxer ``file`` directive.

    These are **not** shell rules. Per ffmpeg's documented syntax ("Quoting and
    escaping"), every character between single quotes is literal — a backslash
    inside them escapes nothing. So a quote cannot be written ``\\'``: ffmpeg
    would read it as the closing quote and silently truncate the path at that
    point. The documented form closes the quote, emits an escaped quote outside
    it, and reopens::

        file '/mnt/share/file 3'\\''.wav'

    Because everything else inside the quotes is literal, Windows backslashes,
    spaces and non-ASCII characters need no treatment at all. The previous
    version doubled backslashes as well; that survived only because Windows
    collapses repeated path separators, and it corrupted any real backslash.

    A newline cannot be represented — the demuxer parses one directive per line.
    Windows forbids newlines in names outright, so this only rejects a pathological
    POSIX name rather than writing a listfile ffmpeg would misread.
    """
    text = str(p)
    if "\n" in text or "\r" in text:
        raise ValueError(f"a line break cannot appear in a concat list entry: {text!r}")
    return "file '" + text.replace("'", "'\\''") + "'"


def write_concat_listfile(paths: List[Path], listfile: Path):
    """Write the concat list as UTF-8 — ffmpeg reads these names as UTF-8."""
    with listfile.open("w", encoding="utf-8", newline="\n") as f:
        for p in paths:
            f.write(ffmpeg_escape_listfile_path(p) + "\n")


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    code, out, _ = run_ff(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if code == 0:
        try:
            return float(out.strip())
        except Exception:
            return None
    return None


def seconds_to_hms(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if h > 0 else f"{m:02d}:{s:06.3f}"


# ---------------------------
# FAST PATH (metadata stripped)
# ---------------------------


def concat_mp3s_fast(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "FAST PATH concat_mp3s_fast", args, err)
    return code == 0


# ---------------------------
# SAFE PATH (WAV normalize + optional gaps)
# ---------------------------


def normalize_to_wav(in_path: Path, out_wav: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"normalize_to_wav: {in_path.name}", args, err)
    return code == 0


def make_silence_wav(seconds: float, out_wav: Path, log_dir: Path) -> bool:
    seconds = max(0.0, float(seconds))
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        f"{seconds:.6f}",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "make_silence_wav", args, err)
    return code == 0


def concat_wavs_to_mp3(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "SAFE PATH concat_wavs_to_mp3", args, err)
    return code == 0


# ---------------------------
# Time edit helpers (always strip metadata)
# ---------------------------


def add_silence_to_mp3(in_mp3: Path, seconds: float, out_mp3: Path, log_dir: Path) -> bool:
    seconds = max(0.0, float(seconds))
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-f",
        "lavfi",
        "-t",
        f"{seconds:.6f}",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-filter_complex",
        "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map",
        "[a]",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"add_silence_to_mp3: {in_mp3.name}", args, err)
    return code == 0


def trim_from_end_mp3(in_mp3: Path, seconds_to_remove: float, out_mp3: Path, log_dir: Path) -> bool:
    seconds_to_remove = max(0.0, float(seconds_to_remove))
    dur = ffprobe_duration_seconds(in_mp3) or 0.0
    new_dur = max(0.0, dur - seconds_to_remove)
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-t",
        f"{new_dur:.6f}",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"trim_from_end_mp3: {in_mp3.name}", args, err)
    return code == 0


# ---------------------------
# GUI
# ---------------------------


class _ArtworkControl:
    """Book Artwork: a caption, a small preview and Choose / Clear. MP3-owned.

    Deliberately **not** a ``SharedMetadataSurface`` field: artwork is a file, not
    a line of text, so it gets its own control drawn once for Shared and once for
    the current Book. Whether the Book copy is enabled is the model's Decision 20B
    answer (``disabled_fields``) combined with the run lock, in the same two-reason
    shape the surface uses — clearing one reason never wrongly enables a control
    the other still holds.

    The preview is a display-only thumbnail scaled in memory; the selected file
    is never opened for writing, resized or rewritten.
    """

    def __init__(self, parent, *, caption: str, theme, shared: bool,
                 on_choose, on_clear) -> None:
        self.caption = caption
        self.path = ""
        self.has_preview = False
        self._overridden = False
        self._locked = False
        self._closed = False
        self._image = None
        self._on_choose = on_choose
        self._on_clear = on_clear

        self.frame = ttk.Frame(
            parent, style=style_name(theme, "shared_surface" if shared else "surface"))
        self.caption_label = ttk.Label(
            self.frame, text=caption,
            style=style_name(theme, "shared_label" if shared else "label"))
        self.preview = ttk.Label(
            self.frame, text="(none)", anchor="center", width=7,
            style=style_name(theme, "shared_secondary" if shared else "secondary_label"))
        self.btn_choose = ttk.Button(self.frame, text="Choose…", width=7,
                                     style=style_name(theme, "button"),
                                     command=self._choose)
        self.btn_clear = ttk.Button(self.frame, text="Clear", width=5,
                                    style=style_name(theme, "button"),
                                    command=self._clear)
        # Two rows only -- caption, then the two buttons side by side -- with
        # the preview spanning both on the left, so the control is no taller
        # than a label and an entry and the band it sits in stays compact.
        self.preview.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        self.caption_label.grid(row=0, column=1, columnspan=2, sticky="w")
        self.btn_choose.grid(row=1, column=1, sticky="ew")
        self.btn_clear.grid(row=1, column=2, sticky="ew", padx=(4, 0))

    def _choose(self) -> None:
        if not self._closed and self._usable():
            self._on_choose()

    def _clear(self) -> None:
        if not self._closed and self._usable():
            self._on_clear()

    @property
    def enabled(self) -> bool:
        """Usable only when **neither** reason holds — override or run lock."""
        return not (self._overridden or self._locked)

    def _usable(self) -> bool:
        return self.enabled

    def set_path(self, path: str) -> None:
        """Show *path*'s preview, or the no-artwork placeholder for blank."""
        self.path = str(path or "")
        self._image = None
        self.has_preview = False
        if not self.path:
            self.preview.configure(image="", text="(none)")
            return
        if Image is None or ImageTk is None:
            self.preview.configure(image="", text="(no preview)")
            return
        try:
            with Image.open(self.path) as opened:
                thumb = opened.copy()
            thumb.thumbnail(PREVIEW_MAX)
            self._image = ImageTk.PhotoImage(thumb)
            self.preview.configure(image=self._image, text="")
            self.has_preview = True
        except Exception:
            self.preview.configure(image="", text="(no preview)")

    def set_enabled(self, enabled: bool) -> None:
        """The Shared-override reason. ``set_locked`` is the run reason."""
        self._overridden = not bool(enabled)
        self._apply_state()

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._apply_state()

    def _apply_state(self) -> None:
        state = "normal" if self._usable() and not self._closed else "disabled"
        for button in (self.btn_choose, self.btn_clear):
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def close(self) -> None:
        self._closed = True
        self._apply_state()
        self._image = None


class MP3ToolUI(ttk.Frame):
    """The MP3 Tool as an embeddable frame: a multi-book workspace."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        theme=None,
        clock=None,
        effective_config=None,
        id_factory: IdFactory | None = None,
        scanner=None,
        thread_factory=None,
        choose_files=None,
        choose_folder=None,
        choose_artwork=None,
        confirm_broad_root=None,
        confirm_large_result=None,
        confirm=None,
        home=None,
        reader=None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog, clock,
        thread or tag reader — the injection points the Converter, Cover and TTS
        panels already expose. Production passes none of them.
        """
        if theme is None:
            theme = ui_theme.apply_theme(parent.winfo_toplevel(), ttk.Style(parent))
        super().__init__(parent, style=style_name(theme, "window"))
        self.theme = theme
        self._guard = MainThreadGuard()
        self._closed = False
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None
                                  else effective_config)
        self._ids = IdFactory("mp3-") if id_factory is None else id_factory
        self._reader = wf.read_source_tags if reader is None else reader
        self._choose_files = self._ask_files if choose_files is None else choose_files
        self._choose_folder = self._ask_folder if choose_folder is None else choose_folder
        self._choose_artwork = (self._ask_artwork if choose_artwork is None
                                else choose_artwork)
        self._confirm = self._ask_confirm if confirm is None else confirm
        self._confirm_large = (self._confirm_large_result
                               if confirm_large_result is None
                               else confirm_large_result)

        # --- the workspace: the Plan 6 snapshot and the Phase 3 store -------- #
        # The one mutable reference to the current immutable workspace lives
        # here. Every edit asks a model operation and renders the value back;
        # nothing below mutates a book in place.
        self.workspace: WorkspaceSnapshot = wf.new_workspace(id_factory=self._ids)
        self.store = wf.ObservationStore()
        # The user-facing Book number, by stable id. Assigned once, the first
        # time a Book appears in the workspace, and never reused while that
        # workspace lives: remove Book 1 of three and the survivors stay Book 2
        # and Book 3. A folder import replaces every Book, so numbering starts
        # again at 1 for the new set. This is a display fact hung off the real
        # identity — never a key anything else is stored by.
        self.book_numbers: dict[str, int] = {}
        self._rendering = False
        self._summary: list[str] = []
        self._details: list[str] = []

        # --- the shared importing foundation ----------------------------- #
        # One pump owns every scheduled callback; the scan poller rides it.
        # The manager is a *scratch* commit target for the shared coordinator:
        # a folder scan or a file selection is committed through it, projected
        # into Books, and the manager is cleared before the next import. The
        # Books are the only list; the manager is never rendered.
        self._pump = MainThreadPump(self)
        self._manager = ImportedFileManager(id_factory=self._ids)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=self._ids,
            confirm_broad_root=(self._confirm_broad_root
                                if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )
        self._poller = ImportPoller(
            self._coordinator, self._pump.schedule, cancel=self._pump.cancel,
            interval_ms=self._pump.interval_ms, on_outcome=self._handle_outcome)
        self._import_kind: str | None = None

        # Where the next run will go, shown read-only. Reserving the numbered
        # run folder is the processing phases' job; nothing is created here.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self._build(theme)

        # Run locking is the shared contract. Idle now; the processing phases
        # apply real job states through this same group.
        self.lock_group = LockGroup()
        self._tracks_lock = self._ButtonLock(
            self.btn_add_files, self.btn_move_up, self.btn_move_down,
            self.btn_remove_tracks)
        self._import_lock = self._ButtonLock(self.btn_import_folder)
        self._book_options_lock = self._ButtonLock(
            self.btn_write_id3, self.btn_combine, self.check_auto_number,
            self.entry_start_number)
        self.lock_group.register(ControlKind.IMPORTED_INPUT, self.navigator,
                                 self._tracks_lock, self._import_lock)
        self.lock_group.register(ControlKind.PROCESSING_OPTION, self.surface,
                                 self.shared_artwork, self.book_artwork,
                                 self._book_options_lock)
        self.lock_group.register(ControlKind.JOB_CONTROL, self.controls)
        self.lock_group.register(ControlKind.PROGRESS_STATUS, self.status)
        self.lock_group.register(ControlKind.LOG_VIEW, self.log)
        self.lock_group.apply(JobState.IDLE)
        self.controls.apply(JobState.IDLE)

        self.render()
        if not ensure_ffmpeg_available():
            self.status.set_status(
                "WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.")
        else:
            self.status.set_status(STATUS_READY)
        self._pump.start()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _build(self, theme) -> None:
        pad = 10
        self.columnconfigure(0, weight=1)
        # Pinned rows keep their requested height; the two variable-length
        # regions -- tracks/chapters and the log -- absorb a short window, so
        # at 920x600 the actions row never falls off the bottom and no
        # whole-panel scrollbar is needed.
        self.rowconfigure(0, weight=0)   # Import Folder, import status, output
        self.rowconfigure(1, weight=0)   # navigator
        self.rowconfigure(2, weight=0)   # Shared + Current Book
        self.rowconfigure(3, weight=3)   # tracks | chapter titles -- scroll
        self.rowconfigure(4, weight=0)   # actions, job controls, progress
        self.rowconfigure(5, weight=2)   # the one log region -- scrolls

        # -- row 0: workspace-level import ------------------------------ #
        top = ttk.Frame(self, style=style_name(theme, "window"))
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 4))
        top.columnconfigure(1, weight=1)
        self.btn_import_folder = ttk.Button(
            top, text="Import Folder", style=style_name(theme, "button"),
            command=self.import_folder)
        self.btn_import_folder.grid(row=0, column=0, sticky="w")
        self.import_status = job_ui.ImportStatusBar(
            top, theme=theme, on_cancel=self.cancel_import)
        self.import_status.frame.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        self.output_label = ttk.Label(
            top, textvariable=self.var_outdir, anchor="e",
            style=style_name(theme, "secondary_label"))
        self.output_label.grid(row=0, column=2, sticky="e")

        # -- row 1: the shared navigator --------------------------------- #
        self.navigator = BookNavigator(
            self, theme=theme, describe=self._describe, label_for=self._label_for,
            on_previous=self.on_previous, on_next=self.on_next,
            on_add=self.on_add, on_duplicate=self.on_duplicate,
            on_remove=self.on_remove, on_select=self.on_select)
        self.navigator.frame.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, 4))

        # -- row 2: Shared above Current Book ----------------------------- #
        text_fields = tuple(
            (key, wf.FIELD_LABELS[key]) for key in wf.SHARED_FIELDS if key != "artwork")
        self.surface = SharedMetadataSurface(
            self, text_fields, theme=theme, layout="rows",
            show_header=False, entry_width=12,
            shared_title="Shared — applies to every Book and overrides its own value",
            book_title="Current Book",
            on_shared_change=self.on_shared_change,
            on_book_change=self.on_book_change)
        self.surface.frame.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, 6))
        field_columns = len(text_fields)
        # Widget padding, not a style: the theme's card padding suits a card,
        # and two stacked bands of it would spend the height the track list
        # needs at the 920x600 minimum. The style (and its colours) is unchanged.
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(8, 2))

        # Artwork sits beside the four text fields in each group. It is this
        # panel's own control, not a surface field.
        self.shared_artwork = _ArtworkControl(
            self.surface.shared_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=theme, shared=True, on_choose=self.choose_shared_artwork,
            on_clear=self.clear_shared_artwork)
        self.shared_artwork.frame.grid(row=0, column=field_columns, rowspan=2,
                                       sticky="nw", padx=(12, 0))
        self.book_artwork = _ArtworkControl(
            self.surface.book_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=theme, shared=False, on_choose=self.choose_book_artwork,
            on_clear=self.clear_book_artwork)
        self.book_artwork.frame.grid(row=0, column=field_columns, rowspan=4,
                                     sticky="nw", padx=(12, 0))

        # Mixed-source markers, one under each observed scalar of the Book.
        self.mixed_labels: dict[str, ttk.Label] = {}
        for column, key in enumerate(wf.SCALAR_FIELDS):
            marker = ttk.Label(self.surface.book_frame, text="",
                               style=style_name(theme, "warning_label"))
            marker.grid(row=2, column=column, sticky="w")
            self.mixed_labels[key] = marker

        # Auto-number | Start # | status, on one row of the Book group.
        options = ttk.Frame(self.surface.book_frame, style=style_name(theme, "surface"))
        options.grid(row=3, column=0, columnspan=field_columns, sticky="ew", pady=(4, 0))
        self.var_auto_number = tk.BooleanVar(master=self, value=wf.DEFAULT_AUTO_NUMBER)
        self.check_auto_number = ttk.Checkbutton(
            options, text="Auto-number tracks", variable=self.var_auto_number,
            style=style_name(theme, "checkbutton"), command=self.on_auto_number)
        self.check_auto_number.grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Start # (blank → 1):",
                  style=style_name(theme, "label")).grid(
            row=0, column=1, sticky="w", padx=(16, 4))
        self.var_start_number = tk.StringVar(master=self, value="")
        self.entry_start_number = ttk.Entry(
            options, textvariable=self.var_start_number, width=6,
            style=style_name(theme, "entry"))
        self.entry_start_number.grid(row=0, column=2, sticky="w")
        self._start_trace = self.var_start_number.trace_add(
            "write", lambda *_a: self.on_start_number())
        ttk.Label(options, text="Status:", style=style_name(theme, "label")).grid(
            row=0, column=3, sticky="w", padx=(16, 4))
        self.status_label = ttk.Label(options, text=STATUS_READY,
                                      style=style_name(theme, "status_label"))
        self.status_label.grid(row=0, column=4, sticky="w")

        # -- row 3: tracks | chapter titles ------------------------------- #
        middle = ttk.Frame(self, style=style_name(theme, "window"))
        middle.grid(row=3, column=0, sticky="nsew", padx=pad, pady=(0, 6))
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)

        tracks = ttk.Labelframe(middle, text="MP3 Tracks (this Book)",
                                style=style_name(theme, "labelframe"),
                                padding=(6, 2))
        tracks.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tracks.columnconfigure(0, weight=1)
        tracks.rowconfigure(0, weight=1)
        self.track_list = tk.Listbox(tracks, selectmode="extended",
                                     exportselection=False, height=3, width=24,
                                     activestyle="none")
        track_scroll = ttk.Scrollbar(tracks, orient="vertical",
                                     command=self.track_list.yview,
                                     style=style_name(theme, "vscrollbar"))
        self.track_list.configure(yscrollcommand=track_scroll.set)
        self.track_list.grid(row=0, column=0, sticky="nsew")
        track_scroll.grid(row=0, column=1, sticky="ns")
        ui_theme.style_tk_widget(self.track_list, theme, role="list")
        ui_theme.enable_mousewheel(self.track_list)
        track_buttons = ttk.Frame(tracks, style=style_name(theme, "surface"))
        track_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.btn_add_files = ttk.Button(track_buttons, text="Add Files",
                                        style=style_name(theme, "button"),
                                        command=self.add_files)
        self.btn_move_up = ttk.Button(track_buttons, text="Move Up",
                                      style=style_name(theme, "button"),
                                      command=self.move_up)
        self.btn_move_down = ttk.Button(track_buttons, text="Move Down",
                                        style=style_name(theme, "button"),
                                        command=self.move_down)
        self.btn_remove_tracks = ttk.Button(track_buttons, text="Remove Selected",
                                            style=style_name(theme, "button"),
                                            command=self.remove_selected_tracks)
        for column, button in enumerate((self.btn_add_files, self.btn_move_up,
                                         self.btn_move_down, self.btn_remove_tracks)):
            button.grid(row=0, column=column, padx=(0 if column == 0 else 4, 0))

        chapters = ttk.Labelframe(middle, text="Chapter Titles — one title per line",
                                  style=style_name(theme, "labelframe"),
                                  padding=(6, 2))
        chapters.grid(row=0, column=1, sticky="nsew")
        chapters.columnconfigure(0, weight=1)
        chapters.rowconfigure(0, weight=1)
        self.chapter_text = tk.Text(chapters, height=3, width=24, wrap="none",
                                    undo=True)
        chapter_scroll = ttk.Scrollbar(chapters, orient="vertical",
                                       command=self.chapter_text.yview,
                                       style=style_name(theme, "vscrollbar"))
        self.chapter_text.configure(yscrollcommand=chapter_scroll.set)
        self.chapter_text.grid(row=0, column=0, sticky="nsew")
        chapter_scroll.grid(row=0, column=1, sticky="ns")
        ui_theme.style_tk_widget(self.chapter_text, theme, role="text")
        ui_theme.enable_mousewheel(self.chapter_text)
        self.chapter_text.bind("<KeyRelease>", self.on_chapter_edit)
        self._suspend_chapters = False
        self._chapter_baseline = ""

        # -- row 4: the two actions, the shared job controls, progress ----- #
        actions = ttk.Frame(self, style=style_name(theme, "window"))
        actions.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, 6))
        actions.columnconfigure(2, weight=1)
        self.btn_write_id3 = ttk.Button(
            actions, text="Write ID3 Tags", style=style_name(theme, "primary_button"),
            command=self.write_id3_tags)
        self.btn_write_id3.grid(row=0, column=0, sticky="w")
        self.btn_combine = ttk.Button(
            actions, text="Combine MP3s → One MP3",
            style=style_name(theme, "primary_button"), command=self.combine_mp3s)
        self.btn_combine.grid(row=0, column=1, sticky="w", padx=(8, 16))
        self.controls = job_ui.JobControlBar(
            actions, theme=theme,
            on_pause=self.on_pause, on_resume=self.on_resume,
            on_cancel=self.on_cancel, on_retry=self.on_retry)
        self.controls.frame.grid(row=0, column=2, sticky="e")
        # The progress view has three rows of its own (bar, stage and ETA,
        # status) and the control bar four buttons; side by side they exceed
        # the 920px minimum, so the view takes the full width beneath.
        self.status = job_ui.JobStatusView(actions, theme=theme,
                                           progress_length=240)
        # Per-instance restyling only, the way the M4B Metadata Editor does
        # it: the shared ``ProgressIndicator`` itself stays generic because
        # the unconverted panels build their own from the same class, and a
        # converted panel must not carry generic widgets inside its design
        # system. On aqua and classic every name below is ``""``.
        self.status.indicator.frame.configure(style=style_name(theme, "card"))
        self.status.indicator.bar.configure(style=style_name(theme, "progressbar"))
        self.status.indicator.label.configure(style=style_name(theme, "status_label"))
        self.status.frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        # -- row 5: the one log region ----------------------------------- #
        # Two requested lines: the log is the region that yields first at the
        # 920x600 minimum, and it grows with the window like the track list.
        self.log = job_ui.SummaryDetailsView(self, theme=theme,
                                             height=2)
        self.log.frame.grid(row=5, column=0, sticky="nsew", padx=pad, pady=(0, pad))

    # -- lock seams for the panel's own buttons ---------------------------- #

    class _ButtonLock:
        """Registers a set of this panel's own buttons with the shared group."""

        def __init__(self, *buttons) -> None:
            self.buttons = buttons

        def set_locked(self, locked: bool) -> None:
            for button in self.buttons:
                try:
                    button.configure(state="disabled" if locked else "normal")
                except tk.TclError:
                    pass

    # ------------------------------------------------------------------ #
    # Dialog and confirmation seams (main thread, before any worker)
    # ------------------------------------------------------------------ #

    def _remember(self, path: Path) -> None:
        settings.set(KEY_INPUT_DIR, str(path))

    def _ask_files(self):
        chosen = tuple(filedialog.askopenfilenames(
            parent=self, title="Select MP3 files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("MP3 files", "*.mp3"), ("All files", "*.*")]))
        if chosen:
            self._remember(Path(chosen[0]).parent)
        return chosen

    def _ask_folder(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Select a folder of MP3 audiobooks",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)), mustexist=True)
        if not chosen:
            return ()
        self._remember(Path(chosen))
        return (str(chosen),)

    def artwork_filetypes(self) -> list:
        """The chooser filter, from the shared capability probe, never a list."""
        patterns = " ".join(f"*{s}" for s in image_capabilities.decodable_suffixes())
        return [("Images", patterns), ("All files", "*.*")]

    def _ask_artwork(self) -> str:
        chosen = filedialog.askopenfilename(
            parent=self, title="Select Book Artwork",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=self.artwork_filetypes())
        return str(chosen or "")

    def _ask_confirm(self, title: str, message: str) -> bool:
        return job_ui.ask_confirm(self, title, message)

    def _confirm_broad_root(self, roots) -> bool:
        listed = "\n".join(str(entry) for entry in roots)
        return self._confirm(
            "Scan a very broad folder?",
            "This covers a whole drive or your home folder:\n\n"
            f"{listed}\n\nScanning it can take a long time. Continue?")

    def _confirm_large_result(self, outcome) -> bool:
        return self._confirm(
            "Import a large number of MP3s?",
            f"{outcome.proposed_count:,} MP3 files are ready to be imported.\n\n"
            "Importing this many at once can make the workspace slow. Import them?")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _describe(self, book) -> str:
        return wf.display_hint(self.workspace.shared, book)

    def _label_for(self, book, _position: int) -> str:
        """``Book <stable number>``, with the Album / folder hint when there is one.

        A long hint is elided so the heading beside the navigator buttons stays
        one readable line at the 920px minimum; the number, which is what keeps
        two Books apart, is never shortened.
        """
        number = self.book_numbers.get(book.book_id, "?")
        hint = self._describe(book)
        if len(hint) > HINT_LIMIT:
            hint = hint[:HINT_LIMIT - 1].rstrip() + "…"
        return f"Book {number} — {hint}" if hint else f"Book {number}"

    def _assign_book_numbers(self) -> None:
        """Number every Book that has none, in workspace order; forget the gone.

        When no current Book is numbered the set was replaced wholesale -- a
        folder import, or removing the last Book, which leaves the model's one
        fresh pristine Book -- so numbering starts again at 1: there is no
        survivor whose identity a reused number could blur. Otherwise a newcomer
        takes the next number after the highest ever given, and a removed
        Book's number is never handed to anyone else.
        """
        ids = [book.book_id for book in self.workspace.books]
        if not any(book_id in self.book_numbers for book_id in ids):
            self.book_numbers = {}
        highest = max(self.book_numbers.values(), default=0)
        for book_id in ids:
            if book_id not in self.book_numbers:
                highest += 1
                self.book_numbers[book_id] = highest
        # Forgetting the gone: their numbers stay retired because ``highest``
        # was taken before they were dropped.
        self.book_numbers = {book_id: number for book_id, number in self.book_numbers.items()
                             if book_id in ids}

    def render(self) -> None:
        """Show the current workspace. Every value comes from the snapshot."""
        self._guard.require("render")
        if self._closed:
            return
        self._rendering = True
        try:
            space = self.workspace
            book = space.current
            self._assign_book_numbers()
            self.navigator.render(space)
            self.surface.render(space)
            overridden = disabled_fields(space.shared)
            self.shared_artwork.set_path(str(space.shared.values.get("artwork", "")))
            self.book_artwork.set_path(str(book.configuration.get("artwork", "")))
            self.book_artwork.set_enabled("artwork" not in overridden)
            self._render_tracks()
            self._render_chapters()
            self.var_auto_number.set(wf.auto_number_enabled(book))
            if self.var_start_number.get() != wf.start_number_text(book):
                self.var_start_number.set(wf.start_number_text(book))
            self._render_mixed()
            self.status_label.configure(text=STATUS_READY)
        finally:
            self._rendering = False

    def _render_light(self) -> None:
        """After a per-Book text edit: what the edit can change, and no more."""
        if self._closed:
            return
        self._assign_book_numbers()
        self.navigator.render(self.workspace)

    def _render_tracks(self, selection=()) -> None:
        book = self.workspace.current
        self.track_list.delete(0, "end")
        for entry in book.files.files:
            self.track_list.insert("end", entry.name)
        wanted = set(selection)
        for row, entry in enumerate(book.files.files):
            if entry.occurrence_id in wanted:
                self.track_list.selection_set(row)
                self.track_list.see(row)

    def _chapter_display(self) -> str:
        """Stored Chapter Titles text; until the user edits it, the defaults.

        Section 15.3: the editor is populated with each track's automatic Title
        on import. Those defaults are *displayed*, not stored — so reordering
        tracks re-orders the display, and a Book the user never edited keeps an
        empty configuration. The first real edit stores the whole box.
        """
        book = self.workspace.current
        if "chapter_titles" in book.configuration:
            return wf.chapter_titles_text(book)
        return "\n".join(wf.default_titles(book, self.store))

    def _render_chapters(self) -> None:
        raw = self._chapter_display()
        self._chapter_baseline = raw
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return
        self._suspend_chapters = True
        try:
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
        finally:
            self._suspend_chapters = False

    def _render_mixed(self) -> None:
        summary = wf.summary_for(self.workspace.current, self.store)
        mixed = wf.mixed_fields(summary)
        for key, marker in self.mixed_labels.items():
            marker.configure(text=MIXED_MARK if key in mixed else "")

    # -- read-back seams --------------------------------------------------- #

    def shared_field_keys(self) -> tuple:
        return self.surface.fields + ("artwork",)

    def book_status_text(self) -> str:
        return str(self.status_label.cget("text"))

    def mixed_text(self, name: str) -> str:
        return str(self.mixed_labels[name].cget("text"))

    def chapter_titles_text(self) -> str:
        return self.chapter_text.get("1.0", "end-1c")

    # ------------------------------------------------------------------ #
    # Applying model results
    # ------------------------------------------------------------------ #

    def _apply(self, mutation) -> bool:
        if mutation.changed:
            self.workspace = mutation.workspace
        self.render()
        return mutation.changed

    def _say(self, line: str, detail: str = "") -> None:
        """One Summary line, optionally with a Details line beneath it."""
        self._summary.append(line)
        self._details.append(detail or line)
        del self._summary[:-LOG_LIMIT]
        del self._details[:-LOG_LIMIT]
        if not self._closed:
            self.log.set_summary(self._summary)
            self.log.set_details(self._details)

    # ------------------------------------------------------------------ #
    # Navigator callbacks
    # ------------------------------------------------------------------ #

    def on_previous(self) -> None:
        self._apply(previous_book(self.workspace))

    def on_next(self) -> None:
        self._apply(next_book(self.workspace))

    def on_select(self, book_id: str) -> None:
        self._apply(select_book(self.workspace, book_id))

    def on_add(self) -> None:
        self._apply(add_book(self.workspace, id_factory=self._ids))

    def on_duplicate(self) -> None:
        self._apply(duplicate_book(self.workspace, id_factory=self._ids))

    def on_remove(self, meaningful: bool) -> None:
        """Decision 50A: the model answered; this panel decides to ask."""
        if meaningful and not self._confirm(
                "Remove this Book?",
                "This Book has imported MP3s or edited settings.\n\nRemove it anyway?"):
            return
        self._apply(remove_book(self.workspace, id_factory=self._ids))

    # ------------------------------------------------------------------ #
    # Shared and Book field callbacks
    # ------------------------------------------------------------------ #

    def on_shared_change(self, field: str, raw: str) -> None:
        if self._rendering:
            return
        values = dict(self.workspace.shared.values)
        values[field] = raw
        self._apply(set_shared_metadata(
            self.workspace, SharedMetadata(wf.SHARED_FIELDS, values)))

    def on_book_change(self, field: str, raw: str) -> None:
        if self._rendering:
            return
        mutation = wf.set_book_field(self.workspace, field, raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def set_book_field(self, name: str, value) -> None:
        """Store one raw Book value and show it. The model owns the write."""
        self._guard.require("set_book_field")
        self._apply(wf.set_book_field(self.workspace, name, value))

    def on_auto_number(self) -> None:
        if self._rendering:
            return
        self._apply(wf.set_book_field(self.workspace, "auto_number",
                                      bool(self.var_auto_number.get())))

    def on_start_number(self) -> None:
        if self._rendering or self._closed:
            return
        raw = self.var_start_number.get()
        if raw == wf.start_number_text(self.workspace.current):
            return
        mutation = wf.set_book_field(self.workspace, "start_number", raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def type_start_number(self, raw: str) -> None:
        self.var_start_number.set(raw)

    def on_chapter_edit(self, _event=None) -> None:
        if self._suspend_chapters or self._rendering or self._closed:
            return
        raw = self.chapter_text.get("1.0", "end-1c")
        if raw == self._chapter_baseline:
            return
        self._chapter_baseline = raw
        mutation = wf.set_book_field(self.workspace, "chapter_titles", raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def type_chapter_titles(self, raw: str) -> None:
        """Type into the Chapter Titles box as a person would, then report it."""
        self.chapter_text.delete("1.0", "end")
        if raw:
            self.chapter_text.insert("1.0", raw)
        self.on_chapter_edit()

    # -- artwork ----------------------------------------------------------- #

    def choose_shared_artwork(self) -> None:
        self._guard.require("choose_shared_artwork")
        chosen = str(self._choose_artwork() or "")
        if chosen:
            self.on_shared_change("artwork", chosen)

    def clear_shared_artwork(self) -> None:
        self._guard.require("clear_shared_artwork")
        self.on_shared_change("artwork", "")

    def choose_book_artwork(self) -> None:
        self._guard.require("choose_book_artwork")
        if not self.book_artwork.enabled:
            return
        chosen = str(self._choose_artwork() or "")
        if chosen:
            self.set_book_field("artwork", chosen)

    def clear_book_artwork(self) -> None:
        self._guard.require("clear_book_artwork")
        if not self.book_artwork.enabled:
            return
        self.set_book_field("artwork", "")

    # ------------------------------------------------------------------ #
    # Tracks
    # ------------------------------------------------------------------ #

    def selected_occurrences(self) -> tuple:
        files = self.workspace.current.files.files
        return tuple(files[int(row)].occurrence_id
                     for row in self.track_list.curselection()
                     if int(row) < len(files))

    def select_tracks(self, *rows: int) -> None:
        self.track_list.selection_clear(0, "end")
        for row in rows:
            self.track_list.selection_set(row)

    def _move(self, direction: int) -> None:
        selected = self.selected_occurrences()
        if not selected:
            return
        mutation = wf.move_tracks(self.workspace, selected, direction)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_tracks(selected)
        self._render_chapters()
        self._render_light()

    def move_up(self) -> None:
        self._guard.require("move_up")
        self._move(wf.UP)

    def move_down(self) -> None:
        self._guard.require("move_down")
        self._move(wf.DOWN)

    def remove_selected_tracks(self) -> None:
        self._guard.require("remove_selected_tracks")
        selected = self.selected_occurrences()
        if not selected:
            return
        self._apply(wf.remove_tracks(self.workspace, selected))

    # ------------------------------------------------------------------ #
    # Importing
    # ------------------------------------------------------------------ #

    def _request(self, roots: tuple) -> ScanRequest:
        return ScanRequest(
            request_id=self._ids.next_id("req"),
            roots=roots,
            catalog=wf.MP3_CATALOG,
            options=ImportOptions.for_catalog(wf.MP3_CATALOG),
            effective_config=self._effective_config,
            created_at=self._clock(),
        )

    def import_folder(self) -> None:
        """Workspace-level: scan one parent folder, then replace the Books."""
        self._guard.require("import_folder")
        if self._closed or self._coordinator.is_active:
            return
        if any(has_meaningful_work(book) for book in self.workspace.books):
            if not self._confirm(
                    "Replace the current Books?",
                    "Import Folder replaces every Book in the workspace with the "
                    "folders it finds.\n\nReplace them?"):
                return
        chosen = tuple(self._choose_folder() or ())
        if not chosen:
            return
        roots = tuple(
            ImportRoot(root_id=self._ids.next_id("root"), path=Path(entry),
                       order=order, kind=RootKind.FOLDER)
            for order, entry in enumerate(chosen))
        self._manager.clear()
        self._import_kind = "folder"
        report = self._coordinator.start(self._request(roots))
        if report.outcome is StartOutcome.STARTED:
            self.import_status.set_scanning(0)
            self._poller.start()
            return
        self._import_kind = None
        self.import_status.set_idle(report.display_message)
        self._say(f"Import Folder: {report.display_message}")

    def add_files(self) -> None:
        """Into the current Book, in the order the dialog returned them."""
        self._guard.require("add_files")
        if self._closed or self._coordinator.is_active:
            return
        paths_chosen = tuple(self._choose_files() or ())
        if not paths_chosen:
            return
        root = ImportRoot(root_id=self._ids.next_id("root"), path=None, order=0,
                          kind=RootKind.DIRECT_FILES)
        self._manager.clear()
        self._import_kind = "files"
        outcome = self._coordinator.import_files(self._request((root,)), paths_chosen)
        self._handle_outcome(outcome)

    def cancel_import(self) -> bool:
        self._guard.require("cancel_import")
        if self._closed:
            return False
        cancelled = self._coordinator.request_cancel()
        if cancelled:
            self.import_status.set_cancelling()
        return cancelled

    def _handle_outcome(self, outcome: ImportOutcome) -> ImportOutcome:
        if self._closed:
            return outcome
        status = outcome.status
        if status is OutcomeStatus.RUNNING:
            self.import_status.set_scanning(outcome.discovered_count)
            return outcome
        if status is OutcomeStatus.AWAITING_CONFIRMATION:
            self.import_status.set_message(
                f"{outcome.proposed_count:,} files found — waiting for confirmation…")
            if self._confirm_large(outcome):
                return self._handle_outcome(self._coordinator.confirm_pending())
            return self._handle_outcome(self._coordinator.decline_pending())
        if status in TERMINAL_STATUSES or status is OutcomeStatus.CLOSED:
            self._poller.stop()
            kind, self._import_kind = self._import_kind, None
            self.import_status.set_idle(outcome.display_message)
            if status is OutcomeStatus.COMMITTED and outcome.commit is not None:
                self._project_import(kind, outcome)
            else:
                label = "Import Folder" if kind == "folder" else "Add Files"
                self._say(f"{label}: {outcome.display_message}",
                          outcome.technical_detail or outcome.display_message)
            for problem in outcome.problems:
                self._say(f"  {problem.display_message}",
                          f"  {problem.technical_detail or problem.display_message}")
            return outcome
        if status in (OutcomeStatus.BUSY, OutcomeStatus.NO_TYPES_SELECTED):
            self.import_status.set_message(outcome.display_message)
        return outcome

    def _project_import(self, kind: str | None, outcome: ImportOutcome) -> None:
        """The committed snapshot becomes Books (folder) or tracks (files)."""
        commit = outcome.commit
        if kind == "folder":
            result = wf.import_folder(
                self.workspace, commit.snapshot, id_factory=self._ids,
                store=self.store, reader=self._reader)
            self.store = result.store
            self._apply(result.mutation)
            books = [book for book in self.workspace.books if not book.files.is_empty]
            total = sum(book.file_count for book in books)
            self._say(f"Import Folder: {total} MP3 file(s) in {len(books)} Book(s).")
            return
        held = set(self.workspace.current.files.identities)
        additions = tuple(entry for entry in commit.added if entry.identity not in held)
        skipped = len(commit.added) - len(additions)
        result = wf.add_files(self.workspace, additions, store=self.store,
                              reader=self._reader)
        self.store = result.store
        self._apply(result.mutation)
        note = f" {skipped} already in this Book were skipped." if skipped else ""
        self._say(f"Add Files: {len(additions)} MP3 file(s) added to "
                  f"{self.navigator.position_text}.{note}")

    # ------------------------------------------------------------------ #
    # The processing seams
    # ------------------------------------------------------------------ #

    def write_id3_tags(self) -> bool:
        self._guard.require("write_id3_tags")
        return self._request_operation("Write ID3 Tags")

    def combine_mp3s(self) -> bool:
        self._guard.require("combine_mp3s")
        return self._request_operation("Combine MP3s → One MP3")

    def _request_operation(self, label: str) -> bool:
        """Validate the workspace and say what would run. Nothing runs yet.

        The processing pipelines, the frozen run capture and the run directory
        arrive in later phases; this phase must not fake any of them.
        """
        if self._closed:
            return False
        space = self.workspace
        eligible = []
        for position, book in enumerate(space.books, start=1):
            try:
                wf.parse_start_number(wf.start_number_text(book))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Start # for Book {position}: {exc}",
                                     parent=self)
                return False
            try:
                wf.parse_time_delta(
                    str(wf.effective_scalars(space.shared, book).get("time_delta", "")))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Time for Book {position}: {exc}",
                                     parent=self)
                return False
            if not book.files.is_empty:
                eligible.append(book)
        if not eligible:
            messagebox.showwarning(APP_TITLE, "Import a folder or add MP3 files first.",
                                   parent=self)
            return False
        self._say(f"{label}: {len(eligible)} Book(s) ready. Processing is not available "
                  "in this build yet; nothing was written.")
        return False

    # -- job-control shell: nothing runs, so nothing can be paused or retried --

    def on_pause(self) -> None:
        pass

    def on_resume(self) -> None:
        pass

    def on_cancel(self) -> None:
        pass

    def on_retry(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Cancel any scan, stop the pump, close every component. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for component in (self._poller, self.navigator, self.surface,
                          self.shared_artwork, self.book_artwork, self.controls,
                          self.status, self.log, self.import_status, self.lock_group):
            try:
                component.close()
            except Exception:
                pass
        try:
            self._coordinator.close()
        except Exception:
            pass
        try:
            self._pump.close()
        except Exception:
            pass
        try:
            self.var_start_number.trace_remove("write", self._start_trace)
        except (tk.TclError, ValueError):
            pass


def build_ui(parent: tk.Misc, theme=None) -> MP3ToolUI:
    """Build the MP3 Tool UI into ``parent`` and return the frame.

    ``theme`` is optional and backwards-compatible: the launcher's existing
    ``build_ui(container)`` call keeps working, and the panel resolves the
    platform theme itself when nothing is passed.
    """
    ui = MP3ToolUI(parent, theme=theme)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry(ui_theme.DEFAULT_GEOMETRY)
    root.minsize(*ui_theme.MIN_SIZE)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
