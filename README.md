# Audiobook Creation Tool v0.8.1 (Windows and macOS)

A desktop app for Windows and Apple Silicon Macs for turning PDF/TXT books into narrated audio and combining, converting, tagging and preparing audiobook files and cover images.

## Download / Install

| Platform | Version | Archive | Double-click after extraction |
|---|---|---|---|
| Windows | v0.8.1 | [AudiobookTool-Windows-v0.8.1.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.8.1/AudiobookTool-Windows-v0.8.1.zip) | `Setup_and_Run-audiobook-creation-tool.bat` |
| macOS (Apple Silicon) | v0.8.1 | [AudiobookTool-MacOS-v0.8.1.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.8.1/AudiobookTool-MacOS-v0.8.1.zip) | `Setup_and_Run-audiobook-creation-tool.command` |

**v0.8.1 is the current release for Windows and macOS**, built from one shared source tree (one version number again; the macOS-only revision that was prepared after v0.8.0 was never published and is superseded by this release). Windows qualification is limited to Windows 11 on one computer (the developer's HOME-PC) at 100% display scaling; Windows 10, other computers, other display scaling and the configurations listed under [Release verification and what is not yet qualified](#release-verification-and-what-is-not-yet-qualified) are not separately qualified.

**macOS:** Apple Silicon only; see [macOS (Apple Silicon)](#macos-apple-silicon) for what was and was not qualified. Linux is not qualified or distributed. The earlier Windows download (v0.8.0) is listed under [More information](#more-information) and is unchanged; there has never been a published macOS download of v0.8.0.

### Windows

Extract the whole archive into an ordinary folder you can write to (for example Downloads or `C:\Audiobook Creation Tool`) and keep its contents together. Avoid very deep folders: Windows limits path lengths, and setup tells you if the folder is too deep before it installs anything.

### Important: Windows Installation Path Length

**Extract the whole app into a short folder, for example `C:\AudiobookTool`.** This is the recommended way to install: it works without changing any Windows setting, as long as you are allowed to create a folder there.

Why it matters: the app keeps its own Python environments inside its folder, and the Qwen3 and OmniVoice voice engines sit many folders deep inside them. Windows limits how long a file's full path may be. If the app's own folder already has a long path (for example a folder inside several other folders on the Desktop or in a synced cloud folder), those engines cannot be installed or loaded.

How long the path of the app's folder may be (the folder that contains `Setup_and_Run-audiobook-creation-tool.bat`; `C:\AudiobookTool` is 16 characters; Windows counts a few characters, such as emoji, as two):

| Windows setting | The app with the Edge, Kokoro, Chatterbox and Qwen3 voices | Also with the OmniVoice voices (v0.8.0) |
|---|---|---|
| Default Windows (long paths off) | 87 characters or fewer | 83 characters or fewer |
| "Enable Win32 long paths" switched on | 123 characters or fewer | 119 characters or fewer |

These are this app's own limits, enforced by its setup; they are not general Windows limits. They were worked out from the measured depth of the deepest files in two real installations, and automated tests check the rule at each exact limit. What has been installed and run for real is narrower: for v0.8.0, one Windows 11 computer with long paths switched on, in folders of 89 and 102 characters. No installation has yet been run for real on a computer with long paths off, or in a folder exactly at one of these limits. (v0.7.3 accepts up to 131 characters with long paths on; 123 is the corrected limit from v0.8.0.) Setup checks the folder before it downloads the app's packages or any voice, and tells you what to do if the folder is too deep. (Only the app's own Python, about 46 MB, may already have been fetched into the folder by then.)

**Optional: Windows long paths.** Windows has a setting called "Enable Win32 long paths" that allows longer paths for programs that support them. It does not guarantee that every Python package or program library works at any length, which is why the limits above still apply. From v0.8.0, where switching it on would be enough, the first-run setup window offers to do it for you: Windows asks for an administrator's approval first, setup never changes the setting silently, and setup checks that long paths really work before it installs anything. This offer has not yet been tried for real on a computer where the setting is off: the approval prompt and the change itself were tested only with the Windows setting simulated. v0.8.0 was released without that check (see [Release verification and what is not yet qualified](#release-verification-and-what-is-not-yet-qualified)); the short folder above avoids the question entirely. To change the setting yourself:

- **Group Policy** (may need administrator permission; not available on Windows Home, and it may be locked on a computer managed by an organisation): open the Local Group Policy Editor (`gpedit.msc`) → Computer Configuration → Administrative Templates → System → Filesystem → **Enable Win32 long paths** → **Enabled**.
- **Registry (advanced, for information only):** under `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`, the value `LongPathsEnabled` (DWORD) set to `1`. Changing the registry needs the appropriate permissions; do it only if you are comfortable administering Windows.

Restart Windows after changing the setting, before relying on it.

**Do not move an app folder that is already set up.** The Python environments inside it remember their full paths, so a moved copy can stop working. To use a shorter location, extract a fresh copy of the download there and run `Setup_and_Run-audiobook-creation-tool.bat` in it; do not move or copy an existing `.venv` folder by hand.

First run opens a setup window. Choose the voices you want installed on this computer:

| Choice | Default | What it adds |
|---|---|---|
| Kokoro | Checked | Natural local English voices (about 345 MB) |
| Chatterbox Turbo | Unchecked | Expressive local voices from the six bundled recordings (about 3 GB) |
| Qwen3 CustomVoice | Unchecked | The Aiden and Ryan voices (about 4.5 GB, plus the shared Qwen3 engine) |
| Qwen3 Cloned Voices | Unchecked | The six bundled cloned voices (about 3.9 GB, plus the shared Qwen3 engine) |
| OmniVoice — Six Cloned Voices | Unchecked | Six cloned voices; NVIDIA graphics card only; **non-commercial** model weights (about 6.9 GB to download, about 11.6 GB on disk; see [OmniVoice](#whats-new-in-v080-omnivoice)) |

**Begin Setup** first prepares the app itself: a private Python environment with its packages (about 2.5 GB, needed whatever you choose) and FFmpeg. Edge TTS voices work as soon as that is done. Then a review screen lists exactly what the voices you chose will download, reuse and occupy on disk; nothing is downloaded until you press **Install Selected Components**, and **Skip** opens the app without them. The two Qwen3 choices share one voice engine (about 3.1 GB), downloaded once. Every file comes from a fixed, tested source and is checked before it is used. Later launches open the app directly.

You can add a voice later: in **TTS Audiobook**, choose it and press **Create**. If it is not installed yet, **Install & Continue** shows the same review screen and, once the voice is installed and checked, starts that conversion; Skip or Cancel starts nothing.

### macOS (Apple Silicon)

**Requirements:** a Mac with Apple Silicon (M1 or later). Intel Macs are not supported. Qualification is limited to one computer: a MacBook Pro with an Apple M4 Pro and 24 GB of memory, on macOS 27.0.1. Other Macs, other macOS versions and Macs with less memory are not separately qualified; for OmniVoice, 16 GB of memory or more is recommended (narration used up to about 11 GB on the Mac it was tested on).

1. **Download** `AudiobookTool-MacOS-v0.8.1.zip` and double-click it in Finder (Archive Utility extracts it to a folder named `AudiobookTool-MacOS-v0.8.1`).
2. **Move the whole extracted folder out of Downloads**, for example onto your Desktop or into your home folder, and keep its contents together. If the app is started straight from Downloads, macOS may run the launcher from a temporary read-only copy ("App Translocation"); the launcher then says so and asks you to move the folder.
3. **Open it the first time.** The app is not signed by an identified Apple developer, so the first double-click of `Setup_and_Run-audiobook-creation-tool.command` is blocked by macOS ("Apple could not verify…"). Click **Done** (not Move to Trash), then open **System Settings › Privacy & Security**, scroll to the message about `Setup_and_Run-audiobook-creation-tool.command`, click **Open Anyway** and confirm with your password or Touch ID. Double-click the launcher again. macOS remembers the choice for that file. (Since macOS 15, Control-click › Open no longer bypasses this.)
   - *Optional, for people comfortable with Terminal:* `xattr -d com.apple.quarantine Setup_and_Run-audiobook-creation-tool.command`, run in the app folder, removes the download flag from **that one file** only. It skips Apple's malware check for it; use it only for an archive you downloaded from this repository's Releases page.
4. **First run.** A Terminal window asks before it downloads the app's own Python 3.12 (a standalone build, about 25 MB, checked against a fixed SHA-256) into the app folder. Then the setup window installs the app's private Python environment (each package checked against a fixed SHA-256, `scripts/requirements-lock-macos-arm64-py312.txt`) and the app's own FFmpeg 9.0.1 (an arm64 build, checked before use) into the app folder, and offers the optional voices. Later launches open the app directly.

Nothing is installed on the Mac itself: no Homebrew, no administrator password, no change to the Python or FFmpeg already on the computer. Everything stays inside the app folder; deleting the folder removes it. Files the app downloads for itself are checked by SHA-256. Do not move a folder that is already set up; extract a fresh copy instead.

**Voices on a Mac: 20, from three engines.** Edge TTS (5, online), Kokoro (9, on the computer) and OmniVoice (6 cloned voices, on the Mac's GPU, optional). Chatterbox Turbo and the Qwen3 voices are Windows only and are not offered on a Mac.

| First-run choice | Default | What it adds on a Mac |
|---|---|---|
| Kokoro | Checked | Natural local English voices (about 320 MB). On the tested Mac a 6.3-hour book took about 21 minutes. |
| OmniVoice — Six Cloned Voices | Unchecked | Six cloned voices on the Mac's GPU (Apple Silicon), about real time on the tested Mac; the processor (CPU) can be chosen instead and is slower. Its engine and model take about 4.2 GB on disk. **Non-commercial** model weights: the same licence terms as on Windows (see [OmniVoice](#whats-new-in-v080-omnivoice)); the review screen shows the terms before anything is downloaded. |

**Cancel and Pause on a Mac:** Cancel stops the running job at once, without waiting for the current book, file or chunk to finish; the button shows the cancelling state within about a second, the job's helper processes are stopped, and nothing unfinished is published. If the app cannot confirm that a helper process ended, the run is reported as failed rather than cancelled. Pause lets the files in progress finish, keeps your progress, and Resume continues; Cancel also works while paused.

## What's new in v0.8.1

v0.8.1 is one shared version for Windows and macOS (it follows the published Windows v0.8.0; the macOS-only revision prepared after it was never published). Which voices each platform offers is unchanged: **34 registered voices on Windows**, and **20 on a Mac** (Edge 5, Kokoro 9, OmniVoice 6; Chatterbox and Qwen3 stay Windows only).

- **File dialogs remember where you were.** Add Files, Add Folder, the M4B Maker's custom-destination Browse and the Preferences output-location Browse each reopen in the folder you last used, per tool and per action. The remembered folder changes only when a selection is accepted; an unreachable folder opens your home folder and is kept for when it returns. **Reset Preferences** clears every remembered folder (no file or folder is deleted). Add Files and Add Folder refuse while an import is already running.
- **Outlined buttons by meaning.** Buttons show one of four colours in their text and outline only, in Light and Dark: red for Cancel, Clear, Remove and Reset; green for Start, Build, Save and Install; yellow for Pause, Resume and Retry Failed; blue for the Book controls, repair and review. Other buttons stay as they were. A coloured button never floods with its colour.
- **The same look on macOS.** The outlined buttons are drawn on a Mac's native (Aqua) buttons too, in Light and Dark, with a visible disabled state and focus halo; Reset Preferences repaints them with the stored appearance.
- **OmniVoice and empty paragraphs.** A paragraph with nothing to say (only "...", or a lone unreadable character) no longer fails the chapter: it becomes a 0.2-second pause, and everything else sounds as before. A failure now says where it happened (chunk and worker batch), and its technical details (never the narrated text) are kept beside the engine's last-failure file.
- **Fixes from the independent review.** Three findings from the independent Codex review were fixed and re-reviewed: a cancelled second import dialog could discard the running import's remembered folder; Reset Preferences left the Aqua outlined buttons with the previous theme's images; and the test suite's write guard was too permissive about bundled-Python bytecode (tests only).
- **Voice samples are unchanged:** the published gallery still has **28 previews**. The six OmniVoice rows listed there as "To Be Added" are placeholders; they are not previews and are not an authorisation to publish any.

The final independent Codex review of v0.8.1 concluded **PASS WITH LIMITATIONS**; the limitations are listed below, and the full record is [`files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`](https://github.com/elmatthe/audiobook-creation-tool/blob/master/files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md). See the [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md) for the complete list.

## What's new in v0.8.0: OmniVoice

v0.8.0 adds a fifth optional voice engine. The app now has **34 registered voices across five engines**: Edge TTS 5, Kokoro 9, Chatterbox 6, Qwen3 8 and OmniVoice 6. The owner listened to and approved all 12 OmniVoice listening tracks (two for each of the six voices).

- **Six OmniVoice cloned voices:** OmniVoice - Female 1, Female 2, Male 1, Male 2, Male 3 and Male 4, each cloned from its own bundled recording (at most 10 seconds; Male 1's is 10.2 seconds) and the owner's transcript of it. They follow the other voices in TTS Audiobook. They have no preview samples yet.
- **A fifth first-run choice, unchecked:** *OmniVoice — Six Cloned Voices* (about 6.9 GB to download and about 11.6 GB on disk, in its own environment, `.venv/engines/omnivoice`, held inside the app's one `.venv` folder beside the Qwen3 engine; each of the three keeps its own Python packages). It can also be added later with **Install & Continue**. Nothing is downloaded until you press **Install Selected Components**, and the review screen shows the licence terms first (**View licence terms** opens each licence text).
- **Hardware (Windows):** an NVIDIA graphics card (GPU) only; on Windows it does not run on the processor alone. It was tested on one computer (an RTX 5070), where narration used about 2 to 2.5 GB of graphics memory (up to about 4.6 GB the first time each voice is used) and ran several times faster than real time. Other cards are not promised.
- **Hardware (macOS revision):** a Mac with Apple Silicon, on its GPU by default (processor optional). Tested on one MacBook Pro (M4 Pro, 24 GB), where a 43-minute narration ran at about real time and used up to about 11 GB of memory.
- **Non-commercial:** the OmniVoice model weights are licensed CC-BY-NC, **non-commercial use only**. Installing OmniVoice does not give you the right to make commercial audiobooks or to sell or monetise audio made with these voices. The program code is Apache-2.0. The audio tokenizer it needs has its own licence, the Boson Higgs Audio 2 Community License, based on the Meta Llama 3 Community License: the Llama 3 Acceptable Use Policy applies, its outputs may not be used to improve any other large language model, and a product or service with more than 100,000 annual active users in the preceding calendar year needs an expanded licence from Boson AI. The model card also forbids unauthorised voice cloning, impersonation and fraud. This app never ships the weights or the tokenizer: your own installation downloads them, with their licence files, from one pinned revision. This summary is not legal advice.
- **Speech preparation:** OmniVoice uses the app's existing speech preparation (`tts.speech_prep`, default `v1`), with every number, date, time, currency, unit, title, Roman-numeral and symbol rule expanded, as heard in the listening tracks the owner approved; `off` still reads the text as written.
- **Nothing changes for the other engines:** Edge, Kokoro, Chatterbox and Qwen3 keep working without OmniVoice and need no new download. Each cloned engine now has its own six bundled recordings (`files/Cloned-Voice-Uploads/Chatterbox`, `Qwen3` and `OmniVoice`); Qwen3 keeps its original recordings unchanged.
- **Also in v0.8.0:** one `.venv` folder holds the app's environment and both optional engines; the app's path limit with Windows long paths on is corrected to 123 characters (was 131); setup can offer to switch on Windows long paths with your approval; a damaged engine is recognised and offered a repair. See the [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md) for the full list.

Attribution required by the audio tokenizer's licence (section 1.b.i, quoted as the pinned licence words it): "Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc., All Right Reserved".

## Release verification and what is not yet qualified

### v0.8.1

v0.8.1's one full automated verification run (Windows) **failed**: its 56 of 56 native acceptance journeys passed, but 30 tests failed and one errored, all of them out-of-date test and gate expectations or Windows-versus-macOS test differences rather than application faults. Two bounded remediation commits corrected them; a later focused re-run of the original 30 reported 18 passes, 12 Windows skips and no failures, and the original teardown trigger was not reproduced. The independent review then raised three findings, all fixed and independently re-reviewed (verdict **PASS WITH LIMITATIONS**). **No passing final canonical full run exists.** The owner declined a second full run and accepted the combined evidence for this release. Skips are not passes. The details are in [`files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`](https://github.com/elmatthe/audiobook-creation-tool/blob/master/files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md).

Not yet qualified for v0.8.1:

- On a Mac: the native Preferences Reset confirmation, remembered folders in the Finder's file dialogs, and Full Keyboard Access (Tab) traversal of the outlined buttons.
- On Windows: the remaining manual folder-dialog checks and the conditional first-run (setup) visuals.
- Windows rejection of a real symbolic link, on an account that holds the privilege to create one (this account could not; that test skips).
- A first installation of this exact release on a fresh Mac or a fresh Windows computer; a fresh Mac has not been qualified by any separate evidence. Everything listed for v0.8.0 below that was not re-tested still applies.

### v0.8.0

v0.8.0's one full automated verification run **failed** on five out-of-date checks in the test and verification tools (no fault in the app was found). Those five were corrected and their focused checks passed. The owner accepted the combined evidence (the passing parts of that full run, the corrected focused checks, an independent code review whose three findings were fixed, real installations in disposable copies on HOME-PC and the owner's approval of the 12 OmniVoice listening tracks) for this Windows release, and decided not to repeat the full run. The details are in [`files/release-history/ACT-v0.8.0-Windows-Release-Acceptance.md`](https://github.com/elmatthe/audiobook-creation-tool/blob/master/files/release-history/ACT-v0.8.0-Windows-Release-Acceptance.md).

Not yet qualified for v0.8.0:

- Setup's offer to switch on Windows long paths, for real, on a computer where the setting is off (approving or declining Windows' administrator prompt, the "restart Windows" step), and an installation on a computer with long paths off or in a folder exactly at a limit.
- A standard (non-administrator) Windows account, or a computer managed by an organisation that blocks the change.
- Windows 10, other computers and display scaling other than 100%.
- OmniVoice on any graphics card other than the one RTX 5070 it was tested on.
- A complete first-time installation of all five voice choices from this exact release (it was run on earlier v0.8.0 code; the later steps were rerun on the final code in disposable copies).

### macOS (revision prepared as v0.8.0 Revision 1, never published; carried into v0.8.1): what was checked and what is not yet qualified

The macOS revision was developed and tested natively on the one Mac named above: automated tests and the app's own automated checks of all six tools on the real window, long narrations with Kokoro (a whole 6.3-hour book), Edge (37 minutes) and OmniVoice (43 minutes), and Cancel, Pause and closing the app during work. Not yet qualified for the macOS revision:

- A first installation on a Mac that has never had Homebrew, Apple's developer tools or another Python installed (the release archive's own clean-Mac installation check), and Macs other than the one tested, including Macs with 8 or 16 GB of memory.
- The real Force Quit window (Activity Monitor or Option-Command-Escape) during work; it was checked with equivalent signals, not by hand.
- Very long single text files with the local voices on Macs with less memory: Kokoro and OmniVoice assemble a file's whole narration in memory, and the 6.3-hour book above used up to about 7.3 GB with Kokoro. Splitting a very long book into several text files keeps each narration smaller.
- Some rare failures of macOS itself while a job is being stopped (for example the system refusing to end a process); the app then reports the run as failed instead of cancelled.

## Earlier: v0.7.3

- Fixed M4B Converter failures caused by conflicting QuickTime and Nero chapter metadata.
- When normal chapter validation fails, ACT can recover a separately stored Nero chapter table only when its provenance and timeline are demonstrably valid.
- Recovery preserves chapter ordering, titles and complete audio coverage.
- Ordinary correctly structured M4B files retain their existing behavior.
- Invalid or ambiguous metadata still fails safely.

That focused hotfix retained the v0.7.2 Windows improvements and installation workflow, which v0.8.0 keeps.

## What it can do

- **TTS Audiobook:** turn PDF or TXT files into MP3 narration using online Edge TTS or optional local Kokoro, (Windows) Chatterbox and Qwen3, and OmniVoice (Windows with an NVIDIA graphics card, or a Mac with Apple Silicon) voices.
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

Short samples of all 28 voices from before v0.8.0 (the gallery still holds exactly **28 published previews** in v0.8.1), each reading the same sentence and named exactly as in the app, are in the [voice previews](https://github.com/elmatthe/audiobook-creation-tool/blob/f7963c31813a344a92a9f67e6c3af3fc2603f64d/files/voice-previews/README.md) folder of this repository on GitHub. The six OmniVoice voices have no preview samples yet. The samples are not part of the download.

## Requirements

- **macOS:** a Mac with Apple Silicon; see [macOS (Apple Silicon)](#macos-apple-silicon) for what is installed, where, and what was qualified. Internet access is needed for the first-run downloads and for Edge TTS narration.
- Windows (64-bit), with space for the Python environment, outputs and any voice models. Qualification is limited to Windows 11 at 100% display scaling as described above; Windows 10 is not separately qualified.
- On Windows the app is portable: everything it needs stays inside its folder and nothing is installed on the computer. On the first run, setup asks before downloading the app's own Python 3.12 (a standalone build, about 46 MB, checked against a fixed SHA-256) into `files\runtime-data\python`; it does not use or change any Python already on the computer, needs no administrator rights and leaves PATH and file associations alone. FFmpeg is the app's own verified copy in `files\bin` (about 250 MB, also checked before use) unless a working FFmpeg is already on the computer. The Python packages come from a fixed list in which every package has one version and a SHA-256 (`scripts\requirements-lock-windows-py312.txt`); the downloaded packages are kept in `files\runtime-data\python-packages` (about 500 MB), so a repair needs no internet, and pip's cache stays in the folder too. The Edge voices' English sentence data (about 4.3 MB from NLTK's data repository, also checked) is downloaded during setup, or, if it is missing later, only after you agree when you start an Edge narration; it is kept in `files\runtime-data\nltk_data`. Deleting the folder removes everything the app set up. (The optional offer to switch on Windows long paths is the one step that changes a Windows setting, and only with an administrator's approval.)
- Internet access for first-run downloads and **Edge TTS** narration. Optional local voice models run offline after download; The six Chatterbox reference voices are bundled; no manual reference-recording placement is needed. Models need additional disk space (the first four choices together download about 14.8 GB and use about 18 GB; OmniVoice adds about 6.9 GB to download and about 11.6 GB on disk).
- OmniVoice only: an NVIDIA graphics card (tested on an RTX 5070, about 2 to 2.5 GB of graphics memory while narrating, up to about 4.6 GB the first time each voice is used).

## More information

See the [Releases page](https://github.com/elmatthe/audiobook-creation-tool/releases) for release notes and other versions.

Previous Windows release: [v0.8.0](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.8.0/AudiobookTool-Windows-v0.8.0.zip), superseded by v0.8.1. (The macOS-only revision `0.8.0+macos.1` was prepared but never tagged or published; no download exists.)

Previous macOS build: [v0.6.6](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-MacOS-v0.6.6.zip) (superseded). Previous Windows version: [v0.7.3](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.7.3/AudiobookTool-Windows-v0.7.3.zip).

Detailed project and developer information: [Briefing](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Briefing.md), [Changelog](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Changelog.md), [Decisions](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Decisions.md), and [Handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/master/md-instructions/Handoff.md).

## Credits / License

[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by Christopher Aedo is the basis of the TTS engine. Licensed **GPL‑3.0**. Also uses Edge TTS, Kokoro and other open-source audio/image libraries.

GNU General Public License v3.0 (GPL‑3.0), inherited from the upstream project; derivative works must also be licensed under GPL‑3.0. The complete, unmodified licence text is the [LICENSE](LICENSE) file at the top of this download (it is also at the [GNU project](https://www.gnu.org/licenses/gpl-3.0.html)). The licences of the optional voice models and tokenizers are separate from this one and are not part of it; this download does not contain their weights (the OmniVoice licence terms are shown before that model is downloaded, as described above).
