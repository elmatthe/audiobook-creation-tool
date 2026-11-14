# Audiobook Creation Tool — Apple Silicon macOS Compatibility and Native Verification

**Master implementation plan | Phase 0 deliverable (research, architecture and roadmap only) | NOT an authorization to implement**
**Planning date:** 2026-11-14 (Claude Code, Opus 5.5, xHigh reasoning; Phase 0 session on the owner's Apple Silicon MacBook)
**Repository:** https://github.com/elmatthe/audiobook-creation-tool
**Working branch:** `feature/0.8.0-macos-compatibility`, created in Phase 0 at `9554bc8461ae00c4b7308f74d989fc0c8cfb9c90` (= `master` = `origin/master`)
**Released baseline:** Windows v0.8.0, tag `v0.8.0` (tag object `0a3653e`) → release-source commit `d1701e987f106ce00f557f267a6761c5370f5968`
**Integration target:** `master` (only on explicit owner approval, never in Phase 0)
**Last published macOS archive:** `AudiobookTool-MacOS-v0.6.6.zip` (GitHub release v0.6.6, 2026-09-30). No macOS asset exists for v0.7.x or v0.8.0.
**Intended owner outcome:** download/extract the app on an Apple Silicon Mac, double-click `Setup_and_Run-audiobook-creation-tool.command`, answer simple prompts, reach the same six-tool app, and create the same audiobooks with every voice that can be **proven** on the Mac, with no regression to the released Windows behaviour.

> **Status vocabulary used throughout.** **PROVEN** = demonstrated by this plan's own evidence on this Mac (Phase 0 proves only read-only facts: interpreter probes, hashes, PyPI metadata). **SUPPORTED UPSTREAM** = an official upstream source documents or contains the code path; nothing run here. **PLAUSIBLE BUT UNVERIFIED** = no blocker found, but no trustworthy run on comparable hardware/software. **REPORTED** = a third-party report that has not been checked here (always paired with another status). **BLOCKED** = a concrete defect or missing capability prevents it today. **UNSUPPORTED** = deliberately not offered. *Nothing about any TTS engine is PROVEN on this Mac in Phase 0: no environment was created, no model was downloaded, nothing was synthesized.*

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

   Each needs a native POSIX/macOS design, not a "skip on mac" (§11).
3. **GUI.** The aqua shell exists and has 39+ macOS-only layout tests that have not run on a Mac since v0.6.6. Gaps:
   - `::tk::mac::Quit` (Cmd+Q) is unhandled;
   - some fonts are hard-coded to Windows families;
   - Tk versions diverge. **Every no-admin Python route on macOS ships Tk 9.** Windows builds use Tk 8.6.15; python-build-standalone 20261009 builds macOS with Aqua Tk 9.0.4, and Homebrew with Tk 9.0.x. So a small, bounded **Tk 9 port** of ACT's GUI is required (§10). ACT's exposure is modest: no legacy `trace()` calls and no `~` paths handed to Tk. Three custom scroll handlers need `<TouchpadScroll>`.
4. **Engines.** Summary only; the evidence is in §6 and §12.
   - Edge: platform-neutral network engine.
   - Kokoro: CPU is already its only non-CUDA path; reliability first.
   - Chatterbox Turbo: CPU by default. ACT's `select_device()` would pick MPS today, and MPS has open sampling and memory risks.
   - Qwen3-TTS: CPU float32 is the only Apple Silicon configuration with a controlled, reported comparison of correct speech. MPS has been reported badly wrong on torch 2.7. It is gated as Windows-only today.
   - OmniVoice 0.2.1: upstream documents MPS, and the code path is device-neutral. ACT's worker hard-refuses non-CUDA devices. There is conflicting MPS fp16 evidence on M4 hardware. CPU fp32 is plausible but slow.

   Qwen3 and OmniVoice therefore get **owner-gated feasibility experiments** before integration.
5. **Verification.** The canonical gate's skip policy exists only for `win32`, and its acceptance adapters are Windows-only. On macOS today every skip would be recorded as "NOT APPLICABLE, not judged". That is exactly how Windows-only skips could masquerade as a macOS pass. A `darwin` policy and macOS-native counterparts are required before any macOS result is trusted (§14, §17).

**Final objectives (exit of the whole programme, P7):**
- O1. A fresh Apple Silicon Mac with no Homebrew and no compatible Python reaches a healthy app through the double-click launcher. It uses an app-owned, hash-verified arm64 Python and FFmpeg, gets explicit consent for every download, and needs no admin password.
- O2. All six tools pass native macOS functional acceptance with real media, including Cancel, Pause, recovery and publication invariants.
- O3. Each of the five engine families is either **PROVEN on this Mac** for its whole voice roster, or explicitly shown as unavailable with an accurate reason and an owner-recorded decision. No voice is silently removed, substituted or faked.
- O4. The 34 stable `(backend, voice_id)` identities, the 18 clone-reference WAVs, their transcripts, the 28 preview WAVs and the shared speech-preparation pipeline are byte-for-byte unchanged.
- O5. Windows v0.8.0 behaviour is preserved and re-verified on HOME-PC on the final candidate (owner decision D8).
- O6. One independent Codex review and its remediation, owner acceptance, and then **one** canonical native macOS full gate on the frozen candidate. A failed gate is investigated, never rerun into a pass.
- O7. A release whose provenance is truthful: no moved tag, and no macOS binary attributed to the Windows v0.8.0 commit (§18).

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
| Subprocess control | `shared/subprocess_utils.py` (`run_supervised` terminate → kill through the handle, which works on POSIX), `tts/qwen3_process.py` (`start_new_session` + `killpg` on POSIX) | **Reuse**. Add a parent-death lifeline and a POSIX `stop_media_children` (MAC-009) |
| Output and publication | `shared/output_paths.py` (NFC, collisions; already treats darwin as case-insensitive), `tts/publication.py` (staging + `fsync` + `os.link` no-clobber on POSIX, `os.replace` for overwrite) | **Reuse**. Consider `renamex_np(RENAME_EXCL)` for non-APFS volumes (MAC-017) |
| Jobs | `shared/job_control.py`, `shared/job_ui.py`, `shared/cancellation.py` | **Reuse unchanged** (thread-based; no platform branches) |
| Optional engines | `tts/optional_setup*.py`, `shared/optional_setup_protocol.py`/`_panel.py`, `tts/voice_install.py`, per-engine `platform_supported()` gates | **Reuse** the consent, progress, Install & Continue and readiness flows. Change *gates* per engine only after proof |
| Speech preparation | `tts/speech/*` (`pipeline.prepare`, 16 classes, `modes.json`, glossary) | **Reuse unchanged**; it is pure Python (§13) |
| Engines | `tts/kokoro_synth.py`, `tts/chatterbox_synth.py` (both in-process); `qwen3_*`, `omnivoice_*` (isolated worker processes) | Narrow device/dtype adapters (§12) |
| Packaging | `shared/release.py` already builds `AudiobookTool-MacOS-vX.Y.Z.zip` with a forced 0755 `.command` (`_write_executable`). The ordinary build is gated by `RELEASE_OS_NAMES = ("Windows",)` | **Reuse**. Enable MacOS only at P7 with owner approval |
| Verification | `files/dev-work/verification-gate/` (`verify.py`, `verification.json`, `coverage.json`, `helpers/winproc.py` with a POSIX process-group branch), `files/dev-work/feature-map/` | **Reuse** the core. Add a `darwin` skip policy, a darwin preflight and macOS acceptance coverage. Keep Windows adapters untouched |

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
| Cancel / Pause | In-process Kokoro/Chatterbox: Cancel between chunks (latency = one chunk on CPU, to be measured). Workers: flag → kill the process group. Pause at the file boundary | `run_supervised` SIGTERM → SIGKILL (POSIX OK) | Same | Same | Same | n/a (quick operations) |
| Window close / Cmd+Q / crash | `WM_DELETE_WINDOW` handled. **Cmd+Q unhandled** (MAC-008). Orphaned workers after a crash (MAC-009) | `stop_media_children` is Windows-only, so FFmpeg can outlive the app (MAC-009) | Same | Same | Same | n/a |
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
| **B. Kokoro-82M** (kokoro 0.9.4, misaki 0.9.4, espeakng-loader 0.2.4, spaCy 3.8.16 + `en_core_web_sm` 3.8.0, torch 2.6.0; 9 voices) | All wheels exist. `espeakng_loader-0.2.4-py3-none-macosx_11_0_arm64.whl` bundles `libespeak-ng.dylib` 1.52 and its data. **eSpeak calls `exit(1)` if its data path is ≥ 160 characters** (espeakng-loader #10). ACT's `espeak_data.py` already makes a short symlink root on POSIX; this checkout's path would be 155 characters (MAC-035). misaki would pip-install `en_core_web_sm` at runtime if missing, which ACT prevents with its pinned wheel | **REPORTED** on M4 Pro CPU: ~17× faster than real time, 4.85 GB peak (model card; versions not stated). **REPORTED** kokoro 0.9.4 on macOS 27 with **torch 2.13** (kokoro#152). torch **2.6.0 on macOS 27: no report** | Not used by ACT (`cuda` else `cpu`). Upstream MPS support (PR #164) is unreleased. Needs `PYTORCH_ENABLE_MPS_FALLBACK` for `aten::angle`. **REPORTED** crashes on long strings and allocator growth (1.9 → 8.9 GB) without `empty_cache` | `kokoro_synth._local_model`: `cuda` else `cpu` (fine) | **CPU fp32** (owner priority: reliability + pronunciation). MPS not offered | **PLAUSIBLE BUT UNVERIFIED (strong).** The only open question is torch 2.6.0 on macOS 27 (P1A import proof, P2 synthesis) |
| **C. Chatterbox Turbo** (chatterbox-tts 0.1.7, torch 2.6.0, transformers 5.2.0, numpy 1.26.4, resemble-perth 1.0.1; 6 cloned voices) | All wheels exist (incl. `spacy_pkuseg-1.0.1-…-macosx_11_0_arm64`, `s3tokenizer`/`resemble_perth` pure). Turbo needs no libsox/FFmpeg from torchaudio (only `Resample` + `kaldi.fbank`; audio read by librosa) | **SUPPORTED UPSTREAM** (device-agnostic code: safetensors load to CPU, then `.to(device)`; no CUDA kernels, bf16, flash-attn or `torch.compile`). **PLAUSIBLE BUT UNVERIFIED** here. Upstream **does not claim** Turbo on Mac (README/CI: Linux/CUDA). Speed unknown: the original model reported ~0.34× real time on an M4 CPU; Turbo (350M params, 2-step decoder) should be faster [inference]. ~3.0 GB fp32 loaded | **PLAUSIBLE BUT UNVERIFIED, high risk:** torch 2.6 MPS `multinomial` can pick zero-probability tokens (pytorch#192577; silent); allocator growth on 24 GB machines (chatterbox#577: multilingual model reached 24.9 GB driver memory); macOS 27 MPSGraph argmax defect (pytorch#187280). The float64 crash (#499) probably avoided by numpy 1.26.4 [inference] | `select_device()` = cuda → **mps** → cpu, so **ACT would choose MPS on this Mac today** (MAC-023) | **CPU fp32 default on darwin**; MPS only as an owner opt-in after the correctness oracle | **PLAUSIBLE BUT UNVERIFIED** (CPU) |
| **D1. Qwen3 CustomVoice** (qwen-tts 0.1.1, transformers 4.57.3, accelerate 1.12.0, torch 2.10.0; Aiden, Ryan) | All 89 pins have a Mac artefact (onnxruntime 1.31.0 `macosx_14_0_arm64`; `sox` = ACT's pure supply wheel; the SoX *binary* is not needed: pysox only logs "SoX could not be found!"). onnxruntime/sox are imported at module scope but used only by the unreleased 25 Hz tokenizer. **ACT's installer authority fails closed off Windows** (MAC-013) | **REPORTED** working on a base M4 (third-party audiobook project; torch 2.7, qwen-tts 0.1.1): 0.38 audio-s per wall-s (~2.6× slower than real time), 25/30 lines exact by ASR, 11.3 GB RSS. Second report on macOS 26 CPU fp32 | MPS **fp32 REPORTED badly wrong** on torch 2.7 (6/30 exact, mean WER 1.15, 16.5 GB driver allocation). MPS **bf16**: anecdotal "works", no quality data. **fp16: overflow → inf/NaN** (#355) | `choose_device`: cuda:0 or cpu; default dtype **bf16**; `platform_supported()` = win32 only; `MachineGuard` no-op off Windows | **CPU fp32, sdpa, one chunk at a time.** CPU bf16 / MPS bf16 only if they match CPU fp32 on WER and listening. Never fp16 | **PLAUSIBLE BUT UNVERIFIED (+ REPORTED on M4 CPU); installer BLOCKED (ACT-side).** Upstream has no official Mac path; Mac PRs #124/#345 unmerged; last commit 2026-03 |
| **D2. Qwen3 Voice Clone** (Base model; 6 cloned voices from the 18-reference set) | Same as D1 | The clone path is pure PyTorch (Mimi-based 12 Hz encoder, ECAPA-style speaker encoder, mel STFT on a CPU tensor, librosa/soxr resample). **PLAUSIBLE BUT UNVERIFIED** (no direct Apple CPU fp32 report; CPU **fp16** ran >20 min without finishing, #69) | Anecdotal (bf16 #69; MPS fp32 on 0.6B Base; PR #345 exits 0, no quality data) | As D1 | As D1, with the same reference WAV and transcript bytes | **PLAUSIBLE BUT UNVERIFIED; installer BLOCKED (ACT-side)** |
| **E. OmniVoice 0.2.1** (omnivoice 0.2.1 @ `5ba967c4`, transformers 5.3.0, torch 2.8.0; model `k2-fsa/OmniVoice` @ `c5fdb5cc`; 6 cloned voices) | Pure wheel, no native extensions, no CUDA-only dependencies (triton only on linux x86_64). **Upstream's own `uv.lock` resolves darwin to PyPI `torch==2.8.0`** ("CUDA doesn't exist for Mac"). ~86 Mac wheels, ~247 MB (vs 3.66 GB Windows) [summed, not resolved]. Offline load is platform-neutral (local dir with `audio_tokenizer/`, `ref_text` supplied → no Hub, no Whisper) | **SUPPORTED UPSTREAM** code path (`get_best_device` falls back to CPU; no CUDA calls in inference). **REPORTED** correct speech on Apple CPU (#8 on 0.1.1, #172), RTF ≈ 3 (slow). ~612M-param backbone (2.45 GB fp32) + ~201M-param tokenizer | **SUPPORTED UPSTREAM** (README documents Apple Silicon and `device_map="mps"`, fp16; code pins the audio tokenizer to CPU on MPS). **Conflicting REPORTS on M4:** #172 (Mac mini M4, torch 2.8.0) garbled audio + NaN with fp16+SDPA, where the maintainer's advice was fp32; #279 (M4 Max, 0.2.1, fp16) works, RTF ≈ 0.4. Memory growth across `generate()` calls (#199) is CUDA-reported, untested on MPS | Worker refuses `device != "cuda"`; `device_map="cuda:0"`, fp16; `torch.cuda.synchronize`/memory/seed calls; `platform_supported()` = win32; NVIDIA-only GPU probe and setup proof | Decided by the **P4A experiment**: MPS fp32 (likely candidate), MPS fp16 (only if oracle-clean), CPU fp32 (correct but ~3× slower than real time) | **PLAUSIBLE BUT UNVERIFIED; ACT-side BLOCKED** (CUDA-only worker). No configuration is proven on Apple Silicon; nothing upstream blocks it |

**Not acceptable as substitutes:** MLX ports exist for Kokoro-adjacent stacks, Qwen3-TTS (mlx-audio) and OmniVoice (mlx-audio, OmniVoice-MLX). They load *converted* weights with different hashes and numerics. Using one would change the engine's identity, so they are noted only as future, owner-decided alternatives and never as silent replacements.

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
| FFmpeg arm64 sources | Homebrew ffmpeg now 9.0.2 (GPL); **Martin Riedl**: arm64 release builds incl. 9.0.2 with per-ZIP `.sha256`, signed ZIPs; osxexperts: arm64 ZIPs + SHA-256, not notarized, mismatched source link; evermeet: Intel only | VERIFIED (pages) | formulae.brew.sh; ffmpeg.martin-riedl.de; osxexperts.net; evermeet.cx |
| PyTorch macOS wheels | torch 2.6.0 / 2.8.0 / 2.10.0 (+ `-2` rebuild) `macosx_11_0_arm64` for cp312; newest 2.15.0 (`macosx_14_0`, py ≥ 3.11). MPS needs macOS 14+ from 2.9 and 15+ from 2.15; float64/complex128 unsupported on MPS (fallback does not apply); bf16 needs macOS 14+; 2.15 raises on MPS OOM instead of returning wrong values | VERIFIED | pypi.org/pypi/torch/json; PyTorch 2.9/2.15 release notes; docs.pytorch.org/docs/2.15/notes/mps.html |
| MPS memory controls | `PYTORCH_MPS_HIGH_WATERMARK_RATIO` (default 1.7), `PYTORCH_MPS_LOW_WATERMARK_RATIO` (1.4 on unified memory); `torch.mps.{synchronize, empty_cache, current_allocated_memory, driver_allocated_memory, recommended_max_memory, manual_seed}`; **no peak-memory API** | VERIFIED | docs.pytorch.org/docs/2.15/mps_environment_variables.html, /mps.html |
| Process control | `start_new_session` → `setsid`; `os.killpg`; no `PR_SET_PDEATHSIG` on macOS; kqueue `EVFILT_PROC`/`NOTE_EXIT` can watch the parent; `flock` locks are per open file and freed on close/death; `rename(2)` atomic on one volume; `fsync` ≠ `F_FULLFSYNC` | VERIFIED | Python docs; `kqueue(2)`, `flock(2)`, `fcntl(2)`, `rename(2)`, `fsync(2)` |

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

1. If `files/runtime-data/python/bin/python3.12` exists, run it under a **bounded probe**. macOS has no `timeout`, so start it in the background and kill it after N seconds with a bash loop. The probe is `-I -c "import sys, ssl, venv, ensurepip, tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy(); …"`: a real Tk init, not just `Tcl()` (the Windows audit lesson ACT67-AUD-006). It must also assert arm64 (`platform.machine()=='arm64'`) and version 3.12. On success, write the path and exit 0.
2. Otherwise **explain and ask**: what is downloaded (about 25 MB, from GitHub/astral-sh), where it goes, and that no admin is needed. Nothing downloads without Yes. Exit codes match Windows: 0 = proven, 2 = declined, 3 = failed.
3. Download into `files/temp/bootstrap/` with `curl --fail --location --proto =https`. Verify the **exact size and SHA-256** with `shasum -a 256` (built-in). On mismatch, delete the file and exit 3. Never fall back to an unverified source.
4. Extract with `/usr/bin/tar` into a staging sibling. Verify `bin/python3.12` exists and is arm64 (`lipo -archs` or the probe). Move it into place with one `mv` (atomic same-volume rename). Prove it with the probe and delete the archive and staging folder.
5. Hand off to `bootstrap.py`, which stays the authority for `.venv`, packages, FFmpeg, models and launch.

Qualification-only switches mirror `-AssumeYes/-AssumeNo/-DownloadOnly/-ArchivePath`. They exist so the stage can be tested offline against a fixture archive, and the launcher passes none of them.

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
- **Transactions:** reuse the staging-then-rename pattern. Interrupted downloads resume or restart in staging and never in place. A partially installed engine has no receipt, so it reads as NOT READY and is never deleted silently.
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
- **Cmd+Q (MAC-008).** Register `root.createcommand("::tk::mac::Quit", app._on_close)` and route it through the same close path as the red close button. That path saves `last_tool`, lets panels cancel their runs, finishes Tk objects on the main thread and runs `stop_media_children`. Also consider `::tk::mac::ShowPreferences` → Preferences & Data (the existing `<Command-comma>` accelerator).
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

  - **Recommended UX (D10):** the README gives step-by-step "Open Anyway" guidance, with a screenshot taken in P5. As an *optional, explained, opt-in* alternative, it shows a one-line Terminal command that removes quarantine from **the launcher file only** (`xattr -d com.apple.quarantine Setup_and_Run-audiobook-creation-tool.command`), stating plainly that it skips Apple's malware check for that file.
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
  - **Recommended:** a *versioned* (never "latest") **Martin Riedl** macOS arm64 release ZIP for `ffmpeg` and `ffprobe` (ffmpeg.martin-riedl.de). Riedl publishes a `.sha256` per ZIP and signs the macOS builds. Prefer 9.0.1 to match Windows' Gyan 9.0.1 if it is still offered as a versioned release; otherwise 9.0.2, which the owner must accept.
  - **Pin:** ACT pins its *own* recorded size + SHA-256 in `shared/ffmpeg_portable.py` (macOS block). Like the Gyan pin, the digest and not the URL is the authority.
  - **Acquisition:** with consent, curl (no quarantine) into `files/temp/bootstrap/`, verify, extract to `files/bin/ffmpeg/<version>/bin/`, `codesign --verify`, then the `ffmpeg_health` execution proof.
  - **Proof:** it also requires `aac_at` in `-decoders` and `libmp3lame` in `-encoders`. FFmpeg autodetects AudioToolbox on Darwin, but a static third-party build could disable autodetection, so this is **PLAUSIBLE until P1A checks it**. Without `aac_at` the build is rejected (xHE-AAC) and the next candidate is tried.
  - **Licensing:** these builds are GPL (x264/x265); Gyan "full" on Windows is GPL too. ACT does not bundle FFmpeg in its archive; it downloads it on consent, as on Windows.
  - **Alternatives:**
    - accept a proven Homebrew pair when present (today's behaviour; unpinned version);
    - osxexperts (SHA-256 but not notarized, mismatched source link): not recommended;
    - evermeet: Intel-only, unusable without Rosetta.
  - **Discovery hygiene:** check the Mach-O architecture (`lipo -archs`) *before* executing a candidate. An Intel binary in `/usr/local/bin` is rejected without being run, which avoids any Rosetta prompt.
- **Byte-identity routes.** The Converter's continuous split route is enabled only for `QUALIFIED_BUILDS` (Gyan Windows hashes). On macOS it is *correctly* refused and the existing per-chapter route is used: identical semantics, slower. Qualifying a macOS build means adding its hash pair after running the `m4b-scaling` harness on the Mac. That harness takes about 3 hours (owner decision D11c). It is not required for correctness.
- **MP3 `-write_xing 0` on darwin (MAC-019).** This historic macOS-only encode flag makes macOS MP3 bytes differ from Windows. Re-verify why it exists (v0.3.x "MP3 speed-up" era) and whether it is still needed with FFmpeg 9.0.1. Keep it unless a test proves it unnecessary, and record the outcome in Decisions. Its removal would be an owner decision, because it changes output bytes.

### 11.2 Processes, cancellation and containment (macOS semantics)

| Mechanism | Windows today | macOS design (proposed) |
|---|---|---|
| Child ownership | Job Object (kill-on-close), suspended start | `start_new_session=True` gives each worker its **own process group** (pgid = pid); already used by `qwen3_process.spawn`, pip and the GUI launch |
| Cancel a worker | flag file → `TerminateJobObject` | flag file (unchanged) → bounded grace → `os.killpg(pgid, SIGTERM)` → bounded grace → `os.killpg(pgid, SIGKILL)` → `waitpid`. Never kill by name |
| Cancel a single FFmpeg step | `run_supervised` terminate → kill via handle | Unchanged (works on POSIX) |
| **Parent death (GUI crash, force quit, Cmd+Q bypass)** | Job Object kill-on-close | **New lifeline (MAC-009):** the parent passes a pipe read-end (`pass_fds`). A daemon thread in every worker (`qwen3_worker`, `omnivoice_worker`, the optional-setup worker) blocks on it; on EOF it calls `os.killpg(0, SIGKILL)` on its own group. A `kqueue` `EVFILT_PROC`/`NOTE_EXIT` watch on the parent pid is an acceptable alternative. macOS has no `PR_SET_PDEATHSIG` |
| App-exit cleanup of media children | `stop_media_children` (Toolhelp snapshot, own children named ffmpeg/ffprobe) | POSIX twin: track every spawned media child's pid/pgid in a registry inside `subprocess_utils` and terminate those still alive at exit. No `ps` scan by name. Registered at `atexit` and in the Cmd+Q path |
| Cross-copy engine exclusion | `Global\` named mutex (CreateMutexW); off Windows `scope = "none"` (MAC-010) | `fcntl.flock` on a per-user lock file in `tempfile.gettempdir()/ACT-locks/<engine>.lock`, the same temp root ACT already uses. The kernel releases it on process death, so locks never go stale. Owner decision D13 (Windows itself documents "two copies can still run Qwen3 and OmniVoice together"; the new lock is a strict improvement) |
| Pause | Between files | Unchanged (platform-neutral) |

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
  - E-A4: Cancel during synthesis and during finalization takes effect within ~2 s, with nothing published; Pause then Cancel.
- **Expected limitation:** service-side throttling, voice removals and token changes are upstream risks. An outage is recorded as BLOCKED, not as a Mac defect.

### 12.B Kokoro-82M (P2; owner's preferred engine)

- **Needed:**
  - nothing in the synthesis path; the device stays `cuda` else `cpu` (`kokoro_synth._local_model`), i.e. CPU on the Mac;
  - verify the eSpeak NG short-root logic (`shared/espeak_data.py`) on macOS, including an app folder deep enough to push the data path past 160 characters (MAC-035), and the spaCy pinned-wheel route (`require_spacy_english`).
- **Optional (owner):** make the CPU choice explicit on darwin for readability. Kokoro MPS is **not offered**: the gain is small and the crash/allocator-growth risks are reported.
- **Experiments:**
  - **E-B1 (imports):** in one process, import torch 2.6.0, sklearn, numba, spacy, kokoro and `misaki.en`; load `en_core_web_sm`; exercise the espeak fallback on 20 out-of-dictionary words. The watch item is a duplicate OpenMP runtime abort (torch and sklearn/numba each bringing `libomp`).
  - **E-B2 (pronunciation, the accuracy proof):** run `KPipeline(model=False)` (G2P only) over `quality_corpus` texts A–C on the Mac and on Windows (HOME-PC). **The phoneme strings must be identical.** This is the strongest "same pronunciation" oracle available, because Kokoro's decoder adds unseeded noise and audio is never byte-identical even on one machine.
  - **E-B3 (CPU synthesis):** all nine voices through `synthesize_text_to_mp3`, plus one ≥30-minute chapter. Record RTF and peak memory (`/usr/bin/time -l`). Pass if RTF ≤ 0.25 (owner may adjust at D6), memory is flat, there are no errors, and the listening/WER spot check is clean.
  - **E-B4:** Cancel latency (bounded by one 3,000-character chunk; record seconds), Pause at the boundary.
- **If torch 2.6.0 fails on macOS 27** (E-B1/P1A): stop. The options are an owner decision, because torch is shared with Chatterbox, whose 0.1.7 metadata pins `torch==2.6.0` exactly:
  - (i) a darwin-only torch pin with Chatterbox gated off on macOS;
  - (ii) a newer torch on both platforms with Windows re-qualification;
  - (iii) keep investigating.

### 12.C Chatterbox Turbo (P3A)

- **Needed:**
  - `chatterbox_synth.select_device()` (L1088–1103): on darwin return **`cpu`** unless the owner has explicitly opted into MPS (a setting or env var, recorded per run). Windows order `cuda → mps → cpu` is unchanged.
  - Add the device to the conditionals cache key.
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
  - **E-C3 (soak):** one chapter (~50 chunks) on the chosen device. Pass: footprint < 16 GB, no swap growth, per-chunk time drift < 20%.
  - **E-C4:** a conditionals cache made on one device is never reused on another (identity key).

### 12.D Qwen3-TTS: CustomVoice and Voice Clone (P3B)

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
  - the out-of-memory match already covers "MPS backend out of memory".
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
  - **E-D5:** long form ≥ 1 hour: RSS per chunk (fail at > 10% growth after warm-up), Tk responsiveness, Cancel and kill of the worker group, lifeline on GUI kill.
- **Stop rule:** if CPU fp32 fails E-D3 or E-D4, the Qwen3 macOS gate stays closed (D7).

### 12.E OmniVoice 0.2.1 (P4A experiment, then P4B integration)

**P4A feasibility experiment (owner-gated; disposable; no ACT code).** It never touches the six reference WAVs (read-only, hash-checked), ACT's `.venv` or ACT's prompt cache.

1. **Preconditions:** owner consent, ≥ 5 GB free, an arm64 interpreter (the app-owned PBS Python).
2. **Environment:** a scratch venv under `files/dev-work/omnivoice-feasibility/`, built from the darwin wheel set resolved from upstream's `uv.lock` darwin markers, hash-pinned (~247 MB).
3. **Model:** the 11 files at `c5fdb5cc…` (3.27 GB), verified against ACT's existing manifest SHA-256s (platform-neutral).
4. **Guards:** `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, ACT's network audit hook, `PYTORCH_ENABLE_MPS_FALLBACK` **unset**.
5. **References:**
   - first a neutral reference: `say -o ref.aiff "<known sentence>"`, then `afconvert -f WAVE -d LEI16@24000` (built-in tools; known transcript; no licence question);
   - then each of the six owner references, read-only, with the owner-written transcripts.
6. **Configurations:** **MPS fp16**, **MPS fp32**, **CPU fp32**. Each uses ACT's `GENERATION` (32 steps…), `normalize_text=False`, fixed seeds, and ~10 sentences from one word to > 30 s (the chunked path).
7. **Measurements:**
   - NaN/Inf;
   - 50 ms RMS-envelope variation against the CPU run (the #8 failure signature was a near-constant envelope);
   - token agreement against CPU;
   - RTF;
   - `torch.mps.current_allocated_memory()`/`driver_allocated_memory()` per chunk and peak process RSS;
   - same-seed repeatability on the same device;
   - 50 back-to-back `generate()` calls (#199-style growth);
   - `model.audio_tokenizer.device == cpu` (upstream pins it there on MPS);
   - zero network attempts.
8. **Pass per configuration:**
   - all outputs finite;
   - the owner judges every sentence intelligible and the same voice in a blind A/B against CPU;
   - envelope variation within ~2× CPU's;
   - no `NotImplementedError`, OOM or network attempt;
   - < 10% memory growth over 50 calls after warm-up;
   - RTF within the owner's budget (D6).

   **Fail** on any NaN, any garbled sentence or any op error. Seeds will not reproduce Windows CUDA audio; record whether same-device repeats are bit-identical.
9. **Optional:** move the tokenizer to MPS (`model.audio_tokenizer.to("mps")`). Codes must be identical and decode differences < 1e-4 (#279 reports ~6× faster).

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
  - `MachineGuard` POSIX lock.
- **Already neutral:** the `fcntl` lock (L131–157), the network guard, the CPU prompt load, `_is_oom`, the long-path checks (they return early off Windows) and the POSIX `site_packages` branch.

**If no configuration passes:** the six OmniVoice voices stay visible but unavailable on macOS, with the measured reason (D7). Nothing is substituted. An MLX port would be a separate, owner-decided project, because its weights differ.

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
| Stage 0 and launcher | Every state in §8.2, against fixture archives (size/hash mismatch, declined consent, interrupted download, truncated archive, Tk proof failure, healthy fast path, repair exit 3, translocated location) | `files/tests/test_bootstrap_host_macos.py` (bash run under bounded subprocess) | P1A | Yes |
| GUI (automated, in-process) | Widget construction for all six tools; `event_generate` for Cmd+Q, Select-All; worker→UI thread stress; Tk version and windowing system | Tk tests on the Mac display | P1B | Yes |
| GUI (owner manual) | Light/Dark, Retina, min/max geometry, dialogs, Finder reveal, focus at launch, Dock/menu name, Terminal auto-close, Gatekeeper double-click | Checklist in Handoff | P1B, P5 | Yes (owner-signed) |
| Subprocess/cancellation | Cancel during long generation (every engine), Cancel during encode, Pause at file boundary, `kill -9` of GUI → workers gone ≤ N s (lifeline), Cmd+Q during a job, two app copies + engine lock | Focused tests + bounded real runs | P1B (FFmpeg), P2–P4 (engines) | Yes |
| Fault injection | Disk full (small `hdiutil` image), corrupted model file (flip a byte in a *copy* under scratch), failed repair (network off), interrupted publication (kill between stage and link), exFAT target, read-only target, NFD names | Repo-contained scratch under `files/dev-work/` | P1B, P2–P4, P5 | Yes |
| Engine real synthesis | Opt-in, offline, bounded: each engine's voices on short multi-chunk texts | Guarded tests keyed by env vars (precedent `ACT_OMNIVOICE_P1_REAL=1`), each with its own exact skip rule | P2–P4 | Yes, only when actually run |
| Install/repair/recovery | Fresh first run, healthy relaunch (no work), `.venv` damage → repair, engine carry-across, interrupted engine install, Windows-origin `runtime-data` | Disposable worktree copies under `files/dev-work/` | P1A, P3B, P4B, P5 | Yes |
| MP3/M4B/metadata/image functional | Real media from `files/test-files/` via existing env-var fixtures; xHE-AAC via `aac_at`; chapter/series atoms; HEIC | Existing real-media acceptance tests run on the Mac | P1B, P5 | Yes |
| Packaging/extraction | `release.py` MacOS archive into scratch → audit (members, 0755 launcher, LF, no env/models) → extract with Archive Utility *and* `ditto`, quarantined copy → first run | P5 dry run; P7 real | P5, P7 | Yes |
| Owner listening | §15 packs per engine | Owner | P2–P5 | Owner-signed |
| Independent Codex review | Changed-area review of the frozen candidate | Codex CLI, read-only | P6 | Review evidence, not a test PASS |
| Canonical full gate | `verify.py --mode full --platform macos` once, on the frozen clean-LF candidate | Native macOS | P6 | The one macOS gate PASS |
| Windows regression | Focused Windows checks on HOME-PC for every shared file touched; Windows full gate on the same final SHA (D8) | HOME-PC | P5 (focused), P6 (full, if D8) | Windows evidence only |

### 14.2 Reporting rules (no false passes)

Every result is one of: `PASS`, `FAIL`, `BLOCKED` (could not run: prerequisite missing), `NOT APPLICABLE ON MACOS` (Windows mechanism; listed with count and reason id), `UNSUPPORTED` (engine gated off with an owner decision), or `NOT RUN`. A macOS gate verdict states its non-applicable count explicitly.

**`coverage.json` work (P1B).** Each behaviour id currently satisfied only by Windows-only tests gets one of two things:
- a macOS counterpart test; or
- an owner-reviewed `not_applicable_on: darwin` entry with a reason.

The coverage-inventory check then fails on any behaviour with neither.

**Windows coverage is never weakened:** the `win32` policy and all Windows tests are unchanged, and new tests are additive.

### 14.3 Gate changes required before any macOS gate result is trusted (P1B, MAC-027)

- `verification.json`: add `skip_policy.darwin`, derived from the *actual* collected darwin skip reasons. Each gets an id, an exact pattern, a maximum count and a "why". A darwin run with an unknown skip reason **fails**; it is no longer "NOT APPLICABLE, not judged".
- `verify.py` preflight on darwin: replace the Windows error-mode/Job checks with POSIX equivalents. Prove that a child is in the gate's own process group and is reaped on stop, and that no dialog can block (no Tk window outside tests). Windows logic is unchanged.
- `acceptance`: there is no macOS native-input adapter in this programme (D9). macOS GUI journeys are owner-manual plus in-process Tk tests. `acceptance.required_scenarios` stays Windows-scoped, and a darwin full gate records the acceptance stage as `NOT APPLICABLE ON MACOS: owner-manual checklist P1B/P5`. It must be visibly separate, not PASS.
- `qualification`: `fresh_windows`, `m4b-scaling` (Windows build hashes) and `edge-low-memory` are Windows scenarios. A darwin qualification scenario `fresh-macos` (packaged archive → extracted → stage 0 → first run → repair → launch) is added in P5 only if the owner wants it automated (D9b).

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
- **Acceptance budgets** are owner-set at P5 entry (D6). The plan records numbers and does not invent pass thresholds for speed. Correctness thresholds are fixed:
  - zero non-finite outputs;
  - zero truncated or garbled sentences in the owner's listening;
  - MPS or other faster configurations have WER no worse than CPU fp32 + 1 pt absolute on texts A+B;
  - no unbounded memory growth.

---

## 16. Independent Codex review and remediation gate (P6a)

- **When:** after P5 is accepted (all implementation, focused acceptance and listening done), on a frozen candidate SHA pushed to the feature branch. Codex is an **independent verifier**: it implements nothing and does not run the full gate.
- **Scope (changed-area):** `git diff 9554bc8..<candidate>`, with priority on:
  - the stage-0 download, hash and unpack path (supply-chain trust);
  - the POSIX port of the Qwen3 installer authority (path pinning, symlink and race resistance);
  - process containment, lifeline and cancel semantics;
  - publication no-clobber and recovery;
  - platform gates (no fake-enable; Windows paths unchanged);
  - lock files (one artefact per pin, hashes, no CUDA wheel);
  - immutable-asset contracts;
  - the darwin skip policy (no Windows skip counted as PASS);
  - docs truthfulness.
- **Inputs:** this plan, the Handoff, the diff and the focused evidence. Codex runs read-only checks and may run focused tests in a scratch worktree.
- **Output:** findings `MACR-nnn` (severity, file:line, reproduction).
- **Remediation:** Claude fixes each finding with a positive and a negative control and its focused tests. Then a **focused Codex closure check** of the fixes only, not a second full review. Findings the owner rejects are recorded in Decisions with reasons.
- **Exit:** every finding fixed and closure-confirmed, or owner-waived in writing. Then owner acceptance of the remediated candidate, before the full gate.

## 17. Native full-gate execution and failure policy (P6b)

- **Preconditions:**
  - Codex remediation closed;
  - owner acceptance recorded;
  - a clean LF worktree at the candidate SHA (§3);
  - the app `.venv` built from the macOS lock;
  - the engines that are claimed are installed and offline-ready;
  - no other heavy process running;
  - mains power;
  - the candidate SHA recorded in Handoff **before** the run.
- **Command (exactly once):** `.venv/bin/python -u files/dev-work/verification-gate/verify.py --mode full --platform macos --label macos-final-<sha8>`, run from the clean worktree. Outputs go to the gate's ignored `outputs/`. Durable evidence: run id, counts, skips by darwin-policy id, `NOT APPLICABLE` totals, BLOCKED items, the tree fingerprint and the environment identity.
- **During phases P1–P5:**
  - Permitted: only `--mode focused --test <ids>` for the touched modules.
  - Forbidden: `--mode changed`. Its `full_on` rule escalates any `scripts/shared/` change to a full run.
  - Forbidden: `--mode full`, unfiltered `pytest` and repository-wide runs.
- **Failure policy:**
  - A FAIL or incomplete run is **BLOCKED**, not PASS. Stop: diagnose with narrow tests; fix only what is necessary, with focused checks.
  - **Ask the owner before any rerun.** Any program or test change after the run invalidates it, and a new full run is needed for the changed tree.
  - Never re-run unchanged failures, never split the gate into giant partial suites to dodge it, and never describe a stale or failed run as PASS.
- **Windows (D8, recommended):** the same frozen SHA gets the canonical Windows full gate on HOME-PC (`.venv\Scripts\python.exe files/dev-work/verification-gate/verify.py --mode full --platform windows`), by the owner or a Windows-session agent, under the same failure policy. Without it, the release notes must state the Windows evidence actually obtained.

---

## 18. Git branching, versioning and release provenance

**Branch and commit practice:**
- Work happens on `feature/0.8.0-macos-compatibility` (from `9554bc8`).
- One or more scoped commits per phase, pushed to the feature branch at each phase checkpoint.
- No master merge, rebase, force-push or tag move without explicit owner approval.
- The owner's 17 tracked deletions and untracked files are never staged; stage only explicit paths.
- No AI trailer unless the owner's attribution rule says otherwise.

**Integration:** at P7 only, on approval, a fast-forward of `master` if ancestry permits. If `master` has diverged, stop for a new decision.

**Provenance facts:** `v0.8.0` = `d1701e9` and ships only `AudiobookTool-Windows-v0.8.0.zip`. Every macOS change happens after that commit. A macOS archive built from the macOS branch therefore **cannot** honestly be called "v0.8.0", because its source is not `d1701e9`.

| Option | What | Advantages | Disadvantages / Git implications |
|---|---|---|---|
| **A. v0.8.1 patch release with Windows + macOS assets from one commit (recommended)** | Identity 0.8.1 (`config.toml`, `version.py`). One tag `v0.8.1` on the merged commit. Both ZIPs built from it | One version = one source = two platforms. Shared fixes (process lifeline, publication, Cmd+Q, fonts, lock tooling) reach Windows. Clean "latest". `release.py` already builds both | Windows must be re-verified on that commit (D8). Windows users see a new version whose changes are mostly macOS. The patch number is arguable: adding a platform is a feature (see D) |
| B. Add a macOS asset to the existing v0.8.0 release | — | — | **Rejected.** It misattributes source: the tag points at `d1701e9`, and the Mac build is not from it |
| C. macOS-only revision (e.g. tag `v0.8.0-macos.1`, release "v0.8.0 for macOS (source r1)") | macOS ZIP from the Mac commit; Windows stays v0.8.0 | No Windows re-release; the Windows evidence is untouched | Two lines of versions; "latest" ambiguity; `version.py` must not say plain `0.8.0` for different source (needs e.g. `0.8.0+macos.1`, which tests and release tooling must accept); shared fixes do not reach Windows |
| D. v0.9.0 (minor) with both assets | As A, minor bump | SemVer-honest for "new platform + new setup stage" | Same verification cost as A |

**Recommendation:** A (or D if the owner prefers minor-version semantics). The decision is separate and recorded before P7.

**In all options:**
- Annotated tags only.
- Release notes state exactly which platforms and engines were qualified, on what hardware, and what is still open.
- The macOS asset is built from the clean LF worktree at the tagged SHA by the unchanged packager.
- The archive is audited (members, modes, LF, no env, models or secrets) and its SHA-256 recorded.
- An anonymous re-download is verified.
- Nothing in this programme is published without that separate approval.

---

## 19. Numbered implementation phases and acceptance criteria

**Session rules (every phase):**
- A **fresh** Claude Code context per phase. Read this plan, `AI-WORKSPACE.md`, the Handoff, and the previous phase's checkpoint and actual Git state.
- Do not re-audit earlier phases unless a concrete mismatch appears.
- Complete only the named phase. Use focused tests only (§17).
- Commit and push scoped changes to the feature branch.
- Update Handoff (and Decisions for non-obvious choices).
- **STOP** with a report: verdict PASS/BLOCKED, SHA, files, tests run with counts, real-hardware evidence, open items, and the next phase.
- Never roll into the next phase.

**Windows protection (every phase):**
- Each change is platform-guarded or proven platform-neutral.
- Every touched shared file is listed in the Handoff "Windows touchpoints" list, with the Windows tests that cover it.
- Run on the Mac the platform-neutral tests that exercise Windows branches through injectable `platform=` parameters.
- HOME-PC focused verification of the accumulated touchpoints happens in P5.

### P0 — Native research, architecture and roadmap (this session) — DONE when this plan is committed and pushed
- **Entry:** owner prompt.
- **Delivered:**
  - this plan;
  - the feature branch;
  - the Handoff checkpoint;
  - the ignored private inventory and wheel matrix.
- **Not done:** any code change, environment, install, download, model or gate.

### P1A — Native bootstrap and environment foundation
- **Entry:**
  - the owner approves this plan;
  - decisions D1–D5 are recorded;
  - `chmod +x` of the `.command` is approved;
  - the clean-LF worktree decision is made;
  - network access to python-build-standalone, PyPI and the FFmpeg source is approved for lock generation and first-run tests.
- **Scope:**
  - `Setup_and_Run-audiobook-creation-tool.command`;
  - new `scripts/shared/bootstrap_host_macos.sh`;
  - `scripts/shared/bootstrap.py` (macOS branches: `APP_PYTHON` per platform, `install_python`, `find_suitable_python`, Homebrew removal from the default path, macOS FFmpeg acquisition);
  - `scripts/shared/base_packages.py` (platform-keyed lock);
  - new `scripts/requirements-lock-macos-arm64-py312.txt`;
  - `files/dev-tools/lock_base_requirements.py` (platform parameter);
  - `scripts/shared/ffmpeg_portable.py`/`ffmpeg_health.py` (macOS source pin, `aac_at` requirement);
  - `scripts/shared/cleanup_state.py` (no Apple-python candidate, MAC-028);
  - `venv_layout`/`venv_integrity`/`maintenance` case probe (MAC-015);
  - platform-tagged receipts and stores (MAC-029);
  - tests.
- **Tests:**
  - stage-0 fixture states (§14);
  - lock parse/applies/completeness;
  - every installed native file is arm64;
  - `pip check`;
  - bootstrap import proofs;
  - Windows `lock_applies` unchanged (injected `platform="win32"`);
  - a real first run in a disposable clean worktree under `files/dev-work/`: stage 0 → base env → FFmpeg → GUI launches → all six tools open;
  - `.venv` damage → repair;
  - Windows-origin `runtime-data` ignored.
- **Owner manual:** Finder double-click of the `.command` in the disposable copy (no Gatekeeper yet; that is P5).
- **Exit (PASS):**
  - the fresh setup reaches a running app with no Homebrew dependence and no admin prompt;
  - hashes are enforced;
  - focused tests pass;
  - Windows touchpoints are listed;
  - committed and pushed.
- **Stop conditions:**
  - the PBS Tk proof fails on macOS 27 (escalate D1);
  - any pin lacks a macOS artefact at resolution time (owner decision);
  - torch 2.6.0 fails to import on macOS 27 (owner decision; affects the shared pins).

### P1B — macOS GUI shell, platform safety layer and the five non-TTS tools
- **Entry:** P1A PASS.
- **Scope:**
  - `launcher.py` (Cmd+Q, `ShowPreferences`, `RLIMIT_NOFILE`);
  - `shared/subprocess_utils.py` (POSIX media-child registry and `stop_media_children`; lifeline helper);
  - `tts/worker_limits.py` (darwin memory reader, neutral wording);
  - `tts/publication.py` (`renamex_np` no-clobber);
  - optionally `shared/work_area.py` (D11b);
  - fonts and shortcuts (MAC-020, 037);
  - the Tk 9 port (trackpad `<TouchpadScroll>`, wheel deltas; MAC-040) and the PBS launch cosmetics (MAC-042), all guarded by the running Tk version;
  - the main-thread audit (MAC-032);
  - fixes for aqua regressions the native tests reveal;
  - gate: `verification.json` darwin skip policy, `verify.py` darwin preflight, `coverage.json` macOS counterparts / not-applicable entries (MAC-027).
- **Tools accepted:** MP3 Tool, M4B Converter (incl. xHE-AAC via `aac_at`; continuous route refused and fallback correct), M4B Maker, M4B Metadata Editor, Cover/Image Tool (incl. HEIC).
- **Tests:**
  - focused module suites on the Mac, including the 39+ aqua tests;
  - real-media acceptance with the existing env-var fixtures;
  - Cancel and Pause with real FFmpeg;
  - Cmd+Q during a job;
  - `kill -9` of the GUI during an FFmpeg step (child gone);
  - disk-full image;
  - exFAT image;
  - NFD names;
  - two app copies;
  - Edge-like 8-way open-file stress under 256.
- **Owner manual:** GUI checklist (Light/Dark, Retina, geometry, dialogs, Finder reveal, focus, Terminal auto-close) for the five tools.
- **Exit:** five tools PASS focused + real-media + owner GUI check; gate darwin policy in place; Windows touchpoints listed.
- **Stop:** a GUI crash from the Tk/AppKit thread rule that cannot be fixed narrowly; any invariant break.

### P2 — Edge TTS and Kokoro (TTS Audiobook panel on macOS)
- **Entry:** P1B PASS.
- **Scope:** TTS panel macOS behaviour, Edge multi-file workers, Kokoro (device policy and eSpeak data path on macOS), and the listed §12 changes.
- **Tests:**
  - five Edge voices: real network, short multi-file run with 8 workers, Cancel during synthesis and finalization, Pause then Cancel;
  - nine Kokoro voices: CPU, texts A + short multi-chunk;
  - Cancel latency measured (bounded by one chunk; record seconds);
  - speech-prep `v1` and `off` parity tests;
  - real-runtime opt-in tests with their exact skip rules;
  - 18 reference hashes before and after.
- **Owner manual:** listening pack per §15 (A track for all 14 voices; B track for one Kokoro and one Edge voice); Kokoro is the priority engine.
- **Exit:** Edge and Kokoro **PROVEN on this Mac** for all 14 voices, with owner listening approval.
- **Stop:** Kokoro pronunciation regressions vs Windows (owner-judged); espeak-ng load failure; Edge endpoint failure (upstream outage is BLOCKED, not FAIL, and recorded).

### P3A — Chatterbox Turbo
- **Entry:** P2 PASS.
- **Scope:** `chatterbox_synth.py` device policy (CPU default on darwin), dtype guard, conditionals cache key with device, and macOS-neutral wording (§12).
- **Tests:**
  - experiments E0–E4 (§12);
  - six voices on CPU: A + short multi-chunk;
  - watermark detection;
  - memory soak of one chapter;
  - Cancel latency;
  - MPS only as a documented opt-in experiment, never the default unless it passes the §15 correctness oracle.
- **Owner manual:** six-voice listening (A track).
- **Exit:** six Chatterbox voices PROVEN on CPU (or the owner accepts an MPS configuration on evidence).
- **Stop:** CPU RTF unacceptable to the owner (D6) → recorded; voices stay available with an accurate speed note, or are gated per the owner.

### P3B — Qwen3-TTS (CustomVoice and Voice Clone)
- **Entry:** P3A PASS.
- **Owner consents:**
  - the ~9.1 GB model download (CustomVoice + Base);
  - the Qwen3 environment;
  - optionally Whisper for WER;
  - **D12** (POSIX authority design).
- **Scope:**
  - **(a) Installer authority port:** a POSIX implementation of `artifact_store.boundary` and the Qwen3 package/engine authority. It uses directory file descriptors (`os.open(..., O_DIRECTORY|O_NOFOLLOW)`, `dir_fd=`-relative operations, `fstat` identity checks before and after, `O_NOFOLLOW` leaf opens, same-volume `rename` from a pinned staging dir) to give the same "no renamed/replaced parent between check and use" guarantee the Windows handles give. Security-relevant; Codex review priority.
  - **(b)** The macOS hash lock and darwin target in the Qwen3 manifest (PyPI only, one torch 2.10.0 file, ACT `sox` supply wheel).
  - **(c)** Worker device/dtype adapter: CPU fp32 default; MPS bf16 only by evidence; never fp16.
  - **(d)** `platform_supported()` → darwin arm64 only after E1–E5 pass.
  - **(e)** Hardware text from measurements.
- **Tests:**
  - experiments E1–E5 (§12);
  - eight voices (two CustomVoice, six clones);
  - the long-form memory trend;
  - Cancel/kill of the worker group;
  - lifeline on GUI kill;
  - interrupted install;
  - corrupt model → repair;
  - reference hashes.
- **Owner manual:** listening for eight voices (A track; B track for one CustomVoice and one clone).
- **Exit:** eight Qwen3 voices PROVEN on the chosen device, or **D7** applied (voices stay visible-unavailable on macOS, with the recorded reason).
- **Stop:** E3/E4 fail on CPU fp32 → the Qwen3 macOS gate stays closed (no fake-enable).

### P4A — OmniVoice feasibility experiment (owner-gated; no product code)
- **Entry:** P3B closed (PASS or D7).
- **Owner consents:** the ~3.27 GB model and ~0.25 GB wheels into a **disposable** environment under `files/dev-work/omnivoice-feasibility/`.
- **Procedure:** §12 OmniVoice experiment, steps 1–9:
  - neutral `say`-generated reference first, then the six real references read-only (hashes verified before and after);
  - three configurations (MPS fp16, MPS fp32, CPU fp32);
  - every measurement listed;
  - `PYTORCH_ENABLE_MPS_FALLBACK` unset.
- **Exit:** a written verdict per configuration (PASS/FAIL against §15 correctness) plus an owner decision: integrate on a named configuration, or keep OmniVoice unavailable on macOS (D7). No ACT code changed in P4A; the disposable environment is removed or kept per the owner.

### P4B — OmniVoice integration (only if P4A yields an owner-accepted configuration)
- **Scope:**
  - the darwin wheel list in the manifest;
  - worker adapter (every CUDA call site in §12);
  - `omnivoice_synth` device/dtype;
  - `prompt_identity` gains the device;
  - setup proof job per platform;
  - optional-setup texts and the GPU probe (Apple GPU vs NVIDIA);
  - `platform_supported()` for darwin arm64.
- **Tests:**
  - six voices: A + multi-chunk;
  - the 48-chunk worker bound on MPS (memory trend);
  - Cancel, kill and lifeline;
  - install, adopt, repair and receipt on macOS;
  - reference hashes;
  - the offline audit hook.
- **Owner manual:** six-voice listening (A + B), compared against the Windows-approved tracks.
- **Exit:** six OmniVoice voices PROVEN, or the engine is closed with D7.

### P5 — Cross-platform integration and macOS acceptance
- **Entry:** P4A/P4B closed.
- **Scope:**
  - long-book qualification (text D) for Kokoro, plus ≥30-minute runs for each other proven engine;
  - the §15 benchmark table;
  - App Nap / hidden-window run;
  - packaging dry run (`release.py` MacOS archive into scratch → audit → Archive Utility extraction of a **quarantined** copy → Gatekeeper "Open Anyway" flow → first run → repair → relaunch);
  - README/Briefing/Changelog/Decisions updates (truthful per-engine status);
  - feature-map entries for macOS;
  - **HOME-PC focused Windows regression** on all accumulated Windows touchpoints (owner or a Windows agent);
  - optional `fresh-macos` qualification scenario (D9b).
- **Owner manual:**
  - full macOS GUI pass of all six tools;
  - final listening sign-off across all proven voices;
  - Gatekeeper first-run experience.
- **Exit:** owner acceptance of macOS functionality; Windows focused regression PASS; the candidate frozen and pushed.

### P6 — Independent Codex review, remediation, owner acceptance, ONE native full gate
- **P6a:** Codex review → remediation → closure (§16).
- **P6b:** owner acceptance of the remediated candidate.
- **P6c:** **one** macOS full gate (§17). **P6d (D8):** the Windows full gate on the same SHA.
- **Exit:** both gates PASS (or the owner's recorded, informed exception, as with v0.8.0); the evidence recorded.
- **Stop:** any FAIL leads to diagnosis → owner approval before a rerun.

### P7 — Release candidate packaging and publication approval
- **Entry:** P6 PASS and the release-strategy decision (§18).
- **Scope:**
  - version identity bump;
  - `RELEASE_OS_NAMES` includes MacOS;
  - both archives built from the clean LF worktree at the final SHA, then audited;
  - README release section.
- **Then the owner decides:**
  - merge (fast-forward);
  - tag;
  - publish;
  - each separately approved.
- **Exit:** published release verified by anonymous download (hash = audited file); Handoff closeout.

---

## 20. Risks, unresolved blockers and owner decisions

### 20.1 Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | The app-owned runtime brings **Tk 9.0.4** (PBS) where Windows has Tk 8.6. Tk 9 + Python 3.12 relies on PBS's downstream patches (the #1320 threading fix shipped in `20261009`), and is untested by ACT on macOS 27. Possible issues: blurry or unfocused windows (non-framework build), trackpad scrolling, geometry pins | Medium / medium–high (GUI is the product surface) | Bounded Tk proof in stage 0; the P1B Tk 9 port (§10); aqua tests; owner GUI check. Fallback D1 → python.org 3.12.10 + Tk 8.6.16 (admin install, frozen since 2025-04) only by owner decision |
| R2 | torch 2.6.0 (Jan 2025) on macOS 27: CPU fine, MPS untested by PyTorch on macOS 27 | Medium for MPS, low for CPU | CPU defaults; MPS only by measured evidence; a pin bump is an owner decision with Windows re-verification |
| R3 | MPS silent wrong output: multinomial zero-probability picks (pytorch#192577), MPSGraph argmax read past buffer on macOS 27 (pytorch#187280), NaNs in fp16 | Medium / high (garbled audio without an exception) | Correctness oracle vs CPU fp32 (§15); fallback disabled during experiments; no MPS default without owner acceptance |
| R4 | MPS allocator growth on 24 GB (chatterbox#577: 3.2 GB allocated, 24.9 GB driver) | Medium / high (swap, stalls) | Memory slope checks; `empty_cache` between chunks; watermark ratios; bounded workers; CPU default |
| R5 | Qwen3 CPU too slow for whole books (about 2.6× slower than real time reported on a base M4) | High / medium | Owner speed budget D6; honest speed note; keep available or gate per owner |
| R6 | OmniVoice MPS fp16 garbled on M4 (#172) vs working (#279) | Medium | P4A three-configuration experiment before any code |
| R7 | The POSIX installer authority is security-sensitive and new | Medium / high | D12; focused race/symlink tests; Codex priority |
| R8 | Gatekeeper friction for unsigned `.command` in a downloaded ZIP | High / medium (first-run UX) | Clear README and launcher guidance; D10 (signing/notarization is a future option) |
| R9 | Tk/AppKit main-thread crashes from worker callbacks | Low–medium / high | Static audit + stress test (P1B) |
| R10 | Shared-code changes regress Windows | Medium / high | Platform guards; touchpoint list; HOME-PC focused regression (P5) + Windows full gate (D8) |
| R11 | In-process engines (Kokoro, Chatterbox) keep models resident; switching engines may stack memory | Medium / medium | Measure in P3A/P5; unload-on-switch only if needed (owner-visible behaviour unchanged) |
| R12 | Edge service changes (403s, voice removals) | Low–medium / medium | Upstream-outage = BLOCKED, not FAIL; pinned edge-tts reviewed at P2 entry. 7.3.1 is current as of 2026-11-14. `NoAudioReceived` (#512) is open upstream, so ACT's existing per-file retry policy applies unchanged |
| R14 | Duplicate OpenMP runtimes (torch + sklearn/numba `libomp`) abort a process on macOS | Low–medium / high | E-B1 imports everything in one process before any synthesis work |
| R15 | torch 2.6.0 (pinned by chatterbox-tts 0.1.7 metadata) fails on macOS 27 | Low (CPU) / high (shared pin) | P1A import proof; options listed in §12.B, owner decision |
| R16 | eSpeak NG data-path length limit (≥ 160 chars → `exit(1)`) in deep install folders | Medium / high for Kokoro | Verify the `espeak_data` short root; refuse too-deep folders before downloads, like the Windows depth checks |
| R13 | App Nap / idle sleep during long books | Medium / medium | Measure; optional `caffeinate -w` (D11d) |

### 20.2 Unresolved blockers (today)

- **B1.** Qwen3 installation on macOS is BLOCKED by the Windows-only `artifact_store.boundary` (fails closed). It needs the D12 port.
- **B2.** OmniVoice and Qwen3 workers have CUDA-only / Windows-only code paths and `platform_supported()` gates. Removing them is gated on experiments.
- **B3.** A fresh Mac without Homebrew cannot set up today: the launcher depends on Homebrew. Resolved by P1A.
- **B4.** No `darwin` skip policy exists, so any macOS gate result today is untrustworthy. Resolved by P1B.

None of these blocks the *plan*.

### 20.3 Owner decisions required (recommendation first)

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Base Python for macOS | App-owned python-build-standalone 3.12.15+20261009 aarch64 (same as Windows): no admin, SHA-pinned, **Tk 9.0.4 on macOS**, so the bounded Tk 9 port is accepted. Fallback only on P1A failure: python.org 3.12.10 (Tk 8.6.16, admin, frozen) |
| D2 | Launcher stops installing Homebrew and Homebrew Python | Yes; the app-owned runtime only |
| D3 | FFmpeg on macOS | Accept a discovered arm64 pair only if proven (incl. `aac_at`, `libmp3lame`); app-owned fallback = a versioned Martin Riedl arm64 build (9.0.1 if offered, else 9.0.2), pinned by ACT's own size + SHA-256, signature-checked, downloaded on consent |
| D4 | Checkout hygiene | `chmod +x` the `.command` in this tree; build releases and run the full gate from a clean LF worktree under `files/dev-work/worktrees/` |
| D5 | Network access for P1A | Approve python-build-standalone, PyPI and the FFmpeg source for lock generation and first-run tests |
| D6 | Speed/memory budgets per engine | Set at P5 entry from measured data; correctness thresholds per §15 are fixed |
| D7 | If an engine cannot be proven on macOS | Ship macOS without it; its voices remain visible-unavailable with the reason; no substitution |
| D8 | Windows evidence for a combined release | Windows full gate on the same final SHA |
| D9 | macOS GUI acceptance method | Owner-manual checklist + in-process Tk tests; no Accessibility / Screen Recording permission grants. D9b: automated `fresh-macos` scenario optional |
| D10 | Gatekeeper UX | README + launcher guidance for "Open Anyway"; no signing this release; Developer ID / notarization as a future decision |
| D11 | Optional improvements | (a) F_FULLFSYNC: no; (b) macOS work-area recovery: yes if cheap; (c) qualify a macOS FFmpeg build for the continuous route: later; (d) `caffeinate` during jobs: decide after the P5 measurement |
| D12 | Qwen3 installer authority on POSIX | Implement the dir-fd design (same guarantee), not a reduced-guarantee shortcut |
| D13 | Cross-copy engine lock location | Per-user temp (`tempfile.gettempdir()/ACT-locks/`), consistent with the existing work area |
| D14 | Download consent and disk budget | Per-engine, as Windows (§9 table shown before consent) |
| D15 | ASR for WER | Reuse the pinned Whisper small.en in a dev-only scratch environment, on consent |
| D16 | Release version and strategy | §18 option A (v0.8.1), or D (v0.9.0) |

---

## 21. Phase-by-phase checklist and stop conditions

**Universal checklist (start of every phase):**
1. A fresh context.
2. Read this plan, `AI-WORKSPACE.md`, `md-instructions/Handoff.md` (top block) and the prior phase report.
3. `git status -sb`, `git log --oneline -5`, `git fetch origin`. Confirm the branch is `feature/0.8.0-macos-compatibility` and the expected prior SHA, and that the owner state is unchanged (17 deletions + untracked set).
4. Confirm this phase's entry decisions and consents are recorded.
5. Re-verify the 18 reference hashes if this phase runs any engine.
6. List the planned focused tests.

**Universal checklist (end of every phase):**
1. Focused tests pass, with counts recorded.
2. Real-runtime evidence recorded (paths in ignored folders only).
3. 18 reference hashes re-verified (engine phases).
4. Windows touchpoints updated.
5. Handoff updated (Decisions for non-obvious choices).
6. Stage explicit paths only; review `git diff --cached`.
7. Commit and push to the feature branch.
8. Report (verdict, SHA, files, tests, evidence, open items, next phase).
9. **STOP.**

**Universal stop conditions (any phase):**
- Any immutable contract in §13 would change.
- A test passes only by weakening, skipping or deleting a meaningful check.
- A Windows code path would change behaviour without being a deliberate, owner-approved shared fix.
- An engine would be enabled without its proof, or a voice substituted.
- Any download without recorded consent.
- Any action outside the repository, or a system setting change (Gatekeeper, SIP, permissions, global Python, Homebrew).
- The full gate is about to run outside P6c.
- Git state contradicts Handoff (trust Git, investigate, correct Handoff).
- Repeated failure of the same real-runtime test (diagnose, don't loop).

| Phase | Must be true to start | Must be true to finish | Hard stop if |
|---|---|---|---|
| P1A | Plan approved; D1–D5; chmod approved | Fresh-copy first run → healthy app, no Homebrew/admin; locks hashed; focused PASS | PBS Tk fails; a pin cannot resolve natively; torch 2.6 import fails |
| P1B | P1A PASS | Five tools PASS (focused + real media + owner GUI); darwin gate policy | Unfixable Tk/AppKit crash; invariant break |
| P2 | P1B PASS | 14 Edge/Kokoro voices PROVEN + listening | Kokoro pronunciation regression; espeak-ng failure |
| P3A | P2 PASS | 6 Chatterbox voices PROVEN (CPU or accepted MPS) | MPS made default without the oracle; memory blow-up on CPU |
| P3B | P3A closed; D12; consents | 8 Qwen3 voices PROVEN, or D7 recorded | CPU fp32 fails E3/E4 (gate stays closed) |
| P4A | P3B closed; consent | Per-configuration verdict + owner decision | Any reference WAV hash change |
| P4B | P4A accepted configuration | 6 OmniVoice voices PROVEN, or D7 | Correctness oracle fails |
| P5 | P4 closed | Owner macOS acceptance; Windows focused PASS; frozen candidate | Packaging audit fails; Gatekeeper path unusable |
| P6 | P5 accepted | Codex closed; owner acceptance; ONE macOS full gate PASS (+ Windows per D8) | Gate FAIL (no rerun without owner) |
| P7 | P6 PASS; D16 | Audited archives; approved merge/tag/publish | Any provenance mismatch |

---

## Appendix A — Source links (accessed 2026-11-14)

Labels as used in the text. Third-party reports are evidence of plausibility, not proof on this Mac.

**Platform: Python, Tk, Gatekeeper, FFmpeg, PyTorch, POSIX**
- python-build-standalone release 20261009 (asset digests): https://github.com/astral-sh/python-build-standalone/releases/tag/20261009 ; Tk version at the tag: https://github.com/astral-sh/python-build-standalone/blob/20261009/pythonbuild/downloads.json , https://github.com/astral-sh/python-build-standalone/blob/20261009/cpython-unix/build-tk.sh ; Tcl 9 threading fix: https://github.com/astral-sh/python-build-standalone/issues/1320 ; non-framework build: https://github.com/astral-sh/python-build-standalone/issues/274
- python.org: https://www.python.org/downloads/release/python-31210/ , https://www.python.org/downloads/release/python-31216/ , https://docs.python.org/3.13/using/mac.html , https://github.com/python/cpython/blob/v3.12.10/Mac/BuildScript/build-installer.py ; Tk 9 in CPython: https://github.com/python/cpython/issues/124111
- Homebrew formulae API: https://formulae.brew.sh/api/formula/python-tk@3.12.json , https://formulae.brew.sh/api/formula/tcl-tk.json , https://formulae.brew.sh/api/formula/ffmpeg.json
- Tk 9: https://www.tcl-lang.org/software/tcltk/9.0.html , TIP 474 https://core.tcl-lang.org/tips/doc/trunk/tip/474.md , TIP 684 https://core.tcl-lang.org/tips/doc/trunk/tip/684.md , `tk::mac` hooks https://www.tcl-lang.org/man/tcl9.0/TkCmd/tk_mac.html , file dialogs https://www.tcl-lang.org/man/tcl9.0/TkCmd/getOpenFile.html , AppKit main-thread ticket https://core.tcl-lang.org/tk/info/bec431fc689e , tkinter threading https://docs.python.org/3/library/tkinter.html
- Gatekeeper/quarantine: https://developer.apple.com/news/?id=saqachfa , https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac , https://support.apple.com/en-us/102445 , https://eclecticlight.co/2022/09/09/app-first-run-quarantine-and-translocation/ , https://eclecticlight.co/2025/12/08/who-decides-to-quarantine-files/ , https://eclecticlight.co/2024/08/10/gatekeeper-and-notarization-in-sequoia/ , `ditto(1)` https://keith.github.io/xcode-man-pages/ditto.1.html , arm64 signing https://developer.apple.com/documentation/macos-release-notes/macos-big-sur-11_0_1-universal-apps-release-notes
- FFmpeg builds: https://ffmpeg.martin-riedl.de/ , https://www.osxexperts.net/ , https://evermeet.cx/ffmpeg/
- PyTorch: https://pypi.org/pypi/torch/json , MPS notes https://docs.pytorch.org/docs/2.15/notes/mps.html , MPS env vars https://docs.pytorch.org/docs/2.15/mps_environment_variables.html , `torch.mps` https://docs.pytorch.org/docs/2.15/mps.html , bf16 on MPS https://github.com/pytorch/pytorch/pull/119641 , MPS multinomial https://github.com/pytorch/pytorch/issues/192577 , macOS 27 MPSGraph https://github.com/pytorch/pytorch/issues/187280 , MPS in sandboxes https://github.com/pytorch/pytorch/issues/177819
- POSIX: `kqueue(2)` https://keith.github.io/xcode-man-pages/kqueue.2.html ; Python `subprocess`/`os`/`fcntl` docs (3.12)

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
| MAC-002 | Executable bit lost in this ZIP-transferred checkout (index 100755, disk 0666) | working tree | P1A (owner-approved chmod) |
| MAC-003 | Gatekeeper/quarantine first-run UX for a downloaded ZIP | launcher, README | P1A text, P5 test |
| MAC-004 | `bootstrap.py` macOS Python acquisition is Homebrew-only; `APP_PYTHON` is Windows-only | `bootstrap.py` | P1A |
| MAC-005 | The dependency lock applies only to `win32`; macOS installs unhashed `==` pins | `base_packages.lock_applies` | P1A |
| MAC-006 | macOS FFmpeg: Homebrew-only, no pinned source; continuous route qualified only for Gyan Windows hashes; `aac_at` needed for xHE-AAC | `ffmpeg_portable.py`, `ffmpeg_health.py`, `m4b_continuous.py` | P1A/P1B |
| MAC-007 | Tk 9.0.4 (every no-admin macOS Python, incl. PBS) vs Tk 8.6.15 (Windows) | runtime choice (D1) | P1A (proof), P1B (port) |
| MAC-008 | Cmd+Q (`::tk::mac::Quit`) unhandled | `launcher.py` | P1B |
| MAC-009 | No parent-death containment; `stop_media_children` Windows-only | `subprocess_utils.py`, workers | P1B (FFmpeg), P3B/P4B (workers) |
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
| MAC-027 | Gate has no darwin skip policy; Windows-only acceptance adapters | `verification.json`, `verify.py` | P1B |
| MAC-028 | Cleanup coordinator may fall back to PATH `python3` (Apple's) | `cleanup_state.interpreter_candidates` | P1A |
| MAC-029 | Windows-origin `runtime-data` (settings with a Windows path, consents, sessions) must be foreign-safe | settings, optional setup, receipts | P1A |
| MAC-030 | CRLF working tree from the ZIP | checkout | P1A (D4) |
| MAC-031 | App Nap / idle sleep during long jobs | app | P5 (D11d) |
| MAC-032 | Tk/AppKit main-thread rule | all panels | P1B |
| MAC-033 | `RELEASE_OS_NAMES` Windows-only; README macOS status | `release.py`, README | P7 |
| MAC-034 | Local agent guidance names stale paths (`scripts/Universal`, `scripts/verify.py`, `CHANGELOG.md`) | `.claude/CLAUDE.md` (local, untracked) | Owner refresh (not code) |
| MAC-035 | eSpeak NG data path on macOS (`espeak_data.py` symlink/short-root logic) | `shared/espeak_data.py` | P2 |
| MAC-036 | No `timeout` utility; bash 3.2 for stage 0 | stage 0 | P1A |
| MAC-037 | `<Control-a>` without `<Command-a>` in some text boxes | `shared/job_ui.py` | P1B |
| MAC-038 | NFD-named inputs and outputs need fixtures | import/output tests | P1B |
| MAC-039 | Terminal auto-close via `osascript` (possible Automation prompt) | `shared/close_terminal.py` | P1A manual |
| MAC-040 | Tk 9 trackpad `<TouchpadScroll>` missing at three custom scroll sites; `qwen3_clone_setup_ui` wheel handler never scrolls with small macOS deltas | `ui_theme.py`, `cover_resizer.py`, `qwen3_clone_setup_ui.py` | P1B |
| MAC-041 | The launcher's Gatekeeper help says "right-click → Open", which macOS 15+ no longer honours | `.command`, README | P1A |
| MAC-042 | Possible menu-bar name "Python", Dock icon, Retina sharpness and front-most focus with a non-framework PBS interpreter | GUI launch | P1A measure, P1B fix if needed |
