"""The verification-owned child bootstrap (v0.8.2 Phase 1A-1 R2).

A routine verification process never starts an effect-capable Python child as it was asked to. Its launch boundary
(``routine_effects`` preparation, on ``subprocess.Popen``) reserves the child's accounting obligation, then starts::

    <the same interpreter> [the same interpreter options] <this file> script <path>   [arguments...]
    <the same interpreter> [the same interpreter options] <this file> module <name>   [arguments...]
    <the same interpreter> [the same interpreter options] <this file> code   <source> [arguments...]

Before the program, its imports or a package initializer run, this file installs the routine envelope in the child
(``routine_effects.child_main``): the launch is checked against its reservation, the child's own accounting record is
initialized, and the network, model-weight, native-input and launch restrictions are installed. Then the program runs in
this same process, as ``python <path>``, ``python -m <name>`` or ``python -c <source>`` would have run it: its ``argv``,
``__main__``, working directory, import path and exit status are the ones the unprepared command would have had. If the
envelope cannot be established, nothing runs and the child exits non-zero; the parent's reservation then has no
participant, which its ledger never calls clean.

It is always started by absolute path from the marked checkout, so a copy of it elsewhere is never the one that runs.
Standard library only. A cooperating-verification control, not an operating-system sandbox.
"""

if __name__ == "__main__":
    import importlib.util as _util
    import os as _os
    import sys as _sys

    _spec = _util.spec_from_file_location(
        "routine_effects", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "routine_effects.py"))
    _effects = _util.module_from_spec(_spec)
    _sys.modules["routine_effects"] = _effects
    _spec.loader.exec_module(_effects)
    _effects.child_main()
