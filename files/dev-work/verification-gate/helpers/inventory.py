#!/usr/bin/env python3
"""The facts the coverage inventory is judged against, gathered from disk, and the small tool that keeps it up to date (plan section 7.1).

``coverage_model`` judges; this reads. It finds the application's source by the suite's own registry, digests each file, runs static
discovery, reads the feature-map documents, lists the registered journeys and resolves test ids and symbols from source with ``ast``,
without collecting or importing the application. The gate, the coverage tests and the command line below all ask the same function,
``problems``, so they cannot disagree about what is wrong.

Usage (from anywhere; nothing here edits anything but coverage.json, and only ``restamp`` does that):

    python files/dev-work/verification-gate/helpers/inventory.py check
    python files/dev-work/verification-gate/helpers/inventory.py discover
    python files/dev-work/verification-gate/helpers/inventory.py restamp scripts/mp3/mp3_tool.py [more paths]

``restamp`` records that a person has reviewed the named files' features against the source as it is now. It refuses a path it is not
given, so nothing is ever restamped wholesale.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import sys
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GATE_DIR.parents[2]
if __name__ == "__main__" and str(GATE_DIR) not in sys.path:
    sys.path.insert(0, str(GATE_DIR))  # run as a script; imported, the importer has already put the gate on the path

from helpers import coverage_model, surface_discovery  # noqa: E402

COVERAGE_FILE = GATE_DIR / "coverage.json"
POLICY_FILE = GATE_DIR / "verification.json"
FEATURE_MAP_DIR = "files/dev-work/feature-map"
#: The root launch-and-repair scripts are source a user runs, so they are reviewed like application code.
SETUP_LAUNCHER_GLOB = "Setup_and_Run-*"
RUNTIME_SCRIPT_SUFFIXES = (".ps1", ".sh", ".bat", ".cmd", ".command")
QUALIFICATION_SCENARIOS = ("m4b-scaling", "edge-low-memory", "optional-engines", "fresh-windows")


def source_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    """The application's Python source by the suite's registry, the root launchers, and the non-Python scripts inside the registered
    packages that the launch path runs (``bootstrap_host.ps1``). Only registered packages: an untracked local helper elsewhere under
    ``scripts/`` is not application source."""
    files = list(surface_discovery.application_files(repo_root))
    files += [path for path in repo_root.glob(SETUP_LAUNCHER_GLOB) if path.is_file()]
    for package in surface_discovery.application_packages(repo_root):
        files += [path for path in (repo_root / "scripts" / package).rglob("*")
                  if path.suffix.lower() in RUNTIME_SCRIPT_SUFFIXES and path.is_file()]
    return sorted(files)


def digest(path: Path) -> str:
    """Of the text as Git stores it: a checkout's line endings are not a change to review."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def source_digests(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    return {path.relative_to(repo_root).as_posix(): digest(path) for path in source_files(repo_root)}


def documents(coverage: dict, repo_root: Path = REPO_ROOT) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for facts in coverage.get("tools", {}).values():
        document = facts.get("document")
        if document:
            path = repo_root / document
            found[document] = path.read_text(encoding="utf-8") if path.is_file() else None
    return found


def readme(repo_root: Path = REPO_ROOT) -> str | None:
    path = repo_root / FEATURE_MAP_DIR / "README.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def scenario_registry(policy: dict) -> dict[str, dict]:
    """Every registered journey with the layers it gives, from the journeys' own registrations, and whether the policy requires it.
    Registering a journey only defines it; nothing here starts an application. ``sys.path`` is left as it was found."""
    saved = list(sys.path)
    if str(GATE_DIR) not in sys.path:
        sys.path.insert(0, str(GATE_DIR))
    try:
        registered = _runner().load_scenarios()
    finally:
        sys.path[:] = saved
    acceptance = policy.get("acceptance", {})
    required = set(acceptance.get("required_scenarios", []))
    known = required | set(acceptance.get("optional_scenarios", []))
    return {key: {"layers": list(item.layers), "tool": item.tool, "required": key in required}
            for key, item in registered.items() if key in known}


@functools.lru_cache(maxsize=1)
def _runner():
    """The acceptance runner, by its path: the gate may have taken its own folder off ``sys.path`` again after importing this module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("act_acceptance_runner_registry", GATE_DIR / "acceptance_runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=None)
def _tree(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _qualified_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def walk(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                names.add(name)
                walk(node.body, name + ".")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for item in ast.walk(target):
                        if isinstance(item, ast.Name):
                            names.add(prefix + item.id)
            elif isinstance(node, (ast.If, ast.Try)):
                walk(node.body, prefix)
                walk(getattr(node, "orelse", []), prefix)

    walk(tree.body, "")
    return names


def symbol_resolver(repo_root: Path = REPO_ROOT):
    def exists(path: str, symbol: str) -> bool:
        if not path.endswith(".py"):
            return False  # a launcher script names no Python symbol; its entry lists none
        tree = _tree(repo_root / path)
        return tree is not None and symbol in _qualified_names(tree)

    return exists


def test_resolver(repo_root: Path = REPO_ROOT):
    """A reason the test id cannot be found in its module's source, or None. No collection: a deleted or renamed test is seen at once."""

    def reason(test_id: str) -> str | None:
        module, _, rest = test_id.partition("::")
        if "[" in rest:
            rest = rest[:rest.index("[")]
        path = repo_root / module
        if not path.is_file():
            return f"{module} does not exist"
        tree = _tree(path)
        if tree is None:
            return f"{module} does not parse"
        names = _qualified_names(tree)
        parts = rest.split("::")
        if ".".join(parts) in names:
            return None
        if len(parts) == 2 and _inherited(tree, parts[0], parts[1]):
            return None
        return f"{module} defines no {'::'.join(parts)}"

    return reason


def _inherited(tree: ast.Module, cls: str, method: str) -> bool:
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    seen = set()
    while cls in classes and cls not in seen:
        seen.add(cls)
        node = classes[cls]
        if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method for item in node.body):
            return True
        bases = [base.id for base in node.bases if isinstance(base, ast.Name)]
        cls = bases[0] if bases else ""
    return False


def problems(coverage: dict, policy: dict, *, repo_root: Path = REPO_ROOT, collected: set[str] | None = None,
             scenarios: dict[str, dict] | None = None) -> list[str]:
    """Everything structurally wrong with the inventory as it stands on disk. The live index is judged by ``inventory.live-surfaces``."""
    scenarios = scenario_registry(policy) if scenarios is None else scenarios
    acceptance = policy.get("acceptance", {})
    found = coverage_model.problems_in_inventory(
        coverage, scenarios=scenarios, collected=collected, disk_check=lambda relative: (repo_root / relative).is_file(),
        required_tools=acceptance.get("required_tools", coverage_model.SIX_TOOLS), qualification_scenarios=QUALIFICATION_SCENARIOS,
        test_check=test_resolver(repo_root), symbol_check=symbol_resolver(repo_root))
    if coverage.get("schema_version", 1) >= 2:
        static = surface_discovery.discover(repo_root, surface_discovery.application_files(repo_root))
        found += coverage_model.discovery_problems(coverage, static_found=static, source_digests=source_digests(repo_root),
                                                   documents=documents(coverage, repo_root), readme=readme(repo_root))
        if not coverage.get("inventory_reviewed"):
            found.append("inventory_reviewed is false: the inventory has not been reviewed")
    return found


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_coverage(coverage: dict, path: Path = COVERAGE_FILE) -> None:
    text = json.dumps(coverage, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def restamp(paths: list[str], *, repo_root: Path = REPO_ROOT, coverage_file: Path = COVERAGE_FILE) -> list[str]:
    """Record the named files as reviewed as they are now. Returns what was done; refuses anything it was not given by name."""
    if not paths:
        raise SystemExit("restamp needs the paths you reviewed; nothing is restamped wholesale")
    coverage = _load(coverage_file)
    current = source_digests(repo_root)
    stamps = coverage.setdefault("source_review", {})
    done = []
    for raw in paths:
        path = raw.replace("\\", "/")
        if path not in current and path not in stamps:
            raise SystemExit(f"{path} is not application source (see files/tests/source_probe.py) or a setup launcher")
        features = sorted({feature["id"] for feature in coverage.get("features", []) for source in feature.get("source", [])
                           if source.get("path") == path})
        if path in current:
            stamps[path] = current[path]
            done.append(f"stamped {path}; its features: {features or 'NONE: map it to a feature before this passes'}")
        else:
            del stamps[path]
            done.append(f"removed the stamp of {path}, which no longer exists; its features still naming it: {features}")
    coverage["source_review"] = dict(sorted(stamps.items()))
    write_coverage(coverage, coverage_file)
    return done


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    if command == "restamp":
        for line in restamp(argv[1:]):
            print(line)
        return 0
    coverage, policy = _load(COVERAGE_FILE), _load(POLICY_FILE)
    if command == "discover":
        static = surface_discovery.discover(REPO_ROOT, surface_discovery.application_files(REPO_ROOT))
        for line in surface_discovery.compare_static(coverage.get("surfaces", {}).get("static", {}), static):
            print(line)
        return 0
    if command != "check":
        raise SystemExit(f"unknown command {command!r}: check, discover or restamp")
    found = problems(coverage, policy)
    for line in found:
        print(line)
    print(f"{len(found)} problem(s); {len(coverage.get('features', []))} features")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
