# scripts/ — the application

Everything a fresh copy of the Audiobook Creation Tool needs in order to run lives under this folder. Anything used only for development (tests, fixtures, dev tools, recordings, scratch) lives under `../files/`.

`scripts/` is the application's **import root**: the packages below are imported by their plain names (`shared`, `tts`, `mp3`, `m4b`, `artwork`), so `from shared import paths` works from any module. Nothing here depends on the current working directory.

| Path | What it holds |
|---|---|
| `launcher.py` | The one window that opens every tool (the entry point named in `../config.toml`) |
| `shared/` | Code every tool uses: paths, configuration, settings, first-run setup and repair, FFmpeg handling, job control, importing, shared Tk widgets, output folders, cleanup, release packaging |
| `tts/` | The TTS Audiobook tool and its four voice engines (Edge, Kokoro, Chatterbox, Qwen3) |
| `mp3/` | The MP3 Tool |
| `m4b/` | The M4B Converter (`m4b/converter/`), M4B Maker (`m4b/maker/`) and M4B Metadata Editor (`m4b/metadata/`), plus the M4B code they share |
| `artwork/` | The Cover Image tool, plus the artwork code the MP3 Tool, M4B Maker and M4B Metadata Editor share |
| `verify.py` | The repository's verification gate (`python scripts/verify.py`); a development tool |
| `requirements.txt` | Pinned packages for the main environment (`.venv`) |
| `qwen3-requirements.txt` | Hash-pinned packages for the optional Qwen3 environment (`.venv-qwen3`) |

## Which module is which tool

| Launcher tile | Start reading at | Details |
|---|---|---|
| TTS Audiobook | `tts/epub2tts_gui.py` | `tts/README.md` |
| MP3 Tool | `mp3/mp3_tool.py` | `mp3/README.md` |
| M4B Converter | `m4b/converter/m4b_converter.py` | `m4b/README.md` |
| M4B Maker | `m4b/maker/m4b_maker.py` | `m4b/README.md` |
| Cover Image | `artwork/cover_resizer.py` | `artwork/README.md` |
| M4B Metadata | `m4b/metadata/m4b_metadata_editor.py` | `m4b/README.md` |

Artwork handling is shared by the MP3 Tool, the M4B Maker and the M4B Metadata Editor: see `artwork/README.md` and `shared/image_capabilities.py`.

## About the folder layout

Until v0.6.7 these packages lived one level deeper, under `scripts/Universal/`. That folder, and the empty `scripts/MacOS/` and `scripts/Windows/`, no longer exist in a fresh copy. If you updated by extracting a new release over an old install and still see `scripts/Universal/`, it is a leftover: nothing uses it, and you can delete it yourself. The app only warns about it (once, as a line in the launcher's status bar, when the folder still holds Python or JSON files; bytecode caches alone stay silent); it never deletes it for you.

Later in v0.6.7 the single `mp3_tools/` package was split by tool into `mp3/`, `m4b/` and `artwork/` (checkpoint B2). Only development copies ever had `scripts/mp3_tools/`; a `git pull` across the split leaves at most an ignored `__pycache__` folder there, which nothing imports.
