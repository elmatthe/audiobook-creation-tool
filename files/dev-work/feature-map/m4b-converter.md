# M4B Converter

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## M4B Converter

The M4B Converter turns M4B audiobooks into MP3s, either one MP3 per book (Whole book) or one MP3 per chapter (Split by chapter). The user imports `.m4b` files or folders, picks the output structure, MP3 quality and metadata mode, optionally turns on track numbering, and presses **Convert M4Bs → MP3s**. The run first reads every source (preflight), freezes one immutable plan for the whole run, then encodes each output with FFmpeg (or, for xHE-AAC books FFmpeg cannot decode, with Windows' own decoder feeding FFmpeg) into a numbered run folder. Pause, Resume, Cancel and Retry Failed come from the shared job controls.

Source: the panel is `scripts/m4b/converter/m4b_converter.py` (`M4BConverterUI`); planning lives in `m4b/converter/m4b_plan.py`, `m4b_destinations.py` and `m4b_metadata.py`; the shared M4B modules are `m4b/m4b_probe.py` (one FFprobe read per source), `m4b_chapters.py` (chapter model, validation, timeline), `m4b_naming.py`, `m4b_commands.py` (FFmpeg argument lists), `m4b_execution.py` (running, stopping and publishing one output), `m4b_continuous.py` (the one-decode split route, v0.7.2 Phase 7B), `m4b_winaudio.py` (Windows Media Foundation decoding) and `m4b_numbering.py` (re-export of the shared success-only numbering). `m4b_staging.py` sits in the same package but is used only by the Maker and the Metadata Editor.

### Converter panel, layout and appearance

`ACT.CONVERTER.LAYOUT`

- **Purpose:** the panel the launcher embeds, plus a standalone `main()` for running the tool on its own.
- **How to reach it:** choose M4B Converter in the launcher.
- **Layout:** four sections: 1. Sources, 2. Conversion & Metadata, 3. Output & Run, and Activity on the right. The arrangement (wide, split or stacked) is chosen from the widgets' measured sizes; there is no whole-panel scrollbar. At the launcher's sizes from 920x600 up, every required control stays on screen and the list and log keep usable heights.
- **Appearance:** Light/Dark switches in place; imports, selections, options, log text and a running job are untouched.
- **Persistence:** only the shared appearance setting.

### Import M4B audiobooks

`ACT.CONVERTER.IMPORT`

- **Purpose:** build the queue of books to convert with the shared importer.
- **How to reach it:** section 1: Add Files…, Add Folder…, Move Up, Move Down, Remove, Clear All; options M4B audiobook, Include subfolders, Include hidden folders, Allow duplicate files; Cancel Import while a scan runs.
- **Inputs:** only `.m4b`. Other extensions are refused by the shared validator, not just hidden by the dialog filter. Add Files keeps the dialog's order; Add Folder recurses by default.
- **Safety prompts:** scanning a whole drive or the home folder asks first (declining starts nothing); a very large result asks before anything is added.
- **States:** the list and options lock while a conversion runs; Cancel Import stays usable and cancels only the scan.
- **Persistence:** the last folder chosen in either dialog (`m4b_converter.input_dir`). The queue is not saved.

### FFmpeg readiness check

`ACT.CONVERTER.FFMPEG-READY`

- **Purpose:** show the FFmpeg state when the tool opens and refuse to start when FFmpeg is not verified.
- **Behaviour:** the shared status line is written to both log panes on opening. Convert requires a *verified* FFmpeg (one this machine has actually run), not merely a found one; otherwise an "FFmpeg is not ready" error appears and no run starts.
- Convert with an FFmpeg pair nobody proved shows "FFmpeg is not ready" and starts no worker, reserves no folder and runs no command (ACT72-051, v0.7.2 Phase 6).

### Whole book: one MP3 per audiobook

`ACT.CONVERTER.WHOLE`

- **Purpose:** one MP3 of the entire book.
- **How to reach it:** section 2, Output structure → Whole book (the default).
- **Output:** `<source stem>.mp3` per usable book, covering the source from 0 to its full duration, encoded in one FFmpeg pass with no seek. The chapter map, chapter titles and cover are kept unless Write none is chosen.
- **States:** the mode is one choice for the whole run, frozen at Start, and locked while running.
- **Failure:** a failed or cancelled book leaves no MP3 under its final name.

### Split by chapter: one MP3 per chapter

`ACT.CONVERTER.SPLIT`

- **Purpose:** one MP3 per chapter so each chapter is a track.
- **How to reach it:** section 2, Output structure → Split by chapter.
- **Output:** a folder per book named for the source file's stem, holding `NN - <chapter title>.mp3` (at least two digits; order restarts at 01 per book). The outputs tile the whole book: audio before the first chapter belongs to chapter 1, any gap belongs to the chapter before it, and the last output ends at the source's end. Each output has its own chapter title and track number and never carries the book's chapter map.
- **Failure:** if any chapter of a book fails or is cancelled, that book's finished chapters are removed so a partial book never looks complete; other books are untouched.
- **Difference:** per-book folders were a maintainer ruling after a flat 12-book split proved unusable; Whole book stays flat.

### Books without chapters

`ACT.CONVERTER.CHAPTERLESS`

- A book that is read correctly and simply has no chapters is a success in both modes.
- In Split by chapter it becomes one file, `<stem>/<stem>.mp3`, with a log note that it had no chapters. It is treated as a whole book, not a fragment: no structural track, no whole-run number.
- A book that could not be read is never treated as "chapterless".

### MP3 VBR quality

`ACT.CONVERTER.QUALITY`

- **How to reach it:** section 2, MP3 quality spinbox ("VBR 0–9, lower is better"); default 2 (about 190 kbps).
- **Output:** every output of the run is encoded with libmp3lame at `-q:a <quality>`, on both decode routes. Never a constant bitrate.
- **Invalid values:** a typed value outside 0–9 is clamped at Start and a non-number becomes 2.
- **Persistence:** not saved; each session starts at 2.
- A typed quality outside 0-9 is held to the nearest end and anything that is not a number becomes 2, as the encoder's own command line shows; it is corrected without a word, unlike the other tools, which refuse (see the consistency matrix; ACT72-051, v0.7.2 Phase 6).

### Metadata mode: Preserve, Replace, Write none

`ACT.CONVERTER.METADATA`

- **How to reach it:** section 2, Metadata → Preserve source / Replace with the values below / Write none, and the Title, Artist, Album Artist and Album fields.
- **Preserve (default):** carries only the source's title, artist, album artist, album and a bare track number; a filled field overrides its own value.
- **Replace:** writes only what was typed; blank fields stay absent.
- **Write none:** no tags, no chapter map, no cover. FFmpeg's own encoder tag always remains.
- **Always:** no other source tag reaches an MP3 (no Audible IDs, MP4 brands, genre, comment, narrator). Split outputs never carry the book's title, only their own chapter title and track. Every tagged output is ID3v2.3, which Windows Explorer reads.
- **Fields:** disabled (never hidden) under Write none and during a run; typed text is kept.
- **Persistence:** not saved; each session starts on Preserve with empty fields.
- The Title field is labelled "Title", like its neighbours: blank keeps the source title under Preserve and writes none under Replace; no filename is substituted (the label promised one until v0.7.2 Phase 6, ACT72-028).

### Chapter markers and titles in whole-book MP3s

`ACT.CONVERTER.CHAPTER-MAP`

- Whole book under Preserve or Replace keeps the source's chapter map with unchanged timing, and writes every chapter title back explicitly (the metadata allowlist would otherwise strip them).
- Write none and all split outputs carry no chapter map.
- An output with a chapter map is ID3v2.3 even when it has no text tags.
- Non-ASCII chapter titles are read and written exactly; an untitled chapter stays untitled.

### Embedded cover art

`ACT.CONVERTER.ARTWORK`

- Follows the metadata mode; there is no separate artwork control.
- The cover is the one stream marked as an attached picture; ordinary video is never treated as artwork. It is copied, never re-encoded.
- Preserve and Replace keep it; Write none drops it. A book with no cover converts normally. A book with more than one cover is refused at preflight in every mode rather than guessing.
- Whole book: the cover rides in the single encode, read from a second opening of the same file (reading it from the same input truncated long books). Split: each chapter is encoded first, then the cover is stream-copied on in a second pass that leaves the audio bit-identical.

### Auto-number tracks

`ACT.CONVERTER.NUMBERING`

- **How to reach it:** section 2, Auto-number tracks and Start #.
- **States:** off by default, Start # 1. Applies only to Whole book; no effect in Split by chapter or under Write none.
- **Behaviour:** each successfully written book takes the next number; a failed, refused or cancelled book consumes nothing, so there are no gaps. A retry continues from where the run got to. Filenames are never numbered.
- **Persistence:** not saved.
- A typed Start # below 1, or one that is not a number, becomes 1 in the frozen run, without a word (ACT72-051, v0.7.2 Phase 6).

### Run output folder and Open Output Folder

`ACT.CONVERTER.OUTPUT-FOLDER`

- **How to reach it:** section 3, the read-only Output field and Open Output Folder. The base folder is set in Preferences & Data.
- **Behaviour:** each run gets `<output base>/M4B-Converter-Outputs/M4B-Converter-N/`, reserved only after preflight finds something usable; a run where every book is refused creates no folder. A run keeps the base it started with even if Preferences change mid-run; the next run uses the new base. A finished or cancelled run reveals its folder in Explorer.
- **Open Output Folder:** reveals the last run's folder, or the tool folder before any run; shows an "Output folder" error if it cannot be created. It never locks.
- Before any run it reveals the tool's own folder, made so the person lands somewhere real; after a run, that run's folder; a folder that cannot be made shows "Output folder" and reveals nothing else (ACT72-051, v0.7.2 Phase 6).

### Output names, book folders and collisions

`ACT.CONVERTER.NAMING`

- Whole: `<stem>.mp3`. Split: `NN - <title>.mp3`; slashes in a title become " - ", a blank title becomes "Chapter N", and the shared sanitiser handles illegal characters, reserved names and length.
- Directly added files land flat in the run folder; a folder import mirrors its sub-folders; several imported roots get separate containers.
- One collision domain per run: same-named books or folders get `-1`, `-2` suffixes, and an existing file is never overwritten. No output can be one of the run's sources.
- Names are frozen at Start; a retry reuses them exactly.

### Start a conversion: preflight and a frozen plan

`ACT.CONVERTER.START`

- **How to reach it:** section 3, Convert M4Bs → MP3s. An empty queue shows "No files".
- **Behaviour:** the queue and every option are read once at Start; changing them afterwards cannot affect the run. Every source is then read on a background thread ("Examining the imported audiobooks…", no progress total yet). Only after that is the run folder reserved and every destination planned, and the progress total becomes the number of planned outputs.
- **States:** inputs and options lock while running and unlock when the run settles (Succeeded, Completed with failures, Failed or Cancelled), even after an unexpected internal error, which is logged as "The run did not complete."
- **Failure:** one book failing never stops the others.

### Exact chapter boundaries (output-side seek, or the same samples from one decode)

`ACT.CONVERTER.PRIMING`

- **Seeking route** (every book the continuous route does not take): each split chapter is cut with `-ss` placed after `-i` and the length given as `-t`. Seeking before `-i` is about a hundred times faster but was measured to drop or fade audio at chapter starts (AAC decoder priming) while still reporting correct durations.
- Boundaries are the chapter starts copied exactly, written to the microsecond; adjacent chapters neither lose nor repeat audio, and chapter 1 starts at the very beginning.
- **Continuous route** (v0.7.2 Phase 7B, eligible books only; see `ACT.CONVERTER.SCALING`): there is no seek. Chapter *k* is exactly the decoded samples the output-side seek selects, from the same `-ss`/`-t` strings: first sample `half_up(S × rate)`, count `half_up(D × rate)`, cut at absolute positions, never by adding up rounded durations. Neighbours whose rounding overlaps or gaps by a sample are reproduced as the seek does (FFmpeg's own seek was checked at exact half-sample ties). Every output is byte-identical to the seeking route's.
- **Cost of the seeking route:** about 1.3–1.6 s of extra decoding per hour of audio before each chapter (Phase 7A); the continuous route removes it where it applies.

### Codec compatibility: FFmpeg AAC and the Windows xHE-AAC decoder

`ACT.CONVERTER.DECODE-COMPAT`

- Ordinary AAC books are decoded by FFmpeg and never take the Windows route. A split AAC-LC book may be decoded by FFmpeg once rather than per chapter (`ACT.CONVERTER.SCALING`); the Windows route and every other codec are not touched by that.
- xHE-AAC books that this FFmpeg cannot decode completely (it silently lost about 24% of a measured book) are decoded by Windows Media Foundation when the machine can: once per book, with split chapters cut from the decoded audio and piped into the same encoder, quality, metadata, chapters and cover. The log notes that Windows decoded it.
- With no capable decoder (for example a Windows N edition without media components) the book is refused at preflight, nothing is created, and it is not retryable.
- A decoder failure fails the output even if FFmpeg exits 0. A wrong-length output names xHE-AAC as the cause only when the plan established it.
- **Known gap:** every automated check of this route uses a simulated decoder; the real Windows decode of an xHE-AAC book is covered by no automated test or journey (Phase 8), so the owner's real-book check is needed.

### Malformed chapter lists are refused

`ACT.CONVERTER.CHAPTER-VALIDATION`

- Chapter starts must be finite, not negative, before the end of the audio and strictly increasing. Otherwise the book is refused at preflight, in either output structure, before any folder exists. Nothing is sorted, clamped or dropped to make a list pass.
- The Summary gives one sentence; Details names the offending chapter. Not retryable in place; a corrected file needs a new run.
- The refusal says only that the chapter list is not usable: Whole book refuses the same file, so no mode is offered (ACT72-026, fixed in v0.7.2 Phase 6).

### Unreadable or corrupt sources

`ACT.CONVERTER.CORRUPT`

- A file FFprobe cannot read, a file with no audio and a file with no usable length are each refused at preflight with their own reason; the rest of the run continues.
- If nothing is usable, nothing is converted and no run folder is created ("Nothing could be converted, so no output folder was created.").
- Refused books count as failures but are not offered for Retry Failed. Sources are never modified.

### Safe output writing: temporary file, length check, rollback

`ACT.CONVERTER.SAFE-PUBLISH`

- Each output is written to a temporary file beside its destination and moved onto its final name only after FFmpeg (and any cover pass) succeeded and the measured length is within 3% of the planned span (spans of a second or less are not judged).
- A failed, cancelled or wrong-length output leaves nothing; an existing file at the planned name is never overwritten (the output fails instead).
- One failed chapter removes that book's already-written chapters; other books are untouched.
- FFmpeg's messages go to a temporary file, and only a bounded tail reaches Details.
- **Difference:** this is the Converter's own publication path; it does not use the Maker/Metadata Editor staging folder.

### Activity transcript and Clear Log

`ACT.CONVERTER.ACTIVITY`

- Summary shows the run's progress and results; Detailed shows the per-file transcript and every FFmpeg command line, which never appear in Summary.
- A failure is named by book and output in Summary (for example "A.m4b: A.mp3 could not be written."), with the exit code and FFmpeg's last lines in Detailed.
- The FFmpeg status line on opening and the run's closing line appear in both panes.
- Clear Log clears the visible text only and never locks. History is capped at 400 lines per pane.
- After a run, Summary shows the run's lines, its end once, then "All done." (ACT72-018, fixed in v0.7.2 Phase 6). Log following is the shared view's (ACT.SHARED.LOG-VIEW).

### Pause and Resume

`ACT.CONVERTER.PAUSE`

- Pause is a request: the status reads "Pause requested." until the run reaches the next boundary (between books while reading sources, between outputs while converting), then "Paused". The FFmpeg encode in progress is never suspended or killed by Pause.
- Resume continues the same run. Cancel works while paused. Pause is offered only while a run is going.
- A paused run does not survive closing the application.

### Cancel a conversion

`ACT.CONVERTER.CANCEL`

- The shared Cancel button. Cancel takes effect at once: a running FFmpeg is asked to stop, killed after 5 seconds if it refuses, and always reaped.
- The interrupted output and the rest of that book are removed; books already finished stay. No further book starts. Cancelling while sources are still being read reserves no folder.
- The run shows Cancelled only after cleanup; books never reached are "not attempted", not failures.
- **Same as:** the M4B Maker and MP3 Tool, which also stop a running FFmpeg step since v0.7.2 Phase 6C (ACT72-023); the Converter keeps its own runner.
- The log says "Cancelling… stopping the file being converted now; its book is taken back, and books already finished are kept." (ACT72-027, fixed in v0.7.2 Phase 6; it used to promise to stop after the current file). (A cancelled or failed split book's empty folder is removed since v0.7.2 Phase 6, ACT72-029.)

### Retry Failed

`ACT.CONVERTER.RETRY`

- Offered only after a run completed with failures that happened while converting. Books refused at preflight are never retryable; they need a new run.
- A retry repeats only the failed books from the original plan, at the original names in the original run folder, whatever has changed in the list, options or Preferences since.
- Results add up across attempts: earlier successes stay, a book that fails again keeps being offered, numbering continues.
- If a retryable book somehow has no plan entry, a "Retry Failed" error asks for a new run and nothing is re-read or re-planned.
- Pause and Cancel work during a retry.

### Closing the Converter while it works

`ACT.CONVERTER.CLOSE-DURING-WORK`

- Closing the window during a run (including a paused run or a retry) behaves like Cancel: the running FFmpeg is stopped and reaped, the worker is waited on for up to 5 seconds, and the importer, job controls and scheduling are shut down.
- The application exits cleanly with no window and no FFmpeg of its own left running. The launcher-wide backstop is `ACT.SHARED.CLOSE-DURING-WORK`.

### Long books and many chapters

`ACT.CONVERTER.SCALING`

- Long split runs must produce every chapter with exact boundaries; the Windows decoder route streams in small chunks and never writes the decoded audio to disk; the ETA is based on measured time per output.
- **The continuous route (v0.7.2 Phase 7B, ACT72-012).** The seeking route decodes everything before each chapter again (1.3–1.6 s per hour of prefix, per chapter: chapters × book length). An eligible split book is instead decoded once by FFmpeg, to its own float samples, and each chapter's samples are cut from that stream and piped into the same per-chapter encoder (`pcm_argv` through `run_argv_streaming`, the Windows route's seams). The cover pass, the measurement and drift guard, staging, refusal and publication are the seeking route's, unchanged; every output is byte-identical.
- **Which books.** Decided once at preflight and frozen into the plan (a retry keeps it): split mode; a chaptered book; FFmpeg's own decoder (not the Windows route, no other decoder); one AAC-LC audio stream in float planar samples; a sample rate LAME takes as it is (8–48 kHz); mono or stereo with that standard layout; time base 1/rate, start 0, priming of one AAC frame by edit list or none; a packet scan (one ffprobe, cancellable, between sources) proving every timestamp is the running sample count and the total is the declared one; an FFmpeg build the route is qualified on (by SHA-256: today gyan.dev 9.0.1 full_build, the portable pin); and enough to gain: the prefix (every chapter's start added up) less twice the book's length, because moving the whole book through a pipe costs about 1.4 decodes per second of book (measured), must reach the calibrated threshold, so a short book, or a long book of a few long chapters, keeps the seeking route. Anything else, or anything that cannot be proven, takes the seeking route, byte for byte.
- **Bounded.** At most a 256 KiB block and one second of already-read audio are held (under 1 MiB); nothing is written to disk; the pipes are the back-pressure.
- **Never a quiet shortfall.** End of stream counts only if the decoder exited 0 with exactly the declared samples. A short feed, a stream ending part-way through a sample, a failed or killed decoder fail the chapter, and the book is taken back as for any failed chapter; Retry Failed starts a fresh decoder. A book whose audio frames are damaged (FFmpeg skips them and still exits 0) therefore fails on this route, where the seeking route had no such check.
- **Cancel** stops the encoder and the decoder and reaps both; Pause waits between outputs as before (the decoder simply waits on its pipe).
- **Measured and qualified:** the m4b-scaling qualification (`files/dev-work/verification-gate/scaling/`) with the frozen budgets T1–T8 and T1b passed on HOME-PC on 2026-11-10 (79 of 79 checks, 207 runs; 6 h/48 chapters 2.16× faster, 1,000 chapters 2.88×, every output identical to the pinned reference); baseline, design and results: `files/plans/ACT-v0.7.2-Phase7A-M4B-Converter-Baseline-and-Design.md` section 13.
- **Ending a run** that has an output folder reveals it through `os.startfile` on the Tk thread (`_pump_queue`, "done"), on both routes; a slow or restarting Explorer holds the window until it answers (36.9 s measured under an Explorer flood in Phase 7B). Pre-existing, left for the owner.

### Intentional differences from other tools

- The Converter writes variable-bitrate MP3 (`-q:a`, user-chosen 0–9), not the TTS tool's constant bitrate.
- It imports only `.m4b`.
- Pause waits for the next output boundary; Cancel interrupts the running FFmpeg, as the Maker and MP3 Tool now also do (ACT72-023).
- Auto-number is off by default and applies only to Whole book; split outputs use chapter order as the track.
- Preserve is an allowlist (title, artist, album artist, album, track); narrator, genre and other true but unsupported fields are dropped on purpose.
- Books refused at preflight are not retried in place; only conversion failures are.
- The run folder appears only after preflight; a run of unreadable books leaves no folder.
- Outputs are published from temporary files in the destination folder, not through the Maker/Metadata Editor staging pattern.

### Not verified here

- Real Windows Media Foundation decoding of a real xHE-AAC book (owner's real-book check; no automated coverage).
- 1000+ chapter and multi-hour split runs, and the continuous route's speed and output identity at scale (the m4b-scaling qualification, run on its own, not by the routine gate; it passed on HOME-PC on 2026-11-10 and must run again for another machine, FFmpeg build or route change).
- The continuous route on any FFmpeg build other than the qualified one (it keeps the seeking route there), on macOS, and on HE-AAC/xHE-AAC books (they keep their existing routes).
- Visual approval of the captured screenshots and display scales other than 100% (owner).
- macOS behaviour, including the aac_at xHE-AAC route (not a qualified platform).
- No native journey yet presses Pause/Resume, Retry Failed, Auto-number tracks or Open Output Folder in the Converter, or converts a chapterless or malformed-chapter book; those rely on automated tests only.

The Maker and Metadata Editor's private staging and whole-Book publication (`ACT.SHARED.M4B-STAGING`) lives in `scripts/m4b/m4b_staging.py`, which the Converter does not use; it is described in `shared-workflows.md`.
