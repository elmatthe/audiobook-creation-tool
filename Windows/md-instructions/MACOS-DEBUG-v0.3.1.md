# Audiobook Creation Tool — macOS Debug, Test & Release Plan (v0.3.0 → v0.3.1)

**For: Claude Code, running on the maintainer's MacBook Pro against the real repo.**
**Goal:** Make the app actually launch and run on macOS, prove every tool works against real
assets, write down the exact fixes (so they can be replayed on Windows), then ship v0.3.1.

> **Reported symptom (must reproduce first):** Double-clicking `setup_and_run.command` opens
> Terminal, prints the session-save lines, then immediately shows `[Process completed]`. **No app
> window opens. No error is shown. The in-app Log stays empty.** The Windows launcher works fine,
> and the screenshot shows the GUI *does* render once running (M4B Converter, 41 files imported,
> "FFmpeg detected", "Convert M4Bs → MP3s" produces nothing in the log). So there are likely **two
> distinct problems**: (1) the macOS launcher exits before/at GUI start, and (2) the M4B
> conversion itself may not be doing anything on macOS. Investigate both.

---

## Operating Rules for This Session

- **The cloned repo on this Mac is the source of truth.** Read the real files. Do **not** assume
  the code matches anything in this document — every code reference below is a *hypothesis to
  verify against the actual source*, not a fact. If reality differs, follow reality and note it.
- **Never invent code.** When you know exact text, use FIND/REPLACE. When you don't, SEARCH the
  symbol first, read it, then MODIFY.
- **Preserve every working system.** Windows must keep working. macOS-specific fixes go behind
  `sys.platform == "darwin"` branches inside the shared code — do **not** fork the trees. The repo
  invariant is that `Windows/scripts/` and `MacOS/scripts/` stay byte-identical (the README says
  this is hash-verified); any fix you make in one tree must be mirrored into the other.
- **Test data:** the maintainer placed all 41 `.m4b` files in a `test-files/` folder in the repo
  root. Use it. Do not commit it (it should already be excluded by `release.py`; confirm it's in
  `.gitignore`).
- **Don't push anything destructive.** Work on a branch. The push step is the very last thing, and
  only after the test matrix is green.

---

## Step 0 — Orient (read before touching anything)

Run these and read the output. They tell you what you're actually working with.

```
sw_vers                      # macOS version
which python3 && python3 -V  # system python
which brew                   # is Homebrew present?
which ffmpeg ffprobe         # is ffmpeg on PATH?
ls -la                       # repo root — confirm the "exactly 5 items" + test-files/
cat setup_and_run.command
ls -la MacOS MacOS/scripts MacOS/scripts/shared MacOS/scripts/mp3_tools
cat MacOS/scripts/shared/version.py
ls -la MacOS/.venv 2>/dev/null || echo "NO .venv yet"
```

Things to confirm and write down:
- The exact macOS version (relevant: Python 3.12 availability, Tk/Tcl, Gatekeeper behaviour).
- Whether `MacOS/.venv` already exists (a half-built venv from a failed first run is a classic
  cause of silent re-launch failure).
- The launch chain: `.command` → bootstrap/launcher. Map out exactly what calls what.

---

## Step 1 — Reproduce the silent exit (the headline bug)

The `[Process completed]` with no error means **stdout/stderr is being swallowed** — almost
certainly because the `.command` launches the GUI **detached / backgrounded** (so Terminal can
auto-close) and any crash on the Python side dies into a closed pipe. Confirm by running the
launch path *in the foreground* so you can see the real traceback:

```
# Run the .command's launch logic manually, foregrounded, capturing everything.
# (Read setup_and_run.command first to get the EXACT python + script path it uses.)
cd MacOS
# If a venv exists, use its python directly so you see the real error:
./.venv/bin/python scripts/launcher.py 2>&1 | tee /tmp/abt_launch.log   # adjust path to match the .command
# If there is no venv, run the bootstrap foregrounded:
python3 scripts/shared/bootstrap.py 2>&1 | tee /tmp/abt_bootstrap.log    # adjust to match
```

**Hypotheses to check (verify each against the real code, don't assume):**

1. **Detached launch hides the crash.** The README/Briefing note the macOS `.command` uses
   `osascript` / a detached launch to auto-close Terminal ("best-effort"). If the GUI process is
   spawned detached and then crashes on import, the user sees a clean `[Process completed]` and
   nothing else. **Fix direction:** on first run, or when a `--debug` flag/env var is set, launch
   the GUI in the **foreground** and only detach on the fast-path once the venv is known-good; and
   always **tee Python stdout/stderr to `resources/logs/launch_YYYY-MM-DD.log`** so a crash is
   never invisible. Read `shared/logging_setup.py` and `shared/paths.py` to see where logs go.

2. **macOS GUI needs the framework Python, not a plain `python3`.** Tkinter apps on macOS must run
   under a Python that's linked against a Tk that has a Cocoa event loop. A venv created from a
   Homebrew `python3` is usually fine, but a venv created from a *non-framework* or a pyenv build
   can fail to open a window (or crash with a Tcl/Tk error). Check what `bootstrap.py` selects as
   the base interpreter for the venv. **On macOS, GUI apps also frequently need to be launched so
   AppKit can attach to the windowserver** — running detached without a controlling terminal can
   matter. Verify `import tkinter; tkinter.Tk()` works under the venv python:
   ```
   ./.venv/bin/python -c "import tkinter; r=tkinter.Tk(); print('tk ok', r.winfo_screenwidth()); r.destroy()"
   ```

3. **`pythonw.exe` assumption leaked into the Mac path.** The whole console-suppression design is
   Windows-specific (`pythonw.exe`, `CREATE_NO_WINDOW`, `STARTUPINFO`). Grep the launcher + bootstrap
   + `subprocess_utils` for `pythonw`, `CREATE_NO_WINDOW`, `STARTUPINFO`, `.exe`, `Scripts\\` (the
   Windows venv bin dir is `Scripts/`, macOS is `bin/`). Any of these reached unguarded on darwin
   will raise — and if that raise happens in the detached launch, it's invisible.
   ```
   grep -rn "pythonw\|CREATE_NO_WINDOW\|STARTUPINFO\|Scripts/\|\.exe" MacOS/scripts | grep -vi "windows\|win32\|sys.platform"
   ```
   For each hit, confirm it's inside a `sys.platform == "win32"` / `os.name == "nt"` branch. If not,
   that's a bug.

4. **Venv bin path divergence.** Windows venv → `.venv/Scripts/python.exe`; macOS venv →
   `.venv/bin/python3`. If the `.command` or bootstrap hardcodes `Scripts/` or `python.exe`, the
   fast-path launch silently no-ops or errors. This is a prime suspect for the headline symptom.

5. **Half-built / stale venv.** If a previous run created `MacOS/.venv` but failed mid-install, the
   fast-path may "find" a venv, try to launch, and die on a missing dependency. Test: delete the
   venv and re-run bootstrap foregrounded.
   ```
   rm -rf MacOS/.venv && cd MacOS && python3 scripts/shared/bootstrap.py 2>&1 | tee /tmp/abt_bootstrap.log
   ```

6. **Gatekeeper quarantine.** If the zip was downloaded via browser, files carry
   `com.apple.quarantine`. Usually that produces a *dialog*, not a silent exit, but rule it out:
   ```
   xattr -l setup_and_run.command
   xattr -dr com.apple.quarantine .   # only if quarantine xattrs are present
   ```

**Deliverable for Step 1:** the actual Python traceback (or the exact reason there is none), and a
one-line root-cause statement for the silent exit.

---

## Step 2 — Fix the launch path

Apply the minimal fix that makes the app open reliably on macOS, guided by what Step 1 found.
Likely changes (only the ones that match the real root cause):

- **Make crashes visible.** In the macOS launch path, redirect the GUI process's stdout+stderr to a
  timestamped file under `resources/logs/` (reuse `paths.py` + `logging_setup.py`), even on the
  detached fast-path. A user should be able to open the log folder (the GUI already has an "Open log
  folder" link, per the screenshot) and see why a launch died.
- **Correct the venv interpreter path** for macOS (`bin/python3`, not `Scripts/python.exe`).
- **Guard all Windows-only console-suppression code** behind `sys.platform`/`os.name` so it's never
  reached on darwin.
- **Foreground the first run** (where the venv is being built) so install errors are visible, and
  only auto-close/detach on subsequent fast-path launches once the venv is verified.
- If `osascript` auto-close is the thing eating the error, gate it so it only runs after a
  successful launch handshake (e.g. the GUI writes a "started" marker), not unconditionally.

Use the instruction format below for each edit. Example (adjust to real code):

```
FILE: MacOS/scripts/shared/bootstrap.py
SEARCH: def venv_python(
THEN MODIFY: ensure it returns <venv>/bin/python3 on darwin and <venv>/Scripts/python.exe on win32;
read the function first and confirm which branch is wrong.
```

```
FILE: MacOS/scripts/launcher.py
SEARCH: pythonw
THEN MODIFY: confirm every pythonw / CREATE_NO_WINDOW / STARTUPINFO reference is win32-guarded;
add the missing guard if not.
```

After each fix, re-run the foreground launch from Step 1 until the window opens cleanly **and** the
log file shows a clean startup. Then test the **double-click** path the user actually uses (open the
`.command` from Finder) — the foreground python working is necessary but not sufficient; the
`.command` wrapper is what the user runs.

> **Mirror to Windows tree:** after the macOS fix is verified, port the *same* edits into
> `Windows/scripts/...` so the trees stay identical. Re-run `python -m py_compile` on both trees and
> diff them (`diff -r Windows/scripts MacOS/scripts` — expect zero diff, or only the documented
> intentional `sys.platform` branches if any are file-level).

---

## Step 3 — The M4B Converter "nothing happens" bug

The screenshot shows: 41 files imported, "FFmpeg detected", **"Do NOT write any metadata (use
filenames only)" is checked**, output folder set, then "Convert M4Bs → MP3s" clicked — and the log
shows only `FFmpeg detected.` with no conversion progress. Investigate whether conversion actually
runs on macOS.

Read `MacOS/scripts/mp3_tools/m4b_converter.py` and `shared/ffmpeg_utils.py` carefully. Check:

1. **Does the worker thread actually start, or does it raise immediately and silently?** The Briefing
   says tool subprocess calls route through `shared/subprocess_utils`. If `subprocess_utils` applies
   `STARTUPINFO`/`CREATE_NO_WINDOW` unconditionally, the very first ffmpeg call on macOS raises
   `ValueError`/`TypeError` and the worker dies — and if that exception isn't surfaced to the log
   queue, the log stays at "FFmpeg detected." Confirm `subprocess_utils` is fully win32-guarded and
   that worker exceptions are caught and **logged** (not swallowed).
   ```
   grep -rn "STARTUPINFO\|CREATE_NO_WINDOW\|creationflags\|startupinfo" MacOS/scripts/shared/subprocess_utils.py
   ```

2. **ffmpeg/ffprobe resolution on macOS.** `ffmpeg_utils.py` resolves bundled `resources/bin/` first,
   then PATH. The macOS zip almost certainly has **no bundled `resources/bin/` ffmpeg** (it's
   excluded from releases and Windows-specific). Confirm it correctly falls through to the
   Homebrew/system `ffmpeg` on PATH (the log says "FFmpeg detected", so detection works — but verify
   the actual command list uses the resolved absolute path and that pydub is pinned to it via
   `configure_pydub()`).

3. **Reproduce headless.** Run the converter's `main()` standalone against `test-files/` to get a
   real traceback without the GUI in the way (the Briefing says each tool module has a standalone
   `main()` for debugging):
   ```
   cd MacOS/scripts
   ../.venv/bin/python -m mp3_tools.m4b_converter   # or whatever the module's debug entry is — read it first
   ```
   And try a single raw conversion by hand to prove ffmpeg + the chosen args work on this Mac:
   ```
   ffmpeg -i "../../test-files/<one file>.m4b" -codec:a libmp3lame -qscale:a 2 /tmp/test_out.mp3
   ```
   If the manual ffmpeg works but the app's call doesn't, the bug is in how the app builds/launches
   the command (path quoting, the subprocess wrapper, the worker thread, or the cancel/queue plumbing).

4. **Filename-only mode path.** The "Do NOT write any metadata" box is checked. Make sure that code
   path is implemented on macOS and doesn't early-return or skip the conversion loop.

**Deliverable for Step 3:** either a confirmed fix that makes conversion run and write MP3s into the
output folder with live log progress, or a precise root cause if it's environmental.

---

## Step 4 — Full feature test matrix on macOS

Run **every tool** live against real assets and record PASS/FAIL with notes. The README/Briefing
list six tools; the macOS column has never had a live pass, so treat every cell as unverified.

For each: launch the app via the real double-click `.command`, exercise the tool, confirm output
files land in the expected `Downloads/<Tool>-N` (or chosen) folder, confirm the **live log streams**,
and confirm **Cancel** stops cleanly with temp cleanup.

| # | Tool | Test to run | Pass criteria |
|---|------|-------------|---------------|
| 1 | **M4B Converter** | Import several files from `test-files/`, filename-only mode, convert | MP3s written, log streams per-file, Cancel works |
| 2 | **MP3 Tool** | Take a few of the just-made MP3s: Combine (with gap + timestamp sheet), Time-edit, Bulk ID3 | Each op produces correct output; timestamp sheet written |
| 3 | **M4B Maker** | Build a chaptered `.m4b` from those MP3s + a cover image + series name/part | Single `.m4b` with chapters, cover, and Audiobookshelf series atoms (verify with `ffprobe`) |
| 4 | **Cover Image Converter** | Letterbox and center-crop a JPG/PNG (and HEIC if available) | Square output, both modes, correct overwrite behaviour |
| 5 | **M4B Metadata Editor** | Open one `.m4b` (pre-fill check), then a batch (blank check); edit a field; "Clear All Tags (keep chapters)"; chapter-title import | Blank preserves, filled overwrites, clear keeps chapters, series read-back correct |
| 6 | **TTS Audiobook** | Edge TTS on a short TXT/EPUB; (Kokoro only if Python < 3.13 and you're willing to pull multi-GB — otherwise SKIP and note why) | Edge produces an MP3; Cancel cleans temp; note Kokoro status |

Cross-cutting checks for every tool:
- No Terminal/console window flashes (the macOS equivalent of the Windows no-console requirement).
- Worker exceptions appear in the in-app **Log**, never silently swallowed.
- Output folders auto-create and "Open Output Folder" / "Open log folder" reveal in Finder
  (`shared/subprocess_utils.reveal_in_file_manager` must use `open` on darwin, not Explorer).
  ```
  grep -rn "explorer\|reveal_in_file_manager\|open -R\|subprocess" MacOS/scripts/shared/subprocess_utils.py
  ```

**Deliverable for Step 4:** the matrix above, filled with PASS / FAIL(reason) for macOS.

---

## Step 5 — Sweep the whole macOS repo for other platform bugs

Beyond the two headline bugs, audit for latent Windows-isms that would bite on macOS:

```
# Windows-only APIs / paths reached unguarded:
grep -rn "pythonw\|\.exe\|Scripts/\|CREATE_NO_WINDOW\|STARTUPINFO\|winget\|explorer\|os.startfile\|\\\\\\\\" MacOS/scripts \
  | grep -vi "sys.platform\|win32\|os.name\|# windows"

# Hardcoded path separators / backslashes:
grep -rn "\\\\Users\|C:\\\\\|\\\\\\\\" MacOS/scripts

# Home/Downloads handling — must use pathlib + expanduser, not string concat:
grep -rn "Downloads\|expanduser\|Path.home\|HOMEPATH\|USERPROFILE" MacOS/scripts

# Subprocess calls that bypass the shared wrapper (should be ZERO in tool code):
grep -rn "subprocess\." MacOS/scripts/mp3_tools MacOS/scripts/tts | grep -v subprocess_utils

# Static check everything compiles under this Mac's python:
cd MacOS && python3 -m compileall scripts -q && echo "compileall OK"
```

For each finding: confirm whether it's actually reachable on darwin, and either fix it (mirrored to
Windows) or document why it's safe. Pay attention to:
- `bootstrap.py` Homebrew path (`brew install python@3.12 ffmpeg`) — does it handle Apple Silicon
  (`/opt/homebrew`) vs Intel (`/usr/local`) brew prefixes? Does it handle brew being absent (open the
  install page rather than crash, per the README's promise)?
- The `.command` Terminal auto-close `osascript` — confirm it doesn't fire before the GUI is up
  (which is likely the headline-bug culprit).
- HEIC support in the Cover tool (Pillow needs `pillow-heif` or similar; confirm it's in
  `requirements.txt` or that HEIC degrades gracefully).

---

## Step 6 — Write the verified fix report (the artifact the maintainer carries to Windows)

Produce a second markdown file in the repo root or `MacOS/md-instructions/`, named
**`MACOS-FIX-REPORT-v0.3.1.md`**, that the maintainer will drop onto the Windows PC for Claude Code
to replay. It must contain:

1. **Root causes** — one short paragraph per distinct bug found, with the file + symbol.
2. **Exact patches** — every change as FIND/REPLACE or SEARCH/THEN-MODIFY blocks, with the real
   before/after code (now that you know the real code). These must be precise enough to apply
   verbatim on Windows.
3. **Which tree each patch lands in** — and confirmation the trees are identical after.
4. **Test results** — the filled Step 4 matrix, plus the `ffprobe` output proving series atoms.
5. **Anything macOS-only** — e.g. brew prefix handling — clearly flagged as "no-op on Windows".
6. **Regression note** — confirm Windows still compiles (`py_compile`) and the diff between trees.

Keep it copy-pasteable and unambiguous. This file is the whole point of the exercise.

---

## Step 7 — Version bump, changelog, commit, release v0.3.1

Only after Steps 1–6 are done and the matrix is green:

1. **Bump version** — `MacOS/scripts/shared/version.py` (and Windows mirror) from `0.3.0` → `0.3.1`.
   Confirm `version.py` is the single source of truth the README/`release.py` read from.
2. **Update `CHANGELOG.md`** — move `[Unreleased]` to `[0.3.1] - <today>`, with **Fixed** entries
   for the launch crash and the M4B conversion bug, plus any sweep fixes. Note "first live macOS
   pass" and which test-files assets were used.
3. **Update README** download links/status if they're version-pinned (they currently read v0.1.x in
   the project copy — confirm against the real repo and update to v0.3.1; flip the "macOS untested"
   limitation to "verified live on macOS <version> against real assets").
4. **Branch + commit:**
   ```
   git checkout -b fix/macos-launch-and-convert-v0.3.1
   git add -A
   git status                     # SANITY: confirm test-files/ and .venv are NOT staged
   git diff --cached --stat
   git commit -m "Fix macOS launch crash and M4B conversion; first live macOS pass (v0.3.1)"
   ```
5. **Build the release zips** with the maintainer's packaging tool (read it first; the README points
   to `release.py`):
   ```
   python MacOS/scripts/shared/release.py      # or Windows/... — read which it expects
   ls -la dist/
   ```
   Confirm `dist/AudiobookTool-MacOS-v0.3.1.zip` and the Windows zip are produced and exclude
   `.venv/`, `__pycache__/`, `*.pyc`, logs, settings, `resources/bin/`, and `test-files/`.
6. **Push and create the GitHub release.** Confirm the maintainer is authenticated (`gh auth status`)
   and the remote is correct (`git remote -v` → `elmatthe/audiobook-creation-tool`):
   ```
   git push -u origin fix/macos-launch-and-convert-v0.3.1
   # Open a PR or merge to main per the maintainer's preference, then tag + release:
   git checkout main && git merge --no-ff fix/macos-launch-and-convert-v0.3.1
   git tag v0.3.1
   git push origin main --tags
   gh release create v0.3.1 \
     dist/AudiobookTool-MacOS-v0.3.1.zip dist/AudiobookTool-Windows-v0.3.1.zip \
     --title "v0.3.1 — macOS launch + conversion fixes" \
     --notes-file MACOS-FIX-REPORT-v0.3.1.md     # or a trimmed release-notes file
   ```

   > **Pause before pushing.** Show the maintainer the final diff, the changelog entry, and the
   > `dist/` contents, and get an explicit go-ahead. Tags and releases are public and awkward to undo.

---

## Verification Checklist (must all be true before Step 7's push)

- [ ] Double-clicking `setup_and_run.command` opens the GUI window reliably (cold start *and*
      fast-path), no silent `[Process completed]`.
- [ ] Any launch failure now writes a visible traceback to `resources/logs/`.
- [ ] M4B Converter converts the `test-files/` assets to MP3 with live log progress; Cancel works.
- [ ] All six tools pass the Step 4 matrix on macOS (or have a documented, defensible SKIP).
- [ ] No console/Terminal window flashes during any operation.
- [ ] `python3 -m compileall scripts` clean on **both** trees; `diff -r` shows the trees identical
      (modulo documented platform branches).
- [ ] `MACOS-FIX-REPORT-v0.3.1.md` exists and is copy-pasteable for the Windows replay.
- [ ] `version.py` = 0.3.1, CHANGELOG updated, README status/links updated.
- [ ] `dist/` zips built and exclude venv/caches/logs/settings/bin/test-files.
- [ ] Maintainer approved the release before the push.

---

## Notes

- **Two bugs, not one.** Don't stop at making the window open — the screenshot strongly implies the
  conversion itself is also silently no-op-ing on macOS. Both must be green.
- **The recurring failure mode is "swallowed exception."** Detached launch + a worker thread that
  catches-and-drops exceptions = invisible failures. A good chunk of this fix is *making errors
  visible*; that alone will likely reveal the rest.
- **Keep the trees identical.** Every macOS fix is mirrored to Windows behind a platform guard, so
  the Windows replay from the fix report should be near-mechanical.
- **Don't pull Kokoro/PyTorch unless you mean to** — it's multi-GB. Edge TTS is enough to verify the
  TTS tool; note Kokoro as SKIP if you don't download it.
- This document's code references are *hypotheses*. The cloned repo wins every time.
