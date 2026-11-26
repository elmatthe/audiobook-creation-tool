"""The negative controls' tiny Tk window on macOS (v0.8.x P1B): ``adapters/windows/control_target.py`` itself, with the
in-process acting channel in place of the observation-only one, because there is no native input on macOS (D9).

Usage: python control_target.py <config.json>
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

def _routine_context():
    """helpers/routine_context.py, loaded by path so this program's own imports stay as they are (v0.8.2 Phase 1A-1 R1)."""
    import importlib.util
    import sys as _sys

    if "act_gate_routine_context" in _sys.modules:
        return _sys.modules["act_gate_routine_context"]
    spec = importlib.util.spec_from_file_location("act_gate_routine_context",
                                                  Path(__file__).resolve().parents[2] / "helpers" / "routine_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _sys.modules["act_gate_routine_context"] = module
    return module


HERE = Path(__file__).resolve().parent
WINDOWS = HERE.parent / "windows"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    _routine_context().refuse_under_routine("adapters/macos/control_target.py", "native-desktop")  # v0.8.2 Phase 1A-1 R1: wherever it lies
    mac = _load("act_macos_app_launcher", HERE / "app_launcher.py")  # loads only; its main() is not run
    channel = types.ModuleType("channel")
    channel.Channel = mac.MacChannel
    sys.modules["channel"] = channel
    target = _load("act_control_target", WINDOWS / "control_target.py")
    raise SystemExit(target.main())
