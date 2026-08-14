# EPUB reference archive — retired from production in v0.6.1 Plan 4 Phase 5

**This directory is a reference record, not a build system.** Nothing here is imported by
the application, added to `sys.path`, packaged into a release, or collected as tests. It
exists so that EPUB support can be reconstructed if the maintainer ever reverses the
retirement decision, without having to excavate it from Git history.

**Do not delete this directory when the temporary Plan 4 instruction drop is retired at
closeout.** It is permanent.

---

## Why EPUB was retired

**Maintainer decision, 2026-08-11.** EPUB is no longer a supported application input. The
TTS tool accepts **PDF and TXT only** — for direct file selection, folder traversal, dialog
filters, dispatch and retry alike.

This supersedes **only the EPUB clause** of Decision 52B. 52B's PDF/TXT folder-batching
clause remains fully authoritative, and the historical Decision Register 1–55 was not
rewritten.

## Source commit

Everything here was taken **from Git**, not from a working directory, at:

```
3d9de97e7befc27fa22210bdcc27f174aa594883
```

That is `v0.6.1 Plan 4: Serialize Cover ETA sampling` on
`feature/0.6.1-tts-cover-workflows` — the last commit in which EPUB was an active
application input.

## Licence and attribution

This project is **GPL-3.0**, inherited from
[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by **Christopher Aedo**.

Retiring EPUB **did not** change the licence and **did not** remove the upstream
attribution. The surviving Edge synthesis engine in `scripts/Universal/tts/epub2tts_edge/`
is the *same upstream derivation*, so the attribution obligation lives in **production** as
well as here — `README.md`'s Credits and License sections are unchanged. Everything in this
archive remains GPL-3.0.

---

## Manifest

### `epub2tts_edge_epub_functions.py`

| | |
|---|---|
| **Original path** | `scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py` |
| **Archive path** | `files/archived-code/epub-tts/epub2tts_edge_epub_functions.py` |
| **Source commit** | `3d9de97e7befc27fa22210bdcc27f174aa594883` |
| **Purpose** | The EPUB parsing, cover-extraction and text-export functions, plus the CLI's EPUB flag and early-exit branch. |
| **Preserved symbols** | `namespaces`, `chap2text_epub`, `get_epub_cover`, `export`, `check_for_file`, and the removed `main()` fragments (`--epub-convert`, the `.epub` export shortcut, the `sourcefile` help string). |
| **Retained production counterpart** | **Yes — the rest of the module.** `read_book`, `run_edgespeak`, `parallel_edgespeak`, `run_save`, `intra_sentence_chunks`, `_merge_nonspeakable_intra_chunks`, `trim_silence_segment`, `trim_tts_chunk_file`, `append_silence`, `_export_audio`, `get_book`, `generate_metadata`, `get_duration`, `make_m4b`, `make_mp3`, `add_cover`, `ensure_punkt`, `_run_ffmpeg`, `_ensure_shared_on_path` and **every** timing constant stayed in production. This is the Edge synthesis engine PDF and TXT depend on. |
| **Note on `check_for_file`** | Not EPUB-specific in itself, but `export` was its only caller anywhere in the tree, so it was orphaned by the retirement and is preserved here rather than left as dead code. |
| **Licence** | GPL-3.0 (aedocw/epub2tts-edge, Christopher Aedo). |

### `runner_epub_dispatch.py`

| | |
|---|---|
| **Original path** | `scripts/Universal/tts/epub2tts_edge/runner.py` |
| **Archive path** | `files/archived-code/epub-tts/runner_epub_dispatch.py` |
| **Source commit** | `3d9de97e7befc27fa22210bdcc27f174aa594883` |
| **Purpose** | The `.epub` branch of `run_conversion_job`, its `epub_convert` parameter and its guard. |
| **Preserved fragments** | the `from ebooklib import epub as epub_mod` import; the `export` name in the engine import block; `epub_convert: bool = False`; the `".epub"` member of the accepted-suffix tuple; the `epub_convert=True` guard; the EPUB extraction branch. |
| **Retained production counterpart** | **Yes — the runner itself.** `_normalize_for_match`, `_ensure_pdf_txt_has_chapter_heading` and the whole PDF/TXT body of `run_conversion_job` are unchanged. The accepted-suffix tuple is now `(".pdf", ".txt")`. |
| **Licence** | GPL-3.0 (aedocw/epub2tts-edge, Christopher Aedo). |

### `epub2tts_gui_epub_surfaces.py`

| | |
|---|---|
| **Original path** | `scripts/Universal/tts/epub2tts_gui.py` |
| **Archive path** | `files/archived-code/epub-tts/epub2tts_gui_epub_surfaces.py` |
| **Source commit** | `3d9de97e7befc27fa22210bdcc27f174aa594883` |
| **Purpose** | Every EPUB surface of the TTS panel: the option checkbox, the Tk variable, the pause-skip condition, the Edge export-only worker branch, the Kokoro `.epub` branch, the dialog filter and the two labels that named EPUB. |
| **Preserved fragments** | `epub_convert_var`; the `EPUB: convert to audio in one step` checkbox; `epub_export_only`; the `.epub` export-only branch; the Kokoro `.epub` branch; the `"*.epub *.pdf *.txt"` dialog filter; the Mode radio and pause-group label text. |
| **Retained production counterpart** | **Yes — the panel itself.** Its Single/Batch structure, PDF/TXT dispatch, Edge and Kokoro paths, output-hint wiring, cancellation and every timing control are unchanged. |
| **Licence** | GPL-3.0 (aedocw/epub2tts-edge, Christopher Aedo). |

---

## Dependencies retired alongside this code

Removed from `scripts/requirements.txt` and from `bootstrap.REQUIRED_IMPORTS` because the
functions above were their only consumers anywhere in the tree:

| Package | Pin at retirement | Sole consumer |
|---|---|---|
| `ebooklib` | `0.20` | `chap2text_epub`/`export` (`ebooklib.ITEM_DOCUMENT`), `epub.read_epub` in the runner and the panel |
| `beautifulsoup4` | `4.14.3` | `chap2text_epub` |
| `lxml` | `6.1.1` | `get_epub_cover` (`etree` over `META-INF/container.xml`) |

Restoring EPUB means restoring these three pins — at compatible versions verified at that
time, not at the versions above — and re-adding `ebooklib` and `bs4` to
`bootstrap.REQUIRED_IMPORTS` and `bs4 → beautifulsoup4` to `bootstrap._PIP_NAME`.

## The naming compatibility boundary

Phase 5 deliberately **did not rename** `epub2tts_edge` / `epub2tts_gui`. Both names
survive in production and neither is evidence of EPUB-specific code:

* `tts/epub2tts_edge/` is the **Edge synthesis engine for PDF and TXT**, and the source of
  this project's GPL-3.0 lineage;
* `tts/epub2tts_gui.py` is the **PDF/TXT TTS panel**;
* the `epub2tts_` temp-directory prefixes in `runner.py` and `kokoro_synth.py` are naming
  artifacts of the same lineage.

A complete rename would have had to move atomically across the launcher module path,
`bootstrap.LAUNCHER_FALLBACK`, `tts/__init__.py`, nine test modules holding those paths as
literal strings, `files/Dockerfile` and `README.md` — while Phases 6 and 7 restructure that
same panel. The drop's §4.4 default (keep the names, document the boundary) was taken
rather than risk a half-rename across a phase boundary. **This paragraph is that documented
compatibility boundary.**

## Restoration guidance (high level)

1. Re-pin `ebooklib`, `beautifulsoup4` and `lxml` at versions verified current at that time,
   and restore `bootstrap.REQUIRED_IMPORTS` / `_PIP_NAME`.
2. Paste `namespaces`, `chap2text_epub`, `get_epub_cover`, `export` and `check_for_file`
   back into `epub2tts_edge.py` with their original imports (`ebooklib`, `ebooklib.epub`,
   `bs4.BeautifulSoup`, `lxml.etree`, `PIL.Image`, `zipfile`, `warnings`).
3. Restore the runner's `epub_convert` parameter, the `".epub"` suffix member, the guard and
   the extraction branch.
4. Restore the panel's Tk variable, checkbox, dialog filter, labels and the two worker
   branches.
5. Restore the CLI's `--epub-convert` flag, help text and export shortcut.
6. Delete or narrow `files/tests/test_epub_retirement.py`, which exists specifically to keep
   all of the above out of production.

Every fragment is reproduced verbatim; only indentation was changed, and function wrappers
were added purely so this archive stays inert and parseable.
