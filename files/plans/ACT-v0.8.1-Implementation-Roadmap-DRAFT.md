# Audiobook Creation Tool v0.8.1 — Implementation roadmap (planning draft)

**Status:** UI colors and file-dialog persistence APPROVED by owner November 17, 2026. **OmniVoice mass-test diagnosis remains evidence-dependent** until the owner sends the complete failed-chapter list and technical logs. **This is NOT a request to begin implementation or a release authorization.**

**Repository:** `https://github.com/elmatthe/audiobook-creation-tool`  
**True default branch:** `master` (not `main`)  
**Planned release branch:** exact name `0.8.1`, created only after v0.8.0 macOS compatibility is accepted, Windows reverified, and approved source integrated into `master`. Do not assume the release branch exists already.  
**Build order:** HOME-PC Windows implementation → native macOS implementation/acceptance → final HOME-PC Windows full gate (one canonical run) → fresh independent Codex review on HOME-PC → maintainer approval → integration and Windows/macOS ZIP release artifacts.

## 1. Approved non-negotiable UI decisions

### Button colors are OUTLINED, never solid-filled

- A / **Red**: red text **and red border** on the same neutral base fill as a normal button. Clear, Remove, Reset, Cancel, user-selected destructive controls.
- B / **Green**: green text **and green border**, neutral base fill. Start, Build, Save, process/installation trigger where owner selected B.
- C / **Yellow**: yellow text **and yellow border**, neutral base fill. Pause, Resume, Retry and owner-selected retry controls.
- D / **Blue**: blue text **and blue border**, neutral base fill. Ten Book navigation/creation selections across three tools, plus special setup/repair actions.
- E / **Normal**: normal text/border/fill. Secondary utility and navigation controls.

**Mimic the existing red-outline buttons visible in the owner's `M4B-Metadata-UI-(DARK).png`, with the new colors applied to TEXT AND BORDER ONLY.** No solid red/green/yellow/blue background on normal, hovered, pressed, focused, selected, alternate/default or disabled state. If a hover/press needs feedback, use neutral tonal changes only, not semantic-colored fill; ensure semantic text/border remain legible. Disabled buttons must remain visually disabled; preserve distinct focus indication independent of semantic border. Provide coherent Light and Dark versions and pass real Tk/ttk visual validation on Windows and Aqua/macOS. Never assume macOS native ttk background/border overrides work without inspection. **Native Finder/File Explorer buttons belong to the operating system and are excluded from recoloring.**

The current shared `scripts/shared/appearance.py` Danger.TButton already uses a neutral fill at rest, but changes fill to red on hover/press; this existing state map must be reconciled with the owner's stricter all-state requirement. Do not turn Preferences Save into a filled green button; it must match the same outline rule.

### File-dialog persistence, all five approved A answers

1. **Missing/unmounted saved directory:** fall back to existing documented initial folder (or the user's home folder where appropriate), and preserve the saved entry until the next successful selection. Never create a replacement folder or erase user state merely because a volume is temporarily unavailable.
2. **Cancel:** no changes to saved directory history; update only upon user confirmation of a valid file or folder selection. File chooser stores parent of the selected file; folder chooser stores selected folder.
3. **Schema:** explicit, namespaced `tool.action` keys in existing `files/runtime-data/settings.json` using `scripts/shared/settings.py`. Preserve existing keys and values; register exact new keys in `scripts/shared/config.py`'s `USER_STATE_SETTINGS` allowlist; do not add a config.toml overlay or rework the schema.
4. **Other/custom destination dialogs:** separate per-tool destination key, distinct from same tool's import/artwork history. Preferences output-location browser is distinct from the runtime output-directory setting.
5. **Windows/macOS:** independent local histories per installation. Never translate Windows paths to macOS or share them across machines.

Every tool has independent import history shared between Add Files / Add Folder / Import Folder. All Shared and Current Book artwork selectors in a given tool use that tool's single artwork-history key, independently of importing. Cover Image's imported images are SOURCE IMPORTS, not book-artwork selection.

## 2. Code landmarks verified during planning (reinspect after v0.8.0 integration)

- `scripts/shared/settings.py` — atomic `settings.json` writes and reset. `reset()` clears only persisted preferences and does not remove media, outputs or downloaded engine data.
- `scripts/shared/config.py` — exact `USER_STATE_SETTINGS` allowlist; tracked AST tests assert it corresponds to writers.
- `scripts/shared/appearance.py` — existing button semantic roles: `button`, `primary_button`, `danger_button`, `ghost_button`, `nav_button`. Add limited reusable **outline** success/warning/info roles as needed and reconcile current danger hover/pressed behavior.
- `scripts/shared/job_ui.py` — shared ImportedFileList, ImportStatusBar and JobControlBar; avoid manually assigning styles everywhere when shared components cover them.
- `scripts/shared/book_workspace_ui.py` — BookNavigator. Map Previous/Next/Add/Duplicate = blue in MP3 Tool/M4B Maker; Previous/Next = blue in Metadata; Remove Book = red. Keep app sidebar navigation normal/uncolored.
- `scripts/artwork/m4b_artwork_ui.py` — shared choose/clear artwork controls; passed-in per-tool chooser must persist tool-specific directory history.
- `scripts/mp3/mp3_tool.py` — confirmed defect: artwork chooser currently starts at `KEY_INPUT_DIR` and does not remember a separate artwork path. Add `mp3_tool.cover_dir`, and never use the import key for artwork.
- `scripts/m4b/maker/m4b_maker.py` and `scripts/m4b/metadata/m4b_metadata_editor.py` — existing `*.input_dir` and `*.cover_dir` working patterns; preserve and share across each tool's artwork areas.
- `scripts/m4b/converter/m4b_converter.py`, `scripts/artwork/cover_resizer.py` — existing tool-specific import history.
- `scripts/tts/epub2tts_gui.py` — TTS file/folder chooser currently has no explicit `initialdir`/settings update. Add one scoped TTS import key.
- `scripts/m4b/maker/m4b_maker.py` custom destination chooser currently has no `initialdir`/settings update. Add independent destination key.
- `scripts/shared/preferences_ui.py` — custom output folder chooser currently has no independent browsing history; preserve separation between browsing and saving a new output location.
- `scripts/tts/omnivoice_synth.py`, `scripts/tts/omnivoice_worker.py`, `scripts/tts/worker_limits.py` — OmniVoice diagnosis and potential remediation, ONLY after reading actual failures.

Candidate new setting keys (agent may refine naming consistently without changing semantics): `tts.input_dir`, `mp3_tool.cover_dir`, `m4b_maker.destination_dir`, `preferences.output_browse_dir`, plus any other real browse actions found in a complete source/runtime inventory. Preserve exact historic keys: `cover_resizer.input_dir`, `m4b_converter.input_dir`, `m4b_maker.input_dir`, `m4b_maker.cover_dir`, `m4b_metadata.input_dir`, `m4b_metadata.cover_dir`, `mp3_tool.input_dir`. Avoid adding unused settings keys; tie all allowlisted keys to actual production writers and tests.

## 3. Bounded Claude Code implementation phases

**Process:** Each phase is sized for one fresh or appropriately compacted Claude Code terminal session, with a single bounded objective, focused tests, commit and push on `0.8.1`, and `Handoff.md` / `Decisions.md` updates. If the phase exposes a genuine blocker, stop and report with evidence; do not silently expand scope or fake verification. Follow the repo's current `AI-WORKSPACE.md`, `AGENTS.md`, `md-instructions/Handoff.md`, branch safety and scratch containment. No production branch merge, tag, package publishing, engine installation or protected data changes without approval.

### Phase 0 — v0.8.0 prerequisite and clean v0.8.1 branch (ONE session)

- Finish and accept macOS 0.8.0 consolidation independently of v0.8.1; conduct its planned Windows HOME-PC regression verification; obtain the owner's approval for integration into actual `master` (not fictitious `main`).
- On HOME-PC, fetch and inspect exact Git state; preserve local files and protected audio. Create the **exact named** branch `0.8.1` at the accepted `master` tip only after approval. Record SHA/branch provenance. Do not re-open accepted 0.8.0 work unless it is a blocking regression.
- Add a concise plan/checkpoint reference (approved by maintainer) and a bounded entry in handoff; keep untracked/private work intact.

### Phase 1 — Windows file-dialog persistence (ONE session)

- Inventory every production `filedialog.askopenfilename`, `askopenfilenames`, `asksaveasfilename`, `askdirectory` and other OS chooser call, including conditional dialogs/setup utilities. Make an explicit list of tool, action, key, dialog type, old behavior, new behavior; identify native/no-path dialogs as exclusions.
- Implement smallest shared helper if it reduces duplicated code; otherwise use existing `settings.get/set` consistently. On every invocation, validate saved `Path.is_dir()` with fail-safe behavior for inaccessible/unmounted paths; choose safe home/default fallback WITHOUT rewriting saved entry.
- Update saved history ONLY after a nonempty valid confirmed chooser result. Cancel, chooser error, invalid selection, declined processing and source rejection must not overwrite saved history. Avoid unnecessary path canonicalization, unexpected directory creation or accidental cross-tool fallback.
- Preserve existing per-tool `*.input_dir` / `*.cover_dir`; add MP3 artwork key, TTS import key, Maker destination key and Preferences custom output chooser history as appropriate. Ensure Shared Artwork and Current Book Artwork share the same tool-level key; `Add Files` and `Import Folder` share a different tool-level key.
- Honor `Reset Preferences` clearing only the saved keys; validate old settings files/malformed values, failed atomic write, unavailable/removable/network volumes, user home fallback, cross-session and multi-tool independence. Never write to `config.toml`.
- Tests: isolated settings path, existing-key migration, exact allowlist AST, each chooser type, invalid/cancel/unmounted, app restart, Windows dialog injection/mocking plus real manual Windows File Explorer acceptance. Checkpoint push and report.

### Phase 2 — Windows color taxonomy and shared controls (ONE session)

- Create/adjust shared semantic outline styles centrally in `scripts/shared/appearance.py`, with typography, padding, border and neutral background matching M4B Metadata red outline. Include light/dark, normal, hover, pressed, focus, alternate/default and disabled maps. No colored fill in ANY state.
- Wire labels/roles in shared `JobControlBar`, `ImportStatusBar`, `ImportedFileList`, `BookNavigator`, `m4b_artwork_ui` and individual execution buttons/settings panels. Avoid setting styles by text alone when intent differs; use stable action keys / explicit role arguments. Update existing Primary/Save semantics where the owner chose green outline; leave global shell navigation normal.
- Apply exact approved 146-button inventory (Appendix A), including 10 deliberate blue departures from original recommendations and all conditional/secondary dialogs. For conditional popups, ensure dynamically-created buttons and theme toggles keep roles; no dead/incorrect styles on hidden/disabled buttons.
- Maintain layout/density/responsiveness, accessibility/keyboard focus, action behavior, cancel availability, previews and dynamic theme switching. Native OS dialog buttons remain unchanged.
- Tests: theme definitions/mappings and interaction state tests plus manual Windows 11 screenshots for all seven panels, Preferences and representative conditional setup dialogs at both light and dark settings. Audit all 146 mapped source controls (some represent conditional named actions), record any newly discovered buttons in a supplemental inventory rather than guessing. Checkpoint push and report.

### Phase 3 — Windows OmniVoice failure diagnosis and bounded remediation (ONE diagnostic session; ONE implementation session if a cause is confirmed)

- Wait for owner to supply final mass-run failures (filenames) PLUS detailed technical logs where possible, including event stage, chunk index, worker batch index, exception, GPU allocations/reservations, subprocess and encoder diagnostics. Do not assume TXT is corrupt or OOM; seven sample TXT files were valid UTF-8, with ordinary paragraphs and no NULs.
- Treat the filename-only Summary as insufficient for causal proof. Reproduce representative categories in a repo-contained ignored scratch area on HOME-PC 12 GB VRAM, without reprocessing 2,342 copyrighted chapters or modifying the owner's output. Never commit novel text, generated audiobooks, model binaries or private logs.
- Investigate deterministic seed, long sentences, worker lifetime (300-character chunks / batches of up to 48), CUDA fragmentation, model-specific generate exceptions, error propagation, invalid/partial audio, MP3 encoding, timeouts and cancellation. Capture before/after evidence and classify transient/recoverable vs permanent.
- Implement minimal justified change(s): e.g. bounded retry of an isolated chunk after a fresh worker *only if safe*; atomic output and complete text coverage must remain mandatory. Do not silently skip text, alter model/reference version, decrease quality, suppress exceptions, change seed on normal success, or retry endlessly. Permit a separate maintainer decision if the evidence calls for a bigger engine change.
- Add deterministic failure-injection unit tests, targeted real OmniVoice regression tests using the provided failed examples where licensed/private local tests are allowed, and assert preserved output/rollback, cancel, Pause/Resume, retry, memory/worker boundedness, and actionable failure details.
- If evidence never confirms a remediable defect, document that outcome and DO NOT invent a fix; still improve specific diagnostics if demonstrably deficient. Push checkpoint and report.

### Phase 4 — Windows integration of the three v0.8.1 changes (ONE session)

- Review exact branch history, run focused suites for settings/chooser/theme/shared UI/OmniVoice, inspect affected GUI controls in light/dark and real Explorer, verify no omitted roles or untested failure path. Address focused failures in-scope. No canonical Full gate here.
- Verify `Reset Preferences`, preferences Save, per-tool history, tooltip/focus semantics, dynamic dialogs, and no output/media regressions. Produce Windows-focused acceptance checklist and Mac handoff, push integrated checkpoint.

### Phase 5 — Native macOS adaptation and verification (ONE session on HOME-MacOS, extend only for real platform blockers)

- Fetch the Windows-verified v0.8.1 branch on the Apple Silicon Mac. Adapt only OS-specific behavior: Finder's chosen initial directory, inaccessible/unmounted volume fallback, native Aqua themed border/text rendering (including hover/focus/disabled), file dialog cancel, appearance switching and compact layout. Native Finder system controls remain OS-colored.
- Verify all seven tool surfaces, Preferences, representative conditional dialogs, saved per-tool/action directories after complete app quit/relaunch, cross-tool isolation, bad path resilience, and Reset Preferences. Run relevant macOS focused tests and manual Apple Silicon smoke checks, including model tests only if the engine is available and safe to run; do not claim Windows CUDA results apply to Mac MPS.
- Do not modify macOS bootstrap/dependencies without a separate narrowly justified approval. Push exact macOS implementation SHA and report platform differences, leaving `0.8.1` ready for Windows final validation.

### Phase 6 — ONE canonical full verification gate at the final combined HEAD (ONE Windows session)

- On HOME-PC fetch the Mac-finished `0.8.1` HEAD. Run targeted Windows spot checks for the integrated Mac edits, then run **the full verification gate once** against that exact combined SHA; save all reports, command, timestamp, environment and SHA in repo-contained ignored evidence. Do NOT require every historical unrelated failure to become green before considering this scoped release: categorize baseline known issue vs introduced regression vs environment issue vs not executed.
- A new regression in core behavior, source data integrity, settings or UI should remain a blocker, even if the gate reports baseline failures. Any risk acceptance/exception belongs to the owner, not Claude or Codex. No further canonical Full gate is planned without explicit maintainer approval.
- If follow-on changes after this gate occur, identify exactly what checks are stale and rerun relevant focused tests. If material late changes invalidate the gate's coverage, STOP and ask for approval to rerun the full gate rather than claiming the previous result applies to the new HEAD.

### Phase 7 — LAST confirmation: independent Codex review on HOME-PC Windows (ONE fresh Codex session)

- Independent from Claude's implementation. Review exact final SHA, all commits/diff, approved 146-button matrix, 5 path-history decisions, UI/OS consistency, tests and full-gate report. Run bounded independent adversarial tests and inspect current Windows GUI; no second automatic full gate.
- Priority checks: mistaken artwork history coupling, permission/unmounted path fallback, cross-session persistence, accidentally colored button fills in pressed/hover/Aqua states, missing conditional buttons, controls that lose theme style on live update, red Cancel interaction correctness, partial MP3, irreversible output overwrite, unbounded retries and memory handling.
- Codex writes an independent PASS/FAIL review report with reproducible evidence. If FAIL, return blockers for bounded Claude remediation and owner-controlled re-verification; Codex PASS is not itself a merge authorization. If PASS, present for maintainer manual acceptance; no automatic merge or release.

### Phase 8 — Owner-approved integration and two official ZIPs (ONE release session after approval)

- Owner personally accepts Windows + macOS manual behavior and independent Codex evidence. Only then merge/fast-forward per actual approved integration policy to **master**, record provenance, create tag `v0.8.1` and official distinct Windows/macOS ZIP archives using repository release tooling. Audit archive members, hashes, paths, launchers, platform assets and clean extraction, and publish only with separate explicit release approval.
- Keep v0.8.0 assets and user's existing outputs/models untouched. Do not assume macOS gate outcome from Windows, nor assume an artifact exists before it is actually built and verified.

## 4. Scope boundaries and acceptance

- **In:** remembered browse folders, semantic outline button colors for approved UI controls, evidence-driven OmniVoice failure diagnostics/remediation, minimal regression tests, platform validation and release packaging upon approval.
- **Out:** UI redesign, changing generation voices/presets or speech quality without proven need, rewriting any user-provided chapters, changing file import/processing data semantics, dependency/model installation without approval, cleanup of personal directories, output deletion, previous release changes, moving from `master` to `main` or force pushing.
- **Windows acceptance:** all 146 approved button roles accounted for; ten specified blue deviations visible; no colored background fills in any state; paths scoped per tool/action and persist across restarts; canceled selectors do not update; unavailable paths fall back without erasing settings; source media and successful outputs preserved; focused tests pass, full gate run ONCE and failures reported precisely.
- **Mac acceptance:** same behaviors under native Finder/Aqua both dark/light; paths independent/local; keyboard and tool accessibility still intact; accepted macOS focused checks and smoke tests.
- **OmniVoice acceptance:** whole-failure list categorized; evidence supports any actual fix; all failed chapters capable of safe retries or individually explained; no loss of text or partial published audio; repeatable local evidence before release. Zero-failure promise is not realistic for every external-resource/environment failure.
- **Independent review acceptance:** independent Codex PASS at final tested SHA, or user-approved documented exceptions with no material unreviewed changes; maintainer authorizes integration/release explicitly.

## Appendix A — Approved 146-button matrix

**Code:** A = red outline; B = green outline; C = yellow outline; D = blue outline; E = normal (no semantic color). Background neutral for ALL roles and interaction states.

### TTS Audiobook — 16 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Add Files… | **E** |
| Add Folder… | **E** |
| Move Up | **E** |
| Move Down | **E** |
| Remove | **A** |
| Clear All | **A** |
| Cancel Import | **A** |
| Start | **B** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Open Output Folder | **E** |
| Clear Log | **A** |
| Install / repair Qwen3 voices… | **D** |
| Qwen3 details / disclosure | **E** |

### M4B Converter — 14 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Add Files… | **E** |
| Add Folder… | **E** |
| Move Up | **E** |
| Move Down | **E** |
| Remove | **A** |
| Clear All | **A** |
| Cancel Import | **A** |
| Convert M4Bs → MP3s | **B** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Open Output Folder | **E** |
| Clear Log | **A** |

### MP3 Tool — 23 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Import Folder | **E** |
| Cancel Import | **A** |
| Clear All Imports | **A** |
| ◀ Previous Book | **D** |
| Next Book ▶ | **D** |
| Add Book | **D** |
| Duplicate Book | **D** |
| Remove Book | **A** |
| Shared Artwork — Choose… | **E** |
| Shared Artwork — Clear | **A** |
| Book Artwork — Choose… | **E** |
| Book Artwork — Clear | **A** |
| Add Files | **E** |
| Move Up | **E** |
| Move Down | **E** |
| Remove Selected | **A** |
| Write ID3 Tags | **B** |
| Combine MP3s → One MP3 | **B** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Clear Log | **A** |

### M4B Maker — 23 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Import Folder | **E** |
| Cancel Import | **A** |
| Clear All Imports | **A** |
| ◀ Previous Book | **D** |
| Next Book ▶ | **D** |
| Add Book | **D** |
| Duplicate Book | **D** |
| Remove Book | **A** |
| Shared Artwork — Choose… | **E** |
| Shared Artwork — Clear | **A** |
| Book Artwork — Choose… | **E** |
| Book Artwork — Clear | **A** |
| Add Files | **E** |
| Move Up | **E** |
| Move Down | **E** |
| Remove Selected | **A** |
| Custom Destination — Browse… | **E** |
| Build M4B(s) | **B** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Clear Log | **A** |

### Cover Image — 13 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Add Files… | **E** |
| Add Folder… | **E** |
| Move Up | **E** |
| Move Down | **E** |
| Remove | **A** |
| Clear All | **A** |
| Cancel Import | **A** |
| Resize Covers | **B** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Clear Log | **A** |

### M4B Metadata — 20 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Import Folder | **E** |
| Add Files | **E** |
| Cancel Import | **A** |
| Clear All Imports | **A** |
| ◀ Previous Book | **D** |
| Next Book ▶ | **D** |
| Remove Book | **A** |
| Shared Artwork — Choose… | **E** |
| Shared Artwork — Clear | **A** |
| Book Artwork — Choose… | **E** |
| Book Artwork — Clear | **A** |
| Save Tags | **B** |
| Clear All Tags (keep chapters) | **A** |
| Remove Series Numbering | **A** |
| Open Output Folder | **E** |
| Pause | **C** |
| Resume | **C** |
| Cancel | **A** |
| Retry Failed | **C** |
| Clear Log | **A** |

### Preferences & Data — 6 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Output Location — Browse… | **E** |
| Save | **B** |
| Reset Preferences… | **A** |
| Clear Downloaded Data | **A** |
| Repair App Environment… | **D** |
| Close | **E** |

### Application navigation — 9 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| TTS Audiobook navigation | **E** |
| M4B Converter navigation | **E** |
| MP3 Tool navigation | **E** |
| M4B Maker navigation | **E** |
| Cover Image navigation | **E** |
| M4B Metadata navigation | **E** |
| Light / Dark toggle | **E** |
| Preferences & Data… | **E** |
| Open log folder | **E** |

### Conditional setup & dialogs — 22 buttons

| Button (as shown or conditional action) | Approved |
|---|:---:|
| Install & Continue | **B** |
| Install Selected Components | **B** |
| Skip optional installation | **E** |
| View licence terms | **E** |
| Open licence document | **E** |
| Cancel setup / installation | **A** |
| Continue setup | **E** |
| Continue without components | **E** |
| Try again | **C** |
| Qwen3 — Install CustomVoice | **B** |
| Qwen3 — Install Base | **B** |
| Qwen3 — Install Both | **B** |
| Qwen3 — Check and repair | **D** |
| Qwen3 — Developer tools | **D** |
| Qwen3 — Cancel install | **A** |
| Qwen3 — Close | **E** |
| Cleanup — Review Selection | **D** |
| Cleanup — Cancel | **A** |
| Cleanup — Confirm deletion | **A** |
| Cleanup — Continue | **E** |
| Cover replacement — Confirm replace | **A** |
| Cover replacement — Cancel | **A** |


**Owner screenshot deltas (10):** MP3 Tool and M4B Maker Previous Book, Next Book, Add Book, Duplicate Book are D/Blue (8 total); M4B Metadata Previous Book and Next Book are D/Blue (2 total). All other options remain as the prior recommended selections. This appendix represents screenshot-approved intended roles, not proof every conditional button was rendered simultaneously. If a later source/runtime audit discovers a *new* control that is absent here, preserve normal styling until classified or get a maintainer decision.

## 5. Deferred source inputs before this draft can be finalized

1. The full final *Reverend Insanity* failed-chapter list once the mass test settles.
2. The technical error lines / Detailed logs / runtime `last-failure` evidence representative of all failure categories, if available. Filename lists alone do not prove cause.
3. The accepted integration status and latest exact SHA of macOS v0.8.0 after Windows regression testing.

No further owner choice is needed for the **button colors** or **file-dialog behavior**. Claude must verify any platform/tool-specific technical facts it cannot know in this planning conversation.
