# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

---

## 2026-07-08 — AI-WORKSPACE.md and files/vibe-coding-templates/ are excluded from version control

**Decision:** Neither `AI-WORKSPACE.md` nor `files/vibe-coding-templates/` is tracked in git,
effective this session. Both are listed in `.gitignore`. `AI-WORKSPACE.md` stays on disk as the
authoritative *local* reference for this machine's conventions (including the HOME-MacOS
section), but is never committed. `files/vibe-coding-templates/` is permanently removed from the
tree and is not referenced in any doc.

**Why:** Privacy — `AI-WORKSPACE.md` contains private machine/workspace details that should not
be published to the public GitHub repo; the vibe-coding-templates were workspace scaffolding
with no role in the shipped tool. Upstream commits that delete `AI-WORKSPACE.md` (e.g.
`9c89479`) are therefore correct and must not be reverted.

**Alternatives considered:** committing a redacted `AI-WORKSPACE.md` (rejected — the file's
value is the private local detail; a redacted copy adds maintenance for no benefit); keeping the
templates as dev-only reference (rejected — they duplicate the workspace tooling that lives
outside the repo).

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-08

---

## 2026-07-08 — Shared progress widget lives in ui_theme.py; M4B Maker progress is deliberately indeterminate

**Decision:** Per-tool run progress is one shared class,
`shared.ui_theme.ProgressIndicator` (ttk.Progressbar + counter/percentage label,
main-thread-only `update / set_indeterminate / reset / finish` API), placed in
`ui_theme.py` — **not** in `launcher.py` — and rendered inside each tool's own
layout near its action buttons/status area. Updates are marshaled exclusively
through each tool's existing worker queue (`("progress", (done, total))` /
`("progress_ind", text)` payloads) and applied only in the main-thread drain,
the same channel that feeds each Log box. Determinate wherever a real total
exists (M4B Converter / Cover Image / M4B Metadata per file, MP3 Tool per
track/file, TTS per batch file / Kokoro chunk / Edge paragraph). The **M4B Maker
build is deliberately indeterminate**: it is a single ffmpeg concat/encode with
no observable sub-steps, so the bar animates while working and shows 1/1 on
success rather than faking a percentage. Do not "fix" the Maker to determinate
without a real progress source.

**Why:** `ui_theme.py` is the shared UI module every tool already imports, and
tools also run standalone via their own `main()` while `launcher.py` imports
the tools — placing the widget in the launcher would invert that dependency.
Inventing Maker percentages (e.g. ticking on log lines) would display made-up
numbers; the drop explicitly prefers an honest indeterminate bar.

**Alternatives considered:** launcher-owned status-bar progress (rejected —
tools must work standalone, and per-tool placement keeps the bar next to the
action it describes); parsing ffmpeg `-progress` output for a real Maker
percentage (viable future improvement, but new subprocess plumbing — out of
this drop's scope).

— Decided and implemented by Claude Code per drop
`0.5.0-ux-progress-and-metadata-layout.md`, 2026-07-08

---

## 2026-07-08 — Panel wheel scrolling: crossing events on the wrap frame + Tcl-level NotifyInferior guard

**Decision:** Scroll-on-hover for canvas-based panels is provided by
`shared.ui_theme.enable_mousewheel(scroll_target, hover_region)`: `<Enter>` on the
hover region installs a `bind_all("<MouseWheel>")` handler, `<Leave>` removes it —
but a Leave whose crossing detail is `NotifyInferior` (the pointer merely moved into
a CHILD widget, still inside the region) is ignored. The Leave side is deliberately
bound **at the Tcl level** (`widget.tk.call("bind", …, "+cmd %d")`), not via
`widget.bind()`, because tkinter's event substitution has no `%d` — `event.detail`
does not exist on Python-level events (verified live on Tk 9.0.3), so a pure-tkinter
guard silently never fires. Do not "simplify" this back to a tkinter-level bind.

**Why:** The TTS options canvas is fully covered by its form frame, so the old
Enter/Leave-on-the-canvas wiring never armed the wheel handler in normal use
(wheel/trackpad scrolling simply did nothing, on Windows too). Binding on the wrap
frame arms it anywhere over the panel; without the inferior-guard the binding tears
down the moment the pointer touches any child control, which is the same bug again.

**Alternatives considered:** binding `<MouseWheel>` recursively on every descendant
(fragile — widgets created later are missed); `winfo_containing` hit-testing on every
Leave (heavier, same result); Button-4/5 bindings (X11-only, irrelevant on
macOS/Windows). Listbox/Text widgets in the other tools scroll natively via Tk class
bindings and intentionally do not use the helper.

— Implemented by Claude Code per maintainer instruction, 2026-07-08

---

## 2026-07-08 — macOS launcher uses the native aqua theme, not a Finder-styled clam

**Decision:** On macOS the launcher applies ttk's native `aqua` theme (with a
`TclError` fallback to the classic clam look for Tk builds without aqua). The
Finder-style chrome — tinted source-list sidebar, hover/selection rows, toolbar,
content card — is built from **classic tk widgets** colored via macOS *semantic*
system colors resolved at runtime in `shared/ui_theme.py`; all six tool panels keep
native aqua ttk controls. Windows/other platforms take the classic branch, which
reproduces the pre-v0.5.0 look byte-for-byte.

**Why (both tested live on this Mac, Tk 9.0.3, dark mode):** aqua gives real native
controls in every tool panel and automatic light/dark adaptation for free, which a
Finder-styled clam would have to fake and maintain by hand. aqua's one limit — it
ignores background styling on native-drawn ttk widgets — is confined to the launcher
chrome, hence the classic-tk sidebar. Fonts use the `.AppleSystemUIFont` alias for
San Francisco (SF Pro Text/Display are NOT installed font families on macOS 26);
alpha-based semantic colors flatten through `winfo_rgb`, so secondary/hover/separator
shades are computed blends instead.

**Alternatives considered:** Finder-styled `clam` everywhere (rejected: non-native
controls in all six panels, manual dark-mode); PyObjC/AppKit for true vibrancy
(rejected per drop constraint — no heavy deps for a visual effect; flagged as an
optional future decision).

— Decided and implemented by Claude Code per drop `0.5.0-macos-ui-shell.md`, 2026-07-08

---

## 2026-07-07 — macOS venv must be built on Python 3.12 for Kokoro; 3.13+ is a degraded fallback only

**Decision:** Kokoro's PyPI wheels require Python >=3.10,<3.13, so the venv base on macOS
must be 3.12 (the `PREFERRED_PY` sweet spot). `bootstrap.py` now enforces this in two
places: (1) `run_setup` no longer accepts a >=3.13 interpreter as-found — it first calls
`install_python` (brew `python@3.12` + `python-tk@3.12`) and only keeps the newer
interpreter if 3.12 truly cannot be installed; (2) `_create_validated_venv` detects an
existing venv built on >=3.13 and rebuilds it once a Kokoro-compatible (<3.13) base is
available, closing the "3.13 venv is reused forever" gap. Python 3.13+ is accepted only
as a degraded fallback: Edge TTS works, Kokoro voices are disabled (the requirements
marker `kokoro==0.9.4 ; python_version < "3.13"` skips the wheel, and the self-heal
repair cannot install it either). The compatibility range lives in one helper,
`_is_kokoro_compatible`.

**Why:** A live Mac run (2026-07-07, only Homebrew python3.13 present) built the venv on
3.13.7; every launch-time Kokoro self-heal then failed with "No matching distribution
found for kokoro==0.9.4" — an environmental failure, unfixable from `kokoro_synth.py`.
The old flow only ran `install_python` when NO interpreter was found at all, so a
3.13-only Mac never attempted the 3.12 install, and the fast path reused the bad venv
forever.

**Alternatives considered:** pinning a newer Kokoro that supports 3.13 (none exists —
the newest 3.13-compatible release on PyPI is 0.7.16, an older API); fixing inside
`kokoro_synth.py` (rejected — the package can never be installed on 3.13, so no
synth-side change helps). The Windows path is unaffected: it selects `py -3.12`
directly and never enters these branches.

— Root-caused and implemented by Claude Code per maintainer instruction, 2026-07-07

---

## 2026-07-07 — Kokoro pause fields: paragraph maps to the inter-chunk gap; full parity deferred

**Decision:** For Kokoro voices, the GUI's "After each paragraph block" field drives
`kokoro_file_to_mp3(chunk_pause_ms=…)` (the silence appended after every ~3000-char
synthesis chunk) and "End of recording" drives `end_silence_ms`. The Between-sentences,
After-title, and Before-chapter fields intentionally do **nothing** on Kokoro voices.
Full per-sentence/title/chapter parity requires sentence-level synthesis inside
`kokoro_synth` (Edge gets it from per-sentence clips) — that is a deliberate deferral to
its own future drop and needs maintainer sign-off to expand. Do not "fix" the missing
parity piecemeal in a bug hunt.

**Why:** The Drop 3 plan scoped Kokoro timing to paragraph + end pause to keep the drop
tractable and avoid a synth rewrite. Kokoro chunks are split on ~3000-char sentence
boundaries, not paragraphs, so the mapping is approximate by design.

**Alternatives considered:** sentence-tokenizing inside kokoro_synth (a rewrite — its own
drop); leaving all pause fields dead on Kokoro (rejected — silently ignoring visible GUI
fields is worse than an approximate mapping).

— Decided by maintainer via drop `drop3-plan`, implemented by Claude Code, 2026-07-07

---

## 2026-07-07 — No AI co-author trailers in commit messages, ever

**Decision:** All commits on this repo are authored solely by the maintainer. Commit
messages are plain text with **no trailers of any kind** — in particular, never a
`Co-Authored-By: Claude ...` (or any Claude/Anthropic co-author) line. Claude appears
only in whatever tooling/log metadata arises naturally, never as an author or co-author.

**Why:** Maintainer is the sole author and sole committer on this repo (stated
2026-07-07 when a co-author trailer was about to be added to the Drop 1 commit).
Applies to Drops 2–5 and all future work — future sessions must not add the trailer
by default.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-07

---

## 2026-07-06 — One commit per drop for the entire v0.5.0 sequence (not per phase)

**Decision:** For all of v0.5.0 — Drop 1 (restructure), Drop 2 (metadata), Drop 3 (TTS),
Drop 4 (script hardening), and the final UI drop — work through every phase of a drop
back-to-back with **no git commits per phase**. Checkpoint progress only via
`md-instructions/handoff.md` (work log) and the session task list. When a drop's final
bug-hunt/verify phase is fully green, stop and present a final summary; the maintainer
reviews and then a **single commit covering the whole drop** is made, followed by a
maintainer-triggered push/force-push. The agent never pushes.

**Why:** Maintainer wants to review + force-push each drop as a single unit. This
overrides the AI-WORKSPACE.md default of committing after each completed phase for the
rest of the v0.5.0 line — future sessions must not default back to per-phase commits.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code

---

## 2026-07-06 — Runtime-writable data lives in `files/runtime-data/` + `files/bin/`

**Decision:** All state the app writes at runtime goes under `files/`: session/setup/launch
logs in `files/runtime-data/logs/`, persisted settings at `files/runtime-data/settings.json`,
the ~300 MB Kokoro HuggingFace cache at `files/runtime-data/models/huggingface/`, and the
portable-ffmpeg fallback in `files/bin/`. All gitignored. `shared/paths.py` keeps the
`RESOURCES_DIR` name pointing at `files/runtime-data/` so the code diff stayed minimal.

**Why:** Maintainer ruled out `scripts/resources/` and OS user-data dirs (Q4): keeping
everything in-tree preserves the "delete the folder to fully uninstall" property; `files/`
is the AI-WORKSPACE home for non-script assets. Alternatives: `%APPDATA%`-style dirs
(rejected — scatters state, breaks portable uninstall).

— Decided by maintainer (layout details by Claude Code), 2026-07-06

---

## 2026-07-06 — Restructured to the AI-WORKSPACE standard layout (v0.5.0 Drop 1)

**Decision:** Unified the two mirrored per-OS root trees into
`scripts/{Universal,Windows,MacOS}` + dev-only `files/` + one `md-instructions/` set, venv at
the repo root, launchers renamed to `Setup_and_Run-audiobook-creation-tool.*`.

**Why:** The mirrored trees had to be kept byte-identical by hand and duplicated every doc —
pure drift risk with zero benefit (Phase-0 diffs proved the trees identical). Alternatives:
keep mirrored trees (rejected — drift, double docs). Consequences: all imports/paths rewired
once; future OS work goes in `Universal/` unless truly platform-specific.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Almost everything lives in `scripts/Universal/`

**Decision:** The entire application is cross-platform code in `Universal/`;
`scripts/Windows/` and `scripts/MacOS/` are empty (.gitkeep) by design.

**Why:** The two per-OS `scripts/` trees were byte-identical except two unused legacy files
(`mp3_tools_launcher.py`, `tts/setup_env.py` — deleted, maintainer Q2); platform differences
are `sys.platform` branches inside shared code and stay that way. Consequence: a file only
moves out of `Universal/` when it genuinely cannot be shared.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Version 0.5.0, not 0.3.x

**Decision:** This restructure line is **v0.5.0**.

**Why:** v0.3.1 is tagged and v0.4.0 released; a MINOR bump keeps linear history honest.
Alternatives: 0.3.2 (behind already-released history), 1.0.0 (deferred for a stability
milestone).

— Decided by maintainer via drop 0.5.0-drop1

---

## 2026-07-06 — `verify.py` adopted as the mechanical gate

**Decision:** `scripts/verify.py` (from the workspace `verify-template.py`) must print
`RESULT: PASS` before any drop is considered done: pytest suite in `files/tests/` (fails on
"no tests collected"), every dependency `==`-pinned, permanent docs de-templated.

**Why:** No mechanical pass/fail gate existed; releases relied on manual checklists.
Consequence: every phase/drop now ends with the same objective check.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code
