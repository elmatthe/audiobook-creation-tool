# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it. Entries dated before
2026-11-13 (before v0.8.0) are archived unchanged under `files/documentation-history/decisions/` (DOC-1; see "Archival split").

### Index of standing decisions (navigation only; added by Phase 0B on 2026-11-25)

This index changes nothing below it. Every line names a dated entry; find it with `grep -n "^## <date> — <first words>"` or your editor's
search. Entries are never moved or rewritten (append-only), so the index cites headings, not line numbers. A later entry supersedes an
earlier one only where this index or the entry itself says so. The index lists what still governs the code and the process; anything
not listed is history, recoverable here and through Git.

**Documents, Git and process**
- 2026-11-27 — v0.8.2 Phase 2: DOC-1 archival (entries before 2026-11-13 in `files/documentation-history/`), tracked historical cleanup, simple manual retention (GATE.md).
- 2026-11-25 — v0.8.2 Pre-Phase 1A: `C:\ACT-Dev` development checkout (D-1), the main application environment is always root `.venv/`, A5 and A6 approved in principle, DOC-1 archival in Phase 2.
- 2026-11-25 — v0.8.2 Phase 0B: Handoff and Briefing compaction, this index, the open pronunciation requirement, D17 recorded.
- 2026-11-25 — v0.8.2 Phase 0A: five permanent documents (exact case), plans in `files/plans/`, a local-only AI Workspace (D-5), v0.8.1 published (D-7), interim verification rule.
- 2026-11-21 — v0.8.2 is a long-running development branch: nothing is merged, tagged or released per fix; identity stays 0.8.1.
- 2026-08-29 — Project work lives in the repository; external workspaces need permission.
- 2026-07-08 — AI-WORKSPACE.md and the vibe-coding templates are excluded from version control (reaffirmed by Phase 0A).
- 2026-07-07 — No AI co-author trailers in commit messages, ever (maintainer is sole author; a harness attribution reminder does not override it).
- 2026-07-06 — One commit per drop for the entire v0.5.0 sequence (historical; v0.5.0 only).

**Verification gate**
- 2026-11-27 — v0.8.2 verification simplification: the routine envelope is retired (it supersedes the routine-envelope parts of the 1A-1, R1, R2 and R3 entries below); standard pytest under a supervised stage with a small guard; routine modes execute; Phase 1A consolidated, 1A-2 reduced and deferred.
- 2026-11-27 — v0.8.2 Phase 1A-1 R3: launch evidence is the reserving parent's own (one spawn, one terminal observation); an explained stop is one proved action with its exact code; nothing runs before the envelope and admission binds the whole invocation; recipes and stage 0 are bound to their actual commands; privacy fails closed before any read; the exact Qwen3 read-only selfcheck profile restored.
- 2026-11-26 — v0.8.2 Phase 1A-1 R2: explained termination only (D-R2-1); exact reviewed startup, footprint, native, multiprocessing and shell profiles (D-R2-2..4); bounded compatibility campaigns (D-R2-5, D-R2-10); positive synthetic recipes, one launch decision, pre-launch reservations, collection reconciliation, privacy before reads, ambiguous imports as gaps; the bypass test replaced (D-R2-6); worker network-guard measurements (D-R2-7); inert fast-cancellation stand-ins (D-R2-8); scrubbed guarded workers (D-R2-9); recovery accounting corrections.
- 2026-11-25 — v0.8.2 Phase 1A-1 R1: location is never evidence of a synthetic run (reviewed synthetic fixture only), the launch contract judges the real program, environment and form, one early envelope for both runners, canonical selectors, the requested module or node is the scope, admission re-resolves, routine accounting fails closed.
- 2026-11-25 — v0.8.2 Phase 1A-1: plan Revision 5 (A5-W, A5-M, A6-R, ENTRY; Phase 1A as 1A-1, 1A-2, 1A-3); every request is an explicit execution plan, changed selection never widens, routine verification refuses heavyweight effects.
- 2026-11-06 — Phase 2 closeout: verification is targeted first, one planned full gate per phase on a committed candidate.
- 2026-11-06 — The canonical gate moves to `files/dev-work/verification-gate`; scratch stays short (the `%TEMP%\act-gate` exception).
- 2026-11-06 — The gate owns its Windows error mode, and why a run can lose a flag.
- 2026-11-07 — The journeys' application runs at Low integrity so its file dialogs cannot write the owner's history.
- 2026-11-11 — Phase 8 checkpoint after a Windows Update restart: a blocked gate is fixed at its cause, not rerun.
- 2026-11-22 — v0.8.2: Windows excuses the `files/dev-work/` "no colliding test basename" skip, and only that one.

**Setup, environment and packaging**
- 2026-11-28 — v0.8.2 Phase 5B: OmniVoice installed by uv into `.venv-engines/omnivoice` from `scripts/tts/engines/omnivoice/` (88 Windows / 86 macOS artifacts, exact v0.8.1 parity, no package cache); `omnivoice_manifest.json` holds the model only, the v0.8.1 package sets stay as the lock's parity reference; an earlier `.venv/engines/omnivoice` keeps working until the new engine is proved, then is retired to set-aside (supersedes the 2026-11-13 nested-layout entry for new OmniVoice installs).
- 2026-11-27 — v0.8.2 Phase 5A: one explicit engine registry (`scripts/tts/engines/registry.py`) that seven consumers derive from; shared engine provisioning (`shared/engine_env.py`); Qwen3 installed by uv into `.venv-engines/qwen3` (89/89 parity, no package cache), an earlier engine kept until the new one is proved, the nested one then retired to set-aside (supersedes the 2026-10-25 nested-layout entry for new Qwen3 installs).
- 2026-11-27 — v0.8.2 Phase 4 macOS acceptance: a dangling `.venv/bin/python` link takes the repair route; a person's download answer stands for the process; the test guard excuses the macOS managed interpreter's stdlib bytecode; census standings for ROUTINE-EFFECTS and SCRATCH.
- 2026-11-27 — v0.8.2 Phase 4: the base environment is provisioned only by uv (one wrapper, one locked base project, offline-first repair cache, receipts after RECORD and import proof); D-6 fallback approved and implemented; the legacy interpreter stays for engines through one resolver (supersedes 2026-10-31's local-store route for the base).
- 2026-11-27 — v0.8.2 Phase 3B (macOS uv feasibility) and the owner's approvals: uv 0.13.10, A2 exact pinned build, A1 sibling engine environments `.venv-engines/<engine>/` (supersedes the engine part of 2026-11-13), A4/D-8 Windows copy and macOS clone, base repair cache kept, no GPU-engine cache by default, bytecode at install.
- 2026-11-27 — v0.8.2 Phase 3A (Windows uv feasibility): uv 0.13.10 and an ACT-owned CPython 3.12.15+20261009 download pin reproduce today's interpreter and every locked artifact; A1 (siblings recommended), A2, A4/D-8 (copy) proposed to the owner.
- 2026-11-13 — v0.8.0 unified `.venv` layout: OmniVoice at `.venv/engines/omnivoice`; an earlier `.venv-omnivoice` is never used. Engine placement superseded by 2026-11-27 Phase 3B (A1 siblings) as each engine migrates to uv.
- 2026-11-13 — v0.8.0 Phase 3: OmniVoice is the fifth component of the optional installer, used only with the installer's receipt.
- 2026-11-18 — Windows starts the app on the venv's `python.exe` with a hidden console; `pythonw.exe` is never started (Smart App Control).
- 2026-10-31 — The app environment installs only from a complete hash lock through a verified local store. Superseded for the base by 2026-11-27 Phase 4 (uv).
- 2026-10-27 — Owner-approved Option B: base preparation is separate from optional acquisition (an out-of-order entry near the end of the file; see the ordering note).
- 2026-10-25 — P04C closes on the nested Qwen3 layout: `.venv/engines/qwen3` is canonical; legacy `.venv-qwen3` kept unused for rollback.
- 2026-10-25 — Optional voices are acquired only from pinned identities, under a spent consent; inference loads only verified local copies.
- 2026-10-24 — Developer mode is a typed `config.toml` boolean, shipped false; reference-transcript tools are developer-only.

**Engines, voices and platforms**
- 2026-11-16 — macOS P4C: one platform capability policy (`scripts/shared/engine_policy.py`) decides the engines; macOS offers Edge, Kokoro and OmniVoice (20 voices).
- 2026-11-16 — Owner decisions Q1=A, Q2=A, Q3=A: Mac-first scope with an approved Edge/Kokoro fallback; unsupported engines removed from the Mac UI.
- 2026-11-16 — P4B owner-accepted with its memory performance exception: the Mac-GPU worker keeps its 16-chunk bound.
- 2026-10-24 — Voice identity is (backend, voice_id); labels and order are cosmetic; the six recordings per engine are fixed by table.
- 2026-11-20 — v0.8.1 Checkpoint C1: an OmniVoice chunk with nothing to say, trimmed to zero samples, is a 0.2 s pause; refined by the next line.
- 2026-11-25 — v0.8.2: an OmniVoice chunk with words that comes back empty is rendered again with further seeds derived from its own (24 renderings at most).
- 2026-11-18 — P5 closeout: the darwin map is complete; long-form real-media evidence; App Nap measured.
- 2026-11-18 — P5-H: on a Mac a narration that reaches the assembly gate is joined on disk, never in memory.
- 2026-11-18 — P5-D: on POSIX a synthesis worker is never reaped before its process group has been ended (a series of P5 containment entries follows it).
- 2026-11-20 — Expedited macOS release readiness: Cancel acknowledgment about 1 s; D16 route C; no further wholesale containment redesign (route C was overtaken: v0.8.1 shipped both ZIPs).

**Output, cancellation and data safety**
- 2026-11-03 — TTS output is published atomically through one contract; Overwrite is off unless ticked for a run.
- 2026-11-05 — Cancel stops active work promptly, finished narration included; only Pause drains active files.
- 2026-11-04 — No low-memory path can hang: every Edge FFmpeg route is supervised and stoppable.
- 2026-11-08 — Cancel stops a running FFmpeg step in the MP3 Tool and the M4B Maker through one small supervisor.
- 2026-11-22 — v0.8.2 Windows qualification: Import Folder replaces only the Books the user agreed to replace.
- 2026-11-21 — v0.8.2: no persistence feature for the MP3 workspace; the guarantee is responsiveness and kept edits within the session.

**User interface**
- 2026-11-20 — v0.8.1 Checkpoint A: shared identity 0.8.1; engine roster decided only by the capability policy; dialog history written only on accepted selection.
- 2026-11-20 — v0.8.1 Checkpoint E: on Aqua the four outlined role styles draw a same-size outline image element.

**Ordering notes.** The file is newest-first from the top down to `2026-07-06 — verify.py adopted as the mechanical gate`. Known breaks, left in
place (append-only): `2026-10-01 — Strip only recognised embedded MP3 join metadata before strict decoding` sits among the 2026-09-20 entries;
`2026-10-19` entries sit among the 2026-10-20 ones near `2026-10-20`; and the last eight entries (`2026-10-27 — Owner-approved Option B`,
`2026-10-30 — Release installer`, and six dated 2026-11-09 for v0.7.2 Phase 6 batches A to E and its final candidate) were appended after the
2026-07-06 entry. D16 and D18 (macOS) are recorded inside the 2026-11-18 P5 closeout entry; D17 is recorded in the entry below.

**Archival split (DOC-1, v0.8.2 Phase 2, 2026-11-27).** This file keeps the entries from 2026-11-13 (v0.8.0) onward. The older
entries moved unchanged, byte for byte and in their original order, to two per-era files; an index line dated before
2026-11-13 names an entry there. [v0.6.7 to v0.7.3](../files/documentation-history/decisions/Decisions-v0.6.7-to-v0.7.3.md) (October to
12 November 2026, with the eight late-appended entries at its end) and [v0.5.0 to v0.6.6](../files/documentation-history/decisions/Decisions-v0.5.0-to-v0.6.6.md)
(July to September 2026). The ordering breaks above are in those files. The whole file before the split:
`git show dabb02d:md-instructions/Decisions.md`.

## 2026-11-28 — v0.8.2 Phase 5B: the OmniVoice engine is installed by uv into `.venv-engines/omnivoice`; its manifest holds the model only; an earlier engine keeps working until the new one is proved

**Context.** The owner's Phase 5B prompt (plan Revision 10; this phase is recorded as Revision 11), on HOME-PC in `C:\ACT-Dev`, on top of
Phase 5A. Approved inputs as for 5A: uv 0.13.10, CPython 3.12.15 + PBS 20261009 through ACT's metadata, A1 siblings
`.venv-engines/<engine>/`, A4/D-8 (Windows copy, macOS clone, never hardlink, no GPU-engine package cache), bytecode at install, and the
Windows OmniVoice installation proof moved to 5B (Revision 7). Agent-verified on Windows, not independently reviewed; macOS owed.

1. **One project, two platforms, exact parity.** `scripts/tts/engines/omnivoice/` (`pyproject.toml` + `uv.lock`, a virtual project,
   `no-build`, environments `win32/AMD64` and `darwin/arm64`, every v0.8.1 version pinned as a constraint): on Windows exactly the 88
   v0.8.1 artifacts (torch and torchaudio 2.8.0+cu128 only from the explicit CUDA 12.8 index, by a `sys_platform == 'win32'` source
   marker; CUDA float16 as released), on an Apple Silicon Mac exactly the 86 (plain PyPI torch 2.8.0; MPS or the CPU in float32 as
   released). `test_omnivoice_uv_project.py` derives what the lock installs on each platform (the graph under the platform's markers,
   then the most specific wheel by the standard tag order; macOS 15 arm64, where the Mac set was acquired) and holds it equal to the
   v0.8.1 sets by name, version, file and SHA-256. No Windows CPU-only or Intel-Mac profile; no dependency or model upgrade.
2. **Package and model concerns are separate.** `omnivoice_manifest.json` (version 2) holds the engine version, the pinned model snapshot
   (repository, revision, files, sizes, SHA-256, tokenizer, load set) and the licences only. The v0.8.1 package sets move unchanged to
   `scripts/tts/omnivoice_packages.json`: `uv.lock`'s parity reference, the source of the download size shown before an install (the
   PyTorch index publishes no sizes) and the pinned set an earlier version's engine is still judged by. Nothing is installed from it;
   it goes with the first OmniVoice dependency change, at the latest in Phase 6. The engine unit's consent source is
   `uv-lock:scripts/tts/engines/omnivoice/uv.lock@sha256:<lock>`; the model unit's is unchanged.
3. **The installer is uv, through the 5A foundations only.** `omnivoice_setup.build_engine`: `uv venv` at `.venv-engines/omnivoice` on the
   managed CPython, then `uv sync --locked --no-dev --no-cache --compile-bytecode --link-mode copy` (macOS `clone`), all through
   `shared/engine_env.py` and `shared/uv_runner.py`; the pip route, its wheel fetcher and the base-interpreter probe are removed (no
   second production installer). The model door (the scoped opener) refuses every package URL. After the sync every installed file is
   checked against its RECORD, then the worker's existing probe runs; only then are the environment's own receipt
   (`.act-environment.json`) and, last, the install receipt (`files/runtime-data/omnivoice/uv-engine-receipt.json`, version 3, bound to
   the folder and the lock identity) written. The install lock, inference lock, engine lease, worker protocol, offline guard, process
   ownership and every model, voice, prompt, seed, retry and generation behaviour are unchanged.
4. **Which engine is in use.** `.venv-engines/omnivoice` once its version-3 receipt says `installed`; otherwise an earlier
   `.venv/engines/omnivoice` (v0.8.0-v0.8.1, judged by its own version-2 receipt and the v0.8.1 pins) while it is there. A new engine that
   is not installed to the end is never used. Once installed, the new engine stays the one in use even when a conversion later proves it
   damaged (its receipt keeps `installed` and gains `rejected`), so a damaged engine is never hidden behind an older one; the repair is
   offered. The first builds' `.venv-omnivoice` is never used.
5. **Migration: no forced move; nothing working is broken.** An earlier engine keeps working, unchanged, until an install or repair builds
   and proves the new one. Then the nested engine is moved whole by rename to `files/runtime-data/omnivoice/set-aside/nested-omnivoice-<UTC>-<id>/`
   with its version-2 receipt and `RETIRED-READ-ME.txt` (`engine_env.retire`), and `.venv-omnivoice` is retired as before; neither is ever
   deleted, and one that cannot be moved now stays, unused, and is said. An interrupted or failed new install leaves the earlier engine in
   use and byte-identical; the next plan offers to finish the new one (re-synced in place).
6. **Only what this app built is ever deleted.** A repair removes `.venv-engines/omnivoice` only when this app's receipt says it built it
   (stage `creating`/`created`, or origin `installed`); an adopted or unknown environment is moved aside whole instead. Adoption needs a
   uv environment on this copy's managed CPython holding exactly the locked set, a clean RECORD check and the same probe.
7. **Measured, not assumed.** uv `--no-cache` unpacks every package into its scratch before copying it, so an install needs about the
   environment's size twice (`install_temp_bytes` = the environment size; measured peak 16.5 GB for an 8.33 GB environment). The
   environment size stays the v0.8.1 measurement (8.35 GB; the uv build measured 8.33 GB). `.venv-engines/omnivoice` is exactly as deep as
   `.venv/engines/omnivoice`, and the measured deepest file and native library (168 and 135 characters below the app folder) equal the
   released depth constants, so the length rule is unchanged.
8. **Smaller.** The planner says, while an earlier engine is in use and a new install stopped half-way, that the voices keep using the
   earlier engine until the new one works (`NESTED_IN_USE_NOTE`); the registry places OmniVoice `engine` with its project, and the
   `nested` placement stays only to describe earlier engines; the test session guards the real OmniVoice engine marker, environment
   receipt and install receipt; the planning bridge's read-only source list carries the engine project and the package reference; the
   packager ships the project from the registry (refusing a build without it); `test_uv_provisioning`'s resolver contract no longer
   names OmniVoice (only Qwen3's sealed seam, cleanup and the setup protocol still ask `app_python`).

**Why.** The same reasons as 5A: an engine in its own locked project beside the base survives every base rebuild, one installer route
instead of two, and no install, interruption or failure leaves a person without working voices.

**Not changed.** VERSION 0.8.1; no dependency or model upgrade; Kokoro and Chatterbox stay in the base until 5C/5D; Edge and the non-TTS
tools are unaffected; nothing merged, tagged or released.

— Claude Code (Opus 5.5) under the owner's Phase 5B prompt.

## 2026-11-27 — v0.8.2 Phase 5A: one explicit engine registry; the Qwen3 engine is installed by uv into `.venv-engines/qwen3`; an earlier engine keeps working until the new one is proved

**Context.** The owner's Phase 5A prompt (plan Revision 9; this phase is recorded as Revision 10), on HOME-PC in `C:\ACT-Dev`, after the
owed Windows regression of the Phase 4 macOS corrections and the D-6 cold-fallback check. Approved inputs: uv 0.13.10, CPython 3.12.15 +
PBS 20261009 through ACT's metadata, A1 siblings `.venv-engines/<engine>/`, A4/D-8 (Windows copy, no GPU-engine package cache), bytecode at
install. Agent-verified, not independently reviewed.

1. **One explicit registry.** `scripts/tts/engines/registry.py` (standard library only) holds one `EngineDefinition` per engine: identity
   and names, platforms, placement (`base`, `nested`, `engine`), its uv project, earlier environment places, model manifest, installer,
   worker, and the optional-setup `Component`s. `engine_policy` (engine lists, names, component engines), `voice_registry.BACKENDS`,
   `optional_setup_protocol` (components, labels, wizard defaults, Qwen3 model keys), `bootstrap.WINDOWS_OPTIONAL_CHOICES`,
   `local_engine_host.ENGINE_NAMES`, `venv_layout`'s engine places and `release`'s excluded environment folders and required engine
   projects are derived from it, value for value as released. Adding an engine is one definition plus its own modules; removing one is
   deleting it (`test_engine_registry.py` proves both on a disposable list and pins the released tables). No plugin discovery, dependency
   injection, service container or worker server.
2. **Shared engine provisioning without a second wrapper.** `scripts/shared/engine_env.py` holds what every `.venv-engines/<engine>` shares,
   all through `shared.uv_runner`: its place and project, the `uv venv`/`uv sync` commands, identity (its own place, no link, isolated, built
   by uv, on this copy's managed interpreter with the pinned build), the RECORD check (`shared.venv_integrity`), the receipt (lock,
   interpreter, profile, distributions, health) and retirement of an earlier version's environment. Locks, runtime-use leases, process
   ownership and cancellation stay each engine's own (Qwen3: `InstallLock`, the engine lease, `run_command`'s Job Object).
3. **Qwen3's production installer is uv** (the pip route is no longer reachable from any production path). Project
   `scripts/tts/engines/qwen3/` (`pyproject.toml` + `uv.lock`): 89 packages, every version and wheel hash exactly the v0.8.1 reviewed set
   (`qwen3-requirements.txt` and `qwen3-artifacts.json` stay as its parity references, `test_qwen3_uv_project.py`); torch/torchaudio
   2.10.0+cu128 only from the explicit CUDA 12.8 index; sox as ACT's commit-pinned derivative wheel; Windows x64 only; `no-build`; a virtual
   project (`package = false`). Install: `uv venv` on the managed CPython at `.venv-engines/qwen3`, then `uv sync --locked --no-dev
   --no-cache --compile-bytecode --link-mode copy`. No Qwen3 package cache is kept (A4/D-8): a failed or cancelled install keeps no packages
   and the next downloads them again; the size shown first is every reviewed wheel. The v0.7.0-v0.8.1 wheel store and pip cache are removed
   after a successful install, the store only when its `verified.json` shows it is the app's. The consent source of the engine unit is now
   `uv-lock:scripts/tts/engines/qwen3/uv.lock@sha256:<lock>`. Both Qwen3 choices share this one environment; `qwen3_models.json` and every
   model, voice and generation behaviour are unchanged.
4. **Migration: no forced move; nothing working is broken.** An engine of an earlier version (`.venv/engines/qwen3`, v0.7.0-v0.8.1; or
   `.venv-qwen3`) stays the engine in use, unchanged, until an install or repair builds the new one. The new one becomes the engine in use
   only when its install record is written, last, after the sync, a RECORD check of every installed file, the worker's probe and the
   receipt. An interrupted or failed new install never takes over; Check and repair finishes it. Then the nested engine is moved, whole and
   by rename, into `files/runtime-data/qwen3/set-aside/nested-qwen3-<UTC>-<id>/` beside a `RETIRED-READ-ME.txt` (the OmniVoice convention;
   never deleted by the app; left where it is while a file in it is in use). `.venv-qwen3` is never moved or deleted (the owner's to remove).
   Only a create or remove the app recorded as interrupted is cleared automatically; an engine folder no record vouches for is left alone
   until Check and repair rebuilds it. Check and repair also checks the uv engine's RECORDs read-only.
5. **What stays as it was (seams).** The v3 sealed-package seam (`qwen3_engine_authority`, `optional_setup_authority.acquire_disposable`;
   no production caller) still installs with pip into the nested place it was designed for, until Phase 6 removes the pip paths. The
   nested-engine carry protocol stays for OmniVoice (5B) and for an earlier Qwen3 engine not yet replaced. OmniVoice, Kokoro and Chatterbox
   are unchanged (5B-5D); Edge and the non-TTS tools are unaffected; macOS offers no Qwen3 and behaves as before.
6. **A killed operation's partial downloads do not stay.** Each uv operation records its owner (process id and creation time) in its
   scratch folder; the Qwen3 installer, before it starts, removes the scratch of operations whose process is provably gone
   (`uv_runner.clear_stale_scratch`, `shared.work_area.owner_state`). A live, unknown or unrecorded owner's folder is left alone. Found by
   the native interruption run (422 MB of partial downloads were left behind).
7. **Clear Downloaded Data.** Its environment item still removes only `.venv`; the engine beside it is never reached and stays in use.
   An earlier version's engine held inside `.venv` keeps every protection (the item is refused while one is there).
8. **Smaller.** The pre-venv planner stays standard-library only and process-free (`uv_runner` imports `subprocess` where it runs it); the
   test session guards the real `.venv-engines`, the Qwen3 engine's marker and receipt; the packager ships each engine's uv project and
   refuses a build without it; the D-6 fallback hands `curl` each URL by variable name (passing it through `call` expanded the `%2B` of the
   CPython URL into a 404, found by the cold run); `voice_registry` and `bootstrap` may import the registry package and nothing else of
   `tts`; the direct-spawn allow-list names `uv_runner.run` (developer CLI and probes; a Phase 4 omission).

**Why.** One list instead of seven parallel tables makes adding and removing engines (5B-5D, v0.9.0) one change; an engine in its own uv
project beside the base survives every base rebuild (uv removes a whole project environment when it recreates it); keeping the earlier
engine in use until the new one is proved means no install, interruption or failure leaves a person without working voices.

**Not changed.** VERSION 0.8.1; no dependency or model upgrade; no new authorization store; nothing merged, tagged or released.

— Claude Code (Opus 5.5) under the owner's Phase 5A prompt.

## 2026-11-27 — v0.8.2 Phase 4 macOS acceptance: corrections found natively on HOME-MacOS

**Context.** The Phase 4 macOS verification procedure ran natively (agent-run, one owner-supervised app launch; evidence in `Handoff.md`).
It found defects that the Windows run could not see; each was corrected in the smallest place, with a regression test.

1. **A `.venv/bin/python` that is a link leading nowhere counts as present** in `Setup_and_Run-audiobook-creation-tool.command` (`[ -e ] ||
   [ -L ]`). uv's macOS environment links it to the app Python's absolute path, so a moved or copied folder leaves it dangling; `[ -e ]`
   alone sent that installed copy through first-time setup. It now takes `--repair-venv`, which rebuilds offline and carries the engines.
   Windows is unaffected (its `python.exe` is a real file).
2. **A person's download answer stands for the rest of that process** (`bootstrap._ask_download_consent`). A repair whose in-place attempt
   was refused continues on the rebuild route, which reached the same question again. A No given only because nothing could ask (no
   window, no console) is not remembered.
3. **The test guard excuses the macOS managed interpreter's own first-import standard-library bytecode** (`conftest.py`:
   `cpython-3.12.15-macos-aarch64-none/lib/python3.12` and uv's minor-version link, the tag read from `lib/libpython3.12.dylib`), exactly as
   it already did on Windows. Without it every gate run from a new uv dev environment on a Mac failed once a test started its base
   interpreter. Site-packages, foreign tags, links and anything else still count.
4. **Census:** `ACT.GATE.ROUTINE-EFFECTS` (created in 1A-1 after the P1B census) gets its native macOS standing from a native run (8 of 8
   pass); `ACT.GATE.SCRATCH` moves from native-with-failures to native (its one failure was D3). No other standing was touched.
5. Smaller: the failed-rebuild wording, the headless Tk summary, the developer `--` passthrough and a bounded per-module import retry (one
   targeted reinstall per failing module, none after a failed sync); the P1A skip ceiling raised to the counted 55.

**Why.** A moved install must be repaired, not reinstalled; one question per start; the dev environment Phase 4 prescribes must be able to
run the gate on both platforms.

**Not changed.** VERSION 0.8.1; the containment guardian's ~1 s orderly exit after `--venv-check` (the Mac launcher does not call it); the
launch health check's sampling (by design). Nothing merged, tagged or released.

— Claude Code (Opus 5.5) under the owner's Phase 4 macOS acceptance prompt.

## 2026-11-27 — v0.8.2 Phase 4: the base environment is provisioned only by uv; D-6 approved and implemented; the legacy interpreter stays for engines through one resolver

**Owner decision D-6 (APPROVED in the Phase 4 prompt).** When PowerShell cannot run, setup uses a contained fallback built from Windows'
own `curl.exe`, `certutil` and `tar.exe` with the pinned hashes (`scripts/shared/bootstrap_host_fallback.cmd`); a Python that merely
happens to be on the computer is never used (this retires the `.bat` PATH-Python fallback).

**Decisions taken while implementing the approved plan (agent-implemented, not independently reviewed).**
1. One wrapper, `scripts/shared/uv_runner.py`, runs every uv command: `--python 3.12.15` with managed interpreters only and no
   downloads by uv itself, `--project`, `--locked`, an explicit profile (`user` = `--no-dev`, `dev` = `--group dev`), link mode `copy` on
   Windows and `clone` on macOS (never a hard link), `--compile-bytecode`, and a scrubbed environment (`UV_`, `PIP_`, `PYTHON*`,
   `SSL_CERT_` and activation settings dropped; the cache, Python installs and per-operation scratch inside the app folder). It refuses
   any target but `.venv` or `.venv-engines/<engine>`.
2. The base project is the root `pyproject.toml` with its `uv.lock`: a parity translation of the v0.8.1 hash locks (the same releases and
   SHA-256s; Kokoro and Chatterbox stay until 5C/5D). pytest lives only in the `dev` group, which is the gate's single pytest pin. A profile
   is recorded only by `bootstrap.py --profile`, never inferred.
3. Offline first, from the persistent repair cache `files/runtime-data/uvc`. A download happens only after consent: starting first-run
   setup is that consent; a launch or repair asks once, on the main thread (a worker never creates Tk); no one to ask means No. A package
   whose kept files are damaged is fetched again only after its cache entries are removed (`uv cache clean <package>`), because
   `--refresh-package` alone reinstalled the same damaged unpacked files. `uv cache prune` runs only after a real successful sync.
4. The receipt `.venv/.act-environment.json` binds the base project and lock (line endings normalised), the interpreter (home, `BUILD`,
   archive SHA-256, `sys.version`), the profile and the health. It is withdrawn before any sync and written only after every installed file
   matched its RECORD (read directly; a missing RECORD is damage) and the required imports were proved. A v0.8.1 stamp is not a receipt.
5. uv never syncs an environment it could recreate (recreation deletes nested engines): only a uv-built `.venv` on exactly this copy's
   managed interpreter is synced in place. Anything else (a v0.8.1 pip environment, another home, a moved copy) is rebuilt through the
   existing set-aside transaction, which carries `.venv/engines/*` byte for byte and puts the old environment back on failure. Package damage
   in a uv environment is repaired in place first, and only then rebuilt.
6. Transitional rule 2: `files/runtime-data/python` is never deleted or moved. `scripts/shared/app_python.py` names the base of the copy's
   `.venv` (the managed interpreter, or the legacy one while `.venv` still runs on it) for the Qwen3 and OmniVoice installers, the cleanup
   coordinator and the optional-setup checks.
7. Stage 0 accepts only the pinned uv binary (its SHA-256) and the exact interpreter (`BUILD`, `sys.version`, ssl, venv, ensurepip, a real Tk
   root on Windows), proved at its final place with its own path compared inside it; it refreshes uv's minor-version link after a move and
   reports a relative ASCII path, so any folder name works.
8. The path budget stays 172 characters: measured, a uv `.venv` reaches 155 and the managed interpreter 164; only uv (long-path aware)
   touches the deeper cache (171).
9. Gate: the pytest pin comes from `pyproject.toml`'s `dev` group; D1-D3 of the Phase 3B report are corrected; the test guard excuses the
   managed interpreter's first-import standard-library bytecode exactly as it excuses the legacy one's.

**Why.** Exact, hash-locked, offline-repairable installs with one tool on both platforms, without ever trusting a Python found on the
computer, and without risking the voice engines that still live inside `.venv`.

**Evidence (HOME-PC, agent-run).** Real disposable scenarios: fresh cold install, relocation, warm launch, package repair, cache damage,
interruption, legacy migration with a rollback, the legacy engine route on both layouts, the fallback `.cmd`, a cached offline install of a
fresh copy; registry, PATH and user-profile state unchanged. `C:\ACT-Dev` migrated to the dev profile. Details: `Handoff.md` (Phase 4).
**macOS: implemented, native verification PENDING** (`files/plans/ACT-v0.8.2-Phase4-macOS-Verification.md`).

**Not changed.** VERSION 0.8.1; the Qwen3 and OmniVoice installers' own route (5A/5B); FFmpeg, NLTK, eSpeak and model handling; the owner's
installations and checkouts. Nothing merged, tagged or released.

— D-6 decided by the owner; implemented and recorded by Claude Code under the owner's Phase 4 prompt.

## 2026-11-27 — v0.8.2 Phase 3B: native macOS uv feasibility PASS; the owner approves the Phase 3A proposals (uv 0.13.10, A2, A1 siblings, A4/D-8, bytecode); Phase 4 may start

**Owner decisions (recorded by Claude Code from the owner's Phase 3B prompt).** (1) uv **0.13.10**, subject to native macOS
compatibility (proved). (2) **A2:** preserve the exact existing pinned CPython 3.12.15 + PBS 20261009 build through ACT-owned
download metadata. (3) **A1:** independent sibling engine environments `ACT_ROOT/.venv-engines/<engine>/`; the main application
environment stays `ACT_ROOT/.venv/`; **the engine portion of the 2026-11-13 unified-layout decision is superseded** (it governs the
current installers until each engine migrates). (4) **A4/D-8:** Windows `copy`, the base repair cache retained, no persistent
Qwen3/OmniVoice package cache by default; macOS `clone` subject to native proof (proved). (5) Bytecode compiled during
installation. (6) The Windows OmniVoice installation proof moves to Phase 5B. (7) Native macOS feasibility completes before
Phase 4 (done). Offline-repair limits for engines whose artifacts are not retained stay documented honestly.

**Evidence (Phase 3B, HOME-MacOS, agent-verified, not independently reviewed).** Report:
`files/plans/ACT-v0.8.2-Phase3B-macOS-uv-Feasibility.md`; pin: `files/plans/phase3a-uv-examples/python-downloads-macos.json`.
- uv `uv-aarch64-apple-darwin.tar.gz` SHA-256 `e419bf07533bdbf48795fc793601c834dd79db57a8c49ce8e25cfe3a8639958d` (three sources agree);
  Developer ID signed, notarized; a quarantined copy runs.
- The ACT-owned pin installs the archive `bootstrap_host_macos.sh` pins (`83dcb047…75b8`). uv patches two files at install time on
  macOS (`libpython3.12.dylib`'s install name, `_sysconfigdata`); every other file is byte-identical to today's interpreter; Aqua Tk
  9.0.4, ssl, venv and offline restoration proved; no user, PATH or system writes.
- Parity with the Phase 3A definitions unchanged: base 169/169, OmniVoice 86/86, Kokoro 97/97 + the spaCy model; all three installed
  and import-proved with MPS available. No model loads or synthesis.
- APFS `clone`: warm install 0.56 s and 18 MiB physical (copy 8.78 s, 1.2 GiB); in-place damage stays out of the cache; offline repair
  0.10 s. uv deletes nested engines when it recreates the base; siblings survive. Move and copy relocation recreate offline.

**Why clone and siblings.** Clone keeps environments independent of the cache (copy-on-write) at almost no disk cost, which is what
made `copy` necessary on Windows; siblings remove the base-rebuild protection protocol entirely on both platforms.

**Requirements carried to Phase 4** (report §11): pass `--python 3.12.15` and validate `home` (an interpreter path or `==3.12.*`
records uv's minor-version link); interpreter identity by archive SHA-256 + `BUILD` + `sys.version`, never a tree hash; receipts
after a RECORD check (a dist-info without RECORD is damage) and real imports; per-operation Python cache scratch removed; never
transfer an interpreter through a quarantining path; `hardlink` never used.

**Gate finding (not changed here).** D1: on Darwin an exiting process group answers EPERM to `killpg`, so
`helpers/winproc.py` reports a false survivor or raises; the smallest correction (treat EPERM like ESRCH in `_stop_tree`, poll
before recording survivors on POSIX) is owed before Phase 4 relies on macOS gate cleanup. D2: one exit-code contract test assumes
the Windows-only `m4b-scaling` scenario (test portability). D3: `helpers/scratch.py` cannot prove a POSIX owner alive, so
`--audit-scratch` on macOS calls an active run's scratch abandoned (read-only reporter; low severity).

**Not changed.** Application code and behaviour, VERSION 0.8.1, the root `.venv/` and its nested OmniVoice engine,
`files/runtime-data/`, the production setup route, the gate, macOS security settings, the owner's uncommitted work.

— Owner decisions recorded and Phase 3B implemented by Claude Code under the owner's Phase 3B prompt.

---

## 2026-11-27 — v0.8.2 Phase 3A: uv is feasible on Windows with exact parity; A1, A2, A4/D-8 and the uv pin are proposed to the owner

**Decision (evidence recorded; the proposals below are NOT approved until the owner says so).** Phase 3A of the Developer
Experience Upgrade ran on HOME-PC (Smart App Control enforcing) entirely inside the ignored `files/dev-work/uv-3a/`. Report:
`files/plans/ACT-v0.8.2-Phase3A-Windows-uv-Feasibility.md`; examples: `files/plans/phase3a-uv-examples/`.

- **Established.** uv 0.13.10 (`uv-x86_64-pc-windows-msvc.zip`, SHA-256 `297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683`)
  installs CPython 3.12.15 + PBS 20261009 byte-identical to today's `files/runtime-data/python` when ACT supplies its own download
  pin (`--python-downloads-json-url`); uv's built-in catalog would choose a different build. No registry, PATH, bin or
  user-directory writes. Independent uv projects reproduce today's pins exactly: base 170/170 (Windows) and 169/169 (macOS) in one
  lock, Qwen3 89/89, OmniVoice 88/88 and 86/86, Kokoro 99/99, Chatterbox 113/113, versions and artifact hashes, no index fallback
  and no uncontrolled builds. Every executable ran from a MOTW-tagged extraction under SAC.
- **Superseded.** The 2026-10-31 entry listed "pip-tools or uv for the lock" as not chosen; the owner-approved v0.8.2
  requirements adopt uv, and this evidence shows uv keeps that entry's contract (a complete hash lock, a verified source, offline
  installation). That part of the 2026-10-31 entry is superseded for v0.8.2; the rest stands. macOS evidence is Phase 3B.
- **Proposed to the owner (pending).** (1) Pin uv 0.13.10. (2) A2 outcome A with the ACT-owned interpreter pin. (3) A1:
  independent sibling engine environments `.venv-engines/<engine>/`, because uv deletes the whole `.venv` when it recreates the
  base, nested engines included; this would supersede the engine part of the 2026-11-13 unified-layout entry. The base stays
  `.venv/` in the application root (fixed). (4) A4/D-8: Windows `copy` link mode (hardlinks share in-place damage with the cache),
  base cache kept for offline repair (about 2 GiB), GPU engines installed with `--no-cache`. (5) Bytecode compiled at install.
- **Requirements carried to Phase 4.** Receipts only after a csv RECORD check that counts a dist-info without RECORD as damage,
  plus real imports (uv's own checks missed two broken packages after an interrupted sync); a per-operation Python archive cache;
  `--project` on every call; validated environment paths; the deepest path rises to 175 characters (uv cache).

**Not changed.** Application code and behaviour, VERSION 0.8.1, the root `.venv/`, installed engine environments, the owner's
primary checkout, the production setup route, Windows security and long-path settings.

— Implemented by Claude Code under the owner's Phase 3A prompt; the owner decides the proposals.

---

## 2026-11-27 — v0.8.2 Phase 2: classified repository cleanup; DOC-1 archives the pre-v0.8.0 Decisions and Changelog unchanged; retention stays simple and manual

**Decision.** Phase 2 of the Developer Experience Upgrade, kept proportionate by the owner's directive (practical cleanup, no cleanup service, no retention framework, no automatic deletion of history).

- **DOC-1 performed.** Decisions entries dated before 2026-11-13 (before v0.8.0) and Changelog sections from `[0.7.3]` down moved, byte for byte and in their original order, into two per-era files each under `files/documentation-history/decisions/` and `files/documentation-history/changelog/`. The eight Decisions entries that had been appended after the oldest one (2026-10-27, 2026-10-30, six of 2026-11-09) sit, unchanged, at the end of the v0.6.7 to v0.7.3 file. Reassembling each archive body with the kept part reproduces both `dabb02d` blobs exactly. `md-instructions/` keeps exactly five documents; both indexes say where the older entries are, and an index line dated before 2026-11-13 names an archived entry. Two tests that pinned archived phrases (the speech G1 comparison numbers; the EPUB "compatibility boundary") read the whole Decisions record (the permanent file plus the archive); a mutation control (archive moved aside) made both fail. The gate classifies `files/documentation-history/` as documentation.
- **Removed from the tree (kept in Git history).** Four `files/dev-tools/` programs that nothing imports or cites outside history: `macos_p2_kokoro_assets.py`, `macos_p4b_omnivoice_install_qa.py`, `macos_p4b_omnivoice_setup.py`, `omnivoice_p2_smoke.py`, with their entrypoint rows. Eight completed plans, each byte-identical to a copy in the owner's local archives (`files/Archives/old-md-instruction-drops/` or `files/plans/archived-plans/` of the primary checkout): `ACT-PLAN_01-PROMPT.txt`, the three v0.6.7 Plan 01/01B/CP6 plans, `ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md`, `ACT-v0.7.0-P05B-Stage4C-Isolation.md`, `ACT-v0.7.1-Edge-Multi-File-Workers-Plan.md` and `ACT-v0.7.2-Windows-Hardening-Feature-Map-and-Verification-Gate-Implementation-Plan.md`. Their decisions were recorded in Decisions when they were implemented.
- **Kept on purpose.** The other 13 dev-tools the entrypoint table calls obsolete (a maintained tool imports `macos_p4a_omnivoice*` and `clone_transcript_extract`; tests that run production code import the rest, such as the Chatterbox colon matrix and the speech characterization that generated the speech goldens). The P05B Stage 4B-2, 4B-3A and 4B-3B plans (linked as contracts from `scripts/shared/README.md` and `scripts/tts/README.md`), the v0.7.2 Phase 7A plan (its section 13 is the m4b-scaling qualification record cited by `coverage.json` issue 11 and the Converter map), the v0.8.0 and v0.8.1 plans and the spike verdict, and every `files/release-history/` file (D-4: five of them have no local copy).
- **Retention: written rules, applied by hand** (GATE.md "Retention and cleanup"): every agent removes its own disposable work; gate run folders and guarded basetemps are kept while cited, the newest per mode always, others eligible for manual removal after 7 days, soft budget 2 GiB (about 0.93 GiB now); protected and unknown paths are never touched. The plan's bounded retention module in the gate runner is not built.
- **`files/run-temp/`** stays untracked and unignored (owner decision, unchanged). Recommendation for the owner: ignore it with one `.gitignore` line (`files/run-temp/`), which removes the staging hazard and changes nothing on disk.

**Not changed.** Application code and behaviour, VERSION 0.8.1, the root `.venv/`, the owner's primary checkout and its uncommitted archiving (D-4), `C:\t\` (D-2), the ACL-locked folders (D-3), protected evidence, D-5 local-only files.

— Implemented by Claude Code under the owner's Phase 2 prompt.

---

## 2026-11-27 — v0.8.2 verification simplification: the universal routine envelope is retired; routine verification is standard pytest under a supervised stage with a small guard, the routine modes execute, Phase 1A is consolidated and 1A-2 reduced

**Decision.** By owner directive (stop over-engineering the verification system; return to application development), and with the owner's delegated authority to evaluate and implement the read-only Codex simplification investigation (`files/codex-summary-for-remote-access/ACT-v0.8.2-Verification-Simplification-Investigation.md`, report commit `ec3343b`), Claude Code replaced Revision 5's routine envelope with a smaller contract (plan Revision 6; GATE.md is authoritative):
(1) **Removed:** launch interception (the CPython `Popen._execute_child` wrapper, thread and multiprocessing patching), the child bootstrap (`routine_child.py`), the direct routine runner (`routine_pytest.py`), exact fixture profiles (`routine_fixtures.py`), launch reservations, per-child effect ledgers, explained-stop accounting and the `routine_stop` markers, the gate's stage ledgers and `routine-effects` check, the guarded runner's stacked envelope, and their infrastructure-only tests.
(2) **Kept:** explicit execution plans, affected-test selection with gaps instead of widening, admission by re-resolution, the requested-scope reconciliation, the session probe and collection reconciliation, stage supervision (deadline, stall, kill-on-close Job or process group, survivors), candidate identity, privacy before reads, historical readers, the guarded groups and their runner, the entrypoint self-checks.
(3) **New and small:** `files/tests/routine_effects.py` is a guard of about 250 lines (marker inherited by children, opt-in scrub, in-process refusal of non-loopback network, real model-weight reads, native input and desktop hand-offs; refusals fail their test even when caught); the gate starts pytest as `python -u -s -m pytest` in a scrubbed environment; quick, focused `--feature`, changed and regression execute (routine 1A-3); GATE.md and the published review summaries are documentation for evidence identity; `.codex/` joins D-5's local-only list.
(4) **Roadmap:** Phase 1A is closed by this consolidated checkpoint (agent-verified, not independently reviewed; 1A-1's FAIL history stands); 1A-2 is reduced (one owner-supervised attempt, an OS lock across checkouts, manual recovery; no authorization store, delegated grants or automatic crash recovery) and deferred until a heavyweight run needs it; 1B's truthful-reporting part is done, its inventory and stable-selector work moves to Phase 2 as touched, its release requalification to Phase 8/9. Next: Phase 2, then Phase 3 (uv feasibility).

**Why.** Two of eighteen checkpoints were done after four failed reviews of one verification phase. The envelope designed against adversarial tests rather than trusted repository tests and cooperating agents; its accounting produced new review findings each round and refused legitimate fixtures (a Git Bash shim, a Tk startup measurement), while the practical risks -- accidental heavyweight execution, owner data, an honest result for the requested scope -- are met by the marker checks at the real entrypoints, the in-process guard, stage supervision and JUnit/probe/scope reconciliation. The gate is an accident-prevention and verification tool, not a security sandbox.

**R3 dispositions.** R3-01 corrected for the gate, superseded for the retired direct helper; R3-02 corrected at the writer; R3-03 superseded (ledger retired with its claim); R3-04 corrected; R3-05 superseded (selfcheck exception retired; the installed-library proof stays an environment obligation); R3-06 corrected; the identity finding corrected. Historical FAIL verdicts are not changed.

**Still open.** The Qwen3 installed-library proof (owner-deferred environment obligation); native macOS verification of the simplified routine path (Phase 3B); independent review of this checkpoint if the owner wants one.

Signed: Claude Code (Opus 5.5), under the owner's delegated authority of 2026-11-27.

## 2026-11-27 — v0.8.2 Phase 1A-1 R3: the R2 independent review FAIL is remediated in six bounded groups; launch evidence is the parent's own, stops bind to one proved action, nothing runs before the envelope, recipes and stage 0 are bound to their actual commands, and privacy fails closed before any read

**Decision.** The independent Codex review of R2 (b96c36f) returned FAIL (sanitized summary in `files/codex-summary-for-remote-access/`); the planning chat accepted it and scoped R3 to six groups, keeping every independently closed finding closed and reusing the existing plan, GateRun, supervisor, bootstrap, recipes, Inventory, probe, ledger format 3 and sealed evidence (no new framework). GATE.md "R3" is the reference.
(1) **R3-01, startup and launch admission.** One startup check (`routine_effects._startup_problem`) judges every Python launch: startup variables, a sitecustomize/usercustomize on PYTHONPATH, the user site's startup code where the interpreter would process it. A nested runner is judged by it, has nothing beside it shadowing a library module, and its PYTHONPATH is moved past its bootstrap and restored after the envelope; `routine_pytest.py` imports only the interpreter's own library before its bootstrap. The inert profile needs a trusted import path. The final admission compares the program the platform starts, the complete arguments, the working directory, the effective environment's values and (unchanged forms) the reviewed profile itself with what was prepared; environment object identity alone never admits.
(2) **R3-02, synthetic outputs and stage 0.** A recipe is admitted on its actual command: destinations inside its fixture tree with no link on the way, plain identifiers, exact options; `check_operation` judges the exact supervised command (without it no stand-in is admitted). Stage 0 runs only as a disposable copy whose app folder holds nothing it would prove before consent but a proved disposable state (an inert stub, or a byte-identical copy of this session's base interpreter with no startup code but its own `.pth` files and at most the pinned BREAK_TK fault); the checkout's own stage 0 is refused, also by the guarded runner's policy while a real interpreter exists. cmd forms without `/d` run only without AutoRun, the setup sandbox holds nothing runnable cmd would find first, and bash forms refuse startup files and exported functions and resolve helpers to the reviewed shims, then system folders. Native macOS proof is pending.
(3) **R3-03, accounting and explained termination.** Every completed reserved launch needs its reserving parent's own spawn and exactly one terminal observation of that process (in the parent's ledger for a linked private ledger); a child's own records never substitute. An explained stop is ONE successful action by the reserving parent (or `self`) for the launch's own process (pid and creation time) before that parent observed exactly the code it leaves (a kill-on-close Job close leaves 0, measured; a stop with no known code explains nothing); its own tree flag governs descendants, which are accounted only when its writer observed them gone after it, and the stopper now observes every descendant of the stopped tree, ended ones included. A reviewed taskkill is recorded from its actual result. Lifecycle expectations reach the opening thread and threads started from it while open, never an unrelated concurrent launch. Dry-run on the 30 sealed R2 ledgers: one verdict changes (R2 batch 16's four completed children whose stopped parent never observed them), the gap the stopper's descendant observation now closes.
(4) **R3-04, privacy (C2).** The local-only policy is mandatory (unavailable or malformed: nothing fingerprinted, read, logged or compared; `changed.local_only` is required by `load_policy`); a tracked local-only path or a tracked/in-scope path through a link stops capture without a name; Git is asked for names before content and for rename detection only when no side is private; bytes are read through the no-follow Inventory and blob ids come from those bytes (`hash-object --stdin --path`; an external clean filter is refused); historical maps are filtered as consumed, never rewritten; Git stderr, exceptions and logged argv never carry a private name; equal digests never make an identity current over a privacy problem.
(5) **R3-05, the Qwen3 selfcheck.** Codex found R2 refused, as real-engine, the exact read-only selfcheck R1 allowed (concealed by the environment skip). The exact form (this checkout's Qwen3 interpreter, `-I -B`, `files/dev-tools/qwen3_calm_venv_tools.py selfcheck <a folder under files/runtime-data/models>`, offline, every cache and scratch destination disposable) is again an exact profile; every other engine-interpreter launch is refused. The installed-library proof is deferred by the owner as a separately recorded environment obligation; it is not a skip-policy waiver, R2 batch 9 stays FAIL, nothing was installed and the installed-library test was not run.
(6) **R3-06, documentation.** Briefing section 8 and Handoff now say what GATE.md says: plan-only modes execute from 1A-3 and owner authorization does not activate them; guarded groups run only through the gate.
(7) **Verification (agent-run, not independent).** RED on the R2 baseline reproduced for every group (Codex's probes and behavioural controls); GREEN after. Gate pilot 3879, 93ce, 2eed, a481 PASS. Owner-authorized R3 campaign (120-minute, three-segment, 10-minute-batch caps): 24 of 25 batches in 4,488 s; 22 PASS; two FAIL kept in the record (the R3-02 bindings refused the packaged launcher's Git-bash shim PATH and D-R2-2's stage-0 Tk measurement; re-admitted exactly with controls, reruns PASS). One guarded control (tk-harness, spaCy consumer, P05B isolation) did not fit the final segment and was not executed in R3.

**Why.** Independent reproduction showed passing evidence that a child could write alone, stops explained by unrelated records, code run before the envelope, recipes writing outside their fixtures and private paths read before the policy was known. Each is closed at the point of decision, without widening anything.

**Still open.** Native macOS verification of the R2 and R3 envelopes; the Qwen3 installed-library proof; the unexecuted guarded control; Phase 1A-2 stays on HOLD.

## 2026-11-26 — v0.8.2 Phase 1A-1 R2: the R1 independent review FAIL is remediated; a child ends unaccounted only by an explained stop, exact reviewed profiles replace exemptions, synthetic fixtures are positive recipes, and every launch owes accounting before it exists

**Decision.** The independent review of the R1 remediation confirmed eight findings (H1/R1-02, H2/R1-01, H3, M1/R1-05, M2/R1-03, M2/R1-04, C2, C4); H4, M3, C1 and C3 stay closed. The first R2 attempt ended in a compatibility discovery and planning stop (reported BLOCKED, nothing committed); the owner's continuation decided D-R2-1 to D-R2-5 and the recovery D-R2-6 to D-R2-10, and these contracts now govern routine verification (GATE.md is the reference; plan amendment R2 records them):
(1) **D-R2-1, explained termination.** A required participant may end without its own end record only when all hold: a valid pre-launch obligation; successful initial accounting; an expected lifecycle established before termination and bound to the launch (the `routine_stop` test marker or `expected_termination`); its own identity; the recorded intent and action of the stop; independent observation of the terminal result; agreement of mechanism and outcome; reconciled descendants; no unexpected refusal or accounting corruption. A kill request alone, a post-hoc explanation and a child that never initialized are never explained; no graceful end record is manufactured; interrupted gate evidence stays incomplete; there is no `os._exit` wrapper.
(2) **D-R2-2, D-R2-3, D-R2-4, exact profiles.** Startup measurements and fixtures run only under exact reviewed profiles (`files/tests/routine_fixtures.py`, pinned by SHA-256, judged on interpreter, bytes, arguments, working directory and environment; a modified probe, target or environment is not the profile): the tk_proof hanging `sitecustomize` under the production timeout path and the `-I -S` pre-venv footprint probe run unchanged with parent-side evidence; the Low-integrity `CreateProcessAsUserW` launches of `containment.spawn_low` (no lowered labels, no widened ledger permissions; any other ctypes process creation refused); multiprocessing `spawn` children through the bootstrap with spawn semantics, `__main__`, the four-way race and the exited-PID assertions kept; cmd, PowerShell and bash only in recipe-based reviewed forms (setup-launcher sandbox, fake FFmpeg wrapper, stage 0, console host, fixed helpers). Arbitrary `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `sitecustomize`, `usercustomize`, startup hooks, shell text, stdin programs, expansions, chains and encoded commands stay unapproved.
(3) **H1, H2, H3.** A synthetic stand-in is valid only while its bytes are exactly a reviewed recipe's source in this checkout (`files/tests/routine_recipes/`, format `act-synthetic-fixture/2`) and its data validates in the recipe's closed vocabulary; a real, modified or historical runner is never a stand-in. Every launch gets one side-effect-free decision -- refuse, bootstrap through `files/tests/routine_child.py`, or an exact profile -- prepared through a verification-only wrapper of the pinned CPython 3.12 `Popen._execute_child` that fails closed on any other interface; `os.system`, `os.exec*`, `os.spawn*`, `os.fork` and direct native process creation are refused. The gate reserves and binds each stage's runner launch.
(4) **M1, M2, C2, C4.** The probe's initial collection inventory must equal what ran plus what was deselected. Effect ledger format 3: an exclusive reservation file before every accounted launch, then spawn, stop and observation rows; every reservation reconciled exactly once; the reader is total. The local-only rule applies before any read or evidence write (a tracked private path BLOCKS a run or a plan, unnamed). An ambiguous dotted import is a gap for its importer, its candidates and everything reached through them.
(5) **D-R2-5.** Compatibility with the corrected child contract is established by one bounded affected-suite routine campaign from a finite manifest (10 minutes per focused batch, 45 minutes aggregate, one sequential pass, disk checked between batches), never by a full gate or sweep; an exhausted budget is reported with the remaining selectors and no claim of complete compatibility. That first campaign exhausted its budget (16 of 19 batches, 13 failing routine-effects) and both real guarded v3 stages failed; nothing was committed, and the owner then decided D-R2-6 to D-R2-10 (2026-11-26).
(6) **D-R2-6.** R1's gate-contract `bypass-bootstrap` case, which expected raw `python -m pytest` to run, is replaced: the same module with a harmless execution sentinel runs through the supported bootstrap (positive control), and as raw `python -m pytest` is refused at its launch with the sentinel untouched; the gate-level "no completed session of the stage's own runner" invariant keeps its own damage case.
(7) **D-R2-7, worker network-guard measurements.** The OmniVoice tests that prove a worker's own network guard (the real worker on the reviewed stand-in stack, the reference probe, the dev-tools worker's inert-event measurement) run through the bootstrap under an exact profile whose reservation names the measurement; the child's envelope then refuses network last instead of first (a hook appended behind the program's guard), so the worker's own refusal is what the test sees, and anything that guard lets through is still refused before it resolves or connects (and fails the test). A changed worker, stand-in, launcher, interpreter form or output outside the disposable roots is not the profile.
(8) **D-R2-8, fast cancellation.** Each case is classified by what it measures. Class A: a stand-in whose `-c` program can reach no effect (time, standard-stream writes, `print`, `sys.exit`, ignoring a signal; checked on its syntax tree, constants only; the trusted interpreter, nothing after the program, no `-i`, and no `PYTHONPATH`, `PYTHONHOME`, `PYTHONINSPECT`, `PYTHONUSERBASE` or `PYTHONEXECUTABLE` unless `-I`/`-E` ignores them -- `PYTHONSTARTUP` is read only by an interactive session, which such a program is not) runs unchanged under an exact inert profile with parent-side evidence, so a cancellation measured within its startup is not turned into a missing participant; the Job-refusal test's stand-in proves it never ran by the pipe it would write first instead of a file. Class B: the two decoder close tests read the decoder's first samples before timing the close of a running decoder (one on a single-process interpreter, as FFmpeg is, so the process holding the decoder's log is the one reaped). Class D: an effect-capable child that never initialized stays a failure, and D-R2-1 is unchanged.
(9) **D-R2-9, scrubbed guarded workers.** The v3 supervisor's fixed fake worker, the read-only planning worker (its own stricter isolation) and the planning bridge worker (its adapter's reviewed containment prefix first) run unchanged under exact profiles that bind the interpreter, `-I -B -S`, the program, a byte-identical copy of the marked sources, the working directory and the exact six-name environment (temporary folders the run root, offline, the real Windows directory); their Jobs own them and their parents record their launches. No routine marker is ever added to such an environment; an arbitrary replacement environment, a changed worker or a widened one is refused as before.
(10) **D-R2-10.** One further bounded campaign (at most 120 minutes in up to three 40-minute segments, 10 minutes per batch, at least 10 GiB free before each segment, 5 GiB floor) replaces the exhausted one; its results are recorded in plan amendment R2 and the Handoff.
(11) **Recovery corrections to the accounting (each with positive and negative controls).** An observed exit that differs from the exit a participant reported in its own end record is accepted only as the code of an explained stop recorded after that record (a supervisor's Job kill landing between its worker's end record and its exit). A profiled leaf its parent never observed is accounted only when an ancestor observed that leaf's own process gone after its own successful tree stop of the chain. A descendant of an ancestor that ended with its own end record is accounted through a declared, successful tree stop its reserving parent then made (the worker exited; its Job ended what it left behind). Closing a kill-on-close Job is recorded as the `close-job` stop of its members (the Job's limits had been queried with an oversized buffer, which Windows refuses, so such a stop was never recorded). A process that assigns its own launch to a kill-on-close Job records it (`contained`); a descendant held so by a participant whose own end is an explained stop is accounted once observed gone (the gate tests that kill a gate outright, whose own Job ends its tree), and a leaf that participant never observed, once its owner saw it gone after that stop. A gate driven by a test keeps the session role for a substituted stage command only when it is the reviewed fake-pytest recipe, which now writes the initial collection inventory (M1); the gate's evidence file map treats a Git failure in its privacy check like any other unavailable map instead of crashing the run. The deliberate stops of effect-capable children carry exact per-test `routine_stop` markers naming the mechanisms the code under test uses; no module-wide marker. The bash test_release_packaging falls back to is reviewed only when it is Git for Windows' own (when `git` resolves to Git's `mingw64\bin`, as from Git Bash).

**Why.** The review reproduced each defect: a modified or historical real backend was accepted as a stand-in; Python and shell children inherited the markers but not the restrictions; a test dropped during collection let its module pass; a child that never wrote its first record left no obligation; malformed rows raised or were ignored with exit 0; private paths were hashed before the privacy rule applied; ambiguous imports resolved silently.

**Not authorized by this entry.** Phase 1A-2 stays on hold; the A5 lock, A6 grants, live delegation, authorized full execution, activation of the plan-only modes and the final evidence schema stay with 1A-2, 1A-3 and 1B. Native macOS verification of the R2 envelope is pending.

Signed: the owner (the R2 assignment, the continuation's decisions D-R2-1 to D-R2-5 and the recovery's decisions D-R2-6 to D-R2-10, via the planning chat); implemented and recorded by Claude Code (Opus 5.5).

## 2026-11-25 — v0.8.2 Phase 1A-1 R1: the independent review FAIL is remediated; location is never evidence of a synthetic run, the requested module or node is the scope, plans are admitted only as re-resolved, and routine accounting fails closed

**Decision.** Phase 1A-1 failed independent review (eleven confirmed findings). Revision 5's architecture stands; these contracts are corrected and now govern routine verification (GATE.md is the reference):
(1) **H1.** A maintained heavyweight entrypoint refuses inside routine verification wherever it lies -- this checkout, another checkout, a disposable or renamed copy (recognized by path suffix and by its bytes). The only exception is a reviewed synthetic gate fixture: a disposable tree inside the routine session's own basetemp, declared in `act-synthetic-fixture.json` (its own path and the SHA-256 of each stand-in), whose orchestrator is byte-identical to this checkout's; its acceptance and qualification launches start only declared stand-ins that are not a real runner's bytes. No `--mock` flag, ambient grant or blanket pytest privilege.
(2) **H2.** A routine launch is judged by the program actually started (`executable=`), its arguments, working directory and environment: data-only flags only in their reviewed position; Python by script, `-m` module and inline path literals; nested pytest only through `routine_pytest.py`; shells by what they run; a Python or shell child whose environment drops the marker, the marked checkout or the ledger, or re-adds an opt-in, is refused unless the guarded runner's reviewed process profile vouches for it; installers, network tools, desktop hand-offs, machine-configuration programs and unreviewed native programs are refused.
(3) **H3.** `routine_pytest.py` and `guarded_pytest.py` share one early setup (`routine_effects.bootstrap`) before pytest is imported; the guarded runner's stronger hooks run first and its lifetime report carries the routine accounting. Operation checks: non-loopback sockets, a model library reading real weights, native-input resolution outside the gate's adapter, `os.startfile`, and the gate's own heavyweight callables (`check_operation`). Raw `python -m pytest` is not a supported verification invocation.
(4) **H4, M1, M3, C1-C4.** Selectors are canonical repository identities before classification and guarded routing (case aliases resolved or refused, links refused, membership by `files/tests/<module>`); the requested module or node is the scope (withheld or missing requested items keep the plan INCOMPLETE; `requested-scope` reconciles executed node ids); admission re-resolves the plan from the authoritative request and compares (`execution_plan.admit`), plan fields are immutable; one contained no-follow inventory serves every reader; local-only privacy follows the filesystem's case rule and the index; a staged deletion with recreation keeps both facts; dependency uncertainty is a gap; every plan's candidate binds working bytes and is diagnostic only.
(5) **M2.** Each stage's effect ledger is a directory the gate initializes before the stage exists; every cooperating process writes its own record (start, refusals, end); a write failure is an accounting failure; a missing, empty, unreadable, incomplete or malformed ledger, or a stage without a completed session of its runner, is never clean. Expected refusals are scoped to their thread and named effects and grant nothing.

**Why.** The review reproduced each defect: a copied or foreign root ran where the original refused; `executable=`, replacement environments, module and shell forms bypassed classification; the guarded runner took the envelope only after pytest had loaded; a Windows case variant routed a guarded module into ordinary pytest; whole-module requests lost heavyweight nodes while reporting COMPLETE; a missing or empty ledger read as clean; the boundary trusted plan-supplied fields.

**Not authorized by this entry.** The A5 lock, A6 grants, live delegation, authorized full execution, activation of the plan-only modes and the final evidence schema stay with 1A-2, 1A-3 and 1B. Native macOS verification of the R1 envelope is pending.

Signed: the owner (the R1 assignment and its approved mixed-module semantics, via the planning chat); implemented and recorded by Claude Code (Opus 5.5).

## 2026-11-25 — v0.8.2 Phase 1A-1: plan Revision 5 (A5-W, A5-M, A6-R, ENTRY; Phase 1A in three checkpoints); every gate request is an explicit execution plan; changed selection is read from Git and never widens; routine verification refuses heavyweight effects

**Decision.** (1) **Owner decisions recorded in plan Revision 5** (`files/plans/Developer-Experience-Upgrade.md`). **A5-W (Windows):** the heavyweight lock is a native, machine-wide OS primitive with machine-wide semantics; its durable recovery records live in one protected control directory inside the development checkout `C:\ACT-Dev` (a development location only); one authority is shared by every checkout on the machine; any failure fails closed; there is no checkout-local fallback; the details are Phase 1A-2's and no production control store exists yet. **A5-M (macOS):** a shared, developer-only lock location in a stable machine-common domain, adopted only after a native proof and the owner's approval of that exact location; a per-checkout or per-user location is not machine-wide; until then heavyweight verification on macOS stays blocked. **A6-R:** one authorization admits exactly one execution attempt of its named scope, platform and candidate within its expiry and budget; it is consumed on admission and never refunded by a failure, interruption or crash; agents never mint one (Phase 1A-2). **ENTRY:** every executable verification entrypoint is classified in `verification.json` `entrypoints` (active, maintained, obsolete, plus bounded fixtures and support tools) with its routine disposition and effects, and discovery fails a new unclassified one; obsolete entries are Phase 2 removal candidates. Phase 1A is delivered as 1A-1 (this entry), 1A-2 (heavyweight admission) and 1A-3 (execution of the plan-only modes); 1B is unchanged. The architecture spike report is kept as a sanitized historical copy, `files/plans/ASTRA-ARCHITECTURE-SPIKE-VERDICT.md`; it is investigation, not implementation evidence, and the plan governs.

(2) **Every request resolves into one explicit, immutable execution plan** (`helpers/execution_plan.py`) before anything runs, and `verify.py` validates it again at the execution boundary. Every collection defaults to empty and an empty collection selects nothing; only `--mode full` names the release partition. Six modes: quick, focused (`--test`, `--feature`), changed (optional `--base`), regression (repeatable `--component`, no unnamed or `all`), qualification (exactly one `--scenario` or a set of `--journey`) and full. A focused run never starts a journey; the old `--mode focused --journey` is refused with a migration message. In 1A-1 only `focused --test` executes as routine; `full` and `qualification --scenario` keep the interim owner-authorization rule; quick, changed, regression, focused `--feature` and qualification `--journey` resolve and print their plans only (exit 3) until 1A-3. `--plan` prints any plan and writes nothing. A plan that is not COMPLETE runs nothing.

(3) **Changed selection is read from Git and never widens** (`helpers/git_changes.py`, `helpers/selection.py`). The default anchor is HEAD (staged, unstaged and untracked work anywhere outside ignored roots); `--base REV` adds its merge base to HEAD; there is no `origin/master` default. Rename-aware NUL-delimited records, both rename paths, staged reversal kept, conflicts and unreliable bases refused, links never followed, local-only paths excluded by entry and count (a tracked one is a violation). Routing goes through the evidence ledger's import closure, built once per snapshot as a reverse index, plus the reviewed feature mapping and the policy's routes and static checks. An unresolved path, a parse failure, a deleted test, an over-budget module or suite-wide infrastructure is a selection gap that keeps the scope INCOMPLETE; `changed-conservative-full` and `changed.full_on` are gone.

(4) **Every pytest process of this checkout is a routine verification process** (`files/tests/routine_effects.py`, installed before pytest by `files/tests/routine_pytest.py` and by `conftest.py` for raw runs). Real-engine opt-ins and destination overrides are scrubbed and never grant anything; third-party plugin autoload is off; there is no `--mock` flag, no environment bypass and no "under pytest" grant. A test that reaches a real heavyweight boundary declares it statically (`ACT_EFFECTS`) and calls `routine_effects.require(...)`; routine plans withhold it (requested: INCOMPLETE; reached otherwise: a qualification obligation). Launches of classified heavyweight entrypoints of this checkout, real engine interpreters, installers, online installs and desktop hand-offs are refused before the process exists; the maintained roots refuse under the inherited marker themselves; `verify.py` refuses to execute a run against this checkout inside routine verification. Every refusal is recorded and fails its test and its run even when caught, in a child, or after the session. Markers and file names classify nothing.

**Why.** The spike found that the old `Selection` used `None` for "everything" and that changed runs widened to the whole suite and every journey; that routine pytest could open the real launcher window (`test_root_lifetime.py`), force-quit a real first-run window, load a real model through an inherited opt-in (`ACT_OMNIVOICE_P1_REAL`, `ACT_KOKORO_P2_REAL`) or start real GUI drivers; and that nothing classified the heavyweight entrypoints. Making the plan explicit and the refusal operational turns accidental heavyweight execution from routine paths into a fail-closed error, before 1A-2 adds the admission that can deliberately allow it.

**Consequences and seams (each removed by a later checkpoint).** An owner-authorized Windows full run cannot PASS until 1A-2: its ordinary stage runs inside the routine envelope, so the declared heavyweight tests in the release partition are refused (1A-2 admits an authorized run's stages). The plan-only modes execute from 1A-3. `selection.json` keeps its legacy keys beside `"format": "execution-plan/1"` until the 1B evidence schema. It is a cooperating-verification control, not an operating-system sandbox; the limits are in GATE.md.

**Not authorized by this entry.** The authorization store, any real grant, the machine lock or its control directory, durable recovery, process-tree delegation, run-wide deadlines, the final evidence schema, incremental requalification, the lean inventory, a skip-policy redesign, historical cleanup, uv or dependency changes, application changes; heavyweight runs; merging, tagging or releasing.

Signed: the owner (A5-W, A5-M, A6-R, ENTRY and the decomposition, via the planning chat); implemented and recorded by Claude Code (Opus 5.5).

## 2026-11-25 — v0.8.2 Pre-Phase 1A: the permanent development checkout is `C:\ACT-Dev` (D-1); the main application environment is always `.venv/` in the application root; A5 and A6 are approved in principle; historical documentation archival is approved for Phase 2 (DOC-1)

**Decision.** (1) **D-1 approved.** Real-environment development and verification of `0.8.2` happens in a dedicated Git clone at `C:\ACT-Dev` (short path, its own real root `.venv/`, no linked environment). It is an explicit exception to the earlier rule that project work stays inside the repository (2026-08-29 entry) and a development location only, not a requirement on ACT users: production code, launchers, packaging and user documentation never hard-code it. Project work, dependencies, environments and disposable artifacts otherwise stay in that checkout, subject to the previously approved narrowly scoped scratch exceptions (`%TEMP%\act-gate`). The old nested worktree `files/dev-work/wt082` and the owner's primary checkout stay as found; retiring the worktree is a later approved cleanup.

(2) **Fixed requirement: the main application virtual environment is always `.venv/` directly inside the ACT application root**, in development checkouts, GitHub source ZIPs and official release ZIPs, on Windows and macOS, with no dependency on `C:\ACT-Dev`. It is not open for redesign. Phase 3's nested-versus-sibling comparison (A1) concerns only the independent engine environments.

(3) **A5 approved in principle:** native OS-backed machine-wide heavyweight verification locking: a Windows named kernel mutex with appropriate machine-wide semantics; the macOS equivalent is evaluated in the Phase 1A architecture spike; any new persistent external lock artifact or location needs separate approval.

(4) **A6 approved in principle:** owner-issued, scoped heavyweight-verification authorization records bound to candidate identity, platform, permitted scope, expiry and execution budget; consumption, concurrency and trust-boundary semantics are defined in the Phase 1A architecture spike.

(5) **DOC-1 approved:** Phase 2 archives classified historical Decisions and Changelog entries into tracked per-era documents (`files/documentation-history/decisions/`, `files/documentation-history/changelog/`), keeps exactly five permanent documents in `md-instructions/`, keeps indexes, links and meaningful historical evidence, and keeps the protected local-only `files/Archives/` separate. Nothing is archived before Phase 2.

**Corrections from the Phase 0B independent review.** The Index of standing decisions above is a navigation aid, not a mechanism that automatically supersedes unlisted decisions: an entry stays in force unless it or a later entry says otherwise. Outstanding historical defects are reassessed for release relevance during the final independent review. `files/run-temp/` is untracked and unignored by an earlier owner decision, a staging hazard recorded for Phase 2.

**Why.** The nested worktree cannot run guarded or depth-sensitive tests (123-character root, no `.venv`, product link checks refuse a junction); a clone at a 10-character root can, as the earlier `C:\t\a82` clone proved. One predictable root `.venv/` keeps every distribution and launcher on the location they already assume.

**Not authorized by this entry.** Implementing the A5 lock, the A6 authorization records, any new verification mode or the archival; uv or any packaging change; heavyweight runs; merging, tagging or releasing.

Signed: the owner (decisions, via the planning chat); recorded by Claude Code (Sonnet 5.5).

## 2026-11-25 — v0.8.2 Phase 0B: Handoff and Briefing are compacted to current state with Git recovery; the Tay-mar requirement and D17 get a Decisions home; v0.8.1 is recorded as published

**Decision.** `md-instructions/Handoff.md` holds the current state only (an `## Execution Snapshot` of `- **Key:** value` lines in the shape the
owner's local `scripts/project-status.py` reads, work in progress, open issues and blockers, owner decisions, verification and evidence,
recent checkpoints). `md-instructions/Briefing.md` describes the application as it is (architecture, constraints, conventions) and separates
implemented architecture from approved future architecture, pending feasibility decisions and retired history. Everything else they used to
carry is recoverable and not repeated: the last pre-compaction commit is `85462005bc203e6b33fd975e2709fe3d9014b7b3`, so
`git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` and the same path for `Briefing.md` return the full documents
(2.7 MB and 200 KB). Decisions and Changelog are not rewritten; they gain navigation indexes only. A permanent plan-by-era split of Decisions
and Changelog is a proposal awaiting the owner's approval, not a decision.

**Why.** The Handoff had grown to 27,317 lines and the Briefing to 1,794: a new agent session could not orient without reading years of
development logs, and most open items were buried in superseded blocks. One authoritative home per durable fact, with Git for history.

**v0.8.1 is published.** The GitHub release `v0.8.1` was published 2026-11-21T05:45:50Z (2026-11-20 23:45 at the maintainer's UTC-6 clock) with
`AudiobookTool-Windows-v0.8.1.zip` and `AudiobookTool-MacOS-v0.8.1.zip`; the tag `v0.8.1` is the commit `6a7be7525222f93cd569b356e5467d270c971fe0`
on `master`. The macOS-only `0.8.0+macos.1` revision was never tagged separately: it shipped inside v0.8.1. Publication does not mean every
acceptance item passed: v0.8.1 shipped on the maintainer's recorded exception (no passing final canonical Full gate) and its not-qualified
list stands (`files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`). `VERSION` stays 0.8.1 until Phase 7.

**Open requirement: the pronunciation of Tamar (moved here from the Handoff so the compaction cannot lose it).** The maintainer requires that
the name Tamar be spoken "Tay-mar"; Chatterbox says "Ta-mar" or "Tay-Mar" inconsistently. This is **not solved and not claimed solved**. It is
deliberately not implemented as a word rule: it needs a separately designed, general pronunciation-override facility (entries such as
`Tamar -> Tay-mar`, with global and per-voice scopes) and a research spike that keeps two things apart: A, a deterministic override that can be
guaranteed per engine, and B, generation consistency, which cannot be fully guaranteed. Other observed names (for example Nephis and
Ascended) are evidence only and are never hard-coded. No engine carries a word-substitution table, and `files/tests/test_chatterbox_selected_tuning.py`
fails if any such token appears in executable engine code and fails if this requirement disappears from this document. Chatterbox pause and
rhythm tuning stays frozen at the maintainer's Phase 12 values; further tuning needs its own authorisation.

**D17 (macOS plan, recorded here because the plan may be retired in Phase 2).** Preemptible Cancel for the local engines: on macOS, Kokoro and Chatterbox (where offered) run
in the supervised local-engine worker under the Cancel contract C1 to C5; on Windows, Kokoro and Chatterbox stay in-process with
between-chunk Cancel exactly as released. Adopting the worker on Windows is a later decision with Windows qualification. The Developer
Experience Upgrade plan (Phase 5C) supersedes it for Kokoro and Chatterbox when Phases 5C and 5D land. D16 and D18 stay inside the 2026-11-18 P5 closeout entry.

**Consequences.** The Tay-mar pin in `test_chatterbox_selected_tuning.py` now reads this file (its meaningful requirement is unchanged). The
Decisions ordering breaks stay documented in the index above; no entry was moved.

## 2026-11-25 — v0.8.2 Phase 0A: five permanent documents, active plans in `files/plans/`, a local-only AI Workspace (D-5), v0.8.1 published (D-7), and an interim verification rule

Signed: the owner (D-5, D-7, the plan location and the interim rule, through the planning chat's Phase 0A prompt); recorded by Claude Code (Opus 5.5), HOME-PC. Plan: `files/plans/Developer-Experience-Upgrade.md` (Revision 3).
- **Documentation contract.** `md-instructions/` holds exactly `Briefing.md`, `Changelog.md`, `Decisions.md`, `Feature-Map.md` and `Handoff.md`, under those exact names, and nothing else: no case-variant alias, no missing document, no extra or non-file entry. Enforced by `verify.py` `docnames`, `files/tests/test_repository_contract.py` and `files/tests/test_plan3_boundaries.py`. Supersedes the exact-four contract, including P00B's "the four-document contract is unchanged". `Feature-Map.md` is an index; the detailed maps stay in `files/dev-work/feature-map/` and `coverage.json` stays the id authority.
- **Locations (ACT convention, overrides the generic workspace convention of plans in `md-instructions/`).** Active implementation plans: `files/plans/`. Protected historical archives: `files/Archives/` (local-only). Durable release qualification records: `files/release-history/`. Protected historical distributions: `dist/`. The Developer Experience Upgrade plan moved from `md-instructions/` to `files/plans/` by a tracked rename; no other active copy exists.
- **D-5: the AI Workspace is local-only.** The repository is public. `AI-WORKSPACE.md`, `AGENTS.md`, the root `CLAUDE.md`, `.ai/` and `.claude/` are gitignored and never staged, committed or pushed, not even temporarily; no public review branch carries them; no history rewrite. Review happens through a sanitized local bundle under `files/run-temp/`, never committed. The application and its tests must work in a fresh public checkout without them. This reaffirms 2026-07-08 (`AI-WORKSPACE.md` private), supersedes the plan's Revision 2 recommendation to track them, and supersedes P00B's "unignored" for `.ai/` only: `.ai/` is now ignored. `scripts/project-status.py` and `files/run-temp/` stay untracked and unignored as P00B decided.
- **D-7: v0.8.1 is published.** The planning chat verified the GitHub release `v0.8.1`, published 2026-11-21T05:45:50Z with `AudiobookTool-Windows-v0.8.1.zip` and `AudiobookTool-MacOS-v0.8.1.zip`. Phase 0B corrects the stale release statements; the version stays 0.8.1 until Phase 7.
- **Interim verification rule.** `files/dev-work/verification-gate/GATE.md` is the authoritative ACT verification policy. Until Phase 1A, ordinary implementation never starts `--mode full`, `--mode qualification`, `--mode changed`, `--mode focused --feature` or `--journey`: each can start native GUI journeys or the whole suite. Use `--mode focused --test` with named selectors, or guarded direct targeted pytest.
- **Why.** Public history cannot be un-published, so private files must never enter it. The Revision 2 checkpoint left the exact-four contract red with a plan in `md-instructions/`. The gate's routine paths reach the desktop.
- **Rejected.** Tracking the workspace files (Revision 2) or pushing them temporarily for review. Keeping plans in `md-instructions/` beside the permanent documents (Revision 2's five-plus-plans proposal). Installing the older local workspace template as if it were the owner's canonical version (it is not; see Handoff).

## 2026-11-25 — v0.8.2: an OmniVoice chunk with words that comes back empty is rendered again with further seeds derived from its own (24 renderings at most); never a pause, never another voice

Signed: Claude Code (Opus 5.5), HOME-PC, self-reviewed (not independently reviewed). Evidence: Handoff "v0.8.2 failed-chapter remediation"; `files/dev-work/v082-fc/` (ignored, local).
- **Decision.** In the worker, a chunk that has a letter or digit and whose rendering returns no samples is rendered again with the next seed of a fixed sequence the app derives from the chunk's own seed inputs (`derive_seed(voice, chunk, attempt)`), up to `SPEECH_RENDERINGS` = 24 renderings including the first. Attempt 0 keeps the released seed. Exhaustion fails the file as before, with the count. Cancel is checked between renderings.
- **Why.** The four failures are a deterministic property of (fragment text, seed): the model renders a two-letter cut-off word below OmniVoice's -50 dBFS silence threshold on some seeds (26 of 40 for the worst text) and keeps it on others. With a fixed seed a retry can never succeed; a different seed is the only change that leaves the words, the voice and every other chunk alone. 24 renderings put the worst measured text at about 3 in 100,000 and cost about 16 s on CUDA when a chunk never speaks.
- **Rejected.** A pause for the fragment (drops words the text contains; C1 allows it only for chunks with nothing to say). Merging short paragraphs into a neighbour or changing quotes in speech preparation (changes the plan, the seeds or the spoken text of every chapter with such a paragraph, so all their audio). Turning off OmniVoice's post-processing (changes every rendering; the fragment is still silence). Retrying other failures (an exception, out of memory or non-finite audio is not this condition). Adding a cause to the run Summary line (a shared, pinned contract; the technical cause is already in the Detailed log, the session log and `failures.jsonl`) — left for the owner.
- **Pipeline revision unchanged (1).** Only chunks that would have failed their file render differently; the eight neighbouring chapters regenerated on the fix are byte-identical to the production MP3s.

## 2026-11-22 — v0.8.2: Windows excuses the `files/dev-work/` "no colliding test basename" skip, and only that one

Signed: Claude Code (Sonnet 5.5), HOME-PC, self-reviewed. Evidence: Handoff "v0.8.2 Windows skip-policy reconciliation".
- **Decision.** Add one exact, anchored Windows skip rule (`windows-dev-work-local-fixture-absent`, max 1) for the reason "files/dev-work/ currently holds no colliding test basename".
- **Why.** In a clean clone `files/dev-work/` exists but holds no local test copies, so the isolation test's `dev-work` case cannot find a collision and skips by design (its docstring: a fresh clone must not turn the suite red). macOS already excused the reason; Windows did not, so the Windows Full gate reported an unexpected skip.
- **Not widened.** The `files/runtime-data/` twin stays under the existing generic rule; the Qwen3 absence is still not excused on Windows (macOS-only rule, owner decision Q2=A); no pattern was loosened and no production check changed.

## 2026-11-22 — v0.8.2 Windows qualification: Import Folder replaces only the Books the user agreed to replace; a Book changed while the import ran is kept and the replacement refused

Signed: Claude Code (Opus 5.5), HOME-PC, self-reviewed (not independently reviewed). Evidence: Handoff "v0.8.2 Windows qualification"; `files/dev-work/v0.8.2-qual-evidence/` (ignored, local).
- **The defect (reproduced on `5da1271`).** Import Folder asks "Replace the current Books?" (only when a Book holds work) at the press; the scan and, since Checkpoint 6, the reading of every file then run while the Books stay editable (Checkpoint 6 limit 6 recorded this for the owner). At completion the workflow's `import_folder` replaced whatever the workspace held, so a field typed, Chapter Titles pasted, a track moved or removed, or a Book added, duplicated or removed after the press was discarded silently. Reproduced in the MP3 Tool and the Metadata Editor (during the reading) and the M4B Maker (during the scan; no reading there): 13 of 13 "edit kept" cases failed on the unmodified tree.
- **Decision: a guard at adoption, not a lock and not a merge.** At the press each panel keeps the Books it was pressed to replace (`self._replacing = self.workspace.books`, after the confirmation and the folder chooser); at completion it commits any unreported Chapter Titles change (`flush_pending_editor_state`) and compares. Books are immutable values and every edit makes a new one, so the comparison is exact: equal → the replacement goes ahead exactly as before; different → nothing is replaced or added, every change stays, the import line and the Summary say "Import Folder: the Books were changed while the import was running, so they were not replaced and your changes were kept. Choose Import Folder again to replace them.", one warning dialog says the same, and the tool is free. Rejected: locking the Books for the whole (possibly multi-minute) import — the owner asked for a minimal guard over a long lock; a merge — a folder import is a replacement by contract and no merge is provably safe; asking a second time at completion — that would change Import Folder's established confirmation, which the owner asked to keep.
- **What is not a change.** Navigation (`select_book`/`next`/`previous` move the revision but keep the same Books), Shared fields (Shared Metadata is carried through a replacement by `_changed`), and an edit put back to the identical value. So the workspace revision is deliberately not the test: comparing it would refuse an import the user only browsed through.
- **Unchanged:** the confirmation and its wording, the coordinator and its pins, the workflows (`import_folder`, `add_files`), the readers, Add Files (a merge into the Book pressed on by id, or new Books; never a replacement), Cancel Import, Close, stale and failed readings. `shared/book_workspace.py` and `book_workspace_ui.py` exports are pinned, so the guard lives in each of the three panels with one shared sentence (`REPLACEMENT_REFUSED`, identical in the three modules; the tests hold all three to one string).
- **macOS standing.** Covered under `ACT.SHARED.WORKSPACE-SCALING` (contract and tests added), which stays `pending`, phase `P7`, by the owner decision; no macOS evidence is claimed.
- **Unchanged by owner decision.** No persistence feature (Save Job, autosave, workspace drafts, crash recovery, session restoration).

## 2026-11-22 — v0.8.2 Checkpoint 6: an import's files are read on a worker and the import ends when they are read; Book labels, Book numbers and list selection are linear; the activity log, job events and Cover's GIL window are measured and left alone; `ACT.SHARED.WORKSPACE-SCALING` is pending on macOS under the owner decision

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 6; `files/dev-work/v0.8.2-cp6-evidence/` (ignored, local).
- **The readback is part of the import, not a later fill-in.** After the shared coordinator commits a scan (unchanged), the MP3 Tool and the Metadata Editor read the committed files on one worker per import (`shared.source_readback.SourceReadback`, Tk-free, read-only: it calls only the readers it is given) and only then call the **unchanged** workflow functions (`import_folder` / `add_files`) with lookups of what was read. Considered and rejected: adding Books at once with observations "pending" and filling them in later. That would put Books in the workspace whose sources are not observed, so every reader of the store (page prefill, mixed markers, Book labels, the planners' readability, Start) would need a pending state, and a half-read workspace could be frozen into a run. With the chosen design no Book exists until its source was read, so processing cannot accept an incomplete observation, and nothing downstream changed.
- **While the files are read the import is still running.** The import line shows "Reading tags… N of M files" (Editor: "Reading tags and chapters…") with Cancel Import; Import Folder, Add Files and Clear All Imports are refused as during a scan, and so are the MP3 Tool's Write ID3 Tags / Combine (as during a scan already) and the Editor's three actions (new: the Editor's actions were not gated on a scan, and are not now; only on the reading, whose Books do not exist yet). Navigation and editing stay available, exactly as during a scan; a folder import then replaces the Books as it always did when the scan committed.
- **Cancel Import, Close, stale and failed readings.** Cancel Import while reading drops the reading at once ("The import was cancelled and nothing was added.", the coordinator's own wording) and the worker stops after the file in hand; Close cancels it. The panel adopts only the reading it is waiting for, and only when it finished uncancelled; a cancelled reading never reports finished. A worker that ends without reading everything (it should not happen; a reader's own exception is an answer, kept for the lookup) marks the reading failed, and the panel says "The files could not be read, so nothing was added." A worker that cannot be started leaves the reading to the Tk thread, as v0.8.1 did.
- **Same observations.** Each distinct path is read once with the readers the workflow would have used (MP3: the panel's `reader`; Editor: `m4b_metadata_workflow.source_readers()`, the two defaults of `observe_source`); a reader's exception is re-raised by the lookup as the same object, so `observe_source`'s "readable=False" and error text are the synchronous path's. The import's summary line and problem lines are logged after the Books are made, in their old order.
- **MP3 Add Files keeps its target by identity.** The Book Add Files was pressed on is remembered by id; if the user moved to another Book while the tags were read, the files still go to that Book and the page the user is on stays showing; a target removed meanwhile receives nothing and the log says so. A pasted Chapter Titles edit is committed before the import is applied (the existing flush), so nothing typed is lost or moved.
- **Linear rendering.** `_assign_book_numbers` (MP3, Maker, Editor) filtered with `book_id in <list>`: quadratic on every render. It uses a set. The Editor's selector label (`display_hint`) built all seven of a Book's page values for every Book on every render; it now takes the Title alone through the same rule (`_page_value`, which `page_values` also uses; same values, same contract errors). The MP3 Tool and M4B Maker skip refilling a Book's track list when the very same immutable track snapshot is already shown and no selection was asked for, which also keeps the user's track selection through a Shared keystroke; moves, removals, navigation and imports redraw as before. The shared imported-file list (TTS, Converter, Cover's importer) built a set per row when selecting; it builds one, and sets the selection one run of rows at a time; Cover Image's own browser did the same when painting a selection (`CoverBrowser._paint_selection`) and builds one too.
- **Linear projection.** MP3 Tool's folder import seeded each new Book with its own `replace_book` call, each rebuilding the whole workspace (quadratic in Books: 4.2 s on Tk for 5,000 one-file folders). It now builds one snapshot whose value is exactly the loop's, revision included: an unchanged Book keeps its object and moves no revision (`replace_book`'s no-op rule), every seeded Book advances it once. `replace_book` stays the operation for single edits; there is no new shared bulk operation (the change is local to the MP3 model, and the Plan 6 guard that the model reuses `replace_book` still holds). The Metadata Editor's Add Files found the Books that give way with `book not in kept` (12.5 million field-by-field comparisons beside 5,000 Books); it uses the exact complement of `kept`'s own test.
- **Measured and deliberately not changed.** (1) Summary/Details log: an append costs about 0.5 ms and grows to about 0.8 ms at 20,000 lines; switching panes and Clear Log about 1 ms; nothing to fix, and no history is trimmed or hidden. (2) Job event drains re-project the whole event history (`project_summary`, `detail_lines`) each tick: 8–25 ms at 4,700–13,000 events, largest 32 ms; linear, within the target at the checkpoint's workloads, so no incremental projection was added. (3) Cover Image's 5,000-image heartbeat gap during standard preparation (93–143 ms in Checkpoint 5): the window is GIL hand-off while the shared planner's pure-Python `_finish` runs on the worker; there is no Cover-local yield point inside it, and the remedies (a chunked shared `_finish`, all six tools; or the interpreter's switch interval, ruled out by the owner) are outside this checkpoint. (4) Replace original files' validation on Tk before its confirmation: unchanged by owner direction. (5) Add Files validates the chosen paths on Tk inside the coordinator's synchronous `import_files` (about 0.1 s per 1,250 files); unchanged. (6) A finished folder scan is committed to the shared manager on Tk (`import_coordination`, untouched and pinned by `test_plan3_boundaries`): about 0.1–0.13 s at 5,000 files in every list tool, the same before and after. Moving either of these off Tk means changing the shared coordinator's commit protocol for all six tools, which is outside this checkpoint.
- **Unchanged:** the coordinator and its pins (`import_coordination.py` not touched), the readers themselves, observation contents, chapter timestamps, editing semantics, Book identity and order, output naming, no-clobber publication, frozen snapshots and every preparation protocol (no consolidation, as directed).
- **macOS standing.** `ACT.SHARED.WORKSPACE-SCALING` was built and tested on Windows only; it is recorded `pending`, phase `P7`, `"source": "owner decision, not the census"`. Nothing claims macOS evidence.
- **Unchanged by owner decision.** No persistence feature (Save Job, autosave, workspace drafts, crash recovery, session restoration); no merge, tag, release or Full gate per checkpoint.

## 2026-11-21 — v0.8.2 Checkpoint 5: the M4B Converter checks its outputs against one input index per plan and per attempt; Cover Image's standard Start prepares on its own worker; the source-side modes are unchanged; `ACT.COVER.PREPARATION` is pending on macOS under the owner decision

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 5; `files/dev-work/v0.8.2-cp5-evidence/` (ignored, local).
- **Converter: one authoritative input index per plan, one per attempt.** `m4b_plan.assemble_plan` builds one `shared.output_paths.InputIndex` (Checkpoint 1's, unchanged) over **every** frozen occurrence, usable or not, in queue order, **before** `reserve()`; `m4b_destinations.plan_outputs` takes it as an optional `inputs=` (without it, it builds one from its own entries, so its standalone contract is unchanged) and `assemble_plan`'s final check uses the same index. The worker builds one more per attempt for execution, and `m4b_execution.convert_segment` takes it as an optional `inputs=` (without it, the one-shot guard over `sources` runs as before; the Converter is its only production caller). Same key (`_input_key`), same refusal text and detail (the first input in queue order with that key). Two consequences, both on the refusing side only: a destination equal to an *unusable* book's file is now refused inside `plan_outputs` rather than one step later in the final check (same exception, same text, same detail; the plan fails either way), and an input that cannot be normalised refuses the plan before a run folder is reserved instead of after. Kept: both plan-time checks (redundant by construction now, kept as defence in depth, linear) and the execution-time check (a per-attempt snapshot of the inputs, never global, dropped with the attempt; publication stays no-clobber).
- **Rejected for the Converter:** moving its planning or making it cancellable mid-plan. Planning already runs on the Converter's worker after preflight; after this change 5,000 outputs plan in 5.4–5.9 s (the shared planner's containment and link checks, linear). No worker architecture change was needed.
- **Cover Image: the TTS pattern, kept inside the panel.** A standard-output press validates (list, typed size) and freezes the run on Tk exactly as before, takes `shared_config.get_effective()` once, shows "Preparing job…" with Cancel (Pause disabled), locks list and options through the lock matrix and returns; one short-lived `cover-prepare-N` worker (`prepare_run`, module level, no panel) waits up to 0.25 s for the press to be painted, reserves with that configuration and plans with the unchanged `plan_destinations` (new optional `checkpoint=`, called once per image through the rename hook; names unchanged); the panel's existing worker-queue drain adopts it. Unlike TTS, the worker's messages ride the panel's one worker queue (`PREPARATION_MESSAGE` on `_log_q`) and the paint gate is released by that drain's first tick after the press (it flushes Tk's pending redraw with `update_idletasks`, then sets `painted`), not by an `after_idle`: Cover's standing pins say the panel registers exactly one drain and schedules no callback of its own, and those pins were kept rather than relaxed. `_Preparation.offer / adopt / withdraw` decide under one lock (exactly one side releases a reservation; an unadopted plan is released by a `cover-release-N` worker, never on Tk). The worker uses the panel's existing `thread_factory` seam (the importer's), defaulting to daemon threads. This is a fourth copy of the offer/adopt/withdraw protocol (MP3 Tool, M4B package, TTS, Cover); consolidation stays the recorded follow-up.
- **The source-side modes do not prepare.** Numbered copies and Replace original files reserve nothing and plan nothing at Start (measured: numbered 56 ms at 5,000), so they keep the synchronous launch. The replacement's validation and its confirmation dialog stay on the Tk thread, in the same order, asked from the same one place; no worker can reach a replacement. **Measured and not changed:** validating every source before the confirmation takes 0.58 s at 2,341 and 1.24 s at 5,000 on Tk, immediately before the modal dialog. Moving that validation would change the destructive path's gate; left for an owner decision.
- **Build, swap, retire for the Cover job area.** `_install_jobs` builds the new adapter completely while the previous one is live (registering list and options after its own render, as TTS does) and raises `_AttemptNotStarted` with nothing changed if it cannot; `_launch` creates the controller and reporter first and commits the attempt's state (destinations, output folder, snapshot, result, attempt number) only after the swap. A numbered, replacement or retry attempt whose job area cannot be built says "Resize not started" and changes nothing. After the swap, a resize worker that cannot start settles the attempt FAILED (`_settle_unstarted`, never retryable) and an adopted standard run's empty folder is released.
- **The Cover resize worker's per-image input check** uses one `InputIndex` of the attempt's files, built lazily at the first image that asks and inside that image's own error handling (a failure to build it fails images exactly as the one-shot check's failure did). Replacement never asks (it writes over its own validated source by design).
- **Unchanged:** names, collision numbering, containment and link checks, no-clobber publication, HEIC capability handling, decoding and image quality, thumbnails, chapter timing, frozen retry destinations, the shared `DestinationPlanner` (Checkpoint 3's resume kept; no shared planner change in this checkpoint).
- **macOS standing.** `ACT.COVER.PREPARATION` was built and tested on Windows only; it is recorded `pending`, phase `P7`, `"source": "owner decision, not the census"`, under the 2026-11-21 owner decision's rule for features added on Windows after the census. Nothing claims macOS evidence.
- **Unchanged by owner decision.** No persistence feature (Save Job, autosave, workspace drafts, crash recovery, session restoration); no merge, tag, release or Full gate per checkpoint.

## 2026-11-21 — v0.8.2 Checkpoint 4: TTS Start prepares on its own worker; the job area is built before it is swapped; the shared import list sends a lock to Tk only when it changes; the three `*.PREPARATION` features are pending on macOS by owner decision

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 4; `files/dev-work/v0.8.2-cp4-evidence/` (ignored, local).
- **The MP3/M4B pattern, kept inside the TTS panel.** The press validates, checks the voice (Install & Continue unchanged), freezes the run and takes `shared_config.get_effective()` once, on Tk; one short-lived `tts-prepare-N` worker (`prepare_run`, module level, no panel) reserves with that configuration and plans with the unchanged `plan_destinations`; the pump's preparation drain adopts it. `_Preparation.offer / adopt / withdraw` decide under one lock (exactly one side releases a reservation; an unadopted plan is released by a `tts-release-N` worker, never on Tk). Rejected: importing `m4b.m4b_preparation` from the TTS panel (a TTS-to-M4B package dependency; its endings carry no dialog title and its result no run snapshot) and moving it to `shared/` now (it would touch both M4B panels and add a shared module for a checkpoint about TTS). So the repository holds three copies of the protocol (MP3 Tool, M4B package, TTS); consolidating them into one shared module is a recorded follow-up, not done here.
- **The worker asks the voice question once more.** Planning can take seconds; a voice whose files went away meanwhile is refused before adoption ("Voice unavailable"), with nothing reserved left behind. The question is `voice_readiness(entry, **seams)`, a pure function bound to the panel's seam callables (never the panel), and `_voice_status` now calls the same function.
- **Cancellation granularity.** `plan_named` gained an optional `checkpoint` called once per source in each of its two passes; it changes no name (test: identical plans with and without it, called 2N times). Cancel is acknowledged at once ("Cancelling preparation…"); the panel frees itself when the worker reaches its next file, so a single hung filesystem call holds only the preparation, never Tk. The shared planners' end-of-pass `_finish` (about 0.27 s at 5,000 files) has no checkpoint; not changed (shared code, all six tools).
- **Build, swap, retire for the TTS job area** (the MP3 Tool's R1 order). `_install_jobs` builds the new adapter completely while the previous one is live and raises `_AttemptNotStarted` with nothing changed if it cannot; `_launch` commits the attempt's state only after that. After the swap, any failure up to the conversion thread's start settles the attempt FAILED through its own controller (`_RunContext.settle_unstarted`, no containment step because nothing ran).
- **Two Tk costs that remained on the press, removed.** (1) Start re-measured the whole layout (`_content_changed`, seven `update_idletasks`, about 0.2–0.3 s) even when the voice message had not changed; it now re-measures only when the message appeared, changed or went away. (2) A Tk `Listbox` re-measures every row when it is configured: the import list's lock cost about 40 ms per call at 5,000 files and an accepted run flipped it three times (lock at the press, unlock when the new job area rendered idle, lock at its first state). `ImportedFileList.set_locked` (shared) now sends the state to Tk only when the widget shows another one, and a run's job area registers the queue and options after its own renders, so its first state change is the first lock it applies. The construction-time job area renders once more after registering, exactly as before.
- **Measurement method.** The 20 ms `after` heartbeat is measured on `mainloop()` with Windows timer resolution set to 1 ms (`timeBeginPeriod(1)`, the harness only): at the default 15.6 ms quantum an idle panel's largest gap is already about 63 ms and every figure is a multiple of 15.6 ms. Default-resolution figures are reported beside the 1 ms ones; nothing is excluded from the window (press, paint, planning, adoption, first events).
- **Rejected after measurement:** a per-file `time.sleep(0)` in the worker (no measurable effect at 1 ms resolution) and a shorter interpreter switch interval (diagnostic only: 1 ms changed nothing).
- **macOS standing of the `*.PREPARATION` features (owner decision 2026-11-21).** `ACT.MAKER.PREPARATION`, `ACT.METADATA.PREPARATION` and `ACT.TTS.PREPARATION` were built and tested on Windows only. coverage.json's macOS block now records each as `pending`, phase `P7` (the macOS release qualification), with no test counts and `"source": "owner decision, not the census"`; the block's `about` names this exception. Nothing claims macOS evidence; their Windows standing is unchanged.
- **Unchanged by owner decision.** No persistence feature; no merge, tag, release or Full gate per checkpoint.

## 2026-11-21 — v0.8.2 Checkpoint 3: the shared collision search resumes per sequence inside one planner; names unchanged; TTS Start still plans on Tk

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 3; `files/dev-work/v0.8.2-cp3-evidence/` (ignored, local).
- **Resume, not a new allocator.** `DestinationPlanner.plan` / `plan_directory` keep, per instance, the index where each numbered sequence's last search ended, keyed by kind (file or folder), the exact folder text, the exact sanitised name and the first index (so `start_index` 0 and 1 share one sequence, a higher start has its own). Every index skipped was found taken or occupied by this planner, and `_taken` only grows. Nothing else changed: same sanitiser, containment, link check, case-insensitive taken-set, disk check, suffix format, bound and refusal text. Rejected: a TTS-specific naming service, a cache keyed by casefolded names (exact text cannot be wrong whatever casefolding does), memoising disk answers across planners.
- **The one behavioural difference, accepted.** A name occupied on disk when its index was tried, and freed later in the same planning operation, is not offered again; the restarting search would have offered it. Only ever a later number; publication is no-clobber in every tool. A name that appears on disk during planning is still avoided (each untried index is checked when tried).
- **`plan_named` left as it is.** Its folder-finding pass gives every source the same placeholder name; with the resume that pass is linear too, so `output_names.py` is unchanged.
- **Not done here (measured, recorded for Checkpoint 5).** TTS Start still plans on the Tk thread; after this change the press is linear at 1.6–2.4 ms per file, almost all of it the containment and link checks (`assert_contained`, `_relative_parent`) that both passes run for every file. Moving TTS preparation off Tk, as the MP3 Tool and M4B tools now do, is the fix; it is a panel redesign, not a collision change.
- **Pre-existing, flagged for the owner, not changed:** `_is_free` treats a dangling Windows junction as free (`exists` and `is_symlink` are both False); such a numbered name is planned and its publication refused (`DestinationOccupied`). Changing the occupancy test would change allocations.

## 2026-11-21 — v0.8.2 Checkpoint 2: the M4B Maker and Metadata Editor prepare on one shared, Tk-free preparation worker; their Plan 6 capture is taken there; the worker lets Tk paint the press first

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 2; `files/dev-work/v0.8.2-cp2-evidence/` (ignored, local).
- **Index, as in Checkpoint 1.** Both planners build one `InputIndex` per plan; the one-shot `assert_not_input` is no longer called by them (the Converter and Cover still use it until their own checkpoint). Plans are unchanged (parity tests).
- **One shared hand-off module.** `scripts/m4b/m4b_preparation.py` holds the preparation's offer / adopt / withdraw decision, its cooperative Cancel and the worker body, for both panels, as `m4b_staging` already serves both. It imports no Tk. Rejected: copying the MP3 Tool's private `_Preparation` into each panel (three copies of an ownership protocol whose whole value is being one decision under one lock).
- **The capture moves to the worker.** Checkpoint 1 took the MP3 Tool's capture on Tk because the shared capture documents itself as "on the caller's thread, before any worker exists". Measured here, at 5,000 Editor files the capture alone was about 100 ms of the press (one `RunSnapshot` per file) and the largest heartbeat gap after the press 139–167 ms. The capture is a pure function of the immutable workspace snapshot, the immutable observation store and the lock-guarded `IdFactory`; it reads no disk, and the Editor's readability predicate reads only that frozen store and is never stored. So `plan_run` takes it on the preparation worker, synchronously, before any processing worker exists, which is where `ffd1621`'s `plan_run` took it too (then on Tk). Rejected: keeping it on Tk and batching it across `after` calls (two places to freeze one press; the workspace could change between batches).
- **Paint first.** The worker waits up to 0.25 s for an idle callback scheduled by the press before reserving. Measured: with the worker planning at once, the repaint after the press took 105–117 ms at 5,000 files, and with `gc` disabled it still took 96–132 ms; with the worker parked, 15 ms. So the cause is GIL contention, not collection. Rejected: starting the worker from `after_idle` (a press that returns before its worker exists makes Close and thread-start failure two more states); `sys.setswitchinterval` (process-wide).
- **Per-run staging locks.** Each run gets its own `threading.Lock` instead of one panel-wide lock, so removing a superseded run's kept staging on a release worker can never make Tk or the new run wait. The lock still orders that run's worker against Tk (ACT72-031).
- **Unchanged by owner decision.** No persistence feature (Decisions 2026-11-21); no merge, tag, release or Full gate per checkpoint.

## 2026-11-21 — v0.8.2: no persistence feature for the MP3 workspace; the guarantee is responsiveness and kept edits within the running session

Signed: the owner's decision (Checkpoint 1 R1 instructions, 2026-11-21), recorded by Claude Code (Fable 5.2), HOME-PC.
- **Decision.** NO Save Job, NO autosave, NO workspace drafts, NO crash-recovery feature, NO session restoration. Nothing of the kind is to be introduced on `0.8.2`.
- **What is required instead.** Normal UI actions, large-job preparation and processing must not silently lose an in-memory edit or freeze the window. Editor state stays memory-only and ends with the application.
- **Effect.** Item 5 of the v0.8.2 scalability backlog (large-workspace recovery / draft persistence) is withdrawn. The long-running-branch decision below is unchanged: no merge, tag, release, deadline or automatic Full gate per fix.

## 2026-11-21 — v0.8.2 Checkpoint 1 review remediation R1: one editor commit boundary; a build / swap / retire job-area swap; one configuration snapshot; a capture must match its workspace; unused runs are released off Tk

Signed: Claude Code (Opus 5.5, then Fable 5.2), HOME-PC. Evidence: Handoff, the R1 block; the two Codex reviews (ignored, local). Verdict on the commit is a self-review by the owner's choice of a single-agent completion; it is not an independent PASS.
- **Editor commit boundary.** `flush_pending_editor_state` is the one place a Chapter Titles change enters the model outside a key release. It is bound to the Book the box shows (identity, not "current"), called first by every callback that asks the model for a change, and repeated inside `render` / `_render_chapters`, the only writers of the box, as the safety net. Rejected: relying on `<<Modified>>` alone (queued, so a callback can run first; kept as an addition); making `workspace` a flushing property (hidden Tk reads on every access); committing only at Start and navigation (the Checkpoint 1 state, which the review broke with a Shared edit).
- **Job-area swap.** Build the new adapter completely, switch by assignment, then retire the old one as cleanup that can no longer affect ownership. "Nothing changed hands" is decided by `self.jobs is retired`, which is only sound because the previous adapter is untouched until after the switch; the first R1 version closed it first and the re-review showed the consequence (a closed adapter treated as live). A constructor must not leave a drain or a frame behind, so `JobAdapter.__init__` rolls back its own failure in the shared module rather than each caller reaching into the pump. Rejected: a new lifecycle framework; restoring a closed adapter; retrying a failed destroy.
- **After ownership transfers.** A failure settles the accepted run through its own controller (`_fail_unstarted`); a previous run's result is never restored at that point because its job area is gone. The replaced run's kept staging has no ordering constraint and goes to a release worker; the unstarted attempt's own staging is released before its terminal event, on Tk, because a later Retry Failed relies on that order.
- **One configuration snapshot.** Read once at the press and used for the capture and the reservation. The panel's construction-time configuration is kept for importing only. Rejected: using the injected construction-time configuration for the run (it is the import seam, and it is stale by the time of a press).
- **Capture validation.** `plan_run` checks a supplied capture against the workspace by value (Shared Metadata, Book membership and order, files, effective options), linear in the tracks. Rejected: a single frozen "preparation input" type replacing the two arguments (a wider API change than the finding needs).
- **Releasing an unused run.** A short-lived worker per release, exactly one owner per reservation (decided under the preparation's lock), no dependence on Tk or the pump. If no worker can start, the empty folder is left and reported rather than making Tk wait.

## 2026-11-21 — v0.8.2 is a long-running development branch: daily-use fixes accumulate on `0.8.2`; nothing is merged, tagged or released per fix

Signed: the owner's decision (Checkpoint 1 instruction, 2026-11-21), recorded by Claude Code (Opus 5.5), HOME-PC.
- **Decision.** Branch `0.8.2` (from the published v0.8.1 `6a7be7525222f93cd569b356e5467d270c971fe0`) is for extended real-world testing and iterative remediation. Every defect found in daily use is fixed on this same branch as a focused checkpoint: commit, push `origin/0.8.2`, independent review, then the owner keeps testing. Checkpoints are development steps, not release milestones.
- **Not done per fix.** No merge into `master`, no `v0.8.2` tag, no GitHub release, no automatic Full gate, no release deadline, and no replacement of the installed v0.8.1, which stays available as the rollback. The application identity stays `0.8.1` until a release decision.
- **Backlog.** The ordered v0.8.2 scalability backlog lives in the Handoff (Checkpoint 1 block).

## 2026-11-21 — v0.8.2 Checkpoint 1: MP3 jobs are prepared on their own worker from an input index built once per plan; the run starts when Tk adopts the plan

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence: Handoff v0.8.2 Checkpoint 1; Codex's root-cause handoff (ignored, local).
- **Cause.** Both MP3 buttons reserved and planned inside the Tk callback, and the planner re-resolved every source for every destination (2N² resolutions; 20 minutes at 2,341 tracks).
- **Index.** `output_paths.InputIndex` normalises one operation's inputs once and answers exactly as `assert_not_input` (same key, fallback, casefold and refusal). Rejected: a process-wide resolve cache (stale across jobs and filesystem changes; Codex measured that caching the resolver alone still froze for 193 s at 5,000), and removing checks. The one-shot guard stays for the other tools until their own checkpoints prove the index there.
- **Thread boundary.** The press stays on Tk for edit commit, validation, the Plan 6 capture (documented as taken on the caller's thread) and freezing; a preparation worker reserves and plans; the pump adopts; then the existing `_start_attempt` creates the one `JobController` and the one processing worker. The preparation is not a controller: Cancel is its own event raised through the shared `ConversionCancelled` at checkpoints. Rejected: Codex's alternative of the same worker continuing into the engine after a FIFO or acknowledgement handshake, because (1) the owner's instruction is to start the conversion worker only after Tk adopts a successful plan, (2) a worker waiting on Tk deadlocks the suite's inline thread factories, and (3) keeping the previous job area untouched until adoption is what lets a refused or cancelled preparation restore Retry Failed with one re-render. Never more than one worker runs at a time: the preparation has posted its final message before the processing worker exists.
- **Ownership.** The preparation worker owns its reservation until `_Preparation.offer` succeeds (once only); then the panel adopts or withdraws it. Every path releases a never-adopted run with `release_if_empty`, never recursively. The previous run's kept staging is released by the new run's worker (no staging lock: nothing else owns that abandoned plan), so a failed or cancelled preparation never destroys it.
- **Deferred.** The shared `DestinationPlanner` identical-basename suffix search stays O(k²) (23.8 s at 2,341 identical titles with numbering off); changing it affects all six tools and belongs to backlog checkpoint 3 with cross-tool proof.

## 2026-11-20 — v0.8.1 Checkpoint E: on Aqua the four outlined role styles draw a same-size outline image element; every other Aqua control stays native

Signed: Claude Code (Sonnet 5.5), HOME-MacOS. Evidence: Handoff v0.8.1 Checkpoint E; ignored `files/dev-work/macos-e/`.
- **Cause.** Aqua draws `Button.button` with Cocoa and ignores ttk `bordercolor` and `background`; a role style could only recolour the text, and `style.lookup` reported colours that never showed. Measured before changing anything (five identical native buttons in Light and Dark).
- **Decision.** Only the red, green, yellow and blue styles replace `Button.button` with a ttk `image` element drawn from the palette (1 px role outline, neutral body, transparent margin, focus halo), with the native request size (label + 40 x 28). Rejected: cloning clam's `Button.border` (square corners, and 6 px taller than native); classic `tk.Button` (changes widget classes and state handling); a custom widget (a framework this patch does not need). The neutral `button` role stays Cocoa, so ordinary buttons keep native look, press and Dark behaviour.
- **Consequence.** The image is 1x, so edges are slightly soft on Retina. Images are redrawn in place on a theme switch; a Tk image finalised behind the module's back is rebuilt under a new element name (`CompactAqua.<role>.button.<generation>`) because ttk cannot redefine an element. The Windows styles and palette are unchanged.

## 2026-11-20 — v0.8.1 Checkpoint C1: an OmniVoice chunk with nothing to say whose rendering is trimmed to zero samples is a 0.2 s pause, not a failure; a chunk failure names its chunk and worker batch and keeps a technical record

Signed: Claude Code (Opus 5.5), HOME-PC. Evidence-driven: Handoff v0.8.1 Checkpoint C1; private evidence in `files/dev-work/v0.8.1-c1-evidence/` (ignored).
- **Cause.** A paragraph of only "..." (or a lone U+FFFD) is its own chunk. OmniVoice renders it as under a second of near-silence; for about one seed in five all of it is below -50 dBFS, and OmniVoice's own `postprocess_output` removes all of it as silence and returns no samples. The worker rightly refused empty audio, which failed the whole chapter (all 80 failures of the owner's mass test).
- **Decision.** In the worker, only when the chunk has no `str.isalnum()` character AND the model returned exactly 0 samples, the chunk becomes 2 x `pad_duration` (0.2 s) of silence: what OmniVoice's `fade_and_pad_audio` puts around every non-empty rendering, i.e. "trimmed to nothing, then padded". The chunk event carries `silent`; the run log says so; the parent fails the file if a `silent` chunk has words (one rule: `speakable` is the worker's own, imported by `omnivoice_synth`).
- **Rejected.** Retrying with another seed (a blind retry; breaks "same chunk, same seed, same audio"). Turning off `postprocess_output` or changing its threshold (changes every approved rendering; upstream code). Merging or dropping letterless paragraphs in the shared planner (also Qwen3's; shifts chunk indices and so every later seed, changing chapters that already succeeded). Treating any empty rendering as a pause (would hide lost words).
- **Why it is safe.** Only chunks that used to fail their whole file change; every other rendering is bit-identical (a control chapter's MP3 is byte-identical to the production output). `PIPELINE_REVISION` stays 1: no audio that could have been produced before changes.
- **Diagnostics.** The failure message ends "(chunk N of M, worker batch B of K)", so the session log keeps it per failure. `last-failure.txt` and one line of the bounded `failures.jsonl` (1 MiB, then `failures.previous.jsonl`) keep the technical record: chunk identified by index, batch, position, length, SHA-256 and seed, never its words. The worker adds position, timing, the returned shape and GPU memory to its `failed` event; a figure it cannot measure is left out rather than replacing the failure.

## 2026-11-20 — v0.8.1 Checkpoint B: outlined semantic button roles are one shared style set plus a stable action-to-role map; a role colours the text and the border only, never a fill

Signed: Claude Code (Sonnet 5.5), HOME-PC. Implements the owner-approved 146-control matrix (roadmap `files/plans/ACT-v0.8.1-Implementation-Roadmap-DRAFT.md` Appendix A); it is not an owner acceptance of how the result looks.
- **Where the code lives.** `shared/appearance.py`: four styles `Compact.Red/Green/Yellow/Blue.TButton` built from one loop, palette tokens `role_red/green/blue` (the existing danger/success/accent colours), `role_yellow`, and two neutral greys `role_hover`/`role_pressed`; `BUTTON_ACTION_ROLES` (stable action key -> role) and `button_style_key()` (a role, a role letter or an action; an unknown name raises, so a control can never fall back to plain by accident). `job_ui.action_style(theme, action)` is what shared code and the panels call; it returns `""` for a bundle with no styles (native) and the plain `button` style for the shell's `ACT.*` bundle, which no tool panel uses. Panels, shared components and dialogs pass an action (`cancel`, `run`, `pause`, `book_add` ...), never a colour.
- **The fill rule.** Background is neutral in every state: resting `surface`, hover `role_hover`, pressed `role_pressed`, disabled `field_disabled`; the default-button cue (`alternate`) and focus change nothing. Text and border are the role colour in every live state, 4.5:1 or better on all three backgrounds in Light and Dark. Disabled uses the neutral disabled text and border. Focus keeps the role border (not the blue focus border the plain button shows) and the focus ring is drawn in the neutral text colour, so a red, green, yellow or blue button is never mistaken for a different role when focused. The plain button (role E) is untouched, including its soft-blue hover.
- **Danger.** The old `Compact.Danger.TButton` filled danger-red on hover and press; it no longer exists. `danger_button` and `primary_button` remain as names for the red and green roles so existing callers keep working. `Primary.TButton` (accent fill) is gone; the only users were Preferences (Save is green, Review Selection blue, the two Continue buttons normal).
- **Interpretations recorded (the matrix is names, the code has widgets).** The row "Install & Continue" is the dialog's one affirmative button, the same widget as "Install Selected Components" (both B). "Previous Book" is the live "◀ Previous". The Cancel Import row is the shared status bar's in every tool. Every row is bound to a live widget by `button_role_inventory.audit`, which also fails on any button under a panel that the inventory does not list.
- **Not in the matrix, left normal until the owner classifies them:** the first-run wizard's own Begin Setup, Cancel and Close; the long-path prompt; the Qwen3 reference-transcript developer tools (its inner buttons, not the entry button); the sentence-data download Cancel; the startup configuration-warning Continue. The Install & Continue panel inside the first-run wizard does take roles, through a Light bundle built in the wizard's own process (its window is the platform's light surface whatever the remembered appearance is). Native File Explorer, Finder and message boxes are never recoloured.
- **macOS.** The Aqua bundle publishes the same style keys (they resolve to native buttons), so nothing on a Mac changes; the Aqua rendering is Checkpoint E and is not claimed here.
- **Guards.** `test_button_roles` pins the taxonomy, the 146 counts, the ten blue Book controls, the fill, contrast, disabled and focus rules through a live theme switch, and that every `ttk.Button` in the application takes its style through a role helper. Mutations (a Book role flipped, a hover fill reintroduced) each turned the tests red; the unmutated control stayed green. Coverage inventory: new feature `ACT.SHARED.BUTTON-ROLES`, 14 sources reviewed and restamped.

## 2026-11-20 — v0.8.1 Checkpoint A: shared identity `0.8.1`; file-dialog history is written only when a selection is accepted, through two read-only settings helpers and each panel's own literal key (Claude Code)

Signed: Claude Code (Opus 5.5), HOME-PC. Implements the owner-approved file-dialog decisions of 2026-11-17 (roadmap `files/plans/ACT-v0.8.1-Implementation-Roadmap-DRAFT.md` §1); not an owner acceptance.
- **Identity.** `VERSION`/`config.toml` `0.8.1`, `platforms = ["Windows", "MacOS"]`, `release.RELEASE_OS_NAMES = ("Windows", "MacOS")`. Which engines and voices a platform offers is decided by `shared/engine_policy.py`, never by `platforms` (parsed, consumed by nothing else), so Windows keeps its roster and macOS its accepted 20 voices (no Qwen3, no Chatterbox).
- **What "accepted" means, per chooser.** Import dialogs: the import outcome is `COMMITTED` (`job_ui.import_choice_accepted`); Cancel, nothing added, a refused file, a declined broad folder or large result, a conflict, busy or closed leave the history unchanged. Artwork: only after the decoder accepted the image. M4B Maker custom destination: a reachable folder (history only; the destination itself stays unsaved, Decision 10A). Preferences Browse…: a reachable folder the output-location rule accepts; Save never writes the browse key and Browse never writes `output_base_directory`.
- **Where the code lives.** `settings.remembered_dir(key)` (where a dialog opens: the saved folder while it is a reachable directory, else home; never rewrites or erases the saved value, so an unplugged drive comes back) and `settings.selected_dir(chosen, is_file=...)` (what a selection leaves: a file's folder, a folder itself, or nothing). Both only read and validate. Every write stays a literal `settings.set(KEY_CONST, ...)` in its own panel so `test_settings_allowlist` keeps deriving the allowlist from real writers. No new module, no second store, nothing in `config.toml`.
- **Why not save at the dialog, as before.** The approved behaviour says rejected and declined selections do not change history; the dialog cannot know that, the import outcome can. The pending folder is replaced by every chooser open, and every import entry point is a chooser, so a stale one is never committed.
- **Guard change.** `test_settings_allowlist::test_the_settings_module_describes_what_is_really_saved` admits the two new history kinds (`.destination_dir`, `.output_browse_dir`) and checks the docstring names them; nothing else in it is relaxed.
- **Keys.** New: `tts.input_dir`, `mp3_tool.cover_dir` (fixes the MP3 artwork dialog opening at the import folder), `m4b_maker.destination_dir`, `preferences.output_browse_dir`. Kept, names and values unchanged: `cover_resizer.input_dir`, `m4b_converter.input_dir`, `m4b_maker.input_dir`, `m4b_maker.cover_dir`, `m4b_metadata.input_dir`, `m4b_metadata.cover_dir`, `mp3_tool.input_dir`.

## 2026-11-20 — macOS candidate `451041e`: Cover Image Cancel ordered against publication; GPL-3.0 text shipped; independent re-review APPROVE; owner gates unchanged

Signed: Claude Code (Sonnet 5.5), HOME-MacOS. Not an owner decision and no owner acceptance is signed here. Evidence: `files/dev-work/macos-release-rc/` (ignored). Detail: Handoff, CURRENT block.
- **Context.** The independent pre-merge review of `5c810e7` (REJECT) found two source blockers: Cover Image could replace an original after Cancel and report success, and the archive carried no GPL-3.0 text. The owner's bounded remediation order excluded further containment redesign and any v0.8.1 work.
- **Decision (implementation).** Cover Image stages every output and makes it final only after `JobController.authorize_commit()` (existing protocol, shared contract not changed), so Cancel and the save have exactly one winner; a winning save is never rolled back. The canonical GNU GPL v3 text ships as `LICENSE`, and the packager's root allowlist names it and requires every root file to be git-tracked. The `.act-tmp-cover-*` staging name is short and fixed.
- **Why.** An unlocked check before the replacement leaves a gap Cancel can enter; the controller's lock-ordered grant is the one primitive that records who went first. The README states GPL-3.0 inherited from epub2tts-edge, so a distributed copy has to carry the licence text itself.
- **Result.** New archive 199 members, 12,666,341 bytes, SHA-256 `ebc47366f0c9ad1da82b8addab67970d7ebfe51137d36b09b025045c703d7a0e`, audit 22/22 PASS; previous archive (`658d15d9...63c6`) preserved. Codex on `b7f380c`: REJECT (one BLOCKER, a failure under a latched Cancel settling COMPLETED_WITH_FAILURES), corrected once; Codex on `451041e`: APPROVE. Residuals recorded in the Changelog, not changed: copy output on exFAT/FAT fails with an explanation; a staging file can remain after a window closed mid-encode; reference-WAV redistribution authority (incl. historical Qwen3 AUD-005) is a separate unresolved question.
- **Still open, unchanged:** REAL CLEAN installation, the macOS full gate (blocked at collection), KX-10 Force Quit, the OmniVoice preview deferral, the owner's remaining qualifications. Windows regression and E-B2 stay deferred to v0.8.1. Merge, tag and publication each need the owner's own approval and were not done.

## 2026-11-20 — macOS release candidate `5c810e7`: Codex findings verified (no release-critical macOS regression); native acceptance PASS; recommendation BLOCKED on owner gates, not on a product defect (Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS. Evidence: `files/dev-work/macos-release-rc/` (ignored).
- **Codex review of `b51dc6c`** (gpt-6.2-sol, high, read-only, fresh) answered "RELEASE-CRITICAL: FOUND (11)". Each finding was checked against the code and against the published Windows v0.8.0 (`codex/TRIAGE.md`). Rejected: #3 (a split book is withdrawn whole on Cancel — the documented publication unit, `m4b_execution.remove_outputs`, unchanged since v0.8.0) and #12 (`-write_xing 0` applies only to `codec == "mp3"`; the app passes `libmp3lame`). Pre-existing shared behaviour, noncritical, v0.8.1 candidates: #1, #2 (Cover Image writes in place and honours Cancel between images, by design), #4–#8, #10. Confirmed and bounded: #9 (a local-engine worker may be spawned just after the latch on a cold start; retired within the route bound, nothing published) — v0.8.1. Known: #11 (in-memory assembly peak of the local engines; D6-K, owner pending; the README now states it). No remediation round was opened, because no finding is a verified critical defect.
- **Gate harness fix (`f11e126`, dev-only):** `inventory.live-surfaces` asked a Mac for Windows' four voice families; on darwin it now checks Edge, Kokoro and OmniVoice and that Chatterbox and Qwen3 are absent.
- **Recommendation: BLOCKED for publication, pending owner decisions, not a product defect.** The open items are the never-run `fresh-macos` REAL CLEAN qualification, the full gate that cannot run on macOS until Windows-only tests skip there (see Handoff), and the KX-10 owner check. The agent does not waive any of them.
- **Proposed deferral (owner approval needed):** the six OmniVoice voice previews (plan P6a Revision 3) to v0.8.1. Safe because the gallery is repository documentation outside the archive, and its publication needs the owner's licence review (CC-BY-NC weights, Higgs tokenizer terms) anyway; the README keeps saying the OmniVoice voices have no previews yet.

## 2026-11-20 — Expedited macOS release readiness: Cancel acknowledgment relaxed to about 1 s; D16 route C (`v0.8.0-macos.1`, identity `0.8.0+macos.1`); P5-I-R3 residuals triaged as non-blocking; no further containment redesign (owner decisions; recorded and triaged by Claude Code)

Signed: the owner (decisions 1–3, given in the session's instruction); Claude Code (Opus 5.5), HOME-MacOS (recording, triage and implementation). Start `f61ed77`.

1. **Cancel acknowledgment (C1) is about one second, asserted as < 1.0 s (was ≤ 0.5 s).** The 0.723 s measured in the last partial Codex review is accepted; no speed work is done for that bound alone. Unchanged: Cancel interrupts the active job at once (it never waits for the current book, file or chunk to finish), stops the run's workers and subprocesses, publishes nothing incomplete, lets the user exit or start other work once cleanup is confirmed, and reports FAILED, not CANCELLED, when termination cannot be confirmed; Pause keeps its file-boundary behaviour, preserves progress and resumes; C2 (every route's T_stop), C3–C5 and the 30 s first-run setup settle are unchanged. Recorded in plan §11.2.1 and CX-1 and in the tests that asserted 0.5 s (`C1_ACK_S = 1.0` in six `test_macos_p5*` modules; `ACK_BOUND_S` in `test_macos_p2_kokoro_real.py`).
2. **D16, release route (final publication approval still pending): Option C.** Tag `v0.8.0-macos.1`, release "ACT v0.8.0 for macOS — Revision 1", identity `0.8.0+macos.1`, archive `AudiobookTool-MacOS-v0.8.0-macos.1.zip`. The published Windows v0.8.0 (`d1701e9`) and its asset are not touched and no macOS archive is attached to its tag. Implementation: `config._VERSION_RE` accepts `X.Y.Z+build`; `release.release_tag` names the archive after the tag, because GitHub rewrites `+` in asset names (an asset name that differs from the audited one would break the hash-checked re-download); `RELEASE_OS_NAMES = ("MacOS",)` and `config.toml` `platforms = ["MacOS"]`, because a Windows archive from this source would misattribute it. Consequence stated, not waived silently: no Windows archive ships from this source, so P7b (the Windows full gate) qualifies nothing this release publishes and moves to v0.8.1, with the HOME-PC regression and E-B2. v0.8.1 is the next shared release; its code work starts only after this publication decision.
3. **No further wholesale containment redesign.** Rare, multiply injected containment failures are not automatic release blockers; genuine critical failures still are.

**Triage of the last review observations (Claude Code):**
- **A. Cancel acknowledgment 0.723 s:** owner-accepted (item 1). No change.
- **B. Mixed `str`/`bytes` environment mapping:** not a defect of any supported ACT call. `child_ownership._write_environment` encodes every key and value with `os.fsencode`, exactly as `subprocess.Popen` does on POSIX, so a mixed mapping is written as `Popen` would pass it; `_exec_name` reads `PATH` through `os.get_exec_path`, which takes either key type (and, like `Popen`, refuses a mapping holding both). No production caller passes a `bytes`-keyed environment (searched: `scripts/` builds every child environment from `os.environ` copies with `str` keys). Disposition: noncritical, not changed.
- **C. Residual process/guardian risks (P5-I-R3 (a)–(d)):** each needs either an injected multiple fault or a case ordinary use does not create. (a) a `setsid` descendant that is an Apple platform binary is not found by the token sweep — ACT's contained programs (FFmpeg, its own Python workers, pip) are not platform binaries and do not `setsid` into one; group retirement still ends same-group descendants. (b) guardian killed + child stopped before exec + app killed inside the ~0.1 s replacement — triple injected fault; the child ends itself if resumed. (c) go byte already read while unlink, rename, `chmod` and SIGKILL are all refused — injected OS refusal; reported FAILED, never success. (d) owner-approved bounds (import 5 s join, setup 30 s settle), setup FFmpeg health probes (bounded by their timeout; orphaned only if setup itself is SIGKILLed during one), the Edge CLI under SIGKILL (developer CLI, not the app), an abandoned TTS item thread after a worker that would not stop (already reported FAILED). Disposition: fault-injection-only or noncritical residuals; documented, not fixed.
- **D. Release-critical correctness** (incomplete publication, lost output, failure to stop ordinary jobs, unsafe orphans, false success, setup failure): judged on native evidence at the candidate SHA (the gate's darwin journeys and the bounded native checks), recorded in Handoff.

## 2026-11-18 — P5 closeout, independent re-review 3 (Codex): VERDICT PASS; review 2's findings closed, with two wording precisions made after it

Signed: Claude Code (Opus 5.5), HOME-MacOS. Codex ran read-only in a fresh context on `74ba6d4`. Report: `files/dev-work/macos-p5-closeout/codex/review3/report.md` (ignored).
- **Closed:** the growth wording, the clipping counts and the E-B2 command. Codex recomputed 51.12, 51.10 and 51.12 MiB per further part (about 0.786 MiB of PCM each, about 65 times), and confirmed 29.7 MiB on the disk route and 1.29/10.29 GiB for the screen. `worker_limits.py`'s change is comment-only (identical AST), and all 161 inventory hashes match.
- **Made after it, not re-reviewed:**
  1. (MEDIUM, partly open in review 3) Plan Revision 3u said "per paragraph part" beside the native 5.2 GiB. It now separates the native run from the reproduction with stand-in cuts.
  2. (LOW, new) The review-2 entry's "equal-length cuts (11, 32–232 and 128)" is imprecise. Two sets were prepared, of 11 and of 128 cuts. The scaling runs took the first 32, 64 and 128 cuts of the 128-cut set, and past 128 reused that set in order. The 256-part request stopped at its 10 GiB guard after 232.
- **Nothing in these reviews was HIGH or BLOCKER.**

## 2026-11-18 — P5 closeout, independent review 2 (Codex): VERDICT PASS, no HIGH or BLOCKER; four accuracy corrections to the P5-H and P5 closeout entries below (those entries stand as written; this one corrects them)

Signed: Claude Code (Opus 5.5), HOME-MacOS. Codex CLI 0.169.0 ran read-only in a fresh context over `bae180c..f7cb65a`. Report: `files/dev-work/macos-p5-closeout/codex/review2/report.md` (ignored). Each finding was checked against the evidence before anything changed; all four are correct.

1. **(MEDIUM) "grew with the square of the number of parts" overstates the measurement.**
   - The steps were: 32→64 parts +1.19 GiB (38 MiB per part); then 64→128 +3.195 GiB, 128→192 +3.194 and 192→232 +2.0, each 51.1 MiB per part.
   - So the growth is superlinear only up to about 64 parts. After that it is linear, at about 51 MiB per further part of 0.79 MiB of audio (about 65 times).
   - The P5-H entry gave "no linear budget fits a quadratic cost" as the reason for rejecting a darwin budget multiplier. The reason is now: a linear budget would need about 65 times the audio per narration second, where ~3 times is budgeted now, for an effect whose cause is not established. The measured disk route is the safer remedy.
   - The conclusion stands: the budget was exceeded about 13-fold, and the disk route removes it.
   - The code comment, test docstring, coverage contract, feature map, Handoff and plan are corrected in place in the commit that adds this entry; `worker_limits.py` is restamped (a comment-only change).
2. **(MEDIUM) The reproduction's inputs were stand-ins.**
   - They were not "the 128 paragraph parts the run really held". They were equal-length cuts (11, 32–232 and 128) of the run's published MP3, decoded once to 24 kHz mono 16-bit FLAC. The route deletes its own paragraph files after joining.
   - The 11- and 128-part join script took the parts in file-name order (`p100` before `p11`); the scaling script took numeric order. Memory does not depend on the order, and the in-memory and disk joins were compared on the same order (identical PCM).
   - The native evidence for the defect remains the real run's 5.2 GiB.
3. **(LOW) OmniVoice clipping mixed two counts.** 19 of 144 chunks hold 1–4 samples at |x| ≥ 0.999, 28 in all (the chunk screens). 26 is a separate count: samples at exact int16 full scale in the encoder's input.
4. **(LOW) The Handoff's E-B2 compare command** now carries its interpreter and path (`.venv\Scripts\python.exe files\dev-tools\macos_p2_qualify.py eb2-compare …`).
5. **Two figures Codex could not corroborate are now saved:**
   - The harness's own screen, alone: 1.29 GiB on the Edge MP3, and 10.29 GiB on the 6.3-hour Kokoro MP3 (the first, unsaved reading was 8.37 GiB). Either way it is the harness's peak, not the product's (`screen-peaks.jsonl`).
   - The disk route on the 128 parts: 29.7 MiB, identical PCM (`edge-join-disk.json`; the first, unsaved reading was 28 MiB).

**What Codex found correct:**
- P5-H's disk-only place uses the existing room check, reservation, wait, failure and Cancel. Reservations, repeated `to_disk`, exception cleanup and Cancel stay consistent; there is no unexpected caller, deadlock or leak (it also ran 1,280 default-route comparisons and 24 concurrent disk-only waiters).
- The six pinned modules keep disk-route coverage. The by-id comparisons match.
- The focused-gate failures are honestly reported, and the KX-10 timings match their records.
- D6-final, Windows, owner acceptance and release qualification stay pending; no Windows claim is made from Mac evidence. All 55 Windows module names exist.
- The gate, the policy, the darwin map and `DARWIN_NA_SCOPE` are unchanged since `bae180c`.
- The App Nap records support "no slowdown observed under the recorded conditions".

Its stated limits: no pytest collection (sandbox scratch); no engine, GUI or Windows run; App Nap activation and idle sleep not exercised independently.

## 2026-11-18 — P5 closeout: the darwin map is complete; long-form on real media for Kokoro (whole book), Edge and OmniVoice (each ≥30 min); App Nap measured (no throttling); D6-final recommended; KX-10 adapted to Kokoro and OmniVoice; one new Mac defect found and fixed (P5-H). Verdict: MAC IMPLEMENTATION COMPLETE — RELEASE QUALIFICATION PENDING

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's FINAL PHASE 5 CLOSEOUT instruction (2026-11-18). Commits: `bae180c` P5-G, `f71f8b7` harness (dev-only), `89189ab` and `f04075f` P5-H, then this documents commit. Evidence (ignored): `files/dev-work/macos-p5-closeout/` (`ledger.md` holds every item and its record), `files/dev-work/macos-p5g/`, `files/dev-work/macos-p4b/q/memory/p5-closeout-book-M1-mps.*`. **Nothing here is owner-signed; every owner item below is still the owner's.**

**Decision 1 (run conditions).**
- One heavy job at a time on mains power. Nothing else heavy ran; Claude Code's own `caffeinate` held off idle sleep, and the display never sleeps on this Mac.
- `HF_HUB_OFFLINE=1` for Kokoro; OmniVoice's worker enforces offline itself. Edge used Microsoft's service, as the product does.
- Text D is the whole of Re:Monster volume 1 (`files/test-files/`, 368,650 characters through ACT's PDF extractor, SHA-256 `377d2df8…`). **This book was chosen by the agent, for continuity with P2's 34-minute chapter; the plan says owner-chosen, so the owner's confirmation of the choice is pending.**
- The ≥30-minute runs use that book's first 33,608 characters (the P2 chapter's own cut, the same text hash `8481a7bd…` for every engine).
- `files/runtime-data` was digested before and after. No model, voice, environment or FFmpeg file changed; only OmniVoice job folders came and went (row 26 of the ledger).

**Decision 2 (long-form results; AUTOMATED, this Mac).**
- **Kokoro, text D (af_heart, visible window, `bae180c`).** PASS.
  - 6.29 h of audio in 1,276.8 s: wall RTF 0.0564, inference 0.0543, 139 chunks, one cold load (4.97 s).
  - Output screen clean: decode OK, −26.3 dBFS, peak −1.22 dBFS, nothing clipped, longest silence 1.62 s. No swap, no thermal or performance warning, at least 5.89 GiB free throughout.
  - Worker footprint after each chunk: 2.58–5.48 GiB, with a fitted trend of −8.7 % over the 138 post-warm-up chunks (no growth). Its **lifetime peak was 7.29 GiB**.
  - Five chunks in fresh workers (the longest-sentence chunk, 728 characters; the chunk with the highest footprint in the run; a typical chunk; two more) peaked at 4.22–5.26 GiB. So the 7.29 GiB is a long-lived worker's effect, not one chunk's length (P2's "peak follows chunk length" does not explain it). Cause not established.
  - The app process held the book's audio as 32-bit samples, 2.3 GiB in all. A 6.98 GiB reading after the run was the harness's own output screen, measured alone at 8.37 GiB on that MP3 (not the product).
- **Edge (Steffan).** PASS, three runs on the excerpt: 36.6 min of audio each; 806/806 requests OK; 0 retries, 0 403, 0 NoAudioReceived; screen clean. Speed is the service's request time.
  - Visible (`bae180c`): 1,099.7 s, RTF 0.50, median request 1.26 s.
  - Hidden: 770.1 s, RTF 0.35, median request 0.87 s.
  - Visible on P5-H (`89189ab`): 769.8 s, RTF 0.35, median request 0.87 s.
  - The first two found P5-H (see its entry). The third shows the app at 0.34 GiB through assembly instead of 5.2 GiB.
- **OmniVoice (Male 1, Mac GPU, 16-chunk workers, `f04075f`).** PASS.
  - 43.1 min of audio in 2,337 s: wall RTF 0.905, inference 0.924. 144 chunks in 9 workers, start-up 33.8 s in all.
  - No swap; memory pressure reached level 2 (warn); the 14 GiB safety ceiling was never hit; no process left.
  - **Peak 11,201 MiB (10.94 GiB, 9.4 % over 10 GiB).** Growth inside a worker 20–40 % (70 % in the last, from a low warm-up), each worker given back at its restart. This is the owner-accepted P4B memory exception in kind, at its upper edge (P4B recorded 5–9 % over on book-like text).
  - The integrity screen flagged 1–4 full-scale samples in 19 of 144 chunks (26 samples in all). Male 1 on the GPU has shown this in every book-like run since P4B (10 of 48 chunks there). These flags await the owner's listening confirmation.

**Decision 3 (App Nap / hidden window, D11d; MEASURED).**
- **Kokoro**, A/B/A/B on the excerpt (`bae180c`). Hidden means the window withdrawn and the app hidden as Cmd+H does; `lsappinfo` confirms "(hidden)" and never in front.
  - Wall RTF: visible 0.0584 and 0.0596; hidden 0.0592 and 0.0610 (+1.9 % on the mean, inside the run-order drift 0.0584→0.0610).
  - Chunk overhead about 8 ms in all four runs.
  - The app at priority 46 hidden and 47 in front; the worker at 31.
- **Edge** hidden was faster than visible (service time).
- **No App Nap throttling was measured.** Recommendation for D11d: no `caffeinate` for throughput. Idle system sleep during a long job was not exercised (this Mac's display never sleeps); whether to add `caffeinate -i -w <gui>` for that remains the owner's decision.

**Decision 4 (D6-final — RECOMMENDED; the owner confirms or adjusts; no budget was moved).**
- **D6-E:** confirm unchanged (no speed budget; completion within the retry policy): 3 × 806 requests, 0 retries.
- **D6-K, speed and growth:** RTF ≤ 0.25 confirmed (0.0564 on 6.29 h). Load confirmed (3.4–5.0 s cold). Growth < 10 % after warm-up confirmed as a slope (−8.7 % over 138 chunks). The harness's older "largest against the first" reading gives 31.1 %, from chunk-to-chunk variation, not a trend.
- **D6-K, peak ≤ 6 GiB: OUTSIDE** (7.29 GiB on text D; 5.59–5.91 GiB on the excerpt; P2's 6.0046 GiB). Owner's choice:
  - (i) keep 6 GiB and record a Kokoro peak performance exception, as P4B did for OmniVoice — **the agent's recommendation**, since the cause is not established; or
  - (ii) adopt ≤ 8 GiB on this measured basis.
- **D6-O:** MPS RTF ≤ 1.0 confirmed (0.905 on a real book). Peak and growth remain the owner-accepted exception. Recommend recording its real-book upper edge, 9.4 % over 10 GiB.
- **App process (no budget exists):** a whole-book Kokoro file holds about 0.33 GiB per hour of audio, as Windows does in its one process. An Edge file's assembly on a Mac is now bounded by the disk route (P5-H).

**Decision 5 (KX-10 resolved for automation without Chatterbox; the Force Quit window stays the owner's).**
- Chatterbox stays off. Force Quit sends SIGKILL; each half of KX-10 has an automated counterpart, re-run at `f04075f`.
- **Kokoro on the real window:** `test_macos_p2_kokoro_real.py` KX-1/2/3(a) and KX-7, all PASS.
  - Worker gone 0.048 s after SIGKILL, 0.323 s after SIGSEGV, 0.339 s after SIGABRT (bound 3 s).
  - SIGTERM 0.186 s and Quit 0.231 s (bound 5 s).
  - KX-7: the orphan is seen without the lifeline.
- **OmniVoice:** `macos_p4b_omnivoice_qualify.py kx1`, PASS: the owner SIGKILLed during generation, worker group gone in 0.096 s, nothing published.
- **Maker:** `macos-kx10`, RESULT PASS (31 checks, `2026-11-18_205228_qualification_fff4`).
- The owner's part is `files/dev-work/macos-acceptance/P5-KX10-owner-checklist.md` (Kokoro chapter, Maker build, optional OmniVoice; the read-only process check), bound to this documents commit. **PENDING; not performed by the agent.**

**Decision 6 (the darwin acceptance map and what is re-proved).**
- The map is complete: 49 automated, 7 not applicable under reviewed reasons, nothing pending, nothing owner-manual.
- Every automated counterpart passed in its own phase. The incremental ledger at `f04075f` reports 55 items NEED RERUN (the gate's own helpers and `worker_limits.py` reach them) and 18 with no run in this checkout's outputs (their runs are in worktrees).
- The closeout's proportional focused gate re-proves the subset these changes reach in substance (`2026-11-18_205858_focused_e4aa` at `b0c2e19`: the 11 journeys AUTOMATED PASS (the seven `tts.*` journeys, both `shutdown.tts-*`, `setup.first-run-choices-and-cancel`, `setup.clear-downloaded-data`); pytest 584 collected, 549 passed, 33 skipped (each named by the policy), 2 failed: `test_low_memory`'s Windows `winerror` allocation forms (`failure2`, `failure3`), which fail identically by id before P5-H; RESULT FAIL on those two inherited ids only; process ownership, cleanup, skips, coverage inventory and tree PASS. The first run (`2026-11-18_205425_focused_8463`, at `f04075f`) also failed `test_application_source_boundary` on the new module's raw `rglob`; fixed in `b0c2e19`). **The whole map is not re-proved at one SHA here:** that is the final gate's job on both platforms (P7). It was not run here, per the instruction.

**Decision 7 (Windows; HOME-PC untouched).** The HOME-PC focused regression and E-B2 are **PENDING**. The exact commands, scope (the union of every P1A–P5-H touchpoint list) and required SHA are in Handoff's closeout block. Windows is never claimed verified from Mac evidence.

**Decision 8 (D16 — RECOMMENDATION; owner sign-off required).**
- **Option A:** one shared v0.8.1 source release, with the Windows and macOS ZIPs built from one commit and tag `v0.8.1`. The published Windows-only `v0.8.0` (tag `0a3653e` → `d1701e9`) and its asset stay untouched.
- This matches the owner's own v0.8.1 roadmap draft (`b1250d0`, on `origin/master`, not on this branch).
- **Integration note:** `origin/master` has diverged from this branch by that one documents commit, so a fast-forward of `master` to the final SHA is not possible as things stand. The plan's rule applies: stop for the owner's integration decision.
- Option D (v0.9.0) is the alternative if the owner prefers minor-version semantics.

**Decision 9 (D18 — RECOMMENDATION; owner sign-off and the machine required before P7c).**
- A real, clean Apple Silicon Mac (a second Mac, or a freshly erased one) that never had Homebrew, the Xcode CLT or python.org, ideally with at least 16 GB.
- Preferred over a VM. A VM needs an approved virtualization tool and a macOS image download. A VM's GPU is not the Mac's, so OmniVoice's MPS route could not be qualified in one.
- A new user account on this Mac is SIMULATED only.

**Verdict: MAC IMPLEMENTATION COMPLETE — RELEASE QUALIFICATION PENDING.** The agent-side Mac work of P5 is done. The formal P5 exit is not met. What blocks it:
1. Owner acceptance: P5-A, A-R1, B, D/D-R1/D-R2, E, F/F-R1, G, H (P5-C is owner-accepted).
2. Owner manual items:
   - the six-tool GUI pass;
   - the P1B visual-debt disposition (20 findings, never cleared);
   - the owner's Dark look re-review;
   - listening (the P2 pack's 24 samples, NOT YET REVIEWED; OmniVoice Male 1's clipped-sample flags);
   - the KX-10 Force Quit window.
3. Owner decisions:
   - permissions (P5-A audit);
   - D6-final (Kokoro peak; OmniVoice exception edge);
   - D11d;
   - D15 (WER is NOT RUN until it is decided);
   - confirmation of text D's book.
4. Windows HOME-PC focused regression and E-B2.
5. D16 and D18 recorded, with the clean Mac available before P7c.
6. The complete map re-proved at one SHA (P7).

## 2026-11-18 — P5-H: on a Mac a narration that reaches the assembly gate is joined on disk, never in memory (found by the P5 closeout's long-form Edge run: the in-memory join's footprint grows with the square of the number of parts on macOS)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's FINAL PHASE 5 CLOSEOUT instruction (2026-11-18). **This product change is an agent decision, not an owner decision: it was not named in the instruction, and is recorded here for the owner's review and veto.** Commits `89189ab` (the rule), `f04075f` (the Mac's own log sentence, found natively) and `b0c2e19` (a test-only fix the focused gate asked for), on `f71f8b7` (the dev-only harness options). Evidence (ignored): `files/dev-work/macos-p5-closeout/` (`edge/`, `edge-assembly*/`, `edge-join-scaling.jsonl`, `tests/`).

**Decision 1 (the finding, measured before anything changed).**
- In the 37-minute Edge run (`edge/visible`, the 33,608-character Re:Monster excerpt, Steffan), the app process stayed at 0.32 GiB for the whole synthesis, then rose to 5.2 GiB in the six seconds before the run finished, at 16–34 % CPU, and stayed there. The hidden run did the same (5.19 GiB).
- The harness's own output screen was excluded: alone in a fresh process on that MP3 it peaks at 1.29 GiB, and it runs after the finish.
- Reproduced in isolation, on parts cut from that run's real narration: `read_book`'s in-memory chapter join, verbatim (`combined += AudioSegment.from_file(part)`), over the 128 paragraph parts the run really held. RSS 4.87 GiB; physical footprint 4.77 GiB after the join and a lifetime peak of 4.86 GiB, so this is real memory, not reclaimable pages. `make_mp3` on the joined chapter: 0.52 GiB.
- Scaling on the same narration (fresh process per count; a 10 GiB guard): 32 parts 0.43 GiB, 64 1.62, 128 4.81, 192 8.0; 232 parts (66 minutes, 182 MiB of PCM) reached the guard at 10 GiB. `peak_bytes_for_pcm` budgets 0.14, 0.22, 0.37, 0.52 and 0.62 GiB for those. Each part copies everything joined so far, and on this Mac the superseded copies' memory stays with the process.
- **Mechanism inferred, not proven:** the macOS allocator keeping freed large blocks. The 150 kB per narration second budget fits a heap that returns large blocks on free. **Windows was not measured.**

**Decision 2 (the remedy: the existing disk route, on macOS only).**
- `worker_limits.IN_MEMORY_ASSEMBLY = sys.platform != "darwin"`. At or above `ASSEMBLY_GATE_MIN_PCM_BYTES` (16 MiB, about 5.5 minutes), `assembly_place` asks the gate for a disk place only, through a new `disk_only` option of `AssemblyGate.place`/`_route` (default off). It reserves and waits for `DISK_ASSEMBLY_BYTES`, and its wait message names that, not the in-memory budget.
- The disk route's room check, reservation, wait, failure with a reason, and Cancel are the gate's own, unchanged. Below the minimum nothing changes; a short join still happens in memory.
- Every other platform is unchanged; one module-level flag is the whole difference.
- The disk routes are the existing `disk_assembly.join_to_flac`/`encode_mp3`, which give the same MP3 to the byte (`test_assembly_on_disk`). On the 128 real parts: 28 MiB peak footprint, 3.0 s, PCM SHA-256 identical to the in-memory join.
- Rejected:
  - a darwin budget multiplier (no linear budget fits a quadratic cost);
  - rewriting the join itself (that changes Windows' code path, which needs Windows evidence);
  - environment switches for the system allocator (not ACT's to set).

**Decision 3 (tests).**
- New `files/tests/test_macos_p5_assembly_on_disk.py` (14), covering:
  - the rule's source line and its value here;
  - `assembly_place` as the only reader;
  - the class defaults off;
  - disk at the minimum, at 101 MiB and at 3 GB with 20 GB free, each with an in-memory negative control;
  - the small join untouched;
  - the reservation and its return;
  - Cancel;
  - no room even for disk;
  - the wait message, and the log sentence when it goes to disk;
  - both Edge routes end to end: no in-memory route runs, two chapter joins and the encode go through `disk_assembly`, and the MP3 equals the in-memory route's MP3 to the byte.
- Five mutations were each caught: the rule off on a Mac (1 failure), the Mac branch removed (8), `disk_only` ignored (6), the in-memory budget named in the wait (1), the Mac's log sentence removed (1).
- The six modules that test the in-memory route and its fall back (`test_worker_limits`, `test_low_memory`, `test_assembly_on_disk`, `test_cancel_semantics`, `test_edge_publication`, `test_tts_worker_concurrency`) now pin the flag on with an autouse fixture. They test the same thing on every machine; without it, 24 of their tests took the disk route on this Mac and failed.

**Verification.**
- By id, the six modules: 540 passed and 2 failed before and after. The 2 are `test_low_memory`'s Windows `winerror` allocation forms, which fail on a Mac before the change too.
- The 35 other modules that reach the gate (by import), split as in P5-D: 2,675 tests, identical by id before (HEAD's `worker_limits.py` swapped in) and after: 2,614 passed, 56 skipped, 5 failed. The 5 pre-existing are `test_tts_output_names` 1 and `test_voice_previews` 4.
- Coverage, the new module, P5-G's and both P1B gate modules: 158 passed.
- Inventory: `worker_limits.py` restamped by name after its five features were reviewed (only `ACT.TTS.LOW-MEMORY` is about the route; it gained a contract, the symbol, the module in its selection and two behaviour checks); 0 problems. The feature map states the macOS rule.
- **Native, on the committed code:** the 37-minute Edge file, visible, on `89189ab`: the app at 0.34 GiB through assembly (5.2 GiB before), 806/806 requests, screen clean. Its log said the Windows sentence ("needs about 0.1 GB to assemble, more than this computer has free now"), twice, which was untrue on a Mac: corrected in `f04075f` with its own test and a mutation check. Its MP3 cannot be compared to the byte with the earlier runs, because Edge's service gives different audio from run to run (the two in-memory runs differ too), so the identity rests on the tests and the 128-part reproduction. The closeout's focused gate then ran on `b0c2e19` (Decisions, P5 closeout, Decision 6).

**Windows.** Not changed in behaviour, by construction (the flag is true off darwin, and the pinned tests prove the in-memory route unchanged). `worker_limits.py` and the six test modules join the HOME-PC touchpoint list. Windows' own assembly footprint was never measured; its budget is as it was.

## 2026-11-18 — P5-G: `setup.first-run-refuses-a-folder-too-deep` is NOT APPLICABLE ON MACOS under its own reviewed reason (`windows-only-installation-path-limit`), scoped to that one scenario and to the mandatory `fresh-macos` qualification; the darwin acceptance map is complete (49 automated, 7 not applicable, nothing pending)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's FINAL PHASE 5 CLOSEOUT instruction (2026-11-18), which approved this exception and its requirements A–J. Start `a5aaf23`; commit `bae180c`. Evidence (ignored): `files/dev-work/macos-p5g/` (`na-run1`: the real runner on this scenario; `codex/review1`: the independent review).

**Decision 1 (why not an automated counterpart).** The journey's subject is Windows' own installation-path limit: production `bootstrap.install_path_problem` returns `""` on every system but Windows (`if not IS_WINDOWS: return ""`), so a Mac has no refusal to show and a journey that showed one would have to fabricate it. The Windows journey (`journeys/setup.py` `first_run_refusal`: "too long for Windows", Begin Setup, "Setup did not complete", status 1) and its Windows map entry are unchanged and still required on Windows.

**Decision 2 (a dedicated reason, scoped).** `helpers/acceptance_report.py`: `DARWIN_NA_REASONS = ("windows-input-harness",)` became `DARWIN_NA_SCOPE`: `windows-input-harness` keeps its `control.*` prefix rule; `windows-only-installation-path-limit` covers exactly `setup.first-run-refuses-a-folder-too-deep` and requires the entry's `qualification` to stay `fresh-macos`. `darwin_na_problem` returns the reason a not-applicable entry is refused (unknown reason, wrong scenario, prefix outside `control.`, qualification removed or changed); `darwin_map_problems` uses it, so `verify.py`'s darwin policy load and `judge_darwin`'s first step both refuse a map that stretches the exception. No `why` requirement was added (it would have broken the P1B harness-rule fixtures, which the instruction requires preserved).

**Decision 3 (the map).** The entry is `class: not-applicable`, `reason_id: windows-only-installation-path-limit`, `qualification: fresh-macos`, `decided` naming this entry, its tests and a `why`; `pending_phase` is gone and no other entry changed (the 49 automated entries are byte-identical; Codex compared them). `darwin_about` names both reasons. macOS installation, repair and recovery stay with P1A's native suites and the mandatory REAL CLEAN `fresh-macos` qualification (P7c, D18).

**Decision 4 (what the gate does with it).** The runner reports `NOT APPLICABLE ON MACOS (windows-only-installation-path-limit)`; `judge_darwin` counts a justified not-applicable item as `NOT APPLICABLE — JUSTIFIED`, never as PASS, and a stage holding only such items is NOT RUN. A failing automated counterpart still fails the stage.

**Tests.** New `files/tests/test_macos_p5_platform_exception.py` (22): the production basis (both platforms, via the `IS_WINDOWS` seam), the Windows journey source intact, the entry, the complete map (the 49 automated ids pinned), negative controls (the reason on six other scenarios; six other reasons on this one; `fresh-macos` removed or changed; the harness reason off `control.*`; no other `setup.*` scenario under any reviewed reason), the runner and the judge. P1B gate and closeout tests, the P5-E and P5-F modules now pin an empty pending set; five mutations of the scope logic were each caught. Targeted modules: platform exception 22, P1B gate 24, closeout 60, P5-E 22, P5-F 76, native acceptance 34 (+8 Windows-desktop skips), coverage 39, wrap margin 5: all pass; inventory 0 problems.

**Independent review (Codex CLI 0.169.0, read-only, fresh context, `a5aaf23..bae180c`).** VERDICT: PASS, no finding (`files/dev-work/macos-p5g/codex/review1/report.md`). Its limits as it stated them: sandbox-denied pytest temp files (it ran 33 selected cases and 190 in-memory checks instead); no native GUI journey; no Windows.

**Not changed:** Windows behaviour, the Windows journey, any other darwin entry, the harness rules, the `fresh-macos` requirement.

## 2026-11-18 — P5-F-R1: the first-run window wraps descriptions to the width they really have (margin 48 to 62); `setup.first-run-choices-and-cancel` PASSES natively on the corrected source and is an automated macOS counterpart; `setup.first-run-refuses-a-folder-too-deep` stays pending on P5

Signed: Claude Code (Sonnet 5.5), HOME-MacOS, under the owner's P5-F-R1 instruction (2026-11-18). Start `4801b40`; candidate commit `4579a1e` (production, tests, map, coverage, feature map); this entry is in the documents-only commit after it. Evidence (ignored): `files/dev-work/macos-p5f/` (P5-F's `dev1`, `dev2`, `run1`, `run2-committed-map`, `fix-proof1` are kept unchanged, and `dev2` and `fix-proof1` are NOT acceptance evidence; new: `r1-run1`, `r1-run2-revised-map`, `r1-run3-candidate-4579a1e`) and `files/dev-work/macos-p5f-r1/tests/` (by-id before and after of the first-run modules, the gate-contract run).

**Decision 1 (the production change, and one deviation from the proposal).** `scripts/shared/bootstrap.py`, `run_with_gui._wrap_to_width`: `target = max(320, width - 48)` became `max(320, width - 62)`, with a comment. Nothing else changed (the floor, the `<Configure>` binding, the single list of wrapped labels, the roster, defaults, descriptions and consent text are as they were). **The proposal was 60; the value is 62.** A sweep of the real window every 10 px from 660 to 1400 wide, with each margin, both rosters (the Mac's two choices and Windows' five), counting any label given less width or height than it asked for: margin 48, short at 34 widths per roster by up to 14 px; 58, up to 4 px; 60, up to 2 px, at 3 (Mac roster: 710, 940, 1080) and 5 (Windows roster: 820, 860, 900, 1210, 1270) widths; 62, 64 and 68, none, and no label short in height at any margin. The layout takes 58 px (18 px of padding a side, a 22 px indent) and Tk lets a wrapped line run up to 4 px past its wraplength, so 62 is the smallest margin at which no label is ever short-changed; 60 would have left clipped text at 710 px wide on a Mac. Both rosters were swept on this Mac's fonts.

**Decision 2 (the permanent regression test).** `files/tests/test_first_run_wrap_margin.py`: (a) structural, from the source: the margin is at least twice the container's padding plus a description's indent plus Tk's 4 px overshoot, and is 62; the `<Configure>` binding, the floor and the single wrapping mechanism are unchanged; (b) live Tk, on the real `run_with_gui` with the Mac's and Windows' rosters, at the four sizes the journey shows and every 10 px from 660 to 1000: no label asks for more width or height than it got, no control or description overlaps another or leaves the window, Begin Setup and Cancel are the only buttons, the labels and defaults are the roster's own, every description is shown whole, closing before Begin Setup is still the cancellation status, and `run_setup` and `launch_gui` are never called. It fails at margins 48, 58 and 60 (and its exact pin at 64) and passes at 62. By id, the 11 modules that exercise the first-run window (411 outcomes) are identical before and after the change: 350 passed, 60 failed, 1 skipped both times; the 60 are Windows-only suites (`test_long_paths` 18, `test_omnivoice_setup` 42) that fail the same way on a Mac.

**Decision 3 (verification records).** `bootstrap.py` was restamped by name through `inventory.py restamp` after the inventory flagged it (18 features share the file; the change touches only the first-run window's wrap width); `ACT.SETUP.FIRST-RUN` gained the layout contract, the new test in its selection and its two live-Tk cases in its verification; the feature map states the layout and its Mac-font measurement. The inventory check reports 0 problems. The `coverage.json` `macos` census still reads "pending P5" for this scenario, as it did for `setup.clear-downloaded-data` after P5-E: it is a derived P1B snapshot and was not hand-edited.

**Decision 4 (the policy transition, after a genuine PASS on the corrected source).** `setup.first-run-choices-and-cancel` lost `pending_phase`; its map entry names `journey-checks` and `real-screenshots` and its tests (the two new modules added). **`dialog-contract` is deliberately absent:** that class requires an answered file or folder dialog and fails a journey with none (`acceptance_report._dialog_contract_problems`); Cancel before Begin Setup opens none. The P1B closeout test lists it in `ANSWERS_NO_FILE_DIALOG` (beside `setup.clear-downloaded-data`) and now pins `STILL_PENDING_ON_P5` to the folder-depth journey alone; `test_macos_p1b_gate.py` pins the same pending set and adds a mutation that puts this scenario back to P5. New negative controls in the P5-F module: a re-pended map reports NOT RUN and refuses a PASS; a map without evidence is refused; naming `dialog-contract` fails a complete PASS. The journey also now shows the window at 700x640 (where P5-F measured a 12 px cut), so it shows four sizes and a PASS carries six pictures.

**Decision 5 (runs; this Mac, single scenario, the real runner).** `r1-run1`: pre-policy (the map patched in memory for this id only), corrected source, PASS: 44 checks, 0 failed, 5 native inputs, six pictures PASS review, `judge_darwin` AUTOMATED PASS. `r1-run2-revised-map`: the revised committed-map entry with no override, PASS. `r1-run3-candidate-4579a1e`: no override, on the committed candidate, PASS: 44 checks, `judge_darwin` AUTOMATED PASS, every picture's provenance is `4579a1e` (`dirty` is true only for the owner's untracked `scripts/project-status.py`). In each: zero clipped labels at 660x600, 700x640, 760x680 and 900x700; the approved roster, estimates (344.7 MB, 3.5 GB), licensing text and defaults; all four checkbox states exercised and restored; exit status 2 from the process and the window's own record; no child process, no network attempt, no `run_setup` call, no folder or launch; no owned process, group or window left and no process naming the copy; the copy byte-identical with no new file; the bystander and the real checkout (environment, FFmpeg, models, logs, settings, code, runtime data, default outputs) and the real `files/runtime-data` unchanged.

**Tests.** The P5-F, P5-E, wrap-margin, both P1B modules, coverage, native-acceptance, visual-remediation, containment and dialog-fit modules pass. `test_verification_gate_contract.py`: 12 failed, 200 passed, 87 skipped, the same 12 ids as P5-A-R1. `test_verify_evidence::test_an_interrupted_run_stops_its_child_and_is_recorded_as_incomplete`, which failed once inside P5-F's 18-module run, passed on its own and in the whole module again here (99 passed); it is an unexplained intermittent failure observed once under load, NOT classified as inherited and NOT diagnosed (it does not touch the changed files). **Correction of P5-F's count:** the 18 doc-reading modules collected 961 tests, not 957: 954 passed, 3 failed, 4 skipped (957 omitted the skips).

**Residuals.** Windows is not natively verified: the layout test and the sweep run on this Mac's Tk and fonts with Windows' five-choice roster (it proves the shared arithmetic and that nothing overlaps or loses a line), and the `first-run-scaling` owner check on Windows display scaling stands. The Dark appearance was the only one exercised. The clicks are Tk-level press and release events (D9), not OS pointer events. Remaining on P5: `setup.first-run-refuses-a-folder-too-deep`, whose Windows premise (a path too long for Windows) likely has no Mac counterpart and needs its own decision.

## 2026-11-18 — P5-F: `setup.first-run-choices-and-cancel` has a native macOS journey on the real first-run window; it FAILS natively on a real product defect (the OmniVoice licence line is cut at the window's minimum size) and stays pending on P5

Signed: Claude Code (Sonnet 5.5), HOME-MacOS, under the owner's P5 First-Run Choices and Cancel instruction (2026-11-18). Start `f3d81ce`. Evidence (ignored): `files/dev-work/macos-p5f/` (`dev1/`, `dev2/`, `run1/`, `run2-committed-map/`, `fix-proof1/`, `tests/`, `run_one.py`, `run_fix_proof.py`; each run folder holds the runner's report, the journey's checks, the action log, the pictures with their provenance, `isolation-preflight.json`, `first-run-outcome.json` and `judgement.json`).

**Decision 1 (the journey).** The scenario keeps its id. On a Mac, `journeys/setup.py` dispatches to `first_run_cancel_macos`; the Windows body and its launcher are unchanged. It runs the real `bootstrap.run_with_gui()` through a new `adapters/macos/setup_launcher.py` and the in-process driver, on a disposable copy of the committed `scripts/` under the gate's scratch, beside a second bystander copy. The window runs on the interpreter a first run uses, the app's own base Python (`files/runtime-data/python/bin/python3.12`), through a new optional `AppSession(python=...)` (default unchanged: the gate's own interpreter). Nothing is installed: Begin Setup is never pressed.

**Decision 2 (isolation preflight before any launch).** `helpers/first_run_journey.isolation_problems` judges what the copy's own code says, probed read-only (`-I -B`) on that base Python: the root and `bootstrap.py` are the copy's, the five mutable paths setup would write (`.venv`, `files/bin`, `files/runtime-data`, its logs, the app's Python folder) are exactly the copy's and reached through no link, none reaches the real checkout or a protected location, the interpreter is under the real checkout's `files/runtime-data/python` and outside the copy, every cleanup target and every mutable path, is not a virtual environment, and the copy holds no link at all. A failure raises `ContainmentUnavailable`: BLOCKED before anything is launched. The probe must also write nothing into the copy.

**Decision 3 (tripwires, not mocks).** The launcher refuses and records (a) any call of `bootstrap.run_setup`, the install itself, (b) any name lookup or connection to anything but this computer, and records the folder reveal and the application launch instead of performing them; every child process the window starts is recorded (`children.jsonl`). The window's choices, defaults, estimates, Cancel and exit status are production's own, and a journey never scripts an outcome. Because Begin Setup is never pressed natively, the tripwires are proved headless in the test module (the launcher's own start replaced by deliberate attempts: each is refused and recorded).

**Decision 4 (what is judged).** The approved macOS roster is pinned in the judge from the owner-accepted P4C record (`macos-p4c/smoke/wizard-record.json`): exactly Kokoro (up to 344.7 MB, ticked) then OmniVoice (up to 3.5 GB, unticked), OmniVoice's description carrying Apple Silicon, NON-COMMERCIAL, CC-BY-NC, the separately licensed tokenizer and the terms-before-download line, and no word about Chatterbox, Qwen, NVIDIA or Windows anywhere in the window; the copy's own code and figures must agree. The clicks are a press and a release at each control's centre, dispatched through Tk's own class bindings (the driver's pointer on a Mac with no Accessibility grant, D9; not OS pointer events): Kokoro off, OmniVoice on, Kokoro on, OmniVoice off visit all four states and restore the defaults; after each click only the clicked box differs and no other widget appeared, vanished, was disabled or changed its words. The window is shown at its minimum (660x600), its opening size (760x680) and 900x700, each wholly inside the visible desktop, with no overlap. Cancel is pressed before Begin Setup; the exit status must be 2 from the process and from the window's own record, distinct from 0 and 1 by production's own `setup_exit_code`; no child, folder, launch, connection or install; no owned process, group or window; no process anywhere names the copy; the copy byte-identical with at most its own dated setup log; the bystander and the real checkout (environment, FFmpeg, models, logs, settings, code, runtime data, default outputs) unchanged.

**Decision 5 (the picture's appearance).** `dev1` PASSED its checks but all five pictures FAILED the gate's review ("shows the light appearance it was set to"): the capture op asks `shared.appearance` (the application's setting, `light`) what to expect, while AppKit drew the first-run window Dark, as this Mac's system is. The first-run window never reads that setting, so the expectation was the harness's, not the product's. The launcher's capture now records what AppKit drew, labelled as the system's appearance; the review still compares it against the pixels. This is a harness correction, not a product change.

**Decision 6 (the finding: text cut at the minimum size).** `dev2` PASSED every check and review, yet its 660x600 picture shows the OmniVoice licence line cut at the right edge ("...the fu" then "terms are shown..."). The picture review judges a wrapped label on height only, so it could not see this. A read-only `labels` op in the launcher's channel and `text_clip_problems` now compare what each label asked for with what it got. `run1` (final harness, committed code, pre-policy) FAILS exactly there: 41 checks, 40 pass; at 660x600 the OmniVoice description asked for 611 px and got 602 (wrap at 612). Measured: at 700x640 it is cut by 12 px; at the opening size (760x680, 695 against 702) and at 900x700 it fits. **Cause (production, `scripts/shared/bootstrap.py`, `run_with_gui._wrap_to_width`):** every wrapped label is wrapped to the container's width less 48, but the container pads 18 px on each side and each option's description is indented a further 22 px, so those descriptions have the width less 58: the widest line can overflow by up to 10 px, and it does at the window's own declared minimum. The same arithmetic is in the Windows window; it was not measured there. **Proposed remediation, NOT applied:** the margin 48 to 60 (`target = max(320, width - 60)`). `fix-proof1` runs the same journey on a disposable copy whose `bootstrap.py` carries that one change (the real `scripts/` was never written): 41 checks PASS, judge AUTOMATED PASS. It is evidence about the proposal, not about the committed code.
**Why it is not applied here.** The window is shared Windows and Mac production code, the instruction forbade touching accepted Windows behaviour, and its own rule is that a journey that fails stays pending and is reported. Relaxing the check to the controls only (as the Windows journey's geometry does) would have hidden clipped licensing text, so it was not done. The fix, its restamp, a regression test and this journey's transition are one small bounded checkpoint of their own.

**Decision 7 (the map is unchanged).** `setup.first-run-choices-and-cancel` keeps `pending_phase` P5; no evidence or test is registered for it; both P1B pending-set tests, the coverage records and the feature map are unchanged (the inventory check reports 0 problems). `run2-committed-map` shows the committed map reporting it `NOT RUN ... pending P5`. When it passes on the committed code its entry names `journey-checks` and `real-screenshots` and not `dialog-contract` (Cancel before Begin Setup answers no file or folder dialog), and `ANSWERS_NO_FILE_DIALOG` in the P1B closeout test must list it.

**Runs (this Mac, single scenario, the real runner, pre-policy: the map patched in memory for this id only).** `dev1`: runner PASS (38 checks), judge FAIL (pictures, Decision 5). `dev2`: PASS on 38 checks and the judge, SUPERSEDED: it predates the label check and passed a picture with a cut line. `run1`: FAIL (41 checks, 40 pass; Decision 6; 5 native inputs; all five pictures PASS review, which cannot see the cut; real `runtime-data` identical before and after). `run2-committed-map`: NOT RUN, pending P5. `fix-proof1`: NOT an acceptance run (Decision 6). In every run the window exited 2, recorded no child, no network attempt and no `run_setup` call, left no owned process, and left the copy with zero new files (the window wrote not even a setup log); the bystander and the real checkout were unchanged.

**Tests.** 75 new tests (`files/tests/test_macos_p5_first_run_choices.py`): every control named in the instruction, a mutation check of 24 single-rule changes to the judge (each caught; three overlapping rules were first missed and now have their own tests), the headless tripwire proof, the journey's wiring (every required check and picture is one the journey makes; only a voice box and Cancel are ever pressed) and the map. P5-E's module, both P1B modules, coverage, native-acceptance, visual-remediation and the two containment modules pass; `test_verification_gate_contract.py` gives the 12 inherited macOS failures, the same ids as P5-A-R1. The 18 doc-reading modules (957 tests) gave 954 passed, 4 skipped, 3 failed: `test_cross_tool_consistency::test_maximized_grows_every_flexible_region` and `test_gate_scratch_exception::test_a_child_whose_owner_process_still_runs...` (both inherited, reproduced alone) and `test_verify_evidence::test_an_interrupted_run_stops_its_child...`, which failed once inside the large run and PASSES alone (load-sensitive; not related to the changed files).

**Residuals.** The clicks are Tk-level (Decision 4), not OS pointer events. The Dark appearance was the only one exercised; Light was not. The first-run window's picture has no solid classic-Tk points to register against Tk's layout (an advisory of the review: the window is all ttk). The remaining first-run scenario, `setup.first-run-refuses-a-folder-too-deep`, was not started; its Windows premise (a path too long for Windows) has no obvious macOS counterpart and likely needs a decision of its own.

## 2026-11-18 — P5-E: `setup.clear-downloaded-data` has a native macOS counterpart on a disposable copy, held first to an isolation preflight computed by the copy's own code; it PASSES and its map entry is automated; the two first-run journeys stay pending on P5

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5 Clear Downloaded Data instruction (2026-11-18). Start `049a7b4`. Evidence (ignored): `files/dev-work/macos-p5e/` (`run1/`, `run2/`, `run3/`: the runner's report, the scenario's checks, action logs, screenshots with provenance, `isolation-preflight.json`, `cleanup-outcome.json`, `judgement.json`; `run_one.py`).

**Decision 1 (the counterpart).** The scenario keeps its id. On a Mac, `journeys/setup.py` dispatches to `clear_downloaded_data_macos`, and the Windows body is unchanged. It runs the real application through the in-process driver on a disposable copy of the committed `scripts/` under the gate's scratch. The seed is synthetic and in a Mac's layout: `.venv/bin`, `.venv/lib/python3.12`, `files/bin`, models, a seeded log, OmniVoice's folder, and two links in `.venv` to a sentinel outside the copy. There is a seeded bystander copy beside it. The real helper, the real lease and the real result window are used; nothing is mocked.

**Decision 2 (isolation preflight before any launch).** `helpers/cleanup_journey.isolation_problems` judges what the copy's own code says, run as a read-only child on the application's interpreter: its root, the four authorized targets, the maintenance folder, the helper script and the helper's interpreter (`find_non_venv_python`). Every one must be the copy's own, and the interpreter must lie outside the copy and outside every cleanup target of the real checkout. Here it is this checkout's base `files/runtime-data/python/bin/python3.12`, outside its four targets. The only links may be the two seeded, pointing at the scratch sentinel. A "must never be inside" rule is checked both as written and as resolved, so a link is no way out. If any check fails, `ContainmentUnavailable` stops the scenario BLOCKED before anything is launched. The real checkout's environment, FFmpeg, models, logs, settings, code and the default output folder are digested before and after.

**Decision 3 (the outcome oracle, and one correction).** Every entry of the copy is digested by content (links by their text) after launch and before the first click, and again after the helper ends. The ticked entries must be gone. Every other entry must be identical, except where the application writes (its logs, maintenance state, settings and FFmpeg record); the seeded log is still pinned. Nothing new may appear. `run1` FAILED on one check: five new files in the copy, `qwen3/{setup,inference,engine}.lock` and `omnivoice/{inference,engine}.lock`, all empty. The real helper creates them on purpose: `hold_engine_still` takes the copy's `EnvironmentLease` before it re-checks or removes `.venv` or the models (v0.7.0 P04C). That was an oracle gap, not a product or isolation defect; the real `runtime-data` was identical. The correction allows exactly those five paths, only as new and empty files. A test pins them to `engine_lease.ORDER` and `OMNIVOICE_ORDER`, and a journey check requires that they appear (the lease was taken in the copy). `run1` stays recorded as FAIL.

**Decision 4 (the helper identified, and containment).** The acknowledgement's `coordinator_process_id` must match three things. The application's spawn record must show it started that process, leading a session of its own (class D, detached by design). The kernel's command line must be the preflight's interpreter, the copy's `cleanup_worker.py`, `--run --request-id` and this request. The request must name the application under test's pid and exactly the three items. The helper may be the only owned process outliving the window; afterwards no owned process or group may remain. Its own log in the copy must show it accepted, removed and recorded.

**Decision 5 (evidence and map).** The map entry for `setup.clear-downloaded-data` drops `pending_phase` and names the evidence `journey-checks` and `real-screenshots`, with its tests (`test_macos_p5_clear_downloaded_data.py` added). It does not name `dialog-contract`: that class requires an answered file or folder dialog and fails a journey with none (`acceptance_report._dialog_contract_problems`). This journey opens none; its confirmation is the application's own window, checked by the journey. The P1B closeout test names this exception exactly. The two first-run journeys stay pending on P5, and both P1B expectations now pin exactly those two.

**Runs.** Each pre-policy run used `acceptance_runner.main()` with the map patched in memory for this id only (`run_one.py --pre-policy`). `run1` FAIL (above). `run2` PASS: 42 checks, 9 inputs, 4 screenshots PASS on review at `049a7b4`. `run3` PASS through the committed map with no patch. `judge_darwin` gave AUTOMATED PASS each time it passed. The real `files/runtime-data` was identical before and after every run.

**Residuals.** This is not a real downloaded-data cleanup of an installation: that stays with `fresh-macos`. The real NSAlert/NSOpenPanel are not involved (the dialogs are the application's own Tk windows). The `coverage.json` `macos` census is a derived P1B snapshot; it still reads "pending P5" for this journey, as its tts rows still read "pending P2", and was not hand-edited. Cosmetic: the models item's second consequence line wraps to the left margin in the confirmation.

## 2026-11-18 — Owner accepts the bounded Windows launcher remediation at 10a2fc4; the P1B closeout test's "later phases stay NOT RUN" assertion is corrected to the map's actual pending set

Signed: Claude Code (Sonnet 5.5), HOME-MacOS, under the owner's return-and-closeout instruction (2026-11-18). Parent `10a2fc4`.

**Owner acceptance (recorded as stated by the owner).** The owner explicitly accepted the bounded Windows launcher remediation at `10a2fc4`. Accepted: the Windows launcher implementation; its targeted automated verification; the development `.bat` GUI smoke test; the verification-map reconciliation. **Not accepted / not covered:** replacing the production distribution; real Windows first-run or repair qualification; Windows-native Phase 5 regression; E-B2 phoneme parity; full cross-platform release qualification. The production distribution is unchanged. This supersedes the "Not accepted by the owner" residual of the entry below for the scope listed here only.

**Test correction.** `test_macos_p1b_closeout_gate.py::test_no_automated_journey_waits_on_an_owner_signature_and_each_names_its_evidence` required every `tts.`, `shutdown.tts-` and `setup.` scenario to carry `pending_phase`. The map has 12 such scenarios; the nine tts/shutdown ones completed (no `pending_phase`, full `journey-checks`, `real-screenshots`, `dialog-contract` evidence) and only the three `setup.*` scenarios remain pending on P5. The assertion was stale, not a launcher regression (test and `verification.json` byte-identical between `421fb71` and `10a2fc4`). It now pins the pending set to those three (all P5), and requires every non-pending scenario of those families to be an automated, non-manual counterpart with all three evidence classes. `verification.json` is unchanged; no classification or threshold changed.

**Sibling test (resolved, owner-authorized follow-up).** `test_macos_p1b_gate.py::test_the_five_tools_shutdown_and_behaviour_controls_are_automated_now` carried the same stale premise; it now requires completed TTS/shutdown scenarios to be automated, non-manual and fully evidenced, and the pending set to be exactly the three `setup.*` on P5, with a negative-control test. `verification.json` unchanged.

## 2026-11-18 — Windows starts the app on the venv's `python.exe` with a hidden console; `pythonw.exe` is never started, because Smart App Control blocks it

Signed: Claude Code (Sonnet 5.5), HOME-PC, under the owner's Windows launcher remediation and closeout instructions (2026-11-18). Parent `421fb71`. Local evidence (untracked): `files/run-temp/s5w/diag-sac-disk-2026-11-18.md`.

**Finding.** CodeIntegrity/Operational events 3033, 3077 and 3118 (policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`, Smart App Control, enforcing) name the venv `pythonw.exe` itself as the blocked image: unsigned, and its first reputation lookup was not trusted. It was blocked at the development path (12:07 to 12:13) and at the production path (2026-11-17). The venv `python.exe` is not blocked. A direct `python.exe scripts/launcher.py` start opened the six-tool window with no event.
**Decision.** On Windows the window is started on `python.exe` with `CREATE_NO_WINDOW` alone, and `--launch-only` hands itself to a hidden-console process so the batch window closes at once. There is no fallback to `pythonw.exe`. The `.bat` reports a launch that did not start and sends a returned repair code to the repair route. The fresh-windows qualification follows the same launch and may close only a window that belongs to a process it started and that runs from the extracted copy.
**Why.** Smart App Control has no per-app exception and must not be weakened; the executable it permits is the one to use. `DETACHED_PROCESS` was measured to give the venv launcher's real-interpreter child a visible console, so it is not used. A fallback to `pythonw.exe` would only fail later and out of sight.
**Rejected.** Turning Smart App Control off (irreversible on some builds, and a security change); signing a launcher (the only durable alternative, needs a trusted certificate, not done here); a console that stays open for the whole start (a regression of the console-free launch).
**Residuals.** A failure inside the hidden process after it starts is in the logs only (as before). Live first-run and repair qualification, the Windows-native Phase 5 regression and E-B2 are pending. The production distribution is unchanged and still carries the blocked `pythonw.exe` launch. Not accepted by the owner.

## 2026-11-18 — P5-D-R2: a request in flight asks for its own local-engine worker's end by name, so a retirement another caller has already completed -- unconfirmed -- is never reported as a clean Cancel; each retirement's answer is kept on its own worker (independent-review remediation; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-D-R2 instruction (2026-11-18). Start SHA `5954998`. Evidence: `files/dev-work/macos-p5d-r2/` (ignored): `repro/` (harness `test_r2_repro.py`, rows `before/` and `after/`, `source-*.sha256`), `iter/` (red run against `5954998` from an exported tree, green run), `before-set/`, `after-set/`, `comparison.json`, `protected-*.json`, `release-*.json`. Earlier entries and gate results stand unchanged.

**Finding (H3), reproduced at `5954998`** (14 cases; the real host and `local_engine_worker.py`, a stand-in engine blocked mid-chunk with a helper in its group; an unrelated sentinel survived every case). The precise ordering, made deterministic: the request in flight is parked inside its own Cancel check -- the top of `_await`, before it reads any event -- while another thread's `close` (the engine-switch release) or `kill` (a Cancel hook) retires the worker completely (`_proc` None); only then does the request resume.
- Group really ended, its answer then withheld (`remaining` or `unproved`), via `close` or `kill`: the request raised a **clean** `ConversionCancelled`.
- Without any injection, a helper that left the group (`setsid`) holding the worker's output (`output_open`): also a **clean** Cancel, the escapee still running.
- The same ordering with the request reading on instead of seeing Cancel: the file failed as "stopped unexpectedly: it exited." with nothing about the unconfirmed retirement.
- Control: a confirmed retirement gave a clean Cancel (correct).
- Why R1 did not cover it: `_end` read `self._proc`, found None and returned before its `_last_retirement` lookup; that lookup covered only a caller that read the worker before another finished retiring it.

**Fix (`tts/local_engine_host.py` only).** `_await` notes the worker the request is using and hands it to its own `_cancel`/`_died`, which ask `_end` for that worker's end by name. `_reap_quietly(expected)` retires only that worker, and only while it is still current; each retirement's `Retired` is kept on its own `Popen` (`act_retired`, as `qwen3_process` keeps `act_group_end`), replacing R1's single `_last_retirement` slot. A worker already retired by another caller -- while this end waited or before it began -- answers with its own retirement; an end asked for one worker never retires the current one or takes its answer. Unchanged: a normal Cancel (the request retires its own worker, confirmed: clean), the hooks and engine switching (`kill`/`close` without a worker), Pause, warm reuse, the bounds, every lock, Windows (no worker there).

**Verification (this Mac, native, agent-reported).**
- `test_synthesis_worker_group_retirement.py`: 37 → 44 tests (42 POSIX-only, 2 every platform). Seven new: a Cancel after another caller fully retired the worker unconfirmed (`close` + withheld `remaining`, `kill` + withheld `unproved`, `kill` + an escapee: no injection), the read-on ordering, the confirmed control (`close`, `kill`), and the identity test. Adapted, intent kept: R1's second-caller test wraps `_reap_quietly` with its new optional argument. Against `5954998` (exported tree): 5 failed -- 4 on behaviour, the identity test for the attribute it reads -- 39 passed; with the fix 44/44.
- Proportionate set by test id, before (unchanged tree) and after, same split: `test_local_engine_worker`, `test_synthesis_worker_group_retirement`, the Kokoro route modules (`test_kokoro_health`, `_pipeline_cache`, `_timing_wiring`, `_voices`, `test_cancel_semantics`, `test_mp3_finalization`), `test_epub_retirement`, `test_macos_p2_kokoro_real` (opt-in: 12 skipped both sides), and the containment modules `test_child_ownership`, `test_macos_p1b_containment`, `test_macos_p1b_gui_containment`, `test_normal_exit_group_retirement`, `test_engine_policy`: **0 new failures, 0 new skips, 0 removed, 0 changed among 592 existing ids; 7 added, all PASS.**
- The 27 document/policy-reading modules after these edits: identical by id to P5-D-R1's final run at `5954998` (1,693 passed / 101 skipped / 15 inherited failures).
- Focused gate `2026-11-18_094125_focused_5cd3` (label `p5d-r2`; 4 min 45 s): **RESULT: PASS**, exit status 0. pytest 365: 352 passed, 13 policy-named skips, 0 failed, 0 errors (P5-D-R1's selection); journeys 9/9 PASS (Edge Cancel settled 0.376 s); process ownership, cleanup, skips, coverage inventory and tree PASS. Focused selection only; not full acceptance.
- No test-created worker, helper or sentinel remained (process listing after each run); a confirmed Cancel stays inside its 2 s bound (asserted).
- Protected: reference WAVs, transcripts, previews and Kokoro files match; environment, engine, model and evidence trees, `pyvenv.cfg` and owner settings identical before and after; draft release `447445728` and `master` unchanged; the 22 owner entries untouched. No download, package, pin, OS or permission change.

**Gate policy and maps.** The Windows rule `posix-synthesis-worker-retirement-p5d` max 35 → 42. `coverage.json`: a P5-D-R2 contract on `ACT.TTS.CANCEL` (its symbols already mapped); `local_engine_host.py` restamped (inventory: 0 problems). Feature map `tts-audiobook.md` (macOS worker end).

**Residuals (owner; not changed here).**
1. `_send` reads `_proc` twice without a guard: a worker retired by another caller between a request's `alive()` check and its send would surface as an internal error rather than a worded failure (still a failure, never a clean Cancel). Not reproduced; outside H3.
2. A request's Cancel seen before it reaches its worker (the pre-checks in `load`/`synthesize`) still answers for the current worker, as before: none, if another caller already retired it.
3. P5-D-R1's and P5-D's residuals stand.

## 2026-11-18 — P5-D-R1: on POSIX a synthesis worker whose identity could not be recorded at spawn is never admitted, and `kill_tree` never falls back to signalling a group it cannot prove; choosing another engine retires a local-engine worker that has already exited; a Cancel meeting another caller's unconfirmed end of the same worker is never clean; the Pause journey waits for its control to be on screen (independent-review remediation; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-D-R1 instruction (2026-11-18). Start SHA `22784cb`. Evidence: `files/dev-work/macos-p5d-r1/` (ignored): `repro/` (harness `test_r1_repro.py`, rows `before/` and `after/`, `sources-*.sha256`), `iter/` (red run against `22784cb` from an exported tree, green runs), `pause-probe/` (a dev-only probe scenario and its three runs), `after-suite/`, `comparison.json`, `docs/`, `protected-*.json`, `release-*.json`. P5-D's entry below stands, including its FAILED focused gate.

**H1 — reproduced at `22784cb`** (real disposable processes; the production `spawn_worker`, `qwen3_process.spawn`, `kill_tree` and `WorkerHost`; the kernel start-time lookup made to answer None, deterministically, only to the spawn-time readers `Owner._register`, `leader_start_time` and `WorkerHost._start`, every later read real; every `os.killpg`/`os.kill` recorded with its caller; an unrelated sentinel survived every case):
- OmniVoice `done`: `run_worker` took the released route (`leads_proved_group` false), reaped the worker (exit 0) with no group end at all and returned **success**; its helper ran on. Helper on the worker's output: success after 14 s (shortened bounds), helper running.
- OmniVoice, a Cancel the worker obeys: a **clean** `ConversionCancelled`, helper running. A crash: failure, helper running.
- OmniVoice, a stubborn worker: `kill_tree`'s older POSIX branch sent `killpg(SIGKILL)` to the **unproved group** (caller `kill_tree`), then a clean Cancel.
- `kill_tree` directly: an exited leader was **reaped by `poll()` first** and its child ran on; a running one got `killpg` on an unproved group.
- The local-engine host (classification): not silent and nothing signalled -- a Cancel failed the file ("could not be confirmed stopped") -- but the worker and its helper ran on, forgotten by the host and its owner, until the app ended: Cancel's stop unmet.
- Mismatched identity (P5-D's control): nothing signalled, `GROUP_UNPROVED`; unchanged.

**H1 — fix (POSIX only; the smallest fail-closed correction).**
- A worker whose identity was not recorded is never admitted. `qwen3_process.identity_unrecorded(proc)`: a POSIX process carrying `act_start_time` that is not a recorded tuple (set by `spawn`/`spawn_worker`; Windows and a test's own `Popen` carry none). `run_worker` and `WorkerHost._start` refuse such a worker before supervising it: `end_unadmitted` ends its leader alone through `Popen.kill()` (CPython's own guard: `poll()` first, so only while it is this process's unexited child), reaps it (at most 1 s) and closes its pipes; its group is never signalled. The file fails: "The OmniVoice voice engine was not started: the app could not keep control of it ... (its identity could not be recorded when it started, so it was stopped before it could run)", or "The voice engine could not be started under the app's control (...)". Measured: refused about 3 ms after spawn, before the interpreter had run any of the worker's program.
- `kill_tree`: a process `spawn` started on POSIX -- proved or not -- never takes the older `poll()`/`killpg()` route; with no recorded identity `end_group` answers `GROUP_UNPROVED` and nothing is signalled.
- Why not refuse inside `qwen3_process.spawn`: its POSIX callers include P5-A's setup worker and the setup probes, whose unproved outcome P5-A-R1 already defines (`containment-unproved`); the refusal is kept to the two synthesis workers.
- Unchanged: Windows' Job Object and `taskkill /T` paths (pinned, every platform); the released supervision for a spawn without the attribute (pinned); `child_ownership`; the P5-A to P5-C setup paths; every worker whose identity is recorded -- always, on a healthy Mac.

**H2 — reproduced at `22784cb`** (the real host and `local_engine_worker.py`, a stand-in engine): with the worker exited idle (not reaped) and a helper in its group, `engine_selected("omnivoice")` returned at `alive()`: the host stayed current, the worker stayed a zombie, the helper was still running 2.5 s later (with no helper, the zombie stayed). Controls held: a running idle worker was released, its group ended; a busy one was deferred (`release_when_idle`).
- The second caller (reproduced): a request in flight saw Cancel while another caller -- `close`, as the engine-switch release runs it, or `kill` -- was retiring its worker and could not confirm the group ended (`GROUP_REMAINING` injected after the real end; a real `remaining` holds the end lock for the whole 1 s bound). Waiting on `_end_lock`, the request found the worker gone (`_reap_quietly` answered None) and raised a **clean** `ConversionCancelled`.

**H2 — fix.** `engine_selected` returns only when there is no worker at all (`host._proc is None`, as `cancel_requested` does), so a worker that has exited is released exactly like a running idle one: off the panel's thread, `release` → `close` → group ended, then reaped. Busy deferral, the same-engine no-op, the nonblocking panel and every lock are unchanged. `_reap_quietly` records `(that worker, its Retired)` together under `_end_lock`; an `_end` whose worker another caller retired meanwhile reports that same answer, so `_cancel` raises `LocalEngineFailed` ("asked to stop, but it could not be confirmed stopped") and never a clean Cancel. A caller that finds no worker at all still gets None.

**Pause journey (`tts.pause-at-file-boundary`) — an acceptance-driver readiness race; not a product defect; not caused by P5-D.**
- The failed run `2026-11-18_074413_focused_81e0` (stays FAILED): Start at t=1.937; refused at t=2.385 for the run's newly built Pause (exists, 54×28 at 817,308, `state normal`, `disabled false`, `viewable false`); `at-failure.png` at t=2.508 shows Pause on screen and enabled. The replay's first request came about 8 ms before the click (its scratch log's time).
- Mechanism: Start's command builds a fresh job adapter and grids it synchronously (the Tk thread is held about 0.36 s); Tk maps the new controls at its next idle pass; the adapter's channel serves the driver's click from a timer callback, which can come first. The journey clicked as soon as the first request appeared, with no readiness wait; `open_tool` and `cover.py` already wait for `viewable`/enabled.
- Probe (a dev-only scenario through the gate's own runner on the unchanged app, three runs): a Pause click right after Start was refused "it is not on screen" 3/3; the first request arrived before Pause was on screen 3/3 (0.494 s vs 0.511 s, 0.450 vs 0.471, 0.445 vs 0.465; the probe's own polling of the channel may lengthen that window). 11 of 12 recorded runs had their click accepted 0.438-0.507 s after Start.
- Not P5-D: P5-D touches nothing on the Edge Start path, and the failed click's 0.448 s lies inside the accepted range.
- Fix (the journey only): before clicking, `tts.pause-at-file-boundary` waits -- an explicit condition, at most 5 s -- for the run's Pause to be on screen and enabled, the two things the adapter's `_actionable` refuses a click for. The journey's checks, the adapter's refusal rule and the product are unchanged.

**Verification (this Mac, native, agent-reported).**
- `test_synthesis_worker_group_retirement.py`: 28 → 37 tests (35 POSIX-only, 2 every platform). Nine new: an OmniVoice worker never admitted (`done`, stubborn), a local-engine worker never admitted, `kill_tree` never falling back (running, exited), an engine switch retiring an exited worker (with and without a helper), a Cancel meeting another caller's unconfirmed end (`close`, `kill`). Adapted, intent kept: the Windows pin also covers an unrecorded identity (still `poll` + `taskkill /T`, never refused); the two-ends test asserts one retirement whose answer both callers share; the mismatched-identity control also records that nothing is signalled. Against `22784cb` (its `scripts/` and tests exported with `git archive`, the new module dropped in): 10 failed -- the 9 new on behaviour, the Windows pin only for the function it now names -- 27 passed; with the fix 37/37 (three runs, and in the gate).
- The 121 affected modules (P5-D's list and split: non-Tk in one pytest, each Tk module alone) plus the module, by test id against P5-D's after-run, whose `scripts/` are byte-identical to `22784cb`: **0 new failures, 0 new skips, 0 removed, 0 changed outcomes among 7,619 existing ids; 9 added, all PASS.** Totals 6,489 passed / 842 failed / 158 errors / 139 skipped (baseline 6,480 / 842 / 158 / 139); every failure and error inherited and identical by id.
- The 27 document/policy-reading modules on the final code and maps: identical by id to P5-D's final run (1,693 passed / 101 skipped / 15 inherited failures); after the Handoff, Decisions and roadmap edits: identical by id.
- Focused gate `2026-11-18_085804_focused_fd6c` (label `p5d-r1`; 4 min 44 s): **RESULT: PASS**, exit status 0. pytest 358: 345 passed, 13 skipped, 0 failed, 0 errors (the same 11 modules as P5-D's gate; the skips are policy-named: "Job Objects are a Windows mechanism" 11, "the identity checks read Windows process creation times" 2). Journeys 9/9 PASS (`tts.edge-replay-direct-file`, `tts.edge-replay-folder-mixed`, `tts.service-failure-then-retry`, `tts.cancel-during-narration` -- settled 0.368 s, `tts.pause-at-file-boundary` -- Pause clicked 0.488 s after Start, after the new wait, `tts.pdf-without-text`, `shutdown.tts-close-during-work`, `shutdown.tts-close-forced-landing`, `tts.kokoro-local`). Process ownership, cleanup, skips, coverage inventory and tree PASS. A new run; P5-D's `2026-11-18_074413_focused_81e0` stays FAILED. Focused selection only; not full acceptance.
- Cancel bounds held (asserted): the local-engine worker within 2 s, OmniVoice within 4 s with its grace; a refused worker fails within about 3 ms. No test-created worker, helper or sentinel remained (process listing after each stage); no unproved group or pid was signalled in any case (every `killpg`/`kill` recorded by caller).
- Protected: the 18 reference WAVs, 2 transcript files, 28 previews and 11 Kokoro files match; the environment, engine, model and evidence trees, `pyvenv.cfg` and owner settings are identical before and after (`protected-before.json`/`protected-after.json`); draft release `447445728` and `master` unchanged. No download, package, pin, OS or permission change. The 17 owner deletions and 5 untracked owner entries are untouched.

**Gate policy and maps.** `verification.json`: the Windows rule `posix-synthesis-worker-retirement-p5d` max 26 → 35. `coverage.json`: a P5-D-R1 contract on `ACT.TTS.CANCEL`, `ACT.TTS.ENGINE.LOCAL-ONE-WORKER` (maps `WorkerHost._start`), `ACT.TTS.ENGINE.OMNIVOICE` and `ACT.TTS.ENGINE.QWEN3-WORKER-CONTROL` (maps `_spawned_on_posix`, `identity_unrecorded`, `UNADMITTED_REAP_S`, `end_unadmitted`); the three sources restamped (inventory: 0 problems). Feature map `tts-audiobook.md` (macOS worker end). Journey `tts.pause-at-file-boundary` (gate tooling).

**Residuals (owner; not changed here).**
1. A refused worker's leader is killed on `waitpid`'s word (CPython's guard), not a start time: something reaping this app's children behind `Popen` could in principle hand its id on between that check and the signal. ACT has none (no `SIGCHLD` ignore, no `waitpid(-1)`).
2. A worker that started something within its first milliseconds, before the refusal, would leave it unreached (its group has no proof). Neither real worker starts anything before it has loaded.
3. `kill_tree` on an unrecorded identity now signals nothing: a POSIX caller relying on the older route (only `qwen3_synth`/`qwen3_setup`; Qwen3 is not offered on a Mac) would leave such a process running, answered `unproved`. The synthesis callers never admit one.
4. `engine_selected`'s `busy()` check and its release thread remain unsynchronized with a run starting at that instant (unchanged); that run's Cancel now reports the release's own answer.
5. P5-D's residuals 1-6 stand.

## 2026-11-18 — P5-D: on POSIX a synthesis worker (the local-engine worker, the OmniVoice worker) is never reaped before its process group has been ended; its exit is seen without reaping it; a pipe is never closed under a reader blocked on it; a group not proved or confirmed ended makes the file a failure, never a success or a clean Cancel; `kill_tree` ends a group whose leader has already exited and signals none it cannot prove; Windows unchanged (owner authorization of P5-D; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-D authorization (2026-11-18). Start SHA `bafa792`. Evidence: `files/dev-work/macos-p5d/` (ignored): `repro/` (harness, stand-ins, `before/`, `after/`, `before-table.txt`, `after-table.txt`, `sources-before.sha256`), `probe/close_blocks.py`, `before/`, `after/`, `comparison.json`, `iter/` (red run against the old code), `protected-before.json`/`protected-after.json`.

**Audit (P5-C residual 2).** The two Mac synthesis workers are class-A children (own process group, `child_entry.py`, the owner's lifeline): the local-engine worker (`tts/local_engine_host.py`, Kokoro on a Mac) and the OmniVoice worker (`tts/omnivoice_synth.run_worker` through `spawn_worker`/`qwen3_process.spawn`, killed through `qwen3_process.kill_tree`). Qwen3 and Chatterbox are not offered on a Mac (P4C), and Windows ends these trees through Job Objects. Their supervisors observed a worker's end by reaping it, or by the end of its output, before its group was ended:
- `WorkerHost.alive()` (`poll()`: also the GUI's `cancel_requested`/`engine_selected`), `kill()` (`poll()` and `Owner.kill_now`, which polls), `close()` (`wait(1)`), `_died()` (`wait(2)`), `_reap_quietly()` (`wait(2)`, then it CLOSED the pipes and only then joined their readers);
- `run_worker`'s `finally` (`poll()`/`wait(10)`), and `kill_tree`'s POSIX branch (`poll()` first; `killpg` only if still running, with no identity proof or lock);
- every wait ended on end-of-output; neither supervisor looked for the worker's exit.

**The defect, reproduced at `bafa792`** (`repro/before-table.txt`; real disposable processes; the real `WorkerHost` with the real `local_engine_worker.py` program serving a stand-in engine, the real `run_worker`/`spawn_worker`/`kill_tree` with a stand-in worker speaking the real protocol; each stand-in leaves one helper in its own group; every process judged by pid and kernel start time; an unrelated sentinel survived every case; `scripts/` identical to HEAD, SHA-256 recorded).
- The helper outlived its worker after a crash (L2, O5, O7), an engine-switch `close()` and then the owner's orderly end (L4), an idle worker's own exit followed by the run's Cancel (`kill`, L6) or the panel's `cancel_requested` (L8), a normal `done` (O1: reported **success**), an obeyed Cancel (O3: a **clean** Cancel), and SIGKILL of the owning app after a normal batch (F1: the worker, and with it its lifeline thread, were gone).
- A helper holding a pipe: the host **hung** after a crash with the helper on stderr (L1) and on an engine switch (L5, 21 s, released only by ending the helper), because `_reap_quietly` closed the pipe under its blocked reader (CPython's buffered `close()` waits for that read; `probe/close_blocks.py`); with the helper on the protocol channel it first waited the chunk timeout (L3: 6 s here, 1,800 s in production) and then hung. OmniVoice: `done` → success after **40.4 s** (O2); an obeyed Cancel → "clean" Cancel after **22.2 s** (O4; bound 4 s); a crash → the event timeout (O6: 8 s here, 900 s in production) + 10 s; each leaked a reader thread.
- Controls held before the fix: Cancel during a busy chunk (L7, 2 ms), a stubborn OmniVoice worker (O8, 2.08 s after the latch), a malformed event (O9): the group is signalled while its leader still runs.
- Not reproduced (theoretical; removed by the fix, not separately proved): `kill_tree`'s and `kill_now`'s check-then-signal without the waitpid lock could, if another thread reaped the worker in that instant, signal an id the kernel had already freed.
- Production trigger: neither production worker is known to start a helper (no subprocess use in `local_engine_worker.py`, `omnivoice_worker.py`, the Kokoro/misaki packages, or OmniVoice's inference path; only its CLI/eval scripts spawn). The supervisors' contract does not depend on that: plan 11.2.2 and 11.2.3 (CX-3: the group is empty) promise the whole group, `kill_tree` promises "every descendant, whether or not the process itself is still running", and Windows' Job Object already gives it.

**Decision: retire the worker the P5-A way -- group ended under proof, output read to its end, reaped last (POSIX only; reuses `child_ownership`; no new framework).**
- `qwen3_process`: `spawn` records the new leader's kernel start time on POSIX (`act_start_time`: its owner's record, or read at once while nobody else holds the child). `leads_proved_group`, `leader_exited` (`has_exited`: never reaps), `end_group` (`end_led_group`: waitpid lock, unreaped, same start time, SIGKILL until the kernel says nothing is left; the answer kept as `act_group_end`; once reaped, the earlier answer stands), `containment_problem` (`Retired.problem()`). `kill_tree` on POSIX ends a proved group whether or not its leader still runs (bound `GROUP_END_BOUND_S` = 1.5 s), then reaps it; it never polls first. The job and `taskkill /T` branches are unchanged; Windows never sets `act_start_time`.
- `omnivoice_synth.run_worker` (POSIX, a proved group only; any other worker keeps the released loop byte for byte): the worker's exit, seen on each 0.2 s tick without reaping it, ends its group at once; what it wrote is still handed on; output silent for `OUTPUT_DRAIN_S` = 2 s after that is held by something outside the group (`output_open`). `_settle_led_worker` keeps the released 10 s for a worker still running at the end, ends the group, joins the reader (bounded), reaps, closes stdout only if its reader has finished. `spawn_worker`'s private owner records the identity too.
- `local_engine_host.WorkerHost`: the start time is recorded at spawn; `alive()`/`_exited()` never reap; `_await` acts on the worker's exit (after `EXIT_DRAIN_S` = 0.5 s for what it wrote) as on end-of-output; `_reap_quietly` (under a new `_end_lock`, so a Cancel hook and the run's own end retire a worker once) ends the group (`GROUP_END_BOUND_S` = 1 s), closes stdin, reaps (`REAP_BOUND_S` = 0.5 s), joins the readers (`OUTPUT_EOF_S` = 0.4 s) and closes a pipe only if its reader has finished; worst case 1.9 s, inside Cancel's 2 s. `_died`/`close` wait for the exit without reaping it. `cancel_requested` also retires an idle worker that has already exited. `kill_now` is no longer used here.
- Reporting (never success, never a clean Cancel, when `Retired.problem()` says anything: `unproved`, `remaining`, `signalled`, output held open, not reaped): the local-engine Cancel raises `LocalEngineFailed("... was asked to stop, but it could not be confirmed stopped: ...")`, a death says it in its message, every case is logged and noted (`unconfirmed`); OmniVoice raises `OmniVoiceFailed` ("... could not be confirmed stopped, so its audio was discarded: ..." / "... was asked to stop, but ..."), logged when the file is failing already. The panel already shows such a file FAILED with that sentence (`convert_one`), and the run still settles as Cancelled.
- **Unchanged:** `child_ownership` (no edit), P5-A/R1/B/C behaviour, Cancel's immediacy (the busy-chunk Cancel still SIGKILLs at once; OmniVoice's 2 s grace), Pause, warm reuse across files and runs, the engine-switch release, OmniVoice's per-worker chunk bounds, the worker protocols, text/chunk order, staging, publication and no-clobber rules, voices and references, `Owner._end` (below), every Windows path.

**`Owner._end` (P5-C residual 4) assessed separately, not changed.** It signals a single class-B child (`run_external`'s time-out on its own thread; a lost guardian's orphans) after a start-time check without the waitpid lock; a concurrent reap in that instant could free the id first. It is one pid (never a group), no defect was reproduced, and macOS allocates pids sequentially, so reuse within that window needs a full pid wrap. Left as a recorded residual rather than an unproved refactor.

**Tests (this Mac, native; agent-reported).** New `files/tests/test_synthesis_worker_group_retirement.py`, 28 tests (26 POSIX-only, 2 on every platform), real processes, an unrelated sentinel in each, every process judged by pid and kernel start time and anything left ended by that identity after the assertions; hung supervisors are bounded by the test (a thread with a deadline) so a red run cannot hang:
- the local-engine worker (the REAL `local_engine_worker.py` program serving a stand-in engine): a crash with its helper on `/dev/null`, on its stderr and on its protocol channel; an engine-switch `close` (helper on `/dev/null` and on stderr); `alive()` never reaping an exited worker; Cancel after an idle worker exited, through the run's own end and through `cancel_requested`; Cancel mid-chunk (control; `killed`/`cancel-stopped` and `-SIGKILL` pinned); an unconfirmed group end turning Cancel into `LocalEngineFailed`; a `setsid` escapee holding stderr reported, not waited for; two ends at once retiring the worker once (3 rounds);
- the OmniVoice worker (`run_worker`, real spawn and kill): `done`, an obeyed Cancel and a crash, each with the helper on `/dev/null` and on its output; a stubborn worker (control); an unconfirmed group end never a success or a clean Cancel; an escapee holding the output reported within the bounds; the app window's owner (`qwen3_process.spawn` records the owner's identity);
- `kill_tree` on POSIX: the twins of `test_qwen3_process.py`'s Windows-only tree tests (a child whose parent already exited; the pipe reaching end-of-file) and the identity control (a recorded start time that does not match gets no signal at all; a reaped process is never signalled again);
- every platform: `kill_tree`'s Job Object and `taskkill /T` paths consult no group identity; a worker without a proved group keeps the released supervision.
- Against `bafa792` (`iter/red-old-code.txt`, `iter/red-summary.txt`): 24 failed, 4 passed. 23 failed on behaviour (helper left running; supervisor still waiting past its bound -- 9 hung; success or a clean Cancel reported for an unconfirmed group; an unproved group signalled), 1 because `WorkerHost._end` did not exist. The 4 that pass on both: the two controls and the two every-platform pins. With the fix: 28/28, and 3 more runs 28/28 each (`iter/stability/`; 234 recorded identities, none left).
- The affected set, from the import graph of the three changed modules (`importers.py`; 120 test modules) plus the P5-A/A-R1/B/C and P1B containment modules (121 in all, `affected-tests.txt`), split because an unattended Mac slows Tk tests drastically in a long process (a first attempt in one process: one `test_qwen3_gui.py` test past 8 min, one P5-C window test past 12 min; both modules take 5 s and 21 s alone): the 87 non-Tk modules in one pytest, each of the 34 Tk modules in its own (`core-modules.txt`, `tk-modules.txt`, `run_suite.sh`), the same split before and after. By test id against the untouched `bafa792` (`before/outcomes.json`): **0 new failures, 0 new skips, 0 removed, 0 changed outcomes among the 7,591 existing ids; 28 added, all PASS** (`comparison.json`). Totals 6,480 passed / 842 failed / 158 errors / 139 skipped (baseline 6,452 / 842 / 158 / 139); every failure and error is inherited and identical by id (Windows-only modules on a Mac, as recorded since P1B). The two aborted single-process attempts are kept (`before/aborted-before.txt`).
- One failure seen once outside that comparison, in a five-module sanity run: `test_qwen3_synth.py::test_the_supervisor_gives_up_waiting_after_a_kill_that_never_closes_the_pipe`. It passed alone (3/3), as a module, in the five-module set twice more and in the after-run. Cause (`iter/race-probe-*.txt`): its fake worker checks the cancel flag right after `loaded`, and the test latches Cancel on that line; when the flag lands before that check and inside the 0.3 s grace, the fake obeys, so the stand-in kill is never called (`assert killed`). Widening that gap to 0.1 s fails it identically on the old and the new code in 1.3 s. A pre-existing race in a Qwen3 test (not offered on a Mac); not changed here.
- The 27 modules that read the edited documents and policy (`docs/doc-tests.txt`, P5-C's list): on the final code, policy, coverage and feature map, identical by id to P5-C's recorded run at `bafa792` (1,693 passed, 101 skipped, 15 failed); before and after the Handoff, Decisions and roadmap edits, on the same code: identical by id (`docs/comparison.json`). The 15 are the inherited gate-contract, cross-tool, scratch-exception and P1B-closeout failures.
- Not run: `test_macos_p2_kokoro_real.py` (opt-in `ACT_KOKORO_P2_REAL=1`; it drives the real app window in this checkout); P2 measured the real worker's kill and reap at 0.02 s, far inside the new 1 s bound. The gate's `tts.kokoro-local` journey runs the real Kokoro worker and the app's close.
- Focused gate `2026-11-18_074413_focused_81e0` (label `p5d`; 4 min 36 s), **RESULT: FAIL**, exit status 1, on one journey. pytest 336 passed, 13 skipped, 0 failed, 0 errors of 349 (`test_synthesis_worker_group_retirement.py`, `test_local_engine_worker.py`, `test_omnivoice_synth.py`, `test_qwen3_process.py`, `test_child_ownership.py`, `test_engine_policy.py`, `test_normal_exit_group_retirement.py`, `test_first_run_setup_ownership.py`, `test_first_run_setup_close.py`, `test_macos_p1b_containment.py`, `test_macos_p1b_gui_containment.py`; the 13 skips are policy-named Windows-only tests: 11 Job Object, 2 Windows identity); process-ownership, cleanup, skips, coverage inventory and tree PASS. Journeys 8/9 PASS: `tts.edge-replay-direct-file`, `tts.edge-replay-folder-mixed`, `tts.service-failure-then-retry`, `tts.cancel-during-narration`, `tts.pdf-without-text`, `shutdown.tts-close-during-work`, `shutdown.tts-close-forced-landing`, `tts.kokoro-local`. FAIL: `tts.pause-at-file-boundary`, `InputRefused: tts:jobs.controls.buttons[PAUSE]: it is not on screen` -- the driver refuses a widget that is not yet mapped (`winfo_viewable`), and the journey clicks Pause as soon as the replay sees the first Edge request: here 0.448 s after Start, in the earlier gates 0.475–0.505 s; the screenshot 0.12 s later shows Pause on screen and enabled. An Edge run reaches none of the changed functions before Pause, and the panel and `job_ui` are unchanged. A readiness race in the journey, first seen here in 9 recorded runs of this journey; not changed (gate tooling is outside P5-D).
- Diagnostic re-run of that journey alone on the same tree (`72580b5…`): `2026-11-18_075021_focused_cb0f`, **RESULT: PASS**, exit status 0 (Start → Pause 0.467 s). The full focused gate itself was not re-run.
- Protected: the 18 reference WAVs, 2 transcript files and 28 previews match; the 11 Kokoro files match by size and SHA-256; the `.venv` (engines, lib, bin), base Python, OmniVoice, model, package and eSpeak trees, `pyvenv.cfg`, owner settings and the P4A–P5-C evidence folders are identical before and after (`protected-before.json`/`protected-after.json`). No model downloaded, no package installed, no pin, OS or permission change. The 17 owner deletions and 5 untracked owner entries are untouched (the only new untracked entry was the new test module, committed here); draft release `447445728` is unchanged; `master` was not touched.

**Gate policy and maps.** `verification.json`: new Windows rule `posix-synthesis-worker-retirement-p5d`, max 26 (the 26 POSIX-only tests; nothing Windows ran before is skipped by it). `coverage.json`: `ACT.TTS.CANCEL` maps `WorkerHost._end`, `_exited`, `_died`, `alive` and the four bounds; `ACT.TTS.ENGINE.OMNIVOICE` maps `spawn_worker`, `_settle_led_worker`, `OUTPUT_DRAIN_S` and requires the every-platform released-supervision pin; `ACT.TTS.ENGINE.QWEN3-WORKER-CONTROL` maps `leader_start_time`, `leads_proved_group`, `leader_exited`, `end_group`, `containment_problem`, `GROUP_END_BOUND_S` and requires the every-platform `kill_tree` Windows-path pin; `ACT.TTS.ENGINE.LOCAL-ONE-WORKER` gains the close contract; each adds a P5-D contract and selects the new module; `local_engine_host.py`, `omnivoice_synth.py`, `qwen3_process.py` restamped (inventory: 0 problems). Feature map: `tts-audiobook.md` (Cancel; OmniVoice on a Mac).

**Residuals (owner; not changed here).**
1. `setsid` escapees: a helper that leaves the group is not reached; one holding the worker's output is now reported (`output_open`) within the bounds, never waited for (tested).
2. An owner killed in the instant between a worker's exit and its group's end (OmniVoice: up to one 0.2 s tick; the local-engine host: up to 0.55 s) leaves a helper the worker started (no lifeline holds it then); the same shape as P5-A's.
3. `qwen3_synth.run_worker` (Qwen3: not offered on a Mac) keeps its own reap-first `finally`; its `kill_tree` now ends a proved group. Windows: Job Objects.
4. When the orderly end (`Owner.shutdown`) reaps a worker while its supervisor is retiring it, the supervisor reports `unproved` (the file fails at app close, as it already did).
5. `Owner._end` and `subprocess_utils`' class-B `kill_now` keep their unlocked single-pid check (above).
6. Windows: production unchanged (new code runs only for a POSIX proved group); the new module's 2 every-platform tests and the new rule have not run on Windows (HOME-PC).

## 2026-11-17 — P5-C: on POSIX a pip or probe that exits normally is never reaped before its process group has been ended; its caller waits for its exit, not for the end of its output; a group it cannot prove or confirm ended fails the step; the orderly end checks and signals a child only under its waitpid lock; Windows unchanged (owner authorization of P5-C; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-C authorization (2026-11-17). Start SHA `05ec184`. Evidence: `files/dev-work/macos-p5c/` (ignored): `repro/` (harness, `before/`, `after/`, `before-findings.md`, `before-table.txt`, `after-table.txt`), `before/`, `after/`, `comparison.json`, `iter/` (`red-old-code.txt`, `red-summary.txt`, the order checks).

**The defect, reproduced at `05ec184`** (`repro/before-findings.md`; real disposable processes in a copy of the app with its own base Python and `.venv`; only the worker and "pip" programs are stand-ins, every caller is production code; each process judged by pid and kernel start time; an unrelated sentinel survived every mode).
- A class-A child (pip, an engine probe, `-m venv`) leads its own process group; a helper it starts (a build backend) is in that group. When the leader exited normally, every caller reaped it at once: `qwen3_setup.run_command` (the optional-setup worker's pip and probes: Kokoro, OmniVoice, Qwen3, spaCy), `bootstrap._pip` (the base install), `Owner.run_python` (`bootstrap._child_run`: probes, proofs, `-m venv`, offline pip; through `subprocess.run`), and "Stop setup?" (`request_setup_stop`/`_end_owned_pip`, through `poll()`). Once reaped, the group's id cannot be proved the leader's own, so nothing may signal it: not the run, not the owner's orderly end (it had forgotten the child, or `run_python` never registered it), not the lifeline (only the leader held it). On Windows the Job Object's close does this at the end of every run (`qwen3_process.release`); POSIX had no equivalent for a normal exit.
- Recorded: the helper outlived a normal exit under the first-run window (client and the real window), under the app window's Install & Continue, and in the base install (`_pip`, `_child_run`). A helper that inherited pip's output was worse: every caller waited for end-of-file, so `run_command` stayed blocked until the run's 25 s time-out or the window's Cancel, and `_pip` and `_child_run` without a timeout waited as long as the helper ran; with `timeout=8` a probe whose leader had exited at once waited the full 8 s and then killed only the leader's (gone) pid. "Stop setup?" after pip had exited reaped pip itself, after which its helper outlived setup.
- Also confirmed by reading: `Owner.shutdown` → `_end_many` checked a child's start time and then signalled it (class A: its group) without the `Popen`'s waitpid lock, so a run reaping that child at the same moment could leave a recycled id between the check and the signal (P5-A/P5-B residual 3).

**Decision: follow the leader, end its group, then reap (POSIX only, reusing P5-A's `end_led_group`).**
- `child_ownership.follow_lines(proc, start_time, on_line, stop=...)`: lines are handed on from the caller's thread while a reader thread pumps the pipe; what ends the wait is the LEADER's exit, observed without reaping it (`has_exited`), never end-of-file alone. Then its group is ended the P5-A way (`end_led_group`: waitpid lock held, unreaped, same kernel start time; SIGKILL until the kernel says no signallable member is left), the output already written is still handed on (until end-of-file; at most `DRAIN_IDLE_S` = 5 s of silence and `DRAIN_LIMIT_S` = 30 s in all), and only then is the leader reaped (bounded). A stop (Cancel, "Stop setup?") ends the running group at once; an error in the caller's line callback ends it before propagating. A reader still blocked at the bound is left alone (never closed under it).
- `child_ownership.communicate_led(...)`: the same for `communicate`: stdout/stderr read as raw bytes on threads, *input* written on a thread, the leader's exit or the deadline ends the wait, the group is ended, the output collected (at most 5 s), the leader reaped.
- `child_ownership.Retired` records the outcome; `problem()` is None only when the group was `GROUP_ENDED`, the output reached end-of-file and the leader was reaped. Anything else is a failure the caller reports, never a success: `GROUP_UNPROVED` (already reaped or replaced: nothing signalled), `GROUP_REMAINING`, `GROUP_SIGNALLED`, output still held open by something outside the group, or a leader not reaped in time.
- Callers (the only places that reaped a class-A leader before its group was ended):
  - `qwen3_setup.run_command` (POSIX, no Job Object): `_follow_led_command` uses `follow_lines`; the start time is the owner's record (spawn) or, with no owner, read at once while this call alone holds the child. Cancel → `SetupCancelled` after the group ended. A `problem()` → `SetupError` naming it (never the exit status, never a clean Cancel); the worker's acquisition reports a `SetupError` as a failed install. The Windows loop is unchanged; its `finally` was moved verbatim into `_command_finished`, which both paths call.
  - `bootstrap._pip` (contained): `follow_lines` with `stop=_SETUP_STOP.is_set`; a `problem()` is logged as `ERROR` and the step returns -1 (`PIP_STOPPED` still wins after a stop). The registry forgets pip only once it is reaped.
  - `request_setup_stop` / `_end_owned_pip` (contained): never `poll()` (it reaped); "running" is `has_exited` (never reaps); the group is ended by `end_led_group`, also when pip has already exited; the thread following pip reaps it.
  - `Owner.run_python`: `popen_python` (now a registered class-A child while it runs) + `communicate_led`. `subprocess.run`'s arguments and results are kept: *input* (and its `stdin` conflict), *capture_output* (and its `stdout`/`stderr` conflict), text decoding with the stream's own encoding/errors and universal newlines (as `Popen._translate_newlines`), `check` → `CalledProcessError`, `timeout` → `TimeoutExpired` (now after the WHOLE group was ended), the child's own return code, `args` (still through `child_entry.py`). A `problem()`: a zero status is reported as `UNCONFIRMED_RETURNCODE` (-1), the reason is appended to a captured stderr and recorded in the owner's events (setup's log), as `run_external` reports a lost guardian. Not an exception: several callers catch only `OSError`/`TimeoutExpired`, and `-m venv` catches nothing.
- `Owner.shutdown` (`_end_many`, shared with `stop_external`): each check-and-signal is made under the child's waitpid lock (`_signal_proved`; bounded at `_LOCK_WAIT_S` = 1 s, otherwise left unsignalled for its lifeline or guardian); a class-A group is ended by `end_led_group` (confirmed); a child reaped by its own run meanwhile is never signalled. A run and the owner can no longer race to reap or signal a leader whose id could have been handed on.
- **Unchanged:** `end_led_group`, `WorkerRun` and R1's outcomes, P5-B's first-run ownership and settle, Cancel's immediacy (a stop ends the running group at once, no grace), Pause (never touches a running step), consent and install protections, the app window's owner, `qwen3_process.spawn`/`kill_tree`/`release`, every Windows path (Job Objects, `taskkill /T`, `subprocess.run`; pinned on every platform). No process scan, name match, guessed pid or unproved group signal was added.
- **Behaviour notes.** A helper a pip or probe leaves running is now ended when the leader exits, as Windows' Job Object close already did; nothing in ACT relies on such a helper outliving its leader. A presence probe (`required_modules_present`) whose containment could not be confirmed reads its -1 as a negative and proposes a repair; the log carries the containment line. The orderly end may now leave a child unsignalled when its waitpid lock cannot be had within 1 s; that child's lifeline (class A) or guardian (class B) still ends it with the owner.

**Tests (this Mac, native; agent-reported).** New `files/tests/test_normal_exit_group_retirement.py`, 38 tests (36 POSIX-only, 2 on every platform), real processes, an unrelated sentinel in each; a "pip" that starts a helper (output to `/dev/null` or to pip's own pipe), records both, waits for the test's barrier and exits normally:
- the mechanism: a normal exit (both outputs) ends the helper before the reap and hands on every line; a stop ends the running group at once; a leader reaped beforehand is never signalled and is reported; an unconfirmed group end (`remaining`, `signalled`) is reported;
- the base install: `_child_run` probes (both outputs; time-out ends the whole group; a failing and a crashing probe keep their status and leave nothing; `subprocess.run`'s argument and result rules; an unconfirmed end is never a success), `_pip` (both outputs; "Stop setup?" during pip; "Stop setup?" after pip exited never reaps it and ends its helper; pip reaped behind its back fails with -1 and says why);
- the worker's `run_command` (both outputs, under an owner and in its own session; failure; crash; Cancel; reaped behind its back → `SetupError`);
- the orderly end: ends an exited leader's helper; never signals a leader reaped while it waited for the lock; races a run's own retirement (8 rounds) without error or leftover;
- end to end, the real `WorkerRun` and worker spawn under the first-run window's owner and the app window's (both outputs: success, nothing left; an unprovable end: the worker's own failure, published once, is the answer) and through the real first-run window (check and install, the helper on pip's output);
- Windows: `run_command`'s Job Object path and the base install's released paths (`subprocess.run`, the streamed pip, `taskkill /T`) are unchanged and never consult the new code.
- Against `05ec184` (sources swapped back temporarily, restored and verified by SHA-256): 34 failed (`iter/red-old-code.txt`, `iter/red-summary.txt`): 24 on behaviour (helper left running; caller still waiting 5–10 s after pip's exit; the stop reaping pip; an unprovable end reported `succeeded`; the orderly end signalling a group whose leader had been reaped) and 10 because the new functions did not exist. The other 4 (preservation pins) pass on both.
- Existing tests adapted to the new seam, intent unchanged: `test_bootstrap_requirements_state.py`'s two "a probe that cannot run" tests now also make `subprocess.Popen` fail (a contained POSIX setup creates the probe with it; Windows still through `subprocess.run`); `test_venv_recovery.py::test_the_whole_assessment_costs_one_subprocess` counts at `Owner.run_python` as well as `subprocess.run`; `test_macos_p1b_containment.py`'s exact KX-9 list drops `run_python` (it no longer spawns directly; `popen_python` does).
- Harness lessons, kept in the new module: a helper SIGKILLed after its parent has gone is a zombie for a moment (launchd reaps it), so "running" excludes zombies and "gone" waits at most 2 s for an exit already under way (a helper never ended sleeps 300 s); "nothing was signalled" requires the helper still running a full second later; the suite's `_no_real_qwen3_install` guard replaces `qwen3_setup.run_command` per test, so the module calls the real function captured at import (as `test_spacy_consumer.py` does); "reaped behind its back" happens inside the caller's own line callback, so it is deterministic.
- The 79 affected modules (`affected-tests.txt`: P5-B's 70 without `test_qwen3_gui.py`, which is Tk layout only and starts no process (P5-B's recorded after-run matches this baseline on all 4,152 shared ids), plus `test_first_run_setup_ownership.py` and nine that reach the changed functions) plus the new module, by test id against the untouched `05ec184` (`before/outcomes.json`): **0 new failures, 0 new skips, 0 removed, 0 changed outcomes among the 4,710 existing ids; 38 added, all PASS** (`comparison-final.json`). Totals 3,693 passed / 723 failed / 158 errors / 174 skipped (baseline 3,655 / 723 / 158 / 174); every failure and error is inherited and identical by id. The first after-run (`after/`) had 10 more failures, all on the old seam (`test_chatterbox_bootstrap.py` 8, `test_spacy_restore.py` 2), fixed by the adaptation above before the final run (`final/`). A subset run had also shown 14 failures in `test_qwen3_setup.py` and `test_optional_setup_acquisition.py` (a Windows-simulation sandbox importing `soundfile` first): the original code gives the same outcomes in that order (`iter/order-old.json`), and in the baseline's order both match.
- 27 more modules that import the changed modules (`extension-tests.txt`), run on the original sources (swapped back, then restored and verified by SHA-256) and on the final tree: identical by id, 1,150 ids (1,036 passed / 67 failed / 47 skipped; `extension/comparison-final.json`). This is where `test_kokoro_health.py` (16) and `test_tk_proof.py` (1) showed the old seam before their adaptation.
- The 27 modules that read the edited documents (`docs/doc-tests.txt`: P5-B's 25 plus `test_dev_work_isolation.py` and `test_verification_coverage.py`), before and after the Handoff, Decisions and roadmap edits, on the same code: identical by id (1,693 passed, 101 skipped, 15 failed; `docs/comparison.json`). The 15 failures are the inherited ones (`test_verification_gate_contract.py` 12, `test_cross_tool_consistency.py`, `test_gate_scratch_exception.py`, `test_macos_p1b_closeout_gate.py` 1 each), identical by id at `05ec184`.
- Inherited, observed, not changed: after the baseline the two processes of `test_verification_gate_contract.py`'s synthetic gate trees (its inner pytest and a synthetic `scaling/qualify.py`) outlived pytest briefly and ended by themselves; nothing was signalled. After the final runs, the reproduction harness and the gate, no test or harness process remained; every process the harness left was ended by its recorded identity after it was judged.
- Focused gate `2026-11-17_202440_focused_7e07`, **RESULT: PASS**, exit status 0 (4 min 22 s). Journeys, all PASS (9/9): `tts.edge-replay-direct-file`, `tts.edge-replay-folder-mixed`, `tts.service-failure-then-retry`, `tts.cancel-during-narration`, `tts.pause-at-file-boundary`, `tts.pdf-without-text`, `shutdown.tts-close-during-work`, `shutdown.tts-close-forced-landing`, `tts.kokoro-local`. pytest 356 passed, 2 skipped, 0 failed of 358 (`test_engine_policy.py`, `test_child_ownership.py`, `test_first_run_setup_ownership.py`, `test_first_run_setup_close.py`, `test_normal_exit_group_retirement.py`, `test_macos_p1b_containment.py`, `test_macos_p1b_gui_containment.py`, `test_bootstrap_requirements_state.py`, `test_bootstrap_setup_cancel.py`, `test_chatterbox_bootstrap.py`, `test_spacy_restore.py`, `test_kokoro_health.py`; the 2 skips are `test_first_run_setup_close.py`'s Windows-only identity tests, under a reason the policy names); process-ownership, cleanup, skips, coverage inventory and tree PASS. It ran on the final code and tests (`05ec184` plus this checkpoint's working tree); only Handoff, Decisions and the roadmap changed after it. Focused selection only, not full acceptance.
- Protected: the 18 reference WAVs, 2 transcript files and 28 previews match; the 11 Kokoro files match by size and SHA-256; the `.venv/engines`, OmniVoice, model and package trees and the P4B–P5-B evidence folders are identical before and after (`protected-before.json`/`protected-after.json`). No model was downloaded, no package installed, no dependency pin or OS setting changed, and no permission was changed. The 17 owner deletions and the 5 untracked owner entries are untouched (the only new untracked entry was the new test module, committed here); draft release `447445728` is unchanged (same asset, size, digest and update time). `master`'s `files/plans/ACT-v0.8.1-Implementation-Roadmap-DRAFT.md` is not on this branch and was not touched.

**Gate policy and maps.** `verification.json`: new Windows rule `posix-normal-exit-retirement-p5c`, max 36 (the 36 POSIX-only tests; nothing Windows ran before is skipped by it). `coverage.json`: `ACT.SETUP.FIRST-RUN.CANCEL` maps `Owner.run_python`, `Owner._end_many`, `_signal_proved`, `follow_lines`, `communicate_led`, `retire_led_group`, `Retired`, `UNCONFIRMED_RETURNCODE`, adds a P5-C contract, selects the new module and requires its every-platform base-install pin; `ACT.TTS.SETUP.QWEN3-ENVIRONMENT` maps `_follow_led_command` and `_command_finished`, adds a contract, selects the module and requires the `run_command` Job Object pin; `ACT.SETUP.DEPENDENCY-LOCK` selects the module; `child_ownership.py`, `bootstrap.py`, `qwen3_setup.py` restamped (inventory: 0 problems). Feature map: `shared-workflows.md` (setup's children; the worker end's former "Gap").

**Residuals (owner; not changed here).**
1. `setsid` escapees: a descendant that leaves the group itself is not reached; one that holds the output open is now reported (`output_open`), not waited for.
2. Synthesis workers, not pip or probes: `local_engine_host` and `omnivoice_synth` reap their class-A workers without ending the group first, and `qwen3_process.kill_tree`'s POSIX branch still checks `poll()` before `killpg`; they start no helper known to outlive them. Assessed, not changed (outside P5-C's pip/probe scope).
3. P5-A's: a plain child left in the worker's own group survives if setup is killed between the worker's exit and its run's group end; the lifeline end is asynchronous.
4. `Owner._end` (a single class-B child: `run_external`'s time-out, a lost guardian) still signals without the lock; it signals one pid, never a group.
5. A containment failure in a presence probe reads as "missing" (a repair is proposed); the log names the containment failure.
6. Windows: production unchanged (one refactor: `run_command`'s `finally` moved verbatim into `_command_finished`); the new module's 2 every-platform tests and the new rule have not run on Windows yet (HOME-PC).

## 2026-11-17 — P5-B: on POSIX the first-run setup window owns the optional-setup workers it starts, through the same P1A owner and lifeline the app window uses; once the window has closed nothing new starts, each run ends and reaps its own worker first (bounded), and only then does the orderly end run; Windows takes no new ownership (owner authorization of P5-B; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-B authorization (2026-11-17). Start SHA `a88f3fb`. Evidence: `files/dev-work/macos-p5b/` (ignored): `repro/` (harness, `before/`, `after/`, `before-table.txt`, `after-table.txt`), `before/`, `after/`, `comparison.json`, `iter/red-old-code.txt`.

**The defect, reproduced at `a88f3fb`** (real disposable processes; a copy of the app with its own base Python and `.venv`; only the worker program is a stand-in, started by the real window, panel, client, `WorkerRun`, `qwen3_process.spawn` and `child_ownership`; each process identified by pid and kernel start time; an unrelated sentinel checked in every mode).
- Root cause: `run_with_gui`'s optional-voices phase never made setup a containment owner. `qwen3_process.spawn` chooses class A only when the process has a containment owner (`subprocess_utils.containment_owner()`) or runs under a lifeline; the first-run setup process had neither, so the worker started with a plain `start_new_session` (own session, no lifeline, not registered), and the worker, not under a lifeline, started pip and the probes the same way. The app window never had the defect: `launcher.main` calls `subprocess_utils.enable_containment` before Tk starts.
- Recorded (`before-table.txt`): closing the window during a blocked check left the worker, its own child, pip and pip's helper running; Cancel and a time-out ended the worker's group (`cancelled`/`timed-out`, group `ended`) but pip's helper, in pip's own group, kept running; SIGKILL or `abort` of setup left all four; a worker that exits leaving its pip left pip and the helper. Under the app window's owner the same Cancel left nothing.

**Decision: the first-run window is an owner, the app window's way (POSIX only).**
- `bootstrap.own_optional_setup()`, called by `optional_phase` before the panel is built (so before its first check): setup's own owner, `_owner()` (the process's single `child_ownership.owner()`, already ending setup's children at exit), becomes `subprocess_utils`' containment owner via `enable_containment`, which returns that same object. No second owner and no new mechanism: every worker is a class-A child (own group, `child_entry.py`, setup's lifeline), and a worker under a lifeline starts pip and the probes as class-A children on its own lifeline, as under the app window. So the worker ends when setup ends, however it ends, and pip and the probes end when the worker ends, however it ends (a forced Cancel or time-out ends the worker's group).
- `bootstrap.settle_optional_setup()`, called once the main loop has returned and before anything else (`LOG.close`, the relaunch):
  - `begin_closing()`: from here a request to start a worker, pip or probe raises; nothing starts.
  - It waits, bounded by `OPTIONAL_SETUP_SETTLE_S` (30 s), until every owned child has been reaped. A run asked to stop (the window's close sets the panel's cancel) gives its worker `CANCEL_GRACE_S` (10 s), then ends its group and confirms it empty within `TERMINATE_WAIT_S` (15 s), and only then reaps it; the bound covers both, with a margin (pinned by a test).
  - Why the wait: `Owner.shutdown` signals and reaps without the proof `WorkerRun` holds. Calling it while a run is still judging its worker's group could reap the worker first and turn a provable end into `containment-unproved`, or race the run's reap. Waiting keeps P5-A's order (group ended and confirmed, then reaped) and R1's outcomes intact.
  - A worker still unreaped at the bound has its group ended the P5-A way (`child_ownership.end_led_group`: proved by the waitpid lock and start time, signalled, confirmed, never reaped there); then `Owner.shutdown` runs. Its run, if still going, reports what it can prove; never a clean outcome it cannot (pinned by a test that forces the bound to 0).
  - Then the lifeline closes; anything left that holds it ends.
- Both are no-ops on Windows (`_contained()` false): the Job Object path, the first-run window and every Windows spawn are unchanged (pinned on every platform).
- **Races considered.** The panel's threads only post to a queue; the window's close sets cancel and destroys Tk; the run thread keeps judging its worker while `settle` waits on the main thread, and the process cannot exit before that (or the bound). A start requested once the window has closed raises (`begin_closing`): the client reports setup unavailable (the panel's failure path) and no worker starts, owned or not (pinned). Setup killed before its worker starts leaves nothing; killed while the worker is starting, the worker (already on the lifeline) ends; killed just after the worker exited, the worker's probe (on the worker's lifeline) ends (pinned by real processes).
- **Behaviour change, accepted:** after the window closes while a step ignores Cancel, setup exits once that step's run has ended its worker (about 12 s with the stand-in; at most 30 s plus the 15 s group end), instead of exiting at once and leaving the step running. The window itself closes at once, as before.
- **Unchanged:** `WorkerRun`, `child_ownership`, `qwen3_process`, the client and panel; R1's containment outcomes; consent, plan, install, progress, Skip, Continue, Try again, "Stop setup?" and the exit codes; the base install and the launch; Install & Continue in the app window. No process scan, name match, guessed pid or unverified `killpg` was added.

**Tests (this Mac, native; agent-reported).** New `files/tests/test_first_run_setup_ownership.py`, 23 tests (19 POSIX-only, 4 on every platform), real processes with an unrelated sentinel in each:
- the source order (owner before the panel's first check; settle right after the window) and the bound covering a run's own stop; Windows takes no new ownership; the app window's ownership path unchanged;
- the first-run owner is setup's own and the one the spawn path uses;
- through the real window: a completed check and install leave no worker or probe; Cancel during a blocked check and install; closing the window during a blocked check and install; Force Quit (SIGKILL) of the window's process;
- through the client the panel calls: time-out of a check and an install; a worker that exits leaving a probe and a child; each run ends its own worker before the orderly end (the end is observed); a run still stopping at the bound is never reported clean; an unconfirmed end is never a success; no worker starts once the window has closed;
- setup killed or crashed mid-check; killed before its worker starts, while it starts and just after it exited.
- 22 failed against `a88f3fb` (15 because the hook they call did not exist, 7 on what they check); the app-window pin passes on both.
- `files/tests/conftest.py`: fixture `fresh_containment_owner` (owner state is process-wide by design; a test that reaches the voices' phase in-process gets a fresh owner, shut down after). The existing optional-voices close test in `test_first_run_setup_close.py` uses it; its assertions are unchanged.
- The 70 affected modules (`files/dev-work/macos-p5b/affected-tests.txt`: P5-A-R1's 37; nine more that reach the first-run window, the launcher or the gate; the 25 that read the edited documents, one shared) plus the new module, compared by test id with the untouched `a88f3fb` (`before/outcomes.json`): **0 new failures, 0 new skips, 0 removed, 0 changed outcomes among the 4,185 existing ids; 23 added, all PASS** (`comparison-final.json`). Totals 3,281 passed / 628 failed / 158 errors / 141 skipped (baseline 3,258 / 628 / 158 / 141). Every failure and error is inherited and identical by id (Windows-only modules on a Mac, and those P5-A recorded). In the full after-run (3 h 10 min; the baseline took 4 h 49 min) one new test failed: the SIGKILL case read the stand-in pip's identity before pip had recorded it. The tests waited for the record of pip's helper, which pip writes before its own; a race in the test harness, not in containment. Reproduced by widening that gap (`iter/race-probe-old.txt`: the same assertion, and the cancel, close and settle tests passed there without pip in what they checked); fixed by waiting for pip's own record everywhere and asserting pip and its helper present before asserting them ended (`iter/race-probe-new.txt`: 6/6 with the gap); the time-out test now allows 8 s instead of 3 s so its worker and pip have recorded themselves first. The fixed module passed 23/23 in four further runs and in the gate; its outcomes replace the after-run's in `after/outcomes-final.json` (the original stays in `after/outcomes.json`).
- The 25 modules that read the edited documents (`docs/doc-tests.txt`), before and after the Handoff, Decisions and roadmap edits, on the same code: identical by id (1,635 passed, 100 skipped, 15 failed; `docs/comparison.json`). The 15 failures are the inherited ones P5-A-R1 recorded (`test_verification_gate_contract.py` 12, `test_cross_tool_consistency.py`, `test_gate_scratch_exception.py`, `test_macos_p1b_closeout_gate.py` 1 each), the same in the baseline.
- Inherited, observed, not changed: as in P5-A-R1, two processes from `test_verification_gate_contract.py`'s synthetic gate trees (its inner pytest and a synthetic `scaling/qualify.py`) outlived the baseline run by about a minute and ended by themselves; nothing was signalled. After the after-run, the reproduction harness, the race probe and the gate, no test or harness process remained; every process the harness left was ended by its recorded identity.
- Focused gate `2026-11-17_174054_focused_060c`, **RESULT: PASS**, exit status 0 (3 min 10 s). Journeys, all PASS (9/9): `tts.edge-replay-direct-file`, `tts.edge-replay-folder-mixed`, `tts.service-failure-then-retry`, `tts.cancel-during-narration`, `tts.pause-at-file-boundary`, `tts.pdf-without-text`, `shutdown.tts-close-during-work`, `shutdown.tts-close-forced-landing`, `tts.kokoro-local`. pytest 143 passed, 2 skipped, 0 failed of 145 (`test_engine_policy.py`, `test_child_ownership.py`, `test_first_run_setup_ownership.py`, `test_first_run_setup_close.py`; the 2 skips are the last one's Windows-only identity tests, under a reason the policy names); process-ownership, cleanup, skips, coverage inventory and tree PASS. It ran on the final code and tests (`a88f3fb` plus this checkpoint's working tree); only Handoff, Decisions and the roadmap changed after it.
- Protected: The 18 reference WAVs, 2 transcript files and 28 previews match; the 11 Kokoro files match by size and SHA-256; the `.venv/engines`, OmniVoice, model and package trees and the P4B–P5-A-R1 evidence folders are identical before and after (`files/dev-work/macos-p5b/protected-before.json`/`protected-after.json`). No model was downloaded and no package installed: the harness and the tests run stand-ins in disposable copies. The 17 owner deletions and the 5 untracked owner entries are untouched (the only new untracked entry was the new test module, committed here), and draft release `447445728` is unchanged (same asset, size, digest and update time).

**Gate policy and maps.** `verification.json`: new Windows rule `posix-first-run-ownership-p5b`, max 19 (the 19 POSIX-only tests; nothing that runs on Windows is skipped by it). `coverage.json`: `ACT.SETUP.FIRST-RUN.CANCEL` maps the three new symbols, selects the new module and requires its two every-platform pins; `bootstrap.py` restamped. Feature map: `shared-workflows.md` (first-run cancel and the optional-voices worker end).

**Residuals (owner; not changed here).**
1. Inherited, path-independent: a pip or probe that exits normally after starting a helper in its own process group is reaped without that group being ended (`qwen3_setup.run_command`; by code reading also `bootstrap._pip` in the base install), so the helper keeps running. Reproduced from the first-run window and under the app window's owner alike (`repro/after/client-plan_pip-exits`, `repro/after/client-app-owner-plan_pip-exits`). Recommended for the next checkpoint.
2. P5-A's: a plain child left in the worker's own group survives if setup is killed between the worker's exit and its run's group end.
3. P5-A's: `Owner.shutdown` checks identity without the waitpid lock; P5-B reaches it only after the runs have reaped their workers or `end_led_group` has ended a straggler's group.
4. `setsid` escapees are not reached.
5. The lifeline end is asynchronous; a pip could in principle exit on its broken output pipe before its lifeline thread ends its group. Not observed.
6. Windows: production unchanged; the new module and the new rule have not run on Windows yet (HOME-PC).

## 2026-11-17 — P5-A-R1: on POSIX a setup run whose worker's process group was not confirmed empty is never a success, a clean Cancel or a plain time-out; it fails as `containment-unproved` (identity not proved, nothing signalled) or `containment-incomplete` (signalled, emptiness not confirmed, including Linux's `signalled`); the worker's own result file is never replaced (independent-review remediation; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-A-R1 remediation instruction (2026-11-17). Start SHA `266d603`. Evidence: `files/dev-work/macos-p5a-r1/` (ignored): `repro-before.txt`, `contract.md` (both recorded before any production change), `after/`, `comparison.json`.

**The finding, reproduced at `266d603`** (independent review of P5-A; real disposable processes, seams only where named).
- `WorkerRun._finish()` ended the worker's group, and on `GROUP_UNPROVED` or `GROUP_REMAINING` only added a line to `run.protocol_errors`. It then returned `self.result()`: the worker's own published result. `protocol_errors` is not part of the result, so `optional_setup_client.run` (the wizard and Install & Continue) received an unqualified `succeeded`. `GROUP_SIGNALLED` recorded nothing.
- Same root, second path: `result()` called after the worker was reaped outside the run skipped `_finish()` and returned the published result with the group never judged (`group_end` None).
- Before (`repro-before.txt`): success + `unproved` (a real reap behind the run's back) → `succeeded`; direct `result()` after that reap → `succeeded`; success + `remaining` (a real SIGKILL with no time to confirm) → `succeeded`, also for an install success and through `client.run`; success + `signalled` (seam) → `succeeded`; a Cancel with unconfirmed cleanup → a clean `cancelled`. Already failures: no result (`no-result`), time-out (`timed-out`).

**Decision: no success without a confirmed end (POSIX only).**
- A POSIX run may return the worker's own result, or the cancelled/timed-out/no-result outcome it publishes in the worker's place, only when `group_end` is `GROUP_ENDED`: the kernel confirmed no member left.
- Otherwise the run's one outcome is `failed`, `forced`, with a new run-only error code (the worker never writes them):
  - `containment-unproved` for `GROUP_UNPROVED`: process identity uncertainty. The group's id could not be proved the worker's, so nothing was signalled; something may still run.
  - `containment-incomplete` for `GROUP_REMAINING` (a member still answered at the 15 s bound, or the signal was refused), for `GROUP_SIGNALLED`, and for any unknown answer: termination not confirmed.
- **`GROUP_SIGNALLED` assessed:** only non-darwin POSIX answers it (Linux, development only; not a shipped platform). SIGKILL was delivered while the id was proved, but a zombie leader is still a member there, so emptiness cannot be read without a process scan, which the project forbids. Without evidence the run does not vouch for its cleanup: it is not a success either. No production platform reaches it (macOS answers `ended`/`remaining`/`unproved`; Windows has its job).
- The containment failure keeps what the run would otherwise have said: the worker's own success and the components it verified, or "Cancelled …", "took too long", "without reporting a result", or why a result could not be trusted. `verified` is kept: those components were proved working, and the panel already shows them on a failure. `plan` is dropped: a plan answer is only usable from a success, and a retry plans afresh.
- **Publication.** With no worker result, the containment failure is what the run publishes in the worker's place (the same exclusive, atomic publication; held in memory when that is impossible). A result file the worker published is never replaced: it keeps the worker's own claim, and the run's outcome is settled once (`_outcome`), so every later `result()` returns the same failure.
- `result()` on POSIX now always goes through `_finish()`: the group is judged and the worker reaped first, also after a reap behind the run's back (which then is `containment-unproved`). The file-reading body moved unchanged into `_settle()`, which `_forced` also uses.
- `_finish()` also records `GROUP_SIGNALLED` and unknown answers in `protocol_errors`.
- **Unchanged:** `child_ownership` (the identity proof, the waitpid lock, reap-after-cleanup, the 15 s bound); `GROUP_ENDED` outcomes; Cancel (`cancelled`) and time-out (`timed-out`) with confirmed cleanup, and the `terminated`/`timed_out`/`stop_requested` flags; consent and installation protections; the Windows Job Object path, which has no group verdict and never consults it. No process scan, guessed pid or unverified `killpg` was added.
- **Changed existing pin:** `test_a_worker_reaped_behind_the_runs_back_never_has_its_group_signalled` expected `no-result`; it now expects `containment-unproved` (still a failure, and the missing result stays in its text). Nothing was weakened or skipped.

**Tests (this Mac, native; agent-reported).** `test_optional_tts_setup.py` +12 (11 POSIX-only, 1 every platform):
- success + `unproved` through `wait` and through `result()` alone (real reap behind the run's back; the grandchild is proved untouched, then ended by the test by identity);
- success + `remaining` (real SIGKILL, confirmation bound 0: the only seam), with bystanders in the test's group and in another session untouched;
- success + `signalled` (seam: the real end runs, the answer is renamed);
- an install success keeps `verified` but is not a success, and its text never reads "Installed and checked";
- no result + `remaining` publishes the containment failure;
- Cancel and time-out with confirmed cleanup keep `cancelled`/`timed-out` (2); with unconfirmed cleanup they are containment failures that keep their reason (2);
- the client (`optional_setup_client.run`) returns the containment failure;
- every platform: a run with a Job Object keeps the worker's own success, and the POSIX rule is never consulted.
- Red before the fix: 10 of these failed against `266d603` (`repro-before.txt`); the 6 already passing were the confirmed-cleanup, job, bystander and normal-exit cases.
- The 37 affected modules (`files/dev-work/macos-p5a-r1/affected-tests.txt`, P5-A's list) were compared by test id with P5-A's after-run (`files/dev-work/macos-p5a/after/outcomes.json`; its `scripts/` and `files/tests/` are identical to `266d603`): **0 new failures, 0 new skips, 0 removed, 0 changed outcomes; 12 added, all PASS** (`files/dev-work/macos-p5a-r1/comparison.json`). Totals 1,546 passed / 594 failed / 158 errors / 21 skipped (baseline 1,534 / 594 / 158 / 21). Every failure and error has the same outcome by id as in the baseline (the inherited ones P5-A recorded). The run took 1 h 50 min. Afterwards no test process remained.
- The 25 modules that read the edited documents (P5-A's `doc-tests.txt`), before and after the document edits: identical by id (1,635 passed, 100 skipped, 15 failed; `files/dev-work/macos-p5a-r1/docs/comparison.json`). The 15 failures are inherited: the four modules that hold them (`test_verification_gate_contract.py` 12, `test_cross_tool_consistency.py`, `test_gate_scratch_exception.py`, `test_macos_p1b_closeout_gate.py` 1 each) give the same 379 outcomes by id at `266d603` in a clean worktree, and none imports the changed code.
- Inherited, observed, not changed: after every run of `test_verification_gate_contract.py` (here and at `266d603` alike), two processes from its synthetic gate trees outlive pytest for up to a few minutes and then end by themselves: the inner pytest of `test_killing_the_gate_kills_its_tree_and_leaves_an_incomplete_run` (it SIGKILLs its gate and, on POSIX, ends only the grandchild, so the inner test finishes its 120 s sleep alone) and a synthetic `scaling/qualify.py` from its m4b-scaling tests. Nothing was signalled; after each wait no test process remained.
- Focused gate `2026-11-17_082412_focused_5388`, **RESULT: PASS**, exit status 0 (P5-A's selection, 1 min 32 s). Journeys, all PASS (9/9): `tts.edge-replay-direct-file`, `tts.edge-replay-folder-mixed`, `tts.service-failure-then-retry`, `tts.cancel-during-narration`, `tts.pause-at-file-boundary`, `tts.pdf-without-text`, `shutdown.tts-close-during-work`, `shutdown.tts-close-forced-landing`, `tts.kokoro-local`. pytest 116/116 (`test_engine_policy.py`, `test_child_ownership.py`); process-ownership, cleanup, skips (0), coverage inventory and tree PASS. It ran on the final code and tests (`266d603` plus this checkpoint's working tree); only the documents changed after it. Focused selection only, not full acceptance. Afterwards no test process remained.
- Protected: The 18 reference WAVs, 2 transcript files and 28 previews match; the 11 Kokoro files match by size and SHA-256; the `.venv/engines`, OmniVoice, model and package trees and the P4B–P5-A evidence folders are identical before and after (`files/dev-work/macos-p5a-r1/protected-before.json`/`protected-after.json`); the P4C and P5-A gate runs are untouched. The 17 owner deletions and the 5 untracked owner entries are untouched, and draft release `447445728` is unchanged (same asset, size, digest and update time).

**Gate policy (`verification.json`, Windows rule only).** `posix-process-groups-p5a` max 7 → 18 (the 11 new POSIX-only tests). Nothing that runs on Windows is skipped by it.

**Residuals (owner; not changed here).**
1. Windows: a job whose accounting still shows members at the bound records `lingering` in `protocol_errors` but keeps the worker's result (closing the job then ends them, kill-on-close). It is the same class of question, left unchanged as instructed; to be assessed with the Windows-native regression on HOME-PC.
2. The panel heads a containment failure "The voices could not be installed" even when `verified` names installed components; the message under it says what happened. GUI wording is out of this scope.
3. P5-A's residuals stand: `setsid` escapees; the first-run window is not a containment owner (the next P5-B candidate); the unlocked identity check in `Owner.shutdown`; an app killed in the at most 0.2 s after the worker exits.

## 2026-11-17 — P5-A: on POSIX the setup worker is never reaped before its process group is ended, and that group is signalled only while its id is proved to be the worker's own; `pyvenv.cfg` must carry `executable`, and `home` and `executable` must be absolute and name this copy's own Python; the checkout's world-writable modes are inherited, audited read-only and left for the owner (owner authorization of P5-A; implementation decisions by Claude Code; owner decisions pending)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P5-A authorization (2026-11-17). Start SHA `48fb12b`. Evidence: `files/dev-work/macos-p5a/` (ignored).

**A. The defect, reproduced at `48fb12b`.**
- `test_a_grandchild_left_behind_by_a_worker_that_exited_is_ended_with_the_run` failed natively (`repro-before.txt`): the worker (pid 48308) was gone and its grandchild (48309) alive, re-parented to launchd (ppid 1), still in process group 48308.
- Cause: `WorkerRun.wait()` (`Popen.wait`) reaps the worker the moment it exits, and `optional_setup_client.run` reaps it even earlier (`worker.process.poll()` in its loop). Once reaped, the worker's id, which is also its group's id, may be handed to another process, so `_finish` rightly had nothing safe to signal. Windows' Job Object ends the grandchild instead.
- The same held for a Cancel the worker obeyed within its grace (reaped by `wait(grace)`), for a crash, and for `kill_tree`'s `poll()`.

**Decision: reap last (POSIX only; Windows unchanged).**
- `child_ownership` gains `has_exited`/`wait_exited` (exit seen without reaping; macOS reads the zombie state, as `_has_exited` already did) and `end_led_group(proc, start_time)`.
- `end_led_group` signals only while a three-part proof holds, for the whole check-and-signal:
  1. the `Popen`'s own waitpid lock is held: every `Popen.wait`/`poll` reaps only under it (CPython bpo-38630), so nothing reaps the worker through its `Popen` meanwhile; the wait for the lock is bounded, and an object without one is never signalled;
  2. `returncode is None`: nobody has reaped it, so the kernel still reserves its id (a zombie keeps it), and no other process or group can have that id;
  3. its kernel start time equals the one recorded at spawn: no reap outside `Popen` handed the id on.
- It then repeats `killpg(SIGKILL)` until macOS answers `EPERM` (only the unreaped zombie leader is left; zombies are not signalled) or `ESRCH`, within 15 s, and never reaps. Linux (development only) answers `signalled`: a zombie leader is still a member there, so emptiness cannot be read.
- `WorkerRun`:
  - records the start time at spawn;
  - `running()` and every wait are non-reaping;
  - `_terminate` (Cancel past its grace, time-out) and `_finish` end the group through `end_led_group`, then reap;
  - `result()` on an exited, unfinished POSIX run finishes it first;
  - a group not proved, or not emptied in time, is recorded in `protocol_errors`, as Windows records lingering members; a group not proved is never signalled.
- A run whose process carries a Job Object keeps the released path exactly: `poll`, `wait`, `kill_tree`, terminate, accounting, close.
- `optional_setup_client.run` asks `worker.running()` instead of `process.poll()`.
- Partial start-up fails closed: on POSIX, `shared.child_ownership` must import before the worker is spawned, or the worker is never started (`containment-unavailable`).
- Outcomes are unchanged: the worker's own valid result stands; a worker that exits without one is a forced failure (`no-result`, with its exit status); Cancel gives `cancelled`, time-out `timed-out`.

**Why it is safe (measured on this Mac, `kernel_semantics.json`, `kernel_probe2.json`).**
- With the leader exited and unreaped, `killpg` reaches a live member, and SIGKILL ends it. With only the zombie leader left, `killpg` answers `EPERM`; after the reap, `ESRCH`. `getpgid` fails on the zombie, but its start time still reads.
- A group's id is its creator's id. The worker made its own session (`start_new_session`), so the group is the worker's, and its members descend from it. While the worker is unreaped, no other process can hold that id.
- Nothing is found by name, by a process scan or by a bare pid. Every wait is bounded. The existing identity rules of `child_ownership.py` are unchanged.

**Tests (this Mac, native; agent-reported).**
- `test_child_ownership.py` +7 (6 native): an exited, unreaped leader's group is ended and the kernel confirms it empty; a running leader's group (Cancel, time-out); never after a reap (the member is proved untouched); never for a mismatched or missing identity or an object without the lock; not while another thread holds the lock (bounded); unrelated processes untouched; the CPython lock the proof relies on exists (every platform).
- `test_optional_tts_setup.py` +8 `WorkerRun` tests on a real disposable app with real processes: a valid result stays valid when a grandchild outlives the worker; a Cancel the worker obeys; a crash (SIGKILL) is a failure, and its grandchild is ended; a worker reaped behind the run's back never has its group signalled (the grandchild is proved alive, then ended by the test by identity); bystanders in the test's own group and in another session survive a normal exit and a time-out; the client's loop no longer reaps; no ownership module, no worker; a run with a job keeps the released Windows path (every platform, recording stand-in job; the POSIX rule is never consulted). The original acceptance test also asserts, on POSIX, that the group was ended and confirmed empty.
- The 37 affected modules compared by test id with `48fb12b` (`comparison.json`): 0 new failures, 0 new skips, 0 removed; 28 added, all PASS; the grandchild test fixed.
- Focused gate `2026-11-17_053703_focused_61f2`: **RESULT: PASS** (9/9 journeys; pytest 116/116).
- After every run, no test process was left.

**B. `pyvenv.cfg` `executable` (decision).**
- Proved on this copy's bundled CPython 3.12.15 (`venv-probe/`): `venv` writes `executable = os.path.realpath(sys.executable)` unconditionally (`venv/__init__.py`, `create_configuration`), in the same step as `command`, which the rule already requires. Made through `python3.12`, `python3` and `python`, with `--copies`, through `child_entry.py` and after `--upgrade`, it always names `<copy>/files/runtime-data/python/bin/python3.12`. The production `.venv` does too.
- Rule now: `executable` must be present, absolute and exactly this copy's `python3.12` (either spelling of the copy: its path as given and its real path); `home` must be absolute. No legitimate environment can fail this, because one without `executable` has no `command` either.
- Also fixed: a relative `home` or `executable` was compared after `abspath`, so it matched whenever the check ran from the copy's own folder.
- Tests: 8 new tamper cases (no `executable`, empty, relative, this copy's `python3` and `python` aliases, the venv's own `python3.12`, an unnormalised path, an empty `home`), 2 relative-path cases run from the copy's own folder, and 3 contract cases (a venv made under each of the three names records its own `python3.12` and is accepted). Negative control: against the old rule, 5 of the new cases fail (no `executable`, the two aliases, relative `home`, relative `executable`).
- Windows is unaffected: this rule is reached only through the POSIX link rule. The accepted P4C-A link rules are unchanged.

**C. Permissions (read-only audit; owner decision pending).** `files/dev-work/macos-p5a/permissions-audit.md`.
- The checkout root, `scripts/`, `.git/`, most of `files/` and every root file are 777/666. They arrived with the checkout on 2026-11-14, as files copied from a Windows file system typically do. Everything made on this Mac since 2026-11-15, including every folder ACT created (`.venv`, the bundled Python, models, packages, OmniVoice), is 755/644. ACT's code never grants group or other write.
- No ACL beyond `deny delete` on `~` and `~/Desktop`; no foreign-owned entry; no sticky, setuid or setgid; no linked folder on the interpreter chain.
- The exposure is latent: `~/Desktop` is 700 and this Mac has one local account. It becomes real if the checkout, or a ZIP of it built on a Mac, is moved or copied where other accounts can reach. Through the 777 folders, another account could then change app code, launchers and git hooks, and rename and replace `.venv`, models and packages; the P4C-A launch rule refuses only a swapped interpreter chain. **The interpreter-link validation does not close this.**
- Proposed (not applied): `chmod -R go-w <repo>`, run by the owner, or the minimal targeted list in the audit; and normalising ZIP entry modes in release packaging (P6/P7).

**Residuals (owner).**
1. A descendant that leaves the group by itself (`setsid`/`setpgid`) cannot be reached by a group signal; finding it would need a process scan, which the project forbids.
2. **First-run window (inherited, reproduced, not changed):** `bootstrap.py` makes the first-run window an owner (`child_ownership.owner()`) for setup's own children, but never calls `subprocess_utils.enable_containment`. So `qwen3_process.spawn` starts the optional-voices worker with `start_new_session` only: not class A, not tied to that window's lifeline. The Python children the worker starts through `qwen3_setup.run_command` (pip, probes) lead their own sessions. A forced Cancel or time-out ends the worker's group, but not them (`firstrun-gap/result.jsonl`: child alive after a forced Cancel without an owner, ended with one). A cooperative Cancel still ends them through `run_command`. Install & Continue in the app window is not affected.
3. `Owner.shutdown` (app close) checks identity, then signals a class-A group without the waitpid lock. A reap in another thread between the two is the window `signal_if_same` has always had; macOS hands out ids sequentially, so a freed id is not reused until the id space wraps. Not changed.
4. If the app itself is killed in the moment between the worker's exit and the end of the run (one poll interval, at most 0.2 s, plus the bounded end), a grandchild still in the worker's group is left: nothing remains to signal it. Before P5-A this was the whole time after the worker's exit. ACT's own Python children of a class-A worker (app window) have their own lifeline to the worker and end with it regardless.

**Gate policy (`verification.json`, Windows rules only).** `native-macos-p1a` max 46 → 52 (6 new native tests). New `posix-process-groups-p5a` (max 7) for the new POSIX-only reason. New `posix-venv-interpreter-links` (max 56): the P4C-A POSIX-only reason had no Windows rule (43 skips there would have been "unexpected" on HOME-PC; found in P5-A), and P5-A adds 13. Nothing that runs on Windows is skipped by them.

## 2026-11-17 — P4C OWNER ACCEPTED: the macOS roster of 20 voices, the first-run choices, Kokoro and OmniVoice from the GUI, an OmniVoice Cancel and the Preferences & Data wording, checked by the owner; not an approval to merge or release (the owner; recorded by Claude Code)

Signed: the owner (acceptance given with the P5-A authorization, 2026-11-17); recorded by Claude Code (Opus 5.5), HOME-MacOS. Accepted at `48fb12b`.

- **The owner's own checks on HOME-MacOS (M4 Pro, 24 GB):**
  - exactly 20 macOS voices: 5 Edge, 9 Kokoro, 6 OmniVoice;
  - no Chatterbox Turbo or Qwen3 voice;
  - the first run shows Kokoro checked and OmniVoice unchecked, and no other optional choice;
  - Kokoro Heart generated an MP3 from the GUI;
  - OmniVoice Male 1 generated an MP3 using MPS float32;
  - OmniVoice Male 3 was cancelled during narration in 2.303 s, and no incomplete MP3 was published;
  - the Preferences & Data wording was accepted by hand.
- **Gate evidence kept:** the passing focused gate `2026-11-16_234204_focused_4cf5` (Option A entry below).
- **Not an approval to merge or release.** Nothing was merged, tagged, released or published; draft release `447445728` is untouched.
- **Authorized next:** only the bounded P5-A checkpoint (entry above). The rest of P5 waits for the owner's review of P5-A.
- P4C's two findings for the owner became P5-A's scope: the POSIX grandchild gap (fixed in P5-A) and the world-writable checkout (audited read-only in P5-A; correction pending the owner).

## 2026-11-16 — P4C Option A: on POSIX the setup worker's launch accepts the venv's own interpreter link only when the whole chain is proved to be this copy's own environment and Python; Windows' rule unchanged; Kokoro acquired through the fixed production route (owner authorization of Option A; implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS. Start SHA `aa9d3af`. The owner explicitly authorized Option A in this session.

**The defect, reproduced at `aa9d3af` (read-only).**
- `.venv/bin/python -> python3.12 -> <copy>/files/runtime-data/python/bin/python3.12`, a regular file. Both links were made by `python -m venv`, which setup's `create_venv` runs.
- `worker_launch` raised `wrong-interpreter`: "the app environment's console Python is missing or reached through a link". The worker's own `execution_home_problem` passed.
- The same "no link" rule guarded the acquirer's spaCy pip step (`RealAcquirer._acquire_spacy`), so a fresh Mac Kokoro install would also have stopped there.
- Ten real-child tests in `test_optional_tts_setup.py` already failed on the Mac for the same cause; they were counted among the baseline failures.

**Decision: one dedicated rule, `optional_setup_protocol.interpreter_problem(root, python)`.**
- **A real file** reached through no link: accepted everywhere, exactly as before (`venv_layout.unsafe_component`, unchanged).
- **Windows:** any link is refused, with the same words as before.
- **POSIX, when the interpreter is a link** (`_venv_link_problem`). Accepted only when all of these are proved:
  1. It is exactly this copy's `.venv/bin/python`.
  2. Nothing from the copy down to `.venv/bin`, or down to `files/runtime-data/python/bin/python3.12`, is a link. The copy's own folder may itself be reached through one, as everywhere.
  3. Each link sits in `.venv/bin` (named `python`, `python3` or `python3.12`) or beside the base Python (named `python` or `python3`). Each points to a plain name in the same folder or to a normalised absolute path. There are at most 4 links, so a loop ends.
  4. The chain ends at this copy's `python3.12`: a non-empty, executable regular file, and `samefile` agrees.
  5. Every link, folder and file on the way belongs to this account. `.venv`, `.venv/bin`, `pyvenv.cfg`, `files/runtime-data/python`, its `bin` and `python3.12` cannot be written by group or others.
  6. `pyvenv.cfg` is a file, not a link. Its `home` and `executable` name this copy's base, its `command` names this `.venv`, it is isolated, and it says CPython 3.12. The copy's path may be spelled as given or resolved.
- **Where it applies.** `worker_launch` uses it, as does the acquirer's spaCy pip step (same interpreter, same route).
- **The worker's own check.** `optional_setup_worker.main` now defaults to `worker_home_problem`: `execution_home_problem`, plus on POSIX `interpreter_problem` for the interpreter it was started as. A worker started some other way therefore refuses another copy's Python, which `execution_home_problem` alone accepted (tested). Windows' self-check is `execution_home_problem` alone, as before.
- **Unchanged.** The argv (`-E -s -m`), the environment scrub, containment (`qwen3_process.spawn`, class A through `child_entry.py` when the app owns it, a new process group otherwise), cancellation, the single result, consent, provenance, hashes and path checks.

**Why not the alternatives.**
- `--copies`, rebuilding `.venv` or changing the bundled Python: forbidden by the task, and they would hide the real layout every Mac copy has.
- Allowing links in `unsafe_component`: it guards every other path in the app.
- Comparing only `realpath`: it would accept any path that happens to land on the right file, such as `../../files/...` through other folders.

**The trust boundary, stated exactly.** Trusted:
- the copy's own folder, wherever it is and however it is reached (as before);
- the two named links (`.venv/bin`) and the bundled Python's own aliases;
- this account.

Refused:
- any link elsewhere on the way;
- any other Python;
- a moved or copied environment (its links and `pyvenv.cfg` name the first copy);
- other accounts' ownership or write access to what holds the chain.

**Why no other path protection is weakened.**
- `unsafe_component` and every other caller of it are unchanged.
- The exception covers one file name, in one folder, on POSIX, and only for a chain proved end to end.
- The exchange folder, request, result, consent and model paths keep their link refusals.

**Residuals (owner).**
1. **This checkout's folders are writable by any account.** The root, `scripts/`, `files/` and `files/runtime-data/` are `drwxrwxrwx`; the app's own folders (`.venv`, `python/`, models) are `755`. Any account on this Mac could change the app's code, whatever a launch rule says. The rule therefore checks only the owner of `files` and `files/runtime-data` (pinned by a test). It is not tightened here: the owner's permissions were not changed. Suggested owner action: remove group and world write from the checkout (`chmod -R go-w`).
2. **On POSIX, a grandchild left by a worker that exited normally is not ended with the run.** Windows' Job Object ends it. `WorkerRun._finish` acts only on a job. Cancel and time-out do end the worker's whole process group (`killpg`), and killing the owner ends both (tested).
   - The existing `test_a_grandchild_left_behind_by_a_worker_that_exited_is_ended_with_the_run` still fails on a Mac. It was a baseline failure (the launch refusal) and now fails for this reason.
   - Fixing it means signalling a group whose leader has already been reaped. The project deliberately avoids that (`child_ownership`: "a group is signalled only while its leader is an unreaped child"). That is a containment design decision, not taken here.
   - The production worker waits for its own contained children (probes, pip), so no stray is expected in normal runs.
3. **Corrupt bytes in an otherwise well-formed executable** cannot be judged by a launch rule. The OS refuses to run them: the worker never starts and the request's one result is a forced failure (tested).

**Tests.**
- **New in `test_optional_tts_setup.py`: 46 tests.** They use real `-m venv` environments built from each disposable copy's own clone of the bundled Python:
  - acceptance, including a venv made through the `python3` alias;
  - links: foreign copy, foreign installation, unexpected hop, relative escape, unnormalised absolute, dangling, loop, too long;
  - moved or copied environment;
  - redirected `.venv`, `.venv/bin`, `python/`, `bin/` and `python3.12`;
  - base Python missing, empty, a folder, or not executable;
  - eight kinds of `pyvenv.cfg` tampering;
  - group and world write on six members; another owner; the trust-boundary pin;
  - a non-console link;
  - the worker's self-check from the link, and a worker started by hand from another copy's Python refusing itself;
  - a consent changed after review refused by the real worker, with nothing spent or downloaded;
  - the owner killed, ending the worker and its grandchild;
  - a non-program base Python, which never runs;
  - Windows' rule and self-check, deterministic.
- **New in `test_optional_setup_acquisition.py`: 2 tests.** The spaCy pip step runs from this copy's venv link and refuses another copy's.
- **Existing tests adapted, none weakened.**
  - On POSIX, the `app` and `plain_app` fixtures give the copy its own base Python (setup's real layout). Windows builds as before.
  - Four Windows-shaped pins now name their platform:
    - the planned readiness (P4C: Chatterbox and Qwen3 `unsupported`, Chatterbox's engine `unproved`) and the number of probes;
    - `lingering`, which only a Windows job measures; on POSIX the test proves the worker's process group is gone;
    - the `files/runtime-data` listing, which on POSIX holds the copy's `python`;
    - the import-record lookup: on POSIX a process's own record, since there is no venv redirector.
- Run evidence is in the Handoff block and the roadmap (§19 P4C, Revision 3h).

## 2026-11-16 — P4C Kokoro acquisition stopped before any download: the app's setup worker cannot start on macOS; the in-process route used by P2 and P4B was not taken without the owner's say (decision by Claude Code under the owner's acquisition authorization)

Signed: Claude Code (Opus 5.5), HOME-MacOS. HEAD `a713789`.

- **Authorized:** the 11 pinned `KOKORO_FILES` only, through the app's existing consented installer, without bypassing its safeguards; stop and report on any blocker.
- **Found:** `optional_setup_protocol.worker_launch` refuses `.venv/bin/python` because it is a symlink, and `python -m venv` (the app's `bootstrap.create_venv`) always makes it one on POSIX. Both GUI install routes (first-run setup, Install & Continue) go through it. All 11 files were missing; nothing was downloaded.
- **Why stop rather than call `RealAcquirer` in-process as P2 and P4B did:**
  - That route keeps the plan, consent, byte budget, scoped opener, hash checks and atomic writes.
  - It drops the worker launch's interpreter-link refusal and its process-group containment. Those are installer safeguards this authorization did not lift.
  - Passing the gate either way needs a code change or a new authorization: both are stop conditions.
- **Recommended fix (needs its own authorization):** on POSIX, accept the venv's interpreter link only when `.venv` itself is not a link and the link resolves to the app's base Python inside this copy. Tests use a real `-m venv` environment. Windows is unchanged.

## 2026-11-16 — macOS P4C independent-review remediation: the sample helper checks explicit voice patterns once, before anything runs, in ordinary samples, `--quality-suite` and `--final-acceptance`; on a Mac a pattern naming a Chatterbox or Qwen3 voice refuses the whole request (exit 2), and an empty selection is never a success (exit 1, every platform); the Mac's incompatible-Python and engine-lock wording names only offered engines. P4C still owner acceptance pending (implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS, under the owner's P4C remediation task after the independent review of `24398fe`. Start SHA `24398fe`.

**The finding, reproduced at `24398fe`.** The engine guards held: no blocked engine could synthesise. The false success was in selection and reporting.
- On a Mac, `--quality-suite chatterbox`, `--final-acceptance chatterbox` and `--final-acceptance qwen3` selected no voice. Each reported "0/0", exited 0 and (re)wrote its manifest.
- Mixed requests ran their offered part: `--quality-suite chatterbox kokoro` ran the nine Kokoro voices, and `--final-acceptance qwen3 omnivoice` the six OmniVoice voices.
- Ordinary `chatterbox Steffan` and `"Female 1"` printed NOT OFFERED, made one sample and exited 0.
- On every platform, `--quality-suite` or `--final-acceptance` with a pattern that matched nothing reported "0/0" and exited 0.

**Decisions.**
- **One check.** `generate_voice_samples._explicit_selection` is used by `main()` for all three pattern modes, before any runner, folder or manifest is touched. `run_quality_suite` and `run_final_acceptance` call it too, for other callers. The policy stays in `shared.engine_policy` (`_refused` asks `is_offered`).
- **Fail before synthesis, the whole request.** A pattern that names any voice the platform does not offer refuses the request, whether it stands alone, sits beside offered patterns, or matches through a shared word ("Female 1" names the OmniVoice, Chatterbox and Qwen3 Female 1 voices). Each such voice is reported NOT OFFERED, the run says nothing was synthesised or written, and it exits 2.
  - Chosen over "run the offered part and exit nonzero": a partial run would still make samples and rewrite manifests for a request the platform refuses. The documented semantics (substring filters) do not need partial runs.
  - Exit 2 matches P4C's refusal of the Chatterbox and Qwen3 evaluation modes. P4C's own pin of plain `chatterbox` therefore changes from 1 to 2.
- **An empty selection is never a success.** In every mode and on every platform, patterns that select no voice exit 1 with "No voice matched", and the two reporters return 1 when there are no rows.
  - This changes Windows only where Windows reported a false "0/0" success: `--quality-suite` or `--final-acceptance` with a pattern that matched nothing.
  - Every Windows request that selects voices runs exactly as before. No pattern still means every offered voice (34 on Windows, 20 on a Mac).
- **Wording: an audit of P4C's two acknowledged exceptions.** Changed only where a Mac reaches the text in ordinary setup, repair or Clear Downloaded Data. Each site takes Windows' words verbatim or the Mac's, chosen through `engine_policy.is_offered`:
  - `bootstrap.assess_venv_health`, an existing `.venv` on an incompatible Python: a Mac says "the local Kokoro voices".
  - `bootstrap._take_engine_lease`: when the locks cannot be checked, "whether the OmniVoice voices are in use". The "held still" log line names OmniVoice only. A refusal from the Qwen3 folder is logged as the shared install locks.
  - `engine_lease.EnvironmentLease`: on a Mac, the Qwen3 folder holds only the shared `setup.lock`. Its "could not check" message is therefore `SHARED_UNAVAILABLE_MESSAGE` ("whether voices of this copy are being installed or repaired").
  - `maintenance.engine_uncheckable_problem()`: `WINDOWS_` and `MAC_` constants, with `ENGINE_UNCHECKABLE_PROBLEM` the running platform's, as `CATALOG` is. `cleanup_worker.hold_engine_still` returns it at call time, and its note for a Qwen3-folder refusal matches.
  - `qwen3_setup.InstallLock`: a Mac's Kokoro and spaCy installs meet its two "already being installed" refusals (the in-process lock and `setup.lock`) while another install or a repair runs. A Mac says "Voices of this copy of the app …".
- **Left unchanged: not reachable in ordinary Mac workflows.**
  - `find_suitable_python`'s "Kokoro/Chatterbox" log line and setup's "Setup finished with limits" message: a Mac selects only the app's hash-pinned Python 3.12 (P1A).
  - The inference- and engine-lock sentences of `InstallLock` and `engine_lease.BUSY_MESSAGES`: only a Qwen3 conversion or worker holds those locks.
  - `qwen3_runtime`'s linked-folder refusal: only a tampered copy reaches it.
  - Qwen3's Windows-only messages.
  - Historical documents and implementation comments.

**Tests.**
- `files/tests/test_engine_policy.py` gains 43 tests (80 in all):
  - Mac refusals in all three modes, including mixed and shared-word requests: exit 2, no synthesis, nothing written, every refused voice named, no success words;
  - Mac offered requests and each mode's no-pattern default;
  - the same requests on Windows;
  - no-match patterns on both platforms;
  - the runners' own refusals and the empty reports;
  - the Mac and Windows texts of each changed message, through the real `assess_venv_health`, `_take_engine_lease`, `EnvironmentLease`, `hold_engine_still` and `InstallLock`.
- Three existing pins now name their platform:
  - `test_cleanup_engine_lease`: its sandbox runs as `win32`, so it compares with `engine_uncheckable_problem()` and pins Windows' text.
  - Two `test_omnivoice_layout` repairs take the `windows_engine_policy` seam for their Windows wording.
- Run evidence is in the Handoff block and the roadmap (§19 P4C).

## 2026-11-16 — macOS P4C: one platform capability policy (`scripts/shared/engine_policy.py`) decides the voice engines; macOS offers Edge 5 + Kokoro 9 + OmniVoice 6 = 20 voices and refuses Chatterbox Turbo and Qwen3-TTS at every surface and entry point; Windows keeps all 34. P4C IMPLEMENTED and TESTED (automated); owner acceptance pending (implementation decisions by Claude Code)

Signed: Claude Code (Opus 5.5), HOME-MacOS (Apple M4 Pro, 24 GB), under the owner's P4C authorization (2026-11-16) and §12.F Revision 3. Start SHA `d2b2eae`.

**The policy (one module, standard library only).**
- `shared/engine_policy.py` answers which engines a platform offers. It reads `sys.platform` when asked (`current_platform`, the one seam tests replace); every function also takes an explicit `platform=`. There is no setting, toggle or compatibility mode.
- macOS (`darwin`) offers `edge`, `kokoro`, `omnivoice`. Every other platform offers all five engines, so Windows is exactly as released and Linux keeps today's behaviour (each engine's own gates).
- It lives in `shared/` because the first-run setup imports it in the base interpreter before the app's environment exists, as it does `optional_setup_protocol`. It imports nothing of the app, so `tts.voice_registry` can ask it without a cycle.
- One refusal, `EngineNotOffered`, with one message: "<Engine> voices are not available in this app on macOS, so nothing was started, installed or downloaded. Choose a Microsoft Edge TTS, Kokoro or OmniVoice voice instead."

**Where it is asked (narrow guards; nothing duplicated or deleted).**
- Registry: `voice_registry.offered_voices`/`offered_labels`; all 34 rows stay, `display_labels()` and every lookup are unchanged. The registry refuses a default voice that either platform would not offer.
- TTS panel (`epub2tts_gui`): the dropdown lists the offered labels; a restored, imported or stale selection of a non-offered engine becomes the default voice and is logged; Start and Retry Failed refuse such a voice with the message before anything is frozen, reserved, installed or synthesised; the conversion worker (`_RunContext.execute`) asks again before any engine module is imported and settles a refusal as a job failure; the "Install / repair Qwen3 voices" button is never offered where Qwen3 is not.
- Engine entry points: `chatterbox_file_to_mp3`, `synthesize_text_to_wav`, `synthesize_text_to_mp3` and the model loader `_get_model`; `qwen3_file_to_mp3`, before the source is read or the availability seam is asked.
- Setup: the wizard's choices (`bootstrap.optional_choices_for("darwin")`: Kokoro checked as released, OmniVoice unchecked, no Qwen3 note); `voice_install.component_for` (so Install & Continue never offers one); `optional_setup.plan`/`estimate` (a non-offered component is UNSUPPORTED with the message, never checked, consented, acquired or repaired; the plan's Mac limits, Qwen3 line and base-package note name no other engine); `RealAcquirer.acquire` refuses any unit of a non-offered component before disk, network or process; `optional_setup_health.local_health` never probes Chatterbox there.
- Sample helper and CLI (`generate_voice_samples`): offered voices only; a Chatterbox or Qwen3 pattern is reported "NOT OFFERED" and fails the run; the Chatterbox and Qwen3 evaluation modes exit 2; the per-voice dispatch refuses first.
- Wording: the launcher's TTS line, Clear Downloaded Data's two engine-naming items and Repair App Environment's confirmation have Mac versions naming OmniVoice (the engine a Mac keeps in `.venv/engines`); Windows' words are byte-identical.
- Coverage of the cleanup coordinator: `maintenance.py` now imports the policy, so the coordinator's module closure is seven files (`test_cleanup_worker.COORDINATOR_MODULES`), as `venv_layout` and `engine_lease` joined it before. The real coordinator runs from the real `scripts/` tree.
- The planning bridge's reviewed closure (`optional_setup_planning_bridge_v3.SOURCES`) gains `shared/engine_policy.py`.

**Deliberately not changed.**
- The Mac's base environment keeps `chatterbox-tts` as a dormant pinned dependency, and the base install's import probe (`REQUIRED_IMPORTS`) still checks it (§12.F: no slimming). That probe is base-environment integrity, not an engine install.
- `qwen3_setup`'s and `qwen3_runtime`'s own Windows-only refusals stay; they agree with the policy.
- Setup messages for an incompatible Python that name "Kokoro and Chatterbox" (reachable only without CPython 3.11/3.12; a Mac uses the app's own 3.12), and engine-lock messages naming Qwen3 ("the Qwen3 or OmniVoice voices are in use"), are left for P5/P6a wording review. Neither invites choosing or installing an engine.
- Windows' "Kokoro/Hugging Face data downloads again when needed" (Clear Downloaded Data) predates v0.7.0's consented installs and is stale; it is a Windows wording follow-up, not changed here.

**Tests.**
- New `files/tests/test_engine_policy.py` (37 tests): both rosters by identity and label, headings, default, the six OmniVoice voices and their recordings; the wizard (data and a real Tk window, with and without Kokoro's skip); plans, estimate, consent, acquirer and health; Install & Continue; the panel's list, stale selection, Start, worker and Retry; the engine entry points; the sample helper; launcher, maintenance and repair wording; no setting carries a voice. Windows rows run through the policy's seam.
- Adapted (macOS behaviour P4C deliberately changes; every assertion still exact): the five-choice wizard pins now read `optional_choices_for("win32")` and pin a Mac's two; the OmniVoice dropdown test is parametrized 34/20; the darwin Qwen3 plan reason is the policy's; the environment item's wording is pinned for both platforms; the coordinator closure has seven modules. A `windows_engine_policy` fixture (conftest) is available to Windows-behaviour suites.
- Run evidence is in the P4C Handoff block and the roadmap (§19 P4C).

## 2026-11-16 — P4B OWNER ACCEPTED with its documented memory performance exception: the Mac-GPU worker keeps its 16-chunk bound (48 on Windows CUDA and the Mac's CPU), no `torch.mps.empty_cache()` policy is adopted, and no further P4B memory optimization is authorized; P4C authorized (owner decision; recorded by Claude Code)

Signed: the owner (decision); recorded by Claude Code (Opus 5.5), HOME-MacOS, at `d2b2eae`.

**Decision.**
- P4B is **OWNER ACCEPTED** with its memory-performance exception.
- Kept: at most 16 chunks per OmniVoice worker on a Mac's GPU (`omnivoice_synth.MPS_CHUNKS_PER_WORKER`), 48 on Windows CUDA and on a Mac's CPU (`CHUNKS_PER_WORKER`), as committed in `dc7b1ed`.
- No per-chunk, every-N or threshold `torch.mps.empty_cache()` is adopted (option B, entry below).
- No further P4B memory optimization is authorized. Work on the per-shape caching would need a new, separate authorization.
- P4C is authorized (the entry above).

**The exception, as measured (kept on record, not re-measured).**
- Book-like text (Male 1, 48 long, all-different paragraphs) at the 16-chunk bound peaks at 10,745–11,131 MiB, 5–9 % over the provisional 10 GiB footprint target; worker growth after warm-up is +20 to +31 % there and +10.6 % on the 60-chunk sequence, against the provisional < 10 %.
- No memory-pressure event and no swap in any 16-chunk run; S is PASS; the audio is bit-identical to the 48-chunk runs.
- The provisional D6-O targets are unchanged as written (MPS wall RTF ≤ 1.0, CPU wall RTF ≤ 3.5, footprint ≤ 10 GiB, growth < 10 %). They stay practicality targets, not rejection thresholds; this acceptance is an owner exception against them, not a new target.
- The accepted MPS speed exception (P4A acceptance entry) is unchanged.

**Correction applied with this decision (documents and one code comment only).**
- The comment above `MPS_CHUNKS_PER_WORKER` (`scripts/tts/omnivoice_synth.py`) and the feature map's macOS OmniVoice bullet (`files/dev-work/feature-map/tts-audiobook.md`) repeated the memory checkpoint's wrong cause ("GPU buffers kept by PyTorch's MPS caching allocator").
- They now say what option B measured: `torch.mps.empty_cache()` frees one chunk's working space that the next chunk takes back and does not stop the growth; the accumulating memory is GPU memory outside PyTorch's free pool plus the CPU heap. Per-shape MPSGraph resources are the likely cause, stated as inferred, not proven.
- No production behaviour changed: OmniVoice generation, worker rotation, model pins, reference identities and audio processing are untouched.

## 2026-11-16 — macOS P4B option B (MPS cache clearing) feasibility: `torch.mps.empty_cache()` gives no meaningful, repeatable memory improvement. Recommendation: keep the present 16-chunk behaviour and adopt no clearing policy. The memory exception stays OWNER DECISION PENDING; P4B is not owner accepted; P4C has not started

Signed: Claude Code (Opus 5.5), HOME-MacOS (Apple M4 Pro, 24 GB), under the owner's option-B authorization: one final bounded feasibility experiment, no production change, no new policy without the owner's review. Start SHA `dc7b1ed`.

**Method.**
- **Same as the memory checkpoint:**
  - the installed engine: model `c5fdb5cc`, OmniVoice 0.2.1, MPS float32;
  - the production `GENERATION` settings, seeds, `v1` speech preparation, assembly and encode, and the production 16-chunk MPS bound;
  - the book-like text: Male 1, 48 all-different paragraphs of 229–293 characters, 984 s of audio, 3 workers of 16 chunks.
- **How the clearing ran (experiment only).**
  - It ran in a generated, ignored copy of `omnivoice_worker.py`, reached only through `omnivoice_file_to_mp3`'s `script` seam.
  - It acts at the post-chunk boundary: after the chunk's audio is written, synchronized and its memory measured, and before its event is sent. When due, it synchronizes, calls `torch.mps.empty_cache()`, synchronizes again and measures again.
  - `gen_s` is taken before the clear, and nothing is cleared after a worker's last chunk.
- **The variants:**
  - `control`: the production worker, unchanged;
  - `every4`: after every 4th chunk of a worker;
  - `thr8192`: after any chunk whose measured footprint is at least 8,192 MiB.
- **Tools and evidence:**
  - The driver `files/dev-work/macos-p4b/q/cache-exp/run_cache_exp.py` and `analyse.py` (ignored, not committed) reuse `macos_p4b_omnivoice_qualify`.
  - Evidence is in `q/cache-exp/` (ignored).
  - No tracked file changed during the experiment.

**Results.**

| Run | Clears | Worker lifetime peaks | Highest chunk-end footprint | Worst worker growth | Max MPS driver | Pressure / swap | Wall s (RTF) | Chunk generation vs control | Clear cost |
|---|---|---|---|---|---|---|---|---|---|
| control (16, no clear) | 0 | 11,131 / 9,988 / 10,360 MiB | 11,131 MiB | +31.2 % | 7,179 MiB | normal / 0 | 931.7 (0.947) | — | — |
| every4 | 9 | **13,944** / 10,297 / 9,994 MiB | 10,844 MiB | +33.4 % | **10,277** MiB | normal / 0 | 985.1 (1.001) | +5.8 % (already +11 % on chunks 0–3, before any clear) | 0.192 s in all (mean 21 ms, max 26 ms) |
| thr8192 | 20 | 10,931 / 9,907 / 10,086 MiB | 10,490 MiB | +27.7 % | 7,179 MiB | normal / 0 | 919.2 (0.934) | −1.4 % | 0.360 s in all (mean 18 ms) |

- **Audio.** Every variant's MP3 (`ef0910ad…71b6`) and all 48 chunk hashes are identical to the control's, and to D and V1 from the memory checkpoint.
- **Repeat and noise.**
  - The same 16-chunk production code peaked at 10,745 MiB in V1 and 11,131 MiB here, so a peak varies about 400 MiB between identical runs.
  - Chunk generation time varies up to about 11 % between runs.
- **Containment and Cancel, with clearing after every chunk** (the `every1` copy, so clearing is on the stopping path):
  - CX-3 Cancel: 2.13 s (bound 4 s). Worker group empty, nothing published.
  - KX-1(c): worker group gone 0.083 s after the owner's SIGKILL (bound 3 s). Nothing published, no process left.

**What `empty_cache` recovers, and what it cannot.**
1. **Allocator recovery is real but small and fixed.**
   - Every clear released exactly 2,096 MiB of MPS driver memory after a long chunk, or 1,072 MiB after a shorter one: PyTorch's pool holding one chunk's working space.
   - Live tensors stayed at 2,336 MiB.
   - The worker's footprint read straight after the clear did not drop yet. Metal gives the memory back a moment later; `footprint -p` at chunk 11 showed about 1.1 GB less, in "Owned physical footprint (unmapped) (graphics)".
2. **The next chunk takes it straight back.**
   - In `thr8192`, 35 of 48 chunk ends have MPS driver memory exactly equal to the control.
   - The 13 that differ are shorter chunks that followed a cleared long chunk, each exactly 1,024 MiB lower: the long chunk's extra working space. The next long chunk takes it again.
   - Peaks happen at long chunks, so they are unchanged.
3. **The growth is below what `empty_cache` can reach.**
   - The driver memory left after each clear rose in every worker. In `every4`, from the 4th to the 12th chunk: 3,152 → 4,466, 3,258 → 4,417 and 3,384 → 4,425 MiB. `thr8192` was the same: 3,656 → 4,883, 3,631 → 4,577 and 3,697 → 4,942 MiB. That is about 120–180 MiB a chunk.
   - The CPU heap's "Malloc Small" (MPSGraph structures) was about 860 MiB at chunk 15 in all three runs.
   - At chunk 15, "IOAccelerator (graphics)" was 2,696–2,729 MiB in all three.
   - So the accumulating memory is GPU memory outside PyTorch's free pool, plus the CPU heap. Both grow with each new chunk shape and are freed only when the process ends.
   - Its likely owner is the Metal resources of the MPSGraph executables compiled per shape (`heap`: +466 executables in 10 chunks). That is inferred, not proven.
4. **Clearing can make things worse.**
   - In `every4`'s first worker, chunk 15 ended with 10,277 MiB of driver memory against the control's 7,179, and the worker peaked at 13,944 MiB against 11,131.
   - This was not seen in its other workers or in `thr8192`. It is unexplained, and only one occurrence was observed.

**Correction to the memory-checkpoint entry below.**
- It said about 88 % of the growth is "GPU buffers kept by PyTorch's MPS caching allocator".
- That is wrong as a cause. The allocator does keep about 1–2 GB of working space between chunks, but it does not accumulate. The GPU growth is in memory `empty_cache` cannot release.
- The same wording is in the comment above `MPS_CHUNKS_PER_WORKER` (`scripts/tts/omnivoice_synth.py`) and in the feature map's macOS bullet. Neither was edited, because this was a feasibility run. Correct them when the owner decides the final memory behaviour.

**Not run.** The `every1` memory run was not run. `thr8192` already cleared after consecutive chunks (11–14, 25–29, 41–46), which is every-chunk clearing over those stretches, and the pool released is fixed. That leaves no material uncertainty, as the owner's condition required.

**Recommendation.**
- Keep the present behaviour: a fresh worker every 16 chunks on the Mac's GPU, and 48 on Windows and the Mac's CPU, as committed in `dc7b1ed`.
- Adopt no cache-clearing policy. It gives no repeatable memory improvement: peaks are unchanged within run-to-run noise, the growth is untouched, and one clearing run peaked 2.8 GB higher. Its only measured benefit, about 1 GB lower after a shorter chunk, does not lower any peak.
- **Throughput:** a clear costs about 20 ms, which is negligible. Run-to-run variation hides any effect on the next chunk.

**The remaining exception, unchanged in kind.**
- Book-like text at 16 chunks peaks at 10.7–11.1 GB, 5–9 % over the 10 GiB target.
- Worker growth after warm-up is +20 to +31 % on book-like text and +10.6 % on the 60-chunk sequence, against < 10 %.
- S: PASS. There was no pressure event and no swap in any run.

**What is left for the owner.**
- Accept the exception with the 16-chunk bound.
- Or authorize work on the per-shape caching itself. That would need a different, separately authorized approach: a shorter bound with diminishing returns, or limiting distinct shapes, which would change the model's input and need listening.

**Status.** P4B is NOT owner accepted. P4C has not started. Nothing was merged, tagged or released; draft release `447445728` is untouched. A third KX-1 job folder (the killed owner's) waits for the 24-hour stale cleanup.

## 2026-11-16 — macOS P4B memory checkpoint: a 16-chunk worker bound on the Mac's GPU reduces the memory exception but does not close it. OWNER DECISION PENDING; P4B not owner accepted; P4C not started

Signed: Claude Code (Opus 5.5), HOME-MacOS (Apple M4 Pro, 24 GB). This was the owner's authorized memory checkpoint: one bounded Mac-only investigation, worker lifetimes 48 / 24 / 16 only, no per-chunk cache clearing, no downloads. Start SHA `ce67630`.

**Summary.**
- On the Mac's GPU, memory growth comes from PyTorch's MPS caching allocator keeping GPU buffers, plus MPSGraph caches compiled for each new chunk shape.
- On a book-like text, one 48-chunk worker reached 13.6 GB, with memory pressure and swap.
- A bound of 16 chunks per worker on the Mac's GPU was implemented. It cuts the worst measured peak to 10.7 GB, with no pressure, no swap and bit-identical audio. Windows and a Mac's CPU keep 48.
- The peak and growth targets are still missed: **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**, reduced, not closed.

**Correction to the P4B entry below.** It says "no worker exceeds about 6.9 GB however long the book". That is true only for short chunks. On book-length chunks, one 48-chunk worker reached 13,590 MiB (run D).

**Method.**
- **Same conditions in every run:**
  - the installed production engine: model `c5fdb5cc`, OmniVoice 0.2.1, MPS float32;
  - the production `GENERATION` settings and seeds;
  - `v1` speech preparation, assembly and one encode, through `omnivoice_file_to_mp3`.
- **The harness:** the dev-only `macos_p4b_omnivoice_qualify.py long`, extended with:
  - the `chunks_per_worker` test seam;
  - per-chunk SHA-256 of the audio;
  - per-worker growth and start-up time;
  - swap and memory-pressure readings per chunk;
  - `footprint -p` and `heap` snapshots;
  - a safety cancel at 14 GiB.
- **Evidence:** `files/dev-work/macos-p4b/q/memory/` (ignored).
- **The baseline:** A is P4B's own record and was not rerun. P4B's original CX-3 and KX-1 records were copied to `q/p4b-original/` before the reruns.

**Controlled comparison: the P4B 60-chunk sequence** (Female 2, one-sentence chunks of 74–89 characters, 366 s of audio).

| Run | Bound | Workers | Peak footprint | Worst worker growth after a 5-chunk warm-up | Max MPS driver | Start-up per worker | Wall RTF | Audio |
|---|---|---|---|---|---|---|---|---|
| A (P4B) | 48 | 48 + 12 | 6,900 MiB | +28.4 % | 4,135 MiB | not recorded | 1.312 | MP3 `4e6b17f5…a28` |
| B | 24 | 24 + 24 + 12 | 6,459 MiB | +19.5 % | 3,964 MiB | 4.0–5.4 s | 1.223 | identical MP3 |
| C | 16 | 16 × 3 + 12 | 5,922 MiB | +10.5 % | 3,840 MiB | 3.7–4.0 s | 1.285 | identical MP3 |
| V2 (production default, after the change) | 16 | 16 × 3 + 12 | 5,919 MiB | +10.6 % | 3,840 MiB | 2.8–4.4 s | 1.296 | identical MP3 |

- **Truncation, not change.** A bound cuts the same memory curve short; it does not change the curve.
  - B's first worker matched A's first 24 chunks within 5 MiB (4,936 → 6,411 against 4,933 → 6,406).
  - Every restart brought the footprint back to 4.9–5.0 GB.
  - Inside one worker the footprint grows about 50–58 MiB a chunk and never levelled off.
- **Integrity.** In B, C and V2 the MP3 and all 60 per-chunk SHA-256 are identical. Every chunk was produced once, in plan order, and the bound changes no audio.
- **Speed.**
  - The wall-time differences are run-to-run variation. B was 8.6 % faster than A even on chunks 0–23, where both use the same fresh worker.
  - The real cost of a shorter bound is the start-up of each extra worker: 2.8–5.4 s, of which 0.8–1.8 s is the model load. That is about 2 % on short chunks and about 1 % on long ones.
- **System.** No memory-pressure event and no swap-out in A, B, C or V2.

**The book-like case** (D, then V1): Male 1 on 48 all-different paragraphs of 229–293 characters, 984 s of audio.

| Run | Bound | Peak footprint | Max MPS driver | Worst worker growth | Memory pressure | Swap-outs | Wall RTF |
|---|---|---|---|---|---|---|---|
| D | 48 | 13,590 MiB | 10,453 MiB | +59.5 % | reached the warning level (2) | +26,400 pages (about 412 MiB); swap file 2 → 3 GB | 1.029 |
| V1 (production default, after the change) | 16 | 10,745 MiB (workers 10.6, 10.2, 10.7 GB) | 7,179 MiB | +31.4 % | normal (1) after every chunk | 0 | 0.979 |

V1's MP3 and all 48 chunk hashes are identical to D's.

**Root cause (measured).**
1. **Reusable allocator cache retention: the main part.**
   - The live MPS tensors stay at 2,336 MiB after every chunk in every run, while the MPS driver memory grows (D: 3,721 → 10,142 MiB).
   - In `footprint -p`, "IOAccelerator (graphics)" rose from 1,111 MiB at chunk 5 to 5,553 MiB at chunk 47. That is about 88 % of the footprint's +5,047 MiB.
   - PyTorch's MPS caching allocator keeps the GPU buffers freed after each chunk, sized for that chunk's shapes, and does not hand them back while the process lives.
2. **CPU-side caches for each shape: the second part.**
   - "Malloc Small" grew from 524 to 1,544 MiB in D (chunks 5 to 47).
   - `heap` (run E: Male 1, the first 12 paragraphs, chunks 1 and 11) shows malloc'd blocks going from 1.98 M to 5.50 M (340 → 676 MB).
   - The growing types are Apple MetalPerformanceShadersGraph objects: +466 `MPSGraphExecutable` (compiled graphs), their device, runtime and shape-function caches, MLIR storage caches and `MPSNDArray` objects. These are graphs compiled per operation and input shape.
   - 258 MB of the growth is untyped ("non-object"). Its owner was not identified; that would need MallocStackLogging.
3. **It depends on chunk shape and size.**
   - It grows only on new shapes. P4A's 50 repeats of one text grew +1.11 %, with MPS driver memory flat.
   - Varied short chunks add about 55 MiB a chunk; long chunks about 120 MiB (about 108 MiB of it MPS driver memory).
   - Male 1's slower speech gives longer audio and larger tensors.
4. **It is not prompt retention, temporary-tensor retention or ACT data.**
   - The clone prompt is loaded once per worker from its cache.
   - The worker writes each chunk's audio to disk and keeps only counters (read in the code).
   - Live tensors stay flat.
5. **Part of each peak is transient.**
   - "Malloc Large" differs by up to about 1.5 GB between runs at the same chunk: D 11,451 MiB against E 9,977 MiB at chunk 11.
   - The MPS driver memory there was identical, 6,562 MiB.
6. **Uncertain.**
   - The run did not show whether the caches level off with enough distinct shapes. D's growth slowed between chunks 25 and 40, then rose again.
   - The untyped 258 MB is unattributed.

**What was implemented** (within the authorization).
- `omnivoice_synth.MPS_CHUNKS_PER_WORKER = 16` and `chunks_per_worker_for(policy)`: a run on the Mac's GPU starts a fresh worker every 16 chunks.
- Windows (CUDA) and a Mac's CPU keep `CHUNKS_PER_WORKER = 48`.
- The entry point's `chunks_per_worker` seam now defaults to `None`, meaning the run's device bound. The GUI and the sample path use the default.
- Nothing else changed: model, generation settings, references, the worker, Cancel and containment.

**Why 16, not 24.**
- On the owner's comparison it gave the lowest peak (5,922 against 6,459 MiB) and growth (+10.5 % against +19.5 %).
- On the book-like text it cut the peak by 21 % and kept the system out of memory pressure and swap.
- The audio is bit-identical.
- The cost is one start-up of about 3–4.5 s per 16 chunks.

**Why only the GPU.** The mechanism is the MPS allocator and MPSGraph. CPU fp32 grew +2.6 % over 20 chunks in one worker (V4), so there is no evidence of a CPU problem.

**Verification of the change.**
- **Memory:** V1 and V2 above, through the production default with no seam.
- **V3, CX-3 Cancel on MPS:** 2.41 s (bound 4 s). The worker group is empty, nothing was published and no job folder was left.
- **V4, CPU fp32** (Female 2, 20 chunks): PASS. One worker (the 48 bound), peak 3,011 MiB, growth +2.6 %, wall RTF 1.873 on short chunks (target ≤ 3.5).
- **V5, KX-1(c):** the worker group was gone 0.09 s after the owner's SIGKILL (bound 3 s). Nothing was published and no process was left. The killed owner's job folder stays until the 24-hour stale cleanup, as in P4B; there are two such folders now, both from KX-1 runs.
- **Tests:**
  - `test_omnivoice_synth.py` gained 2 tests (4 cases): the bound per device (48 on Windows, 16 on MPS, 48 on a Mac's CPU), and 50 chunks through the default in plan order (Windows 48 + 2, MPS 16 × 3 + 2, CPU 48 + 2). They were written first and seen failing.
  - Nine affected modules (OmniVoice synth, reference, GUI, layout and speech; chatterbox evaluation; epub retirement; speech pipeline; verification coverage): 814 passed, 4 skipped, 36 failed.
  - All 36 failures are in `test_omnivoice_layout.py`, Windows-simulation tests that fail the same way at `ce67630`. None are new.
- **Bookkeeping:** `coverage.json` restamped for `omnivoice_synth.py`; the feature map's Mac bullet updated.
- **Protected assets,** before and after: 18/18 references, both transcript files, 28/28 previews.
- **Windows:** `CHUNKS_PER_WORKER` stays 48, and a Windows run batches 48 + 2 (test pinned to win32). No Windows machine was used; the HOME-PC regression is in P5.

**P verdict against D6-O** (provisional targets), after the change:
- *Peak ≤ 10 GiB:* met on the 60-chunk sequence (5.9 GB) and on texts A and B as before. **Missed on the book-like text: 10,745 MiB, 4.9 % over** (13,590 MiB, 33 % over, before the change).
- *Growth < 10 % after warm-up:* **missed.** +10.6 % on the sequence (was +28.4 %), +31.4 % on the book-like text (was +59.5 %).
- Both remain a **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**, reduced but not closed. The 10 % target is unchanged, and nothing is marked PASS.
- *S:* PASS. There was no pressure event and no swap, every restart gave the memory back, and no run came near the 14 GiB safety cancel.

**The owner's options.**
- **(a)** Accept the remaining exception with the 16-chunk bound.
- **(b)** Authorize one more bounded Mac-only experiment aimed at the main measured component, the allocator's kept buffers: `torch.mps.empty_cache()` after each chunk, every N chunks, or only above a footprint threshold.
  - The evidence now shows about 88 % of the growth is GPU buffers, which `empty_cache` targets.
  - The MPSGraph heap part would remain; only a worker restart clears it.
  - The throughput cost is not measured.
- **(c)** Revert to 48. The 13.6 GB result, with memory pressure, then stands for book-like text.

**Status.** P4B memory checkpoint: one Mac-only change implemented and verified, and the exception reduced but not closed. P4B is NOT owner accepted. P4C has not started. Nothing was merged, tagged or released; draft release `447445728` is untouched.

## 2026-11-16 — macOS P4B OmniVoice production integration: implemented and verified on HOME-MacOS. P4B TECHNICAL PASS (F, S) with one PERFORMANCE EXCEPTION — OWNER DECISION PENDING (memory growth inside one worker); the P4B checkpoint awaits the owner; P4C not started

Signed: Claude Code (Opus 5.5), HOME-MacOS (Apple M4 Pro, 24 GB), under the owner's P4B authorization (entry below). Start SHA `ca778c9`.

**Owner approvals used (this session, each asked for separately).**
- **Adoption of the P4A bytes, token `39f30ad47add55ca3598148c78316ef3e1ad86f63408385f3aab0968b2aaa874`.** 97 files (86 Mac wheels + 11 model files), 3,514,204,377 bytes, placed in the production wheel cache and model folder with `clonefile(2)` (APFS copy-on-write: no extra disk). Each file was hashed against the production manifest before and after; the sources were only read. Tool: `files/dev-tools/macos_p4b_omnivoice_setup.py` (dev-only).
- **Installation through ACT's own installer** (`optional_setup.plan` → consent → `RealAcquirer`), approved at a download total of 0 bytes. Engine READY in 41.7 s. Receipt: stage `installed`, origin `installed`, `probe_ok`. Probe: `mps` float32, "Apple M4 Pro GPU (MPS)", load 1.04 s, 0 network attempts, footprint 2,970 MiB. `packages_sha256` `3d98081b…1853`, `model_manifest_sha256` `1fda8c17…3d2a`. The wheels were discarded after the proof, as the installer does. Engine: `.venv/engines/omnivoice`, 1.2 GB.

**Implementation decisions (within the authorization; Windows behaviour unchanged).**
1. **One device policy** (`omnivoice_runtime.device_policy`). Windows: CUDA float16, as released; the Mac setting is ignored there. Mac: `mps` float32 by default, `cpu` float32 when `config.toml` says `[tts] omnivoice_device = "cpu"`. The value is validated by `shared.config`; an invalid one keeps the default and gets a diagnostic. It is read once per file. Float16 and every other device are refused, never substituted.
2. **No silent fallback.** After loading, the worker checks that the model is on the requested device and dtype; if not, it fails. `PYTORCH_ENABLE_MPS_FALLBACK` and the MPS watermark switches are removed from the worker's environment, and a job carrying a fallback switch is refused.
3. **Prompt identity** gains `device` only off CUDA. Every Windows clone-prompt key stays byte-identical, so no cached Windows prompt is lost; the Mac's GPU and CPU prompts each get their own key. Measured: the CPU run built its own prompts, and the GPU track B reused the GPU's.
4. **Mac wheel set:** a `darwin_arm64` section in `omnivoice_manifest.json`. It holds 86 PyPI wheels (`files.pythonhosted.org` only), the same pins as P4A: plain torch and torchaudio 2.8.0, no colorama or tzdata. The Windows top-level set is unchanged.
5. **Containment.** The Mac worker is a class-A child of the app window's containment owner, tied to its lifeline; a command-line run gets a private owner instead. The Windows Job Object path is unchanged. Cancel is unchanged everywhere: the flag, a 2 s grace, then the whole group is killed (T_stop 4 s).
6. **Cross-copy model guard (D13) on a Mac:** a `flock` on `ACT-locks/omnivoice.lock` in the per-user temporary folder (`confstr(_CS_DARWIN_USER_TEMP_DIR)`, which a worker's `TMPDIR` cannot move). It is opened with `O_NOFOLLOW`; the kernel releases it when its holder dies. Windows is unchanged.
7. **The installer's base Python on a Mac** is `files/runtime-data/python/bin/python3.12` (`omnivoice_runtime.app_owned_python`). The first real install showed the installer refusing it ("inside this app's folder"), because the Windows-shaped rule only knew `python.exe`. Fixed; a regression test covers it.
8. **A config bug, found by the new test before any commit:** `omnivoice_device` was missing from `config.py`'s `[tts]` schema, so a CPU choice would have been ignored as an unknown key. Fixed. The test also follows `config.toml`'s own "remove the '# '" instruction and checks the result is a valid CPU choice.
9. **First-run wizard:** `bootstrap.optional_choices_for(platform)`. The Windows tuple is byte-identical (`WINDOWS_OPTIONAL_CHOICES`). On a Mac the same five choices remain, and only OmniVoice's line names Apple Silicon. Trimming the Mac wizard to Kokoro + OmniVoice is P4C.
10. **88 standard-library bytecode caches** were written into the app-owned Python by the installer's base-Python probe and venv creation: normal CPython behaviour, and the installer does the same on Windows. They were left in place, since they are production behaviour, not an experiment artefact (P4A removed its own).
11. **Feature map and coverage.** Feature map: macOS P4B bullets added to `ACT.TTS.ENGINE.OMNIVOICE`, `ACT.TTS.SETUP.OMNIVOICE` and `ACT.SHARED.CONFIG`; the Windows text is unchanged. `coverage.json`: the 8 changed sources were reviewed and restamped, their feature mappings unchanged.

**Verification (real engine, production paths; evidence `files/dev-work/macos-p4b/q/`, ignored).** Every conversion went through `omnivoice_file_to_mp3`: `v1` speech preparation, the chunk plan, bounded workers, assembly, one encode and atomic publication. Pinned OmniVoice 0.2.1, model `c5fdb5cc`, references and `GENERATION` unchanged.

| Check | Result |
|---|---|
| Six voices, text A, MPS fp32 | 6/6 PASS. Wall RTF 0.923–1.069 (inference 0.869–1.005); peak footprint 7,439–9,577 MiB; 4 chunks each; device `mps` "Apple M4 Pro GPU (MPS)" float32 |
| Multi-chunk, text B, MPS fp32 (Female 1, Male 1) | 2/2 PASS, 14 chunks each. 151.3 s and 200.8 s of audio; wall RTF 1.043 and 1.092; peak 7,454 and 9,437 MiB |
| Worker bound and memory, 60 one-sentence chunks, MPS (Female 2) | PASS: 60/60 chunks, 2 workers (48 + 12), 366.0 s of audio, wall RTF 1.312, peak 6,900 MiB. Memory after a 5-chunk warm-up, see the P verdict below |
| CPU fp32 by choice (Female 1, Male 4, text A) | 2/2 PASS. Device `cpu` "Apple M4 Pro CPU" float32; wall RTF 1.510 and 1.233; peak 3,331 and 2,265 MiB |
| CX-3, real Cancel mid-chunk (1 s into chunk 2) | MPS: 2.144 s. CPU: 2.103 s (bound 4 s). Worker group empty, nothing published, no job folder left |
| KX-1(c), owner SIGKILLed mid-inference (Force Quit's signal) | Worker group gone in 0.384 s (bound 3 s); nothing published; no process left. The killed owner's job folder (704 KB) stays until the next conversion's 24-hour stale cleanup, as on Windows |
| CX-2 (a worker ignoring SIGTERM and the flag) and CX-8 (Cancel after the commit point) | Unit tests on the Mac: PASS (CX-2 ends within the bound in about 2.1 s) |
| Installer in a disposable sandbox (`macos_p4b_omnivoice_install_qa.py`, real installer, no network) | T0: a tampered cached wheel is no longer counted as verified (it would be downloaded again). S0: Cancel during pip leaves it `incomplete`. S1: a repair cancelled during the proof leaves it `unchecked` with nothing recorded. S2: adoption proves and records it, with nothing downloaded or rebuilt. S3: damage is detected as `broken`; the repair moves the old environment aside, rebuilds offline, proves on `mps` and discards the wheels. All PASS, no process left. The sandbox was removed afterwards |
| Availability | All six voices `(True, "ok")` on this Mac; policy `mps` float32 (default) |
| Protected assets, before and after | 18/18 references, both transcript files, 28/28 previews unchanged |
| Focused tests (no full gate) | The 76 affected modules: 4,230 passed, 57 skipped, 229 failed. All 229 failures fail identically on clean HEAD `ca778c9` (a `git archive` tree; Windows-simulation suites: `winreg`, the `python.exe` layout); 0 new. New Mac tests cover the device policy, the config key, the base Python, the model guard, the MPS switch, placement, prompt identity, CX-2 and CX-8; every Windows pin goes through `ov._system`, and no new skip was added. `test_verification_coverage` passes after reviewing and restamping the 8 changed sources. `test_verification_gate_contract`'s 12 failures also fail on clean HEAD |

**P verdict against D6-O (provisional targets).**
- *Speed:* MPS within the C2 speed exception the owner accepted. CPU within its target.
- *Peak:* at most 9,577 MiB, within 10 GiB.
- *Growth: outside the target → PERFORMANCE EXCEPTION — OWNER DECISION PENDING.* Within one worker on 60 varied one-sentence chunks, the footprint grows 28.4 % after warm-up (5,363 → 6,884 MiB) and the MPS driver memory 14.5 % (3,611 → 4,135 MiB). The MPS-allocated tensors stay flat at 2,336 MiB, so the model is not leaking tensors. It is safe (S PASS): the existing 48-chunk worker bound returns it to 4,927 MiB, so no worker exceeds about 6.9 GB however long the book. P4A's +1.11 % came from 50 calls of one text; varied text is the stricter measure. The C2 speed exception does not waive memory.
- *The owner's options:* (a) accept it as bounded; or (b) authorize a Mac-only mitigation experiment, such as `torch.mps.empty_cache()` after each chunk or a smaller Mac worker bound. Neither was tried: both change worker behaviour beyond what P4B was authorized to change.

**Q observations (diagnostic only; the owner's P4A listening verdict stands and is not reopened).**
- Full-scale samples at the encoder's input: Male 3 text A 2, Male 1 text B 5. Production adds no loudness processing, as on Windows.
- The chunk speaking-rate screen flags 21.3–21.5 characters/s on text B, just outside the P4A screen's 8–20 band; Codex found that screen not reproducible.

**Not covered here.**
- No GUI smoke: the Mac's TTS surfaces are P4C's. It is an owner check.
- No Windows machine. The Windows branches were verified through platform seams on the Mac; the HOME-PC focused regression stays a P5 gate.
- The Windows-simulation OmniVoice installer tests still fail on a Mac exactly as on clean HEAD (`winreg`; 42 in `test_omnivoice_setup.py`), so the Mac installer paths were exercised for real in the sandbox instead. Their darwin seams are P4C or P5 work.
- No `verify.py` gate run: focused tests only, as the authorization said.

**Status.** P4B TECHNICAL PASS (F, S) with the one P exception above. Q accepted at P4A. The checkpoint waits for the owner's acceptance and the growth decision. P4C (20-voice roster, Chatterbox and Qwen3 gated on the Mac) is next only after that. Nothing merged, tagged or released; draft release `447445728` untouched.

## 2026-11-16 — P4A OWNER ACCEPTED: all six OmniVoice voices accepted by the owner's listening; MPS fp32 preferred, CPU fp32 a selectable alternative, MPS fp16 experimental only; C2's speed exception accepted for integration; P4B authorized; the final macOS roster is Edge + Kokoro + OmniVoice (20 voices); six OmniVoice previews added to the final release (owner decisions; recorded by Claude Code)

**Evidence the acceptance rests on (P4A evidence SHA `6fb98e63098981692b5b1508e7f4abafd68f96c4`; local evidence `files/dev-work/omnivoice-feasibility/`, ignored).**
- **Technical (agent-reported, P4A results entry below):** C1 CPU fp32 and C2 MPS fp32 each F PASS and S PASS; C3 MPS fp16 a bounded experiment only (S0, S1 and two samples).
- **Owner listening:** the owner listened to all 16 P4A MP3s. All six voices (Female 1, Female 2, Male 1, Male 2, Male 3, Male 4) sound good enough for integration. No meaningful audible difference was heard between the X/Y/Z configurations. No audio-tuning campaign is requested.
- **Independent Codex review (`P4A-Codex-Independent-Audio-Review.md`, 2026-11-16, read in full by this session).**
  - *Verdict:* PASS for bounded encoded-audio integrity and for CPU/MPS fp32 integration readiness. No configuration is objectively and consistently worse. MPS fp16 stays CONCERN / experimental.
  - *Scope:* all 16 MP3s decoded (mpg123) and measured: hashes against the indexes, format, duration, a local BS.1770-style loudness estimate, true-peak estimate, silence, spectra, pitch, discontinuities.
  - *Not covered:* no independent perceptual listening, no ASR, WER unmeasured, meters not conformance-validated, source PCM not available. It is not full-product verification.
  - *Nonblocking observations:* six files with less than 1 dB true-peak headroom (possible mastering improvement, not clipping); one unconfirmed CPU Female 2-Z onset transient at 0.234 s; the source-stage clipping counts and the chunk-level speaking-rate flags of the index are not reproducible from the MP3s and stay unverified. None is a proven defect.
- **WER: NOT RUN — NO AUTHORIZED ASR MODEL** (D15 stays deferred).

**Owner decisions.**
1. **P4A: OWNER ACCEPTED.** The listening verdict is final and is not reopened.
2. **MPS fp32 (C2): the preferred and default OmniVoice configuration** on supported Apple Silicon Macs. Technical PASS. **Its speed exception is accepted** for integration (wall RTF 0.914–1.190 against the provisional ≤ 1.0). This waives no memory, safety, Cancel, functional or long-form reliability requirement.
3. **CPU fp32 (C1): a supported, explicitly selectable alternative.** Technical PASS.
4. **MPS fp16 (C3): experimental only.** It is not offered as a production choice, and no full stability qualification is claimed.
5. **P4B is authorized:** production integration of OmniVoice on macOS through the real engine, installer and Cancel paths (plan §12.E, §19 P4B). The P4A acquisition consent covered only the disposable experiment. Any new production download, and any adoption of the P4A bytes into the production runtime, needs its own owner approval, kept apart from accepting the code.
6. **Final macOS roster (P4C, the configuration "Edge + Kokoro + OmniVoice" of §12.F): exactly 20 voices.** Edge TTS 5, Kokoro-82M 9, OmniVoice 6. Chatterbox Turbo and Qwen3 (CustomVoice and Voice Clone) are absent from every macOS user-facing surface and refused by macOS dispatch, through the one platform policy of §12.F; Windows keeps all 34 voices and every setup option unchanged. The macOS first-run optional TTS choices are the Kokoro model download and the OmniVoice installation; Edge needs none. P4C follows P4B's acceptance and is required before the Mac work is complete or any release.
7. **New final-release requirement (deferred to P6a): six OmniVoice previews** (`omnivoice-female-1.wav` … `omnivoice-male-4.wav`) join the public preview gallery, making 34. The 28 historical previews stay byte-for-byte; the same short sample text; the real production pipeline; lossless WAV; voice identities, hashes, durations and provenance recorded; the original references and transcripts never published; the model's non-commercial and tokenizer terms reviewed before publication. The owner intends to publish them, subject to that review. Not generated in P4B.

**Protected.** The temporary GitHub draft release `447445728` ("ACT P4A OmniVoice — TEMPORARY LISTENING EVIDENCE — DO NOT PUBLISH", asset `ACT-P4A-OmniVoice-listening-pack.zip`, digest `sha256:b72ab61d…`) delivered the pack. It is not published, changed or deleted without separate authorization. No listening sample, model file or experiment log enters source history.

**Unchanged.** P2 acceptance items, Windows E-B2, the Windows focused regression, D16 (version identity), D18 and both final gates on one SHA stay as recorded. P4A evidence is never relabelled as a P4B result.

## 2026-11-16 — macOS P4A OmniVoice feasibility executed: P4A TECHNICAL PASS — OWNER LISTENING PENDING (C1 CPU fp32 within every D6-O target; C2 MPS fp32 a narrow PERFORMANCE EXCEPTION on speed; C3 MPS fp16 bounded experiment clean); the listening pack is not on GitHub, so delivery waits for the owner (recorded by Claude Code)

**What ran (bounded, once; no tuning loop, no setting, revision or reference changed).**
- **Acquisition.** Only the consented manifest (token `7932d4ef…62f4c`): 97 files, 3,514,204,377 bytes, in about 60 s. Every file was accepted by size and SHA-256 and re-hashed afterwards (97/97). There were no other downloads: no Whisper, nothing of Chatterbox or Qwen3.
- **Environment.** `files/dev-work/omnivoice-feasibility/venv` was built from the app-owned CPython 3.12.15, offline (`--no-index --no-deps --require-hashes --only-binary :all: --isolated`). `pip check` is clean, and the installed set equals the manifest plus the venv's own pip. Nothing on `sys.path` reaches `.venv` or another site-packages, and the user site is off. torch 2.8.0 with MPS available, omnivoice 0.2.1, 1.22 GB.
- **Harness, dev-only:** `files/dev-tools/macos_p4a_omnivoice_worker.py` and `macos_p4a_omnivoice_run.py`.
  - It runs ACT's production text and audio path: `v1` speech preparation, `plan_chunks`, `derive_seed`, `GENERATION`, `build_job`, and for the pack the production `omnivoice_file_to_mp3` with its supervisor, chunk reader, assembly, final tail and one encode.
  - Only device and dtype differ from production.
  - In the harness process only, `omnivoice_runtime.model_dir`, `engine_lock_path` and `inference_lease` point at the experiment, and the worker environment is the experiment's own. That way nothing goes to `files/runtime-data`.
  - The worker reuses ACT's network audit hook, reference proof and speech-recognizer refusal from `tts/omnivoice_worker.py`.
  - It refuses a silent CPU fallback: the MPS fallback switch must be unset and the backbone must be on the requested device.
  - It writes chunks under a temporary name, and has a parent lifeline.
  - Production engine code is unchanged.
- **One harness defect, fixed and S0 rerun once.** The first placement guard counted the audio tokenizer, which is registered under the model, as part of the backbone. Upstream deliberately keeps it on the CPU under MPS. The guard now checks the backbone and the tokenizer separately.

**Results per configuration (evidence: `files/dev-work/omnivoice-feasibility/runs/s0`–`s4`, receipts, logs).**
- **S0, offline load and smoke:**
  - all three load and generate finite audio with zero network attempts and no unsupported-op error (fallback unset);
  - the backbone is on the requested device and dtype, and the tokenizer on the CPU, where upstream places it;
  - cold load C1 0.51 s, C2 0.96 s, C3 0.95 s; clone prompt about 0.4–0.5 s.
- **S1, correctness screen:**
  - neutral `say` reference, then Female 1: an eight-item ladder from 1 word to one 291-character sentence, on C1, C2 and C3;
  - 57 chunks, all finite: zero clipped samples, no internal silence over 2 s, and no envelope or noise-signature flag against C1;
  - same-device repeats are bit-identical on all three (9/9);
  - the only flag is one neutral-reference item at 20.4–21.1 characters per second (the fast synthetic `say` speaker).
- **S2, listening pack, production path:** 16/16 MP3s PASS and decode with zero errors (24 kHz mono, 160 kbit/s: MPEG-2 Layer III caps the route's 192k at 24 kHz). Integrity notes:
  - 1–5 full-scale samples in four files, on the CPU reference as well as MPS;
  - one short track-B chunk per file at about 21.3–21.5 characters per second.
- **S3, stability:**
  - **C2:** 50/50 calls finite and bit-identical (one distinct output). Footprint growth after warm-up +1.11 % (6.29 → 6.36 GiB); MPS driver memory flat (4.67 GiB, 0 %). RTF 1.105–1.206 (mean 1.163, +3 % drift over the run). No memory-pressure event, swap unchanged.
  - **C1:** 10/10, growth +0.08 %, RTF mean 1.601.
- **S4, termination during active generation:**
  - SIGTERM to the worker's group: gone in 0.030 s (C1) and 0.074 s (C2), with no SIGKILL needed, no group member left, only completed chunk files (no `.part`), and the MPS memory recovered (available 5.55 → 12.73 GB, against 12.07 GB before).
  - ACT's existing OmniVoice supervisor (Cancel flag, 2 s grace, group kill): `ConversionCancelled` in 2.24 s (C1) and 2.29 s (C2), within the macOS contract's OmniVoice T_stop ≤ 4 s.
  - This is experimental evidence, not proof of a P4B Cancel integration.

**Verdicts (F functional / S safety, stability and containment / Q owner audio quality / P D6-O practicality).**
- **C1 CPU fp32:** F PASS; S PASS; Q **PENDING (owner)**; P **within every target**:
  - wall RTF 1.31–1.66 (target ≤ 3.5);
  - peak footprint ≤ 4.05 GiB;
  - growth +0.08 %.
- **C2 MPS fp32:** F PASS; S PASS; Q **PENDING (owner)**; P **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**:
  - wall RTF 0.914–1.111 on track A (three of six over 1.0), 1.148 and 1.190 on track B, and 1.163 in the soak, against a target ≤ 1.0 (up to +19 %);
  - peak footprint 9.54 GiB, within the 10 GiB target but close;
  - growth +1.11 % (within).
- **C3 MPS fp16** (bounded experiment: S0, S1 and two pack samples only, with no soak or termination test): F PASS; S1 screen clean; Q **PENDING (owner)**; P wall RTF 0.903 and 0.998, peak 7.31 GiB.
- **WER: NOT RUN — NO AUTHORIZED ASR MODEL** (D15 deferred). Low WER is not inferred from the integrity screen.
- **Campaign state: `P4A TECHNICAL PASS — OWNER LISTENING PENDING`.** C1 is a technical PASS within every target, and C2 is reported separately as a performance exception. In practice, C2 runs at about real time (a 10-hour book in roughly 10–12 hours) and C1 at about 1.3–1.7× real time. A negative owner listening verdict still activates the Q1=A fallback, whatever these results.

**Pack.** `files/dev-work/omnivoice-feasibility/listening-pack/` holds 16 MP3s, all NOT YET REVIEWED:
- track A for the six voices as blind pairs, CPU against MPS fp32, plus MPS fp16 as a third file for Female 2 and Male 2;
- track B, multi-chunk, for Female 1 and Male 1 on MPS fp32.

`index.md` and `index.json` give comparison groups, durations, integrity flags and SHA-256s, with nothing that reveals the device. `key.json` names each file's configuration with its speed and memory. A ready bundle is in `delivery/ACT-P4A-OmniVoice-listening-pack.zip` (21.4 MB; SHA-256 `b72ab61d…a9`): no references, transcripts, logs or paths.

**Delivery decision (the owner's clarification of 2026-11-16).** The repository is public, and the audio must not enter the history of any branch.
- A GitHub Actions artifact can only be produced by a workflow run on a runner. The repository has no workflow, and `gh` can list, download and delete artifacts but not upload one. Getting the files onto a runner would need a commit or another host.
- There is therefore no practical GitHub artifact path within the owner's constraints (no new workflow, release, tag, repository, tool or external upload service without separate authorization).
- Delivery STOPS at this checkpoint, and the options go to the owner. Nothing was uploaded.

**Changes outside the experiment, found and undone.** While verifying the environment (`pip check` and the probes), the venv's Python, which shares the app-owned base interpreter, wrote 87 standard-library bytecode caches into `files/runtime-data/python/lib/python3.12/` (86 in `encodings/__pycache__`, 1 for `fileinput`). Python does this on any first import. ACT's integrity checks ignore `__pycache__`, so the files were harmless. Their list was recorded (`receipts/base-python-pyc-written.txt`) and exactly those 87 new files were removed: the runtime data is back to its 2,434 entries, and only directory timestamps differ.

Everything else is unchanged before and after:
- the 18 references, both transcript files and the 28 previews;
- the main `.venv` (59,229 entries, same digest) and the Hugging Face cache;
- the Downloads outputs (299 entries) and the owner's test files and audiobooks;
- the owner's git state: the 17 deletions and the untracked files.

No P4A process remains. Disk use: 4.6 GB in the area.

**Still the owner's:**
- listening to the pack (Q for C1, C2 and C3);
- disposition of C2's speed exception, and the choice of configuration;
- the pack delivery route;
- D15;
- afterwards, P4B authorization, or the fallback (P4C, Edge + Kokoro).

P4B and P4C have not started. P2 acceptance and Windows E-B2 stay pending. Nothing was merged, tagged or released.

## 2026-11-16 — P4A owner approvals: acquisition consent to manifest token `7932d4ef…`; D6-O set as provisional practicality targets, not automatic rejection thresholds; D15 (Whisper) deferred until after the listening verdict (owner decisions; recorded by Claude Code before execution)

**ACQUISITION = A.** The owner authorizes downloading **only** the files that `files/dev-tools/macos_p4a_omnivoice_manifest.json` lists at `bac67d4`, whose raw bytes hash to the consent token `7932d4ef5b3ed0e531b958b9729f1de77ce27de37c755de290d5d9b896f62f4c`:
- 86 wheels, 246,737,206 bytes, from PyPI;
- 11 model files of `k2-fsa/OmniVoice@c5fdb5ccb189668d56333f77ba2629f4cd7535f4`, 3,267,467,171 bytes, from Hugging Face.

That is 3,514,204,377 bytes in total, and everything (environment, receipts, logs, audio) goes into `files/dev-work/omnivoice-feasibility/` only. No other acquisition is authorized. A changed manifest needs a new authorization; the token is never reused for a regenerated one.

**D6-O BUDGET = A: the four proposed values become provisional practicality targets.**
- The targets: MPS RTF ≤ 1.0; CPU RTF ≤ 3.5; peak process footprint ≤ 10 GiB; growth after warm-up < 10 %. Each is evaluated and reported separately.
- *Why the earlier line changed:* the Revision 2 roadmap proposed "every technically passing configuration outside D6-O = the Q1 impractical line → fallback". The owner chose a more nuanced rule, in which audio quality and reliability outrank speed.
- Technical correctness, performance practicality and owner-perceived narration quality are **separate verdicts**.
- A technically correct configuration outside a target is **PERFORMANCE EXCEPTION — OWNER DECISION PENDING**, unless its resource behaviour is unsafe. A small miss never starts the fallback.
- Unsafe behaviour fails the safety and reliability gate, and may end that configuration's run at once. That covers a serious memory-pressure event, unsafe growth, running out of memory and instability. A memory-unsafe run is never continued to collect benchmarks.
- The owner keeps the final decision on speed, footprint and audio quality.
- The Q1=A fallback stays authorized when OmniVoice is technically impractical or unreliable, or when the owner rejects its narration. Q1, Q2 and Q3 are not reopened.
- The roadmap's §12.E (Revision 2a) now has four outcome states: TECHNICAL PASS — OWNER LISTENING PENDING; TECHNICAL PASS — PERFORMANCE EXCEPTION / OWNER DECISION PENDING; FALLBACK CONDITION MET — TECHNICAL OR SAFETY FAILURE; BLOCKED. The original proposal is kept there and in §20.3 as history.

**D15 WHISPER = A: deferred.** Whisper is not downloaded, installed or run at this checkpoint. The listening samples come first, then the owner's verdict. WER is reported as **NOT RUN — NO AUTHORIZED ASR MODEL**, and low WER is never inferred from intelligibility or the integrity screen.

**Boundary.** P4A is feasibility only: no P4B, no P4C, no Chatterbox or Qwen3 work or downloads, no shared Windows engine change, no merge, tag or release. P2 acceptance and Windows E-B2 stay pending.

## 2026-11-16 — Owner decisions Q1=A, Q2=A, Q3=A: Mac-first scope with an approved Edge/Kokoro fallback; one bounded OmniVoice feasibility campaign (P4A) before P3, prepared without acquisition; P3A/P3B skipped by owner decision on macOS; Windows verification deferred, not waived (owner decisions; preparation by Claude Code)

**Owner decisions (final for this development checkpoint; the owner's 2026-11-16 instruction, recorded, not invented).**
- **Q1=A:** OmniVoice receives one bounded technical feasibility campaign. If it proves impractical or unreliable, or the owner rejects its audio quality, its macOS integration is abandoned.
- **Q2=A:** when the fallback is activated, unsupported engines are removed completely from the macOS user-facing experience. Shared Windows code, existing assets, voice identities and base dependency pins are kept.
- **Q3=A:** finish and verify the macOS implementation while HOME-PC is unavailable. Mandatory native Windows verification and the final cross-platform release qualification are deferred until HOME-PC is available. They are not waived.
- **Engine priorities on macOS:** Kokoro-82M (nine voices), Edge TTS (five voices), the five non-TTS tools, then OmniVoice, only if technically feasible **and** audibly acceptable. Chatterbox Turbo and Qwen3 are no longer required on macOS. They are not implemented there if OmniVoice fails, and not started without new owner authorization if it succeeds.
- **Quality priorities:** stable long-form narration; calm, natural delivery; minimal emotion or tone fluctuation; accurate pronunciation and low WER; no hallucination, clipping, unexpected silence or voice drift; reliable Cancel and containment. Audio quality outranks speed.

**What this changes in the roadmap (`files/plans/ACT-v0.8.0-MacOS-Compatibility-and-Verification-Implementation-Plan.md`, Revision 2, amended in place; no competing plan).**
- **Status vocabulary** for delivery: IMPLEMENTED, TESTED, OWNER ACCEPTED, BLOCKED, SKIPPED BY OWNER DECISION, RELEASE READY.
- **O3 is replaced on macOS:** the Mac offers only the proven, owner-accepted engines, and every other engine is absent from its user-facing experience (no "visible but unavailable"). O4 (assets and identities), O5 and O6 (both gates on one SHA) are unchanged.
- **P3A and P3B: SKIPPED BY OWNER DECISION on macOS.** Not PASS and not a technical FAIL. Their text stays as the record. D12 is moot on macOS.
- **P4A is moved before P3** and rewritten as one bounded campaign (§12.E Revision 2), with exactly one outcome: `P4A TECHNICAL PASS — OWNER LISTENING PENDING`, `FALLBACK CONDITION MET` or `P4A BLOCKED`. No tuning loop.
- **D7-O** is answered in advance by Q1=A, so a failure or an owner rejection goes straight to the fallback.
- **P4B** needs a proven configuration, the owner's acceptance of its audio and its own authorization. Any macOS OmniVoice install control needs separately verified macOS setup behaviour.
- **New P4C** (both outcomes): one central, platform-aware capability policy decides the macOS roster at startup from the real platform, with no user toggle. It governs every surface, the runtime dispatch and stale or imported settings (§12.F). Windows keeps the full roster. It never starts before the P4A outcome: no Mac engine control is removed early.
- **P5** keeps the macOS acceptance: Edge/Kokoro, the five tools, setup, Cancel, Pause, containment, publication and the native UI. The HOME-PC items (E-B2, the Windows focused regression) are PENDING until HOME-PC returns, and due before P6. The Mac can reach `MAC IMPLEMENTATION COMPLETE — RELEASE QUALIFICATION PENDING`, never released.
- **P2 stays IMPLEMENTED and TESTED (automated), not OWNER ACCEPTED.** Still tracked:
  - listening to the 24-sample pack;
  - the Andrew disposition;
  - the D6-K peak (6.0046 GiB) and growth (10.98 %) readings;
  - the 19 journey pictures;
  - D15;
  - the spaCy model in `.venv`;
  - Windows E-B2 (PENDING, deferred under Q3=A).

**P4A preparation, done without any package or model acquisition (at `d6f21f9`).**
- **Read-only metadata fetched:** upstream's `uv.lock`, `pyproject.toml` and four source files at `5ba967c4` (text), the PyPI JSON and Hugging Face tree metadata, and upstream and PyTorch issue threads. Stored in the ignored `files/dev-work/omnivoice-feasibility/upstream/`.
- **Not downloaded:** no wheel, no model file, no Whisper, nothing of Chatterbox or Qwen3.
- **The lock is the recorded one:** `uv.lock` hashes to ACT's `56f22586…`.
- **The darwin acquisition set:** `files/dev-tools/macos_p4a_omnivoice_manifest.json`, SHA-256 `7932d4ef5b3ed0e531b958b9729f1de77ce27de37c755de290d5d9b896f62f4c`, which is the consent token.
  - **Wheels:** 86, 246,737,206 bytes, all from PyPI. They differ from Windows only in two ways: no `colorama`/`tzdata`, and plain torch/torchaudio 2.8.0. PyPI confirms all 86 by filename, SHA-256 and size, none yanked.
  - **Model:** ACT's `k2-fsa/OmniVoice@c5fdb5cc`, unchanged: 11 files, 3,267,467,171 bytes. Hugging Face confirms all 11.
  - **Transfer:** 3,514,204,377 bytes; about 5.2 GB of disk with the environment and outputs (estimated). Nothing on this Mac is reusable.
- **The tool:** `files/dev-tools/macos_p4a_omnivoice.py` (dev-only).
  - `derive` re-derives the manifest byte-for-byte.
  - `check-upstream` does the metadata cross-check.
  - `op-probe` runs the indicative MPS checks.
  - `plan` needs no network.
  - `fetch` refuses without the exact token (shown).
  - The engine-run stages S0–S4 are written at the start of the authorized run, so they are exercised against the real model, not committed untested.
- **Findings that shaped the procedure:**
  1. Upstream itself keeps the audio tokenizer on the CPU under MPS, so Revision 1's optional "tokenizer on MPS" step is dropped (#279 is an unmerged proposal).
  2. Upstream's Gumbel-noise sampling gives CPU and MPS different random streams. Token agreement with the CPU is therefore only informational, and same-device repeatability is measured.
  3. The macOS 27 MPSGraph `argmax` corruption (pytorch#187280) was fixed in torch 2.13 and in the OS. OmniVoice pins torch 2.8.0, so the CPU fp32 reference stays mandatory.
  4. Indicative: with the app's torch 2.6.0 on macOS 27.0.1, MPS gave the CPU's answer in all 28 cases at OmniVoice's shapes. MPS is available in this agent session, so MPS runs are not BLOCKED by the sandbox here.
  5. ACT's seven OmniVoice suites on macOS: 540 passed, 79 failed, 5 skipped. All 79 failures predate this work and are Windows-installer simulations (`winreg`, `msvcrt`, `_winapi`, the Windows certificate store, Windows text). Under the fallback they become darwin skip rules or platform seams in P4C.
  6. The 12 Windows-approved OmniVoice tracks are not on this Mac (only their index).
  7. **The macOS surfaces today** (read-only inventory; plan §12.F):
     - No central platform policy exists. Qwen3 and OmniVoice show as "visible but unavailable" with a "need Windows" sentence, in the status line, the Voice-unavailable dialog, the wizard descriptions and the review panel.
     - **Chatterbox has no platform gate at all.** The wizard and Install & Continue offer it on a Mac, and `select_device()` would run it on MPS inside the app's own process, outside the Cancel worker.
     - Nothing persists a voice, so no stored setting can name one today.

     All of this changes only in P4C, after the P4A outcome (the owner: no early removal of Mac engine controls).
- **Protected assets:** 18/18 references, both transcript files and 28/28 previews verified. All six OmniVoice references pass ACT's `verify_reference`.

**Still the owner's (nothing is acquired before them).**
- Consent to the P4A acquisition (token above).
- D6-O and its practicality line.
- D15 (WER).
- The open P2 items above.

P3A, P3B, P4B and P4C have not started. Nothing was merged, tagged or released.

## 2026-11-16 — macOS P2 (Edge TTS and Kokoro-82M): implementation complete at `38af4fd`; specific acceptance evidence pending the owner (owner budgets and authorization recorded; findings for owner disposition; recorded by Claude Code)

**Owner decisions this phase ran under (the owner's 2026-11-16 instruction, recorded here, not invented).**
- **D6-E (Edge):** no speed budget. Every file of the 2-file and 8-file runs must complete within the existing retry policy; failures, 403s, `NoAudioReceived`, retries and throughput are recorded; an upstream outage is BLOCKED, not FAIL.
- **D6-K (Kokoro):** RTF ≤ 0.25; peak worker footprint ≤ 6 GiB; memory growth after warm-up < 10 %; cold and warm load measured. Out-of-budget results are reported for the owner's disposition; no tuning.
- **Owner priorities:** calm narration, low WER, consistent pronunciation and minimal emotional fluctuation over speed.
- **P2-only download and network authorization:** bounded qualification of ACT's pinned Kokoro-82M model and its nine voices through ACT's own asset identities, hashes, locations and consent; real Edge calls for E-A1–E-A4. Not authorized and not done: Chatterbox weights, Qwen3 models or engine, OmniVoice models or engine, other TTS models, Whisper (D15).

**What was acquired, reused and changed on this Mac (all ACT's pinned identities; nothing in the owner's settings).**
- **Kokoro (disposable worktree `files/dev-work/worktrees/p2` only):** `kokoro-v1_0.pth`, `config.json` and `af_heart.pt` reused byte-for-byte from the existing Hugging Face snapshot of `hexgrad/Kokoro-82M@f3ff3571791e39611d31c381e3a41a3af07b4987` after size and SHA-256 checks; the eight other voices (≈ 523 KB each, 4.19 MB) fetched by `optional_setup_acquire.RealAcquirer` under a consent derived from ACT's own plan. The owner's checkout keeps the optional voices the owner left unchecked.
- **spaCy English `en_core_web_sm` 3.8.0 (ACT's pin, 12,806,118 bytes):** fetched from its pinned release URL (size and SHA-256), installed offline (`--no-index --no-deps --require-hashes`) into **the main checkout's `.venv`** (07:07), the interpreter every worktree runs on; the wheel is kept in the worktree. This is the one change to the owner's environment; it is ACT's own pinned version. The owner may keep it or remove it.
- **English sentence data (NLTK punkt_tab):** the four pinned files were copied from the main checkout's verified copy into the worktree after size and SHA-256 checks; nothing downloaded.
- **Not changed:** the 34 voice identities, the shared speech preparation, the 18 clone references and both transcript files, the 28 previews (all verified before and after), Kokoro's default-voice behaviour, Windows audio generation, Python/FFmpeg/dependency pins, the owner's Downloads output folder (fingerprint unchanged in every run: 299 entries).

**Implementation decisions.**
- **macOS Kokoro inference runs in one preemptible local-engine worker** (`tts/local_engine_host.py`, `tts/local_engine_worker.py`): a child of the app's containment owner (P1A/P1B class A, lifeline, own process group), protocol on a private channel, float32 PCM handed back through a file and validated (24 kHz, mono, finite, length) before use. The parent keeps speech preparation, chunking, assembly, the one encode, publication and reporting. CPU fp32; no MPS; no speech-setting change; no pronunciation rule. Windows keeps Kokoro in process, unchanged (`isolation_enabled()` is darwin only). No Chatterbox adapter (P3A).
- **Cancel** ends the worker's whole group from the request's own poll (no waiting for the chunk) and, when the run is paused or between files, from Cancel itself; the next run starts a fresh worker. Choosing another engine's voice releases an idle worker; app exit ends it with the other owned children.
- **macOS wording:** the Edge sentence-data question and message name the folder with the system's separator (`files/runtime-data/nltk_data` on macOS; Windows word for word unchanged).

**Findings for the owner (evidence in `files/dev-work/macos-p2/`, ignored).**
1. **Andrew, track A: BLOCKED (upstream).** The Edge service sends no audio for some short clauses with `en-US-AndrewNeural` (`gone out entirely.` 0/2, `versus gone out entirely.` 0/2, `vs. the storm.` 1/2 called directly with edge-tts 7.3.1, outside ACT), while Steffan and Ava get audio for each; through the panel the A paragraph's clause `vs. gone out entirely.` is closed (1006) without audio on every attempt. Andrew narrates a plain sentence through the panel. Not macOS-specific: Windows sends the same clause.
2. **D6-K peak footprint: one sample over budget.** `am_michael` track C (two chunks near 3,000 characters) peaked at 6.0046 GiB (6,447,404,864 bytes; budget 6 GiB). Every other sample was within budget (A 2.60–3.19 GiB, C 4.52–5.70 GiB, B 5.02 GiB, the 34-minute chapter 5.63 GiB). Peak follows chunk length.
3. **D6-K growth after warm-up: 10.98 % by the harness's definition** (the largest post-warm-up footprint against the first one), all of it from the chapter's last chunk; the fitted trend over the 12 post-warm-up chunks is −2.7 % (no leak). The owner decides which reading the budget means.
4. **Pre-existing test isolation defects (not P2; baseline `b363344` shows them too):** a test among the affected suites creates empty `files/runtime-data/qwen3/{cache,tmp}` in the checkout under test (culprit not identified); `test_kokoro_health::test_the_real_proof_passes_on_the_qualified_environment` writes the eSpeak short-root link into the real runtime data on macOS (the guard reports it; the link was removed).
5. **eSpeak short-root boundary:** the short root fits while the runtime-data folder is ≤ 134 characters, else the temp-folder root is used (≈ 49 characters on a Mac); only when both are too long does eSpeak fail (the library ends the worker, which is reported). Recorded for P6a/P7.
6. **Windows-separator wording outside P2:** the bootstrap's Kokoro failure notice (`files\runtime-data\logs`) and OmniVoice notes still use backslashes on every platform — for P5/P6a (bootstrap) and P4 (OmniVoice).
7. **`coverage.json`'s `macos` census block** still reads `pending P2` for the TTS features; it is re-derived by the census tool, not asserted (later census).

**Evidence at `38af4fd` (agent-reported, AUTOMATED unless named otherwise; detail in Handoff).** Affected suites `2026-11-16_084951_focused_d5c1`: the failure set is exactly the unchanged baseline's at `b363344` (53 + 1 error, `2026-11-16_074230_focused_22d5`), no new failure, every skip named by the policy, inventory reviewed. Ten darwin TTS journeys and the opt-in real-Kokoro suite `2026-11-16_085817_focused_24f3`: PASS (10 journeys, 48 tests). The Cancel and crash cases, Edge E-A1–E-A4 and Kokoro E-B1–E-B3 qualifications are recorded in Handoff with their figures.

**What remains the owner's (P2 is not accepted by this entry).** Listening approval of the pack (`files/test-for-manual-listen-elmatthe/ACT-v0.8.0-macos-p2/`, 24 samples, all NOT YET REVIEWED); disposition of findings 1–3; D15 (Whisper) for WER, which is NOT RUN; the HOME-PC E-B2 run for Windows phoneme parity (PENDING); the 19 journey pictures listed for visual review (none approved).

## 2026-11-16 — macOS P1B accepted by the owner at `61078f9`; visual debt, ACT72-080 and three deferrals carried to named later phases (owner decision; recorded by Claude Code)

**Owner decision (the owner's P1B acceptance and P2 instruction of 2026-11-16, recorded here, not invented).**
- **A. P1B is accepted at the verified checkpoint `61078f9`** (documents only on the code candidate `b363344`; application code identical to `2ab868d`).
- **B. The 20 visual FAIL findings of the `847e` eye review are NONBLOCKING P1B visual debt, not visual PASS results.** Their original pictures (`files/dev-work/worktrees/p1b-closeout/files/dev-work/verification-gate/outputs/2026-11-15_221914_qualification_847e/`) and their individual FAIL findings (`files/dev-work/macos-p1b/act72-081/eye/eye-review-847e.{md,json}`) are retained unchanged: OBS-ENTRY-PATH (9), OBS-LOG-WRAP (8), OBS-LIST-ELLIPSIS (6), OBS-TTS-FOCUS (2), OBS-FOCUS-BORDER (1), OBS-ALERT-MATERIAL (1). They are reviewed for usability and disposition in **P5**, before release, and are never silently cleared.
- **C. The 1120 × 800 Aqua minimum is kept.**
- **D. D11c (macOS FFmpeg continuous-route qualification) is deferred.** The verified per-chapter fallback stays; the 17 continuous-route proofs stay accurately dispositioned, never passed.
- **E. D11b (cross-process abandoned work-area cleanup) is deferred.** ACT72-076 and the current safe non-deletion behaviour are retained.
- **F. MAC-042 (Dock and menu-bar branding) is deferred to P6a packaging.** The development interpreter's "python" identity is accepted provisionally, not as the release's branding.
- **G. ACT72-080 stays the APPROVED P1B EXCEPTION.** Selection inside the real native file picker stays UNVERIFIED and never counts as a PASS; it is revisited at P5/P7; no Accessibility or Screen Recording change is authorized.
- **H. The remaining nonblocking visual debt** (cut log and path displays, imperfect focus indicators, the Light Mode native-alert appearance) **stays documented for P5.** Any item found to prevent access to essential information or functionality is escalated, not treated as cosmetic.
- These decisions permit P1B closure. They waive no P2, P5, P6 or P7 release requirement.

**What the acceptance rests on (each kept in its own evidence class).**
- **Automated checks — agent-reported evidence at the P1B code candidate `b363344`** (Handoff, P1B ACT72-081 block): focused `221213_focused_c1d7` PASS (566 passed, 16 policy skips); 38 darwin journeys `221546_focused_f1d8` PASS; `macos-native-dialogs` `221850_qualification_fd48` PASS; `macos-visual` `221914_qualification_847e` PASS (machine review); `macos-kx10` `222115_qualification_719a` PASS; the coverage route `222347_focused_04da` at its census baseline. `verify.py --evidence`: every automated P1B requirement AUTOMATED PASS at the candidate. Not rerun for this record (the owner's instruction).
- **Visual review — 50 PASS and 20 known visual FAIL findings** (Claude Code's eye review of all 70 `847e` pictures; never the owner's own look). The owner accepts the 20 FAILs as debt (B), not as passes.
- **ACT72-080 — approved exception, selection UNVERIFIED** (G).
- **Later-phase TTS and real-clean-Mac checks — NOT RUN** (`tts-journeys` P2, `terminal-autoclose` P5, `dock-menu-name` P6, `fresh-macos` P7c).
- **Canonical macOS and Windows full gates — NOT RUN** (P7a/P7b on one final SHA; mandatory).
- **The P1B ledger is left as it reads.** No new owner visual record was created: the owner reported no new look of their own, so `owner-visual-dark` keeps reading NEEDS RE-REVIEW against the 2026-11-15 Dark record (`455bf83`) and the ledger's outcome stays `AWAITING THE OWNER'S VISUAL RE-REVIEW`. P1B is closed by this owner decision, with the visual state carried as debt (B, H); the ledger is not edited to read otherwise.

Signed: the owner (A–H, by instruction of 2026-11-16); Claude Code (the record).

## 2026-11-15 — macOS P1B ACT72-081: the footer follows the app's appearance (owner-approved amendment to the frozen shell); the picture review finds a native button in a box (owner decision recorded by Claude Code; implementation decisions by Claude Code)

**Owner decision (the owner's instruction of 2026-11-15, recorded here, not invented).**
- **ACT72-081 — a narrowly scoped, macOS-only amendment to the frozen shell appearance is approved.** The macOS footer's background follows the application's current appearance, so its native Aqua buttons sit on one coherent footer in Light and Dark. Native `ttk.Button`s, their positions, labels, actions and keyboard access, the Dark appearance, and the Windows and Linux shells are preserved; the main window, sidebar, toolbar and content panels are not redesigned; native buttons are not replaced by custom drawing. Had the background approach not produced an acceptable native appearance, the work was to stop and report.
- Unchanged: ACT72-080 stays an APPROVED P1B EXCEPTION (native-picker selection UNVERIFIED; no Accessibility or Screen Recording for P1B; revisit P5/P7). The 1120 × 800 minimum, D11c, D11b and MAC-042 keep their existing safe behaviour (planning recommendations, not newly approved decisions). The final real-clean-Mac qualification and the full Windows and macOS gates stay mandatory.

**Implementation decisions (Claude Code).**
- **Root cause (measured).** The darwin footer was a `tk.Frame` in the window colour `ui_theme` resolved from the system at start; the app's appearance is set per window (`appearance.apply_native_appearance`), and Tk Aqua fills each native `ttk.Button`'s rectangle with the window colour of the window's *current* appearance, which no ttk style reaches. On this Mac (system Dark, app Light): rectangles 236 on a footer of 50 (gap 186); the mirrored case (system Light, app Dark) puts dark rectangles on a light footer. A frame using the semantic `systemWindowBackgroundColor`, or a frame recoloured with `winfo_rgb` values read after the switch, matched the fill exactly (gap 0) through four switches; `winfo_rgb` resolves the window's current appearance, and Tk sends `<<LightAqua>>`/`<<DarkAqua>>` to the root when the app's appearance takes effect at map and after every switch (measured).
- **The footer is recoloured in place, nothing rebuilt** (`launcher._aqua_footer_colors`, `LauncherApp._paint_footer`): the two footer surfaces, the status label and the log link take the colours the window resolves now — `systemWindowBackgroundColor`; the status text the shell's own secondary formula (`ui_theme._readable_secondary`, the formula the sidebar heading uses); the link `systemLinkColor` moved toward the label colour only as far as WCAG AA requires. Painted at build, from the existing appearance listener on every switch (Preferences' reset path included), and on Tk's `<<LightAqua>>`/`<<DarkAqua>>` (bound once at build). In a Dark window the colours are exactly the shell's Dark palette, so Dark is unchanged. The footer separator keeps its colour (it reads as the dark chrome's lower edge; recolouring it was not needed for coherence). `ui_theme`, `appearance` and the Windows and classic builders are unchanged; on those shells the paint is a no-op.
- **Contrast (resolved system colours, this Mac):** Light footer `#ececec` — status `#6a6a6a` 4.58:1; the system link `#0068da` measured 4.45:1 (the earlier probe's finding, reproduced) and is drawn `#0067d8`, 4.52:1 (1 % toward the label colour). Dark footer `#323232` — status `#a3a3a3` 5.08:1, link `#419cff` 4.53:1, unchanged.
- **The machine review now sees the defect.** `layout_audit` names, for each native button on a classic surface, the surface's colour and a point of the button's rectangle (just inside its corner, outside the bezel); `visual_review` fails a picture where they differ by more than the probe tolerance. It passed the 27 boxed pictures before (a synthetic boxed picture: PASS under the previous review, FAIL now). `macos-visual` gains a toggle case per appearance (switched, switched back, four more, after Preferences opened and closed — no restart): 70 pictures, 10 runs.
- **Tests read real pictures.** `test_macos_p1b_visual_remediation.py` images the launcher window as the gate does and compares each footer button's rectangle with the footer beside it; a take out of register with the window, or of the wrong size (the window imaged mid-animation while the desktop was in use, seen), is kept, retaken within a bounded budget and never read. 8 of the new tests fail on the previous launcher, each on ACT72-081 itself.
- **Coverage:** the new binding is mapped to `ACT.SHARED.APPEARANCE`, whose contracts gain the footer; `launcher.py` restamped after review. The feature's verification list is unchanged (it applies to the Windows gate; the footer tests are Aqua-only).
- **Eye review (Claude Code; never the owner's):** all 70 `macos-visual` pictures at the candidate — ACT72-081 fixed in all 64 window pictures; 50 PASS, 20 FAIL, every FAIL pre-existing (identical at `a0bf460`, passed by the earlier review) and outside the approved scope: OBS-ENTRY-PATH, OBS-LOG-WRAP, OBS-LIST-ELLIPSIS, OBS-TTS-FOCUS, OBS-FOCUS-BORDER, OBS-ALERT-MATERIAL (Handoff). Recorded for the owner, not changed. `files/dev-work/macos-p1b/act72-081/eye/eye-review-847e.{md,json}` (ignored).
- **Incremental verification:** the ledger read NEEDS RERUN for every P1B suite, journey and scenario (`launcher.py` is in each closure); all were rerun at the candidate. No `--mode changed`, `--mode full`, unfiltered pytest, long conversion or TTS work.

**Why.** The owner approved one coherent footer in both appearances without a redesign; resolving the colours from the window itself makes the footer match the native fill by construction, whatever the system and app appearances are, and the review change keeps the class of defect from passing a machine review again.

Signed: the owner (the ACT72-081 amendment, by instruction of 2026-11-15); Claude Code (implementation decisions).

## 2026-11-15 — macOS P1B final visual remediation (ACT72-078, ACT72-079, sidebar contrast) and the owner's approved native-picker exception (ACT72-080) (owner decision recorded by Claude Code; implementation decisions by Claude Code)

**Owner decision (the owner's instruction of 2026-11-15, recorded here, not invented).**
- **ACT72-080 — APPROVED P1B EXCEPTION.** P1B may close without granting Accessibility or Screen Recording solely to automate a selection made with a real keyboard or pointer inside the native macOS file picker (NSOpenPanel's out-of-process browser). The selection itself stays **UNVERIFIED**, never PASS. The automated evidence for opening, configuring and cancelling the real panels (`macos-native-dialogs`) and the in-process evidence for returned paths, NFC/NFD names and downstream processing (`p1b-suites`, the journeys) stay valid within their tested scope and are not proof of a real selection. No owner signature, screenshot or selection result was created. The exception relaxes no other requirement and is revisited at P5/P7 release qualification; it is not blanket release approval. Recorded as `verification.json` → `darwin_p1b` requirement `native-panel-selection`, kind `approved-exception` (issue, decision, scope, revisit), shown by `verify.py --evidence` as `APPROVED P1B EXCEPTION - ACT72-080 UNVERIFIED …`, distinct from PASS, FAIL, BLOCKED and NOT RUN.
- **Still planning recommendations, not newly approved owner decisions:** keep 1120 × 800 for P1B; defer D11c (continuous-route qualification); defer D11b (cross-process staging cleanup, ACT72-076); defer MAC-042 (Dock and menu name) to packaging. The existing safe behaviour continues.

**Implementation decisions (Claude Code).**
- **ACT72-079 — the time remaining follows the run's state, in one place.** `job_ui.eta_is_estimated(state)`: an estimate (or `Calculating…` while the estimator has fewer than three comparable samples) is shown only for RUNNING and PAUSE_REQUESTED (§6.10: the stage runs on to its checkpoint). Before a run has reported anything (every panel's idle adapter, and a run's adapter before its first event), PAUSED, CANCEL_REQUESTED, CANCELLED, SUCCEEDED, COMPLETED_WITH_FAILURES and FAILED show no time-remaining text; the status line already names the state. The estimator (§6.13), the job lifecycle, Cancel, Pause and publication are unchanged. The mapping is shared, so Windows shows the same corrected text (the same defect existed there); the coverage contract of `ACT.SHARED.PROGRESS` and the feature map said "Calculating… while paused or after the run ends" and were corrected.
- **ACT72-078 — Aqua remedies through the theme's panel hints** (the Windows bundle carries none, pinned by `test_ui_theme`), at the provisional 1120 × 800 minimum, which is unchanged:
  - the darwin toolbar's tool description wraps to the width it is given (two lines fit the 44 pt toolbar);
  - TTS: the Voice list asks for 30 characters on Aqua (44 elsewhere) and, in the small-window "split" arrangement only, File workers folds under MP3 bitrate; together they let "split" fit 1120 × 800 (it needed 919 pt of 847), so Activity sits beside the workflow and the Sources list fills its column, instead of "stacked", where Sources showed two rows and Activity lay below the window. The rate controls moved from grid row 2 to row 3 on every platform (an empty grid row takes no space; nothing moves);
  - the Book navigator's heading (MP3 Tool, Maker, Metadata Editor) asks for no width and fits the slack column: the Book label yields behind an ellipsis, `(X of Y)` is never cut; the whole heading stays in `position_variable` and the selector lists every row whole (`BookNavigator(fit_heading=True)`, default off);
  - Metadata Editor: the Chapter Titles box asks for six rows and keeps three in either density (it showed one); the Source line fits its width — the folder, then the file name, yield in the middle, the status (readable, or why the tags could not be read) stays whole — and the whole line shows on hover (`ui_theme.HoverText`); `var_source` keeps the full text.
- **Found by the eye review of the 48 pictures, fixed the same way:** the content card's 1 pt outline was drawn in its focus colour (white on Dark, black on Light) whenever a field had focus — the card now has one colour and takes no focus (darwin shell only); the output-folder hint's last glyph was cut because the fit counted the label's own padding (2 pt a side on Aqua, measured) as room — `ui_theme.text_room` subtracts it (the compact hint is used on Windows too: there the shortened hint may drop one more character where the last would have been cut); the Maker's tight status line beside its controls is one line ending in an ellipsis on Aqua (`JobStatusView.fit_status`; the whole line stays in the status variable and is the Summary's last line); Cover's Details view scrolls sideways on Aqua (two of its five columns showed at 1120 × 800).
- **Sidebar contrast:** Aqua's sidebar "TOOLS" heading uses `colors["sidebar_label"]`, the secondary grey moved toward the label colour only as far as WCAG AA (4.5:1) on the sidebar tint requires, computed from the resolved system colours in Light and Dark: 4.31 → 4.51 in the gate's pictures (`#a3a3a3` → `#a7a7a7` on `#3d3d3d`, Light and Dark), 4.14 → 4.59 in process with the system's light colours resolved. Windows colours are unchanged.
- **Eye review (Claude Code; never the owner's):** the remaining 48 pictures of the closeout's run (first reading 21 PASS / 27 FAIL on the four defects above; amended to 13 PASS / 35 FAIL when ACT72-081 was found, which the first reading — and the closeout's first 12 — had missed) and all 60 fresh pictures at the candidate (33 PASS / 27 FAIL: every fix holds wherever it applies; the 27 FAILs are ACT72-081, the 27 Light-look window pictures). Per picture, with path, SHA-256, tool and state: `files/dev-work/macos-p1b/remediation/eye-review-*.{md,json}` (ignored).
- **New open issue ACT72-081 (pre-existing; Light look only; not changed):** in the app's Light look the footer's Dark mode and Preferences & Data… buttons each sit in a square light-grey box on the dark footer. The darwin shell's footer is a `tk.Frame` in the window colour resolved at start, while Tk Aqua fills a native `ttk.Button`'s rectangle with the window's current appearance; a ttk style background does not reach that fill (measured). The remedies change the frozen shell (a non-ttk footer button, or a footer that follows the toggle), so they are left to the owner's decision at final acceptance.
- **Closed by this remediation (subject to the owner's visual re-review):** ACT72-078, ACT72-079 and the sidebar contrast advisory.
- **Recorded, not changed:** the Shared group's 2 pt top border thins under its first-row labels (cosmetic); the import status reads "Added 1 files."; the TTS "wide" arrangement at larger sizes keeps its compact list beside Activity (3 rows at 1440 × 900 and at this Mac's largest visible size).
- **Test isolation (found by the first focused run, at `fb58185`; pre-existing at `2d02485`):** `test_launcher_smoke`'s HF_HOME test ran `launcher.main()`, which installed the process-wide containment owner and left it installed; a later Cmd+Q test closed it, and every spawn after that in the same pytest process was refused (`ContainmentUnavailable`: 21 tests in the publication-cancel, remux-cancel and MP3 appearance suites). The test now stubs `enable_containment` and asserts no owner remains (`a0bf460`). No application change.
- **Incremental verification:** what the change reaches was rerun at the candidate (the ledger read NEEDS RERUN for every P1B suite, journey and scenario, because `job_ui`, `ui_theme`, `launcher` and the tool modules are in their closures); nothing else. No `--mode changed`, `--mode full`, unfiltered pytest, long-form TTS or extra conversion.
- **Evidence ledger:** the outcome is one pure function (`verify.evidence_outcome`): a failure, then anything blocked, then anything not current, then the owner's visual record re-opened by an application change (`AWAITING THE OWNER'S VISUAL RE-REVIEW`; it used to read COMPLETE — fixed with a regression test), each outrank a completion; an approved exception is named in the outcome and never stands in for another requirement.

**Why.** The owner asked for the documented clipping and the misleading "Calculating…" to be fixed without enlarging the minimum or changing job behaviour, for every picture to be looked at, and for the native-picker gap to stay visible as an approved, unverified exception rather than a pass.

Signed: the owner (the ACT72-080 exception, by instruction of 2026-11-15); Claude Code (implementation decisions).

## 2026-11-15 — macOS P1B closeout: the owner's revised acceptance (automated functional evidence, owner-reported visual acceptance, incremental verification); implementation decisions for real pictures, real native dialogs, KX-10 and the evidence ledger (owner decisions recorded by Claude Code; implementation decisions by Claude Code)

**Owner decisions (the owner's instructions of 2026-11-15, recorded here, not invented).**
- **P1B acceptance revised.** The owner's manual part is limited to subjective visual design and usability review and to unavoidable operating-system permissions. Functional testing of the five non-TTS tools, their dialogs, cancellation, metadata, conversions and process containment belongs to the gate. The former checklist (`files/dev-work/macos-acceptance/P1B-owner-checklist.md`, ignored) is kept unchanged as history; its disposition is `P1B-checklist-disposition.md` beside it and `verification.json` → `darwin_p1b.checklist_map`. No owner JSON signature is required for, or may stand in for, an automated check.
- **Owner visual acceptance, OWNER-REPORTED (not agent-observed).** All six panels (TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker, Cover/Image, M4B Metadata Editor) visually accepted in Dark Mode; no significant clipping, overlapping controls or layout problems; every optional TTS voice-engine choice was unchecked in the first-run setup. Recorded in `files/dev-work/macos-acceptance/evidence/455bf833…/owner-visual-acceptance.json` (ignored) and bound to `455bf83` (application code identical to `2d02485`) by the agent-verified launch and session logs (15:36:03 launch from this checkout; the six panels loaded 15:36:04–15:37:26). One screenshot is bound (Desktop `Screenshot 2026-11-15 at 3.36.21 PM.png`, SHA-256 `a0f484f1…dc6f`, TTS panel, Dark); the owner's other screenshots were not found on this Mac and are not bound to any SHA. No individual checklist item is recorded as performed.
- **Incremental verification during implementation and remediation.** A failure is diagnosed (test, root cause, affected behaviour), the fix gets a regression test, and the rerun is: the failing test, the new regression tests, the tests of the modified modules and of what imports them, the journeys and scenarios that drive them, the safety/cancel/containment/publication tests they reach, and the gate's self-tests when gate code changed. Unrelated passing evidence is not rerun without a dependency or risk reason; evidence keeps its SHA; statuses distinguish PASS on the current SHA, PREVIOUSLY PASS — NOT AFFECTED, NEEDS RERUN, FAIL, BLOCKED and NOT RUN; shared infrastructure or an unbounded change widens the rerun; a targeted run is never a canonical full-gate PASS. `--mode focused` is the tool; `--mode changed` is not used where its routing would widen a narrow fix to the whole repository.
- **Release boundary unchanged.** The approved final P7 full gates on macOS and Windows on the same finalized SHA stay mandatory; REAL CLEAN (`fresh-macos`, P7c) is unchanged; P2 does not begin until P1B is closed.
- **Planning defaults, not newly signed decisions** (formal approval stays open): keep the Aqua minimum 1120 × 800 for this phase; defer D11c (the Converter's continuous-route FFmpeg qualification on macOS); defer D11b (cross-process staging cleanup, ACT72-076); defer MAC-042 (Dock and menu name) to packaging.

**Implementation decisions (Claude Code).**
- **Real pictures without a privacy grant.** The macOS session images the application's own window with `CGWindowListCreateImage(kCGWindowListOptionIncludingWindow)` inside the application process: measured on this Mac (macOS 27.0.1) with `CGPreflightScreenCaptureAccess()` false, a process's own window comes back whole (title bar included) and nothing else is imaged. `screencapture` of another process's window would need Screen Recording, which this host (Cursor) does not hold; it was not requested or bypassed. Each picture carries a provenance sidecar (source SHA, tool, appearance, size, state) and Tk's audit of that moment; `helpers/visual_review.py` decides PASS/FAIL/UNVERIFIED. Defects: a control's text clipped, a control outside the window, overlapping controls, text contrast under 3.0. Advisories (never decisive alone): a clipped label, contrast between 3.0 and 4.5. Aqua's natively drawn buttons are counted as unresolved for contrast (Tk's style lookups do not describe AppKit's drawing; the first audit falsely flagged the white-on-blue default button).
- **Real native dialogs, synthetic events, no Accessibility.** With `native_dialogs` the stand-ins are not installed. A watcher thread inside the application reads each panel from the panel itself and answers it: alerts with Return/Escape posted to the application's own event queue (`postEvent:atStart:`), open panels with their own `cancel:` performed on the main thread in the modal run-loop mode. `abortModal` alone hangs a panel shown as a sheet (measured: the MP3 Tool, Converter and Metadata Editor attach their panels to the window), so it is only the fallback. The open panel's browser is drawn by `openAndSavePanelService`: posted keys do not reach it and its picture is blank (measured), so choosing files inside it is BLOCKED on Accessibility (`darwin_p1b: native-panel-selection`) and never claimed.
- **A picture out of register is named and retaken, never passed** (`c0a1553`). The journeys run at `b97d5bf` failed one picture of 133: `converter.cancel-during-encode`'s "cancelled" image showed the window 16 points right of the image's bounds (32 px transparent at the left, the right edge cut off), while AppKit's frame and Tk's layout were exactly those of 96 other pictures at that position: the window server's image, not the application, was wrong for an instant. The review now checks "the window fills the picture to its edges (in register)" (the transparent run inward from each edge's middle; 4 px or more fails, 1 px is border rounding, seen once), and the session retakes only a take that fails that check, at most twice, keeping each rejected image (`<name>.out-of-register-<n>.png`, listed in the sidecar's `retakes`). A take with the wrong content, appearance or layout is never retaken; one still out of register after the last retake fails. Re-reviewing the evening's 133 real pictures with the new check: 132 PASS as before, the one FAIL named by the new check.
- **A real alert's Return reaches it when another application holds the front** (`b8e0c92`, corrected in `cf85aa1`). At `c0a1553` and again at `f8af54b` the native-dialogs and visual scenarios failed at their first real alert answered with Return: a system alert (`UserNotificationCenter`, 260 × 318, modal-panel layer; its text is withheld without Screen Recording) held the front, so macOS did not make the application active, and AppKit answers Return only in an active application's key window; a posted Escape still worked. The alert is almost certainly macOS's crash dialog for the journeys' deliberate crash controls: each journeys run writes two `python3.12` crash reports, the alert appeared after those runs, and the owner's last input followed the earlier ones. `b8e0c92` handed the event to the alert window's `performKeyEquivalent:`, which works only while the application is active (measured live both ways), so it did not fix this. `cf85aa1`: with the application not active a Return is answered by the button Return presses — the alert window's `defaultButtonCell` (measured on Tk's yes/no alert: "No" carries the Escape key equivalent, "Yes" none, and the default button cell is Yes's) — performing its click on the main thread; the record says it is a click, names the button and the activation state, and the scenario's check accepts only a posted key event or that click. Escape keeps the queue. Proved live with the system alert in front and untouched (Return → Yes, Escape → No). The key-event path itself is the one taken whenever the application is active (all three alerts at `b8e0c92`). No permission is used; the system alert was left for the owner.
- **Darwin evidence is named per journey** (`darwin_map[...].evidence`: `journey-checks`, `real-screenshots`, `dialog-contract`); an automated entry with `manual` is refused by the map check. The `owner-manual` class remains in code for a future owner-only item and is used by no scenario.
- **The closeout scenarios are darwin qualification scenarios with runners** (`macos-native-dialogs`, `macos-visual`, `macos-kx10`), run through the acceptance runner's own `run_one` but never registered as journeys: the journey registry and the 55-scenario required set Windows shares are unchanged. `fresh-macos` keeps no runner.
- **KX-10 automated** as SIGKILL of exactly the application process (pid and kernel start time) while an FFmpeg child encodes a real Maker book; the Force Quit window itself is not exercised (its effect on the process is SIGKILL). The killed build's private `.work` staging is left in place and not reported on relaunch — recorded as found under ACT72-076, not as recovery.
- **Incremental evidence is bookkeeping over the gate's own runs** (`helpers/evidence_ledger.py`, `verify.py --evidence`): each run records every file it saw as a git blob (`evidence-files.json`, on every platform); a run is admitted only if `runstore.read_run_status` reads it back valid; an item's dependence is its static import closure (with module- and `.py`-naming strings), `conftest.py` in every test's closure, journeys bounded to their own module and tool, and the policy's `changed` routes; any other non-Python change reaches everything. It prints EVIDENCE, never RESULT. A session-wide Downloads guard in `conftest.py` was not added: it would change shared test infrastructure (invalidating every test's evidence) and could fire on the owner's concurrent use of the app; the barrier is `files/tests/output_guard.py` in the tests that run real tools, plus the gate's existing before/after checks of the default output folder.
- **The owner's visual record re-opens only on application code** (`f8af54b`). `verify.py --evidence` carries the owner-reported Dark acceptance while `scripts/` and `config.toml` are as at `455bf83`, leaving out the paths the policy names in `changed.no_selection` (the owner's own untracked `scripts/project-status.py` had read as an application change).
- **New open issues:** ACT72-077 (the macOS first-run window offers Kokoro checked by default and shows Windows-only/GPU engines with Windows wording; Qwen3 and OmniVoice are refused before any download — P5 for the window, P2–P4B for each engine's availability); ACT72-078 (text clipped at the 1120 × 800 Aqua minimum: the TTS panel's header subtitle; the MP3 Tool's and Maker's book counter, cut to "(1 of" beside a long title; the Metadata Editor's Source path; and two short boxes there — the TTS Sources list one row, the Metadata Editor's chapter titles one line — decided with the minimum); ACT72-079 (a progress line reads "Calculating…" when nothing is being estimated: before any run, beside 100 % when finished (Cover, Maker), beside 50 % when cancelled (Converter)); ACT72-080 (native-panel selection with a real keyboard or pointer: BLOCKED on Accessibility).

**Why.** The owner wants manual involvement only where judgment or an OS permission is unavoidable, and every functional claim backed by evidence the gate re-checks. Each mechanism here uses what macOS allows a process to do to itself, says exactly what it does not prove, and keeps Windows' contracts as they were.

Signed: the owner (decisions above, by instruction of 2026-11-15); Claude Code (implementation decisions).

## 2026-11-15 — macOS P1B: implementation decisions for the five tools, containment, platform and the darwin gate; five owner decisions requested (implementation decisions by Claude Code; owner decisions pending)

Scope: P1B only (plan §19 P1B). No TTS engine work, no P2, no merge, tag or release. Windows behaviour is unchanged except where listed under "Windows touchpoints" in the Handoff P1B block.

**Implementation decisions (Claude Code).**
- **The app window owns its children on macOS.** `launcher.main` makes the window the containment owner (`subprocess_utils.enable_containment`): FFmpeg and ffprobe start as class B in the guardian's group; optional setup's Python workers as class A with the `act-lifeline`. A class-A child running under a lifeline becomes the owner of its own Python children (`qwen3_process._posix_owner`), because the setup worker's `pip` otherwise escaped into a new session (found by KX-1(e)). Stopping is by registry identity (pid + kernel start time), never by name or a process listing. Windows keeps Job Objects and the Toolhelp `stop_media_children`; `enable_containment` returns `None` there.
- **One close path.** Cmd+Q (`::tk::mac::Quit`), Settings (`::tk::mac::ShowPreferences`), SIGTERM/SIGHUP/SIGINT (through a wake-up pipe Tk watches) and the red button all reach `LauncherApp._on_close`, which runs once. After the main loop the signals are handed back and the two Tcl commands deleted: both held the closed window from C (found by the shutdown journeys; SIGTERM after close was otherwise swallowed). An inherited `SIG_IGN` stays ignored.
- **`RLIMIT_NOFILE`:** the soft limit is raised to `min(hard, 4096)` on macOS. Justified by measurement, not by need: eight Edge-like workers (an FFmpeg pipe, temporary files and a socket each) peaked at **53** descriptors under the inherited soft limit of 256 (`test_macos_p1b_filesystem.py`); the raise is headroom for long books and many files.
- **Publication on macOS:** `output_paths.move_without_replacing` uses `renamex_np(RENAME_EXCL)` first, then a hard link; exFAT and FAT (measured on macOS 27 FSKit: no link, no exclusive rename, `rename` replaces, `O_EXCL` works, NFD stored as given and found by NFC) are **refused with a clear message, never published by a look followed by a move**. TTS publication uses the same primitive.
- **Output permissions:** on POSIX the temporary sibling that becomes an output is created with mode 0o666 under the user's umask (it was `mkstemp`'s 0o600: every Converter MP3 was owner-only, found by the owner-media qualification), and a file replaced in place keeps its permission bits. Windows keeps `mkstemp`.
- **The Aqua minimum stays 1120 × 800, provisionally** (`ui_theme.AQUA_MIN_SIZE`). The owner ruled 1024 × 800 for Windows (v0.6.4 Phase 13). On Aqua the sidebar cannot shrink below about 190 points without truncating "TTS Audiobook" and "M4B Converter", and at 184 points the M4B Maker's ETA line was still 49 points over. Windows layout expectations were not changed to satisfy Aqua. **Owner decision requested (1).**
- **Tk 9 on macOS:** `<TouchpadScroll>` and small wheel deltas handled where Tk's own classes do not (canvas, the Qwen3 dialog, the shared scroll helper), Command-A select-all on Aqua only, Menlo for logs and the platform UI font for the optional-setup panel — each guarded by the running Tk or windowing system; the Windows formulas are kept byte for byte.
- **Main-thread rule held, measured:** no Tk call from a worker thread during a real 90-minute Combine with 150 window-manager resizes (MAC-032); the same audit wraps every macOS journey.
- **The darwin gate** (plan §14.3): `skip_policy.darwin` with exact reasons and maxima from the census; `acceptance.darwin_map` maps all 55 required scenarios and the optional `tts.kokoro-local` exactly once — 38 automated now (in-process driver `adapters/macos`, no Accessibility or Screen Recording grant), 12 mapped to their later phase and reported NOT RUN (9 TTS → P2, 3 setup → P5), 6 NOT APPLICABLE ON MACOS (only the Windows input-harness self-tests, reason id `windows-input-harness`); 20 automated journeys also need the owner's signed `macos-checklist:native-dialogs` record for the candidate SHA. `judge_darwin` holds the report to every rule `judge` has (token, registered set, duplicates, unselected, unknown, exit status, required tools) plus the Tk thread audit. A darwin acceptance stage therefore cannot PASS before P2/P5 and the owner's signature; it never reports a blanket NOT APPLICABLE. `fresh-macos` is a mandatory darwin scenario reported NOT RUN until the owner's signed run of `qualification/fresh_macos_procedure.md`; P1B made no run of any class and claims no REAL CLEAN.
- **The M4B Converter's continuous route stays refused on macOS** (`build_refusal`: only the Windows Gyan builds are qualified). On the owner's xHE-AAC book the route was refused and the seek-per-chapter route used, every audio decode through `aac_at`. Its 17 real-media proofs in `test_m4b_continuous.py` fail loudly on this build by design ("never a skip") and stay baseline failures. **Owner decision requested (2): D11c** — qualify the Riedl build with the `m4b-scaling` harness (about 3 hours), or accept the slower route on macOS and give those proofs a reviewed darwin disposition.
- **Work-area recovery (D11b) not implemented:** on macOS another, killed process's work area is never reclaimed (the safe direction); open issue ACT72-076. **Owner decision requested (3).**
- **MAC-042 measured, not changed:** AppKit names the app `python` (the interpreter's file name), a regular Dock app with a generic icon, frontmost at launch. A fix needs a named interpreter link used by the launcher or an `.app` wrapper at packaging. **Owner decision requested (4).**
- **Not introduced without an owner decision:** `F_FULLFSYNC`, `caffeinate`, any other optional system behaviour; the Converter's continuous route on the new FFmpeg.
- **MAC-039 (Terminal auto-close Automation prompt) and the Finder reveal** are owner-manual checklist items. **Owner decision requested (5):** sign the P1B checklist (`files/dev-work/macos-acceptance/P1B-owner-checklist.md`, bound to the candidate SHA), including KX-10.

**Why.** P1B's exit asks for the five tools to work natively on macOS with Windows untouched, every acceptance journey mapped, and nothing claimed that was not observed. Each decision above keeps a refusal or a NOT RUN where the evidence does not exist yet, rather than a pass.

Signed: Claude Code (implementation decisions); the owner's decisions (1)–(5) are pending.

## 2026-11-15 — macOS P1A accepted by the owner at `d6c0d77`: the three manual checks PASS (owner-reported); nothing else changes (owner decision; recorded by Claude Code)

- **Owner decision.** P1A is accepted as PASS at the exact SHA `d6c0d77c010b1412dc3adb13aa73c67b1db71846`. The basis is the automated P1A evidence (the "D3 remediation" entry below) and three manual checks the owner performed personally, each reported PASS:
  1. the listening comparison of the real xHE-AAC audiobook with the converted output (proof 8, C);
  2. the Finder double-click of `Setup_and_Run-audiobook-creation-tool.command`;
  3. KX-4: closing the Terminal window during first-run package installation left no installer running, and the next launch repaired.

  Source: OWNER-MANUAL, owner-reported in the P1B kickoff. The agent observed none of them and made no screenshot, observation record or signature for them.
- **Unchanged by this acceptance.**
  - The 333 pre-existing macOS test failures stay unresolved baseline failures.
  - No canonical macOS full gate has passed; none runs before P7.
  - Clean-install evidence stays SIMULATED, never REAL CLEAN (P7c, D18).
  - The seven-file signing exception stays exactly as narrow as recorded.
  - The Riedl 9.0.1 identity and the revised proof 8 are unchanged. The pin is accepted for P1A, not for release.
- **Why it is recorded on its own.** P1A's exit required the owner's checks to be performed by the owner and never inferred (plan §19 P1A, exit 3; §14.2's source qualifier). Binding the acceptance to the exact SHA keeps the evidence attributable: every P1B change comes after it.

Signed: the owner (P1A acceptance, 2026-11-15); recorded by Claude Code.

## 2026-11-15 — macOS P1A D3 remediation: proof 8's sample-count clause amended for one proven stitched file; Riedl 9.0.1 adopted for local qualification (owner listening still pending); a narrow signing exception for seven upstream files; the locks' requirements digest no longer depends on line endings (owner decisions; implementation decisions by Claude Code)

**Owner decisions (2026-11-15, after the D3 forensic investigation).**
- **D3 — APPROVED, revised.** Keep the historical Riedl arm64 FFmpeg 9.0.1 build. Amend only proof 8's sample-count criterion. Decoded audio is never trimmed, resampled or otherwise altered to match Apple's length. Exact alignment and PCM equality over the Apple-decoded portion are preserved. Extra frames are permitted only when the fixture's own packet/sample accounting bounds them and the whole extra region is verified digital silence. The finding is not generalised: no unconditional tolerance, no automatic trimming rule, no assumption that any other xHE-AAC file can be shortened. Every supply-chain, architecture, signing and codec proof stays. No FFmpeg 9.0.2.
- **Source pin.** Enabling the verified Riedl 9.0.1 pin is authorized for further P1A local qualification once the amended automated proof 8 and the real Converter journey pass. This is not the owner's listening acceptance and not release authorization.
- **Native signing — APPROVED narrowly.** The six universal2 wheels' modules whose arm64 slice verifies (the unused x86_64 slice is unsigned) and PyTorch's one hash-verified `libomp.dylib` (reported unsigned, loads and runs). No blanket exception; REAL CLEAN and Gatekeeper qualification stay mandatory for release (P7c).
- **Test remediation and documentation corrections — APPROVED** (below). Not authorized: P1B, TTS engines or models, Windows behaviour changes, merge, tag, release.

**Corrections to the earlier 2026-11-15 P1A entry (that entry is left as written; this one supersedes it where they differ).**
- "the end trim is not applied with `aac_at`" is **not supported**. FFmpeg's model of the file declares no end trim, and `aac_at` applies every trim a container declares (below). Apple truncates its output to the edit-list length (35,199,625 ms → 1,552,303,462 frames); FFmpeg presents all 1,515,928 packets × 1,024 = 1,552,310,272 frames. The file is a stitched concatenation: its `stts` declares 6,822 frames of padding inside the stream, at 15 interior joins, and the last packet is declared fully valid. Apple's "6,810 remainder" is that interior padding less 12.5 frames of millisecond rounding, not trailing padding. Both decoders keep the interior padding (bit-identity at lag 0 across the whole file).
- The P1A Handoff's "3,352 PASS / 334 FAIL / 176 SKIP" merged runs of two code states. The HEAD code measured alone (forensic, LF worktree): 3,347 / 338 / 177. The "four real-coordinator tests" never failed at `de99ba1`, in the composite or at HEAD. The final numbers are below.

**Implementation decisions.**
- **Proof 8, amended, as code: `files/dev-tools/xhe_proof.py`** (stdlib, dev-only, never shipped). T2 (lag ≤ 2,048) and T3 (SNR ≥ 60 dB, ≤ 64 LSB) unchanged. T1 passes within one AAC frame, or through a length exception that needs all of: E1 the source's SHA-256 is an owner-approved record and both measured counts equal the recorded ones; E2 an excess, never a shortfall; E3 lag 0 and every Apple frame bit-identical; E4 FFmpeg's count = packets × frames-per-packet (from `stsz`/`stts`); E5 the excess ≤ the padding the `stts` declares; E6 every excess frame is zero, the whole region read (its SHA-256 equals that of as many zero frames); and the media timescale is the decode rate. One record exists: the owner's fixture, at 1,552,303,462 / 1,552,310,272 frames. Pinning the exact counts makes the exception unusable for any other file, build or decoder change without a new owner decision. Nothing trims, pads or rewrites audio, in the tool or in ACT.
- **Result on the real fixture (MEASURED, the recorded Riedl bytes):** PASS. Lag 0 (exact match); all 1,552,303,462 Apple frames bit-identical (max |diff| 0, SNR ∞); excess 6,810 frames, all zero (`f71c9ca6…797a` = SHA-256 of 6,810 zero frames); declared padding 6,822; packets 1,515,928 × 1,024; FFmpeg exit 0 with no stderr; source SHA-256 `b9a24a88…f8d4` before and after.
- **AAC-LC control (MEASURED):** `Mistborn, Book 1_ The Final Empire.m4b` — head (`-t 2`) 88,200 frames and tail (`-ss 88670`) 1,480,323 frames for both `-c:a aac` and `-c:a aac_at`; with `-flags2 +skip_manual` 1,481,480 (+1,157): the declared trims are applied to `aac_at` exactly as to the native decoder. A synthetic AAC-LC file from Apple's own encoder (2,112 priming + 1,003 remainder declared): FFmpeg `aac_at` and `aac` both give exactly the source's 133,077 frames, and the decode equals Apple's at the same length (proof-8 tool PASS, difference 0).
- **Adoption:** `ffmpeg_portable.MACOS_FFMPEG_PIN = MACOS_RIEDL_9_0_1` (the constant renamed from `MACOS_RIEDL_9_0_1_CANDIDATE`; `adopted=True`). Every recorded value is unchanged: build path `1787073674_9.0.1`; `ffmpeg.zip` 28,447,413 B `8287a1b2…07fe`, `ffprobe.zip` 28,370,930 B `102a26b8…741a`; programs `393e4c39…1611` and `7abc49fb…71bc`; `Developer ID Application: Martin Riedl (KU3N25YGLU)`. Acquisition and every repair repeat proofs 1–7 against them. Status recorded in the pin: automated source identity and runtime/audio qualification PASS; owner listening PENDING; not release-accepted.
- **Converter real-media journey (MEASURED):** the real panel (`M4BConverterUI`), worker, planner, FFmpeg commands and publication on the adopted build, in `p1a-sim`; harness seams only for the output folder and the Finder reveal. **Split by chapter:** SUCCEEDED in 567 s; 15 MP3s named `NN - <title>.mp3` (the product writes `:` as `_`); the run revealed its own folder and nothing else is left in it. The independent check passed 77/77:
  - each chapter sits within 0.6 samples (22.05 kHz) of the position the source's `stts` predicts, and matches its source audio over its whole length (lag ≤ 16 samples, correlation ≥ 0.90, edge energies);
  - lengths are within 0.1 ms of the chapter span plus the padding declared inside it;
  - consecutive chapters meet within ±1 sample (no gap, no overlap);
  - the last chapter ends at the decode's last sample, the 6,810 zero frames included.

  **Whole book:** SUCCEEDED in 131 s; 44/44 checks passed. Its length equals the source decode (35,199.7794 s); it decodes cleanly; it has 15 chapter markers (titles, starts within 0.05 s) and artwork; every chapter interval and the last 30 s match. The source SHA-256 is unchanged. The first split check sliced the reference at time × rate, which this stitched file breaks: FFmpeg presents the 14–926 padding frames declared at each of the 15 joins, while chapter times are timestamps (chapter 3 was off by exactly join 1's 588 frames). That check and its file-name expectation (it expected ` - `) were corrected and re-run on the same published files. The product was not changed.
- **SIMULATED acquisition, relaunch and interruption** (PATH-restricted, `env -i`, scratch HOME/TMPDIR, recording shims, clean LF worktree `p1a-sim` at `1a6604a` + this change, adopted pin): the first-run FFmpeg step (`bootstrap.ensure_ffmpeg`) from an absent installation downloaded both ZIPs from the pinned build path, ran proofs 1–7 and pinned the exact programs (`393e4c39…`, `7abc49fb…`) in 4 s. Healthy relaunches through the real `.command` returned rc 0, with no download and no notice. `kill -9` during the launch-time repair, while `ffmpeg.zip.part` held 1,048,576 bytes, left 0 ACT processes after 3 s; the next `.command` removed the partial, downloaded again, verified and pinned (rc 0). `kill -9` during verification, with codesign running, left 0 processes (codesign included) and a dead run's stage folder; the next `.command` removed it and reused the verified ZIPs (rc 0). Every GUI loaded 0 images from `/opt/homebrew` or `/usr/local`. The recording shims (brew, PATH python/pip/ffmpeg, xcrun) were called 0 times. The launcher's Terminal-close helper was recorded by an `osascript` shim and never sent. The scratch HOME and TMPDIR stayed empty. 0 ACT processes were left.
- **The narrow signing exception, as code: `files/dev-tools/macos_native_audit.py`** (dev-only). Every Mach-O under `files/runtime-data/python`, `.venv` and `files/bin` must contain arm64 (arm64 only unless approved), link only system libraries or its own installation in every slice, and pass `codesign --verify --strict`, or be one of exactly seven files judged as recorded: the installed bytes equal the recorded SHA-256 and pip's `RECORD`; the architectures equal the recorded ones; for the six universal2 files `codesign --verify --strict --arch arm64` passes; for `libomp.dylib` codesign's verdict is exactly "not signed at all" (an architecture note may follow; any other failure is not excepted) and, with `--prove-load`, the loader maps it, its own code runs (`omp_get_max_threads`), and PyTorch reports its OpenMP backend and computes an exact parallel sum. Files, installed SHA-256, wheel (whose SHA-256 is its macOS-lock hash; each member equals the installed bytes): `_brotli.cpython-312-darwin.so` `faeac3d1…4eb9` (brotli 1.2.0 universal2, `35d38262…4f84`); `onnx/onnx_cpp2py_export.abi3.so` `4b638f68…85f3` (onnx 1.23.2, `1b8680ce…c1f6`); `google/_upb/_message.abi3.so` `5fe9c5aa…4f6d` (protobuf 7.36.2, `cbc70b17…079e`); `charset_normalizer/cd.cpython-312-darwin.so` `d38c3dff…a48b` and `md.cpython-312-darwin.so` `cd79f238…f655` (charset-normalizer 3.5.2, `ed2a239c…a491`); `ml_dtypes/_ml_dtypes_ext.cpython-312-darwin.so` `00d3d4ce…e353` (ml_dtypes 0.5.4, `a174837a…7dac`); `torch/lib/libomp.dylib` `def839a0…3dd0` (torch 2.6.0 arm64, `9a610afe…0989`). Upstream files are never modified, re-signed or replaced. Why it is safe here: the host Python has no hardened runtime (no library validation); pip installs these from hash-locked wheels without quarantine; `release.py` ships no `.venv`. A future hardened or notarised host (D10) needs a fresh evaluation. **Real audit of the SIMULATED installation (MEASURED):** 435 Mach-O files: 428 PASS, 7 PASS-EXCEPTION, 0 FAIL; load proof PASS.
- **The locks' `requirements.txt sha256` header no longer depends on line endings.** `base_packages.requirements_digest` hashes `requirements.txt` with every line ending written as CRLF: the form the released Windows lock was generated from, so its header (`a4805b76…42dc`) and the macOS lock's still match, with neither lock changed by a byte, while an LF checkout, a CRLF checkout and an extracted archive now agree. Any change other than line endings still changes it. Used by the gate's `deps` stage, the lock generator and the tests. Setup's receipt stamp (`bootstrap.requirements_fingerprint`) still hashes the raw bytes: unchanged on Windows (a test recomputes it as released), and self-consistent within any one tree. CRLF rather than LF is chosen only because LF would have required rewriting the released Windows lock's header.
- **Test-environment corrections, assertions kept.** `test_cleanup_state::test_the_real_base_interpreter_is_found_and_is_outside_the_project` now asserts the product's rule against both roots it can be given (the disposable root, and the real checkout, where only the app's own base Python may be inside), instead of assuming the test interpreter lives outside this checkout. The `setup_steps` fixture of `test_bootstrap_requirements_state` stubs the sentence-data step, which wrote an empty `files/runtime-data/nltk_data` into the real checkout on a fresh tree and tripped the session guard (pre-existing since the step was added). The session guard itself is unchanged.
- **The suite refuses the real macOS own-build route, as it already refused the Windows one.** With a build adopted, `bootstrap._download_portable_ffmpeg_macos` reaches the real acquisition; the network refusal is caught and logged by the download step like any network error, after the staging folder exists, so a test that reached it passed while writing `files/runtime-data/ffmpeg-staging` (found by the guard in this checkpoint's first CRLF run: `test_first_run_contract`'s `no_package_manager` fixture and two `test_ffmpeg_health` tests stubbed only the Windows route). `conftest._no_real_provisioning` now refuses the Mac route by name too; those fixtures stub it like the Windows one; the one test that exercises the real Mac wrapper does so inside its sandbox. The empty folder this run created was removed after checking it was empty and born in this session. Windows never reaches either Mac stub.
- **First-run text on a Mac.** When setup's FFmpeg step fails on a Mac it now says the app uses only its own verified build and tries again by itself at the next start (the launch path repairs FFmpeg), instead of "Install it (ffmpeg.org) and re-run", which a Mac would ignore under D3. The Windows text is byte-identical.

**Tests (final, MEASURED; one pytest process per file, the same 61-file list as the forensic HEAD run, plus the stage-0 module and the two new modules).** 3,896 test ids. **Clean LF worktree:** 3,388 PASS, 333 FAIL, 175 SKIP. **Inherited CRLF main checkout:** 3,384 / 333 / 179. **0 new failures** against the untouched `de99ba1` (either representation), and 0 regressions against the forensic HEAD run. All 333 failures also fail at `de99ba1`. 332 fail for the same reason (14 of them differ only in worktree paths, PIDs or truncated gate output). One changed: `test_base_packages::test_the_deps_gate_passes…` now fails only on its Windows-only "170 packages" expectation, because its line-ending part is fixed. By file: qwen3_setup 84, qwen3_offline_engine 45, omnivoice_setup 42, omnivoice_layout 36, qwen3_nested_adoption 33, cleanup_engine_lease 31, long_paths 18, verification_gate_contract 13, optional_tts_setup 11, venv_recovery 8, qwen3_runtime 3, base_packages 2, qwen3_environment_layout 2, release_installer 2, qwen3_install_ui 1, qwen3_lifecycle_locks 1, verification_coverage 1.
  - Fixed against the forensic run (5): the three new P1A line-ending tests; `test_base_packages::test_the_lock_records…` (failing since `b025b6c` in an LF tree); the `nltk_data` guard echo.
  - Fixed against `de99ba1` (3): that lock test, `test_this_test_environment_is_exactly_the_locked_set` and `test_a_copied_ffmpeg_state_is_replaced_by_this_copys_own_ffmpeg`.
  - 11 baseline ids are absent because they were renamed: 9 Homebrew-era Mac tests in P1A and 2 here (the "no build adopted" and "candidate" tests became the adopted-pin tests).
  - LF and CRLF differ only in 8 skips that depend on local data: the pinned Python archive and the Riedl ZIPs exist only in the main checkout; a qualified environment and an installed FFmpeg exist only in `p1a-sim`.
  - Skips are Windows-only reasons (junctions, Job Objects, named mutexes, long paths, the `.bat`), plus 4 for local data not present: the AAC-LC control, the 6 GB Apple decode (opt-in), the pinned archive and the Riedl ZIPs.
  - Real-media tests run in this checkpoint: the amended proof 8 on the fixture, the Mistborn control and the synthetic AAC-LC control all passed.
  - One observation, not reproduced: during the first LF attempt the empty `files/runtime-data/ffmpeg-staging` folder left by the simulations in `p1a-sim` disappeared. Neither a full rerun nor a file-by-file pass over all 66 modules reproduced it, and the cause was not identified. It was an empty folder in a disposable worktree.

**Still open.** Owner listening of the xHE-AAC output (proof 8, C); Finder double-click; KX-4 (closing Terminal during first-run pip). Each stays PENDING until the owner performs it. P1A is therefore not PASS. P1B: the `win32` skip rule for the native-only reason (its count changes with the new tests), the darwin gate preflight, the 333 pre-existing darwin failures, the inventory CLI's `winreg` import.

Signed: the owner (D3 revised, the signing exception, the remediation scope, 2026-11-15); implementation decisions recorded by Claude Code.

## 2026-11-15 — macOS P1A: the owner's D1–D5; the app's own Python, lock and FFmpeg route on a Mac; setup's children contained after any exit; the Riedl 9.0.1 candidate passes proofs 1–7 and not proof 8, so it is not adopted and D3 returns to the owner (owner decisions D1–D5; implementation decisions by Claude Code)

**Owner decisions (2026-11-15, authorizing P1A only).**
- **D1 — APPROVED.** The app-owned python-build-standalone CPython 3.12.15, release `20261009`, native macOS arm64, with Aqua Tk 9.0.4; the bounded Tk 9 compatibility work is accepted. No other interpreter and no admin-required install without renewed approval.
- **D2 — APPROVED.** The default macOS launcher no longer installs Homebrew or a Homebrew/PATH Python; ACT uses its own verified Python. The existing Homebrew installation is not changed.
- **D3 — CONDITIONALLY APPROVED.** Evaluate the historical Martin Riedl macOS arm64 FFmpeg 9.0.1 build first; the authorized downloads are its `ffmpeg.zip`, `ffprobe.zip` and their `.sha256` files. All eight proofs of plan §11.1 are required before adoption. No 9.0.2, no other version and no unverified alternative without a separate owner decision.
- **D4 — APPROVED.** The disk-only `chmod +x` of the existing `.command`; owner changes and Git settings preserved; clean LF disposable worktrees where the plan requires them; new executables staged as `100755`.
- **D5 — APPROVED.** Network for P1A from python-build-standalone, PyPI and the FFmpeg source, with hash enforcement and the download consent. Not TTS models, Qwen3/OmniVoice, Whisper, system-wide installs, Homebrew changes or later phases.

**Implementation decisions.**
- **Stage 0 checks architecture with `/usr/bin/file`, never `lipo`; runtime code reads Mach-O headers itself (`shared/macho.py`).** Measured on this Mac: `/usr/bin/lipo` and `/usr/bin/otool` are byte-identical to `/usr/bin/git` and `/usr/bin/clang` — the `xcode_select` tool shim — so on a Mac without the Command Line Tools running either opens the "install developer tools" prompt. The plan's `lipo -archs` steps are kept as developer cross-checks only. `codesign`, `file`, `shasum`, `curl`, `tar`, `afconvert` are real system programs.
- **One lock per platform; Windows byte-identical.** `base_packages.LockTarget`: Windows keeps `requirements-lock-windows-py312.txt`, `python-packages`, `pip-cache` and the same requirements stamp (a test renders the committed Windows lock byte-for-byte and recomputes the stamp). The Mac uses `requirements-lock-macos-arm64-py312.txt` and the sub-folders `python-packages/macosx_arm64`, `pip-cache/macosx_arm64`, `python-packages-quarantine/macosx_arm64`, so a folder copied from Windows can never offer a Windows artifact (MAC-029). A Mac never installs without the lock's hashes (no unhashed fallback, unlike other platforms).
- **The macOS lock freezes the Windows versions.** Generated natively (`lock_base_requirements.py --platform macosx_arm64`) on the app-owned interpreter with the Windows lock's 170 versions minus `colorama` (Windows-only marker) as constraints; pip's resolution matched exactly: 169 packages, each with one artifact hash (40 arm64, 5 universal2, 122 pure, the same 2 pure sdists Windows builds), no Windows or x86-only artifact, torch 2.6.0 `macosx_11_0_arm64`. No pin changed.
- **Containment (plan §11.2.2) as built.** Class A (pip and its build backends, `-m venv`, probes) start through `shared/child_entry.py`, whose first statements start the lifeline thread; class B (here `codesign`) joins the guardian's group at spawn. Every bootstrap spawn goes through `_child_run`/`_child_popen` paths on POSIX; on Windows those helpers call `subprocess` exactly as before (AST guard KX-9). The guardian is started on the first class-B spawn rather than at process start (no class-B child can exist earlier).
- **A guardian that dies on its own fails closed.** The owner waits on its guardian; if it ends unexpectedly, every class-B child still in its group is ended (identity-checked SIGTERM, then SIGKILL), marked `lost_containment` so its caller reports a failure (a bounded run returns non-zero with "lost containment"), the event is recorded, and the next class-B spawn starts a new guardian first; no class-B child is ever started without a guardian that answered `ready`. **Residual:** a class-B child whose guardian died *and* whose owner died (or was stopped) before the owner's watcher ran; a guardian that is SIGSTOPped (not dead) does not act until continued. Stage 0 (class C, bash): if the stage-0 script alone is SIGKILLed, its curl or probe child is not ended by anything (curl is bounded by its own `--max-time 1200`/`--speed-time 60`; the next run removes the dead run's files); closing the Terminal window, Ctrl+C and SIGTERM are contained.
- **CPython has no `os.waitid` on macOS.** Found when the first version crashed in a native test: a class-A group is SIGKILLed while its leader is still unreaped, so the owner observes exit through the kernel's process state (`kinfo_proc.kp_proc.p_stat == SZOMB`, via the same `sysctl` as the start time).
- **Synchronous probes stay `subprocess.run`.** A timed-out `run` ends its child as before; every such call site is a single process. The lifeline still ends it, and anything it started, when setup ends however it ends.
- **FFmpeg on a Mac: the app's own folders only.** Under D3 ("no unverified alternative"), macOS FFmpeg discovery looks only in `files/bin` and `files/bin/ffmpeg/<version>`; a PATH or Homebrew FFmpeg is never probed, and an earlier pin outside the app's folders is ignored. A candidate's Mach-O header must say arm64 before it is executed, and a pair is usable only with the `aac_at` decoder. Homebrew is never run (D2). Windows and Linux discovery are unchanged; the tests that hold the PATH contract now say so explicitly.
- **Riedl 9.0.1 (`1787073674_9.0.1`) evaluated on the actual bytes (2026-11-15).** Proof 1: both ZIPs downloaded with curl (no `com.apple.quarantine`; only `com.apple.provenance`). Proof 2: `ffmpeg.zip` 28,447,413 bytes, SHA-256 `8287a1b2229e05eb41859f073e18e6c52c60a778f2f5e6881070fe51b79407fe`; `ffprobe.zip` 28,370,930 bytes, `102a26b8940a053298d9929bfaae71e4b6ef65ba5f19a99a88c433108560741a`; both equal Riedl's published `.sha256` (two hashers). Proof 3: each ZIP holds exactly one regular 0755 member; programs `ffmpeg` 66,334,032 bytes `393e4c395020a1cb7cbd77fbe00599ce69d1c6466fee0dbd59d13f86a81a1611`, `ffprobe` 66,159,232 bytes `7abc49fb2bdf2204f018e76dc6e0a8ae7643313bae09a9fa43e7eb12442271bc`. Proof 4: arm64 only. Proof 5: `codesign --verify --strict` passes; `Developer ID Application: Martin Riedl (KU3N25YGLU)`, hardened runtime, timestamped 2026-08-18 (`spctl`: not an app; informational). Proof 6: only `/usr/lib` and `/System/Library` (incl. AudioToolbox). Proof 7: `-version` 9.0.1, decoder `aac_at`, encoder `libmp3lame`; the production acquisition (`ffmpeg_portable.acquire_macos`) repeats 1–7 against these values and pins the pair (test, from the local verified copies). **Proof 8 (tolerance fixed before measuring):** on the owner's local xHE-AAC audiobook (`afinfo`: `usac`; 35,199.6 s), FFmpeg's `aac_at` decode is bit-identical to Apple's `afconvert` decode for every one of Apple's 1,552,303,462 frames (lag 0, maximum difference 0), but carries **6,810 further frames of digital silence** at the end (1,515,928 × 1,024: the end trim is not applied with `aac_at`; Apple's length equals the last chapter's end). That exceeds the one-AAC-frame (1,024) sample-count tolerance, so **proof 8 FAILS as specified**; the owner's listening check and the Converter journey on this build were not run. FFmpeg's native `aac` decoder fails the same file (362,464 packets "not implemented"), which is why ACT uses `aac_at`. The fixture's SHA-256 was identical before and after.
- **So nothing is adopted.** `ffmpeg_portable.MACOS_FFMPEG_PIN = None`; the Riedl values are recorded as `MACOS_RIEDL_9_0_1_CANDIDATE` (`adopted=False`), which production refuses (it downloads nothing and says no build is approved) and only qualification code passes explicitly. **D3 returns to the owner** with the measured evidence; 9.0.2 was not downloaded.
- **macOS-only tests and the Windows gate.** The new tests that need a Mac skip elsewhere with one exact reason, `native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks`. The `win32` skip policy was not edited in P1A (the plan keeps it unchanged and gate policy is P1B); P1B must add one reviewed `win32` rule for that exact reason with its exact count before any Windows full gate on this branch, or the gate will report those skips as unexpected.
- **Receipts are platform-bound by construction.** The requirements stamp hashes the platform's own lock (name and bytes) and the import proof records the interpreter's identity, so a Windows stamp never matches on a Mac; no stamp format changed on Windows.
- **The launcher's headless fallback is gone on macOS.** The app's own Python always carries Tk; a Tk proof that fails is a stage-0 failure with its reason, and the interpreter that failed is set aside (`python.unusable-<time>`), never deleted.
- **Two defects the SIMULATED run found, fixed in the same phase.** (1) A setup killed while `python -m venv` ran (ensurepip included) left an environment with no pip that every check called healthy; the next setup kept it and every install failed. Worse, the real launch path then failed the same way on every later launch. On a Mac, an environment whose `lib/python3.X/site-packages` exists but holds no `pip-*.dist-info/RECORD` (what `python -m venv` leaves when killed during ensurepip) is now repairable (`incomplete`) and rebuilt by the launcher. A completion-marker file was tried first and withdrawn: the project's recovery rule is to re-evaluate existing authorities and record nothing new (`test_no_new_success_marker_file_was_introduced`), and pip's own record is that authority. **Windows has the same latent gap and is not changed here** (a shared fix needs its own owner approval and Windows re-verification). A pre-P1A Mac environment built on a Homebrew Python is not yet rebuilt automatically (open item). (2) The FFmpeg build server answers Python's default `Python-urllib` user agent with HTTP 403 (measured; curl and a neutral agent get 200); the macOS download sends `AudiobookCreationTool` and a 60 s socket timeout. The earlier test served the ZIPs from local files, so only the live run could catch it.
- **Linkage-verified evidence, as measured (SIMULATED).** 435 Mach-O files under `files/runtime-data/python`, `.venv` and `files/bin`: every one contains arm64 (429 arm64-only, 6 universal2), and none links outside `/usr/lib`, `/System/Library` or the app's own folder (ACT's reader and `otool -L` agree). `codesign --verify`: 428 pass; the 6 universal files fail only on their unused, unsigned x86_64 slice and pass with `--arch arm64`; torch 2.6.0's bundled `torch/lib/libomp.dylib`, byte-identical to the hash-verified PyPI wheel, carries a CodeDirectory but `codesign --verify` reports it "not signed at all", and it loads (the torch import proof). Upstream bytes are never modified; this is recorded for the owner rather than called a pass.
- **The gate's focused mode does not run on macOS yet.** Its preflight stops at a Windows-only path in the guarded-process specification (`.venv/Lib/site-packages/...`), before any test runs (P1B's darwin preflight). P1A's focused tests ran through pytest directly, with every result compared, by test id, with the untouched baseline on this Mac.

Signed: the owner (D1–D5, 2026-11-15); implementation decisions recorded by Claude Code.

## 2026-11-14 — v0.8.0 Windows release: the owner accepts the combined verification evidence as a maintainer release exception; no new full gate; the original full gate stays FAIL; macOS deferred (owner decision; release mechanics by Claude Code)

**Owner decision (2026-11-14).** Accept, for the Windows v0.8.0 release, the combined evidence: the passing stages of
the one canonical full gate `2026-11-14_113416_full_c8e8` on `c583d78` (15,942 of 16,009 tests passed, 2 failed, 65
skipped; 54 of 56 journeys; four failing checks, all verification pins that predated v0.8.0's additions), the F1-F5
remediation `ee426fd` with its focused checks (PASS), the independent Codex review's R1-R3 remediation (`c583d78`)
and the owner's approval of all 12 OmniVoice listening tracks. Do not rerun the full gate. Integrate into `master`,
build and audit the Windows ZIP, tag `v0.8.0`, publish the release. Defer macOS.

- **An exception, not a PASS.** It replaces, for this release only, the earlier requirements of a passing full gate on
  the final tree and an external Windows qualification before release. The run `c8e8` is a FAIL and is recorded as
  one everywhere; nothing claims the corrected tree passed a full gate.
- **What stays open, said where a user reads it.** The README's "Release verification and what is not yet qualified"
  section, the acceptance record and the release notes list the unqualified configurations: the real long-path
  switch-on (UAC prompt, restart, standard and managed accounts), long paths off, folders exactly at a limit, Windows
  10, other computers and scaling, other GPUs for OmniVoice, and the full five-component first run on the final code.
- **The README pin follows the release, it is not dropped.** `test_long_paths.py` held "there is no v0.8.0 download"
  as a pre-release guard. It now requires the opposite facts that matter after release: exactly one v0.8.0 Windows
  download link, no macOS v0.8.0 archive, the sentence that the switch-on was released untested on a real machine, and
  the long-path items in the open list. The test is renamed accordingly and `coverage.json` cites the new id; four
  README mutations and a no-change control prove the new assertions.
- **Release mechanics.** Integration is a fast-forward of `master` (`master` was an ancestor; no rebase, squash, force
  or rewrite; `master` is not protected). The archive is built by the unchanged packager from the exact commit the tag
  names. The tag is never moved; facts known only after publication (archive SHA-256, release URL) go into a later
  commit that changes only `Handoff.md`, which is not packaged, so the tagged source and the archive stay identical.

Signed: the owner (release decision, 2026-11-14); recorded by Claude Code.

## 2026-11-14 — v0.8.0 Phase 5 gate failure remediation (F1-F5): five stale verification pins are brought up to v0.8.0 with no program change; the long-path probe is the one approved pip call site outside the policy modules, pinned whole; the OmniVoice real-clone opt-in skip has its own exact rule; a dead coverage id is replaced by every collected parameter (owner instruction; implementation decisions by Claude Code)

**Owner instruction (2026-11-14).** Fix exactly F1-F5 of the failed canonical full gate
`2026-11-14_113416_full_c8e8` on `c583d78` with the smallest focused checks; no full gate, no rerun of passing tests,
journeys or stages, no model loading, no production change unless a defect is established; record the failure as a
failure and stop before any new full gate.

- **F1: the journey keeps its own expectation of the choices and takes the path limits from production.** The five
  choices and their defaults are what the window must show (owner-approved), so they stay written in the journey;
  reading `bootstrap.OPTIONAL_CHOICES` would make the check agree with any change. The path limits are the refusal's
  own arithmetic, not a promise to check independently, so the journey now takes them from the disposable copy's
  `bootstrap.app_path_limits()` through the setup launcher's record (the copy under test, not this checkout), and
  counts the folder's UTF-16 length itself to cross-check `long_paths.windows_length`.
- **F2: one approved call site, held by function and pinned whole; production unchanged.** Allowing the module would
  let a second pip literal in `long_paths.py` through, so the guard names `shared/long_paths.py::_pip_command` and the
  new test pins the builder, its one caller and the exact command. Measured, not assumed: pip 26.2.2's `--isolated`
  still reads `PIP_CONFIG_FILE` and the site and global configuration files. That is the posture the spaCy and Qwen3
  pip users already have and pin; under a hostile configuration the probe reached no index or find-links location.
  Changing the probe's environment would be a production change beyond the authorized scope with no established
  defect, so it is recorded here, not made.
- **F3: the route inventory is held by name as well as by count.** The structural guard names the four local routes
  and requires the set of functions that publish through `_convert_with_local_engine` to be exactly those, so adding
  or losing a route fails with "decide what it does on Cancel", as the count alone did before. Production unchanged.
- **F4: an exact reason, a budget of 1, and a written justification.** The gate's skip schema matches reasons only, so
  the rule cannot name the test id; its anchored pattern equals the one reason only `test_real_clone_proof` gives today
  (`git grep`), and a second skip with it exceeds the budget. A routine skip is never qualification evidence: the rule's
  `why` says so, and coverage keeps OmniVoice's owner and qualification items release-pending.
- **F5: every collected parameter, not one representative.** A bare name meant the whole test, so each is replaced by
  all of that test's collected parameter ids (83 for 17). coverage.json elsewhere cites some parametrized tests in
  full and some by a subset; none of these 17 had chosen a subset, so none is narrowed now.

Signed: Claude Code (implementation decisions), on the owner's instruction of 2026-11-14.

## 2026-11-14 — v0.8.0 independent review remediation (R1-R3): a conversion's startup imports are classified where they fail; every Windows path length is counted in UTF-16 units; the long-path tests never write outside their own scratch (owner instruction; implementation decisions by Claude Code)

**Owner instruction (2026-11-14).** Fix exactly R1, R2 and R3 of the independent Codex review of `feca89f`
(`files/dev-work/act080-independent-feca89f-20261114/Independent-Review.md`, kept unchanged), each with positive and
negative controls; no new phase, no redesign, no canonical full gate, no new Codex review, no change to HOME-PC's
long-path setting, no real elevation, no model download.

**R1: classify by where the failure happened, not by the exception's kind.** The conversion worker now wraps its
startup imports (NumPy, soundfile, PyTorch, OmniVoice) and reports what they raise through one function,
`omnivoice_worker.import_failure`, as stage `import`, as the installer's probe already did. A native library Windows
will not load arrives from PyTorch's loader as `OSError` (`ctypes.WinError`: 193 damaged image, 126 missing), which
`failure_needs_rebuild` never recognised at stage `worker`; at stage `import` it now reaches the existing rejection
(`reject_ready_engine`) and the ordinary Install & Continue repair. `failure_needs_rebuild` itself is unchanged.
- *Not every OSError there is damage.* Windows' own memory refusals while a library loads (`MemoryError`, or WinError 8,
  14 or 1455 "The paging file is too small", which PyTorch's CUDA libraries meet near the commit limit, a condition
  recorded on HOME-PC) are stage `memory`: never a rebuild, and the person is told to close programs and try again.
  Rebuilding a healthy 8 GB engine for a memory shortage would have been the opposite mistake.
- *Smart App Control* keeps stage `import` with Windows' words; the existing mark excludes it, and the "packages look
  damaged" hint is no longer added to its message.
- *The network guard* is re-raised from the imports (also when a library wraps it), so `main` still reports stage
  `network`.
- *The probe uses the same function.* Its import step already reported stage `import`; it now also tells memory and
  the network guard apart, so a proof that ran out of memory no longer condemns a freshly built engine. *Not chosen:*
  a second, probe-only rule (two answers to one question), or treating every `OSError` as damage (the review's warning).
- An `OSError` outside the imports (model load, generation) keeps its own stage and condemns nothing, as before.

**R2: one helper, `shared.long_paths.windows_length`, for every Windows path length.** Windows limits paths in UTF-16
units; Python's `len()` counts code points, so a character beyond the Basic Multilingual Plane (an emoji in a user or
folder name) counted once instead of twice. The helper is used by the app's folder check (`install_path_problem`),
OmniVoice's (`install_depth_problem`), the assessment behind the long-path offer and its page, the decision whether the
fresh-process proof is needed, the proof's depths, the probe's exact-length paths and the lengths it reports. The four
limits are unchanged (87/123, 83/119): no new measurement was made or needed, only the unit corrected.
`tts/output_names.py` already counted UTF-16 units and was left alone; the gate's journeys build ASCII-only paths.
Standard library only, pure arithmetic, importable everywhere. `omnivoice_runtime` imports it inside
`install_depth_problem`, not at the top: that module is on the pre-venv planning path, which a guard keeps free of
process and thread modules, and the pre-venv estimate never asks for a depth (the first focused run caught the
top-level import). *Not chosen:* a copy of the helper elsewhere (two definitions), or moving it to `venv_layout`
(`long_paths` must also run alone as the fresh-process probe script, which cannot import `shared`).

**R3: synthetic paths are strings; real files only in the test's own scratch.** `test_long_paths.py` arms the suite's
`write_tripwire` for the whole module over every synthetic root it can build (`synthetic_folder`, `C:\aaa...`, with and
without U+1F4DA), so a write there is refused before it happens and fails the test. The probe stand-in touches no
filesystem for a synthetic root and, inside the test's `tmp_path`, first checks that its folder is there. A negative
control points the old stand-in at the old synthetic roots and at one no run can have made: refused, nothing created.
*Not chosen:* broader permissions, links, or a "guard off" mutant (it would really write at the drive root).
The two folders an earlier unrestricted run left at the drive root on HOME-PC (2026-11-13 21:21:59, empty
`files\runtime-data` inside) are reported to the owner and left untouched.

**Test-execution blockers in the review were its context, not the code.** Run from the repository on HOME-PC with the
suite's usual scratch, the review's 14 Tcl/Tk errors do not occur (the app environment's Tcl initialises; the review's
sandbox could not read it), the depth-policy failures do not occur (the review's archived checkout was deliberately
deep), and the two real pip probes pass (WinError 206 came from that depth). Nothing was weakened to get there.

## 2026-11-14 — v0.8.0 unified `.venv` recovery acceptance closeout: scenario 9 is completed in the retained copy on the final program code; the cold select-all run is carried forward, not repeated; the real Windows long-path switch-on is an external qualification item; README gives enforced limits apart from what was really installed (owner instructions; implementation decisions by Claude Code)

**Owner instruction (2026-11-14).** Complete only the gaps the 2026-11-13 acceptance left: the rebuild of both engines
after scenario 9, an honest mapping of the cold run to the final tree, the long-path limitation recorded, the README
corrected. No Phase 5, no Codex, no full gate, no change to HOME-PC's long-path setting, no new large installation,
nothing done under unsafe memory pressure.

**Owner listening is approved (the owner's statement).** All 12 OmniVoice listening tracks (A Natural and B
Normalization for each of the six voices) are approved. It is recorded on the owner's word of 2026-11-14; README,
Briefing and Changelog no longer call it pending. No track, reference, transcript or setting was touched, and no
verdict was written into the listening pack by an agent.

**Scenario 9 is finished where it stopped, not started again.** The retained copy `c1` was used as it stood: the app
environment recovered on 2026-11-13, no engines, the models kept. Before anything ran, its 188 packaged files were
shown byte-identical to the archive built from `67d9d6e`, and no packaged path differs at `6c3e908`, so "the final
program code" is a checked statement, not an assumption. *Not chosen:* a fresh copy or a second cold install (the
owner's instruction, and 23.4 GB).

**Each engine by the installer's own route, one after the other.** `optional_setup_client.plan`, the disclosure,
`consent_for` and `install` in the contained worker: what the setup panel calls, driven by the acceptance harness.
Commit headroom was read before each model-loading step (floor 8 GB; 11 GB for the last two narrations).
- *Qwen3 was downloaded.* No verified wheel store for it exists on this computer (the installer removes its download
  cache after a success), so its 89 hash-locked packages were fetched from the pinned sources: 3,074,017,943 bytes, each
  checked by size and SHA-256. Both models (9.06 GB) were reused.
- *OmniVoice was not.* HOME-PC still holds the 88 verified wheels of the Phase 1 qualification (3,663,315,198 bytes).
  They were copied, never linked, with the source only read, into the copy's installer cache; each was checked against
  the copy's own manifest before it was copied, and the installer checked each again. The install then ran with the
  network closed: 0 bytes downloaded. It is the same disclosed manual step as the HOME-PC migration. *Not chosen:*
  downloading them again (3.66 GB for no new proof: that download ran for real on `191bd87` in scenario 7, and its
  code is unchanged since).

**What was verified, and how.** Read-only, each environment asked through its own interpreter. Three different
`python.exe` (three file identities), each with its own prefix, each built from the copy's app-local Python 3.12.15,
no entry of another environment on any `sys.path`, no system site packages. Every pinned package present at its
pinned version: the app's 170 locked packages and the separately pinned English model, Qwen3's 89, OmniVoice's 88,
with only `pip` beyond them. OmniVoice's `engine-receipt.json` (version 2, written by this install) names the nested
path, the base Python, the pinned package identity and the pinned model identity, and records an isolated proof with
no network attempt; Qwen3's record in `state.json` names the nested path, stage `installed` and the pinned
requirements identity. Every file of the OmniVoice model and of both Qwen3 models equals its pinned SHA-256. The
planner reports all five components ready with nothing to download. The real launcher, started offline, opened the
app in 3.6 s with no setup step, and both engines were byte-identical before and after it.

**The app environment and unrelated files.** The app environment's listing (53,439 files) is identical before the
rebuilds, after them and after the relaunch. The models, the package store, the app-local Python, the earlier
set-aside folder and the references are unchanged throughout. What changed is what the installs and the narrations
write: the two engines, their two receipts, the seeded wheels (removed by the installer once the engine was proved),
the settings file, Chatterbox's reference manifest, the copy's own logs, setup records and caches under
`files\runtime-data`, and 40 numba cache files (below).

**Bounded smoke.** Five two-sentence narrations, offline, one voice at a time: Qwen3 - Aiden, Qwen3 - Female 1,
OmniVoice - Female 1, Kokoro - Heart, Chatterbox - Female 1. The three Qwen3 and OmniVoice MP3s are byte-identical
to the same voices' files from the cold install, which is the strongest statement available that the rebuilt engines
are the same engines. Kokoro and Chatterbox do not repeat byte for byte between runs (three Kokoro runs, three
hashes), so they are judged by success, duration and level only. No long GPU run was made.

**The cold select-all run is carried forward by named evidence, never restated as new.** It ran once, on `8e4caa5`
(`c1-cold-select-all`, 2026-11-13 19:25 to 20:07: 21.7 GB disclosed, 23.4 GB received). Between `8e4caa5` and
`6c3e908`, `scripts/` changed in ten files (lock wording, the damaged-engine record, the interpreter-less
environment, the path limits and long-path offer, Qwen3's probe line); no source list, manifest, hash or download
routine changed, and the launcher and `config.toml` did not change.

| Claim of the cold run on `8e4caa5` | On the final program code |
|---|---|
| The first-run window with all five components chosen, from start to end | **Not repeated.** The window was driven for the base setup only (scenario 9, 2026-11-13), where the new long-path proof ran for real; the two engines were installed through the client the window calls, not by pressing its buttons. |
| Real downloads from the pinned sources | **In part.** Qwen3's engine wheels: downloaded today (3.07 GB) and on `06d52f7` (scenario 8). OmniVoice's wheels: last downloaded on `191bd87` (scenario 7), today taken from the verified store. Kokoro, the English model, Chatterbox, both Qwen3 models, the OmniVoice model, the app's Python, packages, FFmpeg and NLTK data: downloaded on `8e4caa5` only (one package file again in scenario 6); carried by unchanged code, and every model file was hashed again today. |
| All five components installed and ready | **Verified today** (planner, receipts, pins, model hashes). |
| Every engine family narrates | **Verified.** Qwen3 (both models), OmniVoice, Kokoro and Chatterbox today; Edge on 2026-11-13 on the same program files. |
| The app starts from the launcher with nothing more to install | **Verified today**, offline. |
| Disclosed sizes equal what is fetched; the 42 minutes | Qwen3's engine only (3.1 GB disclosed, 3,074,017,943 bytes fetched); the rest by the focused tests. The time was not measured again. |

**Windows long paths: an external qualification item.** HOME-PC's `LongPathsEnabled` was read (1) and not written, and
the elevated helper was not run: the owner's rule, and unchanged from 2026-11-13. What exists is every refusal path
with an injected runner and the page, the proof and setup's restart run for real with only the registry value
simulated; those records are untouched. What does not exist, and cannot be made on this computer: the consent prompt
approved for real, declined for real, a standard account, a computer managed by policy, the "restart Windows" answer,
and an installation run with long paths off (at any length, and at the limits of 87 and 83). It is recorded as a
qualification item for a person on a Windows computer where the setting is off, before any release.

**README (and the test that holds it).** The path-length section said "tested limits". The limits are measured (the
deepest files of two real installations) and enforced by setup, and the rule is tested at each exact limit; what was
installed for real is narrower: one Windows 11 computer with long paths on, folders of 89 and 102 characters. README
now says both, says that the switch-on has not been tried on a computer where the setting is off, and no longer calls
the owner's listening pending. `test_long_paths.py` pins the new sentences and refuses "tested limits"; five mutations
of the README are each caught, with a passing control.

**Memory, measured.** At rest 25 to 26.5 GB of 36.6 GB were committed. Commit was read before and after each
install, not sampled during it. During the narrations it was sampled twice a second: each Qwen3 narration held it at
34.2 to 35.0 GB for 15 to 20 seconds with a peak of 36.0 GB, 10.6 GB above rest and more than the 6 to 7 GB allowed
for. Windows enlarged its own page file meanwhile (the commit limit read 40.7 GB instead of 36.6; nothing was
configured), so headroom read 4.7 GB or more; against the usual limit the same commit would have left 0.5 to 2.4 GB,
the level at which a background command was stopped on 2026-11-13. OmniVoice peaked at 32.1 GB and Chatterbox at
32.5 GB. Nothing was stopped. *Consequence for Session 5:* a Qwen3 narration on this computer needs about 11 GB of
commit headroom, not 8.

**Found, not changed.** (1) Chatterbox's first narration in a fresh app environment lets numba write its cache (40
files, 2.2 MB) into `.venv\Lib\site-packages\librosa\util\__pycache__`; HOME-PC's own `.venv` has held the same files
since October, and no package file changes. Qwen3 and OmniVoice direct numba's cache into `files\runtime-data`. A
candidate for the same treatment later; outside this closeout. (2) The first run of the session's verifier reported
one failure of its own making (it did not know the app's separately pinned English model); the record is kept and the
corrected runs follow it.

## 2026-11-13 — v0.8.0 unified `.venv` layout: OmniVoice lives at `.venv/engines/omnivoice`; an earlier `.venv-omnivoice` is never used and is set aside only after the nested engine is proved; verified path limits and an optional, consent-based Windows long-path change (owner decisions; implementation decisions by Claude Code)

**Owner decision.** The root-level `.venv-omnivoice` layout of Phases 1-4 is superseded. The app has ONE top-level
`.venv` holding three independent Python environments: the app's own (`.venv/`), Qwen3 (`.venv/engines/qwen3/`) and
OmniVoice (`.venv/engines/omnivoice/`). Each engine keeps its own interpreter, pinned packages, receipt, model identity
and lifecycle locks; no package set is combined. The portable base Python, model weights, wheel stores, FFmpeg, receipts
and settings stay where they were. This replaces plan section 4's sibling choice and the "Environment" paragraph of the
Phase 1 entry below; both are kept as history.

**One runtime path (implementation).** `omnivoice_runtime.venv_dir()` is always the nested path. *Not chosen:* keeping a
healthy sibling in use until it is migrated (what P04C did for `.venv-qwen3`). The only way back into the optional setup
after first run is Install & Continue, which is offered only for a voice that is unavailable, so a sibling that kept
working would never be migrated; and the owner's instruction is that no runtime path depends on the old folder. The
consequence, stated plainly: on a copy that has only the sibling, the OmniVoice voices are unavailable from the first
start of this version until Install & Continue is pressed once. Until the new engine is proved, nothing of the sibling
is changed. Only HOME-PC and disposable test copies ever had one (v0.8.0 is unreleased).

**A rebuild, never a move.** A Windows environment is not relocatable, so the nested engine is created at its final
path from the app's base Python (`-I -m venv`, never the parent's interpreter) and the same 88 hash-locked wheels,
offline, then proved (versions, isolation, imports, CUDA kernel, offline model load). The model is reused where it is.
The old receipt is never copied: the nested engine's receipt is another file and version (`engine-receipt.json`,
version 2, bound to the nested path, the base Python's identity and the package lock); `install-receipt.json`
(version 1) is never rewritten and never vouches. Wheels are reused only from the installer's own cache, where each is
checked against the lock again.

**Retirement.** After the proof is recorded, still under the install lock, the sibling is renamed whole into
`files/runtime-data/omnivoice/set-aside/legacy-venv-omnivoice-<UTC>-<id>/`, its version-1 receipt is moved beside it,
and `retired.json` and `RETIRED-READ-ME.txt` say what it is, that it is not runnable there, and how to delete or restore
it. Never deleted, never copied; a link, a stray file or a folder that cannot be moved is left exactly where it is and
the install still stands. Nothing moves a leftover sibling while the engine stays ready (no install runs), so the note
shown for it promises only that. *Not chosen:* a retired name at the app's root (shorter paths, but a second `.venv-*`
folder beside `.venv`, against the decision); deleting it; adopting it.

**Depth.** The nested engine's deepest native library is 135 characters below the app folder (the sibling's was 127)
and Windows' loader refuses anything past 259 even with long paths enabled. `omnivoice_runtime.install_depth_problem`
therefore refuses this one component, before any download, where the app folder is longer than 119 characters (83
where long paths are off). `bootstrap`'s own rule was then measured too and its long-path limit corrected (below).

**The app-environment repair.** The transaction already carried the whole `engines/` folder in one rename and never
deleted a folder holding an engine; no deletion path changed. `shared/engine_lease.EnvironmentLease` now takes Qwen3's
three locks and then OmniVoice's two (its installs already take the shared `setup.lock` first), all or none, for the
repair, first-run recovery, the cleanup helper and the data-clearing coordinator. `setup.lock` is held by every
optional install, so its sentence names no engine. Locks that cannot even be checked are a refusal.
`omnivoice_setup.parent_problem` refuses to build into an app environment that is missing, linked or half repaired.

**A damaged engine is recorded (found during acceptance, fixed).** On a real test copy, with one file deleted inside a
package, the listing and the receipt still said "ready", every conversion failed and nothing offered a repair. A
conversion whose worker cannot import the engine's packages now records that in the receipt
(`reject_ready_engine`), as the installer does when a re-proof fails that way; the engine is then "broken", the voices
say why, and Install & Continue offers the ordinary repair (the damaged environment is set aside whole and a fresh one
is built and proved). GPU, memory, generation, isolation and Smart App Control failures record nothing. *Not chosen:*
checking every package file on each readiness question (the planner must write nothing and stay cheap).

**An app environment that lost its interpreter is replaced (found during acceptance, fixed in `191bd87`).** On a real
test copy with `.venv\Scripts\python.exe` deleted, the launcher took the first-run route and setup *kept* the folder
("absent"), had nothing to run and failed on every start, with both engines inside the folder a person would then
delete. The behaviour is in the released v0.7.3 too. `_create_validated_venv` now treats a folder that is present
without an interpreter like a repairable one: set aside, rebuilt, engines carried home, put back whole if the rebuild
fails. Both callers already hold the two-engine lease.

**Qwen3's Check and repair sees a package that lost its own files (found during acceptance, fixed in `06d52f7`).** On
the same test copy, with `qwen_tts\__init__.py` deleted, every Qwen3 conversion failed and pointed at "Check and
repair", which answered "Everything checks out": its probe ran `import qwen_tts`, and a package folder without its
`__init__` still imports as an empty namespace. The probe now imports the name a conversion imports. This is the one
change to Qwen3's code in this work, one line, and the behaviour is in the released v0.7.3 too. *Not done:* recording a
damaged Qwen3 engine at the moment a conversion fails, as OmniVoice now does; Qwen3 keeps its own dialog for that, and
its message already names it.

**Path limits, verified by measurement (owner requirement: use verified values).** Measured on HOME-PC and on a cold
install made by the first-run window (identical): below the app's folder, the deepest native library is 120 characters
in `.venv`, 132 in `.venv/engines/qwen3` and 136 in `.venv/engines/omnivoice`; the deepest file is 155, 165 and 169;
the base Python, the models and FFmpeg are shallower. `bootstrap.DEEPEST_NATIVE_LIBRARY_CHARS` was 128, right while
Qwen3 was a sibling folder and not raised when the engine moved inside `.venv` (v0.7.0 P04C): a folder of 128 to 131
characters with long paths on was accepted although Qwen3's deepest library could not have loaded there. It is now
136 (132 + the usual margin), so the app's limit with long paths on is **123** (was 131). The other three limits were
already safe and are unchanged: **87** for the app with long paths off, **83 / 119** for OmniVoice. *Consequence:* a
copy in a folder of 124 to 131 characters with long paths on still starts, but its next repair or setup is refused
with the "move it" instruction. No such copy is known. *Not chosen:* a separate Qwen3-only rule (Qwen3 has no depth
check of its own; the app-wide rule is documented as covering every environment in `.venv`).

**Optional Windows long paths (owner requirement).** `shared/long_paths.py`, standard library only.
*Offer.* Only where the setting reads off and switching it on would be enough: the first-run window then shows a
path-length page instead of the welcome page (move the app, recommended; or switch long paths on). Where only OmniVoice
is too deep (84 to 87) the page appears when OmniVoice is chosen, with "Continue without OmniVoice". A folder too long
even with long paths is never offered the change. A setting that cannot be read is never changed (it could not be read
back).
*The elevated helper is Windows' own `reg.exe`.* It is found through `GetSystemDirectoryW` (never PATH or an
environment variable) and started through the ordinary consent prompt (`ShellExecuteExW`, verb `runas`) with one
constant command line that sets `LongPathsEnabled` to 1. *Not chosen:* an elevated Python or PowerShell helper of the
app's own. The app's folder is writable by the person's account, so any script in it that is run elevated is a way for
an ordinary process to gain administrator rights; with `reg.exe` nothing of the app, and nothing that can be edited,
runs elevated, and nothing can be passed into the command. The prompt therefore names "Registry Console Tool", which
the page says in advance. Setup itself is never elevated.
*A value of 1 is not proof.* After the change, and before every first-run setup or repair in a folder that needs long
paths, a fresh process of the app's base Python must report long paths, write and read a file, install a generated
package with pip and load a native library at the installation's real depth. Windows applies the setting per process,
so after a successful change setup starts again in a new process, which then passes the unchanged depth rule; a value
that reads on while new processes do not have it is answered "restart Windows", and nothing is installed.
*Limits of the evidence.* The elevated write itself was never run: HOME-PC has long paths on, its setting must not be
changed by tests, and approving a consent prompt is a person's act. Every refusal path (declined, no administrator,
blocked by policy, registry failure, value put back) is proved with an injected runner; the probe, the read-only
detection, the page and the setup continuation were run for real in disposable copies.

**Independent review (a read-only agent, on `8e4caa5`).** No critical finding; fixed in `b18720c`: a linked set-aside
folder no longer turns a finished install into a reported failure; the leftover note; `InstallLock` gives back what it
took when a later lock file cannot be opened; the neutral `setup.lock` wording; uncheckable locks; the base interpreter
compared by file identity where its spelling differs (mapped or substituted drive).

**Not changed.** Dependency versions, generation settings, voice registrations, normalization, reference recordings,
transcripts, model weights, the 12 approved listening tracks, Qwen3's code apart from the one probe line above, and
the release packaging rules (the archive
still carries no environment and exactly the 18 reference WAVs).

**For the owner.** (1) The set-aside folder on HOME-PC (8.3 GB) and the disposable acceptance copies are kept; removing
them is the owner's decision. (2) The kept tree has paths longer than 260 characters; its note says how to delete it if
Explorer refuses. (3) Qwen3's installer still compares the base interpreter by spelling only (unchanged code); a copy on
a mapped drive may refuse to build it. (4) A sibling that could not be moved is not retried until OmniVoice is
installed or repaired again. (5) The app's limit with long paths on is now 123, not 131 (above). (6) The long-path
change has not been made once for real: before release it should be tried by a person on a computer where long paths
are off (approve the prompt, see setup restart and continue; decline it; try a standard account). (7) HOME-PC's folder
is 102 characters and the acceptance copies 89: both depend on long paths being on, as they are on HOME-PC.
(8) After scenario 9 (the whole `.venv` removed) the app was recovered for real, but rebuilding the two engines in that
state was not run: the computer was critically low on memory and no further model-loading work was started. (9) The
refusal shown when a repair meets a busy engine ends with a sentence about package files that does not apply there;
wording only, left for the owner.

## 2026-11-13 — v0.8.0 Phase 4: the runtime roster is 34 while the preview collection stays the historical 28; the listening pack is made through the production path with the owner's verdicts left pending; identity 0.8.0; no peak correction without an audible defect (implementation decisions by Claude Code)

**Roster versus previews.** Tests that pin the *runtime* registry now assert 34 voices in five engine families (the first
28 rows still pinned verbatim, the six OmniVoice rows appended in their own group). The preview gallery is a separate,
fixed historical collection: `files/dev-tools/voice_previews.py` now names its roster explicitly as the voices of the four
engines the owner's 2026-10-20 decision covered (`PREVIEW_BACKENDS`), so it stays exactly 28 and an OmniVoice voice is
neither listed, pending nor blocked there. No preview was generated or changed; six new tracked previews need the
owner's separate authorization. Test names that stated "28" for the runtime roster were renamed to "34" (the one cited by
the coverage inventory was carried into `coverage.json`); names about the 28 previews were kept.

**Version identity.** `scripts/shared/version.py` and `config.toml` say 0.8.0 (release-candidate identity, not
publication). Only tests that pin the current version moved (nine pinned 0.7.2, behind the released 0.7.3); historical
fixtures (`test_verification_coverage`'s `"release": "0.7.2"` exception records) are data and were left alone.

**M4B (v0.7.3).** `m4b_nero.py` is the Converter's own module (read only by `m4b_probe` and `m4b_execution`): it is in the
M4B README's module map and the structural authority's Converter set, and the inventory gains
`ACT.CONVERTER.NERO-RECOVERY` after reviewing `a2cc65d`'s diff; no M4B production code changed.

**The numba test.** `test_numba_compiles_and_writes_only_the_contained_cache` asserts nothing was written beside the
probe source; without `-B` CPython itself writes `__pycache__` there. The canonical invocation (`-I -B`, the gate and
`guarded_pytest`) passes. Recorded, not changed: the contract assumes `-B` on purpose.

**The listening pack.** Track A is `quality_corpus.DIFFICULT_SHORT` verbatim (the plan's preferred passage; it carries
real proper names but no fantasy names, and no owner-approved variant exists). Track B is one indexed text of eleven
spoken parts built only from `test_speech_g1.SNIPPETS` and golden-corpus inputs, verbatim, plus two lines with no golden
case (initials; a names line using the fantasy names from the owner's own reference transcripts, spelled as the owner
spells them), each proved unchanged by `v1`. Before any audio, a check proves every item's prepared text appears in order
in the prepared composite, every corpus line reads exactly as its golden case expects, and every snippet token reads as
the corpus case for the same token; the expected readings shown to the owner come only from those cases, and
kept-as-written tokens are labelled model-native. Part seven was split in two because the shared sentence planner takes
"Apt." for a sentence end and would otherwise have put a chunk boundary inside "Apt. 4B". Every sample goes through
`generate_voice_samples`' new OmniVoice route, which is `omnivoice_file_to_mp3` with the voice's preset, the panel's
default 192k and an explicit `v1` snapshot built as the panel builds it; the harness only observes (wrapped worker
runner, chunk reader and encoder). Generation settings were not changed. Every owner verdict starts NOT YET REVIEWED.

**Peaks.** The model's own output reached exactly 1.0 in 4 + 4 samples of Male 1 and 1 of Male 3 (A); libsndfile clamps
them in the 16-bit WAV (checked: no wrap-around); decoded MP3s have no sample at full scale and true peaks of -0.2 dBTP
or lower. A handful of clamped samples is not a demonstrated audible defect, so no OmniVoice gain change and no global
loudness change was made; the owner is pointed at the exact times.

**Tokenizer attribution.** The Boson licence's section 1.b.i asks a product that uses the Higgs Materials to display its
attribution on a website, user interface or product documentation; the install UI already does (Phase 3) and the README
now quotes it as the pinned licence words it. Section 1.b.iii's Notice file applies to distributed copies; ACT never
distributes the tokenizer (each person's own consented download, licence file included), so the release archive needs
none. The in-app string writes "All Rights Reserved" where the licence's second occurrence says "All Right Reserved";
left for the owner. Not legal advice.

**Inventory.** 29 application sources restamped after reviewing each diff since its stamp against its features; new
features `ACT.TTS.ENGINE.OMNIVOICE` (owner check `listen-omnivoice`), `ACT.TTS.SETUP.OMNIVOICE` (qualification
`fresh-windows`: real fresh installs and repairs were exercised with mocks only) and `ACT.CONVERTER.NERO-RECOVERY` (owner
check `nero-full-book`); release kinds stay pending, so nothing claims release readiness.

## 2026-11-13 — v0.8.0 Phase 3: OmniVoice is the fifth component of the existing optional installer; an environment is used only with the installer's receipt, and an existing one is adopted after a proof, never rebuilt (implementation decisions by Claude Code)

**What the person sees.** The first-run window and Install & Continue offer five components in the existing order;
OmniVoice — Six Cloned Voices is appended last and unchecked (`WIZARD_DEFAULTS`); the other four keep their order,
labels and defaults. No new window, button, launcher or protocol: the v2 request/consent/worker/lifecycle/acquirer path
carries it, and `voice_install.installable` now offers it through the existing Install & Continue (it was already mapped
in Phase 2, gated on `COMPONENTS`). The review screen shows the licence and hardware terms before Install, and a
"View licence terms" button opens a read-only window with a button per licence text at its pinned revision; reading
them is never a consent.

**Licences, as the pinned files say them (one correction to Phase 1's record).** Code Apache-2.0; weights CC-BY-NC,
non-commercial, no version stated anywhere; the audio tokenizer under the Boson Higgs Audio 2 Community License (Llama 3
based). Its section 2 threshold is **100,000 annual active users in the preceding calendar year** -- not "monthly" as the
Phase 1 entry below and the Session 3 brief said; the shipped manifest's licence text and the disclosure use the
licence's own words. The disclosure also carries its 1.b.i attribution sentence, its Notice-file and Acceptable Use
Policy terms, the no-improving-other-LLMs term, and the model card's prohibition of unauthorised cloning. No term found
blocks the optional download: ACT never redistributes the weights or tokenizer (the person's own consented download
from the pinned Hub revision), and the attribution is displayed in the install UI. For the owner (not legal advice):
whether the attribution should also appear in the README/about text is a Phase 4 documentation decision.

**Sources (production, not developer files).** `scripts/tts/omnivoice_manifest.json` now pins the 88 wheels by URL, size
and SHA-256 (promoted unchanged from Phase 1's verified lock; a test proves equality with the dev manifest) and the
model's pinned-revision URL form; it ships in the release ZIP like every tracked `scripts/` file, and nothing reads
`files/dev-tools/` or the Phase 1 wheel folder. Unit sources: `omnivoice-engine` = the wheel pins by hash,
`omnivoice-model` = repository@commit plus the model manifest hash (the licence files are in it, so a changed licence
file is a different source and needs a fresh consent). pip installs only the verified local wheels, offline, behind an
audit hook that refuses network and process starts inside pip.

**Readiness = the installer's receipt (Qwen3's pattern).** `files/runtime-data/omnivoice/install-receipt.json`, beside the
environment, is written only after the installer's proof passed: the worker's new `probe` job checks the pinned
versions, isolation from `.venv`/Qwen3/user site, the imports, a CUDA kernel and an offline model load (no audio). The
receipt binds the folder, the base Python's identity and the pinned-set hash. `environment_status` now requires it, so a
complete-looking environment that was never proved -- including one interrupted after pip -- is never ready. Plans never
probe OmniVoice; its GPU presence is a caller fact the worker supplies (`Facts.gpu`, nvidia-smi only when OmniVoice is
chosen).

**Adoption.** An environment holding exactly the pinned set, isolated, at its own path and built from the app's own base
Python, with no valid receipt, is *unchecked*: planned as an install that downloads and writes nothing ("check and
adopt"), which runs only the proof and then writes the receipt (`origin: adopted`). Nothing in it is replaced, nothing is
downloaded again. A proof that fails at the versions/isolation/import stage records `rejected`, so the next plan offers a
repair under its own consent instead of the same check; a GPU, memory, timeout, busy-guard or Smart App Control failure
rejects nothing (Smart App Control's first-load refusal is retried up to 8 times, as for the other engines).

**Repair never deletes what the app did not make.** A broken environment (wrong packages, not isolated, another
Python, rejected) is moved whole to `files/runtime-data/omnivoice/set-aside/` and a fresh one built; only an environment
the app's own receipt says it was still creating is removed. A damaged pinned model file is replaced only under repair
consent and only by its verified download. Missing or changed OmniVoice recordings make the component a bad bundle:
nothing is downloaded or repaired for it (installing cannot restore a recording), and Install & Continue is not offered
for that voice.

**Figures.** Fresh install: 6,930,782,369 B download (manifest: 88 wheels 3,663,315,198 + 11 model files 3,267,467,171;
Phase 1's 6,930,785,458 included the snapshot's two `.gitattributes`, which are not part of the engine), disk about
11.6 GB (environment 8,346,271,361 B approximate, measured on HOME-PC, plus the model), temporary 3.66 GB of wheels plus a
2 GB margin (removed after a proved install). An adoption, a ready install and a record-only model are 0 B download, 0 B
disk and no margin. Partial states count exactly what is present (by record, or by hashing where no record vouches).

**The v3 seam.** The non-production v3 authority still refuses OmniVoice (no reviewed v3 terms; a test pins it). Its
reviewed source closure (`optional_setup_planning_bridge_v3.SOURCES`) gains only the planner's new read-only
dependencies (`omnivoice_runtime.py`, `clone_references.py`, the manifest and the reference list), as v0.7.0 did for
`qwen3_wheels.py`; the planner reads the wheel cache through `omnivoice_runtime`, never the installer module. Its two
tests that iterated `proto.COMPONENTS` now iterate the four components it covers.

**Locks.** An OmniVoice install holds `setup.lock` (every install/repair of this copy and the app's own repair), then
OmniVoice's `inference.lock` (held by every OmniVoice conversion), and requires its `engine.lock` free; the proof takes
OmniVoice's machine-wide model guard. Those OmniVoice locks also make the component busy in a plan.

## 2026-11-13 — v0.8.0 Phase 2 correction: every cloned engine has its own six reference recordings; OmniVoice conditions directly on the owner's curated WAVs (owner decision; implementation decisions by Claude Code)

**Owner decision (2026-11-13, a bounded Phase 2 correction; no new phase, the five-phase roadmap and the single Session 5
gate are unchanged).** It supersedes the derived-excerpt design in the entry below. The clone references are
engine-specific: `files/Cloned-Voice-Uploads/<Engine>/<Engine> - <Voice>.wav` for Chatterbox, OmniVoice and Qwen3, six
each, exactly 18 tracked, none shared between engines and nothing loose at the folder root.

- **Qwen3** keeps the six original v0.7.x production recordings byte for byte: `git mv` from
  `Chatterbox - <Voice>.wav` to `Qwen3/Qwen3 - <Voice>.wav` (pure renames, SHA-256s unchanged: `b740b9ed…`, `428d3869…`,
  `45fbfba0…`, `592139a2…`, `4ab6bd67…`, `47eff938…`). `scripts/tts/data/bundled_clone_transcripts.json` is unchanged
  byte for byte (`dd953523…`); only the path lookup changed. Neither the Qwen3 folder of the owner's ZIP (empty) nor the
  Qwen3 part of the owner's transcript document is used.
- **Chatterbox** uses the owner's six new recordings (44.1 kHz mono 16-bit, 7.5-10.9 s; the engine still decodes its own
  leading 24 kHz window and needs more than 5 s). Chatterbox Turbo takes no reference text, so the owner-written
  transcripts are checked metadata and never reach the model.
- **OmniVoice** is conditioned directly on the owner's six curated recordings (44.1 kHz, used whole: no second crop),
  with the owner-written transcripts as reference text. Ten seconds stays the maximum. **One explicit exception:**
  `OmniVoice - Male 1.wav`, 451,022 frames at 44,100 Hz (10.227 s), SHA-256 `77533853…`, kept whole so "things." and its
  natural quiet tail are not cut. It is bound to that hash, frame count and rate (`omnivoice_runtime.DURATION_EXCEPTIONS`)
  and widens nothing else.
- The transcripts are the owner's own words ("Cloned-Voice-Transcripts-Personally-written-and-owner-approved.md"): no
  speech recognizer, no rewriting, and no rule that an OmniVoice text be a prefix of a Qwen3 text.

**Implementation decisions (Claude Code).**

- One declarative authority, `scripts/tts/data/clone_references.json` (loaded by `tts/clone_references.py`): all 18
  entries with file, SHA-256, PCM format and exact frame count, plus text and text SHA-256 for Chatterbox and OmniVoice
  (Qwen3's text is `null`: its bundle stays the authority, nothing is duplicated). It is checked whole against the
  registry, which now names each engine's folder and file explicitly (`voice_registry.REFERENCE_FOLDERS`,
  `REFERENCE_RECORDINGS[(backend, reference id)]`, `reference_recording_parts`). Each engine still pins its own WAV hashes
  in code (Qwen3 unchanged, Chatterbox's six new ones, OmniVoice's six new ones plus its six transcript SHA-256s, so an
  edited transcript fails closed even when its checksum is recomputed).
- OmniVoice: `verify_reference` reads the recording once (hash, then format and frame count from the same bytes); the
  worker gets the shipped path and proves the same bytes again before `create_voice_clone_prompt((waveform, 44100),
  ref_text, preprocess_prompt=True)`. Upstream resamples to its 24 kHz in memory (torchaudio) and trims silences; the file
  is only read, never copied or cropped. The prompt-cache identity is schema 2 (`act-omnivoice-reference-v3`: WAV SHA-256,
  frames and rate, transcript SHA-256, model revision, engine version, prompt format, preprocessing flag, dtype), so no
  Phase 2 excerpt prompt can be reused and a changed WAV or transcript misses the cache. The silence-rule crop code,
  `data/omnivoice_excerpts.json` and the transcript-prefix rule are removed. The Phase 1 proof and its evidence stay as
  recorded history.
- `.gitignore` re-includes each engine folder, then ignores everything in it except its six WAVs (Git cannot re-include a
  file under an ignored folder). `release.py` ships exactly the 18, one copy each, from its closed allowlist.

**What the owner recordings were checked for (no speech recognizer).** All 12 new files cross-correlate at 0.98-0.9997
with the original 15-second recordings (the same performances), so each ending was placed on the original timeline
against the pauses measured in Phase 2: every file starts in quiet, has no clipped samples and ends after a complete word,
matching its transcript. For the owner's ears: (1) both Male 2 files end inside a soft breath after "Jaw." (about
-50 dBFS, some 28 dB above the room floor, cut off rather than decayed; the original 15-second file ends at the same
place); (2) the owner's transcripts spell "Joric Reclentos" where Qwen3's bundle has "Jorg"; (3) the two Female 2 files
open differently ("His direct superior ..." for Chatterbox, "Vice Chancellor ..." for OmniVoice), as their transcripts
say. Voice quality and these points remain for the owner's Session 4 listening.

## 2026-11-13 — v0.8.0 Phase 2: ten seconds is a maximum and every OmniVoice excerpt ends in a natural pause; the engine prepares text once and runs in bounded offline workers (owner decision; implementation decisions by Claude Code)

**Owner decision (2026-11-13, Session 2 kickoff), superseding the plan's exact-10-second crop.** Ten seconds is a
MAXIMUM. Each of the six OmniVoice references starts at 0.000 s and ends as close to 10.000 s as is safe, never later:
the final audible word is complete, the last sample lies inside a natural quiet interval after it, a short natural quiet
tail is kept where the recording permits, nothing is padded or faded, and if the nearest safe pause is earlier the
shorter excerpt is used; where no defensible end exists the ambiguity is reported, not guessed. The plan's §§3, 4, 5, 6
and 7 now say this (narrow wording changes only; Session 1's historical text is unchanged).

**The silence rule (`act-omnivoice-silence-v1`, `tts/omnivoice_runtime.py`).** Mean-square energy of 20 ms frames every
5 ms; an adaptive threshold per recording, `floor + max(6 dB, 20% of (speech - floor))`, with floor and speech the 5th
and 95th percentiles of its frame energies (never one low sample or a zero crossing). A quiet run counts as a natural
pause only from 150 ms: English stop and glottal closures are shorter, and the real recordings have 40-80 ms closures
inside and between words that an energy check alone would accept. The cut keeps at least 100 ms of the pause after the
last word and at least 50 ms before the next sound; the latest such cut within 10 s is chosen deterministically. Silence
cannot prove a word is complete, so each end word was also aligned with the approved transcript: syllable-nucleus counts
between pauses against the transcript's syllables, and spectrograms of every boundary (no speech recognizer). The six
transcripts are the approved full transcripts' exact opening words, cut at the pause; they are **provisional** until the
owner's Session 4 listening.

| Voice | End frame (24 kHz) | Duration | Last word | Natural pause |
|---|---|---|---|---|
| OmniVoice - Female 1 | 199,440 | 8.310 s | "me," | 7.850-8.360 s (510 ms) |
| OmniVoice - Female 2 | 176,160 | 7.340 s | "Reclentos," | 7.115-7.390 s (275 ms) |
| OmniVoice - Male 1 | 117,240 | 4.885 s | "Shinovar," | 4.295-4.935 s (640 ms) |
| OmniVoice - Male 2 | 198,360 | 8.265 s | "Whiskers," | 7.995-8.315 s (320 ms) |
| OmniVoice - Male 3 | 196,560 | 8.190 s | "day." | 7.280-8.240 s (960 ms) |
| OmniVoice - Male 4 | 218,280 | 9.095 s | "drowsing," | 8.850-9.145 s (295 ms) |

**Male 1: the Phase 1 proof crop is replaced.** Frame 230,760 (9.615 s, owner-accepted for the Session 1 proof) ends
where the voicing of "all" runs into the /th/ frication of "things": its 20 ms frames measure -38 to -40 dB against the
recording's -70.5 dB floor and -58.9 dB quiet threshold. Under the new rule that is a real defect. Between 4.935 s and
10 s the recording has no natural pause, only 45, 80 and 65 ms closures (the 65 ms one at 8.70 s is most likely the
glottal onset of "end" after "the", which would also have left the transcript's last word uncertain), so the rule gives
the 640 ms pause after "Shinovar,": 4.885 s, inside upstream's own 3-10 s recommendation. Likewise Female 2's 65 ms gap
after "subordinate," (8.53 s; stop closures) was not used. All six recordings are mid-speech at exactly 10.000 s. The
owner may still choose differently in Session 4; any change is a new authority entry, never an edit to a recording.

**Where it lives.** `scripts/tts/data/omnivoice_excerpts.json` holds, per voice, the recording's SHA-256 and format, the
crop, the pause, the excerpt's PCM and WAV SHA-256, the last word, the transcript and its SHA-256, a status
(`provisional`) and a note on the evidence; it is checked as a whole against the shipped full-transcript bundle and the
registered recording hashes. The excerpt is cut again from the verified recording in each run's job folder (ignored,
removed after the run), its PCM proved equal to the reviewed one; nothing is padded. `scripts/tts/omnivoice_manifest.json`
pins the 88-package set (upstream's `uv.lock` at 0.2.1) and 11 model files (the snapshot's two `.gitattributes` are not
part of the engine). Readiness is cheap: the environment's `*.dist-info` listing must equal the pinned set (pip aside),
and the model's sizes and modification times must match a record (`files/runtime-data/omnivoice/model-verified.json`,
beside the snapshot, never in it) that only a full SHA-256 verification (`verify_model_files`) writes. That verification
was run once on HOME-PC this session over the Phase 1 snapshot (no file changed); it is not a production install record,
and plan Phase 3 still decides whether the Phase 1 environment is adopted or rebuilt.

**Engine decisions.** One OmniVoice file worker at a time; each worker renders at most 48 chunks and exits (upstream issue
#199: no file accumulates GPU state in one process), reloading the model (about 1.7 s) and the clone prompt from cache.
Chunks are at most 300 characters: upstream re-splits anything it estimates above 30 s of speech, and the excerpts speak
about 12-14 characters a second. Generation is upstream's own 0.2.1 defaults (32 steps), fp16 on the GPU only: no CPU
path is offered or claimed, and a computer without an NVIDIA GPU is told so and not offered an install. The worker runs
`-I`, offline (Hub switches, an app-owned empty cache) behind an audit hook that refuses every non-loopback lookup and
connection, refuses OmniVoice's speech recognizer outright, and calls `generate(..., normalize_text=False)`. A reusable
clone prompt is filed under a SHA-256 of every input that shapes it (recording, excerpt PCM and crop, preprocessing and
silence-rule versions, excerpt transcript, model revision, engine version, prompt format, preprocessing flag, dtype) and is
loaded (`torch.load(weights_only=True)` upstream) only when its identity record matches and the file hashes to the bytes
this app's worker recorded. The run holds `files/runtime-data/omnivoice/inference.lock` and a machine-wide named mutex of
its own (`AudiobookCreationTool-OmniVoice-ModelGuard-v1`); it does not take Qwen3's, so two different copies of the app
could still run Qwen3 and OmniVoice at once (within one app a run has one engine). The upstream decoder's final `tanh` is
removed, so output is unbounded: in the six smokes no sample reached full scale (highest 0.99997, Male 3) and the decoded
MP3s peaked at -0.45 dBFS or below with no overs, so no gain processing was added; the run logs its peak and any samples
at full scale, and Phase 4's longer run must check them again.

**Speech preparation.** OmniVoice is a fifth engine in the existing system and nothing else: route and engine `omnivoice`
in `speech/profiles.py` (Qwen3's heading-as-paragraph structure, its own 300 ceiling, Qwen3's protected punctuation, no
phoneme markup), the glossary's engine allowlist, and a complete 16-class `modes.json` row, all `expand` as the plan's
provisional baseline (the table's comment says it is not a G1 verdict). No rule, number, unit, lexicon or historical
verdict changed; the 60 G1 verdicts are pinned by a canonical hash. `prepare()` runs once per file in the app before
chunking, with the run's frozen snapshot; `off` leaves only the structure stage.

**Install & Continue.** The six voices name the component `omnivoice`, but it is offered only once the optional-setup
protocol knows that component (plan Phase 3); until then an uninstalled voice shows the engine's sentence and Start is
refused before anything is reserved.

**Tests left for Phase 4 (plan §5 Session 4, "tests that explicitly assume four engines/28 total voices").** Registering
the six rows makes 35 existing assertions of the 28-voice, four-backend roster and the 28-preview gallery fail (files:
`test_chatterbox_boundaries`, `test_voice_labels`, `test_voice_previews`, `test_tts_smoke`, `test_fatal_diagnostics`,
`test_tts_importing`, `test_chatterbox_integration`, `test_chatterbox_candidates`, `test_chatterbox_evaluation`,
`test_epub_retirement`, `test_tts_jobs`). Each was inspected: every one is a closed-roster count, list or preview-manifest
pin, none a behaviour change. `generate_voice_samples` has no OmniVoice route yet (Phase 4 listening pack decides it).

## 2026-11-13 — v0.8.0 Phase 1: OmniVoice is qualified in a sibling environment pinned to upstream's own lock; the proof's reference is an owner-accepted shorter whole-word crop (owner rulings recorded by Claude Code)

**Environment.** `.venv-omnivoice` is a sibling of `.venv`, as plan §4 chose: OmniVoice 0.2.1 needs
`transformers>=5.3.0`, which neither the app's `.venv` (5.2.0) nor the Qwen3 engine (4.57.3) can hold. Its base is the
CPython 3.12 the app's own `.venv` was built from (`sys._base_executable`), proved to be a base interpreter: the rule
`tts.qwen3_setup.verified_base_python` applies to the Qwen3 engine. On HOME-PC that is the per-user CPython 3.12.10
both existing environments use. The portable base Python is not present in this development checkout and was
deliberately not placed at `files/runtime-data/python`, because the bootstrap treats that path as the app's own base
and could then want to rebuild the owner's `.venv`. `shared/release.py` already excludes every `.venv-*` folder from
the ZIP; `.gitignore` now names this one.

**Pins.** Every package version and wheel hash is upstream OmniVoice's own `uv.lock` at tag `0.2.1` (commit
`5ba967c4d5b0f08244ae856b033eea583d1e4517`), resolved for win32 / CPython 3.12 / x86-64 without extras: 88 wheels,
including `torch`/`torchaudio 2.8.0+cu128` and `transformers 5.3.0`. That is upstream's tested set; the Qwen3 engine's
HOME-PC-proven torch 2.10.0 would have been an untested combination, so it was not substituted. Installation reads
only the verified local wheels (`--no-index --require-hashes --no-deps --only-binary=:all:`). The model is
`k2-fsa/OmniVoice@c5fdb5ccb189668d56333f77ba2629f4cd7535f4`. Its `audio_tokenizer/` is byte-identical to
`eustlb/higgs-audio-v2-tokenizer@0e3a9177c2991016b8e5e17d23aa474ee665bef2`, so `OmniVoice.from_pretrained` never
reaches its Hub fallback and no separate tokenizer acquisition is needed. Licences, as found: code Apache-2.0; weights
CC-BY-NC per the model card (no version is stated and the Hub metadata names none); tokenizer under the Boson Higgs Audio
2 Community Licence (Llama-3-based). Phase 3's consent text must carry both; commercial audiobook use is not licensed.
The owner consented to the 6,930,785,458-byte download on 2026-11-13.

**Proof reference (owner ruling).** At exactly 10.000 s all six references are mid-speech (energy analysis only; no
speech recognizer). For Male-1 the strict crop would cut the word "things" (its final sibilant lies at about 10.18 to
10.33 s). The owner chose, for the Session 1 proof only, the shorter whole-word crop ending in the gap before "things":
frames 0 to 230,760 at 24 kHz (9.615 s), with the excerpt transcript "Zeth, Sun Sun, Balano, truthless of Shinovar, sat
atop the highest tower in the world and contemplated the end of all". The question put to the owner misstated the
frame count as 231,360 (9.640 s, which would cut into "things"); 230,760 is the 9.615 s the option named, and is the
crop used. The transcript stays provisional: the six excerpt crops and transcripts are approved by the owner in Session 4.
The full-length transcripts and the six recordings are unchanged.

**Proof identity and isolation.** A reusable clone prompt is keyed by the original WAV's SHA-256, the excerpt WAV's
SHA-256, the crop (start, end, rate), the preprocessing version, the excerpt transcript's SHA-256, the model revision,
the omnivoice version, the prompt format and the preprocessing flag, so a change to any of them never reuses an old
prompt. The proof worker sets the Hub's offline switches and an empty app-owned cache, and installs an audit hook that
refuses every non-loopback name lookup and connection. The real run recorded none and left that cache empty.

---

Older entries (before 2026-11-13): [v0.6.7 to v0.7.3](../files/documentation-history/decisions/Decisions-v0.6.7-to-v0.7.3.md) and [v0.5.0 to v0.6.6](../files/documentation-history/decisions/Decisions-v0.5.0-to-v0.6.6.md).
