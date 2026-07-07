<!--
Instruction-drop scaffold for the Audiobook Creation Tool.
Copy this file, rename it (e.g. `0.5.0-drop2-metadata.md`), fill in the slots, drop it in
md-instructions/. The implementing agent reads it fully, implements it phase by phase,
verifies it, then DELETES the copy. This scaffold itself is permanent; the copies are not.

Project constants (do not re-litigate per drop):
- Program code → scripts/Universal/ (scripts/Windows|MacOS only for truly OS-specific code)
- Dev-only/tests → files/tests/ ; fixtures → files/test-files/ (gitignored, env-var pointed)
- Runtime state → files/runtime-data/ ; portable binaries → files/bin/ (both gitignored)
- Gate: `python scripts/verify.py` must print RESULT: PASS
- v0.5.0 line: NO per-phase commits — one commit per completed drop (see DECISIONS.md
  2026-07-06); the maintainer pushes.
-->

# Audiobook Creation Tool — <Drop / Feature Name>

## Context
<Where the project is right now and what was last completed. Point to the relevant
handoff.md entry.>

## Goal
<What should be TRUE when this drop is done. One clear sentence.>

## Scope

**In scope (build this):**
-

**Out of scope (do not touch):**
-

## Skills Needed
<Check .claude/skills/ (audio-processing lives there) and .codex/skills/ first; note any to
pull from public repos before coding. "none" if genuinely not applicable.>
-

## Implementation Notes
- **Language / libraries to use or avoid:**
- **File paths to be aware of:**
- **Platform notes:** <what differs between scripts/Universal and the OS dirs, if anything>
- **Behaviour / edge cases to handle:**
- **Behaviours that must not regress:** Windows pythonw no-console fast path; macOS
  Gatekeeper/App-Translocation guard; Kokoro/venv/ffmpeg self-heal on every launch;
  copy-based outputs to Downloads/<Tool>-N.

## Phases
<Small numbered phases — each verifiable before the next. Update handoff.md after each;
do NOT commit per phase (one commit per drop).>

1.
2.
3. Bug hunt and verify (full pytest suite + `python scripts/verify.py`).

## Definition of Done
This drop is complete when:
- [ ] All phases above are implemented.
- [ ] Each touched tool has a passing pytest test in files/tests/ (each fixed bug has a
      regression test).
- [ ] `python scripts/verify.py` → RESULT: PASS.
- [ ] CHANGELOG.md has a new entry for this change.
- [ ] Briefing.md reflects the new state (if features/architecture changed).
- [ ] handoff.md is updated (work log + session sync log).
- [ ] This instruction file (the copy) has been deleted from the repo.
