# Audiobook Creation Tool

**A cross-platform desktop app that turns ebooks and loose audio into finished, tagged audiobooks — with a one-click installer, a single clean GUI, and no terminal required.**

The Audiobook Creation Tool bundles a **text-to-speech engine** (EPUB / PDF / TXT → MP3, using Microsoft Edge TTS over the network plus the local Kokoro‑82M AI voice model) with a suite of **MP3 / M4B utilities** (combine MP3s, batch‑convert M4B → MP3, build chaptered M4B files with cover art and Audiobookshelf series tags, resize cover images, and edit existing M4B metadata). It is built for **non‑technical users**: download a zip, double‑click one setup file, and get a single GUI window — no terminal, no manual Python or ffmpeg install, and no console windows flashing during use.

> **Status:** v0.3.0 — series/track numbering fix in the M4B Metadata Editor: auto-numbering now writes the native `trkn` track atom (so Windows Explorer's `#` column populates) and the native movement atoms (`©mvn`/`©mvi`/`©mvc`) alongside the freeform iTunes series atoms, so Audiobookshelf groups a set into a numbered series; plus a new **Remove Series Numbering** action that strips every numbering surface while keeping chapters. Verified end-to-end on Windows (Explorer `#` 1–11 and an Audiobookshelf rebuild grouping the set); the macOS tree mirrors Windows byte-for-byte but awaits a live pass on a Mac. Builds on v0.2.0's macOS installer hardening. See [Known Limitations](#known-limitations).

---

## Download

Grab the latest release — extract the zip and double‑click the setup file (see [Installation](#installation)):

- **Windows:** [**AudiobookTool-Windows-v0.3.0.zip**](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.3.0/AudiobookTool-Windows-v0.3.0.zip)
- **macOS:** [**AudiobookTool-MacOS-v0.3.0.zip**](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.3.0/AudiobookTool-MacOS-v0.3.0.zip)

All releases are listed on the [**Releases page**](https://github.com/elmatthe/audiobook-creation-tool/releases).

---

## Table of Contents

- [Download](#download)
- [Features](#features)
- [The Launcher](#the-launcher)
- [Installation](#installation)
- [System Requirements](#system-requirements)
- [Tools — How to Use Each One](#tools--how-to-use-each-one)
- [Architecture](#architecture)
- [Building a Release](#building-a-release)
- [Known Limitations](#known-limitations)
- [Credits](#credits)
- [License](#license)

---

## Features

Six tools, one window:

1. **TTS Audiobook** — Convert an **EPUB, PDF, or TXT** into a narrated **MP3** using either Microsoft **Edge TTS** (online, no setup, many natural voices) or the local **Kokoro‑82M** AI model (offline once downloaded). Single‑file mode and a batch‑a‑folder‑of‑PDFs mode, with a live log and a **Cancel** button that cleans up cleanly mid‑run.
2. **M4B Converter** — Batch‑convert a folder of **M4B audiobooks → clean MP3s** (libmp3lame VBR), with optional bulk metadata and automatic track numbering.
3. **MP3 Tool** — **Combine** many MP3s into one (with optional gaps and a timestamp sheet), **time‑edit** tracks (pad or trim seconds), and **bulk‑write ID3 tags** (title / artist / album / track numbers, with a paste‑in chapter‑title list).
4. **M4B Maker** — Turn a set of MP3s into a single **chaptered .m4b** with embedded **cover art**, full metadata, and **Audiobookshelf series tags** (series name + part).
5. **Cover Image Converter** — Pad (letterbox) or center‑crop cover art to a clean **square**; accepts JPG / PNG / HEIC.
6. **M4B Metadata Editor** — Open one or more existing **.m4b** files and edit their tags **without re‑encoding** — Title, Author, Album, Year, Genre, Comment, Series, and cover image. **Preserve‑by‑default:** a blank field is never written, so each file keeps its existing value; a filled field overwrites that tag across every selected file. A **Clear All Tags (keep chapters)** button wipes all identifying metadata (and cover art) while leaving the chapter markers and titles intact, and a paged **chapter‑title import** lets you paste new chapter titles (one per line, applied positionally, blank line = leave that chapter) per file.

**Non‑destructive by design (v0.1.1):** every tool that transforms a file works on a **copy** and delivers results to an auto‑named **`Downloads/<Tool>-N`** folder (chosen fresh each launch; **Browse** redirects it for the current run). Your imported originals are never modified — the only exception is the Cover Image tool's explicit "overwrite original" toggle.

Cross‑cutting niceties: every long operation runs on a worker thread with a live log and a **Cancel** button; the app remembers your last‑used input folder, window size, and selected tool between runs; and **no console window ever flashes** during normal use.

---

## The Launcher

A single window: a sidebar of the six tools on the left, and one swappable content panel on the right. Selecting a tool raises its panel — in‑progress state (file lists, typed metadata) survives switching between tools.

```
+--------------------------------------------------------------+
|  Audiobook Creation Tool                            [_][[]][X]|
+--------------------------------------------------------------+
|  +----------------+                                          |
|  | TTS Audiobook  |  <- Sidebar: 6 tool buttons              |
|  | M4B Converter  |                                          |
|  | MP3 Tool       |     +-------------------------------+    |
|  | M4B Maker      |     |   Selected tool's UI renders   |    |
|  | Cover Image    |     |   into this content panel      |    |
|  | M4B Metadata   |     |                               |    |
|  +----------------+     +-------------------------------+    |
+--------------------------------------------------------------+
|  Status: Ready.                     |  Log: [open log folder] |
+--------------------------------------------------------------+
```

---

## Installation

The app installs itself on first run. There is nothing to configure by hand.

### Windows

1. Download `AudiobookTool-Windows-v0.3.0.zip` and extract it anywhere.
2. Double‑click **`setup_and_run.bat`**.
3. The **first** run opens a small setup window that installs a private Python environment, the audio libraries, and ffmpeg — and (optionally) pre‑downloads the Kokoro AI voice model. A progress bar and live log show what's happening.
4. **Every run after that** opens the app instantly, with no console window.

### macOS

1. Download `AudiobookTool-MacOS-v0.3.0.zip` and extract it anywhere.
2. Double‑click **`setup_and_run.command`** in Finder. (If macOS blocks it the first time, right‑click → **Open**.)
3. Same as Windows: the first run sets everything up in a small window; later runs just open the app.

> The setup uses **winget** (Windows) or **Homebrew** (macOS) to fetch Python 3.12 and ffmpeg if they aren't already present. If neither is available, it opens the right download page and tells you exactly what to install. The app never crashes with a raw error because something is missing.

---

## System Requirements

| | Recommended | Notes |
|---|---|---|
| **OS** | Windows 10/11, or macOS 12+ | |
| **Python** | **3.11 or 3.12** | Auto‑installed by the setup. **3.12 is the target** because the Kokoro AI voice model requires Python **< 3.13**. |
| **Edge TTS voices** | works on **3.13 too** | Edge TTS has no Python upper bound — only Kokoro does. |
| **ffmpeg / ffprobe** | bundled / auto‑installed | Resolved from a bundled portable build first, then the system PATH. |
| **Disk** | ~a few hundred MB, or ~2 GB with Kokoro | Kokoro pulls in PyTorch (multi‑GB) and a ~300 MB model on first use. It is **optional** — skip it and Edge TTS covers the full pipeline online. |
| **Network** | required for Edge TTS | Kokoro runs fully offline once its model is downloaded. |

---

## Tools — How to Use Each One

**TTS Audiobook.** Pick an EPUB/PDF/TXT (or a folder of PDFs for batch mode), choose a voice, and click Start. Edge voices need no setup and run over the network; Kokoro voices run locally once the model is downloaded (Python < 3.13 only). The log streams progress; **Cancel** stops at the next chapter/paragraph boundary and removes all temp files.

**M4B Converter.** Add a folder of `.m4b` files, choose an output folder, optionally set bulk metadata and auto‑track numbering, and convert. Each book is re‑encoded to a clean VBR MP3.

**MP3 Tool.** Three batch operations on an imported list of MP3s: **Combine** (one output MP3, optional inter‑track gaps, writes a timestamp sheet), **Time edit** (add or remove seconds per track), and **Bulk ID3** (strip then rewrite title/artist/album/track tags; paste a chapter‑title list to map line N → file N).

**M4B Maker.** Add your MP3s in order, set title/author/album/year/genre, optionally a cover image and **series name + part**, pick an output folder, and build. The result is a single chaptered `.m4b`; the series tags are written so **Audiobookshelf** reads them correctly.

**Cover Image Converter.** Add one or more images, choose **letterbox** (pad to square, no crop) or **center‑crop**, and convert. Outputs sit next to the source images.

**M4B Metadata Editor.** Add one `.m4b` (the form pre‑fills from its current tags) or several (batch mode, starts blank). Edit any field — leaving one **blank** preserves whatever each file already has; filling one **overwrites** that tag in every selected file. **Clear All Tags (keep chapters)** strips every identifying tag (title/author/album/year/genre/comment/series/cover) while keeping the chapter markers and titles — any field you've typed is then re‑applied on top. The **Chapter Titles (optional)** section pages through your loaded files (◀ / ▶); paste new titles one per line and they apply positionally (line N → chapter N; a blank line leaves that chapter's title unchanged; extra lines beyond the chapter count are ignored). Everything is written to **copies** in the output folder — your originals are never modified. Save runs per‑file with a Cancel button; one failure doesn't abort the batch.

---

## Architecture

### Repository layout

```
Audiobook-Creation-Tool/
├── README.md                    # this file (repo root only — not duplicated per OS)
├── setup_and_run.bat            # Windows double-click entry point
├── setup_and_run.command        # macOS double-click entry point
├── Windows/
│   ├── requirements.txt         # pinned dependencies
│   ├── md-instructions/         # Briefing.md, CHANGELOG.md
│   ├── resources/               # icons, default cover, logs/, settings.json, bin/ (portable ffmpeg)
│   └── scripts/
│       ├── launcher.py          # the unified GUI
│       ├── tts/                 # TTS engine (Edge + Kokoro), PDF/EPUB extraction, batch
│       ├── mp3_tools/           # the five MP3/M4B tools
│       └── shared/              # cross-cutting modules (see below)
└── MacOS/                       # a mirror of Windows/ (scripts kept in lockstep)
```

The repo root deliberately holds **exactly five items** (README + two launchers + two OS folders) so a non‑technical user who unzips it sees only what they need.

### `scripts/{tts, mp3_tools, shared}`

- **`tts/`** — the EPUB/PDF/TXT → MP3 engine: `epub2tts_edge/` (a hardened fork of [epub2tts‑edge](https://github.com/aedocw/epub2tts-edge)), `batch_convert.py`, `kokoro_synth.py` (local AI), `pdf_extractor.py` (PyMuPDF), and `voice_registry.py`.
- **`mp3_tools/`** — one self‑contained module per tool (`m4b_converter.py`, `mp3_tool.py`, `m4b_maker.py`, `cover_resizer.py`, `m4b_metadata_editor.py`). Each exposes `build_ui(parent)` to embed in the launcher and a standalone `main()` for debugging.
- **`shared/`** — `paths.py` (single source of truth for all paths), `subprocess_utils.py` (hidden‑console process wrappers), `ffmpeg_utils.py` (ffmpeg/ffprobe resolution + pydub config), `settings.py` (atomic JSON persistence), `cancellation.py` (cooperative cancel primitive), `metadata.py` (mutagen read/write + series atoms), `logging_setup.py`, `version.py`, `bootstrap.py` (the installer), and `release.py` (the dev packaging tool).

### Key design decisions

- **Install‑on‑first‑run, not a frozen binary.** Because the TTS engine depends on Kokoro → PyTorch (multi‑GB), a PyInstaller/py2app bundle would be fragile and huge. Instead a small `bootstrap.py` builds a private `.venv` on first run and installs pinned dependencies; updates are as simple as replacing `scripts/`.
- **Thread safety.** Every long operation runs on a worker thread. Tk variables are read **on the main thread** and handed to the worker as plain copies; the worker talks back only through a `queue.Queue` drained by an `after()` pump loop. This eliminates the classic *"main thread is not in main loop"* Tcl crash.
- **Console suppression.** The GUI launches under `pythonw.exe`, and **every** subprocess call routes through `shared/subprocess_utils` (`CREATE_NO_WINDOW` + hidden `STARTUPINFO`). An audit confirms zero direct `subprocess.*` calls in tool code — so no black window flashes during use.
- **Atomic settings.** `settings.py` writes JSON via a temp file + `os.replace`, and never raises on a missing or corrupt file — a bad settings file degrades to defaults instead of crashing.
- **ffmpeg isolation.** `ffmpeg_utils.py` is the single place that resolves ffmpeg/ffprobe (bundled `resources/bin/` first, then PATH) and pins pydub to that binary, so behaviour is identical regardless of what's on the user's PATH.
- **Cooperative cancellation.** A reusable `cancellation.py` primitive (`ConversionCancelled` + `raise_if_cancelled`) backs the Cancel button in every tool: the button sets a `threading.Event`, and workers check it at natural checkpoints (between chapters / files / stages), clean up partial output, and log `Cancelled.`
- **One codebase, two trees.** The `Windows/` and `MacOS/` `scripts/` directories are kept byte‑identical (verified by hash); platform differences live in `sys.platform` branches inside the shared code, not in divergent copies.
- **Audiobookshelf‑correct series tags.** Series metadata is written as the freeform MP4 atoms `----:com.apple.iTunes:SERIES` / `SERIES-PART`, which ffprobe (and therefore Audiobookshelf) surfaces as `series` / `series-part`. ffmpeg can't write these, so mutagen writes them immediately after the encode.

---

## Building a Release

Maintainers package the two distributable zips with the developer helper:

```
python Windows/scripts/shared/release.py
```

It reads the version from `scripts/shared/version.py` (the single source of truth) and writes
`dist/AudiobookTool-Windows-vX.Y.Z.zip` and `dist/AudiobookTool-MacOS-vX.Y.Z.zip`, each excluding
machine‑specific artifacts (`.venv/`, `__pycache__/`, `*.pyc`, `resources/logs/`,
`resources/settings.json`, `resources/bin/`) and placing `README.md` + the correct launcher at the
archive root. It then prints the full release checklist. `release.py` is a build‑time tool only — it
is never imported by the app.

---

## Known Limitations

- **macOS is untested live.** The `MacOS/` tree mirrors Windows byte‑for‑byte and compiles cleanly, but no Mac was available to run the matrix. The Windows column is fully green; the macOS column is expected to mirror it once a Mac host is available.
- **Kokoro requires Python < 3.13.** The Kokoro AI voice model's wheels don't support Python 3.13+, which is why the installer targets 3.12. On a 3.13 system, **Edge TTS voices still work fully** — only the local Kokoro voices are unavailable.
- **The clean‑machine one‑click install isn't yet live‑verified end‑to‑end.** Each piece is verified (Python/ffmpeg detection, venv creation, pinned dependency resolution against PyPI), but the full first‑run install on a fresh Python‑3.12 box — including the multi‑GB PyTorch/Kokoro download — should be run on a clean VM before shipping.

---

## Credits

This project builds on excellent open‑source work:

- **[epub2tts‑edge](https://github.com/aedocw/epub2tts-edge)** by **Christopher Aedo** — the basis of the TTS engine. Licensed **GPL‑3.0**.
- **[edge‑tts](https://github.com/rany2/edge-tts)** — the Microsoft Edge TTS client.
- **[Kokoro‑82M](https://huggingface.co/hexgrad/Kokoro-82M)** — the local AI text‑to‑speech model.

Also gratefully relying on: [mutagen](https://mutagen.readthedocs.io/) (metadata), [PyMuPDF](https://pymupdf.readthedocs.io/) (PDF extraction), [pydub](https://github.com/jiaaro/pydub) + [ffmpeg](https://ffmpeg.org/) (audio), [ebooklib](https://github.com/aerkalov/ebooklib) (EPUB), [Pillow](https://python-pillow.org/) (images), and [NLTK](https://www.nltk.org/) (sentence tokenization).

---

## License

Released under the **GNU General Public License v3.0 (GPL‑3.0)**, inherited from the upstream
epub2tts‑edge project. You may use, modify, and redistribute this software under the terms of the
GPL‑3.0; derivative works must also be licensed under GPL‑3.0. See the upstream project for the full
license text.
