<!--
HOW TO USE THIS FILE (read me first, AI)
========================================
handoff.md answers ONE question: "What's happening right now?"

It is the live, in-flight working state of the repo — the most detailed and most frequently
updated of the three permanent docs, but NARROWER than Briefing (it does not re-describe every
feature). It exists so any agent (Claude Code, Codex) or any of the user's machines can pick up
exactly where the last one left off. It has THREE parts:

1. CURRENT FOCUS  — one or two lines on what's actively being worked on.
2. OPEN ISSUES / BUGS — the live bug/issue table. Found during coding or bug hunts.
3. WORK LOG — signed, dated agent-to-agent entries (what was done, what's next). This is how
   two agents trade and review work without the user re-explaining.
4. SESSION SYNC LOG — per-session list of files added/changed/deleted, for clean git push/pull
   across the user's machines (CSPW-PC, HOME-PC, MacBook).

RULES:
- ALWAYS sign and date your entries (— Agent Name, YYYY-MM-DD).
- Update this BEFORE a context reset and BEFORE pushing, so nothing in-flight is lost.
- Session Sync Log: before pushing, list the files you changed and make sure they're actually
  staged/committed — the log and the commit must agree. Starting on a possibly-behind machine,
  read this first, reconcile against `git status`/`git log`, then pull.
- Keep distinct from CHANGELOG (released versions) and Briefing (feature overview).
- Replace [bracketed] placeholders. Delete this comment block once the project is real.
-->

# [Project Name] — Handoff

## Current Focus
[One or two lines: what is actively being worked on right now, and by whom if relevant.]

---

## Open Issues / Bugs
[Live issues found during coding or bug hunts. Severity: Critical (breaks core function /
crashes for a non-technical user) · Minor (cosmetic / edge case) · Suggestion (optional).
Fix criticals immediately and add a regression test; flag minors/suggestions for the user.]

| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | [Critical/Minor/Suggestion] | [path/to/file] | [what's wrong] | [Open/Fixed] | [Agent] |

---

## Work Log (newest first)
[Signed, dated entries. What was just done, what's in progress, what's blocked, what the next
agent should pick up or re-verify.]

- [YYYY-MM-DD] — [What you did / found / decided. Reference the plan + phase if relevant, e.g.
  "Implemented Phase 3 §4 of plan-x.md; tests pass."] — [Agent Name]

---

## Session Sync Log (newest first)
[One block per working session, for clean cross-device push/pull. List files
added/changed/deleted with a one-line note each, the machine you were on, and push status.]

### [YYYY-MM-DD] — [Machine: CSPW-PC / HOME-PC / HOME-MacOS] — [pushed / not pushed]
- Added:   [path/to/new/file]
- Changed: [path/to/file] ([what changed])
- Deleted: [path/to/file]
- Note:    [anything the next machine/agent should know before continuing.]
