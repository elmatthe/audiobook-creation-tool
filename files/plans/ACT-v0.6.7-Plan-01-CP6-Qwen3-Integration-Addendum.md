# ACT v0.6.7 — Plan 01 CP6 Addendum: Qwen3-TTS Production Integration

**Status:** ARCHITECTURE APPROVED by the owner on 2026-10-19 with the rulings in section 0 (Q1-Q8). Slices S1-S4 are implemented on this branch (section 8); S5 qualification and the owner's rights decisions remain. The independent Kokoro slice is already implemented (section 1).
**Authority:** `files/plans/ACT-v0.6.7-Plan-01-Qwen3-TTS-Evaluation-and-Conditional-Integration.md` (CP6, "Owner voice-roster decision recorded 2026-10-19"), `AI-WORKSPACE.md`, the latest `md-instructions/Handoff.md`.
**Branch:** `feature/0.6.7-bundled-chatterbox-references`. No merge, tag, release or Plan 02 work is implied.

## 0. Owner rulings, 2026-10-19 (these supersede the draft text below wherever they differ)

| Q | Ruling | What it means for the build |
|---|---|---|
| Q1 | **Approved.** Second isolated `.venv-qwen3` and one Qwen worker subprocess per source file. | Root `.venv`, production dependencies and Chatterbox stay unchanged. Cancellation, failure recovery, output preservation and progress are verified with fake-worker tests and then against the real worker. |
| Q2 | **Approved with modification.** CustomVoice and Base install independently, plus an "Install Both" choice, in **one shared environment**. | CustomVoice enables Aiden and Ryan; Base enables the six clones. Sizes are shown before anything is acquired, valid cached files are reused (including the speech tokenizer the two models share), nothing downloads on ordinary launch. |
| Q3 | **Approved.** CPU fallback on Windows without an NVIDIA GPU. | Hardware and expected speed are stated in the voice's status text. The 2.15x figure applies only to the tested Ryzen 7 9800X3D. Validated under the production worker, with supported configurations and limits recorded. No silent downgrade, quantization or alternate model. |
| Q4 | **Approved.** Windows first. | macOS keeps every existing engine working and shows the eight Qwen3 voices as "not yet available". No macOS Qwen3 support is claimed until it is tested on a Mac. |
| Q5 | **Not approved for public redistribution.** | The six verified transcripts, new cloned-voice previews and (pending a rights audit) the original reference recordings are **not committed**. The transcript data interface is built and tested with synthetic fixtures and accepts development-only local transcript files. Real clone synthesis still needs the owner's `verified.json` approval; there is no transcript-free cloning. Clone assets stay blocked for public-release qualification instead of silently dropping the safeguard. |
| Q6 | **Approved.** | Qwen follows ACT's existing local-engine narration policy (the voice preset's paragraph pause between chunks and its end pause), not the evaluation's fixed values. Source text, chunk and paragraph boundaries are preserved and there is one final MP3 encode. Timing and assembly have regression tests. |
| Q7 | **Approved.** About 1.4-1.9x real time is acceptable for the first integration. | The UI discloses speed as machine-dependent and promises no fixed performance. Progress, cancellation and error recovery are meaningful. |
| Q8 | **Conditionally approved.** | The generator, documentation, metadata and validation for the permanent 10-second previews are prepared. A preview is generated or published only for a voice whose output rights and source permissions are confirmed. A per-voice rights/status manifest is kept. Edge and cloned-voice previews stay unpublished while rights are unresolved, and the 28-preview deliverable is never declared complete while any preview is blocked. |

**Build decisions taken under these rulings** (recorded in `Decisions.md`):

- Install and repair happen **in the app only**, through one "Install / repair Qwen3 voices" dialog that serves first-time and existing users. `bootstrap.py` is not changed, which removes the D8 bootstrap slice and its risk. The every-launch fast path never touches Qwen3.
- The clone transcripts are read from a **local, untracked** file (`files/runtime-data/qwen3/transcripts.json`, or the path in `ACT_QWEN3_TRANSCRIPTS`), in the same shape as the evaluation's `verified.json`. A tracked transcript file must not exist; a test enforces that.
- One tested wheel set (the cu128 build) is used on every Windows machine. A smaller CPU-only wheel is a later optimisation, not part of this build, because CPU speed was measured with the cu128 build.

## 1. Scope

The owner chose **Decision B**: Edge 5 (unchanged), Kokoro 9, Chatterbox 6 (unchanged, none retired), Qwen3-TTS 8 = **28 voices**.

| Slice | State | Needs owner approval? |
|---|---|---|
| Four Kokoro additions (`am_fenrir`, `am_puck`, `am_onyx`, `bm_daniel`) | Implemented in the registry, tests and Changelog; same Kokoro engine, neutral speed 1.0, no bootstrap change (voice files fetch on first use like the existing five) | No: pre-authorized as a focused slice |
| Qwen3 voices: `Qwen3 - Aiden`, `Qwen3 - Ryan`, `Qwen3 - Female 1`, `Female 2`, `Male 1`, `Male 2`, `Male 3`, `Male 4` | Designed below; nothing implemented | **Yes**, for every item marked "decision" in section 5 |
| 10-second voice previews (`files/voice-previews/`) | Deferred until integration is approved and qualified; rights matrix in section 7 | Yes, for the rights blockers |

Out of scope: any Chatterbox change, any root dependency change, importing the evaluation worker into the GUI, Plan 02.

## 2. What is verified and what is not

Everything in the "Verified" column was measured on HOME-PC (Windows 11, CPython 3.12.10, RTX 5070 12 GB) during CP1-CP5; evidence is in the git-ignored `files/dev-work/qwen3-eval/runs/qwen3-initial/`.

| Fact | Verified? | Evidence / note |
|---|---|---|
| The root venv cannot host Qwen3. The upstream package hard-pins `transformers==4.57.3` and `accelerate==1.12.0`; root pins `transformers==5.2.0`, which alone forces isolation. The other versions in the evaluation stack (`numpy 2.5.4`, `torch 2.10.0+cu128`, `safetensors 0.8.0`, `scipy 1.18.1`) are what the resolver chose and the GPU wheel needs; they are the *tested* stack, not upstream-mandated, and differ from root (`1.26.4`, `2.6.0` CPU build, `0.5.3`, `1.17.1`) | Yes | dependency dry-run report; root `pip freeze` unchanged after the whole evaluation |
| `torch 2.10.0+cu128` executes on this GPU (`sm_120`), bf16 + SDPA finite | Yes | GPU probe before any model download |
| Qwen3 loads from a pinned local snapshot with `HF_HUB_OFFLINE=1` and synthesises | Yes | every evaluation recording was made this way |
| Speed on RTX 5070 (generation seconds / audible seconds): about 1.5-1.9x on the short passage and pilots, and about 1.36x on the two sustained recordings (Aiden 770 s for 567 s of speech; Ryan 833 s for 615 s), so a 10-minute recording takes about 13 minutes; model load about 4 s; clone prompt about 0.8 s | Yes | manifest timings |
| Peak GPU memory 4.7 GB allocated / 5.4 GB reserved at batch size 1; the desktop shell held about 6 GB of 12 GB on the evaluation machine | Yes | pilot + short suite |
| Speed comparison: Chatterbox on this machine's CPU runs at 1.4-2.9x real time; Kokoro 0.18-0.31x | Yes | manifest timings |
| Disk: evaluation venv 5.3 GB installed (wheels 3.1 GB), CustomVoice 4.52 GB + Base 4.54 GB models; the 0.68 GB `speech_tokenizer` is byte-identical in both | Yes | acquisition record (SHA-256 equal) |
| CPU-only feasibility of Qwen3 | Yes, **on one machine only** | AMD Ryzen 7 9800X3D (8 cores / 16 threads, 31 GB RAM), CUDA hidden, CustomVoice Aiden, bf16: the whole 67.76 s short passage took 145.7 s = **2.15x real time**, about 5.7 GB peak memory, load 0.6 s (the GPU path measured about 1.5x on the same chunks). fp32 was 4.1x on a two-chunk sample. A weaker CPU, one without fast bf16, or a laptop is unmeasured and will be slower |
| macOS (Apple Silicon): Qwen3 on MPS/CPU | **No** | not tested; HOME-MacOS is a different machine. No macOS support is claimed |
| Windows without an NVIDIA GPU | **No** (except as the CPU row above) | no CUDA device means CPU only |
| Fresh-install behaviour of a second venv + model download through ACT's setup | **No** | designed here, not built |
| Quality of Aiden and Ryan | Owner selected them for the roster | their short and sustained recordings exist (advisory read-back coverage 0.95-0.96 on the sustained ones) |
| Quality of the six clones | **No: pending.** The owner selected them for the roster, but every clone short and long recording is still blocked on transcript approval; only a synthetic-reference smoke test of the clone code path has run | clones must be heard and accepted before integration is called qualified |

## 3. Proposed architecture (decisions marked D1-D10)

### D1. Isolated runtime: a second virtual environment
Create `.venv-qwen3/` beside the existing `.venv/`, from the same base CPython 3.12 that setup already selects, installing a new pinned file `scripts/qwen3-requirements.txt` (the 89 evaluation pins, `torch`/`torchaudio` from the official cu128 index). It is gitignored, never packaged, never imported by the GUI process, and has its own requirements-state stamp so root drift detection is unaffected. Rebuilding it never touches `.venv`. *Alternative rejected:* editing root pins (impossible without breaking Chatterbox/Kokoro) or bundling a frozen interpreter (size, signing, update burden).

### D2. Process model: one worker subprocess per source file
A small `scripts/Universal/tts/qwen3_worker.py` (venv side, the only module that imports Qwen/torch) and an orchestration module `scripts/Universal/tts/qwen3_synth.py` (GUI side, stdlib + numpy only). The orchestrator starts the worker with an argument list and the absolute `.venv-qwen3` interpreter, writes a job file, reads JSON-lines events, and finally asks the existing PCM seam to export once. Cancellation is a flag file checked between chunks, with a bounded escalation (wait a fixed interval for the worker to stop, then kill the process tree); the worker contract is exactly one terminal event per file, an unexpected end of output or a malformed event is a failed file, partial output and job text are removed, and chunk events are logged while the run's progress stays the existing completed-source-files model (as the Chatterbox path does). Fake-worker tests cover mid-chunk cancellation, unexpected EOF, malformed events, cleanup and clean completion. This re-uses the *design* the evaluation proved (chunk plan, assembly, atomic state, event protocol); it does not import the evaluation modules, which stay dev-only. Per-file launch costs about 5 s of model load, negligible against minutes of synthesis, and means a crash can only lose one file.

### D3. Text handling, joins and pauses
Sentence-aware chunks of at most 600 characters preserving paragraph and title boundaries (the evaluation's verified planner, re-implemented in `qwen3_synth.py` with its own tests), PCM concatenated at the model's native rate, one MP3 encode through `shared.ffmpeg_utils.mp3_export_options`, exactly as Chatterbox and Kokoro do. **Decision:** inter-chunk and end pauses should follow the run's paragraph/end pause settings (as the Chatterbox path does), not the evaluation's fixed 50 ms / 3 s.

### D4. Models: acquisition, storage, offline loading, reuse
`Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` (Aiden, Ryan) and `...-Base` (six clones), at the evaluation's immutable revisions, files hash-verified against the Hub's declared SHA-256, stored under `files/runtime-data/models/qwen3-tts/<repo>@<revision>/` (in-tree, gitignored, never packaged), always loaded from the local snapshot with Hugging Face offline mode on. Download is **opt-in with an explicit size disclosure** (about 4.5 GB per model; about 8.4 GB for both because the speech tokenizer can be shared), as the Chatterbox weights are today. A voice whose model is absent shows "setup required" and stays selectable-but-blocked; nothing downloads silently.

### D5. Clones: reference and transcript requirements
Each clone needs its bundled 15-second reference WAV (already tracked, hash-pinned in `chatterbox_synth.REFERENCE_VOICES`, already in the release allowlist) **and its owner-verified transcript**, shipped as a small tracked data file under `scripts/` that stores each transcript with the reference's SHA-256 (the evaluation already binds approvals to the recording hash). No transcript or a hash mismatch means "setup required"; there is no transcript-free fallback and no auto-approval. Clones remain independent of Chatterbox: `Qwen3 - Male 1` shares only the reference recording with `Chatterbox - Male 1`.

### D6. Platform support and fallback
Supported and qualified first: Windows 10/11 x64 with an NVIDIA GPU (the measured configuration). Everything else is reported honestly through the voice's availability message rather than hidden: macOS is "not yet available" until it is measured on a Mac; Windows without NVIDIA falls back to CPU bf16, which was measured usable on one strong CPU (section 2) but not on typical hardware, so any user-facing claim needs a disclosure that speed depends on the processor and that about 6 GB of memory is used. **Decision** (questions Q3/Q4).

### D7. Registry, GUI and dispatch
New backend literal `"qwen3"` in `voice_registry.py`; eight rows with the owner's exact labels, in a separate group labelled for Qwen3 (distinct from the Chatterbox group), placed after the Chatterbox block so existing order and the default voice (Steffan) are unchanged. Internal ids `qwen3-aiden`, `qwen3-ryan`, `qwen3-female-1` ... `qwen3-male-4`; dispatch reads `VoiceEntry.backend`, never the label. `convert_with_qwen3` is a sibling of `convert_with_chatterbox`; its availability seam is `qwen3_status(voice_id)` (venv, models, transcript, GPU) and its worker cap is 1. No speed control; the engine line states "Qwen3-TTS (local AI, NVIDIA GPU)". Existing registry pins in about a dozen test files move from 20 rows to 28 deliberately, as they did for the Kokoro slice.

### D8. Setup and repair (revised by the rulings in section 0: in-app only, `bootstrap.py` unchanged)
An optional setup step "Qwen3-TTS voices" (checkbox with the size and GPU disclosure) that creates `.venv-qwen3`, installs the pins, downloads and verifies the models, and runs a one-off load probe; a matching repair path; nothing runs on the every-launch fast path. Because setup is bypassed when the existing environment is healthy (`bootstrap.py` launches straight into the app), a first-run checkbox alone would be unreachable for existing installs and for users who first declined it, so the design also needs an **in-app "Install / repair Qwen3 voices" action** reachable from the voice's status line, tested for upgrade, declined, partial-install and retry paths. `bootstrap.py` is about 3,100 lines with contract tests, so the change is made as a minimal, separately reviewed slice.

### D9. Packaging and fresh install
`release.py` already packages the tracked `scripts/` tree and a closed six-WAV allowlist; the new modules, `qwen3-requirements.txt` and the transcript data file ship because they are tracked under `scripts/`. Venv, models, evaluation worker and evidence do not. A fresh install therefore shows the eight voices as "setup required" until the user opts in, and works fully offline afterwards. README and the in-app help gain accurate Qwen3 setup text (size, GPU, speed).

### D10. Output compatibility and rollback
Same 24 kHz mono PCM, same single MP3 encode and bitrate option, same timing-preset fields, same output folders. Rollback is a full revert of the Qwen3 commits: the registry rows, dispatch branch, new modules, **and the bootstrap/setup, availability-hook, requirements-state and test changes**, so no installation or probe caller outlives its worker (qualified on an existing installation, not just a fresh one); `.venv-qwen3` and the models are ignored files that can be deleted at will. Nothing in `.venv`, `scripts/requirements.txt` or Chatterbox changes, so a revert cannot affect existing voices.

## 4. Implementation slices (after approval), each with focused tests and a Codex review

| Slice | Content | Gate |
|---|---|---|
| S1 | `qwen3_synth.py` (plan, protocol, status, export) + `qwen3_worker.py` + `qwen3-requirements.txt` + transcript data, with fake-worker tests (protocol, cancel, progress, availability states, no GUI-process import of torch/qwen, root requirements unchanged) | focused tests, Codex review |
| S2 | Registry rows, dispatch, GUI status line and availability, registry-pin test updates | focused + registry/UI suites |
| S3 | In-app "Install / repair Qwen3 voices" dialog and installer (venv, pinned requirements, per-model download with cache reuse, verify, repair, cancel); no bootstrap change | installer tests with fake pip/HTTP, a real fresh-venv run, dialog layout tests |
| S4 | Packaging checks, README/help/Changelog | release-packaging tests |
| S5 | Qualification: fresh-clone install on Windows with an NVIDIA GPU, a real conversion with each engine path, cancellation mid-file, then one full `scripts/verify.py` | owner manual gate; baseline failures reported as such |

## 5. Questions that need the owner's decision

1. **Q1 (D1/D2):** Approve the isolated second venv + per-file worker subprocess as the production architecture?
2. **Q2 (D4/D8):** Install both Qwen3 models together (one opt-in, about 8.4 GB + 5.3 GB venv) or let the user choose CustomVoice (2 voices) and clones (6 voices) separately?
3. **Q3 (D6):** On Windows without an NVIDIA GPU: offer CPU generation (measured 2.15x real time on one strong CPU, about 6 GB memory; other CPUs unmeasured), or mark the eight voices unavailable? My recommendation: offer it with that speed/memory disclosure and qualify it on a second, weaker machine before claiming broad support.
4. **Q4 (D6):** macOS: ship the eight voices as "not yet available on this platform" until a Mac qualification, or hold the Qwen3 slice until macOS works?
5. **Q5 (D5):** Ship the six verified reference transcripts inside the app (they are short excerpts of the narrators' books and are required at run time). Confirm this is acceptable, or tell me where they must live instead.
6. **Q6 (D3):** Follow the run's paragraph/end pause settings for Qwen3 (recommended) rather than the evaluation's fixed values?
7. **Q7:** Is about 1.4x real time acceptable, with the throughput disclosed in the voice's status line? The two sustained CustomVoice recordings ran at 1.36x and the short passages and pilots at 1.5-1.9x, so a 10-hour book is roughly 14-19 hours of generation on an RTX 5070. Sustained clone (Base model) speed is not measured yet because the clones wait on transcript approval. Chatterbox on CPU is similar (1.4-2.9x).
8. **Q8 (section 7):** Authorize publishing 10-second previews of the cloned voices, and say what to do about Edge TTS previews.

## 6. Risks and limitations

- Throughput is slower than real time on both the GPU (about 1.4-1.9x) and the measured CPU (2.15x); long audiobooks take hours. The GPU is only about 1.4x faster than the CPU here because the autoregressive generation loop is largely CPU-bound.
- NVIDIA-only acceleration; VRAM headroom depends on other GPU applications (about 5.4 GB reserved).
- About 14 GB of disk and a multi-gigabyte download for full Qwen3 support; setup time is long.
- Windows application-control prompts may appear on first load of the unsigned native libraries; the first-load retry/pre-warm pattern already used for Kokoro and Chatterbox is reused.
- Qwen3 does not expose a stop-reason, so generation-cap hits are only estimated from output length (across every completed recording the longest chunk used about 8% of the 8,192-token generation cap, 659 estimated codec frames in one Ryan chunk, and about 6% in the pilot, so a cap hit is not a practical concern at the 600-character chunk size).
- The evaluation proved quality only for the English passage used; other languages are untested.

## 7. Preview redistribution matrix (for `files/voice-previews/`; nothing is published yet)

| Voices | Provenance | Rights status |
|---|---|---|
| Edge (5) | Microsoft's online service, reached over the network | **Unconfirmed**: the service terms govern redistribution; I will not publish these without your explicit decision |
| Kokoro (9) | Local model `hexgrad/Kokoro-82M`, Apache-2.0 | Expected to be publishable; I will cite the license and confirm per voice |
| Chatterbox (6) | Local MIT engine, cloned from the bundled reference recordings | **Unconfirmed**: a preview is a synthetic voice derived from another person's recording; needs your confirmation that you may publish it |
| Qwen3 CustomVoice (2) | Local model, Apache-2.0, preset speakers | Expected to be publishable; cite the license |
| Qwen3 clones (6) | Same six reference recordings as Chatterbox | **Unconfirmed**, same reason as Chatterbox |

Rejected presets (Dylan, Eric, Ono_Anna, Serena, Sohee, Uncle_Fu, Vivian) are never published. Previews are not added to release archives or the website without separate approval.

## 8. Implementation record (2026-10-19, slices S1-S4)

Built on this branch under the rulings in section 0; the build decisions are in `Decisions.md` (2026-10-19, two entries). What was built, and
where it differs from the draft text above:

- **D1/D2 as approved.** `.venv-qwen3` (CPython 3.12, 89 packages, each pinned by SHA-256 in `scripts/qwen3-requirements.txt`, torch/torchaudio
  from the cu128 index), one worker subprocess per source file (`tts/qwen3_worker.py`), `@@EVENT` JSON lines, Windows Job Object containment
  (`tts/qwen3_process.py`; a command that cannot be contained is not run). Machine-wide OS file locks (`setup.lock`, `inference.lock`).
- **D3 (Q6).** The voice preset's paragraph pause after every chunk and its end pause once; 600-character sentence planner with source spans;
  one final MP3 encode via the existing `mp3_export_options`; atomic publish; the job folder (which holds the user's text) is always removed.
- **D4/D8 (Q2).** `qwen3_models.json` pins both models at immutable revisions (11 files each, size and SHA-256); CustomVoice, Base and "Install
  Both" install independently, shared files are downloaded once, intact files are reused, sizes are shown before anything downloads, and nothing
  downloads on launch. One in-app dialog serves first-time and existing users; `bootstrap.py` is unchanged.
- **D5 (Q5).** Clone availability needs the reference recording and a locally supplied, approved transcript; no transcript is tracked and a test
  enforces that.
- **D6 (Q3, Q4).** Windows only; the cu128 build is used for GPU and CPU alike; the status line states the detected hardware. macOS lists the eight
  voices as not yet available.
- **D7.** Registry rows 21-28, the `convert_with_qwen3` dispatch, the GUI status line and the install button; the registry-pin tests identify rows
  by id.
- **D9/D10.** The new modules, the model manifest and the requirements ship; `.venv-qwen3`, models, the install record, job folders and any
  transcript never do (tests build real and planted archives). Output format, folders and timing fields are those of the other local engines.
- **Q8.** Section 7's matrix is implemented in `files/voice-previews/previews.json` (per-voice rights record) with a rights-gated generator.

Reviews and checks: three Codex slice reviews (S1-S3), a Codex review of the S3 fixes plus S4, and two confirmation rounds; every finding was fixed
and has a regression test. Real-machine evidence is summarised in `Handoff.md`. **Not done (S5):** fresh-clone install on a second machine,
weaker-CPU timing, long-form clone speed, macOS, the real clones, and the owner rights decisions.
