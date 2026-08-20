"""v0.6.1 Plan 4 Phase 12 remediation — settings keys the app writes itself.

**The defect.** Every launch showed *"Some settings could not be used —
settings.json holds keys that are not allowlisted configuration overrides; they
were ignored"*. The ignored keys were the app's own "last folder you used"
state. :data:`config.USER_STATE_SETTINGS` had been written with un-namespaced
names (``input_dir``, ``m4b_cover_dir``, ``tts_output_dir``, …) that **no writer
in this repository has ever used** — every panel namespaces by tool
(``cover_resizer.input_dir``). The allowlist therefore matched nothing, and the
application warned the user about state it had just written itself.

**The guard.** Rather than trusting a hand-maintained list, this module walks the
production tree by AST, finds every ``settings.set(KEY, …)`` call, resolves the
constant it names, and requires the result to be allowlisted. A new panel that
remembers a folder now fails here instead of nagging the user.

**What is deliberately still warned about.** Two keys in the maintainer's real
``settings.json`` have no writer left in the tree — ``window_geometry`` (last
written by ``df900bf``) and ``m4b_maker.output_dir`` (last written by
``466c3d9``). They are genuinely stale, so the warning about them is truthful and
is left alone. Nothing here turns the allowlist into "accept everything", and
arbitrary keys still cannot override ``config.toml``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared import config as cfg  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` assignments."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _settings_writes() -> list[tuple[str, str, int]]:
    """Every ``settings.set(<key>, …)`` in production: (module, key, line)."""
    found: list[tuple[str, str, int]] = []
    for path in sorted(UNIVERSAL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "set":
                continue
            owner = getattr(func.value, "id", "")
            if owner not in {"settings", "app_settings"}:
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                key = first.value
            elif isinstance(first, ast.Name) and first.id in constants:
                key = constants[first.id]
            else:
                continue
            found.append((str(path.relative_to(UNIVERSAL)), key, node.lineno))
    return found


# --------------------------------------------------------------------------- #
# A. The regression guard
# --------------------------------------------------------------------------- #
def test_production_actually_writes_settings():
    assert _settings_writes(), "the AST walk found nothing — the guard is not working"


@pytest.mark.parametrize("module,key,line", _settings_writes(),
                         ids=lambda v: str(v))
def test_every_key_the_app_writes_is_allowlisted(module, key, line):
    """The exact defect: the app warning the user about its own state."""
    overlay = set(cfg.SETTINGS_OVERLAY)
    assert key in cfg.USER_STATE_SETTINGS or key in overlay, (
        f"{module}:{line} writes settings key {key!r}, which is neither "
        f"allowlisted user state nor a configuration override — every launch "
        f"would warn the user about it")


def test_the_allowlist_contains_no_key_no_writer_produces():
    """Keeps the list honest in the other direction, so it cannot become a
    dumping ground of names nothing writes."""
    written = {key for _m, key, _l in _settings_writes()}
    orphans = cfg.USER_STATE_SETTINGS - written
    assert not orphans, (
        f"USER_STATE_SETTINGS allows {sorted(orphans)}, which no production "
        f"settings.set() call produces")


# --------------------------------------------------------------------------- #
# B. The allowlist stays an allowlist
# --------------------------------------------------------------------------- #
def test_an_unknown_key_is_still_reported(tmp_path):
    """B-classified keys — genuinely stale — must keep warning truthfully."""
    assert "window_geometry" not in cfg.USER_STATE_SETTINGS
    assert "m4b_maker.output_dir" not in cfg.USER_STATE_SETTINGS


def test_user_state_never_becomes_a_configuration_override():
    """Allowlisted state must not silently gain power over config.toml."""
    assert not (cfg.USER_STATE_SETTINGS & set(cfg.SETTINGS_OVERLAY))


def test_the_only_configuration_override_is_still_the_output_base():
    assert set(cfg.SETTINGS_OVERLAY) == {"output_base_directory"}


def test_the_allowlist_is_not_a_wildcard():
    assert isinstance(cfg.USER_STATE_SETTINGS, frozenset)
    assert "anything_at_all" not in cfg.USER_STATE_SETTINGS
    assert len(cfg.USER_STATE_SETTINGS) < 40


# --------------------------------------------------------------------------- #
# C. End to end against a realistic settings file
# --------------------------------------------------------------------------- #
def _load_with_settings(tmp_path: Path, payload: dict):
    """Inject settings through the module's own seam — no real file is touched."""
    return cfg.load(settings_data=payload, repo_root=tmp_path, home=tmp_path)


def test_a_settings_file_of_only_app_written_state_produces_no_warning(tmp_path):
    result = _load_with_settings(tmp_path, {
        "last_tool": "tts",
        "cover_resizer.input_dir": str(tmp_path),
        "m4b_maker.input_dir": str(tmp_path),
        "m4b_maker.cover_dir": str(tmp_path),
        "m4b_metadata.input_dir": str(tmp_path),
        "m4b_metadata.cover_dir": str(tmp_path),
        "mp3_tool.input_dir": str(tmp_path),
        "m4b_converter.input_dir": str(tmp_path),
    })
    unrecognised = [d for d in result.diagnostics
                    if "not allowlisted" in d.message]
    assert not unrecognised, [d.detail for d in unrecognised]


def test_a_genuinely_stale_key_is_still_reported(tmp_path):
    result = _load_with_settings(tmp_path, {
        "last_tool": "tts",
        "window_geometry": "1299x846+-1449+30",
    })
    unrecognised = [d for d in result.diagnostics if "not allowlisted" in d.message]
    assert len(unrecognised) == 1
    assert "window_geometry" in unrecognised[0].detail
