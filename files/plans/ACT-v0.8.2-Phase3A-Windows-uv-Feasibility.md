# ACT v0.8.2 — Phase 3A: Windows uv feasibility report

Decision-ready findings for plan `Developer-Experience-Upgrade.md` (Revision 6), Phase 3A. Agent-run, not independently
reviewed. Machine HOME-PC: Windows 11 Pro 10.0.26300, Smart App Control **enforcing** (`VerifiedAndReputablePolicyState`
= 1), `LongPathsEnabled` = 1. Candidate `b1a28d5` (branch `0.8.2`) in the D-1 checkout. Every prototype, download, cache,
environment and log stayed in the ignored `files/dev-work/uv-3a/`; nothing in this report is a production change. The five
prototype project definitions and the Python download pin are kept as small examples in `files/plans/phase3a-uv-examples/`
(file names end in `.pyproject.toml` so no tool discovers them as projects).

## Verdict

| Experiment | Result | One line |
|---|---|---|
| A. uv pin and managed Python (A2) | **PASS** | uv 0.13.10 installs the exact current interpreter (3.12.15, PBS 20261009), byte-identical to today's, with no registry, PATH, bin or user-directory writes. |
| B. Dependency parity | **PASS** | All five projects resolve to exactly today's versions and artifact hashes; base and Qwen3 also installed and import-proved. |
| C. Engine environment isolation (A1) | **PASS, with a decisive finding** | uv deletes the whole `.venv` when it recreates the base, nested engines included. Independent siblings are unaffected. |
| D. Cache and offline repair (A4/D-8) | **PASS, with findings** | Offline install and targeted repair work; hardlinks share damage with the cache; uv's own checks miss partial packages. |
| E. Windows compatibility and relocation | **PASS** (long paths off: computed, NOT RUN) | Move and copy relocation recreate offline from the root's own data; every executable ran from a MOTW-tagged extraction under SAC. |

Go/no-go per environment: **base GO; Kokoro GO; Chatterbox GO; Qwen3 GO; OmniVoice GO (lock parity only, installation
proof owed).** No fundamental blocker. Phase 4 still waits for Phase 3B (macOS) or an owner-approved deferral.

## 1. uv pin

- **uv 0.13.10** (released 2026-11-24): `https://github.com/astral-sh/uv/releases/download/0.13.10/uv-x86_64-pc-windows-msvc.zip`,
  15,641,577 bytes, SHA-256 `297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683` (identical in the download, the
  release's `.sha256` file and the GitHub asset digest). Contents `uv.exe` (`9f9f3631…5c76`), `uvx.exe`, `uvw.exe`; no unsafe
  entries; extracted with Windows' built-in `tar.exe`. All three are Authenticode-valid (signer "OpenAI OpCo, LLC").
- Why this one: it is the current 0.13 patch and addresses GHSA-vjvj-3m3f-fgmm; nothing in the 0.13.x Windows notes conflicts
  with ACT. A pin changes only by an explicit update of the digest.
- Every flag used was checked against this binary's `help` (saved under `uv-3a/logs/help/`). The environment variables the
  binary reads were listed from the executable; the isolation set below is drawn from that list.

## 2. Managed CPython (A2) — outcome A, with an ACT-owned download pin

- uv 0.13.10's built-in catalog would install `3.12.15` as **PBS 20261021 `install_only_stripped`** (and `3.12` as 3.12.16),
  not today's build; `UV_PYTHON_CPYTHON_BUILD` does not change that. The supported `--python-downloads-json-url` /
  `UV_PYTHON_DOWNLOADS_JSON_URL` accepts a local file: one entry naming today's archive
  (`cpython-3.12.15+20261009-x86_64-pc-windows-msvc-install_only.tar.gz`, 46,352,482 bytes, SHA-256 `194c8f0d…b93b`, the same
  pin as `bootstrap_host.ps1`) makes `uv python install 3.12.15` install exactly today's interpreter (5.5 s). ACT then owns the
  interpreter pin independently of the uv version.
- Result compared with `files/runtime-data/python`: 3,384 shared files, **0 differences** outside runtime bytecode; uv adds
  `BUILD` (`20261009`) and a PEP 668 `Lib/EXTERNALLY-MANAGED` marker. `sys.version` identical; OpenSSL 3.5.9; Tk/Tcl 8.6; ssl
  default context loads 50 CA certificates from the Windows store; stdlib `venv` + `ensurepip` work (2.5 s); one native Tk
  window opened and closed itself in 1.56 s.
- Installed at `<install dir>\cpython-3.12.15-windows-x86_64-none\` plus a uv-created **junction**
  `cpython-3.12-windows-x86_64-none` (always created since uv 0.10; cannot be disabled). Environments created with the exact
  `3.12.15` request record the versioned folder, never the junction.
- Offline restoration: from the Python archive cache with `--offline` 1.3 s; from a local `file://` mirror (`--mirror`) without
  `--offline` 1.2 s behind an unreachable proxy (`--offline` refuses a `file://` mirror and reads only the archive cache).
- Integrity: a truncated archive and a well-formed but re-packed archive were both refused, nothing installed; the SHA-256 is
  re-checked on every use of a cached archive. **Defect found:** a refused archive stays in `UV_PYTHON_CACHE_DIR` under its
  expected name, and every later install fails on it (`--reinstall` with a good mirror included; `uv cache clean` does not touch
  that directory). Fail-closed, but sticky.
- Default source: uv rewrites GitHub PBS URLs to `releases.astral.sh` unless a mirror is given; the hash still binds the bytes.
- No writes to `HKCU`/`HKLM\Software\Python` or `HKCU\Environment`, none to `%APPDATA%\uv`, `%LOCALAPPDATA%\uv`, `~\.local\*`,
  `~\.cache\uv`, `~\.config\uv`; the Python bin, tool and credential directories stayed empty (before/after snapshots).

Isolation set that achieved this (the planned `uv_runner` wrapper sets all of them): `UV_NO_CONFIG=1`, `UV_CACHE_DIR`,
`UV_PYTHON_INSTALL_DIR`, `UV_PYTHON_CACHE_DIR`, `UV_PYTHON_BIN_DIR`, `UV_PYTHON_INSTALL_BIN=0`, `UV_PYTHON_INSTALL_REGISTRY=0`,
`UV_PYTHON_NO_REGISTRY=1`, `UV_PYTHON_PREFERENCE=only-managed`, `UV_PYTHON_DOWNLOADS=manual` (never for launches),
`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_CREDENTIALS_DIR`, `UV_NO_ENV_FILE=1`, `UV_PYTHON_DOWNLOADS_JSON_URL`, `TEMP`/`TMP` (uv
writes `uv-*.lock` files there), explicit `--project`, `UV_PROJECT_ENVIRONMENT`, `--link-mode`; inherited `UV_*`, `PIP_*`,
`XDG_*`, `VIRTUAL_ENV`, `CONDA_PREFIX`, `PYTHONPATH`, `PYTHONHOME`, `SSL_CERT_*` cleared.

## 3. Dependency parity (one `uv.lock` per independent project)

Each project is a non-package project, `requires-python = "==3.12.*"`, resolution limited by `[tool.uv] environments` to the
platforms ACT supports for it, today's exact pins as `constraint-dependencies`, explicit `[[tool.uv.index]] explicit = true`
for PyTorch cu128 selected through `[tool.uv.sources]`, and `build-constraint-dependencies` (setuptools 80.9.0 with its hash,
`require-build-hashes = true`) for the named sdists.

| Project | Platforms | Reference | Version + artifact-hash matches | Notes |
|---|---|---|---|---|
| Base | Win x64 + macOS arm64, one lock | both base locks (170 / 169) | **170/170 and 169/169** | pytest moves to the `dev` group (`--no-dev` removes exactly pytest, iniconfig, pluggy); sdists antlr4 4.9.3, docopt 0.6.2; SAC holds srsly 2.5.3, scikit-learn 1.9.0 and setuptools 80.9.0 unchanged; torch 2.6.0 CPU from PyPI |
| Qwen3 | Win x64 | `qwen3-requirements.txt` (89) | **89/89** | torch/torchaudio 2.10.0+cu128 from the explicit cu128 index; `sox` as a URL source = ACT's commit-pinned wheel, hash = `SOX_WHEEL_SHA256` (the reference lists the sdist hash) |
| OmniVoice | Win x64 + macOS arm64 | manifest wheels (88 / 86) | **88/88 and 86/86** | torch 2.8.0+cu128 (Windows, cu128 index), 2.8.0 (macOS, PyPI) by marker; model set untouched |
| Kokoro | Win x64 + macOS arm64 | base lock | **99/99** (+ the spaCy model) | exact current stack (plan A3-A); `en-core-web-sm` 3.8.0 as a URL source; owns the docopt sdist |
| Chatterbox | Win x64 | base lock | **113/113** | the requirements.txt Chatterbox block unchanged; owns the antlr4 sdist |

Locking took 0.04-4.5 s per project (metadata only; the PyTorch index publishes no sizes, so `uv.lock` has none for those
wheels). No version differences, no extra or missing packages, no index fallback, no uncontrolled builds.

Installation proof: **base** (cold, online, copy: 62 s = 47 s download/prepare of 166 + 15 s install; everything imports under
SAC including `srsly.msgpack._epoch`, `sklearn.utils._isfinite`, `kokoro`, `chatterbox.tts_turbo`, `pkg_resources`);
**Qwen3** (268 s cold; only 28 of 89 packages downloaded, 61 came from the shared cache; hardlink install 2.7 s; imports
including `qwen_tts`; `torch.cuda.is_available()` True, CUDA 12.8, RTX 5070; RECORD hashes clean). Kokoro and Chatterbox
artifacts are an exact subset of the installed base (their imports proved there); their isolated environments were not
installed separately. **OmniVoice installation NOT RUN** (about 3.4 GiB download and an 8 GiB environment repeat the mechanism
Qwen3 proved; owed before or in Phase 5B). No model downloads, model loads or synthesis.

## 4. A1 — engine environment layout

| | A. Nested `.venv\engines\<engine>\` | B. Independent siblings `.venv-engines\<engine>\` |
|---|---|---|
| Base recreated by uv (interpreter missing or replaced, relocation, Python change) | **Engine deleted with `.venv`** (observed: "Removed virtual environment at: …\.venv") | Engine untouched (observed, including while an engine process ran) |
| Ordinary base exact sync, `--reinstall` | Engine untouched (foreign folder ignored) | Engine untouched |
| Protection needed | Before every base repair: hold every engine lease, rename `engines` aside on the same volume, sync, rename back, journal and crash-recover the aside state. The rename **succeeds while an engine worker is running** (observed), so the leases are mandatory, not optional | None beyond ordinary install locks |
| Deepest paths | Identical: `.venv\engines\chatterbox\` and `.venv-engines\chatterbox\` are both 25 characters | Identical |
| Physical disk | Identical | Identical |
| Complexity | Aside/restore journal, recovery on start, uv-recreation prediction | None; `release.py` already excludes `.venv-*` folders |

**Recommendation: B, independent siblings** `ACT_ROOT\.venv-engines\<engine>\`, with the base fixed at `ACT_ROOT\.venv\`.
Structural isolation removes the whole protection protocol. This would supersede the 2026-11-13 unified-layout decision for
engine environments, so it is the owner's call; nothing has been changed.

Other uv behaviour (both layouts): running uv from a folder without a `pyproject.toml` selects the parent project, so every
call passes `--project`; a non-empty non-environment folder is refused, an empty one accepted; a mistargeted
`UV_PROJECT_ENVIRONMENT` would turn one environment into another (exact sync), so the wrapper derives and validates every
environment path itself.

## 5. A4 / D-8 — link mode, cache and storage

Measured (base): environment 1.99 GiB, its cache share 1.98 GiB (uv keeps wheels unpacked). Hardlink: environment + cache
2.0 GiB physical, warm install 2.8 s. Copy: 4.0 GiB, warm install 14.8 s (+7.6 s with `--compile-bytecode`). An in-place write
to a hardlinked environment file **changed the cache entry**; offline `--reinstall-package` then relinked the damaged file, and
only `uv cache clean <package>` + a network download recovered it. In copy mode the same damage was repaired offline in 35 ms.

**Recommendation:** Windows `copy` (macOS `clone`, Phase 3B). One repo-local shared cache that keeps the base project's
artifacts (Kokoro and Chatterbox share them until 5C/5D), about 2 GiB, so the default install repairs fully offline. The GPU
engines (Qwen3, OmniVoice) install with `--no-cache` (verified: the shared cache is untouched), as today, where no Qwen3 or
OmniVoice wheel cache is kept; repairing them re-downloads with consent. `uv cache prune` after a successful sync (it removes
only dangling entries). uv has no "keep only what the current locks need" command, and per-package `uv cache clean` removes
every version of a name; a normal update deletes the whole folder anyway. Owner alternative: keep the GPU engines cached too
(about +4.7 GiB for Qwen3 and about +8 GiB for OmniVoice) for fully offline engine repair.

Python archive cache: set `UV_PYTHON_CACHE_DIR` to a per-operation scratch folder and keep ACT's own verified copy of the PBS
archive as the `file://` mirror for offline restoration (avoids the sticky refused-archive defect above).

## 6. Offline installation and repair

| Case | Result |
|---|---|
| Base from warm cache, `--offline` | 14.8 s copy / 2.8 s hardlink, no network (unreachable proxy) |
| Missing cache entry, `--offline` | Clear error naming the missing artifact; no silent network (fail-closed) |
| Deleted package (dist-info gone) | `uv sync --check` detects it (7 ms); offline sync restores it |
| Modified or deleted file inside a package | **Not detected by uv**; ACT's RECORD check finds it; `--reinstall-package` repairs offline (35 ms) |
| `uv sync` killed during `--reinstall` | 50 packages missing (detected, restored offline in 13.5 s); **plus two silently broken ones**: `cffi` with a dist-info but no RECORD/METADATA and no `_cffi_backend.pyd`, `scikit-learn` half-uninstalled with intact metadata. `uv sync --check` reported "no changes"; Kokoro and Chatterbox failed to import. A csv RECORD check (4.0 s presence, ~10 s with hashes over 35k files) found both; targeted offline reinstall fixed them |
| Corrupted external input (find-links wheel) | Refused, nothing installed |

Consequences for Phase 4: a receipt is invalidated before any sync and written only after sync + RECORD check + real import
proof (as the plan requires). `venv_integrity` must count a dist-info without RECORD as damage (today `_record_files` treats it as a
legacy install, "never a finding"), and must parse RECORD itself: Python 3.12's `importlib.metadata` `Distribution.files`
silently drops files that no longer exist. Use `--compile-bytecode` to match pip (first `import torch` without it: 27.7 s).

## 7. Smart App Control and Mark of the Web

The test ZIP held `uv.exe`/`uvx.exe`/`uvw.exe`, a copy of the managed Python and a uv venv (launchers and the `pytest.exe`
trampoline). It was tagged with the standard Internet-zone `Zone.Identifier` stream a browser writes (`ZoneId=3`, the official
uv URL as `HostUrl`) and extracted through Explorer's ZIP handler (`Shell.Application`), which propagated `ZoneId=3` to all 4,109
files. Under enforcing SAC, from that MOTW-tagged tree: `uv.exe`, `uvx.exe`, managed `python.exe` (loading MOTW-tagged `_ssl`,
`_ctypes`, `sqlite3`, `_tkinter`, `_lzma`, `_bz2`), managed `pythonw.exe`, the venv `python.exe` and `pythonw.exe` launchers
(uv's own 262 KB launchers, not pip's) and `pytest.exe` all ran; **zero Code Integrity events**. The same set ran without MOTW.
Only uv is signed; PBS Python and both launcher families are unsigned, as today. Fallback if a trampoline is ever blocked:
`python -m <module>` (verified for pytest). The MOTW tag was applied by writing the stream, not by a browser download; behaviour
on another machine (cloud reputation) is not proved by HOME-PC.

## 8. Path depth and relocation

Deepest paths relative to the ACT root (characters; base with bytecode, as pip leaves it):

| Location | Deepest file | Deepest native library |
|---|---|---|
| `.venv\` (base, unchanged from today) | 154 | 119 |
| `files\runtime-data\uv\cache\` (cu128 torch header) | **175** | n/a (not loaded) |
| `files\runtime-data\uv\python\cpython-3.12.15-windows-x86_64-none\` | 163 | 93 |
| Kokoro / Qwen3 / OmniVoice / Chatterbox environment (either A1 layout) | 165 / 164 / 168 / **173** | 134 / 131 / 135 / 138 |

Today's limits are `bootstrap.DEEPEST_FILE_CHARS = 172` and OmniVoice's 176. The cache and the Chatterbox environment exceed
172, so with long paths off the ACT root may be at most 83 characters (259 − 1 − 175), against 86 today. A shorter cache name
(for example `files\runtime-data\uvc\`, −5) would bring it to 170. Long paths are on here and were not changed: the off case is
computed, NOT RUN. uv's temporary extraction folders were not measured separately.

Relocation (a mini root holding its own managed Python, cache, base and a sibling engine): **moved** — uv found the Python at
the new path, reported the old environments as linked to a missing interpreter, removed and recreated both offline from the
root's own cache, all `home` paths inside the new root. **Copied with the original still present** — uv still recreated both
against the copy's own interpreter (`only-managed` with the install dir inside the copy), never reaching back. The minor-version
junction kept pointing at the old root until `uv python install --reinstall` refreshed it. A Git Bash `cp -r` copied the
junction as a 150 MB real folder.

## 9. Existing verified store and download estimates

- The base store (`files/runtime-data/python-packages`, 170 artifacts) **seeds a uv base environment offline** (`uv pip sync
  --require-hashes --no-index --find-links`, 21.5 s, sdists built from the store's own setuptools), and `uv sync --locked
  --offline` accepts that environment as matching the PyPI-sourced `uv.lock`. It does **not** seed uv's cache: uv's cache is keyed
  by the lock's artifact URL, `--find-links` cannot substitute, so offline repair needs the cache filled once.
- One-time downloads per migrated Windows install (from the locks, plus HTTP sizes for the PyTorch wheels): base 0 (store seed)
  or 0.49 GiB (to fill the repair cache); Kokoro 0.01 GiB beyond base (the spaCy model); Chatterbox 0 beyond base; Qwen3 about
  2.9 GiB (torch 2.10.0+cu128 is 2.87 GB); OmniVoice about 3.4 GiB (manifest total 3.41 GiB). All five deduplicated: about
  6.7 GiB. macOS (3B): base 0.34 GiB, OmniVoice 0.25 GiB.
- This phase downloaded about 3.5 GiB in total (uv 15.6 MB, PBS 46 MB, resolution metadata about 41 MB, base 0.49 GiB, Qwen3
  about 2.9 GiB, small items). Peak footprint in `uv-3a` about 16 GiB apparent; free space never fell below 20 GB.

## 10. Remaining Windows limitations

Long paths off, a second Windows machine, Windows 10, a standard user and a fresh install are untested. SAC reputation is
machine- and time-dependent. `require-build-hashes` is still experimental in uv. The PyTorch index gives `uv.lock` no sizes,
so consent wording needs sizes from the manifests or HTTP. The uv-owned minor-version junction lives inside runtime data, so
ACT's link-refusing checks must tolerate exactly that one. OmniVoice installation, real synthesis and the in-app worker route
are untested under uv.

## 11. Phase 3B (HOME-MacOS) requirements

1. uv 0.13.10 `aarch64-apple-darwin` archive: digest from the release `.sha256` and the GitHub asset digest; code signature
   and quarantine (`com.apple.quarantine`) behaviour of a browser-equivalent download.
2. A `cpython-3.12.15-macos-aarch64-none` download pin to the archive `bootstrap_host_macos.sh` pins; byte comparison with today's
   interpreter; one Aqua Tk 9.0.4 window smoke; ssl, venv; no writes to `~/.local`, `~/.cache/uv`, `~/.config/uv`.
3. Base sync from the same `uv.lock` on macOS (169 artifacts), imports; OmniVoice and Kokoro macOS resolution checked as
   installed (MPS visibility only, no model load), within disk.
4. `clone` versus `copy`: in-place damage isolation and physical size on APFS.
5. The A1 recreation behaviour on macOS, relocation (move and copy), `.command` permissions, case sensitivity, path lengths.
6. Native verification of the simplified routine gate path (marker inheritance, stage process groups, case-sensitive routing),
   carried from Phase 1A.

## 12. Decisions requiring the owner

1. **uv pin**: uv 0.13.10 with the digest above.
2. **A2**: uv-managed CPython 3.12.15 + PBS 20261009 through an ACT-owned download pin (exact parity), or accept uv's catalog
   build (20261021 stripped) as a deliberate change.
3. **A1**: independent sibling engine environments `.venv-engines\<engine>\` (recommended; supersedes the 2026-11-13 layout
   for engines) or nested with the aside/restore protocol.
4. **A4 / D-8**: copy mode; base cache kept (about 2 GiB); GPU engines installed with `--no-cache` (recommended), or all cached.
5. Bytecode compiled at install (`--compile-bytecode`; recommended for pip parity).
6. OmniVoice installation proof: authorize it now or carry it to Phase 5B.
7. Phase 3B on HOME-MacOS, or an explicit documented macOS deferral.
