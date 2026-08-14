"""EPUB-exclusive dispatch extracted from ``scripts/Universal/tts/epub2tts_edge/runner.py``.

Preserved verbatim from commit 3d9de97e7befc27fa22210bdcc27f174aa594883. Reference
material only: never imported, never packaged, never collected as tests.

Original module: scripts/Universal/tts/epub2tts_edge/runner.py
Retirement:      v0.6.1 Plan 4 Phase 5 (maintainer decision, 2026-08-11).
Licence:         GPL-3.0, inherited from epub2tts-edge by Christopher Aedo
                 (https://github.com/aedocw/epub2tts-edge).

The runner itself survived in production. Only the four fragments below were
removed; ``_normalize_for_match``, ``_ensure_pdf_txt_has_chapter_heading`` and the
whole PDF/TXT body of ``run_conversion_job`` are unchanged in production.
"""

# ruff: noqa

# 1. Module-level import (runner.py:13), removed:
#        from ebooklib import epub as epub_mod
#
# 2. Removed from the `from .epub2tts_edge import (...)` block (runner.py:24):
#        export
#
# 3. Removed keyword-only parameter of `run_conversion_job` (runner.py:125):
#        epub_convert: bool = False,
#
# 4. Removed body fragments of `run_conversion_job`. The accepted-suffix tuple
#    at runner.py:143 was `(".epub", ".pdf", ".txt")` and is now `(".pdf", ".txt")`.

def _archived_epub_guard(suffix, epub_convert):
    """runner.py:146-147 — the pre-retirement guard, verbatim."""
    if suffix == ".epub" and not epub_convert:
        raise ValueError("EPUB input requires epub_convert=True for audio output")


def _archived_epub_branch(suffix, sourcefile, tmp, export, epub_mod, shutil, os):
    """runner.py:155-161 — the pre-retirement extraction branch, verbatim.

    Wrapped in a function purely so the archive stays inert and parseable; the
    body below is byte-identical to the original, only re-indented.
    """
    work_txt = None
    if suffix == ".epub":
        epub_name = os.path.basename(sourcefile)
        local_epub = os.path.join(tmp, epub_name)
        shutil.copy2(sourcefile, local_epub)
        book = epub_mod.read_epub(local_epub)
        export(book, local_epub, overwrite=True)
        work_txt = local_epub.replace(".epub", ".txt")
    return work_txt
