# Audiobook Creation Tool — Codex entry point

Read `AI-WORKSPACE.md` (repo root) first — it defines the global workspace conventions
(layout, git habits, verify gate, docs contract).

**Session kickoff read order:**
1. `md-instructions/Briefing.md` — what this project is
2. `md-instructions/CHANGELOG.md` — what has shipped
3. `md-instructions/DECISIONS.md` — standing decisions (note the v0.5.0 one-commit-per-drop
   rule: no per-phase commits for the entire v0.5.0 drop sequence; the maintainer pushes)
4. `md-instructions/handoff.md` — live state, open issues, what to do next

If an instruction-drop markdown is present in `md-instructions/` (named like
`X.Y.Z-dropN-*.md`), read it fully next; it is temporary and gets deleted once implemented.

Mechanical gate: `python scripts/verify.py` must print `RESULT: PASS` before a drop is done.
Program code lives in `scripts/Universal/`; dev-only assets and tests in `files/`.
