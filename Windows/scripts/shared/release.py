"""Developer release-packaging helper — NOT part of the running application.

Run this by hand from a dev checkout to produce the distributable zips:

    python Windows/scripts/shared/release.py
    # or, equivalently, from the MacOS tree:
    python MacOS/scripts/shared/release.py

It builds two archives under ``<repo-root>/dist/``:

    dist/AudiobookTool-Windows-vX.Y.Z.zip
    dist/AudiobookTool-MacOS-vX.Y.Z.zip

Each archive contains the matching OS tree (``Windows/`` or ``MacOS/``) with all
machine-specific / regenerable artifacts excluded, plus ``README.md`` and the
correct double-click launcher at the archive root, so a non-technical user sees
the launcher immediately on extract. The version string comes from the single
source of truth in ``version.py``.

This module must never be imported by the launcher or any tool — it is a
build-time developer utility only and depends on nothing inside the app.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

# release.py lives at <repo>/<OS>/scripts/shared/release.py
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
OS_ROOT = SHARED_DIR.parent.parent          # e.g. <repo>/Windows
REPO_ROOT = OS_ROOT.parent                  # the 5-item repo root
DIST_DIR = REPO_ROOT / "dist"

# Pull the version from the single source of truth next to this file. Running a
# script makes its own directory sys.path[0], but be explicit so the import
# works no matter what the current working directory is.
sys.path.insert(0, str(SHARED_DIR))
from version import VERSION  # noqa: E402

# Per OS tree: the launcher that belongs at the archive root.
ENTRY_FILES = {
    "Windows": "setup_and_run.bat",
    "MacOS": "setup_and_run.command",
}

# Directory names that are excluded wherever they appear in the tree.
EXCLUDED_DIR_NAMES = {".venv", "__pycache__"}
# File suffixes that are always excluded.
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
# Paths (relative to the OS tree, forward-slash form) excluded by prefix/exact.
EXCLUDED_PREFIXES = ("resources/logs/", "resources/bin/")
EXCLUDED_EXACT = {"resources/settings.json"}


def _is_excluded(rel: Path) -> bool:
    """True if *rel* (relative to an OS tree) must not be packaged."""
    parts = set(rel.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if rel.suffix in EXCLUDED_SUFFIXES:
        return True
    rel_posix = rel.as_posix()
    if rel_posix in EXCLUDED_EXACT:
        return True
    if any(rel_posix.startswith(p) for p in EXCLUDED_PREFIXES):
        return True
    # test-files/ is a repo-root fixture, never inside an OS tree, but guard anyway.
    if rel.parts and rel.parts[0] == "test-files":
        return True
    return False


def _package_os(os_name: str) -> Path:
    """Build dist/AudiobookTool-<os_name>-vX.Y.Z.zip and return its path."""
    tree_dir = REPO_ROOT / os_name
    if not tree_dir.is_dir():
        raise FileNotFoundError(f"Expected OS tree not found: {tree_dir}")

    entry_name = ENTRY_FILES[os_name]
    entry_file = REPO_ROOT / entry_name
    readme = REPO_ROOT / "README.md"
    for required in (entry_file, readme):
        if not required.is_file():
            raise FileNotFoundError(f"Required root file missing: {required}")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DIST_DIR / f"AudiobookTool-{os_name}-v{VERSION}.zip"
    if zip_path.exists():
        zip_path.unlink()

    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # The launcher and README sit at the archive root so they're the first
        # thing a user sees on extract.
        zf.write(readme, arcname="README.md")
        zf.write(entry_file, arcname=entry_name)

        for path in sorted(tree_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(tree_dir)
            if _is_excluded(rel):
                continue
            # Archived under "<OS>/..." so it sits beside the launcher, matching
            # the launcher's own "cd <OS>" expectation.
            zf.write(path, arcname=f"{os_name}/{rel.as_posix()}")
            file_count += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  [{os_name}] {zip_path.name}  ({file_count} files, {size_mb:.1f} MB)")
    return zip_path


def _print_checklist() -> None:
    """Echo the Briefing §13 release process so nothing is forgotten."""
    print()
    print("=" * 64)
    print(f"  Release checklist  (Audiobook Creation Tool v{VERSION})")
    print("=" * 64)
    steps = [
        "All test matrix cells PASS (Briefing section 12).",
        f"CHANGELOG [Unreleased] -> [{VERSION}] - <date> (both OS trees).",
        f"Version bumped in both OS trees (shared/version.py = {VERSION}).",
        "Zip each OS folder + root files (this script) -> dist/.",
        "Attach both zips to the GitHub Release; update README download links.",
    ]
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    print("=" * 64)
    print("  Before shipping, also clear the remaining pre-release items:")
    print("    - Debug Gate 2: full one-click install on a clean Python-3.12 box.")
    print("    - macOS matrix column on a real Mac.")
    print("    - Final visual no-console-flash confirmation on Windows.")
    print("=" * 64)


def main() -> int:
    print(f"Packaging Audiobook Creation Tool v{VERSION}")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Output:    {DIST_DIR}")
    print()
    built = [_package_os(os_name) for os_name in ("Windows", "MacOS")]
    _print_checklist()
    print()
    print(f"Done. {len(built)} archive(s) written to {DIST_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
