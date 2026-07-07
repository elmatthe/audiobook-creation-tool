"""Shared pytest setup: make scripts/Universal (the import root) importable.

These are behaviour-preservation smoke tests: fast, deterministic, no network
(Edge TTS / Kokoro downloads are never touched). Fixtures that need real media
live in files/test-files/ (gitignored, local-only) and tests that use them skip
when the folder is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "Universal"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
