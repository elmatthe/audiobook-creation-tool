"""Run ordinary pytest inside the routine verification envelope (v0.8.2 Phase 1A-1, corrected in R1).

Usage (the gate's ordinary collection and execution stages, and a direct targeted run):
    python -u files/tests/routine_pytest.py <pytest arguments>

Collection already executes code -- plugins, ``conftest.py``, every selected test module's imports -- so the restrictions
and the accounting are established here, before ``pytest`` is imported, by the same early setup the guarded runner uses
(``routine_effects.bootstrap``): third-party plugin autoload off, ambient real-engine opt-ins and overrides scrubbed, the
routine marker set for every child, the launch, network, model-weight and native-input checks installed, and this session's
own record opened in its effect ledger (the gate stage's ledger, initialized by the gate; for a direct run, a new ledger
beside the requested ``--basetemp``). The session's end record is written last -- after every later ``atexit`` callback --
so a refusal recorded after pytest finished (an ``atexit`` callback, a late thread) still changes this process's exit
status, and a session that could not complete its accounting is never clean.

This is the supported invocation for ordinary routine pytest; a raw ``python -m pytest`` gets the restrictions from
``conftest.py`` only after its plugins load, and is not verification evidence (GATE.md). The import environment is the one
``python -m pytest`` gives (the working directory first on ``sys.path``), so nothing a test imports resolves differently
because of this file. The stronger guarded runner (``guarded_pytest.py``) keeps its own process-site, lifetime-report and
containment contracts.
"""

from __future__ import annotations

import atexit
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_effects():
    spec = importlib.util.spec_from_file_location("routine_effects", os.path.join(_HERE, "routine_effects.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["routine_effects"] = module  # conftest's ``import routine_effects`` finds this same instance
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    sys.path[0] = os.getcwd()  # as ``python -m pytest`` would have it
    effects = _load_effects()
    try:
        effects.bootstrap("routine-pytest", argv)
    except OSError as exc:  # the ledger could not be established: nothing may run unaccounted
        sys.stderr.write(f"routine_pytest: the effect ledger could not be established ({exc}); nothing ran\n")
        return 3
    state = {"exit": None}

    owned = effects.ledger_owner == "routine-pytest"

    def account() -> None:
        code = 1 if state["exit"] is None else int(state["exit"])
        final = effects.finish(code)
        if owned and final == 0:
            # This run created its ledger (a direct run): as its owner, judge it whole now that the session has ended --
            # a cooperating child that never completed its record, or a malformed record, is not clean.
            verdict = effects.read_ledger(os.environ[effects.LEDGER_ENV], require_role="routine-pytest")
            if verdict["status"] != "PASS":
                sys.stderr.write("routine_pytest: the effect ledger is not clean: " + "; ".join(
                    verdict["problems"][:4] + [f"{row.get('effect')}: {row.get('detail')}" for row in verdict["unexpected"][:2]])
                    [:2000] + "\n")
                final = 1
        late = effects.unexpected()
        if final != code or late:
            sys.stderr.write(f"routine_pytest: {len(late)} unexpected refusal(s), {len(effects.accounting_failures())} "
                             "accounting failure(s); the run is not a pass\n")
            sys.stderr.flush()
        if final != code:
            os._exit(final)

    atexit.register(account)  # registered before pytest exists: runs after every later atexit callback
    import pytest

    code = int(pytest.main(argv))
    if code == 0 and (effects.unexpected() or effects.accounting_failures()):
        code = 1  # conftest fails the session for these already; this keeps the exit status honest if it could not
        details = [f"{row.get('effect')}: {row.get('detail')}" for row in effects.unexpected()] + effects.accounting_failures()
        sys.stderr.write("routine_pytest: not a pass: " + "; ".join(details[:5])[:2000] + "\n")
    state["exit"] = code
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
