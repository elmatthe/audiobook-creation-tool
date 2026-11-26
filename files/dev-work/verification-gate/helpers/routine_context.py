"""A heavyweight verification root refuses to start inside routine verification (v0.8.2 Phase 1A-1).

Every process a routine pytest run starts inherits ``ACT_VERIFY_CONTEXT=routine`` (``files/tests/routine_effects.py``). A
child Python does not inherit the parent's audit hook, so the maintained heavyweight roots -- the acceptance runner, the
qualification scenarios (through ``qualification/common.start``) and the scaling programs -- check the marker themselves,
first thing, and refuse: the refusal goes to the inherited ledger (``ACT_EFFECT_LEDGER``) so the routine run that reached
them fail even if the launching test ignored the exit status. Data-only flags (``--help``, ``--list``) stay usable.

The refusal covers the roots of the checkout that set the marker (``ACT_VERIFY_ROOT``, set with it). A disposable copy a
test makes elsewhere -- the gate's own contract tests run synthetic copies of the gate in temporary trees -- is the test's
own and is judged by that test's static classification, exactly as the launch rule in ``routine_effects`` judges it. A
marker without a readable root, or a root that cannot be resolved, refuses (fail closed).

The marker only restricts. Its absence grants nothing beyond today's interim policy (owner authorization for every
heavyweight run, GATE.md); Phase 1A-2 replaces that with an admission delegated from a live coordinator. Standard library
only; a root without ``helpers`` on its import path loads it by file path, so it never changes what that root imports.
Kept in step with ``files/tests/routine_effects.py`` (same names, same ledger format; a contract test compares them).
"""

from __future__ import annotations

import json
import os
import sys

CONTEXT_ENV = "ACT_VERIFY_CONTEXT"
ROOT_ENV = "ACT_VERIFY_ROOT"
LEDGER_ENV = "ACT_EFFECT_LEDGER"
ROUTINE = "routine"
REFUSED_EXIT = 2
DATA_ONLY = frozenset({"--help", "-h"})


def within_marked_root(origin) -> bool:
    """Whether ``origin`` (the starting script) lies in the checkout that set the routine marker. Unknown means yes."""
    root = os.environ.get(ROOT_ENV)
    if not root or not origin or str(origin) in ("-c", "-m", "-"):
        return True
    try:
        real = os.path.normcase(os.path.realpath(origin))
        base = os.path.normcase(os.path.realpath(root))
    except (OSError, ValueError, TypeError):
        return True
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def refuse_under_routine(entry: str, effect: str, argv=None, *, data_only=frozenset(), origin=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get(CONTEXT_ENV) != ROUTINE or (DATA_ONLY | set(data_only)) & set(argv):
        return
    if not within_marked_root(sys.argv[0] if origin is None else origin):
        return
    row = {"effect": effect, "detail": f"{entry} refused to start under {CONTEXT_ENV}={ROUTINE}", "origin": "entrypoint",
           "pid": os.getpid(), "test": os.environ.get("PYTEST_CURRENT_TEST", "child"), "expected": False}
    path = os.environ.get(LEDGER_ENV)
    if path:
        try:
            with open(path, "a", encoding="utf-8") as sink:
                sink.write(json.dumps(row) + "\n")
        except OSError:
            pass
    sys.stderr.write(f"{entry}: refused: a heavyweight verification entrypoint does not start inside routine verification "
                     "(GATE.md)\n")
    raise SystemExit(REFUSED_EXIT)

