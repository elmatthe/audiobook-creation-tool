# macOS Fix Report — v0.3.1

**Host:** macOS 26.3.1 (build 25D771280a), Apple Silicon (arm64), Homebrew at `/opt/homebrew`,
system `python3` = 3.13.7 with working `python-tk@3.13`. No Python 3.12 present, so the `.venv` is
built on 3.13 and Kokoro/torch are excluded by the `<3.13` requirements marker. ffmpeg/ffprobe on PATH.

**Scope:** first live macOS pass against the real `test-files/` assets (41 `.m4b` + a cover + a TXT).
Six defects found and fixed. Every code fix is mirrored byte-for-byte into the Windows tree behind
`sys.platform` guards; the only non-mirrored change is the macOS-only entry file
`setup_and_run.command` (Windows uses `setup_and_run.bat`). `compileall` clean on both trees; the
`scripts/` trees diff-clean except the two pre-existing unused legacy files
(`mp3_tools/mp3_tools_launcher.py`, `tts/setup_env.py`) that already differed before this work.

This document is the Windows-side replay artifact: each fix below gives the root cause, the file +
function, and a FIND / REPLACE (or SEARCH → MODIFY) block, plus which tree it lands in. Items flagged
**macOS-only** are no-ops on Windows.

---

## 1. Launch crash — Gatekeeper App Translocation  *(macOS-only; `setup_and_run.command`)*

**Root cause.** Double-clicking the quarantined `setup_and_run.command` (it arrives quarantined from
any browser/zip download) made macOS run it from a temporary, read-only **translocated** copy that
contains only the `.command` — its `MacOS/` program folder is *not* beside it. The old script then ran
`cd "$HERE/MacOS"` (under `set -u`, no guard), the `cd` failed, and the script exited **before Python
ever started** — no window, no log, `.venv` untouched. That is exactly the reported "Terminal flashes,
prints a couple of lines, `[Process completed]`, no window, empty log".

**Evidence.** The quarantine xattr was present at session start and **gone** after the maintainer's
Gatekeeper "Open" approval; the maintainer's double-click produced **zero** new entries in
`resources/logs/` (the bootstrap writes a setup header instantly when Python runs), and the venv was
untouched. A path probe on a correct (non-translocated) launch recorded:

```
2026-06-03 22:40:29  HERE=…/audiobook-creation-tool  MacOS_exists=yes  PWD=/Users/elijahmatthew
```

i.e. when launched normally the `MacOS/` sibling resolves; under translocation it does not. The fix is
gated on exactly that condition (missing `MacOS/` sibling, or an `/AppTranslocation/` path).

**FIND** (the unguarded resolve-then-cd in `setup_and_run.command`):

```bash
HERE="$(cd "$(dirname "$0")" && pwd)"

cd "$HERE/MacOS"
```

**REPLACE** (resolve, then guard, then cd):

```bash
HERE="$(cd "$(dirname "$0")" && pwd)"

# ---- Gatekeeper "App Translocation" guard -------------------------------
# A quarantined download opened straight from Finder may run from a temporary,
# read-only randomized copy that contains only this .command — its MacOS/
# program folder is NOT beside it. The old code then failed `cd "$HERE/MacOS"`
# and exited silently ("Terminal flashes, no window"). Show a clear, persistent
# message and KEEP THE WINDOW OPEN instead of dying silently.
if [ ! -d "$HERE/MacOS" ]; then
    translocated=no
    case "$HERE" in
        */AppTranslocation/*) translocated=yes ;;
    esac
    cat <<'EOF'

============================================================
  Audiobook Creation Tool — can't start from here
============================================================

macOS is running this launcher from a temporary, read-only copy
(Gatekeeper "App Translocation"), so it cannot find its program
files. This happens when the app is opened straight from a
Downloads or unzipped-in-place location.

To fix it (one time):

  1. In Finder, move the WHOLE "audiobook-creation-tool" folder
     OUT of Downloads — for example onto your Desktop or into
     Applications.
  2. Open that moved folder and double-click setup_and_run.command
     again.

Moving the folder in Finder clears the translocation. (Alternatively,
right-click setup_and_run.command -> Open, then confirm the prompt.)

EOF
    if [ "$translocated" = yes ]; then
        echo "  Detected translocated path:"
        echo "    $HERE"
        echo
    fi
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
fi

cd "$HERE/MacOS" || { echo "Could not find the MacOS folder next to this script."; exit 1; }
```

**Tree:** macOS only (no Windows equivalent — `.bat` cannot translocate).

---

## 2. Terminal "terminate running processes" dialog on close  *(new `shared/close_terminal.py`; `.command` wiring is macOS-only)*

**Root cause.** The fast path closed its own Terminal window with `osascript` **while `bash` +
`osascript` were still alive in that window**. Closing a Terminal window that still has running
processes raises the "Do you want to terminate running processes? (bash, osascript)" prompt. Verified
empirically (windows identified by tty; a blocking modal leaves the window open): a self-close from
within the doomed window is *blocked* by the modal (window stays open) — that is the dialog. An
*external* detached process closing the window after `bash` exits closes it cleanly.

**Fix.** Spawn the GUI fully detached (it already uses `start_new_session=True`), and hand the
window-close to a helper that **detaches into its own session (`os.setsid`)**, waits for the launching
`bash` to exit, then closes the window matched **by tty** — by which point the window has no running
process, so the close is silent. Verified on a real double-click: GUI comes up, the Terminal window
auto-closes, no dialog (reproducible across repeats).

**ADD new file** `scripts/shared/close_terminal.py` (**both trees**; no-op on non-`darwin`):

```python
#!/usr/bin/env python3
"""Detached helper that closes the launcher's Terminal window cleanly on macOS.
... (see file for full docstring) ...
"""
from __future__ import annotations
import os, subprocess, sys, time


def main() -> int:
    if sys.platform != "darwin":
        return 0
    tty = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not tty:
        return 0
    try:
        os.setsid()           # leave the launcher window's session/process group
    except OSError:
        pass
    time.sleep(1.2)           # let the launching bash exit first
    script = (
        'tell application "Terminal"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      try\n"
        f'        if (tty of t) is "{tty}" then close w saving no\n'
        "      end try\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
    )
    try:
        subprocess.run(["osascript", "-e", script],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**FIND** (the old fast-path self-close in `setup_and_run.command`):

```bash
if [ -x ".venv/bin/python" ]; then
    nohup ".venv/bin/python" "$BOOTSTRAP" --launch-only >/dev/null 2>&1 &
    disown 2>/dev/null || true
    osascript -e 'tell application "Terminal" to close (every window whose name contains "setup_and_run")' >/dev/null 2>&1 || true
    exit 0
fi
```

**REPLACE** (foreground launch so a crash is visible + hand close to the detached helper):

```bash
if [ -x ".venv/bin/python" ]; then
    if ".venv/bin/python" "$BOOTSTRAP" --launch-only; then
        # GUI up + detached. Close THIS window without the terminate-processes
        # prompt: a direct osascript close here runs while bash + osascript are
        # alive in this window (which triggers that dialog). A helper detached
        # into its own session waits for this bash to exit, then closes the
        # window (matched by our tty) when nothing is running in it.
        launcher_tty="$(tty 2>/dev/null || true)"
        nohup ".venv/bin/python" "scripts/shared/close_terminal.py" "$launcher_tty" \
            >/dev/null 2>&1 &
        disown 2>/dev/null || true
        exit 0
    fi
    echo
    echo "The app window did not start. Details are in:"
    echo "  MacOS/resources/logs/launch_$(date +%Y-%m-%d).log"
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
fi
```

**Tree:** `close_terminal.py` lands in **both** trees (no-op on Windows); the `.command` wiring is
macOS only.

---

## 3. Packaging could ship a non-executable launcher  *(`shared/release.py`; both trees)*

**Root cause.** `release.py` added the entry launcher with `ZipFile.write(...)`, which stores only the
source file's *current* Unix mode. A dev checkout that lost the `+x` bit (a clone with `core.filemode`
off, a plain file copy) would ship a `.command` extracted as `644`, forcing the user to `chmod +x`.
Both `unzip` and macOS Archive Utility honour the *stored* mode — the risk is purely a non-executable
source at zip time. Verified: 644 source → forced archive entry `0o755` → extracts `755`.

**ADD helper** (in `scripts/shared/release.py`, before `_is_excluded`):

```python
def _write_executable(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
    """Add *src* to the archive as *arcname* with a forced 0o755 mode.

    The double-click launcher MUST be executable the instant a user extracts the
    zip. ``ZipFile.write`` only preserves whatever mode the source happens to
    have, so a checkout that lost its +x bit would ship a non-runnable launcher.
    Storing an explicit rwxr-xr-x makes packaging robust; macOS Archive Utility
    and ``unzip`` both honour the stored mode on extract.
    """
    zi = zipfile.ZipInfo.from_file(src, arcname)
    zi.external_attr = (0o100755 << 16)  # high 16 bits = Unix st_mode (reg file + 0755)
    zi.compress_type = zipfile.ZIP_DEFLATED
    with open(src, "rb") as fh:
        zf.writestr(zi, fh.read())
```

**FIND** (the entry write in `_package_os`):

```python
        zf.write(readme, arcname="README.md")
        zf.write(entry_file, arcname=entry_name)
```

**REPLACE**:

```python
        zf.write(readme, arcname="README.md")
        # Force the launcher executable so a user never has to `chmod +x`.
        _write_executable(zf, entry_file, entry_name)
```

**Tree:** both (`release.py` is mirrored byte-identical). Affects both the Windows `.bat` and the macOS
`.command` entries (harmless for `.bat`, which Windows doesn't mode-check).

---

## 4. TTS Audiobook — log crushed to ~1 px, Start/Cancel off-screen  *(`tts/epub2tts_gui.py`; both trees)*

**Root cause.** The TTS panel's natural height is ~1300 px but the launcher gives it ~660 px. The log
was the only `weight=1` grid row, so Tk grid **shrank it to ~1 px** to fit the fixed content above, and
pushed everything below it (Start/Cancel) **off the bottom of the window**. Measured live before the
fix: log actual height = 1 px (reqheight 404); Start button top y=880 vs window bottom 815. A larger
`height=`/font request can't help because grid discards the weighted row's request when the fixed
content already overflows.

**Fix (three edits in `build_ui`).** (a) Put the dense options in a vertically **scrollable canvas**;
(b) move the footer help text to the end of that scrollable form; (c) pull **Start/Cancel** and a
labelled **12-row monospace "Log" box** out into always-visible bottom rows of the panel. Measured
after: log = 224 px (~12 rows) and both buttons visible at 1024×720 (default), 920×600 (minimum), and
1024×900 (tall).

**SEARCH → MODIFY (a):** replace the single `frm = ttk.Frame(root, padding=10)` setup with a
canvas+scrollbar that hosts `frm`, wired with `<Configure>` handlers (scrollregion + form width) and an
Enter/Leave-scoped `<MouseWheel>` binding. Root grid: row 0 = scroll canvas (`weight=1`), row 1 =
buttons, row 2 = Log box.

**SEARCH → MODIFY (b):** the old in-`frm` `scrolledtext.ScrolledText(frm, height=22, …)` log block is
removed from the scrollable form; the long "Default voice…" footer label is moved to the end of `frm`.

**SEARCH → MODIFY (c):** the old in-`frm` `btn_row`/footer is replaced by always-visible bottom rows:

```python
    # --- Action buttons (row 1): always visible, outside the scroll area. ---
    btn_row = ttk.Frame(root, padding=(10, 8))
    btn_row.grid(row=1, column=0, sticky="w")
    go_btn = ttk.Button(btn_row, text="Start", command=run_job); go_btn.pack(side=tk.LEFT)
    cancel_btn = ttk.Button(btn_row, text="Cancel", command=cancel_job, state=tk.DISABLED)
    cancel_btn.pack(side=tk.LEFT, padx=(8, 0))

    # --- Log box (row 2): labelled, multi-row, always visible (never crushed). ---
    log_font = ("Consolas", 10) if sys.platform == "win32" else ("Menlo", 11)
    logf = ttk.LabelFrame(root, text="Log", padding=(8, 4))
    logf.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
    logf.rowconfigure(0, weight=1); logf.columnconfigure(0, weight=1)
    log = scrolledtext.ScrolledText(logf, height=12, state=tk.DISABLED, wrap=tk.WORD, font=log_font)
    log.grid(row=0, column=0, sticky="nsew")

    pump_queue()
```

The platform difference (log font) is a `sys.platform` branch inside the shared code, so the file stays
byte-identical Win↔Mac. **Tree:** both. (See the file for the full canvas-scaffold block.)

---

## 5. M4B Maker — FAST path fails on an external cover image  *(`mp3_tools/m4b_maker.py`; both trees)*

**Root cause.** In `run_fast_concat`, the output-only option `-filter:a` was appended to the command
**before** the cover `-i` was added. ffmpeg scopes an option to the next file token, so `-filter:a`
became an *input* option for the cover image → `Option filter:a cannot be applied to cover.png`, and the
build fell back to the slower SAFE path (which has no `-filter:a`, hence "self-heals"). The scary log
line and the unnecessary fallback are both eliminated by ordering inputs before output options.

**FIND** (interleaved order — output option emitted before the cover input):

```python
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-y", "-xerror",
        "-f", "concat", "-safe", "0", "-i", str(audio_list_path),
        "-i", str(ffmeta_path),
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-filter:a", "asetpts=N/SR/TB,aresample=async=1:first_pts=0",
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    if cover_path:
        cmd += ["-i", str(cover_path)]
        maps += ["-map", "2:v:0", "-disposition:v:0", "attached_pic",
                 "-metadata:s:v:0", "title=Album cover",
                 "-metadata:s:v:0", "comment=Cover (front)"]
        cmd += ["-c:v:0", "mjpeg"]
    cmd += maps + ["-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart", str(out_path)]
```

**REPLACE** (all inputs first; `-fflags +genpts` stays an input option on the concat demuxer;
`-filter:a` / `-avoid_negative_ts` move to the output section):

```python
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-y", "-xerror",
        "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", str(audio_list_path),
        "-i", str(ffmeta_path),
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    if cover_path:
        cmd += ["-i", str(cover_path)]
        maps += ["-map", "2:v:0", "-disposition:v:0", "attached_pic",
                 "-metadata:s:v:0", "title=Album cover",
                 "-metadata:s:v:0", "comment=Cover (front)"]
    # All inputs declared above; everything below is output options.
    cmd += maps
    cmd += ["-filter:a", "asetpts=N/SR/TB,aresample=async=1:first_pts=0"]
    if cover_path:
        cmd += ["-c:v:0", "mjpeg"]
    cmd += ["-c:a", "aac", "-b:a", bitrate,
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", str(out_path)]
```

**Tree:** both. The SAFE-path auto-fallback is retained as a safety net.

---

## 6. Launcher crash on the fast path was invisible  *(`shared/bootstrap.py`; both trees)*

**Root cause.** On the fast path the `.command`/`.bat` send the bootstrap process's own stdout/stderr
to the void (and on Windows the GUI runs windowless), then `launch_gui()` spawned the launcher
**inheriting those discarded fds** and **returned `True` unconditionally**. So any failure during
launcher import/init (a broken venv, a missing dependency, a Tk failure) died to `/dev/null` with no
window and nothing to diagnose — a clean `[Process completed]`. This is the same class of "silent
launch" symptom as the translocation crash (#1), and it also makes the new `.command` fast-path
else-branch (#2) meaningful: that branch only fires when `launch_gui` actually reports failure.

**Fix.** Redirect the spawned GUI's stdout+stderr to `resources/logs/launch_<date>.log`, watch the
child for `_LAUNCH_GRACE_SECONDS` (1.5 s), and on an immediate non-zero exit surface the captured tail
and **return `False`** instead of a false success. Adds `import time`, a `_tail_text()` helper, and the
`_LAUNCH_GRACE_SECONDS` constant.

**FIND** (old `launch_gui` body — inherits discarded stdio, always returns True):

```python
    """Spawn the launcher GUI detached so this process can exit."""
    ...
    log.line(f"Launching {target.name} via {py.name}…")
    try:
        if IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            subprocess.Popen([str(py), str(target)], cwd=str(SCRIPTS_DIR),
                             env=env, creationflags=flags, close_fds=True)
        else:
            subprocess.Popen([str(py), str(target)], cwd=str(SCRIPTS_DIR),
                             env=env, start_new_session=True)
        return True
    except Exception as exc:
        log.line(f"  ERROR launching GUI: {exc}")
        return False
```

**REPLACE** (capture GUI output to a dated log; watch for an immediate crash; report failure):

```python
    """Spawn the launcher GUI detached so this process can exit.

    The child's stdout+stderr are redirected to resources/logs/launch_<date>.log
    so a crash during import/startup is never invisible. After spawning we briefly
    watch the child: if it dies immediately, the captured output is surfaced and we
    report failure instead of a false success.
    """
    ...
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    launch_log_path = LOGS_DIR / f"launch_{datetime.now():%Y-%m-%d}.log"
    try:
        launch_fh = open(launch_log_path, "a", encoding="utf-8")
        launch_fh.write(f"\n===== Launch {datetime.now():%Y-%m-%d %H:%M:%S} : "
                        f"{py} {target} =====\n")
        launch_fh.flush()
    except Exception:
        launch_fh = None
    log.line(f"Launching {target.name} via {py.name} (GUI output -> {launch_log_path.name})…")
    try:
        kwargs: dict = {"cwd": str(SCRIPTS_DIR), "env": env}
        if launch_fh is not None:
            kwargs["stdout"] = launch_fh
            kwargs["stderr"] = subprocess.STDOUT
        if IS_WINDOWS:
            kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            kwargs["close_fds"] = True
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([str(py), str(target)], **kwargs)
    except Exception as exc:
        log.line(f"  ERROR launching GUI: {exc}")
        return False
    finally:
        if launch_fh is not None:
            launch_fh.close()

    time.sleep(_LAUNCH_GRACE_SECONDS)
    rc = proc.poll()
    if rc is not None and rc != 0:
        log.line(f"  ERROR: the app window failed to start (exited with code {rc}).")
        tail = _tail_text(launch_log_path)
        if tail:
            log.line(f"  --- last lines of {launch_log_path.name} ---")
            for line in tail.splitlines():
                log.line("    " + line)
            log.line("  --- end ---")
        log.line(f"  Full launch log: {launch_log_path}")
        return False
    return True
```

**Tree:** both — the trees-identical rule applies. The macOS `.command` consumes the failure-return
(its else-branch keeps the window open and points at `launch_<date>.log`); the Windows `.bat` does
**not** consume the failure-return today, but the launch-log capture benefits Windows too (a windowless
`pythonw` launcher crash is now written to `launch_<date>.log` instead of vanishing). Honest framing:
the *behavioural* consumer is Mac-only; the *logging* benefit is cross-platform.

---

## Step-4 test matrix — macOS 26.3.1 / Python 3.13 venv, real `test-files/`

PASS/FAIL with an honest note on **GUI** (driven through the real `build_ui` + button handler +
worker/queue) vs **scripted** (driven at the worker function level).

| Tool | What was exercised | How | Result |
|---|---|---|---|
| **M4B Converter** | 41 `.m4b` → MP3, live per-file log + Cancel | **GUI** (maintainer) | **PASS** |
| **M4B Maker** | 3 MP3 + external PNG cover + series → `.m4b`, FAST path | **GUI** | **PASS** (cover + 3 chapters + SERIES/SERIES-PART atoms; **no fallback** after fix #5) |
| **M4B Metadata Editor** | write title/series; preserve untouched album + chapters; series-part autonumber on/off | **GUI** | **PASS** (album + chapters preserved; series-part written only with Auto-number ON — by design) |
| **MP3 Tool** | Combine + 2 s gap + timestamp sheet; Time-edit; Bulk ID3 | scripted (worker) | **PASS** |
| **Cover Image** | letterbox JPG + center-crop PNG → 512² | scripted (worker) | **PASS** |
| **TTS Audiobook** | Edge TTS, TXT → MP3 + mid-run Cancel | scripted (worker) | **PASS** (cancel → `ConversionCancelled`, 0 leaked temp dirs) |
| **TTS Kokoro** | local AI voices | — | **SKIP** (Python 3.13 host; Kokoro needs `<3.13`) |
| **Launch / close UX** | real double-click: GUI up + Terminal auto-closes | **GUI** (real `.command`) | **PASS** (no terminate dialog; maintainer-confirmed) |

---

## macOS-only items (no-op / not present on Windows)

- `setup_and_run.command` — the macOS double-click entry file (translocation guard + close-helper
  wiring). Windows uses `setup_and_run.bat`; neither change touches it.
- `scripts/shared/close_terminal.py` — present in **both** trees for byte-identical mirroring, but
  returns immediately on any non-`darwin` platform, so it is a **no-op on Windows**.
- The TTS log-font line is a `sys.platform == "win32"` branch (`Consolas` vs `Menlo`) inside the shared
  file — the file is identical across trees; only the runtime branch differs.

All other changes (`bootstrap.py`, `release.py`, `epub2tts_gui.py`, `m4b_maker.py`, `version.py`,
`CHANGELOG.md`) are mirrored byte-identical across both trees. `bootstrap.py`'s launch-log capture
applies on both platforms; only its failure-return *consumer* (the `.command` else-branch) is Mac-only.
