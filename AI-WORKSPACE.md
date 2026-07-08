# Global Developer Preferences

This file defines my workflow, preferences, and structure across all projects. It lives in the
root of every repo. Read it at the start of every session and apply these defaults unless a
project-level `CLAUDE.md` / `CODEX.md` or a dropped instruction markdown overrides them.

**The docs I rely on** (each has one job — keep them from bleeding into each other):

| Doc | Answers | Nature |
|-----|---------|--------|
| `AI-WORKSPACE.md` (this file) | Global, cross-project rules | Rarely changes |
| `md-instructions/Briefing.md` | *What the project is* — AI-facing dev README, all features | Broad, slow |
| `md-instructions/CHANGELOG.md` | *What changed over time* — append-only version history | Append-only |
| `md-instructions/DECISIONS.md` | *Why it's built this way* — append-only ADR log | Append-only |
| `md-instructions/handoff.md` | *What's happening now* — live state, bugs, agent notes, sync log | Most volatile |
| `md-instructions/*.md` (drops) | *What to build right now* — one-time plans | Read, do, delete |

Because each doc has a single job, the same fact should live in exactly one of them: reasoning
→ DECISIONS, versions → CHANGELOG, features → Briefing, live state → handoff.

---

## Core Rules — get these right first

These three areas matter most; everything else in this file supports them. Read the linked
sections in full before acting, but the load-bearing rule for each is:

1. **Repo structure — single- vs cross-platform** (§ *Project Structure*). Both use the **same**
   clean root: 5 folders (`.claude/ .codex/ scripts/ files/ md-instructions/`) plus fixed loose
   files, and `.venv/` as the only auto-generated exception. The **only** cross-platform
   difference is that the OS split lives *inside* `scripts/` (`Universal/ Windows/ MacOS/`) —
   the root never forks, and `md-instructions/` is a single set, never split per OS. Also strict:
   `scripts/` = what the program needs to run (ships); `files/` = dev-only (doesn't ship).

2. **The 5 `md-instructions/` files** (§ *The `/md-instructions` Folder*) — four permanent docs
   with one job each, plus the instruction drop, and one fact lives in exactly one of them:
   `Briefing.md` (what the project is) · `CHANGELOG.md` (what changed, versioned) · `DECISIONS.md`
   (why — append-only ADR) · `handoff.md` (what's happening now — live state + cross-device sync
   log) · instruction drops from `Instructions_Template.md` (one-time plans: read → implement →
   verify → **delete**). Never let their contents bleed together.

3. **`Setup_and_Run` launchers** (§ *Setup and Launch Files*). Every repo has two —
   `Setup_and_Run-<project>.bat` (Windows) and `.command` (macOS) — and each is **both**
   first-time setup **and** the daily launcher. They **contain everything in the repo/venv**
   (deps → `.venv`; tools like ffmpeg → `files/bin/`, on PATH for the session only) and install
   onto the machine **only** when a base runtime (Python) is completely missing — that's the one
   time a Y/N and the user-vs-machine scope question appear. They are **self-healing**: delete
   `.venv` or Python and re-running rebuilds to a working state. The macOS file must be a
   `.command` (not `.sh`) so it runs on double-click.

---

## My Machines & Workspace Roots

I work across more than one machine. Use the roots and constraints for whichever machine the
session runs on — paths and permissions differ, so never assume a path from one machine exists
on another. The `claude-skills-main` folder per machine is my local clone of reusable skills;
it sits alongside the workspace roots, not inside a project.

### CSPW-PC — Work Computer

Roots:
```
C:\Users\ematthew\Desktop\Files\Coding_Repositories
C:\Users\ematthew\Desktop\Files\Coding_Repositories\MyProjects\CSPW-PC
C:\Users\ematthew\Desktop\Files\claude-skills-main
```
Portable tools (added to PATH for the session only via `Start-Portable-Development-CSPW.cmd`):
```
C:\Users\ematthew\Portable-User-Installs\PortableGit\{cmd,mingw64\bin,usr\bin}
C:\Users\ematthew\Portable-User-Installs\PortableNodeJS\node-v26.4.0-win-x64
```
Specs: Lenovo ThinkPad T16 Gen 2 (AMD) · Win 11 Pro · Ryzen 5 PRO 7545U (6c/12t) · 32 GB RAM ·
Radeon 740M integrated (**no CUDA**) · 256 GB SSD (**~89 GB free — keep builds lean**) · 2× QHD.

**Permissions — locked down (matters most here):** user `EMatthew` is a **Standard User, no
admin rights.** Can't run `.exe`/`.msi` installers that write to `C:\Program Files` or the
registry (needs an IT password I don't have). Can run local PowerShell (`RemoteSigned`).
**Default approach:** portable apps and fully self-contained in-repo setups that run from
`C:\Users\ematthew\` — nothing system-wide. This is the machine the "contain everything in the
repo and venv" rule matters most for. Notes: no permanent system PATH changes; use `npm.cmd`/
`npx.cmd` (not `.ps1`); GitHub HTTPS auth via Git Credential Manager; Codex may block Git Bash/
SSH subprocesses in its Windows sandbox even though the portable install works normally.

### HOME-PC — Personal Computer

Roots:
```
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces\MyProjects\Home-PC
C:\Users\ematthew\Desktop\Apps\Coding\claude-skills-main
```
Specs: Custom build (MSI MS-7E66) · Win 11 Pro · Ryzen 7 9800X3D (8c/16t) · 32 GB RAM ·
**RTX 5070 (CUDA)** + integrated Radeon · 2 TB SSD (~676 GB free — ample) · 2× monitors.

**Permissions — full access:** user `ematthew` is an **Administrator** (any installer, registry,
`C:\Program Files` via "Run as Administrator"). **CUDA GPU available**, so GPU-accelerated work
(ML, heavier local models) is viable here but not on CSPW-PC.

### HOME-MacOS — Personal MacBook Pro

Roots / specs / permissions: **to be filled in.** Until then, treat any macOS session as
undefined for paths — ask me for the workspace root and machine details before assuming anything.

---

## Vibe Coding Workspace Files

Above and around the individual project repos sits a shared **Vibe Coding Workspace** — the
scaffolding layer that creates and standardizes every new project. It lives one level up from
the workspace roots (e.g. on CSPW-PC: the parent of `Coding_Repositories`, holding
`Coding_Repositories\` plus a sibling `templates\`, `.claude\`, `.codex\`). These files are the
workspace's own tooling, distinct from anything in a project repo, and are not modified
per-project:

```
[coding_root]/
  AI-WORKSPACE.md                          <- this file (copied into every new project root)
  .claude/  .codex/                        <- master agent configs, cloned into new projects
  templates/
    verify-template.py                     <- source for scripts/verify.py
    setup_and_run-templates/
      Setup_and_Run-template.bat           <- Windows setup+launcher source
      Setup_and_Run-template.command       <- macOS setup+launcher source
    md-templates/
      briefing-template.md  changelog-template.md  decisions-template.md
      handoff-template.md  instructions-template.md
  Coding_Repositories/ (workspace_root)
    Create_New_Repo-CSPW.bat               <- scaffolder (work-PC paths)
    Create_New_Repo-HOME.bat               <- scaffolder (home-PC paths)
    Map-Repo-Structure.bat                 <- drop into ANY repo; maps it to REPO-STRUCTURE.md
    Start-Portable-Development-CSPW.cmd     <- CSPW-PC only: portable Git/Node/Claude on PATH
    MyProjects/
      CSPW-PC/  Home-PC/  <individual project repos>
```

- **`Create_New_Repo-*.bat`** — interactive scaffolders (one per machine, fixed paths differ).
  Each validates the template sources, lets me pick a workspace and name a project, creates the
  standard layout, clones `.claude/`+`.codex/`, copies/renames the two `Setup_and_Run` launchers
  (substituting `[PROJECT_NAME]`), copies and de-templates the five core `md-templates/*.md`
  into `md-instructions/` in one PowerShell pass, copies `verify-template.py` → `scripts/verify.py`,
  and writes `README.md`, `.gitignore`, `.env`, `CLAUDE.md`/`CODEX.md`.
- **`Map-Repo-Structure.bat`** — standalone utility (not part of scaffolding). Drop into any repo
  root and double-click; it writes a `REPO-STRUCTURE.md` snapshot (skipping `.git`, `.venv`,
  `__pycache__`, `node_modules`, `files/bin`) to paste to an AI before asking for changes.
- **`Start-Portable-Development-CSPW.cmd`** — CSPW-PC only (no admin). Puts portable Git, Node,
  and Claude Code on PATH for the session, lets me pick a directory then a repo by number, and
  drops me into an interactive PowerShell with tool versions confirmed. No HOME-PC equivalent
  (that machine has admin + standard installs).

The behavior of the launcher, verify, and md-template files is documented in their own sections
below. Treat this layer as infrastructure: edits here affect every future project, so keep the
templates' header comments in sync with this file when either changes.

---

## How I Work With You

Two surfaces:
- **AI chat tool** (Claude.ai, ChatGPT, Gemini) — my planning/thinking layer: designing
  features, interpreting output, writing implementation markdowns, architectural decisions.
- **AI coding agent / CLI** (Claude Code, Codex, Cursor) — my execution layer: it receives those
  plans as markdown and implements them.

Every repo has a `.claude/` and a `.codex/` folder for generic agent setup. I often run **both
Claude Code and Codex** on one project — co-implementing or reviewing each other's work —
coordinating through `handoff.md`.

### CLI prompts must be ONE copyable code block

The most important rule for how the chat layer talks to the CLI layer: when I ask you (the chat
AI) for a prompt/plan to feed a CLI, **put the entire prompt in one fenced code block** so I can
copy it in a single click. Everything the agent must act on goes *inside* that one block — start
to finish, never split, never with a stray actionable line left in prose. Anything meant only
for *me* (manual test steps, permissions to grant, "do this on HOME-PC for CUDA," push/pull
reminders) goes *outside* the block. Rule of thumb: if the agent reads it, it's inside; if only
I read it, it's outside.

### Instruction markdowns are temporary

Read any plan I drop in fully before doing anything; if anything is ambiguous, ask before
starting rather than assuming. Once implemented and verified, delete it — the permanent record
lives in Briefing, CHANGELOG, DECISIONS, and handoff.

---

## Project Structure I Typically Use

Default to this layout when starting or reorganizing a project (follow project-level
instructions if they differ). **If a repo doesn't match, ask whether to reorganize before
proceeding.** Guiding principle: a **clean, minimal root** — instantly obvious what the project
is and how to run it, nothing else.

**Root — nothing else belongs at the top level:**
```
Folders (these 5 only):
  .claude/          <- Claude agent config (settings.json, CLAUDE.md, skills/)
  .codex/           <- Codex agent config  (settings.json, CODEX.md, skills/)
  scripts/          <- everything the PROGRAM needs to run (ships in the release)
  files/            <- everything the DEVELOPER needs (does NOT ship)
  md-instructions/  <- markdown for AIs (Briefing, CHANGELOG, DECISIONS, handoff, drops)
Loose files (these only):
  README.md  AI-WORKSPACE.md  .gitignore  .env
  Setup_and_Run-<project>.bat  Setup_and_Run-<project>.command
Auto-generated (the one exception):
  .venv/   <- created in root by Setup_and_Run; gitignored, rebuilt on demand, never committed
```
A non-technical user who unzips a release should see only the README and the two launchers as
obvious entry points. `.venv/` must live in root because the setup script creates it there and
activation/`requirements.txt` paths assume it.

**The core split — `scripts/` (ships) vs `files/` (doesn't):** be strict.
- `scripts/` — everything the program needs to run from a fresh release zip: every runtime file
  it imports/uses, plus `requirements.txt`.
- `files/` — everything development-only: the pytest suite, test inputs, QA logs, binaries,
  assets, fixtures, scratch.
- The test: *"Does the running program break without this file in a fresh release zip?"*
  Yes → `scripts/`, No → `files/`.

**Contents of `scripts/`:** multi-tool projects have `scripts/launcher.py` as the entry point
plus `requirements.txt` and program scripts (subfolders as needed).

**Cross-platform:** the **root stays identical**. The OS split happens **inside `scripts/`** so
the root never forks:
```
scripts/
  Universal/   <- shared code used by both platforms
  Windows/     <- Windows-only scripts
  MacOS/       <- macOS-only scripts
  requirements.txt   <- shared; split per-OS only if deps genuinely differ
```
`md-instructions/` is a **single set** for the whole project (never split per OS — call out
platform-specific detail inline as "Windows: … / macOS: …"). `files/tests/` may mirror the
`Universal/Windows/MacOS` split if tests differ. Instruction/plan drops are never split by OS —
one file covers both.

---

## The `/md-instructions` Folder

This folder is **for AIs** — where I instruct agents, agents record state, and agents talk to
each other. End users never see it. It holds **five files in total**: four **permanent** docs
(see the table at the top for their one-line jobs) plus the temporary instruction drop. Detail
on each:

**`Briefing.md` — what the project is.** A detailed AI-facing README (more thorough than the
user-facing `README.md`) so a new session understands the whole project without me re-explaining:
purpose and audience; tech stack and key libraries; architecture and major design decisions
(entry point, how pieces fit, data flow); every major feature at a descriptive level; current
version and high-level state.

**`CHANGELOG.md` — what changed over time.** Append-only history by version: every release,
feature, fix, and breaking change under clear version markers. Update whenever a version is cut
or a meaningful change lands. Keep it clean — release history, not a scratchpad or file-diff log.

**`DECISIONS.md` — why it's built this way.** Append-only ADR log capturing the reasoning behind
non-obvious choices so a future session (or bug hunt) doesn't "fix" something deliberate. Add an
entry when: a library/tool was chosen over an obvious alternative; a structural/data-flow choice
isn't self-evident from code; a deliberate trade-off was made ("slower but simpler," "no async
because the user base is small"); a constraint shaped the design (no admin on CSPW-PC, 256 GB
SSD, no CUDA); or anything an agent might otherwise undo. Skip routine bug fixes and obvious
choices. **Append-only, newest on top, never rewrite history** — if a decision is reversed, add
a new entry noting "Supersedes #N" rather than deleting. Sign and date every entry.
```markdown
## 002 — Static ffmpeg over system install — 2026-06-20 — Claude Code
**Status:** Accepted
**Context:** CSPW-PC users have no admin rights; can't install ffmpeg system-wide.
**Decision:** Bundle a static ffmpeg binary in files/bin/, downloaded by Setup_and_Run.
**Alternatives considered:** System install (needs admin); python-only audio libs (too limited).
**Consequences:** Larger release zip; no PC-level install or PATH changes required.
```

**`handoff.md` — what's happening right now.** Most detailed and most frequently updated, but
narrower than Briefing (doesn't re-describe features) and distinct from DECISIONS (logs *state*,
not *reasoning*). Two jobs:
1. **Agent-to-agent working state** — on finishing or picking up work, append a short signed,
   dated entry (done / in progress / blocked / next) so two agents trade work without me
   re-explaining.
2. **Cross-device file-sync log** — because I move between machines via GitHub, log which files
   changed each session so a behind machine can pull exactly what's listed. Before pushing,
   append a dated per-machine entry of files added/changed/deleted (one line each) and make sure
   those changes are actually staged and committed so the log and the commit agree. Starting on
   a possibly-behind machine, read this first, reconcile against `git status`/`git log`, then
   pull.
```markdown
# <Project> — Handoff
## Current Focus
One or two lines on what's actively being worked on.
## Open Issues / Bugs
| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | Critical | scripts/launcher.py | Crash on first run, no config | Open | Codex |
## Work Log (newest first)
- 2026-06-25 — Implemented Phase 3 §4 of plan-x.md; tests pass. — Claude Code
## Session Sync Log (newest first)
### 2026-06-25 — HOME-PC — pushed
- Added:   scripts/Universal/parser.py
- Changed: scripts/launcher.py (wired parser into menu)
- Note:    Parser feature complete; pull these before continuing on CSPW-PC.
```

**Temporary instruction drops** — all other markdown here is a one-time plan: read, implement,
verify, delete. `Instructions_Template.md` is the scaffold I copy for a new one.

---

## The `.claude/skills` and `.codex/skills` Folders

Skills are **reusable capability documents** — a durable pattern an agent loads on demand (how
to generate an Excel workbook my way, write VBA to my conventions, scaffold a tkinter launcher).
Capturing these instead of re-explaining every session improves consistency and saves tokens.
Each skill is its own folder with a `SKILL.md`:
```
/.claude/skills/   (or /.codex/skills/)
  excel-generation/SKILL.md
  vba-macros/SKILL.md
```
Place a new skill under the folder for the agent you are (Claude → `.claude/skills/`, Codex →
`.codex/skills/`); mirror into both only if genuinely agent-agnostic.

**Skill vs. instruction markdown:** a skill is a *durable capability* recurring across projects,
never deleted ("how to do a kind of thing well, every time"); an instruction markdown is a
*one-time plan*, deleted when done. If I'd have to explain it again next session, it's a skill.

**Assemble skills BEFORE coding (research step).** At project start, and when building any plan,
gather the skills the work needs rather than waiting to be told: (1) examine the repo and read
`md-instructions/` — especially the active drop; (2) research skills, checking
`https://github.com/alirezarezvani/claude-skills` first, plus other public repos; (3) copy the
relevant skill files into your own skills folder, taking only what's useful and noting the
source; (4) keep curating as you go, creating a new skill whenever a recurring capability is
missing. List the skills the work needs (and where they come from) in the plan, up front.

---

## The `/files` Folder

Catch-all for everything the **developer** needs but the program **does not ship** — the
counterpart to `scripts/`. Nothing the running program depends on belongs here. Typical
subfolders:
- **`files/tests/`** — the pytest suite (run by `verify`); may mirror `Universal/Windows/MacOS`.
- **`files/test-files/`** — test inputs only: sample files I drop in for the agent to test
  against (a sample PDF for a converter, a spreadsheet for a parser). When verifying, look here
  first; a pytest test typically feeds a fixture from here and asserts the result.
- **`files/test-logs/`** — gitignored manual QA logs, final release pass only.
- **`files/bin/`** — self-contained binaries the setup script downloads (e.g. ffmpeg); gitignored
  unless you intend to commit the binary.
- Assets, icons, fixtures, config templates, build scratch, `__pycache__/`, etc.

---

## Setup and Launch Files

Every repo gets two root launchers from my templates, named for the project:
`Setup_and_Run-<project>.bat` (Windows) and `.command` (macOS). Both behave identically and
serve two purposes: **first-time setup** and **daily launcher** (double-click to run).

**Core philosophy — contain first; install onto the machine only when forced.** Keep as much as
possible *inside the project folder* — pip deps into `.venv`, self-contained tools (a static
ffmpeg) into `files/bin/` added to PATH for that session only. The **one unavoidable exception is
Python itself** (or another base runtime like Node.js): a venv can't be created without an
interpreter, so if it's completely missing it must be installed — and that's the *only* point a
real system install (and the scope question) comes up. If Python already exists, the user is
never prompted about scope.

**The flow for a non-technical user** (assume they've never installed anything, may have no
admin): double-click the `Setup_and_Run` file → a terminal opens and scans for Python and needed
tools → if Python is missing, explain plainly and ask a simple **Y/N** to install it for the
current user only (no admin, never system-wide by default) → create a fresh `.venv` in root and
install deps into it → on every later run, the same file is the launcher.

**Self-healing:** delete `.venv` (to move/shrink/reset) and re-run → it rebuilds from scratch;
remove Python (or another base runtime) and it detects the absence and offers to reinstall.
Re-running always returns to a working state.

**Prompts and scope:**
- **Y/N for big installs only.** Pause before installing Python/a base runtime, or a tool being
  set up because the contained route failed. A contained in-repo tool gets one plain-language
  Y/N framed as "this stays in the project folder, nothing installed on your PC." Never prompt
  per pip package — those install silently into the venv.
- **Scope — only when a system install is forced.** Ask once: **Just for me** (user scope, no
  admin — the safe default) or **For all users** (machine scope, needs admin). Windows: `winget`
  with `--scope user`/`--scope machine`. macOS: user scope via Homebrew (no admin), system-wide
  Python via the official python.org installer. The install must land somewhere writable.

**First-run security block (unavoidable):** downloaded launchers are unsigned, so Windows
SmartScreen/Defender/WatchGuard (or macOS Gatekeeper) blocks the **first** run — no code can
suppress this. Include a short friendly note: Windows → "More info" → "Run anyway"; macOS →
System Settings → Privacy & Security → "Open Anyway." Normal, once only.

**Platform mechanics:** the macOS launcher must be a **`.command`** (not `.sh`) so it opens on
double-click from Finder, with execute permissions (`chmod +x`). The Windows `.bat` keeps the
console open during setup so the user sees a live log, then prompts "press Enter to close."
Suppress unnecessary console popups once the GUI is running.

---

## Python and Script Preferences

- Python is the default, but use whatever fits best — if another language/runtime is clearly
  better, use it and briefly say why. Don't force Python.
- GUIs use `tkinter` unless a project says otherwise.
- Multi-tool projects have a `scripts/launcher.py` entry point: a clean GUI presenting each tool
  as a button/menu item. Suppress console popups when launched from setup.
- Keep scripts modular (one tool per file, called from the launcher), organized in `scripts/`
  with subfolders as needed (and the `Universal/Windows/MacOS` split when cross-platform).

---

## Research Before Building

Do less work by borrowing well-tested code. Order: **skills → GitHub → write it yourself.**
1. **Skills first** — check your skills folder; do the up-front skill research (above) and list
   expected skills in the plan.
2. **Then GitHub** for repos handling the task (e.g. "ffmpeg python wrapper", "tkinter file
   converter gui"). Prefer recent commits, reasonable stars, permissive license (MIT, Apache
   2.0). Read the files to confirm they work and are clean. Prefer a self-contained module over
   a whole framework.
3. **When you borrow:** add only the needed files to the right folder (program → `scripts/`,
   dev-only → `files/`), note the source in the commit message and `CHANGELOG.md`, and comment
   any changes you make to fit. If the choice itself was non-obvious, also log it in `DECISIONS.md`.

If nothing useful turns up after a reasonable search, write it from scratch and say so. Don't
over-search something simple enough to just implement.

---

## Implementation Approach

When given a plan (dropped markdown or direct instruction):
1. **Read everything first**, including current `md-instructions/` state. Understand full scope
   before writing a line.
2. **Identify and gather skills** the task needs; pull in missing useful ones before building.
   List them in the plan.
3. **Research before building** — evaluate existing libraries/repos before writing from scratch.
4. **Phase your work** into small numbered phases. After each, verify mechanically (add/update
   pytest and run `verify`) before moving on — don't chain phases without checkpointing. Update
   `handoff.md` at each checkpoint.
5. **Prefer working code over clever code** — these ship to non-technical users; reliability
   beats elegance.
6. **Don't refactor unrelated code** unless a bug hunt or the plan calls for it. Stay in scope.
7. **If unsure, stop and ask** — don't guess on ambiguous requirements, especially around file
   structure, user-facing behaviour, or data handling.
8. **Log non-obvious choices** in `DECISIONS.md` before moving on.

---

## Testing and Verification

Correctness is **mechanical, not aspirational.** Order: **pytest tests → the `verify` gate → a
manual log (final release pass only).**

**Automated pytest tests — the default.** Every tool gets at least one small test asserting its
core function returns the right thing for a known input; grow coverage as bugs are found (each
fixed bug gets a regression test). Tests live in `files/tests/` (`test_<tool>.py`; mirror the OS
split if needed), use `files/test-files/` fixtures, and stay fast and deterministic — no network,
no machine-specific state. Add/update a tool's test in the same phase as the tool. `pytest` goes
in `requirements.txt`, pinned.

**The `verify` gate.** A change isn't done until one `verify` command passes. At minimum it: runs
pytest (fail if any test fails); checks all `requirements.txt` deps are pinned; checks
`CHANGELOG.md` was updated for this change. If any check fails, treat it like a failing build —
stop and fix, don't work around. Run it before committing a phase and before any release. (If no
`verify` script exists yet, run the checks by hand and note one should be added.)

**Severity levels** (here and in bug hunts):
- **Critical** — breaks core functionality or crashes for a non-technical user.
- **Minor** — cosmetic, edge case, unlikely to affect typical use.
- **Suggestion** — optional improvement, not a bug.

Fix all criticals before closing a pass and add a regression test for each; flag minors and
suggestions for my review before touching them.

**Manual test log — final release pass only.** Token-heavy, so reserved for the final release
verification of a major plan or building a distributable exe/installer — not individual features
or mid-session checkpoints. Logs live in `files/test-logs/` (gitignored, don't delete between
sessions), named by version and purpose (e.g. `v1.2.0_pre-release.md`). Structure: a summary,
per-section checklists (`[ ]` unchecked, `[x]` passed, `[~]` failed with detail, `[-]` skipped),
and an Issues Found table (# / Severity / File / Description / Status).

---

## Bug Hunt Phase

Most multi-phase plans end with a bug hunt. I routinely have **both Claude Code and Codex** run
it, alternating — one hunts and fixes, the other reviews — until both agree no major bugs remain.
Coordinate through `handoff.md` (log what was checked, found, fixed, and what the other agent
should re-verify; each entry signed and dated). If a fix would reverse an earlier deliberate
choice, check `DECISIONS.md` first; if it genuinely needs to change, add a superseding entry
rather than silently reverting. When hunting:
- Go through **every** script systematically, not just the ones you touched.
- Flag deprecated library usage, missing error handling, hardcoded paths, and anything that
  breaks for a non-technical user on a fresh machine.
- Fix criticals immediately with a regression test; flag minors/suggestions for my review first.
- When reviewing the other agent's fixes, confirm the regression test exists and covers the bug,
  and sign off in `handoff.md`.
- Run `verify` at the end before calling it done.

---

## Session and Context Management

At natural breakpoints where current context is no longer needed, remind me of my options and
let me choose — never automatically. The right moment is after a self-contained phase is complete
and verified — not mid-implementation or mid-debug. First make sure `handoff.md` is up to date.
Then offer: **start a new session** (clean start, no dependency on current context); **clear
context** (wipe the window, stay in the directory — Claude Code `/clear`); or **compact/summarize**
(compress when some history is still useful but the window is long — Claude Code `/compact`).
Word it like: *"Phase X is complete and committed, and handoff.md is updated. Before we move on,
you may want to start a fresh session or clear/compact context. What would you like to do?"*
Don't push one option unless the situation clearly favours it.

---

## Git and Version Habits

- Commit after each completed phase, not just at the end, with clear messages on what and why.
- Work on a branch for anything non-trivial; don't push directly to main. If I haven't specified
  a branch, ask before committing.
- **Clean push/pull across devices:** before pushing, update the `handoff.md` Session Sync Log
  and make sure every file it names is staged and committed. Starting on a possibly-behind
  machine, read that log, reconcile against `git status`/`git log`, and pull.

---

## Dependency and Environment Rules

- **`requirements.txt` lives in `scripts/`** (the setup file looks there). One shared file
  cross-platform; split per-OS only if deps genuinely differ.
- **Pin everything** to an exact version (`requests==2.31.0`, never bare `requests`) — including
  dev tools like `pytest`. Unpinned deps let a later install silently pull a breaking version
  (e.g. `openpyxl` has broken existing code across versions). When adding a package, check the
  latest stable version and pin to it.
- **`.gitignore` hygiene** — before every commit, ensure these are ignored (create `.gitignore`
  first if missing):
  ```
  .venv/   .python_runtime/   __pycache__/   *.pyc   *.pyo
  dist/   build/   *.spec   files/bin/   files/test-logs/   .env
  ```
- **Binary dependencies (ffmpeg, etc.)** are handled by `Setup_and_Run`: contained in
  `files/bin/` by default, system install only as a forced fallback, always with a "No, I'll do
  it manually" option and the exact download URL. The program must never crash on a missing
  binary — check at startup and handle absence with a clear prompt.

---

## Session Kickoff Routine

At the start of every session on an existing project, read in order:
1. `CLAUDE.md` / `CODEX.md` and `AI-WORKSPACE.md` — global instructions.
2. `md-instructions/Briefing.md` — what the project is.
3. `md-instructions/CHANGELOG.md` — how it got here.
4. `md-instructions/DECISIONS.md` — why non-obvious choices were made.
5. `md-instructions/handoff.md` — live state, open issues, sync log. On a possibly-behind
   machine, reconcile the sync log against `git status`/`git log` and pull before working.

Then confirm the current version, what was last worked on, and any open issues; flag anything
missing or stale. Read a dropped instruction markdown next if present. Know what's in your skills
folder (for a new project, do the up-front skill research before coding) — you needn't read every
skill in full, just load the relevant `SKILL.md` when needed. State this confirmation
conversationally (chat AI) or as a brief summary at the start of your first response (CLI agent).

---

## What I Don't Want (unless an instruction prompt says otherwise)

- Don't add dependencies/libraries without a one-line explanation of what and why (you have full
  discretion on the best library — just don't add things silently).
- Don't put anything in the repo root beyond the five folders, the allowed loose files, and the
  auto-generated `.venv/`.
- Don't restructure folders outside the current task — except you may **ask** to reorganize a
  repo that doesn't match my structure.
- Don't leave debug prints or test files in the final output.
- Don't call a task done until its tests pass and `verify` is green. "Looks done" isn't done.
- Don't produce output requiring the user to edit a config file or run a terminal command to
  finish setup — `Setup_and_Run` handles everything.
- Don't split a CLI prompt across multiple code blocks, or leave any agent-actionable instruction
  outside the single prompt block.
- Don't let the four permanent docs bleed together — reasoning goes in DECISIONS, not Briefing/
  CHANGELOG/handoff.
