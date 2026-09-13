# v0.6.4 — M4B Maker + M4B Metadata Editor

**Status:** DRAFT — maintainer review required before implementation.  
**Scope:** One coordinated drop covering **M4B Maker** and **M4B Metadata Editor**.  
**Recommended branch:** `feature/0.6.4-m4b-maker-metadata-editor`  
**Baseline integration anchor:** `e0bab662b385734807bf264d8f450aebac053dcc`  
**Repository default branch:** `master` — never substitute `main`.  
**Current code/version identity:** `0.6.2` **UNRELEASED**.  
**Latest published GitHub release:** `v0.4.0`.

This plan does **not** authorize a version bump, release, tag, package, pull request, merge, branch deletion, rebase, squash, amend, force-push or history rewrite.

Every phase is separately bounded. Complete one phase, verify it, commit/push only when its gate is green, report, and **STOP** for maintainer review before the next phase.

---

## 1. Purpose

Complete the remaining adoption of the proven v0.6.3 multi-Book foundation by modernizing **both M4B tools in one coordinated v0.6.4 drop**:

1. **M4B Maker** — creates new chaptered M4B audiobooks from ordered MP3 inputs.
2. **M4B Metadata Editor** — edits copies of existing M4B-family files without re-encoding their audio.

The tools must look and behave like members of the same application and reuse the same shared workspace/job/UI foundations, while retaining separate business models and processing implementations.

This is **not** permission to merge the tools into one generic M4B mega-tool.

---

## 2. Authority and supersession

Apply authority in this order:

1. The maintainer's latest explicit instruction.
2. This temporary v0.6.4 implementation plan once the maintainer approves it.
3. Applicable project-specific agent instructions.
4. Current project documentation and configuration, including the permanent Decision Register and Master Index.
5. `AI-WORKSPACE.md` and applicable `.ai/` guidance.
6. Current source, tests and Git history as implementation evidence.

If two statements still materially conflict after applying that order, stop and report the exact conflict before editing.

### 2.1 Maintainer supersession dated 2026-09-13

The following old roadmap assignments are superseded for current/future execution, without deleting their historical record:

- old **Plan 7 / v0.6.3 Drop 2 = M4B Maker alone**;
- old **Plan 8 / v0.6.4 = MP3 Tool + M4B Metadata Editor**;
- later proposal **v0.6.4 Maker, v0.6.5 Metadata Editor**;
- Master Index §15 wording proposing separate future branches:
  - `feature/0.6.4-m4b-maker`;
  - `feature/0.6.5-m4b-metadata-editor`.

The authoritative current assignment is:

> **v0.6.4 = M4B Maker + M4B Metadata Editor in one implementation plan and one feature branch.**

The MP3 portion formerly associated with old Plan 8 has already been delivered and accepted through the v0.6.3 focused MP3 continuation.

The existing old Plan-9 assignment of **v0.6.5 to final visual parity / hardening / packaging / release work** is not changed by this plan unless the maintainer later explicitly changes it.

### 2.2 PR #10 status supersession

Any current document saying PR #10 is open, unmerged, or awaiting integration is stale post-merge wording.

Canonical integration fact:

- PR #10 merged into `master`;
- merge commit: `e0bab662b385734807bf264d8f450aebac053dcc`;
- parent 1: `83a2bfc7de25dbe5a599b48fd73fe306695e490d`;
- parent 2: `4b988676ac258f4f3b4991aa92c99679a2e6ce33`.

Treat stale wording as a documentation-reconciliation item, **not a production defect**.

---

## 3. Baseline and invariants

At implementation kickoff, re-fetch Git state and confirm:

- repository: `elmatthe/audiobook-creation-tool`;
- default branch: `master`;
- intended branch base descends from the PR-10 integration anchor `e0bab662...`;
- no unexpected newer `origin/master` change invalidates the plan;
- working tree and index are clean except for explicitly expected maintainer material;
- version identity remains `0.6.2`;
- published release remains `v0.4.0`.

If `origin/master` has advanced after this plan was written, inspect the delta before branching. Do not silently rebase this plan onto unexplained changes.

### 3.1 Protected repository contracts

Throughout this drop:

- `launcher.TOOLS` remains exactly six tools.
- No new tool slug is added.
- `config-template.toml` remains absent.
- The four canonical documentation filenames retain exact casing:
  - `Briefing.md`
  - `Changelog.md`
  - `Decisions.md`
  - `Handoff.md`
- `md-instructions/don't-delete/` remains protected.
- Existing Plan 1–6 behavior outside the authorized M4B adoption scope must not regress.
- Input media remains read-only.
- No ordinary operation silently overwrites an existing output.
- No AI co-author/session/provenance trailer may be added to a commit.
- No user/project workspace may be created outside the repository without the explicit exception process in `AI-WORKSPACE.md`.
- No business behavior branches by platform merely to make a UI fit.

### 3.2 Platform contract

Windows:

- use the approved ACT dark design system;
- minimum remains `920×600`.

macOS:

- use native Aqua/Finder presentation;
- minimum remains `1024×720`.

Both platforms expose the same functional behavior. Layout may respond to native control metrics through the existing theme/layout seam.

---

## 4. Existing infrastructure to reuse

Do not rebuild these foundations.

### 4.1 Shared Book workspace

Reuse:

- `BookJob`
- `WorkspaceSnapshot`
- stable Book IDs
- `add_book`
- `duplicate_book`
- `remove_book`
- `previous_book`
- `next_book`
- `select_book`
- `replace_book`
- `has_meaningful_work`
- `SharedMetadata`
- `effective_value`
- `effective_metadata`
- `disabled_fields`
- `capture_workspace_run`
- `BookDisposition`
- `WorkspaceRunResult`
- `retry_failed_books`

The shared model remains field-agnostic. Each M4B consumer declares its own field vocabulary and its own meaning for blank values.

### 4.2 Shared Book UI

Reuse:

- `BookNavigator`;
- `SharedMetadataSurface`;
- stable direct selector behavior;
- row/stacked layout support;
- main-thread guarding;
- ACT style lookup / native Aqua fallback.

A narrow backwards-compatible extension to `BookNavigator` is allowed if necessary so the Metadata Editor can expose only actions meaningful to a one-file-per-Book editor. The default MP3 behavior must remain unchanged.

Do **not** copy the navigator into either M4B panel.

### 4.3 Plan-3 job infrastructure

Reuse:

- `JobController`;
- `JobReporter`;
- `JobEventStream`;
- `LoggerBridge`;
- `EtaEstimator`;
- `JobAdapter`;
- `JobControlBar`;
- `JobStatusView`;
- `SummaryDetailsView`;
- `LockGroup`;
- `MainThreadGuard`;
- `MainThreadPump`.

Each processing action is one batch run under one controller, not one controller per Book.

### 4.4 Importing

Reuse the Plan-3 imported-file manager, coordinator, poller, occurrence identity, natural sorting, scanning and cancellation.

Do not create another scanner or raw `list[Path]` business model.

### 4.5 Outputs

Reuse `shared/output_paths.py` for:

- output-base resolution;
- numbered standard runs;
- custom-destination validation;
- component sanitisation;
- collision planning;
- input/output safety;
- containment.

### 4.6 Artwork

Use `shared.image_capabilities` as the sole capability authority.

Accepted selection must follow what the machine can decode. Do not maintain a second M4B-specific fixed extension list.

JPG/JPEG and PNG should remain usable everywhere. HEIC/HEIF is offered only where the shared capability probe says it can be decoded.

Selected artwork is read-only.

### 4.7 MP3 Tool as architectural precedent, not a business template

The accepted MP3 Tool is the preferred precedent for:

- thin panel composition;
- Book navigation;
- one global progress/status area;
- one Summary/Detailed region;
- frozen run planning;
- private staging;
- whole-Book publication;
- failure continuation;
- Retry Failed;
- platform layout hints.

Do **not** copy MP3-specific metadata, signed-Time, ID3, naming or blank-field rules into the M4B tools.

---

# PART I — PRODUCT CONTRACTS

## 5. M4B Maker contract

### 5.1 Responsibility

M4B Maker builds **new chaptered `.m4b` audiobooks from ordered MP3 inputs**.

One Book produces at most one final M4B.

Books never merge into one another.

### 5.2 Workspace/import behavior

Start with one empty Book.

Support:

- `Import Folder`
  - recurse through the chosen root using the shared importer;
  - each directory directly containing compatible MP3s becomes one Book;
  - natural-sort tracks within that Book;
  - never flatten separate book directories together.
- `Add Files`
  - adds selected MP3s to the current Book;
  - explicit user order remains under the Book's control.
- Add Book.
- Duplicate Book.
- Remove Book.
- Previous / Next.
- direct Book selector.
- per-Book track reorder/remove.

Duplicate Book follows the existing Plan-6 contract:

- new stable Book ID;
- copies Book configuration;
- starts with an empty imported-file list.

### 5.3 Maker Shared fields

The Maker Shared region is deliberately **not identical** to the MP3 Tool's Shared region.

Shared fields:

- Artist / Author
- Album Artist / Author
- Album
- Series Name
- Silence Between Tracks (seconds)
- Artwork

A populated Shared value overrides and disables the corresponding current-Book value.

Clearing Shared restores the Book's saved value unchanged.

### 5.4 Maker Book-only configuration

Per Book:

- Title
- Artist / Author
- Album Artist / Author
- Album
- Series Name
- Series Part
- Silence Between Tracks
- Artwork
- optional Output Filename
- Chapter Titles
- ordered MP3 inputs
- compact run status

Title, Series Part, Output Filename and Chapter Titles are not Shared fields.

### 5.5 Silence

Preserve M4B Maker's existing concept:

> **non-negative silence inserted between tracks**

This is **not** the MP3 Tool's signed trim/pad Time field.

Rules:

- `0` means no inserted silence;
- positive values insert that duration between adjacent tracks;
- no extra gap is appended after the final track unless existing approved Maker behavior specifically requires one;
- negative values are invalid and must be rejected before run reservation.

A Book with nonzero silence uses the Safe normalization path required by the existing implementation.

### 5.6 Chapters

Each imported MP3 represents one M4B chapter.

Chapter titles remain one-per-line.

Initial chapter-title suggestions may derive from cleaned source filenames.

User-edited titles are frozen when the run begins.

If fewer usable titles than MP3s are supplied, remaining chapters use their deterministic automatic title.

No worker may consult the live textbox after capture.

### 5.7 Metadata

Preserve the Maker metadata vocabulary already implemented unless separately authorized:

- Title
- Artist
- Album Artist
- Album
- Series Name
- Series Part
- Artwork

Do not silently add Year, Genre, Comment or other fields merely because another M4B component supports them.

If Title is blank, use the plan's safe deterministic fallback for the final M4B title rather than producing an unusable nameless book.

### 5.8 Output filename — Decision 51A

Each Book gets an optional **Output Filename**.

Resolution priority:

1. explicit Book Output Filename;
2. effective Title;
3. effective Album;
4. source-containing folder name, when unambiguous;
5. `Book N`.

Always:

- sanitise through the shared cross-platform authority;
- append `.m4b` exactly once;
- collision-number through the shared planner;
- never derive safety from a hand-written local regex.

The output filename and embedded Title are distinct values.

### 5.9 Series numbering — Decision 48A

Provide batch-level:

- **Auto-number Series Part**
- **Start Part**

When Auto-number is OFF:

- each Book's own Series Part applies normally.

When Auto-number is ON:

- Book Series Part controls are disabled for the run;
- blank Start Part means `1`;
- only successfully published Books consume a number;
- failed/skipped/not-attempted Books create no gap.

Use the shared success-number allocator.

Example:

- Book A succeeds → part 1;
- Book B fails → consumes nothing;
- Book C succeeds → part 2;
- Retry Failed later succeeds for B → part 3.

The run's metadata/configuration remains frozen; success allocation is the existing success-driven state contract, not a read of current widgets.

### 5.10 Fast/Safe behavior

Preserve the existing capability:

- Fast-first where eligible;
- automatic Safe fallback after Fast failure;
- Safe when the operation requires normalization, including inserted silence.

The existing preference to try Fast first may remain a **batch run option**, default ON.

Do not copy the MP3 Combine implementation merely because both have Fast/Safe paths.

Detailed logging must record:

- which path was chosen;
- why Safe was required;
- Fast failure/fallback detail where applicable.

### 5.11 Artwork

Maker artwork supports the shared decode-capability set.

For M4B embedding:

- valid JPG/JPEG may remain JPEG;
- valid PNG may remain PNG;
- HEIC/HEIF must be decoded through the shared capability path and converted **in memory** to a player-compatible M4B cover representation, preferably PNG;
- preserve pixel dimensions unless the format conversion itself requires normalisation;
- do not resize/crop the user's selected source;
- write no converted sidecar beside the source.

Artwork embedding should occur on the staged M4B without re-encoding its audio.

### 5.12 Maker output placement

Standard mode:

`<base>/M4B-Maker-Outputs/M4B-Maker-N/`

All successfully published M4Bs for the batch go directly inside that one run folder.

Custom destination mode:

- preserve the existing explicit custom-destination exception;
- outputs go directly inside the selected destination;
- do not create another `M4B-Maker-N` beneath it;
- collision safety remains active.

One failed Book must not cause successful Books to disappear.

### 5.13 Atomic Book publication

Each Book builds in private operation-owned staging.

A final M4B becomes visible only after all required work for that Book succeeds:

- audio assembly;
- chapters;
- metadata;
- artwork;
- series data;
- final validation.

A failed Book publishes no partial M4B.

Later Books continue where safe.

---

## 6. M4B Metadata Editor contract

### 6.1 Responsibility

The Metadata Editor edits **existing M4B-family files without audio re-encoding**.

Preserve the currently accepted input compatibility unless a later explicit decision narrows it:

- `.m4b`
- `.m4a`
- `.mp4`

Each imported source file is **one independent Book/page**.

This is intentionally different from Maker's directory-to-Book grouping.

### 6.2 Source safety

Imported originals are always read-only.

Every action operates on a copy in operation-owned staging.

A file is published only after its complete edit transaction succeeds.

### 6.3 Editor workspace construction

Use the common `BookJob`/`WorkspaceSnapshot` identity and navigation model, but use a tool-specific import projection:

> **one imported M4B-family occurrence = one Book**

Do not call the directory-to-Book grouping rule when it would combine several existing M4Bs into one Book.

Support:

- Add Files;
- Import Folder through the shared importer;
- optional recursive folder import using the existing shared import option;
- Previous / Next;
- direct selector;
- Remove Book.

Do **not** expose meaningless `Duplicate Book` or empty manual `Add Book` controls merely for symmetry.

If necessary, extend `BookNavigator` backwards-compatibly so a consumer can choose the visible action subset. Its default full Maker/MP3 action set must remain unchanged.

### 6.4 Preserve-by-default is binding

This tool's semantics differ deliberately from the MP3 Tool:

> **blank Shared + blank/unchanged Book edit = preserve the corresponding value from the imported source.**

Blank does **not** mean remove.

Existing tags not targeted by the action remain untouched.

A user who wants wholesale removal uses **Clear All Tags (keep chapters)**.

Do not introduce per-field deletion implicitly through an empty entry.

### 6.5 Source snapshot versus edit intent

For each Book, retain a frozen observation of the imported source metadata sufficient to:

- prefill the page;
- display series provenance;
- determine whether a value actually changed;
- preserve unchanged vendor-specific series representations;
- freeze a run independently of later UI edits.

Do not treat the prefilled display text itself as proof that the user asked to rewrite that tag.

Especially for series values:

- an unchanged source value must not be silently migrated from a vendor/movement/implied representation to the canonical atom;
- an explicitly changed or Shared-overridden value may be written authoritatively using the existing metadata authority.

### 6.6 Editor Shared fields

Shared starts **blank**, even when all imported files happen to have the same source value.

That prevents source coincidence from accidentally becoming an explicit global override.

Shared editable fields:

- Title
- Author / Artist
- Album
- Year
- Genre
- Comment
- Series Name
- Artwork

A populated Shared value:

- is an explicit edit request;
- overrides/disables the matching Book control;
- applies to every eligible Book.

A blank Shared value leaves each Book independent.

### 6.7 Editor Book fields

Each Book page is prefilled from its own source and exposes:

- Title
- Author / Artist
- Album
- Year
- Genre
- Comment
- Series Name
- source Series Part/readback
- Artwork replacement
- Chapter Titles
- source filename/path summary
- compact status

The current Series Part auto-number contract remains distinct rather than being converted into an ordinary text override by accident.

### 6.8 Series Part / numbering

Preserve the established Editor model:

- Auto-number OFF by default;
- Series Part is not rewritten merely because a source part was detected;
- Auto-number ON uses Start Part, blank meaning 1.

Bring automatic numbering into compliance with the shared success-only contract:

- failed/skipped/not-attempted Books consume no part;
- later successful Books receive consecutive parts;
- Retry Failed receives the next available success number.

Writing a new series part continues to use the existing canonical freeform/native series-numbering behavior.

### 6.9 Series removal action

Retain a distinct:

**Remove Series Numbering**

This action removes the numbering surfaces already owned by `clear_series_numbering`, including applicable:

- series-part representations;
- track number used as series numbering;
- movement index/count numbering surfaces.

It does **not** silently remove Series Name or unrelated metadata.

Clear All Tags remains the operation for wholesale metadata removal.

### 6.10 Clear All Tags

**Clear All Tags (keep chapters)** must:

1. copy source to private staging;
2. remove identifying metadata and artwork while retaining chapter structure;
3. reapply only explicit Shared edits and explicit per-Book edits appropriate to the clear operation;
4. apply explicit chapter-title edits;
5. publish only after all steps succeed.

Unchanged values that merely came from source-prefill must **not** be re-applied after the clear, or the action would not actually clear them.

If Shared/Book replacement artwork was explicitly selected, it may be re-applied after the clear. Otherwise source artwork remains removed.

### 6.11 Chapter editor

Each Book has its own chapter-title buffer.

Semantics remain positional:

- line `N` targets chapter `N`;
- a blank line means leave that chapter's current title unchanged;
- excess lines beyond the actual chapter count are ignored/refused according to established safe behavior;
- chapter boundaries are retained.

Do **not** copy the MP3 Tool's blank-line-collapse semantics; these are different workflows.

Chapter-title editing/remux must not re-encode audio.

### 6.12 Editor artwork

Save Tags:

- blank Shared and no Book replacement → preserve source artwork;
- populated Shared artwork → replace artwork on all Books;
- Book replacement → replace artwork only on that Book.

Clear All Tags:

- no explicit replacement → source artwork is removed;
- explicit Shared/Book replacement → reapply that replacement after clearing.

Remove Series Numbering:

- artwork is untouched.

Artwork chooser/preview/capability behavior should be shared with Maker, not separately reinvented.

### 6.13 Editor outputs

One action reserves one normal Metadata Editor run directory.

Final outputs remain flat in that run directory with collision-safe names.

Do not create one directory per M4B merely because the MP3 Tool does so; each Metadata Editor Book already produces one file.

---

# PART II — TARGET ARCHITECTURE

## 7. Recommended module structure

Preserve the current public panel module names used by the launcher:

- `mp3_tools/m4b_maker.py`
- `mp3_tools/m4b_metadata_editor.py`

Keep those modules as UI/composition layers as the redesign progresses.

Recommended supporting modules:

### Shared between the two M4B tools

- `mp3_tools/m4b_artwork.py`
  - Tk-free artwork validation;
  - capability-based accepted types;
  - HEIC/HEIF in-memory conversion;
  - M4B-compatible cover representation;
  - preview-image production;
  - no panel state.

A small M4B artwork UI adapter may be added if both panels would otherwise duplicate chooser/preview/Shared-vs-Book state handling.

Do not force the MP3-specific `mp3_artwork.apply_artwork()` ID3 implementation into M4B containers.

### M4B Maker

Prefer:

- `mp3_tools/m4b_maker_workflow.py`
  - Book configuration vocabulary;
  - import projection;
  - title/chapter defaults;
  - validation;
  - effective Maker values.
- `mp3_tools/m4b_maker_plan.py`
  - immutable batch/Book plans;
  - output naming;
  - private staging;
  - standard/custom destination planning.
- `mp3_tools/m4b_maker_processing.py`
  - actual M4B build;
  - Fast/Safe logic;
  - silence;
  - chapter metadata;
  - final tags/artwork;
  - processing events;
  - staged publication.

### M4B Metadata Editor

Prefer:

- `mp3_tools/m4b_metadata_workflow.py`
  - source observations;
  - one-file-to-one-Book projection;
  - preserve/edit intent;
  - chapter buffers;
  - series provenance.
- `mp3_tools/m4b_metadata_plan.py`
  - immutable Save/Clear/Remove-Series plans;
  - flat destinations;
  - staging.
- `mp3_tools/m4b_metadata_processing.py`
  - staged copy;
  - metadata mutations;
  - chapter-title application;
  - series removal;
  - atomic publication;
  - processing events.

Exact module boundaries may vary if the source audit proves a smaller split is clearer, but:

- business policy must remain Tk-free;
- the two tools must not share one generic processing engine;
- no second workspace/job/output framework may appear.

---

## 8. Frozen-run contract

Every operation follows:

**validate → reserve → plan/freeze → lock → execute → settle → publish**

Workers receive frozen values only.

After run start, workers may not consult:

- Tk variables;
- live workspace state;
- current Shared values;
- current file lists;
- current settings;
- later Book edits.

Retry Failed uses the original frozen plan and source occurrences.

The only success-driven state allowed to advance after capture is an explicitly designed success-number allocator.

---

## 9. Run/job contract

For each processing action:

- one batch;
- one `JobController`;
- one `JobReporter`;
- one event stream;
- one `JobAdapter`;
- one worker;
- one `LockGroup`;
- one overall progress/ETA view;
- one Summary/Detailed log region.

Pause/Resume:

- cooperative;
- acknowledge at safe checkpoints;
- do not freeze an arbitrary subprocess.

Cancel:

- stops at the next safe checkpoint;
- keeps already-published successful Books;
- leaves unreached Books Not attempted;
- publishes no partial current Book.

Failure:

- mark Book failed;
- preserve useful private retry state only where safe;
- continue later Books.

Retry Failed:

- retries failed Books/occurrences only;
- uses original frozen configuration/output plan;
- does not read current UI.

---

## 10. Logging contract

Both M4B panels use the existing shared:

**Summary | Detailed**

pattern.

Summary:

- concise user-facing milestones;
- Book status;
- warnings/failures;
- output location;
- completion.

Detailed:

- timestamps;
- Book/stage context;
- source/output paths where useful;
- FFmpeg command/fallback diagnostics for Maker;
- metadata/chapter operation diagnostics for Editor;
- Python exception detail.

The normal persistent session logger remains active.

Visible log history:

- survives between runs;
- uses dividers between run/retry attempts;
- can be cleared with `Clear Log`;
- clearing visible text does not erase the persistent logger or frozen result.

Do not add a Copy button or severity selector.

---

# PART III — TEST AND EXECUTION POLICY

## 11. Efficient verification policy

The older permanent index's “full suite every phase” wording is superseded for this drop by the maintainer's current efficiency instruction.

Use:

### Every implementation phase

- new/changed focused tests;
- relevant regression tests for touched shared authority;
- `compileall` over changed Python scope;
- `git diff --check`;
- repository/Git sanity;
- no unexplained test collection loss in the focused scope.

### Full suite + `scripts/verify.py`

Run at meaningful checkpoints:

1. Phase 0 baseline;
2. completed Maker functional adoption;
3. completed Metadata Editor functional adoption;
4. combined hardening;
5. after any manual-platform remediation that changes code;
6. documentation closeout;
7. final temporary-drop retirement.

Do not repeatedly burn the full-suite cost after a phase that changes only one well-covered pure helper unless a risk gate below requires it.

### RED proof

For every material new behavior:

1. first prove the new/updated focused test fails for the intended missing behavior;
2. implement;
3. prove it green.

Do not manufacture destructive failure states in the maintainer's real workspace merely to obtain RED evidence.

---

## 12. Commit policy

For implementation Phases 0–11:

- one completed green phase → one normal commit;
- push only to `feature/0.6.4-m4b-maker-metadata-editor`;
- no amend/squash/rebase/force-push;
- no AI authorship/session/provenance trailers.

Manual-only phases may produce no code commit when nothing changes. If permanent Handoff evidence is recorded, a documentation-only checkpoint commit is permitted when the phase explicitly calls for it.

---

# PART IV — PHASES

## Phase 0 — Baseline, branch, contract map and plan activation

### Goal

Establish the exact implementation baseline without changing production behavior.

### Scope

1. Fetch the repository.
2. Verify `origin/master`.
3. Confirm the PR-10 merge anchor is in ancestry.
4. Inspect local status/index/untracked state.
5. Create:
   `feature/0.6.4-m4b-maker-metadata-editor`
   from the verified current `origin/master`.
6. Confirm the manually saved plan is the only **active** implementation authority; the retained v0.6.3 Plan-6 file is a read-only contract reference.
7. Re-audit:
   - current Maker;
   - current Metadata Editor;
   - workspace/shared UI;
   - job controls;
   - output paths;
   - metadata/artwork;
   - relevant MP3 architecture;
   - test boundary guards.
8. Record exact old guards that deliberately protected Maker/Editor from Plan-6 adoption and therefore must be changed only when each adoption begins.
9. Update `Handoff.md` with the new branch/phase state.

### Verification

Run:

- full pytest;
- `python scripts/verify.py`;
- compile gate;
- `git diff --check`.

Record exact test counts/skips/warnings rather than copying old counts.

### Constraints

No production-code change.

Do not edit permanent `don't-delete/` roadmap files in Phase 0.

### Commit

Commit/push the plan activation and Handoff baseline only if all gates are understood and no unexplained regression exists.

### STOP

Stop after Phase 0 report.

If current `master` materially differs from the plan's audited baseline, report before adapting.

---

## Phase 1 — Shared M4B adoption seams and artwork foundation

### Goal

Create only the small reusable seams both M4B consumers genuinely need.

### Scope

#### BookNavigator

If needed, extend it with a backwards-compatible visible-action/action-subset option so:

- Maker keeps Add/Duplicate/Remove;
- MP3 keeps its current behavior unchanged;
- Metadata Editor may use navigation/direct selector/Remove without meaningless Duplicate/empty Add Book controls.

Default behavior must remain byte-for-behavior compatible for current MP3 users.

#### M4B artwork

Create one Tk-free M4B artwork service shared by Maker and Editor:

- chooser patterns from `image_capabilities`;
- decode validation;
- JPG/PNG source-byte preservation where compatible;
- HEIC/HEIF in-memory conversion to a compatible cover representation;
- preview thumbnail;
- no source writes.

Add only the minimum UI adapter needed to avoid duplicate chooser/preview implementation.

### RED proof

Before implementation prove tests fail for:

- selectable navigator action subset;
- MP3 default navigator behavior remaining complete;
- HEIC/HEIF M4B artwork handling;
- invalid/mismatched image rejection;
- source hash unchanged;
- no sidecar creation.

### Verification

Focused tests only plus shared workspace/UI/image-capability regressions, compile and diff check.

### STOP

No Maker or Editor production panel adopts the new seams yet.

---

## Phase 2 — M4B Maker workspace/import model

### Goal

Move Maker state from one raw mutable file list to the shared multi-Book vocabulary, without running media yet.

### Scope

Implement Tk-free Maker workflow/model support for:

- field declarations;
- effective Shared/Book values;
- folder-to-Book construction;
- Add Files to current Book;
- track ordering;
- Book configuration updates;
- Chapter Title defaults;
- silence parsing/validation;
- Series Part/Start Part parsing;
- explicit Output Filename;
- meaningful-work behavior;
- duplicate configuration semantics.

Do not create a second imported-file list.

### RED proof

Cover:

- folder → several Books;
- natural ordering;
- Add Files targets only selected Book;
- stable IDs;
- duplicate config/no inputs;
- Shared override restores Book value after clearing;
- negative silence rejected;
- chapter-title fallback.

### Verification

Focused Maker workflow + Plan-6 workspace regression tests.

### STOP

No FFmpeg processing and no Maker panel conversion yet.

---

## Phase 3 — M4B Maker frozen planning and destinations

### Goal

Freeze the entire Maker operation before media work.

### Scope

Create immutable Maker run/Book plans carrying:

- exact Book order and IDs;
- exact source occurrences;
- final chapter titles;
- effective metadata;
- effective artwork choice;
- effective silence;
- manual/auto series settings;
- optional output filename;
- Fast-first batch option;
- standard or custom destination;
- staged and final output path.

One operation reserves exactly one standard Maker run or validates one custom destination.

Use shared collision/sanitisation rules.

Planning creates no media output.

### RED proof

Prove:

- later workspace edits cannot change the plan;
- collision names deterministic;
- custom destination gets no nested `M4B-Maker-N`;
- source/output overlap refused;
- Output Filename priority/fallback;
- all plan values are immutable and widget-free.

### Verification

Focused plan/output tests.

### STOP

No encoding yet.

---

## Phase 4 — M4B Maker single-Book processing and atomic publication

### Goal

Extract/preserve the current working Maker engine behind the frozen plan.

### Scope

Implement one frozen Book execution:

- FFmpeg readiness through shared authority;
- existing Fast path;
- Safe fallback;
- safe WAV normalization;
- silence between tracks;
- chapter timing and titles;
- core metadata;
- series metadata;
- M4B artwork;
- private staged output;
- validation;
- final atomic publication.

Where practical, move existing proven helper behavior instead of rewriting algorithms.

### Critical constraints

- no live Tk reads;
- no direct output before the Book succeeds;
- no source modification;
- no second FFmpeg-discovery path;
- M4B artwork post-processing must not re-encode audio.

### RED proof

Include:

- Fast eligible;
- automatic Fast→Safe fallback;
- silence forces appropriate Safe path;
- chapters correct;
- cover correct;
- HEIC converted only in memory;
- staged failure publishes nothing;
- collision destination safe;
- cancellation checkpoint removes/retains only operation-owned state.

### Verification

Focused processing tests, including subprocess-command assertions/synthetic media where established.

### STOP

Do not wire the full batch/UI yet.

---

## Phase 5 — M4B Maker batch execution, success numbering and Retry Failed

### Goal

Run all planned Maker Books through the shared job architecture.

### Scope

Use:

- one JobController;
- reporter/event stream;
- one worker;
- shared JobAdapter;
- WorkspaceRunResult;
- Retry Failed;
- shared success allocator.

Behavior:

- process Books in frozen order;
- continue after Book failure;
- publish each Book atomically;
- success-only Series Part allocation;
- Cancel leaves unreached Books Not attempted;
- Retry Failed uses original plan.

Do not create a parallel Book-state machine merely for display.

### Series-numbering ordering

Delay the final success-numbered series mutation until the Book is otherwise ready to publish.

Propose a number, write/finalise it in staging, publish, then commit the number only on successful publication.

If a failed publication is retried after other Books succeeded, rewrite the staged part to the retry's newly proposed success number before publication.

### RED proof

At minimum:

- A success / B fail / C success = consecutive parts;
- B retry success gets next part;
- retry construction consumes no part;
- later live workspace edits cannot alter retry;
- failure does not stop C;
- Cancel dispositions correct.

### Milestone gate

Run full pytest, `verify.py`, compile and diff check.

### STOP

Maker engine is functionally adopted but UI redesign is not yet complete.

---

## Phase 6 — M4B Maker production UI adoption

### Goal

Replace the single-Book Maker panel with the coordinated workspace UI.

### Layout

Use:

1. import/workspace band;
2. Shared Maker fields;
3. Book navigator/direct selector;
4. current Book configuration;
5. local MP3 list;
6. local Chapter Titles editor;
7. output/run options;
8. processing action + Pause/Resume/Cancel/Retry;
9. overall progress/status;
10. one Summary/Detailed log region.

No whole-tool scrollbar.

Local scrolling is allowed for:

- MP3 list;
- chapter titles;
- log;
- selector popup.

### Presentation

Windows:

- ACT styles only;
- no generic style mutation.

macOS:

- native Aqua;
- use responsive layout hints where native metrics require a stacked arrangement.

### Required UI behavior

- Shared overrides visibly disable matching Book controls.
- underlying Book values survive override.
- Auto-number disables manual Series Part as appropriate.
- Book status is derived from actual run state/result.
- controls lock through shared `LockGroup`.
- no Tk access from worker thread.
- custom destination remains explicit.
- artwork preview uses the Phase-1 common M4B artwork seam.

### Boundary reconciliation

Update old Plan-6/hash/adoption guards **only as required to authorize Maker as a real adopter**.

Do not weaken the guards globally.

### Verification

Focused UI/state/geometry tests plus full suite/verify because Maker adoption is now end-to-end.

### STOP

Do not begin Metadata Editor changes in the same phase.

---

## Phase 7 — Metadata Editor source/workspace model

### Goal

Define one existing M4B-family file as one stable Book and preserve source semantics explicitly.

### Scope

Create Tk-free source observations containing the data required for:

- prefilled fields;
- series provenance;
- source artwork presence;
- chapter titles/count;
- edit-intent comparisons.

Build one Book per imported occurrence.

Shared starts blank.

Per-Book pages prefill from source.

Preserve:

- `.m4b/.m4a/.mp4` compatibility;
- blank = unchanged;
- implied series values are display facts, not automatic writes;
- Series Part auto-number behavior.

### Import

Adopt the Plan-3 importer/coordinator.

Folder import may use the shared recursive option.

Each matching source file remains one Book regardless of folder grouping.

### RED proof

Cover:

- two M4Bs in one directory → two Books, not one;
- stable IDs;
- per-source prefill;
- blank Shared does not become a write;
- populated Shared disables Book field;
- clearing Shared restores Book value;
- vendor/implied series provenance retained;
- unreadable source settles safely without poisoning other Books.

### Verification

Focused model/import tests.

### STOP

No metadata writes yet.

---

## Phase 8 — Metadata Editor frozen action plans

### Goal

Freeze exact intent for the three editor actions.

### Actions

1. `Save Tags`
2. `Clear All Tags (keep chapters)`
3. `Remove Series Numbering`

### Save Tags plan

For each Book freeze:

- source;
- final output name;
- source observation;
- explicit Shared overrides;
- explicit Book edits;
- artwork replacement intent;
- chapter-title edits;
- series auto-number settings.

Do not turn unchanged prefill into an implicit rewrite.

### Clear plan

Freeze:

- clear-all action;
- explicit fields to reapply afterward;
- explicit artwork to reapply;
- explicit chapter-title edits.

Source-prefilled-but-unchanged values must not survive through accidental reapplication.

### Remove-series-numbering plan

Freeze only what that action needs.

Do not accidentally apply unrelated pending tag/chapter edits merely because they happen to be visible in the UI.

### Outputs

One standard run folder.

One staged and final file per Book, flat and collision-safe.

### RED proof

Test all three plan modes and plan immutability.

### Verification

Focused plan tests.

### STOP

No mutation engine yet.

---

## Phase 9 — Metadata Editor atomic processing and job-control adoption

### Goal

Execute frozen editor plans safely without re-encoding audio.

### Per-Book transaction

1. preflight required source facts;
2. copy to private staging;
3. perform selected metadata action;
4. apply chapter-title changes if the action permits;
5. apply artwork if intended;
6. validate resulting file;
7. publish atomically.

A failure at any step produces no visible partially edited copy.

### Batch behavior

Use:

- one JobController;
- one Reporter/EventStream;
- one worker;
- Pause/Resume/Cancel;
- continue-on-failure;
- WorkspaceRunResult;
- Retry Failed.

### Series auto-number

Use the shared success allocator.

Failed Books do not create numbering gaps.

### Existing bug/debt closed here

A metadata/tag failure must no longer leave a visible copied output merely because the initial `copy2` succeeded.

The copy belongs to private staging until all edits for that Book succeed.

### RED proof

Include:

- metadata-write failure after copy;
- chapter-title failure after metadata;
- cover failure;
- unreadable source;
- continue to next Book;
- Retry Failed;
- success-only series numbering;
- source hash unchanged;
- unknown/unedited tags preserved by Save;
- Clear removes metadata but keeps chapters;
- Remove Series Numbering preserves Series Name and unrelated tags.

### Milestone gate

Full pytest, verify, compile, diff check.

### STOP

Do not redesign the panel in this phase.

---

## Phase 10 — Metadata Editor production UI adoption

### Goal

Replace the batch-global shared form with one Shared surface plus one independent page per imported file.

### UI composition

1. import controls;
2. Shared Metadata;
3. Book navigator/direct selector;
4. current M4B page;
5. artwork/readback;
6. local chapter-title editor;
7. series-numbering controls;
8. actions;
9. shared job controls/progress;
10. Summary/Detailed log.

### Navigator behavior

Use the common navigator with only meaningful Editor actions visible.

Do not show Duplicate Book merely because Maker uses it.

### Preserve clarity

The UI must clearly explain:

- blank Book edit = preserve source;
- populated Shared = override all Books;
- blank Shared = use each Book independently;
- Clear All is destructive to metadata **on the output copy only**;
- source files are never modified.

### Whole-form scrolling

The redesigned Editor should no longer require a whole-form scrollbar as its ordinary layout.

Use responsive composition and local scroll regions for:

- Book/file selector/list;
- chapter editor;
- log.

This discharges the Editor-specific whole-form-scroll debt early while leaving application-wide scaling/parity work to the later final parity plan.

### Platform behavior

Windows ACT / macOS Aqua, one business implementation.

### Boundary reconciliation

Update the old byte-identity/adopter guards narrowly for the Editor's now-authorized adoption.

### Verification

Focused UI/geometry/main-thread/lock tests plus full suite and verify.

### STOP

Both tools are now functionally adopted; do not begin manual acceptance until the combined hardening phase passes.

---

## Phase 11 — Combined automated hardening matrix

### Goal

Prove the coordinated drop as one system before spending manual-test time.

### Cross-tool cases

#### Workspace

- stable IDs;
- add/remove/navigation;
- selector identity after removal;
- Shared override restore;
- duplicate Maker config/no files;
- one-file-per-Book Editor projection.

#### Frozen state

Change after Start:

- Shared metadata;
- Book metadata;
- artwork;
- chapter titles;
- Book order;
- imported files;
- output settings.

The active run/retry must remain unchanged.

#### Job control

- Pause requested/acknowledged;
- Resume;
- Cancel;
- continue-after-failure;
- Retry Failed;
- stale event rejection;
- terminal settlement.

#### Output safety

- duplicate names;
- invalid filename characters;
- Unicode;
- long names;
- source/output containment;
- custom Maker destination;
- rollback on publish failure;
- symlink/link-safe staging cleanup.

#### Artwork

- JPEG;
- PNG;
- HEIC/HEIF when capability is available;
- unavailable capability;
- invalid/mismatched extension/content;
- source hash unchanged.

#### M4B Maker

- Fast;
- forced Safe;
- Fast→Safe;
- silence;
- chapters;
- metadata;
- manual series part;
- success-auto series parts;
- output filename fallback.

#### Metadata Editor

- preserve unknown tags;
- Shared override;
- per-Book edit;
- clear-all;
- chapter retention;
- chapter-title edit;
- artwork preserve/replace/clear;
- series provenance;
- numbering removal;
- success-auto series parts.

### Structural guards

Prove there is still exactly one authority for:

- Book model;
- Book navigation;
- importing;
- job control;
- outputs;
- image capability;
- metadata writing.

No generic M4B mega-controller is permitted.

### Gate

Run:

- race-sensitive focused tests as warranted;
- full pytest once;
- `python scripts/verify.py`;
- compileall;
- `git diff --check`;
- repository filename/branch/status checks.

No unexplained reduction in collected tests.

### STOP

If green, request Windows manual acceptance. Do not start it automatically.

---

## Phase 12 — Windows combined manual acceptance

### Goal

Validate both completed tools through the real launcher on Windows.

No code change is expected. If a defect is found, stop the matrix, root-cause it, fix only that defect, rerun its focused automated proof and the affected manual row, then run the appropriate full gate before acceptance.

### Environment

Use the real supported launcher and current proved FFmpeg.

Test Windows minimum `920×600` and normal `1024×720`.

### Maker manual matrix

Use a bounded representative multi-Book set covering:

- Import Folder → several Books;
- Add Files/current Book;
- Book navigation/direct selector;
- Shared overrides;
- Book-specific values;
- chapter titles;
- artwork preview;
- standard output;
- custom destination;
- at least one real M4B build;
- source playback/unchanged proof;
- output playback;
- chapter navigation;
- metadata/artwork inspection;
- success series numbering;
- one controlled Book failure followed by later success;
- Retry Failed;
- Pause/Resume/Cancel sufficiently to prove wiring.

Do not manually repeat every mechanically proved edge case.

### Metadata Editor manual matrix

Use representative existing M4Bs covering:

- several Books/pages;
- source-prefilled metadata;
- Shared override;
- per-Book edit;
- source-preserve behavior;
- artwork replacement;
- chapter-title edit;
- Clear All Tags while chapters remain;
- Remove Series Numbering while Series Name/chapters remain;
- output copy only;
- source unchanged;
- failure continuation / retry;
- Pause/Resume/Cancel wiring where meaningful.

Inspect outputs mechanically with existing metadata/ffprobe authorities as well as through a normal player where relevant.

### Artwork

Exercise HEIC/HEIF only if this Windows machine reports the capability.

### Acceptance

Maintainer explicitly accepts or rejects Windows.

### STOP

Do not start macOS until Windows is accepted.

---

## Phase 13 — macOS parity acceptance

### Goal

Prove the same business behavior under native Aqua without needlessly replaying every Windows row.

### Start state

Use a fresh Mac terminal/coding-agent context.

Verify:

- branch;
- exact remote SHA;
- clean worktree;
- setup/launch health;
- FFmpeg readiness;
- Python environment.

### Automated

Run platform-relevant focused tests followed by one complete macOS suite/verify gate.

### Manual

At `1024×720` and larger:

- inspect both layouts;
- confirm no inaccessible controls or whole-tool scroll dependency;
- navigation/direct selector;
- Shared/Book disabling/restoration;
- native artwork picker/preview;
- one representative Maker multi-Book build;
- one representative Metadata Editor Save;
- one destructive-to-copy Editor action (`Clear All` or Remove Series Numbering);
- HEIC/HEIF if reported available;
- output playback/metadata where relevant;
- source safety.

Cross-platform business logic already mechanically proven and manually accepted on Windows does not need exhaustive duplication unless macOS uses a materially different external path.

### Defects

Any Mac-only issue receives:

- root cause;
- focused RED/green automated test where practical;
- bounded remediation;
- relevant manual row repeated;
- full gate after final code change.

### Acceptance

Maintainer explicitly accepts or rejects macOS.

### STOP

Do not close the drop until accepted or explicitly waived with the waiver recorded as a waiver, never as PASS.

---

## Phase 14 — Permanent-document and roadmap reconciliation

### Goal

Transfer lasting truth before temporary plans are eligible for retirement.

### Update permanent product documents

#### `Decisions.md`

Add one new dated v0.6.4 closeout decision describing durable rules, including:

- combined Maker + Editor drop;
- shared infrastructure reuse;
- Maker Shared/Book field split;
- Maker success-only series numbering;
- one-file-per-Book Metadata Editor model;
- Editor blank=preserve semantics;
- Shared Editor fields begin blank;
- atomic staged publication;
- M4B artwork capability behavior;
- common JobController/Summary-Detailed model;
- platform presentation.

Do not edit old ADR text to pretend the decisions always existed.

#### `Changelog.md`

Under `[Unreleased]`, describe user-visible Maker and Editor changes.

Do not create a `[0.6.4]` release heading without separate release authority.

#### `Briefing.md`

Update architecture/module descriptions and operating semantics.

#### `README.md`

Update both tool instructions to match actual implemented behavior.

Resolve any stale Maker field wording such as unsupported Year/Genre claims rather than adding features to make the stale sentence true.

#### `Handoff.md`

Record:

- completed phases;
- final branch/SHA;
- automated results;
- Windows acceptance;
- macOS acceptance;
- remaining limitations;
- exact next action.

### Reconcile permanent planning record carefully

#### Master Implementation Plan Index

Add/update current status while preserving superseded history.

Record:

- PR #10 merged at `e0bab662...`;
- old separate Plan-7/Plan-8 scope split superseded on 2026-09-13;
- v0.6.4 now contains remaining Maker + Metadata Editor adoption;
- MP3 portion already delivered in v0.6.3;
- no separate v0.6.5 Metadata Editor plan;
- existing later final parity/release assignment remains v0.6.5 unless separately changed.

Do not rewrite old dated status blocks as if they were never true.

#### Approved Plan Series Map

Do not erase the 2026-07-31 approved map.

Append a clearly dated **Maintainer supersession** section explaining the new combined mapping.

#### Decision Register 1–55

Do **not** rewrite the locked register.

The new dated `Decisions.md` entry records the later supersession.

### Version/release

`VERSION` and `config.toml` remain `0.6.2`.

Do not bump them in this phase unless the maintainer separately and explicitly authorizes that exact change.

### Retained Plan-6 file

Confirm mechanically that all reasons for retaining:

`md-instructions/0.6.3-drop1-shared-multi-book-workspace.md`

are now satisfied:

- MP3 adopted;
- Maker adopted;
- Metadata Editor adopted;
- lasting contracts promoted.

Mark it **eligible for retirement**, but do not delete it yet.

### Verification

Run complete suite, verify, compile and diff check after documentation reconciliation.

### STOP — mandatory closeout approval gate

Ask the maintainer to approve or reject retirement of:

1. `md-instructions/0.6.4-m4b-maker-metadata-editor.md`
2. retained `md-instructions/0.6.3-drop1-shared-multi-book-workspace.md`

Do not delete either without explicit approval.

---

## Phase 15 — Approved temporary-plan retirement and closeout

**This phase may run only after explicit maintainer approval following Phase 14.**

### Goal

Leave the feature branch in a clean integration-ready state.

### Scope

If and only if specifically approved:

- delete the completed v0.6.4 temporary plan;
- retire the retained v0.6.3 Plan-6 temporary drop whose final outstanding adopters are now complete.

Delete no other file.

Do not touch `md-instructions/don't-delete/`.

### Verification after deletion

Re-run:

- full pytest;
- `python scripts/verify.py`;
- compile gate;
- `git diff --check`;
- exact canonical-doc-name check;
- protected-reference check;
- `git status --short`;
- `git diff --name-status`.

The post-retirement gate must be as green as the pre-retirement gate.

### Commit/push

Create one normal closeout commit and push the feature branch.

No PR and no merge are authorized by this phase.

### Final STOP

Return the complete closeout report.

The next action is an **independent READ-ONLY integration-readiness review** from a fresh coding-agent context.

Do not open a PR, merge, bump version, tag, package, release or delete the branch until separately instructed.

---

# PART V — MANUAL ACCEPTANCE AND DEFINITION OF DONE

## 13. Definition of Done — shared

The combined v0.6.4 drop is complete only when all are true:

- both tools use stable shared Book identity/navigation where applicable;
- no duplicate workspace/import/job/output framework exists;
- both freeze run intent before worker execution;
- both use one shared JobController/reporting pipeline per batch;
- both support Pause/Resume/Cancel;
- both continue after isolated Book failure;
- both offer Retry Failed from frozen state;
- both publish each Book/file atomically;
- both show one Summary/Detailed log region;
- Windows uses ACT presentation;
- macOS uses native Aqua;
- source files remain unchanged;
- all required automated gates pass;
- Windows manual acceptance is explicitly approved;
- macOS manual acceptance is explicitly approved or explicitly documented as a waiver;
- permanent documentation is reconciled;
- roadmap supersession is recorded without rewriting history;
- temporary-plan retirement is explicitly approved and completed;
- version remains `0.6.2` unless separately authorized otherwise.

---

## 14. Definition of Done — M4B Maker

Maker specifically must prove:

- several Books can coexist;
- folder import makes one Book per directory directly containing MP3s;
- Add/Duplicate/Remove/navigation/direct selector work;
- ordered inputs remain per Book;
- Shared Maker values override/disable matching Book controls;
- underlying Book values survive Shared override;
- chapters are correct;
- silence behavior is preserved;
- artwork supports shared capability formats;
- M4B output has correct cover/metadata/chapters;
- explicit per-Book output filename works;
- automatic fallback/collision naming is safe;
- standard run output works;
- custom destination works without nested run folder;
- Fast-first/Safe fallback is preserved;
- one Book failure does not stop later Books;
- automatic Series Parts have no failure gaps;
- retry uses frozen state and appropriate next success number;
- no partial failed Book appears in final output.

---

## 15. Definition of Done — M4B Metadata Editor

Metadata Editor specifically must prove:

- every imported existing M4B-family file has its own stable Book/page;
- source metadata pre-fills that Book;
- Shared starts blank;
- Shared values deliberately override matching Book controls;
- blank/unchanged Book values preserve source metadata;
- source vendor/implied series values are not silently migrated;
- Save Tags preserves unrelated tags;
- Clear All Tags removes metadata/artwork while retaining chapters;
- explicit edits may be reapplied after Clear;
- Chapter Titles apply positionally with blank-line-preserve semantics;
- Remove Series Numbering removes numbering but not Series Name/unrelated metadata;
- automatic Series Parts are success-only;
- artwork can be preserved or replaced correctly;
- no audio re-encoding is introduced;
- failed edit transactions publish no partial copy;
- output copies remain collision-safe and flat in one run folder;
- Retry Failed uses the original frozen edit plan;
- imported originals remain byte-unchanged.

---

## 16. Phase report format

Every coding-agent phase report must contain:

1. **PHASE**
   - completed phase;
   - next phase named but not started.

2. **GIT STATE**
   - branch;
   - starting SHA;
   - final SHA;
   - upstream equality;
   - worktree/index status.

3. **SCOPE**
   - files changed;
   - approximate size;
   - no unrelated changes.

4. **IMPLEMENTATION**
   - what changed;
   - why;
   - deviations from this plan, if any.

5. **RED / GREEN EVIDENCE**
   - new material tests that were first proved red;
   - final focused result.

6. **VERIFICATION**
   - focused tests;
   - full tests when this phase requires them;
   - skips/warnings;
   - `verify.py` where required;
   - compile gate;
   - `git diff --check`.

7. **SAFETY**
   - source safety;
   - output/staging safety;
   - protected docs/files;
   - no AI commit trailers.

8. **MANUAL GATE**
   - exact maintainer action if one is pending;
   - otherwise `None`.

9. **STOP**
   - explicitly confirm the next phase was not started.

---

## 17. Explicit non-goals

This drop does not:

- combine Maker and Metadata Editor into one tool;
- redesign M4B Converter;
- redesign TTS or Cover;
- change MP3 Tool business behavior;
- add new TTS features;
- add Year/Genre/etc. to Maker without separate approval;
- add signed trim/pad Time to Maker;
- add a new generic media importer;
- create another job controller;
- create another output framework;
- change Windows process DPI awareness;
- complete every remaining application's final UI-parity item;
- fix `.DS_Store` release packaging unless directly required by this work;
- release v0.6.4;
- bump `VERSION` merely because the branch is called v0.6.4;
- create a tag/package/release;
- open or merge a PR;
- delete the feature branch.

---

## 18. Expected state after this plan

After Phase 15:

- M4B Maker and M4B Metadata Editor are both modern multi-Book/shared-infrastructure consumers;
- MP3, Maker and Metadata Editor have a coherent workspace/run/log interaction model without sharing inappropriate business logic;
- the original Plan-6 multi-Book foundation has all intended production adopters;
- the old roadmap split is preserved as history but clearly superseded;
- `master` remains untouched until a later approved integration;
- code identity remains `0.6.2` unless separately changed;
- the next activity is an independent integration-readiness review, not another implementation phase.