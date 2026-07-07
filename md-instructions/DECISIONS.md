# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

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
