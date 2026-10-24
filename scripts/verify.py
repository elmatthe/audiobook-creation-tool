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
                   under their EXACT names, with no aliases, extra files or
                   subdirectories. Local archives are not repository inputs.
  5. config      — the committed root config.toml must parse and every key must
                   be valid. The running application deliberately falls back on
                   a bad value; the repository gate deliberately does not. It
                   must also state [development] developer_mode = false
                   (v0.7.0 P03D): developer mode is never committed.

Usage:
    python scripts/verify.py
    python -u scripts/verify.py --evidence-dir files/dev-work/act070-remediation/verify/<phase>-<sha>-<run>

Evidence mode (developer observability, v0.7.0 P00C) runs the same five gates,
in the same order and with the same meanings, and leaves a durable record in a
NEW directory under files/dev-work/act070-remediation/ (never an existing one):

  verify.log       this script's own log, flushed line by line
  pytest.log       the pytest child's merged stdout/stderr, streamed and flushed
                   as it runs (tracebacks included, nothing truncated)
  pytest.xml       pytest's JUnit report; pytest also gets -ra so the log lists
                   every skip and xfail
  start.json       the start record: argv, interpreter, tested-tree fingerprint
  INCOMPLETE.json  present from the start until normal completion; an
                   interruption or an unexpected error is recorded in it
  result.json      written atomically, and only after every gate has run

A directory holding INCOMPLETE.json, or lacking result.json, is never a PASS
(read_evidence_status). Evidence mode adds two integrity conditions to PASS: a
pytest exit 0 must be matched by a readable JUnit report with tests and no
failures, and the tree fingerprint must be the same at the end as at the start.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
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
# scripts is the application's import root.
IMPORT_ROOT = SCRIPTS_DIR
# Evidence mode writes only below this ignored folder (plan §6, P00C).
EVIDENCE_ROOT = REPO_ROOT / "files" / "dev-work" / "act070-remediation"
# Untracked files can change what the suite tests only here: a new test module or
# source file not yet added. Other untracked trees (pytest scratch under
# files/run-temp/, local notes) are deliberately outside the fingerprint.
FINGERPRINT_UNTRACKED_SCOPES: tuple[str, ...] = ("scripts", "files/tests")
# Output chunks of pytest kept in memory for the one-line summary; the full
# output is in pytest.log.
SUMMARY_CHUNKS = 200
EXIT_REFUSED = 2
EXIT_INTERRUPTED = 130
MARKER_NAME = "INCOMPLETE.json"
RESULT_NAME = "result.json"
# One component of a path below EVIDENCE_ROOT: portable, no spaces, and no
# trailing dot (Windows silently drops it, which would alias an existing name).
_EVIDENCE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?<!\.)$")
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)

# The four permanent documents. These names and this casing are a contract:
# never rename, recase, duplicate or alias them. Compared against the real
# on-disk names, so a case-insensitive filesystem cannot mask a mismatch.
CANONICAL_DOCS: tuple[str, ...] = (
    "Briefing.md",
    "Changelog.md",
    "Decisions.md",
    "Handoff.md",
)

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
    """Only the four canonical files exist, under EXACTLY those names.

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

    unexpected = [name for name in entries if name not in CANONICAL_DOCS]
    if unexpected:
        problems.append("unexpected entry(s): " + ", ".join(unexpected))
    nonfiles = [name for name in CANONICAL_DOCS
                if name in entries and not (md_dir / name).is_file()]
    if nonfiles:
        problems.append("canonical name is not a file: " + ", ".join(nonfiles))

    if problems:
        return _fail("docnames", "; ".join(problems))
    return _pass(
        "docnames",
        f"exactly {len(CANONICAL_DOCS)} canonical files, no aliases or extra entries",
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
    # v0.7.0 P03D: the shipped value is an explicit false. A developer who switched it on locally restores their own
    # edit before a checkpoint; a deleted line would silently stop documenting the setting.
    if effective.development.developer_mode:
        return _fail("config", "developer_mode = true must never be committed; set it back to false under [development]")
    if effective.source_of("development.developer_mode") != shared_config.SOURCE_TOML:
        return _fail("config", "config.toml must state developer_mode = false under [development]")
    return _pass(
        "config",
        f"config.toml valid; version {effective.project.version}, "
        f"platforms {', '.join(effective.project.platforms)}",
    )


# --------------------------------------------------------------------------- #
# Evidence mode (--evidence-dir)
# --------------------------------------------------------------------------- #


class EvidenceError(ValueError):
    """The requested evidence directory is unsafe, out of scope or already exists."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _inside(path: Path, root: Path) -> bool:
    """``path`` is strictly below ``root`` — compared case-insensitively where the filesystem is."""
    p = Path(os.path.normcase(str(path)))
    r = Path(os.path.normcase(str(root)))
    return p != r and p.is_relative_to(r)


def resolve_evidence_dir(
    raw: str, repo_root: Path | None = None, evidence_root: Path | None = None
) -> Path:
    """Turn ``--evidence-dir`` into a safe absolute path that does not exist yet.

    Relative values are taken from the repository root, not the current
    directory, so the same command means the same place wherever it is run.
    Refused: empty values, ``..``, anything not strictly below the evidence
    root, a path that a link or junction would redirect, non-portable or
    reserved component names, and any path that already exists — earlier
    evidence is never reused or overwritten.
    """
    repo_root = REPO_ROOT if repo_root is None else Path(repo_root)
    evidence_root = EVIDENCE_ROOT if evidence_root is None else Path(evidence_root)
    if not raw or raw != raw.strip():
        raise EvidenceError("the value is empty or has leading/trailing whitespace")
    candidate = Path(raw)
    if ".." in candidate.parts:
        raise EvidenceError(f"{raw!r} contains '..'")
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    target = Path(os.path.abspath(candidate))
    # Windows' path normalization silently drops a trailing dot or space, so
    # "run." would quietly become "run"; refuse anything it would rewrite.
    if str(target) != str(candidate):
        raise EvidenceError(f"{raw!r} would be rewritten by the operating system to {str(target)!r}")
    root = Path(os.path.abspath(evidence_root))
    if not _inside(target, root):
        raise EvidenceError(f"{raw!r} is not a new directory below {root}")
    for part in target.parts[len(root.parts):]:
        if not _EVIDENCE_COMPONENT.match(part) or _WINDOWS_RESERVED.match(part):
            raise EvidenceError(
                f"path component {part!r} is not allowed (letters, digits, '.', '_', '-'; "
                "no trailing dot, no reserved device name)")
    if os.path.normcase(str(target.resolve())) != os.path.normcase(str(target)):
        raise EvidenceError(f"{raw!r} passes through a link or junction")
    if os.path.lexists(target):
        raise EvidenceError(f"{target} already exists; evidence is never reused or overwritten")
    return target


def create_evidence_dir(raw: str) -> Path:
    """Resolve and create the directory; ``mkdir`` without ``exist_ok`` closes the race with a second run."""
    target = resolve_evidence_dir(raw)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir()
    except FileExistsError:
        raise EvidenceError(f"{target} already exists; evidence is never reused or overwritten") from None
    except OSError as exc:
        raise EvidenceError(f"cannot create {target}: {exc}") from None
    if os.path.normcase(str(target.resolve())) != os.path.normcase(str(target)):
        raise EvidenceError(f"{target} resolved through a link or junction after creation")
    return target


def _git(repo_root: Path, *args: str) -> str:
    # --no-optional-locks: fingerprinting must not even refresh the index.
    proc = subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=str(repo_root),
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8", "surrogateescape")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(repo_root: Path | None = None) -> dict:
    """SHA-256 over the working-tree bytes of what the suite tests.

    The starting commit alone does not identify the tested tree when edits are
    uncommitted (plan §6), so this hashes what is on disk: every tracked file,
    plus untracked, non-ignored files in FINGERPRINT_UNTRACKED_SCOPES. A
    tracked file missing from the working tree is recorded as deleted, not
    skipped. Read-only: no index refresh, no objects written.
    """
    repo_root = REPO_ROOT if repo_root is None else Path(repo_root)
    try:
        tracked = {p for p in _git(repo_root, "ls-files", "-z", "--cached").split("\0") if p}
        untracked = {p for p in _git(repo_root, "ls-files", "-z", "--others", "--exclude-standard",
                                     "--", *FINGERPRINT_UNTRACKED_SCOPES).split("\0") if p}
        status = [line for line in _git(repo_root, "status", "--porcelain=v1",
                                        "--untracked-files=no").splitlines() if line]
        try:
            head = _git(repo_root, "rev-parse", "--verify", "HEAD").strip()
        except subprocess.CalledProcessError:
            head = None  # a repository with no commit yet
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    digest = hashlib.sha256()
    deleted: list[str] = []
    for relative in sorted(tracked | untracked):
        try:
            content = _sha256_file(repo_root / relative)
        except FileNotFoundError:
            content = "<deleted>"
            deleted.append(relative)
        digest.update(relative.encode("utf-8", "surrogateescape") + b"\0" + content.encode("ascii") + b"\n")
    return {
        "available": True,
        "sha256": digest.hexdigest(),
        "head": head,
        "tracked_files": len(tracked),
        "untracked_in_scope": sorted(untracked),
        "untracked_scopes": list(FINGERPRINT_UNTRACKED_SCOPES),
        "dirty_tracked": status,
        "deleted_tracked": deleted,
    }


def _interpreter() -> dict:
    return {
        "executable": sys.executable,
        "version": sys.version,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "platform": sys.platform,
    }


def read_junit(path: Path) -> dict:
    """Totals from a JUnit report, or why it cannot be trusted. Missing or truncated is never a pass."""
    if not path.is_file():
        return {"valid": False, "problem": "missing"}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"valid": False, "problem": f"unreadable or truncated ({exc})"}
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
    else:
        suites = []
    if not suites:
        return {"valid": False, "problem": f"no <testsuite> element (root is <{root.tag}>)"}
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.get(key, "0"))
    except ValueError as exc:
        return {"valid": False, "problem": f"non-numeric total ({exc})"}
    return {"valid": True, **totals}


def read_evidence_status(directory: Path) -> str:
    """PASS, FAIL, INCOMPLETE or INVALID for an evidence directory.

    Only a finalized result.json with no INCOMPLETE marker beside it can say
    PASS; a killed run leaves the marker behind and so reads INCOMPLETE.
    """
    directory = Path(directory)
    if (directory / MARKER_NAME).exists() or not (directory / RESULT_NAME).is_file():
        return "INCOMPLETE"
    try:
        result = json.loads((directory / RESULT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "INVALID"
    if not isinstance(result, dict) or result.get("status") != "COMPLETE" \
            or result.get("result") not in ("PASS", "FAIL"):
        return "INVALID"
    return result["result"]


class EvidenceRun:
    """The files of one evidence directory. Every write is flushed as it happens."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.junit: dict | None = None
        self._log = open(directory / "verify.log", "x", encoding="utf-8", newline="\n")

    def log(self, message: str) -> None:
        for line in message.splitlines() or [""]:
            self._log.write(f"{_now()} {line}\n")
        self._log.flush()

    def close(self) -> None:
        self._log.close()

    def _write_json(self, name: str, data: dict) -> None:
        """Write to a fresh temporary file, fsync, then rename into place."""
        temporary = self.directory / f".{name}.tmp"
        with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.directory / name)

    def write_start(self, data: dict) -> None:
        if (self.directory / "start.json").exists():
            raise EvidenceError("start.json already exists")
        self._write_json("start.json", data)

    def mark_incomplete(self, data: dict) -> None:
        self._write_json(MARKER_NAME, {"status": "INCOMPLETE", **data})

    def finalize(self, result: dict) -> None:
        """result.json first, then the marker goes: a crash between the two still reads INCOMPLETE."""
        if (self.directory / RESULT_NAME).exists():
            raise EvidenceError(f"{RESULT_NAME} already exists")
        self._write_json(RESULT_NAME, result)
        (self.directory / MARKER_NAME).unlink()


def _pytest_command(junit_xml: Path) -> list[str]:
    """The ordinary scope and -q, plus -ra and a JUnit report. ``-u`` keeps the
    child's output unbuffered, so pytest.log fills while the suite runs."""
    return [sys.executable, "-u", "-m", "pytest", str(TESTS_DIR), "-q", "-ra", f"--junitxml={junit_xml}"]


def _stop_child(proc: subprocess.Popen, run: EvidenceRun) -> None:
    """End the one known pytest child — nothing else — and say so in verify.log."""
    if proc.poll() is None:
        run.log(f"stopping pytest child pid {proc.pid}")
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    run.log(f"pytest child pid {proc.pid} ended with exit {proc.returncode}")


def check_pytest_streaming(run: EvidenceRun) -> tuple[tuple[str, bool, str], int | None]:
    """check_pytest's contract, with the output streamed to pytest.log as it arrives.

    Returns the gate tuple and pytest's native exit status. Exit 0 passes only
    when the JUnit report agrees; exit 5 (no tests collected) and every other
    non-zero exit fail exactly as in the ordinary gate.
    """
    if not TESTS_DIR.exists():
        return _fail("pytest", f"tests dir missing: {TESTS_DIR}"), None
    junit_path = run.directory / "pytest.xml"
    command = _pytest_command(junit_path)
    run.log(f"pytest command: {command}")
    tail: deque[bytes] = deque(maxlen=SUMMARY_CHUNKS)
    with open(run.directory / "pytest.log", "xb") as sink:
        proc = subprocess.Popen(command, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        run.log(f"pytest child started, pid {proc.pid}")
        try:
            # read1, not line iteration: -q progress dots arrive without a
            # newline, and a hung test must still show up in pytest.log.
            for chunk in iter(lambda: proc.stdout.read1(1 << 16), b""):
                sink.write(chunk)
                sink.flush()
                tail.append(chunk)
            returncode = proc.wait()
        except BaseException:
            _stop_child(proc, run)
            raise
        finally:
            proc.stdout.close()
    run.junit = read_junit(junit_path)
    run.log(f"pytest exit {returncode}; JUnit {run.junit}")
    lines = b"".join(tail).decode("utf-8", "replace").splitlines()
    summary = next((line.strip() for line in reversed(lines) if line.strip()), "(no output)")
    if returncode == 0:
        junit = run.junit
        if not junit["valid"]:
            return _fail("pytest", f"exit 0 but the JUnit report is {junit['problem']}"), returncode
        if junit["tests"] == 0:
            return _fail("pytest", "exit 0 but the JUnit report records no tests"), returncode
        if junit["failures"] or junit["errors"]:
            return _fail("pytest", f"exit 0 but the JUnit report records {junit['failures']} failure(s) "
                                   f"and {junit['errors']} error(s)"), returncode
        return _pass("pytest", summary), returncode
    if returncode == 5:
        return _fail("pytest", "no tests collected (an empty gate is not valid)"), returncode
    return _fail("pytest", f"exit {returncode}: {summary}"), returncode


def _evidence_gates():
    """The five gates of main(), in the same order; only pytest takes its streaming form.

    Looked up at call time so the suite can stand a gate in for a synthetic one.
    """
    return [
        ("pytest", None),
        ("deps", check_requirements),
        ("docs", check_docs),
        ("docnames", check_doc_names),
        ("config", check_config),
    ]


def run_with_evidence(raw_dir: str, argv: list[str]) -> int:
    try:
        directory = create_evidence_dir(raw_dir)
    except EvidenceError as exc:
        print(f"verify.py: refusing --evidence-dir: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    run = EvidenceRun(directory)
    started_at, started = _now(), time.monotonic()
    current: str | None = None
    try:
        run.log(f"verify.py evidence mode; directory {directory}")
        interpreter = _interpreter()
        run.log(f"interpreter {interpreter['executable']} ({interpreter['version'].split()[0]})")
        start_fingerprint = tree_fingerprint()
        run.log(f"tree fingerprint at start: {start_fingerprint.get('sha256', start_fingerprint.get('error'))}")
        run.write_start({
            "schema": 1, "started_at": started_at, "argv": argv, "cwd": os.getcwd(),
            "repo_root": str(REPO_ROOT), "interpreter": interpreter, "fingerprint": start_fingerprint,
        })
        run.mark_incomplete({"reason": "started; no normal completion has been recorded",
                             "started_at": started_at, "current_gate": None})
        records = []
        for name, gate in _evidence_gates():
            current = name
            run.mark_incomplete({"reason": "started; no normal completion has been recorded",
                                 "started_at": started_at, "current_gate": name})
            run.log(f"gate {name}: start")
            began = time.monotonic()
            if gate is None:
                (_, ok, detail), exit_status = check_pytest_streaming(run)
            else:
                (_, ok, detail), exit_status = gate(), None
            elapsed = round(time.monotonic() - began, 3)
            records.append({"name": name, "status": "PASS" if ok else "FAIL", "ok": ok, "detail": detail,
                            "exit_status": exit_status, "elapsed_seconds": elapsed})
            run.log(f"gate {name}: {'PASS' if ok else 'FAIL'} in {elapsed:.3f}s (exit {exit_status}) - {detail}")
        current = None
        end_fingerprint = tree_fingerprint()
        tree_ok = (start_fingerprint.get("available") and end_fingerprint.get("available")
                   and start_fingerprint["sha256"] == end_fingerprint["sha256"])
        if tree_ok:
            tree_detail = f"unchanged during the run ({end_fingerprint['sha256']})"
        elif not (start_fingerprint.get("available") and end_fingerprint.get("available")):
            tree_detail = "fingerprint unavailable: " + "; ".join(
                f["error"] for f in (start_fingerprint, end_fingerprint) if not f.get("available"))
        else:
            tree_detail = (f"changed during the run ({start_fingerprint['sha256']} -> "
                           f"{end_fingerprint['sha256']}); the tested inputs were not frozen")
        gates_ok = all(r["ok"] for r in records)
        all_ok = bool(gates_ok and tree_ok)
        lines = _report_lines([(r["name"], r["ok"], r["detail"]) for r in records], all_ok,
                              extra=[("tree", bool(tree_ok), tree_detail)])
        run.finalize({
            "schema": 1, "status": "COMPLETE", "result": "PASS" if all_ok else "FAIL",
            "exit_code": 0 if all_ok else 1, "gates_result": "PASS" if gates_ok else "FAIL",
            "gates": records,
            "evidence_checks": [{"name": "tree", "status": "PASS" if tree_ok else "FAIL", "detail": tree_detail}],
            "junit": run.junit, "started_at": started_at, "finished_at": _now(),
            "elapsed_seconds": round(time.monotonic() - started, 3), "interpreter": interpreter,
            "fingerprint": {"start": start_fingerprint, "end": end_fingerprint},
        })
        run.log("\n".join(lines))
        run.log(f"complete: RESULT {'PASS' if all_ok else 'FAIL'}")
        print("\n".join(lines))
        print(f"  evidence: {directory}")
        return 0 if all_ok else 1
    except KeyboardInterrupt:
        run.log(f"INTERRUPTED (KeyboardInterrupt) during gate {current}; no result was recorded")
        run.mark_incomplete({"reason": "interrupted (KeyboardInterrupt)", "started_at": started_at,
                             "current_gate": current, "interrupted_at": _now()})
        print(f"verify.py: INCOMPLETE - interrupted during gate {current}; evidence: {directory}", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BaseException as exc:
        run.log(f"ERROR during gate {current}; no result was recorded\n{traceback.format_exc()}")
        run.mark_incomplete({"reason": f"error: {type(exc).__name__}: {exc}", "started_at": started_at,
                             "current_gate": current, "failed_at": _now()})
        raise
    finally:
        run.close()


class _EvidenceDirAction(argparse.Action):
    """Store --evidence-dir once; a second occurrence is an error, not a silent override."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(f"{option_string} may be given only once")
        setattr(namespace, self.dest, values)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify.py", description="The mechanical verify gate for the Audiobook Creation Tool.")
    parser.add_argument(
        "--evidence-dir", metavar="DIR", action=_EvidenceDirAction, default=None,
        help="write durable run evidence to this NEW directory below "
             "files/dev-work/act070-remediation/ (relative paths are from the repository root)")
    return parser.parse_args(argv)


def _report_lines(checks, all_ok: bool, extra=()) -> list[str]:
    lines = ["=" * 60, "verify.py — Audiobook Creation Tool gate", "=" * 60]
    for name, ok, detail in [*checks, *extra]:
        line = f"  [{'PASS' if ok else 'FAIL'}] {name:<8}"
        if detail:
            line += f" - {detail}"
        lines.append(line)
    lines += ["-" * 60, f"  RESULT: {'PASS' if all_ok else 'FAIL'}", "=" * 60]
    return lines


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.evidence_dir is not None:
        return run_with_evidence(args.evidence_dir, list(sys.argv if argv is None else argv))
    checks = [
        check_pytest(),
        check_requirements(),
        check_docs(),
        check_doc_names(),
        check_config(),
    ]
    all_ok = all(ok for _name, ok, _detail in checks)
    print("\n".join(_report_lines(checks, all_ok)))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
