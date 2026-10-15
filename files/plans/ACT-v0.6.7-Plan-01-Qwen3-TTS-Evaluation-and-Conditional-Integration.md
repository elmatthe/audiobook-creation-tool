# Audiobook Creation Tool — Plan 01: Qwen3-TTS and Kokoro Voice Evaluation and Conditional Integration

**Status:** Requirements settled on 2026-10-15; ready for bounded local implementation when the owner gives Claude Code an execution prompt. This document does not start implementation in the planning chat.

**Repository:** https://github.com/elmatthe/audiobook-creation-tool  
**Required branch:** `feature/0.6.7-bundled-chatterbox-references`  
**Inspected remote head:** `f2ccf82bd41529f2e5737852da7592c6d6d7274f`  
**Kokoro extension checked:** 2026-10-15 at `267571181c0ee85a229fb39c9567d24ab1f08f32`; the intervening commit adds only this plan and its prompt, with no runtime-code change.  
**Save this plan as:** `files/plans/ACT-v0.6.7-Plan-01-Qwen3-TTS-Evaluation-and-Conditional-Integration.md`

## 1. Goal and execution boundary

Give the owner trustworthy, play-ready comparisons of all nine official Qwen3-TTS presets, clones of the six existing Chatterbox references, six current Chatterbox baselines, and the six specified Kokoro voices, followed by four Qwen sustained narration tests. Preserve the working ACT application while the owner decides whether to integrate Qwen and, independently, which new Kokoro candidates to add.

Claude Code implements approved checkpoints locally on HOME-PC. Codex CLI independently reviews the changed implementation and evidence at the checkpoints below; it does not build a competing implementation. The owner verifies reference transcripts, selects two Qwen long-test voices after hearing the short samples, makes the final Qwen/Chatterbox decision, and separately approves or rejects each new Kokoro candidate.

The evaluation checkpoints are executable now as a plan. Production integration is a conditional follow-up requiring the owner's listening decision and a bounded implementation addendum. **Plan 02 remains deferred until the chosen Plan 01 outcome is implemented, reviewed, and committed/pushed on this branch.** Neither phase implies a default-branch merge or release.

Follow current owner instructions, this active plan, actual project authority, the supplied `AI-WORKSPACE.md`, and relevant local guidance. Use the existing workflow's Goal / Scope / Constraints / Checkpoints / Done-when pattern. Discover local `AGENTS.md`, adapters, and any actual instructions-template selectively; do not invent them or restore retired template collections. `Useful-Repositories.md` is an optional index, not permission to install capabilities. Native tools, official upstream sources, and the existing harness are sufficient; no new skill collection, routing gateway, cloud service, or multi-agent framework is required.

## 2. Approved scope and constraints

| Item | Settled requirement |
|---|---|
| Short comparisons | 27 expected recordings: nine Qwen CustomVoice presets, six Qwen Base clones, six current Chatterbox baselines, and six specified Kokoro voices; every requested row must exist even when generation fails. |
| Short length | Approximately one minute; 45–90 seconds is the listening target. Use the identical canonical passage for all voices. |
| Kokoro slice | Existing `am_michael` and `bm_george`, plus new candidates `am_fenrir`, `am_puck`, `am_onyx`, `bm_daniel`; existing engine/root environment, neutral speed 1.0, no production registry/GUI changes during evaluation. |
| Sustained comparisons | Four Qwen recordings: Aiden, Dylan, one female preset and one clone chosen by the owner after short listening. Kokoro has no mandatory long test in this addition; extra long trials require a separate owner selection. |
| Sustained length | Approximately ten minutes; 8–12 minutes is the target, using one identical complete passage for all four. |
| Formats | Native-rate lossless WAV evidence and convenient MP3 listening copies, with an index and machine-readable manifests. |
| First machine | HOME-PC, Windows, reported RTX 5070 12 GB. Confirm hardware, driver and usable memory live. Windows 10/11 clean-install qualification belongs to Plan 02. |
| macOS | Qwen synthesis qualification is deferred during evaluation. If Qwen is selected for production, macOS requirements and tests must be settled before claiming product support. |
| Dependencies | Preserve the root `.venv` and production requirements. Explicitly approved evaluation-only exception: `files/dev-work/qwen3-eval/.venv/`, Python 3.12, invoked by absolute executable path. |
| Reference text | Check the desktop repository for existing transcripts. Otherwise draft them locally with Whisper, then obtain owner verification before transcript-conditioned cloning. |
| Resources | Up to 20 GB total new downloads for the approved evaluation; reuse valid existing files. The owner confirms ample disk space, so space is not a product constraint. Check actual free space and estimate downloads before starting; keep volatile measurements in local evidence and stop before exceeding the download allowance. |
| Performance | Record latency, generation throughput and peak VRAM where measurable. Quality is the evaluation priority; there is no arbitrary speed cutoff. |
| Deferred experiments | No VoiceDesign, 0.6B downgrade, transcript-free clone comparison, quantization, fine-tuning or third-party Qwen fork without a separate decision. |

Out of scope during evaluation: GUI/voice-registry integration, production bootstrap or dependency changes, Chatterbox removal/archival, launcher redesign, release packaging changes, unrelated repairs, global installs, drivers/CUDA Toolkit installation, PATH/profile/registry changes, cloud synthesis, recording uploads, tags/releases/default-branch writes.

Do not alter source recordings, manufacture a successful result, silently substitute a model or voice, tune individual speakers, or repeatedly regenerate until a voice happens to sound good. Report failures and all retained attempts. A technically successful generation is not listening approval.

## 3. Confirmed baseline and extension points

Facts below were checked read-only against the named remote branch. They do not prove the state of the desktop checkout, installed environment, or available model caches.

| Path / component | Confirmed behavior and consequence |
|---|---|
| Branch / version | Head `f2ccf82` is one commit ahead of `master`, containing the embedded-MP3-metadata fix. Application/config identity remains 0.6.6. Do not bump it merely for evaluation. |
| `md-instructions/Briefing.md` | Bundled references are exactly six leading-15-second mono 24 kHz PCM s16le WAVs; originals and runtime derivatives remain read-only/local as specified. |
| `scripts/Universal/tts/voice_registry.py` | Edge, Kokoro and six Chatterbox voices are registered. Kokoro `am_michael` and `bm_george` are present; the four named new candidates are not. Do not register Qwen or new Kokoro candidates to make the harness enumerate them. |
| `scripts/Universal/tts/kokoro_synth.py` | Accepts a `voice_id` directly, routes `am_` to American English (`a`) and `bm_` to British English (`b`), caches pipelines by language, and exposes `kokoro_file_to_mp3` plus a PCM `_export_mp3` seam. Reuse this engine unchanged. |
| `scripts/Universal/tts/generate_voice_samples.py` | Dev-only entrypoint; `_synthesize_for_voice`, quality-suite helpers, `QualitySample`, manifest writing, reference-state protection and final-artifact measurements provide reusable seams. Existing modes must retain their behavior. |
| Historical `--chatterbox-eval` | Covers only four original voices and historical temperature 0.8. It is not the six-voice, current-production baseline requested here. |
| `scripts/Universal/tts/quality_corpus.py` | Supplies original difficult prose, structural tests, sustained narration and a longer complete story, with corpus identity. Extend additively only where necessary; do not rewrite the old fixtures or their expected results. |
| `scripts/Universal/tts/chatterbox_synth.py` | `REFERENCE_VOICES` / `resolve_reference` own source identity. `chatterbox_file_to_mp3` uses the real chunked production path, a 300-character ceiling, PCM assembly and one MP3 encode. Current production temperature is 0.72. Leave these policies intact. |
| `scripts/requirements.txt` | Python 3.12 production stack includes torch/torchaudio 2.6.0, Transformers 5.2.0, numpy 1.26.4 and safetensors 0.5.3. Do not upgrade/downgrade these for Qwen. |
| `scripts/verify.py`, `files/tests/test_repository_contract.py` | `md-instructions/` permits exactly Briefing, Changelog, Decisions and Handoff. The owner chose `files/plans/`; preserve this gate instead of weakening it. |
| `scripts/Universal/shared/release.py` | Packages the tracked scripts tree and an explicit six-WAV asset allowlist; it does not generally package `files/`. Keep worker/evidence/model files outside production runtime dependencies. |
| Latest committed handoff | Reports 183 focused passes and a full macOS result of 7,882 passed / 93 skipped / 16 failed. The failures were reproduced on its unchanged base; they remain non-green and unwaived for future release qualification. These are historical reported results, not tests run for this plan. |

The remote root has no tracked `AGENTS.md`, `.ai/` directory or `AI-WORKSPACE.md`; local-only guidance may exist. Do not infer that it is absent locally. Do not reread the 1.7 MB historical Handoff in full: start with its newest relevant section and inspect older decisions only to resolve a concrete question.

### Voice and reference inventory

All nine presets must synthesize **English**, without optional style instructions. Match the loaded model's reported supported speakers case-insensitively, retaining exact API/display identities in the manifest; stop on an unexpected inventory rather than substituting voices.

| Preset | Upstream native language |
|---|---|
| Aiden | English |
| Dylan | Chinese, Beijing dialect |
| Eric | Chinese, Sichuan dialect |
| Ono_Anna | Japanese |
| Ryan | English |
| Serena | Chinese |
| Sohee | Korean |
| Uncle_Fu | Chinese |
| Vivian | Chinese |

Upstream recommends native-language synthesis for best quality, but explicitly supports other model languages. Label the English test accordingly; do not quietly retest a weak English result in its native language.

References are `files/Chatterbox-Voice-Uploads/{Female-1,Female-2,Male-1,Male-2,Male-3,Male-4}.wav`. Read expected SHA-256 values from the existing engine's `REFERENCE_VOICES`, validate actual hashes/PCM properties before use, and compare before/after. Do not duplicate a second editable authority for their hashes. A source-integrity failure blocks that reference's clone/baseline work; independent preset work may continue with the overall gate marked incomplete.

### Kokoro short-test inventory — exactly six voices

| Voice ID | ACT status at inspected branch | English pipeline |
|---|---|---|
| `am_michael` | Existing ACT voice; comparison baseline | American (`a`) |
| `bm_george` | Existing ACT voice; comparison baseline | British (`b`) |
| `am_fenrir` | New listening candidate | American (`a`) |
| `am_puck` | New listening candidate | American (`a`) |
| `am_onyx` | New listening candidate | American (`a`) |
| `bm_daniel` | New listening candidate | British (`b`) |

The official `hexgrad/Kokoro-82M` voice directory contains all six voice assets. CP1 must verify their availability against ACT's installed pinned Kokoro version and current repo-local cache; directory presence alone does not prove successful local synthesis. Michael/George remain registered regardless of the candidate listening outcome. Evaluate only this closed six-voice Kokoro set, not every upstream voice.

## 4. Runtime design and acquisition policy

Use a small evaluation worker in a tracked development location such as `files/dev-tools/qwen_eval_worker.py`, orchestrated by an explicit opt-in mode of the existing sample generator. Split modules only when needed for clear, testable boundaries. Keep new Qwen imports lazy and inside the evaluation interpreter. Never import Qwen into the production process or rely on the production voice registry to discover evaluation candidates.

Run Chatterbox and Kokoro through the root `.venv`, and Qwen through the approved evaluation `.venv`, as sequential subprocesses. Do not install a second Kokoro engine into the Qwen environment or change the root package pins for this addition. Use an argument list, absolute interpreter paths and repository-relative data identities; never construct shell commands from paths/text. No shell activation is required. Preserve spaces/Unicode paths, return codes and bounded logs. A worker failure must leave a useful manifest and release its GPU allocations when the process exits.

Set child-process caches/temp paths before third-party imports: Hugging Face, Torch, pip, XDG/Numba/config caches where applicable, and TEMP/TMP/TMPDIR all under the ignored work area or the existing in-tree model cache. Existing environment variables must not redirect this experiment into a home-directory cache. Do not change the user's global environment. Reuse existing repo-local model cache content read-only where appropriate; do not reorganize or delete it. Disable optional analytics and start no Gradio/web server.

### Dependency gate before model downloads

| Component | Planning baseline / implementation proof required |
|---|---|
| Python | Reuse a live validated 64-bit CPython 3.12 interpreter; record patch version. No global Python install. |
| Qwen package | Official `qwen-tts==0.1.1` is the researched candidate. Inspect the exact published wheel metadata/source before installation; source inspection used upstream commit `022e286b98fbec7e1e916cb940cdf532cd9f488e`. Do not assume wheel and repository HEAD are identical. |
| Qwen exact dependencies | Upstream pins `transformers==4.57.3` and `accelerate==1.12.0`, confirming a conflict with ACT's Transformers pin. Resolve remaining dependencies only inside the evaluation environment and lock exact versions. |
| CUDA PyTorch | A concrete candidate is the official matching torch/torchaudio 2.10.0 CUDA 12.8 wheel pair, listed for Windows by PyTorch. Confirm cp312/win_amd64 wheel availability, dependency resolution, driver compatibility and actual CUDA tensor execution before adopting it. This is a candidate, not a claimed tested combination. Do not install torchvision unless a demonstrated dependency requires it. |
| Attention / precision | First prove the official implementation with PyTorch SDPA and batch size one; upstream code advertises SDPA support. Prefer supported bfloat16, otherwise a documented supported dtype. SDPA changes the execution backend, not per-voice sampling settings. Do not compile FlashAttention or install a toolchain as a side effect. |
| Root Chatterbox | Its torch 2.6.0 stack must be tested independently. CUDA availability alone does not prove RTX 5070 kernel support. Explicitly use `device="cpu"` for baselines if that environment cannot execute on the GPU; label device/precision and do not compare CPU/GPU timing as equivalent. |
| Root Kokoro | Reuse the existing `kokoro==0.9.4` stack, model/cache, language pipelines and FFmpeg resolver. Verify both American and British prerequisites and the six voice assets. If its default device cannot execute on the existing CUDA stack, use a dedicated CPU-only child process with the root interpreter (for example `CUDA_VISIBLE_DEVICES=-1` before importing Torch), record the fallback, and keep installed packages unchanged. The ACT Kokoro helper has no `device` argument; do not invent one. |
| Transcription | Prefer Whisper via the already-required Transformers API. This needs model weights but no separate Whisper package/framework. Start with `openai/whisper-small.en` if the references are confirmed English; select only safetensors plus required processor/config/tokenizer files, approximately 1 GB, not all alternate-framework weights. |

Record a dependency report/dry-run before installing, then exact resolved constraints plus pip reports, interpreter/package versions and `pip check` after installing. Rebuilding the isolated evaluation environment is the recovery route; bypassing resolver constraints or using `--no-deps` to conceal a conflict is not. If the candidate fails, document the concrete problem and a revised compatible pin set before proceeding; a materially different framework/source/model requires owner approval.

Use `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` and `Qwen/Qwen3-TTS-12Hz-1.7B-Base`. Resolve immutable model revisions before acquisition and retain required configs, generation config, text-tokenizer assets and the embedded `speech_tokenizer/` subtree. The two model repositories list roughly 4.52 GB and 4.54 GB respectively; exact selected bytes and cache reuse must be checked locally. The integrated tokenizer normally removes any need for a separate standalone tokenizer download; verify against the installed package.

For Kokoro, reuse its valid existing repo-local model and voice assets. Acquire only missing official assets needed by the six selected voices and include them in the existing download allowance; record model revision and per-voice asset hashes. Use ACT's existing loader/cache mechanism, not an alternative Kokoro implementation. Report missing phonemizer/language/model prerequisites before proposing additional acquisition; do not install packages or system tools into the root environment as an implicit voice-selection side effect.

Official Qwen code and these model cards declare Apache-2.0. Preserve relevant licenses/notices and record provenance; this is not permission to redistribute all dependency assets, recordings or weights. Evaluation weights/audio/transcripts remain ignored, local and excluded from releases. Production redistribution decisions are deferred.

After explicit acquisition, synthesize from complete, pinned **local snapshot directories**, with offline mode enabled. This also avoids ambiguity from wrapper calls that may not forward a revision to every nested processor/tokenizer loader. Prove one subsequent preset and one clone generation with network access disabled at the application/Hugging Face level. Do not claim an OS-wide network-isolation test unless one was actually performed.

## 5. Corpus, cloning and audio contract

### Canonical passages

Reuse `DIFFICULT_SHORT` and the original longer story where adequate. Add evaluation-specific corpus items only if necessary for repeated fantasy names and clear title/paragraph/dialogue transitions; preserve the existing corpus entries. Aim for roughly 150–180 words short and 1,300–1,600 words long, calibrated using pilot timing. Freeze one passage per test length, with exact UTF-8 text, word/character counts and SHA-256 before comparison runs.

Include difficult proper names, repeated invented names, dialogue, abbreviations, initials, numbers, dates/times, decimal/ratio punctuation, ellipses and paragraph/title transitions in natural prose. No copyrighted book excerpts, repeated filler loops or hidden metadata lines that one engine silently removes. All voices receive the same underlying narration. Record unavoidable existing engine normalization separately from the canonical input; do not rewrite Chatterbox's established behavior for this experiment.

Durations are targets, not permission to cut content, pad to length, alter speed or choose different text per voice. If a common passage misses the target during calibration, revise it globally before the comparison run. Later outliers retain their actual complete output and a warning; an owner must accept the deviation or authorize a uniform rerun.

### Reference transcripts

Search likely repo-local reference/document locations first, excluding environments, model caches and large generated output trees. Do not search the whole PC or invent the longer-MP3 location. A found transcript is usable only if it matches the **exact 15-second WAV** by source identity and listening, not merely the longer original recording.

If none is usable, transcribe each WAV locally through Whisper in the evaluation environment, without Qwen models resident. Use the installed Transformers `WhisperProcessor`/`WhisperForConditionalGeneration` or equivalent supported automatic-speech-recognition API; load audio as an array through existing audio dependencies and resample in memory to the processor's required rate. Preserve source bytes. CPU transcription is sufficient for these six short clips.

Produce a local transcript review sheet linking each original WAV to its draft transcript, hash and language. The owner corrects names, missing/extra words and clipped endings and explicitly marks each transcript verified. Do not invent a completion beyond the recording. Keep drafts/verified text and hashes locally; do not commit their full content or upload recordings. If language is not English or the selected ASR path fails, report it and propose a bounded alternative rather than silently using the English model.

Preset generation can proceed while transcript verification is pending. **A clone cannot be labeled transcript-conditioned/verified until its matching transcript is approved.** Do not silently fall back to `x_vector_only_mode=True`.

Kokoro needs no Chatterbox reference audio or transcript. Once the common short corpus is frozen and its existing runtime/assets are ready, its six samples may be generated independently of Qwen setup or transcript-review blockers.

### Qwen calls and untuned defaults

Use the official `Qwen3TTSModel` APIs: `generate_custom_voice(text=..., language="English", speaker=...)`; for clones, `create_voice_clone_prompt(ref_audio=<unchanged local WAV>, ref_text=<verified transcript>, x_vector_only_mode=False)` and `generate_voice_clone(..., language="English", voice_clone_prompt=...)`. Reuse a clone prompt within that voice's chunks instead of repeatedly extracting features. Do not substitute a CustomVoice speaker for a failed Base clone.

Omit optional `instruct`. Preserve the installed package/model's resolved generation defaults, including sampling, subtalker settings, repetition penalty and generation cap; record their **effective values**, not just the phrase “defaults.” Use one recorded seed policy across the suite, with stable per-voice/chunk derivation and recorded library/hardware versions. Do not promise cross-hardware bitwise determinism.

### Chunking and joining

Do not reuse Kokoro's 3,000-character limit or treat Chatterbox's 300 as a Qwen limit. Build a small Qwen-specific chunk plan using existing boundary/content-preservation ideas without refactoring the production engines. Preserve paragraph/title boundaries and ordered source spans, avoid false sentence breaks at abbreviations/decimals, pack complete units where possible, and split oversized sentences conservatively. No content loss, duplication, reordering or empty chunks.

Use a small pilot to establish a common safe Qwen profile before the full suite: start around 600 characters per call; test bounded smaller/larger candidates only as needed for generation-cap headroom, memory and seam behavior. Include a preset and a transcript-conditioned clone, plus an English Dylan smoke check. The final cap is evidence-based and common to the comparison run, not a voice-specific quality tuning knob. Record any fallback profile separately and rerun affected comparisons consistently. Keep all pilot results labeled as pilot evidence.

Upstream's wrapper fallback `max_new_tokens` is 2,048, but the snapshot's generation config takes precedence. Read the actual effective cap. Ten minutes must be multiple bounded generations; never pass an entire chapter and merely assume all words were synthesized. If EOS/cap-hit information is not exposed by the supported API, record that limitation instead of fabricating it.

Preserve native-rate float/PCM chunks and join them **before** one MP3 encode. Begin with a documented evaluation join profile matching ACT's local-engine assembly pattern: 50 ms between generated chunks and 3,000 ms trailing silence, without double-inserting a gap or re-encoding already-lossy chunks. Record boundary types and all inserted samples. Do not add normalization, crossfades, denoise, pitch/rate changes or automatic silence trimming that conceals problems. A later timing change must be separately identified and applied consistently.

Keep raw chunks, assembled WAV and MP3, plus join timestamps and first/last text cues. Preserve floating-point originals if integer export would clip; never normalize a clipped sample to make the check pass. Decode-check final files and verify assembled sample count against chunks plus inserted silence within format rounding tolerance.

### Current Chatterbox baselines

Select all six existing registry voices and call `chatterbox_file_to_mp3` with the common short source through the root environment. Preserve temperature 0.72 and all other current production policies, including the 300-character ceiling and existing retry behavior. Do not use the historical four-voice evaluation mode or a recreated upstream demo implementation.

For native WAV evidence, a narrowly scoped **harness-only** wrapper around the existing PCM export seam may capture the exact array passed to `_export_mp3`, then call the original exporter unchanged. Similarly, capture per-chunk outcomes if needed to detect an empty/skipped generation. Keep interception inside a dedicated sequential process/context and restore it even on failure; do not patch production source. If only a decoded MP3-derived WAV is available, label it truthfully and report the native-evidence gap. Never call a one-shot synthesizer with the whole one-minute passage.

### Kokoro samples through the existing engine

Generate one short recording per ID in the six-voice table using **the identical frozen difficult fantasy passage** used for Qwen/Chatterbox. Call `kokoro_file_to_mp3` with that source, the exact `voice_id` and `speed=1.0`, retaining its existing chunking, language routing and PCM assembly. Do not apply Qwen/Chatterbox chunk limits, speaker blending, voice-specific speed changes, pitch processing or pronunciation/style tuning. Keep the 45–90-second target and report actual duration without time stretching.

Allow the dev-only harness to pass the four unregistered candidate IDs directly, or use evaluation-only descriptors; do not append them to `voice_registry.VOICES`, alter GUI menus, or change default voice order/settings. Existing Michael/George entries are reused without modification. Preserve the engine's American/British pronunciation routing rather than forcing all voices through one English locale.

Capture native WAV evidence at Kokoro's existing `_export_mp3` PCM seam using the same narrow harness-only approach as the Chatterbox baselines, then call the original exporter for the MP3. Account for empty/skipped chunks rather than presenting partial audio as complete. Keep source, speed, locale, model/voice-asset identity, actual device and any warnings in the shared manifest. All six get named listening-index links; identify the two existing baselines and four new candidates explicitly.

No new Kokoro voice is added to the product until the owner hears it and explicitly selects its exact ID. This approval is independent of whether Qwen is accepted or rejected. Optional further Kokoro trials can be requested after short listening; do not silently replace one of the four required Qwen long tests with a Kokoro voice.

## 6. Checkpoints and stopping points

Each checkpoint is a bounded unit. During implementation, run focused checks; commit/push verified tracked changes on the exact working branch, update the newest concise Handoff section, and report the actual SHA. Ignored evidence alone is not pushed. Do not reread full historical logs or repeatedly run the full suite.

### CP1 — Local orientation and preflight; no installation or model downloads

1. Confirm actual repository root, HOME-PC identity, expected origin, exact branch, tracked/untracked work and latest remote state using the supplied workspace Git policy. Do not discard or move unrelated work. Reconcile a newer head with this plan instead of resetting to the inspected SHA.
2. Read local authority and the newest Handoff section, this plan, and only relevant code/test ranges. Verify `files/plans/` does not conflict with another local instruction.
3. Inventory root Python/packages, working ACT launch status, existing FFmpeg/ffprobe via the project's resolver, GPU/driver/free VRAM, cache locations and available disk. Do not launch an installer or synthesize as a side effect of detection.
4. Validate all six WAV hashes/headers and find likely transcripts. Check whether Chatterbox weights are already cached and whether the existing CUDA build actually supports this GPU.
   Also inventory the exact six Kokoro IDs, existing-vs-candidate registry status, American/British language prerequisites, model/voice caches and any missing asset downloads. Inspection must not auto-load a pipeline that fetches models.
5. Report the exact isolated-environment/package/model acquisition proposal, estimated new download bytes, proposed tracked paths, and any blocker. Record unresolved local facts as unresolved.

**Acceptance:** Sanitized preflight evidence under `files/dev-work/qwen3-eval/`; root environment/references unchanged; clear next checkpoint. If local facts match, CP2 can proceed under an explicit execution instruction without reopening settled product questions. Missing authority, wrong repo/branch, source-integrity failure or resource overrun is a concrete stop condition.

### CP2 — Isolated runtime and transcript preparation

1. Add the minimal environment preparation/worker scaffolding, exact dependency constraints and lazy opt-in entrypoint. Verify existing sample-generator CLI modes are unchanged and root tests can import the new development helpers without Qwen installed.
2. Create only the approved isolated environment; resolve/install the recorded compatible wheel set, run `pip check`, package/import probes and real CUDA tensor/SDPA probes. Confirm the root package inventory and production requirements remain unchanged.
3. Acquire only the pinned approved models/assets within the download budget, record revisions/hashes/licenses, and prove local snapshot loading. Load one large model at a time; record load and synthesis timing separately.
4. Reuse existing verified transcripts or generate the six draft transcripts locally. Present the review sheet. Independent preset work may continue, but reference-conditioned cloning waits for the applicable owner verification.
   Verify Kokoro's unchanged root environment and acquire only approved missing official model/voice assets within the allowance; do not tie Kokoro readiness to successful Qwen installation or transcript approval.

**Acceptance:** Reproducible isolated runtime with actual hardware proof, exact environment report, intact root environment/assets and a usable transcript review package. Technical compatibility is not claimed solely because installation completed.

### CP3 — Corpus, chunking, manifests and pilot; first Codex review

1. Finalize the canonical short/long corpus and identities without breaking existing corpus fixtures. Implement source-span chunk planning, native PCM assembly, decoding/measurement, durable results and safe cancellation/resume.
2. Add deterministic offline tests with fake synthesizers/audio: exact 27-row inventory; transcript/hash gating only for clones; input-span preservation; boundaries/oversized tokens; sample counts/rate/channel mismatches; empty/corrupt/failed chunks; failure/cancel reporting; resume identity mismatches; missing worker/environment; existing CLI isolation. Cover all six Kokoro IDs, `am_`/`bm_` language routing, speed 1.0, direct unregistered-candidate dispatch, root-interpreter selection, PCM capture and unchanged production registry/order/defaults. Kokoro failures must not erase successful Qwen/Chatterbox rows or block unrelated ready work.
3. Run the small real pilot, inspect its seams/content/cap headroom, record final common device/dtype/attention/chunk/join profiles, and verify offline preset/clone synthesis. Do not silently settle a model downgrade or major runtime change.
4. Have Codex independently review the diff, dependency isolation, source fidelity, effective defaults, chunk coverage/assembly, failure paths and tests. Claude fixes confirmed issues and reruns affected checks; no redundant full-suite loop.

**Acceptance:** Focused tests pass; pilot is technically usable; findings resolved or explicitly blocking. A complete dependency report and actual model revision/config are attached to the local run evidence. No production runtime/GUI change.

### CP4 — Full short suite and first owner listening gate

1. Generate all nine English Qwen presets, all six verified-transcript clones, all six current Chatterbox baselines and all six specified Kokoro voices with the frozen passage/profiles. Use sequential worker execution and retain per-row failures without losing the rest of the run. Kokoro uses the existing root engine and its own production chunking, not the Qwen worker runtime.
2. Persist the result after each chunk/recording as appropriate; retain technical retry attempts, reasons and seeds. Resume only identity-matching work. Do not overwrite previous evidence or cherry-pick a preferred random take.
3. Finish the listening index, paired clone/Chatterbox links, a labeled six-voice Kokoro section, duration/decode/peak/silence warnings and transcript/parameter provenance. Verify all 27 requested identities are accounted for and references/root environment are unchanged.
4. Ask the owner to listen and choose **one female preset and one clone** for the long tests, alongside Aiden and Dylan. Do not choose “best” automatically. Record the owner's exact selection in local `long-selection.json` and a concise sanitized Handoff decision.
   Separately collect retain/reject/defer feedback for each of the four new Kokoro candidates, using Michael/George as existing-voice comparisons. Record exact IDs in local listening decisions; listening feedback alone does not authorize GUI edits or require replacing either existing voice.

**Acceptance:** 27 truthful rows (nine Qwen presets + six Qwen clones + six Chatterbox baselines + six Kokoro voices); successful rows have play-ready artifacts, failures have precise reasons and retained diagnostics. Short listening may reject a voice despite clean measurements. **STOP Qwen long generation until the two selections arrive.** If no clone is usable, report the block and seek a bounded fallback/trial decision rather than substituting another preset. Kokoro registration remains unchanged until separate integration approval.

### CP5 — Four sustained recordings and independent closeout review

1. Generate the same frozen long passage for exactly the four approved voices. Keep reusable clone conditioning stable, record every chunk/span/join, and preserve complete native and encoded outputs.
2. Check text-plan coverage, chunk accounting, sample-count assembly, decoding, corruption, empty or skipped outputs, obvious silence/clipping and implausible duration. Provide join cue times and expose every warning; do not declare spoken word accuracy from a hash or duration alone.
3. The owner listens to sustained stability, start/end completeness, repeated names, paragraph/dialogue transitions, join artifacts and fatigue. Use the rubric below and timestamp defects. Optional local ASR can flag suspect omissions, but it cannot prove exact narration or overrule listening.
4. Codex independently reviews final changed code/tests and representative actual evidence, including a reference hash check and failed/interrupted-run behavior. Claude resolves confirmed defects and reruns only affected tests/artifacts, retaining old attempts.
   Include Kokoro asset/locale identity, six-row listening coverage and proof that candidate evaluation did not modify production registration or require a root dependency change.
5. Run the repository's actual full gate, `scripts/verify.py`, once at the evaluation closeout checkpoint, plus any focused checks justified by fixes. If it fails, report exact failures. Reproduce only implicated cases on a safe unchanged baseline where necessary; do not silently waive historical failures, weaken checks, or rerun two complete suites just to rediscover the same baseline failures.

**Acceptance:** Four complete sustained comparisons, or explicitly blocked rows requiring owner disposition; trustworthy manifests and listening feedback; independent review completed; reference/root integrity preserved; verification reported honestly. This reaches the final engine decision, not automatic integration.

### CP6 — Owner engine and Kokoro candidate decisions; hard production boundary

Record one of the following Qwen/Chatterbox decisions, the exact retained voices, and any requested additional trials. Record a separate add/reject/defer decision for each new Kokoro ID; rejecting Qwen does not reject Kokoro candidates automatically.

| Decision | Next action |
|---|---|
| A — Keep Chatterbox, reject Qwen for now | Preserve the evaluation evidence/tooling and document the Qwen decision. No Qwen integration; any separately approved Kokoro additions proceed only through their own bounded integration addendum. |
| B — Keep Chatterbox and add selected Qwen options | Prepare the bounded integration addendum below for the selected presets/clones and obtain approval before product changes. |
| C — Replace Chatterbox with selected Qwen clones/presets | Prepare the addendum, prove replacement and restoration, and obtain explicit archival/removal approval before moving or deleting anything. |
| D — Mixed choice or further trials | State exact scope: presets only, partial replacement, more comparisons, or defer. No inferred blanket permission. |

If B/C/D calls for product work, the addendum must define: registry labels/ordering and dispatch; optional isolated engine runtime/acquisition with informed size disclosures; supported Windows/macOS device/OS matrix and honest CPU fallback; retained engine compatibility; offline behavior; model/clone prompt identity; normalization/chunk/join policy; worker progress/pause/cancel/retry; settings/output preservation; packaging exclusions and help; regression/manual gates; rollback. Any final dependency/platform decisions not proven during evaluation must be resolved here. Do not route Qwen into the GUI just because a development worker exists.

For separately selected Kokoro candidates, create a small owner-approved integration slice for the exact chosen IDs only: registry labels/groups/order and neutral defaults, existing-engine dispatch, model/voice asset availability and supported-platform smoke tests, settings/default preservation, accurate user documentation and focused registry/UI regression tests. Reuse the existing Kokoro backend; do not introduce another backend or Qwen dependency. Preserve Michael, George and other existing entries unless the owner explicitly chooses a different change. Apply this slice even if Qwen decision A is selected; conversely, approval to integrate Qwen does not implicitly approve all four Kokoro candidates.

For an authorized Chatterbox retirement, verify the existing local `files/archived-code-folder` location and its EPUB archive before designing any move. It is not verified on GitHub. If absent/different, ask rather than inventing/recreating an archive. Preserve code, dependency restoration instructions, source/conditional provenance and existing unrelated contents; do not publish private archives. Removal needs a tested restoration plan and explicit owner approval.

**Plan 01 closes only when the owner's chosen Qwen/Chatterbox outcome and separate Kokoro candidate decisions are implemented to their approved scope, reviewed, accurately documented and committed/pushed to this feature branch.** If all additions are deferred/rejected, it can close without GUI work. Any requested Qwen or Kokoro integration cannot be called complete at the sampling gate. Then refresh the actual branch and refine Plan 02 from that state; do not execute the old bootstrap skeleton unchanged.

## 7. Local artifacts and evidence contract

Use `files/dev-work/qwen3-eval/` for ignored environment, caches, reports and run outputs. Prefer this existing ignored area over adding another generated-output rule. Keep the plan and useful repeatable development code/constraints/tests tracked; large environments, wheels, recordings, transcripts, clone-prompt tensors, caches and run manifests stay local.

Suggested organization: `.venv/`, `cache/`, `temp/`, `environment/`, and `runs/<run-id>/` containing `corpus/`, `references/`, `presets/`, `qwen-clones/`, `chatterbox-baselines/`, `kokoro/`, `long-form/`, `chunks/`, `manifest.jsonl`, `manifest.md`, `README-listen-first.md`, `long-selection.json` and listening notes. Names can follow existing conventions, but identities and containment are mandatory. Never put absolute home paths/usernames into tracked documentation.

Use explicit statuses such as pending, blocked, running, succeeded, failed, canceled and needs-listening. Write manifests atomically and persist progress so interruption does not erase completed evidence. A partially completed file must not appear as a successful complete sample. Resume requires matching model/package revision, source/reference/transcript/corpus hashes, generation/seed/chunk/join profile and output validation; otherwise create a new run/attempt.

Per recording/chunk, record as applicable:

- Run/attempt/row ID; git SHA and relevant dirty-state/content identity; engine, model ID and immutable revision; package/interpreter versions; speaker identity and cloning mode.
- For Kokoro: exact voice ID, existing-vs-new-candidate status, model and per-voice asset hashes/revision, American/British `lang_code`, neutral speed 1.0 and actual root-runtime/device profile. Cloning mode and reference-transcript fields are not applicable; do not fabricate them.
- Canonical passage hash/counts; ordered source spans and effective normalized chunk text/hash; chunk count, join type/time and inserted sample counts.
- Reference repo-relative path/hash/properties; transcript hash/source/verification state; clone-prompt provenance. Keep full transcripts local.
- Effective sampling/subtalker/generation-cap settings; seed policy; device, dtype and attention implementation; actual output sample rate/channels/format.
- Relative output paths/hashes; decoded duration and audible-content estimate excluding inserted silence; generation/load/encode wall times separately; real-time factor; peak allocated/reserved GPU memory when supported, otherwise unavailable with reason. Synchronize CUDA around timed work and reset peak counters for the stated measurement interval; distinguish cold load from warm generation.
- Decode result, amplitude/clipping/silence/duration warnings; completed/expected chunks; status, exception/error reason and retained retry history. Do not equate a duration heuristic with absence of missing spoken words.

The listening index must have relative clickable audio links, a concise inventory, paired comparisons, a labeled six-voice Kokoro section and plain instructions to open locally. Include a 1–5 rubric for pleasantness, clarity, natural pacing, stable narrator identity, repeated-name pronunciation, dialogue, clone similarity where applicable, joins and long-session fatigue where tested, plus timestamped omissions/repetitions. Show technical warnings separately from human judgments. Kokoro short-sample decisions must not be represented as passed ten-minute fatigue tests.

## 8. Proposed operator interface and verification commands

The `--qwen-eval` interface below is **a requirement to add**, not an existing branch capability. Keep ordinary sample generation and its existing flags unchanged. Use one explicit stage per command so a missing listening decision cannot be bypassed by an “all” mode.

| Proposed stage | Behavior |
|---|---|
| `--qwen-eval preflight` | Detection/reporting only, including the six-voice Kokoro inventory/prerequisites; no installs, downloads or synthesis. |
| `--qwen-eval prepare` | Prepare only the approved isolated environment and pinned assets after dependency/resource checks. |
| `--qwen-eval transcribe` | Reuse verified transcripts or create local drafts for owner review. |
| `--qwen-eval pilot` | Small technical/corpus/chunk calibration; requires verified transcript for clone pilot. |
| `--qwen-eval short` | Explicit 27-row short suite, including six Kokoro voices through the existing engine, with per-engine prerequisite gating and resumable evidence. |
| `--qwen-eval long` | Only four voices from the recorded owner selection. |
| `--qwen-eval report` | Rebuild indexes/read evidence without loading/downloading models. |

Keep this existing proposed stage name if convenient; it now orchestrates all specified comparison groups. Provide a dev-only group selector such as `--eval-group kokoro` so the six Kokoro samples can run from a ready root environment without requiring Qwen packages, models or transcripts. Predeclare all requested rows in a combined run and retain independent blocked/pending states. Group filtering must not change production voice selection or imply that unattempted groups passed.

Provide a stable run selector such as `--eval-run <run-id>`. No flag should silently download extra models or authorize integration. Validate the implemented CLI with `--help` and focused tests before supplying commands to the owner. Example **PowerShell** invocation once implemented, run from repository root:

```powershell
& .\.venv\Scripts\python.exe .\scripts\Universal\tts\generate_voice_samples.py --qwen-eval preflight --eval-run qwen3-initial
```

Use the existing root interpreter for offline repository tests, for example a newly added focused module under `files/tests/`, then the actual full checkpoint gate:

```powershell
& .\.venv\Scripts\python.exe -m pytest files/tests/test_qwen_evaluation.py -q
& .\.venv\Scripts\python.exe scripts/verify.py
```

The focused module name is proposed and must match the actual implementation. For each environment run `python -m pip check` through that environment's absolute interpreter. Never use an unqualified `pip`, invoke global installation, or imply these checks ran in this planning session.

## 9. Failure handling, rollback and reporting

- Missing environment/dependency/FFmpeg/model/transcript: give an actionable blocked status. Do not auto-repair the root production stack or fetch unapproved assets.
- CUDA/VRAM failure: release the worker, capture profile/error and propose the smallest supported change. Sequential batch-one execution and a smaller uniformly applied chunk profile may be tried with recorded evidence; no silent CPU/0.6B/quantized substitution for Qwen quality comparisons.
- Generation defect: preserve the failed chunk/attempt and stop publication of that row; continue independent rows where safe. Detect the production Chatterbox path skipping empty chunks rather than labeling partial narration complete. Do not expand into an unrelated engine repair without a bounded follow-up.
- Kokoro asset/language/runtime failure: name the exact voice and missing prerequisite, retain its failed/blocked row and continue other ready voices. Do not substitute Michael for a failed new voice, force British voices into American routing, auto-register a candidate, or let a Qwen dependency block invalidate completed Kokoro evidence.
- Cancel/interruption: stop between chunks, retain completed evidence and explicit incomplete status. Forced worker termination, if needed, must not leave a published successful row or an orphan GPU process.
- Recovery: deactivate/stop using the evaluation interpreter; production remains usable. Do not delete models, evidence or environments automatically. Correct tracked changes with scoped commits, preserving unrelated work; no destructive Git cleanup or broad environment deletion.
- Verification: full pass is required for an unqualified completion claim. Known baseline failures may be described and evidenced, never converted into an implied waiver. An owner may explicitly accept a bounded checkpoint with documented baseline failures; record that ruling rather than assuming earlier exceptions apply.

Before a checkpoint commit, inspect the staged diff for scope, private paths/transcripts, generated media, weights and other large binaries. Commit/push only verified task files to the expected origin working branch under `AI-WORKSPACE.md`; never force-push, merge/push `master`, amend pushed history, tag, release or delete remote branches without explicit approval. A read-only checkpoint with no tracked change does not need an empty commit.

Handoff updates should be a short newest-first snapshot: machine/date, branch, last actual verification, pending transcript/listening gate, unresolved issue and next exact action. Preserve historical records; do not rewrite megabytes of old documents. A commit cannot contain its own SHA: resolve it after committing and include it in the report.

Every checkpoint report states repository/branch/pushed SHA (or why not pushed), changed paths/behavior, commands and actual outcomes, local evidence location, unverified facts, owner action if blocking, and next bounded checkpoint. Recommend KEEP/COMPACT/FRESH based on actual remaining work; do not invent CLI commands for unverified tool versions. Supply one short copy-ready prompt for the next approved slice.

## 10. Done when

- The actual local environment is proven compatible and isolated; existing ACT requirements, reference bytes, GUI and retained engines remain intact during evaluation.
- All 27 short attempts are accounted for: nine Qwen presets, six Qwen clones, six current Chatterbox baselines and the exact six Kokoro voices. Statuses are honest and successful rows have play-ready files; material missing outputs are owner-dispositioned rather than concealed.
- Four owner-selected long comparisons expose complete planned text/chunks and joins, and the owner has heard the evidence needed for the final engine decision.
- Codex reviews and relevant automated/manual checks are complete, confirmed findings are resolved, and any required failure/manual limitation is explicit.
- The Qwen/Chatterbox decision and separate per-candidate Kokoro decisions are recorded; any chosen production integration/removal is separately approved, implemented and verified before calling that outcome finished. Four Kokoro candidates remain evaluation-only until selected; Michael/George remain existing ACT voices.
- Useful tooling/tests/constraints and lasting decisions are in the repository, the concise Handoff points to the next task, and verified checkpoints are committed/pushed on the exact feature branch. The temporary plan may be retired only after lasting facts are preserved and the owner's chosen outcome is closed; do not delete it prematurely at the first listening gate.
- Plan 02 is still an independent later planning task based on the final committed Plan 01 branch state. No release or merge is implied.

## 11. Research references and limits

Checked 2026-10-15. No installation, synthesis, tests, model download or Git mutation was performed by the planning chat. Local compatibility, timings, transcript presence and free resources require CP1–CP3 proof.

- [ACT inspected branch](https://github.com/elmatthe/audiobook-creation-tool/tree/f2ccf82bd41529f2e5737852da7592c6d6d7274f); [requirements](https://github.com/elmatthe/audiobook-creation-tool/blob/f2ccf82bd41529f2e5737852da7592c6d6d7274f/scripts/requirements.txt); [sample harness](https://github.com/elmatthe/audiobook-creation-tool/blob/f2ccf82bd41529f2e5737852da7592c6d6d7274f/scripts/Universal/tts/generate_voice_samples.py); [Chatterbox engine](https://github.com/elmatthe/audiobook-creation-tool/blob/f2ccf82bd41529f2e5737852da7592c6d6d7274f/scripts/Universal/tts/chatterbox_synth.py); [corpus](https://github.com/elmatthe/audiobook-creation-tool/blob/f2ccf82bd41529f2e5737852da7592c6d6d7274f/scripts/Universal/tts/quality_corpus.py).
- [ACT documentation contract tests](https://github.com/elmatthe/audiobook-creation-tool/blob/f2ccf82bd41529f2e5737852da7592c6d6d7274f/files/tests/test_repository_contract.py); [latest committed Handoff additions](https://github.com/elmatthe/audiobook-creation-tool/commit/f2ccf82bd41529f2e5737852da7592c6d6d7274f).
- [Kokoro extension branch head](https://github.com/elmatthe/audiobook-creation-tool/commit/267571181c0ee85a229fb39c9567d24ab1f08f32); [existing Kokoro engine](https://github.com/elmatthe/audiobook-creation-tool/blob/267571181c0ee85a229fb39c9567d24ab1f08f32/scripts/Universal/tts/kokoro_synth.py); [existing voice registry](https://github.com/elmatthe/audiobook-creation-tool/blob/267571181c0ee85a229fb39c9567d24ab1f08f32/scripts/Universal/tts/voice_registry.py); [official Kokoro voice assets](https://huggingface.co/hexgrad/Kokoro-82M/tree/main/voices). Asset presence is verified remotely; actual installed-runtime synthesis remains a local execution gate.
- [Qwen official README](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/README.md); [package metadata](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/pyproject.toml); [inference wrapper](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py); [model loader/attention implementation](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/core/models/modeling_qwen3_tts.py); [published package candidate](https://pypi.org/project/qwen-tts/0.1.1/).
- [CustomVoice model/files/license](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/tree/main); [Base model/files/license](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/tree/main). Resolve immutable model revisions locally before downloading; live `main` links are discovery references, not a lockfile.
- [PyTorch Blackwell support](https://pytorch.org/blog/pytorch-2-7/); [official matching wheel versions](https://pytorch.org/get-started/previous-versions/).
- [Transformers 4.57.3 Whisper API](https://huggingface.co/docs/transformers/v4.57.3/en/model_doc/whisper); [OpenAI Whisper small.en model/files](https://huggingface.co/openai/whisper-small.en/tree/main). ASR provides draft evidence; owner verification remains required.
