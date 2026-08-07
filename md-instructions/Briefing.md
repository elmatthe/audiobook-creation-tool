# Audiobook Creation Tool — Briefing

> **Audience:** future AI sessions and any new contributor.
> **Purpose:** the single document that fully orients a new session without the user re-explaining
> anything. Version history lives in `Changelog.md`; architectural decisions in `Decisions.md`;
> in-flight work and open bugs in `Handoff.md`.
>
> **These four names are a permanent contract** — `Briefing.md`, `Changelog.md`, `Decisions.md`,
> `Handoff.md`, in exactly that casing. Never rename, recase, duplicate or alias them, and never
> recreate the old `CHANGELOG.md` / `DECISIONS.md` / `handoff.md` spellings. `scripts/verify.py`
> enforces this by reading the real directory entries (`os.listdir`) rather than calling
> `Path.exists()`, because a path lookup on Windows and macOS is case-insensitive and would
> happily report a non-existent `CHANGELOG.md` as present. `files/tests/test_repository_contract.py`
> holds the same line, including the permanent references under `md-instructions/don't-delete/`.

## What This Project Does

The Audiobook Creation Tool is a cross-platform (Windows + macOS) desktop app that turns ebooks
and loose audio into finished, tagged audiobooks. It bundles a **text-to-speech engine**
(EPUB / PDF / TXT → MP3, using Microsoft Edge TTS over the network plus the local Kokoro-82M AI
model) with a suite of **MP3/M4B utilities** (combine MP3s, batch M4B→MP3, build chaptered M4B
files with cover art and series tags, resize cover images, and edit existing M4B metadata). It is
built for **non-technical users**: they download a zip, double-click one setup file, and get a
single GUI window — no terminal, no manual Python or ffmpeg install, and no console windows
flashing during use.

## Tech Stack

- **Language:** Python 3.12 (the bootstrap installs 3.12 specifically — PyPI `kokoro` wheels
  require <3.13; 3.13+ works but loses the Kokoro voices)
- **GUI:** tkinter/ttk (single launcher window, sidebar + swappable content panel). Three
  explicit platform branches live in `shared/ui_theme.py`: macOS gets a Finder-style shell
  on the native `aqua` theme; **Windows gets the v0.6.0 dark design system** (see *Windows
  design system* below); Linux/other keeps the historical classic look. Windows is routed
  explicitly on `sys.platform == "win32"` — never inferred from "not macOS".
  **tkinter/ttk is the approved toolkit going forward**: the v0.6.0 Drop 1 prototype was
  built, reviewed against screenshot evidence and approved on 2026-08-02, which settled the
  open question of whether ttk could carry a modern dark UI without a toolkit switch.
- **Key libraries:** edge-tts (network TTS), kokoro + torch (local AI TTS), mutagen (audio
  metadata), PyMuPDF/fitz (PDF text extraction), pydub + soundfile + numpy/scipy (audio
  assembly), ebooklib + beautifulsoup4 + lxml (EPUB parsing), nltk (sentence tokenization),
  pillow (cover images). All pinned to exact versions in `scripts/requirements.txt`.
- **External binaries:** ffmpeg + ffprobe — installed system-wide by the bootstrap (winget
  `Gyan.FFmpeg` / Homebrew) or dropped as a portable build into `files/bin/`.
- **Platform:** cross-platform Windows + macOS from a **single code tree**
  (`scripts/Universal/`); platform differences are `sys.platform` branches inside shared code.

## Architecture

- **Entry point (users):** `Setup_and_Run-audiobook-creation-tool.bat` (Windows) / `.command`
  (macOS) at the repo root — the only files a user ever touches. Fast path: if `.venv` exists,
  launch via `pythonw.exe` (Windows — no console) / detached (macOS). First run hands off to the
  bootstrap.
- **`scripts/Universal/shared/bootstrap.py`** — single cross-platform setup + launch brain
  (stdlib + Tk only; runs before the venv exists). Locates/installs Python 3.12, creates the
  repo-root `.venv`, pip-installs pinned requirements, ensures ffmpeg, optionally pre-downloads
  the Kokoro model (~300 MB), **self-heals a missing/broken Kokoro install on every launch**
  (probes kokoro/soundfile/scipy, repairs without blocking the GUI), redirects the HuggingFace
  cache into the project tree, then launches the GUI detached with stdout/stderr captured to
  `files/runtime-data/logs/launch_<date>.log`. `--launch-only` is the fast-path flag;
  `--self-test` is detection-only.
- **`scripts/Universal/launcher.py`** — the unified Tk GUI. Sidebar of 6 tools; each tool
  exposes `build_ui(parent_frame)`, is lazy-imported and guarded (a missing dependency renders
  an in-panel error, never a crash), built once and shown/hidden on selection so in-progress
  state survives switching. Installs `install_no_window_guard()` first so even pydub/edge-tts
  *internal* ffmpeg spawns are console-hidden on Windows. All theming comes from
  `shared/ui_theme.apply_theme()`, which returns one backwards-compatible bundle and picks
  the shell from `theme["mode"]`: **aqua** — a Finder-style shell (native aqua controls,
  tinted source-list sidebar with hover/selection rows and glyphs, toolbar strip, content
  card), unchanged since v0.5.0 (see Decisions.md 2026-07-08); **windows** — the v0.6.0
  dark shell (navigation rail, header strip naming the active tool and its description,
  framed content card, status bar with a focusable "Open log folder" button); **classic**
  (Linux/other) — the pre-v0.5.0 layout, byte-for-byte. **The content host is never
  styled:** `self.content` and every tool container stay plain, unstyled `ttk.Frame`s in
  all three modes, which is the structural reason an unconverted panel inherits nothing
  from the shell.
- **`scripts/Universal/shared/`** — `paths.py` (single source of truth for every project
  path — everything derives from `REPO_ROOT`), `subprocess_utils.py` (hidden-console subprocess
  wrapper + the global Popen no-window guard), `ffmpeg_utils.py` (resolves ffmpeg/ffprobe:
  `files/bin/` → PATH; pins pydub to the resolved binaries; xHE-AAC decoder selection),
  `config.py` (the typed effective-configuration core — see *Configuration* below),
  `preferences_ui.py` (the Preferences & Data dialog and the once-per-launch configuration
  warning — presentation only, see *Preferences & Data* below),
  `output_paths.py` (output base, run reservation, sanitisation, collisions, containment and
  mirroring — built in Phase 3, consumed by the tools from Phase 4; see *Output services*),
  `settings.py` (atomic JSON at `files/runtime-data/settings.json`, plus reset/reload and
  explicit write-failure reporting), `cancellation.py` (shared
  Cancel/threading.Event pattern), `metadata.py` (mutagen M4B tag read/write incl. series
  atoms + chapter-title re-mux), `logging_setup.py` (session logs, retention read from
  `logging.max_sessions`),
  `ui_theme.py` (platform theming — the aqua/Finder palette, the Windows design system and
  the classic fallback, plus `style_tk_widget` for classic Tk widgets ttk cannot style, the
  `enable_mousewheel` scroll-on-hover helper and the shared `ProgressIndicator` —
  progressbar + counter/percentage label, main-thread-only API, used by all six tools),
  `version.py` (single source of truth),
  `release.py` (dev-only zip packager, never imported by the app), `close_terminal.py`
  (macOS Terminal auto-close helper).
- **Configuration (v0.6.0 Drop 2 Phase 1).** A committed, commented **root `config.toml`**
  holds the project's documented defaults; `shared/config.py` turns it into one *typed,
  immutable* `EffectiveConfig` snapshot. **Precedence, last wins: code defaults → valid
  values from `config.toml` → the allowlisted mutable settings overlay.** The overlay is
  exactly one key today — `output_base_directory` in `settings.json` overriding
  `output.base_directory` — and `config.SETTINGS_OVERLAY` is the whole of it, so no other
  stored preference can reach the configuration however it is spelled. Existing user state
  (`last_tool`, remembered dialog directories, voice, bitrate) stays a plain setting and
  deliberately has **no** TOML counterpart.
  **Every key is validated on its own**, so one bad value never discards a good neighbour, and
  a missing or malformed file can never stop the application from starting: it falls back and
  records a `Diagnostic` (source, key, human-readable fallback, plus technical `detail` kept
  out of the summary). Unknown sections/keys are ignored and reported **once**, aggregated and
  deduplicated by `warning_summary()`. A snapshot is frozen dataclasses + tuples +
  `MappingProxyType`, so an operation that captures one at run start cannot have it shift
  underneath; `get_effective()` caches, `reload()`/`invalidate()` rebuild deterministically.
  Loading configuration **never creates a directory** — resolving the output base computes a
  path and nothing more. The module is Tk-free, platform-neutral, takes injected paths for
  testing, and **never imports `logging_setup`**: retention reads config, so the dependency
  runs one way only. `logging_setup.configured_max_sessions()` imports config lazily inside
  the function and falls back to 30 on *any* failure, because logging must always come up.
  Schema: `project.{name,version,python_min,entry_point,platforms}`, `output.base_directory`,
  `logging.max_sessions` (1–1000), `importing.large_result_warning_threshold` (validated now;
  Plan 3 owns the behaviour that consumes it). An empty output base means
  `~/Downloads/Audiobook-Creation-Tool-Outputs`; a non-empty one must be absolute or `~`-based
  — a **relative path is rejected** rather than resolved against the working directory, and
  environment variables are **never** expanded (`%USERPROFILE%`/`$HOME` stay literal, and are
  therefore rejected as relative). The GUI writes `settings.json` only and **never** rewrites
  the committed TOML. `settings.reset()` clears every mutable preference atomically and touches
  nothing else — no `.venv`, model, binary, log, output or source file; clearing downloaded
  data is a separate, differently confirmed action that does not exist yet.
- **Output services (v0.6.0 Drop 2 Phases 3–4) — built in Phase 3, adopted by all six tools
  in Phase 4.** `shared/output_paths.py` is the platform-neutral foundation. Every standard
  output now lands in `<base>/<Tool>-Outputs/<Tool>-N/`, reserved **at validated operation
  start** — not at `build_ui()` time. Opening the launcher, building a panel, importing,
  browsing, switching tools or failing validation creates **no** directory at all. The legacy
  `paths.next_output_dir()` and `paths.avoid_input_overwrite()` are now dormant compatibility
  API called by nothing in the shipped tree, and a test asserts that.
  **Per-tool destinations:** TTS `TTS-Audiobook-Outputs`, M4B Converter `M4B-Converter-Outputs`,
  MP3 Tool `MP3-Tool-Outputs`, M4B Maker `M4B-Maker-Outputs`, Cover Image `Cover-Image-Outputs`,
  M4B Metadata `M4B-Metadata-Outputs`. Each panel shows its tool folder read-only and names the
  actual reserved run once an operation starts; the base is changed only in Preferences & Data,
  so no per-tool browse control can bypass it. Every output-producing action reserves its own
  run — MP3 Tool's combine, time-edit and ID3 each get one, as do the editor's Write Tags,
  Clear All Tags and Remove Series Numbering — and staging (`build/`, WAV normalisation,
  ffmetadata) stays inside that run, so cleanup can never reach another run, the tool parent or
  the base.
- **The two destination exceptions (v0.6.0 Drop 2 Phase 5).** Decision 10A allows exactly two
  departures from "everything lands in the reserved run", both opt-in and both expressed in
  `shared/output_paths.py` rather than inside a panel.
  **Cover Image — `Save beside source images`.** Off on every fresh build, with
  `Create numbered copies` preselected and `Replace original files` never the default; turning
  the toggle off resets the action, so a Replace selection cannot survive as a hidden mode.
  *Numbered copies* use `SourceSidePlanner`, which keeps one collision sequence **per source
  directory** and starts at `stem-1.ext` — beside a source the unnumbered name *is* the source.
  *Replacement* needs three independent gates: the toggle, the radio, and a per-run
  confirmation ("Confirm replacement of original images") whose Cancel is the focused default,
  where Escape and closing both cancel, and which is rebuilt every run so nothing can be
  remembered or suppressed. Every source is validated **before** the dialog, so the count shown
  is the count that can be processed; links, missing files, directories and formats the writer
  cannot round-trip in place (anything outside `.jpg/.jpeg/.png/.heic/.heif`, which fall back
  to `.jpg`) are refused there rather than mid-run. Each replacement writes a complete
  `.act-tmp-…` sibling in the source's own directory — same filesystem, so the install can be
  atomic — validates the finished image's size, then calls `os.replace`. **Never
  delete-then-rename.** A failure or cancellation before that boundary leaves the original
  byte-for-byte unchanged and removes only this operation's own temporary file;
  `discard_temporary()` refuses any path lacking the temporary prefix. A partial batch reports
  truthfully: files already installed stay installed.
  **M4B Maker — `Choose custom destination`.** Off on every fresh build; the path and Browse
  controls exist only while it is on, and `custom_destination()` is the single place the widget
  is read, so a stale hidden path cannot steer a standard build. The chosen directory is
  validated before anything starts (absolute, existing, a directory, not a link, writable —
  proved with a temporary probe that is removed again, so no user file is created or touched)
  and a validation failure reserves **no** run. The finished `.m4b` goes straight in, with the
  usual sanitisation and collision numbering and **no nested `M4B-Maker-N`**. Staging moves to
  an operation-owned `tempfile.mkdtemp()` so the user's folder is never littered, and — the
  important one — cancellation no longer `rmtree`s `out_dir`, because in custom mode that is
  the user's own folder; it removes only this operation's staging and its own partial output.
  **Planning is pure; materialisation is explicit.** Every `plan_*` function, the sanitizer and
  the collision service compute paths and touch nothing. Only `ensure_output_base()` and
  `reserve_run_directory()` create anything, and only directories — never a file, never
  anything source-side. Tk-free, subprocess-free, network-free, working-directory-independent.
  **Layout** `<base>/<Tool>-Outputs/<Tool>-N/`. `TOOL_OUTPUT_PARENTS` derives the six parent
  folders from the existing `paths.TOOL_SLUGS`, so a slug is never written down twice; an
  unknown tool key raises `UnknownToolError` rather than becoming an unchecked path fragment.
  **Reservation is atomic:** `mkdir()` without `exist_ok` either creates the run directory or
  raises `FileExistsError`, so concurrent runs can never claim the same number — there is
  deliberately no "does it exist?" check first, because that is the race. The search is bounded,
  the result is a frozen `RunReservation` carrying the configuration snapshot the run was
  planned against, and `release_if_empty()` removes a reserved directory **only** while it is
  still empty.
  **Sanitisation** (`sanitize_component`) reduces a path to its last element, strips control
  characters, replaces the Windows-forbidden set, normalises Unicode to NFC, strips trailing
  dots and spaces (Windows drops them on write, which would silently merge two names), defuses
  reserved device names with or without an extension, and truncates the stem to 255 characters
  while keeping the extension. Only the **final** suffix is treated as the extension —
  `Book 1.5 - Extras.m4b` keeps its title, which matters far more often than `.tar.gz` does.
  **Collisions** try the requested name first, then `stem-1.ext`, `stem-2.ext`. A
  `DestinationPlanner` is created per run — never shared globally — and combines what exists on
  disk with what the batch has already planned, so two proposed outputs cannot select one
  destination before either file exists. Comparison is case-insensitive on every platform:
  Windows and macOS are case-insensitive anyway, and erring toward an extra `-1` beats erring
  toward an overwrite.
  **Safety:** `assert_contained` normalises without requiring the path to exist, so an
  unresolved child is checked rather than assumed safe; `assert_no_link_in` refuses a
  destination established through a symlink or junction *even when the link points back inside
  the root*, which containment alone cannot catch; `assert_not_input` and
  `assert_outside_source_trees` keep outputs off the inputs and out of the source tree. Every
  failure is a typed `OutputPathError` carrying a human-readable `message` and a separate
  technical `detail`. **Nothing here deletes anything.**
  **Planning:** `plan_flat` puts individually selected files straight into the run directory
  without recreating parent trees (Decision 31A), numbering same-named files;
  `plan_mirrored` reproduces each source's relative parent under one declared root;
  `plan_multi_root` gives each root a collision-safe container (`Books`, `Books-1`) so one
  root's tree can never merge into another's. A source outside its declared root is rejected
  rather than silently flattened.
- **Preferences & Data (v0.6.0 Drop 2 Phase 2).** `shared/preferences_ui.py` holds the
  cross-platform dialog and the launch-warning window. It is **presentation only**: every
  rule it enforces lives in `shared/config.py` and `shared/settings.py` and is tested
  without Tk. The launcher reaches it from a status-bar `Preferences & Data…` button —
  an `ACT.Ghost.TButton` on Windows, a native unstyled `ttk.Button` on macOS/Linux — plus
  `Ctrl+,` / `Cmd+,` bound on every platform. The launcher holds the one live instance, so
  repeated activation **focuses** rather than stacking duplicates; the window is non-modal
  and Escape closes it. Styling goes through `_style(theme, name)`, which returns `""`
  wherever `theme["styles"]` is absent — a widget naming no style resolves the platform's
  generic one, which is the same mechanism that keeps the five unconverted panels native.
  There is no platform-specific *logic* in the file.
  The dialog shows the effective output base **and where it came from** (built-in default /
  `config.toml` / your saved preference), offers default-or-custom with Browse, validates
  through the Phase 1 rules (absolute or `~` only; relative rejected; environment variables
  never expanded), and **never creates the folder** — saving stores a preference, nothing
  more. A save persists atomically and reloads the snapshot immediately; a failed write is
  rolled back in memory as well as on disk, so "the previous setting is still in use" is
  literally true. No raw traceback ever reaches the GUI; the technical detail goes to the log.
  **Reset Preferences** confirms first, clears mutable preferences only through
  `settings.reset()`, refreshes the fields and source line, and reports failure instead of
  claiming success. It never edits `config.toml` and never touches `.venv`, models, binaries,
  logs, outputs or source media. **Clear Downloaded Data is a separate action** that opens the
  inventory described below; it is never bundled into Reset and never shares its confirmation.
  **Configuration warnings are presented once per launch**: `config.take_launch_warning()`
  owns the guard (platform-neutral, so a reload storm cannot become a dialog storm and a test
  can re-arm it with `reset_launch_warning_guard()`), and the launcher shows one non-modal
  window carrying the whole aggregated summary — never one dialog per bad key, never a
  blocking `messagebox`, and never a reason to fail startup.
- **Downloaded-data maintenance (`shared/maintenance.py`, v0.6.0 Drop 2 Phases 6–7).** The
  catalog, the rules, the schemas and the wording live here; **the GUI process still deletes
  nothing.** The module is platform-neutral, Tk-free, imports neither `shutil` nor
  `subprocess`, and calls no deletion or process primitive; tests assert that structurally.
  Removal happens in a separate helper process after the app exits (see the entry below). The
  catalog is a **closed set
  of exactly four IDs** held as frozen dataclasses behind a `MappingProxyType`, so it cannot
  grow at runtime: `virtual_environment` → `.venv` (removed whole, always post-exit),
  `portable_binaries` → `files/bin`, `downloaded_models` → `files/runtime-data/models`, and
  `application_logs` → `files/runtime-data/logs` (contents only; post-exit, since the session
  log is open). System ffmpeg is never included, and settings, `config.toml`, outputs, source
  media and repository source/docs/tests are absent by construction rather than by a filter.
  **An ID becomes a path in exactly one place.** `authorized_target(asset_id, repo_root)` takes
  an always-explicit root — there is no default, so a test cannot be handed the real project by
  accident — and returns a path only after proving it is the exact compiled target, inside the
  root, not the root, not equal to / inside / containing any protected location, and not reached
  through a symlink, junction or reparse point at any level. Normalisation uses `abspath`, never
  `resolve()`, so a link is *detected* instead of followed. **No arbitrary path can ever reach a
  delete:** the request and result schemas (version 1, immutable, validated in `__post_init__`,
  strict allowlist on deserialize) carry enumerated asset IDs only and have no `path`, `target`,
  `directory`, `root`, `command` or executable field at all. Size estimation is read-only
  (`scandir`/`lstat`), never follows a directory link, tolerates files vanishing mid-walk, and
  reports an unreadable subtree as an *incomplete* estimate — `1.2 MB (at least)`, and *"plus
  data whose size could not be read safely"* in the confirmation — rather than a false exact
  total. The dialog opens with **every box unchecked**, disables missing and unsafe rows, keeps
  `Review Selected Data…` disabled until something eligible is deliberately ticked, persists no
  selection, and measures sizes on a worker thread with every Tk update returned to the main
  thread. The confirmation is one custom window (never a Yes/No box) rebuilt from the live
  selection each time, with Cancel as the focused default and no suppression path. Accepting
  builds one immutable request and hands it to an injected callback and nothing else.
- **Post-exit cleanup (`shared/cleanup_state.py` + `shared/cleanup_worker.py`, v0.6.0 Drop 2
  Phase 7).** The accepted request is saved atomically into one project-owned maintenance
  folder — `files/runtime-data/maintenance/`, not configurable, unreachable from a request, and
  validated on every use to be inside the repository and outside all four removable targets —
  and a **separate helper process** is started with an argument vector (`shell=False`,
  detached, no console) under a Python interpreter *verified* to be outside any virtual
  environment, because the first thing it may remove is the one the app is running from. The
  helper is standard-library only, derives its repository root from its own file location
  rather than from anything the request carries, and is the **only** code in the project that
  deletes a catalog asset. **The app closes only after the helper positively acknowledges the
  request** — started, loaded, validated, ready to wait — and never merely because a process
  was spawned; every other outcome withdraws the request, leaves both windows open and reports
  *"Cleanup did not start. No data was changed…"*. The helper waits for the requesting process
  to exit (bound to that exact process on Windows, so a recycled process id cannot end the wait
  early), retires the request **before** the first deletion so a crash can never replay it,
  makes exactly one attempt, and never retries or relaunches. Every target is **re-derived from
  its ID and re-checked** — containment, protected paths, links, type — immediately before it
  is touched, because the inventory the user saw is not permission: a folder swapped for a
  junction in the meantime is refused, not followed, and a link found inside a target is
  detached rather than descended into. `.venv` goes entirely; the other three keep their folder
  and lose their contents; a missing target is a successful no-op; a locked file fails that one
  item and the pass continues. One immutable result is written atomically and the **next launch
  reports it once** — per item removed / already gone / failed / left alone for safety, the
  space freed, and recovery advice whenever anything was not removed. It never claims complete
  success if something failed, and a corrupt record is moved aside and never executed.
  `bootstrap.py` and both root launchers are unchanged: a removed `.venv` already falls through
  their fast path into the ordinary setup that rebuilds it.
- **Windows design system (v0.6.0 Drop 1 — approved 2026-08-02).** A centralized set of
  *semantic* tokens in `shared/ui_theme.py`, consumed only through the theme bundle:
  `_WINDOWS_COLORS` (surfaces window/sidebar/surface/elevated/muted/border/divider, text
  primary/secondary/disabled/inverse, accent + hover/pressed/soft, focus, success/warning/
  danger, field/selection/scrollbar roles, and the Shared Metadata background/border/header),
  `_WINDOWS_METRICS` (sidebar width, row height, spacing scale, card/field/button padding,
  border and focus widths, scroll width, progress thickness), and `_windows_fonts` (title,
  heading, subheading, section, body, row, small, status, button, mono). **A panel must never
  re-declare a hex literal or a magic number** — it reads `theme["colors"]`,
  `theme["metrics"]`, `theme["fonts"]`, or names a style from `theme["styles"]`. Classic Tk
  widgets (`Canvas`, `Listbox`, `Text`) are coloured through the one sanctioned helper,
  `ui_theme.style_tk_widget(widget, theme, role)`, which is a no-op on any non-Windows
  bundle so panels may call it unconditionally. These primitives are the extension point
  later plans build on.
- **The `ACT.*` style-isolation contract — the load-bearing rule.** `vista` stays the base
  ttk theme, and every style this project registers is namespaced `ACT.*`
  (`ui_theme.WINDOWS_STYLE_PREFIX`). Generic `TFrame` / `TLabel` / `TButton` / `TEntry` /
  `Treeview` / … are **never** created, reconfigured or re-laid-out, and there is no
  `option_add` / `tk_setPalette` anywhere in `scripts/`. Because `vista` draws buttons,
  entries, comboboxes, scrollbars, notebook tabs and Treeview headings with native parts
  that ignore `-background`, each recolorable element is *cloned* out of `clam` into the
  live theme (`ttk::style element create ACT.Button.border from clam Button.border`) and the
  `ACT.*` styles are laid out from those clones. ttk has no style inheritance — a widget
  naming no style resolves the generic one — so an unconverted panel keeps native vista
  rendering while a converted panel opts in explicitly. Every `ACT.*` widget-class variant
  needs its own entry in `_ACT_LAYOUTS` or it silently falls back to the native look.
  `files/tests/test_ui_theme.py`, `test_launcher_smoke.py`, `test_m4b_metadata_editor_ui.py`
  and `test_prototype_regression.py` all assert this isolation, the last of them across a
  whole application build.
- **Conversion boundary (still in force).** The **Windows launcher shell** and the
  **M4B Metadata Editor** are the only converted surfaces. **TTS Audiobook, M4B Converter,
  MP3 Tool, M4B Maker and Cover Image Resizer remain classic** and must stay that way until
  the Plan 9 conversion drop — measured live, they carry **zero** `ACT.*` styles between
  them, against 19 in the editor. Approval of the prototype did not add them to its scope.
- **Import convention:** `scripts/Universal/` is the single import root. Cross-module imports
  are absolute (`tts.*`, `mp3_tools.*`, `shared.*`); entry scripts prepend the import root to
  `sys.path` so they work standalone or via the launcher. The `epub2tts_edge/` subpackage is
  only ever imported as `tts.epub2tts_edge`.
- **Data flow (TTS):** GUI → `tts/epub2tts_edge/runner.run_conversion_job` (cwd-safe temp-dir
  wrapper) → Edge TTS, or `tts/pdf_extractor.pdf_to_txt` → `tts/kokoro_synth.kokoro_file_to_mp3`
  for the Kokoro path. Batch PDF folders go through `tts/batch_convert.py` (threaded, resume,
  retry). Long operations run on worker threads with a Cancel button and a per-tool progress
  indicator (determinate with a percentage where the total is known; indeterminate otherwise —
  e.g. the M4B Maker's single concat/encode); **workers never read Tk variables** (hoisted to
  the main thread — see Decisions.md / memory), and progress flows the same way: the worker enqueues
  `("progress", (done, total))` on its existing queue and only the main-thread drain touches
  the widget.
- **Outputs are copy-based everywhere:** since v0.6.0 Drop 2 Phase 4 every transforming tool
  writes into a run directory reserved at validated operation start under
  `<output base>/<Tool>-Outputs/<Tool>-N/`; imported originals are only ever read. There is
  currently **no** in-place exception — the Cover Image overwrite control is disabled and its
  parameter forced `False` until Phase 5 rebuilds it as a confirmed source-side mode.

## Features

- **TTS Audiobook** (`tts/epub2tts_gui.py`) — EPUB/PDF/TXT → MP3; 12 voices (7 Edge network +
  5 Kokoro local AI); single file or batch folder (PDF / TXT; nested subfolders are mirrored
  in the output so same-named files in different books never collide); per-chunk retry;
  Cancel. Edge voices honor all five pause fields in **single-file** conversion; Edge
  **batch folder** mode honors speaker + rate only — inter-sentence pacing there is
  Edge's natural prosody by deliberate decision (a timing-aware batch rewrite was
  built, measured, and rejected by ear — see Decisions.md 2026-07-19). Kokoro voices
  honor the paragraph pause (mapped to the inter-chunk gap) and the end-of-recording
  pause — sentence/title/chapter parity is deliberately deferred (see Decisions.md). Dev/QA helper
  `tts/generate_voice_samples.py` writes one short sample per voice to
  `files/test-for-manual-listen-elmatthe/` (gitignored, never imported by the app).
- **M4B Converter** (`mp3_tools/m4b_converter.py`) — batch M4B → clean MP3 (libmp3lame VBR),
  optional bulk metadata + auto track numbers.
- **MP3 Tool** (`mp3_tools/mp3_tool.py`) — combine MP3s into one, time-edit track ends, bulk
  ID3 tagging with chapter-title paste.
- **M4B Maker** (`mp3_tools/m4b_maker.py`) — MP3s → chaptered M4B with cover art, metadata, and
  Audiobookshelf-compatible series tags (freeform `----:com.apple.iTunes:SERIES`/`SERIES-PART`
  atoms — what ABS's ffprobe scanner actually reads).
- **Cover Image Converter** (`mp3_tools/cover_resizer.py`) — pad/crop cover art to square;
  JPG/PNG/HEIC.
- **M4B Metadata Editor** (`mp3_tools/m4b_metadata_editor.py`) — edit existing M4B tags without
  re-encoding; preserve-by-default (blank = unchanged); series detection across vendor freeform
  + movement atoms; auto-number series parts; per-file chapter-title import; writes copies.
  Batch mode (multiple files or the "Open Folder…" picker, non-recursive) pre-fills fields
  whose value is identical across all loaded files and marks differing ones "(varies)";
  single-file mode is unchanged. The tag/settings sections scroll in a TTS-style canvas
  (wheel/trackpad via `enable_mousewheel`); the action buttons and a fixed Log sit
  below the scroll area, always visible.
  **Presentation (v0.6.0 Drop 1):** the panel forks on `theme["mode"]`. On Windows it builds
  a card layout from the `ACT.*` design system — an "Audiobook Files" card, the **Shared
  Metadata** surface, "Chapter Titles (optional)", "Output", then the always-visible action
  bar and Log. **Every other mode builds the historical layout byte-for-byte**, so macOS and
  Linux are untouched. The fork is presentation only: both branches create the same widgets
  and attributes, and every callback, worker, queue, progress, cancel path and busy/idle
  transition below the builders is shared and unaware of which one drew the screen. Nothing
  about metadata reading/writing, field precedence, file order, output paths, filenames, tag
  namespaces, chapter logic, thread boundaries or cancellation timing differs between them.
- **Shared Metadata (visual treatment only).** The editor's existing batch-wide fields are
  grouped on a distinct muted-navy surface with an accent border, accent header and a
  caption reading "These values are written to every loaded file. Blank fields are left
  unchanged." **This is a visual statement of behaviour that already existed** — the same
  shared-value / "(varies)" detection shipped in v0.5.0. It adds **no** per-book override,
  **no** field precedence, **no** disabling and **no** workspace: Decision 20B's full
  populated-global-overrides model needs the Plan 6 data model and the Plan 8 editor
  workflow and does **not** exist today. `test_shared_metadata_grouping_adds_no_precedence_or_disabling`
  pins that down.
- **Summary/Details specimen (presentation only, developer-only).**
  `files/tests/manual_windows_ui_prototype.py` is a developer fixture, **not part of the
  product and not part of the test suite**: pytest cannot collect it, it is not in
  `launcher.TOOLS`, it lives under `files/` rather than the shipped `scripts/` tree, and
  nothing in the product imports it. It renders the *production* theme primitives and the
  *production* editor to reach populated, active-run and Summary/Details states that are
  otherwise slow or non-deterministic to photograph. Its Summary/Details sheet is a visual
  component specimen carrying its own on-screen disclaimer: there is **no** filtering, **no**
  dual log buffers, **no** technical-log routing, **no** job snapshot, **no** ETA, **no**
  Retry Failed and **no** Pause/Resume. That behaviour belongs to Plan 3 and is absent from
  the shipped panel, which contains no notebook at all.

## Project Layout Notes

Standard AI-WORKSPACE.md layout since v0.5.0:

```
Audiobook-Creation-Tool/
├── README.md, AI-WORKSPACE.md, .gitignore
├── Setup_and_Run-audiobook-creation-tool.bat / .command   ← the ONLY user-facing entry files
├── .venv/                      ← auto-built by the bootstrap (gitignored)
├── .claude/  .codex/           ← agent wiring
├── config.toml                 ← committed project defaults (validated by verify.py)
├── md-instructions/            ← Briefing, Changelog, Decisions, Handoff (+ temporary drops)
├── scripts/
│   ├── requirements.txt        ← single pinned cross-platform list
│   ├── verify.py               ← mechanical gate: pytest + pinned deps + de-templated docs
│   │                             + exact canonical doc names (os.listdir, no alias)
│   │                             + a valid committed config.toml (fails on any diagnostic)
│   ├── Universal/              ← ALL program code (launcher.py, tts/, mp3_tools/, shared/)
│   ├── Windows/  MacOS/        ← empty by design (.gitkeep) — only truly OS-specific code
└── files/                      ← dev-only + runtime (nothing here ships in release zips)
    ├── bin/                    ← portable ffmpeg fallback (gitignored)
    ├── runtime-data/           ← logs/, settings.json, models/huggingface/ (Kokoro ~300 MB;
    │                             all gitignored — delete with .venv for a full uninstall)
    ├── tests/                  ← pytest suite + Kokoro voice harness
    ├── test-files/             ← local fixtures incl. copyrighted media (entirely untracked;
    │                             point tests at it via KOKORO_TEST_PDF_FOLDER)
    ├── test-logs/              ← QA logs + harness outputs (gitignored)
    ├── UI-Current-Screenshots/ ← the v0.5.1 before-state UI reference (8 images, tracked)
    ├── UI-Prototype-Screenshots/v0.6.0-drop1/
    │                           ← the APPROVED v0.6.0 Drop 1 evidence: 10 images, 1920x1080
    │                             maximized, true 100% and true 125% Windows scaling (tracked)
    └── release-history/        ← one-shot docs from past releases (v0.3.1 set)
```

Release zips (built by `shared/release.py` into `dist/`) contain README + the OS's launcher +
the whole `scripts/` tree; both OS zips share the same code and differ only in launcher.

## Current Version

v0.5.1 (v0.5.0 line plus the Jenny Edge voice; v0.4.0 is the latest
published GitHub release — remote: [elmatthe/audiobook-creation-tool](https://github.com/elmatthe/audiobook-creation-tool))

## High-Level State

All six tools are built, live-verified on Windows (v0.1.0 test matrix: 18/18 applicable rows
PASS; later releases re-verified their areas) **and on macOS (2026-07-08: full per-tool live
pass under the Finder shell — the `0.5.0-macos-component-verify` plan)**, and shipped through
GitHub Releases v0.1.0–v0.4.0.
v0.4.0 added Kokoro self-heal on every launch, the in-tree HF model cache, and the 5-voice
verification harness. v0.5.0 is a multi-drop line: Drop 1 (this restructure — no tool behaviour
changes), then metadata, TTS, script hardening, and UI drops.

**v0.6.0 Drop 1 (Windows UI prototype) — approved 2026-08-02, not released.** The Windows
design system, the converted launcher shell and the converted M4B Metadata Editor passed the
maintainer's visual gate against the ten-image evidence matrix under
`files/UI-Prototype-Screenshots/v0.6.0-drop1/` (1920×1080, maximized, true 100% and true 125%
Windows display scaling). **Approval is of the design contract, not a release:** `version.py`
is still `0.5.1`, no v0.6.0 exists, and the remaining five panels are unconverted. The eight
further v0.6.x plans are named in the sequencing note but undrafted; **Plan 2 is the next
implementation-planning target.**

**Non-Windows preservation is a standing contract.** macOS `aqua`/Finder and the Linux/other
`classic` fallback must not change as Windows evolves. At the v0.6.0 Drop 1 approval this was
proven by AST-level comparison against `master`: `_apply_darwin`, `_apply_classic`,
`_classic_font_family`, `_resolve_color`, `_blend`, `_is_dark`, `_mac_font_family`,
`enable_mousewheel`, all five `ProgressIndicator` methods, `launcher._build_ui_darwin` and
`launcher._build_ui_classic` are **byte-identical**; `apply_theme` gained only its `win32`
arm. Four automated tests keep it that way (`test_apply_theme_on_current_platform` aqua arm,
`test_classic_branch_other_platform`, `test_non_windows_theme_builds_the_unconverted_layout`,
`test_an_aqua_bundle_builds_the_historical_layout`). **A live macOS re-verification of the
v0.6.0 line has not been performed** — it is an explicitly approved deferral, not a pass, and
the exact five-step smoke test is written out in `Handoff.md`.

**Known limitations (documented, not bugs):**
- **The application is DPI-unaware on Windows — unresolved future work, not finished
  behaviour.** `GetProcessDpiAwareness` returns `UNAWARE`, and neither the venv's
  `python.exe` / `pythonw.exe` nor the base Python 3.12.10 they are copied from carries a
  `dpiAware` manifest entry; `pythonw.exe` is what `Setup_and_Run` launches, so this is the
  real end-user path. At 100% scaling there is no virtualization and rendering is 1:1. At
  125% Windows bitmap-scales the whole window: the app's coordinate space never changes (Tk
  still reports 96 px/inch), so **text is slightly soft rather than re-rendered at 120 DPI**.
  The same fact is why **nothing clips, overlaps or reflows at 125%** — every dimension
  scales by an identical factor, and the measured geometry at 1024×720 and 920×600 is
  byte-identical to the 100% pass. This did **not** block the v0.6.0 Drop 1 approval because
  the app stays usable and unclipped, but it is **explicitly unresolved Windows work**
  reserved for Plan 9 or an appropriately scoped future plan. Fixing it means a manifest or
  a `SetProcessDpiAwareness` call at startup plus a re-measure of every fixed pixel metric —
  a real behaviour change, deliberately not attempted during the prototype.
- **The final GUI fit contract (target for Plan 9, binding on all new UI now).** At the
  reference environments — Windows 11 at 1920×1080 with both 100% and 125% display scaling,
  plus the approved live macOS reference display — the **maximized** launcher must show each
  complete tool view **without a whole-panel or whole-form scrollbar where practical**: the
  bounded configuration sections, primary actions, run controls, progress/status and output
  location all visible at once. Reach that with adaptive layout (responsive columns, compact
  spacing, wrapping, collapsible secondary material, local list sizing) rather than by putting
  a whole tool inside a permanently scrolling canvas. **Scrolling stays valid for genuinely
  unbounded content** — imported-file lists, book/job collections, chapter-title collections,
  long metadata/result details, Summary/Details logs, thumbnail browsers — and must be kept
  *local to that region*, with primary actions, Cancel/Pause/Resume, progress, status and
  output access still reachable. "Full screen" here means the ordinary window maximized by the
  OS; it does **not** mean an F11 borderless mode and does **not** change the startup geometry
  or force auto-maximizing. At the `920×600` minimum no plan promises every variable-length
  section is simultaneously visible — the requirement is graceful adaptation: no unreachable
  primary action, no unresolvable overlap, no clipped confirmation button. `MIN_SIZE` and
  `DEFAULT_GEOMETRY` are unchanged (below). The M4B Metadata Editor's permanently scrolling
  form is an accepted Plan 1 limitation, not the final target; Plan 9 owns the reflow.
- **Windows geometry, deliberately unchanged.** `MIN_SIZE = (920, 600)` and
  `DEFAULT_GEOMETRY = "1024x720"` stay as they are. At the 920×600 minimum the **M4B
  Converter's** primary action and Log are still clipped (~19 px and ~108 px bottom + 75 px
  right, identical at both scaling levels). That panel is unconverted and Plan 9 will rebuild
  it, so the clipping is deferred there rather than fixed by widening the minimum on behalf
  of a layout that is about to change. The converted editor clips nothing at any size or
  scaling; its long form is a deliberate scroll region at every size, with the action bar and
  Log outside it.
- **The Windows `ttk.Combobox` popdown is unthemed** (Tk draws it as a native list ttk
  cannot restyle), and the **window title bar stays light** above the dark app (Tk would need
  a Win32 `DwmSetWindowAttribute` call). Both are Plan 9 items.
- **Windows xHE-AAC decode** — ffmpeg's native AAC decoder can't decode xHE-AAC (USAC) M4Bs;
  macOS routes decoding through Apple's `aac_at` decoder, which supports xHE-AAC. Confirmed
  Windows limitation since v0.3.2. The macOS `aac_at` path is live-verified on standard
  AAC-LC M4Bs, but an actual xHE-AAC/USAC decode on macOS is still unverified — no USAC
  sample on hand (2026-07-08).
- **Fresh one-click clean-machine install** (winget Python 3.12 + multi-GB torch + 300 MB
  model) is verified in pieces, not yet end-to-end on a virgin box.
- The `.bat` entry point briefly flashes its own cmd window on launch (the GUI itself never
  shows a console); eliminating it entirely would need a shortcut shim — deferred.

**Owner ground rules:** non-technical users are the audience; no visible consoles; every
dependency `==`-pinned; repo root stays minimal; upstream credit (GPL-3.0): epub2tts-edge
(Christopher Aedo), edge-tts, Kokoro-82M.
