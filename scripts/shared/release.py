"""Developer release-packaging helper — NOT part of the running application.

Run this by hand from a dev checkout to produce the distributable zips:

    python scripts/shared/release.py

It builds two archives under ``<repo-root>/dist/``:

    dist/AudiobookTool-Windows-vX.Y.Z.zip
    dist/AudiobookTool-MacOS-vX.Y.Z.zip

Since v0.5.0 there is a single cross-platform code tree (``scripts``),
so both archives contain the same ``scripts/`` folder; they differ only in which
double-click launcher sits at the archive root (``.bat`` vs ``.command``), plus
``README.md`` and the committed ``config.toml``. All machine-specific /
regenerable artifacts (venv, caches, dev assets and runtime data — recreated on
first run) are excluded. Exactly six named Chatterbox WAV references ship from
``files/Chatterbox-Voice-Uploads/``; no other ``files/`` content ships.
The version string comes from the single
source of truth in ``version.py``.

Packaging works by **explicit scope**: the root files are a named list and
exactly one tree (``scripts/``) is walked. Nothing is ever copied wholesale and
then pruned, so a file this module does not name — the maintainer's unrelated
untracked root template beside ``config.toml``, for one — cannot leak because
somebody forgot to extend an exclusion list.

Only **committed** content ships (v0.6.6 Phase 11). Inside ``scripts/`` a file
is packaged only if git tracks it, so local-only work in a dev checkout (the
maintainer's uncommitted ``scripts/project-status.py`` used to land in both
archives) stays behind whatever its name. ``main()`` also refuses to build while
any packaged path has uncommitted changes, so an archive is always the committed
state rather than a dirty working tree. Outside a git checkout the packager
refuses rather than guessing.

**Existing archives are never replaced** (v0.6.7, audit ACT67-AUD-001). The
packager used to delete a same-version zip before writing the new one, which
once destroyed the local copies of published release assets; a failure part-way
through would have left neither the old archive nor a complete new one. Now both
destinations are checked before anything is written and the build refuses if
either is occupied. Each archive is written to a fresh staging folder inside
``dist/``, checked member by member against its source, and only then published
with a hard link, which the OS refuses if the destination appeared in the
meantime. If one platform cannot be published, the other's just-published link
is withdrawn (only when it is still this build's own file), so a run publishes
both archives or neither. To rebuild a version, move the old archives aside by
hand first.

This module must never be imported by the launcher or any tool — it is a
build-time developer utility only and depends on nothing inside the app.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

# release.py lives at <repo>/scripts/shared/release.py
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent             # <repo>/scripts
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

# Root files shipped verbatim in both archives, in the order they are written.
# ``config.toml`` is packaged byte-for-byte as committed — the packager never
# generates, edits or substitutes it, and a clean extraction reads its documented
# defaults from the archive root.
ROOT_FILES = ("README.md", "config.toml")

# CLOSED ALLOWLIST: never walk files/ or the reference directory. MP3 originals,
# extra recordings, derivatives and caches are not distributable assets.
REFERENCE_ASSETS = (
    "files/Chatterbox-Voice-Uploads/Chatterbox - Female 1.wav",
    "files/Chatterbox-Voice-Uploads/Chatterbox - Female 2.wav",
    "files/Chatterbox-Voice-Uploads/Chatterbox - Male 1.wav",
    "files/Chatterbox-Voice-Uploads/Chatterbox - Male 2.wav",
    "files/Chatterbox-Voice-Uploads/Chatterbox - Male 3.wav",
    "files/Chatterbox-Voice-Uploads/Chatterbox - Male 4.wav",
)

# Directory names that are excluded wherever they appear in the tree.
# ``.venv-qwen3`` is the optional Qwen3-TTS environment (v0.6.7 CP6): it lives at the repository root, outside the
# ``scripts/`` tree the packager walks, so it cannot be reached in the first place; it is named here too so that a
# future widening of the walk can never package a multi-gigabyte environment by accident.
EXCLUDED_DIR_NAMES = {".venv", ".venv-qwen3", "__pycache__", ".pytest_cache"}
# File suffixes that are always excluded.
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
# Exact file names that are always excluded, wherever they appear in the tree.
# Folder-metadata artifacts a real OS drops just from browsing a folder in
# Finder/Explorer -- gitignored (never committed), so they cannot be relied on
# to be absent from a real dev checkout at packaging time, the way a v0.6.5
# Phase 8 real-Mac packaging run found (scripts/.DS_Store on a checkout that
# had simply been opened in Finder).
EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db"}


class ReleaseError(RuntimeError):
    """The checkout cannot be packaged as it stands."""


def _git(*args: str) -> str:
    """Run git in the repository root and return its stdout; raise ReleaseError."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, encoding="utf-8",
        )
    except OSError as exc:  # git not installed
        raise ReleaseError(f"git is required to package a release: {exc}") from exc
    if result.returncode != 0:
        raise ReleaseError(
            f"git {' '.join(args)} failed in {REPO_ROOT}: {result.stderr.strip()}")
    return result.stdout


def _tracked_scripts() -> set[str]:
    """The repo-relative POSIX paths git tracks under ``scripts/``."""
    if not (REPO_ROOT / ".git").exists():
        raise ReleaseError(
            f"{REPO_ROOT} is not a git checkout; only committed files can be packaged.")
    return {p for p in _git("ls-files", "-z", "--", "scripts").split("\0") if p}


def _uncommitted_changes() -> list[str]:
    """Packaged paths whose working tree or index differs from HEAD.

    Untracked files are not listed: they are never packaged in the first place.
    """
    scope = ["scripts", *ROOT_FILES, *ENTRY_FILES.values(), *REFERENCE_ASSETS]
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=no", "--", *scope)
    return [entry[3:] for entry in status.split("\0") if len(entry) > 3]


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
    # Unix attributes must be declared Unix even when building on Windows;
    # otherwise an extractor may interpret the stored mode as DOS attributes.
    zi.create_system = 3
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
    if rel.name in EXCLUDED_FILE_NAMES:
        return True
    return False


def _destination(os_name: str) -> Path:
    return DIST_DIR / f"AudiobookTool-{os_name}-v{VERSION}.zip"


def _refuse_occupied(os_names) -> None:
    """Fail before anything is written if any destination already exists (file, folder or link)."""
    occupied = [p for p in (_destination(n) for n in os_names) if os.path.lexists(p)]
    if occupied:
        listed = ", ".join(p.name for p in occupied)
        raise ReleaseError(
            f"{listed} already exist(s) in {DIST_DIR}. Existing archives are never replaced; "
            "move them aside by hand to rebuild this version.")


def _write_archive(os_name: str, zip_path: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """Write the archive for *os_name* to the fresh path *zip_path*.

    Returns the ``(arcname, source)`` pairs written, in order, and the untracked
    paths left behind.
    """
    if not SCRIPTS_DIR.is_dir():
        raise FileNotFoundError(f"Expected scripts tree not found: {SCRIPTS_DIR}")

    entry_name = ENTRY_FILES[os_name]
    entry_file = REPO_ROOT / entry_name
    root_files = [REPO_ROOT / name for name in ROOT_FILES]
    for required in [entry_file, *root_files]:
        if not required.is_file():
            raise FileNotFoundError(f"Required root file missing: {required}")
    tracked = _tracked_scripts()
    tracked_assets = set(_git("ls-files", "-z", "--", *REFERENCE_ASSETS).split("\0"))
    for name in REFERENCE_ASSETS:
        if name not in tracked_assets or not (REPO_ROOT / name).is_file():
            raise ReleaseError(f"Required tracked Chatterbox reference missing: {name}")

    written: list[tuple[str, Path]] = []
    left_behind: list[str] = []
    # "x": the staging path is fresh, so an existing file there is a bug, never something to overwrite.
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as zf:
        # The launcher, README and config sit at the archive root so they're the
        # first thing a user sees on extract, and so bootstrap/config resolution
        # finds config.toml exactly where a dev checkout keeps it.
        for source, name in zip(root_files, ROOT_FILES):
            zf.write(source, arcname=name)
            written.append((name, source))
        # Force the launcher executable so a user never has to `chmod +x`.
        _write_executable(zf, entry_file, entry_name)
        written.append((entry_name, entry_file))

        for name in REFERENCE_ASSETS:
            zf.write(REPO_ROOT / name, arcname=name)
            written.append((name, REPO_ROOT / name))

        # The whole scripts/ tree (application code + requirements.txt), archived
        # under "scripts/..." beside the launcher — matching the launcher's
        # <repo_root>/scripts/shared/bootstrap.py expectation.
        for path in sorted(SCRIPTS_DIR.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT)
            if _is_excluded(rel):
                continue
            if rel.as_posix() not in tracked:
                left_behind.append(rel.as_posix())
                continue
            zf.write(path, arcname=rel.as_posix())
            written.append((rel.as_posix(), path))
    return written, left_behind


def _validate_archive(zip_path: Path, written: list[tuple[str, Path]], entry_name: str) -> None:
    """Re-read the finished archive: every member present once, in order, intact and equal to its source."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if [i.filename for i in infos] != [name for name, _ in written]:
                raise ReleaseError(f"{zip_path.name}: the member list does not match what was written")
            bad = zf.testzip()
            if bad is not None:
                raise ReleaseError(f"{zip_path.name}: member {bad} fails its CRC check")
            for info, (name, source) in zip(infos, written):
                data = source.read_bytes()
                if info.file_size != len(data) or info.CRC != zlib.crc32(data):
                    raise ReleaseError(f"{zip_path.name}: member {name} differs from its source")
            if (zf.getinfo(entry_name).external_attr >> 16) != 0o100755:
                raise ReleaseError(f"{zip_path.name}: the launcher lost its executable mode")
    except zipfile.BadZipFile as exc:
        raise ReleaseError(f"{zip_path.name} is not a readable zip: {exc}") from exc


def _publish(staged: dict[str, Path]) -> list[Path]:
    """Link every staged archive to its destination, all or nothing, never replacing anything.

    ``os.link`` fails if the destination exists, so a file created after the
    preflight is never overwritten. If a later link fails, the links this call
    already made are removed again -- only while they are still the staged file
    itself, so nothing anyone else wrote is ever deleted.
    """
    published: list[tuple[Path, Path]] = []
    try:
        for os_name, staged_path in staged.items():
            dest = _destination(os_name)
            try:
                os.link(staged_path, dest)
            except FileExistsError as exc:
                raise ReleaseError(
                    f"{dest.name} appeared in {DIST_DIR} while building; it was left untouched "
                    "and nothing was published.") from exc
            except OSError as exc:
                raise ReleaseError(
                    f"could not publish {dest.name} without replacing anything ({exc}); "
                    "dist/ must be on a drive that supports hard links (NTFS, APFS, ext4).") from exc
            published.append((dest, staged_path))
    except BaseException:
        for dest, staged_path in published:
            try:
                if os.path.samefile(dest, staged_path):
                    os.unlink(dest)
            except OSError:
                pass
        raise
    return [dest for dest, _ in published]


def _package(os_names) -> list[Path]:
    """Build, validate and publish one archive per OS into ``DIST_DIR``; return the published paths.

    Nothing in ``DIST_DIR`` is ever deleted or overwritten except this run's own
    staging folder.
    """
    os_names = list(os_names)
    _refuse_occupied(os_names)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=DIST_DIR))
    try:
        staged: dict[str, Path] = {}
        reports = []
        for os_name in os_names:
            zip_path = staging / _destination(os_name).name
            written, left_behind = _write_archive(os_name, zip_path)
            _validate_archive(zip_path, written, ENTRY_FILES[os_name])
            staged[os_name] = zip_path
            reports.append((os_name, zip_path, len(written) - len(ROOT_FILES) - 1, left_behind))
        built = _publish(staged)
    finally:
        # Best effort: a staged file is at most a second link to a published archive, so removing it loses
        # nothing, and a failure here must not hide the error that ended the build.
        try:
            for leftover in staging.iterdir():
                leftover.unlink()
            staging.rmdir()
        except OSError as exc:
            print(f"  note: could not remove the staging folder {staging.name}: {exc}")
    for os_name, zip_path, file_count, left_behind in reports:
        size_mb = _destination(os_name).stat().st_size / (1024 * 1024)
        print(f"  [{os_name}] {zip_path.name}  ({file_count} files, {size_mb:.1f} MB)")
        for rel in left_behind:
            print(f"      not packaged (untracked): {rel}")
    return built


def _package_os(os_name: str) -> Path:
    """Build dist/AudiobookTool-<os_name>-vX.Y.Z.zip and return its path; refuse if it already exists."""
    return _package([os_name])[0]


def _print_checklist() -> None:
    """Echo the Briefing release process so nothing is forgotten."""
    print()
    print("=" * 64)
    print(f"  Release checklist  (Audiobook Creation Tool v{VERSION})")
    print("=" * 64)
    steps = [
        "Required automated gates PASS; manual deferrals recorded (see Handoff).",
        f"Changelog.md records v{VERSION} publication/rebuild state truthfully.",
        f"Application identity in scripts/shared/version.py = {VERSION}.",
        "Everything committed (this script refuses uncommitted packaged paths).",
        "Build both zips (this script) -> dist/.",
        "STOP for maintainer integration/release/publication authorization.",
        "Only after publication: date the release notes and update download links.",
    ]
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    print("=" * 64)


def main() -> int:
    print(f"Packaging Audiobook Creation Tool v{VERSION}")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Output:    {DIST_DIR}")
    print()
    try:
        print(f"Source commit: {_git('rev-parse', 'HEAD').strip()}")
        dirty = _uncommitted_changes()
        if dirty:
            print("Refusing to package: these packaged paths have uncommitted changes.")
            print("Commit or discard them first, so the archives match a commit.")
            for rel in dirty:
                print(f"  {rel}")
            return 1
        built = _package(("Windows", "MacOS"))
    except ReleaseError as exc:
        print(f"Refusing to package: {exc}")
        return 1
    _print_checklist()
    print()
    print(f"Done. {len(built)} archive(s) written to {DIST_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
