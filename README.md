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

- **TTS Audiobook:** turn PDF or TXT files into MP3 narration using online Edge TTS or optional local Kokoro/Chatterbox voices.
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

## Requirements

- Windows 10/11 or macOS 12+, with space for the Python environment, outputs and any voice models.
- Setup can acquire Python and FFmpeg when supported acquisition tools are available (winget on Windows, Homebrew on macOS), and provides guidance if automatic setup cannot complete. Python 3.11/3.12 is recommended; setup targets 3.12 for local voices. Kokoro requires Python below 3.13.
- Internet access for first-run downloads and **Edge TTS** narration. Optional local voice models run offline after download; The six Chatterbox reference voices are bundled; no manual reference-recording placement is needed. Models need additional disk space.

## More information

See the [Releases page](https://github.com/elmatthe/audiobook-creation-tool/releases) for release notes and other versions.

Detailed project and developer information: [Briefing](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Briefing.md), [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md), [Decisions](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Decisions.md), and [Handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Handoff.md).

## Credits / License

[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by Christopher Aedo is the basis of the TTS engine. Licensed **GPL‑3.0**. Also uses Edge TTS, Kokoro and other open-source audio/image libraries.

GNU General Public License v3.0 (GPL‑3.0), inherited from the upstream project; derivative works must also be licensed under GPL‑3.0. See the [full license text](https://www.gnu.org/licenses/gpl-3.0.html).
