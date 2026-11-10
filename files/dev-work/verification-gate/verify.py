#!/usr/bin/env python3
"""verify.py — the one verification gate of the Audiobook Creation Tool.

Run it with the project environment's interpreter, from any directory:

    .venv\\Scripts\\python.exe files/dev-work/verification-gate/verify.py --mode full --platform windows
    ... --mode focused --test files/tests/test_cancel_semantics.py [--test <node id>] [--feature ACT.TTS.CANCEL] [--journey cover.center-crop]
    ... --mode changed --base origin/master
    ... --mode qualification --scenario m4b-scaling
    ... --status files/dev-work/verification-gate/outputs/<run> [--require-current]

What a mode means (plan §6):

  focused        the named tests or features plus the required guards. PASS for that scope only.
  changed        the tests a merge-base diff plus dirty files reach; an unmapped or shared change widens to every test.
                 PASS for the selected scope, never full acceptance.
  full           the native and real-media journeys first, then the whole ordinary suite, every guarded group, deps, docs, docnames,
                 config, the collection partition, the coverage inventory and the gate's own self-tests. The routine gate. Requirements
                 owned by later phases are listed as NOT RUN in every result: this is not full acceptance and not release readiness
                 until they exist and pass.
  qualification  one named expensive scenario, run on its own and never by a routine mode. m4b-scaling is implemented (v0.7.2
                 Phase 7B: scaling/qualify.py, about three hours); each other scenario reports NOT RUN and names the phase
                 that owns it.

The gates of a full run, always in this order and all of them even after a failure:

  acceptance  real Windows input into isolated instances of the real application, real media in and out, judged from outside
            (acceptance_runner.py, helpers/acceptance_report.py). First, because it needs the desktop while someone is at it, and a locked
            session reads BLOCKED, never a pass. Takes over the mouse and keyboard for its few minutes: nothing else should be used meanwhile.
  pytest    files/tests, leaving out the suites of files/tests/guarded_groups.json. Exit 0 alone never passes: the JUnit
            report and the session's own record must exist and agree with it.
  guarded   each group of guarded_groups.json through files/tests/guarded_pytest.py (process-lifetime write, process and
            network protection). A group passes only when pytest passed and the guard saw no unintended production write, no
            unqualified process and no network or model use. Its basetemps stay below files/dev-work/p05b-stage4c because six
            production modules pin that root and its prefixes (Decisions.md, v0.7.2 Phase 2); its reports are copied into
            this run's evidence.
  deps      requirements.txt is '=='-pinned, PEP 508 markers allowed, no recursive includes, and the hash lock beside it
            records this file and locks every pin.
  docs      Changelog.md and Briefing.md are de-templated, with a real version entry.
  docnames  md-instructions/ holds the four canonical documents under their exact names and nothing else.
  config    the committed root config.toml parses, every key validates, its version matches, and it states
            [development] developer_mode = false.

Every invocation that gets past its arguments owns one new directory below outputs/, and no other. See results.json,
summary.md, start.json, selection.json, logs/ and reports/ there. outputs/ is ignored and disposable; the next run recreates
it. Runs written by the old gate stay where they are and read as legacy, never as current acceptance.

Exit codes are the contract: 0 PASS for the requested scope, 1 FAIL, 2 BLOCKED (a prerequisite is unavailable), 3 NOT RUN or
incomplete (including no tests executed), 64 invalid invocation or configuration, 130 interrupted. Windows error dialogs are
turned off for this process and everything it starts before anything starts (helpers/winproc.py explains why that matters
and what can undo it).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent
# files/dev-work/verification-gate/verify.py: the repository root is three levels above this folder.
REPO_ROOT = GATE_DIR.parents[2]

_on_path = str(GATE_DIR) in sys.path
if not _on_path:
    sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report, coverage_model, pytest_reports, runstore, scratch as scratch_store, selection as selection_rules, winproc  # noqa: E402
from helpers import inventory as inventory_tools  # noqa: E402

if not _on_path:
    sys.path.remove(str(GATE_DIR))

SCRIPTS_DIR = REPO_ROOT / "scripts"
REQUIREMENTS = SCRIPTS_DIR / "requirements.txt"
# The pytest suite is dev-only and lives under files/tests/ (not shipped).
TESTS_DIR = REPO_ROOT / "files" / "tests"
# TESTS_DIR / GUARDED_SPEC_NAME lists the suites that run only under the guarded runner, their groups and the reviewed
# process sources their run configuration pins. guarded_pytest.py accepts a basetemp and report only below
# REPO_ROOT / GUARDED_SUBDIR (ignored).
GUARDED_SPEC_NAME = "guarded_groups.json"
GUARDED_SUBDIR = Path("files") / "dev-work" / "p05b-stage4c"
MD_DIR = REPO_ROOT / "md-instructions"
CHANGELOG = MD_DIR / "Changelog.md"
BRIEFING = MD_DIR / "Briefing.md"
CONFIG_FILE = REPO_ROOT / "config.toml"
# scripts is the application's import root.
IMPORT_ROOT = SCRIPTS_DIR
# Every run owns one new child of this folder (ignored).
OUTPUTS_ROOT = GATE_DIR / "outputs"
# A run's disposable scratch (pytest basetemp, TEMP, pytest cache) is one new child of this folder, in the system temp folder
# where pytest has always put the suite's scratch. The owner approved this exact root as an exception on 2026-11-06, with the
# conditions helpers/scratch.py keeps (Decisions.md, v0.7.2 Phase 3). Deliberately not inside the repository, measured on HOME-PC.
# Something outside the process briefly holds directories created under the repository, so renaming one fails
# with WinError 5: 7 to 18 of 1,500 there against 0 of 1,500 here, which makes test_venv_recovery fail 2 runs in 6. And inside
# outputs/<run>/ git runs out of path: it is not long-path aware by default and a test's repository needs room for
# .git/objects/xx/<38 hex>.
SCRATCH_ROOT = Path(tempfile.gettempdir()) / "act-gate"
POLICY_FILE = GATE_DIR / "verification.json"
COVERAGE_FILE = GATE_DIR / "coverage.json"
ACCEPTANCE_RUNNER = GATE_DIR / "acceptance_runner.py"
BASELINES_FILE = GATE_DIR / "baselines" / "approved.json"
# Runs of the old gate, under their old schema. Read-only: never moved, rewritten or made current.
LEGACY_EVIDENCE_ROOT = REPO_ROOT / "files" / "dev-work" / "act070-remediation"
# Untracked files can change what is tested only here: a new test, source file or gate helper not yet added. Other
# untracked trees (pytest scratch under files/run-temp/, local notes) are deliberately outside the fingerprint.
FINGERPRINT_UNTRACKED_SCOPES: tuple[str, ...] = (
    "scripts", "files/tests", "files/dev-work/verification-gate", "files/dev-work/feature-map")
# Which identity a path belongs to, first match wins. Documentation is separate so a docs-only commit can truthfully carry
# code evidence forward; everything not named is "other", which never carries.
DIGEST_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("policy", ("files/dev-work/verification-gate/", "files/dev-work/feature-map/", "files/tests/guarded_groups.json",
                "pytest.ini", ".gitignore", ".gitattributes")),
    ("tests", ("files/tests/", "files/test-files/")),
    ("locks", ("scripts/requirements", "scripts/qwen3-requirements", "scripts/qwen3-artifacts")),
    ("source", ("scripts/", "config.toml", "Setup_and_Run-")),
    ("docs", ("md-instructions/", "files/plans/", "files/release-history/", "README.md", "REPO-STRUCTURE.md")),
)
_OUTPUTS_RELATIVE = "files/dev-work/verification-gate/outputs/"
SCENARIO_NAMES = ("m4b-scaling", "edge-low-memory", "optional-engines", "fresh-windows")
MODES = ("focused", "changed", "full", "qualification")
GATE_ORDER = ("acceptance", "pytest", "guarded", "deps", "docs", "docnames", "config")
# Never inherited by a stage: each could narrow, extend or redirect what pytest runs without appearing on its command line.
_SCRUBBED_ENV_PREFIXES = ("PYTEST_", "_PYTEST", "ACT_GATE_")
_SCRUBBED_ENV = {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONBREAKPOINT"}
# Tests at this depth have a stack dumped into the log long before the stall limit ends them. The slowest is about 80 s.
FAULTHANDLER_SECONDS = 600
SUMMARY_BYTES = 1 << 16

# The four permanent documents. These names and this casing are a contract: never rename, recase, duplicate or alias
# them. Compared against the real on-disk names, so a case-insensitive filesystem cannot mask a mismatch.
CANONICAL_DOCS: tuple[str, ...] = (
    "Briefing.md",
    "Changelog.md",
    "Decisions.md",
    "Handoff.md",
)

# Lines on this allowlist are exempt from the strict '==' rule. Documented exceptions only — currently none.
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


class GuardedSpecError(ValueError):
    """files/tests/guarded_groups.json is missing a part, names a missing suite or lists one twice."""


class PolicyError(ValueError):
    """verification.json or coverage.json is unusable."""


class InvocationError(ValueError):
    """The request is well formed but names something that does not exist: exit 64, with a record of it."""


def load_guarded_spec() -> dict | None:
    """The guarded-suite specification, or None when the test tree has none (then nothing is guarded)."""
    path = TESTS_DIR / GUARDED_SPEC_NAME
    if not path.is_file():
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("version") != 1 or not spec.get("groups"):
        raise GuardedSpecError(f"{path.name}: unknown version or no groups")
    seen: set[str] = set()
    for group in spec["groups"]:
        name, prefix, modules = group.get("name"), group.get("basetemp_prefix"), group.get("modules")
        if not name or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name) or not prefix or not modules:
            raise GuardedSpecError(f"{path.name}: group {name!r} needs a name, a basetemp_prefix and modules")
        for module in modules:
            if module in seen:
                raise GuardedSpecError(f"{path.name}: {module} is listed in more than one group")
            if Path(module).name != module or not (TESTS_DIR / module).is_file():
                raise GuardedSpecError(f"{path.name}: {module} is not a test module in {TESTS_DIR}")
            seen.add(module)
    return spec


def guarded_modules() -> list[str]:
    """Every suite the guarded gate runs and the ordinary pytest gate therefore leaves out."""
    spec = load_guarded_spec()
    return [] if spec is None else [m for group in spec["groups"] for m in group["modules"]]


def _ignore_arguments() -> list[str]:
    return [f"--ignore={TESTS_DIR / module}" for module in guarded_modules()]


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded_run_config(spec: dict) -> dict:
    """guarded_pytest.py configuration version 1 for this tree: each reviewed process source pinned by its current
    SHA-256 (the tree fingerprint and the runner's own re-check keep it from changing during the run), each tool by
    resolved path and SHA-256. A listed source or tool that is missing fails the gate rather than being dropped."""
    sites = {}
    for relative, functions in spec.get("process_sites", {}).items():
        path = REPO_ROOT / relative
        if not path.is_file():
            raise GuardedSpecError(f"reviewed process source {relative} is missing")
        sites[relative] = {"sha256": _sha256_of(path), "functions": list(functions)}
    tools = {}
    for name in spec.get("tools", []):
        found = shutil.which(name)
        if not found:
            raise GuardedSpecError(f"tool {name!r} is not on PATH")
        resolved = Path(found).resolve()
        tools[name] = {"path": str(resolved), "sha256": _sha256_of(resolved)}
    config = {"version": 1, "process_sites": sites, "tools": tools}
    if "spacy_fixture" in spec:
        config["spacy_fixture"] = spec["spacy_fixture"]
    return config


def _guarded_command(config: Path, report: Path, basetemp: Path, targets: list[str], *, extra=()) -> list[str]:
    """The runner under ``-I -B``. ``targets`` are module names or node ids relative to TESTS_DIR's parent's parent."""
    resolved = [str(TESTS_DIR / target) for target in targets]
    return [sys.executable, "-I", "-B", str(TESTS_DIR / "guarded_pytest.py"), str(config), str(report), *resolved,
            "-q", "-p", "no:cacheprovider", *extra, f"--basetemp={basetemp}"]


def _read_guard_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"unreadable": f"{type(exc).__name__}: {exc}"}


def _judge_group(name: str, returncode: int, report: dict, *, require_tests: bool = True) -> tuple[bool, str]:
    """A group passes only on every one of: runner exit 0, pytest exit 0, at least one test passed, none failed
    or errored, no unintended production write, no unqualified process and no network/model use."""
    if "unreadable" in report:
        return False, f"{name}: exit {returncode}, guard report {report['unreadable']}"
    counts = report.get("counts", {})
    problems = []
    if returncode != 0 or report.get("outer_exit") != 0:
        problems.append(f"exit {returncode}/outer {report.get('outer_exit')}")
    if report.get("pytest_exit") != 0:
        problems.append(f"pytest exit {report.get('pytest_exit')}")
    if require_tests and not counts.get("passed"):
        problems.append("no test passed")
    for key in ("failed", "error"):
        if counts.get(key):
            problems.append(f"{counts[key]} {key}")
    for key, label in (("unintended_production_refusals", "unintended production write(s)"),
                       ("unexpected_processes", "unqualified process(es)"),
                       ("network_model_refusals", "network/model refusal(s)")):
        if report.get(key):
            problems.append(f"{len(report[key])} {label}")
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no counts"
    if problems:
        return False, f"{name}: FAIL ({'; '.join(problems)}; {summary})"
    return True, f"{name}: {summary}"


def check_guarded_specification(membership: dict | None = None) -> tuple[str, bool, str]:
    """The guarded specification is usable, every source and tool it pins exists, and its groups are exactly the membership
    the policy names. Suite membership never changes as a side effect: moving a module takes an edit in both places."""
    try:
        spec = load_guarded_spec()
    except (GuardedSpecError, ValueError) as exc:
        return _fail("guarded", f"guarded-suite specification unusable: {exc}")
    if spec is None:
        return _fail("guarded", f"missing {TESTS_DIR / GUARDED_SPEC_NAME}")
    try:
        guarded_run_config(spec)
    except (GuardedSpecError, OSError) as exc:
        return _fail("guarded", str(exc))
    if membership is not None:
        actual = {group["name"]: list(group["modules"]) for group in spec["groups"]}
        if actual != membership:
            return _fail("guarded", f"guarded_groups.json {actual} differs from the policy's membership {membership}")
    return _pass("guarded", f"{len(spec['groups'])} groups, {len(guarded_modules())} modules")


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
    # v0.7.0: the hash lock beside requirements.txt is what setup installs on Windows; it must exist, record this
    # requirements.txt, contain every pin of it at the same version, and name one hashed artifact per package.
    if str(IMPORT_ROOT) not in sys.path:
        sys.path.insert(0, str(IMPORT_ROOT))
    try:
        from shared import base_packages
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        return _fail("deps", f"could not import the lock reader: {exc}")

    lock = base_packages.lock_path(REQUIREMENTS)
    if not lock.is_file():
        return _fail("deps", f"missing {lock.name} (regenerate it with files/dev-tools/lock_base_requirements.py)")
    problems = base_packages.lock_problems(REQUIREMENTS.read_text(encoding="utf-8"), lock.read_text(encoding="utf-8"),
                                           hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest())
    if problems:
        return _fail("deps", f"{lock.name}: " + "; ".join(problems[:5]))
    count = len(base_packages.parse_lock(lock.read_text(encoding="utf-8")).entries)
    return _pass("deps", f"all dependencies '=='-pinned; {lock.name} locks {count} packages by SHA-256")


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


def _static_gates():
    """The four gates after the suites. Looked up at call time so a test can stand one in for a synthetic one."""
    return [("deps", check_requirements), ("docs", check_docs), ("docnames", check_doc_names), ("config", check_config)]


# --------------------------------------------------------------------------- #
# The identity of what is being tested
# --------------------------------------------------------------------------- #
def _git(repo_root: Path, *args: str) -> str:
    # --no-optional-locks: fingerprinting must not even refresh the index.
    proc = subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=str(repo_root),
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8", "surrogateescape")


def _digest_class(relative: str) -> str:
    for name, prefixes in DIGEST_CLASSES:
        if any(relative == prefix or relative.startswith(prefix) for prefix in prefixes):
            return name
    return "other"


def tree_fingerprint(repo_root: Path | None = None) -> dict:
    """SHA-256 over the working-tree bytes of what the suite tests, as a whole and per class.

    The starting commit alone does not identify the tested tree when edits are uncommitted (plan §13.3), so this hashes
    what is on disk: every tracked file, plus untracked, non-ignored files in FINGERPRINT_UNTRACKED_SCOPES. A tracked file
    missing from the working tree is recorded as deleted, not skipped. Read-only: no index refresh, no objects written.
    outputs/ is excluded even if the ignore rules were damaged, since this run is writing there.
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
        try:
            branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        except subprocess.CalledProcessError:
            branch = None
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    digest = hashlib.sha256()
    classes = {name: hashlib.sha256() for name, _prefixes in DIGEST_CLASSES}
    classes["other"] = hashlib.sha256()
    deleted: list[str] = []
    for relative in sorted(tracked | untracked):
        if relative.startswith(_OUTPUTS_RELATIVE):
            continue
        try:
            content = runstore.sha256_file(repo_root / relative)
        except (FileNotFoundError, NotADirectoryError):
            content = "<deleted>"
            deleted.append(relative)
        line = relative.encode("utf-8", "surrogateescape") + b"\0" + content.encode("ascii") + b"\n"
        digest.update(line)
        classes[_digest_class(relative)].update(line)
    return {
        "available": True,
        "sha256": digest.hexdigest(),
        "head": head,
        "branch": branch,
        "tracked_files": len(tracked),
        "untracked_in_scope": sorted(untracked),
        "untracked_scopes": list(FINGERPRINT_UNTRACKED_SCOPES),
        "dirty_tracked": status,
        "deleted_tracked": deleted,
        "source_digest": classes["source"].hexdigest(),
        "test_digest": classes["tests"].hexdigest(),
        "policy_digest": classes["policy"].hexdigest(),
        "locks_digest": classes["locks"].hexdigest(),
        "docs_digest": classes["docs"].hexdigest(),
        "other_digest": classes["other"].hexdigest(),
    }


def _ffmpeg_identity() -> str | None:
    """The pinned FFmpeg's recorded hash, or None when this checkout has no proved pair."""
    try:
        state = json.loads((REPO_ROOT / "files" / "runtime-data" / "ffmpeg-state.json").read_text(encoding="utf-8"))
        return state["pair"]["ffmpeg"]["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _tk_identity() -> str | None:
    try:
        import tkinter

        return str(tkinter.Tcl().eval("info patchlevel"))
    except Exception:  # noqa: BLE001 - recorded as absent, never a reason for the gate to stop
        return None


def environment_identity() -> dict:
    mode = winproc.error_mode()
    try:
        pytest_version = importlib.metadata.version("pytest")
    except importlib.metadata.PackageNotFoundError:
        pytest_version = None
    return {
        "os_build": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "sys_platform": sys.platform,
        "tk": _tk_identity(),
        "pytest": pytest_version,
        "ffmpeg_sha256": _ffmpeg_identity(),
        "error_mode": None if mode is None else hex(mode),
        "interactive_desktop": winproc.interactive_desktop(),
    }


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #
def load_policy(path: Path | None = None) -> dict:
    path = POLICY_FILE if path is None else Path(path)
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"{path.name} is unusable: {type(exc).__name__}: {exc}") from None
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise PolicyError(f"{path.name}: unknown schema")
    for key in ("stages", "process", "scenarios", "inventory", "later_phase_requirements", "skip_policy", "focused",
                "changed", "required_self_tests"):
        if key not in policy:
            raise PolicyError(f"{path.name}: missing {key!r}")
    if set(policy["scenarios"]) != set(SCENARIO_NAMES):
        raise PolicyError(f"{path.name}: scenarios {sorted(policy['scenarios'])} are not the frozen {sorted(SCENARIO_NAMES)}")
    for rules in policy["skip_policy"].values():
        for rule in rules:
            try:
                re.compile(rule["pattern"])
            except (KeyError, re.error) as exc:
                raise PolicyError(f"{path.name}: bad skip rule {rule}: {exc}") from None
    return policy


def load_coverage(path: Path | None = None) -> dict:
    path = COVERAGE_FILE if path is None else Path(path)
    try:
        coverage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"{path.name} is unusable: {type(exc).__name__}: {exc}") from None
    ids = [feature.get("id") for feature in coverage.get("features", [])]
    if len(ids) != len(set(ids)) or not all(ids):
        raise PolicyError(f"{path.name}: feature ids must be present and unique")
    return coverage


def coverage_problems(coverage: dict) -> list[str]:
    """The seed's own honesty: every test module and source it names must exist. It proves nothing about coverage."""
    problems = []
    for feature in coverage.get("features", []):
        for selector in feature.get("selection", []):
            if not (REPO_ROOT / selector).is_file():
                problems.append(f"{feature['id']} selects {selector}, which does not exist")
        for source in feature.get("source", []):
            if not (REPO_ROOT / source["path"]).is_file():
                problems.append(f"{feature['id']} names source {source['path']}, which does not exist")
    return problems


# --------------------------------------------------------------------------- #
# One gate run
# --------------------------------------------------------------------------- #
def _pytest_command(junit_xml: Path, *, token: str, basetemp: Path, cache: Path, targets=None) -> list[str]:
    """The whole ordinary scope, or the given selectors, plus reporting and this run's own scratch. Nothing narrows it."""
    scope = [str(TESTS_DIR), *_ignore_arguments()] if targets is None else list(targets)
    return [sys.executable, "-u", "-m", "pytest", *scope, "-q", "-ra", f"--junitxml={junit_xml}",
            "-o", f"junit_suite_name={token}", f"--basetemp={basetemp}", "-o", f"cache_dir={cache}",
            "-o", f"faulthandler_timeout={FAULTHANDLER_SECONDS}"]


def _collect_command(*, token: str, basetemp: Path, cache: Path, targets=None) -> list[str]:
    scope = [str(TESTS_DIR), *_ignore_arguments()] if targets is None else list(targets)
    return [sys.executable, "-u", "-m", "pytest", *scope, "--collect-only", "-q",
            f"--basetemp={basetemp}", "-o", f"cache_dir={cache}", "-o", f"junit_suite_name={token}"]


def _dialog_probe_source(stub: Path) -> str:
    return ("import ctypes,json,subprocess,sys\n"
            "mode=ctypes.WinDLL('kernel32').GetErrorMode()\n"
            "if not mode&1:\n"
            "    print(json.dumps({'mode':hex(mode),'refused':True}));sys.exit(0)\n"
            "try:\n"
            f"    subprocess.run([{str(stub)!r}],capture_output=True,timeout=20)\n"
            "    print(json.dumps({'mode':hex(mode),'started':True}))\n"
            "except OSError as e:\n"
            "    print(json.dumps({'mode':hex(mode),'winerror':getattr(e,'winerror',None)}))\n")


@dataclass
class Selection:
    kind: str
    ordinary: list[str] | None = None  # None: the whole ordinary scope
    guarded: dict[str, list[str]] | None = None  # None: every group whole; {} no guarded group
    journeys: list[str] | None = None  # None: every registered journey; [] none
    requested: list[str] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def record(self) -> dict:
        return {"kind": self.kind, "ordinary": self.ordinary, "guarded": self.guarded, "journeys": self.journeys,
                "requested": self.requested, **self.notes}


class GateRun:
    """Everything one invocation does between reserving its directory and finalizing its result."""

    def __init__(self, args, argv: list[str], record: runstore.RunRecord, established: dict) -> None:
        self.args = args
        self.argv = argv
        self.record = record
        self.established = established
        self.directory = record.directory
        self.checks: list[dict] = []
        self.stages: list[dict] = []
        self.probes: dict[str, pytest_reports.Probe] = {}
        self.collected_ordinary: list[str] | None = None
        self.collected_guarded: dict[str, list[str]] = {}
        self.current_gate: str | None = None
        self.lifecycle = "created"
        self.policy: dict = {}
        self.coverage: dict | None = None
        self.identity_start: dict = {}
        self.environment: dict = {}
        self.started_at = runstore.now_utc()
        self.began = time.monotonic()
        self.temp_trees: list[tuple[Path, Path]] = []
        self.module_skips: set[str] = set()
        self.cleanup_violations: list[dict] = []
        self.guarded_work: tuple[Path, str] | None = None
        self.scratch_root: Path | None = None
        self.invocation_error: str | None = None
        self.scope = {"platform": sys.platform, "profile": args.mode, "full_acceptance": False}
        self.acceptance: acceptance_report.Judgement | None = None
        self.coverage_result: coverage_model.CoverageResult | None = None
        #: Qualification scenarios this run executed, and their verdicts.
        self.qualified: dict[str, str] = {}

    # ------------------------------------------------------------------ bookkeeping
    def enter(self, lifecycle: str) -> None:
        self.lifecycle = lifecycle
        self.record.log(f"lifecycle: {lifecycle}")
        self.mark()

    def mark(self) -> None:
        self.record.mark(self.lifecycle, reason="started; no normal completion has been recorded",
                         started_at=self.started_at, current_gate=self.current_gate)

    def check(self, name: str, status: str, detail: str = "", *, required: bool = True, **facts) -> dict:
        entry = {"name": name, "status": status, "required": required, "detail": detail, **facts}
        self.checks.append(entry)
        self.record.log(f"check {name}: {status} - {detail}")
        return entry

    def budget(self, stage: str) -> dict:
        return {**self.policy.get("process", {}), **self.policy.get("stages", {}).get(stage, {})}

    def supervise(self, stage: str, argv, *, log: Path, env: dict, progress=()) -> winproc.ChildResult:
        budget = self.budget(stage)

        def started(result: winproc.ChildResult) -> None:
            self.record.log(f"{log.stem} child started, pid {result.pid}, ownership {result.ownership}, "
                            f"error mode {result.error_mode_at_launch}")

        result = winproc.run_supervised(
            argv, log_path=log, cwd=REPO_ROOT, env=env, timeout=budget.get("timeout_seconds", 600),
            stall=budget.get("stall_seconds"), progress_paths=progress, drain=budget.get("drain_seconds", 15),
            kill_wait=budget.get("kill_wait_seconds", 20), on_start=started)
        self.record.log(f"{log.stem} child pid {result.pid} ended: {result.ended}, exit {result.returncode}, "
                        f"{result.seconds:.1f}s, remaining {result.remaining}, survivors {result.survivors}")
        return result

    def stage_env(self, temp: Path, *, probe: Path | None = None, token: str = "") -> dict:
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in _SCRUBBED_ENV and not key.upper().startswith(_SCRUBBED_ENV_PREFIXES)}
        env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
        if probe is not None:
            env.update(ACT_GATE_PROBE=str(probe), ACT_GATE_TOKEN=token)
        return env

    def scratch(self, name: str) -> Path:
        """A disposable folder of this run. Short on purpose: see SCRATCH_ROOT."""
        if self.scratch_root is None:
            self.scratch_root = runstore.reserve_scratch_dir(SCRATCH_ROOT, SCRATCH_ROOT.parent)
            scratch_store.write_owner(self.scratch_root, self.record.run_id, self.record.nonce)
            self.record.log(f"scratch: {self.scratch_root}")
        path = self.scratch_root / name
        path.mkdir()
        (path / "t").mkdir()
        return path

    def reports(self) -> Path:
        path = self.directory / "reports"
        path.mkdir(exist_ok=True)
        return path

    def relative(self, path: Path | None) -> str | None:
        return None if path is None else path.relative_to(self.directory).as_posix()

    # ------------------------------------------------------------------ the sequence
    def execute(self) -> None:
        """Everything before finalizing. A path that turns out to be unsafe stops the run as BLOCKED, with nothing touched."""
        try:
            self._sequence()
        except runstore.RunRefused as exc:
            self.check("safe-paths", "BLOCKED", str(exc))

    def _sequence(self) -> None:
        self.enter("preflight")
        self.write_start()
        try:
            self.policy = load_policy()
            self.coverage = load_coverage()
        except PolicyError as exc:
            self.invocation_error = str(exc)
            self.check("policy", "NOT RUN", str(exc))
            return
        self.check("policy", "PASS", f"{POLICY_FILE.name}, {COVERAGE_FILE.name} usable")
        if not self.preflight():
            return
        if self.args.preflight_only:
            self.check("execution", "NOT RUN", "--preflight-only: no test ran, so this establishes nothing")
            return
        if self.args.mode == "qualification":
            self.check_scenario()
            return
        try:
            selection = self.select()
        except InvocationError as exc:
            self.invocation_error = str(exc)
            self.check("selection", "NOT RUN", str(exc))
            return
        runstore.write_json_atomic(self.directory / "selection.json", selection.record())
        self.record.log(f"selection: {selection.kind}")
        if self.args.mode == "full" or self.args.collect_only:
            self.enter("collecting")
            if not self.collect(selection):
                return
        if self.args.collect_only:
            self.check("execution", "NOT RUN", "--collect-only: no test ran, so this establishes nothing")
            return
        self.enter("running")
        self.run_acceptance(selection)
        self.run_ordinary(selection)
        self.run_guarded(selection)
        if self.args.mode in ("full", "changed"):
            self.run_static()

    def write_start(self) -> None:
        self.identity_start = tree_fingerprint()
        self.environment = environment_identity()
        self.record.log(f"interpreter {sys.executable} ({sys.version.split()[0]})")
        self.record.log(f"tree fingerprint at start: {self.identity_start.get('sha256', self.identity_start.get('error'))}")
        self.record.write_start({
            "started_at": self.started_at, "mode": self.args.mode, "label": self.args.label, "argv": self.argv,
            "cwd": os.getcwd(), "repo_root": str(REPO_ROOT), "error_mode": self.established,
            "utc_offset": time.strftime("%z"), "environment": self.environment, "identity": self.identity_start,
        })

    def preflight(self) -> bool:
        wanted = self.args.platform
        actual = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
        if wanted and wanted != actual:
            self.check("platform", "BLOCKED", f"--platform {wanted} was asked for on {actual}")
            return False
        if not self.identity_start.get("available"):
            self.check("source-identity", "BLOCKED", f"fingerprint unavailable: {self.identity_start.get('error')}")
            return False
        self.check("source-identity", "PASS", f"HEAD {self.identity_start['head']}, tree {self.identity_start['sha256']}")
        _, spec_ok, detail = check_guarded_specification(self.policy["inventory"]["guarded_membership"])
        self.check("guarded-specification", "PASS" if spec_ok else "FAIL", detail)
        return self.preflight_children() and spec_ok

    def preflight_children(self) -> bool:
        """Prove on real children what the suite will depend on: the pin, the job, the inherited mode and no dialog."""
        scratch = self.scratch("p")
        log = self.directory / "logs" / "preflight-interpreter.log"
        env = self.stage_env(scratch / "t")
        try:
            result = self.supervise("preflight", [sys.executable, "-c", "import pytest;print('pytest',pytest.__version__)"],
                                    log=log, env=env)
        except winproc.JobUnavailable as exc:
            self.check("process-ownership", "BLOCKED", f"no owned process tree can be established: {exc}")
            return False
        output = log.read_text(encoding="utf-8", errors="replace")
        pin = _pinned_pytest()
        found = re.search(r"^pytest (\S+)\s*$", output, re.MULTILINE)
        if result.returncode != 0 or not found:
            self.check("interpreter", "BLOCKED", f"this interpreter cannot import pytest (exit {result.returncode}); "
                                                 "run the gate with the project environment's python")
            return False
        if pin is None or found.group(1) != pin:
            self.check("interpreter", "BLOCKED", f"pytest {found.group(1)} here; the requirements pin {pin}")
            return False
        self.check("interpreter", "PASS", f"pytest {pin} under {sys.executable}")
        if not result.clean:
            self.check("process-ownership", "FAIL", f"{result.ownership}; leftovers {result.remaining} {result.survivors}")
            return False
        self.check("process-ownership", "PASS", f"{result.ownership}; the child and its tree ended clean")
        if not winproc.IS_WINDOWS:
            self.check("error-mode", "NOT APPLICABLE", "not Windows", required=False)
            return True
        if not self.established.get("ok"):
            self.check("error-mode", "BLOCKED", f"the flags could not be set: {self.established}")
            return False
        stub = scratch / "invalid.exe"
        stub.write_text("sandbox binary", encoding="utf-8")
        log = self.directory / "logs" / "preflight-dialog-probe.log"
        result = self.supervise("preflight", [sys.executable, "-c", _dialog_probe_source(stub)], log=log, env=env)
        reading = next((line for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                        if line.startswith("{")), "{}")
        probe = json.loads(reading)
        expected = result.ended == "exited" and probe.get("winerror") == 216
        inherited = int(probe.get("mode", "0x0"), 16) & winproc.REQUIRED_ERROR_MODE == winproc.REQUIRED_ERROR_MODE
        if not (expected and inherited):
            self.check("error-mode", "BLOCKED", f"found {self.established['found']}, set {self.established['established']}; "
                                                f"a real child read {probe} and ended {result.ended}")
            return False
        self.check("error-mode", "PASS", f"found {self.established['found']}, set {self.established['established']}; a real "
                                         f"child inherited {probe['mode']} and starting an invalid executable failed at "
                                         "once with WinError 216, no dialog")
        return True

    def check_scenario(self) -> None:
        name = self.args.scenario
        scenario = self.policy["scenarios"][name]
        runner = scenario.get("runner")
        if not runner:
            self.check(f"scenario:{name}", "NOT RUN", f"not implemented yet; Phase {scenario['phase']} owns it: {scenario['detail']}")
            return
        script = GATE_DIR / runner
        if not script.is_file():
            self.check(f"scenario:{name}", "BLOCKED", f"its runner {runner} is not here")
            return
        # The scenario owns one folder of this run; its own runs, fixtures checks and verdict are evidence like any other.
        folder = self.directory / "qualification"
        scratch = self.scratch("q")
        log = self.directory / "logs" / f"qualification-{name}.log"
        self.enter("running")
        try:
            result = self.supervise("qualification", [sys.executable, "-u", str(script), "--out", str(folder)],
                                    log=log, env=self.stage_env(scratch / "t"), progress=(folder / "progress.log",))
        except winproc.JobUnavailable as exc:
            self.check("process-ownership", "BLOCKED", f"no owned process tree can be established: {exc}")
            return
        self.stages.append({"name": f"qualification:{name}", "ended": result.ended, "returncode": result.returncode,
                            "seconds": round(result.seconds, 1), "log": self.relative(log)})
        self.judge_cleanup(f"qualification:{name}", result)
        self.check("cleanup", "FAIL" if self.cleanup_violations else "PASS",
                   f"owned processes left behind: {self.cleanup_violations}" if self.cleanup_violations
                   else "no owned process remained after the scenario")
        verdict_file = folder / "verdict.json"
        try:
            verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.check(f"scenario:{name}", "FAIL", f"the scenario ended {result.ended} (exit {result.returncode}) without a "
                                                   f"readable verdict: {type(exc).__name__}: {exc}")
            return
        status = verdict.get("status") if verdict.get("status") in ("PASS", "FAIL", "BLOCKED") else "FAIL"
        if result.ended != "exited" or result.returncode != {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]:
            status = "FAIL" if status == "PASS" else status
        failing = [item["name"] for item in verdict.get("checks", []) if item.get("status") != "PASS"]
        self.qualified[name] = status
        self.check(f"scenario:{name}", status, f"{verdict.get('reason', '')}; {len(verdict.get('checks', []))} checks, "
                                               f"{verdict.get('runs', 0)} runs; failing {failing[:8]}; verdict "
                                               f"{self.relative(verdict_file)}")

    def select(self) -> Selection:
        mode = self.args.mode
        if mode == "full":
            self.scope["profile"] = "routine"
            return Selection("full")
        if mode == "focused":
            selectors = self._focused_selectors()
            journeys = self._focused_journeys()
            chosen = self._split(selectors, "focused")
            chosen.journeys = journeys
            return chosen
        return self._changed_selection()

    def _focused_journeys(self) -> list[str]:
        policy = self.policy.get("acceptance", {})
        known = [*policy.get("required_scenarios", []), *policy.get("optional_scenarios", [])]
        features = {feature["id"]: feature for feature in self.coverage.get("features", [])}
        wanted = list(self.args.journey or [])
        for feature_id in self.args.feature or []:
            wanted.extend(features[feature_id].get("journeys", []))
        unknown = sorted(set(wanted) - set(known))
        if unknown:
            raise InvocationError(f"unknown journey {unknown}; known: {sorted(known)}")
        return list(dict.fromkeys(wanted))

    def _focused_selectors(self) -> list[str]:
        features = {feature["id"]: feature for feature in self.coverage.get("features", [])}
        selectors = list(self.args.test or [])
        for feature_id in self.args.feature or []:
            if feature_id not in features:
                raise InvocationError(f"unknown feature {feature_id!r}; known: {sorted(features)}")
            selectors.extend(features[feature_id].get("selection", []))
            # The exact tests the feature is verified by, even where its selection does not name their module.
            selectors.extend(item["test"] for item in coverage_model.verifications_of(features[feature_id]) if item.get("kind") == "behavior")
        return [*self.policy["focused"]["required_guards"], *selectors]

    def _split(self, selectors: list[str], kind: str, **notes) -> Selection:
        membership = {module: group["name"] for group in load_guarded_spec()["groups"] for module in group["modules"]}
        ordinary, guarded = [], {}
        # A node of a module that is selected whole would only be collected a second time.
        whole = {selector for selector in selectors if "::" not in selector}
        selectors = [selector for selector in selectors if "::" not in selector or selector.split("::", 1)[0] not in whole]
        for selector in selection_rules.in_suite_order(selectors):
            module = selection_rules.module_name(selector)
            if module in membership:
                guarded.setdefault(membership[module], []).append(selector)
            else:
                ordinary.append(selector)
        return Selection(kind, ordinary=ordinary, guarded=guarded, requested=list(selectors), notes=notes)

    def _changed_selection(self) -> Selection:
        base = self.args.base
        try:
            merge_base = _git(REPO_ROOT, "merge-base", base, "HEAD").strip()
            changed = {p for p in _git(REPO_ROOT, "diff", "--name-only", "--no-renames", "-z", merge_base).split("\0") if p}
            changed |= {p for p in _git(REPO_ROOT, "ls-files", "-z", "--others", "--exclude-standard",
                                        "--", *FINGERPRINT_UNTRACKED_SCOPES).split("\0") if p}
        except (OSError, subprocess.CalledProcessError) as exc:
            raise InvocationError(f"--base {base!r} cannot be resolved against HEAD: {type(exc).__name__}") from None
        sources = {f"files/tests/{path.name}": path.read_text(encoding="utf-8", errors="replace")
                   for path in sorted(TESTS_DIR.glob("test_*.py"))}
        chosen = selection_rules.select_for_changes(changed, self.policy["changed"], sources)
        # The features whose source changed bring their own tests and journeys too: the reviewed mapping is a route, not only a word match.
        touched = [feature for feature in (self.coverage or {}).get("features", [])
                   if any(source.get("path") in changed for source in feature.get("source", []))]
        by_feature = sorted({*(selector for feature in touched for selector in feature.get("selection", [])),
                             *(item["test"] for feature in touched for item in coverage_model.verifications_of(feature)
                               if item.get("kind") == "behavior")})
        notes = {"base": base, "merge_base": merge_base, "changed_paths": sorted(changed), "ignored_paths": chosen.ignored,
                 "mapped": chosen.mapped, "widened_because": chosen.reasons, "features_touched": [feature["id"] for feature in touched]}
        self.scope["profile"] = "changed"
        if chosen.conservative_full:
            return Selection("changed-conservative-full", requested=sorted(changed), notes=notes)
        selected = self._split([*chosen.tests, *by_feature], "changed", **notes)
        acceptance = self.policy.get("acceptance", {})
        known = [*acceptance.get("required_scenarios", []), *acceptance.get("optional_scenarios", [])]
        journeys = selection_rules.journeys_for_changes(changed, acceptance.get("journey_routes", {}), known)
        journeys += [journey for feature in touched for journey in feature.get("journeys", []) if journey in known]
        selected.journeys = list(dict.fromkeys(journeys))
        return selected

    # ------------------------------------------------------------------ collection and partition
    def collect(self, selection: Selection) -> bool:
        """Know the inventory before spending an hour on it, and refuse a partition that does not hold."""
        (self.directory / "collection").mkdir()
        if selection.ordinary != []:
            scratch = self.scratch("co")
            token = f"{self.record.run_id}-collect-pytest"
            probe = self.reports() / "collect-pytest-probe.jsonl"
            log = self.directory / "logs" / "collect-pytest.log"
            command = _collect_command(token=token, basetemp=scratch / "b", cache=scratch / "c", targets=selection.ordinary)
            result = self.supervise("collect", command, log=log, env=self.stage_env(scratch / "t", probe=probe, token=token),
                                    progress=(probe,))
            parsed = pytest_reports.read_probe(probe, token)
            self.stages.append({"name": "collect-pytest", "log": self.relative(log), "probe": self.relative(probe), **result.record()})
            if result.returncode != 0 or not parsed.valid or parsed.collected is None or parsed.collect_errors:
                self.check("collection", "FAIL" if result.returncode not in (0, 5) or parsed.collect_errors else "NOT RUN",
                           f"ordinary collection: exit {result.returncode}, {len(parsed.collect_errors)} error(s), "
                           f"record {parsed.problem or 'ok'}")
                return False
            self.collected_ordinary = parsed.collected
            self._write_inventory("pytest", parsed.collected, parsed.collect_skips)
            self.judge_cleanup("collect-pytest", result)
        groups = self.guarded_groups(selection)
        for index, (group, targets) in enumerate(groups):
            collected = self.collect_group(group, targets, index)
            if collected is None:
                return False
            self.collected_guarded[group["name"]] = collected
        if selection.ordinary is not None or selection.guarded is not None:
            self.check("collection", "PASS", "selected scope collected")
            return True
        return self.check_partition()

    def _write_inventory(self, name: str, nodes: list[str], skips: list[dict]) -> None:
        with open(self.directory / "collection" / f"{name}.txt", "x", encoding="utf-8", newline="\n") as sink:
            sink.write("".join(f"{node}\n" for node in nodes))
        self.module_skips.update(row["id"] for row in skips if row["id"].endswith(".py"))

    def collect_group(self, group: dict, targets: list[str], index: int) -> list[str] | None:
        name, prefix = group["name"], group["basetemp_prefix"]
        work, stamp = self.guarded_work_dir()
        config = work / "config.json"
        if not config.exists():
            config.write_text(json.dumps(guarded_run_config(load_guarded_spec()), indent=1), encoding="utf-8")
        report = work / f"c-{name}.json"
        probe = work / f"c-{name}-probe.jsonl"
        token = f"{self.record.run_id}-collect-{name}"
        basetemp = self.guarded_root() / f"{prefix}c{stamp}{index}"
        log = self.directory / "logs" / f"collect-guarded-{name}.log"
        env = self.stage_env(self.scratch(f"cg{index}") / "t", probe=probe, token=token)
        result = self.supervise("collect", _guarded_command(config, report, basetemp, targets, extra=("--collect-only",)),
                                log=log, env=env, progress=(probe,))
        parsed = pytest_reports.read_probe(probe, token)
        stored = self.keep_report(probe, f"collect-guarded-{name}-probe.jsonl")
        stored_report = self.keep_report(report, f"collect-guarded-{name}.json")
        self.stages.append({"name": f"collect-guarded-{name}", "log": self.relative(log), "probe": self.relative(stored),
                            "report": self.relative(stored_report), **result.record()})
        ok, detail = _judge_group(name, result.returncode, _read_guard_report(report), require_tests=False)
        if not ok or not parsed.valid or parsed.collected is None or parsed.collect_errors:
            self.check("collection", "FAIL", f"guarded collection: {detail}; record {parsed.problem or 'ok'}; "
                                             f"{len(parsed.collect_errors)} error(s)")
            return None
        self.remember_temp(basetemp)
        self._write_inventory(f"guarded-{name}", parsed.collected, parsed.collect_skips)
        return parsed.collected

    def check_partition(self) -> bool:
        inventory = self.policy["inventory"]
        prefix = TESTS_DIR.relative_to(REPO_ROOT).as_posix()
        disk = {f"{prefix}/{path.name}" for path in TESTS_DIR.glob("test_*.py")}
        problems = pytest_reports.partition_problems(
            self.collected_ordinary or [], self.collected_guarded, inventory["guarded_membership"], disk, prefix,
            self.module_skips, set(inventory.get("modules_without_tests", {})))
        ordinary_count = len(self.collected_ordinary or [])
        if ordinary_count < inventory["minimum_ordinary"]:
            problems.append(f"{ordinary_count} ordinary tests collected, fewer than the required {inventory['minimum_ordinary']}")
        for group, floor in inventory["minimum_guarded"].items():
            if len(self.collected_guarded.get(group, [])) < floor:
                problems.append(f"{len(self.collected_guarded.get(group, []))} tests in {group}, fewer than the required {floor}")
        facts = {"ordinary": ordinary_count, "guarded": {g: len(n) for g, n in self.collected_guarded.items()},
                 "modules_on_disk": len(disk), "module_level_skips": sorted(self.module_skips)}
        runstore.write_json_atomic(self.directory / "collection" / "partition.json", {"problems": problems, **facts})
        if problems:
            self.check("partition", "FAIL", "; ".join(problems[:6]), **facts)
            return False
        self.check("partition", "PASS", f"{ordinary_count} ordinary + {sum(facts['guarded'].values())} guarded, disjoint, "
                                        f"covering all {len(disk)} test modules on disk", **facts)
        return True

    # ------------------------------------------------------------------ the suites
    def run_ordinary(self, selection: Selection) -> None:
        self.current_gate = "pytest"
        self.mark()
        if selection.ordinary == []:
            self.check("pytest", "NOT APPLICABLE", "the selection holds no ordinary test", required=False)
            return
        scratch = self.scratch("o")
        token = f"{self.record.run_id}-pytest"
        junit = self.reports() / "pytest.xml"
        probe = self.reports() / "pytest-probe.jsonl"
        log = self.directory / "logs" / "pytest.log"
        command = _pytest_command(junit, token=token, basetemp=scratch / "b", cache=scratch / "c",
                                  targets=selection.ordinary)
        self.record.log(f"pytest command: {command}")
        result = self.supervise("pytest", command, log=log, env=self.stage_env(scratch / "t", probe=probe, token=token),
                                progress=(probe,))
        report = pytest_reports.read_junit(junit, token)
        parsed = pytest_reports.read_probe(probe, token)
        verdict = pytest_reports.judge_stage(result.returncode, result.ended, report, parsed, _tail(log), child_pid=result.pid)
        self.probes["pytest"] = parsed
        self.stages.append({"name": "pytest", "log": self.relative(log), "junit": self.relative(junit) if junit.is_file() else None,
                            "probe": self.relative(probe) if probe.is_file() else None,
                            "junit_summary": pytest_reports.junit_summary(report), "counts": parsed.counts, **result.record()})
        self.judge_cleanup("pytest", result)
        self.check("pytest", verdict.status, verdict.detail, exit_status=result.returncode, seconds=round(result.seconds, 3))

    def run_acceptance(self, selection: Selection) -> None:
        """Real input, real media, judged from outside the process that ran them. Never skipped quietly: nothing selected says so."""
        self.current_gate = "acceptance"
        self.mark()
        policy = self.policy.get("acceptance", {})
        required, optional = list(policy.get("required_scenarios", [])), list(policy.get("optional_scenarios", []))
        wanted = [*required, *optional] if selection.journeys is None else list(selection.journeys)
        if not wanted:
            self.check("acceptance", "NOT APPLICABLE", "the selection holds no native or media journey", required=False)
            return
        scratch = self.scratch("a")
        token = f"{self.record.run_id}-acceptance"
        report = self.reports() / "acceptance.json"
        evidence = self.directory / "acceptance"
        log = self.directory / "logs" / "acceptance.log"
        argv = [sys.executable, "-I", "-B", "-u", str(ACCEPTANCE_RUNNER), "--report", str(report), "--token", token,
                "--evidence", str(evidence), "--scratch", str(scratch / "w")]
        for scenario_id in wanted:
            argv += ["--only", scenario_id]
        env = self.stage_env(scratch / "t")
        result = self.supervise("acceptance", argv, log=log, env=env, progress=(report,))
        self.judge_cleanup("acceptance", result)
        self.acceptance = acceptance_report.judge(
            report, token=token, wanted=wanted, required=required, optional=optional, evidence_root=evidence, returncode=result.returncode,
            ended=result.ended, required_tools=list(policy.get("required_tools", [])), whole_set=selection.journeys is None)
        self.stages.append({"name": "acceptance", "log": self.relative(log), "report": self.relative(report) if report.is_file() else None,
                            "scenarios": self.acceptance.scenarios, **result.record()})
        (self.directory / "acceptance-report.md").write_text("\n".join(acceptance_report.report_lines(self.acceptance)) + "\n",
                                                              encoding="utf-8", newline="\n")
        self.check("acceptance", self.acceptance.status, self.acceptance.detail, exit_status=result.returncode, seconds=round(result.seconds, 3))
        self.check_visual_candidates()

    def check_visual_candidates(self) -> None:
        """Pictures are candidates until the owner approves them. A normal run lists them for review and never writes the approved list."""
        candidates = self.acceptance.candidates if self.acceptance else []
        approved = load_approved_baselines()
        lines = ["# Visual candidates for owner review", "",
                 "Nothing here is approved by this run. Approving one takes an owner-signed entry in baselines/approved.json.", "",
                 "| Scenario | Picture | Client size | DPI |", "|---|---|---|---|"]
        lines += [f"| `{item['scenario']}` | {item.get('path')} | {item.get('client')} | {item.get('dpi')} |" for item in candidates]
        (self.directory / "visual-candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        problems = baseline_problems(approved)
        if problems:
            self.check("visual-baselines", "FAIL", "; ".join(problems[:5]))
            return
        self.check("visual-baselines", "NOT RUN", f"{len(approved)} approved, {len(candidates)} candidates listed in visual-candidates.md for "
                                                  "the owner's review; no picture was compared or approved by this run", required=False)

    def guarded_root(self) -> Path:
        return REPO_ROOT / GUARDED_SUBDIR

    def guarded_work_dir(self) -> tuple[Path, str]:
        """This run's folder below the qualification root, created once. Short names on purpose: the spaCy consumer suite
        refuses a fixture path near Windows' 248-character cwd bound, and pinned production checks read these prefixes."""
        if self.guarded_work is None:
            stamp = time.strftime("%y%m%d%H%M%S", time.gmtime()) + self.record.run_id.rsplit("_", 1)[-1]
            root = self.guarded_root()
            runstore.refuse_links(root, REPO_ROOT)
            root.mkdir(parents=True, exist_ok=True)
            work = root / f"verify-{stamp}"
            work.mkdir()  # exclusive: nothing that exists is reused
            self.guarded_work = (work, stamp)
            self.remember_temp(work)
        return self.guarded_work

    def remember_temp(self, path: Path) -> None:
        self.temp_trees.append((path, self.guarded_root()))

    def keep_report(self, source: Path, name: str) -> Path | None:
        """Copy a guarded artefact out of the qualification tree, where the guard let it be written, into this run."""
        if not source.is_file():
            return None
        target = self.reports() / name
        shutil.copyfile(source, target)
        return target

    def guarded_groups(self, selection: Selection) -> list[tuple[dict, list[str]]]:
        groups = []
        for group in load_guarded_spec()["groups"]:
            if selection.guarded is None:
                groups.append((group, list(group["modules"])))
            elif group["name"] in selection.guarded:
                targets = [item.split("/", 2)[-1] for item in selection.guarded[group["name"]]]
                groups.append((group, targets))
        return groups

    def run_guarded(self, selection: Selection) -> None:
        self.current_gate = "guarded"
        self.mark()
        groups = self.guarded_groups(selection)
        if not groups:
            self.check("guarded", "NOT APPLICABLE", "the selection holds no guarded test", required=False)
            return
        statuses, details = [], []
        for index, (group, targets) in enumerate(groups):
            status, detail = self.run_group(group, targets, index)
            statuses.append(status)
            details.append(detail)
        self.check("guarded", _worst(statuses), "; ".join(details))

    def run_group(self, group: dict, targets: list[str], index: int) -> tuple[str, str]:
        name, prefix = group["name"], group["basetemp_prefix"]
        try:
            work, stamp = self.guarded_work_dir()
            config = work / "config.json"
            if not config.exists():
                config.write_text(json.dumps(guarded_run_config(load_guarded_spec()), indent=1), encoding="utf-8")
        except (GuardedSpecError, OSError, runstore.RunRefused) as exc:
            return "FAIL", f"{name}: {exc}"
        report = work / f"{name}.json"
        probe = work / f"{name}-probe.jsonl"
        junit = work / f"{name}.xml"
        token = f"{self.record.run_id}-guarded-{name}"
        basetemp = self.guarded_root() / f"{prefix}v{stamp}{index}"
        log = self.directory / "logs" / f"guarded-{name}.log"
        command = _guarded_command(config, report, basetemp, targets,
                                   extra=(f"--junitxml={junit}", "-o", f"junit_suite_name={token}"))
        env = self.stage_env(self.scratch(f"g{index}") / "t", probe=probe, token=token)
        result = self.supervise("guarded", command, log=log, env=env, progress=(probe,))
        guard = _read_guard_report(report)
        parsed = pytest_reports.read_probe(probe, token)
        junit_report = pytest_reports.read_junit(junit, token)
        ok, detail = _judge_group(name, result.returncode, guard)
        problems = _guard_identity_problems(guard, config)
        if problems:
            ok, detail = False, f"{name}: the guard report does not belong to this run: {'; '.join(problems)}"
        verdict = pytest_reports.judge_stage(result.returncode, result.ended, junit_report, parsed, _tail(log),
                                             child_pid=result.pid)
        stored = {key: self.keep_report(source, target) for key, source, target in (
            ("report", report, f"guarded-{name}.json"), ("probe", probe, f"guarded-{name}-probe.jsonl"),
            ("junit", junit, f"guarded-{name}.xml"))}
        self.probes[f"guarded-{name}"] = parsed
        self.stages.append({"name": f"guarded-{name}", "log": self.relative(log),
                            **{key: self.relative(path) for key, path in stored.items()},
                            "junit_summary": pytest_reports.junit_summary(junit_report), "counts": parsed.counts,
                            "guard": {key: guard.get(key) for key in ("pytest_exit", "outer_exit", "counts", "error_mode")},
                            **result.record()})
        self.judge_cleanup(f"guarded-{name}", result)
        status = "FAIL" if not ok else verdict.status
        if status != "PASS":
            return status, detail if not ok else f"{name}: {verdict.detail}"
        self.remember_temp(basetemp)
        return "PASS", detail

    def run_static(self) -> None:
        for name, gate in _static_gates():
            self.current_gate = name
            self.mark()
            began = time.monotonic()
            _, ok, detail = gate()
            self.check(name, "PASS" if ok else "FAIL", detail, exit_status=None, seconds=round(time.monotonic() - began, 3))
        self.current_gate = None

    def judge_cleanup(self, stage: str, result: winproc.ChildResult) -> None:
        if result.remaining or result.survivors:
            self.cleanup_violations.append({"stage": stage, "remaining": result.remaining, "survivors": result.survivors})

    # ------------------------------------------------------------------ finalizing
    def finalize(self) -> dict:
        self.enter("finalizing")
        cleanup = self.cleanup_violations
        ran_tests = any(s.get("counts", {}).get("executed") for s in self.stages)
        if self.lifecycle_reached_tests():
            self.check("cleanup", "FAIL" if cleanup else "PASS",
                       f"owned processes left behind: {cleanup}" if cleanup else "no owned process remained after any stage")
        if ran_tests:
            self.check_error_mode()
            self.check_skips()
            self.check_inventory_executed()
        if self.lifecycle_reached_tests():
            self.check_coverage()
        if self.args.mode == "full" and self.lifecycle_reached_tests():
            self.check_self_tests()
            self.check_later_requirements()
        identity_end = tree_fingerprint() if self.identity_start else {}
        match = self.check_tree(identity_end)
        status, exit_code = self.outcome()
        temp_problems = self.remove_temp(status)
        counts = self.counts()
        results = {
            "schema_version": runstore.SCHEMA_VERSION, "run_id": self.record.run_id, "nonce": self.record.nonce,
            "mode": self.args.mode, "label": self.args.label, "lifecycle": "completed", "status": status,
            "exit_code": exit_code, "scope": self.scope,
            "identity": {"head": self.identity_start.get("head"), "branch": self.identity_start.get("branch"),
                         "source_digest": self.identity_start.get("source_digest"),
                         "test_digest": self.identity_start.get("test_digest"),
                         "policy_digest": self.identity_start.get("policy_digest"),
                         "locks_digest": self.identity_start.get("locks_digest"),
                         "docs_digest": self.identity_start.get("docs_digest"),
                         "tree_digest": self.identity_start.get("sha256"), "start_end_match": match,
                         "start": self.identity_start, "end": identity_end},
            "environment": self.environment, "counts": counts, "checks": self.checks, "stages": self.stages,
            "coverage": {**(self.coverage_result.record() if self.coverage_result else {"inventory_reviewed": False}),
                         "exceptions": [item for feature in (self.coverage or {}).get("features", []) for item in feature.get("exceptions", [])]},
            "qualification": {"required": [], "satisfied": sorted(n for n, s in self.qualified.items() if s == "PASS"),
                              "pending": [n for n in SCENARIO_NAMES if self.qualified.get(n) != "PASS"],
                              "ran": dict(self.qualified)},
            "pending_requirements": self.policy.get("later_phase_requirements", []),
            "release_ready": False,
            "cleanup": {"owned_children_remaining": sum(len(c["remaining"]) + len(c["survivors"]) for c in cleanup),
                        "violations": cleanup, "temp_not_removed": temp_problems,
                        "scratch": None if self.scratch_root is None or not self.scratch_root.exists()
                        else str(self.scratch_root)},
            "started_at": self.started_at, "finished_at": runstore.now_utc(),
            "elapsed_seconds": round(time.monotonic() - self.began, 3),
            "invocation_error": self.invocation_error,
        }
        self.write_summary(results)
        # The log is an artifact like any other, so it is finished before the manifest hashes it.
        self.record.log("\n".join(_report_lines(results, self.directory)))
        self.record.log(f"complete: RESULT {status}")
        self.record.close()
        return self.record.finalize(results)

    def lifecycle_reached_tests(self) -> bool:
        return any(c["name"] in ("acceptance", "pytest", "guarded") for c in self.checks)

    def check_error_mode(self) -> None:
        if not winproc.IS_WINDOWS:
            return
        problems, drifts = [], []
        for stage, probe in self.probes.items():
            if not probe.session:
                continue
            problems += [f"{stage}: {text}" for text in pytest_reports.error_mode_findings(
                probe, winproc.REQUIRED_ERROR_MODE, winproc.SEM_FAILCRITICALERRORS)]
            drifts += [{"stage": stage, **drift} for drift in probe.drifts]
        detail = "; ".join(problems) if problems else (
            f"every session started with the flags set; {len(drifts)} drift(s) of a non-critical flag repaired at a test "
            f"boundary" + (f", first {drifts[0]['found']} at {drifts[0]['where']}" if drifts else ""))
        self.check("error-mode-held", "FAIL" if problems else "PASS", detail, drifts=drifts[:50])

    def check_skips(self) -> None:
        policy = self.policy.get("skip_policy", {}).get(sys.platform)
        skips = [skip for probe in self.probes.values() for skip in probe.skips]
        xfails = [item for probe in self.probes.values() for item in probe.xfails]
        problems, tally = pytest_reports.skip_policy_problems(skips, xfails, policy)
        if policy is None and not problems:
            self.check("skips", "NOT APPLICABLE", f"no skip policy for {sys.platform}: {len(skips)} skip(s) recorded, not "
                                                  "judged", required=False, tally=tally)
            return
        self.check("skips", "FAIL" if problems else "PASS",
                   "; ".join(problems[:8]) if problems else f"{len(skips)} skip(s), each with a reason the policy names",
                   tally=tally)

    def check_inventory_executed(self) -> None:
        """Every test collected before the run actually ran, in the suite it belongs to."""
        problems = []
        if self.collected_ordinary is not None and "pytest" in self.probes:
            executed = self.probes["pytest"].executed()
            if executed != set(self.collected_ordinary):
                problems.append("ordinary: " + pytest_reports._difference(self.collected_ordinary, executed))
        for group, nodes in self.collected_guarded.items():
            probe = self.probes.get(f"guarded-{group}")
            if probe is not None and probe.executed() != set(nodes):
                problems.append(f"{group}: " + pytest_reports._difference(nodes, probe.executed()))
        if self.collected_ordinary is None and not self.collected_guarded:
            return
        self.check("inventory", "FAIL" if problems else "PASS",
                   "; ".join(problems) if problems else "selected, collected and executed tests are the same set")

    def check_self_tests(self) -> None:
        executed = {pytest_reports.module_of(node) for probe in self.probes.values() for node in probe.executed()}
        missing = [name for name in self.policy.get("required_self_tests", []) if name not in executed]
        self.check("self-tests", "FAIL" if missing else "PASS",
                   f"not executed: {missing}" if missing else "the gate's own negative controls executed in this run")

    def check_coverage(self) -> None:
        """The inventory held to account, in two checks kept apart.

        ``coverage-inventory`` is the inventory itself: reviewed, every discovered surface mapped, every application source file reviewed
        as it is now and named by a feature, no dangling id, test, scenario, symbol or document. A full run also holds every test id to
        this run's exact collection. It is required in full and changed runs when the policy requires a reviewed inventory, so a source
        change cannot pass without its mapping being looked at again.

        ``coverage`` is what this run satisfied. Only a full run can be held to every required routine verification; a narrower run
        reports its own satisfaction and says so. Release-pending evidence (qualification, owner, planned) is reported, never satisfied.
        """
        full = self.args.mode == "full"
        policy = self.policy.get("acceptance", {})
        coverage = self.coverage or {}
        reviewed_required = bool(self.policy.get("coverage", {}).get("require_reviewed_inventory"))
        collected = None
        if full and self.collected_ordinary is not None:
            collected = set(self.collected_ordinary) | {node for nodes in self.collected_guarded.values() for node in nodes}
        passed = {node for probe in self.probes.values() for node, outcome in probe.outcomes.items()
                  if outcome.get("call") == "passed" and "failed" not in outcome.values()}
        passed_scenarios = {item["id"] for item in self.acceptance.scenarios if item["verdict"] == "PASS"} if self.acceptance else set()
        if coverage.get("schema_version", 1) >= 2:
            scenarios = inventory_tools.scenario_registry(self.policy)
            problems = inventory_tools.problems(coverage, self.policy, repo_root=REPO_ROOT, collected=collected, scenarios=scenarios)
        else:
            scenarios = {scenario_id: {"layers": _layers_of(scenario_id, self.acceptance) or None}
                         for scenario_id in [*policy.get("required_scenarios", []), *policy.get("optional_scenarios", [])]}
            problems = coverage_model.problems_in_inventory(
                coverage, scenarios=scenarios, collected=collected, disk_check=lambda relative: (REPO_ROOT / relative).is_file(),
                required_tools=list(policy.get("required_tools", [])))
            if reviewed_required:
                problems.append(f"schema {coverage.get('schema_version', 1)}: a reviewed inventory is schema 2 or later")
        self.coverage_result = coverage_model.evaluate(
            coverage, scenarios=scenarios, passed_tests=passed, passed_scenarios=passed_scenarios, collected=collected,
            required_tools=list(policy.get("required_tools", [])), qualification_scenarios=SCENARIO_NAMES)
        result = self.coverage_result
        result.problems = problems
        (self.directory / "coverage-report.md").write_text("\n".join(coverage_model.report_lines(result)) + "\n", encoding="utf-8", newline="\n")
        if reviewed_required:
            self.check("coverage-inventory", "FAIL" if problems else "PASS",
                       "; ".join(problems[:8]) + (f" (and {len(problems) - 8} more in coverage-report.md)" if len(problems) > 8 else "")
                       if problems else f"reviewed; {result.inventoried} features, {result.surfaces.get('static', 0)} static and "
                                        f"{result.surfaces.get('live', 0)} live surfaces indexed, every application source file reviewed "
                                        "as it is now; the live index is judged by inventory.live-surfaces",
                       required=self.args.mode in ("full", "changed"))
        else:
            self.check("coverage-inventory", "NOT APPLICABLE", "this policy does not require a reviewed inventory", required=False)
        if not full:
            self.check("coverage", "NOT APPLICABLE", f"this {self.args.mode} run satisfied {result.satisfied_required} of {result.required} required "
                                                     "entries; only a full run judges satisfaction", required=False)
            return
        # A blocked journey is reported as blocked by its own check, and what it would have satisfied stays visible in the report. Only a
        # run whose acceptance stage passed can be held to having satisfied everything.
        unsatisfied = result.unsatisfied if self.acceptance is not None and self.acceptance.status == "PASS" else []
        failing = [*([] if reviewed_required else problems), *(f"required but not satisfied in this full run: {item}" for item in unsatisfied[:20])]
        pending = ", ".join(f"{kind} {len(items)}" for kind, items in sorted(result.release_pending.items())) or "none"
        self.check("coverage", "FAIL" if failing else "PASS", "; ".join(failing[:8]) if failing else
                   f"{result.mapped_required} of {result.required} required entries mapped and {result.satisfied_required} satisfied here; "
                   f"{len(result.unmapped_required)} with no routine evidence; release-pending: {pending}")

    def check_later_requirements(self) -> None:
        for item in self.policy.get("later_phase_requirements", []):
            self.check(f"requirement:{item['id']}", "NOT RUN", f"Phase {item['phase']} owns it: {item['detail']}",
                       required=bool(item.get("required")))

    def check_tree(self, end: dict) -> bool:
        start = self.identity_start
        if not start.get("available"):
            return False  # already reported as BLOCKED: nothing was compared, so nothing can match
        same = bool(start.get("available") and end.get("available") and start.get("sha256") == end.get("sha256")
                    and start.get("head") == end.get("head"))
        if same:
            detail = f"unchanged during the run ({end['sha256']})"
        elif not (start.get("available") and end.get("available")):
            detail = "fingerprint unavailable: " + "; ".join(
                item["error"] for item in (start, end) if not item.get("available"))
        else:
            moved = [key for key in (*runstore.EXECUTION_DIGESTS, "docs_digest", "head") if start.get(key) != end.get(key)]
            detail = f"changed during the run ({start['sha256']} -> {end['sha256']}, {moved}); the tested inputs were not frozen"
        self.check("tree", "PASS" if same else "FAIL", detail)
        return same

    def outcome(self) -> tuple[str, int]:
        if self.invocation_error:
            return "NOT RUN", runstore.EXIT_INVALID
        status = _worst(c["status"] for c in self.checks if c.get("required", True))
        counts = self.counts()
        if status == "PASS" and self.args.mode != "qualification" and not (counts["executed"] or counts["journeys_passed"]):
            status = "NOT RUN"
        return status, runstore.EXIT_FOR_STATUS[status]

    def counts(self) -> dict:
        totals = {"expected": len(self.collected_ordinary or []) + sum(len(n) for n in self.collected_guarded.values()),
                  "collected": 0, "executed": 0, "passed": 0, "failed": 0, "errors": 0, "blocked": 0, "skipped": 0,
                  "xfailed": 0, "xpassed": 0, "deselected": 0}
        for probe in self.probes.values():
            for key, value in probe.counts.items():
                totals[key] = totals.get(key, 0) + value
        # Kept apart from the test counts, which an independent recount of the JUnit must be able to reproduce.
        scenarios = self.acceptance.scenarios if self.acceptance else []
        totals["journeys_selected"] = len(scenarios)
        totals["journeys_passed"] = sum(1 for item in scenarios if item["verdict"] == "PASS")
        return totals

    def remove_temp(self, status: str) -> list[str]:
        """Disposable scratch goes on PASS. After a failure it stays, as evidence, and results.json names where it is."""
        problems: list[str] = []
        if status != "PASS":
            self.preserve_failure_diagnostics()
        if status == "PASS":
            for path, within in self.temp_trees:
                try:
                    problems += runstore.safe_remove_tree(path, within=within)
                except runstore.RunRefused as exc:
                    problems.append(str(exc))
            if self.scratch_root is not None:
                try:
                    problems += runstore.safe_remove_tree(self.scratch_root, within=SCRATCH_ROOT)
                    SCRATCH_ROOT.rmdir()  # only if no other run is using it
                except runstore.RunRefused as exc:
                    problems.append(str(exc))
                except OSError:
                    pass
        if problems:
            self.record.log(f"scratch not removed: {problems}")
        return problems

    def preserve_failure_diagnostics(self) -> None:
        """A failing test's temp folder goes into this run's evidence, within limits, before anything can clean its scratch."""
        if self.scratch_root is None:
            return
        preserved = {}
        for stage, probe in self.probes.items():
            failing = [node for node, outcome in probe.outcomes.items() if "failed" in outcome.values()]
            basetemp = self.scratch_root / "o" / "b" if stage == "pytest" else None
            if not failing or basetemp is None:
                continue
            preserved[stage] = scratch_store.preserve_failed(basetemp, failing, self.directory / "failed-scratch" / stage)
        if preserved:
            runstore.write_json_atomic(self.directory / "failed-scratch.json", preserved)
            self.record.log(f"failed tests' temp folders copied into this run: "
                            f"{ {stage: len(entry['copied']) for stage, entry in preserved.items()} }")

    def write_summary(self, results: dict) -> None:
        identity = results["identity"]
        lines = [f"# {results['run_id']}", "", f"**{results['status']}** (exit {results['exit_code']}), mode "
                 f"`{results['mode']}`, {results['elapsed_seconds']:.0f} s", "",
                 f"- HEAD `{identity['head']}`, branch `{identity['branch']}`",
                 f"- Tree `{identity['tree_digest']}`, unchanged during the run: {identity['start_end_match']}",
                 f"- Counts: {results['counts']}", f"- Full acceptance: {results['scope']['full_acceptance']}; "
                 f"release ready: {results['release_ready']}", "", "| Check | Status | Detail |", "|---|---|---|"]
        for check in results["checks"]:
            detail = str(check["detail"]).replace("|", "/").replace("\n", " ")
            lines.append(f"| {check['name']}{'' if check.get('required', True) else ' (not required)'} | {check['status']} "
                         f"| {detail[:600]} |")
        (self.directory / runstore.SUMMARY_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        failures = [check for check in results["checks"] if check.get("required", True)
                    and check["status"] in ("FAIL", "BLOCKED", "NOT RUN")]
        if failures:
            text = "\n\n".join(f"## {c['name']}: {c['status']}\n\n{c['detail']}" for c in failures)
            (self.directory / "failures.md").write_text(f"# What kept this run from PASS\n\n{text}\n", encoding="utf-8",
                                                        newline="\n")


def _layers_of(scenario_id: str, judgement: acceptance_report.Judgement | None) -> list[str]:
    if judgement is None:
        return []
    return next((item.get("layers", []) for item in judgement.scenarios if item["id"] == scenario_id), [])


def load_approved_baselines(path: Path | None = None) -> list[dict]:
    path = BASELINES_FILE if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(data.get("approved", [])) if isinstance(data, dict) else []


def baseline_problems(approved: list[dict]) -> list[str]:
    """An approved baseline carries the owner's word and what it describes. An agent cannot approve one, and a run never writes one."""
    problems = []
    for entry in approved:
        if str(entry.get("approved_by", "")).strip().lower() != "owner":
            problems.append(f"baseline {entry.get('name')!r} is not approved by the owner")
        missing = [key for key in ("name", "sha256", "os", "tk", "dpi", "client") if not entry.get(key)]
        if missing:
            problems.append(f"baseline {entry.get('name')!r} does not record {missing}")
    return problems


_SEVERITY = ("FAIL", "BLOCKED", "NOT RUN", "PASS", "NOT APPLICABLE")


def _worst(statuses) -> str:
    """FAIL outranks BLOCKED outranks NOT RUN (plan §6.1). Nothing to judge is NOT RUN, never PASS."""
    seen = set(statuses)
    for status in _SEVERITY[:4]:
        if status in seen:
            return status
    return "NOT RUN"


def _tail(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - SUMMARY_BYTES))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _guard_identity_problems(report: dict, config: Path) -> list[str]:
    """The report must have been written by this tree's runner over this run's configuration."""
    if "unreadable" in report:
        return []  # already a failure, reported as such
    problems = []
    if report.get("runner_sha256") != _sha256_of(TESTS_DIR / "guarded_pytest.py"):
        problems.append("runner hash differs")
    if report.get("config_sha256") != _sha256_of(config):
        problems.append("configuration hash differs")
    return problems


def _pinned_pytest() -> str | None:
    try:
        text = REQUIREMENTS.read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"^pytest==(\S+)", text, re.MULTILINE)
    return found.group(1) if found else None


def _report_lines(results: dict, directory: Path) -> list[str]:
    tags = {"NOT RUN": "NOT RUN", "NOT APPLICABLE": "N/A"}
    lines = ["=" * 60, "verify.py — Audiobook Creation Tool gate", "=" * 60, f"  mode: {results['mode']}"]
    for check in results["checks"]:
        line = f"  [{tags.get(check['status'], check['status'])}] {check['name']:<8}"
        if check["detail"]:
            line += f" - {str(check['detail'])[:400]}"
        lines.append(line)
    pending = [item["id"] for item in results.get("pending_requirements", [])]
    release = results.get("coverage", {}).get("release_pending", {})
    lines += ["-" * 60, f"  RESULT: {results['status']}"]
    if results["mode"] == "full":
        waiting = [f"{kind} {len(items)} feature(s)" for kind, items in sorted(release.items())]
        lines.append("  scope: routine gate only; NOT full acceptance or release readiness"
                     + (f"; NOT RUN: {', '.join(pending)}" if pending else "")
                     + (f"; release-pending: {', '.join(waiting)}" if waiting else ""))
    elif results["status"] == "PASS":
        lines.append(f"  scope: {results['mode']} selection only; NOT full acceptance")
    lines += ["=" * 60, f"  evidence: {directory}"]
    return lines


def _execute_run(args, argv: list[str], established: dict) -> int:
    try:
        directory = runstore.reserve_run_dir(OUTPUTS_ROOT, REPO_ROOT, args.mode)
    except runstore.RunRefused as exc:
        print(f"verify.py: refusing to create a run: {exc}", file=sys.stderr)
        return runstore.EXIT_INVALID
    record = runstore.RunRecord(directory)
    run = GateRun(args, argv, record, established)
    try:
        run.mark()
        record.log(f"verify.py run {record.run_id}; argv {argv}; error mode {established}")
        run.execute()
        results = run.finalize()
        print("\n".join(_report_lines(results, directory)))
        return results["exit_code"]
    except KeyboardInterrupt:
        record.log(f"INTERRUPTED (KeyboardInterrupt) during gate {run.current_gate}; no result was recorded")
        record.mark("interrupted", reason="interrupted (KeyboardInterrupt)", started_at=run.started_at,
                    current_gate=run.current_gate, interrupted_at=runstore.now_utc())
        print(f"verify.py: INCOMPLETE - interrupted during gate {run.current_gate}; evidence: {directory}", file=sys.stderr)
        return runstore.EXIT_INTERRUPTED
    except BaseException as exc:
        record.log(f"ERROR during gate {run.current_gate}; no result was recorded\n{traceback.format_exc()}")
        record.mark(run.lifecycle, reason=f"error: {type(exc).__name__}: {exc}", started_at=run.started_at,
                    current_gate=run.current_gate, failed_at=runstore.now_utc())
        raise
    finally:
        record.close()


def _not_in_place(directory: Path) -> str | None:
    """Why this is not where the gate wrote a run, directly below ``outputs/`` with no link on the way, or None.

    Plan section 10: a copied run is rejected as current acceptance and its directory name is not trusted. A copy normally keeps
    its folder name, and its id, nonce and manifest travel with it, so its place is the one thing a copy cannot bring along.
    """
    path = Path(os.path.abspath(directory))
    if Path(os.path.normcase(path.parent)) != Path(os.path.normcase(os.path.abspath(OUTPUTS_ROOT))):
        return f"{path} is not directly below {OUTPUTS_ROOT}"
    try:
        runstore.refuse_links(path, REPO_ROOT)
    except runstore.RunRefused as exc:
        return str(exc)
    return None


def _status_command(args) -> int:
    directory = Path(args.status)
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    legacy = (directory / "result.json").is_file() and not (directory / runstore.RESULTS_NAME).exists()
    if legacy or LEGACY_EVIDENCE_ROOT in directory.parents:
        print(f"legacy evidence: {runstore.read_legacy_evidence_status(directory)}. A historical record of its own source, "
              "under the old schema; never current acceptance.")
        return runstore.EXIT_NOT_RUN
    identity, environment = (tree_fingerprint(), environment_identity()) if args.require_current else (None, None)
    outcome = runstore.read_run_status(directory, identity, environment)
    displaced = _not_in_place(directory)
    if displaced and outcome["current"] is not None:
        outcome["current"], outcome["identity_differences"] = "elsewhere", [displaced]
    print(f"status: {outcome['status']}" + (f" (run {outcome['results'].get('run_id')})" if outcome["results"] else ""))
    if displaced and outcome["valid"]:
        print(f"  not in place: {displaced}")
    for problem in outcome["problems"]:
        print(f"  problem: {problem}")
    if args.require_current:
        print(f"  current: {outcome['current']} {outcome.get('identity_differences', '')}")
    if outcome["status"] in ("INCOMPLETE", "INVALID"):
        return runstore.EXIT_NOT_RUN
    code = runstore.EXIT_FOR_STATUS.get(outcome["status"], runstore.EXIT_NOT_RUN)
    if args.require_current and code == runstore.EXIT_PASS and outcome["current"] != "exact":
        if outcome["current"] == "docs-only":
            print("  code, tests, policy, locks and environment match; only documents differ. That is not the same source: "
                  "this evidence carries forward only with the docs checks rerun and both SHAs recorded (plan section 13.3)")
        elif outcome["current"] == "elsewhere":
            print("  a run is current only where the gate wrote it; a copy or a link is a record of that run, not acceptance "
                  "of this source (plan section 10)")
        else:
            print("  this PASS does not describe the current source and environment")
        return runstore.EXIT_NOT_RUN
    return code


class _OnceOnly(argparse.Action):
    """A single-value option. Given twice, argparse would let the last win in silence, so --platform macos --platform windows
    would step around the platform refusal and --status <missing> --status <good> would read PASS. Empty is never a value."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(f"{option_string} may be given only once")
        if not values:
            parser.error(f"{option_string} may not be empty")
        setattr(namespace, self.dest, values)


class _GateParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(runstore.EXIT_INVALID, f"{self.prog}: error: {message}\n")


_HELP_EPILOG = """\
modes: focused needs --test or --feature; changed takes --base (default origin/master); full is the routine gate;
qualification needs --scenario. --preflight-only and --collect-only leave evidence and never establish acceptance.

exit codes: 0 PASS for the requested scope; 1 FAIL; 2 BLOCKED, a prerequisite is unavailable; 3 NOT RUN or incomplete,
including no tests executed; 64 invalid invocation or configuration; 130 interrupted. Exit 0 does not imply release readiness.

--audit-scratch lists every child of the scratch root with its owning run, size and whether it is in use, and changes nothing.

--status reads a finished run back and checks it holds together, read-only. With --require-current a PASS must also describe
the current source and environment and still be where the gate wrote it; its digests, installation and place decide, never
the directory name.
"""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _GateParser(prog="verify.py", description="The verification gate of the Audiobook Creation Tool.",
                         epilog=_HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", action=_OnceOnly, choices=MODES, help="what to verify; see below")
    parser.add_argument("--test", action="append", metavar="ID",
                        help="focused: a test module or node id under files/tests (repeatable)")
    parser.add_argument("--feature", action="append", metavar="ID",
                        help="focused: a stable feature id from coverage.json, such as ACT.TTS.CANCEL (repeatable)")
    parser.add_argument("--journey", action="append", metavar="ID",
                        help="focused: a native and real-media journey registered in verification.json (repeatable); needs the desktop")
    parser.add_argument("--base", action=_OnceOnly, metavar="REF", help="changed: compare with the merge base of this ref (default origin/master)")
    parser.add_argument("--platform", action=_OnceOnly, choices=("windows", "macos"), help="refuse to run (BLOCKED) on any other platform")
    parser.add_argument("--scenario", action=_OnceOnly, choices=SCENARIO_NAMES, help="qualification: the named scenario")
    parser.add_argument("--network", action=_OnceOnly, metavar="POLICY", help="qualification: a network policy the scenario declares; there is "
                                                            "no way to turn isolation off")
    parser.add_argument("--preflight-only", action="store_true", help="prove the prerequisites; run no test")
    parser.add_argument("--collect-only", action="store_true", help="also collect and check the partition; run no test")
    parser.add_argument("--label", action=_OnceOnly, metavar="NAME", help="a short name recorded with the run")
    parser.add_argument("--status", action=_OnceOnly, metavar="RUN_DIR", help="read a run back instead of starting one")
    parser.add_argument("--require-current", action="store_true", help="with --status: a PASS must describe the current source and environment")
    parser.add_argument("--audit-scratch", action="store_true", help="report who owns each scratch folder; removes nothing")
    args = parser.parse_args(argv)
    if args.audit_scratch:
        if args.mode or args.status or args.require_current:
            parser.error("--audit-scratch stands alone")
        return args
    if bool(args.mode) == bool(args.status):
        parser.error("give exactly one of --mode and --status")
    if args.status:
        return args
    if args.require_current:
        parser.error("--require-current goes with --status")
    if args.mode != "focused" and (args.test or args.feature or args.journey):
        parser.error("--test, --feature and --journey go with --mode focused")
    if args.mode == "focused" and not (args.test or args.feature or args.journey):
        parser.error("--mode focused needs --test, --feature or --journey; an empty selection is not a test run")
    if args.mode != "changed" and args.base:
        parser.error("--base goes with --mode changed")
    if args.mode == "changed" and not args.base:
        args.base = "origin/master"
    if args.mode != "qualification" and (args.scenario or args.network):
        parser.error("--scenario and --network go with --mode qualification")
    if args.mode == "qualification" and not args.scenario:
        parser.error("--mode qualification needs --scenario")
    if args.preflight_only and args.collect_only:
        parser.error("--preflight-only and --collect-only are alternatives")
    if args.mode == "qualification" and args.collect_only:
        parser.error("a qualification scenario has no test collection to stop at")
    if args.network and args.network not in _SCENARIO_NETWORK.get(args.scenario, ()):
        parser.error(f"--network {args.network!r} is not a policy of scenario {args.scenario!r}")
    try:
        if args.label:
            runstore.validate_label(args.label)
        if args.test:
            args.test = [selection_rules.parse_selector(raw) for raw in args.test]
    except (runstore.RunRefused, selection_rules.SelectorError) as exc:
        parser.error(str(exc))
    return args


# Named here as well as in the policy so a bad --network is refused before anything exists; a test keeps the two equal.
_SCENARIO_NETWORK = {"edge-low-memory": ("online-edge",)}


def main(argv: list[str] | None = None) -> int:
    # First, before anything can start a child: a gate launched from any terminal must not hang on a dialog.
    established = winproc.establish_error_mode()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # a test name the console cannot encode must not crash a finished run
            stream.reconfigure(errors="backslashreplace")
    args = _parse_args(argv)
    if args.audit_scratch:
        print("\n".join(scratch_store.audit_lines(scratch_store.audit(SCRATCH_ROOT, OUTPUTS_ROOT))))
        return runstore.EXIT_PASS
    if args.status:
        return _status_command(args)
    return _execute_run(args, list(sys.argv if argv is None else argv), established)


if __name__ == "__main__":
    sys.exit(main())
