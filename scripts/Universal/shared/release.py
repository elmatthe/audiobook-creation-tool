"""Developer release-packaging helper — NOT part of the running application.

Run this by hand from a dev checkout to produce the distributable zips:

    python scripts/Universal/shared/release.py

It builds two archives under ``<repo-root>/dist/``:

    dist/AudiobookTool-Windows-vX.Y.Z.zip
    dist/AudiobookTool-MacOS-vX.Y.Z.zip

Since v0.5.0 there is a single cross-platform code tree (``scripts/Universal``),
so both archives contain the same ``scripts/`` folder; they differ only in which
double-click launcher sits at the archive root (``.bat`` vs ``.command``), plus
``README.md``. All machine-specific / regenerable artifacts (venv, caches,
``files/`` dev assets and runtime data — recreated on first run) are excluded.
The version string comes from the single source of truth in ``version.py``.

This module must never be imported by the launcher or any tool — it is a
build-time developer utility only and depends on nothing inside the app.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

# release.py lives at <repo>/scripts/Universal/shared/release.py
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent.parent      # <repo>/scripts
REPO_ROOT = SCRIPTS_DIR.parent
DIST_DIR = REPO_ROOT / "dist"

# Pull the version from the single source of truth next to this file. Running a
# script makes its own directory sys.path[0], but be explicit so the import
# works no matter what the current working directory is.
sys.path.insert(0, str(SHARED_DIR))
from version import VERSION  # noqa: E402

# Per OS: the launcher that belongs at the archive root.
ENTRY_FILES = {
    "Windows": "Setup_and_Run-audiobook-creation-tool.bat",
    "MacOS": "Setup_and_Run-audiobook-creation-tool.command",
}

# Directory names that are excluded wherever they appear in the tree.
EXCLUDED_DIR_NAMES = {".venv", "__pycache__", ".pytest_cache"}
# File suffixes that are always excluded.
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}


def _write_executable(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
    """Add *src* to the archive as *arcname* with a forced 0o755 mode.

    The double-click launcher MUST be executable the instant a user extracts the
    zip. ``ZipFile.write`` only preserves whatever mode the source file happens to
    have, so a dev checkout that lost its +x bit (a clone with ``core.filemode``
    off, a plain file copy) would otherwise ship a non-runnable launcher and force
    the user to ``chmod +x``. Storing an explicit Unix mode of ``rwxr-xr-x`` makes
    packaging robust regardless of the source file's mode; macOS Archive Utility
    and ``unzip`` both honour the stored mode on extract.
    """
    zi = zipfile.ZipInfo.from_file(src, arcname)
    zi.external_attr = (0o100755 << 16)  # high 16 bits = Unix st_mode (reg file + 0755)
    zi.compress_type = zipfile.ZIP_DEFLATED
    with open(src, "rb") as fh:
        zf.writestr(zi, fh.read())


def _is_excluded(rel: Path) -> bool:
    """True if *rel* (relative to the repo root) must not be packaged."""
    parts = set(rel.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if rel.suffix in EXCLUDED_SUFFIXES:
        return True
    return False


def _package_os(os_name: str) -> Path:
    """Build dist/AudiobookTool-<os_name>-vX.Y.Z.zip and return its path."""
    if not SCRIPTS_DIR.is_dir():
        raise FileNotFoundError(f"Expected scripts tree not found: {SCRIPTS_DIR}")

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
        # Force the launcher executable so a user never has to `chmod +x`.
        _write_executable(zf, entry_file, entry_name)

        # The whole scripts/ tree (Universal code + requirements.txt), archived
        # under "scripts/..." beside the launcher — matching the launcher's
        # <repo_root>/scripts/Universal/shared/bootstrap.py expectation.
        for path in sorted(SCRIPTS_DIR.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT)
            if _is_excluded(rel):
                continue
            zf.write(path, arcname=rel.as_posix())
            file_count += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  [{os_name}] {zip_path.name}  ({file_count} files, {size_mb:.1f} MB)")
    return zip_path


def _print_checklist() -> None:
    """Echo the Briefing release process so nothing is forgotten."""
    print()
    print("=" * 64)
    print(f"  Release checklist  (Audiobook Creation Tool v{VERSION})")
    print("=" * 64)
    steps = [
        "All test matrix cells PASS (see Briefing).",
        f"CHANGELOG [Unreleased] -> [{VERSION}] - <date>.",
        f"Version bumped in scripts/Universal/shared/version.py = {VERSION}.",
        "Build both zips (this script) -> dist/.",
        "Attach both zips to the GitHub Release; update README download links.",
    ]
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
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
