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

## [Unreleased]

### Changed — **The M4B Converter is rebuilt** (v0.6.2 Plan 5, 2026-08-31)

The Converter now turns an M4B audiobook into MP3s either as **one whole book** or **split by
chapter**, and the split is a complete partition of the source: every second of the book lands in
exactly one output, including anything before the first chapter and the tail after the last.

- **Chapters.** A whole-book MP3 keeps the source's chapter map **and its chapter titles**, under
  both *Preserve* and *Replace* — replacing a book's text does not invalidate its navigation.
  *Write none* removes it. A split fragment never carries the whole book's map; it gets its own
  title and its position within its own book.
- **Metadata.** *Preserve*, *Replace* and *Write none*, all three built as an allowlist: only
  `title`, `artist`, `album artist`, `album` and an optional track number can reach an output.
  Container brands, Audible identifiers and freeform tags from the source no longer travel with it.
- **Artwork.** An embedded cover is kept by Preserve and Replace and removed by *Write none*, on
  whole books and on every chapter of a split. Covers are copied, never re-encoded. A book with no
  cover is fine; a book with two is reported rather than guessed at.
- **Split outputs are grouped per book.** Each book gets its own folder, named after the source
  file, so converting a shelf of audiobooks no longer interleaves hundreds of chapter files in one
  directory.
- **Importing.** Add files or a folder, with an **Include subfolders** option; reorder, remove and
  clear the queue; add the same book twice deliberately if you want to. The queue is frozen when you
  press Convert, so changing it mid-run cannot affect the run.
- **Running a conversion.** Progress and a time estimate, **Pause**, **Resume** and **Cancel** —
  cancelling stops the run, cleans up the partial file and leaves finished books alone — plus
  **Retry Failed**, which re-runs only what failed, to exactly the paths originally planned.
- **Optional whole-book track numbering**, numbered only as books succeed so a failure leaves no gap.
  It is **off by default**.
- **Sources are never modified**, and no existing file is ever overwritten.

### Fixed (v0.6.2 Plan 5, 2026-08-31)

- **A whole book with a cover could be silently truncated** — a 13½-hour audiobook came out 0.32
  seconds long and reported success. Any book over about 50 minutes was affected.
- **Chapter titles were lost** from whole-book MP3s: the output carried the right number of chapters
  at the right times, all unnamed.
- **xHE-AAC audiobooks on Windows** decoded only ~76 % of their audio and reported success; they are
  now decoded through Windows Media Foundation, or the run stops rather than writing a short book.
- **Books whose tags contain characters outside the system code page** no longer fail to import.
- **FFmpeg is verified before use** — both `ffmpeg` and `ffprobe`, proved as a working pair rather
  than trusted because a path exists — and installed automatically on Windows when missing.
- **A failure while finishing a file** (a full disk, an ejected drive, a file held open by another
  program) now reports the problem and returns the window to normal instead of leaving it stuck.
- **Chapter navigation is written in the tag version Windows Explorer reads**, for every output.
- **Changing the output folder mid-run** no longer moves a conversion that has already started; the
  next one picks up the new location as expected.

### Removed — **BREAKING: EPUB is no longer a supported TTS input** (v0.6.1 Plan 4 Phase 5, 2026-08-14)

> **This is a breaking change for anyone who converted EPUB files.** The TTS Audiobook tool now
> accepts **PDF and TXT only**. There is no EPUB mode, no EPUB conversion option, no `.epub`
> dialog filter and no internal dispatch route that will accept one — a stale saved state, a
> retry or a direct internal call is refused just as the UI is.

- The EPUB-exclusive source is **preserved, not deleted**, in a permanent tracked archive at
  **`files/archived-code/epub-tts/`** — three extracted source files plus a `README.md` manifest
  recording, per file, its original path, purpose, source SHA, retirement reason, the retained
  production counterpart, its licence and how to restore it. The archive is **provably inert**:
  it lives outside `scripts/`, no production module imports or names it, it is uncollectable as
  tests, it contains no `__init__.py` / `conftest.py` / `setup.py`, nothing in it executes on
  import, and `release.py` cannot package it (the packager walks `ROOT_FILES` + one launcher +
  `scripts/` only). **It is permanent and was not deleted with the temporary plan drop.**
- **The shared Edge/PDF/TXT synthesis engine survived untouched.** Only four of
  `epub2tts_edge`'s twenty-four functions were EPUB-specific; every PDF/TXT and Edge code path,
  every timing constant and all five sibling TTS modules are unchanged. The module names
  `epub2tts_edge` / `epub2tts_gui` are **deliberately kept** — they carry the GPL-3.0 upstream
  provenance, and a rename across the launcher, bootstrap fallback, nine test modules and the
  Dockerfile while Phases 6–7 restructured the same panel was the larger risk. The boundary is
  documented in the panel docstring, the README and the archive manifest.
- **Dependencies removed on evidence:** `ebooklib==0.20`, `beautifulsoup4==4.14.3` and
  `lxml==6.1.1`, each with its consumers enumerated and its reverse-dependencies checked; the
  three pins are recorded verbatim in a `requirements.txt` comment and in the manifest so
  restoration is mechanical. `bootstrap.REQUIRED_IMPORTS` and `_PIP_NAME` were updated to match.
  **Every retained pin is byte-identical.**
- **GPL-3.0 licence and the Christopher Aedo / `aedocw/epub2tts-edge` attribution are intact**
  in production as well as in the archive, now pinned by tests. Only the `ebooklib` line left the
  "gratefully relying on" list, because the project no longer relies on it.
- 101 AST- and metadata-driven guard tests (`files/tests/test_epub_retirement.py`). No test was
  deleted, skipped, xfailed or weakened.

### Added — TTS and Cover Image workflows (v0.6.1 Plan 4, approved 2026-08-21)

> Plan 4 is the first plan to adopt the Plan 2 configuration/output services and the Plan 3
> importing and job-control foundation **inside production panels**. The launcher still lists
> exactly six tools.

- **One unified PDF/TXT queue in TTS Audiobook.** Direct files and whole folders coexist in a
  single queue and a single run — no separate single-file and batch modes. Occurrence identity,
  deliberate duplicates, provenance and natural ordering are preserved; folder-derived items are
  mirrored into the output tree and direct files are placed flat; and the run's frozen snapshot
  is what a Retry Failed re-runs, so a retry reproduces the exact original configuration.
- **A third TTS engine: Chatterbox**, with four maintainer-authorized voices —
  `Chatterbox - Female 1 / Female 2 / Male 1 / Male 2` — bringing the dropdown to sixteen rows.
  It is **optional and non-default**: the first-run setup checkbox is unchecked and states the
  real ~3.9 GB model size, and Kokoro's default is unchanged.
  - **Device selection is CPU-first** and resolves `cuda → mps → cpu` behind one testable seam.
    No CUDA build, index URL or git source was added. On Apple Silicon it really does run on
    Metal — measured, not assumed.
  - **Degraded installs stay truthful.** A machine without the `chatterbox-tts` package starts
    normally and still offers the twelve Edge/Kokoro voices. A machine without the reference
    recordings starts, converts, and reports every Chatterbox voice as *setup required* rather
    than offering a selection that cannot work. Missing recordings are deliberately **not** a
    startup requirement.
  - Reference audio is verified by SHA-256 **on every use**; derivatives and cached voice
    identity data live under the ignored `files/runtime-data/`, keyed on voice + source hash +
    engine release + clip spec so a stale entry misses rather than gets reused, and writes into
    the recordings folder are refused structurally.
- **A Cover Image browser with three views — Details, List and Medium Thumbnails**, defaulting to
  Details. All three are projections of the one shared imported-file manager rather than a second
  list, so order and selection survive a view switch by construction, and two deliberate
  duplicates of one path stay two independently selectable items. Selection semantics are
  identical across the three views because click and key handling routes through one pure engine.
  Thumbnail decoding is lazy, visible-only and hard-capped at 60 items, with a bounded LRU cache
  as the single owner of a decoded image.
- **HEIC/HEIF is a probed capability with decode and encode reported separately**
  (`shared/image_capabilities.py`, pinned at `pillow-heif==1.5.0`). Encode capability is proved
  by actually encoding, because registering the HEIF opener installs a saver whether or not an
  encoder exists behind it. A destination the build cannot honour is **refused truthfully** —
  HEIC output is never silently substituted with JPEG.
- **Cover Image and TTS both adopt the shared job controls** — Pause/Resume, Cancel, Summary and
  Details, progress, current-run ETA and Retry Failed — and the shared output services, including
  the Cover tool's source-side destination exception.
- **The twelve original voice rows keep their identity** — voice IDs, backends, timing presets,
  ordering and the Steffan default are unchanged. Their **display labels** were deliberately
  restyled by explicit maintainer override on 2026-08-21 into one consistent
  `Engine Gender - Name (locale)` form; the exact ordered list is pinned by 39 tests.

### Changed — TTS narration and output quality (v0.6.1 Plan 4 Phase 12, 2026-08-19)

- **Every TTS final MP3 is now encoded exactly once through one explicit contract, never on
  ffmpeg's defaults.** The old path produced 32 kbps output whose Xing header could not fit in an
  MPEG-2 frame, so players reported exactly half the true duration. Kokoro, Chatterbox and the
  Edge folder path now share the explicit encode, with a 64 kbps correctness floor. The
  file-size consequence — the panel's `192k` default yielding an effective 160 kbps, roughly 5×
  the old size — was put to the maintainer with the numbers and **accepted as tested**; no
  `64k` option was added and the default was not changed.
- **Chatterbox text is planned on natural boundaries** — paragraph → sentence → clause →
  whitespace → hard limit, packed to a 300-character ceiling — and **no structural newline ever
  reaches the model**, because the model renders one as a pause of no fixed length. This took the
  worst measured interior silence in a real chapter from **8.73 s to 2.90 s** with the duration
  essentially unchanged (488.94 → 486.34 s). Narration timing is **frozen for Plan 4** by
  maintainer ruling after listening; residual pause/rhythm tuning is a recorded observation, not
  scheduled work.

### Fixed — a hover-scoped mouse-wheel binding could outlive its own panel (v0.6.1 Plan 4 Phase 14, 2026-08-22)

- `shared/ui_theme.enable_mousewheel` takes the shared root's single global `<MouseWheel>` slot
  while the pointer is inside a scrollable options region — which is how the Cover, TTS and M4B
  options columns all scroll. It gave that slot back only on `<Leave>`, and **two real lifecycle
  paths never fire one**: the launcher's tool switch `pack_forget()`s the outgoing panel out from
  under the pointer, and closing a panel destroys the region outright. The stranded binding then
  scrolled the tool the user had just left and, once the widget was gone, fired at a Tcl command
  that no longer existed on every subsequent wheel tick. Release is now also wired to `<Unmap>`
  and `<Destroy>`, and is **ownership-guarded** — a region only ever gives back the binding it
  still holds, so a stale region's teardown cannot steal the wheel from the region the pointer is
  actually over. 11 direct lifecycle tests cover it.
- The Cover browser's wheel-locality contract was **corrected without being weakened**. Its old
  assertion — that no global `<MouseWheel>` binding may exist anywhere, ever — was true of the
  browser but false of the application, making it a tripwire for another panel's legitimate hover
  state. It now measures what actually matters: the browser's binding lives on its own Canvas, and
  building, scrolling and closing it leaves whatever owned the shared slot exactly as it found it.

### Changed — a missing Tk root is a failure on Windows, not a skip (v0.6.1 Plan 4 Phase 14, 2026-08-22)

- Every live-Tk test module opened its own root inside `try/except TclError → pytest.skip`. That
  is right on a headless POSIX box and wrong on Windows, where the desktop *is* the platform:
  Phase 14 measured one full-suite run that **silently dropped forty-nine Chatterbox integration
  tests and still exited zero**. The classification now lives once in `files/tests/tk_gate.py`
  and is made from the platform, not from the text of the error — a failed root **fails** the run
  where a windowing system is part of the platform and still **skips** where a display is
  genuinely optional. Any other exception propagates as itself. A structural AST guard prevents a
  new module from reopening the hole. **Developer-only; no production code is involved.**

### Changed — v0.6.1 version identity, and Plan 4 closed out (v0.6.1 Plan 4 Phase 15, 2026-08-22)

- `version.py` moved from `0.5.1` to **`0.6.1`**, with `config.toml` and the version guard tests
  updated in the same commit. **This is a version-identity closeout, not a release:** no tag, no
  GitHub release, no packaging, no publication, no `release.py` run, and no merge. There is
  deliberately **no `[0.6.1]` heading in this changelog**.
- The lasting Plan 4 record moved into `Briefing.md`, `Decisions.md`, `Handoff.md`, `README.md`
  and the master implementation index, and the temporary drop
  `md-instructions/0.6.1-tts-cover-workflows.md` was retired — **only** after that transfer, and
  with every gate re-run afterwards. `files/archived-code/epub-tts/` is permanent and stays.
- **Deferred, and recorded as deferrals rather than passes:** the Windows 125% display-scaling
  matrix; Windows DPI awareness; the `.DS_Store`-into-release-packaging defect found on the Mac
  (prototyped, deliberately **not** committed — packaging belongs to Plan 9); and a general
  pronunciation-override capability, which is a recorded future requirement and is **not
  implemented**. The one native `torch_cpu.dll` `0xC0000005` crash remains **historical,
  characterised and never reproduced — it is not claimed to be fixed.**

### Added — shared importing and job-control foundation (v0.6.0 Drop 3, approved 2026-08-10)

> Four new shared modules that **no production tool uses yet**. Plan 3 builds the importer and
> the run controls once so that Plans 4–8 can adopt them instead of growing six divergent
> versions. **Nothing a user can reach behaves differently:** the launcher still lists exactly
> six tools, no panel imports any of this, and `version.py` is still `0.5.1`.

- **`shared/importing.py`** — immutable import vocabulary (supported-type catalog, frozen
  per-import options, roots, occurrences, problems, requests, results and snapshots); a
  read-only, non-following traversal core that refuses symlinks, Windows junctions and other
  reparse points and reports them rather than walking them; natural ordering that emits a
  folder's compatible direct files before its child directories and sorts `1, 2, 10` correctly;
  optional hidden-folder inclusion, default off; and `ImportedFileManager`, which owns the
  ordered list, mints stable occurrence IDs, restores selection by ID after any rebuild, moves a
  multi-selected block as one unit, deduplicates by non-following file identity with an explicit
  per-import duplicate override, and commits transactions atomically. Removing or clearing the
  list never deletes a source file, and neither does anything else here.
- **`shared/import_coordination.py`** — one background scan at a time, with the broad-root
  warning raised **before** any worker is created, live discovered counts published on a queue,
  Plan 2's captured 1,000-result threshold confirmed **after** a completed scan, and an atomic
  commit that a cancelled, declined, failed, closed or conflicting import never reaches. Cancel
  Import is its own per-operation event with no connection to a processing job's cancellation.
- **`shared/job_control.py`** — a cooperative run controller that is truthful about what it can
  promise: a pause request stays "Pause requested" through an indivisible stage and becomes
  "Paused" only on the worker's acknowledgement, cancel wakes a paused worker and reaches
  "Cancelled" only after cleanup, and no thread or process is ever suspended. Plus one frozen
  configuration per run, a UI-neutral lock and action-availability derivation, ordered item
  outcomes that do not let one item failure fail the job, Retry Failed built against the exact
  original snapshot, typed events with stale/post-terminal rejection, a Summary that
  structurally cannot show a raw command or traceback while Details keeps every one, a bridge
  into the **one existing** session logger, progress that never rounds an unfinished run up to
  100%, and a conservative current-run ETA that says `Calculating…` rather than guess.
- **`shared/job_ui.py`** — narrow compositional Tk adapters for the above: one main-thread queue
  pump owning the single `after` chain, explicit thread ownership that rejects a worker's widget
  access before any widget is touched, reuse of the existing shared `ProgressIndicator`,
  close-safe idempotent teardown that leaves no callback behind, `ACT.*` styles on Windows with
  no generic ttk style touched, and the native macOS/aqua appearance preserved by asking for no
  style at all.
- **Developer-only manual harness** `files/tests/manual_plan3_harness.py`, used for the Windows
  manual matrix. It has no launcher entry, is never collected as a test, is imported by nothing
  under `scripts/`, ships in neither release archive, and runs no real work.
- **1,460 tests** across nine focused suites, including structural guards proving the three
  Tk-free modules import no Tk, that no production module or launcher adopts any of this, and
  that no runtime dependency was added.

### Changed — Plan 3 closed out (v0.6.0 Drop 3 Phase 10, 2026-08-10)

- The lasting importing/job-control architecture moved into `Briefing.md`, the non-obvious
  Plan 3 choices into `Decisions.md`, and the final verification, approvals and deferrals into
  `Handoff.md`. The master implementation index now records Drop 3 as complete and approved and
  awaiting integration, with Plan 4 as the next unopened plan.
- The temporary drop `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` was retired,
  as its plan directs, only after that transfer.
- **No application source, packaging, screenshot or configuration change** is part of the
  closeout, and **no version bump, tag, release, publication, merge or branch deletion** was
  performed. The Windows manual matrix passed by explicit maintainer attestation; **exact
  100%-display-scaling confirmation was not independently recorded**, and **Windows 125% scaling
  and live macOS remain deferred, not passed**.

### Added — `config.toml` in both release archives (v0.6.0 Drop 2 Phase 8, 2026-08-07)

> Both platform archives now ship the committed root configuration, and the maintainer's
> unrelated untracked `config-template.toml` is proven absent from both. `version.py` remains
> `0.5.1`; no release was built, published or tagged.

- **`shared/release.py`** gained a named `ROOT_FILES = ("README.md", "config.toml")` list. The
  packager still walks exactly one tree (`scripts/`) and names its root files explicitly, so a
  file it does not name cannot leak because an exclusion list was forgotten. `config.toml` is
  packaged byte-for-byte as committed — never generated, edited or substituted.
- **34 new packaging tests** (`files/tests/test_release_packaging.py`): `config.toml` present
  exactly once at the root of each archive and byte-identical to the committed file;
  `config-template.toml` absent even while it sits beside it; only the correct platform launcher
  included; the macOS `.command` stored with mode `0o755`; no member absolute, traversing,
  duplicated or escaping the extraction root; no runtime, developer or maintenance state; a
  deterministic manifest across two builds; the version sourced from `version.py`; and the
  packager never imported by the application nor part of startup.

### Fixed — MP3 Combine on paths containing an apostrophe (v0.6.0 Drop 2 Phase 8, 2026-08-07)

- **`mp3_tools/mp3_tool.py`** wrote ffmpeg concat-list entries with `'` escaped as `\'`.
  Inside single quotes ffmpeg treats every character literally, so that backslash escaped
  nothing and the quote was read as the **closing** quote: the path truncated there and
  *Combine MP3s → One MP3* produced no output on both the fast and safe paths. It now uses
  ffmpeg's documented close-escape-reopen form (`'` → `'\''`) and leaves backslashes untouched
  (they were previously doubled, which only survived because Windows collapses repeated
  separators). The list is written UTF-8; a path containing a line break is refused rather than
  producing a listfile the line-oriented demuxer would misread.
- **25 new tests** (`files/tests/test_mp3_concat_paths.py`) pin the representation and run the
  **real ffmpeg binary** across plain, space, one-quote, many-quote, Unicode and combined
  directory names, quotes in the filename as well as the parent, input ordering, source
  byte-identity, and the no-shell-invocation contract.

### Fixed — stale output location after a preference change (v0.6.0 Drop 2 Phase 8, 2026-08-07)

- A tool panel built **before** the output base changed kept displaying the old location until
  it was rebuilt. `shared/output_paths.py` now keeps a small registry of those read-only
  displays; a successful Preferences **Save** or **Reset** re-points every live registration
  through the same `destination_hint` resolution. Rejected, cancelled and failed changes never
  reach a panel, no panel is rebuilt or destroyed, none gained a constructor argument, and run
  reservation still re-reads the effective configuration at operation start.
- **41 new tests** (`files/tests/test_output_location_refresh.py`) cover all six panels'
  registration, Save, Reset, invalid, cancelled and failed-write paths, and that the displayed
  destination is where a run actually lands.

### Changed — Plan 2 closed out (v0.6.0 Drop 2 Phase 9, 2026-08-08)

- The lasting configuration/output/maintenance architecture moved into `Briefing.md`, the
  non-obvious Phase 8 choices into `Decisions.md`, and the final verification, approvals and
  deferrals into `Handoff.md`. The master implementation index now records Drop 2 as complete
  and approved, with Drop 3 as the next unopened drop.
- The temporary drop `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md` was
  retired, as its plan directs, only after that transfer.
- **No application source, packaging, screenshot or configuration change** is part of the
  closeout, and **no version bump, tag, release, publication, merge or branch deletion** was
  performed. Two validations remain explicitly **deferred, not passed**: live macOS, and the
  Windows 125% scaling matrix (held for the later UI-compression/no-scroll phase).

### Added — Safe post-exit cleanup and result reporting (v0.6.0 Drop 2 Phase 7, 2026-08-06)

> Clear Downloaded Data now completes: the request the Phase 6 flow builds is saved, handed to
> a separate helper process running outside the virtual environment, and executed only after
> the application has exited. The next launch reports exactly what happened. `version.py`
> remains `0.5.1`; nothing is released, tagged or merged.

- **New `shared/cleanup_state.py`** — the client half of the boundary. One project-owned
  maintenance folder at `files/runtime-data/maintenance/`, chosen rather than configurable,
  validated on every use to be inside the repository and outside all four removable targets.
  Requests, acknowledgements and results are written atomically (temporary file, flush, fsync,
  `os.replace`), so a crash can never leave a half-written request that reads as authorization.
  It removes only its own named state files and its own `.act-maint-` temporary writes.
- **New `shared/cleanup_worker.py`** — the coordinator, and the only code in the project that
  deletes a catalog asset. Standard-library only through its whole path, started detached with
  an argument vector and `shell=False` by a Python interpreter that is verified to be outside
  any virtual environment, and given its repository root by its own file location rather than
  by anything a request carries.
- **Acknowledgement before shutdown.** The app closes only after the helper has started, loaded
  *that* request, validated it, checked the root and state folder, and signalled it is ready to
  wait. Users see *"Cleanup is ready. Audiobook Creation Tool will now close…"* only then.
- **A truthful failure everywhere else.** A failed save, a missing verified interpreter, a spawn
  error, a timeout or a handoff that raised all produce *"Cleanup did not start. No data was
  changed, and Audiobook Creation Tool will remain open,"* the request is withdrawn, and every
  asset is left exactly as it was. Repeated clicks cannot start a second helper.
- **Exactly one attempt.** The helper waits for the requesting process to exit — bound to that
  precise process on Windows, so a recycled process id cannot satisfy the wait — retires the
  request *before* the first deletion, deletes once, writes one result, and exits. It never
  retries, loops or relaunches. Requests older than six hours are refused.
- **Deletion re-authorized at the last moment.** Every target is re-derived from its enumerated
  ID and re-checked for containment, protected paths, type and links immediately before acting;
  the earlier inventory is not treated as permission. `.venv` is removed entirely, the other
  three keep their folder and lose their contents, a missing target is a successful no-op, and a
  target swapped for a junction is refused rather than followed. Links found inside a target are
  detached, never descended into.
- **Failures are collected, not hidden.** A locked file fails that item, the pass continues
  through the rest of the tree and on to the later assets, and the result says which ones and
  why.
- **A report on the next launch**, shown once, listing every selected item as removed, already
  gone, failed or left alone for safety, with the space freed and recovery advice when anything
  was not removed. It never claims complete success if something failed, and a corrupt record is
  moved aside and never executed.

### Changed — Preferences hands off instead of failing closed (v0.6.0 Drop 2 Phase 7, 2026-08-06)

- `shared/preferences_ui.py` now routes an accepted confirmation to the real handoff and closes
  the application once it is acknowledged. It still imports no `os`, `shutil` or `subprocess`,
  still calls no deletion or process primitive, and never imports the coordinator.
- `launcher.py` passes its ordinary close path to Preferences and queues the previous run's
  report after the configuration warnings. A launch with no maintenance state does no extra
  work.
- `shared/maintenance.py` gained the approved handoff wording, the report wording and public
  path helpers so the coordinator applies the same link and containment rules rather than a
  second implementation of them. It still deletes nothing and imports neither `shutil` nor
  `subprocess`.
- **`bootstrap.py` and both root launchers are unchanged.** A removed `.venv` already falls
  through their fast path to the ordinary setup that rebuilds it; routing cleanup through
  `bootstrap.py` was rejected because importing it holds a log file open inside one of the
  removable targets.

### Added — Downloaded-data inventory and confirmation (v0.6.0 Drop 2 Phase 6, 2026-08-04)

> The Clear Downloaded Data flow now exists end to end **except the deletion**. Phase 6
> inventories, lets the user select, confirms in the strongest terms, and builds one immutable
> request. **Nothing is deleted, scheduled, spawned or written.** The post-exit coordinator that
> acts on a request is Phase 7 and is not implemented. `version.py` remains `0.5.1`.

- **New `shared/maintenance.py`** — platform-neutral, Tk-free, and provably non-destructive: it
  imports neither `shutil` nor `subprocess`, calls no deletion or process primitive, and defines
  no executor, coordinator or persistence function. Tests assert all of that structurally.
- **A closed catalog of exactly four assets** — `virtual_environment` (`.venv`),
  `portable_binaries` (`files/bin`), `downloaded_models` (`files/runtime-data/models`) and
  `application_logs` (`files/runtime-data/logs`) — held as frozen dataclasses behind a
  `MappingProxyType`, so it cannot be extended at runtime. Settings, `config.toml`, outputs,
  source media, repository source/docs/tests and anything system-installed are absent by
  construction, and system ffmpeg is called out as never removed.
- **IDs map to paths in exactly one place.** `authorized_target()` takes an always-explicit
  repository root and returns a path only after proving it is the exact compiled target, inside
  the root, not the root, not equal to / inside / containing any protected location, and not
  reached through a symlink, junction or reparse point at any level. Normalisation uses
  `abspath`, never `resolve()`, so a link is detected rather than followed.
- **Read-only size estimation** using `scandir`/`lstat` only. It never follows a directory link,
  tolerates files vanishing mid-walk, and reports an unreadable subtree as an *incomplete*
  estimate — shown as `1.2 MB (at least)` — instead of raising or inventing an exact total.
- **Safe selection defaults.** Every checkbox is created unchecked on every open, missing and
  unsafe items have no usable control, `Review Selected Data…` stays disabled until something
  eligible is deliberately ticked, and no selection is ever persisted or restored. Reset
  Preferences remains a separate action.
- **Immutable, versioned request and result schemas** (schema version 1) carrying enumerated
  asset IDs only. Neither schema has a `path`, `target`, `directory`, `root`, `command` or
  executable field, so no string from JSON, TOML or a widget can name something to delete.
  Validation runs in `__post_init__` and deserialization uses a strict allowlist where a missing
  *or* extra field is a refusal. The result schema is defined for Phase 7 to consume; Phase 6
  never creates one.
- **The Clear Downloaded Data dialog** replaces the Phase 2 disabled placeholder. Sizes are
  measured on a worker thread with every Tk update returned to the main thread, so opening the
  dialog never stalls and closing it mid-walk updates nothing.
- **One custom confirmation**, never a generic Yes/No box, rebuilt from the live selection every
  time and impossible to suppress. Cancel is the focused default and is what Escape and the
  window-close control both do; the destructive button is `Clear N Selected Items and Close` and
  is never the default.

### Changed — the Preferences cleanup entry is live, but still fails closed (v0.6.0 Drop 2 Phase 6)

- Accepting the confirmation builds one validated request and hands it to an injected callback —
  and nothing else. In production that callback is `unavailable_cleanup_handler`, which refuses,
  so the dialog reports *"Cleanup did not start. Safe post-exit cleanup is not available yet. No
  data was changed, and Audiobook Creation Tool will remain open."* and both windows stay usable.
  A callback that raises is treated the same way, so a future coordinator failing can never leave
  the app claiming success.
- The Phase 2 scope guards moved to the Phase 7 boundary rather than being relaxed: Preferences
  may now open the review, but still may not delete, spawn, persist or close anything.

### Added — Cover Image source-side modes and M4B Maker custom destination (v0.6.0 Drop 2 Phase 5, 2026-08-04)

> The two destination exceptions Decision 10A allows, both opt-in and both off by default.
> Standard modes are unchanged and remain the default. `version.py` remains `0.5.1`.

- **Cover Image: `Save beside source images`** replaces the Phase 4 disabled placeholder. It is
  off on every fresh build, exposes exactly `Create numbered copies` (preselected) and
  `Replace original files` (never the default), and switching it off resets the action — so a
  Replace selection cannot survive as a hidden mode. Nothing about it is persisted.
- **Numbered copies** write beside each source starting at `stem-1.ext`, because beside a source
  the unnumbered name *is* the source. Collision sequences are tracked **per source directory**,
  so two same-named images in different folders each get their own `-1`. Sources are never
  opened for writing, and no standard run is reserved.
- **Replacement requires three independent gates** — the toggle, the radio, and a per-run
  confirmation titled *"Confirm replacement of original images"*. Cancel is the focused default,
  Escape and closing the window cancel, the destructive button is labelled
  `Replace N Original Files`, the exact captured count is shown, and the dialog is rebuilt every
  run so nothing can be remembered or suppressed. Declining creates no run, no output and no
  temporary file.
- **Replacement is atomic.** Each source is validated *before* the dialog (links, missing files,
  directories and formats that cannot round-trip in place are refused there). Then a complete
  `.act-tmp-…` sibling is written **in the source's own directory** — same filesystem, so the
  install can be atomic — the finished image's size is validated, and only then does
  `os.replace` install it. **Never delete-then-rename.** A failure or cancellation before that
  boundary leaves the original byte-for-byte unchanged and removes only this operation's own
  temporary file. A partial batch reports truthfully: files already installed stay installed.
- **M4B Maker: `Choose custom destination`.** Off on every fresh build; the path and Browse
  controls exist only while it is on, and the widget is read in exactly one place, so a stale
  hidden path cannot steer a standard build. The chosen directory is validated before anything
  starts — absolute, existing, a directory, not a link, and writable, proved with a temporary
  probe that is removed again so no user file is created or touched. The finished `.m4b` goes
  **straight in with no nested `M4B-Maker-N`**, using the same sanitisation and collision
  numbering as everywhere else. Imported MP3s and the cover image are only ever read.
- **New shared APIs** in `output_paths.py`: `SourceSidePlanner`, `temporary_sibling()`,
  `discard_temporary()` (refuses anything without the `.act-tmp-` prefix), `atomic_replace()`
  (refuses to install a non-temporary file, and refuses a linked target),
  `validate_source_for_replacement()`, `validate_custom_destination()`, and a `start_index`
  argument on `DestinationPlanner.plan()`.

### Fixed — cancelling a custom-destination build would have deleted the user's folder (v0.6.0 Drop 2 Phase 5)

- The Phase 4 cancellation path ran `shutil.rmtree(out_dir)` unconditionally, which is correct
  for a reserved run that belongs entirely to one build — but in the new custom-destination mode
  `out_dir` **is the folder the user chose**, so cancelling would have destroyed it and
  everything in it. Cancellation now removes only this operation's own staging directory and its
  own partial output; the reserved-run branch is unchanged. Found while wiring the custom mode,
  before it could ship. Covered by a source-level guard test asserting the destructive `rmtree`
  sits behind the custom-mode check.

### Added — Phase 5 regression coverage (v0.6.0 Drop 2 Phase 5)

- `files/tests/test_cover_source_side.py` (34) — numbered-copy planning and collisions,
  per-directory independence, duplicate imports, no output-base writes, confirmed replacement,
  temporary-sibling placement and uniqueness, injected write/validation/replace failures all
  preserving the original, cancellation, partial-batch truthfulness, no source opened for
  writing before the boundary, link/missing/directory/unsupported-format refusal, and the full
  confirmation contract (count, plural, wording, focused Cancel, Escape, window close, fresh
  dialog per run, no suppression path).
- `files/tests/test_maker_custom_destination.py` (31) — toggle state and visibility, stale-path
  inertness, no persistence, every destination-validation rejection, validation failure
  reserving no run, direct output with no nested run, sanitised titles, existing and planned
  collisions, the final-suffix rule, containment, staging and cleanup boundaries, source safety,
  and no Plan 7 behaviour.
- Phase 4's Cover placeholder tests were superseded by Phase 5 state tests, and two Phase 4
  scope guards were retargeted from "no exceptions exist" to "exactly these two exist".

### Changed — all six tools now write to the configured output base (v0.6.0 Drop 2 Phase 4, 2026-08-03)

> **This changes where finished files appear.** Standard outputs move from
> `Downloads/<Tool>-N` to `<output base>/<Tool>-Outputs/<Tool>-N/`, where the base defaults to
> `Downloads/Audiobook-Creation-Tool-Outputs` and is changed in Preferences & Data. No release
> has shipped; `version.py` remains `0.5.1`.

- **Every output-producing action reserves its own run at validated start.** TTS Convert, M4B
  Converter Convert, MP3 Tool Combine / Time Edit / Write ID3, M4B Maker Build, Cover Image
  Resize, and the M4B Metadata Editor's Write Tags / Clear All Tags / Remove Series Numbering
  each reserve one atomic run directory **after** their inputs validate. Opening the launcher,
  building a panel, importing, browsing, switching tools or failing validation now creates
  **no directory at all** — previously five panels picked a `Downloads/<Tool>-N` number at
  `build_ui()` time and froze it for the whole session.
- **Duplicate filenames can no longer overwrite each other.** All six tools plan destinations
  through the shared batch planner, so two imports with the same name from different folders
  produce `Book.mp3` and `Book-1.mp3`. The old `avoid_input_overwrite()` guarded only against
  writing *onto an input*, so this was a real silent-overwrite hole in the Converter, MP3 Tool
  and Metadata Editor.
- **Filenames go through one central sanitiser.** M4B Maker's local regex is gone; titles like
  `My<Book>:Title` become `My_Book__Title.m4b`, with Windows reserved names, control
  characters, trailing dots/spaces and length limits handled the same way everywhere.
- **Staging is contained.** MP3 Tool combine staging moved from `edited_mp3s-N` beside a
  user-chosen save path into the operation's own reserved run; M4B Maker's `build/` and the
  editor's copies were already per-run and now provably cannot reach another run, the tool
  parent or the output base.
- **Per-tool output Browse controls removed.** The output base is managed in Preferences & Data;
  a per-panel override would bypass it. Each panel now shows its tool folder read-only and
  names the actual reserved run once an operation starts. Input and cover folder history is
  unchanged. The M4B Maker's opt-in custom destination remains Phase 5 work.
- **Cover Image no longer writes beside your source images.** Standard resizes land in the
  reserved run. The *"Overwrite original files"* control is now **visible but disabled** and
  captioned *"available in a later update"*, its variable forced `False` and the captured
  worker parameter a literal `False`. Phase 5 owns the safe redesign — deliberate source-side
  mode, explicit numbered-copy/replace choice, strong per-run confirmation, atomic replacement.
- `paths.next_output_dir()` and `paths.avoid_input_overwrite()` are retained as documented
  dormant compatibility API; **nothing in the shipped tree calls either**, and a test enforces
  that. `mp3_tool.next_available_folder()` and `BASE_OUTPUT_DIRNAME` were removed outright.

### Fixed — `stem` reference orphaned during the Converter migration (v0.6.0 Drop 2 Phase 4)

- Routing the M4B Converter through the shared planner removed the local `stem` assignment
  while the metadata fallback title still referenced it, so every conversion failed with
  `name 'stem' is not defined` and produced no output. Caught by driving the **real worker** on
  a generated fixture — every planner-level test passed. `files/tests/test_tool_output_integration.py`
  now runs the actual Converter, Time Edit and Cover workers so this class of regression cannot
  pass again.

### Added — Phase 4 integration coverage (v0.6.0 Drop 2 Phase 4)

- `files/tests/test_tool_output_integration.py` (68 tests): nothing created by launcher
  startup, panel construction, tool switching or opening Preferences; no panel promises an
  unreserved run number; per-tool parents; sequential and 6-thread concurrent reservation;
  captured snapshots surviving a mid-run preference change; per-tool destination, collision and
  containment behaviour; the Cover placeholder's disabled state, forced-`False` variable and
  literal captured parameter; AST guards that reservation happens only in action handlers and
  that no Phase 5/6/7 or Plan 3 behaviour arrived; and real-worker runs for the Converter, MP3
  time-edit and Cover Image on generated fixtures.
- Existing tests updated for the new phase boundary: the Plan 1 editor surface lists drop
  `btn_browse_out`/`choose_outdir`, the copy-only collision assertions expect the approved
  `stem-1.ext` numbering, and the Phase 3 "no tool consumes the service" guards were inverted
  to "every tool consumes it".

### Added — shared output reservation, collision and mirroring services (v0.6.0 Drop 2 Phase 3, 2026-08-03)

> Foundation work on the v0.6.0 line. **No release has shipped**; `version.py` remains `0.5.1`.
> **No tool consumes these services yet** — Phase 4 migrates the six panels, so current
> user-facing output behaviour is byte-for-byte unchanged.

- **`scripts/Universal/shared/output_paths.py`** — the platform-neutral output foundation for
  `<base>/<Tool>-Outputs/<Tool>-N/`. Tk-free, subprocess-free, network-free, and independent of
  the working directory. **Planning is pure; materialisation is explicit:** every `plan_*`
  function, the sanitizer and the collision service touch nothing, and only
  `ensure_output_base()` and `reserve_run_directory()` create anything — directories only,
  never a file and never anything source-side.
- **Central tool-parent registry** — `TOOL_OUTPUT_PARENTS` derives the six folders
  (`TTS-Audiobook-Outputs`, `M4B-Converter-Outputs`, `MP3-Tool-Outputs`, `M4B-Maker-Outputs`,
  `Cover-Image-Outputs`, `M4B-Metadata-Outputs`) from the existing `paths.TOOL_SLUGS`, so a slug
  is never written down twice. An unknown tool key raises `UnknownToolError` instead of becoming
  an unchecked path fragment, and a test proves the mapping matches the launcher's six tools.
- **Atomic run reservation** — `mkdir()` without `exist_ok` is the correctness boundary: it
  either creates `<Tool>-N` or raises `FileExistsError`, so two concurrent runs can never claim
  the same number. There is deliberately no existence check first, because that is exactly the
  check-then-create race the plan forbids. The search is bounded, failures carry diagnostics,
  and `release_if_empty()` removes a reserved directory **only** while it is still empty.
- **Filename sanitisation** — reduces a path to its last component, strips control characters,
  replaces the Windows-forbidden set, normalises Unicode to NFC, strips trailing dots and spaces
  (Windows drops them on write, which would silently merge two distinct names), defuses reserved
  device names with or without an extension (`CON.txt` → `_CON.txt`), and truncates the stem to
  255 characters while preserving the extension. Only the **final** suffix is treated as the
  extension, so `Book 1.5 - Extras.m4b` keeps its title.
- **Collision numbering** — the requested name first, then `stem-1.ext`, `stem-2.ext`. A
  `DestinationPlanner` is created per run, never shared globally, and combines existing files
  and directories with names the batch has already planned, so two proposed outputs cannot
  select one destination before either file exists. Comparison is case-insensitive on every
  platform, deliberately: both shipping targets are case-insensitive, and an extra `-1` is a
  better failure than an overwrite.
- **Input protection and containment** — `assert_not_input`, `assert_outside_source_trees`,
  `assert_contained` (which normalises without requiring the path to exist, so an unresolved
  child is checked rather than assumed safe) and `assert_no_link_in`, which refuses a
  destination established through a symlink or junction **even when the link points back inside
  the root** — the case containment alone cannot catch. Nothing in this module deletes anything.
- **Pure path planning** — `plan_flat` (individually selected files land directly in the run
  directory without recreating parent trees, per Decision 31A), `plan_mirrored` (one declared
  root, relative parents preserved) and `plan_multi_root` (each root gets a collision-safe
  container, so `Books` and `Books-1` keep two trees apart). A source outside its declared root
  is rejected rather than silently flattened. Plans are frozen dataclasses of tuples.

### Changed — `paths.next_output_dir()` marked for removal (v0.6.0 Drop 2 Phase 3)

- Documented as a **compatibility wrapper scheduled for removal in Phase 4**: the pre-Plan-2
  behaviour (non-atomic check-then-create, computed at `build_ui()` time and frozen for the
  session, no configurable base, no tool parent). **Behaviour is unchanged** — five tool panels
  still call it — and `test_output_paths.py` records the exact five call sites, so a sixth
  caller fails the suite and Phase 4's removals are visible in the diff.

### Added — output-service regression coverage (v0.6.0 Drop 2 Phase 3)

- `files/tests/test_output_paths.py` (144 tests) covering base resolution (default, absolute,
  `~`, relative fallback, no env expansion, nothing created, cwd-independence, unwritable),
  the complete tool mapping and unknown-key rejection, reservation (layout, no files, existing
  directory skipped, repeat runs, **8-thread concurrency**, bounded failure, diagnostics,
  immutability, captured snapshot, empty-only release), sanitisation (every forbidden
  character, control characters, trailing dots/spaces, blank/`.`/`..`, reserved names with and
  without extensions, whole-path reduction, length limit, Unicode including NFC normalisation,
  spaces and apostrophes, determinism, final-suffix rule), collisions (existing file, existing
  directory, planned-only, combined, already-numbered names, sanitisation-induced, case-only,
  independent trackers, determinism, nothing created, bounded), safety (input equality,
  source-tree protection, containment, traversal, absolute-child injection, root-as-destination,
  non-existent children, link escape and link-back-inside-root, nothing deleted), and planning
  (flat, one-root, multi-root, duplicate root labels, same-stem files, sanitised components,
  determinism, immutability, no filesystem writes, no input modification, no escape).
- Windows note: directory-link tests run via **junctions**, which need neither Developer Mode
  nor elevation. The single file-symlink test skips on this machine with the exact reason
  (`WinError 1314`); the pure containment logic it guards is covered by the non-link tests.

### Added — Preferences & Data, once-per-launch warnings and Reset Preferences (v0.6.0 Drop 2 Phase 2, 2026-08-03)

> Foundation work on the v0.6.0 line. **No release has shipped**; `version.py` remains `0.5.1`.
> No tool-output behaviour changed and no downloaded-data cleanup exists yet.

- **`Preferences & Data…` in the launcher status bar**, on all three shells: an
  `ACT.Ghost.TButton` beside "Open log folder" on Windows, a native unstyled `ttk.Button` on
  macOS and Linux. Both `Ctrl+,` and `Cmd+,` are bound, so the conventional shortcut works on
  whichever platform emits it. The launcher holds the single live instance, so activating the
  entry point again **focuses** the open window rather than stacking duplicates.
- **`scripts/Universal/shared/preferences_ui.py`** — the non-modal dialog plus the launch
  warning window. Presentation only: every rule it enforces lives in the Phase 1 modules and
  is tested without Tk. Styles are looked up through `_style()`, which returns `""` where
  `theme["styles"]` does not exist, so macOS and Linux keep native rendering with no
  platform-specific logic in the file.
- **Output-location preference** — shows the effective base *and its source* (built-in
  default / `config.toml` / your saved preference), with default-or-custom radio choice, an
  editable path and Browse. Validation is the Phase 1 rule set: absolute or `~`-based only,
  relative paths rejected rather than resolved against the working directory, environment
  variables never expanded. **Saving stores a preference and creates no folder.** A successful
  save persists atomically and reloads the effective snapshot immediately.
- **Reset Preferences** — explains its scope, requires confirmation, clears mutable
  preferences only through the Phase 1 atomic reset, refreshes the visible fields and source
  line, and reports failure rather than claiming success. Cancelling changes nothing. It never
  edits `config.toml` and never touches `.venv`, models, binaries, logs, outputs or media.
- **Clear Downloaded Data placeholder** — visibly disabled, captioned "Available after
  downloaded-data management is implemented", and carrying **no command at all**, so there is
  nothing to invoke even if something re-enabled it. Phase 6 owns the real behaviour.
- **Once-per-launch configuration warning** — `config.take_launch_warning()` owns a
  platform-neutral guard (with `reset_launch_warning_guard()` for tests), and the launcher
  presents one non-modal window carrying the whole aggregated summary after the root window
  exists. Never one dialog per bad key, never a blocking `messagebox`, never a reason to fail
  startup; technical detail goes to the session log and stays out of the visible text.

### Fixed — a failed settings write left the in-memory cache ahead of the file (v0.6.0 Drop 2 Phase 2)

- `settings.set()` and `settings.update()` mutated the cache and then reported failure if the
  atomic write did not land, so the running application believed a preference that was never
  saved. Both now **roll the change back in memory** when the write fails, which is what makes
  the dialog's "the previous setting is still in use" literally true. Found while building the
  failed-save path; covered by regression tests in `test_settings.py` and `test_preferences_ui.py`.

### Changed — layout of the Preferences dialog to fit the supported minimum (v0.6.0 Drop 2 Phase 2)

- The first build measured **689×626 px under the Windows theme**, taller than the app's own
  `920×600` minimum. Entry/Browse/Save now share one row, Reset sits on its card's heading row,
  and the outer padding uses the tight end of the spacing scale. The bounded form is now
  **618×596 px on Windows and 630×488 px unstyled**, with no whole-dialog scrolling — local
  scrolling remains reserved for genuinely growing content, of which this dialog has none.

### Added — Preferences & Data regression coverage (v0.6.0 Drop 2 Phase 2)

- `files/tests/test_preferences_ui.py` (65 tests): entry-point wiring, keyboard reachability,
  both accelerators, single-instance/focus-existing behaviour, effective value and source
  display, every accepted and rejected output-base form, no-directory-creation, atomic save,
  failed-write rollback, immediate reload, reset confirm/cancel/success/failure, UI refresh,
  `config.toml` byte-identity, unrelated assets untouched, the disabled placeholder and its
  absent command, warning aggregation and deduplication, the once-per-session guard under a
  twenty-iteration reload storm, technical detail logged but not displayed, `ACT.*` isolation
  across dialog construction, the exact window constants, and the measured fit at `920×600`
  under **both** the Windows theme and the unstyled path.
- `test_repository_contract.py`'s Phase 1 "no GUI surface" guard moved with the phase boundary:
  the launcher may now name Preferences, but is AST-checked to define no cleanup function and
  call no destructive filesystem operation.

### Added — committed `config.toml`, the configuration core and the canonical-name gate (v0.6.0 Drop 2 Phase 1, 2026-08-03)

> Foundation work on the v0.6.0 line. **No release has shipped**; `version.py` remains `0.5.1`
> and there is no v0.6.0 heading. No GUI or tool-output behaviour changed in this phase.

- **Committed root `config.toml`** — the project's documented, commented, machine-agnostic
  defaults: `project.{name,version,python_min,entry_point,platforms}`, `output.base_directory`,
  `logging.max_sessions` and `importing.large_result_warning_threshold`. Safe to hand-edit: an
  unusable value falls back and is reported rather than stopping the application. Personal
  choices still live in the gitignored `files/runtime-data/settings.json`, which is the only
  file the application writes.
- **`scripts/Universal/shared/config.py`** — one typed, immutable `EffectiveConfig` snapshot
  (frozen dataclasses, tuples, `MappingProxyType`) built from **code defaults → valid
  `config.toml` values → the allowlisted mutable-settings overlay**. Per-key validation, so one
  bad value never discards a good neighbour; missing/malformed TOML falls back without raising;
  unknown sections and keys are ignored and reported once; `Diagnostic` records source, key, a
  human-readable fallback and separate technical `detail`; `warning_summary()` aggregates and
  deduplicates with no traceback in it; `get_effective()` / `reload()` / `invalidate()` give
  deterministic caching. Standard-library `tomllib` only — **no new dependency**. The module is
  Tk-free, takes injected paths for testing, and never creates a directory.
- **Output-base rules** — empty means `~/Downloads/Audiobook-Creation-Tool-Outputs`; a
  non-empty value must be absolute or `~`-based. A **relative path is rejected** instead of
  being resolved against the working directory, and environment variables are **never**
  expanded, so `%USERPROFILE%\…` and `$HOME/…` stay literal (and are therefore rejected).
  Resolving a base computes a path; nothing is created. Phase 3 owns run folders.
- **Settings reset and reload** (`shared/settings.py`) — `reset()` clears every mutable
  preference through the atomic temp-file-then-replace boundary; `save()`/`set()`/`update()`
  now **report success as a bool** instead of failing silently; `last_load_error()` explains a
  malformed file, which is **never rewritten during a load**; `use_path()` is the injection
  seam so tests never touch the maintainer's real preferences. Reset deliberately touches
  nothing but `settings.json` — no `.venv`, model, binary, log, output or source file.
- **Configurable log retention** — `logging_setup` reads `logging.max_sessions` through the
  effective configuration, importing it lazily inside the function so retention can read config
  while config never reads logging. Any failure at all falls back to 30; logging must come up.
- **Permanent documentation-name gate** — `verify.py` gained a `docnames` check that compares
  the **real directory entries** (`os.listdir`) against the exact canonical names, and a
  `config` check that fails on any diagnostic from the committed file.

### Fixed — `verify.py` was validating a document that no longer exists (v0.6.0 Drop 2 Phase 1)

- `scripts/verify.py` read `md-instructions/CHANGELOG.md`. That name has not existed since the
  documents were recased to `Changelog.md` / `Decisions.md` / `Handoff.md`, and the gate kept
  reporting `PASS` **only because a path lookup on Windows is case-insensitive** — on a
  case-sensitive filesystem the `docs` check would have failed outright. The reference is now
  canonical, and the new `docnames` check enumerates real directory entries so the same class
  of defect cannot hide again. **The documents were not renamed**; the reference was wrong.
- Remaining active references corrected to the canonical casing: `README.md`'s layout tree,
  `Briefing.md`'s pointers and cross-references, and `release.py`'s printed release checklist.
  Archived one-shot notes under `files/release-history/` keep their historical wording.

### Added — regression protection for the configuration contract (v0.6.0 Drop 2 Phase 1)

- `files/tests/test_config.py` (68), `files/tests/test_settings.py` (25) and
  `files/tests/test_repository_contract.py` (40) — 133 new tests. They pin down: the committed
  file is valid, documented and machine-agnostic; missing/malformed TOML, wrong types, out-of-
  range numbers, blank name, version drift, bad `python_min`, bad entry point and unknown
  platforms each fall back alone; unknown keys aggregate into one diagnostic; every output-base
  form (empty, absolute, `~`, relative, env-var, wrong type); precedence and the one-key
  overlay allowlist; malformed `settings.json` reported without being rewritten; atomic write,
  write-failure reporting and reset; cache invalidation; retention from config and its
  fallback; and that the gate **fails** a missing canonical file, any case-variant alias, a
  deleted permanent reference, an invalid config, version drift and malformed TOML — proved
  against temporary trees, because a case-insensitive filesystem will not let a real alias be
  staged beside the canonical file.
- Tests use temporary directories and injected paths throughout: none reads, writes or resets
  the maintainer's real settings, Downloads folder, logs, outputs, `.venv` or model cache.

### Added — Windows design system, converted launcher shell and M4B Metadata Editor (v0.6.0 Drop 1, approved 2026-08-02)

> Prototype work on the v0.6.0 line. **No release has shipped**; `version.py` remains `0.5.1`
> and there is no v0.6.0 heading. Approved against the ten-image evidence matrix under
> `files/UI-Prototype-Screenshots/v0.6.0-drop1/`.

- **Centralized Windows theme primitives** in `scripts/Universal/shared/ui_theme.py`: an
  explicit `win32` branch returning semantic colour roles (surfaces, text, accent, focus,
  status, field/selection/scrollbar, and the Shared Metadata surface), a metrics/spacing
  scale, a typography scale, and a `theme["styles"]` name map. Added `style_tk_widget()` for
  the classic Tk widgets ttk cannot style (`Canvas` / `Listbox` / `Text`), a no-op on
  non-Windows bundles. Panels read tokens from the bundle — no panel-local hex literals.
- **Namespaced `ACT.*` ttk styles** built by cloning recolorable `clam` elements into the
  live `vista` theme, so a dark control set is available without switching the application's
  base theme. No generic ttk style is created, reconfigured or re-laid-out, and there is no
  `option_add` / `tk_setPalette` anywhere in `scripts/`.
- **Redesigned Windows launcher shell** (`launcher.py`): navigation rail, header strip naming
  the active tool and its description, framed content card, and a status bar whose "Open log
  folder" action is a real focusable button. The active tool is marked with the ttk `selected`
  state instead of being disabled, so it stays keyboard-reachable. The six-tool registry and
  order, availability logic, lazy build-once containers, error panels, saved last-tool
  selection and panel-state preservation are all unchanged.
- **Converted M4B Metadata Editor** (`mp3_tools/m4b_metadata_editor.py`) — the only converted
  tool panel. The Windows presentation is a card layout (Audiobook Files, Shared Metadata,
  Chapter Titles, Output, a fixed action bar and a fixed Log); every other platform builds the
  historical layout byte-for-byte. `build_ui(parent)` is unchanged and gained an optional
  backwards-compatible `theme` argument.
- **Shared Metadata visual treatment** — the editor's existing batch-wide fields grouped on a
  distinct muted-accent surface with its own border, header and caption. Presentation only: no
  per-book override, no field precedence, no disabling, no workspace behaviour.
- **Developer-only Summary/Details specimen** (`files/tests/manual_windows_ui_prototype.py`) —
  a non-collected, launcher-unreachable fixture that renders production theme primitives and
  the production editor to reach deterministic populated, active-run and Summary/Details
  states for screenshots. The specimen carries an on-screen disclaimer; it adds no filtering,
  log buffers, ETA, retry or pause/resume behaviour to the product.
- **Ten-image approval evidence** committed under
  `files/UI-Prototype-Screenshots/v0.6.0-drop1/` — 1920×1080, maximized, five states at true
  100% and the same five at true 125% Windows display scaling.

### Changed — Windows navigation rail width (v0.6.0 Drop 1)

- `sidebar_width` 232 → **180 px** after measurement showed the wider rail cost the tool panels
  110 px of content width and clipped a primary action at the 920×600 minimum. This returned
  52 px of width to every panel at every window size. `MIN_SIZE` (920×600) and
  `DEFAULT_GEOMETRY` (1024×720) are deliberately unchanged.

### Added — regression protection for the classic panels and the non-Windows paths (v0.6.0 Drop 1)

- `files/tests/test_prototype_regression.py` (12 tests) plus extensions to
  `test_ui_theme.py`, `test_launcher_smoke.py` and `test_m4b_metadata_editor_ui.py`. Together
  they assert: the generic ttk styles are byte-identical before and after theme application,
  after the converted editor is built, and across a **whole application build**; the five
  unconverted panels (TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker, Cover Image Resizer)
  carry zero `ACT.*` styles; macOS aqua and Linux/other bundles build the historical editor
  layout; the copy-only output contract, the input==output collision guard and read-only
  originals hold in both workers; cooperative cancellation still runs through
  `shared.cancellation`; both build forks expose the same surface to every shared method; no
  Plan 3/6/8 control reached the shipped panel; and no new persisted setting was introduced.
- **Known and unresolved:** the application is DPI-unaware on Windows, so at 125% scaling
  Windows bitmap-scales the window (text is soft; nothing clips). Recorded as future work,
  not fixed in this drop.

### Added — Jenny Edge TTS voice (2026-07-19)
- **New Edge voice: Jenny (`en-US-JennyNeural`)** in `scripts/Universal/tts/voice_registry.py`,
  appended after Ava as the last en-US Female entry. Uses the same
  `_edge_preset(sentence=780, paragraph=830)` timing as Aria and Ava. Voice roster is now
  12 (7 Edge + 5 Kokoro); `files/tests/test_tts_smoke.py` counts updated to match.
- **Note:** this entry was requested as Sara (`en-US-SaraNeural`), but that voice is not
  offered by edge-tts — it exists in the paid Azure Speech Service, not the free Edge
  read-aloud endpoint that `edge-tts` queries. Confirmed against the live voice list: the
  only "Sara" match is `ta-LK-SaranyaNeural`, and the en-US female roster is Ana, Aria,
  AvaMultilingual, Ava, EmmaMultilingual, Emma, Jenny, Michelle. Jenny was substituted by
  maintainer decision. Shipping the unavailable ID would have added a dropdown entry that
  failed only at synthesis time.

### Changed — Jenny timing trim + pause-path measurements (2026-07-19)
- **Jenny's `timing_preset` trimmed:** `sentence 780→750`, `paragraph 830→800`
  (−30 ms each, ~4%). Title/chapter/end/trim/rate unchanged. No other voice touched.
- **Measured finding — the preset was not the driver.** Matched single-file renders of
  `00-intro-a-livid-lady-7` and `03-ch1-1-a-livid-lady-7` show Jenny's real inter-sentence
  gaps were already *shorter* than Steffan's (877 ms vs 951 ms on the intro; 894 ms vs
  984 ms on prose), despite near-identical presets. Ordering held at every silence
  threshold from −40 to −60 dBFS, so it is not a detection artifact. Steffan simply
  retains more residual trailing silence per chunk after `trim_tts_chunk_file`.
- **Root cause of the "stop-and-start" feel is the batch path, not the preset.**
  `batch_convert.run_batch_convert` accepts only `speaker` and `rate` — it never receives
  the five pause fields, and its pipeline (`split_into_chunks` → `synthesize_chunk_mp3` →
  `merge_mp3s`) does no sentence tokenization and inserts silence only *between* ~3000-char
  chunks (`CHUNK_PAUSE_MS = 50`) and at end of file. Every inter-sentence gap in a batch
  render is therefore Edge's own prosody. Measured batch-mode gaps: Jenny ~995 ms vs
  Steffan ~800 ms on prose (~195 ms gappier) — the inverse of single-file mode, and the
  mode the full-book test used. **Jenny's preset has no effect on batch/folder runs.**
- **Known-issue note:** `Briefing.md` states "Edge voices honor all five pause fields."
  That holds for single-file conversion only; Edge *batch folder* mode honors `rate` alone.
  (Briefing.md now states this limitation explicitly — it is deliberate, see the
  2026-07-19 DECISIONS.md entry.)

### Changed — batch-timing rework attempted and reverted; version 0.5.1 (2026-07-19)
- **A batch-timing-parity rewrite was implemented, measured, and reverted the same day.**
  Batch per-file conversion was routed through the single-file timing-aware engine (child
  subprocess per file) with per-path registry presets re-tuned to match every non-Jenny
  voice's old-batch cadence within −22…0 ms of its measured median gap. Despite hitting
  the numeric targets, the maintainer's A/B listening judged the new engine subjectively
  worse than the original batch method for every compared voice, and the entire change
  was reverted from the working tree before ever being committed. Batch mode is exactly
  the original chunk pipeline; no shipped behavior changed. Full rationale and the
  do-not-retry guidance: DECISIONS.md 2026-07-19.
- **Version bumped 0.5.0 → 0.5.1** (`shared/version.py`): the Jenny voice addition above
  is the sole functional change riding this bump.

### Added — v0.5.0 UX progress + metadata layout (2026-07-08)
- **Every tool now shows run progress.** New shared `ProgressIndicator` widget in
  `scripts/Universal/shared/ui_theme.py` — a ttk.Progressbar plus a "done/total  pct%"
  counter label with a main-thread-only `update / set_indeterminate / reset / finish`
  API. Wired into all six tools strictly through each tool's existing
  worker→queue→main-thread drain (the same channel that feeds its Log box), so workers
  never touch Tk. **Determinate** where a total is known: M4B Converter (files),
  Cover Image (images), M4B Metadata Editor (files — Save, Clear All Tags, and Remove
  Series Numbering), MP3 Tool (per track in the SAFE combine path; per file in
  time-edit and ID3), TTS (per file in Edge and Kokoro batch; per synthesis chunk in
  Kokoro single; per paragraph in Edge single — via new optional `progress_callback`
  parameters on `kokoro_file_to_mp3`, `read_book`, and `run_conversion_job`, additive
  and default-off so non-GUI callers are unaffected). **Indeterminate** where no total
  exists: the M4B Maker build (one long ffmpeg concat/encode with no observable
  sub-steps — its old bar was effectively dead, sitting at 0 until a single end jump)
  and the MP3 Tool's single-concat stages (FAST mode and the SAFE final concat).
  Cancel and the Log behave exactly as before on every tool. Shared code — Windows
  gets the same progress indication; the classic launcher layout is unchanged
  (proven by a stubbed-win32 construct, 6/6 tools, no error panels).
- **Tests:** `files/tests/test_ui_theme.py` gained a headless-guarded
  ProgressIndicator state-contract test (determinate label math, clamping,
  indeterminate switch and recovery, reset/finish semantics).

### Changed — v0.5.0 UX progress + metadata layout (2026-07-08)
- **M4B Metadata Editor layout.** The tag/settings sections (file actions, file list,
  tag form, chapter titles, output row) now live in a vertically scrollable canvas
  using exactly the TTS panel's wiring (wrap frame + Canvas + `create_window` +
  scrollregion/width sync + `shared.ui_theme.enable_mousewheel`), and the **Log is a
  fixed 14-row pane** below the scroll area next to the always-visible action buttons
  (was 8 rows and competed for space with the fixed-height sections above).
- **Stale launcher description fixed:** the M4B Metadata sidebar entry no longer reads
  "(Added in Phase 6.)" — it now describes the tool like the other entries.
- Removed a dead `progress_max` queue branch from the M4B Maker pump (nothing ever
  enqueued that message kind).

### Verified — v0.5.0 macOS component verify (2026-07-08)
- **Per-tool live pass on macOS complete — all six tools work end-to-end on a real Mac**
  under the new Finder-style shell (the `0.5.0-macos-component-verify` plan, Phases 1–5).
  Kickoff gates green (Python 3.12.13 venv, edge-tts imports, `kokoro_is_healthy` →
  `(True, 'ok')`, real `.command` fast-path launch); all 11 voice samples (6 Edge +
  5 Kokoro) generated on macOS and approved by maintainer listen; every tool exercised
  live with copy-based outputs and confirmed by the maintainer (screenshots reviewed).
  No macOS-specific breakage found — zero code changes this drop. **One caveat:** the
  M4B Converter was verified on a standard AAC-LC M4B; the Apple `aac_at` xHE-AAC/USAC
  decode path (the documented Windows limitation's macOS counterpart) remains unverified
  live — no USAC sample was on hand.

### Added — v0.5.0 macOS UI shell (2026-07-08)
- **Finder-style macOS launcher shell.** On macOS the launcher now uses the native
  `aqua` ttk theme (real macOS controls in every tool panel, automatic light/dark)
  with a Finder-style chrome: tinted source-list sidebar with hover + accent-color
  selection rows and per-tool glyphs, a toolbar strip naming the active tool, a
  hairline-bordered content card, and a refined status bar. All styling comes from
  the new `scripts/Universal/shared/ui_theme.py` (`apply_theme`), the single
  auditable platform split; fonts resolve to San Francisco via `.AppleSystemUIFont`.
  **Windows (and any non-mac platform) renders byte-for-byte unchanged** — the
  classic branch reproduces the pre-v0.5.0 look and was proven by constructing the
  launcher under a stubbed `win32` platform. The `build_ui(parent)` tool contract,
  lazy build-once/show-hide panels, last-tool restore, and load-error panel are all
  untouched. Setup/run was live-verified on a real Mac first (fresh `.venv` build →
  deps → ffmpeg → Kokoro healthy → GUI on screen).
- **Tests:** `files/tests/test_ui_theme.py` — headless-guarded theme smoke tests
  (current platform + stubbed win32/linux classic branches) and the
  `enable_mousewheel` wiring test.

### Fixed — v0.5.0 macOS UI shell (2026-07-08)
- **Mouse wheel / two-finger trackpad scrolling never worked on the TTS options
  panel** (pre-existing on Windows too — only dragging the scrollbar worked). The
  panel's wheel handler was armed by `<Enter>`/`<Leave>` on the canvas itself, but
  the form frame covers the canvas, so the pointer was always over child controls
  and the binding never installed (and would tear down on every crossing into a
  child). New shared helper `shared.ui_theme.enable_mousewheel(scroll_target,
  hover_region)` binds the crossing events on the panel's wrap frame and ignores
  `<Leave>` events with detail `NotifyInferior` (pointer moved into a child, still
  inside the panel); the Leave side is bound at the Tcl level because tkinter never
  delivers the crossing-detail field. Cross-platform fix in shared code — improves
  Windows and macOS alike. The other tools' Listbox/Text scrollers already scroll
  natively via Tk class bindings (verified live) and were left untouched.

### Fixed — v0.5.0 macOS component verify (2026-07-07)
- **Kokoro could never install on a Mac whose only Python is 3.13+** (the Drop 3 §2.4
  open issue, root-caused on a live Mac). The bootstrap built the venv on Python 3.13,
  but Kokoro's PyPI wheels require >=3.10,<3.13, so the requirements marker skipped the
  wheel and every launch-time self-heal repair failed with "No matching distribution
  found for kokoro==0.9.4". The cause was environmental (Python version), not
  `kokoro_synth.py`. `bootstrap.py` now (1) tries to install Python 3.12 (brew
  `python@3.12` + `python-tk@3.12`) before accepting a >=3.13 interpreter, keeping
  3.13+ only as a degraded Edge-TTS-only fallback, and (2) rebuilds an existing
  >=3.13 venv once a Kokoro-compatible (<3.13) base is available, so a previously
  broken install heals itself on the next setup run. Windows behaviour unchanged
  (it selects `py -3.12` directly and never enters these branches). New regression
  test: `files/tests/test_bootstrap_python_version.py` (the `_is_kokoro_compatible`
  version gate). Verified live: fresh setup on a 3.13-only Mac now produces a
  Python 3.12.13 venv with `kokoro_is_healthy` → `(True, 'ok')`.

### Fixed — v0.5.0 Drop 3 (TTS improvement & hardening, 2026-07-07)
- **Kokoro batch ignored the End-of-recording pause.** The batch path never passed
  `end_silence_ms`, so every batch MP3 got the baked-in 3000 ms default regardless of the
  GUI field. Batch now honors it exactly like single-file mode.
- **Kokoro voices ignored the "After each paragraph block" field.** The GUI showed the
  pause fields for Kokoro voices but passed none of them. The paragraph pause is now
  mapped onto Kokoro's inter-chunk gap (single-file AND batch), verified end-to-end with
  the real model (200 → 2000 ms setting produced exactly +1800 ms of output). The
  sentence / title / chapter fields remain Edge-only for now — a deliberate deferral,
  see DECISIONS.md.
- **Batch folders-of-folders no longer collide.** Batch discovery always recursed into
  subfolders (`rglob`) but wrote every MP3 flat into the output root, so two files with
  the same name in different subfolders silently overwrote each other, and Resume
  matched the wrong file. The output now mirrors the input subfolder tree (both the
  Edge and Kokoro batch paths); Resume and the per-file temp chunk dirs follow the
  mirrored path. Folders with files directly inside keep the exact flat layout as before.

### Added — v0.5.0 Drop 3
- **Batch folder mode accepts `.txt` alongside `.pdf`** on both engines — pre-extracted
  text chapters no longer need to be PDFs. Mode label is now "Batch folder (PDF / TXT →
  MP3)".
- **`tts/generate_voice_samples.py`** — dev/QA helper (never imported by the app) that
  writes one short sample per registered voice into `files/test-for-manual-listen-elmatthe/`
  (gitignored). First run: 11/11 voices OK.
- **Tests:** `files/tests/test_batch_convert_folders.py` (mirroring, same-stem collision
  safety, `.txt` bypasses the PDF extractor, flat regression, mirrored Resume) and
  `files/tests/test_kokoro_timing_wiring.py` (fake pipeline proves `end_silence_ms` /
  `chunk_pause_ms` actually reach the output audio).

### Added — v0.5.0 Drop 2 (shared-metadata detection, 2026-07-07)
- **M4B Metadata Editor: batch shared-value detection.** Loading multiple files (or a
  folder) now pre-fills every tag field whose value is identical across ALL loaded files
  (Author/Artist, Album, Series Name, Genre, Year, …); fields that differ are left blank
  and reported as "(varies)" in the mode line and series read-back. A shared Series Name
  left unedited is still not written back (preserve-by-default, unchanged); shared
  non-series fields left unedited are written back byte-identically, matching the
  existing batch rule (maintainer ruling — see the Drop 2 notes in handoff.md).
  Single-file behaviour is unchanged. Unreadable files are logged and excluded from the
  detection instead of aborting the load. `series_part` is never pre-filled (still owned
  solely by the Auto-number toggle).
- **M4B Metadata Editor: "Open Folder…" button** — loads every `.m4b`/`.m4a`/`.mp4`
  directly inside a chosen folder (non-recursive; the "No audiobooks found" message says
  subfolders aren't searched). One action to load a whole series folder.
- **QA: Jack Ryan finished-product inspection test**
  (`files/tests/test_jack_ryan_final_product.py`, gated on `JACK_RYAN_M4B_FOLDER`) —
  asserts every book in the local Jack Ryan fixture set (built with every tool except
  TTS) has title, author, embedded cover, titled chapters, integer series parts, and one
  consistent series name. First run: 14/14 PASS, no findings. Plus
  `files/tests/test_m4b_metadata_editor_shared.py` covering the shared/varies detection
  rules.

## [0.5.0] - 2026-07-06

### Changed
- **Repository restructured to the AI-WORKSPACE standard layout — no user-facing tool
  changes.** The two mirrored per-OS root trees (`Windows/`, `MacOS/` — byte-identical
  except two dead legacy files) collapsed into a single cross-platform code tree at
  `scripts/Universal/` (git-mv, history preserved), with `scripts/Windows|MacOS/` kept
  as empty homes for any future truly-OS-specific code. Runtime-writable state moved to
  `files/runtime-data/` (logs, settings.json, and the ~300 MB Kokoro HuggingFace model
  cache) and the portable-ffmpeg fallback to `files/bin/` — both gitignored, so
  "delete the folder to fully uninstall" still holds. Dev-only assets moved under
  `files/` (tests, test fixtures, test logs, Dockerfile, v0.3.1 release one-shots →
  `files/release-history/`). The venv now lives at the repo root (`.venv/`). All paths
  derive from `shared/paths.py`'s `REPO_ROOT`; `bootstrap.py`, `release.py`, and the
  root launchers were rewired accordingly. Every existing behaviour was preserved and
  re-verified: the Windows `pythonw` no-console fast path, the macOS Gatekeeper/App-
  Translocation guard, and the Kokoro/venv/ffmpeg self-heal on every launch.
- **One `md-instructions/` set instead of two.** The duplicated per-OS
  Briefing/CHANGELOG merged into single canonical files; new permanent `DECISIONS.md`
  (ADR log) and `handoff.md` (live state + session sync) added; Briefing rewritten to
  current state.
- **Root launchers renamed** to `Setup_and_Run-audiobook-creation-tool.bat` /
  `.command` — still the only two files a user ever touches.
- `release.py` now packages README + the OS launcher + the single `scripts/` tree into
  both OS zips (previously zipped each per-OS tree).

### Added
- `scripts/verify.py` — mechanical release gate: runs the pytest suite in
  `files/tests/`, checks every dependency in `scripts/requirements.txt` is `==`-pinned,
  and checks the permanent docs are de-templated. Behaviour-preservation smoke tests
  added per tool in `files/tests/`.

### Fixed
- **No more ffmpeg console windows flashing during the TTS combine stage.** When a
  conversion finished and pydub/edge-tts stitched the per-segment MP3s together, each
  internal ffmpeg spawn popped a `ffmpeg.EXE` console window on screen — dozens in a
  row, stealing focus from whatever else the user was doing. The app's own ffmpeg calls
  were already hidden via `shared.subprocess_utils`, but pydub's *internal* spawns
  bypassed that wrapper. Added `install_no_window_guard()` (Windows-only, idempotent),
  which wraps `subprocess.Popen` itself so every child process — including pydub's —
  inherits the hidden-window flags. Installed once at the top of `launcher.main()`,
  before pydub/edge-tts are imported. No-op on macOS; both script trees stay
  byte-identical.

### Removed
- All copyrighted web-novel test fixtures stripped from git history via
  `git filter-repo`. The entire `test-files/` folder is now gitignored and
  will never be tracked again. Use the `KOKORO_TEST_PDF_FOLDER` env var to
  point the voice-test harness at a local folder of input PDFs.

## [0.4.0] - 2026-06-05

### Fixed
- **Bootstrap now self-heals a missing/broken Kokoro install on every launch.** The
  fast-path (`.venv` exists → launch GUI) previously skipped Kokoro entirely, so a
  partial first-run install or a manually-uninstalled `kokoro` package would silently
  break the AI voice path until the user ran a Kokoro batch and saw 10 chapters fail
  in a row with `No module named 'kokoro'`. `bootstrap.py` now probes the venv for
  `kokoro` + `soundfile` + `scipy` before every launch (both the `--launch-only`
  fast-path used by `setup_and_run` and the `venv_is_valid()` path) and pip-installs
  the pinned versions into the existing venv if any are missing, showing a small
  "Repairing the Kokoro AI voice install…" progress window with a live log. The repair
  never blocks launch — if it fails, a clear warning is shown and the GUI still opens
  so Edge TTS keeps working. The `--skip-kokoro-download` flag and first-run opt-in
  checkbox are now scoped to the optional ~300 MB HuggingFace model weights only; the
  Python wheels are mandatory and always installed because they are required for the
  import to succeed. The first-run install now pre-warms the Kokoro pipeline to force
  Windows Smart App Control / WDAC to evaluate Kokoro's unsigned native DLLs during the
  install dialog rather than during the user's first synthesis, and a single retry on
  OSError/RuntimeError/ImportError during the first in-process pipeline load absorbs
  any remaining transient DLL-load block.

### Changed
- **Kokoro model weights now live inside the project tree.** `HF_HOME` and
  `HUGGINGFACE_HUB_CACHE` are set to `resources/models/huggingface/` by
  `bootstrap.py`, `scripts/launcher.py`, and `scripts/tts/kokoro_synth.py`, so the
  ~300 MB model is part of the project folder instead of `~/.cache/huggingface/`.
  Keeps the user's home directory clean and makes the install fully self-contained
  (uninstall = delete the project folder).

### Added
- `scripts/tests/test_kokoro_voices.py` — verifies all five Kokoro voices
  (`af_heart`, `af_bella`, `am_michael`, `bf_emma`, `bm_george`) with a synthetic
  smoke test, a per-voice end-to-end PDF run, and a full 10-PDF batch run. Mirrored
  in both OS trees. (Tests B/C drive the real Kokoro path — `pdf_to_txt` →
  `kokoro_file_to_mp3` — since `run_conversion_job`/`run_batch_convert` are Edge-only.)

## [0.3.2] - 2026-06-04

> **MP3 output speed-up fix — real root cause was xHE-AAC, not a sample-rate mismatch.**
> The bug was confirmed on macOS with ffprobe: source M4B and the bad MP3 were **both 44100 Hz
> stereo**, so the originally-suspected sample-rate/`-ar` theory was wrong. The actual cause is the
> source codec profile. Verified on the real `test-files/Reincarnated as a Sword.m4b`: a 600 s
> source slice that previously produced a 454.6 s MP3 now produces a correct 600.0 s MP3. Fixed in
> the shared decode path; Win↔Mac `scripts/` byte-identical, `compileall` clean.

### Fixed
- **M4B Converter — MP3 output sped up and choppy for xHE-AAC audiobooks.** Converting some M4B
  audiobooks (e.g. newer Audible rips) to MP3 produced audio that played ~1.3× too fast with
  stutter/dropouts. **Root cause (ffprobe-confirmed):** the source is **xHE-AAC (USAC)**, which
  ffmpeg's *native* `aac` decoder cannot decode — it logs `Error submitting packet to decoder: Not
  yet implemented in FFmpeg, patches welcome` and silently drops ~24% of packets, so the decoded
  stream is much shorter than the source and, re-encoded to MP3, plays faster. It is **not** a
  sample-rate mismatch (source and output are both 44100 Hz stereo) and **not** a concat/`-ar`
  problem. Fixes:
  - The converter now **probes each source** via the new `ffmpeg_utils.probe_audio_stream()` and,
    for xHE-AAC sources, decodes through the **Apple AudioToolbox decoder (`aac_at`)** when it is
    available — on macOS this restores full-length, correct-speed output. Decoder selection is a
    **runtime** check (decoder availability), so the `Windows/` and `MacOS/` `scripts/` trees stay
    byte-identical.
  - A new **post-encode duration guard** compares the output length to the source and **fails the
    file (discarding it) when they differ by more than 3%**, so a source that cannot be decoded
    correctly on a given platform yields a clear error instead of a silently corrupt MP3.
  - The per-file log now shows a one-line **source summary** (codec/profile/sample-rate/channels)
    and the **full ffmpeg command**.
  - New shared helpers in `scripts/shared/ffmpeg_utils.py`: `probe_audio_stream`, `is_xhe_aac`,
    `input_decoder_args`, `needs_special_aac_decoder` (plus cached decoder detection).
  - **MP3 Tool and M4B Maker were not changed** — they ingest MP3, not AAC, so they never reach the
    AAC decoder path. (The original report listed them, but that was based on the disproven
    sample-rate theory.)
- **Release packaging could leak internal QA logs.** `release.py` builds the zips by walking the
  filesystem, so a gitignored `test-logs/` working file present on a dev machine could be packaged
  into the distribution zip (caught while rebuilding the v0.3.1 zips on Windows; the Mac build was
  clean only because that file never existed on the Mac). Added `test-logs/` to the packaging
  exclusions so internal QA logs never ship, regardless of which machine builds the release.
  (`scripts/shared/release.py` — both trees, byte-identical.)

### Platform note / known limitation
- **macOS is fully fixed** (`aac_at` decodes xHE-AAC). **On Windows, xHE-AAC is a known
  limitation.** Verified on the Windows host against `test-files/Reincarnated as a Sword.m4b`: the
  bundled ffmpeg (build `N-123884`, April 2026) has **no `aac_at`** and its native `aac` decoder
  also mis-decodes xHE-AAC (a 600 s slice decoded to 454.6 s, ~1.3× fast — the same
  `Not yet implemented` packet drop seen on the Mac). FFmpeg exposes no Windows decoder for xHE-AAC,
  so this is not fixable by a decoder flag. The new **duration guard** therefore **fails the
  conversion of an xHE-AAC source on Windows with a clear message** rather than shipping a sped-up
  file — no silent corruption, but such files cannot yet be converted on Windows. Ordinary AAC-LC
  audiobooks (the common case) are unaffected on both platforms.

## [0.3.1] - 2026-06-04

> **First live macOS pass — the macOS column is now green.** Verified end-to-end on a real Mac
> (macOS 26.3.1, Apple Silicon, Python 3.13 venv) against the real `test-files/` assets (41 `.m4b`
> audiobooks + a cover image + a TXT). Six launch/UX/packaging defects found and fixed on the way,
> all behind `sys.platform` guards (or in Mac-only entry files) and mirrored so the Windows↔MacOS
> `scripts/` trees stay byte-identical; `compileall` clean on both. No Windows behaviour changes.

### Fixed
- **macOS launch crash — Gatekeeper App Translocation.** Double-clicking the quarantined
  `setup_and_run.command` ran it from a temporary, read-only translocated copy with no `MacOS/`
  sibling, so `cd "$HERE/MacOS"` failed and the script exited **silently before Python ever ran** —
  the "Terminal flashes, no window, empty log" symptom. The launcher now detects a missing `MacOS/`
  sibling (or an `/AppTranslocation/` path), prints a clear, persistent "move the whole folder out of
  Downloads, then right-click → Open" message, and keeps the window open instead of dying silently.
  (`setup_and_run.command` — Mac-only entry file.)
- **A launcher crash on the fast path was invisible (no window, no log).** `bootstrap.launch_gui()`
  spawned the GUI inheriting the `.command`/`.bat`'s discarded stdio and returned success
  unconditionally, so any import/venv/Tk failure at launcher startup died to `/dev/null` — a clean
  `[Process completed]` with nothing to diagnose. It now redirects the GUI's stdout+stderr to
  `resources/logs/launch_<date>.log`, watches the child ~1.5 s, and returns failure (surfacing the
  captured tail) on an immediate crash; the macOS `.command` uses that to keep its window open and
  point at the log instead of closing silently. (`scripts/shared/bootstrap.py` — both trees; the
  Windows `.bat` does not consume the failure-return today, but the launch-log capture benefits
  Windows too.)
- **macOS "terminate running processes" dialog on close.** The fast path closed its own Terminal
  window with `osascript` while `bash` + `osascript` were still alive in that window, which is exactly
  what triggers Terminal's "Do you want to terminate running processes?" prompt (a self-close from
  within the doomed window is blocked by the modal). Added **`scripts/shared/close_terminal.py`**: a
  helper that detaches into its own session (`os.setsid`), waits for the launching `bash` to exit, then
  closes the window matched **by tty** — by which point the window has no running process, so the close
  is silent. The GUI itself is spawned fully detached (`start_new_session`). Verified on a real
  double-click: GUI comes up, Terminal window auto-closes, **no dialog**. (Helper is macOS-only — a
  no-op on any non-`darwin` platform; the `.command` wiring is Mac-only.)
- **Release packaging could ship a non-executable launcher.** `release.py` zipped the entry launcher
  with `ZipFile.write`, which only preserves the source file's *current* mode — a dev checkout that
  lost its `+x` bit (a clone with `core.filemode` off, a plain copy) would ship a `.command` the user
  had to `chmod +x`. Added `_write_executable()`, which stores the launcher entry with a forced
  `0o100755`; both `unzip` and macOS Archive Utility honour the stored Unix mode on extract (verified
  644 source → archive `0o755` → extracts `755`). (`scripts/shared/release.py` — both trees.)
- **TTS Audiobook log pane was crushed to ~1 px and the Start/Cancel buttons rendered off-screen.**
  The panel's natural height (~1300 px) far exceeds the window, and the log was the only weighted grid
  row, so Tk shrank it to nothing and pushed the buttons below the visible area. The options now live
  in a **vertically scrollable canvas**, with **Start/Cancel and a labelled 12-row monospace "Log"
  box pulled out into always-visible bottom rows** (matching the other tools). Verified the log stays a
  full ~12-row pane and the buttons stay on-screen at the default, minimum, and tall window sizes.
  (`scripts/tts/epub2tts_gui.py` — both trees, behind a `sys.platform` font branch.)
- **M4B Maker FAST path failed on an external cover image.** In `run_fast_concat` the output-only
  option `-filter:a` was emitted *before* the cover `-i`, so ffmpeg parsed it as an **input** option
  for the cover ("Option filter:a cannot be applied to cover.png") and fell back to the slower SAFE
  path. Reordered so all inputs are declared first, `-fflags +genpts` stays an input option on the
  concat demuxer, and `-filter:a` / `-avoid_negative_ts` move into the output section. The FAST path
  now embeds an external cover directly (verified via the GUI: cover + 3 chapters + series atoms, no
  fallback). (`scripts/mp3_tools/m4b_maker.py` — both trees.)

### Added
- **macOS test matrix — first live pass (green).** Drove every tool on a real Mac against the real
  `test-files/` assets: M4B Converter (41 `.m4b` → MP3, run through the GUI by the maintainer), and —
  via the real `build_ui` + button handlers + worker/queue — M4B Maker (chapters + external cover +
  series atoms) and the M4B Metadata Editor (write title/series, preserve untouched album + chapters;
  series-part display-only unless Auto-number is on). The remaining tools (MP3 Tool combine/time-edit/
  ID3, Cover Image letterbox+crop, TTS Edge TXT→MP3 + cancel) passed at the worker level. Kokoro
  voices remain skipped on this host (Python 3.13, above Kokoro's `<3.13` gate).

> Series & track numbering fix for the M4B Metadata Editor. Auto-numbering now lights up **all three
> surfaces** a reader looks at — the native track atom, the native movement atoms, and the freeform
> iTunes series atoms — and a new **Remove Series Numbering** action strips every one of them again.
> Verified end-to-end on Windows: a re-tagged 11-volume "Shadow Slave" set shows `#` 1–11 in File
> Explorer and groups as a numbered series in Audiobookshelf after a library rebuild. Win↔Mac
> `scripts/` byte-identical; `compileall` clean; headless round-trip self-test passed (trkn / movement
> / freeform all written and correct, chapter count unchanged, `clear_series_numbering` removes
> everything). macOS still awaits a live pass on a Mac.

### Added
- **M4B Metadata Editor — "Remove Series Numbering" action.** A new button beside "Clear All Tags
  (keep chapters)" that strips every series/track numbering surface from a **copy** of each loaded
  file — the native `trkn`, the movement atoms (`©mvn`/`©mvi`/`©mvc` plus legacy `mvnm`/`mvin`/`mvc`
  spellings), and every freeform `----:…:SERIES` / `…:PART` atom in any vendor namespace — while
  preserving chapters, cover art, and all other tags. Mirrors the Clear-All wiring exactly
  (copy-based, worker thread, Cancel, per-file ✓/✗ log). Backed by new
  `shared.metadata.clear_series_numbering`.

### Fixed
- **Blank Explorer `#` column (RC1).** `write_m4b_tags` now writes the native MP4 track atom
  `trkn = (part, total)` whenever a numeric series part is auto-numbered, so Windows Explorer's `#`
  column (and generic players that read `trkn`) shows 1…N. `write_m4b_tags` gained an optional
  `total` parameter; the editor passes `len(files)` so `trkn`/`©mvc` reflect the batch size.
- **Audiobookshelf not grouping app-tagged sets (RC2).** Alongside the existing freeform
  `----:com.apple.iTunes:SERIES` / `SERIES-PART` atoms, the writer now ALSO writes the native
  movement atoms `©mvn` (series name) / `©mvi` (index) / `©mvc` (count) when a part is supplied —
  belt-and-suspenders so grouping doesn't depend on a single namespace being honoured. The native
  atoms are written **after** the v0.1.2 conflicting-atom strip, so the strip only removes
  foreign-namespace duplicates and never the atoms just written.

### Changed
- **Movement-index atom constant corrected for read/write symmetry.** `MOVEMENT_INDEX_ATOM` was the
  non-canonical `"mvin"`; it is now the iTunes `"\xa9mvi"` (`©mvi`) that mutagen reads and writes
  natively, so the read path round-trips what the write path emits. The legacy `mvnm`/`mvin`/`mvc`
  spellings are retained only as strip targets in `clear_series_numbering`.

## v0.2.0 — Installer Hardening (macOS)

**macOS installer now self-heals on fresh machines with no Python/Homebrew/ffmpeg.**

- setup_and_run.command: replaces "first python3 wins" discovery with a
  GUI-capability probe (import tkinter; tkinter.Tcl()); only accepts a
  Python that can actually run the GUI.
- Auto-installs python-tk@3.12 + ffmpeg via Homebrew when a Tk-less
  python@3.12 is found; auto-installs Homebrew itself on a bare Mac (user
  is warned before the password prompt).
- bootstrap.py: new capability probes (tkinter, ssl, venv, functional
  Tcl/Tk, ffprobe); preflight report printed before setup begins.
- find_suitable_python now prefers a Tk-capable interpreter and falls back
  to Tk-repair before accepting a Tk-less one.
- Venv validation: post-creation capability probe on the venv interpreter
  (not just the base); self-heals by deleting and recreating a broken venv.
- Package validation: explicit import-test for edge_tts, pydub, fitz,
  mutagen, PIL, ebooklib, bs4, nltk after pip install; force-reinstalls on
  failure.
- ffmpeg: in-session PATH refresh after brew install (Apple Silicon +
  Intel); ffprobe added to checks.
- --headless mode: full venv + deps + ffmpeg + validation without requiring
  Tk; activated automatically when no GUI-capable Python can be found.
- launcher.py + epub2tts_gui.py: guarded top-level import tkinter with a
  clear CLI-fallback message instead of a raw _tkinter traceback.
- Windows path unchanged in behavior.
- Known: macOS clean-machine one-click install is correct by inspection and
  compile-verified but awaits a live pass on real Mac hardware before the
  macOS column can be marked fully green.

## [0.1.3] - 2026-05-30

> Update release batching three independent improvements staged off `master` since v0.1.2: a
> part-only / track-implied series-detection fix, a new auto-number Series Part toggle in the M4B
> Metadata Editor, and a launcher that always opens at its default size. `compileall` clean, the
> Windows↔MacOS `scripts/` trees byte-identical, and verified headless on Windows against the real
> `test-files/` assets (the Dungeon Crawler Carl, Trials of Apollo, and Mistborn M4Bs). macOS
> deferred (no host).

### Added
- **M4B Metadata Editor:** an **Auto-number Series Part** toggle, now the *sole* control over whether
  anything is written to the series-part tag. When **on**, the Series Part field is the starting
  number and sequential parts are written across the loaded files **in list order** (a single file
  gets just that number; a blank field starts at 1), with a live hint showing the exact range that
  will be written. When **off** (the default), the Series Part field is display-only and nothing is
  written to the series-part tag (preserve-by-default).

### Fixed
- **M4B Metadata Editor:** series position is now detected for files that carry only a track-number
  marker (e.g. `trkn = 4/5`) with the series name in Album/Grouping rather than a dedicated series
  atom. Series **name** and **part** now resolve independently: a name from `…SERIES` → `©mvn` → the
  album (album-implied); a part from `…SERIES-PART`/`…PART` → `mvin` → the track number (the last only
  when *series-like* — track total > 1 or an album/grouping name present, so an incidental track number
  on a standalone book is not turned into a fake part). Implied values (`album-implied` /
  `track-implied`) are display-only, with their source shown in the read-only "Detected on file" line;
  the album-implied name is never written unless the user types a Series Name, and the series-part is
  written only via the new auto-number toggle. Eliminates the false "no series tag" reading on such
  files.

### Changed
- **Launcher:** the window now always opens at its default size. Previous window size/position is no
  longer saved or restored; last-selected-tool memory is unchanged.

## [0.1.2] - 2026-05-30

> Patch release: a series-metadata read/display correctness fix in the M4B Metadata Editor.
> Phase-gated off `master`, `compileall` clean, Windows↔MacOS `scripts/` trees byte-identical,
> and verified live on Windows against the real `test-files/` assets (the Harry Potter &
> Mistborn M4Bs). macOS deferred (no host).

### Fixed
- **M4B Metadata Editor:** Series Name and Series Part now display the existing value from real
  Audible/Audiobookshelf M4B files. `read_m4b_tags` previously checked only the freeform
  `----:com.apple.iTunes:SERIES` atom, so it missed series stored in **other freeform namespaces**
  (real Audible rips tagged with Libation/tone use `----:com.pilabor.tone:SERIES` / `:PART`, which
  ffprobe and Audiobookshelf surface as `SERIES`/`PART`) **and** the native MP4 movement atoms
  (`©mvn`/`mvin`) — so the fields showed blank even when Audiobookshelf grouped the book into a series.
  The reader now resolves series from the canonical freeform atom first, then any other vendor freeform
  atom, then the movement atoms, and reports which atom it found.
- **`shared/metadata.py`:** writing a series value now also strips any *other* vendor freeform or
  movement atom that ffprobe (and Audiobookshelf) would surface under the same name — e.g. a leftover
  `----:com.pilabor.tone:SERIES`. Without this, the original atom **shadowed** the new write and the
  overwrite silently failed to take effect in Audiobookshelf. Blank fields are still never written, so
  this never disturbs an existing tag (preserve-by-default intact). The chapter-title re-mux still
  snapshots/restores the freeform atoms, so the series survives a later chapter-title import.

### Added
- **M4B Metadata Editor:** a read-only "Detected on file" line beneath the Series fields shows the
  original series value and its exact source atom (e.g. `(source: ----:com.pilabor.tone:SERIES)`), or
  "none — this file has no series tag", so an overwrite can be confirmed before and after writing. For
  multiple files it shows "(multiple files loaded)".
- **`shared/metadata.py`:** `read_m4b_tags` now returns series provenance (`series_source` /
  `series_part_source` ∈ `freeform` | `movement` | `None`, plus the exact `series_atom` /
  `series_part_atom`), and a new `describe_series_atoms(path)` helper lists every series-bearing atom on
  a file for diagnostics. Existing return keys are unchanged, so no callers break.

## [0.1.1] - 2026-05-30

> v0.1.1 update release. Phase-gated (A–F) off `master` with the same discipline as
> the 0–9 build: each phase code-complete + verified, `compileall` clean, and the
> Windows↔MacOS `scripts/` trees kept byte-identical before every commit. Verified
> live on Windows against the real `test-files/` assets (the real Harry Potter &
> Mistborn M4Bs, real Shadow Slave MP3s, a real JPG); macOS deferred (no host).

### Added
- **Phase A — shared output-folder resolver (`shared/paths.py`).** `downloads_dir()`
  and `next_output_dir(tool_name, *, create=False)` plus a canonical `TOOL_SLUGS`
  map (one user-visible folder slug per tool). `next_output_dir` returns
  `Downloads/<Tool>-N` for the lowest free `N` at call time; each tool computes it
  once at build time and the folder is created lazily on first successful write.
- **Phase C — "Clear All Tags (keep chapters)" in the M4B Metadata Editor.** A new
  button strips every standard + freeform iTunes metadata atom (title / artist /
  album / year / genre / comment / cover + `SERIES`/`SERIES-PART`) while leaving the
  chapter track — count, titles, timestamps — untouched, then re-applies only the
  tag fields the user actually edited (so an auto-prefilled single-file form is not
  re-applied over the clear). Implemented as `shared.metadata.clear_metadata_keep_chapters`
  (mutagen; verified to preserve chapters on a real 1.17 GB / 39-chapter M4B, so the
  ffmpeg fallback is not needed). Runs on the copy-based pipeline with Cancel.
- **Phase D — per-file positional chapter-title import in the Metadata Editor.** A
  paged "Chapter Titles (optional)" section (one page per loaded file, ◀/▶ pager,
  per-file buffer, a hint showing each file's chapter count) lets you paste new
  titles one per line: line N → chapter N, blank line = leave that chapter
  unchanged, extra lines ignored. Backed by `shared.metadata.read_chapter_titles` /
  `apply_chapter_titles` (an ffmpeg ffmetadata round-trip, since mutagen cannot edit
  MP4 chapter titles) — `-c copy` keeps audio + chapter timestamps byte-stable, and
  freeform `----:` atoms (series) are snapshotted/restored across the re-mux.

### Changed
- **Phase B — copy-based, non-destructive output across every transforming tool, with
  smart default folders.** The M4B Metadata Editor now copies each selected file into
  the output folder and tags the **copy** (mutagen), never the imported original.
  Every output-producing tool (TTS, M4B Converter, MP3 Tool, M4B Maker, Metadata
  Editor) defaults its output folder to a fresh `Downloads/<Tool>-N`, decided once at
  build time and created lazily on first write; **Browse** redirects it for the current
  run only and is **no longer persisted** across sessions (next launch resets to the
  next free `-N`). The legacy nested `*-output-N` subfolders are replaced by the single
  Downloads folder. Added `shared.paths.avoid_input_overwrite()` (input==output
  collision guard) and applied it in the Metadata Editor, MP3 Tool (time-edit + ID3),
  M4B Converter, and M4B Maker. The Cover Image tool keeps its sanctioned in-place
  overwrite toggle (and otherwise writes `Name-N` copies next to the source).

### Fixed
- **Metadata Editor (Phase C):** "Clear All Tags" no longer re-applies the values
  auto-loaded into the single-file form, which previously undid the clear — only
  fields changed from the pre-filled snapshot are re-applied.
- **`shared/metadata.py` (Phase D):** the ffmpeg chapter re-mux dropped the freeform
  Audiobookshelf `SERIES`/`SERIES-PART` atoms; they (and any `----:` atom) are now
  snapshotted with mutagen before the re-mux and restored after. Also fixed an
  ipod/mov muxer error by mapping only `0:a` + `0:v?` (not the file's text chapter
  stream) and rebuilding the chapter track via `-map_chapters`.
- **MP3 Tool (Phase B):** the bulk-ID3 path could tag the **original** file as a
  fallback when its working copy failed to write; it now skips that file instead, so
  an original is never modified. Time-edit / ID3 cancel no longer deletes the shared
  session output folder (finished outputs are left valid).

## [0.1.0] - 2026-05-29

### Added
- **Phase 9 (GitHub Remote + Public Release) — complete.** Created the public GitHub repo
  **[elmatthe/audiobook-creation-tool](https://github.com/elmatthe/audiobook-creation-tool)**, set
  it as `origin`, and pushed the full local history — all **8 branches** (`master`,
  `phase-2-bootstrap` … `phase-8-release`) plus the annotated tag **`v0.1.0`**; `master` is the
  default branch. Fast‑forward‑merged `phase-8-release` into `master` (linear history, clean ff) and
  tagged the merged commit `v0.1.0`. Built the two distributable zips with `release.py` and published
  the **GitHub Release**
  **[v0.1.0](https://github.com/elmatthe/audiobook-creation-tool/releases/tag/v0.1.0)** with both
  `AudiobookTool-Windows-v0.1.0.zip` and `AudiobookTool-MacOS-v0.1.0.zip` attached (both verified
  downloadable, HTTP 200). Added a **Download** section + TOC entry to the root `README.md` with direct
  links to the two release assets. `dist/` remains gitignored — the zips ship only as release assets,
  never committed. `compileall` clean one final time on both trees. No application code changed.
- **Phase 8 (README + Release Packaging) — complete (docs + dev tooling; no app code
  changed).** Wrote the CV-grade **`README.md`** at the repo root (root only, never duplicated
  into the OS trees): one-paragraph summary, six-tool feature list, an ASCII launcher mockup,
  Windows + macOS install steps, a system-requirements table (Python 3.11–3.12 for Kokoro, 3.13
  for Edge-only), a per-tool usage walkthrough, a full architecture section
  (`scripts/{tts,mp3_tools,shared}` layout + the thread-safety / console-suppression / atomic-settings
  / ffmpeg-isolation / cancellation design decisions), upstream credits (epub2tts-edge — Christopher
  Aedo, GPL-3.0; edge-tts; Kokoro-82M), a GPL-3.0 license section, and the known limitations. Added
  **`scripts/shared/version.py`** (`VERSION = "0.1.0"`, the single source of truth) and the developer
  packaging helper **`scripts/shared/release.py`** — a stdlib-only, never-imported-by-the-app tool that
  zips each OS tree (excluding `.venv/`, `__pycache__/`, `*.pyc`, `resources/logs/`,
  `resources/settings.json`, `resources/bin/`, `test-files/`) into
  `dist/AudiobookTool-{Windows,MacOS}-vX.Y.Z.zip`, placing `README.md` + the correct double-click
  launcher at each archive root, then prints the Briefing §13 release checklist. Verified the produced
  zips with `zipfile.namelist()` (README + correct launcher at root, OS tree nested, zero excluded
  leaks). `version.py` and `release.py` mirrored byte-identical to both trees; `compileall` clean.
- **Phase 7 (Cross-Platform Test Matrix) — complete on Windows (live verification pass; no
  feature code changes).** Ran every deferred live debug-gate item (Gates 2–6) and filled the
  Briefing §12 matrix against the real `test-files/` assets. **18/18 applicable Windows rows PASS,
  zero unresolved FAILs**; **no bugs found**, so Phase 7.3 changed no tool code. The runs drove the
  *real* worker code paths (not mocks): Edge-TTS **EPUB→MP3** (17.8 s) and **PDF→MP3** (13.1 s) over
  the network, a **2-file PDF batch**, a mid-run **TTS cancel** raising `ConversionCancelled` with
  **0 leaked temp dirs** (Gate 4), an **M4B Maker** build with 3 ffprobe-verified chapters +
  `series`/`series-part` atoms, an **M4B-encode cancel** that removed its partial output folder
  (Gate 5), an **M4B→MP3** convert, **MP3-Tool** combine/time-edit/ID3, a **Cover-Resizer**
  letterbox+crop (→512²), and the **Metadata Editor** single-file round-trip + multi-file overwrite +
  blank-field preserve (Gate 6). All on a working dir **with a space in its path**, including a
  **Unicode-named** file; settings persisted across a simulated restart; the launcher listed and built
  **all six tools** live (no error frames, ~1.25 s). **Gate 2** verified live: `bootstrap.py
  --self-test` clean and a throwaway venv resolved the **full pinned `requirements.txt`** against PyPI
  (kokoro correctly excluded on Python 3.13). **Console-flash** suppression is mechanism-verified
  (zero direct `subprocess.*` in tool code; `subprocess_utils` applies `CREATE_NO_WINDOW`+hidden
  `STARTUPINFO`; launcher under `pythonw`). Documented known-limitations (not failures): **fresh
  one-click install** (needs a clean machine + Python 3.12 + multi-GB torch/Kokoro — not run live) and
  **TTS Kokoro voice** (this box is Python 3.13, above Kokoro's `<3.13` gate). The whole **macOS**
  column is **SKIP (no Mac available)**. `compileall` clean on both trees.
- **Phase 6 (M4B Metadata Editor + Series Tags) — complete (new editor tool, series
  fields in M4B Maker, verified headless).**
  - Added **`scripts/mp3_tools/m4b_metadata_editor.py`** — a new tool that opens one or
    more existing M4B files and edits their tags **without re-encoding**, built on
    `shared/metadata.py`'s `read_m4b_tags` / `write_m4b_tags` (mutagen). Editable fields:
    **Title, Author/Artist, Album, Year, Genre, Comment, Series Name, Series Part**, and a
    **cover image** (Browse/Clear). It is **preserve-by-default**: a blank field is never
    written, so each file keeps its existing tag; a field with a value overwrites that tag
    in every selected file. **Single-file mode** pre-fills the form from the file's current
    tags (and notes if a cover is already present); **multi-file mode** shows a *batch*
    notice and starts blank. The Save runs on a **worker thread** with the standard
    **Cancel** button (idle-disabled / active-enabled, cooperative cancellation *between
    files* via `shared/cancellation.py`) and reports **per-file success/failure** in the log
    pane (one failure doesn't abort the batch). Exposes `build_ui(parent)` for the launcher
    and a standalone `main()` for debugging.
  - **Extended `shared/metadata.py` (additively) for the editor's fields.** Added the text
    atoms **comment (`©cmt`), genre (`©gen`), year (`©day`)** to the mutagen read/write
    mapping, plus **`cover_path`** (embed a JPEG/PNG as the front `covr` atom, or clear it)
    and a **`has_cover`** boolean from `read_m4b_tags`. The Phase-5 ffmpeg encode-time
    helpers (`ffmpeg_metadata_args` / `ffmetadata_header_lines`) are unchanged, so the M4B
    Converter and the Maker's existing tag path are unaffected.
  - **Un-hid the Metadata Editor in the launcher sidebar.** The slot was pre-registered in
    Phase 3 and auto-hidden via `importlib.util.find_spec`; now that the module exists the
    guard reveals it automatically — **no launcher code change was needed** (verified the
    sidebar lists all six tools).
  - **Series tags in M4B Maker.** Added **Series Name** and **Series Part** fields to
    `M4BMakerUI`. Because ffmpeg cannot write the freeform iTunes atoms, the maker writes
    them with mutagen (`shared/metadata.write_m4b_tags`) **immediately after a successful
    encode**, so newly built M4B files carry the `----:com.apple.iTunes:SERIES` /
    `SERIES-PART` atoms (read by ffprobe as `series` / `series-part`) from the start — not
    just on a later edit pass.
- **Phase 5 (MP3 Tools Polish) — complete (Cancel buttons + settings-backed folders +
  shared metadata module, verified headless).**
  - Added a **Cancel button** to all four MP3 tools (M4B Converter, MP3 Tool, M4B Maker,
    Cover Image Converter), beside their action buttons. Each is **disabled when idle and
    enabled only while an operation is running**; clicking it disables itself, sets a
    `threading.Event`, and the worker bails at the next **natural checkpoint (between files /
    between tracks / at stage boundaries)** via `shared/cancellation.py`
    (`raise_if_cancelled` / `ConversionCancelled`). On cancel the tool **cleans up its partial
    output** (M4B Maker / MP3 Tool delete the staging output folder; the Converter drops a
    partial MP3) and reports a clear **"Cancelled."** line in the log/status.
  - **M4B Maker and MP3 Tool now run their conversions on a worker thread.** They previously ran
    synchronously on the main thread, which froze the GUI (and made a Cancel button impossible).
    Each now reads all Tk variables on the main thread, hands plain copies to the worker, and the
    worker talks back only through a thread-safe queue drained by a `pump_queue` (`after`) loop —
    the same pattern (and the same fix) as the Phase 4 TTS worker, avoiding
    "main thread is not in main loop". The M4B Converter and Cover Resizer already used worker
    threads; their off-thread widget writes were likewise routed through the queue.
  - Added `scripts/shared/metadata.py` — the canonical M4B/MP4 metadata module:
    `read_m4b_tags(path) -> dict` and `write_m4b_tags(path, tags)` (mutagen; `write` only touches
    the keys you pass, preserving every other tag — for the Phase 6 Metadata Editor), plus the
    encode-time helpers `ffmpeg_metadata_args` / `ffmetadata_header_lines` shared by the two M4B
    tools, and the Audiobookshelf series-atom constants `----:com.apple.iTunes:SERIES` /
    `SERIES-PART` (Briefing §6). `m4b_maker.py` and `m4b_converter.py` now build their ffmpeg
    tag fields from this module instead of each spelling them out.
- **Phase 4 (TTS Integration & Polish) — complete (Cancel button + cancellation plumbing,
  verified headless).**
  - Added a **Cancel button** to the TTS tool, beside Start. It is **disabled when idle and
    enabled only while a conversion is running**; clicking it disables itself and requests a stop.
    Works for **all four conversion paths** — single-file Edge, batch-PDF Edge, single Kokoro, and
    batch Kokoro.
  - Added `scripts/shared/cancellation.py` — a small cooperative-cancellation primitive
    (`ConversionCancelled` + `raise_if_cancelled`). The Cancel button sets a `threading.Event`;
    a `cancel_check` callable (`event.is_set`) is threaded into the worker, which consults it at
    **natural checkpoints (between chapters, paragraphs, and TTS chunks)**. Lives in `shared/`
    (not `tts/`) so the MP3 tools can reuse it for their own Cancel (Phase 5.1).
  - Wired `cancel_check` through `epub2tts_edge.read_book` (chapter / paragraph / sentence-chunk
    checkpoints), `runner.run_conversion_job`, `batch_convert.run_batch_convert` /
    `convert_single_pdf` (between PDFs and between chunks; queued PDFs are cancelled, in-flight
    workers bail at the next chunk), and `kokoro_synth.kokoro_file_to_mp3` (between chunks).
    On cancel the worker **cleans up its temp directory** (the runner's existing `finally` and the
    synth helpers' `TemporaryDirectory` contexts) and logs a clear **"Cancelled."** line.
  - **Feature-parity audit (4.1):** confirmed the Phase 3 `main()`→`build_ui(parent)` refactor
    dropped no controls and broke no bindings — `main()` now simply wraps `build_ui` in a private
    `Tk()`, so the launcher panel and the standalone window are the same UI. The only intentional
    UI change is the new Cancel button.
  - **Runner cwd isolation (4.3):** verified `runner.run_conversion_job` captures `old_cwd` before
    `os.chdir(tmp)` and restores it in a `finally` (alongside `shutil.rmtree(tmp)`), so launching
    via the unified launcher leaves no cwd side-effects between tool invocations. No change needed.

- **Phase 3 (Unified Launcher GUI) — code-complete; live conversion + visual console-flash check pending.**
  - Built `scripts/launcher.py`: a single Tk window with a left **sidebar of tools** and one
    **swappable content panel** on the right (matches the Briefing UX sketch). Includes a status
    bar with an **"Open log folder"** link. The launcher initialises the per-session file logger
    and calls `ffmpeg_utils.configure_pydub()` once at startup.
  - **Refactored all five existing tools to expose `build_ui(parent)`** so they render inside the
    launcher's content panel instead of owning a `Tk` root. Each keeps a standalone `main()`
    (wraps `build_ui` in a private `Tk()`) for debugging. The MP3 tools changed from
    `class App(tk.Tk)` / `MP3ToolGUI(root)` to embeddable `ttk.Frame` subclasses
    (`CoverResizerUI`, `M4BConverterUI`, `MP3ToolUI`, `M4BMakerUI`); the TTS GUI's `main()` body
    became `build_ui(parent)`.
  - **Tools are built once and shown/hidden (raise) on selection**, not destroyed and rebuilt, so
    in-progress state (file lists, typed metadata) survives switching tabs. This is a deliberate
    refinement of the "clear and repopulate" sketch — same single-panel feel, better UX.
  - **Lazy, guarded tool loading:** each tool module is imported on first selection and wrapped in
    try/except, so a missing optional dependency shows a friendly in-panel error instead of
    crashing the whole launcher. The Phase 6 **M4B Metadata Editor** is pre-registered in the
    sidebar but auto-hidden until its module exists (detected via `importlib.util.find_spec`).
  - Added `scripts/shared/settings.py` — atomic JSON settings at `resources/settings.json`
    (temp-file + `os.replace`; never raises on missing/corrupt file). The launcher persists
    **window geometry** and **last-selected tool** across restarts.
  - Added `scripts/shared/ffmpeg_utils.py` — resolves ffmpeg/ffprobe (bundled `resources/bin/`
    first, then PATH) and configures pydub (`AudioSegment.converter/ffmpeg/ffprobe`,
    `get_prober_name`) so audio ops use the right binary and don't depend on PATH.

- **Phase 2 (`setup_and_run` cross-platform bootstrap) — code-complete; live install pending.**
  - **Initialized the git repository** at the root with a `.gitignore` (`.venv/`, `__pycache__/`,
    `*.pyc`, `dist/`, `build/`, `*.spec`, `resources/bin/`, `resources/logs/`, `settings.json`,
    `test-logs/`, OS/editor cruft) and a `.gitattributes` that forces `*.command`/`*.sh` to **LF**
    (so the macOS launcher is never corrupted by CRLF) and `*.bat` to CRLF. Verified the initial
    stage contains only source — no `.venv`/`__pycache__`/logs leaked.
  - Built `scripts/shared/bootstrap.py` — a single **cross-platform** bootstrap (kept byte-identical
    in both OS trees; platform logic is branched inside). It: fast-path launches the GUI if `.venv`
    exists; otherwise locates/installs **Python 3.12** for the venv (system Python may be 3.13, which
    drops Kokoro), creates `<os_root>/.venv`, pip-installs the pinned `requirements.txt`, ensures
    ffmpeg (winget `Gyan.FFmpeg` / Homebrew, with a portable-build fallback into `resources/bin/`),
    optionally pre-downloads the Kokoro model, and launches the GUI detached via `pythonw` (Windows).
    First run shows a **Tk progress dialog** (intro + Kokoro opt-in checkbox, default checked) with a
    progress bar and live log; all output is tee'd to `resources/logs/setup_YYYY-MM-DD.log`. Depends
    on **stdlib + Tk only** (runs before the venv exists). Flags: `--launch-only`, `--self-test`,
    `--skip-kokoro-download`. Adapted from the legacy `tts/setup_env.py`.
  - Rewrote `setup_and_run.bat` and `setup_and_run.command` from stubs into real, **simple/readable**
    entry points: fast-path (no-console GUI launch when `.venv` exists) + first-run Python discovery
    (winget/Homebrew install, browser fallback) that hands off to `bootstrap.py`.

- **Phase 1 (Repository Restructure & File Migration) complete — restructure only, no behavior change.**
  - Built the final `scripts/{tts,mp3_tools,shared}` skeleton in both `Windows/` and `MacOS/`,
    with `__init__.py` for each package and the `epub2tts_edge/` subpackage preserved intact.
  - Migrated the TTS subsystem into `scripts/tts/` (`epub2tts_gui.py`, `batch_convert.py`,
    `kokoro_synth.py`, `pdf_extractor.py`, `voice_registry.py`, `setup_env.py`, and the
    `epub2tts_edge/` package). On macOS the helper modules that lived under a `scripts/`
    subfolder were flattened into `tts/`, erasing the old Win/Mac layout divergence.
  - Migrated the four MP3 tools into `scripts/mp3_tools/`, renamed to importable module names:
    `mp3_tool-v5-4.py`→`mp3_tool.py`, `m4b_maker-v5-3.py`→`m4b_maker.py`,
    `m4b_converter-v1-2.py`→`m4b_converter.py`, `cover_resizer-v2.py`→`cover_resizer.py`.
    The old MP3 `launcher.py` was copied as `mp3_tools_launcher.py` (absorbed in Phase 3) and its
    tool paths updated to the new flat, renamed files.
  - Created the `shared/` module: `paths.py` (pathlib single-source-of-truth for all project
    paths — no more hardcoded/absolute paths), `subprocess_utils.py` (Windows console-hiding
    `run`/`popen` wrappers), `logging_setup.py` (per-session file logger under `resources/logs/`,
    keeps last 30 sessions).
  - Created merged OS-level `requirements.txt` (TTS + MP3, de-duplicated) in both `Windows/`
    and `MacOS/`. Versions left **unpinned** for now — Phase 2 pins all per the dependency rules.
  - Created stub `setup_and_run.bat` / `setup_and_run.command` at the repo root (full bootstrap
    in Phase 2); `.command` marked executable.
  - Created `resources/logs/` in both OS folders.
- **Phase 0 (Research & Discovery) complete.** Full source inventory of both source repos
  (`epub2tts-edge` TTS + `mp3_scripts` MP3 tools) recorded in `Briefing.md` §4, including
  public entry points, dependencies, and cwd/hardcoded-path assumptions per file.
- GitHub/docs research recorded in `Briefing.md` §6: authoritative Audiobookshelf series-tag
  mapping (write freeform atoms `----:com.apple.iTunes:SERIES` / `SERIES-PART`, which ffprobe
  surfaces as `series` / `series-part`), mutagen freeform write pattern, console-suppression
  pattern, and the Kokoro Python <3.13 gate.
- MP3 Tool feature inventory pre-filled (`Briefing.md` §6a) ahead of Phase 5.2.
- Unified launcher UX sketch (`Briefing.md` §8): sidebar + single swappable content panel.

### Changed
- **Phase 7: added `test-files/` to `.gitignore`.** A ~2.7 GB folder of real test assets (2 M4Bs,
  289 MP3, 836 PDF, JPGs, TXT) sits at the repo root as a local fixture for the test matrix; it must
  never be committed. (No tool/source code changed in Phase 7.)
- **Phase 5: routed every MP3-tool input/output folder through `shared/settings.py`** instead of
  hardcoding `~/Downloads/...`. Each tool remembers its folders under per-tool keys
  (`m4b_maker.input_dir` / `.output_dir` / `.cover_dir`, `m4b_converter.input_dir` / `.output_dir`,
  `mp3_tool.input_dir` / `.output_dir`, `cover_resizer.input_dir`). **First run defaults to the
  user's home directory** (no more `~/Downloads`); the chosen folders persist on every successful
  operation and pre-fill the file dialogs (`initialdir`) and a new **"Output folder" picker** added
  to M4B Maker, M4B Converter, and MP3 Tool. The Cover Resizer writes next to its source images, so
  it only remembers its input folder. The sequential auto-named subfolders (`M4B-Output-N`,
  `m4b_converter_output-N`, `edited_mp3s-N`) are unchanged — they're now created **inside** the
  remembered base folder.
- **Phase 3: routed every tool's external-binary call through `shared/subprocess_utils`** so no
  console window flashes on Windows. The MP3 tools' `subprocess.run` / `check_output` and the TTS
  engine's two `subprocess.run(["ffmpeg", …])` calls in `epub2tts_edge.make_m4b` now go through the
  hidden-console wrapper; folder-opening (`os.startfile` / `open` / `xdg-open`) goes through the new
  `subprocess_utils.reveal_in_file_manager`. Audit confirms **zero direct `subprocess.*` calls** in
  tool code (installer `bootstrap.py`/`setup_env.py` and the legacy `mp3_tools_launcher.py` are out
  of scope). Extended `subprocess_utils` with `check_output` and `reveal_in_file_manager`.
- **Phase 3: unified the two previously-divergent tool files across OS trees.** `cover_resizer.py`
  (file-dialog filter) and `epub2tts_gui.py` (Mac window size/labels/`sys.path` shim) are now
  byte-identical Win↔Mac; all platform differences are handled by `sys.platform` branches inside
  the shared code (console-hide kwargs, exe suffix, file-manager command, launcher font/theme).
- **Phase 3: demoted startup "ffmpeg not found" modals to log lines** in the MP3 tools, so switching
  between tools in the single-panel launcher never pops a dialog on every selection.
- **Pinned every dependency** in both `Windows/requirements.txt` and `MacOS/requirements.txt` to an
  exact version (project rule), verified against PyPI on 2026-05-28: beautifulsoup4 4.14.3,
  ebooklib 0.20, edge-tts 7.2.8, lxml 6.1.1, mutagen 1.47.0, nltk 3.9.4, pillow 12.2.0, pydub 0.25.1,
  pymupdf 1.27.2.3, setuptools 82.0.1, tqdm 4.67.3, soundfile 0.13.1, scipy 1.17.1,
  `audioop-lts==0.2.2 ; python_version >= "3.13"`, `kokoro==0.9.4 ; python_version < "3.13"`
  (optional `pillow-heif==1.3.0` pinned but commented). The `<3.13` Kokoro marker matches the
  bootstrap targeting Python 3.12.
- **Import convention established:** `scripts/` is the single import root; all cross-module
  imports are absolute `tts.*` / `mp3_tools.*` (subpackage-internal imports inside
  `epub2tts_edge/` stay relative). Entry-point scripts that can be run directly
  (`epub2tts_gui.py`, `batch_convert.py`) self-bootstrap `scripts/` onto `sys.path`, so they
  work both standalone and when imported by the future unified launcher — and the same module
  is never importable under two names (avoids the double-import trap).
- Rewrote all internal imports in the migrated TTS files to the new convention
  (e.g. `from pdf_extractor import` → `from tts.pdf_extractor import`); removed the macOS GUI's
  old `sys.path.insert(..., "scripts")` shim, replaced with the standard bootstrap.
- Moved `Dockerfile` into `Windows/` only (optional Linux container; documented divergence —
  macOS has no Dockerfile).
- `Briefing.md` fully populated (was placeholder): summary, structure, subsystems, source
  inventory, Win↔Mac divergence analysis, design decisions, research, dependency table.

### Removed
- Deleted the four source-repo folders after migration was verified: `Windows/epub2tts-edge`,
  `Windows/mp3_scripts`, `MacOS/epub2tts-edge`, `MacOS/mp3_scripts` (including their `.git`
  fork histories and the working `.venv`). Also removed the empty `Windows/files` and
  `MacOS/files` folders — the project structure uses `resources/`, not `files/`.
  The `.venv` is rebuilt fresh by Phase 2's bootstrap.

### Fixed
- **Phase 4: TTS conversion crash — "main thread is not in main loop."** The TTS worker thread was
  reading Tk variables directly (`mode_var.get()`, `workers_var.get()`, `resume_var.get()`,
  `voice_var.get()`, `rate_var.get()`, `bitrate_var.get()`, `overwrite_var.get()`,
  `epub_convert_var.get()`, `kokoro_speed_var.get()`, `end_pause_var.get()`). Tcl variable access
  off the main thread raises `RuntimeError: main thread is not in main loop`. Fixed by reading
  **every** Tk variable on the main thread in `run_job` (into plain Python locals) before spawning
  the worker; the worker now uses only those copies and talks to the GUI exclusively through the
  thread-safe log queue (drained by `pump_queue` via `root.after`). Surfaced by the Phase 4 headless
  test and reported live during conversion.

---

## Decisions (Phase 0)

- **Bundling = Path A** (install-on-first-run bootstrap), not PyInstaller/py2app. Reason:
  Kokoro→PyTorch makes self-contained builds fragile/huge; existing `setup_env.py` already
  implements Path A and becomes `shared/bootstrap.py` in Phase 2.
- **Launcher UX = sidebar + single swappable content panel**; each tool exposes `build_ui(parent)`.
- **Single shared codebase per subsystem** with thin platform shims — Phase 0 diff proved the
  TTS core and MP3 tools are ~byte-identical across Win/Mac; only divergence is layout
  (Win flat-root vs Mac `scripts/` subfolder) + cosmetic GUI lines.

---

## Open Questions

> Use this section to log anything that needs the project owner's input before proceeding.
> Move resolved items into the appropriate Unreleased category once answered.

- _(none — Phase 0 surfaced no blockers; series-tag convention resolved via research)_

---

## Session Log

> One entry per Claude Code session. Newest at the top. Keep short — point at file changes, not full diffs.

### 2026-05-30 — Session 10
- **Phase:** v0.1.1 update release — Phases A–F (complete).
- **Git:** phase chain off `master` — `v0.1.1-phaseA-output-infra` → `…-phaseB-copy-output`
  → `…-phaseC-clear-tags` → `…-phaseD-chapter-import` → `…-phaseE-test` → `…-phaseF-release`,
  each fast-forward off the previous for a linear merge to `master`.
- **Done:** Phase A `shared/paths.py` output resolver (`downloads_dir` / `next_output_dir` /
  `TOOL_SLUGS` / `avoid_input_overwrite`); Phase B copy-based non-destructive output + smart
  `Downloads/<Tool>-N` defaults across all six tools (Metadata Editor now tags copies; Browse
  no longer persisted); Phase C `clear_metadata_keep_chapters` + "Clear All Tags (keep chapters)"
  button; Phase D `read_chapter_titles`/`apply_chapter_titles` (ffmpeg ffmetadata round-trip,
  freeform-atom preservation) + paged per-file chapter-title import UI; Phase F version bump
  (0.1.1), README + Briefing + CHANGELOG, release zips. All changes mirrored byte-identical
  Win↔Mac.
- **Verification:** `compileall` clean both trees at every commit; headless functional tests
  (real Tk + ffmpeg + mutagen) per phase; Phase E live pass on real `test-files/` (Harry Potter
  + Mistborn M4Bs, Shadow Slave MP3s, real JPG) — all transforms on copies, every imported
  original MD5-identical before/after; subprocess audit clean. See `Windows/test-logs/
  v0.1.1_pre-release.md`.
- **Next:** post-release — macOS live pass on a Mac; final visual no-console-flash confirmation.
- **Blockers:** none. **Deferred (carried from v0.1.0):** clean-machine one-click install on
  Python 3.12, the macOS matrix column, and the visual no-flash check.

### 2026-05-29 — Session 9
- **Phase:** Phase 8 — README + Release Packaging (complete).
- **Git:** work on new branch `phase-8-release` (off `phase-7-test-matrix`). Local only.
- **Done:** wrote the CV-grade root **`README.md`** (summary, six-tool feature list, ASCII launcher
  mockup, Windows/macOS install, system-requirements table, per-tool usage, architecture +
  design-decisions section, GPL-3.0 credits/license, known limitations). Added
  **`shared/version.py`** (`VERSION = "0.1.0"`) as the single source of truth and the dev-only
  **`shared/release.py`** packager (stdlib-only; zips each OS tree with the documented exclusions,
  README + launcher at the archive root, prints the §13 checklist). Mirrored both new modules
  byte-identical to Windows + MacOS. Finalised both CHANGELOG copies: `[Unreleased]` → `[0.1.0] -
  2026-05-29` with a fresh empty `[Unreleased]` on top, and removed the stale bottom `[0.1.0]`
  placeholder.
- **Verification:** ran `release.py` → two zips under `dist/`; `zipfile.namelist()` confirms each has
  `README.md` + the correct launcher at root, the OS tree nested under its folder, and **zero**
  excluded leaks (no `.venv`/`__pycache__`/`.pyc`/logs/settings/bin/test-files). `compileall` clean,
  both trees.
- **Next:** GitHub remote + first Release (attach both zips). Before a real public ship, still run
  **Debug Gate 2** (full one-click install on a clean Python-3.12 box), the **macOS** matrix column on
  a Mac, and the final **visual** no-console-flash confirmation.
- **Blockers:** none.

### 2026-05-29 — Session 8
- **Phase:** Phase 7 — Cross-Platform Test Matrix (complete on Windows; macOS deferred — no host).
- **Git:** work on new branch `phase-7-test-matrix` (off `phase-6-metadata-editor`). Local only.
- **Done:** ran every deferred live gate (2–6) and filled Briefing §12 against the real `test-files/`
  assets (copied to a temp working dir **with a space**; originals untouched). Verified live on
  Windows, driving the real worker code paths: Edge-TTS EPUB→MP3 + PDF→MP3 + 2-file batch + mid-run
  cancel (Gate 4, 0 leaked temp dirs); M4B Maker chapters + series (ffprobe-verified); M4B-encode
  cancel cleanup (Gate 5); M4B→MP3; MP3-Tool combine/time-edit/ID3; Cover-Resizer square+crop;
  Metadata Editor single/multi/blank-preserve (Gate 6); Unicode filename; spaces in path; settings
  persist across simulated restart; launcher builds all six tools (~1.25 s). Gate 2 verified live
  (`bootstrap.py --self-test` + throwaway-venv pip dry-run resolving the full pinned requirements).
  Console-flash mechanism re-audited (zero direct `subprocess.*` in tool code). Added `test-files/`
  to `.gitignore`.
- **Result:** **18/18 applicable Windows rows PASS, 0 FAIL.** **No bugs found → no tool code changed**
  (Phase 7.3 was a no-op by design). `compileall` clean on both trees.
- **Next:** Phase 8 — README + release packaging. Before release, still run **Debug Gate 2** (full
  one-click install on a clean machine with Python 3.12) and the **macOS** matrix column on a Mac.
- **Blockers:** none. **Deferred (documented known-limitations):** fresh one-click install (system
  mutation + Python 3.12), TTS Kokoro voice (needs Python <3.13; this box is 3.13), final *visual*
  no-console-flash confirmation, and the entire macOS column (no Mac).

### Debug Gate 7 — PASS (Windows live; macOS deferred)
- [x] **Gate 2** — venv + pip path verified live: `bootstrap.py --self-test` clean; `python -m venv`
  works; throwaway venv resolved the full **pinned** `requirements.txt` against PyPI (kokoro excluded
  on 3.13). [~] Full one-click fresh install on a clean machine w/ Python 3.12 — still deferred.
- [x] **Gate 3** — real conversions run from the tool worker paths (TTS single-file Edge → MP3 incl.).
  Console-flash mechanism-verified (zero direct `subprocess.*` in tool code; `subprocess_utils` hides
  the window; launcher under `pythonw`). [~] Final *visual* no-flash confirmation — manual, deferred.
- [x] **Gate 4** — real TTS conversion cancelled mid-run: `ConversionCancelled` raised, **0 leaked
  temp dirs**; GUI logs "Cancelled." (Phase 4 behavior unchanged).
- [x] **Gate 5** — real M4B encode cancelled at a stage boundary: partial output folder removed,
  `("cancelled")` posted.
- [x] **Gate 6** — Metadata Editor on a real M4B (slice of a `test-files/` audiobook): edit a field →
  save → re-read confirms the change persisted, untouched fields preserved; multi-file overwrite and
  blank-field preserve verified.
- [x] Full §12 matrix filled: **18/18 applicable Windows rows PASS**, 0 unresolved FAIL.
- [x] `compileall` clean, both trees. **No bugs found → no code changes.**
- [~] **macOS** column — SKIP(no-Mac), deferred to a Mac host.

### 2026-05-29 — Session 7
- **Phase:** Phase 6 — M4B Metadata Editor + Series Tags (complete).
- **Git:** work on new branch `phase-6-metadata-editor` (off `phase-5-mp3-polish`). Local only.
- **Done:** added `mp3_tools/m4b_metadata_editor.py` (open/edit existing M4B tags without
  re-encoding; Title/Author/Album/Year/Genre/Comment/Series/cover; preserve-by-default;
  single-file pre-fill + multi-file batch overwrite; worker-thread Save + Cancel + per-file
  log; `build_ui` + `main`). Extended `shared/metadata.py` additively (comment/genre/year
  atoms, `cover_path` embed/clear, `has_cover` read flag) — ffmpeg encode helpers untouched.
  Added **Series Name / Series Part** fields to `M4BMakerUI`, written via mutagen right after
  a successful encode (ffmpeg can't write the freeform atoms). Launcher slot auto-reveals via
  the existing `find_spec` guard — no launcher change. Mirrored all 3 changed/new code files
  byte-identical to MacOS.
- **Verification:** `compileall` clean (both full trees); a temporary headless test (real Tk +
  real mutagen + real ffmpeg/ffprobe) passed **17/17 on each tree** — launcher reveal,
  single-file round-trip (edit one field, others preserved), comment/genre/cover round-trip,
  batch blank-preserve / non-blank-overwrite, ffprobe surfacing `series` / `series-part`, and a
  real short M4B-Maker build whose output carries the series atoms. Test scaffold removed.
- **Next:** Phase 7 — full cross-platform test matrix (§12) on Windows + a Mac.
- **Blockers:** none. **Deferred:** live click-through of the editor on a Mac and the broader
  Phase 7 matrix (manual pre-release pass).

### Debug Gate 6 — PASS (headless)
- [x] `m4b_metadata_editor.py` exists and compiles; `build_ui(parent)` and `main()` both present.
- [x] Launcher sidebar shows the Metadata Editor without any manual config change (`_available_tools`
  lists `m4b_metadata`; the `find_spec` auto-hide now reveals it).
- [x] Single-file tag round-trip: read tags → edit one field → write → re-read confirms the change,
  with untouched fields preserved (headless, real mutagen). Comment/genre/cover atoms round-trip too.
- [x] Batch mode: a blank field preserves each file's existing tag; a non-blank field overwrites all.
- [x] Series atoms written as `----:com.apple.iTunes:SERIES` / `SERIES-PART` and read back by ffprobe
  as `series` / `series-part`.
- [x] M4B Maker series fields present in the UI and written to the output on a real (short) M4B build
  (ffprobe confirms `series` on the produced file).
- [x] `compileall` clean, both trees.
- [~] Live click-through of the editor GUI on a Mac — deferred to the Phase 7 manual pass.

### 2026-05-29 — Session 6
- **Phase:** Phase 5 — MP3 Tools Polish (complete).
- **Git:** work on new branch `phase-5-mp3-polish` (off `phase-4-tts-polish`). Local only.
- **Done:** added `shared/metadata.py` (mutagen `read_m4b_tags`/`write_m4b_tags` + series atoms +
  `ffmpeg_metadata_args`/`ffmetadata_header_lines`); `m4b_maker.py` and `m4b_converter.py` now build
  their tag fields from it. Added a **Cancel button** to all four MP3 tools (idle-disabled,
  active-enabled, `threading.Event` checkpoints via `shared/cancellation.py`, "Cancelled." line,
  partial-output cleanup). **Moved M4B Maker and MP3 Tool conversions onto worker threads** (they
  were synchronous on the main thread) with a queue + `pump_queue` so Tk is only touched on the main
  thread; routed the Converter/Resizer off-thread widget writes through the queue too. Replaced every
  hardcoded `~/Downloads/...` path with `shared/settings.py`-backed per-tool input/output folders
  (default = home), added an "Output folder" picker to the three output-producing tools, and persist
  folders on success + pre-fill dialogs. Mirrored all 5 changed/new files byte-identical to MacOS.
- **Verification:** `compileall` clean (both full trees); a temporary headless test (real Tk + real
  ffmpeg/ffprobe) passed 38/38 — Cancel state machine (idle→busy→cancel→idle) for all four tools,
  `normalize_to_wav` honouring `cancel_check`, the `ffmpeg_metadata_args`/`ffmetadata_header_lines`
  output, and a full M4B tag round-trip incl. **ffprobe surfacing the freeform series atoms as
  `series` / `series-part`** (validates Briefing §6 live). Test scaffold removed after the pass.
- **Next:** Phase 6 (M4B Metadata Editor + series tags in M4B Maker) — builds directly on
  `shared/metadata.py`.
- **Blockers:** none. **Deferred:** live mid-operation cancel during a single long ffmpeg encode
  (cancel lands at stage/file boundaries, not mid-subprocess) — manual pre-release pass, same posture
  as the deferred TTS live cancel.

### Debug Gate 5 — PASS (headless)
- [x] Cancel button present and correctly state-managed in all four MP3 tools (headless: idle
  `disabled`; enabled while busy; `cancel()` sets the event and disables itself; `_finish_idle()`
  clears busy and leaves Cancel disabled).
- [x] No hardcoded `~/Downloads` paths remain in tool code (grep: only doc-comment mentions left);
  all folders route through `shared/settings.py` with a home-dir default.
- [x] Last-used input/output folders persist per tool independently via distinct settings keys
  (`<tool>.input_dir` / `.output_dir` / `.cover_dir`); written on success, read as dialog `initialdir`.
- [x] `shared/metadata.py` exists; `m4b_maker.py` and `m4b_converter.py` import its ffmpeg tag
  helpers; no duplicated field-mapping logic remains. `read_m4b_tags`/`write_m4b_tags` round-trip
  verified, and ffprobe confirms the series atoms surface as `series` / `series-part`.
- [x] `compileall` clean, both trees.
- [x] Existing MP3-tool functionality preserved (same ffmpeg command construction, same output-folder
  naming, same ID3/timestamp behaviour; the only changes are the worker-thread move, Cancel, and the
  remembered folders).
- [~] Live mid-encode cancel on real audio — deferred to the manual pre-release pass.

### 2026-05-29 — Session 5
- **Phase:** Phase 4 — TTS Integration & Polish (complete).
- **Git:** work on new branch `phase-4-tts-polish` (off `phase-3-launcher`). Local only.
- **Done:** added `shared/cancellation.py`; added a **Cancel button** to the TTS GUI (idle-disabled,
  active-enabled) wired into all four conversion paths; threaded `cancel_check` through `read_book`
  (chapter/paragraph/chunk checkpoints), `runner.run_conversion_job`, `batch_convert`
  (`run_batch_convert` + `convert_single_pdf`), and `kokoro_synth.kokoro_file_to_mp3`; cancel logs
  "Cancelled." and temp dirs are removed by existing `finally`/`TemporaryDirectory` cleanup.
  Completed the 4.1 feature-parity audit (Phase 3 refactor dropped nothing) and confirmed 4.3
  runner cwd is restored in a `finally` (no change needed). Mirrored all 6 files byte-identical to
  both trees.
- **Fixed (critical):** TTS worker thread was reading Tk variables off-thread →
  `RuntimeError: main thread is not in main loop` during conversion (reported live, also caught by
  the headless test). All Tk reads hoisted to the main thread in `run_job`; worker now uses plain
  copies + the log queue only.
- **Verification:** `compileall` clean (both trees); a headless GUI test (real Tk, stubbed runner,
  no network) confirmed idle→active→cancel→idle button states, the engine + batch cancel checkpoints
  raising/returning without network, a clean "Cancelled." log, and **no** "main thread" error. Test
  scaffold was temporary and removed after the pass.
- **Next:** Phase 5 (MP3 tools polish; route hardcoded `~/Downloads/...` outputs through
  settings/`paths.py`; MP3-tools Cancel can reuse `shared/cancellation.py`).
- **Blockers:** none. **Deferred:** live mid-conversion cancel on real audio (manual pre-release pass,
  same posture as the deferred Debug Gate 2/3 live items).

### Debug Gate 4 — PASS (headless)
- [x] Cancel button visible; correctly enabled/disabled idle vs. active (headless test: idle Cancel
  `disabled` / Start `normal`; after start Cancel `normal` / Start `disabled`; after cancel click
  Cancel `disabled`; back-to-idle Start `normal`).
- [x] Worker thread exits cleanly on cancel; temp dir removed (runner `finally` + synth
  `TemporaryDirectory`); **"Cancelled."** present in the log pane.
- [x] Feature-parity: every control from the standalone TTS GUI is present in the launcher panel
  (`main()` wraps the same `build_ui`); only addition is the Cancel button.
- [x] `runner.py` restores cwd in a `finally` (captured before `os.chdir`); no cwd leakage between
  tools.
- [x] No "main thread is not in main loop" error — all Tk reads moved to the main thread.
- [x] `compileall` clean, both trees.
- [~] Live mid-conversion cancel on real EPUB/PDF audio — deferred to the manual pre-release pass.

### 2026-05-29 — Session 4
- **Phase:** Phase 3 — Unified Launcher GUI (code-complete; live conversion + visual no-flash check pending).
- **Git:** committed the existing work as two local commits before starting — `Phase 0+1 restructure
  baseline` on `master`, `Phase 2 bootstrap` on branch `phase-2-bootstrap`. Phase 3 work is on a new
  branch `phase-3-launcher` (off `phase-2-bootstrap`). Local only; no remote yet (GitHub at the end).
- **Done:** wrote `scripts/launcher.py` (sidebar + swappable panel, status bar w/ open-log link,
  geometry + last-tool persistence, lazy guarded tool loading, Phase-6 metadata slot auto-hidden);
  refactored all 5 tools to `build_ui(parent)` as embeddable frames with standalone `main()`;
  added `shared/settings.py` (atomic JSON) and `shared/ffmpeg_utils.py` (ffmpeg/ffprobe resolve +
  pydub config); routed all tool subprocess calls through `shared/subprocess_utils` (added
  `check_output`, `reveal_in_file_manager`); unified the 2 divergent files Win↔Mac. Mirrored all
  10 changed/new files to MacOS (byte-identical).
- **Verification (static + headless, no system mutation):** `compileall` clean (both trees);
  subprocess audit shows **zero** direct `subprocess.*` calls in tool code (both trees); `import
  launcher` succeeds without heavy deps; **headless GUI smoke test** instantiated the launcher and
  built all 5 tools into the content panel (all `BUILT`, no error frames) and persisted geometry +
  last-tool on close; settings round-trip verified; bootstrap `--self-test` confirms
  `launch target = scripts/launcher.py (exists=True)` — the bootstrap now opens the unified launcher.
- **Next:** Phase 4 — TTS integration & polish (feature-parity pass inside the launcher; add the
  **Cancel button**; confirm Runner keeps all temp I/O out of the launcher cwd).
- **Blockers:** none. **Deferred:** the live items in Debug Gate 3 (run a real conversion from the
  launcher and visually confirm no console flash under `pythonw`) — manual pre-release, same posture
  as the deferred Debug Gate 2 live install.

### Debug Gate 3 — PARTIAL (static + headless PASS; live conversion deferred)
- [x] Launcher opens; each of the 5 existing tools loads into the content panel (headless smoke test:
  all 5 `BUILT`). The 6th (Metadata Editor) arrives in Phase 6 and is auto-hidden until then.
- [x] Settings persist across restarts (window geometry + last sidebar selection round-trip to
  `resources/settings.json`).
- [x] Subprocess audit: zero direct `subprocess.*` calls in tool code; all routed through
  `shared/subprocess_utils` (which applies `CREATE_NO_WINDOW` + hidden `STARTUPINFO` on Windows).
- [x] pydub pointed at the resolved ffmpeg/ffprobe via `ffmpeg_utils.configure_pydub()`.
- [~] Running a TTS / MP3 / M4B operation **from inside the launcher** produces output identical to
  the old standalone GUI — **not run live this session** (needs a real conversion with sample assets).
- [~] **No console window flashes during any operation** under `pythonw.exe` — code-verified (routing
  + pythonw launch), **visual confirmation deferred** to the manual pre-release pass.

### 2026-05-28 — Session 3
- **Phase:** Phase 2 — `setup_and_run` cross-platform bootstrap (code-complete; live install pending).
- **Done:** `git init` + `.gitignore` + `.gitattributes` (LF for `.command`/`.sh`); pinned every dep
  in both `requirements.txt`; wrote `scripts/shared/bootstrap.py` (one byte-identical cross-platform
  file, adapted from `setup_env.py`) with fast-path launch, Python-3.12 locate/install, venv create,
  pinned pip install, ffmpeg ensure (+ portable fallback), Kokoro opt-in, detached GUI launch, dated
  setup log, and `--launch-only`/`--self-test`/`--skip-kokoro-download` flags; rewrote
  `setup_and_run.bat` and `.command` from stubs into real fast-path + first-run-Python-discovery
  entry points.
- **Verification (static, no system mutation):** `py_compile` clean (both trees); `--self-test`
  detection ran with no side effects and correct results; auto-driven headless GUI smoke test ran the
  intro→worker→progress→done→launch wiring to success (install/launch stubbed); `bootstrap.py`
  confirmed byte-identical across trees; `.command` confirmed 0 CR bytes (LF-only); git stage
  confirmed free of `.venv`/`__pycache__`/logs.
- **Next:** Phase 3 — unified launcher GUI (`scripts/launcher.py`). Once it exists, the bootstrap's
  launch target switches from the TTS-GUI fallback to it automatically (no bootstrap change needed).
  After Phase 3, run the **live Debug Gate 2** fresh-machine install on Windows + a Mac.
- **Blockers:** none. **Deferred:** live fresh-machine install (Debug Gate 2) — see below.

### Debug Gate 2 — PARTIAL (static PASS; live install deferred)
- [x] `setup_and_run.bat` / `.command` rewritten from stubs; fast-path + first-run logic in place.
- [x] `bootstrap.py` compiles, self-tests, and its first-run GUI wiring runs to completion (stubbed).
- [x] Logs written to `resources/logs/setup_YYYY-MM-DD.log` (verified by self-test run).
- [~] Fresh-machine install (winget/brew Python 3.12 → venv → pinned pip incl. torch/Kokoro → ffmpeg
  → optional 300 MB model → GUI open, 1 click) — **NOT run live.** Mutates the host (system Python +
  ffmpeg, multi-GB downloads); to be run on a clean VM / the target machine before release.
- [~] Second-launch under 2s, no console window — **needs a real `.venv` + Phase 3 `launcher.py`** to
  verify end-to-end; the fast-path code path is in place and the GUI runs under `pythonw`.
- [-] macOS double-click flow — **skipped this session** (no Mac available); `.command` built to mirror
  Windows and confirmed LF-only.

### 2026-05-28 — Session 2
- **Phase:** Phase 1 — Repository Restructure & File Migration (complete).
- **Done:** Built `scripts/{tts,mp3_tools,shared}` skeleton (both OS); migrated TTS + MP3 source
  into it; renamed MP3 tools to importable names; rewrote all internal imports to the `tts.*` /
  `mp3_tools.*` convention with a `scripts/`-root bootstrap in entry scripts; created `shared/`
  (paths, subprocess_utils, logging_setup); merged unpinned `requirements.txt`; moved Dockerfile
  to Windows/; created root `setup_and_run.*` stubs. Smoke-tested all imports + `py_compile`
  (both trees) and launch-verified both GUIs under `pythonw.exe`. Deleted the four source-repo
  folders + empty `files/` folders.
- **Verification:** Debug Gate 1 — all items pass (see below).
- **Next:** Phase 2 — `setup_and_run` bootstrap. Adapt `tts/setup_env.py` into
  `shared/bootstrap.py` (Python/ffmpeg detect+install, create `Windows/.venv` / `MacOS/.venv`,
  pin + install requirements, optional Kokoro download, launch GUI via `pythonw`/detached).
  **First Phase 2 action: pin every dependency in both `requirements.txt`.**
- **Blockers:** none.

### Debug Gate 1 — PASS
- [x] Root has exactly 5 permanent items (+ temp `IMPLEMENTATION_PLAN.md`): `README.md`,
  `setup_and_run.bat`, `setup_and_run.command`, `Windows/`, `MacOS/`.
- [x] `Windows/` and `MacOS/` have identical folder shape (`diff` of dir trees = identical;
  Windows carries an extra `Dockerfile` file — documented intentional divergence).
- [x] TTS GUI launches from new location (`scripts/tts/epub2tts_gui.py`) under `pythonw.exe`
  — process stayed alive, window opened, no crash.
- [x] MP3 launcher launches from new location (`scripts/mp3_tools/mp3_tools_launcher.py`).
- [x] Imports succeed from `scripts/` for both trees: `from tts.epub2tts_edge.epub2tts_edge
  import DEFAULT_SPEAKER`, `from mp3_tools import m4b_converter`, all helpers, runner, shared.
- [x] `python -m py_compile` clean across every migrated `.py` (both OS).
- [x] `CHANGELOG.md` + `Briefing.md` updated (both copies).

### 2026-05-28 — Session 1
- **Phase:** Phase 0 — Research & Discovery (complete).
- **Done:** Read all 4 source trees end-to-end; diffed Win↔Mac (core is identical, only layout
  differs); researched Audiobookshelf series tags + mutagen + console suppression; decided
  bundling (Path A) and launcher UX; fully wrote `Briefing.md` (both copies).
- **Next:** Phase 1 — Repository Restructure & File Migration. Create the `scripts/{tts,mp3_tools,shared}`
  skeleton, migrate both source repos into it, fix top-level imports, create empty `shared/` stubs,
  smoke-test imports. No behavior change.
- **Blockers:** none.

_The version history above (Phases 0–8) all ships under **[0.1.0]** — the initial public release._
