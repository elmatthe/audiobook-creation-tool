# Audiobook Creation Tool v0.7.3

A Windows desktop app for turning PDF/TXT books into narrated audio and combining, converting, tagging and preparing audiobook files and cover images.

## Download / Install

**v0.7.3 is prepared for manual GitHub publication.** The download below becomes available when the owner publishes the release. Qualification remains Windows 11 (HOME-PC) at 100% display scaling; Windows 10, other machines and other display scaling are not separately qualified.

| Platform | Archive | Double-click after extraction |
|---|---|---|
| Windows | [AudiobookTool-Windows-v0.7.3.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.7.3/AudiobookTool-Windows-v0.7.3.zip) | `Setup_and_Run-audiobook-creation-tool.bat` |

macOS and Linux are not qualified or distributed for v0.7.3; the latest macOS build is [v0.6.6](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-MacOS-v0.6.6.zip).

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

## In development: v0.8.0 with OmniVoice (not released)

The `feature/0.8.0-omnivoice-integration` branch adds a fifth optional voice engine. **It is not released and there is no v0.8.0 download:** the owner's listening approval, an independent review and the final verification gate are still pending.

- **Six OmniVoice cloned voices:** OmniVoice - Female 1, Female 2, Male 1, Male 2, Male 3 and Male 4, each cloned from its own bundled recording (at most 10 seconds; Male 1's is 10.2 seconds) and the owner's transcript of it. They follow the other voices in TTS Audiobook (34 voices in all). They have no preview samples yet.
- **A fifth first-run choice, unchecked:** *OmniVoice — Six Cloned Voices* (about 6.9 GB to download and about 11.6 GB on disk, in its own `.venv-omnivoice` environment inside the app folder). It can also be added later with **Install & Continue**. Nothing is downloaded until you press **Install Selected Components**, and the review screen shows the licence terms first (**View licence terms** opens each licence text).
- **Hardware:** Windows with an NVIDIA graphics card (GPU) only; it does not run on the processor alone. It was tested on one computer (an RTX 5070), where narration used about 2 to 2.5 GB of graphics memory (up to about 4.6 GB the first time each voice is used) and ran several times faster than real time. Other cards are not promised.
- **Non-commercial:** the OmniVoice model weights are licensed CC-BY-NC, **non-commercial use only**. Installing OmniVoice does not give you the right to make commercial audiobooks or to sell or monetise audio made with these voices. The program code is Apache-2.0. The audio tokenizer it needs has its own licence, the Boson Higgs Audio 2 Community License, based on the Meta Llama 3 Community License: the Llama 3 Acceptable Use Policy applies, its outputs may not be used to improve any other large language model, and a product or service with more than 100,000 annual active users in the preceding calendar year needs an expanded licence from Boson AI. The model card also forbids unauthorised voice cloning, impersonation and fraud. This app never ships the weights or the tokenizer: your own installation downloads them, with their licence files, from one pinned revision. This summary is not legal advice.
- **Speech preparation:** OmniVoice uses the app's existing speech preparation (`tts.speech_prep`, default `v1`), with every number, date, time, currency, unit, title, Roman-numeral and symbol rule expanded for now, pending the owner's listening review; `off` still reads the text as written.
- **Nothing changes for the other engines:** Edge, Kokoro, Chatterbox and Qwen3 keep working without OmniVoice and need no new download. Each cloned engine now has its own six bundled recordings (`files/Cloned-Voice-Uploads/Chatterbox`, `Qwen3` and `OmniVoice`); Qwen3 keeps its original recordings unchanged.

Attribution required by the audio tokenizer's licence (section 1.b.i, quoted as the pinned licence words it): "Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc., All Right Reserved".

## What's new in v0.7.3

- Fixed M4B Converter failures caused by conflicting QuickTime and Nero chapter metadata.
- When normal chapter validation fails, ACT can recover a separately stored Nero chapter table only when its provenance and timeline are demonstrably valid.
- Recovery preserves chapter ordering, titles and complete audio coverage.
- Ordinary correctly structured M4B files retain their existing behavior.
- Invalid or ambiguous metadata still fails safely.

This focused hotfix retains the v0.7.2 Windows improvements and installation workflow described below.

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

- Windows (64-bit), with space for the Python environment, outputs and any voice models. Qualification is limited to Windows 11 at 100% display scaling as described above; Windows 10 is not separately qualified.
- On Windows the app is portable: everything it needs stays inside its folder and nothing is installed on the computer. On the first run, setup asks before downloading the app's own Python 3.12 (a standalone build, about 46 MB, checked against a fixed SHA-256) into `files\runtime-data\python`; it does not use or change any Python already on the computer, needs no administrator rights and leaves PATH and file associations alone. FFmpeg is the app's own verified copy in `files\bin` (about 250 MB, also checked before use) unless a working FFmpeg is already on the computer. The Python packages come from a fixed list in which every package has one version and a SHA-256 (`scripts\requirements-lock-windows-py312.txt`); the downloaded packages are kept in `files\runtime-data\python-packages` (about 500 MB), so a repair needs no internet, and pip's cache stays in the folder too. The Edge voices' English sentence data (about 4.3 MB from NLTK's data repository, also checked) is downloaded during setup, or, if it is missing later, only after you agree when you start an Edge narration; it is kept in `files\runtime-data\nltk_data`. Deleting the folder removes everything the app set up.
- Internet access for first-run downloads and **Edge TTS** narration. Optional local voice models run offline after download; The six Chatterbox reference voices are bundled; no manual reference-recording placement is needed. Models need additional disk space (all four choices together download about 14.8 GB and use about 18 GB).

## More information

See the [Releases page](https://github.com/elmatthe/audiobook-creation-tool/releases) for release notes and other versions.

Previous Windows version: [v0.7.2](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.7.2/AudiobookTool-Windows-v0.7.2.zip), available while v0.7.3 awaits publication.

Detailed project and developer information: [Briefing](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Briefing.md), [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md), [Decisions](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Decisions.md), and [Handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Handoff.md).

## Credits / License

[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by Christopher Aedo is the basis of the TTS engine. Licensed **GPL‑3.0**. Also uses Edge TTS, Kokoro and other open-source audio/image libraries.

GNU General Public License v3.0 (GPL‑3.0), inherited from the upstream project; derivative works must also be licensed under GPL‑3.0. See the [full license text](https://www.gnu.org/licenses/gpl-3.0.html).
