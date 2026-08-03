# Audiobook Creation Tool v0.6.x — Confirmed Decision Register 1–55

**Date:** 2026-07-31  
**Status:** Complete and locked unless a genuine contradiction is discovered during the final source audit.

| # | Confirmed choice | Settled direction |
|---:|---|---|
| 1 | 1A | Keep and modernize tkinter/ttk; meaningful Windows redesign, not a recolor. |
| 2 | 2A | Deliver through several staged v0.6.x releases. |
| 3 | 3A | Committed root `config.toml` for defaults/overrides; mutable state stays in `settings.json`. |
| 4 | 4A | Cooperative Pause/Resume at safe checkpoints. |
| 5 | 5A | Separate Reset Preferences from Clear Downloaded Data. |
| 6 | 6A | Configurable output base with safe unique tool/run folders. |
| 7 | 7A | Optional recursive importing for compatible tools, mirroring source hierarchy. |
| 8 | 8A | User-facing Summary log plus timestamped technical Details. |
| 9 | 9A | Lock job inputs/settings after a run starts. |
| 10 | 10A | Universal safe output rules, with explicit Cover and M4B Maker exceptions. |
| 11 | 11A | Current-run rolling ETA; show `Calculating…` until reliable. |
| 12 | 12A | Each directory directly containing compatible audio files is one book/job. |
| 13 | 13A | Dynamic Add/Duplicate/Remove Book workflow with Previous/Next navigation. |
| 14 | 14A | Shared imported-file manager with add/reorder/remove/clear and standard multi-selection. |
| 15 | 15A | Background cancellable folder scans with live count and large-result confirmation. |
| 16 | 16A | Individual supported-file-type checkboxes rather than A/B/C exclusive choices. |
| 17 | 17A | Cover browser defaults to Details; also simple list and medium thumbnails. |
| 18 | 18A | Chapterless M4B in split mode produces one MP3 with warning. |
| 19 | 19A | M4B Converter defaults to Preserve; modes Preserve, Strip, Replace. |
| 20 | 20B | Populated Shared Metadata always overrides and disables matching per-book controls; visually distinct page. |
| 21 | 21A | Only successful outputs consume sequential automatic numbering. |
| 22 | 22A | MP3 Tool has Combine and Bulk ID3 only; standalone Time Edit removed. |
| 23 | 23A | Bulk ID3 preserves existing tags by default; optional clear-all-first. |
| 24 | 24A | Signed Time remains directly in Bulk ID3; nonzero Time runs even with blank metadata. |
| 25 | 25D | MP3 Combine metadata modes are Preserve-majority or Remove-all. |
| 26 | 26A | Populated Shared Metadata overrides Combine majority/removal results. |
| 27 | 27C | MP3 Combine always removes embedded artwork. |
| 28 | 28A | Continue after book failures; no numbering gaps. |
| 29 | 29A | Shared functionality on both platforms; Windows dark design, macOS Finder appearance. |
| 30 | 30A | M4B Metadata Editor gets one prefilled independent page per imported M4B. |
| 31 | 31A | Individually selected files output flat in one run folder with collision-safe names. |
| 32 | 32A | Code defaults → TOML → allowlisted mutable user settings precedence. |
| 33 | 33A | Itemized downloaded-data cleanup with post-exit deletion where required. |
| 34 | 34A | Broad-root pre-warning plus configurable 1,000-result confirmation. |
| 35 | 35A | Deduplicate within a job, with explicit intentional-duplicate override. |
| 36 | 36A | Normalize majority comparison while preserving a natural original display value. |
| 37 | 37A | Retry Failed only, using frozen run configuration. |
| 38 | 38A | During indivisible stages show Pause requested and pause at next safe boundary. |
| 39 | 39A | Windows prototype is launcher + M4B Metadata Editor with screenshot/functional approval gate. |
| 40 | 40A | Natural-sorted depth-first traversal, direct files before child directories. |
| 41 | 41A | One root mirrors directly; multiple roots use named collision-safe containers. |
| 42 | 42A | Do not follow links/junctions; hidden folders optional; report skipped/unreadable entries. |
| 43 | 43A | Folder imports commit atomically only after scan completion and confirmation. |
| 44 | 44A | M4B Converter uses one batch-wide whole-book or split mode. |
| 45 | 45A | Split chapter filenames begin with padded order number and chapter title. |
| 46 | 46A | Preserve complete source timeline; no silence trimming or replacement gaps. |
| 47 | 47A | Strip is truly empty; Replace split outputs keep generated title/track structure. |
| 48 | 48A | Shared-series auto-numbering with configurable starting part; success-only consumption. |
| 49 | 49A | Duplicate Book copies configuration but starts with an empty MP3 list. |
| 50 | 50A | Confirm Remove Book only when meaningful work would be lost. |
| 51 | 51A | Optional per-book M4B output filename with safe automatic fallback and collision numbering. |
| 52 | 52B | TTS folder batch remains PDF/TXT only; EPUB remains single-file only. |
| 53 | 53A | MP3 Tool uses one batch operation and processes each book job independently. |
| 54 | 54A | Make HEIC/HEIF an officially pinned, probed, tested capability. |
| 55 | 55A | Nine focused instruction drops across six v0.6.x checkpoints. |

## Specific supersession notes

- Decision 52B narrows Decision 16A’s generic TTS example: TTS batch checkboxes are PDF and TXT; EPUB is not part of folder batch.
- Decision 21A supersedes the rough plan’s page-number-based series numbering.
- Decision 13A supersedes the rough plan’s manually entered fixed page count.
- Decision 45A supersedes chapter-number suffix naming because prefix numbering sorts correctly.
- Decision 47A creates a narrow split-mode exception to the rough statement that blank Replace always equals Strip.
- Decision 5A/33A supersede the single combined Restart Program and Clear Data idea.
- The existing architecture decision to retain empty `scripts/Windows/` and `scripts/MacOS/` supersedes the rough suggestion to delete them.
