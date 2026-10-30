# Audiobook Creation Tool v0.7.0

A Windows desktop app for turning PDF/TXT books into narrated audio and combining, converting, tagging and preparing audiobook files and cover images.

## Download / Install

**v0.7.0 is for Windows 10/11.** Download the Windows archive:

| Platform | Archive | Double-click after extraction |
|---|---|---|
| Windows | [AudiobookTool-Windows-v0.7.0.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.7.0/AudiobookTool-Windows-v0.7.0.zip) | `Setup_and_Run-audiobook-creation-tool.bat` |

macOS is not part of v0.7.0 (it has not been qualified on a Mac yet); the latest macOS build is [v0.6.6](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-MacOS-v0.6.6.zip).

Extract the whole archive into an ordinary folder you can write to (for example Downloads or `C:\Audiobook Creation Tool`) and keep its contents together. Avoid very deep folders: Windows limits path lengths, and setup tells you if the folder is too deep before it installs anything.

First run opens a setup window. Choose the voices you want installed on this computer:

| Choice | Default | What it adds |
|---|---|---|
| Kokoro | Checked | Natural local English voices (about 345 MB) |
| Chatterbox Turbo | Unchecked | Expressive local voices from the six bundled recordings (about 3 GB) |
| Qwen3 CustomVoice | Unchecked | The Aiden and Ryan voices (about 4.5 GB, plus the shared Qwen3 engine) |
| Qwen3 Cloned Voices | Unchecked | The six bundled cloned voices (about 3.9 GB, plus the shared Qwen3 engine) |

**Begin Setup** first prepares the app itself: a private Python environment with its packages (about 2.5 GB, needed whatever you choose) and FFmpeg. Edge TTS voices work as soon as that is done. Then a review screen lists exactly what the voices you chose will download, reuse and occupy on disk; nothing is downloaded until you press **Install Selected Components**, and **Skip** opens the app without them. The two Qwen3 choices share one voice engine (about 3.1 GB), downloaded once. Every file comes from a fixed, tested source and is checked before it is used. Later launches open the app directly.

You can add a voice later: in **TTS Audiobook**, choose it and press **Create**. If it is not installed yet, **Install & Continue** shows the same review screen and, once the voice is installed and checked, starts that conversion; Skip or Cancel starts nothing.

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

## Qwen3 voices

Eight local voices: **Qwen3 - Aiden** and **Qwen3 - Ryan** (CustomVoice) and **Qwen3 - Female 1**, **Female 2**, **Male 1**, **Male 2**, **Male 3** and **Male 4** (cloned from the bundled reference recordings). Install them from the first-run setup or with **Install & Continue**; **Install / repair Qwen3 voices...** in TTS Audiobook still checks and repairs an existing installation. The voice engine lives in its own environment inside the app folder (`.venv\engines\qwen3`).

- Qwen3 runs on an NVIDIA GPU when one is found, otherwise on the CPU. Both are slower than real time: on the RTX 5070 it was tested on, narration took about 1.4 to 1.9 times as long as the audio; on the CPU tested (a Ryzen 7 9800X3D) about 2.2 times, using about 6 GB of memory. Your computer will differ, and a long book can take many hours.
- The six cloned voices are ready as soon as they are installed: the app already includes the words spoken in each voice's reference recording, so there is nothing else to set up.
- Windows Smart App Control checks the engine's files the first time they load; setup waits for that and reports clearly if Windows refuses them.

## Voice samples

Short samples of all 28 voices, each reading the same sentence and named exactly as in the app, are in the [voice previews](https://github.com/elmatthe/audiobook-creation-tool/blob/f7963c31813a344a92a9f67e6c3af3fc2603f64d/files/voice-previews/README.md) folder of this repository on GitHub. They are not part of the download.

## Requirements

- Windows 10/11 (64-bit), with space for the Python environment, outputs and any voice models.
- On Windows the app is portable: everything it needs stays inside its folder and nothing is installed on the computer. On the first run, setup asks before downloading the app's own Python 3.12 (a standalone build, about 46 MB, checked against a fixed SHA-256) into `files\runtime-data\python`; it does not use or change any Python already on the computer, needs no administrator rights and leaves PATH and file associations alone. FFmpeg is the app's own verified copy in `files\bin` (about 250 MB, also checked before use) unless a working FFmpeg is already on the computer. Deleting the folder removes everything the app set up.
- Internet access for first-run downloads and **Edge TTS** narration. Optional local voice models run offline after download; The six Chatterbox reference voices are bundled; no manual reference-recording placement is needed. Models need additional disk space (all four choices together download about 14.8 GB and use about 18 GB).

## More information

See the [Releases page](https://github.com/elmatthe/audiobook-creation-tool/releases) for release notes and other versions.

Detailed project and developer information: [Briefing](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Briefing.md), [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md), [Decisions](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Decisions.md), and [Handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Handoff.md).

## Credits / License

[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by Christopher Aedo is the basis of the TTS engine. Licensed **GPL‑3.0**. Also uses Edge TTS, Kokoro and other open-source audio/image libraries.

GNU General Public License v3.0 (GPL‑3.0), inherited from the upstream project; derivative works must also be licensed under GPL‑3.0. See the [full license text](https://www.gnu.org/licenses/gpl-3.0.html).
