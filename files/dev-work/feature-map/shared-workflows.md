# Launcher, shared workflows, setup and repair

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## Launcher and shared UI

The launcher (`scripts/launcher.py`) is the one window of the Audiobook Creation Tool: a TOOLS rail on the left, the selected tool's panel on the right, and a status bar with Light/Dark, Preferences & Data… and Open log folder. Each of the six tools is built into its own container the first time it is chosen and is only hidden afterwards, so its state survives switching. Underneath, every tool uses the same shared pieces in `scripts/shared/`: one importer (`importing.py`, `import_coordination.py`), one run model (`job_control.py`, `cancellation.py`), one set of Tk adapters for lists, run buttons, progress and the Summary/Details log (`job_ui.py`), one multi-Book workspace for MP3 Tool, M4B Maker and the Metadata Editor (`book_workspace.py`, `book_workspace_ui.py`), one output-folder service (`output_paths.py`), the settings and configuration layers (`settings.py`, `config.py`), the appearance and shell theme (`appearance.py`, `ui_theme.py`), the Preferences & Data dialogs (`preferences_ui.py`), and helpers for tags, numbering, FFmpeg, child processes, image formats and logging.

### Open each tool from the sidebar
`ACT.LAUNCHER.OPEN-TOOLS`

- Purpose: reach any of the six tools — TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker, Cover Image, M4B Metadata — in that order.
- How: click a name in the TOOLS rail. On Windows these are real buttons, so Tab, Enter and Space work too.
- States: one tool is current. Windows marks it "selected" and keeps it enabled (it stays in the Tab order); the classic Linux shell disables it; macOS highlights a list row. M4B Metadata appears only when its module is present.
- Result: the panel, the header title and description, and the status line "‹Tool› — ready."
- Failure: a tool that cannot load shows an error panel instead (see below); the others still work.
- Persistence: the choice is saved as `last_tool`.

### Switch tools while idle or while a job runs
`ACT.LAUNCHER.SWITCH-DURING-WORK`

- Switching only hides the current panel. Typed values, imported lists and a running job survive, and a run keeps going while you look at another tool and finishes with complete output.
- Switching never creates an output folder.
- Switching does not pause or cancel anything; Pause and Cancel stay with the tool that owns the run.

### Remember the last tool across launches
`ACT.LAUNCHER.SETTINGS`

- The selected tool is written to `settings.json` on every selection and again on close; the next launch reopens it.
- An unknown or unavailable saved tool quietly falls back to TTS Audiobook.
- Remembered: the last tool and the Light/Dark choice. Deliberately not remembered: window size and position, and anything typed into a panel.

### Window opens at 1024x720 and stays usable down to 920x600
`ACT.LAUNCHER.WINDOW-SIZE`

- Windows: opens at 1024x720 every launch; minimum 920x600. macOS: 1024x800 for both (native controls are larger).
- Every tool's core controls are meant to fit from 920x600 to maximized, Light and Dark, without core scrolling.
- The process is not DPI-aware, so at 125%/150% Windows scales the same 96-DPI layout.
- Persistence: none, on purpose.
- Gaps: no test closes a resized window and checks it reopens at 1024x720. Display scaling above 100% and the screenshot baselines are owner checks.

### A tool that fails to load shows an error panel
`ACT.LAUNCHER.LOAD-ERROR`

- If a tool's module raises while loading, its panel shows "Could not load ‹Tool›." with read-only details; the rest of the app is unaffected.
- An invalid voice list names the entries to fix in `scripts/tts/voice_registry.py` and never blames a missing dependency; any other failure advises running setup again and includes the traceback.
- The tool stays unavailable until the app is restarted after the cause is fixed. Because `last_tool` is still saved, the next launch shows the error panel again.
- The status line says "‹Tool› failed to load." each time a tool that failed to load is selected (ACT72-041, fixed in v0.7.2 Phase 6; it used to be overwritten with "— ready.").

### Open log folder
`ACT.LAUNCHER.OPEN-LOG-FOLDER`

- "Open log folder" at the right of the status bar creates `files/runtime-data/logs` if needed and opens it in Explorer without a console window. Errors are swallowed.
- On Windows it is a real, Tab-reachable button; macOS and Linux use a text link that is not keyboard-reachable.
- Checked since v0.7.2 Phase 4, by a widget-level press rather than a native one: pressing it creates the log folder and reveals exactly that folder, and nothing else.

### Start-up sequence and one-time start-up reports
`ACT.LAUNCHER.STARTUP`

- Before any panel exists: hidden-console guard installed, model cache pointed into `files/runtime-data/models/huggingface`, crash diagnostics armed, pydub pointed at the proven FFmpeg.
- After the window exists, each once: configuration warnings, the result of the last downloaded-data cleanup, and a one-line start-up notice in the status bar (never a dialog). A failure in any of these is logged and the launch continues.
- Starting the app creates no output folder. A Python without Tk prints install advice and exits.
- Gap: the launcher's own copy of the model-cache redirect has no test.

### Close the app while a tool is working
`ACT.SHARED.CLOSE-DURING-WORK`

- Alt+F4 or the close button at any time: the process ends with status 0, no window remains, no child process the app started remains, and Tcl does not crash.
- Each panel cancels its own run on close; after the main loop ends the launcher terminates only `ffmpeg.exe`/`ffprobe.exe` processes it started itself. Repair and cleanup helpers are deliberately left running.
- Closing during a folder import cancels and joins the scan and adds nothing.
- The launcher holds its Tk root for the life of the process so it is never freed on a worker thread.
- After the main loop ends the launcher finishes the closed window's Tk variables, images and fonts on the main thread, so a collection on a worker afterwards makes no Tk call and waits for nothing (ACT72-017, fixed in v0.7.2 Phase 6; the TTS and Cover forced-shutdown paths took about 23 s and 17 s before). The forced-landing scenarios check both. Closing during an import has no native journey yet.

### Cooperative cancellation primitive
`ACT.SHARED.CANCELLATION`

- The checkpoint every worker uses: nothing happens unless cancellation was requested, then `ConversionCancelled` unwinds the worker through its own cleanup.
- Old workers written against `raise_if_cancelled` work unchanged with the run controller.
- Import cancellation is a separate flag and never reaches a processing job.
- Cancel is a request honoured at the next checkpoint; the checkpoint itself stops no operating-system process. A tool that runs FFmpeg stops a running step itself: the MP3 Tool and M4B Maker through `subprocess_utils.run_supervised` inside the worker's `cancellable` block, which watches the controller's non-blocking `cancel_check` (ACT72-023, v0.7.2 Phase 6C), the Metadata Editor's chapter-title remux through the same supervisor and block (ACT72-033, v0.7.2 Phase 6D), the M4B Converter through its own runner and TTS through its FFmpeg watchdog. The Edge command line's M4B step has no controller: Ctrl+C stops its running FFmpeg step through the same supervisor, and each step has a deadline from the book's playing time (ACT72-010, v0.7.2 Phase 6E).

### Pause, Resume, Cancel and Retry Failed controls and the run state machine
`ACT.SHARED.JOB-CONTROL`

- Buttons: Pause, Resume, Cancel (danger style), Retry Failed, above each tool's progress area.
- States: Idle, Running, Pause requested, Paused, Cancel requested, Cancelled, Succeeded, Completed with failures, Failed.
- Running offers Pause and Cancel; Pause requested and Paused offer Resume and Cancel; other states offer nothing, except Retry Failed after "Completed with failures" when a retryable failure exists.
- Pause and Cancel are requests: "Pause requested" is shown until the worker reaches a checkpoint. Cancel outranks Pause and wakes a paused worker. A run ends exactly once; Cancel and a result being made final race under one lock and exactly one wins.
- Retry Failed re-runs only the retryable failures, with the original frozen settings. A run that broke as a whole is Failed and not retryable.
- Workers never touch the window directly; their events are drawn on the main thread.
- Differences: what Pause and Cancel can actually interrupt is each tool's own contract.

### Locked inputs, disabled controls and keyboard reach during a run
`ACT.SHARED.INPUT-LOCKING`

- While a run is Running, Pause requested, Paused or Cancel requested, the imported list (buttons and shortcuts included) and every option the tool registered are disabled; they come back when the run ends in any way.
- Run buttons, log tabs, progress/status and Open Output are never locked.
- Tab is meant to reach every visible core control in workflow order at 920x600 and 1024x720 and never stop on a hidden one.
- Every option a run freezes is registered for locking in all six tools (audited in v0.7.2 Phase 6, ACT72-014: the TTS Resume, Edge rate and Kokoro speed and the MP3 Chapter Titles box were added).

### Progress bar, stage line and time remaining
`ACT.SHARED.PROGRESS`

- Shows "done/total N%", animates when the total is unknown, and never rounds an unfinished, cancelled or failed run up to 100%. It never goes backwards within one stage.
- The stage line names the stage and current item (tools may add context such as "Book 2 of 10 — Track 14 of 32").
- Time remaining reads "Calculating…" until there is enough evidence, while paused, and after the run ends.

### Summary and Details log panes
`ACT.SHARED.LOG-VIEW`

- Two read-only tabs in every tool: Summary (progress, warnings, failures, output location; never technical detail) and Details (every event, timestamped, with technical detail). Some tools rename the second tab.
- Earlier runs and the panel's own lines stay above the live run; clearing empties the visible text without the same run refilling it.
- Ctrl+A selects all in either pane and copying works. Each pane keeps at least one readable line at the smallest window.
- The panes are emptied when the app closes; the session log keeps the technical record.
- Following (v0.7.2 Phase 5, ACT72-005): each pane on its own follows new lines while its newest line is on screen, holds a reader who scrolled up on the same line through new lines, trimmed history, resizes and tab or tool switches, and follows again at the bottom. A render changes only the lines that changed.
- A run that ended says so once: when the stream holds the run's own ending event, the controller's terminal state change adds no line; a panel's own closing line comes after the run's lines (ACT72-018, fixed in v0.7.2 Phase 6).

### Session log files and crash diagnostics
`ACT.SHARED.SESSION-LOG`

- One `session_‹date›_‹time›.log` per launch in `files/runtime-data/logs`; only the newest 30 are kept by default (`logging.max_sessions` in `config.toml`).
- A native crash writes every thread's Python stack into that log; failing to set this up never stops the app.
- Technical job events are written once; rejected events are never logged.

### Add Files and Add Folder importing
`ACT.SHARED.IMPORTING`

- Add Files… keeps the dialog's order. Add Folder… scans in the background, depth first, natural order (1, 2, 10), roots in the order chosen.
- Options where a tool shows them: supported-type tick-boxes (all on), "Include hidden folders" (off), "Allow duplicate files" (off), "Include subfolders" (on).
- A drive or share root, or the home folder, is confirmed before scanning; more than the configured number of files (default 1000) is confirmed before adding. Declining adds nothing.
- An import is added in one step or not at all; a failed, cancelled or declined import leaves the list unchanged; a second import during a scan is refused. Source files are only read.
- Persistence: five tools remember their last import folder; TTS does not; the options are not saved.
- Differences: each tool supplies its own file types; MP3 Tool, M4B Maker and the Metadata Editor turn a folder into Books.

### Cancel Import
`ACT.SHARED.IMPORTING.CANCEL`

- During a scan the status reads "Scanning… N files found" (a real count) and Cancel Import is enabled; otherwise "No import running." and disabled.
- Pressing it shows "Cancelling the import…" and adds nothing, even if files were found.
- It never touches a running job, and a job's Cancel never touches an import.

### Imported file list: order, selection, remove and Clear All
`ACT.SHARED.FILE-LIST`

- Rows "‹n›. ‹relative path or name›" under "‹N› files imported — ‹M› selected".
- Shift-click, Ctrl-click and Ctrl+A select; Move Up/Move Down and Alt+Up/Alt+Down move a selected block together; Remove, Delete, BackSpace and Clear All remove rows. Buttons are enabled only when they can act.
- Only rows change; no source file is touched. Selection follows the item, so moved rows stay selected and deliberate duplicates are separate rows. Shortcuts are bound to the list only.
- The list is not saved between launches.

### Confirmation questions: No changes nothing
`ACT.SHARED.CONFIRMATIONS`

- Broad-root scans, large results, Clear All or Remove Book with work in it, clearing or renumbering tags, and Reset Preferences ask a Yes/No question first. No changes nothing and starts nothing.
- A pristine Book is cleared or removed without a question; any file, setting or Shared value makes it ask.
- A question nobody can answer fails closed (the import is declined and says so). No answer is remembered.
- Difference: Cover Image's replace-the-originals question is its own dialog with Cancel as the default.

### Books: navigate, add, duplicate and remove
`ACT.SHARED.BOOK-WORKSPACE`

- In MP3 Tool, M4B Maker and the Metadata Editor: "Book X of Y", ◀ Previous, Next ▶, a Book selector, Add Book, Duplicate Book, Remove Book (the Metadata Editor offers Remove Book only).
- No wrap-around at either end. Add appends an empty Book and selects it; Duplicate copies the settings but not the files and appears right after its source; Remove selects the Book that took its place, and removing the last one leaves one empty Book.
- A folder import makes one Book per folder that directly holds files, in first-appearance order.
- Books are not saved between launches.

### Shared Metadata overrides per-Book fields
`ACT.SHARED.BOOK-WORKSPACE.SHARED-METADATA`

- A filled Shared field applies to every Book and disables the matching per-Book field; clearing it brings the Book's own value back untouched.
- A field of only spaces counts as blank; stored values are never trimmed. Each tool declares its own fields; artwork and other non-text items are handled by the tool.

### Per-Book runs, outcomes and Retry Failed
`ACT.SHARED.BOOK-WORKSPACE.RUN`

- Starting a run freezes each eligible Book; later edits cannot change it.
- Empty and invalid Books are skipped (and say why) without failing the batch.
- Each Book ends succeeded, failed, skipped empty, skipped invalid or not attempted; a Book cancelled part-way is failed.
- Retry Failed re-runs only failed Books with a retryable failure.

### Gap-free series numbers for successful Books
`ACT.SHARED.SUCCESS-NUMBERING`

- With auto-numbering on (M4B Maker, Metadata Editor, Converter), only Books that succeed take a number, starting at the chosen start value, so a failure leaves no gap. The start comes from the frozen run.

### Output folders, run folders and safe file names
`ACT.SHARED.OUTPUT-PATHS`

- Each run writes to `‹output base›/‹Tool›-Outputs/‹Tool›-N`; the base defaults to `~/Downloads/Audiobook-Creation-Tool-Outputs`; N is the lowest free number, claimed atomically when a validated run starts. An empty unused run folder is released.
- Starting the app, building or switching panels and opening or saving Preferences create nothing.
- Existing or already-planned names get "-1", "-2"… (case-insensitive). Names are cleaned of characters and device names Windows forbids. A destination equal to an input, inside a source tree, or through a link or junction is refused.
- Each tool's read-only output-folder line updates when the base is saved or reset.
- Differences: Cover Image can write beside the sources (next section); M4B Maker can use a custom destination. The old `next_output_dir`/`avoid_input_overwrite` helpers are dormant.

### Safe replacement through a temporary sibling
`ACT.SHARED.OUTPUT-PATHS.REPLACE`

- In-place changes are written to a temporary file beside the original, then swapped in with one atomic replace. Any failure before the swap leaves the original as it was and no temporary file behind.
- Linked, missing or folder sources are refused; numbered copies beside the source never collide.
- Checked on Windows on a junction, the one link an ordinary account can always create. A file symlink is checked only where the account holds the privilege to make one, which the gate's machine does not, so the gate does not count that case.

### Saved settings file and malformed-file recovery
`ACT.SHARED.SETTINGS`

- User state lives only in `files/runtime-data/settings.json`; `config.toml` is never written.
- Saves are atomic; a failed save leaves the old file intact and the old value in force.
- A missing file means defaults. Broken JSON is ignored with a reason, reported once at launch, and not overwritten, so the user can fix it or Reset.
- Stored: last tool, Light/Dark, custom output folder, last import folders. Not stored: window size.

### Configuration defaults, config.toml and the launch warning
`ACT.SHARED.CONFIG`

- Built-in defaults, then valid values from `config.toml`, then the one allowed user override (output folder).
- Each value is checked on its own; nothing in a bad file can stop the app.
- Problems appear once per launch in one "Configuration warnings" window with a plain summary and Continue (Escape closes it); details go to the session log.
- Developer mode is read only from `config.toml`, only as a real true/false, at start-up.

### Light/Dark appearance toggle
`ACT.SHARED.APPEARANCE`

- The status-bar button reads "☾ Dark mode" in Light and "☀ Light mode" in Dark. Pressing it repaints every tool interior and open app dialog in place, with nothing moved or rebuilt and nothing typed lost; the status line says "Appearance: Dark." or "Appearance: Light."
- Saved as `appearance`; first run or an unknown value means Light; a failed save shows the stored value.
- Difference: the Windows outer shell keeps its fixed dark style; on macOS the native window appearance follows the choice.
- Owner checks: the Light/Dark screenshot baselines (none approved yet) and scaling above 100%.

### Mouse-wheel scrolling over scrollable regions
`ACT.SHARED.SCROLLING`

- The wheel scrolls whichever region is under the pointer, including over its child controls. Leaving, switching tools or closing releases it; a stale region never steals it.
- Gap: ownership is tested, but no test checks that a wheel event actually moves the hovered region.

### Preferences & Data window
`ACT.SHARED.PREFERENCES`

- Opened by "Preferences & Data…" in the status bar or Ctrl+, (Cmd+, on macOS). Non-modal, one instance; opening again focuses it. Close, Escape or the title-bar close dismiss it.
- Three cards: Output location, Reset preferences, Downloaded data. The Downloaded data card's "Repair App Environment…" and "Clear Downloaded Data" belong to the setup map (`ACT.SETUP.REPAIR`, `ACT.SETUP.CLEAR-DOWNLOADED-DATA`).
- Save, Reset, Close and Browse stay reachable at 920x600 without scrolling. Opening it creates no folder.

### Choose the output location
`ACT.SHARED.PREFERENCES.OUTPUT-LOCATION`

- Shows the folder in force and its source (built-in default, `config.toml`, or your saved preference).
- "Use the default Downloads location" disables the path field and Browse…; "Use a custom folder" enables them; Browse… fills the path; cancelling Browse changes nothing.
- Save accepts a full path or one starting with ~. Relative paths, environment variables and an empty path are refused in plain words and nothing is saved. Saving does not create the folder. A failed save keeps the old value and says so.
- Runs already started keep the folder they captured; open tools' output lines update after a successful save.

### Reset Preferences
`ACT.SHARED.PREFERENCES.RESET`

- "Reset Preferences…" asks first. No: "Reset cancelled. Nothing was changed." Yes: `settings.json` is emptied; nothing else is touched (no models, logs, outputs, media or `config.toml`). A failed reset says so and leaves the file intact.
- After a reset the fields, open tools' output lines and Light/Dark refresh immediately.
- The question and the card's caption name everything a reset clears: the last tool, remembered folders, the custom output location and Light/Dark, which goes back to Light (ACT72-042, fixed in v0.7.2 Phase 6).
- Kept separate from Clear Downloaded Data.

### Shared M4B tag reading and writing
`ACT.SHARED.M4B-TAGS`

- One field list for the Converter's and Maker's FFmpeg tagging; empty values are left out.
- Writing tags changes only the given keys. Series go to the freeform SERIES / SERIES-PART atoms Audiobookshelf reads, with `trkn` and movement atoms for a numeric part; removing numbering strips them all and can keep the series name.
- Clearing tags keeps chapters and audio; retitling chapters keeps every chapter and boundary by stream copy; a failed remux is reported, even when FFmpeg exits with status 0.

### Use only the proven FFmpeg pair
`ACT.SHARED.FFMPEG`

- Every FFmpeg/ffprobe run uses the pair setup has proven on this machine; an unproven copy is never executed and nothing falls back to PATH. pydub is pointed at the proven pair or at a target that cannot run.
- MP3 exports always use libmp3lame at the requested bitrate (192k default).
- xHE-AAC sources use the AudioToolbox decoder where it exists; elsewhere the caller is told to warn rather than produce sped-up audio.

### No console windows from child processes
`ACT.SHARED.HIDDEN-CONSOLE`

- On Windows every child process — including the FFmpeg runs pydub and edge-tts start themselves — is started hidden, so no console flashes. The guard is installed once at start-up before those libraries load.
- Checked since v0.7.2 Phase 4, in a child interpreter so the test process is untouched: every start gets the hidden-window flag and window state, a caller's own flags are kept, installing twice wraps once, and `launcher.main` installs the guard before anything else. Whether a real console ever flashes is not measured.

### Image formats that can be read and written
`ACT.SHARED.IMAGE-FORMATS`

- JPEG and PNG always work both ways. HEIC/HEIF reading and writing are tested separately on this machine by decoding and encoding one pixel; a read-only build offers HEIC for import but not as an output.
- A HEIC output that cannot be encoded is refused truthfully and is never silently written as JPEG. A missing plugin never stops the app.

### Intentional differences from other tools

- TTS Audiobook, M4B Converter and Cover Image use the shared importer's list directly; MP3 Tool, M4B Maker and the Metadata Editor use Books, Shared Metadata and per-Book track lists with the same shortcuts.
- The Metadata Editor's Book navigator offers Remove Book only (no Add or Duplicate).
- TTS does not remember its last import folder; the other five tools do.
- Cover Image can write beside the sources and asks its own replace-the-originals question with Cancel as the default.
- M4B Maker can deliver to a custom destination folder instead of the numbered run folder.
- Each tool registers the options it freezes for locking during a run (all six audited in v0.7.2 Phase 6, ACT72-014) and what Pause and Cancel can interrupt (see the tool sections; ACT72-033 was fixed in v0.7.2 Phase 6D, ACT72-010 in 6E).
- The Windows shell is a dark rail with real buttons; macOS uses a Finder-style list and Linux the classic layout; on both of those, Open log folder is a text link rather than a button.

### Not verified here

- Windows display scaling other than 100% (125%, 150%): HOME-PC runs at 96 DPI; owner check.
- Visual appearance: 68 screenshot candidates await the owner; no visual baseline is approved.
- Closing the window during a running folder import with real input (only closes during runs have native journeys).
- What "Open log folder" actually opens in Explorer.
- The hidden-console guard and the launcher's own model-cache redirect.
- macOS and Linux shells (aqua and classic branches), including Cmd+, and the macOS native window appearance.
- Log following is checked on real widgets in every tool and natively in the MP3 Tool only; the other tools' panes are the same view.

## Shared M4B staging (Maker and Metadata Editor)

### Private staging and atomic publication (M4B Maker and Metadata Editor)

`ACT.SHARED.M4B-STAGING`

- Lives in `scripts/m4b/m4b_staging.py`; the Converter does not use it. The Maker and Metadata Editor engines stage each output in a private folder directly under their work area and publish it onto its planned final name.
- Publication refuses an unstaged file, an existing destination or a link, and is atomic (through a temporary sibling when the work area is on another drive). Discarding removes only the staging folder's own contents and never follows a symlink or junction. The work area is removed only when empty.

## Setup, launch and repair

Everything that gets the Audiobook Creation Tool onto a computer, starts it, keeps its installation healthy and lets a person reclaim space. A person double-clicks `Setup_and_Run-audiobook-creation-tool.bat` (Windows). The first time, a small setup window builds a private Python environment (`.venv`) from the app's own Python, installs the hash-locked packages, sets up FFmpeg and the English sentence data, and then offers the optional local voices through a review-and-consent panel. Every later double-click runs a quick health check and a bounded self-heal (environment, packages, FFmpeg, Kokoro) and opens the launcher; anything still missing is reported in one notice after the window appears. Preferences & Data adds two maintenance actions: Repair App Environment and Clear Downloaded Data. The code lives in the two root launchers, `scripts/shared/bootstrap_host.ps1` (stage 0) and `scripts/shared/bootstrap.py`, with helper modules in `scripts/shared/` (`venv_integrity`, `venv_layout`, `base_packages`, `ffmpeg_health`, `ffmpeg_portable`, `nltk_store`, `spacy_store`, `espeak_data`, `engine_lease`, `maintenance`, `cleanup_state`, `cleanup_worker`, the `optional_setup_*` modules and `release.py`). Everything is kept inside the app's folder; nothing is installed on the computer on Windows. v0.7.x ships for Windows only.

### First-run setup wizard and base install
`ACT.SETUP.FIRST-RUN`

- **Purpose:** install what the app needs on a new copy and hand over to the optional voices and the app.
- **How to reach it:** the first double-click of `Setup_and_Run-audiobook-creation-tool.bat` (no `.venv` yet). The window "Audiobook Creation Tool - Setup" shows four voice checkboxes with sizes, Cancel and Begin Setup.
- **States:** intro (choices) -> progress (step label, bar, live log) -> either a "Setup did not complete" error with Open log folder and Close, or the optional-voices review -> app launch. A headless variant (no working Tk) runs the same base steps with no window and installs no optional voice.
- **Inputs and outputs:** the four choices are Kokoro (checked), Chatterbox Turbo, Qwen3 CustomVoice and Qwen3 Cloned Voices (unchecked). Choosing is not consent: nothing optional is downloaded here. The base install is five steps: locate the app's Python, create `.venv`, install the locked packages, set up FFmpeg, fetch the English sentence data. No voice model is downloaded. Progress goes to `files/runtime-data/logs/setup_<date>.log`. A folder too deep for Windows is refused before anything is touched.
- **Failure, cancel, retry:** a failed step ends setup with a plain message and the log location; running the launcher again picks up from what is already in place. Cancel and close are described next.
- **Persistence:** the choices are read once, when Begin Setup is pressed, and are not saved.
- **Live log (v0.7.2 Phase 6, ACT72-059):** the progress log follows new lines while its reader is at the bottom. A reader who scrolls up keeps their place, to the pixel, while setup keeps writing, and following resumes once they are back at the bottom. Every line is kept, and only the window's own thread writes the log.
- **Known gaps:** the "Setup did not complete" dialog and Open log folder are checked only from source text, and no native journey drives the window. Begin Setup and the live log are driven in the real window by an automated test (since v0.7.2 Phase 6).

### Cancelling or closing first-run setup
`ACT.SETUP.FIRST-RUN.CANCEL`

- **Purpose:** declining setup is an ordinary outcome, not a reported failure.
- **How to reach it:** Cancel on the intro screen, the window's close control, or "Stop setup?" when the window is closed during the base install or while the optional voices are being checked or installed.
- **States and outputs:** not started exits with code 2, and the launcher prints "Setup cancelled. Nothing was installed." and closes without pausing. A run that failed or was closed part-way exits 1, and the launcher keeps its window open with the log location. Success exits 0. A cancelled run never writes the "packages installed" stamp. The base-install progress view has no Cancel button.
- **Stop setup?** (v0.7.2 Phase 6): answering **No** keeps whatever is running going and launches nothing (ACT72-038). Closing during the base install asks the same question; **Yes** ends the running pip and everything it started, starts no later step, and closes the window once setup's worker has reported; the exit is 1 and the log says to run Setup_and_Run again to finish (ACT72-039).
- **Differences:** the TTS tool's Install & Continue window cancels on close without asking.

### App-local Python (stage 0)
`ACT.SETUP.APP-PYTHON`

- **Purpose:** give the app a known Python 3.12 of its own, inside its folder, so setup and repair never depend on or change the computer's Python.
- **How to reach it:** automatic. On first run and before an environment repair, the launcher runs `scripts/shared/bootstrap_host.ps1`, which asks yes/no before any download.
- **States:** a working app Python is used as is. If it is absent or broken, the download is offered. Declining exits 2 and changes nothing; failure exits 3. If PowerShell itself is blocked, the launcher falls back to `py` or `python` on PATH, which bootstrap still checks.
- **Inputs and outputs:** one pinned standalone CPython archive is downloaded to `files/temp/bootstrap`, checked against its SHA-256 before unpacking, moved to `files/runtime-data/python` with one rename, and accepted only after it runs (ssl, venv, ensurepip and a real Tk window). There is no installer, no administrator rights, no WinGet and no PATH change. Bootstrap's interpreter choice rejects any Python whose Tk cannot initialise. The fully supported range is 3.11 to 3.12, and 3.12 wins over a newer interpreter.
- **Persistence:** the app Python stays in `files/runtime-data/python` across repairs.
- **Differences:** macOS has no app-local Python (see the macOS launcher).

### Install-folder depth check and eSpeak NG data path
`ACT.SETUP.LONG-PATHS`

- **Purpose:** stop a deeply nested extraction from producing a half-built install whose voice engines fail later with cryptic errors.
- **Behaviour:** setup and repair measure the app folder's path against a limit that depends on whether Windows long-path support is on. A folder that is too long is refused with the folder shown and a shorter example; nothing is installed and no Windows setting is changed. Separately, when eSpeak NG's bundled data path is too long for its fixed buffer, the data is linked (never copied) under a short project-owned root. An installation that already fits is left alone, and when no short root can be used the error says so.

### Hash-locked dependencies and the verified package store
`ACT.SETUP.DEPENDENCY-LOCK`

- **Purpose:** every install and repair produces the same verified packages, and repairs can work offline from files already kept on the computer.
- **Behaviour:** on Windows x86-64 CPython 3.12, every package comes from `scripts/requirements-lock-windows-py312.txt`. Each artifact is fetched into `files/runtime-data/python-packages` against its SHA-256 (or found there already) and installed from that store alone, with no index. A package the lock does not name cannot be installed, and a kept file whose hash changed is refused. Files that do not belong in the store are moved to `files/runtime-data/python-packages-quarantine` and never installed. pip is never upgraded, its cache is `files/runtime-data/pip-cache`, and no inherited pip configuration applies. On any other interpreter, the `==` pins of `requirements.txt` install under the same pip policy.
- **Failure and retry:** a kept file that fails its check is fetched once more. A store that cannot be made safe installs nothing.
- **Persistence:** the store survives environment rebuilds, which is what makes offline repair possible.

### English sentence data for the Edge voices
`ACT.SETUP.SENTENCE-DATA`

- **Purpose:** supply the sentence splitter the Edge voices need, verified and kept in the app folder.
- **How to reach it:** first-run step 5. The wizard's intro discloses the size and source before Begin Setup. Otherwise, a TTS Edge conversion that needs the data asks before downloading it.
- **Behaviour:** one pinned NLTK data commit is used. The archive and every installed file are checked against pinned SHA-256s and installed into `files/runtime-data/nltk_data` with one rename. Anything that does not match installs nothing. NLTK searches only that folder, never the user's profile. A failed fetch during setup is not fatal. Answering No in the TTS prompt starts nothing and downloads nothing.

### Optional voices: review, consent and install
`ACT.SETUP.OPTIONAL-VOICES`

- **Purpose:** the one consented route for installing the optional local voices (Kokoro, Chatterbox Turbo, Qwen3 CustomVoice, Qwen3 Cloned Voices) and their models.
- **How to reach it:** after the first-run base install, for the voices ticked in the wizard. The TTS tool's Install & Continue embeds the same panel.
- **States:** checking (Cancel) -> review (Skip, or Install Selected Components) or "nothing needs to be installed" (Continue) -> installing (Cancel) -> installed (Continue) or failed (Continue without them, or Try again). Choices that cannot be installed now are listed with the reason.
- **Rules:** a read-only plan is made and shown in full first; nothing is downloaded before the person presses Install Selected Components. That click creates exactly one consent, whose terms match what the worker derives from the plan that was shown. A second click does nothing, and Install is never the Enter-key default. Skip, Cancel and closing download nothing and keep what already works. Try again makes a new plan and needs a new confirmation.
- **Inputs and outputs:** each request and result is a versioned JSON file in `files/runtime-data/optional-setup/<request>/`. The worker runs only in the app's `.venv` (`python -E -s -m tts.optional_setup_worker`) and only if its whole process tree can be contained. A timed-out worker and its children are ended. Each request gets one terminal result, published once.
- **Install log (v0.7.2 Phase 6, ACT72-059):** it follows new steps while its reader is at the bottom and keeps a reader who scrolled up (wheel or scrollbar) where they are.
- **Differences:** the first-run wizard asks "Stop setup?" on close (see the cancel gap above); Install & Continue cancels on close.

### Launch from Setup_and_Run
`ACT.SETUP.LAUNCH`

- **Purpose:** the everyday start.
- **How to reach it:** double-click `Setup_and_Run-audiobook-creation-tool.bat`.
- **Behaviour:** with a `.venv` present, the launcher asks `bootstrap.py --venv-check`. Exit 0 starts `pythonw bootstrap.py --launch-only` detached, with no console. Any other exit takes the repair route. The launch then runs a bounded self-heal (environment, packages, FFmpeg, Kokoro), never the full first-run install. Repairs run behind a small progress window whose live log follows new lines at the bottom and keeps a reader who scrolled up in place (v0.7.2 Phase 6, ACT72-059). The launcher window then starts with its output captured in `files/runtime-data/logs/launch_<date>.log`, and if it exits with an error within 1.5 s the launch is reported as failed. Problems that could not be fixed are collected into exactly one "Some features are unavailable" warning, shown only after the app window exists. An environment too broken to carry the app still reports before any window. A leftover pre-v0.6.7 `scripts/Universal` folder is reported once in the launcher's status bar and never deleted. The model cache (`HF_HOME`) points inside `files/runtime-data/models/huggingface`.
- **Known gaps:** the early-crash detection (non-zero exit inside the grace window, with the tail of the launch log) has no automated test.
- **Differences:** Windows asks `--venv-check` first because it cannot wait for the detached launch; macOS runs `--launch-only` in the foreground and reads the same exit codes.

### Environment health assessment
`ACT.SETUP.VENV-HEALTH`

- **Purpose:** decide quickly, without installing anything, whether `.venv` can carry the app.
- **States:**
  - **Healthy.**
  - **Degraded** (launch with limits): Python outside 3.11 to 3.12 or Tk not starting, when no better Python is available; or no display.
  - **Repairable** (exit 3): the interpreter does not run; no ssl; it runs on another copy's Python (a copied folder); incompatible Python or broken Tk when a better base exists; a repair was requested; package files are missing under intact metadata.
  - **Absent.**
- **Behaviour:** a healthy check costs one subprocess. Anything that cannot be read counts as not proven, never as healthy.

### Automatic environment rebuild
`ACT.SETUP.VENV-REPAIR`

- **Purpose:** recover a damaged or outdated `.venv` without anyone deleting anything by hand.
- **How to reach it:** automatic when the health check says repairable. The launcher prints "repairing the app environment", prepares the app's Python and runs `--repair-venv` from it, never from the venv being replaced.
- **Behaviour:** only the Python environment and its packages are rebuilt, from the app's Python and the verified package store. A complete store needs no network. The old `.venv` is renamed aside (`.venv.replaced`) and put back if the new one fails to build, install, import or launch. A voice engine held under `.venv/engines` is carried to the new environment at the same path and never deleted. An interrupted repair is finished first on the next start. After a repair, the launch never asks for another one. If the repair failed but the kept environment still runs, the app opens with a notice and the repair is tried again next start.
- **Persistence:** settings, outputs, downloaded models and the Qwen3 engine are untouched.

### Requirements stamp, import proof and launch-time package reconcile
`ACT.SETUP.REQUIREMENTS-STATE`

- **Purpose:** keep an existing installation in step with the packages a new release needs, and catch packages that went missing or stopped importing.
- **Behaviour:** a "reconciled" stamp (a hash of `requirements.txt` plus the lock) is written only after pip succeeded and every required module really imported. A changed pin set is reconciled once, in place, at launch, behind an "Updating the app's components…" window. The environment is never deleted for it and no model is downloaded. A package missing despite matching pins is found by a cheap presence check and repaired ("Restoring the app's components…"). The real import proof is redone after 7 days or when the interpreter changes. Failures open the app anyway, add one line to the single notice, and are retried next start.
- **Persistence:** both records live inside `.venv`, so a rebuilt environment never inherits them.

### FFmpeg proof and health record
`ACT.SETUP.FFMPEG.HEALTH`

- **Purpose:** one answer to "which FFmpeg does this app use, and does it really run here?" for setup and for every tool.
- **Behaviour:** a usable FFmpeg is an ffmpeg and ffprobe pair from one folder, and it counts only after both actually run (bounded, hidden `-version` calls). The proven pair is pinned in `files/runtime-data/ffmpeg-state.json` and reused while both files are unchanged. A changed or deleted binary invalidates the pin. While the pin holds, a launch runs no other FFmpeg on the computer. Candidates are tried in this order: `files/bin`, the app's versioned builds, PATH, WinGet package folders, Homebrew. Another copy's `files/bin` is never used. The failure text says running the same launcher again will not help, and never suggests turning protection off.

### FFmpeg repair at setup and on every launch
`ACT.SETUP.FFMPEG.REPAIR`

- **Purpose:** a missing or broken FFmpeg fixes itself on the next ordinary start.
- **Behaviour:** first-run setup and every launch use the same repair. The order is the pinned pair on file, then (Windows) the app's own verified build or (macOS) Homebrew. Windows never runs a package manager. Only a proved pin counts as ready; an installer's exit code never does. On a launch, the repair shows "Setting up the audio tools…" and may download the pinned build without a separate yes/no. If it fails (for example offline), the app opens in limited mode with one notice naming only the routes actually tried; Edge TTS still works. An FFmpeg problem never rebuilds the Python environment, and the launch after a successful repair does no work. In first-run setup, a failed FFmpeg step fails setup.
- **Note:** an older working note said a launch could detect a missing FFmpeg but never install one. The current source repairs it on launch, so that note is out of date.

### The app's own FFmpeg build (Windows)
`ACT.SETUP.FFMPEG.PORTABLE`

- **Purpose:** FFmpeg on Windows without installing anything on the computer.
- **Behaviour:** only the pinned download URL (Gyan FFmpeg 9.0.1) is used. The archive's SHA-256 is checked before anything is extracted, and every member is vetted first (no absolute paths, traversal, links or absurd sizes). The pair is proved in staging, moved with one rename into `files/bin/ffmpeg/<version>`, proved again there and only then pinned. Any failure before the pin leaves the previously working pair active, with nothing partial in the final place. An already-promoted build is adopted without a download.
- **Persistence:** the build stays until Clear Downloaded Data's "Portable binaries" item removes it.

### Launch-time Kokoro check and package self-heal; Chatterbox probe
`ACT.SETUP.ENGINE-SELF-HEAL`

- **Purpose:** find a Kokoro install that will not run before the person reaches a Kokoro conversion.
- **Behaviour:** the proof imports Kokoro's synthesis chain offline and builds no model, so it never downloads weights or spaCy's model. Missing Kokoro weights are reported, not downloaded, and are not a failure.
- **States:**
  - **Healthy:** the result is remembered for 7 days.
  - **Broken:** one repair ("Repairing the Kokoro AI voice install…") through the one package installer. If the repair's proof still fails, it is not retried the same day.
  - **Unverified** (the proof could not finish): a notice and no repair.
  - **Blocked by Windows Application Control:** explained in plain words; reinstalling does not help.
- **Chatterbox:** its health probe runs in a subprocess against `.venv` and also downloads nothing and builds no model.
- **Failure:** never blocks the launch; the single notice explains what is unavailable.

### Offline restore of Kokoro's spaCy English model
`ACT.SETUP.SPACY-RESTORE`

- **Purpose:** keep Kokoro usable after an environment rebuild, with no new download or consent, when an earlier consented install kept the model's wheel.
- **Behaviour:** this runs only after a fully proved package reconcile. If the kept wheel in `files/runtime-data/models/spacy` is exactly the approved size and SHA-256, the model is absent and spaCy is compatible, it is reinstalled offline (no index, no dependencies, hash enforced). Otherwise nothing runs, and Kokoro offers Install & Continue as before. A failed reinstall is logged and never fails setup.

### Engine lease
`ACT.SETUP.ENGINE-LEASE`

- **Purpose:** an environment repair or cleanup never moves or deletes the Qwen3 engine while it is being installed or used.
- **Behaviour:** before changing `.venv`, setup recovery and repair take all three Qwen3 locks in `files/runtime-data/qwen3/` (setup, inference, engine), in one order, or none. A busy lock is an immediate refusal that says what is running and changes nothing. The lease is held through the whole replacement, including a rollback, and released even if the work fails. Locks held by a process that dies are released by the operating system. Another copy's GPU guard does not block this copy.

### Preferences: Repair App Environment
`ACT.SETUP.REPAIR`

- **Purpose:** an in-app way back from a damaged environment that keeps the Qwen3 engine.
- **How to reach it:** Preferences & Data, "Downloaded data" card, "Repair App Environment…".
- **Behaviour:** asks for confirmation first; declining changes nothing ("Repair cancelled. Nothing was changed."). Confirming writes one request file inside `.venv` and removes nothing; the running app and any conversion are left alone. On the next start, the health check reads it as "repair requested" and the ordinary rebuild runs. If the request cannot be written, the status line says so and tells the person to close the app and start it again with Setup_and_Run.
- **Differences:** unlike Clear Downloaded Data's environment item, this keeps the separately installed Qwen3 engine and needs no helper after the app exits.

### Preferences: Clear Downloaded Data
`ACT.SETUP.CLEAR-DOWNLOADED-DATA`

- **Purpose:** reclaim space used by downloaded data and rebuildable environments, safely and with an honest report.
- **How to reach it:** Preferences & Data, "Downloaded data" card, Clear Downloaded Data. A review dialog opens, then a confirmation, then the app closes.
- **States:** four rows: Private Python environment (`.venv`), Portable binaries (`files/bin`), Downloaded voice models (`files/runtime-data/models`) and Application logs (`files/runtime-data/logs`). Each is present (selectable), missing (disabled) or unavailable (disabled, with the reason). Sizes start as "calculating". Nothing is preselected, and Review stays disabled until a deliberate tick. The confirmation lists only the selected items, with Cancel as the default button.
- **Behaviour:** the request carries item ids only. A helper must acknowledge it (within 20 s) before the app closes. The helper runs on a Python that is not a virtual environment and lies outside everything the cleanup can remove; inside the app folder, only the app's own Python in `files/runtime-data/python` qualifies. If the helper cannot start or does not answer, the request is withdrawn, the app stays open and nothing changes. After the app exits, the helper removes exactly the selected items (`.venv` itself; the other three are emptied) and writes one result. The next launch shows that result once. A request older than 6 hours is never run. Settings, outputs, sources and config are never offered.
- **Persistence:** selections are never saved; the result record is retired once shown.
- **Known gaps:** no registered native journey drives the whole flow (real dialog clicks, app exit, the helper's deletion, the result on the next launch).
- **Differences:** Reset Preferences is a separate control and never touches downloaded data.

### Clear Downloaded Data target safety
`ACT.SETUP.CLEAR-DOWNLOADED-DATA.SAFETY`

- **Purpose:** the rules that stop the only code in the app that deletes from removing anything but the four listed items.
- **Behaviour:**
  - Each target is re-derived from its fixed id and checked again (inside the app folder, not protected, a real folder, not a link) immediately before removal.
  - A target swapped for a link is refused. A link inside a target is removed as a link and never followed.
  - A `.venv` holding a separately installed voice engine is refused and not offered.
  - `.venv` and the models folder are removed only while the helper holds the engine lease; if Qwen3 is busy they are left whole, with a message saying why.
  - Nothing is removed if the app does not exit in time.
  - The request is used up before the first deletion, so it can never run twice.
  - Outcomes are removed, missing, refused or failed (for example, a locked file). Refusals say nothing was removed and what to do.

### Application version identity
`ACT.SETUP.VERSION`

- `scripts/shared/version.py` holds the single version string. The release archive name uses it. A disagreeing `project.version` in `config.toml` is warned about and the code version wins.
- **Known gaps:** the version is still 0.7.1 on the v0.7.2 branch. Per the plan, the v0.7.2 version, config and test identity is set together at a named Phase 8 checkpoint.

### Release packaging
`ACT.SETUP.PACKAGING`

- **Purpose:** defines what a person downloads. The packager runs only on the developer's checkout and is itself excluded from the archive, but its output is the shipped product.
- **Behaviour:** the Windows archive holds only the Windows launcher, `README.md`, `config.toml`, the git-tracked `scripts/` tree and exactly six named reference WAVs from `files/Cloned-Voice-Uploads`. Developer-only entry points, the verification gate, development trees, environments, caches and runtime data never ship. `config.toml` must ship with developer mode off, which is checked again in the finished archive. A build refuses uncommitted changes and an existing archive of the same name, checks every member against its source, and publishes all or nothing. The ordinary build produces only the Windows archive.

### macOS launcher
`ACT.SETUP.MACOS-LAUNCH`

- **Purpose:** the macOS counterpart of the Windows launcher. Not part of the v0.7.x release: no macOS archive is distributed until a native macOS qualification exists. The code is kept.
- **Behaviour:**
  - Without its `scripts/` folder beside it (Gatekeeper App Translocation, or the `.command` copied out on its own), it explains how to move the folder and keeps the window open.
  - With a runnable `.venv`, it runs `--launch-only` in the foreground. A detached helper (`close_terminal.py`) then closes the Terminal window without the "terminate running processes" prompt.
  - Exit 3, or a present but unrunnable interpreter, takes the repair route.
  - First run looks for a Tk-capable `python3.12`, `python3.11` or `python3`. If none is found it may install Homebrew (asking for the Mac login password), Python with Tk, and ffmpeg. As a last resort it falls back to a headless install.
- **Differences:** unlike Windows, a cancelled setup (exit 2) is also reported as "did not complete".

### Optional-setup v3 foundations (not in the shipped app)
`ACT.SETUP.V3.CONSENT`, `ACT.SETUP.V3.EXCHANGE`, `ACT.SETUP.V3.SUPERVISOR`, `ACT.SETUP.V3.DISPLAY`, `ACT.SETUP.V3.ARTIFACTS`

These modules are groundwork for a future version of the optional-setup protocol. Each states that it has no production caller, and a person using the app cannot reach them. Some suites run only in the guarded v3 groups. They are inventoried so their contracts stay visible, but they are not release-required:

- **Consent and wire codecs** (`optional_setup_v3`, `optional_setup_wire_v3`): strict v3 consent spent once; any changed term needs a new consent; v2 and v3 are never confused; a read-only planning result never permits confirmation.
- **Exchange** (`optional_setup_exchange_v3`): a fixed, bounded exchange folder with one winner for duplicate publishers, refusal of junctions and forged replacements, and no repair of interrupted exchanges.
- **Supervision** (`optional_setup_supervisor_v3`, `optional_setup_planning_bridge_v3`, `optional_setup_readonly_context_v3`): only test factories can launch, with a fixed program and a scrubbed environment; timeouts empty the job; a leftover grandchild is rejected and reaped.
- **Presentation and confirmation** (`optional_setup_display_controller_v3`, `optional_setup_tk_harness_v3`): delivery counts only after a real Tk paint; at most one consent; a decline never comes back to life. The Tk harness window exists only in tests.
- **Artifact store, transfer ledger, resource budget** (`artifact_store`, `artifact_transfer`, `optional_setup_resource_budget`): wrong bytes never publish, no overwrite, no redirects, no reuse of a finished consent, and fixed metadata ceilings. The production Qwen3 install path imports the store and transfer modules but no production code calls their functions; this was found by reading the code, not proved.

### Intentional differences from other tools

- Setup has no per-tool job controls. The base install has no Cancel button. The optional-voices panel has its own Cancel, Skip and Try again.
- Recoverable launch problems are never shown as separate dialogs: they are collected and shown once, after the app window exists.
- The launch may download the app's own FFmpeg build behind a progress window without a separate yes/no. Optional voice models are downloaded only after the explicit Install Selected Components click.
- Clear Downloaded Data acts only after the app exits, through a separate helper running outside `.venv`. Every other destructive action in the app runs in-process.
- Windows installs nothing on the computer. macOS may install Homebrew and Homebrew packages.

### Not verified here

- A genuinely fresh Windows install and repair: first run with no assets, deliberate optional choices, offline reuse, and recovery after controlled damage to a disposable copy. This is the `fresh-windows` qualification, which the routine gate does not run. Windows 11 evidence does not cover Windows 10.
- Real local-engine health and installs (Kokoro, Chatterbox Turbo, both Qwen3 choices) through the optional-voices panel: the `optional-engines` qualification.
- The real first-run window and the launch progress and warning windows, driven by real input: no native journey covers them.
- Display scaling other than 100% for the first-run window and the review panel: an owner check.
- Native macOS (the `.command`, Homebrew routes, Terminal auto-close): not run.
- Real network behaviour of the stage-0 Python download, the FFmpeg build download and the sentence-data download against their live hosts.
