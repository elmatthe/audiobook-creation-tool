# PRE-PLAN-6 — `Setup_and_Run` / bootstrap self-healing remediation

**Type:** temporary implementation drop (delete at closeout — see §14)
**Version identity:** `0.6.2`, **UNRELEASED** — this drop publishes nothing
**Branch:** `maintenance/0.6.2-setup-self-healing`
**Base:** `e36ab7d9236e210a5dfd8aaf69f25a158ca0908c` (PR #8 merge commit on `master`)
**Status:** Phase 0 complete (this document). **Phase 3 complete** — the portable Windows
FFmpeg acquisition is pinned, verified, transactional and cannot sacrifice a working pair.
Phase 4 not started. **Phase 1 complete** — C2, M1, L1a and L1b
fixed; Python contract enforced; remediated after review so a present-but-non-importable
module can no longer hide behind matching pins. **Phase 2 complete** — H2 closed; venv
health is one bootstrap-owned authority, recovery is reachable and rollback-safe, and no
launch path reaches FFmpeg provisioning. Phase 3 not started.
**Authored:** 2026-09-03, from the approved Checkpoint-1 read-only investigation as revised by
maintainer/ChatGPT review.

---

## 1. Context

### What this is

This is **one bounded maintenance drop**, sequenced *between* Plan 5 and Plan 6.

- **Plan 5** (M4B Converter upgrade) is **COMPLETE / APPROVED / CLOSED / MERGED**, integrated
  through **PR #6 / `7fc9d18b69a2a5b802cc88ef9eada99f17a3df6f`**, with follow-up records
  reconciliation through **PR #7 / `e8c6635673fd95ed5e0a3842e480ab5a3d9c8c0a`** and durable
  integration anchors through **PR #8 / `e36ab7d9236e210a5dfd8aaf69f25a158ca0908c`**.
  **This drop does not reopen Plan 5.**
- **Plan 6 has NOT started.** It must not begin — no drafting, no drop, no planning — until this
  maintenance work is dispositioned **and integrated into `master`**.
- The carry-forward defect that makes this drop necessary is recorded in `Handoff.md` and in
  `md-instructions/don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md`
  (§5 / §15), both of which name a separate PRE-PLAN-6 remediation as the next action.

Per the *never hard-code a live branch tip* rule established by PR #8, the SHAs above are permanent
merge commits, not a claim about where `master` points today. Query Git for the tip.

### The defect, as reproduced

A read-only investigation on current `master` (`e36ab7d`) **reproduced the reported failure live**
on HOME-PC and traced it in source. It is not a hypothesis.

> Existing root `.venv` + no usable FFmpeg/ffprobe pair
> → `Setup_and_Run` takes its fast path (`--launch-only`)
> → `bootstrap` **detects** that no pair is usable
> → **cannot provision one**
> → tells the user *"Run Setup_and_Run again to install a known-good copy."*
> → re-running repeats the identical non-repairing path, indefinitely.

The only escape today is **manually deleting `.venv`** — the one recovery a non-technical user must
never be asked to perform, and the one the product contract in `AI-WORKSPACE.md` forbids.

The investigation also found a **second instance of the same shape** on a different dependency
(the requirements success stamp, §4.3 C2), plus supporting defects. All are in scope here.

### Preserved acceptance state — do not repair before Phase 7

HOME-PC deliberately still holds the reproduction condition:

- root `.venv` present and healthy (Python 3.12.10, `ssl` OK, Tk OK, requirements stamped current);
- **no usable ffmpeg/ffprobe pair anywhere** — `files/bin/` absent, nothing on `PATH`, no
  `Gyan.FFmpeg*` WinGet package, `files/runtime-data/ffmpeg-state.json` holds no pin.

**Phases 1–6 must not consume, repair or disturb this condition.** Phase 7 is the first phase
permitted to spend it, and spending it *is* the acceptance test.

### Untouchable local file

`md-instructions/don't-delete/Codex-Investigation-Report-batch-launcher.md` is a maintainer-owned
**untracked** historical report. **Never edit, move, delete, stage or commit it** — including to
make a test green (see §10.4).

---

## 2. Goal

**`Setup_and_Run` becomes the single idempotent, self-healing entry point on Windows and macOS.**

| Machine state | Required behaviour |
|---|---|
| **Healthy** | Launch quickly. No repair work, no dialogs, no probing beyond the cheap steady-state assessment. |
| **Broken** | Detect the **minimum** unhealthy prerequisite → repair **only** that prerequisite → **prove** the repair by executing/importing it → write success state **only after** the proof → launch. |
| **Repair failed** | No false success stamp. No false FFmpeg pin. Preserve last-known-good state where possible. Remain safely retryable. Give one truthful message stating what was attempted and what failed. |

**Two absolute rules:**

1. **No normal recovery may require the user to manually delete `.venv`.**
2. **Never tell the user to repeat `Setup_and_Run` when repeating it follows the identical
   non-repairing path.** Once repair genuinely exists, "run it again" becomes a true instruction —
   until then it is a lie, and it is the mechanism of the loop.

---

## 3. Scope

### In scope

- `Setup_and_Run-audiobook-creation-tool.bat` and `.command` — the health gate that selects the
  fast path, and the recovery route when that gate fails.
- `scripts/Universal/shared/bootstrap.py` — assessment, repair, proof, stamping, orchestration,
  Python selection, requirements validation, FFmpeg provisioning.
- `scripts/Universal/shared/ffmpeg_health.py` — remains the **one** health authority; may gain a
  bounded deterministic repo-local candidate location. **No competing discovery/proof system.**
- `scripts/Universal/shared/ffmpeg_utils.py` and its production consumers — trust closure only.
- `files/tests/` — the regression matrix in Phase 6.
- `md-instructions/` — coordination records and the closeout ADR.

### Out of scope

- **Plan 6.** Not drafted, not started, not referenced as begun.
- **Plan 9 work:** signing, code-signing reputation, redistribution/licence policy for shipped
  binaries, packaging, `release.py`, fresh-machine release certification, Windows 125% scaling.
- **Any release action:** no `[0.6.2]` changelog heading, no tag, no GitHub release, no package,
  no `release.py` run. Latest published release stays **`v0.4.0`**.
- **A newly invented macOS portable-binary architecture.** macOS gets the existing Homebrew route
  made reachable and its absence handled truthfully (§8.6), nothing more.
- **Unrelated refactoring.** Do not touch the Converter, TTS, metadata, launcher UI or any Plan-5
  surface except where a named contract in §8 requires it.
- **Bundling FFmpeg bytes in Git or in a release package.** The portable fallback is an **on-demand
  runtime acquisition** only.
- **Repairing the preserved HOME-PC FFmpeg condition** before Phase 7.

---

## 4. Current architecture (as-is) and the confirmed defects

### 4.1 The Windows control flow, as it actually runs

```
Setup_and_Run-audiobook-creation-tool.bat
  |- if exist ".venv\Scripts\pythonw.exe"                      <- existence test, NOT health
  |     start "" ".venv\Scripts\pythonw.exe" bootstrap.py --launch-only
  |     exit /b 0
  |- (else) first-run console branch: where py / where python / winget Python.Python.3.12
            then "%PYCMD%" bootstrap.py   (no flag)

bootstrap.main()                                               bootstrap.py:1862
  |- if args.launch_only:  return _launch_with_kokoro_healthcheck()
  |- if venv_is_valid():   return _launch_with_kokoro_healthcheck()   <- ***
       (run_with_gui() / _run_headless() -> run_setup() are reached ONLY if neither holds)

_launch_with_kokoro_healthcheck()                              bootstrap.py:1780
  |- requirements_are_current()?  -> if current, the whole reconcile block is skipped
  |- ensure_ffmpeg_ready_for_launch()                          bootstrap.py:1751
  |     |- ffmpeg_health.ensure_ready()  -> discover / prove / pin ONLY. Never installs.
  |     |- show_warning_dialog(...)      -> BLOCKING modal
  |     |- return False                 -> RETURN VALUE DISCARDED BY THE CALLER
  |- kokoro_is_healthy() -> optional in-venv repair
  |- launch_gui()
```

macOS `.command` reaches the **same** `main()` through `".venv/bin/python" "$BOOTSTRAP"
--launch-only`. `bootstrap.py` is one cross-platform file; there is no macOS-specific launch path.
**The gap is confirmed on both platforms.**

### 4.2 Why provisioning is unreachable

FFmpeg provisioning exists in exactly one chain:

```
run_setup()                       bootstrap.py:1308
  |- ensure_ffmpeg()              bootstrap.py:1004
  |    |- _install_ffmpeg()       bootstrap.py:1039   winget Gyan.FFmpeg / brew install ffmpeg
  |    |    |- _download_portable_ffmpeg_windows()    bootstrap.py:1082
  |    |- ffmpeg_health.establish()
```

`run_setup()`'s only callers are `run_with_gui()` and `_run_headless()`, and `main()` returns
before reaching either **whenever a valid `.venv` exists** — for `--launch-only` *and* for a bare
`bootstrap.py` invocation. `ffmpeg_health` contains no provisioning code, correctly and by design.

**Root cause, stated once:** `ensure_ffmpeg_ready_for_launch()` is a *detector* wired into a path
that has no *provisioner*, and its `False` is discarded. This is a wiring defect, not a flaw in the
Plan-5 Phase-15 health architecture.

### 4.3 Confirmed defects to be fixed by this drop

| ID | Sev | Defect | Evidence |
|---|---|---|---|
| **C1** | Critical | Launch path detects a missing/broken FFmpeg pair, cannot provision, and instructs the user to repeat the identical failing action. Windows **and** macOS. | Reproduced live; `bootstrap.py:1751`, `:1780`, `:1862`; `ffmpeg_health.describe_failure()` |
| **C2** | Critical | `run_setup()` discards `validate_installed_packages(log)`'s result (`bootstrap.py:1368`) and calls `record_requirements_state()` unconditionally (`:1372`). A first run whose package installs but does not import is stamped healthy **permanently**; no later launch re-probes `REQUIRED_IMPORTS`. | Source; the drift path `ensure_requirements_current()` (`:296`) is **correct** and honours both gates |
| **H1** | High | Portable FFmpeg fallback: floating BtbN `latest`/`master-latest` URL, **no checksum**, downloads *into* the live `files/bin/`, two independent `write_bytes` over the live pair, success gated on `ffmpeg.exe` **existence only**, no cleanup or rollback. Currently masked by C1 — **fixing C1 first would make it reachable.** | `bootstrap.py:1082` onward |
| **H2** | High | The `.bat` gates on `pythonw.exe` **existing**, not on the venv being alive; `--launch-only` never calls `venv_is_valid()`. A broken venv is routed into a path that cannot rebuild it. `_create_validated_venv`'s ssl/Tk recreate and its `>=3.13` rebuild are structurally dead from a launch. | `.bat` fast path; `bootstrap.py:865`, `:1900`, `:1904` |
| **H3** | High | Runtime executes an **unproved** pair: `ffmpeg_utils._resolved_pair()` falls back to the first coherent-but-unproved discovered pair, and every consumer gates on `have_ffmpeg()`. `verified_ffmpeg()` exists and **no production code calls it.** | `ffmpeg_utils.py:29`, `:75`, `:87`; `m4b_converter.py:650`, `:963`; `mp3_tool.py:81` |
| **M1** | Medium | `argv = cand.split() if " " in cand else [cand]` (`bootstrap.py:769`) shatters `C:\Program Files\Python312\python.exe` into two argv elements; both existence guards are `len(argv) == 1` so they are skipped, the spawn fails, the exception is swallowed and the candidate is **silently dropped**. A username containing a space breaks the `%LOCALAPPDATA%` candidate identically. It is the **only** `.split()`-based argv construction in the tree; there is no `shell=True` anywhere. | `bootstrap.py:769` |
| **M2** | Medium | `ffmpeg_cmd()` / `ffprobe_cmd()` fall back to bare `"ffmpeg"` / `"ffprobe"`, resolved **independently** through `PATH` at exec time — outside `pair_in()`'s sibling rule, so the two halves can come from different installations. | `ffmpeg_utils.py:112`, `:117` |
| **M3** | Medium | The unrepairable-prerequisite notice is a **blocking modal on the launch fast path**. Observed live: the process sat indefinitely at *"The audio tools are unavailable"* before the GUI existed. | `bootstrap.py:1737`, `:1751`; live reproduction |
| **M4** | Medium | macOS has no repo-local fallback and no automated route without Homebrew; `_install_ffmpeg`'s mac branch prints `https://brew.sh/` and returns. The `.command`'s only `brew install ffmpeg` lives in the **first-run** branch and never runs for an existing venv. | `.command`; `bootstrap.py:1039` |
| **M5** | Medium | Neither WinGet invocation passes an explicit `--scope`. Both `Python.Python.3.12` and `Gyan.FFmpeg` rely on the package default — untested against the CSPW-PC Standard User constraint. | `.bat`; `bootstrap.py:828`, `:1039` |
| **L2** | Low | **Tk finalisation stalls a worker thread (pre-existing, NOT fixed here).** A garbage collection that lands on a non-main thread finalises a leftover `tkinter.Variable`; `Variable.__del__` calls into Tcl, which stalls off the main thread. Any bounded wait on that thread then times out. It predates this drop and is only ever *exposed* by changes to allocation timing. **Phase 1 changed nothing for it** — see Phase 6 row 18. | Stack dump of the stalled `import-c-op-000001` thread, stopped inside `tkinter/__init__.py:414 __del__` |
| **L1** | Low | **Test runs mutate production environment state.** (a) Module-level `LOG = SetupLog()` writes into the **production** `files/runtime-data/logs/setup_<date>.log` during pytest runs, interleaving tmpdir paths with real runs. (b) A full suite run **rewrites the real `.venv/.requirements-state.json`** — observed 2026-09-03, `recorded_at` advancing from `2026-09-02T21:05:05` to `2026-09-03T06:17:22` during a `verify.py` run, fingerprint unchanged. **Traced mechanically in Phase 1** (a plugin that redirected and recorded any write aimed at the real stamp, so one run found every culprit instead of the first): **three** tests — `test_bootstrap_setup_logging.py::test_run_setup_reaches_kokoro_warmup_without_typeerror` and `test_chatterbox_bootstrap.py::{test_run_setup_skips_the_chatterbox_steps_when_not_requested, test_run_setup_downloads_chatterbox_only_when_asked}`. Each drives `run_setup` with every install *step* stubbed but leaves `bootstrap.VENV_DIR` at the real checkout, so C2's unconditional stamp lands in the real `.venv`. Harmless only because the fingerprint matched — a suite that can write the real stamp can write a **false** one, which is exactly the C2 invariant. | Tripwire stacks: `run_setup` → `record_requirements_state` → `Path.write_text` |

### 4.4 Two structural test weaknesses that let C2 and M1 survive

- `test_bootstrap_requirements_state.py::test_setup_records_the_stamp_only_after_packages_validate`
  parses with AST but then asserts **string indices** (`body.index(a) < body.index(b)`). It proves
  textual ordering, never that the stamp is conditional — so it passes against C2 while its name
  promises the opposite.
- `test_first_run_contract.py::test_a_winget_install_is_accepted_without_waiting_for_path` slices
  source between substrings.

The repo already carries the standing lesson *never write substring boundary guards, use AST*.
Both must be tightened. **A test that cannot fail on the defect it names is worse than no test,
because it is read as coverage.**

### 4.5 What is already correct and must be preserved

Do not "fix" these — they are deliberate and, in several cases, ADR-backed:

- `ensure_requirements_current()` honours **both** gates and writes no stamp on failure.
- Reconciliation **never deletes or recreates** the environment.
- `ffmpeg_health`'s coherent-pair rule (`pair_in` requires both halves as siblings of one
  directory), its execute-to-prove rule, its **pin-where-it-lives** rule, its rejected-candidate
  memory (a blocked binary is never re-executed, so Windows Security is not re-provoked), and its
  `path + size + mtime_ns` identity with SHA-256 kept as durable evidence rather than as the hot
  check.
- `kokoro_is_healthy()`'s cheap probe and in-venv repair; `chatterbox_is_healthy()`'s deliberate
  **absence** from the launch fast path (it imports torch).
- The refusal to name a security product to disable, anywhere in the failure text.

---

## 5. Relevant files

**Production — will change**

| File | Role in this drop |
|---|---|
| `Setup_and_Run-audiobook-creation-tool.bat` | Windows entry point; the `pythonw.exe`-existence gate (H2), WinGet Python scope (M5) |
| `Setup_and_Run-audiobook-creation-tool.command` | macOS entry point; the `[ -x ]` gate, Gatekeeper translocation guard, first-run Homebrew route (H2, M4) |
| `scripts/Universal/shared/bootstrap.py` | C1, C2, H1, H2, M1, M3, M4, M5, L1 — the central file |
| `scripts/Universal/shared/ffmpeg_health.py` | Sole health authority; bounded repo-local candidate location; failure text (C1, H1) |
| `scripts/Universal/shared/ffmpeg_utils.py` | Trust closure (H3, M2) |
| `scripts/Universal/mp3_tools/m4b_converter.py` | `have_ffmpeg()` gates at `:650`, `:963` (H3) |
| `scripts/Universal/mp3_tools/mp3_tool.py` | `ensure_ffmpeg_available()` at `:81` (H3) |

**Production — read for context, do not modify**

`shared/subprocess_utils.py` (no-console wrappers, `install_no_window_guard()`),
`shared/maintenance.py` (cleanup catalog: `virtual_environment`, `portable_binaries` → `files/bin`,
`PROTECTED_RELATIVE`), `mp3_tools/m4b_maker.py`, `m4b_probe.py`, `shared/metadata.py`,
`tts/chatterbox_synth.py`, `tts/epub2tts_edge/epub2tts_edge.py` (all consume `ffmpeg_cmd()` /
`ffprobe_cmd()`), `scripts/requirements.txt`, `scripts/verify.py`.

**Tests — will change or be added**

`files/tests/test_first_run_contract.py`, `test_ffmpeg_health.py`,
`test_bootstrap_requirements_state.py`, `test_bootstrap_python_version.py` (currently one test),
plus new modules for Python selection, portable acquisition and the orchestration state machine.

**Coordination**

`md-instructions/Handoff.md` (per-phase state), `md-instructions/Decisions.md` (closeout ADR),
`md-instructions/Changelog.md` and `Briefing.md` (closeout only, if appropriate),
`AI-WORKSPACE.md` (read-only contract source).

**Never touched**

`md-instructions/don't-delete/**` — maintainer-owned. Read as evidence; never write.

---

## 6. Tools and skills

Assemble before coding, per `AI-WORKSPACE.md` *Implementation Approach* §2.

| Tool / skill | Source | Use here |
|---|---|---|
| `.claude/skills/audio-processing/` | already in repo | FFmpeg/ffprobe invocation conventions; **note its "ffmpeg on PATH" assumption is exactly what this drop replaces** — treat that line as superseded by `ffmpeg_health` |
| **Context7 MCP** | user-scope MCP | Current docs when working against a specific API — `zipfile`, `hashlib`, `urllib.request`, `os.replace` atomicity, WinGet CLI `--scope`, Homebrew CLI. Do not rely on training data for CLI flags. |
| **Sequential Thinking MCP** | user-scope MCP | Phase 5 orchestration only, where the state machine has genuinely revisable branching |
| **Superpowers** (brainstorm → plan → TDD → review) | user-scope plugin | Structures Phases 1–6, which are test-first by contract |
| `scripts/verify.py` | in repo | The mechanical gate (`RESULT: PASS`) |
| `python -m pytest files/tests/...` | in repo | Per-phase targeted gates |
| `bootstrap.py --self-test` | in repo | Existing detection-only reporter: `pinned_pair()`, `discover_pairs()`, `_ffmpeg_on_path()`, `_ffmpeg_in_bin()`, `_ffprobe_available()` |

**No new runtime dependency may be added by this drop.** Everything required — `hashlib`,
`zipfile`, `urllib.request`, `shutil`, `os.replace`, `subprocess` — is stdlib, and `bootstrap.py`
must remain **stdlib-only and importable before the venv exists**
(`test_the_health_module_stays_importable_before_the_venv_exists` guards this).

If a genuinely useful public skill is found during the work, copy it into `.claude/skills/`, note
its source, and list it here.

---

## 7. Permissions

**Granted for this drop, standing:**

- Full permission to run file edits and terminal commands without per-action approval, on the
  `maintenance/0.6.2-setup-self-healing` branch.
- Commit and push **to that branch only**, once per completed phase whose gate is satisfied.
- Create and use repo-local working directories under `files/dev-work/<phase>/` (gitignored).

**Requires explicit maintainer permission — STOP and ask:**

- Any workspace **outside** the repository. `AI-WORKSPACE.md` *Repository-Local Artifact
  Containment* is a hard rule as of 2026-08-29: state (1) why `files/` cannot satisfy it,
  (2) the exact path, (3) what is created, (4) the cleanup plan. Proceed only after agreement.
- Anything that repairs or disturbs the preserved HOME-PC FFmpeg condition **before Phase 7**.
- Merging to `master`, opening a PR, tagging, releasing, packaging, or running `release.py`.
- Force-push, history rewrite, branch deletion, `git reset --hard`, `git clean`, rebase, or stash
  manipulation on this branch.

**Never permitted, in any phase:**

- Removing Zone.Identifier / quarantine metadata; disabling or weakening Smart App Control,
  Defender, WDAC or any endpoint policy; adding exclusions; unblocking files; or otherwise routing
  around a security policy. An organisation's policy that refuses every legitimate build is a limit
  the application accepts.
- Uninstalling, downgrading or mutating **any** unrelated Python or FFmpeg installation. 3.13 /
  3.14 stay installed and untouched.
- Editing, moving, deleting, staging or committing
  `md-instructions/don't-delete/Codex-Investigation-Report-batch-launcher.md`.
- Committing FFmpeg binaries or archives to Git, or bundling them into a release package.
- Adding a `Co-Authored-By: Claude` (or any AI co-author) trailer — ADR 2026-07-07.

---

## 8. Binding contracts

These are the authoritative requirements. Where an implementation choice conflicts with one of
these, the contract wins.

### 8.1 Python contract

The full-feature project range under the **current** repository pins is:

> **Python `>= 3.11` and `< 3.13`.**

Preference order:

1. a compatible **Python 3.12**;
2. an already-good compatible **Python 3.11**;
3. **Python 3.13+ is NOT a fully healthy successful setup** under the current pins.

If only 3.13+ is present:

- attempt **user-scope acquisition** of a compatible Python 3.12;
- **do not uninstall or modify** 3.13 / 3.14 / any other installation;
- if a compatible Python cannot be obtained, **do not stamp or report the setup as fully healthy**;
- an **explicitly labelled degraded launch** may remain possible, but it **is not setup success**.

**Interpreter candidates must be structured argv sequences** (`list[list[str]]`, e.g.
`["py", "-3.12"]` and `[r"C:\Program Files\Python312\python.exe"]`). **Never infer argv boundaries
by splitting a string because it contains spaces.** These must work:

- `C:\Program Files\Python312\python.exe`
- `C:\Users\John Smith\AppData\Local\Programs\Python\Python312\python.exe`
- a repository checkout whose own path contains spaces

Selection must stay **deterministic** on a given machine — chosen by version predicate, never by
`PATH` order. The `py` launcher, WindowsApps redirector stubs, and a missing `py` must all degrade
cleanly. Derive the compatibility gate from **one** predicate (`_is_kokoro_compatible` already
exists) so a future 3.13 unlock is a single change.

### 8.2 Requirements / import validation contract

A requirements-state stamp may be written **only after**:

1. pip installation/reconciliation succeeds; **and**
2. required-import validation succeeds.

**`run_setup` and the drift/reconciliation path must obey the same invariant.** The correct
structural fix makes the stamp a *consequence* of a proof that no call site can bypass — not a
second `if` bolted next to the first.

The implementation must distinguish **four different things** and never let one stand in for
another:

| Concept | Means |
|---|---|
| requirements fingerprint | *which pins* this environment was reconciled against |
| distribution / module presence | a thing is on disk / discoverable |
| **actual importability** | the module really imports in the target interpreter |
| interpreter / SSL / Tk health | the interpreter runs, `ssl` works, Tcl/Tk initializes |

**Do not claim `importlib.find_spec` alone proves an "installed but non-importable" package
healthy.** `find_spec` answers *presence*, not *importability* — a package with a broken native
extension, a bad DLL dependency, or an incompatible ABI has a spec and still raises on import.

Fast-path design is **bounded**:

- **cheap steady-state assessment** on a healthy launch;
- **real import proof** after setup, reconciliation or repair;
- **measure before** placing any heavyweight import on every healthy launch. If a real-import probe
  of `REQUIRED_IMPORTS` costs more than a small, measured budget on a healthy machine, keep the
  cheap probe on the fast path and put the real proof behind the repair boundary — and record the
  measurement in the phase report rather than asserting the cost.

### 8.3 FFmpeg health contract

`shared/ffmpeg_health.py` remains the **ONE** health authority. **Do not create a competing
discovery or proof system.**

A usable FFmpeg dependency is:

> **one coherent `ffmpeg` + `ffprobe` sibling pair, where both executables actually execute
> successfully.**

- Normal system / package-managed candidates stay **pinned in place by their absolute proved
  paths**. This preserves the 2026-08-28 ADR.
- **Do NOT copy an already-good package-managed or system installation into `files/bin`.** The
  222 MB × 2 duplication, the silent-staleness hazard and the redistribution question that ADR
  identified all still stand.
- **Actual audio operations must not consume** either:
  - a coherent-but-**unproved** discovered pair, or
  - independently resolved bare `"ffmpeg"` + `"ffprobe"` names.

The existing 2026-08-28 ADR **deliberately** allowed those two narrower historical behaviours
(`have_ffmpeg()` meaning "a coherent pair is available", and the bare-name fallback for command
building). Changing them is a real contract change: the drop must record an **additive, superseding
ADR** at the closeout (§9 Phase 10) rather than silently contradicting the old record. The old
entry stays intact — the log is append-only.

### 8.4 Windows portable fallback — provenance (RESOLVED)

**Do NOT use the old floating BtbN `master-latest` URL.**

The reviewed fallback candidate is the **same Gyan build already used by the primary WinGet
`Gyan.FFmpeg` path**:

| Field | Value |
|---|---|
| Version | **9.0.1** |
| Upstream release | `GyanD/codexffmpeg` release tag **9.0.1** |
| Asset | `ffmpeg-9.0.1-full_build.zip` |
| Exact asset URL | `https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-full_build.zip` |
| Expected SHA-256 | `2E8E28AF97C2AE338CCEF92E36DA9B2A4CD21D0CAD9DDE093545606CB07F5B00` |

Independent provenance evidence already established by the review layer:

- the Gyan GitHub release reports the same SHA-256 digest;
- the Microsoft `winget-pkgs` `Gyan.FFmpeg` **9.0.1** manifest points to the **exact same asset
  URL** and the **exact same `InstallerSha256`**;
- FFmpeg's official download page lists Gyan as a Windows binary provider.

**Re-verification is mandatory before the production pin is written** (Phase 3). Confirm the
release tag, the asset filename, the asset URL and the digest still match, from both the Gyan
release and the `winget-pkgs` manifest. **If any fact no longer matches, STOP and report — do not
silently choose a different build.**

A GitHub release asset can technically be replaced upstream, so **the hard-coded hash is the
content-integrity authority**. A replacement with different bytes **MUST fail closed**: no
extraction, no promotion, no pin, an honest log line naming expected vs actual.

**Do not bundle this archive or its binaries in Git or in a release package during this drop.** The
fallback remains an on-demand runtime acquisition. Release-distribution compliance is Plan 9.

### 8.5 Portable installation / promotion design

**Do NOT swap or replace the entire generic `files/bin` directory.** It is a shared, general-purpose
location (`maintenance.py`'s `portable_binaries` asset points at it) and must not become
FFmpeg-owned.

Use a **dedicated FFmpeg-owned versioned destination**, conceptually:

```
files/bin/ffmpeg/9.0.1/bin/     <- final, versioned, previously nonexistent
files/runtime-data/ffmpeg-staging/   <- per-attempt staging (repo-owned, gitignored)
```

Both live under `files/` and are already gitignored (`.gitignore` lines 24 and 29).

**Required sequence, in order:**

1. download to **per-attempt staging** (never to the final destination);
2. **stream and hash**, verifying the expected SHA-256 **BEFORE extraction**;
3. **safe extraction** — reject path traversal, absolute paths and symlink entries; bound the
   uncompressed total; extract into a per-attempt subdirectory so a retry never merges with a
   partial;
4. require **sibling `ffmpeg.exe` + `ffprobe.exe`** in the extracted build — reuse
   `ffmpeg_health.pair_in()`, which already encodes the rule; missing either half is a failure, not
   a partial success;
5. **prove BOTH halves in staging** (`ffmpeg_health.prove_pair`) — this is also where a Smart App
   Control refusal surfaces, on a file that has not yet replaced anything;
6. **promote the COMPLETE FFmpeg directory with ONE same-volume directory rename** into a
   **previously nonexistent** versioned final destination;
7. **prove the promoted pair**;
8. **pin the promoted absolute pair** through `ffmpeg_health`;
9. **only after the new pin succeeds** may older repo-local fallback material be considered for
   cleanup.

**Invariants:**

- A failure or interruption at any step **leaves the previous usable pair untouched**.
- **Never perform two independent writes over live `ffmpeg.exe` / `ffprobe.exe`.**
- No success state, and no pin, before promotion **and** proof both succeed — the same
  proof-before-stamp invariant as §8.2.
- Stale staging from an earlier attempt is purged on entry; a verified staged archive already on
  disk makes a repeat attempt idempotent rather than re-downloading.

Candidate discovery may gain a **bounded, deterministic** repo-local search for the dedicated
versioned FFmpeg location. **Do not recursively scan arbitrary drives**, and do not make
`files/bin` broadly recursive.

### 8.6 User scope / portability

| Machine | Constraint |
|---|---|
| **HOME-PC** | Windows, Administrator available. The machine holding the preserved reproduction condition. Note: **no `py` launcher resolvable**, and `PATH` resolves 3.13 before 3.12. |
| **CSPW-PC** | Windows **Standard User, no admin**. Cannot write `C:\Program Files` or the registry. ~89 GB free — keep transient staging bounded. |
| **HOME-MacOS** | Apple Silicon M4 Pro, Homebrew at `/opt/homebrew` in user scope, no `sudo` needed. |

Containment priority, always:

1. an **existing proved** dependency;
2. **repo-contained / user-scope** repair;
3. machine-wide / elevated **only if genuinely unavoidable**.

- **WinGet user-scope behaviour must be explicit and tested** where supported — pass the scope
  rather than relying on a package default, and treat an elevation prompt or a scope error as
  "WinGet unavailable" and fall through to the repo-local route.
- **Do not uninstall any unrelated Python or FFmpeg installation.**
- **macOS does not need a newly invented portable-binary architecture in this drop.** But the plan
  must cover the **existing Homebrew-supported repair path** and must not ignore "existing venv +
  FFmpeg removed". Where the existing first-run Homebrew acquisition can safely be reused from the
  launch path, **reuse it** rather than leaving the existing-venv path structurally unable to
  repair. A **missing-Homebrew** case is handled **truthfully** — a clear, non-looping, honest
  limited-mode message, not a silent failure and not a false claim of success.
- Broad fresh-machine release certification remains **Plan 9**.

### 8.7 Failure UX

The current blocking-warning-before-GUI behaviour is **not** the desired steady contract.

**Repair first.**

- **Repair succeeds** → no warning at all; launch healthy.
- **Repair genuinely fails** →
  - show **one** truthful failure / limited-mode notice stating **what was attempted**;
  - **do not** claim setup succeeded;
  - **do not** tell the user merely to repeat the same failed action;
  - **allow a degraded GUI launch where useful** (Edge TTS remains usable without FFmpeg) unless a
    genuinely fatal prerequisite prevents GUI startup.
- **No indefinite pre-GUI modal loop.** A notice must never be able to hold the process before the
  GUI exists with nobody at the keyboard.

---

## 9. Phases

Ten bounded phases plus this one. The ordering is deliberate: the contract is written before the
code; the **destructive** fallback is made safe **before** it is made reachable; orchestration lands
only once every component it will call has been proved; and the real machine is spent last.

---

### PHASE 0 — maintenance branch + implementation drop *(this checkpoint)*

**Scope:** documentation and coordination only.
- Verify the baseline (`master` = `origin/master` = `e36ab7d…`, tracked tree clean).
- Create `maintenance/0.6.2-setup-self-healing` from that exact commit.
- Author this drop.
- Minimal `Handoff.md` current-state entry recording that this maintenance drop is active.

**Explicitly not in this phase:** any production Python, root launcher, test, requirements, config,
`release.py` or packaging change. No Plan 6.

**Gate:** tracked diff contains only the authorized planning/coordination files; `verify.py` doc
checks unaffected.
**Manual gate:** no. **Ends with:** commit + push + STOP + report.

---

### PHASE 1 — requirements-state invariant + Python selection ✅ COMPLETE

> **Outcome.** C2 closed by making `reconcile_requirements` the single owner of
> pip → real import proof → stamp (AST-guarded: it is the only caller of
> `record_requirements_state`). M1 closed by structured `list[list[str]]` candidates.
> Python contract enforced through one `is_full_feature_python` predicate (`>=3.11,<3.13`),
> kept distinct from Kokoro's `>=3.10` range so the project floor is not widened.
> L1a closed by making `SetupLog` open its file on first use rather than at import;
> L1b closed by redirecting `VENV_DIR`/`LOGS_DIR` in the three traced tests, plus a
> conftest guard that fails any test mutating the real stamp.
> **Measured, not asserted** (median of five, net of a 30 ms interpreter start):
> the presence probe of all seven costs **~32 ms**; a real import of the same seven
> costs **~6 763 ms**, of which **chatterbox alone is ~5 895 ms** (torch) — the other
> six total ~1 430 ms (`nltk` ~994, `edge_tts` ~500, `fitz` ~66, `pydub` ~26,
> `mutagen` ~14, `PIL` ~1).
>
> **Remediated after review.** Presence alone left a second hole: a module whose
> spec resolves but whose *import* raises stayed invisible behind a matching
> fingerprint. `prove_required_imports` now really imports the whole set, its
> success is recorded in `.venv/.import-proof.json`, and the record is
> re-established after `IMPORT_PROOF_MAX_AGE_DAYS`. Steady state is unchanged
> (~32 ms plus one small file read); the proof's ~6.8 s is paid at most once per
> window, and a break is caught within that window instead of never.
> **Gate:** 17 failed / 5102 passed / 57 skipped / 76 errors — failures, errors and
> skips all equal to the pre-existing baseline, with +41 passed from the new tests.
> Phase-1-attributable failures: **zero**.

**Fixes:** C2, M1, and the §4.4 stamp test weakness.

**Scope:**
- Make the requirements stamp structurally conditional on **both** gates (§8.2), in `run_setup`
  **and** the drift path, through a single owner that no call site can bypass.
- Replace the string-splitting interpreter candidates with **structured argv sequences** (§8.1).
- Implement the **3.12 → 3.11** full-feature preference explicitly; **no 3.13+ healthy-success
  fallback** — a 3.13-only machine attempts user-scope acquisition of 3.12 and, failing that, is
  **not** reported as healthy setup.
- Add **real conditional regression tests** — monkeypatch validation to fail and assert no stamp is
  written and failure is reported truthfully; assert spaced executable paths survive as one argv
  element; assert version-predicate selection rather than `PATH` order.
- Tighten `test_setup_records_the_stamp_only_after_packages_validate` from string-index ordering to
  a real behavioural assertion.
- **Identify and fix the unredirected stamp writer** (L1b). A test run must not be able to write the
  real `.venv/.requirements-state.json`. Find the actual culprit among the five modules named in
  §4.3 — do not guess — and add a guard that fails if the suite writes production environment state.
  This is not housekeeping: a suite that can write the real stamp can write a **false** one, which is
  the very invariant this phase exists to protect.

**Mutation proof:** demonstrate the new tests **fail against the pre-fix behaviour** (transient
red, in the phase report), then **the phase ends green**. Do not leave a permanently red checkpoint.

**Gate:** new + existing `test_bootstrap_requirements_state.py`, `test_bootstrap_python_*` green;
`verify.py` non-pytest rows PASS; pytest row per §10.2.
**Manual gate:** no. **Ends with:** commit + push + STOP + report.

---

### PHASE 2 — existing-venv liveness / launcher recovery ✅ COMPLETE

> **Outcome.** H2 closed. Venv health is no longer an existence test: bootstrap owns one
> authority, `assess_venv_health`, returning `VenvHealth` over four states — healthy,
> repairable, degraded, absent — from a **single** subprocess (~58 ms measured, against
> ~190 ms for `probe_capabilities`' four). The launchers know nothing about Python
> versions, ssl or Tk; Windows asks `--venv-check` (169.7 ms measured on the real healthy
> environment) and macOS reads the same verdict from the `--launch-only` call it already
> waited on. A venv cannot replace itself — Windows locks the running `python.exe` — so
> replacement is requested with `EXIT_VENV_REPAIR_REQUIRED = 3` and performed from a base
> interpreter via `--repair-venv`.
>
> **Scope held.** Recovery runs through `repair_venv`, never `run_setup`, so no ordinary
> launch can reach `ensure_ffmpeg` or the portable fallback a phase early — guarded
> structurally (AST) and behaviourally. Package problems are still repaired in place and
> never rebuild the environment.
>
> **Rollback safety.** `_create_validated_venv` used to `rmtree` the environment and only
> then try to build one; a failing `create_venv` left the user with nothing. The old
> environment is now renamed aside on the same volume and restored if the replacement
> fails or cannot import ssl, and discarded only once the replacement is proved.
>
> **Degraded is not a rebuild loop.** A 3.13-only machine with no obtainable 3.12, or a
> Tk-less environment with no better base, launches and says so rather than being
> destroyed on every run. A repair never asks for a second repair.
>
> **Also:** the import proof now carries the venv interpreter's identity (path, size,
> mtime), so a proof cannot survive the interpreter being replaced. The **Python** WinGet
> install is explicitly `--scope user` now that an ordinary repair can reach it; the
> FFmpeg WinGet command is deliberately untouched and stays with M5.
>
> **Gate:** 17 failed / 5168 passed / 57 skipped / 76 errors — failure and error rows
> identical to Phase 1's, +45 passed. Phase-2-attributable failures: **zero**.
>
> **Remediated after review.** The health model, handoff and ~169.7 ms check were accepted;
> four correctness gaps inside the replacement transaction were not. A Tk-broken environment
> passes `venv_is_valid` (interpreter + ssl), so it was never set aside and the recreate step
> destroyed it outright. The aside was discarded when the candidate's *capabilities* passed —
> before a single package had been installed or proved. The replace decision still used
> `_is_kokoro_compatible` (floor 3.10) while the health model used `is_full_feature_python`
> (floor 3.11), so a 3.10 environment could be called incompatible and then kept. And the
> final report read the *base* interpreter's version, which says nothing about the environment
> that ended up on disk.
>
> Now: replacement is an explicit `VenvReplacement` transaction owned by `repair_venv` and
> spanning create → capabilities → pip → real imports → resulting-venv health, committing only
> at the end; nothing destroys an environment it did not create; the replace decision goes
> through `assess_venv_health` so it cannot disagree with the health verdict; the outcome is
> read from the actual venv; and `recover_interrupted_replacement` resolves a half-finished
> repair deterministically — an aside with no venv is restored, and with both present the
> candidate wins only if it recorded a valid import proof. An aside is never blindly deleted.
> **Gate after remediation:** 17 failed / 5195 passed / 57 skipped / 76 errors, rows identical,
> +27 passed.
>
> **Remediated again, once more on review.** Interrupted-repair recovery treated the import
> proof as *the* commit condition. It is one of eight. A real window exists where pip
> succeeded, the imports were proved and the proof was written — and the process died before
> the final health check ever ran; recovery then deleted a working environment on the strength
> of a candidate nobody had confirmed could launch. Recovery now re-establishes **both** halves
> — a current interpreter-matching proof **and** the actual candidate passing
> `assess_venv_health(...).can_launch`, the same authority and the same meaning `repair_venv`
> uses immediately before `commit` — and takes the caller's `require_tk` context so an
> interrupted headless repair is not judged against a GUI standard. No new marker file was
> needed: the existing authorities are simply re-evaluated. **Final gate:** 17 failed /
> 5203 passed / 57 skipped / 76 errors, rows identical, +8 passed.

**Fixes:** H2, and the dead `_create_validated_venv` recovery branches.

**Scope:**
- The Windows launcher **may not treat `pythonw.exe` existence as health**. Decide liveness in one
  place — preferably move the decision into `bootstrap` so a single implementation owns it on both
  platforms — and update the `.bat` contract tests in the same commit.
- The macOS `.command` equivalent (`[ -x ".venv/bin/python" ]` is a stronger gate but hits the same
  wall afterwards).
- Make recovery **reachable from a launch** for: broken interpreter, missing/uninstalled base
  Python, missing `ssl`, broken or missing Tk, and a venv built on an incompatible (`>=3.13`)
  interpreter while a compatible one exists.
- **No manual `.venv` deletion** in any of those paths.
- Preserve the existing correct behaviour: reconciliation never deletes the environment; a Tk-less
  venv still finishes with a warning because the CLI works.

**Gate:** `test_first_run_contract.py` + new venv-state tests green; `verify.py` per §10.2.
**Manual gate:** no. **Ends with:** commit + push + STOP + report.

---

### PHASE 3 — safe Windows portable FFmpeg acquisition ✅ COMPLETE

> **Provenance re-verified first**, against both authorities, before the pin was written:
> the GyanD/codexffmpeg release for tag `9.0.1` (asset `ffmpeg-9.0.1-full_build.zip`,
> size `251427729`, digest `sha256:2e8e28af…5b00`, not draft/prerelease) and Microsoft's
> winget-pkgs `Gyan.FFmpeg` `9.0.1` manifest (same `InstallerUrl`, same `InstallerSha256`,
> and `ffmpeg-9.0.1-full_build\bin\{ffmpeg,ffprobe}.exe`). No mismatch. The asset was **not**
> downloaded for this check.
>
> **Two pins, kept apart.** The *source* pin (`shared/ffmpeg_portable.py`) says only *these
> bytes are the reviewed build*; the *runtime* pin (`ffmpeg_health`) says only *these sibling
> executables were actually executed*. Neither substitutes for the other, and `ensure_ready`
> still re-proves the active pair later.
>
> **The transaction:** stream to `…​.part` → hash while streaming → compare at EOF, extracting
> nothing unless it matches → validate every member (traversal, absolute, drive, UNC, symlink,
> size bounds) before writing any payload → require the sibling pair via `pair_in` in the
> deterministic `ffmpeg-9.0.1-full_build/bin` → **prove both halves in staging** → promote the
> complete build with **one** `os.replace` into `files/bin/ffmpeg/9.0.1` → prove again at the
> final paths → pin via the new `ffmpeg_health.adopt_pair`.
>
> **`adopt_pair` exists because `establish` was the wrong primitive**: it is a discovery loop
> that writes `pair=None` when nothing proves, so handing it one failing candidate would have
> erased a working pin. `adopt_pair` proves one coherent candidate itself, pins only on
> success, and on failure records the rejection **without** touching the incumbent.
>
> **Interruption:** a promoted-but-unpinned build is re-proved and adopted without
> re-downloading; an existing final directory is never overwritten or merged into; a verified
> staged archive is reused (re-hashed, never trusted by name); a stale extraction never merges
> into a retry.
>
> **Discovery** gained one bounded level: `files/bin/ffmpeg/<version>/bin`, sorted, no walking,
> no execution. **Not reachable from any ordinary launch** — asserted over the call graph for
> `--venv-check`, `--launch-only`, `repair_venv` and `--repair-venv`. Phase 5 owns that wiring.
>
> **Gate:** 17 failed / 5283 passed / 57 skipped / 76 errors — rows identical to Phase 2's,
> +80 passed. Phase-3-attributable failures: **zero**. Nothing was downloaded or installed;
> HOME-PC still has no FFmpeg.
>
> **Remediated after review**, at the persistence/retry boundary. `save_state` swallowed
> `OSError` and returned nothing, so `adopt_pair` proved a pair, failed to record it, and
> reported it as pinned anyway — a false success that Phase 4 would then have taught consumers
> to trust. It now writes the complete JSON to a uniquely-named sibling, `fsync`s, and swaps it
> in with one `os.replace`, returning a bool; `adopt_pair` returns an `Adoption`
> (`pinned` / `not-proved` / `not-persisted` / `incoherent`) so *proved* and *pinned* can no
> longer be confused, and `establish` is truthful the same way. Separately, an incomplete or
> non-running installed `9.0.1` was a permanent dead end — `promote` refused the occupied
> destination forever, clearable only by hand. It now moves the unusable occupant aside once a
> fresh candidate has been hash-verified, extracted and **proved**, restores it if the install
> fails, and discards it only on success. A build that is promoted and proved but cannot be
> recorded is left in place for the next run to adopt without re-downloading.
> **Gate after remediation:** 17 failed / 5304 passed / 57 skipped / 76 errors, rows identical,
> +21 passed.

**Fixes:** H1. **Deliberately still NOT reachable from a normal launch at phase end.**

**Scope:**
- **Re-verify the §8.4 provenance facts first.** Tag, asset name, URL and SHA-256, from both the
  Gyan release and the `winget-pkgs` manifest. **Any mismatch → STOP and report.**
- Write the exact Gyan **9.0.1** pin (§8.4). The floating `latest` / `master-latest` URL must not
  survive anywhere in the codebase.
- Implement the full §8.5 sequence: staging → stream+hash before extraction → safe extraction →
  sibling-pair requirement → prove in staging → single same-volume directory rename into the
  previously nonexistent versioned destination → prove promoted → pin promoted → only then consider
  older repo-local material for cleanup.
- Tests: download failure, **hash mismatch fails closed**, truncated archive, traversal/symlink/
  absolute-path member rejected, archive missing `ffprobe.exe`, interrupted promotion,
  **last-known-good preserved across a failed replacement**, idempotent retry, successful promotion
  then re-proof.
- **No live download in the automated suite** — a local fixture archive and a stubbed fetcher. The
  real network path is exercised in Phase 7.

**Gate:** the new acquisition module's tests green; `verify.py` per §10.2. Confirm by inspection
that no normal launch path reaches the new code yet.
**Manual gate:** no — but the phase **may not open** until the §8.4 re-verification passes.
**Ends with:** commit + push + STOP + report (including the re-verification result).

---

### PHASE 4 — runtime FFmpeg trust closure ✅ COMPLETE

> **The invariant:** *observation is not permission.* Finding two coherent siblings on disk is a
> fact about the filesystem; being allowed to execute them is a fact about `ffmpeg_health` having
> actually run both halves. Phase 4 stops the first from being reported as the second.
>
> **The central API is fail-closed, so consumers inherit the boundary.** `ffmpeg_cmd()` and
> `ffprobe_cmd()` resolve **only** `ffmpeg_health.pinned_pair()` and raise `FFmpegUnavailable`
> otherwise — no discovery fallback, no bare `"ffmpeg"`/`"ffprobe"`, and therefore no way for the
> two halves to come from different installations. That was chosen over scattering ~20 duplicated
> gates across `m4b_maker`, `m4b_probe`, `mp3_tool`, `metadata`, `chatterbox_synth` and
> `epub2tts_edge`: a gate can be forgotten at the next call site, a raising accessor cannot.
> `have_ffmpeg()` is now exactly `verified_ffmpeg()`; the observation half moved to the separate,
> honestly-named `discovered_ffmpeg()`, which is used for wording and nothing else.
>
> **pydub was the one route with no gate in front of it.** Left unconfigured it shells out to
> whatever `PATH` resolves. `configure_pydub()` now *always* sets `converter` / `ffmpeg` /
> `ffprobe` and `pydub_utils.get_prober_name`, pointing them at `UNVERIFIED_PYDUB_SENTINEL`
> (`<no-verified-ffmpeg>`) when nothing is pinned, so an unverified machine fails visibly instead
> of silently running an unproved binary. `refresh()` clears the configured flag, so a later pin
> replaces the sentinel.
>
> **`status_line()` is still the single place the wording lives**, now with three states, and a
> test proves that drawing it executes nothing.
>
> **Red proof** (`files/dev-work/phase4/red-proof.txt`): against `fd6c8b2`, five invariants break —
> unproved pair reported runtime-ready, unproved pair exposed as executable, the MP3 Tool gate
> authorising it, `ffmpeg_cmd()`/`ffprobe_cmd()` returning the bare names, and pydub defaulting to
> a bare `PATH` ffmpeg. All six hold against this tree. The sixth is labelled `[control]` because
> it is a positive invariant that also passes pre-fix.
>
> **The two old-contract tests were rewritten, not deleted**, so the change of contract is legible:
> `test_an_unproven_coherent_pair_is_not_runtime_ready` and
> `test_there_is_no_bare_name_fallback_for_command_building`. `test_ffmpeg_runtime_trust.py` adds
> 26 tests including a structural inventory (no bare-name argv head, no runtime `shutil.which`)
> and AST assertions that the headline gates ask only `verified_ffmpeg`.
>
> **Two allowlist entries, each with a companion proof.** `epub2tts_edge.py` builds
> `["ffmpeg", …]` lists but always routes them through `_run_ffmpeg`, which rewrites `argv[0]`
> via `ffmpeg_cmd()` — two tests prove the rewrite exists and inherits the refusal.
> `bootstrap.py`'s `shutil.which("ffmpeg")` is setup-layer *detection*, not runtime execution.
>
> **`shared/ffmpeg_portable.py` was not touched.** The 2026-08-28 ADR is intact; the **additive
> superseding ADR is owed at Phase 10**, not now.
>
> **Gate:** 17 failed / 5335 passed / 57 skipped / 76 errors — the 93 FAILED/ERROR rows are
> byte-identical to Phase 3's, +31 passed. Phase-4-attributable failures: **zero**. Nothing was
> downloaded or installed; HOME-PC still has no FFmpeg.
>
> **Remediated after review**, at the one place the closure was not cross-platform. The
> unpinned pydub target was the string `"<no-verified-ffmpeg>"` — decorative, and mechanically
> still a **bare command token**. Process creation treats an argv[0] with no path separator as a
> *command name* and searches PATH for it, so that value closed the escape on Windows **only by
> accident**: `<` and `>` are illegal in NTFS filenames, so the lookup can never match. On
> macOS — which this project supports — they are ordinary filename characters, a PATH directory
> may legally hold an executable named exactly that, and pydub would have run it. One platform's
> filename rules are not an invariant.
>
> `UNVERIFIED_PYDUB_SENTINEL` is now `str(Path(__file__).resolve().parent)` — this package's own
> absolute directory. Absolute, so no PATH search occurs on any platform; a **directory**, so no
> process API can execute it. A nonexistent absolute file would also have closed the PATH route,
> but "nothing executes a directory" is a property of the operating system while "this file does
> not exist" is a property of the filesystem right now, which anyone can change by creating the
> file. Nothing is written to disk and no fake executable exists; the directory is necessarily
> present because the module was imported from it.
>
> The approved model is untouched: the same four settings
> (`converter` / `ffmpeg` / `ffprobe` / `get_prober_name`) are still always set, pinned
> behaviour is unchanged, and `refresh()` still replaces the fail-closed target with a real pin.
>
> **Red proof:** four of the five new regressions fail against `c96d566` — the sentinel is not
> absolute, is not a directory, the prober name is not absolute, and an unverified pydub run is
> handed a bare token. The fifth asserts pinned behaviour is *not* regressed and passes on both
> trees, so it is reported as such rather than as red evidence. The test asserts the
> platform-independent property; it does **not** create a `<`/`>` filename, which the Windows
> development machine cannot represent.
> **Gate after remediation:** 17 failed / 5340 passed / 57 skipped / 76 errors, the 93 rows
> byte-identical, +5 passed — exactly the five new tests.

**Fixes:** H3, M2.

**Scope:**
- Actual audio consumers require a **health-proved** pair. Move the production gates from
  `have_ffmpeg()` to `verified_ffmpeg()` at `m4b_converter.py:650`, `m4b_converter.py:963` and
  `mp3_tool.py:81`.
- **No coherent-but-unproved runtime execution**; **no independent bare-name pair fallback**. If a
  degenerate fallback is retained for command *building*, it must not be able to resolve the two
  halves from different installations.
- `shared/ffmpeg_health.py` remains the sole authority — no second discovery path.
- Update the two tests that currently bless the old behaviour
  (`test_have_ffmpeg_is_true_for_an_unproven_but_coherent_pair`,
  `test_the_bare_name_fallback_survives_for_command_building`) to the new contract, and note in the
  phase report that the **additive superseding ADR** for the 2026-08-28 entry is owed at Phase 10.
- Keep `status_line()` as the single place the found/verified distinction is worded.

**Gate:** `test_ffmpeg_health.py` (all ~70) + consumer tests green; `verify.py` per §10.2.
**Manual gate:** no. **Ends with:** commit + push + STOP + report.

---

### PHASE 5 — `Setup_and_Run` self-healing orchestration ✅ COMPLETE

> **The components finally became reachable from a double-click.** Phases 1-4 built an
> environment assessment, an in-place requirements repair, a hash-verified repo-local FFmpeg
> build and a fail-closed runtime. None of it was on the path a person actually takes.
>
> **C1.** `ensure_ffmpeg_ready_for_launch()` detected a dead FFmpeg, opened a modal, and
> launched anyway; the only provisioning route sat behind `run_setup`, which an existing
> installation never reaches. It now **repairs**, behind the existing progress window, and
> returns a result instead of a warning.
>
> **The repair is one transactional orchestration, `repair_ffmpeg`**, shared by setup and every
> launch so the two cannot drift. Containment order (§8.6): what is already here → a user-scope
> package-manager install → the app's own verified build. Crucially the fallback moved **out of**
> `_install_ffmpeg`: while it lived inside, a winget run that exited 0 and left nothing provable
> ended the repair, because the fallback had already been skipped inside the function that had
> just returned `True`. An installer's exit code now means only *the command appeared to
> complete*; `ffmpeg_health` alone decides ready.
>
> **After a portable success, discovery is deliberately not re-run.** `ffmpeg_portable.acquire`
> already proved the pair at its final paths and pinned it atomically; `establish` afterwards
> could pin a different installation, so the orchestration confirms *that* pair.
>
> **M5.** The Gyan.FFmpeg WinGet call now passes `--scope user` explicitly, like the Python one
> already did. A scope or elevation refusal is treated as *this route is unavailable* and falls
> through. Nothing ever asks for machine scope. An AST inventory asserts **every** production
> `winget install` names user scope, so a new call site cannot omit it.
>
> **M4.** macOS existing-venv launches reach the existing Homebrew acquisition. Homebrew is
> never *installed* from a launch repair — that stays a first-run decision the `.command` makes
> with a person watching — and a Mac without Homebrew gets a truthful, non-looping notice naming
> Homebrew rather than a silent failure. `brew` exiting 0 is not success: only a proved, pinned
> pair is.
>
> **M3 / §8.7.** Repair first, then launch, then at most **one** notice. Requirements, FFmpeg and
> Kokoro could each open a pre-GUI modal — three blocking dialogs in front of a person who had
> double-clicked and walked away, with no window behind them. They are collected and shown once,
> after `launch_gui` confirms the GUI started, and the notice names only the routes actually
> attempted. Genuinely fatal environment failures still report before the GUI, because there is
> no GUI to put them behind. `describe_failure()` no longer tells anyone to open the launcher
> again; a parametrised test asserts no active module in `scripts/Universal/` does.
>
> **Minimum scope held.** AST proofs that no FFmpeg path reaches `repair_venv`/`create_venv`, that
> the requirements paths do not either, and that no launch routes through `run_setup`.
> `--venv-check` and `repair_venv` remain sealed off from acquisition — Phase 3's seal narrowed,
> it did not come off.
>
> **Test isolation.** A new autouse conftest guard makes a real `winget`/`brew` run and a real
> `urlopen` impossible, and refuses `_download_portable_ffmpeg_windows` unless a test stubs it.
> That was not theoretical: an intermediate run created `files/runtime-data/ffmpeg-staging/9.0.1`
> (empty — the download was refused). It was removed and the seam closed.
>
> **Red proof:** against `1e788db`, five invariants break — no repair on a normal launch (C1),
> warning before GUI (M3), no brew from an existing macOS venv (M4), no `--scope user` on the
> Gyan.FFmpeg argv (M5), and a WinGet exit 0 that proves nothing never reaching the fallback. All
> hold on this tree. The sixth is a `[control]` that passes both sides.
>
> **Gate:** 17 failed / 5433 passed / 57 skipped / 76 errors — the 93 FAILED/ERROR rows identical
> to Phase 4's, +93 passed. Phase-5-attributable failures: **zero**. Nothing was installed or
> downloaded; the HOME-PC no-FFmpeg condition is untouched and still reserved for Phase 7.

**Fixes:** C1, M3, M4, M5. This is where user-visible behaviour changes.

**Scope:**
- Implement the state machine: **ASSESS → REPAIR → PROVE → STAMP → LAUNCH**, entered identically by
  `--launch-only` and by a bare `bootstrap.py`.
- **The missing/broken-FFmpeg launch path reaches provisioning.** WinGet first (stable package),
  then the Phase-3 repo-local fallback.
- **Minimum-scope repair:** a missing FFmpeg costs an FFmpeg install, never a venv rebuild; changed
  pins cost one `pip install -r`, never a rebuild.
- **Explicit user-scope package-manager behaviour** (§8.6, M5) for both WinGet calls; treat
  elevation refusal as "unavailable" and fall through.
- **Corrected failure UX** (§8.7): repair first; no warning when repair succeeds; one truthful
  notice naming what was attempted when it genuinely fails; degraded launch preserved; **no
  indefinite pre-GUI modal**. Rewrite every *"Run Setup_and_Run again"* string, including
  `ffmpeg_health.describe_failure()`, `m4b_converter.py:650` and `:963`.
- **macOS orchestration** structurally (§8.6): the existing Homebrew acquisition reachable from the
  existing-venv path; missing Homebrew handled truthfully.
- Address **L1a** (test runs must not write the production setup log) if it is genuinely small scope
  while the logging surface is already open; otherwise record it and let Phase 6 row 17 catch it.
  **L1b** — the unredirected requirements-stamp writer — belongs to **Phase 1**, not here.

**Do NOT consume the real HOME-PC broken state in this phase.** Prove the orchestration against
mocked/staged environments only.

**Gate:** the full targeted suite for every module touched; `verify.py` per §10.2.
**Manual gate:** no (Phase 7 owns it). **Ends with:** commit + push + STOP + report.

---

### PHASE 6 — automated regression / hardening matrix ✅ COMPLETE

> **An audit first, then only the gaps.** Rows 1-5, 7-9, 11-15 and most of 6, 10 and 16 were
> already covered — strongly — by what Phases 1-5 left behind, and re-testing them would have
> inflated the count without improving the gate. Four genuine gaps were found and filled: a stale
> pin whose build **moved** (bytes intact, path changed — a WinGet upgrade), a **repository** path
> containing spaces (the interpreter side was covered, the repo side was not), macOS repair
> reached through the **normal launch path** rather than a direct `repair_ffmpeg` call, and the
> production-state guard's blind spots.
>
> **Row 17 — the guard was incomplete, and it had already missed something.** It watched the
> requirements stamp, the import proof and the log directory. Phases 3-5 added three more ways to
> write production state — the runtime pin, `files/bin`, the staging tree — and none was watched.
> That is how an intermediate Phase-5 run created `files/runtime-data/ffmpeg-staging/9.0.1`
> without the suite noticing; it was found by hand afterwards. All three are guarded now, the
> fingerprint **recurses** (a build three directories down cannot hide behind an unchanged
> `files/bin`), absence and reappearance are both detected, and the five small paths are checked
> per test so a violation names its culprit while the 79-file log tree stays session-scoped for
> cost.
>
> **Row 18 — L2 is fixed, not avoided.** Diagnosed first: `tk_gate._reset_root` destroys widgets,
> cancels `after` callbacks and unbinds events, but a `tkinter.Variable` is not owned by the
> widget that used it. Measured at `b59f562` over three UI modules, **90 variables were still
> armed** at session end, each holding the live interpreter and each carrying a `__del__` that
> calls into Tcl — and because they sit in reference cycles it is the *cyclic* collector that
> finalises them, on whichever thread happens to trigger it. Phase 1 reduced allocation churn so
> that landed badly less often; that is a probability, not an invariant.
> `tk_gate.finalise_tk_objects` now runs at every module boundary, on the main thread (it raises
> if called from anywhere else), does what each finaliser would have done, and then clears the
> attribute that arms it — `Variable._tk`, `Image.name`. Afterwards there is no finaliser that
> *can* reach Tcl, wherever it later runs. **Measured: 90 → 0**, same 262 tests passing on both
> sides. No timeout was raised, no GC disabled, no test serialised, nothing skipped. The shared
> single-interpreter rule is untouched and asserted.
>
> **Structural hardening.** The drop's named remaining weakness —
> `test_a_winget_install_is_accepted_without_waiting_for_path`, which sliced `bootstrap.py`
> between two `def` markers — is AST now, along with five sibling guards in the same two modules.
> The shared helper is `files/tests/source_probe.py`, and it has its own self-checks against
> synthetic code, because a structural guard that cannot fail reads as coverage while testing
> nothing. A meta-test forbids `.index("def …")` in the modules this phase touched. The `.bat`
> guards are deliberately left textual: a batch file has no AST and its ordering really is
> positional.
>
> **My own new code had a defect, and the broad gate caught it.** The first version of the Tk
> boundary used `isinstance` over `gc.get_objects()`; a dead `weakref.proxy` raises
> `ReferenceError` on `isinstance`, which turned 1028 unrelated tests into setup errors. It now
> filters on `type(obj)`, which never dereferences anything, and tolerates the fake `tkinter`
> modules some fixtures inject.
>
> **Gate.** Targeted suites (15 modules incl. the three new ones): **711 passed, 0 failed**. Broad
> slice — the full suite minus the 93 classified baseline nodes, deselected by exact node ID and
> recorded in `files/dev-work/phase6/excluded-nodes.txt`: **5479 passed, 57 skipped, 0 failed, 0
> errors**. Full run: 17 failed / 5479 passed / 57 skipped / 76 errors, the **93 FAILED/ERROR
> node IDs byte-identical** to Phase 5's, +46 passed. A = 76 `require_ffmpeg` errors, B = 16
> Chatterbox failures, C = 1 protected-report boundary, **D = 0**. `verify.py` deps/docs/docnames/
> config PASS; the pytest row is the standing HOME-PC red baseline.
>
> **Production state re-proved mechanically**, not asserted: `snapshot.py` before and `compare.py`
> after every gate — requirements stamp, import proof, log tree, `ffmpeg-state.json`, `files/bin`,
> `ffmpeg-staging`, `.venv.replaced*`, `where ffmpeg`/`ffprobe`, the WinGet inventory, the PATH
> hash and both protected untracked files: **16 keys, 0 differences**. No production code was
> changed in this phase.


**Scope:** complete the matrix. **All required Windows scenarios; structural/mockable macOS
scenarios.** At minimum:

| # | Scenario |
|---|---|
| 1 | download failure |
| 2 | hash mismatch → fails closed |
| 3 | archive missing `ffprobe` |
| 4 | broken / unexecutable FFmpeg binary |
| 5 | mismatched candidates from different directories |
| 6 | stale pin (binary changed, moved or deleted) |
| 7 | requirements validation failure → no stamp, retried next launch |
| 8 | broken venv (interpreter, base, `ssl`, Tk) |
| 9 | multiple Python versions installed, incl. 3.13-only and 3.13-before-3.12 on `PATH` |
| 10 | spaced executable paths **and** spaced repository path |
| 11 | WinGet unavailable → fallback |
| 12 | no-admin semantics where mockable |
| 13 | interrupted staging and interrupted promotion |
| 14 | last-known-good preservation across a failed replacement |
| 15 | successful repair → **second launch is a no-op fast path** |
| 16 | macOS: existing venv + FFmpeg removed, Homebrew present and Homebrew absent (mocked) |
| 17 | **test isolation** — a full suite run writes **no** production state: not the real `.venv/.requirements-state.json`, not `.venv/.import-proof.json`, not `files/runtime-data/logs/setup_<date>.log`, not `files/runtime-data/ffmpeg-state.json`, not `files/bin` (L1) |
| 18 | **Tk finalisation on worker threads (L2, pre-existing)** — a cyclic collection landing on a non-main thread finalises a leftover `tkinter.Variable`; `Variable.__del__` calls into Tcl and stalls off the main thread, timing out bounded waits in unrelated threading tests. Latent in the suite and **not** introduced by this drop: Phase 1 surfaced it by changing fixture allocation and closed it by reverting to session-scoped isolation, changing **no** production or test behaviour for it. Needs a real fix — deterministic main-thread finalisation of Tk objects between modules — not a widened timeout. |

Also tighten the remaining substring-slicing structural test (§4.4) to AST.

**Preserve the real HOME-PC missing-FFmpeg acceptance condition** — this phase is mocked and
staged only.

**Gate — read this carefully.** **Do NOT require a false full `verify.py` PASS here.** The
preserved real environment still makes FFmpeg-dependent tests red on this machine. Require instead:
- the strongest **targeted** gate for every module this drop touched, green;
- the **FFmpeg-independent** and **mocked** suites, green;
- `verify.py` deps / docs / docnames / config rows **PASS**;
- and the pytest row recorded **truthfully**, with each known environmental failure row named and
  attributed (see §10.2).

**Manual gate:** no. **Ends with:** commit + push + STOP + report.

---

### PHASE 7 — real HOME-PC self-repair acceptance ✅ COMPLETE

> **The preserved condition has been spent, and it bought exactly what it was kept for.** The
> maintainer double-clicked `Setup_and_Run-audiobook-creation-tool.bat` from Explorer on
> 2026-09-04. The first run detected that no usable pair existed, installed **Gyan.FFmpeg in
> user scope via WinGet**, checked the package directory **directly rather than waiting for
> PATH**, proved the pair, pinned it, and launched. The app has run on this machine ever since
> against `…\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-9.0.1-full_build\bin\{ffmpeg,ffprobe}.exe`.
>
> **Minimum scope held.** `.venv` stayed Python 3.12.10, no `.venv.replaced*` was created, the
> requirements stamp is byte-identical, and no pip reconciliation ran. The import proof was
> re-established — an import re-proof, recording the *same* `requirements_sha256` as the
> untouched stamp, not an install. `files/bin` and the staging tree were never created: the
> portable fallback was correctly never reached. The second double-click re-proved the active
> pin and launched; no reinstall, no download, no repair loop.
>
> **The post-repair gate did not close on the first attempt, and that was worth more than a
> clean pass.** Two defects that the *absence* of FFmpeg had been hiding turned red the moment a
> real pair existed. Both were test-only; no production module was implicated, and the
> generated Unicode book plus the production probe were proved sound against the real pair
> before anything was touched.
>
> **Defect 1 — a `pytestmark` that could not be opted out of.** `test_m4b_probe_encoding` applied
> the sandbox `pinned_ffmpeg` pair to its whole module, including the three tests whose entire
> purpose is to run a *real* ffmpeg against a *real* generated book. They were handed a stub text
> file. The sandbox is now opted into one test at a time — fourteen command-building tests that
> genuinely need a pinned pair, because `probe_source` builds its argv from `ffprobe_cmd()`
> *before* it consults an injected runner; five pure payload/AST tests need nothing; the three
> media tests get the real pair.
>
> **Defect 2 — pydub's configuration is process-wide, and nothing gave it back.**
> `configure_pydub()` writes absolute paths into `pydub.AudioSegment` and rebinds
> `pydub.utils.get_prober_name`. Those are a third-party package's module globals: not something
> `monkeypatch` ever patched, and not something `refresh()` rewrites — refresh clears
> `ffmpeg_utils`' own caches and lowers `_pydub_configured`, leaving the rewrite to the next
> `configure_pydub()` call, which a consumer like `kokoro_synth` never makes. So a test that
> pinned a sandbox pair left pydub pointing inside its own `tmp_path`, which pytest then deleted,
> and two `test_kokoro_timing_wiring` tests inherited it. An autouse guard in `conftest.py` now
> snapshots and restores those four settings around every test, treating **absence as a value**
> (`AudioSegment.ffprobe` does not exist until `configure_pydub()` creates it, so a guard that
> only reassigns would leave it behind).
>
> **A correction worth recording.** The remediation brief proposed that the leak was a stale
> `ffmpeg_utils` cache caused by `pinned_ffmpeg` refreshing before `monkeypatch` restored. That
> mechanism was tested and **does not exist**: `refresh()` only clears its lru_caches, so the next
> resolution happens lazily and correctly after restoration. The reproduction asserts that
> explicitly, and that assertion passes at `bec7050` as well as after the fix. The real leak was
> pydub's, and the fix follows the evidence rather than the hypothesis.
>
> **Red proof against `bec7050`, both defects.** Seven of the ten new permanent regressions fail
> on the pre-fix tree and pass after. Final gate: **two consecutive full runs, each 1 failed /
> 5630 passed / 14 skipped / 0 errors**, the single failure being the known local-only
> `test_plan3_boundaries` row caused by the protected untracked maintainer report — proved green
> at 129/129 from a clean `git archive` tree. All 76 Category-A missing-FFmpeg errors are gone,
> Category B did not reproduce, Category D is zero, and the 23 `ttk/winTheme` transients did not
> recur in either run. Production state was unchanged across every gate, 21 keys, 0 differences.

**This is the first phase allowed to consume the preserved broken condition.**

**Required proof — maintainer's normal double-click, not a scripted invocation:**

1. existing `.venv` + no FFmpeg → `Setup_and_Run` **detects** → **provisions** → **proves** →
   **pins** → **launches healthy**;
2. then a **second** normal launcher run → **no reinstall, no repair loop, healthy fast launch**.

**Artificial failure scenarios** — corrupt staging, forced WinGet-unavailable fallback, interrupted
promotion — **should be driven by the agent through controlled test/evidence environments wherever
possible, not manually offloaded to the maintainer.**

**After the real FFmpeg repair, run the full Windows automated gate.**

Because the preserved untracked maintainer report poisons one strict repository-boundary test
locally (`test_plan3_boundaries.py` asserts `md-instructions/don't-delete/` with strict set
equality), also provide a **clean repo-local snapshot/gate under `files/dev-work/`** if needed.
**Never delete or move the maintainer report merely to make the suite green.**

**Gate:** the real acceptance run above, plus the full Windows automated gate post-repair, recorded
in a manual test log under `files/test-logs/` per `AI-WORKSPACE.md`.
**Manual gate:** **YES — maintainer runs the double-click and approves.** ✅ passed 2026-09-04.
**Ends with:** commit + push + STOP + report. ✅ **Phase 8 NOT STARTED.**

---

### PHASE 8 — HOME-MacOS targeted validation

**Not** full Plan-9 fresh-machine certification. Prove at minimum:

- an existing compatible venv;
- FFmpeg removed / missing;
- a normal `.command` double-click **repairs** through the supported macOS path;
- Python 3.12 and Tk remain healthy;
- a second normal launch is healthy and a no-op;
- **no manual `.venv` deletion** anywhere in the recovery.

**Manual gate:** **YES — maintainer runs it on HOME-MacOS and approves.**
**Ends with:** commit + push + STOP + report.

---

### PHASE 9 — CSPW-PC non-admin targeted validation

Prove the new repair contract under the **actual Standard User restriction**, with **no admin
installation** where user-scope or repo-local repair is available.

**Manual / remote-agent gate as appropriate.**
**Ends with:** commit + push + STOP + report.

---

### PHASE 10 — maintenance closeout

**Scope:**
- All approved target-machine evidence recorded **truthfully**, waivers named as waivers.
- `Changelog.md` / `Briefing.md` / `Handoff.md` / `Decisions.md` updated **only as appropriate** —
  no `[0.6.2]` release heading.
- **Record the superseding FFmpeg / self-healing ADR** (§8.3): additive, newest-on-top, naming what
  it supersedes in the 2026-08-28 entry and why, leaving that entry intact.
- **Retire this drop** — delete `md-instructions/pre-plan-6-setup-self-healing.md` (§14).
- Version remains **0.6.2**. **No tag, no release, no package, no `release.py`.**
- Final clean-tree automated gate.
- **STOP.**

**Manual gate:** maintainer sign-off on the closeout records.

---

### After Phase 10 — NOT silently chained

1. an independent **READ-ONLY integration-readiness review**;
2. **PR creation and review only after READY**;
3. **merge only after explicit maintainer authorization.**

**Plan 6 may begin only after this maintenance work is integrated into `master`.**

---

## 10. Verification rules

### 10.1 Order

`pytest` → the `verify.py` gate → a manual log (Phases 7–9 only).
`python scripts/verify.py` must print `RESULT: PASS` for its **deps / docs / docnames / config**
rows at every phase.

### 10.2 The pytest row and the preserved environment — report honestly

This machine has **no usable FFmpeg pair by design** until Phase 7, and holds the preserved
untracked maintainer report. The known-red baseline on `master` at `e36ab7d`, recorded in the PR #8
commit body, is:

> **17 failed / 5061 passed / 57 skipped / 76 errors** — from this machine's absent FFmpeg plus the
> preserved untracked report.

Every phase report must state the pytest numbers and **attribute each failure row** to either
(a) the preserved environmental condition, (b) a pre-existing known failure, or (c) this phase's
work. Category (c) must be zero at a phase gate. **Never present an environmental red as a pass,
and never present a pass as clean if it is not.**

### 10.3 Mutation proof

Where practical, each phase demonstrates that its new regression tests **fail against the pre-fix
behaviour** — transiently, inside the phase, shown in the report. **Do not create a permanently red
checkpoint merely to "write failing tests first."** Every phase **ends green** on its own gate.

### 10.4 Boundary tests and the maintainer report

`test_plan3_boundaries.py` asserts `md-instructions/don't-delete/` contents with strict set
equality and therefore fails **locally only** because of the preserved untracked report. It is
**not** branch content and cannot affect a clean checkout. Record it as a known local row. If a
clean gate is genuinely needed, take a **repo-local snapshot under `files/dev-work/`**. **Never
delete, move or stage the maintainer report to go green.**

### 10.5 Test quality

- **AST, never substrings.** No boundary or structural guard may assert on `body.index(...)`,
  string slicing between markers, or substring presence as a proxy for behaviour.
- Every test asserts **behaviour**, and must be able to fail on the defect it names.
- Tests stay fast, deterministic, offline, and free of machine-specific state; fixtures live in
  `files/test-files/`, scratch in `files/dev-work/`.
- **No live network download in the automated suite.**

### 10.6 Containment

All working artifacts stay inside the repository, under `files/dev-work/<phase>/` (gitignored).
External workspaces require the §7 permission gate. Never `git add files/` broadly; never
force-add ignored developer material.

---

## 11. Manual gates

| Phase | Manual gate | Who |
|---|---|---|
| 0–6 | none — automated only | — |
| **7** | **required** — HOME-PC double-click self-repair, then a second clean launch | maintainer |
| **8** | **required** — HOME-MacOS `.command` repair + second launch | maintainer |
| **9** | **required** — CSPW-PC Standard User repair without admin | maintainer / remote agent |
| **10** | closeout records sign-off | maintainer |

Manual logs live in `files/test-logs/` (gitignored, kept between sessions), named by version and
purpose, using the `[ ]` / `[x]` / `[~]` / `[-]` markers and an Issues Found table.

---

## 12. Per-phase STOP / report requirement

**Every implementation phase must:**

1. **start** by confirming the expected branch, the expected parent SHA, and a clean tracked tree;
2. make **only that phase's bounded changes**;
3. demonstrate the regression tests would **fail against the pre-fix behaviour** where practical;
4. end with the **strongest applicable green gate** for that phase;
5. **commit and push only when that phase's specified gate is satisfied**;
6. **STOP**;
7. return the standard summary for maintainer / ChatGPT review;
8. **never chain into the next phase.**

**Standard phase summary:**

- phase number and name;
- before / after SHAs, branch, exact files changed;
- what was fixed, in terms of the §4.3 defect IDs;
- mutation proof — which tests failed against pre-fix behaviour, and how that was shown;
- gate result: targeted suites, `verify.py` rows, pytest numbers with **every failure row
  attributed** per §10.2;
- what was deliberately **not** done, and why;
- confirmation that the preserved HOME-PC condition is intact (Phases 1–6);
- explicit **STOP**.

---

## 13. Definition of Done — the whole drop

- [ ] `Setup_and_Run` is idempotent and self-healing on Windows and macOS: healthy launches fast;
      broken detects, repairs the minimum prerequisite, proves, stamps, launches.
- [ ] A failed repair writes **no** false success stamp and **no** false FFmpeg pin, preserves
      last-known-good state, stays retryable, and says something true.
- [ ] **No normal recovery requires the user to delete `.venv`.**
- [ ] **No message tells the user to repeat an action that follows an identical non-repairing
      path.**
- [ ] The requirements stamp is written **only** after pip success **and** import-validation
      success, in `run_setup` **and** the drift path.
- [ ] Interpreter candidates are structured argv; spaced executable and repository paths work.
- [ ] Python 3.12 → 3.11 preference; 3.13+ is never reported as a healthy successful setup; no
      unrelated interpreter is uninstalled or modified.
- [ ] Audio operations consume only a **health-proved** pair; no unproved pair, no independent
      bare-name resolution.
- [ ] `shared/ffmpeg_health.py` is still the only health authority.
- [ ] The Windows portable fallback is pinned to Gyan **9.0.1** by URL **and** SHA-256, verified
      before extraction, staged, safely extracted, proved in staging, promoted by a single
      same-volume directory rename into a versioned destination, proved and pinned after.
- [ ] Nothing weakens or routes around a security policy.
- [ ] A full test run writes **no** production environment state — no real `.venv` stamp, no
      production setup log, no `ffmpeg-state.json`, no `files/bin`.
- [ ] Phases 7, 8 and 9 have maintainer-approved real-machine evidence.
- [ ] The superseding ADR is recorded; the 2026-08-28 entry is intact.
- [ ] Coordination records are accurate; this drop is deleted.
- [ ] Version identity is still **0.6.2**, **UNRELEASED**; latest published release still
      **`v0.4.0`**; no tag, release, package or `release.py` run.
- [ ] **Plan 6 has still not started.**

---

## 14. Closeout / drop-retirement rule

Instruction markdowns are **temporary** (`AI-WORKSPACE.md`, *Instruction markdowns are temporary*).

At **Phase 10**, once every phase is complete and approved:

1. move the durable content into the permanent records — `Decisions.md` (the superseding ADR and
   any non-obvious choice), `Changelog.md` (what changed, under `0.6.2`, **without** creating a
   release heading), `Briefing.md` (only if the project description genuinely changed),
   `Handoff.md` (final state and what comes next);
2. **delete `md-instructions/pre-plan-6-setup-self-healing.md`**;
3. confirm the four canonical documents still pass `check_doc_names`;
4. run the final clean-tree gate;
5. **STOP.**

This file is **not** permanent documentation and must not be referenced by anything that outlives
it. `md-instructions/don't-delete/**` is never retired with a drop.

---

*Authored 2026-09-03 by Claude Code at the maintainer's direction, from the approved Checkpoint-1
read-only investigation as revised by maintainer/ChatGPT review. Phase 0 only — no production or
test code was written in the checkpoint that produced this document.*
