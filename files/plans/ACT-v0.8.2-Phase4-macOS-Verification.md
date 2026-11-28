# ACT v0.8.2 Phase 4 — native macOS verification (HOME-MacOS)

Status: **instructions, not yet run.** Phase 4 (production uv-based base provisioning) is implemented for both platforms and verified on
Windows (HOME-PC, `Handoff.md` "Verification and Evidence"). Nothing of Phase 4 has run on a Mac. This file is what an agent (or the owner)
runs on HOME-MacOS, with the owner present, to close that gap. It installs uv and the managed CPython into disposable copies and downloads
about 0.4 GB of packages, so it needs the owner's authorization for that run (GATE.md interim rule). It is temporary: delete it from
`files/plans/` once its results are recorded in `Handoff.md` and the plan.

## Rules for this run

- Work only in disposable copies under the HOME-MacOS checkout's ignored `files/dev-work/p4m/`. Never touch the checkout's own `.venv/`,
  `files/runtime-data/`, the owner's daily-use copy of the app, or the owner's uncommitted work (never reset, stash, stage or overwrite it).
- No global installation, no `sudo`, no PATH, shell-profile, Homebrew, `/usr/local` or security-setting change. Nothing quarantined is
  copied in (never transfer an interpreter through a browser download or AirDrop).
- No model download, no synthesis. The app window is opened exactly once (step 4), by the owner, and closed.
- Record every command's exit code and wall time. Remove `files/dev-work/p4m/` at the end and say how much space it freed.

## 0. Bring the checkout to the Phase 4 commit

```bash
cd <HOME-MacOS checkout>
git status --short                      # note the owner's uncommitted work; it must look the same at the end
git fetch origin && git merge --ff-only origin/0.8.2   # refuses rather than touch conflicting local work
git log -1 --oneline                    # the Phase 4 commit
```

Global snapshot (before), kept for step 10:

```bash
mkdir -p files/dev-work/p4m
for d in ~/.local/share/uv ~/.cache/uv ~/Library/Caches/uv ~/.config/uv ~/.local/bin ~/Library/Application\ Support/uv; do
  if [ -e "$d" ]; then echo "$d exists $(find "$d" | wc -l) $(stat -f %m "$d")"; else echo "$d absent"; fi
done > files/dev-work/p4m/global-before.txt
echo "PATH=$PATH" >> files/dev-work/p4m/global-before.txt
```

## 1. Gate corrections D1-D3 (Phase 3B report §7) on the checkout's existing `.venv`

The gate reads its pytest pin from `pyproject.toml`'s `dev` group (9.1.1, unchanged), so the v0.8.1 `.venv` still runs it.

```bash
.venv/bin/python files/dev-work/verification-gate/verify.py --mode quick
.venv/bin/python files/dev-work/verification-gate/verify.py --mode focused \
  --test files/tests/test_gate_scratch_exception.py --test files/tests/test_uv_provisioning.py \
  --test files/tests/test_bootstrap_host_macos.py --test files/tests/test_macos_foundation.py \
  --test files/tests/test_bootstrap_requirements_state.py --test files/tests/test_venv_integrity.py
```

Then rerun the ten selectors of the Phase 3B run `2026-11-27_153203_focused_0c84` (FAIL on D1/D2 then): expected PASS, `cleanup` PASS,
no false "process group" survivor; and `verify.py --audit-scratch` while a focused run is active must not call that run's scratch abandoned (D3).

## 2. A fresh source copy (spaces and accents in the path)

```bash
COPY="$PWD/files/dev-work/p4m/Livres été/ACT"
mkdir -p "$COPY" && git archive --format=tar HEAD | tar -x -C "$COPY"
cd "$COPY"
time bash scripts/shared/bootstrap_host_macos.sh --out-file files/temp/bootstrap/selected-python.txt   # answer y once
PY="$(cat files/temp/bootstrap/selected-python.txt)"; echo "$PY"
"$PY" -c "import sys, ssl, tkinter; print(sys.version); r = tkinter.Tk(); r.withdraw(); r.destroy()"
```

Expect: uv `uv-aarch64-apple-darwin.tar.gz` and the CPython archive verified (the script prints both checks) and kept under
`files/runtime-data/uv/` (`mirror/20261009/` holds the archive); `$PY` is
`files/runtime-data/uv/python/cpython-3.12.15-macos-aarch64-none/bin/python3.12`; no Gatekeeper prompt; `xattr -l` on `uv` and `$PY` shows no
`com.apple.quarantine`.

## 3. Cold install, then the warm path

```bash
time "$PY" scripts/shared/bootstrap.py --headless --skip-kokoro-download
cat .venv/pyvenv.cfg                      # home = …/cpython-3.12.15-macos-aarch64-none/bin, uv = 0.13.10, version_info 3.12.15
"$PY" -c "import json; r = json.load(open('.venv/.act-environment.json')); print(r['manager'], r['profile'], r['health'], len(r['distributions']))"
du -sh .venv files/runtime-data/uvc; df -h .   # clone: the environment's physical cost is far below its logical size
for i in 1 2 3; do /usr/bin/time -p bash scripts/shared/bootstrap_host_macos.sh --out-file files/temp/bootstrap/selected-python.txt --assume-no; \
  /usr/bin/time -p .venv/bin/python scripts/shared/bootstrap.py --venv-check; done
```

Expect exit 0 everywhere, `user` profile, `{"record": "ok", "imports": "ok", …}`, about 167 distributions (no pytest), `--venv-check` exit 0
well under a second.

## 4. The app opens (owner, once)

`open Setup_and_Run-audiobook-creation-tool.command` from Finder or Terminal: the launcher window opens on the uv environment; close it.
Note anything unusual (a Gatekeeper prompt, a Terminal window that stays).

## 5. Package damage and the targeted in-place repair

```bash
rm .venv/lib/python3.12/site-packages/tqdm/__init__.py
.venv/bin/python scripts/shared/bootstrap.py --venv-check; echo "exit $?"         # 3: damaged-packages
REPAIR='import sys; sys.path.insert(0, "scripts"); from shared import bootstrap as b; b.allow_downloads(MODE); ok, m = b.repair_venv(b.LOG, headless=True); print(ok, m); sys.exit(0 if ok else 1)'
time HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 "$PY" -c "${REPAIR/MODE/False}"
```

Expect "reinstalled; the rest of the environment was kept", offline (dead proxy), `.venv/bin/python` unchanged (`stat -f %m`).

## 6. Cache damage

Corrupt one byte of tqdm's `std.py` inside the repair cache (`find files/runtime-data/uvc/archive-v0 -path '*tqdm/std.py'`), then remove
`.venv/lib/python3.12/site-packages/tqdm/__init__.py` again.

- `"$PY" -c "${REPAIR/MODE/False}"` (downloads refused): fails, downloads nothing, the environment is left as it was.
- `"$PY" -c "${REPAIR/MODE/True}"` (online): "fetching them again", `Removed 42 files`, then every file matches its record.

## 7. Relocation, offline

```bash
cd "$OLDPWD"; mv "files/dev-work/p4m/Livres été" "files/dev-work/p4m/Moved été"; cd "files/dev-work/p4m/Moved été/ACT"
readlink files/runtime-data/uv/python/cpython-3.12-macos-aarch64-none           # still the old folder
HTTPS_PROXY=http://127.0.0.1:9 bash scripts/shared/bootstrap_host_macos.sh --out-file files/temp/bootstrap/selected-python.txt --assume-no
readlink files/runtime-data/uv/python/cpython-3.12-macos-aarch64-none           # now this folder
PY="$(cat files/temp/bootstrap/selected-python.txt)"
.venv/bin/python scripts/shared/bootstrap.py --venv-check; echo "exit $?"        # 3
time HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 "$PY" -c "${REPAIR/MODE/False}"
```

Before the repair, add a stand-in engine and fingerprint it: `mkdir -p .venv/engines/omnivoice && echo stand-in > .venv/engines/omnivoice/marker.txt`;
`find .venv/engines -type f -exec shasum -a 256 {} \; -exec stat -f '%m %N' {} \;` before and after must be identical.

## 8. Interruption

Start the repair of step 7 again after breaking `.venv/pyvenv.cfg`'s `home`, and `kill -9` the repairing process group while uv syncs
(`pgrep -fl "uv sync"`). Then `.venv/bin/python scripts/shared/bootstrap.py --venv-check` (if `.venv` is the half-built candidate, run the
check with `"$PY"`): "an earlier environment repair did not finish"; rerun the repair: "restoring the environment it had set aside", then a
successful rebuild with the engine identical.

## 9. Legacy migration and the not-yet-migrated engine route

Make a second copy (step 2 into `files/dev-work/p4m/Legacy/ACT`, stage 0 only), then give it a v0.8.1 shape: clone the legacy
interpreter in (`cp -cR <a v0.8.1 copy>/files/runtime-data/python files/runtime-data/python`; the checkout's own is fine to read, never to
change), `files/runtime-data/python/bin/python3.12 -m venv .venv`, `files/runtime-data/python/bin/python3.12 -m venv --without-pip
.venv/engines/omnivoice`, and a marker file. Fingerprint the engine and the legacy interpreter (`find … -type f | sort | xargs shasum -a 256`
plus `stat -f %m`). Then:

- `.venv/bin/python -c "import sys; sys.path.insert(0, 'scripts'); from tts import omnivoice_runtime as ov; print(ov.app_owned_python())"`:
  the legacy interpreter (legacy layout);
- break the lock (`sed -i '' 's/"tqdm==4.67.3"/"tqdm==4.67.2"/' pyproject.toml`), repair: rolls back, everything identical; restore the
  line (`git -C <checkout> show HEAD:pyproject.toml > pyproject.toml`);
- repair offline: the environment is uv's (`pyvenv.cfg` has `uv = 0.13.10`), the engine and the legacy interpreter are identical, the
  carried engine still runs (`.venv/engines/omnivoice/bin/python -c "import sys; print(sys._base_executable)"`);
- the same `app_owned_python()` call now prints the managed interpreter.

## 10. Global state after, cleanup, report

Repeat the snapshot of step 0 into `global-after.txt`; `diff` must be empty. Run `git status --short` in the checkout: identical to step 0
apart from the Phase 4 files the fast-forward brought. Remove `files/dev-work/p4m/` and report the space freed.

Report back (to `Handoff.md` "Verification and Evidence", macOS): each step's result and timing; the clone evidence (physical versus logical
size); any prompt, quarantine attribute or Terminal behaviour; the D1-D3 gate runs; anything that failed, exactly as it failed.
