"""The negative controls' tiny Tk window on macOS (v0.8.x P1B): ``adapters/windows/control_target.py`` itself, with the
in-process acting channel in place of the observation-only one, because there is no native input on macOS (D9).

Usage: python control_target.py <config.json>
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOWS = HERE.parent / "windows"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    mac = _load("act_macos_app_launcher", HERE / "app_launcher.py")  # loads only; its main() is not run
    channel = types.ModuleType("channel")
    channel.Channel = mac.MacChannel
    sys.modules["channel"] = channel
    target = _load("act_control_target", WINDOWS / "control_target.py")
    raise SystemExit(target.main())
