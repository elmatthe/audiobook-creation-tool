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

The Audiobook Creation Tool is a cross-platform (Windows + macOS) desktop app that turns books
and loose audio into finished, tagged audiobooks. It bundles a **text-to-speech engine**
(**PDF / TXT → MP3** — Microsoft Edge TTS over the network, plus two local AI engines, Kokoro-82M
and Chatterbox Turbo) with a suite of **MP3/M4B utilities** (combine MP3s, batch M4B→MP3, build chaptered M4B
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
- **Key libraries:** edge-tts (network TTS), kokoro + torch (local AI TTS), chatterbox-tts
  (the second local AI TTS engine, added in v0.6.1), mutagen (audio metadata), PyMuPDF/fitz (PDF
  text extraction), pydub + soundfile + numpy/scipy (audio assembly), nltk (sentence
  tokenization), pillow + pillow-heif (cover images, including HEIC/HEIF). All pinned to exact
  versions in `scripts/requirements.txt`. **`ebooklib`, `beautifulsoup4` and `lxml` were removed
  in v0.6.1** when EPUB was retired — each had its consumers enumerated and its
  reverse-dependencies checked first, and the three pins are recorded verbatim in a
  `requirements.txt` comment so restoration is mechanical. `setuptools` is deliberately held at
  `80.9.0` (not the newer `82.0.1`) as recorded compatibility debt: `resemble-perth`, which
  Chatterbox pulls in, imports the `pkg_resources` that `82.0.1` removed.
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
  `image_capabilities.py` (the one place HEIC/HEIF support is probed, with decode and encode
  reported separately — see *Image capabilities* below), `espeak_data.py` (the macOS espeak-ng
  short-data-path seam Kokoro needs — see *Known limitations*),
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
  `<output base>/<Tool>-Outputs/<Tool>-N/`; imported originals are only ever read. Phase 5 then
  added the **only two** destination exceptions, both opt-in and both described below: Cover
  Image's source-side modes (numbered copies by default, replacement off by default and behind
  a strong confirmation) and M4B Maker's custom destination. Everything else is copy-based, and
  no normal operation silently overwrites an input or an existing output.
- **A tool panel displays the destination; it never decides it.** The read-only "Output folder"
  line is a hint from `output_paths.destination_hint()`, and the run resolves the base again at
  operation start, so a preference changed mid-session can never move an operation already
  under way. Since the Phase 8 remediation the reverse is also true: `output_paths` keeps a
  small registry of those displays, and a successful Preferences **Save** or **Reset** re-points
  every already-built panel immediately, so the application never shows a destination it would
  not actually use. Panels are not rebuilt to achieve that, and none of them resolves a path
  itself.

- **Downloaded-data maintenance (v0.6.0 Drop 2 Phases 6–7).** *Preferences & Data → Clear
  Downloaded Data* inventories exactly **four** enumerated assets — the virtual environment,
  portable binaries, downloaded voice models and application logs — and nothing else can be
  named. The catalog is a frozen mapping of closed IDs; a request carries IDs only, never a
  path, so no serialized or GUI-supplied path can reach a deletion. Nothing is selected by
  default, a missing or unsafe row cannot be selected, and reviewing is always non-destructive.
- **Cleanup happens after the application has exited, in a separate non-venv process.** The
  confirmed request is written atomically to `files/runtime-data/maintenance/` — a
  project-owned location, re-validated on every use to be inside the repository and outside all
  four removable targets. A standard-library-only coordinator is started with an argument
  vector and `shell=False` under an interpreter *verified* to sit outside any virtual
  environment; the GUI closes only once that coordinator has positively acknowledged the
  request, waits for the requesting process to exit by handle (not by PID), retires the request
  before the first deletion so a crash cannot replay it, and re-authorizes every target
  immediately before removing it. Deletion is post-order and link-safe: links are detached,
  never followed. The result is written atomically and reported **once** on the next launch,
  then retired. `.venv` removal is expected to be followed by an ordinary launcher rebuild.
- **Release packaging (v0.6.0 Drop 2 Phase 8).** Both platform archives carry the committed root
  `config.toml` byte-for-byte beside `README.md`, the correct platform launcher (stored `0o755`
  so a macOS extraction is immediately runnable) and the complete `scripts/` tree — and nothing
  else. Packaging works by **explicit scope**: the root files are a named list and exactly one
  tree is walked, so nothing is ever copied wholesale and then pruned. That is why the
  maintainer's unrelated untracked root `config-template.toml` needs no exclusion rule and has
  none; the packager never names it, the runtime never loads it, and automated tests prove both
  even while it sits directly beside `config.toml`.

- **Shared importing and job-control foundation (v0.6.0 Drop 3).** Four modules under
  `scripts/Universal/shared/`, built with **no production consumer at the time**. They exist so the
  tool plans that follow can adopt one importer and one set of run controls instead of six
  divergent ones; adoption belongs to Plans 4–8 and is now under way — **TTS Audiobook and Cover
  Image Converter adopted them in v0.6.1 (Plan 4) and the M4B Converter in v0.6.2 (Plan 5)** — while
  the remaining three panels still use their own importing and run handling.

  - **`importing.py`** — the immutable vocabulary plus the traversal core and the list owner.
    An adopting tool supplies its own `SupportedTypeCatalog`; there is no universal media list
    here. `ImportOptions` freezes the selected types, `include_hidden_folders` and
    `allow_duplicate_files` per import. Traversal is **read-only and non-following**: its
    entire filesystem budget is `os.scandir` and `lstat`, so it can neither write nor walk
    through a symlink, a Windows junction or any other reparse point, all of which are refused
    and reported rather than followed — link classification reuses the already-validated
    `maintenance.is_link` rather than growing a second one, because a junction reports
    `is_symlink() == False` and a naive check would fail open on exactly the case that matters.
    Within each root, compatible direct files are emitted before child directories and both are
    ordered by a Unicode-aware natural key, so `1, 2, 10` comes out in that order; root order is
    never globally re-sorted. Hidden directories are skipped and reported unless the option is
    on; a hidden file the user chose explicitly is still accepted. `ImportedFileManager` owns an
    ordered list with a revision that moves only on a real change, mints a stable
    **occurrence ID** per entry, restores selection by that ID rather than by index or path,
    moves a multi-selected block as one unit without wrapping, and commits a planned transaction
    **atomically** — a cancelled, declined, failed or conflicting import changes nothing at all.
    Deduplication prefers non-following file identity and falls back to a normalized lexical
    path; a deliberate duplicate gets a new occurrence but keeps its true source identity, so it
    is never disguised as a different file. Removing or clearing the list never deletes a source.
  - **`import_coordination.py`** — one background scan at a time, owned end to end.
    `ImportCoordinator` fences every manager-touching entry point to the owning (main) thread,
    raises the **broad-root warning before any worker exists** — a volume root, a UNC share root
    or the exact home directory, refused outright if no confirmer was wired — publishes typed
    events on a queue, and applies Plan 2's captured
    `importing.large_result_warning_threshold` **after** a completed scan, where equal to the
    threshold does not warn and there is no hard maximum. `ImportCancellation` is a per-operation
    event with **no connection whatsoever** to a processing job's cancellation: Cancel Import
    stops a scan and can never reach a conversion. `ImportPoller` is a Tk-free polling seam
    shaped exactly like `after`/`after_cancel`.
  - **`job_control.py`** — the cooperative run model and its reporting. `JobController` enforces
    one transition table with a condition rather than a spin, and it is **truthful**: a pause
    request stays `PAUSE_REQUESTED` while an indivisible stage runs and becomes `PAUSED` only on
    the worker's acknowledgement, cancel wakes a paused worker and reaches `CANCELLED` only after
    that worker has stopped starting work and cleaned up, and a run ends exactly once. No Python
    thread and no OS process is ever suspended. `capture_run` deep-freezes one configuration per
    run, `ControlKind`/`LOCK_MATRIX`/`is_locked` and `JobAction`/`is_available` derive control
    state UI-neutrally, `RunResult` settles ordered item outcomes without letting an item failure
    force a fatal job failure, and `RetryRequest` rebuilds Retry Failed **against the exact
    original frozen snapshot** — never against current widgets, settings or list contents. The
    reporting layer on top produces typed immutable events with an injected clock;
    `JobEventStream` rejects stale-run, unknown-occurrence, post-terminal and duplicate-terminal
    events and a rejected event is **inert** — not rendered, not counted, not logged. Summary
    shows milestones and **structurally cannot** show a diagnostic, because the projection that
    builds it never reads the field commands and tracebacks live in; Details keeps every one of
    them. `LoggerBridge` feeds technical events to the **one existing** session logger and
    creates no second log or retention policy. Progress is monotonic within a scope and an
    ending never changes a counter, so a cancelled run keeps the count it really reached.
    `EtaEstimator` uses only comparable completed samples from the current run — three minimum,
    a rolling twenty, paused time excluded — and says `Calculating…` for every unreliable case
    rather than guessing.
  - **`job_ui.py`** — the only module in the drop that imports Tk, and the reason the other
    three provably do not. It is compositional: each class *owns* a `frame` rather than *being*
    one, every decision arrives as a callback, and there is no universal base panel for a later
    tool to fight. `MainThreadPump` owns the single `after` chain (the import poller rides its
    `schedule`/`cancel` seam rather than opening a second one), `MainThreadGuard` opens every
    public Tk-reaching method so a worker is refused **before** a widget is touched, and workers
    communicate only by putting immutable values on a queue. Teardown is idempotent, cancels its
    own callback, makes later events inert and survives a destroyed root. It **reuses the
    existing `ui_theme.ProgressIndicator`** unstyled, asks the theme bundle for `ACT.*` names on
    Windows, and asks for **no style at all** on macOS aqua and the classic branch — which is
    how the native appearance is preserved without this module ever testing the platform itself.
    A snapshot proves it leaks into no generic ttk style.

  A developer-only harness, `files/tests/manual_plan3_harness.py`, drives these adapters against
  a generated disposable fixture root for manual validation. It has **no launcher entry, is not
  collected by pytest, is imported by nothing under `scripts/`, and is excluded from both
  release archives** by the packager's explicit `scripts/` scope; its "work" is a timed no-op
  that runs no process and produces no output.


### Image capabilities (v0.6.1 Plan 4)

`shared/image_capabilities.py` replaced the bare optional `import pillow_heif` that used to sit at
the top of `cover_resizer.py`. It imports and registers the plugin exactly once, under a lock, and
**reports decode and encode independently** — a `libheif` build can genuinely read HEIC and be
unable to write it. Encode capability is proved by *actually encoding* a 1×1 image to memory,
because `register_heif_opener()` installs a saver whether or not an encoder exists behind it. The
probe never raises; every failure becomes a capability carrying a truthful reason, and the import
dialog's filter follows the probe rather than a hard-coded string.

**HEIC preserves the input format.** `resize_for_audiobook` refuses a `.heic`/`.heif` destination
it cannot honour, with `UnsupportedImageFormat`, rather than silently writing a `.jpg`. The
pre-existing `.jpg` fallback for genuinely *unknown* extensions such as `.webp` is unchanged, and
`REPLACEABLE_SUFFIXES` / `written_suffix()` are byte-for-byte unchanged. `pillow-heif==1.5.0` is
pinned but deliberately **not** in `bootstrap.REQUIRED_IMPORTS`: that list is what a machine must
have, and optional HEIC support is not a startup requirement.

### The third TTS engine — Chatterbox (v0.6.1 Plan 4)

`tts/chatterbox_synth.py` mirrors `kokoro_synth.py`: the same module-load `HF_HOME` fallback into
the **existing** in-tree model cache (there is no second cache), lazy imports so nothing heavy
loads at import time, a single-first-load allowance for Windows Application Control, and an
identical worker signature. It drives `chatterbox.tts_turbo.ChatterboxTurboTTS` from the pinned
`chatterbox-tts==0.1.7` wheel.

- **Device selection resolves `cuda → mps → cpu` behind one testable seam.** The engine was
  adopted CPU-first on measured evidence and is **optional and non-default**.
- **Four fixed voices** cloned from four maintainer-supplied reference recordings. Reference audio
  is verified by SHA-256 **on every use**; short derivatives and cached voice-identity
  conditionals live under the ignored `files/runtime-data/chatterbox/`, keyed on voice + source
  hash + engine release + clip spec so a stale entry misses rather than gets reused. A manifest
  records label → source → source SHA-256 → derivative → parameters, and writes back into the
  recordings folder are refused structurally.
- **Text is planned on natural boundaries** — paragraph → sentence → clause → whitespace → hard
  limit, packed to a 300-character ceiling — and **no structural newline reaches the model**,
  because the model renders one as a pause of no fixed length. A plan that does not reproduce its
  source text is refused outright.
- **Degraded installs are truthful.** Without the package, the application starts and offers the
  twelve Edge/Kokoro voices. Without the recordings, it starts, converts, and reports the
  Chatterbox voices as *setup required* — missing recordings are deliberately not a startup
  requirement, and no broken selection is offered.
- The upstream PerTh watermark path is untouched.

**Local assets are a portability boundary, not an asset.** The four reference recordings and every
derivative and cached conditional are ignored, untracked and never packaged. Making Chatterbox
work on a different machine requires the maintainer to place their own recordings and is a
separately authorized action — nothing in this repository carries them.

### The M4B Converter (v0.6.2 Plan 5)

The Converter is the first tool rebuilt on the Drop-3 foundation, and the shape of that adoption is
the point: `mp3_tools/m4b_converter.py` is the panel, and it owns no policy — it is the only one of
these modules that imports Tk. The policy is decomposed into ten helper modules beside it, none of
which imports `tkinter` at all:

| Module | Responsibility |
|---|---|
| `m4b_chapters.py` | The chapter vocabulary: the probe result types, the structural verdict on them, and the complete-timeline partition computed from a verdict that passed. Stdlib-only and pure — no I/O, no ffprobe, no clock. |
| `m4b_probe.py` | The one ffprobe call per source. A single `-print_format json` read yields format tags, streams and chapters together, plus the source's compatible metadata and its embedded cover. Runs a subprocess, so it belongs on a worker thread. |
| `m4b_naming.py` | Turning one source chapter title into one safe split-output filename, in two stages so that a title containing `/` or `\` is not silently reduced to its last element by `shared.output_paths.sanitize_component`. Strings in, strings out. |
| `m4b_numbering.py` | The one number a run has to earn — the optional sequential `track` a **whole book** carries, proposed before ffmpeg runs and committed only on success, so a failure consumes nothing and the sequence stays gap-free. The two *structural* numbers do not live here. |
| `m4b_metadata.py` | What metadata and artwork each of the six cells (Preserve / Replace / Strip × whole / segment) writes — decided, never executed. Owns the strict five-field allowlist, chapter retention, the artwork policy and the output-side ffmpeg metadata arguments. |
| `m4b_destinations.py` | Where each imported occurrence's outputs go, decided once per run. Spends the importer's provenance through the shared Plan-2 planners and returns answers keyed by occurrence id, expanding a split book into one planner entry per requested filename. |
| `m4b_commands.py` | The ffmpeg argument vectors the run will execute — built here, never run. Owns the measured **output-side** `-ss` ordering, which must not be "optimised" to input-side seek. |
| `m4b_plan.py` | Where every other layer meets and becomes one immutable answer to "what is this run going to do?" — the frozen `ConversionPlan`. No widget, no variable, no thread, no queue, no process: values only. |
| `m4b_execution.py` | Running one already-planned segment and being able to stop it. Handed a `SegmentWork` carrying a frozen span, tag set, cover and destination; reinterprets no decision. Owns the child process and the temp-file diagnostics drain. |
| `m4b_winaudio.py` | Decoding an xHE-AAC (MPEG-D USAC) source through Windows Media Foundation via `ctypes` when ffmpeg's native AAC decoder cannot, measured at 100.0004% of a source ffmpeg silently truncated by 23.91%. |

Artwork selection and policy are **not** a separate module: they live with the metadata contract in
`m4b_metadata.py` (`wants_artwork`, and the `attached_pic` stream identification fed to it from
`m4b_probe`), which is where the Preserve/Replace/Strip decision that governs them already lives.
The panel imports the shared importer, the shared job controls, the shared destination planner and
the shared output reservation rather than growing private copies, and the whole run is decided
before ffmpeg is invoked once.

- **A run is frozen, and the freeze is total.** Pressing Convert calls `job_control.capture_run`,
  and the worker reads only that snapshot — the queue, the mode, the metadata choice, the numbering
  choice **and the configuration the run started under**. The output directory is reserved through
  `output_paths.reserve_run_directory(TOOL_KEY, effective=<the run's frozen config>)`, so a
  Preferences change mid-run cannot move a conversion already in flight, and Retry Failed rebuilds
  from that same snapshot to the same planned paths rather than from current widgets.
- **Splitting is a partition, not a chapter loop.** `m4b_plan` builds a **complete timeline**: every
  second of the source belongs to exactly one segment, including a pre-first-chapter head and a
  post-last-chapter tail, and the segments are proved contiguous and exhaustive rather than assumed
  to be. Segments are cut with output-side `-ss`/`-t`, which is why a long book with an attached
  cover no longer produces a fraction of a second of audio.
- **Metadata is an allowlist enforced at the ffmpeg boundary.** Every output starts from
  `-map_metadata -1` and receives only the five permitted fields through the one shared mapping in
  `m4b_metadata.py`. Chapter retention is a separate axis (`-map_chapters 0` or `-1`) and whole-book
  retention re-attaches the source's chapter **titles** through `-metadata:c:N`, which the allowlist
  firewall would otherwise strip. Outputs that carry chapters or tags are written `-id3v2_version 3`,
  because that is the version Windows Explorer reads.
- **Destinations are planned centrally and collision-safe.** `m4b_destinations` plans direct files,
  grouped folders and — for Split — one **container folder per occurrence** through the same shared
  planners, so two books named alike, or the same book imported twice, each get their own folder.
  Every component is sanitized to a fixed point, every planned path is asserted contained under the
  reserved run root, and every path is asserted not to be an input. Nothing is ever overwritten and
  no source is ever modified.
- **Duplicates are occurrences, never paths.** Outcomes, retries and destinations are keyed on the
  importer's occurrence ID, so importing one book twice is a supported deliberate act rather than a
  collapsed pair.
- **Decoding is routed, and a route that cannot be trusted stops the run.** On Windows an xHE-AAC
  (USAC) source is decoded through Windows Media Foundation into a PCM timeline instead of ffmpeg's
  native AAC decoder; macOS uses Apple's `aac_at`. When neither route can decode a source, the run
  reports it rather than writing a short book, and the drift check does not blame the platform on a
  path it deliberately routed around.

## Features

- **TTS Audiobook** (`tts/epub2tts_gui.py`) — **PDF/TXT → MP3** (v0.6.1: EPUB retired, see
  below); **16 voices** (7 Edge network + 5 Kokoro local AI + 4 Chatterbox local AI); **one
  unified queue** in which direct files and whole folders coexist in a single run — folder-derived
  items are mirrored into the output so same-named files in different books never collide, direct
  files are placed flat, and occurrence identity, deliberate duplicates, provenance and natural
  ordering all survive the run's frozen snapshot and a Retry Failed; Plan 3's shared job controls
  (Pause/Resume, Cancel, Summary/Details, progress, current-run ETA, Retry Failed); per-chunk
  retry. **The module name is historical**: `epub2tts_gui` / `epub2tts_edge` keep the upstream
  GPL-3.0 provenance of the surviving Edge engine and no longer imply EPUB support.
  Edge voices honor all five pause fields in **single-file** conversion; Edge
  **batch folder** mode honors speaker + rate only — inter-sentence pacing there is
  Edge's natural prosody by deliberate decision (a timing-aware batch rewrite was
  built, measured, and rejected by ear — see Decisions.md 2026-07-19). Kokoro voices
  honor the paragraph pause (mapped to the inter-chunk gap) and the end-of-recording
  pause — sentence/title/chapter parity is deliberately deferred (see Decisions.md). Dev/QA helper
  `tts/generate_voice_samples.py` writes one short sample per voice to
  `files/test-for-manual-listen-elmatthe/` (gitignored, never imported by the app).
- **M4B Converter** (`mp3_tools/m4b_converter.py`) — batch M4B → MP3 (libmp3lame VBR), **whole
  book or split by chapter** (v0.6.2 Plan 5). Import files or a folder with an **Include
  subfolders** option; reorder, remove, clear, and import the same book twice deliberately.
  Metadata is *Preserve*, *Replace* or *Write none*, restricted throughout to title, artist, album
  artist, album and an optional track number — nothing else from the source travels with it. A
  whole book keeps the source's chapter map **and its chapter titles** under Preserve and Replace;
  *Write none* removes it. Embedded cover art is copied (never re-encoded) by Preserve and Replace
  and removed by Write none, on whole books and on every fragment of a split. A split is a complete
  partition of the book — the head before the first chapter and the tail after the last are
  included — and each book's fragments land in **their own folder**. What a split fragment carries
  depends on the mode, and the two cases are genuinely different: under **Preserve** and
  **Replace** a fragment inherits only the book-level identity (`artist`, `album_artist`, `album`)
  and **regenerates its own `title` and its structural `track`**, which always win; under **Write
  none / Strip** a fragment gets **no metadata at all** — nothing is regenerated, not even a title
  or a track number. Optional whole-book track numbering is **off by default** and numbers only
  successes, so a failure leaves no gap. Progress with an ETA, **Pause/Resume/Cancel** and **Retry
  Failed** come from the shared job controls; sources are never modified and nothing is overwritten.
- **MP3 Tool** (`mp3_tools/mp3_tool.py`) — combine MP3s into one, time-edit track ends, bulk
  ID3 tagging with chapter-title paste.
- **M4B Maker** (`mp3_tools/m4b_maker.py`) — MP3s → chaptered M4B with cover art, metadata, and
  Audiobookshelf-compatible series tags (freeform `----:com.apple.iTunes:SERIES`/`SERIES-PART`
  atoms — what ABS's ffprobe scanner actually reads).
- **Cover Image Converter** (`mp3_tools/cover_resizer.py`) — pad/crop cover art to square;
  JPG/PNG/HEIC (HEIC in → HEIC out; never a silent JPEG substitution). Adopts the shared importer
  and the shared job controls, and adds a **three-view browser — Details, List and Medium
  Thumbnails**, defaulting to Details. All three are projections of the one imported-file manager
  rather than a rival list, so order and selection survive a view switch by construction, and two
  deliberate duplicates of one path stay two independently selectable items. Click and key
  handling routes through one pure selection engine, so the three views behave identically, with
  anchors and ranges in **manager order** rather than widget order. Thumbnail decoding runs on a
  worker thread producing plain data only, is lazy and visible-only, and is hard-capped at 60
  items — an unmapped widget honestly answers "all of it" for its own extent, so without the cap a
  5,000-image import would decode 5,000 previews. A bounded LRU (96 entries, deliberately a count
  and not a byte budget) is the single owner of a decoded image. Late results are dropped inertly
  and nothing is lost: the next refresh asks again for whatever is still visible.
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
    ├── archived-code/epub-tts/ ← PERMANENT. The retired EPUB source + its manifest (tracked,
    │                             inert, unpackaged, uncollectable). Not a temporary drop.
    ├── Chatterbox-Voice-Uploads/ ← the four local reference recordings (entirely untracked and
    │                             gitignored; never committed, never packaged)
    ├── UI-Current-Screenshots/ ← the v0.5.1 before-state UI reference (8 images, tracked)
    ├── UI-Prototype-Screenshots/v0.6.0-drop1/
    │                           ← the APPROVED v0.6.0 Drop 1 evidence: 10 images, 1920x1080
    │                             maximized, true 100% and true 125% Windows scaling (tracked)
    └── release-history/        ← one-shot docs from past releases (v0.3.1 set)
```

Release zips (built by `shared/release.py` into `dist/`) contain README + the OS's launcher +
the whole `scripts/` tree; both OS zips share the same code and differ only in launcher.

## Current Version

**v0.6.2** — set at the v0.6.2 Plan 5 closeout on 2026-08-31. v0.4.0 is still the latest
*published* GitHub release (remote:
[elmatthe/audiobook-creation-tool](https://github.com/elmatthe/audiobook-creation-tool)).

**This is a version identity, not a release.** `version.py` and `config.toml` read `0.6.2`, and
that is the whole of it: there is **no `[0.6.2]` changelog heading, no tag, no GitHub release, no
built archive and no publication**, and the branch `feature/0.6.2-m4b-converter-upgrade` is **not
merged** — integration is the maintainer's decision. v0.6.0 Drops 1–3 (Plans 1–3) never carried a
version of their own and still do not; v0.6.1 was the first bump since v0.5.1 and v0.6.2 the
second. The wider v0.6.x initiative is **not** complete — four of the nine plans (6–9) remain
undrafted.

## High-Level State

All six tools are built, live-verified on Windows (v0.1.0 test matrix: 18/18 applicable rows
PASS; later releases re-verified their areas) **and on macOS (2026-07-08: full per-tool live
pass under the Finder shell — the `0.5.0-macos-component-verify` plan)**, and shipped through
GitHub Releases v0.1.0–v0.4.0.
v0.4.0 added Kokoro self-heal on every launch, the in-tree HF model cache, and the 5-voice
verification harness. v0.5.0 is a multi-drop line: Drop 1 (this restructure — no tool behaviour
changes), then metadata, TTS, script hardening, and UI drops.

**v0.6.2 (Plan 5 — M4B Converter upgrade) — COMPLETE, APPROVED and CLOSED on 2026-08-31; not
merged and not released.** The Converter became a full audiobook-conversion tool: whole-book or
**split-by-chapter** output over a **complete timeline** (nothing before the first chapter or after
the last is dropped), three metadata modes over one strict five-field allowlist, whole-book chapter
maps **with their titles** retained under Preserve and Replace, artwork copied rather than
re-encoded, **per-book folders** for split output, shared importer / job-control / destination /
reservation adoption, occurrence-identity duplicates, a fully frozen run including its
configuration, Pause/Resume/Cancel and Retry Failed, and success-only optional track numbering that
is **off by default**. Sources are never modified. `launcher.TOOLS` still holds exactly six tools.

**How Plan 5 was validated, and what it deliberately did not prove.** Phase 15 completed the
**Windows** manual matrix and Phase 16 the **macOS** one, both on the maintainer's real audiobook
corpus — twelve real M4Bs converted whole and split, with the resulting outputs mechanically
audited (durations, chapter maps, chapter titles, tag frames, artwork bytes, placement) rather than
eyeballed. Phase 16 accepted a small number of rows as **WAIVED / EVIDENCE GAP, not as PASS**: a
real xHE-AAC (USAC) source was not available on either platform, so neither the Windows Media
Foundation route nor the macOS `aac_at` route has a live end-to-end xHE decode behind it; the code
paths are covered by tests and by the refusal-rather-than-truncate contract only. Phase 17 was an
independent bug hunt using three fresh reviewer contexts that had not participated in the
implementation, with every reported finding mechanically confirmed before it was accepted and every
resulting regression proved load-bearing by mutation; it found and fixed six defects, including a
whole-book truncation that reported success, lost chapter titles, an ID3 version that Explorer
would not read, two occurrences collapsing into one folder, a panel permanently wedged by any
worker exception, and a run that followed live Preferences instead of its own frozen configuration.

**v0.6.0 Drop 1 (Windows UI prototype) — approved 2026-08-02, not released.** The Windows
design system, the converted launcher shell and the converted M4B Metadata Editor passed the
maintainer's visual gate against the ten-image evidence matrix under
`files/UI-Prototype-Screenshots/v0.6.0-drop1/` (1920×1080, maximized, true 100% and true 125%
Windows display scaling). **Approval is of the design contract, not a release:** `version.py`
is still `0.5.1`, no v0.6.0 exists, and the remaining five panels are unconverted. The eight
further v0.6.x plans are named in the sequencing note but undrafted; **Plan 2 is the next
implementation-planning target.**

**v0.6.0 Drop 2 (configuration, output, and application maintenance) — approved 2026-08-08,
not released.** Plan 2 delivered the committed root `config.toml` with per-key fallback and
once-per-launch warnings, Preferences & Data with the shared output base and Reset, the
`output_paths` reservation/collision/mirroring service adopted by all six tools, the two
confirmed destination exceptions, the four-asset downloaded-data inventory with post-exit
cleanup and rebuild, and `config.toml` in both release archives. Approved at Phase 8
`0e7ad0c264cb2a46f3c64f968e24f00963cb1987`; Phase 9 is the documentation/retirement commit, not
another feature phase.

**v0.6.1 (Plan 4 — TTS and Cover Image workflows) — COMPLETE, APPROVED, CLOSED and MERGED
through pull request #5 (merge `81c9c06`); not released.** The first plan to adopt Plans 2 and 3
inside production panels. It
delivered: the **unified PDF/TXT queue** in TTS Audiobook; the **retirement of EPUB** from every
production surface with its source preserved in the permanent tracked archive
`files/archived-code/epub-tts/`; the Cover **Details / List / Medium Thumbnail** browser;
**HEIC/HEIF capability detection** with decode and encode reported separately and **format
preserved rather than silently substituted**; the **Chatterbox** engine with its **four
maintainer-authorized voices** on **CPU-first** device selection and a truthful degraded path;
shared importer, output-service and job-control adoption in both panels; the one-explicit-encode
MP3 finalization contract; and the natural-boundary Chatterbox chunk planner. `launcher.TOOLS`
still holds exactly six tools.

**How Plan 4 was validated.** The **Windows manual matrix is complete and explicitly approved**
(HOME-PC, 1920×1080 at 100%, closed 2026-08-19). It ran in maintainer-authorized blocks and
produced five real defects, each root-caused before being fixed rather than patched around: a
silently truncated Chatterbox long-form synthesis (Kokoro's 3,000-character chunker was ten times
Turbo's supported input); an existing `.venv` skipping newly pinned requirements; a clipped
first-run setup dialog; a settings allowlist written with key names no writer in this repository
uses; and — the largest — **every TTS final MP3 encoded on ffmpeg's defaults at 32 kbps**, which
made players report exactly half the true duration. An uncontrolled multi-second silence in
Chatterbox long-form output was then root-caused to seventeen raw newlines reaching the model and
fixed by the natural-boundary planner, taking the worst interior gap from **8.73 s to 2.90 s**.
The maintainer listened to and approved the regenerated chapters.

**Live macOS validation was performed — it is a pass, not a deferral.** Phase 13 ran on an Apple
M4 Pro (`arm64`, macOS 26.5.2, native Python 3.12.13, not Rosetta) from the approved Phase 12
commit, and the official `.command` launcher built the environment unaided. It caught four
failures Windows could not: a real case-folding identity defect on case-insensitive APFS (fixed
with a seam that **asks the volume, never the platform**); `sanitize_relative` letting a
Windows-shaped path become a literal `C:` folder on POSIX; one shell-aware test defect; and the
Cover panel's primary action being unreachable under Aqua, fixed by converting one outer stack
from `pack` to `grid` with measured row weights. **Genuine HEIC passed 12/12** against a real
maintainer-supplied file — HEIC in, HEIC out, no `.jpg` anywhere, source SHA-256 unchanged. Kokoro
died with a native abort traced to espeak-ng's fixed 160-byte data-path buffer overflowing this
venv's 147-character path; the repository-owned `shared/espeak_data.py` seam links a short root at
the wheel's own data and does nothing at all where the path already fits. **All four Chatterbox
voices synthesized on real Metal** — every one of the 694,834,668 parameters on `mps:0`, 3.1–3.5 GB
of live Metal allocation, no CPU model ever built — and the maintainer listened to all four and
**approved all four on 2026-08-21**.

**Phase 14 (full regression and the approval gate) found and fixed a real production defect.**
`enable_mousewheel` took the shared root's single global `<MouseWheel>` slot on hover and gave it
back only on `<Leave>` — but the launcher's tool switch `pack_forget()`s a panel out from under
the pointer and closing one destroys it, and **neither fires `<Leave>`**. The stranded binding
scrolled the tool the user had just left and, once its widget was gone, fired at a Tcl command
that no longer existed on every wheel tick. Release is now also wired to `<Unmap>` and
`<Destroy>` and is **ownership-guarded**, so a stale region cannot steal the wheel from the region
the pointer is actually over. Phase 14 also closed a **testing** hole with no production
component: every live-Tk module turned a failed `tk.Tk()` into a skip, and one full-suite run
silently dropped forty-nine Chatterbox integration tests while still exiting zero. The
classification now lives once in `files/tests/tk_gate.py` and is made from the platform rather
than from the text of the error — **fail** where a windowing system is part of the platform,
**skip** only where a display is genuinely optional.

**Plan 4's deferrals, recorded as deferrals and not as passes.** The **Windows 125% scaling
matrix** was not run (it belongs to the later UI-compression phase, Plan 9) and Windows **DPI
awareness** is still unresolved. A credible **`.DS_Store`-into-release-packaging defect**, exposed
by the first Mac checkout, was root-caused and a narrow fix prototyped, then **deliberately left
uncommitted** — packaging is Plan 9's scope — so it **is not fixed**. A general **pronunciation
override** capability (global and per-voice) is a recorded future requirement and is **not
implemented**. Chatterbox narration timing is **frozen** for this release with a small amount of
residual pause accepted by ear. One native `pythonw.exe` / `torch_cpu.dll` `0xC0000005` access
violation is **historical, characterised from its minidump, and never reproduced in nine
controlled attempts or any later run — it is not claimed to be fixed**, and diagnostics were added
so a recurrence is observable.

**v0.6.0 Drop 3 (shared importing and job-control foundation) — approved 2026-08-10, MERGED
through pull request #4 (merge `809a43e`); not released.** Plan 3 delivered the four shared modules
described under Architecture —
`importing.py`, `import_coordination.py`, `job_control.py` and `job_ui.py` — plus 1,460 tests and
a developer-only manual harness. **It is infrastructure, not a feature a user can reach:** no
production panel or launcher imports any of it, `launcher.TOOLS` still holds exactly six tools,
and no tool's behaviour changed. The Windows manual matrix was run on HOME-PC by the maintainer
against generated disposable fixtures and **explicitly approved**; the automated gate at closeout
is **2,534 collected, 2,521 passed, 13 skipped, 1 pre-existing warning**, theme 17/17,
`verify.py` PASS, compile exit 0.

**What Plan 3's evidence does and does not cover.** The maintainer's attestation is the complete
manual result; the supplied screenshots visually support only a subset of it (harness startup,
fixture generation, a 50-file import, list clearing, a completed 1/1 job, the Summary milestones,
a 380-file repository import, an active 106/380 job at 28% with an ETA of `1m 36s`, per-occurrence
failure messages, and Pause/Cancel availability while running). Two gaps are recorded rather than
filled: **exact 100%-display-scaling confirmation was never independently recorded**, so the
functional Windows matrix is a pass while the true-100% claim is not asserted; and the harness's
literal source-tree before/after console line was not supplied, so repository verification stands
as corroborating evidence of source integrity rather than as the harness's own output. The
maintainer also imported the repository folder as a root (380 supported files) — **broader than
the plan's disposable-fixture-only preference and recorded as a test-scope deviation.** It mutated
nothing, and that is provable rather than asserted: importing is pinned to `scandir` and `lstat`,
the worktree stayed completely clean with no untracked file, `git diff HEAD` was empty, and every
tracked file and all 22 approved screenshots remained byte-identical. **Windows 125% scaling and
live macOS validation were not run for Plan 3 and remain deferred to Plan 9.**

**Plans 3 and 4 are now MERGED into `master`** — Plan 3 through pull request #4 (merge `809a43e`)
and Plan 4 through pull request #5 (merge `81c9c0600ca74a42a22bd09d367a702bee9708fe`, a normal merge
commit). Both feature branches were retained, not deleted. **v0.6.2 Plan 5 (M4B Converter upgrade)
is COMPLETE, APPROVED and CLOSED** as of 2026-08-31 on `feature/0.6.2-m4b-converter-upgrade`,
branched from that verified `master`; its temporary implementation drop has been retired, and its
lasting record lives here, in `Changelog.md`, `Decisions.md`, `Handoff.md` and the Master
Implementation Plan Index. That branch is **not merged**: integration review, pull request, merge,
tag, release and packaging are all still to be decided by the maintainer, and none of them has
happened. Code/version identity is now **`0.6.2`**, and the **published GitHub release remains
`v0.4.0`** — no tag, release or package exists for any of these plans. *(Superseded, kept as
history: this paragraph previously said Plan 5 was ACTIVE with Phase 0 complete and Phase 1 not
started and identity still at `0.6.1`; before that, that the next action was Plan 4 integration
review, that both branches were unmerged, and that Plan 5 had not been drafted or started. An
earlier sentence still further back described Plan 4 as the next unopened work, true until Plan 4
opened on 2026-08-11.)*

**How Plan 2 was validated, and what was deliberately not validated.** The evidence is a clean
extraction of the real Windows archive into a disposable root whose path carries a space, an
apostrophe and non-ASCII characters: the real `.bat` launcher detected the absent environment,
ran the full pinned install, launched the application, read `config.toml` from the extraction,
created runtime state only in its own `files/runtime-data/`, and used the healthy fast path on
the next launch with no console. A live **Edge TTS** synthesis produced a real 12.66 s MP3, and
all six tools' output routes, run numbering, mirroring, both destination exceptions, and the
post-exit cleanup plus `.venv` rebuild were exercised end to end. The Windows manual matrix
finished **46/46 PASS**, after a first pass of **44/46** that exposed two genuine defects —
both fixed before approval:

- **MP3 Combine failed on any path containing an apostrophe.** The ffmpeg concat list escaped
  `'` as `\'`, but inside single quotes ffmpeg treats every character literally, so the quote
  closed the token early and truncated the path. It now uses ffmpeg's documented
  close-escape-reopen form (`'` → `'\''`) and leaves backslashes alone. Spaces, Unicode,
  apostrophes and all three together are covered by tests that run the real binary.
- **An already-built panel kept showing the old output location** after a preference change.
  The shared display registry described above fixes it; the run was always correct, but the
  displayed destination now is too.

**Two validations are explicitly deferred, and neither is a pass.** **Live macOS was not
performed for Plan 2** — the aqua path is import- and build-tested only. **The Windows 125%
scaling/screenshot matrix was not performed**; Windows stayed at true 100% throughout, no
registry edit or DPI simulation was used, and by maintainer decision the true 125% pass belongs
to the later dedicated UI-compression/no-scroll phase, once the remaining features are in and
the layout is stable. Plan 2's screenshot evidence is the twelve-image 100% set under
`files/UI-Prototype-Screenshots/v0.6.0-drop2/`, plus the `920×600` reachability result; the ten
Plan 1 images are unchanged.

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
- **xHE-AAC decode is routed but unproven on real media.** ffmpeg's native AAC decoder cannot
  decode xHE-AAC (USAC) M4Bs. Since v0.6.2 the M4B Converter routes such a source through
  **Windows Media Foundation** on Windows, and macOS uses Apple's `aac_at`; where neither route
  can decode, the run reports it rather than writing a truncated book. Both routes remain
  **unverified end to end** — no real USAC audiobook has been available on either platform
  (macOS 2026-07-08, Windows and macOS again through Plan 5's Phases 15–16, 2026-08-31) — so this
  is an evidence gap, recorded as a waiver and never as a pass. The other five tools still use
  ffmpeg's native decoder and are unchanged.
- **Fresh one-click clean-machine install** (winget Python 3.12 + multi-GB torch + 300 MB
  model) is verified in pieces, not yet end-to-end on a virgin box.
- The `.bat` entry point briefly flashes its own cmd window on launch (the GUI itself never
  shows a console); eliminating it entirely would need a shortcut shim — deferred.

**Owner ground rules:** non-technical users are the audience; no visible consoles; every
dependency `==`-pinned; repo root stays minimal; upstream credit (GPL-3.0): epub2tts-edge
(Christopher Aedo), edge-tts, Kokoro-82M.
