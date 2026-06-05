# Windows Release Handoff — v0.3.1

One-shot working doc (macOS tree only; **not mirrored to Windows/** and excluded from the release
zips by `release.py`). It carries everything needed to finish the v0.3.1 release from the Windows PC.

## What is already done (from the Mac)

- The full v0.3.1 patch is committed and **pushed to GitHub** on a branch.
  - **Branch on GitHub:** `release-v0.3.1`
  - **Release commit:** `49bb51a` (`49bb51ab038b9019cdef095cdedd3b098aebf591`)
  - **Tag:** `v0.3.1` — **annotated**, already pushed, points at commit `49bb51a`.
  - **Remote:** `https://github.com/elmatthe/audiobook-creation-tool.git`
- Verified on the remote with `git ls-remote`: `refs/heads/release-v0.3.1` = `49bb51a`,
  `refs/tags/v0.3.1` resolves to commit `49bb51a`.
- Both trees compile; the Win↔Mac `scripts/` trees are byte-identical except the two pre-existing
  unused legacy files (`mp3_tools/mp3_tools_launcher.py`, `tts/setup_env.py`) that already differed.

## What is left to do (on Windows)

1. Fast-forward `release-v0.3.1` into `master`, then push `master`.
2. Build the release zips **from the Windows tree** (so Windows packaging is proven end-to-end).
3. Create the GitHub Release `v0.3.1`, marked latest, with both zips attached.

## Merge convention (why fast-forward)

`origin/master` has **zero merge commits** and every previous tag (`v0.1.0`–`v0.3.0`) sits directly on
the `master` line — the project history is strictly linear. So `release-v0.3.1` must be **fast-forward
merged** into `master` (no merge commit). `release-v0.3.1` is `master` + the v0.3.1 commit (+ this
handoff commit), so the fast-forward is guaranteed.

> Note: the `v0.3.1` **tag** stays on the release commit `49bb51a`; the later handoff-doc commit rides
> along into `master` during the fast-forward (it lives in `md-instructions/`, so it never ships). This
> matches the existing pattern where small follow-up commits land on `master` after a tagged release.

## Exact Windows commands (run in order, from the repo root)

```bat
git fetch origin
git checkout master
git pull --ff-only origin master
git merge --ff-only origin/release-v0.3.1
git push origin master

REM Build the zips fresh on Windows (proves Windows packaging works on this release):
python Windows\scripts\shared\release.py

REM Save the "Release notes body" section below as release-notes-v0.3.1.md (repo root),
REM then create the release from the existing tag, marked latest, with both zips:
gh release create v0.3.1 ^
  dist\AudiobookTool-Windows-v0.3.1.zip ^
  dist\AudiobookTool-MacOS-v0.3.1.zip ^
  --repo elmatthe/audiobook-creation-tool ^
  --latest ^
  --title "v0.3.1 — first live macOS pass" ^
  --notes-file release-notes-v0.3.1.md
```

Notes:
- The tag `v0.3.1` already exists on the remote (pushed from the Mac), so `gh release create v0.3.1`
  attaches the release to that existing tag — it does **not** create a new tag.
- `release.py` reads the version from `Windows/scripts/shared/version.py` (= `0.3.1`) and writes
  `dist/AudiobookTool-Windows-v0.3.1.zip` and `dist/AudiobookTool-MacOS-v0.3.1.zip`. `dist/` is
  gitignored.
- **Rebuild the zips on Windows rather than using the Mac-built ones**, so Windows packaging is proven
  on this release. The Windows-built and Mac-built zips should have **zero substantive content
  difference** (same committed tree, same `release.py`) — only file ordering / timestamps differ. The
  Mac build was already verified: `md-instructions/` is excluded; `.venv/`, `__pycache__/`, `*.pyc`,
  `resources/logs/`, `resources/settings.json`, `resources/bin/`, `test-files/` are excluded;
  `README.md` + the correct launcher are at each zip root; `setup_and_run.command` extracts as `0o755`.

## Release notes body — save this as `release-notes-v0.3.1.md`

```markdown
## v0.3.1 — first live macOS pass

The macOS build is now verified end-to-end on real hardware (macOS 26.3.1, Apple
Silicon) against real audiobook assets. Six macOS launch / UX / packaging issues found
during that pass are fixed. All fixes are guarded by platform checks (or live in the
macOS-only launcher) and are mirrored into the Windows tree; Windows behaviour is
unchanged.

### Fixed
- **Launch crash from Gatekeeper App Translocation.** Opening the downloaded
  `setup_and_run.command` straight from Downloads could run it from a temporary,
  read-only copy with no program folder beside it, so it exited silently with no
  window. The launcher now detects this and shows a clear, persistent message: move
  the whole folder out of Downloads (or right-click → Open).
- **Invisible launcher-startup crash.** A failure while the app window was starting
  could vanish with no window and no log. The window's output is now captured to a
  dated log under `resources/logs/`, and a failed start is reported instead of
  silently swallowed.
- **"Terminate running processes" dialog on close.** After the app starts, the macOS
  setup Terminal window now closes cleanly, without the terminate-processes prompt.
- **Download could ship a non-executable launcher.** Packaging now always marks
  `setup_and_run.command` executable inside the zip, so it runs on a double-click
  with no `chmod` needed.
- **TTS Audiobook layout.** The log is now a clearly labelled, multi-row pane, the
  options scroll, and the Start / Cancel buttons stay visible at every window size.
- **M4B Maker fast path with an external cover image.** Building an M4B with a
  separate cover image no longer falls back to the slower path — the cover is
  embedded directly.

### Notes
- The Kokoro local AI voices require Python 3.11–3.12; on a Python 3.13 system the app
  uses Microsoft Edge TTS (online) for narration.
```
