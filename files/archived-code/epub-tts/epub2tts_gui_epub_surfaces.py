"""EPUB-exclusive UI and worker surfaces extracted from ``scripts/Universal/tts/epub2tts_gui.py``.

Preserved verbatim from commit 3d9de97e7befc27fa22210bdcc27f174aa594883. Reference
material only: never imported, never packaged, never collected as tests.

Original module: scripts/Universal/tts/epub2tts_gui.py
Retirement:      v0.6.1 Plan 4 Phase 5 (maintainer decision, 2026-08-11).
Licence:         GPL-3.0, inherited from epub2tts-edge by Christopher Aedo
                 (https://github.com/aedocw/epub2tts-edge).

The panel survived. Its Single/Batch structure, its PDF/TXT dispatch, its Edge and
Kokoro paths and every timing control are unchanged in production; only the
fragments below were removed.
"""

# ruff: noqa

# Module-level import (epub2tts_gui.py:35), removed:
#        from ebooklib import epub as epub_mod
# Removed from the `from tts.epub2tts_edge.epub2tts_edge import (...)` block (:55):
#        export
# Removed Tk variable (:101):
#        epub_convert_var = tk.BooleanVar(value=True)
# Removed hoisted worker copy (:514):
#        epub_convert = epub_convert_var.get()


def _archived_epub_checkbox(opts, ttk, tk, epub_convert_var, sr):
    """epub2tts_gui.py:215-219 — the removed option control, verbatim."""
    ttk.Checkbutton(
        opts,
        text="EPUB: convert to audio in one step (otherwise export .txt only)",
        variable=epub_convert_var,
    ).grid(row=sr, column=0, columnspan=2, sticky="w", pady=(6, 0))


def _archived_epub_pause_skip(inp, epub_convert_var, is_kokoro):
    """epub2tts_gui.py:476-478 — pause settings were skipped for an export-only run."""
    low = inp.lower()
    epub_export_only = low.endswith(".epub") and not epub_convert_var.get()
    if not epub_export_only and not is_kokoro:
        pass


def _archived_epub_export_only_branch(inp, epub_convert, epub_mod, export, overwrite, log_q):
    """epub2tts_gui.py:697-702 — the Edge export-only worker branch, verbatim."""
    low = inp.lower()
    if low.endswith(".epub") and not epub_convert:
        book = epub_mod.read_epub(inp)
        export(book, inp, overwrite=overwrite)
        log_q.put(("done", "Exported EPUB to text (and cover PNG if present)."))
        return


def _archived_kokoro_epub_branch(low, inp, stem, tmpd, epub_mod, export, Path):
    """epub2tts_gui.py:725-730 — the Kokoro single-file EPUB branch, verbatim."""
    if low.endswith(".epub"):
        book = epub_mod.read_epub(inp)
        export(book, inp, overwrite=True)
        txt_path = str(Path(inp).with_suffix(".txt"))
        if not Path(txt_path).exists():
            txt_path = str(Path(tmpd) / f"{stem}.txt")
    return txt_path


# Removed keyword at the `run_conversion_job(...)` call site (:770):
#        epub_convert=epub_convert if low.endswith(".epub") else False,
#
# The file dialog filter (:851-857) was:
#        filetypes=[
#            ("Audiobook sources", "*.epub *.pdf *.txt"),
#            ("All files", "*.*"),
#        ],
#
# The Mode radio label (:167) was "Single file (EPUB / PDF / TXT)" and the pause
# group title (:224) was "Pause timing - single-file EPUB / PDF / TXT (milliseconds)".
