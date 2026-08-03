# Audiobook Creation Tool v0.6.x — Planning Handoff

**Handoff date:** 2026-07-31  
**Repository:** <https://github.com/elmatthe/audiobook-creation-tool>  
**Repository default branch:** `master` (not `main`)  
**Status:** Requirements clarification is in progress. No source code, branch, issue, pull request, or GitHub file has been changed during this planning conversation.

## 1. Purpose of This Handoff

This file transfers the full v0.6.x planning conversation into a fresh ChatGPT chat in the same Audiobook Creation Tool project space.

The user wants ChatGPT to:

1. Read the rough `audiobook-creation-tool-new-version.md` idea document thoroughly.
2. Inspect the current public repository and the project-space context files.
3. Identify ideas that are unclear, ambiguous, contradictory, duplicative, risky, or already implemented.
4. Ask focused multiple-choice questions, with a clearly identified recommendation for each material choice.
5. Add sensible improvements that make the application cleaner, easier for non-technical users, and more reliable without adding unnecessary complexity.
6. Turn the settled requirements into a staged series of implementation-plan Markdown files for `md-instructions/`.
7. Ultimately guide Codex and Claude Code through implementation, verification, manual testing, documentation, and staged v0.6.x GitHub releases.

This handoff is **not yet an implementation plan**. The next chat should continue clarifying unresolved requirements before drafting the actual instruction drops.

## 2. Files and Sources to Read in the New Chat

The new chat is in the same project space. It should read the latest available copies of:

- This handoff file.
- `audiobook-creation-tool-new-version.md` — the user's rough v0.6.x idea plan.
- `AI-WORKSPACE.md` — the authoritative repository/agent workflow rules. It is gitignored and was not available during the first review; obtain/read the current project-space copy before writing final implementation plans.
- `Vibe-Coding_Chat_Workflow.md`.
- `Briefing.md`.
- `handoff.md` — the repository's existing development handoff, distinct from this planning handoff.
- `CHANGELOG.md`.
- `DECISIONS.md`.
- `README.md`.
- The current `master` branch of <https://github.com/elmatthe/audiobook-creation-tool>.
- Relevant current source, especially `launcher.py`, `shared/ui_theme.py`, `shared/paths.py`, `shared/settings.py`, `shared/cancellation.py`, `shared/metadata.py`, `m4b_maker.py`, `m4b_converter.py`, `mp3_tool.py`, `m4b_metadata_editor.py`, `cover_resizer.py`, both setup launchers, `requirements.txt`, and `verify.py`.

If `AI-WORKSPACE.md` or `audiobook-creation-tool-new-version.md` cannot be accessed in the new chat, ask the user to attach the current copy before producing the final implementation-plan files. Do not guess at their missing rules or requirements.

## 3. Confirmed Repository Baseline

The earlier read-only review established the following:

- The GitHub default branch is `master`, not `main`. Future branches and pull requests must start from and target `master` unless the repository changes later.
- The working code line is v0.5.1 on `master`; v0.4.0 remains the latest published GitHub release.
- The application is one shared Python codebase for Windows and macOS.
- The GUI uses tkinter/ttk. Each of the six tools exposes a stable `build_ui(parent)` boundary inside a unified launcher.
- Platform appearance is already centralized in `shared/ui_theme.py`.
- Shared modules already centralize paths, user settings, metadata, ffmpeg, cancellation, logging, and theme behavior.
- All six tools already have shared progress indicators and Cancel support.
- TTS folder importing already supports recursive PDF/TXT discovery and mirrored output subfolders.
- Existing shared foundations should be extended; v0.6.x must not duplicate or rebuild them unnecessarily.
- Long operations already use worker threads, queues, main-thread-only Tk updates, and cooperative cancellation. Pause/Resume should extend this pattern safely.
- The application targets non-technical users: one-click setup, no visible console windows during normal use, pinned dependencies, safe defaults, and no destructive surprises.

## 4. Overall Direction Already Locked

- Keep tkinter/ttk; do not adopt CustomTkinter or PySide6 for v0.6.x.
- Create a genuinely redesigned Windows interface, not merely a recolored version of the current layout.
- Keep macOS's existing Finder-style appearance while adding the same new functionality on both platforms.
- Deliver the complete feature program through several staged v0.6.x releases rather than one enormous release branch.
- Add a committed root `config.toml` containing documented application defaults and supported runtime overrides.
- Keep mutable per-user choices, last-used state, paths, and window state in the existing gitignored `settings.json`.
- Keep requirements clarification and planning read-only until the plan series is approved.

## 5. Complete Decision Record

### Round 1 — Core Architecture

#### 1A — Modernize existing tkinter/ttk

Confirmed. The Windows UI will use the existing toolkit and shared `ui_theme.py` boundary.

Requirements:

- Create a coherent Windows design system using dark navy/charcoal surfaces, restrained blue accents, high-contrast text, consistent cards, typography, spacing, field grouping, and clear primary/secondary/danger button roles.
- This must be a meaningful layout and visual-hierarchy redesign, not a flat black recolor.
- Start with a Windows prototype covering the launcher plus one complex tool.
- Obtain screenshot approval before converting all remaining tools.
- If the prototype still looks dated or requires brittle workarounds, stop and reassess the toolkit choice before converting the whole application.
- macOS keeps its existing Finder-style appearance.

#### 2A — Several staged v0.6.x releases

Confirmed. Build and verify the feature set through multiple v0.6.x checkpoints so `master` remains usable and manual testing can occur between stages.

The previously suggested release grouping was only illustrative—foundations/UI, universal importing/output, converter upgrades, multi-book workflows, and final hardening. The exact v0.6.0–v0.6.x mapping still needs to be designed after clarification finishes.

#### 3A — `config.toml` provides defaults and runtime overrides

Confirmed.

- Commit `config.toml` at the repository root.
- Use it for documented application defaults and supported runtime overrides.
- Keep mutable user state in gitignored `files/runtime-data/settings.json`.
- Include `config.toml` in release ZIPs.
- Validate it safely. Missing, malformed, or invalid values must fall back to known defaults and produce a useful warning rather than preventing startup.
- Do not rewrite the committed TOML whenever a user changes something in the GUI.

### Round 2 — Runtime Behavior and Safety

#### 4A — Safe checkpoint Pause/Resume

Confirmed.

- Pause cooperatively at the next safe file, chapter, chunk, or encoding-stage boundary.
- Resume within the same application session.
- Do not attempt unsafe instantaneous worker/subprocess freezing.
- Completed work must not be restarted unnecessarily.

#### 5A — Separate reset and cleanup actions

Confirmed.

- `Reset Preferences` restores application/user settings.
- `Clear Downloaded Data` separately removes selected regenerable runtime assets such as models, downloaded binaries, logs, and the virtual environment.
- Data cleanup requires stronger confirmation and must explain what will need to be downloaded/rebuilt on the next launch.
- Resetting preferences must not unexpectedly delete gigabytes of runtime data.

#### 6A — Configurable output base with unique folders

Confirmed.

- Default base path on Windows: `Downloads\Audiobook-Creation-Tool-Outputs\`.
- `config.toml` may override the default base.
- Normal operations create collision-safe tool and run folders beneath the base, conceptually:

  `Downloads\Audiobook-Creation-Tool-Outputs\<Tool>-Outputs\<Tool>-N\`

- Never silently overwrite an existing output.
- One-run output exceptions for Cover Image and M4B Maker are recorded under Decision 10.

#### 7A — Optional recursion for compatible tools

Confirmed.

- Compatible batch tools receive an `Include subfolders` option.
- Enable it by default where recursive discovery is safe.
- Mirror relevant input hierarchy in output for folder imports.
- Order-sensitive book workflows must interpret folders as book jobs and must not silently flatten or scramble chapter order.

### Round 3 — Logs, Controls, and Output Consistency

#### 8A — Milestone Summary plus timestamped Details

Confirmed.

- Summary view: current stage, progress, warnings, failures, output location, and completion.
- Detailed view: timestamped per-file activity, subprocess information/output where useful, and diagnostics.
- Do not overwhelm the Summary view with every file or raw background command.

#### 9A — Lock job settings while processing

Confirmed.

- Inputs and processing options become read-only when a run starts.
- Pause, Resume, Cancel, log-view controls, and Open Output remain available as appropriate.
- One batch must not silently use multiple configurations because settings changed mid-run.

#### 10A — Universal safe output rule, amended twice

The default remains safe, unique output folders under the configured base, with two explicit opt-in exceptions.

**Cover Image behavior:**

- Default output: `Downloads\Audiobook-Creation-Tool-Outputs\Cover-Image-Outputs\Cover-Image-N\`.
- Optional `Save beside source images` mode.
- When source-folder mode is enabled, offer two explicit choices:
  - `Create numbered copies`: for example, `cover-1.jpg`, then `cover-2.jpg`.
  - `Replace original files`.
- Replacement must never be selected by default.
- The user must deliberately enable source-folder mode and choose replacement before originals may be changed.

**M4B Maker behavior:**

- Default output: `Downloads\Audiobook-Creation-Tool-Outputs\M4B-Maker-Outputs\M4B-Maker-N\`.
- Optional `Choose custom destination` toggle.
- Browse/destination controls appear only when the toggle is enabled.
- In custom-destination mode, completed `.m4b` files go directly into the chosen directory; do not create another `M4B-Maker-N` folder inside it.
- Never replace imported MP3 source files.

### Round 4 — ETA and Multi-Book Organization

#### 11A — Current-run rolling ETA

Confirmed.

- Show `Calculating…` initially.
- After enough comparable work completes, calculate remaining time from a rolling current-run average.
- Recalculate after each meaningful file/stage.
- When an estimate is not trustworthy, continue showing `Calculating…` rather than a misleading value.

#### 12A — Each directory containing compatible files directly is one book

Confirmed for order-sensitive multi-book folder imports such as M4B Maker and MP3 Tool.

- Every directory that directly contains compatible audio files becomes one book/job.
- Natural-sort files inside each directory (`1, 2, 3 … 10`, not `1, 10, 2`).
- Do not combine separate book directories into one unintended audiobook.

#### 13A — Dynamic Add Book workflow

Confirmed.

- Begin with one book job.
- Provide `Add Book`, `Duplicate Book`, and `Remove Book`.
- Provide Previous/Next navigation and a visible `Book X of Y` counter.
- Folder import creates the necessary book jobs automatically.
- Empty/invalid jobs are identified clearly and skipped safely at run time.

### Round 5 — Universal Importing

#### 14A — Full shared imported-file manager

Confirmed for compatible tools.

- `Add Files`
- `Add Folder`
- `Move Up`
- `Move Down`
- `Remove`
- `Clear All`
- Normal click, Ctrl/Command-click, and Shift-click selection.

The controls should be implemented as reusable shared UI/logic rather than independently reinvented in every tool.

#### 15A — Background, cancellable large-folder scans

Confirmed.

- Folder scans must not freeze the GUI.
- Show a live discovered-file count.
- Provide `Cancel Import` separately from canceling a processing job.
- Ask for confirmation before adding an unusually large result set.
- Do not impose a hard maximum; the warning threshold remains an implementation/configuration detail to settle later.

#### 16A — Individual supported-file-type checkboxes

Confirmed.

- Show one checkbox per supported input type.
- Enable all supported types by default.
- Allow any combination.
- Examples: PDF/TXT/EPUB for compatible TTS importing; JPG/JPEG/PNG and supported HEIC/HEIF formats for Cover Image.

### Round 6 — Cover Browser and M4B Converter

#### 17A — Cover Image opens in Details view

Confirmed.

- Default columns: filename, dimensions, format, file size, and folder.
- Allow switching to a simple-path list or medium thumbnails.
- Do not default to thumbnails because large imports could become slow.

#### 18A — Chapterless M4B produces one MP3

Confirmed.

- In split mode, an M4B with no usable chapter markers produces one MP3.
- Show a clear warning.
- Continue the rest of the batch.

#### 19A — Preserve metadata by default

Confirmed for M4B Converter.

- Modes are mutually exclusive: Preserve, Strip, or Replace.
- Default to Preserve.
- Split chapters inherit compatible book metadata and receive chapter titles and track numbers.

### Round 7 — Multi-Book Processing

#### 20B — Populated Shared Metadata always wins

Confirmed, including a visual requirement.

- Any populated Shared Metadata field overrides the corresponding per-book value.
- Disable the matching per-book control so the precedence is visually and behaviorally clear.
- A blank shared field leaves the per-book field usable.
- The Shared Metadata page/section must be visually distinct from normal book pages through a muted accent background, border, and header treatment that fits the dark theme.
- The unique shading should let a user instantly recognize that this is the universal/global page, even before reading its label.

#### 21A — Number completed books sequentially

Confirmed.

- Only successful outputs receive automatic series numbers.
- Skipped, empty, invalid, canceled-before-start, or failed jobs do not create gaps.

#### 22A — One MP3 Tool operation per batch, modified

Confirmed with a major simplification.

- MP3 Tool will have two batch operations only:
  - `Combine`
  - `Bulk ID3`
- Remove standalone `Time Edit` as a separate operation.
- Preserve time adjustment within Bulk ID3 because the current `Write ID3 Tags` workflow already applies it.
- Remove only the redundant separate Time Edit action/path; do not remove the proven timing capability from Bulk ID3.

### Round 8 — MP3 Tool Details

#### 23A — Bulk ID3 preserves existing tags by default, amended

Confirmed.

- Blank metadata fields preserve the corresponding existing tag.
- Provide an optional `Remove all existing metadata` checkbox.
- When enabled, clear existing metadata first, then write only nonblank values supplied by the user/shared fields.
- Never rename the input file as a side effect of tag editing.

#### 24A — Signed Time field, no enabling checkbox

Confirmed.

- Keep a directly actionable Time field inside Bulk ID3.
- Positive value adds time to the track ending.
- Negative value removes time from the track ending.
- `0` means no timing change.
- Pressing `Write ID3` must apply the Time value even if every metadata field is blank.
- Example confirmed by the user: entering `03.7` and nothing else, then pressing `Write ID3`, applies the timing operation to all targeted files.
- Do not add an extra checkbox merely to enable timing; zero already represents disabled/no change.

#### 25D — Combine metadata modes: Preserve majority or Remove all

This was a user-defined option beyond A/B/C and is confirmed.

- Provide two mutually exclusive Combine metadata modes:
  - `Preserve existing metadata`: choose the most abundant value separately for each compatible tag across the ordered input files.
  - `Remove all metadata`: start with blank metadata.
- If two or more values tie for the highest count for a tag, leave that output tag blank.
- The user chooses the combined output filename when Combine is run.
- Embedded cover artwork follows Decision 27 and is always removed.

### Round 9 — Metadata and Failure Handling

#### 26A — Shared Metadata wins during Combine

Confirmed.

- Populated Shared Metadata fields override the values chosen by Preserve-majority.
- Blank shared fields use Preserve-majority results in Preserve mode.
- In Remove-all mode, clear metadata first and then apply any populated Shared Metadata fields.
- Therefore, `Remove all` means remove inherited metadata; it does not suppress explicit shared values the user entered.

#### 27C — Always remove embedded cover artwork during MP3 Combine

Confirmed.

- Strip embedded artwork in both Preserve-majority and Remove-all modes.
- Text-tag preservation does not imply artwork preservation.

#### 28A — Continue after multi-book failures without numbering gaps

Confirmed.

- Report the failed book clearly.
- Continue processing later jobs.
- The next successful output receives the next sequential series number.

### Round 10 — Platform Parity, M4B Metadata, and Manual-File Outputs

#### 29A — Shared functionality, platform-specific appearance

Confirmed in the final message of this chat.

- Every v0.6.x workflow feature must function on both Windows and macOS.
- Windows receives the redesigned dark navy/charcoal theme.
- macOS retains its existing Finder-style appearance.
- Do not fork business logic or create Windows-only workflow implementations when the shared codebase can support both.

#### 30A — Prefilled independent M4B Metadata pages

Confirmed in the final message of this chat.

- Every imported M4B receives its own page.
- Prefill the page with that file's existing metadata and chapter titles so the user can see what the output will contain.
- Populated Shared Metadata fields override and disable matching per-book fields, consistent with Decision 20B.
- Per-book chapter titles and other non-overridden fields remain independently editable.

#### 31A — Flat run folder for individually selected files

Confirmed in the final message of this chat.

- When files are selected individually from multiple source locations, write their outputs directly into one unique run folder.
- Never overwrite on filename collision.
- Resolve collisions with safe numbered names such as `Book-1.m4b`, `Book-2.m4b`.
- Do not recreate source-parent directory trees for individually selected files.
- Mirrored directory structures remain reserved for folder-import workflows.

## 6. Important Cross-Cutting Rules

These apply across the eventual plans:

- Preserve one shared Windows/macOS codebase and shared business logic.
- Keep Tk access on the main thread; workers communicate through queues/events.
- Pause and cancellation must happen at explicit safe checkpoints and clean partial outputs.
- Do not allow a paused job to hold unsafe half-written state indefinitely.
- Keep default operations copy-based and non-destructive.
- Any destructive or source-modifying option must be explicit, off by default, and clearly confirmed.
- Never silently overwrite outputs. Use unique run directories and collision-safe names.
- Use natural sorting for ordered chapter/audio files.
- Keep normal logs understandable while retaining detailed diagnostics.
- Make very large imports responsive and cancellable.
- Keep setup simple for non-technical users and preserve no-visible-console behavior.
- Pin dependencies exactly and use existing shared infrastructure before adding new dependencies.
- Update tests and the repository verification gate with each implementation phase.
- Final plans must follow `AI-WORKSPACE.md` and `Vibe-Coding_Chat_Workflow.md`, including small phases, stop-and-report boundaries, manual-test checkpoints, documentation updates, and deletion of temporary instruction drops at completion.

## 7. Matters That Are Not Yet Finalized

The next chat should continue the numbered multiple-choice process rather than immediately writing implementation plans.

At minimum, it should re-read the rough plan and determine which material decisions remain. Likely planning details still requiring confirmation or an explicit design recommendation include:

- Remaining tool-specific behavior from the rough plan that was not covered in Decisions 1–31.
- Exact staged release boundaries and branch/drop names across v0.6.0, v0.6.1, and later v0.6.x releases.
- The final `config.toml` schema, supported keys, precedence rules, warning presentation, and which values should remain user-only settings.
- The exact contents and safety model of `Clear Downloaded Data`, including assets that cannot be removed while the application is running.
- The large-import warning threshold and whether it belongs in TOML.
- Natural-sort, filename-collision, and duplicate-file policies at edge cases.
- Metadata normalization used by Preserve-majority: whitespace/case normalization, unsupported tags, dates, multi-value tags, and conflicting embedded data.
- Queue cancellation/failure behavior at job boundaries, retry affordances, and what Pause means during long single ffmpeg stages.
- Manual acceptance criteria for the Windows UI prototype and macOS feature-parity testing.
- Exact mapping of existing rough-plan requests to: already implemented, extend, modify, postpone, or reject.

Do not reopen confirmed choices merely to ask them again. Reopen one only if the current repository or rough plan exposes a genuine contradiction, and explain the conflict precisely before asking.

## 8. Required Final Planning Deliverables (After Clarification)

Once all material choices are settled, ChatGPT should produce a coordinated series of Markdown instruction drops for `md-instructions/`. The exact names and release grouping remain to be designed, but together they must cover:

- Shared configuration and settings precedence.
- Shared UI design system and the Windows prototype/approval gate.
- Pause/Resume, logs, ETA, locking, reset, and data cleanup.
- Shared importing/file-manager infrastructure and responsive recursive scans.
- Output-path and collision-safe naming infrastructure.
- Cover Image upgrades.
- M4B Converter upgrades.
- M4B Maker multi-book workspace and output choices.
- MP3 Tool simplification, Combine, Bulk ID3, timing, metadata precedence, and multi-book handling.
- M4B Metadata Editor shared/per-book pages.
- Cross-platform regression coverage.
- Documentation, packaging, staged releases, and final manual test matrix.

Each drop should contain context, goals, in/out scope, implementation constraints, small independently verifiable phases, tests, manual checks, documentation duties, and a definition of done. Coding agents must implement one phase, stop, and return the required summary for user review before continuing.

## 9. Immediate Next Action for the New Chat

1. Read this handoff and the current project-space files listed in Section 2.
2. Confirm that Decisions **29A, 30A, and 31A** are recorded.
3. Keep the repository read-only.
4. Continue the clarification interview with the next logical three or four numbered multiple-choice questions, starting at **32**.
5. Give a recommendation for every question and briefly explain the tradeoff.
6. Do not draft the large implementation-plan series until the remaining material questions are answered.

## 10. Compact Continuation Summary

The user is redesigning and substantially extending the current cross-platform Audiobook Creation Tool for staged v0.6.x releases. The project will keep tkinter/ttk, gain a professional dark Windows design, keep the Finder-style macOS appearance, add a committed `config.toml` plus existing mutable `settings.json`, and extend the current shared architecture rather than rebuild it. Thirty-one decisions are settled, including safe checkpoint Pause/Resume, separate reset/cleanup, unified output defaults with explicit Cover Image and M4B Maker exceptions, responsive universal importing, multi-book jobs, Shared Metadata precedence and visual distinction, M4B Converter preservation rules, MP3 Tool simplification to Combine/Bulk ID3, signed timing inside Bulk ID3, majority-tag preservation for Combine, artwork removal, continue-on-failure numbering, cross-platform feature parity, prefilled per-M4B metadata pages, and flat safe output for individually selected files. Continue with Decision 32 onward; do not implement yet.
