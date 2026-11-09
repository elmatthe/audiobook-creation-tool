# M4B Metadata Editor

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## M4B Metadata Editor

The M4B Metadata Editor changes the tags, chapter titles and cover art of audiobooks that already exist (`.m4b`, `.m4a`, `.mp4`). It never edits a file in place: every action writes edited copies into a new numbered run folder and leaves the originals untouched. The workflow is: import files (one file becomes one Book page), review what each file already carries, type changes per Book or once for all Books in the Shared fields, then run one of three actions: **Save Tags**, **Clear All Tags (keep chapters)** or **Remove Series Numbering**. The panel lives in `scripts/m4b/metadata/m4b_metadata_editor.py`; the rules sit in four Tk-free modules beside it: `m4b_metadata_workflow.py` (workspace, source observation, what counts as an edit), `m4b_metadata_plan.py` (the frozen plan for one action), `m4b_metadata_processing.py` (one Book: stage, edit, validate, publish) and `m4b_metadata_batch.py` (the run over all Books, numbering, pause/cancel/retry). It reuses the shared Book navigator, Shared/Book field surface, artwork control, importer, job controls and Summary | Detailed log.

### Open the Metadata Editor panel
`ACT.METADATA.PANEL-ENTRY`

- Reached from the launcher's M4B Metadata Editor button; the launcher calls `build_ui(parent)`. Running the file directly opens the same panel in its own window.
- A new panel shows one empty Book ("Book 1 of 1"), blank Shared fields, status Ready and no run. Building it creates no output folder.
- The package's `__init__.py` holds only a docstring.

### Import Folder and Add Files
`ACT.METADATA.IMPORT`

- **Import Folder** (dialog "Select a folder of M4B files") scans the folder and all its subfolders (hidden folders excluded) and replaces the workspace with one Book per `.m4b`/`.m4a`/`.mp4` file, in order. Two files in one folder are two Books. If any Book already holds a file or edits, it asks "Replace the current Books?" first.
- **Add Files** (dialog "Select M4B file(s)") appends one Book per new file, skips files already in the workspace and makes the last added Book current.
- Each file's tags, series information, cover presence and chapter titles are read once; nothing is written. The log says how many Books were made and how many were skipped.
- Both buttons are ignored during a scan and disabled while an action runs.
- Known gap: nothing tests the "Replace the current Books?" answer, and no journey drives the real folder dialog (only Add Files' dialog is driven natively).

### Import progress, Cancel Import and scan confirmations
`ACT.METADATA.IMPORT-SCAN`

- During a folder scan the import status shows how many files were found, with a **Cancel Import** button.
- A whole drive or the home folder asks "Scan a very broad folder?"; a very large result asks "Import a large number of files?". Declining imports nothing.
- Checked since v0.7.2 Phase 4, through this panel but not by a native journey: Cancel Import ends a running scan and leaves the workspace as it was; the home folder is asked about before anything is scanned, and a result over the warning threshold before anything is imported; declining either imports nothing.

### Remembered dialog folders
`ACT.METADATA.REMEMBERED-FOLDERS`

- The file and folder dialogs reopen in the last folder used (`m4b_metadata.input_dir`); the artwork dialog in the last image folder (`m4b_metadata.cover_dir`). If that folder no longer exists, the home folder is used.
- Nothing else is saved: not the imported files, edits, Auto-number options or the output folder.
- Known gap: no test checks that a choice is saved and reused by the next dialog; the existing check only reads which keys the code writes.

### Clear All Imports
`ACT.METADATA.CLEAR-IMPORTS`

- Resets the workspace to one empty Book with blank Shared fields and forgets the last run. Nothing on disk is deleted or changed; earlier outputs stay, and the log keeps its history with a divider.
- An empty workspace clears without asking; otherwise it asks "Clear all imports?" and No changes nothing.
- Disabled and refused while an action runs or a scan is active.
- After a reset Retry Failed is no longer available for the earlier run.

### Book navigation and Remove Book
`ACT.METADATA.NAVIGATION`

- ◀ Previous, Next ▶ and the Book selector move between Books. Labels read "Book N — <title or filename>" (cut to 40 characters); numbers stay fixed while the workspace lives.
- Each Book keeps its own edits, chapter titles and artwork while you move around.
- **Remove Book** asks "Remove this Book?" when the page holds a file or edits; the file itself is never touched.
- There is no Add Book or Duplicate Book. Locked while an action runs.

### Source read-back
`ACT.METADATA.SOURCE-READBACK`

- Under the Current Book fields: the source file name and folder with "readable" (or the read error), a "Detected on file:" series line that names where the series came from (for example a vendor tag), and "Series Part · Artwork · Chapters" facts.
- A series name guessed from the album, or a part guessed from the track number, is shown here only and is never prefilled for writing.
- This is display only; it is never written.

### Per-Book fields
`ACT.METADATA.BOOK-FIELDS`

- Seven fields per Book: Title, Author / Artist, Album, Year, Genre, Comment, Series Name. They show the file's own values; showing them is not an edit.
- Preserve-by-default: only what you type counts, and a blank value or a value equal to the file's means "keep the file's value". A changed value is written to that Book's copy only.
- A series stored in a vendor or movement tag is never moved to a different tag unless you change it.
- Series Part is not editable here (see Auto-number). Fields are disabled while the matching Shared field is filled and while an action runs.

### Shared fields
`ACT.METADATA.SHARED-FIELDS`

- The tinted Shared group ("applies to every Book and overrides its own value") has the same seven fields plus Shared artwork. They start blank even when every file carries the same value.
- A filled Shared field overrides that field for every Book and disables the matching Book field; clearing it brings each Book's own value back. A blank Shared field writes nothing.
- Shared values are applied by Save Tags and re-applied after Clear All Tags; Remove Series Numbering ignores them.

### Artwork
`ACT.METADATA.ARTWORK`

- An artwork control in the Shared group and one in the Current Book group, each with a small preview, **Choose…** and **Clear**. The dialog only offers image types this machine can decode (HEIC only where supported; it is converted in memory).
- The chosen image is decoded straight away; an unusable file shows an "Artwork:" error and leaves the previous choice in place. The image file itself is never written.
- Shared artwork overrides and disables every Book's artwork control.
- What happens to the cover: Save Tags keeps the file's cover unless you chose one; Clear All Tags removes it unless you chose one; Remove Series Numbering never changes it.
- Choose… and Clear each get at least their label's width, so both read whole at every size (ACT72-020, fixed in Phase 5; the M4B Maker and MP3 Tool were clipped the same way).

### Chapter Titles
`ACT.METADATA.CHAPTER-TITLES`

- One box per Book in section 3, showing the file's chapter titles until you edit it.
- Positional: line N renames chapter N. A blank or unchanged line keeps that chapter's title; blank lines keep their place and are never collapsed; extra lines are ignored.
- Renaming rebuilds only the chapter track with a stream copy: chapter count, start/end times, audio and cover are kept. If no line changed, the chapter step does not run at all.
- Applied by Save Tags and Clear All Tags; ignored by Remove Series Numbering. Locked while an action runs.

### Auto-number Series Part
`ACT.METADATA.AUTO-NUMBER`

- "Auto-number Series Part (Save / Clear; successes only)" and "Start Part (blank → 1)". Off by default.
- When on, Save Tags and Clear All Tags give consecutive Series Parts, starting at Start Part, only to Books that succeed. A failed Book uses up no number; Retry Failed gives it the next free number.
- An invalid Start Part (not a whole number of 1 or more) stops the action with a "Start Part:" message before any folder is made.
- When off, Save Tags keeps each file's own Series Part. Remove Series Numbering never numbers.

### Starting an action
`ACT.METADATA.RUN-START`

- Shared by all three actions. With nothing imported: "Import a folder or add M4B files first." and nothing happens.
- Otherwise one numbered run folder is reserved and the whole action is frozen: what each Book will get, plus the Auto-number settings. Edits made after this never reach the run, including its Retry Failed.
- A second action is refused while one runs. The work runs on one background thread that never touches the window.
- If reserving the folder or planning fails, an error dialog appears and no empty folder is left.
- Known gap: no test makes the reservation or the plan fail in this panel.

### Save Tags and Clear All Tags (keep chapters)
`ACT.METADATA.SAVE-AND-CLEAR`

- **Save Tags** writes only your explicit changes (Shared values first, then Book edits), any chosen cover and any renamed chapters onto the copies; every other tag is the file's own. With nothing to change, the copy is identical to the original.
- **Clear All Tags (keep chapters)** asks "Clear all tags?" first. The copies lose every tag and the cover, but keep their chapter markers and titles. Then only what you typed here (Book edits, Shared values, chosen artwork, chapter renames) is put back; the file's own unchanged values are not.
- Each action writes into its own new run folder.

### Remove Series Numbering
`ACT.METADATA.REMOVE-SERIES-NUMBERING`

- Asks "Remove series numbering?" first. The copies lose the Series Part, the track number (Explorer's # column) and the movement index in every tagger's namespace.
- The Series Name stays on whichever tag carried it; chapters, cover and all other tags stay.
- Pending edits on the pages, artwork choices and chapter renames are not applied, and Auto-number is ignored.

### Declining a confirmation
`ACT.METADATA.DECLINED`

- Answering No to "Clear all tags?" or "Remove series numbering?" starts nothing, reserves no folder and writes nothing; the workspace is unchanged. Save Tags has no confirmation.

### Unreadable files
`ACT.METADATA.UNREADABLE`

- A file whose tags cannot be read (damaged or not MP4) still becomes a Book. Its read-back says "the file's tags could not be read: <error>"; it prefills nothing.
- Actions skip it ("Skipped (unreadable)") and the other Books carry on; the file is never written.
- If no imported file is readable, the action stops with "None of the imported files could be read, so there is nothing to write."
- Known gap: nothing checks that this refusal also removes the run folder it reserved.

### Output: copies in a numbered run folder
`ACT.METADATA.OUTPUT`

- Every action writes to `<output base>/M4B-Metadata-Outputs/M4B-Metadata-N/`. Each copy keeps its source file name and extension, all in one flat folder. Same names get numbered (`Book.m4b`, `Book-1.m4b`); a file already there is never overwritten; a run folder inside a source folder is refused.
- There is no in-place save and no custom destination.
- The output hint in the import band shows where the next run goes (after a start, that run's folder); in a narrow window it shows the end of the path.

### Open Output Folder
`ACT.METADATA.OPEN-OUTPUT`

- Opens the last run's folder, or the tool's output folder before any run (creating it if needed). An output-path problem shows an error dialog. Never locked.
- Checked since v0.7.2 Phase 4, through the panel but not by a native journey: before any run it reveals the tool's folder and reserves no run; a folder that cannot be made shows the error and reveals nothing; after a run it reveals that run's folder.

### Audio, chapter and artwork preservation
`ACT.METADATA.PRESERVATION`

- The audio is never re-encoded: tags are rewritten in place in the copy, the cover is swapped as an image, and chapter renames are a stream-copy remux.
- Before a copy is published it is read back and checked against the plan: the audio is readable, every planned value is present, cleared values are gone, the cover is there exactly when it should be, chapter titles are in order, and chapter count and start/end times match the source (to 10 ms), with a complete chapter track after a rename. Any mismatch fails that Book.

### Failed Books publish nothing
`ACT.METADATA.FAILURE-SAFETY`

- Each Book is copied into its own private staging folder (`<run>/.work/<name>/`), edited and checked there, then moved into the run in one step.
- A failure at any step (the source vanished, unusable cover, copy, tags, cover, chapters, validation) leaves nothing for that Book in the run and removes its staging folder. Publishing never overwrites a file that appeared at the destination.
- A copy that passed validation but could not be published is kept in staging so Retry Failed can reuse it.
- That copy lives only while a Retry Failed can reach it: a cancelled run keeps nothing, and Clear All Imports, a new action or closing the tool removes it (ACT72-034, fixed in v0.7.2 Phase 6, as in the MP3 Tool and the Maker).

### Batch run and Book status
`ACT.METADATA.BATCH-RUN`

- Books run one at a time in workspace order. A failed Book does not stop the next; the run then ends "completed with failures".
- A Book that cannot even start (for example its chosen artwork became unusable) fails without a retry; other failures can be retried.
- Each Book's Status shows Ready, Queued, Processing, Completed, Failed, Skipped (unreadable) or Not attempted. The job area shows progress, the current file as "<file> (N of M)" and an ETA.
- The Summary ends with a line counting completed, failed, skipped and not-attempted Books and the run folder.

### Pause and Resume
`ACT.METADATA.PAUSE`

- Pause takes effect at the next checkpoint (between Books, or between steps inside a Book); nothing runs while paused. Resume carries on and the run finishes normally.
- A chapter rename already running is never stopped or suspended by Pause: it finishes, the copy is checked, and the run pauses before that Book is published (measured on a real remux in v0.7.2 Phase 6D).

### Cancel
`ACT.METADATA.CANCEL`

- Cancel stops a running chapter rename (either of its two FFmpeg steps: reading the chapter list or rebuilding the chapter track) within a fraction of a second, through that step's own process handle; any other FFmpeg, even one this program started, is untouched. No later step starts. Otherwise Cancel takes effect at the next checkpoint. Books already published stay; the Book in progress publishes nothing, and its half-written rename output and temporary chapter list are removed; the rest are "Not attempted" (and are not offered by Retry Failed). A stopped rename is never reported as a failure. (ACT72-033, fixed in v0.7.2 Phase 6D; before, Cancel waited for FFmpeg to finish the step.)
- A Cancel that arrives while a Book is being published lets that Book finish and stops before the next.

### Retry Failed
`ACT.METADATA.RETRY`

- Re-runs only the Books that failed in a retryable way, in the same run folder with the same frozen plan; anything edited since is ignored and Books already done are not touched.
- A kept, validated copy is reused, even if the original file has since gone. Refused while a run is active or when there is nothing to retry.
- A chapter rename FFmpeg refuses (a non-zero exit, or an error logged with exit 0, as when chapters would be lost) fails only that Book, retryably; Retry Failed rebuilds it. A cancelled rename never counts as such a failure.

### Controls lock while an action runs
`ACT.METADATA.RUN-LOCKING`

- During a run: import buttons, Clear All Imports, the navigator, Shared and Book fields, artwork, the Chapter Titles box, the three actions and the Auto-number controls are disabled, and unlock when it ends. Clear Log and Open Output Folder stay usable.

### Activity log
`ACT.METADATA.ACTIVITY-LOG`

- One Summary | Detailed log at the bottom. Each action (and each Retry Failed attempt) starts with a divider naming it and the run folder; history is kept across runs and across Clear All Imports (up to 400 lines per pane).
- Detailed lists each Book's steps in order; Summary marks each published file with ✓.
- Clear Log clears the visible text only and is never locked.
- Known gaps: no test presses Clear Log in this panel or checks a second run's divider (ACT72-053, Phase 6); the panes follow, hold and resume as the shared log view does.

### Layout and keyboard
`ACT.METADATA.LAYOUT`

- Four stacked sections: 1. Import & Books, 2. Metadata, 3. Chapters & Save, Activity. Nothing scrolls the whole tool; only the Chapter Titles box and the log scroll and shrink.
- In the launcher's small windows (920x600, 1024x720) a tighter layout shrinks padding and uses shorter wording (the Auto-number option joins the chapter caption line, the preserve note joins the Current Book caption); nothing is hidden. Choosing artwork does not make the Metadata section grow.
- Tab moves through the sections in order; Ctrl+A, Delete, BackSpace and Alt+Up/Down in a text field only edit that text.
- Display scaling other than 100% is an owner check.

### Light / Dark appearance
`ACT.METADATA.APPEARANCE`

- Uses the shared compact Light and Dark styles with no colours of its own. Switching appearance recolours the text boxes, log and selector list without rebuilding the panel or changing any value, position or running action. The look itself is for the owner to approve.

### Closing during work
`ACT.METADATA.CLOSE`

- Closing the window cancels a running action and any scan, stops the panel's event handling and stops listening for appearance changes. Closing while a save runs is expected to exit cleanly with no window or process left.
- The cancel that closing asks for now also reaches a running chapter rename (ACT72-033, v0.7.2 Phase 6D); whether the worker stops it before the interpreter ends is not measured, so the launcher's end-of-process sweep of the FFmpeg it started remains the guarantee.
- Whether the Book in progress leaves anything in `.work` when the process exits before the next checkpoint is not checked.

### Intentional differences from other tools

- One file is one Book; the M4B Maker groups a folder's tracks into one Book.
- The navigator has only Remove Book; no Add Book or Duplicate Book (Books come only from imports).
- Blank chapter-title lines keep their place and preserve that chapter; the MP3 Tool collapses blank lines.
- Copies only: no in-place save and no custom destination (the M4B Maker offers a custom destination).
- "Clear All Imports" (reset the workspace) is deliberately not called "Clear All", because "Clear All Tags" is a different action on the output copies.
- Shared fields start blank even when every file agrees, and Series Part is read-back plus Auto-number, not an editable field.

### Not verified here

- No native journey runs an accepted Remove Series Numbering, types into a Shared field, navigates between several Books, presses Pause, Cancel, Retry Failed or Open Output Folder, or drives the real folder or artwork dialogs; these rely on in-process tests.
- Windows display scaling other than 100%, and the final Light/Dark look, need the owner.
- macOS behaviour (the aqua layout hints exist in code) is not qualified here.
- Very large libraries (many Books, very long books with many chapters) are not measured for speed.
- Cancel and Pause during a chapter rename are measured in-process on the Editor's own remux, slowed to the Book's playing time with FFmpeg's `-re` on a coverless Book (FFmpeg 9 ignores `-re` while a cover picture is mapped), and through the panel with real threads; not through a native window. How long an unslowed rename of a long real audiobook takes is not measured.
