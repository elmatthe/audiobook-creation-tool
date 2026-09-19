# Audiobook Creation Tool v0.6.x — Approved Plan Series Map

**Date:** 2026-07-31  
**Decision basis:** Confirmed Decision 55A  
**Purpose:** Coordinate the future `md-instructions/` plans. This is a roadmap, not an implementation drop and not permission to change the repository.

## Plan count

**Nine focused instruction drops across six v0.6.x checkpoints.**

Each drop will contain several small, independently verifiable phases. The coding agent implements one phase, stops, and returns the required summary for user review.

## Proposed sequence and filenames

### v0.6.0 — Shared foundations and approved Windows direction

#### Plan 1 — Windows UI prototype and approval gate

**Proposed filename:** `0.6.0-drop1-windows-ui-prototype.md`

Covers:

- Windows design tokens and shared theme primitives
- Redesigned launcher shell
- M4B Metadata Editor prototype conversion
- Summary/Details visual specimen where required for design validation
- Shared Metadata visual specimen
- 1920×1080 at 100% and 125% screenshot matrix
- Keyboard, scrolling, file dialog, selection, switching, state-preservation, and Cancel regression checks
- Hard stop for user visual approval

Must not:

- Convert the other five tools
- Add broad new workflow functionality
- Change toolkit unless the prototype fails and the user approves reassessment

**Dependency:** none beyond current v0.5.1 baseline.  
**Approval gate:** mandatory before broad Windows conversion.

#### Plan 2 — Configuration, output, and application-maintenance foundation

**Proposed filename:** `0.6.0-drop2-config-output-maintenance-foundation.md`

Covers:

- Root `config.toml`
- Validation and warning behavior
- Layered precedence
- Shared output-base/run-folder/collision services
- Flat individual-file and mirrored folder-root rules
- Cover and M4B Maker output exceptions
- Reset Preferences
- Itemized Clear Downloaded Data
- Safe post-exit cleanup of `.venv` and other locked assets
- Release packaging of `config.toml`

**Dependency:** may use approved UI primitives from Plan 1 for dialogs, but business logic should remain platform-neutral.

#### Plan 3 — Shared job controls and importing foundation

**Proposed filename:** `0.6.0-drop3-shared-job-controls-importing.md`

Covers:

- Reusable imported-file manager
- File counts and selection/reorder actions
- Background atomic recursive scans
- Cancel Import
- Natural depth-first traversal
- Multiple roots
- Deduplication and explicit duplicate override
- Hidden/link/unreadable safety rules
- Large-root/result warnings
- Frozen run snapshots and input locking
- Cooperative Pause/Resume state model
- Summary/Details log contracts
- Rolling ETA
- Retry Failed state and interfaces

**Dependency:** Plan 2 configuration/output services.  
**Important:** extend existing cancellation/progress/thread/queue foundations rather than replace them.

### v0.6.1 — TTS and Cover workflows

#### Plan 4 — TTS and Cover Image upgrades

**Proposed filename:** `0.6.1-tts-cover-workflows.md`

Covers:

- Adoption of shared importer and controls
- TTS PDF/TXT folder batch only; EPUB stays single-file
- TTS mirrored output and regression protection
- No Edge timing-engine rewrite
- Cover Details/List/Medium Thumbnail views
- Cover folder importing and output choices
- Pinned `pillow-heif` and centralized capability detection
- Windows/macOS HEIC verification

**Dependencies:** Plans 1–3.

### v0.6.2 — M4B conversion

#### Plan 5 — M4B Converter upgrade

**Proposed filename:** `0.6.2-m4b-converter-upgrade.md`

Covers:

- Shared importer adoption
- Whole-book vs split mode
- Chapter-map validation and chapterless fallback
- Complete-timeline chapter splitting
- Correct order-prefixed naming
- Preserve/Strip/Replace metadata modes
- Structural tag rules
- Folder mirroring, collision safety, progress, pause/cancel, retry, and failures

**Dependencies:** Plans 1–3.

### v0.6.3 — Multi-book creation

#### Plan 6 — Shared multi-book workspace foundation

**Proposed filename:** `0.6.3-drop1-shared-multi-book-workspace.md`

Covers:

- Book job data model
- Add/Duplicate/Remove Book
- Previous/Next and Book X of Y
- Folder-to-book job creation
- Shared Metadata precedence and disabled-control behavior
- Distinct Shared Metadata visual state
- Frozen effective-value snapshots
- Success-only numbering
- Retry integration
- Meaningful-work removal confirmation

**Dependencies:** Plans 1–3.  
**Consumers:** M4B Maker and MP3 Tool; reusable parts may support M4B Metadata Editor.

#### Plan 7 — M4B Maker multi-book implementation

**Proposed filename:** `0.6.3-drop2-m4b-maker-multi-book.md`

Covers:

- Multiple M4B outputs in one run
- Per-book MP3 lists, metadata, cover, silence, filename, and processing state
- Shared-series metadata
- Auto-numbering with starting part
- Custom destination behavior
- Safe filename fallbacks and collision numbering
- Continue-on-failure, retry, and success-only part assignment
- Preserve Fast-first + fallback behavior

**Dependencies:** Plans 1–3 and 6.

### v0.6.4 — MP3 and metadata workflows

#### Plan 8 — MP3 Tool and M4B Metadata Editor upgrade

**Proposed filename:** `0.6.4-mp3-and-m4b-metadata-workflows.md`

MP3 Tool covers:

- Combine/Bulk ID3 only
- Multi-book processing per job
- Preserve-majority normalization
- Remove-all mode
- Shared Metadata precedence
- Embedded artwork removal
- Signed Time inside Bulk ID3
- Existing-tag preservation and clear-all-first option
- Output organization, filenames, failure continuation, and retry

M4B Metadata Editor covers:

- One prefilled page per M4B
- Shared Metadata global page
- Existing chapter titles visible and independently editable
- Shared/per-book override rules
- Shared importing/output/job-control foundations

**Dependencies:** Plans 1–3 and 6. Plan 7 should validate the multi-book foundation before this drop consumes it broadly.

### v0.6.5 — Full visual conversion and release hardening

#### Plan 9 — Remaining Windows UI conversion, macOS parity, QA, docs, and packaging

**Proposed filename:** `0.6.5-ui-parity-hardening-release.md`

Covers:

- Convert all remaining Windows tool panels to the approved design system
- Preserve macOS Finder-style appearance while exposing all new functionality
- Full Windows/macOS regression matrix
- DPI/scaling and keyboard/accessibility review
- Long-run Pause/Resume/Cancel/retry drills
- Large import and collision edge cases
- Fresh/repaired setup checks
- HEIC capability checks
- Release ZIP contents and launch tests
- Version/release checkpoint documentation
- README, Briefing, Changelog, Decisions, and Handoff updates
- Final manual test matrix and release checklist

**Dependencies:** Plans 1–8.

## Dependency overview

```text
Plan 1 UI prototype approval
   ├── Plan 2 config/output/maintenance
   └── Plan 3 job controls/importing
          ├── Plan 4 TTS/Cover
          ├── Plan 5 M4B Converter
          └── Plan 6 multi-book foundation
                 ├── Plan 7 M4B Maker
                 └── Plan 8 MP3 + M4B Metadata

Plans 1–8 ──> Plan 9 parity, QA, docs, packaging, release
```

## Planning order in the fresh chat

1. Read all final handoff and source materials.
2. Perform the final consistency audit.
3. Confirm/refine this roadmap’s filenames and exact documentation ownership without changing the nine-drop structure unless a genuine dependency conflict is found.
4. Draft Plan 1 completely.
5. Stop for user review.
6. Draft Plans 2–9 one at a time in later turns, keeping each plan internally consistent with earlier approved plans.

## Repository safety during plan creation

- Read-only repository inspection only.
- No branches.
- No issues.
- No commits.
- No pull requests.
- No implementation files.
- No edits to current repository docs.
- The produced plan markdowns are planning artifacts for user review, not executed changes.

---

## Maintainer supersession — 2026-09-13 (recorded 2026-09-17 at v0.6.4 Phase 14)

**The approved 2026-07-31 map above is not erased; this section records how execution departed from
it, by explicit maintainer ruling, and what stands unchanged.**

**What was superseded.** The map assigned v0.6.3 Drop 2 / Plan 7 to the M4B Maker alone and v0.6.4 /
Plan 8 to the MP3 Tool plus the M4B Metadata Editor. In execution:

- **v0.6.3** delivered Plan 6 (the shared multi-Book workspace foundation, Phases 0–8) **and the MP3
  Tool half of old Plan 8** as the *focused MP3 redesign* (temporary plan
  `0.6.3-plan6-mp3-tool-redesign.md`, Phases 1–13, retired at its closeout), accepted on both
  platforms on 2026-09-12 and **merged into `master` through pull request #10** on 2026-09-13 as
  `e0bab662b385734807bf264d8f450aebac053dcc`. v0.6.3 closed there; no separate Maker drop followed.
- **v0.6.4** delivered the **M4B Maker (old Plan 7) and the M4B Metadata Editor (the remaining half of
  old Plan 8) together, in one implementation plan and one feature branch**:
  `md-instructions/Audiobook Creation Tool v0.6.4 — M4B Maker + M4B Metadata Editor.md` on
  `feature/0.6.4-m4b-maker-metadata-editor`, cut from that merge. The maintainer ruled this on
  2026-09-13, superseding the two-drop split, the later proposal "v0.6.4 = Maker, v0.6.5 = Metadata
  Editor", and the Master Index §15 branch names `feature/0.6.4-m4b-maker` /
  `feature/0.6.5-m4b-metadata-editor` — none of which were ever created. The proposed filenames
  `0.6.3-drop2-m4b-maker-multi-book.md` and `0.6.4-mp3-and-m4b-metadata-workflows.md` were never
  created either. That drop completed through Phase 15 at `41361ab`, was accepted on Windows and
  macOS on 2026-09-15, is closed, and is not merged or released. Phase 15 retired both the completed
  v0.6.4 temporary plan and the retained Plan-6 drop after explicit maintainer approval; their
  lasting contracts remain in the permanent records.

**What the combined v0.6.4 drop covered**, against the two "Covers" lists above: every Plan 7 item
(multiple M4B outputs in one run; per-Book MP3 lists, metadata, cover, silence, filename and
processing state; shared-series metadata; auto-numbering with a starting part, success-only;
custom-destination behaviour preserved; safe filename fallbacks and collision numbering;
continue-on-failure, retry and success-only part assignment; Fast-first + fallback preserved) and
every Metadata Editor item of Plan 8 (one prefilled page per M4B; a Shared row that starts blank;
existing chapter titles visible and independently editable per page; Shared/per-Book override rules
with preserve-by-default binding; the shared importing / output / job-control foundations). The MP3
Tool items of Plan 8 had been delivered in v0.6.3 with the maintainer's later rulings (two actions
only, blank means blank, Title-derived filenames — `Decisions.md`, 2026-09-12); the "Remove-all
mode", "preserve-majority normalization" and "existing-tag preservation and clear-all-first option"
wordings above were resolved by those rulings and are not separate features.

**What stands unchanged.** The nine-plan structure as history; Plans 1–6 exactly as recorded in the
Master Index; **Plan 9 / v0.6.5 — full visual conversion of the remaining classic panels (TTS
Audiobook, M4B Converter, Cover Image Resizer), macOS parity, QA, docs, packaging and release** — is
unchanged and undrafted, and remains the only release-owning plan. The dependency overview's
`Plans 1–8 ──> Plan 9` edge now reads, in effect, `v0.6.3 (Plan 6 + MP3 Tool) → v0.6.4 (Maker +
Editor) → Plan 9`.

**One further platform ruling recorded for completeness:** the macOS minimum window is **1024×800**
since v0.6.4 Phase 13 (2026-09-15; it was 1024×720 from v0.6.3 Phase 12, and universal 920×600 before
that). Windows remains 920×600. Business behaviour never branches on platform; only presentation does,
behind the theme bundle. Version identity remains `0.6.2`, unreleased; the published GitHub release
remains `v0.4.0`.

**Current action after the Phase 15 closeout:** an independent read-only integration-readiness
recheck of `feature/0.6.4-m4b-maker-metadata-editor`, followed by the maintainer's PR/merge decision
if the recheck returns READY. Nothing here authorizes a merge, release, version bump or the start of
v0.6.5.
