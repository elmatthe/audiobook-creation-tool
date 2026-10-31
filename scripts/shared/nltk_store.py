"""nltk_store.py — the English sentence data the Edge voices' sentence splitter reads (NLTK ``punkt_tab``), kept
verified inside the app's folder (v0.7.0 portability remediation).

NLTK 3.9 splits sentences with ``tokenizers/punkt_tab/<language>/`` (four small text files for English). NLTK's own
``nltk.download`` writes them to the user's profile (``%APPDATA%\\nltk_data``), from a moving branch, without a hash, and
the old ``ensure_punkt`` called it silently at the start of every narration. Here instead:

* **One place.** ``files/runtime-data/nltk_data`` in NLTK's own layout; :func:`configure` makes it the *only* folder NLTK
  searches, so no copy in the user's profile (or ``NLTK_DATA``) is ever read, and every route reads the same files.
* **Fixed identity.** The archive is ``punkt_tab.zip`` at nltk_data commit ``4f15a3d`` (the newest change to it,
  2025-02-17), pinned by size and SHA-256 -- the same SHA-256 NLTK's own index publishes -- and each of the four English
  files is pinned again by size and SHA-256 and re-checked before every use.
* **Only with consent.** Nothing here runs by itself: first-run setup fetches it after the person starts the setup it
  is disclosed in, and otherwise the Edge route asks before the first conversion that needs it (``tts.epub2tts_gui``).
  A missing or damaged copy is reported as :class:`SentenceDataMissing` with what to do, never fetched silently.
* **Atomic and contained.** The archive is streamed to a part file inside the folder, checked, unpacked (the four
  English members only, each checked) into a staging folder and moved into place with one rename. A link anywhere below
  the app's folder on the way is refused.

Standard library only, under ``shared/``, so first-run setup (``bootstrap``) can use it before the app environment has
any packages. Run it directly to fetch or check the data of an installation:
``python scripts/shared/nltk_store.py --install|--check [--root <app folder>]``.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from typing import Callable, Mapping, Optional

SOURCE_COMMIT = "4f15a3d89eefe9748ec1c05be495d91289197155"
SOURCE_URL = ("https://raw.githubusercontent.com/nltk/nltk_data/" + SOURCE_COMMIT
              + "/packages/tokenizers/punkt_tab.zip")
ARCHIVE_NAME = "punkt_tab.zip"
ARCHIVE_SIZE = 4_319_076
ARCHIVE_SHA256 = "e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106"
#: The English model inside the archive: member name -> (size, SHA-256).
MEMBER_PREFIX = "punkt_tab/english/"
FILES: Mapping[str, tuple[int, str]] = {
    "abbrev_types.txt": (619, "92a3e070f43d9b4c5534758ca40ad7343b04e7e29bfe0c2eb658a39445a4f779"),
    "collocations.tab": (594, "8e2da1225e4dd2cc9dba261ee231ccb134859e21b46006e7f472c5ee269af0cf"),
    "ortho_context.tab": (236_303, "4bbcca25ed3d3f06c02402abf8419b9f033b8adc06e7b482eca4e45f81a5dc4c"),
    "sent_starters.txt": (241, "f3f8535483e1dba487241b764945168123bca3209a9645e59acd1225dc76edac"),
}
#: Where the English files live below the data folder (NLTK's own layout).
ENGLISH_PARTS = ("tokenizers", "punkt_tab", "english")
DOWNLOAD_TIMEOUT_S = 60
#: How the download is described to the person before they agree to it.
DOWNLOAD_SIZE_TEXT = "about 4.3 MB"
SOURCE_TEXT = "NLTK's data repository on GitHub (a fixed version, checked against its SHA-256)"

_REPARSE_POINT = 0x400
_BLOCK = 1 << 16


class SentenceDataMissing(RuntimeError):
    """The verified English sentence data is not installed (or not intact). The message says what to do."""


class SentenceDataError(RuntimeError):
    """Fetching or installing the English sentence data failed; nothing was changed. The message says why."""


class SentenceDataCancelled(SentenceDataError):
    """The fetch was cancelled; nothing was changed."""


def _default_root() -> Path:
    from shared import paths

    return paths.REPO_ROOT


def data_dir(root: Optional[Path] = None) -> Path:
    """``files/runtime-data/nltk_data`` of the installation at ``root`` (default: this one)."""
    return Path(_default_root() if root is None else root) / "files" / "runtime-data" / "nltk_data"


def english_dir(root: Optional[Path] = None) -> Path:
    return data_dir(root).joinpath(*ENGLISH_PARTS)


def _is_link(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _link_below(root: Path, path: Path) -> Optional[Path]:
    """The first component below ``root`` down to ``path`` that is a link or junction, else None."""
    root = Path(os.path.abspath(str(root)))
    path = Path(os.path.abspath(str(path)))
    walked = root
    for part in path.parts[len(root.parts):]:
        walked = walked / part
        if _is_link(walked):
            return walked
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def problem(root: Optional[Path] = None, *, file_pins: Mapping[str, tuple[int, str]] = FILES) -> str:
    """Why the installation's English sentence data cannot be used, or "" when every file is present and intact."""
    root = Path(_default_root() if root is None else root)
    folder = english_dir(root)
    link = _link_below(root, folder)
    if link is not None:
        return f"{link} is a link or junction, so the sentence data there is not used"
    if not folder.is_dir():
        return "the English sentence data is not installed"
    for name, (size, sha256) in file_pins.items():
        path = folder / name
        try:
            st = os.lstat(path)
        except OSError:
            return f"the English sentence data is incomplete ({name} is missing)"
        if not stat.S_ISREG(st.st_mode) or st.st_size != size:
            return f"the English sentence data is damaged ({name} is not the expected file)"
        try:
            if _sha256_file(path) != sha256:
                return f"the English sentence data is damaged ({name} does not match its SHA-256)"
        except OSError as exc:
            return f"the English sentence data cannot be read ({name}: {exc})"
    return ""


def is_ready(root: Optional[Path] = None) -> bool:
    return problem(root) == ""


def missing_message(detail: str) -> str:
    """What the person is told when an Edge conversion cannot start for want of the sentence data."""
    return (f"The Edge voices need the app's English sentence data, and {detail}. Nothing was converted. Press "
            f"Create again and choose Yes to download it ({DOWNLOAD_SIZE_TEXT} from {SOURCE_TEXT}); it is kept inside "
            f"this folder in files\\runtime-data\\nltk_data.")


def configure(nltk_module, root: Optional[Path] = None) -> None:
    """Make the installation's own data folder the only one NLTK searches (never the user's profile)."""
    nltk_module.data.path[:] = [str(data_dir(root))]


def require(nltk_module, root: Optional[Path] = None) -> None:
    """Point NLTK at the verified local data and prove it is intact, or raise :class:`SentenceDataMissing`.
    Never downloads anything."""
    configure(nltk_module, root)
    detail = problem(root)
    if detail:
        raise SentenceDataMissing(missing_message(detail))


def _safe_member(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return not name.startswith(("/", "\\")) and ".." not in parts and ":" not in name


def install_from_archive(archive: Path, root: Optional[Path] = None, *, archive_size: int = ARCHIVE_SIZE,
                         archive_sha256: str = ARCHIVE_SHA256,
                         file_pins: Mapping[str, tuple[int, str]] = FILES) -> None:
    """Check ``archive`` against its pins, then install its English files (each checked) with one rename.
    Raises :class:`SentenceDataError` and changes nothing when anything does not match."""
    root = Path(_default_root() if root is None else root)
    folder = data_dir(root)
    link = _link_below(root, folder)
    if link is not None:
        raise SentenceDataError(f"{link} is a link or junction; the sentence data is not installed there")
    try:
        size = os.path.getsize(archive)
        if size != archive_size or _sha256_file(Path(archive)) != archive_sha256:
            raise SentenceDataError("the downloaded sentence-data archive is not the expected file (size or "
                                    "SHA-256 differs); nothing was installed")
        with zipfile.ZipFile(archive) as bundle:
            if not all(_safe_member(name) for name in bundle.namelist()):
                raise SentenceDataError("the sentence-data archive holds an unsafe path; nothing was installed")
            contents = {}
            for name, (expected_size, expected_sha) in file_pins.items():
                data = bundle.read(MEMBER_PREFIX + name)
                if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_sha:
                    raise SentenceDataError(f"{name} in the sentence-data archive is not the expected file; "
                                            "nothing was installed")
                contents[name] = data
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SentenceDataError(f"the sentence-data archive could not be read ({exc}); nothing was installed") \
            from exc
    target = english_dir(root)
    token = secrets.token_hex(4)
    staging = folder / f".staging-{token}"
    aside = folder / f".replaced-{token}"
    try:
        staging.mkdir(parents=True)
        for name, data in contents.items():
            with open(staging / name, "xb") as handle:
                handle.write(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        if _link_below(root, target) is not None:
            raise SentenceDataError("a link appeared below the data folder; nothing was installed")
        if os.path.lexists(target):
            os.rename(target, aside)
        try:
            os.rename(staging, target)
        except OSError:
            if os.path.lexists(aside) and not os.path.lexists(target):
                os.rename(aside, target)
            raise
    except OSError as exc:
        raise SentenceDataError(f"the sentence data could not be put in place ({exc})") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(aside, ignore_errors=True)
    detail = problem(root, file_pins=file_pins)
    if detail:
        raise SentenceDataError(f"after installing, {detail}")


def download(root: Optional[Path] = None, *, opener: Optional[Callable] = None, timeout: float = DOWNLOAD_TIMEOUT_S,
             progress: Optional[Callable[[int, int], None]] = None, cancel: Optional[Callable[[], bool]] = None,
             source: str = SOURCE_URL, archive_size: int = ARCHIVE_SIZE, archive_sha256: str = ARCHIVE_SHA256,
             file_pins: Mapping[str, tuple[int, str]] = FILES) -> None:
    """Fetch the pinned archive into the data folder, check it, and install the English files. Call only after the
    person agreed. Raises :class:`SentenceDataError` (:class:`SentenceDataCancelled` when cancelled); a failure leaves
    whatever was there before exactly as it was and no part file behind."""
    import urllib.request

    root = Path(_default_root() if root is None else root)
    folder = data_dir(root)
    link = _link_below(root, folder)
    if link is not None:
        raise SentenceDataError(f"{link} is a link or junction; the sentence data is not downloaded there")
    opener = urllib.request.urlopen if opener is None else opener  # looked up now: the test suite closes this door
    part = folder / f".{ARCHIVE_NAME}.{secrets.token_hex(4)}.part"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(source, headers={"User-Agent": "AudiobookCreationTool"})
        received = 0
        digest = hashlib.sha256()
        with opener(request, timeout=timeout) as response, open(part, "xb") as handle:
            while True:
                if cancel is not None and cancel():
                    raise SentenceDataCancelled("the download was cancelled; nothing was changed")
                block = response.read(_BLOCK)
                if not block:
                    break
                received += len(block)
                if received > archive_size:
                    raise SentenceDataError("the download is larger than the expected sentence-data archive; "
                                            "nothing was installed")
                digest.update(block)
                handle.write(block)
                if progress is not None:
                    progress(received, archive_size)
        if received != archive_size or digest.hexdigest() != archive_sha256:
            raise SentenceDataError("the downloaded sentence-data archive is not the expected file (size or SHA-256 "
                                    "differs); nothing was installed")
        install_from_archive(part, root, archive_size=archive_size, archive_sha256=archive_sha256,
                             file_pins=file_pins)
    except SentenceDataError:
        raise
    except Exception as exc:  # noqa: BLE001 - a network or file failure, reported in the person's terms
        raise SentenceDataError(f"the sentence data could not be downloaded ({type(exc).__name__}: {exc}); "
                                "nothing was changed") from exc
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch or check an installation's English sentence data.")
    parser.add_argument("--root", type=Path, default=None, help="the app folder (default: this one)")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true", help=f"download it ({DOWNLOAD_SIZE_TEXT}) and install it")
    action.add_argument("--check", action="store_true", help="check the installed copy; downloads nothing")
    args = parser.parse_args(argv)
    if args.install and is_ready(args.root):
        print("The English sentence data is already installed and intact.")
        return 0
    if args.install:
        try:
            download(args.root)
        except SentenceDataError as exc:
            print(f"FAILED: {exc}")
            return 1
    detail = problem(args.root)
    print("OK: the English sentence data is installed and intact." if not detail else f"NOT READY: {detail}")
    return 0 if not detail else 1


if __name__ == "__main__":
    if str(Path(__file__).resolve().parents[1]) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
