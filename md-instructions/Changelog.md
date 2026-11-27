# Changelog

All notable changes to the Audiobook Creation Tool are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Convention:**
- During active development, log work-in-progress under `[Unreleased]` with one entry per session.
- When a phase from `IMPLEMENTATION_PLAN.md` is complete, note it as a sub-bullet.
- On release, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and start a new `[Unreleased]` section above it.
- Categories: **Added** / **Changed** / **Fixed** / **Deprecated** / **Removed** / **Security**.

---

### Release-history index (navigation only; added by Phase 0B on 2026-11-25)

Nothing is rewritten. Since DOC-1 (v0.8.2 Phase 2, 2026-11-27) this file keeps the 0.8.x sections; the sections from `[0.7.3]`
down moved unchanged, byte for byte, to [v0.6.7 to v0.7.3](../files/documentation-history/changelog/Changelog-v0.6.7-to-v0.7.3.md) and
[v0.1.0 to v0.6.6](../files/documentation-history/changelog/Changelog-v0.1.0-to-v0.6.6.md). Find a section with its heading text.

- `[0.8.2]` — development branch `0.8.2` (long-running; nothing tagged, merged or published).
- `[0.8.1]` — published 2026-11-21 (UTC), Windows and macOS; shipped on a maintainer exception.
- `[0.8.0+macos.1]` — macOS-only revision; never tagged separately, it shipped inside 0.8.1 (its heading still reads as a candidate, as written then).
- `[0.8.0]` — 2026-11-14, OmniVoice; Windows release on maintainer-accepted evidence.
- `[0.7.3]` — 2026-11-12 hotfix; then `v0.7.2 release-readiness history` and the `[Unreleased] — v0.7.2 Phase …` blocks (Phases 3 to 9), then one plain
  `[Unreleased]` block holding the v0.7.0-era and v0.6.7-era work before `[0.7.0]` (2026-11-02).
- `[0.6.6]` — 2026-09-30 (the v0.6.x checkpoint history is inside and below it).
- `[0.5.0]` 2026-07-06, `[0.4.0]` 2026-06-05, `[0.3.2]` and `[0.3.1]` 2026-06-04, `v0.2.0 — Installer Hardening (macOS)`, `[0.1.3]` to `[0.1.0]` 2026-05-29/30.
- The file ends with early planning residue (`Decisions (Phase 0)`, `Open Questions`, `Session Log`); treat it as history.

## [0.8.2] - unreleased (development branch `0.8.2`; nothing is tagged, merged or published)

**Changed (repository cleanup, v0.8.2 Phase 2, 2026-11-27; the app is unchanged)**
- The long history documents are split, unchanged: Decisions entries from before v0.8.0 and Changelog sections from 0.7.3 down now live in
  `files/documentation-history/decisions/` and `files/documentation-history/changelog/`; this file and `Decisions.md` link to them.
- Removed from the tree (still in Git history): four development programs nothing used (`files/dev-tools/macos_p2_kokoro_assets.py`,
  `macos_p4b_omnivoice_install_qa.py`, `macos_p4b_omnivoice_setup.py`, `omnivoice_p2_smoke.py`) and eight completed v0.6.7 to v0.7.2 plans.
- `files/dev-work/verification-gate/GATE.md` states simple retention rules for agents' scratch and gate evidence.

**Changed (verification gate simplified, 2026-11-27; tests and tooling only, the app is unchanged)**
- The verification gate is simpler: tests run as standard pytest under a supervised stage, with a small guard that keeps real engines, network
  downloads, installers and desktop automation out of routine runs. The per-process launch interception and accounting of Phase 1A-1 is removed
  (about 5,200 lines of verification code and 2,300 lines of its own tests). `--mode quick`, `--mode changed`, `--mode regression` and
  `--mode focused --feature` now run instead of only printing their plans. Documentation and review reports no longer make earlier test evidence stale.

**Changed (documentation and development process; the app is unchanged)**
- `md-instructions/` now holds exactly five permanent documents (`Briefing.md`, `Handoff.md`, `Feature-Map.md`, `Decisions.md`, `Changelog.md`); active
  plans live in `files/plans/`. The Feature-Map is an index of the maps under `files/dev-work/feature-map/`.
- Handoff and Briefing were compacted to current state (Phase 0B). The full earlier documents are recoverable with
  `git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` (and `Briefing.md`). Decisions and this file gained navigation indexes only.
- The v0.8.1 release status above was corrected to published. The Tay-mar pronunciation requirement now lives in Decisions.

**Fixed (TTS: OmniVoice chapters that could never convert)**
- Chapters whose text has a cut-off word in its own paragraph (for example a thought that breaks off after two letters and an ellipsis) no longer fail with OmniVoice. On some seeds the voice renders such a fragment so quietly that the engine's own clean-up removes all of it; every chunk's seed is fixed, so those chapters failed the same way every time (four Shadow Slave chapters in the owner's mass run). Such a chunk is now rendered again with further seeds derived from its own, up to 24 renderings, until it speaks. Words are never replaced by silence or another voice, a chunk that speaks at once is rendered exactly as before (every file the app could already make is unchanged), Cancel is honoured between renderings, and a chunk that stays silent on every seed still fails its file, now saying how many renderings were tried (in the detailed log and the failure record). 10 regression tests added.

**Changed (Windows verification policy; the app is unchanged)**
- The Windows skip policy now excuses exactly one more reason, "files/dev-work/ currently holds no colliding test basename" (max 1), which a clean clone produces because it holds no local test copies. Qwen3 absence and every other unreviewed skip remain failures on Windows. One focused policy test added (`test_macos_p1b_gate.py`).

**Fixed (Windows full-gate closeout; tests only, the app is unchanged)**
- A developer test no longer leaves empty folders in the app's runtime data. Four cases of `test_voice_previews` (the voice-preview tool's speech read-back) built the Qwen3 engine's process environment, which creates `files/runtime-data/qwen3/cache/{hf,numba,pip,torch,xdg}` and `qwen3/tmp`, in the checkout's real runtime data; on a computer without Qwen3 the suite's own production-state guard then failed the next test that looked. The test now points the Qwen3 runtime folder at its own temporary folder, and a new test proves nothing appears in the real one and that the engine's caches and scratch lie in the test's folder (it fails, and the guard fires, when the redirect is removed). The tool and the app keep their behaviour: the folders are still prepared, inside the test's folder.
- The tests of Import Folder's edit protection now cover the M4B Maker as fully as the MP3 Tool: pasted Chapter Titles, a track moved or removed, a Book added or duplicated while the folder is scanned, and a paste no key release reported (6 new cases; the protection itself is unchanged).

**Fixed (Windows qualification of Checkpoints 1–6)**
- Import Folder no longer throws away changes you make to the Books while it is still running. It replaces every Book, and you agree to that when you press it; but the Books stay editable while the folder is scanned and (since Checkpoint 6, for minutes with thousands of M4Bs in the Metadata Editor) while the files are read, and whatever you typed, pasted or rearranged in that time was replaced without a word when the import finished. This happened in the MP3 Tool, the M4B Maker and the Metadata Editor. Now, if a Book was changed after you pressed Import Folder (a field, pasted Chapter Titles, a track moved or removed, a Book added, duplicated or removed), the import replaces nothing, keeps every change, and says so: "Import Folder: the Books were changed while the import was running, so they were not replaced and your changes were kept. Choose Import Folder again to replace them." Switching Books, Shared fields and an edit put back to what it was do not count as a change, so an import you only watched goes ahead as before. Add Files is unaffected (it adds to the Books you have; nothing is replaced).

**Fixed (Checkpoint 6, large workspaces)**
- Importing many M4B files into the Metadata Editor no longer freezes the window. The Editor reads every imported file's tags and asks FFprobe for its chapter titles, about 30 ms a file; it did that inside the import, so 2,341 files held the window for over a minute (2.5 minutes at 5,000). Now the files are read in the background: the import line counts "Reading tags and chapters… N of M files" with Cancel Import available, the window stays usable, and the Books appear when every file has been read, with exactly the information as before (readable or not, chapter titles, prefilled fields). Cancel Import or closing the tool while the files are read adds nothing; the files themselves are only read, never changed. The reading itself takes as long as before.
- The MP3 Tool reads imported MP3s' tags the same way, in the background ("Reading tags… N of M files"), instead of pausing the window at the end of a large import. Add Files puts the files into the Book it was pressed on, even if another Book is on screen when the tags arrive; that Book stays on screen, and Chapter Titles pasted there are kept.
- While an import's files are being read, Import Folder, Add Files, Clear All Imports and the tool's Start buttons wait, as they already did during a scan; the Books being imported do not exist yet, so nothing can start from a half-read import.
- Importing a folder of thousands of one-file folders into the MP3 Tool no longer pauses the window when the Books appear: 2,341 Books took half a second and 5,000 Books over four seconds; now a few hundredths of a second. The Books and their prefilled fields are exactly as before.
- Add Files in the Metadata Editor beside thousands of Books no longer pauses the window for about a second after the files are read.
- Switching Books, and typing in a Book or Shared field, no longer slows down with thousands of Books. With 5,000 Books in the Metadata Editor each keystroke or Book switch took 0.16–0.25 s; it now takes about 15 ms. The same work was quadratic in the MP3 Tool and M4B Maker.
- Typing in a Shared field no longer redraws an unchanged track list in the MP3 Tool and M4B Maker, so it stays quick with thousands of tracks in a Book and the tracks you selected stay selected.
- Selecting all (Ctrl+A) or moving a large selection in a long imported-file list (TTS Audiobook, M4B Converter, Cover Image) no longer pauses the window: Select All on 5,000 files took about 0.7 s and is now immediate. Select All in Cover Image's image browser (0.9 s at 5,000 images) is immediate too.
- Measured and not changed: the Summary and Details logs (each line about half a millisecond, nothing hidden or trimmed), progress updates during large jobs, Cover Image's remaining short pause at 5,000 images while a resize is prepared, and the brief pause (about 0.1–0.2 s at 5,000 files) when a folder scan or an Add Files selection is handed over to a tool.

**Fixed (Checkpoint 5, M4B Converter planning and Cover Image Start)**
- The M4B Converter no longer takes minutes to plan a run of many books or many chapters before converting. For every output it planned it checked, path by path, that the output was not one of the books being read, re-reading every book's location each time, and it did that twice while planning and once more as each file was written. Planning 1,000 whole books took 348 s on HOME-PC (almost 6 minutes after the books had been read and before the first one was converted); it now takes under 1 s, and 5,000 chapter files plan in about 6 s. The check itself is unchanged: an output can still never be one of the books being read (including a book that could not be used, the same file spelled with other letter case, or a file reached through a folder link), and output names, book folders, chapter order and numbering are exactly as before.
- Pressing Resize Covers with a large standard-output job no longer freezes the Cover Image window. Start used to reserve the run folder and work out every image's output path, with all of its safety checks, before the window could repaint: about 1.2 s for 2,341 images and 2.4–4.5 s for 5,000. Now "Preparing job…" appears at once with Cancel available and the paths are worked out in the background while the window keeps responding; the resize then starts by itself. Destinations, numbering of duplicates ("-1", "-2"), every safety check and Retry Failed are exactly as before.
- Cancel or closing the tool while a Cover job is being prepared starts nothing and leaves no empty run folder. If the output folder cannot be used or a destination cannot be planned, the same message as before is shown, nothing is created, the previous run's result and Retry Failed stay usable, and Resize Covers works again. The output-folder Preferences in force when Resize Covers was pressed are used, even if they change while the job is prepared.
- While resizing, Cover Image no longer re-checks every image against every other image's location for each image it writes (about 25 million path look-ups over a 5,000-image run); each image is checked once against a list made at the start of the run. An output that would be one of the images being read is still refused.
- Save beside source images is unchanged: numbered copies still start at once and are named beside each source as before, and Replace original files still checks every image and asks for confirmation on the window before anything is replaced; declining still changes nothing. Not changed: with Replace original files, checking a very large selection before the confirmation still holds the window briefly (about 1.2 s at 5,000 images).
- If a new Cover job area cannot be set up, or the resize cannot be started, the panel no longer stays locked and the previous run's Retry Failed stays usable.

**Fixed (Checkpoint 4, TTS Audiobook Start)**
- Pressing Start on a large TTS Audiobook job no longer freezes the window. Start used to reserve the run folder and work out every output file's name, with all of its safety checks, before the window could repaint: about 4 s for 2,341 files and 8–12 s for 5,000. Now "Preparing job…" appears at once (25 ms at 2,341 files, under 70 ms at 5,000) with Cancel available, and the names are worked out in the background while the window keeps responding (its largest pause on HOME-PC was 45 ms at 2,341 files and under 90 ms at 5,000, measured at 1 ms timer resolution; up to 123 ms at Windows' default 15.6 ms timer, see the Handoff). The job then starts by itself; the background work takes about as long as the freeze used to.
- Output names, folders, numbering of duplicates ("-1", "-2"), every safety check, voices and audio settings are exactly as before. Retry Failed still writes each file to the destination its run planned.
- Cancel or closing the tool while the job is being prepared starts nothing and leaves no empty run folder. If the output folder cannot be used, a name cannot be made, or the selected local voice stopped being available while the job was prepared, the reason is shown, nothing is created, the previous run's result and Retry Failed stay usable, and Start works again. The output-folder Preferences in force when Start was pressed are used, even if they change while the job is prepared.
- Starting a TTS job no longer re-measures the whole window layout every time (about 0.2–0.3 s). In every tool, locking or unlocking the list of imported files is no longer sent to the window when nothing changes (each time cost about 40 ms at 5,000 files), and the TTS list is no longer unlocked and locked again as a job starts.
- If a new job area cannot be set up, or the conversion cannot be started, the TTS panel no longer stays locked.

**Fixed (Checkpoint 3, TTS Audiobook output names and the shared collision search)**
- Starting a TTS Audiobook job with many files that share one output name, or many files added directly or sitting in one folder, no longer takes minutes. The "-1", "-2" numbering restarted its search from "-1" for every file, and the first of the two planning passes gives every file the same temporary name, so 2,341 identical titles took 41 s and 5,000 directly added files over 2 minutes even when their names were unique. The search now carries on from where it stopped. Measured on HOME-PC: 2,341 identical titles planned in 3.1 s, 5,000 in 6.7 s (199 s before), 5,000 unique titles in 6.5 s (136 s before).
- File and folder names are exactly what they were, in every tool that uses the shared planner (TTS Audiobook, MP3 Tool, M4B Maker, M4B Metadata Editor, M4B Converter, Cover Image).
- Not changed: TTS Start still plans on the window's thread, so a very large job still holds the window while it is planned (about 4 s for 2,341 files, 8–12 s for 5,000); a later checkpoint moves that work off the window.

**Fixed (Checkpoint 2, M4B Maker and M4B Metadata Editor large jobs)**
- Build M4B(s), Save Tags, Clear All Tags and Remove Series Numbering no longer freeze the window on large workspaces. The tools planned inside the button press and re-checked each Book's outputs against every source (18 s for 250 one-track Maker Books, 15 s for 250 Editor files, about 4.5 minutes for 1,000, with "Ready" still shown). Planning now checks each output against an index of the job's sources built once and runs on a preparation worker. On HOME-PC, 2,341 tracks in seven Books are planned in 0.36 s and 2,341 Editor files in about 2 s, while the window keeps responding (largest heartbeat gap 31 ms for the Maker and 66 ms for the Editor at 5,000).
- The job area shows "Preparing job…" with Cancel as soon as the button is pressed (after the Editor's confirmation). Cancel or closing the tool during preparation starts nothing, removes the empty run folder (or the custom build's own temporary work area) in the background, and leaves every Book, setting, title, original and the previous run (including Retry Failed and its kept staging) as it was. A refused preparation shows its error and also leaves them as they were; the next Start works.
- The output-folder Preferences in force when Start is pressed are used for the whole job, even if they are changed while the job is being prepared.
- A Chapter Titles change made without a key release (for example a mouse paste) is no longer lost when another field is edited, when the box is redrawn, when moving between Books or when a job starts. Ctrl+Z after moving to another Book no longer brings back the previous Book's titles. Remove Series Numbering still applies no pending metadata edit.
- If the job area of a new run cannot be set up, or its worker cannot be started, the tool no longer stays locked (as in the MP3 Tool, Checkpoint 1 R1). Clear All Imports builds its fresh job area first; if that fails, nothing is cleared.
- The previous run's kept staging is removed in the background instead of on the window's thread.
- Not changed: the Metadata Editor still reads each file's tags when it is imported, on the window's thread.

**Fixed (Checkpoint 1 review remediation R1, MP3 Tool)**
- Ctrl+Z in the Chapter Titles box can no longer bring the previous Book's titles into the Book you moved to.
- Pasted Chapter Titles are no longer lost. A paste that was not followed by a keystroke used to be thrown away when a Shared or Book field, artwork, numbering or the track list was changed afterwards, and the run then used the old titles. The titles now stay with the Book they were pasted into through every such change, through moving between Books, duplicating, and both Start buttons.
- If the job area of a new run cannot be set up, the tool no longer stays locked. Before the new run takes over, the previous run, its Retry Failed, its kept staging and every Book and edit stay as they were, the unused empty run folder is removed and the error is shown. After it has taken over, the run is reported as failed instead of appearing to run. Navigation and both Start buttons always come back.
- One output-folder setting per job: the Preferences in force when Start is pressed are used for the whole job and recorded with it, even if Preferences are changed while the job is being prepared.
- A job is refused if its frozen snapshot no longer matches the workspace it is planned from (tracks, their order, settings or titles changed).
- Cancel and closing the window just after a job was prepared no longer wait on the output drive; the empty run folder is removed in the background.
- Clear All Imports builds its fresh job area first; if that fails, nothing is cleared.
- Internal: a job area that fails while being built leaves nothing behind (`shared/job_ui.py`).

**Fixed (Checkpoint 1, MP3 Tool large jobs)**
- Write ID3 Tags and Combine no longer freeze the window on large workspaces. v0.8.1 planned inside the button press and re-checked every output against every source (about 20 minutes for 2,341 tracks with "Ready" still shown); planning now checks each output against an index of the job's sources built once, and runs on a preparation worker. On HOME-PC, 2,341 tracks in seven Books are prepared in about 2.7 s while the window keeps responding (largest heartbeat gap 29 ms).
- The job area shows "Preparing job…" with Cancel as soon as the button is pressed. Cancel during preparation starts nothing, removes the empty run folder and leaves every Book, setting, title and the previous run (including Retry Failed) as it was. A refused preparation shows its error and also leaves them as they were.
- A Chapter Titles change made without a key release (for example a mouse paste) is no longer lost when a run starts or when moving to another Book.
- The previous run's kept staging is removed by the new run's worker instead of on the window's thread.

## [0.8.1] - 2026-11-21 — published (GitHub release `v0.8.1`, Windows and macOS ZIPs; tag at release-preparation commit `6a7be75`)

One shared Windows + macOS version again after the macOS-only `0.8.0+macos.1` revision (which was prepared but never tagged or
published).

**Release status (corrected 2026-11-25, v0.8.2 Phase 0B).** v0.8.1 was published on GitHub on 2026-11-21 at 05:45:50 UTC (2026-11-20 23:45 at
UTC-6) with `AudiobookTool-Windows-v0.8.1.zip` and `AudiobookTool-MacOS-v0.8.1.zip`. It shipped on the maintainer's recorded verification
exception (below): publication does not mean every acceptance item passed. The text under this heading was written while v0.8.1 was a release
candidate and is otherwise unchanged.

**Release preparation (documents only; no application code, no `scripts/` change)**
- Final independent Codex review: **PASS WITH LIMITATIONS** for `f7a0b51e697cf71cf8d51887ed548a10908918ec` (M1, M2 and M3 independently closed).
- README: v0.8.1 download links for `AudiobookTool-Windows-v0.8.1.zip` and `AudiobookTool-MacOS-v0.8.1.zip`, v0.8.1 release notes, and the v0.8.1 verification limits; the Windows v0.8.0 link and history are kept. The never-published `v0.8.0-macos.1` link is no longer given as a download.
- New `files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`: the maintainer verification exception. The historical Full gate FAILED (56/56 journeys passed); F1/F2 corrected the failures; the targeted re-run of the original 30 reported 18 passes, 12 Windows skips and 0 failures; there is **no passing final canonical Full gate**, and the owner declined a second one.
- The v0.8.1 voice-preview gallery still has 28 published previews; the six OmniVoice placeholders are not previews.


**Fixed (Review R3, Codex M3; tests only)**
- The test guard's bundled-Python bytecode exception no longer covers anything below `python/Lib/site-packages` (third-party code, matched by path component and case-insensitively); only genuine standard-library bytecode is excused.

**Fixed (Review R2, Codex M3 re-review; tests and gate metadata only)**
- The test guard's bundled-Python bytecode exception now requires the bundled interpreter's own cache tag, an existing source module, a `__pycache__` that is not nested, and a location under `python/Lib/`; foreign-tag, source-less and nested-cache entries and links are reported.
- The real-link isolation test has its own skip reason and policy rule (ceiling 1); the generic `no-symlink-privilege` ceiling stays 17.

**Fixed (Review R1, Codex findings M1-M3; focused tests only)**
- Add Files and Add Folder (all six tools, one shared adapter) refuse while an import is already running, before the file dialog opens. A cancelled or rejected second dialog can no longer discard the running import's remembered folder or become the next one.
- Reset Preferences refreshes the Light/Dark bundle through the interpreter root, so the Aqua outlined role buttons repaint with the stored appearance instead of keeping the previous theme's images. Native Mac confirmation is still the owner's.
- The test guard's bundled-Python bytecode exception now covers only regular `*.cpython-NNN[.opt-N].pyc` files in a bundled `__pycache__`; any other file written there is reported.

**Fixed (Checkpoint F2, tests, dev tool and gate metadata only; no application code)**
- `files/dev-tools/voice_previews.py` renders the owner-edited `files/voice-previews/README.md` exactly: an `Availability` column from the application's engine policy and six display-only OmniVoice rows (`To Be Added`) that are not manifest records, are not counted and claim no publication right. `previews.json` (28 authorized previews) and every WAV are unchanged; the four README tests that F1 left failing pass again.
- The Windows no-link-rule test is split: a deterministic test that needs no link, and the real-link test, which now skips only on WinError 1314 (this account cannot create symbolic links) under its own exact skip-policy rule with a ceiling of 1. Real link rejection stays unverified on accounts without the privilege.

**Fixed (Checkpoint F1, tests and gate metadata only; no application code)**
- The Aqua layout pins in five tests (`test_clear_all_imports`, `test_m4b_maker_ui`, `test_m4b_metadata_editor_ui`,
  `test_prototype_regression`, `test_mp3_tool_ui`) asserted that every Aqua button has the native `TButton` layout. Since
  Checkpoint E a role button (red, green, yellow, blue) draws its own outlined image element and a plain button stays
  native; they now say so through one helper (`assert_aqua_button_layout` in `test_button_roles.py`).
- `ACT.SHARED.BUTTON-ROLES` has its macOS standing in `coverage.json` (recorded from the native Checkpoint E run, not
  derived from the P1B census); the four Mac-only native-size comparisons are a `macos-native` owner check instead of
  routine Windows verifications that could never run there.
- The Windows skip policy names each macOS-only reason with its own exact ceiling and reason text instead of leaving 229
  skips unmatched; the P5-D ceiling is 44 (two tests were added after it was set). Unreviewed skips still fail.
- Mac-only tests that failed on Windows now say so: eight `fcntl` simulations, a process-id probe that ended the process
  on Windows, a first-run copy layout, and three assembly and two worker tests made platform-correct. The Mac stop-budget
  timing is asserted on POSIX only.
- `test_stage_zero_rejects_a_python_whose_tk_cannot_initialise` is hermetic (a copy of stage 0 and of the Python, with a
  healthy control); `test_edge_publication` simulates POSIX through the shared primitive; the MP3 hardening version pin is
  0.8.1; the Tk module boundary forgets the application's disarmed indicator images; the production-write guard no longer
  counts the bundled Python's own `__pycache__`.
- Not changed: the four voice-preview documentation tests (the README was edited by hand on 2026-11-16; owner decision
  needed) and the Windows symlink-privilege test.

**Fixed (Checkpoint F, tests only)**
- Two macOS-only test modules (`test_macos_p1b_gui_containment.py`, `test_macos_p2_kokoro_real.py`) no longer stop test
  collection on Windows: their `parametrize` decorators named `signal.SIGKILL`, which Windows does not have, and the
  gate's collection stage failed with two errors. The decorators now look the signal up by name; on a Mac the real
  `SIGKILL` is used and every native assertion is unchanged. A new test (`test_macos_p1b_containment.py`) imports both
  modules wherever it runs.

**Changed (Checkpoint E, macOS)**
- **Outlined button colours on macOS.** The red (Cancel, Clear, Remove), green (Start, Build, Save), yellow (Pause,
  Resume, Retry) and blue (the Book controls, repair and review) buttons now show their colour on a Mac, as on Windows: text and
  a thin outline only, a neutral body in every state, a visible disabled state and a focus halo, in Light and Dark.
  Ordinary buttons stay native. Size and spacing are unchanged. (Aqua cannot colour a native button's outline, so these four styles
  draw a small outline image of the same size.)

**Fixed (Checkpoint D, tests and coverage document only)**
- The cleanup-worker deletion guard now recognises the macOS launch-permit cleanup in `child_guardian.py` and
  `child_ownership.py` (each removes only the permit folder its owner created) and pins that by AST in a new test; the guard's catalog
  assertions are unchanged.
- Two verification coverage ids that went dead when their tests were parametrized now name the exact parametrized ids.
- Eight macOS-simulation tests that import `fcntl` on Windows are classified as a pre-existing Windows-only artefact and
  deferred to the native macOS checkpoint.

**Added**
- **The file dialogs remember where you were, per tool and per action.** TTS Audiobook's Add Files and Add Folder now
  reopen in the folder last used (they remembered none before). The M4B Maker's custom-destination
  Browse… and the Preferences output-location Browse… each remember their own folder. (Checkpoint A)
- **Outlined semantic button colours (Windows).** Buttons now draw one of four colours by what they do, in the
  button's text and border only, in Light and in Dark: red for Cancel, Clear, Remove, Reset and Clear Log; green for
  Start, Build, Save and Install; yellow for Pause, Resume and Retry Failed; blue for the Book Previous, Next, Add Book
  and Duplicate Book buttons (MP3 Tool and M4B Maker; Previous and Next in M4B Metadata) and for repair, review and
  developer tools. Every other button, and the left-hand navigation, stays as it was. The roles apply to all six tools,
  Preferences & Data, the Cleanup dialogs, the Cover replacement confirmation, the Qwen3 install and repair dialog and
  the Install & Continue panel (also in the first-run voices step). The roles follow the owner's 146-control matrix.
  (Checkpoint B)

**Fixed**
- **OmniVoice no longer fails a chapter over a "..." paragraph.** A paragraph with nothing to say (only "...", or a lone
  unreadable character) sometimes came back from OmniVoice as complete silence, which OmniVoice's own clean-up then
  removed, and the whole chapter failed with "the model returned unusable audio (shape (0,))" -- the cause of all 80
  chapters that failed in a long OmniVoice mass test. Such a paragraph now becomes a short pause (0.2 s) and the chapter completes;
  everything else sounds exactly as before, and a passage with words that comes back empty still fails. (Checkpoint C1)
- **All 80 chapters that failed in the long OmniVoice mass test now narrate.** Regenerated with the real engine
  (Male 3, RTX 5070) on this branch: 80 of 80 completed and passed full MP3 decoding, 8,337 of 8,337 passages rendered,
  93 empty "..." paragraphs became 0.2 s pauses. No product code changed. (Checkpoint C2)
- **MP3 Tool artwork dialog** opened in the import folder; it now has its own remembered folder, shared by Shared and
  Book artwork, and choosing artwork no longer changes where Import Folder and Add Files open. (Checkpoint A)

**Changed**
- **An OmniVoice failure says where it happened.** The message ends "(chunk N of M, worker batch B of K)", and each
  failure's technical details (never the narrated text) are kept in the engine's `failures.jsonl` beside
  `last-failure.txt`. (Checkpoint C1)
- **A remembered folder changes only when a selection is accepted**, in every tool: Cancel, a selection that adds
  nothing, a refused file or image, and a declined broad-folder question leave it as it was. A file choice remembers its
  folder; a folder choice remembers the folder itself.
- **An unreachable remembered folder** (deleted, on an unplugged drive or a share that is offline, or not readable)
  makes the dialog open at your home folder, and is kept, so it is used again once it is back.
- Import and artwork folders are separate in every tool that has both; a tool's Shared and Book artwork share one.
  Browsing in Preferences never changes the saved output location; only Save does. Reset Preferences clears every
  remembered folder; no file or folder is deleted. Each installation keeps its own remembered folders.
- Application identity `0.8.1`; the configuration lists Windows and macOS again and the packager builds both archives.
  Which voices each platform offers is unchanged.
- **A coloured button never fills with its colour.** The red Cancel and Clear buttons used to flood red when the pointer
  touched or pressed them; every coloured button now keeps a neutral grey background in every state (resting, hover,
  pressed, focused, default and disabled). A disabled coloured button shows plain grey text and border, and a focused
  one keeps its coloured border and the focus ring. macOS keeps its native buttons for now (Checkpoint E). (Checkpoint B)

## [0.8.0+macos.1] - unreleased (release candidate; publication awaits the owner) — v0.8.0 for macOS, Revision 1

**Release route (D16, owner 2026-11-20; publication not yet approved).** The first macOS release of the v0.8.0
generation, as its own revision: tag `v0.8.0-macos.1`, release "ACT v0.8.0 for macOS — Revision 1", identity
`0.8.0+macos.1`, archive `AudiobookTool-MacOS-v0.8.0-macos.1.zip`. Built from the macOS branch, which is different
source from the published Windows v0.8.0 (`d1701e9`); that release, its tag and its asset are unchanged, and no Windows
archive is built from this source. Qualified on one Mac (MacBook Pro, Apple M4 Pro, 24 GB, macOS 27.0.1). Not
qualified: a REAL CLEAN first installation from the release archive, other Macs and memory sizes, the owner's manual
Force Quit check. v0.8.1 is the next shared Windows + macOS release.

**Added (macOS, Apple Silicon)**
- **Native macOS support for all six tools** on the app's own Python 3.12.15 (python-build-standalone, Tk 9), set up
  by the `.command` launcher and a bash 3.2 stage 0 with consent and SHA-256 checks; no Homebrew, no administrator
  password, nothing outside the app folder. A hash-locked arm64 dependency set
  (`scripts/requirements-lock-macos-arm64-py312.txt`) and the app's own FFmpeg 9.0.1 arm64 build (Martin Riedl
  release build, pinned by SHA-256, `aac_at` for xHE-AAC). (macOS P1A, P1B)
- **Voices on a Mac: Edge TTS (5), Kokoro (9) and OmniVoice (6), 20 in all**, through one platform capability policy
  (`shared/engine_policy.py`); Chatterbox Turbo and Qwen3 are not offered on a Mac at any surface. Kokoro runs in its
  own local-engine worker; OmniVoice on the Mac GPU (MPS fp32) by default with the CPU selectable. (P2, P4A–P4C)
- **Process containment on a Mac:** every helper the app starts (FFmpeg, engine workers, setup's pip and probes) is
  owned by the app and ends with it, including after a crash or a forced quit, through a guardian process and a
  permit-gated launch; a run whose helpers cannot be confirmed ended is reported FAILED, never a clean Cancel or a
  success. (P1A–P5-I-R3)

**Changed**
- **Cancel contract (owner decision 2026-11-20):** Cancel is acknowledged within about one second (was 0.5 s; 0.723 s
  measured and accepted). Cancel still stops the active job at once, ends its workers and subprocesses, publishes
  nothing incomplete and reports FAILED when it cannot confirm their end. Pause and the per-route stop bounds are
  unchanged.
- On a Mac, a narration long enough to reach the assembly gate is joined on disk, never in memory (the same MP3 to the
  byte; a 37-minute Edge book went from 5.2 GiB to 0.34 GiB). (P5-H)
- The version may carry build metadata (`X.Y.Z+build`), and an archive is named after its tag (`release.release_tag`),
  because GitHub rewrites `+` in asset names. The ordinary build makes the macOS archive only.

**Fixed (pre-merge remediation, found by the independent final review)**
- **Cover Image: Cancel is ordered against saving.** A Cancel pressed after the between-images checkpoint could still
  resize an image, install it over the original (Replace Original) and finish as SUCCEEDED. Every image is now written
  to a private staging file first and made final only after `JobController.authorize_commit()` grants it, under the lock
  the Cancel latch is taken under, so exactly one of Cancel and the save wins. A Cancel that wins discards the staging
  file, leaves the original and every earlier result untouched, starts no further image and finishes CANCELLED; a save
  that won is never rolled back. The replacement confirmation, Pause and Resume are unchanged.
- **Cover Image: no unfinished file under a final name.** Standard and numbered-beside-source saves were encoded directly
  to their final name; they now stage and publish by an exclusive new-name rename, so a name taken meanwhile is never
  overwritten and an interrupted save leaves no partial image.
  A run that fails on an image while a Cancel is already latched ends CANCELLED (it used to end "completed with failures"
  and say "All done"). The staging name is short and fixed, so a source name that fits the 255-byte limit still works.
  A publication error now shows the shared helper's reason in the log. **Known limit:** a copy output on an exFAT or FAT
  drive cannot be named exclusively (the same rule as every other tool); it fails with that explanation instead of saving
  directly, so choose an output folder on another drive. A window closed while an image is still being encoded can leave one
  `.act-tmp-cover-*` staging file beside it (the bounded shutdown predates this change).
- **The complete GNU GPL v3 text ships in the archive** as `LICENSE` (the project inherits GPL-3.0 from
  epub2tts-edge). It is the canonical text, byte for byte, tracked and pinned to LF; the packager's root allowlist now
  names it and refuses a root file that git does not track. No model weights are added or redistributed.

---

## [0.8.0] - 2026-11-14 — OmniVoice; Windows release on maintainer-accepted verification evidence (macOS pending)

**Release (Windows only, 2026-11-14).** `AudiobookTool-Windows-v0.8.0.zip`, tag `v0.8.0`. The one canonical
full gate (`2026-11-14_113416_full_c8e8` on `c583d78`) FAILED on five verification pins that predated v0.8.0's
additions, with no product defect; they were fixed in `ee426fd` and their focused checks passed. The owner accepted
the combined evidence for this Windows release as a maintainer exception and decided not to rerun the full gate
(`files/release-history/ACT-v0.8.0-Windows-Release-Acceptance.md`). Qualified: Windows 11 (HOME-PC) at 100% display
scaling. Not qualified: the Windows long-path switch-on on a computer where the setting is off, installations with
long paths off or exactly at a limit, Windows 10, other computers, scaling and GPUs, and the full five-component first
run on the final code. macOS v0.8.0 is not supported or published.

**Added**
- **OmniVoice, a fifth optional local engine (Windows, NVIDIA GPU only):** six cloned voices, *OmniVoice - Female 1*,
  *Female 2*, *Male 1*, *Male 2*, *Male 3* and *Male 4*, after the other voices in TTS Audiobook (34 voices in all). Each
  is conditioned on its own bundled recording (at most 10 s; Male 1 is 10.2 s by the owner's decision) and the owner's
  transcript of it. It runs offline in its own worker environment (`.venv\engines\omnivoice`; see Changed), prepares the
  text once with the existing speech
  preparation (default `v1`, all classes expanded for now), uses bounded workers so GPU memory does not build up over a
  long book, and Cancel stops it mid-chunk or mid-encode without publishing anything. (v0.8.0 Phases 1-2)
- **A fifth first-run choice, unchecked:** *OmniVoice — Six Cloned Voices*, also offered by Install & Continue. The review
  screen shows the licence and hardware terms before Install, and **View licence terms** opens each licence text. An
  existing matching environment is checked and adopted without downloading anything. (v0.8.0 Phase 3)
- **Windows path length: a clear README section and an optional long-path step in first-run setup (owner requirement
  2026-11-13).** The README's new "Important: Windows Installation Path Length" section recommends a short folder
  (`C:\AudiobookTool`), gives the limits the app enforces and explains Windows' "Enable Win32 long paths" setting and how to
  change it by hand. Where the app's folder is too deep for Windows as it comes but would fit with that setting on, the
  first-run window now shows the two ways forward before anything else: move the app (recommended), or switch long
  paths on. The setting is changed only if that button is pressed and Windows' own permission prompt is approved
  (Windows' own registry tool makes the one change; setup is never run as administrator). Setup then checks in a new
  process that long paths really work, says "restart Windows" if they do not yet, and otherwise starts again and
  continues. Declining, cancelling or a managed computer's refusal changes nothing. The README gives the limits as
  measured and enforced, says apart from them what was installed for real (one Windows 11 computer with long paths
  on, folders of 89 and 102 characters), and says that the switch-on itself has not yet been tried on a computer
  where the setting is off (2026-11-14).
- **README:** a v0.8.0 section, including the non-commercial terms (OmniVoice weights are
  CC-BY-NC) and the audio tokenizer licence's attribution. (v0.8.0 Phase 4)

**Changed**
- Every cloned engine has its own six reference recordings: 18 bundled WAVs in
  `files/Cloned-Voice-Uploads/<Engine>/`. Qwen3 keeps its original six byte for byte (renamed); Chatterbox uses the owner's
  new recordings. The release archive carries exactly these 18. (v0.8.0 Phase 2 correction)
- Application identity is 0.8.0 (`scripts/shared/version.py`, `config.toml`). (v0.8.0 Phase 4)
- **One `.venv` folder, three independent environments (owner decision 2026-11-13, unified `.venv` layout):** the
  OmniVoice engine is installed at `.venv\engines\omnivoice`, inside the app's own `.venv` beside the Qwen3 engine
  (`.venv\engines\qwen3`). Each of the three keeps its own Python packages; nothing is merged. Earlier builds of this
  unreleased version installed OmniVoice beside `.venv`, as `.venv-omnivoice`. This version never uses that folder:
  Install & Continue builds the engine again in its new place from the same pinned packages (a model already on the
  computer is reused), checks it there, and only then moves the old folder, whole and never deleted, to
  `files\runtime-data\omnivoice\set-aside`. If anything fails or is cancelled first, the old folder stays exactly where
  it was.
- Repairing the app's own environment waits for OmniVoice as it does for Qwen3 (it is refused while either is
  converting or being installed) and carries both engines across unchanged.
- OmniVoice is not installed in a copy of the app whose folder path is too long for Windows to load the engine from
  inside `.venv` (more than 119 characters, or 83 where Windows long paths are off); it says so before downloading
  anything, and every other voice is unaffected.
- **The app's folder-path limit with Windows long paths on is 123 characters (was 131).** Measured on two real
  installs, Qwen3's deepest program library sits 132 characters below the app's folder since the engine moved inside
  `.venv` (v0.7.0), which the old limit did not allow for: a folder of 128 to 131 characters was accepted although that
  library could not have loaded there. The limit with long paths off stays 87. A copy already installed in a folder of
  124 to 131 characters still starts; its next repair or setup asks for a shorter folder.
- Wherever setup or a repair depends on Windows long paths (a folder longer than 87 characters), it first checks in a
  new process that long paths really work there, and stops with a plain instruction if they do not.
- A "folder too long" refusal now also names the long-path way where that would be enough, and says so where it would
  not.

**Fixed (v0.8.0 unified `.venv` layout)**
- An OmniVoice engine whose files were damaged after it was installed stayed "ready": every conversion failed and no
  repair was offered. The failed conversion now records the damage, the voices say why they are unavailable, and
  Install & Continue repairs the engine (the damaged environment is kept aside, never deleted).
- A repair or cleanup refused because voices were being installed said "Qwen3" whichever voices they were; it now
  names no engine.
- An app environment whose own `python.exe` had been deleted (the `.venv` folder still there) could not be set up
  again: setup kept the folder, had nothing to run and failed on every start. It is now replaced like any environment
  that cannot run: set aside, rebuilt, and the Qwen3 and OmniVoice engines inside it are carried into the new one
  unchanged. (Found during the recovery acceptance on a disposable copy; the behaviour predates v0.8.0.)
- Qwen3's **Check and repair** answered "Everything checks out" for an engine whose package had lost its own files,
  while every Qwen3 conversion failed and pointed back at Check and repair. Its check now imports what a conversion
  imports, finds the damage and rebuilds the engine. (Found during the recovery acceptance; the behaviour predates
  v0.8.0.)

**Fixed (tests and tooling only, v0.8.0 Phase 4)**
- Tests that still pinned 28 voices, four engines or version 0.7.2 now assert the current roster and identity; the 28
  historical voice previews stay a fixed collection of 28. `m4b_nero.py` is documented in the M4B module map. The speech
  A/B dev tool no longer fails to load with five engines. The coverage inventory maps the OmniVoice and Nero features.

**Fixed (v0.8.0 independent review remediation, 2026-11-14)**
- An OmniVoice engine with a damaged or missing program library (for example a PyTorch DLL Windows refuses to load)
  stayed "ready": each conversion failed, but the damage was never recorded and no repair was offered, because Windows
  reports such a library as an `OSError`, not an import error. The engine now records it, says why its voices are
  unavailable, and Install & Continue offers the repair. Running out of memory while the engine starts says so ("close
  other programs and try again") and is never mistaken for damage; Smart App Control and the network guard are not
  either. (Independent review R1)
- A folder name holding characters such as emoji was measured shorter than Windows measures it, so a folder slightly
  too long could pass the path-length checks before a download. Every path-length check, the long-path offer, its
  message and the long-path proof now count as Windows does. The limits themselves are unchanged. (Independent review R2)
- Tests only: the long-path tests no longer create folders at the root of drive C: (an earlier run left two empty
  folders there on the development computer; they are reported, not removed). (Independent review R3)

**Verification only (v0.8.0 Phase 5 gate remediation, 2026-11-14; no program change)**
- The one canonical full gate on `c583d78` (`2026-11-14_113416_full_c8e8`) FAILED on five verification pins that
  predated v0.8.0's additions, with no product defect. Fixed in the gate and tests only: the first-run journeys expect
  the five choices (OmniVoice fifth, off) and take the path limits from the application (F1); the pip guard approves
  the long-path probe's one pip call and pins it whole (F2); the cancel guard names OmniVoice's route (F3); the
  OmniVoice real-clone opt-in skip has its own exact rule (F4); 17 coverage ids name real parametrized tests (F5).
  Focused checks pass; a new full gate has not been run.

**Owner listening:** the owner approved all 12 tracks of the OmniVoice listening pack (the owner's statement, recorded
2026-11-14).

**Independent review:** done (Codex, 2026-11-14): three findings, R1-R3, fixed the same day (see Fixed above).

**Full verification gate:** run once, on `c583d78` (`2026-11-14_113416_full_c8e8`): FAIL; its five findings are
fixed (see Verification only above).

**Not done, released without by the owner's decision (2026-11-14):** a passing full verification gate on the
corrected tree; the Windows long-path switch-on tried for real on a computer where the setting is off, and a
real installation with long paths off (an external Windows qualification). See Release above.

---

Older releases: [v0.6.7 to v0.7.3](../files/documentation-history/changelog/Changelog-v0.6.7-to-v0.7.3.md) (from `[0.7.3]` to `[0.7.0]`) and [v0.1.0 to v0.6.6](../files/documentation-history/changelog/Changelog-v0.1.0-to-v0.6.6.md).
