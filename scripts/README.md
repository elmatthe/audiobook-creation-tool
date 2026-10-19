# scripts/ — the application

Everything a fresh copy of the Audiobook Creation Tool needs in order to run lives under this folder. Anything used only for development (tests, fixtures, dev tools, recordings, scratch) lives under `../files/`.

`scripts/` is the application's **import root**: the three packages below are imported by their plain names (`shared`, `tts`, `mp3_tools`), so `from shared import paths` works from any module. Nothing here depends on the current working directory.

| Path | What it holds |
|---|---|
| `launcher.py` | The one window that opens every tool (the entry point named in `../config.toml`) |
| `shared/` | Code every tool uses: paths, configuration, settings, first-run setup and repair, FFmpeg handling, job control, importing, shared Tk widgets, output folders, cleanup, release packaging |
| `tts/` | The TTS Audiobook tool and its four voice engines (Edge, Kokoro, Chatterbox, Qwen3) |
| `mp3_tools/` | MP3 Tool, M4B Converter, M4B Maker, M4B Metadata Editor and Cover Image, plus their shared artwork code |
| `verify.py` | The repository's verification gate (`python scripts/verify.py`); a development tool |
| `requirements.txt` | Pinned packages for the main environment (`.venv`) |
| `qwen3-requirements.txt` | Hash-pinned packages for the optional Qwen3 environment (`.venv-qwen3`) |

## Which module is which tool

| Launcher tile | Start reading at | Details |
|---|---|---|
| TTS Audiobook | `tts/epub2tts_gui.py` | `tts/README.md` |
| MP3 Tool | `mp3_tools/mp3_tool.py` | `mp3_tools/README.md` |
| M4B Converter | `mp3_tools/m4b_converter.py` | `mp3_tools/README.md` |
| M4B Maker | `mp3_tools/m4b_maker.py` | `mp3_tools/README.md` |
| Cover Image | `mp3_tools/cover_resizer.py` | `mp3_tools/README.md` |
| M4B Metadata | `mp3_tools/m4b_metadata_editor.py` | `mp3_tools/README.md` |

Artwork handling is shared by the MP3 Tool, the M4B Maker and the M4B Metadata Editor: see the "Artwork" section of `mp3_tools/README.md` and `shared/image_capabilities.py`.

## About the folder layout

Until v0.6.7 these packages lived one level deeper, under `scripts/Universal/`. That folder, and the empty `scripts/MacOS/` and `scripts/Windows/`, no longer exist in a fresh copy. If you updated by extracting a new release over an old install and still see `scripts/Universal/`, it is a leftover: nothing uses it, and you can delete it yourself. The app only warns about it; it never deletes it for you.
