"""The repository's test tree is files/tests/, and local workspaces stay inert.

**The defect this exists to prevent.** The 2026-08-29 containment policy moved
roughly 5 GB of development evidence inside the repository, under the gitignored
``files/dev-work/``. One of those trees is a clean-room checkout carrying its own
copy of ``files/tests/``. With no pytest configuration at all, a bare ``pytest``
from the repository root recursed into it, imported those modules first, and
shadowed the real suite: **158 import-file-mismatch errors plus 6 unimportable
snapshot modules**, and 5021 of the 5083 items it did collect came from the
clean-room rather than from the project.

``python scripts/verify.py`` never broke, because it passes ``files/tests`` as an
explicit path. That is exactly what made the breakage easy to miss, and it is why
the fix pins *both* entry points to the same tree rather than trusting the gate
alone.

``files/runtime-data/`` is excluded for the same reason and is **not** new to the
problem: its retained ``phase14/tree-phase12/`` snapshot has carried a second copy
of ``files/tests/`` since 2026-08-22, so ``pytest .`` was already broken before the
migration added a second instance of the same class.

Deliberately cheap: this reads configuration and the current tree. It does not
spawn pytest, so it cannot recurse into the very directories it is guarding.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTEST_INI = REPO_ROOT / "pytest.ini"

#: pytest's own built-in list. Re-declaring ``norecursedirs`` REPLACES it, so
#: dropping one of these silently would remove protection we never meant to touch
#: -- ``.*`` is what keeps ``.venv`` out.
PYTEST_DEFAULTS = (
    "*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}",
)

#: Local-only trees that live inside the repository for containment but are not
#: project source. Both have been observed carrying a second ``files/tests/``.
LOCAL_WORKSPACES = ("dev-work", "runtime-data")


def _ini() -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    return parser


def _norecursedirs() -> list[str]:
    return _ini().get("pytest", "norecursedirs").split()


def test_the_repository_declares_a_pytest_configuration():
    """Without one, pytest's rootdir heuristics decide the suite. They chose wrong."""
    assert PYTEST_INI.is_file(), "pytest.ini is missing; bare pytest will recurse"
    assert _ini().has_section("pytest")


def test_the_default_test_tree_is_files_tests():
    """``testpaths`` is what a bare ``pytest`` collects when given no path."""
    assert _ini().get("pytest", "testpaths").split() == ["files/tests"]


def test_the_verifier_and_a_bare_pytest_agree_on_the_tree():
    """The two entry points must not be able to drift apart.

    ``verify.py`` passes an explicit path, so it ignores ``testpaths`` entirely --
    which is precisely how the suite stayed green while ``pytest`` was broken.
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import verify
    finally:
        sys.path.pop(0)
    declared = Path(_ini().get("pytest", "testpaths").split()[0])
    assert verify.TESTS_DIR.resolve() == (REPO_ROOT / declared).resolve()


@pytest.mark.parametrize("name", LOCAL_WORKSPACES)
def test_each_local_workspace_is_excluded_from_recursion(name):
    """``testpaths`` alone is not enough: ``pytest .`` supplies its own path."""
    assert name in _norecursedirs()


@pytest.mark.parametrize("pattern", PYTEST_DEFAULTS)
def test_no_pytest_default_exclusion_was_dropped(pattern):
    """Re-declaring the key replaces the defaults; none may go missing."""
    assert pattern in _norecursedirs()


def test_the_patterns_are_basenames_not_paths():
    """``norecursedirs`` is fnmatch-ed against the directory *basename*.

    ``files/dev-work`` would silently match nothing, and a backslash form would
    only ever be right on one platform. Keeping every entry separator-free is
    what makes this identical on Windows, macOS and Linux.
    """
    for entry in _norecursedirs():
        assert "/" not in entry and "\\" not in entry, entry


def test_the_local_workspace_is_gitignored():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "files/dev-work/" in text


@pytest.mark.parametrize("name", LOCAL_WORKSPACES)
def test_the_hazard_is_real_where_the_workspace_exists(name):
    """Not hypothetical: prove a colliding basename is actually sitting there.

    Skipped rather than failed when the tree is absent -- both are local-only and
    a fresh clone has neither, which must not turn into a red suite.
    """
    root = REPO_ROOT / "files" / name
    if not root.is_dir():
        pytest.skip(f"files/{name}/ is local-only and not present here")
    mine = {path.name for path in (REPO_ROOT / "files" / "tests").glob("test_*.py")}
    for stray in root.rglob("test_*.py"):
        if stray.name in mine:
            return
    pytest.skip(f"files/{name}/ currently holds no colliding test basename")
