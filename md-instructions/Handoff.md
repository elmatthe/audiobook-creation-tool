# Audiobook Creation Tool — Handoff

## Current Focus

**v0.6.1 Plan 4 (TTS and Cover Image upgrades) — ACTIVE. Phases 0–10 approved or implemented.**
Phases 0–7 approved (Phase 4 including its ETA-serialization remediation; Phase 6 approved
2026-08-15 in the prompt that authorized Phase 7; **Phase 7 including its reporting-order
remediation approved by the maintainer on 2026-08-15**, final SHA
`c368542af9c158652da9a94db7f58619fa4fb6af`). **Phase 8 was approved by the maintainer on
2026-08-15**, in the prompt that authorized Phase 9 — approved SHA
`ce6e62bcd4e0060786259c68f9d1c5c5b9c1c97b`. (Any earlier sentence in this file saying Phase 8
"awaits approval" is stale and superseded by this one.) **Phase 9 was approved by the maintainer on
2026-08-15** — they listened to all four evaluation WAVs and approved **all four**, with the GUI
labels set to the ASCII-hyphen form `Chatterbox - Female 1`. The response is recorded verbatim in
the Phase 10 entry. Approved Phase 9 SHA `2c63aa75521ae8e082d31923506aa6641ef0686f`.
**Phase 10 is implemented:** the four approved voices are registered (sixteen `VoiceEntry` rows,
the original twelve unchanged by value) and usable through the one unified PDF/TXT queue, behind a
truthful registered-vs-available distinction. **Phase 11 is NOT AUTHORIZED and has NOT started.**
One discovered consequence needs a decision in Phase 11: the dev-only `generate_voice_samples.py`
ordinary mode now routes the four Chatterbox rows to Edge TTS and exits 1 — see the Phase 10 entry.
The temporary drop
`md-instructions/0.6.1-tts-cover-workflows.md` is the authoritative
specification: sixteen phases (0–15), with Phase 5 retiring EPUB from production and archiving
its source, Phase 9 the four-output Chatterbox listening hard stop, and Phase 10 the approved-voice
registration into one unified PDF/TXT queue. Maintainer decisions 1A–7A are recorded in §7 of the
drop and are closed. `version.py` is `0.5.1` and stays there until approved Phase 15 closeout.

- **Approved baseline SHA:** `809a43e754920fce2f11f08e3c401dcc4c7a5223` (`master` = `origin/master`)
- **Branch:** `feature/0.6.1-tts-cover-workflows`
- **Baseline suite at Phase 0:** 2521 passed, 13 skipped, 1 warning (2534 collected);
  `verify.py` → `RESULT: PASS`; `compileall` exit 0.

### Local Chatterbox voice assets — read-only, local-only

Four maintainer-supplied recordings live in `files/Chatterbox-Voice-Uploads/`. Phase 0 added the
narrow ignore rule at `.gitignore:55`; all four are provably ignored.

| File | Bytes | SHA-256 |
|---|---|---|
| `Female-1.mp3` | 32,999,135 | `a047d77fe191c1a957d36b1e9f9af8e67756a63672686c55731b30534bb8bde2` |
| `Female-2.mp3` | 13,405,769 | `4bad0d3845199eae723aceb7a864b419fe553cd9d23799ee6390f54df08d3140` |
| `Male-1.mp3` | 2,946,239 | `6258dde294a91b0c2e965e8579aafde10e9cff48957c2138432be4c6c80165ae` |
| `Male-2.mp3` | 12,403,843 | `7b8fd74dfb262740476fba8317c0b7483a9f8b290e58c1d7e496e48b048d6ab2` |

Their only authorized provenance statement is: *maintainer-supplied local reference recording,
authorized by the maintainer for use by this local Chatterbox integration.* No copyright, consent,
redistribution or licence claim is made, and the speakers are not to be identified.

**Standing rules:**

- **Read-only inputs.** Never modified, renamed, moved, copied, trimmed, normalized or re-encoded
  in place. Derivatives and cached conditionals belong under `files/runtime-data/` (ignored).
- **Never staged, committed, pushed, packaged or released**, and never copied into `files/tests/`.
  `git add -f` is forbidden against them.
- **Local-asset portability boundary.** They exist only on this machine. Bundling or committing
  them, or any cached voice identity data, to make Chatterbox work elsewhere is **not authorized**
  and requires an explicit separate maintainer decision.
- **Missing assets must never break anything.** On a machine without the recordings, the
  application and every Edge and Kokoro voice still start and convert normally.
- **No Chatterbox voice may be offered unless its required local asset or cached conditional is
  truthfully available.** A voice whose asset is missing is shown unavailable with a
  setup-required status — never offered as a selection that then fails, never silently
  substituted, and never sourced from the internet.

### Phase 0 — Baseline, branch, and local-asset protection (2026-08-11, HOME-PC)

Pre-branch gates, all passed before the branch existed: `origin/master` fetched and still exactly
`809a43e`; no tracked modification; untracked paths exactly the drop plus the four MP3s, enumerated
explicitly rather than trusting the collapsed directory entry; no fifth file and no nested path
under `files/Chatterbox-Voice-Uploads/`; the four names, byte sizes and SHA-256 values matching the
drop exactly; the drop confirmed as the corrected sixteen-phase version; `VERSION` `0.5.1`;
`config-template.toml` absent from worktree, index and `origin/master` tree; `launcher.TOOLS`
exactly six entries; four canonical document names with exact casing and no alias; all 22 approved
Plan 1/2 screenshots byte-identical to `origin/master`.

Recorded for later phases: local `master` still has **no configured upstream** — noted, not
"fixed", as the drop requires. `batch_convert_child.py`, `prereq-workflows.md` and
`Vibe-Coding_Chat_Workflow.md` do not exist anywhere in this repository; verify every named symbol
against the tree before implementing it. The three no-adoption guards Plan 4 will narrow **by AST**
are `test_tool_output_integration.py::test_no_plan_three_importing_behaviour_arrived` (currently a
substring guard whose mechanism must be replaced),
`test_plan3_boundaries.py::test_no_production_module_imports_the_plan3_foundation` and
`::test_the_launcher_and_every_panel_still_names_nothing_from_plan3`.

Phase 0 changed only `.gitignore`, this document and the temporary drop. No production code, test,
requirement, launcher, packaging or version change; nothing merged, tagged, released or published;
no Mac action taken.

### Phase 1 — Centralized image-capability detection and the `pillow-heif` pin (2026-08-11, HOME-PC)

**Result: HEIC/HEIF is now a pinned, probed, separately-reported capability (Decisions 54A and
3A), and the Cover panel consumes it instead of owning a bare optional import.** Five files
changed — one new shared module, one new test module, `cover_resizer.py`, `scripts/requirements.txt`,
and the two documents assigned to this phase. No behaviour changed for JPG/JPEG/PNG, and none of
Phase 2's importer work was started.

**What was built.** `scripts/Universal/shared/image_capabilities.py` replaces the module-level
`try: import pillow_heif … except Exception: pass` that sat at `cover_resizer.py:53-59`. It
imports the plugin once, registers it once (the cached answer is what makes registration
exactly-once, under a lock so two workers cannot both register), and reports **decode and encode
independently** — a `libheif` build can read HEIC and be unable to write it. Encode capability is
proved by actually encoding a 1×1 image to memory, because `register_heif_opener()` registers a
saver whether or not an encoder exists behind it. The probe never raises; every failure becomes a
capability carrying a truthful reason. `resize_for_audiobook` now refuses a `.heic`/`.heif`
destination it cannot honour, with `UnsupportedImageFormat`, rather than silently writing a
`.jpg`; the pre-existing `.jpg` fallback for genuinely unknown extensions such as `.webp` is
unchanged. `REPLACEABLE_SUFFIXES` and `written_suffix()` are byte-for-byte unchanged. The import
dialog's filter now follows the probe rather than a hard-coded string. The reasoning for adding a
fifth `shared/` module is recorded as an ADR in `Decisions.md`.

**Dependency.** `pillow-heif==1.5.0` is now pinned in `scripts/requirements.txt`, replacing the
commented-out `1.3.0` suggestion. Verified against PyPI on 2026-08-11: 1.5.0 is current stable
(released 2026-07-22), `requires-python >=3.10`, `requires pillow>=11.1.0` (the project pins
`12.2.0`), with cp312 wheels for `win_amd64`, `macosx_11_0_arm64` and manylinux. **It was not
installed** — Phase 1 authorizes the pin, not an install — so this machine currently probes as
HEIC-unavailable, which is exactly the degraded path the tests cover. `verify.py`'s pinning check
and `release.py` needed no change, and `pillow_heif` was deliberately **not** added to
`bootstrap.REQUIRED_IMPORTS`: that list is what a machine must have, and adding it would make
optional HEIC support a startup requirement.

**Gates.** 2556 passed, 13 skipped, 1 warning (2569 collected) against the Phase 0 baseline of
2521/13/1 (2534 collected). The +35 is 34 new tests in `files/tests/test_image_capabilities.py`
plus one automatically generated case — `test_no_production_module_imports_the_plan3_foundation`
is parametrized over every production module, so the new shared module added a case, and it
passes. Skips and the single third-party `pydub`/`audioop` `DeprecationWarning` are unchanged.
`verify.py` → `RESULT: PASS`; `compileall` exit 0; `git diff --check` clean.

**Not proven here, and not claimed.** Every capability state is constructed through injected
probe seams, so nothing above is evidence that a real HEIC file decodes or encodes on any
machine. Real HEIC behaviour is Phase 12 on Windows and Phase 13 on Apple Silicon, and neither
substitutes for the other. No Mac action was taken.

**Next action: Phase 2 approval.**

### Phase 2 — Cover: shared importer adoption (2026-08-11, HOME-PC)

**Result: the Cover panel is the first production panel to adopt the Plan 3 foundation.** Its
own `self.files: list[Path]`, its `tk.Listbox`, its `add_files` / `remove_selected` /
`clear_list` / `update_count` and its independent `after(150, …)` loop are gone. Processing
still runs on the existing worker and queue, untouched.

**Composition adopted — nothing reimplemented.** The panel builds one `ImportedFileManager`
and one `ImportCoordinator`, hands both to one `job_ui.ImportAdapter`, and rides one
`MainThreadPump`. The adapter supplies Add Files, Add Folder, Move Up, Move Down, Remove,
Clear, the imported/selected counts, the per-type controls, include-hidden, allow-duplicates,
the live discovered count and the import cancel control. `validate_direct_files`,
`scan_roots`, `plan_transaction`, the broad-root warning and the captured large-result
threshold are all consumed, never re-created — proven by an AST guard that fails if the panel
defines any of those names itself.

**Catalog and the HEIC boundary.** `build_catalog()` always offers JPG/JPEG and PNG, and
offers HEIC/HEIF **only when Phase 1's centralized probe reports decode capability**. Decode
is the only question asked here: a decode-only machine may import a HEIC, and the output side
refuses separately at write time rather than substituting a JPEG (Decision 3A). No local
`pillow_heif` import or registration returned to the panel. Decision 16A holds — one control
per type, every offered type selected by default.

**The manager is the single source of truth.** Displayed order, selection, count, removal,
clearing and movement all come from it, and `imported_files()` reads its snapshot. A resize
captures that snapshot on the main thread and freezes a plain copy, so a later import moves
the manager and never a run that has already started. The worker still receives paths only.

**One pump.** `MainThreadPump` owns the panel's whole scheduled-callback chain; the import
poller rides its `schedule` seam and the processing worker's queue is registered as its single
drain. `self.after(` no longer appears in the panel at all. `close()` (also reached through
`destroy()`) closes the adapter and the pump, leaving nothing scheduled.

**The two cancellations stay separate.** `Cancel Import` reaches the coordinator only;
`Cancel` reaches the panel's own `_cancel_event` only. Locking inputs for a resize locks the
imported list and the import options as one unit and deliberately leaves the import status
bar alone, so a scan already running stays cancellable while a resize runs.

**Two no-adoption guards were narrowed, by AST, and not weakened.** Plan 3 proved the
foundation was adopted by nothing; Plan 4 makes that false for Cover. `ADOPTED` in
`test_plan3_boundaries.py` now excludes exactly `mp3_tools/cover_resizer.py` from
`test_no_production_module_imports_the_plan3_foundation` and
`test_the_launcher_and_every_panel_still_names_nothing_from_plan3`; every other module and
panel is held to the identical boundary. Two new guards keep that honest: one measures the
real set of importers against `ADOPTED` (so the list can neither grow silently nor be padded),
and one proves the adopting panel composes the services rather than defining its own. **The
plan assigns guard migration to Phase 11**; Phase 2 did the minimum the universal
full-suite gate forces, took only the Cover entry, and left the TTS entry and the substring
mechanism in `test_tool_output_integration` for Phase 11 as written.

**One pre-existing test needed updating.** `test_cover_declining_confirmation_starts_nothing`
seeded the panel with `ui.files = [src]`; with that attribute retired the panel saw an empty
list and opened a real modal warning dialog, which hung the suite. Both Cover sites now import
through the adapter's own dialog seam via a small `_import_into_cover` helper, so they
exercise the real shared direct-file path instead of reaching past it.

**Gates.** 2607 passed, 13 skipped, 1 warning (2620 collected) against the Phase 1 baseline of
2556/13/1 (2569 collected). The +51 is 51 new tests in `files/tests/test_cover_importing.py`,
plus 2 new guards, minus the 2 parametrized cases the Cover exclusion removes. Skips and the
single third-party `pydub`/`audioop` `DeprecationWarning` are unchanged. `verify.py` →
`RESULT: PASS`; `compileall` exit 0; `git diff --check` clean.

**Not started.** Phase 3's Details / List / Medium Thumbnail views, and Phase 4's
`JobController`, output planning and Retry Failed. No dependency was installed or changed —
`pillow-heif` is still pinned and still not installed locally, which is why the catalog on
this machine truthfully offers JPG/JPEG and PNG only.

**Next action: Phase 3 approval.**

### Phase 3 — Cover: Details / List / Medium Thumbnail browser (2026-08-12, HOME-PC)

**Result: Decision 17A's three views exist, default to Details, and are projections of the
Phase 2 manager rather than a second list.** Three files changed — one new test module,
`cover_resizer.py`, and one assertion in `test_cover_importing.py`. No new production module,
no dependency change, no `ACT.`-namespaced style, and no Phase 4 vocabulary anywhere.

**What was built.** `CoverBrowser` lives inside `cover_resizer.py` and composes three widgets:
a five-column `ttk.Treeview` for **Details** (filename, dimensions, format, file size, folder),
a one-column `ttk.Treeview` for **List** (full path), and a `tk.Canvas` tile grid for **Medium
Thumbnails**. All three sit on one raised page stack; switching between them is a `tkraise`
plus a re-read of `manager.snapshot()`, so **order and selection survive by construction, not
by being copied across**. Rows and tiles are keyed by occurrence id, so two deliberate
duplicates of one path stay two independently selectable items. Nothing in the class sorts,
filters or keeps a rival copy of the list — proved by AST.

**Selection.** Both Treeviews are built `selectmode="none"` and all three views route every
click and key through **one pure engine** (`resolve_selection` / `resolve_key`). That was a
deliberate choice over Tk's native `extended` mode: the canvas has no native selection at all,
so an engine was needed regardless, and using it everywhere gives the three views identical
semantics with **anchors and ranges in manager order** rather than widget order. `Button-1`
replaces, `Control-Button-1` and `Command-Button-1` toggle, `Shift-Button-1` extends, and
arrows / Shift-arrows / Home / End / Control-a / Command-a navigate. Worth recording: Tk
normalises binding names, so `bind()` reports `<Key-Up>` for `<Up>` and **`<Mod1-…>` for
`<Command-…>`** — Command-click really is registered separately from Control-click, and a test
that looks for the literal string it asked for will wrongly conclude it is missing.

**Following the manager without a second callback chain.** The shared `ImportAdapter` builds
its own `ImportedFileList` and exposes no selection-change hook, so rather than reaching into
its private slots the browser compares `manager.revision` and `manager.selection` against what
it last rendered, on the pump tick it already rides (`_sync_if_stale`). Every importer mutation
— Remove, Clear, Move Up, Move Down, a committed import — advances the revision, so this
catches all of them through the public contract. Selection made in the browser is pushed back
to the importer's rows so the two never disagree on screen.

**Thumbnails: lazy, visible-only, bounded.** `read_image_facts` and `encode_thumbnail` run on a
decoder thread and produce **plain data only** — a frozen `ImageFacts` and PNG bytes; the
`PhotoImage` is built on the main thread in `_accept`. Only the visible span is requested, and
`visible_span` **hard-caps** it at `MAX_VISIBLE_ITEMS` (60). That cap is the real guarantee, not
a nicety: an unmapped widget honestly answers "all of it" for its own extent, so without the
cap a 5,000-image import would decode 5,000 previews. `ThumbnailCache` is an LRU with an
explicit finite bound (`THUMBNAIL_CACHE_LIMIT` = 96 entries, deliberately a count and not a
byte budget so eviction is deterministic) and it is the **only owner** of a decoded image —
which is what makes eviction, `retain()` and `clear()` the whole lifetime story. Details and
List never ask for an image at all.

**Late results are inert.** A result is dropped if its occurrence was removed, if the manager
moved to a newer revision while it decoded, or if the browser closed. None is an error and
none loses anything: the next refresh asks again for whatever is still visible.

**A real defect this phase surfaced and fixed.** The first full run produced **16 warnings
against a baseline of 1** — `PytestUnraisableExceptionWarning: Variable.__del__ … main thread
is not in main loop`, scattered across a dozen unrelated test files. Cause: the new decoder
threads do enough allocation to trigger cyclic GC **on a worker thread**, and any Tk
`Variable.__del__` that runs off the main thread raises, because the tests never enter
`mainloop`. It is not specific to the objects the thread holds — it collects whatever Tk
garbage happens to be pending. The fix is `CoverBrowser.close()` joining its outstanding
decoder batches within a bounded `WORKER_JOIN_TIMEOUT`, mirroring how the import coordinator
joins its own worker; batches are capped at 60 items so the wait is short and finite. That took
the count back to the inherited 1. **Any future phase that adds a background thread to a Tk
panel should expect this class of warning and join, not suppress.**

**Gates.** 2698 passed, 13 skipped, 1 warning (2711 collected) against the Phase 2 baseline of
2607/13/1 (2620 collected). The **+91 is exactly the 91 new tests** in
`files/tests/test_cover_browser.py`; no parametrized case was added or removed, because the
browser is a class inside the existing panel rather than a new production module. Skips are the
same 13 environmental ones (symlink privilege WinError 1314, case-insensitive filesystem,
`JACK_RYAN_M4B_FOLDER` unset) and the single warning is still the third-party `pydub`/`audioop`
`DeprecationWarning`. `verify.py` → `RESULT: PASS`; `compileall` exit 0; `git diff --check` on
`'*.py'` exit 0.

**One existing test changed, and why.** `test_exactly_one_pump_owns_the_panels_scheduled_callbacks`
asserted `drain_count == 1`. The browser registers its preview drain on the *same* pump, so the
count is now 2. Only that number and its comment moved — the two assertions that actually
enforce the one-pump design (`"self.after(" not in source` and `source.count("MainThreadPump(")
== 1`) are byte-identical and still pass, and a new test names both drains explicitly.

**One production shape chosen to keep an existing guard untouched.**
`test_cover_source_side.py::test_focus_is_set_on_cancel_and_never_on_the_destructive_button`
scans the whole module for `<Name>.focus_set()` and expects only `btn_cancel`. Giving the
clicked view keyboard focus is legitimate and unrelated to the replacement dialog, so it is
written as `self.surface(self._view).focus_set()` — which is also the more natural expression
— and the guard stays exactly as written. Same precedent as Phase 2's comment reword.

**Preserved and re-proved.** The manager is still the single imported-file source; `self.files`
and `self.listbox` are still absent; the processing worker still reads no Tk variable and no
widget (now also asserted for `browser` and `cache`); `Cancel Import` and the processing cancel
are still separate objects; the old worker, its queue protocol and all three output modes are
untouched. `disable_inputs` now locks the browser's selection with the rest, while leaving the
**view switch** available — looking at the queue mutates nothing, so blinding the user during a
run would buy no safety. The importer's own list height dropped from 12 rows to 6 so both
components fit the supported minimum; nothing else about it changed.

**Not started.** Phase 4's `JobController`, `JobAdapter`, output planning and Retry Failed. No
dependency was installed or changed. **Installation validation is not applicable in Phase 3** —
no dependency or setup change — so no `pip install`, no `pillow-heif` install, no
`requirements.txt`/bootstrap/launcher edit, and neither root launcher was run. No Mac action.

**Next action: Phase 4 approval.** *(Given 2026-08-13; see below.)*

### Phase 4 — Cover: job-control, output and Retry Failed adoption (2026-08-13, HOME-PC)

**Result: Cover's *run* now belongs to the shared Plan 3 foundation, and its output plan to
Plan 2's three planners, with every clause of §4.2 still proven by test.** Five files changed —
one new test module, `cover_resizer.py`, and one migrated guard in each of three existing test
modules. No new production module, no dependency change, no `ACT.`-namespaced style, and no
Phase-5-or-later vocabulary anywhere.

**Composition adopted — nothing reimplemented.** `capture_run` freezes one run; a
`JobController` owns its cooperative pause/resume/cancel; a `JobReporter` mints every event from
a controller snapshot; a `JobAdapter` (with its `JobControlBar`, `JobStatusView`,
`SummaryDetailsView`, `LockGroup` and `EtaEstimator`) renders the whole stream; `RunResult.settle`
and `.retry()` are the only retry vocabulary. An AST guard fails if the panel *defines* any of
those names.

**One run, frozen once.** `start_resize` captures the manager snapshot, the catalog, the import
options, the effective configuration and `{size, letterbox, mode}` in one `capture_run` call on
the main thread, then never consults them again. Occurrence id is the item identity end to end —
plan, worker, event stream, outcome and retry — so two deliberate duplicates of one path stay two
items with two destinations and two retry entries.

**Output planning.** `plan_destinations()` uses `planning_groups()` as the *only* bridge:
individually chosen files go through `plan_flat` (Decision 31A), a single folder root through
`plan_mirrored` (7A), several roots through `plan_multi_root` (41A) — all sharing one
`DestinationPlanner`, so a flat file and a mirrored file can never be planned onto the same path.
Destinations are planned under `written_name()`, the name the writer will *actually* produce, and
the whole map is computed before the worker exists. That is what makes a retried item land where
it would originally have landed and makes it impossible for it to take a name an earlier success
already occupies. The two source-side modes plan per item at write time, exactly as before, and
reserve no run directory.

Occurrence ids are walked in parallel with `planning_groups`' own rule and then **cross-checked
element by element** against the returned paths, raising `UnsafePathError` rather than allowing a
silent mismatch. That check is why a second grouping cannot quietly drift into existence.

**The destructive contract.** Unchanged, and now reachable from two callers instead of one:
`_gate_replacement()` validates every source and then asks the one confirmation, and both a first
run and a retry go through it — which is how `self.confirm_replacement(` still appears exactly
once in the module and how a retry can never inherit an earlier answer. A declined confirmation
still creates no run directory, no temporary file and no output, and now also no accepted run.

**Pause, resume, cancel.** `controller.checkpoint()` is called once, at the top of the single
per-image loop, before `resize_for_audiobook` — so a pause asked for mid-resize records
"Pause requested" and takes effect at the next boundary, a paused run holds no half-written
output, and resume redoes nothing. `cancel()` sets the panel's own `_cancel_event` **and** asks
the controller, which wakes a worker already waiting at a paused checkpoint; the worker
acknowledges at that checkpoint and only then may the run be settled as cancelled. A completed
replacement is never rolled back and the log still says so. `Cancel Import` still reaches the
coordinator only.

**One pump, three drains.** The import poller rides the pump's `schedule` seam; the processing
queue, the browser's previews and the job adapter are its three drains. `self.after(` still does
not appear in the panel and `MainThreadPump(` still appears once. The adapter is rebuilt per run
— one run owns one event stream and one estimate, and neither can be rebound — and closing the
retired one is what drops its drain, so the count stays three however many runs a session
performs. Both the Phase 2 and Phase 3 one-pump guards now **name** the three drains rather than
counting them.

**Close safety.** `close()` asks the controller to stop *before* joining, so closing a paused run
finds a thread already unwinding rather than one that will never be woken; the join is bounded by
the same `WORKER_JOIN_TIMEOUT` the browser uses.

**A real defect this phase surfaced and fixed.** The first full run produced **2 warnings against
a baseline of 1** — the same `PytestUnraisableExceptionWarning: Variable.__del__ … main thread is
not in main loop` class Phase 3 hit, surfacing in an unrelated file. Cause: the shared job widgets
bring Tk variables that survive `destroy` inside reference cycles, so they are freed by the
*cyclic* collector, which runs on whichever thread crosses its threshold. `destroy()` now
finishes its own teardown with an explicit `gc.collect()` after `super().destroy()`, on the thread
that owns the widgets. Bisected by running the full suite without the new test module — still 2
warnings — which proved it was the production change and not the tests. **The warning is fixed,
never suppressed**, and a regression test asserts both the mechanism and the absence of any
warning filter in the panel.

**Gates.** 2790 passed, 13 skipped, 1 warning (2803 collected) against the Phase 3 baseline of
2698/13/1 (2711 collected). The **+92 is exactly the 92 new tests** in
`files/tests/test_cover_jobs.py`; no parametrized case moved, because Phase 4 added no production
module. `verify.py` → `RESULT: PASS`; `compileall` exit 0; `git diff --check` on `'*.py'` exit 0.
The race-sensitive subset was re-run 6 consecutive times and the five concurrency-heavy modules 5
consecutive times, all green.

The 13 skips are the same environmental ones, by node id: `test_cover_source_side.py::
test_replacement_refuses_a_linked_source`, `test_import_manager.py::
{test_a_file_symlink_supplied_as_a_file_is_refused, test_case_only_names_on_a_case_sensitive_filesystem_stay_distinct}`,
`test_import_traversal.py::{test_is_link_says_yes_to_a_file_symlink,
test_is_link_says_yes_to_a_directory_symlink, test_names_differing_only_in_case_are_both_collected,
test_a_file_symlink_inside_a_scanned_folder_is_refused,
test_a_directory_symlink_inside_a_scanned_folder_is_refused,
test_a_root_that_is_a_symlink_is_refused}`, `test_jack_ryan_final_product.py::
{test_folder_has_m4bs, test_finished_product_invariants[NOTSET],
test_series_is_consistent_across_the_set}` and `test_output_paths.py::
test_a_linked_destination_name_is_refused` — **eight** for symlink privilege (WinError 1314), two
for a case-insensitive filesystem, three for `JACK_RYAN_M4B_FOLDER` being unset. (Phase 3's
abbreviated categories summed to 12 and this entry first said nine, which sums to 14; the
node-by-node list above is the real thirteen and 8 + 2 + 3 is its real grouping. Corrected during
the Phase 4 remediation below — no skip changed, only the arithmetic describing it.) The single
warning is still the third-party `pydub`/`audioop` `DeprecationWarning`.

**Four existing tests changed, and why.** Each is a phase-ordering marker that Phase 4 is the
phase to retire, or a mechanism made *more* precise — none is weakened:

1. `test_cover_importing.py::test_the_processing_worker_and_its_queue_protocol_are_unchanged` —
   the "kept" half is byte-identical; the half that asserted Phase 4 had not started now names
   Phase-5-and-later vocabulary instead.
2. `test_cover_browser.py::test_no_phase_four_vocabulary_entered_the_panel` — same marker, same
   migration, renamed to `…no_phase_five_vocabulary…`.
3. The worker's "reads no Tk variable and no widget" guard, in both modules — narrowed from *any*
   attribute anywhere in the body to a **whitelist of the attributes it reaches on `self`**
   (`_log_q` and `_cancel_event`, exactly). Strictly stronger, and no longer confusable with a
   shared reporting call that happens to share a widget's name.
4. `test_prototype_regression.py::test_building_the_whole_app_leaves_the_generic_styles_untouched`
   — the values are now compared through one canonical spelling. Tcl answers
   `{'tabmargins': '2 2 2 0'}` before any notebook has existed in the interpreter and
   `{'tabmargins': [2, 2, 2, 0]}` afterwards: identical padding, two encodings. Cover is the first
   panel to instantiate a `ttk.Notebook` (through the shared Summary/Details view), so the guard
   reported a "leak" that was a property of lazy Tcl conversion. A real change of colour, layout
   or state map still differs.

**Two presentation decisions.** The panel's own `Cancel` button is retired in favour of the shared
control bar's Pause / Resume / Cancel and the retry control; `Resize Covers` remains the panel's
own Start. `self.progress` is now an alias of the shared status view's indicator, so there is
exactly one progress model and nothing can draw a second, disagreeing bar. The Log pane is kept
(it is the raw transcript, distinct from the shared Summary and Details projections) and shrunk
from 8 rows to 4 so the whole panel still fits the supported minimum.

**Preserved and re-proved.** The manager is still the single imported-file source; `self.files`
and `self.listbox` are still absent; the three browser views, their default and their selection
semantics are untouched; `Cancel Import` stays usable while a run's inputs are locked; the catalog
still follows Phase 1's probe; `REPLACEABLE_SUFFIXES` and `written_suffix()` are byte-identical;
and `resize_worker` still runs a plain, unreported batch when handed the legacy parameter dict,
which is what keeps `test_cover_source_side.py` passing unmodified.

**Not started.** Phase 5's EPUB retirement and reference archival. No dependency was installed or
changed. **Installation validation is not applicable in Phase 4** — no dependency or setup change
— so no `pip install`, no `pillow-heif` install, no `requirements.txt`/bootstrap/launcher edit,
and neither root launcher was run. No Mac action.

**Next action: Phase 4 approval.**

### Phase 4 remediation — Cover ETA sampling serialized through the queue (2026-08-14, HOME-PC)

**Raised in review, and correctly.** The Phase 4 report disclosed, as a "deliberate trade-off",
that one `EtaEstimator` was written by the worker (`begin`/`complete`/`discard`) while the
main-thread `JobAdapter` read and mutated the same object (`observe` → `note_state`, `display`,
`estimate`). That was not a trade-off to accept. Three things were wrong with it:

1. `EtaEstimator` is compound mutable state — a `deque`, a category, an open-unit timestamp, a
   pause accumulator and a terminal flag — with no synchronization of any kind.
2. `estimate()` sums `_samples` while the worker may be appending to it. That can raise, not
   merely return a slightly stale mean, so the report's "worst case is one imprecise sample" was
   simply wrong.
3. Plan 4 §5.5 says workers communicate **only** through the queue the main-thread pump drains.
   One mutable object shared across the two threads violates that boundary whatever the observed
   failure rate is.

**The fix: the worker sends a number, not an object.** `resize_worker` no longer receives an
estimator at all — it is not in `params`, and the worker names neither the class nor any of its
methods (asserted by AST). Instead it reads the run's injected clock once before an image and once
at the top of that image's `finally`, and on success puts a frozen
`TimingSample(run_id, attempt, category, duration)` on the **existing** `_log_q`. The main thread's
existing `_drain_worker_queue` consumes it and calls `_record_timing`, the single place any
estimator is ever mutated. No new queue, no new drain, no `after` chain: still exactly one
`MainThreadPump` with the same three drains.

**Real work, not queue latency.** The measurement brackets one image's own work — planning its
destination, writing it, and for a replacement validating and installing it — and closes before
the message is queued. Proven rather than asserted: the tests use a clock that moves *only* inside
`resize_for_audiobook`, so a recorded sample equals exactly the time attributed to the image;
a companion test advances that clock by 500s while the message sits in the queue and the recorded
sample is still `0.0`.

**Main-thread-only, proven at runtime.** A recording subclass of the shared estimator captures
`threading.get_ident()` on every one of its public operations. Across a real two-thread run every
recorded call is the main thread, `record` is among them, and `begin`/`complete`/`discard` are
never called at all — while the same test confirms the work genuinely ran off the main thread.

**Fencing.** A sample is dropped inertly when the panel has closed, when its `run_id` is not the
current estimator's, or when its `attempt` is not the attempt now running. The attempt counter is
load-bearing rather than belt-and-braces: **a retry re-runs the same frozen snapshot and therefore
carries the same run id**, so the run id alone cannot tell a first attempt's leftover sample from
the retry's own. A retry still gets a brand-new estimator and inherits no sample.

**One narrow additive shared change, as authorized.** `EtaEstimator` had no public way to accept
an already-measured duration — `begin`/`complete` are inseparable from the estimator's own clock,
which is precisely what forces the cross-thread sharing. `shared/job_control.py` therefore gains
`EtaEstimator.record(category, duration)`: it clears history on a changed category exactly as
`begin` does, keeps the bounded window, the three-sample minimum and `Calculating…` untouched,
returns `None` without recording for a non-finite or negative duration exactly as `complete` does,
raises `JobContractError` for a non-number, a blank category, or a call made while a unit is open,
and **reads no clock at all**. No `JobEventKind`, `JobEvent` field, `RunSnapshot` field, controller
transition, retry vocabulary or output descriptor changed — asserted by test. A pre-existing §6.13
guard said every sample enters through `complete()`; it now names both sanctioned entry points and
additionally proves `record` touches no clock, so it is stricter about the new one than the old
wording was about anything.

**Files changed.** `scripts/Universal/shared/job_control.py` (+44), `mp3_tools/cover_resizer.py`
(+~85/−~20), `files/tests/test_job_events_eta.py` (+~150, 21 new tests),
`files/tests/test_cover_jobs.py` (+~490/−~30, 16 net new tests), and this document.

**A test-harness defect fixed on the way.** The Phase 4 `Gate` used two bare `Event`s, so two
consecutive releases could be collapsed into one and a worker could block forever. It is now a
counted barrier on a `Condition` — each image takes a ticket and waits for that ticket — and the
cancel-during-an-image tests now request cancellation *before* releasing the image, so which
checkpoint stops the run is decided rather than raced. Still no sleeps anywhere.

**Gates.** 2827 passed, 13 skipped, 1 warning (2840 collected) against the Phase 4 baseline of
2790/13/1 (2803 collected). The **+37 is exactly 21 new estimator tests + 16 net new Cover tests**
(`test_job_events_eta.py` 258 → 279, `test_cover_jobs.py` 92 → 108); no parametrized case moved,
because no production module was added. `verify.py` → `RESULT: PASS`; `compileall` exit 0;
`git diff --check` on `'*.py'` exit 0. The race-and-ETA subset was re-run 7 consecutive times and
the six concurrency-heavy modules 5 consecutive times, all green.

**Skips, with the corrected grouping: 8 + 2 + 3 = 13.** Eight symlink-privilege (WinError 1314):
`test_cover_source_side::test_replacement_refuses_a_linked_source`,
`test_import_manager::test_a_file_symlink_supplied_as_a_file_is_refused`,
`test_import_traversal::{test_is_link_says_yes_to_a_file_symlink,
test_is_link_says_yes_to_a_directory_symlink, test_a_file_symlink_inside_a_scanned_folder_is_refused,
test_a_directory_symlink_inside_a_scanned_folder_is_refused, test_a_root_that_is_a_symlink_is_refused}`,
`test_output_paths::test_a_linked_destination_name_is_refused`. Two case-insensitive filesystem:
`test_import_manager::test_case_only_names_on_a_case_sensitive_filesystem_stay_distinct`,
`test_import_traversal::test_names_differing_only_in_case_are_both_collected`. Three
`JACK_RYAN_M4B_FOLDER` unset: `test_jack_ryan_final_product::{test_folder_has_m4bs,
test_finished_product_invariants[NOTSET], test_series_is_consistent_across_the_set}`. No skip was
changed; only the arithmetic describing them was wrong, and it is corrected above. The one warning
is still the third-party `pydub`/`audioop` `DeprecationWarning`.

**Preserved.** Every approved Phase 4 behaviour is unchanged and still proven: one frozen
`RunSnapshot` and stable occurrence identity; the manager as the sole imported-file authority;
flat / mirrored / multi-root planning; the numbered-copy `SourceSidePlanner`; all four replacement
gates and the atomic install; the retry built only from `RunResult.retry()`; successful outputs
never overwritten; deliberate duplicates distinct; the checkpoint only between images; cancel
waking a pause and never rolling back a completed replacement; Summary free of diagnostics;
truthful progress; `LockGroup`/matrix locking; one pump with the same three drains; `Cancel Import`
separate from processing cancellation; the three browser views; bounded browser workers and close
cleanup. The owner-thread `gc.collect()` in `destroy()` is retained unchanged, its focused
regression test is green, and no warning filter or `RuntimeError` suppression exists anywhere.

**Installation validation: not applicable to this remediation** — no dependency or setup change.
No `pip install`, no requirements/bootstrap/launcher edit, no `.venv` rebuild, neither root
launcher run. No Mac action.

**Phase 5 (EPUB production retirement and reference archival) is still not started.**

**Next action: Phase 4 approval.** *(Given 2026-08-14; see below.)*

### Phase 5 — EPUB production retirement and reference archival (2026-08-14, HOME-PC)

**Result: EPUB is gone from every active production surface, its tracked source is preserved in
a permanent, provably inert archive, and the shared Edge/PDF/TXT synthesis engine survived
untouched.** Entry SHA `3d9de97e7befc27fa22210bdcc27f174aa594883`. Nine files changed, five
added; **no production module was added, removed or renamed**, which is why the collected-test
delta is exactly the new guard module and nothing else.

**This was a disentangling job.** The fresh `rg` inventory confirmed §4.4.1's warning in full:
`epub2tts_edge/` *is* the Edge synthesis engine for PDF and TXT, and only four of its twenty-four
functions were EPUB-specific.

#### The five-category inventory (re-derived, not trusted)

1. **EPUB-exclusive.** `epub2tts_edge.py` — `chap2text_epub`, `get_epub_cover`, `export`,
   `check_for_file`, the `namespaces` dict, the `ebooklib.epub` warning filter, the imports
   `bs4.BeautifulSoup` / `ebooklib` / `ebooklib.epub` / `lxml.etree` / `PIL.Image` / `zipfile` /
   `warnings`, and `main()`'s `--epub-convert` flag, `.epub` early exit and help string.
   `runner.py` — the `epub_mod` import, the `export` import, the `epub_convert` parameter, the
   `".epub"` suffix member, the `epub_convert=True` guard and the extraction branch.
   `epub2tts_gui.py` — the `epub_mod` and `export` imports, `epub_convert_var`, the option
   checkbox, `epub_export_only`, the hoisted `epub_convert` copy, the Edge export-only branch, the
   Kokoro `.epub` branch, the `run_conversion_job` kwarg, the `*.epub` dialog filter and two
   labels. **`check_for_file` was not EPUB-specific in itself** — `export` was simply its only
   caller anywhere in the tree, so it was orphaned by the retirement rather than left as dead
   interactive `input()` code in a GUI app. It is preserved in the archive.
2. **Shared PDF/TXT/Edge infrastructure — untouched.** `read_book`, `run_edgespeak`,
   `parallel_edgespeak`, `run_save`, `intra_sentence_chunks`, `_merge_nonspeakable_intra_chunks`,
   `trim_silence_segment`, `trim_tts_chunk_file`, `append_silence`, `_export_audio`, `get_book`,
   `generate_metadata`, `get_duration`, `make_m4b`, `make_mp3`, `add_cover`, `ensure_punkt`,
   `_run_ffmpeg`, `_ensure_shared_on_path`, `_SPEAKABLE` and **every** timing constant;
   `runner.py`'s `_normalize_for_match`, `_ensure_pdf_txt_has_chapter_heading` and the whole
   PDF/TXT body of `run_conversion_job`. **`pdf_extractor.py`, `batch_convert.py`,
   `kokoro_synth.py`, `voice_registry.py` and `generate_voice_samples.py` contain no EPUB code at
   all** — the only matches are stale *upstream-project-name* docstring mentions. Zero edits to
   all five.
3. **Mixed-purpose.** Exactly the three §4.4.1 names, disentangled in place, never archived
   wholesale.
4. **Historical / test / reference.** No test file was EPUB-exclusive, so **nothing under
   `files/tests/` was archived and no test was deleted**. `test_importing.py:284` (which asserts
   `.epub` is *not* baked into the shared layer), `test_importing.py:600`, `test_job_control.py:416`
   and `test_job_ui.py:851-854` (which use `"epub"` as an arbitrary *unknown* type id) are kept
   verbatim — none is a TTS support expectation. Exactly **one** stale expectation was found and
   retargeted: `test_tool_output_integration.py::test_tts_flat_single_file_lands_in_the_run_root`
   planned a fixture named `novel.epub`; it now plans `novel.pdf`, preserving the identical
   flat-placement coverage. `files/release-history/`, `Changelog.md`, `Decisions.md` and
   `don't-delete/` are preserved history and are explicitly outside every guard's scope.
5. **Dependency / bootstrap / launcher / docs / packaging.** `requirements.txt` ×3 pins,
   `bootstrap._PIP_NAME` and `REQUIRED_IMPORTS`, `launcher.TOOLS[0].description`,
   `tts/__init__.py`, `README.md`. `verify.py` and `release.py` needed no change.
   `files/Dockerfile` was assessed and **left alone**: it is a dev-only asset outside `scripts/`,
   it entry-points the *surviving* Edge engine rather than anything EPUB, and it is already
   non-functional as committed (`COPY epub2tts_edge/… setup.py` — no `setup.py` exists and the
   paths are not relative to `files/`).

#### Rename decision: **A — names kept, boundary documented**

`epub2tts_gui` / `epub2tts_edge` survive. A complete rename would have had to move atomically
across the launcher module path, `bootstrap.LAUNCHER_FALLBACK`, `tts/__init__.py`, **nine** test
modules holding those paths as literal strings, `files/Dockerfile` and `README.md` — while Phases
6 and 7 restructure that same panel. Renaming now and restructuring next doubles the churn exactly
where the drop's half-rename risk lives, and the names carry the GPL-3.0 provenance. The boundary
is written down in three places: the panel's module docstring, `README.md`'s `scripts/tts` bullet,
and a dedicated section of the archive manifest. A guard asserts the manifest says so.

#### The archive

`files/archived-code/epub-tts/` — tracked, permanent, **not deleted with the drop at closeout**.
Every byte came from `git show 3d9de97:…`, never from the working directory.

| Archived file | Original path | Preserves |
|---|---|---|
| `epub2tts_edge_epub_functions.py` | `scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py` | `namespaces`, `chap2text_epub`, `get_epub_cover`, `export`, `check_for_file`, the CLI fragments |
| `runner_epub_dispatch.py` | `scripts/Universal/tts/epub2tts_edge/runner.py` | the `.epub` guard and extraction branch, the removed import/parameter/suffix |
| `epub2tts_gui_epub_surfaces.py` | `scripts/Universal/tts/epub2tts_gui.py` | the checkbox, the pause-skip, both worker branches, the dialog filter, both labels |
| `README.md` | — | the manifest: per-file original path, archive path, purpose, source SHA, retirement reason, retained production counterpart, licence, and restoration guidance |

**Inertness, proved rather than asserted.** `files/archived-code/` was re-verified as **not
ignored** (`git check-ignore` exit 1) so **no `.gitignore` change was needed** — the negation-rule
risk never arose. `release.py` walks `ROOT_FILES` + one entry launcher + `scripts/` only, so its
built file list (45 members, enumerated without building a release) contains no `files/` path at
all. The suite is invoked as `pytest files/tests`, so the archive is uncollectable by path; a guard
additionally proves no archived file matches any default collection pattern. Further guards prove:
the archive is outside `scripts/`; no production module names it in an executable string or
imports it; no `sys.path` entry and no loaded module resolves inside it; it contains only `.py`
and `.md`; it has no `__init__.py`, `conftest.py`, `setup.py`, `pyproject.toml` or `sitecustomize`;
and **no archived module executes anything on import** (no top-level `if`, no top-level call).
It holds no media, no book fixture and no untracked file.

#### Dependency evidence (§4.7), package by package

| Package | Consumers enumerated by search | Classification | Reverse-deps in the venv | Decision |
|---|---|---|---|---|
| `ebooklib==0.20` | `epub2tts_edge.py:15,16,60,174`; `runner.py:13`; `epub2tts_gui.py:35`; `bootstrap.REQUIRED_IMPORTS` | all EPUB-only | **none** | **removed** |
| `beautifulsoup4==4.14.3` | `epub2tts_edge.py:14→102`, inside `chap2text_epub` only; `bootstrap._PIP_NAME` + `REQUIRED_IMPORTS` | single EPUB-only consumer | only optional extras (`transformers[dev/testing]`, `lxml[htmlsoup]`) | **removed** |
| `lxml==6.1.1` | `epub2tts_edge.py:18→130,134`, inside `get_epub_cover` only | EPUB-only | `EbookLib→lxml` (itself removed), `beautifulsoup4[lxml]` extra, `networkx[extra]` — **no non-extra requirer among retained pins** | **removed** |

Read from installed distribution metadata, not from memory, and re-asserted by a test that walks
`importlib.metadata` and fails if any *retained* pin declares a bare (non-extra) requirement on one
of the three. `bootstrap.REQUIRED_IMPORTS` is now
`["edge_tts", "pydub", "fitz", "mutagen", "PIL", "nltk"]` and `_PIP_NAME` lost its `bs4` alias — a
removed package still listed there would break a clean install. **Every retained pin is
byte-identical**, including `pillow-heif==1.5.0`, `kokoro==0.9.4 ; python_version < "3.13"` and
`audioop-lts==0.2.2 ; python_version >= "3.13"`. Nothing was upgraded, downgraded or reordered.
The three removed pins are recorded verbatim in a `requirements.txt` comment and in the manifest so
restoration is mechanical.

#### Licence and attribution — intact, and now guarded

`README.md`'s **License** section and the **Christopher Aedo / aedocw/epub2tts-edge** credit are
byte-identical, and three new tests pin their exact wording. The surviving Edge engine is the same
upstream derivation, so the obligation lives in production as well as in the archive; a fourth test
asserts `generate_metadata` still writes the upstream URL into every M4B. **One** credit line
changed: `ebooklib` was dropped from the "Also gratefully relying on" list, because the project no
longer relies on it. That is a dependency acknowledgement, not the protected upstream attribution.

#### Tests

**Added:** `files/tests/test_epub_retirement.py` — **101 tests**, all AST- or metadata-driven, with
an explicit production allow-list rather than a repository-wide substring ban. A meta-guard proves
the allow-list equals the real set of production TTS modules on disk, so it can neither go stale nor
be padded to hide one. Docstrings are excluded deliberately (describing the retirement is not
offering it), and `.epub` is matched as a *file extension* (`\.epub(?![A-Za-z0-9_])`) so
`tts.epub2tts_edge` cannot trip it. Coverage: PDF/TXT are the only accepted types; `.epub` cannot
enter through dialogs, extension sets, mode controls, validation, folder traversal, stale persisted
state, dispatch, retry or a direct internal call; no UI label, launcher description or CLI help
offers it; Edge and Kokoro PDF/TXT paths are behaviourally unchanged; every timing, retry and voice
default holds; the run directory is still reserved only after validation; the archive is inert and
unpackaged; the manifest is accurate; licence and attribution survive; and the dependency contract
holds both ways. **An import-blocking seam** poisons `sys.modules` with a sentinel that raises on
attribute access and re-imports the engine and runner, so a lingering EPUB import fails loudly
instead of passing because the package happens to still be installed in this venv.

**Removed / weakened: none.** No test was deleted, skipped, xfailed or weakened. One fixture
filename changed, as described above.

**Collection reconciliation.** 2941 collected (2928 passed, 13 skipped) against the Phase-4
remediation baseline of 2840 collected (2827 passed, 13 skipped). **+101 = exactly the 101 tests in
`test_epub_retirement.py`.** No test was deleted (0), none was moved or archived (0), and no
parametrized case moved (0) — `test_no_production_module_imports_the_plan3_foundation` is
parametrized over production modules and Phase 5 added and removed none, only editing existing
files. Nothing is unexplained.

**Skips: the same 13, 8 + 2 + 3.** Eight symlink-privilege (WinError 1314):
`test_cover_source_side::test_replacement_refuses_a_linked_source`,
`test_import_manager::test_a_file_symlink_supplied_as_a_file_is_refused`,
`test_import_traversal::{test_is_link_says_yes_to_a_file_symlink, test_is_link_says_yes_to_a_directory_symlink,
test_a_file_symlink_inside_a_scanned_folder_is_refused, test_a_directory_symlink_inside_a_scanned_folder_is_refused,
test_a_root_that_is_a_symlink_is_refused}`, `test_output_paths::test_a_linked_destination_name_is_refused`.
Two case-insensitive filesystem: `test_import_manager::test_case_only_names_on_a_case_sensitive_filesystem_stay_distinct`,
`test_import_traversal::test_names_differing_only_in_case_are_both_collected`. Three
`JACK_RYAN_M4B_FOLDER` unset: `test_jack_ryan_final_product::{test_folder_has_m4bs,
test_finished_product_invariants[NOTSET], test_series_is_consistent_across_the_set}`.

**Warnings: still exactly 1** — the inherited third-party `pydub`/`audioop` `DeprecationWarning`.

#### Gates

`verify.py` → `RESULT: PASS` (all five checks); `compileall -q scripts files/tests` exit 0 — the
inert archive is deliberately **not** compiled as runtime code; `git diff --check -- '*.py'` exit 0.

#### Installation testing — deferred, not passed

Phase 5's **narrow** dependency and bootstrap contract is **passed**: the automated dependency,
bootstrap, requirements-pinning and release-packaging tests are green, and the import-blocking seam
proves PDF/TXT operation does not need the removed packages. The **real end-user installation test
is DEFERRED, not passed.** The Plan 4 dependency set is not final — the Chatterbox phases may still
add or alter requirements — so no package was installed or uninstalled in the working `.venv`, the
`.venv` was neither deleted nor rebuilt, no standalone pip clean install was run, `bootstrap.py`
was not executed directly, and neither root launcher was run. At the later authorized Windows gate
it must use the root `Setup_and_Run-audiobook-creation-tool.bat` for **both** a disposable clean
first-run installation **and** a second-invocation existing-environment fast path.

#### Preserved boundaries

Version `0.5.1`; six launcher tools; `master` = `origin/master` = `809a43e`; `config-template.toml`
absent from worktree and index; `pillow-heif==1.5.0`; all 22 approved Plan 1/2 screenshots
byte-identical. Every approved Phase 4 Cover behaviour untouched — `cover_resizer.py`,
`job_control.py`, `job_ui.py` and `image_capabilities.py` are not in the diff. The four reference
recordings are byte-identical to their Phase 0 hashes, still ignored at `.gitignore:55`, and still
absent from `git ls-files`; no audio, model, cache, log or runtime-data blob entered the index.
**Phase 6 and later were not started**: no unified importer queue, no panel frame class, no
`ImportAdapter` / `JobController` / `JobAdapter` / `planning_groups` / `capture_run` anywhere under
`scripts/Universal/tts/`, no change to PDF/TXT output planning, no change to the Edge or Kokoro
conversion flow, and no Edge timing rewrite. No Chatterbox work, no HEIC manual testing, no macOS
action, no CUDA/Metal work, no version bump, no tag, release, packaging run, publication, merge or
branch deletion.

#### One contract reading resolved

The drop's Phase 6 text says *"The mode radio is gone with EPUB in Phase 5."* Read literally that
would delete the Single/Batch control now — but the surviving PDF/TXT workflow needs both paths
until Phase 6 builds the unified queue, and the maintainer's Phase 5 kickoff is explicit and later
in authority: *"Phase 5 removes EPUB and leaves the surviving PDF/TXT workflow operational. Phase 6
owns the panel restructure and unified queue."* So Phase 5 removed the **EPUB** mode control
(`epub_convert_var` and its checkbox) and retitled the radio to `Single file (PDF / TXT)`; the
Single/Batch radio itself — not an EPUB control — survives for Phase 6 to collapse.

**Phase 5 was APPROVED by the maintainer on 2026-08-14.**

---

### Phase 7 — TTS: job-control adoption and mirrored-output consolidation (2026-08-15, HOME-PC)

**Result: the TTS run is owned by the shared `JobController`, presented by the shared `JobAdapter`,
frozen once by `capture_run`, and its every destination is planned once and keyed by occurrence id
so a retry lands where the original run planned.** Three files changed —
`scripts/Universal/tts/epub2tts_gui.py`, a new `files/tests/test_tts_jobs.py`, and nine tests
rewritten in place in `files/tests/test_tts_importing.py`. **No engine module was touched, and
`batch_convert.py` did not need a seam** — Phase 6 already called `convert_single_pdf` with the
planned target as `out_mp3`, which is the seam the drop hoped would suffice.

**Entry checkpoint:** `d5be8af` (Phase 6, approved), branch `feature/0.6.1-tts-cover-workflows`,
8 ahead / 0 behind `master`, worktree clean, `VERSION` `0.5.1`, six launcher tools,
`config-template.toml` absent from worktree, index and tree. All four Chatterbox reference MP3s
present and byte-identical to their Phase 0 sizes and SHA-256 values; the four older recordings
named in the Phase 6 kickoff (`files/voices/*.wav`, `tests/fixtures/reference/The Moon.mp3`)
**remain absent from this repository** and were deliberately not created.

#### What was built

**One run, frozen once.** `run_job()` validates, reads every remaining Tk variable on the main
thread, then calls `capture_run` exactly once — freezing the imported snapshot, the PDF/TXT
catalog, the live `ImportOptions`, the captured `EffectiveConfig` and a `freeze_tts_options`
mapping holding every setting the worker or a retry could need (speaker, rate, resume, overwrite,
bitrate, workers, Kokoro voice and speed, the end and paragraph pauses, and the whole `pause_kw`
block). Only then is a run directory reserved, and only then are destinations planned. After that
point neither the worker nor any retry consults a widget, a `tk.Variable`, the live
`ImportedFileManager` or today's configuration.

**Destinations are keyed by occurrence id.** `plan_destinations` now returns
`occurrence_id -> PlannedOutput(source, destination, direct)`. It walks identities with
`_identity_buckets` and paths with `planning_groups`, then cross-checks the two in `_pair` and
raises `UnsafePathError` rather than pairing an occurrence with another's destination. Placement is
unchanged and still Plan 2's alone: `plan_flat` for directly added files (31A), `plan_mirrored` for
one folder root (7A), `plan_multi_root` for several (41A), all sharing the one
`DestinationPlanner` the reservation hands out. Two deliberate duplicates of one path get two
occurrence ids and two collision-safe destinations, and a retry of one can never reach the other.

**The controller is the only processing-cancel authority.** Phase 6's `threading.Event` is gone.
The Cancel button calls `controller.request_cancel()`; both engines receive
`controller.cancel_check` through the same `cancel_check` seam their existing chapter/chunk
checkpoints already used, so cancellation inside a conversion is as responsive as before. A run is
reported `CANCELLED` only after the controller has genuinely acknowledged the cancellation at a
checkpoint and this attempt's own partial artifact has been cleaned — the worker takes the
acknowledgement itself, after cleanup, if an engine raised at its own checkpoint rather than at the
controller's.

**Pause is between source files, never inside one.** `controller.checkpoint()` is called before
each directly added file and, inside the folder pool, at the top of each pooled task — so a paused
run starts no new source, while a task already inside an indivisible conversion finishes it. A task
that arrives during a pause waits on the controller's condition: woken, never polled, with no sleep
anywhere in production. Cancel outranks pause and wakes a paused worker, which is also what makes
`close()` safe during a pause. Tests assert that neither engine helper contains a checkpoint.

**Item failure versus job failure.** A source that will not convert becomes a retryable
`FailureRecord` against its occurrence, the run continues, and it settles
`COMPLETED_WITH_FAILURES` — which is what makes the retry control available at all. Only a genuine
orchestration failure produces a fatal, item-less, non-retryable record and `FAILED`. A final
`finish()` guard makes sure the panel is released even if settlement itself raises.

**The shared adapter is the processing UI.** One `JobAdapter` per attempt lives in a `job_area`
row, installed at construction with an idle run id and replaced wholesale per run — the retired one
is closed first, so the pump keeps exactly two drains however many runs a session performs. The
panel's `self.progress` **is** the adapter's own indicator, so no second progress model exists. The
importer registers as imported input and the panel as processing options, both locking through the
shared matrix; Start stays the panel's own button (the shared bar does not own Start) but locks
with the processing options. `LoggerBridge()` routes technical detail and failures to the one
session log the launcher already opens.

#### Deliberate presentation changes, both authorized by the drop

- **Fine-grained single-file progress was retired.** The old single-direct path fed the progress
  bar in paragraphs. With one truthful shared progress model counting completed source files, a
  second stream counting paragraphs into the same bar would contradict it, so `progress_callback`
  is now `None` for both engines and the current file is reported as a current-item event instead.
  The drop's §19 explicitly prefers the shared event contract here.
- **The Log box became "Engine output".** The engines are unchanged and chatty, and their
  stdout/stderr is still captured — but it is now a raw transcript, not a job record. What
  happened in the run (state, progress, current item, failures, output location, ending) comes only
  from `JobAdapter` Summary/Details. Routing every engine line through the event stream instead was
  rejected: the stream is an unbounded list re-projected on every drain, so a long book would make
  rendering quadratic.

#### Preserved, and proved

PDF/TXT only; EPUB still retired and the archive still tracked and inert; `epub2tts_edge/*`,
`kokoro_synth.py`, `pdf_extractor.py`, `voice_registry.py` and `batch_convert.py` all absent from
the diff; Edge chunk/PDF retry counts, inter-chunk delay, chunk target and end-silence asserted by
value; the twelve voices and `DEFAULT_VOICE_LABEL` asserted by value; per-source temp-chunk
isolation still keyed on the run root; resume still skips an existing folder target on a first
attempt and deliberately does **not** apply on a retry; Cover untouched; no Chatterbox, macOS or
HEIC work; no dependency change.

#### Gates

Full suite **3085 collected / 3072 passed / 13 skipped / 1 warning** against the approved Phase 6
baseline of 3012 / 2999 / 13 / 1. The delta reconciles exactly: **+73**, the whole of the new
`test_tts_jobs.py`. Nothing was removed, renamed away or re-parametrized — `test_tts_importing.py`
still collects 73 tests, with nine rewritten in place rather than deleted. Skips are the same 13
inherited environment skips (8 Windows symlink-privilege `WinError 1314`, 2 case-insensitive
filesystem, 3 `JACK_RYAN_M4B_FOLDER`); the one warning is the inherited third-party
`pydub`/`audioop` `DeprecationWarning`. `python scripts/verify.py` → `RESULT: PASS` (all five
checks). `compileall` exit 0. `git diff --check -- '*.py'` exit 0.
`test_batch_convert_folders.py` passes **unmodified**, as the drop requires.

#### Installation evidence

**NOT APPLICABLE / NOT RUN in Phase 7** — no dependency or setup change. No `pip
install`/`uninstall`/upgrade, no bootstrap run, no clean venv, and neither root `Setup_and_Run`
launcher was executed. The real Windows installation gate remains deferred to the later authorized
dependency-final phase and must use `Setup_and_Run-audiobook-creation-tool.bat` for both a
disposable clean first-run and a second-run fast path.

#### Residual risks, stated plainly

- **No synthesis was executed.** Every engine call is proved through stubs at the panel seam —
  argument for argument, including the planned targets and the controller's own `cancel_check` —
  but no MP3 was produced end to end in this phase.
- ~~**Two event producers can still race.**~~ **Reported at review and REMEDIATED — see the
  Phase 7 remediation record immediately below.** The window was real and reproducible, not
  theoretical.
- **The rolling estimate is conservative for a concurrent folder pool.** Each sample is one file's
  own wall-clock duration, so with several workers the remaining-time figure over-states rather
  than under-states. Over-estimating never claims an early finish. Direct and folder work are kept
  in separate ETA categories, so the estimator clears its history between them rather than
  averaging two different kinds of work.

**Phase 7 is implemented and AWAITING APPROVAL. Phase 8 (Chatterbox) is NOT AUTHORIZED and was NOT
STARTED.**

---

### Phase 7 remediation — TTS job reporting serialized through one producer (2026-08-15, HOME-PC)

**Result: every TTS reporting call for a run goes through one `RunPublisher`, which holds a single
lock across the whole of minting *and* publishing — so the order events enter the `JobAdapter`
queue is the order `JobReporter` numbered them, and `JobEventStream` never has a lower number
arriving late to refuse.** The remediation is entirely TTS-local: `shared/job_control.py` was not
touched, `JobEventStream`'s `OUT_OF_ORDER` rule was not weakened, no second state machine or event
vocabulary was created, nothing already accepted is re-sorted, and no engine module was edited.

**Entry checkpoint:** `71887b8` (Phase 7), branch `feature/0.6.1-tts-cover-workflows`, 9 ahead /
0 behind `master` (`809a43e`), worktree clean, `VERSION` `0.5.1`, six launcher tools,
`config-template.toml` absent, no Chatterbox work present. All four Chatterbox reference MP3s
verified byte-identical before and after; the four older recordings remain absent and were not
recreated.

#### The defect, in the maintainer's own terms

`JobReporter._emit` allocates the event's `sequence` under its own lock, then calls the publisher
with that lock released — deliberately, because §5.4 of the shared contract forbids holding a lock
across caller code. The docstring states the rule that follows: *one run reports from one
producer.* Phase 7's TTS panel had several: the Tk thread while a button moved the controller, the
conversion worker, and every folder-pool thread that reached a checkpoint and dispatched a state
change. So thread A could take N, be descheduled, thread B take and publish N + 1, and A publish N
afterwards — leaving the stream to refuse the legitimate N as `OUT_OF_ORDER`.

**It was reproduced, not assumed.** A throwaway probe against unmodified `71887b8` held one
producer at the queue's own `put` and released a second: recorded arrival order **`[4, 3]`**,
verdict **`EventVerdict.OUT_OF_ORDER`**, accepted sequences **`[0, 1, 2, 4]`** — sequence 3, a
legitimate progress report, lost.

#### The remediation

**`RunPublisher`** (new, in `epub2tts_gui.py`) is the run's one publication authority. It owns the
attempt's `JobReporter` — which is reachable from nowhere else, so there is nothing to bypass it
with — and the attempt's queue. `_publish` takes one `threading.Lock` and holds it across the
reporter call, whose own publisher hook does the `put`. A thread that would take N + 1 therefore
cannot enter the reporter until the thread holding N has already queued its event.

**It cannot deadlock.** The guarded region calls exactly two things: one shared reporter method
(whose lock is a leaf) and one `put` on an unbounded queue (which never blocks). It never touches
Tk, never touches the controller, and is never re-entered — enforced by a test that reads the
class with its docstrings stripped. The controller dispatches its listener with its own lock
released, so nothing waiting here is holding anything this waits for.

**Retirement is lock-free.** `close()` sets an `Event`, so a panel being torn down can never block
behind a report in flight. `TtsPanel.close()` retires the authority *before* it asks the run to
stop, so the cancellation it provokes has nowhere to draw.

**Superseded states are dropped, never drawn.** Because the controller dispatches outside its own
lock, two threads that moved the run can arrive at the listener inverted — a `PAUSED` before the
`PAUSE_REQUESTED` it answered. `state_changed` compares the snapshot's `revision`, the controller's
own monotonic counter, and refuses one older than the last reported. Nothing is invented, nothing
already accepted is reordered, and the endings (`completed`/`cancelled`) are deliberately outside
the guard, because an ending is not a state.

**Attempt lineage.** A retry re-uses the original `RunSnapshot` and therefore the original run id,
so the id alone cannot tell a live report from a straggler. `_install_jobs` is the one retirement
point: it closes the outgoing authority and installs a new one bound to the new queue. A retired
authority publishes nothing and could not reach the live queue even if it did.

#### Tests — written first, and RED first

New: `files/tests/test_tts_reporting_order.py`, **14 tests**, sections A–I covering the race
reproduction, admission exclusion, state-versus-worker, terminal, concurrent item reporting,
pause/resume, cancellation, retry lineage and teardown. **Initial RED: 14 failed, 0 passed.**
Exclusion is proved with no timing at all — while a producer is held inside the queue's `put`, the
authority is asked directly whether it is free. The one bounded window in the file is the
*opportunity* a second producer is given, never a wait for a race, and the verdict comes from the
recorded arrival order either way. No test sleeps.

Three existing tests were corrected, narrowly and truthfully; none was deleted, skipped, xfailed or
weakened:

- `test_tts_jobs.py::test_the_worker_receives_no_tk_object_and_no_import_state` — now asserts the
  worker holds a `RunPublisher` and that **no** bare `JobReporter` appears in `params` at all,
  which is strictly stronger than what it asserted before.
- `test_tts_jobs.py::test_events_reach_the_ui_only_through_the_queue_the_pump_drains` — reads
  `RunPublisher._deliver` instead of the retired `TtsPanel._publish`; the property is unchanged.
- `test_tts_jobs.py::test_a_cancelled_run_keeps_the_outputs_that_already_finished` — a latent test
  defect the timing change exposed: it read `panel._result` after waiting only for the controller
  to reach `CANCELLED`, but the settled result is delivered to the main thread afterwards, through
  the queue. It now drains to the end. No production behaviour changed.

`files/tests/test_batch_convert_folders.py` passes **UNMODIFIED**. Cover production code is
unchanged and its job tests pass as a regression consumer of the untouched shared foundation.

#### Gates

- Targeted §13 set (TTS ×4, batch-convert folders, job control/controller/events-ETA/results/UI,
  import manager/coordination/traversal/importing, Plan 3 boundaries, tool-output integration,
  output paths, EPUB retirement, Kokoro timing and voices, Cover ×5): **2244 passed, 10 skipped**.
- Full suite: **3099 collected, 3086 passed, 13 skipped, 1 warning**. Baseline 3085 / 3072 / 13 / 1
  → delta **+14 collected, +14 passed**, exactly the new module. `test_tts_jobs.py` still collects
  73 and `test_tts_importing.py` still collects 73: nothing was removed or re-parametrized.
- Skips (13, unchanged): 8 Windows symlink-privilege `WinError 1314`, 2 case-insensitive
  filesystem, 3 `JACK_RYAN_M4B_FOLDER` env-gated. Warning (1, unchanged): third-party
  `pydub`/`audioop` `DeprecationWarning`.
- `python scripts/verify.py` → **`RESULT: PASS`**. `compileall` exit 0. `git diff --check` exit 0.

#### Installation evidence

**NOT APPLICABLE / NOT RUN.** No dependency change, no `pip` of any kind, no clean venv, neither
`Setup_and_Run` launcher executed, no real synthesis. This remediation changes reporting
orchestration only.

**Phase 7, including this remediation, is AWAITING APPROVAL. Phase 8 (Chatterbox) is NOT AUTHORIZED
and was NOT STARTED.**

##### Session Sync Log — 2026-08-15 — HOME-PC — Phase 7 remediation

- Entered at `71887b8`, 9 ahead / 0 behind `master` `809a43e`; clean.
- Pre-fix race reproduced at the real queue boundary before any edit was made.
- One production file changed (`epub2tts_gui.py`), one new test file, three tests corrected in
  `test_tts_jobs.py`, this Handoff.
- Committed as a separate remediation commit and pushed to
  `origin/feature/0.6.1-tts-cover-workflows`. `master` untouched. No merge, tag, release, package,
  version bump or branch deletion.

---

### Phase 6 — TTS: panel restructure and importer adoption (2026-08-14, APPROVED 2026-08-15)

**Result: the TTS panel is a state-owning frame class with one unified PDF/TXT queue, and it is
the second production adopter of the Plan 3 importing foundation.** Three files changed —
`scripts/Universal/tts/epub2tts_gui.py`, a new `files/tests/test_tts_importing.py`, and one
two-line narrowing of the Plan 3 adoption guard. No engine module was touched.

**Entry checkpoint:** `47a829d` (Phase 5), branch `feature/0.6.1-tts-cover-workflows`, 7 ahead /
0 behind `master`, worktree clean, `VERSION` `0.5.1`, six launcher tools, `config-template.toml`
absent from worktree, index and tree.

#### What was built

`build_ui(parent)` was a closure-based function holding ~30 `tk.*Var`s in scope, which gave the
shared adapters nothing to attach a lifetime to. It is now `TtsPanel(ttk.Frame)`; `build_ui` still
takes the launcher's container, packs the panel into it, and now also returns it (the launcher
ignores the return value, so its integration contract is unchanged). `close()` cancels the run,
joins the worker within a bounded timeout, closes the `ImportAdapter` and closes the
`MainThreadPump`; `destroy()` calls it first. The hand-written `root.after(200, pump_queue)` chain
is gone — the log/progress queue is now a **drain** on the one pump, which the import poller also
rides, so exactly one Tk callback is ever outstanding.

The Single/Batch radio, the input entry box, `input_var` and `_browse_input` are gone. `Add Files`
takes several PDF/TXT files through the shared direct-file validator; `Add Folder` recurses through
the shared scanner with the existing broad-root pre-warning, the captured large-result threshold,
the live discovered count and its own separate import cancel. Directly added files and
folder-derived occurrences live in **one** `ImportedFileManager`, which is the sole authority: no
second path list, no local scanner, no local dedup, no local natural sort, no local hidden-folder
or link rule. Both option groups were retitled from the retired mode names to the halves of the
queue they actually govern (`MP3 options — files added directly`, `Pause timing — files added
directly`, `Options for files imported from a folder`); what each setting does is unchanged.

**Provenance selects the processing path**, which is exactly the distinction the retired radio made
and the distinction the shared importer already carries. A directly added file takes the rich
chapter/pause engine (`run_conversion_job`) and lands flat in the run (Decision 31A); a
folder-derived file takes the chunked batch worker (`convert_single_pdf`, which already accepts its
mirrored target as `out_mp3`) and mirrors its folder (Decision 7A); several roots each get their own
container (Decision 41A). Destinations come from `planning_groups(snapshot)` into `plan_flat` /
`plan_mirrored` / `plan_multi_root` sharing **one** `DestinationPlanner`, so nothing in a mixed
queue can be planned onto another item's path. One mixed queue is **one** run.

**One genuinely new panel-side mechanism, recorded plainly.** `run_conversion_job` names its own
artifact `<stem> (<speaker>).mp3`, so a directly added item is given a private `tempfile` staging
directory and its finished file is moved to the planned destination. That is what stops two
directly added files with the same stem overwriting each other — the one queue can now hold both,
where the single-file mode could only hold one. The engine itself is called unchanged.

#### Main-thread safety

The three conversion helpers were deliberately moved **out** of the panel to module level, taking
the queue and the cancel predicate rather than `self`. `conversion_worker` therefore reaches
exactly two attributes on the panel — `_log_q` and `_cancel_event` — and the suite asserts that as
an AST **whitelist**, which is stronger than a blacklist of known-bad names. Every Tk value and the
manager snapshot are captured on the main thread before the thread starts; the worker receives
plain values only. The two cancellation domains stay separate: the import cancel reaches the
coordinator only, `cancel_job` reaches the conversion event only, and each is proved not to touch
the other while the other is live.

#### Gates

**3012 collected / 2999 passed / 13 skipped / 1 warning**, against the approved Phase 5 baseline of
2941 / 2928 / 13 / 1. The **+71** reconciles exactly: **+73** new tests in
`files/tests/test_tts_importing.py`, **−2** parametrized cases removed because `tts/epub2tts_gui.py`
moved from the two no-adoption guards' `UNADOPTED_*` lists into `ADOPTED`. No test was deleted,
skipped, xfailed or weakened. Skips are the same 13 inherited environment skips (three
`JACK_RYAN_M4B_FOLDER`, two case-insensitive-filesystem, eight Windows symlink-privilege
`WinError 1314`); the single warning is still the third-party `pydub`/`audioop`
`DeprecationWarning`. `verify.py` → `RESULT: PASS`; `compileall` exit 0; `git diff --check --
'*.py'` clean.

*Honest note on skip counts:* the symlink-privilege skips flap on this machine. One baseline run
before any edit reported 22 skips / 2919 passed (the same 2941 collected) because nine more
symlink tests skipped that run; an immediate re-run reported the approved 13 / 2928. The
post-implementation run reported 13 skips. The **collected** count is the stable number and is what
the delta above is reconciled against.

#### Preserved boundaries

`epub2tts_edge/*`, `kokoro_synth.py`, `pdf_extractor.py`, `voice_registry.py` and
`batch_convert.py` are **not in the diff** — Phase 6 needed no seam in any of them, because
`convert_single_pdf`'s `out_mp3` parameter already was one. Edge and Kokoro timing constants,
retry counts, inter-chunk delay, the twelve voices and `DEFAULT_VOICE_LABEL` are unchanged and
asserted by value. EPUB stays retired and is proved unable to enter through a direct add, a folder
scan, a stale selection or the shared options; the tracked archive at `files/archived-code/epub-tts/`
is untouched, and GPL-3.0 and the upstream attribution are unaffected. Cover's approved Phase 1–4
behaviour is untouched. **No Phase 7 vocabulary arrived**: no `JobController`, `JobAdapter`,
`JobControlBar`, `capture_run`, `RunResult`, retry execution, pause/resume or ETA anywhere in the
panel. Phase 11's broader guard conversion was **not** performed — the third substring guard in
`test_tool_output_integration` still stands unmodified, and the panel simply does not contain the
literals it forbids. No Chatterbox work, no HEIC manual testing, no macOS action, no version bump,
no tag, release, packaging run, merge or branch deletion.

`VERSION` `0.5.1`; six launcher tools; `master` = `origin/master` = `809a43e`;
`config-template.toml` absent. The four Chatterbox reference recordings are byte-identical to their
Phase 0 SHA-256 values, still ignored at `.gitignore:55`, and still absent from `git ls-files`. The
four `files/voices/*.wav` and `tests/fixtures/reference/The Moon.mp3` paths named in the Phase 6
kickoff as protected recordings **do not exist anywhere in this repository** — recorded, and
deliberately not created.

#### Installation evidence

**NOT APPLICABLE — no dependency or setup change.** No `pip install`, `pip uninstall` or upgrade;
no bootstrap run; neither root launcher was executed; no clean venv was created. The real Windows
installation gate remains deferred to the later authorized dependency-final phase and must use the
root `Setup_and_Run-audiobook-creation-tool.bat` for both a disposable clean first-run installation
and a second-invocation fast path.

**Next action: Phase 6 approval. Phase 7 — TTS: job-control adoption and mirrored-output
consolidation — is NOT authorized and was NOT started.**

#### Session Sync Log — 2026-08-14 — HOME-PC — Phase 6

- Changed: `scripts/Universal/tts/epub2tts_gui.py` (panel restructured to `TtsPanel`, unified
  PDF/TXT queue, importer/pump adoption, planned destinations, worker helpers moved to module level)
- Added:   `files/tests/test_tts_importing.py` (73 Phase 6 tests)
- Changed: `files/tests/test_plan3_boundaries.py` (`ADOPTED` gains the TTS panel; adjacent comment
  corrected so it stays true)
- Changed: `md-instructions/Handoff.md` (this entry)
- Note:    One commit on `feature/0.6.1-tts-cover-workflows`, pushed. `master` untouched. No AI
           co-author trailers.

### Phase 8 — Chatterbox: model selection, dependency proof, and the engine module (2026-08-15, HOME-PC)

Ran as three gated stages: **8a discovery** in an isolated venv, an **8b hard stop** returned to
the maintainer, and — after the maintainer resolved both gates — the **8c engine foundation**.

#### 8a — what the exact wheel actually provides

Every finding below comes from the published `chatterbox-tts` **0.1.7** wheel (released
2026-03-26, MIT, `requires-python >=3.10`), not from documentation or from master. The §5.6
Turbo/Nano discrepancy is **confirmed still true**:

| Question | Answer, from the wheel |
|---|---|
| Import path | `chatterbox.tts_turbo.ChatterboxTurboTTS` — the package root exports only `ChatterboxTTS`, `ChatterboxVC`, `ChatterboxMultilingualTTS`, `SUPPORTED_LANGUAGES`, so the documented `from chatterbox import ChatterboxTurboTTS` **fails** |
| Nano | **Not reachable from 0.1.7.** `from_pretrained` takes `device` only; there is no `nano=` parameter. That behaviour exists only on unversioned master |
| Loaders | `from_pretrained(device)` → `from_local(ckpt_dir, device)` |
| `generate` | `(text, repetition_penalty=1.2, min_p=0.0, top_p=0.95, audio_prompt_path=None, exaggeration=0.0, cfg_weight=0.0, temperature=0.8, top_k=1000, norm_loudness=True)`; Turbo logs a warning and **ignores** cfg_weight / exaggeration / min_p |
| Output | `torch.float32`, shape `(1, N)`, sample rate `model.sr` = **24000** |
| Reusable conditionals | **Yes** — `prepare_conditionals(wav_fpath, …)` plus `Conditionals.save()` / `.load(fpath, map_location=…)`; round-trip verified, ~170 KB per voice |
| Model | `ResembleAI/chatterbox-turbo`, MIT, **4,044,167,698 bytes** (~3.86 GiB) |
| Watermark | PerTh watermarking is applied inside `generate` and is **mandatory and default** |

**Reference-audio contract, derived from the model's own code rather than from a docs figure.**
`prepare_conditionals` asserts the input is **longer than 5 seconds**, then takes plain **leading
slices**: `s3gen_ref_wav[:DEC_COND_LEN]` (10 s at 24 kHz) for the decoder and
`ref_16k_wav[:ENC_COND_LEN]` (15 s at 16 kHz) for the speech tokenizer. It resamples to 24 kHz
mono itself and **normalises loudness itself** to about **-27 LUFS**, so a caller must not
pre-normalise. Raw MP3 loads directly (librosa read the 362.3 s `Male-1.mp3` in 11.57 s), but a
short WAV derivative loads instantly — so a derivative is right on cost alone. The "10s" figure in
an upstream example filename is a hint, not the specification.

*Recorded nuance:* the **voice-encoder speaker embedding is computed over the whole loaded
waveform**, not over a truncated window — only the decoder and tokenizer paths are sliced. A
15-second derivative therefore also fixes the embedding to those 15 seconds. That is deterministic
and matches the widest window the model consults, but it is a real characteristic of the choice and
is written down here rather than assumed away.

**Measured cost (HOME-PC, CPU, this machine only — these figures do not generalize).**

| Metric | Measured |
|---|---|
| Aggregate real-time factor (compute ÷ audio) | **1.211** |
| Throughput | **0.826 audio-seconds per compute-second** |
| Per-chunk RTF | 1.228 / 1.214 / 1.175 / 1.189 — stable |
| Peak working set | **~6,191 MB**; steady ~3,990 MB |
| Model download | 4,044,167,698 bytes (~3.86 GiB), first fetch ~6 min 13 s |
| Warm model load | 4.65 s (8.57 s in the clean-venv proof) |
| `prepare_conditionals` | ~16.1 s per voice, one-time and cached (~170 KB) |
| Installed-size delta | ~+1,152 MB (1363 → 2515 MB), 111 → 169 packages |
| Device | `torch 2.6.0+cpu`; `cuda_available` **False**, `mps_built` **False** on Windows |

**Generation is slower than real time.** It must not be described as real-time CPU synthesis.

#### 8b — the hard stop, and the maintainer's two rulings

Gates A (Kokoro damage), B (Python 3.12), C (four-reference cloning), F (CUDA/shared-torch) and I
(licence) were all **clear**. Two triggered and the phase stopped with evidence rather than a
workaround:

- **Gate E — CPU practicality ambiguous.** RTF 1.21 with a 6.2 GB peak is neither clearly fine nor
  clearly fatal; calling it "practical" would have meant inventing a threshold.
  **Maintainer ruling (2026-08-15): ACCEPTED** for an **optional, non-default** engine.
- **Gate G — an undeclared incompatibility.** `resemble-perth` imports `pkg_resources` but declares
  **no dependencies at all**, and `chatterbox-tts` declares **no setuptools bound**. Under this
  project's `setuptools==82.0.1`, which removed `pkg_resources`, the import fails, perth swallows it
  and sets its watermarker class to `None`, and model construction dies with a misleading
  `TypeError: 'NoneType' object is not callable`.
  **Maintainer ruling (2026-08-15): AUTHORIZED** to pin exactly `setuptools==80.9.0`.

**Kokoro compatibility, proven not assumed.** On the combined stack in an isolated Python 3.12.10
venv, a real CPU synthesis through the production `tts/kokoro_synth.py` produced **byte-identical**
output (33,837 bytes, 8.35 s audio) and the **full repository suite passed unchanged**.

#### 8c — what was built

**Dependencies (`scripts/requirements.txt`).** `setuptools==82.0.1` → **`80.9.0`**, with the reason
recorded beside the pin as explicit **compatibility debt** (pkg_resources is deprecated and was
slated for removal from 2025-11-30; move forward as soon as upstream stops importing it). Added
`chatterbox-tts==0.1.7` plus the pins upstream leaves floating (`numpy==1.26.4`,
`resemble-perth==1.0.1`, `s3tokenizer==0.3.0`, `spacy-pkuseg==1.0.1`, `pyloudnorm==0.2.0`,
`omegaconf==2.3.1`) and the four headline downgrades stated explicitly rather than left implicit
(`torch==2.6.0`, `torchaudio==2.6.0`, `transformers==5.2.0`, `safetensors==0.5.3`). All gated
`python_version < "3.13"` alongside Kokoro. **No CUDA build, no index URL, no git/master source.**

**Engine (`scripts/Universal/tts/chatterbox_synth.py`, new).** Mirrors `kokoro_synth.py`: the same
module-load `HF_HOME` fallback into the **existing** in-tree cache (no second cache), lazy imports
so nothing heavy loads at import, `_get_model(device)` with the same **single first-load**
allowance for Windows Application Control, and `chatterbox_file_to_mp3(...)` carrying the identical
worker signature. Device selection resolves `cuda → mps → cpu` behind one testable seam. Reference
resolution verifies SHA-256 **on every use**; derivatives go to
`files/runtime-data/chatterbox/reference-clips/` and conditionals to
`…/chatterbox/conditionals/`, both keyed on `voice + source hash + engine release + clip spec`, so
a stale entry misses rather than gets reused. A manifest records label → source → full source
SHA-256 → derivative → parameters. Writes into `files/Chatterbox-Voice-Uploads/` are refused
structurally. The four voice IDs exist **inside the engine only** and reach no dropdown.
The PerTh watermark path is untouched.

**Bootstrap (`shared/bootstrap.py`).** `CHATTERBOX_PKGS` (including the setuptools compatibility
pin, because a repair without it leaves a package that imports but cannot build a model),
`chatterbox_is_healthy()` — a subprocess probe that checks the exact module *and* class, since
resolvable-but-unusable is this engine's actual failure mode, and therefore deliberately **kept off
the every-launch fast path** — `ensure_chatterbox_installed()`, `warmup_chatterbox()` and
`predownload_chatterbox()`. The first-run checkbox is **unchecked by default** and states the real
~3.9 GB size; Kokoro's default is unchanged. `"chatterbox"` joined `REQUIRED_IMPORTS`, with a new
`_GATED_BELOW_313` skip so a 3.13+ venv does not report a false failure for a package its own
marker excludes. Missing *recordings* are deliberately **not** a setup requirement: a machine can
have the package and no references and must still launch.

**Registry (`tts/voice_registry.py`).** `BACKEND` widened to
`Literal["edge", "kokoro", "chatterbox"]` and `_chatterbox_preset()` added. **No `VoiceEntry` row.**
All twelve existing rows and `DEFAULT_VOICE_LABEL` are asserted field-by-field and unchanged.

#### Gates

Full suite **3270 passed, 13 skipped, 1 warning** (3283 collected), `verify.py` **RESULT: PASS**,
`compileall` exit 0, `git diff --check` clean. Collection reconciled exactly against the 3099-node
baseline: **+181** new Chatterbox tests, **+2** from the EPUB guard list gaining the new module,
**+1** from `test_plan3_boundaries` auto-parametrizing over production modules. **Zero tests
removed** — the two changed node ids are a `setuptools` parametrize id (82.0.1 → 80.9.0) and one
documented rename in `test_tts_jobs.py`, each matched 1:1 by an added id. The 13 skips are all
pre-existing and environmental (8 Windows symlink privilege, 2 case-insensitive filesystem, 3
unset `JACK_RYAN_M4B_FOLDER`).

**Clean-environment proof.** A fresh Python 3.12.10 venv built from the **committed**
`requirements.txt` in one `pip install` with **no manual post-install correction**: `pip check`
clean, every target version exact, the health probe passes, `ChatterboxTurboTTS` constructs on CPU,
weights load from the existing cache (0 bytes downloaded), one real Chatterbox CPU synthesis
succeeds, one real Kokoro CPU synthesis through the production module succeeds, and the full suite
gives the identical 3270/13/1.

**Not performed:** the working `.venv` was not modified, `Setup_and_Run-…bat` was not run, no CUDA
was installed or benchmarked, and no Mac work was done. MPS evidence is code-reading only (the
loader has a real MPS branch with CPU fallback); it is **not** a macOS proof.

**Local-asset boundary.** All four recordings re-hashed before and after: byte-identical, exactly
four files, zero tracked. One derivative and one cached conditional were produced for `Male-1` by
the smoke test; both live under ignored `files/runtime-data/`. **Phase 9 has not started** — no
evaluation folder, no four derivatives, no four listening outputs.

**Approval.** The maintainer **approved Phase 8 on 2026-08-15**, at SHA
`ce6e62bcd4e0060786259c68f9d1c5c5b9c1c97b`, in the same prompt that authorized Phase 9.

---

### Phase 9 — Chatterbox: listening-evaluation samples — HARD STOP (2026-08-15, HOME-PC)

**Start SHA** `ce6e62bcd4e0060786259c68f9d1c5c5b9c1c97b` (approved Phase 8), branch
`feature/0.6.1-tts-cover-workflows`, 11 ahead / 0 behind `master` at entry.

**What this phase is.** Four maintainer-supplied recordings in, four evaluation WAVs out, a table,
and a stop. It decides nothing. No voice was registered, no GUI or dispatch was touched, and
Phase 10 was not begun.

#### The four references — verified, and unchanged afterwards

Each source's SHA-256 was verified **before** use and **re-verified after** all synthesis. All four
are byte-identical to the values recorded at the top of this document, still exactly four files,
still zero tracked.

| Voice | Source | Source SHA-256 (verified twice) | Derivative | Conditional |
|---|---|---|---|---|
| `chatterbox-female-1` | `Female-1.mp3` | `a047d77f…4bb8bde2` | `female-1__a047d77fe191c1a9__3d3a090f288c.wav` | computed this run |
| `chatterbox-female-2` | `Female-2.mp3` | `4bad0d38…f08d3140` | `female-2__4bad0d3845199eae__2c8230d3b25d.wav` | computed this run |
| `chatterbox-male-1` | `Male-1.mp3` | `6258dde2…c80165ae` | `male-1__6258dde294a91b0c__5ae92af1f724.wav` | **reused** from Phase 8 |
| `chatterbox-male-2` | `Male-2.mp3` | `7b8fd74d…b048d6ab2` | `male-2__7b8fd74dfb262740__e0390f888f05.wav` | computed this run |

**Derivative spec — Phase 8's, unchanged and not re-invented here:** leading 15-second window,
audio stream selected explicitly (`-map 0:a:0 -vn`, so the embedded cover art can never be picked
up), mono, 24,000 Hz, `pcm_s16le`, **no caller-side loudness normalization** (the model normalizes
to about -27 LUFS itself). Each derivative is 720,044 bytes — identical size, as a fixed-length
PCM window must be. All four live under ignored `files/runtime-data/chatterbox/reference-clips/`;
the four conditionals (~170 KB each) under `…/chatterbox/conditionals/`. `Male-1`'s derivative and
conditional kept their Phase 8 timestamps: **reused, not rebuilt**, which is the cache working.

#### The four outputs

`files/test-for-manual-listen-elmatthe/chatterbox-eval/` — inside the parent that `.gitignore:35`
already covers, so the audio cannot reach the repository. `tests/samples/voice_eval/` was **not**
created; it sits outside the approved layout and outside that ignore rule.

| Voice | Reference source | Output path | Duration | Parameters | Result |
|---|---|---|---|---|---|
| chatterbox-female-1 | Female-1.mp3 | `files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-female-1.wav` | 7.56 s | Turbo defaults (below) | **OK** |
| chatterbox-female-2 | Female-2.mp3 | `files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-female-2.wav` | 7.92 s | Turbo defaults (below) | **OK** |
| chatterbox-male-1 | Male-1.mp3 | `files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-male-1.wav` | 8.52 s | Turbo defaults (below) | **OK** |
| chatterbox-male-2 | Male-2.mp3 | `files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-male-2.wav` | 8.64 s | Turbo defaults (below) | **OK** |

All four are mono, 24,000 Hz, 16-bit PCM, readable and non-empty (181,440 / 190,080 / 204,480 /
207,360 frames). Every output was rendered from the **identical** approved sentence: *"Welcome to
the audiobook creation tool. This is a sample test evaluating Chatterbox for clarity, pacing, and
emotional depth."* — no prefix, no suffix, no voice name.

**Parameters — one set for all four, read off the pinned wheel's own signature rather than
transcribed.** The module passes **no** generation keyword, so these *are* the effective values:
`repetition_penalty=1.2, min_p=0.0, top_p=0.95, audio_prompt_path=None, exaggeration=0.0,
cfg_weight=0.0, temperature=0.8, top_k=1000, norm_loudness=True`. Turbo logs a warning and
**ignores** `cfg_weight` / `exaggeration` / `min_p` — they are reported because the signature
carries them, not because they do anything here. No voice was tuned independently and no sweep,
A/B variant or "best of" rerun was produced.

#### Measured performance — device `cpu`

| Voice | Wall time | Audio | RTF | Conditional |
|---|---|---|---|---|
| chatterbox-female-1 | 15.99 s | 7.56 s | 2.115 | computed |
| chatterbox-female-2 | 10.63 s | 7.92 s | 1.343 | computed |
| chatterbox-male-1 | 11.04 s | 8.52 s | 1.296 | reused |
| chatterbox-male-2 | 11.56 s | 8.64 s | 1.338 | computed |

**Successes 4, failures 0.** Derived aggregate: 49.22 s of compute for 32.64 s of audio, mean
RTF **1.508** — clearly labelled as derived, and **not** comparable to Phase 8's 1.211 without the
caveat below.

**What the wall time includes, stated rather than glossed.** It is measured end-to-end per voice
and therefore includes conditional computation, and for the first row the one-time model load. That
is why `female-1` reads 2.115 while the other three cluster near 1.30–1.34; the three comparable
rows sit close to Phase 8's measured 1.211 aggregate. These are **measurements on this machine**,
not a generalization, and nothing here extrapolates them to audiobook length.

#### Implementation

Reused `tts/generate_voice_samples.py` as the drop requires — no second sample script exists.
It gained a `--chatterbox-eval` mode, deliberately **opt-in**: an ordinary sample refresh must never
load a ~3.9 GiB model by accident, and a test asserts the mode is unreachable outside that flag.
The Edge and Kokoro branches, `SAMPLE_TEXT`, `_out_dir()`, `_select()` and the OK/FAIL reporting
style are unchanged.

The run is **two stages on purpose**. Stage one proves all four sources — hash plus derivative —
and a single failure there is a hard stop that generates *nothing*, because a mismatched recording
invalidates the comparison the maintainer is about to make. Stage two synthesizes; a failure there
is a FAIL row and the remaining voices continue. Either way the table always has four rows and no
failure is dropped or silently retried.

`chatterbox_synth.py` took three narrow additions, no broadening: `synthesize_text_to_wav()` (the
same path as the MP3 helper minus the lossy encode — the evaluation must not judge the engine
through an MP3 encoder; returns the model's own sample rate so the caller reports what was used),
`generation_defaults()` (introspects the wheel's `generate` signature, so a pin change cannot leave
a stale figure in a docstring), and the manifest now records the conditional cache path and is
refreshed on **every** `prepare_reference_clip` call rather than only on a rebuild — otherwise a
derivative cached by an earlier run left the manifest permanently incomplete. **One** manifest
still exists, at `files/runtime-data/chatterbox/reference-clips/manifest.json`, now with all four
entries; no second competing manifest was invented.

#### Gates

Full suite **3341 passed, 13 skipped, 1 warning** (3354 collected) — exactly **+71** on the
approved Phase 8 baseline of 3283, which is the new `test_chatterbox_evaluation.py` in full.
`verify.py` **RESULT: PASS**, `compileall` exit 0, `git diff --check` clean (only the known
CRLF-normalization notices). The 13 skips are unchanged and environmental (Windows symlink
privilege, case-insensitive filesystem, unset `JACK_RYAN_M4B_FOLDER`).

**Zero tests removed.** Three Phase 8 boundary guards were **retargeted, not deleted**, because
Phase 9 is exactly the boundary they were written to detect and it is now authorized — the file's
collected count is unchanged:

| Was | Now | Why |
|---|---|---|
| `UNTOUCHED_BY_PHASE_EIGHT` listing `generate_voice_samples.py` | `UNTOUCHED_BY_PHASE_NINE` listing `epub2tts_edge/runner.py` | The generator is Phase 9's authorized target; the vacated slot went to the Edge runner, which Phase 10 would be the first phase to touch. Still five files, still two parametrized guards |
| `test_the_phase_nine_evaluation_folder_was_not_created` | `test_the_phase_nine_evaluation_folder_stays_out_of_the_repository` | The folder now exists locally; what still matters is that `git check-ignore` refuses it |
| `test_the_sample_generator_still_covers_only_the_registered_voices` | `test_the_sample_generator_reaches_chatterbox_only_behind_its_own_flag` | An AST check that `run_chatterbox_evaluation` appears **only** inside the `--chatterbox-eval` branch of `main` |

No test was skipped, xfailed or weakened. Phase 9's own contract is asserted in far more detail by
the 71 new tests than the guards they replaced ever did.

#### Environment — nothing was mutated

The real synthesis ran in the **retained Phase 8 probe environment**
(`files/runtime-data/chatterbox/phase8-probe/baseline-venv`, Python 3.12.10), first verified to
match the **committed** `scripts/requirements.txt` exactly: all 24 applicable pins present at the
exact version, zero mismatches. The working `.venv` was **not** modified — it still has no
Chatterbox, by design, and it is where the test suite and `verify.py` ran. Model weights were
reused from `files/runtime-data/models/huggingface/`; **0 bytes downloaded**.
`Setup_and_Run-audiobook-creation-tool.bat` was **not** run, CUDA was **not** configured or used
(`torch 2.6.0+cpu` selects `cpu` truthfully through the Phase 8 selector), and no Mac was involved.

#### Preservation

No `VoiceEntry` added — still exactly twelve rows, asserted field-by-field, same order,
`DEFAULT_VOICE_LABEL` unchanged, `display_labels()` unchanged. No GUI, dropdown, timing control,
worker dispatch, direct/folder conversion, Retry Failed, output planning or unified-queue change.
Phase 7's `RunPublisher` untouched. Edge, Kokoro and Cover untouched. EPUB remains retired. The
four Chatterbox IDs remain **engine-internal**.

#### The stop

The four WAVs remain on disk, ignored and local-only, for the maintainer to listen to:

```
files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-female-1.wav
files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-female-2.wav
files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-male-1.wav
files/test-for-manual-listen-elmatthe/chatterbox-eval/chatterbox-male-2.wav
```

**The maintainer listened on 2026-08-15 and approved all four.** The response is recorded verbatim
in the Phase 10 entry below, and Phase 10 was authorized on the strength of it. The four WAVs stay
on disk, ignored and local-only, as reference evidence until Plan 4 closes. The active Plan 4 drop
is **not** retired.

---

### Phase 10 — Chatterbox: lock the approved voices and integrate the unified queue (2026-08-15, HOME-PC)

**Start SHA** `2c63aa75521ae8e082d31923506aa6641ef0686f` (approved Phase 9), branch
`feature/0.6.1-tts-cover-workflows`, 12 ahead / 0 behind `master` at entry.
**Approved Phase 9 SHA:** `2c63aa75521ae8e082d31923506aa6641ef0686f`.
**Protected `master`:** `809a43e754920fce2f11f08e3c401dcc4c7a5223`, unchanged.

#### The listening gate — the maintainer's response, verbatim

> I just listened to all 4 and I am very happy with the results and i want to keep them:
>
> Female 1 — approve
> Female 2 — approve
> Male 1 — approve
> Male 2 — approve
>
> Leave names as Chatterbox - Female 1, etc. for display on the gui (i might change them later). I am very happy with how they sound in fact.

**Summary of the decision (the verbatim quote above is the authority, not this paragraph).**
All four voices are approved. **Zero rejected, zero deferred, zero renamed in substance.** No
source mapping changed and no `voice_id` changed. The maintainer explicitly set the GUI display
labels to the **ASCII-hyphen** form — `Chatterbox - Female 1` — superseding the em-dash labels the
drop's §5.7 had proposed. The maintainer may rename them in a later version; they were not renamed
in this phase.

#### What was registered

`VOICES` went from twelve rows to **sixteen**. The first twelve are unchanged **by value** —
backend, `voice_id`, `display_label`, `group_label` and every key of every `timing_preset` — in
their original order, and `DEFAULT_VOICE_LABEL` is still Steffan. The four approved rows are
appended after them, in this order:

| # | backend | `voice_id` | `display_label` | `group_label` | timing preset |
|---|---|---|---|---|---|
| 13 | `chatterbox` | `chatterbox-female-1` | `Chatterbox - Female 1` | `Chatterbox Turbo Local AI — Cloned Voices` | `_chatterbox_preset()` |
| 14 | `chatterbox` | `chatterbox-female-2` | `Chatterbox - Female 2` | `Chatterbox Turbo Local AI — Cloned Voices` | `_chatterbox_preset()` |
| 15 | `chatterbox` | `chatterbox-male-1` | `Chatterbox - Male 1` | `Chatterbox Turbo Local AI — Cloned Voices` | `_chatterbox_preset()` |
| 16 | `chatterbox` | `chatterbox-male-2` | `Chatterbox - Male 2` | `Chatterbox Turbo Local AI — Cloned Voices` | `_chatterbox_preset()` |

All four take Phase 8's `_chatterbox_preset()` **unmodified and identically** — 600/700/1000/1800/
3000 ms, `trim_dbfs` -58, `trim_edge_chunks` False, `rate` `+0%`, `kokoro_speed` `1.0`. There is
deliberately **no per-voice tuning**: the maintainer approved all four under one common parameter
set, so Female 1 is not timed differently from Male 2. The group label is cosmetic, shared by all
four, and is not part of any voice's name.

#### Registered is not the same as available

The four voices are backed by local reference recordings that exist only where the maintainer put
them. Phase 10 keeps those two ideas apart:

- **Registered** — the row is in `VOICES` on every machine. A missing recording never removes a
  voice, and the four MP3s are **not** an installation requirement.
- **Available** — the local reference is present and valid *here*. Answered by the engine, never
  re-derived by the GUI.

`chatterbox_synth.voice_availability(voice_id)` is the one narrow read-only helper Phase 10 added
to the engine (§23). It gives the same answer `engine_status` gives, memoised per process on the
source recording's `(size, mtime_ns)`, so selecting a voice does not re-hash a 33 MB file every
time. It loads no model, downloads nothing, synthesizes nothing, writes nothing and builds no
derivative. It is **not** a replacement for verification: `resolve_reference` still re-checks the
full SHA-256 on every real conversion, exactly as before, and a memo miss simply runs the full
check again.

The panel projects that into **one boolean and one message** — no second registry, no second state
machine. It never hashes, never names a derivative, never reads the manifest. Behaviour:

- an unavailable voice stays selectable in the dropdown but shows a truthful setup-required reason
  under the voice row, and **Start is refused before capture, before the run directory is reserved
  and before any worker exists**;
- the check is re-asked at Start, not trusted from selection time, so a recording removed in
  between stops the run at the button rather than failing mid-conversion;
- **no substitution of any kind** — not another Chatterbox voice, not Kokoro, not Edge, and nothing
  fetched from the internet;
- one missing recording leaves the other three fully usable; all four missing leaves Edge and
  Kokoro fully usable and the app starting normally;
- a machine with no engine package at all gets a truthful status, never an exception — the seam
  answers rather than raises.

#### Dispatch — one backend, not two booleans

`is_kokoro` is gone. The run freezes an explicit **`backend`** (`edge` / `kokoro` / `chatterbox`)
and **`voice_id`** in `tool_options`, taken from the registry entry — never inferred from a display
label, so renaming a voice later cannot change what any run does. `kokoro_voice_id` was replaced by
that pair rather than joined by a second flag.

The three-way decision is **three calls deep in one shared loop**, at the synthesis seam only. One
queue, one frozen run, one `JobController`, one `RunPublisher`, one progress model, one set of
output planners, one retry lineage — all shared. Backend-specific behaviour is confined to: which
engine function is called; whether Edge's pause/trim block is parsed; whether the direct filename
carries the speaker; and the folder-pool width.

**Folder-pool width for Chatterbox is 1, and that is correctness, not tuning.** Every item in a run
shares one cached model object whose voice conditioning is attached to it, so concurrent
generations would race that state. Edge stays at 32, Kokoro at 8, both unchanged.

#### Controls by backend

| Control | Edge | Kokoro | Chatterbox |
|---|---|---|---|
| Engine label | `Engine: Microsoft Edge TTS \| Voice ID: … \| Group: …` | `Engine: Kokoro local AI \| …` | `Engine: Chatterbox Turbo (Local AI) \| Voice: … \| Group: …` |
| Kokoro speed spinbox | hidden | **shown** | **hidden** |
| Kokoro download notice | hidden | shown | hidden |
| Voice-status line | hidden | hidden | shown only when setup is required |
| Edge pause/trim block parsed into `pause_kw` | yes | no | no |
| Direct output filename | `<stem> (<speaker>).mp3` | `<stem>.mp3` | `<stem>.mp3` |

No Chatterbox tuning UI was invented: the pinned Turbo release exposes no speed parameter, and
`temperature` / `exaggeration` / `cfg_weight` / `top_p` / `top_k` are deliberately absent. Phase 9
approved the engine's own defaults. Engine wording (`Turbo`, `Local AI`) lives in the engine line
and never in a voice's name.

#### Conversion coverage — all through the one queue

Direct TXT, direct PDF, folder TXT, folder PDF, nested folders, the same stem in two subfolders,
and **mixed direct + folder in one frozen run** all convert with a Chatterbox voice. Direct inputs
land **flat**; folder-derived inputs **mirror** their root; two roots each keep their own
**container** through `plan_multi_root`. PDFs take the **existing** `pdf_to_txt` seam — no second
extractor, and `pdf_extractor.py` was not edited. Deliberate duplicates stay two collision-safe
outputs. The worker never rescans a folder; provenance comes from the frozen occurrence.

#### Job controls

Pause and resume run through the same `JobController` lifecycle as Edge and Kokoro, at the same
boundary between source files — a generation already in flight is never torn down. Cancel goes
through the controller's own `cancel_check` predicate, which is what the engine receives; a
cancelled run settles `CANCELLED`, claims no false success, and its partial output is discarded
while earlier successes survive. No second cancellation `Event` exists. Progress publishes only
through `RunPublisher`; as with Kokoro, the engine's fine-grained chunk callback is deliberately
**not** wired, because the run's one progress model counts completed source files and a second
stream into the same bar would contradict it.

**A retry reuses the original frozen `RunSnapshot`** — the exact object — with the original
`backend`, the original `voice_id`, the original source occurrence and the original destination.
Proven explicitly: changing the dropdown to a Kokoro voice between the failure and the retry still
retries with the original Chatterbox voice. An earlier success is never overwritten, direct and
mirrored placement both survive, and the retired attempt's publisher stays closed.

#### Preservation

`RunPublisher`, `shared/job_control.py` and `shared/job_ui.py` are **untouched** — not in the diff
at all — and `test_tts_reporting_order.py` and `test_batch_convert_folders.py` both ran
**unmodified**. `kokoro_synth.py`, `batch_convert.py`, `pdf_extractor.py`,
`epub2tts_edge/runner.py`, `generate_voice_samples.py`, `scripts/requirements.txt`,
`shared/bootstrap.py` and every Cover file are unchanged. The seven Edge and five Kokoro rows are
asserted field-by-field. EPUB remains retired: PDF and TXT are still the only catalog types, an
EPUB cannot enter direct add, folder scan or retry, and no legacy Single/Batch mode or mode radio
returned. `VERSION` is still `0.5.1`; `launcher.TOOLS` is still six; `config-template.toml` is
still absent.

#### Tests and gates

Tests were written first and **genuine RED was recorded**: the new file opened at **67 failed, 24
passed**, the 24 being preservation assertions that must already have held.

| Gate | Result |
|---|---|
| Full suite (fixed order) | **3444 collected, 3431 passed, 13 skipped, 1 warning** |
| Full suite (randomized order) | 3431 passed, 13 skipped — no ordering leak |
| `python scripts/verify.py` | **`RESULT: PASS`** |
| `python -m compileall -q scripts files/tests` | exit 0 |
| `git diff --check -- '*.py'` | clean, before and after staging |

**Collection delta: 3354 → 3444, exactly +90.** `test_chatterbox_integration.py` adds **93** tests;
**3** parametrized cases were removed, all of them the `epub2tts_gui.py` entry in two
"Phase 10 has not started" guard lists. **Zero tests were deleted, skipped, xfailed or weakened.**

Boundary guards were **migrated, not dropped**, and the retargeting is recorded in each file:

| Guard | Was | Now |
|---|---|---|
| registry row count | exactly 12 | exactly 16, **first 12 asserted unchanged by value and order** |
| `test_no_chatterbox_voice_is_registered_in_phase_eight` | zero chatterbox rows | exactly four, all after the twelve |
| em-dash lookup guard | four labels unreachable | retained — the superseded labels must never be registry labels |
| registry AST row check | 12 rows, all edge/kokoro | 16 rows, `["edge"]*7 + ["kokoro"]*5 + ["chatterbox"]*4` |
| `UNTOUCHED_BY_PHASE_NINE` / `PHASE_TEN_MODULES` | included `epub2tts_gui.py` | `epub2tts_gui.py` removed — Phase 10 was authorized to add exactly that dispatch. The four **engine** modules remain guarded |
| panel vocabulary sweep | no `chatterbox` substring anywhere | substring guard retargeted at `torch` / `librosa` / `resemble_perth` / `pillow_heif`, plus a new **AST** guard that the panel never imports the third-party `chatterbox` package |
| frozen-options guard | `kokoro_voice_id is None` | `backend == "edge"` and `voice_id == "en-US-SteffanNeural"` |

The retired guard's subject is covered far more thoroughly than before: 93 assertions now describe
the panel-side contract that the removed "has not started" cases used to stand in for.

**The known ffmpeg skip flake occurred once and was not fixed here.** One full run reported **24
skipped** instead of 13, with **zero failures**. Cause proved to be the pre-existing PATH-lookup
condition and nothing else: this machine has no bundled `files/bin/ffmpeg.exe`, so
`ffmpeg_utils._find` falls back to `shutil.which`, and `have_ffmpeg()` is `lru_cache`d at its first
call — a transient miss gates the 11 ffmpeg-marked tests for the whole process. Removing
`C:\ffmpeg\bin` from `PATH` reproduces skips on demand with no code change; restoring it gives
85 passed / 0 skipped on the same subset. `ffmpeg_utils.py` is **not in this phase's diff**. Two
subsequent full runs, fixed and randomized order, both gave 13 skips. **Reported, not hidden, and
deliberately not broadened into.**

The 13 skips are all environment or fixture gates: six symlink-privilege, two case-insensitive
filesystem, three `JACK_RYAN_M4B_FOLDER` unset, and the cover symlink case. The single warning is
the pre-existing pydub `audioop` `DeprecationWarning`.

#### Discovered consequence — NOT fixed, needs a decision

Registering four rows has a side effect on the **dev-only** sample utility. `generate_voice_samples
.py`'s ordinary mode iterates every registered voice and dispatches `kokoro` → Kokoro, **everything
else → Edge TTS**. With four Chatterbox rows registered, a bare `python generate_voice_samples.py`
now hands `chatterbox-female-1` to `edge_tts`, which raises per voice, is caught and printed as
`FAIL`, and makes the utility exit 1 instead of 0. Nothing in the application is affected — this
file is never imported by anything the app runs, and normal conversion does not go near it.

**It was deliberately left alone.** §25 lists `generate_voice_samples.py` as do-not-edit and
requires reporting before broadening scope; more decisively, the obvious fix — a Chatterbox branch
in `main()` — would break Phase 9's guard
`test_the_sample_generator_reaches_chatterbox_only_behind_its_own_flag`, which asserts the word
never appears in `main()` outside the `--chatterbox-eval` branch. Fixing it properly therefore
needs an authorized decision about that guard. **Recommended for Phase 11.**

#### Protected assets

Re-hashed before staging and again after all tests. All four **byte-identical**, still exactly four
files, still zero tracked:

| File | Bytes | SHA-256 |
|---|---|---|
| `Female-1.mp3` | 32,999,135 | `a047d77fe191c1a957d36b1e9f9af8e67756a63672686c55731b30534bb8bde2` |
| `Female-2.mp3` | 13,405,769 | `4bad0d3845199eae723aceb7a864b419fe553cd9d23799ee6390f54df08d3140` |
| `Male-1.mp3` | 2,946,239 | `6258dde294a91b0c2e965e8579aafde10e9cff48957c2138432be4c6c80165ae` |
| `Male-2.mp3` | 12,403,843 | `7b8fd74dfb262740476fba8317c0b7483a9f8b290e58c1d7e496e48b048d6ab2` |

`git ls-files files/Chatterbox-Voice-Uploads/ files/runtime-data/` returns **zero**. No source MP3,
derivative, cached conditional, manifest, evaluation WAV, model weight, runtime cache or probe venv
was staged. `git add -f` was never used and `git clean` was never run. The four Phase 9 evaluation
WAVs remain on disk, ignored and local-only.

#### Environment

**No real synthesis ran in this phase** — every engine boundary is stubbed, so nothing loaded Turbo
weights, read a maintainer recording, or reached the network. The working `.venv` was **not**
modified and still has no Chatterbox, by design. The Phase 8/9 probe environment was **not** used
and needed no real integration smoke: the automated boundaries prove the worker calls the engine's
Phase 8 contract with the right arguments. `Setup_and_Run-audiobook-creation-tool.bat` was **not**
run, CUDA was **not** used, no Mac was involved, and no Windows manual matrix was performed.

#### Not done

No version bump, merge, tag, release, packaging or branch deletion. **Phase 11 — Structural guards,
deterministic race and lifecycle testing — is NOT AUTHORIZED and has NOT started.**

---

## Previous Focus
**v0.6.0 Drop 3 (Plan 3 — shared importing and job-control foundation) — COMPLETE, APPROVED AND
CLOSED OUT. All ten phases are done; the temporary drop is retired; the branch awaits integration
review. Plan 2 is merged into `master` through pull request #3, and the Plan 3
branch `feature/0.6.0-drop3-shared-job-controls-importing` now carries the immutable importing
and job-control vocabulary, a read-only link-refusing traversal core, the imported-file manager
with its deduplication and atomic transactions, the background import coordinator with its own
cancellation, the cooperative run controller with pause/resume/cancel and one-acknowledgement
settlement, the run framing (one frozen configuration per run, a UI-neutral lock derivation,
ordered item outcomes, and Retry Failed against the exact original snapshot), the reporting layer
(typed event production that cannot claim a state the controller never reached, a stream that
refuses stale and post-terminal events, Summary/Details projections that keep commands and
tracebacks out of the Summary, a bridge to the one existing session logger, a truthful progress
contract for the existing `ProgressIndicator`, and a current-run rolling ETA that says
`Calculating…` rather than guess), and now the Tk boundary itself: `shared/job_ui.py`, whose two
compositional adapters draw all of the above through one main-thread pump, refuse every widget
touch from a worker before a widget is reached, and close without leaving a callback behind. No
production panel or launcher adopts any of it, no behaviour changed, and `version.py` is still
`0.5.1`. **The Phase 9 Windows manual matrix was run on HOME-PC by the maintainer, who attested
that every checked behaviour worked and returned an explicit verdict of APPROVED**, and the full
automated matrix was re-run against that same commit with no regression. Phase 10 has now
transferred the lasting record into `Briefing.md`, `Changelog.md` (under `[Unreleased]`),
`Decisions.md` and the master index, and retired the temporary drop. **The next action is Plan 3
integration review only** — nothing has been merged, tagged, released or bumped, and Plan 4 is
not started.**

### Phase 10 — Approved closeout and temporary-drop retirement (2026-08-10, HOME-PC)

**Result: the lasting Plan 3 record is transferred and the temporary drop is retired. This phase
changed no production code, no test code, no configuration, no packaging and no screenshot — the
entire diff is five documents plus the deletion of one temporary planning file. Plan 3 is
complete, approved and awaiting integration review; `version.py` is still `0.5.1`, nothing was
merged, tagged, released or published, and Plan 4 was not started.**

#### Entry gate

The maintainer explicitly approved the Phase 9 evidence and every accurately recorded deferral,
including the functional Windows 11 HOME-PC matrix passing by attestation, the screenshots
supporting only the recorded subset, the unrecorded exact 100%-scaling confirmation, the missing
literal harness source-tree comparison output, the repository verification corroborating that the
read-only repository-root scan mutated nothing, and the Windows 125% and live macOS deferrals to
Plan 9 — with the explicit finding that **those gaps do not require the passed matrix to be
repeated**.

Starting state, verified before any edit: branch
`feature/0.6.0-drop3-shared-job-controls-importing`; HEAD, its configured upstream and
`origin/feature/…` all exactly `9f0cf211a89efb064f6acf435b324bd8c4c1805f`; `origin/master`
unchanged at `563df9884497032e19abd4437a0e66584cd9ec12`; all ten approved phase commits ancestors
of HEAD; index and worktree clean with zero untracked files; version `0.5.1`; root
`config-template.toml` absent from worktree, index and committed tree and tracked nowhere; four
canonical documents with exact casing and no alias; four protected `don't-delete` references
present; all 22 approved screenshots byte-identical to `origin/master`; `launcher.TOOLS` exactly
six entries; and no production module importing a Plan 3 module.

#### What was transferred, and where

| Document | What it now carries |
|---|---|
| `Briefing.md` | A new Architecture entry describing all four shared modules — the immutable vocabulary and read-only non-following traversal, the coordinator with its pre-scan broad-root warning and post-scan threshold and its independent Cancel Import, the truthful cooperative controller with frozen run snapshots, UI-neutral locking, item outcomes and Retry Failed against the original snapshot, the typed reporting with stale/post-terminal rejection and the Summary that structurally cannot leak a diagnostic, and the one Tk module with its single `after` chain, thread guard, reused `ProgressIndicator`, `ACT.*` isolation and preserved native branch — plus the harness's developer-only status. The Current Version and High-Level State sections now record Drop 3 as approved and closed, **explicitly as infrastructure no user can reach**, together with the evidence gaps and the two deferrals |
| `Changelog.md` | Two entries under **`[Unreleased]`** — an *Added* entry for the foundation and a *Changed* entry for the closeout. **No v0.6.0 release heading was created.** Both state that no production tool uses any of it, that the launcher still lists six tools, and that the version is unchanged |
| `Decisions.md` | One new ADR dated 2026-08-10, in the established newest-on-top signed format, recording six lasting choices: shipping a foundation with no adopters and guarding that boundary structurally; making a false state unconstructible rather than merely unasserted; injecting every clock so the whole drop tests without a single sleep; one Tk module with one `after` chain and one guard that raises before a widget is touched; composition and reuse over inheritance and reimplementation; and recording the manual evidence with its gaps intact. **Decisions 1–55 were not reopened** and no narrow implementation detail was promoted to a permanent decision |
| `Handoff.md` | This entry. The Phase 9 evidence wording and limitations above are preserved verbatim |
| Master index | Plan 3 marked complete, approved and awaiting integration, with the closeout commit and the immediate next action |

#### The temporary drop, retired

`md-instructions/0.6.0-drop3-shared-job-controls-importing.md` (979 lines) was deleted **after**
the transfer above, and it is the **only** deleted path in this commit. `git diff --name-status
-M -C` reports exactly one `D` and no `R`. The four canonical documents and the four protected
`don't-delete` references all remain present with exact casing, and nothing was restored
afterwards.

#### Verification, run before and after the deletion

| Gate | Before deletion | After deletion |
|---|---|---|
| `test_job_ui.py` alone | **128 passed, 0 skipped, 0 warnings** | **128 passed, 0 skipped, 0 warnings** |
| Repetition — adapter suite | **128 passed × 5 consecutive runs** | — |
| Repetition — race-sensitive subset | **36 passed × 5 consecutive runs** | — |
| Repetition — Phase 4 + 5 concurrency | **302 passed × 3 consecutive runs** | — |
| Phase 1 / 2 / 3 / 4 | **355** / **91 + 6 skipped** / **144 + 2 skipped** / **129** | unchanged |
| Phase 5 / 6 / 7 / 8 | **173** / **174** / **258** / **128** | unchanged |
| Maintenance + cleanup / output-paths group | **337** / **255 + 1 skipped + 1 warning** | unchanged |
| Eight cancellation-bearing suites | **61 passed** | **61 passed** |
| `test_ui_theme.py` explicitly | **17 passed — all 17 executed** | **17 passed — all 17 executed** |
| Collection | **2,534** | **2,534** |
| Full suite | **2,521 passed, 13 skipped, 1 warning** | **2,521 passed, 13 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** | **RESULT: PASS** |
| `compileall -q scripts files/tests` | exit **0** | exit **0** |

Deleting the drop changed nothing, which is the point: the temporary plan was never referenced by
any test, gate or module. **No test was lost, deleted, skipped, xfailed, deselected or replaced,
and no new warning appeared.**

#### Skip reconciliation — 13, unchanged

`test_import_traversal.py:131` **six** (three file and three directory symlinks, `[WinError
1314]`); `test_cover_source_side.py:363` one; `test_output_paths.py:757` one;
`test_import_traversal.py:552` one (case-insensitive filesystem); `test_import_manager.py:678`
one (case-insensitive filesystem); `test_jack_ryan_final_product.py:40/:44/:64` three
(`JACK_RYAN_M4B_FOLDER` unset). `test_job_ui.py` skips nothing, and the documented Tk
root-creation transient did **not** recur. The one warning is unchanged and third-party:
`.venv\Lib\site-packages\pydub\utils.py:14` — `DeprecationWarning: 'audioop' is deprecated`.

#### Whitespace, stated precisely

Scoped to code, `git diff --cached --check -- '*.py'` exits **0** — this phase changes no Python
file at all. The broad staged check reports only the inherited structural findings this
repository has always produced, all in `Handoff.md`, whose stored blob is CRLF so every added
line reads as trailing whitespace; **the drop header's intentional two-space hard breaks are gone
from the check because the file that carried them was retired**, and the other four documents add
none. **Phase 10 introduced no non-structural whitespace defect**, and no protected document was
reformatted or normalised to quieten the check.

#### Final repository state

Branch `feature/0.6.0-drop3-shared-job-controls-importing`; start SHA
`9f0cf211a89efb064f6acf435b324bd8c4c1805f`. Worktree and index clean; `origin/master` still
`563df9884497032e19abd4437a0e66584cd9ec12`; version `0.5.1`; root `config-template.toml` still
absent; four canonical documents and four protected references intact; all 22 approved
screenshots byte-identical; `launcher.TOOLS` six entries; no production module importing a Plan 3
module; requirements, both root launchers, packaging, release code, production code, tests,
source media and runtime data byte-identical to the Phase 9 commit. **No pull request, merge,
branch deletion, version bump, tag, release, packaging or publication was performed**, and no
Plan 4 behaviour or planning work was introduced.

#### No deviations

No approved Phase 1–9 public contract was rewritten, no production panel or launcher adopted
Plan 3, no dependency was added, and no real conversion, synthesis, ffmpeg, media probe, network
call, output creation, settings write, cleanup or source mutation occurred. The Phase 9 manual
matrix was **not** repeated, no broad root or repository scan was performed, and **Windows 125%
scaling and live macOS validation were not run and remain deferred to Plan 9**.

#### Next action

**Plan 3 integration review only.** The feature branch
`feature/0.6.0-drop3-shared-job-controls-importing` is complete, approved and pushed, and the
maintainer owns the decision to merge it into `master`. **Plan 4 — TTS and Cover Image upgrades**
is the next unopened plan in the approved series map and the first that adopts Plans 2 and 3 in a
production panel; it has **not** been drafted or started and requires separate explicit maintainer
approval.

### Phase 9 — Full regression, Windows manual matrix, and approval gate (2026-08-10, HOME-PC)

**Result: an evidence phase, and it changed no code. The maintainer ran the Phase 9 Windows manual
matrix on HOME-PC using `files/tests/manual_plan3_harness.py` and returned an explicit verdict of
APPROVED — all Phase 9 Windows manual checks passed. The complete automated matrix was re-run
against the same commit and every figure is identical to the approved Phase 8 baseline: 2,534
collected, 2,521 passed, 13 skipped, 1 warning, theme 17/17, `verify.py` RESULT: PASS, compile
exit 0. No implementation deviations, no approved Phase 1–8 contract rewritten, and no production
panel adopting Plan 3. The only changed paths are this Handoff entry, the active drop's status
and baseline header, and the master index's Plan 3 status, evidence and next-action fields.**

#### Starting state, verified before anything else

Branch `feature/0.6.0-drop3-shared-job-controls-importing`; HEAD, its configured upstream and
`origin/feature/…` all exactly `bada212a8276a537c75073f0539147d689463f4a`; `origin/master`
unchanged at `563df9884497032e19abd4437a0e66584cd9ec12`; all nine approved phase commits
ancestors of HEAD. **The index and worktree were completely clean with zero untracked files** —
which matters more than usual this phase, because the maintainer had just finished a manual
session that included an import of the repository root, and a clean tree is what proves the scan
wrote nothing. Version `0.5.1`; root `config-template.toml` absent from worktree, index and tree
and tracked nowhere; four canonical documents with exact casing and no alias; four protected
`don't-delete` references present; all 22 approved screenshots byte-identical to `origin/master`;
`launcher.TOOLS` exactly six entries; 40 production modules AST-parsed and **none** importing a
Plan 3 module.

#### The maintainer's manual approval, recorded as supplied

**Verdict: APPROVED — all Phase 9 Windows manual checks passed.**

| Item | As supplied |
|---|---|
| Machine | HOME-PC |
| Operating system | Windows 11 |
| Python | 3.12.10, 64-bit |
| Repository | `C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces\MyProjects\Home-PC\Audiobook-Creation-Tool` |
| Harness | `files/tests/manual_plan3_harness.py`, launched successfully with no initialization error |
| Fixture roots | Generated beneath `C:\Users\ematthew\AppData\Local\Temp\act-plan3-harness-*`; one observed fixture generated **33 paths** |
| Attested working | Add Files and Add Folder; the imported-file listing, selection, clearing and supported-type controls; the fake-job controls and lifecycle; progress, current occurrence/stage, ETA, Summary, Details, failure reporting and completion. The maintainer confirmed the remaining manual cases passed |
| Also performed | The repository folder was selected as an import root and produced an observed **380 supported files** |

The maintainer's attestation is the complete result. It is recorded here as given and has not been
expanded, itemised per checklist step, or supplemented with invented observations.

#### What the screenshots visibly support — and what they do not

The supplied screenshots visually support **a subset** of the attestation: successful harness
startup; disposable fixture-root generation; 33 generated paths in one fixture; a 50-file import;
clearing the imported list; a completed 1/1 fake job at 100%; Summary milestones for Running,
Preparing, Converting, Finished and "1 of 1 items finished"; the repository-root import showing
380 files; an active 106/380 job at 28%; a displayed ETA of `1m 36s`; per-occurrence conversion
failure messages; and Pause and Cancel available while running.

**The screenshots do not independently prove every checklist item**, and no claim here rests on
them beyond the list above. Everything else in the manual result stands on the maintainer's
explicit attestation.

*Worth noting for its own sake:* the visible `106/380 — 28%` with an ETA of `1m 36s` is the
Phase 7 estimator and the Phase 8 adapter behaving exactly as specified — a determinate count
that is genuinely 28%, and a duration that only appeared once enough comparable samples existed.

#### The repository-root import, classified honestly

The active plan's §11 asks that manual evidence use **generated disposable fixtures only**, and
the Phase 8 report's checklist said the same. Selecting the repository folder as an import root
went **beyond that preferred boundary**. It is recorded as a deviation from the preferred test
scope rather than glossed over.

What it was not is a safety problem, and that is established by repository evidence rather than by
assertion:

- Importing is read-only by construction. An approved Phase 1 guard pins `shared/importing.py` to
  exactly two filesystem verbs — `os.scandir` and `lstat` — and forbids every writing, content-
  reading and link-following call; the coordinator touches the filesystem not at all; and
  `shared/job_ui.py` makes no filesystem call whatsoever. Nothing in that path can write.
- No processing was requested or reported. Selecting an import root fills a list; it starts no
  job, and the harness's "job" is a timed no-op that produces no output in any case.
- **`git status --short --untracked-files=all` returns nothing at all**, `git diff --name-only
  HEAD` is empty, and the index matches HEAD. Every one of the 139 tracked files is byte-identical
  to the commit, and the scan created no untracked file anywhere in the tree.
- All 22 approved screenshots remain byte-identical to `origin/master`, the four protected
  references and four canonical documents are intact, `config-template.toml` is still absent, and
  version is still `0.5.1`.
- For scale: the index holds exactly **one** file with an extension the harness catalog accepts
  (`scripts/requirements.txt`). The observed 380 therefore came almost entirely from untracked and
  ignored trees such as `.venv` — paths the repository does not record at all, which is a further
  reason the tracked tree could not have changed.

**Conclusion: the read-only repository scan caused no repository mutation.** The proof is Git's,
not the harness's.

#### Two evidence gaps, named rather than filled

1. **Exact 100%-scaling confirmation is not independently recorded.** The maintainer's environment
   details name HOME-PC, Windows 11 and Python 3.12.10 but do not state the display scaling, and
   no screenshot establishes it. The functional Windows matrix is therefore recorded as **passed**;
   the separate claim "verified at true Windows 11 100% scaling" is **not** recorded as proven.
   Plan 9 owns the full DPI matrix regardless.
2. **The literal harness source-tree before/after output was not supplied.** The harness's Record
   and Compare buttons produce a path count and an UNCHANGED/CHANGED verdict, and that console
   line did not come back with the attestation. The repository verification above is recorded as
   **corroborating** evidence of source integrity; it is not presented as the harness's own output,
   and the maintainer's passed verdict has not been converted into a fabricated console result.

Neither gap contradicts the maintainer's verdict, and neither is a reason to ask for the matrix to
be repeated.

#### Complete automated re-verification

| Gate | Result |
|---|---|
| `test_job_ui.py` alone | **128 passed, 0 skipped, 0 warnings**, ~1.0 s |
| Repetition — full adapter suite | **128 passed × 10 consecutive runs**, identical |
| Repetition — race-sensitive subset (worker, thread ownership, pump, drain, terminal, close, destroyed widget, Cancel Import) | **36 passed × 10 consecutive runs**, identical |
| Repetition — Phase 4 + Phase 5 concurrency suites | **302 passed × 5 consecutive runs**, identical |
| Phase 1 contracts and boundaries | **355 passed** |
| Phase 2 traversal | **91 passed, 6 skipped** |
| Phase 3 manager | **144 passed, 2 skipped** |
| Phase 4 coordination | **129 passed** |
| Phase 5 controller | **173 passed** |
| Phase 6 run framing | **174 passed** |
| Phase 7 reporting | **258 passed** |
| Phase 8 adapters | **128 passed** |
| Maintenance and cleanup | **337 passed** |
| Output paths group | **255 passed, 1 skipped, 1 warning** |
| Eight cancellation-bearing production suites | **61 passed**, unchanged |
| `test_ui_theme.py` explicitly | **17 passed — all 17 executed** |
| Collection | **2,534** |
| Full suite | **2,521 passed, 13 skipped, 1 warning** in 28.61 s |
| `scripts/verify.py` | **RESULT: PASS** (all five checks) |
| `python -m compileall -q scripts files/tests` | exit **0** |

Every figure equals the approved Phase 8 baseline. **No test was lost, deleted, skipped, xfailed,
deselected or replaced, and no new warning appeared.**

#### Skip reconciliation — 13, node by node, unchanged

| Node | Count | Reason |
|---|---|---|
| `test_import_traversal.py:131` | **6** | 3 file + 3 directory symlinks, `[WinError 1314]` — a required privilege is not held by this account |
| `test_cover_source_side.py:363` | 1 | file symlink, `[WinError 1314]` |
| `test_output_paths.py:757` | 1 | file symlink, `[WinError 1314]` |
| `test_import_traversal.py:552` | 1 | this filesystem is case-insensitive, so the two names are one file |
| `test_import_manager.py:678` | 1 | this filesystem is case-insensitive, so the two names are one file |
| `test_jack_ryan_final_product.py:40/:44/:64` | 3 | `JACK_RYAN_M4B_FOLDER` is unset |

Total **13**, matching the reconciliation Phase 7 corrected and Phase 8 preserved. `test_job_ui.py`
skips nothing: the Tk root opened on this host, and its module-scoped fixture would have skipped
the whole file rather than silently thinning it. **The documented Tk root-creation transient did
not recur**, so no Tk suite needed an explicit rerun beyond the one the matrix already requires.

The one warning is unchanged and third-party:
`.venv\Lib\site-packages\pydub\utils.py:14` — `DeprecationWarning: 'audioop' is deprecated and
slated for removal in Python 3.13`.

#### Whitespace, stated precisely

Before staging, with a clean tree, both forms of `git diff --check` returned **nothing at all** —
scoped to code (`-- '*.py'`) it exits **0**, and the broad form produced zero findings, because
this phase changes no code. With the documentation staged the broad check reports the inherited
structural findings this repository has always produced: `Handoff.md` is stored as a CRLF blob so
every added line reads as trailing whitespace, and the active drop's header uses markdown
two-space hard line breaks. **Phase 9 introduced no non-structural whitespace defect**, and no
protected document was reformatted or normalised to quieten the check.

#### Changed paths

| Path | Change |
|---|---|
| `md-instructions/Handoff.md` | this entry |
| `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` | status line and current-baseline header only |
| `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` | Plan 3 status, evidence and immediate-next-action fields only |

**No production code and no test code changed.** No generated artifact, no screenshot, no renamed
or deleted path. `Briefing.md`, `Changelog.md` and `Decisions.md` were deliberately not touched —
their lasting transfer belongs to Phase 10.

#### No implementation deviations

No approved Phase 1–8 public contract was rewritten. No production tool panel, launcher, TTS
engine, importing, coordination, controller, event, progress, ETA, logger, output, config,
maintenance, theme, cancellation or subprocess module changed. No dependency was added. No
conversion, synthesis, ffmpeg, media probe, network call, output creation, settings write, cleanup
or source mutation was performed, and no broad-root or repository scan was re-run by this phase.
Windows 125% scaling and live macOS validation were **not run** and remain deferred to Plan 9;
an automated Aqua-branch assertion is not a macOS pass and is not described as one.

#### Phase 10 — not started

**Phase 10 — Approved closeout and temporary-drop retirement** has not begun and needs explicit
maintainer approval. Its entry gate is exactly what this phase just produced: the maintainer's
explicit approval of the Phase 9 evidence and of every accurately recorded deferral. When
authorized it transfers the lasting record into `Briefing.md`, `Changelog.md` (under
`[Unreleased]`, with no v0.6.0 release heading) and `Decisions.md`, updates the master index to
Plan 3 complete/approved/awaiting integration, deletes **only**
`md-instructions/0.6.0-drop3-shared-job-controls-importing.md`, re-runs every gate after that
deletion, and commits and pushes the closeout — without merging, deleting a branch, bumping the
version, tagging, publishing, or beginning Plan 4.

### Phase 8 — Reusable Tk adapters and developer-only integration harness (2026-08-10, HOME-PC)

**Result: one new production module, `shared/job_ui.py` (2,197 lines), is now the only module in
Plan 3 that imports Tk — and the reason the other three provably still do not. It adds two
compositional adapters and the small components they are built from, and it decides nothing: the
manager owns the list, the coordinator owns the import, the controller owns the state, the event
stream owns which events count, the approved projections own Summary and Details, `LOCK_MATRIX`
owns what locks, `is_available` owns which buttons appear, `EtaEstimator` owns the estimate, and
`ui_theme.ProgressIndicator` owns the bar. 128 focused Tk-boundary tests plus a disposable
developer harness for the Phase 9 matrix. No approved Phase 1–7 contract was rewritten, no
production panel adopted anything, `ui_theme.py` and `logging_setup.py` are byte-identical, and
no mandatory gate was encountered.**

#### The contract-extraction gate, before any edit

| # | Contract | What the active plan and the approved source actually specify |
|---|---|---|
| A | Services to compose | `ImportedFileManager` (snapshot/count/selection/`plan`/`commit`/`remove_selected`/`clear`/`move_selected_up`/`move_selected_down`, selection restored by occurrence ID, revision moves only on a real change); `SupportedTypeCatalog` + `ImportOptions.for_catalog`; `ImportCoordinator` (`start`/`import_files`/`request_cancel`/`pump`/`confirm_pending`/`decline_pending`/`close`, owner-thread fenced, broad-root warning **before** any worker, captured-threshold confirmation after a completed scan); `ImportPoller` (a `schedule(delay_ms, cb)` / `cancel(handle)` seam shaped exactly like `after`/`after_cancel`); `JobController` + `JobSnapshot`; `ControlKind`/`LOCK_MATRIX`/`is_locked` and `JobAction`/`is_available`; `JobReporter`/`JobEventStream`/`project_summary`/`detail_lines`/`LoggerBridge`/`ProgressView`/`EtaEstimator`; `ui_theme.ProgressIndicator`; and the `ACT.*` vocabulary published **only** by the Windows branch of `apply_theme` |
| B | Adapter architecture | §6.15: composition, callbacks and small protocols. Every class *owns* a `frame` rather than *being* one; no base panel, no inheritance hierarchy, no abstract class; values captured from widgets on the main thread and handed to workers only as frozen requests |
| C | Imported-file adapter | Extended selection; imported and selected counts; Add Files / Add Folder / Move Up / Move Down / Remove / Clear; supported-type selection; include-hidden; allow-duplicates; live import status and discovered count; a **separate** Cancel Import; selection restored by occurrence ID after every rebuild; every dialog and confirmation on the main thread; completed / declined / cancelled / failed / closed / conflict all leaving the prior list untouched |
| D | Job adapter | Authoritative state and status; Pause / Resume / Cancel / Retry Failed availability; input and processing-option locking through the existing matrix; the existing `ProgressIndicator`; current stage and occurrence; ETA text; Summary and Details; warnings, failures, an explicit output location, and the final result — and none of it derived, fabricated, rounded up or logged twice |
| E | Pump and teardown | One main-thread chain; never `after`, `after_cancel`, a widget, a variable, a dialog or a style from a worker; producer order preserved; no `qsize`, no sleep, no timing guess; deterministic drain hooks; at most one scheduled callback; stale and post-terminal events inert; empty and bounded drains legal; inert after close; owned callback cancelled; destroyed root tolerated; teardown idempotent |
| F | Styling | `theme["styles"]` exists on the Windows branch only, and every entry is already `ACT.*`-namespaced. On aqua and on the classic branch there is no bundle at all, and an empty style name is precisely "draw this natively" — so the native macOS branch is preserved by construction. `ProgressIndicator` is deliberately unstyled today and must stay so |
| G | Harness | Phase 9 needs a real file dialog, a real junction refusal, a >1,000-result scan, a broad-root decline, a watchable pause, and a close during live work. None of that is reachable from a unit test, and building it during Phase 9 would mean writing code in a verification phase |
| H | Scope | Frozen: §6.15 and §6.16. Unchangeable: every Phase 1–7 public contract. Narrow internal choices: the five recorded below. Deferred to Phase 9: the manual matrix. Deferred to Plans 4–8: adoption. Deferred to Plan 9: 125%, live macOS, packaging, release |

**No unresolved omission was found and no mandatory gate was encountered.** In particular the
§6.15 styling gate was *considered and not triggered*: the existing `ACT.*` catalog already
publishes a frame, card, label, secondary label, status label, warning label, button, primary
button, danger button, checkbutton, notebook, progressbar, scrollbar, treeview, labelframe and
separator style, and the two classic Tk widgets this module needs — a `Listbox` and a `Text` —
are coloured through the sanctioned `ui_theme.style_tk_widget` roles `list` and `log`. **No
reusable style was missing, so `ui_theme.py` was not touched.**

#### Five narrow internal choices, recorded

1. **`MainThreadPump` owns the only `after` chain, and `ImportPoller` rides it.** The poller is
   composed, not replaced — it is handed `pump.schedule` and `pump.cancel`, which is exactly the
   seam Phase 4 designed for a caller that owns its own scheduling. The alternative, letting the
   poller call `root.after` directly, would have meant two outstanding Tk callbacks, and
   "at most one scheduled callback" would have become an aspiration rather than an assertion.
2. **The event stream is the job adapter's only state source.** Every state-bearing event was
   minted by Phase 7's reporter *from a controller snapshot*, so rendering the stream is
   rendering the controller — and a second source (a snapshot pushed in from a worker thread)
   would have been both racy and redundant. The consequence is recorded plainly: before any
   state event arrives the adapter draws `IDLE`, which is what an unstarted run is.
3. **`sync_selection` is public.** A click or an arrow key changes the widget and Tk fires
   `<<ListboxSelect>>`; the handler behind that binding has to be nameable so the behaviour can
   be driven in a test without simulating a mouse. Generating the virtual event is Tk's job and
   does not fire on a withdrawn root, so testing through it would have tested Tk.
4. **A confirmation nobody wired up fails closed.** If `confirm_large_result` is absent, the
   adapter declines the pending transaction and says why — mirroring the coordinator's own rule
   that an unwired broad-root warning refuses the scan. The refusal reason survives the terminal
   outcome that follows it, so the status says "needs confirmation, which is not available here"
   rather than the blander "nothing was added".
5. **Three methods are exempt from the guard-first rule, by name.** `MainThreadPump.cancel`
   flips a flag on its own token and must tolerate a stale one; `LockGroup.registered` reads a
   dictionary; `JobControlBar.availability` is arithmetic over `is_available`. None reaches a Tk
   object. Every other public method on every class opens with `self._guard.require(...)`, and a
   structural guard walks the AST to prove it.

#### What the adapters actually do

**`MainThreadPump`** — one `after` chain, two kinds of rider. *Drains* are registered once and
run on every tick in registration order; *scheduled callbacks* are one-shot and are how the
poller re-registers itself. `tick()` is public because a deterministic test needs to advance the
adapter without an event loop. `stop()` and `close()` are idempotent, cancel the outstanding
callback and leave `pending is None`; a callback already in flight when `close()` lands returns
without touching anything; a destroyed widget stops the chain rather than raising through it.

**`ImportedFileList`** — an extended-selection `Listbox` over the manager. Selection is always
occurrence IDs, never indices and never paths, so two deliberate duplicates of one path are two
independently selectable rows and a moved row is still the selected row. Move Up and Move Down
offer themselves only where the block can actually move. Remove and Clear mutate the manager and
nothing else — a test snapshots the whole fixture tree around them and requires it byte-identical.

**`ImportOptionsBar`** — the supplied catalog's types, all selected by default, any combination
representable including none; include-hidden and allow-duplicates default off. `options()` freezes
the widgets into an `ImportOptions` on the main thread, which is the only value a worker ever sees.

**`ImportStatusBar`** — the live discovered count and a Cancel Import button wired to
`coordinator.request_cancel()` and to nothing else. A test starts a real job controller alongside
a real scan, cancels the import, and requires the controller still `RUNNING` and unacknowledged.

**`ImportAdapter`** — composes those three with one coordinator and one poller. Add Files
preserves dialog order; Add Folder preserves root order; the broad-root confirmer is handed
straight to the coordinator so it fires *before* a thread exists; the threshold confirmer runs
after a completed scan and before any commit. Exactly-at the captured threshold does not ask.
Close cancels the scan, joins within the coordinator's bounded timeout, empties its queue, and
claims nothing about an indivisible `scandir` that was still running.

**`JobControlBar`, `JobStatusView`, `SummaryDetailsView`, `LockGroup`, `JobAdapter`** — every
button's availability comes from `is_available`, every lock from `is_locked`, every Summary line
from `project_summary`, every Details line from `detail_lines`, every progress value from
`ProgressView` and every ETA string from `EtaEstimator.display`. A cancelled run that reached two
of five keeps `2/5  40%` on screen; an unknown total stays indeterminate; `finish()` stops an
animation and never invents a completion. Accepted technical events are forwarded by the stream's
`LoggerBridge` and by nobody else — a test with a recording logger renders three times and finds
exactly three log calls.

#### The harness, and why it exists

`files/tests/manual_plan3_harness.py` (553 lines) generates one disposable fixture root under the
system temporary directory — natural-ordered names, nested discs, an unsupported file, a hidden
folder, a second root with a repeated child name, a same-named root elsewhere, a real NTFS
junction pointing inside the fixtures, and an optional `--large N` bulk folder — and refuses to
run against the repository, the home directory, Downloads, Documents, Desktop, a volume root or
anything `is_broad_root` classifies as broad. It then builds the *production* adapters and drives
them with a fake job: a timed no-op that obeys the real controller, stays in `PAUSE_REQUESTED`
through a deliberately indivisible first stage, acknowledges `PAUSED` at a real checkpoint,
raises the real cancellation exception, fails every third item so Retry Failed becomes reachable,
and produces no output whatsoever. Record/Compare buttons fingerprint the fixture tree so the
before/after source check Phase 9 requires is one click each. It has no launcher entry, is not
collected by pytest, is never imported by anything under `scripts/`, and is excluded from both
release archives by the packager's explicit `scripts/` scope. **It was exercised end to end
during Phase 8**: import 7 files, run to `COMPLETED_WITH_FAILURES` through a pause request, an
acknowledged pause and a resume, then a second run cancelled mid-flight to `Cancelled after 2 of
7 items.`, then closed — with the fixture digest identical before and after.

#### Six boundary guards narrowed, and eleven added

`PLAN3_MODULES` still names the three Tk-free modules and now sits beside `ADAPTER_MODULE` and
`ALL_PLAN3_MODULES`; `PRODUCTION_SOURCES` excludes the adapter, because composing the foundation
is the one thing it is for, and that it is adopted by nothing is proved separately from the
launcher and panel side. `test_the_phase_eight_adapter_module_does_not_exist_yet` became
`test_the_adapter_is_the_only_new_reusable_tk_module`; the recorded-but-not-created UI-test guard
became `test_the_single_intended_ui_test_module_is_the_one_that_exists`, still asserting
`test_import_ui.py` was never created; the dependency and clock guards now cover the adapter too;
and the shipped/not-shipped guard names `job_ui.py`, `test_job_ui.py` and the harness. Eleven new
guards prove the Tk-free core is still Tk-free, that the adapter composes rather than duplicates,
that it defines no enum and no second estimator, that it reuses the one `ProgressIndicator`, that
it constructs no thread and no queue and uses `threading` only to ask who is calling, that every
public Tk-reaching method opens with the guard, that it creates and inspects no output, that it
never logs what the bridge logged, that no module in the drop grows a universal base panel, that
every style name comes from the theme bundle rather than a literal, and that the harness is
registered nowhere.

**Two substring guards were caught and rewritten as AST checks before they could pass wrongly** —
the same lesson Phases 6 and 7 recorded. `"qsize" not in source` failed on the docstring that
explains why the module avoids it, and `"subprocess" not in harness` failed on the sentence
promising there is none. Both are now checked as attribute access and as imports.

#### One genuine defect, caught by a test rather than by review

`JobStatusView.apply` called through to `ProgressIndicator` without a destroyed-widget guard. The
shared indicator knows nothing about teardown, so a worker's last event arriving after the window
closed raised `TclError` out of an `after` callback — precisely the "no Tk traceback on close"
requirement. `test_a_destroyed_widget_tree_does_not_take_the_adapter_down` found it; the fix
checks `_alive(self.indicator.bar)` and wraps the three calls, and the same guard was added to
`finish()`.

#### Evidence

- Focused: **`test_job_ui.py` 128 passed, 0 skipped**, ~0.9 s, identical over **eight consecutive
  runs**; the race-sensitive subset (worker, thread-ownership, close-during-activity,
  destroyed-widget, Cancel Import) **19 passed over five further consecutive runs**.
- Focused Phase 1–7, all matching their approved baselines: Phase 1 contracts and boundaries
  **355 passed** (337 + 18 net new guards); Phase 2 traversal **91 passed, 6 skipped**; Phase 3
  manager **144 passed, 2 skipped**; Phase 4 coordination **129 passed**; Phase 5 controller
  **173 passed**; Phase 6 run framing **174 passed**; Phase 7 reporting **258 passed**;
  maintenance and cleanup **337 passed**; output paths **255 passed, 1 skipped, 1 warning**; the
  eight cancellation-bearing production suites **61 passed**, unchanged.
- Collection **2,534** (2,388 + 128 Phase 8 tests + 18 net new boundary guards). Full suite
  **2,521 passed, 13 skipped, 1 warning**. Theme suite **17/17 executed** and the documented Tk
  root-creation transient did **not** recur. `verify.py` **RESULT: PASS**. `compileall` exit 0.
- **The thirteen skips are unchanged and Phase 8 added none.** Node by node:
  `test_import_traversal.py:131` six (three file and three directory symlinks, `[WinError 1314]`),
  `test_cover_source_side.py:363` one, `test_output_paths.py:757` one,
  `test_import_traversal.py:552` one, `test_import_manager.py:678` one, and
  `test_jack_ryan_final_product.py:40/:44/:64` three. `test_job_ui.py` skips nothing: the Tk root
  opened on this host, and the module-scoped fixture would have skipped the whole file rather
  than silently thinning it.
- The one warning is unchanged and third-party:
  `.venv\Lib\site-packages\pydub\utils.py:14` — `DeprecationWarning: 'audioop' is deprecated`.
- **`git diff --check`, stated precisely.** Restricted to code (`--cached --check -- '*.py'`) it
  exits **0**, and with only the four code files staged the broad check reported **nothing at
  all**. The staged markdown adds the inherited structural findings this repository has always
  produced: `Handoff.md` is stored as a CRLF blob so every added line reads as trailing
  whitespace, and the drop header uses markdown two-space hard line breaks. **Phase 8 introduced
  no non-structural whitespace defect**, and no document was reformatted to quieten the check.
- **Automated Tk ran on this host. The Phase 9 Windows manual matrix did not.** Windows 125%
  scaling and live macOS remain not run and deferred, and an automated Aqua-branch assertion is
  not a macOS pass.

#### Changed paths

| Path | Change |
|---|---|
| `scripts/Universal/shared/job_ui.py` | **added, 2,197 lines** — the only production change |
| `files/tests/test_job_ui.py` | **added, 2,035 lines — 128 tests** |
| `files/tests/manual_plan3_harness.py` | **added, 553 lines** — developer-only, not collected |
| `files/tests/test_plan3_boundaries.py` | modified, **+320 / −18** → 1,442 lines, 100 → 118 tests |
| `md-instructions/Handoff.md` | this entry |
| `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` | status and baseline header only |
| `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` | Plan 3 status, evidence and next action only |

No generated artifact. No screenshot. No renamed or deleted path.

#### Repository state

Branch `feature/0.6.0-drop3-shared-job-controls-importing`; start SHA
`b922102c73992ca6edce90899f8b60fedd76990f`, confirmed equal to its upstream and to the origin
feature branch before any edit, with a clean worktree and no untracked files, and all eight
approved phase commits ancestors of HEAD. `origin/master` unchanged at
`563df9884497032e19abd4437a0e66584cd9ec12`. Version `0.5.1`. Root `config-template.toml` absent
from the worktree, the index and the tree, and tracked nowhere. Four canonical documents with
exact casing and no alias; four protected `don't-delete` references present; **all 22 approved
Plan 1/2 screenshots byte-identical to `origin/master`**. Byte-identical to the Phase 7 commit:
`cancellation.py`, `importing.py`, `import_coordination.py`, `job_control.py`, `output_paths.py`,
`maintenance.py`, `logging_setup.py`, `ui_theme.py`, `preferences_ui.py`, `subprocess_utils.py`,
`config.py`, `version.py`, `release.py`, `settings.py`, `bootstrap.py`, `launcher.py`,
`config.toml`, `requirements.txt`, `verify.py`, both root launchers, `Briefing.md`,
`Changelog.md`, `Decisions.md`, every production tool panel and TTS module, and every approved
Phase 1–7 test file except the boundary guards this phase was authorized to extend.
`launcher.TOOLS` still holds exactly six entries and no production module names a Plan 3 module.

#### Phase 9 — not started

**Phase 9 — full regression, Windows manual matrix, and approval gate** has not begun and needs
explicit maintainer approval. The exact Windows steps it requires are listed in the Phase 8
completion report and are summarised here: run the harness from the repository root on HOME-PC at
true Windows 11 100% scaling, recording OS, scaling, Python/venv, commit SHA and fixture root;
record the source tree; then walk Add Files ordering and type combinations, Add Folder
direct-files-before-children natural order, several roots including same-named ones, extended
selection with move/remove/clear, duplicate suppression and the explicit override, hidden folders
off and on, the NTFS junction being refused, a broad-root warning declined *before* any scan, a
generated >1,000-result scan declined and then accepted, the live count with Cancel Import
leaving the prior list unchanged, frozen inputs and lock state during a run, a pause requested
during the indivisible stage followed by an acknowledged pause, resume and cancel-while-paused,
Summary and Details, progress and the ETA fallback, failure collection and the failed-only retry
request, and closing the window while a worker is still running; then compare the source tree and
confirm it is unchanged. Windows 125% and live macOS stay recorded as not run.

### Phase 7 — Typed events, Summary/Details, progress, and rolling ETA (2026-08-10, HOME-PC)

**Result: `shared/job_control.py` gained the reporting layer — `JobReporter` produces the typed
events, `JobEventStream` decides which of them belong to the run at all, `summary_lines` and
`detail_lines` project the two views a person reads, `LoggerBridge` feeds the technical ones to
the session logger this application already opens, `ProgressTracker` says what a progress bar may
honestly show, and `EtaEstimator` answers "how much longer" — or, far more often, `Calculating…`.
258 focused tests, all pure: an injected clock, a list for a queue, a recorder for a logger, and
no display, no disk, no process and no real workload anywhere. The production change is
`job_control.py` alone, +1,037/−7, and all seven deleted lines are module-docstring lines
rewritten in place. No mandatory gate was encountered and no approved Phase 1–6 contract was
rewritten.**

#### The contract-extraction gate, before any edit

| # | Contract | What the active plan and the approved source actually specify |
|---|---|---|
| A | Event vocabulary | `JobEventKind` has been frozen at **eleven** members since Phase 1, and `JobEvent` at **thirteen** fields. Per-kind required payloads are already enforced in `_require_payload`; the timestamp is injected, finite and non-negative; `message` is display-safe and single-line, `detail` unrestricted; `TERMINAL_EVENT_KINDS` = {`COMPLETED`, `CANCELLED`}. **Phase 7 added no kind, no field, no severity system and no parallel event type** — it only produces and consumes what Phase 1 froze |
| B | Lifecycle and ordering | Production is owned by `JobReporter`; `sequence` is the ordering authority; run binding is `run_id`; occurrence binding is `item_id` ∈ the run's `item_ids`; staleness means "not this run", never a wall-clock interval; a run ends exactly once |
| C | Summary vs Details | §6.12's two lists, turned into `SUMMARY_KINDS` and its complement — see the inclusion matrix below |
| D | Progress | `ui_theme.ProgressIndicator` already has exactly three presentations (`update`, `set_indeterminate`, `reset`), so `ProgressMode` has exactly three members and Phase 8 maps one onto the other. No second progress implementation |
| E | Existing logger | `logging_setup.get_logger()` takes no argument, returns the `audiobook_tool` logger at DEBUG with one `FileHandler`, opens the session file **on first call**, and prunes to `logging.max_sessions`. The bridge must therefore resolve it *lazily* and create nothing |
| F | ETA | §6.13 in full: injected monotonic clock, comparable completed units only, current run only, current work category only, three-sample minimum, twenty-sample rolling window, paused time excluded, invalid units excluded, media probes never samples, no persistence, central formatting, `Calculating…` for everything unreliable |
| G | Scope | Frozen: §6.12 and §6.13. Unchangeable: every Phase 1–6 public contract. Narrow internal choices: the four recorded below. Deferred to Phase 8: applying any of it to a real widget |

**No unresolved omission was found, and no mandatory gate was encountered.** The plan resolved
every contract Phase 7 needed. Nothing was invented to fill a gap: in particular the plan defines
no retry lineage, so none was added, and it prescribes no public logger-level mapping, so the one
used is internal and is *not* encoded in the event vocabulary.

#### Four narrow internal choices, recorded

1. **Level mapping.** `TECHNICAL_DETAIL` → `debug`, `WARNING` → `warning`, `FAILURE` → `error`.
   The repository already writes `warning`, `exception`, `debug` and `info`; `error` is the
   standard level for a failure recorded outside an `except` block. Deliberately a private
   `LoggerBridge.LEVELS` mapping rather than a severity field on `JobEvent`, so the public
   vocabulary did not grow to express an implementation detail. Milestones are **not** forwarded:
   they are already on screen, and duplicating them would bury the diagnostics the log exists for.
2. **`state_message`.** One concise display-safe sentence per state, in one place, because two
   surfaces that each write their own "Paused" eventually disagree. §6.10's `Pause requested` is
   reproduced word for word.
3. **Details timestamps are elapsed, not wall-clock.** The clock is injected and monotonic, so it
   has no calendar meaning; `[+1.500s]` is measured from the first event of the projection.
   Printing a fabricated time of day beside a real diagnostic would be the one lie in the view
   whose whole job is fidelity.
4. **Two drain seams instead of a `queue` import.** `drain(iterable)` and `pump(pull)`, where
   `pull` returns `None` when empty. Phase 8's adapter wraps `get_nowait` and its empty signal;
   this module stays free of `queue`, never blocks, and never asks how many events are waiting.

#### What the reporting layer does, and why

**A state is never asserted, only copied.** Every state-bearing event is minted from a
`JobSnapshot` the Phase 5 controller handed out — `state_changed(snapshot)`,
`completed(snapshot)`, `cancelled(snapshot)`. That is what makes the two dangerous claims
*unconstructible* rather than merely checked: `PAUSED` cannot be reported while an indivisible
stage is still running, because the controller only reaches `PAUSED` on worker acknowledgement
and there is no other way to obtain the snapshot; and `CANCELLED` cannot be reported before
acknowledgement, because `JobSnapshot.__post_init__` refuses to construct a cancelled snapshot
without it. `completed` additionally refuses any state that is not one of the three endings, and
`cancelled` refuses anything but `CANCELLED`. A snapshot from another run is refused outright.

**Ordering and the one lock.** `sequence` is allocated atomically under a plain `threading.Lock`
that covers the counter and nothing else — neither the caller's clock nor the caller's publisher
is invoked while it is held, because §5.4 forbids holding a lock across user code, and a boundary
guard now proves it by walking the `with` block in `_emit`. One consequence is stated in the code
rather than hidden: a reporter shared by several threads may hand its queue two events in the
opposite order to their numbers, and the stream then refuses the later arrival as `OUT_OF_ORDER`
rather than filing it in the wrong place. One run reports from one producer.

**The stream is the single gate.** Four questions can only be answered against a run rather than
against an event — is it ours, does it name an occurrence we have, has the run already ended, and
where does it go in the order — so `JobEventStream` answers all four once and every consumer
downstream sees the same story. Its verdicts are `ACCEPTED`, `STALE_RUN`, `UNKNOWN_ITEM`,
`AFTER_TERMINAL`, `DUPLICATE_TERMINAL` and `OUT_OF_ORDER`. **A rejected event is completely
inert**: not stored in the history, not projected into Summary or Details, and not forwarded to
the logger — tested directly for both the stale-run and post-terminal cases. It is kept only in
`rejected`, in memory, so a developer can see what was turned away and why. Deliberate duplicates
of one path stay independently reportable throughout, because every binding is on occurrence id
and never on a path — proved end to end with two occurrences of the same file.

**Summary versus Details.** The inclusion matrix, built from §6.12:

| In Summary | Out of Summary | In Details |
|---|---|---|
| state and stage changes; import count; concise warnings; concise failures; an explicitly supplied output location; the terminal result | every per-file diagnostic; raw commands; traceback text; detailed subprocess output; exception diagnostics | every accepted event, timestamped, with its diagnostics kept whole and multi-line detail indented rather than flattened |

The anti-flooding rule is structural rather than a heuristic: `_summary_line` **never reads the
`detail` field at all**, so a command or a traceback cannot reach the Summary by accident. Current
stage and current occurrence are still "supported" by the Summary, but as *state* on `SummaryView`
rather than as history — appending them two hundred times is exactly the flooding §6.12 forbids.
A test drives two hundred files' worth of churn (603 events) through the projection and gets three
Summary lines and 603 Details lines.

**The logger bridge creates nothing.** It asks `logging_setup.get_logger()` for the one logger the
launcher already opens, and only when it first has something to forward — constructing a bridge
must never be what opens a log file, and a test proves it by making the resolver explode. There is
no second logger, handler, file, formatter, retention policy or telemetry path; a guard asserts by
name that none of `logging_setup`'s vocabulary appears in `job_control.py`, and `logging_setup.py`
itself is byte-identical to the Phase 6 commit. The stdlib `logging` module stays forbidden.

**Progress is truthful or it is indeterminate.** Two rules do all the work. Progress does not go
backwards *within one scope* (one stage, one total), so a late or duplicated report cannot make a
run look like it lost ground; when the total itself changes the scope changed, and the new pair is
adopted rather than compared across. And **an ending changes no counter**: a run that succeeded
after reporting three of five files shows three of five, because "it finished" and "it did all of
it" are different claims and only the events can make the second one. An unknown total stays
`INDETERMINATE` and is never turned into one-of-one. A new stage starts the count again.
`ProgressView` is a frozen value with no widget in it; `ProgressMode`'s three members are exactly
the three presentations `ProgressIndicator` already has, and Phase 7 instantiates none of them.

**The ETA.** `EtaEstimator` measures with the injected clock between `begin(category)` and
`complete()`, keeps a `deque(maxlen=20)` of comparable samples, needs three before it will say
anything, and discards every unit that did not honestly complete. `PAUSED` starts an excluded
interval and `RUNNING` closes it, so repeated pause/resume cycles are all subtracted to the
second — while `PAUSE_REQUESTED` deliberately does **not** stop the clock, because §6.10 says the
stage keeps running and counting that as a pause would understate every later estimate. A changed
work category clears the history rather than averaging incomparable units. A new run or a retry
gets a new estimator and there is nothing to inherit, because nothing is stored anywhere. A
backwards or non-finite clock costs that one sample and leaves the earlier ones intact. It returns
`Calculating…` for an unknown total, too few samples, a changed category, a paused run, a
terminal run, and a question asked about a different run. `format_duration` is the single place a
length of time becomes text, and a guard proves it is called from exactly one function.

#### Deviations

**None.** No approved Phase 1–6 contract was rewritten. `JobEventKind` still has eleven members
and `JobEvent` still has its thirteen Phase 1 fields, checked by name in two suites.
`cancellation.py`, `importing.py`, `import_coordination.py`, `output_paths.py`, `maintenance.py`,
`logging_setup.py`, `ui_theme.py` and **every approved Phase 1–6 test file except the boundary
guards** are byte-identical to the Phase 6 commit. `git diff --numstat` reports **zero deleted
lines** in `job_control.py`'s existing sections; the only seven deletions are module-docstring
lines rewritten in place, because the docstring said this module contains "no ETA arithmetic" and
that had to stop being true before it stopped being written.

*Six boundary guards were narrowed rather than weakened, each recorded here:* the controller's
lock count is now checked **per class** (a stronger statement than the module-wide count it
replaced, plus a new guard that no third class holds a lock, plus a new guard that `_emit` calls
neither the clock nor the publisher under its lock); `shared.logging_setup` is permitted in
`job_control.py` only, while the stdlib `logging` import stays forbidden everywhere; `pump` is
exempted for `job_control.py` for exactly the reason `request_cancel` already was — two subsystems
legitimately drain their own queues; the Phase 7 names moved off the "later phase" list and onto a
positive `_PHASE_SEVEN_NAMES` list still forbidden in both importing modules; and the ETA guard
split into one half that still forbids **all three** modules from reading a clock of their own and
one half that keeps `Calculating…` and every estimator concept out of the importing modules,
checked as defined names rather than as substrings.

#### Evidence

- Focused: Phase 1 contracts and boundaries **337 passed** (328 + 9 net new guards); Phase 2
  traversal **91 passed, 6 skipped**; Phase 3 manager **144 passed, 2 skipped**; Phase 4
  coordination **129 passed**; Phase 5 controller **173 passed**; Phase 6 run framing **174
  passed**; **Phase 7 reporting 258 passed, 0 skipped**, stable over **eight consecutive runs**
  at 0.30 s; maintenance and cleanup **337 passed**; output paths **255 passed, 1 skipped, 1
  warning**; the eight cancellation-bearing production suites **61 passed**, unchanged.
- The eight cancellation-bearing suites, named once so the figure can be reproduced:
  `test_maker_custom_destination.py` (31), `test_prototype_regression.py` (12),
  `test_batch_convert_folders.py` (5), `test_m4b_maker_smoke.py` (4), `test_mp3_tool_smoke.py`
  (3), `test_kokoro_timing_wiring.py` (3), `test_tts_smoke.py` (2),
  `test_m4b_converter_smoke.py` (1) = **61**.
- Collection **2,388** (2,121 + 258 new Phase 7 tests + 9 net new boundary guards). Full suite
  **2,375 passed, 13 skipped, 1 warning**. Theme suite **17/17 executed**; the documented Tk
  transient did not recur in any run. `scripts/verify.py` **RESULT: PASS** (re-run after the
  documentation edits). Compile gate exit 0.
- **The 13 skips, reconciled node by node — and a documentation correction.** The prose in the
  Phase 6 entry said "five Phase 2 at `test_import_traversal.py:131`"; the actual number is
  **six**, which is the whole of the arithmetic gap the Phase 7 kickoff flagged (the categories
  summed to 12 against a real 13). No test was lost and no new skip appeared: the label was wrong
  by one and is corrected here. The exact accounting, unchanged before and after Phase 7:

| Node | Count | Reason |
|---|---|---|
| `test_import_traversal.py:131` | **6** | three file symlinks and three directory symlinks, all `[WinError 1314]` — privilege not held |
| `test_cover_source_side.py:363` | 1 | file symlink, `[WinError 1314]` |
| `test_output_paths.py:757` | 1 | file symlink, `OSError` |
| `test_import_traversal.py:552` | 1 | this filesystem is case-insensitive |
| `test_import_manager.py:678` | 1 | this filesystem is case-insensitive |
| `test_jack_ryan_final_product.py:40`, `:44`, `:64` | 3 | `JACK_RYAN_M4B_FOLDER` fixture not set |
| **Total** | **13** | |

- **The 1 warning**, unchanged and third-party: `.venv\Lib\site-packages\pydub\utils.py:14` —
  `DeprecationWarning: 'audioop' is deprecated and slated for removal in Python 3.13`.
- **Whitespace, stated precisely.** Scoped to code, `git diff --check -- '*.py'` exits **0**. One
  genuine defect was introduced and fixed rather than tolerated: moving the Phase 7 block below
  the module's local validators (necessary, because `IDLE_PROGRESS` is evaluated at import and
  needs them) left a blank line at end of file, which the check caught and which is gone. The
  broad check's remaining findings are the established inherited ones — `Handoff.md` is stored as
  a CRLF blob so every added line reads as trailing whitespace, and the drop header uses markdown
  two-space hard line breaks. **Phase 7 introduced no new non-structural whitespace**, and no file
  was reformatted to quieten the check. Note also that `job_control.py`'s worktree copy is CRLF
  while its blob is LF; the block move was written with `newline=""` throughout, so no
  line-ending change was recorded.
- No test sleeps and none waits on a wall clock. The clock is injected everywhere; the one
  genuinely concurrent test (four threads numbering a hundred events) uses a `threading.Barrier`
  and bounded five-second joins that assert the thread finished.

#### Repository state

Branch `feature/0.6.0-drop3-shared-job-controls-importing`, start SHA
`f3afa9c168741355499bb9e4ee920973a87333ce` (approved Phase 6), confirmed equal to its upstream
and to `origin/feature/...` before any edit; `origin/master` still
`563df9884497032e19abd4437a0e66584cd9ec12`; worktree and index clean with no untracked files at
the start. All seven approved phase commits confirmed ancestors of HEAD. Version `0.5.1`. Root
`config-template.toml` absent from the worktree, the index and the committed tree, and tracked
nowhere. The four canonical documents keep their exact casing with no alias, the four protected
`don't-delete` references are intact, and all **22** approved screenshots are byte-identical to
`origin/master`. No production panel or launcher imports or names any Plan 3 module. No
dependency was added — a new guard proves every import in all three Plan 3 modules is either the
standard library or `shared`. `shared/job_ui.py` and `files/tests/test_job_ui.py` still do not
exist; Phase 8 owns them.

#### Changed paths

| Path | Change |
|---|---|
| `scripts/Universal/shared/job_control.py` | **+1,037 / −7** → 2,723 lines (the seven are docstring lines rewritten in place) |
| `files/tests/test_job_events_eta.py` | **added, 2,084 lines — 258 tests**, none skipped |
| `files/tests/test_plan3_boundaries.py` | **+205 / −22** → 1,140 lines |
| `md-instructions/Handoff.md` | this entry |
| `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` | status/baseline header only |
| `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` | Plan 3 status, evidence and next action only |

No generated artifact was committed.

#### Next

**Phase 8 — Reusable Tk adapters and developer-only integration harness. Not started; it
requires separate explicit maintainer approval.** It creates `shared/job_ui.py` and
`files/tests/test_job_ui.py` (the single intended UI-test filename; `test_import_ui.py` will not
be created), and brings its own boundaries: every widget mutation on the Tk/main thread with
thread ids recorded, queue-only worker communication, close-during-scan and close-during-job
without a traceback or a lingering `after` callback, `ACT.*` style isolation with the native
macOS branch preserved, reuse of the existing `ProgressIndicator` rather than a new widget, and a
developer harness with no launcher entry, no real output and no seventh production tool.

### Phase 6 — Frozen snapshots, locking contract, failures, and Retry Failed (2026-08-09, HOME-PC)

**Result: `shared/job_control.py` gained the frame around a run — `capture_run` freezes one
configuration at the moment a run is accepted, `is_locked`/`is_available` derive what the UI may
still touch, and `RunResult` settles what became of every occurrence, from which Retry Failed
re-runs only the retryable failures against that same snapshot. 174 focused tests, all pure. No
mandatory gate was encountered, and the risk gate was honoured by omission: no Phase 6 type
carries an output descriptor, so Plan 2 keeps sole ownership of placement.**

#### The contract-extraction gate, before any edit

| # | Contract | What the active plan actually specifies |
|---|---|---|
| 1 | `RunSnapshot` fields | Already frozen in Phase 1 (§6.11): `snapshot_id`, `files`, `catalog`, `import_options`, `effective_config`, `tool_options`, `created_at`. Phase 6 adds the *capture* half |
| 2 | Lock matrix | **No per-panel matrix exists.** §8 task 2 asks for a *UI-neutral lock-state derivation*; §6.11 names six kinds of control |
| 3 | Item outcome vocabulary | The plan defines `FailureRecord`/`FailureLog` and the run's disposition; no per-item enum existed |
| 4 | `RetryRequest` | Already complete in Phase 1: `snapshot` + `item_ids`, with `from_failures`. **No lineage fields are defined**, so none were invented |
| 5 | Adapter or specimen | **None authorized.** Phase 8 owns adapters; §6.11 says panels do not adopt until their later plans |
| 6 | Reuse unchanged | Phase 1 `JobState`, `LEGAL_TRANSITIONS`, `TERMINAL_STATES`, `INPUT_LOCKED_STATES`, `RunSnapshot`, `FailureRecord`, `FailureLog`, `RetryRequest`; every Phase 5 controller semantic |

**One kickoff difference, recorded.** The kickoff asked for an `INPUT_LOCKED_DURING_RUN` matrix
"for every applicable panel". **No such symbol exists anywhere in the plan or the repository** —
I searched every tracked `.py` and `.md`. §8 task 2 asks for a UI-neutral derivation, and §5.3
forbids any production panel from adopting this foundation at all, so a table of panel and widget
names would be a table of names nothing may use, drifting the moment a panel was redesigned. The
matrix is therefore keyed on the six control **kinds** §6.11 actually names, and its states are
derived from the Phase 1 frozen set rather than restated beside it. No panel field, failure kind,
retry policy or snapshot property was invented. The master index already recorded this shape at
Phase 5 closeout, and both documents now agree.

#### The RunSnapshot contract and how it is deeply immutable

Deep immutability is not one frozen dataclass with mutable children. Each field earns it
separately: `files` is Phase 3's already-immutable `ImportedFileSnapshot` of frozen occurrences;
`catalog` and `import_options` are frozen dataclasses of `frozenset`s; `effective_config` is
Plan 2's captured value; and `tool_options` goes through Phase 1's `freeze_options`, which
deep-copies lists into tuples and dicts into read-only mappings and **refuses** anything it
cannot copy into a value — a widget, a variable, a callable, a thread, an open file, a mutable
dataclass, a reference cycle. A test edits a caller's nested dictionary and list after capture
and finds the snapshot unmoved.

`capture_run` is duck-typed on `files`: it takes an `ImportedFileSnapshot` or anything offering
`snapshot()`, which the imported-file manager does. That deliberately avoids giving the job
module an import to reach into — the beginning of a second manager.

#### One configuration per run

Proved by attack rather than assertion. After capture: the caller's list and nested dictionary
are mutated; the imported-file manager is reordered, has rows removed and is cleared entirely;
and `config.get_effective` is monkeypatched to raise if anything ever calls it again. The run
still reports the three occurrences it was accepted with, in the order it was given them, with
the threshold it captured — and the retry built from it does too.

#### The lock derivation

`ControlKind` has exactly six members, each traceable to one phrase of §6.11: imported input,
processing option, job control, log view, progress/status, Open Output. `LOCK_MATRIX` maps every
one of them — a kind that is never locked maps to an empty set rather than being absent, because
"absent" and "never locked" must not look the same. Inputs and processing options are locked in
exactly `INPUT_LOCKED_STATES`, *derived* from the Phase 1 frozen set so the two cannot disagree;
everything else is never locked. Availability is separate from locking: `is_available` answers
when Pause, Resume, Cancel and Retry Failed are meaningful, read straight off the transition
table so an action is never offered for a move the controller would refuse, and Retry Failed
additionally requires a retryable failure (§6.14). All fifty-four lock cells and all forty-five
action cells are exercised.

#### Item failure versus job failure

`RunResult.settle` derives one terminal disposition, in an order that is the meaning: a
cancelled run wins outright; then a fatal, item-less `FailureRecord` means the run itself broke
(`FAILED`); then any failed item means the orchestration finished but lost something
(`COMPLETED_WITH_FAILURES`, which is what makes Retry Failed possible); otherwise `SUCCEEDED`.
**An item failure can never force `FAILED`** — a structural guard asserts that `RunResult` calls
no controller method at all, so the authoritative Phase 5 transition mechanism is never bypassed.
Items a cancelled run never reached report `NOT_ATTEMPTED`; they are not fabricated into failures.

Outcomes are *derived* from the snapshot and the failure log rather than assembled by a caller,
so an outcome cannot drift out of step with the records it summarises, contradictions are
unconstructible, deliberate duplicates stay distinct (everything is keyed on occurrence id, never
a path), and the counts cannot disagree with the list they count.

#### Retry Failed

`RunResult.retry()` returns Phase 1's `RetryRequest` holding the **exact original snapshot
object** — tests assert identity, not equality. It selects all and only retryable failures, in
the order they failed regardless of the order asked for, so the same result always yields the
same request. It excludes successes, non-retryable failures, unattempted items and unknown ids;
refuses duplicates, an empty selection and a foreign snapshot; mutates nothing; and reads nothing
live. The plan defines no retry lineage beyond that snapshot identity and the ordered ids, so
none was invented.

#### Deviations

**None.** No Phase 1–5 contract changed. `cancellation.py`, `importing.py`,
`import_coordination.py`, `output_paths.py`, `maintenance.py` and **every approved Phase 1–5 test
file** are byte-identical to the Phase 5 commit; the only two deleted code lines in this phase are
a module docstring header and one test-list line, both rewritten in place.

#### Evidence

- Focused: Phase 1 contracts and boundaries **328 passed**; Phase 2 traversal **91 passed, 6
  skipped**; Phase 3 manager **144 passed, 2 skipped**; Phase 4 coordination **129 passed**;
  Phase 5 controller **173 passed**; Phase 6 run framing **174 passed**; maintenance and cleanup
  **337 passed**; output paths **255 passed, 1 skipped, 1 warning**; the eight
  cancellation-bearing production suites **61 passed**, unchanged.
- Collection **2,121** (1,943 + 174 new tests + 4 net new boundary guards). Full suite **2,108
  passed, 13 skipped, 1 warning**. Theme suite **17/17 executed**; the documented Tk transient did
  not recur. `scripts/verify.py` **RESULT: PASS**. Compile gate exit 0.
- **Whitespace.** With only the three source files staged, `git diff --cached --check` reported
  **nothing at all**, and `-- '*.py'` exits 0. Every finding in the broad check comes from the
  documentation edits and is inherited: `Handoff.md`'s stored blob is CRLF, so every added line
  ends in a carriage return, and the drop header uses markdown two-space hard line breaks. No
  file was reformatted to make the check quieter.
- The 13 skips are unchanged from the Phase 5 baseline — two Windows file-symlink privilege
  skips, **three** `JACK_RYAN_M4B_FOLDER` fixture skips, five Phase 2 symlink skips, and one
  Phase 2 and one Phase 3 case-insensitive-filesystem skip. Phase 6 added none: all 174 of its
  tests are pure and run everywhere.
- No test sleeps, starts a thread, opens a display, reads the repository or creates an output.
  The few filesystem-shaped values are named under `tmp_path` and never opened, and one test
  asserts the temporary directory is byte-for-byte unchanged after a whole run is described.

### Phase 5 — Cooperative job state, pause, resume, and cancel (2026-08-09, HOME-PC)

**Result: `shared/job_control.py` gained the object that owns a run — `JobController` and its
immutable `JobSnapshot` — and `shared/cancellation.py` gained exactly one additive predicate.
Pause and cancel are cooperative requests honoured at a condition-based checkpoint; a run is
reported cancelled only after a worker actually acknowledged it; exactly one terminal result can
win. The compatibility gate was **not encountered**: both pre-existing public names keep their
signatures and behaviour, no line was deleted from that file, and all eight existing callers pass
unchanged. 173 focused tests, no sleeps, stable over eight consecutive runs.**

#### The compatibility gate: not encountered

Before touching `shared/cancellation.py` I inventoried its entire public surface and every
caller:

| Public name | Kind | Preserved |
|---|---|---|
| `CancelCheck` | `Optional[Callable[[], bool]]` alias | unchanged |
| `ConversionCancelled` | `Exception` subclass | unchanged, still directly under `Exception` |
| `raise_if_cancelled(cancel_check, message="Cancelled.")` | function | unchanged, byte for byte |

Callers: six production modules (`m4b_maker.py`, `m4b_metadata_editor.py`, `mp3_tool.py`,
`epub2tts_gui.py`, `epub2tts_edge.py`, `kokoro_synth.py`) and two test modules
(`test_prototype_regression.py`, `test_plan3_boundaries.py`). Their suites were run **before**
any edit as the recorded baseline — 61 passed, 1 warning — and again afterwards: **identical**.

The change is additive only. `git diff` on that file shows **zero deleted lines**; the single
addition is `is_cancelled(cancel_check)`, the non-raising counterpart of `raise_if_cancelled`
with the same `None`-tolerant rule. It closes a real gap rather than inventing one: the
controller must *ask* whether cancellation was requested while deciding whether to keep a paused
worker waiting, and `batch_convert.py` (twice) and `kokoro_synth.py` already open-code the exact
same test. Those three callers were deliberately **not** rewired — Phase 5 keeps production
workers unchanged — so they are simply available to adopt it later.

**One kickoff difference, recorded.** The Phase 5 kickoff listed `CancellationController` among
the existing public names to preserve. No such name has ever existed in this repository — the
module has only ever defined the three above — and §8 of the active drop names only
`ConversionCancelled` and `raise_if_cancelled`. The active drop is authoritative, so those are
what was preserved, and nothing was invented to satisfy a name that was never there.

#### State-transition semantics

The Phase 1 table is unchanged and is now *enforced* rather than merely published. Exactly one
method assigns the state, it calls `require_legal_transition` first, and a structural test
asserts by `ast` that `_state` is assigned in only `__init__` and `_set_locked` — so an illegal
move cannot reach the attribute by any path, including one a later phase adds. A parametrised
test drives the controller into each of the nine states and attempts all nine successors, all
eighty-one pairs, through that same authority.

Commands and transitions are deliberately different things. `start()` is strict: starting twice,
or starting a finished run, raises `IllegalJobTransition`. Pause, resume and cancel are
**buttons**, and a button pressed where it means nothing is inert rather than explosive — pausing
an idle run, resuming a running one, or pausing after cancel has been requested each return the
current snapshot and move nothing, including the revision. The revision advances only on a real
observable change, so a no-op cannot invalidate a snapshot another part of the UI is holding.

#### Pause, resume, and the checkpoint

`request_pause()` reaches `PAUSE_REQUESTED` and stops there. Only the worker, arriving at
`checkpoint()`, can make it `PAUSED` — which is what makes the UI's "Pause requested" text
truthful during an indivisible stage. A test parks a worker inside a simulated indivisible stage,
requests the pause, asserts the state stays `PAUSE_REQUESTED`, then releases the stage and
watches the acknowledgement arrive.

`checkpoint()` returns immediately while running, waits on a `threading.Condition` while paused,
and raises while cancelled. The wait releases the lock, so a snapshot can still be read and a
resume or cancel still delivered while the worker sleeps. **No busy-spin, proved rather than
asserted:** one test wraps the controller's own `Condition.wait` and asserts it was entered
exactly once with no timeout argument — woken, not polled — and a structural guard rejects any
`wait(...)` call in the module that carries one. Every wake re-checks from the top, so a spurious
notification simply waits again and a cancel arriving mid-pause is honoured on the next pass.

#### Cancellation and acknowledgement

Cancel outranks pause and is checked first at every checkpoint. Requested before the run starts,
the flag is recorded while the state stays `IDLE` — there is nothing running to cancel yet — and
the first checkpoint after `start()` honours it. Requested after the run ended it does nothing at
all, because a finished run must not begin describing itself as cancelled.

**Requesting a cancellation is never an acknowledgement.** The acknowledgement is recorded only
where a worker actually observes it, at most once per run, and repeated checkpoints re-raise
without re-acknowledging or moving the revision. `finish_cancelled()` refuses outright if no
checkpoint ever observed the cancellation, and `JobSnapshot` refuses to be constructed in the
`CANCELLED` state without one — so "cancelled" means "it has actually stopped", enforced in two
independent places rather than trusted.

A run that genuinely finished before its next checkpoint reports `SUCCEEDED` with
`cancel_requested` still true and `cancel_acknowledged` false. That is the honest outcome and the
Phase 1 table always allowed it.

#### Terminal integrity and concurrency ownership

Every terminal state maps to an empty successor set, so the second settle attempt raises rather
than replacing the first — completed-then-failed, failed-then-completed and
cancelled-then-completed are all impossible by table lookup, not by a special case. A race test
starts two threads on a barrier, one settling success and one settling cancellation, and asserts
exactly one winner and exactly one `IllegalJobTransition`.

State lives behind one `threading.Condition` built on a deliberately **non-reentrant** `Lock`, so
an accidental re-entry deadlocks a test instead of silently succeeding. That choice is what makes
"no callback under the lock" provable: a listener that reads the snapshot, the state and the
cancel flag from inside the notification would hang if the guarantee were false, and it does not.
Failure messages are validated *before* the state moves, and a failure detail refuses a live
exception object outright and truncates at 2,000 characters.

#### Deviations

**None.** No Phase 1–4 contract was changed and no contradiction surfaced. The frozen nine-state
vocabulary, the transition table, traversal, the imported-file manager, transaction semantics and
the import coordinator are all byte-identical or behaviourally untouched.

#### Evidence

- Focused: Phase 1 contracts and boundaries **324 passed**; Phase 2 traversal **91 passed, 6
  skipped**; Phase 3 manager **144 passed, 2 skipped**; Phase 4 coordination **129 passed**;
  Phase 5 controller **173 passed**; maintenance and cleanup **337 passed**; output paths **255
  passed, 1 skipped, 1 warning**; the eight cancellation-bearing production suites **61 passed**,
  identical to the pre-edit baseline.
- Collection **1,943** (1,767 + 173 new controller tests + 3 net new boundary tests). Full suite
  **1,930 passed, 13 skipped, 1 warning**. Theme suite **17/17 executed**; the documented Tk
  transient did not recur. `scripts/verify.py` **RESULT: PASS**. Compile gate exit 0.
- **Whitespace.** With only the four source files staged, `git diff --cached --check` reported
  **nothing at all**, and `-- '*.py'` exits 0. Every finding in the broad check comes from the
  documentation edits and is inherited: `Handoff.md`'s stored blob is CRLF, so every added line
  ends in a carriage return, and the drop header uses markdown two-space hard line breaks. No
  file was reformatted to make the check quieter.
- The 13 skips are unchanged from the Phase 4 baseline. Phase 5 added none: all 173 of its tests
  run here, because the controller needs no privileged filesystem facility and no display.
- No test sleeps and none waits on a wall clock. Pauses are arranged with per-checkpoint gates,
  races with `threading.Barrier`, and "has it paused yet?" is answered by the controller's own
  listener rather than by polling. Eight consecutive runs of the focused suite gave identical
  results in 0.14 s each.

### Phase 4 — Background import coordination and Cancel Import (2026-08-09, HOME-PC)

**Result: a new pure companion module, `shared/import_coordination.py`, makes folder importing
responsive without making it unsafe — one operation at a time, the broad-root warning before any
worker exists, a bounded queue of frozen events, owner-thread fencing on every entry point that
can reach the imported list, the captured >threshold confirmation, and atomic commit with
bounded stale-revision recomputation — plus 129 focused tests. The cancellation isolation gate
was **not encountered**: `shared/cancellation.py` is byte-identical and the coordinator does not
import it at all. No Tk, no output run, no processing work, no source file touched.**

#### The isolation gate: not encountered

The active drop makes Phase 4 stop if import cancellation cannot be kept away from the
processing job's controller without changing `shared/cancellation.py` or production processing
code. It cannot arise here, because the two never meet:

- `ImportCancellation` is a per-operation `threading.Event` behind a four-method class. It is
  created fresh for each operation, is never reset, and raises nothing — cancelling a scan
  returns a cancelled *result*, it does not unwind a stack.
- `shared/import_coordination.py` does not import `shared/cancellation.py`, defines no
  `ConversionCancelled`, and calls no `raise_if_cancelled`. An `ast` guard asserts both.
- Behaviourally, a stand-in processing controller wired exactly as the existing tools wire one
  stays unset across an import cancel, an import close and everything in between.
- `shared/output_paths.py`, `shared/maintenance.py` and `shared/cancellation.py` are all
  byte-identical to the approved Phase 3 commit, as are `config.py`, `config.toml`,
  `requirements.txt`, both root launchers and every production panel.

#### One deviation, recorded: the coordinator is its own module

§7's "likely new production modules" names `importing.py`, `job_control.py` and `job_ui.py`.
Phase 4's coordinator is a fourth, `shared/import_coordination.py`. §7 expressly allows a
different split when it is explained and recorded, and the reason is a guard rather than a
preference: `importing.py` carries an approved Phase 1 test proving it constructs no thread,
owns no queue, and names `threading` exactly once — the lock inside `IdFactory`. Folding a
worker and a queue into that file would have deleted that proof for the rest of the drop, and
that proof is what keeps the value objects, the traversal core and the manager auditable as
pure. The dependency runs one way, `import_coordination` → `importing`, exactly as
`job_control` already does, and a guard asserts that too.

#### What Phase 4 added

- **`ImportCoordinator`** — the whole lifecycle of one import. `start()` validates, applies the
  broad-root warning and creates at most one worker; `pump()` drains the queue on the owner
  thread and resolves what it found; `confirm_pending()` / `decline_pending()` answer the
  large-result question; `request_cancel()` is Cancel Import; `close()` cancels, joins and
  refuses everything afterwards. `import_files()` routes Add Files through the identical
  confirmation-and-commit path, synchronously, so there is exactly one door into the manager
  rather than two that could drift apart.
- **Owner-thread fencing.** The coordinator records the thread that constructed it, and every
  entry point that can read or change the manager raises `ImportCoordinationError` if called
  from anywhere else. "The worker never mutates the list" is therefore enforced, not documented;
  a test drives each of the six entry points from a second thread and watches it refuse.
- **`ImportEvent` / `ImportOutcome`** — the frozen queue vocabulary. Five event kinds (started,
  discovered, completed, cancelled, failed), of which exactly one terminal kind is published per
  accepted start. A `ScanResult` is already a frozen dataclass of tuples, so publishing one is
  safe; an exception object never crosses, because a failure is converted to a display-safe
  sentence plus a one-line technical detail before it is put on the queue.
- **`ImportPoller`** — the seam Phase 8's Tk adapter will plug into. It takes a scheduler with
  `root.after`'s shape and an optional cancel with `root.after_cancel`'s shape, and imports no
  Tk itself. At most one callback is ever pending; `stop()` and `close()` are idempotent; and a
  callback that fires after either one returns immediately without touching the coordinator,
  which is how a destroyed widget is survived rather than crashed into.

#### Decisions worth knowing

- **Progress is coalesced, so the queue is bounded by design.** The worker asks a gate before
  publishing a count and is refused while an earlier progress event is still unread. Ten
  thousand discoveries produce one queued event, not ten thousand. Counts stay monotonic and
  truthful — intermediate values are skipped, never invented or reordered.
- **A count discovered after Cancel was pressed is not live progress.** The worker stops
  offering counts once its flag is set, and the coordinator ignores any that were already in
  flight, so the number on screen never climbs after the user asked the import to stop.
- **A broad root with no confirmer wired up is refused, not scanned.** An application that
  forgets to connect the warning must not silently walk a whole drive. Declining creates no
  thread, and the check is lexical: a root that does not even exist is still classified without
  a single filesystem call.
- **Equal to the threshold does not warn.** Only a strictly greater proposal asks, per §6.7, and
  the threshold is read from the `EffectiveConfig` frozen onto the request — a test monkeypatches
  `config.get_effective` to explode and the import still completes.
- **A stale revision is recomputed exactly once, never merged and never looped.** If the
  recomputation proposes a materially different set — a different number of additions or
  duplicate skips — and the user had already agreed to the old one, they are asked again rather
  than given something they did not approve. A second conflict is reported as `CONFLICT` with
  nothing appended, rather than retried forever.
- **Close is orderly and truthful.** It sets the cancellation flag first, then joins within a
  bounded timeout, then empties the queue. If the join expires it reports `worker_stopped=False`
  rather than claiming a running call stopped (§5.4). The daemon flag on the worker is a
  backstop for a hung network `scandir`, never the mechanism — a test proves no thread survives
  a deterministic teardown.

#### Evidence

- Focused: Phase 1 contracts and boundaries **321 passed**; Phase 2 traversal **91 passed, 6
  skipped**; Phase 3 manager **144 passed, 2 skipped**; Phase 4 coordination **129 passed**;
  maintenance and cleanup **337 passed**; the output-path group **255 passed, 1 skipped, 1
  warning**; the existing processing-cancellation suites **32 passed**, unchanged.
- Collection **1,767** (1,629 + 129 new coordination tests + 9 net new boundary tests). Full
  suite **1,754 passed, 13 skipped, 1 warning**. Theme suite **17/17 executed**; the documented
  Tk transient did not recur in this phase. `scripts/verify.py` **RESULT: PASS**. Compile gate
  exit 0.
- **Whitespace.** `git diff --check` against the Phase 3 starting commit is **completely clean
  for the code change** — with only the three source files staged it reports nothing at all, and
  `git diff --cached --check -- '*.py'` exits 0. Every finding in the broad check comes from the
  documentation edits and is inherited, not introduced: `Handoff.md`'s stored blob is CRLF, so
  every added line ends in a carriage return, and the drop header uses markdown two-space hard
  line breaks. The same two files produce the same class of finding in the approved Phase 3
  commit. No file was reformatted to make the check quieter.
- The 13 skips are unchanged from the Phase 3 baseline: two Windows file-symlink privilege skips
  (`[WinError 1314]`), three `JACK_RYAN_M4B_FOLDER` fixture skips, five Phase 2 symlink skips,
  one Phase 2 and one Phase 3 case-insensitive-filesystem skip. Phase 4 added no skip: every one
  of its 129 tests runs on this machine, because it needs no privileged filesystem facility.
- No test sleeps. Races are arranged with `threading.Event` and injected scanners; every wait
  carries a five-second explanatory timeout so a hang fails loudly.

### Phase 3 — Imported-file manager, deduplication, atomic transactions (2026-08-09, HOME-PC)

**Result: `shared/importing.py` gained the ownership half of the foundation — Add Files
validation, deduplication by non-following source identity, the deliberate-duplicate override,
atomic transactions against an expected revision, and the ordered manager with its selection and
four mutations — plus 146 focused tests. The `output_paths.py` compatibility gate was **not
encountered**: the manager feeds Plan 2's existing planners through a pure regrouping and
`output_paths.py` is byte-identical. No worker, no queue, no Tk, no confirmation dialog, no
output run.**

#### The compatibility gate: not encountered

The active drop makes Phase 3 stop if a manager snapshot cannot reach `plan_flat`,
`plan_mirrored` or `plan_multi_root` without changing `output_paths.py`. It cannot arise here,
because the planners already accept exactly what `ImportedFile` has carried since Phase 1:

| Planner | What it asks for | What the importer already has |
|---|---|---|
| `plan_flat(root, sources)` | an iterable of source paths | every occurrence whose root is the `DIRECT_FILES` group (Decision 31A) |
| `plan_mirrored(root, sources, source_root)` | sources plus their declared root | `ImportedFile.path` and `ImportedFile.mirroring_root` |
| `plan_multi_root(root, grouped)` | `[(source_root, sources), …]` | occurrences grouped by `source_root`, in `ImportRoot.order` |

`planning_groups()` is therefore a **regrouping and nothing more** — it sorts occurrences into
those three shapes and decides no destination. No collision numbering, no sanitising, no run
reservation and no directory creation exist in `importing.py`, and a structural guard now asserts
that by name, so two services can never start disagreeing about where a file lands. Blob hashes
for `output_paths.py`, `maintenance.py` and `shared/cancellation.py` are unchanged from the
approved Phase 2 commit.

#### What Phase 3 added to `shared/importing.py`

- **`validate_direct_files`** — Add Files. It preserves the user's order *exactly* (natural
  ordering belongs to Add Folder, where the user chose a tree rather than a sequence) and
  re-inspects every path the dialog returned, in the same fail-closed order the scanner uses:
  existence and readability first, then the link question, then the file's shape, then its type.
  A directory, shortcut, junction, device node, vanished file, unreadable file, unsupported
  extension and unusable path each become a reported problem rather than a silent omission. A
  hidden file chosen **explicitly** is accepted — hidden policy exists so a scan does not sweep
  up dot-files the user never saw, not to overrule a deliberate choice (§6.2). It never recurses,
  never follows, never opens a file and never sorts.
- **`plan_transaction` / `ImportTransaction`** — the deduplication pass. Each candidate's identity
  is compared against every occurrence already in the snapshot *and* every candidate already
  accepted in the same transaction, so a file cannot slip in twice by being reached two ways.
  Identity is Phase 2's `capture_identity`: the platform's own non-following file id where there
  is one — which is why a **hard link** is correctly recognised as the same physical source — and
  a Unicode-normalised lexical key where there is not, casefolded only where the filesystem is
  case-blind. Skips are recorded as `ProblemCategory.DUPLICATE`, kept distinct from unsupported,
  link, unreadable and invalid problems, and each names the real path and the occurrence it
  matched: a duplicate is never disguised as a different file.
- **The duplicate override (Decision 35A)** — off by default, read from the frozen
  `ImportOptions` and then **stamped onto the transaction**, so a preference toggled afterwards
  cannot retroactively rewrite what that transaction meant. When on, every occurrence is kept:
  same path, same root, same relative path, same identity, new occurrence id. A second copy is a
  second *row*, not a second *file*.
- **`ImportedFileManager`** — the ordered list, a monotonic `Revision`, and a selection kept by
  occurrence id rather than row number, so it survives a reorder and can be restored after the UI
  rebuilds its list. `plan` prepares, `commit` appends the whole accepted set once or appends
  nothing, `recompute` re-plans a stale transaction against current state, and
  `remove_selected` / `clear` / `move_selected_up` / `move_selected_down` mutate the list.
- **`planning_groups` / `PlanningGroups`** — the Plan 2 adapter described above.

#### Decisions worth knowing

- **The revision moves only when something actually changed.** A no-op move, a removal with
  nothing selected, a clear on an empty list and a commit whose accepted set is empty all leave it
  alone — otherwise a no-op would invalidate a transaction another part of the UI is holding.
  A valid-but-empty commit reports `NOTHING_TO_ADD` rather than a misleading success.
- **Occurrence ids are minted by the manager's own `IdFactory` at planning time.** The scan's ids
  are provisional; reissuing them is what guarantees both uniqueness against the existing list and
  a distinct id for every deliberate duplicate. `commit` additionally refuses, loudly, any
  transaction whose additions collide with ids already in the list — defence in depth behind the
  revision check, for a transaction planned through a foreign factory.
- **A cancelled, failed or declined result cannot become a transaction at all.** `plan_transaction`
  raises on a non-committable `ScanResult`, and `ScanResult` already refuses to carry files unless
  it completed — so "cannot partly modify the manager" is structural in two places, not a rule
  someone has to remember in Phase 4.
- **Move semantics, stated literally (§6.6).** Selected rows travel as one logical block across
  the nearest adjacent unselected row, closing up around it; both selected and unselected rows keep
  their relative order; nothing wraps. A block whose topmost row is already at the top will not
  move up even if a lower selected row could — the block is one thing, and the call is a safe
  no-op, exactly as it is with no selection and with everything selected. Repeated moves are
  deterministic and reversible.
- **A directory supplied to Add Files produces one refusal, not one per child.** It is not walked.

#### Evidence

- Focused: Phase 1 contracts + boundary guards **312 passed**; Phase 2 traversal **91 passed, 6
  skipped**; Phase 3 manager/validation/dedupe/transactions/selection/compatibility **144 passed,
  2 skipped**; maintenance + both cleanup suites **307 passed**; output-path group **255 passed,
  1 skipped, 1 warning**; cancellation-bearing tool suites **30 passed**.
- Collection **1,629**. Full suite **1,616 passed, 13 skipped, 1 warning**. Theme suite **17/17
  executed**. `verify.py` **RESULT: PASS** on three consecutive runs, identical counts each time.
  `compileall` exit 0.
- **`git diff --check`, stated precisely.** Restricted to code (`-- '*.py'`) it exits **0**: no
  Python file carries a whitespace defect. Unrestricted it reports trailing whitespace in exactly
  two markdown files, for two structural reasons that predate this phase — `Handoff.md`'s stored
  blob is CRLF (5,876 CRLF lines, 0 bare LF), so *every* added line ends in `\r` and Git counts
  that as trailing whitespace, and the drop's header uses markdown two-space hard line breaks on
  the lines this phase updated. Re-running the same check against the **approved Phase 2 commit**
  (`git diff --check 8a8b0b1^ 8a8b0b1`) produces 239 flags in those same two files, so this is the
  established state of the documentation and not something Phase 3 introduced. Phases 1 and 2
  recorded the check as simply "clean", which was accurate for code and imprecise for those two
  files; recorded here rather than silently repeated, and **no file was reformatted to make the
  check quieter** — rewriting `Handoff.md`'s line endings would produce a 5,876-line diff for no
  benefit.
- The 13 skips are the 11 established ones plus Phase 3's two, each naming its exact limitation:
  one `[WinError 1314]` file-symlink privilege skip and one case-insensitive-filesystem skip.
  Symlink coverage is not lost to the privilege limit — refusal is additionally proved by
  injecting the classifier, and real junctions run for real.
- **The documented Tk skip transient recurred.** One `verify.py` run reported *1,607 passed, 22
  skipped*, and a later direct run reproduced it in full with reasons: all 17 `test_ui_theme.py`
  tests skipped with `Tk cannot open a display here: Can't find a usable init.tcl in the following
  directories:`. It is environmental, confined to that one module, and unrelated to Plan 3.
  `verify.py` and the Tk tests were **not** modified. The stable figures above were confirmed by
  six consecutive runs (three `verify.py`, three direct) plus the explicit 17/17 theme run.

### Phase 2 — Safe natural traversal core (2026-08-08, HOME-PC)

**Result: `shared/importing.py` gained the scanning half of the foundation — natural ordering,
broad-root classification, hidden detection, non-following identity capture and a synchronous
`scan_roots()` — plus 91 focused traversal tests. The link-classification risk gate was
**reached and cleared with evidence**; nothing was refactored. No manager, no worker, no queue,
no Tk, no output run.**

#### The risk gate: reached, evidenced, and cleared

The active drop makes Phase 2 stop before refactoring if `maintenance.is_link` cannot safely
classify an importing case. It was checked first, against real filesystem objects on this
machine, and it classifies **all five** required cases correctly:

| Required case | `maintenance.is_link` | Evidence |
|---|---|---|
| Ordinary file | `False` | real file under `tmp_path` |
| Ordinary directory | `False` | real directory under `tmp_path` |
| **Real NTFS junction** | **`True`** | created without elevation via `_winapi.CreateJunction`; `lstat` attributes `0x410` = `DIRECTORY \| REPARSE_POINT` |
| File symlink | `True` | real symlink where creatable; otherwise skipped with the exact `WinError 1314` |
| Directory symlink | `True` | same |
| **Selected root that is a link** | **`True`** | a junction supplied as the chosen root |

**The junction case is the one that justifies the reuse.** A junction reports
`is_symlink() == False`; only the reparse-point attribute catches it. A hand-rolled
`is_symlink()` check in the importer would have failed **open** on exactly the case this drop
cares most about, and would have walked out of the selected tree. `maintenance.is_link` already
tests both, so it is imported and used rather than re-implemented.

**One nuance found, recorded, and handled without touching `maintenance.py`.** `is_link` answers
`False` for a path it cannot `lstat` **at all**. That is the right answer for a cleanup target
that is re-authorised immediately afterwards, but "I could not read it" must never be read as
"safe to walk into". The scanner therefore settles **existence and readability first** and only
then asks the link question, so an unreadable entry is refused as a problem and never reaches the
link check. This is a sequencing decision inside `importing.py` — **not** an extraction, an
extension, or a change to `maintenance.py`, whose only new caller is the one `is_link` import.

**A second observation, not acted on.** `maintenance._is_link` assumes `st_file_attributes` is an
integer. Every real `os.lstat` satisfies that; only a synthetic `os.stat_result` built from a
bare ten-tuple leaves it `None`, which would raise `TypeError`. That is a fixture artefact, not a
reachable production condition, so the **test fixture** was corrected to build realistic stat
results and `maintenance.py` was left alone. Recorded here so a later phase can judge it rather
than rediscover it.

#### What Phase 2 added to `shared/importing.py`

- **`natural_key`** — Unicode-aware, case-insensitive ordering that counts: digit runs compare as
  integers, text runs as casefolded text, and the two are never compared to each other, so no
  `int`/`str` comparison can raise. Ties break on the NFC-normalised original name, so `A` and
  `a` have a deterministic order instead of depending on what the filesystem returned first. A
  digit run past CPython's 4,300-digit `int()` limit degrades to text rather than crashing a scan.
- **`RootBreadth` / `classify_root_breadth` / `is_broad_root`** — purely lexical classification of
  volume roots, UNC share roots and the **injected** user home. Nothing is scanned in order to
  discover that it is broad, and the home is a parameter, so a test never depends on who is
  logged in. The warning itself is Phase 4.
- **`is_hidden_name` / `has_hidden_attribute` / an injectable `hidden_probe`** — the portable
  dot rule plus the Windows `FILE_ATTRIBUTE_HIDDEN` read through `lstat`, with the platform probe
  injectable so Windows behaviour is provable on POSIX and vice versa.
- **`capture_identity`** — prefers the platform's own `(st_dev, st_ino)`, so one physical file
  reached through two spellings or a hard link is recognised as one source; falls back to an
  NFC-normalised lexical absolute-path key, casefolded only where the filesystem is case-blind.
  **`resolve()` is never called.** Phase 3 owns what to *do* with two matching identities.
- **`scan_roots()`** — the synchronous core. Per root, in the order supplied and never globally
  re-sorted: validate without following, enumerate one directory, classify every entry from a
  **fresh `lstat`**, emit that directory's compatible files first in natural order, then descend
  into its eligible children in the same order.

#### The decisions inside the traversal worth knowing

1. **It fails closed.** Every entry is re-`lstat`-ed rather than trusted from the `scandir`
   buffer, so an entry that changed shape since enumeration is classified as it is *now*. A
   `FileNotFoundError` becomes `VANISHED`, any other `OSError` becomes `UNREADABLE`, and neither
   is descended into. Anything that is neither a regular file nor a directory becomes
   `WRONG_TYPE`.
2. **An explicit stack, not recursion.** A deep tree must not depend on Python's recursion limit,
   and the ordering is easier to prove: children are pushed in reverse natural order so the first
   child pops first, which yields files-then-depth-first without a second sort.
3. **Root failures are `INVALID_ROOT`; entry failures keep their own category.** A missing,
   unreadable, non-directory or linked *root* is one clearly attributable problem with the precise
   cause in `technical_detail`; `LINK`, `UNREADABLE`, `VANISHED`, `WRONG_TYPE`, `HIDDEN` and
   `UNSUPPORTED_TYPE` describe entries *inside* a scan. Both category families stay in use and
   nothing is silently discarded.
4. **Hidden folders are optional; hidden files never are.** `include_hidden_folders` gates
   directories only. A hidden *file* found by walking is always skipped and reported — but the
   vocabulary still accepts a hidden path the user chose deliberately, so Phase 3's `Add Files`
   has something to build on. "Include hidden" is also not "include anything": a hidden folder
   that is a junction is still refused.
5. **`DIRECT_FILES` roots are not walked.** They name no tree; validating individually chosen
   files is Phase 3's `Add Files`. A request mixing both kinds scans the folder roots and simply
   ignores the direct group.
6. **Cancelling an import raises nothing.** `scan_roots` returns a `ScanOutcome.CANCELLED` result
   carrying **no files** — the Phase 1 invariant makes a partial commit unrepresentable — and
   stops calling `on_count`. `shared.cancellation` is untouched and unmentioned: Cancel Import is
   not the processing job's cancel.
7. **A checkpoint was added inside the emission loop.** The plan names checkpoints before each
   root, during entry classification, before each descent and before publication. Testing
   "no callback after acknowledged cancellation" showed a directory holding thousands of matches
   would keep reporting counts between checkpoints, so emission now checks too. The bound is
   tighter than the plan requires and contradicts nothing in it.

#### Structural guards updated, not deleted

Three Phase 1 guards had to move as Phase 2 delivered what they forbade. Each was **narrowed**
rather than removed:

- The blanket "no filesystem call" guard split in two. `job_control.py` keeps the strict version
  (**zero** filesystem verbs). `importing.py` gets a budget of **exactly `scandir` and `lstat`**,
  with every write, every content read and every *following* call — `resolve`, `realpath`, `stat`,
  `exists`, `is_dir`, `is_file`, `is_symlink`, `samefile`, `readlink` — still forbidden, plus a
  text check for `follow_symlinks=True` and `.resolve()`.
- The "imports no Plan 2 service" guard now permits `importing.py` exactly one edge to
  maintenance, and a new test pins it: the **only** name borrowed is `is_link`, the whole module
  is never imported, and no cleanup concept (`authorized_target`, `inventory`, `estimate_size`,
  `PROTECTED_RELATIVE`, `ASSET_IDS`, …) appears in the importer. A companion test proves
  `maintenance.py` itself was not rearranged and still imports neither `shutil` nor `subprocess`.
- The later-phase name guard dropped Phase 2's own names (`scan_roots`, `natural_key`,
  `classify_root_breadth`, hidden probes, `capture_identity`) and kept Phases 3–8, with a new
  positive test asserting Phase 2 delivered exactly its own names and no manager, coordinator or
  estimator.

#### Deliberately not done

No `ImportedFileManager`, deduplication against an existing list, duplicate override, transaction
commit, worker thread, queue, polling, broad-root dialog, 1,000-result confirmation, pause/resume
controller, ETA, Retry Failed, Tk adapter or developer specimen. No production panel or launcher
touched. `shared/cancellation.py`, `shared/output_paths.py`, `shared/config.py`,
`shared/maintenance.py`, packaging, requirements, launchers and `version.py` are **unchanged**.
`Briefing.md`'s deferred packaging sentence is still untouched. The Phase 1 packaging remediation
and every Phase 1 contract are preserved, and **no Phase 1 state-transition judgement call was
altered** — the traversal work exposed no contradiction with them.

#### Phase 2 verification (2026-08-08, HOME-PC, repo venv Python 3.12.10)

| Command | Result |
|---|---|
| Focused: Phase 1 contracts + boundary guards | **310 passed** |
| Focused: Phase 2 traversal and safety | **91 passed, 6 skipped** |
| Focused: `test_maintenance.py` + both cleanup suites (link/read-only) | **307 passed** |
| Focused: `test_output_paths.py` + tool-output + refresh (no planning regression) | **255 passed, 1 skipped, 1 warning** |
| Focused: cancellation-bearing tool suites | **16 passed** |
| `-m pytest files/tests --collect-only -q` | **1481 collected** (1381 + 100) |
| `-m pytest files/tests -q -rsw` (full suite) | **1470 passed, 11 skipped, 1 warning** |
| `-m pytest files/tests/test_ui_theme.py -q -rsw` | **17 passed, 0 skipped — all 17 executed** |
| `scripts/verify.py` (three consecutive runs) | **RESULT: PASS** each time, `1470 passed, 11 skipped, 1 warning` each time |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | clean — exit 0 |

**The 1 warning**, unchanged: `.venv\Lib\site-packages\pydub\utils.py:14` —
`DeprecationWarning: 'audioop' is deprecated and slated for removal in Python 3.13`.

**The 11 skips**, every one named. Five are the documented stable set carried since Phase 0:

1. `test_cover_source_side.py:363` — file symlink, `[WinError 1314] A required privilege is not
   held by the client`.
2. `test_output_paths.py:757` — file symlink, same `WinError 1314`.
3. `test_jack_ryan_final_product.py:40` — `set JACK_RYAN_M4B_FOLDER to the Jack Ryan fixture
   folder to run`.
4. `test_jack_ryan_final_product.py:44` — same reason.
5. `test_jack_ryan_final_product.py:64` — same reason.

Six are **new and expected**, each naming the exact platform limitation:

6. `test_is_link_says_yes_to_a_file_symlink` — `WinError 1314`.
7. `test_is_link_says_yes_to_a_directory_symlink` — `WinError 1314`.
8. `test_a_file_symlink_inside_a_scanned_folder_is_refused` — `WinError 1314`.
9. `test_a_directory_symlink_inside_a_scanned_folder_is_refused` — `WinError 1314`.
10. `test_a_root_that_is_a_symlink_is_refused` — `WinError 1314`.
11. `test_names_differing_only_in_case_are_both_collected` — *"this filesystem is
    case-insensitive, so the two names are one file"* (NTFS).

**Symlink coverage is not simply lost to the privilege limitation.**
`test_link_refusal_is_proved_even_where_symlinks_cannot_be_created` injects the classifier and
proves the refusal path on every machine, and **real NTFS junctions run for real without
elevation** — root junctions, junctions inside a scanned folder, and a junction inside a folder
the user asked to include as hidden are all refused, verified.

**No Tk skip transient occurred in this phase.** All three `verify.py` runs and the direct suite
run reported the identical `1470 passed, 11 skipped`, with collection steady at 1481.

#### Next action

**Phase 3 — Imported-file manager, deduplication, and atomic transactions.** **Not started.** It
requires explicit maintainer approval before any work begins.

### Phase 1 — Pure contracts and compatibility boundaries (2026-08-08, HOME-PC)

**Result: two new platform-neutral modules of frozen value types, 307 new tests, and the Phase 0
baseline defect repaired under the maintainer's approved option (a).** No traversal, no manager,
no worker, no queue, no controller, no ETA and no Tk was written. `scripts/verify.py` is back to
`RESULT: PASS`.

#### The approved baseline remediation, first

`files/tests/test_release_packaging.py` carried a *precondition* asserting the real repository
root held **both** `config.toml` and `config-template.toml`. The maintainer's 2026-08-08
instruction removed the template, so that guard was false and its two parametrised cases failed
before reaching their real assertion.

Under approved option (a) the test was **retained and narrowed, not deleted, skipped, xfailed or
broadly rewritten**:

- the precondition now asserts the current contract — `config.toml` present, `config-template.toml`
  **absent** — with `os.listdir` still used instead of `Path.exists`, because an NTFS/APFS lookup
  is case-insensitive and would confirm a name that is not there;
- **the substantive assertion underneath is byte-identical**: `"config-template.toml" not in
  names(archives[os_name])`;
- the synthetic-root tests are untouched and still deliberately *create* a template in a
  disposable `tmp_path` repository, so the packager is exercised against one it must refuse;
- `import os` moved from inside the function to the module imports, and the module docstring's
  now-obsolete "sits directly beside the real `config.toml`" sentence was corrected to say the
  proof **moved to the synthetic fixture** rather than weakened.

No `config-template.toml` was opened, restored, generated, staged, packaged or used. Focused
result: `test_release_packaging.py` **34/34 PASS**, including all five template-related tests.
Baseline immediately afterwards: **1074 collected, 1069 passed, 5 skipped, 1 warning**,
`verify.py` **RESULT: PASS**, theme 17/17, `compileall` exit 0, `git diff --check` clean — exactly
the expected stable figures, so Phase 1 proper began from green.

The test's *name* — `test_the_untracked_template_beside_it_is_still_absent` — was deliberately
left alone. "Beside it" is now stale, but renaming would make the test read as removed-and-added
in any report that compares node ids, and the instruction was to retain it. Cosmetic only;
flagged for whichever later phase touches that module anyway.

#### What Phase 1 added

**`scripts/Universal/shared/importing.py`** — the importing vocabulary. `SupportedType` /
`SupportedTypeCatalog` (normalised dot-prefixed lowercase extensions; an extension may belong to
exactly one type, or `supported_type_id` would be ambiguous), `ImportOptions` (all types selected
by default; **an empty selection is deliberately representable**, because "you have not ticked
anything" is a message the UI must show, not a constructor crash), `ImportRoot` (a selected folder
that mirrors, or the one direct-files group that does not), `ImportedFile` (occurrence identity
kept separate from source identity, so Decision 35A's deliberate duplicate is visibly the same
source), `ImportProblem` with all nine refusal categories, `Revision` / `ImportedFileSnapshot`,
`ScanRequest` / `ScanResult`, and `IdFactory`.

**`scripts/Universal/shared/job_control.py`** — the job vocabulary. `JobState` (all nine states),
the complete `LEGAL_TRANSITIONS` table, `TERMINAL_STATES`, `INPUT_LOCKED_STATES`,
`freeze_options` / `is_frozen_options`, `RunSnapshot`, `FailureRecord` / `FailureLog`,
`RetryRequest`, and `JobEvent` with all eleven kinds.

**Three test modules** — `files/tests/test_importing.py` (103), `files/tests/test_job_control.py`
(134) and `files/tests/test_plan3_boundaries.py` (70): **307 tests**.

#### The decisions inside those contracts that are worth knowing

1. **Every invalid value is unconstructable, not merely detectable.** All validation is in
   `__post_init__` on frozen, slotted dataclasses, so there is no "validate it later" path for a
   future phase to forget, and no `__dict__` on which a stray attribute could be set.
2. **A non-completed scan carries no files at all.** `ScanResult` refuses to hold candidates when
   its outcome is `CANCELLED` or `FAILED`. "A cancelled or declined import never changes the
   manager" therefore stops being a rule Phase 4 has to remember and becomes something the value
   cannot express. A `FAILED` result must also carry at least one problem — a failure that does
   not say why is not a report.
3. **`freeze_options` copies and refuses; it never keeps a live reference.** Lists become tuples,
   dicts become new read-only mappings, sets become frozensets, and a widget, variable, callable,
   module, thread primitive, open buffer, mutable dataclass, non-finite float, non-string key or
   reference cycle is **rejected** rather than stored. Mutating the payload afterwards provably
   cannot reach the snapshot. `RunSnapshot` freezes in `__post_init__` rather than trusting the
   caller, so there is exactly one door.
4. **Two transitions encode truthfulness over tidiness, and are the notable judgement call.**
   `PAUSE_REQUESTED` and `CANCEL_REQUESTED` may both end the run directly in `SUCCEEDED` /
   `COMPLETED_WITH_FAILURES` / `FAILED`, not only in `PAUSED` / `CANCELLED`. A pause or cancel
   asked for during an indivisible stage does not stop that stage, and if the work genuinely
   finished before the next safe checkpoint, reporting what happened is correct while claiming it
   paused or was cancelled would be a lie. `RUNNING → PAUSED` and `PAUSED → CANCELLED` are
   **illegal**: acknowledgement is mandatory in both directions. **Phase 5 is bound by this
   table** — if it needs a different shape, that is a change to argue for, not to assume.
5. **A fatal, job-level failure can never be retryable** (`item_id is None` ⇒ `retryable=False`),
   and a `FailureLog` allows one record per item, because "an ordered subset of failed ids" must
   not be ambiguous. `RetryRequest.from_failures` normalises any requested subset back into
   failure order, so the same set of ids always produces the same request.
6. **`RetryRequest` stores the original `RunSnapshot` object.** A test asserts
   `request.snapshot is run` — identity, not equality — and that the class has exactly two fields,
   so no destination, output directory or reservation can creep in. Retry placement stays with the
   adopting plan and Plan 2's services.
7. **User-facing text is validated as display-safe at construction.** `display_message` and event
   `message` must be a single line and may never contain `Traceback (most recent call last)`;
   `technical_detail` and event `detail` are unconstrained. Summary/Details *filtering* is Phase 7,
   but the split that makes it possible is enforced now. The rule lives in exactly one function,
   `importing.ensure_display_safe`; `job_control` wraps it only to raise its own error type.
8. **Timestamps are carried, never read.** Nothing imports `time`; `created_at` and `timestamp`
   come from an injected clock and must be finite and non-negative. NaN is refused so a frozen
   value cannot become non-reflexive.
9. **`IdFactory` is injected, not global.** A `threading.Lock` serialises its counter — a lock is
   not concurrency, and creating one starts no thread; a test asserts the live thread count does
   not move while four threads take 800 ids without a collision.

#### Structural guards added (70 tests)

- Neither module imports Tk, `queue`, `asyncio`, `concurrent`, `multiprocessing`, `subprocess`,
  `logging`, `shutil`, `tomllib`, or any Plan 2 service module, and neither constructs a
  `Thread`, `Timer`, `Queue`, `Condition`, `Event` or executor.
- Neither performs any filesystem call — the AST is checked for `scandir`, `walk`, `iterdir`,
  `glob`, `stat`, `lstat`, `exists`, `resolve`, `mkdir`, `write_text`, `open` and eighteen others.
- Neither defines a name Plan 2 already owns (`get_effective`, `reserve_run_directory`,
  `plan_mirrored`, `sanitize_component`, `get_logger`, `raise_if_cancelled`, …).
- **The entire shipped tree** — every `.py` under `scripts/Universal/`, not just the six panels —
  is parsed and proved not to import `shared.importing`, `shared.job_control` or `shared.job_ui`,
  and the panels are additionally proved not to name any Plan 3 type. `launcher.TOOLS` still has
  exactly six entries.
- `shared/cancellation.py` is proved unchanged in shape: it still defines exactly
  `ConversionCancelled` and `raise_if_cancelled`, imports exactly `__future__` and `typing`, and
  behaves identically for `None` / false / true predicates and a custom message. Neither Plan 3
  module mentions either name, so nothing shadows or re-exports it.
- No Phase 2–8 behaviour has leaked in: 25 later-phase names (`scan_roots`, `natural_key`,
  `ImportedFileManager`, `ImportCoordinator`, `JobController`, `EtaEstimator`, `build_ui`, …) are
  proved undefined, `shared/job_ui.py` proved not to exist, and no ETA arithmetic or clock read
  exists anywhere in the foundation.
- The dependency runs one way: `job_control` imports `importing`, `importing` does not import
  `job_control`, and `config` imports neither — the same discipline `logging_setup` follows.
- Repository invariants: version `0.5.1`; `config.toml` and `requirements.txt` unchanged in shape
  with every dependency `==`-pinned; both root launchers present; **all 22 approved screenshots
  present by exact filename**; the four canonical documents exact with no alias and no
  `CHANGELOG.md` / `DECISIONS.md` / `handoff.md` variant; all four protected references present;
  and **root `config-template.toml` absent**.
- The ships/does-not-ship split holds: the two modules are under `scripts/`, the three test
  modules under `files/`, and neither leaked into the other tree.

#### Phase 0 open item, now closed

1. ~~**`verify.py` is FAILING at the baseline**, solely through `test_release_packaging.py:147`.~~
   **RESOLVED in Phase 1** under the maintainer's approved option (a), as recorded above.
   `verify.py` reports `RESULT: PASS`.

#### Reconnaissance inconsistency resolved conservatively

Phase 0 recorded that the plan's §7 names both `test_import_ui.py` and `test_job_ui.py` while
§6.15 puts every adapter in one `shared/job_ui.py`. **One adapter module needs one Tk-boundary
test module: `files/tests/test_job_ui.py` is the intended name, and `test_import_ui.py` will not
be created.** No UI test module was created now to satisfy a filename list — Phase 1 adds no Tk
test at all. `test_plan3_boundaries.py` asserts both files are still absent and carries that
decision in its docstring so Phase 8 finds it.

#### Deliberately not done

- **No new importing→maintenance dependency and no refactor of link detection.** `maintenance.is_link`
  was not imported, wrapped or moved; that risk gate belongs to Phase 2's traversal work.
- **`Briefing.md` was not edited.** Its line 384 still describes the template as sitting beside
  `config.toml`. Phase 1's authorised documentation is `Handoff.md`, the master index's current
  status, and the drop's own status fields; `Briefing.md`/`Changelog.md`/`Decisions.md` belong to
  the approved Phase 10 closeout. The discrepancy stays recorded.
- No `conftest.py` change. The plan reserves that for later fake-clock/filesystem fixtures; Phase 1
  needed none, and the two shared helpers `test_job_control.py` uses are imported from
  `test_importing.py` instead.
- No new dependency, plugin, skill, or `.claude`/`.codex` change.

#### Phase 1 verification (2026-08-08, HOME-PC, repo venv Python 3.12.10)

| Command | Result |
|---|---|
| Focused: the three new modules + `test_release_packaging.py` | **341 passed** |
| `-m pytest files/tests --collect-only -q` | **1381 collected** (1074 + 307) |
| `-m pytest files/tests -q -rsw` (full suite) | **1376 passed, 5 skipped, 1 warning** |
| `-m pytest files/tests/test_ui_theme.py -q -rsw` | **17 passed, 0 skipped — all 17 executed** |
| `scripts/verify.py` | **RESULT: PASS** — `pytest`, `deps`, `docs`, `docnames`, `config` all PASS |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | clean — exit 0 |

The **1 warning** is the same pre-existing pydub `audioop` `DeprecationWarning`. The **5 skips**
are the same five named in the Phase 0 record — two `WinError 1314` symlink-privilege skips
(`test_cover_source_side.py:363`, `test_output_paths.py:757`) and three `JACK_RYAN_M4B_FOLDER`
fixture skips (`test_jack_ryan_final_product.py:40`, `:44`, `:64`). **Phase 1 added no skip and no
warning**, and no test was lost: 1074 → 1381 collected, and the 1069 that passed at the baseline
all still pass.

**The Tk skip transient recurred once more.** One `verify.py` invocation reported
`1367 passed, 14 skipped`; three subsequent runs all reported the stable `1376 passed, 5 skipped`
and `RESULT: PASS`, with collection at 1381 throughout. Fourth recorded occurrence (Plan 1 Phases
3 and 4 at 17 skips, Plan 3 Phase 0 at 11, this one at 9); the reason string is again uncaptured
because `verify.py` runs pytest without `-rs` — the master index §14 blind spot, still unowned.

#### Next action

**Phase 2 — Safe natural traversal core.** **Not started.** It requires explicit maintainer
approval, and its own risk gate applies: if `maintenance.is_link` cannot safely classify an
importing case, stop and report before refactoring maintenance or output-path services.

### Phase 0 — Post-merge reorientation, repository invariants, and baseline evidence (2026-08-08, HOME-PC)

#### Plan 3 branch and start state

| Field | Value |
|---|---|
| Branch | `feature/0.6.0-drop3-shared-job-controls-importing` (new; existed **neither** locally **nor** on `origin` before creation) |
| Start SHA / `origin/master` at fetch | `563df9884497032e19abd4437a0e66584cd9ec12` |
| What that SHA is | the **merge commit for pull request #3**, parents `bada8a3dee87acf6a6619252bd31cdee429f1711` (previous `master`) and `c6fcac7b7469e36cb0d81de2cc524f46cec31bb7` (Drop 2 head) |
| Local `master` | fast-forwarded `bada8a3…` → `563df98…` with `git merge --ff-only origin/master`. No merge commit, reset, rebase, stash, clean, prune, force-push or history rewrite. Local `master` == `origin/master` |
| Fetch | `git fetch origin --no-prune` — the only remote-mutating verb used was a later `git push` of this phase |
| Version | `0.5.1` — unchanged. No bump, tag, release, publication or PR |

The Drop 2 branch was **not** developed on. `master` was reconciled first, and the Plan 3 branch
was cut from the verified local `master`.

#### Drop 2 merge and required ancestry — verified, not assumed

| Required commit | Ancestor of `origin/master` `563df98…` |
|---|---|
| Drop 2 head `c6fcac7b7469e36cb0d81de2cc524f46cec31bb7` | **YES** (`git merge-base --is-ancestor` → 0) |
| Approved Drop 2 Phase 8 `0e7ad0c264cb2a46f3c64f968e24f00963cb1987` | **YES** |
| Plan 1 merge (PR #2) `86933e6510c6303cadf3437dc295d000ffa9ee82` | **YES** |
| Plan 1 feature head `f3d70e8c9017f2fec3ae459c1438dd71b42f9ef0` | **YES** |

Both earlier feature branches are retained and untouched, locally and on `origin`:
`feature/0.6.0-drop1-windows-ui-prototype` at `f3d70e8` and
`feature/0.6.0-drop2-config-output-maintenance-foundation` at `c6fcac7`.

**Stale merge metadata, recorded rather than rewritten.** PR #3's merge message body reads
*"v0.6.0 Drop 2 Phase 0: reorientation, repository invariants, and baseline evidence"* — the
title of Drop 2's *first* phase, not of the whole completed drop. The merge **content and
ancestry are correct**; only the human-readable title is stale. The merge commit was not
rewritten and must not be.

#### `config-template.toml` — the maintainer's superseding instruction, applied

The current contract is **absence**, and it supersedes the older "preserve it exactly" language.

- **No removal was necessary.** The exact repository-root path `config-template.toml` was
  **already absent** when this phase inspected the worktree — the maintainer removed it on
  HOME-PC on 2026-08-08, before this session acted.
- Proven, in this order, before any other step: `git ls-files --error-unmatch config-template.toml`
  → *"did not match any file(s) known to git"* (**untracked**); `git ls-files | grep -i
  config-template` → no index entry; `git ls-tree --name-only origin/master` → the root of the
  merged tree holds only `.gitattributes`, `.gitignore`, `README.md`, both `Setup_and_Run-*`
  launchers, `config.toml`, `files/`, `md-instructions/`, `scripts/` — **no template**; and a
  case-exact `os.listdir(REPO_ROOT)` (never `Path.exists()`, which NTFS answers
  case-insensitively) confirming the physical file is gone.
- Nothing was deleted, recreated, restored, staged, committed, packaged, loaded or read by this
  session. No `git clean`, no wildcard, no recursive delete, and no similarly named file
  elsewhere was touched. No ignore rule was added, so a future tracked regression cannot be
  concealed.
- The **defensive guards stay**, exactly as the instruction allows: `shared/maintenance.py:168`
  keeps `"config-template.toml"` in `PROTECTED_RELATIVE`, and
  `test_repository_contract.py:249–255`, `test_release_packaging.py`, `test_maintenance.py`,
  `test_cleanup_state.py` and `test_cleanup_worker.py` keep the filename as a
  forbidden/protected string. Removing the local file does not weaken the rules that keep it out
  of runtime loading and release archives.

#### Phase 0 baseline evidence (2026-08-08, HOME-PC, repo venv Python 3.12.10)

Run from the repository root with `.venv\Scripts\python.exe`. These are the **actual** merged-master
numbers, not Plan 2's recorded closeout figures.

| Command | Result |
|---|---|
| `-m pytest files/tests -q -rsw` (full suite) | **1074 collected — 1067 passed, 2 FAILED, 5 skipped, 1 warning** (17.4 s) |
| `-m pytest files/tests/test_ui_theme.py -q -rsw` (explicit theme suite) | **17 passed, 0 skipped — all 17 executed** |
| `scripts/verify.py` | **RESULT: FAIL** (exit 1). `pytest` FAIL; `deps`, `docs`, `docnames`, `config` all PASS |
| `-m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | clean — exit 0 |
| `git diff --cached --check` | clean — exit 0 |
| canonical documentation filename/alias check | PASS — 4 canonical names exact, no case-variant alias (`verify.py` `docnames`, backed by a case-exact `os.listdir`) |
| protected `don't-delete` reference check | PASS — all 4 references present under their exact names |

**The 1 warning**, named: `.venv\Lib\site-packages\pydub\utils.py:14` —
`DeprecationWarning: 'audioop' is deprecated and slated for removal in Python 3.13`, raised at
`import audioop`. Pre-existing, third-party, carried unchanged since Plan 1.

**The 5 skips**, all named with their reasons:

1. `test_cover_source_side.py:363` — *"this environment cannot create a file symlink:
   [WinError 1314] A required privilege is not held by the client"*. This Windows account is not
   elevated and lacks `SeCreateSymbolicLinkPrivilege`.
2. `test_jack_ryan_final_product.py:40` — *"set JACK_RYAN_M4B_FOLDER to the Jack Ryan fixture
   folder to run"*. Copyrighted local media fixture, deliberately not in the repository.
3. `test_jack_ryan_final_product.py:44` — same reason.
4. `test_jack_ryan_final_product.py:64` — same reason.
5. `test_output_paths.py:757` — *"this environment cannot create a file symlink → symlink:
   OSError: [WinError 1314] A required privilege is not held by the client"*. Same privilege
   limitation as (1).

None of the five is a masked failure, and the skip set is identical to Plan 2's five documented
skips.

#### Baseline FAILURE recorded, NOT fixed in Phase 0

`verify.py` reports **RESULT: FAIL**, and the sole cause is two tests that the maintainer's own
superseding `config-template.toml` instruction invalidated:

```
FAILED files/tests/test_release_packaging.py::test_the_untracked_template_beside_it_is_still_absent[Windows]
FAILED files/tests/test_release_packaging.py::test_the_untracked_template_beside_it_is_still_absent[MacOS]
```

Both fail on the same line — `test_release_packaging.py:147`:

```python
entries = os.listdir(REPO_ROOT)
assert "config.toml" in entries and "config-template.toml" in entries, (
    "this test is only meaningful while both files sit at the root")
```

That is a **precondition guard**, not the safety assertion. It hard-codes the assumption that
the maintainer's untracked template is sitting beside `config.toml` in the real repository. Now
that the file is gone by instruction, the guard is false and the run stops before reaching the
real check on line 149 (`"config-template.toml" not in names(archive)`).

**The packaging safety property itself is unaffected and still proven green** by two tests that
do not depend on the real worktree:

- `test_a_template_in_a_synthetic_root_is_excluded_by_scope` — builds both archives from a
  `tmp_path` fake repo that *does* contain a template, and asserts no member matches
  `config-template`. **PASSED.**
- `test_the_packager_never_names_the_template_at_all` — parses `shared/release.py` and asserts
  the string is absent, along with `shutil`/`copytree`. **PASSED.**

Arithmetic against Plan 2's closeout: 1074 collected then and now; the 1,069 that passed then
are 1,067 passed + these 2 failed now. **No test was lost, added or silently skipped by the
merge** — exactly two flipped, for exactly this reason.

**Not fixed here, deliberately.** Phase 0's contract forbids changing production source, tests,
configuration or packaging; the repair is a one-line change of a test precondition and belongs
to the first phase authorized to touch `files/tests/`. Recorded as an open item below rather
than quietly repaired or excluded.

#### The documented Tk skip transient recurred once — reported, not smoothed over

The **first** `verify.py` invocation of this phase reported `2 failed, 1056 passed, 16 skipped`
— eleven passes that became skips. The two immediately following `verify.py` runs, and both
direct `pytest` runs (including one reproducing `verify.py`'s exact absolute-path invocation),
all reported the stable `2 failed, 1067 passed, 5 skipped`. Collected stayed 1074 throughout.

This is the third occurrence of the transient recorded in this file (Plan 1 Phases 3 and 4, both
17 extra skips; 11 this time), and the reason string was again **not captured** — `verify.py`
runs `pytest` without `-rs`, which is precisely the *"`verify.py` skipped-suite detection blind
spot"* carried in the master index §14 as unowned. The reported baseline above is the stable,
thrice-reproduced figure; the transient is disclosed rather than averaged away.

#### Skills audited for Plan 3

| Skill / capability | Location | Verdict for Plan 3 |
|---|---|---|
| `audio-processing` | `.claude/skills/audio-processing/SKILL.md` | **Read and will use as a guardrail.** Plan 3 changes no audio behaviour, but its subprocess-list/`shlex.quote` rule, its copy-first/never-overwrite-the-original rule and its ffmpeg/ffprobe-presence discipline are exactly the boundaries the importer and job controller must not erode. |
| `fullstack-bridge-sync` | `.claude/skills/fullstack-bridge-sync/` | **Not applicable** — Python↔TypeScript API contract syncing; this project has no frontend/backend split. |
| `.codex/skills/` | repository | Present but empty of skills on this machine; nothing to audit. |
| Superpowers — `test-driven-development` | user scope | **Will use** in Phases 1–8. Every Plan 3 module is pure logic or a queue boundary, which is the ideal shape for test-first. |
| Superpowers — `systematic-debugging` | user scope | **Will use** if a Phase 4/5 concurrency test proves flaky; the plan forbids "fixing" a race by sleeping. |
| Superpowers — `verification-before-completion` | user scope | **Will use** at every phase boundary; it is the same evidence-before-assertion rule this drop's §1 already imposes. |
| Superpowers — `requesting-code-review` / `receiving-code-review` | user scope | Available for phase boundaries; optional. |
| Superpowers — `brainstorming` / `writing-plans` / `executing-plans` | user scope | **Not needed** — the plan is already written, approved and phase-gated by the maintainer. |
| Superpowers — `using-git-worktrees` | user scope | **Deliberately not used.** This drop names one branch in the main worktree; adding a worktree would contradict the recorded branch/SHA contract. |
| Sequential Thinking (MCP) | user scope | **Will use** for the genuinely revisable reasoning in §6.5 (duplicate identity) and §6.9–6.10 (the pause/resume/cancel state machine and its races). |
| Context7 (MCP) | user scope | Available for current stdlib/pytest API confirmation. Use is inherently limited — the drop forbids any new runtime dependency. |
| UI-testing support | — | No dedicated UI-testing skill is installed. The repository's own Tk patterns are the harness: `test_ui_theme.py`'s module-scoped `tk_root` fixture, `test_prototype_regression.py`'s `_walk` widget crawler and `@windows_only` gate. |
| Everything else offered (`dataviz`, `artifact-*`, `claude-in-chrome`, `claude-api`, `security-review`, `schedule`, `loop`, `init`, `run`, `fewer-permission-prompts`) | user scope | **Not applicable** to this drop. |

**No skill, plugin, MCP server or dependency was installed, copied or modified**, and neither
`.claude/` nor `.codex/` was expanded — the drop forbids it without separate approval.

#### Implementation surface inspected (read-only, Phase 0)

Every component named in the drop's §2 table was located and compared against the plan's cited
line ranges. **The plan's map of the codebase is accurate; the drift found is minor and listed
at the end.**

| Component | Found at | Against the plan's citation |
|---|---|---|
| `shared/cancellation.py` | whole file is 38 lines: `CancelCheck` L21, `ConversionCancelled` L24, `raise_if_cancelled` L28–38 | cited "≈24–38" — **exact** |
| `shared/config.py` | `ImportingConfig` L213, `EffectiveConfig` L219, `DEFAULT_LARGE_RESULT_WARNING_THRESHOLD = 1000` L112, validator L419–420, `SETTINGS_OVERLAY` L65 | cited "≈219–241" and "≈107–115" — **exact** |
| `shared/output_paths.py` | `RunReservation` L615, `reserve_run_directory` L635, `plan_flat` L761, `plan_mirrored` L787, `plan_multi_root` L815, `DestinationPlanner` L526, `sanitize_component` L306, `assert_no_link_in` L405, `assert_contained` L445, `destination_hint` L118 | cited "≈615–632" and "≈720–855" — **exact** |
| `shared/maintenance.py` | `is_link` L277, `authorized_target` L297, `estimate_size` L373, `inventory` L498 | cited "≈277" and "≈360–548" — **exact** |
| `shared/preferences_ui.py` | `CleanupDialog` L489, `start_inventory` L663, `_poll` L678 | cited "≈663–710" — **exact** |
| `shared/ui_theme.py` | `ProgressIndicator` L1002 (file 1076 lines), `WINDOWS_STYLE_PREFIX = "ACT"` L60, `style_tk_widget` L911, `enable_mousewheel` L968 | cited "≈1002–1052" — **exact** |
| `shared/subprocess_utils.py` | `_hidden_kwargs` L19, `run` L32, `popen` L41, `check_output` L46, `install_no_window_guard` L54, `reveal_in_file_manager` L94; file is 110 lines | cited "19–110" — **exact** |
| `shared/logging_setup.py` | `DEFAULT_MAX_SESSIONS = 30` L25, `configured_max_sessions` L35, `_prune_old_logs` L48, `get_logger` L60; file is 81 lines | cited "35–80" — **exact** |
| `shared/settings.py` (201 lines), `launcher.py`, `scripts/verify.py` (299 lines), `.gitignore`, `.gitattributes`, `scripts/requirements.txt` (all `==`-pinned) | inspected | consistent |

**Per-panel worker foundations** — every one of the six production panels already owns its own
daemon thread(s), queue, `threading.Event`s and `after()` pump, exactly as the plan's §2 row
"Tool workers" describes:

| Panel | `threading.Thread` | queue | `threading.Event` | `.after(` | cancellation refs |
|---|---:|---:|---:|---:|---:|
| `tts/epub2tts_gui.py` | 1 | 2 | 2 | 1 | 3 |
| `mp3_tools/m4b_converter.py` | 1 | 1 | 2 | 2 | 0 |
| `mp3_tools/mp3_tool.py` | 3 | 1 | 2 | 2 | 11 |
| `mp3_tools/m4b_maker.py` | 1 | 1 | 2 | 2 | 7 |
| `mp3_tools/cover_resizer.py` | 1 | 1 | 2 | 2 | 0 |
| `mp3_tools/m4b_metadata_editor.py` | 2 | 1 | 2 | 2 | 5 |

**Current traversal**, which Plan 3 must not alter: `tts/batch_convert.py:241–246` (`rglob("*")`
with a suffix check, commented as deliberate) and `tts/epub2tts_gui.py:564`
(`in_root.rglob("*")`); the M4B Metadata Editor's folder picker is a **non-recursive
`folder.iterdir()`** at `m4b_metadata_editor.py:728–736`. Elsewhere, `os.scandir` appears only
in `shared/cleanup_worker.py:189` and `Path.rglob` only in `shared/release.py:125`.

**Plan 3's own target modules do not exist yet**, as expected: `shared/importing.py`,
`shared/job_control.py` and `shared/job_ui.py` are all absent. `files/tests/conftest.py` is a
20-line `sys.path` shim with **no fixtures**, so Phase 2 onward will add the fake-clock and
disposable-filesystem fixtures the plan anticipates.

**Existing Plan 3 scope guards already in the suite**, which later phases must update rather
than delete:

- `test_config.py:277` `test_the_large_result_threshold_is_only_validated_not_consumed` — asserts
  `config.py` contains none of `def scan`, `rglob`, `Cancel Import`, `recursive_scan`. The
  threshold is validated and **consumed by nothing in `scripts/Universal/` today**, confirmed by
  grep. This is the boundary the plan says Phase 4 replaces with captured-threshold tests.
- `test_preferences_ui.py:873` `test_phase_two_added_no_later_phase_behaviour` — asserts
  `preferences_ui.py` contains none of `reserve_run`, `Retry Failed`, `Pause`, `Resume`,
  `large_result_warning_threshold`, `Add Book`. Plan 3 does not touch that module, so this guard
  stays valid.
- `test_prototype_regression.py:432–460` — `FORBIDDEN_TEXT` blocks `summary`, `details`, `eta`,
  `retry`, `pause`, `resume`, `filter`, `add book`, `duplicate book`, `remove book` from
  appearing as widget text in the shipped M4B Metadata Editor, and forbids a `ttk.Notebook` in
  it. Because Plan 3 adopts nothing into a production panel, this must **continue to pass
  unchanged** and is the sharpest available proof of the non-adoption boundary.

**Genuine drift from the plan, all minor:**

1. **The two failing packaging tests above** — the one substantive item. The plan's §1.1
   anticipated that source/tests keep the *string*; it did not anticipate that one test asserts
   the *file's physical presence*.
2. The plan's §7 lists `files/tests/test_import_ui.py` **and** `files/tests/test_job_ui.py` among
   likely new tests. Given §6.15 puts every adapter in one `shared/job_ui.py`, one Tk-boundary
   module is likelier than two; recorded now so a later split or merge is a noted choice, not a
   silent one.
3. The plan says Phase 2 may reuse `maintenance.is_link`. It is public and importable at
   `maintenance.py:277`, but `shared/maintenance.py` also carries the whole cleanup catalog, so
   `shared/importing.py` importing it creates an importing→maintenance edge that does not exist
   today. Flagged for Phase 2's risk gate; **no refactor is proposed or authorized here**.
4. Read-only note, out of Phase 0's authorized edit set: `md-instructions/Briefing.md:384` still
   describes the untracked template as sitting "directly beside `config.toml`". That sentence is
   a *description* of the packaging contract, not an instruction to preserve the file, so it was
   left alone — Phase 0 may edit only `Handoff.md`, the master index's current status/contract,
   and this drop's status fields. A later authorized documentation phase can reword it.

#### Superseded instructions updated in this phase

`md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
said, in §4 and §10, to *preserve* the local `config-template.toml` exactly. Both statements are
now replaced by the absence contract and marked as superseded. **Historical Plan 2 phase records
were not rewritten** — they accurately state that the file existed, untracked and unchanged,
while Plan 2 ran.

#### Open items carried out of Phase 0

1. ~~**`verify.py` is FAILING at the baseline**, solely through
   `test_release_packaging.py:147`. It must be repaired by the first phase authorized to edit
   `files/tests/`, and the honest fix is to make the precondition tolerate the file's absence
   (or drop the worktree-dependent test in favour of the synthetic-root one that already proves
   the property) — **not** to recreate the template and **not** to weaken line 149.~~
   **RESOLVED 2026-08-08 in Phase 1** — the maintainer approved option (a) and the precondition
   was narrowed in place. See the Phase 1 record above.
2. The `verify.py` skipped-suite blind spot (master index §14) claimed a third victim here.
   Still unowned; do not misreport skips because of it.
3. Everything already carried from Plan 2 — live macOS, the Windows 125% matrix, Windows DPI
   unawareness, M4B Converter clipping at `920×600`, Windows xHE-AAC, and the clean-machine
   install — remains open and untouched.

#### Next action

**Phase 1 — Pure contracts and compatibility boundaries.** **Not started.** It requires explicit
maintainer approval before any work begins, and it must not be started in the same turn as this
summary.

---

## Previous Focus (v0.6.0 Drop 2 — Plan 2, approved 2026-08-08, merged through PR #3)
**v0.6.0 Drop 2 (Plan 2 — configuration, output, and application-maintenance foundation) —
COMPLETE, MAINTAINER-APPROVED AND CLOSED (2026-08-08), and since merged into `master` through
pull request #3 as merge commit `563df9884497032e19abd4437a0e66584cd9ec12`.** The sections below
are the record as written at closeout, when the branch was still unmerged; they are left
historically accurate rather than rewritten.

### Phase 9 — Plan 2 approval closeout and temporary-drop retirement (2026-08-08, HOME-PC)

**Plan 2 is approved.** The maintainer approved Phase 8 at
`0e7ad0c264cb2a46f3c64f968e24f00963cb1987` — the original implementation
(`88a64dce840d8fe7e3305818eac3ad659fb3555e`) and its remediation accepted together — and Plan 2
as a whole. Phase 9 is a **documentation and retirement commit**: no application behaviour, no
UI, no packaging, no configuration and no screenshot changed, and `version.py` is still `0.5.1`.

**What moved where.** `Briefing.md` gained the lasting configuration/output/maintenance
architecture (the two destination exceptions, the display-hint-versus-reservation rule and the
new live refresh, the four-asset downloaded-data catalog and the post-exit coordinator, and the
explicit-scope packaging contract), plus the Plan 2 approval paragraph, the validation summary
and both deferrals. `Changelog.md` gained four `[Unreleased]` entries — packaging, the two
fixes, and this closeout — with **no v0.6.0 release heading**. `Decisions.md` gained one signed,
dated ADR covering the four non-obvious choices (explicit-scope packaging, ffmpeg's documented
concat quoting, the shared display registry, and recording the two deferrals as deferrals); no
historical entry was rewritten and Decisions 1–55 were not reopened. The master implementation
index now shows Drop 2 complete and approved and Drop 3 as the next unopened drop, with the
nine-plan sequence unchanged.

**The temporary drop was retired** — `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md`,
54,346 bytes, SHA-256 `faa83b0ffe4c85f54f8e788ff5eed0ecbdc52c99929c670d5d8e4079fb1e8920` —
deleted by exact path only, after the transfer above, exactly as its own Phase 9 directs
(deletion, not archival). Nothing under `md-instructions/don't-delete/` was touched, and no
tracked document now depends on the retired file as its only source of truth.

#### The final Plan 2 record, in one place

| | |
|---|---|
| Branch | `feature/0.6.0-drop2-config-output-maintenance-foundation` — **not merged** |
| Start SHA | `bada8a3dee87acf6a6619252bd31cdee429f1711` |
| Phase 8 approved at | `0e7ad0c264cb2a46f3c64f968e24f00963cb1987` |
| Version | `0.5.1` — unchanged, no tag, no release, no published archive |
| Tests | 1074 collected, 1069 passed, 5 documented skips, 1 pre-existing warning, all 17 theme tests executed |
| Gates | `scripts/verify.py` `RESULT: PASS`; compile gate; `git diff --check`; canonical-name/alias gate; protected-folder gate |
| Windows matrix | **46/46 PASS**, after a recorded **44/46** first pass and two fixes |
| Screenshots | twelve 100% images under `files/UI-Prototype-Screenshots/v0.6.0-drop2/`; the ten Plan 1 images unchanged |
| Live TTS | Edge TTS `en-US-SteffanNeural`, 254,925-byte MP3, 12.66 s measured |
| `config-template.toml` | untracked, unstaged, byte-identical `94b05edc3211efe531be018fbc442c240df8db42`, never loaded, absent from both archives |

#### Carried limitations and deferrals — none of these is a pass

1. **Live macOS validation was not performed for Plan 2.** The aqua path is import- and
   build-tested only. Automated aqua coverage is explicitly **not** a live pass. Deferred by
   maintainer decision on 2026-08-07.
2. **The Windows 125% scaling/screenshot matrix was not performed.** Windows stayed at true
   100% throughout Phase 8 and its remediation; no registry edit or DPI simulation was used.
   By maintainer decision this pass belongs to the **later dedicated UI-compression/no-scroll
   phase**, after the remaining features land and the layout is stable — that pass will do the
   final layout compression, verify the maximized no-scroll goal, and retest 100% **and** 125%
   against the stable interface. Do not reopen it before then.
3. **The application is DPI-unaware on Windows** (Plan 1 finding, unchanged). Nothing clips or
   reflows at 125% because the whole window is bitmap-scaled uniformly; text is softer.
4. **M4B Converter clipping at the `920×600` minimum** (~19 px primary action, ~108 px + 75 px
   Log) remains, deferred to that panel's later conversion.
5. **Windows xHE-AAC decode** remains a confirmed limitation since v0.3.2.
6. **A fresh one-click clean-machine install** is verified in pieces, not on a virgin box.

#### Standing requirement carried forward — NOT part of Plan 2, NOT transferred yet

Recorded here only so it is not lost. It was **not** implemented, **not** documented as done,
and **not** transferred into the protected planning records during Phase 9, because the Plan 2
drop does not assign that transfer. It belongs to the later UI-compression/no-scroll planning
pass and the Drop 3 fresh-chat handoff:

- remove the visible "Trim Edge TTS padding" checkbox and the individual timing controls, while
  **keeping the underlying trimming/padding behaviour**;
- tested internal defaults must give natural batch joins across every currently exposed Edge TTS
  voice;
- Kokoro must be checked independently for equivalent joining, clipping, silence and pacing
  problems;
- broader timing customisation belongs to the later TTS-focused v0.7.x series.

#### Next action

**Plan 2 integration review only.** The branch is integration-ready; merging, tagging, bumping
the version and publishing a release are all outside every phase of this plan and were not done.
Drop 3 (shared importing and job controls) is the next unopened implementation drop: it has not
been drafted or started, and it needs new explicit maintainer direction in a fresh session.

### Phase 8 — Packaging, cross-platform regression, and manual approval gate (2026-08-07, HOME-PC)

**Result: both release archives now carry the committed root `config.toml`, and the complete
Plan 2 behaviour has been exercised in a genuine clean extraction of the Windows archive.**
Packaging: one production file modified (`shared/release.py`), one test file added, twelve
screenshots added. The remediation below then corrected two defects this phase's own manual
matrix exposed. `version.py` is still `0.5.1`. **Phase 9 was not started.**

**Phase 8 start SHA:** `1eddc5163b4ad81f858d30b7df75fd2a28188da9` (approved Phase 7). The
ending SHA is the commit carrying this section.

**Phase 8 is complete but NOT approved.** It awaits the maintainer's manual review of the
returned screenshots and evidence package. The first pass was rejected on 2026-08-07; see
the remediation immediately below, which supersedes the amended rows in the matrix and the
amended findings.

#### Phase 8 remediation (2026-08-07) — two defects the manual matrix exposed, now fixed

The first Phase 8 pass (`88a64dce840d8fe7e3305818eac3ad659fb3555e`) found two real defects and
then mis-scoped them. Both are corrected here, and the claims below that contradicted the
observed behaviour have been amended rather than left standing.

**Why they were not out of scope.** The apostrophe failure was diagnosed as pre-existing
(`mp3_tool.py`'s escaping dates to `5459d3d`, 2026-05-28, untouched by Phase 4) and reported as
outside Plan 2. That reasoning was wrong: Plan 2's own contract lets the user choose the output
base and requires spaces, Unicode and apostrophes to work, so a user-selected folder that breaks
a tool is a Plan 2 defect regardless of which commit introduced the faulty line. The stale label
is likewise part of the preference contract — the application must not display a destination it
would not use.

**Correction 1 — ffmpeg concat-list serialization.**
Root cause: `ffmpeg_escape_listfile_path` wrapped the path in single quotes and then wrote a
quote as `\'`. Inside single quotes ffmpeg treats every character literally, so the backslash
escaped nothing and the `'` was read as the **closing** quote; the path silently truncated
there and the rest became stray tokens. The same function also doubled every backslash, which
survived only because Windows collapses repeated path separators and would corrupt a genuine
backslash. Both failed identically on the fast and safe paths, so `combined.mp3` was never
produced.

The fix uses ffmpeg's documented form (ffmpeg-all, *Concat demuxer* and *Quoting and escaping*,
which gives the example `file '/mnt/share/file 3'\''.wav'`): close the quote, emit an escaped
quote outside it, reopen. Everything else inside the quotes is left exactly as-is, so
backslashes, spaces and non-ASCII need no treatment at all. The list is written UTF-8 with
explicit `newline="\n"`. A path containing a line break now raises rather than producing a
listfile the demuxer would misread — the demuxer is line-oriented and cannot represent one.

Nothing else moved: argument-vector execution is unchanged, no path is interpolated into a
shell command, `shlex.quote` remains confined to the human-readable error log, input order is
preserved, the fast-path/fallback structure is untouched, and concat lists still live inside the
operation's own `build/` directory under the reserved run folder.

**Correction 2 — live output-location refresh.**
Each panel read `destination_hint(TOOL_KEY)` once at build time into a read-only variable, and
the launcher builds panels lazily then reuses them, so a panel that already existed kept showing
the old base. `output_paths` now carries a small registry: `register_destination_hint()` records
the variable a panel already owns, and `refresh_destination_hints()` re-points every live
registration through the same `destination_hint` resolution. `PreferencesDialog` calls it from
exactly two places — the successful `_commit` and the successful `reset_preferences` — so a
rejected, cancelled or unsaved value can never reach a panel. Dead registrations are dropped on
first touch rather than raised over, because refreshing a label must never break the call that
just saved a preference. No panel is rebuilt or destroyed, no panel gained a constructor
argument, no panel resolves a path itself, and reservation still re-reads the effective
configuration at operation start.

**Files changed in the remediation**

| Path | Change |
|---|---|
| `scripts/Universal/mp3_tools/mp3_tool.py` | escaper rewritten + registration, ~+30 / −4 |
| `scripts/Universal/shared/output_paths.py` | the hint registry, ~+58 |
| `scripts/Universal/shared/preferences_ui.py` | import + two refresh calls, ~+9 / −1 |
| `scripts/Universal/tts/epub2tts_gui.py` | registration, +3 |
| `scripts/Universal/mp3_tools/m4b_converter.py` | registration, +3 |
| `scripts/Universal/mp3_tools/m4b_maker.py` | registration, +3 |
| `scripts/Universal/mp3_tools/cover_resizer.py` | registration, +3 |
| `scripts/Universal/mp3_tools/m4b_metadata_editor.py` | registration, +3 |
| `files/tests/test_mp3_concat_paths.py` | **added**, 25 tests |
| `files/tests/test_output_location_refresh.py` | **added**, 41 tests |
| `files/tests/test_tool_output_integration.py` | one guard restated, ~+30 / −3 |

The Phase 3 guard `test_preferences_still_reserves_no_output` asserted the *string*
`output_paths` never appeared in `preferences_ui.py`. Preferences now legitimately imports it to
refresh a display, so that check no longer expressed the rule. It was **strengthened, not
relaxed**: it now parses the module and requires that the only `output_paths` member Preferences
touches is `refresh_destination_hints`, and that it calls nothing which reserves, creates or
plans a destination (`reserve_run_directory`, `ensure_output_base`, `ensure_tool_parent`,
`mkdir`, `makedirs`, `touch`, `plan_destination`, `destination_hint`).

**Manual retest (2026-08-07, Windows 11 Pro 10.0.26200, 1920×1080, true 100% scaling)**

Disposable test root: `…\scratchpad\Phase 8 clean extract Ré'sumé` — the retained Phase 8
extraction, proven separate from the real repository again before use (distinct, neither
contains the other, not an ancestor of it, not a drive root, not the home directory, not the
workspace root). Its `scripts/` tree was replaced from the **rebuilt Windows archive**
(SHA-256 `0d8d7b217f20e685b5c4ed0335add023734f81927901184b8b5bbd14914a5278`), so the code under
test still has archive provenance; its `.venv` and pinned install were kept because
`requirements.txt` did not change. Fixtures and outputs both live in fresh disposable folders
whose names carry a space, an apostrophe and non-ASCII characters:
`…\scratchpad\P8r fixtures Ré'sumé Ñ\o'clock inputs\` and `…\scratchpad\P8r outputs Ré'sumé Ñ`.

MP3 combine, with an apostrophe in the output base, the parent input directory **and** both
filenames (`1 o'clock Ré tone.mp3`, `2 o'clock Ré tone.mp3`, 2 s and 4 s):

- the generated list is
  `file 'C:\…\P8r fixtures Ré'\''sumé Ñ\o'\''clock inputs\1 o'\''clock Ré tone.mp3'` — the
  documented close-escape-reopen form, backslashes untouched;
- `combined.mp3` produced at
  `…\P8r outputs Ré'sumé Ñ\MP3-Tool-Outputs\MP3-Tool-2\combined.mp3`, 27,272 bytes;
- `ffprobe` validates it: `mp3`, 44,100 Hz, 1 channel, **duration 6.000000 s** — exactly
  2 s + 4 s;
- order preserved: `combined_time-stamps.txt` reads `01. 1 o'clock … @ 00:00.000 (+00:02.000)` /
  `02. 2 o'clock … @ 00:02.000 (+00:04.000)`;
- the **fast path** succeeded — only `inputs_fast.txt` exists in `build/`, there is no
  `inputs_safe.txt`, no `wavs/` directory and no `ffmpeg_log.txt` at all;
- run numbering held: an earlier single-file combine took `MP3-Tool-1` and this one took
  `MP3-Tool-2`, with `MP3-Tool-1` untouched;
- both sources are byte-identical afterwards (`2d68f304ac61ce0e…`, `14da7e0c794b0020…`) and no
  file was written beside them;
- the concat list stayed inside its own run's `build/` folder — nothing was left anywhere else.

**The "empty-bodied error dialog" claim is withdrawn.** It was an artifact of capturing native
message boxes with `PrintWindow`, not a product defect: reading the dialog's text directly gives
`Combine complete.` / `Output: …\MP3-Tool-2\combined.mp3`, and the failure branch already
supplies `FFmpeg failed.` plus the log path. No error-reporting code was changed.

Output-location refresh, with all six panels built first and the MP3 Tool panel left visible:

| Action | Observed |
|---|---|
| Save a custom base (`…\P8r outputs Ré'sumé Ñ`) | The visible MP3 Tool panel changed from `…\Downloads\Audiobook-Creation-Tool-Outputs\MP3-Tool-Outputs` to `…\P8r outputs Ré'sumé Ñ\MP3-Tool-Outputs` **immediately** — no run, no tool switch, no rebuild, no restart |
| The other already-built panels | TTS, M4B Converter, M4B Maker and Cover Image all show `…\P8r outputs Ré'sumé Ñ\<Tool>-Outputs`. M4B Metadata's row sits below its panel's visible scroll area, so its refresh is covered by the automated registration and refresh tests rather than by eye |
| Displayed vs actual | The combine reserved `…\P8r outputs Ré'sumé Ñ\MP3-Tool-Outputs\MP3-Tool-2`, under exactly the folder the panel displayed |
| Invalid path (`still/relative`) | Refused with the same precise message; **no** panel label moved to the rejected value |
| Cancelled reset | Nothing changed anywhere |
| Confirmed reset | Every panel returned to `…\Downloads\Audiobook-Creation-Tool-Outputs\<Tool>-Outputs` immediately, again with no restart or rebuild |
| Failed settings write | Not forced live; covered by two automated tests (a `set_output_base` that returns `False`, and one that raises `OSError`) — both leave every label at the prior effective value |

`920×600` regression at 100%: requesting 600×400 clamped to a 922×632 frame, i.e. a client area
of exactly **920×600**. All six sidebar entries, Import/Remove Selected/Clear List, the Output
folder row, **Combine MP3s → One MP3**, the status line, "Preferences & Data…" and "Open log
folder" are all fully visible and unclipped; the panel's own content region scrolls locally and
the window itself does not scroll. No whole-window scrolling was introduced. No UI compression
was attempted.

**Screenshots: all twelve preserved byte-for-byte.** Neither correction changes the visible
content of any committed image — the concat fix has no UI at all, and the refresh fix only alters
a label *after* a preference change, which no committed screenshot depicts. All twelve Phase 8
hashes and all ten Plan 1 hashes were re-verified after the remediation and are unchanged, so
nothing was recaptured.

**Display scaling.** Windows stayed at **true 100% on both displays** throughout this
remediation (`GetDpiForMonitor(MDT_EFFECTIVE_DPI)` = 96 before and after); the maintainer was
not asked to change it, no registry edit or other DPI simulation was used, and the 125% matrix
was not run. Per the maintainer's standing policy, 100% is the working scaling for the remaining
feature drops and the true 125% pass belongs to the later dedicated UI-compression/no-scroll
phase, which will perform the final layout compression, verify the maximized no-scroll goal, and
retest 100% and 125% against the stable interface.

**Live macOS remains explicitly deferred and untested.** Nothing in this remediation changed
that, and no macOS check was run.

**Testing after the remediation:** 1074 collected, 1069 passed, 5 skipped, 1 warning. The
increase reconciles exactly to the new tests: 1008 + 25 (`test_mp3_concat_paths.py`) + 41
(`test_output_location_refresh.py`) = 1074; 1003 + 25 + 41 = 1069. Skips (5) and the one
`audioop` `DeprecationWarning` are unchanged. All 17 theme tests executed and passed.
`scripts/verify.py` → `RESULT: PASS`; compile gate exit 0; `git diff --check` clean over
`scripts` and `files/tests`.

**Phase 9 remains unstarted.** No permanent-document transfer, no drop deletion, no merge, bump,
tag, release or publication.

#### Packaging — the narrowest change that satisfies the contract

`shared/release.py` gained a `ROOT_FILES = ("README.md", "config.toml")` constant; the
per-OS builder validates and writes that named list instead of `README.md` alone. Nothing
else changed: the same single `scripts/` walk, the same exclusion sets, the same forced
`0o755` launcher mode, the same `version.py` source of truth.

The safety argument is **explicit scope, not exclusion**. The packager names three root
files and walks exactly one tree. A file it never names cannot leak because somebody forgot
to extend a list — which is precisely why the maintainer's untracked root
`config-template.toml`, sitting directly beside `config.toml`, has never needed an exclusion
rule and still does not have one. `release.py` contains no reference to it at all; the
existing `test_repository_contract` guard would fail if it ever did.

#### The archives (built with the real entry point, `python scripts/Universal/shared/release.py`)

| | Windows | macOS |
|---|---|---|
| Name | `AudiobookTool-Windows-v0.5.1.zip` | `AudiobookTool-MacOS-v0.5.1.zip` |
| Size | 228,283 bytes | 230,517 bytes |
| SHA-256 | `77d1e7002bf1ba10716ee8adc9a77b5f23166e332dbb46d3c04d856c171fc1b2` | `387ba241e9ea4a0e8951457473eb6d1829e5d74cb2c136d02d8ce4e759004a1f` |
| Members | 43 (43 unique) | 43 (43 unique) |
| Root entries | `README.md`, `config.toml`, `Setup_and_Run-audiobook-creation-tool.bat`, `scripts/` | `README.md`, `config.toml`, `Setup_and_Run-audiobook-creation-tool.command`, `scripts/` |
| `config.toml` | present exactly once, byte-identical | present exactly once, byte-identical |
| Launcher mode | `0o755` | `0o755` |
| Opposite launcher | absent | absent |

Committed `config.toml` SHA-256 `6ca21b6e6f3789c150b0f85c24afac511237cad82b6ab5ed5e4457af957520c1`
(3,539 bytes) — identical in both archives and in the extraction.

Absent from both: `config-template.toml`, the opposite launcher, `.venv/`, `.git/`,
`.claude/`, `.codex/`, `files/`, `md-instructions/`, `dist/`, `test-logs/`, `__pycache__`,
`.pyc`/`.pyo`/`.pyd`, `settings.json`, session logs, models, maintenance state, any
`cleanup-*` file, screenshots, `.DS_Store`, `Thumbs.db`. Every member is relative, free of
`..`, free of drive letters and backslashes, and resolves inside the extraction root; there
are no duplicate members. Two consecutive builds produce identical `(name, size, CRC)`
manifests.

The archives were built to `dist/` (gitignored) and **not published, uploaded, attached to a
release, or tagged**. No prior archive was overwritten — no `v0.5.1` zips existed before.

#### The clean extraction (Windows)

Real root: `…\MyProjects\Home-PC\Audiobook-Creation-Tool`. Disposable extraction root:
`…\Repository_Workspaces\scratchpad\Phase 8 clean extract Ré'sumé` — a **new** location
carrying a space, an apostrophe and a non-ASCII letter. Proven before anything ran: the two
paths differ, neither contains the other, the extraction is not an ancestor of the real
repository, not a drive root, not the home directory and not the workspace root.

- 43 members extracted; the on-disk file list equals the archive manifest exactly.
- Extracted `config.toml` byte-identical to the committed file; `config-template.toml` absent;
  no `.venv`, `.git`, `files/`, `md-instructions/` or `dist/`.
- The **real `.bat` launcher** was invoked (never an internal bootstrap function), with
  `VIRTUAL_ENV` cleared and the real repository's `.venv\Scripts` stripped from `PATH` — the
  contamination lesson from the Phase 7 addendum, applied from the start this time.
- First-run setup detected the absent environment through the production path: the intro
  dialog appeared, preflight reported `[OK]` for Python ≥ 3.11, venv, tkinter, Tcl/Tk, ssl,
  ffmpeg and ffprobe, then `Creating virtual environment at …Phase 8 clean extract Ré'sumé\.venv…`,
  `Virtual environment created.`, the **full pinned install** (114 packages including torch,
  kokoro, spacy, transformers), `All required packages import cleanly.`, and
  `ffmpeg already on PATH: C:\ffmpeg\bin\ffmpeg.EXE`.
- The optional Kokoro pre-download was **accepted** on this first run and the 327 MB
  `kokoro-v1_0.pth` landed in the in-tree cache.
- The application opened from the extraction's own `.venv\Scripts\pythonw.exe` (pid 19392 →
  base-python redirector child pid 20468 owning the window).
- Configuration is read from the extraction: `paths.REPO_ROOT` is the extraction root, the
  loaded `config.toml` hashes to the committed value, and no path under the real repository
  appears on `sys.path`.
- Runtime state was created only at its intended runtime locations — `files/runtime-data/`
  with `logs/`, `models/` and `settings.json` inside the extraction. Nothing was written to
  the real repository and nothing to the real `Downloads` folder.
- Closed normally with the window's own close path; both processes exited and `settings.json`
  was rewritten.
- The second launch used the healthy fast path: `Kokoro health-check: ok` → launch, in
  **1.7 s**, with no pip, no venv creation, no repair dialog and **no `cmd.exe`/`conhost.exe`
  process** associated with the extraction.

**macOS clean extraction was not performed** — see the approved deferral below. The macOS
archive's contents, exclusions and `0o755` launcher mode are verified by automated test and
by direct archive inspection; its launcher was never executed.

#### Windows manual matrix — every row observed in the clean extraction

**Amended 2026-08-07.** Rows 14 and 46 originally read PASS; the manual matrix had in fact
exposed an apostrophe-path failure in MP3 Tool, and the summary claim of "46/46 PASS" was
incompatible with it. Both rows now record what was first observed **and** the retested
result after the remediation. The final tally is **46/46 PASS after remediation; 44/46 on
the first pass**.

Windows 11 Pro 10.0.26200, 1920×1080, **100% scaling (effective DPI 96 on both displays)**,
Python 3.12.10 in the extraction's own `.venv`, commit `1eddc516…` plus the Phase 8 working
tree. All fixtures are synthetic (ffmpeg sine tones, plain text, a solid-colour PNG) in
disposable folders; the `ffmpeg`/`ffprobe`-on-PATH precondition from the repository's
audio-processing skill was asserted before generating them.

| # | Check | Result |
|---|---|---|
| 1 | Valid committed configuration | **PASS** — no warnings, defaults in force |
| 2 | Malformed TOML | **PASS** — every value falls back; one clear warning |
| 3 | Partly invalid (`base_directory` relative, `max_sessions` 99999) | **PASS** — both fall back per key; the unrelated valid `large_result_warning_threshold = 500` is **kept** |
| 4 | Unknown table `[nonsense]` | **PASS** — ignored, reported once as "contains entries this version does not use" |
| 5 | Missing `config.toml` | **PASS** — full fallback, one warning |
| 6 | Once-per-launch warning | **PASS** — dialog shown once; a second `take_launch_warning()` returns `None` in all four cases; the status bar keeps the short form |
| 7 | Output base: default | **PASS** — `Downloads/Audiobook-Creation-Tool-Outputs` |
| 8 | Output base: custom selection + Save | **PASS** — written to `settings.json` only, Unicode and apostrophe preserved exactly |
| 9 | Output base: invalid (relative) path | **PASS** — refused with a precise message, effective location unchanged, nothing written |
| 10 | Output base: reload | **PASS** — dialog and newly built panels show the saved custom base |
| 11 | Reset Preferences | **PASS** — `settings.json` → `{}`; dialog refreshes live; all six produced output files remain |
| 12 | TTS Audiobook standard route | **PASS** — `TTS-Audiobook-Outputs/TTS-Audiobook-1` |
| 13 | M4B Converter standard route | **PASS** — `M4B-Converter-Outputs/M4B-Converter-1/tiny book.mp3` |
| 14 | MP3 Tool standard route | **FAILED on the first pass**, **PASS after remediation** — the run directory was always reserved correctly, but with an apostrophe in the path no `combined.mp3` was produced. Retested 2026-08-07: 27,272 bytes, 6.000000 s, correct order. See finding 1 |
| 15 | M4B Maker standard route | **PASS** — `M4B-Maker-Outputs/M4B-Maker-1/audiobook.m4b` |
| 16 | Cover Image standard route | **PASS** — `Cover-Image-Outputs/Cover-Image-1/cover art.png` |
| 17 | M4B Metadata standard route | **PASS** — `M4B-Metadata-Outputs/M4B-Metadata-1/tiny book.m4b`, copy-only |
| 18 | Repeat-run numbering | **PASS** — an identical second TTS run reserved `TTS-Audiobook-2`; run 1 untouched |
| 19 | Folder mirroring (one root) | **PASS** — `batch root/` mirrored directly into `TTS-Audiobook-3/` |
| 20 | Validation before reservation | **PASS** — a bad Maker destination was refused and **no** run directory was created |
| 21 | Source preservation | **PASS** — every fixture byte-identical after all runs; no file written beside a source |
| 22 | Cover: default (numbered copy to the run folder) | **PASS** |
| 23 | Cover: save beside source, numbered copies | **PASS** — `beside me-1.png` created, original byte-identical |
| 24 | Cover: replacement off by default | **PASS** — "Save beside source images" unchecked; sub-options disabled; "Create numbered copies" preselected |
| 25 | Cover: confirmed replacement | **PASS** — strong confirmation naming the count, permanence, the temp-then-install mechanism and partial-failure honesty; **Cancel holds initial focus**; after confirming, the original was replaced in place |
| 26 | M4B Maker custom destination | **PASS** — writes directly into the chosen folder, no run folder; the standard base gained no `M4B-Maker-2`; sources untouched |
| 27 | Itemized downloaded-data inventory | **PASS** — four rows with status and size |
| 28 | No default cleanup selection | **PASS** — opens "Nothing selected."; "Review Selected Data…" disabled |
| 29 | Missing/unsafe row disabled | **PASS** — "Portable binaries — Missing —" is greyed; clicking it does not select it |
| 30 | Accurate sizes | **PASS** — 1.2 GB / 312.1 MB / 52.4 KB against independently measured 1,303,927,924 / 327,276,837 / 53,687 bytes |
| 31 | Confirmation content | **PASS** — items, freed estimate, close notice, per-item effects, exclusion notice, final question; **Cancel holds initial focus** |
| 32 | Cancellation | **PASS** — returns to the inventory, nothing deleted, no request written |
| 33 | Disposable post-exit cleanup | **PASS** — GUI closed first, coordinator pid 304 removed exactly the three selected assets |
| 34 | Truthful result | **PASS** — recorded bytes `1303927924 / 327276837 / 53829` match the measurements |
| 35 | `.venv` rebuild through the normal launcher | **PASS** — full pinned reinstall, imports clean, application relaunched |
| 36 | One-time result presentation | **PASS** — report shown once, retired to `cleanup-result.presented.json`, absent on the next launch |
| 37 | No cleanup replay | **PASS** — coordinator log records exactly one helper run; no new request |
| 38 | Keyboard navigation | **PASS** — Tab moves focus into the cleanup rows, Space toggles, the status and enablement update |
| 39 | Escape | **PASS** — closes the cleanup dialog and the Preferences dialog without acting |
| 40 | Window close | **PASS** — `WM_CLOSE` exits cleanly every time and rewrites `settings.json` |
| 41 | Single-instance Preferences | **PASS** — two clicks produce one dialog |
| 42 | Single-instance cleanup | **PASS** — two clicks produce one dialog |
| 43 | `ACT.*` styling on converted surfaces only | **PASS** — launcher shell and M4B Metadata carry the dark design system; the other five panels keep their historical native ttk look, unchanged |
| 44 | Ordinary launcher / fast path | **PASS** — first run installs, later runs launch in ~1.7 s |
| 45 | No persistent console | **PASS** — expected setup console on first run only; no `cmd.exe`/`conhost.exe` and no visible console on the fast path |
| 46 | Spaces, Unicode, apostrophes end to end | **PARTIAL on the first pass, PASS after remediation** — extraction root, venv creation, pip, launch, config, outputs, coordinator argv and maintenance paths were all correct, but MP3 Tool's concat list broke on an apostrophe. Retested 2026-08-07 with an apostrophe in the output base, the input directory and both filenames |

**Live TTS synthesis — PASSED (this closes the long-carried pending item).**
Engine **Edge TTS**, voice **en-US-SteffanNeural**. Input
`P8 fixtures Ñ'x\tiny narration.txt` (108 bytes, SHA-256 `cb198042f0db2799…`). Output
`P8 outputs Ñ'x\TTS-Audiobook-Outputs\TTS-Audiobook-1\tiny narration (en-US-SteffanNeural).mp3`,
254,925 bytes, **12.66 s** measured with `ffprobe`. Log read `Conversion finished.` at 2/2
100%. The source was byte-identical afterwards. A folder-batch run produced
`chapter one.mp3` (5.52 s) and `chapter two.mp3` (5.47 s) mirrored into `TTS-Audiobook-3`.
Kokoro was not exercised for synthesis; only Edge TTS was required, and no optional asset was
downloaded beyond the production-supported first-run pre-download.

#### The load-bearing proof that panels do not cache a stale destination

The TTS panel was already built when the output base changed, and its read-only "Output
folder" label kept showing the old base. The **run did not**: it reserved
`…\P8 outputs Ñ'x\TTS-Audiobook-Outputs\TTS-Audiobook-1` and wrote there. That is by design —
`reserve_run_directory()` re-reads the effective configuration at run start, so the label is
a hint and the reservation is the truth. Recorded as finding 2 below rather than as a defect.

#### Findings

1. **MP3 Tool "Combine MP3s → One MP3" fails when a path contains an apostrophe — pre-existing,
   outside Plan 2, not fixed.** With the output base `…\P8 outputs Ñ'x`, both the fast and
   safe concat paths failed with `Impossible to open …` and no `combined.mp3` was produced;
   the tool showed an empty-bodied message box rather than a clear error. Isolated by
   reproducing the tool's own escaping in four folders: plain **OK**, a space **OK**, a
   non-ASCII letter **OK**, an **apostrophe FAIL**. The cause is
   `mp3_tool.py:110`, which escapes `'` as `\'` inside a single-quoted ffmpeg concat entry;
   ffmpeg's concat demuxer does not honour that escape. `git log -L 110,110` dates the line
   to `5459d3d` (2026-05-28) and Phase 4 did not touch it, so the faulty line predates Plan 2.
   Re-running the identical combine with an apostrophe-free base (still containing a space and
   `Ñ`) produced `combined.mp3` (18,431 bytes) on the fast path. **Severity: Critical.**
   **FIXED on 2026-08-07 — see the remediation above.** The first pass wrongly called this
   out of scope on the grounds that it predated Plan 2; the maintainer correctly rejected
   that, because Plan 2's contract permits user-selected paths and requires apostrophes to
   work.
2. **A tool panel built before an output-base change shows a stale "Output folder" label.**
   Cosmetic only; the run reserves against the current configuration (proved above), and the
   label corrected itself only on the next run or the next panel build. **Severity: Minor.**
   **FIXED on 2026-08-07 — see the remediation above.** A user must not be shown a
   destination the application would not use, so this belongs to the Plan 2 preference
   contract rather than being acceptable as cosmetic.
3. **The optional Kokoro pre-download reports a problem on a clean machine.** During first-run
   setup the weights downloaded correctly (327 MB `kokoro-v1_0.pth`), but the warm-up
   synthesis failed with
   `Error processing file 'D:/a/espeakng-loader/…/espeak-ng-data\phontab': No such file or directory`
   and setup printed `Kokoro pre-download had a problem; voices will download on first use
   instead.` Setup then continued and launched normally. The path is baked into the
   `espeakng-loader` wheel, so this is a dependency issue, not Plan 2 code. **Severity: Minor
   (degrades gracefully). Not changed.** Kokoro synthesis itself was not exercised.

#### Explicitly approved deferrals — recorded as deferrals, never as passes

1. **Windows 125% display-scaling screenshot pass — DEFERRED by explicit maintainer decision
   on 2026-08-07.** Both displays were measured at effective DPI 96 (100%) via
   `GetDpiForMonitor(MDT_EFFECTIVE_DPI)`; changing Windows display scaling requires the
   maintainer's own action, and simulating it through a registry edit was neither permitted
   nor attempted. When asked whether to set 125% on the primary display, on the secondary
   display, or to defer, the maintainer chose **defer**. Phase 8 therefore ships a twelve-image
   **100%** set plus the 920×600 reachability evidence. **The 125% pass was not run and is not
   claimed.** The Plan 1 finding still stands and is unaffected: the application is
   DPI-unaware, so at 125% Windows bitmap-scales the whole window uniformly and nothing
   reflows or clips. **Standing policy, confirmed 2026-08-07:** Windows stays at 100% for the
   remaining feature drops, and the true 125% matrix is completed only in the later dedicated
   UI-compression/no-scroll phase, together with the final layout compression, the maximized
   no-scroll verification and a 100%/125% retest against the stable interface.
2. **Live macOS matrix — DEFERRED by explicit maintainer decision on 2026-08-07.** This
   session runs on HOME-PC (win32) with no Mac access, and `AI-WORKSPACE.md` records the
   HOME-MacOS workspace root as *"to be filled in — ask me for the workspace root before
   assuming any path"*, so no root was assumed. When asked to either supply the Mac root, hold
   Phase 8 open, or approve a recorded deferral, the maintainer chose **defer**. **No live
   macOS check was run. The automated aqua coverage is import- and build-level only and is
   explicitly NOT a live pass.** What *is* verified for macOS: the archive's exact contents and
   exclusions, that it carries only the `.command` launcher, and that the launcher is stored
   with mode `0o755` so a Finder extraction is immediately runnable. The `.command` launcher
   itself was never executed.

#### Screenshot evidence — `files/UI-Prototype-Screenshots/v0.6.0-drop2/`

Captured with `PrintWindow(PW_RENDERFULLCONTENT)` and cropped to the DWM extended frame
bounds, so each image is exactly what a user sees, with no invisible resize border and no
surrounding desktop. Every image was inspected at full resolution. No personal path, account
name, unrelated filename, notification, tooltip, cursor or transient window appears in any of
them; every visible path is a disposable Phase 8 folder or the standard Downloads default.

| File | Size | SHA-256 |
|---|---|---|
| `windows-100-launcher-maximized.png` | 1920×1032 | `468c52d62d37078f7f05472135bfcff415f7cac83100897d8d2bd9c57dd00eed` |
| `windows-100-launcher-minimum-size.png` | 922×632 | `16177adc71a7c447f4427e38a4cef7ee6f6ffeadd60e4ed4f0c49fd2c267bf50` |
| `windows-100-preferences-default.png` | 620×628 | `b1678d97bd51cd87d4e78088c8e1c09b3e4d113add5916de0b49b2184f3fce33` |
| `windows-100-preferences-invalid-path.png` | 655×629 | `33d68eafed39ddcc353919819c9cc0af97727f2039ab77ca1590fc283b2d7bf7` |
| `windows-100-preferences-custom-saved.png` | 626×646 | `e6c333c02b6897c17651a626044d3e2ce828d543a6f399a303839857bd8df6bc` |
| `windows-100-preferences-after-reset.png` | 629×628 | `590bfea42af9d65cf7b75e1a90fe084029d4a870a69ff9d96d70cd00cfdf179f` |
| `windows-100-config-warning.png` | 492×325 | `bd3bb051e5cc9b085662258174fa5ba585cb5a876a45191baab97f4b1c5e1cf2` |
| `windows-100-cleanup-inventory.png` | 633×445 | `2a7af66cd696c4f1bf69b9529cd4e2cc428daf9ed42f2c93c2e62eb6b0e8fba2` |
| `windows-100-cleanup-selected.png` | 633×445 | `6f097ea58522ba3955701e2ad27a4173844fdbc5f7ca94779373a0df869aff03` |
| `windows-100-cleanup-confirmation.png` | 759×523 | `266b1bea53fe2cc5b79d6c1dc46af0f0e8d40d2249944afd0ab0d0f724bb0117` |
| `windows-100-cleanup-result.png` | 490×275 | `9c3c6c2f71d74509d72cc31dca53406168fba8d669fed041ca0205e1429906b0` |
| `windows-100-cover-replace-confirmation.png` | 493×244 | `6809067f6c3102b9a228dd6531f97362271a65d70477457f44bb18622c17a2fa` |

Visual findings: labels, consequences and states are legible and complete at every size; no
control is clipped, overlapped or truncated; the destructive dialogs give Cancel the visible
focus ring while the destructive button carries no accent; the accent colour is reserved for
the safe primary action (Save, Continue, Review Selected Data… once a selection exists); the
Preferences dialog grows from 620×628 to at most 655×646 to accommodate a message line and
never needs whole-dialog scrolling; the `ACT.*` dark treatment appears on the launcher shell
and the converted M4B Metadata panel only, and the five unconverted panels keep their
historical native ttk appearance exactly as Plan 1 left them.

**920×600 reachability — PASS.** Requesting a 600×400 window produced a clamped
922×632 frame, i.e. a client area of exactly **920×600** — `MIN_SIZE` enforced. At that size
all six sidebar entries, all four primary actions (Save Tags, Clear All Tags, Remove Series
Numbering, Cancel), the progress bar, the status line, "Preferences & Data…" and "Open log
folder" are fully visible and unclipped. The growing regions (file list, metadata form, Log)
carry their **own** local scrollbars; the window itself never scrolls. Preferences & Data
opens from the minimum-size window at its own bounded 620×628 and is fully visible.

**The ten approved Plan 1 images were not touched.** All ten SHA-256 values were recorded at
the Phase 8 gate and re-verified after the new evidence was captured; all ten are unchanged.

#### Testing

Repository virtual environment, Python 3.12.10.

| Focused suite | Result |
|---|---|
| `test_release_packaging.py` | 34 passed |
| `test_config.py` + `test_repository_contract.py` | 108 passed |
| `test_maintenance` + `cleanup_state` + `cleanup_worker` + `cleanup_handoff_ui` + `preferences_maintenance_ui` | 399 passed |
| `test_preferences_ui.py` + `test_settings.py` | 90 passed, 1 warning |
| `test_output_paths.py` + `test_tool_output_integration.py` | 214 passed, 1 skipped, 1 warning |
| `test_cover_source_side.py` + `test_maker_custom_destination.py` | 64 passed, 1 skipped |
| `test_launcher_smoke` + `bootstrap_python_version` + `bootstrap_setup_logging` | 20 passed, 1 warning |
| `test_ui_theme.py -v` | **17 passed — all 17 executed, none skipped** |

Complete suite: **1008 collected, 1003 passed, 5 skipped, 1 warning**, before and after the
commit. Reconciliation against the Phase 7 baseline is exact: 974 collected + **34** new
packaging tests = 1008; 969 passed + 34 = 1003; skips unchanged at 5; warnings unchanged at 1.
No collection loss, no execution loss, no transient Tk/display skip burst — the GUI suites
executed cleanly on the first run.

The five skips are the same five carried since Phase 3, each still named for its own reason
(missing local media fixtures). The single warning is the pre-existing
`DeprecationWarning: 'audioop' is deprecated` raised by `pydub` under Python 3.12.

#### Verification gates

- `python scripts/verify.py` → **`RESULT: PASS`** (pytest, deps `==`-pinned, docs, 4 canonical
  names with no alias and 4 permanent references, `config.toml` valid at version 0.5.1).
- Compile gate `compileall -q scripts files/tests` → exit 0.
- `git diff --check` → clean, exit 0. The accepted CRLF-in-blob condition on the four canonical
  documents is retained: `Handoff.md` was edited **in CRLF** to match its existing blob, so no
  whole-file renormalisation appears in the diff and no permanent document was normalised
  merely to silence an inherited notice. No changed code file carries a whitespace defect.
- Canonical documents: exactly `Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md`;
  no case alias. `md-instructions/don't-delete/` retains all four references.
- Source-level guards, all asserted by the new suite: `config-template.toml` is neither
  packaged nor loaded (the string appears nowhere in `release.py`, and only once in
  `maintenance.PROTECTED_RELATIVE`); maintenance state cannot be packaged (`files/` is out of
  scope and no member starts with it); the packager is never imported by any application
  module and imports nothing from the application; building is not part of startup; ordinary
  launch runs no cleanup without a validated request; no GUI-side deletion exists; the catalog
  is still exactly four IDs; no arbitrary path can reach cleanup.

#### The real repository was untouched

The whole matrix ran in the disposable extraction and in disposable fixture/output folders.
Verified afterwards: the real `.venv` is present and was never inventoried, modified, deleted
or rebuilt; no `files/runtime-data/maintenance` folder exists; no `cleanup-*` file exists
anywhere under `files/`; no `Audiobook-Creation-Tool-Outputs` folder was created in the real
Downloads folder; `config-template.toml` remains untracked, unstaged and byte-identical at
`94b05edc3211efe531be018fbc442c240df8db42`. `dist/` (gitignored) gained two v0.5.1 archives
and no existing archive was overwritten.

#### Plan 2 — Definition of Done

| Item | Status |
|---|---|
| Phase 0 started from `origin/master` with the Plan 1 merge, on the Plan 2 branch | **MET** |
| `config-template.toml` untouched and absent from commits/releases | **MET** — hash unchanged; absent from both archives |
| Four canonical docs keep exact names, with an automated alias gate | **MET** |
| `don't-delete` references and master index intact | **MET** |
| A documented valid root `config.toml` is committed | **MET** |
| Safe fallback and warning for missing/malformed/invalid config, unrelated valid values kept | **MET** — matrix rows 1–6 |
| Precedence: code defaults → TOML → allowlisted user settings | **MET** |
| GUI writes settings only, never TOML | **MET** — `config.toml` byte-identical after the whole matrix |
| Preferences and Data works on both platform branches | **PARTIALLY MET** — Windows observed live; macOS aqua path is build/import-tested only (deferral 2) |
| Reset Preferences removes only mutable settings and refreshes state | **MET** — row 11 |
| Default base `Downloads/Audiobook-Creation-Tool-Outputs`, safely overridable | **MET** — rows 7–10, and since 2026-08-07 every already-built panel shows the change immediately |
| Every run uses an atomically reserved `<Tool>-Outputs/<Tool>-N` | **MET** — rows 12–18 |
| Individual-file outputs flat and collision-safe | **MET** |
| One folder root mirrors directly; multiple roots use named containers | **MET** for one root (row 19); multiple roots covered by automated tests only |
| No normal operation silently overwrites an input or output | **MET** — row 21, re-verified after the remediation |
| All six tools use the shared output service | **MET** — rows 12–17; MP3 Tool's route needed the 2026-08-07 concat fix before its row could honestly read PASS |
| Cover source-side modes follow Decision 10A, replacement off by default and strongly confirmed | **MET** — rows 22–25 |
| M4B Maker custom destination writes directly and stays source-safe | **MET** — row 26 |
| Clear Downloaded Data itemized, initially non-destructive, separate from Reset, catalog-restricted | **MET** — rows 27–32 |
| `.venv` and locked assets processed only after GUI exit by a non-venv coordinator | **MET** — row 33 |
| Requests cannot specify arbitrary paths; deletions allowlisted, contained, link-safe | **MET** |
| Results truthful, persisted, presented on next launch | **MET** — rows 34, 36 |
| Automated deletion tests use only temporary fake roots | **MET** |
| Normal setup, repair and no-console fast launch still work | **MET** — rows 35, 44, 45 |
| Both archive builders include `config.toml` and exclude `config-template.toml` | **MET** |
| New dialogs meet maximized/no-whole-dialog-scroll and minimum-size reachability | **MET** at 100%, re-verified after the remediation; the 125% pass is deferred to the later UI-compression phase (deferral 1) |
| Plan 1 isolation, panels, evidence, geometry and carried limitations intact | **MET** — ten hashes unchanged; row 43 |
| All focused tests pass | **MET** |
| Complete suite passes with no unexplained loss; every skip/warning named | **MET** — 1074/1069/5/1 after the remediation |
| `scripts/verify.py` reports `RESULT: PASS` | **MET** |
| Compile gate and `git diff --check` pass | **MET** |
| Windows manual matrix approved | **PENDING** — 46/46 PASS after the 2026-08-07 remediation, awaiting the maintainer |
| Live macOS approved, or an explicit approved deferral accurately recorded | **DEFERRED** — explicitly approved 2026-08-07, recorded as a deferral |
| Permanent documents carry the correct lasting record | **PENDING** — Phase 9 owns the transfer; Phase 8 updated `Handoff.md` only |
| Version remains `0.5.1`; no v0.6.0 release/tag claimed | **MET** |
| No Plan 3–9 scope or unrelated issue implemented | **MET** — the two corrections are squarely inside Plan 2's output/preference contract; nothing else was touched |
| The maintainer explicitly approved Plan 2 | **PENDING** |
| The temporary drop deleted only in the approved closeout | **PENDING** — the drop is intact |
| Closeout commit pushed and the agent stopped before merge/Plan 3 | **PENDING** — Phase 9 |

#### The Phase 9 boundary

Phase 9 owns the permanent-document transfer (`Briefing.md`, `Changelog.md`, `Decisions.md`,
the master index), deletion of
`md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md`, and the final
verification re-run. **None of it was started.** Phase 8 deliberately did not write a
Changelog entry or an ADR, because the drop assigns those to Phase 9. The drop file is intact.
No merge, version bump, tag, release, publication, force-push or branch deletion occurred.

### Phase 7 evidence addendum (2026-08-07) — supersedes the drill's narrow evidence limitation

The Phase 7 record below is historically accurate and is **not** rewritten: the original
2026-08-06 drill really did call `bootstrap._create_validated_venv()` directly, really did
skip the pinned pip install, and really did check only `import ssl, tkinter; tkinter.Tcl()`.
That narrow evidence was correctly rejected.

It was superseded on **2026-08-06/07** by a full launcher-driven verification in the same
disposable copy (`…\scratchpad\Ro'lål cleanup phase 7`), which the maintainer approved on
2026-08-07 together with the Phase 7 implementation at
`1eddc5163b4ad81f858d30b7df75fd2a28188da9`:

- the actual disposable-root **`.bat` launcher** — not an internal bootstrap function —
  detected the missing `.venv` and rebuilt it through the ordinary production setup path;
- the **full pinned dependency installation completed successfully** (114 packages);
- all applicable pins matched exactly (15 applicable, `audioop-lts` correctly skipped by its
  `python_version >= "3.13"` marker), all 8 `REQUIRED_IMPORTS` imported cleanly,
  `probe_capabilities()` returned true for tkinter/ssl/venv/Tcl-Tk, and `kokoro_is_healthy()`
  returned `True (ok)`;
- only the supported optional **model-weight** pre-download was declined; the Kokoro wheels,
  torch and the rest of the pinned set were installed;
- the real application opened under the disposable `.venv`, the cleanup report appeared
  exactly once, a second launch used the healthy fast path, no repair loop occurred, and no
  cleanup replay or second deletion happened;
- a path containing a space, an apostrophe and a non-ASCII letter passed through the complete
  flow; the expected first-run setup console appeared and no persistent console was present on
  the fast path;
- the real repository was proven separate before destructive work and remained untouched.

One attempt is explicitly **not** part of the accepted evidence: a first launcher run that
inherited the real repository's `VIRTUAL_ENV` and was stopped before it installed anything.
All accepted evidence comes from the subsequent clean run with `VIRTUAL_ENV` cleared and the
real `.venv\Scripts` removed from `PATH`. Phase 8 applied that lesson from the outset.

### Phase 7 — Safe post-exit cleanup and launcher/bootstrap coordination (2026-08-06, HOME-PC)

**Result: the Clear Downloaded Data flow now actually clears data — in a separate process,
after the application has exited, and only ever the four enumerated items.** Two files added,
six modified. `bootstrap.py` and both root launchers are untouched. `version.py` is still
`0.5.1`.

**Phase 7 start SHA:** `6dfd37e6d4658a1ec7a08070e777962c5e3fde73` (approved Phase 6). The
ending SHA is the commit carrying this section; it is quoted in the phase summary.

**Phase 8 was not started.** No packaging or archive change, no screenshot matrix, no live
macOS run, no live TTS synthesis check, no version bump, tag, merge or branch deletion.

#### The maintenance-state location

`files/runtime-data/maintenance/`, derived from a verified repository root and never
configurable. It satisfies every condition the drop requires: inside the repository, outside
`.venv`, outside `files/bin`, outside `files/runtime-data/models`, outside
`files/runtime-data/logs`, not any protected path, and unreachable from a request — a request
has no field that could name it. `state_dir()` re-validates all of that on **every** call,
including that no level of the path is a symlink, junction or reparse point. It is already
covered by the `files/runtime-data/` ignore rule, and release archives contain only `scripts/`
plus the root launcher and README, so it can never ship.

| File | Written by | Purpose |
|---|---|---|
| `cleanup-request.json` | the GUI | the one active request |
| `cleanup-accepted.json` | the coordinator | proof it loaded and validated *that* request |
| `cleanup-request.consumed.json` | the coordinator | the request, retired before the first deletion |
| `cleanup-request.unusable.json` | the GUI | a stale or corrupt predecessor, moved aside not deleted |
| `cleanup-result.json` | the coordinator | the one immutable result |
| `cleanup-result.presented.json` | the GUI | the result, retired after it was shown |
| `cleanup-result.unreadable.json` | the GUI | a corrupt result, moved aside and never executed |
| `cleanup-coordinator.log` | the coordinator | technical detail, deliberately not in `logs/` |

`STATE_FILENAMES` is the complete allowlist. `state_file()` refuses any other name, and the
only files this layer removes are those names plus its own `.act-maint-` temporary writes —
`_discard_own_file()` raises rather than removing anything else.

#### Atomic writes

`write_json()` writes to a `tempfile.mkstemp` file in the same folder, flushes, `fsync`s,
closes, then `os.replace`s. A crash leaves either the previous file or the new one, never a
half-written request that a coordinator could read as authorization. A failed replace discards
only its own temporary file. `sweep_temporary_files()` removes abandoned temporary writes older
than an hour, strictly name-matched.

#### The coordinator and its interpreter boundary

`scripts/Universal/shared/cleanup_worker.py`, started as `python cleanup_worker.py --run
--request-id <uuid>` — an argument vector, `shell=False`, detached, `CREATE_NO_WINDOW`, stdio
to `DEVNULL`. The only three things in that vector are a verified interpreter, this module's
own sibling file, and a UUID; nothing from a request participates, so a folder with spaces, an
apostrophe or non-ASCII characters is simply one argv element and quoting cannot be got wrong.

The interpreter is **verified, not assumed**: candidates are `sys._base_executable`, then
`sys.base_prefix`, then `PATH`; anything inside the repository is rejected before it is even
probed; and the survivor must itself report that `sys.prefix == sys.base_prefix`. The
coordinator imports only `argparse`, `os`, `stat`, `sys`, `datetime`, `pathlib` plus
`shared.maintenance` and `shared.cleanup_state`, which are themselves standard-library only —
so it keeps working while `.venv` is being deleted. It derives the repository root from its own
`__file__` and proves it by finding itself again at
`<root>/scripts/Universal/shared/cleanup_worker.py`; the current working directory is never
consulted.

#### The acknowledgement handshake and the close sequence

1. The dialog builds one immutable request and disables its own controls.
2. `cleanup_state.start_cleanup()` re-validates by round-tripping the request through the
   strict schema, then persists it atomically. An **active** request — valid, recent, and its
   requesting process still alive — is never displaced; the handoff refuses and says so.
3. The coordinator is started. It loads the request, checks it is the one named on its command
   line, checks it is not stale and does not name the coordinator itself, validates the root
   and the state folder, opens a handle to the requesting process, and only **then** writes the
   acknowledgement.
4. The GUI waits for that acknowledgement, bounded at 20 s, giving up early if the helper
   process dies first. Only a payload matching that exact request id, schema version and a
   plausible coordinator process id counts.
5. On acknowledgement the dialog shows *"Cleanup is ready. Audiobook Creation Tool will now
   close…"* and closes the whole application 700 ms later, through an injected callback that
   the launcher wires to its ordinary close path (so the last-used tool is still remembered).
6. On **any** failure — persistence, no verified interpreter, spawn error, timeout, or a
   handoff that raised — the request is withdrawn, the headline is *"Cleanup did not start. No
   data was changed…"* with a short specific detail appended, and both windows stay open and
   usable. The success sentence is never shown on the strength of having started a process.

A withdrawal that races a late acknowledgement is resolved by withdrawing **first** and then
looking once more: either the acknowledgement is seen and success is reported, or the
coordinator finds no request and refuses. `_handoff_pending` plus disabled buttons make a
second click a no-op, so repeated clicks cannot start a second helper.

#### Waiting for the requesting process

On Windows the handle is opened *before* acknowledgement and the wait blocks in
`WaitForSingleObject`, so it is bound to that exact process object and a recycled process id
cannot satisfy it. Elsewhere it sleeps between `os.kill(pid, 0)` probes. Either way it is
bounded (15 minutes) and never a busy loop. Beyond process-id reuse, a request older than six
hours, or dated more than five minutes in the future, is refused outright.

If the application never closes, the coordinator consumes the request, records **every**
selected item as `refused` with *"Audiobook Creation Tool was still running, so nothing was
removed,"* and exits. It never retries and never relaunches.

#### Deletion semantics — exactly four, re-authorized at the last moment

| ID | What is removed |
|---|---|
| `virtual_environment` | the `.venv` directory itself |
| `portable_binaries` | the contents of `files/bin`; the folder stays |
| `downloaded_models` | the contents of `files/runtime-data/models`; the folder stays |
| `application_logs` | the contents of `files/runtime-data/logs`; the folder stays |

The inventory the user saw is **not** authorization. Immediately before acting,
`process_asset()` re-derives the target from its enumerated ID and re-runs every Phase 6
check — exact compiled target, containment, repository root, protected paths, links at every
level — then re-inspects the type with `lstat`. A target swapped for a junction between review
and execution is `refused`, not followed. A target that is no longer a folder is `refused`. A
missing target is `missing`, a successful no-op.

The walk is post-order and iterative over `scandir`/`lstat` with `follow_symlinks=False`
throughout. A link found *inside* a target is detached (`unlink`, falling back to `rmdir` for a
Windows junction) and never descended into, so whatever it points at is neither counted nor
touched. A read-only file gets its attribute cleared once and is retried. Every failure is
collected and the pass continues — through the rest of the tree and on to the later selected
assets — so one locked file cannot hide the rest of the work.

The request is consumed (`os.replace` to `cleanup-request.consumed.json`) **before** the first
deletion, so a crash mid-pass can never replay. If the file is gone at that moment — the
requester withdrew it — the run stops and deletes nothing.

#### The result and the next launch

One `CleanupResult` per run, written atomically, containing per-asset `removed` / `missing` /
`failed` / `refused`, bytes freed, and a short message. It has no path field of any kind, and
messages quote names relative to the target, never absolute paths.

On the next ordinary launch the launcher queues `present_downloaded_data_report()` after the
configuration warnings. It deserializes through the strict schema; a corrupt or unsupported
record is moved to `cleanup-result.unreadable.json`, logged, and **never executed**. The report
lists every selected asset with its outcome, states the space freed (or *"at least …, plus data
whose size was not measured"* when a figure is unknown), and never claims complete success if
anything failed or was refused — a partial run gets the recovery line telling the user what is
still there and that they can try again from Preferences & Data. The record is retired to
`cleanup-result.presented.json` only **after** the window was built, so a display failure does
not lose the report. There is no retry button: a future cleanup starts as a fresh confirmed
request.

#### Launcher and bootstrap changes

**None to `bootstrap.py`, none to either root launcher.** They were read against the
requirement and already satisfy it: the `.bat` fast path is `if exist
".venv\Scripts\pythonw.exe"`, so a removed environment falls through to the ordinary first-run
setup that rebuilds it, and `bootstrap.venv_is_valid()` does the same for the `--launch-only`
route. Routing cleanup *through* `bootstrap.py` was considered and rejected: importing it opens
a log file inside `files/runtime-data/logs/`, which is one of the four selectable targets, and
on Windows that open handle would block the very deletion the run was asked to perform. The
coordinator therefore logs into the maintenance folder instead. Normal setup, repair, the daily
fast path, no-visible-console behaviour, interpreter selection, venv creation and dependency
installation are all unchanged.

`launcher.py` gained exactly two things: it passes its ordinary close path to Preferences as
`close_application`, and it queues the report. Neither adds work to a launch with no
maintenance state — `load_result()` returns immediately when the file is absent, and the state
folder is not even created.

#### Automated evidence

| Suite | Result |
|---|---|
| `test_cleanup_state.py` (new) | 72 passed |
| `test_cleanup_worker.py` (new) | 64 passed |
| `test_cleanup_handoff_ui.py` (new) | 30 passed |
| `test_maintenance.py` + `test_preferences_maintenance_ui.py` | 233 passed |
| `test_preferences_ui.py`, `test_config.py`, `test_settings.py`, `test_repository_contract.py` | 198 passed |
| `test_output_paths.py` + `test_tool_output_integration.py` | 214 passed, 1 skipped |
| `test_cover_source_side.py`, `test_maker_custom_destination.py`, `test_launcher_smoke.py` | 75 passed, 1 skipped |
| `test_ui_theme.py` | 17 passed, 0 skipped |
| complete suite | **969 passed, 5 skipped, 1 warning** |
| `pytest --collect-only` | **974 collected** |

974 = the Phase 6 baseline of 807 + 167 added (72 + 64 + 30 + 1 new report-window guard).
Collected equals executed. The five skips are the documented five (three Jack Ryan fixture
folder, two file-symlink `WinError 1314`); the one warning is the pre-existing pydub `audioop`
deprecation.

**One transient:** the very first full run after the new files were written reported 11 extra
environment-dependent skips (the junction and base-interpreter guards). It did not recur — every
run since returned exactly 969/5. No skip guard was weakened to get there.

Four Phase 6 guards moved to the Phase 8 boundary rather than being dropped: the Preferences
"deletes, spawns and persists nothing" guard (still true — persistence and spawning live in
`cleanup_state`), the cleanup-flow guard in `test_output_paths.py`, the handoff guard in
`test_tool_output_integration.py` (now behavioural: a helper that cannot start must leave the
tree byte-identical), and the initial-focus guard, which is now scoped to the two windows that
can lead to a deletion so the read-only report window may focus its own dismiss button.

#### The disposable end-to-end drill (Windows 11, HOME-PC, 2026-08-06)

Real root: `…\MyProjects\Home-PC\Audiobook-Creation-Tool`. Disposable root:
`…\scratchpad\Réal's Drill Copy\Audiobook Tool` — deliberately containing a space, an
apostrophe and a non-ASCII character. Proven before anything destructive ran: the two paths
differ, neither is inside the other, the disposable root is not a drive root, not the home
folder and not an ancestor of the real repository. 138 code files were copied; runtime data,
`.git` and `.venv` were not.

The drill ran the **real production interfaces**, and the requesting process ran from the
disposable copy's own `.venv` — the environment it was about to have removed:

- the dialog opened with `()` selected and `Review Selected Data…` disabled;
- all four rows read Present with sizes `11.5 MB / 6.0 KB / 72.0 KB / 768 bytes`;
- the confirmation carried the exact approved title, the four consequences, the freed-space
  line, the close notice, the four effect lines, the exclusion notice and the final question;
- accepting wrote one request, the coordinator (a separate process id, base interpreter)
  acknowledged it, and the status read the exact scheduled sentence;
- nothing was deleted at that point — `.venv/Scripts/python.exe`, `files/bin/ffmpeg.exe` and a
  log file were all still present when the GUI closed itself;
- after the requesting process exited, the four items were removed with byte totals matching
  the fixtures **exactly** (12,088,166 / 6,144 / 73,728 / 768), `.venv` gone entirely and the
  three container folders present and empty;
- `settings.json`, `config.toml`, `config-template.toml`, a decoy `my-audiobook-output.m4b`,
  `scripts/`, `md-instructions/` and both root launchers were byte-identical afterwards;
- re-running the coordinator with the same request id exited 1 and removed nothing, including a
  file created after the first run;
- the launcher fast-path marker was gone, the ordinary `bootstrap._create_validated_venv()`
  rebuilt the environment, `venv_is_valid()` went back to true, and the rebuilt interpreter ran
  `import ssl, tkinter; tkinter.Tcl()` cleanly;
- the next launch presented the report exactly once, at 349×221, and a second call returned
  nothing.

**The pinned pip install was deliberately not re-run** in the drill: it downloads roughly 2 GB
of torch, and it is unchanged code covered by the existing setup tests. What was exercised is
the decision and the venv creation the normal path performs.

**The real repository was untouched.** Fingerprints taken before and after match for
`files/runtime-data/models`, `files/runtime-data/logs`, `settings.json`, `config.toml` and
`config-template.toml`; `files/bin` is still absent as before; the real `.venv` still exists
with its interpreter and an unchanged directory mtime — and it was deliberately **not walked**,
because inventorying it is outside the authorization. No maintenance-state folder exists in the
real repository. The disposable copy was **retained** for review.

#### Pending evidence — described as pending, never as passed

- **Windows 125% scaling** — not re-run for the new report window; Phase 8 owns the scaling
  matrix, and display scaling was deliberately not changed for this phase.
- **Phase 8 screenshots** — not collected.
- **Live macOS** — not run. The aqua path is import- and build-tested only.
- **Live TTS synthesis** — deliberately not run; it is independent of Phase 7.

#### The Phase 8 boundary

Phase 8 owns packaging (`config.toml` in both archives, never `config-template.toml`), the
clean-extraction smoke tests, the full Windows manual matrix, the live macOS matrix or an
explicitly approved deferral, the screenshot evidence, and the Definition-of-Done table. None
of it was started, and it requires new explicit maintainer approval.

### Phase 6 — Downloaded-data inventory and confirmation UI (2026-08-04, HOME-PC)

**Result: the itemized cleanup model and its whole user flow exist, and nothing can delete
anything.** Phase 6 inventories, selects, confirms and builds one immutable request — then
fails closed, because the coordinator that would act on that request is Phase 7. Three files
added, five modified. `version.py` is still `0.5.1`.

**Phase 6 start SHA:** `89cca58914a9d94eb6d480c802e6021d2a09e872` (approved Phase 5).

#### Scope implemented

The exact four-item catalog; canonical ID→target mapping with full authorization; present/
missing inventory; safe size estimation; a selection model with no destructive default;
immutable versioned request and result schemas with strict validation; the Clear Downloaded
Data dialog; the strong confirmation; and the fail-closed production callback.

**Phase 7 was not started.** No deletion executor, no coordinator, no request persistence, no
maintenance-state directory, no process spawning, no post-exit wait, no launcher or
`bootstrap.py` change, no `.venv` rebuild, no next-launch result presentation.

#### The catalog — exactly four IDs, and no way to add a fifth at runtime

| Asset ID | Display name | Target (relative to the supplied root) | Post-exit | Removes |
|---|---|---|---|---|
| `virtual_environment` | Private Python environment | `.venv` | yes | the directory itself |
| `portable_binaries` | Portable binaries | `files/bin` | no | contents |
| `downloaded_models` | Downloaded voice models | `files/runtime-data/models` | no | contents |
| `application_logs` | Application logs | `files/runtime-data/logs` | yes | contents |

`CATALOG` is a tuple of frozen dataclasses and `CATALOG_BY_ID` a `MappingProxyType`, so neither
can be extended or edited. `ASSET_IDS` is the one deterministic order used by rows, requests,
totals and confirmation lines.

#### Target authorization — how an ID becomes a path

`authorized_target(asset_id, repo_root)` is the only mapping, and the root is **always
explicit** (no default, so the suite cannot accidentally be handed the real project). Before a
path is returned it must be the exact compiled target, inside the root, not the root itself,
not equal to / inside / containing any `PROTECTED_RELATIVE` entry (`.git`, `scripts`,
`md-instructions`, `files/tests`, both screenshot folders, `settings.json`, `config.toml`,
`config-template.toml`, `README.md`, `AI-WORKSPACE.md`, both root launchers), and reached
without crossing a symlink, junction or reparse point at any level including the root. Paths
are normalised with `abspath`, never `resolve()`, precisely so a junction is *detected* rather
than silently followed. `assert_authorized()` re-derives and compares, so a path that did not
come from the mapping cannot pass.

`config-template.toml` appears in this codebase exactly once, in that protected list. That is
the opposite of using it, and `test_repository_contract.py` now pins it to that single place.

#### Inventory and size estimation

`estimate_size()` walks with `os.scandir`/`lstat` only — read-only by construction, no open,
no timestamp touch. It never follows a directory link (the link is recorded as a problem and
the estimate becomes incomplete), tolerates files vanishing mid-walk as normal, and turns an
unreadable subtree into a recorded problem rather than a traceback. An incomplete estimate is
shown as `1.2 MB (at least)` and never as an exact figure.

`inventory(root, measure=False)` does no walking at all, which is what lets the dialog paint
instantly; the measured pass runs on a worker thread and every Tk update returns to the main
thread through `after`. A missing target is a normal state. A wrong-type or unsafe target is
*present but unavailable*, carrying the sentence the row shows.

#### Selection — safe by construction

Every checkbox is created unchecked on every open. Missing and unsafe rows have no usable
control. `selected_ids()` intersects "ticked" with "eligible", so even a forced variable
yields nothing. `Review Selected Data…` is disabled until something eligible is deliberately
ticked. Nothing is persisted or restored — closing and reopening starts over. Reset
Preferences remains a separate button with a separate command and is never bundled.
`summarise_selection()` refuses an ID that is unknown, duplicated, missing or unsafe, and
reports `complete=False` rather than inventing a total when a size is unknown.

#### Request and result schemas

Schema version `1`. A request carries **only** `schema_version`, `asset_ids` (an immutable
tuple in catalog order), `process_id`, a tz-aware UTC `created_at`, and a UUID `request_id`.
There is no `path`, `target`, `directory`, `root`, `command` or executable field anywhere in
either schema — a test asserts that of every field name, and another asserts a serialized
request contains no `/` or `\` at all. Validation lives in `__post_init__`, so no construction
path (direct or deserialized) yields an invalid object; `bool` is excluded explicitly from the
integer checks. Deserialization uses a strict allowlist: a missing *or* extra field is a
refusal. Clock, PID and request-ID are injectable for deterministic tests.

The result schema (`removed` / `missing` / `failed` / `refused`, non-negative bytes, immutable
outcomes in catalog order) is defined so Phase 7 inherits a fixed boundary. **Phase 6 creates
no result during normal use.**

#### The dialog and the confirmation

Title `Clear Downloaded Data`, with the approved introduction. Each row shows display name,
`Present`/`Missing`, size (or `Calculating…`, or a truthful minimum), and its consequence or
its safety explanation. Footer: a running total, `Cancel`, and `Review Selected Data…`.

The confirmation is one custom window titled `Confirm clearing downloaded data`, built fresh
from the live selection every time. Cancel is the focused default and is what Escape and the
window-close control both do; the destructive button is `Clear 1 Selected Item and Close` /
`Clear {N} Selected Items and Close` and is never the default. There is no suppression path.

**Declining creates nothing, calls nothing and changes nothing.** Accepting builds exactly one
validated immutable request and passes it to the injected callback — nothing else. In
production that callback is `maintenance.unavailable_cleanup_handler`, which returns `False`,
and the dialog then shows verbatim:

> Cleanup did not start. Safe post-exit cleanup is not available yet. No data was changed, and
> Audiobook Creation Tool will remain open.

Both dialogs stay open and usable. A callback that *raises* is treated identically — the
handoff is wrapped, so a future coordinator's crash can never leave the app claiming success.

#### Automated verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `-m pytest -q files/tests/test_maintenance.py` | **171 passed** |
| `-m pytest -q files/tests/test_preferences_maintenance_ui.py` | **61 passed** |
| `-m pytest -q files/tests/test_preferences_ui.py` | 65 passed |
| `-m pytest -q files/tests/test_config.py` | 68 passed |
| `-m pytest -q files/tests/test_settings.py` | 25 passed |
| `-m pytest -q files/tests/test_repository_contract.py` | 40 passed |
| `-m pytest -q -rs files/tests/test_output_paths.py` | 143 passed, 1 skipped |
| `-m pytest -q files/tests/test_tool_output_integration.py` | 71 passed |
| `-m pytest -q -rs files/tests/test_cover_source_side.py` | 33 passed, 1 skipped |
| `-m pytest -q files/tests/test_maker_custom_destination.py` | 31 passed |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** |
| `-m pytest --collect-only -q files/tests` | **807 collected** |
| `-m pytest -q -rs files/tests` (×3) | **802 passed, 5 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** (5/5 checks) |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | clean, exit 0 |

**Against the Phase 5 baseline (574 collected / 569 passed / 5 skipped / 1 warning):** 807
collected, **+233** — `test_maintenance.py` +171, `test_preferences_maintenance_ui.py` +61,
`test_tool_output_integration.py` +1 (two boundary guards became three). `test_preferences_ui.py`
stays at 65: four Phase 2 placeholder tests were replaced by four Phase 6 entry-point tests, the
guard among them narrowed to the Phase 7 boundary rather than dropped. Collected == executed;
the five skips are the same documented five (three Jack Ryan fixture-folder skips, two
file-symlink skips needing a Windows privilege this account lacks). The one warning is the
pre-existing pydub `audioop` DeprecationWarning. **No Tk/display skip burst occurred in any
Phase 6 run.**

One new-test-only issue was found and fixed rather than tolerated: a dialog's background
inventory thread could finalise a discarded Tk variable, raising `Variable.__del__: main thread
is not in main loop`. The test helper now leaves `measure` off by default, the three
background tests join their worker, and the fixture collects on the main thread. Six
consecutive clean runs followed.

#### Temporary-root fixture verification — PASSED (2026-08-04, HOME-PC)

Disposable fake root `…\Temp\act-phase6-*\fake-repo`, driving the production catalog,
inventory, selection, confirmation and fail-closed callback with **only the root injected**.
Windows theme, 1920×1080, Tk scaling 1.3333, 96 px/in.

| Fake file | Bytes | | Asset | Expected | Observed |
|---|---|---|---|---|---|
| `.venv/pyvenv.cfg` | 120 | | `virtual_environment` | 3 520 = 3.4 KB | Present, **3.4 KB** |
| `.venv/Lib/site-packages/pkg/__init__.py` | 3 400 | | `portable_binaries` | 51 200 = 50.0 KB | Present, **50.0 KB** |
| `files/bin/ffmpeg.exe` | 51 200 | | `downloaded_models` | 262 144 = 256.0 KB | Present, **256.0 KB** |
| `files/runtime-data/models/kokoro/model.onnx` | 262 144 | | `application_logs` | 2 000 = 2.0 KB | Present, **2.0 KB** |
| `files/runtime-data/logs/session-1.log` | 900 | | | | |
| `files/runtime-data/logs/session-2.log` | 1 100 | | | | |

Decoy neighbours `config.toml`, `settings.json`, `scripts/Universal/launcher.py` and
`md-instructions/Briefing.md` were present throughout and never appeared in the inventory.

- Preferences cleanup button **enabled**; opening twice returned the **same** window.
- Initial state: `selected_ids() == ()`, every box unchecked, Review **disabled**, status
  `Nothing selected.`
- Degraded second root: missing `.venv` → **Missing/DISABLED**; a junctioned `models` pointing
  at a 999 999-byte folder → **Present/DISABLED**, *"this item is a shortcut or link, which is
  never followed or removed"*. Force-ticking both still yielded `()`, and the linked folder was
  **never walked**.
- Totals: `1 item selected — about 2.0 KB` → `2 items selected — about 52.0 KB` →
  `4 items selected — about 311.4 KB`.
- Confirmation: exact title, exact body (all four items with state, size and consequence;
  `Estimated space to be freed: 311.4 KB.`; the close notice; the four applicable effect lines;
  the exclusion notice; the final question), Cancel default, `WM_DELETE_WINDOW → cancel`,
  Escape bound, **766×559** — inside 920×600. Singular label verified as
  `Clear 1 Selected Item and Close`.
- Declining: `result=False`, window destroyed, **no request built**, fake root byte-identical.
- Accepting: exactly one `CleanupRequest`, fields
  `['asset_ids','created_at','process_id','request_id','schema_version']`, IDs in catalog
  order, tz-aware UTC, payload containing no path of any kind. `submit()` returned **False**,
  the status matched the approved fail-closed wording **exactly**, and the cleanup dialog,
  Preferences and the Tk root all remained alive.
- Geometry: cleanup dialog **718×414** requested (minsize 631×413), whole dialog inside
  920×600; only the item-list row carries grid weight and the actions sit below it, so growth
  can never displace them. Preferences unchanged at 618×596.
- **Nothing written:** fake-root hashes and listing identical (10/10 files), and no
  request/result/maintenance-state/`.act-` file created anywhere under the temporary tree.
- **Real project untouched:** all 6 size walks were under the temporary root, none under the
  repository; the real `.venv`, `files/bin` (absent on this machine), `files/runtime-data/models`
  and `…/logs` fingerprints (mtime + entry count + names) were identical before and after.

#### Pending evidence — accurately pending, not passed

| Item | State |
|---|---|
| Windows 125% scaling | **Pending** — deferred to Phase 8; system scaling was not changed |
| Live macOS | **Pending** — approved deferral; the aqua path is import/build-tested only |
| Screenshot evidence for the new surfaces | **Pending** — assigned to Phase 8 |
| Live TTS synthesis | **Pending** — independent of Phase 6 and deliberately not run |

#### Repository state

`git status --short` shows only `?? config-template.toml`; `git diff --name-status` is empty.
`config-template.toml` is untracked, unstaged and still hashes
`94b05edc3211efe531be018fbc442c240df8db42`. The four canonical documents keep their exact
names with no alias, `md-instructions/don't-delete/` keeps its four references, and the ten
approved Plan 1 screenshots are unmodified. `master` and `origin/master` remain `bada8a3`;
the Plan 1 feature head remains `f3d70e8`.

#### Next action

**Phase 7 — Safe post-exit cleanup and launcher/bootstrap coordination.** It requires new
explicit maintainer approval, and it is the first phase in this drop that is able to delete
anything.

---

### Phase 5 — Cover Image and M4B Maker exceptions (2026-08-04, HOME-PC)

**Result: both Decision 10A exceptions exist, opt-in and off by default, with the standard
modes unchanged.** Two files added, six modified. `version.py` is still `0.5.1`.

**Phase 5 start SHA:** `abdd1cfa10f4ceb9f666bf4455169bdaddac300e` (approved Phase 4).

#### Cover Image

| Aspect | Behaviour |
|---|---|
| Toggle | `Save beside source images`, **off on every fresh build**, nothing persisted |
| Choices | `Create numbered copies` (preselected) / `Replace original files` (never default) |
| Turning off | Resets the action, so a Replace selection cannot survive as a hidden mode |
| Numbered | `stem-1.ext` beside each source, per-directory collision sequences |
| Replace gates | toggle **and** radio **and** per-run confirmation — each inert alone |
| Confirmation | Title *"Confirm replacement of original images"*, exact count, focused Cancel, Escape/close cancel, `Replace N Original Files`, rebuilt every run |
| Pre-validation | Links, missing files, directories and non-round-trippable formats refused **before** the dialog |
| Install | complete `.act-tmp-…` sibling → validate size → `os.replace`. **Never delete-then-rename** |
| Failure | original byte-for-byte unchanged; only this operation's temporary file removed |
| Partial batch | truthful: "N of M original(s) replaced; any not reached are unchanged" |

#### M4B Maker

Toggle `Choose custom destination`, off on every fresh build; path and Browse revealed only
while on; `custom_destination()` is the single read point, so a stale hidden path cannot steer
a standard build. Validation (absolute, existing, directory, not a link, writable via a probe
that is removed again) runs before anything starts, and a failure reserves **no** run. Output
goes straight in with **no nested `M4B-Maker-N`**, using the shared sanitiser and collision
numbering. Staging moved to an operation-owned `tempfile.mkdtemp()`.

#### The bug this phase found before it shipped

Phase 4's cancellation ran `shutil.rmtree(out_dir)` unconditionally. Correct for a reserved run
— but in custom mode `out_dir` **is the user's own folder**, so cancelling a build would have
deleted it and everything in it. Cancellation now branches on the mode and removes only this
operation's staging and its own partial output. A source-level guard test asserts the
destructive `rmtree` sits behind the custom-mode check.

#### Automated verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `-m pytest -q -rs files/tests/test_cover_source_side.py` | **33 passed, 1 skipped** |
| `-m pytest -q -rs files/tests/test_maker_custom_destination.py` | **31 passed** |
| `-m pytest -q files/tests/test_tool_output_integration.py` | **70 passed** |
| `-m pytest -q -rs files/tests/test_output_paths.py` | 143 passed, 1 skipped |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** |
| `-m pytest -q -rs files/tests/` | **569 passed, 5 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | clean |

**Against the Phase 4 baseline (503 collected / 499 passed / 4 skipped):** 574 collected now,
+71. That is +34 Cover source-side, +31 Maker custom destination, +7 net in
`test_tool_output_integration.py` (five Phase 4 placeholder tests replaced by five Phase 5
state tests, two Phase 4 guards replaced by two Phase 5 guards, plus five new), and −1 in
`test_output_paths.py` (two exception guards merged into one). The fifth skip is new: the
Cover link-refusal test needs a **file** symlink, which this account cannot create.

#### Live Windows fixture verification — PASSED (2026-08-04, HOME-PC, real ffmpeg + Pillow)

Temporary output base, generated images and tones, settings redirected to a temp file.

| Check | Observed |
|---|---|
| Cover standard | `Cover-Image-Outputs/Cover-Image-1` → `cover.jpg`; source folder unchanged |
| Cover numbered ×2 | `art-1.jpg` then `art-2.jpg` beside the source; original unchanged |
| Cover replacement | confirmation asked for 1 file (`Replace 1 Original File`); image went 400×200 → 64×64; neighbour `keep-me.png` untouched |
| Cover failed replacement | injected failure before the boundary → original **and** sibling byte-identical, **no** `.act-tmp-` file left |
| Maker standard | `M4B-Maker-Outputs/M4B-Maker-1` → `Standard Book.m4b` |
| Maker custom ×2 | `My_Book__Title.m4b` then `My_Book__Title-1.m4b` **directly** in the chosen folder; `pre-existing.txt` kept; **no nested run** |
| Exception modes | final base tree contains **only** `Cover-Image-1` and `M4B-Maker-1` — no unused standard runs |
| All sources | mp3, cover and image fixtures byte-identical except the one deliberately replaced disposable copy |

#### Still pending — not claimed as passed

1. **Windows 125% display scaling** — deferred to the later manual-validation phase.
2. **Live macOS** — explicit deferral.
3. **Phase 2 screenshot evidence** — assigned to Phase 8.
4. **TTS live synthesis** — still pending, unchanged and untouched by this phase.

### Next action

**Phase 6 — downloaded-data inventory and confirmation UI.** Not started. It requires explicit
maintainer approval before any work begins.

---

## Phase 4 record (v0.6.0 Drop 2, approved 2026-08-04)

**v0.6.0 Drop 2 (Plan 2) — PHASE 4 COMPLETE.**

### Phase 4 — standard output integration across all six tools (2026-08-03, HOME-PC)

**Result: every tool now writes to `<output base>/<Tool>-Outputs/<Tool>-N/`, reserved at
validated operation start.** One file added, ten modified. `version.py` is still `0.5.1`.

**Phase 4 start SHA:** `10819f1b7cc0d7ddb1b8c51ae870a44c694a3fdc` (approved Phase 3).

#### The §G blocker and its ruling

Phase 4 stopped before any edit because the drop specifies Cover Image's Phase 4 default and
its Phase 5 source-side mode but never rules on the **already-shipped destructive
`Overwrite original files` checkbox** in between. The maintainer approved **Option A**: keep it
visible but disabled, captioned *"available in a later update"*. Implemented past the widget
state on purpose — `var_overwrite` forced `False` **and** the captured worker parameter is the
literal `False`, so re-enabling the checkbox alone cannot reach the source-side branch.

#### Per-tool disposition

| Tool | Destination | Notes |
|---|---|---|
| TTS Audiobook | `TTS-Audiobook-Outputs/TTS-Audiobook-N` | Reserved in `run_job` after input validation. Mirroring, voices, timing, retry untouched. |
| M4B Converter | `M4B-Converter-Outputs/M4B-Converter-N` | Batch planner; duplicate stems now number instead of overwriting. Decoder/xHE-AAC untouched. |
| MP3 Tool | `MP3-Tool-Outputs/MP3-Tool-N` | **Three** reservations — combine, time edit, ID3 — each its own run. Combine staging moved from `edited_mp3s-N` into the run. Time-only-through-Write-ID3 preserved. |
| M4B Maker | `M4B-Maker-Outputs/M4B-Maker-N` | Local sanitise regex replaced by the central sanitiser; `build/` staging inside the run. |
| Cover Image | `Cover-Image-Outputs/Cover-Image-N` | No longer writes beside sources. Overwrite control disabled per Option A. |
| M4B Metadata | `M4B-Metadata-Outputs/M4B-Metadata-N` | Plan-before-copy; copy-only contract intact; `avoid_input_overwrite` gone. |

#### Legacy helpers

- `paths.next_output_dir()` and `paths.avoid_input_overwrite()` — retained as **documented
  dormant compatibility API**; a test asserts nothing under `scripts/Universal` calls either.
- `mp3_tool.next_available_folder()` and `BASE_OUTPUT_DIRNAME` — **removed outright**.
- `cover_resizer.next_version_path()` and its `overwrite` branch — **dormant legacy reserved
  for Phase 5**, unreachable from the Phase 4 UI and operation-start path.
- Per-tool output Browse controls and `choose_outdir` — **removed** (they would bypass the
  configured base). `_browse_dir` retired from TTS.

#### Two real bugs

1. **Found and fixed by the migration:** `avoid_input_overwrite()` only guarded against writing
   *onto an input*, so two imports with the same name from different folders silently
   overwrote each other in the Converter, MP3 Tool and Metadata Editor. The batch planner
   closes it — verified live (`Track A.mp3` + `Track A-1.mp3`).
2. **Introduced and caught by the live check:** routing the Converter through the planner
   removed its local `stem` assignment while the metadata fallback title still used it — every
   conversion failed with `name 'stem' is not defined` and produced nothing. **Every
   planner-level test passed.** Only driving the real worker on a generated fixture exposed it.
   The suite now runs the actual Converter, time-edit and Cover workers.

#### Automated verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `-m pytest -q -rs files/tests/test_tool_output_integration.py` | **68 passed** |
| `-m pytest -q -rs files/tests/test_output_paths.py` | 143 passed, 1 skipped |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** — all executed |
| `-m pytest --collect-only -q files/tests/` | **503 collected** (was 439) |
| `-m pytest -q -rs files/tests/` | **499 passed, 4 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** across five checks |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | clean |

#### Live Windows fixture verification — PASSED (2026-08-03, HOME-PC, real ffmpeg + PIL)

Temporary output base, generated tone/image fixtures, settings redirected to a temp file. The
maintainer's real preferences, Downloads folder, outputs and media were never touched.

| Check | Observed |
|---|---|
| MP3 Tool time edit | `MP3-Tool-Outputs/MP3-Tool-1` → `Track A.mp3`, `Track A-1.mp3`, `Track B.mp3` |
| MP3 Tool Write ID3 | `MP3-Tool-2` (distinct), `TIT2 = Phase 4 Title` |
| MP3 Tool combine FAST | `MP3-Tool-1` → `Combined Book.mp3` + timestamps + `build/` inside the run |
| MP3 Tool combine SAFE (gap 0.2) | `MP3-Tool-2`, distinct run |
| M4B Converter | `M4B-Converter-Outputs/M4B-Converter-1` → `Book.mp3` |
| M4B Converter duplicate stems | `Book.mp3` + `Book-1.mp3` |
| M4B Maker | `M4B-Maker-1` → `My_Book__Title.m4b` (central sanitiser); second build → `M4B-Maker-2` |
| Cover Image | `Cover-Image-1` → `cover.jpg`, `cover-1.jpg`; **nothing beside the sources** |
| Cover placeholder | widget state `disabled`, variable `False` |
| M4B Metadata | `M4B-Metadata-1` → `Book.m4b`; original byte-identical |
| Forced collision | existing `Track A.mp3` → `Track A-1.mp3` → `Track A-2.mp3` |
| Validation failure | run count unchanged — no directory created |
| All fixtures | mp3, m4b and image sources **byte-identical** after every run |

#### Still pending — not claimed as passed

1. **Windows 125% display scaling** — deferred to the later manual-validation phase by
   maintainer decision; scaling was not changed during Phase 4.
2. **Live macOS** — explicit deferral.
3. **Phase 2 screenshot evidence** — assigned to Phase 8.
4. **TTS live synthesis** — not run: Edge TTS needs the network and Kokoro needs the ~300 MB
   model. TTS's destination, mirroring and validation-before-reservation are covered by
   automated tests and an AST guard; **the synthesis path itself was not live-exercised.**

### Next action

**Phase 5 — Cover Image and M4B Maker exceptions.** Not started. It requires explicit
maintainer approval before any work begins.

---

## Phase 3 record (v0.6.0 Drop 2, approved 2026-08-03)

**v0.6.0 Drop 2 (Plan 2) — PHASE 3 COMPLETE.**

### Phase 3 — output reservation, collision, and mirroring services (2026-08-03, HOME-PC)

**Result: the platform-neutral output foundation exists and is exhaustively tested, and
absolutely nothing consumes it yet.** Two files added, one comment-only modification. Current
user-facing output behaviour is unchanged; `version.py` is still `0.5.1`.

**Phase 3 start SHA:** `e16fd42dcb54a6f34a4d79a498fa681f18ef6e6b` (approved Phase 2).

#### What was built — `scripts/Universal/shared/output_paths.py`

| Area | Contract |
|---|---|
| Layout | `<base>/<Tool>-Outputs/<Tool>-N/` |
| Tool parents | `TOOL_OUTPUT_PARENTS`, derived from the existing `paths.TOOL_SLUGS` so a slug is never written twice. Unknown key → `UnknownToolError`, never a path fragment. |
| Base | `resolve_output_base(snapshot)` reads the captured Phase 1 snapshot; `ensure_output_base()` is the only creation step and proves writability before a run starts. |
| Reservation | `mkdir()` **without** `exist_ok` is the race boundary — no existence check first. Bounded, diagnosable, returns a frozen `RunReservation` carrying the run's config snapshot. |
| Release | `release_if_empty()` removes a reserved directory **only** while empty. |
| Sanitisation | Path→last component, control chars, forbidden set, NFC, trailing dots/spaces, reserved device names (with or without extension), 255-char limit preserving the extension. |
| Collisions | requested name → `stem-1.ext` → `stem-2.ext`. Per-run `DestinationPlanner`, never global; disk state + planned names combined; case-insensitive everywhere. |
| Safety | `assert_contained` (handles non-existent children), `assert_no_link_in`, `assert_not_input`, `assert_outside_source_trees`. Typed `OutputPathError` with message/detail split. **Deletes nothing.** |
| Planning | `plan_flat`, `plan_mirrored`, `plan_multi_root` — all pure, all returning frozen plans. |

**Planning is pure; materialisation is explicit.** Only `ensure_output_base()` and
`reserve_run_directory()` create anything, and only directories. Tk-free, subprocess-free,
network-free, working-directory-independent — all asserted.

#### Three findings worth recording

1. **The junction escape is caught by containment, not by the link check.** `resolve()` follows
   a junction, so a link pointing *outside* the run directory normalises outside the root and
   containment rejects it. A link pointing *back inside* the root resolves to a contained path
   and passes containment entirely — that is the case `assert_no_link_in` exists for, and it now
   has its own test. Both defences are needed; neither is redundant.
2. **Windows reports `<tmp>/NUL` as existing.** The OS resolves the device name, so a test that
   asserted the un-created root did not exist failed. That is Windows device semantics, not a
   defect — and it is exactly the hazard the sanitiser defuses (`NUL` → `_NUL`).
3. **Directory-link tests run via junctions.** `mklink /J` needs neither Developer Mode nor
   elevation, so the link-safety tests get real coverage on an ordinary account rather than
   being skipped wholesale. Only the file-symlink test still needs the privilege.

#### Automated verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `-m pytest -q -rs files/tests/test_output_paths.py` | **143 passed, 1 skipped** |
| `-m pytest -q files/tests/{test_config,test_settings,test_repository_contract,test_preferences_ui,test_launcher_smoke,test_prototype_regression,test_batch_convert_folders}.py` | **226 passed** |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** — all executed |
| `-m pytest --collect-only -q files/tests/` | **439 collected** (was 295) |
| `-m pytest -q -rs files/tests/` | **435 passed, 4 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** across five checks |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | **clean, exit 0 — zero notices** |

+144 collected = exactly the new file. The 1 warning is the pre-existing pydub `audioop`
`DeprecationWarning`.

#### Skips — named, with exact reasons

| Skip | Reason |
|---|---|
| `test_a_linked_destination_name_is_refused` | This account cannot create a **file** symlink: `OSError WinError 1314 — A required privilege is not held by the client`. Windows needs Developer Mode or elevation for file symlinks; a junction cannot stand in for a file. The pure containment logic it guards is covered by the non-link containment tests, and the two directory-link tests **did** run via junctions. **Not claimed as passed.** |
| 3 × `test_jack_ryan_final_product.py` | Pre-existing, gated on `JACK_RYAN_M4B_FOLDER`. |

#### Scope held

No tool panel imports or calls the new service (asserted per module). The launcher does not
either. `paths.next_output_dir()` is unchanged in behaviour and now documented as a
compatibility wrapper scheduled for removal in Phase 4, with a test recording the exact five
call sites so a sixth fails and Phase 4's removals show in the diff. No cleanup, no post-exit
behaviour, no Cover source-side mode, no M4B Maker custom destination, no Plan 3 importing.
Preferences and the launch warning still pass unchanged.

#### Still pending — not claimed as passed

1. **Windows 125% display scaling** — deferred to the later manual-validation phase by
   maintainer decision; system scaling was not changed during Phase 3.
2. **Live macOS** — explicit deferral.
3. **Phase 2 screenshot evidence** — assigned to Phase 8.

### Next action

**Phase 4 — standard output integration across all six tools.** Not started. It requires
explicit maintainer approval before any work begins.

---

## Phase 2 record (v0.6.0 Drop 2, approved 2026-08-03)

**v0.6.0 Drop 2 (Plan 2) — PHASE 2 COMPLETE.**

### Phase 2 — Preferences, warning presentation, Reset Preferences (2026-08-03, HOME-PC)

**Result: the Preferences & Data surface exists on both platforms, warnings are reported once
per launch, and Reset Preferences works — with no tool-output change and no cleanup behaviour
of any kind.** Two files added, four modified. `version.py` is still `0.5.1`.

**Phase 2 start SHA:** `56076fe4baf32626fa82ad7ecad78dad8c0235e2` (approved Phase 1).

#### Identifier integrity check — no defect found

The pasted Phase 1 summary showed a garbled `output_barectory`. That string **does not exist
anywhere in the repository** (`git grep barectory` → no match). The committed code, tests and
schema consistently use the persisted settings key `output_base_directory` and the TOML key
`output.base_directory` — 11 occurrences across `config.py`, `test_config.py` and
`test_settings.py`, all canonical. The garbling was a display artefact in the pasted text.
**No correction was needed and none was made.**

#### What was built

| Area | Outcome |
|---|---|
| Entry point | `Preferences & Data…` in the launcher status bar on **all three shells** — `ACT.Ghost.TButton` on Windows, native unstyled `ttk.Button` on aqua and classic — plus `Ctrl+,` and `Cmd+,` bound unconditionally. `takefocus=True`, so it is in the Tab order everywhere. |
| Dialog | New `shared/preferences_ui.py`. Non-modal, Escape-closable, single-instance: the launcher holds the one live reference and repeated activation **focuses** it. |
| Output base | Shows the effective value **and its source**; default-or-custom radio, editable path, Browse. Validated through the Phase 1 rules; saving creates no folder; success reloads the snapshot immediately. |
| Reset | Confirms, clears mutable preferences only, refreshes fields and source, reports failure honestly. Cancel changes nothing. |
| Cleanup | Disabled `Clear Downloaded Data` placeholder with **no command at all**. |
| Warning | `config.take_launch_warning()` guard + one non-modal aggregated window per launch. |

#### Two defects found and fixed while building

1. **A failed settings write left the cache ahead of the file.** `settings.set()`/`update()`
   mutated the in-memory dict and then returned `False` if the atomic write failed, so the
   running app believed a preference that never reached disk. Both now roll the change back on
   failure — which is what makes the dialog's *"the previous setting is still in use"* true.
2. **The dialog did not fit the supported minimum.** The first build measured **689 px tall
   under the Windows theme**, against the app's own `920×600` minimum; the unstyled build was
   556 px, so a fit test that only exercised the unstyled bundle passed and hid it. Fixed by
   layout, not by relaxing the test: Entry/Browse/Save share one row, Reset sits on its card's
   heading row, outer padding moved to the tight end of the spacing scale. Now **618×596 px on
   Windows, 630×488 px unstyled**, no whole-dialog scrolling. The fit test now asserts the
   Windows path explicitly, and a companion test proves Save/Reset/Close/Browse all sit inside
   the dialog's own height and are keyboard-reachable.

#### Automated verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `-m pytest -q -rs files/tests/test_preferences_ui.py` | **65 passed** |
| `-m pytest -q -rs files/tests/test_config.py` | **68 passed** |
| `-m pytest -q -rs files/tests/test_settings.py` | **25 passed** |
| `-m pytest -q -rs files/tests/test_repository_contract.py` | **40 passed** |
| `-m pytest -q -rs files/tests/test_launcher_smoke.py` | **11 passed** |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** — all executed |
| `-m pytest -q -rs files/tests/test_prototype_regression.py` | **12 passed** |
| `-m pytest --collect-only -q files/tests/` | **295 collected** (was 230) |
| `-m pytest -q -rs files/tests/` | **292 passed, 3 skipped, 1 warning** |
| `scripts/verify.py` | **RESULT: PASS** across five checks |
| `-m compileall -q scripts files/tests` | exit 0 |
| `git diff --check` | **clean, exit 0 — zero notices** |

The 1 warning is the pre-existing pydub `audioop` `DeprecationWarning`; the 3 skips are the
`JACK_RYAN_M4B_FOLDER`-gated tests. +65 collected = exactly the new file.

#### Live Windows manual verification — PASSED (2026-08-03, HOME-PC)

Windows 11, 1920×1080 **primary display at 100% scaling**, Tk reporting 96 px/inch, repo venv
Python 3.12.10, driven against the **real** `LauncherApp` with the settings layer redirected to
a temporary file (the maintainer's real `settings.json` was never read or written).

| Check | Observed |
|---|---|
| Launcher opens | 1024×720 at default geometry, `minsize=(920, 600)` |
| Preferences opens | 618×596, title `Preferences & Data` |
| Repeated activation | same object returned, **1** toplevel open |
| Keyboard traversal | Radiobutton → Save → Reset Preferences… → Close, cycling |
| Effective value + source | `C:\Users\…\Downloads\Audiobook-Creation-Tool-Outputs` — "Using the default Downloads location (config.toml leaves it unset)." |
| Rejected relative path | `Outputs` → refused, error status, nothing saved |
| Rejected environment variable | `%USERPROFILE%/Outputs` → refused (stays literal, therefore relative) |
| Accepted absolute path | saved; **folder not created**; source became "your saved preference" |
| Reset cancelled | returned False, "Reset cancelled. Nothing was changed.", value kept |
| Reset confirmed | success, mode back to default, effective back to Downloads |
| Failure presentation | injected write failure → "Your preferences could not be saved. The previous setting is still in use." and the prior value still in force |
| Cleanup placeholder | label `Clear Downloaded Data`, state `('disabled',)`, **command `''`**, caption as specified |
| Escape | dialog closed |
| Once-per-launch warning | temporary malformed config in a fake repo root → **1** window, second call returned `None`, summary listed both bad keys as bullets with no traceback |
| Fit at 1024×720 | dialog 618×596, fits 920×600 |
| Fit at 920×600 minimum | dialog 618×596, Save and Close both inside the form |
| Maximized | launcher 1920×1009, dialog fits the screen |

#### Manual checks still PENDING — not claimed as passed

1. **Windows 125% display scaling.** Requires the maintainer to change Settings → System →
   Display; it cannot be set from here without altering the machine's configuration. The app
   is DPI-unaware (Plan 1 finding), so Windows bitmap-scales the whole window uniformly and
   nothing can clip differentially — but that is *reasoning*, not evidence, and it is recorded
   as pending, not as a pass.
2. **Live macOS.** An explicit deferral, as this phase's instructions direct.
3. **Screenshot evidence** for the new surfaces. Deferred to Phase 8's manual matrix, which
   owns the evidence collection; Phase 2 recorded measurements instead of adding image files.

### Next action

**Phase 3 — shared output reservation, collision, and mirroring services.** Not started. It
requires explicit maintainer approval before any work begins.

---

## Phase 1 record (v0.6.0 Drop 2, approved 2026-08-03)

**v0.6.0 Drop 2 (Plan 2) — PHASE 1 COMPLETE.**

Active drop: `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md`
(temporary; deleted only in its approved Phase 9 closeout).

**Branch:** `feature/0.6.0-drop2-config-output-maintenance-foundation`
**Phase 0 start SHA (= verified `origin/master` at fetch time):**
`bada8a3dee87acf6a6619252bd31cdee429f1711`
**Phase 0 commit:** `ca10c5beb8d2ac6a89ce345a7ba96f733de5df42` (approved 2026-08-03)
**Phase 1 commit:** the branch HEAD created by the Session Sync Log entry below — a commit
cannot name its own SHA, so read it with
`git log -1 feature/0.6.0-drop2-config-output-maintenance-foundation`.

### Phase 1 — canonical-file gate and configuration core (2026-08-03, HOME-PC)

**Result: the documentation contract is now mechanically enforced and the configuration core
exists, with no GUI, no tool-output change and no new dependency.** Ten files changed, four
added. `version.py` is still `0.5.1`.

#### What was built

| Area | Outcome |
|---|---|
| Root `config.toml` | **New, committed, commented, machine-agnostic.** `project.{name,version,python_min,entry_point,platforms}`, `output.base_directory`, `logging.max_sessions`, `importing.large_result_warning_threshold`. Written from the Plan 2 specification; the maintainer's unrelated `config-template.toml` was **not** opened, copied or referenced. |
| `shared/config.py` | **New, 660 lines.** One typed, immutable `EffectiveConfig` (frozen dataclasses + tuples + `MappingProxyType`) built as **code defaults → valid TOML → allowlisted settings overlay**. Per-key validation, `Diagnostic` records, `warning_summary()` aggregation/deduplication, `get_effective()` / `reload()` / `invalidate()`. Standard-library `tomllib` only. |
| `shared/settings.py` | Extended narrowly: `reset()`, bool returns from `save()`/`set()`/`update()`, `last_load_error()`, `invalidate()`, and `use_path()` as the test-injection seam. A malformed file is **never rewritten during a load**. |
| `shared/logging_setup.py` | `configured_max_sessions()` reads `logging.max_sessions` through the effective configuration, importing config **lazily inside the function**, and falls back to 30 on any failure. |
| `scripts/verify.py` | Canonical `Changelog.md` reference, plus two new checks: `docnames` and `config`. |
| Tests | Three new files, **133 tests**, all using temporary directories and injected paths. |

#### Precedence and the mutable overlay

`config.SETTINGS_OVERLAY` is the entire allowlist and today contains exactly one entry:
`output_base_directory` → `output.base_directory`. Known user-state keys (`last_tool`,
remembered input/cover/output directories, voice, bitrate) stay legitimate settings, are
skipped silently, and deliberately have **no** invented TOML counterpart. Anything else in
`settings.json` is ignored with one aggregated diagnostic. A whitelist was chosen over
name-matching so a future preference cannot silently become a configuration override — see the
2026-08-03 ADR in `Decisions.md`.

#### The runtime and the gate deliberately disagree

At runtime an invalid value **falls back and warns**, per key, so a user's hand-edit can never
stop the application starting and one bad key never discards a good neighbour. `verify.py`
**fails on any diagnostic** from the committed file, because a shipped file that needs a
fallback is a defect. Both use the same loader, so the two rule sets cannot drift.

#### The casing defect recorded in Phase 0 is fixed — correctly

`scripts/verify.py:34` read `md-instructions/CHANGELOG.md`, a name that has not existed since
the documents were recased. **The reference was wrong; the files were right**, so the reference
moved and no document was renamed. The new `docnames` check compares **real directory entries**
(`os.listdir`) against the exact canonical names rather than calling `Path.exists()`, which is
what let the defect hide on NTFS. Other active references corrected: `README.md`'s layout tree,
`Briefing.md`'s pointers and cross-references, and `release.py`'s printed release checklist.
Left deliberately historical: the archived `files/release-history/*.md` notes, this file's own
Phase 1–6 Plan 1 entries, the protected `don't-delete/` references, the active drop's own
instruction text, and the dated `# … see CHANGELOG 2026-07-19` comment in `voice_registry.py`
(a pointer to a historical entry inside an unrelated tool module).

#### Proof the gate is real, not NTFS luck

`verify.py`'s two new checks take optional paths so the suite can drive them against temporary
trees — necessary because a case-insensitive filesystem will not let a real alias be staged
beside its canonical twin. `test_repository_contract.py` proves the gate **fails** on: a
missing canonical document; `CHANGELOG.md` in place of `Changelog.md`; each lowercase alias; a
deleted `don't-delete/` reference; a missing `don't-delete/` directory; an invalid committed
config; project-version drift; malformed TOML; and a missing config file. It also asserts
`verify.py` holds no stale alias as a real string value (AST-parsed, so the docstring may keep
explaining the defect without tripping the test that enforces the fix).

#### Verification (repo venv, Python 3.12.10, HOME-PC, Windows 11)

| Command | Result |
|---|---|
| `-m pytest -q -rs files/tests/test_repository_contract.py` | **40 passed** |
| `-m pytest -q -rs files/tests/test_config.py` | **68 passed** |
| `-m pytest -q -rs files/tests/test_settings.py` | **25 passed** |
| `-m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** — all theme tests executed |
| `-m pytest --collect-only -q files/tests/` | **230 collected** (was 97) |
| `-m pytest -q -rs files/tests/` | **227 passed, 3 skipped, 1 warning** (was 94/3/1) |
| `scripts/verify.py` | **RESULT: PASS** — pytest, deps, docs, **docnames**, **config** |
| `-m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | 225 notices, **all** on the three CRLF markdown files; **zero** on any `.py` or `.toml` |

The 1 warning is the pre-existing pydub `audioop` `DeprecationWarning`. The 3 skips are the
`JACK_RYAN_M4B_FOLDER`-gated tests. **No test was lost:** 97 → 230 collected is +133, exactly
the new files.

#### `git diff --check`, stated honestly

Every notice is the **inherited CRLF condition** recorded in Phase 0: the blobs GitHub stored
for `Briefing.md`, `Changelog.md` and `Decisions.md` use CRLF, so each added line reads as
trailing whitespace. Per the maintainer's Phase 0 decision, no renormalisation was run and no
formatting pass was performed; the edits inherited each file's existing endings, so the diffs
stayed line-based (+83 / +67 / +85) instead of becoming whole-file rewrites. **Phase 1
introduced no new whitespace error** — the check names no `.py`, `.toml` or `README.md` line.

#### What Phase 1 deliberately did not do

No Preferences dialog, no visible configuration-warning presentation, no GUI Reset control, no
Clear Downloaded Data, no post-exit cleanup, no run reservation, no collision or mirroring
service, no tool migration, no Cover source-side mode, no M4B Maker custom destination, no
Plan 3 import behaviour. `shared/paths.py` and all six tool panels are **untouched**;
`launcher.py` is untouched. `test_repository_contract.py` asserts the launcher gained no
Preferences/Reset/Cleanup surface and that `config.py` defines no run-reservation or mirroring
function and performs no filesystem write.

### Next action

**Phase 2 — Preferences, warning presentation, and Reset Preferences.** Not started. It
requires explicit maintainer approval before any work begins.

---

## Phase 0 record (v0.6.0 Drop 2, approved 2026-08-03)

**Phase 0 start SHA (= verified `origin/master` at fetch time):**
`bada8a3dee87acf6a6619252bd31cdee429f1711`
**Local `master`:** fast-forwarded `1da1e547…` → `bada8a3…` (`--ff-only`, no merge commit, no
reset, no stash, no rewrite). Local `master` and `origin/master` are equal.

### Plan 1 ancestry — verified, not assumed

| Required commit | Present in `origin/master` ancestry |
|---|---|
| Plan 1 merge (PR #2) `86933e6510c6303cadf3437dc295d000ffa9ee82` | **YES** (`git merge-base --is-ancestor` → 0) |
| Plan 1 feature head `f3d70e8c9017f2fec3ae459c1438dd71b42f9ef0` | **YES** |
| Previous local `master` `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318` | **YES** — so the update was a true fast-forward |

The branch `feature/0.6.0-drop1-windows-ui-prototype` still exists locally and on `origin`
at `f3d70e8` and was **not** deleted. All ten approved screenshots under
`files/UI-Prototype-Screenshots/v0.6.0-drop1/` are present and unmodified.

**What the two commits above the Plan 1 merge are.** `origin/master` gained
`d2d6f0e` ("Delete md-instructions directory") and `bada8a3` ("Add files via upload") after
PR #2. Inspected commit-by-commit, that pair is the maintainer's GitHub-web rename of the
documentation to its canonical casing plus the addition of the permanent planning references:

- `CHANGELOG.md` → `Changelog.md`, `DECISIONS.md` → `Decisions.md`, `handoff.md` → `Handoff.md`
  (`Briefing.md` unchanged in name);
- new `md-instructions/don't-delete/` holding the Approved Plan Series Map, Decision
  Register 1–55, and the 2026-07-31 Planning Handoff.

No source, test, or screenshot was touched by either commit. This is the reason the four
canonical names are now correct in the repository while `scripts/verify.py` still points at
the old casing — see the baseline defect below.

### Planning artifacts (authorized, now tracked)

Two authorized Plan 2 planning artifacts were placed in the worktree by the maintainer and are
committed in this Phase 0 commit:

- `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md` — the active temporary drop;
- `md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
  — permanent program index.

The only other untracked worktree item is the pre-existing root `config-template.toml`. It is
**unrelated user work**: not edited, staged, committed, renamed, copied or used as a source for
Plan 2's future `config.toml`. It remains untracked and byte-for-byte unchanged.

### Phase 0 baseline evidence (2026-08-03, HOME-PC, repo venv Python 3.12.10)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | **17 passed, 0 skipped** — all theme tests executed |
| `.venv\Scripts\python.exe -m pytest -q -rs files/tests/test_launcher_smoke.py` | 11 passed, 1 warning |
| `.venv\Scripts\python.exe -m pytest -q -rs files/tests/test_m4b_metadata_editor_shared.py` | 7 passed |
| `.venv\Scripts\python.exe -m pytest -q -rs files/tests/test_m4b_metadata_editor_ui.py` | 12 passed |
| `.venv\Scripts\python.exe -m pytest -q -rs files/tests/test_prototype_regression.py` | 12 passed, 1 warning |
| `.venv\Scripts\python.exe -m pytest --collect-only -q files/tests/` | **97 tests collected** |
| `.venv\Scripts\python.exe -m pytest -q -rs files/tests/` (full suite) | **94 passed, 3 skipped, 1 warning** |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** (exit 0) — but see the casing defect below |
| `.venv\Scripts\python.exe -m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | clean — exit 0 |

The 1 warning is the pre-existing pydub `audioop` `DeprecationWarning`. The 3 skips are the
`JACK_RYAN_M4B_FOLDER`-gated tests in `test_jack_ryan_final_product.py`, named by `-rs`. The
merged-master baseline is therefore **identical** to the Plan 1 closeout baseline
(94 passed / 3 skipped) — no test was lost by the merge or the documentation rename.

### Baseline defect recorded, NOT fixed in Phase 0

`scripts/verify.py:34` still reads `REPO_ROOT / "md-instructions" / "CHANGELOG.md"`. That file
name no longer exists — the canonical name is `Changelog.md`. The gate still reports
`RESULT: PASS` **only because NTFS is case-insensitive**, so `Path("md-instructions/CHANGELOG.md").exists()`
returns `True` while `"CHANGELOG.md"` is absent from the directory listing. Proven directly:

```
actual filenames on disk: ['0.6.0-drop2-…md', 'Briefing.md', 'Changelog.md', 'Decisions.md', 'Handoff.md']
CHANGELOG.md    exists()=True   exact-name-present=False
DECISIONS.md    exists()=True   exact-name-present=False
handoff.md      exists()=True   exact-name-present=False
```

On a case-sensitive filesystem the `docs` check would FAIL. This is a genuine cross-platform
verification defect and is **Phase 1's** work (drop §5, §8 Phase 1 task 2): fix the reference,
never rename the document. Phase 0 changed no production code.

### Second baseline finding recorded, NOT fixed in Phase 0 — CRLF in the web-uploaded docs

`git diff --check` (worktree vs index — the gate this drop names) is **clean, exit 0**. But
`git diff --cached --check` reports 224 whitespace notices on the Phase 0 commit. They are
**entirely pre-existing**, not introduced here:

- **209 of them are `md-instructions/Handoff.md`** — one per added line. The blob GitHub stored
  for this file in `bada8a3` uses **CRLF**, because a web upload bypasses the `.gitattributes`
  `* text=auto` clean filter. `git diff --check` reads each `\r` as trailing whitespace. Every
  line I added inherited the file's existing CRLF, so the diff stays minimal (209 insertions,
  **0 deletions**) rather than becoming a whole-file rewrite.
- **8 + 7 are the two new planning artifacts** — the maintainer's markdown hard-break trailing
  double-spaces on their header lines, plus one "new blank line at EOF" each. That is authored
  file content, not damage.

Scale check: `git show bada8a3 --check` emits **9202** notices, against **52** for the
agent-authored Plan 1 closeout `f3d70e8`. The condition arrived with the web upload.

Deliberately not fixed: normalizing `Handoff.md` to LF would rewrite ~2,800 lines and bury the
Phase 0 diff, and reformatting the maintainer's planning artifacts exceeds the one factual
status correction Phase 0 permits. Cosmetic only — CRLF in `.md` breaks nothing on either
platform. Flagged for the maintainer to decide; a `git add --renormalize md-instructions/`
in a scoped later phase would clear it in one commit.

### Skills audited for Plan 2

| Skill | Location | Verdict |
|---|---|---|
| `audio-processing` | `.claude/skills/audio-processing/SKILL.md` | **Will use** — its copy-first/never-overwrite-in-place rule, `shutil.copy2` + temp-then-replace pattern, and subprocess-list/`shlex.quote` rule map directly onto Plan 2's collision service, the Cover replace-original atomic write, and the launcher/bootstrap cleanup coordination. |
| `fullstack-bridge-sync` | `.claude/skills/fullstack-bridge-sync/` | **Not applicable** — Python↔TypeScript API contract syncing; this project has no frontend/backend split. |
| `.codex/skills/` | — | Directory does not exist on this machine; nothing to audit. |

User-scope plugin capabilities (Superpowers, Sequential Thinking, Context7) remain available
and will be used proportionally where they fit; none was needed for Phase 0. No new skill,
plugin, or dependency was installed — the drop forbids expanding `.claude/`/`.codex/` scope.

### Implementation surface inspected (read-only, Phase 0)

- `shared/paths.py` — `TOOL_SLUGS` (six stable slugs), `downloads_dir()`, `next_output_dir()`
  (non-atomic check-then-name, `Downloads/<Tool>-N`, no configurable base), `avoid_input_overwrite()`.
- `shared/settings.py` — 83 lines; lazy `_cache`, forgiving load, atomic `save()` via
  `mkstemp`+`os.replace`; **no allowlist, no reset API, no cache invalidation, no diagnostics**.
- `shared/logging_setup.py` — hard-coded `MAX_SESSIONS = 30`.
- `shared/bootstrap.py` — 1408 lines, stdlib+Tk only, pre-venv; `--launch-only` fast path and
  `--self-test`; the correct coordination boundary for post-exit cleanup.
- `shared/release.py` — packages README + the OS launcher + the whole `scripts/` tree; **no
  root `config.toml`** is packaged today.
- `shared/ui_theme.py` — 1076 lines; `DEFAULT_GEOMETRY = "1024x720"`, `MIN_SIZE = (920, 600)`,
  `WINDOWS_STYLE_PREFIX = "ACT"`, `style_tk_widget`, `enable_mousewheel`, `ProgressIndicator`.
- `launcher.py` — 573 lines; six-tool registry, three shell branches, no Preferences entry point.
- Tool panels: TTS (`epub2tts_gui.py:90`), M4B Converter (`:95`), MP3 Tool (`:372`),
  M4B Maker (`:397`) and M4B Metadata (`:194`) all call `paths.next_output_dir(SLUG)` **at
  panel-build time**, which is exactly what drop §6.4 requires moving to validated run start.
  `cover_resizer.py` has **no** run folder at all — it writes beside the source with an
  `overwrite` checkbox (`:191`), so Plan 2 gives it the standard default plus the approved
  opt-in source-side mode.
- Root launchers: `.bat` (78 lines, `pythonw.exe` no-console fast path), `.command` (214 lines).
- `scripts/verify.py` (168 lines), `.gitignore`, `.gitattributes`, `scripts/requirements.txt`
  (all `==`-pinned), `files/tests/` (18 test modules + `conftest.py` + the developer-only
  `manual_windows_ui_prototype.py`).

`version.py` remains `VERSION = "0.5.1"`. No version bump, tag, release, merge, or PR occurred.

### Next action

**Phase 1 — canonical-file gate and configuration core.** Not started. It requires explicit
maintainer approval before any work begins.

---

## Previous Focus (v0.6.0 Drop 1 — Plan 1, approved 2026-08-02, merged through PR #2)
**v0.6.0 Drop 1 (Windows UI prototype) — APPROVED 2026-08-02 and CLOSED OUT. PLAN 1 IS
COMPLETE.** The maintainer replied `APPROVED` to the Phase 5 ten-image matrix and the
functional evidence. Phase 6 recorded the accepted contract in the permanent docs and
deleted the temporary drop; the plan file
`md-instructions/0.6.0-drop1-windows-ui-prototype.md` **no longer exists** (deleted in the
Phase 6 commit, as the workflow requires).

**Approval is of a design contract, not a release.** `version.py` is still `0.5.1`, there is
no v0.6.0 release heading anywhere, nothing was merged to `master`, and no release package
was built. **Next implementation-planning target: Plan 2 — undrafted and unstarted.**
(Plan 1 of nine planned v0.6.x instruction drops; the remaining eight are named in
the plan's sequencing note but are **not drafted and must not be started**).

**Branch:** `feature/0.6.0-drop1-windows-ui-prototype`
**Start SHA (actual implementation base):** `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318`
— this is `origin/master` after a fast-forward-only pull, and it is **identical to the
plan's stated planning-audit baseline**, so there is **zero drift** to explain.
The desktop checkout was 10 commits behind at `695045c` and fast-forwarded cleanly
(no divergence, no merge, no reset, no stash).

**Phase 0 commit:** `0971a20e24fc196967da97d1b204375dc549ad5a` (docs only).
**Phase 1 commit:** `9cd7fb8e04e11d64f9303d0f44a7ca3f3723af51`.
**Phase 2 commit:** `b2e5285958a8d7adcc19a4c17d45f1e55fd7e900`.
**Phase 3 commit:** `d8d0b1b7aec1b62d80989ffb791cda313fb22763`.
**Phase 4 commit:** `9d4f58cdb24f0963552490d73273acaec1369589`.
**Phase 5 commit (the approved evidence SHA):** `b2e809fe4e25f5aaaef1684b5998bc652374de87`.
**Phase 6 commit (closeout):** the branch HEAD created by the Session Sync Log entry below —
a commit cannot name its own SHA, so read it with
`git log -1 feature/0.6.0-drop1-windows-ui-prototype`. It is also stated in the Phase 6
summary returned to the maintainer.

**Phase 0 result:** baseline established and green. No theme, launcher, tool-panel,
test, `requirements.txt`, or `version.py` source was edited — Phase 0 is
reorient/synchronize/record only. `version.py` remains `0.5.1`; no version bump and
no v0.6.0 release is part of this drop.

**Phase 1 result:** the Windows design system exists and is proven isolated. Two
files changed — `scripts/Universal/shared/ui_theme.py` (+795/-7) and
`files/tests/test_ui_theme.py` (+429/-13). **Nothing was converted:** the launcher,
all six tool panels, `requirements.txt` and `version.py` are byte-identical to
Phase 0. A live run of the real launcher confirms every one of the 283 widgets
across the six panels and all 14 launcher-chrome widgets still carries an **empty**
style string, i.e. still renders through the native `vista` theme.

**Hard boundaries carried forward (from the plan):**
- Only the **Windows launcher shell** and the **Windows M4B Metadata Editor** may ever
  be converted by this plan. TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker, and
  Cover Image Resizer must stay unconverted and protected from ttk style leakage —
  before *and* after screenshot approval. Their conversion belongs to Plan 9.
- macOS aqua/Finder and the Linux/other fallback must remain unchanged.
- No toolkit switch away from tkinter/ttk, no new runtime dependency,
  no `requirements.txt` change, no release.
- Phase 5 has a hard **visual approval gate**: the exact ten-image 1920×1080
  100%/125% matrix under `files/UI-Prototype-Screenshots/v0.6.0-drop1/`, then an
  explicit user *approved* / *changes requested* decision. Screenshots existing is
  not approval.

**Phase 2 result:** the Windows launcher shell is converted and recognizably
redesigned — dark navigation rail, header strip naming the active tool, framed
content card, status bar with a focusable log action. Two files changed:
`scripts/Universal/launcher.py` (+151/-8) and `files/tests/test_launcher_smoke.py`
(+299/-0). **`shared/ui_theme.py` was NOT edited** — the Phase 1 API was sufficient.
The five unconverted panels (and the not-yet-converted metadata editor) still carry
an empty style string on every widget. One genuine geometry regression was measured
and is **open for a maintainer decision** — see *Phase 2 limitations* below.

**Phase 3 result:** the Windows M4B Metadata Editor is converted and is now the
**only** converted tool panel. Six files touched (two new). The panel forks on
`theme["mode"]`: `windows` builds the new card layout, every other mode builds the
historical layout byte-for-byte. The maintainer-approved `sidebar_width` correction
(232 → 180) shipped with it and gave the tool panels **+52px of width** back at every
window size. The five unconverted panels still carry **zero** namespaced styles.
Full detail in *Phase 3* below; the one thing still open is the **vertical** part of
the Phase 2 geometry regression, which the width change could not address.

**Phase 4 result:** the prototype was audited, regression-tested and functionally
exercised on Windows, and **no source defect caused by Phases 1–3 was found**, so
Phase 4 is **test-and-documentation-only**: one new test file, no production-source
change. The whole-diff audit proves every non-Windows code path and every
behavioural method is byte-identical to `master`, and the Section 11 matrix ran
against the real launcher and the real editor on disposable fixtures with SHA-256
evidence at every step. Full detail in *Phase 4* below.

**Phase 5 result:** the exact ten-image matrix exists at
`files/UI-Prototype-Screenshots/v0.6.0-drop1/`, captured from the real application at
1920×1080 in **two true Windows display-scaling passes** (100% and 125% — Windows did
the scaling, not Tk, not an image editor). **No production source changed:**
`git diff --name-only 9d4f58c..HEAD -- scripts/ files/tests/` is empty. Two files
were added to the repository beyond the PNGs: none. Full detail in *Phase 5* below.

**Phase 6 result:** closeout only — the accepted contract is now recorded in `Briefing.md`,
`CHANGELOG.md` and `DECISIONS.md`, this file carries the approval record, and the temporary
drop is deleted. **No production code changed in Phase 6** (`git diff --name-only
b2e809f..HEAD -- scripts/ files/` is empty). `README.md`, `AI-WORKSPACE.md`, both setup
launchers, `scripts/requirements.txt` and `version.py` are untouched.

### Phase 6 — approved closeout (2026-08-02, HOME-PC)

#### The approval record

**On 2026-08-02 the maintainer replied `APPROVED`** to the Phase 5 phase summary, the ten
screenshots and the functional evidence. The decisions recorded with that approval, verbatim
in substance:

| # | Approval decision |
|---|---|
| 1 | The complete ten-image visual matrix is **approved**. |
| 2 | The 125% images captured on the **secondary** 1920×1080 display are accepted as valid evidence; **no primary-monitor reshoot** is required. |
| 3 | The current Summary/Details specimen is **sufficient** — no additional Details screenshot, no change to the specimen. |
| 4 | Keep `MIN_SIZE = (920, 600)` and `DEFAULT_GEOMETRY = (1024, 720)` **unchanged**. |
| 5 | The remaining **M4B Converter** minimum-height clipping is **deferred to its Plan 9 conversion**. |
| 6 | The **DPI-unaware** behaviour does **not** block Plan 1 approval, because the app stays usable and unclipped at 125% — but it must be recorded prominently as **unresolved Windows work** for Plan 9 or an appropriately scoped future plan, and **must not be fixed during Phase 6**. |
| 7 | **Live macOS testing remains an explicitly approved deferral** and must never be called passed. |
| 8 | **tkinter/ttk is approved** as the continuing UI toolkit for the broader Plan 9 conversion. |
| 9 | The **five unconverted panels remain deferred to Plan 9**. |
| 10 | **Plan 2 is the next implementation-planning target** after Plan 1 closes. |

**Approved evidence path and SHA:** `files/UI-Prototype-Screenshots/v0.6.0-drop1/` (ten PNGs)
at Phase 5 SHA `b2e809fe4e25f5aaaef1684b5998bc652374de87`, branch
`feature/0.6.0-drop1-windows-ui-prototype`. All ten remain present and unmodified; Phase 6
did not touch, re-shoot, crop or re-encode any image.

**Phase 6 start SHA:** `b2e809fe4e25f5aaaef1684b5998bc652374de87`
**Phase 6 end SHA:** recorded in the Session Sync Log entry below.

#### Exact permanent-document updates

| Document | What was added |
|---|---|
| `md-instructions/Briefing.md` | Tech-stack GUI bullet rewritten for the three explicit theme branches and ttk's continued acceptance; the launcher architecture bullet now describes all three shells and the deliberately unstyled content host; the `shared/` bullet names `style_tk_widget`; **three new architecture bullets** — the Windows design system (semantic tokens, no panel-local literals), the `ACT.*` isolation contract (why cloning clam elements into vista is the mechanism, and why ttk's lack of style inheritance is what makes it structural), and the conversion boundary; the editor feature entry gained its Windows presentation fork, plus new entries for the Shared Metadata visual treatment and the developer-only Summary/Details specimen; the layout tree now shows both screenshot directories; **three new known limitations** (DPI-unaware, unchanged geometry + converter clipping, unthemed combobox popdown and light title bar); High-Level State gained the v0.6.0 Drop 1 approval paragraph and a standing non-Windows preservation contract naming the four tests that hold it. |
| `md-instructions/CHANGELOG.md` | Three entries **beneath the existing `[Unreleased]` heading** — Added (theme primitives, `ACT.*` namespacing, launcher shell, converted editor, Shared Metadata treatment, developer-only specimen, the ten evidence images), Changed (`sidebar_width` 232 → 180 with the measurement that justified it, and the explicit note that `MIN_SIZE`/`DEFAULT_GEOMETRY` are unchanged), and Added — regression protection (the twelve new tests and what they pin down, plus the unresolved DPI note). **No v0.6.0 release heading was created and no release is claimed.** |
| `md-instructions/DECISIONS.md` | One newest-first, dated, signed ADR: *"The Windows dark design system is APPROVED as the durable UI contract; tkinter/ttk stays; geometry, DPI awareness and live macOS are explicitly deferred."* Records the contract, the evidence path and Phase 5 SHA, the namespaced isolation rule, why ttk remains acceptable (with a "do not propose a toolkit change" instruction to future sessions), macOS/Linux preservation, the geometry deferral, the live-macOS deferral, DPI awareness as unresolved future work, and the alternatives rejected. **No historical entry was rewritten and the Decisions 1–55 planning register was not duplicated.** |
| `md-instructions/handoff.md` | This section, the Current Focus rewrite, the Definition-of-Done assessment below, a Work Log entry and a Session Sync Log entry. |
| `README.md` | **Unchanged**, deliberately — the user-facing launch/setup procedure did not change, and the drop is visual and unreleased. |
| `AI-WORKSPACE.md` | **Unchanged**, deliberately — never edited or published as part of a drop. |
| `scripts/Universal/shared/version.py` | **Unchanged** — still `VERSION = "0.5.1"`. |
| `scripts/requirements.txt` | **Unchanged** — no dependency was added, removed or re-pinned in the entire drop. |

#### Temporary-drop deletion

`md-instructions/0.6.0-drop1-windows-ui-prototype.md` was **deleted** in the Phase 6 commit,
as the workflow requires once a plan is implemented and verified. It was a tracked file, so
the deletion is recorded in git history and the plan text remains recoverable from any
Phase 0–5 commit. **No other plan or documentation file was deleted.** The durable record of
what that plan established now lives in `Briefing.md` (architecture), `CHANGELOG.md`
(what changed), `DECISIONS.md` (why, and what was deferred) and this file (state and evidence).

#### Plan 1 — Definition of Done assessment

| Definition-of-Done item | Result |
|---|---|
| Started from an updated, clean `master` with the actual start SHA recorded | **MET** — `1da1e547`, recorded in Phase 0 and above; zero drift from the plan's audit baseline |
| Centralized semantic Windows tokens, metrics, fonts and namespaced ttk/Tk helpers in the existing shared architecture | **MET** — `shared/ui_theme.py`; no new module tree, no new dependency |
| Windows launcher shell is a meaningful dark hierarchy/layout redesign | **MET** — approved on the evidence; rail + header + content card + status bar, not a recolour |
| The M4B Metadata Editor is the only converted tool panel | **MET** — 19 `ACT.*` styles in the editor, 0 in each of the other five, measured in the live app |
| The five classic panels were not converted and were protected from style leakage | **MET** — snapshot tests across theme application, editor construction and a whole app build |
| macOS retains Finder/aqua and the Linux/other fallback is unchanged | **MET at the code level** (byte-identical functions + four automated tests). **Live macOS is an approved deferral — NOT claimed as passed.** |
| All six panels build, switch and preserve state per the current contract | **MET** — `test_launcher_smoke.py`, plus three live sweeps in the Phase 4 matrix |
| Every editor input, action, page, worker, progress/log state, Cancel path, copy-only output and read-only-original safeguard still works | **MET** — the nine-area Section 11 matrix on disposable fixtures, with source SHA-256 verified unchanged at seven checkpoints |
| Shared Metadata has the approved distinct treatment without Plan 6/8 behaviour | **MET** |
| Summary/Details has an approved presentation-only specimen without Plan 3 behaviour | **MET** |
| The exact ten-image 1920×1080 100%/125% matrix exists at the approved path | **MET** |
| The user explicitly approved the matrix after reviewing functional results | **MET** — `APPROVED`, 2026-08-02 |
| Focused tests, full pytest, `git diff --check` and `verify.py` pass at closeout | **MET** — counts in the Phase 6 results table below |
| Required manual checks passed, or an explicit user-approved deferral recorded; no unperformed check called passed | **MET** — the only deferral is live macOS, explicitly approved (decision 7), and it is nowhere described as a pass |
| `requirements.txt` unchanged and `version.py` still `0.5.1` | **MET** |
| Briefing / CHANGELOG / DECISIONS / handoff have accurate, non-duplicated closeout updates; `README.md` unchanged unless its user instructions truly changed | **MET** — README deliberately unchanged |
| No Plan 2/3/6/8/9 feature work, toolkit switch, runtime dependency, release package or speculative architecture entered the drop | **MET** |
| The temporary instruction file is deleted and the branch is clean after its final commit | **MET** |

**All eighteen items are satisfied**, with the single deferral (live macOS) explicitly
approved by the maintainer rather than assumed. **Plan 1 is complete.**

#### Carried-forward limitations (open, and owned by later work)

1. **DPI awareness — unresolved Windows work.** The app is DPI-unaware, so at 125% Windows
   bitmap-scales the window and text is soft. Did not block approval (nothing clips, the app
   stays usable); recorded in `Briefing.md` and `DECISIONS.md`. A fix needs a manifest or a
   `SetProcessDpiAwareness` call **plus** a re-measure of every fixed pixel metric and fresh
   screenshot evidence. **Plan 9 or a scoped future plan.**
2. **Live macOS verification of the v0.6.0 line — approved deferral, never a pass.** The exact
   five-step smoke test is preserved in *Phase 4 limitations* item 1.
3. **M4B Converter clipping at the 920×600 minimum** (~19 px action, ~108 px + 75 px Log,
   identical at both scalings) — deferred to that panel's Plan 9 conversion. `MIN_SIZE` and
   `DEFAULT_GEOMETRY` stay unchanged.
4. **The five unconverted panels** remain classic and deferred to Plan 9.
5. **`ttk.Combobox` popdown unthemed** and the **window title bar stays light** over the dark
   app (needs a Win32 `DwmSetWindowAttribute` call) — both Plan 9.
6. **The editor's form scrolls at every size**, including maximized (it wants 1083 px). Permitted
   by plan §7.3 and visible in the approved evidence; not a defect.
7. **The `verify.py` skip blind spot** — the gate cannot distinguish "a suite was skipped" from
   "a suite does not exist", so the Tk transient seen in Phases 3 and 4 could hide a whole
   module while still reporting PASS. It did not recur in Phases 5 or 6. Pre-existing; owned by
   whoever hardens `verify.py`, not by Plan 1.
8. **Pre-existing and untouched:** the launcher status bar does not follow a tool's run; an
   unreadable input is copied before its tag write fails, leaving an untagged copy; Open
   Issue #2 (`kokoro_synth` CLI-only cp1252 `UnicodeEncodeError`).

#### Phase 6 verification (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **17 passed, 0 skipped** |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 11 passed, 1 warning |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_ui.py` | PASS — 12 passed |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_prototype_regression.py` | PASS — 12 passed, 1 warning |
| `.venv\Scripts\python.exe -m pytest -q -rs` (full suite) | PASS — **94 passed, 3 skipped**, 1 warning |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** |
| `.venv\Scripts\python.exe -m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | clean — exit 0 |

Exact timings are in the Session Sync Log entry. Unchanged from the Phase 4/5 baseline, which
is the expected result for a documentation-only phase. The 1 warning is the pre-existing pydub
`audioop` DeprecationWarning; the 3 skips are the three `JACK_RYAN_M4B_FOLDER`-gated tests in
`test_jack_ryan_final_product.py`, named by `-rs`. All 17 theme tests executed; the Tk skip
transient did not recur.

### Phase 5 — visual evidence capture (2026-08-01, HOME-PC)

**Branch and SHA the images were generated from:**
`feature/0.6.0-drop1-windows-ui-prototype` @ `9d4f58cdb24f0963552490d73273acaec1369589`
(Phase 4 HEAD). No source was edited before, during or after capture.

#### Environment and how each scaling pass was verified

| | 100% pass | 125% pass |
|---|---|---|
| Physical resolution | 1920×1080 | 1920×1080 |
| Display used | primary (rect `0,0–1920,1080`) | secondary (rect `-1920,0–0,1080`) |
| `GetDpiForMonitor(MDT_EFFECTIVE_DPI)` | **96 → 100%** | **120 → 125%** |
| Window state | maximized | maximized |
| Captured image size | 1920×1032 | 1920×1020 |
| ttk base theme | `vista` | `vista` |

Scaling was verified by enumerating every monitor with `EnumDisplayMonitors` and reading
`GetDpiForMonitor` from a process explicitly set to `PER_MONITOR_AWARE_V2`, so the number
is the monitor's real effective DPI rather than whatever the app happens to believe.
Windows was **not** touched by script or registry — the maintainer changed the scale in
Settings → System → Display.

**Why the 125% pass ran on the second display, and why that is equivalent.** When asked,
the maintainer set 125% on the secondary display; the primary stayed at 100%. That is
sufficient, and not an approximation, because of the finding below: the application is
**DPI-unaware**, so Windows bitmap-scales its window whenever the window's display is not
at 100%. An unaware app on a 125% *primary* is virtualized in exactly the same way (it
sees a 1536×864 screen and Windows stretches the result to 1920×1080). The pixels are
produced by the same Windows scaler either way, and a screen capture reads the
framebuffer, so the physical panel is irrelevant to the image. If the maintainer wants
the second pass re-shot on a 125% primary, say so at the gate and it will be redone.

**The load-bearing finding of this phase: the application is DPI-unaware.**
`GetProcessDpiAwareness` returns `0 / UNAWARE`, and neither `.venv\Scripts\python.exe`,
`.venv\Scripts\pythonw.exe`, nor the base Python 3.12.10 interpreter they come from
carries a `dpiAware` manifest entry. `pythonw.exe` is what
`Setup_and_Run-audiobook-creation-tool.bat` launches, so this is the real end-user path.
Consequences, measured rather than assumed:

- At 100% there is no virtualization: 1:1 pixels, text fully sharp.
- At 125% Windows scales the **whole window as a bitmap**. The app's own coordinate space
  never changes — Tk still reports 96 px/inch and the maximized window is 1536×793
  *logical*, stretched to 1920×1020 *physical*. Text is therefore slightly soft rather
  than crisply re-rendered at 120 DPI.
- The good news is the direct consequence of the same fact: **nothing clips, overlaps,
  reflows or truncates at 125%**, because every dimension scales by the identical factor.
  The 125% layout is pixel-proportional to the 100% layout.
- Nothing was done about it. Making the app DPI-aware is a production behaviour change
  (a manifest or a `SetProcessDpiAwareness` call at startup) and Phase 5 is evidence-only.
  It is raised at the gate as a decision, not fixed.

#### The ten evidence images

All ten are full maximized application windows, uncropped, unannotated, unedited.

| # | Path (under `files/UI-Prototype-Screenshots/v0.6.0-drop1/`) | Source | State |
|---|---|---|---|
| 1 | `windows-100-launcher-overview.png` | **runtime app** | real `LauncherApp`, M4B Metadata selected, six nav rows, header, status bar + log action |
| 2 | `windows-100-m4b-metadata-empty.png` | **runtime app** | same window, empty editor, form scrolled to the foot so Chapter Titles / Output / action bar / Log are all shown |
| 3 | `windows-100-m4b-metadata-populated.png` | runtime app + **developer fixture data** | 3 canned books, shared fields pre-filled, Title varying → blank |
| 4 | `windows-100-m4b-metadata-active-run.png` | runtime app + **developer fixture state** | inputs locked, progress 2/3 67%, Cancel enabled, live log |
| 5 | `windows-100-summary-details-specimen.png` | **developer fixture** | Summary/Details component sheet + action-hierarchy swatch |
| 6–10 | the same five as `windows-125-*.png` | identical sources and states | true 125% Windows scaling |

**What came from the developer-only fixture, stated plainly.** Images 1 and 2 are the
shipped application with nothing added. Images 3 and 4 are the shipped launcher hosting
the shipped editor, with `files/tests/manual_windows_ui_prototype.py`'s canned books
(`_populate`) and its controlled busy state (`_make_busy`) applied — the fixture calls the
editor's own public methods, so the widgets, styles and state on screen are the real ones.
Image 5 is entirely the fixture's specimen sheet, and it carries its own on-screen
`VISUAL SPECIMEN — presentation only` disclaimer naming every Plan 3 behaviour it does
*not* have. The fixture remains unreachable from the runtime launcher
(`test_manual_fixture_is_developer_only_and_unreachable_at_runtime`).

**No private data.** The capture process ran with `USERPROFILE` pointed at
`C:\Users\Public`, so the editor's default output folder renders as
`C:\Users\Public\Downloads\M4B-Metadata-1` and the fixture's fictional books as
`C:\Users\Public\Audiobooks\Samples\…`. Those paths are still computed by the shipped code
from `Path.home()`; only the profile location differs. No username, no real audiobook
title, no real path and no real log content appears in any of the ten images. (For
contrast, the committed before-state `m4b-metadata-current-ui-2.png` does show the
maintainer's real profile path.)

#### Visual comparison against `files/UI-Current-Screenshots/`

Compared against `m4b-metadata-current-ui-1.png` / `-2.png` (same tool, same window size).

| Aspect | Current (v0.5.1) | Prototype |
|---|---|---|
| Hierarchy | one flat stack of hairline labelframes; no grouping beyond the frame captions | four titled cards — Audiobook Files, **Shared Metadata**, Chapter Titles, Output — each with its own surface, border and internal rhythm |
| Shared/batch fields | indistinguishable from any other field | a separate muted-navy surface with an accent border, an accent header, an explanatory caption and the batch notice inside it |
| Form layout | every label right-aligned with a trailing colon, one field per row, one full-width column | labels left-aligned without colons, a deliberate two-up row (Year \| Genre), a `Series` sub-group behind its own divider and header |
| Action hierarchy | four visually identical grey buttons | filled accent **Save Tags**, two outlined red destructive actions, a neutral Cancel pushed to the right edge |
| Progress | a bare grey trough floating at the right of the action row | its own full-width line above the buttons, accent fill, with a `2/3 67%` counter |
| Navigation | "Tools" heading, six raised buttons, active tool shown by **disabling** it (greyed, unreachable by keyboard) | a `TOOLS` rail with flat rows, active tool marked by the ttk `selected` state (soft accent fill, left-aligned) and still keyboard-reachable |
| Context | none — nothing on screen names the active tool | a header strip with the tool's title and one-line description |
| Log | plain proportional text box | elevated surface, `Consolas` mono, themed scrollbar |

**Against the plan's nine approval criteria** (§10, assessed — the decision is the
maintainer's):

1. Hierarchy/layout redesign rather than a recolour — **yes**; the composition, grouping, label alignment, action hierarchy and progress placement all changed, not just the palette.
2. Launcher and editor feel like one application — **yes**; identical surface ladder, one type scale, one accent, one border token.
3. Text / selection / disabled / focus readable — **yes**; contrast is asserted numerically in `test_windows_colors_are_valid_and_readable` (≥7:1 primary, ≥4.5:1 secondary, ≥3:1 disabled and focus, on all seven surfaces), and the active-run image shows the disabled state legible but clearly inactive.
4. No clipping, overlap, truncated action or lost status at either scaling — **yes**, measured: 0 px clipped on Save / Clear All Tags / Remove Series Numbering / Cancel / progress bar / progress label / Log at all three sizes and both scalings.
5. Scrolling deliberate and discoverable — **yes**; the form is a scroll region with a visible themed scrollbar at every size, and the action bar and Log sit outside it.
6. Shared Metadata visibly distinct — **yes**; own fill, own accent border, own header colour, own caption.
7. Summary/Details has a visual relationship without pretending the behaviour exists — **partly, and one honest limitation**: the tab pairing, the selected/unselected tab states and the Summary treatment are all visible, but a `ttk.Notebook` shows one pane at a time, so the **Details pane's content is not visible in either specimen image**. Its treatment is the same mono-on-elevated log surface visible in images 4 and 9. If the maintainer wants both panes side by side, that is a `CHANGES REQUESTED` item for the fixture.
8. The five unconverted panels have not silently adopted prototype styles — **yes**: 0 `ACT.*` styles in each of the five in the live app, 19 in the editor.
9. No fragile per-machine hacks — **yes**; no registry edit, no image assets, no machine-specific workaround. The one environment nicety is the neutral `USERPROFILE`, used only to keep a username out of the pictures.

**Two further observations, neither fixed:**
- In the active-run images the launcher status bar still reads `M4B Metadata — ready.`
  while a run is in progress. That is pre-existing v0.5.1 behaviour (the shell's status is
  set on tool switch, never by a tool's run) and is unchanged by this drop, but with a
  prominent status bar in the new shell it is more noticeable than it used to be.
- The window title bar is drawn by Windows in the system's light theme above a dark app.
  Tk cannot set the immersive dark title bar without a Win32 `DwmSetWindowAttribute` call.
  Out of scope here; noted for Plan 9.

#### Geometry review — measured at both scalings

Same method as Phase 4: on the real mapped window, "reachable" = mapped **and** the box
lies inside the content host; "clipped" is the real overflow in pixels.

| | 1024×720 | 920×600 | Maximized |
|---|---|---|---|
| Content host @100% | 825×577 | 721×457 | 1721×866 |
| Content host @125% | 825×577 | 721×457 | **1337×650** |
| Editor form viewport @100% | 326 px | 206 px | 615 px |
| Editor form viewport @125% | 326 px | 206 px | **399 px** |
| Form required height (both) | 1083 px | 1083 px | 1083 px |
| Editor Save / Clear / Remove / Cancel / progress / Log | 0 px clipped, both scalings | 0 px clipped, both scalings | 0 px clipped, both scalings |
| Six nav labels readable | yes | yes | yes |
| Status bar + log action visible | yes | yes | yes |
| **M4B Converter primary action** | reachable | **clipped 19 px, both scalings** | reachable |
| **M4B Converter Log** | reachable | **clipped 108 px bottom + 75 px right, both scalings** | reachable |

- `sidebar_width` is 180; the widest nav row needs 115 px against a 160 px interior — 45 px
  of slack, unchanged at 125% because the app is DPI-unaware.
- **The clipping does not become materially worse at 125% — it is byte-identical.** At
  1024×720 and 920×600 every measurement matches the 100% pass exactly, because those are
  logical sizes and the app never sees the DPI change. The only 125% difference is
  maximized, where the logical window is 1536×793 instead of 1920×1009, so the editor's
  form viewport falls 615 → 399 px and simply scrolls more.
- The editor's form is a scroll region at all three sizes and both scalings (form wants
  1083 px, never gets it). Permitted by §7.3; stated so the images are read correctly.

#### Phase 5 automated results (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **17 passed, 0 skipped**, in 0.15s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 11 passed, 1 warning in 2.45s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_ui.py` | PASS — 12 passed in 0.54s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_prototype_regression.py` | PASS — 12 passed, 1 warning in 1.94s |
| `.venv\Scripts\python.exe -m pytest -q -rs` (full suite) | PASS — **94 passed, 3 skipped**, 1 warning in 5.86s |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 94 passed / 3 skipped in 5.80s; deps `==`-pinned; docs de-templated |
| `.venv\Scripts\python.exe -m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | clean — exit 0 |

Identical to the Phase 4 baseline, which is the expected result for a phase that changes
no code. The 1 warning is the pre-existing pydub `audioop` DeprecationWarning; the 3 skips
are the three `JACK_RYAN_M4B_FOLDER`-gated tests in `test_jack_ryan_final_product.py`,
named by `-rs`.

**The Tk skip transient did NOT recur in Phase 5.** All 17 `test_ui_theme.py` tests
executed on every run, both in the focused suite and inside the full suite (94 = 82 + 12,
with the theme module's 17 present). The guard was not touched, per the plan; the blind
spot recorded in *Phase 4 limitations* item 8 remains open and unowned by Plan 1.

### Phase 5 limitations and open items

1. ~~**THE GATE ITSELF IS OPEN.**~~ **RESOLVED 2026-08-02 — the maintainer replied
   `APPROVED`.** Recorded in *Phase 6* above. (Nothing was merged on approval; approval is
   of the design contract, not a release.)
2. **The application is DPI-unaware** (see above). At 125% Windows bitmap-scales the whole
   window, so text is soft rather than re-rendered at 120 DPI. Nothing clips as a result,
   and nothing was changed — making the app DPI-aware is a production change and needs a
   maintainer decision. This is the single most consequential finding of Phase 5.
3. **The 125% pass ran on the secondary 1920×1080 display**, which was the one set to 125%.
   Argued equivalent above (an unaware app is bitmap-scaled identically on a 125%
   primary). **RESOLVED 2026-08-02 — the maintainer accepted those images as valid evidence
   and required no primary-monitor reshoot** (approval decision 2).
4. **`MIN_SIZE` / `DEFAULT_GEOMETRY`** — **DECIDED 2026-08-02: option 1, change nothing**
   (approval decisions 4 and 5); the converter clipping is deferred to that panel's Plan 9
   conversion. The reasoning that was put to the maintainer is kept below, unchanged.

   The M4B Converter's primary action and Log remain clipped at the 920×600 minimum
   (19 px / 108 px + 75 px), the same at both scalings. The Phase 5 recommendation was
   **option 1: change nothing now** —
   the clipping is in an *unconverted* panel that Plan 9 will rebuild, the converted editor
   clips nothing at any size, raising `MIN_SIZE` would be a theme-contract change made for
   a panel this drop is forbidden to touch, and `test_windows_metrics_are_usable` /
   `test_apply_theme_on_current_platform` both pin the current values. If the maintainer
   would rather close it now, option 2 (raise only `MIN_SIZE` to about 920×740) removes the
   clipping without changing the launch size — but it belongs in Plan 9 with the panel
   rebuild, not here.
5. **The Details pane's content is not visible in the specimen images** (a notebook shows
   one pane at a time). Limitation of the single-image slot, not of the design.
6. **Live macOS remains deferred and is NOT claimed as passed.** No Mac was available. The
   exact five-step smoke test is preserved verbatim in *Phase 4 limitations* item 1 and
   carries forward unchanged. It is not a blocker for this Windows visual gate: the
   non-Windows code paths are byte-identical to `master` and are covered by
   `test_apply_theme_on_current_platform` (aqua arm), `test_classic_branch_other_platform`,
   `test_non_windows_theme_builds_the_unconverted_layout` and
   `test_an_aqua_bundle_builds_the_historical_layout`. That is evidence, not a live pass.
7. **`ttk.Combobox` popdown still unthemed** (Plan 9), and the **Windows title bar stays
   light** over the dark app (needs a Win32 DWM call; Plan 9).
8. **Pre-existing and untouched:** the launcher status bar does not follow a tool's run;
   an unreadable input is copied before its tag write fails, leaving an untagged copy; and
   Open Issue #2 (`kokoro_synth` CLI-only cp1252 `UnicodeEncodeError`).
9. **No production source changed in Phase 5.**
   `git diff --name-only 9d4f58c..HEAD -- scripts/ files/tests/` is empty; `version.py` is
   still `0.5.1`; `requirements.txt` and both setup launchers are untouched.

### Phase 4 — regression hardening (2026-08-01, HOME-PC)

**Outcome: no production-source change.** The plan's source-change rule is "fix only
a genuine regression caused by Phases 1–3". The audit and the functional matrix found
none, so nothing under `scripts/` was edited. One file was added:
`files/tests/test_prototype_regression.py` (12 tests).

#### Whole-diff audit (`1da1e547..d8d0b1b`, the complete Phase 1–3 diff)

Nine files changed overall: three sources, four test files, the drop plan and this
handoff. Findings, each with the evidence rather than an assertion:

| Audit item | Finding | Evidence |
|---|---|---|
| Generic ttk style leakage | **None.** Every `style.configure` / `style.map` / `style.layout` on an added line names an `ACT.*` style or a loop variable bound only to `ACT.*` names | grep of all 1338 added source lines |
| `ACT.*` reaching the five unconverted panels | **None.** 0 namespaced styles in each of the five; 19 in the converted editor | live app walk + `test_launcher_smoke` + the new whole-app snapshot test |
| Missing explicit layouts | **None.** Every style in `theme["styles"]`, plus the four sub-styles, has a layout, and every natively-drawn class roots in a cloned `ACT.` element | `test_windows_styles_are_namespaced_and_registered` |
| Global option-database changes | **None.** `option_add` / `option_clear` / `tk_setPalette` appear nowhere in `scripts/` | repo-wide grep |
| Panel-wide hardcoded colours/fonts/metrics | **None.** All 34 hex literals live in `_WINDOWS_COLORS` in `ui_theme.py`; `launcher.py` and the editor contain **zero** | per-file grep of added lines |
| Windows leaking into aqua / Linux-other | **None.** `_apply_darwin`, `_apply_classic`, `_classic_font_family`, `_resolve_color`, `_blend`, `_is_dark`, `_mac_font_family`, `enable_mousewheel` and all five `ProgressIndicator` methods are **byte-identical** to master; `apply_theme` gained only the `win32` arm | AST-level definition compare, master vs HEAD |
| Metadata semantics | **Unchanged.** `shared/metadata.py` untouched; all 46 editor definitions from `add_files` down are byte-identical | `git diff --name-only` + AST compare |
| Output paths / collision / copy-only / original protection | **Unchanged.** `shared/paths.py` untouched; `_save_worker` and `_remove_numbering_worker` byte-identical | as above, plus the new worker tests and the live matrix |
| Settings persistence | **Unchanged.** `shared/settings.py` untouched; the editor still writes only `m4b_metadata.input_dir` and `m4b_metadata.cover_dir`; the launcher only `last_tool` | AST compare + `test_no_new_persisted_settings_arrived_with_the_new_presentation` |
| Workers / queues / cancellation / threading / audio | **Unchanged.** Both workers, `_start_job`, `cancel`, `disable_inputs`, `_pump_queue`, `_finish_idle` byte-identical; `shared/cancellation.py` untouched | AST compare |
| Launcher lifecycle / ordering / build-once / saved selection / error panels / status / log folder | **Unchanged.** `TOOLS`, `select_tool`, `_load_tool_into`, `_available_tools`, `_module_exists`, `__init__`, `_on_close`, `_open_logs`, `_apply_default_geometry`, `_build_ui_classic`, `_build_ui_darwin` all byte-identical. Only `_build_ui` (routing), `_highlight_selection` (new `windows` arm, aqua arm and classic tail identical) and `_show_load_error` (the old body moved verbatim into an `else:`) changed | AST + statement-level compare |
| Runtime access to the developer-only fixture | **None.** Not in `TOOLS`, not under `scripts/`, not pytest-collectable | `test_manual_fixture_is_developer_only_and_unreachable_at_runtime` |
| `requirements.txt` / `version.py` / setup launchers / unrelated tools | **Untouched.** `git diff --name-only 1da1e547..HEAD` over all of them returns empty; `version.py` still `VERSION = "0.5.1"` | direct check |

**The load-bearing audit result:** at the definition level, `mp3_tools/m4b_metadata_editor.py`
has **46 byte-identical definitions** and exactly **three changed** (`__init__`,
`_build_ui`, `build_ui`) plus three added (`_build_ui_classic`, `_build_ui_windows`,
`_wrap_with`). `_build_ui_classic` is statement-for-statement master's `_build_ui`
minus its two trailing state syncs, which moved to the dispatcher and now run for
**both** forks. That is what makes "no metadata, output, threading or cancellation
change" a proof rather than a claim.

**One correction to the Phase 3 record.** Phase 3 said the two forks create "exactly
the same widgets and attributes". Measured: they create the same widget *set* and the
same widget *types* for every attribute either fork's shared code touches, but the
Windows fork additionally names one label that the classic fork leaves anonymous —
`self.lbl_chap_hint`. Nothing reads it, `disable_inputs` does not touch it, and no
contract depends on it, so it is not a defect; the earlier wording was just slightly
too strong.

#### Tests added (`files/tests/test_prototype_regression.py`, 12)

Only what Phases 1–3 did not already cover, and behaviour over appearance:

| Test | What it pins down |
|---|---|
| `test_save_worker_writes_only_copies_and_never_the_originals` | every write lands in the output folder, every original is byte-identical, and the copies really are copies |
| `test_save_worker_never_overwrites_an_input_when_output_is_the_input_folder` | the `avoid_input_overwrite` guard, i.e. output folder == input folder is safe |
| `test_remove_numbering_worker_is_copy_only_too` | the same contract for the second worker |
| `test_cancel_before_the_first_file_writes_nothing` | a pre-set cancel writes nothing and reports `(0, 0, cancelled)` |
| `test_cancel_mid_run_finishes_the_current_file_and_stops_the_rest` | the documented semantics: the in-flight file completes, later files stop, only whole copies exist |
| `test_cancellation_uses_the_shared_primitive` | cancellation still travels through `shared.cancellation`, not a local flag |
| `test_both_build_forks_expose_the_same_surface` | all 16 `disable_inputs` targets exist with the same types on both forks, and busy → idle behaves identically |
| `test_an_aqua_bundle_builds_the_historical_layout` | macOS takes the unconverted fork — the check is on `mode`, not on `sys.platform` |
| `test_building_the_whole_app_leaves_the_generic_styles_untouched` | 16 generic styles byte-identical across theme + shell + **all six panels** building (Phase 1 covered theme only, Phase 3 one panel) |
| `test_the_runtime_editor_contains_no_plan_3_6_or_8_controls` | no notebook, no Summary/Details/ETA/Retry/Pause/Resume/filter/per-book wording, exactly the two historical Text areas, and no button without a command |
| `test_shared_metadata_grouping_adds_no_precedence_or_disabling` | a populated shared field disables nothing and overrides nothing |
| `test_no_new_persisted_settings_arrived_with_the_new_presentation` | the panel still writes only its two historical dialog-location keys |

The first six need no display (they call the unbound workers on a stub, like the
existing shared-value tests); the Windows-only ones skip elsewhere.

#### Windows manual functional matrix (Section 11)

**Fixtures.** Generated rather than copied: every real file in `files/test-files/` is
0.5–3 GB and the matrix copies each input again, so three ~3.4 KB M4Bs were built with
ffmpeg — real AAC audio, three real chapters, real tags (shared artist / album / year /
genre / comment, differing titles, track numbers 1–3) — plus one deliberately invalid
`BROKEN.m4b`. They travel the same mutagen/ffmpeg paths at 1/50000th the size, and
nothing irreplaceable was ever in the working directory.

**Location and disposability.** Everything lived in the session scratchpad
(`…\Temp\claude\…\scratchpad\p4\work\`), **outside the repository**: `src/` (sources),
`bulk2/` (400 copies for the cancel run) and eight `out-*/` folders. **Nothing was
committed** — `git status` after the run showed only the new test file and the
pre-existing untracked `config-template.toml`. `settings.json` was snapshotted before
and byte-restored after every run (`settings_restored: true` both times). No stray
`Downloads/M4B-Metadata-N` folder was created.

**Method.** The real `LauncherApp` built the real converted editor; every check calls
the production callback the button is wired to. `filedialog` and `messagebox` were
scripted so a "cancelled" dialog returns exactly what Tk returns when the user presses
Cancel. Nothing in the editor, the workers, metadata or the output logic was patched.

| # | Check | Result |
|---|---|---|
| 1 | Dialog safety — open and cancel Add M4B / Add Folder / cover / output | **PASS** — all four opened with their real titles; files, listbox, cover, output folder and `settings.json` bytes all identical before and after; panel still usable |
| 2 | File list — import one, import many, order, selection, Remove Selected, Clear List, re-import | **PASS** — 1 → 3 files, a re-added duplicate is not duplicated, multi-selection `(0, 2)` removed both, Clear List emptied everything and reset the notice, re-import restored all three in import order |
| 3 | Shared metadata + chapter pages | **PASS** — batch notice named the shared fields (Author/Artist, Album, Year, Genre, Comment); Title varies → left blank; pager stepped 1→2→3 and back with the label and hint following the selected file; `btn_chap_prev` correctly disabled on page 1; **all 8 fields `normal`** — nothing disabled by the grouping; single-file load re-prefilled from the file itself |
| 4 | Safe Save on disposable copies | **PASS** — 3 outputs in the redirected folder, the edited Comment applied, every unrelated tag (title/artist/album/year/genre/series/series_part) preserved, all 3 chapters intact per file, **all source SHA-256 unchanged**, no output path equals an input path, returned to idle |
| 5 | Clear All Tags — both confirmation choices | **PASS** — declining did nothing (not busy, output folder never created, sources unchanged); accepting produced 3 copies with title/artist/album/genre/year/series/cover **gone**, chapters kept, and the one field the user had edited re-applied (the documented `only_edited` behaviour); sources unchanged |
| 6 | Remove Series Numbering — both confirmation choices | **PASS** — declining did nothing; accepting removed `series` / `series_part` / `track` on the copies while title, artist and album survived and all 3 chapters were kept; sources unchanged |
| 7 | Cancel during work | **PASS** — 400 disposable inputs, no artificial delay added. Cancel pressed 400 ms in while busy with 8 files done: the button was enabled, went disabled on press, the event was set, the log recorded "Cancelling… will stop after the current file.", the in-flight file (#9) finished, files 10–400 stopped, the run reported "Cancelled. 9 saved, 0 failed.", the UI returned to idle with **every** control restored, all 400 inputs byte-identical, every one of the 9 outputs a complete copy (no zero-byte or truncated file), and the next run after the cancel completed normally with the event cleared |
| 8 | Controlled error path | **PASS** — the invalid fixture was reported at load ("Could not read tags"), the run logged `[2/3] ✗ … : not a MP4 file`, finished "Done. 2 saved, 1 failed.", raised the existing "Completed with errors" warning, kept the UI responsive, left the sources unchanged, and a subsequent safe save completed normally. Note (pre-existing, not introduced here): the invalid file *is* copied to the output folder before the tag write fails, so an untagged copy is left behind — that is the existing copy-then-write order, unchanged by this drop |
| 9 | Launcher lifecycle after all of the above | **PASS** — six tools in order, **zero** error panels, 6 containers with identical object identity across three full sweeps, the editor object and its typed state preserved, the `selected` flag on exactly the active row, no row disabled, status correct, log-folder action worked |

#### Resize, scrolling and keyboard (HOME-PC, 1920×1080 @ 100%)

Measured on the real mapped window — "reachable" means mapped **and** the widget's box
lies inside the content host, not an eyeball.

| | 1024×720 | 920×600 | Maximized |
|---|---|---|---|
| Window | 1024×720 | 920×600 | 1920×1009 |
| Content host | 825×577 | 721×457 | 1721×866 |
| Editor scroll viewport | 326 px | 206 px | 615 px |
| Form requested height | 1083 px | 1083 px | 1083 px |
| Save / Clear All Tags / Remove Numbering / Cancel | reachable, 0 px clipped | reachable, 0 px clipped | reachable, 0 px clipped |
| Progress bar + counter | reachable, 0 px clipped | reachable, 0 px clipped | reachable, 0 px clipped |
| Log | reachable, 0 px clipped | reachable, 0 px clipped | reachable, 0 px clipped |
| Status bar + log button visible | yes | yes | yes |
| Six nav rows visible | yes | yes | yes |
| Form region scrolls | yes | yes | yes |
| Log scrolls independently of the form | yes | yes | yes |

- **Nav rows at `sidebar_width = 180`:** widest 115 px (TTS Audiobook) against a 160 px
  interior — 45 px of slack for 125%. All six readable at all three sizes.
- **Mouse-wheel scoping:** unchanged — one canvas in the editor, `<Enter>`/`<Leave>`
  bound on the hover wrap, and the Leave side still carries the `%d` crossing-detail
  substitution that keeps the binding alive over child widgets.
- **Keyboard:** a **31-stop closed loop with no trap** — rail (6) → file actions → list
  → the seven shared fields → cover Browse/Clear → series + auto-number → chapter text
  → output → Save / Clear All Tags / Remove Series Numbering → Open log folder. The
  disabled Cancel and the disabled pager arrows are correctly skipped.
- **Selection / hover / pressed / disabled / focus:** unchanged from Phases 2–3.
- **Five classic panels:** still unconverted (0 `ACT.*` styles each, in the live app).
- **ttk theme:** still `vista`.
- **Correction to the Phase 3 record:** Phase 3 said the whole form fits without
  scrolling when maximized. Re-measured, it does not — the form wants 1083 px against a
  615 px viewport even maximized, so the editor's form is a scroll region at **all
  three** sizes. That is permitted by the plan (§7.3 requires deliberate scrolling, not
  zero scrolling) and the action bar and Log stay outside it, but the earlier claim was
  wrong and is corrected here.

#### Phase 4 automated results (repo venv, Python 3.12.10)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_ui.py` | PASS — 12 passed in 0.45s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — 17 passed, **0 skipped**, in 0.13s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 11 passed, 1 warning in 2.35s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_prototype_regression.py` | PASS — **12 passed**, 1 warning in 1.74s (new) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_metadata_smoke.py` | PASS — 4 passed in 0.01s |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **94 passed, 3 skipped**, 1 warning in 5.33s |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 94 passed / 3 skipped in 5.03s; deps `==`-pinned; docs de-templated |
| `.venv\Scripts\python.exe -m compileall -q scripts files/tests` | PASS — exit 0 |
| `git diff --check` | clean — exit 0 |

**Baseline change explained:** 82 → 94 passed is exactly the 12 new tests in
`test_prototype_regression.py`. Nothing else moved. The 1 warning is still the
pre-existing pydub `audioop` DeprecationWarning; the 3 skips are still the three
`JACK_RYAN_M4B_FOLDER`-gated tests in `test_jack_ryan_final_product.py`, confirmed by
name with `pytest -rs`.

**The Tk skip transient DID recur — once — and is reported rather than smoothed over.**
On the post-handoff verification pass, one full-suite run reported **77 passed, 20
skipped**: 17 fewer passes and 17 more skips than the baseline. `scripts/verify.py`,
run seconds later in the same command, reported `94 passed, 3 skipped` and **PASS**.

- **Which module:** `test_ui_theme.py`. It is the only module with exactly 17 tests,
  all 17 hang off its module-scoped `tk_root` fixture, and 94 − 77 = 20 − 3 = 17. The
  three baseline skips are the `JACK_RYAN_M4B_FOLDER`-gated tests, confirmed by name.
- **The reason string was not captured.** The bad run was not under `-rs`, and the
  condition would not reproduce afterwards. The only path that can turn those 17 into
  skips is the fixture's `except tk.TclError -> pytest.skip("Tk cannot open a display
  here: …")`, so the underlying event is a transient failure of `tk.Tk()` on this
  machine, most likely under the load of several pytest processes creating and
  destroying Tk roots back to back — which is exactly what preceded it both times.
- **Retried, hard.** 22 further full-suite runs, including 16 that deliberately
  re-created the trigger (four or five focused Tk suites immediately before the full
  suite): **94 passed, 3 skipped every single time, 0 deviations.** `test_ui_theme.py`
  run explicitly on its own gave **17 passed, 0 skipped** on every attempt.
- **Not accepted as equivalent.** The recorded Phase 4 result is the 94/3 baseline; the
  77/20 run is logged as an environment transient, not as coverage.
- **The guard was not rewritten**, per the plan — it is not a reproducible defect, and
  a narrow fix would need its own justification. What it does mean is worth stating
  plainly: when this fires, the theme suite silently vanishes from the run and
  `verify.py` still says PASS, because the gate cannot tell "17 tests skipped" from
  "17 tests never existed". That is a real, if rare, blind spot in the gate. It predates
  this drop and belongs to whoever hardens `verify.py`, not to Plan 1.

### Phase 4 limitations and open items

1. **Live macOS is still deferred — the exact smoke test still required.** No Mac was
   available this session, so nothing macOS is claimed as passed. What Plan 1 still
   needs on HOME-MacOS, precisely: (a) launch through
   `Setup_and_Run-audiobook-creation-tool.command` and confirm the Finder/aqua shell is
   visually unchanged from v0.5.1 — source-list sidebar, toolbar strip, content card,
   accent selection row; (b) select all six tools and confirm each opens with no error
   panel and no dark chrome; (c) open the M4B Metadata Editor and confirm it renders the
   **historical** layout (one flat stack of labelframes, native aqua controls) and **not**
   the card layout; (d) confirm the editor's file list, chapter pager, Save/Cancel and
   Log behave as they did on v0.5.1; (e) confirm `ttk` is still `aqua`. Automated
   coverage exists and is reported separately: `test_apply_theme_on_current_platform`
   (aqua arm), `test_classic_branch_other_platform`,
   `test_non_windows_theme_builds_the_unconverted_layout` and the new
   `test_an_aqua_bundle_builds_the_historical_layout` — plus the audit fact that
   `_apply_darwin` and `_build_ui_darwin` are byte-identical to master. That is
   evidence, **not** a live pass. Carried into Phase 5.
2. **The vertical half of the Phase 2 geometry regression is still open, and is
   deliberately not fixed here.** `MIN_SIZE` and `DEFAULT_GEOMETRY` are unchanged. The
   M4B Converter's `Convert M4Bs → MP3s` row and Log are still clipped at the 920×600
   minimum (~19 px and ~110 px). Phase 5 decision, per the maintainer.
3. **The editor's form viewport is shallow at 920×600** (206 px) and, corrected above,
   the form scrolls at every size including maximized. Not fixed in Phase 4 — that would
   be visual redesign, which this phase is forbidden.
4. **No 125% scaling pass yet.** Everything above is 100%. The true 125% pass is Phase 5.
5. **`ttk.Combobox` popdown still unthemed** (carried from Phases 1–3). Plan 9 item.
6. **The matrix used generated fixtures, not the real library.** Deliberate — see
   *Fixtures* above. It means the matrix did not exercise a multi-hour, multi-GB file or
   an unusual real-world tagger namespace. The real-library behaviour of those code
   paths is unchanged by this drop (they are byte-identical to master), so this is a
   scope note rather than a gap, but it is not the same as a full-size run.
7. **One pre-existing behaviour surfaced by check 8, not introduced here:** an
   unreadable input is copied into the output folder before the tag write fails, leaving
   an untagged copy behind. That is master's copy-then-write order. Recorded, not
   changed — Phase 4 may only fix regressions caused by Phases 1–3.
8. **The Tk skip transient recurred once** (see the automated-results section above for
   the full account). Two occurrences now — Phase 3 and Phase 4 — both 17 extra skips,
   both unreproducible afterwards (22 clean retries this time), both leaving
   `verify.py` reporting PASS. The guard was deliberately not rewritten. The residual
   risk is that the gate cannot distinguish a skipped suite from an absent one.
9. Pre-existing Open Issue #2 (`kokoro_synth` CLI-only cp1252 `UnicodeEncodeError`)
   remains open and out of scope.

### Phase 3 — M4B Metadata Editor + visual specimens (2026-07-31, HOME-PC)

**What it is.** `mp3_tools/m4b_metadata_editor.py` now forks its presentation:

| Mode | Build path | Result |
|---|---|---|
| `windows` | `_build_ui_windows()` | the new card layout, built entirely from `ACT.*` |
| `aqua` / `classic` | `_build_ui_classic()` | the pre-v0.6.0 layout, byte-for-byte |

Both forks create **exactly the same widgets and attributes**, so every method below
the builders — callbacks, workers, the queue pump, `disable_inputs`, the Cancel path,
`_collect_tags`, `_shared_tags` — is shared and has no idea which one drew the screen.
Nothing about metadata reading/writing, field precedence, file order, output paths,
filenames, tag namespaces, chapter logic, thread boundaries or cancellation timing was
touched.

**Entry point.** `build_ui(parent)` is unchanged. It gained an optional
`theme=None` second parameter: when omitted (which is what the launcher does) the panel
resolves the platform bundle itself via `ui_theme.apply_theme`, which is idempotent by
contract. The parameter exists so the developer-only fixture — and, later, the launcher
— can hand in a bundle already applied instead of re-resolving it. Every existing caller
keeps working untouched.

**The new section/card hierarchy** (row 0 scrolls; rows 1 and 2 never do):

```
row 0  scrollable canvas  ── Audiobook Files      (ACT.TLabelframe)
                          ── Shared Metadata      (ACT.Shared.TLabelframe)  <- distinct
                          ── Chapter Titles (optional)  (ACT.TLabelframe)
                          ── Output                     (ACT.TLabelframe)
row 1  action bar   progress line, then Save / Clear All Tags / Remove Numbering / Cancel
row 2  Log          (ACT.TLabelframe + ACT-styled Text)
```

**Visual mapping of every pre-existing control** (nothing was dropped, hidden or
renamed):

| Control | New home | Style |
|---|---|---|
| Open M4B File(s) / Open Folder… / Remove Selected / Clear List | Audiobook Files, toolbar row | `button` |
| File list (`listbox`) | Audiobook Files | `style_tk_widget(…, "list")` + `vscrollbar` |
| `mode_var` notice (shared/"(varies)") | Shared Metadata caption block | `shared_secondary` |
| Title, Author/Artist, Album, Year, Genre, Comment | Shared Metadata grid (Year \| Genre share a row) | `shared_label` + `entry` |
| Cover image entry + Browse… + Clear | Shared Metadata grid, last row | `entry`, `button` |
| Series Name, Series Part, Auto-number toggle | Shared Metadata → Series sub-group | `shared_label`, `entry`, `shared_checkbutton` |
| `series_readback_var`, `autonumber_hint_var` | Shared Metadata, under the sub-group | `shared_secondary` |
| Chapter pager ◀ / ▶ / page label / hint / text | Chapter Titles card | `button`, `label`, `secondary_label`, `style_tk_widget(…, "text")` |
| Output folder entry + Browse… + Open | Output card | `entry`, `button` |
| Progress bar + counter | Action bar, own line, natural width, left-aligned | `progressbar`, `status_label` |
| Save Tags | Action bar | `primary_button` |
| Clear All Tags / Remove Series Numbering | Action bar | `danger_button` |
| Cancel | Action bar, right-aligned | `button` |
| Log | Row 2 card | `style_tk_widget(…, "log")` + `vscrollbar` |

**Shared Metadata, and what it deliberately is not.** Every metadata field in this
editor is *already* batch-wide — a non-blank value is written to every loaded file, and
the existing shared-value detection reports which of them matched across the batch and
which "(varies)". The card is a visual statement of that behaviour, using the Phase 1
`ACT.Shared.TLabelframe` surface (muted accent fill, accent border, accent header) so it
reads as the universal section at a glance. It adds **nothing**: no populated-global-
overrides-per-book precedence, no per-book field disabling, no multi-book workspace, no
one-page-per-M4B workflow — those are Plan 6 / Plan 8. A test asserts no field in the
card is disabled by the grouping, and `test_m4b_metadata_editor_shared.py` (7 tests,
untouched) still owns the shared/"(varies)" semantics.

**Summary/Details, and what it deliberately is not.** It is **not** in the runtime
editor — putting a Summary/Details control there would be a non-functional control in a
user-facing panel, which the plan forbids. It lives in the developer-only fixture as a
component sheet: an `ACT.TNotebook` with Summary and Details tabs, plus the primary /
secondary / danger / ghost / disabled action swatches. The sheet labels itself with
`SPECIMEN_NOTE`, which states in so many words that there is no filtering, no separate
log buffers, no technical-log routing, no job snapshot, no ETA, no Retry Failed and no
Pause/Resume — all Plan 3. A test asserts that text is present and that no button on the
sheet has a command bound to it.

**The developer-only fixture — `files/tests/manual_windows_ui_prototype.py`.** Needed,
because the Phase 5 matrix requires a populated editor and a mid-run editor, and a real
batch finishes far too fast to photograph while a populated batch would otherwise need
real audiobooks on the screenshot machine. Runtime isolation is enforced four ways and
asserted by `test_manual_fixture_is_developer_only_and_unreachable_at_runtime`:

1. pytest cannot collect it — the filename is not `test_*` and it declares no test
   functions (the test greps the source to prove it).
2. The launcher cannot reach it — it is in no `launcher.TOOLS` entry.
3. It is not in the shipped tree — it lives under `files/`, and the test asserts no copy
   exists anywhere under `scripts/`.
4. It patches nothing. Every state is reached by calling the editor's own public methods
   (`_populate` seeds `files`/`_tag_cache`/`_chap_counts` then calls the real
   `_refresh_mode`; `_make_busy` calls the real `disable_inputs`/`progress.update`). A
   test asserts none of its canned paths exist on disk, so it is fully offline.

States: `empty`, `populated`, `active-run`, `specimen`.

**`sidebar_width` 232 → 180 (maintainer-approved).** Measured content-host size:

| Window | Classic (master) | Phase 2 (rail 232) | Phase 3 (rail 180) | Recovered |
|---|---|---|---|---|
| 920×600 (minimum) | 796×561 | 669×457 | **721×457** | +52 w |
| 1024×720 (default) | 900×673 | 773×577 | **825×577** | +52 w |
| Maximized 1920×1009 | — | — | 1721×866 | +52 w |

Navigation is still comfortable: the widest row ("TTS Audiobook") wants 115px against
160px of rail interior — 45px of slack for 125% scaling. A test pins the token at 180
and a launcher test asserts every row still fits.

**Is the M4B Converter's primary action and Log reachable again? Partly — honestly:**

| Window | `Convert M4Bs → MP3s` row | Log box |
|---|---|---|
| 1024×720 (default) | **YES** — mapped, fully inside the host | **YES** — mapped, fully inside the host |
| 920×600 (minimum) | **NO** — unmapped, ~19px past the host bottom | **NO** — unmapped, ~110px past |

The rail change gave back **width**, and width was the whole of the new-in-Phase-2
horizontal overflow — so at the default size that panel is fully usable again. The
remaining clip at the minimum size is **vertical**, caused by the launcher's header
strip (~96px), and neither lever for that (`MIN_SIZE` / `DEFAULT_GEOMETRY`) was changed,
per the maintainer's decision. Recorded, not fixed.

**Panel fit after the change** (requested size minus host; positive = overflow):

| Panel | 1024×720 | 920×600 |
|---|---|---|
| TTS Audiobook | −204 w / −50 h | −100 w / +70 h |
| M4B Converter | −57 w / +102 h | +47 w / +222 h |
| MP3 Tool | −227 w / +278 h | −123 w / +398 h |
| M4B Maker | +23 w / +187 h | +127 w / +307 h |
| Cover Image | −140 w / +21 h | −36 w / +141 h |
| **M4B Metadata (converted)** | **−165 w / −61 h** | −61 w / +59 h |

The converted editor is now the best-fitting panel of the six: it needs no scrolling at
all at the default size, where before Phase 3 it overflowed by 77px horizontally.

**Combobox popdown: not needed, limitation carried forward.** The editor owns no
combobox, so Phase 3 never had to style the popdown list. It remains unthemed and
remains a Plan 9 problem; no `option_add()` was used anywhere (the diff scan is clean).

**Phase 3 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_ui.py` | PASS — **12 passed** in 0.45s (new file) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **17 passed** in 0.13s (was 16) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — **11 passed**, 1 warning in 2.23s (was 10) |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **82 passed, 3 skipped**, 1 warning in 4.91s (was 68/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 82 passed / 3 skipped in 4.86s; deps `==`-pinned; docs de-templated |
| `git diff --check` | clean (only the benign LF→CRLF notices) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3 skips
are still the pre-existing `JACK_RYAN_M4B_FOLDER`-gated tests. Neither is new.

**What the new tests prove.** `test_m4b_metadata_editor_ui.py` (12): the panel still
builds and exposes all 24 required widgets and 24 required callbacks, one Tk var per
field correctly bound to its entry, the idle starting state, the busy→idle transition
across every guarded widget, shared-value prefill driven through the real widget tree,
and a non-Windows theme building the historical layout with zero namespaced styles. On
Windows: only `ACT.*` styles are used and no ttk widget was left generic; the generic
styles are byte-identical before and after building it; Listbox/Text/Canvas go through
`style_tk_widget` rather than local literals; the scroll region is still one canvas with
its scoped `%d`-substituted wheel binding; the Shared Metadata surface is unique,
contains every batch field and disables none of them; and Save/Cancel/progress/Log are
outside the scroll region while the form, list and chapter pages are inside it. Plus the
two fixture-isolation tests. `test_launcher_smoke.py` gained the narrowed-rail test and
its isolation test now distinguishes the converted panel (>40 ACT-styled widgets, none
generic) from the five unconverted ones (zero ACT styles between them).
`test_ui_theme.py` gained the Shared Metadata surface-family test and the pinned rail
width.

**Draft visual review (real app, real Tk, HOME-PC, 1920×1080 @ 100%).** Draft only —
scratchpad images, deliberately **not** committed; the ten-image 100%/125% matrix is
Phase 5.

| Check | Result |
|---|---|
| Narrower rail still shows all six tool names clearly | PASS — widest row 115px in a 160px interior |
| Nav selection / hover / pressed / disabled / keyboard focus | PASS — unchanged from Phase 2, verified again after narrowing |
| Editor is a hierarchy redesign, not a recolor | PASS — four titled cards, a distinct shared surface, an action bar and a log, where the old panel was one flat stack of labelframes |
| Shared Metadata visually distinct and recognizable | PASS — accent-blue border and header on the muted fill, clearly different from the neutral cards above and below it |
| Every existing control reachable (layout or deliberate scroll) | PASS — all present; the form scrolls, the actions and log do not |
| Primary actions, progress, Cancel, status, log reachable | PASS at 1024×720, 920×600 and maximized (measured, not eyeballed: all mapped and inside the host at the minimum) |
| File list / chapters / fields / cover / output scroll correctly | PASS |
| Mouse-wheel affects the intended area | PASS — wheel over the form scrolls the form; over the Log scrolls the Log; unchanged wiring |
| Tab / Shift+Tab order sensible, no focus trap | PASS — a 31-stop closed loop: rail (6) → file actions → list → shared fields → cover → series → chapters → output → primary actions → log folder. Disabled controls (Cancel, the pager arrows with no files) are correctly skipped |
| Five classic panels remain unconverted | PASS — in the running app and by test |
| ttk still `vista` | PASS |
| Content-host measurements re-recorded at 920×600 / 1024×720 | PASS — table above |
| Remaining classic-panel overflow reported honestly | PASS — table above; M4B Converter at the minimum is still clipped |
| Summary/Details specimen is clearly presentation-only | PASS — headed "component specimen" with the explicit note; not in the product |
| Fixture unreachable from the runtime launcher | PASS — in-app and by test |

### Phase 3 limitations and open items

1. **The vertical half of the Phase 2 geometry regression is still open.** The approved
   rail change fixed the width. The ~96px of height the shell costs the panels (header
   strip + card frame) is untouched, and that is what still clips M4B Converter's
   `Convert M4Bs → MP3s` row (~19px) and Log (~110px) at the 920×600 minimum. The
   maintainer's decision was to leave `MIN_SIZE`/`DEFAULT_GEOMETRY` alone for now and
   re-assess at Phase 5 against the full 100%/125% matrix. Context that still applies:
   M4B Converter, MP3 Tool and M4B Maker already overflow at 920×600 on master too.
2. **The editor's scroll viewport is shallow at the minimum size** — about 206px at
   920×600 (about 330px at the 1024×720 default, and the whole form fits without
   scrolling when maximized). The form is a deliberate scroll region and the action bar
   and Log stay visible, which is the plan's requirement, but at the absolute minimum
   window size only the Audiobook Files card is visible without scrolling. Flagged for
   the Phase 5 review rather than fixed by shrinking the Log.
3. **No 125% scaling pass yet** (carried from Phase 2). Nothing added in Phase 3 uses a
   fixed pixel height — the cards size from their own fonts — but the true 125% pass is
   Phase 5 and is **not** claimed.
4. **`ttk.Combobox` popdown still unthemed** (carried from Phases 1–2). Phase 3 did not
   need it; the editor owns no combobox. Still a Plan 9 item.
5. **macOS still not verified live** (carried from Phases 0–2). The editor's non-Windows
   fork is asserted to build the historical layout with zero namespaced styles via an
   explicit classic bundle, and `_build_ui_darwin`/`_apply_darwin` were not touched, but
   no Mac was available. Not claimed as passed.
6. **One transient observed in the verify gate.** A single `scripts/verify.py` run
   reported `65 passed, 20 skipped` instead of `82 passed, 3 skipped` — 17 extra skips,
   exactly the size of `test_ui_theme.py`, whose module-scoped fixture skips when
   `tk.Tk()` cannot open a display. It happened once, immediately after several GUI
   scripts had created and destroyed Tk roots, and did not reproduce on the same command
   before or after (both `82 passed, 3 skipped`). Recorded because the headless guard
   converts that condition into skips rather than failures, so a transient can quietly
   reduce coverage while the gate still says PASS. The guard predates this drop; not
   changed here.

### Phase 2 — Windows launcher shell (2026-07-31, HOME-PC)

**What it is.** `launcher.py` now routes three shells off `theme["mode"]`:
`aqua` -> `_build_ui_darwin` (untouched), `windows` -> the new `_build_ui_windows`,
anything else -> `_build_ui_classic` (untouched). macOS and Linux/other are
byte-identical to Phase 1; only the Windows arm is new.

**Layout and style mapping** (every widget names a `theme["styles"]` key — no hex
literal and no magic number reaches `launcher.py`):

| Region | Widget | Style key |
|---|---|---|
| Application background | `root.configure(background=…)` | `colors["window"]` |
| Navigation rail | `ttk.Frame`, fixed `metrics["sidebar_width"]` | `sidebar` |
| Rail header ("TOOLS") | `ttk.Label` | `sidebar_label` |
| Tool rows (6) | `ttk.Button`, `command=select_tool` | `nav_button` |
| Rail / column rules | `ttk.Frame` width or height 1 | `divider` |
| Header strip | `ttk.Frame` | `toolbar` |
| Active tool name | `ttk.Label` | `title` |
| Active tool description | `ttk.Label` | `status_label` |
| Content card frame | `ttk.Frame` (1px hairline around the host) | `divider` |
| Content host (`self.content`) | `ttk.Frame` | **none — deliberately unstyled** |
| Status bar | `ttk.Frame` | `window` |
| Status text | `ttk.Label` (`status_var`) | `status_label` |
| Open log folder | `ttk.Button`, `command=_open_logs` | `ghost_button` |
| Load-failure panel | `ttk.Frame` / `ttk.Label` / `tk.Text` | `window`, `title`, `status_label`, `style_tk_widget(…, "log")` |

**How the content host isolates the five classic panels.** `self.content` and every
per-tool container stay **plain, unstyled `ttk.Frame`s in every mode**. ttk has no
style inheritance, so a child that names no style resolves the *generic* `TFrame` /
`TButton` / `TEntry` — exactly what it resolved on master. The shell therefore cannot
leak into a panel even in principle: there is nothing to inherit from. The card
*border* is drawn by a hairline frame wrapped **around** the host rather than by
styling the host itself, which is what lets the border exist without the host
carrying a style. The one thing inside a container that may carry an `ACT.*` style is
the launcher-owned load-failure panel, which only exists when a tool failed to build
— and the smoke tests assert that never happens.

**Selection cue.** The rail marks the active tool with the standard ttk `selected`
state flag, which `ACT.Nav.TButton` maps to the soft accent fill plus primary text.
Unlike the classic cue (which *disables* the active button) no row is ever disabled,
so every row stays reachable by Tab and keeps its focus ring. `Open log folder` was
promoted from a clickable `tk.Label` to a real `ttk.Button` for the same reason —
it now takes focus and fires on Enter/Space. Both actions are otherwise unchanged.

**No fixed pixel heights.** The header and status bar size themselves from their own
fonts, so 125% display scaling grows them instead of clipping them. `sidebar_width`
is the only fixed dimension; the longest tool name needs 112px of the 212px available
inside the rail, so it has slack at 125%.

**Phase 2 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — **10 passed**, 1 warning in 2.18s (was 1) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — 16 passed in 0.12s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **68 passed, 3 skipped**, 1 warning in 4.42s (was 59/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 68 passed/3 skipped; deps `==`-pinned; docs de-templated |
| `git diff --check` | clean (only the benign LF→CRLF notice) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3
skips are the pre-existing env-gated suites. Neither is new.

**What the 9 new launcher tests assert:** the six tools stay in `TOOLS` order and each
gets a nav control in that order; three full sweeps of all six panels produce zero
error panels, no new containers, and the *same container objects* (build-once intact);
a real typed value in the metadata editor survives switching away through three other
tools and back; a valid saved `last_tool` is restored and **only that tool is built**
(the rest stay lazy); an unknown saved key falls back to the first available tool; a
saved tool whose module has gone missing drops out of the registry, gets no nav row,
and falls back safely; every launcher-owned widget carries the intended `ACT.*` style
and **every** non-empty style string anywhere in the shell is `ACT.*`-prefixed;
selection moves the `selected` flag rather than accumulating it and no row is left
disabled; and no widget inside any tool container carries an `ACT.*` style, while
`TButton`/`TFrame` still resolve to `SystemButtonFace` and `ACT.Primary.TButton` to
the accent. The last three are Windows-only and skip elsewhere, because
monkeypatching `sys.platform` for a whole launcher build would also lie to the six
tool modules while they construct.

**Draft visual review (real app, real Tk window, HOME-PC, 1920×1080 @ 100%).** Not
the Phase 5 matrix — draft images live in the session scratchpad and are deliberately
**not** committed.

| Check | Result |
|---|---|
| Recognizably redesigned Windows shell | PASS — dark rail + header + card + status bar, not a recolor |
| Six tools, existing order, all open | PASS — 6/6, zero error panels |
| Selected / hover / pressed / disabled / focus visible | PASS — accent-soft selected fill; focus ring visible on both a nav row and the log button |
| Five non-prototype panels keep classic presentation | PASS — TTS, M4B Converter, MP3 Tool, M4B Maker, Cover render exactly as on master |
| No child-panel `ACT.*` styling | PASS — verified in-app and by test |
| Switching preserves identity and state | PASS |
| Saved last-tool restore / invalid fallback | PASS |
| Status text and log-folder action | PASS — status updates per tool; log button focusable and fires |
| ttk theme still `vista` | PASS |
| Normal (1024×720) / minimum (920×600) / maximized (1920×1009) | PASS for launcher-owned controls — nothing overlaps or clips at any of the three; status and log action stay visible and reachable |
| Content host seam around classic panels | PASS — the host is unstyled, so a classic panel sits on the same background it always had; no unreadable seam |
| **Usable panel area at minimum size** | **OPEN — regression, see below** |

### Phase 2 limitations and open items

1. **The new shell costs the tool panels real space, and at the 920×600 minimum that
   clips a primary action.** Measured content-host size (both shells, same build,
   same panels):

   | Window | Classic shell (master) | Windows shell (Phase 2) | Delta |
   |---|---|---|---|
   | 920×600 (minimum) | 796×561 | 669×457 | −127 w, −104 h |
   | 1024×720 (default) | 900×673 | 773×577 | −127 w, −96 h |

   110 of the 127 lost pixels are the navigation rail: `metrics["sidebar_width"]` is
   232 where the classic sidebar was ~122 including its padding. The rest is the
   header strip and the card frame. I already took the card frame down from
   `content_pad` to `gap_sm`, which recovered 16 w / 12 h; that is everything
   reclaimable inside `launcher.py` without changing a Phase 1 token.

   Effect, by panel requested-size vs host:
   - **Already true on master:** M4B Converter (+118 h), MP3 Tool (+294 h) and
     M4B Maker (+203 h) overflow at 920×600 on the *classic* shell too. Panels
     overflowing at the minimum size is a pre-existing condition, not a new class
     of bug.
   - **New in Phase 2 at the default 1024×720:** M4B Maker (+75 w) and M4B Metadata
     (+77 w) now overflow *horizontally* where they had 52/50px of slack, and every
     panel's vertical overflow grows by ~96px.
   - **Concretely visible:** M4B Converter at 920×600 no longer shows its
     `Convert M4Bs → MP3s` row or its Log box; on master at the same size it does.

   **I did not fix this, on purpose.** The two real levers are
   `metrics["sidebar_width"]` and `MIN_SIZE`, both of which live in
   `shared/ui_theme.py` — a file this phase was told to leave alone unless the
   launcher exposed a *missing primitive*, which this is not. It is a value/geometry
   decision, and the plan (§7.1, §7.2) says token values and any geometry change are
   approved by the maintainer with evidence, not chosen by the implementer.
   **Options for the maintainer, cheapest first:**
   (a) drop `sidebar_width` 232 → 180 (recovers 52 w; the existing test floor is
   `>= 180`, so it still passes); (b) raise `MIN_SIZE`/`DEFAULT_GEOMETRY` with the
   evidence above — note `MIN_SIZE` is shared with macOS; (c) accept it, on the
   grounds that Plan 9 converts these panels to the denser new design anyway and
   they already overflow at the minimum size today.

2. **No 125% scaling pass yet.** The draft review was 100% only. Nothing in the shell
   uses a fixed height, and the rail has 100px of text slack, but the true 125% pass
   is Phase 5 work and is **not** claimed as done.

3. **Draft review is not visual approval.** The mandatory ten-image 1920×1080
   100%/125% matrix under `files/UI-Prototype-Screenshots/v0.6.0-drop1/` remains
   Phase 5, and the draft images are not committed.

4. **`ttk.Combobox` popdown list is still unthemed** (carried from Phase 1). The
   dropdown is a classic Tk listbox reachable only through the global option database,
   which would leak into the five unconverted panels. The launcher owns no combobox,
   so this did not bite in Phase 2; if Phase 3 needs a dark popdown it must be scoped
   per-widget with the isolation tests still green.

5. **macOS still not verified live** (unchanged from Phases 0–1). `_build_ui_darwin`
   and `_apply_darwin` were not touched, and the aqua/classic branch tests pass, but
   no Mac was available. Not claimed as passed.

### Phase 1 — Windows design primitives (2026-07-31, HOME-PC)

**What it is.** `shared/ui_theme.py` now routes each platform explicitly —
`darwin -> "aqua"`, `win32 -> "windows"`, everything else -> `"classic"`. Windows is
never inferred from "not macOS" any more. The Windows branch keeps the **native
`vista` base theme** and layers a dark design system on top as namespaced styles and
token dictionaries. Nothing is applied to a widget automatically: a panel opts in by
naming an `ACT.*` style or by calling `style_tk_widget()`.

**The isolation mechanism (this is the part later phases must not break).**
`vista` draws buttons, entries, comboboxes, spinboxes, checkbuttons, radiobuttons,
notebook tabs, progressbars, scrollbars, Treeview fields/headings and labelframes
with native Windows theme parts that **ignore** `-background`/`-foreground`. Switching
the app to `clam` would recolor them but would also silently restyle the five panels
this drop must leave alone. So each recolorable element is *cloned* into the live
theme under the prefix:

```
ttk::style element create ACT.Button.border from clam Button.border
```

and the `ACT.*` styles are laid out from those clones. Generic `TFrame` / `TLabel` /
`TButton` / `TEntry` / `TCombobox` / `Treeview` / … are never created, configured or
re-laid-out, so an unconverted panel keeps native vista rendering while a converted
one gets a fully colorable dark control set from the same toolkit.
`element_create` raises `Duplicate element` on re-entry, so the clone step is guarded
and `apply_theme` is idempotent.

**Rule for Phase 2/3 and for Plan 9 later:** every variant style needs its **own**
layout. ttk resolves a name by stripping leading components, so `ACT.Primary.TButton`
falls back to plain `TButton` — the native vista button — unless it is given the
`ACT.TButton` layout explicitly. `_ACT_LAYOUTS` does this for every variant; adding a
new variant means adding it there too, or the dark fill silently will not stick.

**API introduced (all in `shared/ui_theme.py`):**

| Name | What it is |
|---|---|
| `WINDOWS_STYLE_PREFIX` | `"ACT"`. Every registered style begins with it; nothing outside it is touched. |
| `theme["mode"]` | now `"windows"` on win32 (was `"classic"`). `launcher.py` only tests `== "aqua"`, so it still takes the classic build path — that is why Phase 1 changes nothing on screen. |
| `theme["base_theme"]` | the ttk theme actually in use (`"vista"`, or `"clam"`/`"default"` when vista is unavailable). |
| `theme["colors"]` | 35 semantic colour roles (surfaces, text, accent/focus, status, fields/selection, scrollbars, Shared Metadata). Nonempty on Windows; still `None` on the classic branch. |
| `theme["metrics"]` | 26 spacing/sizing tokens (sidebar width, row height, pads, gap scale, control padding, border/scroll widths, `content_max_width`). |
| `theme["fonts"]` | 11-entry Segoe UI type scale + `Consolas` mono. `font_heading`/`font_button` keep their historical values so the bundle is still a drop-in for the classic launcher. |
| `theme["styles"]` | semantic key → ttk style name (`theme["styles"]["primary_button"] == "ACT.Primary.TButton"`). **Panels must look styles up here, not hard-code the string.** |
| `style_tk_widget(widget, theme, role="surface", **overrides)` | the one sanctioned way to colour classic Tk widgets ttk cannot style (`Canvas`, `Listbox`, `Text`, `Frame`). Roles: `window, surface, elevated, muted, sidebar, shared, field, list, text, log, canvas, divider`. Unsupported options are dropped so one call works for every widget class; `overrides` win; unknown role raises `ValueError`; **no-op on any non-Windows bundle**, so panels may call it unconditionally. Returns the applied option dict. |

**Explicitly unchanged:** `apply_theme(root, style)` signature, `DEFAULT_GEOMETRY`,
`MIN_SIZE`, `enable_mousewheel`, and the whole `ProgressIndicator` class (`update`,
`set_indeterminate`, `reset`, `finish`, main-thread contract). `ProgressIndicator`
deliberately still uses the *generic* styles — five unconverted panels instantiate it,
and a test asserts its widgets carry an empty style string.

**Phase 1 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **16 passed** in 0.15s (was 5) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 1 passed, 1 warning in 1.54s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **59 passed, 3 skipped**, 1 warning in 3.64s (was 48/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 59 passed/3 skipped; deps all `==`-pinned; docs de-templated |
| `git diff --check` | clean (no whitespace errors) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3
skips are the pre-existing env-gated suites. Neither is new.

**What the 11 new theme tests actually assert:** explicit `"windows"` mode and a
backwards-compatible bundle; every colour parses as `#rrggbb` and every required
semantic role exists; WCAG contrast floors on all seven surfaces (primary text ≥7:1,
secondary ≥4.5:1, disabled ≥3:1, focus ring ≥3:1, status/accent ≥4.5:1 on the card,
`inverse`-on-accent and `selection_text`-on-selection ≥4.5:1); metrics are
non-negative ints with sane layout minimums; every style name starts with `ACT.`, has
a layout, and roots in a cloned element rather than a native one; hover / pressed /
selected / disabled / focus / danger states are defined and actually resolve to
different values; **generic styles are byte-identical before and after applying the
Windows theme** (layout + configure + background/foreground/fieldbackground lookups +
state maps, for 18 generic styles); re-applying three times is idempotent; the branch
still returns a full bundle when `vista` raises; one real widget per style builds and
renders; and `style_tk_widget` applies/drops/overrides correctly and is a genuine
no-op on the classic bundle.

**Live Windows evidence (real `LauncherApp`, real Tk window, not a mock):**
- `theme["mode"] == "windows"`, `ttk` theme in use still `vista`.
- All six tools registered in order and selected twice: **zero** error panels,
  6 containers with stable object identity (build-once intact), state marker survived
  switch-away/back, `last_tool` round-tripped, geometry `1024x720`, minsize
  `(920, 600)` — identical to the Phase 0 baseline.
- Style audit across the whole widget tree: `tts` 63, `m4b_converter` 38, `mp3_tool`
  41, `m4b_maker` 53, `cover` 24, `m4b_metadata` 64 widgets — **the only distinct
  style string in every panel is `""`**, and the 14 launcher-chrome widgets are the
  same. Zero widgets use an `ACT.*` style anywhere in the application.
- Generic lookups after theming: `TButton`/`TFrame`/`TLabel`/`TEntry`/`TCombobox` →
  `SystemButtonFace`, `Treeview` → `SystemWindow` (native vista values), while
  `ACT.Primary.TButton` → `#4f8ff7`. Both facts are true at the same time, which is
  the whole point of the namespace.

### Phase 1 limitations and open items

1. **No visual/eyes-on inspection.** Everything above is behaviour and style-resolution
   evidence gathered programmatically. Nothing has been *looked at*, and by design
   nothing is visible yet — no widget uses the new styles. Appearance remains Phase 5's
   gate, and the exact colour values are approved through screenshots, not by these
   tests.
2. **`ttk.Combobox` popdown list is not themed.** The dropdown is a classic Tk listbox
   reachable only through the global option database
   (`option_add("*TCombobox*Listbox.background", ...)`), which would leak straight into
   the five unconverted panels' comboboxes. Deliberately not done. If Phase 3 needs a
   dark popdown it must be scoped per-widget, and the leakage test must still pass.
3. **Element clones are per-interpreter.** `ACT.*` elements are created in the live ttk
   theme of the Tk interpreter that `apply_theme` was called on. That is fine for the
   app (one root) and for the tests (module-scoped root); a second `tk.Tk()` would need
   its own `apply_theme` call. Not a defect, just the contract.
4. **macOS still not verified live** (unchanged from Phase 0). aqua preservation is
   proven only by the untouched `_apply_darwin` code path plus monkeypatched-platform
   tests. Not claimed as passed.
5. **Optional tooling:** Context7 was not needed — the question was "can vista host
   cloned clam elements", which was answered by probing the actual Tk 8.6 build in the
   repo venv rather than by reading documentation. Superpowers' executing-plans flow
   structured the phase. Nothing was auto-installed.

### Phase 0 baseline evidence (2026-07-31, HOME-PC)

**Environment**
- Windows 11 Pro 10.0.26200, HOME-PC, repo at
  `…\MyProjects\Home-PC\Audiobook-Creation-Tool`
- Repo venv `.venv\Scripts\python.exe` → Python 3.12.10
- `bootstrap.py --self-test`: venv valid, requirements found, HF_HOME →
  `files/runtime-data/models/huggingface`, `kokoro health = True (ok)`,
  tkinter/ssl/venv/tcl_tk all True, ffmpeg on PATH (`C:\ffmpeg\bin\ffmpeg.EXE`),
  ffprobe available, launch target `scripts/Universal/launcher.py` present.

**Automated baseline (no source edits)**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — 5 passed in 0.18s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 1 passed, 1 warning in 8.90s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — 48 passed, 3 skipped, 1 warning in 8.41s |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 48 passed / 3 skipped; deps all `==`-pinned; docs de-templated |
| `git diff --check` | clean (no whitespace errors, no output) |

The single warning is the long-standing pydub `audioop` DeprecationWarning, not a
regression. The 3 skips are the pre-existing env-gated suites.

**Windows launcher six-tool manual baseline** — a real (non-withdrawn) Tk window was
opened on this machine through the real `LauncherApp` and every tool was selected once
in registry order, then a second full pass was made to prove build-once and state
preservation:

- Registry order (6/6, unchanged): `tts`, `m4b_converter`, `mp3_tool`, `m4b_maker`,
  `cover`, `m4b_metadata` — titles "TTS Audiobook", "M4B Converter", "MP3 Tool",
  "M4B Maker", "Cover Image", "M4B Metadata".
- Error panels raised across both passes: **none** (`_show_load_error` was
  instrumented and never fired).
- Build-once: 6 containers after pass 1, still 6 after pass 2, and every container's
  object identity was unchanged — panels are shown/hidden, never rebuilt.
- State preservation: a marker attribute set on the M4B Metadata container survived a
  full switch-away/switch-back cycle.
- `last_tool` persisted and read back correctly (`m4b_metadata`); `settings.json` was
  snapshotted and restored, so the baseline left no trace.
- Build-all wall time 1.601 s (per-tool 0.015–0.077 s).
- Realised window: `1024x720+104+104`, minsize `(920, 600)`.

**Pre-prototype Windows theme contract** (what Phase 1 must extend without breaking) —
`shared.ui_theme.apply_theme()` on `win32` returns:

```
mode          = "classic"        ttk theme in use = "vista"
family        = "Segoe UI"       font_heading = ("Segoe UI", 15, "bold")
geometry      = "1024x720"       font_button  = ("Segoe UI", 11)
min_size      = (920, 600)
colors        = None             metrics      = None
```

`colors`/`metrics` being `None` on Windows is exactly the gap Phase 1 closes. Public
surface to preserve: `DEFAULT_GEOMETRY`, `MIN_SIZE`, `ProgressIndicator`,
`apply_theme`, `enable_mousewheel`.

**Before-state screenshot inventory** — all **8** images present and untouched under
`files/UI-Current-Screenshots/`: `cover-image-resizer-current-ui.png`,
`m4b-converter-current-ui.png`, `m4b-maker-current-ui.png`,
`m4b-metadata-current-ui-1.png`, `m4b-metadata-current-ui-2.png`,
`mp3-tool-current-ui.png`, `tts-audiobook-current-ui-1.png`,
`tts-audiobook-current-ui-2.png`. (The plan says "eight before-state images"; the
matrix is 8 files covering 6 tools — TTS and M4B Metadata each have two.)

### Phase 0 limitations and open items (recorded, not silently passed)

1. **No visual/eyes-on inspection was performed.** The six-tool pass was driven
   programmatically through the real `LauncherApp` on a real Tk window; an agent
   cannot judge appearance. This is a baseline of *behaviour*, not of *looks* —
   appearance is Phase 5's gate.
2. **`md-instructions/` filename casing.** The maintainer had renamed the four
   permanent docs on disk to the AI-WORKSPACE casing (`Changelog.md`, `Decisions.md`,
   `Handoff.md`). Git tracks them as `CHANGELOG.md`, `DECISIONS.md`, `handoff.md`, and
   because `core.ignorecase=true` on Windows the rename was never staged — the
   fast-forward checkout restored the tracked casing. **Not changed, and deliberately
   out of Phase 0 scope:** `scripts/verify.py` hard-codes
   `md-instructions/CHANGELOG.md`, so a real case-rename needs a `verify.py` edit,
   which this drop is forbidden from touching. The live filenames are
   `Briefing.md` / `CHANGELOG.md` / `DECISIONS.md` / `handoff.md`, and the plan
   references those same names. **Maintainer decision needed** if the AI-WORKSPACE
   casing is wanted — it should be its own housekeeping commit, not part of this drop.
3. **macOS not verified this session.** No Mac was available; the macOS Finder/aqua
   preservation requirement is proven only through monkeypatched platform-branch
   tests. A live macOS pass remains open for Plan 9 and is **not** claimed as passed.
4. **Git identity on this checkout** is `Elijah Matthew <elijahmatthew015@gmail.com>`,
   not the `elmatthe <elmatthe@ualberta.ca>` pair in AI-WORKSPACE. Left as-is (the
   repo does not lack an identity); flagged only so it is a conscious choice.
5. **Optional tooling:** Sequential Thinking / Context7 were available but not needed
   in Phase 0 — no external library documentation question arose. Superpowers'
   executing-plans flow was used to structure the phase. No tool was auto-installed.

## Previous Focus (v0.5.1 — shipped to master)
**Batch-timing-parity drop ABANDONED by maintainer decision after A/B listening
(2026-07-19); Jenny voice addition kept; v0.5.1 committed to branch
`add-jenny-voice` and pushed for a Windows second-verify pass.** The Phases 1–3
engine work (subprocess delegation, pause-field threading, per-path
`batch_timing_preset` overrides, batch harness, engine `rate` kwarg) hit its
measured targets (every non-Jenny voice within −22…0 ms of its old-batch median)
but sounded subjectively worse than the original chunk pipeline on the
maintainer's six-voice A/B listen — reverted IN FULL from the working tree
(nothing had been committed; see the do-not-retry ADR in DECISIONS.md
2026-07-19 and the work-log entries below, which stand as the historical
record). Final state: batch mode is byte-identical to pre-drop `master`
(chunk pipeline, speaker+rate only, original "Steffan Neural" banner); the ONLY
functional change vs master is the Jenny voice addition (registry entry
750/800 single-file preset, smoke-test counts 12/7, generate_voice_samples
filter args, gitignore entries, sample MP3) plus docs and the 0.5.1 version
bump. Investigation artifacts (batch-baselines/, phase3-listen/, harness, child
script) deleted; drop file deleted per convention. Maintainer pulls
`add-jenny-voice` on Windows, verifies, and merges to master themself — do NOT
merge or push to master from here. Phase 2 (engine change) is
implemented: batch per-file conversion now delegates to `run_conversion_job` in a
child subprocess per file (`tts/batch_convert_child.py` is the child entry;
`_delegate_to_child` in `batch_convert.py` is the spawn/cancel/log seam and the
test-fake point). All seven pause/trim fields + MP3 bitrate thread GUI →
`run_batch_convert` → `convert_single_pdf` → child; presets NOT re-tuned (Phase 3
measures against phase1 baselines). The engine gained ONE additive, default-inert
kwarg: `rate="+0%"` through `run_conversion_job` → `read_book` →
`run_edgespeak`/`parallel_edgespeak` (edge-tts's own default — needed because old
batch honored the GUI Speech-rate field and the single-file engine had no rate
support; single-file inertness proven live: post-change single-file intro render is
millisecond-identical to the reference). Old chunk pipeline
(`split_into_chunks`/`synthesize_chunk_mp3`/`merge_mp3s` + CHUNK_* constants)
removed from batch_convert; "Steffan Neural" banner now shows the real voice.
Live gates: workers=2 real batch → 2/2 mirrored outputs correct, no orphan
children; cancel drill terminates the in-flight child cleanly; verify → RESULT:
PASS (49 passed / 3 skipped; batch tests rewritten around the delegation seam,
5→8). New-engine measurements in
`files/livid-lady-test-files/batch-baselines/phase2-newengine.json`. **⚠ Phase 3
conflict now quantified (maintainer decision required):** restoring old-batch
cadence needs sentence-preset cuts of −162 ms (Steffan), −436…−458 ms (Andrew ×2,
Ava ×2), Aria +70 ms, all of which would shift single-file identically under the
shared preset — per-path presets (or accepting single-file cadence in batch) must
be chosen before Phase 3 re-tuning. Jenny's batch is already −150 ms tighter than
her old batch purely from the engine change. The Jenny preset-trim session's 6
modified files (2026-07-19, further below) still await the same single drop commit.
No behavior change: the only new code is the dev/QA harness
`scripts/Universal/tts/batch_timing_harness.py` (never imported by the app);
verify → RESULT: PASS (46 passed, 3 skipped). Decision: **delegate batch per-file
conversion to `run_conversion_job` via a child subprocess per file** (thread-level
delegation is disproven — a 2-thread demo corrupted/crashed on the process-global
`os.chdir` in `runner.py` on 2/2 runs; a chdir-free engine refactor would touch ~30
cwd-relative filename sites in the GPL-derived engine). Subprocess prototype passed
at workers=1 (real PDF) and workers=2 (nested same-stem tree): mirrored absolute
targets correct, no cross-contamination, parent cwd preserved, and the delegated
render's gap profile is identical to the single-file reference (timing parity by
construction). Baselines for all **7** Edge voices (drop says 6 — Jenny makes 7) ×
{00-intro, 03-ch1-1} captured on the CURRENT engine →
`files/livid-lady-test-files/batch-baselines/phase1-baseline.json` (+
`phase1-variance.json`: Edge synthesis is deterministic run-to-run, gap means ±2 ms,
so Phase 3's ±25 ms tolerance is measurable). Kokoro batch confirmed NOT on this
path (inline GUI loop → `kokoro_file_to_mp3`; untouched by this drop). **⚠ Flag for
the maintainer before Phase 3:** old-batch parity and single-file invariance are
mutually exclusive under one shared preset — e.g. Steffan's old batch median gap is
~770 ms but his single-file (= new-batch) measured gap is ~951 ms at the same preset;
matching old batch within ±25 ms forces preset cuts that would audibly change
single-file mode. Resolution options recorded in the Phase 1 summary. The Jenny
preset-trim session's 6 modified files (2026-07-19, further below) still await the
same single drop commit.

## Previous Focus (UX progress + metadata layout drop — awaiting maintainer commit)
**UX progress + metadata layout drop (`0.5.0-ux-progress-and-metadata-layout.md`) —
ALL PHASES (1–5) DONE on HOME-MacOS (2026-07-08), awaiting maintainer final sign-off
+ the single drop commit.** Phase-4 layout was visually approved by the maintainer
(scrolling, larger Log, de-staled description, progress all confirmed). Phase 5
close-out: full suite 46 passed / 3 skipped; `python scripts/verify.py` →
RESULT: PASS; Windows/classic path proven unchanged (scoped win32 stub on ui_theme →
classic mode, Segoe UI, 6 ttk sidebar buttons, all six tools built, zero error
panels); CHANGELOG [Unreleased] Added+Changed entries, Briefing (ui_theme /
worker-progress / metadata-editor bullets), DECISIONS ADR (progress placement in
ui_theme.py + the deliberate M4B Maker indeterminate call). Drop file deliberately
NOT deleted and nothing committed (maintainer instruction — no .git on this copy;
the maintainer carries files to a real clone, single commit, no AI co-author
trailers).
Work summary — Phase 2: shared `ProgressIndicator` (ttk.Progressbar +
counter/percentage label, main-thread-only `update/set_indeterminate/reset/finish`
API) in `shared/ui_theme.py` (NOT the launcher — tools import shared.*, never
launcher.py) + headless-guarded test. Phase 3: progress wired into all six tools
strictly through each tool's EXISTING worker queue/drain (workers only enqueue
`("progress", (done, total))` / `("progress_ind", text)`; no off-thread widget
violations found in any tool). Determinate: M4B Converter (files), Cover Image
(images), M4B Metadata (files ×3 workers), MP3 Tool (SAFE-combine per track,
time-edit + ID3 per file), TTS (Edge batch + Kokoro batch per file; Kokoro single
per chunk and Edge single per paragraph via new additive `progress_callback=None`
params in `kokoro_file_to_mp3` / `read_book` / `run_conversion_job`). Indeterminate:
M4B Maker (single concat/encode — its old bar was dead: 0 until one jump at the end;
dead `progress_max` queue kind removed) and MP3 Tool's single-concat stages (FAST
mode, SAFE final concat). Phase 4: metadata editor tag/settings sections wrapped in
the exact TTS-style scroll canvas (canvas_wrap + create_window + scrollregion/width
sync + `enable_mousewheel`), Log enlarged to a fixed 14 rows outside the scroll
area, stale "(Added in Phase 6.)" description fixed in launcher.py. Cancel + Log
untouched on every tool. The two previous foci below also still await their single
maintainer commits.

## Previous Focus (component-verify drop — awaiting maintainer commit)
**macOS component-verify drop (`0.5.0-macos-component-verify.md`) — ALL PHASES DONE on
HOME-MacOS (2026-07-08), awaiting maintainer sign-off + the single drop commit.**
Phase 1 kickoff gates green; Phase 2 (Kokoro §2.4) was already fixed 2026-07-07, health
re-confirmed only; Phase 3 voice samples 11/11, approved by maintainer listen; Phase 4
per-tool live pass — **all six tools confirmed working live on macOS** (maintainer reviewed
screenshots), zero macOS-specific breakage, zero code changes; Phase 5 close-out — full
suite 45 passed / 3 skipped, `python scripts/verify.py` → RESULT: PASS, docs updated.
**Residual gap (not a bug):** M4B Converter was verified on a standard AAC-LC M4B only —
the `aac_at` xHE-AAC/USAC decode path on macOS is still unverified (no USAC sample on
hand); see Briefing known limitations. Drop file deliberately NOT deleted and nothing
committed (maintainer instruction). Still no `.git` on this copy — the maintainer carries
files to a real clone. Previous focus below (UI-shell drop close-out) also remains
awaiting its single maintainer commit.

## Previous Focus (UI-shell drop — awaiting maintainer commit)
**macOS UI-shell drop (`0.5.0-macos-ui-shell.md`) — ALL PHASES DONE on HOME-MacOS
(look approved by maintainer 2026-07-08; wheel/trackpad scroll fix added; Phase 5
close-out complete, verify → RESULT: PASS).** Awaiting two maintainer actions:
(1) live-test wheel/two-finger scrolling on the TTS panel, then (2) make the single
drop commit (drop file deliberately NOT deleted and nothing committed until then).
Earlier: the Kokoro-on-macOS §2.4 fix in `bootstrap.py` is live-verified on this
machine and still uncommitted alongside this drop's work. **⚠ This Mac's working copy
has NO `.git` directory** (not a clone — likely copied/zip-transferred), so nothing
can be committed or pushed from this machine as-is; the maintainer must reconcile
these changes onto a real clone. Windows-side drops still pending after this:
Drop 4 (script hardening), then the Windows UI drop.

---

## Open Issues / Bugs

| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | Minor | scripts/Universal/shared/bootstrap.py | Drop 3 §2.4 (Kokoro on macOS) — RESOLVED 2026-07-07 on the MacBook. Real root cause: ENVIRONMENTAL, not `kokoro_synth.py`. The venv was built on Python 3.13.7 (the Mac's only Python), but Kokoro's PyPI wheels require >=3.10,<3.13, so the requirements marker skipped the wheel and every self-heal repair failed with "No matching distribution found for kokoro==0.9.4". Fixed in `bootstrap.py`: `run_setup` now installs Python 3.12 before accepting a >=3.13 interpreter (3.13+ kept only as Edge-only fallback), and `_create_validated_venv` rebuilds a >=3.13 venv once a <3.13 base exists. Verified live: 3.12.13 venv, `kokoro_is_healthy` → `(True, 'ok')`. See DECISIONS.md 2026-07-07 ADR. | **Closed — fixed in bootstrap.py** | Claude Code |
| 2 | Minor | scripts/Universal/tts/kokoro_synth.py | CLI-only cosmetic: `kokoro_file_to_mp3`'s default `log=print` emits a `→` character, which raises UnicodeEncodeError on a cp1252-encoded Windows console (found while scripting Drop 3 verification). The GUI is unaffected (logs go through the Tk queue, never stdout). Flagged for review, not fixed — out of Drop 3 scope. | Open — flagged for maintainer | Claude Code |
|   |       |     | (Windows xHE-AAC decode is a documented known limitation, not a bug — see CHANGELOG [0.3.2]. The macOS `aac_at` counterpart decodes AAC-LC fine (verified 2026-07-08) but an actual xHE-AAC/USAC decode on macOS is still unverified — no USAC sample on hand.) | | |

---

## Migration Map — contract for Phase 2 (drop `0.5.0-drop1-restructure-and-docs.md`)

Grounded in the fresh REPO-STRUCTURE.md (2026-07-06 15:56) and the maintainer's answers to all
nine open questions. Windows tree is the canonical source (trees byte-identical except the two
dead legacy files below).

**Program code → `scripts/Universal/`** (git mv from `Windows/scripts/`):
- `mp3_tools/{__init__,cover_resizer,m4b_converter,m4b_maker,m4b_metadata_editor,mp3_tool}.py`
- `shared/{__init__,bootstrap,cancellation,close_terminal,ffmpeg_utils,logging_setup,metadata,paths,release,settings,subprocess_utils,version}.py`
- `tts/{__init__,batch_convert,epub2tts_gui,kokoro_synth,pdf_extractor,voice_registry}.py`
- `tts/epub2tts_edge/{__init__,epub2tts_edge,runner}.py`
- `launcher.py`
- `Windows/requirements.txt` → `scripts/requirements.txt` (single shared; the two files were
  identical except the header comment — maintainer confirmed Q6)

**Deleted, not migrated (maintainer Q2 — confirmed dead, no legacy folder):**
- `scripts/mp3_tools/mp3_tools_launcher.py` (both trees)
- `scripts/tts/setup_env.py` (both trees)

**Dev-only → `files/`:**
- `scripts/tests/test_kokoro_voices.py` → `files/tests/`
- root `test-files/` → `files/test-files/` (stays gitignored — copyrighted media)
- `Windows/test-logs/` → `files/test-logs/` (gitignored)
- `Windows/Dockerfile` → `files/Dockerfile` (maintainer Q3 — dev-only, not a shipped path)
- v0.3.1 one-shot docs (`MACOS-DEBUG-v0.3.1.md`, `MACOS-FIX-REPORT-v0.3.1.md`,
  `WINDOWS-RELEASE-HANDOFF-v0.3.1.md`) → `files/release-history/` (one copy each)
- `files/vibe-coding-templates/` — already in place, unchanged

**Runtime-writable data → `files/runtime-data/` (maintainer Q4; layout chosen by agent):**
- `<OS>/resources/logs/` → `files/runtime-data/logs/` (gitignored; old log files not carried —
  runtime-generated)
- `<OS>/resources/settings.json` → `files/runtime-data/settings.json` (gitignored; Windows copy
  wins if the two diverge — it is the actively-used one)
- `Windows/resources/models/huggingface/` (Kokoro-82M cache, ~300 MB) →
  `files/runtime-data/models/huggingface/` (gitignored, never committed; answers Q5 — this is
  the ONE canonical in-repo cache path for `bootstrap.py`/`launcher.py`/`kokoro_synth.py`)
- `resources/bin/` concept (portable ffmpeg fallback) → `files/bin/` (the AI-WORKSPACE-standard
  home for setup-downloaded binaries; gitignored)
- Implementation: repoint `RESOURCES_DIR`-style constants in `paths.py` / `bootstrap.py` once;
  keep the internal `logs / models / settings.json` names so the diff stays minimal.

**md-instructions — two sets collapse into one root set:**
- `Windows/md-instructions/{Briefing,CHANGELOG}.md` + identical MacOS copies → one
  `md-instructions/{Briefing,CHANGELOG}.md` (byte-identical today, verified by diff — merge is
  trivial; then rewritten per Phase 3)
- New: `DECISIONS.md`, `Instructions_Template.md` (from `files/vibe-coding-templates/`)
- This `handoff.md` is already at its final location

**Entry points (maintainer Q1 + Q7):**
- Root launchers renamed to exactly `Setup_and_Run-audiobook-creation-tool.bat` /
  `Setup_and_Run-audiobook-creation-tool.command` (Phase 5). These stay the ONLY user-facing
  entry files.
- Fast path stays `bootstrap.py --launch-only` (self-heal on every launch preserved exactly),
  repointed to `scripts/Universal/shared/bootstrap.py`. No `cd` into `Windows/`/`MacOS/`.
- Preserve untouched: Windows `pythonw.exe` no-console fast path, macOS Gatekeeper/App
  Translocation guard, Kokoro/venv/ffmpeg self-heal. `.venv` moves to the repo root (the
  AI-WORKSPACE location) since the per-OS trees disappear.

**Other maintainer decisions:**
- Q8: create `.codex/` (CODEX.md pointer to AI-WORKSPACE.md + settings) — Codex is used.
- Q9: README gets a short v0.5.0 status line (internal restructure, no feature changes); keep
  v0.4.0 download links until a v0.5.0 release is published.
- Pending master edits (console-flash fix + AI-WORKSPACE.md) committed on master as `e80ba7f`
  BEFORE branching, so the restructure branch contains only restructure work.

**Drift found vs the drop's assumptions (reality followed, per drop rules):**
- The "loose root handoff.md" no longer exists; `md-instructions/handoff.md` was a blank
  template (no live state to migrate from it — live state reconstructed from the v0.3.1
  one-shots + CHANGELOG).
- Empty `scripts/{Universal,Windows,MacOS}/`, `md-instructions/`, and `files/` skeletons were
  pre-created by the maintainer before this session.
- Working tree had uncommitted `[Unreleased]` changes on master (handled above).
- `dist/` (gitignored release zips) stays at root — `release.py` writes there by design.

---

## Work Log (newest first)
- 2026-08-04 — v0.6.0 Drop 2 (Plan 2) **Phase 5 — Cover Image and M4B Maker exceptions**
  (HOME-PC). Implemented both Decision 10A destination exceptions, opt-in and off by default,
  leaving the Phase 4 standard modes untouched. Cover Image's disabled placeholder became a real
  `Save beside source images` toggle with exactly two choices; replacement needs **three
  independent gates** — toggle, radio and a per-run confirmation — and `effective_mode()` is the
  single place that combines them, so either switch alone yields a safe mode. Numbered copies
  use the new `SourceSidePlanner`, which starts at `stem-1.ext` (beside a source the unnumbered
  name *is* the source) and keeps a separate collision sequence per source directory. Every
  source is validated before the dialog, so the count shown is the count that can be processed
  and links, missing files, directories and formats that cannot round-trip in place are refused
  there rather than mid-run. Replacement writes a complete `.act-tmp-…` sibling **in the
  source's own directory** so the install can be atomic, validates the finished image's size,
  then calls `os.replace` — never delete-then-rename — and a failure at any of those three
  points leaves the original byte-for-byte unchanged with only this operation's temporary file
  removed. `discard_temporary()` refuses any path lacking the prefix, so cleanup cannot be
  talked into deleting a user's file. A partial batch reports truthfully. M4B Maker gained
  `Choose custom destination`: controls revealed only while on, one read point so a stale hidden
  path cannot steer a standard build, full pre-validation (absolute, existing, directory, not a
  link, writable via a probe that is removed again), direct output with **no nested
  `M4B-Maker-N`**, and staging moved to an operation-owned `tempfile.mkdtemp()`. **Found and
  fixed a serious bug before it shipped:** Phase 4's cancellation ran `shutil.rmtree(out_dir)`
  unconditionally, which in custom mode would have deleted the *user's own folder* and
  everything in it; cancellation now branches on the mode and removes only operation-owned
  artifacts. Added `test_cover_source_side.py` (34) and `test_maker_custom_destination.py` (31);
  Phase 4's Cover placeholder tests were superseded and two scope guards retargeted from "no
  exceptions exist" to "exactly these two exist". Suite 503 → **574 collected, 569 passed, 5
  skipped, 1 warning** (the new skip is the Cover file-symlink refusal, which needs a privilege
  this account lacks); theme 17/17; `verify.py` **RESULT: PASS**; `compileall` exit 0;
  `git diff --check` clean. Live Windows fixture pass on disposable generated fixtures across
  all six checks, including an injected pre-boundary failure that left the original and its
  sibling byte-identical with no temporary file left behind, and a final base tree proving the
  exception modes reserved **no** standard runs. **Pending, not claimed:** 125% scaling, live
  macOS, Phase 8 screenshots, and TTS live synthesis (untouched by this phase). Phase 6 is not
  started.
- 2026-08-03 — v0.6.0 Drop 2 (Plan 2) **Phase 4 — standard output integration across all six
  tools** (HOME-PC). Stopped first at the §G blocker (the drop never rules on Cover Image's
  already-shipped destructive `Overwrite original files` checkbox during migration) and resumed
  on the maintainer's **Option A** ruling: keep it visible but disabled, captioned "available
  in a later update", with `var_overwrite` forced `False` **and** the captured worker parameter
  a literal `False`, so re-enabling the widget alone cannot reach the source-side branch.
  Migrated all six tools to `<output base>/<Tool>-Outputs/<Tool>-N/`, reserved atomically at
  **validated operation start** — five panels previously picked a `Downloads/<Tool>-N` number
  at `build_ui()` time and froze it for the session. Every output-producing action reserves its
  own run: MP3 Tool's combine, time-edit and ID3 are three, as are the editor's Write Tags,
  Clear All Tags and Remove Series Numbering. All destinations now go through the shared batch
  planner, central sanitiser, containment and input-protection checks. Removed the per-tool
  output Browse controls (they would bypass the configured base; the base is managed in
  Preferences & Data and the Maker's opt-in custom destination is Phase 5), moved MP3 combine
  staging from `edited_mp3s-N` beside a user-chosen path into the run, and replaced M4B Maker's
  local sanitise regex with the central one. **Two real bugs:** the migration *closed* a silent
  overwrite — `avoid_input_overwrite()` guarded only against writing onto an input, so two
  same-named imports from different folders overwrote each other in three tools — and it
  *introduced* one, an orphaned `stem` reference that made every conversion fail with
  `name 'stem' is not defined`; **every planner-level test passed**, and only driving the real
  worker on a generated fixture caught it, so the suite now runs the actual Converter,
  time-edit and Cover workers. Retired `next_available_folder`/`BASE_OUTPUT_DIRNAME` outright;
  `next_output_dir` and `avoid_input_overwrite` stay as documented dormant API with a test
  proving nothing shipped calls them. Added `test_tool_output_integration.py` (68 tests) and
  updated the Plan 1 editor surface lists, the copy-only collision assertions (now the approved
  `stem-1.ext`) and the inverted Phase 3 scope guards. Suite 439 → **503 collected, 499 passed,
  4 skipped, 1 warning**; theme 17/17; `verify.py` **RESULT: PASS**; `compileall` exit 0;
  `git diff --check` clean. Live Windows fixture pass with real ffmpeg and PIL across all six
  tools on a temporary base — every source byte-identical, nothing written beside a Cover
  source, validation failure creating no run. **Pending, not claimed:** 125% scaling, live
  macOS, Phase 8 screenshots, and TTS live synthesis (needs network/model). Added the README
  output-location note. `version.py` still `0.5.1`; `config-template.toml` untouched. Phase 5
  is not started.
- 2026-08-03 — v0.6.0 Drop 2 (Plan 2) **Phase 3 — shared output reservation, collision and
  mirroring services** (HOME-PC). Added `shared/output_paths.py`: the platform-neutral
  foundation for `<base>/<Tool>-Outputs/<Tool>-N/`, built and exhaustively tested but
  **consumed by nothing**. Planning is pure and materialisation explicit — only
  `ensure_output_base()` and `reserve_run_directory()` create anything, and only directories.
  `TOOL_OUTPUT_PARENTS` derives the six parent folders from the existing `paths.TOOL_SLUGS` so
  a slug is never written down twice, and an unknown tool key raises rather than becoming a
  path fragment. Reservation uses `mkdir()` **without** `exist_ok` as the race boundary with no
  prior existence check — proven by an 8-thread barrier test giving eight distinct directories
  numbered 1–8 — bounded, diagnosable, returning a frozen `RunReservation` that carries the
  run's configuration snapshot; `release_if_empty()` removes a reserved directory only while it
  is still empty. Sanitisation reduces a path to its last component, strips control characters
  and trailing dots/spaces (Windows drops those on write, which would silently merge two names),
  replaces the forbidden set, normalises to NFC, defuses reserved device names with or without
  an extension, and truncates to 255 characters keeping the extension; only the **final** suffix
  counts as the extension, so `Book 1.5 - Extras.m4b` keeps its title. Collisions try the
  requested name then `stem-1.ext`/`stem-2.ext` through a per-run `DestinationPlanner` that
  combines disk state with already-planned names and compares case-insensitively on every
  platform (both shipping targets are case-insensitive; an extra `-1` beats an overwrite).
  Safety adds containment that handles non-existent children, link refusal, input-equality and
  source-tree protection, all raising typed errors with a message/detail split, and **nothing in
  the module deletes anything**. Planning provides flat (Decision 31A — no parent trees
  recreated), one-root mirrored, and multi-root with collision-safe containers (`Books`,
  `Books-1`). **Three findings recorded:** a junction escaping the root is caught by containment
  rather than the link check (`resolve()` follows it), while a junction pointing *back inside*
  the root passes containment and is caught only by `assert_no_link_in` — both defences are
  needed and both now have tests; Windows reports `<tmp>/NUL` as existing because the OS
  resolves the device name, which is the very hazard the sanitiser defuses; and directory-link
  tests run via `mklink /J` junctions, which need neither Developer Mode nor elevation, so link
  safety got real coverage instead of a blanket skip. Marked `paths.next_output_dir()` as a
  compatibility wrapper scheduled for Phase 4 removal — **behaviour unchanged** — with a test
  recording the exact five call sites so a sixth fails and Phase 4's removals are visible.
  Suite 295 → **439 collected, 435 passed, 4 skipped, 1 warning**; theme suite 17/17 executed;
  `verify.py` **RESULT: PASS**; `compileall` exit 0; `git diff --check` **completely clean**.
  The one new skip is the file-symlink test (`WinError 1314`, no privilege on this account),
  named and **not** claimed as passed. No tool panel or the launcher imports the new service, no
  current output behaviour changed, no cleanup exists, `version.py` is still `0.5.1`, and
  `config-template.toml` was never touched. Phase 4 is not started.
- 2026-08-03 — v0.6.0 Drop 2 (Plan 2) **Phase 2 — Preferences, warning presentation, and Reset
  Preferences** (HOME-PC). Ran the identifier integrity check first: the garbled
  `output_barectory` from the pasted summary **does not exist anywhere in the repository**;
  `output_base_directory` (settings key) and `output.base_directory` (TOML key) are used
  consistently in all 11 places, so no correction was needed. Added
  `shared/preferences_ui.py` — a non-modal, single-instance Preferences & Data dialog plus the
  once-per-launch warning window — and wired a `Preferences & Data…` status-bar entry point
  into all three launcher shells (ACT ghost button on Windows, native `ttk.Button` on aqua and
  classic) with `Ctrl+,` / `Cmd+,` bound on every platform. The dialog is presentation only:
  styles come from `_style()`, which returns `""` where `theme["styles"]` is absent, so the
  Windows build is fully `ACT.*` and the macOS build fully native **from one code path with no
  `sys.platform` branch**. It shows the effective output base and its source, validates through
  the Phase 1 rules (absolute or `~` only; relative and environment-variable forms rejected),
  creates no folder, saves atomically, reloads the snapshot immediately, and keeps every raw
  traceback out of the GUI while logging the detail. Reset Preferences confirms, clears mutable
  settings only, refreshes the fields, and reports failure honestly. Clear Downloaded Data is a
  visibly disabled placeholder with **no command at all**, AST-asserted alongside "no
  shutil/subprocess/os import and no rmtree/unlink/remove/Popen call". Moved the once-per-launch
  guard into `config.take_launch_warning()` (with `reset_launch_warning_guard()` for tests) so a
  reload storm cannot become a dialog storm and the contract is assertable headlessly.
  **Two real defects found and fixed while building:** `settings.set()`/`update()` left the
  in-memory cache ahead of the file after a failed atomic write (now rolled back, which is what
  makes "the previous setting is still in use" true); and the dialog measured **689 px tall
  under the Windows theme** against the app's own `920×600` minimum while the unstyled build was
  556 px, so a fit test exercising only the unstyled bundle had passed and hidden it — fixed by
  layout (Entry/Browse/Save on one row, Reset on its heading row, tighter outer padding) to
  **618×596 Windows / 630×488 unstyled**, and the fit test now asserts the Windows path
  explicitly. Retargeted `test_repository_contract.py`'s Phase 1 "no GUI surface" guard to the
  new phase boundary rather than deleting it: the launcher may name Preferences, but is
  AST-checked to define no cleanup function and call nothing destructive. Suite 230 → **295
  collected, 292 passed, 3 skipped, 1 warning**; theme suite 17/17 executed; `verify.py`
  **RESULT: PASS**; `compileall` exit 0; `git diff --check` **completely clean**. Live Windows
  manual pass at 1920×1080 / 100% scaling against the real launcher with settings redirected to
  a temp file — every check green. **Pending, not claimed:** 125% scaling (needs the maintainer
  to change the display setting), live macOS (explicit deferral), and screenshot evidence
  (Phase 8 owns the matrix). No tool-output behaviour changed, no cleanup exists, `version.py`
  is still `0.5.1`, and `config-template.toml` was never touched. Phase 3 is not started.
- 2026-08-03 — v0.6.0 Drop 2 (Plan 2) **Phase 1 — canonical-file gate and configuration core**
  (HOME-PC). Four files added, eight modified, none deleted or renamed. Added the committed
  root `config.toml` (written from the plan, never from the maintainer's unrelated
  `config-template.toml`) and `shared/config.py`: one typed, immutable `EffectiveConfig`
  resolved as **code defaults → valid `config.toml` → allowlisted mutable overlay**, with
  per-key validation so one bad value never discards a good neighbour, safe fallback for a
  missing or malformed file, unknown keys aggregated into one diagnostic, `Diagnostic` records
  separating the human-readable message from the technical detail, and deterministic
  `get_effective()` / `reload()` / `invalidate()`. Standard-library `tomllib` only — **no new
  dependency**. The overlay allowlist is exactly one key (`output_base_directory`); existing
  user state got no invented TOML counterpart. Output bases: empty means
  `~/Downloads/Audiobook-Creation-Tool-Outputs`; non-empty must be absolute or `~`-based; a
  relative path is **rejected** rather than resolved against the cwd; environment variables are
  **never** expanded. Extended `shared/settings.py` with `reset()`, bool write results,
  `last_load_error()` and a `use_path()` injection seam — a malformed file is never rewritten
  during a load. Routed log retention through `logging.max_sessions` with the config import
  **inside** `configured_max_sessions()` so retention can read config while config never reads
  logging, falling back to 30 on any failure. **Fixed the Phase 0 casing defect the right way:**
  `verify.py` now reads `Changelog.md`, and its new `docnames` check compares real directory
  entries (`os.listdir`) instead of `Path.exists()`, so the NTFS case-insensitivity that hid the
  bug cannot hide it again; a new `config` check fails on any diagnostic from the committed
  file. Other active references corrected in `README.md`, `Briefing.md` and `release.py`;
  archived release-history notes, the protected `don't-delete/` references and this file's own
  Plan 1 history were left historical on purpose. Added 133 tests across
  `test_repository_contract.py` (40), `test_config.py` (68) and `test_settings.py` (25), all on
  temporary directories and injected paths — the suite never touches the maintainer's real
  settings, Downloads, logs, outputs, `.venv` or model cache, and it proves the gate *fails* on
  a missing canonical file, every alias, a deleted permanent reference, an invalid config,
  version drift and malformed TOML. Suite 97 → **230 collected, 227 passed, 3 skipped, 1
  warning**; theme suite 17/17 executed; `verify.py` **RESULT: PASS** across five checks;
  `compileall` exit 0. `git diff --check` reports only the inherited CRLF markdown condition —
  zero new whitespace errors in any `.py` or `.toml`. **No GUI or tool-output behaviour
  changed**, `shared/paths.py`, `launcher.py` and all six tool panels are untouched, and
  `version.py` is still `0.5.1`. Phase 2 is not started.
- 2026-08-03 — v0.6.0 Drop 2 (Plan 2) **Phase 0 — reorientation, repository invariants and
  baseline evidence** (HOME-PC). Read `AI-WORKSPACE.md`, the four permanent `don't-delete/`
  planning references, the four canonical docs, and the active drop in full, then inspected the
  whole implementation surface read-only. Fetched `origin` with `--no-prune`, which moved
  `origin/master` `1da1e54…` → `bada8a3…`; commit-by-commit inspection showed the two new
  commits are the maintainer's GitHub-web documentation recasing (`CHANGELOG.md`/`DECISIONS.md`/
  `handoff.md` → `Changelog.md`/`Decisions.md`/`Handoff.md`) plus the three permanent
  `md-instructions/don't-delete/` references — no source, test or screenshot touched.
  Verified by `git merge-base --is-ancestor` that `origin/master` contains the Plan 1 merge
  `86933e6…`, the Plan 1 feature head `f3d70e8…` and the old local head `1da1e547…`, then
  fast-forwarded local `master` with `--ff-only`. The FF was initially blocked because three
  `don't-delete/` files sat untracked in the worktree; each was proved **byte-identical** to
  the incoming blob with `git hash-object` (`7bd35c2`, `b4979cf`, `8076626`), backed up to the
  session scratchpad, removed, and re-verified identical after the FF wrote them — no user
  content was altered or lost. Created
  `feature/0.6.0-drop2-config-output-maintenance-foundation` from the verified `master`
  (the branch existed neither locally nor on `origin` beforehand; nothing was overwritten).
  Baseline: 97 collected, **94 passed / 3 skipped / 1 warning**, 17 theme tests all executed,
  `verify.py` `RESULT: PASS`, `compileall` exit 0, `git diff --check` clean — identical to the
  Plan 1 closeout baseline, so the merge and rename cost no tests. Recorded (and deliberately
  did **not** fix) the `scripts/verify.py:34` `CHANGELOG.md` casing defect, proving it is
  masked only by NTFS case-insensitivity. Audited installed skills: `audio-processing` will be
  used, `fullstack-bridge-sync` is not applicable, `.codex/skills/` does not exist.
  **No production code changed**; the commit carries the two authorized planning artifacts plus
  this file and the master index. The unrelated untracked root `config-template.toml` was left
  untouched. Phase 1 is not started and awaits explicit maintainer approval.
- 2026-08-02 — v0.6.0 Drop 1 **APPROVED and CLOSED OUT — Plan 1 is complete** (HOME-PC
  session; final per-phase commit on the implementation branch). The maintainer replied
  `APPROVED` to the ten-image matrix and the functional evidence, with ten explicit
  decisions recorded in the Phase 6 section: the matrix is approved as-is; the 125% images
  shot on the secondary display are valid evidence with no reshoot required; the current
  Summary/Details specimen is sufficient; `MIN_SIZE` and `DEFAULT_GEOMETRY` stay unchanged
  and the M4B Converter clipping defers to that panel's Plan 9 conversion; DPI-unawareness
  does not block approval but must be recorded prominently as unresolved Windows work and
  must not be fixed during closeout; live macOS remains an approved deferral that is never
  to be called passed; **tkinter/ttk is approved as the continuing toolkit**; the five
  classic panels defer to Plan 9; Plan 2 is the next planning target. Phase 6 is
  **documentation-only** — `git diff --name-only b2e809f..HEAD -- scripts/ files/` is empty.
  `Briefing.md` gained the Windows design system, the `ACT.*` isolation contract (including
  *why* it is structural — ttk has no style inheritance, so a panel naming no style resolves
  the generic one and stays native), the conversion boundary, the editor's presentation
  fork, the Shared-Metadata-is-visual-only statement, the developer-only specimen, three new
  known limitations, and a standing non-Windows preservation contract naming the four tests
  that hold it. `CHANGELOG.md` gained three entries **beneath** the existing `[Unreleased]`
  heading — **no v0.6.0 release heading was created and no release is claimed**.
  `DECISIONS.md` gained one newest-first signed ADR recording the approved contract, the
  evidence path and Phase 5 SHA `b2e809f`, why ttk stays (with an explicit "do not propose a
  toolkit change" note to future sessions), macOS/Linux preservation, and the three
  deferrals. `README.md` and `AI-WORKSPACE.md` are deliberately unchanged, `version.py` is
  still `0.5.1`, and `scripts/requirements.txt` was never touched in the whole drop. The
  temporary drop `md-instructions/0.6.0-drop1-windows-ui-prototype.md` was **deleted**, as
  the workflow requires; it was tracked, so the plan text stays recoverable from any
  Phase 0–5 commit. All eighteen Definition-of-Done items are satisfied, with the single
  deferral (live macOS) explicitly approved rather than assumed. Verification unchanged from
  baseline: focused 17 / 11 / 7 / 12 / 12, full suite **94 passed, 3 skipped**, `verify.py`
  **RESULT: PASS**, `compileall` exit 0, `git diff --check` clean, all 17 theme tests
  executed, ten PNGs still present and untouched. **Nothing was merged to `master`**, the
  feature branch was not deleted, no release work was done, and **Plan 2 is neither drafted
  nor started.**
- 2026-08-01 — v0.6.0 Drop 1 **Phase 5 evidence captured; STOPPED at the hard visual
  gate** (HOME-PC session; per-phase commit on the implementation branch). The ten-image
  matrix required by §10 now exists under
  `files/UI-Prototype-Screenshots/v0.6.0-drop1/`, with the plan's exact filenames, in two
  **true** Windows display-scaling passes at 1920×1080 — Windows did the scaling, not Tk's
  internal scaling, not a resized window, not an enlarged image. Scaling was verified per
  pass by reading `GetDpiForMonitor(MDT_EFFECTIVE_DPI)` from a `PER_MONITOR_AWARE_V2`
  process: 96 (100%) on the primary and 120 (125%) on the secondary. Images 1–2 are the
  shipped `LauncherApp` with nothing added; 3–4 are the shipped launcher hosting the
  shipped editor with the developer fixture's canned books and controlled busy state
  applied through the editor's own public methods; 5 is the fixture's Summary/Details
  sheet, which carries its own on-screen presentation-only disclaimer. `USERPROFILE` was
  pointed at `C:\Users\Public` for the captures so no username, real path or real
  audiobook title appears in any image — the paths are still computed by the shipped code.
  **The finding of the phase: the application is DPI-unaware** — `GetProcessDpiAwareness`
  returns `UNAWARE`, and neither the venv's `python.exe`/`pythonw.exe` nor the base
  Python 3.12.10 they copy carries a `dpiAware` manifest, and `pythonw.exe` is what the
  setup launcher runs. So at 125% Windows bitmap-scales the entire window: text is soft
  rather than re-rendered at 120 DPI, but by the same token **nothing clips, overlaps or
  reflows**, and the 125% geometry is byte-identical to 100% at 1024×720 and 920×600
  (only the maximized logical window shrinks, 1920×1009 → 1536×793, so the editor's form
  viewport falls 615 → 399 px and scrolls more). Not fixed: DPI awareness is a production
  behaviour change and Phase 5 is evidence-only, so it is raised at the gate as a
  decision. The carried-forward M4B Converter clipping at the 920×600 minimum was
  re-measured at both scalings and is unchanged (19 px action, 108 px + 75 px Log); the
  recommendation is to leave `MIN_SIZE` and `DEFAULT_GEOMETRY` alone because the clipping
  is in a panel Plan 9 will rebuild and the converted editor clips nothing anywhere. The
  visual comparison against `files/UI-Current-Screenshots/` is written up in the Phase 5
  section: card hierarchy replacing a flat labelframe stack, a distinct Shared Metadata
  surface, a real primary/destructive/neutral action hierarchy, an accent progress line, a
  navigation rail whose active row stays keyboard-reachable instead of being disabled, and
  a header strip that names the active tool. One honest limitation on the specimen: a
  notebook shows one pane at a time, so the Details pane's content is not visible in either
  specimen image. **No production source changed** — `scripts/` and `files/tests/` are
  byte-identical to Phase 4 HEAD `9d4f58c`, `version.py` is still `0.5.1`. Verification is
  unchanged from the Phase 4 baseline: focused suites 17 / 11 / 7 / 12 / 12, full suite
  **94 passed, 3 skipped**, `verify.py` **RESULT: PASS**, `compileall` exit 0,
  `git diff --check` clean; all 17 theme tests executed and the Tk skip transient did not
  recur. **Nothing is approved.** The permanent docs are deliberately untouched and the
  plan file is not deleted; Phase 6 cannot start until the maintainer replies `APPROVED`
  or `CHANGES REQUESTED`.
- 2026-08-01 — v0.6.0 Drop 1 **Phase 4 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Regression hardening, and the headline is what did *not*
  happen: **no production-source change**. The plan permits a source edit only for a
  genuine regression caused by Phases 1–3, and the audit plus the functional matrix
  found none, so the only file added is `files/tests/test_prototype_regression.py`
  (12 tests). **Whole-diff audit** of `1da1e547..d8d0b1b` at the definition level rather
  than by reading the diff: in `m4b_metadata_editor.py`, 46 definitions are
  byte-identical to master and exactly three changed (`__init__`, `_build_ui`,
  `build_ui`); `_build_ui_classic` is statement-for-statement master's `_build_ui` minus
  its two trailing state syncs, which moved to the dispatcher and now run for both
  forks. In `ui_theme.py`, `_apply_darwin`, `_apply_classic`, `enable_mousewheel` and all
  five `ProgressIndicator` methods are byte-identical; only `apply_theme` changed, by the
  addition of the `win32` arm. In `launcher.py`, `TOOLS`, `select_tool`,
  `_load_tool_into`, `_build_ui_classic` and `_build_ui_darwin` are byte-identical; the
  aqua arm of `_highlight_selection` and the whole body of `_show_load_error` were moved
  verbatim, not rewritten. Zero `option_add` anywhere; all 34 hex literals live in
  `_WINDOWS_COLORS` and neither `launcher.py` nor the editor contains one; `metadata.py`,
  `paths.py`, `settings.py`, `cancellation.py`, `requirements.txt`, `version.py`, both
  setup launchers and the five other tool modules are untouched. **Section 11 matrix**
  ran against the real launcher and the real editor with scripted dialogs, on generated
  ~3.4 KB M4B fixtures in the scratchpad (the real library files are 0.5–3 GB and the
  matrix copies every input again): dialog cancel, file-list operations, shared/varies
  prefill, chapter paging, Safe Save, both Clear All Tags confirmation choices, both
  Remove Series Numbering choices, Cancel mid-run over 400 inputs, the controlled error
  path, and launcher lifecycle afterwards — **all pass**, with source SHA-256 verified
  unchanged at seven checkpoints and `settings.json` byte-restored. The cancel run is the
  one worth naming: pressed 400 ms in with 8 files done, the in-flight file finished, 391
  later files stopped, every partial output was a complete copy, all 400 inputs were
  byte-identical, and the next run after it completed normally. **Two corrections to the
  Phase 3 record**, both honest rather than convenient: the two forks are not attribute-
  identical (Windows names one extra label, `lbl_chap_hint`, that nothing reads), and the
  editor's form does **not** fit without scrolling when maximized (1083 px wanted against
  a 615 px viewport). Tests 82 → **94 passed, 3 skipped**; `verify.py` **PASS**;
  `compileall` exit 0; `git diff --check` clean. The Phase 3 Tk skip transient **did
  recur once** (one run of `77 passed, 20 skipped` — `test_ui_theme.py`'s 17 tests
  skipping on a transient `tk.Tk()` failure) and would not reproduce in 22 further
  runs, 16 of them deliberately re-creating the trigger; it is logged as an environment
  transient, not accepted as coverage, and the pre-existing guard was left alone per the
  plan. Live macOS remains **deferred**, with the exact five-step smoke test now written
  down. Stopped at the Phase 5 gate.
- 2026-07-31 — v0.6.0 Drop 1 **Phase 3 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Converted the **Windows M4B Metadata Editor** — the only
  tool panel this plan may ever convert — and built the visual specimens.
  `m4b_metadata_editor.py` now forks on `theme["mode"]`: `_build_ui_windows()` draws four
  titled cards (Audiobook Files, Shared Metadata, Chapter Titles, Output) in a scroll
  region, with an action bar and a Log that never scroll away; `_build_ui_classic()` is
  the old layout kept byte-for-byte for macOS and Linux/other. **Both forks create the
  same widgets and attributes**, so every callback, worker, queue pump, busy/idle
  transition, Cancel path and copy-only write below the builders is shared code that
  cannot tell them apart — no metadata, output, threading or cancellation behaviour was
  touched. `build_ui(parent)` is unchanged; it gained an optional, backwards-compatible
  `theme=None` parameter (the launcher still calls it with one argument).
  **Shared Metadata** groups every batch-wide field on the Phase 1 accent surface. Every
  one of those fields already applied to every loaded file, so the card states existing
  behaviour visually — it adds no precedence, disables no field, and implements nothing
  from Plan 6/8. **Summary/Details is deliberately NOT in the runtime editor** (that
  would be a non-functional control in a user-facing panel); it is a component sheet in
  the new developer-only fixture, labelled in its own text as presentation-only with no
  filtering/ETA/Retry/Pause-Resume — all Plan 3.
  `files/tests/manual_windows_ui_prototype.py` is the fixture: not pytest-collectable,
  not in `launcher.TOOLS`, not under `scripts/`, patches nothing (it drives the editor's
  own public methods with canned in-memory data), and touches no file on disk. All four
  isolation properties are asserted by a test.
  **The approved `sidebar_width` 232 → 180 shipped with it** and gave every tool panel
  +52px of width back: content host 669×457 → **721×457** at the minimum and 773×577 →
  **825×577** at the default. Widest nav row is 115px in a 160px interior, so the rail is
  still comfortable. **Half the Phase 2 regression is fixed and half is not, and the
  split is exactly width vs height:** at 1024×720 M4B Converter's `Convert M4Bs → MP3s`
  row and Log are fully visible again (measured, mapped, inside the host); at the 920×600
  minimum they are still clipped by ~19px and ~110px, because that deficit is vertical
  and `MIN_SIZE`/`DEFAULT_GEOMETRY` were left alone per the maintainer's decision.
  Tests: new `test_m4b_metadata_editor_ui.py` (12), `test_ui_theme.py` 16 → 17,
  `test_launcher_smoke.py` 10 → 11, full suite 68 → **82 passed, 3 skipped**.
  `ui_theme.py` gained four styles only — `ACT.Shared.TFrame`, `ACT.Shared.TLabel`,
  `ACT.SharedSecondary.TLabel`, `ACT.Shared.TCheckbutton` — so the Shared Metadata
  surface has its own frame/label/toggle family instead of borrowing the "muted" one,
  whose token merely happens to be the same colour today. `launcher.py` was **not**
  edited. Draft review at 1024×720 / 920×600 / maximized, including a measured 31-stop
  Tab loop with no trap (scratchpad images, not committed).
- 2026-07-31 — v0.6.0 Drop 1 **Phase 2 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Converted the **Windows launcher shell only**:
  `_build_ui_windows()` in `launcher.py` builds a dark navigation rail, a header strip
  naming the active tool, a framed content card and a status bar with a focusable
  "Open log folder" button — all from `theme["styles"]` / `theme["colors"]` /
  `theme["metrics"]`, so not one hex literal or magic number entered `launcher.py`.
  `shared/ui_theme.py` was **not** edited: the Phase 1 API (41 styles + `style_tk_widget`)
  covered the whole shell, which is the strongest evidence the design system is right.
  `files/tests/test_launcher_smoke.py` grew from 1 test to 10.
  **The isolation trick that matters:** `self.content` and every per-tool container are
  left as *plain, unstyled* `ttk.Frame`s. ttk has no style inheritance, so an unconverted
  panel resolves the generic `TFrame`/`TButton`/`TEntry` exactly as it does on master —
  the shell cannot leak into a panel even in principle, because there is nothing to
  inherit from. The card border is a 1px hairline frame wrapped *around* the host rather
  than a style *on* the host, which is what buys the border without giving the host a
  style. Verified in the running app: zero of the panels' widgets carry an `ACT.*` style
  while every non-empty style in the shell itself is `ACT.*`.
  Two behaviour changes, both deliberate and both improvements: the active nav row is
  marked with the ttk `selected` flag instead of being *disabled* (so it stays reachable
  by Tab and keeps its focus ring), and the log-folder action became a real `ttk.Button`
  instead of a clickable label (focusable, fires on Enter/Space). The action itself,
  `_open_logs`, is unchanged.
  **Regression found and escalated rather than papered over:** the new shell costs the
  tool panels 127px of width and ~100px of height against the classic shell (110px of
  that is the 232px `sidebar_width` token). At the 920×600 minimum the M4B Converter's
  `Convert M4Bs → MP3s` row and Log box fall outside the visible area, where on master
  they fit. I reclaimed everything reclaimable inside `launcher.py` (card padding
  `content_pad` → `gap_sm`, +16w/+12h) and stopped there: the two real levers are
  `sidebar_width` and `MIN_SIZE`, both in `shared/ui_theme.py`, and both are maintainer
  value/geometry decisions under plan §7.1–§7.2 — not a "missing primitive" this phase
  was authorized to add. Full numbers, per-panel overflow, and three costed options are
  in *Phase 2 limitations* above. Worth noting for context: M4B Converter, MP3 Tool and
  M4B Maker already overflow at 920×600 on master, so this makes an existing condition
  worse rather than creating a new class of bug.
  Draft visual review done at 1024×720, 920×600 and maximized 1920×1009 on this machine
  (scratchpad images, not committed — the ten-image 100%/125% matrix is Phase 5).
- 2026-07-31 — v0.6.0 Drop 1 **Phase 1 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Built the isolated Windows design system in
  `shared/ui_theme.py` and extended `files/tests/test_ui_theme.py` from 5 tests to 16.
  **Converted nothing** — the launcher and all six panels are untouched, and a live
  style audit through the real `LauncherApp` proves it (297 widgets, every one with an
  empty style string; generic ttk styles still resolve to the native vista values).
  Key engineering decision: keep `vista` as the base theme and clone the recolorable
  `clam` elements into it under an `ACT.` prefix, because vista's native parts ignore
  colour options and a global switch to `clam` would have restyled the five panels this
  drop must not touch. Probed the actual Tk 8.6 build in the repo venv to confirm
  `element create … from clam` works for all 28 required elements before writing any
  production code. Every style variant gets an explicit layout, otherwise ttk resolves
  e.g. `ACT.Primary.TButton` down to the native `TButton` and the dark fill silently
  does not stick — that trap is documented in the module and in Current Focus above.
  Also added `style_tk_widget()` as the single sanctioned way to colour `Canvas` /
  `Listbox` / `Text`, so no panel ever carries its own hex literal.
  **Diagnostic-notice investigation** (requested before editing): the two earlier IDE
  notices — "70 new diagnostic issues in 1 file" and "26 new diagnostic issues in 1
  file" — were **Markdown editor-linter notices, not Python or source errors**. They
  fired while `md-instructions/handoff.md` and the drop plan were being written in
  Phase 0 (line-length / list-spacing style rules). `mcp__ide__getDiagnostics` now
  reports **zero** diagnostics for the whole workspace, including
  `handoff.md`, the drop file and `shared/ui_theme.py`, and
  `python -m compileall scripts files/tests` exits 0 with no output. No baseline source
  problem exists and nothing was broadened to "fix" them.
  Results: focused theme suite 16 passed; launcher smoke 1 passed; metadata shared
  7 passed; full suite 59 passed / 3 skipped / 1 warning; `verify.py` **RESULT: PASS**;
  `git diff --check` clean. `requirements.txt`, `version.py` (still `0.5.1`), both setup
  launchers and every tool module are unchanged. Stopped at the Phase 2 approval gate.
- 2026-07-31 — v0.6.0 Drop 1 **Phase 0 complete** (HOME-PC session; committed and pushed
  on the implementation branch per the plan's per-phase commit contract, which
  supersedes the v0.5.0-only one-commit-per-drop rule). Read order completed first:
  AI-WORKSPACE.md, Briefing, CHANGELOG, DECISIONS, handoff, the full drop file, and
  `.claude/skills/audio-processing/SKILL.md` (present and read; `fullstack-bridge-sync`
  inspected and correctly not applicable — no backend/frontend contract work here).
  Worktree protection: the checkout carried an unstaged deletion of
  `md-instructions/Instructions_Template.md` plus untracked `Map-Repo-Structure.bat`,
  `REPO-STRUCTURE.md`, and the new drop file. All four were copied to a scratch backup
  **before** touching git; nothing was reset, discarded, stashed, or overwritten. The
  incoming history deleted `Instructions_Template.md` itself (`9dcf49c`), so the
  fast-forward absorbed the local deletion with a zero net diff, and `220b6dc`/`65d3855`
  added `.gitignore` rules that now cover both convenience tools — `git check-ignore`
  confirms `Map-Repo-Structure.bat` (line 75) and `REPO-STRUCTURE.md` (line 59).
  Sync: `git fetch --prune` then `git pull --ff-only origin master` — 10 commits,
  `695045c..1da1e54`, strictly fast-forward (verified with `git merge-base --is-ancestor`
  before pulling). Start SHA `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318` **equals** the
  plan's planning-audit baseline, so no drift analysis was needed; the incoming diff
  was the v0.5.1 Jenny line, the 8 `files/UI-Current-Screenshots/` images, gitignore
  hardening, and docs. Branch `feature/0.6.0-drop1-windows-ui-prototype` cut from the
  updated master. Baseline (all with the repo venv, Python 3.12.10, **no source
  edits**): focused suites 5 / 1 / 7 passed; full suite 48 passed, 3 skipped;
  `scripts/verify.py` → **RESULT: PASS**; `git diff --check` clean. Six-tool manual
  baseline driven on a real Tk window through the real `LauncherApp`: 6/6 registered in
  order, zero error panels over two full passes, container identity stable (build-once
  proven), a state marker survived switch-away/back, `last_tool` round-tripped, 1.601 s
  build-all, window `1024x720`/minsize `(920,600)`. Pre-prototype Windows theme contract
  captured verbatim (`mode="classic"`, vista, Segoe UI, `colors=None`, `metrics=None`) —
  that `None` pair is the Phase 1 target. **Nothing was converted, restyled, or
  redesigned.** Limitations recorded above rather than glossed: no eyes-on visual check,
  no live macOS, and the `md-instructions/` case-rename left alone because `verify.py`
  hard-codes `CHANGELOG.md` and this drop may not weaken or edit the gate. Next: Phase 1
  (Windows design primitives only) — **awaiting explicit user approval**. — Claude Code
- 2026-07-19 — Batch-timing-parity drop ABANDONED + Jenny addition shipped to branch
  (MacBook session). Maintainer listened to all six Phase-3 A/B pairs: the rewritten
  batch engine, despite median-gap parity within −22…0 ms, sounded subjectively worse
  than the original chunk method — full working-tree revert ordered and executed
  (nothing was ever committed). Surgical handling: voice_registry.py hand-reverted
  (batch_timing_preset field, effective_preset(), _batch_override(), six overrides
  and Phase-3 comments removed; Jenny's entry restored verbatim to her original
  addition incl. original comment); test_tts_smoke.py kept the 12/7 counts but lost
  the effective_preset contract test; plain `git checkout` (diffs verified pure
  Phase-2/3 first) for batch_convert.py (banner fix reverted with it),
  epub2tts_gui.py, epub2tts_edge.py + runner.py (rate kwarg), and
  test_batch_convert_folders.py (back to the original 5 fake-synth tests);
  batch_convert_child.py + batch_timing_harness.py deleted; batch-baselines/ +
  phase3-listen/ investigation data deleted (Jenny's pre-drop samples kept);
  Instructions_Template.md restored from HEAD (deleted only as a side effect of
  drop-file creation — same precedent as Drop 3). Docs: DECISIONS do-not-retry ADR;
  CHANGELOG revert note + 0.5.1 entry; Briefing pause-fields accuracy fix + version
  line; version.py 0.5.0 → 0.5.1; drop file batch-timing-parity.md deleted last.
  verify → RESULT: PASS. Committed as ONE commit on new branch `add-jenny-voice`
  (Jenny addition + docs/version + revert record), pushed to origin; master
  untouched — maintainer does the Windows verify + merge. — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 3 DONE (MacBook session; no commit per
  drop). Per-path presets prototyped per maintainer option (a): registry field
  `batch_timing_preset` (partial dict, None default) + `effective_preset(v, mode)`
  merge helper + `_batch_override()` factory; GUI `_on_voice_selected` now loads
  the effective preset for the current mode and both mode radios re-invoke it
  (lambda for late binding — the radios are built before the handler exists).
  Harness renders batch with the effective batch preset and records the merged
  preset in its JSON. Tuning: two measured iterations (first pass undershot
  medians ~45 ms — the trim residual measured at presets 780–820 shrinks at
  340–640, so Phase-2's implied values were systematically tight); final values
  land every non-Jenny voice within −22…0 ms of its old-batch ch1-1 median.
  Title/chapter batch overrides = 0 (beyond the maintainer's given sentence
  numbers, flagged): the old batch never inserted them, and with 0 the title gap
  is the voice's natural residual — intro title gaps landed within 5–64 ms of old
  batch for five voices (Steffan +113, his residual runs long), trails within
  ±60 ms. Choppiness check for the low-preset voices (AndrewM 423 / Andrew 410 /
  AvaM 373 / Ava 344): new minimum gaps are HIGHER than old batch's own natural
  minimums (e.g. Ava 375 vs 218, Steffan 363 vs 232) — the preset acts as a floor;
  remaining sub-200 ms gaps are comma-scale, present in old batch too. No numeric
  sign of clipping; agent cannot literally listen — old-vs-new A/B samples for all
  six voices staged in files/livid-lady-test-files/phase3-listen/ for the
  maintainer's ear gate. Tests: new per-path merge + single-file-verbatim contract
  test in test_tts_smoke (50 passed / 3 skipped); verify RESULT: PASS. — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 2 DONE (MacBook session; no commit per
  drop). Engine change per the Phase-1 decision: `convert_single_pdf` rewritten to
  spawn `batch_convert_child.py` (new, ~68 lines) via `shared.subprocess_utils.popen`
  — child installs the no-window guard + configure_pydub + ensure_punkt itself
  (fresh process), turns SIGTERM into SystemExit so the engine's finally cleans its
  temp dir, renders into a private absolute dir under `.tmp_chunks/<tmp_key>`
  (existing orphan-cleanup covers it), prints `BATCH_CHILD_SAVED::` on success;
  parent moves `<stem> (<voice>).mp3` onto the mirrored target. Cancel: parent polls
  cancel_check every 0.5 s and terminate()s the child (grace 10 s then kill) — faster
  than the old between-chunk checkpoint; per-PDF retry loop unchanged around the
  spawn; network retry lives in the engine (run_edgespeak 3×, finer than the old
  per-chunk retry); per-file progress_report unchanged; child stdout pumped on a
  thread, only retry/error-ish lines forwarded (log stays as quiet as the old
  pipeline), full tail kept for failure messages; `-X utf8 -u` on the child guards
  the cp1252-console issue (Open Issues #2 class). `run_batch_convert` gained
  mp3_bitrate + 7 optional pause kwargs (None → engine defaults, engine stays the
  single source of truth). GUI: pause_kw now built for batch too (validation dialog
  now also fires on bad pause fields at batch start — new, correct) and passed with
  bitrate into run_batch_convert; Kokoro single/batch paths untouched. Harness
  updated to pass each voice's preset pause fields (same mapping as the GUI) and
  self-describe the engine in its JSON. Tests: fake seam moved from
  synthesize_chunk_mp3 to `_delegate_to_child`; same five scenarios preserved
  (same-stem test no longer needs fitz — parent never parses PDFs) + new
  pause-threading, engine-defaults, and cancel tests (5→8). Proofs: single-file
  intro render on new code millisecond-identical to reference (20.215 s /
  961-942-949 ms gaps); live workers=2 batch 2/2 mirrored, 0 orphans; cancel drill
  clean; verify RESULT: PASS (49/3). Measured new engine on all 7 voices × 2
  sources → phase2-newengine.json; conflict numbers recorded in Current Focus.
  — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 1 DONE (MacBook session; no commit per
  drop). Traced GUI batch invocation: in batch mode `pause_kw` is never built
  (epub2tts_gui.py:462 gates it on mode=="single"); Edge batch receives only
  speaker/rate/workers/resume, though every pause Tk var is readable on the main
  thread at start_job — threading them through is pure plumbing. Kokoro batch is an
  inline GUI loop (lines ~534–649), not `run_batch_convert` — out of blast radius.
  Chose subprocess-per-file delegation after disproving in-process thread delegation
  live (chdir race: 2/2 runs failed — `sntnc*.mp3` written/read across the wrong tmp
  dirs, CouldntDecodeError, one thread's finally-chdir targets a dir the other
  rmtree'd) and sizing the chdir-free refactor as too invasive (~30 bare relative
  filenames in read_book/make_mp3/make_m4b). Prototype (scratchpad) proved the
  delegated shape: child renders to a private absolute dir, parent moves
  `<stem> (voice).mp3` to the mirrored target; workers=1 real PDF + workers=2 nested
  same-stem TXT tree both correct, cwd stable, delegated gaps == single-file
  reference (961/942/949 ms). Built `scripts/Universal/tts/batch_timing_harness.py`
  (renders via the real `convert_single_pdf`, measures gaps with pydub at
  −50 dBFS/150 ms, writes JSON) and captured baselines: 7 Edge voices ×
  {00-intro, 03-ch1-1} → batch-baselines/phase1-baseline.json; variance run shows
  Edge is deterministic (±2 ms), so ±25 ms tolerance is real. Surprise flagged: batch
  medians (Steffan ~770, Jenny ~1000, Andrew ~452 ms) sit far from single-file
  measured gaps at the same presets (Steffan ~951 ms), so Phase 3's "match old batch"
  and "don't change single-file" conflict under one shared preset — maintainer input
  needed on resolution (per-path preset values vs. accepting single-file cadence in
  batch). verify → RESULT: PASS. — Claude Code
- 2026-07-08 — UX-progress drop Phase 5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). Maintainer
  approved the Phase-4 metadata layout visually (scroll, larger Log, description,
  progress). Close-out gates: full suite 46 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Windows/classic proof: launcher
  constructed under a win32 stub scoped to ui_theme's sys reference (a global
  sys.platform stub breaks stdlib shutil — same technique as the UI-shell drop):
  theme mode "classic", family "Segoe UI", colors/metrics None, 6 plain ttk.Button
  sidebar entries, all six tools built through the real LauncherApp with zero error
  panels, settings.json snapshot/restored. Docs: CHANGELOG [Unreleased] gained the
  UX-progress Added + Changed entries; Briefing updated (ui_theme bullet gains
  ProgressIndicator, worker/data-flow bullet gains the progress-marshaling rule,
  metadata-editor bullet gains the scroll layout + 14-row Log); DECISIONS gained
  the progress-placement + Maker-indeterminate ADR; handoff (this file — focus,
  work log, sync log). Awaiting maintainer final sign-off and the single drop
  commit; the maintainer deletes the drop file at commit time (or asks for it to
  be deleted then). — Claude Code
- 2026-07-08 — UX-progress drop Phases 1–4 done; STOPPED at the Phase-4 visual gate
  (MacBook session; no commit — no .git here). Phase 1 re-run after a context clear:
  confirmed no prior Phase 2/3/4 work existed on disk before starting. Phase 2:
  `ProgressIndicator` in shared/ui_theme.py + test_ui_theme.py test. Phase 3 per tool —
  M4B Converter/Cover Image: existing queue "progress" payload widened to (done, total),
  bar swapped for the indicator (determinate, per file/image); M4B Metadata: same for
  all three workers (save / clear-tags / remove-numbering; determinate per file);
  M4B Maker: indeterminate during the single concat/encode, 1/1 on success (old bar was
  dead — value 0 until one end-jump; dead "progress_max" pump branch removed);
  MP3 Tool: new indicator + queue kinds — combine determinate per track in SAFE
  normalize, indeterminate "Concatenating…" during FAST/final concat, time-edit + ID3
  determinate per file; TTS: indicator beside Start/Cancel, Edge/Kokoro batch per-file
  counts, Kokoro single per-chunk and Edge single per-paragraph via new additive
  progress_callback=None params (kokoro_synth.py, epub2tts_edge.py read_book,
  runner.py) — defaults keep all non-GUI callers byte-identical in behaviour. All
  updates flow worker→queue→main-thread drain (same path as each Log box); Cancel and
  Log wiring untouched on every tool. Phase 4: metadata editor scroll canvas mirroring
  the TTS wiring exactly, Log 8→14 rows fixed below the scroll area, launcher
  description de-staled. Gates: compileall clean; suite 46 passed / 3 skipped
  (test_launcher_smoke builds all 6 tools); real-Tk behavioural check of the new
  layout (canvas window, %d Leave bind, log row, busy/idle toggle) passed. NOT done
  (deliberate): Phase 5 close-out — waits for the maintainer's visual sign-off on the
  metadata editor. — Claude Code
- 2026-07-08 — Component-verify drop Phases 4–5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). **Phase 3 gate:**
  maintainer listened to all 11 samples and approved. **Phase 4 (per-tool live pass) —
  PASS:** all six tools exercised end-to-end on macOS under the new Finder shell and
  confirmed working by the maintainer (screenshots reviewed): TTS Audiobook (Edge +
  Kokoro voices, pause-timing fields effective, panel scrolling works), M4B Converter,
  MP3 Tool, M4B Maker, Cover Image, M4B Metadata Editor (Drop 2 shared-metadata
  pre-fill + "(varies)" + Open Folder…). No macOS-specific breakage found — zero code
  changes, so no new regression tests were needed. Caveat recorded everywhere: the M4B
  Converter ran against a standard AAC-LC M4B; the `aac_at` xHE-AAC/USAC decode path is
  still unverified on macOS (no USAC sample on hand). **Phase 5 (close-out):** full
  suite 45 passed / 3 skipped; `python scripts/verify.py` → RESULT: PASS. Docs:
  CHANGELOG [Unreleased] component-verify Verified entry; Briefing macOS-live-pass
  known-limitation bullet retired (replaced by the narrow xHE-AAC-on-macOS residual,
  folded into the Windows xHE-AAC bullet) + High-Level State notes the macOS live pass;
  handoff (this file — focus, open-issues note, work log, sync log). Open Issues #1 was
  already closed 2026-07-07; no DECISIONS ADR needed (no new aac_at/MPS decision arose —
  decoder selection pre-existed in ffmpeg_utils.py). Awaiting maintainer sign-off and
  the single drop commit. — Claude Code
- 2026-07-08 — Component-verify drop Phases 1–3 (MacBook session; no commit — no .git here).
  **Phase 1 (kickoff gates) — PASS:** venv Python 3.12.13; edge-tts 7.2.8 imports;
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`; real `.command` fast-path launch OK
  (Kokoro health-check ok, GUI detached, launch log clean); test instance closed (a
  pre-existing maintainer launcher window from 04:03 was left running). **Phase 2 (§2.4):**
  treated as CLOSED per maintainer — fixed 2026-07-07 in bootstrap.py (environmental: 3.13
  venv; now forced 3.12), `kokoro_synth._get_pipeline` untouched; only the health check was
  re-run. **Phase 3 (voice samples):** `tts/generate_voice_samples.py` run on macOS →
  11/11 OK (6 Edge + 5 Kokoro) in `files/test-for-manual-listen-elmatthe/`. STOPPED at the
  maintainer manual-listen gate; Phase 4 (per-tool live pass) starts only after sign-off.
  — Claude Code
- 2026-07-08 — Wheel/trackpad scroll fix + UI-shell drop Phase 5 close-out (MacBook
  session; maintainer approved the Finder look first; no commit — maintainer makes the
  single drop commit after live-testing scroll). **Scroll fix:** the TTS options panel
  never scrolled on wheel/trackpad (only scrollbar drag worked) — pre-existing bug in
  SHARED code, so the fix improves Windows and macOS alike. Root cause: the wheel
  handler was armed by Enter/Leave on `options_canvas`, but the form frame covers the
  canvas, so the canvas Enter almost never fired. New
  `shared.ui_theme.enable_mousewheel(scroll_target, hover_region)` binds Enter/Leave
  on the panel's wrap frame instead and ignores Leave-with-detail-NotifyInferior
  (pointer into a child = still inside the panel). CRITICAL non-obvious bit: tkinter's
  bind() never delivers the crossing detail (`%d` absent from `Misc._subst_format_str`
  — verified live on Tk 9.0.3), so the Leave side is a Tcl-level bind; see the
  2026-07-08 DECISIONS ADR before "simplifying" it. `epub2tts_gui.py` now calls
  `enable_mousewheel(options_canvas, hover_region=canvas_wrap)` (old inline handler
  removed). All-scrollers sweep: every other scroller (M4B Converter / MP3 Tool /
  M4B Maker / Cover Image / M4B Metadata Listbox + Text/ScrolledText widgets) already
  scrolls natively via Tk class bindings — verified live with synthetic MouseWheel
  events — so NONE needed the helper; none were touched. Verified end-to-end on the
  real TTS panel (real Tk): Enter-on-wrap arms bind_all, wheel over a child Entry
  scrolls the canvas, Leave(NotifyInferior) keeps the binding, real Leave unbinds;
  same flow re-proven under the classic/win32 path (ui_theme-scoped platform stub —
  stubbing sys.platform globally breaks stdlib shutil) incl. Windows ±120 deltas.
  **Phase 5:** `test_ui_theme.py` gained the headless-guarded `enable_mousewheel`
  wiring test (asserts Enter/Leave bound + Tcl-level %d on the Leave script; wheel
  motion itself can't be simulated headless). Full suite 45 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG (UI shell Added + scroll
  Fixed), Briefing (GUI/launcher/shared bullets + macOS-live caveat narrowed to the
  per-tool matrix), DECISIONS (aqua-vs-clam ADR deferred from Phase 3 + wheel-binding
  ADR). Drop file NOT deleted, nothing committed — both deliberate, awaiting the
  maintainer's live scroll test and single drop commit. — Claude Code
- 2026-07-08 — macOS UI-shell drop Phases 1–4 done (MacBook session spanning the
  07-07→07-08 midnight; no commit — awaiting maintainer UI review before Phase 5).
  **Phase 1** — AI-WORKSPACE.md → HOME-MacOS filled from the real machine: root
  `~/Desktop/Coding_Repositories` (claude-skills-main inside it, no MyProjects split),
  MacBook Pro 14" M4 Pro (14c) · 24 GB · macOS Tahoe 26.5.2 · 1 TB (~466 GB free),
  user `elijahmatthew` = Administrator (sudo w/ password), brew python@3.12+3.13 with
  Tk, default python3 = 3.13.7; noted TCC blocks agent shells from listing ~/Desktop.
  **Phase 2 (baseline launch gate) — PASS**: deleted `.venv`, invoked the real
  `.command` via Finder-equivalent `open`. First-run setup: correct 3.12 base chosen
  (the §2.4 fix working), venv built, all pinned deps installed, ffmpeg on PATH,
  Kokoro model + voices ready (setup_2026-07-07.log, run marker 23:48:28). Caveat:
  the setup window's final auto-launch step wasn't observed (window was closed
  on-screen right at the end — agent shells here have no Accessibility permission,
  so the "Begin Setup" click and window handling happened at the physical machine);
  launch itself was then proven via the `.command` fast path: Kokoro health-check ok,
  GUI on screen detached, Terminal auto-closed promptless, session log clean.
  Health: edge-tts 7.2.8 imports, kokoro_is_healthy → (True, 'ok'), 11 voices
  (6 Edge + 5 Kokoro). Logs: files/runtime-data/logs/{setup_2026-07-07.log,
  launch_2026-07-07.log, launch_2026-07-08.log}.
  **Phase 3** — `scripts/Universal/shared/ui_theme.py` added (apply_theme(root, style)
  → fonts/colors/metrics dict). Research done live on this Mac (Tk 9.0.3): native
  `aqua` chosen over Finder-styled clam (native controls in all six panels, auto
  dark-mode — this Mac runs dark mode; aqua can't recolor native ttk buttons, so the
  sidebar chrome uses classic tk widgets); fonts via `.AppleSystemUIFont` (SF Pro
  Text/Display are NOT installed font families on Tahoe), fallback Helvetica Neue;
  macOS semantic system colors + computed blends (alpha colors flatten in Tk).
  DECISIONS.md ADR deferred to Phase 5 per drop. win32/other branch reproduces the
  old look byte-identically (vista/Segoe UI; clam/TkDefaultFont). Headless-guarded
  `files/tests/test_ui_theme.py` added (3 tests: current platform, stubbed win32
  values, stubbed linux) — pass.
  **Phase 4** — launcher.py wired to ui_theme.apply_theme(); `_build_ui` split into
  `_build_ui_classic` (old body verbatim — Windows tree unchanged) and
  `_build_ui_darwin` (Finder shell: tinted source-list sidebar w/ hover +
  accent-selection rows + emoji glyphs, toolbar strip naming the active tool +
  description, hairline-bordered content card, refined status bar w/ system link
  color). `build_ui(parent)` contract, lazy build-once/show-hide, last_tool restore,
  load-error panel, `_on_close` all untouched; the six tools' internals untouched
  (only launcher.py edited + ui_theme.py/test added). Verified: compileall clean;
  test_launcher_smoke (6/6 tools through the real LauncherApp on the new shell) +
  test_ui_theme pass; scoped win32-stub constructs the classic layout (6 ttk
  buttons); darwin behavioral check (selection/hover/toolbar/build-once) pass; real
  `.command` fast-path launch with the new UI confirmed on screen and left open for
  review. NOT done yet (deliberately): Phase 5 bug hunt, full verify.py run, doc
  close-out, DECISIONS ADR, drop-file deletion, commit. — Claude Code
- 2026-07-07 — §2.4 Kokoro-on-macOS root-caused and FIXED (MacBook session; no commit —
  maintainer reviews first). Live diagnosis: `.venv` was Python 3.13.7 (the Mac's only
  Python — no python3.12 anywhere), and the setup log showed pip skipping kokoro
  (`markers 'python_version < "3.13"' don't match`) then every self-heal repair dying on
  "No matching distribution found for kokoro==0.9.4" (newest 3.13-compatible release on
  PyPI is 0.7.16). ENVIRONMENTAL — `kokoro_synth.py` untouched. Three `bootstrap.py`
  changes: `_is_kokoro_compatible()` helper (single source of the >=3.10,<3.13 range);
  `run_setup` now calls `install_python` when the found interpreter is >=3.13 and only
  keeps it if 3.12 truly can't be installed (logs "Edge TTS works, Kokoro voices
  disabled"); `_create_validated_venv` rmtree-rebuilds an existing >=3.13 venv when the
  chosen base is <3.13 (closes the "bad venv reused forever" gap). Windows path
  unaffected (`py -3.12` is found directly, branches never fire). Verified live: brew
  python@3.12 + python-tk@3.12 installed, old venv deleted, full headless setup → venv
  Python 3.12.13, ssl=True tkinter=True, kokoro==0.9.4 installed,
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`. New test
  `files/tests/test_bootstrap_python_version.py` (7 params over the version gate,
  pure logic). `python scripts/verify.py` → RESULT: PASS (41 passed, 3 skipped).
  Docs: CHANGELOG macOS-verify entry, DECISIONS ADR, Open Issues #1 closed. — Claude Code
- 2026-07-07 — Drop 3 complete — DROP 3 DONE (no commit yet — maintainer reviews then
  makes the single drop commit). Per `drop3-plan.md` (deleted on close-out):
  **Phase 1** — batch Kokoro now passes `end_silence_ms=end_pause` (was baking the 3000 ms
  default); `chunk_pause_ms=50` kwarg anchor confirmed pre-existing, untouched.
  **Phase 2.1** — `paragraph_pause` hoisted on the main thread next to `end_pause`
  (never read Tk vars off-thread) and passed as `chunk_pause_ms` into BOTH the
  single-file and batch `kokoro_file_to_mp3` calls. Sentence/title/chapter parity
  deliberately deferred — ADR added to DECISIONS.md.
  **Phase 2.2** — `run_batch_convert` + the GUI Kokoro batch now mirror each source's
  path relative to the input dir under the output dir (same-stem files in different
  subfolders no longer overwrite); Resume checks the mirrored target; per-file temp
  chunk dirs keyed off the relative path (they collided on stem too); flat inputs
  keep the exact old flat layout. **Phase 2.3** — batch discovers `.txt` alongside
  `.pdf` on both engines; `.txt` is read directly (PDF extractor bypassed — the GUI
  Kokoro `_do_one` needed the same suffix branch, a necessary deviation from the
  plan's "label + glob only" wording since `pdf_to_txt` would fail on `.txt`);
  labels updated. **Phase 2.4** — BLOCKED (see Open Issues #1): needs a real Mac.
  **Phase 3.1** — `tts/generate_voice_samples.py` added per plan verbatim (only
  change: removed the plan's unused `import tempfile`); output folder gitignored;
  live run 11/11 voices OK. **Phase 3.2** — 8 new tests in
  `test_batch_convert_folders.py` (5: mirroring / same-stem PDFs via fitz / txt
  bypasses extractor / flat regression / mirrored resume; fake `synthesize_chunk_mp3`,
  no network) + `test_kokoro_timing_wiring.py` (3: fake `_get_pipeline`; duration
  deltas prove `end_silence_ms`/`chunk_pause_ms` are applied). **Phase 3.3** — Edge
  pause scaling verified live (small 10 269 ms vs large 23 769 ms — scales, no
  escalation needed). Extra live QA: real-model Kokoro single-file (chunk 200→2000 ms
  = exactly +1800 ms; end 0→3000 ms = exactly +3000 ms) and a real-Tk GUI smoke
  driving the actual panel (batch radio → voice combobox event → spinboxes → Start)
  over nested txt+pdf with same-stem books: mirrored tree, no collisions, 4/4 outputs.
  Gates: compileall scripts/Universal + files/tests clean; `python scripts/verify.py`
  → RESULT: PASS (34 passed, 3 skipped; 1 pre-existing pydub audioop warning).
  Docs: CHANGELOG Drop 3 entries, Briefing TTS bullet, DECISIONS pause-mapping ADR.
  — Claude Code
- 2026-07-07 — Drop 2 Phase QA + close-out complete — DROP 2 DONE (no commit yet —
  maintainer reviews then makes the single drop commit). `files/tests/
  test_jack_ryan_final_product.py` added (env-gated on JACK_RYAN_M4B_FOLDER; `_m4bs()`
  guards the unset var at collection time so verify/CI skip cleanly — agreed deviation
  from the drop's verbatim code). Run against the real fixtures: **14/14 PASS, zero
  findings** (all 12 books: title, author, cover, titled chapters, integer parts, one
  consistent series name) — no Open Issues row needed. Unit tests
  `test_m4b_metadata_editor_shared.py` added (7 tests: shared/varies, missing key,
  album-implied, series_part display-only, unreadable-file exclusion, empty list,
  strip-compare). Gates: compileall scripts/+files/tests clean; full suite 26 passed /
  3 skipped (the one warning is the pre-existing pydub audioop deprecation, not Drop 2);
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG [Unreleased] Drop 2 entry;
  Briefing metadata-editor bullet updated. Drop file `0.5.0-drop2-metadata.md` deleted.
  — Claude Code
- 2026-07-07 — Drop 2 Phase 3 complete (no commit — one-commit-per-drop rule).
  `btn_add_folder` added to the `disable_inputs` widget set. Smoke vs the real fixture
  tree (real UI instance, real `read_m4b_tags`, dialogs injected): Harry Potter 7 files →
  artist 'J.K. Rowling' + series 'Harry Potter' pre-filled, Title blank; Shadow Slave /
  Supreme Magus / Noble Queen also share Genre 'Web Novel'; Dungeon Crawler 8 files OK;
  Jack Ryan OUTER folder → "No audiobooks found" box (subfolder hint shown), list
  unchanged; Jack Ryan INNER folder → 12 files, Tom Clancy + 'Jack Ryan' shared;
  single-file pre-fill unchanged (title + per-file readback w/ source atom); empty
  folder → info box, list unchanged. series_part never pre-filled anywhere. Next:
  Phase QA (Jack Ryan inspection test) + unit tests + verify + docs. — Claude Code
- 2026-07-07 — Drop 2 Phase 2 complete (no commit — one-commit-per-drop rule). Added
  "Open Folder…" button + `add_folder()` (non-recursive .m4b/.m4a/.mp4; "No audiobooks
  found" box now explicitly says subfolders aren't searched — the drop's Jack Ryan
  caveat); `_refresh_mode` n>1 branch now calls `_prefill_shared(n)` (shared values
  pre-filled + snapshotted into `_prefill`, mode line names shared fields,
  `_batch_series_readback` summarises series identical/varies/none). Docstrings
  corrected vs the drop verbatim: module + `_prefill_shared` now state that shared
  NON-series fields left unedited ARE written on Save (byte-identical rewrite —
  maintainer ruling), only series keys are preserve-by-default. Verified via real Tk
  instance w/ monkeypatched `_tags_for`: shared artist/genre/series pre-fill; differing
  title blank; series_part never pre-filled; `_collect_tags` excludes unedited shared
  series but includes shared artist; varies read-back correct; empty-list mode label
  intact. py_compile clean. Next: Phase 3 (disable-state + manual smoke). — Claude Code
- 2026-07-07 — Drop 2 Phase 1 complete (no commit — one-commit-per-drop rule). Per
  `0.5.0-drop2-metadata.md`: added `self._tag_cache` to `__init__`, new `_tags_for()`
  (cached, fault-tolerant read — a failing file is logged and excluded, never aborts) and
  `_shared_tags()` (shared/varies across all readable files; `series_part` display-only;
  album-implied series treated as absent) in `m4b_metadata_editor.py`; cache cleared in
  `clear_list()` and `remove_selected()`. Purely additive — nothing calls the helpers yet.
  Two agreed deviations from the drop's literal anchors: new methods inserted after the
  complete `_prefill_from` body (the drop's mid-method anchor would break the file), and
  (upcoming, QA phase) `_m4bs()` will guard the unset env var at collection time.
  Maintainer rulings recorded: continue on `restructure-v0.5.0` atop unmerged Drop 1;
  NO `album_artist` row this drop; NO preserve-by-default for shared non-series fields
  (`_collect_tags` untouched). Verified: py_compile clean; `_shared_tags` on a stub —
  empty list → `({}, set())`; 3 files sharing artist w/ differing titles + album-implied
  series → `({'artist': 'X'}, {'title', 'series'})`. Next: Phase 2 (folder picker +
  batch wiring). — Claude Code
- 2026-07-07 — Phase 6 complete — DROP 1 DONE (no commit yet — maintainer reviews then makes
  the single drop commit). Bug hunt: whole-tree grep for stale tokens (`scripts\shared`,
  `resources\logs|bin|models|settings`, `Windows\...`, `MacOS\...`, `setup_and_run`) —
  remaining hits only in CHANGELOG history (preserved verbatim by design), handoff's own
  migration map, and files/release-history snapshots; live code + launchers + tests are clean.
  README repo-describing sections updated to the new layout (structure diagram, one-tree
  design note, files/bin ffmpeg path, release-build command; install steps use the new
  launcher names with "(named setup_and_run.* in the v0.4.0 zip)" parentheticals; v0.4.0
  download links kept per maintainer Q9). release.py dry run: both v0.5.0 zips built, exit 0,
  archive root = README + correct launcher only, zero runtime/test leaks, .command packaged
  0o755. Final gates: compileall scripts/ + files/tests clean; verify.py → 19 passed,
  RESULT: PASS. Deleted scratch REPO-STRUCTURE.md + Map-Repo-Structure.bat + the drop file
  `0.5.0-drop1-restructure-and-docs.md`. Root now: README, AI-WORKSPACE.md, two Setup_and_Run
  launchers, scripts/, files/, md-instructions/ (+ gitignored .venv/ + dist/). — Claude Code
- 2026-07-07 — Phase 5 complete (no commit — one-commit-per-drop rule). Root launchers
  git-mv-renamed to the exact maintainer-specified names
  `Setup_and_Run-audiobook-creation-tool.bat` / `.command` and rewired: no more `cd` into
  Windows/-MacOS/ (cd to repo root), BOOTSTRAP → scripts/Universal/shared/bootstrap.py,
  log-path messages → files/runtime-data/logs/. Preserved verbatim: Windows pythonw
  no-console fast path, macOS Gatekeeper/App-Translocation guard (sibling marker changed
  from MacOS/ to scripts/ — same logic + message), foreground --launch-only +
  close_terminal.py Terminal auto-close, Tk-capable-Python probe + Homebrew repair +
  headless fallback, winget Python install path. Kokoro install logic untouched (Drop 3).
  Verified live: bootstrap --self-test all green on the new layout (venv valid at root,
  requirements found, HF_HOME → files/runtime-data, kokoro health ok, launch target =
  scripts/Universal/launcher.py); real double-click path via the renamed .bat launched the
  GUI detached under pythonw (launch log in files/runtime-data/logs/, no crash output);
  test instance closed. — Claude Code
- 2026-07-07 — Phase 4 complete (no commit — one-commit-per-drop rule). scripts/verify.py
  stood up from verify-template (project name set; deps check made PEP-508-marker-aware so
  `kokoro==… ; python_version < "3.13"` / `audioop-lts==… ; python_version >= "3.13"` don't
  false-fail the operator regex — the pin rule applies to the spec before ';'). pytest==9.1.1
  added to scripts/requirements.txt and installed in the venv. files/tests/ suite written:
  conftest (import-root bootstrap) + launcher build-all smoke (all 6 tools through the real
  LauncherApp, error-panel monkeypatch, settings.json snapshot/restore) + per-tool
  behaviour-preservation smokes (tts voice registry 11-voice contract + pdf_to_txt on a
  generated PDF; mp3_tool hms/concat-escape/next-folder; m4b_maker natural sort/title
  normalization/ffmetadata chapters/concat quoting; m4b_converter sanitize_filename;
  cover_resizer letterbox+crop+ext-fallback+next_version_path via real PIL; shared.metadata
  ffmpeg args/header lines/freeform namespace/ABS series-atom constants). No network anywhere.
  One test expectation corrected against real behaviour (normalize_title: first `_` becomes
  the colon before the possessive rule can see it). `python scripts/verify.py` → 19 passed,
  RESULT: PASS. — Claude Code
- 2026-07-06 — Phase 3 complete (no commit — one-commit-per-drop rule). Briefing.md rewritten
  to current state per the template (architecture, all 6 tools, new layout, known limitations;
  old v0.1–0.3 status stack dropped — that history lives in CHANGELOG + files/release-history).
  CHANGELOG: prior [Unreleased] items (console-flash fix, test-fixture history scrub) folded
  into a new [0.5.0] - 2026-07-06 entry along with the restructure/Added-verify entries
  (explicitly "no user-facing tool changes"); fresh empty [Unreleased] on top; ALL prior
  history preserved verbatim. DECISIONS.md seeded with the drop's four ADRs + the
  runtime-data-layout ADR (+ the earlier commit-policy ADR). Instructions_Template.md written
  (project-tailored, uses <angle> slots so verify's [bracket] scan can't false-positive).
  version.py → 0.5.0; README status line → short v0.5.0-in-development note, v0.4.0 download
  links kept (maintainer Q9). .claude/CLAUDE.md + .codex/CODEX.md created pointing at
  AI-WORKSPACE.md with the kickoff read order and the no-per-phase-commit rule. — Claude Code
- 2026-07-06 — Phase 2 complete (no commit — one-commit-per-drop rule). Executed the full
  migration map: git mv Windows/scripts → scripts/Universal (git recorded all as renames —
  history preserved); requirements → scripts/requirements.txt (header de-Windows-ified);
  Dockerfile + v0.3.1 one-shots → files/{,release-history}; test_kokoro_voices.py →
  files/tests/; deleted mp3_tools_launcher.py + tts/setup_env.py + entire MacOS dupe tree.
  Untracked moves: settings.json/models/huggingface → files/runtime-data/, harness MP3s →
  files/test-logs/kokoro-voices/, test-files → files/test-files/, Windows/.venv → root .venv
  (old resources/logs discarded — runtime-generated). Rewired paths.py + bootstrap.py to
  REPO_ROOT derivation (RESOURCES_DIR → files/runtime-data, BIN_DIR → files/bin, VENV_DIR →
  root .venv, REQUIREMENTS → scripts/requirements.txt); removed the OS_ROOT alias everywhere;
  kokoro_synth HF fallback now walks to the repo root (scripts/+files/ present); release.py
  reworked for the single-tree layout (both zips = README + OS launcher + scripts/**);
  updated all stale resources/-and-setup_and_run docstrings. .gitkeep in scripts/{Windows,
  MacOS} so the empty OS dirs survive clone. Verified: compileall clean; headless build-all
  6/6 tools, no error panels, 1.35 s; all derived paths print correct new locations; moved
  venv works (Python 3.12.10). Old Windows/ + MacOS/ trees deleted. — Claude Code
- 2026-07-06 — Phase 1 complete (no commit — maintainer's one-commit-per-drop rule, see
  DECISIONS.md 2026-07-06 entry; applies to the whole v0.5.0 sequence). Rewrote .gitignore to
  the final layout (`.venv/` root, `files/bin/`, `files/runtime-data/`, `files/test-files/`,
  any-depth `test-logs/`; dropped all Windows/-MacOS/-prefixed rules); verified with
  `git check-ignore -v`. Created files/ skeleton (tests, release-history,
  runtime-data/{logs,models}, bin). DECISIONS.md created early with the standing commit-policy
  decision. Next: Phase 2 (the big migration). — Claude Code
- 2026-07-06 — Phase 0 complete. Committed pending console-flash fix + AI-WORKSPACE.md on
  master (`e80ba7f`); cut branch `restructure-v0.5.0`; re-ran Map-Repo-Structure.bat and
  reconciled the migration map (this file) against the fresh tree + all nine maintainer
  answers. Baseline recorded: `compileall` clean on both trees (venv Python 3.12.10); headless
  launcher build-all via the real `LauncherApp` = 6/6 tools built, zero error panels, 4.32 s.
  This is the known-good bar for every later phase. Next: Phase 1 (skeleton + .gitignore).
  — Claude Code
- 2026-07-06 — Session kickoff: read AI-WORKSPACE.md, both Briefing/CHANGELOG copies (verified
  byte-identical Win↔Mac), the three v0.3.1 one-shots, and the full Drop 1 instruction file.
  Confirmed version state: version.py/README = 0.4.0, CHANGELOG top release [0.4.0], tags
  v0.1.0–v0.4.0 incl. v0.3.1 (`49bb51a`). — Claude Code

---

## Session Sync Log (newest first)

### 2026-08-15 — HOME-PC — v0.6.1 Plan 4 Phase 9 — committed and pushed to `feature/0.6.1-tts-cover-workflows`

**Branch:** unchanged. **Phase 9 start SHA:** `ce6e62bcd4e0060786259c68f9d1c5c5b9c1c97b` (the
maintainer-approved Phase 8 commit, equal to its upstream at start; 11 ahead / 0 behind `master`).
No fetch, merge, reset, stash, rebase, force-push or `git clean`; `master` was not touched and
remains `809a43e754920fce2f11f08e3c401dcc4c7a5223`.

**Files added (1):**
- `files/tests/test_chatterbox_evaluation.py` — 71 tests. The evaluation mode and its opt-in flag,
  the closed four-voice set, the approved sentence byte-for-byte, the four exact output names, the
  single output root, the rejection of `tests/samples/voice_eval/`, exactly four generations, the
  hash-mismatch hard stop, delegation of reference preparation to the engine, conditional reuse,
  WAV writing at the model's own rate, four-row reporting with failures included, per-voice
  performance, the protected-folder boundary, and the registry / GUI / Phase 10 boundaries.

**Files changed (3):**
- `scripts/Universal/tts/generate_voice_samples.py` — the `--chatterbox-eval` mode: the approved
  text and voice IDs, `_chatterbox_eval_dir()`, `ChatterboxEvalResult`,
  `run_chatterbox_evaluation()` (two stages: prove all four sources, then generate),
  `format_chatterbox_table()`, `_report_chatterbox_evaluation()`, `_build_parser()`. Edge and
  Kokoro behaviour is byte-for-byte unchanged.
- `scripts/Universal/tts/chatterbox_synth.py` — three narrow additions: `synthesize_text_to_wav()`,
  `generation_defaults()`, and the manifest now recording the conditional cache path and being
  refreshed on every `prepare_reference_clip` call rather than only on a rebuild.
- `files/tests/test_chatterbox_boundaries.py` — the boundary moved from "Phase 9 has not started"
  to "Phase 10 has not started": one parametrize entry swapped and two guards retargeted. **No test
  removed; the file's collected count is unchanged.**
- `md-instructions/Handoff.md` — this entry, the Current Focus rewrite recording the maintainer's
  Phase 8 approval, and the Phase 9 work-log section.

**Not staged, by design (all provably ignored):** the four evaluation WAVs under
`files/test-for-manual-listen-elmatthe/chatterbox-eval/`, the four derivatives and the manifest
under `files/runtime-data/chatterbox/reference-clips/`, the four conditionals under
`…/chatterbox/conditionals/`, the model cache, the probe venv, and the four protected source MP3s
(zero tracked, re-hashed byte-identical after all synthesis). `git add -f` was not used.

**Gates:** 3341 passed, 13 skipped, 1 warning (3354 collected, +71 on the Phase 8 baseline, zero
removed); `verify.py` **RESULT: PASS**; `compileall` exit 0; `git diff --check` and
`git diff --cached --check` clean.

**State:** Phase 9 is at its **hard stop**. The maintainer has not listened. **Phase 10 is not
authorized and has not started.** No merge, tag, release, packaging or VERSION bump; the branch is
retained and the drop is not retired.

### 2026-08-15 — HOME-PC — v0.6.1 Plan 4 Phase 8 — committed and pushed to `feature/0.6.1-tts-cover-workflows`

**Branch:** unchanged. **Phase 8 start SHA:** `c368542af9c158652da9a94db7f58619fa4fb6af` (the
approved Phase 7 commit, equal to its upstream at start). No fetch, merge, reset, stash, rebase,
force-push or `git clean`; `master` was not touched and remains
`809a43e754920fce2f11f08e3c401dcc4c7a5223`.

**Files added (5):**
- `scripts/Universal/tts/chatterbox_synth.py` — the engine module: availability seams, reference
  resolution with per-use SHA-256 verification, deterministic derivative preparation, cached
  conditionals, `cuda → mps → cpu` selection, the single first-load allowance, and the
  Kokoro-shaped worker entry points.
- `files/tests/test_chatterbox_requirements.py` — 44 tests. The dependency contract asserted by
  parsed value, including the setuptools compatibility pin and the absence of any CUDA or git source.
- `files/tests/test_chatterbox_engine.py` — 69 tests. Lazy import, missing package, missing and
  mismatched references, write refusal into the protected folder, derivative identity, audio
  preparation (mono / 24 kHz / leading window / cover-art exclusion / source untouched /
  deterministic), the conditional cache, device selection, the first-load allowance, and the
  file-synthesis contract.
- `files/tests/test_chatterbox_bootstrap.py` — 31 tests. Repair set, health probe, self-heal,
  pre-download, warm-up, the opt-in checkbox, and startup safety.
- `files/tests/test_chatterbox_boundaries.py` — 37 tests. The twelve existing voices by value, and
  the Phase 9/10 boundary.

**Files changed (5):**
- `scripts/requirements.txt` — the setuptools step-back and the pinned Chatterbox stack.
- `scripts/Universal/shared/bootstrap.py` — the Chatterbox counterparts of the Kokoro helpers.
- `scripts/Universal/tts/voice_registry.py` — `BACKEND` widened, `_chatterbox_preset` added, **no row**.
- `files/tests/test_epub_retirement.py` — three inventory updates, none weakened: the guard list
  gains `tts/chatterbox_synth.py` (putting the new module *in* scope for every EPUB guard),
  `REQUIRED_IMPORTS` gains `"chatterbox"`, and the tracked `setuptools` pin becomes `80.9.0`.
- `files/tests/test_tts_jobs.py` — **one test retargeted, none deleted.**
  `test_no_dependency_was_added_for_this_phase` asserted that `chatterbox` / `resemble-perth` /
  `torchaudio` were absent, which was Phase 7's boundary; Phase 8 is the authorized phase that adds
  exactly those. It is renamed to
  `test_the_only_engine_dependency_added_since_is_the_authorized_one` and now requires the three to
  be **present** while still forbidding a second engine, a CUDA pivot and any unpinned source — a
  stronger guard, not a weaker one. The GUI-side boundary test beside it is untouched and still
  forbids all Chatterbox vocabulary in the panel.

**Files deliberately NOT changed:** `epub2tts_gui.py`, `batch_convert.py`, the whole
`epub2tts_edge/` package, `kokoro_synth.py`, `pdf_extractor.py`, `generate_voice_samples.py`, the
Cover Image modules, `shared/job_control.py`, `shared/job_ui.py`, `shared/cancellation.py`,
`files/tests/test_batch_convert_folders.py` and `files/tests/test_tts_reporting_order.py` — the
last two pass **unmodified**, as required. Phase 7's RunPublisher is untouched. EPUB remains
retired and its archive inert. `version.py` stays `0.5.1`.

**Nothing local was staged:** no reference MP3, derivative, conditional, model weight, HF cache
entry, benchmark audio, probe venv, clean validation venv, setup log or any other
`files/runtime-data/` file. No `git add -f`, no `git clean`.

- Note:    One commit on `feature/0.6.1-tts-cover-workflows`, pushed. `master` untouched. No AI
           co-author trailers. **Phase 9 is NOT AUTHORIZED and has NOT started.**

### 2026-08-15 — HOME-PC — v0.6.1 Plan 4 Phase 7 — committed and pushed to `feature/0.6.1-tts-cover-workflows`

**Branch:** unchanged. **Phase 7 start SHA:** `d5be8af43c1d043b6946459b3cd4cf7689dfe61d` (the
approved Phase 6 commit, equal to its upstream at start). No fetch, merge, reset, stash, rebase,
force-push or `git clean`; `master` was not touched and remains
`809a43e754920fce2f11f08e3c401dcc4c7a5223`.

**Files added (1):**
- `files/tests/test_tts_jobs.py` — **73 tests**, none skipped. Run capture, controller lifecycle,
  adapter installation and locking, direct/folder/multi-root placement, occurrence identity,
  the retry contract, item-versus-job failure, pause between source files, cancellation, resume,
  mirroring regression, the estimate, main-thread safety, engine freeze, and the Phase 8 boundary.

**Files changed (2):**
- `scripts/Universal/tts/epub2tts_gui.py` — job-control adoption, occurrence-keyed destinations,
  the `_RunContext` worker body, and the retirement of the panel's own processing cancel event.
- `files/tests/test_tts_importing.py` — **nine tests rewritten in place, none deleted.** Each one
  encoded a Phase 6 processing UI that Phase 7 legitimately replaces: the drain count (now two),
  the drain's message kinds, the worker's attribute whitelist (now `{_log_q}` — strictly narrower),
  the worker's parameter shape, the three cancellation-domain tests, the checkpoint test, and the
  phase-boundary test, which was **inverted** rather than dropped: job control is now asserted
  present-and-not-reimplemented instead of absent.

**Files deliberately NOT changed:** `scripts/Universal/tts/batch_convert.py` (the existing
`out_mp3` seam sufficed), the whole `epub2tts_edge/` package, `kokoro_synth.py`, `pdf_extractor.py`,
`voice_registry.py`, `shared/*`, `mp3_tools/*`, `launcher.py`, `scripts/requirements.txt`, and
`files/tests/test_tool_output_integration.py` — the third substring guard belongs to Phase 11, so
the panel was worded to avoid its five reserved literals rather than the guard being edited.
`files/tests/test_batch_convert_folders.py` passes unmodified.

**Gates:** 3085 collected / 3072 passed / 13 skipped / 1 warning (delta **+73**, reconciling
exactly to the new module); `verify.py` → `RESULT: PASS`; `compileall` exit 0;
`git diff --check` exit 0. All four Chatterbox reference MP3s byte-identical before and after,
still ignored at `.gitignore:55`, still zero tracked matches.

### 2026-08-09 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 6 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 6 start SHA:** `52f72f0d9c53f095d76d80b560ddb6cb29fdf69b`
(the approved Phase 5 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (1):**
- `files/tests/test_job_run_results.py` — 1,022 lines, **174 tests**, none skipped. Capture and
  one-configuration-per-run, the lock derivation across every cell, item outcomes, failure
  records, the run's disposition, Retry Failed, and the boundaries.

**Files modified (4):**
- `scripts/Universal/shared/job_control.py` — +461 / −1, now 1,693 lines. `capture_run`;
  `ControlKind`, `LOCK_MATRIX`, `is_locked`, `JobAction`, `is_available`; `ItemStatus`,
  `ItemOutcome`, `RunResult`. The single deleted line is the module docstring's header. No new
  import edge: the module still imports only `shared.config`, `shared.cancellation` and
  `shared.importing`.
- `files/tests/test_plan3_boundaries.py` — +75 / −1. Four new guards: Phase 6 delivered its own
  names and no more; no output descriptor exists on any Phase 6 type; the lock matrix is derived
  and exhaustive; an item failure cannot force a job-level failure. The single deleted line is
  the shipped-tests tuple.
- `md-instructions/Handoff.md` — the Phase 6 record, the Current Focus rewrite, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row, the
  recorded start-state "Phase reached" row, two new gate rows, and the next action only.
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — status/baseline header fields.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated or restored.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files); no
  rename or recase in `git diff --name-status -M -C`.
- All **22** approved screenshots byte-identical to `origin/master` (10 drop1 + 12 drop2).
- Root `config-template.toml` absent from worktree, index and committed tree.
- `version.py` `0.5.1`; **`output_paths.py`, `maintenance.py`, `importing.py`,
  `import_coordination.py`, `cancellation.py`, `config.py`, `subprocess_utils.py`,
  `logging_setup.py`, `ui_theme.py`, `launcher.py`, `config.toml`, `requirements.txt`, both root
  launchers, all six production tool modules and every approved Phase 1–5 test file are
  byte-identical to the Phase 5 commit** (blob hashes compared).
- 36 production modules parsed with `ast`: none imports `shared.importing`,
  `shared.job_control`, `shared.import_coordination` or `shared.job_ui`.
- No dependency added; no packaging, release, tag or version change; no PR opened or merged.

### 2026-08-09 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 5 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 5 start SHA:** `418deb93c53dd759643e50d6e0b292b9138491e5`
(the approved Phase 4 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (1):**
- `files/tests/test_job_controller.py` — 1,365 lines, **173 tests**, none skipped. The snapshot
  invariants, the exhaustive eighty-one-pair transition proof, pause and resume, cancellation,
  acknowledgement, failure and completion, the concurrency races, and compatibility with the
  existing cancellation primitive in both directions.

**Files modified (5):**
- `scripts/Universal/shared/job_control.py` — +508 / −12, now 1,230 lines. `JobSnapshot`,
  `JobController`, `MAX_FAILURE_DETAIL` and `_bounded_detail`. The twelve deleted lines are
  eleven rewritten docstring lines and one widened import.
- `scripts/Universal/shared/cancellation.py` — **+37 / −0**, purely additive: the `is_cancelled`
  predicate and a docstring recording how Phase 5 extends the pattern. Nothing was removed and
  nothing changed meaning.
- `files/tests/test_plan3_boundaries.py` — +160 / −22, now 745+ lines. The pure-vocabulary list
  narrowed to `importing.py` alone so its approved no-concurrency proof survives intact; the
  job module given its own precise budget guard (one condition, one non-reentrant lock, no
  thread or queue); the cancellation guard widened to admit the additive name while pinning both
  originals; a new guard that only `job_control.py` may raise the conversion exception; a new
  guard that the pause wait carries no timeout; a new per-caller resolution check; and the
  later-phase name lists re-cut per module.
- `md-instructions/Handoff.md` — the Phase 5 record, the Current Focus rewrite, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row, the
  recorded start-state "Phase reached" row, two new gate rows, and the next action only.
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — status/baseline header fields.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated or restored.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files); no
  rename or recase in `git diff --name-status -M -C`.
- All **22** approved screenshots byte-identical to `origin/master` (10 drop1 + 12 drop2).
- Root `config-template.toml` absent from worktree, index and committed tree.
- `version.py` `0.5.1`; **`output_paths.py`, `maintenance.py`, `importing.py`,
  `import_coordination.py`, `config.py`, `subprocess_utils.py`, `logging_setup.py`,
  `ui_theme.py`, `launcher.py`, `config.toml`, `requirements.txt`, both root launchers and all
  six production tool modules are byte-identical to the Phase 4 commit** (blob hashes compared).
- 36 production modules parsed with `ast`: none imports `shared.importing`,
  `shared.job_control`, `shared.import_coordination` or `shared.job_ui`.
- No dependency added; no packaging, release, tag or version change; no PR opened or merged.

### 2026-08-09 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 4 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 4 start SHA:** `2c7844e04b1a6b4a73d358867ec5b4e883e73efa`
(the approved Phase 3 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (2):**
- `scripts/Universal/shared/import_coordination.py` — 1,474 lines. The background coordinator,
  its import-scoped cancellation, the frozen event and outcome vocabulary, and the Tk-free
  poller seam. Recorded as a deviation from §7's expected module list, with its reason.
- `files/tests/test_import_coordination.py` — 2,120 lines, **129 tests**, none skipped.
  Vocabulary, lifecycle, thread ownership, cancellation, the isolation gate, queue behaviour,
  broad-root confirmation, the captured threshold, commit coordination and revision drift, Add
  Files, shutdown, the poller, and end-to-end safety.

**Files modified (4):**
- `files/tests/test_plan3_boundaries.py` — +190 / −23, now 745 lines. The module lists widened,
  the no-thread/no-queue guard narrowed to the two vocabulary modules so its approved proof
  survives intact, the later-phase name lists re-cut per module, the Phase 3 positive guard
  grown into a Phase 4 one, and six new guards: one worker and one queue, no filesystem call at
  all, cancellation isolation, the worker never had a manager to mutate, only `_commit` appends,
  and the one-way dependency.
- `md-instructions/Handoff.md` — the Phase 4 record, the Current Focus rewrite, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row, the
  recorded start-state "Phase reached" row, two new gate rows, and the next action only.
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — status/baseline header fields.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated or restored.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files); no
  rename or recase in `git diff --name-status -M -C`.
- All **22** approved screenshots byte-identical to `origin/master` (10 drop1 + 12 drop2).
- Root `config-template.toml` absent from worktree, index and committed tree; nothing named
  `config-template` is tracked anywhere.
- `version.py` `0.5.1`; **`shared/output_paths.py`, `shared/maintenance.py`,
  `shared/cancellation.py`, `shared/config.py`, `shared/subprocess_utils.py`,
  `shared/logging_setup.py`, `shared/ui_theme.py`, `launcher.py`, `config.toml`,
  `requirements.txt` and both root launchers are byte-identical to the Phase 3 commit** (blob
  hashes compared).
- 36 production modules parsed with `ast`: none imports `shared.importing`,
  `shared.job_control`, `shared.import_coordination` or `shared.job_ui`.
- No dependency added; no packaging, release, tag or version change; no PR opened or merged.

### 2026-08-09 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 3 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 3 start SHA:** `8a8b0b169c59112d6d08e4510afc76a3f353e8a4`
(the approved Phase 2 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (1):**
- `files/tests/test_import_manager.py` — 1,498 lines, **146 tests** (144 run, 2 skipped with
  exact platform reasons). Manager and snapshots, Add Files, deduplication, the duplicate
  override, atomicity and conflicts, selection and reordering, Plan 2 compatibility, and safety.

**Files modified (4):**
- `scripts/Universal/shared/importing.py` — +891 / −11, now 2,216 lines. `validate_direct_files`,
  `CommitStatus`/`ManagerOperation`, `ImportTransaction`/`CommitResult`/`MutationResult`,
  `plan_transaction`, `PlanningGroups`/`planning_groups`, and `ImportedFileManager`. No new
  import edge: the module still imports only `shared.config` and `maintenance.is_link`.
- `files/tests/test_plan3_boundaries.py` — +79 / −26, now 578 lines. The later-phase guard split so the manager
  vocabulary is permitted in `importing.py` and still forbidden in `job_control.py`, the Phase 2
  positive guard grown into a Phase 3 one, and two new guards proving the importer neither plans
  an output path nor caused `output_paths.py` to be rearranged.
- `md-instructions/Handoff.md` — the Phase 3 record, the Current Focus rewrite, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row,
  recorded start-state "Phase reached", and the next action only.
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — status/baseline header fields.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated or restored.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files); no
  rename or recase in `git diff --name-status`.
- All **22** approved screenshots unchanged and unstaged (10 drop1 + 12 drop2).
- Root `config-template.toml` absent from worktree, index and committed tree.
- `version.py` `0.5.1`; **`shared/output_paths.py`, `shared/maintenance.py` and
  `shared/cancellation.py` byte-identical to the Phase 2 commit** (blob hashes compared);
  `config.toml`, `requirements.txt`, both launchers, `shared/release.py`, `shared/config.py`,
  `launcher.py` and all six production panels unchanged; no new dependency.
- 36 production modules parsed with `ast`: none imports `shared.importing`, `shared.job_control`
  or `shared.job_ui`.
- No runtime data, settings, outputs or source media touched. Every fixture tree was built under
  `tmp_path` and thrown away; a before/after mode-size-mtime snapshot proves the manager and Add
  Files leave every source file exactly as they found it, and no run directory was reserved.

### 2026-08-08 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 2 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 2 start SHA:** `bdfa4c0720ba506926340537c98cc21b27c07819`
(the approved Phase 1 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (1):**
- `files/tests/test_import_traversal.py` — 1,089 lines, **97 tests** (91 run, 6 skipped with
  exact platform reasons). Includes the six `maintenance.is_link` risk-gate evidence tests.

**Files modified (4):**
- `scripts/Universal/shared/importing.py` — ~+521 / −9, now 1,336 lines. `natural_key`,
  `RootBreadth`/`classify_root_breadth`/`is_broad_root`, `is_hidden_name`/`has_hidden_attribute`,
  `capture_identity`, and `scan_roots` with its helpers. One new import edge:
  `from shared.maintenance import is_link`.
- `files/tests/test_plan3_boundaries.py` — ~+120 / −24. Three guards narrowed as Phase 2
  delivered what they forbade, plus three new guards pinning the maintenance edge to `is_link`
  and proving `maintenance.py` was not rearranged.
- `md-instructions/Handoff.md` — the Phase 2 record, the Current Focus rewrite, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row,
  recorded start-state "Phase reached", and the next action only.
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — status/baseline header fields.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated or restored.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files); no
  rename or recase in `git diff --name-status`.
- All **22** approved screenshots unchanged and unstaged (10 drop1 + 12 drop2).
- Root `config-template.toml` absent from worktree, index and committed tree.
- `version.py` `0.5.1`; `config.toml`, `requirements.txt`, both launchers, `shared/release.py`,
  `shared/cancellation.py`, `shared/output_paths.py`, `shared/config.py`, `shared/maintenance.py`,
  `launcher.py` and all six production panels **unchanged**; no new dependency.
- No runtime data, settings, outputs or source media touched. Every fixture tree was built under
  `tmp_path` and thrown away; the scan is read-only and a before/after mode-size-mtime snapshot
  proves it.

**Verification:** **1481 collected** (1381 + 100); **1470 passed, 11 skipped, 1 warning**; theme
suite **17/17 executed**; `verify.py` **RESULT: PASS** on three consecutive runs with identical
counts; `compileall` exit 0; `git diff --check` clean. Six of the eleven skips are new and each
names its exact platform limitation (five `WinError 1314` symlink-privilege, one case-insensitive
filesystem); real NTFS junctions ran for real without elevation. No Tk skip transient occurred.

**Next:** Phase 3 (imported-file manager, deduplication, atomic transactions) — **not started**,
pending explicit maintainer approval.

### 2026-08-08 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 1 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** unchanged. **Phase 1 start SHA:** `d97b710b530555ec00e1f2c31b91699cf3c25449`
(the approved Phase 0 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched and remains
`563df9884497032e19abd4437a0e66584cd9ec12`.

**Files added (5):**
- `scripts/Universal/shared/importing.py` — 833 lines. The frozen importing vocabulary. Tk-free,
  thread-free, filesystem-free.
- `scripts/Universal/shared/job_control.py` — 737 lines. The frozen job vocabulary, the legal
  transition table, and `freeze_options`.
- `files/tests/test_importing.py` — 689 lines, **103 tests**.
- `files/tests/test_job_control.py` — 721 lines, **134 tests**.
- `files/tests/test_plan3_boundaries.py` — 423 lines, **70 structural tests**.

**Files modified (3):**
- `files/tests/test_release_packaging.py` — ~+27 / −8. The maintainer-approved option (a)
  remediation only: the obsolete real-worktree precondition now asserts `config.toml` present and
  `config-template.toml` **absent**; the substantive archive assertion is byte-identical; the
  synthetic-root tests are untouched; `import os` hoisted; the module docstring's obsolete
  coexistence sentence corrected. Nothing was deleted, skipped or xfailed.
- `md-instructions/Handoff.md` — the Phase 1 record, the Current Focus rewrite, the Phase 0 open
  item struck through as resolved, and this entry.
- `md-instructions/don't-delete/…-Master-Implementation-Plan-Index.md` — Plan 3 status row and
  the recorded start-state "Phase reached" only.

**Files deleted or renamed:** none. `config-template.toml` was **not** recreated, restored,
generated, opened, staged or packaged.

**Protected-contract checks at commit time:**
- Four canonical names exact, no alias; `md-instructions/don't-delete/` intact (4 files). No
  rename or recase anywhere in `git diff --name-status`.
- All **22** approved screenshots unchanged and unstaged (10 drop1 + 12 drop2), and now asserted
  by exact filename in `test_plan3_boundaries.py`.
- Root `config-template.toml` absent from worktree, index and committed tree.
- `version.py` `0.5.1`; `config.toml`, `scripts/requirements.txt`, both root launchers,
  `shared/release.py`, `shared/cancellation.py`, `shared/output_paths.py`, `shared/config.py`,
  `launcher.py` and all six production panels **unchanged**; no new dependency.
- No runtime data, settings, outputs or source media touched.

**Verification:** **1381 collected** (1074 + 307); **1376 passed, 5 skipped, 1 warning**; focused
341 passed; theme suite **17/17 executed**; `verify.py` **RESULT: PASS**; `compileall` exit 0;
`git diff --check` clean. Phase 1 added no skip and no warning. The Tk skip transient recurred on
one `verify.py` invocation (14 skips) and did not reproduce across three further runs.

**Next:** Phase 2 (safe natural traversal core) — **not started**, pending explicit maintainer
approval.

### 2026-08-08 — HOME-PC — v0.6.0 Drop 3 (Plan 3) Phase 0 — committed and pushed to `feature/0.6.0-drop3-shared-job-controls-importing`

**Branch:** **new** — `feature/0.6.0-drop3-shared-job-controls-importing`, created from verified
local `master`. It existed neither locally nor on `origin` beforehand (`git rev-parse --verify`
→ *"Needed a single revision"*; `git ls-remote --heads origin` → empty).
**Phase 0 start SHA:** `563df9884497032e19abd4437a0e66584cd9ec12` — the PR #3 merge commit,
confirmed byte-exact against `origin/master` after `git fetch origin --no-prune`.
**Local `master`:** fast-forwarded `bada8a3dee87acf6a6619252bd31cdee429f1711` →
`563df98…` with `git merge --ff-only origin/master`, after proving the old head was an ancestor.
No prune, reset, rebase, stash, clean, force-push or history rewrite at any point. The Drop 2
branch was not developed on and was not deleted.

**Files added (0 by this session).**

**Files modified (2):**
- `md-instructions/Handoff.md` — the new Current Focus, the complete Phase 0 record (branch and
  start state, ancestry table, the `config-template.toml` absence contract, baseline evidence,
  the two recorded failures, the Tk skip transient, the skill audit, the read-only
  implementation-surface reconnaissance and its drift list, open items, next action), the
  demotion of Plan 2's sections to *Previous Focus*, and this entry.
- `md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
  — current status/contract only: §4 post-merge baseline and the replaced template rule, the §5
  Plan 2/Plan 3 status rows and status note, §10's template rule, §15's immediate next action,
  and a new Plan 3 recorded start state. The nine-plan structure, ownership sections and
  dependency graph are untouched.

**Files newly tracked (1):**
- `md-instructions/0.6.0-drop3-shared-job-controls-importing.md` — the active temporary drop the
  maintainer placed in the worktree; its status/authorization line was updated to record Phase 0
  as complete. It is tracked **only** on this branch.

**Files deleted or renamed:** none. No file was deleted by this session, including
`config-template.toml`, which was already absent when the phase began.

**Protected-contract checks at commit time:**
- Four canonical names exact (`Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md`); no
  case-variant alias; no rename or recase in `git diff --name-status`.
- `md-instructions/don't-delete/` intact — all four permanent references present under exact names.
- All **22** approved screenshots unchanged and unstaged: ten under
  `files/UI-Prototype-Screenshots/v0.6.0-drop1/`, twelve under `…/v0.6.0-drop2/`.
- Root `config-template.toml` **absent** from the worktree, the index and the committed tree;
  proven untracked before anything else; no `git clean`, wildcard or recursive deletion used.
- `version.py` `0.5.1`; `config.toml`, `scripts/requirements.txt`, both root launchers,
  packaging and every production module unchanged; no new dependency.
- No runtime data, user settings, outputs or source media touched. `files/runtime-data/` and
  `files/test-logs/` remain gitignored and untouched.

**Verification:** 1074 collected; **1067 passed, 2 failed, 5 skipped, 1 warning**; theme suite
**17/17 executed**; `verify.py` **RESULT: FAIL** — `pytest` FAIL, `deps`/`docs`/`docnames`/`config`
PASS; `compileall -q scripts files/tests` exit 0; `git diff --check` and
`git diff --cached --check` clean. The two failures are
`test_release_packaging.py::test_the_untracked_template_beside_it_is_still_absent[Windows|MacOS]`,
whose line-147 precondition requires the now-removed template to exist; the packaging safety
property is still proven by two other tests that pass. Not repaired here — Phase 0 may not edit
tests. Every skip and the single warning are named in the Phase 0 record above.

**Next:** Phase 1 (pure contracts and compatibility boundaries) — **not started**, pending
explicit maintainer approval.

### 2026-08-04 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 5 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** unchanged. **Phase 5 start SHA:** `abdd1cfa10f4ceb9f666bf4455169bdaddac300e`
(the approved Phase 4 head, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched.

**Files added (2):**
- `files/tests/test_cover_source_side.py` — 34 tests.
- `files/tests/test_maker_custom_destination.py` — 31 tests.

**Files modified (6):**
- `scripts/Universal/shared/output_paths.py` — `SourceSidePlanner`, `temporary_sibling()`,
  `discard_temporary()`, `atomic_replace()`, `validate_source_for_replacement()`,
  `validate_custom_destination()`, and `start_index` on `DestinationPlanner.plan()`.
- `scripts/Universal/mp3_tools/cover_resizer.py` — the source-side toggle and two choices, the
  confirmation dialog and its wording helpers, `written_suffix()`, the reworked worker.
- `scripts/Universal/mp3_tools/m4b_maker.py` — the custom-destination toggle, validation,
  direct output, operation-owned staging, and the corrected cancellation branch.
- `files/tests/test_tool_output_integration.py`, `files/tests/test_output_paths.py` —
  phase-boundary updates.
- `md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md` — the Phase 5
  record. One new append-only ADR; no historical entry rewritten; no v0.6.0 release heading.

**Files deleted or renamed:** none.

**Protected-contract checks at commit time:**
- Four canonical names exact; no alias. `md-instructions/don't-delete/` intact (4 files).
- All ten Plan 1 screenshots unchanged.
- Root `config-template.toml` untracked and byte-for-byte unchanged
  (`94b05edc3211efe531be018fbc442c240df8db42`, verified at start and at commit).
- Root `config.toml` unchanged, valid and machine-agnostic.
- `version.py` `0.5.1`; `scripts/requirements.txt` unchanged; no new dependency.
- Preferences, launch warnings and the disabled Clear Downloaded Data placeholder unchanged.
- No cleanup coordinator, no post-exit behaviour, no Phase 6 catalog.

**Verification:** 574 collected; 569 passed, 5 skipped, 1 warning; theme 17/17;
`verify.py` `RESULT: PASS`; `compileall` exit 0; `git diff --check` clean. Live Windows fixture
pass on disposable fixtures. 125% scaling, live macOS, Phase 8 screenshots and TTS live
synthesis remain **pending**, not passed.

**Next:** Phase 6 (downloaded-data inventory and confirmation UI) — **not started**, pending
explicit maintainer approval.

### 2026-08-03 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 4 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** unchanged. **Phase 4 start SHA:** `10819f1b7cc0d7ddb1b8c51ae870a44c694a3fdc`
(the approved Phase 3 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched.

**Files added (1):**
- `files/tests/test_tool_output_integration.py` — 68 Phase 4 tests, including real-worker runs.

**Files modified (10):**
- `scripts/Universal/tts/epub2tts_gui.py` — reserve in `run_job` after validation; read-only
  destination display; `_browse_dir` retired.
- `scripts/Universal/mp3_tools/m4b_converter.py` — reserve in `start_convert`; batch planner;
  `stem` restored from the planned destination.
- `scripts/Universal/mp3_tools/mp3_tool.py` — one `_reserve_run()` seam used by combine, time
  edit and ID3; combine staging inside the run; `next_available_folder` and
  `BASE_OUTPUT_DIRNAME` removed; the combine filename is now a name prompt, not a save dialog.
- `scripts/Universal/mp3_tools/m4b_maker.py` — reserve in `build`; central sanitiser replaces
  the local regex.
- `scripts/Universal/mp3_tools/cover_resizer.py` — standard output into the reserved run;
  Option A disabled placeholder; dormant legacy branch documented.
- `scripts/Universal/mp3_tools/m4b_metadata_editor.py` — `_reserve_run()` for both action
  paths; workers take the batch planner; plan-before-copy; `avoid_input_overwrite` gone.
- `scripts/Universal/shared/output_paths.py` — added `destination_hint()` and
  `ensure_tool_parent()` for read-only displays and explicit reveals.
- `scripts/Universal/shared/paths.py` — **docstrings only**; both legacy helpers marked dormant.
- `files/tests/test_output_paths.py`, `test_prototype_regression.py`,
  `test_m4b_metadata_editor_ui.py`, `test_mp3_tool_smoke.py` — phase-boundary updates.
- `README.md` — the output-location note (no first-run popup, no other rewrite).
- `md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md` — the Phase 4
  record. One new append-only ADR; no historical entry rewritten; no v0.6.0 release heading.

**Files deleted or renamed:** none.

**Protected-contract checks at commit time:**
- Four canonical names exact; no alias. `md-instructions/don't-delete/` intact (4 files).
- All ten Plan 1 screenshots unchanged.
- Root `config-template.toml` untracked and byte-for-byte unchanged
  (`94b05edc3211efe531be018fbc442c240df8db42`, verified at start and at commit).
- Root `config.toml` unchanged, valid and machine-agnostic.
- `version.py` `0.5.1`; `scripts/requirements.txt` unchanged; no new dependency.
- Preferences, launch warnings and the disabled Clear Downloaded Data placeholder unchanged;
  `preferences_ui.py` does not import `output_paths`.

**Verification:** 503 collected; 499 passed, 4 skipped, 1 warning; theme 17/17 executed;
`verify.py` `RESULT: PASS`; `compileall` exit 0; `git diff --check` clean. Live Windows fixture
pass across all six tools. 125% scaling, live macOS, Phase 8 screenshots and TTS live synthesis
remain **pending**, not passed.

**Next:** Phase 5 (Cover Image and M4B Maker exceptions) — **not started**, pending explicit
maintainer approval. No merge, PR, tag, release, version bump, branch deletion or force-push
was performed or is authorised.

### 2026-08-03 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 3 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** unchanged. **Phase 3 start SHA:** `e16fd42dcb54a6f34a4d79a498fa681f18ef6e6b`
(the approved Phase 2 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched.

**Files added (2):**
- `scripts/Universal/shared/output_paths.py` — output base, tool-parent registry, atomic run
  reservation, sanitisation, collision service, containment/link/input safety, and the flat /
  one-root / multi-root planners.
- `files/tests/test_output_paths.py` — 144 tests.

**Files modified (5):**
- `scripts/Universal/shared/paths.py` — **docstring only**. `next_output_dir()` is marked a
  compatibility wrapper scheduled for removal in Phase 4; no code and no behaviour changed.
- `md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md` — the Phase 3
  record. One new append-only ADR; no historical entry rewritten; no v0.6.0 release heading.

**Files deleted or renamed:** none.

**Protected-contract checks at commit time:**
- Four canonical names exact and unrenamed; no alias exists.
- `md-instructions/don't-delete/` holds all four permanent references, unmoved.
- All ten `files/UI-Prototype-Screenshots/v0.6.0-drop1/` PNGs unchanged.
- Root `config-template.toml` untracked and byte-for-byte unchanged (blob
  `94b05edc3211efe531be018fbc442c240df8db42`, verified at start and at commit).
- Root `config.toml` unchanged, valid and machine-agnostic — `verify.py`'s `config` check passes.
- `version.py` `0.5.1`; `scripts/requirements.txt` unchanged; no new dependency.
- No tool panel and not the launcher imports `output_paths`; `preferences_ui.py` and
  `launcher.py` are untouched by this phase.

**Verification:** 439 collected; 435 passed, 4 skipped, 1 warning; theme suite 17/17 executed;
`verify.py` `RESULT: PASS`; `compileall` exit 0; `git diff --check` **clean, zero notices**.
The one new skip is the file-symlink test (`WinError 1314`); directory-link safety ran for real
via junctions. Windows 125% scaling, live macOS and Phase 2 screenshots remain **pending**, not
passed.

**Next:** Phase 4 (standard output integration across all six tools) — **not started**, pending
explicit maintainer approval. No merge, PR, tag, release, version bump, branch deletion or
force-push was performed or is authorised.

### 2026-08-03 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 2 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** unchanged. **Phase 2 start SHA:** `56076fe4baf32626fa82ad7ecad78dad8c0235e2`
(the approved Phase 1 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched.

**Files added (2):**
- `scripts/Universal/shared/preferences_ui.py` — the Preferences & Data dialog, the
  single-instance entry point, and the once-per-launch configuration-warning window.
- `files/tests/test_preferences_ui.py` — 65 tests.

**Files modified (5):**
- `scripts/Universal/launcher.py` — `Preferences & Data…` in all three status bars,
  `open_preferences()` single-instance handling, `_bind_preferences_accelerators()`,
  `present_configuration_warnings()` scheduled with `after(0, …)`.
- `scripts/Universal/shared/config.py` — public `validate_output_base()`, plus the
  platform-neutral launch-warning guard (`take_launch_warning`, `launch_warning_pending`,
  `reset_launch_warning_guard`).
- `scripts/Universal/shared/settings.py` — `set()`/`update()` now roll the in-memory change
  back when the atomic write fails.
- `files/tests/test_repository_contract.py` — the Phase 1 "no GUI surface" guard retargeted to
  the Phase 2/6 boundary (AST-checked: no cleanup function, no destructive call).
- `md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md` — the Phase 2
  record. One new append-only ADR; no historical entry rewritten; no v0.6.0 release heading.

**Files deleted or renamed:** none.

**Protected-contract checks at commit time:**
- Four canonical names exact and unrenamed; no alias exists (asserted by `verify.py` and the
  contract suite).
- `md-instructions/don't-delete/` holds all four permanent references, unmoved.
- All ten `files/UI-Prototype-Screenshots/v0.6.0-drop1/` PNGs unchanged.
- Root `config-template.toml` untracked and byte-for-byte unchanged (blob
  `94b05edc3211efe531be018fbc442c240df8db42`).
- Root `config.toml` unchanged and still valid/machine-agnostic — `verify.py`'s `config` check
  passes and a test asserts its bytes survive a save-then-reset cycle.
- `version.py` `0.5.1`; `scripts/requirements.txt` unchanged; no new dependency.
- `shared/paths.py` and all six tool panels untouched; a test asserts no panel references
  `preferences_ui` or the cleanup label.

**Verification:** 295 collected; 292 passed, 3 skipped, 1 warning; theme suite 17/17 executed;
`verify.py` `RESULT: PASS`; `compileall` exit 0; `git diff --check` **clean, zero notices**.
Live Windows manual pass at 1920×1080 / 100%; 125% scaling, live macOS and screenshot evidence
recorded as pending, not as passes.

**Next:** Phase 3 (shared output reservation, collision, mirroring) — **not started**, pending
explicit maintainer approval. No merge, PR, tag, release, version bump, branch deletion or
force-push was performed or is authorised.

### 2026-08-03 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 1 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** unchanged. **Phase 1 start SHA:** `ca10c5beb8d2ac6a89ce345a7ba96f733de5df42`
(the approved Phase 0 commit, equal to its upstream at start). No fetch, merge, reset, stash,
rebase or force-push; `master` was not touched.

**Files added (4):**
- `config.toml` (root) — the committed, commented, machine-agnostic project defaults.
- `scripts/Universal/shared/config.py` — the typed effective-configuration core.
- `files/tests/test_config.py` — 68 tests.
- `files/tests/test_settings.py` — 25 tests.
- `files/tests/test_repository_contract.py` — 40 tests.

**Files modified (8):**
- `scripts/verify.py` — canonical `Changelog.md` reference; new `docnames` and `config` checks;
  both take optional paths so the suite can prove they fail on a broken tree.
- `scripts/Universal/shared/settings.py` — `reset()`, bool write results, `last_load_error()`,
  `invalidate()`, `use_path()`; no load-time rewrite of a malformed file.
- `scripts/Universal/shared/logging_setup.py` — retention from `logging.max_sessions` with a
  lazy, always-falling-back config read.
- `scripts/Universal/shared/release.py` — one printed checklist line, `CHANGELOG` →
  `Changelog.md`. No packaging behaviour changed (that is Phase 8).
- `README.md` — two lines: the layout tree's doc names, plus the new root `config.toml`.
- `md-instructions/Briefing.md` — the permanent-filename contract, a new *Configuration*
  architecture bullet, the final maximized-fit/local-scroll rule, the `shared/` and `verify.py`
  descriptions, and its own stale cross-references.
- `md-instructions/Changelog.md` — three `[Unreleased]` entries (Added / Fixed / Added —
  regression protection). **No v0.6.0 release heading was created.**
- `md-instructions/Decisions.md` — one newest-first, dated, signed ADR. **No historical entry
  was rewritten.**
- `md-instructions/Handoff.md` — this section, the Phase 1 record above, and a Work Log entry.

**Files deleted or renamed:** none.

**Protected-contract checks at commit time:**
- Four canonical names exact and unrenamed; no `CHANGELOG.md` / `DECISIONS.md` / `handoff.md`
  alias exists — now asserted by both `verify.py` and `test_repository_contract.py`.
- `md-instructions/don't-delete/` holds all four permanent references, unmoved.
- All ten `files/UI-Prototype-Screenshots/v0.6.0-drop1/` PNGs unchanged.
- Root `config-template.toml` remains **untracked and byte-for-byte unchanged** (blob
  `94b05edc3211efe531be018fbc442c240df8db42`); it was never opened as a source for
  `config.toml`, and a test asserts no file under `scripts/` references it.
- `version.py` unchanged at `0.5.1`; `scripts/requirements.txt` unchanged (no new dependency).
- `shared/paths.py`, `launcher.py` and all six tool panels untouched.

**Verification:** 230 collected; 227 passed, 3 skipped, 1 warning; theme suite 17/17 executed;
`verify.py` `RESULT: PASS` across five checks; `compileall` exit 0; `git diff --check` clean of
new errors (inherited CRLF markdown only).

**Next:** Phase 2 (Preferences, warning presentation, Reset Preferences) — **not started**,
pending explicit maintainer approval. No merge, PR, tag, release, version bump, branch deletion
or force-push was performed or is authorised.

### 2026-08-03 — HOME-PC — v0.6.0 Drop 2 (Plan 2) Phase 0 — committed and pushed to `feature/0.6.0-drop2-config-output-maintenance-foundation`

**Branch:** `feature/0.6.0-drop2-config-output-maintenance-foundation`, created from
`master` @ `bada8a3dee87acf6a6619252bd31cdee429f1711` (= `origin/master`). The branch did not
exist locally or on `origin` before this session; nothing was overwritten or force-pushed.

**Remote reconciliation:** `git fetch origin --no-prune` → `origin/master` `1da1e54..bada8a3`.
Local `master` fast-forwarded with `git merge --ff-only` (no merge commit, no reset, no stash,
no rewrite, no branch deleted). Local `master` == `origin/master` == `bada8a3`.

**Files added (tracked for the first time):**
- `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md` — the authorized active
  Plan 2 drop (833 lines), placed by the maintainer.
- `md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
  — permanent program index (336 lines), placed by the maintainer.

**Files changed:**
- `md-instructions/Handoff.md` — new Plan 2 Current Focus with ancestry proof, planning-artifact
  status, full baseline evidence, the recorded `verify.py` casing defect, the skill audit, the
  read-only surface inspection, and the next action; the Plan 1 block demoted to
  *Previous Focus*; a Work Log entry and this Session Sync Log entry.
- `md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
  — §5 Plan 2 status row and §15 next-action updated with the real branch and start SHA.
- `md-instructions/0.6.0-drop2-config-output-maintenance-foundation.md` — Status line only,
  corrected from "not yet authorized for implementation" to the authorized/in-progress state.

**Files deleted:** none.

**Production code changed:** **none.** `git diff --name-status bada8a3..HEAD` touches only
`md-instructions/`. `scripts/`, `files/`, both root launchers, `.gitignore`, `.gitattributes`,
`README.md` and `version.py` (still `0.5.1`) are untouched.

**Protected-contract checks at commit time:**
- The four canonical names are exact and unrenamed: `Briefing.md`, `Changelog.md`,
  `Decisions.md`, `Handoff.md`. No `CHANGELOG.md` / `DECISIONS.md` / `handoff.md` alias exists.
- `md-instructions/don't-delete/` holds all four permanent references; nothing removed or moved.
- All ten `files/UI-Prototype-Screenshots/v0.6.0-drop1/` PNGs unchanged.
- Root `config-template.toml` remains **untracked and byte-for-byte unchanged**; it is not in
  the index, the commit, or any diff.

**Verification:** 97 collected; 94 passed, 3 skipped, 1 warning; theme suite 17/17 executed;
`verify.py` `RESULT: PASS`; `compileall` exit 0; `git diff --check` clean.

**Next:** Phase 1 (canonical-file gate and configuration core) — **not started**, pending
explicit maintainer approval. No merge, PR, tag, release, version bump or branch deletion was
performed or is authorized.

### 2026-08-02 — HOME-PC — v0.6.0 Drop 1 Phase 6 (approved closeout) — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `b2e809fe4e25f5aaaef1684b5998bc652374de87` (Phase 5 — the approved evidence SHA).
  No pull needed — `master` and `origin/master` are both still `1da1e547` and were not
  touched. Phase 0–5 commits all confirmed as ancestors of HEAD before editing.
- Changed: `md-instructions/Briefing.md` — tech-stack GUI bullet, the launcher architecture
  bullet, the `shared/` bullet, **three new architecture bullets** (Windows design system,
  the `ACT.*` isolation contract, the conversion boundary), the M4B Metadata Editor feature
  entry plus new Shared Metadata and Summary/Details-specimen entries, the layout tree (both
  screenshot directories), **three new known limitations** (DPI-unaware, unchanged geometry +
  converter clipping, unthemed combobox popdown and light title bar), and High-Level State
  (the v0.6.0 Drop 1 approval paragraph and the standing non-Windows preservation contract).
- Changed: `md-instructions/CHANGELOG.md` — three entries beneath the existing `[Unreleased]`
  heading (Added: theme primitives / `ACT.*` namespacing / launcher shell / converted editor /
  Shared Metadata treatment / developer-only specimen / the ten evidence images; Changed:
  `sidebar_width` 232 → 180 with `MIN_SIZE` and `DEFAULT_GEOMETRY` explicitly unchanged;
  Added: the regression protection for the five classic panels and the non-Windows paths,
  with the unresolved DPI note). **No v0.6.0 release heading; no release claimed.**
- Changed: `md-instructions/DECISIONS.md` — one newest-first, dated, signed ADR
  (2026-08-02) recording the approved contract, evidence path + Phase 5 SHA, namespaced
  isolation, why tkinter/ttk stays, macOS/Linux preservation, the geometry deferral, the
  live-macOS deferral, DPI awareness as unresolved future work, and the rejected
  alternatives. No historical entry rewritten; the Decisions 1–55 register not duplicated.
- Changed: `md-instructions/handoff.md` — Current Focus rewritten to the approved/closed
  state, a Phase 6 section (the ten approval decisions, the evidence path and approval SHA,
  the exact permanent-document updates, the drop deletion, the eighteen-row Definition-of-Done
  assessment, the carried-forward limitations, the verification table), three Phase 5
  limitations marked resolved by the approval, a Work Log entry and this entry.
- **Deleted (planned): `md-instructions/0.6.0-drop1-windows-ui-prototype.md`** — the
  temporary instruction drop, removed as the workflow requires now that Plan 1 is
  implemented, verified and approved. It was tracked, so the plan text remains recoverable
  from any Phase 0–5 commit. **No other plan or documentation file was deleted.**
- **Unchanged, deliberately:** `README.md` (the user launch/setup procedure did not change),
  `AI-WORKSPACE.md`, `scripts/Universal/shared/version.py` (still `0.5.1`),
  `scripts/requirements.txt`, both `Setup_and_Run-*` launchers, and **all production code** —
  `git diff --name-only b2e809f..HEAD -- scripts/ files/` is empty, so the ten approved PNGs
  are also byte-identical to what was approved.
- Verified before commit: `test_ui_theme.py` 17 passed / **0 skipped**;
  `test_launcher_smoke.py` 11 passed; `test_m4b_metadata_editor_shared.py` 7 passed;
  `test_m4b_metadata_editor_ui.py` 12 passed; `test_prototype_regression.py` 12 passed; full
  suite **94 passed, 3 skipped**, 1 pre-existing pydub `audioop` warning; `scripts/verify.py`
  **RESULT: PASS**; `compileall` exit 0; `git diff --check` clean. Exactly ten PNGs remain in
  the evidence directory. The Tk skip transient did not recur.
- Worktree after push: only the pre-existing untracked `config-template.toml`, which was not
  edited, staged, moved or deleted at any point in this drop.
- **Status: Plan 1 COMPLETE.** Not merged to `master`, feature branch not deleted, no release
  work performed, Plan 2 neither drafted nor started.

### 2026-08-01 — HOME-PC — v0.6.0 Drop 1 Phase 5 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `9d4f58cdb24f0963552490d73273acaec1369589` (Phase 4). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Added:   `files/UI-Prototype-Screenshots/v0.6.0-drop1/` — exactly **ten** PNGs with the
  plan's §10 filenames: `windows-100-launcher-overview.png`,
  `windows-100-m4b-metadata-empty.png`, `windows-100-m4b-metadata-populated.png`,
  `windows-100-m4b-metadata-active-run.png`,
  `windows-100-summary-details-specimen.png`, and the same five as `windows-125-*`.
  Full maximized application windows at 1920×1080; uncropped, unannotated, unedited.
- Changed: `md-instructions/handoff.md` — Current Focus moved to the open visual gate, a
  Phase 5 section (environment + how each scale was verified, the DPI-awareness finding,
  the ten-image table with fixture provenance, the visual comparison against
  `files/UI-Current-Screenshots/`, the assessment against the nine §10 criteria, the
  two-scaling geometry table, the automated-results table), nine Phase 5 limitations, a
  Work Log entry and this entry.
- **No production source was changed.** `git diff --name-only 9d4f58c..HEAD -- scripts/
  files/tests/` is empty. `requirements.txt`, both setup launchers, all six tool modules,
  `shared/`, and `version.py` (still `0.5.1`) are untouched. `verify.py` and the
  pre-existing Tk headless guard were not modified.
- Not committed, by design: the capture and geometry probe scripts and their JSON output,
  and the trial captures — all in the session scratchpad outside the repository. No test
  fixture, settings file, log, generated audio, output file or draft screenshot entered
  the repository; `settings.json` was snapshotted and byte-restored around every capture.
- Verified before commit: focused suites 17 / 11 / 7 / 12 / 12 passed; full suite
  **94 passed, 3 skipped**, 1 pre-existing warning; `scripts/verify.py` **RESULT: PASS**;
  `compileall` exit 0; `git diff --check` clean. All 17 `test_ui_theme.py` tests executed
  — the Tk skip transient did not recur this session. Every one of the ten PNGs was
  opened and reviewed before committing.
- Worktree after push: only the pre-existing untracked `config-template.toml`, which was
  not edited, staged, moved or deleted at any point.
- **Status: STOPPED at the hard visual gate.** Awaiting an explicit maintainer `APPROVED`
  or `CHANGES REQUESTED`. Nothing merged, no permanent doc updated, plan file not deleted.

### 2026-08-01 — HOME-PC — v0.6.0 Drop 1 Phase 4 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `d8d0b1b7aec1b62d80989ffb791cda313fb22763` (Phase 3). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Added:   `files/tests/test_prototype_regression.py` — 12 tests covering only what
  Phases 1–3 left uncovered: the copy-only/original-protection contract in both workers,
  the input==output collision guard, cooperative cancellation (pre-set, mid-run, and via
  the shared primitive), build-fork surface parity, an aqua bundle taking the
  unconverted fork, generic-style isolation across a **whole app build**, the absence of
  any Plan 3/6/8 control in the runtime editor, the Shared Metadata card adding no
  precedence or disabling, and no new persisted settings.
- Changed: `md-instructions/handoff.md` — Current Focus moved to the Phase 5 gate, a
  Phase 4 section (audit table with evidence per item, the tests-added table, the
  9-row functional matrix, the three-size resize/scroll/keyboard table, the automated
  results table), eight Phase 4 limitations including the written-out macOS smoke test,
  a Work Log entry and this entry.
- **No production source was changed.** `scripts/` is byte-identical to `d8d0b1b`;
  `requirements.txt` and `version.py` (still `0.5.1`) are untouched, as are both setup
  launchers and all five unconverted tool modules.
- Not committed, by design: the generated M4B fixtures, the 400 bulk copies, the eight
  output folders, the audit/matrix/geometry probe scripts and their JSON results — all
  in the session scratchpad outside the repository. `settings.json` was snapshotted and
  byte-restored after every run.
- Verified before commit: focused suites 7 / 12 / 17 / 11 / 12 / 4 passed; full suite
  **94 passed, 3 skipped**, 1 pre-existing warning; `scripts/verify.py` **RESULT: PASS**;
  `compileall` exit 0; `git diff --check` clean. One full-suite run in the middle of the
  pass reported `77 passed, 20 skipped` (the Tk transient); it did not reproduce in 22
  retries and is recorded, not accepted — see *Phase 4 limitations* item 8.
- Worktree after push: only the pre-existing untracked `config-template.toml`, which was
  not edited, staged, moved or deleted at any point.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 3 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `b2e5285958a8d7adcc19a4c17d45f1e55fd7e900` (Phase 2). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/mp3_tools/m4b_metadata_editor.py` (+373 / -9) — the
  presentation fork (`_build_ui` dispatcher, `_build_ui_classic` holding the old body
  verbatim, the new `_build_ui_windows`, the `_wrap_with` caption helper), a theme-aware
  `__init__`, the optional `theme=None` parameter on `build_ui`, and an expanded module
  docstring. Every method from `add_files` down is unchanged.
- Changed: `scripts/Universal/shared/ui_theme.py` (+21 / -2) — `sidebar_width` 232 → 180
  (maintainer-approved, with the reason in a comment) plus four new namespaced styles
  for the Shared Metadata surface (`ACT.Shared.TFrame`, `ACT.Shared.TLabel`,
  `ACT.SharedSecondary.TLabel`, `ACT.Shared.TCheckbutton`, the last with its own explicit
  layout). No generic style was created, configured or re-laid-out.
- Added:   `files/tests/test_m4b_metadata_editor_ui.py` (12 tests) — preserved public
  contract, busy/idle, shared-value prefill through the real widget tree, the non-Windows
  fork, and the Windows-only style/isolation/scroll/Shared-Metadata assertions plus the
  two fixture-isolation tests.
- Added:   `files/tests/manual_windows_ui_prototype.py` — the developer-only visual
  fixture (`empty` / `populated` / `active-run` / `specimen`). Not pytest-collectable,
  not reachable from the launcher, not in the shipped tree, patches nothing, offline.
- Changed: `files/tests/test_ui_theme.py` (+49 / -5) — the pinned 180px rail and the
  Shared Metadata surface-family test; new styles added to the build-everything test.
- Changed: `files/tests/test_launcher_smoke.py` (+51 / -3) — the narrowed-rail regression
  test, and the isolation test now separates the converted editor from the five
  unconverted panels instead of requiring all six to be style-free.
- Changed: `md-instructions/handoff.md` (this file — Phase 3 section, hierarchy and
  control-mapping tables, Shared Metadata / Summary-Details boundaries, fixture isolation,
  the rail measurements, the M4B Converter reachability answer, limitations, work-log
  entry, this sync entry)
- Note:    **`scripts/Universal/launcher.py` was NOT edited.** The narrower rail exposed
  no launcher-owned defect.
- Note:    **Only the metadata editor was converted.** `scripts/requirements.txt`,
  `scripts/Universal/shared/version.py` (still `0.5.1`), both setup launchers,
  `scripts/Universal/tts/`, the other five tool modules and
  `files/UI-Current-Screenshots/` are untouched — confirmed with `git diff --name-only
  HEAD` over each path (empty). A grep of the added lines under `scripts/` for
  `style.configure|style.map|style.layout|option_add|#rrggbb` returns only the three new
  `ACT.Shared*` configure calls; no hex literal and no `option_add` entered the drop.
- Note:    **Open item carried forward:** the vertical half of the Phase 2 geometry
  regression. Width is fixed; M4B Converter's primary action and Log are reachable again
  at 1024×720 but still clipped at the 920×600 minimum. `MIN_SIZE`/`DEFAULT_GEOMETRY`
  left unchanged per the maintainer's decision; re-assess at Phase 5.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed, moved or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 82 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 2 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `9cd7fb8e04e11d64f9303d0f44a7ca3f3723af51` (Phase 1). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/launcher.py` (+151 / -8) — new `_build_ui_windows()`
  (navigation rail, header strip, framed content card, status bar with a focusable
  log button), a `windows` arm in `_build_ui()` and in `_highlight_selection()`
  (ttk `selected` flag instead of disabling the active row), a themed arm in
  `_show_load_error()`, and an updated module docstring. `_build_ui_classic`,
  `_build_ui_darwin`, `_row_hover`, `select_tool`, `_load_tool_into`, `TOOLS`,
  `_available_tools`, `_apply_default_geometry`, `_open_logs`, `_on_close`,
  `_configure_hf_cache` and `main()` are unchanged.
- Changed: `files/tests/test_launcher_smoke.py` (+299 / -0) — 1 test → 10. Adds
  registry order, build-once/no-rebuild across three sweeps, a real typed state marker
  surviving switching, valid-saved-tool restore (with the other five still lazy),
  invalid-key fallback, missing-module fallback, `ACT.*` chrome styling, selected-state
  handling, and the child-panel style-isolation test. The original build-all test is
  preserved verbatim.
- Changed: `md-instructions/handoff.md` (this file — Phase 2 section, layout/style
  mapping table, isolation explanation, draft-review table, limitations, work-log
  entry, this sync entry)
- Note:    **`shared/ui_theme.py` was NOT edited.** The Phase 1 API covered the entire
  shell, so no new style, token or helper was needed and the isolation tests did not
  have to change.
- Note:    **Only the launcher shell was converted.** All six tool modules,
  `scripts/requirements.txt`, `scripts/Universal/shared/*` (including `version.py`,
  still `0.5.1`), both setup launchers and `files/UI-Current-Screenshots/` are
  untouched — confirmed with `git diff --name-only HEAD` over each of those paths
  (empty). `git status` shows only the three files above.
- Note:    **Open geometry regression escalated, not silently accepted** — the shell
  costs the tool panels 127px width / ~100px height vs the classic shell, which clips
  M4B Converter's primary action row at the 920×600 minimum. Full measurements and
  three costed options are in *Phase 2 limitations*. Deliberately not fixed here
  because both levers live in `ui_theme.py` and are maintainer decisions.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 68 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 1 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `0971a20e24fc196967da97d1b204375dc549ad5a` (Phase 0). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/shared/ui_theme.py` (+795 / -7) — explicit `win32`
  branch returning `mode="windows"`, 35 semantic colours, 26 metrics, an 11-entry font
  scale, 41 `ACT`-namespaced ttk styles in `theme["styles"]` (plus 4 widget-owned
  sub-styles) built from 24 explicit layouts over 28 cloned `clam` elements, and the
  new `style_tk_widget()` helper for classic Tk widgets. `apply_theme` signature,
  `DEFAULT_GEOMETRY`, `MIN_SIZE`, `enable_mousewheel` and `ProgressIndicator` are
  unchanged.
- Changed: `files/tests/test_ui_theme.py` (+429 / -13) — 5 tests → 16. Adds the Windows
  bundle/colour/metric contracts, WCAG contrast floors, style-namespace and
  widget-state coverage, a real-widget build pass, the missing-native-theme fallback,
  idempotent re-application, `style_tk_widget` behaviour, and the **generic-style
  isolation** test that compares 18 generic styles before/after theming. The classic
  Linux/other and macOS aqua assertions are preserved as they were.
- Changed: `md-instructions/handoff.md` (this file — Phase 1 section, API table,
  isolation rule for later phases, limitations, work-log entry, this sync entry)
- Note:    **Nothing was converted.** `launcher.py`, all six tool modules,
  `scripts/requirements.txt`, `scripts/Universal/shared/version.py` (`0.5.1`), both
  setup launchers and `files/UI-Current-Screenshots/` are untouched. `git status`
  shows only the three files above.
- Note:    IDE diagnostics investigated before editing, as instructed. Both earlier
  notices (70 and 26 issues) were **Markdown linter output on the documentation files
  written during Phase 0**, not Python errors. Workspace diagnostics are now empty and
  `compileall` over `scripts` + `files/tests` exits 0. No genuine baseline source
  problem; nothing unrelated was fixed.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 59 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 0 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Pulled:  `master` fast-forwarded `695045c` → `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318`
  (`git pull --ff-only`, 10 commits, no divergence). Incoming: v0.5.1 Jenny line,
  8 `files/UI-Current-Screenshots/*.png`, `.gitignore` hardening,
  `md-instructions/Instructions_Template.md` deleted upstream, docs, `version.py` 0.5.1.
- Added:   `md-instructions/0.6.0-drop1-windows-ui-prototype.md` (the active temporary
  drop — tracked on purpose so its Phase 6 deletion is a recorded git event, matching
  how `drop3-plan.md` / `0.5.0-drop2-metadata.md` were handled)
- Changed: `md-instructions/handoff.md` (this file — new Current Focus with the Phase 0
  baseline evidence, limitations, and next phase; work log; this sync entry)
- Note:    **No program, theme, launcher, tool-panel, or test source was touched.**
  `scripts/requirements.txt` and `scripts/Universal/shared/version.py` (still `0.5.1`)
  are byte-identical to `origin/master` — confirmed with `git diff` against the remote.
  `files/UI-Current-Screenshots/` preserved unchanged.
- Note:    Worktree carried pre-existing user work — an unstaged deletion of
  `Instructions_Template.md` and untracked `Map-Repo-Structure.bat` /
  `REPO-STRUCTURE.md`. Nothing was reset, discarded, stashed, or overwritten; all were
  backed up to scratch first. Upstream deleted the template itself and gitignored both
  convenience tools, so the working tree resolved with a zero net diff.
- Note:    The maintainer's on-disk case-rename of the four permanent docs
  (`Changelog.md` / `Decisions.md` / `Handoff.md`) did **not** survive the pull —
  `core.ignorecase=true` meant git never saw it. Live tracked names remain
  `Briefing.md` / `CHANGELOG.md` / `DECISIONS.md` / `handoff.md`. Renaming needs a
  `scripts/verify.py` edit (it hard-codes `CHANGELOG.md`), which this drop may not make;
  raised for a separate maintainer decision.
- Note:    **Untracked `config-template.toml` left alone at the repo root.** It is not
  this session's work (file mtime 2026-07-17, contents are the raw scaffolder template
  with `[PROJECT_NAME]` placeholders) and it appeared in `git status` only partway
  through the session, so an external process (VS Code / a scaffolder run) wrote it.
  It is neither committed nor deleted. Per AI-WORKSPACE the committed root file is
  `config.toml`, not `config-template.toml`, and this repo has neither tracked — so
  this is scaffolding drift for the maintainer to resolve, not drop work. Staging was
  done by explicit path, never `git add -A`, so it cannot be swept in.
- Note:    Phase 0 is committed and pushed on the implementation branch only. `master`
  is untouched. Per-phase commits are this plan's explicit contract (§1.5); the v0.5.0
  one-commit-per-drop ADR does not apply to the v0.6.x line. No AI co-author trailers.

### 2026-07-19 — MacBook — Jenny voice + batch-rework revert — committed to `add-jenny-voice`, pushed (NOT merged to master)
- Changed: scripts/Universal/tts/voice_registry.py (Jenny VoiceEntry, 750/800 single-file preset)
- Changed: files/tests/test_tts_smoke.py (voice counts 11→12, edge 6→7)
- Changed: scripts/Universal/tts/generate_voice_samples.py (reusable voice-filter CLI args)
- Changed: .gitignore (files/livid-lady-test-files/ voice-timing corpus)
- Changed: scripts/Universal/shared/version.py (0.5.0 → 0.5.1)
- Changed: md-instructions/CHANGELOG.md (Jenny entries + rework-reverted 0.5.1 note)
- Changed: md-instructions/Briefing.md (12 voices / 7 Edge; batch pause-fields limitation
  made explicit; version line 0.5.1)
- Changed: md-instructions/DECISIONS.md (batch-rewrite-abandoned-by-ear ADR)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    ALL batch-engine work from the abandoned drop reverted before commit —
  batch_convert.py / epub2tts_gui.py / epub2tts_edge.py / runner.py /
  test_batch_convert_folders.py are byte-identical to master; batch_convert_child.py,
  batch_timing_harness.py, and the drop file batch-timing-parity.md never committed.
- Note:    Maintainer pulls this branch on HOME-PC for a second verify pass and merges
  to master themself. No AI co-author trailers.

### 2026-07-08 — MacBook — UX-progress drop (all phases) — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new ProgressIndicator class)
- Changed: scripts/Universal/mp3_tools/m4b_converter.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/cover_resizer.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/m4b_maker.py (indicator, indeterminate encode,
  dead progress_max branch removed)
- Changed: scripts/Universal/mp3_tools/mp3_tool.py (new indicator + progress/progress_ind
  queue kinds + per-worker ticks)
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (indicator + (done,total)
  payloads; Phase 4 scroll-canvas layout + 14-row Log)
- Changed: scripts/Universal/tts/epub2tts_gui.py (indicator beside Start/Cancel; progress
  enqueues in all four conversion paths)
- Changed: scripts/Universal/tts/kokoro_synth.py (additive progress_callback param)
- Changed: scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py (read_book
  progress_callback, paragraph units)
- Changed: scripts/Universal/tts/epub2tts_edge/runner.py (progress_callback pass-through)
- Changed: scripts/Universal/launcher.py (M4B Metadata description de-staled)
- Changed: files/tests/test_ui_theme.py (ProgressIndicator test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] UX-progress Added + Changed)
- Changed: md-instructions/Briefing.md (ui_theme / worker-progress / metadata-editor
  bullets)
- Changed: md-instructions/DECISIONS.md (progress-placement + Maker-indeterminate ADR)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Phase 5 close-out complete (suite 46/3, verify PASS, win32-stub classic
           proof). Drop file 0.5.0-ux-progress-and-metadata-layout.md intentionally
           NOT deleted and nothing committed (maintainer instruction) — maintainer
           does the final sign-off, carries files to a real clone, and makes the
           single drop commit (no AI co-author trailers).

### 2026-07-08 — MacBook — component-verify drop (all phases) — NOT committed (no .git on this copy)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] component-verify Verified entry)
- Changed: md-instructions/Briefing.md (xHE-AAC bullet reworded w/ macOS USAC residual;
  macOS-live-pass caveat retired; High-Level State notes the macOS per-tool pass)
- Changed: md-instructions/handoff.md (this file — focus, open-issues note, work log,
  sync log)
- Note:    NO program-code changes this drop — the live pass found no macOS breakage.
  The only working-tree deltas vs the previous sync entries are the three docs above.
- Note:    Drop file 0.5.0-macos-component-verify.md intentionally NOT deleted and
  nothing committed (maintainer instruction) — maintainer does the manual sign-off,
  carries files to a real clone, and makes the single drop commit (no AI co-author
  trailers).

### 2026-07-08 — MacBook — scroll fix + UI-shell Phase 5 close-out — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new enable_mousewheel helper —
  wrap-frame Enter/Leave + Tcl-level NotifyInferior guard)
- Changed: scripts/Universal/tts/epub2tts_gui.py (inline wheel handler + canvas
  Enter/Leave block replaced by enable_mousewheel(options_canvas, canvas_wrap);
  shared.ui_theme import added)
- Changed: files/tests/test_ui_theme.py (added enable_mousewheel wiring test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS UI shell Added + Fixed)
- Changed: md-instructions/Briefing.md (GUI/launcher/shared/ui_theme bullets;
  macOS-live-pass caveat narrowed)
- Changed: md-instructions/DECISIONS.md (2 ADRs: aqua theme choice; wheel-binding
  Tcl-level detail guard)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Drop file 0.5.0-macos-ui-shell.md intentionally NOT deleted yet —
  maintainer live-tests scrolling on the TTS panel, then makes the single drop
  commit (one commit for Phases 1–5 + this fix; no AI co-author trailers) and
  deletes the drop file.

### 2026-07-08 — MacBook — UI-shell drop Phases 1–4 — NOT committed (no .git on this copy)
- Changed: AI-WORKSPACE.md (HOME-MacOS section filled in from the real machine)
- Added:   scripts/Universal/shared/ui_theme.py (apply_theme; aqua/Finder vs classic)
- Changed: scripts/Universal/launcher.py (wired to ui_theme; _build_ui split into
  classic (verbatim old body) + darwin Finder shell; _highlight_selection branch;
  _row_hover; _ui_font_family/DEFAULT_GEOMETRY/MIN_SIZE moved into ui_theme)
- Added:   files/tests/test_ui_theme.py (3 headless-guarded theme tests)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Machine state: `.venv` deleted and rebuilt fresh via the .command
  (Python 3.12.13, Kokoro healthy) as the Phase 2 launch-gate test.
- Note:    ⚠ This working copy has NO .git directory — the maintainer must carry
  these files onto a real clone (branch `restructure-v0.5.0` per plan) to commit.
  One commit for the whole drop, maintainer-made, no AI co-author trailers.

### 2026-07-07 — MacBook — §2.4 Kokoro fix — not committed, not pushed
- Changed: scripts/Universal/shared/bootstrap.py (`_is_kokoro_compatible` helper;
  run_setup installs 3.12 before accepting >=3.13; _create_validated_venv rebuilds a
  >=3.13 venv on a <3.13 base)
- Added:   files/tests/test_bootstrap_python_version.py (version-gate regression test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS component-verify Fixed entry)
- Changed: md-instructions/DECISIONS.md (macOS-venv-on-3.12 ADR)
- Changed: md-instructions/handoff.md (this file — focus, Open Issues #1 closed,
  work log, sync log)
- Note:    Machine state changed: brew installed python@3.12 + python-tk@3.12; root
  `.venv` rebuilt on Python 3.12.13 (Kokoro healthy). No commits — maintainer reviews
  and commits. No AI co-author trailers.

### 2026-07-07 — HOME-PC — Drop 3 — committed, merged to master, pushed
- Changed: scripts/Universal/tts/epub2tts_gui.py (batch end_silence_ms fix; paragraph_pause
  hoist + chunk_pause_ms into both Kokoro calls; Kokoro batch .pdf/.txt discovery with
  mirrored output subfolders; mode/browse/docstring labels)
- Changed: scripts/Universal/tts/batch_convert.py (mirrored output tree + collision-safe
  temp dirs + .txt support; out_mp3 threaded through convert_single_pdf; docstrings/CLI text)
- Added:   scripts/Universal/tts/generate_voice_samples.py (per-voice manual-listen QA)
- Added:   files/tests/test_batch_convert_folders.py (5 tests)
- Added:   files/tests/test_kokoro_timing_wiring.py (3 tests)
- Changed: .gitignore (files/test-for-manual-listen-elmatthe/ — generated MP3 samples)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 3 Fixed + Added)
- Changed: md-instructions/Briefing.md (TTS feature bullet)
- Changed: md-instructions/DECISIONS.md (Kokoro pause-mapping ADR)
- Changed: md-instructions/handoff.md (this file — focus, open issues, work log, sync log)
- Deleted: md-instructions/drop3-plan.md (drop implemented)
- Note:    md-instructions/Instructions_Template.md restored from HEAD — the working
           tree showed it deleted alongside the untracked drop file (the drop was
           evidently created from the template, same as before Drop 2), so the net
           working-tree diff for it is zero.
- Note:    Single Drop 3 commit made on restructure-v0.5.0 (stacked on 97758c2) at the
           maintainer's explicit instruction, then fast-forward merged to master and
           pushed. restructure-v0.5.0 RETAINED and pushed (base for macOS work).
           No AI co-author trailers.
- Note:    REMOTE ANOMALY FOUND AND RESOLVED at ship time: origin/master had been
           force-moved to a stale pre-restructure line (a20fa21 "Delete AI-WORKSPACE.md",
           a Jul 2 GitHub web-UI commit atop 391326e — the OLD test-files-scrub rewrite,
           content-identical to our 45c66e5 but with no common ancestor). Maintainer
           ruled it a stale accident: our line was force-pushed over it
           (--force-with-lease), so a20fa21 is gone from master and the root
           AI-WORKSPACE.md remains (as refreshed in 97758c2). If another machine still
           has the old line locally, hard-reset its master to origin/master before
           doing anything.
- Note:    Drop 3 §2.4 (Kokoro on macOS) is NOT done — blocked on a real Mac (Open
           Issues #1). It is the FIRST task for the MacBook session, from master.

### 2026-07-07 — HOME-PC — Drop 2 — not committed, not pushed
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (tag cache + _tags_for/
  _shared_tags/_prefill_shared/_batch_series_readback, Open Folder… button + add_folder,
  batch branch of _refresh_mode, disable_inputs set, docstrings)
- Added:   files/tests/test_m4b_metadata_editor_shared.py (7 detection unit tests)
- Added:   files/tests/test_jack_ryan_final_product.py (env-gated QA inspection)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 2 entry)
- Changed: md-instructions/Briefing.md (metadata-editor feature bullet)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Deleted: md-instructions/0.5.0-drop2-metadata.md (drop implemented)
- Note:    Awaiting maintainer review → single Drop 2 commit on restructure-v0.5.0
           (stacked on a7044d4). Agent does not push. No AI co-author trailers.
- Note:    A SECOND separate commit follows Drop 2 (maintainer ruling, same precedent
           as e80ba7f): the refreshed root AI-WORKSPACE.md + the synced copy at
           files/vibe-coding-templates/AI-WORKSPACE.md. Pre-Drop-2 working-tree
           leftovers resolved: Map-Repo-Structure.bat + REPO-STRUCTURE.md discarded
           (scratch); md-instructions/Instructions_Template.md restored from HEAD
           (deletion predated the session; the refreshed AI-WORKSPACE still
           references it).

### 2026-07-07 — HOME-PC — not committed, not pushed
- Entire v0.5.0 Drop 1 restructure sits UNCOMMITTED in the working tree of branch
  `restructure-v0.5.0` (per the one-commit-per-drop rule): all git mv renames staged,
  new files (tests, verify.py, DECISIONS.md, handoff.md, Instructions_Template.md,
  .claude/CLAUDE.md, .codex/, files/vibe-coding-templates/) untracked pending the single
  drop commit the maintainer will make after review.
- Do NOT start work on another machine until this branch is committed, force-pushed by the
  maintainer, and merged — the whole tree has moved.

### 2026-07-06 — HOME-PC — not pushed
- Changed: AI-WORKSPACE.md (refreshed global workspace doc — committed on master `e80ba7f`)
- Changed: Windows+MacOS scripts/launcher.py, scripts/shared/subprocess_utils.py,
  md-instructions/CHANGELOG.md (console-flash fix, committed on master `e80ba7f`)
- Added:   md-instructions/handoff.md (this file — de-templated, migration map written)
- Note:    Branch `restructure-v0.5.0` active; restructure in flight. Do not start work on
           another machine until this branch merges — the whole tree is about to move.
