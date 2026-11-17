# Audiobook Creation Tool — Apple Silicon macOS Compatibility and Native Verification

**Master implementation plan | Phase 0 deliverable (research, architecture and roadmap only) | NOT an authorization to implement**
**Planning date:** 2026-11-14 (Claude Code, Opus 5.5, xHigh reasoning; Phase 0 session on the owner's Apple Silicon MacBook)
**Revision 1:** 2026-11-15 (Claude Code, Opus 5.5; documents only), amended in place on `389f56e`. Nine engineering corrections are written into the contracts, phases, tests, risks and decisions where they apply:
- preemptible Cancel for active inference (§11.2.1);
- parent-death containment for every ACT-owned child (§11.2.2);
- native macOS acceptance coverage and a mandatory extracted fresh-install qualification (§14.3);
- the release order: release source final before review, then both gates on one SHA (§16–§19);
- clean-install evidence classes (§8.2, §14.2);
- the FFmpeg 9.0.1 pin procedure (§11.1);
- per-engine owner decisions after a failed gate (D7);
- per-engine provisional budgets and four separate qualification verdicts (§15, D6);
- Git working-tree and local-guidance rules (§3.1).
**Revision 2:** 2026-11-16 (Claude Code, Opus 5.5; documents only, at `d6f21f9`). The owner's final decisions for this development checkpoint are written into the objectives, phases and decisions. This is an explicit owner-approved Mac scope change, not an acceptance of anything:
- **Q1=A:** OmniVoice gets one bounded technical feasibility campaign (P4A, moved before P3A/P3B). If it proves impractical or unreliable, or the owner rejects its audio, its macOS integration is abandoned.
- **Q2=A:** when the fallback is active, engines that are not supported on macOS are removed completely from the macOS user-facing experience. Shared Windows code, existing assets, voice identities and base dependency pins are kept (§12.F, P4C).
- **Q3=A:** the macOS implementation is finished and verified while HOME-PC is unavailable. Mandatory native Windows verification (E-B2, the Windows focused regression) and the final cross-platform release qualification are deferred until HOME-PC is available. They are not waived.
- **Consequences:**
  - P3A and P3B are **SKIPPED BY OWNER DECISION** on macOS (§19).
  - Chatterbox and Qwen3 are not implemented on macOS, even if OmniVoice succeeds, without new owner authorization.
  - The final macOS and Windows gates on one SHA (O5, O6, P7) stay mandatory.
**Revision 3:** 2026-11-16 (Claude Code, Opus 5.5). **P4A OWNER ACCEPTED** (Decisions, 2026-11-16 P4A acceptance entry):
- all six OmniVoice voices accepted by the owner's listening; an independent Codex review found bounded encoded-audio integrity PASS (not full-product verification);
- MPS fp32 preferred and default, its speed exception accepted for integration; CPU fp32 a selectable alternative; MPS fp16 experimental only;
- P4B authorized; the final macOS roster is fixed at **Edge 5 + Kokoro 9 + OmniVoice 6 = 20 voices** (P4C);
- six OmniVoice previews are added to the final release (P6a), the 28 historical previews unchanged.
**Revision 3a:** 2026-11-16 (Claude Code, Opus 5.5). **P4B implemented and verified: TECHNICAL PASS (F, S), one PERFORMANCE EXCEPTION — OWNER DECISION PENDING** (memory growth inside one worker, bounded by the 48-chunk restart). The P4B checkpoint waits for the owner; P4C has not started (§19 P4B status; Decisions, P4B entry).
**Revision 3b:** 2026-11-16 (Claude Code, Opus 5.5). **P4B memory checkpoint:** P4B is not owner accepted while the memory growth is open. The investigation found that on the Mac's GPU the growth is PyTorch's MPS caching allocator keeping GPU buffers, plus per-shape MPSGraph caches. One book-like text drove a 48-chunk worker to 13.6 GB, with memory pressure and swap. A Mac-GPU worker bound of 16 chunks was implemented and verified: peak 10.7 GB, no pressure, no swap, bit-identical audio. Windows and the Mac's CPU keep 48. The peak and growth targets are still missed: **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**, reduced, not closed (§19 P4B memory checkpoint; Decisions, memory-checkpoint entry). P4C has not started.
**Revision 3c:** 2026-11-16 (Claude Code, Opus 5.5). **P4B option B (MPS cache clearing): feasibility only, no meaningful improvement.** `torch.mps.empty_cache()` every 4 chunks or above an 8 GiB footprint released a fixed 1–2 GB working space that the next chunk took back. Peaks and growth were unchanged within run-to-run noise, and one run peaked higher. The growth is GPU memory `empty_cache` cannot release, plus the MPSGraph CPU heap; this corrects 3b's "allocator-kept buffers". Recommendation: keep the 16-chunk bound and adopt no clearing. The exception stays **OWNER DECISION PENDING**; P4B is not owner accepted; P4C has not started (§19; Decisions, option-B entry).
**Revision 3d:** 2026-11-16 (the owner; recorded by Claude Code). **P4B OWNER ACCEPTED with its documented memory performance exception** (Decisions, P4B acceptance entry): the Mac-GPU worker keeps its 16-chunk bound, Windows CUDA and the Mac's CPU keep 48, and no `torch.mps.empty_cache()` policy is adopted. No further P4B memory optimization is authorized. The measured exception stays on record against the unchanged provisional D6-O targets: book-like text peaks at 10.7–11.1 GB (target ≤ 10 GiB) and worker growth is +20 to +31 % there, +10.6 % on the 60-chunk sequence (target < 10 %). The wrong cause wording ("GPU buffers kept by PyTorch's allocator") is corrected in the `MPS_CHUNKS_PER_WORKER` comment and the feature map; per-shape MPSGraph resources are the likely cause, inferred and not proven. P4C authorized.
**Revision 3e:** 2026-11-16 (Claude Code, Opus 5.5). **P4C IMPLEMENTED and TESTED (automated); owner acceptance pending.** One platform capability policy, `scripts/shared/engine_policy.py`, decides the voice engines from the real platform: macOS offers Edge 5 + Kokoro 9 + OmniVoice 6 = 20 voices, Chatterbox Turbo and Qwen3-TTS are absent from every macOS surface and refused at every dispatch, setup, repair and probe entry; Windows keeps all 34 and its five setup choices unchanged (§12.F status; §19 P4C status; Decisions, P4C entry). P5 has not started.
**Revision 3f:** 2026-11-16 (Claude Code, Opus 5.5). **P4C independent-review remediation; owner acceptance still pending.** The sample helper's `--quality-suite` and `--final-acceptance` could report a "0/0" success for a refused or empty selection, and mixed requests ran their offered part. All three pattern modes now check explicit patterns first: a Mac request naming a Chatterbox or Qwen3 voice is refused whole (exit 2), and an empty selection fails (exit 1). P4C's two acknowledged wording exceptions (incompatible Python naming Chatterbox; engine locks naming Qwen3) are closed where a Mac reaches them. Windows' words are unchanged (§19 P4C status; Decisions, P4C remediation entry). P5 has not started.
**Revision 3g:** 2026-11-16 (Claude Code, Opus 5.5). **The owner-authorized Kokoro acquisition stopped before any download.** The app's setup worker cannot start on a Mac: `python -m venv` makes `.venv/bin/python` a symlink, and `optional_setup_protocol.worker_launch` refuses links. The first-run setup and Install & Continue therefore cannot install an optional voice on macOS. This is a pre-existing defect; P2 and P4B installed in-process. All 11 pinned Kokoro files are still missing, `tts.kokoro-local` is still BLOCKED and the gate is still FAIL. A bounded fix needs the owner's authorization (§19 P4C status; Decisions, Kokoro-acquisition entry).
**Revision 3h:** 2026-11-16 (Claude Code, Opus 5.5). **Option A (owner-authorized): the setup worker now starts on a Mac; Kokoro acquired through the production installer; the Kokoro journey and the focused gate PASS.** `optional_setup_protocol.interpreter_problem` accepts, on POSIX only, the venv's own `.venv/bin/python` link when the whole chain is proved to be this copy's own:
- expected link names in `.venv/bin` or beside the bundled Python, at most 4 links;
- the chain ends at this copy's `files/runtime-data/python/bin/python3.12`;
- no linked folder on the way;
- this account's ownership, and no group or world write on what holds the chain;
- `pyvenv.cfg` names this copy, isolation and 3.12.

`worker_launch`, the worker's own check (`worker_home_problem`) and the spaCy pip step use it. Windows' rule and `venv_layout.unsafe_component` are unchanged. The 11 pinned `KOKORO_FILES` were installed by `client.plan`/`install` through the real, contained worker and verified 11/11 by size and SHA-256. The gate reads `RESULT: PASS` (§19 P4C status; Decisions, Option A entry). P4C owner acceptance is pending; P5 has not started.
**Revision 3i:** 2026-11-17 (the owner; recorded by Claude Code). **P4C OWNER ACCEPTED** (Decisions, P4C acceptance entry). The owner's checks on HOME-MacOS:
- exactly 20 macOS voices (Edge 5, Kokoro 9, OmniVoice 6), and no Chatterbox Turbo or Qwen3 voice;
- the first run shows Kokoro checked and OmniVoice unchecked, and no other optional choice;
- Kokoro Heart, and OmniVoice Male 1 on MPS float32, generated MP3s from the GUI;
- OmniVoice Male 3 was cancelled during narration in 2.303 s, with no incomplete MP3 published;
- the Preferences & Data wording was accepted.

The passing focused gate `2026-11-16_234204_focused_4cf5` is kept. This is not an approval to merge or release. Only the bounded P5-A checkpoint is authorized.
**Revision 3j:** 2026-11-17 (Claude Code, Opus 5.5). **P5-A IMPLEMENTED and TESTED (automated, this Mac); independent review and owner approval pending.**
- **A. Containment.** On POSIX the setup worker is never reaped before its process group is ended. The group is signalled only while its id is proved to be the worker's own (`child_ownership.end_led_group`, §11.2.2). A grandchild left by a worker that exited now ends with the run. Mac containment of the setup worker's group: PASS (automated, native).
- **B. Interpreter.** `pyvenv.cfg` `executable` is required, absolute and exactly this copy's `python3.12`, and `home` must be absolute.
- **C. Permissions.** The checkout's world-writable modes were audited read-only. Any correction is an owner decision, and the security issue is not closed.
- **Gate:** focused gate `2026-11-17_053703_focused_61f2` **PASS**.
- **Still PENDING:** the Windows-native regression (HOME-PC) and the rest of P5 (§19 P5-A status; Decisions, P5-A entry).
**Revision 3k:** 2026-11-17 (Claude Code, Opus 5.5). **P5-A-R1 (independent-review remediation): on POSIX a setup run whose worker's process group was not confirmed ended is never a success.** Before, a worker's own `succeeded` was returned even when its group was `unproved` or `remaining`, and a Cancel with unconfirmed cleanup was a clean `cancelled`. Now such a run fails, `forced`, as `containment-unproved` (identity not proved, nothing signalled) or `containment-incomplete` (signalled, emptiness not confirmed, including Linux's `signalled`). The message keeps the original outcome, `verified` is kept, and the worker's own result file is never replaced. Only `shared/optional_setup_protocol.py` changed; `child_ownership`, `GROUP_ENDED` outcomes and the Windows Job Object path are unchanged.
- **Gate:** focused gate `2026-11-17_082412_focused_5388` **RESULT: PASS**, exit 0 (9/9 journeys including `tts.kokoro-local`, Cancel and both shutdown journeys; pytest 116/116; process-ownership, cleanup, skips and tree PASS). Protected assets and draft release `447445728` unchanged.
- **Still PENDING:** independent re-review and owner approval of P5-A, the owner's permissions decision, the Windows-native regression (HOME-PC) and the rest of P5. P5-B has not started (§19 P5-A-R1 status; Decisions, P5-A-R1 entry).
**Revision 3l:** 2026-11-17 (Claude Code, Opus 5.5). **P5-B: on POSIX the first-run setup window owns the optional-setup workers it starts.** Before (reproduced at `a88f3fb` with real processes), that window never made setup a containment owner. So its worker, pip and probes led sessions of their own with no lifeline: a forced Cancel or time-out left pip's helper running, and closing the window, SIGKILL or a crash of setup left the worker, pip and the helper running. Now `optional_phase` makes setup's own P1A owner the containment owner before the panel's first check (`bootstrap.own_optional_setup`), as the app window does. Once the window has closed, `bootstrap.settle_optional_setup` starts nothing new, lets each run end and reap its own worker first (P5-A order, R1 outcomes; bounded at 30 s), and then runs the orderly end. Only `shared/bootstrap.py` changed; `WorkerRun`, `child_ownership`, the app window's Install & Continue and Windows are unchanged.
- **Gate:** focused gate `2026-11-17_174054_focused_060c` **RESULT: PASS**, exit 0 (9/9 journeys including `tts.kokoro-local`, Cancel and both shutdown journeys; pytest 143 passed, 2 policy-named skips, 0 failed; process-ownership, cleanup, skips and tree PASS). Protected assets and draft release `447445728` unchanged.
- **Still PENDING:** independent review of P5-B; owner approval of P5-A, P5-A-R1 and P5-B (recommended for bounded acceptance, not approved); the owner's permissions decision; the Windows-native regression (HOME-PC); the rest of P5. Recommended next checkpoint: the inherited normal-exit gap (a pip or probe that exits leaving a helper in its own group) on both windows and in the base install (§19 P5-B status; Decisions, P5-B entry).

**Repository:** https://github.com/elmatthe/audiobook-creation-tool
**Working branch:** `feature/0.8.0-macos-compatibility`, created in Phase 0 at `9554bc8461ae00c4b7308f74d989fc0c8cfb9c90` (= `master` = `origin/master`)
**Released baseline:** Windows v0.8.0, tag `v0.8.0` (tag object `0a3653e`) → release-source commit `d1701e987f106ce00f557f267a6761c5370f5968`
**Integration target:** `master` (only on explicit owner approval, never in Phase 0)
**Last published macOS archive:** `AudiobookTool-MacOS-v0.6.6.zip` (GitHub release v0.6.6, 2026-09-30). No macOS asset exists for v0.7.x or v0.8.0.
**Intended owner outcome:** download/extract the app on an Apple Silicon Mac, double-click `Setup_and_Run-audiobook-creation-tool.command`, answer simple prompts, reach the same six-tool app, and create the same audiobooks with every voice that can be **proven** on the Mac, with no regression to the released Windows behaviour.

> **Status vocabulary used throughout.** **PROVEN** = demonstrated by this plan's own evidence on this Mac (Phase 0 proves only read-only facts: interpreter probes, hashes, PyPI metadata). **SUPPORTED UPSTREAM** = an official upstream source documents or contains the code path; nothing run here. **PLAUSIBLE BUT UNVERIFIED** = no blocker found, but no trustworthy run on comparable hardware/software. **REPORTED** = a third-party report that has not been checked here (always paired with another status). **BLOCKED** = a concrete defect or missing capability prevents it today. **UNSUPPORTED** = deliberately not offered. *Nothing about any TTS engine is PROVEN on this Mac in Phase 0: no environment was created, no model was downloaded, nothing was synthesized.*
>
> **Delivery status vocabulary (Revision 2).** Each feature and engine is reported in one of these states, never a looser word:
> - **IMPLEMENTED:** the functionality exists.
> - **TESTED:** identified evidence supports it, named with its run.
> - **OWNER ACCEPTED:** the owner explicitly approved it.
> - **BLOCKED:** a prerequisite or the evidence is unavailable.
> - **SKIPPED BY OWNER DECISION:** deliberately removed from the Mac scope. It is not PASS and not a technical FAIL.
> - **RELEASE READY:** only after every required final gate (P7).
>
> Until HOME-PC is available, the Mac implementation can reach IMPLEMENTATION COMPLETE at most. Its final release qualification stays PENDING, and it is never called released.

---

## 1. Executive summary and final objectives

**Verdict of the research.** Native Apple Silicon support for all six tools and all five engine families looks *technically feasible*, but two of the five engine families depend on device-level behaviour that only a measured experiment can settle. The dependency side is far better than expected. Every exact version pinned in ACT's three Windows lock sets has a CPython 3.12 macOS arm64 wheel or a pure-Python wheel on PyPI. That covers the app environment (170 packages), Qwen3 (89) and OmniVoice (88), including torch 2.6.0, 2.8.0 and 2.10.0 (§7). The real work is ACT's own Windows-only plumbing and the device choices for the local engines:

1. **Setup and launcher (BLOCKED for a fresh Mac today).** Windows gets its own pinned, hash-verified Python (python-build-standalone 3.12.15+20261009) inside the app folder. The macOS launcher instead scavenges any `python3.12/3.11/python3` on PATH and installs Homebrew via an unpinned `curl … HEAD/install.sh | bash` with the user's admin password. It then installs unpinned Homebrew `python@3.12` (whose Tk is now **9.0.3**) and FFmpeg. The base packages are installed from unhashed `==` pins, because the dependency lock only applies on `win32`. The matching macOS arm64 python-build-standalone asset exists for the *same* release tag (§8).
2. **Windows-only safety plumbing.** Several mechanisms have no macOS counterpart:
   - process containment (Job Objects, `stop_media_children`);
   - the machine-wide engine mutex (`Global\`, a no-op off Windows);
   - the Qwen3 installer's directory-pinning authority (`artifact_store.boundary`, which **fails closed** off Windows);
   - free-memory reading (`None` on macOS);
   - case-folding assumptions written as `os.name == "nt"`.

   Each needs a native POSIX/macOS design, not a "skip on mac" (§11). Two gaps are broader than plumbing:
   - **Cancel is not preemptive for Kokoro and Chatterbox.** They run inside the GUI process and check Cancel only between chunks; Chatterbox lets "a generation already in flight … finish". The standing rule (Decisions 2026-11-05) is "Cancel means stop, at once, everywhere". On a Mac CPU one chunk can take tens of seconds, so macOS runs active inference in a supervised worker process that Cancel can end at once (§11.2.1).
   - **Containment off Windows relies on orderly exit.** Nothing ends ACT's FFmpeg, pip or worker children when the GUI or setup process is SIGKILLed, crashes or is force-quit, and `atexit` cannot help in those cases. macOS gets an ownership and lifeline design (§11.2.2).
3. **GUI.** The aqua shell exists and has 39+ macOS-only layout tests that have not run on a Mac since v0.6.6. Gaps:
   - `::tk::mac::Quit` (Cmd+Q) is unhandled;
   - some fonts are hard-coded to Windows families;
   - Tk versions diverge. **Every no-admin Python route on macOS ships Tk 9.** Windows builds use Tk 8.6.15; python-build-standalone 20261009 builds macOS with Aqua Tk 9.0.4, and Homebrew with Tk 9.0.x. So a small, bounded **Tk 9 port** of ACT's GUI is required (§10). ACT's exposure is modest: no legacy `trace()` calls and no `~` paths handed to Tk. Three custom scroll handlers need `<TouchpadScroll>`.
4. **Engines.** Summary only; the evidence is in §6 and §12.
   - Edge: platform-neutral network engine.
   - Kokoro: CPU is already its only non-CUDA path; reliability first. On macOS it moves out of the GUI process into the supervised local-engine worker (§11.2.1).
   - Chatterbox Turbo: CPU by default, in the same worker. ACT's `select_device()` would pick MPS today, and MPS has open sampling and memory risks.
   - Qwen3-TTS: CPU float32 is the only Apple Silicon configuration with a controlled, reported comparison of correct speech. MPS has been reported badly wrong on torch 2.7. It is gated as Windows-only today.
   - OmniVoice 0.2.1: upstream documents MPS, and the code path is device-neutral. ACT's worker hard-refuses non-CUDA devices. There is conflicting MPS fp16 evidence on M4 hardware. CPU fp32 is plausible but slow.

   Qwen3 and OmniVoice therefore get **owner-gated feasibility experiments** before integration.
5. **Verification.** The canonical gate's skip policy exists only for `win32`, and its acceptance adapters are Windows-only. On macOS today every skip would be recorded as "NOT APPLICABLE, not judged". That is exactly how Windows-only skips could masquerade as a macOS pass. A `darwin` policy and macOS-native counterparts are required before any macOS result is trusted (§14, §17). The 55 required acceptance journeys are **not** exempted because their Windows input adapter does not apply: each gets a native macOS automated test, a documented owner-manual check, or a reviewed per-journey not-applicable reason (§14.3). The extracted fresh-install and repair qualification is mandatory.

**Final objectives (exit of the whole programme, P7):**
- O1. A fresh Apple Silicon Mac with no Homebrew and no compatible Python reaches a healthy app through the double-click launcher. It uses an app-owned, hash-verified arm64 Python and FFmpeg, gets explicit consent for every download, and needs no admin password. This is proven on a **real clean Mac** from the extracted release archive (D18). Evidence from this development Mac, where Homebrew is present but hidden, is labelled **SIMULATED** and never satisfies O1 by itself (§8.2, §14.2).
- O2. All six tools pass native macOS functional acceptance with real media, including Cancel, Pause, recovery and publication invariants. Cancel meets the bounded contract of §11.2.1 for every engine, including during active inference.
- O3. Each of the five engine families is either **PROVEN on this Mac** for its whole voice roster, or explicitly shown as unavailable with an accurate reason. Unavailable requires a separate owner decision for that engine, recorded after its failed gate (D7). No voice is silently removed, substituted or faked.
- O4. The 34 stable `(backend, voice_id)` identities, the 18 clone-reference WAVs, their transcripts, the 28 preview WAVs and the shared speech-preparation pipeline are byte-for-byte unchanged.
- O5. Windows v0.8.0 behaviour is preserved and re-verified on HOME-PC by the canonical Windows full gate on the **same final executable SHA** as the macOS gate (D8).
- O6. Steps run in this order:
  1. release source finalized: version identity, MacOS platform declarations and packaging support (P6a);
  2. one independent Codex review, its remediation and owner acceptance, which freeze the final executable SHA;
  3. **one** canonical native macOS full gate and one canonical Windows full gate, both on that SHA (P7).

  A failed gate is investigated, never rerun into a pass.
- O7. A release whose provenance is truthful:
  - the archives are built and audited from that same SHA with no source change;
  - no tag is moved;
  - no macOS binary is attributed to the Windows v0.8.0 commit (§18).
- O8. No ACT-owned child process outlives its owner after any exit, including a crash, SIGKILL, Force Quit or a closed Terminal window during setup. The only exceptions are the deliberately detached children named in §11.2.2.

**Revision 2 objective amendments (owner, 2026-11-16; Q1=A, Q2=A, Q3=A).** The goal is a reliable Mac edition, not the largest engine count.
- **O3 is replaced on macOS.** The Mac edition offers exactly the engines **PROVEN on this Mac and owner-accepted**, in this priority:
  1. Kokoro-82M, nine voices;
  2. Edge TTS, five voices;
  3. OmniVoice, six voices, only through an owner-accepted P4A configuration and P4B.

  Chatterbox Turbo and Qwen3 (CustomVoice and Voice Clone) are **SKIPPED BY OWNER DECISION** on macOS. Under the fallback, every engine not offered on macOS is absent from the macOS user-facing experience (§12.F), not shown as "visible but unavailable". Windows keeps the full released roster and behaviour. No voice is substituted.
- **O2** covers the six tools with the macOS engine roster above.
- **O4** is unchanged everywhere: the 34 identities, the 18 references, both transcript sets, the 28 previews and the shared speech preparation stay byte-for-byte. Nothing is deleted to slim the Mac edition, and no dormant dependency is removed from the shared environment.
- **O5 and O6** are unchanged. They are deferred, not waived, while HOME-PC is unavailable (Q3=A). The Windows phoneme comparison (E-B2) and the Windows focused regression run when HOME-PC returns, before the P6d freeze. Both full gates on one SHA (P7) stay mandatory.

**Revision 3 objective amendments (owner, 2026-11-16; P4A OWNER ACCEPTED).**
- **The macOS roster is fixed:** Edge TTS 5 + Kokoro-82M 9 + OmniVoice 6 = **20 voices**, OmniVoice on MPS fp32 by default and CPU fp32 by explicit choice (MPS fp16 not offered). Chatterbox Turbo and Qwen3 are absent from every macOS user-facing surface and refused by macOS dispatch (P4C). Windows keeps all 34.
- **O4, preview gallery:** the 28 historical previews stay byte-for-byte. Six OmniVoice previews are **added** in P6a (34 in the gallery). The gallery is separate from the runtime roster: Windows registers 34 voices, the Mac offers 20.

---

## 2. Actual MacBook hardware and software inventory (sanitized)

Collected read-only on 2026-11-14. Private detail (paths, usernames, exact PATH order, raw outputs) is kept in the gitignored `files/dev-work/macos-compat-p0/machine-inventory.local.md`, which is never staged.

| Item | Observed | Consequence for ACT |
|---|---|---|
| Machine | MacBook Pro, **Apple M4 Pro**: 14-core CPU (10 performance + 4 efficiency), **20-core GPU**, Metal support "Metal 4" | Real MPS hardware; CPU is strong for small models |
| Unified memory | **24 GB**, shared by CPU, GPU, app and OS | One local engine at a time. Qwen3 fp32 (~7.7 GB weights; a reported ~11 GB peak) plus a resident Chatterbox (~3–6 GB) plus the GUI risks memory pressure (§12, §15) |
| OS | **macOS 27.0.1** (build 26A434), Darwin 27.0.0 | Newer than any macOS on which PyTorch 2.6–2.10 was tested; MPS on macOS 27 is a stated risk (§6) |
| Architecture | Native **arm64** (`sysctl.proc_translated = 0`); **Rosetta 2 not installed** | Any x86_64-only binary fails outright, so wheels and binaries must be arm64/universal2 (§7 confirms they are) |
| Storage | APFS, **case-insensitive**; ~637 GiB free of 926 GiB | Ample for all engines (~20 GB with every model). Case-insensitivity matters for path identity (§11) |
| Display | Built-in Retina (3024×1964) | HiDPI scaling for Tk (§10) |
| Shells | `/bin/zsh` 5.9 (login); `/bin/bash` **3.2.57** (runs the `.command`) | Stage 0 must be bash-3.2-compatible. macOS has **no `timeout`** utility, so bounded probes need their own watchdog |
| Xcode Command Line Tools | Installed (clang 21.0.0, git 2.54.0) | Not required by the plan. Every pin has a wheel; the 3 sdist-only pins are pure Python |
| Homebrew | Installed (`/opt/homebrew`), 7.0.7 | Present on *this* Mac, but a non-technical user's Mac may not have it. It must not be a prerequisite (O1) |
| Python candidates | Homebrew 3.12.13 (**Tk 9.0.3**), Homebrew 3.13.7 (Tk 9.0.3), Homebrew 3.14.8 (**no tkinter**; it is `python3` on PATH), Apple CLT `/usr/bin/python3` 3.9.6 (**Tk 8.5.9**, Apple-controlled), and a dangling python.org 3.13 framework link | The current `.command` would pick Homebrew 3.12 with Tk 9 here. Elsewhere it could reach Apple's 3.9/Tk 8.5. Neither is an acceptable app runtime (§8). (Upstream note: python-build-standalone's macOS builds use Aqua Tk 9.0.4; the only Tk 8.6 option is the frozen, admin-only python.org 3.12.10 installer) |
| FFmpeg | Homebrew ffmpeg/ffprobe **9.0.1**, built with `--enable-audiotoolbox` (so `aac_at` exists) | Same FFmpeg version as the Windows pin (Gyan 9.0.1), but a different build. Byte-identity routes are qualified per build (§11) |
| Other | espeak 1.48 (classic, *not* espeak-ng) via Homebrew; no uv, pipx or conda | Kokoro uses `espeakng-loader`'s bundled library, so a system espeak is irrelevant (§6) |
| Metal/MPS | Metal 4 reported by `system_profiler`; MPS availability in torch cannot be tested without installing torch (not done in Phase 0) | MPS is *expected* available. Correctness per engine is unproven |
| GPU/memory telemetry without sudo | `ioreg -c IOAccelerator` → "Device Utilization %"; `/usr/bin/time -l` → max RSS and peak footprint; `vm_stat`; `memory_pressure` | Benchmarks need no `powermetrics`/sudo (§15) |
| Open files | launchd default soft `maxfiles` **256** (a shell started from Terminal or Finder inherits it); hard limit unlimited; `kern.maxfilesperproc` 92160 | Edge's ≤8 parallel files, FFmpeg pipes and staging files must be measured under 256, or the soft limit raised in-process (§11) |
| Temp | `tempfile.gettempdir()` is the per-user `/var/folders/...` | ACT's work area lives there. macOS purges it periodically. Crashed-run leftovers are only reclaimed by ACT on Windows (§11) |
| Agent tooling | Claude Code (Cursor terminal), Codex CLI and `gh` present | Codex is reserved for the independent review (§16) |

**Practical limits for long-form inference.** Kokoro on CPU is the low-risk path. Chatterbox Turbo on CPU is expected to be at or below real time (unmeasured). Qwen3 1.7B on CPU fp32 is expected to be *slower* than real time: one third-party report measured about 2.6× slower than real time on a base M4. OmniVoice is roughly real time on MPS if fp16 or fp32 proves correct, and about 3× slower on CPU (third-party figures). All of these are hypotheses for §15 to measure. None is a promise.

---

## 3. Git, repository state and source baseline

| Check | Result |
|---|---|
| Repository root and git dir | Repository root is the working folder; `.git` is a real directory; `git fsck --no-dangling` reports no problems |
| HEAD and branches | `master` = `origin/master` = `9554bc8` (0 ahead, 0 behind after `git fetch origin --no-prune`); `origin/feature/0.8.0-omnivoice-integration` = `9554bc8` |
| Remote | `origin` = `https://github.com/elmatthe/audiobook-creation-tool.git`; `git ls-remote` confirmed `master`, the feature branch and every tag |
| Tag and release | `v0.8.0` is annotated (`0a3653e`) → `d1701e9`. `v0.8.0..master` = one documents-only commit, `9554bc8`, which changes only `md-instructions/Handoff.md` (+44 lines). GitHub release v0.8.0 = `AudiobookTool-Windows-v0.8.0.zip` only (sha256 `e6b6929b…5b22`). `releases/latest` = v0.8.0 |
| Owner state (preserved, never staged) | 17 tracked deletions (12 under `files/plans/`, 5 under `files/release-history/`). Untracked: `.ai/`, `files/plans/archived-plans/` (which holds the v0.7.1/v0.7.2 plans, including the Windows hardening plan this roadmap cites), `files/release-history/ACT-v0.8.0-HOME-PC-Cleanup.md`, `files/run-temp/` (not ignored) and `scripts/project-status.py` |
| ZIP-transfer artefacts | <ul><li>Inherited Windows config: `core.filemode=false`, `core.symlinks=false`, `core.ignorecase=true`.</li><li>Every file is mode 0666/0777. The `.command` is **not executable** on disk, although the index records `100755` (hidden by `filemode=false`).</li><li>**221 tracked text files are CRLF** in the working tree (LF in the index; text=auto). The `.command` and the data JSONs are LF.</li><li>No tracked symlinks exist.</li><li>Four prunable worktree records point at Windows paths (not pruned).</li></ul> |
| Filesystem | APFS case-insensitive, which agrees with `core.ignorecase=true` |
| Immutable assets | All **18** clone-reference WAVs match `clone_references.json` SHA-256 and their committed blobs. All 12 Chatterbox/OmniVoice transcript hashes match. The 28 preview WAVs are tracked and unmodified (`git status` clean for them) |
| Transferred runtime state | No `.venv`, `files/bin`, models or wheel store came across. `files/runtime-data/` holds only `settings.json` (with a Windows-era `m4b_converter.input_dir`) and `optional-setup/` (Windows sessions and consents). macOS must treat both as foreign and harmless (MAC-029) |
| Feature branch | `feature/0.8.0-macos-compatibility` created at `9554bc8` with `git switch -c`. Before and after `git status --porcelain` were byte-identical, so no working-tree file was rewritten. The upstream is set when it is first pushed |

**Source baseline for the work.** The *code* baseline is `d1701e9` (the v0.8.0 tag). `9554bc8` differs from it only in the Handoff document, so branching from `master` is code-identical to the release.

**Checkout hygiene (owner decision D4).** This ZIP-transferred tree is usable for development: Python reads CRLF fine, and git does not report CRLF as modification. However, two kinds of output must come from a clean LF checkout created from the same commit, because CRLF bytes would otherwise end up in them:
- **release archives**, which `release.py` builds from the working tree;
- **the canonical full gate**, whose tree fingerprint and packaging checks read working-tree bytes.

The recommended clean checkout is `git worktree add files/dev-work/worktrees/<name> <sha>`. `files/dev-work/` is gitignored and excluded by `pytest.ini`.

### 3.1 Working-tree, Git-mode and local-guidance rules (D4, MAC-030, MAC-034, MAC-046)

**Leave the inherited settings and bytes alone.** `core.filemode=false`, `core.symlinks=false` and `core.ignorecase=true` stay as inherited, and so do the CRLF bytes of the 221 working-tree files. No phase does a broad cleanup. Specifically:
- no `git add --renormalize .`;
- no `git checkout -- .`, `git restore`, `git reset --hard` or `git clean`;
- no change to `core.autocrlf`, `core.eol` or `core.filemode`;
- no repository-wide `chmod`;
- no `git update-index --chmod` on existing files;
- no `git worktree prune` of the four Windows records without owner approval.

**Editing a CRLF file is safe as it is, but check which case applies.** `git ls-files --eol` (read 2026-11-15) shows two cases:
- **Index LF (`i/lf`) with CRLF or mixed working-tree bytes:** 225 files (221 CRLF, 4 mixed). `.gitattributes` has `* text=auto`, so Git normalizes them to LF on commit, and only real line changes enter the commit.
- **Index already mixed (`i/mixed`):** `md-instructions/Briefing.md`, `Decisions.md` and `Handoff.md`. Their committed bytes already contain CRLF lines, so Git does **not** convert them.
  - New lines follow the surrounding committed endings (the current top blocks are CRLF).
  - `git diff --check` then reports those CRs as trailing whitespace. That is the inherited state, not an error.
  - No phase normalizes these three files, because that would rewrite thousands of lines. Only a separate, owner-approved documents-only renormalization may do it.

Each phase checks this before committing:
- `git diff --cached --stat` lists only the intended files, with line counts matching the real edit;
- `git diff --cached --summary` shows no `mode change` lines except intended ones.

A file that would show whole-file churn is a stop: investigate, do not commit.

**New executable files need their Git mode set explicitly (MAC-046).** With `core.filemode=false`, `git add` records a new file as `100644` whatever its disk mode. A new script that must run directly (for example `scripts/shared/bootstrap_host_macos.sh`, or any new `.command`) is staged with `git add --chmod=+x <path>`. The phase then confirms `git ls-files -s <path>` shows `100755`. Rules for such files:
- `*.sh` and `*.command` are LF by `.gitattributes`, and new ones must stay LF;
- a focused test asserts the index mode and LF bytes of every launcher and stage-0 script, beside the existing release-packaging 0755 rule (`release._write_executable`);
- the disk-only `chmod +x` of the existing `.command` (D4) is invisible to Git and changes nothing in the index.

**Stale local agent guidance (MAC-034; owner file, not changed by any phase).** `.claude/CLAUDE.md` is local and gitignored (`.gitignore` covers `.claude/`). It still names paths that do not exist or have other names:
- `md-instructions/CHANGELOG.md`, `DECISIONS.md` and `handoff.md`: the real files are `Changelog.md`, `Decisions.md` and `Handoff.md`. They resolve only because this APFS volume is case-insensitive.
- `scripts/Universal/`: absent.
- `scripts/verify.py`: the gate is `files/dev-work/verification-gate/verify.py`.
- the `files/dev/qwen_worker.py` delegation route: absent.
- the v0.5.0 one-commit-per-drop rule: historical.

`AI-WORKSPACE.md` also points at an `AGENTS.md` that the repository does not have.

**Recommended reconciliation:** the owner edits `.claude/CLAUDE.md`, or authorizes a separate documents-only task to edit it, so that it points to `AI-WORKSPACE.md`, the four canonical documents with their real names, this plan and the real gate path, and drops the absent delegation route. Until then, agents follow the read order in §21 and treat the stale entries as non-authoritative. They never invoke the absent delegation script and never "fix" the file on their own.

---

## 4. Reusable Windows application architecture

The v0.8.0 code tree is single and cross-platform (`scripts/`), with `sys.platform` branches. These seams are reusable as-is or with narrow platform branches. "Reuse" means *keep the contract and the Windows code path byte-for-byte*; add a macOS branch beside it.

| Area | Module(s) | Reuse verdict |
|---|---|---|
| Launch brain | `scripts/shared/bootstrap.py` (4,246 lines): venv health (`--venv-check`), `--launch-only`, repair transaction, Kokoro/Chatterbox self-heal, FFmpeg proof, detached GUI launch with a captured log | **Reuse** the orchestration. Add a macOS app-owned Python (`APP_PYTHON` per platform), the macOS lock and the stage-0 handoff. Remove the Homebrew dependence from the default path |
| Windows stage 0 | `scripts/shared/bootstrap_host.ps1` (python-build-standalone, size + SHA-256, consent, staging, one rename, a bounded Tk proof) | **Mirror** it in `scripts/shared/bootstrap_host_macos.sh`, the canonical name in `.ai/BOOTSTRAP.md` |
| Package locks | `scripts/shared/base_packages.py`, `scripts/requirements-lock-windows-py312.txt`, `files/dev-tools/lock_base_requirements.py` | **Reuse** the hashed-store design. Make `lock_applies`/`lock_path` platform-keyed. Add `requirements-lock-macos-arm64-py312.txt` |
| Unified environments | `.venv/`, `.venv/engines/qwen3/`, `.venv/engines/omnivoice/`; `shared/venv_layout.py`, `shared/engine_lease.py` (already `fcntl.flock` on POSIX) | **Reuse** the layout (owner decision 2026-11-13). Engines are built at their final path, as on Windows |
| FFmpeg | `shared/ffmpeg_health.py` (discover → prove by execution → pin), `shared/ffmpeg_utils.py` (consumes only the proven pair; `aac_at` selection for xHE-AAC), `shared/ffmpeg_portable.py` (Windows source pin) | **Reuse** the health model. Add a macOS source pin (§11) |
| Subprocess control | `shared/subprocess_utils.py` (`run_supervised` terminate → kill through the handle, which works on POSIX), `tts/qwen3_process.py` (`start_new_session` + `killpg` on POSIX) | **Reuse** the supervision. Add the POSIX ownership layer of §11.2.2: an owned-child registry, lifelines, the ACT guardian and an identity-checked POSIX `stop_media_children` (MAC-009, MAC-044) |
| Output and publication | `shared/output_paths.py` (NFC, collisions; already treats darwin as case-insensitive), `tts/publication.py` (staging + `fsync` + `os.link` no-clobber on POSIX, `os.replace` for overwrite) | **Reuse**. Consider `renamex_np(RENAME_EXCL)` for non-APFS volumes (MAC-017) |
| Jobs | `shared/job_control.py`, `shared/job_ui.py`, `shared/cancellation.py` | **Reuse unchanged** (thread-based; no platform branches) |
| Optional engines | `tts/optional_setup*.py`, `shared/optional_setup_protocol.py`/`_panel.py`, `tts/voice_install.py`, per-engine `platform_supported()` gates | **Reuse** the consent, progress, Install & Continue and readiness flows. Change *gates* per engine only after proof |
| Speech preparation | `tts/speech/*` (`pipeline.prepare`, 16 classes, `modes.json`, glossary) | **Reuse unchanged**; it is pure Python (§13) |
| Engines | `tts/kokoro_synth.py`, `tts/chatterbox_synth.py` (both in-process; Cancel is checked only between chunks); `qwen3_*`, `omnivoice_*` (isolated worker processes) | Narrow device/dtype adapters (§12). On darwin, Kokoro and Chatterbox inference moves into a supervised local-engine worker (§11.2.1, MAC-043). The parent keeps speech preparation, chunking, assembly, the one encode and publication. Windows stays in-process (D17) |
| Packaging | `shared/release.py` already builds `AudiobookTool-MacOS-vX.Y.Z.zip` with a forced 0755 `.command` (`_write_executable`). The ordinary build is gated by `RELEASE_OS_NAMES = ("Windows",)` | **Reuse**. Enable MacOS in P6a, in the release-source finalization before review and the gates, with owner approval (D16). Never after the gates |
| Verification | `files/dev-work/verification-gate/` (`verify.py`, `verification.json`, `coverage.json`, `helpers/winproc.py` with a POSIX process-group branch), `files/dev-work/feature-map/` | **Reuse** the core. Add a `darwin` skip policy, a darwin preflight, a per-journey darwin acceptance map with native counterparts (§14.3) and the mandatory `fresh-macos` qualification. Keep Windows adapters untouched |

**What must not be assumed to carry over:** Windows-measured speed, memory or VRAM figures; the qualified FFmpeg build set (`m4b/m4b_continuous.QUALIFIED_BUILDS` holds only the Gyan Windows hashes); seeds reproducing Windows audio (RNG differs by device); and any Windows qualification scenario (`fresh_windows`, `winjob`, the Windows native-input adapter).

---

## 5. Six-tool macOS compatibility gap matrix

Gap IDs (`MAC-nnn`) are indexed in Appendix B. "Status" describes macOS today, from source inspection. None of these tools has run on this Mac in Phase 0.

| Concern | TTS Audiobook (`tts/epub2tts_gui.py`) | MP3 Tool (`mp3/`) | M4B Converter (`m4b/converter/`) | M4B Maker (`m4b/maker/`) | M4B Metadata Editor (`m4b/metadata/`) | Cover/Image Tool (`artwork/`) |
|---|---|---|---|---|---|---|
| Native GUI (aqua shell, layout) | Aqua branch exists (`_is_aqua`). Compact layout tests are aqua-only and unrun since v0.6.6 | Aqua layout tests exist (`test_mp3_tool_layout.py`), unrun | Shares the shell; unrun | `test_m4b_layout.py` aqua-only, unrun | Unrun | Unrun; custom canvas wheel handler |
| Fonts | Theme-driven | Theme-driven | Theme-driven | Theme-driven | Theme-driven | Theme-driven; `Consolas` mono in `appearance.py` (MAC-020) |
| Mouse wheel / trackpad | `ui_theme` sign-only `<MouseWheel>` (correct for Tk 8.6 deltas). Under Tk 9, trackpads emit `<TouchpadScroll>` (§10, MAC-007) | Same | Same | Same | Same | Own handler (`cover_resizer.py:1010`) |
| Shortcuts | `<Command-…>` used in places; Select-All uses `<Control-a>` in `job_ui` (MAC-037) | Same | Same | Same | Same | Already binds `<Command-a>`/`<Command-Button-1>` |
| File dialogs | `filedialog` with `*.*`, which works on NSOpenPanel. Multi-select must be verified | Same | `*.m4b` filter | `*.mp3` filter | Same | Image filetypes incl. HEIC |
| Unicode/NFD names | Inputs NFC-normalised in `importing.py`; outputs NFC (`output_paths`, `output_names`). APFS is normalization-insensitive. Needs an NFD fixture test (MAC-038) | Same | Same | Same | Same | Same |
| FFmpeg dependence | Encode (pydub/`disk_assembly`). darwin adds `-write_xing 0` for MP3 (MAC-019) | Heavy (concat/convert; Cancel via `run_supervised`) | Heavy. xHE-AAC via `aac_at` (needs an AudioToolbox build). The fast one-decode split route is qualified only for the Gyan Windows build, so macOS falls back to the slower safe route (MAC-006) | Heavy (encode, chapters, art; supervised) | Chapter-title remux (supervised) | None (Pillow) |
| Metadata/art deps | mutagen (pure) | mutagen | mutagen | mutagen + Pillow | mutagen | Pillow 12.2.0 and pillow-heif 1.5.0: arm64 wheels exist (§7) |
| Cancel / Pause | In-process Kokoro/Chatterbox check Cancel only **between** chunks, and a chunk already in flight finishes. On a Mac CPU that can take tens of seconds, which breaks the immediate-Cancel rule (MAC-043). macOS moves them into the local-engine worker that Cancel ends at once (§11.2.1). Workers: flag → kill the process group within a stated bound. Pause at the file boundary, unchanged | `run_supervised` SIGTERM → SIGKILL (POSIX OK) | Same | Same | Same | n/a (quick operations) |
| Window close / Cmd+Q / crash | `WM_DELETE_WINDOW` handled. **Cmd+Q unhandled** (MAC-008). Orphaned workers after a crash (MAC-009) | `stop_media_children` is Windows-only. Nothing contains FFmpeg after SIGKILL or a crash, so FFmpeg can outlive the app (MAC-009, MAC-044) | Same | Same | Same | n/a |
| Publication | `publication.py`: `os.link` no-clobber, which fails on exFAT/FAT/some SMB (MAC-017) | Roll-back cannot "take back" on macOS (`_CAN_TAKE_BACK`, documented degradation, MAC-018) | Same publication service | Same | In-place edit through a temp copy | Writes new files |
| Temp/recovery | Work area in `$TMPDIR`. Other processes' leftovers are reclaimed only on Windows (MAC-016) | Same | Same | Same | Same | n/a |
| Memory planning | `memory_info()` is `None` on macOS, so 4 GB/2 GB is assumed and the text says "kept for Windows" (MAC-011) | n/a | n/a | n/a | n/a | n/a |
| Finder reveal | `subprocess_utils._ask_file_manager` uses `open` on darwin (implemented) | Same | Same | Same | Same | Same |
| Drag and drop | Not implemented on any platform. **Not a parity gap; out of scope** | — | — | — | — | — |

**Launcher-wide.** `.command` and stage 0 (MAC-001…004, 036). Quarantine and Gatekeeper (MAC-003). The executable bit (MAC-002). The Terminal auto-close helper `shared/close_terminal.py` uses `osascript` to close its own window; whether it prompts for Automation consent must be confirmed by a manual test (MAC-039).

---

## 6. Five-engine feasibility matrix

Status is per configuration. Evidence links are in §7 and Appendix A. In this table, **REPORTED** means a third-party run that this plan has not reproduced.

| Engine (ACT pin) | Install on macOS arm64 / CPython 3.12 | CPU | MPS (Apple GPU) | CUDA-only assumptions in ACT today | Recommended Mac configuration *to be proven* | Overall status today |
|---|---|---|---|---|---|---|
| **A. Edge TTS** (edge-tts 7.3.1, 5 voices) | Pure wheel. TLS via `certifi.where()` (no Keychain dependence). Proxies via the system settings (`trust_env=True`; PAC files not handled). 7.3.0 shipped a macOS-only fix (#493) | n/a (network) | n/a | None | As Windows: up to `min(requested, ceiling, CPUs, memory)` files in parallel | **SUPPORTED UPSTREAM; PLAUSIBLE BUT UNVERIFIED on this Mac.** 7.3.1 (latest, 2026-10-13) fixed the October 403s. Open risks: intermittent `NoAudioReceived` (#512, still reported 2026-11-10) and the service-held voice list (en-GB voices were removed in Dec 2025, #451). The five en-US voices are PLAUSIBLE until P2 lists and synthesizes them |
| **B. Kokoro-82M** (kokoro 0.9.4, misaki 0.9.4, espeakng-loader 0.2.4, spaCy 3.8.16 + `en_core_web_sm` 3.8.0, torch 2.6.0; 9 voices) | All wheels exist. `espeakng_loader-0.2.4-py3-none-macosx_11_0_arm64.whl` bundles `libespeak-ng.dylib` 1.52 and its data. **eSpeak calls `exit(1)` if its data path is ≥ 160 characters** (espeakng-loader #10). ACT's `espeak_data.py` already makes a short symlink root on POSIX; this checkout's path would be 155 characters (MAC-035). misaki would pip-install `en_core_web_sm` at runtime if missing, which ACT prevents with its pinned wheel | **REPORTED** on M4 Pro CPU: ~17× faster than real time, 4.85 GB peak (model card; versions not stated). **REPORTED** kokoro 0.9.4 on macOS 27 with **torch 2.13** (kokoro#152). torch **2.6.0 on macOS 27: no report** | Not used by ACT (`cuda` else `cpu`). Upstream MPS support (PR #164) is unreleased. Needs `PYTORCH_ENABLE_MPS_FALLBACK` for `aten::angle`. **REPORTED** crashes on long strings and allocator growth (1.9 → 8.9 GB) without `empty_cache` | `kokoro_synth._local_model`: `cuda` else `cpu` (fine) | **CPU fp32** (owner priority: reliability + pronunciation), run in the supervised local-engine worker on darwin (§11.2.1). MPS not offered | **PLAUSIBLE BUT UNVERIFIED (strong).** The only open question is torch 2.6.0 on macOS 27 (P1A import proof, P2 synthesis) |
| **C. Chatterbox Turbo** (chatterbox-tts 0.1.7, torch 2.6.0, transformers 5.2.0, numpy 1.26.4, resemble-perth 1.0.1; 6 cloned voices) | All wheels exist (incl. `spacy_pkuseg-1.0.1-…-macosx_11_0_arm64`, `s3tokenizer`/`resemble_perth` pure). Turbo needs no libsox/FFmpeg from torchaudio (only `Resample` + `kaldi.fbank`; audio read by librosa) | **SUPPORTED UPSTREAM** (device-agnostic code: safetensors load to CPU, then `.to(device)`; no CUDA kernels, bf16, flash-attn or `torch.compile`). **PLAUSIBLE BUT UNVERIFIED** here. Upstream **does not claim** Turbo on Mac (README/CI: Linux/CUDA). Speed unknown: the original model reported ~0.34× real time on an M4 CPU; Turbo (350M params, 2-step decoder) should be faster [inference]. ~3.0 GB fp32 loaded | **PLAUSIBLE BUT UNVERIFIED, high risk:** torch 2.6 MPS `multinomial` can pick zero-probability tokens (pytorch#192577; silent); allocator growth on 24 GB machines (chatterbox#577: multilingual model reached 24.9 GB driver memory); macOS 27 MPSGraph argmax defect (pytorch#187280). The float64 crash (#499) probably avoided by numpy 1.26.4 [inference] | `select_device()` = cuda → **mps** → cpu, so **ACT would choose MPS on this Mac today** (MAC-023) | **CPU fp32 default on darwin**, in the supervised local-engine worker (§11.2.1); MPS only as an owner opt-in after the correctness oracle | **PLAUSIBLE BUT UNVERIFIED** (CPU) |
| **D1. Qwen3 CustomVoice** (qwen-tts 0.1.1, transformers 4.57.3, accelerate 1.12.0, torch 2.10.0; Aiden, Ryan) | All 89 pins have a Mac artefact (onnxruntime 1.31.0 `macosx_14_0_arm64`; `sox` = ACT's pure supply wheel; the SoX *binary* is not needed: pysox only logs "SoX could not be found!"). onnxruntime/sox are imported at module scope but used only by the unreleased 25 Hz tokenizer. **ACT's installer authority fails closed off Windows** (MAC-013) | **REPORTED** working on a base M4 (third-party audiobook project; torch 2.7, qwen-tts 0.1.1): 0.38 audio-s per wall-s (~2.6× slower than real time), 25/30 lines exact by ASR, 11.3 GB RSS. Second report on macOS 26 CPU fp32 | MPS **fp32 REPORTED badly wrong** on torch 2.7 (6/30 exact, mean WER 1.15, 16.5 GB driver allocation). MPS **bf16**: anecdotal "works", no quality data. **fp16: overflow → inf/NaN** (#355) | `choose_device`: cuda:0 or cpu; default dtype **bf16**; `platform_supported()` = win32 only; `MachineGuard` no-op off Windows | **CPU fp32, sdpa, one chunk at a time.** CPU bf16 / MPS bf16 only if they match CPU fp32 on WER and listening. Never fp16 | **PLAUSIBLE BUT UNVERIFIED (+ REPORTED on M4 CPU); installer BLOCKED (ACT-side).** Upstream has no official Mac path; Mac PRs #124/#345 unmerged; last commit 2026-03 |
| **D2. Qwen3 Voice Clone** (Base model; 6 cloned voices from the 18-reference set) | Same as D1 | The clone path is pure PyTorch (Mimi-based 12 Hz encoder, ECAPA-style speaker encoder, mel STFT on a CPU tensor, librosa/soxr resample). **PLAUSIBLE BUT UNVERIFIED** (no direct Apple CPU fp32 report; CPU **fp16** ran >20 min without finishing, #69) | Anecdotal (bf16 #69; MPS fp32 on 0.6B Base; PR #345 exits 0, no quality data) | As D1 | As D1, with the same reference WAV and transcript bytes | **PLAUSIBLE BUT UNVERIFIED; installer BLOCKED (ACT-side)** |
| **E. OmniVoice 0.2.1** (omnivoice 0.2.1 @ `5ba967c4`, transformers 5.3.0, torch 2.8.0; model `k2-fsa/OmniVoice` @ `c5fdb5cc`; 6 cloned voices) | Pure wheel, no native extensions, no CUDA-only dependencies (triton only on linux x86_64). **Upstream's own `uv.lock` resolves darwin to PyPI `torch==2.8.0`** ("CUDA doesn't exist for Mac"). ~86 Mac wheels, ~247 MB (vs 3.66 GB Windows) [summed, not resolved]. Offline load is platform-neutral (local dir with `audio_tokenizer/`, `ref_text` supplied → no Hub, no Whisper) | **SUPPORTED UPSTREAM** code path (`get_best_device` falls back to CPU; no CUDA calls in inference). **REPORTED** correct speech on Apple CPU (#8 on 0.1.1, #172), RTF ≈ 3 (slow). ~612M-param backbone (2.45 GB fp32) + ~201M-param tokenizer | **SUPPORTED UPSTREAM** (README documents Apple Silicon and `device_map="mps"`, fp16; code pins the audio tokenizer to CPU on MPS). **Conflicting REPORTS on M4:** #172 (Mac mini M4, torch 2.8.0) garbled audio + NaN with fp16+SDPA, where the maintainer's advice was fp32; #279 (M4 Max, 0.2.1, fp16) works, RTF ≈ 0.4. Memory growth across `generate()` calls (#199) is CUDA-reported, untested on MPS | Worker refuses `device != "cuda"`; `device_map="cuda:0"`, fp16; `torch.cuda.synchronize`/memory/seed calls; `platform_supported()` = win32; NVIDIA-only GPU probe and setup proof | Decided by the **P4A experiment**: MPS fp32 (likely candidate), MPS fp16 (only if oracle-clean), CPU fp32 (correct but ~3× slower than real time) | **PLAUSIBLE BUT UNVERIFIED; ACT-side BLOCKED** (CUDA-only worker). No configuration is proven on Apple Silicon; nothing upstream blocks it |

**Not acceptable as substitutes:** MLX ports exist for Kokoro-adjacent stacks, Qwen3-TTS (mlx-audio) and OmniVoice (mlx-audio, OmniVoice-MLX). They load *converted* weights with different hashes and numerics. Using one would change the engine's identity, so they are noted only as future, owner-decided alternatives and never as silent replacements.

**Revision 2 (2026-11-16) status of rows C, D1 and D2 on macOS:** **SKIPPED BY OWNER DECISION** (Q1=A, Q2=A). The research above is kept as the record; it is not a verdict on those engines. Row E is decided by the bounded P4A campaign (§12.E).

**MPS testing caveat.** PyTorch reports MPS as unavailable inside some agent sandboxes (pytorch#177819). Every MPS experiment must first assert `torch.backends.mps.is_available()` in its actual session. If the agent harness hides Metal, the owner runs the bounded experiment script from a normal Terminal window. An "MPS unavailable" result is BLOCKED, never a FAIL of the engine.

---

## 7. Dependency versions and upstream compatibility evidence

### 7.1 What ACT pins today (verified in the tree)

| Environment | Python | Key pins | Platform scope today |
|---|---|---|---|
| App `.venv` (`scripts/requirements.txt` + `requirements-lock-windows-py312.txt`, 170 packages, `--require-hashes`) | CPython 3.12 (`FULL_FEATURE` 3.11–3.12) | edge-tts 7.3.1, kokoro 0.9.4, misaki 0.9.4, espeakng-loader 0.2.4, spacy 3.8.16 (+ `en_core_web_sm` 3.8.0 wheel by URL and SHA-256), chatterbox-tts 0.1.7, **torch 2.6.0, torchaudio 2.6.0**, transformers 5.2.0, numpy 1.26.4, scipy 1.17.1, safetensors 0.5.3, resemble-perth 1.0.1, setuptools 80.9.0 (compatibility debt), mutagen 1.47.0, PyMuPDF 1.27.2.3, Pillow 12.2.0, pillow-heif 1.5.0, pydub 0.25.1, soundfile 0.13.1, nltk 3.9.4, pytest 9.1.1 | The lock applies only to `win32` + x86-64 + 3.12 (`base_packages.lock_applies`). Elsewhere, unhashed `==` pins |
| Qwen3 `.venv/engines/qwen3` (`scripts/qwen3-requirements.txt`, 89 packages, `--require-hashes --no-deps`, cu128 index) | 3.12 | qwen-tts 0.1.1, transformers 4.57.3, accelerate 1.12.0, **torch/torchaudio 2.10.0+cu128**, onnxruntime 1.31.0, sox 1.5.0 (sdist → ACT supply wheel `d7f2d5a2…`), librosa 1.0.0, numpy 2.5.4 | `win_amd64` only (`qwen3_package_manifest` accepts only `any`/`win_amd64`) |
| OmniVoice `.venv/engines/omnivoice` (`tts/omnivoice_manifest.json`, 88 wheels by URL, size and SHA-256) | 3.12 | omnivoice 0.2.1 (git `5ba967c4`), **torch/torchaudio 2.8.0+cu128**, transformers 5.3.0, accelerate 1.13.0; model `k2-fsa/OmniVoice` @ `c5fdb5cc` (11 files, 3.27 GB) | `engine.platform = win_amd64` |
| Models (platform-neutral pins) | — | Kokoro `hexgrad/Kokoro-82M` @ `f3ff3571`; Chatterbox `ResembleAI/chatterbox-turbo` @ `749d1c1a`; Qwen3 CustomVoice @ `0c0e3051` (4.52 GB), Base @ `fd4b2543` (4.54 GB), optional Whisper small.en @ `e8727524` (0.97 GB); OmniVoice @ `c5fdb5cc` | File hashes are platform-neutral, so **no model re-pinning is needed** |

### 7.2 macOS arm64 wheel availability at the *exact* pinned versions (PROVEN from PyPI metadata, 2026-11-14)

Method: the PyPI JSON API was queried for each `name==version` in the three Windows sets (the local version `+cu128` was stripped for torch). The script and its raw output are in the ignored `files/dev-work/macos-compat-p0/`. Nothing was downloaded.

| Set | Pins | cp312 macOS arm64 / universal2 wheel | Pure-Python wheel | sdist only | No macOS artifact |
|---|---|---|---|---|---|
| App (`requirements-lock-windows-py312.txt`) | 170 | 45 | 123 | 2: `antlr4-python3-runtime 4.9.3`, `docopt 0.6.2` (both pure Python; Windows builds them the same way via `base_packages.build_backends`) | **0** |
| Qwen3 | 89 | 25 | 63 | 1: `sox 1.5.0` (ACT's own pure `py3-none-any` supply wheel is reusable) | **0** |
| OmniVoice | 88 | 25 | 63 | 0 | **0** |

Notable native wheels:
- `torch-2.6.0-cp312-none-macosx_11_0_arm64.whl`, `torch-2.8.0-cp312-none-macosx_11_0_arm64.whl` and `torch-2.10.0-cp312-none-macosx_11_0_arm64.whl`. PyPI also holds a re-uploaded `torch-2.10.0-2-…` build-tag file; the macOS Qwen3 lock must pin exactly one by hash.
- `torchaudio` 2.6.0, 2.8.0 and 2.10.0 (`macosx_11_0_arm64`).
- `onnxruntime-1.31.0-cp312-cp312-macosx_14_0_arm64.whl`.
- `numba-0.68.0`/`llvmlite-0.50.0` (`macosx_12_0_arm64`).
- `espeakng_loader-0.2.4-py3-none-macosx_11_0_arm64.whl`.
- `spacy-3.8.16`, `thinc-8.3.13`, `blis-1.3.3` and `srsly-2.5.3` (`macosx_11_0_arm64`).
- `spacy_pkuseg-1.0.1` (`macosx_11_0_arm64`).
- `numpy-1.26.4-…-macosx_11_0_arm64`.
- `PyMuPDF-1.27.2.3-cp310-abi3-macosx_11_0_arm64`.
- `pillow_heif-1.5.0-…-macosx_11_0_arm64`.
- `soundfile` 0.13.1/0.14.0 `py2.py3-none-macosx_11_0_arm64`, which bundle libsndfile, unlike the Windows `none-any` choice.

The minimum macOS tag is ≤ 14.0 everywhere, so all are compatible with macOS 27.

**Caveats (why a native lock is still mandatory).** These are *Windows* pin sets checked for Mac wheels. A native resolution on the Mac can differ in two ways:
- **platform markers:** e.g. `win32_setctime` and `colorama` drop out, and a darwin-only dependency could appear;
- **file choice:** several pins have more than one Mac wheel (numpy 2.5.4, scipy, orjson, regex).

So each Mac lock is generated on the Mac by `lock_base_requirements.py`-style tooling, with every artefact hash-pinned and reviewed. *Wheel existence is not runtime compatibility*: whether torch 2.6.0 (January 2025) behaves on macOS 27 is a P1/P2 experiment (§6 risks).

### 7.3 Upstream evidence summary

Full links are in Appendix A.

| Topic | Finding | Status | Primary source |
|---|---|---|---|
| python.org 3.12 macOS installers | Last binary installer is **3.12.10** (2025-04-08), universal2 `.pkg`, private Tcl/Tk **8.6.16**, MD5 + Sigstore only. Admin required, installs into `/Library/Frameworks`. 3.12.11+ are source-only (3.12.16, 2026-10-25) | VERIFIED | python.org release pages; `Mac/BuildScript/build-installer.py` @ v3.12.10 |
| python-build-standalone (PBS) macOS | `20261009` (the tag ACT's Windows stage 0 pins): Aqua **Tcl/Tk 9.0.4** (`--enable-aqua=yes --without-x`), Windows uses `tk-windows-bin-8615` (8.6.15). Fix for 3.10–3.12 + Tcl 9 threading (lost `after()` callbacks, segfaults: PBS #1320) **shipped in 20261009**. Latest tag `20261110` = 3.12.16. Not a framework build (PBS #274 open) | VERIFIED (downloads.json/build-tk.sh at the tag; release notes) | github.com/astral-sh/python-build-standalone |
| Homebrew `python-tk@3.12` | Now 3.12.16 with `tcl-tk` **9.1.0**; patches 3.12 for Tk 9 (gh-128103, gh-124111 backports). Unpinned | VERIFIED | formulae.brew.sh API |
| CPython + Tk 9 | Tk 9 support (gh-124111) targets 3.13+; 3.12 + Tk 9 works only through downstream patches (PBS, Homebrew) | SUPPORTED UPSTREAM | cpython#124111 |
| Tk 9 breaking changes relevant to ACT | `trace()` family removed (ACT uses only `trace_add`); macOS `<MouseWheel>` rescaled (TIP 474); **trackpads emit `<TouchpadScroll>`, not `<MouseWheel>`** (TIP 684); no `~` expansion in Tcl paths (ACT passes none); strict encodings; Text `count`/search tuples (unused) | VERIFIED | TIP 474, TIP 684, Tcl/Tk 9.0 release page, Python tkinter docs |
| kokoro / misaki and Python 3.13 | PyPI 0.9.4 still `requires_python <3.13`; GitHub main allows `<3.14` but is unreleased, so **stay on 3.12** | VERIFIED | PyPI JSON |
| Gatekeeper | Sequoia (15) removed Control-click override. Current flow: try to open → System Settings › Privacy & Security › **Open Anyway** → password; exception is remembered | VERIFIED | developer.apple.com/news/?id=saqachfa; support.apple.com/guide/mac-help/mh40616 |
| Quarantine propagation | Archive Utility copies quarantine to every extracted file; `ditto` keeps it by default; **curl does not set quarantine**; `unzip`/`tar`/pip PLAUSIBLE (measure) | SUPPORTED UPSTREAM / PBU | eclecticlight.co 2022, 2025-12-08; `ditto(1)` |
| arm64 signing | Every arm64 executable must be signed; ad-hoc (linker) signature suffices to *run*, but not to pass Gatekeeper when quarantined | VERIFIED | Apple Big Sur universal-apps release notes |
| FFmpeg arm64 sources | Homebrew ffmpeg now 9.0.2 (GPL). **Martin Riedl**: arm64 release builds with a per-ZIP `.sha256`; the page says the macOS ZIPs are signed. Current release 9.0.2 (2026-09-20). The release history keeps a **9.0.1** arm64 build: created 2026-08-18, build path `1787073674_9.0.1`, separate `ffmpeg.zip` and `ffprobe.zip`, each with `.sha256`. Its published `codecs.txt` lists the AAC decoder `aac_at` and the MP3 encoder `libmp3lame`. That is the published listing; the binary is unproven, and no digest is recorded here. osxexperts: arm64 ZIPs + SHA-256, not notarized, mismatched source link. evermeet: Intel only | VERIFIED (pages and the 9.0.1 `codecs.txt`, read 2026-11-15; no binary downloaded) | formulae.brew.sh; ffmpeg.martin-riedl.de (release history, 9.0.1 detail page, 9.0.1 `codecs.txt`); osxexperts.net; evermeet.cx |
| PyTorch macOS wheels | torch 2.6.0 / 2.8.0 / 2.10.0 (+ `-2` rebuild) `macosx_11_0_arm64` for cp312; newest 2.15.0 (`macosx_14_0`, py ≥ 3.11). MPS needs macOS 14+ from 2.9 and 15+ from 2.15; float64/complex128 unsupported on MPS (fallback does not apply); bf16 needs macOS 14+; 2.15 raises on MPS OOM instead of returning wrong values | VERIFIED | pypi.org/pypi/torch/json; PyTorch 2.9/2.15 release notes; docs.pytorch.org/docs/2.15/notes/mps.html |
| MPS memory controls | `PYTORCH_MPS_HIGH_WATERMARK_RATIO` (default 1.7), `PYTORCH_MPS_LOW_WATERMARK_RATIO` (1.4 on unified memory); `torch.mps.{synchronize, empty_cache, current_allocated_memory, driver_allocated_memory, recommended_max_memory, manual_seed}`; **no peak-memory API** | VERIFIED | docs.pytorch.org/docs/2.15/mps_environment_variables.html, /mps.html |
| Process control | `start_new_session` → `setsid`; `Popen(process_group=…)` (3.11+) calls `setpgid` in the child before `exec`, joining only a group in the caller's session; `os.killpg`; no `PR_SET_PDEATHSIG` on macOS; kqueue `EVFILT_PROC`/`NOTE_EXIT` can watch the parent; the kernel closes every descriptor of a dead process (SIGKILL included), so a pipe's reader sees EOF once the last writer is gone; new Python descriptors are non-inheritable (PEP 446) and `pass_fds` is the only way one reaches a child; a process-group ID is not reused while the group has a member; `flock` locks are per open file and freed on close/death; `rename(2)` atomic on one volume; `fsync` ≠ `F_FULLFSYNC` | VERIFIED | Python docs (`subprocess`, `os`), PEP 446; `setpgid(2)`, `kqueue(2)`, `flock(2)`, `fcntl(2)`, `rename(2)`, `fsync(2)` |

Engine-specific upstream evidence is in §6 and Appendix A.

---

## 8. Native Python, venv and engine isolation strategy

### 8.1 Base Python selection (owner decision D1; recommendation)

**Recommended: the app-owned python-build-standalone CPython 3.12.15, release tag `20261009`, `aarch64-apple-darwin`, `install_only`.** This is the same CPython version and the same release tag as the Windows stage 0, so both platforms run byte-identical stdlib sources and the same pins.

- Asset: `cpython-3.12.15+20261009-aarch64-apple-darwin-install_only.tar.gz`, 25,165,569 bytes, SHA-256 `83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8`. This is the GitHub asset digest read on 2026-11-14. The sister Windows asset's digest `194c8f0d…b93b` equals ACT's existing `bootstrap_host.ps1` pin, which confirms this is the same source ACT already trusts.
- Location: `files/runtime-data/python/` (`bin/python3.12`). This is the same folder role as Windows (`APP_PYTHON_DIR`), outside `.venv` so a `.venv` repair can run from it.
- No installer runs: nothing goes into `/Library`, nothing is registered, and no admin password is needed. `curl` and `tar` (built-in) do the work; `curl` does **not** set `com.apple.quarantine`, so the extracted interpreter is not quarantined.
- **Tk:** PBS builds macOS tkinter against Aqua **Tcl/Tk 9.0.4**, verified in `pythonbuild/downloads.json` and `cpython-unix/build-tk.sh` at tag `20261009`. The Windows build of the same tag uses Tk 8.6.15. Tag `20261009` is the first with the fix that makes 3.10–3.12 treat Tcl 9 as threaded (PBS #1320: before it, `after()` callbacks from worker threads were lost and widget calls segfaulted). **So adopting this runtime means adopting Tk 9 on macOS.** That is a bounded port (§10) and is unproven on macOS 27 (P1A stop condition).
- **Open questions measured in P1A:**
  - PBS is not a framework build, so check whether the window is sharp on Retina (no app `Info.plist` with `NSHighResolutionCapable`);
  - the menu-bar app name (likely "Python") and the Dock icon;
  - whether the window comes to the front when launched from Terminal.

  Cosmetic issues are recorded and fixed narrowly. A blurry or non-functional window is a stop condition.

**Rejected or secondary routes:**
- **Homebrew `python@3.12`.** Its tkinter links **Tk 9.0.3** on this Mac, which differs from the Windows build's Tk 8.6. It is unpinned (a Homebrew upgrade changes the runtime under a built venv) and needs Homebrew. **Not used for the app.**
- **python.org installer.** It needs an admin password and installs machine-wide into `/Library/Frameworks`. It is the **only Tk 8.6 option** (3.12.10's private Tk 8.6.16), but it has drawbacks:
  - 3.12.10 is the *last* 3.12 binary installer (2025-04-08), so it lacks every 3.12 security fix since; 3.12.11+ are source-only;
  - it is a different patch level from Windows' 3.12.15;
  - it publishes only MD5 + Sigstore (no SHA-256);
  - it is unproven on macOS 27.

  It stays a **fallback** for D1, only if PBS/Tk 9 proves unworkable in P1A, and it would need the owner to approve an admin-password install.
- **Apple `/usr/bin/python3` (3.9.6, Tk 8.5.9).** Never used and never modified, in line with workspace policy.

**Python version:** stay on **3.12**, matching Windows and every lock. PyPI `kokoro 0.9.4` and `misaki 0.9.4` still declare `requires_python <3.13`. Their GitHub `main` allows 3.13 but is unreleased, so moving to 3.13 would mean installing unreleased engine code. Not proposed.

**Pin choice.** Use the exact Windows pair `3.12.15` + `20261009` for parity, rather than PBS's newer `20261110`/3.12.16. Moving both platforms to a newer tag later is a joint, owner-approved bump with Windows re-verification.

### 8.2 Stage 0: `scripts/shared/bootstrap_host_macos.sh` (new, bash 3.2)

The macOS mirror of `bootstrap_host.ps1` and the canonical name in `.ai/BOOTSTRAP.md`. It is responsible **only** for providing a proven base Python:

1. If `files/runtime-data/python/bin/python3.12` exists, run it under a **bounded probe**. The probe is `-I -c "import sys, ssl, venv, ensurepip, tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy(); …"`: a real Tk init, not just `Tcl()` (the Windows audit lesson ACT67-AUD-006). It must also assert arm64 (`platform.machine()=='arm64'`) and version 3.12. On success, write the path and exit 0.
   - **Watchdog.** macOS has no `timeout`, so stage 0 starts the probe in the background and polls it with a bash loop. Past N seconds it sends SIGTERM, waits 2 s, then sends SIGKILL, and always reaps it (`wait`). A probe that hangs (for example a Tk init with no window server, as in an SSH session) or ignores SIGTERM ends as exit 3 with a message naming the cause. It never blocks the launcher.
2. Otherwise **explain and ask**: what is downloaded (about 25 MB, from GitHub/astral-sh), where it goes, and that no admin is needed. Nothing downloads without Yes. Exit codes match Windows: 0 = proven, 2 = declined, 3 = failed.
3. Download into `files/temp/bootstrap/` with `curl --fail --location --proto =https`. curl's own stall limits apply: `--connect-timeout`, `--speed-limit`/`--speed-time`, and an overall `--max-time` sized for 25 MB on a slow link. Verify the **exact size and SHA-256** with `shasum -a 256` (built-in). On mismatch, delete the file and exit 3. Never fall back to an unverified source.
4. **Safe extraction.**
   - **List before extracting** (`/usr/bin/tar -tvzf`). Any member that fails these rules is refused (exit 3) and nothing is extracted:
     - no absolute path and no `..` component;
     - nothing but regular files, directories and symlinks;
     - every symlink target resolves inside the extraction root;
     - no setuid/setgid bit;
     - every member sits under the single expected top folder.
   - **Extract** with `/usr/bin/tar -xzf … --no-same-owner` into a fresh staging sibling named `.act-stage-python-<pid>`. bsdtar refuses `..` and absolute paths unless `-P` is given, and stage 0 never passes `-P`; the listing check above is the authority regardless.
   - **Verify** that `bin/python3.12` exists and is arm64 (`lipo -archs`), then move it into place with one `mv` (atomic same-volume rename). Prove it with the probe, then delete the archive and the staging folder.
5. Hand off to `bootstrap.py`, which stays the authority for `.venv`, packages, FFmpeg, models and launch.

**Interruption recovery.** Every intermediate artefact is named so stage 0 can recognise it as its own: the `.part` download, the `.act-stage-python-<pid>` staging folder and the archive. The final `files/runtime-data/python/` exists only after the single `mv`, so the state is always one of: absent, staging-only or complete.
- **On the next run,** stage 0 removes stale artefacts of its own naming whose recorded pid is not alive, and only inside `files/temp/bootstrap/` or `files/runtime-data/`. It then starts again. A complete interpreter that fails the probe is set aside under its own name, never deleted silently, and the owner is asked.
- **During this run,** a `trap` on `EXIT HUP INT TERM` kills the probe/curl child it started and removes only the partial artefacts it created. Closing the Terminal window delivers SIGHUP to the script and to its children in the same foreground process group (job control is off in scripts), so no download or probe outlives the window.

Qualification-only switches mirror `-AssumeYes/-AssumeNo/-DownloadOnly/-ArchivePath`. They exist so the stage can be tested offline against a fixture archive, and the launcher passes none of them.

**Clean-install evidence classes (P1A, P7; reported as written here).**

| Class | How it is produced | What it proves | What it cannot prove |
|---|---|---|---|
| **SIMULATED (PATH-restricted)** | On this Mac, in a disposable clean LF worktree. The launcher, stage 0 and `bootstrap.py` run under `env -i` with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, a scratch `HOME` and a scratch `TMPDIR`. Recording **shims** named `brew`, `python3`, `python3.12` and `ffmpeg` sit first on PATH; each logs its call and exits non-zero | ACT never *calls* Homebrew or a PATH Python or FFmpeg (every shim log must be empty), and the whole flow works from the app-owned interpreter | That nothing *links to* or *loads* from `/opt/homebrew` or `/usr/local`; that the Xcode Command Line Tools are not needed |
| **SIMULATED (linkage-verified)** | Added to the above. `otool -L` on every Mach-O in `files/runtime-data/python/`, `.venv/`, the engine environments and `files/bin/ffmpeg/`: every dependency must be under the app tree (`@rpath`/`@loader_path` resolving inside it) or a system path (`/usr/lib`, `/System/Library`). The images actually loaded by the running GUI and by each worker are listed (`vmmap --summary` or `lsof -p` on the live process) and must include nothing under `/opt/homebrew` or `/usr/local`. Every Mach-O is arm64 (`lipo -archs`), `codesign --verify` passes (ad-hoc is enough to run), `pip check` is clean and every install used `--require-hashes`. A before/after listing of `~/Library/Caches`, `~/.cache`, `~/Library/Application Support` and `/usr/local` shows no ACT writes outside the repository and `$TMPDIR` | No hidden linkage or load dependence on Homebrew, and no writes outside the repository | That a Mac which never had Homebrew, the CLT or python.org behaves the same: Gatekeeper on a quarantined download, missing CLT prompts (`xcode-select` stubs) and first-run privacy prompts |
| **SIMULATED (separate account)** | Optional. A new standard macOS user on this Mac. Its default PATH has no `/opt/homebrew/bin`, but Homebrew and the CLT still exist on disk | The same as above, from a profile with no user shell customization | Same as above |
| **REAL CLEAN** | An Apple Silicon Mac, physical or a virtual machine, that never had Homebrew, the Xcode CLT or a python.org install. The browser-downloaded **release archive** is extracted with Archive Utility (quarantined) → Gatekeeper "Open Anyway" → stage 0 → first run → all six tools open → `.venv` damage → repair → relaunch → interrupted install → recovery. Method per D18 | O1 | — |

P1A exits on SIMULATED (PATH-restricted + linkage-verified) evidence, labelled as such. REAL CLEAN is mandatory before publication: it is the `fresh-macos` qualification on the exact release archive, P7c. A SIMULATED result is never reported as a clean-Mac result.

### 8.3 The `.command` launcher (redesign; owner decision D2)

Keep it thin.

**Kept:**
- the translocation guard;
- the fast path (`.venv/bin/python bootstrap.py --launch-only`);
- the repair exit code 3;
- the detached GUI;
- the `close_terminal.py` handoff.

**Changed:**
- the PATH-scavenging Python search;
- the automatic Homebrew installation (`curl … HEAD/install.sh`);
- `brew install python@3.12 python-tk@3.12 ffmpeg`;
- the `python3` headless fallback (which could reach Apple's 3.9).

These are replaced by a call to `bootstrap_host_macos.sh`, then `files/runtime-data/python/bin/python3.12 scripts/shared/bootstrap.py [--repair-venv]`. `bootstrap.py`'s `install_python`/`find_suitable_python`/`_brew_install_python_tk` macOS branches follow the same model: the app-owned interpreter only, like Windows' v0.7.0 portable layout. Homebrew stays a *discovered* FFmpeg candidate only if D3 allows it (§11).

### 8.4 Environments and isolation

- **Same unified layout as Windows** (owner decision 2026-11-13): `.venv/` (app), `.venv/engines/qwen3/` and `.venv/engines/omnivoice/`. Each has its own interpreter (a venv on the app-owned base Python), lock, receipt, model identity and lifecycle locks. No package set is combined: transformers 5.2.0 (app), 4.57.3 (Qwen3) and 5.3.0 (OmniVoice) conflict, exactly as on Windows.
- POSIX venvs reference the base interpreter by absolute path. Engines are **built at their final path** and never run from a set-aside location (the same rule as Windows). The app-`.venv` replacement transaction already carries `engines/` across and holds both engines' locks (`engine_lease.EnvironmentLease`, `fcntl.flock` on POSIX). P1A must prove it on APFS: replace `.venv` while engines exist, then verify both engines still import from their final path.
- **Never reuse Windows wheels, CUDA builds, transferred environments or Windows receipts.** A receipt records the platform (`sys.platform`, machine, Python), so a receipt from another platform reads as *absent* and is never adopted (MAC-029). Wheel stores are platform-scoped (`files/runtime-data/python-packages/<platform-tag>/`) so a folder copied between machines cannot mix artefacts.

### 8.5 Native macOS dependency locks

| Lock (new) | Generated by | Content |
|---|---|---|
| `scripts/requirements-lock-macos-arm64-py312.txt` | `files/dev-tools/lock_base_requirements.py --platform macosx_arm64` on the Mac, from `scripts/requirements.txt` (unchanged human list) | Every package with **one** artefact hash (cp312 macosx arm64 or pure; the two pure sdists built by locked setuptools, as on Windows); header records requirements.txt SHA-256, resolver, interpreter |
| `scripts/qwen3-requirements-macos-arm64.txt` + darwin target in `qwen3-artifacts.json`/`qwen3_package_manifest` | Same discipline as `qwen3-requirements.txt`; PyPI only (no cu128 index); exactly one torch 2.10.0 file | 88–89 packages; `sox` from ACT's supply wheel |
| `tts/omnivoice_manifest.json` gains a `darwin_arm64` wheel list (or a sibling manifest) | From upstream `uv.lock`'s darwin markers (PyPI `torch==2.8.0`) re-verified on the Mac | ~86 wheels (~247 MB, vs 3.66 GB on Windows) |

`requirements.txt` stays the single human-maintained list, and **no pin is changed** to make the Mac work unless an experiment proves a pinned version broken on macOS 27. That change would be an owner decision, recorded in Decisions, and it would require Windows re-verification because the app pins are shared.

---

## 9. Model, cache, install and repair architecture

- **Placement (unchanged from Windows):** `files/runtime-data/models/huggingface/` (HF_HOME, Kokoro and Chatterbox pinned snapshots), `files/runtime-data/qwen3/…`, `files/runtime-data/omnivoice/…` (models, receipts, jobs, prompts, set-aside), `files/runtime-data/python-packages/<platform>/`, `files/runtime-data/pip-cache/`, `files/runtime-data/logs/`, and `files/bin/` for an app-owned FFmpeg. Nothing goes to `~/.cache`, `~/Library` or `/usr/local`, with one exception: the per-user temp folder ACT already uses for work areas.
- **Consent:** reuse the existing first-run review panel and Install & Continue. Every model or environment download names its bytes, licence and hardware terms **before** consent. Nothing auto-downloads at synthesis time; the offline audit hooks stay.
- **Integrity:** model files are verified by the existing platform-neutral size + SHA-256 manifests, after download and again on repair. Wheels are installed only with `--require-hashes` from the macOS locks.
- **Transactions:** reuse the staging-then-rename pattern. Interrupted downloads resume or restart in staging and never in place. A partially installed engine has no receipt, so it reads as NOT READY and is never deleted silently. Installer children (pip and its build backends, downloads, unpacking) are owned and contained under §11.2.2. A setup that is killed, crashes or loses its Terminal window therefore leaves no installer running and nothing writing into staging. The next launch finds staging without a receipt and repairs it.
- **Repair:** the normal launch is the repair path (`.ai/BOOTSTRAP.md`). Corrupt model → hash mismatch → offer repair (consented re-download of the affected file). Failed repair → the previous state is kept, with a clear message.
- **Disk-space planning (approximate; recorded, not promised):**

| Component | Approx. download | Approx. installed |
|---|---|---|
| Base Python | 25 MB | ~100 MB |
| App `.venv` (with the Kokoro/Chatterbox stack) | ~0.8–1.2 GB on Mac (torch CPU/MPS wheel ~70 MB vs ~200 MB+ on Windows) | ~1.5–2.5 GB, to be measured |
| Kokoro model + spaCy model | ~0.35 GB | ~0.35 GB |
| Chatterbox Turbo snapshot | ~3.9 GB (pinned repo; Turbo loads ~3.0 GB of it) | ~3.9 GB |
| Qwen3 CustomVoice + Base | ~9.1 GB | ~9.1 GB + env (~1 GB on Mac, to be measured) |
| OmniVoice model + env | ~3.27 GB + ~0.25 GB | ~3.5 GB |
| Optional Whisper (benchmarks only) | 0.97 GB | 0.97 GB |
| **Total with every component** | **~18–19 GB** | **~20–22 GB** (637 GiB free here) |

Disk checks before each consented download reuse `optional_setup_resource_budget.py`.

---

## 10. macOS GUI and launcher design

- **Tk runtime.** Use the Tk shipped in the app-owned Python (D1): Aqua **Tk 9.0.4** on macOS, while Windows stays on Tk 8.6.15. The **Tk 9 port (MAC-007/040)** is small and bounded. Every change is guarded by the *running* Tk version (`tkinter.TkVersion >= 9`) or windowing system, never by guessing the OS, so Windows Tk 8.6 behaviour is untouched.
  - **Trackpad scrolling.** Tk 9 sends two-finger trackpad scrolls as `<TouchpadScroll>` (TIP 684), not `<MouseWheel>`. Add `<TouchpadScroll>` handlers (using `tk::PreciseScrollDeltas %D`) at the three custom scroll sites:
    - `shared/ui_theme.py` (the shared hover-region scroll owner);
    - `artwork/cover_resizer.py:992`;
    - `tts/qwen3_clone_setup_ui.py:153`.

    The last one computes `int(-event.delta/120)`, which is 0 for Tk 8.6's small macOS deltas, so it never scrolled on the old macOS Tk either.
  - **Wheel deltas.** Tk 9 rescales macOS `<MouseWheel>` deltas (TIP 474). The sign-only handler in `ui_theme` is already correct. `cover_resizer`'s handler already accepts both ±120 multiples and small integers. Verify both with a real mouse and trackpad.
  - **Tk 9 hazards already absent** (verified by grep): no `trace()`/`trace_variable`/`trace_vdelete` (only `trace_add`, 7 uses); no `~` paths passed to Tk; no Text `count`/`search` result unpacking.
  - **Threads.** The PBS `20261009` fix makes Tcl 9 threaded for 3.12. P1B still runs the worker → `after()` stress test, because a lost callback would freeze progress.
  - **Native-only tests.** The aqua-only tests (39+) were written against Tk 8.6 metrics, so expect some geometry pins to need Tk 9 values. Update only the macOS expectations, with screenshots in the evidence. Never update the Windows ones.
- **Shell.** Keep the existing `aqua` mode of `shared/ui_theme.py`: Finder-style shell, native aqua controls, unchanged since v0.5.0 (Decisions 2026-07-08). No redesign. Run the existing aqua-only tests natively: 39 skips on Windows (`native-macos-only` policy), concentrated in `test_m4b_layout.py`, `test_mp3_tool_layout.py` and `test_ui_theme.py`. Fix only the regressions they reveal.
- **Cmd+Q (MAC-008).** Register `root.createcommand("::tk::mac::Quit", app._on_close)` and route it through the same close path as the red close button. That path:
  - saves `last_tool`;
  - lets panels cancel their runs;
  - finishes Tk objects on the main thread;
  - runs the orderly containment shutdown of §11.2.2: `stop_media_children`, ending the workers, then closing the lifeline.

  SIGTERM, SIGHUP and SIGINT (Activity Monitor "Quit", logout, Ctrl+C in the Terminal) reach the same close path through a signal handler that schedules it with `after`. Containment after a crash or SIGKILL never depends on this path (§11.2.2). Also consider `::tk::mac::ShowPreferences` → Preferences & Data (the existing `<Command-comma>` accelerator).
- **Main-thread rule (MAC-032).** AppKit requires UI calls on the main thread; a Tk call from a worker thread can crash the whole process on macOS. P1B does two things:
  - a **static audit** that every worker-to-UI path uses `after()`/queues;
  - a **runtime stress test**: many rapid progress events from worker threads while resizing the window.
- **HiDPI, dark mode, focus.** Verify `tk scaling` on Retina, Light/Dark appearance (the aqua shell follows the system), window activation when launched from Terminal (the detached GUI must come to the front), minimum and maximum geometry (the v0.6.5 aqua lessons) and the Dock/menu-bar name.
- **Fonts (MAC-020).** Replace the hard-coded `"Segoe UI"`/`"Consolas"` in `optional_setup_panel.py`, `long_paths.py` (a Windows-only page, low priority) and `appearance.py` (`mono`) with the theme's family helpers. The Windows output stays byte-identical, because the helper returns the same family on win32.
- **Shortcuts (MAC-037).** Add `<Command-a>` beside `<Control-a>` where `<Control-a>` exists alone (`job_ui.py` text boxes). Existing Windows bindings are unchanged.
- **Launcher UX.**
  - First run: Terminal shows plain prompts, then the existing setup window (bootstrap's Tk UI) runs on the app-owned Python.
  - Healthy launches: a fast path, then Terminal closes itself.
  - Failure: the window stays open, pointing at the log.
- **Gatekeeper and quarantine (MAC-003).** A ZIP downloaded with a browser is quarantined, and Archive Utility copies the quarantine flag onto every extracted file, so the `.command` arrives quarantined. Since macOS 15, Control-click → Open no longer overrides Gatekeeper. The supported flow is:
  1. double-click (blocked);
  2. System Settings › Privacy & Security › **Open Anyway**;
  3. confirm with the login password.

  macOS then remembers the exception. The current launcher text still recommends "right-click → Open", which is **obsolete**, and it has to be rewritten. App Translocation is documented for *apps*. Whether it ever applies to a `.command` is unproven (PBU). The existing "no `scripts/` beside me" guard stays as a harmless safety net.

  Files the app downloads itself are **not** quarantined (curl/urllib/pip set no quarantine flag), so stage 0, the wheels and the models need no prompts. Integrity is enforced by SHA-256, not Gatekeeper.

  - **Recommended UX (D10):** the README gives step-by-step "Open Anyway" guidance, with a screenshot taken in the P6a packaging rehearsal. As an *optional, explained, opt-in* alternative, it shows a one-line Terminal command that removes quarantine from **the launcher file only** (`xattr -d com.apple.quarantine Setup_and_Run-audiobook-creation-tool.command`), stating plainly that it skips Apple's malware check for that file.
  - The app never removes quarantine silently or recursively, never touches third-party binaries this way, and never suggests disabling Gatekeeper (`spctl --master-disable`).
  - Signing and notarization of a wrapper app/pkg is a future owner decision (it needs a paid Developer ID).
- **Executable bit (MAC-002).** `release.py` already writes the `.command` as 0755 into the ZIP. This ZIP-transferred working copy needs a one-time, owner-approved `chmod +x Setup_and_Run-audiobook-creation-tool.command` before a Finder double-click test. It is a mode-only change, invisible to git under `core.filemode=false`.

---

## 11. FFmpeg, subprocess and filesystem compatibility

### 11.1 FFmpeg (owner decision D3)

- **Requirements:**
  - an arm64 `ffmpeg`+`ffprobe` pair proven by execution (`ffmpeg_health`);
  - the **`aac_at` (AudioToolbox) decoder**, without which xHE-AAC sources fail on macOS (`ffmpeg_utils.decoder_args_for`);
  - `libmp3lame`;
  - version 9.0.1 to match the Windows pin.
- **Discovery order (unchanged model):** an app-owned pinned pair in `files/bin/ffmpeg/<version>/` first; an explicitly configured pair; then PATH/Homebrew (`/opt/homebrew/bin`). Each candidate must pass the execution proof **and**, on macOS, list `aac_at`.
- **Source pin for a fresh Mac without Homebrew (D3).**
  - **Recommended:** evaluate the **historical Martin Riedl macOS arm64 9.0.1 release build first**, the same FFmpeg version as Windows' Gyan 9.0.1 pin. It is still published in Riedl's release history:
    - build path `/download/macos/arm64/1787073674_9.0.1/`, created 2026-08-18;
    - separate `ffmpeg.zip` and `ffprobe.zip`, each with a `.sha256`;
    - a published `codecs.txt` that lists the AAC decoder `aac_at` and the MP3 encoder `libmp3lame` (§7.3).

    Only the timestamped build path is used, never the `redirect/latest` route. The current 9.0.2 build (`1789931890_9.0.2`) is evaluated **only if 9.0.1 fails** one of the proofs below, and adopting it is a separate owner acceptance (a version different from Windows).
  - **Adoption proofs (P1A).** Each must pass on the actual downloaded bytes, in this order, before anything is pinned or used. A failure rejects the build.
    1. **Consented download** of the exact ZIPs from the build path with curl (no quarantine) into `files/temp/bootstrap/`.
    2. **Immutable identity:** ACT computes the size and SHA-256 of each ZIP from the bytes it received, and each must equal Riedl's published `.sha256`. Only then are those values written into the pin. *This plan records no digest:* none exists until P1A has the bytes, and none may be copied from a page or guessed.
    3. **Safe extraction** (member checks as in §8.2) to a staging folder, then one rename to `files/bin/ffmpeg/9.0.1/bin/`.
    4. **Architecture:** `lipo -archs` reports `arm64` only for both binaries.
    5. **Signature:** `codesign --verify --strict --verbose=2` passes. `codesign -dv` records the signing authority and Team ID, and these go into the pin so that a later re-signed binary is noticed.
    6. **Linkage:** `otool -L` names only system libraries and frameworks (`/usr/lib`, `/System/Library`, including AudioToolbox), with no `/opt/homebrew` or `/usr/local` path.
    7. **Execution:** the `ffmpeg_health` proof passes. `-version` reports 9.0.1, `-decoders` lists `aac_at` and `-encoders` lists `libmp3lame`; a published codec list is not accepted in place of this.
    8. **Real xHE-AAC proof.** (Its sample-count clause was amended by the owner after the D3 forensic investigation: D3 revised, 2026-11-15. Everything else is as first written.)
       - An owner-supplied **real xHE-AAC (USAC) audiobook**, kept local and never committed, is decoded through `-c:a aac_at` to PCM, and by Apple's own decoder (`afconvert`, built in). Tool: `files/dev-tools/xhe_proof.py`.
       - **A. Decoder correctness (unchanged).**
         - The decodes align: lag within 2,048 frames (T2).
         - The PCM matches over the aligned overlap: SNR ≥ 60 dB and largest difference ≤ 64 LSB (T3). No narration is dropped, corrupted or shifted.
         - The source's own packet, sample-table and edit-list accounting is read and recorded with the result.
       - **B. Sample count (amended).** The two counts agree within one AAC frame (1,024 frames). The only other accepted case is narrow. FFmpeg may emit **more** frames than Apple only for a source the owner approved by SHA-256, at exactly its approved counts, and only when all of these hold:
         - it is an excess, never a shortfall;
         - the decodes align at lag 0, and every frame Apple emits is bit-identical in FFmpeg's decode;
         - FFmpeg's count is exactly packets × frames per packet (every packet the container holds, in full);
         - the excess is no larger than the padding the container's own sample table declares;
         - every excess frame is exactly zero, with the whole region read.

         There is no loose tolerance and no general licence. ACT never trims, pads or rewrites decoded audio to match Apple's length. Why: Apple truncates its output to the edit-list length, while FFmpeg presents every decoded packet in full; on the approved stitched file the difference is padding declared at its joins (Decisions 2026-11-15).
       - **C. Manual acceptance (unchanged).** The owner listens. It is a separate owner check and is never inferred from A or B.
       - The existing Converter real-media journey then runs on that file with this build.

       A file generated on the Mac may supplement this proof but never replaces it: whether `afconvert` can encode USAC on macOS 27 is PLAUSIBLE BUT UNVERIFIED. The existing tests note that no xHE-AAC file can be generated with the pinned FFmpeg.
  - **Pin:** ACT pins its *own* recorded build path, sizes, SHA-256s and signing identity in `shared/ffmpeg_portable.py` (macOS block), recorded in Decisions with the proof evidence. As with the Gyan pin, the digest is the authority, not the URL. A changed byte at the same URL fails verification and is never adopted.
  - **Acquisition at run time** (after adoption): with consent, steps 1–7 run on every acquisition and repair, against the pinned values.
  - **Note.** FFmpeg autodetects AudioToolbox on Darwin, and the 9.0.1 listing shows `aac_at`. The binary's behaviour on macOS 27 is still **PLAUSIBLE until proofs 7 and 8 pass**. Without `aac_at` the build is rejected (xHE-AAC) and the next candidate is tried.
  - **Licensing:** these builds are GPL (x264/x265); Gyan "full" on Windows is GPL too. ACT does not bundle FFmpeg in its archive; it downloads it on consent, as on Windows.
  - **Alternatives:**
    - accept a proven Homebrew pair when present (today's behaviour; unpinned version);
    - osxexperts (SHA-256 but not notarized, mismatched source link): not recommended;
    - evermeet: Intel-only, unusable without Rosetta.
  - **Discovery hygiene:** check the Mach-O architecture (`lipo -archs`) *before* executing a candidate. An Intel binary in `/usr/local/bin` is rejected without being run, which avoids any Rosetta prompt.
- **Byte-identity routes.** The Converter's continuous split route is enabled only for `QUALIFIED_BUILDS` (Gyan Windows hashes). On macOS it is *correctly* refused and the existing per-chapter route is used: identical semantics, slower. Qualifying a macOS build means adding its hash pair after running the `m4b-scaling` harness on the Mac. That harness takes about 3 hours (owner decision D11c). It is not required for correctness.
- **MP3 `-write_xing 0` on darwin (MAC-019).** This historic macOS-only encode flag makes macOS MP3 bytes differ from Windows. Re-verify why it exists (v0.3.x "MP3 speed-up" era) and whether it is still needed with FFmpeg 9.0.1. Keep it unless a test proves it unnecessary, and record the outcome in Decisions. Its removal would be an owner decision, because it changes output bytes.

### 11.2 Processes, cancellation and containment (macOS semantics)

Summary table; the binding design is §11.2.1–§11.2.3.

| Mechanism | Windows today | macOS design (proposed) |
|---|---|---|
| Child ownership | Job Object (kill-on-close), suspended start | Every ACT-owned child is in a process group its owner can signal, and is tied to its owner by a lifeline (§11.2.2):<br>• ACT-authored Python children get their **own process group** (`start_new_session=True`, pgid = pid), as `qwen3_process.spawn` and the pip runs already do;<br>• third-party executables join the owner's **ACT guardian** group atomically (`process_group=`) |
| Cancel a worker (Qwen3, OmniVoice) | flag file → `TerminateJobObject` | flag file (unchanged) → the engine's existing grace (Qwen3 3 s, OmniVoice 2 s) → `os.killpg(pgid, SIGKILL)` (as `qwen3_process.kill_tree` does today) → `waitpid`, within the bound of §11.2.1. Never kill by name |
| Cancel Kokoro / Chatterbox inference | In-process; checked between chunks; the chunk in flight finishes (unchanged on Windows, D17) | Inference runs in the **local-engine worker**, and Cancel ends its process group at once (§11.2.1, MAC-043) |
| Cancel a single FFmpeg step | `run_supervised` terminate → kill via handle | Unchanged (works on POSIX) |
| **Parent death (GUI or setup crash, SIGKILL, Force Quit, a closed Terminal during setup)** | Job Object kill-on-close | Lifeline EOF ends every ACT-authored child; the ACT guardian ends third-party executables (§11.2.2, MAC-009/044). macOS has no `PR_SET_PDEATHSIG`, and `atexit` is never the mechanism: it does not run on SIGKILL or a crash |
| App-exit cleanup of media children | `stop_media_children` (Toolhelp snapshot, own children named ffmpeg/ffprobe) | POSIX twin over the owned-child registry (pid + start-time identity), never a `ps` scan by name. It is part of the orderly close path (window close, Cmd+Q, SIGTERM/SIGHUP/SIGINT), with `atexit` only as the last orderly resort |
| Cross-copy engine exclusion | `Global\` named mutex (CreateMutexW); off Windows `scope = "none"` (MAC-010) | `fcntl.flock` on a per-user lock file in `tempfile.gettempdir()/ACT-locks/<engine>.lock`, the same temp root ACT already uses. The kernel releases it on process death, so locks never go stale. Owner decision D13 (Windows itself documents "two copies can still run Qwen3 and OmniVoice together"; the new lock is a strict improvement) |
| Pause | Between files | Unchanged (platform-neutral) |

#### 11.2.1 Cancellation contract and preemptible inference (MAC-043, D17)

**Reconciliation with the standing rule.** Decisions 2026-11-05 (v0.7.2 Phase 1) rules:
- "Cancel means stop, at once, everywhere";
- the publication boundary is the rename;
- Pause is the only graceful boundary.

The released code meets this rule for:
- Edge (one look, 0.25 s);
- FFmpeg (supervised);
- assembly and publication;
- the worker engines (flag → grace → tree kill).

It does **not** meet it for Kokoro and Chatterbox in the GUI process:
- `kokoro_file_to_mp3` and `chatterbox_file_to_mp3` read `cancel_check` only between chunks; Chatterbox also reads it between colon segments, and its docstring says a generation in flight "is allowed to finish".
- A model call in flight cannot be stopped from Python. A thread cannot be killed, and an asynchronous exception is not delivered inside a native torch operation.

On Windows with CUDA a chunk is short. On a Mac CPU, one Chatterbox chunk, or one Kokoro chunk of up to 3,000 characters, can take tens of seconds. The earlier wording "Cancel latency bounded by one chunk" is therefore **withdrawn as an acceptance criterion**: it contradicts the rule.

Alternatives rejected:
- **smaller chunks:** they change the chunk ceilings, which §13 item 6 holds immutable;
- **more cooperative check points:** still unbounded inside a single operation;
- **thread interruption:** impossible inside native code;
- **MPS for speed:** a correctness risk (§6).

**Contract.** Applies to every tool and engine on macOS, measured from the Cancel click.
- **C1 Acknowledge ≤ 0.5 s.** The panel shows the cancelling state and the latch is set. After the latch, no new chunk, request, file, FFmpeg step or publication starts.
- **C2 Stop ≤ T_stop.** Every active operation of the run has ended, every ACT-owned child of the run is reaped, and the run is CANCELLED. The bound **never scales** with chunk length, text length or device speed. Bounds (D17):

  | Route | T_stop | Basis |
  |---|---|---|
  | Edge | ≤ 2.5 s | the existing bounded request end |
  | Local-engine worker (Kokoro, Chatterbox) | ≤ 2 s | immediate SIGKILL |
  | Qwen3 worker | ≤ 5 s | 3 s grace + kill + reap |
  | OmniVoice worker | ≤ 4 s | 2 s grace + kill + reap |
  | One FFmpeg step | ≤ 4 s worst case, typically < 0.2 s | terminate → 2 s → kill → 2 s |
- **C3 Nothing unfinished is published.** These are the 2026-11-05 semantics, unchanged:
  - no file appears under a final name;
  - the run's staging is removed;
  - already-published files are untouched;
  - the stopped items stay NOT_ATTEMPTED and the run is CANCELLED.
- **C4 Pause is unchanged.** `JobController.checkpoint` between source files: active files finish and nothing new starts. A paused local-engine worker stays loaded and idle. Cancel during Pause meets C1–C3.
- **C5 Recovery.** The next run after a Cancel works: a killed worker is restarted and its cold load is logged.
- **Windows is unchanged.** Kokoro and Chatterbox stay in-process with between-chunk Cancel, exactly as released (D17). The remaining Windows gap, a long chunk on a CPU-only Windows machine, is recorded as an open item for a later Windows release. This programme does not change it.

**Local-engine worker (darwin; shared code, selected by platform).**
- **New modules.** `tts/local_engine_worker.py` (child entry) and `tts/local_engine_host.py` (parent side). They follow the Qwen3/OmniVoice worker protocol (JSON-line events, a per-event timeout) and are spawned through the containment layer as class A (§11.2.2).
- **What moves.** Only the model calls: model load (`kokoro_synth._local_model`, Chatterbox `from_local`) and per-chunk synthesis (the `KPipeline` call, `_synthesize_chunk`).
- **What stays in the parent, with the same functions as today:**
  - speech preparation (`pipeline.prepare`, once per file in the parent, §13 item 5);
  - chunking and seeds;
  - the Cancel checks;
  - PCM assembly and the one encode;
  - publication and all job reporting.
- **Data path.**
  - The parent sends one request per chunk: prepared text, voice, settings and seed.
  - The worker returns float32 PCM through a run-private file in the TTS work area (an entry the parent owns and removes) or through a pipe.
  - The parent checks sample rate, dtype, finiteness and length before using it.
- **Lifecycle.**
  - **Running:** one local-engine worker at a time. It starts on first use and stays warm across files and runs while the same engine is selected.
  - **Ending:** on an engine switch, on app close, and on Cancel. Cancel sends SIGKILL to its group, because the worker owns no state worth saving.
  - **Cost after a Cancel:** the next run cold-loads the model, measured in P2/P3A and reported in the log.
  - **Side benefit:** models no longer stay resident in the GUI process, which removes R11.
- **Failure.** A worker exit not caused by Cancel marks the file FAILED with the worker's reason (its stderr tail), and the existing retry policy is unchanged. Nothing hangs: there is a per-event timeout, as with Qwen3's `EVENT_TIMEOUT_S`.
- **Parity proof.** On the CPU with fixed seeds, the worker path and the in-process path must produce identical PCM for Chatterbox and identical phoneme/token streams for Kokoro (Kokoro's decoder noise is unseeded, §12.B). Any difference is a stop.
- **Selection.** `local_engine_isolation()` is true on darwin and false on Windows, which keeps the released path. A later owner decision with Windows qualification can change that (D17).

#### 11.2.2 Process ownership and parent-death containment (MAC-009, MAC-044)

**Owners.** A process that spawns children owns them: the GUI (`launcher.py`) and the setup process (`bootstrap.py`). The gate keeps its own harness containment (the POSIX branch of `helpers/winproc.py`). Each owner holds one owned-child registry (`shared/child_ownership.py`: new, POSIX-only, stdlib).

**Child classes.**

| Class | Members | Process group | Parent-death mechanism |
|---|---|---|---|
| A. ACT-authored Python | Qwen3 and OmniVoice workers; the local-engine worker; the optional-setup worker and supervisor; pip with its build backends, run through a small ACT pip entry that starts the lifeline and then runs pip with `runpy` (the existing `omnivoice_setup.OFFLINE_PIP` wrapper is the precedent); setup helper scripts | Its own (`start_new_session=True`) | The lifeline thread inside the child |
| B. Third-party executables | `ffmpeg`, `ffprobe`, and any external tool an owner runs beyond a short probe (`codesign`/`otool`/`lipo`, and `tar`/`unzip` where bootstrap uses them) | Joins the owner's **ACT guardian** group atomically: `Popen(process_group=<guardian pgid>)` calls `setpgid` before `exec`, so no window exists in which the child is outside a contained group | The guardian ends its group on lifeline EOF |
| C. Stage 0 children (bash, before Python exists) | the bounded probe and curl | The Terminal's foreground group | SIGHUP on window close, the `trap` and the watchdog (§8.2) |
| D. Deliberately detached (fixed allow-list) | the GUI started by setup; the cleanup coordinator (`cleanup_state`, designed to outlive its window); `caffeinate -w <gui-pid>` (D11d; it ends with the GUI); `open` for Finder reveal; `osascript` in `close_terminal.py` | Their own session | None, by design. A test pins the allow-list to exactly these |

**Lifeline.**
- **Write end.** Each owner creates one `os.pipe()` at start. The write end never leaves the owner:
  - it is non-inheritable (the PEP 446 default);
  - it is never passed in `pass_fds`;
  - owners never `fork` without `exec`: the `multiprocessing` start method stays `spawn`, the macOS default, and a test asserts it.

  So no other process can hold the write end.
- **Read end.** It goes to each class-A child and to the guardian through `pass_fds`, with its number in `ACT_LIFELINE_FD`.
- **In the child.** The **first statements** of each class-A entry point start a daemon thread that blocks on `os.read(fd, 1)`. This happens before importing torch, transformers or pip, which can take seconds. On EOF or a read error the thread calls `os.killpg(os.getpgrp(), signal.SIGKILL)`.
- **Why it works without the owner.** The kernel closes a dead process's descriptors whatever ended it: SIGKILL, SIGSEGV/SIGABRT, Force Quit or a closed Terminal. EOF therefore arrives with no code running in the owner.
- **Alternative.** Inside the guardian, a kqueue `EVFILT_PROC`/`NOTE_EXIT` watch on the owner's pid would also work. The pipe is preferred because it cannot be confused by pid reuse.

**ACT guardian** (`shared/child_guardian.py`: stdlib only, a few dozen lines).
- **Start.** Each owner starts one at startup with `process_group=0`. That gives the guardian a new group in the owner's session, which class-B children must share for `setpgid` to succeed. Owners never call `setsid` after starting it.
- **On lifeline EOF.** The guardian holds the read end. On EOF it ignores SIGTERM for itself, sends `killpg(own group, SIGTERM)`, waits at most 1 s, then sends `killpg(own group, SIGKILL)`, which ends the guardian last.
- **Per-step Cancel** of a class-B child is unchanged: `run_supervised` signals that child by handle, and FFmpeg does not fork.
- **If the guardian dies** (for example, killed by hand), the owner reaps it, logs it and starts a new one for later spawns. Class-B children still running in the old group are then covered only by the orderly path until they end (residual R18).

**Orderly shutdown.** Triggers: window close, Cmd+Q, SIGTERM/SIGHUP/SIGINT routed to the close path, and `atexit` as the last orderly resort. The steps, bounded to at most 5 s in all:
1. Cancel running jobs.
2. Run the POSIX `stop_media_children` over the registry.
3. End class-A workers: SIGTERM → at most 1 s → SIGKILL → reap.
4. Close the lifeline write end, which also retires the guardian.
5. Reap the guardian.

Containment after a crash never depends on this path.

**Safe termination rules.**
- **Never kill by name, by a `ps` scan or by a pid alone.** Every registry entry records the pid, the pgid and the start time (`sysctl kern.proc.pid` → `kp_proc.p_starttime`, the same reader as D11b). A signal goes only to a process whose start time still matches.
- **Signal a group only while its ID cannot have been recycled.** A class-A group is signalled only while its leader is an unreaped child of the owner. The guardian signals only its own group, which cannot be recycled while the guardian lives.
  - *P5-A (2026-11-17):* the optional-setup worker keeps this rule after it exits. It is not reaped until its group is ended. `child_ownership.end_led_group` signals the group only while three things hold: it holds the `Popen`'s waitpid lock, the worker is unreaped (a zombie keeps its id), and the worker's start time matches the one recorded at spawn. Only then is the worker reaped.
- **Bounded and quiet.** Every wait is bounded, `ESRCH` counts as success, and nothing raises during shutdown.
- **Leftovers.** Staging left by a killed child is recovered by the existing owner-identity rules (`work_area` recovery, receipts, §9), never by guessing.

**Windows is unchanged:** Job Objects (kill-on-close), the Toolhelp `stop_media_children` and the existing spawn helpers. The new modules are POSIX-only behind `sys.platform != "win32"`, and Windows tests prove no new path is taken.

#### 11.2.3 Bounded cancellation and containment acceptance tests

Rules for every test:
- automated tests synchronize on barriers and recorded events; a sleep is never an assertion;
- times come from `time.monotonic()`;
- every spawned process is recorded with its start time, and its identity is checked before it is declared gone.

| ID | Scenario | Pass |
|---|---|---|
| CX-1 | Cancel while a **local-engine** chunk is mid-inference, after its "chunk started" event. Real runs: a Chatterbox CPU chunk of at least 300 characters and a 3,000-character Kokoro chunk | C1 within 0.5 s; worker group gone and run CANCELLED within 2 s; nothing published; staging removed |
| CX-2 | A stub class-A worker that ignores the Cancel flag and SIGTERM while blocked in a native call, under each worker route | Ends within its route's T_stop through SIGKILL |
| CX-3 | Cancel mid-chunk for the Qwen3 and the OmniVoice worker | Within 5 s and 4 s; the process group is empty (`killpg(pgid, 0)` → ESRCH) |
| CX-4 | Cancel during Edge requests (2 and 8 files) and during finalization | Within 2.5 s; no request after the latch (the existing `test_cancel_semantics` invariants, run on the Mac) |
| CX-5 | Cancel during an FFmpeg step in each of the five non-TTS tools and during the TTS encode | Within 4 s; child reaped; nothing published |
| CX-6 | Pause, then Cancel while paused; Pause during a chunk | The file in progress finishes and the next does not start; Cancel meets C1–C3 |
| CX-7 | Cancel, then a new run with the same engine | The run succeeds; the worker is restarted and its cold load logged |
| CX-8 | Cancel inside the publication window (between staging and the rename), in both orders | The existing commit-ordering rule: nothing is published, or the whole file is published and reported |
| KX-1 | `kill -9` of the GUI during (a) local-engine inference, (b) Qwen3 inference, (c) OmniVoice inference, (d) an FFmpeg step, (e) an optional-setup pip install | Every ACT-owned descendant gone within 3 s; no file under a final name; the next launch recovers staging |
| KX-2 | `kill -SEGV` and `kill -ABRT` of the GUI (a simulated crash) during (a) and (d) | As KX-1 |
| KX-3 | SIGTERM (Activity Monitor "Quit") and Cmd+Q during (a) and (d) | Orderly path completes within 5 s; otherwise as KX-1 |
| KX-4 | `kill -9` of `bootstrap.py` during a pip install and during a model or FFmpeg download; closing the Terminal window during first-run setup (owner-manual) | pip tree and downloads gone within 3 s; the next launch repairs |
| KX-5 | Stage 0: SIGHUP (window close) during curl and during the probe; a probe that hangs; a probe that ignores SIGTERM | Children gone; the watchdog exits 3; partial artefacts removed by the trap or by the next run |
| KX-6 | The guardian killed by hand, then `kill -9` of the GUI while an FFmpeg step started after the restart is running | The new step is contained; the old group's residual is recorded |
| KX-7 | **Negative control:** KX-1(d) with the lifeline disabled by a test-only switch | The orphan **is** detected, proving the test can fail |
| KX-8 | **Identity control:** a registry entry whose pid now belongs to an unrelated process with a different start time | That process is untouched |
| KX-9 | **Spawn-site guard** (AST, like the existing `assemble` guard) | Every spawn goes through the ownership helper or is on the class-D allow-list |
| KX-10 | **Owner-manual:** Force Quit (Activity Monitor, or ⌥⌘⎋) during a Chatterbox chapter and during an M4B Maker build, then run the provided read-only check script | No ACT process remains; owner-signed |

**Placement by phase.**

| Phase | Tests |
|---|---|
| P1A | KX-4, KX-5 |
| P1B | CX-5, CX-8, KX-1(d, e), KX-2(d), KX-3(d), KX-6 to KX-10 |
| P2 (Kokoro) and P3A (Chatterbox) | CX-1, CX-2, CX-4 (P2 only), CX-6, CX-7, CX-8, KX-1(a), KX-2(a), KX-3(a) |
| P3B | CX-2, CX-3, CX-8, KX-1(b) |
| P4B | CX-2, CX-3, CX-8, KX-1(c) |

### 11.3 Filesystem semantics

- **Atomic replace:** `os.replace` = `rename(2)`, atomic on one APFS volume. **No-clobber publish:** `os.link` + `unlink` works on APFS/HFS+. On exFAT, FAT32 and some SMB shares `link()` fails, so publication there fails with a clear message (MAC-017). **Proposal:** use `renamex_np(staged, final, RENAME_EXCL)` through `ctypes` (libSystem), which is atomic no-clobber on APFS. Keep `os.link` as the second method, and fail clearly when neither is supported. Test on APFS and on an exFAT **disk image** created under `files/dev-work/` (`hdiutil create -fs ExFAT`, repo-contained; no system change).
- **Durability:** `os.fsync` on macOS does not flush the drive cache; `fcntl(F_FULLFSYNC)` does. Windows parity does not require it. Optional (D11a); default unchanged.
- **Locks:** `fcntl.flock` (BSD locks: per open file, released on close or process death) is the existing POSIX choice in `engine_lease.py` and is correct on APFS. Network volumes are unsupported for the app folder (documented).
- **Case sensitivity (MAC-015):** `venv_layout._CASE_INSENSITIVE`, `venv_integrity` and `maintenance._CASE_INSENSITIVE_FS` equate case-blindness with `os.name == "nt"`. Use the existing per-volume probe `importing.filesystem_is_case_insensitive` (it already handles darwin via `pathconf`). The Windows answer is unchanged.
- **Unicode:** APFS preserves the given form and compares normalization-insensitively. ACT normalises identities to NFC. Add NFD-named fixtures for import, output collision and Finder-created names (MAC-038).
- **Temp leftovers (MAC-016):** the macOS process start time is available through `sysctl` (`kern.proc.pid`, `kinfo_proc.kp_proc.p_starttime`, ctypes). Implementing it lets `work_area` reclaim crashed workspaces safely, as on Windows. Owner decision D11b; macOS also purges `/var/folders` on its own schedule.
- **Open-file limit (MAC-012):** at GUI start, raise `RLIMIT_NOFILE` soft to `min(hard, 4096)`. This is process-local and not a system change. Test Edge with 8 files under the default 256 first, to prove the need.
- **Memory reader (MAC-011):** implement `worker_limits.memory_info()` for darwin from `sysctl hw.memsize` and Mach `host_statistics64`, via ctypes. Free + inactive + purgeable pages approximate "available". `own_private_bytes()` comes from `task_info`/`phys_footprint`, or from `resource.getrusage` as a lower bound. Change the user text "kept for Windows" to "kept for the system" (string change: the Windows wording becomes platform-neutral; owner OK required because UI text changes on both platforms).
- **Sleep and App Nap (MAC-031):** no platform prevents idle sleep today, so this is a parity question, not a regression. macOS additionally may App-Nap an occluded GUI. P5 measures throughput with the window hidden. If needed, an owner-approved option spawns `/usr/bin/caffeinate -i -w <gui-pid>` (built-in; ends with the app; no settings change) during active jobs (D11d).
- **Quarantine of app-downloaded files:** curl does not set `com.apple.quarantine` (SUPPORTED UPSTREAM; eclecticlight 2025-12-08). Non-sandboxed processes without `LSFileQuarantineEnabled` (Python/pip/urllib) do not either (PLAUSIBLE; P1A checks with `xattr -l` on a downloaded wheel's `.so` and on the extracted interpreter). arm64 binaries must be at least ad-hoc signed to run at all, and wheels' native files are linker-signed. **The one quarantined file is the user's own downloaded ZIP content** (the `.command` and its sibling scripts): Archive Utility copies the flag onto every extracted file. Python *scripts* executed by the app-owned interpreter are data and are not Gatekeeper-checked. Only the `.command` the user double-clicks is.

---

## 12. Engine-by-engine proposed code changes

All changes are platform-guarded. Windows code paths, defaults, seeds, tuning and outputs stay byte-for-byte. No new user-facing tuning controls.

### 12.0 Shared engine scaffolding (P2–P4)

- A small `tts/device_policy.py` (or one function per engine runtime: whichever keeps the diff smallest) answers three questions:
  - *which device/dtype does this engine use on this platform*;
  - *how to synchronize*;
  - *how to read memory*.

  Windows keeps the exact current answers (`cuda`/CPU, fp16/bf16). darwin answers come only from experiment results recorded in Decisions.
- **No silent device fallback.**
  - Each run records the device and dtype it used.
  - `PYTORCH_ENABLE_MPS_FALLBACK` is **left unset** for every proof, so an unsupported op fails loudly. It is set only where an engine's accepted configuration provably needs it (e.g. Kokoro-on-MPS needs it for `aten::angle`, but Kokoro is not offered on MPS).
- **Identity keys include the device and dtype** (clone prompts, conditionals caches), so artefacts made on another device are never reused.
- **Memory hygiene on MPS:**
  - `torch.mps.empty_cache()` between chunks/files;
  - optional `PYTORCH_MPS_LOW_WATERMARK_RATIO`/`HIGH_WATERMARK_RATIO` set *before* torch import, only if measurement shows growth;
  - MPS work on one thread.
- **Speed and hardware wording comes from measurements.** The NVIDIA/Windows sentences stay for Windows. New macOS sentences say what was measured on which Mac.
- **Local-engine worker (§11.2.1).** Built once in P2 with Kokoro and reused unchanged by Chatterbox in P3A. Each engine adapter supplies only "load the model" and "synthesize one prepared chunk to PCM".
- **Containment (§11.2.2).** Every engine worker gets the lifeline as its first statements: the local-engine worker in P2, Qwen3 in P3B, OmniVoice in P4B.
- **Qualification verdicts (§15).** Each engine phase reports four separate verdicts: **F** functionality, **S** speech correctness, **Q** listening/WER quality and **P** speed/memory. P is judged against that engine's provisional budget D6-x, which the owner sets at the engine checkpoint, not at P5.
- Retry messages that blame Windows Application Control (`kokoro_synth.py:93,194-225`; `chatterbox_synth.py:6,1107`) become platform-neutral on darwin. The Windows wording is unchanged.

### 12.A Edge TTS (P2)

- **Code:** no engine change expected. The Edge path is pure Python with threads.
- **Platform layer only:**
  - the darwin `memory_info()` (MAC-011), so parallel planning stops assuming 4 GB;
  - `RLIMIT_NOFILE` (MAC-012);
  - MP3 encode flags (MAC-019 review).
- **Experiments:**
  - E-A1: `edge-tts --list-voices` contains all five voice IDs.
  - E-A2: one sentence per voice through ACT's own path.
  - E-A3: ACT runs with 2 and then 8 files at once, counting 403 and `NoAudioReceived` errors and retries.
  - E-A4: Cancel during synthesis and during finalization meets C1–C3 (CX-4: stopped within 2.5 s, nothing published); Pause, then Cancel (CX-6).
- **Provisional budget D6-E (owner, at P2 entry):** no speed budget, because Edge is network-bound. Reliability budget: in the 2- and 8-file runs every file completes within ACT's existing retry policy.
- **Expected limitation:** service-side throttling, voice removals and token changes are upstream risks. An outage is recorded as BLOCKED, not as a Mac defect.

### 12.B Kokoro-82M (P2; owner's preferred engine)

- **Needed:**
  - the device stays `cuda` else `cpu` (`kokoro_synth._local_model`), i.e. CPU on the Mac;
  - on darwin, the model load and the per-chunk pipeline call run in the **local-engine worker** (§11.2.1, MAC-043). It is built in this phase, with its lifeline (§11.2.2). The parent-side flow of `kokoro_file_to_mp3` (speech preparation, chunking, Cancel checks, assembly, one encode, publication) is unchanged;
  - verify the eSpeak NG short-root logic (`shared/espeak_data.py`) on macOS, inside the worker, including an app folder deep enough to push the data path past 160 characters (MAC-035), and the spaCy pinned-wheel route (`require_spacy_english`).
- **Optional (owner):** make the CPU choice explicit on darwin for readability. Kokoro MPS is **not offered**: the gain is small and the crash/allocator-growth risks are reported.
- **Experiments:**
  - **E-B1 (imports):** in one process, import torch 2.6.0, sklearn, numba, spacy, kokoro and `misaki.en`; load `en_core_web_sm`; exercise the espeak fallback on 20 out-of-dictionary words. The watch item is a duplicate OpenMP runtime abort (torch and sklearn/numba each bringing `libomp`).
  - **E-B2 (pronunciation, the accuracy proof):** run `KPipeline(model=False)` (G2P only) over `quality_corpus` texts A–C on the Mac and on Windows (HOME-PC). **The phoneme strings must be identical.** This is the strongest "same pronunciation" oracle available, because Kokoro's decoder adds unseeded noise and audio is never byte-identical even on one machine.
  - **E-B3 (CPU synthesis):** all nine voices through `synthesize_text_to_mp3` (worker path), plus one ≥30-minute chapter. Record RTF and the worker's peak footprint (`/usr/bin/time -l`). The four verdicts are separate:
    - **F:** no errors;
    - **S:** the §15 correctness screen;
    - **Q:** the listening/WER spot check;
    - **P:** against the provisional budget **D6-K**, set by the owner at P2 entry.

    Proposed starting values for D6-K: RTF ≤ 0.25, peak footprint ≤ 6 GB, growth < 10% after warm-up.
  - **E-B4 (Cancel):** CX-1 with a 3,000-character chunk in flight: stopped within 2 s, *not* "after the chunk". Also CX-2, CX-6, CX-7, the worker/in-process parity proof (§11.2.1), and Pause at the boundary.
- **If torch 2.6.0 fails on macOS 27** (E-B1/P1A): stop. The options are an owner decision, because torch is shared with Chatterbox, whose 0.1.7 metadata pins `torch==2.6.0` exactly:
  - (i) a darwin-only torch pin with Chatterbox gated off on macOS;
  - (ii) a newer torch on both platforms with Windows re-qualification;
  - (iii) keep investigating.

### 12.C Chatterbox Turbo (P3A)

> **Revision 2 (2026-11-16): SKIPPED BY OWNER DECISION on macOS** (Q1=A, Q2=A). None of the changes below is made in this programme, and Chatterbox is not implemented or downloaded on macOS, even if OmniVoice succeeds, without new owner authorization. Windows Chatterbox is unchanged. The list is kept as the design record.

- **Needed:**
  - `chatterbox_synth.select_device()` (L1088–1103): on darwin return **`cpu`** unless the owner has explicitly opted into MPS (a setting or env var, recorded per run). Windows order `cuda → mps → cpu` is unchanged.
  - Add the device to the conditionals cache key.
  - On darwin, `from_local` and `_synthesize_chunk` run in the **local-engine worker** built in P2 (§11.2.1). Only a Chatterbox adapter is added; the parent-side flow of `chatterbox_file_to_mp3` is unchanged. The worker's cold load (~3 GB) after a Cancel is measured and logged.
- **MPS opt-in only (if the owner wants it after E-C2):**
  - env vars set before torch import;
  - `empty_cache` between chunks;
  - single-threaded MPS;
  - a count of zero-probability `multinomial` picks.
- **Optional:** a test that `prepare_conditionals` yields float32 (guards against a future NumPy 2 bump re-triggering #499); a platform-neutral first-load retry message.
- **Experiments:**
  - **E-C0:** install (lock), `pip check`, every `.so` arm64, `chatterbox.tts_turbo` imports, Perth watermarker imports (`pkg_resources` via setuptools 80.9.0).
  - **E-C1 (CPU):** `from_local(…, "cpu")`, each of the six references, three seeded chunks (30/150/300 characters). Record RTF, peak footprint, finite samples and watermark detection.
  - **E-C2 (MPS, informational):** the same, without the fallback; log `driver_allocated_memory` per chunk; count zero-probability picks over ≥200 chunks; compare with CPU by WER and listening.
  - **E-C3 (soak):** one chapter (~50 chunks) on the chosen device. The P verdict uses the provisional budget **D6-C**, set by the owner at P3A entry. Proposed starting values: worker footprint < 8 GB (hard ceiling 16 GB), no swap growth, per-chunk time drift < 20%, CPU RTF ≤ 1.0.
  - **E-C4:** a conditionals cache made on one device is never reused on another (identity key).
  - **E-C5 (Cancel):**
    - CX-1 with a ≥300-character chunk mid-inference: stopped within 2 s;
    - CX-2, CX-6 and CX-7, the last including the measured cold reload;
    - KX-1(a), KX-2(a) and KX-3(a) during a chapter;
    - the worker/in-process parity proof on CPU with fixed seeds.

### 12.D Qwen3-TTS: CustomVoice and Voice Clone (P3B)

> **Revision 2 (2026-11-16): SKIPPED BY OWNER DECISION on macOS** (Q1=A, Q2=A). Neither CustomVoice nor cloning is implemented on macOS, and no Qwen3 model or engine is acquired. That includes the D12 POSIX authority port, which is no longer needed on macOS. Reopening needs new owner authorization. Windows Qwen3 is unchanged. The list is kept as the design record.

- **Needed (installer, MAC-013, D12):**
  - A POSIX implementation of the authority boundary used by `qwen3_packages`/`qwen3_engine_authority` (today `artifact_store.boundary`, CreateFileW handles). Use directory file descriptors opened with `O_DIRECTORY|O_NOFOLLOW` from the repo root down, `dir_fd=`-relative opens and renames, `O_NOFOLLOW` leaves, and `fstat` identity checks (`st_dev`, `st_ino`) before and after each consuming operation. Staging and the final location stay inside one pinned directory chain.
  - Same threat model as Windows: no parent can be replaced by a link between check and use. Documented limits are the same: it does not defend against an administrator rewriting bytes.
- **Needed (packages):**
  - `scripts/qwen3-requirements-macos-arm64.txt` (`--require-hashes --no-deps`, **PyPI only**: `qwen3_setup.PYTORCH_INDEX` = cu128 must not be used on darwin);
  - exactly one `torch==2.10.0` file (either the original or the `-2` rebuild, chosen by hash);
  - `torchaudio==2.10.0`;
  - Mac `soundfile`;
  - ACT's `sox` supply wheel;
  - `qwen3_package_manifest.TARGET`/`_compatible()` gain a reviewed `macosx_*_arm64` target;
  - `qwen3-artifacts.json` gains a darwin section.
- **Needed (worker):**
  - `qwen3_worker.choose_device`: `auto` on darwin resolves to **`cpu`**; `mps` only as an explicit, recorded choice;
  - each job states its dtype, **float32** on the Mac by default (Windows keeps bf16);
  - `_device_state`/sync gain MPS branches;
  - the out-of-memory match already covers "MPS backend out of memory";
  - the lifeline thread (§11.2.2) is the first statement of the worker entry, before any heavy import (POSIX only; the Windows Job Object path is unchanged).
- **Needed (runtime):**
  - `platform_supported()`/`platform_reason()`/`hardware_summary()` accept darwin **arm64** only after E-D1–E-D5 pass (refuse x86_64);
  - Mac speed text from measurements;
  - `detect_gpu()` (nvidia-smi) is not consulted on darwin;
  - `MachineGuard` gains a POSIX `flock` implementation (D13).
- **Model manifests:** unchanged (platform-neutral hashes).
- **Experiments:**
  - **E-D1:** install and import in the engine env. Only the flash-attn and SoX warnings are expected.
  - **E-D2:** load both models under CPU fp32, CPU bf16, MPS bf16 and MPS fp32. Record load time and peak RSS / driver memory; check that the speaker list contains `aiden` and `ryan`.
  - **E-D3:** CustomVoice A/B on 20 fixed chunks including short headings, fixed seeds, both voices, each configuration. Record RTF, runaway re-renders, non-finite failures and WER; listen. Pass: zero failures and WER no worse than CPU fp32.
  - **E-D4:** the six clones: create clone prompts from the unchanged references and transcripts; 5 chunks each on the chosen configuration; WER and identity listening.
  - **E-D5:** long form ≥ 1 hour.
    - RSS per chunk: fail at > 10% growth after warm-up.
    - Tk responsiveness.
    - Cancel mid-chunk (CX-3, within 5 s) and the stubborn-worker case (CX-2).
    - Lifeline on GUI kill (KX-1(b)).
    - The worker's lifeline thread starts before `import torch`.
  - **Provisional budget D6-Q (owner, at P3B entry, after E-D2 load figures):** proposed starting values are CPU fp32 RTF ≤ 3.0 (reports show about 2.6 on a base M4) and peak footprint ≤ 14 GB (11.3 GB reported). A P verdict outside budget does not close the engine; it requires an owner decision (offer with an honest speed note, or gate).
- **Stop rule:** if CPU fp32 fails E-D3 or E-D4 (F, S or Q), the Qwen3 macOS gate stays closed and the phase **STOPS** for a separate, explicit owner decision **D7-Q** (§20.3). Approval of this roadmap does not authorize shipping without Qwen3.

### 12.E OmniVoice 0.2.1 (P4A experiment, then P4B integration)

**P4A feasibility campaign. Revision 2 (2026-11-16) replaces the Revision 1 experiment text. Owner-gated, disposable, no ACT code, one bounded campaign (Q1=A).** It never writes to the six reference WAVs (read-only, hashes checked before and after), ACT's `.venv`, ACT's runtime data or ACT's prompt cache. Everything it writes stays in the ignored `files/dev-work/omnivoice-feasibility/`.

*What is already established without acquisition (2026-11-16, at `d6f21f9`; tool `files/dev-tools/macos_p4a_omnivoice.py`; evidence in `files/dev-work/omnivoice-feasibility/`):*
- **The exact acquisition set.** `macos_p4a_omnivoice_manifest.json` has SHA-256 `7932d4ef5b3ed0e531b958b9729f1de77ce27de37c755de290d5d9b896f62f4c`; that hash is the consent token.
  - **Wheels: 86, 246,737,206 bytes, all from `files.pythonhosted.org`.** Derived from upstream's own `uv.lock` at `5ba967c4` for darwin arm64 / CPython 3.12, without extras. The lock hashes to ACT's recorded `56f22586…`.
    - It re-derives byte-for-byte.
    - It differs from the Windows set only in two ways: `colorama` and `tzdata` are Windows-only, and `torch`/`torchaudio` are plain PyPI 2.8.0 instead of `+cu128`.
    - PyPI lists every wheel with the same SHA-256 and size, and none is yanked.
  - **Model: ACT's pinned `k2-fsa/OmniVoice@c5fdb5cc`, unchanged: 11 files, 3,267,467,171 bytes.** Hugging Face lists all 11 at that revision with the same sizes and LFS SHA-256s.
  - Nothing on this Mac can be reused: no Hub cache, and no model in the runtime data.
- **Upstream code at `5ba967c4`.**
  - It is device-neutral.
  - On MPS it places the audio tokenizer on the CPU itself ("higgs-audio-v2-tokenizer does not support MPS (output channels > 65536)").
  - Its only network path is `snapshot_download` for a non-local path. The local snapshot, the offline switches and ACT's audit hook close it.
  - Sampling adds Gumbel noise (`position_temperature` 5.0). CPU and MPS therefore draw different random streams: token agreement with the CPU is informational, and same-device repeatability is what is measured.
  - Token choice is `argmax` (`class_temperature` 0).
- **Upstream Apple reports.**
  - MPS noise in 0.1.x (#8, #10) was fixed by #13 before 0.2.1.
  - #172 reports garbled audio and NaN with MPS fp16 + SDPA on an M4 Mac mini (macOS 15.7.7). The workaround was fp32; the maintainer calls it device-specific.
  - #279 (open, unmerged) reports that the tokenizer runs on MPS.
  - pytorch#187280 reported corrupted MPS output on macOS 27 from MPSGraph `argmax`. It was fixed in torch 2.13 (Metal kernels) and in the OS. OmniVoice pins torch 2.8.0, so the CPU fp32 reference stays mandatory.
- **Indicative op probe.** It ran the app's torch 2.6.0 (not the pin) on macOS 27.0.1 (26A434), with MPS available in this agent session. All 28 cases agree with the CPU, fp32 and fp16, at OmniVoice's shapes: guided `log_softmax`, `argmax`, `max`, `topk`, SDPA.
- **Protected assets.** ACT's own `verify_reference` accepts all six references. 18/18 references, both transcript files and 28/28 previews are unchanged.
- **ACT's OmniVoice suites on macOS** (`2026-11-16_100729_focused_4489`): 540 passed, 79 failed, 5 skipped. All 79 failures predate this work and come from tests that simulate the Windows installer: `winreg` 64, `msvcrt` 5, `_winapi` 3, the Windows certificate store 1, Windows path or platform text 6. The skips are the four junction tests and the real-clone opt-in. None judges synthesis on macOS.

1. **Preconditions.**
   - The owner's consent to the token above.
   - The owner sets **D6-O**.
   - About 5.2 GB free (3.51 GB transfer, about 1.3 GB environment (estimated), about 0.4 GB outputs).
   - The app-owned arm64 CPython 3.12.15 (`files/runtime-data/python`).
   - Mains power and nothing else heavy running.
2. **Acquire and build** (S0):
   - `macos_p4a_omnivoice.py fetch --consent <token>` downloads through ACT's verified, resumable downloader.
   - A venv at `files/dev-work/omnivoice-feasibility/venv`, built from the app-owned interpreter. pip installs offline with `--no-index --no-deps --require-hashes`.
   - `pip check`; the installed set must equal the manifest; isolation is checked (no ACT `.venv` on `sys.path`, no user site).
   - Neither pip nor the Hub writes outside the area.
3. **Guards in every engine process:**
   - the inherited environment is cleared of `PYTHON*`, `PIP_*`, `HF_*`, `TRANSFORMERS_*`, `TORCH_*` and proxies;
   - then `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and an empty `HF_HOME` inside the area are set;
   - `PYTORCH_ENABLE_MPS_FALLBACK` stays **unset**;
   - ACT's own network audit hook and speech-recognizer refusal are imported from `tts/omnivoice_worker.py`, not copied;
   - the model loads from the local snapshot only.

   Each configuration runs in its own child process and process group, started and reaped by the harness.
4. **Text path = production.** ACT's `v1` speech preparation (OmniVoice route), `omnivoice_synth.plan_chunks` (≤ 300 characters), `derive_seed` and `GENERATION` (32 steps and the rest, unchanged), and ACT's assembly and one encode. An output differs from production only by device and dtype.
5. **Configurations, in this order:**
   - **C1 CPU fp32:** the correctness reference.
   - **C2 MPS fp32:** the preferred accelerated candidate, with the tokenizer on the CPU as upstream places it.
   - **C3 MPS fp16:** bounded and experimental: the S1 ladder only, and the pack only if C3 passes S1.

   **Not run:**
   - the tokenizer on MPS (the former step 9: it changes upstream's device placement);
   - the MPS fallback switch;
   - MLX or converted weights;
   - another revision;
   - changed generation settings;
   - other references;
   - upstream's own > 30 s sub-chunking, which ACT's 300-character plan never reaches.
6. **Stages:**
   - **S0:** acquire and build, then an offline load probe of C1–C3 (no audio). It records load time, footprint, the tokenizer's device and zero network attempts.
   - **S1, configuration screen:** first a neutral reference (`say` → `afconvert -f WAVE -d LEI16@24000`, with a known transcript), then Female 1. Eight items from one word to one 300-character sentence, on C1, C2 and C3. Then three items again on each device with the same seeds: same-device repeatability, bit-identical or not, is recorded.
   - **S2, compact owner listening pack:**
     - track A (836 characters, the Windows-approved OmniVoice A text), six voices, on C1 and on the best MPS configuration that passed S1, as blind-labelled pairs (12 files);
     - track B (2,084 characters, multi-chunk), one female and one male voice, on that configuration (2 files);
     - track A on C3 for two voices, only if C3 passed S1 (2 files).

     At most 16 MP3s plus an index, all NOT YET REVIEWED. The 12 Windows-approved tracks are not on this Mac (only their index), so the owner compares from memory or later on HOME-PC.
   - **S3, stability:** 50 back-to-back `generate()` calls in one process on the candidate MPS configuration, one sentence of about 200 characters. Each call records RTF, `phys_footprint`, `torch.mps.current_allocated_memory()` and `driver_allocated_memory()`; growth is measured after a 5-call warm-up. C1 gets 10 calls, as an informational trend.
   - **S4, termination:** during `generate()` on C1 and on C2, SIGTERM, then SIGKILL of the group after 2 s. The process must be gone within the bound, no orphan may remain, a fresh process's MPS driver memory must be back at its baseline, and nothing may be named as a final output.
7. **Automated measurements per output:**
   - finite samples (no NaN or Inf);
   - peak and clipped-sample count;
   - characters per second within 8–20 (the references speak about 12–14);
   - leading and trailing silence, and any internal silence over 2 s;
   - the 50 ms RMS-envelope coefficient of variation and the spectral flatness, against C1 on the same item (the noise signature of #8 and #172: below 0.5× or above 2× C1 is flagged);
   - RTF; cold load time; peak footprint.

   **WER: NOT RUN** (no ASR; Whisper needs D15). OmniVoice's own recognizer is refused.
8. **Verdict per configuration (F/S/Q/P, §15):**
   - **BLOCKED (never FAIL):**
     - consent not given;
     - a pinned file cannot be acquired at its size and hash;
     - MPS unavailable in the run's session (C2/C3 only; the owner then runs the same command from Terminal);
     - a disk or memory precondition not met.
   - **Technical FAIL** of a configuration:
     - any non-finite output;
     - an op error with the fallback unset, or running out of memory at ACT's chunk sizes;
     - any network attempt;
     - the pinned set not installing or importing on darwin;
     - an output the screen flags as noise or garble that listening confirms;
     - missing or invented words obvious on listening;
     - a Cancel bound exceeded, or an orphan.
   - **Technical PASS:** none of these. A technical PASS goes to the owner's ears. Generating a file is never a quality verdict.
   - **P is judged against D6-O.** Proposed values for the owner to set:
     - MPS RTF ≤ 1.0 (wall, per file);
     - CPU RTF ≤ 3.5;
     - peak footprint ≤ 10 GiB;
     - growth < 10 % after warm-up (fixed).
   - **D6-O as set by the owner (2026-11-16, Revision 2a; this supersedes the practicality line proposed above).** The four proposed values are adopted as **provisional practicality targets, not automatic rejection thresholds**. Each measurement is evaluated and reported separately.
     - Technical correctness, performance practicality and owner-perceived narration quality are **separate verdicts**.
     - A configuration that is technically correct but outside a target is classified **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**, with the measured amount, unless its resource behaviour is unsafe. A small miss never activates the fallback.
     - Unsafe resource behaviour fails the safety and reliability gate (S), and can end that configuration's run at once. That covers a serious memory-pressure event, unsafe growth, running out of memory and process instability. A memory-unsafe run is never continued just to collect benchmarks.
     - The owner keeps the final decision on acceptable speed, footprint and audio quality. Audio quality and reliability outrank speed.
     - **Verdict letters in P4A:** F = functional execution; S = safety, stability and containment; Q = audio quality (the owner's ears only, never inferred from F); P = performance and practicality against the D6-O targets.
   - **WER: NOT RUN — NO AUTHORIZED ASR MODEL** (D15 deferred by the owner until after the listening verdict). Low WER is never inferred from intelligibility or the integrity screen.
   - **Q is the owner's verdict only.**
9. **Campaign outcome (exactly one), bounded:**
   - **No tuning loop.** Settings, revisions and references never change. At most one stage rerun after a harness defect; never after an engine defect.
   - **Revision 2a outcome states (owner, 2026-11-16).** These replace the three states first proposed here, which are kept below as the record. Exactly one applies:
     1. **`P4A TECHNICAL PASS — OWNER LISTENING PENDING`:** at least one of C1/C2 is a technical PASS (F and S) and within every D6-O target. STOP for the owner's listening.
     2. **`P4A TECHNICAL PASS — PERFORMANCE EXCEPTION / OWNER DECISION PENDING`:** a technical PASS exists, but every passing configuration misses at least one D6-O target safely. STOP for the owner's listening and practicality decision. If the only passing configurations are substantially impractical, the specific reason is documented for the owner. The fallback is not started automatically unless a technical or safety failure is independently demonstrated.
     3. **`FALLBACK CONDITION MET — TECHNICAL OR SAFETY FAILURE`:** C1 and C2 both fail F or S (C3 alone never carries OmniVoice), or the pinned set cannot be installed or run on darwin within this scope. Q1=A applies, as below.
     4. **`P4A BLOCKED — INSUFFICIENT EVIDENCE OR UNAVAILABLE PREREQUISITE`:** a blocker prevents a verdict.

     After 1 or 2, a negative owner listening verdict activates the approved fallback (Q1=A), whatever the technical and performance results. An owner acceptance of a named configuration lets P4B be proposed for its own authorization.
   - *Revision 2 states, as first proposed (superseded by Revision 2a):*
   - **`P4A TECHNICAL PASS — OWNER LISTENING PENDING`:** at least one of C1/C2 is a technical PASS and within D6-O. STOP for the owner's listening.
     - If the owner accepts a named configuration, P4B can be proposed. It needs the owner's acceptance and its own authorization.
     - If the owner rejects it, the fallback activates (Q1=A).
   - **`FALLBACK CONDITION MET`:** any of the following, recorded with the evidence:
     - C1 and C2 both technical FAIL (C3 alone never carries OmniVoice);
     - the pinned set cannot be installed or run on darwin within this scope;
     - every technically passing configuration is outside D6-O. This is the proposed practicality line for Q1, confirmed by the owner when D6-O is set. **Superseded by Revision 2a:** a safe budget miss is a PERFORMANCE EXCEPTION for the owner, not the fallback.

     Then OmniVoice integration on macOS stops, and P4C follows directly. Chatterbox and Qwen3 are not taken up in its place.
   - **`P4A BLOCKED`:** a blocker above prevents a verdict. It is reported and never used to reject an untested engine.
10. **Afterwards:** the area (about 5 GB) is kept until the owner decides. If P4B goes ahead, ACT's own installer may adopt the verified model bytes after the same hash checks, by owner decision then.

*Machine time (estimate from REPORTED rates: CPU RTF about 3, MPS about 0.4–1):* about 15 minutes of downloads on a fast link, about 1–1.5 hours of synthesis, run sequentially.

**Executed 2026-11-16 (Decisions, P4A results entry; evidence in `files/dev-work/omnivoice-feasibility/`): `P4A TECHNICAL PASS — OWNER LISTENING PENDING`.**
- **Acquisition:** only the consented 97 files, verified (97/97). The environment is offline and hash-locked; isolation is verified.
- **C1 CPU fp32:** F and S PASS, within every D6-O target:
  - wall RTF 1.31–1.66;
  - peak 4.05 GiB;
  - growth +0.08 %.
- **C2 MPS fp32:** F and S PASS. **PERFORMANCE EXCEPTION — OWNER DECISION PENDING** on speed:
  - wall RTF 0.914–1.190 against ≤ 1.0;
  - peak 9.54 GiB (within);
  - 50-call growth +1.11 %, MPS driver memory flat;
  - outputs bit-identical across all 50 calls.
- **C3 MPS fp16** (bounded: S0, S1 and two samples): clean; RTF 0.90–1.00.
- **S4:** a SIGTERM ends the worker's group in 0.03–0.07 s with the memory recovered. ACT's existing supervisor Cancel takes 2.24–2.29 s (within T_stop ≤ 4 s).
- **Not yet judged:** Q is the owner's (16-MP3 blind pack, NOT YET REVIEWED). WER: NOT RUN — NO AUTHORIZED ASR MODEL.
- **Pack delivery:** the pack is not on GitHub (no history commit; no practical artifact path without a workflow). It waits for the owner's choice of route. *(Later: delivered through the temporary GitHub draft release `447445728`, protected, never published.)*

**Owner acceptance (2026-11-16, Revision 3; Decisions, P4A acceptance entry): `P4A OWNER ACCEPTED`.** P4A evidence SHA `6fb98e6`.

| Item | State |
|---|---|
| Six OmniVoice voices | Owner listening ACCEPTED (all 16 MP3s; no meaningful X/Y/Z difference heard) |
| C1 CPU fp32 | Technical PASS; accepted alternative, explicitly selectable |
| C2 MPS fp32 | Technical PASS; **preferred and default**; its speed exception explicitly accepted for integration planning |
| C3 MPS fp16 | Experimental; not production-approved, not offered |
| WER | NOT RUN — no authorized ASR model (D15 deferred) |
| Independent Codex review | Bounded encoded-audio integrity PASS of the 16 MP3s; no listening, no ASR; not full-product verification |

The speed exception waives no memory, safety, Cancel, functional or long-form requirement. P4A results are evidence for P4B's entry, never a P4B PASS.


**P4B integration (only for an owner-accepted P4A configuration).** The call sites to change (`omnivoice_worker.py` unless noted):

- **Device refusals and GPU checks:**
  - L178 and L219: the `device != "cuda"` refusals.
  - L246–250 `_cuda_usable` → per-platform availability (`torch.backends.mps.is_available()` on darwin).
  - L407/L559: the GPU-usable checks.
- **Device selection and synchronization:**
  - L415/L572: `device_map="cuda:0"` → the policy device.
  - L417, L430, L453, L564, L574: `torch.cuda.synchronize` (raises on a Mac build) → policy sync.
  - L450: `torch.cuda.manual_seed_all` (no-op on a Mac). `torch.manual_seed` already seeds MPS.
- **Memory and device reporting:**
  - L253–255 `_memory`: `torch.mps.*` (the CUDA calls would silently report 0).
  - L435–436 and L580: `get_device_properties` and the `"cuda:0"` literal; the device name comes from `sysctl machdep.cpu.brand_string`.
  - L467–470: peak figures. MPS has no peak API, so use the maximum of per-chunk samples.
  - L563: the cuda/fp16 kernel test.
  - L587: `empty_cache`.
- **Outside the worker:**
  - `omnivoice_synth.py` L74–75 (`DTYPE`/`DEVICE`) and L307 (memory wording);
  - `omnivoice_runtime.py` L547–550 (hardware disclosure), L603–605 (`platform_supported`), L615–618 (`detect_gpu`/NVIDIA), L1343–1347 and L1363;
  - `prompt_identity` (~L1293–1304) gains the device (on MPS the tokenizer runs on CPU; on Windows on CUDA);
  - `omnivoice_setup.py` L657–658 (`proof_job` fp16/cuda);
  - `omnivoice_manifest.json` darwin wheel list;
  - `optional_setup.py` L475–482, L547, L638–650 (texts, GPU facts: Apple GPU vs NVIDIA);
  - `optional_setup_health.py` L111;
  - `MachineGuard` POSIX lock;
  - the lifeline thread (§11.2.2) at the very top of the `omnivoice_worker` entry, before `import torch` (POSIX only).
- **Already neutral:** the `fcntl` lock (L131–157), the network guard, the CPU prompt load, `_is_oom`, the long-path checks (they return early off Windows) and the POSIX `site_packages` branch.

**If no configuration passes, or the owner rejects the audio (Revision 2, Q1=A):** the owner's decision is already given, so no separate D7-O is asked. The precise failure and its evidence are recorded, OmniVoice integration on macOS stops, and P4C removes the six OmniVoice voices from the macOS user-facing experience (Q2=A; not "visible but unavailable"). Windows OmniVoice, the six voice identities, references, transcripts and the manifest stay unchanged. Chatterbox and Qwen3 are not taken up in its place. Nothing is substituted. An MLX port would be a separate, owner-decided project, because its weights differ.

### 12.F macOS engine capability policy and the approved fallback (Revision 2; Q2=A; implemented in P4C)

**When it applies.** Only after the P4A outcome is recorded. Mac engine controls are not removed before the fallback condition is established. Two configurations are possible:

| Configuration | When | macOS TTS roster | Setup choices offered on macOS |
|---|---|---|---|
| **Edge + Kokoro (the approved fallback)** | P4A `FALLBACK CONDITION MET`, or the owner rejects OmniVoice's audio | Edge TTS, 5 voices; Kokoro-82M, 9 voices: **14 voices** | Kokoro's existing optional model-download checkbox only (existing consent rules and working defaults). Edge needs no local model |
| **Edge + Kokoro + OmniVoice** | An owner-accepted P4A configuration, integrated and proven in P4B | + OmniVoice, 6 voices: 20 voices | Kokoro's checkbox, and an OmniVoice choice built on separately verified and approved macOS setup behaviour |

**Revision 3 (2026-11-16): the configuration is decided — Edge + Kokoro + OmniVoice, 20 voices** (P4A OWNER ACCEPTED; P4C implements it after P4B's acceptance). The macOS first-run optional TTS choices are exactly two: the Kokoro model download and the OmniVoice installation. Chatterbox and Qwen3 must be absent from: voice dropdown entries, engine group headings, download checkboxes, setup-wizard choices, Install & Continue entries, repair and optional-install actions, promotional descriptions, availability notices, and launcher, settings or preferences options. Visual-only hiding is not enough: macOS dispatch refuses them safely. No source, manifest, identity or Windows setup capability is removed.

**Status (Revision 3e, 2026-11-16): IMPLEMENTED and TESTED (automated) in P4C; owner acceptance pending** (§19 P4C status; Decisions, P4C entry). The policy is `scripts/shared/engine_policy.py`; the guards sit where the list below says ("Where the P4C guards go"), plus the conversion worker, the acquirer and Clear Downloaded Data / Repair App Environment wording. The inventory below describes the tree **before** P4C (`d6f21f9`).

In both, Chatterbox Turbo (6 voices) and Qwen3 (2 CustomVoice + 6 clone voices) are **SKIPPED BY OWNER DECISION** and absent on macOS. Windows keeps the complete released roster (34 identities) and every engine's setup, unchanged. All six application tools stay on both platforms.

**One policy, decided from the real platform.**
- A single central module answers which engines this platform offers. The question is asked from `sys.platform` (and the machine) at startup, with an injectable `platform=` for tests. There is no user toggle and no Mac compatibility mode.
- Everything below asks that module; no surface keeps its own list.
- The 34 `(backend, voice_id)` identities stay in the registry. The policy filters what macOS *offers*; it never deletes, renames or re-numbers an identity.
- Narrow platform guards at each consumer, no duplicated application, nothing deleted:
  - the Chatterbox, Qwen3 and OmniVoice Windows code;
  - the 18 references, both transcript sets and the 28 previews;
  - the manifests and the pinned requirements, including dormant dependencies in the shared environment. No slimming is required.

**What the macOS user must not see, under the fallback:**
- **The voice list:** the voice-selection dropdown, its group headings and engine categories.
- **Setup:**
  - the download/model-install checkboxes;
  - the Install & Continue optional engine choices;
  - optional-engine repair actions;
  - setup-wizard descriptions.
- **Notices and other controls:**
  - engine-specific hardware and speed notices;
  - menus, details and licence links, and other controls;
  - any status message suggesting the installation of an unsupported engine.

**What must stay:** install and repair for Python, FFmpeg, the core application dependencies and Kokoro; Kokoro's consent rules and defaults; Edge with no local model.

**Rejected safely, not just hidden.** On macOS, runtime dispatch refuses a non-offered engine's voice with a plain message and no fallback to another voice. That covers the panel's Create path, the sample/preview helpers and any CLI route.
- Nothing persists a voice today (see below). If a restored panel state or an imported file ever names one, it is replaced by the platform's default voice, and that is logged. P4C pins on darwin that no setting can carry a voice.
- The same setting on Windows is honoured as before.

**Tests (P4C).**
- **The policy itself, for darwin and win32:**
  - the two rosters pinned exactly: darwin 14 (or 20), win32 34;
  - each surface on darwin;
  - dispatch refusal for every non-offered engine;
  - a stale-settings restore;
  - the setup wizard offering only Kokoro's checkbox.
- **Windows protection:** the Windows-branch suites of every touched shared file, run on the Mac through the platform seams; the touchpoints listed for the HOME-PC regression.
- **Darwin skip rules:** the 79 Windows-installer simulation failures in the OmniVoice suites (§12.E) and their Chatterbox/Qwen3 counterparts get exact darwin skip rules or platform seams, with reasons. No test is weakened to pass.

**What macOS shows today (read-only inventory at `d6f21f9`, 2026-11-16; to change in P4C only).** There is no central policy: each engine gates itself, and nothing is hidden on darwin.
- **Registry:** `tts/voice_registry.py` lists all 34 rows (`VOICES`, `BACKENDS`). It has no platform field. The default is Edge Steffan.
- **TTS panel:** the combobox in `tts/epub2tts_gui.py` lists all 34 labels.
  - **Qwen3 and OmniVoice** answer `platform_supported()` = win32 only, so a Mac user sees their voices with a red "they currently need Windows" status. `run_job` shows a "Voice unavailable" dialog, and their synth entry points refuse again.
  - **Chatterbox has no platform gate.** Today it is offered on a Mac:
    - the wizard checkbox reads "best with an NVIDIA GPU";
    - Install & Continue offers its model;
    - `chatterbox_synth.select_device()` would run it on MPS, in the app's own process, outside the macOS local-engine worker (which has only a Kokoro adapter).

    Under Q2 it is removed with the others in P4C. It is not changed earlier, because the owner said no Mac engine control is removed before the fallback condition is established.
- **First-run wizard:** `shared/bootstrap.py` `OPTIONAL_CHOICES` has five choices with no platform filter: Kokoro default on; the Qwen3 and OmniVoice descriptions say "Windows only". The review panel (`shared/optional_setup_panel.py`) lists the blocked choices as "cannot be installed now (… need Windows …)".
- **Install planning:** `tts/optional_setup.plan`/`estimate` mark Qwen3 and OmniVoice UNSUPPORTED on darwin. Kokoro and Chatterbox are judged only on the Python version.
- **Persistence:** nothing persists a voice or engine (`shared/settings.py`, `config.USER_STATE_SETTINGS`, pinned by `test_voice_labels.py`), and every session starts on Steffan. A stored or imported setting cannot name an unsupported voice today; P4C keeps it that way and pins it on darwin.
- **Retry:** `retry_failed` re-runs a frozen job without asking the panel again. The P4C dispatch refusal must therefore sit at the engine entry points, not only in the panel.
- **Wording that names other engines on macOS:**
  - `launcher.py` ("Kokoro, Chatterbox and Qwen3 voices");
  - the maintenance and preferences text naming "Install / repair Qwen3 voices";
  - fallback sentences naming Chatterbox in `qwen3_runtime` and `epub2tts_gui`.
- **Tests that pin today's macOS behaviour and would flip in P4C:**
  - the "visible but unavailable" darwin pins in the Qwen3 and OmniVoice suites;
  - the 34-value combobox and roster counts (about 15 places);
  - the five-checkbox wizard pins;
  - the gate's darwin skip `qwen3-windows-only (P3B decides macOS)`, whose reason changes to "SKIPPED BY OWNER DECISION".

  Each becomes platform-dependent. None is weakened.

**Where the P4C guards go:**
- the policy over the registry (labels and lookups, Steffan stays the default);
- the combobox values and `run_job`;
- the dispatch and the engine entry points (a Chatterbox refusal on macOS is new);
- `voice_install.component_for`/`installable` and the Install & Continue dialog;
- the wizard's choices, sizes and the Qwen3 note;
- the component vocabulary as seen by `optional_setup.plan`/`estimate`, the client and the worker requests;
- `optional_setup_health`;
- `generate_voice_samples` selection;
- the user-facing copy listed above.

---

## 13. Immutable audio, voice and speech-processing contracts

These hold for every phase. Any test or change that would alter them is a stop condition.

1. **Voice roster: 34 stable `(backend, voice_id)` identities in five families.** Labels, groups and order are unchanged; there are no new voices and no macOS-only voices.

   | Family | Count | Voice IDs |
   |---|---|---|
   | Edge | 5 | `en-US-SteffanNeural`, `en-US-AndrewNeural`, `en-US-AriaNeural`, `en-US-AvaNeural`, `en-US-JennyNeural` |
   | Kokoro | 9 | `af_heart` (default), `af_bella`, `am_michael`, `am_fenrir`, `am_puck`, `am_onyx`, `bf_emma`, `bm_george`, `bm_daniel` |
   | Chatterbox Turbo | 6 | `chatterbox-female-1`, `-female-2`, `-male-1`…`-male-4` |
   | Qwen3 | 8 | `qwen3-aiden`, `qwen3-ryan` (CustomVoice); `qwen3-female-1`, `-female-2`, `-male-1`…`-male-4` (Voice Clone) |
   | OmniVoice | 6 | `omnivoice-female-1`, `-female-2`, `-male-1`…`-male-4` |

   On macOS, an engine that is not proven shows its voices as **visible but unavailable**, with an accurate reason (the existing `platform_supported()`/`platform_reason()` UX). They are never hidden, renamed, remapped or substituted.

   **Revision 2 (Q2=A):** this applies only until P4C. Once the P4A outcome is recorded, P4C removes every engine that is not offered on macOS from the macOS user-facing experience, through the capability policy of §12.F. The identities stay in the registry, and are still never renamed, remapped or substituted. Windows is unchanged.
2. **18 clone-reference WAVs**, exactly as bound by `scripts/tts/data/clone_references.json` (verified on this Mac in Phase 0: 18/18 SHA-256 and git-blob match):

   | Backend | Voice ID | File (`files/Cloned-Voice-Uploads/…`) | Frames @ Hz | WAV SHA-256 (prefix) | Transcript SHA-256 (prefix) |
   |---|---|---|---|---|---|
   | chatterbox | `chatterbox-female-1` | `Chatterbox/Chatterbox - Female 1.wav` | 481091 @ 44100 | `994b700eb4fa65ff` | `6438a7fcd24a663e` |
   | chatterbox | `chatterbox-female-2` | `Chatterbox/Chatterbox - Female 2.wav` | 459480 @ 44100 | `a1a6530fb06d8199` | `6c1a116da4c9af5c` |
   | chatterbox | `chatterbox-male-1` | `Chatterbox/Chatterbox - Male 1.wav` | 450083 @ 44100 | `8f1999ded53fefd8` | `93cb79177664e36f` |
   | chatterbox | `chatterbox-male-2` | `Chatterbox/Chatterbox - Male 2.wav` | 393705 @ 44100 | `d8939ad19dc90718` | `79d1806d7cf7608f` |
   | chatterbox | `chatterbox-male-3` | `Chatterbox/Chatterbox - Male 3.wav` | 330750 @ 44100 | `152b8aa13fbf23d5` | `acd64ab91990b199` |
   | chatterbox | `chatterbox-male-4` | `Chatterbox/Chatterbox - Male 4.wav` | 428472 @ 44100 | `9eb5722dee8fc186` | `c589a087b8b045e0` |
   | qwen3 | `qwen3-female-1` | `Qwen3/Qwen3 - Female 1.wav` | 360000 @ 24000 | `b740b9ed352e6a32` | bundle `bundled_clone_transcripts.json` |
   | qwen3 | `qwen3-female-2` | `Qwen3/Qwen3 - Female 2.wav` | 360000 @ 24000 | `428d3869b6bc7a26` | bundle |
   | qwen3 | `qwen3-male-1` | `Qwen3/Qwen3 - Male 1.wav` | 360000 @ 24000 | `45fbfba0815b76b8` | bundle |
   | qwen3 | `qwen3-male-2` | `Qwen3/Qwen3 - Male 2.wav` | 360000 @ 24000 | `592139a28e82aaf5` | bundle |
   | qwen3 | `qwen3-male-3` | `Qwen3/Qwen3 - Male 3.wav` | 360000 @ 24000 | `4ab6bd671add539a` | bundle |
   | qwen3 | `qwen3-male-4` | `Qwen3/Qwen3 - Male 4.wav` | 360000 @ 24000 | `47eff938180617c0` | bundle |
   | omnivoice | `omnivoice-female-1` | `OmniVoice/OmniVoice - Female 1.wav` | 354241 @ 44100 | `438329e6c39917b5` | `a08d518bc256beba` |
   | omnivoice | `omnivoice-female-2` | `OmniVoice/OmniVoice - Female 2.wav` | 320414 @ 44100 | `909a0ea793538579` | `927d8f7e5825034d` |
   | omnivoice | `omnivoice-male-1` | `OmniVoice/OmniVoice - Male 1.wav` | 451022 @ 44100 (10.227 s, the hash-bound owner exception) | `7753385380675913` | `93cb79177664e36f` |
   | omnivoice | `omnivoice-male-2` | `OmniVoice/OmniVoice - Male 2.wav` | 391826 @ 44100 | `0b2918438b877bbe` | `79d1806d7cf7608f` |
   | omnivoice | `omnivoice-male-3` | `OmniVoice/OmniVoice - Male 3.wav` | 327931 @ 44100 | `5dc34276f15cb42b` | `acd64ab91990b199` |
   | omnivoice | `omnivoice-male-4` | `OmniVoice/OmniVoice - Male 4.wav` | 217055 @ 44100 | `31d7305ce0257a56` | `89413cea1f002d79` |

   Full digests live in `clone_references.json`. They are read only. Every engine phase re-verifies all 18 before and after its real-runtime tests. No crop, resample, re-encode or derivative is written next to them; derivatives and caches belong in `files/runtime-data/`.
3. **Transcripts.** `scripts/tts/data/bundled_clone_transcripts.json` (Qwen3) and the owner-written Chatterbox/OmniVoice texts in `clone_references.json` are unchanged and remain LF (`.gitattributes`). Their hash validation stays fail-closed. There is no ASR and no Whisper in normal use.
4. **28 historical preview WAVs + `previews.json`** are unchanged; they are not regenerated on the Mac.
5. **Speech preparation.** There is one pipeline (`tts/speech/pipeline.prepare`), called once per file in the **parent** process with the run's frozen `SpeechPrepSnapshot`, before chunking or worker IPC. `DEFAULT_SPEECH_PREP = "v1"`; `off` still works. `modes.json` engine rows, `units.json`, `lexicon.json`, `glossary.default.json`, `RULESET_VERSION` and the 60 historical G1 verdicts are unchanged. No macOS-specific normalization, and no second pipeline.
6. **Generation baselines.** Chunk ceilings, timing presets, seeds bases, OmniVoice `GENERATION` (32 steps…), Qwen3/Chatterbox tuning and the 24 kHz assembly are unchanged. Device or dtype can differ on the Mac only where §12 says so, and that difference is **recorded in prompt and identity keys**: a Mac-built clone prompt must never be reused as if it were a CUDA prompt, or the reverse. Mac audio will not be sample-identical to Windows. The acceptance oracle is the owner's listening, WER and stability (§15), not byte equality.
7. **Outputs.** Unchanged: `<source-stem>-<frozen-display-label>.mp3`, collision numbering, MP3 format and bitrate, chapter metadata, M4B atoms (incl. series and movement), the Nero chapter recovery, the never-overwrite default and atomic publication. A cancelled or failed job never publishes an incomplete file under a final name.

---

## 14. Test coverage and native verification design

### 14.1 Coverage matrix

| Layer | What | Where / how | When | Counts as macOS proof? |
|---|---|---|---|---|
| Platform-neutral unit tests | The existing ~13,000+ ordinary tests (306 files) run natively on macOS: speech, planning, naming, metadata, job control | `files/tests/` via the gate's `focused` mode with `--test` ids during phases | Each phase: only touched modules | Yes, when run *on the Mac* |
| macOS-only existing tests | 39+ aqua geometry/branch tests (skipped on Windows) | `test_m4b_layout.py`, `test_mp3_tool_layout.py`, `test_ui_theme.py` | P1B | Yes |
| Windows-mechanism tests | Junctions, Job Objects, Win32 handles, named mutex, `pythonw`, Windows process identity, `.cmd` stand-ins (48 files carry platform skip markers) | Skipped on darwin by a **reviewed `darwin` skip policy** with exact reason patterns and maximum counts | Every macOS run | **No.** Reported as `NOT APPLICABLE ON MACOS (n)`, never folded into PASS |
| macOS counterparts of Windows mechanisms | Process-group kill, lifeline, `flock` engine lock, `renamex_np`/`link` publication, `pathconf` case probe, darwin memory reader, symlink-based tests where Windows uses junctions | New tests beside the Windows ones | P1A/P1B | Yes |
| Native arm64 dependency checks | Lock completeness; `pip check`; every `.so`/`.dylib` in each env is arm64 (`lipo -archs`); `import` proofs (bootstrap `prove_required_imports`); no x86_64 artefact | New focused tests + bootstrap proofs | P1A (app), P3B (Qwen3), P4B (OmniVoice) | Yes |
| Stage 0 and launcher | Every state in §8.2, against fixture archives:<br>• size/hash mismatch, declined consent, interrupted download, truncated archive;<br>• unsafe members: absolute, `..`, link outside the root, setuid, device file;<br>• a stale staging folder from a dead pid;<br>• watchdog: a hung probe and a SIGTERM-ignoring probe;<br>• Tk proof failure, healthy fast path, repair exit 3, translocated location;<br>• SIGHUP during curl and during the probe (KX-5) | `files/tests/test_bootstrap_host_macos.py` (bash run under a bounded subprocess) | P1A | Yes |
| Clean-install evidence | SIMULATED (PATH-restricted with recording shims; linkage-verified) and REAL CLEAN, exactly as defined in §8.2 | Disposable clean worktree (simulated); a clean Mac or VM (real, D18) | P1A (simulated), P7c (real, mandatory) | Yes, under the class stated; SIMULATED never stands in for REAL CLEAN |
| GUI (automated, in-process) | Widget construction for all six tools; `event_generate` for Cmd+Q, Select-All; worker→UI thread stress; Tk version and windowing system | Tk tests on the Mac display | P1B | Yes |
| Acceptance journeys (55 required + 1 optional) | Each Windows journey's *behaviour* on macOS, through the darwin acceptance map (§14.3): native automated counterpart, owner-manual check, or a reviewed not-applicable reason | In-process journey driver (`adapters/macos/`, no Accessibility/Screen Recording grant) + real media + owner checklist | P1B (map + five tools), P2–P4 (TTS journeys), P5 (complete) | Yes; manual items owner-signed and bound to the candidate SHA |
| GUI (owner manual) | Light/Dark, Retina, min/max geometry, dialogs, Finder reveal, focus at launch, Dock/menu name, Terminal auto-close, Gatekeeper double-click | Checklist in Handoff | P1B, P5; Gatekeeper on the quarantined archive at P6a (rehearsal) and P7c (exact archive) | Yes (owner-signed) |
| Subprocess/cancellation | The bounded Cancel contract C1–C5: CX-1…CX-8 (§11.2.3) for every engine route and every FFmpeg tool, mid-inference included; two app copies + engine lock | Focused tests + bounded real runs | P1B (FFmpeg), P2–P4 (engines) | Yes |
| Containment (negative) | GUI and setup `kill -9`, simulated crash (SEGV/ABRT), SIGTERM, Cmd+Q, closed Terminal, guardian loss, negative and identity controls, spawn-site guard, owner Force Quit: KX-1…KX-10 (§11.2.3) | Focused tests + disposable app copies; owner-manual KX-4 (Terminal close) and KX-10 | P1A (setup), P1B (GUI/FFmpeg), P2–P4 (workers) | Yes |
| Fault injection | Disk full (small `hdiutil` image), corrupted model file (flip a byte in a *copy* under scratch), failed repair (network off), interrupted publication (kill between stage and link), exFAT target, read-only target, NFD names | Repo-contained scratch under `files/dev-work/` | P1B, P2–P4, P5 | Yes |
| Engine real synthesis | Opt-in, offline, bounded: each engine's voices on short multi-chunk texts | Guarded tests keyed by env vars (precedent `ACT_OMNIVOICE_P1_REAL=1`), each with its own exact skip rule | P2–P4 | Yes, only when actually run |
| Install/repair/recovery | Fresh first run, healthy relaunch (no work), `.venv` damage → repair, engine carry-across, interrupted engine install (pip killed → no orphan; staging recovered), Windows-origin `runtime-data` | Disposable worktree copies under `files/dev-work/` | P1A, P3B, P4B, P5 | Yes |
| `fresh-macos` qualification (**mandatory**) | Extracted archive → stage 0 → first run → all six tools open → `.venv` damage → repair → relaunch → interrupted install → recovery. Automation is optional (D9b); an owner-manual run against the written procedure, with signed evidence, satisfies it | Rehearsal on the P6a dry-run archive; **REAL CLEAN** on the exact release archive | P6a (rehearsal), P7c (binding) | Yes; reported as its own qualification verdict, never folded into the gate PASS |
| MP3/M4B/metadata/image functional | Real media from `files/test-files/` via existing env-var fixtures; xHE-AAC via `aac_at` (the owner's real file, §11.1); chapter/series atoms; HEIC | Existing real-media acceptance tests run on the Mac | P1B, P5 | Yes |
| Packaging/extraction | `release.py` MacOS archive into scratch → audit (members, 0755 launcher, LF, no env/models) → extract with Archive Utility *and* `ditto`, quarantined copy → first run | P6a rehearsal from the finalized release source; P7c exact archives from the final SHA | P6a, P7c | Yes |
| Owner listening | §15 packs per engine | Owner | P2–P5 | Owner-signed |
| Independent Codex review | Changed-area review of the frozen release candidate, version identity and packaging included | Codex CLI, read-only | P6b | Review evidence, not a test PASS |
| Canonical full gate | `verify.py --mode full --platform macos` once, on the clean-LF checkout of the **final executable SHA** | Native macOS | P7a | The one macOS gate PASS |
| Windows regression | Focused Windows checks on HOME-PC for every shared file touched; the canonical Windows full gate on the **same** final SHA (D8) | HOME-PC | P5 (focused), P7b (full) | Windows evidence only |

### 14.2 Reporting rules (no false passes)

Every result is one of:
- `PASS`;
- `FAIL`;
- `BLOCKED`: could not run because a prerequisite is missing;
- `NOT APPLICABLE ON MACOS`: a Windows mechanism with no macOS behaviour to prove, listed with its count and reason id;
- `UNSUPPORTED`: an engine gated off by its recorded per-engine owner decision (D7-x);
- `NOT RUN`.

A macOS gate verdict states its non-applicable count explicitly. Two qualifiers are always printed beside a result and are never dropped in summaries:
- **evidence class:** `SIMULATED` or `REAL CLEAN` (§8.2);
- **source:** `AUTOMATED` or `OWNER-MANUAL (signed, <evidence id>, <sha>)`.

An engine verdict is reported as four separate entries, **F**, **S**, **Q** and **P** (§15). A combined "PASS" without them is not a valid engine verdict.

**`coverage.json` work (P1B).** Each behaviour id currently satisfied only by Windows-only tests gets one of two things:
- a macOS counterpart test; or
- an owner-reviewed `not_applicable_on: darwin` entry with a reason.

The coverage-inventory check then fails on any behaviour with neither.

**Windows coverage is never weakened:** the `win32` policy and all Windows tests are unchanged, and new tests are additive.

### 14.3 Gate changes required before any macOS gate result is trusted (P1B, MAC-027)

- `verification.json`: add `skip_policy.darwin`, derived from the *actual* collected darwin skip reasons. Each gets an id, an exact pattern, a maximum count and a "why". A darwin run with an unknown skip reason **fails**; it is no longer "NOT APPLICABLE, not judged".
- `verify.py` preflight on darwin: replace the Windows error-mode/Job checks with POSIX equivalents. Prove that a child is in the gate's own process group and is reaped on stop, and that no dialog can block (no Tk window outside tests). Windows logic is unchanged.
- **`acceptance` (MAC-045).** Only the Windows *input adapter* is inapplicable: native mouse and keyboard injection through `adapters/windows/`, with no macOS adapter in this programme (D9). The journeys' *behaviour* is not inapplicable, and the acceptance category is **not** exempted.
  - **The map.** `verification.json` gains `acceptance.darwin_map`. It gives each of the 55 `required_scenarios` and the optional `tts.kokoro-local` exactly one of:
    - **(a) a native automated counterpart:** test ids run by an in-process macOS journey driver (`adapters/macos/`). The driver drives the real panels through Tk (`invoke`, `event_generate`, the widgets' own variables) with real media and real FFmpeg. It needs no Accessibility or Screen Recording grant;
    - **(b) an owner-manual check:** a documented procedure (steps, machine, expected result) in the macOS acceptance checklist, whose signed evidence record names the candidate SHA. Used for what Tk cannot reach in-process: native NSOpenPanel dialogs, Finder reveal, Dock and menu-bar, Gatekeeper, Force Quit;
    - **(c) `NOT APPLICABLE ON MACOS`:** allowed only for a scenario that tests the Windows input harness itself, with a reason id reviewed by the owner.
  - **Expected classes, confirmed per scenario in P1B.** These follow the 55 required scenarios as they stand today (12 `control`, 13 `shutdown`, 3 `setup`, 27 tool/launcher/inventory journeys):
    - **`shutdown.*` (13):** (a). Close-during-work and forced landing are exactly the macOS containment and Cancel behaviour (§11.2), backed by KX-1 to KX-3.
    - **`setup.*` (3):** (a) plus the mandatory `fresh-macos` qualification.
    - **Tool, launcher and inventory journeys (27):** (a) with (b) for their native-dialog steps.
    - **`control.*` (12):** split per scenario.
      - Harness self-tests of Windows input mechanics are (c): real click, lost foreground, covered target, partly hidden window, other desktop, dead input path.
      - Behaviour controls get (a): second run refused by the lease, crash seen with the root released, orphan seen without the stop, forced landing sees the crash, disabled target refused, unmapped live control caught.
  - **How a darwin full gate reports it.** An `acceptance` stage with three counts: automated counterparts PASS/FAIL, owner-manual items *verified present* (an evidence record exists for this SHA and is signed), and not-applicable items with reason ids. The stage **FAILS** on any unmapped scenario, any failed automated counterpart, or any manual item without signed evidence for this SHA. It is never recorded as a blanket `NOT APPLICABLE`.
  - **Windows is untouched:** `required_scenarios`, the Windows adapters and the `win32` path do not change.
- **`qualification`.** `fresh_windows`, `m4b-scaling` (Windows build hashes) and `edge-low-memory` are Windows scenarios.
  - **`fresh-macos` is mandatory.** Path: packaged archive → extracted (quarantined) → stage 0 → first run → all six tools → `.venv` damage → repair → relaunch → interrupted install → recovery. It is added to the darwin qualification set in P1B.
  - **Automation is optional (D9b).** Without a runner, the scenario is satisfied by an owner-manual run of the written procedure with signed evidence. Either way the verdict carries its evidence class: P6a rehearsal, SIMULATED or REAL CLEAN; P7c, **REAL CLEAN** required.
  - **Truthful reporting.** A missing run reports `NOT RUN` and blocks publication. It is never skipped silently.

---

## 15. Listening, WER, speed and memory benchmarks

**Purpose:** compare engines and devices on the owner's priorities, in order:
1. calm, stable narration;
2. low WER;
3. consistent pronunciation;
4. minimal emotional fluctuation;
5. speed;
6. long-book reliability;
7. sensible memory.

Speech tuning is **never** changed to improve speed.

- **Texts (fixed, versioned):**
  - **A, difficult short:** `tts/quality_corpus.DIFFICULT_SHORT` (the difficult fantasy passage).
  - **B, normalization challenge:** the v0.8.0 Phase 4 B-track design, built from `test_speech_g1.SNIPPETS` and the golden corpus. It includes the ambiguous and protected controls.
  - **C, sustained:** `quality_corpus.SUSTAINED_NARRATION` / `LONGER_STRESS` (several minutes).
  - **D, long-book qualification:** one owner-chosen real book from `files/test-files/` (local only, never committed or uploaded). It runs end to end at least for Kokoro, plus a ≥30-minute excerpt for each other proven engine.
- **Controls:** the production path only (GUI run controller or `generate_voice_samples.py` *with the enabled `speech_prep` snapshot*). Fixed seeds, defaults, `v1`; one engine at a time; nothing else heavy running; mains power; window visible (plus one hidden-window App Nap run).
- **Metrics per engine × device × voice:**

  | Metric | Tool / definition |
  |---|---|
  | RTF | Wall synthesis time ÷ audio duration, plus characters/s and words/s, measured per chunk and per file |
  | Model load time | Cold load and warm load |
  | WER | Hypothesis from an ASR pass over the output, compared with the **prepared** text. Reuse the already-pinned `openai/whisper-small.en` @ `e8727524` in a dev-only scratch environment, CPU fp32; owner consent for the 0.97 GB (D15). Normalised by one fixed text normaliser and scored with a stdlib Levenshtein (no new dependency). Report WER, substitution/insertion/deletion counts and the exact error list |
  | Pronunciation errors | Owner-tagged list per track (names, numbers, homographs) |
  | Audible consistency | Owner 1–5 rating per track; cross-chunk stability (voice identity drift across chunk boundaries, loudness via short-term LUFS from pyloudnorm, already pinned) |
  | Emotional fluctuation | Owner 1–5 rating, plus the F0 and energy variance per sentence as a supporting number (librosa `pyin` on CPU, dev-only) |
  | CPU% and GPU% | Sampled `ps`/`top -l` and `ioreg` "Device Utilization %" at 1 Hz |
  | Peak unified memory | `/usr/bin/time -l` (max RSS, peak footprint) per worker; `torch.mps.current_allocated_memory()`/`driver_allocated_memory()` per chunk on MPS; `memory_pressure` |
  | Long-run behaviour | Per-chunk RTF drift; memory slope over ≥50 chunks (fail at >10% growth after warm-up); swap usage (`sysctl vm.swapusage`); thermals as reported by `pmset -g therm` (no sudo) |

- **Comparisons:**
  - Each engine's Mac configuration against its CPU fp32 reference on the same Mac (correctness oracle).
  - Mac against the owner-approved Windows tracks for OmniVoice (the 12 approved v0.8.0 tracks, by listening only).
  - Engines against each other on texts A–C for the owner's priorities.
- **Harness:** a small dev-only script under `files/dev-tools/` (tracked: code only). Outputs, logs and audio go to ignored `files/dev-work/macos-bench/<date>/`. There is no prolonged benchmarking during implementation phases: P2–P4 run A plus a short multi-chunk text per voice; P5 runs C and D once.
- **Four separate qualification dimensions per engine × configuration.** Each has its own verdict, recorded at the engine's own checkpoint (P2, P3A, P3B, P4A/P4B). None is inferred from another.

  | Dim. | Question | Evidence | Threshold | Who judges |
  |---|---|---|---|---|
  | **F: functionality** | Does it work as a product? | Install from the lock, offline load, every voice through the production path, Cancel contract C1–C5 (§11.2.1), containment (§11.2.3), Pause, publication, recovery, the offline audit | Fixed: all PASS | Automated |
  | **S: speech correctness** | Are the words spoken the words prepared, with nothing broken? | Per output: all samples finite; duration within the voice's measured characters-per-second band; no runaway re-render and no internal silence > 2 s; an ASR screen showing every sentence present (WER ≤ 15% absolute as a *screen*, not as quality); Kokoro phoneme identity with Windows (E-B2) | Fixed: zero non-finite outputs, zero truncated or garbled sentences; flagged items confirmed by the owner | Automated + owner confirmation |
  | **Q: listening/WER quality** | Is it as good as the reference? | Owner listening on the §15 priorities (calm, stable, consistent pronunciation, low emotional fluctuation); WER against the reference configuration; cross-chunk consistency; blind A/B where specified | Fixed: WER no worse than CPU fp32 + 1 pt absolute on texts A+B for any faster configuration; owner approval | Owner-signed |
  | **P: speed/memory qualification** | Is it fast and lean enough to offer? | RTF, load time, peak footprint, memory slope, swap, thermals | **Provisional budget D6-x**, set by the owner at that engine's checkpoint; growth < 10% after warm-up is fixed | Measured against the owner's budget |

  An engine is **PROVEN on this Mac** only when F, S and Q all pass for its whole voice roster. P is reported as "within budget" or "outside budget".
  - **Outside budget** does not unprove a correct engine. It requires an owner decision: offer the engine with an honest speed note, or gate it.
  - **F, S or Q failing** is a failed feasibility gate and triggers the per-engine stop and decision **D7-x** (§20.3).
- **Provisional budgets at each engine checkpoint (D6).** Budgets are not deferred to P5. The owner sets each engine's provisional speed/memory budget at its own checkpoint, from the first measured figures and the proposed starting values in §12:

  | Budget | Engine | Set at |
  |---|---|---|
  | D6-E | Edge | P2 entry |
  | D6-K | Kokoro | P2 entry |
  | D6-C | Chatterbox | P3A entry |
  | D6-Q | Qwen3 | P3B entry, after the E-D2 load figures |
  | D6-O | OmniVoice | P4A entry |

  The phase's P verdict is judged against that budget. P5 then confirms or adjusts each budget as **D6-final**, using the long-form runs (texts C and D). Any adjustment is recorded with its reason; a budget is never moved silently to turn a FAIL into a PASS. Speech tuning is never changed to meet a budget.

---

## 16. Independent Codex review and remediation gate (P6b–P6d)

- **When:** after P5 is accepted (all implementation, focused acceptance and listening done) **and** after P6a has finalized the release source. Finalizing means:
  - version identity per D16;
  - `RELEASE_OS_NAMES` including MacOS;
  - the MacOS platform declarations;
  - packaging support;
  - README, Changelog and release-note text.

  The review runs on a frozen release-candidate SHA pushed to the feature branch. Codex is an **independent verifier**: it implements nothing and does not run the full gate. Because the version identity and the packaging rules are already in the reviewed tree, nothing release-relevant can change after the review without the re-verification rule of §17.
- **Scope (changed-area):** `git diff 9554bc8..<candidate>`, with priority on:
  - the stage-0 download, hash and unpack path (supply-chain trust, safe extraction, interruption recovery);
  - the POSIX port of the Qwen3 installer authority (path pinning, symlink and race resistance);
  - process containment, lifeline, guardian and the class-D allow-list; the Cancel contract and the local-engine worker;
  - version identity, platform declarations and `release.py` MacOS packaging (members, modes, LF);
  - publication no-clobber and recovery;
  - platform gates (no fake-enable; Windows paths unchanged);
  - lock files (one artefact per pin, hashes, no CUDA wheel);
  - immutable-asset contracts;
  - the darwin skip policy (no Windows skip counted as PASS);
  - docs truthfulness.
- **Inputs:** this plan, the Handoff, the diff and the focused evidence. Codex runs read-only checks and may run focused tests in a scratch worktree.
- **Output:** findings `MACR-nnn` (severity, file:line, reproduction).
- **Remediation (P6c):** Claude fixes each finding with a positive and a negative control and its focused tests. Then a **focused Codex closure check** of the fixes only, not a second full review. Findings the owner rejects are recorded in Decisions with reasons.
- **Exit (P6d):** every finding fixed and closure-confirmed, or owner-waived in writing. Then owner acceptance of the remediated candidate, which **freezes the final executable SHA** (recorded in Handoff before any gate runs). Both canonical gates and the archives use exactly this SHA.

## 17. Native full-gate execution and failure policy (P7a, P7b)

- **Preconditions:**
  - Codex remediation closed;
  - owner acceptance recorded, and the final executable SHA frozen (P6d);
  - the release source already final: version identity, MacOS declarations and packaging support are in that SHA;
  - a clean LF worktree at that SHA (§3);
  - the app `.venv` built from the macOS lock;
  - the engines that are claimed are installed and offline-ready;
  - no other heavy process running;
  - mains power;
  - the final executable SHA recorded in Handoff **before** the run.
- **Command (P7a, exactly once):** `.venv/bin/python -u files/dev-work/verification-gate/verify.py --mode full --platform macos --label macos-final-<sha8>`, run from the clean worktree. Outputs go to the gate's ignored `outputs/`. Durable evidence: run id, counts, skips by darwin-policy id, `NOT APPLICABLE` totals, BLOCKED items, the tree fingerprint and the environment identity.
- **During phases P1–P6** (no full gate before P7a):
  - Permitted: only `--mode focused --test <ids>` for the touched modules.
  - Forbidden: `--mode changed`. Its `full_on` rule escalates any `scripts/shared/` change to a full run.
  - Forbidden: `--mode full`, unfiltered `pytest` and repository-wide runs.
- **Failure policy:**
  - A FAIL or incomplete run is **BLOCKED**, not PASS. Stop: diagnose with narrow tests; fix only what is necessary, with focused checks.
  - **Ask the owner before any rerun.** Any program or test change after the run invalidates it, and a new full run is needed for the changed tree.
  - Never re-run unchanged failures, never split the gate into giant partial suites to dodge it, and never describe a stale or failed run as PASS.
- **Windows (P7b, D8, required).** The **same** final executable SHA gets the canonical Windows full gate on HOME-PC (`.venv\Scripts\python.exe files/dev-work/verification-gate/verify.py --mode full --platform windows`), run from a clean checkout of that SHA by the owner or a Windows-session agent, under the same failure policy. The two gates may run in either order but never on different SHAs. A release built without a Windows gate on that SHA needs a recorded owner exception, and the release notes must then state the Windows evidence actually obtained.
- **Changes after the freeze (P6d onward) need justified re-verification.** Each change is classified in writing (Handoff and Decisions) before it is committed.

  | Change | Required re-verification |
  |---|---|
  | **Documents outside the release tree:** Handoff/Decisions evidence records, committed *after* the final SHA and not part of the tag | None. The tag and the archives stay on the gated SHA, and `git diff --name-only <final>..HEAD` must list only those documents |
  | **Anything inside the tagged tree:** program code, tests, gate code, configuration, launchers, version identity, or any document that `release.py` packages (README, licence texts) | A new candidate SHA; a focused Codex closure check of the delta; **both** canonical full gates again on the new SHA; the P7c archives rebuilt from it |
  | **Narrower re-verification** | Only by an explicit owner exception recorded in Decisions, naming the delta, why it cannot affect the gated behaviour, and the evidence run instead (the v0.8.0 precedent) |

  The P7c archives are built after both gates PASS, from that SHA, **with no source change**. A defect found while building or auditing them is a change under this table, never a quiet fix.

---

## 18. Git branching, versioning and release provenance

**Branch and commit practice:**
- Work happens on `feature/0.8.0-macos-compatibility` (from `9554bc8`).
- One or more scoped commits per phase, pushed to the feature branch at each phase checkpoint.
- No master merge, rebase, force-push or tag move without explicit owner approval.
- The owner's 17 tracked deletions and untracked files are never staged; stage only explicit paths.
- No AI trailer unless the owner's attribution rule says otherwise.

**Integration:** at P7d only, each step on its own approval:
1. a fast-forward of `master` **to the final executable SHA**, if ancestry permits; if `master` has diverged, stop for a new decision;
2. the annotated tag on that same SHA;
3. publication of the archives built from it in P7c.

The Handoff closeout that records the gate and archive evidence is a documents-only commit *after* the tagged SHA (§17 change rules).

**Provenance facts:** `v0.8.0` = `d1701e9` and ships only `AudiobookTool-Windows-v0.8.0.zip`. Every macOS change happens after that commit. A macOS archive built from the macOS branch therefore **cannot** honestly be called "v0.8.0", because its source is not `d1701e9`.

| Option | What | Advantages | Disadvantages / Git implications |
|---|---|---|---|
| **A. v0.8.1 patch release with Windows + macOS assets from one commit (recommended)** | Identity 0.8.1 (`config.toml`, `version.py`), set in P6a before review and the gates. One tag `v0.8.1` on the final executable SHA that both gates passed. Both ZIPs built from it | One version = one source = two platforms. Shared fixes (process lifeline, publication, Cmd+Q, fonts, lock tooling) reach Windows. Clean "latest". `release.py` already builds both | Windows must be re-verified on that commit (D8). Windows users see a new version whose changes are mostly macOS. The patch number is arguable: adding a platform is a feature (see D) |
| B. Add a macOS asset to the existing v0.8.0 release | — | — | **Rejected.** It misattributes source: the tag points at `d1701e9`, and the Mac build is not from it |
| C. macOS-only revision (e.g. tag `v0.8.0-macos.1`, release "v0.8.0 for macOS (source r1)") | macOS ZIP from the Mac commit; Windows stays v0.8.0 | No Windows re-release; the Windows evidence is untouched | Two lines of versions; "latest" ambiguity; `version.py` must not say plain `0.8.0` for different source (needs e.g. `0.8.0+macos.1`, which tests and release tooling must accept); shared fixes do not reach Windows |
| D. v0.9.0 (minor) with both assets | As A, minor bump | SemVer-honest for "new platform + new setup stage" | Same verification cost as A |

**Recommendation:** A (or D if the owner prefers minor-version semantics). The decision (D16) is separate and is recorded at **P5 exit, before P6a**, because the version identity is release-relevant source and must be in the reviewed and gated tree.

**Release order (all options):**
1. **P6a, release source final:**
   - version identity per D16;
   - `RELEASE_OS_NAMES` including MacOS;
   - the MacOS platform declarations: README platform and engine tables, Briefing and Changelog entries, the feature map, and the final `platform_supported()` state of each engine per its recorded decision;
   - packaging support and the in-tree release text;
   - a packaging rehearsal and the `fresh-macos` rehearsal on the rehearsal archive.
2. **P6b–P6d:** Codex review → remediation → closure → owner acceptance, which freezes the final executable SHA.
3. **P7a/P7b:** the canonical macOS and Windows full gates, both on that SHA.
4. **P7c:** the exact archives built from clean LF checkouts of that SHA by the unchanged packager, with no source change; audited; then the binding REAL CLEAN `fresh-macos` qualification on the exact macOS archive.
5. **P7d:** merge, tag and publish, each separately approved.

**In all options:**
- Annotated tags only, on the gated SHA.
- Release notes state exactly which platforms and engines were qualified, on what hardware, with each engine's F/S/Q/P verdicts and its D7 decision if any, and what is still open. The GitHub release text outside the tree is written at P7d. In-tree text (README, Changelog) is final in P6a.
- Each archive is audited:
  - members equal the packager's expected set from `git ls-tree` at the SHA;
  - modes are correct (0755 launcher);
  - text is LF;
  - no environment, model, secret or private path is included.

  Its SHA-256 is recorded.
- An anonymous re-download is verified (hash = the audited file).
- Nothing in this programme is published without that separate approval.

---

## 19. Numbered implementation phases and acceptance criteria

**Session rules (every phase):**
- A **fresh** Claude Code context per phase. Read this plan, `AI-WORKSPACE.md`, the Handoff, and the previous phase's checkpoint and actual Git state.
- Do not re-audit earlier phases unless a concrete mismatch appears.
- Complete only the named phase. Use focused tests only (§17).
- Commit and push scoped changes to the feature branch, under the §3.1 Git rules.
- Update Handoff (and Decisions for non-obvious choices).
- **STOP** with a report:
  - verdict PASS/BLOCKED;
  - SHA and files;
  - tests run, with counts;
  - real-hardware evidence, with its evidence class and source (§14.2);
  - for an engine phase, the F/S/Q/P verdicts per engine and configuration;
  - open items and owner decisions due;
  - the next phase.
- Never roll into the next phase. A failed engine feasibility gate is a STOP for that engine's D7 decision, not a phase PASS.

**Windows protection (every phase):**
- Each change is platform-guarded or proven platform-neutral.
- Every touched shared file is listed in the Handoff "Windows touchpoints" list, with the Windows tests that cover it.
- Run on the Mac the platform-neutral tests that exercise Windows branches through injectable `platform=` parameters.
- HOME-PC focused verification of the accumulated touchpoints happens in P5.

### P0 — Native research, architecture and roadmap — DONE (`389f56e`); Revision 1 (documents only) after the owner's engineering review
- **Entry:** owner prompt; for Revision 1, the owner's nine engineering corrections.
- **Delivered:**
  - this plan;
  - the feature branch;
  - the Handoff checkpoint;
  - the ignored private inventory and wheel matrix;
  - Revision 1, amended in place.
- **Not done:** any code change, environment, install, download (the FFmpeg evidence comes from published pages only), model or gate.

### P1A — Native bootstrap, environment foundation and installer containment
- **Entry:**
  - The owner approves this plan **as revised** (Revision 1).
  - Decisions D1–D5 are recorded, with D3 as revised in §11.1:
    - evaluate Riedl 9.0.1 first;
    - consent to download its `ffmpeg.zip`, `ffprobe.zip` and their `.sha256` files;
    - 9.0.2 only if 9.0.1 fails a proof and the owner accepts it.
  - The owner supplies **one real xHE-AAC file** locally for D3 proof 8. It is never committed. If none is available, P1A may still run, but it can only exit BLOCKED on exit item 3 until the file is supplied.
  - D4:
    - the disk-only `chmod +x` of the `.command` is approved;
    - the §3.1 Git rules are acknowledged;
    - the clean-LF worktree decision is made.
  - D5: network access to python-build-standalone, PyPI and ffmpeg.martin-riedl.de is approved for lock generation and first-run tests.
  - The universal start checklist (§21) passes: expected SHA, branch and the owner's untouched working-tree state.
- **Scope:**
  - **Launcher and stage 0:**
    - `Setup_and_Run-audiobook-creation-tool.command`;
    - new `scripts/shared/bootstrap_host_macos.sh` (§8.2: watchdog, safe extraction, interruption recovery, `trap`), committed as `100755` and LF (§3.1).
  - **`scripts/shared/bootstrap.py` macOS branches:**
    - `APP_PYTHON` per platform;
    - `install_python` and `find_suitable_python`;
    - Homebrew removed from the default path;
    - macOS FFmpeg acquisition;
    - `request_setup_stop` on POSIX through the containment layer.
  - **Containment, setup side:** new `scripts/shared/child_ownership.py` (registry, start-time reader, lifeline, safe termination) and `scripts/shared/child_guardian.py`, both POSIX-only (§11.2.2). They are applied to the setup process's children: pip through the ACT pip entry, downloads, unpacking.
  - **Packages and locks:**
    - `scripts/shared/base_packages.py` (platform-keyed lock);
    - new `scripts/requirements-lock-macos-arm64-py312.txt`;
    - `files/dev-tools/lock_base_requirements.py` (platform parameter).
  - **FFmpeg:** `scripts/shared/ffmpeg_portable.py` and `ffmpeg_health.py`. The Riedl 9.0.1 pin is recorded only after the eight proofs of §11.1, with `aac_at` and `libmp3lame` required.
  - **Other platform fixes:**
    - `scripts/shared/cleanup_state.py` (no Apple-python candidate, MAC-028);
    - the case probe in `venv_layout`/`venv_integrity`/`maintenance` (MAC-015);
    - platform-tagged receipts and stores (MAC-029).
  - Tests.
- **Tests:**
  - **Stage 0:** the fixture states of §14.1, including unsafe archive members, stale staging, both watchdog cases and KX-5.
  - **Locks:** parse, applies and completeness. Windows `lock_applies` is unchanged (injected `platform="win32"`).
  - **Containment, setup side:** KX-4 (automated part); KX-7 and KX-8 for the setup owner; KX-9 over `bootstrap.py`; Windows paths unchanged.
  - **FFmpeg:** D3 proofs 1–8 (§11.1).
  - **Clean install, SIMULATED (PATH-restricted)** (§8.2), in a disposable clean LF worktree: stage 0 → base env → FFmpeg → the GUI launches → all six tools open. Every shim log must be empty.
  - **Clean install, SIMULATED (linkage-verified)** (§8.2):
    - every Mach-O is arm64;
    - `otool -L` and the loaded images show nothing from Homebrew or `/usr/local`;
    - `codesign --verify` passes. The owner's narrow exception (2026-11-15) covers exactly seven upstream files, each at its recorded bytes: six universal2 modules whose arm64 slice verifies, and PyTorch's unsigned `libomp.dylib`, which must load and run. `files/dev-tools/macos_native_audit.py` judges them; anything else fails, and REAL CLEAN at P7c stays mandatory;
    - `pip check` is clean and every install used `--require-hashes`;
    - nothing was written outside the repository and `$TMPDIR`.
  - **Interruption recovery:** kill during the download, the extraction, the venv build and pip. The next launch repairs, and no orphan remains.
  - **Repair:** `.venv` damage → repair; engine carry-across on APFS (§8.4).
  - **Foreign state:** Windows-origin `runtime-data` is ignored.
  - **torch:** the 2.6.0 import proof in the app environment (the E-B1 imports, without synthesis).
  - **Git:** new executables are `100755` and LF in the index (§3.1).
- **Owner manual:**
  - a Finder double-click of the `.command` in the disposable copy (no Gatekeeper yet: that is P6a/P7c);
  - KX-4: close the Terminal window during first-run pip, then confirm no installer remains.
- **Not claimed by P1A:**
  - REAL CLEAN evidence (P7c, D18);
  - the Gatekeeper first run of a quarantined archive (P6a rehearsal, P7c);
  - GUI and FFmpeg containment (P1B);
  - any engine synthesis (P2 onward).
- **Exit (PASS): all of the following.**
  1. The SIMULATED first run reaches a running app with no Homebrew call, link or load and no admin prompt, and is reported as **SIMULATED**.
  2. Hashes are enforced for every install, and the macOS lock is complete.
  3. FFmpeg is settled one of two ways:
     - Riedl 9.0.1 is adopted after all eight proofs, with its real size, SHA-256s and signing identity recorded (D3 revised, 2026-11-15: the pin may be enabled for further local qualification once the automated part of proof 8 and the Converter journey pass; the owner's listening check stays a P1A exit item and is never inferred); or
     - D3 goes back to the owner with the failing proof, and the phase exits **BLOCKED**. An unproven build is never pinned.
  4. Installer-containment and interruption-recovery tests PASS, with no orphan.
  5. Focused tests PASS, with counts recorded, and the Windows touchpoints are listed.
  6. New executables are `100755` and LF in the index. The staged diff holds only intended files, with no mode or CRLF churn (§3.1).
  7. Committed and pushed.
- **Stop conditions:**
  - the PBS Tk proof fails on macOS 27 (escalate D1);
  - any pin lacks a macOS artefact at resolution time (owner decision);
  - torch 2.6.0 fails to import on macOS 27 (owner decision; it affects the shared pins);
  - both Riedl candidates fail a D3 proof (owner decision). A Homebrew-only or unproven FFmpeg is never the pin for a clean Mac;
  - obtaining any evidence would require a system change (Homebrew, shell profiles, PATH, Gatekeeper).

### P1B — macOS GUI shell, platform safety layer, GUI containment and the five non-TTS tools
- **Entry:** P1A PASS.
- **Scope:**
  - **`launcher.py`:**
    - Cmd+Q and `ShowPreferences`;
    - `RLIMIT_NOFILE`;
    - SIGTERM/SIGHUP/SIGINT routed to the close path;
    - the GUI as a containment owner with its own guardian (§11.2.2).
  - **`shared/subprocess_utils.py`:** FFmpeg and ffprobe spawned as class B into the guardian group; the POSIX `stop_media_children`, checked by identity over the registry.
  - **Optional setup:** the worker and supervisor run as class A with the lifeline.
  - **Platform fixes:**
    - `tts/worker_limits.py` (darwin memory reader, neutral wording);
    - `tts/publication.py` (`renamex_np` no-clobber);
    - optionally `shared/work_area.py` (D11b; it reuses the P1A start-time reader);
    - fonts and shortcuts (MAC-020, 037).
  - **GUI:**
    - the Tk 9 port (trackpad `<TouchpadScroll>`, wheel deltas; MAC-040) and the PBS launch cosmetics (MAC-042), all guarded by the running Tk version;
    - the main-thread audit (MAC-032);
    - fixes for aqua regressions the native tests reveal.
  - **Gate:**
    - the `verification.json` darwin skip policy;
    - the `verify.py` darwin preflight;
    - `coverage.json` macOS counterparts or not-applicable entries (MAC-027);
    - **`acceptance.darwin_map`** with every scenario mapped, and the in-process journey driver `adapters/macos/` (§14.3, MAC-045);
    - the `fresh-macos` qualification procedure, and its optional runner (D9b).
- **Tools accepted:** MP3 Tool, M4B Converter (incl. xHE-AAC via `aac_at` on the owner's file; continuous route refused and fallback correct), M4B Maker, M4B Metadata Editor, Cover/Image Tool (incl. HEIC).
- **Tests:**
  - focused module suites on the Mac, including the 39+ aqua tests;
  - real-media acceptance with the existing env-var fixtures;
  - Cancel and containment: CX-5, CX-8, KX-1(d, e), KX-2(d), KX-3(d), KX-6, KX-7, KX-8, KX-9;
  - disk-full image;
  - exFAT image;
  - NFD names;
  - two app copies;
  - Edge-like 8-way open-file stress under 256;
  - the darwin acceptance map has no unmapped scenario. The automated counterparts for the five tools, the `shutdown.*` journeys and the behaviour `control.*` journeys PASS.
- **Owner manual (revised by the owner, 2026-11-15; Decisions, P1B closeout):** limited to subjective visual design and usability
  review (reported: the six panels accepted in Dark Mode) and unavoidable OS permissions. Functional behaviour is the gate's:
  - the former GUI checklist and class-(b) items are decided by automated evidence (`verification.json` → `darwin_p1b`): the
    journeys with real window-server pictures and the dialog contract, the darwin scenarios `macos-native-dialogs` (the real
    NSOpenPanel/NSAlert) and `macos-visual` (every panel, Light and Dark, sizes and states, machine-reviewed);
  - KX-10 is the darwin scenario `macos-kx10` (SIGKILL of the exact process during a real Maker encode; the Force Quit window
    itself is not exercised);
  - what cannot be automated without a privacy grant is listed as BLOCKED with the grant it needs (choosing files inside the
    native panel's out-of-process browser: Accessibility); later-phase items stay NOT RUN. `fresh-macos` REAL CLEAN is
    unchanged (P7c).
  - **ACT72-080 approved P1B exception (owner, 2026-11-15; Decisions, P1B final visual remediation):** P1B may close without
    granting Accessibility or Screen Recording solely to automate a selection inside the native file picker. The selection
    stays UNVERIFIED (never PASS; `verify.py --evidence` shows APPROVED P1B EXCEPTION); opening, configuring and cancelling
    the real panels and the in-process returned paths keep their own evidence within their scope. It relaxes no other
    requirement and is revisited at P5/P7 release qualification.
  - **ACT72-081 amendment to the frozen shell (owner, 2026-11-15; Decisions, P1B ACT72-081):** on macOS only, the footer
    follows the application's current appearance so its native Aqua buttons sit on one coherent footer in Light and Dark;
    native buttons, their positions, labels, actions and keyboard access, the Dark appearance and the Windows and Linux
    shells are unchanged, and nothing else in the shell is redesigned. `macos-visual` pictures the switch without a
    restart, and its review fails a native button drawn in a box of another colour.
- **Exit:**
  - the five tools PASS on focused tests, real media, their acceptance counterparts with real pictures, and the darwin scenarios
    above; the owner's visual review recorded as owner-reported;
  - the CX and KX tests listed above PASS, with no orphan;
  - the darwin gate policy and the acceptance map are in place;
  - Windows touchpoints are listed.
- **Stop:** a GUI crash from the Tk/AppKit thread rule that cannot be fixed narrowly; any invariant break; any orphaned ACT process after a KX test.
- **Accepted by the owner at `61078f9` (2026-11-16; Decisions, P1B accepted).** The 20 visual FAIL findings of the final eye
  review are nonblocking P1B visual debt (not passes), reviewed for usability and disposition in P5; the 1120 × 800 minimum
  is kept; D11c and D11b (ACT72-076) are deferred; MAC-042 is deferred to P6a; ACT72-080 stays the approved P1B exception
  (selection UNVERIFIED, revisit P5/P7). No P2, P5, P6 or P7 requirement is waived.

### P2 — Edge TTS and Kokoro (TTS Audiobook panel on macOS)
- **Entry:** P1B PASS. The owner sets the provisional budgets **D6-E** and **D6-K** (§12.A, §12.B, §15).
- **Scope:**
  - TTS panel macOS behaviour and Edge multi-file workers;
  - Kokoro: device policy and the eSpeak data path on macOS;
  - **the local-engine worker** (§11.2.1, MAC-043): the host, the worker entry with its lifeline, and the Kokoro adapter;
  - the listed §12 changes.
- **Tests:**
  - **Edge, five voices:** real network; a short multi-file run with 8 workers; CX-4 and CX-6.
  - **Kokoro, nine voices:** CPU in the worker; texts A + a short multi-chunk text.
  - **Kokoro Cancel:** CX-1 (a 3,000-character chunk in flight), CX-2, CX-6, CX-7 and CX-8. KX-1(a), KX-2(a) and KX-3(a).
  - **Parity:** the worker path against the in-process path (§11.2.1).
  - **Speech prep:** `v1` and `off` parity tests.
  - **Opt-in real-runtime tests,** each with its exact skip rule.
  - **Acceptance:** the darwin counterparts of the Edge and Kokoro TTS journeys, including `tts.kokoro-local`.
  - **References:** the 18 reference hashes before and after.
- **Owner manual:** listening pack per §15 (A track for all 14 voices; B track for one Kokoro and one Edge voice); Kokoro is the priority engine.
- **Exit:**
  - Edge and Kokoro **PROVEN on this Mac**: F, S and Q PASS for all 14 voices, with the owner's listening approval;
  - P verdicts recorded against D6-E and D6-K. An outside-budget result carries its recorded owner decision.
- **Stop:**
  - a Kokoro pronunciation regression against Windows (owner-judged);
  - an espeak-ng load failure;
  - a Cancel bound exceeded;
  - an F, S or Q failure. This **STOPS** the phase for a separate per-engine owner decision (D7-E, D7-K).

  An Edge endpoint failure from an upstream outage is BLOCKED, not FAIL, and is recorded.
- **Implemented at `38af4fd` (2026-11-16; Decisions, P2 entry; Handoff): specific acceptance evidence pending the owner.**
  Automated: the affected suites give exactly the baseline's failure set, the ten darwin TTS journeys and the real-Kokoro
  Cancel/containment suite PASS. Pending the owner: listening (pack `ACT-v0.8.0-macos-p2`), WER (D15), Windows phoneme
  parity (HOME-PC E-B2), the disposition of Andrew's upstream-blocked text A and of two D6-K readings (one 6.0046 GiB
  peak; 10.98 % growth by the harness's definition, trend −2.7 %). Not owner-accepted.
- **Revision 2 (2026-11-16):** P2 stays **IMPLEMENTED and TESTED (automated), not OWNER ACCEPTED**. These items are still tracked:
  - owner listening of the 24-sample pack;
  - the Andrew disposition;
  - the two D6-K readings;
  - the 19 journey pictures;
  - D15 (WER);
  - keep or remove the spaCy model in `.venv`.

  **Windows E-B2 phoneme parity is PENDING, deferred under Q3=A until HOME-PC is available.** It is neither waived nor passed, and it is due before the P6d freeze.

### P3A — Chatterbox Turbo
> **Revision 2 (2026-11-16): SKIPPED BY OWNER DECISION on macOS** (Q1=A, Q2=A). This is not PASS and not a technical FAIL. None of the scope below is carried out on macOS, and no Chatterbox weights are acquired, even if OmniVoice succeeds, unless the owner gives new authorization. Windows Chatterbox is unchanged. The text is kept as the record of the original requirement.

- **Entry:** P2 PASS. The owner sets the provisional budget **D6-C**.
- **Scope:**
  - `chatterbox_synth.py` device policy (CPU default on darwin);
  - the dtype guard;
  - the conditionals cache key with the device;
  - the Chatterbox adapter for the local-engine worker;
  - macOS-neutral wording (§12).
- **Tests:**
  - experiments E-C0 to E-C5 (§12), the E-C5 Cancel and containment tests included;
  - six voices on CPU: A + a short multi-chunk text;
  - watermark detection;
  - a memory soak of one chapter;
  - MPS only as a documented opt-in experiment, never the default unless it passes the §15 correctness oracle.
- **Owner manual:** six-voice listening (A track); KX-10 (Force Quit during a Chatterbox chapter).
- **Exit:**
  - six Chatterbox voices **PROVEN**: F, S and Q PASS on CPU, or on an MPS configuration the owner accepts on evidence;
  - the P verdict recorded against D6-C. If it is outside budget, the owner records whether the voices stay available with an accurate speed note or are gated.
- **Stop:**
  - MPS made the default without the oracle;
  - memory blow-up on CPU;
  - an F, S or Q failure. This **STOPS** the phase for a separate owner decision **D7-C**.

### P3B — Qwen3-TTS (CustomVoice and Voice Clone)
> **Revision 2 (2026-11-16): SKIPPED BY OWNER DECISION on macOS** (Q1=A, Q2=A). This is not PASS and not a technical FAIL. No Qwen3 CustomVoice or cloning on macOS, no Qwen3 model or engine download, and no D12 port, unless the owner gives new authorization. Windows Qwen3 is unchanged. The text is kept as the record of the original requirement.

- **Entry:**
  - P3A closed: PASS, or a recorded D7-C decision.
  - Owner consents:
    - the ~9.1 GB model download (CustomVoice + Base);
    - the Qwen3 environment;
    - optionally Whisper for WER;
    - **D12** (POSIX authority design).
  - The owner sets the provisional budget **D6-Q** after the E-D2 load figures, before E-D3.
- **Scope:**
  - **(a) Installer authority port:** a POSIX implementation of `artifact_store.boundary` and the Qwen3 package/engine authority. It gives the same "no renamed or replaced parent between check and use" guarantee that the Windows handles give, using:
    - directory file descriptors (`os.open(..., O_DIRECTORY|O_NOFOLLOW)`);
    - `dir_fd=`-relative operations;
    - `fstat` identity checks before and after;
    - `O_NOFOLLOW` leaf opens;
    - a same-volume `rename` from a pinned staging dir.

    Security-relevant; a Codex review priority.
  - **(b)** The macOS hash lock and darwin target in the Qwen3 manifest (PyPI only, one torch 2.10.0 file, ACT `sox` supply wheel).
  - **(c)** Worker device/dtype adapter: CPU fp32 default; MPS bf16 only by evidence; never fp16.
  - **(d)** The worker lifeline (§11.2.2).
  - **(e)** `platform_supported()` → darwin arm64 only after E-D1 to E-D5 pass.
  - **(f)** Hardware text from measurements.
- **Tests:**
  - experiments E-D1 to E-D5 (§12);
  - eight voices (two CustomVoice, six clones);
  - the long-form memory trend;
  - CX-2, CX-3 and CX-8;
  - KX-1(b);
  - interrupted install (no orphaned pip; staging recovered);
  - corrupt model → repair;
  - reference hashes.
- **Owner manual:** listening for eight voices (A track; B track for one CustomVoice and one clone).
- **Exit:**
  - eight Qwen3 voices **PROVEN** (F, S, Q), with the P verdict recorded against D6-Q; **or**
  - the feasibility gate failed, the phase **STOPPED**, and the owner then recorded a separate, explicit **D7-Q** decision with the evidence.

  Approval of this roadmap is never that decision.
- **Stop:** E-D3 or E-D4 fails on CPU fp32. The Qwen3 macOS gate stays closed (no fake-enable), and the phase waits for D7-Q.

### P4A — OmniVoice feasibility experiment (owner-gated; no product code)
> **Status 2026-11-16 (Revision 3): `P4A OWNER ACCEPTED`** at evidence SHA `6fb98e6`: six voices accepted by listening; MPS fp32 preferred (speed exception accepted), CPU fp32 alternative, MPS fp16 experimental; WER NOT RUN (§12.E, Decisions). P4B is authorized.
>
> **Earlier status 2026-11-16: EXECUTED — `P4A TECHNICAL PASS — OWNER LISTENING PENDING`** (C2 a speed PERFORMANCE EXCEPTION; §12.E). P4B is not started and needs the owner's listening acceptance and authorization. A negative listening verdict activates the fallback (P4C).
>
> **Revision 2 (2026-11-16):** an early, narrowly bounded P4A is authorized **before** P3A/P3B (Q1=A). The procedure is §12.E Revision 2. **Prepared without acquisition** at `d6f21f9`; its findings, tool and evidence are listed in §12.E. Entry is now: the owner's consent to the manifest token `7932d4ef…62f4c` and D6-O set. It no longer waits for P3B. The exit is one of the three campaign outcomes. A negative result or an owner rejection activates the approved fallback (P4C) with no new D7-O question. The Revision 1 text below is superseded where it differs.

- **Entry:**
  - (Revision 1, superseded:) P3B closed: PASS, or a recorded D7-Q decision.
  - The owner consents to the ~3.27 GB model and ~0.25 GB of wheels, into a **disposable** environment under `files/dev-work/omnivoice-feasibility/`.
  - The owner sets the provisional budget **D6-O**.
- **Procedure:** the §12 OmniVoice experiment, steps 1–9:
  - a neutral `say`-generated reference first, then the six real references read-only (hashes verified before and after);
  - three configurations (MPS fp16, MPS fp32, CPU fp32);
  - every measurement listed;
  - `PYTORCH_ENABLE_MPS_FALLBACK` unset;
  - the disposable experiment's processes are bounded and reaped (no orphan).
- **Exit:** a written verdict per configuration, with F/S/Q against §15 correctness and P against D6-O. Then an owner decision:
  - integrate a named configuration; or
  - if no configuration passes, a separate, explicit **D7-O** decision recorded with the evidence.

  No ACT code changes in P4A. The disposable environment is removed or kept, as the owner decides.

### P4B — OmniVoice integration (only if P4A yields an owner-accepted configuration)
> **Revision 2:** P4B needs both a proven P4A configuration and the owner's acceptance of its audio, and then its own authorization. Any OmniVoice install control on macOS uses separately verified and approved macOS setup behaviour. Chatterbox and Qwen3 stay gated.
>
> **Revision 3 (2026-11-16): AUTHORIZED.** Configurations: MPS fp32 default, CPU fp32 by explicit choice, MPS fp16 refused as a production choice. Windows CUDA behaviour, pins and setup unchanged. Pinned OmniVoice 0.2.1, model `c5fdb5cc`, references and `GENERATION` unchanged. Production downloads and adoption of the P4A bytes each need separate owner consent. Only the narrow platform gating P4B needs; the broad roster work is P4C. P4B's minimum verification: install and repair; model hash, receipt and provenance; six voices through production; multi-chunk; the 48-chunk MPS worker/memory test; CPU fp32; device choice without silent fallback; Cancel and containment (CX-2, CX-3, CX-8, KX-1(c)); Force Quit containment; Windows-branch unit tests through platform seams; reference, transcript and preview hashes; GUI smoke where appropriate; installer failure and repair paths.
>
> **Status 2026-11-16: P4B TECHNICAL PASS (F, S), one PERFORMANCE EXCEPTION — OWNER DECISION PENDING; the checkpoint waits for the owner** (Decisions, P4B entry; evidence `files/dev-work/macos-p4b/q/`, ignored). The engine is installed in the HOME-MacOS checkout through ACT's installer, from the P4A bytes adopted by APFS clone (two separate owner approvals; 0 bytes downloaded). Real-engine results:
> - six voices on MPS fp32: wall RTF 0.923–1.069, peak ≤ 9,577 MiB;
> - text B, 14 chunks (Female 1, Male 1);
> - 60 chunks across 2 workers;
> - CPU fp32 by `[tts] omnivoice_device = "cpu"`: RTF 1.233–1.510, peak ≤ 3,331 MiB;
> - CX-3 Cancel: 2.144 s on MPS and 2.103 s on CPU; KX-1(c): 0.384 s;
> - CX-2 and CX-8: unit PASS;
> - installer tampered-wheel, Cancel, adoption, damage and repair paths: PASS in a disposable sandbox;
> - protected assets unchanged.
>
> **Exception:** within one worker the footprint grows 28.4 % after warm-up (MPS tensors flat), bounded by the 48-chunk worker restart; this is outside the provisional < 10 % target. The owner chooses (a) accept as bounded, or (b) a Mac-only mitigation experiment. Not done here: the GUI smoke (P4C surfaces; owner manual) and the HOME-PC Windows regression (P5).
>
> **P4B memory checkpoint (2026-11-16, Revision 3b; Decisions, memory-checkpoint entry; evidence `files/dev-work/macos-p4b/q/memory/`, ignored).** P4B is **not owner accepted**: one bounded Mac-only investigation was authorized, with worker lifetimes 48 / 24 / 16 only.
> - **Cause (measured):**
>   - The live MPS tensors stay flat (2,336 MiB).
>   - About 88 % of the growth is GPU buffers kept by PyTorch's MPS caching allocator ("IOAccelerator (graphics)", MPS driver memory).
>   - The rest is CPU-heap MPSGraph executables and caches compiled for each new chunk shape (`heap`: +466 executables in 10 long chunks).
>   - It grows only on new shapes: one text repeated stays flat (P4A). It is larger for long chunks (about 120 MiB a chunk against about 55).
> - **The 60-chunk sequence (Female 2):**
>
>   | Bound | Peak | Growth |
>   |---|---|---|
>   | 48 | 6,900 MiB | +28.4 % |
>   | 24 | 6,459 MiB | +19.5 % |
>   | 16 | 5,922 MiB | +10.5 % |
>
>   Each MP3 is byte-identical to the 48-chunk run's.
> - **The book-like stress text (Male 1, 48 paragraphs of 229–293 characters):**
>   - With 48: 13,590 MiB, and the system reached memory-pressure warning and swapped out about 412 MiB.
>   - With 16: 10,745 MiB, no pressure and no swap.
>   - The audio is bit-identical.
> - **Implemented:**
>   - `omnivoice_synth.MPS_CHUNKS_PER_WORKER = 16` through `chunks_per_worker_for(policy)`. The entry point's seam defaults to the device's bound.
>   - Windows' CUDA and a Mac's CPU keep `CHUNKS_PER_WORKER = 48`.
>   - Verified: CX-3 2.41 s; KX-1(c) 0.09 s; CPU fp32 20 chunks PASS; focused tests 0 new failures; protected assets unchanged.
> - **Still missed:**
>   - Peak on the stress text, 4.9 % over 10 GiB.
>   - Growth: +10.6 % on the sequence, +31.4 % on the stress text.
> - **The owner's options:**
>   - (a) accept the remaining exception with the 16-chunk bound;
>   - (b) one more bounded experiment aimed at the allocator's kept buffers (`torch.mps.empty_cache()` per chunk, every N chunks, or above a threshold);
>   - (c) revert to 48.
>
> **P4B option B, MPS cache clearing (2026-11-16, Revision 3c; Decisions, option-B entry; evidence `q/cache-exp/`, ignored).** This was a feasibility experiment only, in an ignored copy of the worker reached through the `script` seam. No production change.
> - **Setup:** the book-like text at the production 16-chunk bound.
> - **Peaks:** control 11,131 MiB; `empty_cache` every 4 chunks 13,944 MiB (one worker); above an 8,192 MiB footprint 10,931 MiB. Identical runs vary by about 400 MiB.
> - **Growth:** +31 %, +33 % and +28 % respectively.
> - **What clears:** each clear frees a fixed 2,096 / 1,072 MiB (one chunk's working space), which the next long chunk takes back.
> - **What stays:** the memory left after a clear still grows about 120–180 MiB a chunk; the MPSGraph CPU heap is unchanged.
> - **Unchanged:** audio bit-identical; clear cost about 20 ms; Cancel 2.13 s and KX-1(c) 0.083 s with clearing after every chunk.
> - **Recommendation:** keep the 16-chunk bound and adopt no clearing.
> - **Correction:** 3b's cause wording ("allocator-kept buffers") is wrong. The code comment above `MPS_CHUNKS_PER_WORKER` and the feature map's macOS bullet repeat it, and are to be corrected with the owner's decision.
>
> **P4B OWNER ACCEPTED (2026-11-16, Revision 3d; Decisions, P4B acceptance entry).** Accepted with its memory performance exception: 16 chunks per Mac-GPU worker, 48 on Windows CUDA and the Mac's CPU, no cache clearing, no further memory optimization authorized. The exception as measured (peaks 10.7–11.1 GB on book-like text; growth +20 to +31 % there and +10.6 % on the 60-chunk sequence) and the provisional D6-O targets it misses are kept as written. The cause wording in the code comment and the feature map now matches option B's evidence (likely per-shape MPSGraph resources; not proven). Owner manual items still open from P4B: a GUI OmniVoice conversion with a mid-run Cancel (P4C ran an automated in-process one; see §19 P4C) and the HOME-PC Windows regression (P5).
>
> **P4B implementation map (as built):**
> - `omnivoice_runtime`: `package_set`/`DARWIN_SET`, `platform_supported` (win32, or darwin arm64), `apple_gpu`/`detect_gpu`, `device_policy`/`configured_mac_device`, `prompt_identity(device=)`, `machine_lock_path` and the POSIX `MachineGuard`, `app_owned_python`, the dropped MPS switches, `hardware_disclosure`/`no_gpu_message`;
> - `omnivoice_worker`: `device_problems`, `placement_problem`, `_sync`/`_empty_cache`/`_memory`/`_device_facts` per device;
> - `omnivoice_synth`: `spawn_worker` (private owner off Windows), the device once per file, Mac failure texts;
> - `omnivoice_setup`: the proof job on the policy's device; the base Python through `app_owned_python`;
> - `optional_setup`, `optional_setup_health`: Mac texts and limits;
> - `shared/config`: `tts.omnivoice_device`;
> - `shared/bootstrap`: `optional_choices_for`;
> - the manifest: the `darwin_arm64` set.

- **Scope:**
  - the darwin wheel list in the manifest;
  - the worker adapter (every CUDA call site in §12);
  - the worker lifeline (§11.2.2);
  - `omnivoice_synth` device/dtype;
  - `prompt_identity` gains the device;
  - the setup proof job per platform;
  - optional-setup texts and the GPU probe (Apple GPU vs NVIDIA);
  - `platform_supported()` for darwin arm64.
- **Tests:**
  - six voices: A + multi-chunk;
  - the 48-chunk worker bound on MPS (memory trend);
  - CX-2, CX-3 and CX-8;
  - KX-1(c);
  - install, adopt, repair and receipt on macOS;
  - reference hashes;
  - the offline audit hook.
- **Owner manual:** six-voice listening (A + B), compared against the Windows-approved tracks.
- **Exit:**
  - six OmniVoice voices **PROVEN** (F, S, Q), with the P verdict recorded against D6-O; or
  - a failure **STOPS** the phase for a separate D7-O decision.

### P4C — macOS engine roster through one capability policy (Revision 2; Q2=A)
> **Revision 3 (2026-11-16):** the configuration is **Edge + Kokoro + OmniVoice, 20 voices** (§12.F). P4C starts after P4B's checkpoint is accepted, and must be complete before the Mac work is called complete or any release is authorized.
>
> **Integration points left for P4C after P4B (2026-11-16, read-only survey; nothing done):**
> - `tts/voice_registry.py`: the roster and group labels the panel lists.
> - `tts/epub2tts_gui.py`: the voice dropdown, the engine headings, and dispatch to `chatterbox_file_to_mp3`, `qwen3_file_to_mp3` and `omnivoice_file_to_mp3`. Dispatch must refuse Chatterbox and Qwen3 on darwin.
> - `shared/bootstrap.optional_choices_for("darwin")`: it still lists all five choices; P4C trims it to Kokoro + OmniVoice.
> - `tts/optional_setup.py`, `shared/optional_setup_protocol.py` and `tts/voice_install.py`: Install & Continue, repair and the optional-install entries.
> - The restore of a saved or imported voice selection that names an engine not offered.
> - The Windows-simulation OmniVoice suites that fail on a Mac at baseline (`winreg`, `python.exe` layout): they need darwin seams, or a platform pin, as P4B did for the synth and reference suites.

- **Entry:**
  - the P4A outcome is recorded:
    - **`FALLBACK CONDITION MET`** or an owner rejection: **Edge + Kokoro** configuration;
    - or an owner-accepted P4B: **Edge + Kokoro + OmniVoice** configuration.
  - P4C never starts before that. Mac engine controls are not removed before the fallback condition is established.
- **Scope (§12.F):**
  - one central, testable, platform-aware capability policy, decided from the real runtime platform at startup, with no user toggle;
  - every macOS user-facing surface and the runtime dispatch governed by it;
  - stale or imported settings that name an engine not offered are handled safely;
  - Windows keeps the complete roster;
  - narrow guards, no duplicated application, nothing deleted.
- **Tests:**
  - policy unit tests for darwin and win32 through injected platforms;
  - the darwin roster and the win32 roster (all 34 identities) pinned;
  - each surface on darwin;
  - dispatch refusal for every non-offered engine on darwin;
  - a stale-settings restore;
  - the setup wizard offering only Kokoro's optional checkbox (under the fallback);
  - the existing Windows suites for the touched shared files, run on the Mac through the platform seams;
  - the TTS darwin journeys re-run;
  - the reference, transcript and preview hashes.
- **Exit:** the macOS roster is exactly the configuration's (14 voices under the fallback). Windows behaviour is unchanged (touchpoints listed for the HOME-PC regression). The feature map and coverage are updated.
- **Stop:** a Windows-visible change; a removed asset, identity or pin; an engine hidden only visually while dispatch would still run it.

> **Status 2026-11-16 (Revision 3e): P4C IMPLEMENTED and TESTED (automated); owner acceptance pending.** Start `d2b2eae`; one scoped commit (Decisions, P4C entry; evidence `files/dev-work/macos-p4c/`, ignored).
> - **The policy:** `shared/engine_policy.py` (standard library only; `sys.platform` read when asked; `platform=` on every function; one seam, `current_platform`). macOS offers `edge`, `kokoro`, `omnivoice`; every other platform all five. One refusal, `EngineNotOffered`, with one message ("<Engine> voices are not available in this app on macOS, so nothing was started, installed or downloaded. Choose a Microsoft Edge TTS, Kokoro or OmniVoice voice instead.").
> - **Rosters:** macOS 20 (Edge 5, Kokoro 9, OmniVoice 6; registry order; Steffan default; headings Edge, Kokoro American, Kokoro British, OmniVoice); Windows 34, unchanged. All 34 identities, 18 recordings, both transcript files and 28 previews stay.
> - **Guards:** the voice list (`voice_registry.offered_labels`); a stale selection (becomes Steffan, logged); Start; Retry Failed; the conversion worker before any engine import; `chatterbox_file_to_mp3`, `synthesize_text_to_wav`/`_mp3`, `_get_model`; `qwen3_file_to_mp3`; `voice_install.component_for` (Install & Continue); the wizard (Mac: Kokoro checked, OmniVoice unchecked, no Qwen3 note); `optional_setup.plan`/`estimate` (UNSUPPORTED; consent refused); `RealAcquirer.acquire`; `optional_setup_health.local_health`; the Qwen3 install button; `generate_voice_samples` (patterns and evaluation modes); the launcher's TTS line; Clear Downloaded Data and Repair App Environment wording (Mac names OmniVoice).
> - **Not changed:** the dormant `chatterbox-tts` base package and its base import probe (no slimming); Qwen3's own Windows-only refusals.
> - **Automated evidence (HOME-MacOS):**
>   - Baseline at `d2b2eae`, the 195 affected modules (dependency-selected): 813 failed, 10,666 passed, 328 skipped, 159 errors. Final with P4C, the same modules plus the new suite: 812 failed, 10,707 passed, 328 skipped, 158 errors. **0 new failures and 0 new skips by test id**; every remaining failure predates P4C (Windows-simulation suites and the guarded v3 groups run outside their guard).
>   - `test_engine_policy.py`: 37 passed.
>   - Windows-engine suites run on the Mac through the `windows_engine_policy` seam (12 modules whole, 20 tests in mixed modules); outdated macOS pins adapted to name their platform. None weakened, none skipped.
>   - Gate `2026-11-16_190453_focused_da73` (`--platform macos`): eight darwin TTS journeys automated PASS (Edge direct and folder, service failure and retry, Cancel, Pause, PDF without text, close during work, forced landing); pytest stage, skips, coverage inventory (278 features, every source reviewed), cleanup and tree PASS. `tts.kokoro-local` is NOT APPLICABLE on this checkout (no Kokoro model installed here; P2's Kokoro evidence was in its worktree), so the run reads `RESULT: FAIL`.
>   - Native smoke, in-process on this Mac with the real policy and the real installed engine (`files/dev-work/macos-p4c/smoke/`): the first-run window shows exactly Kokoro (checked) and OmniVoice (unchecked) and names no other engine; the TTS dropdown lists exactly the 20; OmniVoice - Female 1 available on MPS; Create, then Cancel during chunk 2 of 9: settled in 2.54 s, worker gone, nothing published; a complete short Create published one MP3 in 15.8 s with no worker left.
>   - Protected assets before and after: 18/18 references, 2/2 transcript files, 28/28 previews.
> - **Owner manual (not done):** the dropdown and first-run choices by real clicks; an OmniVoice conversion with a mid-run Cancel by real clicks; the Mac's Preferences & Data wording. Windows-native verification of the touchpoints is P5 (HOME-PC).
>
> **Status 2026-11-16 (Revision 3f): P4C independent-review remediation done; READY FOR INDEPENDENT RE-REVIEW; owner acceptance pending.** Start `24398fe`; one scoped commit (Decisions, P4C remediation entry; evidence `files/dev-work/macos-p4c-r1/`, ignored).
> - **Finding fixed (CLI false success):** `generate_voice_samples` checks explicit voice patterns once, before anything runs, in ordinary samples, `--quality-suite` and `--final-acceptance` (`_explicit_selection`). On a Mac a pattern naming any Chatterbox or Qwen3 voice (alone, mixed with offered voices, or through a shared word such as "Female 1") refuses the whole request with exit 2; nothing is synthesised or written. Patterns that select no voice exit 1 on every platform; an empty quality or acceptance report is never a success. Windows requests that select voices run as before.
> - **Wording exceptions closed (Mac only, through `engine_policy`; Windows byte-identical):** an incompatible environment Python names only Kokoro; the repair's and Clear Downloaded Data's lock refusals and the repair's "held still" line name only OmniVoice; the shared install lock's "already being installed" refusals name no engine. Texts a Mac cannot reach in ordinary use are unchanged (listed in the Decisions entry).
> - **Evidence (HOME-MacOS, automated):**
>   - CLI defect reproduced at `24398fe` and absent after the fix.
>   - `test_engine_policy.py`: 80 passed (43 new).
>   - The 200 affected modules compared by test id with `24398fe`: 0 new failures, 0 new skips. The baseline failures (814 failed, 159 errors) predate this work: Windows-simulation suites and guarded groups.
>   - Gate `2026-11-16_210923_focused_23bf`: eight darwin TTS journeys PASS; pytest stage 93/93; inventory, cleanup and tree PASS. `RESULT: FAIL` only because `tts.kokoro-local` is BLOCKED: no `hexgrad/Kokoro-82M` snapshot (`f3ff357`) on this checkout, and installing it needs the owner's consent.
>   - Protected assets 18/2/28, unchanged before and after.
> - **Still open:** the owner-manual GUI checks above; the Kokoro journey (after a consented model install); Windows-native verification (P5, HOME-PC; this remediation adds `engine_lease.py`, `cleanup_worker.py` and `qwen3_setup.py` to the touchpoints).
>
> **Status 2026-11-16 (Revision 3g): owner-authorized Kokoro acquisition STOPPED before any download; the Kokoro prerequisite is still BLOCKED.** At `a713789`:
> - **Inventory:** all 11 pinned `KOKORO_FILES` missing (331,925,412 bytes); none present or corrupt.
> - **Blocker:** the app's installer (`OptionalSetupPanel` → `optional_setup_client` → `worker_launch`, used by the first-run setup and Install & Continue) refuses `.venv/bin/python`, which `python -m venv` always makes a symlink on a Mac: "the app environment's console Python is missing or reached through a link". No Mac copy can install an optional voice from the GUI. This is pre-existing: P2 and P4B called `RealAcquirer` in-process.
> - **Not done:** the in-process route skips the worker launch's link refusal and containment, so it was not used without the owner's authorization.
> - **Clean state:** nothing downloaded or changed; protected assets 18/2/28 and the OmniVoice, model and evidence trees are identical before and after (`files/dev-work/macos-p4c-kokoro/`).
> - **Gate:** still FAIL (`2026-11-16_210923_focused_23bf`); not rerun.
> - **Owner decision:** (A, recommended) a bounded fix to `worker_launch` for the venv's own interpreter link on POSIX, then Kokoro through the fixed production route; or (B) the P2/P4B in-process acquisition for this checkout.
>
> **Status 2026-11-16 (Revision 3h): Option A done; the Kokoro prerequisite is MET; the focused gate PASS; P4C READY FOR INDEPENDENT REVIEW, owner acceptance pending.** Start `aa9d3af`; one commit (Decisions, Option A entry; evidence `files/dev-work/macos-p4c-a/`, ignored).
> - **Fix:** `optional_setup_protocol.interpreter_problem` is the launch rule. On POSIX it accepts the venv's own interpreter link only when the whole chain is proved to be this copy's own (Decisions, Option A entry, rules 1–6).
>   - `worker_launch` and `RealAcquirer._acquire_spacy` use it.
>   - The worker checks itself with `worker_home_problem`.
>   - Windows and every non-link interpreter keep the old rule and words; `venv_layout.unsafe_component` is unchanged.
> - **Tests:**
>   - 48 new tests on real disposable `-m venv` environments, all PASS.
>   - The 30 affected modules compared by test id with `aa9d3af`: **0 new failures, 0 new skips, 0 removed**. 8 baseline failures now pass (the real worker launch, cancel, timeout, stop, callback and both negative controls).
>   - Four Windows-shaped pins now name their platform; none was weakened.
> - **Kokoro:** inventory 11/11 MISSING. Then, through the real worker (class A under its owner, its own process group, nothing left):
>   - plan: Kokoro only, 10 units, 331,925,412 bytes, all at `f3ff357`; spaCy ready, so not acquired;
>   - install: succeeded in 16.2 s, one consent spent.
>
>   An independent check matched 11/11 files by size and full SHA-256.
> - **Journey:** `tts.kokoro-local` PASS, 16/16 (`2026-11-16_234103_focused_9b07`): one MP3, 5.29 s, RMS 0.0448, 160 kbit/s, clean close.
> - **Gate:** `2026-11-16_234204_focused_4cf5`, **RESULT: PASS**. 9/9 journeys; pytest 93/93; inventory, cleanup, skips and tree PASS.
> - **Protected:** assets 18/2/28 identical. Only `files/runtime-data/models` changed: +11 Kokoro files and the verified record.
> - **Findings for the owner:**
>   1. On POSIX, a grandchild left by a worker that exited normally is not ended with the run (Windows' job does that). Cancel and time-out end the group. Closing the gap is a containment design decision. `test_a_grandchild_left_behind_by_a_worker_that_exited_is_ended_with_the_run` still fails on the Mac: it was a baseline failure and now fails for this reason.
>   2. This checkout's root, `scripts/`, `files/` and `files/runtime-data/` are world-writable; the app's own folders are not.
> - **Still open:** the owner-manual GUI checks (Handoff), independent review, owner acceptance of P4C, and Windows-native verification (P5, HOME-PC; this adds `optional_setup_protocol.py`, `optional_setup_worker.py` and `optional_setup_acquire.py` to the touchpoints).
>
> **Status 2026-11-17 (Revision 3i): P4C OWNER ACCEPTED** (Decisions, P4C acceptance entry).
> - **Owner checks passed:** the 20 voices; the first-run choices; the Kokoro Heart and OmniVoice Male 1 MP3s; the OmniVoice Male 3 Cancel in 2.303 s with no incomplete MP3; the Preferences & Data wording.
> - **Not an approval to merge or release.**
> - Findings 1 and 2 above became P5-A's scope (P5 status below).
> - Windows-native verification stays with P5 (HOME-PC).

### P5 — Cross-platform integration and macOS acceptance
> **Status 2026-11-17 (Revision 3j): P5-A IMPLEMENTED and TESTED (automated, this Mac); independent review and owner approval pending.** Start `48fb12b`; one commit (Decisions, P5-A entry; evidence `files/dev-work/macos-p5a/`, ignored). Scope: only A–C below. P5-B and the rest of P5 need their own authorization.
> - **A. Containment** (finding 1 of P4C):
>   - **Reproduced at `48fb12b`:** the worker had been reaped, and its grandchild was alive in the worker's old group.
>   - **Fix (POSIX only):** the worker is never reaped before its group is ended. `child_ownership.end_led_group` signals the group only while three things hold: the `Popen`'s waitpid lock is held, the worker is unreaped, and its start time matches the one recorded at spawn. It then waits, bounded, until macOS reports no member left, and only then is the worker reaped.
>   - A group that cannot be proved is never signalled.
>   - Windows' Job Object path is unchanged.
>   - **Mac containment:** PASS (automated, native).
> - **B. Interpreter:** `pyvenv.cfg` `executable` is required, absolute and exactly this copy's `python3.12`; `home` must be absolute. This was proved first on disposable venvs. The production `.venv` passes and was not rebuilt.
> - **C. Permissions (read-only audit; finding 2 of P4C):** the 777/666 modes came with the checkout, and ACT's own folders are 755/644. The correction is PENDING THE OWNER (§20.3). The interpreter-link rule does not close this.
> - **Tests:**
>   - The previously failing grandchild test passes natively.
>   - 28 new tests: 7 in `test_child_ownership.py`, 8 `WorkerRun` lifecycle tests and 13 `pyvenv.cfg` cases.
>   - The 37 affected modules were compared by test id with `48fb12b`: 0 new failures, 0 new skips, 0 removed; 28 added, all PASS; 1 fixed.
> - **Gate:** focused gate `2026-11-17_053703_focused_61f2` **RESULT: PASS** (9/9 journeys; pytest 116/116; process-ownership, cleanup, skips and tree PASS).
> - **Protected:** assets 18/2/28, the 11 Kokoro files, the engine, model and package trees, the P4A–P4C evidence and draft release `447445728` identical before and after.
> - **Residuals for the owner** (Decisions, P5-A entry):
>   1. `setsid` escapees;
>   2. the first-run window is not a containment owner, so the worker's own children survive a forced Cancel there (reproduced);
>   3. the unlocked identity check in `Owner.shutdown`;
>   4. an app killed in the at most 0.2 s after the worker exits.
> - **Still PENDING:**
>   - the owner's permissions decision;
>   - the Windows-native regression on HOME-PC, which adds `child_ownership.py`, `optional_setup_protocol.py`, `optional_setup_client.py` and the Windows skip rules to the touchpoints;
>   - the rest of P5: long-form runs, D6-final, the darwin acceptance map and KX-10.
>
> **Status 2026-11-17 (Revision 3k): P5-A-R1 (independent-review remediation) IMPLEMENTED and TESTED (automated, this Mac); independent re-review and owner approval pending.** Start `266d603`; one commit (Decisions, P5-A-R1 entry; evidence `files/dev-work/macos-p5a-r1/`, ignored).
> - **Finding (reproduced at `266d603`):** `WorkerRun` returned the worker's own `succeeded` when its group was `unproved` or `remaining` (only `protocol_errors`, which the caller never sees, recorded it). The same happened when `result()` was read after an outside reap, and a Cancel with unconfirmed cleanup was a clean `cancelled`.
> - **Fix (POSIX only, `shared/optional_setup_protocol.py`):** the run's outcome may be the worker's result, or the cancelled/timed-out/no-result outcome, only when the group end is `GROUP_ENDED`. Otherwise it is `failed`, `forced`: `containment-unproved` (identity uncertainty; nothing signalled) or `containment-incomplete` (termination not confirmed: `remaining`, `signalled`, unknown). The original outcome stays in the message, `verified` is kept, and a published worker result file is never replaced.
> - **Unchanged:** `child_ownership` (identity proof, waitpid lock, reap last, 15 s bound), `GROUP_ENDED` outcomes, Cancel and time-out with confirmed cleanup, consent and install protections, the Windows Job Object path.
> - **Tests:** 12 new (11 POSIX-only, 1 every platform); 10 failed before the fix. The 37 affected modules by test id against `266d603`: 0 new failures, 0 new skips, 0 removed, 0 changed; 12 added, all PASS.
> - **Gate:** focused gate `2026-11-17_082412_focused_5388` **RESULT: PASS**, exit 0 (9/9 journeys including `tts.kokoro-local`, Cancel and both shutdown journeys; pytest 116/116; process-ownership, cleanup, skips and tree PASS). Protected assets and draft release `447445728` unchanged.
> - **Still PENDING:** the owner's permissions decision; the first-run window as containment owner (the recommended P5-B); the Windows-native regression on HOME-PC; the rest of P5.
>
> **Status 2026-11-17 (Revision 3l): P5-B (first-run window as containment owner) IMPLEMENTED and TESTED (automated, this Mac); independent review and owner approval pending.** Start `a88f3fb`; one commit (Decisions, P5-B entry; evidence `files/dev-work/macos-p5b/`, ignored).
> - **Defect (reproduced at `a88f3fb`, real processes):** the first-run window was not a containment owner. `qwen3_process.spawn` started its worker without a lifeline, and the worker started pip and the probes the same way. A forced Cancel or time-out left pip's helper running; closing the window, SIGKILL or a crash of setup left the worker, pip and the helper running.
> - **Fix (POSIX only, `shared/bootstrap.py`):** `own_optional_setup()` before the panel's first check makes setup's own owner the containment owner, the app window's arrangement. Workers are then class A on setup's lifeline, and pip and the probes are class A on the worker's lifeline. `settle_optional_setup()` after the window: no new start; each run ends and reaps its own worker first (bounded by `OPTIONAL_SETUP_SETTLE_S`, 30 s); a straggler's group is ended by `end_led_group`; then `Owner.shutdown`.
> - **Unchanged:** `WorkerRun` and R1's outcomes, `child_ownership`, the client and panel, consent and install protections, "Stop setup?", Install & Continue in the app window, the Windows Job Object path.
> - **Tests:** 23 new (19 POSIX-only, 4 every platform); 22 failed before the fix. The 70 affected modules plus the new one by test id against `a88f3fb`: 0 new failures, 0 new skips, 0 removed, 0 changed among 4,185 existing ids; 23 added, all PASS (one test-harness readiness race found in the full run, reproduced and fixed before the gate).
> - **Gate:** focused gate `2026-11-17_174054_focused_060c` **RESULT: PASS**, exit 0 (9/9 journeys including `tts.kokoro-local`, Cancel and both shutdown journeys; pytest 143 passed, 2 policy-named skips, 0 failed; process-ownership, cleanup, skips and tree PASS). Protected assets and draft release `447445728` unchanged.
> - **Still PENDING:** the inherited normal-exit gap (a pip or probe that exits leaving a helper in its own group, both windows; recommended next); the locked identity check in `Owner.shutdown`; the owner's permissions decision; the Windows-native regression on HOME-PC, which adds `test_first_run_setup_ownership.py` and the rule `posix-first-run-ownership-p5b`; the rest of P5.
>
> **Revision 2 (2026-11-16; Q3=A):**
> - **Entry:** P4C complete. Every engine on the macOS roster is PROVEN; every other engine is SKIPPED BY OWNER DECISION and absent from the macOS experience.
> - **macOS scope:** the Edge/Kokoro (and, if accepted, OmniVoice) application and the five non-TTS tools:
>   - native setup and first launch, and automatic platform detection;
>   - the voice roster, and every visible voice's availability and synthesis;
>   - Kokoro download consent and repair;
>   - Edge behaviour, with Andrew's limitation stated honestly;
>   - long-form generation with no clipped text or missing paragraphs, and correct assembly and publication;
>   - immediate Cancel, and Pause at its boundaries;
>   - crash and Force Quit containment, with no orphan engine or FFmpeg process;
>   - source preservation and output-path safety;
>   - MP3 Tool, M4B Converter, M4B Maker, M4B Metadata Editor and Cover/Image Tool;
>   - the native layout, scrolling and important controls.
>
>   Existing P2 evidence is preserved and reused where it is still current. Known limitations are recorded honestly.
> - **HOME-PC:** the Windows focused regression and E-B2 are **PENDING** until HOME-PC is available. The Mac can reach `MAC IMPLEMENTATION COMPLETE — RELEASE QUALIFICATION PENDING`, never released. Both items must pass before P6 starts.
> - The Revision 1 text below is superseded where it differs.

- **Entry:** P4A/P4B closed. Every engine is either PROVEN or carries its recorded per-engine D7 decision.
- **Scope:**
  - long-book qualification (text D) for Kokoro, plus ≥30-minute runs for each other proven engine;
  - the §15 benchmark table, and **D6-final** per engine;
  - App Nap / hidden-window run;
  - the complete darwin acceptance map: every automated counterpart PASS; every class-(b) item signed for the candidate;
  - the remaining KX-10 drills;
  - Briefing/Decisions updates and feature-map entries for the behaviour shipped (truthful per engine). The release-facing README/Changelog text and the version identity are finalized in P6a;
  - **HOME-PC focused Windows regression** on all accumulated Windows touchpoints (owner or a Windows agent).
- **Owner manual:**
  - full macOS GUI pass of all six tools;
  - final listening sign-off across all proven voices.
- **Exit:**
  - owner acceptance of macOS functionality;
  - Windows focused regression PASS;
  - **D16** recorded (version identity and release strategy);
  - **D18** recorded (the REAL CLEAN route), with the clean machine or VM available before P7c.

### P6 — Release-source finalization, independent Codex review, remediation and owner acceptance
- **Entry:** P5 accepted; D16 and D18 recorded.
- **P6a, release-source finalization.** Everything release-relevant is final **before** review:
  - the version identity per D16 (`config.toml`, `version.py`);
  - `RELEASE_OS_NAMES` includes MacOS (MAC-033);
  - the MacOS platform declarations:
    - README platform and engine tables, with each engine's F/S/Q/P and D7 status;
    - Briefing and Changelog;
    - the feature map;
    - the final `platform_supported()` state of each engine, per its recorded decision;
  - packaging support: `release.py` MacOS rules and the archive audit tooling;
  - focused version, packaging and documentation tests;
  - **six OmniVoice previews (Revision 3, owner requirement; must not be dropped from release preparation; HOME-PC may be used):** `omnivoice-female-1.wav`, `-female-2`, `-male-1`, `-male-2`, `-male-3`, `-male-4` added to `files/voice-previews/` (34 in the gallery). Requirements:
    - the 28 existing previews preserved byte-for-byte;
    - the same short sample text as the gallery;
    - generated by the approved OmniVoice production pipeline, not the P4A MP3s;
    - valid lossless WAVs matching the gallery's sample format, with its quality checks;
    - exact voice identities, hashes, durations and generation provenance recorded;
    - the original reference WAVs and transcripts never published;
    - the existing rights/publication decision framework kept, with the model's CC-BY-NC weights and the Higgs Audio tokenizer terms reviewed before publication (owner intent: publish, subject to that review);
    - `files/voice-previews/README.md`, `previews.json`, `files/dev-tools/voice_previews.py` and its focused tests updated;
    - the gallery kept apart from the runtime roster (Windows registers 34 voices; the Mac offers 20);
    - **the owner's README format is the target** (owner commits `7842280`, `e4d7378`, 2026-11-16): the fourth column is `Availability` ("MacOS + Windows" for Edge, Kokoro and OmniVoice; "Windows Only" for Chatterbox and Qwen3), and six OmniVoice rows read "To Be Added". Since those commits `voice_previews.py check` reports "README.md is out of date with the manifest" (the renderer still writes the old `Publication` column). P6a changes the renderer, manifest and tests to produce exactly this format with the six real links. `voice_previews.py readme` must not be run before then: it would overwrite the owner's edit.

  Then a **packaging rehearsal** from a clean LF worktree:
  1. audit the rehearsal archive;
  2. extract a quarantined copy with Archive Utility and with `ditto`;
  3. go through the Gatekeeper "Open Anyway" flow;
  4. run the `fresh-macos` **rehearsal**, labelled SIMULATED or REAL CLEAN.

  Freeze and push the release candidate.
- **P6b:** independent Codex review of that candidate (§16).
- **P6c:** remediation and the focused closure check.
- **P6d:** owner acceptance. This **freezes the final executable SHA**, which is recorded in Handoff.
- **Exit:**
  - the final executable SHA frozen and pushed;
  - every finding closed or waived in writing;
  - **no full gate run in P6**.
- **Stop:** the rehearsal audit fails; the Gatekeeper path is unusable; a finding re-opens an engine phase (return to that phase, then P6 again).

### P7 — Canonical gates on the final SHA, exact archives and publication approval
- **Entry:**
  - P6d complete;
  - a clean LF worktree on the Mac and a clean checkout on HOME-PC, both at the final executable SHA;
  - the REAL CLEAN machine ready (D18).
- **P7a:** the **one** macOS full gate on that SHA (§17).
- **P7b:** the **one** Windows full gate on the same SHA (D8).

  Any FAIL is BLOCKED: diagnose, and get owner approval before any rerun. A fix is a post-freeze change under §17: a new SHA, a closure check of the delta, and both gates again.
- **P7c,** after both gates PASS, with **no source change**:
  1. build both archives from clean checkouts of the final SHA;
  2. audit them (§18) and record their SHA-256s;
  3. run the **binding `fresh-macos` qualification, REAL CLEAN**, on the exact macOS archive, downloaded with a browser and therefore quarantined;
  4. audit the Windows archive and run its fresh qualification per the existing Windows release practice.

  A failure here is a post-freeze change: it is never patched into the archive.
- **P7d:** the owner decides each step separately:
  - merge (fast-forward of `master` to the final SHA);
  - tag (annotated, on the final SHA);
  - publish.

  Then an anonymous re-download is verified (hash = audited file), and the Handoff closeout follows as a documents-only commit after the tagged SHA.
- **Exit:** published release verified by anonymous download; Handoff closeout.
- **Stop:** any provenance mismatch; any change needed inside the tagged tree (§17 change rules).

---

## 20. Risks, unresolved blockers and owner decisions

### 20.1 Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | The app-owned runtime brings **Tk 9.0.4** (PBS) where Windows has Tk 8.6. Tk 9 + Python 3.12 relies on PBS's downstream patches (the #1320 threading fix shipped in `20261009`), and is untested by ACT on macOS 27. Possible issues: blurry or unfocused windows (non-framework build), trackpad scrolling, geometry pins | Medium / medium–high (GUI is the product surface) | Bounded Tk proof in stage 0; the P1B Tk 9 port (§10); aqua tests; owner GUI check. Fallback D1 → python.org 3.12.10 + Tk 8.6.16 (admin install, frozen since 2025-04) only by owner decision |
| R2 | torch 2.6.0 (Jan 2025) on macOS 27: CPU fine, MPS untested by PyTorch on macOS 27 | Medium for MPS, low for CPU | CPU defaults; MPS only by measured evidence; a pin bump is an owner decision with Windows re-verification |
| R3 | MPS silent wrong output: multinomial zero-probability picks (pytorch#192577), MPSGraph argmax read past buffer on macOS 27 (pytorch#187280), NaNs in fp16 | Medium / high (garbled audio without an exception) | Correctness oracle vs CPU fp32 (§15); fallback disabled during experiments; no MPS default without owner acceptance |
| R4 | MPS allocator growth on 24 GB (chatterbox#577: 3.2 GB allocated, 24.9 GB driver) | Medium / high (swap, stalls) | Memory slope checks; `empty_cache` between chunks; watermark ratios; bounded workers; CPU default |
| R5 | Qwen3 CPU too slow for whole books (about 2.6× slower than real time reported on a base M4) | High / medium | Provisional budget D6-Q set at P3B (not deferred to P5); P reported separately from F/S/Q; honest speed note; keep available or gate per owner |
| R6 | OmniVoice MPS fp16 garbled on M4 (#172) vs working (#279) | Medium | P4A three-configuration experiment before any code; a failed gate stops for a separate D7-O decision |
| R7 | The POSIX installer authority is security-sensitive and new | Medium / high | D12; focused race/symlink tests; Codex priority |
| R8 | Gatekeeper friction for unsigned `.command` in a downloaded ZIP | High / medium (first-run UX) | Clear README and launcher guidance; D10 (signing/notarization is a future option) |
| R9 | Tk/AppKit main-thread crashes from worker callbacks | Low–medium / high | Static audit + stress test (P1B) |
| R10 | Shared-code changes regress Windows | Medium / high | Platform guards; touchpoint list; HOME-PC focused regression (P5) + Windows full gate (D8) |
| R11 | In-process engines (Kokoro, Chatterbox) keep models resident; switching engines may stack memory | Medium / medium | On darwin the models live in the local-engine worker, one engine at a time, ended on engine switch (§11.2.1); measure in P3A/P5. Windows unchanged |
| R12 | Edge service changes (403s, voice removals) | Low–medium / medium | Upstream-outage = BLOCKED, not FAIL; pinned edge-tts reviewed at P2 entry. 7.3.1 is current as of 2026-11-14. `NoAudioReceived` (#512) is open upstream, so ACT's existing per-file retry policy applies unchanged |
| R14 | Duplicate OpenMP runtimes (torch + sklearn/numba `libomp`) abort a process on macOS | Low–medium / high | E-B1 imports everything in one process before any synthesis work |
| R15 | torch 2.6.0 (pinned by chatterbox-tts 0.1.7 metadata) fails on macOS 27 | Low (CPU) / high (shared pin) | P1A import proof; options listed in §12.B, owner decision |
| R16 | eSpeak NG data-path length limit (≥ 160 chars → `exit(1)`) in deep install folders | Medium / high for Kokoro | Verify the `espeak_data` short root; refuse too-deep folders before downloads, like the Windows depth checks |
| R13 | App Nap / idle sleep during long books | Medium / medium | Measure; optional `caffeinate -w` (D11d) |
| R17 | The local-engine worker adds a cold model load after each Cancel (~3 GB for Chatterbox), IPC per chunk, and a second code path beside Windows' in-process one | Medium / medium | Warm reuse across files and runs; load time measured and logged; parity proof against the in-process path (§11.2.1); the worker is the only darwin path, so it is fully covered by the P2/P3A tests |
| R18 | Containment residuals: a guardian killed by hand leaves the in-flight class-B children of its old group covered only by the orderly path; a future fork-without-exec in an owner would leak the lifeline write end | Low / medium | Guardian restart + logging; KX-6; the `multiprocessing` start-method assertion and the KX-9 spawn-site guard; Decisions records the residual |
| R19 | SIMULATED clean-install evidence on this Mac (Homebrew and the CLT present) misses a dependency that only a truly clean Mac reveals (CLT stub prompts, Gatekeeper, privacy prompts) | Medium / high (first-run failure for real users) | Evidence classes kept separate (§8.2, §14.2); linkage and loaded-image checks in P1A; **REAL CLEAN `fresh-macos` mandatory** on the exact archive (P7c, D18) |
| R20 | The Riedl 9.0.1 binary differs from its published listing, is re-signed or withdrawn, or its `aac_at` misdecodes real xHE-AAC | Low–medium / medium | Eight adoption proofs on the actual bytes (§11.1); ACT's own digest and signing identity pinned; 9.0.2 only by owner acceptance; never an unproven pin |
| R21 | Git hygiene: a new executable recorded as `100644` under `core.filemode=false`, or a broad CRLF/mode "cleanup" rewriting hundreds of files | Medium / medium | §3.1 rules; `git add --chmod=+x` + `git ls-files -s`; an index-mode test; `--stat`/`--summary` review at every commit |
| R22 | A change after the gates (a late fix, a version or README correction) leaves the archives or the tag on an unverified tree | Medium / high (provenance) | Release source final in P6a; both gates on one frozen SHA (P7a/P7b); the §17 post-freeze change table; archives built afterwards with no source change |

### 20.2 Unresolved blockers (today)

- **B1.** Qwen3 installation on macOS is BLOCKED by the Windows-only `artifact_store.boundary` (fails closed). It needs the D12 port. *Revision 2: moot on macOS. Qwen3 is SKIPPED BY OWNER DECISION.*
- **B2.** OmniVoice and Qwen3 workers have CUDA-only / Windows-only code paths and `platform_supported()` gates. Removing them is gated on experiments. *Revision 2: Qwen3 is SKIPPED BY OWNER DECISION. For OmniVoice the gate is the bounded P4A (§12.E); the CUDA-only call sites are listed there for P4B.*
- **B3.** A fresh Mac without Homebrew cannot set up today: the launcher depends on Homebrew. Resolved by P1A.
- **B4.** No `darwin` skip policy exists, so any macOS gate result today is untrustworthy. Resolved by P1B.
- **B5.** Kokoro and Chatterbox inference cannot be preempted by Cancel (in-process, cooperative between chunks), which breaks the immediate-Cancel rule on a Mac CPU. Resolved by the local-engine worker (P2, P3A; MAC-043).
- **B6.** No POSIX parent-death containment: after a crash, SIGKILL or Force Quit, ACT's FFmpeg, pip and worker children are not ended. Resolved by §11.2.2 (P1A setup side, P1B GUI side, P2–P4B workers; MAC-009, MAC-044).
- **B7.** The 55 acceptance journeys exist only through the Windows input adapter. Resolved by the darwin acceptance map and the in-process journey driver (P1B–P5; MAC-045).

None of these blocks the *plan*.

### 20.3 Owner decisions required (recommendation first)

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Base Python for macOS | App-owned python-build-standalone 3.12.15+20261009 aarch64 (same as Windows): no admin, SHA-pinned, **Tk 9.0.4 on macOS**, so the bounded Tk 9 port is accepted. Fallback only on P1A failure: python.org 3.12.10 (Tk 8.6.16, admin, frozen) |
| D2 | Launcher stops installing Homebrew and Homebrew Python | Yes; the app-owned runtime only |
| D3 | FFmpeg on macOS | Accept a discovered arm64 pair only if proven (incl. `aac_at`, `libmp3lame`). App-owned source: **evaluate the historical Martin Riedl arm64 9.0.1 build first** (`1787073674_9.0.1`; published `codecs.txt` lists `aac_at` and `libmp3lame`), adopted only after the eight proofs of §11.1 on the actual bytes: consented download, size + SHA-256 computed and matched to the published `.sha256`, safe extraction, arm64, signature, linkage, execution, **real xHE-AAC**. 9.0.2 only if 9.0.1 fails, by separate owner acceptance. No digest is recorded before P1A has the bytes |
| D4 | Checkout hygiene and Git rules | `chmod +x` the `.command` in this tree (disk only); build releases and run the full gate from a clean LF worktree under `files/dev-work/worktrees/`; follow §3.1: no broad CRLF/mode cleanup, new executables staged with `--chmod=+x` and verified as `100755`; `.claude/CLAUDE.md` reconciled by the owner, not by a phase |
| D5 | Network access for P1A | Approve python-build-standalone, PyPI and the FFmpeg source for lock generation and first-run tests |
| D6 | Speed/memory budgets per engine | **Provisional budget at each engine checkpoint:** D6-E and D6-K at P2 entry, D6-C at P3A entry, D6-Q at P3B after E-D2, D6-O at P4A entry (starting proposals in §12). Each phase judges its P verdict against its budget; **D6-final** confirmed at P5 from long-form runs, any change recorded with its reason. F/S/Q correctness thresholds (§15) are fixed and never traded for speed |
| D7 | If an engine fails its feasibility gate (F, S or Q) | **No standing answer.** Approving this roadmap does **not** consent to shipping without Qwen3, OmniVoice or any other engine. After each failed gate the phase STOPS and the owner records a separate, explicit decision for that engine (**D7-Q** Qwen3 at P3B, **D7-O** OmniVoice at P4A/P4B; D7-E, D7-K, D7-C likewise if Edge, Kokoro or Chatterbox fail) with the evidence. Options: keep investigating; try another configuration; ship macOS without the engine (its voices visible-unavailable with the measured reason, never substituted); or defer the macOS release. The recommendation is given per case, with the evidence. **Revision 2 (2026-11-16):** D7-C and D7-Q are answered by Q1/Q2 (SKIPPED BY OWNER DECISION on macOS). D7-O is answered in advance by Q1=A: abandon on demonstrated failure or owner rejection, with no new question. The "visible-unavailable" option is replaced by Q2=A (removed from the macOS experience) |
| D8 | Windows evidence for a combined release | **Required:** the canonical Windows full gate on the **same final executable SHA** as the macOS gate (P7b). Anything less needs a recorded owner exception, stated in the release notes |
| D9 | macOS GUI acceptance method | No macOS native-input adapter and no Accessibility / Screen Recording grants, but **no exemption**: every acceptance journey is mapped to a native automated counterpart (in-process journey driver), a documented owner-manual check with signed evidence, or a reviewed per-journey not-applicable reason (§14.3). **D9b:** the extracted `fresh-macos` fresh-install/repair qualification is **mandatory** (REAL CLEAN at P7c); only its *automation* is optional |
| D10 | Gatekeeper UX | README + launcher guidance for "Open Anyway"; no signing this release; Developer ID / notarization as a future decision |
| D11 | Optional improvements | (a) F_FULLFSYNC: no; (b) macOS work-area recovery: yes if cheap; (c) qualify a macOS FFmpeg build for the continuous route: later; (d) `caffeinate` during jobs: decide after the P5 measurement |
| D12 | Qwen3 installer authority on POSIX | Implement the dir-fd design (same guarantee), not a reduced-guarantee shortcut. *Revision 2: not needed on macOS while Qwen3 is SKIPPED BY OWNER DECISION* |
| D13 | Cross-copy engine lock location | Per-user temp (`tempfile.gettempdir()/ACT-locks/`), consistent with the existing work area |
| D14 | Download consent and disk budget | Per-engine, as Windows (§9 table shown before consent) |
| D15 | ASR for WER | Reuse the pinned Whisper small.en in a dev-only scratch environment, on consent. **Still open** (2026-11-16): WER for P2 and P4A is NOT RUN until the owner decides |
| **Q1** | OmniVoice on macOS | **DECIDED 2026-11-16: A.** One bounded technical feasibility campaign (P4A, §12.E Revision 2, before P3). Abandon its macOS integration if it proves impractical or unreliable, or if the owner rejects its audio |
| **Q2** | What the Mac shows when the fallback is active | **DECIDED 2026-11-16: A.** Unsupported engines are removed completely from the macOS user-facing experience (§12.F, P4C). Shared Windows code, assets, voice identities and base dependency pins are kept |
| **Q3** | Windows evidence while HOME-PC is unavailable | **DECIDED 2026-11-16: A.** Finish and verify the Mac implementation now. Native Windows verification (E-B2, the Windows focused regression) and the final cross-platform release qualification are deferred until HOME-PC is available, not waived. D8 and P7 are unchanged |
| **D6-O** | OmniVoice speed/memory budget and the practicality line | Proposed at Revision 2: MPS RTF ≤ 1.0, CPU RTF ≤ 3.5, peak footprint ≤ 10 GiB, growth < 10 % after warm-up (fixed). The proposed line then read: if every technically passing configuration falls outside it, that is the Q1 "impractical" line. **SET 2026-11-16 (Revision 2a): the four values are provisional practicality targets, not automatic rejection thresholds.** A technically correct configuration outside a target is a PERFORMANCE EXCEPTION — OWNER DECISION PENDING, unless its resource behaviour is unsafe, which fails S. F, S, Q and P are separate verdicts; the owner decides speed, footprint and quality (§12.E). **Revision 3 (2026-11-16): C2 MPS fp32's speed exception is accepted for integration** (no memory, safety, Cancel or reliability requirement waived) |
| **P4A acceptance** | OmniVoice on macOS | **ACCEPTED 2026-11-16 (Revision 3):** six voices by owner listening; MPS fp32 preferred, CPU fp32 alternative, MPS fp16 experimental; P4B authorized; macOS roster Edge + Kokoro + OmniVoice = 20; six OmniVoice previews added at P6a |
| **P4B checkpoint** | OmniVoice on macOS, production | **OWNER ACCEPTED 2026-11-16 (Revision 3d)** with its memory performance exception: keep 16 chunks per Mac-GPU worker (48 elsewhere), no `empty_cache` policy, no further memory optimization authorized; P4C authorized. History: **PENDING THE OWNER (2026-11-16):** TECHNICAL PASS (F, S); memory growth inside one worker +28.4 % after warm-up (bounded by the 48-chunk restart, MPS tensors flat) is a PERFORMANCE EXCEPTION against D6-O's provisional < 10 %: (a) accept as bounded, or (b) a Mac-only mitigation experiment. P4C follows the acceptance. **Memory checkpoint (Revision 3b): NOT OWNER ACCEPTED.** The cause is MPS allocator buffer retention plus per-shape MPSGraph caches. A Mac-GPU bound of 16 chunks per worker is implemented: worst measured peak 13.6 → 10.7 GB, growth +28.4 → +10.6 % on the 60-chunk sequence, bit-identical audio. Windows and the Mac's CPU keep 48. The peak (stress text) and growth targets are still missed: PERFORMANCE EXCEPTION — OWNER DECISION PENDING, with options (a) accept, (b) an `empty_cache` experiment, or (c) revert. **Option B ran (Revision 3c): no meaningful improvement.** Keep 16 and adopt no clearing. The exception stays OWNER DECISION PENDING (book-like text peaks 10.7–11.1 GB; growth +20 to +31 %) |
| **P4C checkpoint** | macOS roster through one capability policy | **OWNER ACCEPTED 2026-11-17 (Revision 3i):** the owner's GUI checks passed. This is not an approval to merge or release; only P5-A is authorized |
| **P5-A permissions** | The checkout's inherited world-writable modes (P5-A read-only audit, `files/dev-work/macos-p5a/permissions-audit.md`) | **PENDING THE OWNER.** Recommended: the owner runs `chmod -R go-w <repo>` on this checkout, or the audit's targeted list. Normalising ZIP entry modes is a P6/P7 item. Nothing was changed, and the interpreter-link rule does not close this |
| **P4A consent** | Acquisition for P4A | **GIVEN 2026-11-16:** only the files of `files/dev-tools/macos_p4a_omnivoice_manifest.json` at `bac67d4`, token `7932d4ef5b3ed0e531b958b9729f1de77ce27de37c755de290d5d9b896f62f4c` (86 wheels, 246,737,206 bytes; 11 model files, 3,267,467,171 bytes), into `files/dev-work/omnivoice-feasibility/` only. Whisper **not** authorized (D15 deferred until after the owner's listening verdict) |
| D16 | Release version and strategy | §18 option A (v0.8.1), or D (v0.9.0). **Decided at P5 exit**, because the version identity is release-relevant source finalized in P6a, before review and both gates |
| D17 | Preemptible Cancel for local engines | On darwin, Kokoro and Chatterbox run in the supervised local-engine worker; accept the Cancel contract C1–C5 and its bounds (§11.2.1). Windows keeps the released in-process path in this programme; adopting the worker on Windows is a later decision with Windows qualification |
| D18 | REAL CLEAN qualification route | An Apple Silicon Mac that never had Homebrew, the Xcode CLT or python.org (a second Mac, or a freshly erased one), or a macOS virtual machine (needs an approved virtualization tool install and macOS image download). A new user account on this Mac is SIMULATED only. Decided at P5 exit; used at P7c |

---

## 21. Phase-by-phase checklist and stop conditions

**Universal checklist (start of every phase):**
1. A fresh context.
2. Read this plan, `AI-WORKSPACE.md`, `md-instructions/Handoff.md` (top block) and the prior phase report. `.claude/CLAUDE.md` is local and partly stale (§3.1): this read order governs, and its absent paths and delegation route are not used.
3. `git status -sb`, `git log --oneline -5`, `git fetch origin`. Confirm:
   - the branch is `feature/0.8.0-macos-compatibility`;
   - HEAD is the expected prior SHA;
   - the owner state is unchanged (17 deletions + the untracked set);
   - the inherited `core.filemode=false`, `core.symlinks=false` and `core.ignorecase=true` are as recorded, and nothing is "fixed" (§3.1).
4. Confirm this phase's entry decisions and consents are recorded: for an engine phase, its provisional budget D6-x; after a failed gate, its D7-x.
5. Re-verify the 18 reference hashes if this phase runs any engine.
6. List the planned focused tests, the CX/KX ids due in this phase (§11.2.3), and the evidence class each result will carry.

**Universal checklist (end of every phase):**
1. Focused tests pass, with counts recorded.
2. Real-runtime evidence recorded (paths in ignored folders only), with its evidence class and source (§14.2). An engine phase records its F/S/Q/P verdicts.
3. 18 reference hashes re-verified (engine phases).
4. No ACT-owned process remains after the phase's tests (the read-only check script).
5. Windows touchpoints updated.
6. Handoff updated (Decisions for non-obvious choices).
7. Stage explicit paths only. Review `git diff --cached --stat` and `--summary`: only intended files, no CRLF or mode churn. Every new executable shows `100755` in `git ls-files -s` (§3.1).
8. Commit and push to the feature branch.
9. Report (verdict, SHA, files, tests, evidence, open items, decisions due, next phase).
10. **STOP.**

**Universal stop conditions (any phase):**
- Any immutable contract in §13 would change.
- A test passes only by weakening, skipping or deleting a meaningful check.
- A Windows code path would change behaviour without being a deliberate, owner-approved shared fix.
- An engine would be enabled without its proof, or a voice substituted.
- An engine fails its feasibility gate (F, S or Q): STOP for that engine's separate D7 decision. Roadmap approval is never that decision.
- A Cancel bound of §11.2.1 is exceeded, or a cancelled run publishes anything under a final name.
- Any ACT-owned process outlives its owner in a containment test (outside the class-D allow-list).
- Any download without recorded consent; any digest recorded without the bytes it describes.
- Any action outside the repository, or a system setting change (Gatekeeper, SIP, permissions, global Python, Homebrew, shell profiles).
- A broad Git cleanup (renormalize, restore, repository-wide mode change) is about to happen (§3.1).
- A full gate is about to run outside P7a/P7b, or on a SHA other than the frozen final executable SHA.
- Any change inside the tagged tree after the P6d freeze without the §17 re-verification.
- SIMULATED evidence is about to be reported as REAL CLEAN.
- Git state contradicts Handoff (trust Git, investigate, correct Handoff).
- Repeated failure of the same real-runtime test (diagnose, don't loop).

| Phase | Must be true to start | Must be true to finish | Hard stop if |
|---|---|---|---|
| P1A | Revised plan approved; D1–D5 (D3 as revised); owner's xHE-AAC file available; chmod approved; §3.1 acknowledged | SIMULATED (PATH-restricted + linkage-verified) first run → healthy app, no Homebrew call/link/load, no admin; locks hashed; FFmpeg 9.0.1 adopted after the eight proofs (or BLOCKED back to D3); installer containment and interruption recovery PASS; new executables `100755`; focused PASS | PBS Tk fails; a pin cannot resolve natively; torch 2.6 import fails; both Riedl candidates fail; evidence would need a system change |
| P1B | P1A PASS | Five tools PASS (focused + real media + acceptance counterparts + owner GUI); CX-5/CX-8 and GUI KX tests PASS; darwin gate policy; every acceptance scenario mapped | Unfixable Tk/AppKit crash; invariant break; an orphan after a KX test |
| P2 | P1B PASS; D6-E, D6-K set | 14 Edge/Kokoro voices PROVEN (F, S, Q) + listening; P vs budget recorded; local-engine worker Cancel within 2 s | Kokoro pronunciation regression; espeak-ng failure; Cancel bound exceeded; F/S/Q failure (→ D7-E/D7-K) |
| P3A | **SKIPPED BY OWNER DECISION on macOS (Revision 2).** Originally: P2 PASS; D6-C set | 6 Chatterbox voices PROVEN (CPU or accepted MPS); P vs D6-C recorded; Cancel within 2 s mid-chunk | MPS made default without the oracle; memory blow-up on CPU; F/S/Q failure (→ D7-C) |
| P3B | **SKIPPED BY OWNER DECISION on macOS (Revision 2).** Originally: P3A closed; D12; consents; D6-Q after E-D2 | 8 Qwen3 voices PROVEN (F, S, Q) with P vs D6-Q, **or** STOP and a separate D7-Q recorded after the failure | CPU fp32 fails E-D3/E-D4 (gate stays closed; wait for D7-Q) |
| P4A | **Revision 2:** authorized early (Q1=A); consent to manifest token `7932d4ef…`; D6-O set | One campaign outcome (§12.E): TECHNICAL PASS → owner listening; FALLBACK CONDITION MET → P4C; or BLOCKED reported | Any reference WAV hash change; any download without consent; any tuning loop |
| P4B | P4A accepted configuration | 6 OmniVoice voices PROVEN (F, S, Q) with P vs D6-O, or STOP for D7-O | Correctness oracle fails |
| P4C | P4A outcome recorded (fallback, or P4B accepted) | The macOS roster is exactly the configuration's, through one policy (surfaces + dispatch + stale settings); Windows roster unchanged; focused tests PASS | A Windows-visible change; a removed asset, identity or pin; a hidden-but-dispatchable engine |
| P5 | **Revision 2:** P4C complete; HOME-PC items PENDING until available (Q3=A). Originally: P4 closed; every engine PROVEN or with its D7 | Owner macOS acceptance; complete acceptance map PASS; D6-final; Windows focused PASS; D16 and D18 recorded | Unmapped or failing acceptance scenario; listening rejection |
| P6 | P5 accepted; D16; D18 | P6a release source final (version, MacOS declarations, packaging) + rehearsal; Codex closed; owner acceptance; **final executable SHA frozen**; no gate run | Rehearsal audit fails; Gatekeeper path unusable; a finding re-opens an engine phase |
| P7 | P6d; clean checkouts of the final SHA on both machines; REAL CLEAN machine ready | macOS and Windows full gates PASS on the **same** SHA; exact archives built afterwards with no source change and audited; REAL CLEAN `fresh-macos` PASS on the exact archive; approved merge/tag/publish; anonymous re-download verified | Gate FAIL (no rerun without owner); any provenance mismatch; any needed change inside the tagged tree (→ §17) |

---

## Appendix A — Source links (accessed 2026-11-14)

Labels as used in the text. Third-party reports are evidence of plausibility, not proof on this Mac.

**Platform: Python, Tk, Gatekeeper, FFmpeg, PyTorch, POSIX**
- python-build-standalone release 20261009 (asset digests): https://github.com/astral-sh/python-build-standalone/releases/tag/20261009 ; Tk version at the tag: https://github.com/astral-sh/python-build-standalone/blob/20261009/pythonbuild/downloads.json , https://github.com/astral-sh/python-build-standalone/blob/20261009/cpython-unix/build-tk.sh ; Tcl 9 threading fix: https://github.com/astral-sh/python-build-standalone/issues/1320 ; non-framework build: https://github.com/astral-sh/python-build-standalone/issues/274
- python.org: https://www.python.org/downloads/release/python-31210/ , https://www.python.org/downloads/release/python-31216/ , https://docs.python.org/3.13/using/mac.html , https://github.com/python/cpython/blob/v3.12.10/Mac/BuildScript/build-installer.py ; Tk 9 in CPython: https://github.com/python/cpython/issues/124111
- Homebrew formulae API: https://formulae.brew.sh/api/formula/python-tk@3.12.json , https://formulae.brew.sh/api/formula/tcl-tk.json , https://formulae.brew.sh/api/formula/ffmpeg.json
- Tk 9: https://www.tcl-lang.org/software/tcltk/9.0.html , TIP 474 https://core.tcl-lang.org/tips/doc/trunk/tip/474.md , TIP 684 https://core.tcl-lang.org/tips/doc/trunk/tip/684.md , `tk::mac` hooks https://www.tcl-lang.org/man/tcl9.0/TkCmd/tk_mac.html , file dialogs https://www.tcl-lang.org/man/tcl9.0/TkCmd/getOpenFile.html , AppKit main-thread ticket https://core.tcl-lang.org/tk/info/bec431fc689e , tkinter threading https://docs.python.org/3/library/tkinter.html
- Gatekeeper/quarantine: https://developer.apple.com/news/?id=saqachfa , https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac , https://support.apple.com/en-us/102445 , https://eclecticlight.co/2022/09/09/app-first-run-quarantine-and-translocation/ , https://eclecticlight.co/2025/12/08/who-decides-to-quarantine-files/ , https://eclecticlight.co/2024/08/10/gatekeeper-and-notarization-in-sequoia/ , `ditto(1)` https://keith.github.io/xcode-man-pages/ditto.1.html , arm64 signing https://developer.apple.com/documentation/macos-release-notes/macos-big-sur-11_0_1-universal-apps-release-notes
- FFmpeg builds: https://ffmpeg.martin-riedl.de/ (release history https://ffmpeg.martin-riedl.de/info/history/macos/arm64/release ; 9.0.1 arm64 detail https://ffmpeg.martin-riedl.de/info/detail/macos/arm64/1787073674_9.0.1 ; its codec list https://ffmpeg.martin-riedl.de/download/macos/arm64/1787073674_9.0.1/codecs.txt ; accessed 2026-11-15, pages only, no binary downloaded) , https://www.osxexperts.net/ , https://evermeet.cx/ffmpeg/
- PyTorch: https://pypi.org/pypi/torch/json , MPS notes https://docs.pytorch.org/docs/2.15/notes/mps.html , MPS env vars https://docs.pytorch.org/docs/2.15/mps_environment_variables.html , `torch.mps` https://docs.pytorch.org/docs/2.15/mps.html , bf16 on MPS https://github.com/pytorch/pytorch/pull/119641 , MPS multinomial https://github.com/pytorch/pytorch/issues/192577 , macOS 27 MPSGraph https://github.com/pytorch/pytorch/issues/187280 , MPS in sandboxes https://github.com/pytorch/pytorch/issues/177819
- POSIX: `kqueue(2)` https://keith.github.io/xcode-man-pages/kqueue.2.html ; `setpgid(2)`; Python `subprocess` (`process_group`, `pass_fds`, `start_new_session`) https://docs.python.org/3.12/library/subprocess.html , `os`/`fcntl` docs (3.12) ; non-inheritable descriptors PEP 446 https://peps.python.org/pep-0446/ ; bsdtar extraction safety (`-P`) `bsdtar(1)`

**Engine A — Edge TTS:** https://pypi.org/pypi/edge-tts/json ; https://github.com/rany2/edge-tts/blob/7.3.1/src/edge_tts/communicate.py ; issues #490, #505, #507, #510, #512, #473, #451 and PR #493 at https://github.com/rany2/edge-tts

**Engine B — Kokoro:** https://pypi.org/pypi/kokoro/json , https://pypi.org/pypi/misaki/json ; https://github.com/hexgrad/kokoro/blob/1c7bdd971d2e32981f0f2b92d1fe5b0051e21457/kokoro/pipeline.py ; MPS PR https://github.com/hexgrad/kokoro/pull/164 ; macOS 27 report https://github.com/hexgrad/kokoro/issues/152 ; M4 Pro CPU figure https://huggingface.co/FluidInference/kokoro-82m-coreml ; MPS fallback op https://github.com/remsky/Kokoro-FastAPI/pull/233 ; MPS allocator growth https://github.com/remsky/Kokoro-FastAPI/pull/547 ; eSpeak path limit https://github.com/thewh1teagle/espeakng-loader/issues/10 ; misaki runtime spaCy download https://github.com/hexgrad/misaki/blob/e820629b96334db28227df37f280e4836d46fadb/misaki/en.py

**Engine C — Chatterbox:** https://pypi.org/pypi/chatterbox-tts/json ; source at https://github.com/resemble-ai/chatterbox/tree/59bc590b3cad826e5d5987745bf6844627a21ad5 (`tts_turbo.py`, `example_for_mac.py`) ; issues/PRs #499, #509, #554, #577, #218, #147 at https://github.com/resemble-ai/chatterbox ; model tree https://huggingface.co/ResembleAI/chatterbox-turbo/tree/main ; torchaudio 2.6 install notes https://docs.pytorch.org/audio/2.6.0/installation.html

**Engine D — Qwen3-TTS:** https://pypi.org/pypi/qwen-tts/json ; source https://github.com/QwenLM/Qwen3-TTS/tree/6cafe5582c ; issues #41, #69, #242, #355, #356, #386 and PRs #109, #124, #345 at https://github.com/QwenLM/Qwen3-TTS ; third-party M4 CPU/MPS comparison https://github.com/on22s/alexandria-audiobook2/issues/1650 and PR /pull/1666 ; pysox import behaviour https://github.com/marl/pysox/blob/v1.5.0/sox/__init__.py

**Engine E — OmniVoice:** source at the pinned commit https://github.com/k2-fsa/OmniVoice/tree/5ba967c4d5b0f08244ae856b033eea583d1e4517 (`README.md` Apple Silicon section, `pyproject.toml`, `uv.lock`, `omnivoice/models/omnivoice.py` L359-366 MPS tokenizer pin, `omnivoice/utils/common.py` device fallback) ; issues #8, #157, #172, #199, #279 at https://github.com/k2-fsa/OmniVoice ; transformers Higgs Audio v2 tokenizer https://github.com/huggingface/transformers/blob/v5.3.0/src/transformers/models/higgs_audio_v2_tokenizer/modeling_higgs_audio_v2_tokenizer.py ; torch 2.8 MPS conv limit https://github.com/pytorch/pytorch/blob/v2.8.0/aten/src/ATen/native/mps/operations/Convolution.mm

**Repository evidence (local, read-only):** wheel matrix script and JSON plus the private inventory in the ignored `files/dev-work/macos-compat-p0/`.

## Appendix B — Gap index (MAC-nnn)

| ID | Gap | Where | Phase |
|---|---|---|---|
| MAC-001 | `.command` scavenges PATH Pythons (can reach Apple 3.9/Tk 8.5) and installs Homebrew via an unpinned remote script | `Setup_and_Run-audiobook-creation-tool.command` | P1A |
| MAC-002 | Executable bit lost in this ZIP-transferred checkout (index 100755, disk 0666) | working tree | P1A (owner-approved disk-only chmod; §3.1) |
| MAC-003 | Gatekeeper/quarantine first-run UX for a downloaded ZIP | launcher, README | P1A text; P6a rehearsal; P7c REAL CLEAN on the exact archive |
| MAC-004 | `bootstrap.py` macOS Python acquisition is Homebrew-only; `APP_PYTHON` is Windows-only | `bootstrap.py` | P1A |
| MAC-005 | The dependency lock applies only to `win32`; macOS installs unhashed `==` pins | `base_packages.lock_applies` | P1A |
| MAC-006 | macOS FFmpeg: Homebrew-only, no pinned source; continuous route qualified only for Gyan Windows hashes; `aac_at` needed for xHE-AAC | `ffmpeg_portable.py`, `ffmpeg_health.py`, `m4b_continuous.py` | P1A/P1B |
| MAC-007 | Tk 9.0.4 (every no-admin macOS Python, incl. PBS) vs Tk 8.6.15 (Windows) | runtime choice (D1) | P1A (proof), P1B (port) |
| MAC-008 | Cmd+Q (`::tk::mac::Quit`) unhandled | `launcher.py` | P1B |
| MAC-009 | No parent-death containment; `stop_media_children` Windows-only | `subprocess_utils.py`, workers | P1A (setup children), P1B (GUI, FFmpeg, optional setup), P2/P3A (local-engine worker), P3B/P4B (workers); §11.2.2 |
| MAC-010 | Cross-copy engine mutex is a no-op off Windows | `qwen3_runtime.MachineGuard`, OmniVoice | P3B/P4B |
| MAC-011 | `memory_info()` is `None` on macOS; "kept for Windows" wording | `tts/worker_limits.py` | P1B |
| MAC-012 | Soft open-file limit 256 for Finder/Terminal-launched apps | `launcher.py` | P1B |
| MAC-013 | Qwen3 installer authority requires Windows directory pinning (fails closed) | `artifact_store.py`, `qwen3_packages.py`, `qwen3_engine_authority.py` | P3B |
| MAC-014 | v3 supervisor/exchange qualification fakes require Windows Job Objects (test-only) | `optional_setup_supervisor_v3.py`, `optional_setup_exchange_v3.py` | P1B (classify as N/A or port) |
| MAC-015 | Case-insensitivity assumed only on `nt` | `venv_layout.py`, `venv_integrity.py`, `maintenance.py` | P1A |
| MAC-016 | Other processes' leftover work areas reclaimed only on Windows | `shared/work_area.py` | P1B (D11b) |
| MAC-017 | `os.link` no-clobber fails on exFAT/FAT/some SMB | `tts/publication.py` | P1B |
| MAC-018 | MP3 roll-back cannot take back on macOS (documented degradation) | `mp3/mp3_plan.py` | P1B (accept/record) |
| MAC-019 | darwin-only `-write_xing 0` MP3 flag (cross-platform byte difference) | `tts/disk_assembly.py` | P2 (re-verify) |
| MAC-020 | Hard-coded Segoe UI/Consolas fonts | `optional_setup_panel.py`, `appearance.py`, `long_paths.py` | P1B |
| MAC-021 | Qwen3/OmniVoice `platform_supported()` win32-only | runtimes | P3B/P4B (after proof) |
| MAC-022 | Kokoro device: CUDA else CPU (keep CPU on Mac) | `kokoro_synth.py` | P2 |
| MAC-023 | Chatterbox `select_device()` picks MPS on Mac | `chatterbox_synth.py` | P3A |
| MAC-024 | Qwen3 worker: cuda/cpu only, bf16 default dtype | `qwen3_worker.py` | P3B |
| MAC-025 | OmniVoice worker refuses non-CUDA; `torch.cuda.*` calls | `omnivoice_worker.py`, `omnivoice_synth.py`, `omnivoice_setup.py` | P4B |
| MAC-026 | Qwen3/OmniVoice locks are `win_amd64` + cu128 | manifests | P3B/P4B |
| MAC-027 | Gate has no darwin skip policy; Windows-only acceptance adapters | `verification.json`, `verify.py` | P1B (with MAC-045) |
| MAC-028 | Cleanup coordinator may fall back to PATH `python3` (Apple's) | `cleanup_state.interpreter_candidates` | P1A |
| MAC-029 | Windows-origin `runtime-data` (settings with a Windows path, consents, sessions) must be foreign-safe | settings, optional setup, receipts | P1A |
| MAC-030 | CRLF working tree from the ZIP | checkout | Every phase: left as is, no broad cleanup (§3.1); clean LF worktree for the gate and archives (D4) |
| MAC-031 | App Nap / idle sleep during long jobs | app | P5 (D11d) |
| MAC-032 | Tk/AppKit main-thread rule | all panels | P1B |
| MAC-033 | `RELEASE_OS_NAMES` Windows-only; README macOS status | `release.py`, README | P6a (before review and the gates; never after) |
| MAC-034 | Local agent guidance names stale or absent paths: `scripts/Universal/`, `scripts/verify.py`, `CHANGELOG.md`/`DECISIONS.md`/`handoff.md` (wrong case), the `files/dev/qwen_worker.py` delegation, the v0.5.0 commit rule; `AI-WORKSPACE.md` names an absent `AGENTS.md` | `.claude/CLAUDE.md` (local, gitignored) | Owner reconciliation (§3.1); no phase edits it |
| MAC-035 | eSpeak NG data path on macOS (`espeak_data.py` symlink/short-root logic) | `shared/espeak_data.py` | P2 |
| MAC-036 | No `timeout` utility; bash 3.2 for stage 0 | stage 0 | P1A |
| MAC-037 | `<Control-a>` without `<Command-a>` in some text boxes | `shared/job_ui.py` | P1B |
| MAC-038 | NFD-named inputs and outputs need fixtures | import/output tests | P1B |
| MAC-039 | Terminal auto-close via `osascript` (possible Automation prompt) | `shared/close_terminal.py` | P1A manual |
| MAC-040 | Tk 9 trackpad `<TouchpadScroll>` missing at three custom scroll sites; `qwen3_clone_setup_ui` wheel handler never scrolls with small macOS deltas | `ui_theme.py`, `cover_resizer.py`, `qwen3_clone_setup_ui.py` | P1B |
| MAC-041 | The launcher's Gatekeeper help says "right-click → Open", which macOS 15+ no longer honours | `.command`, README | P1A |
| MAC-042 | Possible menu-bar name "Python", Dock icon, Retina sharpness and front-most focus with a non-framework PBS interpreter | GUI launch | P1A measure, P1B fix if needed |
| MAC-043 | Kokoro/Chatterbox inference runs in the GUI process and checks Cancel only between chunks; a chunk in flight cannot be preempted (breaks the immediate-Cancel rule on a Mac CPU) | `kokoro_synth.py`, `chatterbox_synth.py`; new `local_engine_host.py`/`local_engine_worker.py` | P2 (Kokoro, worker), P3A (Chatterbox); §11.2.1 |
| MAC-044 | Third-party children (FFmpeg, ffprobe, pip and its build backends) and the setup process's children have no POSIX containment after a crash or SIGKILL; `atexit` cannot help | `subprocess_utils.py`, `bootstrap.py`; new `child_ownership.py`/`child_guardian.py` | P1A (setup), P1B (GUI); §11.2.2 |
| MAC-045 | The 55 acceptance journeys exist only through the Windows native-input adapter; macOS has no functional counterparts | `verification.json` (`acceptance`), new `adapters/macos/` | P1B (map, five tools), P2–P5 (TTS journeys, completion); §14.3 |
| MAC-046 | Under `core.filemode=false` a newly added executable is recorded as `100644` | Git index (new `.sh`/`.command` files) | Every phase that adds one (`git add --chmod=+x`; §3.1) |
