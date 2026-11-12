# M4B Maker

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## M4B Maker

The M4B Maker turns ordered MP3 tracks into chaptered M4B audiobooks, one M4B per Book. The user imports a folder of audiobook folders (one Book per folder) or adds MP3s to a Book by hand, orders the tracks, names the chapters, fills in Shared or per-Book metadata, artwork, silence and series options, and presses Build M4B(s). Every Book with tracks is planned once, built in a private staging folder, checked, and only then published under its final name. Pause, Cancel and Retry Failed are the shared job controls.

Source: the panel is `scripts/m4b/maker/m4b_maker.py` (`M4BMakerUI`), a thin Tk layer over four Tk-free modules: `m4b_maker_workflow.py` (the Book model and its rules), `m4b_maker_plan.py` (the frozen run plan, naming and destinations), `m4b_maker_processing.py` (FFmpeg, chapters, tags, staging and publication for one Book) and `m4b_maker_batch.py` (the run, success numbering and Retry Failed). Artwork uses `scripts/artwork/m4b_artwork.py` and `scripts/artwork/m4b_artwork_ui.py`, which the M4B Metadata Editor shares. The navigator, Shared/Book field surface, importer, job controls and log view are shared components instantiated here. The CLI-only `make_m4b` in the Edge TTS engine is not part of this tool (see the TTS engine inventory, `ACT.TTS.CLI`).

### Books workspace and navigator
`ACT.MAKER.WORKSPACE`

- Purpose: the Maker works on a list of Books; each becomes one M4B.
- How to reach it: section 1 "Import & Books", the navigator row: ◀ Previous, Next ▶, the "Book X of Y" selector, Add Book, Duplicate Book, Remove Book.
- States: one empty Book at startup. Each Book is labelled "Book N — hint", the hint being its Title, else its effective Album, else the one folder its tracks come from. Numbers are not reused within a workspace; a folder import starts again at 1. Locked while a build runs.
- Behaviour: Duplicate copies a Book's settings but none of its tracks. Remove Book on a Book with tracks or edited settings asks "Remove this Book?"; No keeps it. Each Book keeps its own tracks, fields and chapter text when you move between Books.
- Persistence: none; the workspace is lost when the tool or application closes.

### Import Folder (one Book per folder)
`ACT.MAKER.IMPORT-FOLDER`

- Purpose: build the Books from a folder of audiobook folders in one step.
- How to reach it: Import Folder, then "Select a folder of MP3 audiobooks". The import status beside it shows the scan and Cancel Import.
- Behaviour: the chosen folder is scanned for MP3s; every directory that directly contains MP3s becomes one Book, tracks in natural order (1, 2, 10). Separate folders are never merged. The new Books replace the whole workspace; if any Book already has tracks or settings, "Replace the current Books?" is asked first. Imported Books start with empty fields: the Maker reads no tags from the sources. An empty scan leaves one empty Book. The log reports how many MP3s in how many Books, plus any problems found.
- Confirmations and cancel: scanning a whole drive or the home folder asks first; a very large result asks before importing. Cancel Import stops a running scan.
- Persistence: the folder is remembered as `m4b_maker.input_dir` and the dialog opens there next time.
- "Replace the current Books?" is asked only when a Book holds work, and No keeps every Book and opens no folder dialog; Cancel Import ends a scan with the workspace as it was; the broad-folder and large-result questions are in the Maker's own words; the folder is remembered, with the home fallback (ACT72-052, v0.7.2 Phase 6). No native journey imports a folder in the Maker.

### Add Files to the current Book
`ACT.MAKER.ADD-FILES`

- Purpose: add individual MP3s to the Book currently shown.
- How to reach it: Add Files under the track list, then "Select MP3 files" (MP3 audio, or All files).
- Behaviour: the chosen files are sorted naturally by name and appended after the Book's existing tracks; they are never regrouped by folder and the Book's fields do not change. Files already in this Book are skipped, and the log says how many were added and skipped.
- States: refused while a folder scan runs; disabled while a build runs.
- Persistence: the folder of the first chosen file is remembered as `m4b_maker.input_dir`.
- A file already in the Book is skipped, and the log says how many were (ACT72-052, v0.7.2 Phase 6).

### Track order and removal
`ACT.MAKER.TRACKS`

- Purpose: set the chapter order of a Book and drop unwanted tracks.
- How to reach it: the "MP3 Tracks (this Book) — one chapter each" list (multi-select), Move Up, Move Down, Remove Selected; on the list, Alt+Up, Alt+Down, Delete or BackSpace, and Ctrl+A.
- Behaviour: a selection moves one step as a block and stops at the edges. Removing tracks keeps the Book's fields. Automatic chapter titles follow the new order. The shortcuts belong to the list only, so text boxes keep their own keys, and they are refused while a build has the track controls locked.

### Chapter Titles box
`ACT.MAKER.CHAPTER-TITLES`

- Purpose: name the chapters.
- How to reach it: "Chapter Titles — one title per line", beside the track list.
- Behaviour: until edited it shows one automatic title per track, the filename with one leading track number removed ("01 - Chapter One" gives "Chapter One"; the first "_" becomes ": ", "_s" becomes "’s", a trailing "_" becomes "?"). Line n names chapter n; blank lines are skipped; fewer lines leave the rest automatic; extra lines are ignored. The text is kept per Book and frozen into the plan at Build.
- States: disabled while a build runs.

### Shared and per-Book fields
`ACT.MAKER.FIELDS`

- Purpose: enter metadata once for every Book (Shared) or for one Book.
- How to reach it: section 2 "Book Settings": the tinted group "Shared — applies to every Book and overrides its own value" above "Current Book". Both have Artist / Author, Album Artist / Author, Album, Series Name, Silence Between Tracks (seconds) and Book Artwork; the Book group adds Title, Series Part, Output Filename and the Book's Status.
- Behaviour: a non-blank Shared value wins and disables the matching Book control; the Book's own value is kept and comes back when Shared is cleared. Values are stored as typed; clearing a field stores a blank. At Build the effective value (Shared, else Book, else blank) is frozen per Book.
- States: all fields are disabled while a build runs.

### Silence Between Tracks
`ACT.MAKER.SILENCE`

- Purpose: put a pause between consecutive tracks.
- Input: seconds as text, in Shared or per Book. Blank means 0. Negative, NaN, infinite or non-numeric text is refused.
- Behaviour: a positive value makes that Book use the Safe path and inserts one silent gap between adjacent tracks, never after the last. The gap belongs to the end of the chapter before it; the next chapter starts exactly at its own track.
- Failure: Build stops with "Silence for Book N: …" before any run folder is reserved.
- A bad Book or Shared Silence (a word, a negative, nan) is refused with "Silence for Book N", before any run folder is reserved or any worker starts (ACT72-032, ACT72-052, v0.7.2 Phase 6).

### Series Name and Series Part numbering
`ACT.MAKER.SERIES`

- Purpose: tag Books as parts of a series.
- How to reach it: Series Name in section 2 (Shared or per Book); Series Part in the Book-only row; "Auto-number Series Part" and "Start Part (blank → 1):" on the options line of section 3.
- Manual: Series Name and Series Part are written as the M4B's series tags; blank writes none.
- Auto-number: off when the panel opens. While on, the manual Series Part entry is disabled (its value is kept) and Books that succeed are numbered consecutively from Start Part. A failed Book uses no number; Retry Failed gives it the next unused one. Each number is written and checked on the staged file and committed only after the Book is published.
- Failure: a Start Part that is not a positive whole number stops Build with "Start Part: …". A failure while writing the number fails that Book and keeps its candidate for Retry Failed.
- Persistence: none of these options is saved.

### Book Artwork selection
`ACT.MAKER.ARTWORK`

- Purpose: choose the cover for all Books or for one Book.
- How to reach it: the "Book Artwork" control in Shared and in Current Book: a small preview, Choose… ("Select Book Artwork") and Clear.
- Behaviour: the dialog offers only image types this computer can decode (JPG and PNG always, HEIC/HEIF only when decodable). The file is checked before it is accepted; an undecodable or mislabelled image shows "Book Artwork: <reason>" and the earlier choice stays. Shared artwork overrides and disables the Book's control; clearing it restores the Book's own. The preview is made in memory and the image file is never written.
- States: "(none)" when blank, "(no preview)" when a stored path cannot be previewed. The Book control has two separate disabling reasons, the Shared override and the build lock.
- Persistence: the image's folder is remembered as `m4b_maker.cover_dir`; the choice itself is not saved.

### Output filename
`ACT.MAKER.OUTPUT-NAMING`

- Purpose: give each M4B a readable, safe and unique name.
- Rule: the first usable of Output Filename, Title, effective Album, the one folder holding every track, then "Book N". The name is made safe by the shared sanitiser and ends in ".m4b" exactly once; a name with no letter or digit left falls through to the next choice. Same names within a run, and files already present, get "-1", "-2" in a fixed order; nothing is overwritten. A path-like name cannot leave the destination, and an output can never be one of the inputs.
- How to reach it: the Book-only "Output Filename" entry, or leave it blank for the automatic name.

### Standard run folder and output hint
`ACT.MAKER.RUN-FOLDER`

- Purpose: keep each Build's M4Bs in their own numbered folder.
- Behaviour: each Build reserves one new folder `<output base>/M4B-Maker-Outputs/M4B-Maker-N` and every Book of that Build lands directly in it. A run folder inside a source folder is refused. Staging uses a hidden `.work` folder inside the run folder that no Book name can take; it is removed when empty. Retry Failed reuses the same folder.
- Output hint: the right end of the import band shows where the run lands; when space is short it shows the end of the path behind "…".
- Failure: if the folder cannot be reserved, Build shows why and starts nothing; if planning then fails, the empty reservation is released.

### Custom destination
`ACT.MAKER.CUSTOM-DESTINATION`

- Purpose: write the M4Bs straight into a chosen folder, for example beside the sources.
- How to reach it: "Choose custom destination" on the options line, then type a path or press Browse… ("Choose the destination folder").
- Behaviour: off on every new panel; the path row appears only while it is on. The folder must exist, be a real (not linked) writable directory given as an absolute path; otherwise a message explains and nothing is reserved. M4Bs go directly into the folder (no M4B-Maker-N inside it), numbered around files already there. Staging happens outside the chosen folder, in an owned entry of the program's temporary work area (`%TEMP%\act-tts\<token>\<n>`, kind `maker`) that is removed once no retry can reach it, and recovered by a later custom build if the program was killed (since v0.7.2 Phase 6; it used to be a loose `act-m4b-build-*` folder nothing owned). While the toggle is off, a path left in the hidden entry is ignored.
- Persistence: neither the toggle nor the path is saved, deliberately.

### Try FAST first (auto-fallback to Safe)
`ACT.MAKER.FAST-FIRST`

- Purpose: build quickly where possible, with an automatic slower path when that fails.
- How to reach it: "Try FAST first (auto-fallback to Safe)" on the options line ("Try FAST first" in the tight layout). On when the panel opens; not saved.
- Behaviour: with no inserted silence, FAST concatenates the source MP3s and encodes AAC 128k. If FAST fails, the Book is rebuilt through Safe (each track normalised to WAV first) and the Detailed log gives FFmpeg's reason. With the option off, Safe runs directly. Inserted silence always means Safe. Both paths keep the chapter marks on the audible boundaries.

### Build M4B(s)
`ACT.MAKER.BUILD`

- Purpose: turn every Book with tracks into one chaptered M4B in a single run.
- How to reach it: Build M4B(s) in section 3, beside the shared job controls.
- Behaviour: with no tracks anywhere it warns "Import a folder or add MP3 files first." Otherwise it checks Silence and Start Part, reserves or checks the destination, freezes one plan of every Book that has tracks (empty Books are skipped), and runs it on one worker thread, Books in workspace order. Anything edited after pressing Build (fields, tracks, artwork, options, destination) does not reach this run or its retries. A divider "Build M4B(s) — <run folder>" opens the run in the log.
- Output: one .m4b per Book: AAC 128k in an MP4 container, with chapters, tags and optional cover.
- States: disabled while running; the run ends Succeeded, Completed with failures, Cancelled or Failed.

### Chapter timing and round trip
`ACT.MAKER.CHAPTERS`

- One chapter per track. Each chapter starts exactly at its track's first sample (there is no lead-in) and the last ends at the end of the audio; every chapter is at least 100 ms.
- FAST starts come from each track's fully decoded length, not its header estimate; Safe starts come from the WAV lengths, silence included.
- Splitting the finished M4B at its marks (as the M4B Converter does) gives back each source track whole. 264 chapters keep their titles and ordered timings. Track paths with an apostrophe build correctly.
- Before publication the staged file must carry exactly the planned chapter titles.

### Embedded tags
`ACT.MAKER.TAGS`

- Title, Artist, Album Artist and Album are written from the frozen effective values. A blank Title falls back to the resolved output name, so no Book is untitled. Characters that mean something to FFmpeg's metadata format (=, ;, #, backslash) come back exactly in tags and chapter titles.
- Series tags are added afterwards (see Series). The Maker writes no Year, Genre or Comment.
- The staged file's Title is checked against the plan before publication.

### Artwork embedded in the M4B
`ACT.MAKER.ARTWORK-EMBED`

- The effective artwork (Shared, else Book) is embedded as exactly one cover after encoding. JPG and PNG keep their exact bytes; HEIC/HEIF becomes a PNG of the same size in memory, with nothing written beside the source. Only the metadata is rewritten; the audio is not re-encoded.
- An image that cannot be read fails its Book before FFmpeg runs, and that failure is not retryable.

### Staged build and atomic publication
`ACT.MAKER.STAGING`

- FFmpeg writes only the Book's private staging file. The staged M4B is checked (audio present, planned chapter titles, Title, cover present exactly when planned) and then moved to its final name in one step; an existing file at that name is never replaced. A work folder on another drive goes through a temporary file beside the destination.
- A failed or cancelled Book leaves no partial M4B under a final name and removes its staging, except that a checked candidate is kept for Retry Failed after a publication or numbering failure. Source MP3s are never changed.
- A kept candidate lives only while a Retry Failed can reach it: a cancelled or failed run keeps nothing, and Clear All Imports, a new Build or closing the tool removes it (ACT72-031, fixed in v0.7.2 Phase 6). If a build is still running when the tool closes, its worker keeps nothing when it ends.
- Crash boundary: a killed program can leave a standard run's `.work/<Book>` in that run folder (private, never published; the output folder is never swept). A custom build's entry is recovered by the next custom build once its owner is provably gone.

### A Book that cannot be built fails alone
`ACT.MAKER.UNREADABLE`

- A track FFmpeg cannot read fails only its own Book; the other Books still build and the run ends Completed with failures. No M4B appears under a final name for the failed Book and its sources are unchanged.
- The failure is one Summary line however many tracks the Book has, with FFmpeg's detail in Detailed. The Book's Status shows Failed.
- Failures of the Book's inputs or build steps are retryable. Unusable artwork, or FFmpeg not being ready on the computer, fails that Book without a retry.

### Book status and run progress
`ACT.MAKER.PROGRESS`

- "Status:" in the Book-only row reads Ready, Queued, Processing, Completed, Failed, Skipped or Not attempted for the current Book, always read from the run. During Retry Failed, Books not being retried show their earlier result.
- The shared progress area shows progress, stage, ETA and a line naming the Book being built as "name.m4b (i of n)". At the end Summary gets one line with completed, failed, skipped and not-attempted counts and the destination.
- The worker never touches the window; its events reach the panel through a queue, and events from another run are rejected.
- While a run works each Book reads Queued, then Processing, then its result; an empty Book reads Skipped; the stage line names the Book being built as "name.m4b (i of n)"; the run ends with one counts line (ACT72-052, v0.7.2 Phase 6).

### Pause and Resume
`ACT.MAKER.PAUSE`

- The shared Pause takes hold at the next checkpoint, between Books or between steps of a Book; nothing more runs while paused. Resume continues the same run.
- An FFmpeg step that is already running finishes first: Pause never stops or suspends it (Cancel does). A paused run does not survive closing the application.

### Cancel a build
`ACT.MAKER.CANCEL`

- The shared Cancel stops a running FFmpeg or ffprobe step within a fraction of a second, through that step's own process handle (an unrelated FFmpeg is untouched), and is otherwise honoured at the next checkpoint, between Books and between steps of a Book. No later step starts. The Book being built publishes nothing and its staging is removed (a candidate kept from an earlier attempt too, if Cancel arrives while it is checked or numbered); Books not reached are Not attempted; Books already published stay. A stopped step is never a failed encode: it does not fall back from FAST to Safe and is not offered to Retry Failed. A cancel that arrives while a Book is being published keeps that Book. In custom mode the chosen folder is never removed. (ACT72-023, fixed in v0.7.2 Phase 6C.)
- Not attempted Books are not offered to Retry Failed; press Build again for a new run. The Book a Cancel stopped part-way reads Cancelled and is counted as stopped by Cancel; Books never reached read Not attempted (both stay NOT_ATTEMPTED; ACT72-004, v0.7.2 Phase 6).
- There is no native Maker cancel journey; Cancel during a running encode is proved on real media through the batch worker.

### Retry Failed
`ACT.MAKER.RETRY`

- Offered only after a run has settled with retryable failed Books; refused while a run is active.
- Re-runs only those Books from the original frozen plan into the same destination, as a new attempt of the same run ("Retry Failed — attempt N" in the log). Edits made since Build are ignored. Books that succeeded are not touched, and the combined result covers the whole run.
- A kept, checked candidate is reused; if it carries a stale tentative Series Part, that is rewritten to the next number before publication.
- Only in the same session; Clear All Imports discards the run.

### Controls locked while a build works
`ACT.MAKER.RUN-LOCK`

- While a build runs, Build, Import Folder, Clear All Imports, Add Files, Move/Remove and their shortcuts, the navigator, all Shared and Book fields, both artwork controls, the run options, the custom destination and the Chapter Titles box are disabled. Everything is released when the run ends, however it ends.
- Series Part and the Book artwork each keep two separate disabling reasons, so releasing one never re-enables a control the other still holds. Clear Log is deliberately never locked.

### Clear All Imports
`ACT.MAKER.CLEAR-IMPORTS`

- Clear All Imports (beside Import Folder, in the destructive style) returns the tool to its startup state: one empty Book, blank Shared, no run, Status Ready, the default output hint.
- It asks "Clear all imports?" only when there is real work (a Book with tracks or settings, or any Shared value); No changes nothing. Nothing on disk is deleted or changed, outputs already written stay, settings are untouched, and the log keeps its history with a divider.
- Disabled while a build runs and refused while a scan runs.

### Activity history and Clear Log
`ACT.MAKER.ACTIVITY-LOG`

- The Activity section has Summary and Detailed tabs, the note "Summary: progress and results. Detailed: every step." and Clear Log. Earlier runs' lines are kept (up to 400 per pane), with a divider for each run, retry and Clear All Imports. Clear Log clears the visible text only and never interferes with a running build.
- Each attempt starts under its own divider ("Build M4B(s) — run folder", "Retry Failed — attempt N"); Clear Log clears the view only, and the run and its outputs stay (ACT72-052, v0.7.2 Phase 6). The panes follow, hold and resume as the shared log view does.

### Panel layout, density and appearance
`ACT.MAKER.LAYOUT`

- Four sections stacked in order: 1. Import & Books, 2. Book Settings, 3. Tracks, Chapters & Build, then Activity. Nothing scrolls the whole tool; the track list, Chapter Titles and log scroll on their own.
- At 920x600 and larger every required control is fully on screen, with or without the custom path row. When the panel is short it switches to a tight layout: less padding, the run separator and Activity note hidden, "Start Part:" and "Try FAST first" shortened, the custom path row moved onto the options line. No usable control is hidden.
- Switching Light/Dark recolours the panel in place without changing any Book, value, selection, option, log line or running build.

### Closing the window during a build
`ACT.MAKER.CLOSE-DURING-BUILD`

- Closing the window always reaches the panel's close: it asks the run to cancel, closes the importer, stops the event pump and closes every component; closing twice is harmless. A closed panel stops following appearance changes.
- Closing the application while a Maker build encodes should end with exit status 0, no window, no leftover owned process and no Tcl crash, and no partial M4B under a final name.
- The cancel that closing asks for now also reaches a running FFmpeg step (ACT72-023, fixed in v0.7.2 Phase 6C); whether the worker stops it before the interpreter ends is not measured, so the launcher's end-of-process sweep of the FFmpeg it started remains the guarantee. Staging under `.work` can be left behind and the shutdown journey accepts that (new gap, Phase 6; read from code, not measured).

### Intentional differences from other tools

- The Maker reads no tags from its source MP3s; imported Books start blank (the MP3 Tool prefills from source tags).
- Silence is a non-negative gap; the MP3 Tool's Time field is signed. Series Name is a Shared field here; Title is never Shared.
- The custom destination writes directly into the chosen folder with no numbered run folder, and may sit beside the sources; the standard mode refuses a run folder inside a source folder.
- Artwork is embedded after encoding as an MP4 cover with mutagen, so HEIC can be converted in memory without re-encoding; MP3 tools use ID3 artwork instead. The artwork control and service are shared with the Metadata Editor.
- Series Part auto-numbering is success-only and decided while the run executes, not at planning.
- The run orchestration lives in a Tk-free module rather than inside the panel (unlike the MP3 Tool).
- Pause and Cancel take effect at checkpoints between Books and between the steps of a Book.

### Not verified here

- Windows display scaling other than 100% (125%, 150%, 200%), and owner approval of the Maker screenshots captured at 920x600, 1024x720 and 1400x900.
- The macOS (aqua) composition and behaviour: the panel has aqua layout hints, but Windows is the acceptance target.
- Very large Books beyond the 264-chapter test, and very long real audiobooks (time and memory).
- Whether a forced close (the process ended before the worker finished) leaves a standard run's `.work` on a real machine; the shutdown journeys accept it, by design of the crash boundary.
- Listening quality of the encoded audio at the fixed AAC 128k.
