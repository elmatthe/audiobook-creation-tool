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
