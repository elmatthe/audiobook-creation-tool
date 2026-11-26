"""Routine capability classification, read statically (v0.8.2 Phase 1A-1; plan Revision 5).

Ordinary tests declare nothing. A test module that reaches a real heavyweight boundary declares it once, at that boundary,
in a module-level literal the gate reads without importing anything::

    ACT_EFFECTS = {"*": ("native-desktop", "real-app-launch")}           # every test of the module
    ACT_EFFECTS = {"test_real_clone_proof": ("real-engine",)}            # an exceptional test of a mixed module

Keys are ``"*"``, a test function name, or a test class name. A declared test is never part of a routine plan: requested
explicitly it is withheld (the request is incomplete); reached through a feature, a component or a change it is a pending
qualification obligation; a mixed module selected whole is expanded into its other tests (by AST: top-level ``test_``
functions and ``Test`` classes), and a module whose tests cannot be enumerated statically is a gap. Test helpers in
``files/tests`` may declare ``"*"`` too, and every test module whose test-side import closure reaches one inherits it.

The runtime half (``files/tests/routine_effects.py``) refuses the same operations where they happen, so a declaration that
was forgotten is still caught at the operation; the static half only decides what a routine plan may contain.

Two discovery checks keep the declarations honest without a hand-kept list of nodes: :func:`unclassified_boundaries` finds
test modules showing a live-boundary indicator (a real-engine opt-in, a real driver program launched by path, a multi-line
child program that opens the real application or setup window, an import of the gate's native adapters or runner, native
input calls) that neither declare effects nor appear in the reviewed list ``effects.reviewed_bounded`` of
``verification.json``; :func:`entrypoint_problems` finds executable verification entrypoints (a ``__main__`` block under the
gate, ``files/dev-tools`` or the test helpers) missing from the reviewed ``entrypoints`` classification. A selected module
with an unclassified boundary is withheld as a gap. Static analysis cannot certify every future dynamic call, and an
unrestricted shell can still run anything; this is a cooperating-verification control, not a sandbox.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from helpers import repo_files
from helpers.execution_plan import EffectResult, Entry, HEAVY_EFFECTS

TESTS = "files/tests/"
# Stems plus ".py" so the evidence ledger's closure does not read these names as dependency edges of the gate.
DRIVER_FILES = tuple(stem + ".py" for stem in ("macos_gui_driver", "manual_plan3_harness", "manual_plan6_harness",
                                              "manual_windows_ui_prototype"))
WINDOW_CALLS = ("run_with_gui(", "launcher.main(", ".mainloop(")
NATIVE_INPUT = frozenset({"SendInput", "keybd_event", "mouse_event", "SetCursorPos", "CGEventPost", "pyautogui", "pynput"})
ENTRY_ROOTS = ("files/dev-work/verification-gate/", "files/dev-tools/", "files/tests/")
ENTRY_CLASSES = frozenset({"active", "maintained", "obsolete", "bounded", "support"})
ROUTINE_DISPOSITIONS = frozenset({"refused", "data-only", "bounded"})


class DeclarationError(ValueError):
    """An ``ACT_EFFECTS`` literal that is not a literal, names an unknown effect, or is empty."""


@dataclass
class ModuleFacts:
    declared: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tests: list[str] = field(default_factory=list)           # node ids relative to the module: "test_x" or "TestY"
    enumerable: bool = True
    indicators: list[str] = field(default_factory=list)
    has_main: bool = False
    #: ``Test`` class -> its own ``test`` methods; a class whose methods cannot be listed statically (it has a base class)
    #: is in ``opaque`` and a node below it is validated after the run (Phase 1A-1 R1, M1).
    members: dict[str, list[str]] = field(default_factory=dict)
    opaque: set[str] = field(default_factory=set)


def _literal_effects(node: ast.AST, where: str) -> dict[str, tuple[str, ...]]:
    try:
        value = ast.literal_eval(node)
    except ValueError as exc:
        raise DeclarationError(f"{where}: ACT_EFFECTS must be a literal: {exc}") from None
    if not isinstance(value, dict) or not value:
        raise DeclarationError(f"{where}: ACT_EFFECTS must be a nonempty dict")
    declared = {}
    for key, effects in value.items():
        effects = (effects,) if isinstance(effects, str) else tuple(effects)
        unknown = sorted(set(effects) - HEAVY_EFFECTS)
        if not isinstance(key, str) or not key or not effects or unknown:
            raise DeclarationError(f"{where}: ACT_EFFECTS[{key!r}] names unknown or no effects {unknown or list(effects)}")
        declared[key] = tuple(effects)
    return declared


def module_facts(root: Path, relative: str, inventory=None) -> ModuleFacts:
    """Read one module's declarations, enumerable tests and live-boundary indicators. Never imports it, and reads it only
    through the no-follow inventory (helpers/repo_files.py): a linked or irregular path raises ``repo_files.UnsafePath``."""
    inventory = inventory or repo_files.Inventory(root)
    return facts_from_text(inventory.read_text(relative), relative)


def facts_from_text(text: str, relative: str) -> ModuleFacts:
    facts = ModuleFacts()
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ACT_EFFECTS" for t in node.targets):
            facts.declared = _literal_effects(node.value, relative)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                facts.tests.append(node.name)
            if node.name == "pytest_generate_tests":
                facts.enumerable = False
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            facts.tests.append(node.name)
            facts.members[node.name] = [item.name for item in node.body
                                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")]
            if node.bases or node.keywords:
                facts.opaque.add(node.name)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("test") for t in node.targets):
            facts.enumerable = False  # a test made by assignment cannot be enumerated statically
        elif isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
            facts.has_main = True
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if re.fullmatch(r"ACT_[A-Z0-9_]*_REAL", text):
                found.add("real-engine opt-in")
            if any(text == name or text.endswith("/" + name) or text.endswith("\\" + name) for name in DRIVER_FILES) or \
                    text in DRIVER_FILES:
                found.add("real driver program")
            if "\n" in text and any(call in text for call in WINDOW_CALLS):
                found.add("child program opening the real window")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(name and (name.startswith("adapters") or name == "acceptance_runner" or name.endswith("native_input"))
                   for name in names):
                found.add("gate native adapter or runner import")
        elif isinstance(node, (ast.Name, ast.Attribute)):
            if (node.id if isinstance(node, ast.Name) else node.attr) in NATIVE_INPUT:
                found.add("native input call")
    facts.indicators = sorted(found)
    return facts


class Classifier:
    """Static classification of pytest selectors for one snapshot. Module facts and closures are read once each."""

    def __init__(self, root: Path, policy: dict, closures, inventory=None) -> None:
        self.root = Path(root)
        self.policy = policy
        self.closures = closures
        #: The one no-follow inventory of this snapshot, shared with the closure index when it has one (C1).
        self.inventory = inventory or getattr(closures, "inventory", None) or repo_files.Inventory(root)
        self._facts: dict[str, ModuleFacts] = {}
        self.reviewed = dict(policy.get("effects", {}).get("reviewed_bounded", {}))

    def facts(self, relative: str) -> ModuleFacts:
        if relative not in self._facts:
            try:
                self._facts[relative] = module_facts(self.root, relative, self.inventory)
            except (OSError, SyntaxError, ValueError) as exc:
                if isinstance(exc, DeclarationError):
                    raise
                facts = ModuleFacts(enumerable=False)
                facts.indicators = [f"unreadable or unparsable ({type(exc).__name__})"]
                self._facts[relative] = facts
        return self._facts[relative]

    def module_effects(self, module: str) -> tuple[tuple[str, ...], list[str]]:
        """The module's own ``"*"`` effects plus those of declaring test helpers in its test-side closure."""
        effects = set(self.facts(module).declared.get("*", ()))
        via = []
        for path in sorted(self.closures.closure([module])):
            if path == module or not path.startswith(TESTS) or path.rsplit("/", 1)[-1].startswith("test_"):
                continue
            star = self.facts(path).declared.get("*", ())
            if star:
                effects.update(star)
                via.append(path)
        return tuple(sorted(effects)), via

    def unclassified(self, module: str) -> list[str]:
        facts = self.facts(module)
        if not facts.indicators or facts.declared or module in self.reviewed:
            return []
        return facts.indicators

    def __call__(self, selectors: list[str], explicit: set[str]) -> EffectResult:
        executable: list[str] = []
        withheld: list[Entry] = []
        obligations: list[Entry] = []
        gaps: list[Entry] = []
        for selector in selectors:
            module, _, node = selector.partition("::")
            requested = selector in explicit
            kind = self.inventory.classify(module)
            if kind == repo_files.MISSING:
                # Phase 1A-1 R1 (M1): a missing module is a selection gap of this plan, never left for pytest to report.
                gaps.append(Entry(selector, "no such test module", "missing", requested=requested))
                continue
            if kind != repo_files.FILE:
                gaps.append(Entry(selector, f"not a readable regular test module ({kind}); it is never read or run",
                                  "unsafe", requested=requested))
                continue
            facts = self.facts(module)
            star, via = self.module_effects(module)
            unclassified = self.unclassified(module)
            if unclassified:
                gaps.append(Entry(selector, f"unclassified live boundary ({', '.join(unclassified)}): declare ACT_EFFECTS or "
                                            "review it into effects.reviewed_bounded", "unclassified", requested=requested))
                withheld.append(Entry(selector, "unclassified live boundary", "unclassified", requested=requested))
                continue
            if star:
                why = "declares " + ", ".join(star) + (f" through {', '.join(via)}" if via else "")
                withheld.append(Entry(selector, why, "effect", star, requested=requested))
                obligations.append(Entry(f"test:{module}", f"{why}: a qualification obligation", "qualification", star))
                continue
            declared = {key: effects for key, effects in facts.declared.items() if key != "*"}
            if node:
                parts = node.split("::")
                head = parts[0].split("[", 1)[0]
                missing = self.missing_node(facts, parts)
                if missing:
                    gaps.append(Entry(selector, missing, "missing", requested=requested))
                    continue
                if head in declared:
                    withheld.append(Entry(selector, "declares " + ", ".join(declared[head]), "effect", declared[head],
                                          requested=requested))
                    obligations.append(Entry(f"test:{module}::{head}", "a heavyweight test: a qualification obligation",
                                             "qualification", declared[head]))
                    continue
                executable.append(selector)
                continue
            if not declared:
                executable.append(selector)
                continue
            # A mixed module selected whole: its other tests, never the declared ones. Requested explicitly, the whole module
            # is the scope, so each declared node is withheld from it and disclosed (Phase 1A-1 R1, M1 semantics A); reached
            # through a feature, a component or a change, each is a separate qualification obligation (semantics C).
            for key, effects in declared.items():
                obligations.append(Entry(f"test:{module}::{key}", "a heavyweight test of a mixed module: a qualification "
                                                                  "obligation", "qualification", effects))
                if requested:
                    withheld.append(Entry(f"{module}::{key}", "declares " + ", ".join(effects) + ": withheld from the "
                                          "requested module", "effect", effects, requested=True))
            if not facts.enumerable:
                gaps.append(Entry(selector, "a mixed module whose tests cannot be enumerated statically (generated or "
                                            "assigned tests): select its routine nodes explicitly", "unenumerable",
                                  requested=requested))
                continue
            kept = [f"{module}::{name}" for name in facts.tests if name not in declared]
            executable.extend(kept)
            if not kept:
                withheld.append(Entry(selector, "every test of the module is declared heavyweight", "effect",
                                      tuple(sorted({e for es in declared.values() for e in es})), requested=requested))
        return EffectResult(tuple(dict.fromkeys(executable)), tuple(withheld), tuple(obligations), tuple(gaps))

    @staticmethod
    def missing_node(facts: ModuleFacts, parts: list[str]) -> str | None:
        """Why a requested node does not exist, from the module's static facts; None when it exists or cannot be judged
        statically (a generated test, a class with a base class): those are reconciled after the run against the node ids
        that actually executed (``execution_plan.unexecuted``)."""
        head = parts[0].split("[", 1)[0]
        if head not in facts.tests:
            return None if not facts.enumerable else f"no test {head!r} in the module"
        if len(parts) > 1 and head in facts.members and head not in facts.opaque:
            method = parts[1].split("[", 1)[0]
            if method not in facts.members[head]:
                return f"no test {method!r} in class {head}"
        return None


def unclassified_boundaries(root: Path, policy: dict, closures) -> dict[str, list[str]]:
    """Every test module (and test helper) with a live-boundary indicator and no classification. Empty in a sound tree."""
    classifier = Classifier(root, policy, closures)
    # A helper that is itself a classified executable entrypoint (the drivers and manual harnesses) is governed by its
    # ``entrypoints`` row and refuses routine starts in its own ``__main__``; the test modules that use it are judged here.
    entrypoints = set(policy.get("entrypoints", {}))
    found = {}
    for path in sorted((Path(root) / TESTS).glob("*.py")):
        relative = TESTS + path.name
        if path.name == "conftest.py" or (not path.name.startswith("test_") and relative in entrypoints):
            continue
        problems = classifier.unclassified(relative)
        if problems:
            found[relative] = problems
    return found


def tracked_entrypoints(root: Path, tracked: list[str]) -> list[str]:
    """Tracked Python files with a ``__main__`` block under the gate, ``files/dev-tools`` or the test helpers (test modules
    themselves excluded): the executable verification entrypoints the reviewed classification must cover."""
    found = []
    inventory = repo_files.Inventory(root)
    for relative in tracked:
        name = relative.rsplit("/", 1)[-1]
        if not relative.endswith(".py") or not relative.startswith(ENTRY_ROOTS) or name.startswith("test_") \
                or "/outputs/" in relative:
            continue
        try:
            text = inventory.read_text(relative)  # no-follow: a linked entrypoint is never read (C1)
        except OSError:
            continue
        if re.search(r"^if __name__ == [\"']__main__[\"']", text, re.MULTILINE):
            found.append(relative)
    return sorted(found)


def entrypoint_problems(table: dict, discovered: list[str]) -> list[str]:
    """The reviewed classification (``verification.json`` ``entrypoints``) covers exactly the discovered entrypoints, and every
    entry is well formed."""
    entries = {key: value for key, value in table.items() if key != "about"}
    problems = [f"unclassified executable entrypoint {path}" for path in discovered if path not in entries]
    problems += [f"classified entrypoint {path} has no __main__ block (or is gone)" for path in entries if path not in discovered]
    for path, entry in entries.items():
        if entry.get("class") not in ENTRY_CLASSES or entry.get("routine") not in ROUTINE_DISPOSITIONS:
            problems.append(f"{path}: class {entry.get('class')!r} / routine {entry.get('routine')!r} is not a known value")
        if not set(entry.get("effects", [])) <= HEAVY_EFFECTS:
            problems.append(f"{path}: unknown effects {sorted(set(entry.get('effects', [])) - HEAVY_EFFECTS)}")
        if entry.get("routine") == "bounded" and entry.get("effects"):
            problems.append(f"{path}: a bounded entrypoint declares heavyweight effects")
        if not str(entry.get("why", "")).strip():
            problems.append(f"{path}: no reason recorded")
    return problems
