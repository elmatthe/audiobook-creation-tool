"""Desktop GUI for epub2tts-edge (EPUB / PDF / TXT → MP3; batch PDF → MP3)."""

from __future__ import annotations

import contextlib
import io
import queue
import sys
import threading
try:
    import tkinter as tk
except (ImportError, ModuleNotFoundError) as _tk_err:  # Tk-less / headless Python
    sys.stderr.write(
        "\n[Audiobook Creation Tool] The graphical interface cannot start because\n"
        "this Python build has no working Tk (tkinter) support.\n\n"
        "To enable the window, install Tk and relaunch:\n"
        "  - macOS (Homebrew):  brew install python-tk@3.12\n"
        "  - then double-click setup_and_run again.\n\n"
        f"(details: {_tk_err})\n"
    )
    raise SystemExit(1)
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import re as _re_mod

# Ensure the scripts/ root is importable so `tts.*` resolves whether this GUI is
# run directly (python scripts/tts/epub2tts_gui.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from ebooklib import epub as epub_mod

from shared import ffmpeg_utils
from shared import paths
from shared.cancellation import ConversionCancelled
from tts.batch_convert import run_batch_convert
from tts.epub2tts_edge.epub2tts_edge import (
    DEFAULT_CHAPTER_PAUSE_MS,
    DEFAULT_END_OF_BOOK_PAUSE_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_SENTENCE_PAUSE_MS,
    DEFAULT_SPEAKER,
    DEFAULT_TITLE_PAUSE_MS,
    DEFAULT_TRIM_SILENCE_DB,
    ensure_punkt,
    export,
)
from tts.voice_registry import (
    DEFAULT_VOICE_LABEL,
    get_voice,
    display_labels,
)


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


def build_ui(parent: tk.Misc) -> None:
    """Build the TTS tool UI into ``parent`` (launcher content frame or a root)."""
    ffmpeg_utils.configure_pydub()
    root = parent

    mode_var = tk.StringVar(value="single")
    input_var = tk.StringVar()
    # Output folder: a fresh Downloads/<SLUG>-N decided once now, at build time.
    # Browse redirects it for this run only (never persisted); the folder is
    # created when a conversion starts.
    output_var = tk.StringVar(value=str(paths.next_output_dir(paths.TOOL_SLUGS["tts"])))
    bitrate_var = tk.StringVar(value="192k")
    voice_var = tk.StringVar(value=DEFAULT_SPEAKER)
    epub_convert_var = tk.BooleanVar(value=True)
    overwrite_var = tk.BooleanVar(value=True)
    workers_var = tk.StringVar(value="2")
    resume_var = tk.BooleanVar(value=True)
    rate_var = tk.StringVar(value="+0%")
    sentence_ms_var = tk.StringVar(value=str(DEFAULT_SENTENCE_PAUSE_MS))
    paragraph_ms_var = tk.StringVar(value=str(DEFAULT_PARAGRAPH_PAUSE_MS))
    title_ms_var = tk.StringVar(value=str(DEFAULT_TITLE_PAUSE_MS))
    chapter_ms_var = tk.StringVar(value=str(DEFAULT_CHAPTER_PAUSE_MS))
    end_pause_var = tk.StringVar(value=str(DEFAULT_END_OF_BOOK_PAUSE_MS))
    trim_edge_chunks_var = tk.BooleanVar(value=True)
    trim_dbfs_var = tk.StringVar(value=str(int(DEFAULT_TRIM_SILENCE_DB)))
    kokoro_speed_var = tk.StringVar(value="1.0")
    selected_voice_label = tk.StringVar(value=DEFAULT_VOICE_LABEL)

    log_q: queue.Queue[tuple[str, str]] = queue.Queue()
    busy = threading.Event()
    cancel_event = threading.Event()

    frm = ttk.Frame(root, padding=10)
    frm.grid(row=0, column=0, sticky="nsew")
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    frm.columnconfigure(1, weight=1)

    r = 0
    ttk.Label(frm, text="Mode").grid(row=r, column=0, sticky="w")
    modes = ttk.Frame(frm)
    modes.grid(row=r, column=1, sticky="w")
    ttk.Radiobutton(
        modes, text="Single file (EPUB / PDF / TXT)", variable=mode_var, value="single"
    ).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Radiobutton(
        modes, text="Batch folder (PDFs → MP3)", variable=mode_var, value="batch"
    ).pack(side=tk.LEFT)
    r += 1

    ttk.Label(frm, text="Input").grid(row=r, column=0, sticky="nw", pady=(8, 0))
    inf = ttk.Frame(frm)
    inf.grid(row=r, column=1, sticky="ew", pady=(8, 0))
    inf.columnconfigure(0, weight=1)
    ttk.Entry(inf, textvariable=input_var).grid(row=0, column=0, sticky="ew")
    ttk.Button(
        inf,
        text="Browse…",
        command=lambda: _browse_input(mode_var, input_var),
    ).grid(row=0, column=1, padx=(6, 0))
    r += 1

    ttk.Label(frm, text="Output folder").grid(row=r, column=0, sticky="nw", pady=(8, 0))
    outf = ttk.Frame(frm)
    outf.grid(row=r, column=1, sticky="ew", pady=(8, 0))
    outf.columnconfigure(0, weight=1)
    ttk.Entry(outf, textvariable=output_var).grid(row=0, column=0, sticky="ew")
    ttk.Button(
        outf,
        text="Browse…",
        command=lambda: _browse_dir(output_var),
    ).grid(row=0, column=1, padx=(6, 0))
    r += 1

    opts = ttk.LabelFrame(frm, text="Single-file MP3 options", padding=8)
    opts.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    opts.columnconfigure(1, weight=1)
    r += 1
    sr = 0
    ttk.Label(opts, text="MP3 bitrate").grid(row=sr, column=0, sticky="w", pady=(6, 0))
    ttk.Combobox(
        opts,
        textvariable=bitrate_var,
        values=("128k", "192k", "320k"),
        width=10,
        state="readonly",
    ).grid(row=sr, column=1, sticky="w", pady=(6, 0))
    sr += 1
    ttk.Checkbutton(
        opts,
        text="EPUB: convert to audio in one step (otherwise export .txt only)",
        variable=epub_convert_var,
    ).grid(row=sr, column=0, columnspan=2, sticky="w", pady=(6, 0))
    sr += 1

    pause_frm = ttk.LabelFrame(
        frm,
        text="Pause timing — single-file EPUB / PDF / TXT (milliseconds)",
        padding=8,
    )
    pause_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    pr = 0
    ttk.Checkbutton(
        pause_frm,
        text=(
            "Trim Edge TTS padding on sentence clips only (chapter title clip is never trimmed; "
            "title/chapter pauses below still apply)"
        ),
        variable=trim_edge_chunks_var,
    ).grid(row=pr, column=0, columnspan=2, sticky="w")
    pr += 1
    ttk.Label(
        pause_frm,
        text="Trim threshold (dBFS; more negative = trim less, keeps slightly more pause)",
    ).grid(row=pr, column=0, sticky="w", pady=(6, 0))
    ttk.Spinbox(
        pause_frm,
        from_=-90,
        to=-35,
        increment=1,
        textvariable=trim_dbfs_var,
        width=8,
    ).grid(row=pr, column=1, sticky="w", padx=(12, 0), pady=(6, 0))
    pr += 1
    pause_rows = [
        ("Between sentences (within a paragraph)", sentence_ms_var),
        ("After each paragraph block", paragraph_ms_var),
        ("After spoken chapter title", title_ms_var),
        ("Before merging last paragraph of chapter", chapter_ms_var),
        ("End of recording (final silence)", end_pause_var),
    ]
    for lbl, var in pause_rows:
        ttk.Label(pause_frm, text=lbl).grid(row=pr, column=0, sticky="w", pady=(4, 0))
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
            "Defaults: 800 ms between sentences; 850 ms after each paragraph block; "
            "1200 ms after chapter title; 2000 ms before last paragraph merge; "
            "3000 ms end silence; trim at -58 dBFS. Batch speech rate +0%. "
            "Try -62 dBFS if audio still feels too tight."
        ),
        wraplength=560,
        justify=tk.LEFT,
    ).grid(row=pr, column=0, columnspan=2, sticky="w", pady=(8, 0))
    r += 1

    batch_opts = ttk.LabelFrame(frm, text="Batch options", padding=8)
    batch_opts.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    br = 0
    ttk.Label(batch_opts, text="Workers").grid(row=br, column=0, sticky="w")
    ttk.Spinbox(batch_opts, from_=1, to=16, textvariable=workers_var, width=6).grid(
        row=br, column=1, sticky="w"
    )
    br += 1
    ttk.Label(batch_opts, text="Speech rate").grid(row=br, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(batch_opts, textvariable=rate_var, width=10).grid(
        row=br, column=1, sticky="w", pady=(6, 0)
    )
    br += 1
    ttk.Checkbutton(batch_opts, text="Resume (skip existing MP3s)", variable=resume_var).grid(
        row=br, column=0, columnspan=2, sticky="w", pady=(6, 0)
    )
    r += 1

    voice_frm = ttk.LabelFrame(frm, text="Voice", padding=8)
    voice_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    voice_frm.columnconfigure(1, weight=1)

    ttk.Label(voice_frm, text="Voice / Engine").grid(row=0, column=0, sticky="w")
    voice_combo = ttk.Combobox(
        voice_frm,
        textvariable=selected_voice_label,
        values=display_labels(),
        state="readonly",
        width=52,
    )
    voice_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

    backend_label_var = tk.StringVar(value="")
    backend_lbl = ttk.Label(voice_frm, textvariable=backend_label_var, foreground="navy")
    backend_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    kokoro_speed_frm = ttk.Frame(voice_frm)
    kokoro_speed_frm.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Label(kokoro_speed_frm, text="Kokoro speed (0.5 – 2.0):").pack(side=tk.LEFT)
    ttk.Spinbox(
        kokoro_speed_frm,
        from_=0.5,
        to=2.0,
        increment=0.05,
        textvariable=kokoro_speed_var,
        width=8,
        format="%.2f",
    ).pack(side=tk.LEFT, padx=(8, 0))
    ttk.Label(
        kokoro_speed_frm,
        text="  (1.0 = normal; <1.0 slower; >1.0 faster)",
        foreground="gray",
    ).pack(side=tk.LEFT, padx=(6, 0))
    kokoro_speed_frm.grid_remove()

    kokoro_notice_var = tk.StringVar(value="")
    kokoro_notice_lbl = ttk.Label(
        voice_frm,
        textvariable=kokoro_notice_var,
        wraplength=560,
        foreground="darkorange",
        justify=tk.LEFT,
    )
    kokoro_notice_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
    kokoro_notice_lbl.grid_remove()

    def _on_voice_selected(event: object | None = None) -> None:
        label = selected_voice_label.get()
        entry = get_voice(label)
        if entry is None:
            return

        voice_var.set(entry.voice_id)

        preset = entry.timing_preset
        sentence_ms_var.set(preset["sentencepause"])
        paragraph_ms_var.set(preset["paragraphpause"])
        title_ms_var.set(preset["title_ms"])
        chapter_ms_var.set(preset["chapter_ms"])
        end_pause_var.set(preset["end_pause"])
        trim_dbfs_var.set(preset["trim_dbfs"])
        trim_edge_chunks_var.set(preset["trim_edge_chunks"])
        rate_var.set(preset["rate"])
        kokoro_speed_var.set(preset["kokoro_speed"])

        if entry.backend == "kokoro":
            backend_label_var.set(
                f"Engine: Kokoro local AI  |  Voice code: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            kokoro_speed_frm.grid()
            notice = (
                "Kokoro voices run locally. On first use, ~300 MB of model weights "
                "may be downloaded from HuggingFace and cached under ~/.cache/huggingface/. "
                "Ensure 'kokoro', 'soundfile', and 'scipy' are installed "
                "('pip install kokoro soundfile scipy'). "
            )
            if sys.version_info >= (3, 13):
                notice += (
                    "WARNING: PyPI 'kokoro' currently requires Python 3.10–3.12. "
                    "Use a Python 3.12 virtual environment for Kokoro voices."
                )
            kokoro_notice_var.set(notice)
            kokoro_notice_lbl.grid()
            trim_edge_chunks_var.set(False)
        else:
            backend_label_var.set(
                f"Engine: Microsoft Edge TTS  |  Voice ID: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            kokoro_speed_frm.grid_remove()
            kokoro_notice_lbl.grid_remove()

    voice_combo.bind("<<ComboboxSelected>>", _on_voice_selected)
    _on_voice_selected()

    r += 1
    ttk.Checkbutton(frm, text="Overwrite existing outputs without asking", variable=overwrite_var).grid(
        row=r, column=0, columnspan=2, sticky="w", pady=(6, 0)
    )
    r += 1

    log = scrolledtext.ScrolledText(frm, height=14, state=tk.DISABLED, wrap=tk.WORD)
    log.grid(row=r, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
    frm.rowconfigure(r, weight=1)
    r += 1

    def append_log(msg: str) -> None:
        log.configure(state=tk.NORMAL)
        log.insert(tk.END, msg)
        log.see(tk.END)
        log.configure(state=tk.DISABLED)

    def pump_queue() -> None:
        try:
            while True:
                kind, payload = log_q.get_nowait()
                if kind == "log":
                    append_log(payload)
                elif kind == "done":
                    append_log(payload + "\n")
                    busy.clear()
                    cancel_event.clear()
                    go_btn.configure(state=tk.NORMAL)
                    cancel_btn.configure(state=tk.DISABLED)
                elif kind == "err":
                    append_log(payload + "\n")
                    busy.clear()
                    cancel_event.clear()
                    go_btn.configure(state=tk.NORMAL)
                    cancel_btn.configure(state=tk.DISABLED)
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        root.after(200, pump_queue)

    def run_job() -> None:
        if busy.is_set():
            return
        inp = input_var.get().strip()
        outd = output_var.get().strip()
        if not inp or not outd:
            messagebox.showwarning("Missing paths", "Choose input and output folder.")
            return
        # Lazy-create the output folder when a run starts (so merely opening the
        # tool never litters Downloads with empty folders).
        try:
            Path(outd).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Output folder", f"Could not create output folder:\n{outd}\n\n{e}")
            return

        current_voice_entry = get_voice(selected_voice_label.get())
        is_kokoro = (
            current_voice_entry is not None and current_voice_entry.backend == "kokoro"
        )

        pause_kw: dict = {}
        trim_chunks = trim_edge_chunks_var.get()
        if mode_var.get() == "single":
            low = inp.lower()
            epub_export_only = low.endswith(".epub") and not epub_convert_var.get()
            if not epub_export_only and not is_kokoro:
                try:
                    pause_kw = {
                        "sentencepause": _parse_pause_ms(
                            sentence_ms_var.get(), "Between sentences"
                        ),
                        "paragraphpause": _parse_pause_ms(
                            paragraph_ms_var.get(), "After each paragraph block"
                        ),
                        "title_trailing_pause": _parse_pause_ms(
                            title_ms_var.get(), "After spoken chapter title"
                        ),
                        "chapter_trailing_pause": _parse_pause_ms(
                            chapter_ms_var.get(), "Before merging last paragraph of chapter"
                        ),
                        "end_of_book_pause": _parse_pause_ms(
                            end_pause_var.get(), "End of recording"
                        ),
                        "trim_tts_padding": trim_chunks,
                        "trim_silence_db": _parse_trim_dbfs(
                            trim_dbfs_var.get(), "Trim threshold"
                        ),
                    }
                except ValueError as e:
                    messagebox.showwarning("Pause settings", str(e))
                    return

        # Read every Tk variable here on the main thread. The worker runs off-thread,
        # and touching Tk vars/widgets from another thread raises
        # "main thread is not in main loop"; the worker must use these plain copies and
        # talk to the GUI only through the thread-safe log queue (drained by pump_queue).
        mode = mode_var.get()
        speaker = voice_var.get().strip() or DEFAULT_SPEAKER
        rate = rate_var.get().strip() or "+0%"
        resume = resume_var.get()
        overwrite = overwrite_var.get()
        epub_convert = epub_convert_var.get()
        bitrate = bitrate_var.get()
        try:
            workers = int(workers_var.get() or "2")
        except ValueError:
            workers = 2
        try:
            kokoro_speed = float(kokoro_speed_var.get())
        except ValueError:
            kokoro_speed = 1.0
        try:
            end_pause = int(end_pause_var.get() or "3000")
        except ValueError:
            end_pause = 3000

        busy.set()
        cancel_event.clear()
        go_btn.configure(state=tk.DISABLED)
        cancel_btn.configure(state=tk.NORMAL)

        def worker() -> None:
            qw = QueueWriter(log_q)
            try:
                with contextlib.redirect_stdout(qw), contextlib.redirect_stderr(qw):
                    ensure_punkt()
                    if mode == "batch":
                        w = workers

                        if is_kokoro:
                            assert current_voice_entry is not None
                            import tempfile

                            from tts.kokoro_synth import kokoro_file_to_mp3
                            from tts.pdf_extractor import pdf_to_txt

                            def _natural_sort_key(p: Path) -> list:
                                parts = _re_mod.split(r"(\d+)", p.stem)
                                return [int(x) if x.isdigit() else x.lower() for x in parts]

                            pdfs = sorted(Path(inp).rglob("*.pdf"), key=_natural_sort_key)
                            if resume:
                                pdfs = [
                                    p
                                    for p in pdfs
                                    if not (Path(outd) / f"{p.stem}.mp3").exists()
                                ]

                            total = len(pdfs)
                            log_q.put(("log", f"Kokoro batch: {total} PDFs to process.\n"))
                            ok = 0
                            fail = 0

                            speed = kokoro_speed

                            def _do_one(pdf_path: Path) -> tuple[str, Path, str | None]:
                                if cancel_event.is_set():
                                    return "cancelled", pdf_path, None
                                stem = pdf_path.stem
                                out_mp3 = str(Path(outd) / f"{stem}.mp3")
                                try:
                                    with tempfile.TemporaryDirectory(prefix=f"kk_{stem}_") as td:
                                        txt_path = str(Path(td) / f"{stem}.txt")
                                        pdf_to_txt(str(pdf_path), txt_path)
                                        kokoro_file_to_mp3(
                                            txt_path,
                                            out_mp3,
                                            voice_id=current_voice_entry.voice_id,
                                            speed=speed,
                                            log=lambda s: log_q.put(("log", s + "\n")),
                                            cancel_check=cancel_event.is_set,
                                        )
                                    return "success", pdf_path, None
                                except ConversionCancelled:
                                    return "cancelled", pdf_path, None
                                except Exception as exc:
                                    return "failed", pdf_path, str(exc)

                            completed_so_far = [0]
                            with ThreadPoolExecutor(max_workers=max(1, min(w, 8))) as ex:
                                futs = {ex.submit(_do_one, p): p for p in pdfs}
                                for fut in as_completed(futs):
                                    status, path, msg = fut.result()
                                    completed_so_far[0] += 1
                                    ts = datetime.now().strftime("%H:%M:%S")
                                    if status == "success":
                                        ok += 1
                                        line = (
                                            f"[{ts}] {path.name} — completed "
                                            f"({completed_so_far[0]}/{total})"
                                        )
                                    elif status == "cancelled":
                                        line = f"[{ts}] {path.name} — skipped (cancelled)"
                                    else:
                                        fail += 1
                                        line = (
                                            f"[{ts}] {path.name} — FAILED "
                                            f"({completed_so_far[0]}/{total}): {msg}"
                                        )
                                    log_q.put(("log", line + "\n"))
                                    if cancel_event.is_set():
                                        for f in futs:
                                            f.cancel()
                                        break

                            if cancel_event.is_set():
                                log_q.put(("done", "Cancelled."))
                                return
                            log_q.put(("done", f"Kokoro batch finished: {ok} ok, {fail} failed."))
                            return

                        def on_progress(
                            pdf_name: str, completed_so_far: int, total: int, status: str
                        ) -> None:
                            ts = datetime.now().strftime("%H:%M:%S")
                            if status == "completed":
                                line = (
                                    f"[{ts}] {pdf_name} — completed -- ({completed_so_far}/{total})"
                                )
                            else:
                                line = (
                                    f"[{ts}] {pdf_name} — FAILED -- ({completed_so_far}/{total})"
                                )
                            log_q.put(("log", line + "\n"))

                        ok, fail, _ = run_batch_convert(
                            inp,
                            outd,
                            speaker=speaker,
                            workers=max(1, min(32, w)),
                            rate=rate,
                            resume=resume,
                            use_tqdm=False,
                            log=lambda s: log_q.put(("log", s + "\n")),
                            progress_callback=on_progress,
                            cancel_check=cancel_event.is_set,
                        )
                        if cancel_event.is_set():
                            log_q.put(("done", "Cancelled."))
                            return
                        log_q.put(("done", f"Batch finished: {ok} ok, {fail} failed."))
                        return

                    low = inp.lower()
                    if low.endswith(".epub") and not epub_convert:
                        book = epub_mod.read_epub(inp)
                        export(book, inp, overwrite=overwrite)
                        log_q.put(("done", "Exported EPUB to text (and cover PNG if present)."))
                        return

                    if is_kokoro and mode == "single":
                        assert current_voice_entry is not None
                        import tempfile

                        from tts.kokoro_synth import kokoro_file_to_mp3
                        from tts.pdf_extractor import pdf_to_txt

                        stem = Path(inp).stem
                        out_mp3 = str(Path(outd) / f"{stem}.mp3")

                        if Path(out_mp3).exists() and not overwrite:
                            log_q.put(
                                (
                                    "err",
                                    f"Output already exists: {out_mp3}\n"
                                    "Enable 'Overwrite' to replace it.",
                                )
                            )
                            return

                        with tempfile.TemporaryDirectory(prefix="epub2tts_kokoro_gui_") as tmpd:
                            if low.endswith(".epub"):
                                book = epub_mod.read_epub(inp)
                                export(book, inp, overwrite=True)
                                txt_path = str(Path(inp).with_suffix(".txt"))
                                if not Path(txt_path).exists():
                                    txt_path = str(Path(tmpd) / f"{stem}.txt")
                            elif low.endswith(".pdf"):
                                txt_path = str(Path(tmpd) / f"{stem}.txt")
                                pdf_to_txt(inp, txt_path)
                                log_q.put(("log", "PDF text extracted.\n"))
                            elif low.endswith(".txt"):
                                txt_path = inp
                            else:
                                log_q.put(("err", f"Unsupported file type for Kokoro: {inp}"))
                                return

                            speed = kokoro_speed
                            end_ms = end_pause
                            kokoro_file_to_mp3(
                                txt_path,
                                out_mp3,
                                voice_id=current_voice_entry.voice_id,
                                speed=speed,
                                end_silence_ms=end_ms,
                                log=lambda s: log_q.put(("log", s + "\n")),
                                cancel_check=cancel_event.is_set,
                            )
                        log_q.put(("done", f"Kokoro conversion finished → {out_mp3}"))
                        return

                    from tts.epub2tts_edge.runner import run_conversion_job

                    _skip = {"trim_tts_padding", "trim_silence_db"}
                    run_conversion_job(
                        inp,
                        output_dir=outd,
                        speaker=speaker,
                        audio_format="mp3",
                        mp3_bitrate=bitrate,
                        cover=None,
                        overwrite=overwrite,
                        epub_convert=epub_convert if low.endswith(".epub") else False,
                        trim_tts_padding=pause_kw.get("trim_tts_padding", True),
                        trim_silence_db=pause_kw.get(
                            "trim_silence_db", float(DEFAULT_TRIM_SILENCE_DB)
                        ),
                        cancel_check=cancel_event.is_set,
                        **{k: v for k, v in pause_kw.items() if k not in _skip},
                    )
                    log_q.put(("done", "Conversion finished."))
            except ConversionCancelled:
                log_q.put(("done", "Cancelled."))
            except Exception as e:
                log_q.put(("log", f"{e!r}\n"))
                log_q.put(("err", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_job() -> None:
        if not busy.is_set() or cancel_event.is_set():
            return
        cancel_event.set()
        cancel_btn.configure(state=tk.DISABLED)
        append_log("Cancelling… will stop at the next checkpoint (chapter / chunk).\n")

    btn_row = ttk.Frame(frm)
    btn_row.grid(row=r, column=0, columnspan=2, pady=(8, 0))
    go_btn = ttk.Button(btn_row, text="Start", command=run_job)
    go_btn.pack(side=tk.LEFT)
    cancel_btn = ttk.Button(
        btn_row, text="Cancel", command=cancel_job, state=tk.DISABLED
    )
    cancel_btn.pack(side=tk.LEFT, padx=(8, 0))
    r += 1

    ttk.Label(
        frm,
        text=(
            "Default voice: Microsoft Edge TTS — Steffan (en-US-SteffanNeural). "
            "Edge TTS voices use network synthesis via edge-tts (no Natural Reader login). "
            "Kokoro voices (Heart, Bella, Michael, Emma, George) run locally using the "
            "Kokoro-82M open-source AI model; ~300 MB model download required on first use."
        ),
        wraplength=620,
        justify=tk.LEFT,
    ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

    pump_queue()


def main() -> None:
    root = tk.Tk()
    root.title("epub2tts-edge v1.1 — Audiobook")
    root.minsize(640, 680)
    build_ui(root)
    root.mainloop()


class QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue[tuple[str, str]]) -> None:
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(("log", s))
        return len(s)

    def flush(self) -> None:
        pass


def _browse_input(mode_var: tk.StringVar, input_var: tk.StringVar) -> None:
    if mode_var.get() == "batch":
        p = filedialog.askdirectory(title="Input folder (PDFs)")
    else:
        p = filedialog.askopenfilename(
            title="Source file",
            filetypes=[
                ("Audiobook sources", "*.epub *.pdf *.txt"),
                ("All files", "*.*"),
            ],
        )
    if p:
        input_var.set(p)


def _browse_dir(output_var: tk.StringVar) -> None:
    p = filedialog.askdirectory(title="Output folder")
    if p:
        output_var.set(p)


if __name__ == "__main__":
    main()
