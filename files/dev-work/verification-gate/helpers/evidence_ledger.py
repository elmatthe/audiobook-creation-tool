"""Incremental verification: which earlier results still describe this tree, which a change invalidated, and why.

Owner's policy of 2026-11-15 (Decisions, P1B closeout): during implementation and remediation a correction reruns what it can
affect -- the failing test, its regression test, the tests of the modules it changed and of everything that imports them, the
journeys and scenarios that drive them, the gate's own self-tests when gate code changed -- and nothing else without a reason.
Earlier passing evidence is kept with its source; a change invalidates the evidence that depends on it and only that. This is
bookkeeping over the runs ``verify.py`` already writes, never a gate of its own and never a canonical PASS: the final release
gate still runs comprehensively on the finalized SHA on both platforms.

How an item's dependence is decided (every rule errs towards rerunning):

  * **The files a run saw.** Each run records the git blob of every tracked and in-scope file as it found them
    (``evidence-files.json``). A run from before that record is usable only if its tree was clean at its HEAD (the blobs are
    then that commit's); otherwise its evidence cannot be tied to files and needs a rerun.
  * **Python dependence** is the static import closure of the item's entry files over ``scripts``, ``files/tests`` and the
    gate folder: ``import`` statements, plus string constants that name a module (``importlib``, the launcher's tool list) or a
    ``.py`` file (a script a test starts). ``files/tests/conftest.py`` is in every test's closure.
  * **Journeys** depend on their own journey module, the runner, the macOS driver, the application shell and the tool modules
    of the tool they drive (``TOOL_MODULES``), plus ``acceptance.journey_routes``. **Scenarios** on their runner and the
    tools they drive (``SCENARIO_TOOLS``).
  * **Other files** follow the policy's ``changed`` tables: ``no_selection`` (documents) reaches nothing; a ``routes`` prefix
    reaches the tests it names; anything else that is not Python -- a fixture, a data file, a lock -- cannot be bounded, so it
    reaches everything. ``changed.always`` is rerun for any change that reaches anything.
  * A different interpreter, Tk or FFmpeg reaches everything.

Statuses: ``PASS (current)`` (this HEAD, nothing changed since), ``PREVIOUSLY PASS - NOT AFFECTED`` (with the run's SHA),
``NEEDS RERUN`` (with the changed files that reach it), ``FAIL``, ``BLOCKED``, ``NOT RUN``. Only the first two count as passed.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

FILES_NAME = "evidence-files.json"
VERDICTS_NAME = "acceptance-verdicts.json"
CURRENT, CARRIED, RERUN, FAIL, BLOCKED, NOT_RUN = (
    "PASS (current)", "PREVIOUSLY PASS - NOT AFFECTED", "NEEDS RERUN", "FAIL", "BLOCKED", "NOT RUN")
PASSED = (CURRENT, CARRIED)
_ORDER = (FAIL, BLOCKED, RERUN, NOT_RUN, CARRIED, CURRENT)
GATE_PREFIX = "files/dev-work/verification-gate/"
OUTPUTS_PREFIX = GATE_PREFIX + "outputs/"
SCOPES = ("scripts", "files/tests", "files/dev-work/verification-gate", "files/dev-work/feature-map")
ROOTS = ("scripts", "files/tests", "files/dev-work/verification-gate")
#: The tool modules a journey or scenario of each tool drives (the launcher loads only the tool that is opened).
TOOL_MODULES = {
    "mp3-tool": ["scripts/mp3/mp3_tool.py"], "m4b-converter": ["scripts/m4b/converter/m4b_converter.py"],
    "m4b-maker": ["scripts/m4b/maker/m4b_maker.py"], "m4b-metadata": ["scripts/m4b/metadata/m4b_metadata_editor.py"],
    "cover-image": ["scripts/artwork/cover_resizer.py"], "tts-audiobook": ["scripts/tts/epub2tts_gui.py"],
}
TOOL_MODULES["launcher"] = sorted({path for paths in TOOL_MODULES.values() for path in paths})
# The registry names tools both ways (the policy's slug and the launcher's key); the shell's own journeys reach every tool.
for _alias, _name in {"mp3_tool": "mp3-tool", "m4b_converter": "m4b-converter", "m4b_maker": "m4b-maker", "m4b_metadata": "m4b-metadata",
                      "m4b-metadata-editor": "m4b-metadata", "cover": "cover-image", "tts": "tts-audiobook", "gate": "launcher",
                      "setup": "launcher"}.items():
    TOOL_MODULES[_alias] = TOOL_MODULES[_name]
SCENARIO_TOOLS = {"macos-native-dialogs": ["mp3-tool", "m4b-converter", "m4b-maker", "m4b-metadata-editor", "cover-image"],
                  "macos-visual": ["launcher"], "macos-kx10": ["m4b-maker"]}
#: The application shell every journey starts, without the tool list it loads lazily.
SHELL = ["scripts/launcher.py", GATE_PREFIX + "adapters/macos/app_launcher.py", GATE_PREFIX + "adapters/windows/app_launcher.py",
         GATE_PREFIX + "acceptance_runner.py", GATE_PREFIX + "adapters/macos/app_session.py"]
_MODULE_TEXT = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def _git(root: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["git", "--no-optional-locks", *args], cwd=str(root), capture_output=True, input=stdin, text=True,
                          encoding="utf-8", errors="surrogateescape")
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {done.stderr.strip()[:300]}")
    return done.stdout


# --------------------------------------------------------------------------- #
#  What files a tree holds, as git blobs (so CRLF working bytes compare as Git stores them)
# --------------------------------------------------------------------------- #
def blob_map(root: Path) -> dict[str, str]:
    """Every tracked file and every untracked, non-ignored file in SCOPES, by its blob id as the working tree has it now."""
    root = Path(root)
    found: dict[str, str] = {}
    for line in _git(root, "ls-files", "-s", "-z").split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            found[path] = meta.split()[1]
    changed = [p for p in _git(root, "diff", "--name-only", "-z").split("\0") if p]
    untracked = [p for p in _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *SCOPES).split("\0") if p]
    present = [p for p in changed + untracked if (root / p).is_file()]
    for path in changed:
        if not (root / path).exists():
            found[path] = "<deleted>"
    if present:
        hashed = _git(root, "hash-object", "--stdin-paths", stdin="\n".join(present) + "\n").split()
        found.update(zip(present, hashed))
    return {path: blob for path, blob in found.items() if not path.startswith(OUTPUTS_PREFIX)}


def blob_map_at(root: Path, sha: str) -> dict[str, str]:
    found = {}
    for line in _git(root, "ls-tree", "-r", "-z", sha).split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            found[path] = meta.split()[2]
    return found


def changed_between(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


# --------------------------------------------------------------------------- #
#  Static dependence
# --------------------------------------------------------------------------- #
class Closures:
    """Import closures over the repository's three Python roots, memoised per entry."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._edges: dict[str, set[str]] = {}
        #: Files that could not be read or parsed: their edge set is unknown, never "no dependencies" (v0.8.2 Phase 1A-1).
        self.unparsed: set[str] = set()
        #: Every dotted name each parsed file imports, resolved or not, so a deleted module's consumers can still be found.
        self.names: dict[str, set[str]] = {}

    def _resolve_module(self, dotted: str, base: Path | None = None) -> str | None:
        parts = dotted.split(".")
        candidates = [self.root / r for r in ROOTS] + ([base] if base else [])
        for start in candidates:
            for tail in (Path(*parts).with_suffix(".py"), Path(*parts) / "__init__.py"):
                path = start / tail
                if path.is_file():
                    return path.relative_to(self.root).as_posix()
            if len(parts) > 1:  # "from a.b import name": name may be an attribute of a.b
                path = start / Path(*parts[:-1]).with_suffix(".py")
                if path.is_file():
                    return path.relative_to(self.root).as_posix()
        return None

    def _resolve_file(self, text: str, here: Path) -> str | None:
        name = text.replace("\\", "/")
        if " " in name or not name.endswith(".py"):
            return None
        for start in (here, *[self.root / r for r in ROOTS], self.root):
            path = (start / name)
            if path.is_file():
                try:
                    return path.resolve().relative_to(self.root.resolve()).as_posix()
                except ValueError:
                    return None
        return None

    def edges(self, relative: str) -> set[str]:
        if relative in self._edges:
            return self._edges[relative]
        self._edges[relative] = found = set()
        path = self.root / relative
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            if path.is_file() or relative.endswith(".py"):
                self.unparsed.add(relative)
            return found
        here = path.parent
        raw = self.names.setdefault(relative, set())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                raw.update(names)
            elif isinstance(node, ast.ImportFrom):
                raw.update([node.module or ""] + [f"{node.module}.{alias.name}" if node.module else alias.name
                                                  for alias in node.names])
                if node.level:
                    base = here
                    for _ in range(node.level - 1):
                        base = base.parent
                    module = node.module or ""
                    for alias in node.names:
                        target = self._resolve_module(f"{module}.{alias.name}".strip("."), base) if module else \
                            self._resolve_module(alias.name, base)
                        if target:
                            found.add(target)
                    if module:
                        target = self._resolve_module(module, base)
                        if target:
                            found.add(target)
                    continue
                module = node.module or ""
                names = [module] + [f"{module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
                text = node.value
                target = self._resolve_file(text, here) if text.endswith(".py") else (
                    self._resolve_module(text) if _MODULE_TEXT.match(text) else None)
                if target:
                    found.add(target)
                continue
            for name in names:
                target = self._resolve_module(name, here)
                if target:
                    found.add(target)
        found.discard(relative)
        return found

    def closure(self, entries, *, exclude=()) -> set[str]:
        """Everything reachable from ``entries``. A file in ``exclude`` (and what only it reaches) is left out unless it is an
        entry: the launcher names every tool and the runner every journey module, but a journey opens one tool and is one module."""
        excluded = set(exclude) - set(entries)
        seen: set[str] = set()
        stack = [entry for entry in entries if (self.root / entry).is_file()]
        while stack:
            current = stack.pop()
            if current in seen or current in excluded:
                continue
            seen.add(current)
            stack.extend(self.edges(current) - seen)
        return seen


@dataclass
class Item:
    kind: str          # test, journey, scenario
    id: str
    files: set[str] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)  # path prefixes that reach it without being in its closure


def build_items(root: Path, policy: dict, *, tests=(), journeys=(), scenarios=(), journey_tools: dict | None = None) -> list[Item]:
    closures = Closures(root)
    changed = policy.get("changed", {})
    items: list[Item] = []
    tool_entries = sorted({path for paths in TOOL_MODULES.values() for path in paths})
    for test in tests:
        files = closures.closure([test, "files/tests/conftest.py"])
        routes = {prefix for prefix, listed in changed.get("routes", {}).items() if test in listed}
        if test in changed.get("always", []):
            routes.add("")  # any change at all
        items.append(Item("test", test, files, routes))
    journey_routes = policy.get("acceptance", {}).get("journey_routes", {})
    journey_modules = sorted(path.relative_to(root).as_posix() for path in (Path(root) / GATE_PREFIX / "journeys").glob("*.py"))
    for journey in journeys:
        tool = (journey_tools or {}).get(journey, "launcher")
        own = [GATE_PREFIX + f"journeys/{journey.split('.', 1)[0]}.py", GATE_PREFIX + "journeys/common.py"]
        mine = TOOL_MODULES.get(tool, TOOL_MODULES["launcher"])
        files = closures.closure([*own, *SHELL, *mine], exclude=[*(set(tool_entries) - set(mine)), *(set(journey_modules) - set(own))])
        routes = {prefix for prefix, listed in journey_routes.items() if listed == "all" or journey in listed}
        items.append(Item("journey", journey, files, routes | {GATE_PREFIX + "verification.json"}))
    for scenario in scenarios:
        runner = policy.get("darwin_scenarios", {}).get(scenario, {}).get("runner") or \
            policy.get("scenarios", {}).get(scenario, {}).get("runner")
        entries = [GATE_PREFIX + runner] if runner else []
        mine = [module for tool in SCENARIO_TOOLS.get(scenario, ["launcher"]) for module in TOOL_MODULES[tool]]
        direct = closures.edges(entries[0]) if entries else set()
        files = closures.closure([*entries, *SHELL, *mine], exclude=[*(set(tool_entries) - set(mine)),
                                                                     *(set(journey_modules) - direct - {GATE_PREFIX + "journeys/common.py"})])
        items.append(Item("scenario", scenario, files, {GATE_PREFIX + "verification.json", GATE_PREFIX + "fixtures/"}))
    return items


def reaches(item: Item, path: str, policy: dict) -> bool:
    """Whether a change to ``path`` can affect ``item`` (true whenever it cannot be bounded)."""
    changed = policy.get("changed", {})
    if any(path == prefix or path.startswith(prefix) for prefix in changed.get("no_selection", [])) or path.startswith(OUTPUTS_PREFIX):
        return False
    if "" in item.routes or path in item.files:
        return True
    if any(prefix and (path == prefix or path.startswith(prefix)) for prefix in item.routes):
        return True
    if path.endswith(".py"):
        return False  # Python reaches only through closures, which were checked above
    if any(path == prefix or path.startswith(prefix) for prefix in changed.get("routes", {})):
        return False  # routed elsewhere: the route names who it reaches
    if any(path == prefix or path.startswith(prefix) for prefix in
           policy.get("acceptance", {}).get("journey_routes", {})) and item.kind != "test":
        return False
    return True  # data, fixtures, locks, configuration: unbounded


# --------------------------------------------------------------------------- #
#  What the runs found
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    folder: Path
    run_id: str
    started_at: str
    status: str
    head: str | None
    environment: dict
    files: dict[str, str] | None
    files_source: str
    results: dict = field(default_factory=dict)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def admissible(folder: Path) -> tuple[bool, str]:
    """A run is evidence only as the gate itself reads it back: completed, sealed, its start and artifacts intact."""
    from helpers import runstore

    outcome = runstore.read_run_status(folder)
    return bool(outcome.get("valid")), "; ".join(outcome.get("problems", [])[:2]) or outcome.get("status", "")


def load_runs(root: Path, folders) -> tuple[list[Run], list[str]]:
    runs, skipped = [], []
    for base in folders:
        for folder in sorted(Path(base).glob("20*_*")) if Path(base).is_dir() else []:
            results = _read(folder / "results.json")
            start = _read(folder / "start.json") or {}
            valid, why = admissible(folder)
            if not isinstance(results, dict) or not valid:
                skipped.append(f"{folder.name}: not admissible ({why or 'unreadable'})")
                continue
            identity = start.get("identity") or {}
            files, source = _read(folder / FILES_NAME), "recorded"
            if not isinstance(files, dict):
                files, source = None, "unrecoverable"
                if identity.get("head") and not identity.get("dirty_tracked") and not identity.get("untracked_in_scope"):
                    try:
                        files, source = blob_map_at(root, identity["head"]), "clean at its HEAD"
                    except RuntimeError:
                        files = None
            runs.append(Run(folder, results.get("run_id", folder.name), results.get("started_at", ""), results.get("status", ""),
                            identity.get("head"), results.get("environment") or start.get("environment") or {}, files, source, results))
    runs.sort(key=lambda run: run.started_at, reverse=True)
    return runs, skipped


def _test_outcomes(run: Run) -> dict[str, str]:
    path = run.folder / "reports" / "pytest.xml"
    outcomes: dict[str, str] = {}
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return outcomes
    for case in tree.iter("testcase"):
        module = (case.get("classname") or "").split("[")[0]
        parts = module.split(".")
        name = next((f"files/tests/{part}.py" for part in parts if part.startswith("test_")), None)
        if name is None:
            continue
        bad = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        previous = outcomes.get(name, "PASS")
        outcomes[name] = "FAIL" if bad or previous == "FAIL" else ("PASS" if not skipped or previous == "PASS" else "SKIP")
    return outcomes


def _journey_outcomes(run: Run) -> dict[str, str]:
    verdicts = _read(run.folder / "reports" / VERDICTS_NAME)
    if isinstance(verdicts, list):
        return {item["id"]: item["verdict"] for item in verdicts if isinstance(item, dict) and "id" in item}
    found = {}
    try:
        text = (run.folder / "acceptance-report.md").read_text(encoding="utf-8")
    except OSError:
        return found
    for match in re.finditer(r"^\| `([^`]+)` \| ([A-Z ]+?) \|", text, re.M):
        found[match.group(1)] = match.group(2).strip()
    return found


def _scenario_outcomes(run: Run) -> dict[str, str]:
    found = {}
    checks = {item.get("name"): item.get("status") for item in run.results.get("checks", []) if isinstance(item, dict)}
    for name, status in checks.items():
        if isinstance(name, str) and name.startswith("scenario:"):
            scenario = name.split(":", 1)[1]
            evidence = checks.get(f"scenario-evidence:{scenario}")
            found[scenario] = "FAIL" if status == "PASS" and evidence not in (None, "PASS") else status
    return found


def outcome_of(run: Run, item: Item) -> str | None:
    table = {"test": _test_outcomes, "journey": _journey_outcomes, "scenario": _scenario_outcomes}[item.kind](run)
    return table.get(item.id)


# --------------------------------------------------------------------------- #
#  The ledger
# --------------------------------------------------------------------------- #
def _environment_key(environment: dict) -> dict:
    return {key: environment.get(key) for key in sorted(environment) if any(word in key for word in ("python", "tk", "ffmpeg", "platform"))
            and not key.endswith(("executable", "path", "prefix"))}


def assess(item: Item, runs: list[Run], current: dict[str, str], head: str | None, environment: dict, policy: dict) -> dict:
    for run in runs:
        outcome = outcome_of(run, item)
        if outcome is None:
            continue
        entry = {"item": item.id, "kind": item.kind, "run": run.run_id, "run_folder": str(run.folder), "run_sha": run.head,
                 "run_outcome": outcome, "closure_files": len(item.files), "files_record": run.files_source}
        if outcome in ("FAIL", "BLOCKED", "NOT RUN", "SKIP", "NOT APPLICABLE"):
            label = {"FAIL": FAIL, "BLOCKED": BLOCKED}.get(outcome, NOT_RUN)
            return {**entry, "status": label, "why": f"its latest run {run.run_id} at {str(run.head)[:12]} said {outcome}"}
        if run.files is None:
            return {**entry, "status": RERUN, "why": f"run {run.run_id} was on a tree that cannot be reconstructed (dirty, no file record)"}
        if _environment_key(run.environment) != _environment_key(environment):
            return {**entry, "status": RERUN, "why": "the interpreter, Tk or FFmpeg differs from the run's"}
        changed = changed_between(run.files, current)
        reaching = [path for path in changed if reaches(item, path, policy)]
        if reaching:
            return {**entry, "status": RERUN, "why": f"{len(reaching)} changed file(s) reach it", "changed": reaching[:12]}
        relevant = [path for path in changed if not any(path.startswith(prefix) for prefix in policy.get("changed", {}).get("no_selection", []))]
        if run.head == head and not relevant:
            return {**entry, "status": CURRENT, "why": f"run {run.run_id} at this HEAD; nothing has changed since"}
        return {**entry, "status": CARRIED, "why": f"PASS at {str(run.head)[:12]} ({run.run_id}); none of the {len(changed)} changed "
                                                   f"file(s) is in its {len(item.files)}-file closure or routes"}
    return {"item": item.id, "kind": item.kind, "status": NOT_RUN, "why": "no recorded run executed it", "closure_files": len(item.files)}


def worst(statuses) -> str:
    present = set(statuses)
    for status in _ORDER:
        if status in present:
            return status
    return NOT_RUN


def rerun_plan(entries: list[dict], platform: str) -> list[str]:
    tests = [entry["item"] for entry in entries if entry["kind"] == "test" and entry["status"] not in PASSED]
    journeys = [entry["item"] for entry in entries if entry["kind"] == "journey" and entry["status"] not in PASSED]
    scenarios = [entry["item"] for entry in entries if entry["kind"] == "scenario" and entry["status"] not in PASSED]
    gate = "files/dev-work/verification-gate/verify.py"
    plan = []
    if tests:
        plan.append(f"{gate} --mode focused --platform {platform} " + " ".join(f"--test {test}" for test in tests))
    # v0.8.2 Phase 1A-1: a journey is never part of a focused run. Its rerun is a qualification, which needs the owner's
    # authorization for that run and executes only once Phase 1A-3 activates it (plan only until then).
    if journeys:
        plan.append(f"{gate} --mode qualification --platform {platform} " + " ".join(f"--journey {j}" for j in journeys)
                    + "   [owner authorization; plan only until Phase 1A-3]")
    plan += [f"{gate} --mode qualification --platform {platform} --scenario {scenario}   [owner authorization]"
             for scenario in scenarios]
    return plan
