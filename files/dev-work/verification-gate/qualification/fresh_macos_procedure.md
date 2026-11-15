# `fresh-macos` qualification — the written procedure (v0.8.x, D9b)

The `fresh-macos` scenario is **mandatory** before a macOS release. Its *automation* is optional (D9b): until a runner
exists, `verify.py --scenario fresh-macos` reports **NOT RUN**, and the scenario is satisfied only by the owner's run of
this procedure with a signed evidence record naming the candidate SHA. The verdict always carries its evidence class.

| Evidence class | Where | Satisfies |
|---|---|---|
| `SIMULATED` | this development Mac (Homebrew and the CLT present but hidden; PATH-restricted, linkage-verified) | nothing on its own; P1A exit only |
| `P6a-rehearsal` | the P6a dry-run archive, on whatever machine P6a uses (labelled SIMULATED or REAL CLEAN as that machine is) | the P6a rehearsal |
| `REAL CLEAN` | an Apple Silicon Mac, physical or virtual, that never had Homebrew, the Xcode CLT or a python.org install (D18). A new user account on this Mac is **not** REAL CLEAN | **P7c (binding)** — the exact release archive |

A SIMULATED result is never reported as a clean-Mac result. P1B wrote this contract and procedure only; no
`fresh-macos` run of any class has been made.

## Before you start

1. Record the candidate: the full 40-character SHA the archive was built from, the archive's file name and its SHA-256
   (`shasum -a 256 <archive>`).
2. Record the machine: model and chip (`sysctl -n machdep.cpu.brand_string`), macOS version (`sw_vers`), and for REAL
   CLEAN that `/opt/homebrew`, `/usr/local/bin/brew`, `xcode-select -p` and `/Library/Frameworks/Python.framework` are
   all absent.
3. Download the archive **with a browser**, so it is quarantined as a user's download is. Confirm with
   `xattr -p com.apple.quarantine <archive>` (a value is printed).
4. Have a stopwatch or note times; the record wants the duration of stage 0 and of the first run.

## The steps

Each step has an expected result. A step that does not meet it is a **FAIL** of the qualification: stop, record what
was seen (a photo or screenshot is welcome), and do not continue past it.

1. **Extract** the archive by double-clicking it (Archive Utility). Expected: one folder, the
   `Setup_and_Run-audiobook-creation-tool.command` inside it carries the quarantine flag
   (`xattr -p com.apple.quarantine …` prints a value) and is executable (`ls -l` shows `x`).
2. **First double-click** on the `.command`. Expected: macOS blocks it (an unidentified-developer warning). Nothing runs.
3. **Open Anyway**: System Settings › Privacy & Security › *Open Anyway*, confirm with the login password, double-click
   again. Expected: Terminal opens and stage 0 begins. (Since macOS 15, Control-click › Open no longer overrides
   Gatekeeper; the README's guidance must match what you see — note any difference.)
4. **Stage 0 and consent**: every download is named and asked for before it starts; answer yes. Expected: the app-owned
   arm64 Python and FFmpeg are fetched and hash-verified, no admin password is asked for, and nothing is written to
   `/Library`, `/usr/local` or `/opt`.
5. **First run**: the app window opens. Expected: the window is in front with keyboard focus, and the Terminal window
   closes itself (record any Automation prompt it shows, MAC-039). Record the name the menu bar and the Dock show for
   the app and whether the Dock icon is the app's own (MAC-042).
6. **All six tools open**: select each tool in the sidebar (TTS, MP3 Tool, M4B Converter, M4B Maker, M4B Metadata
   Editor, Cover Resizer). Expected: each panel draws completely, with no error dialog.
7. **Quit** with Cmd+Q. Expected: the window closes and no `python` or `ffmpeg` process of the app remains
   (Activity Monitor, or `pgrep -fl Audiobook-Creation-Tool`).
8. **Damage the environment**: rename `.venv/bin/python3` inside the extracted folder to `python3.broken`.
9. **Repair**: double-click the `.command`. Expected: the launcher reports the environment as damaged, repairs it with
   consent, and the app opens again.
10. **Relaunch**: Cmd+Q, then double-click the `.command` once more. Expected: the app opens without any download.
11. **Interrupted install**: start an optional install that downloads (the smallest offered), and close its Terminal
    window or press Ctrl+C partway through the download. Expected: nothing half-installed is left that the app treats
    as installed.
12. **Recovery**: double-click the `.command` again and retry the same install. Expected: it completes, and the app
    reports it installed.
13. **Afterwards**: the folders outside the app (`~/Library/Caches`, `~/.cache`, `~/Library/Application Support`,
    `/usr/local`) hold nothing the app wrote; no app process is running.

## The signed evidence record

Save one JSON file per run at
`files/dev-work/macos-acceptance/evidence/<full SHA>/qualification--fresh-macos.json` (an ignored location):

```json
{
  "sha": "<the full 40-character candidate SHA>",
  "signed_by": "<the owner's name or initials>",
  "signed_at": "<date and time>",
  "result": "PASS or FAIL",
  "evidence_class": "SIMULATED, P6a-rehearsal or REAL CLEAN",
  "archive": {"name": "<file name>", "sha256": "<digest>", "downloaded_with": "<browser>"},
  "machine": {"model": "", "chip": "", "macos": "", "clean_checks": "<step 2 of Before you start, as seen>"},
  "steps": {"1": "PASS", "2": "PASS", "3": "PASS", "4": "PASS", "5": "PASS", "6": "PASS", "7": "PASS",
            "8": "PASS", "9": "PASS", "10": "PASS", "11": "PASS", "12": "PASS", "13": "PASS"},
  "notes": "<anything that differed from the expected result, and timings of stage 0 and the first run>"
}
```

A record whose `sha` is not the candidate's, that is unsigned, or whose `result` is not `PASS`, satisfies nothing.
P7c accepts only `"evidence_class": "REAL CLEAN"` on the exact release archive.
