<!--
HOW TO USE THIS FILE (read me first, AI)
========================================
An instruction drop answers ONE question: "What should I build right now?"

This is a TEMPORARY, one-time plan for a specific feature or phase in THIS project. The user
(or the chat-layer AI) fills it in and drops a copy into md-instructions/ (or the repo root).
A CLI agent reads it fully, implements it, verifies it, then DELETES it. It is not permanent
documentation — the lasting record lives in Briefing, CHANGELOG, and handoff.

FOR THE AGENT IMPLEMENTING THIS:
- Read the WHOLE file before writing any code. If anything is ambiguous, ask before starting —
  do not assume and proceed.
- Do the up-front skills research first (see AI-WORKSPACE.md "Skills" / "Research Before
  Building"): check your skills folder, pull useful skills from public repos, and list them
  under "Skills Needed" below before coding.
- Work phase by phase. After each phase, add/update pytest tests and run `verify` before moving
  on. Update handoff.md at each checkpoint.
- Stay in scope — don't refactor unrelated code unless this file says to.

NOTE: This file is for both single- and cross-platform projects. A single instruction file
covers the work for BOTH platforms — it is never split per-OS.

Replace every [bracketed] placeholder. Delete this comment block in the working copy.
-->

# [Project Name] — [Feature or Phase Name]

## Context
[Where the project is right now and what was last completed. One short paragraph. If this
follows on from handoff.md, point to the relevant entry.]

## Goal
[What should be TRUE when this drop is done. One clear sentence.]

## Scope

**In scope (build this):**
-

**Out of scope (do not touch):**
-

## Skills Needed
[Reusable capabilities this work will likely need. Check .claude/skills/ or .codex/skills/ for
existing ones; note which to pull from public repos (e.g. github.com/alirezarezvani/claude-skills)
before coding. List "none" if genuinely not applicable.]
-

## Implementation Notes
[Constraints, preferences, and details the agent needs before starting.]
- **Language / libraries to use or avoid:**
- **File paths to be aware of:** [program code → scripts/ ; dev-only/tests → files/]
- **Platform notes:** [Single-platform, or what differs between scripts/Windows, scripts/MacOS,
  scripts/Universal]
- **Behaviour / edge cases to handle:**

## Phases
[Break the work into small, numbered phases — each small enough to verify before the next.]

1.
2.
3.
4. Bug hunt and verify (run the full test suite + `verify`; have both agents review if used).

## Definition of Done
This drop is complete when:
- [ ] All phases above are implemented.
- [ ] Each tool has a passing pytest test in files/tests/ (each fixed bug has a regression test).
- [ ] `verify` passes (tests green, dependencies pinned, CHANGELOG updated).
- [ ] CHANGELOG.md has a new entry for this change.
- [ ] Briefing.md reflects the new state (if features/architecture changed).
- [ ] handoff.md is updated (work log + session sync log).
- [ ] This instruction file has been deleted from the repo.
