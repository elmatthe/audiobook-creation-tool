#!/usr/bin/env python3
"""verify.py — the mechanical verify gate for the Audiobook Creation Tool.

Run from anywhere; paths are derived from this file's location so the repo
stays portable (no hardcoded user paths). Runs at every phase boundary.

Checks (all must PASS, else the script exits non-zero):
  1. pytest      — run the test suite; only exit 0 passes. Any failure,
                   collection error, OR "no tests collected" (exit 5) is a FAIL.
  2. deps        — every requirements.txt line must be pinned with exact '=='
                   (no bare names, no >= <= ~= != > <, no '-r' recursive includes).
                   PEP 508 environment markers (the part after ';') are allowed —
                   this project guards kokoro/audioop-lts by python_version.
  3. docs        — Changelog.md and Briefing.md must be de-templated real content
                   with a real version entry (not a template stub/placeholder).
  4. docnames    — md-instructions/ must contain the four canonical documents
                   under their EXACT names, must not contain a case-variant
                   alias of any of them, and must still carry the permanent
                   don't-delete/ planning references.
  5. config      — the committed root config.toml must parse and every key must
                   be valid. The running application deliberately falls back on
                   a bad value; the repository gate deliberately does not.

Usage:
    python scripts/verify.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
REQUIREMENTS = SCRIPTS_DIR / "requirements.txt"
# The pytest suite is dev-only and lives under files/tests/ (not shipped),
# while requirements.txt + this gate ship from scripts/.
TESTS_DIR = REPO_ROOT / "files" / "tests"
MD_DIR = REPO_ROOT / "md-instructions"
CHANGELOG = MD_DIR / "Changelog.md"
BRIEFING = MD_DIR / "Briefing.md"
CONFIG_FILE = REPO_ROOT / "config.toml"
# scripts/Universal is the application's import root.
IMPORT_ROOT = SCRIPTS_DIR / "Universal"

# The four permanent documents. These names and this casing are a contract:
# never rename, recase, duplicate or alias them. Compared against the real
# on-disk names, so a case-insensitive filesystem cannot mask a mismatch.
CANONICAL_DOCS: tuple[str, ...] = (
    "Briefing.md",
    "Changelog.md",
    "Decisions.md",
    "Handoff.md",
)

# Permanent planning references that must survive every drop closeout.
PROTECTED_REFERENCES: tuple[str, ...] = (
    "Audiobook-Creation-Tool-v0.6.x-Approved-Plan-Series-Map.md",
    "Audiobook-Creation-Tool-v0.6.x-Decision-Register-1-55.md",
    "Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md",
    "Audiobook-Creation-Tool-v0.6.x-Planning-Handoff-2026-07-31.md",
)
#: Directory holding PROTECTED_REFERENCES, relative to md-instructions/.
PROTECTED_DIR_NAME = "don't-delete"

# Lines on this allowlist are exempt from the strict '==' rule. Documented
# exceptions only — currently none.
PINNING_ALLOWLIST: set[str] = set()

# Markers that betray an un-edited template/placeholder doc.
PLACEHOLDER_MARKERS = (
    "template —",
    "template -",
    "[describe",
    "[e.g.",
    "[list",
    "[what is planned",
    "[x.x.x]",
    "[yyyy-mm-dd",
    "[project name]",
    "[add a short description",
)


def _fail(check: str, detail: str) -> tuple[str, bool, str]:
    return (check, False, detail)


def _pass(check: str, detail: str = "") -> tuple[str, bool, str]:
    return (check, True, detail)


def check_pytest() -> tuple[str, bool, str]:
    """Run pytest against files/tests/. Only exit 0 (all tests passed) is a
    PASS. Exit 5 ("no tests collected") is a FAIL — a verify gate with zero
    tests collected is not a valid gate. Any other code is a failure or
    collection error."""
    if not TESTS_DIR.exists():
        return _fail("pytest", f"tests dir missing: {TESTS_DIR}")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS_DIR), "-q"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    if proc.returncode == 0:
        return _pass("pytest", summary)
    if proc.returncode == 5:
        return _fail("pytest", "no tests collected (an empty gate is not valid)")
    return _fail("pytest", f"exit {proc.returncode}: {summary}")


def check_requirements() -> tuple[str, bool, str]:
    if not REQUIREMENTS.exists():
        return _fail("deps", f"missing {REQUIREMENTS}")
    bad: list[str] = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line in PINNING_ALLOWLIST:
            continue
        # Recursive includes / editable / option lines are not allowed.
        if line.startswith("-"):
            bad.append(f"{line!r} (recursive include / option line)")
            continue
        # The pin rule applies to the requirement itself, not the PEP 508
        # environment marker (e.g. `kokoro==0.9.4 ; python_version < "3.13"`).
        spec = line.split(";", 1)[0].strip()
        # Reject any non-'==' version operator in the spec.
        if re.search(r"(>=|<=|~=|!=|>|<)", spec):
            bad.append(f"{line!r} (non-'==' operator)")
            continue
        # Must be pinned with exactly one '=='.
        if "==" not in spec:
            bad.append(f"{line!r} (bare/unpinned package)")
            continue
    if bad:
        return _fail("deps", "; ".join(bad))
    return _pass("deps", "all dependencies '=='-pinned")


def _is_templated(text: str) -> str | None:
    low = text.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker in low:
            return marker
    return None


def check_docs() -> tuple[str, bool, str]:
    if not CHANGELOG.exists():
        return _fail("docs", f"missing {CHANGELOG}")
    if not BRIEFING.exists():
        return _fail("docs", f"missing {BRIEFING}")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    briefing = BRIEFING.read_text(encoding="utf-8")

    marker = _is_templated(changelog)
    if marker:
        return _fail("docs", f"Changelog.md still has placeholder marker {marker!r}")
    marker = _is_templated(briefing)
    if marker:
        return _fail("docs", f"Briefing.md still has placeholder marker {marker!r}")

    # Require a real version entry: '## [X.Y.Z] - DATE' or '## vX.Y.Z'.
    if not re.search(r"^##\s*\[?v?\d+\.\d+\.\d+\]?", changelog, re.MULTILINE):
        return _fail("docs", "Changelog.md has no real version entry (## [X.Y.Z])")

    return _pass("docs", "Changelog.md + Briefing.md de-templated, version entry present")


def check_doc_names(md_dir: Path | None = None) -> tuple[str, bool, str]:
    """The four canonical documents exist under EXACTLY those names, with no alias.

    ``os.listdir`` is used rather than ``Path.exists`` on purpose. On Windows a
    path lookup is case-insensitive, so ``md-instructions/CHANGELOG.md`` reports
    as existing even when the file on disk is ``Changelog.md`` — which is how a
    stale reference survived here undetected. Comparing the real directory
    entries as exact strings is the only check that behaves the same on NTFS,
    APFS and a case-sensitive Linux filesystem.

    ``md_dir`` exists so the test suite can point the check at a temporary tree
    that actually contains an alias — something a case-insensitive filesystem
    will not let us stage inside the real repository.
    """
    md_dir = MD_DIR if md_dir is None else Path(md_dir)
    protected_dir = md_dir / PROTECTED_DIR_NAME
    if not md_dir.is_dir():
        return _fail("docnames", f"missing {md_dir}")
    entries = sorted(os.listdir(md_dir))
    problems: list[str] = []

    missing = [name for name in CANONICAL_DOCS if name not in entries]
    if missing:
        problems.append("missing canonical file(s): " + ", ".join(missing))

    canonical_lower = {name.lower(): name for name in CANONICAL_DOCS}
    for entry in entries:
        canonical = canonical_lower.get(entry.lower())
        if canonical is not None and entry != canonical:
            problems.append(f"forbidden alias {entry!r} (the canonical name is {canonical!r})")

    if not protected_dir.is_dir():
        problems.append(f"missing protected directory {protected_dir.name}/")
    else:
        protected_entries = set(os.listdir(protected_dir))
        absent = [name for name in PROTECTED_REFERENCES if name not in protected_entries]
        if absent:
            problems.append("missing permanent reference(s): " + ", ".join(absent))

    if problems:
        return _fail("docnames", "; ".join(problems))
    return _pass(
        "docnames",
        f"{len(CANONICAL_DOCS)} canonical names exact, no alias, "
        f"{len(PROTECTED_REFERENCES)} permanent references present",
    )


def check_config(
    config_file: Path | None = None, repo_root: Path | None = None
) -> tuple[str, bool, str]:
    """The committed root config.toml parses and every key validates.

    Reuses the application's own loader so there is one set of rules rather than
    two that can drift. The runtime *tolerates* a bad value (it falls back and
    warns, so a user's hand-edit can never stop the app from starting); the
    repository gate does the opposite and fails on any diagnostic, because a
    committed file that needs a fallback is a defect we are shipping.

    The two arguments exist so the suite can prove that against a temporary
    invalid file without editing the committed one.
    """
    config_file = CONFIG_FILE if config_file is None else Path(config_file)
    repo_root = REPO_ROOT if repo_root is None else Path(repo_root)
    if not config_file.is_file():
        return _fail("config", f"missing {config_file}")
    if str(IMPORT_ROOT) not in sys.path:
        sys.path.insert(0, str(IMPORT_ROOT))
    try:
        from shared import config as shared_config
        from shared.version import VERSION
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        return _fail("config", f"could not import the configuration loader: {exc}")

    effective = shared_config.load(
        config_path=config_file,
        settings_data={},          # the committed file is judged on its own
        repo_root=repo_root,
    )
    if effective.diagnostics:
        detail = "; ".join(d.summary_line() for d in effective.diagnostics)
        return _fail("config", detail)
    if effective.project.version != VERSION:
        return _fail(
            "config",
            f"project.version {effective.project.version!r} != version.py {VERSION!r}",
        )
    return _pass(
        "config",
        f"config.toml valid; version {effective.project.version}, "
        f"platforms {', '.join(effective.project.platforms)}",
    )


def main() -> int:
    checks = [
        check_pytest(),
        check_requirements(),
        check_docs(),
        check_doc_names(),
        check_config(),
    ]
    print("=" * 60)
    print("verify.py — Audiobook Creation Tool gate")
    print("=" * 60)
    all_ok = True
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        line = f"  [{status}] {name:<8}"
        if detail:
            line += f" - {detail}"
        print(line)
    print("-" * 60)
    print(f"  RESULT: {'PASS' if all_ok else 'FAIL'}")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
