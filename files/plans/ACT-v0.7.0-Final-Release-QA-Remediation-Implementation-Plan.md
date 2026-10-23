# Audiobook Creation Tool — v0.7.0 Final Release QA Remediation Implementation Plan

**Status:** owner decisions resolved; executable plan for later, bounded Claude Code sessions. No application implementation, Git mutation, environment change, model acquisition or release was performed in this Work session.

**Planning date:** October 21, 2026 (America/Edmonton). **Revision 2 — finalized after source-grounded external-review reconciliation.** This supersedes the v0.6.7 remediation target; it does not revise historical publication records.

| Item | Baseline / intended outcome |
|---|---|
| Repository | https://github.com/elmatthe/audiobook-creation-tool |
| Inspected branch | `feature/0.6.7-speech-pipeline-and-layout` |
| Inspected and rechecked commit | `d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1` |
| Later implementation branch | `feature/0.7.0-release-remediation`, created from the refreshed inspected branch tip |
| Actual default branch | `master`, verified through repository metadata; never assume `main` |
| Current code/config identity | `0.6.6`; change to `0.7.0` only at the separately approved final-RC identity checkpoint |
| Intended release | v0.7.0 Windows; macOS artifact/support held pending native qualification |
| Plan location when supplied to Claude | `files/plans/ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md` |
| Evidence root, later implementation | `files/dev-work/act070-remediation/` (ignored; machine details and generated media remain here) |

## 1. Goal, authority and execution boundaries

A newcomer can launch ACT, deliberately choose optional voice models, and produce narration with consistent registry-driven filenames and no added closing pause. The six shipped Qwen3 clones require neither Whisper nor customer transcript approval. Display-label edits and row reordering cannot change voice/reference identity. Installation, repair and cancellation preserve user data and known-good environments.

The owner selected A for Questions 1–10 and 12–35, with an explicit config amendment to Q9, and **B for Q11** (include the reference-directory rename). The owner also explicitly changed the release target to v0.7.0 and required the exact previously approved transcript texts, including Male 4's corrected “Hello Arthur.” opening. Section 2 is the decision register.

Roles:

- Normal ChatGPT project chat: manage one checkpoint at a time, review pushed evidence, give concise agent prompts, and guide manual tests.
- Claude Code on the owner's machine: implement the authorized checkpoint, focused tests, permanent-doc updates and working-branch commits/pushes.
- Independent Codex CLI session: audit the final pushed implementation, test adversarial cases and report findings; do not silently co-implement.
- Owner: approve transcript extraction result, perform listening/physical-machine qualification, decide feasibility fallbacks and authorize RC, cleanup, integration and publication separately.

Apply the supplied `AI-WORKSPACE.md` and `Vibe-coding-chat-workflow.md`, then actual local rules if present. At the inspected remote tree, `AGENTS.md`, `AI-WORKSPACE.md`, `.claude/CLAUDE.md` and `.ai/BOOTSTRAP.md` are not tracked. The local ignored copies may exist: inspect them, do not reconstruct them from memory or add them for symmetry.

**Repository-specific documentation rule:** only `Briefing.md`, `Handoff.md`, `Decisions.md` and `Changelog.md`, with that exact casing, may exist in `md-instructions/`. Both `scripts/verify.py` and `files/tests/test_repository_contract.py` enforce this. Keep this plan under `files/plans/`; do not weaken the four-document contract. Resolve this specific project rule over the generic workflow's suggestion to add an instruction drop in `md-instructions/`.

This plan describes later authorized implementation. It is not authorization to run every phase at once. Each checkpoint ends with a report and normal-chat review. Routine working-branch checkpoint commits/pushes follow standing policy; merges/pushes to `master`, tags, publication, history rewrites and destructive cleanup remain separate approval gates.

### In scope

1. Correct final MP3 endings across Edge direct and folder/batch, Kokoro, Chatterbox, Qwen3 presets and clones.
2. Stable voice identity, editable ordered labels, one TTS filename policy, safe paths and existing collision planning.
3. Move the six tracked reference WAVs to `files/Cloned-Voice-Uploads/` without changing their basenames or bytes.
4. Curated, hash-bound bundled six-text manifest; ordinary-user zero-touch clones; config-gated maintainer tools.
5. Four first-run optional choices and an explicit, recoverable Install & Continue flow.
6. Bounded nested-Qwen3-environment feasibility, safe adoption only after proof and an owner decision checkpoint.
7. Packaging/config/docs alignment, non-TTS regression protection, independent verification, second-round manual qualification and exact final-RC evidence.

### Out of scope / deferred

New arbitrary customer voice profiles; replacing recordings or regenerating previews; Qwen3 performance/sampling experiments; retuning internal narration pauses; splitting the proven main dependency stack; upgrading model/dependency pins; a full main-environment transitive lock (AUD-010); Qwen3 on macOS; automatic cleanup/restoration; public-site/download-link changes before publication; merge/tag/release operations without separate approval.

## 2. Owner decision register

All original recommendations were Option A. “Selected” is the owner's actual answer, not an inferred default.

| Q | A recommendation | Selected requirement / amendment | Reason and implementation impact |
|---|---|---|---|
| 1 | No deliberate final pause; at most 300 ms natural/codec tail | A | Protect final sounds while removing multi-second gaps; decoded-audio and listening gates. |
| 2 | Preserve internal pacing | A | Change EOF behavior and proven end-only duplicate additions; no global pause redesign. |
| 3 | Root-cause fixes plus conservative safeguard and measured/listened acceptance | A | A preset-only change is insufficient; do not cut a fixed number of seconds. |
| 4 | `<source-stem>-<display_label>.mp3` | A | No extra backend/ID suffix; numbering only when needed for collisions. |
| 5 | Registry order and labels are cosmetic; IDs are durable | A | Unique nonempty labels; arbitrary 1..28 labels/reordering must preserve dispatch and assets. |
| 6 | Deterministic filename sanitation and existing collision planner | A | Preserve readable punctuation/Unicode where safe; handle sanitation collisions and case-insensitive paths. |
| 7 | Save/restore by stable backend/voice ID | A | Migrate only label-based state actually found; do not invent new selection persistence. |
| 8 | Publish six approved transcript texts as curated bundled data | A | Public texts authorized; private runtime approval history/settings are excluded. |
| 9 | Separate maintainer transcript/Whisper tools from normal setup | A, amended | A boolean `developer_mode` in `config.toml` enables manual maintainer options. Ship false. |
| 10 | Fail closed for missing/unexpected reference WAV | A | Block only affected clones with repair guidance; no stale transcript reuse. |
| 11 | Defer reference-directory rename | **B** | Owner requires `Chatterbox-Voice-Uploads` → `Cloned-Voice-Uploads` in v0.7.0; paths, allowlists, migration, docs and tests included. |
| 12 | No additional customer-uploaded voices | A | Keep the fixed six-slot product roster. |
| 13 | Read only six approved records, verify hashes, owner-review minimal manifest | A, clarified | Exact previous approved texts; Male 4 must include “Hello Arthur.”; no automatic re-drafting, rewriting or private-store dump. |
| 14 | Four independent first-run checkboxes | A | Kokoro, Chatterbox, CustomVoice, Base; share eligible engine/download bytes once. |
| 15 | Kokoro checked, other three unchecked | A | Visible choices and affirmative setup action record consent; no unattended model downloads. |
| 16 | Acquire only requested Qwen model plus shared engine | A | Other model is not a dependency; later installation reuses verified shared bytes. |
| 17 | Install & Continue after a missing-model Create action | A | Install on explicit consent, then resume the same validated intention exactly once. |
| 18 | Recoverable failure/cancel; preserve queue and resumable safe files | A | Base app remains usable; no output reservation for a declined/failed install. |
| 19 | Honest size, disk and verified hardware disclosure | A | Do not promise CPU speed or falsely label supported CPU operation impossible. |
| 20 | Freeze pending conversion; revalidate before one-time resume | A | No live-widget reread that changes inputs, settings or voice. |
| 21 | Investigate an independent Qwen venv under `.venv` | A | Candidate `.venv/engines/qwen3`; retain independent packages/process. |
| 22 | Create at final path, prove, retain legacy environment for rollback | A | No rename-and-assume migration; no unrequested legacy deletion; preserved owner environments excluded. |
| 23 | Mandatory bounded investigation; owner decides fallback | A | If nesting cannot be made reliable, stop with evidence before retaining legacy layout. |
| 24 | Clean standard-user Windows 10 qualification | A | Exact machine build/architecture/policy recorded; no Python/winget/FFmpeg prerequisites. |
| 25 | Clean GPU-less gate tests bootstrap and Edge/Kokoro, heavy engines on HOME-PC | A | Heavy-engine support/disclosure still checked; CPU full narration is not mandatory there. |
| 26 | Windows qualification separate; hold Mac artifact pending native proof | A | Keep Qwen3 Windows-only; no Windows-derived Mac PASS. |
| 27 | Six-hash authorization/provenance record before release | A | Record actual creation/source and third-party-performance facts; missing facts remain a release gate. |
| 28 | Qualification ZIP, then separate final identity/RC and artifact retest | A | Distinct artifact authorization; final exact ZIP audit is last, not inherited from an older ZIP. |
| 29 | Restore originals only after reviewed tests and separate cleanup approval | A | Exact preservation manifest and fresh-directory identity required. |
| 30 | Focused checkpoints, final Claude full gate, independent Codex, owner re-QA | A | Repeat checks when changes/failures justify them; do not use old counts as new proof. |
| 31 | Preserve six reference bytes/basenames, 28 previews and tuning | A | Only the approved reference directory moves; hash invariance is a gate. |
| 32 | Retain proven main package stack; choices govern models / Qwen runtime | A | Disclose base package downloads even when optional models are skipped; no slim-core redesign. |
| 33 | New later implementation branch from refreshed current feature tip | A | `feature/0.7.0-release-remediation`; preserve old branch, no rewriting/remote deletion. |
| 34 | Keep existing run folders, mirroring, per-source outputs and numbering | A | Naming changes do not flatten folders or merge sources into one audiobook. |
| 35 | Developer mode exposes tools but does not change default narration inputs | A | Bundled transcripts remain default; explicit hash-valid local override only in developer mode. |

**Additional owner decision D36:** release target is **v0.7.0**. Historical v0.6.7 plans/evidence retain their original identifiers. New current-state headings and plan/release work use v0.7.0. The current code identity does not change until Phase 11 authorization.

## 3. Preservation and data-handling contract

### Exact owner preservation record

HOME-PC repository root: derive it locally with `git rev-parse --show-toplevel`; record the absolute path only in ignored evidence. This downloadable revision is safe to place at its exact `files/plans/` path without embedding the owner's absolute username/path.

Manifest: `files/dev-work/manual-fresh-install/preservation-20261021-184021-592ae0be.json`  
Tag: `20261021-184021-592ae0be`

| Original relative path | Preserved relative path |
|---|---|
| `.venv` | `.venv.act67-preserved-20261021-184021-592ae0be` |
| `.venv-qwen3` | `.venv-qwen3.act67-preserved-20261021-184021-592ae0be` |
| `files/runtime-data` | `files/runtime-data.act67-preserved-20261021-184021-592ae0be` |

`files/bin` was absent at preservation and was not moved. Fresh setup has subsequently populated some original paths. Do not assume current absence/presence from the old manifest alone.

- No preserved path is a migration/install/repair target. Do not activate or run Python from preserved environments at their temporary paths.
- P00 may read the manifest and metadata. Only P03's controlled extraction may read the six original transcript records; it must not write the source store or dump its whole contents.
- Do not recursively hash multi-GB environments. Record manifest identity and selected metadata; hash the transcript file privately before/after extraction, six WAVs, and 28 previews. No raw private-store text in agent reads/context, console logs, diagnostic reports or event streams. The owner-only review artifact is the explicit private-file exception; after P03B approves the minimal public bundle scope, its six curated strings may appear in bundle diffs/tests, never unrelated local records.
- Do not print/copy unrelated settings, usernames or credentials into tracked project docs. This revision omits the local absolute root; the owner-supplied untracked plan is an expected P00A input and is staged only after P00B reviews it for private machine details. Keep exact owner-specific preservation details in ignored evidence and a brief tracked pointer.
- Before later tests, use the already audited test isolation in `files/tests/conftest.py`; disposable test roots and redirected logs/settings must be proved before any launcher/bootstrap import.
- Protect source books, original reference MP3s, six WAVs, 28 previews, model caches, old ZIPs, fresh qualification results and preservation manifests. No broad `git clean`, `reset --hard`, `restore`, recursive wildcard cleanup or cleanup based on guessed tags.
- The current `.gitignore` excludes ordinary environments/runtime-data but does not reliably cover renamed preserved directories. P00B adds anchored preserved-directory exclusions and proves them without reading their private contents. Explicit scoped staging is required regardless.

A deterministic local script may read six approved strings for an owner-reviewed private manifest under Q13; the agent itself must not read/echo the original store or private review text before the public bundle scope is approved. Deleting, restoring or replacing any owner preservation/fresh-test directory is not authorized by that choice.

## 4. Source audit: verified facts, reports and unresolved proof

### What was inspected

Revision-2 recheck: remote source tip remains `d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1`. GitHub compare reports `master` at `62b0c09543fc5e2a8e6eca18262816e244ca1006`, 56 commits ahead / 0 behind on the feature branch, and that same master SHA as merge base. A fast-forward is possible at this inspection only; recheck before integration. The inspected tree has no tracked `.github/` workflow entries; this plan's verification is local. No Git or application files were changed during this review.

GitHub read-only tools verified branch/ref/tree, repository default branch, the source/test files listed below, current Briefing/Decisions and the top current-state blocks of the large Handoff. Six local PNG screenshots were visually inspected. Supplied workflow, shared development rules, useful-repository index and historical Plan 02 scaffold were read.

The full remote tree has the four permanent documents and no tracked native-agent rule files. The historical scaffold is explicitly unapproved and names obsolete `scripts/Universal/` paths; it is context only. Selective official references were consulted; no external skill/tool installation was needed.

### Evidence classification

| Finding | Evidence status | Consequence |
|---|---|---|
| All four registry preset helpers default EOF pause to 3000 ms | Verified in `voice_registry.py` | Reset application EOF policy and defaults; audit callers, not just dropdown values. |
| Edge rich assembly appends last chapter pause and an end-of-book pause | Verified in `epub2tts_edge.py:read_book` | Last sentence/paragraph/chapter boundaries need explicit EOF treatment. |
| Kokoro/Chatterbox append a chunk gap after every rendered chunk, including last, then optional end zeros | Verified in both synth functions | Changing end=0 alone leaves final paragraph/chunk padding. |
| Qwen `assemble()` explicitly appends gap after last chunk and then end zeros | Verified | Preserve only between-chunk gaps; preserve reference pad separately. |
| Direct Edge and other routes have different output basename functions | Verified in GUI/planner and standalone batch helper | Unify at planned destination boundaries and public helper routes. |
| `reference_recording_filename()` derives path from Chatterbox display label | Verified | Stable asset mapping required for both Chatterbox and Qwen clones. |
| Qwen runtime duplicates labels in `Qwen3Voice.label` | Verified | Resolve cosmetic names via registry without circular imports; worker IDs remain stable. |
| First-run wizard currently has only Kokoro and Chatterbox choices | Verified in bootstrap | Add two independent Qwen model options through shared orchestration. |
| Qwen installer already plans model reuse, hashes, progress, cancellation and component selection | Verified | Reuse that machinery; avoid a second downloader. |
| Main requirements contain Kokoro and Chatterbox packages regardless of model checkbox | Verified | Q32 preserves this stack; make base package size clear. |
| Existing main `VenvReplacement.commit()` deletes the previous parent environment | Verified | Nested Qwen child can be discarded unless lifecycle is redesigned and tested. |
| Config accepts only documented typed section keys; no developer-mode key exists | Verified | Add schema/default/dataclass/validator plus tests; a TOML line alone will be ignored. |
| Current tests forbid tracked transcript text and match any archive “transcript” path | Verified | Supersede narrowly with curated-manifest allowlist tests; keep private-data leak negatives. |
| Current tests freeze 0.6.6 identity, label strings/order, timing and label-derived reference names | Verified | Change only superseded contracts with evidence; retain ID/hash/internals and historical behavior outside approved scope. |
| App currently stores no persistent voice selection by label | Verified in config and voice-label tests | Q7 is an invariant; no speculative settings migration/new remembering feature. |
| Six PNGs show mixed filenames, 8.483 s displayed duration/long quiet tail, 0/6 fresh clones, installed Qwen models | Visually verified | Do not mistake screenshots for audio measurements or real network acquisition logs. |
| Every Edge/Kokoro/Chatterbox ending is wrong | Owner manual report; code supports added-tail mechanism | Treat as FAIL until reproduced/fixed/measured/listened. |
| Earlier CLR audit: 808 passed/2 skipped; Claude full gate 10,440 passed/60 skipped | Supplied handoff report; current remote Handoff independently records Claude full-gate result | Accepted earlier scope only; no new test run performed here. |
| Fresh unseeded Qwen acquisition, clean Windows 10/11, native Mac and exact v0.7.0 RC | Not proved by this session | Explicit manual gates remain open. |
| Safe nested environment implementation | Proposal, not proved | Bounded feasibility + owner checkpoint; no promised nesting. |
| Exact six approved transcript contents | Not available in attachments or tracked source | Later read-only extraction + owner sign-off; do not invent text. |

### Runtime/test map (existing paths unless marked proposed)

| Area | Production / contract paths | Focused existing tests |
|---|---|---|
| Voice roster/timing | `scripts/tts/voice_registry.py` | `test_voice_labels.py`, `test_kokoro_voices.py` |
| Edge direct | `scripts/tts/epub2tts_edge/epub2tts_edge.py`, GUI `convert_with_edge_engine` | `test_edge_direct_pcm_assembly.py`, `test_tts_jobs.py` |
| Edge folder/batch and shipped sample helper | `scripts/tts/batch_convert.py`, GUI worker dispatch; `scripts/tts/generate_voice_samples.py` | `test_batch_convert_folders.py`, `test_tts_jobs.py` |
| Local synthesis | `kokoro_synth.py`, `chatterbox_synth.py`, `qwen3_synth.py` under `scripts/tts/` | `test_kokoro_timing_wiring.py`, `test_chatterbox_engine.py`, `test_chatterbox_integration.py`, `test_qwen3_synth.py` |
| Qwen worker/process/locks | `qwen3_runtime.py`, `qwen3_worker.py`, `qwen3_process.py` | `test_qwen3_runtime.py`, `test_qwen3_worker.py`, `test_qwen3_process.py`, `test_tts_worker_concurrency.py` |
| Installation/clone maintenance | `qwen3_setup.py`, `qwen3_install_ui.py`, `qwen3_clone_setup.py`, `qwen3_clone_setup_ui.py` | `test_qwen3_setup.py`, `test_qwen3_install_ui.py`, `test_qwen3_clone_setup.py`, `test_qwen3_gui.py` |
| Bootstrap/repair | `scripts/shared/bootstrap.py`, `bootstrap_host.ps1`; root `.bat` and `.command` launchers | `test_bootstrap_host.py`, `test_bootstrap_requirements_state.py`, `test_venv_recovery.py`, `test_kokoro_health.py` |
| Config / paths / cleanup | `scripts/shared/{config,paths,maintenance,cleanup_state,cleanup_worker}.py` | `test_config.py`, `test_settings_allowlist.py`, `test_maintenance.py`, `test_cleanup_state.py`, `test_cleanup_worker.py` |
| Imports/planning/job lifecycle | `scripts/shared/{importing,output_paths,job_control,job_ui}.py`; TTS `plan_destinations` and `run_job` | `test_output_paths.py`, `test_tts_importing.py`, `test_tts_jobs.py`, `test_tts_reporting_order.py` |
| Release / documentation | `scripts/shared/release.py`, `scripts/shared/version.py`, root config/README; four permanent docs | `test_release_packaging.py`, `test_qwen3_packaging.py`, `test_repository_contract.py`, `test_application_source_boundary.py` |
| Preview assets (development only) | `files/voice-previews/`; `files/dev-tools/voice_previews.py` | `test_voice_previews.py` |
| Non-TTS features | `scripts/mp3/`, `scripts/m4b/`, `scripts/artwork/`, `scripts/launcher.py` | `test_tool_output_integration.py`, launcher/cleanup/output suites and each tool's existing focused tests |

Test names in the right column are under `files/tests/`. Inspect exact current definitions before invoking selectors. Proposed modules/fixtures below do not exist at baseline.

### Dependency feasibility

| Package | Main `scripts/requirements.txt` | Isolated `scripts/qwen3-requirements.txt` |
|---|---|---|
| torch | 2.6.0 | 2.10.0+cu128 |
| transformers | 5.2.0 | 4.57.3 |
| numpy | 1.26.4 | 2.5.4 |
| safetensors | 0.5.3 | 0.8.0 |

The Qwen stack is hash-locked for Windows x64 / CPython 3.12; it is not a cross-platform lock. Keep its exact artifacts, worker-process isolation and environment scrubbing. A single shared site-packages environment cannot satisfy these pins. The main bootstrap prefers Python 3.12; do not raise it to 3.13+ or alter the proven `srsly==2.5.3`, `setuptools==80.9.0` and `edge-tts==7.3.1` pins.

Windows 10/11 x64 are qualification targets, not a newly proved support matrix. Exact minimum OS build/security-policy limits remain unverified until machine qualification. Qwen3 is Windows-only. macOS code remains present but v0.7.0 Mac distribution is held; the known `.command` Tcl-only/unbounded probe remains a recorded native-Mac issue, not a Windows-derived PASS.

## 5. Implementation contracts

These are the concrete design choices within the approved scope. If a contract cannot be implemented safely with the existing architecture, report evidence and request a decision; do not silently relax acceptance.

### 5.1 Final narration audio

**Product policy:** no intentional EOF pause. Preserve sentence/paragraph/chapter timing between actual speech segments. Every final narration MP3 must have 0–300 ms of trailing near-silence without cutting a phoneme, breath, reverb or transient.

1. Set application EOF preset/default values to zero across all four engines, GUI fallback and Edge CLI defaults. Remove last-chunk/last-paragraph/last-chapter-only gap additions at actual EOF. Keep pauses between non-final content identical.
2. The final segment means the last segment actually rendered, not the last requested index: handle blank/skipped chunks, empty documents, title-only and failed-final-chunk cases explicitly. A contentless/failed run must not publish a silent “success” MP3.
3. Include the module-level Edge batch constants (`CHUNK_PAUSE_MS = 50`, `END_RECORDING_SILENCE_MS = 3000`) and `merge_mp3s`, which do not read registry presets. Trace final sentence/intra, paragraph, chapter and EOF additions in Edge direct rather than treating the visually reported ~6 s as a measured exact value. Inventory the shipped `scripts/tts/generate_voice_samples.py` routes and reporting contract too: line 1064 records captured `end_pause` among other settings; this alone is not proof of a separate synthesis implementation. Any route that calls production converters inherits the fixed policy, and direct callers require explicit coverage.

   Apply one documented final-tail policy to the final assembled narration before its final encode, covering Edge direct, Edge folder/batch and all local engines. A small TTS-local helper such as proposed `scripts/tts/audio_tail.py` is appropriate; do not change generic MP3/M4B tools.
4. Trim only the terminal suffix; do not remove leading silence or internal quiet intervals. Do not use a fixed “delete N seconds,” whole-book reverse-in-memory filter, general silence compression, denoising, speed change or normalization.
5. Use final PCM already available where possible. For Edge routes that hold MP3 chunks, integrate with the existing decode/merge/final-encode boundary. Do not add an extra lossy encode solely for trimming. Preserve bitrate, sample rate/channels, metadata, cancellation and no-clobber publication.
6. The Qwen clone reference's 600 ms pad is conditioning on a work copy, not narration output. Keep it, its cache identity, `CLONE_GENERATION_REVISION = 1`, temperature 0.70 / sub-talker 0.80, other sampling values, seeds, speed and chunk text unchanged.
7. If low-level functions retain an explicit end-pause argument for compatibility/diagnostics, the production MP3 path must enforce zero intentional EOF pause. Document any retained internal assembly argument; do not let old defaults or CLI routes bypass the production policy.

**Measurement contract (proposed engineering specification, to calibrate in P01A):**

- Decode the finished MP3 with ACT's proven FFmpeg executable to PCM; record FFmpeg version, actual sample rate, channels, sample count, decoded duration and container duration. Duration properties or waveform pixels alone are insufficient.
- Evaluate all channels separately and use the latest detected activity across them; never downmix in a way that cancels a quiet channel. Start with 10 ms windows, RMS threshold -60 dBFS, with a peak activity guard at -60 dBFS. A window is potentially active if either measure reaches threshold. Preserve at least 150 ms after the last active window when an excessive suffix is shortened; do not pad an already shorter natural tail.
- Record sensitivity results at -70, -60 and -50 dBFS and a quiet-final-speech fixture. Differences greater than 100 ms between the conservative and nominal endpoint require inspection/listening, not automatic aggressive cropping. Synthetic low-amplitude final phonemes/transients must survive. Thresholds are measurement candidates, not a claim that amplitudes alone identify speech.
- Before finalizing production constants, prove them on synthetic PCM and real final-word endings. Choose the conservative endpoint when uncertain; if that cannot meet 300 ms safely, mark that case FAIL and investigate rather than declare success or cut speech.
- Re-decode the final MP3 after encoding. **Accept only measured trailing near-silence ≤0.300 s at the calibrated criterion AND owner listening PASS for the final sounds.** Keep encoder delay/padding facts in the report; a codec explanation is not an automatic waiver above 300 ms.
- Synthetic assembly proofs compare the exact retained PCM prefix and exact internal-gap sample counts. Real compressed outputs need endpoint/listening and appropriate signal alignment, not byte equality to an earlier lossy encode.
- Log only metrics and case IDs. Suggested record: source case/hash, backend/voice ID, route, commit, parameters, pre/post sample counts, endpoint at each threshold, trim samples, final decoded tail, output hash, listening verdict.
- Keep evidence in `files/dev-work/act070-remediation/audio/`. A proposed offline test module is `files/tests/test_tts_final_tail.py`; an optional developer measurement helper may live under `files/dev-tools/` and never ship.

FFmpeg's `silencedetect` can provide an independent diagnostic with an explicit threshold/duration. It does not replace the windowed PCM proof or listening. Verify actual installed-version options through its help; do not copy a filter chain that removes every silence in the book.

### 5.2 Voice identity, order, naming and destinations

- Treat `(backend, voice_id)` as durable identity. Reference ID, model key, preset speaker and recording SHA are independent metadata. Labels never select a model/reference asset.
- `VOICES` list order is dropdown order, even if entries move across engine groups. Cosmetic headings may mark contiguous group runs but cannot globally regroup/sort rows or become selectable voices.
- Validate labels as nonempty strings with no leading/trailing whitespace, unique under a documented Unicode-normalized comparison (use NFC for comparison, retain original display text). Reject invalid/ambiguous registry edits with an actionable diagnostic identifying stable IDs. Never silently take the first duplicate or switch backend. Do not hide valid unaffected tools or crash bootstrap.
- The shipped roster remains 28 stable identities (5 Edge, 9 Kokoro, 6 Chatterbox, 8 Qwen3). Current labels may remain the initial shipped values; owners can change them without editing identity tables.
- Replace `reference_recording_filename()` label derivation with explicit stable-ID→reference-ID→fixed-basename data. Preserve basenames `Chatterbox - Female 1.wav` through `Chatterbox - Male 4.wav` despite the directory becoming engine-neutral.
- Have Qwen/Chatterbox status, installer/progress/error text resolve visible voice labels through registry authority. Keep runtime model descriptions (“CustomVoice”, “Base”) and preset speaker tokens (“Aiden”, “Ryan”) independent. Prefer lazy lookup/property boundaries over imports that make the registry depend on engine modules.
- Freeze both stable identity and the chosen display label by value when accepting a narration intention. A retry uses the same frozen name/destination even if current registry labels change.
- Canonical base name is `<source-stem>-<frozen-display-label>.mp3`. Sanitize this as a filename component before destination planning: forbidden Windows characters, NUL/control characters, separators, trailing spaces/dots and device basenames must be handled. Preserve ordinary spaces, parentheses and valid Unicode. Source stem is retained as far as legal path limits permit.
- Reuse `shared.output_paths` sanitation and `DestinationPlanner` where sufficient; keep any extra policy TTS-local. Use its existing `stem-1.ext` numbering. A sanitation collision, case-only collision, duplicate imported occurrence or existing file gets a separately reserved path; no voice-ID suffix is added merely to avoid implementing collision planning.
- For path-length constraints, shorten deterministically only as needed, leaving room for collision suffix and extension. If no safe path fits, report before synthesis rather than write somewhere else.
- Direct files remain flat; one folder root mirrors relative parents; multiple roots retain collision-safe containers. PDF and TXT with the same stem, mixed direct/folder imports and intentional duplicates must stay distinct.
- Use exact planned destinations in every worker route, including standalone supported Edge batch helpers. Do not write an old engine-specific basename then rename into an unreserved destination.
- Preserve atomic publication, source/input-overwrite protections, retry IDs and already-successful outputs. Other tools' names and placement must not change.
- There is no existing label-based persistent voice setting to migrate at baseline. If refreshed local code adds one, migrate by unambiguous known mapping only; otherwise fall back with a message. Do not add selection persistence as an unrelated feature.

**Adversarial acceptance:** monkeypatch/inject all 28 labels to distinct `1`..`28` in a disposable in-memory registry (never edit the tracked registry or preview files to perform the stress test), reverse and interleave row order, and render through stubbed production route boundaries. Dropdown values follow that exact order; output labels match; original backend IDs, model speakers, six reference mappings, WAV hashes and transcript keys remain unchanged. Include blanks, duplicates, punctuation, Unicode, sanitized collisions and case-only names. Never edit real assets or regenerate previews for this test.

#### Preview metadata and developer tooling compatibility

The baseline gallery's `previews.json` and generated README are checked against registry labels and order by `test_voice_previews.py`; cosmetic registry edits need metadata synchronization, not new audio. P02 adds or adapts a **metadata-only** operation in `files/dev-tools/voice_previews.py`, explicitly incapable of synthesis/download. It updates only current display labels/order and derived presentation links/text; all 28 WAV bytes, file names, hashes, preview generation/transcript provenance, rights dispositions and sample/audio parameters remain unchanged. If existing sync() changes unrelated fields, narrow it or add a dedicated operation and guard its diff.

For a real intentional registry edit, run the documented metadata-only sync before the repository gate; app dispatch/assets remain independent of that step. For the `1..28`/order stress test, monkeypatch a disposable metadata copy too and assert it can be synchronized without modifying live tracked metadata. Do not weaken gallery consistency tests to conceal stale metadata.

P03 updates preview generation's transcript resolution to the same bundled-default/developer-explicit-override contract as runtime. Keep original preview generation history truthful; do not relabel historical generation as using a newer transcript. Run `test_voice_previews.py`, `test_qwen3_transcript_review.py` and `test_qwen3_calm_harness.py` in P02/P03 as applicable, with synthesis stubbed. No real preview generation is authorized.

### 5.3 Reference-directory migration and immutable transcript bundle

**Canonical v0.7.0 reference directory:** `files/Cloned-Voice-Uploads/`.

Move exactly the six tracked WAV paths through a scoped Git move during implementation; the content hashes and basenames remain unchanged. Do not move the entire old directory, which can contain ignored private MP3 sources or unrelated files. Update Chatterbox and Qwen lookup, release allowlist, ignore rules, tests, README and module docs together.

Fresh ZIPs contain exactly the six canonical paths. P00/P03A must first establish whether in-place overlay updating or a supported local restoration path actually requires a legacy lookup. Fresh ZIP extraction does not. Default to canonical-only resolution and no new compatibility branch when no supported path needs it. If evidence establishes a real supported path, document it and add only a temporary legacy-directory lookup for an exact expected basename and matching WAV hash when the canonical path is absent. If a canonical file exists but has the wrong hash, fail closed; do not conceal corruption by using a legacy copy. If both exist with conflicting content, report ambiguity; do not delete either. No customer migration walks or moves arbitrary old uploads.

Proposed runtime bundle: `scripts/tts/data/bundled_clone_transcripts.json`. It ships via the tracked `scripts/` tree and is the sole permitted published transcript artifact. Suggested explicit schema:

- Top level: `schema_version`, `bundle_revision`, and exactly six `entries`.
- Each entry: stable `reference_id`, corresponding `voice_id`, `wav_sha256`, exact `text`, and `text_sha256` over its UTF-8 bytes.
- No absolute path, username, private `approved_by`, local timestamps, settings, logs, external cache path or serialized user approval record.
- Version approval/provenance and the manifest's SHA belong in a concise permanent decision record; customer validity relies on shipped schema, exact roster, text digest and the registry's expected WAV hashes. Hashing is integrity binding, not a cryptographic publisher-signature claim.
- Reject duplicate IDs, extra/missing entries, malformed/wrong-type fields, blank/oversized text and bad text/WAV digests. Check the actual recording against its fixed expected hash before use. Preset voices need no transcript.

**Extraction checkpoint — no-echo procedure:**

1. Claude authors/reviews a deterministic local extraction helper using synthetic fixtures only. It reads the exact preservation-manifest-bound private store and six approved entries internally; it never shells out to cat/type/Get-Content, emits record repr/JSON or passes text through command arguments, tool output, AI reads, session logs or cloud recognition.
2. The helper checks approved is literally true, six expected recording hashes and existing text digests where present. It writes only the six final strings and minimal bundle fields to a new ignored private review file, with private filesystem access where supported, refusing overwrite/symlink/path escape. It preserves exact text, not normalize/rewrite/transcribe. Source store is read-only and fingerprinted before/after.
3. Console output is metadata only: stable IDs, lengths, approved booleans, WAV/text digests, artifact path/hash and Male 4 startswith("Hello Arthur.") boolean. Exceptions/logging must redact data. Claude must not open/read/grep the store or review artifact, even to “check” the helper's result. Agent tools and saved session context are logs too.
4. The owner opens the review file directly in their editor outside an AI read action, checks all six exact previous texts and the Male 4 opening, and approves the specific file hash/schema for publication. If the prefix check fails, the owner makes the exact correction in the private review workflow; Claude sees only updated metadata/hash and never guesses/prepends words.
5. P03C's deterministic helper generates the curated bundle from that exact approved artifact, refusing approval-hash mismatch and unrelated fields. Text is not reconstructed/typed by the model. Once the owner-approved six-field scope is the public artifact under Q8/Q13, its staged bundle diff may be read/reviewed normally; the original store, approval history and private review file remain private/ignored. Do not apply a blanket no-text-in-logs claim to deliberately published bundle content.
6. Tests use synthetic strings for private extraction fault cases and verify stdout/stderr/events contain no fixture secrets. Do not deliberately trigger tracebacks containing the actual private strings. The extraction helper is optional dev tooling, never a shipped user requirement.


Normal-mode resolution uses the verified bundle only, regardless of an existing private local store or `ACT_QWEN3_TRANSCRIPTS`. Do not let stale user state shadow shipped defaults. No recognizer acquisition, listen/check/approve steps or first-run writes of fake customer approvals are required.

**Config contract:** add `[development]` with `developer_mode = false` to `config.toml`; accept only a TOML boolean, default false on absent/invalid input with normal diagnostics. Add it to typed immutable effective config. It is not a `settings.json` overlay and the app does not rewrite the TOML. Document restart after editing. Ship false. Runtime accepts a locally enabled developer flag, but the repository verification/config contract must reject developer_mode=true in the candidate tracked root config **before a checkpoint commit**, and packaging rejects it too. Developers temporarily enabling it restore only their own exact flag change after testing; never git-restore someone else's config. Intentional true-config runtime tests use isolated fixture configs, not the tracked root.

When true, expose a clearly labeled “Developer tools → Reference transcripts” entry using existing local Whisper/manual-review tooling. Developer mode does not auto-download a recognizer, change voices, waive WAV/transcript hashes or start transcription. A deliberate source selection is required to use a reviewed local override; store that private selection outside the bundle, bind it to stable voice ID and hash, and ignore it when developer mode is false. Route explicit environment overrides through the same developer-only guard. Preserve save-failure recovery and local-only recognition. Keep arbitrary new voice profiles out of scope.

### 5.4 Optional setup and Install & Continue

**First-run execution home is settled:** the pre-venv wizard records the four explicit choices/consent and shows stdlib-only manifest-derived estimates. It must not import heavy TTS modules or call the Qwen installer from its host interpreter. After the main .venv is successfully built/proved, bootstrap launches its explicit console Python in CPython 3.12 to run a small shipped setup-worker entry point (proposed `scripts/tts/optional_setup_worker.py`) for selected acquisitions before final app launch. No deferred surprise install on a later launch.

Invoke the bridge with an argv list such as verified main Python plus `-m tts.optional_setup_worker`, an explicit cwd at the installation's `scripts/` directory and containment-checked request/result paths; do not rely on ambient PYTHONPATH or the user's current directory. The bridge uses a versioned, validated JSON request/progress/result protocol, only allowlisted components/options, no shell evaluation/arbitrary module path, and containment-checked temporary request/result files. It preserves the wizard's progress/cancel behavior and reuses the shared orchestration. Only start the child after base-package/Tk/SSL proof; detect unsupported Python/architecture, propagate cancellation to known children, bound probes, reap processes and keep base app launchable on optional failure. A consented operation interrupted by app exit requires a new visible resume/confirmation, never replay of stale consent.

Do not import the proposed heavy orchestration into bootstrap just to compute estimates: use a tiny stdlib-only shared planning data reader/protocol module if needed. qwen3_setup.console_python() and check_python() must see the verified **main** interpreter. The Qwen child's pyvenv.cfg home must point to the intended base Python installation, not to the parent .venv/Scripts; prove sys.base_prefix and child prefix/version directly. Do not assume that starting venv creation from an activated shell establishes the base correctly.

Keep one orchestration layer for both first-run setup and in-app installation; reuse existing downloaders, model manifests, progress/result sessions, containment and locks. A small proposed `scripts/tts/optional_setup.py` can normalize component plans and results without importing Tk/heavy engines on startup.

Four checkboxes, in this order:

| Choice | Default | Acquisition |
|---|---|---|
| Kokoro | Checked | Missing base model/language and requested roster voice assets needed for the selected support contract; disclose what remains per-voice on demand |
| Chatterbox | Unchecked | Verified required Turbo model assets; six WAV references are already bundled |
| Qwen3 CustomVoice | Unchecked | Shared isolated Qwen engine + CustomVoice model only |
| Qwen3 Cloned Voices / Base | Unchecked | Shared isolated Qwen engine + Base model only; verified bundled six transcripts/reference WAVs |

Q32 retains the main package requirements even if every model is skipped. Say that clearly: checkbox sizes are incremental model/runtime downloads; base application Python packages are separate and can be substantial. Do not describe this as an Edge-only slim package install.

- Planning/probing is read-only and network-free where current manifests permit it. Show base-package estimate, additional download bytes, approximate final disk usage, temporary headroom, eligible reuse, platform/hardware limitations and whether estimates are approximate.
- Count the Qwen environment once and shared model bytes once. Distinguish downloaded bytes, reused bytes, newly linked/copied disk bytes and temporary cache/headroom. Do not promise that network-byte sharing always eliminates installed disk copies.
- Existing indicative UI values are Kokoro ~300 MB, Chatterbox ~3.9 GB, Qwen model ~4.5 GB each / ~8.4 GB for both excluding engine; derive current presentation from actual manifests/plans, not hardcoded totals from screenshots. State GB/GiB units consistently.
- A visible checkbox state plus the affirmative setup action is consent for those listed acquisitions. Selecting a voice alone triggers no network. Base Python acquisition remains its own clear stage-0 user-scope consent.
- Availability is structured: ready; missing installable component; damaged/repairable component; unsupported platform; busy; bad/missing reference/bundle; unverified proof. Do not treat every unavailable voice as permission to download or as proof an environment is broken.
- If Create finds missing model/runtime assets, offer **Install & Continue** and **Cancel** with the incremental plan. Corruption requiring repair needs an explicit repair description/consent; unsupported platform or bad bundled reference needs an explanation/repair path, not a pointless model download.
- Preserve source queue, panel settings and existing destinations on decline/cancel/error. Retain only verified/safe resumable partial files and rehash before trusting them. No silent switch to Edge or a different voice.
- Long-running install/probe work runs off the Tk thread and reports through the existing UI pump/session. No second conflicting progress drain or blocking GUI wait.
- Serialize installation against inference and main-environment repair. Preserve the Global-only Qwen `MachineGuard` semantics, denied/busy/error distinction, per-installation locks and kernel crash release. Do not turn a model-load “busy” or timed-out proof into “healthy” or automatic rebuild.
- Model-specific first use (including a newly selected Kokoro voice, language/G2P asset or missing Chatterbox file) must go through the consented plan; do not hide an upstream library's lazy network download.
- For currently unpinned main-stack acquisition debt, show honest approximations; if required download content/size materially exceeds confirmed scope, request renewed consent. Do not silently upgrade pins to solve it.

**Pending conversion lifecycle:**

1. On Create, validate inputs/options and freeze an immutable pending intent using existing run snapshot structures where possible: occurrence IDs, source paths/root identities, stable voice ID/backend, display label, timing/bitrate/speech-preparation snapshot and output-base choice.
2. Do not reserve output directories or start a narration controller yet. Lock output-affecting controls/import changes while intent is pending; preserve the values if installation is cancelled.
3. Confirm install plan and associate a unique in-memory intent token. Repeated Create clicks and duplicate callbacks cannot mint a second install or conversion.
4. On installation success, verify actual readiness; revalidate frozen inputs still exist and that the original panel/app/intent is alive. If source metadata changed, ask for a fresh Create rather than narrate changed material silently.
5. Atomically consume the token once, reserve the run directory/destinations through existing planners and launch the captured run. Do not reread current widgets or global config. New collisions are planned at this point.
6. Cancellation, closing the panel/app, failed install or lost intent invalidates auto-resume. App restart never auto-narrates; no durable replay queue. Success can leave models installed but must not restart an abandoned conversion.
7. Failure during narration retains the existing exact-snapshot retry contract. Installation retry and narration retry are distinct states.

Required scenarios: all skipped; each of four selected alone; both Qwen selections; all four; second Qwen added later; model already healthy; missing voice-specific asset; offline; disk-full; bad hash; disconnect/resume; duplicate clicks; close during install; cancel around success callback; source changed; busy other app/copy; base app launch after optional failure.

### 5.5 Qwen nested-environment feasibility and lifecycle

Candidate layout is `.venv/engines/qwen3/`, an independent venv containing its own interpreter/site-packages. Models/runtime state remain under `files/runtime-data/`. Explicit interpreter paths and scrubbed subprocess environment retain process isolation.

Official Python guidance treats environments as non-portable: create at the destination; do not migrate by simply renaming `.venv-qwen3` into the nested path. Reuse only safe verified downloads or pip cache content with hashes, not copied site-packages.

Feasibility must prove:

- Distinct `sys.prefix` and package versions, `include-system-site-packages = false`, no inherited `PYTHONPATH`/`PYTHONHOME`/`VIRTUAL_ENV`/pip target overrides.
- Stable base-Python selection independent of the parent app's packages; missing/base-interpreter changes detected without claiming health.
- Specifically inspect/test `bootstrap._discard_venv_aside` as well as `VenvReplacement.commit()`, `_restore_venv` and interrupted recovery, and `qwen3_setup.safe_to_remove_environment` including ancestor links, stale identity and nested-target boundaries. Main `VenvReplacement` commit, rollback and crash recovery cannot delete, orphan or run a nested environment from an invalid temporary path.
- During a parent repair, a child may be held safely and restored to the **same final absolute path** before use, with journal/locks outside the replaceable parent; temporary holding is not a claim of relocatable execution. Alternatively recreate the child at its final path using a consented verified plan. Prove the chosen approach, including failure before/after child reattachment and interruption before commit. Do not delete an old parent backup that still holds the only valid child.
- Windows running-interpreter/file-lock failures are recoverable. Never force-stop unrelated Python or bypass ACL/antivirus policy to complete migration.
- Main repair on a standard-user account preserves models/settings/transcripts and cannot silently trigger multi-GB acquisition. A healthy Qwen engine is not recreated for an inconclusive probe.
- New installs use the approved layout; legacy installs are detected. If both old and new exist, validate identity and choose the approved canonical layout; do not guess or silently delete the legacy one.
- Runtime/install/inference locks live outside the parent where needed, have deterministic ordering, and avoid deadlock; test cross-copy and cross-session Qwen protection.
- Maintenance UI must accurately disclose whether “rebuild dependencies” includes Qwen packages. It must not delete a nested Qwen environment under a promise to remove only main-app packages. Update `maintenance.py`, `cleanup_state.py`, `cleanup_worker.py` and UI/tests as needed.
- Both environment layouts, backups, journals, preserved paths, models/caches and private records remain untracked/unpackaged. No symlink/junction escape or ancestor-link bypass.

First prove topology/lifecycle with tiny disposable environments and synthetic interruption fixtures. Real hash-locked Qwen install and a preset/clone run occur only on owner-approved fresh qualification paths. Do not use preserved environments as experimental inputs. Report evidence at the owner checkpoint. **If nesting is unsafe or disproportionately complex, stop for the owner's explicit retain-legacy decision; no automatic deferral is preauthorized.**

## 6. Phased implementation and checkpoints

Read this section together with the contracts above. Each sub-checkpoint is one bounded Claude session; stop after the assigned sub-checkpoint. No session is authorized to “finish the release” by inference.


### Execution protocol — applies to every checkpoint

This protocol and the exit table below are part of Section 6, not optional process advice. They close the execution gaps identified by the owner's external plan review. They do not authorize changes to HOME-PC from this Work chat.

#### Session entry and exit

- Read only this protocol, the assigned checkpoint/contracts, the decision rows it depends on, and the top current Handoff block first. Search older Handoff sections selectively; do not reload the entire large historical file or all 35 decisions on every session.
- Record actual shell tool/Claude version, repository root, branch, `git status --short`, `git log -1`/HEAD, expected previous reported SHA, and remote tracking. In Git Bash inspect `printenv VIRTUAL_ENV` (unset returns exit 1 normally); in PowerShell inspect `$env:VIRTUAL_ENV`. Never print the whole environment.
- P00A inventories an initially dirty tree read-only. The user-supplied plan at the exact files/plans path is expected untracked dirt; do not stage it then. This revision contains no absolute HOME-PC username/path. Unknown tracked edits, wrong branch/SHA, or new unexplained files block mutations; never reset/stash/restore/clean them automatically.
- From P00B onward, start from the last reviewed pushed checkpoint with clean tracked/staging state and no unexpected untracked files. A source-tip change or legitimate owner edit requires a documented reconciliation before implementing; it does not license discarding it. Known ignored evidence/preserved directories are not “dirt to clean.”
- An inherited active venv may be reported during P00A; it does not prevent read-only inspection. Before environment mutation/repair/restoration, require an actually clean launch context and no handles using targets. Simply unsetting VIRTUAL_ENV does not undo PATH activation or close handles. Routine focused tests still use an explicit known interpreter and isolated subprocess environment.
- At P00A check remote read access noninteractively with `git ls-remote origin <source-ref>`; this proves read access only, not push credentials. P00B checks write/auth readiness via a non-mutating dry-run push to the intended working branch when available. If Git Credential Manager opens a browser or signing needs owner interaction, stop at that handoff; never enter credentials, change remotes or bypass hooks/auth.
- Every mutating checkpoint ends with relevant checks green, allowed-xfail ledger exact, docs updated **before** its gate, scoped reviewed commit, pushed SHA, clean `git status --short`, upstream agreement and next checkpoint in Handoff. P00A/P03B/manual evidence-only stops are explicit exceptions: ignored evidence is produced, no source commit is invented. If an unexpected change appears, report the exception; never clean someone else's work to manufacture a clean exit.
- Resolve actual commit SHA after committing; tie test evidence to a fingerprint of tested source/test/config/doc inputs and then the resulting commit. A running full gate must see frozen tracked inputs: no concurrent edits, branch switches, model operations or second test suite. Logs/ignored evidence can be written. Do not mutate Handoff after the full gate just to insert its own commit SHA.
- No app implementation may proceed beyond an owner gate by interpreting silence as approval.

#### Shell and VS Code hygiene

Use `./.venv/Scripts/python.exe ...` from the repository root for native Windows agent commands: the forward-slash relative executable works in Git Bash and PowerShell. Do not paste PowerShell's `& .\\.venv\\Scripts\\python.exe` into Bash. If using native PowerShell, label shell-specific syntax explicitly; if using WSL/Linux, do not pretend a Linux Python test proves native Windows. Detect tools/version rather than assume Git Bash is the only shell supported by every Claude release.

Before P04/P10/P12 real environment operations, the owner may disable VS Code terminal autoactivation locally: `python.terminal.activateEnvironment = false`; if Python Environments settings supersede it, use `python-envs.terminal.autoActivationType = "off"`. Verify supported settings locally, reopen a fresh nonactivated terminal and restart Claude if it inherited activation. These are owner/workspace-local preferences, not a tracked .vscode addition or an automatic global settings change.

Run destructive-lifecycle simulations only on disposable repo-contained qualification copies that are **not** selected as the open VS Code workspace interpreter/test-discovery environment. The owner can close that workspace or point the interpreter elsewhere. Stop debuggers/test discovery and inspect known child processes before repair. Pylance or Python-extension handles are a possibility to diagnose, not grounds to kill all Python processes. If handles/policy prevent rename, stop/report and retry only after the owner resolves the specific use.

Smart App Control, antivirus, ACL or signature failures are stop-and-report conditions. Do not disable protection, add exclusions, elevate unnecessarily, substitute unqualified wheels or work around policy. Record exact component/error; preserve the qualified srsly pin.

#### Red tests across session boundaries

Prefer adding a regression and fixing its bounded code in the same reviewed checkpoint. P01A may hand off newly added, demonstrated failures for later routes using a narrow temporary marker:
`pytest.mark.xfail(strict=True, raises=AssertionError, reason="ACT070-P01A/<case> — Q1; remove in P01B or P01C")`.

Only exact **new** regression node IDs proved to fail on the old code for the intended assertion may enter this ledger. Use the expected exception type actually demonstrated; unexpected setup/import/error classes must fail, not be hidden. Tests execute (`run=True`); no file/module-wide markers, blanket xfails, run=False, broad-exception catches, old-test quarantine or weaker assertions.

Capture the original red output using those exact nodes with `--runxfail`; that reproduction is expected to exit nonzero and is recorded, never advertised as a passing gate. Commit the new tests with strict markers and an ignored evidence ledger of node ID, reason, old-code failure, fixing checkpoint and expiry. The next normal-chat report names the bounded debt explicitly.

P01B removes the markers for all fixed local-engine cases; only exact Edge cases due in P01C may remain. P01C removes every ACT070 temporary xfail. A strict XPASS is a failed checkpoint: remove the marker and prove the case passes normally. Existing tests invalidated by an approved behavior change are replaced atomically with the meaningful new contract in the fixing commit, never marked xfail simply to keep the branch green.

From the P01 full-phase exit onward, zero ACT070 temporary xfails are allowed. Pre-existing documented platform skips/xfails are inventoried separately and cannot expand unnoticed. P08/P09/P11 explicitly audit the ledger and marker inventory.

#### Durable full gates without duplicate 20-minute runs

The inspected check_pytest() captures pytest stdout and shows only its last line. Redirecting the outer verify command alone does **not** preserve live child diagnostics. Add a narrow developer verification-observability checkpoint P00C before P01A, retaining all existing gate meanings.

P00C adds an explicit `scripts/verify.py --evidence-dir <new-repo-contained-dir>` option. In evidence mode it:
- streams pytest stdout/stderr to a flushed `pytest.log` while retaining a bounded summary for its existing return contract;
- supplies pytest `-ra` (includes skips/xfails) and `--junitxml=<dir>/pytest.xml`, alongside the existing collection scope and no-failure/no-empty semantics;
- writes a flushed outer `verify.log` and atomically finalized `result.json` with each gate, native exit status, elapsed time, actual interpreter, tested-tree fingerprint and PASS/FAIL. A start record/incomplete marker exists until normal completion; missing/truncated JUnit or missing final result can never mean PASS;
- refuses existing evidence directories/unsafe paths, creates outputs only under files/dev-work/act070-remediation, keeps ordinary no-argument usage compatible, and preserves failure traceback/log details;
- does not import the app, download anything, run pytest twice, accept zero collected tests, swallow failure exits or broaden allowed skips.

Cover streaming, failure, empty collection, malformed args, interruption/incomplete status, collision and non-pytest gate results using existing repository-contract tests/mocked subprocess fixtures. Add a small proposed `files/tests/test_verify_evidence.py` only if current test modules cannot hold these meaningful cases. Inspect tests mocking subprocess.run and update their contract deliberately if implementation uses Popen. No app-runtime or dependency change is needed.

For each full gate, pick a new evidence directory containing phase, **starting** SHA and a unique run ID; do not reuse it. The starting SHA alone is insufficient when tested edits are uncommitted, hence the tree fingerprint. Agent command shape after P00C:
`./.venv/Scripts/python.exe -u scripts/verify.py --evidence-dir files/dev-work/act070-remediation/verify/<phase>-<starting-sha>-<unique-run>`.

Use Claude's supported background-task facility, e.g. `run_in_background: true`, with a verified budget of at least 60 minutes where that version/session imposes one. Do not append shell “&” as a replacement for the tool lifecycle or assume background tasks have no cap on every version. Record task ID, PID/process identity, evidence path and expected inputs. Wait for completion using the tool's task mechanism, inspect result/exit/JUnit/logs, and send concise progress updates. If background work is disabled or unavailable, have the owner run the exact long command in a separate clean terminal and return results; do not fake detachment or silently increase global settings.

A tool timeout/interruption is INCOMPLETE, not FAIL of product behavior and not PASS. Check whether the known process remains alive before starting anything else; never launch a duplicate full suite. Preserve partial diagnostics, end only the known run if needed, then rerun once the cause is fixed.

**Full gate schedule:** end of P01C, P02B, P03D, P04C if nesting is adopted, P06C and P07C; P08 requires a full gate on its final tested tree. Reuse the completed P07 gate at P08 only if its tested inputs/fingerprint and required evidence are unchanged; otherwise run once. P11's identity change requires a new final full gate. P00/P05 and edits within each sub-checkpoint use focused checks; no full gate after every edit. Final executable changes/failures reopen only relevant checks plus the required final gate. The repo has no tracked CI workflows at the inspected tree: every gate here is local and no GitHub green check substitutes for it.

#### Dependencies while topology awaits the owner

P04B's owner decision blocks P04C adoption and real topology-specific installation, not layout-neutral analysis. After P03, the normal chat may assign **P05A only** while waiting, provided it uses the runtime environment-path authority and does not install, migrate or choose a layout. No simultaneous editing sessions. P05B/P06 integration waits for the approved P04 outcome (nested proven/adopted, or explicit owner retention of legacy layout). P07 final packaging follows the chosen layout.

#### Sub-checkpoint exit table

All rows inherit session entry/clean scoped push rules above. “Green” means zero failures/errors/strict-XPASS in named relevant suites; table suites are basenames under files/tests. Every row writes `files/dev-work/act070-remediation/checkpoints/<ID>.md`; P00A instead uses its specified `00-baseline.md`, and private/artifact paths are additional evidence, not source files. Only P01A/B may carry ledgered temporary xfails. Suite selectors may be narrowed to affected tests during coding, but the row's entire listed relevant modules run before its final checkpoint.

| ID | Green checks / bounded remaining debt | Evidence and stop |
|---|---|---|
| P00A | Read-only Git/rules/path/asset/credential inventory; no test or clean-tree claim | 00-baseline.md is the P00A record; report expected untracked plan and existing dirt, no commit/push |
| P00B | test_repository_contract.py and relevant ignore checks; exact branch origin/plan/protection diff | P00B.md; clean scoped pushed planning checkpoint |
| P00C | Verification observability tests and existing repository-contract checks, synthetic subprocess outcomes | P00C.md with sample incomplete/failure/success logs; no real full suite required yet |
| P01A | New regressions execute; intended red proofs with --runxfail, normal focused run has only exact ledgered xfails | P01A.md + audio/red-ledger.json; commit new strict-xfail tests, no unexplained red branch |
| P01B | Local synth/timing/final-tail tests green; only P01C Edge nodes may remain xfail | P01B.md + PCM metrics; remove all fixed markers |
| P01C | Edge direct/batch, registry timing and all final-tail tests green; zero ACT070 xfails; full gate | P01C.md + full-gate evidence; owner representative listening checkpoint when authorized |
| P02A | test_voice_labels.py, relevant Qwen runtime/GUI and test_voice_previews.py green, 28-identity injection | P02A.md + stable-ID/permutation/metadata diff; no audio regeneration |
| P02B | test_tts_jobs.py, test_tts_output_names.py, batch/output integration/planner and preview tests green; full gate | P02B.md + naming/collision matrix |
| P03A | Reference mapping, release/Qwen packaging, voice labels and preview/reference checks green under old transcript behavior | P03A.md + six-path/hash manifest; no transcript publication yet |
| P03B | Metadata-only extraction/schema/hash checks; private store before/after identical | P03B.md contains no text; private review artifact + metadata digest; owner review STOP before staging text |
| P03C | test_bundled_clone_transcripts.py, Qwen runtime/GUI/clone loader and preview/review/calm suites green | P03C.md + owner-approved artifact/bundle digests; source scope approved before text diffs |
| P03D | Config/settings allowlist, developer UI/backend, P03C and packaging tests green; full gate | P03D.md + normal/developer mode matrix |
| P04A | test_venv_recovery.py + proposed environment-layout and relevant installer/cleanup tests green with disposable fixtures | P04A.md + interruption matrix; no topology flip |
| P04B | Authorized native nested-stack import/runtime/copy proof; hashes intact; policy/file-lock errors unresolved = BLOCKED | P04B.md + real evidence; owner topology decision STOP |
| P04C | Runtime/setup/process/venv recovery/cleanup/packaging tests green; full gate | P04C.md + approved topology/migration/rollback evidence; skipped only by explicit retain-legacy decision |
| P05A | Pure plan/readiness/protocol tests green; imports verified stdlib-only in pre-venv context | P05A.md + execution-home/lazy-asset/size inventory; no acquisition, topology-neutral |
| P05B | Optional setup, Qwen installer/process, health, consent/cancel/repair tests green | P05B.md + failure matrix and runtime bridge proof |
| P06A | Wizard fit/cancel/logging + component-plan/process-bridge tests green | P06A.md + Tk geometry approximation; owner display-scaling checklist remains pending |
| P06B | TTS jobs, proposed Install & Continue, snapshots/collision/concurrency tests green | P06B.md + exactly-once event/race traces |
| P06C | Entire affected P05/P06 UI/job/install/reporting suites green; full gate | P06C.md + owner demo result or explicit NOT RUN listening/UI status |
| P07A | Release/Qwen packaging, false developer flag, Windows platform-default and leak/no-clobber tests green | P07A.md + disposable archive member/negative controls, no qualification ZIP |
| P07B | Host/FFmpeg/launcher isolation/maintenance/non-TTS integration suites green | P07B.md + compatibility matrix; physical clean-PC tests still pending |
| P07C | Preview metadata check, immutable URL references, repository/config/docs/packaging tests green; full gate | P07C.md + docs/URL scope and final tree fingerprint |
| P08 | Final full-gate evidence, zero ACT070 xfails, marker/asset/private-data audit | P08.md + final pushed SHA; no duplicate full run on identical P07 inputs |
| P09 | Independent Codex findings closed against corrected SHA; necessary focused/negative controls | Codex report + P09.md; code verified, manual gates OPEN |
| P10A | Separate artifact authorization, exact ZIP/member/hash audit | P10A.md + unique artifact evidence; no fabricated source commit for ignored evidence |
| P10B | Owner roster/routes/endings/setup and selected layout demonstrations PASS or blocked | P10B.md + audio/UI matrix; record NOT RUN faithfully |
| P10C | Clean Windows, actual acquisition and provenance rows accepted; Mac HOLD | P10C.md + manual ledger; stop for final identity/RC authorization |
| P11 | Final identity full gate, Codex delta review, exact RC audit/retests and ancestry check | P11.md + frozen RC/hash; no automatic merge/tag/publication |
| P12 | Owner-approved exact dry-run restoration, target/process/path safeguards and post-restore fingerprints | P12.md; no cleanup without concrete approval |


### P00 — Baseline and protection

**P00A: read-only baseline (first session).** Entry: owner supplies this plan in a normal project chat; current local state is not assumed clean.

- Identify HOME-PC and actual local rules; read current docs selectively. Read Git state/remotes/log/branches and refresh remote refs under standing policy. Do not discard dirt, prune/delete local work, switch `master` or execute launchers.
- Confirm current source branch and compare against inspected SHA; document any newer commits and re-evaluate affected contracts before proceeding.
- Read the exact preservation manifest and confirm preserved paths exist; record fresh paths separately. Do not execute preserved interpreters. Verify six references and 28 previews against the baseline; keep private store fingerprints local.
- Record source file/entrypoint map, existing test isolation, EOF additions per route, naming and consent paths, environment repair/cleanup hazards and optional-package debt.
- Create only an ignored baseline report at `files/dev-work/act070-remediation/00-baseline.md`. No production/test/config/Git-tracked edits, model downloads or real synthesis.
- Exit: report branch/SHA, dirty-state boundaries, preservation status, asset manifest, test plan and exact next checkpoint. No “release ready” claim. Owner/normal-chat review is required before P00B.

**P00B: branch and preservation guards.** Entry: baseline reviewed with no unresolved branch/preservation ambiguity.

- Create `feature/0.7.0-release-remediation` from the refreshed source feature tip; if it already exists, compare and stop rather than overwrite/reset it.
- Put the plan under `files/plans/` with local absolute identity sanitized in the tracked copy. Keep this private downloaded original intact. Do not add an extra `md-instructions/` document.
- Add narrowly anchored ignore rules for both preserved venv names and preserved runtime-data, plus newly introduced build evidence/journals where appropriate. Prove `git check-ignore` on representative synthetic paths.
- Add a new current-state pointer in Handoff and append the approved v0.7.0 scope/supersession decision. Keep historical entries intact.
- Verify existing repository/ignore contract checks relevant to these changes; scoped diff/staging only. Exit: pushed planning/protection checkpoint, no app behavior change. Never stage actual preserved content.

**P00C: durable verification observability.** Entry: P00B planning/protection checkpoint reviewed. Implement only the developer verify evidence-mode contract above, with focused existing/new runner tests, zero app/runtime/pin changes. Exit: P00C row green, unique sample logs/JUnit/final/incomplete proofs, clean scoped commit/push; then P01A.

### P01 — Final audio endings

**P01A: reproduce and specify.** Entry: P00 safeguards complete.

- Add synthetic offline regression fixtures at production assembly boundaries for final chunk, final paragraph/chapter, skipped last chunk, quiet terminal speech and single/multiple chunks; record old-code failures before changing behavior.
- Measure route-specific sample accounting, including Edge direct vs batch. Actual owner MP3s are optional evidence if supplied; none were attached to this planning session.
- Calibrate the measurement/safeguard constants from Section 5.1; document exact test vectors and any uncertainty. No network or model acquisition without explicit runtime-test authorization.
- Exit: bounded root-cause/threshold report with demonstrated red proofs; persist only narrow strict-xfail new tests per the ledger, ordinary focused run green-with-declared-debt; no unrelated speech-preparation changes.

**P01B: local-engine policy.** Implement zero EOF defaults, between-rendered-chunks-only pauses and conservative terminal trimming for Kokoro/Chatterbox/Qwen. Preserve Qwen reference padding/sampling. Verify synthetic assembly, final export decoding, quiet sound preservation, bitrate/cancel paths and approved source-text goldens.

**P01C: Edge paths and cross-engine gate.** Fix Edge direct end-boundary stacking, folder/batch terminal padding and common final export policy. Update superseded timing assertions with exact sample expectations; retain internal pauses. Use existing direct PCM assembly and batch tests plus proposed final-tail tests.

**Tests:** `test_voice_labels.py`, `test_edge_direct_pcm_assembly.py`, `test_kokoro_timing_wiring.py`, `test_chatterbox_engine.py`, `test_chatterbox_integration.py`, `test_qwen3_synth.py`, `test_batch_convert_folders.py`, new `test_tts_final_tail.py` and relevant cancellation/export selectors.

**Exit/owner checkpoint:** all offline endpoint/internal-timing proofs PASS, protected hashes unchanged, no extra lossy export. When owner authorizes runtime samples, listen to representative Edge direct/folder, Kokoro, Chatterbox, Qwen preset and clone final words before building further audio changes. Final all-voice manual qualification still occurs in P10. If any final speech is clipped, stop and correct; do not offset it by adding an arbitrary long tail.

### P02 — Stable voice identity and uniform filenames

**P02A: identity and labels.** Add stable reference mapping/registry validation and derive cosmetic engine-status labels from registry. Add the guarded metadata-only preview sync and test it on copies; keep all 28 WAVs and historical generation data intact. Remove fixed engine-name assumptions in label handling. Implement disposable 28-label rename/permutation tests; retain stable roster identities and references.

**P02B: planned output naming.** Centralize TTS basename policy, freeze display label with run options, integrate direct/grouped/standalone routes with existing planners. Preserve retry destinations, run numbering, multiple-root containers and source protection.

**Tests:** `test_voice_labels.py`, `test_tts_jobs.py`, `test_tts_importing.py`, `test_batch_convert_folders.py`, `test_output_paths.py`, `test_tool_output_integration.py`, Qwen GUI/runtime and preview tests; proposed `test_tts_output_names.py`.

**Exit:** “1..28” and arbitrary ordering pass with unchanged dispatch/model/hash/transcript linkage; safe names and collisions pass; no non-TTS naming diff. Owner checkpoint: demonstrate the exact sample filename and registry editing behavior without editing real audio assets.

### P03 — Bundled clone assets, transcripts and developer mode

**P03A: move exactly six WAV paths and prepare extraction tooling.** Implement and test Section 5.3's no-echo extraction helper against synthetic records only, in an approved dev-only location; commit that code and tests now so P03B later executes it without tracked edits.  Update static identity/path mapping, canonical/legacy resolution, allowlists/ignore exceptions and tests. Move no private MP3s/extras; prove old/new reference content hashes and all preview assets identical. Update actual six new basenames in ignore exceptions; the baseline ignore exceptions still name older `Female-1.wav` forms and are stale.

**P03B: controlled transcript extraction — owner gate.** Execute Section 5.3's no-echo helper procedure; the owner alone reads the private artifact. Claude sees only metadata/digests, Male 4 prefix boolean and unchanged source-store fingerprint. Stop for owner approval of exact six text strings and publishable fields. Do not stage bundle text before that review.

**P03C: bundle loader and normal-mode zero-touch clones.** Generate only the reviewed curated bundle through the deterministic helper from its approved file hash; do not have the model type the texts. Adapt preview/transcript-review/calm maintainer tooling to the shared resolution/explicit-override rules. Implement strict validation, exact hash binding, normal-mode precedence and useful errors. Existing local stores remain untouched and unnecessary.

**P03D: typed developer mode and gated tools.** Add the boolean to config schema/default/effective config and documented root config. Hide recognizer/transcript approval entry points by default, gate backend maintainer actions as well as widgets, require explicit local override selection and preserve local save-error handling. Test restart/default/invalid values; ship mode false.

**Tests:** `test_config.py`, `test_settings_allowlist.py`, `test_qwen3_runtime.py`, `test_qwen3_clone_setup.py`, `test_qwen3_gui.py`, `test_qwen3_install_ui.py`, `test_voice_labels.py`, `test_release_packaging.py`, `test_qwen3_packaging.py`, `test_voice_previews.py`, `test_qwen3_transcript_review.py`, `test_qwen3_calm_harness.py` and preview hashes; proposed `test_bundled_clone_transcripts.py`.

**Exit:** isolated fresh runtime-data + Base ready + six bundled WAVs yields six ready clones without local approval/recognizer. Each changed WAV/bundle digest/missing entry fails closed. Developer mode false ignores ambient/local overrides. Exact manifest text and directory move approved; no private data staged.

### P04 — Nested Qwen environment feasibility and owner decision

**P04A: offline lifecycle prototype/proof.** In disposable repo-contained roots, prove independent prefixes, no package leakage, main replacement/rollback/crash recovery and cleanup semantics from Section 5.5. Use tiny venvs/stubs first; no production directory migration. If proof requires source changes, keep them narrow/tested and do not flip production canonical path yet.

**P04B: real isolated proof and decision.** After owner authorizes acquisitions/runtime tests, create the locked stack at its intended final nested test path. Prove imports, existing model reuse, preset and clone synthesis, standard-user/path-space behavior and no asset/private-state changes. Present cost, required lifecycle changes and result.

**Owner stop:** approve adoption if proof succeeds, or explicitly choose legacy layout if it fails. Record evidence and append rationale; a silent fallback is forbidden.

**P04C: production adoption/migration only after approval.** Update path authority, bootstrap/repair transactions, model installer, maintenance/cleanup, locks, diagnostics, ignore/packaging and tests. Create/verify canonical environment at final destination; retain legacy environment pending separate cleanup approval. Keep the exact owner's preserved paths excluded.

**Tests:** `test_qwen3_runtime.py`, `test_qwen3_setup.py`, `test_qwen3_process.py`, `test_venv_recovery.py`, `test_bootstrap_requirements_state.py`, `test_maintenance.py`, cleanup and packaging suites; proposed `test_qwen3_environment_layout.py`.

**Exit:** approved topology, documented migration/rollback and negative/interruption proofs; no shared incompatible packages, silent legacy deletion or misleading cleanup UI. If legacy retained by owner, test/document it consistently in all subsequent phases.

### P05 — Shared optional-install orchestration

**P05A:** implement/specify the settled stdlib pre-venv planning → verified-main-Python setup-worker bridge and its request/result/cancel contract, define component planning/readiness/result contracts, share existing Qwen plans/downloads, and inventory lazy Kokoro/Chatterbox assets. Include base-package size disclosure, temporary disk budget, shared bytes and supported hardware facts.

**P05B:** implement consented operation lifecycle, progress/cancel/resume, health/repair distinction and lock ordering. Failures leave base launch and intact models usable. Bound subprocesses/probes; keep uncertain health distinct from proven failure.

**Tests:** existing Qwen setup/install UI, Kokoro health/bootstrap and cancellation suites; proposed `test_optional_tts_setup.py`. Stub all external acquisition in routine tests. Cover every component alone/both/all/skipped and fault cases from Section 5.4.

**Exit:** GUI-independent orchestration with honest plans and exactly one terminal result; no network on plan/probe/voice selection; no recognizer dependency for customer clones; no duplicate Qwen download. Stop if a required lazy upstream download cannot be brought under consent.

### P06 — First-run wizard and Install & Continue UI

**P06A: wizard.** Add four choices/defaults and consolidated disclosure using P05. Keep setup/repair launch path, user-scope Python consent and FFmpeg fallback working; optional failure must offer launch with available features rather than fail the whole app. Fit 768 px-height windows, owner-tested Windows display scaling at 100/125/150/200% where available (automated Tk scaling approximations are labeled approximations, never native display-scale PASS); wrapped descriptions, visible buttons, keyboard focus and scroll if needed.

**P06B: pending run.** Integrate intent capture, install consent, control locking, revalidation, cancellation/close invalidation, exactly-once resume and delayed output reservation into TTS `run_job`. Reuse shared job/import snapshots and event pump, not an independent job framework.

**P06C: faults and usability.** Test offline, retry, insufficient disk, corruption/repair, all model combinations, cross-copy busy state, rapid repeated clicks and cancellation around success. Remove standard-user prompts requiring Python/CLI commands/manual transcription; use actionable in-app repair guidance.

**Tests:** `test_bootstrap_setup_cancel.py`, `test_bootstrap_setup_dialog_fit.py`, `test_bootstrap_setup_logging.py`, `test_qwen3_install_ui.py`, `test_tts_jobs.py`, `test_tts_worker_concurrency.py`, `test_tts_compact_ui.py`, `test_tts_reporting_order.py`; proposed `test_tts_install_continue.py`.

**Exit/owner checkpoint:** demonstrate four choices and skipped-model Create → consent → install → original conversion once. Decline/cancel leaves no new run directory and preserves queue; closing invalidates auto-resume. No Tk access from workers or stale callback launch.

### P07 — Packaging, Windows bootstrap and regression hardening

**P07A: archive contract.** Set current v0.7.0 product declaration/effective fallback platform list to `["Windows"]`; retain Mac code and known-platform parsing capability for future qualification, without claiming current supported distribution. Make ordinary packaging default to Windows only; explicit Mac production packaging refuses while the qualification hold is recorded. Existing synthetic Mac layout tests can still exercise the internal packager without producing a supported Mac artifact. Update superseded platform assertions deliberately. Update closed six-reference allowlist for new directory and narrowly allow the reviewed transcript bundle under `scripts/`. Add minimal release-builder options for explicit Windows-only selection and a new owner-selected output directory, retaining no-clobber behavior. No current archive creation in this implementation checkpoint except disposable test fixtures.

Keep member validation, source-commit binding, tracked/clean packaged paths and hard-link no-overwrite publication/rollback proofs. Reject developer_mode=true. Force-committed private models, both environment layouts, nested children, preserved paths, private transcript stores, developer tools, previews and extra WAV/MP3 files must remain excluded.

**P07B: installer/repair and other tools.** Prove stage-0 verified per-user Python without winget, bounded functional Tk/SSL, FFmpeg portable fallback and exact expected architecture in tests. Tighten only confirmed defects; no default system/global installs or security-policy bypass. Cover all six panels: TTS Audiobook, MP3 Tool, M4B Converter, M4B Maker, M4B Metadata Editor and Cover Image, plus launcher/preferences. There are five non-TTS tool panels, not six.

**P07C: permanent docs.** Add concise current v0.7.0 scope/state to Briefing/Handoff; append superseding Decisions for transcript publication, config mode, folder move, naming, EOF policy and chosen env topology. Keep old facts/history intact. Changelog describes unreleased v0.7.0 work without claiming publication. Explain base-package vs model downloads, first-run options, on-demand consent, local-only clones and Mac hold.

Update release instructions so `master` is the actual integration target. **Before any qualification/final RC, pin** the shipped root README gallery link and the developer preview tool's RAW_BASE to an existing immutable asset commit, initially `d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1`, after checking those 28 files exist at that ref. Sync only gallery metadata/link text if needed. Keep this immutable pin through integration; do not require a post-RC switch to `master`. If current metadata must be publicly browsable at another ref, push that metadata checkpoint first and pin its verified existing commit without a self-SHA-in-commit requirement. Audio hashes/basenames remain fixed.

**Tests:** `test_release_packaging.py`, `test_qwen3_packaging.py`, `test_repository_contract.py`, `test_application_source_boundary.py`, `test_ffmpeg_health.py`, `test_ffmpeg_portable.py`, `test_ffmpeg_runtime_trust.py`, `test_bootstrap_host.py`, `test_launcher_isolation.py`, cleanup/output/tool integration suites.

**Exit:** clean archive scope in synthetic fixture builds, no-clobber PASS, all intended behavior documented, no accidental private-data/preview inclusion, Mac release held, no actual version bump or final candidate built.

### P08 — Claude final verification checkpoint

Entry: P01–P07 complete, transcript and topology checkpoints resolved, focused checks green.

- Inspect staged/final diff against this plan, stable IDs/parameters and all 34 protected audio hashes. Verify untouched original private transcript store fingerprint using isolated local checks.
- Run affected regression groups and require a completed background evidence-mode full gate on the final tested input fingerprint (reuse P07 only if identical), using explicit main Python per the execution protocol. No bare `python` resolving to Store aliases; no foreground 20-minute run with lost pytest output.
- Record exact command, interpreter, platform, test counts, skips with reasons, warnings, exit code, elapsed time and commit/tree. Required checks cannot be weakened/skipped to claim PASS.
- Full verification may reveal superseded hardcoded contracts; amend only with this plan's explicit rationale and meaningful replacement assertions. Never blanket-delete “old” tests.
- Run launcher tests only after isolation is proved; no production logs/settings/model downloads. Execute real synthesis solely where already authorized and keep generated audio/evidence ignored.
- Update Handoff concisely; commit/push scoped verified checkpoint; resolve final SHA after commit. Do not claim a commit contains its own SHA.
- Exit report: implementation complete for audit, exact branch/SHA and evidence index; manual gates still OPEN. A change after this gate requires relevant checks and a new full gate if it changes executable final-tree behavior or identity.

### P09 — Independent Codex audit and closure

Entry: final Claude SHA pushed and full-gate evidence available. Use a fresh independent Codex context with this plan and actual branch.

Audit must cover Section 8 in full, reproduce meaningful negative controls and verify the executable tree, not just Claude's narrative. Codex writes `files/dev-work/act070-remediation/codex/ACT-v0.7.0-Independent-Verification.md` with severities, exact paths, reproduction, test evidence, protected-asset status, plan deviations and manual-gate status. Do not dump private transcript records.

Codex reports findings; Claude resolves them in bounded checkpoints. Re-run affected checks and final verification as justified, push and have Codex close findings against the corrected SHA. No agent self-approves a manual/release gate. Exit: no unresolved release-blocking code/data-safety findings, exact audited SHA, owner manual testing pending.

### P10 — Owner second-round manual qualification

**P10A: qualification artifact authorization.** Only now request authorization to build a Windows qualification ZIP from the audited clean packaged tree into a unique new directory such as `dist/act070-qualification/<short-SHA>/`. Retain current 0.6.6 application identity until P11; label the directory/report “v0.7.0 development qualification, identity 0.6.6” so it cannot be confused with a public release.

Use real packager with P07's output/platform options, no replacement mode. Record commit, archive hash, member manifest, exact six WAV hashes, six-text bundle hash/schema, developer mode false and exclusions. Extract to a new owner-approved repo-contained qualification location; do not overwrite old ZIPs or the daily installation. Artifact-only tests in disposable fixtures were permitted earlier; this real owner qualification artifact needs this distinct approval.

**P10B: HOME-PC audio/setup.** Owner uses the exact extracted artifact, tests all 28 voices, filenames and final words; direct/folder routes; bundled clones; first-run/skip/on-demand flows and heavy-engine cancellation. Section 9 gives the checklist. Keep test media, metrics and output hashes local.

**P10C: clean Windows + unseeded + provenance.** Perform real standard-user Windows 10 no-Python/no-winget/no-FFmpeg bootstrap, Windows 11 coverage as defined in Section 9, actual Qwen model acquisition provenance and six-hash recording declaration. Screenshots alone cannot close acquisition.

Fix failures through Claude, targeted checks and Codex review; if source changes, issue a newly hashed qualification ZIP with fresh authorization and repeat affected tests. Unaffected evidence can carry forward only with explicit component/commit mapping. Do not label an older artifact as the new one.

**Exit:** all Windows release-blocking manual rows PASS with evidence; Mac explicitly held; missing coverage/rights/acquisition remains OPEN, not inferred PASS. Owner accepts results before P11. Restoring original environments stays separately gated and may wait until final-RC testing is finished.

### P11 — Final identity, exact RC and release decision (separately authorized)

Entry: code audit closed and P10 manual qualification accepted. Ask separate authorization for the concrete identity/RC action.

1. Change code identity to 0.7.0, matching `scripts/shared/version.py`, `config.toml`, identity assertions and current unreleased release docs. Keep historical v0.6.6 records and existing public downloads intact. No tag/merge/publication.
2. Verify the exact identity diff; run focused config/repository/release checks and the full gate once for the final identity tree. Codex reviews the final delta and records the exact final commit. Any non-identity behavior change reopens affected P09/P10 gates.
3. Build the Windows final RC only, using the clean final commit, into a new explicit destination. Existing ZIPs must cause refusal, never overwrite. Record SHA-256, size, source commit, ordered members, reference and bundle hashes, launcher/config/version bytes and no-private-content audit.
4. Re-extract this exact RC and test first/subsequent launch, version display, basic tool output, filename/EOF policy and a bundled clone. Repeat the clean Windows 10 bootstrap from the final artifact and Windows 11 artifact checks; broad prior listening can carry only if all relevant executable/audio inputs match except verified identity metadata. Record which evidence was repeated vs carried.
5. Freeze this exact archive hash as the release candidate. Any archive rebuild invalidates the hash-specific verdict and requires contents/extraction checks again. The final exact artifact audit/retest is the last qualification gate.
6. Re-fetch and recheck default-branch ancestry immediately before integration approval. Present release readiness, exact audited RC commit/hash, provenance/qualification and Mac hold; retain immutable preview URLs. Then request explicit owner decisions for **fast-forward-only** integration into `master`, tag and publication. These are not granted by approving this plan or the RC.
7. When separately authorized, integrate with `git merge --ff-only <exact-audited-RC-SHA>` on the clean refreshed default branch, then verify local/remote master equals that exact commit after the approved push. If fast-forward is no longer possible, stop; do not create a merge commit, rebase, force or rebuild silently. An owner-selected new integration strategy requires renewed audit/artifact qualification. No packaged metadata/link edit is needed merely for fast-forward integration. If any separately authorized integration/link change does alter packaged content, rerun relevant checks and build a new uniquely identified final RC; repeat its artifact checks before publication. Never publish a merged/stable-link build under a previously audited different hash.

**Exit:** exact Windows RC qualified or explicit blocked status. Publication remains unperformed until separately authorized. Mac package is not published as v0.7.0 supported software without native qualification and a separate decision.

### P12 — Optional guarded restoration of original HOME-PC state

Entry: owner reports manual testing is finished, results/evidence reviewed, no qualification process is running, and separately approves restoration.

Prepare a dry-run, manifest-specific script and a readable exact path/action preview first. Verify resolved repository identity; exact manifest/tag; originals vs fresh-created paths; no links/junctions/ancestor escape; inactive `VIRTUAL_ENV`; no ACT/installer/worker process using target paths; all preserved sources present; fresh evidence and needed settings/outputs accounted for.

Only after concrete approval may the script isolate/remove identified fresh directories and restore the three preserved originals to their original absolute paths. Prefer reversible quarantine when practical; any actual deletion requires an explicit reviewed list. Treat newly nested Qwen state inside fresh `.venv` as fresh only after positive identity checks. `files/bin` was not preserved: handle any new one explicitly, never invent a preserved counterpart.

Stop on mismatch, missing path, occupied original, active process, ambiguous data or failed move. Never guess a similar preservation name. Restore at the original paths before probing venv health; then verify settings/transcript fingerprints and six-clone approvals without printing private text. New source expects the approved canonical layout/bundle; validate any legacy-layout compatibility and do not silently migrate/reinstall during restoration. Keep old backup/qualification ZIPs and manifests. This is restoration, not a cleanup permission for models, recordings, previews or all “unused” files.

## 7. Regression matrix and practical test execution

Routine tests must be offline/deterministic and run in isolated roots. New test names below are proposed targets, not claims of existing coverage. Use the existing fixture/assertion style; no new test framework or provider.

| Contract | Required cases / proof | Existing suites to extend / proposed coverage |
|---|---|---|
| EOF policy | One/many chunks; final blank/skipped chunk; title-only; empty/error; exact internal pauses; final no deliberate gap | Existing Edge PCM/local timing/synth suites + proposed `test_tts_final_tail.py` |
| Audio protection | Quiet final fricative, breath, decay, short transient, stereo one-channel tail, internal silence, codec padding | Synthetic PCM prefix equality; decoded final MP3 metrics; owner listening |
| Route completeness | Edge direct, Edge folder/batch constants/helper, shipped sample-helper callers, Kokoro, Chatterbox, Qwen preset/clone; PDF/TXT/mixed imports | Existing TTS jobs/batch/synth integration + route table assertions |
| Identity independence | All 28 labels `1..28`; reverse/interleaved order; renamed labels omit engine tokens | Voice-label/runtime/GUI tests; frozen IDs and reference hashes |
| Invalid registry | Empty/whitespace label; duplicate/NFC-equivalent label; unknown ID; duplicate stable key | Proposed registry validation tests; actionable refusal, no silent voice selection |
| Filename sanitation | Slashes, colon, quotes, controls, trailing dots/spaces, device names, emoji/accents, path length | Existing output planner + TTS-local basename tests |
| Collision safety | Same stem PDF/TXT; direct+folder; multiple roots; case-only; sanitation collision; duplicate occurrences; file appears during install | Existing TTS jobs/output paths; numbered destinations, no overwrite |
| Retry | Current label/widget/config changes after original run; one duplicate occurrence fails; earlier success preserved | Existing exact-snapshot/retry tests |
| Reference move | Exactly six new canonical members; unchanged basenames and WAV SHA; no private extras moved | Release/voice-label/Chatterbox/Qwen tests |
| Reference compatibility if evidenced | Canonical-only by default; only if supported overlay/restoration path needs it: new absent+valid old, canonical corrupt, both conflicting, links/junctions | Prove need first; fail closed/explicit diagnostic, no speculative fallback |
| Bundle validity | Exactly six IDs; missing/extra/duplicate entries; bad schema/type/text/WAV/text-hash | Proposed bundled transcript suite |
| Zero-touch clone | Fresh empty runtime-data; no local store; no recognizer; Base installed | All six available without write/approval/download; extraction-artifact manual proof |
| Private source isolation | Normal mode with stale local store and ambient env override; malformed local JSON | Bundle remains authority; no private file read/use as normal default |
| Developer mode | Absent/false/true/string/integer/broken TOML; hidden UI and guarded actions; explicit source override | Config and clone UI/backend tests; invalid defaults false |
| Private-store preservation | Synthetic extraction fault proofs; real source unchanged; no raw private text in AI reads or stdout/stderr/events | Read-only checksum check; minimal reviewed export only |
| Wizard choices | All skipped; each alone; both Qwen; all; already installed components; default states | Bootstrap UI fit/cancel/logging and optional setup tests |
| Download consent | Probe/select voice no network; listed install only; model/language lazy assets; unknown-size change | Fake opener/network tripwire, no unconsented requests |
| Download resilience | No disk; offline; disconnect; bad hash; partial; valid reuse; cancelled; retry | Existing downloader tests + orchestration result paths |
| Shared download accounting | Qwen engine once; common bytes once; network vs disk/copy costs | Existing plan tests + four-component total assertions |
| Auto-resume | One success callback; duplicates; repeated Create; old intent success; cancel/close near success | New pending-intent tests; exactly one narration start |
| Intent integrity | Input deleted/changed; edits blocked; output collision created during installation; captured speech config | No output reservation before readiness; safe refusal/replan on captured values |
| Health semantics | Healthy/broken/unverified, busy/denied/failure, missing reference vs model | CLR regression suites remain meaningful; no unknown→healthy or auto-rebuild |
| Nested isolation | Independent prefixes/pins, system site-packages false, contaminated env, link ancestor | Proposed layout tests + real Windows proof |
| Parent replacement | Commit/rollback at each step; interrupted between detach/attach/commit; running Windows handle | Venv recovery + nested-specific tests; preserve only valid child |
| Legacy migration | Old only; new only; both; corrupted new; insufficient disk; interrupted new creation | No old deletion; no site-packages move; consented recovery |
| Cleanup maintenance | Parent deletion consequence accurate; nested/runtime/user state boundaries; stale journal | Existing maintenance/cleanup suites + nested fixtures |
| Packaging allowlist | Curated bundle allowed; private transcripts/config/settings/logs/models force-committed remain excluded | Narrow exception replaces blanket transcript ban; planted leak negatives |
| Archive publication | Both destination preflight; existing target; hard-link failure; staging cleanup; member/CRC/source binding | Existing no-clobber tests retained; Windows-only/new-output-directory cases added |
| Version/developer flags | 0.6.6 until authorized; final 0.7.0 consistency; developer true rejected for customer builds | Repository/config/release gate |
| Non-TTS behavior | Same output names, import/retry/cancel/safety for five other tools; launcher/preferences | Existing tool, output, import/job and cleanup suites |
| Test containment | Launcher tests alone/full; output/log/settings redirection before import; evidence-mode verification interruption/logging | `conftest.py`, launcher isolation tests; disposable clone proof |

### Focused commands

For Claude's native Windows Bash tool use forward-slash executable paths from the repository root; the same `./.venv/Scripts/python.exe` path works in PowerShell. Owner-only PowerShell instructions must be labeled separately. These are examples for assigned phases, not a command block to run every session. All referenced existing test paths were found at the inspected commit; proposed files are added by their phases.

- P01: `./.venv/Scripts/python.exe -m pytest files/tests/test_edge_direct_pcm_assembly.py files/tests/test_kokoro_timing_wiring.py files/tests/test_qwen3_synth.py files/tests/test_tts_final_tail.py -q`; add relevant Chatterbox and batch selectors.
- P02: `./.venv/Scripts/python.exe -m pytest files/tests/test_voice_labels.py files/tests/test_tts_jobs.py files/tests/test_tts_output_names.py -q`.
- P03: `./.venv/Scripts/python.exe -m pytest files/tests/test_config.py files/tests/test_qwen3_runtime.py files/tests/test_qwen3_clone_setup.py files/tests/test_bundled_clone_transcripts.py -q`.
- P04: `./.venv/Scripts/python.exe -m pytest files/tests/test_venv_recovery.py files/tests/test_qwen3_environment_layout.py files/tests/test_maintenance.py files/tests/test_cleanup_worker.py -q`.
- P05/P06: use relevant Qwen setup, bootstrap cancel/fit, TTS jobs, `test_optional_tts_setup.py` and `test_tts_install_continue.py`.
- P07: `./.venv/Scripts/python.exe -m pytest files/tests/test_release_packaging.py files/tests/test_qwen3_packaging.py files/tests/test_repository_contract.py files/tests/test_launcher_isolation.py -q`.
- Full-phase exits, P08 and final identity checkpoint: use the background evidence-mode command in the execution protocol, including its unique `--evidence-dir`; wait for final status and inspect logs/JUnit. The ordinary `./.venv/Scripts/python.exe scripts/verify.py` entry remains supported but is not the unattended long-run recipe.

Do not run launcher tests against owner runtime paths until the isolation tripwire is proved. Do not reactivate a preserved interpreter to run these commands. If the fresh main environment is unavailable, report the prerequisite instead of installing anything by assumption.

### Updating old assertions without weakening coverage

The new approved behavior supersedes specific old tests: positive EOF-default/gap expectations, fixed label spelling/order as an identity requirement, filename-from-display-label reference logic, consumer transcript requirement, total ban on transcript bundle paths, old reference-directory paths and final version identity. For each replacement, record the old contract and Q number, add the new invariant and a negative control demonstrating that wrong code fails. Retain private-store exclusion, exact WAV hashes, stable engine IDs, source-text goldens, worker parameters, no-clobber, Global mutex and tri-state health protection.

Full-gate counts will change. A lower/higher count alone is not a verdict; explain removed/replaced parameterizations and skips. No snapshot/golden regeneration that conceals changed speech text or tuning. Temporary red tests follow the execution protocol's exact-node strict-xfail ledger, with zero ACT070 markers after P01C and in final verification.

## 8. Independent Codex verification brief

This is a fresh verifier task, not a claim Codex has already run on v0.7.0.

1. Refresh actual branch/SHA and compare with the complete approved plan and source baseline. Inspect diffs directly; verify Claude's reported test commands/results belong to the executable audited tree.
2. Independently trace every narration/export route and EOF addition, including last paragraph/chapter and skipped final chunks. Reproduce at least one old-code failure or mutation-equivalent negative for end gaps and a clipping guard. Inspect final PCM/MP3 evidence and its limits.
3. Perform the 28-label rename/reorder adversarial check and sanitation/collision cases. Confirm no cosmetic label determines references, model speaker, persisted identity or worker dispatch; retry destinations remain frozen.
4. Confirm exactly six original WAV hashes and all 28 preview WAV bytes are preserved; metadata-only label/order/link synchronization does not change audio hashes or historical generation records. Only approved reference paths moved; private MP3s/records did not move or leak.
5. Verify helper-produced artifact/bundle digests and the owner-recorded reviewed scope; read only the approved public bundle, not the private source/review file. Verify the six-string bundle and hashes, including Male 4. Test altered WAV, altered bundle, missing entry, stale private store and ambient override in normal mode.
6. Audit config type/default/precedence and developer-tool backend guards. Developer mode must not auto-transcribe/download or bypass provenance/hash checks. Customer build config must be false.
7. Exercise four-choice consent, incremental plans, failed install, missing lazy assets, disk/hash/offline faults and source-queue preservation. Inspect callbacks/races: duplicate success, cancelled/closed panel, process crash, changed source and no early output reservation.
8. Audit chosen environment topology, dependency pins, parent repair/recovery and maintenance semantics. If nested, test child loss on parent commit/rollback and path/lock escapes. Verify no preserved owner directory is a code path target.
9. Inspect real release-builder outputs in disposable test roots, narrow bundle exception and planted private-data negatives. Retain member validation and fail-if-exists behavior. Test platform/output options and developer-mode rejection.
10. Recheck CLR-001–004 invariants: unverified Kokoro health is not success/failure; Global-only Qwen exclusion with correct errors; functional Tk proof bounded and child reaped; logs/settings isolated before launcher import.
11. Review non-TTS diffs, speech goldens, inference settings, dependency changes, URLs/docs/version timing and supported-platform claims. No reference/model license inferred from another license; unresolved provenance stays owner-gated.
12. Run independent focused tests/negative controls rather than rerun the entire full gate by habit. Verify Claude's full gate; run another full gate only if evidence/tree changes or findings justify it. Native Windows/Tk/kernel proofs cannot be claimed from mocked/Linux execution.
13. Report every issue with severity, exact file/function, reproduction and acceptance impact. Separate code PASS from physical manual/rights/acquisition/RC status. Required finding closure needs the corrected pushed SHA and new evidence.

Codex may write its local verification report and test in disposable roots. Any production fix should return to Claude under a bounded prompt. No merge/tag/release, cleanup of preserved state or new model downloads without the applicable authorization.

## 9. Second-round manual qualification checklist

Use the exact P10 ZIP, then perform final artifact-specific repeats at P11. This Work session ran none of these tests. Record actual machine/environment facts, not inferred memories.

### Evidence sheet

Each test row records: gate ID, source commit, artifact filename/SHA, extraction root (local report only), OS/build/architecture, account privilege, security policy, Python/FFmpeg discovery source, component states/cache provenance, steps, actual result, log/media paths, expected result, owner verdict/date and unresolved issue.

No copyrighted input books or full private settings/log dumps are committed. Synthetic short texts can be tracked as test fixtures under an approved non-private fixture location; generated media stays ignored.

### HOME-PC all-voice and naming gate

- All 28 voices: Edge 5, Kokoro 9, Chatterbox 6, Qwen3 8. Run the same short difficult narration ending with quiet/fricative/breath-sensitive words; retain full final words, not just total duration. Each final decoded MP3 tail meets ≤300 ms and owner listening PASS.
- Each engine family/preset/clone: a multi-paragraph/multi-chunk case preserves internal pacing. Include Edge direct and folder/batch; PDF and TXT; one folder and multiple roots; same-stem inputs and intentional duplicates.
- At least one long Qwen clone and a representative long Edge/local case verify no new end assembly, omission or late cancellation issue. No speed/sampler tuning.
- Every output uses the exact selected display label after permitted sanitation and only collision numbering. Run folder numbers, mirrored paths and other tools' names remain correct.
- In a disposable test checkout/config injection only, demonstrate labels `1..28` and reordered rows, correct dropdown order, stable voices/assets and expected output filenames. Restore the test code copy only, never production audio assets.
- Test normal mode with fresh runtime-data and Base installed: all six clones work immediately without Whisper, typing, listening-checkbox or customer approval. Missing/corrupt reference yields a clear affected-voice error.
- Test `developer_mode = true` in an isolated local config: developer tools appear, no automatic transcript-source switch/download, explicit manual action works, saving errors retain edits. Turn it false/restart: customer flow is clean; bundled transcripts regain authority.

### First-run and on-demand gate

- Review all four choices and defaults before downloads; base-package cost and GPU/CPU caveats are visible.
- Exercise all skipped and each optional component alone via controlled fresh states/disposable copies; never delete preserved/daily environments to simulate absence.
- Add second Qwen model later; verify requested model only, shared engine retained, reused files actually hash-valid, totals honest.
- Import books, choose an omitted voice, click Create, review Install & Continue plan, consent, observe progress and exactly one resumed original conversion.
- Decline/cancel, disconnect/retry, insufficient disk/corruption tests via safe fixtures where live fault injection is disruptive; preserve queue, no surprise output run or silent fallback.
- Repeated Create, close during install, cancel near completion and model operation busy in another copy do not trigger extra narration. Repeat launch is prompt-free when healthy and does not download optional models.
- Retest Ctrl/GUI cancellation for each engine; no successful partial output or orphan worker. Source files untouched.
- If nesting adopted: first install, legacy migration, parent repair and interrupted repair are demonstrated in disposable qualification copies; both old/new data remain recoverable.

### AUD-004: clean Windows and bootstrap

**Windows 10:** actual standard-user x64 machine, exact build/RAM/security policy/connectivity recorded, no Python/winget/FFmpeg before test. Do not install prerequisites manually.

- Extract approved Windows ZIP into a normal writable path with spaces; double-click the included `.bat`.
- Python stage 0 offers verified user-scope installation and Cancel. Confirm no forced elevation, unrelated PATH/system changes or dependence on winget. Record Python installer verification and its actual per-user location; do not claim Python was installed inside the repo if it was not.
- Prove Tk window initialization and SSL; model choices appear; FFmpeg/ffprobe portable fallback is verified/executable.
- Skip heavy engines; launch and produce Edge and Kokoro output. No GPU promises; heavy engine choices disclose limitations accurately.
- Relaunch; no unnecessary reinstall/download. Controlled repair in a disposable copy preserves settings/models/output and handles cancel/permission denial.
- Record created repo/user-scope components and the precise uninstall/help guidance. Do not remove shared user-scope Python as part of app cleanup.
- Test absence/aliases with real machine discovery or safe stubs; never delete working installed tools from HOME-PC to fake a clean PC.

**Windows 11:** HOME-PC qualifies actual GPU runtime, security-policy behavior and extracted-artifact launch/setup/repair paths. Run standard-user behavior where available through a separately approved account/environment. HOME-PC with preinstalled Python is not a clean no-Python installer test; record that limitation. If a particular Windows 11 clean-machine claim cannot be proved, document the covered Win10 clean + Win11 actual configuration precisely and obtain owner scope approval rather than report a blanket clean Win10/11 PASS. Any required missing gate remains OPEN.

**macOS:** v0.7.0 artifact/support HOLD, Qwen3 unavailable. Keep old published Mac release unchanged. Native qualification later must cover actual architecture/OS, no-Homebrew bootstrap, SSL/Tk including bounded real initialization, FFmpeg, permissions/Gatekeeper, launch/repair, optional supported engines, non-TTS and extracted archive. Windows/Linux unit tests cannot close it.

### AUD-009: actual unseeded acquisition

Use a new owner-approved isolated qualification copy and in-tree caches; do not purge existing models/caches.

- Record initial inventory proving each target Qwen model is absent in that copy and that downloader seeds/external ambient caches are disabled for this gate.
- Download CustomVoice and Base for real over the intended network endpoints, one at a time or both with accurate shared accounting. Record actual bytes transferred, initial/final partial files, reuse source, commit-pinned manifests, sizes and SHA results.
- If Base is added after CustomVoice, approved shared bytes from that same real acquisition are reuse, not an independent second full download. Report network-acquired unique files vs shared reuse explicitly.
- Interrupt and resume a safe acquisition; verify part handling, cancellation and final rehash. Prove load/readiness and a preset/clone output from the extracted copy.
- Existing screenshots showing “installed” or a prior seeded qualification are not sufficient. Previously completed unseeded evidence can close a row only if logs/hash/manifest match the actual acquisition contract and final relevant code is mapped.
- Whisper is not required for ordinary bundled clones. If developer recognizer acquisition is release-qualified, record it as a separate explicit optional developer action. Do not keep the old mandatory-consumer-recognizer gate after removing that consumer requirement.

### AUD-005: six-reference provenance/authorization gate

Collect a minimal owner-reviewed declaration mapping all six hashes in Appendix A to actual creator/source, creation method, any sampled third-party voice/performance and authorization for public distribution/use with both engines. The owner already authorized redistribution in this interview context; missing factual provenance still must be supplied, never invented. Bundle text publication was separately approved by Q8. Keep personal details unnecessary to public documentation in ignored evidence; permanent docs record disposition and hash binding.

### Non-TTS manual gate

Smoke all five non-TTS tools with synthetic non-private fixtures: MP3 Tool, M4B Converter, M4B Maker, M4B Metadata Editor and Cover Image. Check import, output base/run folder, preview/edit where relevant, cancellation, metadata/covers and one real output per tool. Launcher/preferences and maintenance messages must still work, including chosen environment consequences. No filename redesign outside TTS.

### Manual gate completion

Mark each row PASS / FAIL / NOT RUN / HOLD with evidence. A single all-green test-count screenshot cannot replace these rows. Any failure in final speech, naming/identity, zero-touch clones, consent, data preservation, clean Windows, required unseeded acquisition, rights or exact artifact blocks Windows release. Mac HOLD is owner-approved and does not falsely certify a Mac artifact.

## 10. Release gate ledger and rollback

| Gate | Required evidence | State at plan delivery |
|---|---|---|
| Prior CLR scope | Supplied closure account and current remote Handoff evidence | Accepted historical scope; not new release qualification |
| QA-01 endings | Measured final decoded outputs and owner final-word listening across roster/routes | OPEN / owner-reported FAIL |
| QA-02/03 names and identity | 28-label/permutation, planner/collision/retry proofs and manual filenames | OPEN |
| QA-04/05 installation | Four choices and exactly-once pending-run fault matrix | OPEN |
| QA-06 bundled clones | Owner-reviewed exact six texts + fresh clone runtime proof + strict hashes | OPEN; publication approach approved |
| QA-07 topology | Bounded feasibility, owner decision, lifecycle/migration proof | OPEN; outcome conditional |
| QA-08 reference move | Exactly six path moves with invariant hashes/packaging | Approved scope, not implemented |
| QA-09 protected quality | Six references + 28 previews unchanged; sampler/text invariants | Required; no new media changes performed |
| AUD-004 | Physical clean Win10 / honest Win11 actual coverage | OPEN |
| AUD-005 | Six-hash factual declaration and release disposition | Authorization reported/confirmed approach; provenance record OPEN |
| AUD-009 | Actual unseeded model bytes, hashes, resume/load/output evidence | OPEN / existing evidence not inspected locally |
| Claude full gate | Final executable tree gate and honest skips/counts | NOT RUN for v0.7.0 |
| Codex independent closure | Corrected final SHA audit report | NOT RUN for v0.7.0 |
| Owner round-two QA | Exact qualification artifact and reviewed checklist | NOT RUN |
| AUD-008 final RC | Authorized 0.7.0 identity, clean exact ZIP/hash, re-extraction and final tests | NOT AUTHORIZED / NOT BUILT |
| macOS v0.7.0 | Native platform qualification | HOLD by owner decision |
| AUD-010 main full lock | Future dependency debt unless new evidence changes risk | Deferred, nonblocking as approved |
| Default-branch integration, tag, publication | Separate explicit owner approvals after qualified final artifact | NOT AUTHORIZED |
| Restoration/cleanup | Reviewed dry-run exact manifest paths + separate owner approval | NOT AUTHORIZED |

Rollback strategy is to retain evidence and known-good copies, stop on uncertainty, and revert only scoped implementation commits through normal reviewed Git changes if needed. Do not rewrite history or reset a dirty tree. Bundle/path changes are versioned together; an old release continues to use its own old asset mapping. Failed environment migration keeps the legacy installation; failed main repair restores the prior parent/child transaction. Failed downloads leave verified installed models intact. Failed RC publication into a local destination preserves old ZIPs. Failed transcript review publishes nothing and leaves the original store unchanged.

A “code complete” verdict is narrower than “release ready.” No automated agent may convert an unresolved owner/physical-machine gate into PASS.

## 11. Per-checkpoint reporting and next-chat workflow

Every Claude report should contain:

- Repository, branch, actual pushed commit SHA, assigned checkpoint and completion status.
- Files/behaviors changed and reason, including which approved Q supersedes an old assertion.
- Focused tests and actual results; any full gate with exact tree/interpreter/counts; no invented Linux/Mac/Windows proof.
- Protected assets/private-state invariants, download/environment actions actually authorized and performed.
- Open issues, owner tests/decisions required, next exact checkpoint and any scope deviation.

Update Handoff with a short newest-current block and append durable Decisions; do not add another historical megadump. Leave unrelated dirty files alone. Stage explicit paths, inspect staged diff for private records/large binaries/environment files, verify existing origin/working branch and commit/push per standing rules. No blind `git add -A`.

The normal ChatGPT review chat should check the sub-checkpoint exit table/session protocol, verify the pushed state, compare evidence, identify a concrete blocking manual action if any, then recommend KEEP/COMPACT/FRESH based on checkpoint continuity. Do not invent a CLI compaction command; use current local help if the exact command is unknown. Prompts use exactly one fenced copy-ready block per agent assignment; owner manual steps remain outside that block.

### Optional skills — no installation dependency

The owner's external reviewer suggested relevant addyosmani/agent-skills workflows. Use their ideas selectively if already installed and locally inspected; no installation, provider routing, hooks, autonomous agent teams or expanded scope is authorized here. Native code/search/tests suffice.

- Reproduce → localize → reduce → fix → guard for audio; TDD and source-driven verification of installed FFmpeg/pydub behavior.
- Stable interface/migration review for identity, reference paths, bundled records and setup-worker protocol; adversarial lifecycle review for nested venv and exactly-once resume.
- Security review for schema/containment/private-data exclusion; dependency audit only, no pin upgrades.
- Incremental implementation and scoped working-branch commits; ignore trunk-based merge advice.
- Do not invoke /spec, /plan, /build auto or /ship to replace the approved phased plan. If a locally verified plugin exposes /agent-skills:review, use its advertised qualified command rather than assuming /review maps to it.
- Redirect documentation/ADR/constraint advice into the existing Decisions/Handoff/Briefing/Changelog contract or this files/plans plan; no new md-instructions files.
- Any code simplification is within its assigned implementation checkpoint, before the required gate. No after-gate cleanup/refactor that silently invalidates its evidence.

### Compact copy-ready handoff for a new NORMAL ChatGPT project chat

Copy the following text and attach this plan. This handoff is for a normal project chat, not another Work session.

> Continue Audiobook Creation Tool as the planning/review layer. Read the attached ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md as the approved decision/specification source. All 35 questions are resolved: A except Q11=B; Q9 adds config.toml developer_mode=false/true maintainer tools; Q13 preserves exact six approved texts including Male 4 “Hello Arthur.”. The release target is now v0.7.0.
>
> Inspect elmatthe/audiobook-creation-tool, source feature/0.6.7-speech-pipeline-and-layout at inspected d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1 (refresh first). Later implementation branch is feature/0.7.0-release-remediation. Actual default branch is master. Work chat performed planning only: no code/Git/environment/download/release changes and no new tests.
>
> Use final Revision 2, including the execution protocol, P00C evidence runner and sub-checkpoint exit table. Manage one bounded Claude Code checkpoint at a time, starting P00A read-only baseline. Follow supplied AI-WORKSPACE.md and Vibe-coding-chat-workflow.md; repository md-instructions permits exactly four permanent files, so keep this plan under files/plans/. Review pushed evidence and provide concise single-block prompts. Use Codex independently at P09; owner performs second-round manual gates, then separately approved final identity/RC work.
>
> Preserve exact tag 20261021-184021-592ae0be and its manifest under files/dev-work/manual-fresh-install/. No preserved environment activation, cleanup or restoration. Six approved transcripts remain in preserved runtime-data; only later no-echo helper extraction with owner-only private review is approved; agent reads only metadata until the six-field public scope is approved. No private store is committed. Retain all six reference bytes/basenames and all 28 previews; only the reference directory moves.
>
> No version bump yet, no master integration, tags, release, publication or deletion. Stop at transcript review, environment feasibility decision and all explicit artifact/manual/cleanup gates. Existing CLR closure is accepted for its scope; new owner QA blocks release readiness. Begin by giving the P00A prompt and wait for the Claude report.

### First bounded Claude Code prompt — P00A only

```text
Read files/plans/ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md and applicable local development rules. Execute P00A only: a read-only baseline of the refreshed feature/0.6.7-speech-pipeline-and-layout state, preservation manifest/path identities, six reference and 28 preview integrity, and affected audio/naming/setup/environment/test contracts.

Read only the execution protocol, P00A, Sections 1–3 and the top current Handoff first; search other contracts selectively. Record the supplied plan as expected untracked dirt, check actual shell/HEAD/branch/VIRTUAL_ENV and read-only remote access. Write only the ignored baseline report specified by P00A. Do not create/switch implementation branches, edit tracked source/config/tests/docs, run launchers or synthesis, acquire models/packages, activate preserved environments, extract private transcript text, clean/restore directories, package, bump versions, merge, tag or release.

Report actual branch/SHA, relevant dirty state, preservation/integrity findings, risks and the next bounded checkpoint. Stop for review before P00B.
```

If the plan has not yet been placed under files/plans/, the owner supplies that file first; Claude must not pretend it exists or fetch an older v0.6.7 plan instead.

## 12. Revision-2 review disposition

The owner requested reconciliation of an external Claude gap analysis before implementation. This revision integrates the findings into the contracts/phases above; it is not a loose amendment appendix that an implementation agent must merge mentally.

| Review point | Final disposition |
|---|---|
| PowerShell syntax in Bash | All executable Windows agent examples use explicit forward-slash Python paths; detect actual tool shell/version. PowerShell-only owner settings are labeled. |
| Long full-gate timeout and swallowed pytest diagnostics | P00C adds streamed evidence/JUnit/final status before any new full gate. Use supported background tasks and a checked time budget; external stdout redirection alone is insufficient. |
| Full gates too late | Required major-phase full gates added at P01C/P02B/P03D/P04C if adopted/P06C/P07C; P08 can reuse only identical input evidence. Final identity gets its own gate. This supplements Q30 under the owner's review request without running a full suite after every edit. |
| Red regressions between sessions | Exact new-test strict-xfail ledger only for P01A/B; normal execution, proof of intended old-code failure, remove on fix, zero temporary ACT070 markers after P01C. Existing broken tests cannot be quarantined. |
| Private transcript text in AI/session logs | No-echo deterministic extraction and bundle generation, metadata-only agent view, owner-only private-file review and approved artifact hash. Public six-string bundle diffs are allowed only after scoped owner review. |
| VS Code activation/handles | Detect inherited activation; documented local owner settings and new clean session before mutation; real lifecycle tests in disposable copies not used as IDE interpreter. No global settings/policy change or broad process kill. |
| Entry/exit ambiguity | Universal expected-HEAD/branch/status/auth/shell protocol, expected untracked plan input, per-sub-checkpoint green/debt/evidence/stop table and clean scoped pushed exits. Evidence-only/manual exceptions explicit. |
| P04 owner gate stalls unrelated work | Only layout-neutral P05A can proceed while awaiting the decision, one assigned session at a time; P05B/P06 await approved topology. |
| Unsanitized initial plan | This revision removes the absolute local username/root; P00A still reports the exact supplied plan as expected untracked input. |
| Preview labels/order and transcript tooling | Metadata-only sync with immutable WAVs/history; monkeypatched stress tests; preview, transcript-review and calm-harness coverage added. |
| First-run Qwen execution context | Settled: stdlib consent/planning then explicit verified-main-CPython-3.12 setup-worker subprocess before final app launch. No heavy pre-venv import. |
| Missed EOF paths | Explicit Edge batch constants/final gap, direct end stacking and shipped sample/helper caller inventory added. The cited generate_voice_samples.py line records end_pause; it does not itself prove a separate renderer. |
| Nested venv exact danger points | Base-Python home/prefix, _discard_venv_aside, commit/rollback/recovery and safe_to_remove_environment are named proof targets. |
| Lazy acquisition | Inventory per-voice/G2P/spaCy/Chatterbox assets; no implicit first-synthesis network path escapes consent. |
| Developer true commit | Runtime fixture accepts it; candidate root config/repository gate rejects it before commit as well as packaging. |
| Platform declaration/packager default | Windows-only current product metadata/default distribution; preserve Mac code/testing and explicit hold. No routine build-both output. |
| Speculative legacy fallback | Establish supported overlay/restoration need first; otherwise canonical-only lookup. |
| Native scaling, credentials, security policy | Owner-only real display-scale/auth/policy actions are distinguished from approximations or mocks; policy failures stop rather than bypass protection. |
| Skills | Optional locally verified use only; no installs, autonomous build/ship flow, extra documentation tree or automatic branch-policy change. |
| Closeout/integration links | Pin gallery/raw links to existing immutable asset commit before RC. Recheck ancestry and permit only separately authorized --ff-only integration of exact audited RC SHA; divergence stops. |

No architecture or release-scope questions remain open for starting P00A. Later owner transcript-review/topology/manual/artifact/cleanup gates remain deliberate execution requirements. “Final plan” means implementation-ready instructions, not a claim the application fixes or release tests have already passed.


## Appendix A — Fixed six recording identities

These SHA-256 values are read from the inspected runtime's registered expected reference hashes and agree with the corresponding Chatterbox binding contract. This session did not download/recompute binary WAV SHA-256; P00 and implementation must recompute locally. A Git blob SHA is not interchangeable with these content hashes.

| Stable reference ID | Canonical v0.7.0 basename (same as baseline basename) | Qwen voice ID | Expected WAV SHA-256 |
|---|---|---|---|
| Female-1 | Chatterbox - Female 1.wav | qwen3-female-1 | b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4 |
| Female-2 | Chatterbox - Female 2.wav | qwen3-female-2 | 428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205 |
| Male-1 | Chatterbox - Male 1.wav | qwen3-male-1 | 45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58 |
| Male-2 | Chatterbox - Male 2.wav | qwen3-male-2 | 592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355 |
| Male-3 | Chatterbox - Male 3.wav | qwen3-male-3 | 4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80 |
| Male-4 | Chatterbox - Male 4.wav | qwen3-male-4 | 47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad |

Both engines use one copy of each recording. Chatterbox IDs are the corresponding `chatterbox-female-1/2` and `chatterbox-male-1..4`; labels and reference-directory names do not redefine those IDs. The six approved transcript texts are intentionally absent from this plan because their actual contents were not supplied to this Work session.

## Appendix B — Primary-source references and audit anchors

Repository links below are pinned to the inspected commit so future changes do not silently rewrite the evidence baseline. They are navigation/evidence references, not proof that this Work chat executed code.

- [scripts/tts/voice_registry.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/voice_registry.py)
- [scripts/tts/epub2tts_gui.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/epub2tts_gui.py)
- [scripts/tts/epub2tts_edge/epub2tts_edge.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/epub2tts_edge/epub2tts_edge.py)
- [scripts/tts/batch_convert.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/batch_convert.py)
- [scripts/tts/kokoro_synth.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/kokoro_synth.py)
- [scripts/tts/chatterbox_synth.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/chatterbox_synth.py)
- [scripts/tts/qwen3_synth.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/qwen3_synth.py)
- [scripts/tts/qwen3_runtime.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/qwen3_runtime.py)
- [scripts/tts/qwen3_setup.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/qwen3_setup.py)
- [scripts/tts/qwen3_clone_setup.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/qwen3_clone_setup.py)
- [scripts/tts/qwen3_install_ui.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/tts/qwen3_install_ui.py)
- [scripts/shared/bootstrap.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/shared/bootstrap.py)
- [scripts/shared/config.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/shared/config.py)
- [scripts/shared/maintenance.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/shared/maintenance.py)
- [scripts/shared/release.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/shared/release.py)
- [scripts/requirements.txt](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/requirements.txt)
- [scripts/qwen3-requirements.txt](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/qwen3-requirements.txt)
- [config.toml](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/config.toml)
- [scripts/verify.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/scripts/verify.py)
- [files/tests/test_repository_contract.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/files/tests/test_repository_contract.py)
- [files/tests/test_voice_labels.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/files/tests/test_voice_labels.py)
- [files/tests/test_qwen3_packaging.py](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/files/tests/test_qwen3_packaging.py)
- [md-instructions/Briefing.md](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/md-instructions/Briefing.md)
- [md-instructions/Decisions.md](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/md-instructions/Decisions.md)
- [md-instructions/Handoff.md](https://github.com/elmatthe/audiobook-creation-tool/blob/d61822bfbefc6ff0a3a428a7ae93d6993d8ea4f1/md-instructions/Handoff.md)

Official references consulted:

- [Claude Code tools reference](https://code.claude.com/docs/en/tools-reference) and [Windows setup](https://code.claude.com/docs/en/setup): shell availability and foreground/background lifecycle depend on actual version/session; preflight checks these rather than treating ten minutes or Git Bash as universal.
- [VS Code Python settings](https://code.visualstudio.com/docs/python/settings-reference): terminal autoactivation and the newer setting's precedence; local owner changes only.
- [pytest skip/xfail guidance](https://docs.pytest.org/en/stable/how-to/skipping.html): strict XPASS fails; execution and scoped reasons remain necessary.
- [Python 3.12 venv documentation](https://docs.python.org/3.12/library/venv.html): independent environments, absolute interpreter paths and recreation at a changed destination. It does not certify this application's proposed nested repair design.
- [FFmpeg silencedetect documentation](https://ffmpeg.org/ffmpeg-filters.html#silencedetect): explicit threshold/duration diagnostics; verify the shipped executable's options. This does not establish an automatic phoneme-safe trim threshold.

Supplied private/local sources: the complete ACT v0.6.7 Final Manual-QA Remediation Work Handoff; six October 22-labelled PNGs; AI-WORKSPACE.md; Vibe-coding-chat-workflow.md; Useful-Repositories.md; historical Plan 02 scaffold. Source-audit dates refer to the owner's October 21 session; filenames may use UTC October 22. No playable MP3 was attached in this Work session.

**Delivery state:** final Revision 2 planning and source-grounded external-review reconciliation complete. Implementation, local environment/provenance checks, native runtime tests, independent v0.7.0 Codex verification and release qualification remain future work under the gates above.

