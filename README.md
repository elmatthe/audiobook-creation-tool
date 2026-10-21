# Audiobook Creation Tool v0.6.6

A Windows and macOS desktop app for turning PDF/TXT books into narrated audio and combining, converting, tagging and preparing audiobook files and cover images.

## Download / Install

**v0.6.6 is the current published release.** Download the archive for your platform:

| Platform | Archive | Double-click after extraction |
|---|---|---|
| Windows | [AudiobookTool-Windows-v0.6.6.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-Windows-v0.6.6.zip) | `Setup_and_Run-audiobook-creation-tool.bat` |
| macOS | [AudiobookTool-MacOS-v0.6.6.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-MacOS-v0.6.6.zip) | `Setup_and_Run-audiobook-creation-tool.command` |

Extract the whole archive and keep its contents together. On macOS, move the extracted `AudiobookTool-MacOS-v0.6.6` folder from Downloads to Desktop or Applications before opening the launcher. If macOS blocks it, right-click the launcher, choose **Open**, and confirm.

First run opens a setup window with progress and a log. It prepares a private Python environment and required libraries, establishes FFmpeg/ffprobe, and offers the optional Kokoro voice-model download. Allow time and an internet connection for setup; follow any installation guidance it displays. Later launches open the app using the prepared environment.

## What it can do

- **TTS Audiobook:** turn PDF or TXT files into MP3 narration using online Edge TTS or optional local Kokoro, Chatterbox and (Windows) Qwen3 voices.
- **M4B Converter:** convert M4B to one MP3 per book or split MP3s by chapter, with metadata options.
- **MP3 Tool:** write tags to track copies, combine tracks into one MP3 per Book, and add or trim time at track ends.
- **M4B Maker:** build chaptered M4B audiobooks from MP3s with cover art, metadata and series tags.
- **Cover Image:** make square covers by padding or cropping JPG, PNG or HEIC images; correct phone-photo orientation.
- **M4B Metadata Editor:** edit tags, artwork and chapter titles in existing M4B/M4A/MP4 files without re-encoding audio.

## Basic use

1. Choose a tool in the sidebar and import files or folders. Review their order; where supported, folders become separate Books.
2. Choose a voice or output mode and configure metadata, chapters and artwork. **Shared** settings apply across Books; individual Book settings fill in the rest.
3. Start the operation and follow progress in **Activity**, switching between **Summary** and **Detailed** logs. Use **Pause/Resume**, **Cancel** or **Retry Failed** where available.
4. Use **Open Output Folder** to find finished files. Change the output base in **Preferences & Data** if needed.

The global **Light/Dark** toggle changes all tools and remembers your choice. Switching tools keeps their current inputs and settings.

## Outputs / safety

Outputs default to `Downloads/Audiobook-Creation-Tool-Outputs`, grouped by tool and numbered run, for example `M4B-Maker-Outputs/M4B-Maker-1/`. New runs use separate folders; filename collisions receive numbered names.

Originals are preserved. The exception is Cover Image's optional **Replace original files** mode, which is off by default and requires confirmation for each run.

TTS accepts **PDF and TXT only**. Save TXT files as **UTF-8**, with or without a byte-order mark; re-save other encodings as UTF-8 before importing. PDFs must contain extractable text.

## Optional Qwen3 voices (Windows)

Eight more local voices: **Qwen3 - Aiden** and **Qwen3 - Ryan** (preset voices) and **Qwen3 - Female 1**, **Female 2**, **Male 1**, **Male 2**, **Male 3** and **Male 4** (cloned from the bundled reference recordings). They are never installed automatically. In **TTS Audiobook**, choose one of them and press **Install / repair Qwen3 voices...**. Pick **CustomVoice** (about 4.5 GB; Aiden and Ryan), **Base** (about 4.5 GB; the six cloned voices) or **Both** (about 8.4 GB), and confirm the sizes shown. The first install also prepares a separate Python environment for the voice engine (about 3.1 GB to download, about 5.3 GB on disk). Nothing is downloaded until you confirm, everything is stored inside the app folder, and the same button repairs a damaged installation.

- Qwen3 runs on an NVIDIA GPU when one is found, otherwise on the CPU. Both are slower than real time: on the RTX 5070 it was tested on, narration took about 1.4 to 1.9 times as long as the audio; on the CPU tested (a Ryzen 7 9800X3D) about 2.2 times, using about 6 GB of memory. Your computer will differ, and a long book can take many hours.
- The six cloned voices need one more step, once: in the same window choose **Set up cloned voices...**. After you confirm, the app installs a speech recognizer (about 971 MB), drafts each voice's reference transcript on your computer, and asks you to listen to each recording, correct its text if needed and approve it. Until then those voices show **Setup required**. The preset voices do not need this step.
- Windows only for now. On macOS the Qwen3 voices are listed as not yet available.

## Voice samples

Short samples of all 28 voices, each reading the same sentence and named exactly as in the app, are in the [voice previews](files/voice-previews/README.md) folder of this repository on GitHub. They are not part of the download.

## Requirements

- Windows 10/11 or macOS 12+, with space for the Python environment, outputs and any voice models.
- On Windows, when no suitable Python is found, setup asks before installing Python 3.12 for your user account only, using the official python.org installer, which it verifies before running (winget is only a fallback). Setup acquires FFmpeg (and, on macOS, Python) with the supported tools (winget on Windows, Homebrew on macOS), and provides guidance if automatic setup cannot complete. Python 3.11/3.12 is recommended; setup targets 3.12 for local voices. Kokoro requires Python below 3.13.
- Internet access for first-run downloads and **Edge TTS** narration. Optional local voice models run offline after download; The six Chatterbox reference voices are bundled; no manual reference-recording placement is needed. Models need additional disk space (the Qwen3 voices need up to about 14 GB more, see above).

## More information

See the [Releases page](https://github.com/elmatthe/audiobook-creation-tool/releases) for release notes and other versions.

Detailed project and developer information: [Briefing](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Briefing.md), [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md), [Decisions](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Decisions.md), and [Handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Handoff.md).

## Credits / License

[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by Christopher Aedo is the basis of the TTS engine. Licensed **GPL‑3.0**. Also uses Edge TTS, Kokoro and other open-source audio/image libraries.

GNU General Public License v3.0 (GPL‑3.0), inherited from the upstream project; derivative works must also be licensed under GPL‑3.0. See the [full license text](https://www.gnu.org/licenses/gpl-3.0.html).
