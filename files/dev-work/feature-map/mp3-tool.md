# MP3 Tool

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## MP3 Tool

The MP3 Tool retags and joins MP3 audiobooks, several Books at a time. The user imports a parent folder (one Book per folder that directly holds MP3s) or adds files to the current Book, moves between Books with the navigator, sets Artist / Album Artist / Album, Time, artwork and track titles once for every Book (Shared) or per Book, orders the tracks, and then runs one of two operations over every Book that has tracks: **Write ID3 Tags** (a clean, retagged copy of every track) or **Combine MP3s → One MP3** (one joined MP3 and a timestamp list per Book). Each operation reserves one numbered run folder, freezes everything into a plan before any audio is touched, stages work privately and publishes each Book whole. Source files are only ever read. The shared job bar offers Pause, Resume, Cancel and Retry Failed.

Source: `scripts/mp3/mp3_tool.py` (the panel, `MP3ToolUI`), `scripts/mp3/mp3_workflow.py` (the workspace model: imports, source-tag observation, titles, parsers), `scripts/mp3/mp3_plan.py` (the frozen run plan, naming, staging and publication), `scripts/mp3/mp3_processing.py` (FFmpeg helpers and the Write ID3 and Combine engines) and `scripts/artwork/mp3_artwork.py` (what a chosen image becomes in the tag). The Book navigator, the Shared/Current Book field rows, the import status bar, the job bar and the Summary | Detailed log are shared components used here.

### Import Folder: one Book per folder of MP3s
`ACT.MP3.IMPORT-FOLDER`

- **Purpose:** Turn a parent folder of audiobooks into one Book per folder that directly holds MP3s, each pre-filled from its own files.
- **How to reach it:** Section 1 'Import & Books': Import Folder, then the 'Select a folder of MP3 audiobooks' dialog; Cancel Import in the import status bar while a scan runs.
- **States:** Disabled while a run owns the workspace; a press while a scan is already running does nothing; a whole drive or the home folder asks 'Scan a very broad folder?'; a very large result asks 'Import a large number of MP3s?'.
- **Inputs and outputs:** Input: one folder, scanned through the shared importer with the MP3-only catalog. Output: a new workspace whose Books are numbered from 1, tracks in natural order, plus a Summary line with the file and Book counts.
- **Failure, cancel and retry:** Scan problems are logged line by line; a declined replacement, a declined confirmation or a cancelled scan leaves the existing Books untouched.
- **Persistence:** The chosen folder is remembered as the dialog's starting place (settings key mp3_tool.input_dir); Books and imports are not saved between sessions.
- **Intentional differences:** Folder import replaces the workspace; Add Files appends to the current Book only.
- **What must hold:** A folder scan makes one Book per directory that directly contains MP3s; same-named directories never merge. Import Folder replaces every Book; when any Book holds files or settings the user is asked first, and declining changes nothing. A scan that finds no MP3s is reported in the log, not in a dialog. Cancel Import stops a running scan and leaves the workspace as it was.
- Cancel Import ends a folder scan with the workspace as it was, and the broad-folder and large-result questions are asked in the MP3 Tool's own words; declining either changes nothing (ACT72-054, v0.7.2 Phase 6).

### Add Files to the current Book
`ACT.MP3.ADD-FILES`

- **Purpose:** Build or extend one Book by picking MP3 files directly.
- **How to reach it:** Section 3 'Tracks & Run': Add Files, then the 'Select MP3 files' dialog (MP3 files or All files).
- **States:** Disabled while a run is under way; a press while a folder scan is running does nothing.
- **Inputs and outputs:** Input: one or more files, validated by the shared direct-file importer with the MP3-only catalog. Output: the files appended to the current Book's track list and a Summary line naming the Book.
- **Failure, cancel and retry:** Rejected selections are reported in the log; cancelling the dialog does nothing.
- **Persistence:** The folder of the first chosen file is remembered as the next dialog's starting place (mp3_tool.input_dir).
- **Intentional differences:** Unlike Import Folder this never regroups by parent folder and never replaces Books.
- **What must hold:** Chosen MP3s go into the current Book only, in the order the dialog returned them, whatever their folders. A file already in the current Book is skipped and the Summary says how many were skipped. Adding to a Book that already has tracks never changes its typed or cleared values.
- A file already in the current Book is skipped and counted in the log (ACT72-054, v0.7.2 Phase 6).

### Clear All Imports
`ACT.MP3.CLEAR-IMPORTS`

- **Purpose:** Throw away the current workspace and start again without restarting the program.
- **How to reach it:** Section 1: 'Clear All Imports' (danger-styled) beside Import Folder; confirmation 'Clear all imports?'.
- **States:** Locked during a run; refused while a scan is active.
- **Inputs and outputs:** No input. Resets Books, Shared values, the observation store, Book numbering, the last plan and the last result.
- **Failure, cancel and retry:** Declining the confirmation leaves everything as it was; after a reset Retry Failed is no longer offered for the previous run.
- **Persistence:** Settings are untouched; outputs already written stay on disk.
- **Intentional differences:** Same label and behaviour as the M4B Maker and Metadata Editor reset.
- **What must hold:** Returns the tool to its startup state: one pristine Book, blank Shared values, no run result. A pristine workspace is cleared without asking; any Book work or Shared value asks first, and declining changes nothing. Source files and earlier outputs are never touched, and the log keeps its history with a divider. Refused while a run or a scan is in progress (the button is locked).

### Book navigation, add, duplicate and remove
`ACT.MP3.BOOKS`

- **Purpose:** Work on several audiobooks in one session and move between them.
- **How to reach it:** Section 1 Book navigator: '◀ Previous', 'Next ▶', the Book selector, 'Add Book', 'Duplicate Book', 'Remove Book' (confirmation 'Remove this Book?').
- **States:** The navigator is locked while a run owns the workspace.
- **Inputs and outputs:** No files; changes which Book the settings, track list and Chapter Titles show. The Book number also names an output folder when a Book has neither Album nor a single source folder.
- **Failure, cancel and retry:** Declining the removal confirmation keeps the Book.
- **Persistence:** Books live only for the session.
- **What must hold:** Previous, Next and the selector move between Books by stable id, and each Book shows its own values. Add Book adds a pristine Book; Duplicate Book copies settings but no tracks. Removing a Book with files or edited settings asks first; a pristine Book goes without asking. Book numbers are never reused while the workspace lives; a folder import or removing the last Book restarts at 1. The selector label is 'Book N' plus the effective Album or source folder, elided after 40 characters.

### Shared and per-Book metadata
`ACT.MP3.METADATA`

- **Purpose:** Set Artist, Album Artist and Album once for every Book, or per Book.
- **How to reach it:** Section 2 'Book Settings': the tinted 'Shared — applies to every Book and overrides its own value' row and the 'Current Book' row (Artist / Author, Album Artist / Author, Album).
- **States:** A Book field is disabled while the same Shared field has a value; every field is locked during a run.
- **Inputs and outputs:** Free text, stored raw. Feeds TPE1, TPE2 and TALB on every written track and on the combined file, and the Album names the Book's output folder.
- **Failure, cancel and retry:** No validation of these text fields; a run and its retry use the values frozen when the run started.
- **Persistence:** Session only; nothing is saved to settings.
- **Intentional differences:** Title, Year, Genre, Narrator and Comment are not editable here (Title comes from Chapter Titles).
- **What must hold:** Shared has exactly Artist / Author, Album Artist / Author, Album, Time and Book Artwork; a populated Shared value applies to every Book. A populated Shared value disables the matching Book field without erasing the Book's own value, which returns when Shared is cleared. The value written is Shared, else the Book's own, else blank; it is frozen into the plan when the run starts.

### Pre-fill from source tags and Mixed source markers
`ACT.MP3.SOURCE-PREFILL`

- **Purpose:** Save typing by suggesting Artist, Album Artist and Album from the MP3s' own ID3 tags.
- **How to reach it:** Automatic on Import Folder and on the first Add Files into an empty Book; markers appear under the Current Book fields.
- **States:** Only TIT2, TPE1, TPE2 and TALB are read; an unreadable or untagged file reads as blank and still imports.
- **Inputs and outputs:** Reads tags read-only with mutagen. Writes Book configuration once; source values are never used later as an output fallback.
- **Failure, cancel and retry:** A tag that cannot be read yields blank values, not an import failure.
- **Persistence:** Observations are kept per occurrence for the session and dropped by Clear All Imports.
- **Intentional differences:** M4B Maker is the plan's comparison for correct first-population precedence (plan section 11.3).
- **What must hold:** A Book's first files pre-fill Artist, Album Artist and Album with the normalised majority of their tags (first seen wins a tie); a blank majority writes nothing. Files added to a Book that already has tracks never change its stored values. A field whose sources disagree shows 'Mixed source metadata' ('Mixed' in the tight layout); the marker is never a value. Only a field with no value at all is filled by a Book's first files: a value typed or cleared before that import, a duplicate's carried values and the values an emptied Book kept all survive it, in the panel and in the tags written (ACT72-006, fixed in Phase 5).

### Intentional blank values
`ACT.MP3.BLANK-VALUES`

- **Purpose:** Let the user deliberately write no Artist, Album Artist or Album.
- **How to reach it:** Empty any Shared or Current Book text field.
- **States:** An empty stored value is distinct from a never-filled field.
- **Inputs and outputs:** Blank fields produce no TPE1 / TPE2 / TALB frame; track Titles still fall back to the source title or filename.
- **Failure, cancel and retry:** Not applicable.
- **Persistence:** Session only.
- **What must hold:** Clearing a field stores an empty value; the source value never comes back for it. A blank Artist, Album Artist or Album is absent from the written tag, never inherited from the source file. A blank Album leaves the combined file with no Title and no Album frame; nothing is invented. A value cleared before a Book's first import stays cleared through it, in the panel and in the written tags (ACT72-006, fixed in Phase 5).

### Track list reorder and remove
`ACT.MP3.TRACK-ORDER`

- **Purpose:** Set the play order of a Book and drop unwanted tracks.
- **How to reach it:** Section 3: 'MP3 Tracks (this Book)' list with Move Up, Move Down and Remove Selected; keyboard shortcuts on the focused list.
- **States:** Buttons and shortcuts are locked during a run; nothing happens without a selection.
- **Inputs and outputs:** Order drives track numbers, filenames, Combine order and the timestamp sheet; source files are never touched.
- **Failure, cancel and retry:** Not applicable.
- **Persistence:** Session only.
- **Intentional differences:** Uses the shared ordered-list keyboard contract on the panel's own Listbox.
- **What must hold:** Move Up / Move Down move the selected tracks one step as a block, bounded at the ends; the selection follows. Remove Selected drops only the selected tracks; the Book's settings stay. Default Titles stay attached to their tracks through moves and removals. Ctrl+A, Alt+Up / Alt+Down and Delete / BackSpace work on the list and obey the run lock.

### Chapter Titles (track titles)
`ACT.MP3.CHAPTER-TITLES`

- **Purpose:** Name each track of a Book, one title per line.
- **How to reach it:** Section 3: 'Chapter Titles — one title per line' text box beside the track list.
- **States:** Shows defaults until the first edit, after which the whole box is stored for that Book; reordering tracks reorders the defaults.
- **Inputs and outputs:** Plain text, one title per line. Output: TIT2 per track, the track filename stem, and the labels in combined_time-stamps.txt.
- **Failure, cancel and retry:** Edits after a run starts never reach that run or its retry.
- **Persistence:** Session only.
- **What must hold:** Until edited, the box shows each track's default Title: a usable source TIT2, else the cleaned filename. Usable line n names track n; blank lines are ignored; a short list leaves the remaining defaults; extra lines are ignored. The final Titles become TIT2, the filenames and the Combine timestamp labels. The box locks while a run is in progress like the other Book options (ACT72-014, fixed in v0.7.2 Phase 6); the panel still shows a Book's titles in a locked box.
- **Same as:** the M4B Maker's and Metadata Editor's Chapter Titles boxes, which lock the same way.

### Auto-number tracks and Start #
`ACT.MP3.AUTO-NUMBER`

- **Purpose:** Number a Book's tracks in tags and filenames.
- **How to reach it:** Section 2, Current Book: 'Auto-number tracks' checkbox and 'Start # (blank → 1):' entry.
- **States:** Both are locked during a run; a new Book starts with Auto-number on and Start # blank.
- **Inputs and outputs:** Start # must be a whole number of 1 or more. Output: TRCK '7', '8'… and filenames like '07 Title.mp3'; an existing leading number in a Title is removed so it is never doubled.
- **Failure, cancel and retry:** An invalid Start # refuses the operation (see ACT.MP3.INVALID-VALUES).
- **Persistence:** Session only.
- **What must hold:** Auto-number is on by default per Book; Start # blank means 1. With Auto-number on, each track gets TRCK as a plain integer and one zero-padded filename prefix, at least two digits and wider when the last number needs it. With Auto-number off, there is no TRCK and no prefix. Auto-number and Start # are per-Book only; they have no Shared counterpart.

### Add or remove time at the end of each track
`ACT.MP3.TIME-DELTA`

- **Purpose:** Pad or shorten the end of every track by a fixed number of seconds.
- **How to reach it:** Section 2: 'Add/Remove Time at End of Each Track (seconds)', in the Shared row or the Current Book row.
- **States:** Shared overrides the Book value; locked during a run.
- **Inputs and outputs:** A signed decimal number. Every output track (Write ID3) or every constituent (Combine) is re-encoded with libmp3lame -q:a 2 at 44.1 kHz stereo when the value is non-zero; zero copies the audio stream.
- **Failure, cancel and retry:** Invalid text refuses the operation before anything is reserved (see ACT.MP3.INVALID-VALUES); an excessive trim is a retryable failure on that track.
- **Persistence:** Session only.
- **Intentional differences:** add_silence_to_mp3 and trim_from_end_mp3 are retained re-exported helpers; the engine builds its own commands with _append_silence_args and _trim_args.
- **What must hold:** Blank or zero means no change; a positive number appends that many seconds of silence; a negative number trims that much from the end. The adjustment applies to every track, including the last constituent of a Combine. A trim that would leave less than 0.1 s fails that track before FFmpeg runs and publishes nothing for the Book. Lengths are measured by fully decoding the audio, not from header claims.

### Book Artwork (Shared and per Book)
`ACT.MP3.ARTWORK`

- **Purpose:** Embed a front cover in every output of a Book, or of every Book.
- **How to reach it:** Section 2: 'Book Artwork' with a small preview, Choose… and Clear, once in the Shared row and once in Current Book; 'Select Book Artwork' dialog.
- **States:** The Book control is disabled while Shared artwork is set and during a run; the preview shows '(none)' or '(no preview)' when it cannot be drawn.
- **Inputs and outputs:** Input: an image path. Output: one APIC front cover (type 3) on every written track and on the combined file; the source image is never written and no converted file is saved.
- **Failure, cancel and retry:** 'Book Artwork: …' error dialog on a bad choice; at run time an undecodable image is an item-less Book failure.
- **Persistence:** The path is held for the session only.
- **Layout:** Choose… and Clear each get at least their label's width, so both read whole (ACT72-020, fixed in Phase 5).
- **Intentional differences:** Artwork is a file control owned by this panel, not a shared text field.
- **What must hold:** JPG/JPEG and PNG are always offered; HEIC/HEIF only when the shared capability probe can decode it. A chosen file is decoded first; a refusal shows an error and keeps the previous choice. JPG/PNG are embedded as their own bytes; HEIC/HEIF become an in-memory PNG; the tag gets exactly one front-cover APIC, and no artwork means no APIC. Shared artwork overrides every Book without erasing a Book's own choice. Artwork that no longer decodes at run time fails the Book (not retryable) and publishes nothing.

### Invalid Start # and Time are refused before a run
`ACT.MP3.INVALID-VALUES`

- **Purpose:** Stop a run before it starts when a number the user typed cannot be understood.
- **How to reach it:** Pressing Write ID3 Tags or Combine MP3s → One MP3 with a bad Start # or Time.
- **States:** Checked on every Book, including empty ones.
- **Inputs and outputs:** Error dialog titled 'MP3 Tool': '<operation>: Start # for Book N: …' or '<operation>: Time for Book N: …'.
- **Failure, cancel and retry:** Nothing is reserved, planned or run; the user fixes the value and presses again.
- **Persistence:** Not applicable.
- **What must hold:** Start # must be a whole number of 1 or more (blank means 1); Time must be a finite decimal (blank means 0); NaN, infinity, units, commas and hex are refused. Every Book is checked before anything is reserved; the first bad value shows an error naming the field and the Book, and no run folder is made. The Book named in the error is its stable number, as the navigator shows it, also after a removal.
- **Same as:** the M4B Maker's Silence refusal (both named the Book by its position until v0.7.2 Phase 6, ACT72-036).

### Run Write ID3 Tags or Combine for every Book
`ACT.MP3.WRITE-AND-COMBINE`

- **Purpose:** Process every Book of the workspace in one batch.
- **How to reach it:** Section 3: 'Write ID3 Tags' or 'Combine MP3s → One MP3'; warning 'Import a folder or add MP3 files first.' when nothing is imported.
- **States:** Both buttons, the import controls, the navigator, the track controls and the metadata fields lock while the run is active.
- **Inputs and outputs:** Input: the workspace at the moment of the press. Output: one numbered run folder with one subfolder per processed Book (see ACT.MP3.WRITE-ID3 and ACT.MP3.COMBINE).
- **Failure, cancel and retry:** A failed Book never stops later Books; the batch ends Succeeded, Completed with failures, Cancelled or Failed.
- **Persistence:** The last plan and result live for the session only.
- **Intentional differences:** The two operations share one orchestration and differ only in the engine and the outputs.
- **What must hold:** One press is one operation: it validates, reserves one run folder, freezes one plan for every non-empty Book and runs it on one worker with one controller. Empty Books are skipped; with no Book holding tracks the user is told to import first and nothing is reserved. A second operation is refused while one runs; workspace controls are locked for the run. Edits made after the press never reach the run or its retry. An unexpected worker fault settles the run as Failed, frees the panel and keeps the detail out of the Summary.

### Write ID3 Tags output
`ACT.MP3.WRITE-ID3`

- **Purpose:** Produce retagged copies of every track with clean, consistent ID3 tags.
- **How to reach it:** Section 3: 'Write ID3 Tags'.
- **States:** Needs a proved FFmpeg (see ACT.MP3.FFMPEG-REQUIRED).
- **Inputs and outputs:** Output per Book: '<run>/<Book folder>/<NN Title>.mp3' for every track (no number prefix when Auto-number is off), with an ID3v2.3 tag.
- **Failure, cancel and retry:** A track failure is retryable and names the track; artwork, staging or publication failures are the Book's own and not retryable.
- **Persistence:** None.
- **Intentional differences:** Unlike the M4B Metadata Editor, this never edits files in place.
- **What must hold:** Every track becomes a new clean copy in the Book's output folder; the source file is never written. Each copy carries exactly TIT2, plus TPE1/TPE2/TALB when populated, TRCK when Auto-number is on and one APIC when artwork is set; every other source frame is gone. Each copy is validated (present, non-empty, decoded length, exact frames and artwork) before the Book is published. A Book is published only when every track passed; later Books still run.

### Combine MP3s into one MP3 per Book
`ACT.MP3.COMBINE`

- **Purpose:** Join a Book's tracks into a single MP3 with a timestamp list.
- **How to reach it:** Section 3: 'Combine MP3s → One MP3'.
- **States:** Needs a proved FFmpeg.
- **Inputs and outputs:** Output per Book: '<run>/<Book folder>/<Book folder>.mp3' (libmp3lame -q:a 2) and 'combined_time-stamps.txt' (UTF-8, LF). Intermediates are deleted once the Book is published.
- **Failure, cancel and retry:** A constituent that cannot be prepared is retryable; a concat, tag, timestamp or publication failure is the Book's own and not retryable.
- **Persistence:** None.
- **Intentional differences:** No chapter frames are embedded (unlike M4B Maker); concat_mp3s_fast, normalize_to_wav, make_silence_wav, concat_wavs_to_mp3 and save_error_log are retained re-exported helpers that the engine does not call.
- **What must hold:** Each Book becomes exactly one combined MP3 in track order; Books are never joined with each other. FAST concat is used when all constituents share codec, sample rate and channels; otherwise, or if FAST fails, Safe (WAV normalise then encode) is used and the reason is logged. The combined tag is Title = Album, Album, Artist and Album Artist when populated, the artwork, and no track number or chapter frames. combined_time-stamps.txt lists each final Title at its adjusted start offset with its length. Concat lists quote paths with apostrophes, spaces and non-ASCII characters correctly.

### Run folder reservation and output hint
`ACT.MP3.OUTPUT-RUN`

- **Purpose:** Give every operation its own output folder without overwriting anything.
- **How to reach it:** Section 1 shows the destination hint at the right of the import band; the folder is reserved when Write ID3 Tags or Combine is pressed.
- **States:** The hint follows the shared output-base setting.
- **Inputs and outputs:** Output: '<output base>/MP3-Tool-Outputs/MP3-Tool-N/' holding one folder per Book.
- **Failure, cancel and retry:** A reservation or plan failure shows an 'MP3 Tool' error dialog and starts nothing; a retry reuses the original run folder.
- **Persistence:** The output base is a shared setting; the run number is never persisted.
- **What must hold:** Each operation reserves exactly one numbered run folder under <output base>/MP3-Tool-Outputs (MP3-Tool-N); building the panel creates nothing. A failed run keeps its folder for Retry Failed, and a later run never reuses that number. A run folder inside a source folder is refused. The output hint shows where runs land, eliding from the left so the run folder stays visible. If the run cannot be reserved or the plan is refused, the user sees the error and no empty run folder is left.
- A run folder that cannot be made shows the message and starts nothing; a plan refused after reserving releases the empty folder and says why (ACT72-054, v0.7.2 Phase 6).

### Output folder and file names, collisions
`ACT.MP3.OUTPUT-NAMING`

- **Purpose:** Make predictable, safe names for every output.
- **How to reach it:** Automatic when a run is planned.
- **States:** A Title that sanitises to nothing falls back to the source filename.
- **Inputs and outputs:** Folder and file names inside the reserved run folder, decided once and frozen before any media is touched.
- **Failure, cancel and retry:** A retry publishes under the same frozen names.
- **Persistence:** None.
- **What must hold:** A Book folder is named from the effective Album, else the one folder that holds all its tracks, else 'Book N'; names are sanitised. Repeated names within one run are numbered (Dune, Dune-1, Dune-2), including track filenames and a combined file that matches a track name. Track filenames come from the final Title with one leading number removed and the calculated number added once. No destination is ever a source file or inside a source folder, and publication never overwrites an existing file.

### Private staging and whole-Book publication
`ACT.MP3.STAGING-PUBLISH`

- **Purpose:** Never show a half-made Book in the output folder.
- **How to reach it:** Automatic during every run.
- **States:** '.work' exists only while a Book is unpublished or failed.
- **Inputs and outputs:** '<run>/.work/<Book folder>/' holds staged tracks, WAVs and concat lists; published files are moved, not copied.
- **Failure, cancel and retry:** Publication failure is an item-less Book failure; retained pieces are reused by Retry Failed.
- **Persistence:** Staging is on disk until published or (in practice) until the user deletes it.
- **What must hold:** Processing writes only to the run's private '.work' area; a Book becomes visible only when every planned output is staged. Publication moves files into the Book folder and rolls back on any failure, so a Book is published whole or not at all. Each move itself refuses a name that is taken, so a file another program puts at a planned name after the check is kept byte for byte and the Book fails; the roll-back takes back only files this attempt published that are still the files it moved, and removes the Book folder only if it made it and it is empty (v0.7.2 Phase 9 remote re-review, ACT72-075). A failed Book's good pieces stay in staging for Retry Failed; a published Book's intermediates are removed and an empty work area is deleted. Cleanup never follows a link out of the work area: a link planted in staging, a junction included, is unlinked as a link. Staging lives exactly as long as a Retry Failed can reach it: when a run settles, every Book it cannot retry loses its staging, and Clear All Imports, a new run and closing the tool remove what was kept for a retry (ACT72-019, fixed in v0.7.2 Phase 6).
- **Crash boundary:** if the program is killed, a run's `.work` stays in that run folder (private, never published); nothing sweeps the output folder for it.

### Unreadable or damaged tracks
`ACT.MP3.UNREADABLE`

- **Purpose:** Never publish a false result from a file that is not good audio.
- **How to reach it:** Any run that includes a non-audio or damaged '.mp3'.
- **States:** Measured by a full error-free decode through the pinned FFmpeg.
- **Inputs and outputs:** The failing Book's good pieces stay in private staging for Retry Failed; nothing appears in its output folder.
- **Failure, cancel and retry:** The Summary names the failing file; Retry Failed re-runs only that track once the source is fixed.
- **Persistence:** None.
- **What must hold:** A file that does not fully decode fails with its own name and a retryable failure; its Book publishes nothing. Other Books in the run still complete and publish. A staged output that lost audio or carries the wrong frames is caught by validation and not published. Embedded ID3/Info frames between joined MP3 segments are removed only in a private copy; real damage is never repaired. Source files are byte-identical after the run.

### Book status and progress
`ACT.MP3.RUN-STATUS`

- **Purpose:** Show where a batch is and how each Book ended.
- **How to reach it:** Section 2 Current Book 'Status:' label; the shared progress bar, stage and ETA beside the run buttons.
- **States:** Empty Books show Skipped during a run; a Book added after a run shows Ready.
- **Inputs and outputs:** Display only.
- **Failure, cancel and retry:** After a cancel, unreached Books read Not attempted and the Book stopped part-way reads Cancelled; the closing line counts them apart (ACT72-004, v0.7.2 Phase 6).
- **Persistence:** None.
- **What must hold:** The current Book shows Ready, Queued, Processing, Completed, Failed, Skipped or Not attempted, derived from the run, never stored. One progress bar counts every track plus one finalisation step per Book; the status line reads 'Book X of Y — Track M of N'. A batch with one failed Book among successes ends 'Completed with failures'.

### Pause and resume a run
`ACT.MP3.PAUSE`

- **Purpose:** Hold a long batch without losing progress.
- **How to reach it:** Shared job bar: 'Pause' and 'Resume'.
- **States:** Pause requested, then Paused at a checkpoint; Resume returns to Running.
- **Inputs and outputs:** No outputs of its own.
- **Failure, cancel and retry:** Cancel works while paused.
- **Persistence:** A paused run does not survive closing the program.
- **What must hold:** Pause asks the run to stop at its next checkpoint; 'Paused.' is shown only once the worker has stopped there. While paused, Resume is offered and Pause is not; Resume continues the same run to its end. An FFmpeg step already running is never suspended.

### Cancel a run
`ACT.MP3.CANCEL`

- **Purpose:** Stop a long batch safely.
- **How to reach it:** Shared job bar: 'Cancel'.
- **States:** Shown during a run; the state is Cancel requested until the worker acknowledges it: at once when an FFmpeg or ffprobe step is running (that step is stopped), otherwise at the next checkpoint.
- **Inputs and outputs:** Already published Books stay; nothing is deleted from the output folder. A half-written staged track or combined file of the stopped step is removed, and so is the rest of `.work`: no Retry Failed is offered after a Cancel (ACT72-037, fixed in v0.7.2 Phase 6).
- **Failure, cancel and retry:** A cancelled retry keeps the earlier attempt's results. A stopped step is never recorded as a failed or retryable track.
- **Persistence:** None.
- **Intentional differences:** Like the M4B Maker (and the M4B Converter's own runner), Cancel stops a running FFmpeg step; Pause never does.
- **What must hold:** Cancel stops a running FFmpeg or ffprobe step within a fraction of a second, through that step's own process handle (an unrelated FFmpeg, even one this program started, is untouched), and otherwise stops the run at its next checkpoint (between tracks, stages or Books); no later FFmpeg step and no later Book starts. Books never reached are 'Not attempted' and the batch ends Cancelled; a Book already published stays published. Retry Failed is not offered after a cancelled run. (ACT72-023, fixed in v0.7.2 Phase 6C.)
- **Known gap:** No native (real-window) cancel journey for this tool; Cancel during a running encode is proved on real media through the panel's own worker with real threads.
- A cancelled run keeps no .work folder: nothing can retry it, so its staging goes when it ends (ACT72-037, fixed in v0.7.2 Phase 6).

### Retry Failed
`ACT.MP3.RETRY`

- **Purpose:** Finish a batch after fixing the files that failed.
- **How to reach it:** Shared job bar: 'Retry Failed'.
- **States:** Unavailable during a run, after a cancel, after Clear All Imports or once a newer operation has run.
- **Inputs and outputs:** Same run folder and names as the original attempt; a divider 'Retry Failed — … — attempt N' marks it in the log.
- **Failure, cancel and retry:** A retry that fails again can be retried again; a cancelled retry keeps the prior results.
- **Persistence:** Only within the session that ran the operation.
- **What must hold:** Offered only when the run completed with failures and at least one failed track is retryable. Re-runs only the failed tracks of the failed Books against the original frozen plan and run folder; later workspace edits never reach it. Staged pieces that succeeded are reused, the Book is published whole, and Books that succeeded are not touched. Item-less (Book-level) failures and cancelled runs are not retryable.

### Activity log history and Clear Log
`ACT.MP3.ACTIVITY-LOG`

- **Purpose:** Keep a readable record of what the tool did in this session.
- **How to reach it:** 'Activity' section: Summary | Detailed tabs (shared log view, ACT.SHARED.LOG-VIEW) and 'Clear Log'.
- **States:** Clear Log is never locked.
- **Inputs and outputs:** Up to 400 lines per pane; no ffmpeg_log.txt or extra log file is written by the engine.
- **Failure, cancel and retry:** Follow/hold/resume of the panes is the shared view's (ACT.SHARED.LOG-VIEW).
- **Persistence:** Visible history lasts the session; technical lines also go to the shared session log.
- **Intentional differences:** No Copy button and no level selector (the panes are selectable).
- **What must hold:** Log history survives from run to run; a divider marks each run, each retry and each Clear All Imports, and import lines sit between. Clear Log clears only the visible text; the event history, the session log and the run result are untouched and cleared lines never return. Import problems go to the log, not a dialog; technical detail goes to Detailed and the session log, never the Summary.

### FFmpeg required
`ACT.MP3.FFMPEG-REQUIRED`

- **Purpose:** Tell the user plainly when the audio tools are missing instead of failing obscurely.
- **How to reach it:** Status line under the progress bar when the panel opens.
- **States:** Checked when the panel is built and again at the start of every Book.
- **Inputs and outputs:** No outputs.
- **Failure, cancel and retry:** The fix is to re-run the setup launcher; Retry Failed does not apply to this failure.
- **Persistence:** None.
- **What must hold:** Only a proved, pinned FFmpeg/ffprobe pair counts as available; a merely discovered one does not. Without it the panel shows 'WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.' A run without it fails each Book with an item-less, non-retryable failure and publishes nothing.
- Without a proved FFmpeg the panel opens with the warning, and Write ID3 Tags or Combine fails every Book, offers no Retry Failed and publishes nothing (ACT72-054, v0.7.2 Phase 6).

### Panel layout, density and appearance
`ACT.MP3.LAYOUT`

- **Purpose:** Keep the whole workflow usable at the launcher's smallest supported window.
- **How to reach it:** Opening the MP3 Tool from the launcher; resizing the window; the shared appearance toggle.
- **States:** Regular or tight density, chosen from the panel's real height; aqua themes use their own composition hints.
- **Inputs and outputs:** Presentation only; nothing reaches the plan or the engines.
- **Failure, cancel and retry:** Not applicable.
- **Persistence:** Appearance is a shared setting; density is recomputed every time.
- **Intentional differences:** Dense multi-Book (Family B) layout shared with M4B Maker and the Metadata Editor.
- **What must hold:** Four sections in order (1. Import & Books, 2. Book Settings, 3. Tracks & Run, Activity) with every required control fully on screen at 920x600 and larger, without a whole-panel scrollbar. Below the measured floor the panel switches to the tight density; only the track list, Chapter Titles and log give up height. Primary and job controls never overlap; Tab order follows the sections. A live Light/Dark change recolours in place and keeps every Book, value, selection, log line and running job.

### Closing the tool during work
`ACT.MP3.CLOSE`

- **Purpose:** Let the user close the program mid-run without a hang or crash.
- **How to reach it:** Closing the window or switching away in the launcher.
- **States:** Any state, including a scan or a run in progress.
- **Inputs and outputs:** Already published Books stay; unpublished work stays in '.work' (see ACT.MP3.STAGING-PUBLISH).
- **Failure, cancel and retry:** Stopping FFmpeg children at close is the launcher's shared behaviour (ACT.SHARED.CLOSE-DURING-WORK).
- **Persistence:** Nothing of the workspace is saved.
- **What must hold:** Closing the window asks a running worker to cancel; it stops at its next checkpoint. close() is idempotent, stops the scan poller and the pump, closes every component and leaves no scheduled Tk callback. Destroying the panel always reaches close(). Alt+F4 during a long Combine exits with status 0, no window, no owned process and no Tcl crash.

### Intentional differences from other tools

- Import Folder replaces the whole workspace (with a confirmation when there is work); Add Files only ever appends to the current Book.
- Outputs are always new files in a numbered run folder; the MP3 Tool never edits a source in place (the M4B Metadata Editor does).
- Write ID3 writes a whitelist tag from a clean state (Title, Artist, Album Artist, Album, Track Number, one front cover); every other source frame is dropped on purpose.
- Combine embeds no chapter frames; chapter positions go to `combined_time-stamps.txt` instead (M4B Maker embeds chapters).
- The Shared group has exactly five fields; Auto-number, Start # and Chapter Titles are per Book only.
- Source tags are an editing aid: they pre-fill a Book once and are never used later as an output fallback, except a track's own Title.
- Pause acts only between tracks, stages or Books; Cancel also stops a running FFmpeg step at once, as in M4B Maker.
- The log has no Copy button and no level selector; Clear Log clears only the visible text.

### Not verified here

- Windows display scaling other than 100% and the owner's approval of the captured layout screenshots (owner checks).
- There is no native cancel, pause or retry journey for the MP3 Tool. Cancel and Pause while a long FFmpeg step runs are measured on real media through the panel's worker (ACT72-023), not through a native window.
- Behaviour on a machine with no proved FFmpeg beyond the availability check itself.
- HEIC/HEIF artwork on a machine whose capability probe cannot decode it, and the opposite case, are each exercised only where the test machine happens to fall.
- macOS (aqua) composition: the layout hints exist, but Windows is the acceptance target.
- Very large libraries (hundreds of Books or thousands of tracks) for speed; only planning over 120 tracks is exercised.
- Most MP3 behaviour tests need FFmpeg and are skipped on a copy without it, so a run without the pinned FFmpeg proves little about this tool.
