# Audiobook Creation Tool v0.7.2 — Windows hardening, feature map and verification gate

**Implementation roadmap for Claude Code CLI.** Planning date: November 4, 2026, America/Edmonton. Source inspected: `204c33bbd2d11db8a0848b261a5cb567a9240d74`. This document is a plan, not a record that its proposed implementation or Windows acceptance has run.

**Intended repository location:** `files/plans/ACT-v0.7.2-Windows-Hardening-Feature-Map-and-Verification-Gate-Implementation-Plan.md`.

## 1. Outcome, authority and release boundaries

Build a deterministic, Windows-native, media-aware acceptance system for all six ACT tools, a maintainable feature map, and the approved runtime hardening. Correct Cancel semantics, log following, metadata preservation, optional-model layout/testing, and measured M4B chapter-splitting performance without changing the Converter's existing outputs. Agents should run scripts and inspect their evidence; repeated full GUI exploration by an LLM must not be the normal verification mechanism.

### 1.1 Latest owner instructions supersede the older handoff

The original 50 answers were all Option A. Preserve those requirements except where explicitly superseded below. Appendix A retains the original register so a fresh agent need not interview the owner again.

| Topic | Current binding instruction |
|---|---|
| v0.7.1 integration | Merge and verify separately. Do **not** require another independent Codex review before this merge. The owner explicitly authorized the merge in this conversation. |
| Completed merge | `master` was fast-forwarded from `c0896d8714ef14419261b060af34490b18a47a14` to `204c33bbd2d11db8a0848b261a5cb567a9240d74`; the new remote `master` was read back and confirmed. The feature branch was retained. No tag, release or archive was published. |
| New work | The 50-decision overhaul is **v0.7.2**, separate from the merged v0.7.1. Proposed new branch: `feature/0.7.2-windows-hardening-verification`, from refreshed `origin/master`. This supersedes original 2A's reuse of the v0.7.1 branch. |
| Independent review | After Claude completes v0.7.2 implementation and self-verification, obtain a fresh independent Codex CLI review at Extra High effort **before the v0.7.2 merge**. No preliminary v0.7.1 Codex review is required. This is the current interpretation of the timing amendments to 1A/50A. |
| Cancel | Cancel must stop active processing promptly, including assembly/encoding of narration whose speech generation is complete. It must not finish that book for up to ten minutes. Preserve outputs already fully published; do not publish unfinished work. |
| Pause | Pause waits for the current file's work to finish at the existing file boundary. For concurrent Edge work, already active files may finish, but no additional queued file starts after the pause request wins admission. Resume continues the queue. Do not add Pause to tools that do not have it merely for symmetry. |
| M4B optimization | The only intended user-visible change is speed. Preserve actual MP3 output format, encoding choices, boundaries, metadata, artwork, filenames, ordering, collision rules and workflows. Original 18A's strengthened amendment remains binding. |
| v0.7.2 integration | This plan does **not** authorize merging v0.7.2 into `master`, tagging, publishing a release or final archive. Independent review, remaining owner checks and separate integration authorization are required. |

The older v0.7.1 `Handoff.md` and plan §15 still demand an immediate Codex review and describe the old next-release sequence. Those statements are now historical. During the first authorized documentation checkpoint, update the current-state block and append a decision recording the owner's new sequence. Preserve past evidence and historical entries.

### 1.2 In scope and exclusions

In scope: TTS Audiobook, MP3 Tool, M4B Converter, M4B Maker, M4B Metadata Editor, Cover Image, launcher, shared settings/logging/imports/jobs/output safety, installation/repair qualification and packaging checks. Windows is the acceptance target. Keep portable code healthy without claiming native macOS qualification.

Out of scope: multi-file concurrency for Kokoro, Chatterbox Turbo or Qwen3-TTS; new cloud services; replacement UI frameworks; format redesign; unrelated product features; modifications to Vibe Coding Files or other repositories. Local engines remain one file worker each. Do not install whole skill collections, add provider routing, or require model-driven clicks during normal runs.

Follow current repository-specific instructions and the supplied `AI-WORKSPACE.md` and workflow guidance. The inspected remote tree does not contain tracked root `AGENTS.md` or `AI-WORKSPACE.md`; discover actual local files rather than inventing their presence. Do not overwrite owner-local guidance. Exactly four Markdown files belong under `md-instructions/`: `Briefing.md`, `Decisions.md`, `Changelog.md`, `Handoff.md`. Put this plan under `files/plans/`, not in `md-instructions/`.

## 2. Verified baseline and limits of the evidence

### 2.1 Git/source facts checked in this planning session

| Item | Verified fact |
|---|---|
| Repository | `elmatthe/audiobook-creation-tool` |
| v0.7.1 feature tip at inspection | `204c33bbd2d11db8a0848b261a5cb567a9240d74` |
| Previous production base | `c0896d8714ef14419261b060af34490b18a47a14` |
| Relationship before merge | Feature was 15 commits ahead, zero behind; merge base was the previous production base. |
| R2 implementation | `f29281d99b738ef809477074e1735e6b6afa2101`, then cleanup fix `664d8b631df7a04ccdff6073a29f9241f0531f6e`. |
| Reported full-gate checkpoint | `b18518601061743a9408c2070fec1222a4f3934e`; its successor `204c33b` changes five documentation files only, verified through GitHub comparison. |
| Current production base for v0.7.2 | Remote `master` verified at `204c33b` after the explicitly authorized fast-forward. This keeps the tested source tree unchanged by integration. |
| Hosted check evidence | The queried combined-status and PR-workflow endpoints returned no entries. They do not supply an independent CI PASS. |

Refresh refs and local state at implementation time. If `master` has moved, inspect the intervening changes and record the actual starting SHA. Do not reset it to this document's snapshot.

### 2.2 Implementation-agent evidence, not independently rerun here

The committed handoff records: full gate on `b185186`, **13,200 passed / 65 skipped / 0 failed**, guarded groups 457 + 75; low-memory matrix of 30 scenarios without a hang or reservation leak; 470 byte-identical outputs against `e0aab03`; 78 caught mutants; real Edge direct/mixed concurrency. These are Claude's reported Windows results. This planning session checked their provenance and source/document relationship, not the underlying HOME-PC files or native runs.

The full gate's earlier failed run on `664d8b6` is retained and explained. Preserve it. Tests-only corrections are not automatically proof of correctness: final review must challenge the guards and the `test_epub_retirement.py` module-reload interaction.

Known unexercised areas include whole-machine commit exhaustion, real disk exhaustion, other volumes/filesystems/network paths, native macOS, a long real book end to end, owner listening, and actual local-engine synthesis in the last remediation. Do not silently turn these into PASS, mandatory destructive exhaustion tests, or release exemptions. Define relevant safe qualification scenarios and record actual scope.

### 2.3 Protected local state — mandatory rediscovery

Earlier reports identify 14 unrelated tracked deletions; untracked `.ai/`, `files/run-temp/`, `scripts/project-status.py`, and `files/plans/reference-handoff-of-mc-answers/`; ignored environments, voice assets, models and evidence. These are **reported**, not inspected from this environment. Inventory them read-only on HOME-PC. Do not restore, stage, move or delete them to obtain a clean tree. Keep original books, reference WAVs, voice previews and released archives intact. Stage task files explicitly.

After this remote merge the owner's local checkout may still be on the v0.7.1 feature branch. Fetch, inspect, and create the new branch without discarding changes. If a safe branch switch is blocked, use a repository-contained isolated checkout or stop with the exact collision; never use blanket restore/clean. Do not create another clone in system TEMP.

## 3. Source-grounded architecture findings

All paths in this section exist at `204c33b` unless explicitly called proposed. Line numbers are snapshot navigation aids, not contracts for string-slicing tests. Use AST/source symbols and actual behavior when implementing.

| Area | Actual source finding | Planning consequence |
|---|---|---|
| Existing gate | `scripts/verify.py` has pytest, guarded, requirements, docs, document-name and config gates, plus durable evidence, JUnit parsing and before/after tree fingerprints. | Migrate and extend; do not replace it with a thin pytest command. |
| Evidence root | `EVIDENCE_ROOT` is `files/dev-work/act070-remediation`; evidence mode uses `start.json`, `result.json`, `INCOMPLETE.json` and streamed logs. | New runs move to the canonical outputs root. Keep a read-only legacy evidence reader/format adapter; historical results must not be rewritten or made current. |
| Guarded suites | `files/tests/guarded_groups.json` splits v3-planning and v3-supervisor; `guarded_pytest.py` enforces process/network/write policy for the process lifetime. | Every guarded suite runs exactly once, separately from ordinary pytest. Preserve isolation through collection, teardown and atexit. |
| Hardcoded containment | `guarded_pytest.py` requires basetemp and report under `files/dev-work/p05b-stage4c`; guarded spec prefixes encode prior checkpoints. | A simple output-directory change will fail. Migrate these authorities and their tests together to a validated run capability; do not enlarge permission to all of `files/dev-work/`. |
| Pytest collection | Root `pytest.ini` sets `testpaths = files/tests` and excludes directory basename `dev-work`, preventing nested snapshots from shadowing tests. | Keep `files/tests/` intact initially. Place new test modules there and helpers/config under the gate. Do not add a second recursively collected test tree under ignored dev-work without redesigning collection. |
| Source scope | `files/tests/source_probe.py` registers application packages `shared`, `tts`, `mp3`, `m4b`, `artwork`, plus launcher, excluding the developer gate and local scripts. | Reuse its boundary for production guards. Do not replace it with raw `scripts.rglob()` or weaken application coverage. |
| Fingerprints | Current gate hashes tracked working-tree bytes, deletion sentinels, and nonignored untracked source/tests in two scopes. | Add new gate/map/fixture/config/lock inputs explicitly; exclude generated outputs. Separate code/test identity from documentation identity for truthful docs-only carry-forward. |
| Log rendering | `scripts/shared/job_ui.py`, `SummaryDetailsView._write`, around line 2236, deletes and reinserts all text without restoring the viewport. | A concrete source path for the reported jump. Fix per-pane following and preserve historical text/clear semantics. Confirm all tools' actual log implementations. |
| MP3 defaults | `scripts/mp3/mp3_workflow.py`, `_prepopulated`, around line 507, copies nonblank source majorities over configuration on first population. `add_files` preserves configuration when inputs already exist. | Reproduce edits **before the first import**, empty-book refill, shared fields and rerender paths. Do not assume every later import currently overwrites everything. Use absent-vs-present keys before inventing a provenance framework. |
| M4B split | `scripts/m4b/m4b_commands.py`, `_core`, places `-ss` after `-i` deliberately; comments record prior AAC priming corruption with input-side seeking despite plausible durations. | Repeated prefix decoding is a strong profiling hypothesis, not permission to move `-ss` before `-i`. Duration-only checks cannot protect this optimization. |
| Converter output | Same module uses `libmp3lame`, user VBR quality `-q:a`, `-threads 0`; the Converter writes MP3. Metadata/artwork passes are selected in `m4b_execution.py`. | Preserve actual MP3/VBR output; do not accidentally adopt the TTS constant-bitrate contract or output M4B/PCM to users. |
| Windows decoder | `scripts/m4b/m4b_winaudio.py` already contains `PcmFormat` and `PcmTimeline`. Execution has a streaming stdin path. | Inspect and reuse correct timeline/feeding concepts where compatible; do not assume all source codecs use the same decoder. |
| Real-media coverage gap | `test_tool_output_integration.py` explicitly defines `mp3_fixture` as fake ID3 bytes, never real audio. | Preserve its useful orchestration tests, but add valid-media acceptance. A test filename saying integration is not proof of decoding/encoding. |
| Packaging | `scripts/shared/release.py` uses a closed runtime allowlist, excludes developer-only scripts including verify, and allows six named reference WAVs from `files/Cloned-Voice-Uploads/`. | Gate relocation must preserve packaging/source exclusion tests and the exact runtime-asset exception. Never broadly exclude all `files/` at runtime without retaining those assets. |
| Window size | `scripts/shared/ui_theme.py` declares Windows/classic minimum 920×600 and default 1024×720. | Fix the Kokoro notice inside supported geometry. Do not raise the minimum merely to pass. |

### 3.1 Why Cancel waits today, and the required correction

The v0.7.1 low-memory design deliberately protects narration once its last speech paragraph or assembly is in hand. In `scripts/tts/ffmpeg_watch.py`, `controlled(..., abort_on_cancel=False)` is the default. `_verdict_on` lets that work continue while progressing, with `CANCEL_STALL_SECONDS = 30` and `CANCEL_FINISH_SECONDS = 600`. `worker_limits.py` also offers finished narration up to `CANCEL_FINISH_WAIT_SECONDS = 30` to find room for disk assembly. Thus ten minutes is a deliberate finishing allowance, not the time inherently needed to cancel a subprocess.

That policy conflicts with the owner's latest instruction. Correct it early using existing tests, before the broad acceptance rollout:

| Control | Required contract |
|---|---|
| Cancel | Latch cancellation immediately; stop dispatch, synthesis, decode, memory waits, assembly and encode for every active item; wake paused/waiting workers; terminate owned children with bounded escalation. Do not start a disk fallback or retry after Cancel. |
| Pause | Stop admitting new items, allow already active source-file work to complete safely, then remain paused. Do not cancel those active items. Resume admits the remaining queue. |
| Already published output | Keep valid output committed before cancellation won the publication boundary. Preserve all pre-existing destination files. |
| Work not yet published | Do not publish it after cancellation wins the commit boundary. Clean owned staging safely; report CANCELLED, rather than FAILED or SUCCEEDED. Do not delete unrelated or already committed outputs. |

Initial acceptance targets, to validate on HOME-PC: UI reflects Cancel within 100 ms under normal load; cancellation observation within one existing 250 ms poll; owned processing normally settles within 2 s and within a 5 s tested termination/escalation budget. These are proposed engineering budgets, not measured facts. If a platform API cannot meet them, expose the actual blocker and seek a bounded design adjustment; do not reinstate 30/600-second finalization under the Cancel label. Cleanup may be reported separately but must not continue narrating/encoding secretly.

Protect the publish/cancel race with a short, explicit linearization boundary: either publication committed first and the valid file stays, or cancellation won and commit is refused. The GUI must not wait on long encoding or full-file copying to acquire that boundary. Exercise the race with a barrier, not a probabilistic sleep. Include low-memory, FFmpeg stall, final paragraph, encode, all-waiters, paused queue and mixed imports. Recheck local-engine cancellation where the pydub supervision seam reaches their exports; this does not authorize concurrency changes.

## 4. Bounded upstream research and reuse decisions

Research inspected actual source, representative helper/example/test files and license files at the revisions below. No candidate was installed, executed or benchmarked on HOME-PC here. These are source-backed recommendations, subject to the small local feasibility pilot in Phase 0. Recheck revisions before copying code. Any borrowed substantial code must retain required notices; pattern reuse does not require installing a plugin.

| Candidate; inspected revision | Files inspected and observed fit | Decision for ACT |
|---|---|---|
| Cursor plugins, `bb68f2365eceafa0cb2d253112f675acf5f144cc` | pstack create/maintain verification skill bodies, a feature-map example, control-ui/control-cli bodies, pstack/team-kit MIT licenses. Creation interviews source and records user outcomes; maintenance rechecks live features. control-ui explicitly targets browser/CDP. | Adapt the feature-map and evidence principles. Do not install its harness, seed only 3–5 features, import automatic PR behavior or require recurring delegated/model-driven verification. Use ACT's complete inventory and deterministic runner. |
| Anthropic skills, `ca45fc496a3436251f191354091d557da31c15b5` | webapp-testing skill, `scripts/with_server.py`, local Apache-2.0 license. The helper uses shell commands, PIPE output and port readiness. | Reference only. No ACT browser surface needs it; do not copy its process supervision into this media app. ACT needs owned process trees, drained/file-backed diagnostics and application-level readiness. |
| Autodesk browser-test skills, `f11f48f4976811b46e2f65825e4010ea875d1da3` | compiler/runner skill bodies, quality workflow, Apache-2.0 license. Compiler creates standard Playwright specs; the runner skill itself still expects Playwright MCP. | Adapt authoring-versus-repeatable-execution separation. Do not claim its agent runner is an autonomous native Tk test system or maintain both Markdown and compiled specs as competing truth. No direct adoption. |
| obra/superpowers, `22f0b463e7a5e579904dd6211a520321035526f7` | verification-before-completion body and MIT license. | Reference fresh-evidence discipline. Existing ACT instructions already cover much of it; avoid adding a full framework or repeating an expensive gate after every message. |
| pywinauto, `a428d9617a429a76779d235f0702ec0e94b26214` | Windows application tests, BSD-3-Clause license, official getting-started/remote-execution guidance. Win32/UIA exposure varies by control; native input needs a usable desktop. | Pilot against real Tk/ttk controls and common dialogs. Select only if it works with the pinned runtime and beats existing facilities. Never promise full Tk accessibility merely because Win32/UIA exists. |
| Existing ACT pytest/Tk/guards/media utilities | Current gate, guarded runner, conftest isolation, source registry, job UI, media command/execution code and real-output seams. | Adopt as the foundation. Extend narrow helpers and schemas, preserving working tests and process/network guards. |

Official Python 3.12 Tkinter documentation supports main-loop/thread discipline; Microsoft documents owned Job Objects and input APIs; FFmpeg documents distinct input/output seek semantics. Those generic APIs do not override ACT's measured AAC boundary defects. Primary links and pinned source paths are in Appendix C.

Phase 0 must produce a short fit comparison with actual local observations: backend visibility, file-dialog interaction, click/keyboard reliability, screenshot geometry at scaling, process ownership, development dependency versions, licenses and unresolved gaps. Do not add new dependencies or download models as a side effect of a test. If a new package is needed, propose exact pins, compatible transitive dependencies and purpose for the Phase 0 approval. Prefer a small stdlib/ctypes fallback over an unproven framework, but do not grow a custom automation platform just to avoid one justified dependency.

## 5. Canonical layout and migration inventory

The following is a proposed target, not a claim that these files exist already. Keep new tests in `files/tests/` initially, consistent with the current collection boundary. Create only helpers that are used.

```text
files/
  plans/ACT-v0.7.2-Windows-Hardening-Feature-Map-and-Verification-Gate-Implementation-Plan.md
  tests/                         # preserve existing tests and node identities
    test_verification_gate_contract.py
    test_verification_coverage.py
    test_native_acceptance.py
    test_real_media_acceptance.py
    test_cancel_semantics.py
    test_m4b_scaling.py
  dev-work/
    feature-map/
      README.md
      tts-audiobook.md
      mp3-tool.md
      m4b-converter.md
      m4b-maker.md
      m4b-metadata-editor.md
      cover-image.md
      shared-workflows.md
    verification-gate/
      verify.py                  # sole developer gate entry point
      verification.json          # execution policy and profiles
      coverage.json              # authoritative requirements-to-tests mapping
      helpers/                   # reporting, media oracle, supervision, fixtures
      adapters/windows/          # only the selected, piloted desktop adapter
      fixtures/                  # recipes/manifests/tiny immutable inputs
      baselines/                 # approved visuals/compatibility contracts
      tooling/                   # exact development lock/provenance if needed
      outputs/                   # ignored; each invocation owns a new child
```

Do not create a permanent forwarding runner in `scripts/verify.py`. A brief development transition is allowed inside one migration checkpoint; its final state must have one canonical entry point. Update known callers before deleting the old developer entry point. Keep application bootstrap/repair/runtime scripts where runtime needs them.

| Migration obligation | Required inspection/update |
|---|---|
| Root discovery/imports | Gate moves four levels below root; replace location assumptions deliberately. Keep application import root `scripts/` and suite root `files/tests/`. Test invocation from another CWD. |
| Test imports | Update `test_verify_evidence.py`, `test_verify_guarded.py`, `test_repository_contract.py` and every discovered importlib path/AST fixture referencing the old gate. Maintain assertions, not just strings. |
| Guarded invocation | Preserve `-I`, `-B`, disabled plugin autoload, source/tool pins and process-lifetime policies. Migrate report/basetemp roots and prefixes atomically. |
| Ordinary pytest | Preserve guarded exclusions exactly; compare collected ordinary and guarded sets, require disjoint union equal to expected inventory. |
| Collection config | Preserve root `testpaths` and snapshot exclusions. No test discovery from old ignored evidence, nested repositories or outputs. |
| New inputs | Fingerprint untracked new gate helpers, maps, fixtures, manifests and locks even if under an existing ignored parent. Ensure files intended for versioning are actually trackable. |
| Ignore policy | Audit `.gitignore`: broad existing `files/dev-work` rules may require narrow unignore rules for the two canonical tracked trees. Keep only outputs/caches generated and ignored. Prove with `git check-ignore` and `git ls-files`. |
| Docs/status consumers | Search tracked/local callers for old gate commands, old evidence roots, `read_evidence_status`, filenames and status vocabulary. Update active guidance; historical command examples may remain labelled historical. |
| Packaging | Verify developer gate/map/tests/evidence absent from archive manifests and runtime imports. Preserve the six explicitly allowed reference WAVs and necessary runtime assets. |
| Legacy evidence | Read old `result.json`/INCOMPLETE records with their old schema and source identity. Do not relocate old runs, reuse their directory or convert them into new PASS results. |

Migration is complete only when a full repository search and relevant contract tests show no active dependence on the old gate path. Keep a path/caller inventory in the Phase 0 evidence, then maintain it through the migration checkpoint.

## 6. Runner interface and mode contracts

The commands below are the **proposed v0.7.2 interface** to implement and test. They are not executable promises about v0.7.1. Use the actual isolated environment interpreter on Windows.

```powershell
python files/dev-work/verification-gate/verify.py --mode focused --test files/tests/test_cancel_semantics.py
python files/dev-work/verification-gate/verify.py --mode changed --base origin/master
python files/dev-work/verification-gate/verify.py --mode full --platform windows
python files/dev-work/verification-gate/verify.py --mode qualification --scenario m4b-scaling
python files/dev-work/verification-gate/verify.py --mode qualification --scenario edge-low-memory
python files/dev-work/verification-gate/verify.py --mode qualification --scenario optional-engines
python files/dev-work/verification-gate/verify.py --mode qualification --scenario fresh-windows
```

Use repeatable `--test` node IDs and stable `--feature` IDs for focused selection. Do not accept arbitrary shell fragments as test commands. `--preflight-only` and `--collect-only`, if provided, create evidence and never establish acceptance. `--network` must be an explicit named qualification policy, not a global disable-isolation flag. Exact scenario names should be frozen in Phase 1 and kept in help/config/tests together.

| Mode | Selection and scope | Acceptance meaning |
|---|---|---|
| focused | Explicit tests/features plus required guards and fixture prerequisites. Unknown IDs/empty selection are errors. | PASS for that scope only. |
| changed | Merge-base diff plus dirty relevant source; select affected features, reverse dependencies, shared invariants and relevant fixtures/tests. | PASS for selected scope, never full acceptance. Unknown/unmapped shared changes cause conservative full selection or BLOCKED; never zero-test success. |
| full | Entire ordinary suite, every guarded group, canonical static/config/dependency contracts, registered routine Windows GUI/media journeys, coverage checks and gate negative controls. | Full routine gate PASS only when all required applicable cases execute and satisfy policy. Qualification/owner acceptance are separately visible. |
| qualification | Explicit expensive scenario: stress, real optional engines, online Edge, fresh Windows, large chapter counts, long duration. | PASS for named scenario and actual machine/source identity only. |

A release-readiness aggregate consumes the full routine run, required qualification runs, independent review and owner checks. It is not a fifth runner that competes with the canonical entry point. Reuse only compatible evidence with unchanged relevant inputs and environment; never splice together unrelated old test successes.

### 6.1 Status and exit policy

Results: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, `NOT APPLICABLE`. Lifecycle is separate: `created`, `preflight`, `collecting`, `running`, `finalizing`, `completed`, `interrupted`.

| Exit | Meaning |
|---|---|
| 0 | Requested scope passed, including required cleanup/integrity checks; does not imply release readiness. |
| 1 | A product assertion, guard, output validator or gate-integrity check failed. |
| 2 | Required prerequisite unavailable or approved environment cannot be established: BLOCKED. |
| 3 | Required execution/evidence incomplete or no tests executed: NOT RUN/incomplete. |
| 64 | Invalid invocation/configuration before usable execution. |
| 130 | User interruption; persist interrupted evidence and stop owned children. |

Keep raw child/pytest/wrapper codes. Map the installed pinned pytest's actual ExitCode values; code zero alone is insufficient. Missing/malformed JUnit, unexpected skips/xfails, no collection, count mismatch, unapproved deselection, unknown result values and incomplete guarded reports cannot produce PASS. A test expected to raise an error may PASS only because it asserted that intended error. A real failure in a diagnostic rerun remains a recorded failure in its original run; retries never erase it.

If assertions fail and other checks are blocked, aggregate FAIL and retain both categories. If nothing fails but a required prerequisite is blocked, aggregate BLOCKED. Missing required execution is NOT RUN; optional or genuinely inapplicable cases remain explicit. NOT APPLICABLE requires a declared applicability rule and evidence; it is not a manual synonym for skip. No tool may silently downgrade a release-required scenario to optional.

### 6.2 Lifecycle and evidence

Atomically reserve a unique timestamp-prefixed child under `outputs/`, for example `2026-11-04_143025_full_7f4c`; record timezone/UTC offset and monotonic durations separately. A timestamp alone is not collision-safe. Every invocation, including failure/preflight, produces its own record where safe; invalid unsafe output paths must be refused without touching them.

Write a start marker before child launch. Stream bounded log summaries while raw diagnostics go to files. Finalize `results.json` atomically only after child exits, report parsing, coverage, freshness and cleanup checks finish. Preserve incomplete markers on crashes. A status reader must validate schema, run identity and required artifacts; absence of an error string is never a PASS.

Proposed compact result shape:

```json
{
  "schema_version": 1,
  "run_id": "2026-11-04_143025_full_7f4c",
  "mode": "full",
  "lifecycle": "completed",
  "status": "PASS",
  "scope": {"platform": "windows", "profile": "routine", "full_acceptance": true},
  "identity": {"head": "<actual SHA>", "source_digest": "<digest>", "test_digest": "<digest>", "policy_digest": "<digest>", "start_end_match": true},
  "environment": {"os_build": "<observed>", "python": "<observed>", "tk": "<observed>", "ffmpeg_sha256": "<observed>", "interactive_desktop": true},
  "counts": {"expected": 0, "collected": 0, "executed": 0, "passed": 0, "failed": 0, "blocked": 0, "skipped": 0},
  "checks": [],
  "coverage": {"inventory_reviewed": false, "mapped_required": 0, "satisfied_required": 0, "exceptions": []},
  "qualification": {"required": [], "satisfied": [], "pending": []},
  "release_ready": false,
  "artifacts": [],
  "cleanup": {"owned_children_remaining": 0, "violations": []}
}
```

This illustrates fields, not a valid passing run: zero counts and an unreviewed inventory must fail acceptance validation. Store individual checks/tests, stages, exit codes, skipped reasons, timeouts and evidence references in normalized records; do not infer all coverage from totals.

Applicable run artifacts: `results.json`, `summary.md`, `coverage-report.md`, `failures.md`, start/selection/collection records, `logs/`, `screenshots/`, `reports/`, `artifacts/`, `temp/` and traces when useful. Do not create empty decorative directories. All file references must resolve inside the run or name immutable declared inputs; validate traversal, links and missing evidence.

`agent-review.md` is written by Claude/Codex after examining a completed full run. The mechanical runner must not invent a model review. It should summarize exact tree/environment, actual coverage, GUI/media evidence, failures by severity, reproductions, unverified areas and next checkpoint.

## 7. Coverage inventory and feature map

Use one authoritative machine-readable inventory at `verification-gate/coverage.json`. The human documents explain user workflows and link to stable IDs and that inventory; they do not duplicate an independent test-mapping table that can drift.

Each feature needs stable ID, tool, user purpose, controls/entry routes, source symbols and shared dependencies, relevant states, prerequisites, input/output contracts, failure/cancel/retry behavior, persistence, verification requirements, and intentional differences. Suggested ID families: `ACT.TTS.*`, `ACT.MP3.*`, `ACT.CONVERTER.*`, `ACT.MAKER.*`, `ACT.METADATA.*`, `ACT.COVER.*`, `ACT.SHARED.*`, `ACT.SETUP.*`, `ACT.GATE.*`.

Proposed feature record:

```json
{
  "id": "ACT.TTS.CANCEL",
  "tool": "tts-audiobook",
  "release_required": true,
  "applicability": {"platforms": ["windows"]},
  "source": [{"path": "scripts/tts/epub2tts_gui.py", "symbols": ["TtsPanel.cancel_job"]}],
  "controls": [{"key": "cancel", "label": "Cancel", "states": ["running", "paused", "waiting", "assembling"]}],
  "contracts": ["stop active work promptly", "no publication after cancellation wins", "keep already published outputs"],
  "verification": {
    "all_of": [
      {"kind": "behavior", "test": "files/tests/test_cancel_semantics.py::test_cancel_stops_finished_narration_assembly"},
      {"kind": "native", "scenario": "tts.cancel-during-assembly"},
      {"kind": "media", "scenario": "tts.cancel-publication-race"}
    ]
  },
  "exceptions": []
}
```

Symbols and tests in examples must be resolved against implementation before they become required inventory; do not claim illustrative selectors already exist. Parameterized node IDs should use stable parameter names. Map to exact collected IDs or explicit scenario IDs whose definitions enumerate their tests, never a loose `test_*.py` glob as proof.

Use `all_of` for complementary evidence. If equivalent alternative verifications are needed, express `any_of` explicitly with applicability rules; a unit test must not substitute for required native or real-media evidence. Check setup/call/teardown outcomes and guarded membership, not just JUnit display names.

Track four distinct measures: (1) discovered functionality inventoried, (2) required entries mapped to meaningful tests, (3) required verifications actually satisfied in the current scope/evidence, (4) optional source line/branch coverage. A 100% mapping statistic proves only the registered inventory's mappings. Inventory completeness requires source/control/workflow review.

### 7.1 Discovery and maintenance

Combine AST candidates, actual widget trees, launcher/tool routing, menus, keyboard bindings, dialogs, configuration schema, jobs, output plans and observed workflows. Static literal extraction in this planning session found real controls in every tool but deliberately missed dynamically built controls; it is only a starting aid.

Maintain a reviewed surface index covering installed/missing engine states, selected modes, multiple Books, error states and resize layouts. For changed sources, require affected map/contract review even if no label changed. Unknown source regions, deleted test IDs, new unmapped controls, expired exceptions or unexplained missing surfaces block clean full acceptance. Avoid automatic edits that rewrite expectations to match a regression.

Exceptions need owner approval evidence, exact scope, reason, compensating check, review/expiry trigger and affected release. Agents cannot approve their own coverage reductions or screenshot baselines. Keep these records in the inventory/policy, not a second coverage database.

### 7.2 Minimum journey inventory

| Surface | Required states/workflows and observable results |
|---|---|
| Launcher | Open each of six tools; switch tools during idle and meaningful work; preferences/help/output actions as present; startup without outputs; close during imports/runs; no orphan windows/processes. |
| TTS Audiobook | Direct TXT/PDF, folders, mixed queues, voices/rates/bitrates, resume/overwrite, output names, worker selection, progress/errors, pause/resume/cancel/retry, optional setup/status, final tails, source protection and low memory. Real Edge overlap plus offline replay; local engines single-worker. |
| MP3 Tool | Book navigation/add/duplicate/remove; folder/direct import; duplicate filtering; track reorder/remove; shared and per-Book metadata; intentional blank values; auto-number/time/title/artwork options; Write ID3 and Combine; invalid values; output/collision behavior; cancellation/retry. |
| M4B Converter | Whole book/split; source/replace/no metadata modes; numbering/titles/artwork; codec/decode compatibility; chapterless/corrupt sources; known priming boundaries; all chapter outputs and order; cancellation/retry and long-job scaling. |
| M4B Maker | Books, folder/direct sources, ordering/chapter text, shared/per-Book fields, silence/series numbering, artwork/naming, Build M4B(s), chapter timing and round-trip validation, failures/cancellation/retry. |
| M4B Metadata Editor | Import, navigation, shared/per-Book edits, Save Tags, Clear All Tags (keep chapters), Remove Series Numbering; stream/chapter/artwork preservation, in-place or destination behavior actually supported, conflict/cancel/failure recovery. |
| Cover Image | Inputs, size/format settings, crop versus full-image letterbox, numbered copies versus replacement, conflicts, corrupt images, source protection in copy mode, safe replacement, cancellation and valid dimensions/decoding. |
| Shared UI | Log follow/hold/resume per tab; keyboard focus and disabled controls; minimum/normal size, appearance/scaling, scrolling; dialogs and confirmation cancellation; imports while work exists. |
| Settings/setup | Existing persisted values restored, deliberately nonpersisted state remains so; malformed settings recovery; missing optional assets; launch/repair/offline reuse; no silent model downloads. |

Expand every row into discoverable feature IDs during Phase 3; these rows are a required coverage floor, not a claim of complete control discovery.

## 8. Windows GUI acceptance design

Use three complementary layers with distinct evidence labels:

1. Existing pytest and real Tk/ttk widgets for fast model/control/state/event-loop regressions.
2. An isolated, externally supervised ACT process, driven with actual Windows input/native dialog interaction for representative complete workflows.
3. Independent output/media inspection and layout assertions after those interactions.

A widget `.invoke()` or controller call is useful layer-one evidence. It must not be labelled a physical/native click. Playwright is not a Tkinter driver; do not add a browser just to satisfy a generic UI-testing checklist.

### 8.1 Feasibility pilot and fallback

On HOME-PC, launch a disposable ACT instance using isolated settings and synthetic inputs. Inspect actual Win32 and UIA trees when tools already exist. Try a button, entry, combobox, checkbox, menu, file dialog, list/tree, scrolling and keyboard focus. Record failures as well as successes. Test the real 920×600 layout with Kokoro absent and a representative installed state.

Preferred adapter: a narrow pywinauto Win32/UIA wrapper if the pilot proves adequate exposure and compatible approved dependencies. For Tk controls that are not exposed, a test-only launcher under `files/` may obtain widget geometry/state on the Tk main thread and let an external driver send ordinary OS mouse/keyboard input to the owned foreground window. It must not call business methods to bypass the interaction being tested. Prefer stable semantic widget keys and fresh bounds over fixed desktop coordinates. Recompute after resize/scaling/state changes and refuse ambiguous targets.

A test-only observation channel may return readiness, widget identity/bounds and state, or aid diagnostics. Keep it local, run-token scoped, disabled outside the test launcher, and excluded from distributions. It must not become a shipped unauthenticated control endpoint or alternate processing implementation. Use the actual launcher/panels and production processing. All Tk inspection/mutation must run in its event loop; no worker-thread widget access.

If neither native backend nor bounded OS-input fallback can prove a required workflow, report BLOCKED and specify the missing capability. Do not silently substitute `.invoke()` and declare native acceptance complete. A framework installation, SDK installation, new VM or remote desktop service needs the applicable owner approval; do not change system policies to make the pilot pass.

### 8.2 Desktop safety and readiness

Before every native session, verify actual interactive desktop availability, target window visibility, expected PID/start identity, foreground focus, DPI/scaling and synthetic test workspace. Opening an input desktop handle alone is insufficient; Microsoft's documentation says a disconnected session can still return a handle. Perform a harmless focus/input round trip in the owned test window. Missing/locked/minimized-RDP prerequisites produce BLOCKED, not PASS.

Acquire a per-desktop automation lease so two test runs cannot drive each other's windows. Never automate an arbitrary existing ACT instance or the owner's current session. Revalidate focus immediately before OS input; stop if the foreground window belongs elsewhere. Do not send keys to UAC, credentials, unrelated applications or the desktop. Use clipboard-free input where feasible; restore any clipboard state if a tested path necessarily uses it.

Use readiness predicates with bounded polling: window created, event loop responsive, correct tool loaded, import settled, control enabled, task terminal and output validated. Fixed sleeps are not correctness assertions. If a scenario fails, capture owned-window evidence, terminate only its owned process tree, and start the next scenario from a known state.

### 8.3 Geometry, scaling and visual checks

Test Windows minimum 920×600, default 1024×720 and a larger window. Separate application client size from window frame size. Cover available 100%, 125%, 150% and 200% display-scaling environments or explicitly record untested cases; changing Tk scaling alone is not proof of native OS DPI behavior. Do not change system scaling without authorization. Use known compatible machine/session configurations for qualification.

Assert controls' visible/reachable geometry, labels wrapping, scroll access, selected tab, keyboard focus and enabled/disabled behavior. A control may legitimately live in an intentional scroll area; prove that users can reach it. The primary Start/Cancel/status surfaces must remain usable at supported dimensions. Check selected/absent Kokoro and Qwen states, notices and dialogs, multi-Book modes and resize transitions.

Capture only the synthetic application's windows, avoiding personal desktop content. Store candidates/diffs under the run. Approved baselines live outside outputs and identify OS/Tk/fonts/theme/DPI/window size. Missing or changed visual baselines are candidates for explicit review, never auto-approved by a normal run. Do not mask actionable controls, alerts or clipping to reduce diffs. Prefer geometry/state assertions for stable correctness, screenshots for visual evidence, and calibrated image tolerances for known rendering variation.

## 9. Valid media fixtures and independent output oracles

Start by auditing existing fixture generators and real-media tests; reuse correct ones. Keep fake orchestration fixtures clearly labelled. Tiny synthetic inputs should be deterministic, private-data-free and reproducible from declared tools. Either commit small immutable bytes or commit a generator and manifest; regeneration must not depend on a previous outputs directory.

| Fixture tier | Construction/validation | Purpose |
|---|---|---|
| Text/PDF | TXT with paragraphs, blank lines, literal “blank”, headings and protected endings; valid small PDFs including prose continued across pages, Unicode and no-text cases. Use existing approved PDF libraries. | Imports, text sizing, narration requests, PDF join consistency and invalid-input handling. |
| WAV/MP3 | Known PCM samples, multiple rates/channels, silence/transients, distinguishable markers; encode with the actual pinned FFmpeg. Validate headers and full decode. | MP3 combine/tags, TTS assembly, durations, signal boundaries and tail preservation. |
| Routine M4B | A genuinely supported container/codec with embedded chapters, distinguishable content at every boundary, nonzero/odd starts where supported, tags and artwork. | Maker/Converter/editor journeys and exact chapter/order/metadata assertions. |
| Scaling M4B | At least 1,000 real chapters, short but valid content, plus 10/100/500/1,000/2,000-chapter variants where the actual container represents them correctly. | Chapter-count scaling without requiring days of audio. Verify embedded count with independent probing; detect muxer chapter-count truncation before testing the product. |
| Duration stress | Extended synthetic sources with boundary markers, artwork and realistic duration, separately scheduled; a lawful owner-selected real book is optional supplementary evidence. | Prefix-seek cost, long-output behavior, cancellation, memory/disk budgets and duration-sensitive truncation. |
| Images | Valid PNG/JPEG in landscape/portrait/square, alpha, distinguishable corners and metadata as relevant. | Crop/letterbox behavior, dimensions, format and copy/replace safety. |
| Adverse inputs | Truncated/corrupt/unsupported sources, missing files, denied/locked destinations, collisions, duplicate identities and disappearing inputs. | Actionable errors, preserved sources, atomic publication and retries. |

The fixture manifest records ID, generator revision/recipe, dependencies/tool hashes, license/provenance, expected streams/chapters/tags/content, size bounds and checksum where deterministic. Validate generated inputs **before** driving ACT. A malformed generator is an infrastructure failure, not an application defect. An arbitrary file renamed `.m4b` or ID3 header is not a valid media test.

### 9.1 Independent inspection

Use the pinned FFmpeg/ffprobe pair through safe argv lists, with bounded diagnostics and owned process trees. Record their actual execution/build/version/hash, not merely a path. Typical probes include `ffprobe -v error -show_format -show_streams -show_chapters -of json <path>` and a complete `ffmpeg -v error -i <path> -f null -` decode. A successful probe alone does not prove media content, metadata fidelity or boundary integrity.

Inspect container, codec, sample rate, channel layout, bitrate/quality policy, duration/sample count, chapter boundaries/titles, tags/artwork, filenames and ordering. Use a separate oracle that does not call the same transformation routine to derive its expected answer. Where metadata libraries and ffprobe differ, document which field representation is authoritative for the product contract and retain raw evidence.

For signal checks, compare against an independently decoded complete-source PCM timeline, then select expected sample intervals using the established partition contract. Detect gaps, duplication, lost boundary transients, attenuated first frames and wrong ordering. Calibrate codec delay/padding and alignment limits once using actual pinned builds; do not use arbitrary generous duration tolerances or align away missing content. Check first and last chapter as well as interior boundaries. Duration equality cannot detect the historical priming defect.

### 9.2 Compatibility baselines

Keep an immutable v0.7.1 comparison identity at `204c33b`. Run it in a contained reference checkout/environment only when needed for an output/performance baseline; do not execute it in the owner's main checkout or alter `master`. Record fixture hashes, commands/settings, toolchain and source SHA for both sides.

Edge ordinary-memory and fallback routes retain their established byte-identity contract under the same pinned encoder/toolchain. Assert MP3 hashes, request text, internal pacing and final tails. A golden update needs an approved behavior change and independent evidence; migration or performance work is not a reason to regenerate goldens blindly.

For M4B Converter improvements, enforce byte identity wherever baseline runs demonstrate it is stable. Otherwise require technical/semantic equivalence, decoded content/boundary checks, metadata/artwork equivalence and unchanged user-facing format. Do not require impossible container timestamp byte equality, but do not label a changed encoder/quality setting “equivalent” to evade 18A. Establish this compatibility classification before optimization.

## 10. Gate self-tests: prove failures cannot become PASS

Run small adversarial contract tests routinely; schedule expensive media/process mutations separately. Keep a known passing control and prove each mutant's intended assertion executes. A mutant blocked at setup or skipped does not prove that its target defect was caught.

| Negative control | Required outcome/evidence |
|---|---|
| Test assertion or setup/teardown failure; nonzero child exit | FAIL; raw exit/report retained, exact stage named. |
| Pytest no collection, unknown selectors, deselected required case | No PASS; selected-versus-collected-versus-executed discrepancy reported. |
| Missing/corrupt/truncated/duplicated JUnit or guarded report | Invalid/incomplete evidence, never PASS inferred from console text. |
| Fake PASS wrapper exit with failing child/JUnit | FAIL; wrapper and child reconciliation catches it. |
| Required skip/xfail or unavailable optional engine within a required qualification | BLOCKED/FAIL according to cause; no automatic exemption. |
| Locked desktop, missing native prerequisite or lost target focus | BLOCKED; no fallback classification as native success. |
| Missing/unmapped feature, dead test ID, omitted tool/control or unapproved exception | Full acceptance blocked; mappings alone cannot hide a missing inventory surface. |
| Changed source/config/fixtures/policy/locks during run, including relevant untracked files | Current source not certified; start/end mismatch and changed inputs visible. |
| Old run copied into a new directory, edited run ID, stale source digest, missing evidence | Reject as current acceptance; do not trust directory name or latest pointer. |
| Interrupt/timeout/kill during preflight, tests, reports or cleanup | Incomplete/interrupted marker persists; no final PASS; children reaped. |
| Traversal, symlink/junction/reparse escape, unsafe basetemp, reused run directory | Refuse before destructive action; sentinel outside run unchanged. |
| `outputs/` absent or deliberately removed between completed runs | Next invocation recreates it using tracked fixtures/config; prior generated content is not a dependency. |
| Guarded module duplicated/omitted or moved into ordinary pytest | Collection partition check fails, guards not bypassed. |
| Child creates a grandchild or refuses graceful shutdown | Owned tree killed/reaped within budget; unrelated sentinel process survives. |
| Simulated encoder success with wrong/truncated payload | Media oracle fails even if exit code and file extension look valid. |
| Input-side seek/omitted artwork map/wrong chapter count mutation | Boundary/media acceptance fails; no duration-only false PASS. |
| Old 600-second finalization after Cancel, lost cancel propagation or post-cancel fallback | Cancel regression fails on observed work/publication, not merely a constant assertion. |

Retain and challenge the existing low-memory permanent negative control (`test_the_old_hang_is_what_this_test_would_see`) under valid Windows limits. It deliberately reproduces the old hang inside an outer watchdog; it must never strand the full gate. Compare test changes against the merged baseline and retain full-suite import-order scenarios, including `test_epub_retirement.py`.

## 11. Runtime hardening specifications

### 11.1 Cancel/Pause correction — first product checkpoint

Implement §3.1 using the existing test investment before moving the gate. Trace GUI controls, `shared/job_control.py`, `shared/cancellation.py`, Edge direct runner, folder/batch, `worker_limits.assemble`/gate waits, `ffmpeg_watch` and publication. Avoid a superficial constant change: cancellation must win before fallback/retry/admission/commit and reach every active worker. Context-local controls must propagate correctly through actual threads and engine routes.

A paused queue must be cancellable immediately. Cancel must wake all memory/condition waits, remove reservations in finally paths and stop async Edge operations. Test calls made just before and just after the latch with barriers. Differentiate cancelled tasks from retryable local failures and completed tasks; do not auto-retry cancellation. Preserve legitimate Retry Failed behavior for actual failures. If a resume/recovery feature retains intermediate chunks, label and own them explicitly; do not promise complete output from interrupted work.

Updating tests that intentionally encoded “finish narration after Cancel” is authorized by the owner's new behavior requirement. Keep mutation/negative controls so the new prompt-stop semantics are proved. Pause's graceful boundary and already published-file preservation remain independently tested. Update old plan §9/§14.8 references and current user guidance to explain the new semantics accurately without rewriting historical evidence.

### 11.2 Log following across all tools

Fix the shared Summary/Details view where applicable and audit independent log widgets. Before an append/redraw, determine whether each pane is at the bottom. If so, keep the latest lines visible; if not, preserve the user's logical viewport. Resume following when they return to the bottom. Account for wrapped lines, content shorter than viewport, tab switches, resizing, history trimming, clear, frequent updates and a destroyed widget. Preserve copy/select behavior, scrollbars, event history and the session log.

Prefer append/update operations that avoid replacing all text when feasible. If replacement is needed, retain a logical top index/anchor rather than only a yview fraction, since content length changes. Use a small documented tolerance for “at bottom”; test actual Tk geometry/event behavior. Each pane has its own follow state. Do not globally call `.see('end')` after every update or reset the view when the user is reading earlier messages.

Tests: short/long logs, follow initially, scroll up while concurrent messages arrive, return to bottom, clear while active, resize, tab switch and tool transition; no worker-thread Tk operations. Include a high-volume update workload measuring event-loop responsiveness, not only visual correctness.

### 11.3 Metadata preservation and provenance

Required precedence: explicit user edits including intentional empty values; then existing valid session values; then imported defaults for truly unset fields. Audit shared and per-Book scopes separately and preserve their established override semantics.

Reproduce MP3 overwrite paths with a valid tagged input. At minimum: edit Album before any import; deliberately clear it; add first files; add more files with conflicting tags; remove all files then refill; navigate/duplicate Books; shared Album with a per-Book override; folder replacement with its existing confirmation; cancel an import and cancel a field edit. Inspect rendered values **and** produced tags.

The current model already distinguishes absent configuration keys from explicit empty values in places. Prefer extending that minimal representation consistently. Introduce origin/dirty metadata only if key presence cannot represent the needed contract. Never infer “unset” from `value == ''`. Do not store new persistent state unless necessary to fix an existing persistence contract. Use correct Maker behavior as a comparison, not as an unquestioned implementation template.

Surface meaningful metadata conflicts without adding a blocking prompt for every file. Preserve duplicate detection, queue order, existing values, frozen run/retry plans and valid processing state. Do not replace the workspace on additive import. An explicitly destructive folder/workspace replacement retains its existing confirmation and deliberate semantics.

### 11.4 Optional-model states and 920×600

Resolve the three known Qwen GUI test assumptions using explicit installed/missing states and realistic dialog/thread stubs at the existing boundary. Do not patch the whole world to “installed” or skip absent-state tests. Fix the real Kokoro notice overflow at the supported Windows minimum, including its stale download wording. Preserve setup consent and no-silent-download behavior.

Required combinations include absent/present optional assets, setup offered/declined/cancelled/failed, unavailable runtime, selected voice changing during idle, size/appearance changes and Start/Cancel visibility. Deterministic UI tests may fake asset health only; actual model synthesis/readiness remains a separately named qualification. No downloading gigabytes to test a warning label.

### 11.5 Cross-tool audit and safe cleanup

Audit the six tools against shared contracts for imports/duplicates, queue/settings preservation, validation, enabled states, metadata, progress/events, errors, cancel/pause/retry, safe output naming and publication, source protection, shutdown/recovery and GUI access. Document justified differences rather than flattening all tools into one behavior.

The v0.7.1 `%TEMP%/epub2tts_*`, `tts_direct_*` and pydub leftovers after a killed program need an ownership design. Prefer routing new temporaries into an owned app/run workspace, recording a manifest with random run token, creating PID/start identity and exact paths. Recovery may remove stale owned files only when ownership and inactivity are established, paths remain inside the declared root, and no active/resumable job references them. Do not identify ownership by a filename prefix, age alone or PID alone. Never sweep all of system TEMP, all `.tmp_chunks`, Python processes or FFmpeg processes.

Audit the unsupervised CLI-only M4B `_run_ffmpeg` separately. It is distinct from the Converter's execution module and the Edge routes. A deadline/supervision fix is in scope if the audit confirms a meaningful hang/cancel defect; do not claim it shares the old communicate allocation hang without reproduction. Record unexpected Edge `NoAudioReceived` as service/network evidence with bounded retries, not proof that a release failure is external.

Track every discovery with stable issue ID, severity, source/reproduction, expected/actual result, affected requirements, test, fix/deferral and checkpoint. Product-safety, infinite-hang, source-loss and narration-integrity defects block acceptance. Owner-approved deferrals must be explicit; agents cannot waive failures themselves.

## 12. M4B Converter performance work with strict compatibility

### 12.1 Investigate before optimizing

Trace `m4b/converter/m4b_converter.py` planning/dispatch into `m4b_plan.py`, `m4b_commands.py`, `m4b_execution.py`, probing and Windows decoding. Measure actual invocation counts, per-chapter times, cumulative seek/decode time, encoding, probing, metadata/artwork passes, filesystem work, UI updates and memory. Distinguish FFmpeg-decodable AAC from Windows fallback codecs, whole-book from split, and artwork/no-artwork modes.

The current output-side seek is intentional. Moving `-ss` before `-i` to make a benchmark faster is prohibited unless a separately proven design preserves all boundary content across the original failure corpus and supported decoder/build matrix. Generic FFmpeg accurate-seek documentation is not sufficient proof. Do not stream-copy AAC chapters to MP3 filenames, change VBR quality, omit artwork, parallelize hundreds of encoders or skip validation to hide the slowdown.

Capture a baseline at merged v0.7.1 with identical fixtures/toolchain/settings. Use 10/100/500/1,000+ chapter-count tiers and a separately long-duration source with late chapter starts. A short thousand-chapter file can expose per-chapter overhead but cannot prove that long-prefix seeking was fixed.

### 12.2 Candidate designs to evaluate, not preselected implementation

| Candidate | Benefit to investigate | Proof and cost requirements |
|---|---|---|
| Remove genuinely redundant probes/metadata work | Small, low-risk savings if profiling finds repetition. | Cache identity must account for source changes; preserve validation and mutable metadata semantics. |
| Decode a source continuously and feed sample-exact per-chapter PCM into existing encoders | Can avoid repeatedly decoding the book prefix while preserving an MP3 encode per chapter. | Reuse established timeline partition/PCM format semantics; retain decoder priming, precision, channel layout, boundaries and independent encoder settings. Bound buffering/backpressure and cancellation. Test both FFmpeg and applicable Windows decoder routes. |
| Owned PCM spool or bounded per-chapter spool | Separates one decode from later chapter encodes and may simplify retries. | Measure actual disk expansion for long books, preflight space and refusal/fallback behavior; no full-book RAM buffer. Own/clean temporary files safely. Do not make large unbounded disk requirements a hidden regression. |
| Carefully shared decode/stream pipeline using existing execution seams | May reuse `PcmTimeline`/`run_argv_streaming` and preserve source order. | Inspect actual compatible APIs; do not reuse a Windows-only implementation as though it decodes all formats. Handle worker failures, short feeds, partial outputs and retries. |

Select the smallest design with measured benefit and complete compatibility. Write a brief decision comparing at least the current route and the best feasible alternative. A failed candidate must not replace the reference baseline or weaken its tests. Retain the known-safe old path where an optimized route is not yet qualified; report unsupported optimization cases honestly, without falsely claiming all modes improved.

### 12.3 Output and performance acceptance

Freeze a compatibility manifest: container/extension, codec, VBR quality and other encoding options, sample rate/channels, chapter count/order/content/start/end/title, tags, artwork behavior, filenames/directories, collisions, GUI progress/settings/cancel, retries and publication/source protection. Use actual production output from the reference; no aspirational format substitution.

Measure wall time, per-chapter slope/quartiles, cumulative decode input, process counts, peak working set and commit for the owned process tree, disk bytes/peak temporary space and UI heartbeat. Record hardware, power/load conditions, tool hashes and cache condition. Use repeated runs/medians and a same-session control; do not compare a warm optimized run against a cold overloaded baseline.

Proposed budget starting points, to calibrate and approve from measurements before optimizing: at least 2× throughput on the reproduced prefix-decoding-dominated long split scenario; no more than 10% median regression on routine small jobs beyond measured noise; removal of growth in per-chapter decode cost attributable to earlier chapters; bounded PCM buffering independent of total narration duration. These are engineering targets, not existing performance claims. If profiling disproves the bottleneck or targets, submit the measured alternative at the phase checkpoint before changing the budget. Never adjust a threshold after seeing a failed acceptance run merely to obtain PASS.

Stress tests run separately; routine small semantic/regression tests run in the full gate. Include corrupt chapters/invalid timestamps/short decoder feed, disk pressure, user Cancel in late chapter processing, Retry Failed after a killed decoder, source changes during a run, preserved earlier chapter outputs and no partial final names. Prove improved speed **and** unchanged output contract in the same evidence set.

## 13. Containment, dependencies, source freshness and run retention

### 13.1 Filesystem and process ownership

All new development work and test inputs/outputs stay inside the repository. There is no inherited authorization for the other project's TEST-PC directory or external historical snapshot. Each gate invocation owns only its run child. Redirect `TEMP`/`TMP`, settings, logging, caches and framework scratch per **child environment**, not globally. Set pytest basetemp/cache/JUnit paths to unique children; pytest may clear its own disposable basetemp, so never point it at outputs root, repository, immutable fixtures or an earlier run.

Containment must check lexical traversal, canonical paths and symlink/junction/reparse behavior before writes/deletion; include malicious link-swap negative tests for critical cleanup operations. Never widen a production guard to the whole repository merely to make a fixture work. For application output paths, preserve the product's actual rules while fixtures constrain their chosen destinations to the run.

Launch owned Windows process trees under a kill-on-close Job Object where feasible; detect nested-job restrictions and use an explicitly tested ownership-preserving alternative or BLOCKED. Establish ownership before allowing grandchildren to escape. File-backed/drained bounded diagnostics prevent pipe deadlocks. Terminate, bounded wait, kill, reap; report any remaining owned processes as a failed cleanup condition. No name-based broad kills. Protect an unrelated sentinel Python/FFmpeg process in the supervisor tests.

GUI automation requires an exclusive suitable desktop session; background portable tests may run separately if they cannot interfere with it. Do not broadly parallelize the existing suite without proving import/global-state safety. The known `test_epub_retirement` interaction is a reason to retain full-suite order checks. Edge application workers and test-runner concurrency are different policies.

### 13.2 Dependency and optional-engine qualification

Reuse the existing application Python/Tk/FFmpeg/NLTK pins and hash-locked Windows dependency setup. Audit exact current locks before proposing any addition. Use a separate development lock under gate tooling for genuinely new test dependencies, with compatible transitives and an explicit installation step; a verification invocation never silently installs/updates tools or downloads models.

HOME-PC existing installed assets can be reused read-only where product setup supports it. Qualification must identify actual engine/model/hash/runtime and generated audio; mocked readiness is not real synthesis. Run a bounded representative sample for each of Edge, Kokoro, Chatterbox Turbo and Qwen3-TTS, including important existing voices/reference assets. No local-engine worker-count expansion. CPU/GPU memory and ownership must be measured for actual processes; a generic CPU test does not qualify GPU execution.

Fresh Windows qualification uses an approved clean VM/user profile or contained fresh app extraction with exact limitations stated. Do not call a seeded copy a genuinely unseeded installation. Test launch/repair, no optional assets, deliberate optional choices, offline known-good reuse and recovery after controlled damage to disposable copies. Installing tools/creating a VM or acquiring models needs the applicable approval. Missing prerequisites are BLOCKED. Windows 11 evidence does not qualify Windows 10; native macOS remains NOT RUN until a separate native exercise.

### 13.3 Freshness and evidence portability

Record actual Git root/branch/HEAD; relevant dirty bytes and deletion sentinels; in-scope untracked inputs; test/fixture/config/policy/lock/source digests; OS/Python/Tk/toolchain/assets; selection and applicability. Exclude outputs and self-generated status pointers from the digest. New canonical helpers under a formerly ignored dev-work parent must still be inputs, not invisible local files.

Compare start/end identity and recheck before claiming a later commit accepted. A docs-only commit may carry forward code execution evidence only if the code/test/config/fixture/policy digests and environment match; rerun affected docs/name/config checks, record both execution and reporting SHAs, and never claim a full gate ran on a commit where it did not. If documentation changes include acceptance policy or executable selection, they invalidate the relevant execution evidence.

Generated output and machine-specific paths remain ignored/private. Durable milestone summaries can be tracked in the four permanent docs with sanitized paths/counts/SHA/limits. No personal books, usernames, tokens, full environment dumps or private absolute paths in tracked reports. Final reports link relative run artifacts, validate they exist, and keep necessary context to read them offline.

### 13.4 Retention and cleanup

Never erase prior run directories automatically. The entire outputs subtree is disposable by a deliberate owner cleanup, and the next run recreates it. Keep approved baselines, fixture recipes, locks and config outside it. Teardown stops owned processes and removes safe temporary staging; it preserves evidence including failed/interrupted runs. Report remaining disk use and exact owned cleanup paths at milestones.

Do not remove old owner/reviewer TEMP evidence merely because a newer run passed. If an exceptional external artifact must be created, follow the repository's explicit permission procedure for that exact path and record its eventual cleanup. This plan itself grants no such exception.

## 14. Bounded implementation phases and review checkpoints

These phase numbers belong to **v0.7.2**, not the v0.7.1 plan's local-engine Phase 9. The early Cancel checkpoint is a deliberate addition following the owner's latest clarification. Gate foundation, acceptance infrastructure and feature map still precede the remaining broad hardening.

### 14.1 Contract applying to every phase

At entry record actual branch/HEAD/local preserved state, prerequisites and previous checkpoint. Work only in that phase's scope plus essential tests/docs. Preserve narration/publication/source safety and deliberate tool-specific behavior. Use focused verification while iterating; run changed/full/qualification checks at the stated milestone, not after every small edit.

Each completion report must give: exact outcome; source paths/symbols changed and why; tests/modes/raw results/skips; artifact paths and screenshots/media where required; updated issues/map/inventory; rollback/recovery facts; tested source identity and pushed feature SHA; unresolved prerequisites; review recommendation; exact next bounded task. Commit/push verified task-specific feature checkpoints under standing policy, after explicit staged-diff inspection. Never stage the owner's unrelated deletions or local helpers.

Rollback means a new narrowly scoped revert/fix on the feature branch with tests and preserved evidence, or retention of an unadopted candidate. No hard reset, blanket restore, history rewrite or automatic baseline replacement. If a phase cannot meet a required contract, stop with a reproduction and proposed adjustment; do not proceed by weakening tests.

Significant phases stop for the normal planning review required by 49A. Routine substeps within an approved phase do not need separate approval. The current deliverable authorizes no coding in this planning environment beyond the already completed owner-authorized v0.7.1 integration.

An intermediate checkpoint must distinguish newly introduced failures from the specifically recorded inherited optional-voice failures assigned to Phase 5. If those four reproduce unchanged on the reference baseline, retain them as open planned work and report the actual failed gate; do not call it PASS, suppress them or invent a new waiver. They must be corrected before final v0.7.2 acceptance. New safety regressions remain immediate blockers.

### Phase 0 — Local baseline, containment and native feasibility audit

**Entry:** refreshed `origin/master`; expected minimum baseline `204c33b`; this plan supplied under `files/plans/`. Read current instructions and actual local files. No additional v0.7.1 independent review is required.

**Scope:** read-only application investigation and disposable audit evidence. Inspect all six tools, existing tests/fixtures, gate/callers, guarded roots, release manifest, ignore policy, optional assets, desktop/DPI capability, source fingerprints and dependency locks. Reconcile local Git with the remote fast-forward without discarding owner state. Propose the new v0.7.2 branch from the actual production base; do not repurpose the old feature line.

**Outcomes:** a path/caller migration inventory, preservation baseline, issue ledger, preliminary surface inventory, confirmed native pilot, measured/practical test budgets and Phase 1 recommendation. Explicitly reproduce old delayed Cancel under a bounded observation, then stop the owned probe safely; do not run ten-minute finalization as a prerequisite. Check MP3 first-import provenance and the log renderer's live behavior. Profile only enough M4B code/workflow to plan the later measured phase; no optimization yet.

**Verification/evidence:** reuse recent gate evidence only after matching its source/test identity. Run a small justified audit subset, not another 86-minute full baseline by habit. Save `baseline.md`, `migration-inventory.md`, `native-pilot.md`, `issues.json` and `phase-1-recommendation.md` inside a unique ignored `files/dev-work/verification-gate/outputs/<timestamp>_phase0_<id>/` audit directory. This is audit evidence created before the new runner exists, not a claimed execution of a future command. Record unavailable Windows capabilities honestly. Do not install packages, download models or edit production/tests in this audit.

**Recovery:** all disposable pilot actions are owned and contained; stop only owned processes. Preserve input/settings checksums and owner state before/after. A blocked native pilot must identify precisely what is missing and a fallback proposal.

**Checkpoint/stop:** report results and dependency/adapter choice for review; stop before source implementation. Lasting sanitized facts may be proposed for the first implementation docs checkpoint, but do not edit current-state history as part of a read-only audit. **Next:** Phase 1 Cancel/Pause correction with the existing gate.

### Phase 1 — Correct Cancel and retain graceful Pause

**Entry:** reviewed Phase 0 recommendation; new `feature/0.7.2-windows-hardening-verification` from refreshed production base, preserving owner work. Existing v0.7.1 full-gate command remains usable during this phase.

**Allowed scope:** TTS/job cancellation, memory waits, owned FFmpeg control, publication race boundaries, affected engine adapters if demonstrated necessary, existing/new cancellation tests, and current docs/plan. No concurrency expansion or gate migration yet.

**Outcomes:** §3.1/§11.1 contracts implemented. Prompt cancellation in every stage, no completion-on-Cancel fallback, Pause drains active files only, no new admissions, immediate cancellation of paused queues, correct terminal states, no reservation/process leaks and no source/output loss.

**Verify:** deterministic barriers plus valid-media/native smoke where available; cancel synthesis/final paragraph/gate wait/assembly/encode/stalled child and race with commit; mixed 8-worker queues and local single-worker routes. Prove no new Edge requests or retry/fallback after Cancel. Negative control reinstating old finish semantics must fail. Run focused tests, full-suite import-order controls and one existing full gate at the completed product checkpoint. Record exact measured stop deadlines and any unsupported engine state.

**Evidence/docs:** before/after trace with action timestamps, per-worker/task outcomes, child ownership, reservations, output hash/validity, unchanged normal narration and pause behavior. Append the owner's new decision; update current handoff to merged v0.7.1 and separate v0.7.2. Correct active Cancel instructions and tests that intentionally encoded the superseded policy. Record initial stable feature IDs without pretending a complete feature map exists yet.

**Recovery/checkpoint:** retain the last tested branch checkpoint and failure evidence; do not revert to delayed Cancel to pass a guard. Commit/push verified changes and stop for review. **Next:** canonical gate foundation.

### Phase 2 — Migrate and strengthen the canonical gate foundation

**Entry:** Phase 1 accepted; preserved suite and current tested source identity available.

**Allowed scope:** existing gate relocation into `files/dev-work/verification-gate/`, imports/callers, guarded root/config migration, pytest config only where necessary, ignore rules, result policy/supervision/freshness helpers, tests and documentation. Runtime source only if an audited dependency on the developer gate must be removed without behavior change.

**Outcomes:** one canonical entry point; proposed modes/help/exit codes frozen; unique runs; normalized status/lifecycle; preserved legacy evidence reader; deterministic collection partition; safe per-run settings/temp/log outputs; expanded relevant-input fingerprints. Migrate guarded basetemp/report authorities atomically, keeping least privilege and exact suite membership.

**Verify:** existing evidence/guard/repository/source-boundary tests adapted without weakening; ordinary-versus-guarded set equality; invocation from other CWD; duplicate run refusal, absent outputs recreation, unsafe paths, interrupted run, child timeout/grandchild cleanup, no false PASS, source change invalidation. Compare old/new gate behavior on a contained representative passing/failing fixture tree; the old implementation is a temporary comparison fixture, not a second shipped runner. Run one migrated full gate before the checkpoint.

**Evidence/docs:** old/new caller map, selected/collected/executed inventories, root-policy negative controls, exact changed contracts, packaging exclusion result and new run report. Keep old evidence intact. Update active docs to the canonical command; preserve historical references as historical.

**Recovery/checkpoint:** do the move as a coherent verified slice; no permanent forwarding script in `scripts/`. If migration breaks isolation, fix authority checks before continuing. Commit/push; stop for review. **Next:** native/media acceptance and inventory enforcement.

### Phase 3 — Automated acceptance infrastructure

**Entry:** accepted canonical gate and reviewed native/dependency pilot. Any new development dependency installation is separately authorized and reproducibly pinned.

**Allowed scope:** selected Windows adapter/test launcher, valid-media generators/oracles, coverage schema/collector, gate contract tests, scenario definitions, candidate visual baselines, fixture documentation and necessary narrow test seams outside distributed runtime.

**Outcomes:** actual native workflows plus real media for each tool; test scope classification; required-ID enforcement; strict prerequisites and visual-candidate handling; deterministic execution without inference. Preserve useful widget and mock tests.

**Verify:** at least one complete native and real-output journey for each of six tools, correct action/result linkage, meaningful adverse cases, locked/unavailable desktop behavior, fake-versus-real fixture classification, corrupt output detection, no settings/source writes outside run. Challenge empty selection, stale/copied reports, missing media/visual evidence and contradictory child statuses.

**Evidence/docs:** adapter fit/result, native actions/state/screenshots, validated input/output manifests, normalized reports, dependency/license provenance and owner review package for any proposed visual baseline. Baseline approval is explicit; no auto-approval in a normal run.

**Recovery/checkpoint:** reject inadequate adapters or bad fixtures while retaining evidence; use the proven fallback or report BLOCKED. Commit/push only working infrastructure; do not label partial inventory as release complete. Stop for review. **Next:** full feature/control/workflow mapping.

### Phase 4 — Complete the ACT feature map and coverage inventory

**Entry:** working scenario infrastructure and preliminary surface index.

**Allowed scope:** all eight map documents, single coverage inventory, stable scenario/test IDs, missing tests/fixtures, discovery/maintenance checks and focused test helpers.

**Outcomes:** all six tools, launcher, setup/repair and shared workflows indexed with real source/control/state/output contracts. Distinguish inventory review, mapping, executed satisfaction and line coverage. Identify any genuine automation exceptions for owner approval.

**Verify:** every discovered surface reviewed against source and live relevant states; no dangling IDs or unused required controls; source changes trigger appropriate review/selection; required tests actually execute. Inject a new unmapped control/workflow and deleted test to prove detection. Run all mapped routine journeys and relevant existing suites; full acceptance must still report outstanding runtime failures honestly.

**Evidence/docs:** surface discovery ledger, mapped/executed coverage reports, documented intentional differences and proposed exceptions with exact approval scope. Do not duplicate the mapping database in prose.

**Recovery/checkpoint:** missing functionality remains an open requirement, not removed inventory. Commit/push; stop for inventory/exception review. **Next:** known runtime defects using the new gate.

### Phase 5 — Known log, metadata and optional-state defects

**Entry:** reviewed coverage inventory and accepted test infrastructure; Phase 1 Cancel behavior remains required.

**Allowed scope:** `shared/job_ui.py` and other proven log views; MP3/default/shared metadata paths; relevant Maker comparison paths; Kokoro notice layout; Qwen GUI assumption tests; directly related state handling; regressions/map updates.

**Outcomes:** follow/hold/resume logs; explicit metadata including intentional clearing survives imports; all four known fresh-environment failures fixed without suppression; Start/Cancel reachable at 920×600. Preserve all other user contracts.

**Verify:** the detailed §11 matrices with real widgets/native actions and valid output tags; installed and absent assets; dynamic scaling/layout; high-rate logs; additive/cancelled imports and frozen retry state. Focused then changed-area verification; broader full run at the completed phase if shared changes warrant it. Do not run a full gate after each notice/field edit.

**Evidence/docs:** before/after reproductions, saved tags/output hashes, geometry/screenshots, revised feature contracts and issue dispositions. Retain optional missing-state evidence separately from actual engine qualification.

**Recovery/checkpoint:** regressions remain failures; no raising minimum size or erasing blank values to pass. Commit/push and stop for review. **Next:** systematic cross-tool hardening.

### Phase 6 — Cross-tool consistency, recovery and cleanup

**Entry:** known defects corrected, coverage map maintained.

**Allowed scope:** confirmed meaningful defects across imports/settings/jobs/output planning/cancel/retry/shutdown/cleanup and related interfaces. Ownership-safe TEMP recovery and CLI-only subprocess supervision may be included when reproduced. No unrelated visual redesign or new persistence/concurrency features.

**Outcomes:** consistency matrix covering six tools, issue ledger with tested fixes or explicitly proposed deferrals, reliable source protection and publication, safe owned temporary recovery, settings/import state preservation and actionable errors.

**Verify:** representative complete user journeys for every affected tool; controlled failures/collisions/kills; correct already-published outputs and original sources after cancellation; active/stale/foreign temporary ownership scenarios; unrelated sentinel processes survive. Run changed-area checks per slice and full Windows routine gate at the phase milestone.

**Evidence/docs:** cross-tool comparison, exact differences retained and why, per-finding tests/artifacts, cleanup ownership proof and coverage updates. Agents cannot approve a required-coverage reduction.

**Recovery/checkpoint:** revert only a task's unaccepted candidate with a new verified commit if needed; preserve evidence/data. Commit/push verified slices and stop for review. **Next:** measured M4B performance work.

### Phase 7 — Profile and optimize M4B chapter splitting

**Entry:** stable gate and source safety; valid routine/scaling/duration fixtures; preserved `204c33b` compatibility reference.

**Allowed scope:** actual Converter bottleneck, minimal command/execution/timeline/probing changes justified by profiling, bounded temporary handling, performance/compatibility tests and map/docs. Do not change other tools' codecs or output format.

**Sub-checkpoint 7A:** capture reference outputs and detailed performance profile; compare candidate designs; freeze budgets and compatibility manifest. Report the chosen design before high-risk replacement. Routine parameter choices inside the reviewed design are autonomous.

**Sub-checkpoint 7B:** implement the smallest proven optimization, preserving partition/priming/artwork/metadata/output contracts. Keep buffering and disk cost bounded and documented. Preserve safe old routing where a new route is unqualified.

**Verify:** source-timeline marker/oracle tests, baseline-versus-candidate bytes/semantics, ordinary/late chapters, short and long sources, thousands of chapters, decoder variants, tags/artwork, invalid boundaries, short feed, disk pressure, kill/cancel/retry and no partial publication. Prove meaningful speed improvement under the frozen budgets; routine semantic checks plus separate performance qualification.

**Evidence/docs:** raw per-chapter timings, process/memory/commit/disk/heartbeat measures, exact tool/fixture/source identities, compatibility diff and measured limitation report. No claims inferred solely from command shape.

**Recovery/checkpoint:** reject faster-but-corrupt routes; do not loosen the audio oracle or substitute a format. Commit/push and stop for performance/compatibility review. **Next:** comprehensive Claude qualification.

### Phase 8 — Full Windows self-verification and readiness package

**Entry:** all required implementation complete; issue ledger and map current; approved baselines/exceptions recorded.

**Allowed scope:** bounded remediation of discovered in-scope defects, final documentation, tests and release-identity/packaging validation. Establish v0.7.2 version/config/test identity together at a named checkpoint before final evidence; no published tag/archive/release. Earlier development checkpoints remain explicitly unreleased.

**Outcomes:** complete routine full-gate results, required qualification profiles, real engine samples, fresh Windows evidence at actual supported scope, no unresolved required failures/coverage gaps. Include the updated Cancel/Pause behavior and all legacy Edge safety findings in the final matrix.

**Verify:** one final full Windows gate on the final code/test/config/policy state, required Edge low-memory/publication/concurrency and M4B scaling/duration scenarios, optional engines and setup/repair where applicable. Measure actual native desktop/DPI coverage. Re-run only affected evidence after fixes, then obtain coherent final acceptance for changed shared contracts. A docs-only closeout may use §13.3 carry-forward with explicit identities.

**Evidence/docs:** `agent-review.md`, exact run/source/environment inventory, required coverage satisfaction, qualification summary, screenshots, output samples, residual manual checklist, package manifest and private-data exclusions. Keep reports concise enough for independent review but link raw evidence. Feature checkpoint commit/push is not independent acceptance.

**Recovery/checkpoint:** failures return to bounded Claude remediation, never blanket expected-failure additions. Stop for review of the implementation/readiness package. **Next:** fresh independent Codex Extra High review.

### Phase 9 — Final independent Codex Extra High review

**Entry:** Claude's completed v0.7.2 feature checkpoint and full readiness package. Use a fresh Codex CLI context at Extra High reasoning effort. Verify actual supported model/effort controls locally; do not invent CLI flags.

**Scope:** independent read-only source assessment and execution/challenge of the new gate/map across v0.7.2. Test artifacts may be written only to owned contained evidence; no fixes, commits, pushes or merge by the reviewer. Use a separate owned contained checkout if feasible, protecting the owner's live checkout and dirty state. Do not create external scratch without authorization.

**Required verdict areas:** gate false-PASS protections and coverage completeness; actual native workflows; valid media/oracles; Cancel versus Pause in every stage; metadata/settings/import preservation; log following/layout/optional states; Converter performance and unchanged output; installation/repair/packaging; subprocess/temp ownership. Revisit the inherited Edge HIGH-001/HIGH-002A/HIGH-002B/R2-1 mechanisms and eight-worker concurrency as foundations of the final application, without treating v0.7.1 as awaiting another pre-merge review. Verify local engines remain single-worker and test the pydub seam's relevant effects on them.

**Verify/evidence:** independently run the full applicable Windows gate and selected adversarial qualification probes, inspect outputs/screenshots rather than trusting summaries, challenge negative controls and test changes. Missing desktop/assets/platforms must be recorded honestly. Give PASS/BLOCKED per critical area with severity, source symbol/line, reproducible observed/expected results and evidence paths. Do not use personal listening as an excuse to skip objective audio-boundary validation.

**Recovery/checkpoint:** any blocker goes to Claude for a bounded fix, affected gate rerun and necessary independent re-review. Codex does not repair its own reviewed implementation. Save the report and stop; no v0.7.2 merge yet. **Next:** residual owner checks and explicit integration decision.

### Phase 10 — Owner acceptance and v0.7.2 integration readiness

**Entry:** final independent review passed for the actual current source and relevant qualification; all approved exceptions current.

**Owner checks:** representative narration listening/endings and personal UX judgment; observe prompt Cancel and graceful Pause; approve remaining visual baselines; confirm relevant fresh-launch/repair behavior and documented limitations. Keep the checklist small by relying on real automated evidence for routine regression coverage. Listening and native GUI checks not actually performed remain pending.

**Verify:** exact tested source and remote feature SHA, no unreviewed code/policy drift, required coverage and qualification, metadata/media compatibility, packaging exclusions and protected assets. Prepare a merge recommendation with exact branch/base/head and residual risks.

**Stop:** request separate explicit authorization to integrate v0.7.2. The owner's earlier permission to merge v0.7.1 does not carry forward. No tag, release or archive publication is implied by a later merge either. After authorized integration, verify actual remote production SHA/tree and report the evidence relationship.

## 15. Definition of done, risks and unresolved local facts

### 15.1 Implementation done

- One canonical, tracked developer gate with no competing runner under `scripts/`; existing suites/guards preserved and all new outputs contained.
- Complete reviewed feature/workflow/control inventory, meaningful required mappings, actual current-scope execution and approved exceptions only.
- Native Windows interaction and valid real-media outputs proved for all six tools and shared workflows.
- Cancel promptly stops active work, including finalization; Pause drains active files without admitting new work; valid published outputs and original sources preserved.
- Logs follow/hold/resume correctly; explicit metadata and deliberate blanks survive imports; four absent-asset test/layout failures corrected.
- Confirmed meaningful consistency/safety defects resolved, with deferrals individually approved rather than hidden.
- M4B optimization measured on the actual slowdown and unchanged user-facing output contract independently verified.
- Required self-tests reject false PASS, incomplete/stale evidence, missing coverage/prerequisites and unsafe cleanup.
- Required Windows routine/qualification evidence is coherent for final source; local engines remain single-worker; platform limits and remaining owner checks are honest.
- Claude readiness package complete; fresh independent Codex Extra High review passed after implementation; residual owner acceptance complete.
- v0.7.2 merge/release remains separately authorized, and post-integration source identity is verified when that action is approved.

### 15.2 Risk and mandatory-local-check register

| Risk/unresolved fact | Mandatory action and acceptance consequence |
|---|---|
| Owner checkout differs from remote; 14 deletions/local guidance/assets | Read-only inventory and safe branch creation in Phase 0; no assumption of clean checkout. |
| Current v0.7.1 docs still prescribe old review/cancel sequence | Record latest owner decisions at Phase 1; preserve historical reports. No new Codex gate before the already completed v0.7.1 merge. |
| Tk/ttk accessibility is partial or native desktop unavailable | Real pilot and narrow fallback; required native scope BLOCKED if neither works. |
| Guarded root migration accidentally widens permissions | Negative controls and exact collection partition; no phase acceptance on guard regression. |
| Canonical directories hidden by existing ignore rules | Explicit tracking/ignore proof; untracked relevant inputs included in fingerprints. |
| Native automation affects the owner's desktop | Exclusive lease, owned target/focus checks, synthetic windows only; fail safely on focus loss. |
| Pydub global supervision touches local-engine exports | Test real cancellation/exports where applicable; no assumption that unchanged engine modules prove unchanged behavior. |
| Immediate cancellation exposes publication/cleanup races | Barrier-controlled tests and short commit linearization; no post-cancel fallback or unsafe deletion. |
| Media generator cannot represent 1,000+ chapters correctly | Validate container chapter count before product testing; adjust the fixture representation with evidence, not silent truncation. |
| Fast seeking restores AAC priming loss or artwork truncation | Full-source PCM boundary oracle, long-duration fixtures, exact baseline controls; reject wrong-content speedups. |
| Performance target not achievable with a small safe change | Report profile/candidate results and seek a bounded design decision before changing accepted budgets. |
| Optional assets/Windows configurations not available | Mock only deterministic UI states; real qualification remains BLOCKED/NOT RUN for missing prerequisites. |
| Evidence on dirty/changed inputs overstates final acceptance | Separate digests, before/after checks and explicit carry-forward rules. |
| Long tests consume excessive time/tokens | Focused/changed/full/qualification scheduling, concise summaries and raw streamed evidence; do not weaken required checks. |
| Killed process leaves large temporaries | New ownership manifest/root design and safe recovery tests; no prefix-based TEMP sweep. |

## 16. Phase 0 kickoff prompt for Claude Code CLI

Use a fresh implementation context for the new v0.7.2 project phase, or compact an existing session while retaining the repository handoff. There is no need to preserve the old remediation session's reasoning. Read this plan and actual repository state as authority; use the short prompt below. It starts an audit, not the whole implementation without phase review.

```text
Begin ACT v0.7.2 Phase 0 from files/plans/ACT-v0.7.2-Windows-Hardening-Feature-Map-and-Verification-Gate-Implementation-Plan.md. Read the complete plan and follow its latest-owner amendments and original 50-decision register.

v0.7.1 was separately merged by fast-forward: remote master was verified at 204c33bbd2d11db8a0848b261a5cb567a9240d74. Do not request or start another independent Codex review for that merge. Refresh actual refs; preserve unrelated owner deletions, untracked guidance, assets and environments. Plan the new feature/0.7.2-windows-hardening-verification branch from the current approved production base, rather than continuing the old v0.7.1 branch.

Perform the read-only local audit and contained native feasibility pilot. Inventory existing gate/test callers, guarded roots, source/fixture fingerprints, ignore/packaging rules, all six tools and actual GUI/media coverage. Verify dependencies and desktop capability without installing anything or downloading models. Reproduce relevant known behavior safely, including Cancel continuing finished narration, logs and metadata defaults. Record source facts separately from earlier reported test results.

The owner requires Cancel to stop active work promptly, including assembly/encoding; only Pause drains current active files. Phase 1 will correct that using existing tests before the gate migration. Do not implement that fix or broader changes during this audit.

Save audit evidence only inside the repository. Report exact Git/local preserved state, native adapter findings, path/caller migration inventory, issue ledger, test-budget/prerequisite observations and a concrete Phase 1 recommendation. Do not modify production source/tests, merge, tag or release. Stop at the Phase 0 review checkpoint. After all v0.7.2 implementation and self-verification, a fresh independent Codex Extra High review is required before its separately authorized merge.
```




## Appendix A. Original approved 50-decision register

All 50 decisions below were approved Option A in the original consultation. This preserves the original wording. The latest-owner overrides in §1.1 govern release number, branching, review/merge timing and Cancel behavior; do not use this historical register to undo them.

### A. Batch 1 — Scope, priorities and initial architecture

| ID | Approved decision |
|---|---|
| 1A | Complete Edge review before substantial hardening implementation; review timing subsequently amended by 50A. |
| 2A | Continue development on `feature/0.7.1-multi-file-workers`, preserving reviewed checkpoints. |
| 3A | Verify all six ACT tools, launcher, installation/repair, settings and shared infrastructure. |
| 4A | Incrementally integrate existing tests while preserving coverage and identities; safely relocate developer-only runners. |
| 5A | Create `files/dev-work/feature-map/`, with individual tool documentation and shared-workflow mappings. |
| 6A | Require 100% mapping of registered release-required functionality to meaningful automated verification or approved exceptions. |
| 7A | Combine pytest/Tkinter tests, piloted native Windows UI automation and appropriate supporting tools. |
| 8A | Correct all four known clean-environment failures, including the Kokoro minimum-size layout defect. |
| 9A | Logs follow new messages when at the bottom, stop following when manually scrolled up, and resume when the user returns to the bottom. |
| 10A | Use focused, changed-area, full Windows and separate representative stress verification modes. |

### A. Batch 2 — Runtime fixes, consistency and M4B performance

| ID | Approved decision |
|---|---|
| 11A | Preserve explicitly entered, edited or intentionally cleared MP3 album metadata when additional files are imported. |
| 12A | Apply consistent metadata precedence across applicable tools: explicit user edits, preserved session values, then imported defaults. Surface meaningful conflicts. |
| 13A | Standardize equivalent cross-tool behavior while preserving justified tool-specific differences. |
| 14A | Preserve existing queue contents, ordering, settings and valid processing state when importing additional files; handle duplicates deliberately. |
| 15A | Audit settings persistence and restoration, fixing unintended resets without broadly introducing new persistence features. |
| 16A | Establish consistent cancellation, retry, source protection, safe publication and actionable error contracts. |
| 17A | Profile the existing M4B Converter chapter-splitting implementation before selecting an optimization. |
| 18A | Preserve chapter integrity, quality, metadata, output requirements and safe handling; strengthened by the owner amendment below. |
| 19A | Establish measured baseline performance, regression budgets and separate 1,000-plus-chapter stress tests. |
| 20A | Systematically discover defects; remediate release-critical and meaningful in-scope problems, with explicitly approved deferrals where justified. |

**Binding amendment to 18A — User-invisible M4B optimization**

The owner requires the optimized M4B Converter to produce the same user-visible results in exactly the same existing output format.

Preserve the established:

- Container and file extension.
- Codec and encoding parameters.
- Chapter count, order, content, boundaries and titles.
- Metadata and artwork behavior.
- Filenames, directory structure and collision policy.
- Audio quality and decoding integrity.
- GUI workflow, settings, progress and cancellation behavior.
- Error and partial-output recovery contracts.

The only intended user-visible difference is improved processing speed on large chapter-splitting jobs.

Establish a before/after compatibility baseline using actual production processing and valid fixtures.

Where byte identity is a guaranteed invariant, enforce it. Otherwise, verify semantic and technical equivalence independently without requiring byte equality where the existing container/codec behavior does not guarantee it.

Do not redesign the format or relax existing output characteristics merely to obtain better benchmark numbers.

### A. Batch 3 — Verification and feature-map implementation

| ID | Approved decision |
|---|---|
| 21A | Establish one canonical verification runner under `files/dev-work/verification-gate/`. |
| 22A | Maintain human-readable feature documentation linked to one authoritative machine-readable coverage inventory. |
| 23A | Require feature-map, fixture and test-mapping maintenance alongside relevant source changes. |
| 24A | Exercise actual Windows GUI interactions in addition to widget-level testing. |
| 25A | Use small valid synthetic media to exercise real application processing paths and inspect actual outputs. |
| 26A | Use explicit PASS, FAIL, BLOCKED, NOT RUN and NOT APPLICABLE reporting, with separate lifecycle states. |
| 27A | Give each verification invocation a unique disposable evidence directory; preserve previous run evidence. |
| 28A | Adversarially self-test the gate against false PASS, missing prerequisites, failures, stale evidence and incomplete runs. |
| 29A | Run verification deterministically without requiring continuous AI inference or model-driven clicks. |
| 30A | Isolate test settings, processes and output paths; enforce safe cleanup and source/test/config freshness. |

### A. Batch 4 — Qualification, performance and release policy

| ID | Approved decision |
|---|---|
| 31A | Use reproducible pinned development dependencies, without silent installations or model downloads. |
| 32A | Test installed and missing optional voice/model states; separately qualify real engines. |
| 33A | Qualify HOME-PC and isolated fresh Windows environments, reporting actual OS coverage honestly. |
| 34A | Capture screenshots, test scaling/overflow and require explicit review before approving visual baselines. |
| 35A | Establish measured processing, memory, responsiveness and long-job scaling regression budgets. |
| 36A | Schedule focused, changed-area, full and expensive stress gates efficiently. |
| 37A | Research suitable existing verification skills, frameworks and feature-map approaches before adoption. |
| 38A | Windows is the present release target; macOS acceptance remains separate and unverified until native qualification. |
| 39A | Use bounded Claude phases and checkpoints, followed by independent Codex Extra High comprehensive review. |
| 40A | Require complete applicable Windows acceptance, safety, media compatibility, independent review, residual owner checks and separate release authorization. |

### A. Batch 5 — Migration, evidence, permissions and sequencing

| ID | Approved decision |
|---|---|
| 41A | Preserve existing `files/tests/` initially and integrate it through the canonical runner; migrate selectively where beneficial. |
| 42A | Relocate developer-only `scripts/verify.py` functionality; update callers, tests and references, without retaining a competing permanent developer runner in `scripts/`. |
| 43A | Document all ACT tools, controls, source locations, workflows, states, dependencies, failure cases, output contracts and test IDs in the feature map. |
| 44A | Require owner-approved, explicit exceptions for functionality not fully automatable; agents cannot approve their own reductions in required coverage. |
| 45A | Use valid synthetic M4B files with thousands of short chapters for efficient scaling tests, supplemented by separate long-duration stress scenarios. |
| 46A | Native Windows GUI acceptance requires a suitable interactive desktop; unavailable desktop prerequisites produce BLOCKED, not a simulated PASS. |
| 47A | Preserve run evidence until deliberate, safe disposal; keep durable milestone summaries without committing generated private or large test artifacts. |
| 48A | Claude may autonomously correct confirmed in-scope defects and commit/push verified feature checkpoints; material scope changes, installations and external modifications require approval. |
| 49A | Review significant phase checkpoints before authorizing the next major phase; do not require approval for every routine substep. |
| 50A | Use the current Claude High Edge review as the preliminary review; defer dedicated independent Edge verification to the final comprehensive Codex Extra High review. |

These 50 decisions, as explicitly amended by §1.1, constitute the requirements register.

Do not infer additional ACT commitments from the separate Vibe Coding Files consultation.

## Appendix B. Decision-to-phase traceability

The machine-readable inventory created during implementation is the future authoritative functional mapping. This table maps the approved planning decisions to delivery checkpoints; it does not claim execution coverage.

| Original decision IDs | Main implementation checkpoints |
|---|---|
| 1A, 2A, 39A, 40A, 48A, 49A, 50A | §1.1 latest-owner overrides; Phases 0–10 and integration boundaries. |
| 3A, 5A, 6A, 22A, 23A, 43A, 44A | Phases 0, 3, 4 and ongoing mapping/exception enforcement. |
| 4A, 21A, 27A, 30A, 41A, 42A, 47A | Phase 2 migration, containment/freshness, evidence preservation and packaging. |
| 7A, 24A, 25A, 28A, 29A, 34A, 46A | Phase 0 native pilot, Phase 3 acceptance/oracles/self-tests and Phase 9 independent challenge. |
| 8A, 9A, 11A, 12A | Phase 5 optional-state/layout, log and metadata fixes. |
| 13A, 14A, 15A, 16A, 20A | Phase 1 updated Cancel/Pause contract; Phases 5–6 consistency, settings, imports, recovery and defects. |
| 10A, 19A, 26A, 35A, 36A | Phase 2 modes/status/lifecycle, Phase 7 performance budgets and Phase 8 qualification scheduling. |
| 17A, 18A, 45A | Phase 7 profiling, valid large-chapter fixtures and unchanged-output optimization. |
| 31A, 32A, 33A, 38A | Phase 0 dependency/platform audit; Phase 8 actual optional-engine/fresh-Windows qualification; honest macOS limits. |
| 37A | §4 pinned source inspection and Phase 0 local fit validation before dependency adoption. |

## Appendix C. Sources, revisions and evidence provenance

Primary source inspection supports the findings and design decisions. No third-party skill was activated and no upstream runtime was installed here. URLs using the pinned SHA identify exactly the inspected source. Official documentation may change; implementation must check its installed-version APIs rather than upgrade packages to match a live docs page.

### C.1 ACT source and Git facts

- [Merged v0.7.1 source checkpoint, 204c33b](https://github.com/elmatthe/audiobook-creation-tool/commit/204c33bbd2d11db8a0848b261a5cb567a9240d74).
- [Production-to-feature comparison used before fast-forward](https://github.com/elmatthe/audiobook-creation-tool/compare/c0896d8714ef14419261b060af34490b18a47a14...204c33bbd2d11db8a0848b261a5cb567a9240d74).
- [Docs-only comparison after the full-gate checkpoint](https://github.com/elmatthe/audiobook-creation-tool/compare/b18518601061743a9408c2070fec1222a4f3934e...204c33bbd2d11db8a0848b261a5cb567a9240d74).
- [Committed implementation-agent handoff](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/md-instructions/Handoff.md), top CURRENT STATE block. Its future-sequence/Cancel statements are superseded by this conversation; its historical results retain their reported-evidence status.
- [v0.7.1 plan](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/plans/ACT-v0.7.1-Edge-Multi-File-Workers-Plan.md), especially §§12–15 for reported evidence, limits and old Cancel policy.
- [Existing developer gate](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/verify.py): `load_guarded_spec`, `check_guarded`, `resolve_evidence_dir`, `tree_fingerprint`, `read_evidence_status`, `run_with_evidence`.
- [Guarded runner](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/guarded_pytest.py), [guarded suite specification](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/guarded_groups.json), [pytest collection configuration](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/pytest.ini), [source boundary helper](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/source_probe.py) and [test isolation fixtures](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/conftest.py).
- [Gate evidence regressions](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_verify_evidence.py), [guarded-gate regressions](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_verify_guarded.py), [repository contracts](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_repository_contract.py) and [application-source-boundary contracts](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_application_source_boundary.py).
- [Shared job/log UI](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/shared/job_ui.py), `SummaryDetailsView._write`, and [theme geometry](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/shared/ui_theme.py).
- [MP3 workspace defaults/imports](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/mp3/mp3_workflow.py), `_prepopulated` and `add_files`, and [MP3 panel](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/mp3/mp3_tool.py), `_project_import`.
- [Converter command/priming contract](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/m4b/m4b_commands.py), [execution and stream feed](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/m4b/m4b_execution.py), [Windows PCM timeline](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/m4b/m4b_winaudio.py).
- [FFmpeg watch/Cancel policy](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/tts/ffmpeg_watch.py), `_Control`, `controlled` and `_verdict_on`; [memory gate/fallback policy](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/tts/worker_limits.py), `AssemblyGate.place` and `assemble`.
- [Actual low-memory probe helper](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/low_memory_probe.py), [Qwen GUI tests](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_qwen3_gui.py), [output orchestration fixtures](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_tool_output_integration.py).
- [Packaging authority](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/scripts/shared/release.py) and [packaging tests](https://github.com/elmatthe/audiobook-creation-tool/blob/204c33bbd2d11db8a0848b261a5cb567a9240d74/files/tests/test_release_packaging.py).

The six production panels, launcher, shared config/settings, Maker workflow and supporting files were also read for source orientation. File existence in the tree alone is not claimed as a behavior audit or executed coverage.

### C.2 Upstream source inspection

- Cursor plugins at `bb68f2365eceafa0cb2d253112f675acf5f144cc`: [create verification](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/skills/create-verification-skill/SKILL.md), [feature example](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/skills/create-verification-skill/references/feature-map-example/create-note.md), [maintain verification](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/skills/maintain-verification-skill/SKILL.md), [control-ui](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/cursor-team-kit/skills/control-ui/SKILL.md), [control-cli](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/cursor-team-kit/skills/control-cli/SKILL.md), [pstack license](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/LICENSE) and [team-kit license](https://github.com/cursor/plugins/blob/bb68f2365eceafa0cb2d253112f675acf5f144cc/cursor-team-kit/LICENSE).
- Anthropic skills at `ca45fc496a3436251f191354091d557da31c15b5`: [webapp-testing](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing/SKILL.md), [server helper](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing/scripts/with_server.py), [skill license](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing/LICENSE.txt).
- Autodesk at `f11f48f4976811b46e2f65825e4010ea875d1da3`: [compiler](https://github.com/Autodesk/claude-browser-test-skills/blob/f11f48f4976811b46e2f65825e4010ea875d1da3/skills/compiler/SKILL.md), [runner](https://github.com/Autodesk/claude-browser-test-skills/blob/f11f48f4976811b46e2f65825e4010ea875d1da3/skills/runner/SKILL.md), [quality workflow](https://github.com/Autodesk/claude-browser-test-skills/blob/f11f48f4976811b46e2f65825e4010ea875d1da3/.github/workflows/quality.yml), [license](https://github.com/Autodesk/claude-browser-test-skills/blob/f11f48f4976811b46e2f65825e4010ea875d1da3/LICENSE).
- Superpowers at `22f0b463e7a5e579904dd6211a520321035526f7`: [verification-before-completion](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/skills/verification-before-completion/SKILL.md), [license](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/LICENSE).
- pywinauto at `a428d9617a429a76779d235f0702ec0e94b26214`: [Windows application tests](https://github.com/pywinauto/pywinauto/blob/a428d9617a429a76779d235f0702ec0e94b26214/pywinauto/unittests/windows/test_application.py), [license](https://github.com/pywinauto/pywinauto/blob/a428d9617a429a76779d235f0702ec0e94b26214/LICENSE), [official getting started](https://pywinauto.readthedocs.io/en/latest/getting_started.html), [official remote execution limitations](https://pywinauto.readthedocs.io/en/latest/remote_execution.html).

Licenses were inspected at these paths; license labels do not imply redistribution of a dependency or that its transitive dependencies were approved. No downloaded upstream code is part of this implementation-plan deliverable.

### C.3 Official API references and supplied design material

- [Python 3.12 Tkinter and threading model](https://docs.python.org/3.12/library/tkinter.html#threading-model).
- [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html) and [JUnit/report output](https://docs.pytest.org/en/stable/how-to/output.html). Match the installed pinned version before encoding the mapping.
- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput), [OpenInputDesktop](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop).
- [FFmpeg seek documentation](https://www.ffmpeg.org/ffmpeg.html), [ffprobe documentation](https://www.ffmpeg.org/ffprobe-all.html), [FFmpeg licensing](https://ffmpeg.org/legal.html). Direct retrieval of the ffprobe HTML pages and licensing page timed out in this session; those are implementation-time reference links, not claimed successful page inspections. The upstream [ffprobe documentation source](https://github.com/FFmpeg/FFmpeg/blob/master/doc/ffprobe.texi) was successfully read to confirm chapter/stream/format and JSON reporting concepts (live master, unpinned). Installed tool help/execution and actual build provenance remain authoritative for exact options and redistribution.
- Original ACT handoff supplied as `markdown-handoff-prompt(2).md` in this session: complete requirements, register and amendments; the local HOME-PC copy has a longer reference-handoff filename and is untracked.
- Supplied `AI-WORKSPACE.md`, `Vibe-coding-chat-workflow.md`, `Useful-Repositories.md` and historical `ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md`: development/preservation context, subordinate to current explicit instructions and current source facts.
- `markdown-handoff-prompt(1).md` and `Verification-Gate-Claude-Code-Guidance-2026-11-04.md`: read as architectural references for the separate Vibe Coding Files project. Adopt applicable principles only. Its repository paths, historical snapshot name, TEST-PC exception and other-project implementation/merge permissions do not transfer to ACT.


---
