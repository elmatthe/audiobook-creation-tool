# Audiobook Creation Tool — Briefing

> **Audience:** a new AI session or contributor. **Purpose:** what ACT is today, what must not change, where the authoritative detail
> lives. Live state and the next action are in `Handoff.md`; history in `Changelog.md`; standing decisions in `Decisions.md` (start at its
> index); the application's feature inventory in `Feature-Map.md`.
>
> **Earlier text.** This Briefing was compacted in v0.8.2 Phase 0B. The previous 1,794-line version (per-version histories, the old
> architecture narrative, retained follow-ups) is recoverable with
> `git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Briefing.md`. Open items from it moved to `Handoff.md` (open issues) and to
> "Known limits" below; decisions to `Decisions.md`.

Status words used below: **Implemented** (in the shipped code), **Approved future** (owner-approved, not built), **Pending decision**
(feasibility or owner choice unresolved), **Retired** (history; no longer in production).

## 1. What ACT is

A desktop application for Windows and Apple Silicon Macs that turns PDF and TXT books into narrated MP3 audiobooks and prepares audiobook
files: combining, converting, tagging and building M4B. Its users are **non-technical**: they download a ZIP, extract it, double-click one
setup/launch file and use one window. No terminal, no console flashes, no manual installs, nothing silently overwritten. The current release is
**v0.8.1** (published 2026-11-21 UTC, Windows and macOS ZIPs, on a maintainer verification exception); the `0.8.2` branch is long-running
development (nothing merged, tagged or released per fix). The source is GPL-3.0; it credits epub2tts-edge, edge-tts and Kokoro-82M.

Owner ground rules: every dependency exactly pinned; the repository root stays minimal; Tkinter/ttk is the only GUI toolkit; commits carry no AI
co-author trailer (Decisions, 2026-07-07).

## 2. The six tools (Implemented; `scripts/launcher.py` lists exactly these)

| Tool | Module | Job |
|---|---|---|
| TTS Audiobook | `scripts/tts/epub2tts_gui.py` | PDF/TXT to MP3 through one unified file-and-folder queue; output `<stem>-<voice label>.mp3`; Pause, Cancel, Retry Failed; whole-file concurrency. The module name is historical (GPL provenance); EPUB input was retired in v0.6.1 |
| M4B Converter | `scripts/m4b/converter/` | M4B to MP3, whole book or split by chapter on the complete timeline; metadata Preserve, Replace or write none over a five-field allowlist |
| MP3 Tool | `scripts/mp3/` | Multi-Book workspace: Write ID3 Tags, Combine MP3s into one MP3 (fast or safe route), artwork, numbering |
| M4B Maker | `scripts/m4b/maker/` | MP3s to a chaptered M4B with series tags and an optional custom destination |
| Cover Image Converter | `scripts/artwork/cover_resizer.py` | Pad or crop artwork to a square (JPG, PNG, HEIC); numbered copies by default, replace-originals only by toggle, radio and per-run confirmation |
| M4B Metadata Editor | `scripts/m4b/metadata/` | Edit `.m4b/.m4a/.mp4` tags without re-encoding; Save Tags, Clear All Tags, Remove Series Numbering |

MP3 Tool, M4B Maker and Metadata Editor share the multi-Book workspace (`scripts/shared/book_workspace*`): blank means blank on the first two and
preserve on the Editor. Job, log, import, output-folder and Preferences machinery is shared (`scripts/shared/`). Per-package README module maps
live in `scripts/README.md` and each package. The six tools side by side: `files/dev-work/feature-map/consistency-matrix.md`.

## 3. Platforms and TTS engines (Implemented)

Supported: **Windows 11 (HOME-PC is the qualification machine, 100% display scaling)** and **Apple Silicon macOS**. Linux is neither qualified nor
distributed. The voice roster is decided only by `scripts/shared/engine_policy.py`: Windows offers five engines, **34 voices** (Edge 5, Kokoro 9,
Chatterbox 6, Qwen3 8, OmniVoice 6); macOS offers Edge, Kokoro and OmniVoice, **20 voices**; Chatterbox and Qwen3 are removed from the Mac UI.

| Engine | Where it runs | Notes |
|---|---|---|
| Edge TTS | network, in the app process | the only engine with real multi-file concurrency; Kokoro, Chatterbox and Qwen3 use one worker |
| Kokoro-82M | in-process on Windows; the supervised local-engine worker on macOS (D17, Decisions 2026-11-25) | pinned local model files; espeak data under a short path on macOS |
| Chatterbox Turbo | in-process, Windows; optional, not the default | six bundled reference recordings, verified by SHA-256 on every use; torch device order cuda, mps, cpu; setuptools held at 80.9.0 |
| Qwen3-TTS | isolated worker process in `.venv-engines/qwen3` (uv, its own locked project, since v0.8.2 Phase 5A; an earlier `.venv/engines/qwen3` or `.venv-qwen3` keeps working until replaced), Windows only | per-file subprocess, JSON-lines events, Job Object, one-machine mutex; Python 3.12 exactly; models under `files/runtime-data/models/qwen3-tts` |
| OmniVoice | isolated worker process in `.venv/engines/omnivoice` | Windows needs an NVIDIA GPU; macOS uses mps or cpu; offline by audit hook; 300-character chunks, at most 48 per worker; weights are non-commercial (CC-BY-NC) |

The engines are one explicit list, `scripts/tts/engines/registry.py` (v0.8.2 Phase 5A): the policy, the voice registry's backends, the
setup components and first-run choices, the local engine host, the environment places and the packager derive their tables from it.
Clone voices use 18 shipped reference recordings, engine-specific, bound by `clone_references.json`; Qwen3 uses only the shipped transcript bundle.
A clone transcript, approved selection or private listening artifact is never opened by an agent. Speech text preparation lives in `scripts/tts/speech/`;
an OmniVoice chunk with words that renders silent is re-rendered with derived seeds, at most 24
renderings (Decisions 2026-11-25).

## 4. Repository layout (Implemented)

```
README.md  LICENSE  config.toml  pytest.ini
pyproject.toml  uv.lock     the base environment's project and its one lock (v0.8.2 Phase 4; shipped in the ZIP)
Setup_and_Run-audiobook-creation-tool.bat / .command   the only files a user double-clicks
scripts/        all program code (the single import root): launcher.py, shared/, tts/ (tts/engines/: the registry and each engine's
                uv project, Qwen3's since 5A), mp3/, m4b/{converter,maker,metadata}/, artwork/; qwen3-requirements.txt and
                qwen3-artifacts.json, requirements.txt and the two v0.8.1 hash locks stay only as frozen parity references
md-instructions/  exactly five permanent documents (below)
files/
  plans/                    active implementation plans (current: Developer-Experience-Upgrade.md)
  release-history/          durable release qualification records
  tests/                    the test suite (never shipped)
  dev-work/                 local development workspace: verification-gate/ (verify.py, GATE.md, coverage.json), feature-map/
  bin/  runtime-data/       runtime, ignored (FFmpeg, settings, logs, models; uv/ = the pinned uv and managed Python, uvc/ = the repair cache)
  Archives/  dist/          protected, local and ignored (historical archives, built ZIPs)
  test-files/               owner fixtures, never touched
  UI-Tool-Screenshots/  voice-previews/  Cloned-Voice-Uploads/  tracked supporting assets
.venv/          the application environment (uv's); also holds .venv/engines/omnivoice until 5B (and an earlier version's
                .venv/engines/qwen3 until a new Qwen3 install replaces it); rebuilt on each machine, never committed
.venv-engines/  independent engine environments (owner decision A1, 2026-11-27): qwen3/ since 5A; never committed or shipped
```

`scripts/Universal/` no longer exists (Retired: the v0.5.0 layout was lifted to `scripts/` in v0.6.7; any mention of it is stale).

## 5. Runtime, setup, launch and repair (Implemented)

- **Entry.** `Setup_and_Run-audiobook-creation-tool.bat/.command` runs a fast health check (about 150 ms) and launches the GUI; an unhealthy
  environment goes to repair. Windows launches on the venv's `python.exe` with a hidden console; `pythonw.exe` is never started because Smart App
  Control blocks it (Decisions 2026-11-18).
- **Provisioning (v0.8.2 Phase 4; verified natively on Windows and macOS).** Stage 0 (`bootstrap_host.ps1` /
  `bootstrap_host_macos.sh`; when PowerShell cannot run, `bootstrap_host_fallback.cmd` with Windows' own curl, certutil and tar, owner
  decision D-6) obtains, with consent and pinned hashes, uv 0.13.10 and uv's managed CPython 3.12.15 (python-build-standalone 20261009,
  through ACT's own download metadata) into `files/runtime-data/uv`; nothing is installed on the computer and no Python found on it is used.
  The base environment is `uv sync --locked` of the root `pyproject.toml`/`uv.lock` (one lock for both platforms, a parity translation of the
  v0.8.1 locks; Kokoro and Chatterbox stay in the base until 5C/5D) through one wrapper, `scripts/shared/uv_runner.py`: exact interpreter,
  an explicit user or dev profile (`bootstrap.py --profile`, never inferred), offline first from the repair cache `files/runtime-data/uvc`,
  a download only after consent, link mode copy on Windows and clone on macOS, bytecode at install. The receipt `.venv/.act-environment.json`
  is written only after every installed file matches its RECORD and every required module imports. Damaged packages are reinstalled in
  place; anything uv could only recreate (a v0.8.1 pip environment, a moved copy) is rebuilt through the set-aside transaction, engines
  carried. The v0.8.1 interpreter in `files/runtime-data/python` is kept for engines built on it; `scripts/shared/app_python.py` is the one
  resolver of the base interpreter. NLTK and Hugging Face caches stay inside the app folder. First run prepares the base app only; the
  optional-component panel then offers five components (OmniVoice last and unchecked) acquired from pinned identities under a one-use
  consent (Decisions 2026-10-25, 2026-10-27); the OmniVoice installer keeps its own route until 5B.
- **Engine environments (v0.8.2 Phase 5A).** Qwen3 is installed by uv into `.venv-engines/qwen3` (`uv venv` on the managed CPython, then
  `uv sync --locked --no-dev --no-cache` of `scripts/tts/engines/qwen3/`: the v0.8.1 89 packages exactly, torch 2.10.0+cu128 from the
  explicit CUDA 12.8 index, no package cache kept) through `scripts/shared/engine_env.py` (identity, RECORD check, receipt, retirement);
  it is the engine in use only once its install record is written, last. An earlier engine keeps working until then; the nested one is then
  moved whole to `files/runtime-data/qwen3/set-aside/` (never deleted); `.venv-qwen3` is never moved. A base repair never touches
  `.venv-engines`; a Qwen3 install and a repair still refuse each other.
- **Nested layout (until 5B).** `.venv` holds `.venv/engines/omnivoice` (and an earlier version's `.venv/engines/qwen3`); repair, replace
  and rollback keep them; engine leases refuse a repair while a worker runs; set-aside folders (`.venv.replaced*`, `.venv.discarded*`) are
  ignored and never packaged. The older `.venv-qwen3` is Retired and kept only for rollback until the owner retires it.
- **FFmpeg** is user-scope (winget or Homebrew) or a pinned portable copy under `files/bin/ffmpeg/<version>`, proved by running it; no PATH fallback.
- **Path depth.** Windows paths are counted in UTF-16 (`shared.long_paths`): the app folder may be 87 characters or fewer with long paths off
  (83 with OmniVoice), 123 (119) with the Win32 long-paths switch; README documents the limits.
- **Portability.** A release ZIP holds committed files only (README, config.toml, launchers, tracked `scripts/`), built clean; setup self-heals
  Kokoro on every launch; Clear Downloaded Data is a closed four-id catalog run by a post-exit helper.

## 6. Architecture invariants (Implemented; the rules behind the code, with their Decisions entries)

- **Interface.** `scripts/shared/ui_theme.py` has three branches: Windows dark with the `Compact.*` style catalogue, macOS Aqua (native controls;
  four outlined role styles draw a same-size outline image), and classic for Linux. The `ACT.*` and `Compact.*` styles are isolated; widgets are
  styled only through the shared style helpers; there is one appearance setting. Every tool must fit 920x600 (Windows) or 1024x800 (macOS) with
  no whole-panel scroll. The TTS panel is the visual reference for control language. A Tk object is only touched on the main thread; a closed
  Tk root is never touched by a worker.
- **Configuration.** Three layers, last wins: code defaults, valid values in `config.toml`, then the output location chosen in the app
  (`settings.json`). Each `config.toml` value is checked on its own and falls back with a report; unknown keys are mentioned once.
  Outputs go to `<base>/<Tool>-Outputs/<Tool>-N`. `developer_mode` is a strict boolean, shipped false (reference-transcript tools are
  developer-only). Voice identity is (backend, voice_id); labels and order are cosmetic.
- **Cancellation and containment.** A publication commit is ordered against Cancel (`authorized_commit`); collection never runs on the
  cancelling thread; every FFmpeg step runs under one supervisor and can be stopped; Windows workers sit in Job Objects, POSIX workers are never
  reaped before their process group has ended and an identity that cannot be proved is never signalled; retry staging lives exactly as long as
  Retry Failed can reach it. Cancel acknowledgement target is about 1 s on macOS.
- **Acquisition.** Observation is not permission: a model, wheel or binary is acquired only from a pinned identity (commit, size, SHA-256 in
  `scripts/tts/model_assets.py` and the manifests), under consent, and inference loads only verified local copies and never downloads.
- **Release.** The ZIP is built clean from committed files; launchers are byte-proved; reference WAVs are the 18 tracked recordings; a release,
  tag and publication are separate, separately authorized steps (never done by an agent unasked).
- **Private artifacts.** Clone transcripts, approved selections and listening packs are private: never opened, copied or committed.

## 7. User data and output safety (Implemented; never weaken)

Sources are never modified. Outputs are copies published whole-or-nothing from private staging; nothing is silently overwritten (TTS Overwrite
is off unless ticked for a run); the run folder is reserved atomically at validated start. Two opt-in exceptions exist: Cover beside-source
(replace needs toggle, radio and per-run confirmation, uses `os.replace`) and the Maker's custom destination. Output names are sanitised,
case-insensitively collision-checked, contained, and never follow links; importing is read-only. Cancel stops active work promptly (only Pause
drains active files). Settings are written atomically to `files/runtime-data/settings.json`; the GUI never rewrites `config.toml`; Reset touches
nothing else. Private TTS scratch lives in `%TEMP%\act-tts` with dead-owner recovery. There is no Save Job or session restore (owner decision).
A process killed from outside can leave `.work` residue (documented boundary).

## 8. Verification policy (Implemented; simplified 2026-11-27)

`files/dev-work/verification-gate/GATE.md` is the authoritative policy and command reference; `verify.py` there is the one gate (`scripts/verify.py`
is gone). Exit code 0 alone never passes: a pytest stage passes only when its exit, JUnit, the session probe and the requested scope agree, cleanup
is clean and the tree did not change; skipped, blocked or interrupted work never counts as passing. Routine modes execute: `quick` (static checks
and an import smoke), `focused --test`/`--feature`, `changed` (Git plus reverse-import routing; an unresolved path is a gap and nothing runs) and
`regression --component`. `--mode full`, `qualification --scenario`, native journeys, real engines, installs, downloads and release builds run
only with the owner's explicit authorization for that named run; `qualification --journey` is plan only. Every pytest process installs a small
routine guard from `conftest.py` (`files/tests/routine_effects.py`): a routine marker every child inherits (the heavyweight entrypoints refuse
under it), real-engine opt-ins scrubbed, non-loopback network, real model loads and desktop hand-offs refused in-process. Since the v0.8.2
simplification there is no launch interception or per-child accounting; each gate stage is supervised (deadline, kill-on-close Job or process
group, survivors reported). A direct `python -m pytest <module>` from the repository root is a developer check; the gate run is the evidence. The
guarded groups run only through the gate. The 56 native journeys take over mouse and keyboard; a locked desktop is BLOCKED. Scratch is
repository-contained (`files/run-temp/`) except the approved `%TEMP%\act-gate`. Feature changes are recorded in `files/dev-work/feature-map/` and
`coverage.json`. Test rules that bite: AST guards, not substring guards; Windows tests must skip, never fail, on macOS.

## 9. Documentation and workspace conventions (Implemented)

- `md-instructions/` holds exactly five permanent documents in exact case and nothing else: `Briefing.md`, `Handoff.md`, `Feature-Map.md`,
  `Decisions.md`, `Changelog.md`. The gate reads real directory entries because path lookups are case-insensitive. Decisions is append-only,
  newest first, with a navigation index at its top; Changelog keeps release history with an index at its top. Entries before v0.8.0 are
  archived unchanged in `files/documentation-history/decisions/` and `files/documentation-history/changelog/` (DOC-1, Phase 2).
- Plans: `files/plans/`. Release qualification records: `files/release-history/`. Protected archives: `files/Archives/`, `dist/`.
- **Two kinds of checkout (D-5).** The repository is public. A fresh public checkout (clone, source ZIP, release ZIP) has no AI Workspace
  files and works fully. A development checkout adds local-only `AGENTS.md`, root `CLAUDE.md`, `AI-WORKSPACE.md`, `.ai/` and `.claude/`
  (gitignored, never staged or pushed); the application and its tests never need them. The owner's canonical `AI-WORKSPACE.md` is not yet
  installed (Handoff); an older stale `.claude/CLAUDE.md` in the owner's primary checkout still loads as a parent-directory file there (not in the development clone `C:\ACT-Dev`).
- Branches: `master` integrates; `0.8.2` is long-running. The owner's primary checkout (`0.8.1`, daily use, uncommitted owner work) is never
  switched, reset or edited by an agent; `0.8.2` is developed in the permanent short-path clone `C:\ACT-Dev` (owner decision D-1, approved 2026-11-25; its own real root `.venv/`, a development
  location only, never referenced by application code). The old nested worktree `files/dev-work/wt082` is preserved, documentation-only, and holds protected local evidence.
- The main application environment is always `.venv/` directly inside the application root, in development checkouts, source ZIPs and release ZIPs on both platforms (fixed requirement).

## 10. Protected paths

Never modify, clean or reorganize: `dist/`, `files/Archives/`, `.venv/`, `files/runtime-data/`, `files/bin/`, owner fixtures (`files/test-files/`,
`files/test-for-manual-listen-*`), listening evidence and regenerated audio under `files/dev-work/`, active worktrees, other agents' scratch,
unknown paths and ACL-locked folders. Retention rules for agents' scratch and gate evidence: `files/dev-work/verification-gate/GATE.md`
("Retention and cleanup", v0.8.2 Phase 2).

## 11. Direction (Approved future; none of it is built)

The active plan `files/plans/Developer-Experience-Upgrade.md` (Revision 10) sets the v0.8.2 direction: Phases 0 to 3 are done (documentation,
the simplified verification gate, cleanup, uv feasibility on Windows and macOS); **Phase 4, base provisioning through uv, is done**
(accepted natively on Windows and macOS); **Phase 5A, the engine registry and Qwen3 in `.venv-engines/qwen3`, is done on Windows**
(above). Still to come: 5B OmniVoice migrated to `.venv-engines/`, 5C/5D Kokoro and Chatterbox Turbo **isolated** into their own
environments, 6 migration and legacy retirement, 7 user-facing documentation and deterministic distributions (VERSION becomes 0.8.2 only
then), 8 performance and native qualification readiness, 9 independent Codex review. **Not implemented today**: OmniVoice under
`.venv-engines/`, isolated Kokoro or isolated Chatterbox on Windows. Do not duplicate the plan here.

**Pending decisions:** D-2 external scratch, D-3 ACL-locked folders, D-4 the owner's uncommitted plan/release-history archiving (see
`Handoff.md`). D-6 was approved and implemented in Phase 4.

## 12. Known limits (Implemented behaviour; details and evidence in `Handoff.md` and `Decisions.md`)

- **Qualification scope.** Windows is qualified on HOME-PC at 100% scaling only; 125%/150% scaling, Windows 10, other GPUs, a non-admin
  target and a fresh VM are unproven. The app is DPI-unaware by decision. macOS qualification (P7) is pending: `*.PREPARATION` and
  `WORKSPACE-SCALING` features carry a pending macOS standing; no clean Apple Silicon Mac with 16 GB or more has been available.
- **Security software.** Smart App Control blocks unsigned natives (sklearn `.pyd`, FFmpeg, `pythonw.exe`); a fresh venv can pull unsigned
  transitive wheels. WinError 206 appears on over-deep paths.
- **uv provisioning (Phase 4).** One Mac only (HOME-MacOS, administrator; no standard user, fresh account or real browser-quarantined
  ZIP); a moved Mac copy is repaired on its next start (its environment's interpreter link dangles until then); the PowerShell-blocked fallback's download path and a non-admin Windows account are
  untested; the launch health check samples one file per package, so deep pure-Python damage is found by the import proof (7-day window) or
  Preferences' Check and repair. A repair cache costs about 2 GB beside the 2.1 GB environment.
- **Qwen3 through uv (Phase 5A).** Every Qwen3 install or rebuild downloads about 3.1 GB again (no package cache, A4/D-8); proved on
  HOME-PC only (one machine, one GPU); real synthesis on the new environment awaits a separately authorized run; a uv scratch folder left
  by a killed operation is cleared only once its owner is provably gone (folders from before owner records are kept).
- **Engines.** Two app copies can run Qwen3 and OmniVoice on one GPU together; OmniVoice outputs can reach full scale; Qwen3 is English-only
  and slow (RTF about 1.35); Chatterbox says "Tamar" wrongly and has frozen pause tuning (Decisions 2026-11-25); the 900 s worker stall deadline
  was measured only on CUDA.
- **Text and audio.** Narration of about 24.85 hours or more cannot be encoded; a final heading with no text is not spoken; TXT input is UTF-8
  only; xHE-AAC/USAC was never verified on real media; PDF cleaning has five pinned limits (ACT72-064).
- **macOS containment.** `setsid` escapees are unreachable, a helper can survive an app kill in a 0.2 s window, a cancel on a hung filesystem
  call cannot be interrupted; repository folders on macOS are created world-writable pending an owner decision.
- **Large workspaces.** Residual Tk work remains: Cover standard Start up to 143 ms at 5,000 images, replace-originals validation 1.3 s at
  5,000, Converter planning not cancellable; the M4B Maker and Editor do not refuse actions during a folder scan (owner call).

## 13. Retired history (not in production)

EPUB input and `ebooklib`/`bs4`/`lxml` (v0.6.1); the root `.venv-omnivoice` and `.venv-qwen3` locations; `scripts/Universal/` and
`scripts/verify.py`; a four-document contract and the exact-four tests; `pythonw.exe` launching; the macOS-only `0.8.0+macos.1` tag (it shipped
inside v0.8.1); per-version sections of the old Briefing. Release lineage: v0.6.6 (2026-09-30), v0.7.0 (2026-11-02), v0.7.2, v0.7.3
(2026-11-12), v0.8.0 (2026-11-14, owner exception, Windows), v0.8.1 (2026-11-21 UTC, Windows and macOS); see `Changelog.md`'s index and
`files/release-history/`.

## 14. Where to read next

| Need | Read |
|---|---|
| Live state, open issues, next action | `Handoff.md` |
| Why something is the way it is | `Decisions.md` index, then the dated entry |
| What shipped when | `Changelog.md` index |
| What a feature must do and how it is verified | `Feature-Map.md`, `files/dev-work/feature-map/`, `coverage.json` |
| What verification may run | `files/dev-work/verification-gate/GATE.md` |
| The active plan | `files/plans/Developer-Experience-Upgrade.md` |
| Release qualification evidence | `files/release-history/` |
