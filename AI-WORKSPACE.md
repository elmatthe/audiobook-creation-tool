# Global Developer Preferences

This file defines my workflow, preferences, and structure across all projects. It lives in
the root of every repo. Read it at the start of every session and apply these defaults unless
a project-level `CLAUDE.md` / `CODEX.md` or a dropped instruction markdown overrides them.

**The documents I rely on (each detailed in its own section below):**

- **`AI-WORKSPACE.md`** (this file) — global, cross-project rules. Rarely changes.
- **`md-instructions/Briefing.md`** — *what the project is*: an AI-facing, developer-grade
  README covering the project and all its features. Broad, slow-changing.
- **`md-instructions/CHANGELOG.md`** — *what changed over time*: append-only version history.
- **`md-instructions/DECISIONS.md`** — *why it's built this way*: append-only architecture-
  decision record (ADR log) capturing the reasoning behind non-obvious choices.
- **`md-instructions/handoff.md`** — *what's happening right now*: live working state, open
  bugs, agent-to-agent notes, and the cross-device file-sync log. Most detailed, most volatile.
- **`md-instructions/*.md`** (instruction drops) — temporary one-time plans. Read, implement,
  delete.

---

## My Machines & Workspace Roots

I work across more than one machine. Use the roots and constraints for whichever machine the
session is running on. Paths and permissions differ, so never assume a path from one machine
exists on another — confirm against the matching block. The `claude-skills-main` folder listed
per machine is my local clone of reusable skills; it sits alongside the workspace roots, not
inside a project.

### CSPW-PC — Work Computer

**Vibe Coding Space Roots:**
```
C:\Users\ematthew\Desktop\Files\Coding_Repositories
C:\Users\ematthew\Desktop\Files\Coding_Repositories\MyProjects\CSPW-PC
C:\Users\ematthew\Desktop\Files\claude-skills-main
```

**Portable tool paths (added to PATH for the session only, via
`Start-Portable-Development-CSPW.cmd` — see "Vibe Coding Workspace Files" below):**
```
C:\Users\ematthew\Portable-User-Installs\PortableGit\cmd
C:\Users\ematthew\Portable-User-Installs\PortableGit\mingw64\bin
C:\Users\ematthew\Portable-User-Installs\PortableGit\usr\bin
C:\Users\ematthew\Portable-User-Installs\PortableNodeJS\node-v26.4.0-win-x64
```

**Specs:**
- Device: Lenovo ThinkPad T16 Gen 2 (AMD) — Model 21K8S1HN00
- OS: Windows 11 Pro (64-bit)
- CPU: AMD Ryzen 5 PRO 7545U — 6 Cores / 12 Threads
- RAM: 32 GB (30.7 GB usable)
- GPU: AMD Radeon 740M (integrated, no CUDA)
- Storage: 256 GB SSD (88.7 GB free — limited free space, keep builds lean)
- Monitors: 2x Lenovo ThinkVision P27q-30 — 27" QHD (2560×1440 @ 60Hz)

**Permissions — locked down (important):** User `EMatthew` is a **Standard User, no admin
rights.** Cannot run `.exe`/`.msi` installers that write to `C:\Program Files` or the registry
(needs an IT password I don't have). Can run local PowerShell (`RemoteSigned`). **Default
approach:** portable apps (standalone `.exe`/`.zip`) that run from `C:\Users\ematthew\`,
browser extensions, and fully self-contained in-repo setups — nothing system-wide. This is the
machine the "contain everything in the repo and venv" rule matters most for.

**Environment Notes:**
- No administrator rights are available.
- Do not rely on permanent system PATH changes.
- Launch Claude Code, Codex, Git, Node.js, npm, and npx from:
  `C:\Users\ematthew\Portable-User-Installs\Start-Portable-Development.cmd`, or from
  `Start-Portable-Development-CSPW.cmd` at the Vibe Coding Space root (see below) to also
  pick a directory/repo interactively.
- Use `npm.cmd` and `npx.cmd` in PowerShell rather than `npm.ps1` or `npx.ps1`.
- GitHub HTTPS authentication is handled by Git Credential Manager.
- Git Bash and bundled OpenSSH work outside restricted agent sandboxes.
- Codex may block Git Bash or SSH subprocesses inside its Windows sandbox even though the
  portable installation works normally.

### HOME-PC — Personal Computer

**Vibe Coding Space Roots:**
```
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces\MyProjects\Home-PC
C:\Users\ematthew\Desktop\Apps\Coding\claude-skills-main
```

**Specs:**
- Device: Custom Build — MSI Motherboard (Model MS-7E66)
- OS: Windows 11 Pro (64-bit)
- CPU: AMD Ryzen 7 9800X3D — 8 Cores / 16 Threads
- RAM: 32 GB (31.1 GB usable)
- GPU: NVIDIA GeForce RTX 5070 (CUDA) & AMD Radeon (integrated)
- Storage: 2 TB SSD (1862 GB total, 675.9 GB free — ample space)
- Monitors: 2x Generic PnP Monitors (Active)

**Permissions — full access:** User `ematthew` is an **Administrator.** Can run any installer,
modify the registry, write to `C:\Program Files` (right-click → "Run as Administrator"). Can
run local PowerShell (`RemoteSigned`). CUDA GPU available, so GPU-accelerated work (ML, CUDA,
heavier local models) is viable here but not on CSPW-PC.

### HOME-MacOS — Personal MacBook Pro (details to be added)

**Vibe Coding Space Roots:** to be filled in
**Specs:** to be filled in
**Permissions:** to be filled in

Until filled in, treat any macOS session as undefined for paths — ask me for the workspace
root and machine details before assuming anything.

---

## Vibe Coding Workspace Files

Above and alongside the individual project repos sits a shared **Vibe Coding Workspace** — the
scaffolding layer that creates and standardizes every new project. It lives one level up from
(and around) the workspace roots listed above (e.g. on CSPW-PC: the parent of
`Coding_Repositories`, containing `Coding_Repositories\` itself plus a sibling `templates\`
folder, `.claude\`, and `.codex\`). These 13 files are the workspace's own tooling — distinct
from anything inside an individual project repo — and are not modified per-project:

```
[coding_root]/
  AI-WORKSPACE.md                          <- this file; global preferences (copied into
                                               every new project's root by the scaffolder)
  .claude/  .codex/                        <- master agent configs, cloned into new projects
  templates/
    verify-template.py                     <- source for scripts/verify.py in new projects
    setup_and_run-templates/
      Setup_and_Run-template.bat           <- Windows setup+launcher source
      Setup_and_Run-template.command       <- macOS setup+launcher source
    md-templates/
      briefing-template.md                 <- source for md-instructions/Briefing.md
      changelog-template.md                <- source for md-instructions/CHANGELOG.md
      decisions-template.md                <- source for md-instructions/DECISIONS.md
      handoff-template.md                  <- source for md-instructions/handoff.md
      instructions-template.md             <- source for md-instructions/Instructions_Template.md
  Coding_Repositories/ (workspace_root)
    Create_New_Repo-CSPW.bat               <- scaffolder: work-PC paths, run from workspace root
    Create_New_Repo-HOME.bat               <- scaffolder: home-PC paths, run from workspace root
    Map-Repo-Structure.bat                 <- drop into ANY repo root; maps it to REPO-STRUCTURE.md
    Start-Portable-Development-CSPW.cmd    <- CSPW-PC only: puts portable Git/Node/Claude Code
                                               on PATH for the session, then lets me pick a
                                               directory and repo to open a shell in
    MyProjects/
      CSPW-PC/  <individual project repos>
      Home-PC/  <individual project repos>
```

**What each file is for:**

- **`AI-WORKSPACE.md`** — the file you're reading. Copied verbatim into every new project's
  root by the `Create_New_Repo` scaffolders.
- **`Create_New_Repo-CSPW.bat`** / **`Create_New_Repo-HOME.bat`** — interactive scaffolders,
  one per machine (fixed paths differ). Each: validates the template sources exist; lets me
  pick a workspace and name a new project; creates the standard folder layout (`scripts/`,
  `files/tests|test-files|test-logs|bin`, `md-instructions/`); clones `.claude/` and `.codex/`
  agent configs; copies and renames the two `Setup_and_Run-template.*` launchers (token-
  substituting `[PROJECT_NAME]`); copies and de-templates all five core `md-templates/*.md`
  files into `md-instructions/` (`Briefing.md`, `CHANGELOG.md`, `DECISIONS.md`, `handoff.md`,
  `Instructions_Template.md`) in a single PowerShell pass; copies `verify-template.py` into
  `scripts/verify.py`; and writes `README.md`, `.gitignore`, `.env`, and the `CLAUDE.md`/
  `CODEX.md` pointer files.
- **`Setup_and_Run-template.bat`** / **`Setup_and_Run-template.command`** — the Windows and
  macOS setup-and-launcher sources (see "Setup and Launch Files" below for the full behavior
  they scaffold into every project).
- **`verify-template.py`** — the mechanical `verify` gate source (pytest + pinned-deps +
  de-templated-docs checks; see "The `verify` gate" below).
- **`briefing-template.md`**, **`changelog-template.md`**, **`decisions-template.md`**,
  **`handoff-template.md`**, **`instructions-template.md`** — the sources for the four
  permanent `md-instructions/` docs plus the instruction-drop scaffold. Each file's own header
  comment documents exactly how it should be used and kept distinct from the others (see "The
  `/md-instructions` Folder" below for the same detail).
- **`Map-Repo-Structure.bat`** — a standalone utility, not part of the scaffolder flow. Drop a
  copy into any repo root (new or existing, workspace-level or project-level) and double-click
  it; it scans the folder tree (skipping noise like `.git`, `.venv`, `__pycache__`,
  `node_modules`, `files/bin`) and writes a `REPO-STRUCTURE.md` snapshot I can paste to an AI
  so it knows the current layout before I ask for changes.
- **`Start-Portable-Development-CSPW.cmd`** — CSPW-PC only (no admin rights, so tools are
  portable). Puts portable Git, Node.js, and Claude Code on `PATH` for the session, lets me
  pick a directory then a repository inside it by number, and drops me into an interactive
  PowerShell there with tool versions confirmed. There's no HOME-PC equivalent since that
  machine has full admin rights and standard installs.

Treat this workspace layer as infrastructure: changes here affect every future scaffolded
project, so edit deliberately and keep the templates' own header comments in sync with this
file when either changes.

---

## How I Work With You

Two-surface workflow:

- **AI chat tool** (Claude.ai, ChatGPT, Gemini) — my planning/thinking layer: designing
  features, interpreting output, writing implementation markdowns, architectural decisions.
- **AI coding agent / CLI** (Claude Code, Codex, Cursor) — my execution layer: it receives
  those plans as markdown and implements them.

Every repo has a `.claude/` folder (`settings.json` + `CLAUDE.md`) and a `.codex/` folder
(`settings.json` + `CODEX.md`) for generic agent setup. I often run **both Claude Code and
Codex** on one project — co-implementing or reviewing each other's work — coordinating through
`handoff.md` (see The `/md-instructions` Folder).

### CLI prompts must be ONE copyable code block

The single most important rule for how the chat layer talks to the CLI layer:

When I ask you (the chat AI) for a prompt/instruction/plan to feed a CLI, **put the entire
prompt in one fenced code block** so I can copy it all in a single click and paste it straight
in. Everything the agent must act on goes *inside* that one block — start to finish, never
split across multiple blocks, never with a stray actionable line left in prose. Anything meant
only for *me* — manual test steps, permissions I must grant, "do this on HOME-PC for CUDA,"
push/pull reminders — goes *outside* the block in normal text.

Rule of thumb: if the agent needs to read it, it's inside the block; if only I need it, it's
outside.

### Instruction markdowns are temporary

Read any plan I drop in fully before doing anything — internalize the whole scope before
writing code, and if anything is ambiguous, ask before starting rather than assuming. Once a
plan is implemented and verified, delete it. The permanent record lives in Briefing, CHANGELOG,
DECISIONS, and handoff — not in instruction drops.

---

## Project Structure I Typically Use

Default to this layout when starting or reorganizing a project (follow project-level
instructions if they differ). **If a repo doesn't match this structure, ask whether you should
reorganize it before proceeding.** The guiding principle is a **clean, minimal root**: it
should be instantly obvious what the project is and how to run it, and nothing else.

### Root contents — nothing else belongs at the top level

```
Folders (these 5 only):
  .claude/          <- Claude agent config (settings.json, CLAUDE.md, skills/)
  .codex/           <- Codex agent config  (settings.json, CODEX.md, skills/)
  scripts/          <- everything the PROGRAM needs to run (ships in the release)
  files/            <- everything the DEVELOPER needs (does NOT ship)
  md-instructions/  <- markdown for AIs (Briefing, CHANGELOG, DECISIONS, handoff, instruction drops)

Loose files (these only):
  README.md
  AI-WORKSPACE.md
  .gitignore
  .env
  Setup_and_Run-<project_name>.bat       <- Windows launcher/setup
  Setup_and_Run-<project_name>.command   <- macOS launcher/setup

Auto-generated (the one exception):
  .venv/   <- created in root by Setup_and_Run; gitignored, rebuilt on demand, never committed
```

`.venv/` is the only other thing permitted in the root — it must live there because the setup
script creates it there and activation/`requirements.txt` paths assume it. A non-technical user
who unzips a release should see only the README and the two launchers as obvious entry points.

### The core split: `scripts/` (ships) vs `files/` (doesn't)

This is the key organizing decision — be strict about it:

- **`scripts/`** — everything the program **needs to run** from a fresh release `.zip`: every
  Python/JS/JSON/etc. file it imports or uses at runtime, plus `requirements.txt`.
- **`files/`** — everything **development-only**: the `pytest` suite, test inputs, QA logs,
  binaries, assets, fixtures, scratch — anything a user never needs to run the program.

The test: *"Does the running program break without this file in a fresh release zip?"* —
Yes → `scripts/`, No → `files/`.

### Single-platform layout

```
/ProjectName/                       <- clean, minimal root
  README.md  AI-WORKSPACE.md  .gitignore  .env
  Setup_and_Run-ProjectName.bat
  Setup_and_Run-ProjectName.command
  .venv/                            <- gitignored; created by Setup_and_Run
  /.claude/   settings.json  CLAUDE.md (→ AI-WORKSPACE.md)  /skills/
  /.codex/    settings.json  CODEX.md  (→ AI-WORKSPACE.md)  /skills/
  /scripts/                         <- everything the PROGRAM needs to run
    launcher.py                     <- main entry point for multi-tool projects
    requirements.txt
    ... (program scripts; subfolders as needed)
  /md-instructions/                 <- markdown for AI use
    Briefing.md  CHANGELOG.md  DECISIONS.md  handoff.md  Instructions_Template.md
  /files/                           <- everything DEV-only (does not ship)
    /tests/  /test-files/  /test-logs/  /bin/
    ... (assets, fixtures, scratch, __pycache__/, etc.)
```

### Cross-platform layout

The **root stays identical** — same five folders, same loose files. The OS split happens
**inside `scripts/`**, so the root never forks or clutters:

```
/ProjectName/
  (same root files as above)
  /scripts/
    /Universal/   <- shared code used by both platforms
    /Windows/     <- Windows-only scripts
    /MacOS/       <- macOS-only scripts
    requirements.txt   <- shared; split per-OS only if deps genuinely differ
  /md-instructions/     <- ONE set for the whole project (not per-platform)
    Briefing.md  CHANGELOG.md  DECISIONS.md  handoff.md  Instructions_Template.md
  /files/
    /tests/  <- may mirror Universal/Windows/MacOS if tests differ
    /test-files/  /test-logs/  /bin/
```

- `md-instructions/` is a **single set** for the whole project — Briefing, CHANGELOG, DECISIONS,
  and handoff are *not* split per OS; platform-specific detail is called out inline (e.g.
  "Windows: … / macOS: …"). Avoids drifting copies.
- Put shared logic in `scripts/Universal/`; only genuinely OS-specific pieces go in
  `Windows/` and `MacOS/`. Instruction/plan drops are never split by OS — one file covers both.

---

## The `/md-instructions` Folder

This folder is **for AIs** — where I instruct agents, agents record state, and agents talk to
each other. End users never see it. It holds four **permanent** documents (kept distinct — do
not let their contents bleed together) plus temporary instruction drops.

### `Briefing.md` — what the project *is*

A detailed, AI-facing README — more thorough than the user-facing `README.md` — so a brand-new
session can understand the whole project without me re-explaining. Covers: what the project
does and who it's for; tech stack and key libraries; architecture and major design decisions
(entry point, how pieces fit, data flow); every major feature at a descriptive level; current
version and high-level state. It describes the project broadly and completely, but does **not**
track individual bugs or in-flight work — that's handoff — and does **not** justify *why* a
non-obvious choice was made — that's DECISIONS.

### `CHANGELOG.md` — what *changed over time*

An append-only history by version: every release, feature, fix, and breaking change under
clear version markers. Update it whenever a version is cut or a meaningful change lands. Keep
it clean — it's the release history, not a scratchpad and not a file-diff log.

### `DECISIONS.md` — *why* it's built this way

An append-only architecture-decision record (ADR log). Where Briefing covers *what* the project
is, CHANGELOG covers *what changed*, and handoff covers *what's happening now*, DECISIONS
captures the **reasoning** behind non-obvious choices so a future session (or a bug hunt)
doesn't "fix" something that was deliberate. Add an entry when: a library/tool was chosen over
an obvious alternative; a structural or data-flow decision isn't self-evident from the code; a
deliberate trade-off was made (e.g. "slower but simpler," "no async because the user base is
small"); a constraint shaped the design (no admin rights on CSPW-PC, 256 GB SSD, no CUDA,
etc.); or anything an agent might otherwise undo without context. Skip it for routine bug fixes
(handoff/CHANGELOG territory) and obvious choices with no real alternative.

Rules: **append-only**, newest entry on top, never rewrite history. If a decision is later
reversed, don't delete the old entry — add a new one that supersedes it and note "Supersedes
#N" so the reasoning trail stays intact. Sign and date every entry, like handoff.md. Suggested
structure (mirrors `decisions-template.md`):

```markdown
# <Project> — Decisions (ADR Log)

## 002 — Static ffmpeg over system install — 2026-06-20 — Claude Code

**Status:** Accepted
**Context:** Users on CSPW-PC have no admin rights and can't install ffmpeg system-wide.
**Decision:** Bundle a static ffmpeg binary in files/bin/, downloaded by Setup_and_Run.
**Alternatives considered:** System install (needs admin); python-only audio libs (too limited).
**Consequences:** Larger release zip; no PC-level install or PATH changes required.

## 001 — [First decision title] — 2026-06-15 — [Agent/Person]
...
```

### `handoff.md` — what's happening *right now*

The most detailed and most frequently updated of the four, but **narrower** than Briefing (it
doesn't re-describe features) and distinct from DECISIONS (it logs *state*, not *reasoning*).
It captures the live, in-flight state so any agent or machine can pick up exactly where the
last left off. Two jobs:

**1. Agent-to-agent working state.** When an agent finishes or picks up work, it appends a
short, signed, dated entry — what was done, what's in progress, what's blocked, what's next —
so two agents trade work cleanly without me re-explaining.

**2. Cross-device file-sync log.** Because I move between machines via GitHub, handoff also logs
which files changed each session, so on a machine that's behind I can tell the CLI to read it
and pull exactly what's listed — an explicit push/pull instead of guessing what's stale. At the
end of a session (and before I push), append a dated, per-machine entry of files
added/changed/deleted with a one-line note each, and make sure those changes are actually
staged and committed so the log and the commit agree. When starting on a possibly-behind
machine, read this log first, reconcile against `git status`/`git log`, then pull. This
tracks *session file movement* — not versions (CHANGELOG), not features (Briefing), and not
reasoning (DECISIONS).

Suggested handoff structure:

```markdown
# <Project> — Handoff

## Current Focus
One or two lines on what's actively being worked on right now.

## Open Issues / Bugs
| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | Critical | scripts/launcher.py | Crash on first run, no config | Open | Codex |

## Work Log (newest first)
- 2026-06-25 — Implemented Phase 3 §4 of plan-x.md; tests pass. — Claude Code
- 2026-06-25 — Reviewed §4, found edge case on empty input (issue #1). — Codex

## Session Sync Log (newest first)
### 2026-06-25 — HOME-PC — pushed
- Added:   scripts/Universal/parser.py
- Changed: scripts/launcher.py (wired parser into menu)
- Changed: files/tests/test_parser.py (new tests)
- Note:    Parser feature complete; pull these before continuing on CSPW-PC.
```

### Temporary instruction drops

All other markdown here is a one-time plan for a specific feature or phase — read, implement,
verify, delete. `Instructions_Template.md` is the scaffold I copy for a new one.

---

## The `.claude/skills` and `.codex/skills` Folders

Skills are **reusable capability documents** — a durable pattern an agent loads on demand (how
to generate an Excel workbook my way, write VBA macros to my conventions, scaffold a tkinter
launcher, run a build/package step). Capturing these instead of re-explaining them every
session improves consistency, cuts prompting, and saves tokens. Each skill is its own folder
with a `SKILL.md`:

```
/.claude/skills/   (or /.codex/skills/)
  excel-generation/SKILL.md
  vba-macros/SKILL.md
```

Place a new skill under the folder for the agent you are (Claude → `.claude/skills/`, Codex →
`.codex/skills/`); mirror into both only if it's genuinely agent-agnostic.

**Skills vs. instruction markdowns:** a skill is a *durable capability* that recurs across
phases and projects and is never deleted ("how to do a kind of thing well, every time"); an
instruction markdown is a *one-time plan* for this project, deleted once done ("what to build
right now"). Rule of thumb: if I'd have to explain it again next session or project, it's a
skill; if it's only for the task in front of us, it's an instruction.

### Assemble skills BEFORE coding (research step)

At the start of a project, and as part of building any markdown plan, proactively gather the
skills the work will need rather than waiting to be told:

1. **Examine the repo** and read `md-instructions/` — especially the active instruction prompt
   — to understand what the work requires.
2. **Research skills**, checking `https://github.com/alirezarezvani/claude-skills` first, plus
   any other public GitHub repos with skills useful for the task.
3. **Clone/copy the relevant skill files** into your own `.claude/skills/` (or `.codex/skills/`),
   taking only what's useful and noting where each came from.
4. **Keep curating as you go** — reuse skills throughout the build, and create a new skill
   whenever a recurring capability is missing.

List the skills the work will need (and where they'll come from) in the markdown plan, so I see
them up front.

---

## The `/files` Folder

`files/` is the catch-all for everything the **developer** needs but the program **does not
ship** — the counterpart to `scripts/`. Nothing the running program depends on belongs here
(that goes in `scripts/`). Typical subfolders:

- **`files/tests/`** — the `pytest` suite (run by `verify`); may mirror
  `Universal/Windows/MacOS` if tests differ by platform.
- **`files/test-files/`** — **test inputs only**: sample/input files I drop in for the agent to
  test features against (a sample PDF for a converter, a spreadsheet for a parser, an audio
  clip for an ffmpeg tool). When verifying, look here first; a `pytest` test typically feeds a
  fixture from here and asserts the result. Not shipped; gitignore anything large or sensitive.
- **`files/test-logs/`** — gitignored manual QA logs for the final release pass only.
- **`files/bin/`** — self-contained binaries the setup script downloads (e.g. ffmpeg);
  gitignored unless you intend to commit the binary.
- Assets, icons, fixtures, config templates, build scratch, `__pycache__/`, etc.

Add `files/__pycache__/` and any auto-generated subfolders to `.gitignore` as appropriate.

---

## Setup and Launch Files

Every repo gets two root launchers, created from my templates and named for the project:
`Setup_and_Run-<project_name>.bat` (Windows) and `.command` (macOS). Both behave identically
and serve two purposes: **first-time setup** (prepare the environment, contained in the repo
where possible) and **daily launcher** (double-click to run; can be wired to a shortcut).

### The experience I want for a non-technical user

Assume the user has **never installed Python or anything** and may have no admin rights. The
whole flow works by double-clicking one file:

- User downloads the release `.zip`, unzips it anywhere, double-clicks the `Setup_and_Run`
  file → a terminal opens and **scans the machine** for Python and any other needed tools.
- **If Python is missing:** explain in plain language and ask a simple **Y/N** to install it
  **for the current user only** (user scope, no admin) — never system-wide by default.
- Then **create a fresh `.venv`** in the repo root and install all dependencies into it — the
  minimal set needed to run.
- **Self-healing:** if the user deletes `.venv` (to move/shrink/reset the repo), re-running
  rebuilds it from scratch; if they removed Python (or another required base runtime like
  Node.js), the launcher detects it and offers to reinstall. Re-running always returns them to
  a working state.
- After setup, the same file is the **launcher** on every subsequent run.

Goal: **minimum installed on the user's machine**, everything else contained in the repo/venv,
one double-click from "just downloaded" to "running."

### Contain first; install onto the PC only when forced

Keep as much as possible *inside the project folder* — pip deps into `.venv`, self-contained
tools (a static `ffmpeg`) into `files/bin/` and added to PATH for that session only. The one
unavoidable exception is **Python itself** (or another required base runtime like Node.js): a
venv can't be created without an interpreter present, so if it's completely missing it must be
installed. That's the *only* point a real system install — and the scope choice below — comes
up. If Python already exists, the user is never prompted about scope. For anything that *can*
live in the repo, prefer the contained copy; an existing system binary may simply be used.

### Prompts and install scope

- **Y/N for big installs only.** Pause and ask before installing Python/a base runtime, or a
  tool being set up because the contained route failed. A contained in-repo tool gets a single
  plain-language Y/N framed as "this stays in the project folder, nothing is installed on your
  PC." Never prompt for individual pip packages — those install silently into the venv. Add a
  short line near the top of the script explaining setup stays in-folder and only asks before a
  real PC install.
- **Scope — only when a system install is forced.** When (and only when) something must go onto
  the PC, ask once: **Just for me (user scope, no admin — the safe default)** or **For all
  users (machine scope, needs admin)**. On Windows, use `winget` with `--scope user`/`--scope
  machine`; on macOS, user scope via Homebrew (no admin), system-wide Python via the official
  python.org installer. The install must land somewhere the user can write to.

### First-run security block (unavoidable)

Downloaded-from-internet launchers are unsigned, so Windows SmartScreen/Defender/WatchGuard (or
macOS Gatekeeper) will block the **first** run. No code can suppress this — only the user
clicking through. Include a short friendly note up front: Windows → "More info" → "Run anyway";
macOS → System Settings → Privacy & Security → "Open Anyway." Normal, once only.

### Platform mechanics

macOS launcher must be a **`.command`** (not `.sh`) so it opens on double-click from Finder,
and needs execute permissions (`chmod +x`). Windows `.bat` keeps the console open during setup
so the user sees a live log, then prompts "press Enter to close" — don't leave it open with no
way to dismiss. Suppress unnecessary console popups once the GUI is running.

---

## Python and Script Preferences

- Python is the default, but use whatever tool fits best — if another language/runtime is
  clearly better for a task, use it and briefly say why. Don't force Python.
- GUIs use `tkinter` unless a project says otherwise.
- Multi-tool projects have a `scripts/launcher.py` entry point: a clean GUI presenting each
  tool as a button/menu item. Suppress console popups when launched from setup — users see the
  GUI, not terminal output.
- Keep scripts modular (one tool per file, called from the launcher) and organized in
  `scripts/` with subfolders as needed (and the `Universal/Windows/MacOS` split when
  cross-platform).

---

## Research Before Building

Do less work by borrowing well-tested code. Order: **skills → GitHub → write it yourself.**

1. **Skills first.** Check your skills folder; if a captured skill fits, use it. Also do the
   up-front skill research from the Skills section (pull useful skills from public repos into
   your folder before coding) and list expected skills in the plan.
2. **Then GitHub** for repos handling the specific task (e.g. "ffmpeg python wrapper", "tkinter
   file converter gui"). Prefer recent commits, reasonable stars, permissive license (MIT,
   Apache 2.0). Read the files to confirm they work and are clean — no bloat or unmaintained
   code. Prefer a self-contained module over a whole framework.
3. **When you borrow:** add only the needed files to the right folder (program code →
   `scripts/`, dev-only → `files/`), note the source in the commit message and `CHANGELOG.md`,
   and comment any changes you make to fit. If the choice itself was non-obvious (this library
   over an alternative), also log it in `DECISIONS.md`.

If nothing useful turns up after a reasonable search, write it from scratch and say so. Don't
over-search something simple enough to just implement.

---

## Implementation Approach

When given a plan (dropped markdown or direct instruction):

1. **Read everything first**, including current `md-instructions/` state (Briefing, CHANGELOG,
   DECISIONS, handoff). Understand the full scope before writing a line.
2. **Identify and gather skills** the task needs; pull in missing useful ones before building
   (see Skills and Research). List them in the plan.
3. **Research before building** — evaluate existing libraries/repos before writing from scratch.
4. **Phase your work** into small numbered phases. After each, verify mechanically (add/update
   `pytest` and run `verify`) before moving on — don't chain phases without checkpointing.
   Update `handoff.md` at each checkpoint.
5. **Prefer working code over clever code** — these ship to non-technical users; reliability
   beats elegance.
6. **Don't refactor unrelated code** unless a bug hunt or the plan calls for it. Stay in scope.
7. **If unsure, stop and ask** — don't guess on ambiguous requirements, especially around file
   structure, user-facing behaviour, or data handling.
8. **Log non-obvious choices** — if a decision in this phase isn't self-evident from the code
   (a library pick, a trade-off, a constraint-driven design), add an entry to `DECISIONS.md`
   before moving on.

---

## Testing and Verification

Correctness is **mechanical, not aspirational** — automated checks that run every time beat
hand-written logs that only catch what someone remembers and burn tokens. Order of preference:
**`pytest` tests → the `verify` gate → a manual log (final release pass only).**

### Automated `pytest` tests — the default

Every tool gets at least one small test asserting its core function returns the right thing for
a known input. Start with one per tool; grow coverage as bugs are found (each fixed bug gets a
regression test). Tests live in `files/tests/` (e.g. `test_<tool>.py`; mirror the OS split if
needed), use `files/test-files/` fixtures as known inputs, and stay fast and deterministic — no
network, no machine-specific state. Add/update a tool's test in the same phase as the tool
("it works" = "there's a test proving it"). `pytest` goes in `requirements.txt`, pinned.

### The `verify` gate

A change isn't done until one `verify` command passes. At minimum it: runs `pytest` (fail if
any test fails); checks all deps in `requirements.txt` are pinned; checks `CHANGELOG.md` was
updated for this change (top version ahead of last commit, or matching `Briefing.md`). If any
check fails, the work isn't done — treat it like a failing build: stop and fix, don't work
around it. Run it before committing a phase and before any release. (If no `verify` script
exists yet, run the checks by hand and note that one should be added.)

### Severity levels (for any issue, here or in a bug hunt)

- **Critical** — breaks core functionality or crashes for a non-technical user.
- **Minor** — cosmetic, edge case, unlikely to affect typical use.
- **Suggestion** — optional improvement, not a bug.

Fix all criticals before closing a pass and add a regression test for each; flag minors and
suggestions for my review before touching them.

### Manual test log — final release pass only

Token-heavy, so reserved for the **final release verification of a major plan** or building a
distributable exe/installer — not individual features, routine fixes, or mid-session
checkpoints. For everything smaller, `pytest` + `verify` is the check. Logs live in
`files/test-logs/` (gitignored, not shipped, don't delete between sessions), named by version
and purpose (e.g. `v1.2.0_pre-release.md`). Structure:

```markdown
# [Project Name] — [Test Type] — v[X.X.X]
Date: YYYY-MM-DD   Tester: [agent or person]

## Summary
What this release pass checks and why.

## [Section — e.g. Launcher, GUI, Script Name]
- [ ] Check -> Expected outcome
- [x] Check -> Expected outcome  PASSED
- [~] Check -> FAILED: what went wrong

## Issues Found
| # | Severity | File | Description | Status |
|---|----------|------|-------------|--------|
| 1 | Critical | launcher.py | Crash on first run when no config exists | Fixed |
| 2 | Minor    | gui/main.py | Window title shows placeholder text | Open |
```

Status markers: `[ ]` unchecked, `[x]` passed, `[~]` failed (describe inline), `[-]` skipped
(explain).

---

## Bug Hunt Phase

Most multi-phase plans end with a bug hunt. I routinely have **both Claude Code and Codex** run
it, alternating — one hunts and fixes, the other reviews and double-checks, until both agree no
major bugs remain. Coordinate through `handoff.md`: log what was checked, found, and fixed, and
what the other agent should re-verify (each entry signed and dated). If a fix reverses or
overrides an earlier deliberate choice, check `DECISIONS.md` first so a documented trade-off
isn't undone by accident — if it genuinely needs to change, add a new entry that supersedes the
old one rather than silently reverting it. When hunting:

- Go through **every** script systematically, not just the ones you touched.
- Flag deprecated library usage, missing error handling, hardcoded paths, and anything that
  breaks for a non-technical user on a fresh machine.
- Fix criticals immediately and add a regression test for each; flag minors and suggestions for
  my review first (see Severity Levels).
- When reviewing the *other* agent's fixes, confirm the regression test exists and actually
  covers the bug, and sign off in `handoff.md`.
- Run `verify` at the end before calling it done.

---

## Session and Context Management

At natural breakpoints where current context is no longer needed, remind me of my options and
let me choose — never do this automatically. The right moment is after a self-contained phase
is complete and verified (committed, tested, next phase independent of current context) — not
mid-implementation or mid-debug. First make sure `handoff.md` is up to date so nothing in-flight
is lost. Then offer:

- **Start a new session** — best for a clean start with no dependency on current context.
- **Clear context** — wipe the window but stay in the same directory (Claude Code: `/clear`).
- **Compact / summarize** — compress when some history is still useful but the window is long
  (Claude Code: `/compact`).

Word it like: *"Phase X is complete and committed, and handoff.md is updated. Before we move
on, you may want to start a fresh session or clear/compact context to stay efficient. What
would you like to do?"* Don't push one option over another unless the situation clearly favours
one. Always let me decide.

---

## Git and Version Habits

- Commit after each completed phase, not just at the end, with clear messages on what changed
  and why.
- Work on a branch for anything non-trivial; don't push directly to main. If I haven't
  specified a branch, ask before committing.
- **Clean push/pull across devices:** before pushing, update the `handoff.md` Session Sync Log
  and make sure every file it names is staged and committed (log and commit must agree).
  Starting on a possibly-behind machine, read that log, reconcile against `git status`/`git
  log`, and pull so nothing changed elsewhere is left out. (Full spec in The `/md-instructions`
  Folder.)

---

## Dependency and Environment Rules

- **`requirements.txt` lives in `scripts/`** (the setup file looks there). One shared file on
  cross-platform projects; split per-OS only if deps genuinely differ.
- **Pin everything** to an exact version (`requests==2.31.0`, never bare `requests`) —
  including dev tools like `pytest`. Unpinned deps let a later install silently pull a breaking
  version (e.g. `openpyxl` has broken existing code across versions). When adding a package,
  check the latest stable version and pin to it.
- **`.gitignore` hygiene** — before every commit, ensure these are ignored if present (create
  `.gitignore` first if missing):

  ```
  .venv/   .python_runtime/   __pycache__/   *.pyc   *.pyo
  dist/   build/   *.spec   files/bin/   files/test-logs/   .env
  ```

- **Binary dependencies (ffmpeg, etc.)** are handled by `Setup_and_Run` (see that section):
  contained in `files/bin/` by default, system install only as a forced fallback, always with a
  "No, I'll do it manually" option and the exact download URL. The program must never crash on
  a missing binary — check at startup and handle absence with a clear prompt. Gitignore
  `files/bin/` unless committing the binary.

---

## Session Kickoff Routine

At the start of every session on an existing project, before anything else, read in order:

1. `CLAUDE.md` / `CODEX.md` and `AI-WORKSPACE.md` — global instructions.
2. `md-instructions/Briefing.md` — what the project is.
3. `md-instructions/CHANGELOG.md` — how it got here.
4. `md-instructions/DECISIONS.md` — why non-obvious choices were made, so nothing gets
   accidentally "fixed" that was deliberate.
5. `md-instructions/handoff.md` — live state, open issues, sync log. On a possibly-behind
   machine, reconcile the sync log against `git status`/`git log` and pull before working.

Then confirm the current version, what was last worked on, and any open issues; flag anything
missing or stale before proceeding. Read a dropped instruction markdown next if present. Note
what's in your skills folder (and for a new project, do the up-front skill research before
coding) — you needn't read every skill in full, just know what exists and load the relevant
`SKILL.md` when needed.

State this confirmation conversationally (chat AI) or as a brief summary at the start of your
first response (CLI agent). And remember: whenever I ask the chat layer for a CLI prompt, **the
whole prompt goes in one copyable code block**, with notes meant only for me kept outside it.

---

## What I Don't Want (unless an instruction prompt says otherwise)

- Don't add dependencies/libraries without a one-line explanation of what and why. You have
  full discretion on the best library — just don't add things silently.
- Don't put anything in the repo root beyond the five folders, the allowed loose files, and the
  auto-generated `.venv/`. Keep the root clean.
- Don't restructure folders outside the current task — *except* you may **ask** to reorganize a
  repo that doesn't match my structure.
- Don't leave debug prints or test files in the final output.
- Don't call a task done until its tests pass and `verify` is green. "Looks done" isn't done.
- Don't produce output requiring the user to edit a config file or run a terminal command to
  finish setup — `Setup_and_Run` handles everything.
- Don't split a CLI prompt across multiple code blocks, or leave any agent-actionable
  instruction outside the single prompt block.
- Don't record reasoning/trade-offs in Briefing, CHANGELOG, or handoff — that belongs in
  DECISIONS.md; keep the four permanent docs from bleeding into each other.
