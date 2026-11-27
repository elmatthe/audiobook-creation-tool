"""The routine verification marker and the heavyweight entrypoint checks (v0.8.2; simplified 2026-11-27).

A routine pytest session (``files/tests/conftest.py`` through ``files/tests/routine_effects.py``, and the gate's own stage
environment) sets ``ACT_VERIFY_CONTEXT=routine``. Environment variables are inherited, so every ordinary child of that
session carries the marker without any launch interception. The maintained heavyweight roots -- the gate, the acceptance
runner, the qualification scenarios, the scaling programs, the gate's native adapters, the real test drivers -- check the
marker first and refuse (:func:`refuse_under_routine` in their ``__main__``, :func:`check_operation` inside their
callables). The check is in their own bytes, so a copy of a root anywhere refuses exactly as the original does.

The one exception is a **synthetic gate fixture** (:func:`synthetic_fixture`): a disposable tree a test built inside its
session's basetemp and declared in ``act-synthetic-fixture.json``. Its copied ``verify.py`` may orchestrate, and its
acceptance and qualification operations may start the tree's stand-ins; a real runner copied into such a tree still refuses
itself, because its own ``__main__`` check is not exempt.

This is accident prevention for cooperating tests and agents, not an operating-system sandbox: a test that replaces the
environment of its child, or a program that never checks the marker, is outside it. Standard library only; programs that
must not change their own import path load it by file path.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CONTEXT_ENV = "ACT_VERIFY_CONTEXT"
#: The checkout the routine session marks (the outermost session's own).
ROOT_ENV = "ACT_VERIFY_ROOT"
#: The routine session's owned disposable roots (its basetemp): a synthetic fixture must lie inside one.
DISPOSABLE_ENV = "ACT_VERIFY_DISPOSABLE"
ROUTINE = "routine"
REFUSED_EXIT = 2
DATA_ONLY = frozenset({"--help", "-h"})
EFFECTS = frozenset({"native-desktop", "real-app-launch", "real-engine", "external-network", "install", "scaling",
                     "release-build"})
SYNTHETIC_DECLARATION = "act-synthetic-fixture.json"
SYNTHETIC_FORMAT = "act-synthetic-fixture/2"
GATE = "files/dev-work/verification-gate/"
#: A Python file name is spelled as a stem plus ``_PY``: the evidence ledger's static closure reads a literal ``"....py"``
#: string as a dependency edge.
_PY = ".py"
ORCHESTRATOR = GATE + "verify" + _PY
#: The stand-in programs a synthetic gate fixture may carry (test fixtures, ``files/tests/routine_recipes/``).
SYNTHETIC_RECIPES = {
    "scripted-acceptance-runner": {"source": "files/tests/routine_recipes/scripted_acceptance_runner" + _PY,
                                   "targets": (GATE + "acceptance_runner" + _PY,), "data": "scripted.json"},
    "scenario-runner": {"source": "files/tests/routine_recipes/scenario_runner" + _PY,
                        "targets": (GATE + "scaling/qualify" + _PY,), "data": "scenario.json"},
    "fake-pytest": {"source": "files/tests/routine_recipes/fake_pytest" + _PY, "targets": None, "data": None},
}
#: Where a classified heavyweight entrypoint lives, relative to any checkout (a key ending in ``/`` covers its folder). Used
#: to name the effect a refusing test driver reports; the static classification is ``verification.json`` ``entrypoints``.
LAUNCH_ROOTS = {
    GATE + "acceptance_runner" + _PY: "native-desktop",
    ORCHESTRATOR: "native-desktop",
    GATE + "qualification/": "real-app-launch",
    GATE + "scaling/": "scaling",
    GATE + "adapters/": "native-desktop",
    "files/dev-tools/": "real-engine",
    "files/tests/macos_gui_driver" + _PY: "real-app-launch",
    "files/tests/manual_plan3_harness" + _PY: "native-desktop",
    "files/tests/manual_plan6_harness" + _PY: "native-desktop",
    "files/tests/manual_windows_ui_prototype" + _PY: "native-desktop",
    "scripts/launcher" + _PY: "real-app-launch",
    "scripts/shared/bootstrap" + _PY: "install",
    "scripts/shared/bootstrap_host.ps1": "install",
    "scripts/shared/bootstrap_host_macos.sh": "install",
    "scripts/shared/release" + _PY: "release-build",
    "Setup_and_Run-audiobook-creation-tool.bat": "install",
    "Setup_and_Run-audiobook-creation-tool.command": "install",
}


def in_routine(environ=None) -> bool:
    return (os.environ if environ is None else environ).get(CONTEXT_ENV) == ROUTINE


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _within(path, base) -> bool:
    real, root = _norm(path), _norm(base)
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def launch_role(relative_or_path: str) -> tuple[str, str, str] | None:
    """``(launch root, its effect, the path relative to that checkout)`` when a path names a heavyweight entrypoint of any
    checkout, matched by its trailing path components. None otherwise."""
    text = os.fspath(relative_or_path).replace("\\", "/")
    lowered = "/" + text.lower().lstrip("/")
    for root, effect in LAUNCH_ROOTS.items():
        key = "/" + root.lower()
        if root.endswith("/"):
            at = lowered.rfind(key)
            if at >= 0:
                return root, effect, (root + lowered[at + len(key):]) if lowered[at + len(key):] else root
        elif lowered.endswith(key):
            return root, effect, root
    return None


def data_only_shape(args, data_only=(), anywhere=()) -> bool:
    """Whether the arguments after an entrypoint's script are a data-only invocation: ``--help``/``-h`` as the sole argument,
    a reviewed data-only flag of that entrypoint as the first argument, or an ``anywhere`` flag as a standalone token."""
    args = [str(arg) for arg in args]
    if len(args) == 1 and args[0] in DATA_ONLY:
        return True
    if args and args[0] in set(data_only):
        return True
    return bool(set(anywhere) & set(args))


def synthetic_fixture(root, environ=None) -> dict | None:
    """The declaration of a synthetic gate fixture tree, or None. Valid only inside routine verification, for a tree inside
    the session's disposable roots that neither is nor contains the marked checkout, whose declaration names this tree."""
    environ = os.environ if environ is None else environ
    disposable, marked = environ.get(DISPOSABLE_ENV), environ.get(ROOT_ENV)
    if not in_routine(environ) or not disposable or not marked or not root:
        return None
    try:
        tree = Path(root)
        if not any(_within(tree, part) for part in disposable.split(os.pathsep) if part) or _within(marked, tree):
            return None
        declaration = tree / SYNTHETIC_DECLARATION
        if declaration.is_symlink() or not declaration.is_file():
            return None
        data = json.loads(declaration.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("format") != SYNTHETIC_FORMAT or _norm(data.get("root", "")) != _norm(tree):
        return None
    return data


def _own_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _guard():
    """The routine guard of this process (files/tests/routine_effects.py) when installed: a refusal inside a pytest process
    is then recorded there and raised as its EffectRefused, so the test that caused it fails even if it caught it."""
    guard = sys.modules.get("routine_effects")
    return guard if guard is not None and getattr(guard, "_installed", False) else None


def _refuse(entry: str, effect: str, detail: str) -> None:
    guard = _guard()
    if guard is not None:
        guard.refuse(effect, f"{entry}: {detail}", origin="entrypoint")
    sys.stderr.write(f"{entry}: refused ({effect}): {detail} inside routine verification (GATE.md)\n")
    sys.stderr.flush()
    raise SystemExit(REFUSED_EXIT)


def refuse_under_routine(entry: str, effect: str, argv=None, *, data_only=frozenset(), anywhere=frozenset(), origin=None,
                         root=None) -> None:
    """For a maintained heavyweight root, first thing: refuse to start inside routine verification, wherever the root lies.
    A data-only invocation stays usable; a synthetic fixture's own ``verify.py`` may orchestrate. Exits ``REFUSED_EXIT``."""
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}")
    if not in_routine():
        return
    argv = list(sys.argv[1:] if argv is None else argv)
    if data_only_shape(argv, data_only, anywhere):
        return
    origin = os.fspath(origin if origin is not None else (sys.argv[0] if sys.argv else ""))
    tree = Path(root) if root is not None else _own_root()
    if origin and origin not in ("-c", "-m", "-"):
        try:
            relative = Path(os.path.realpath(origin)).relative_to(Path(os.path.realpath(tree))).as_posix()
        except ValueError:
            relative = None
        if relative == ORCHESTRATOR and synthetic_fixture(tree) is not None:
            return
    _refuse(entry, effect, "a heavyweight verification entrypoint does not start")


def check_operation(effect: str, detail: str, *, root=None, stand_in: str | None = None, argv=None) -> None:
    """At a heavyweight operation inside an imported callable: refuse inside routine verification (PermissionError). In a
    synthetic fixture tree, an operation that starts the tree's stand-in for ``stand_in`` may proceed: whatever it starts
    is that tree's file, and a real runner copied there refuses itself."""
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}")
    if not in_routine():
        return
    tree = Path(root) if root is not None else _own_root()
    if stand_in and argv is not None and synthetic_fixture(tree) is not None:
        started = [os.path.normcase(os.path.abspath(os.fspath(arg))) for arg in argv]
        if os.path.normcase(os.path.abspath(tree / stand_in)) in started:
            return
    guard = _guard()
    if guard is not None:
        guard.refuse(effect, detail, origin="operation")
    raise PermissionError(f"refused in routine verification: {effect}: {detail}")
