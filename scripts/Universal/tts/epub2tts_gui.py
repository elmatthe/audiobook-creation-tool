"""Desktop GUI for the PDF / TXT → MP3 audiobook engine — one unified queue.

The module and package names (``epub2tts_gui``, ``tts.epub2tts_edge``) are the upstream
project's names and are kept deliberately — see ``files/archived-code/epub-tts/README.md``
for the documented compatibility boundary. EPUB itself was retired as an application input
by maintainer decision on 2026-08-11; PDF and TXT are the only supported types.

v0.6.1 Plan 4 Phase 6 replaced this panel's two input models — a Single-file browse
box and a Batch-folder browse box, chosen with a mode radio — with **one unified
PDF/TXT queue** built on the shared Plan 3 importing foundation (drop §4.5, decisions
1A and 2A). The :class:`~shared.importing.ImportedFileManager` is now the only
authority on which files a run converts, in what order; nothing here keeps a parallel
list, and nothing here rediscovers a folder.

The panel also stopped being a closure. ``build_ui(parent)`` used to be a single
function holding ~30 ``tk.*Var``s in scope, which gave the shared adapters nothing to
attach a lifetime to. It is now :class:`TtsPanel`, a frame that owns its importer, its
one :class:`~shared.job_ui.MainThreadPump`, and a ``close()`` that tears both down.
``build_ui`` itself is unchanged from the launcher's point of view.

**Provenance selects the processing path**, which is exactly the distinction the
retired radio used to make. A directly added file is a file the user pointed at, so it
takes the rich chapter/pause engine and lands flat in the run (Decision 31A). A file
found under an imported folder is one of many, so it takes the chunked batch worker and
mirrors its folder's shape (Decision 7A); several folders each keep their own container
(Decision 41A). Both kinds live in one queue and convert in **one** run.

The conversion engines themselves are untouched: ``run_conversion_job``,
``convert_single_pdf``, ``kokoro_file_to_mp3`` and ``pdf_to_txt`` are consumed exactly
as they were, with their timing constants, retry counts and per-source temp-chunk
isolation unchanged.
"""

from __future__ import annotations

import contextlib
import io
import queue
import shutil
import sys
import tempfile
import threading
import time
try:
    import tkinter as tk
except (ImportError, ModuleNotFoundError) as _tk_err:  # Tk-less / headless Python
    sys.stderr.write(
        "\n[Audiobook Creation Tool] The graphical interface cannot start because\n"
        "this Python build has no working Tk (tkinter) support.\n\n"
        "To enable the window, install Tk and relaunch:\n"
        "  - macOS (Homebrew):  brew install python-tk@3.12\n"
        "  - then double-click Setup_and_Run-audiobook-creation-tool again.\n\n"
        f"(details: {_tk_err})\n"
    )
    raise SystemExit(1)
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Ensure the scripts/ root is importable so `tts.*` resolves whether this GUI is
# run directly (python scripts/tts/epub2tts_gui.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import ffmpeg_utils
from shared import job_ui
from shared import output_paths

#: Central tool identifier for the shared output services.
TOOL_KEY = "tts"
from shared.cancellation import ConversionCancelled
from shared.import_coordination import ImportCoordinator
from shared.importing import (
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
    planning_groups,
)
from shared.output_paths import plan_flat, plan_mirrored, plan_multi_root
from shared.ui_theme import ProgressIndicator, enable_mousewheel
from tts.epub2tts_edge.epub2tts_edge import (
    DEFAULT_CHAPTER_PAUSE_MS,
    DEFAULT_END_OF_BOOK_PAUSE_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_SENTENCE_PAUSE_MS,
    DEFAULT_SPEAKER,
    DEFAULT_TITLE_PAUSE_MS,
    DEFAULT_TRIM_SILENCE_DB,
    ensure_punkt,
)
from tts.voice_registry import (
    DEFAULT_VOICE_LABEL,
    get_voice,
    display_labels,
)

#: How long ``close()`` waits for a conversion worker to unwind.
WORKER_JOIN_TIMEOUT = 5.0


def build_catalog() -> SupportedTypeCatalog:
    """The two input types this tool accepts, and the only two (drop §4.1).

    There is no EPUB entry, no EPUB extension and no probe behind this: PDF and
    TXT are unconditional, so the offered set is the same on every machine.
    """
    return SupportedTypeCatalog((
        SupportedType("pdf", "PDF document", (".pdf",)),
        SupportedType("txt", "Text file", (".txt",)),
    ))


def _parse_pause_ms(raw: str, label: str) -> int:
    try:
        v = int(str(raw).strip())
    except ValueError as e:
        raise ValueError(f"{label} must be a whole number (milliseconds).") from e
    if v < 0 or v > 10000:
        raise ValueError(f"{label} must be between 0 and 10000 ms.")
    return v


def _parse_trim_dbfs(raw: str, label: str) -> float:
    try:
        v = float(str(raw).strip())
    except ValueError as e:
        raise ValueError(f"{label} must be a number (dBFS).") from e
    if v > -30.0 or v < -90.0:
        raise ValueError(f"{label} must be between -90 and -30 dBFS.")
    return v


def direct_output_name(source: Path, speaker: str) -> str:
    """The filename the rich Edge engine will actually write for a direct file.

    ``make_mp3`` names its artifact ``<stem> (<speaker>).mp3`` and the runner moves
    that name into the destination directory, so a destination has to be planned
    under it. Planning ``<stem>.mp3`` would reserve a name nothing occupies and
    leave the real one unchecked.
    """
    return f"{Path(source).stem} ({speaker}).mp3"


def mp3_output_name(source: Path) -> str:
    """``<stem>.mp3`` — what the batch worker and the Kokoro path both write."""
    return f"{Path(source).stem}.mp3"


def plan_destinations(snapshot, run_root: Path, *, direct_rename, grouped_rename,
                      planner=None) -> list:
    """Where every occurrence of *snapshot* writes inside *run_root*.

    :func:`~shared.importing.planning_groups` is the only bridge from the imported
    queue to Plan 2, and the three approved planners are the only things that decide
    a destination: directly chosen files land flat (Decision 31A), one folder root
    mirrors its relative parents (Decision 7A), and several roots each get their own
    collision-safe container (Decision 41A).

    All of them share one :class:`~shared.output_paths.DestinationPlanner`, so a flat
    file and a mirrored file can never be planned onto the same path, and ``Book.pdf``
    chosen twice from two folders becomes two destinations rather than one overwritten
    one. Nothing is created here: this reserves no directory and opens no file.

    Returns one ``(source, destination, is_direct)`` triple per occurrence, in the
    manager's own order for the direct half and root order for the grouped half —
    which is the order :func:`planning_groups` itself presents them in.
    """
    root = Path(run_root)
    tracker = output_paths.DestinationPlanner(root) if planner is None else planner
    groups = planning_groups(snapshot)

    items: list[tuple[Path, Path, bool]] = []
    if groups.direct:
        plan = plan_flat(root, groups.direct, planner=tracker, rename=direct_rename)
        items.extend((item.source, item.destination, True) for item in plan.items)
    if groups.grouped:
        if groups.needs_multi_root:
            plan = plan_multi_root(root, groups.grouped, planner=tracker,
                                   rename=grouped_rename)
        else:
            source_root, group_sources = groups.grouped[0]
            plan = plan_mirrored(root, group_sources, source_root, planner=tracker,
                                 rename=grouped_rename)
        items.extend((item.source, item.destination, False) for item in plan.items)
    return items


class TtsPanel(ttk.Frame):
    """The TTS tool as an embeddable, state-owning frame.

    Every keyword below is a **seam with a production default**, present so the
    suite can drive a real panel deterministically — a fake dialog, a stub thread
    factory, an injected clock, an in-memory configuration — without a display
    server, a real home directory or a real broad filesystem root. The launcher
    passes none of them.
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
    ):
        super().__init__(parent)
        ffmpeg_utils.configure_pydub()

        self._closed = False

        # Conversion plumbing. This event belongs to the *processing* run and to
        # nothing else: the import side's own cancellation goes to the coordinator
        # and never reaches it, and this one never reaches the coordinator.
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker = None

        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None else effective_config)

        # ---- Tk state ---------------------------------------------------- #
        # Where the next run will go, shown read-only. The numbered run folder is
        # reserved atomically when a validated conversion starts, so building this
        # panel creates nothing and promises no run number. The base is changed in
        # Preferences & Data.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        # Preferences & Data can change the base while this panel is alive; the
        # shared registry re-points this display the moment that happens.
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self.bitrate_var = tk.StringVar(value="192k")
        self.voice_var = tk.StringVar(value=DEFAULT_SPEAKER)
        self.overwrite_var = tk.BooleanVar(value=True)
        self.workers_var = tk.StringVar(value="2")
        self.resume_var = tk.BooleanVar(value=True)
        self.rate_var = tk.StringVar(value="+0%")
        self.sentence_ms_var = tk.StringVar(value=str(DEFAULT_SENTENCE_PAUSE_MS))
        self.paragraph_ms_var = tk.StringVar(value=str(DEFAULT_PARAGRAPH_PAUSE_MS))
        self.title_ms_var = tk.StringVar(value=str(DEFAULT_TITLE_PAUSE_MS))
        self.chapter_ms_var = tk.StringVar(value=str(DEFAULT_CHAPTER_PAUSE_MS))
        self.end_pause_var = tk.StringVar(value=str(DEFAULT_END_OF_BOOK_PAUSE_MS))
        self.trim_edge_chunks_var = tk.BooleanVar(value=True)
        self.trim_dbfs_var = tk.StringVar(value=str(int(DEFAULT_TRIM_SILENCE_DB)))
        self.kokoro_speed_var = tk.StringVar(value="1.0")
        self.selected_voice_label = tk.StringVar(value=DEFAULT_VOICE_LABEL)

        # ---- the shared importing foundation ------------------------------ #
        # One pump owns this panel's whole scheduled-callback chain: the import
        # poller rides its `schedule` seam and the conversion worker's queue is
        # registered as a drain. There is no second `after` loop.
        self._pump = job_ui.MainThreadPump(self)
        self.import_catalog = build_catalog()
        self._manager = ImportedFileManager(id_factory=id_factory)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=id_factory,
            # Handed to the coordinator rather than the adapter deliberately: the
            # coordinator asks it *before* it creates a thread, so a decline starts
            # no worker at all.
            confirm_broad_root=(self._confirm_broad_root if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )

        # ---- layout ------------------------------------------------------- #
        # The imported queue sits OUTSIDE the scrollable options area, alongside
        # the action buttons and the log, so Add and Remove stay reachable however
        # far the form is scrolled. The form itself is untouched: this tool's
        # options are ~1300 px of controls against ~660 px of visible window, so
        # they still live in a vertically scrollable canvas.
        self.rowconfigure(0, weight=0)   # the imported queue — fixed, always visible
        self.rowconfigure(1, weight=1)   # scrollable options grow with the window
        self.rowconfigure(2, weight=0)   # action buttons — fixed, always visible
        self.rowconfigure(3, weight=0)   # log box — fixed height, always visible
        self.columnconfigure(0, weight=1)

        self.importer = job_ui.ImportAdapter(
            self,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            # No theme bundle: this panel stays classic on Windows. Converting it to
            # the namespaced design system belongs to Plan 9, and an empty style name
            # is exactly what ttk means by "draw this the way the platform draws it".
            theme=None,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=self._choose_files if choose_files is None else choose_files,
            choose_folder=(self._choose_folder if choose_folder is None
                           else choose_folder),
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            list_height=6,
        )
        self.importer.frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        canvas_wrap = ttk.Frame(self)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        options_canvas = tk.Canvas(canvas_wrap, highlightthickness=0, borderwidth=0)
        options_canvas.grid(row=0, column=0, sticky="nsew")
        options_sb = ttk.Scrollbar(
            canvas_wrap, orient="vertical", command=options_canvas.yview
        )
        options_sb.grid(row=0, column=1, sticky="ns")
        options_canvas.configure(yscrollcommand=options_sb.set)

        frm = ttk.Frame(options_canvas, padding=10)
        _frm_window = options_canvas.create_window((0, 0), window=frm, anchor="nw")
        frm.columnconfigure(1, weight=1)

        def _sync_scrollregion(_event: object | None = None) -> None:
            options_canvas.configure(scrollregion=options_canvas.bbox("all"))

        def _sync_form_width(event: object) -> None:
            # Make the form fill the canvas width so "ew" rows expand as before.
            options_canvas.itemconfigure(_frm_window, width=event.width)

        frm.bind("<Configure>", _sync_scrollregion)
        options_canvas.bind("<Configure>", _sync_form_width)

        # The launcher reuses one root across tools, so wheel binding is scoped to
        # while the pointer is over this panel (the wrap frame, not the canvas —
        # the form frame covers the canvas, so the canvas itself almost never gets
        # the pointer).
        enable_mousewheel(options_canvas, hover_region=canvas_wrap)

        r = 0
        ttk.Label(frm, text="Output folder").grid(
            row=r, column=0, sticky="nw", pady=(8, 0))
        outf = ttk.Frame(frm)
        outf.grid(row=r, column=1, sticky="ew", pady=(8, 0))
        outf.columnconfigure(0, weight=1)
        self.entry_outdir = ttk.Entry(outf, textvariable=self.var_outdir,
                                      state="readonly")
        self.entry_outdir.grid(row=0, column=0, sticky="ew")
        r += 1
        ttk.Label(
            frm,
            text="Each conversion gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
        ).grid(row=r, column=1, sticky="w", pady=(2, 0))
        r += 1

        # Both option groups used to be named for the retired modes. They now name
        # the halves of the one queue they actually govern; what each setting does
        # is unchanged.
        opts = ttk.LabelFrame(frm, text="MP3 options — files added directly",
                              padding=8)
        opts.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        opts.columnconfigure(1, weight=1)
        r += 1
        sr = 0
        ttk.Label(opts, text="MP3 bitrate").grid(row=sr, column=0, sticky="w",
                                                 pady=(6, 0))
        self.combo_bitrate = ttk.Combobox(
            opts,
            textvariable=self.bitrate_var,
            values=("128k", "192k", "320k"),
            width=10,
            state="readonly",
        )
        self.combo_bitrate.grid(row=sr, column=1, sticky="w", pady=(6, 0))
        sr += 1

        pause_frm = ttk.LabelFrame(
            frm,
            text="Pause timing — files added directly (milliseconds)",
            padding=8,
        )
        pause_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        pr = 0
        ttk.Checkbutton(
            pause_frm,
            text=(
                "Trim Edge TTS padding on sentence clips only (chapter title clip is "
                "never trimmed; title/chapter pauses below still apply)"
            ),
            variable=self.trim_edge_chunks_var,
        ).grid(row=pr, column=0, columnspan=2, sticky="w")
        pr += 1
        ttk.Label(
            pause_frm,
            text=("Trim threshold (dBFS; more negative = trim less, keeps slightly "
                  "more pause)"),
        ).grid(row=pr, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(
            pause_frm,
            from_=-90,
            to=-35,
            increment=1,
            textvariable=self.trim_dbfs_var,
            width=8,
        ).grid(row=pr, column=1, sticky="w", padx=(12, 0), pady=(6, 0))
        pr += 1
        pause_rows = [
            ("Between sentences (within a paragraph)", self.sentence_ms_var),
            ("After each paragraph block", self.paragraph_ms_var),
            ("After spoken chapter title", self.title_ms_var),
            ("Before merging last paragraph of chapter", self.chapter_ms_var),
            ("End of recording (final silence)", self.end_pause_var),
        ]
        for lbl, var in pause_rows:
            ttk.Label(pause_frm, text=lbl).grid(row=pr, column=0, sticky="w",
                                                pady=(4, 0))
            ttk.Spinbox(
                pause_frm,
                from_=0,
                to=10000,
                increment=50,
                textvariable=var,
                width=8,
            ).grid(row=pr, column=1, sticky="w", padx=(12, 0), pady=(4, 0))
            pr += 1
        ttk.Label(
            pause_frm,
            text=(
                "Defaults: 800 ms between sentences; 850 ms after each paragraph "
                "block; 1200 ms after chapter title; 2000 ms before last paragraph "
                "merge; 3000 ms end silence; trim at -58 dBFS. Folder speech rate "
                "+0%. Try -62 dBFS if audio still feels too tight."
            ),
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=pr, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1

        batch_opts = ttk.LabelFrame(
            frm, text="Options for files imported from a folder", padding=8)
        batch_opts.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        br = 0
        ttk.Label(batch_opts, text="Workers").grid(row=br, column=0, sticky="w")
        self.spin_workers = ttk.Spinbox(
            batch_opts, from_=1, to=16, textvariable=self.workers_var, width=6)
        self.spin_workers.grid(row=br, column=1, sticky="w")
        br += 1
        ttk.Label(batch_opts, text="Speech rate").grid(row=br, column=0, sticky="w",
                                                       pady=(6, 0))
        ttk.Entry(batch_opts, textvariable=self.rate_var, width=10).grid(
            row=br, column=1, sticky="w", pady=(6, 0)
        )
        br += 1
        ttk.Checkbutton(batch_opts, text="Resume (skip existing MP3s)",
                        variable=self.resume_var).grid(
            row=br, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        r += 1

        voice_frm = ttk.LabelFrame(frm, text="Voice", padding=8)
        voice_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        voice_frm.columnconfigure(1, weight=1)

        ttk.Label(voice_frm, text="Voice / Engine").grid(row=0, column=0, sticky="w")
        self.voice_combo = ttk.Combobox(
            voice_frm,
            textvariable=self.selected_voice_label,
            values=display_labels(),
            state="readonly",
            width=52,
        )
        self.voice_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.backend_label_var = tk.StringVar(value="")
        ttk.Label(voice_frm, textvariable=self.backend_label_var,
                  foreground="navy").grid(row=1, column=0, columnspan=2, sticky="w",
                                          pady=(4, 0))

        self.kokoro_speed_frm = ttk.Frame(voice_frm)
        self.kokoro_speed_frm.grid(row=2, column=0, columnspan=2, sticky="w",
                                   pady=(6, 0))
        ttk.Label(self.kokoro_speed_frm, text="Kokoro speed (0.5 – 2.0):").pack(
            side=tk.LEFT)
        ttk.Spinbox(
            self.kokoro_speed_frm,
            from_=0.5,
            to=2.0,
            increment=0.05,
            textvariable=self.kokoro_speed_var,
            width=8,
            format="%.2f",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            self.kokoro_speed_frm,
            text="  (1.0 = normal; <1.0 slower; >1.0 faster)",
            foreground="gray",
        ).pack(side=tk.LEFT, padx=(6, 0))
        self.kokoro_speed_frm.grid_remove()

        self.kokoro_notice_var = tk.StringVar(value="")
        self.kokoro_notice_lbl = ttk.Label(
            voice_frm,
            textvariable=self.kokoro_notice_var,
            wraplength=560,
            foreground="darkorange",
            justify=tk.LEFT,
        )
        self.kokoro_notice_lbl.grid(row=3, column=0, columnspan=2, sticky="w",
                                    pady=(4, 0))
        self.kokoro_notice_lbl.grid_remove()

        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
        self._on_voice_selected()

        r += 1
        self.chk_overwrite = ttk.Checkbutton(
            frm, text="Overwrite existing outputs without asking",
            variable=self.overwrite_var)
        self.chk_overwrite.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1

        # Footer help text — last row of the scrollable form.
        ttk.Label(
            frm,
            text=(
                "Default voice: Microsoft Edge TTS — Steffan (en-US-SteffanNeural). "
                "Edge TTS voices use network synthesis via edge-tts (no Natural "
                "Reader login). Kokoro voices (Heart, Bella, Michael, Emma, George) "
                "run locally using the Kokoro-82M open-source AI model; ~300 MB "
                "model download required on first use."
            ),
            wraplength=620,
            justify=tk.LEFT,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # --- Action buttons (row 2): always visible, outside the scroll area. ---
        btn_row = ttk.Frame(self, padding=(10, 8))
        btn_row.grid(row=2, column=0, sticky="w")
        self.go_btn = ttk.Button(btn_row, text="Start", command=self.run_job)
        self.go_btn.pack(side=tk.LEFT)
        self.cancel_btn = ttk.Button(
            btn_row, text="Cancel", command=self.cancel_job, state=tk.DISABLED
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
        # Progress (bar + counter/percentage label; updated only from the drain on
        # the main thread — workers enqueue ("progress", (done, total)) messages).
        self.progress = ProgressIndicator(btn_row, length=280)
        self.progress.frame.pack(side=tk.LEFT, padx=(16, 0))

        # --- Log box (row 3): a labelled, multi-row pane that is always visible
        # and never crushed, matching the other tools. ---
        log_font = ("Consolas", 10) if sys.platform == "win32" else ("Menlo", 11)
        logf = ttk.LabelFrame(self, text="Log", padding=(8, 4))
        logf.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(
            logf, height=12, state=tk.DISABLED, wrap=tk.WORD, font=log_font
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        # The worker->GUI queue is a drain on the one pump, not a second chain.
        self._pump.add_drain(self._drain_worker_queue)
        self._pump.start()

    # ------- the imported queue (owned by the shared manager) -------

    @property
    def manager(self) -> ImportedFileManager:
        """The single authority on the imported queue. Read it; never shadow it."""
        return self._manager

    def imported_files(self) -> list[Path]:
        """The imported paths, in queue order, from the manager's snapshot.

        Main thread only, and the list it returns is a plain copy: what a run
        freezes is this value, so a later import mutates the manager and never a
        run that has already started.
        """
        return [imported.path for imported in self._manager.snapshot().files]

    # ------- dialogs and confirmations, all on the owner thread -------

    def _choose_files(self) -> tuple[str, ...]:
        """The Add Files dialog. Order is the dialog's, and it is preserved."""
        return tuple(filedialog.askopenfilenames(
            parent=self,
            title="Source files",
            filetypes=[
                ("Audiobook sources", "*.pdf *.txt"),
                ("All files", "*.*"),
            ],
        ) or ())

    def _choose_folder(self) -> tuple[str, ...]:
        """The Add Folder dialog. One root, returned as the tuple the seam wants."""
        chosen = filedialog.askdirectory(
            parent=self, title="Folder of PDF / TXT files", mustexist=True)
        return (str(chosen),) if chosen else ()

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
            "Add a large number of files?",
            f"{outcome.proposed_count:,} files are ready to be added.\n\n"
            "Adding this many at once can make the queue slow to work with. "
            "Add them?",
        )

    # ------- voice selection -------

    def _on_voice_selected(self, event: object | None = None) -> None:
        label = self.selected_voice_label.get()
        entry = get_voice(label)
        if entry is None:
            return

        self.voice_var.set(entry.voice_id)

        preset = entry.timing_preset
        self.sentence_ms_var.set(preset["sentencepause"])
        self.paragraph_ms_var.set(preset["paragraphpause"])
        self.title_ms_var.set(preset["title_ms"])
        self.chapter_ms_var.set(preset["chapter_ms"])
        self.end_pause_var.set(preset["end_pause"])
        self.trim_dbfs_var.set(preset["trim_dbfs"])
        self.trim_edge_chunks_var.set(preset["trim_edge_chunks"])
        self.rate_var.set(preset["rate"])
        self.kokoro_speed_var.set(preset["kokoro_speed"])

        if entry.backend == "kokoro":
            self.backend_label_var.set(
                f"Engine: Kokoro local AI  |  Voice code: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            self.kokoro_speed_frm.grid()
            notice = (
                "Kokoro voices run locally. On first use, ~300 MB of model weights "
                "may be downloaded from HuggingFace and cached under "
                "~/.cache/huggingface/. Ensure 'kokoro', 'soundfile', and 'scipy' "
                "are installed ('pip install kokoro soundfile scipy'). "
            )
            if sys.version_info >= (3, 13):
                notice += (
                    "WARNING: PyPI 'kokoro' currently requires Python 3.10–3.12. "
                    "Use a Python 3.12 virtual environment for Kokoro voices."
                )
            self.kokoro_notice_var.set(notice)
            self.kokoro_notice_lbl.grid()
            self.trim_edge_chunks_var.set(False)
        else:
            self.backend_label_var.set(
                f"Engine: Microsoft Edge TTS  |  Voice ID: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            self.kokoro_speed_frm.grid_remove()
            self.kokoro_notice_lbl.grid_remove()

    # ------- worker -> GUI queue drain (main thread, on the one pump) -------

    def append_log(self, msg: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _drain_worker_queue(self) -> None:
        """Drain the conversion worker's queue. Registered once, on the pump.

        This is the same body the panel's own ``after(200, …)`` chain used to run;
        what changed is that it no longer reschedules itself. The single
        :class:`~shared.job_ui.MainThreadPump` calls it on every tick, alongside the
        import poller, so exactly one Tk callback is ever outstanding.
        """
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "progress":
                    self.progress.update(*payload)
                elif kind == "done":
                    self.append_log(str(payload) + "\n")
                    self._finish_idle()
                    self.progress.finish()
                elif kind == "err":
                    self.append_log(str(payload) + "\n")
                    self._finish_idle()
                    self.progress.finish()
                    messagebox.showerror("Error", str(payload))
        except queue.Empty:
            pass

    def _finish_idle(self) -> None:
        self._busy.clear()
        self._cancel_event.clear()
        self.go_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)
        self.set_locked(False)

    def set_locked(self, locked: bool) -> None:
        """Lock the queue and the options while a conversion is running.

        The import *status* bar deliberately stays live: a scan that was already
        running when a conversion started can still be stopped, and that stop
        reaches the coordinator only — never this panel's conversion cancel event.
        """
        self.importer.set_locked(bool(locked))

    # ------- starting and cancelling a conversion -------

    def run_job(self) -> None:
        """Freeze the queue, reserve a run, and hand plain values to a worker."""
        if self._busy.is_set():
            return
        snapshot = self._manager.snapshot()
        if snapshot.is_empty:
            messagebox.showwarning("Missing input", "Add at least one PDF or TXT file.")
            return

        current_voice_entry = get_voice(self.selected_voice_label.get())
        is_kokoro = (
            current_voice_entry is not None and current_voice_entry.backend == "kokoro"
        )
        speaker = self.voice_var.get().strip() or DEFAULT_SPEAKER

        pause_kw: dict = {}
        trim_chunks = self.trim_edge_chunks_var.get()
        if not is_kokoro:
            try:
                pause_kw = {
                    "sentencepause": _parse_pause_ms(
                        self.sentence_ms_var.get(), "Between sentences"
                    ),
                    "paragraphpause": _parse_pause_ms(
                        self.paragraph_ms_var.get(), "After each paragraph block"
                    ),
                    "title_trailing_pause": _parse_pause_ms(
                        self.title_ms_var.get(), "After spoken chapter title"
                    ),
                    "chapter_trailing_pause": _parse_pause_ms(
                        self.chapter_ms_var.get(),
                        "Before merging last paragraph of chapter"
                    ),
                    "end_of_book_pause": _parse_pause_ms(
                        self.end_pause_var.get(), "End of recording"
                    ),
                    "trim_tts_padding": trim_chunks,
                    "trim_silence_db": _parse_trim_dbfs(
                        self.trim_dbfs_var.get(), "Trim threshold"
                    ),
                }
            except ValueError as e:
                messagebox.showwarning("Pause settings", str(e))
                return

        # Input validated; only now is a run directory reserved. Merely opening the
        # tool, importing, browsing or switching panels creates nothing.
        try:
            reservation = output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return
        run_directory = reservation.run_directory
        self.var_outdir.set(str(run_directory))
        self._log_q.put(("log", f"Output folder: {run_directory}\n"))

        # Every destination is decided here, on the main thread, through Plan 2's
        # planners and one shared collision tracker — so two occurrences can never
        # be planned onto the same path, whichever half of the queue they came from.
        try:
            planned = plan_destinations(
                snapshot,
                run_directory,
                direct_rename=(
                    mp3_output_name if is_kokoro
                    else (lambda source: direct_output_name(source, speaker))
                ),
                grouped_rename=mp3_output_name,
            )
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return

        # Read every remaining Tk variable here on the main thread. The worker runs
        # off-thread, and touching Tk vars/widgets from another thread raises "main
        # thread is not in main loop"; the worker must use these plain copies and
        # talk to the GUI only through the thread-safe queue the pump drains.
        try:
            workers = int(self.workers_var.get() or "2")
        except ValueError:
            workers = 2
        try:
            kokoro_speed = float(self.kokoro_speed_var.get())
        except ValueError:
            kokoro_speed = 1.0
        try:
            end_pause = int(self.end_pause_var.get() or "3000")
        except ValueError:
            end_pause = 3000
        try:
            paragraph_pause = int(self.paragraph_ms_var.get() or "700")
        except ValueError:
            paragraph_pause = 700

        params = {
            "items": [
                {"source": source, "destination": destination, "direct": direct}
                for source, destination, direct in planned
            ],
            "run_directory": run_directory,
            "speaker": speaker,
            "rate": self.rate_var.get().strip() or "+0%",
            "resume": self.resume_var.get(),
            "overwrite": self.overwrite_var.get(),
            "bitrate": self.bitrate_var.get(),
            "workers": workers,
            "kokoro_voice_id": None if not is_kokoro else current_voice_entry.voice_id,
            "kokoro_speed": kokoro_speed,
            "end_pause": end_pause,
            "paragraph_pause": paragraph_pause,
            "pause_kw": pause_kw,
        }

        self._busy.set()
        self._cancel_event.clear()
        self.go_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.progress.reset()
        self.set_locked(True)

        self._worker = threading.Thread(
            target=self.conversion_worker, args=(params,), daemon=True)
        self._worker.start()

    def cancel_job(self) -> None:
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.cancel_btn.configure(state=tk.DISABLED)
        self.append_log(
            "Cancelling… will stop at the next checkpoint (chapter / chunk).\n")

    # ------- teardown -------

    def close(self) -> None:
        """Close the import side and stop the pump. Idempotent, and safe late.

        A conversion is asked to stop first, so the bounded join below finds a
        thread already unwinding at its next checkpoint rather than one that will
        never be woken. Closing the adapter cancels any running scan, joins its
        worker within the coordinator's bounded timeout and makes every later event
        inert; closing the pump cancels the outstanding callback and forgets every
        drain. Nothing is left scheduled.
        """
        if self._closed:
            return
        self._closed = True
        self._cancel_event.set()
        worker = self._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(WORKER_JOIN_TIMEOUT)
        self._worker = None
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.close()
        pump = getattr(self, "_pump", None)
        if pump is not None:
            pump.close()

    def destroy(self):
        self.close()
        super().destroy()

    # ------- worker (thread) -------

    def conversion_worker(self, params: dict) -> None:
        """Convert every frozen item, on a worker thread.

        Touches no widget, no Tk variable and no object the main thread also
        mutates — **including the imported-file manager**: everything it needs
        arrived in *params* as plain values, and everything it says goes out
        through the panel's queue. The three conversion helpers it calls are
        module-level functions taking that queue, deliberately: a worker that can
        only reach ``_log_q`` and ``_cancel_event`` is a worker that cannot read a
        Tk variable by accident.

        Directly added items take the rich chapter/pause engine one at a time,
        which is what the retired single-file mode did. Folder-derived items take
        the chunked batch worker under a pool, which is what the retired batch mode
        did. Both engines are called unchanged, each with the destination the main
        thread planned for it.
        """
        log_q = self._log_q
        cancel_check = self._cancel_event.is_set
        qw = QueueWriter(log_q)

        def log(message: str) -> None:
            log_q.put(("log", message + "\n"))

        items = params["items"]
        direct_items = [item for item in items if item["direct"]]
        folder_items = [item for item in items if not item["direct"]]
        kokoro_voice_id = params["kokoro_voice_id"]
        total = len(items)
        done = 0
        ok = 0
        fail = 0

        try:
            with contextlib.redirect_stdout(qw), contextlib.redirect_stderr(qw):
                ensure_punkt()

                # Resume keeps its exact meaning: skip a folder-derived file whose
                # target already exists. A run reserves a fresh numbered directory,
                # so in the GUI this stays the no-op it has always been.
                if params["resume"] and folder_items:
                    kept = []
                    for item in folder_items:
                        if item["destination"].exists():
                            log(f"Skipping (already exists): {item['source'].name}")
                            total -= 1
                        else:
                            kept.append(item)
                    folder_items = kept

                if total:
                    log_q.put(("progress", (0, total)))

                # -- directly added files: one at a time, the rich engine ------- #
                # A lone directly added file is the case the retired single-file
                # mode covered, and it keeps that mode's fine-grained paragraph
                # progress. As soon as a run holds more than one item, progress is
                # reported per item instead, because two engines reporting into one
                # bar would fight over it.
                fine_grained = total == 1
                for item in direct_items:
                    if cancel_check():
                        log_q.put(("done", "Cancelled."))
                        return
                    if kokoro_voice_id is not None:
                        convert_with_kokoro(
                            item, params, log_q, log, cancel_check, fine_grained)
                    else:
                        convert_with_edge_engine(
                            item, params, log_q, cancel_check, fine_grained)
                    done += 1
                    ok += 1
                    stamp = datetime.now().strftime("%H:%M:%S")
                    log_q.put(("log", f"[{stamp}] {item['source'].name} — completed "
                                      f"({done}/{total})\n"))
                    if not fine_grained:
                        log_q.put(("progress", (done, total)))

                # -- folder-derived files: the chunked batch worker, pooled ----- #
                if folder_items:
                    pool_ok, pool_fail, cancelled = convert_folder_items(
                        folder_items, params, log_q, log, cancel_check, done, total)
                    ok += pool_ok
                    fail += pool_fail
                    if cancelled:
                        log_q.put(("done", "Cancelled."))
                        return

                if cancel_check():
                    log_q.put(("done", "Cancelled."))
                    return
                log_q.put(("done", f"Conversion finished: {ok} ok, {fail} failed."))
        except ConversionCancelled:
            log_q.put(("done", "Cancelled."))
        except Exception as e:  # noqa: BLE001 - reported to the user, never raised
            log_q.put(("log", f"{e!r}\n"))
            log_q.put(("err", str(e)))


# --------------------------------------------------------------------------- #
# Conversion helpers — worker-thread only, and deliberately outside the panel
# --------------------------------------------------------------------------- #
#
# None of these takes the panel. They take the frozen parameters, the queue the
# pump drains and the cancel predicate, which is the whole of what a worker is
# allowed to hold. Each one calls an existing engine entry point, unchanged.


def convert_with_edge_engine(item, params, log_q, cancel_check,
                             fine_grained: bool) -> None:
    """One directly added file through ``run_conversion_job``, unchanged.

    The engine names its own artifact — ``<stem> (<speaker>).mp3`` — and moves it
    into whatever directory it is handed. It is therefore handed a private staging
    directory, and the finished file is moved to the destination the shared planner
    reserved. That is what keeps two directly added files with the same stem from
    writing the same name: the one queue can now hold both, where the retired
    single-file mode could only ever hold one.
    """
    from tts.epub2tts_edge import runner

    pause_kw = dict(params["pause_kw"])
    skip = {"trim_tts_padding", "trim_silence_db"}
    destination = item["destination"]
    with tempfile.TemporaryDirectory(prefix="tts_direct_") as stage:
        produced = runner.run_conversion_job(
            str(item["source"]),
            output_dir=stage,
            speaker=params["speaker"],
            audio_format="mp3",
            mp3_bitrate=params["bitrate"],
            cover=None,
            overwrite=params["overwrite"],
            trim_tts_padding=pause_kw.get("trim_tts_padding", True),
            trim_silence_db=pause_kw.get(
                "trim_silence_db", float(DEFAULT_TRIM_SILENCE_DB)),
            cancel_check=cancel_check,
            progress_callback=(
                (lambda d, t: log_q.put(("progress", (d, t))))
                if fine_grained else None),
            **{k: v for k, v in pause_kw.items() if k not in skip},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(produced, str(destination))


def convert_with_kokoro(item, params, log_q, log, cancel_check,
                        fine_grained: bool) -> None:
    """One file through ``kokoro_file_to_mp3``, unchanged.

    A PDF is extracted to a temporary ``.txt`` first, exactly as before; a TXT is
    handed over as it stands. The import stays inside the function so loading the
    local model stack is still deferred to the first Kokoro conversion.
    """
    from tts.kokoro_synth import kokoro_file_to_mp3

    source = item["source"]
    destination = item["destination"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    progress = ((lambda d, t: log_q.put(("progress", (d, t))))
                if fine_grained else None)

    def synthesize(text_path: str) -> None:
        kokoro_file_to_mp3(
            text_path,
            str(destination),
            voice_id=params["kokoro_voice_id"],
            speed=params["kokoro_speed"],
            end_silence_ms=params["end_pause"],
            chunk_pause_ms=params["paragraph_pause"],
            log=log,
            cancel_check=cancel_check,
            progress_callback=progress,
        )

    if source.suffix.lower() == ".txt":
        synthesize(str(source))
        return

    from tts.pdf_extractor import pdf_to_txt

    with tempfile.TemporaryDirectory(prefix=f"kk_{source.stem}_") as work:
        text_path = str(Path(work) / f"{source.stem}.txt")
        pdf_to_txt(str(source), text_path)
        synthesize(text_path)


def convert_folder_items(folder_items, params, log_q, log, cancel_check,
                         done: int, total: int):
    """Every folder-derived file through the existing per-file batch worker.

    ``convert_single_pdf`` is ``run_batch_convert``'s own per-file body, and it
    already accepts the mirrored target as ``out_mp3`` because that is how the
    batch runner has always handed it one. So the queue supplies the list and the
    planner supplies the destination, while the engine keeps its PDF and chunk
    retries, its inter-chunk delay and its per-source temp-chunk directory exactly
    as they are — the temp key is still derived from the target's path under the
    run root, so two same-named files in different subfolders stay isolated.
    """
    from tts import batch_convert

    kokoro_voice_id = params["kokoro_voice_id"]
    run_directory = params["run_directory"]
    if kokoro_voice_id is not None:
        workers = max(1, min(params["workers"], 8))
    else:
        workers = max(1, min(32, params["workers"]))

    def convert(item):
        if cancel_check():
            return "cancelled", item, None
        try:
            if kokoro_voice_id is not None:
                convert_with_kokoro(item, params, log_q, log, cancel_check, False)
                return "success", item, None
            status, _path, message = batch_convert.convert_single_pdf(
                item["source"],
                run_directory,
                params["speaker"],
                params["rate"],
                log,
                None,
                cancel_check,
                item["destination"],
            )
            return status, item, message
        except ConversionCancelled:
            return "cancelled", item, None
        except Exception as exc:  # noqa: BLE001 - reported per item, never raised
            return "failed", item, str(exc)

    ok = 0
    fail = 0
    cancelled = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(convert, item): item for item in folder_items}
        for future in as_completed(futures):
            status, item, message = future.result()
            done += 1
            stamp = datetime.now().strftime("%H:%M:%S")
            if status == "success":
                ok += 1
                line = f"[{stamp}] {item['source'].name} — completed ({done}/{total})"
            elif status == "cancelled":
                line = f"[{stamp}] {item['source'].name} — skipped (cancelled)"
            else:
                fail += 1
                line = (f"[{stamp}] {item['source'].name} — FAILED "
                        f"({done}/{total}): {message}")
            log_q.put(("log", line + "\n"))
            log_q.put(("progress", (done, total)))
            if cancel_check():
                cancelled = True
                for pending in futures:
                    pending.cancel()
                break
    return ok, fail, cancelled


class QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(("log", s))
        return len(s)

    def flush(self) -> None:
        pass


def build_ui(parent: tk.Misc) -> TtsPanel:
    """Build the TTS tool UI into ``parent`` and return the panel frame."""
    panel = TtsPanel(parent)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


def main() -> None:
    root = tk.Tk()
    root.title("TTS Audiobook — PDF / TXT → MP3")
    root.minsize(640, 680)
    panel = build_ui(root)

    def _close():
        panel.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()


if __name__ == "__main__":
    main()
