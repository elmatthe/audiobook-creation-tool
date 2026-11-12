"""Where the verification gate lives, written once, and how a test loads a fresh copy of it.

The gate is a development tool under ``files/dev-work/verification-gate``, not on the application's import path. Every test
that reads it gets it from here, so a future move changes one line. Each call executes the file anew, so what one test
patches on the module it got cannot reach another test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATE_DIR = REPO_ROOT / "files" / "dev-work" / "verification-gate"
GATE_PATH = GATE_DIR / "verify.py"


def load_gate(name: str = "act_verify"):
    """A fresh module object for ``verify.py``, registered under ``name`` so dataclasses can resolve it."""
    spec = importlib.util.spec_from_file_location(name, GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
