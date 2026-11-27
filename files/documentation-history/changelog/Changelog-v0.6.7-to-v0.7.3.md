# Audiobook Creation Tool — Changelog archive: v0.6.7 to v0.7.3

Archived unchanged from `md-instructions/Changelog.md` by DOC-1 (v0.8.2 Phase 2, 2026-11-27). Everything below the line is the original
text, byte for byte and in its original order (from `[0.7.3]` down to the plain `[Unreleased]` block and `[0.7.0]`). Nothing here is rewritten or superseded by being moved; the
index at the top of `md-instructions/Changelog.md` still names the entries that govern. The whole file as it was before the
archival: `git show dabb02d:md-instructions/Changelog.md`.

---

## [0.7.3] - 2026-11-12 — owner-accepted hotfix (Windows)

**Fixed**
- **M4B Converter:** if FFprobe's chapter list is invalid and the source proves it has separate
  QuickTime and Nero chapter representations, recover the independently read Nero table only when
  it passes the existing strict validator and audio-coverage checks. Normal valid files are unchanged;
  unsupported, corrupt or ambiguous tables still fail closed. Split keeps every recovered chapter;
  Whole writes the recovered navigation under the existing metadata options. The original source is untouched.
- Identity is 0.7.3. Focused checks and private real-book/GUI preflight passed. The owner
  reports PASS for the full 33-chapter book and multiple additional audiobook conversions
  using the verified candidate. The earlier old-launcher selection problem is resolved.
  PR #15 is merged into master; Windows packaging is authorized without a repeat full gate
  or qualifications. README now prepares the v0.7.3 download instructions; GitHub publication
  remains a manual owner action and has not occurred. (Later the same day the owner published the GitHub
  release "v0.7.3 - Audiobook Creation Tool" with `AudiobookTool-Windows-v0.7.3.zip`; tag `v0.7.3` =
  `dbf38f7`.)
  See `files/release-history/ACT-v0.7.3-Owner-Acceptance.md`.

## v0.7.2 release-readiness history (2026-11-12)

The following entry records the earlier pre-release checkpoint. The subsequently published
v0.7.2 release, tag and ZIP are unchanged by the v0.7.3 candidate.

**Fixed**
- **MP3 Tool, M4B Maker and Metadata Editor: a file that appears in the output folder while a Book is being
  published is never overwritten.** Each output takes its name only if nothing holds it. Otherwise that Book fails, the
  other file is left exactly as it was, and the finished file stays ready for Retry Failed.
- **MP3 Tool: a failed publication's roll-back takes back only its own files.** On Windows each file is held from the
  moment it is checked until it is moved back, so another program's file at that name can never be taken.
  - Elsewhere, a roll-back leaves what was published where it is and says so; a retry then refuses until that is sorted
    out.
- **TTS, PDF sources: numbers that a sentence runs into at the foot of a page are read** (an access code "1984" was
  dropped as if it were a page number).
  - Still a limit, for the owner to decide: a bare number alone under a finished sentence, counting with the next page's
    number, cannot be told from a page number and is left out.

**Verification only**
- The release record is `files/dev-work/phase9-remote-review/ACT-v0.7.2-FINAL-PR-READINESS.md`. The independent closure
  reviews passed; the M4B scaling and Edge low-memory qualifications passed again on the release candidate. The full
  Windows gate found three out-of-date structural tests; they were corrected, and the gate has not yet been run again.

## [Unreleased] — v0.7.2 Phase 9 remediation: five defects an independent review found, fixed (2026-11-12)

**Fixed**
- **TTS, PDF sources: words and numbers on a line of their own are read again.** The page-number cleanup added in
  Phase 8 removed any number that happened to be the first or last line of a page, and an older rule removed any line of
  one to four capital letters anywhere in a book. A sentence that ended a page with a number lost the number ("The safe
  opens with the code 1984" was read without the code), and "NOT", "NASA" or "I" on a line of their own vanished from
  the sentence they belonged to. A line is now removed only when the page's layout and another page both show it to be
  a page number or a running head: it stands clear at the top or bottom of the page, and the numbers count up page by
  page, or the same short heading sits at the same place on another page. Anything less certain is read aloud. A number
  range or a compound name broken at a line end keeps its hyphen ("1939-1945").
  - Still imperfect, and read aloud rather than dropped: a running head longer than four capital letters, a page
    number or heading that appears only once, a large drop capital on a line of its own. A compound word broken at a
    line end before a small letter still loses its hyphen ("well-known" is read as "wellknown").
- **M4B Converter: Cancel pressed while a finished file is being checked no longer publishes it.** The last step
  before a converted file gets its name is measuring its length. A Cancel that arrived during that measurement was not
  looked at again, so the file appeared in the output folder after Cancel. Cancel is now asked again after the
  measurement, and the file is given its name only if Cancel had not been pressed by then. If the file was already
  being saved when Cancel arrived, it stays and the result says so. Pause is unchanged: the file in hand is finished
  and saved, and the run waits before the next book.
- **M4B Converter: a file that appears in the output folder during a conversion is never overwritten.** If something
  else created a file with the same name while a book was converting, the Converter replaced it. It now stops that book
  with "already exists, so it was not replaced", leaves the other file exactly as it is, and leaves no temporary file
  behind. Retry Failed behaves the same way.
- **Verification only.** A qualification run could be recorded as passed although its own result said a check had
  failed, that nothing had run, or that it belonged to another scenario. The gate now checks this before a pass is
  recorded. The `m4b-scaling` staging check (T5) reads every temporary file exactly, whoever removes it and however,
  fails when it cannot, and compares the total with no allowance, as approved. No budget changed.

## [Unreleased] — v0.7.2 Phase 8: the release candidate (version 0.7.2): a window freeze and two narration defects fixed (2026-11-10)

**Fixed**
- **Verification only (Phase 8 remediation, 2026-11-11).** Nothing in the application changed. The `m4b-scaling` qualification now measures what its memory and staging checks compare: it no longer reads its own open process handles as the job's memory, it counts the console host Windows starts with the decoder, and it reads staged bytes exactly at every discard and publication instead of sampling them. `verify.py --status` reads a qualification PASS as a PASS. The budgets did not move (ACT72-067, ACT72-068, ACT72-069).

- **M4B Converter: the window no longer freezes when a run ends.** The Converter shows its output folder when a run
  finishes. It asked Windows to do that from the window itself, so while Explorer was busy or restarting the whole
  window stopped responding (up to 37 seconds was measured). The folder is now asked for in the background: the run's
  result is shown and the buttons work at once, and if the folder cannot be opened the Activity log says so and where the
  files are. The same applies to every "Open Output Folder" and "Open log folder" button.
- **TTS, PDF sources: page numbers are no longer read aloud in the middle of a sentence.** When a page ended partway
  through a sentence, the page number printed under it was narrated as part of the sentence, and a word hyphenated at the
  bottom of a page was joined to the number instead of to its other half. A number printed as the first or last line of
  a page is now removed first, and a hyphenated word is joined across the page.
- **M4B Converter, xHE-AAC books on Windows:** the Windows decoder's audio format is now read after it has decoded its
  first audio, because Windows can correct its first answer; a format that changes later stops the book with a clear
  message instead of risking wrong audio.
- **Setup help:** `--repair-venv` no longer claims FFmpeg is never installed. The repair rebuilds only the Python
  environment; the launch that follows checks FFmpeg and repairs it, as every launch does.

**Changed**
- The application's version is **0.7.2** (`version.py`, `config.toml`). There is no v0.7.2 release, tag or download yet;
  the README still describes the published v0.7.0.

**Known limits (not changed)**
- PDF sources: a title printed at the top of every page is still read out at each page; a short all-capitals word alone
  on a line is dropped; a compound word broken at its hyphen loses the hyphen (ACT72-064, awaiting a decision).

**Added (development only)**
- Tests on real media and real processes: the Windows decoder on real books, PDF cleaning against hand-written narration,
  a window that crashes as it starts, the setup help text, and a busy file manager.
- Three journeys on disposable copies of the application: the first-run window refusing a folder that is too deep, the
  first-run choices and Cancel, and Clear Downloaded Data from the click to the next launch.
- Three qualification scenarios (`verify.py --mode qualification`): `optional-engines`, `edge-low-memory` and
  `fresh-windows`. A scenario that needs the network runs only when it is given its `--network` policy.
- The gate's pictures of a window are now of the whole window, inside the desktop, with nothing over it: a journey moves
  its window inside the work area before enlarging it, and a picture is refused if any part of the window is covered or
  off the screen. Before, a picture could include the Windows taskbar (development evidence only; nothing shipped).

## [Unreleased] — v0.7.2 Phase 7B: long split books convert much faster, with identical files (2026-11-10)

**Changed**
- **M4B Converter, Split by chapter.** A book of ordinary AAC audio with many chapters is now decoded once and each
  chapter cut from that decode, instead of decoding everything before every chapter again. Every MP3 is byte-identical
  to what the Converter wrote before. Small books, books of a few long chapters, other codecs, the Windows xHE-AAC
  route and FFmpeg builds the route was not qualified on keep the previous route unchanged. The route is chosen when the
  books are examined and kept for the whole run and for Retry Failed.
- A book whose audio frames are damaged in a way FFmpeg skips silently now fails on the new route instead of producing
  shifted chapters (its sample count no longer matches the book).
- Measured on the Windows development machine: a 6-hour book of 48 chapters converts in 133 s instead of 287 s, a
  1,000-chapter book in 154 s instead of 444 s, and a 12-hour book of 24 chapters in 254 s instead of 401 s.

**Added (development only)**
- The `m4b-scaling` qualification (`verify.py --mode qualification --scenario m4b-scaling`) with a deterministic book
  recipe, a pinned per-FFmpeg-build reference and the frozen performance budgets. It passed (79 of 79 checks, 207 runs);
  ACT72-012 is closed.

**Fixed (development only)**
- The qualification's benchmark runs opened an Explorer window each (the Converter reveals its output folder when a run
  ends), which crashed Explorer six times on the development machine; a run now records that request instead and refuses
  to start unless it can. The encoder fault now fires mid-chapter, and the disk-write budget no longer counts audio passed
  between processes.

## [Unreleased] — v0.7.2 Phase 7A: the M4B Converter's split slowdown measured (2026-11-10)

**Added (development only; nothing a person sees changes)**
- A measured baseline of the M4B Converter's Split by chapter against v0.7.1, a frozen compatibility manifest, a comparison of
  five optimisation designs and proposed performance budgets (`files/plans/ACT-v0.7.2-Phase7A-M4B-Converter-Baseline-and-Design.md`). No application code changed; the proposed faster
  route awaits review.

## [Unreleased] — v0.7.2 Phase 6, final candidate: four standing checks the full gate found (2026-11-09)

**Fixed (development only; nothing a person sees changes)**
- The launcher's main-thread Tk teardown (batch B, ACT72-017) is named `_finish_tk_objects`: a standing check forbids the word "release" in the launcher, where it may only ever mean building a release.
- The check that keeps folder removal in the cleanup coordinator now names `work_area.py`, which batch D moved into `shared/`: it removes only its own private working folders, and it is held to the same rule that it never reaches a cleanup target.
- Two coverage entries named test ids pytest does not collect (a parameter containing "→", and a test batch D parametrized); both now name the collected ids.

## [Unreleased] — v0.7.2 Phase 6, batch E: honest words for the TTS skip box, and the six tools side by side (2026-11-09)

**Changed**
- TTS: the box that was labelled "Resume (skip existing MP3s)" now reads "Skip MP3s already in this run". Every run starts in a new folder, so it never resumed an earlier run and never will; what it does is unchanged.

**Added (development only; nothing here ships)**
- A six-tool consistency matrix in the feature map: how the six tools behave where you would expect them to behave alike, and five places where they differ, each left for the owner to decide.

**Not changed, for the owner to decide**
- ACT72-030: eleven helper functions with no caller in the app (the Converter's `sanitize_filename` and `quote`, `m4b_probe.probe_sources`, `m4b_winaudio.unavailable_message`, and the MP3 Tool's `concat_mp3s_fast`, `normalize_to_wav`, `make_silence_wav`, `concat_wavs_to_mp3`, `add_silence_to_mp3`, `trim_from_end_mp3` with the `save_error_log` only they use) are kept: six MP3 test modules pin them as proven FFmpeg helpers, so removing them is not the small change a Phase 6 suggestion allows.

## [Unreleased] — v0.7.2 Phase 6, batch D: the untested branches, and two defects they found (2026-11-09)

**Fixed**
- Cover Image: Enter now answers the "Confirm replacement of original images" question. Tk gives its buttons Space but not Enter, so Enter did nothing at all; it now presses the focused button, which is Cancel unless you moved to Replace. Escape and closing the window cancel, as before.
- Cover Image: when a destination could not be planned after the run folder was made, the empty numbered folder was left behind; it is now given back, as every other tool does.
- First-run setup: the two "setup was stopped" messages no longer tell you to run Setup_and_Run "again"; they say setup finishes the next time you start the app with it.

**Changed (development only; nothing here ships)**
- The owned temporary work area moved from `tts/` to `shared/`: the M4B Maker stages its custom builds in it too, and a tool may not import the TTS package. Its behaviour and its `act-tts` folder are unchanged.
- New tests for branches that had none: import confirmations, Cancel Import, duplicate skips, remembered folders, reservation and plan failures, statuses and dividers, Clear Log, FFmpeg readiness and typed values in the M4B Maker, MP3 Tool, Metadata Editor, Converter and Cover Image; the launcher's own model-cache redirect; wheel scrolling. A real Cancel in a Maker custom build replaces a test that checked nothing.
- Three new native journeys: the Cover replacement question answered with real Enter, Escape, Alt+F4 and a click; Alt+F4 while a folder scan is walking; the real mouse wheel over the Maker's Chapter Titles. The relaunch journey now also proves the window size is never carried over.

## [Unreleased] — v0.7.2 Phase 6, batch C: accurate messages and validated values (2026-11-09)

**Fixed**
- MP3 Tool, M4B Maker and Metadata Editor: after a Cancel, the Book that was being processed now reads "Cancelled" and the closing line counts it as "stopped by Cancel"; Books the run never reached still read "Not attempted". TTS: the closing line of a cancelled run says how many files finished, were stopped and were not started.
- Cover Image and M4B Converter: the Summary no longer shows "All done." above "Running." or "Finished." twice; the run's lines come first, its end once, then the closing line.
- TTS: the MP3 bitrate you choose is now explained when it cannot be reached. Every voice makes 24 kHz speech, where an MP3 can be at most 160 kbit/s, so 192k and 320k give 160k files (measured on real output of every voice); the Summary now says so when a run starts. Nothing about the audio changed.
- TTS: a Kokoro speed outside 0.5 to 2.0, or not a number, is refused when you press Start. A leftover bad Kokoro speed no longer stops an Edge conversion with an error.
- Cover Image: a typed target size must be a whole number from 256 to 4096, the size box's own range; 0 no longer turns into 1024 and huge sizes no longer reach the resizer.
- M4B Converter: the unusable-chapter message no longer suggests converting as a whole book (which refuses the same file); the Cancel message says the file being converted is stopped now and its book taken back; the Title field no longer promises the filename when left blank.
- MP3 Tool and M4B Maker: a refused Start #, Time or Silence names the Book by the number the navigator shows, also after a Book was removed.
- The launcher no longer calls a tool that failed to load "ready". Reset Preferences now says it also returns Light/Dark to Light.

**Added (development only; nothing here ships)**
- Tests for each, every one seen failing on a planted defect; a real-media check of the 24 kHz bitrate ceiling.

## [Unreleased] — v0.7.2 Phase 6, batch B: run locks, shutdown and first-run setup (2026-11-09)

**Fixed**
- TTS: Resume, the Edge speech rate and the Kokoro speed now lock while a conversion runs, like every other option the run has already taken; before, they looked editable and changing them did nothing. MP3 Tool: the Chapter Titles box locks during a run too, as it already did in the M4B Maker and Metadata Editor. What you had chosen is unchanged when the run ends.
- Closing the app no longer risks a long silent wait at exit: the closed window's Tk objects are now cleaned up straight away instead of later from a background thread, where each one waited about a second and logged an error (measured: about 23 seconds for TTS and 17 for Cover Image in the worst case).
- First-run setup: answering No to "Stop setup?" while the optional voices are being checked or installed now really keeps that work going; before, it stopped anyway and launched the app.
- First-run setup: closing the window while the app's packages are installing now asks "Stop setup?". Yes stops the package installer and everything it started, starts nothing else and closes the window once setup has stopped; setup finishes the next time the app is started with Setup_and_Run. Before, the window closed at once and the installer kept running in the background.

**Added (development only; nothing here ships)**
- Tests for each, seen failing on the old code and on planted defects: a real run held inside the engine for the locks, a real Tk root in its own process for the shutdown cleanup, and the real setup window with a stand-in installer that starts a process of its own. The forced-shutdown scenarios now check that no Tk call happens on a background thread and that nothing waits.

## [Unreleased] — v0.7.2 Phase 6, batch A: private staging lives only as long as Retry Failed can use it (2026-11-09)

**Fixed**
- MP3 Tool: a run that was cancelled, that failed in a way Retry Failed cannot repair, or that stopped on an internal error no longer leaves its private `.work` folder in the run folder. The good pieces of a Book that failed in a way Retry Failed can repair are still kept for it, and only while Retry Failed can still use them: Clear All Imports, starting another run or closing the tool removes them. A link planted in that private folder (a Windows junction included) is removed as a link; what it points at is never touched.
- M4B Maker and M4B Metadata Editor: the same rule for the checked copy kept after a publication or Series Part failure. A custom-folder Maker build now keeps its private work in the program's own temporary work area, which records which running program owns it; if the program is killed, the next custom build removes what it left once that program is provably gone, instead of `act-m4b-build-*` folders staying in the temporary folder for good.
- M4B Converter: a split book that failed or was cancelled no longer leaves its empty book folder in the run folder. The run folder itself is never removed, and Retry Failed makes the book's folder again.

**Added (development only; nothing here ships)**
- Regression tests for each tool (failed publication and numbering, Cancel during a real FFmpeg step, a kept candidate then Clear All Imports, a new run or close, a run let go while its worker is still running, a killed Maker's leftovers, a planted junction), each seen failing on the old code and on a planted defect; the MP3 Tool's native unreadable-track journey now checks that nothing is left in `.work` after the tool closes.

## [Unreleased] — v0.7.2 Phase 6E (2026-11-09)

**Fixed**
- Edge TTS command line (`epub2tts-edge --format m4b`, developer only): Ctrl+C now stops the M4B assembly at once. Before, it waited for FFmpeg to finish the running step by itself (measured: about 29 seconds on a step slowed to a 30-second book's playing time, so the wait grows with the book) and ended with a traceback, and a stalled FFmpeg hung the command line for good. Now the running FFmpeg is stopped, no further step starts, nothing is saved, and the command line prints one line and exits with status 130. Each step also has a time limit, the book's playing time plus ten minutes; a step still running then is stopped the same way and the command line exits with status 124. A failed step still exits with status 1. A run that is interrupted, stopped or fails never touches the files already in the output folder (with `--overwrite` too) or the sources.

**Added (development only; nothing here ships)**
- Tests that press a real Ctrl+C in the command line's own console during each FFmpeg step, between and after them, and while a step ignores the first stop, and that a stalled FFmpeg is stopped at its time limit and an unrelated FFmpeg survives; each seen failing on a planted defect.

**Verified**
- The canonical changed-area gate PASSED on `6ef00fe`: every scenario (49 of 49) and 14,466 tests, 65 of them skipped with named reasons. It ran every test because the change touches a module every tool shares. This is a checkpoint, not the full gate reserved for the end of Phase 6, and not a release.

## [Unreleased] — v0.7.2 Phase 6D (2026-11-08)

**Fixed**
- M4B Metadata Editor: Cancel now stops a chapter rename at once. Before, it waited for FFmpeg to finish rebuilding the chapter track (measured: about 59 seconds on a rename slowed to a one-minute book's playing time, so the wait grows with the book), and a Cancel pressed between the rename's two steps still started the second one. Nothing of the cancelled Book is published, Books already finished and the original files are untouched, and a stopped rename is never reported as a failure to retry. Pause is unchanged: the running rename finishes, then the run pauses.

**Added (development only; nothing here ships)**
- Tests that press Cancel and Pause during real chapter renames, at each of the rename's two FFmpeg steps and through the panel, and prove an unrelated FFmpeg survives and FFmpeg's real refusals stay retryable failures; each seen failing on a planted defect.

**Verified**
- The canonical changed-area gate PASSED on `0e35ee5`: every scenario (49 of 49) and 14,446 tests, 65 of them skipped with named reasons. It ran every test because the change touches a module every tool shares. This is a checkpoint, not the full gate reserved for the end of Phase 6, and not a release.

## [Unreleased] — v0.7.2 Phase 6C (2026-11-08)

**Fixed**
- MP3 Tool and M4B Maker: Cancel now stops FFmpeg at once, even in the middle of a long encode. Before, it waited for the running step to finish (measured: about 9 seconds for the MP3 Tool and 27 for the Maker on a one-hour book), and a Write ID3 run whose only Book was being encoded when Cancel was pressed went on to publish it. Nothing of a cancelled Book is published, Books already finished stay, and a stopped step is never reported as a failure to retry. Pause is unchanged: the running step finishes, then the run pauses.

**Added (development only; nothing here ships)**
- Tests that press Cancel and Pause during real encodes and during every FFmpeg step of both tools, and prove an unrelated FFmpeg survives; each seen failing on a planted defect. A test that the subprocess module imports on its own, as the optional-setup planning worker and the pre-setup FFmpeg check load it. The gate's orphan control now switches off both ways the application stops FFmpeg when its window closes.

**Verified**
- The canonical changed-area gate PASSED on `9c4a93e`: every scenario (49 of 49) and 14,432 tests, 65 of them skipped with named reasons. The first candidate's run had failed two checks (the optional-setup planning worker could not import the subprocess module without the cancellation module beside it, and the orphan control no longer saw the FFmpeg it exists to see, because Cancel now stopped it); both were repaired before this run. This is a checkpoint, not the full gate reserved for the end of Phase 6, and not a release.

## [Unreleased] — v0.7.2 Phase 6B (2026-11-08)

**Fixed**
- TTS: a conversion's temporary files (working folders, pydub's files and the local engines' encoding WAV, which can be as large as the whole narration) no longer stay in the system temp folder for good when the program is closed forcibly or crashes. They now live in the tool's own `act-tts` folder there, with a record of which running copy of the program owns them, and the next run removes what a program that has ended left. It never touches files it cannot prove are its own, another running copy's work, or anything else in the temp folder; it names what it left in Detailed. Folders left in the temp folder by earlier versions (`epub2tts_*`) are not removed automatically.

**Added (development only; nothing here ships)**
- Tests that kill and keep real child processes, damage the ownership record in fifteen ways, and plant links and swaps, each seen failing on a planted defect.

**Verified**
- The canonical changed-area gate PASSED on `dc74a3c`, its first run: every scenario (49 of 49) and 14,392 tests, 65 of them skipped with named reasons. The first candidate's run had failed two source-structure checks (a module missing from its package's list, and a class name reserved for the shared Book Workspace); both were repaired before this run. This is a checkpoint, not the full gate reserved for the end of Phase 6, and not a release.

## [Unreleased] — v0.7.2 Phase 6A (2026-11-08)

**Fixed**
- TTS: a Qwen3 voice selected at the 920x600 minimum pushed Start, Cancel and the log out of the window. At that size the hardware and speed note now sits behind a **Hardware and speed...** button beside Install / repair, which shows the whole note. Larger windows show the note in full, as before.
- Setup: the first-run and repair windows, and the optional-voices step, threw a person reading earlier log lines back to the newest line on every new message. The log now follows new lines only while its newest line is on screen, and follows again once the reader is back at the bottom.

**Added (development only; nothing here ships)**
- Regression tests at real sizes in the real launcher for every Qwen3 state, and tests that run the real setup windows with the real mouse wheel. Each failed on the old code.

**Verified**
- The canonical changed-area gate passed on `69514f9`, its first run. The setup fixes touch modules every tool shares, so the gate selected every test and scenario: 49 of 49 scenarios and 14,344 tests, 65 of them skipped with named reasons. This is a checkpoint, not the full gate reserved for the end of Phase 6, and not a release.

## [Unreleased] — v0.7.2 Phase 5 (2026-11-07)

**Fixed**
- The Summary and Detailed logs of every tool jumped back to the first line on every update, so new lines never came into view and a person reading earlier lines lost their place. Each pane now follows new lines while its newest line is on screen and stays where the reader is when they have scrolled up, through resizes and tab or tool switches. It follows again at the bottom.
- MP3 Tool: an Album or Artist typed, or deliberately cleared, before a Book's first files were added was replaced by the files' own tags. A field is now filled from the files only when it has no value at all. A Book emptied and refilled also keeps its values. The written tags follow the panel.
- TTS: with a Kokoro voice selected and not installed, the window at its 920x600 minimum lost Start and the log below the fold. Two messages were stacked, one of them still promising a download on first use, which has not been true since v0.7.0. One message now shows at a time and it says what is true.
- TTS: an Edge speech rate the Edge voices refuse, such as "10%" without a sign, reserved a run folder and then failed every folder-imported file. Start now says how to type it, before anything is created.
- TTS: messages said "Press Create again", but the button is labelled Start. They now say Start.
- MP3 Tool, M4B Maker and M4B Metadata Editor: the artwork "Choose…" button read "Choose." at every size. Both artwork buttons now show their whole label.

**Known issue**
- TTS: a Qwen3 voice selected at the 920x600 minimum still pushes Start out of the window. Its hardware and speed disclosure and the Install / repair button need more height than that size has. 1024x720 and larger are fine. What gives way is the owner's decision (ACT72-058).

**Added (development only; nothing here ships)**
- Regression tests for each fix, on real widgets at real sizes and on the tags real runs publish, and a native journey that types and scrolls with real input. The tests that depended on whether Qwen3 was installed on the machine running them now state the state they assume.

**Verified**
- The complete Windows gate passed on `607ae39`, its first run: 49 of 49 scenarios and 14,327 tests, 65 of them skipped with named reasons. All 262 release-required features are mapped, and routine evidence in that run satisfied every one. 93 of them still wait on release evidence: owner checks, planned gaps or qualification. This is the routine gate, not a release.

## [Unreleased] — v0.7.2 Phase 4 (2026-11-07)

**Added (development only; nothing here ships)**
- The feature map: `files/dev-work/feature-map/`, a README and one document per tool, describing 273 features of the app by stable id. How each is verified lives only in `files/dev-work/verification-gate/coverage.json`, now the reviewed inventory. It holds every feature's source, contracts and verification, every control, dialog, key binding and tool found in the source or in a running copy of the app, a review record for every source file, and a ledger of 57 issues.
- The gate now refuses a full or changed run when the inventory has fallen behind the app: a new or renamed control, a changed source file nobody has reviewed against its features, a deleted or renamed test, a journey no feature maps, or an id that no longer exists.
- Tests for four required behaviours that had none: Open log folder, the hidden console window for every child process, and the M4B Metadata Editor's Open Output Folder and Cancel Import with its scan confirmations.

**Fixed (development only)**
- Running the gate's own contract tests directly no longer leaves a folder in `%TEMP%\act-gate`.
- A Maker test that asserted nothing now checks what its name says.

**Changed**
- The project briefing no longer says the M4B Metadata Editor's Import Folder has a subfolders option. It has none and always includes subfolders.

**Verified**
- The first complete Windows gate, on `927df46`, failed one check. Two release-required features were proved only by tests that always skip on Windows, so nothing on Windows proved them. Each now has a test that runs on Windows. Neither requirement was dropped.
- The complete Windows gate then passed on `7987503`: 48 of 48 scenarios and 14,252 tests, 65 of them skipped with named reasons. All 262 release-required features are mapped, and routine evidence in that run satisfied every one. 99 of them still wait on release evidence: owner checks, planned gaps or qualification. This is the routine gate, not a release.

## [Unreleased] — v0.7.2 Phase 3 acceptance closeout (2026-11-07)

**Fixed**
- Closing the app exited cleanly only because two internal lists happened to keep its closed main window alive. Without them, a background clean-up could crash the app on its way out (Windows error 0x80000003). The launcher now keeps its own window for the life of the program.

**Changed (development only; nothing here ships)**
- The verification gate's native journeys now run the app at Low integrity, so their real file dialogs can no longer add entries to the Windows recent-files history of the person running the gate. The gate refuses to run those journeys if it cannot show that this protection holds.

**Verified**
- The complete Windows gate passed on `118058c`: 46 of 46 scenarios and 14,206 tests, 65 of them skipped with named reasons. The journeys added no dialog-history entry.

## [Unreleased] — v0.7.2 Phase 3 (2026-11-06)

**Fixed**
- Closing the window while M4B Maker was working left FFmpeg running after the app had exited. MP3 Tool runs FFmpeg the same way and gets the same fix, though it was not separately measured before the fix. Closing now stops the work and the FFmpeg it started. M4B Metadata Editor also stops its run now, as the other three tools already did. Any other process, including another program's FFmpeg, is left alone.

**Added (development only; nothing here ships)**
- A native Windows and real-media acceptance stage in the verification gate: 46 scenarios that drive the real application with real mouse and keyboard input, and read the real output back independently.
- `--audit-scratch` and owner records for the gate's `%TEMP%\act-gate` scratch, approved by the owner. A failed run keeps its failing tests' folders in its own evidence.

**Verified**
- The complete Windows gate passed on `abd6400`: 46 of 46 scenarios and 14,190 tests, 65 of them skipped with named reasons. This is the routine gate, not a release.

## [Unreleased]

### v0.7.2 Phase 2 — the canonical verification gate (2026-11-06) — development tooling only; identity stays 0.7.1; NOT published, tagged or merged

- **Changed (the gate moved):** the one developer gate is now `files/dev-work/verification-gate/verify.py`, with modes `focused`, `changed`, `full` and `qualification`, and exit codes 0 PASS, 1 FAIL, 2 BLOCKED, 3 NOT RUN or incomplete, 64 invalid invocation, 130 interrupted. A bare command is now an invalid invocation rather than a 75-minute run.
- **Removed:** `scripts/verify.py`. Nothing forwards to it, and nothing the application ships or runs ever used it. Evidence of earlier runs stays where it was and reads as legacy.
- **Added (a pass has to be earned):** exit 0 alone no longer passes. The JUnit report and a record written from inside the pytest session must exist and agree. Ordinary and guarded collections must be disjoint and cover every test module, every skip must match a named reason, and selected, collected and executed tests must be the same set. A source change during the run, a leftover process or a stale or forged run directory each stops a PASS.
- **Fixed (Windows):** the gate sets Windows error dialogs off for itself and everything it starts, and proves it on a real child, so a gate started from any terminal can no longer hang on a dialog waiting for a person. Each child runs in a kill-on-close Job Object with a time limit and a stall limit.
- **Fixed (test):** `test_a_missing_file_is_probe_failed` never tested a missing file, because its stand-in ffprobe could not start at all. It stays as the test of that case, documented, beside a new test with a real ffprobe and a real missing file.
- **Not in this phase:** native Windows journeys, real-media journeys, the reviewed feature inventory and the qualification scenarios. Each is reported as NOT RUN, naming the phase that owns it. No application behaviour changed.
- **Added (a pass has to stay true):** reading a passed run later now checks the environment as well as the source, so a pass no longer counts as current after FFmpeg, pytest or the interpreter changes.
- **Verified:** the complete migrated gate passed on `749e6c7`: ordinary 13,435 passed, 65 skipped, 0 failed; guarded 457 + 75 passed; dependency, docs, naming and configuration gates passed. That is the routine scope only, and the owner has not accepted it yet. Earlier full runs are kept: `69f072b` failed 3 tests because one test's disposable checkout did not copy the gate's new session probe, and `98761df` passed but was replaced when the environment check above was added.
- **Fixed (closeout, the gate):** a repeated or empty option now exits 64, as a repeated option did before the migration. `--status --require-current` reads a run as current only where the gate wrote it: a copy, a junction or `..` reads `current: elsewhere` and exits 3, and an artifact reached through a link makes the run INVALID.
- **Fixed (closeout, test isolation):** the suite now fails a run that writes the real settings file or any real runtime data, however the write was made, including by a child process or during import. A write the tripwire refuses inside `tempfile` now ends the call instead of retrying until the group stalled.
- **Fixed (closeout, a crash found behind a warning):** a Tk root closed by code outside a shared-root scope could be collected on a worker thread, which ends the process with `0x80000003` (`Tcl_AsyncDelete`). The `main thread is not in main loop` warning in the guarded group was this, held off by accident. The suite now collects on the main thread before such a worker starts. No application code changed; closing a real window while a worker runs is recorded for Phase 3.
- **Restored:** four test requirements lost in the migration, found by an independent audit of the 38 retired test ids. The earlier statement that nothing was lost was wrong.
- **Verified (closeout):** the complete migrated gate passed on `47ba778`: ordinary 13,472 passed, 65 skipped, 0 failed; guarded 457 + 75 passed; dependency, docs, naming and configuration gates passed. That is the routine scope only, and the owner has not accepted it yet. Where ordinary test scratch lives is still the owner's decision.

### v0.7.2 Phase 1 — Cancel stops now (2026-11-05) — identity 0.7.1 until the v0.7.2 release checkpoint; NOT published, tagged or merged

- **Changed (Cancel):** Cancel stops every file being converted at once, whatever it is doing: asking the voice service for speech, a request in flight, a wait between attempts, a wait for memory, the narration being put together or encoded, and the last step of saving. Nothing unfinished is saved, nothing is asked of the voice service again, and nothing falls back to disk or tries again after Cancel. A file that was already saved before Cancel stays, and so does one in the last instant of being saved when Cancel was pressed, whole. Until now a narration whose speech was complete was allowed to finish and be saved for up to 10 minutes after Cancel.
- **Fixed (Cancel and saving, found by independent review):** Cancel and the last step of saving a file now decide in one step which went first. If Cancel did, the file is not saved and whatever had that name stays. If the save did, the file finishes whole and counts as completed. Cancel never waits for the disk to decide this. Until now a file could appear just after Cancel had answered, with nothing recording that it could.
- **Fixed (Cancel, Qwen3 voices):** a Cancel after a Qwen3 voice finished encoding now stops that file being saved. Until now it did not.
- **Fixed (Cancel, Edge voices, found by independent review):** a request to the voice service can no longer hold up Cancel, whatever it does when cancelled. Stopping one takes about 2¼ s at most, measured at 0.1–1.2 s on the real client against a local server that never answers. It used to wait up to 10 s for a connection that would not close, for as long as a name lookup took, and for ever for a request that ignored the cancellation. A request that had to be abandoned, a request's cleanup that was cut short and a lookup still waiting for Windows are said in the log.
- **Fixed (Cancel with several files, found by the full verification gate):** cancelling many files at once no longer waits for a clean-up of the program's whole memory once per file. Files dropped together now share that clean-up on a thread of its own, so eight take about as long as one: 2.66–2.74 s where the full gate on the previous commit measured 5.27 s against a limit of 5.25 s. The limit has not changed. A connection left behind by a request dropped while another clean-up was running is no longer forgotten. If the program cannot start that thread, usually for lack of memory, Cancel still ends on time, and the log says the connection may stay open until a later clean-up or until the application closes. The full verification gate on this correction has since passed: see "Verified" below.
- **Changed (Cancel, local voices):** the Kokoro and Chatterbox voices' final encode now also stops on Cancel; Qwen3's already did.
- **Changed (log):** a file stopped by Cancel is logged as "stopped (cancelled); nothing unfinished was saved"; a file that never started stays "skipped (cancelled)". Neither is a failure, and Retry Failed offers neither. The Cancel line itself now says what happens instead of "will stop at the next checkpoint".
- **Not changed:** Pause (files already converting finish; nothing new starts until Resume; Cancel works while paused), every voice's audio and output names, Overwrite, publication (a saved file appears whole, once), the memory safety and no-hang guarantees of v0.7.1.
- Measured on HOME-PC under a real memory limit with the real FFmpeg (`files/tests/test_low_memory.py`): Cancel-to-end 0.02–0.28 s across seven scenarios (a stalled encoder, a file assembling in memory with others waiting, a starved queue), nothing published after Cancel, no process or reservation left.
- **Verified:** the complete verification gate passed on `0c1ef43` on Windows 11 (HOME-PC): 13,301 tests passed, 65 skipped, none failed; 532 guarded tests passed; the dependency, documentation, naming and configuration checks passed; the tested files were the same at the end as at the start. Eight files cancelled together took 3.22 s in that run, against the unchanged limit of 5.25 s. No program file changed for this; the gate only had to be started with Windows error dialogs off, because a test's deliberately invalid FFmpeg can otherwise open a dialog that waits for a person. The gate does not cover the real Cancel button in the real window, a real audiobook run, the real Edge service, local voice models, listening or macOS. Not accepted yet: the owner decides.

### v0.7.1 R2 review remediation (2026-11-04) — identity 0.7.1; NOT published, tagged or merged

- **Fixed (hang):** running out of memory while a narration was being put together could stop the whole run for ever, with Cancel doing nothing. That can no longer happen: every FFmpeg on the Edge routes can now be stopped, and has nothing it can block on.
- **Changed (memory):** if memory runs out while a narration is assembled, or while a clip or paragraph is processed, that work now carries on using disk: the same audio, byte for byte, with nothing requested from the voice service again. Only if even that runs out, twice, does that file fail, with a reason saying what to do, where it used to say just `MemoryError:`.
- **Changed (memory):** deciding whether a narration fits now also looks at how much Windows can still commit, and at any Job Object limit, as well as free physical memory.
- **Changed (Cancel):** Cancel now works everywhere. A file with speech still to come stops at once. A finished narration no longer waits its turn: it goes to disk straight away and is saved, or, if that cannot finish (30 seconds without memory or progress, 10 minutes in all), the log says it was not saved.
- **Fixed:** with too little memory for even the disk route, a whole queue now fails together after five minutes, not one file after another, which could take hours.
- **Fixed:** FFmpeg stalling for five minutes now fails that file with a reason, and the files waiting behind it carry on.
- **Fixed:** a full disk is named, with where and how much space is needed, and refused before starting when that can be seen. A run clears working files that an interrupted run of its own left in the output folder, and leaves no empty `.tmp_chunks`.
- **Not changed:** every voice's audio, pauses, endings, headings and output names; Overwrite; publication; worker counts for ordinary files; Kokoro, Chatterbox Turbo and Qwen3-TTS at one file at a time.
- **Known, left for planned hardening:** after a program is killed, its working folder in `%TEMP%` stays, up to about the size of the narration.

### v0.7.1 second independent-review remediation (2026-11-04) — identity 0.7.1; NOT published, tagged or merged

- **Fixed (memory):** a PDF of prose that runs on across pages is now sized as the one long paragraph it becomes. It was sized page by page, so an 80-page PDF could be given eight workers on an 8 GB
  computer; it now gets one, and an ordinary book keeps all eight.
- **Fixed (memory):** a very long paragraph no longer builds up in memory while it is being read aloud: it is written out as it grows, and one enormous clip never comes into memory at all.
- **Fixed (memory):** being the first file to finish no longer lets it be assembled in memory regardless of what is free. If it fits, nothing changes. If other files are assembling, it waits for them. If it
  cannot fit, it is **assembled on disk**: the same audio, byte for byte, using about 32 MB instead of hundreds of MB or more. The log says so. It needs temporary disk space about the size of the uncompressed audio, as the
  encoder always has. Only if under 64 MB stays free for five minutes does that file fail, with a reason; its siblings are untouched and Retry Failed runs it again.
- **Not changed:** every voice's audio, pauses, endings and output names; Overwrite; publication; Kokoro, Chatterbox Turbo and Qwen3-TTS at one file at a time.

### v0.7.1 independent-review remediation (2026-11-03) — identity 0.7.1; NOT published, tagged or merged

- **Changed:** **Overwrite existing outputs without asking** now starts unticked. An existing output is never replaced,
  Retry Failed included, unless you tick the box for that run; the run keeps the choice it started with. Names that
  collide are still numbered when the run is planned. This applies to every voice, Edge and local alike.
- **Fixed (data safety):** a finished MP3 now appears under its final name only once, whole. An Edge file used to be moved from
  the system temp folder with a call that, across drives, copies straight onto the final name (half an MP3 was left when
  that copy died) and that replaced an existing file even with overwriting off; the folder route and the local engines
  encoded straight onto the final name. Now the file is finished, written beside its destination under a private name, flushed to
  disk, and given its name in one operation. With the box unticked, a file that appears at any moment is left alone and
  the item fails with a reason; ticked, the old file stays good until the instant the new one replaces
  it. A locked file is waited for briefly, then named in the failure. A failed attempt removes only what it created: a
  file was being deleted merely because its path matched the plan. An empty result is never published, and on Edge neither
  is a silent, invalid or cut-short one. A later run removes leftovers of a killed run (`.act-tmp-*.part`) once their
  process is gone and they are an hour old.
- **Fixed (memory):** the worker count now comes from each file's real text. It used to count bytes, so inserted pauses were
  invisible (10 tiny paragraphs: 2.5 s estimated, 8.6 s of audio), and PDFs by a fixed 3,000 characters a page (a dense page
  held 15,499). And a measurement now backs the estimate: just before a narration is decoded into memory, its real size
  is checked, and if it would not fit beside what is assembling it waits its turn while other files keep synthesising. So
  a queue of whole volumes runs side by side where it used to fall to one worker, and a machine that could not hold even one
  of those assemblies runs one file at a time. Where free memory cannot be read, a cautious 4 GB is assumed, and the log says so.
- **Fixed (log):** `Worker note:` says what could not be measured whenever it could have mattered, not only when a worker
  was removed.
- **Fixed (failures):** running out of memory, a failed encode and an over-long narration no longer make the folder route
  synthesise the whole file again. Two standalone `batch_convert` runs sharing an output folder can no longer read each
  other's audio or remove each other's working files.
- **Documented, not changed:** a last heading with no text after it is not spoken (inherited); changing what a heading
  narrates is the owner's decision.
- **Verified:** finished MP3 bytes, decoded audio and every request's text are identical to the code before this entry on
  18 outputs; `verify.py` RESULT: PASS on `c64140a` (13006 passed, 65 skipped). Not exercised: a real second drive,
  exFAT or network drives. Not listened to.

### v0.7.1 Edge multi-file workers (2026-11-03) — identity 0.7.1; NOT published, tagged or merged

- **Changed:** files added directly with **Add Files** now convert side by side with the Edge voices, as folder
  imports already did — direct TXT and PDF, folder and mixed queues, every Edge voice. v0.7.0 converted a queue of
  directly added files one at a time whatever **File workers** said (`Requested workers: 8 | Effective workers: 1`):
  the engine wrote its scratch files into the current folder, so each conversion switched the whole program's folder
  and a lock let only one run. Each conversion now has its own private work folder and nothing changes the current
  folder.
- **Changed:** **File workers** accepts 1–100. The number that actually runs is the smallest of: the request, the
  files queued, the engine's limit (Kokoro, Chatterbox Turbo and Qwen3-TTS stay at one file at a time), the Edge
  service ceiling (32 files at once), the computer's logical processors, and what free memory allows for the largest
  queued files while they are assembled (measured: about 150 kB per second of narration; where free memory cannot be
  read it is not guessed). The Detailed log says `Requested workers: N | Effective workers: M` and, when M is lower,
  which limit applied. The standalone `batch_convert.py` uses the same rule.
- **Fixed:** a heading written as `# blank` or `# Title` was silently not spoken, and of two headings in a row only
  the second was spoken (the M4B chapter titles then went out of step). A heading is now spoken because the author
  wrote it, whatever it says; consecutive headings are spoken together ("Part One. Chapter 1") and each chapter keeps
  one M4B title. The word "blank" in ordinary text was never removed and still is not; nothing filters words. A
  chapter without a heading now logs "Chapter name: none (no heading in the source here, so no chapter title is
  spoken)".
- **Fixed (hazards that real concurrency exposes):** PDF text is extracted by one file at a time (PyMuPDF is not
  thread-safe; folder workers already used it side by side); the sentence splitter is built once; the ETA divides by
  the files running at once (it overstated N-fold); log lines from different files no longer cut into each other and
  each carries `[<file>]`; each file's progress bar stays on one line (simultaneous bars printed cursor codes and empty
  lines); a failed Edge request waits 1–3 s, then 2–6 s, with jitter, instead of a fixed 3 s, so files do not retry
  in lock-step (still 3 attempts).
- **Verified:** real Edge runs on HOME-PC with 1, 2, 4 and 8 workers (that many files in flight at once), 100
  requested → 16 (this computer's logical processors), mixed direct + folder, a direct PDF, Cancel, Retry Failed,
  same-named files, all five Edge voices, 16- and 32-file service bursts (no retries) and a real-GUI run; every
  output's words checked against its source. Listening samples, not yet listened to by the owner:
  `files/test-for-manual-listen-elmatthe/ACT-v0.7.1-edge-concurrency/` (ignored). `verify.py` RESULT: PASS on
  `48f6667` (12,779 passed, 65 skipped).

## [0.7.0] - 2026-11-02

Published as the GitHub release **v0.7.0** (tag `v0.7.0` = `c0896d8`, asset `AudiobookTool-Windows-v0.7.0.zip`).
The "NOT published, tagged or merged" notes in the entries below record each entry's state when it was written.

### v0.7.0 GUI-acceptance defect remediation D1–D4 (2026-11-01) — identity 0.7.0; NOT published, tagged or merged

- **Fixed (D1):** a copied app folder no longer runs on the original's Python and FFmpeg. The launcher's check sees an
  environment whose base Python is another copy's own (`pyvenv.cfg` `home`) and rebuilds it on this copy's Python from
  its own package store (offline); an FFmpeg recorded by another copy (a copied `ffmpeg-state.json`) is never this
  copy's and its own is proved instead. Each copy keeps working when the other is moved or deleted.
- **Fixed (D2):** a stray file in the package store (for example another build named like a locked release) can no
  longer make every repair fail. Before each install only the lock's exact files with their exact SHA-256 stay in
  `files/runtime-data/python-packages`; anything else is moved to `python-packages-quarantine` beside it (a damaged
  locked file is then fetched again, or the repair fails closed offline). `--require-hashes` is unchanged.
- **Fixed (D3):** a damaged app environment (a package's files gone, its metadata left) is detected at launch (each
  package's `__init__`, top-level modules and native libraries against its own `RECORD`; about 10–15 ms cached) and
  rebuilt from the package store, keeping the Qwen3 engine. Preferences & Data has **Repair App Environment…**, which
  schedules that repair for the next start (it removes nothing and works while the Qwen3 engine is installed). A
  repair that fails on an environment that still runs opens the app with a notice instead of no app. Kokoro no longer
  tells the user to `pip install`.
- **Fixed (D4):** M4B Maker chapter marks sit exactly on the chapter boundaries, so M4B Converter's "Split by chapter"
  no longer cuts the last syllable of each chapter onto the next. Removed the 250 ms lead-in; FAST no longer pulls the
  AAC encoder's 1024 priming samples into the timeline (`-avoid_negative_ts make_zero`), Safe rebuilds its timestamps
  the same way, and FAST chapter starts come from each source's decoded length (an MP3 without a Xing header misreports
  its duration).
- **Verified:** `verify.py` PASS on `d53a036` (12,685 passed). Windows RC `dist/AudiobookTool-Windows-v0.7.0.zip`
  (SHA-256 `bb301f6a…112b`) qualified from a fresh extract and re-accepted through its GUI: Maker → Converter round
  trip, a copied folder, damaged and stray-file repairs offline, Repair App Environment with the Qwen3 engine kept
  byte-identical. The previous candidate is kept as `AudiobookTool-Windows-v0.7.0-3a91056.zip`.

### v0.7.0 portability and reproducibility remediation (2026-10-31) — identity 0.7.0; NOT published, tagged or merged

- **Changed:** the app environment installs only from `scripts/requirements-lock-windows-py312.txt`: all 170 packages
  (transitive ones included) at the versions the qualified portable install proved, each with the SHA-256 of the one
  artifact pip installs on Windows x86-64 CPython 3.12. Setup, repair and the Kokoro/Chatterbox self-heals fetch every
  artifact into `files/runtime-data/python-packages` (hash-checked) and install from there alone, so a repair works
  offline and no resolver can bring in a newer build. pip itself is no longer upgraded.
- **Fixed:** pip's cache no longer lands in the user's profile (`%LOCALAPPDATA%\pip\cache`): every ACT pip command runs
  with no inherited pip settings or configuration file and its cache inside the app's folder.
- **Fixed:** the Edge voices' English sentence data (NLTK `punkt_tab`) is no longer downloaded silently into the user's
  profile at the start of every narration. It is pinned (nltk_data commit, size, SHA-256), kept in
  `files/runtime-data/nltk_data` (the only folder NLTK reads), fetched by first-run setup or — if missing — only after
  a Yes when an Edge narration starts; a missing copy gives a message saying what to do. Kokoro, Chatterbox and Qwen3
  never need it.
- **Fixed:** starting `Setup_and_Run-audiobook-creation-tool.bat` from a PowerShell 7 window no longer breaks stage 0
  (Windows PowerShell 5.1 could not load `Get-FileHash` from the inherited module path and stopped after downloading
  Python).
- **Changed:** a narration that stops while still sounding (Qwen3 Aiden) is now flagged in the run log for listening
  ("please listen to the ending"); nothing is added to or removed from the audio.
- **Changed:** `verify.py`'s deps gate also checks the lock against `requirements.txt`.
- **Fixed:** Clear Downloaded Data can clear the Python environment on a computer whose only Python is the app's
  own (`files\runtime-data\python`): the post-exit cleanup refused every interpreter inside the app's folder.
- **Fixed:** a package that will not import because a dependency's files are gone (its metadata left behind) is
  repaired by reinstalling the whole lock from the verified package store, offline when the store is complete.

### v0.7.0 portable Windows setup — the app's own Python and FFmpeg, nothing installed on the computer (2026-10-30) — identity 0.7.0; NOT published, tagged or merged

- **Changed:** Windows setup no longer installs Python on the computer (the python.org per-user installer and the winget
  fallback are gone). It uses the app's own Python in `files\runtime-data\python`; on a first run it asks, then
  downloads the pinned standalone CPython 3.12.15 build (python-build-standalone `20261009`, about 46 MB, checked against
  a fixed SHA-256), unpacks it with Windows' own `tar.exe` inside the app's folder and proves it by running it (ssl,
  venv, pip, Tk). No installer, no administrator rights, no PATH or registry change.
- **Changed:** Windows FFmpeg repair no longer runs winget; when no working FFmpeg is found it uses the app's own
  pinned Gyan 9.0.1 build in `files\bin` (checked against a fixed SHA-256). A working FFmpeg already on the computer is
  still used as it is.
- **Note:** the app's own Python lives beside `.venv`, not inside it, because a repair renames `.venv` aside while that
  Python is running the repair; there it also survives a deleted `.venv`.

### v0.7.0 release completion — recovery and ending fixes found by real runs, and a complete verify gate (2026-10-30) — identity 0.7.0; NOT published, tagged or merged

- **Fixed:** Edge narrations (direct route) cut the end of the book's final sound. Every Edge chunk's padding is trimmed at
  the last part louder than -58 dBFS, which also removed the quieter decay of the final word (a plosive's release
  measured 0 ms of trailing silence on all five Edge voices). The book's last chunk now keeps its ending for the shared
  final-tail policy, which keeps every sound down to -70 dBFS and then about 150 ms; every earlier pause is unchanged.
- **Fixed:** after the app's environment was rebuilt (a repair, or a lost `.venv`), Kokoro asked to download its English
  pronunciation model again. The verified 12.8 MB wheel is now kept under `files/runtime-data/models/spacy/` after
  install and reinstalled offline (no index, hash enforced) whenever the environment is rebuilt; nothing is downloaded.
- **Fixed:** a repair interrupted after its new environment's Python could already run left the old environment, and any
  Qwen3 engine in it, set aside: the next launch called the half-built environment healthy and used it. The launcher now
  finishes an unfinished repair first (the existing recovery decides which environment survives, engine included).
- **Changed (developer):** `verify.py` has a sixth gate, `guarded`, which runs the eight suites that need
  `files/tests/guarded_pytest.py` (listed in `files/tests/guarded_groups.json`) under process-lifetime write, process and
  network protection; the ordinary pytest gate leaves exactly those out. NumPy's Windows-unavailable `lscpu` probe is
  pinned as the expected refused-before-launch fallback, so it is no longer an "unexpected process".
- **Tests:** a closed panel during Install & Continue and a second Create during a pending install start nothing; the
  macOS launcher checks use a bash that actually runs (Git for Windows' before the WSL stub).

### v0.7.0 release candidate — Windows only (2026-10-30) — identity 0.7.0; NOT published, tagged or merged

- **Changed:** the application identity is 0.7.0 (`version.py`, `config.toml`), declared and packaged for Windows only;
  macOS stays at v0.6.6 until it is qualified on a Mac. The README describes the four setup choices, Install & Continue
  and the Windows-only scope, and its voice-preview links are pinned to commit `f7963c31` (same 28 WAVs).
- **Fixed:** a freshly set-up computer could not start Kokoro (32 transitive packages had drifted to new releases and
  Smart App Control refused spaCy 3.8.18's new unsigned module; they are now pinned to HOME-PC's proven versions), and
  a freshly installed engine failed its first start while Smart App Control was still checking its new files (the
  proofs now wait for Windows, at most 8 tries, and report a lasting refusal).
- **Added:** setup refuses, before installing anything, a copy extracted too deep for Windows' path limits, and says to
  move the folder somewhere shorter.
- Qualified from a release-scope ZIP extracted to a new folder: real base setup, real install of all four optional
  components (14.8 GB) and real narration with Edge, Kokoro, Chatterbox Turbo, Qwen3 Aiden/Ryan and all six Qwen3
  clones on HOME-PC. Clean-PC, owner listening and display-scaling checks remain open (see Handoff).

### v0.7.0 release installer — the four optional voices install for real, from setup or from Create (2026-10-30) — identity stays 0.6.6 until the release candidate

- **Added:** first-run setup offers four independent choices — Kokoro (checked), Chatterbox Turbo, Qwen3 CustomVoice (Aiden,
  Ryan) and Qwen3 Cloned Voices (the six bundled voices) — with their sizes. **Begin Setup** builds the app only; once it is
  built, a review screen shows exactly what each choice downloads, reuses and occupies, and nothing is downloaded until
  **Install Selected Components** is pressed. Skip or Cancel keeps everything that already works, and nothing retries by itself.
- **Added:** Install & Continue. Pressing Create with a voice whose models are not installed shows the same review screen; after
  the install is checked, that same conversion (same files, settings and voice) starts once. Skip or Cancel starts nothing and
  creates nothing.
- **Changed:** the Qwen3 engine's 89 packages are downloaded by the app as the exact reviewed files (each checked by size and
  SHA-256; sox is the accepted wheel at its pinned supply commit), then installed with no internet access for pip. The engine
  still lives only at `.venv/engines/qwen3`.
- **Security:** an install can never download more than the plan you confirmed, and a confirmation for models only can never
  rebuild the Qwen3 engine (closes the three P05B Stage 3 review findings).
- **Removed:** setup's old pre-download and warm-up steps, which fetched Kokoro and Chatterbox at whatever upstream "main" was.

### v0.7.0 P05B Stage 2 — optional voices can be installed under consent, from approved sources only (2026-10-25) — not released; identity stays 0.6.6

- **Added (internal, no screen yet):** the optional-setup worker can now download and install Kokoro, Chatterbox Turbo, Kokoro's English
  pronunciation model and the Qwen3 voices — only after a confirmation of the exact plan, only the approved files (each checked by size
  and SHA-256), and only from the exact approved versions. Files already on the computer are checked and kept; an interrupted download
  resumes after a new confirmation.
- **Changed:** Kokoro and Chatterbox now load only their approved, verified local files and never download anything on first use; a
  missing or damaged file is reported ("Nothing was downloaded") instead. Chatterbox no longer needs the 1.06 GB file Turbo never used.
- No download or install was run by this change; the first-run setup and the in-app Install & Continue are unchanged (P06).

### v0.7.0 P05B Stage 1 — optional voice setup made safe for consented installs (2026-10-25) — not released; identity stays 0.6.6

- **Changed (internal):** a confirmation now covers exactly the plan that was shown — what would be fetched, from which exact source,
  at what size, as an install or a repair — and is used once. A plan that changed, grew, moved source or needs a repair asks again.
- **Changed (internal):** the setup worker and anything it starts are always stopped together on Cancel or time-out, and its answer is
  written completely or not at all; a success is only reported once the voices are proved to work afterwards.
- Nothing is downloaded or installed by this change; optional-voice installation stays disabled (P05B Stage 2).

### v0.7.0 P05A — optional voice setup planning (2026-10-25) — not released; identity stays 0.6.6

- **Added (internal, nothing visible yet):** one planner for the four optional voice choices (Kokoro, Chatterbox Turbo, Qwen3
  CustomVoice, Qwen3 Cloned Voices / Base). Before anything is downloaded it says what is ready, missing, damaged, unsupported, busy,
  blocked by a bad bundled recording or transcript, or not yet proved, and what each choice would download, reuse, copy and occupy. The
  app's own packages are shown separately, and every size says whether it is exact, from a manifest, approximate or unknown.
- **Added (internal):** the optional-setup worker and its versioned request/result protocol. It runs only in the app's own Python 3.12
  environment and, in this build, plans but never installs.
- Nothing is downloaded or installed by this change; the first-run setup and the Qwen3 install dialog are unchanged (P05B/P06).

### v0.7.0 P04C — Qwen3 voice engine moves inside the app environment (2026-10-25) — not released; identity stays 0.6.6

- **Changed:** a new or rebuilt Qwen3 voice engine is installed at `.venv/engines/qwen3`, built by the verified base Python 3.12 rather than
  the app's own interpreter. A copy that already has the older `.venv-qwen3` keeps using it until that engine needs rebuilding; the app
  never changes or deletes `.venv-qwen3`.
- **Changed:** the Qwen3 install dialog says which engine is in use and where a new one goes, and no longer suggests deleting folders.
- **Fixed:** repairing the app's own dependencies and first-run setup now refuse, changing nothing, while a Qwen3 install, conversion or
  worker is using the engine, and a first install and a repair can no longer overlap. Clear Downloaded Data leaves the app environment
  and the downloaded models alone, and says so, while the engine is busy, and never removes the engine with the app's dependencies.
- **Fixed:** an engine inside `.venv`, and repair leftovers such as `.venv.replaced*` / `.venv.discarded*`, can never be packaged or staged.
- Not yet qualified on a clean PC, a standard user account, other GPUs or with long paths disabled (release qualification, P10).

### v0.6.7 closure corrections (2026-10-21) — not released; identity stays 0.6.6

Four findings from the second independent Codex closure audit (`ACT67-CLR-001` to `-004`). Nothing here changes narration, voices, previews,
transcripts, settings, logs or release archives.

#### Fixed
- **A Kokoro check that could not finish is no longer reported as healthy (ACT67-CLR-001).** If the Kokoro dependency proof times out or cannot be
  started, the launcher now says the voices "could not be verified this time" instead of treating that as proof they work. Nothing is reinstalled
  or downloaded because of it and nothing is cached; the check repeats on the next launch, and a completed check replaces the unverified state. A
  repair whose own proof cannot finish is reported the same way and is not counted as a failed repair.
- **The Qwen3 one-model-at-a-time guard no longer quietly shrinks to one Windows session (ACT67-CLR-002).** If Windows will not create or open the
  computer-wide lock, Qwen3 is now refused with a plain explanation instead of falling back to a lock that other Windows users cannot see. A lock
  that another user's copy genuinely holds still reports "another copy is running"; a permission refusal or a lock Windows could not create each
  get their own message. No model is loaded and no worker is started without the computer-wide lock.
- **Every GUI capability check now gives up after 30 seconds (ACT67-CLR-003).** The check run on each ordinary launch allowed 120 seconds for a
  hung Tk; it now uses the same 30-second bound as the base-Python check and the Windows stage-0 script. The timed-out interpreter is ended.

#### Tests
- **Running `test_launcher_smoke.py` on its own can no longer touch your real logs or settings (ACT67-CLR-004; pre-existing, test-only).** The
  test session now redirects the application's log folder and settings file to scratch before anything can start the logger, however the tests are
  selected, and the first smoke test no longer snapshots and rewrites the real `settings.json`. A new test proves this in a throwaway copy of the
  checkout (45 seeded logs, existing and absent settings). `test_the_data_locations_did_not_move` now reads the production paths from the module's
  own source, because the live values are redirected under test.

### v0.6.7 Codex audit remediation (2026-10-21) — not released; identity stays 0.6.6

#### Fixed
- **The release packager no longer deletes an existing archive (ACT67-AUD-001).** `scripts/shared/release.py` refuses to build if either platform's
  `dist/AudiobookTool-<OS>-v<VERSION>.zip` already exists, writes both into a fresh staging folder inside `dist/`, checks every member against its source,
  and publishes by hard link, which never replaces a file that appeared meanwhile. A run publishes both archives or neither.
- **Kokoro is only reported healthy when its voices can actually start (ACT67-AUD-002).** The launch check used to confirm only that the packages were
  present, and said "ok" while Windows was blocking a library every Kokoro voice needs. Setup, repair and launch now prove the whole synthesis chain offline
  (without downloading anything), record the result, and re-prove after a real synthesis fails. Repairs install from `scripts/requirements.txt`, so the
  qualified `srsly==2.5.3` applies; a repair that cannot help is not repeated on every launch; the notice names the real cause (for example Windows
  Application Control) instead of "Python may be 3.13+".
- **Two copies of the app can no longer load Qwen3 models at the same time (ACT67-AUD-003).** Each copy's lock file lived in its own folder. A
  machine-wide Windows lock now covers every Qwen3 conversion, transcription and model check across all copies (and Windows users); it never waits and is
  released automatically if the app crashes.
- **Setup now checks that Tk can really open a window (ACT67-AUD-006).** The checks started Tcl only, so a Python with a broken Tk was accepted and the
  app then failed to open. Stage 0, interpreter selection and the environment check now initialise a real (hidden) Tk window, with a time limit.
- **A clone approval that cannot be saved now says so (ACT67-AUD-007).** A read-only, locked or full disk used to make "Approve" silently do nothing. The
  dialog now explains the problem, keeps the edited text and ticks, never claims success first, and a retry works; existing approvals stay untouched.
- **The README's voice-gallery link works from the downloaded ZIP (ACT67-AUD-011)**: it is now an absolute GitHub link (on the feature branch until the
  owner's merge decision, like the preview downloads).

#### Changed
- The TTS Audiobook description in the launcher names all four engines (Edge TTS, Kokoro, Chatterbox, Qwen3).
- The release ZIPs no longer include three developer-only scripts (`scripts/verify.py`, `scripts/shared/release.py`, `scripts/tts/generate_voice_samples.py`)
  (ACT67-AUD-012). All six tools, the Qwen3 worker and their data still ship.
- The README states that the optional Qwen3 voices need Python 3.12 exactly; on a Python 3.11 app environment everything else works.

#### Not changed / still open
- Owner/manual release gates remain OPEN: clean standard-user Windows setup (AUD-004), redistribution authority for the six bundled reference recordings
  (AUD-005), an exact final release-candidate ZIP (AUD-008), real network download of the Qwen3 models and recognizer (AUD-009). The main environment's
  transitive packages and the Chatterbox model revision are not fully pinned (AUD-010, documented).
- Qwen3 speed: investigated only (`files/dev-work/qwen3-performance/`, local); no production inference change.

### v0.6.7 final implementation and Windows qualification (2026-10-20) — not released; identity stays 0.6.6

#### Added
- **Set up cloned voices, in the app.** TTS Audiobook → "Install / repair Qwen3 voices..." → "Set up cloned voices...": after the user confirms the size, the app installs a pinned
  speech recognizer (Whisper small.en, about 971 MB), drafts each clone's reference transcript on this computer, and the user plays each recording, corrects the text and ticks
  "I listened" before approving. Approval is bound to the recording's SHA-256; an approved transcript is never overwritten by a new draft. No command line, no JSON editing,
  no review page, no external service. Transcripts stay in the ignored `files/runtime-data/qwen3/` and never reach git or a release archive.
- **Windows stage 0 (`scripts/shared/bootstrap_host.ps1`).** When no usable Python 3.11/3.12 is found, setup asks before installing the pinned python.org 3.12.10 installer for the
  current user only; the download is checked for size, SHA-256 and the Python Software Foundation signature before it runs, and is reused when still valid. winget is only a
  fallback, PATH and file associations are not changed, and declining exits cleanly.

#### Changed
- **The six reference recordings are named after their Chatterbox labels** (`files/Chatterbox-Voice-Uploads/Chatterbox - Female 1.wav` ... `Chatterbox - Male 4.wav`); the bytes
  and hashes are unchanged and the Qwen3 clones use the same six files.
- **B2: `scripts/mp3_tools/` is split by tool** into `scripts/mp3/` (MP3 Tool), `scripts/m4b/` (shared M4B code, with `converter/`, `maker/` and `metadata/`) and
  `scripts/artwork/` (Cover Image and shared artwork code). Modules, classes and behaviour are unchanged; imports, launcher entries, tests, guards and READMEs follow the move.
- The voice preview gallery records the owner's listening approval of all 28 samples and points to the in-app clone set-up; the repository README links to it.

#### Fixed
- **Qwen3 - Ryan could laugh or run on after a short heading.** A Qwen3 chunk whose audio is far longer than its words allow (over 1.0 s + 0.6 s per word) is re-rendered with the
  next seed, at most twice, keeping the shortest take if every attempt runs long.
- **Qwen3 crashed when the GPU was hidden with an empty `CUDA_VISIBLE_DEVICES`.** The worker now uses the GPU only when a CUDA device actually exists, otherwise the CPU.
- **The clone set-up dialog no longer runs off a 768-pixel screen**: the six rows scroll inside the window.
- **Kokoro voices failed on a fresh Windows install with Smart App Control on.** A new install picked up srsly 2.5.4 (a library Kokoro uses underneath), whose compiled part
  Windows refused to load ("An Application Control policy has blocked this file"). `srsly` is now pinned to 2.5.3, the build every Kokoro voice was qualified with; an existing
  install picks the pin up on its next launch.

#### Verified (HOME-PC, Windows 11, RTX 5070)
- S5: all 28 voices selected, dispatched and narrated through the real TTS panel (MP3, 24 kHz mono); read-back word error rate at most 0.156, every miss a recognizer spelling;
  a 320-second Qwen3 clone narration; PDF and TXT, single file and folder; mid-run cancellation of each engine leaves no output; Qwen3 and Chatterbox on the CPU.
- Release ZIP built by `scripts/shared/release.py`, extracted into a new folder and set up from it (first run, relaunch, a broken environment repaired with settings kept, the Qwen3
  install, 5,126 tool tests, Edge and Kokoro narration): see Handoff for the results and what stays unproven.

### Changed — Qwen3 cloned voices: calmer, more even narration, and a clean start (v0.6.7, 2026-10-20)

- The six cloned Qwen3 voices now narrate with less pitch, intensity and pace variation (lower sampling temperatures than the model's defaults); the other voices are unchanged.
- A cloned voice no longer opens with a stray leftover sound (or loses its first word) when its reference recording ends mid-sound: a short stretch of silence is added after the reference copy that the voice is cloned from.
  The recordings themselves are untouched.
- `files/voice-previews/` now holds all 28 previews, including the six cloned Qwen3 voices, each linked directly in its README. The clone previews were made with provisional (not yet owner-approved) reference
  transcripts and are for listening review only; the application still requires an approved transcript before it will use a clone.

### Added — Voice previews for the Edge and Chatterbox voices (v0.6.7, 2026-10-20)

- `files/voice-previews/` now holds **22 of 28** ten-second previews: the 11 already there plus the five Edge voices and the six Chatterbox voices, each made by that voice's own engine
  reading the same sentence. The owner authorized publishing previews for all 28 voices (a publication decision, not a verified third-party license finding), which replaces the earlier
  rule that kept the Edge, Chatterbox and Qwen3-clone previews unpublished.
- The six Qwen3 clone previews are **pending**, not blocked: each needs an owner-approved transcript of its reference recording, which has not been approved yet. The set is not called
  complete until all 28 exist. Transcripts and reference recordings are still never committed. Previews are repository documentation only and are not in the release archives.
- The preview tool tracks authorization, generation and pending reasons separately, and checks every file (length, clipping, silence, hash) before it is published.

### Changed — Edge voices: clearer, faster failures when Microsoft's service is unavailable (v0.6.7 final hardening, 2026-10-20)

- When Microsoft's online Edge Read Aloud service refuses or cannot be reached, a file that cannot be converted now says why in plain words and what to try (check the
  connection and the PC's date and time, use Retry Failed, report it if it keeps happening) instead of showing only "could not be converted". Nothing is promised that
  reinstalling or updating cannot deliver, and Setup_and_Run is suggested only if the installed Edge component is not the version ACT expects.
- A refusal that retrying cannot cure (HTTP 401/403, or a service that has changed) is no longer retried: it fails after one request instead of three (single file) or
  fifteen with about 100 seconds of waiting (folder). Temporary network problems keep exactly the same bounded retries as before. Cancelling during a retry wait now stops at once.
- Logs no longer contain the service's handshake tokens or the sentence being read. Voices, text, pauses, output and the pinned `edge-tts 7.3.1` are unchanged.

### Added — Chatterbox colon evaluation evidence (v0.6.7 Plan 01B checkpoint A6, 2026-10-20)

- Development only, no change to narration: the Chatterbox colon handling (times, ratios, web addresses and paths keep their colon; a short pause after an
  ordinary colon) was re-examined now that text preparation is on and is kept as it is, with the evidence recorded (`files/dev-tools/chatterbox_colon_matrix.py`,
  `files/tests/test_chatterbox_colon_a6.py`). The owner's G2 listening of all four engines passed.

### Changed — Speech preparation is on: numbers, money, dates, times and titles are read as written (v0.6.7 Plan 01B checkpoint A5, 2026-10-20)

- Text is now prepared for every voice before it is spoken: `$12.50` becomes "twelve dollars fifty cents", `1/2 cup` "one half cup", `pages 12-15` "pages twelve
  to fifteen", `Mr.` "Mister", `Chapter IV` "Chapter four", and so on. Only the classes the owner approved by ear (gate G1, 60 comparisons) are prepared; four are
  left to the voice's own reading because the owner preferred it: Edge currency, fractions and symbols, and Kokoro currency. Anything ambiguous (`1999 was`, `John 3:16`,
  `24/7`) is still read exactly as written, as are web addresses, file paths and `Title:`/`Author:` lines. Text without numbers or abbreviations is unchanged.
- `[tts] speech_prep = "off"` in `config.toml` restores the previous behaviour exactly.

### Fixed — Edge voices failed with HTTP 403 (edge-tts 7.2.8 -> 7.3.1, 2026-10-20)

- Every Edge voice had stopped working: Microsoft's read-aloud service began refusing the pinned `edge-tts` 7.2.8 at the connection handshake (HTTP 403;
  upstream issue rany2/edge-tts #490, fixed in 7.3.0). The pin is now 7.3.1. Existing installations pick it up on their next launch through `Setup_and_Run`,
  which reconciles a changed requirements file; only `edge-tts` changes. All five Edge voices were checked with real audio through the app's own Edge path.
- Development only: the A4 listening corpus is complete (120 clips, 19.7 min) and is also exported to one flat, numbered folder with its own review sheet.

### Added — Speech-preparation A/B listening tool (v0.6.7 Plan 01B checkpoint A4, 2026-10-20)

- Development only, no application change: `files/dev-tools/speech_ab.py` builds the bounded A/B listening corpus (one class per snippet, one voice per engine) through
  the app's own engine entry points, with blind clip names, a separate key, mechanical checks, an advisory Whisper read-back and a Kokoro pronunciation probe.

### Added — Speech preparation wired into every TTS route, switched off (v0.6.7 Plan 01B checkpoint A3, 2026-10-20)

- No audible change: the new developer setting `[tts] speech_prep` in `config.toml` defaults to `off`, and with `off` every route (Edge direct, Edge folder, Kokoro,
  Chatterbox, Qwen3) makes exactly the calls it made before. With `v1` a run takes one snapshot of the pronunciation glossary and the per-engine mode table when it starts
  and keeps it for the whole run, including Retry Failed; every mode cell ships as `native`, so text still reaches each engine unchanged until reviewed cells are enabled.
- Optional owner files, never required and never able to fail a run: `files/runtime-data/speech/glossary.user.json` and `modes.user.json`. A broken file is ignored with
  a line in the run's Details.

### Added — Speech-preparation normalizer core, not yet wired (v0.6.7 Plan 01B checkpoint A2, 2026-10-20)

- Development only, no audible change: nothing calls it yet. New `tts/speech/` modules (`normalize`, `classes`, `numbers_en`, `glossary`, `integrity`, `report`) and data
  tables (`data/lexicon.json`, `data/units.json`, an empty `data/glossary.default.json`): deterministic English normalization of numbers, money, years, times, ratios, dates,
  ranges, fractions, units, titles, Roman numerals and two symbols; context cues required where a reading is ambiguous, otherwise the token is left exactly as written and
  reported; URLs, e-mail addresses, paths, `Title:`/`Author:` lines, `#` markers and non-English lines are protected. A data-only pronunciation glossary (ships empty).
  Ruleset version 1. Standard library only; no new dependency.

### Changed — Shared source-structure loader for the speech engines (v0.6.7 Plan 01B checkpoint A1, 2026-10-20)

- Development only, no audible change: Kokoro, Chatterbox and Qwen3 now read a source `.txt` (BOM handling, `Title:`/`Author:` lines, `#` headings) through one shared
  module, `tts/speech/document.py`, instead of three private copies. Edge direct shares only the file decode; Edge folder shares only its decode. Each engine keeps its existing
  heading and metadata behaviour; the text each route hands to its engine is byte-identical to before.

### Fixed — Leftover-folder notice and production-guard scope (v0.6.7 Plan 01B corrective checkpoint after B1, 2026-10-19)

- The notice about a leftover `scripts/Universal/` is now shown where a person can see it: one line in the launcher window's status bar, once per launch, never a dialog.
  It was previously only a log line, which a Windows launch (no console) never displays. It now also covers folders that hold only `.json` files; bytecode-only leftovers
  stay silent, and the folder is never touched.
- Development only: the production-module guards read the application source through one shared helper, so an untracked local script under `scripts/` can no longer fail
  an architecture or security guard on one machine; every application module (nested packages included) is still scanned, and a bounded test pins that.

### Changed — Application packages lifted from `scripts/Universal/` to `scripts/` (v0.6.7 Plan 01B checkpoint B1, 2026-10-19)

- **Layout only; no behaviour change.** `launcher.py`, `shared/`, `tts/` and `mp3_tools/` now sit directly under `scripts/`, which is the
  application's import root. The package names (`shared`, `tts`, `mp3_tools`) are unchanged, so no `import` statement changed. The empty
  `scripts/MacOS/` and `scripts/Windows/` placeholders and the `Universal/` level are gone. Git history follows the files.
- Depth-dependent root lookups were shortened by one level (paths, bootstrap, FFmpeg modules, cleanup, release packaging, the Qwen3 and
  Chatterbox fallbacks), and the launchers, `config.toml`'s `entry_point`, `verify.py` and the dev tools follow the new location.
- A leftover `scripts/Universal/` from extracting a new release over an old install is reported by a one-line warning at launch when it still
  holds Python or JSON files (since the corrective checkpoint it is shown once in the launcher's status bar). It is never deleted, moved or edited by the app; a folder holding only bytecode caches stays silent.
- Short module maps: `scripts/README.md`, `scripts/shared/README.md`, `scripts/tts/README.md`, `scripts/mp3_tools/README.md`.
- Development only: A0 characterization baselines for the five TTS text routes (`files/dev-tools/speech_characterization.py`,
  `files/tests/golden/speech/`) were captured from the original code before the move and still match byte for byte; layout canaries
  (`files/tests/test_layout_canary.py`) guard the new layout. Application identity stays 0.6.6; nothing is released.

### Added — Qwen3-TTS voices: eight optional local voices, Windows first (v0.6.7 CP6, 2026-10-19)

- **Eight new voices** in a separate group of the TTS voice list: **Qwen3 - Aiden**, **Qwen3 - Ryan** (preset voices) and **Qwen3 -
  Female 1**, **Female 2**, **Male 1**, **Male 2**, **Male 3**, **Male 4** (cloned from the six bundled reference recordings). The list is
  now 28 voices. Nothing earlier changes: every existing voice keeps its label, order, settings and the default voice.
- **Optional install, never automatic.** Choosing a Qwen3 voice shows **Install / repair Qwen3 voices...**. CustomVoice (Aiden, Ryan; about
  4.5 GB) and Base (the six cloned voices; about 4.5 GB) install independently or together (about 8.4 GB, the files they share downloaded
  once), after a confirmation that states the sizes. The first install also builds a separate Python environment for the voice engine
  (about 3.1 GB to download, 5.3 GB on disk) so the app's own libraries are untouched. Everything is stored inside the app folder; the same
  dialog checks every file and the engine, shows what a repair would download, and repairs only what is wrong. Nothing downloads on launch.
- **Runs on an NVIDIA GPU when one is found, otherwise on the CPU,** and says which. Measured on the development machine: the RTX 5070 about
  1.4 times as long as the audio (5.6 GB of video memory), a Ryzen 7 9800X3D CPU about 2.2 times (5.6 GB of memory). Other computers will
  differ. One Qwen3 file at a time; Cancel stops the worker within seconds and leaves no process, partial file or damaged output behind.
- **Existing pause settings apply** (the voice's paragraph pause between chunks, its end pause once, one final MP3 encode).
- **Cloned voices need an approved reference transcript** that is read from a local file and is not part of the app; until one is provided
  they show "Setup required". They are unavailable in public builds until the maintainer confirms redistribution rights.
- **Windows only for now:** on macOS the eight voices are listed as not yet available and every other voice works as before.
- **Voice previews:** a permanent preview set (about 10 seconds each) with a per-voice rights record; 11 of 28 are available (the nine Kokoro
  voices, Qwen3 Aiden and Ryan) and 17 are blocked pending rights decisions (see `files/voice-previews/`).

### Changed — Qwen3 follow-ups (v0.6.7 CP6)

- Preferences & Data: the "Downloaded voice models" description now says the Qwen3 models must be installed again from the TTS panel.
- Release packaging names the Qwen3 environment folder among its exclusions; the new modules, the pinned model list and the hash-pinned
  requirements ship, the environment, models, install record and any transcript never do.

### Added — Four more Kokoro voices (v0.6.7 voice roster, 2026-10-19)

- The voice list gains **Kokoro Male - Fenrir (en-US)**, **Kokoro Male - Puck (en-US)**, **Kokoro Male - Onyx (en-US)**
  and **Kokoro Male - Daniel (en-UK)**, listed with the other Kokoro voices (nine in total). They use the existing local
  Kokoro engine, the neutral 1.0 speed and the same pause defaults as the other Kokoro voices; each voice's small
  (about 0.5 MB) file downloads on first use, like the existing voices. Existing voices, their labels, their order
  relative to each other, saved settings and the default voice are unchanged.
- The four voices were heard and approved by the maintainer in the v0.6.7 listening comparison before being added.

### Fixed — MP3 embedded segment metadata (2026-10-01)

- Write ID3 Tags now accepts byte-concatenated MP3 segments whose interior ID3
  tags and non-audio Info/Xing frames caused strict FFmpeg decoding to fail with
  `Header missing`. Only complete metadata at verified MPEG frame boundaries is
  removed in a private input copy; every audio byte remains, originals remain
  read-only, and full error-free decoding still governs duration and validation.
- Write ID3, Combine and signed Time share the corrected input. Stale-header,
  damaged-audio and atomic whole-Book publication safeguards remain in force.
  Synthetic regressions reproduce the actual 24 kHz mono concatenation structure,
  exercise processing/orchestration and refuse damaged metadata or audio.
- macOS manual Write ID3 rerun **PASS**: MP3-Tool-5, one Book / 44 tracks,
  44 completed and zero failed/skipped/not attempted; Chapters 3161–3202 and
  whole-Book publication succeeded. Focused verification is green. Complete
  verification remains **FAIL** (7,882 passed / 93 skipped / 16 failures): all
  16 exact failure causes reproduce unchanged on clean base `62b0c095`.
  The maintainer explicitly authorized this bounded checkpoint after comparison;
  no unrelated UI/import failure or verification requirement was changed.

