# ACT v0.8.2 — Phase 3B: native macOS uv feasibility report

Decision-ready findings for plan `Developer-Experience-Upgrade.md` (Revision 7), Phase 3B. Agent-run, not independently
reviewed. Machine HOME-MacOS: Apple M4 Pro (arm64), 24 GB, macOS 27.0.1 (26A434), APFS data volume (case-insensitive),
about 512 GiB free throughout. Candidate `c988bd3` (branch `0.8.2`), reached by a fast-forward of the primary checkout from
`0.8.1` with the owner's uncommitted work carried unchanged. Every prototype, download, cache, environment and log stayed in
the ignored `files/dev-work/uv-3b/`; nothing in this report is a production change. Phase 3A
(`ACT-v0.8.2-Phase3A-Windows-uv-Feasibility.md`) is reused; its platform-independent experiments were not repeated. The
three Phase 3A project definitions were used **unchanged** (no macOS-specific difference was needed); the one new definition
is the macOS Python download pin, kept as `files/plans/phase3a-uv-examples/python-downloads-macos.json`.

## Verdict

| Experiment | Result | One line |
|---|---|---|
| A. uv pin, quarantine | **PASS** | uv 0.13.10 `aarch64-apple-darwin`, digest identical three ways, Developer ID signed and notarized; runs even when quarantined. |
| B. Managed CPython (A2) | **PASS, one documented difference** | The ACT-owned pin installs today's PBS 20261009 archive; uv patches two files at install time on macOS (below); Aqua Tk 9.0.4 window, ssl, venv, offline restore proved; no user, PATH or system writes. |
| C. Dependency parity and installation | **PASS** | Base 169/169, OmniVoice 86/86, Kokoro 97/97 + the spaCy model; all three installed and import-proved; MPS available in each. |
| D. APFS clone versus copy | **PASS, clone recommended** | Clone: 0.56 s and 18 MiB physical for a 1.15 GiB environment; in-place damage stays out of the cache; offline repair 0.10 s. |
| E. A1 layout, relocation, launcher | **PASS** | uv deletes nested engines with the base; siblings survive (also with an engine process running); move and copy relocate offline. |
| F. Simplified gate, native | **PASS with native gate defects D1 (cleanup) and D3 (scratch audit)** | Marker inheritance, stall/timeout supervision, canonical routing and stage/JUnit reporting pass; the exited-leader cleanup path fails on Darwin (smallest correction below). |

Go/no-go (macOS): **base GO; Kokoro GO; OmniVoice GO** (installed and import-proved here). Qwen3 and Chatterbox stay
unsupported on macOS (engine policy unchanged; Chatterbox imports only because it is in today's base lock). **Phase 4: GO.**

Proof levels used below: *resolution* (lock artifacts match), *installation* (uv installed them), *import* (modules import
in that environment), *application behaviour* (the app working on it). Application behaviour, model loads and synthesis are
**NOT RUN** by design in every row.

## 1. uv

- **uv 0.13.10** (`e3e7c1eac 2026-11-24`): `https://github.com/astral-sh/uv/releases/download/0.13.10/uv-aarch64-apple-darwin.tar.gz`,
  14,700,626 bytes, SHA-256 `e419bf07533bdbf48795fc793601c834dd79db57a8c49ce8e25cfe3a8639958d` — identical in the download, the
  release `.sha256` file and the GitHub asset digest. Contents: one directory, `uv` (`4ff271e4…2ab3`) and `uvx`
  (`0d621b3b…d690`), both mode 755; no absolute, `..` or link entries; extracted with `/usr/bin/tar --no-same-owner`.
- **Signature:** `Developer ID Application: OpenAI OpCo, LLC (2DC432GLL2)`, hardened runtime, secure timestamp,
  `codesign --verify --strict` valid; `spctl -a -t open --context context:primary-signature`: *accepted, source=Notarized
  Developer ID*. (`spctl -t execute` answers "not an app", which is normal for a bare command-line tool.)
- **Quarantine:** a `curl` download carries no `com.apple.quarantine` (only `com.apple.provenance`). Controlled fixture,
  clearly identified: a copy of the archive tagged `0083;<time>;Safari;ACT-PHASE3B-CONTROLLED-FIXTURE` (a browser-equivalent
  attribute; no real browser was used). `/usr/bin/tar` **propagates** the attribute to the extracted `uv`/`uvx`; both still
  ran from the shell (0.29 s / 0.08 s) with no prompt, and the attribute stayed unchanged. **PASS.**
- Compatibility: nothing in uv 0.13.10's behaviour on this Mac conflicts with ACT; every flag used appears in this binary's help.

## 2. Managed CPython (A2)

- uv's built-in catalog would install `3.12.15` as PBS **20261021 `install_only_stripped`** (and `3.12` as 3.12.16+20261124), as on
  Windows. The ACT-owned pin (`UV_PYTHON_DOWNLOADS_JSON_URL`, key `cpython-3.12.15-macos-aarch64-none`) names exactly the archive
  `bootstrap_host_macos.sh` pins: `cpython-3.12.15+20261009-aarch64-apple-darwin-install_only.tar.gz`, 25,165,569 bytes, SHA-256
  `83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8`. `uv python install 3.12.15`: 1.75 s (uv rewrote the GitHub URL to
  `releases.astral.sh`; the hash binds the bytes).
- **Identity and parity.** Today's `files/runtime-data/python` is byte-identical to the pristine archive (1,660 files, 0
  differences). The uv install matches it in **1,658 of 1,660 files**; uv adds `BUILD` (`20261009`) and `EXTERNALLY-MANAGED`, and
  **patches two files at install time on macOS** (no Windows equivalent):
  - `lib/libpython3.12.dylib`: its install name (`LC_ID_DYLIB`) changes from `@rpath/libpython3.12.dylib` to the absolute
    install path; the file is re-signed ad hoc (`codesign --verify --strict` valid). `bin/python3.12` does not link the dylib
    (static interpreter), so the interpreter itself is unaffected; only programs that link libpython would record the path.
  - `lib/python3.12/_sysconfigdata__darwin_darwin.py`: 68 lines; the `/install` build prefix becomes the real prefix and
    build-machine tool paths become `ar`/`cc`.
  `sys.version` is identical (`3.12.15 (main, Oct  9 2026, 15:10:57) [Clang 22.1.3 ]`); native arm64 Mach-O, ad-hoc
  linker-signed like today's; OpenSSL 3.5.9. This satisfies the approved A2 (the exact pinned build through ACT-owned metadata);
  ACT's interpreter identity must therefore be the archive SHA-256 + `BUILD` + `sys.version`, never a whole-tree hash.
- **Aqua Tk:** one visible window (`tk windowingsystem` = `aqua`, Tk 9.0.4) was mapped and viewable and closed itself after
  1.84 s (process 2.0 s, bounded at 30 s).
- **ssl:** default context loads 128 CA certificates from the system `/private/etc/ssl/cert.pem`. **venv:** stdlib `venv` +
  `ensurepip` in 1.5 s.
- **Offline restoration:** after `uv python uninstall` (120 ms), with all traffic sent to an unreachable proxy, the no-mirror
  control failed (connection refused) and `uv python install 3.12.15 --mirror file://<ACT's verified archive folder>` restored
  the interpreter in **0.38 s**. Per Phase 3A, `UV_PYTHON_CACHE_DIR` was a fresh per-operation scratch folder each time (no
  cache framework); each such folder keeps a 24 MiB archive copy, so the wrapper must delete it after the operation.
- **No persistent writes:** before/after snapshots of the root `.venv` (with the nested OmniVoice engine), `files/runtime-data/python`,
  the wheel store, `~/.local/bin`, `~/.local/share/uv`, `~/.cache/uv`, `~/.config/uv`, `~/Library/Caches/uv`,
  `~/Library/Application Support/uv`, `~/Library/Python`, `/Library/Frameworks/Python.framework`, `/usr/local/bin`,
  `/opt/homebrew/bin` and eight shell startup files: **14 of 14 unchanged**. The redirected uv bin, tool and credential
  folders stayed empty.
- Install layout: `<install dir>/cpython-3.12.15-macos-aarch64-none/` plus an **absolute symlink**
  `cpython-3.12-macos-aarch64-none`; uv creates `.lock` files with mode 666 in the install dir and in each environment (see §9).

## 3. Dependency parity and installation

Projects: the Phase 3A `base`, `omnivoice` and `kokoro` definitions, unchanged. Locks resolved natively in 2.4 s / 1.0 s / 0.9 s.
Comparison: for every package the export selects on this platform (markers evaluated here), the wheel uv installs (best tag
for CPython 3.12 arm64 on this Mac) or the sdist, by version and SHA-256, against ACT's macOS reference.

| Project | Reference | Version + artifact-hash matches | Notes |
|---|---|---|---|
| Base | `requirements-lock-macos-arm64-py312.txt` (169) | **169/169** | sdists antlr4 4.9.3 and docopt 0.6.2, as today; pytest in the `dev` group |
| OmniVoice | `omnivoice_manifest.json` `darwin_arm64.wheels` (86) | **86/86** | plain PyPI torch/torchaudio 2.8.0 on darwin by marker |
| Kokoro | the base macOS lock, Kokoro's own packages | **97/97** + `en-core-web-sm` 3.8.0 | the model wheel's lock hash equals `spacy_store.SPACY_WHEEL_SHA256`; `win32-setctime` correctly excluded |

Negative control: the same selection checked against the Windows lock reports 124/170 with the platform wheels flagged, so a
match is meaningful.

Installation (each in a disposable environment, `--compile-bytecode`):

| Stack | Route | Time | Installed | Imports (no model loads) | MPS |
|---|---|---|---|---|---|
| Base | cold, online, clone | 9.8 s (download/prepare 5.2 s, link 0.48 s, 17,151 files compiled 3.9 s) | 169 | **20/20**: `bootstrap.REQUIRED_IMPORTS` (edge_tts, pydub, fitz, mutagen, PIL, nltk, chatterbox) + kokoro, misaki, spacy, `srsly.msgpack._epoch`, `sklearn.utils._isfinite`, pkg_resources, pillow_heif, soundfile, scipy, numpy, torch, torchaudio, transformers | built, available (torch 2.6.0) |
| OmniVoice | online, `--no-cache` (D-8) | 9.7 s | 86; shared cache unchanged (0 KiB), env 1.2 GiB | **8/8** incl. `omnivoice`, accelerate, librosa | built, available (torch 2.8.0) |
| Kokoro | warm shared cache, clone | 3.6 s, no download | 98 | **10/10** incl. kokoro, misaki, spacy, `en_core_web_sm` | built, available (torch 2.6.0) |

## 4. APFS: clone versus copy, cache and repair

Warm, offline (unreachable proxy) base syncs from one shared cache (1.2 GiB unpacked); physical = data-volume use before/after:

| Mode | Time | Physical | Logical |
|---|---|---|---|
| clone | **0.56 s** | **18 MiB** | 1,175 MiB |
| copy | 8.78 s | 1,220 MiB | 1,163 MiB |
| clone + bytecode | 4.52 s | 378 MiB | 1,518 MiB |
| copy + bytecode | 12.85 s | 1,614 MiB | 1,506 MiB |
| hardlink (control only) | 16.3 s | — | — |

- **Isolation:** an in-place write into an installed file (`tqdm/std.py`) left the cache entry byte-identical in **clone** and
  **copy**; the **hardlink** control changed the cache entry too (link count 2), proving the check can see sharing.
- **Detection:** `uv sync --check` answered "Would make no changes" for the damaged file; a csv RECORD hash check found it
  (35,374 entries, 1.0–4.7 s with hashes across runs, about 0.13 s presence-only).
- **Offline repair:** `--reinstall-package tqdm --offline` restored the original bytes in 0.10 s (clone and copy), cache intact,
  RECORD clean. A deleted package (dist-info and files) is detected by `--check` and restored by an offline sync.
- **Cache trust (finding):** while the hardlink control had damaged the cache, an offline repair in clone and copy mode
  reinstalled the *damaged* bytes without complaint: uv does not verify cache contents on reuse. Clone is safe because APFS
  clones are copy-on-write; hardlink must never be used, and the RECORD check is what catches a damaged cache.
- **Interruption (clone):** killing `uv sync --reinstall` at 0.3 s and 0.45 s left `numba` and `scikit-learn` as a dist-info
  without RECORD and without most files (`sklearn.utils` missing); `uv sync --check` answered "Would make no changes", and an
  ordinary sync did **not** repair them. The RECORD check found both; `--reinstall-package` repaired them offline (174 ms);
  imports 5/5. This is the Phase 3A finding, reproduced natively.

**Recommendation (A4, macOS): `clone`.** It gives independent writes and reliable offline repair at almost no disk cost;
the base repair cache is retained (about 1.2 GiB unpacked, 0.34 GiB download). OmniVoice installs with `--no-cache` by default
(as approved); repairing it re-downloads about 0.23 GiB with consent (honest limitation: no offline OmniVoice repair).
Not measured: cross-volume clone fallback (ACT keeps cache and environments in one root, so one volume).

## 5. Engine layout (A1) and relocation

Small representative root: its own managed Python and cache, a base (`tqdm`, `mutagen`), a sibling engine
`.venv-engines/kokoro-mini` (`soundfile`, `numpy`, native libraries) and a nested control `.venv/engines/kokoro-mini`.

- **Base recreation** (the base's interpreter link broken): uv printed "Removed virtual environment at: …/.venv" and recreated
  it; the **nested engine was deleted with it**; the **sibling was untouched** (identical inode/mtime fingerprint) and a
  process running from the sibling engine during the recreation continued and exited 0. Native confirmation of A1.
- **Exact interpreter request (new macOS finding):** `--python 3.12.15` records the versioned folder in `home`;
  `requires-python = "==3.12.*"` alone and, notably, an explicit interpreter *path* record the minor-version link
  `cpython-3.12-macos-aarch64-none`. An environment created through the link is later accepted by an exact request without
  recreation, so the wrapper must always pass `--python 3.12.15` and validate `home` itself.
- **Move** (to a path containing a space): both environments were reported "linked to non-existent Python interpreter",
  removed and recreated **offline from the moved root's own cache**, `home` inside the new root; base and engine imported.
  The moved interpreter itself ran, but its minor-version symlink still pointed at the old root (absolute) and its patched
  sysconfig prefix was stale; `uv python install 3.12.15 --reinstall --mirror file://…` (offline, 0.47 s) refreshed both, and
  the existing environments kept working through the reinstall.
- **Copy with the original present** (`ditto`, Finder-equivalent): uv recreated both environments against the **copy's own**
  interpreter and never reached back to the original; the copied minor-version symlink pointed at the original until refreshed.
- **Permissions and links:** the executable file set (119 files) was identical after `ditto` and after `cp -R`; symlinks
  stayed symlinks. Launchers are Git mode `100755`; `release.py` stores the launcher as 0755 in the ZIP.
- **Case:** the data volume is case-insensitive and case-preserving (`.venv` and `.VENV` are one folder). A case-sensitive
  APFS volume was NOT RUN.
- **Path depth** (characters relative to the ACT root, production-equivalent prefixes):

| Location | Deepest file | Deepest native library |
|---|---|---|
| `.venv/` (base, with bytecode) | 165 | 130 |
| `.venv-engines/omnivoice/` | 190 | 148 |
| `.venv-engines/kokoro/` | 176 | 145 |
| `files/runtime-data/uv/cache/` | 173 | 151 |
| `files/runtime-data/uv/python/cpython-3.12.15-macos-aarch64-none/` | 163 | 121 |

  macOS limits are `PATH_MAX` 1024 and `NAME_MAX` 255 (longest name 94), so the root may be about 830 characters. ACT's depth
  limits are Windows-only (`long_paths` gates on `win32`; Decisions P5-G), so siblings' +2 characters do not matter here.

## 6. Quarantine, Gatekeeper and the `.command` launcher

- The launcher runs the host bootstrap through `/bin/bash` and the app through the venv's interpreter; quarantine on extracted
  *scripts* and data does not matter, only on executed *binaries*. It already handles App Translocation, and the README
  documents the first-run "Open Anyway" step; the uv design adds no new prompt.
- Under the uv design the binaries arrive unquarantined: `curl` (the host bootstrap's downloader) sets no quarantine, and the
  uv-installed interpreter carried only `com.apple.provenance`. uv itself is notarized and runs even when quarantined (§1).
- **Controlled fixture:** a copy of the uv-managed interpreter tagged recursively as Archive Utility would tag an extracted
  download: `spctl` *rejected*; running it **hung under Gatekeeper until the 30 s deadline killed it** (a Gatekeeper prompt may
  have been shown). An interpreter must therefore never reach a user through a quarantining path (a root copied from another
  Mac by browser, AirDrop or ZIP); repair is recreating it from ACT's verified archive. The existing bootstrap probe's watchdog
  already turns such a hang into a clear failure. Whether uv's own extraction propagates quarantine from a quarantined archive
  was NOT RUN.

## 7. Native simplified gate (the macOS obligation carried from Phase 1A)

Run with the checkout's real `.venv` (built on 0.8.1; the locks are unchanged since). Evidence in the ignored
`files/dev-work/verification-gate/outputs/`.

| Run | Result | What it shows |
|---|---|---|
| `2026-11-27_153023_quick_8383` | **PASS** (8 s) | static checks, import smoke; `process-ownership` PASS as a process group |
| `2026-11-27_153203_focused_0c84` (10 selectors) | **FAIL** (50 s): 10 failed, 29 passed | reporting accurate: `pytest` FAIL exit 1, JUnit `tests=39 failures=10` agrees with the summary, `cleanup` PASS, `tree` unchanged, the failed run kept its scratch as designed |
| `2026-11-27_153708_focused_d42d` (8 selectors) | **PASS** (33 s): 29 passed | `requested-scope` 8/8, `cleanup` PASS, no skips |

- **Routine marker inheritance: PASS** (`test_routine_guard.py`, whole module: the marker reaches a child, opt-ins scrubbed, a
  child's real entrypoint refuses, a swallowed refusal fails).
- **Process-group supervision and timeout cleanup: PASS for stall and total timeout** (the stalled child and its grandchild
  stopped within the budget; a chattering test stopped by the total timeout). **FAIL for an exited leader with a grandchild
  left behind** (defect D1 below). An unrelated process was never touched.
- **Canonical selector routing on the native filesystem: PASS.** On the real gate, `files/tests/TEST_ROUTINE_GUARD.py`,
  `files/Tests/…` and `./files/tests/../tests/…` are refused before planning; `files/tests/test_ROUTINE_guard.py` (which
  case-insensitive APFS would open) plans as the canonical `files/tests/test_routine_guard.py`, a case-varied node likewise; a
  nonexistent node is a named `missing` gap. The synthetic case-variant guarded-module and path-normalization tests pass.
- **Stage exit and JUnit reporting: PASS** (stage naming for assertion/setup/teardown failures, an inconsistent JUnit report
  rejected, requested-scope reconciliation, and the accurate FAIL run above).

**D1 — native gate defect (Darwin), `files/dev-work/verification-gate/helpers/winproc.py`.** Root cause, reproduced 3/3 with
the gate's own `run_supervised` and an errno trace: after SIGKILL, a process group whose members are exiting (killed, not yet
reaped by launchd, about 15–30 ms) answers signal 0 with success but can answer a real signal with **EPERM**, and only then
ESRCH. (1) The POSIX branch of `run_supervised` records survivors immediately after `_stop_tree`, so the exiting group is
reported as a surviving process (false `cleanup` FAIL); (2) `_stop_tree` catches only `ProcessLookupError` around
`os.killpg`, so an EPERM escapes and the gate dies before `results.json` exists (seen twice in the native run).
**Smallest correction:** in `_stop_tree`, treat `PermissionError` like `ProcessLookupError` around both `killpg` calls; in
`run_supervised`'s POSIX branch, poll `_group_alive` for up to `kill_wait` before recording survivors (the bounded loop the
Windows job branch already has). Windows is unaffected (job branch). The existing contract test
`test_a_grandchild_left_behind_is_a_failed_cleanup_and_an_unrelated_process_survives` is the regression test. Not changed
in this phase.

**D2 — test portability (not a gate defect).** `test_no_exit_code_can_raise_a_verdict_and_only_exit_zero_lets_a_pass_stand`
(9 parameters) plants an `m4b-scaling` qualification, which the planner targets at Windows only; on macOS the plan is
correctly BLOCKED and nothing runs, so the test's Windows expectations fail. Smallest correction: mark it with the module's
existing `WINDOWS_ONLY` marker (or plant a scenario that targets the native platform). It belongs to the owed macOS
test-portability drop listed in Handoff.

**D3 — native gate-tool defect (low severity), `helpers/scratch.py`.** Found by the closeout run below. `_process_created`
returns `None` on every non-Windows platform and `owner_process_alive` treats `None` as "not running" (its docstring says an
unknown creation time counts as alive), so on macOS `--audit-scratch` labels every `act-gate` child "abandoned", an active
run's included. Only the read-only audit uses it (a run removes only its own scratch), so nothing is deleted automatically,
but a manual cleanup guided by the audit could remove an active run's scratch. Smallest correction: a POSIX creation time
(for example `ps -o lstart= -p <pid>` or `sysctl` `kern.proc.pid`), or report such a child as `unproven` on POSIX; the failing
contract test `test_a_child_whose_owner_process_still_runs_is_active_and_one_whose_owner_ended_is_abandoned` is the
regression test.

Closeout runs on the documentation changes of this phase: `2026-11-27_154508_quick_ef85` quick **PASS** (docnames, docs,
doc-links, import smoke); `2026-11-27_154517_focused_8785` **FAIL** only on D3: 11 modules (the ten whole modules
`--mode changed --plan` routed plus `test_routine_guard.py`, which reads GATE.md), 652 passed, 10 policy-named skips
(Windows-only), 1 failed (D3). `--mode changed` itself was not executed here: on this checkout it also routes the owner's
uncommitted archiving (a Windows-only obligation) and about 170 gate-contract nodes that include D2-style Windows
assumptions on macOS; those nodes are NOT RUN on this Mac and are owed to the next Windows `changed` run.

Routine verification time for this phase: about 4.5 minutes in total (gate runs, plans, six direct reproductions of single
tests, read-only audits), within the 10-minute target.

## 8. Downloads, timings and disk

- Downloads, about **0.7 GiB** in total: uv 14.7 MB; the PBS archive twice (uv's online install and ACT's own verified copy for
  the `file://` mirror, 24 MiB each); resolution metadata about 50 MB; base 0.335 GiB; OmniVoice 0.230 GiB (equal to the
  manifest's darwin total); the spaCy model 12.2 MiB; the small representative root's packages about 16 MB; one 0.1 MB refetch.
- Per migrated macOS install (from the locks): base 0.34 GiB to fill the repair cache (or 0 if seeded the Phase 3A way, which
  was not repeated here), Kokoro 0.01 GiB beyond base, OmniVoice 0.23 GiB.
- Timings: see §2–§5 (uv-managed Python 1.75 s online, 0.38 s offline; base cold 9.8 s; warm clone 0.56 s).
- Disk: peak about 5.5 GiB apparent in `uv-3b`; free space never below 510 GiB. Removed at the end (own disposable work): the
  prototype environments, the small roots, the quarantine fixtures, temporary files, six direct-run basetemps under
  `files/run-temp/`, and the failed gate run's own scratch (108 MiB, `act-gate/2021`). Kept (1.4 GiB, ignored): the verified uv
  binary and archive, the PBS archive (offline mirror), the three projects with their `uv.lock` files, the base cache (1.2 GiB),
  the managed Python, logs, snapshots and the small tools. Older `act-gate` folders from earlier agents were left as found.

## 9. Unresolved platform limitations

One Mac (M4 Pro, macOS 27.0.1, administrator account); no second Mac, older macOS, standard user, fresh account or
case-sensitive volume. Quarantine was a controlled fixture, not a real browser download; Gatekeeper behaviour on other macOS
versions is unproved. Cross-volume clone fallback, uv extraction of a quarantined archive and an app launch on a uv environment
were NOT RUN. uv's two macOS install-time patches mean the interpreter tree is not byte-identical to the archive. uv creates
`.lock` files with mode 666 (relevant to the open, owner-pending macOS permissions item). OmniVoice has no offline repair
by default. `require-build-hashes` is still experimental in uv. The Windows OmniVoice installation proof moved to Phase 5B.

## 10. Go/no-go

**Phase 4: GO.** Base GO, Kokoro GO, OmniVoice GO on macOS; no fundamental blocker. D1 should be corrected before the gate's
macOS cleanup results are relied on in Phase 4 (a small change to a development tool, not production).

## 11. Implementation requirements carried into Phase 4 (Phase 3A + 3B)

1. **Pins:** uv 0.13.10 per platform by SHA-256 (Windows `297b3881…8683`, macOS `e419bf07…958d`); CPython 3.12.15 + PBS 20261009
   through ACT-owned download metadata per platform (Windows `194c8f0d…b93b`, macOS `83dcb047…75b8`); ACT keeps its own verified
   archive as the `file://` mirror for offline restoration.
2. **Isolation set on every call** (Phase 3A §2): `UV_NO_CONFIG`, `UV_NO_ENV_FILE`, explicit cache, Python install, Python cache,
   bin, tool and credential dirs, `UV_PYTHON_INSTALL_BIN=0`, `UV_PYTHON_NO_REGISTRY=1`, `UV_PYTHON_PREFERENCE=only-managed`,
   `UV_PYTHON_DOWNLOADS=manual`, `UV_PYTHON_DOWNLOADS_JSON_URL`, `TMPDIR`/`TEMP`, explicit `--project`,
   `UV_PROJECT_ENVIRONMENT` derived and validated by the wrapper, inherited `UV_*`, `PIP_*`, `XDG_*`, `VIRTUAL_ENV`, `CONDA_PREFIX`,
   `PYTHON*` and `SSL_CERT_*` cleared. Paths may contain spaces (quote, never word-split).
3. **Per-operation Python cache scratch**, deleted after the operation (a refused archive stays; each keeps a 24 MiB copy).
4. **Always request `--python 3.12.15`** and validate each environment's `home` against the versioned interpreter folder; tolerate
   the uv-owned minor-version link (Windows junction, macOS absolute symlink) and refresh it with an offline
   `python install --reinstall` after relocation.
5. **Interpreter identity** = archive SHA-256 + `BUILD` + `sys.version` (+ arm64/Tk/ssl probes); never a whole-tree hash (macOS
   patches `libpython3.12.dylib` and `_sysconfigdata`).
6. **Layout (approved A1):** base `ACT_ROOT/.venv/`, engines `ACT_ROOT/.venv-engines/<engine>/`; no aside/restore protocol.
7. **Link mode (approved A4/D-8):** Windows `copy`, macOS `clone`, never `hardlink`; base repair cache retained; Qwen3 and
   OmniVoice installed with `--no-cache` by default; `uv cache prune` after a successful sync.
8. **Receipts** only after sync + a csv RECORD check (a dist-info without RECORD is damage; parse RECORD directly; hashes where
   affordable) + real imports; `uv sync --check` is not an integrity check; targeted `--reinstall-package` for repair.
9. **`--compile-bytecode`** on install.
10. **Relocation:** a moved or copied root recreates its environments offline from its own cache and interpreter; the wrapper
    must expect "Removed virtual environment" for base and engines alike.
11. **Quarantine:** never ship or transfer an interpreter or environment through a quarantining path; acquire uv and Python with
    `curl`/uv; keep the bootstrap watchdog probe.
12. **Path depth:** Windows deepest path 175 (uv cache) against today's 172 limit (Phase 3A §8); macOS has no practical limit.
13. **Gate:** correct D1 before relying on macOS gate cleanup results; D3 before relying on macOS `--audit-scratch`; D2 with the macOS test-portability drop.
14. **Still open:** D-6 (Windows PowerShell-blocked fallback) before Phase 4; Windows OmniVoice installation proof in 5B.

## 12. Owner decisions

Recorded as approved (2026-11-27): uv 0.13.10; A2 (exact pinned build through ACT-owned metadata); A1 (independent siblings
`ACT_ROOT/.venv-engines/<engine>/`, base fixed at `ACT_ROOT/.venv/`, superseding the engine part of the 2026-11-13 layout);
A4/D-8 (Windows copy, base repair cache retained, no persistent Qwen3/OmniVoice package cache by default); macOS clone
subject to native proof (**now proved**, §4); bytecode compiled at install; Windows OmniVoice installation proof in 5B; native
macOS feasibility before Phase 4 (**done**).

Genuinely new, for the owner (none blocks Phase 4):
1. **macOS OmniVoice cache (optional).** Under clone mode a retained OmniVoice cache would cost little beyond the environment
   itself (the base measurement: a clone environment adds 18 MiB to its cache; not measured for OmniVoice) and would give
   offline OmniVoice repair. Default stays `--no-cache` as approved unless the owner chooses otherwise.
