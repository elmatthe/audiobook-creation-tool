"""Run ordinary pytest inside the routine verification envelope (v0.8.2 Phase 1A-1).

Usage (the gate's ordinary collection and execution stages): python -u files/tests/routine_pytest.py <pytest arguments>

Collection already executes code -- plugins, ``conftest.py``, every selected test module's imports -- so the restrictions
are established here, before ``pytest`` is imported: ambient real-engine opt-ins and overrides are scrubbed, third-party
plugin autoload is off (``PYTEST_DISABLE_PLUGIN_AUTOLOAD``; ``pytest.ini`` also says ``--disable-plugin-autoload`` for raw
runs), the routine context marker is set for every child, and ``routine_effects`` refuses heavyweight launches and declared
boundaries from the first import on. ``conftest.py`` loads the session probe and the guards as before (the gate keeps
supplying basetemp, cache and TEMP). A refusal recorded after pytest finished -- an ``atexit`` callback, a late thread --
still changes this process's exit status: the accounting below is registered first, so it runs last.

The import environment is the one ``python -m pytest`` gives (the working directory first on ``sys.path``), so nothing a
test imports resolves differently because of this file. The stronger guarded runner (``guarded_pytest.py``) keeps its own
process-site, lifetime-report and containment contracts and is not replaced by this.
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
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    effects.install()
    state = {"exit": None, "seen": 0}

    def account() -> None:
        late = effects.unexpected()
        if state["exit"] is not None and len(late) > state["seen"]:
            sys.stderr.write(f"routine_pytest: {len(late) - state['seen']} heavyweight effect(s) refused after the session "
                             "ended; the run is not a pass\n")
            sys.stderr.flush()
            os._exit(1 if state["exit"] == 0 else int(state["exit"]))

    atexit.register(account)  # registered before pytest exists: runs after every later atexit callback
    import pytest

    code = int(pytest.main(argv))
    state["exit"], state["seen"] = code, len(effects.unexpected())
    if code == 0 and state["seen"]:
        code = 1  # conftest fails the session for these already; this keeps the exit status honest if it could not
    state["exit"] = code
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
