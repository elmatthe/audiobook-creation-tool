# TTS Audiobook

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## TTS Audiobook (core)

The TTS Audiobook tool turns PDF and TXT files into one MP3 per file. The person builds a single queue (Sources),
chooses a voice, bitrate and worker count (Voice & Audio), and presses Start (Output & Run); progress, failures and the
engines' own output appear in Activity. Each run writes into its own numbered folder under
`TTS-Audiobook-Outputs`. A file added directly is narrated by the Edge chapter engine and lands flat; a file found under
an added folder is narrated by the Edge chunked route and mirrors its folder. Kokoro, Chatterbox and Qwen3 voices use the
same run, queue and output rules, with their own synthesis (described in the tts-engines section). The panel lives in
`scripts/tts/epub2tts_gui.py` (`TtsPanel`, `_RunContext`, `RunPublisher`); the Edge routes in
`scripts/tts/epub2tts_edge/` and `scripts/tts/batch_convert.py`; run safety in `publication.py`, `worker_limits.py`,
`disk_assembly.py`, `ffmpeg_watch.py`, `edge_requests.py` and `edge_failures.py`; naming in `output_names.py`; text in
`pdf_extractor.py` and `scripts/tts/speech/`; the voice list in `voice_registry.py`.

### Import PDF and TXT sources into the one queue
`ACT.TTS.IMPORT`

- **Purpose:** build the one queue a run converts, through the shared importer.
- **How to reach it:** Sources section: Add Files..., Add Folder..., Move Up, Move Down, Remove, Clear All; options
  Include subfolders (on), Include hidden folders (off), Allow duplicate files (off), and the PDF document / Text file
  type boxes; Cancel Import while a folder scan runs.
- **States:** queue editing locks during a run; Cancel Import stays live and only stops a scan.
- **Inputs/outputs:** .pdf and .txt only (EPUB was retired). A very broad folder (a drive or the home folder) is
  confirmed before scanning; a large result is confirmed before it is added.
- **Failure/cancel:** a cancelled dialog, a declined confirmation or a cancelled scan adds nothing. Removing or clearing
  never touches files on disk. Import cancel and conversion cancel never affect each other.
- **Persistence:** the queue is not saved.
- **Difference:** how a file was added (directly or by folder) decides which Edge route narrates it.

### Choose a voice; registered is not the same as available
`ACT.TTS.VOICE`

- **Purpose:** one dropdown for all 28 voices (5 Edge, 9 Kokoro, 6 Chatterbox, 8 Qwen3), with an honest answer about
  whether the chosen one can run on this computer.
- **How to reach it:** Voice dropdown in Voice & Audio. It starts on "Edge Male - Steffan (en-US)".
- **States:** selecting a voice shows its engine line, the one speed or rate control its engine supports (Edge rate,
  Kokoro speed, or none), any notice, and a red status line when it cannot run here. Availability is asked again at
  Start.
- **Inputs/outputs:** a voice's identity is its engine plus voice id; the label is only shown and used in file names.
  A broken voice list refuses to load with a message naming the problem.
- **Failure:** a label that names no registered voice is refused ("Voice not recognised"); a voice that cannot run and
  cannot be installed is refused ("Voice unavailable"). Nothing falls back to another voice or engine.
- **Persistence:** the voice is never saved.

### MP3 bitrate
`ACT.TTS.BITRATE`

- **How to reach it:** MP3 bitrate dropdown: 128k, 192k (default), 320k.
- **Behaviour:** frozen per run and passed to every route (Edge direct, Edge folder, Kokoro, Chatterbox, Qwen3).
- **Persistence:** not saved; each panel build starts at 192k.
- Every voice makes 24 kHz speech (measured on real output of each engine), where an MP3 can be at most 160 kbit/s:
  192k and 320k are written at 160k, and the run's Summary says so at Start; nothing is resampled (ACT72-021,
  fixed in v0.7.2 Phase 6).

### File workers: requested versus effective
`ACT.TTS.WORKERS`

- **Purpose:** convert several Edge files at once where the machine and the service allow.
- **How to reach it:** File workers (requested), 1 to 100, default 2.
- **Behaviour:** one worker owns one whole file. The run uses the smallest of: the request, the number of queued files,
  the engine's limit (Kokoro, Chatterbox and Qwen3: one file at a time), the Edge service ceiling of 32, the number of
  logical processors, and what free memory fits for the queued files' estimated sizes. The Detailed log always says
  "Requested workers: N | Effective workers: M" and, when lower, why.
- **Failure:** a file that cannot be sized is counted as nothing and the log says so; sizing never fails a run.
- **Persistence:** not saved.

### Edge speech rate for folder-imported files
`ACT.TTS.EDGE-RATE`

- **How to reach it:** Edge speech rate field (shown only for Edge voices), with the hint "e.g. +0%, -10%".
- **Behaviour:** frozen per run and sent with every folder-route Edge request; directly added Edge files always use
  Edge's natural pace.
- **Persistence:** reset to the voice's preset (+0%) whenever a voice is selected.
- **Checked at Start (v0.7.2 Phase 5, ACT72-044):** a rate the Edge voices refuse (anything but a sign, a whole number
  and %, for example "10%") is refused with "Edge speech rate" before anything is frozen or reserved, whenever
  folder-imported files would send it; a queue of directly added files never uses it, so it is not judged there.
- Locked during a run, like every other option the run freezes (ACT72-014, fixed in v0.7.2 Phase 6).

### Numbered run folder and Open Output Folder
`ACT.TTS.OUTPUT-FOLDER`

- **How to reach it:** the read-only Output field and Open Output Folder in Output & Run; the base folder is changed in
  Preferences & Data.
- **Behaviour:** opening the panel, importing or switching tools creates nothing. A validated Start reserves exactly one
  numbered folder (TTS-Audiobook-N) for the whole queue and shows it. Open Output Folder shows this run's folder, or the
  tool's parent folder before any run.
- **Failure:** a folder that cannot be made is reported in an "Output folder" message.
- **Persistence:** only the shared output base.

### Skip MP3s already in this run
`ACT.TTS.RESUME`

- **How to reach it:** Skip MP3s already in this run, in Output & Run, ticked by default (labelled "Resume (skip existing MP3s)" until v0.7.2 Phase 6, ACT72-046).
- **Behaviour:** on a first attempt a folder-imported file whose planned MP3 already exists is skipped. It never applies
  to directly added files or to Retry Failed.
- Each first attempt writes into a newly reserved numbered folder, so in the app there is never an earlier output to skip,
  and a new run never continues an earlier one (no cross-run resume, by the owner's decision). The words now say only that
  (ACT72-046, v0.7.2 Phase 6); the command line's --resume is where skipping existing files matters. It locks during a run (ACT72-014, fixed in v0.7.2 Phase 6).

### Start a conversion run
`ACT.TTS.RUN`

- **How to reach it:** Start (the window's default button).
- **Behaviour:** an empty queue warns "Missing input". Otherwise every setting the run uses is frozen at that moment
  (queue, voice identity and label, bitrate, workers, rate, Resume, Overwrite, the voice's pauses, speech preparation);
  changing anything afterwards cannot affect the run. The run folder is reserved only after validation, every output is
  planned, and one worker thread runs the queue.
- **Endings:** Succeeded, Completed with failures, Cancelled or Failed, reported once. One file failing is a retryable
  item failure and the run continues; a broken run is a non-retryable job failure. The panel always returns to idle.
- **Persistence:** nothing is saved; the last result is kept in memory for Retry Failed.

### Ask before downloading the English sentence data
`ACT.TTS.SENTENCE-DATA`

- **Purpose:** the Edge chapter engine splits sentences with NLTK's English data, kept in
  `files/runtime-data/nltk_data`.
- **When it appears:** Start with a directly added file and an Edge voice while the data is missing or damaged.
  Folder-only Edge runs and local engines never need it.
- **Behaviour:** a question names the size, source and folder. No starts nothing and says so; Yes downloads it in a
  small window with a Cancel button, then starts that same run. A failed or cancelled download starts nothing.
- **Wording:** the not-started messages say "Press Start again", naming the button the person sees (ACT72-045,
  fixed in Phase 5).

### Install a missing voice and continue the same run
`ACT.TTS.INSTALL-AND-CONTINUE`

- **When it appears:** Start with a Kokoro, Chatterbox or Qwen3 voice whose files are not installed (but could be).
- **Behaviour:** the run is frozen first; the modal "Install & Continue" window lists exactly what will be downloaded,
  and only its Install Selected Components button installs anything. After a successful install the voice is checked
  again and the same run starts once. Nothing is reserved before that.
- **Failure/cancel:** Skip, Cancel, a failed install, closing the window, closing the panel, or a source file changed or
  removed during the install all leave nothing created and say "Conversion not started" where the panel is still open.
  A second Start while the window is open does nothing.
- **Wording:** "Press Start again", like every message that asks for another try (ACT72-045, fixed in Phase 5).

### Narrate a directly added file with the Edge chapter engine
`ACT.TTS.DIRECT`

- **Purpose:** the rich Edge route for a file the person pointed at.
- **Behaviour:** a TXT's `Title:` and `Author:` lines are metadata; `#` lines start chapters; a heading is spoken only
  when it holds speakable text, and two headings in a row are spoken as one title; a UTF-8 BOM is ignored. A PDF's text
  is extracted and, without a `#` heading, its first line becomes the chapter title. Each sentence is requested in
  order; the voice's approved pauses separate sentences, paragraphs, titles and chapters; commas, ellipses and dashes get
  short pauses; Edge padding is trimmed; nothing follows the last word. Several direct files can convert at once, each
  in its own working folder.
- **Output:** `<run folder>/<stem>-<voice label>.mp3`, flat.
- **Difference:** ignores the Edge speech rate.

### Narrate folder-imported files with the Edge chunked route
`ACT.TTS.FOLDER`

- **Behaviour:** text is split into chunks of about 3000 characters at sentence ends; each chunk is one request at the
  frozen rate, 0.8 s apart; chunks are joined with 50 ms between them into one MP3. `Title:` and `#` lines are spoken
  as written on this route.
- **Output:** mirrors the file's folder inside the run folder; several imported roots each get their own container.
  Scratch chunks live in `.tmp_chunks` inside the run folder and are removed when the file ends.

### Local-engine files in the shared run
`ACT.TTS.LOCAL-ROUTE`

- **Behaviour:** a Kokoro, Chatterbox or Qwen3 run is the same run as an Edge one; only the synthesis call differs. A
  PDF goes through the same extractor; a destination that could not be published is refused before any model loads;
  the engine writes to a private scratch file that is then published. One file at a time.
- **Note:** the engines themselves, their installs and their real synthesis belong to the tts-engines features.

### Edge online speech requests, retries and failure advice
`ACT.TTS.ENGINE.EDGE`

- **Purpose:** Edge Read Aloud is Microsoft's unofficial online service; this decides which failures are worth another
  attempt and what to tell the person.
- **Retries:** only network or temporary trouble (and failures not understood) is retried. Direct route: up to 3
  attempts per clip with growing, randomly spread waits (1-3 s, then 2-6 s). Folder route: up to 5 attempts per chunk
  (2, 4, 8, 16 s) and 2 more whole-file attempts after 5 s. A refused connection (HTTP 401/403), a changed service or a
  local file problem is not retried.
- **Advice:** a final failure puts one plain line in the item's failure message (for example check the connection and
  use Retry Failed, or that Microsoft refused and an offline voice is an option); the technical detail, with handshake
  tokens and book text removed, goes to Detailed. edge-tts is pinned at 7.3.1 and a drifted install is named.

### Extract and clean PDF text
`ACT.TTS.PDF-TEXT`

- **Behaviour:** PyMuPDF text with page numbers at a page's edge removed, words broken by hyphens rejoined (across lines
  and across pages), wrapped lines joined, remaining number-only and short all-caps lines dropped, and paragraphs merged
  across page breaks. Only one PDF is read at a time in the process. Every
  route uses this one extractor.
- **Page numbers (v0.7.2 Phase 8, ACT72-063):** a number printed as the first or last line of a page is removed before the
  page's lines are joined, so it is no longer read out in the middle of a sentence that runs on to the next page, and a
  word hyphenated at the foot of a page is joined to its other half.
- **Checked against expected narration (ACT72-057):** real PDFs built line by line, each checked before the cleaner sees
  it, are held to text written out by hand: hyphen joins, wrapped lines, page numbers, short running heads, paragraphs,
  and what must not be joined or deleted.
- **Known limits (ACT72-064, open):** a running head longer than four capitals (a title on every page) is narrated at
  each page; a line that is only a one-to-four-letter all-caps word is dropped; a compound word broken at its own hyphen
  loses the hyphen; a bare number that ends a page is taken for its page number.

### A source with nothing to read fails cleanly
`ACT.TTS.NO-TEXT`

- **Behaviour:** a PDF with no text layer fails with "No readable text found in PDF. File may be scanned/image-based.";
  an empty, header-only, heading-only or punctuation-only TXT fails before any request; a narration that comes out
  silent is refused. Nothing is published and the source is not changed.

### Speech preparation
`ACT.TTS.SPEECH-PREP`

- **Purpose:** rewrite numbers, years, dates, times, currency, units, Roman numerals and symbols into words, and apply
  the owner's pronunciation glossary, before synthesis.
- **How to reach it:** no panel control. The `tts.speech_prep` configuration key (`off` or `v1`, default `v1`); optional
  `glossary.user.json` and `modes.user.json` in `files/runtime-data/speech`.
- **Behaviour:** read and validated once at Start and kept with the run, so edits during a run or before Retry Failed do
  not reach it. Each engine expands only the classes its table cells allow (set from the owner's G1 listening verdicts);
  protected spans and `Title:`/`Author:`/`#` markers are never changed. Every rewrite is proved to rebuild the source;
  if a proof fails, that file is spoken unchanged and Detailed says so. A broken user file adds one note and nothing
  else. Detailed shows edit counts, tokens left unchanged and examples with line numbers.

### A narration ends with its last sound
`ACT.TTS.FINAL-TAIL`

- **Behaviour:** only the trailing near-silence is shortened, to about 300 ms after the last clearly audible sound,
  keeping at least 150 ms and any quieter decay or breath. Nothing is added at the end. Quiet sound past the budget is
  kept and the log says "please listen to the ending"; a recording that stops while still sounding is flagged, not cut.

### Output names
`ACT.TTS.OUTPUT-NAMES`

- **Behaviour:** every route names its file `<source stem>-<voice label>.mp3` using the label frozen at Start, so a
  later rename of a voice cannot move a run or its retry. Stem and label are cleaned separately; Windows device names
  are guarded. If the path would be too long only the stem is shortened; a label or folder that cannot fit is refused at
  Start ("Output folder") before any synthesis. Clashes, including deliberate duplicates and same-stem PDF/TXT pairs, get
  `-1`, `-2` numbering.

### Publish each MP3 whole, and Overwrite only when asked
`ACT.TTS.PUBLICATION`

- **How to reach it:** automatic; Overwrite existing outputs without asking (off by default, frozen per run).
- **Behaviour:** an MP3 is finished and checked, copied to a private staging file beside its destination, flushed, then
  given its final name in one operation. With Overwrite off an existing file is never replaced, even one that appears
  while the file is being made, and a doomed file is refused before synthesis. With Overwrite on the old file stays
  valid until the new one replaces it. Empty, silent, over-24-hour, non-MP3, cut-short or wrong-length results are
  refused.
- **Failure:** a failed attempt removes only its own staging file. A destination held by another program is waited on
  briefly, then reported.
- **Note:** because each run gets a fresh folder, Overwrite matters only when a file appears at a planned name during a
  run or before Retry Failed.

### Memory-safe assembly and supervised FFmpeg
`ACT.TTS.LOW-MEMORY`

- **Purpose:** let long books and several workers finish on machines with little free memory.
- **Behaviour:** while synthesising, a file keeps at most about 16 MB of audio in memory. Before a whole narration is
  joined, a gate compares its real size with what is free: join in memory, wait for other files, or join on disk (the
  same MP3, byte for byte). If memory runs out anyway, the same audio is joined on disk without asking the service
  again; if even that fails, the file fails with a reason that names memory and suggests Retry Failed. Every FFmpeg is
  supervised: it cannot deadlock, and one that makes no progress for 300 s is stopped with a reason.

### Activity log, progress and estimate
`ACT.TTS.ACTIVITY-LOG`

- **How to reach it:** Activity: Summary and Detailed tabs, Clear Log; progress, stage and estimate beside Start.
- **Behaviour:** Summary shows state, progress, failures and the ending; Detailed adds each step and the engines'
  output, one whole line at a time, prefixed with the file name. Clear Log empties the visible panes only. Each run or
  retry adds a divider; history is capped at 400 lines.
- **Following:** each pane follows new lines at the bottom and holds a reader who scrolled up (the shared view,
  ACT72-005, fixed in Phase 5).

### Controls lock while a run is active
`ACT.TTS.LOCK-DURING-RUN`

- **Behaviour:** Start, File workers, Overwrite, Resume, Edge speech rate, Kokoro speed, Install / repair Qwen3 voices,
  the bitrate and voice dropdowns and the queue editing lock during a run, and keep their values; Open Output Folder,
  Clear Log and Cancel Import do not (Resume, rate and speed were added in v0.7.2 Phase 6, ACT72-014).

### Pause and resume between source files
`ACT.TTS.PAUSE`

- **How to reach it:** Pause and Resume beside Start.
- **Behaviour:** files already converting finish; the run shows Paused once the workers stop at the next file boundary;
  nothing new starts until Resume. Pause never interrupts a chapter, chunk, request or PDF extraction.

### Pause and Resume clicked for real
`ACT.TTS.PAUSE.NATIVE`

- The same contract shown with real clicks on Windows: one worker, two files, the active file finishes, Resume completes
  the queue.

### Cancel a running conversion
`ACT.TTS.CANCEL`

- **How to reach it:** Cancel beside Start.
- **Behaviour:** a request to stop. The panel writes "Cancelling..." and wakes everything that is waiting; the run shows
  Cancelled only after the work has really stopped and cleaned up. Files already published stay; nothing unfinished is
  saved. A started file is logged as stopped, a not-started one as skipped; Retry Failed offers neither. The run's
  closing line counts the files finished, stopped and not started (ACT72-004, v0.7.2 Phase 6).

### Cancel clicked for real with requests in flight
`ACT.TTS.CANCEL.NATIVE`

- The same contract shown with a real click while Edge requests are in flight: the run stops within its budget, makes
  no further request, publishes nothing.

### Cancel ends an Edge request and its waits
`ACT.TTS.CANCEL.EDGE-REQUEST`

- A request in flight is abandoned within a bounded time, its partial clip removed; no back-off or pause between chunks
  is sat out; a request that will not stop is dropped and the log says so.

### Cancel ends a wait at the memory gate
`ACT.TTS.CANCEL.MEMORY-WAIT`

- A file waiting for memory stops waiting at once, even with its narration finished, and nothing is joined or saved.

### Cancel kills the run's FFmpeg within one look
`ACT.TTS.CANCEL.FFMPEG`

- Any FFmpeg the conversion started is killed within about a quarter of a second of Cancel, even while it is making
  progress.

### Cancel and the final rename are ordered
`ACT.TTS.CANCEL.PUBLICATION`

- Cancel and a file's final rename are decided on one lock: if Cancel comes first nothing is published; if the rename
  comes first the file finishes whole and stays, and the run is not reported cancelled until it has. Cancel never waits
  for the disk.

### Retry Failed
`ACT.TTS.RETRY`

- **How to reach it:** Retry Failed, after a run ends with failures.
- **Behaviour:** re-runs only the failed files, with the original run's frozen settings and voice, into the original run
  folder at their original names. A finished file is never overwritten and nothing is re-planned. Changes made to the
  panel since the run are ignored.
- **States:** offered only when there is a retryable failure and no run is active; a job-level failure and cancelled
  files are not offered.

### Working files and leftovers
`ACT.TTS.CLEANUP`

- **Behaviour:** each conversion's temporary folders and files (the Edge engine's folder, the panel's direct and
  local-engine folders, pydub's temporaries and the local engines' encode WAV) are entries of one process's workspace in
  the TTS work area, `%TEMP%\act-tts\<token>\<n>`, listed in a manifest that names the owner by process id and creation
  time before each folder exists. Each entry is removed when its file ends, however it ends; one another program still
  holds is removed at a later start. The folder route's chunks stay in `.tmp_chunks` beside the run.
- **Recovery after a killed program:** at the start of each run, a workspace whose manifest is intact and whose owner
  is provably gone is removed and counted in Detailed. A running owner's work, an unverifiable owner, a damaged or
  foreign manifest, a name the tool does not make, links and files in use are left as they are, and all but a running
  owner are named. Nothing outside the work area is looked at, so loose `epub2tts_*` folders from before v0.7.2 stay
  until the person removes them. Removal never follows a link. It stops at 5 s or at Cancel and finishes at a later
  start. Staging files and chunk folders under the output tree left by a program that is gone and untouched for an hour
  are removed as before.

### Closing the panel or window during work
`ACT.TTS.CLOSE`

- **Behaviour:** closing stops reporting, cancels the run (waking a paused one), waits up to 5 s for it, and closes the
  importer and the scheduler. Alt+F4 during narration should exit cleanly with no leftover process.
- A late garbage collection on a worker no longer touches Tk objects: the launcher finishes them on the main thread once
  the window has gone, and the forced-shutdown case exits at once (about 23 s before; ACT72-017, fixed in v0.7.2 Phase 6).

### Responsive layout and appearance
`ACT.TTS.LAYOUT`

- **Behaviour:** wide windows put Sources, Voice & Audio and Output & Run in a left column and Activity on the right;
  the launcher's 920x600 and 1024x720 sizes split the workflow with Activity still on the right; only a smaller panel
  stacks Activity beneath. Only the queue list and the log scroll. Light and Dark repaint without moving any state.
- **Optional voices at the minimum:** every Kokoro, Chatterbox and Qwen3 state, installed or not, keeps Start and
  Cancel on screen at 920x600: a Kokoro voice shows one message at a time (ACT72-007, fixed in Phase 5).
- **Qwen3 disclosure at the minimum (v0.7.2 Phase 6, ACT72-058, owner-approved):** the hardware and speed disclosure
  is shown in full wherever it fits, which is 1024x720 and larger. Only where the split arrangement cannot fit it (the
  920x600 minimum) does the notice line step aside for a **Hardware and speed...** button on the Install / repair row,
  after it in Tab order, which shows the complete text. The model's own state line and Install / repair stay, the
  queue and the log keep their floors, and resizing or Light/Dark moves between the two presentations.

### Standalone command-line converters (developer only)
`ACT.TTS.CLI`

- **Purpose:** the original `batch_convert` folder converter and the upstream `epub2tts-edge` command line, kept on the
  app's publication contract. Not reachable from the shipped app without a terminal.
- **Behaviour:** `batch_convert` mirrors subfolders, never overwrites an earlier output (it numbers instead) unless
  `--resume` skips it, needs `--label` for an unregistered speaker, and writes failures to `batch_errors.log`.
  `epub2tts-edge` can also make an M4B with chapters and a cover.
- **Interrupting the M4B step (v0.7.2 Phase 6E, ACT72-010, fixed):** both FFmpeg steps of `--format m4b` (the concat
  into FLAC-in-MP4, then the AAC encode with the chapters) run through the shared supervisor
  (`subprocess_utils.run_supervised`). Ctrl+C stops the running step's own FFmpeg at once (any other FFmpeg is
  untouched; further presses cannot cut the stopping short), starts no further step, publishes nothing and ends with
  one line and exit status 130. Each step also has a deadline, the book's playing time (read from the parts' headers)
  plus ten minutes, past which it is stopped the same way and the command line exits 124; both steps measured at
  hundreds of times the playing rate. A failed step still raises (exit 1). However a run ends early, what the output
  folder held and the sources are unchanged and the run's work folder is removed. A Ctrl+C anywhere else in the
  command line ends it the same way (130, one line); how soon it lands during narration is unchanged and not measured.

### Intentional differences from other tools

- The way a file was added (directly or through a folder) chooses the Edge route, not only the output layout.
- Several files can convert at once (Edge only); the other tools work through their queue one item at a time.
- Cancel stops work inside a file (requests, memory waits and FFmpeg); since v0.7.2 Phase 6C the MP3 Tool and M4B
  Maker also stop a running FFmpeg step (ACT72-023), each through its own supervisor.
- Pause acts only between source files.
- Output names follow `<stem>-<voice label>.mp3`, a TTS-only policy; the output location has no per-run browse
  control.
- The bitrate is a constant MP3 bitrate choice; the M4B Converter uses a VBR quality setting instead.
- Speech preparation and the voice registry exist only here.

### Not verified here

- Real online Edge synthesis, service behaviour and real low-memory runs: only the edge-low-memory qualification talks
  to the real service; routine journeys replay recorded MP3 frames.
- Narration quality (pauses, chapter titles, endings, spoken numbers and glossary words): owner listening.
- Real local-engine synthesis and real component installs through Install & Continue: the optional-engines
  qualification and the tts-engines features.
- The real sentence-data download over the network (the suite closes the network door): fresh-Windows qualification.
- Visual approval of the panel at each size, and Windows display scaling above 100%: owner checks.
- Whether a 24 kHz Edge narration asked for 192k or 320k really comes out at 160 kbps: not measured.
- macOS behaviour of this panel.

## TTS Audiobook: local speech engines and their setup

The TTS Audiobook tool can narrate with three optional local engines besides the online Edge voices: **Kokoro** (nine voices, in the app's own Python environment), **Chatterbox Turbo** (six cloned voices, also in-process) and **Qwen3-TTS** (two preset voices and six cloned voices, in a separate engine environment, one worker process per file). None of them is installed by default. Their models are acquired only through a consented setup: **Install & Continue** in the TTS panel, the **first-run setup** (setup group), or for Qwen3 also the **Install / repair Qwen3 voices** dialog. Once installed they run offline.

The engines live in `scripts/tts/kokoro_synth.py`, `chatterbox_synth.py` and `qwen3_synth.py` / `qwen3_worker.py` / `qwen3_process.py` / `qwen3_runtime.py`. The setup path is `optional_setup.py` (planner), `optional_setup_acquire.py` (acquirer), `optional_setup_lifecycle.py` and `optional_setup_worker.py` (the setup worker), `optional_setup_health.py` (probes), `model_assets.py` (pinned identities) and, for Qwen3, `qwen3_setup.py`, `qwen3_wheels.py`, `qwen3_package_manifest.py` and `qwen3_install_ui.py`. `voice_install.py` tells the panel whether a voice is installed. The v3 modules (`optional_setup_authority.py`, the `*_v3.py` workers, `qwen3_engine_authority.py`, `qwen3_packages.py`, `spacy_consumer.py`) and the sample harness (`generate_voice_samples.py`, `quality_corpus.py`) are not reachable by users. The TTS panel itself, the Edge engine and the general run workflow belong to tts-core.

### Kokoro local narration
`ACT.TTS.ENGINE.KOKORO`

- **Purpose:** narrates TXT and PDF sources with the Kokoro-82M model on this computer, offline, once installed.
- **How to reach it:** choose a Kokoro voice, optionally set **Kokoro speed** (0.5 to 2.0, 1.0 = normal), press Start.
- **States:** usable only when the model, the voice's `.pt` file and spaCy's English model are present and verified; otherwise the panel offers Install & Continue. Runs on CUDA when available, otherwise the CPU.
- **Inputs and outputs:** text is split into chunks of up to 3000 characters at sentence ends; chunks are rendered in order with a pause (50 ms by default) between them and nothing after the last; the result is encoded once as a 24 kHz MP3.
- **Failure, cancel, retry:** a missing or wrong model file is refused and named. A stack that will not load gives a message pointing to Setup_and_Run or Preferences & Data > Repair App Environment. The first load in a process is retried once after 2 seconds because Windows Application Control may still be checking new DLLs. Cancel is honoured between chunks and just before the encode, and nothing is written.
- **Persistence:** the loaded pipeline is cached per language for the life of the process.
- **Differences:** the only engine with a speed control.
- A speed typed outside 0.5 to 2.0, or not a finite number, is refused at Start with "Kokoro speed" before anything is frozen or reserved (ACT72-047, fixed in v0.7.2 Phase 6). The bitrate ceiling is described under the bitrate (ACT72-021).

### Chatterbox Turbo cloned-voice narration
`ACT.TTS.ENGINE.CHATTERBOX`

- **Purpose:** narrates in one of six locally cloned voices, conditioned on recordings that ship with the app.
- **How to reach it:** choose a "Chatterbox - ..." voice and press Start.
- **States:** usable when the package resolves, the pinned Turbo model files are verified and the voice's recording matches its checksum.
- **Inputs and outputs:** Chatterbox's own splitter makes the chunks and refuses any plan that loses, repeats or reorders text. Prose colons get a short pause. Chunks are separated by the chunk pause, nothing is added at the end, and the result is encoded once. The device is chosen at runtime: CUDA, then Apple MPS, then CPU.
- **Failure, cancel, retry:** a chunk with an unnatural silence inside it is drawn again a limited number of times, then the file fails rather than publish it. Other generation failures are not retried. Cancel is checked between chunks and leaves no output.
- **Persistence:** the model is cached per device. Voice conditioning data is cached under `files/runtime-data` (see the cloned-voice references feature).
- **Differences:** no speed or rate control; no loudness normalisation; the engine's watermark is left in place.

### Qwen3-TTS preset and cloned-voice narration
`ACT.TTS.ENGINE.QWEN3`

- **Purpose:** narrates with Qwen3-TTS: Aiden and Ryan (CustomVoice model) and six cloned voices (Base model).
- **How to reach it:** choose a "Qwen3 - ..." voice. The panel shows where it will run (GPU or CPU) and how fast to expect it, and an **Install / repair Qwen3 voices...** button; at the 920x600 minimum that disclosure sits behind a **Hardware and speed...** button beside it (see the TTS layout). Press Start.
- **States:** Windows only. Ready when the engine environment and the voice's model are installed, and for a clone when its recording and approved transcript check out. Elsewhere the voices say they are not yet available.
- **Inputs and outputs:** each file gets its own worker process in the engine environment. Chunks are whole sentences that never cross a paragraph, and each carries a stable seed. Chunk audio is read back in plan order, checked, joined with pauses between chunks only, encoded once with the app's FFmpeg, and moved into place in one step. The job folder under `files/runtime-data/qwen3/jobs` holds the user's text and is removed after every run.
- **Failure, cancel, retry:** a failure names its stage (loading, generating, out of memory) and leaves any existing output untouched. A damaged engine points to Check and repair. A chunk that runs away is rendered again with the next seed.
- **Differences:** the only engine that runs in a separate process and a separate Python environment.

### Qwen3 worker supervision, cancel and containment
`ACT.TTS.ENGINE.QWEN3-WORKER-CONTROL`

- **Purpose:** makes sure a Qwen3 conversion can always be stopped, including the real interpreter that the engine's `python.exe` launcher starts.
- **How it works:** the worker starts suspended inside a Windows Job Object that kills every member when closed. If it cannot be contained, it never runs and the user is told why.
- **Cancel:** sets a flag the worker checks before loading and before each chunk. A worker that ignores it is killed, with its children, after a grace period.
- **Failure:** a worker that stalls, ends without exactly one result, or reports success and then crashes or hangs is a failed file. Only protocol events count as signs of life, so a flood of library output cannot delay a cancel.
- **Differences:** Kokoro and Chatterbox stop only between chunks. Qwen3 can be stopped in the middle of a chunk.

### Qwen3 one-operation-at-a-time locks
`ACT.TTS.ENGINE.QWEN3-EXCLUSIVE`

- **Purpose:** stops two multi-gigabyte Qwen3 model loads at once on one computer, and stops an install or repair from changing files that a conversion is reading.
- **How it works:** a conversion holds this copy's `inference.lock` and a machine-wide named mutex for its whole run. An install or repair holds `setup.lock` and `inference.lock`. A running worker holds `engine.lock`, so a repair of the app's environment refuses while it runs. All lock files live in `files/runtime-data/qwen3`.
- **States and failures:** a lock is either free or held. A refusal is immediate and comes with a sentence such as "being installed or repaired", "being used by a conversion right now", or the machine-busy or permission-denied message, and nothing is started. The operating system releases every lock if its holder crashes.
- **Differences:** Kokoro and Chatterbox have no lock shared across copies of the app.

### Local engines convert one file at a time
`ACT.TTS.ENGINE.LOCAL-ONE-WORKER`

- **Purpose:** keeps the local engines safe and within memory. Their cached model objects cannot be shared, and a second Qwen3 file would double several gigabytes of GPU or RAM use.
- **Behaviour:** whatever the Workers box asks (up to 100), a Kokoro, Chatterbox or Qwen3 run converts exactly one file at a time. The run log says "Worker limit: <engine> converts one file at a time."
- **Differences:** Edge runs many files at once, limited by its service ceiling, the processor count and memory.

### Local engines never download at narration time
`ACT.TTS.ENGINE.OFFLINE-USE`

- **Purpose:** choosing a voice and pressing Start never downloads anything.
- **Behaviour:** Kokoro and Chatterbox load only the pinned, verified local files. If one is missing, the wrong size or the wrong checksum, the run is refused and told "Nothing was downloaded" rather than letting the library fetch it. A Kokoro voice with no pinned file is refused. A missing spaCy English model is refused before Kokoro's pronunciation library could install one itself. Chatterbox loads from the pinned commit's folder only. The Qwen3 worker runs with the model hub offline and every cache inside the app folder.
- **Recovery:** Install & Continue or the first-run setup.

### Installed or missing: local voice availability
`ACT.TTS.VOICE-STATE`

- **Purpose:** before a run starts, tells the panel whether the selected local voice can run here and, if not, whether installing would fix it.
- **How to reach it:** asked when a voice is selected and again at Start. The answer appears as the voice status line.
- **States:**
  - ready;
  - not installed, which can be fixed by installing one of four components: Kokoro, Chatterbox, Qwen3 CustomVoice or Qwen3 Base;
  - damaged or partly installed;
  - unavailable for a reason installing cannot fix, such as a missing recording, an unsupported platform or a busy engine.
- **Behaviour:** the checks read files only. They load no model, download nothing, write nothing and never raise an error. Qwen3 checks the platform, then the engine, then the model, then the clone's recording and transcript, and each reason names one next step. One unavailable voice never affects another voice or engine, and is never swapped for a different voice.
- **Persistence:** Chatterbox remembers its answer per process until the recording's size or time stamp changes.
- **Differences:** Edge voices are never checked. Kokoro and Chatterbox call any file that is not ready "not installed", while Qwen3 distinguishes missing, partly installed and damaged.
- **Machine state in tests (v0.7.2 Phase 5):** the panel's Kokoro/Chatterbox check (`voice_install.models_status`) runs unreplaced against real stand-in files in every state (ACT72-057's first half), and the Qwen3 panel tests state the installed and fresh-install machine explicitly instead of reading the machine they run on (ACT72-008). Simulated readiness is asset health, never engine qualification.

### Cloned voices' reference recordings and transcripts
`ACT.TTS.VOICE-CLONE-REFERENCES`

- **Purpose:** keeps the cloned voices tied to the exact approved recordings and transcripts that ship with the app.
- **Behaviour:** a recording is used only if it matches its registered checksum. A missing or changed recording blocks only its own voice, and is never replaced by a download or by another voice. Qwen3 clones narrate with the six approved transcripts shipped with the app. A damaged bundle blocks the six clones and tells the user to extract a fresh copy of the app. It never falls back to a local store.
- **Outputs:** the shipped recordings are never written. Derived clips and cached voice conditioning live under `files/runtime-data` and are rebuilt when their source, engine or settings change. A Qwen3 clone job works from a verified copy of the recording, padded with silence, inside its job folder.
- **Differences:** Chatterbox and Qwen3 clones share one recording per speaker. Only Qwen3 also needs a transcript.

### Install the Kokoro voices
`ACT.TTS.SETUP.KOKORO`

- **How to reach it:** select a Kokoro voice that is not installed and press Start. The Install & Continue window shows exactly what will be downloaded, and only its install button installs anything. The other route is ticking Kokoro in the first-run setup.
- **What is acquired:** the Kokoro-82M configuration and weights, one file per voice, and the approved spaCy English wheel. Everything comes from the pinned commit, never a moving branch. The wheel is checked before pip sees it, installed offline, and kept so that a rebuilt environment can reinstall it without downloading.
- **Outcome:** success only after the files are checked again, recorded, and Kokoro is proved to load. From the panel, the conversion the user asked for then starts once, by itself. Skip, Cancel, closing the window or a failure starts nothing and creates nothing.
- **Failure, cancel, retry:** wrong bytes are never installed. Cancel keeps a partial file that a later, newly confirmed install resumes. A retry needs a fresh plan and a fresh confirmation.
- **States:** missing, damaged, ready, unverified, busy, unsupported Python, or engine proved broken. In the last case nothing is downloaded, because the app's own environment repair fixes packages.
- **In the panel (v0.7.2 Phase 5, ACT72-007):** one Kokoro message at a time. While the voice can run, the notice says it runs locally from its installed model files and promises no download; while it cannot, only the setup line naming Install & Continue shows. At 920x600 Start and Cancel stay on screen in both.

### Install the Chatterbox Turbo model
`ACT.TTS.SETUP.CHATTERBOX`

- **How to reach it:** Install & Continue from a Chatterbox voice, or the first-run setup.
- **What is acquired:** exactly the Turbo files the engine loads. The unused `s3gen.safetensors` is not acquired.
- **Behaviour:** the download can never exceed what was confirmed. If a file is lost or changed after the plan was shown, the install fails and asks for a new plan. Success needs a passing import probe.
- **Differences:** no package is installed, only model files. Missing reference recordings cannot be installed. They block only their own voice.

### Install Qwen3 voices (CustomVoice, Base or both)
`ACT.TTS.SETUP.QWEN3`

- **How to reach it:** with any Qwen3 voice selected, press **Install / repair Qwen3 voices...** (refused while a conversion runs), then choose **Install CustomVoice**, **Install Base** or **Install Both**. Each button shows its size. A Qwen3 component can also come through Install & Continue or the first-run setup.
- **Consent:** nothing downloads until the confirmation is answered Yes. It lists the engine, each model, the files the two models share, the total download and the disk space needed.
- **Behaviour:** the two models install independently, and "Both" fetches their shared files once. Every file is accepted only when its size and checksum match. An interrupted download resumes where it stopped. Too little disk space is refused before anything is downloaded.
- **Failure, cancel, retry:** while an install runs, the other buttons and Close are disabled and **Cancel install** is enabled. Cancel keeps what completed, and the next install fetches only the rest. A model is never reported installed half-way. Closing the window cancels the work first. Failures are a result sentence, and the progress bar stays where it was.
- **States:** the dialog text names the engine in use (`.venv\engines\qwen3`, or an older `.venv-qwen3`), each model and where Qwen3 will run. On a non-Windows platform nothing is offered.

### Check and repair the Qwen3 voices
`ACT.TTS.SETUP.QWEN3-REPAIR`

- **How to reach it:** **Check and repair** in the same dialog, enabled once an engine or any model folder exists.
- **Behaviour:** the check is read-only. It starts the engine and checksums every installed file. The dialog then shows what is wrong and what a repair would download, and acts only on Yes. No changes nothing. A clean check says so and asks nothing.
- **Repair:** re-fetches only the failing files, and rebuilds an engine that will not start. It removes only the app's own engine folder, and refuses to delete a folder it cannot prove is its own.
- **Refusals:** a repair refuses during a conversion and without enough disk space for its plan.

### Qwen3 engine environment
`ACT.TTS.SETUP.QWEN3-ENVIRONMENT`

- **Purpose:** Qwen3-TTS needs library versions that conflict with the app's own, so it gets its own Python environment at `.venv\engines\qwen3`. It is built directly from the app's verified base Python 3.12.
- **Behaviour:** all 89 packages are the exact reviewed wheels. They are fetched and checksummed once, then installed offline, so pip never contacts a package index. The install is recorded only after the worker's probe imports the whole stack. An older `.venv-qwen3` is used while it is the only engine. It is never installed into, rebuilt or deleted.
- **States:** not installed, installing, installed, out of date, cannot be verified, broken.
- **Failure:** a failed pip or probe leaves the install incomplete, and the downloaded wheels are kept for the retry. A network failure or cancel during the wheel fetch leaves an existing engine untouched.

### Developer tools: Qwen3 reference transcripts
`ACT.TTS.SETUP.QWEN3-CLONE` (developer-only, not required for release)

- **Purpose:** the maintainer's workflow that produced the six clone transcripts.
- **How to reach it:** only exists when `config.toml` sets `developer_mode = true`. The shipped app sets it to false, so in normal mode the button is not created and the dialog cannot be opened. In developer mode, open **Developer tools → Reference transcripts...** from the Qwen3 dialog. The steps are:
  1. Install the speech recognizer, after a confirmation that states its size.
  2. Create drafts.
  3. Listen with Play recording and Stop, edit the text, and tick "I listened...".
  4. Approve ticked voices.
  5. Choose "Narrate with my approved texts..." or "Use the shipped texts".
- **Behaviour:** drafts are made locally and saved unapproved. An approval needs the tick and some text, and is tied to the recording's checksum. Narration keeps using the shipped transcripts unless the developer confirms a choice for a voice.
- **Persistence:** a local, untracked store and a selection file under `files/runtime-data/qwen3`. Neither ships with the app.

### Optional voice setup plan and disclosure
`ACT.TTS.SETUP.PLAN`

- **Purpose:** answers, before anything is downloaded, what each of the four components needs here and what it would cost. This is what Install & Continue and the first-run setup show for review.
- **States:** each component is ready, missing, damaged, unsupported, busy, blocked by a bad transcript bundle, or unverified. Only missing (install) and damaged (repair) plan any download.
- **Outputs:** what would be downloaded, reused, copied, occupied and needed as temporary space. Files shared by the Qwen3 models are counted once. Each figure says how it is known, and unknown is never counted as zero.
- **Behaviour:** planning writes nothing and starts no process. The first-run estimate is a stated upper bound that proves nothing.

### Consent-bound acquisition (no silent downloads)
`ACT.TTS.SETUP.CONSENT`

- **Purpose:** makes "nothing downloads unless you agreed to exactly this" a property of the one path every optional-voice byte passes through.
- **Behaviour:** a confirmation is tied to the exact plan shown. A forged, outdated, altered or enlarged confirmation acquires nothing. A confirmation is used once and never replayed. All network access goes through a gate that refuses any address outside the confirmed files and stops at the confirmed number of bytes. Every write is checked to stay inside its own folder.
- **Differences:** the Qwen3 dialog's Yes and the Edge sentence-data prompt are separate consent routes.

### Setup worker operation and its single outcome
`ACT.TTS.SETUP.OPERATION`

- **Purpose:** runs one plan or install request, from a fresh plan to exactly one result.
- **States:** planning, then validating, then acquiring, then verifying, then succeeded; or refused, cancelled or failed at any step.
- **Behaviour:** an install succeeds only when every chosen component is proved to work afterwards. A failure in one component leaves the others' files untouched. Cancel gives one cancelled result at any point and keeps partial files for a later, newly confirmed resume. The worker runs only in the app's own Python 3.12 environment.

### Local engine health probes and busy detection
`ACT.TTS.SETUP.HEALTH`

- **Purpose:** proves whether the Kokoro and Chatterbox packages load, and whether a component is in use.
- **Behaviour:** probes run in a fresh interpreter with the model hub offline, with a time limit, and can be cancelled. The answer is proved, broken or unproved, and a probe that cannot finish is never called broken. A probe is repeated only while Windows Application Control is still evaluating new files, a limited number of times. A component that someone else holds is reported busy and nothing is fetched for it. An engine proved broken gets no download.

### Pinned model identities and offline reuse
`ACT.TTS.SETUP.MODEL-INTEGRITY`

- **Purpose:** "installed" always means these exact bytes.
- **Behaviour:** every model file has a pinned repository, commit, size and checksum. A file with a different size or content is damaged and is fetched again only under a repair confirmation. A verification record never vouches for changed bytes. A moved upstream branch cannot change what is reported, and a linked cache is treated as unverified. Files that are already verified are reused offline: a second install downloads nothing and runs no pip.
- **Differences:** Qwen3's quick status checks sizes only. The full checksum runs in Check and repair.

### v3 authoritative planner and read-only workers (not wired)
`ACT.TTS.SETUP.V3-PLANNING` (not required for release)

The next-generation planner and its contained planning workers. They are built and qualified, but no production path uses them, and the planning worker's entry is disabled without an injected test context. Changed or forged terms never use up a confirmation.

### v3 sealed package and engine authority (not wired)
`ACT.TTS.SETUP.V3-LOCKED-EXECUTION` (not required for release)

Scoped wheel consumption, engine-change authority and a disposable spaCy consumer for the future v3 installer. None has a production caller. The one production use is the offline pip bootstrap that `qwen3_wheels` takes from `qwen3_packages`.

### Voice sample and quality harness (developer)
`ACT.TTS.VOICE-QA-SAMPLES` (not required for release)

A command-line tool that is never imported by the app. It makes one sample per voice for manual listening, plus the Chatterbox evaluations, a quality suite over original test text, and final-acceptance measurements. One failing voice never stops the others.

### Intentional differences from other tools

- Only Kokoro has a speed control. Chatterbox and Qwen3 have neither speed nor rate.
- The local engines are capped at one file at a time. Edge runs many at once.
- Qwen3 runs out of process in its own environment and can be killed mid-chunk. Kokoro and Chatterbox run in-process and stop between chunks.
- Qwen3 has its own install/repair dialog. Kokoro and Chatterbox are installed only through Install & Continue or the first-run setup.
- Only Kokoro installs a Python package (the spaCy English model) into the app's own environment.
- Kokoro and Chatterbox report any non-ready model file as "not installed". Qwen3 distinguishes missing, partly installed and damaged.

### Not verified here

- Real synthesis with installed Kokoro, Chatterbox and Qwen3 models, and real downloads from the pinned sources. These need the optional-engines qualification; routine tests use stand-ins. The `tts.kokoro-local` journey runs only where Kokoro is installed.
- Windows Application Control on a fresh machine blocking the first load of new native files (fresh-windows qualification).
- Listening quality of every local voice (owner).
- Qwen3 on any platform other than Windows (refused by design), and Chatterbox on Apple MPS.
- Real GPU memory pressure and machine-wide Qwen3 contention between two Windows users.
