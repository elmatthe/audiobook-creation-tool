"""Safe acquisition of the pinned portable FFmpeg build for Windows.

**What this replaces.** The old fallback fetched BtbN's ``master-latest``
archive — a URL floating on two axes, whose bytes change on every upstream
commit — with ``urlretrieve`` straight into the live ``files/bin``, no checksum
anywhere, then wrote ``ffmpeg.exe`` and ``ffprobe.exe`` into that same live
directory as two independent writes and called it success if ``ffmpeg.exe``
merely existed. An interrupted run could leave one half of one build beside one
half of another; a stale ``ffmpeg.exe`` could make a download that extracted
nothing report success; and a working pair could be destroyed by an attempt to
replace it.

**The two pins are different claims, and conflating them is how that goes
wrong.** This module owns the *source* pin: version, asset name, exact URL and
expected SHA-256, asserting only that *the bytes we downloaded are exactly the
reviewed Gyan 9.0.1 full build*. It asserts nothing about whether those
executables will run. That is the *runtime* pin, and it belongs to
``ffmpeg_health``, which proves it by executing both halves. Neither substitutes
for the other, and neither is permanent: ``ensure_ready`` still re-proves the
active pair on later launches.

The Gyan GitHub release is not immutable, so the hard-coded digest — not the URL,
not the filename, not the size — is the integrity authority. An upstream asset
replacement with different bytes fails closed, before a single member is
extracted.

Stdlib only, and importable before the venv exists, like its neighbours.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

try:  # normal application import, as ``shared.ffmpeg_portable``
    from . import ffmpeg_health
except ImportError:  # pragma: no cover - bootstrap imports this file directly
    import ffmpeg_health  # type: ignore[no-redef]

# --- Path resolution -------------------------------------------------------
# Derived from __file__ for the same reason as its neighbours: this has to work
# before the venv exists. (Keep in sync with shared/paths.py.)
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent
REPO_ROOT = SCRIPTS_DIR.parent

FILES_DIR = REPO_ROOT / "files"
RESOURCES_DIR = FILES_DIR / "runtime-data"
BIN_DIR = FILES_DIR / "bin"

# ---------------------------------------------------------------------------
#  The source pin. One authoritative set, verified against two independent
#  authorities before it was written here:
#
#  * the GyanD/codexffmpeg GitHub release for tag 9.0.1 — asset name, size
#    251427729 and digest sha256:2e8e28af…5b00;
#  * Microsoft's winget-pkgs manifest for Gyan.FFmpeg 9.0.1 — the same
#    InstallerUrl and the same InstallerSha256, and the build layout below.
#
#  Both must still agree at the start of any future version bump.
# ---------------------------------------------------------------------------
PORTABLE_FFMPEG_VERSION = "9.0.1"
PORTABLE_FFMPEG_ASSET = "ffmpeg-9.0.1-full_build.zip"
PORTABLE_FFMPEG_URL = (
    "https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/"
    "ffmpeg-9.0.1-full_build.zip"
)
PORTABLE_FFMPEG_SHA256 = (
    "2e8e28af97c2ae338ccef92e36da9b2a4cd21d0cad9dde093545606cb07f5b00"
)

#: Advisory only. A size match is not integrity — it is a cheap early reject
#: for an obviously wrong response, and the digest remains authoritative.
PORTABLE_FFMPEG_SIZE = 251427729

#: The directory the archive expands to, per the winget manifest's
#: ``ffmpeg-9.0.1-full_build\bin\ffmpeg.exe`` entries. Named rather than
#: discovered, so an archive that does not contain the build we pinned is a
#: failure instead of an invitation to hunt for any pair inside it.
PORTABLE_FFMPEG_BUILD_DIR = "ffmpeg-9.0.1-full_build"

#: Ceiling on total declared uncompressed size. The real build expands to a
#: little over 700 MB, so this leaves comfortable headroom while refusing an
#: archive that claims to expand to something absurd.
MAX_UNCOMPRESSED_BYTES = 2_000_000_000

#: And a per-member ceiling, so one enormous entry is refused on its own.
MAX_MEMBER_BYTES = 1_000_000_000

#: Streamed in modest blocks so a 251 MB download never lands in memory.
_CHUNK = 1024 * 256


class _NullLog:
    def line(self, text: str) -> None:  # noqa: D401 - trivial sink
        pass


# --------------------------------------------------------------------------- #
#  Locations
# --------------------------------------------------------------------------- #
def staging_root() -> Path:
    """Per-version staging. Repo-owned and gitignored, never the destination."""
    return RESOURCES_DIR / "ffmpeg-staging" / PORTABLE_FFMPEG_VERSION


def archive_path() -> Path:
    """The verified archive. Only ever named this once its digest matched."""
    return staging_root() / PORTABLE_FFMPEG_ASSET


def partial_path() -> Path:
    """The in-progress download. Never confusable with a verified archive."""
    return staging_root() / (PORTABLE_FFMPEG_ASSET + ".part")


def extract_root() -> Path:
    """A fresh per-attempt extraction directory, wiped before every attempt."""
    return staging_root() / "extract"


def final_dir() -> Path:
    """``files/bin/ffmpeg/<version>`` — dedicated, versioned, never files/bin."""
    return ffmpeg_health.portable_root() / PORTABLE_FFMPEG_VERSION


def final_bin_dir() -> Path:
    return final_dir() / "bin"


# --------------------------------------------------------------------------- #
#  Download
# --------------------------------------------------------------------------- #
def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_archive_available() -> bool:
    """True when a previously downloaded archive still hashes to the pin.

    Re-hashed rather than trusted by filename: a name is not evidence, and the
    whole point of the digest is that only the bytes decide.
    """
    archive = archive_path()
    if not archive.is_file():
        return False
    try:
        return _sha256_of(archive) == PORTABLE_FFMPEG_SHA256
    except OSError:
        return False


def download_archive(log=None, *, opener: Optional[Callable] = None) -> Optional[Path]:
    """Stream the pinned asset to staging and verify it. None on any failure.

    The digest is computed *as the bytes land*, and compared only at EOF, so
    nothing is ever extracted from an archive that has not been fully verified.
    The download writes to ``…​.part`` throughout: an interrupted or refused
    transfer can leave a partial file, but never one a later run could mistake
    for a verified archive.
    """
    log = log or _NullLog()
    opener = opener or urllib.request.urlopen

    if verified_archive_available():
        log.line("  Reusing the verified archive already in staging.")
        return archive_path()

    staging_root().mkdir(parents=True, exist_ok=True)
    partial = partial_path()
    partial.unlink(missing_ok=True)

    digest = hashlib.sha256()
    written = 0
    log.line(f"  Downloading {PORTABLE_FFMPEG_ASSET} "
             f"(~{PORTABLE_FFMPEG_SIZE // (1024 * 1024)} MB, one time)…")
    try:
        with opener(PORTABLE_FFMPEG_URL) as response, open(partial, "wb") as handle:
            while True:
                block = response.read(_CHUNK)
                if not block:
                    break
                digest.update(block)
                handle.write(block)
                written += len(block)
    except Exception as exc:  # network error, refusal, disk full…
        log.line(f"  ERROR downloading the FFmpeg archive: {exc}")
        partial.unlink(missing_ok=True)
        return None

    actual = digest.hexdigest()
    if actual != PORTABLE_FFMPEG_SHA256:
        # Say both, so a real upstream replacement is diagnosable rather than
        # just "it failed". Nothing is extracted, promoted or pinned.
        log.line("  ERROR: the downloaded archive is not the reviewed build.")
        log.line(f"    expected sha256 {PORTABLE_FFMPEG_SHA256}")
        log.line(f"    actual   sha256 {actual}")
        log.line(f"    ({written} bytes from {PORTABLE_FFMPEG_URL})")
        partial.unlink(missing_ok=True)
        return None

    if written != PORTABLE_FFMPEG_SIZE:
        # Cannot really happen once the digest matches; kept as a loud
        # contradiction rather than a silent one.
        log.line(f"  NOTE: size {written} differs from the recorded "
                 f"{PORTABLE_FFMPEG_SIZE}, but the digest matched.")

    archive = archive_path()
    archive.unlink(missing_ok=True)
    os.replace(partial, archive)
    log.line("  Archive verified against the pinned SHA-256.")
    return archive


# --------------------------------------------------------------------------- #
#  Extraction
# --------------------------------------------------------------------------- #
def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix mode lives in the top 16 bits of external_attr; 0xA000 is S_IFLNK.
    return (info.external_attr >> 16) & 0xF000 == 0xA000


def unsafe_member(info: zipfile.ZipInfo) -> Optional[str]:
    """Why this member must not be extracted, or None if it is fine.

    Checked against the *declared* names before anything is written, so an
    invalid entry near the end of the archive cannot leave a mostly-extracted
    tree behind for someone to mistake for a build.
    """
    name = info.filename
    if _member_is_symlink(info):
        return f"symlink entry: {name}"
    if info.file_size > MAX_MEMBER_BYTES:
        return f"member is implausibly large ({info.file_size} bytes): {name}"

    # Both separators, because an archive is free to use either and Windows
    # honours both. Normalise before judging.
    unified = name.replace("\\", "/")
    if unified.startswith("/"):
        return f"absolute path: {name}"
    # C:/…, \\?\…, and UNC \\server\share all begin with a drive or a root.
    if len(unified) >= 2 and unified[1] == ":":
        return f"drive-absolute path: {name}"
    if unified.startswith("//"):
        return f"UNC path: {name}"
    if any(part == ".." for part in unified.split("/")):
        return f"parent-directory traversal: {name}"
    return None


def validate_archive(zf: zipfile.ZipFile) -> Optional[str]:
    """Vet the whole member set. Returns an error string, or None if safe."""
    total = 0
    for info in zf.infolist():
        problem = unsafe_member(info)
        if problem is not None:
            return problem
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            return (f"archive expands to more than "
                    f"{MAX_UNCOMPRESSED_BYTES} bytes")
    return None


def _escapes(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([root.resolve(), target.resolve()]) != str(root.resolve())
    except (OSError, ValueError):
        return True


def extract_archive(archive: Path, log=None) -> Optional[Path]:
    """Extract into a fresh per-attempt directory. Returns the build dir.

    A previous attempt's tree is removed first: merging two extractions is how
    a half-written build from one run becomes indistinguishable from a complete
    one in the next.
    """
    log = log or _NullLog()
    destination = extract_root()
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as zf:
            problem = validate_archive(zf)
            if problem is not None:
                log.line(f"  ERROR: refusing the archive — {problem}.")
                shutil.rmtree(destination, ignore_errors=True)
                return None
            zf.extractall(destination)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        log.line(f"  ERROR extracting the FFmpeg archive: {exc}")
        shutil.rmtree(destination, ignore_errors=True)
        return None

    build = destination / PORTABLE_FFMPEG_BUILD_DIR
    if _escapes(destination, build) or not build.is_dir():
        log.line(f"  ERROR: the archive does not contain "
                 f"{PORTABLE_FFMPEG_BUILD_DIR}/.")
        shutil.rmtree(destination, ignore_errors=True)
        return None
    return build


def staged_pair(build: Path):
    """The sibling pair inside an extracted build, or None.

    ``pair_in`` is the sibling rule, reused rather than restated: both halves
    from one directory, or nothing. One executable from the archive and another
    from somewhere else is exactly what this whole design forbids.
    """
    return ffmpeg_health.pair_in(build / "bin")


# --------------------------------------------------------------------------- #
#  Promotion
# --------------------------------------------------------------------------- #
def _unusable_final_aside() -> Path:
    return final_dir().with_name(final_dir().name + ".unusable")


def promote(build: Path, log=None, *, destination: Optional[Path] = None) -> Optional[Path]:
    """Move the complete build into its versioned home. One rename.

    The whole directory moves at once, into a path that did not exist a moment
    earlier, on the same volume by construction — staging and destination are
    both under ``files/``. Nothing writes ``ffmpeg.exe`` and then ``ffprobe.exe``
    as two separate steps, because that is precisely how an interruption used to
    leave one half of one build beside one half of another.

    **An occupied destination is repaired, not surrendered to.** Refusing
    outright was fail-closed but not retryable: an incomplete or non-running
    ``9.0.1`` directory blocked every future attempt forever, and the only way
    out was for someone to delete it by hand — which is exactly the recovery
    this whole drop exists to remove. The caller only reaches here once a fresh
    candidate has been hash-verified, safely extracted and **proved**, so the
    occupant is known to be the worse of the two. It is moved aside rather than
    deleted, and restored if the rename fails, so a failed repair leaves the
    machine as it found it.
    """
    log = log or _NullLog()
    destination = final_dir() if destination is None else destination
    destination.parent.mkdir(parents=True, exist_ok=True)

    aside: Optional[Path] = None
    if destination.exists():
        aside = destination.with_name(destination.name + ".unusable")
        shutil.rmtree(aside, ignore_errors=True)
        try:
            os.replace(destination, aside)
            log.line(f"  Setting aside the unusable build at {destination}.")
        except OSError as exc:
            log.line(f"  ERROR clearing the previous build directory: {exc}")
            return None

    try:
        os.replace(build, destination)
    except OSError as exc:
        log.line(f"  ERROR installing the FFmpeg build: {exc}")
        if aside is not None:
            try:
                os.replace(aside, destination)
                log.line("  Put the previous build directory back.")
            except OSError:
                log.line("  [!!] Could not put the previous build directory back; "
                         f"it is at {aside}.")
        return None

    if aside is not None:
        shutil.rmtree(aside, ignore_errors=True)
    log.line(f"  Installed FFmpeg {destination.name} into {destination}.")
    return destination


def adopt_existing_final(log=None, *, runner=None):
    """Prove and pin an already-promoted build. Returns an ``Adoption``.

    The interruption this exists for: the rename succeeded and the process died
    before the pair was proved and pinned. A directory on disk is evidence that
    a promotion *happened*, never evidence that what it contains runs — the same
    distinction the venv transaction had to learn. So the pair is re-proved from
    the final absolute paths, and only a real proof pins it.

    The result distinguishes three outcomes the caller must treat differently:
    *pinned* (use it), *not proved* (the directory is in the way and may be
    repaired), and *proved but not persisted* (the files are good, the disk is
    not — leave them exactly where they are for the next attempt).
    """
    log = log or _NullLog()
    if not final_dir().is_dir():
        return ffmpeg_health.Adoption(ffmpeg_health.ADOPT_NOT_PROVED,
                                      detail="no installed build")
    pair = ffmpeg_health.pair_in(final_bin_dir())
    if pair is None:
        log.line(f"  {final_dir()} exists but has no ffmpeg + ffprobe pair.")
        return ffmpeg_health.Adoption(ffmpeg_health.ADOPT_NOT_PROVED,
                                      detail="no ffmpeg + ffprobe pair")
    return ffmpeg_health.adopt_pair(pair, log, runner=runner)


# --------------------------------------------------------------------------- #
#  The whole acquisition
# --------------------------------------------------------------------------- #
def acquire(log=None, *, opener: Optional[Callable] = None, runner=None):
    """Download, verify, extract, prove, promote, prove again, pin.

    Returns the pinned pair, or None. Every failure before the final pin leaves
    whatever was already pinned exactly as it was: a replacement that cannot be
    proved costs the attempt and nothing else.
    """
    log = log or _NullLog()

    # An interrupted previous run may already have promoted a usable build.
    adopted = adopt_existing_final(log, runner=runner)
    if adopted.pinned:
        log.line("  A previously installed build was proved and pinned.")
        return adopted.pair
    if adopted.proved:
        # It runs; only the record failed. Replacing perfectly good binaries
        # because a disk write failed would be the wrong repair entirely, and
        # the next run can adopt them once writing works again.
        log.line("  The installed build runs but could not be recorded as the "
                 "active pair. Leaving it in place to try again.")
        return None

    archive = download_archive(log, opener=opener)
    if archive is None:
        return None

    build = extract_archive(archive, log)
    if build is None:
        return None

    pair = staged_pair(build)
    if pair is None:
        log.line("  ERROR: the extracted build has no ffmpeg + ffprobe pair "
                 "in its bin directory.")
        return None

    # Prove before promoting. This is where a Windows application-control
    # refusal surfaces — on files that have not yet replaced anything.
    proof = ffmpeg_health.prove_pair(pair, runner=runner)
    if not proof.ok:
        log.line(f"  ERROR: the downloaded FFmpeg does not run here "
                 f"({proof.failed}): {proof.detail}")
        return None

    promoted = promote(build, log)
    if promoted is None:
        return None

    final_pair = ffmpeg_health.pair_in(final_bin_dir())
    if final_pair is None:
        log.line("  ERROR: the installed build has no ffmpeg + ffprobe pair.")
        return None

    # Proved again at the paths that will actually be used and recorded. The
    # staging proof was about different absolute paths.
    adopted = ffmpeg_health.adopt_pair(final_pair, log, runner=runner)
    if adopted.pinned:
        return adopted.pair
    # Promoted and proved, but not recorded. The build stays where it is: it is
    # good, and the next run adopts it without downloading anything again.
    return None


def cleanup_staging() -> None:
    """Drop staging once a build is installed and pinned. Never the build."""
    shutil.rmtree(staging_root(), ignore_errors=True)


# =========================================================================== #
#  macOS (Apple Silicon): the app's own FFmpeg (v0.8.x P1A, owner decision D3)
#
#  The source is a Martin Riedl release build at its timestamped build path
#  (never a "latest" redirect): two ZIPs, ffmpeg.zip and ffprobe.zip, each one
#  executable. Plan section 11.1 requires eight proofs on the actual bytes
#  before a build is ADOPTED; acquisition repeats proofs 1-7 against the
#  recorded values on every install and repair:
#
#    1 download over HTTPS (urllib sets no quarantine flag) into staging;
#    2 size + SHA-256 of each ZIP, computed from the bytes received;
#    3 safe extraction: exactly the one expected regular file per ZIP, then
#      the extracted program's own size + SHA-256;
#    4 architecture: arm64 only, read from the Mach-O header (lipo is a
#      developer-tool shim on macOS and is never run);
#    5 signature: codesign --verify --strict, and the signing authority and
#      Team ID recorded for the build (a re-signed binary is refused);
#    6 linkage: only /usr/lib and /System/Library, read from the header;
#    7 execution: both halves run, -version names the version, aac_at decodes
#      and libmp3lame encodes.
#
#  Proof 8 (a real xHE-AAC audiobook decoded by aac_at agrees with Apple's own
#  decode, owner listening, the Converter journey) is not repeatable at run
#  time; it is what adoption rests on.
# =========================================================================== #
from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class MacFile:
    zip_name: str          # e.g. "ffmpeg.zip"
    zip_size: int
    zip_sha256: str
    member: str            # the one member it must contain
    binary_size: int
    binary_sha256: str


@_dataclass(frozen=True)
class MacBuild:
    version: str
    build_path: str
    base_url: str
    ffmpeg: MacFile
    ffprobe: MacFile
    signing_authority: str
    team_id: str
    adopted: bool          # False: proofs 1-7 recorded, adoption NOT approved
    status: str

    @property
    def files(self) -> tuple[MacFile, MacFile]:
        return (self.ffmpeg, self.ffprobe)

    def url(self, name: str) -> str:
        return f"{self.base_url}/{self.build_path}/{name}"


#: The Riedl 9.0.1 arm64 release build, evaluated in P1A on 2026-11-15. Every value below was computed by ACT from the
#: bytes it downloaded (the ZIP digests also equal Riedl's published .sha256 files) or read from those binaries; none
#: was copied from a page. Proofs 1-7 PASSED. Proof 8 did NOT pass as specified: the aac_at decode of the owner's real
#: xHE-AAC audiobook is bit-identical to Apple's afconvert decode for every sample Apple produces, but it carries 6,810
#: further frames of digital silence at the end (FFmpeg does not apply the end trim with aac_at), which exceeds the
#: one-AAC-frame (1,024) sample-count tolerance; the owner's listening check and the Converter journey are pending.
#: So it is a CANDIDATE, not an adopted pin: :func:`acquire_macos` refuses it unless a qualification caller passes it
#: explicitly. Adoption is the owner's D3 decision (Decisions, 2026-11-15).
MACOS_RIEDL_9_0_1_CANDIDATE = MacBuild(
    version="9.0.1",
    build_path="1787073674_9.0.1",
    base_url="https://ffmpeg.martin-riedl.de/download/macos/arm64",
    ffmpeg=MacFile("ffmpeg.zip", 28447413, "8287a1b2229e05eb41859f073e18e6c52c60a778f2f5e6881070fe51b79407fe",
                   "ffmpeg", 66334032, "393e4c395020a1cb7cbd77fbe00599ce69d1c6466fee0dbd59d13f86a81a1611"),
    ffprobe=MacFile("ffprobe.zip", 28370930, "102a26b8940a053298d9929bfaae71e4b6ef65ba5f19a99a88c433108560741a",
                    "ffprobe", 66159232, "7abc49fb2bdf2204f018e76dc6e0a8ae7643313bae09a9fa43e7eb12442271bc"),
    signing_authority="Developer ID Application: Martin Riedl (KU3N25YGLU)",
    team_id="KU3N25YGLU",
    adopted=False,
    status="candidate: proofs 1-7 passed; proof 8 sample count outside tolerance; owner listening pending (D3)",
)

#: The adopted macOS build: None until the owner accepts one under D3. With None, a Mac gets no FFmpeg from the app
#: and the audio tools say so (limited mode); nothing unqualified is installed.
MACOS_FFMPEG_PIN: Optional[MacBuild] = None

#: Ceiling for one ZIP member (the real programs are about 66 MB).
MAC_MAX_MEMBER_BYTES = 400_000_000
_CODESIGN = "/usr/bin/codesign"
#: The build server refuses Python's default ``Python-urllib`` user agent (HTTP 403, measured 2026-11-15); a neutral
#: product name is sent instead. Nothing about the person or the computer is sent.
MAC_DOWNLOAD_USER_AGENT = "AudiobookCreationTool"
#: Seconds a stalled connection may stay silent before the download fails (and is retried by a later repair).
MAC_DOWNLOAD_SOCKET_TIMEOUT_S = 60


def _mac_open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": MAC_DOWNLOAD_USER_AGENT})
    return urllib.request.urlopen(request, timeout=MAC_DOWNLOAD_SOCKET_TIMEOUT_S)


def macos_staging_root(build: MacBuild) -> Path:
    """Repo-owned staging, separate from the Windows staging so a folder copied from Windows is never mixed in."""
    return RESOURCES_DIR / "ffmpeg-staging" / f"macos-{build.version}"


def _mac_zip_path(build: MacBuild, file: MacFile) -> Path:
    return macos_staging_root(build) / file.zip_name


def _mac_download(build: MacBuild, file: MacFile, log, opener) -> Optional[Path]:
    """Proofs 1 and 2 for one ZIP: stream to ``.part`` hashing as the bytes land; only an exact size and digest are
    renamed to the verified name. A previously verified ZIP is re-hashed, never trusted by name."""
    target = _mac_zip_path(build, file)
    if target.is_file():
        try:
            if target.stat().st_size == file.zip_size and _sha256_of(target) == file.zip_sha256:
                log.line(f"  Reusing the verified {file.zip_name} already in staging.")
                return target
        except OSError:
            pass
        target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    url = build.url(file.zip_name)
    log.line(f"  Downloading {file.zip_name} of FFmpeg {build.version} (~{file.zip_size // (1024 * 1024)} MB)…")
    try:
        with opener(url) as response, open(partial, "wb") as handle:
            while True:
                block = response.read(_CHUNK)
                if not block:
                    break
                written += len(block)
                if written > file.zip_size:
                    raise OSError(f"more than the expected {file.zip_size} bytes")
                digest.update(block)
                handle.write(block)
    except Exception as exc:  # network error, refusal, disk full, oversize
        log.line(f"  ERROR downloading {file.zip_name}: {exc}")
        partial.unlink(missing_ok=True)
        return None
    actual = digest.hexdigest()
    if written != file.zip_size or actual != file.zip_sha256:
        log.line(f"  ERROR: {file.zip_name} is not the recorded build ({written} bytes, sha256 {actual}; expected "
                 f"{file.zip_size} bytes, sha256 {file.zip_sha256}). It was deleted; nothing was installed.")
        partial.unlink(missing_ok=True)
        return None
    os.replace(partial, target)
    return target


def _mac_unsafe_member(info: zipfile.ZipInfo, expected: str) -> Optional[str]:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = mode & 0xF000
    if info.filename != expected:
        return f"unexpected member {info.filename!r} (only {expected!r} is allowed)"
    if kind not in (0, 0x8000):
        return f"{info.filename} is not a regular file"
    if mode & 0o6000:
        return f"{info.filename} carries a set-user-ID or set-group-ID bit"
    if info.file_size > MAC_MAX_MEMBER_BYTES:
        return f"{info.filename} is implausibly large ({info.file_size} bytes)"
    return None


def _mac_extract(archive: Path, file: MacFile, destination: Path, log) -> bool:
    """Proof 3 for one ZIP: exactly one expected regular member, extracted to ``destination/bin``, mode 0755, then
    the program's own size and SHA-256."""
    try:
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            if len(members) != 1:
                log.line(f"  ERROR: {archive.name} has {len(members)} members; exactly one ({file.member}) is allowed.")
                return False
            problem = _mac_unsafe_member(members[0], file.member)
            if problem is not None:
                log.line(f"  ERROR: refusing {archive.name}: {problem}.")
                return False
            out = destination / "bin" / file.member
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(members[0]) as source, open(out, "wb") as sink:
                shutil.copyfileobj(source, sink, _CHUNK)
            os.chmod(out, 0o755)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        log.line(f"  ERROR extracting {archive.name}: {exc}")
        return False
    if out.stat().st_size != file.binary_size or _sha256_of(out) != file.binary_sha256:
        log.line(f"  ERROR: the extracted {file.member} is not the recorded program.")
        return False
    return True


def _codesign_identity(binary: Path, owner) -> tuple[bool, str, str, str]:
    """Proof 5: ``(verified, authority, team id, detail)``. codesign is a system program (not a developer-tool shim)
    and runs inside the owner's guardian group."""
    try:
        verify = owner.run_external([_CODESIGN, "--verify", "--strict", "--verbose=2", str(binary)], timeout=120,
                                    label="codesign")
        if verify.returncode != 0:
            return False, "", "", (verify.stderr or verify.stdout or "").strip()[:300]
        info = owner.run_external([_CODESIGN, "-dv", "--verbose=4", str(binary)], timeout=120, label="codesign")
    except Exception as exc:  # noqa: BLE001 - containment unavailable, timeout, missing tool
        return False, "", "", f"{type(exc).__name__}: {exc}"
    authority = team = ""
    for line in (info.stderr or "").splitlines():
        if line.startswith("Authority=") and not authority:
            authority = line.partition("=")[2].strip()
        elif line.startswith("TeamIdentifier="):
            team = line.partition("=")[2].strip()
    return info.returncode == 0, authority, team, ""


def verify_macos_build(build: MacBuild, bin_dir: Path, log=None, *, owner=None, runner=None) -> Optional[str]:
    """Proofs 4-7 on an extracted build in ``bin_dir``. None when every proof passes, else why not."""
    try:
        from . import macho
    except ImportError:  # pragma: no cover - bootstrap imports this file directly
        import macho  # type: ignore[no-redef]
    if owner is None:
        try:
            from . import child_ownership
        except ImportError:  # pragma: no cover
            import child_ownership  # type: ignore[no-redef]
        owner = child_ownership.owner()
    log = log or _NullLog()
    for file in build.files:
        binary = bin_dir / file.member
        archs = macho.architectures(binary)
        if archs != ("arm64",):
            return f"{file.member}: architecture {archs or 'not Mach-O'}, not arm64 only (proof 4)"
        ok, authority, team, detail = _codesign_identity(binary, owner)
        if not ok:
            return f"{file.member}: the code signature does not verify (proof 5): {detail}"
        if authority != build.signing_authority or team != build.team_id:
            return (f"{file.member}: signed by {authority!r} (team {team!r}), not the recorded "
                    f"{build.signing_authority!r} (proof 5)")
        foreign = macho.foreign_dependencies(binary)
        if foreign is None or foreign:
            return f"{file.member}: links outside the system libraries (proof 6): {foreign}"
    pair = ffmpeg_health.pair_in(bin_dir)
    if pair is None:
        return "no ffmpeg + ffprobe pair after extraction"
    proof = ffmpeg_health.prove_pair(pair, runner=runner)
    if not proof.ok:
        return f"{proof.failed} does not run here (proof 7): {proof.detail}"
    if runner is None:
        if f"version {build.version}" not in (proof.version_text or ""):
            return f"ffmpeg reports {proof.version_text!r}, not version {build.version} (proof 7)"
        if not ffmpeg_health.has_codec(pair.ffmpeg.as_path, "encoders", "libmp3lame"):
            return "ffmpeg has no libmp3lame encoder (proof 7)"
    log.line(f"  FFmpeg {build.version}: arm64, signed by {build.signing_authority}, system libraries only, "
             f"aac_at and libmp3lame present.")
    return None


def acquire_macos(log=None, *, build: Optional[MacBuild] = None, opener: Optional[Callable] = None, runner=None,
                  owner=None):
    """Download, verify, extract, prove, promote, prove again, pin -- the macOS counterpart of :func:`acquire`.

    ``build`` defaults to the adopted :data:`MACOS_FFMPEG_PIN`; with none adopted this refuses and installs nothing.
    Qualification code passes a candidate explicitly. Returns the pinned pair, or None. Every failure before the final
    pin leaves whatever was pinned exactly as it was.
    """
    log = log or _NullLog()
    opener = opener or _mac_open
    build = build or MACOS_FFMPEG_PIN
    if build is None:
        log.line("  No FFmpeg build for macOS has been approved for this version of the app yet, so none is "
                 "downloaded. The audio tools that need FFmpeg stay unavailable until one is.")
        return None
    if final_dir_for(build).is_dir():
        problem = verify_macos_build(build, final_dir_for(build) / "bin", log, owner=owner, runner=runner)
        if problem is None:
            adopted = ffmpeg_health.adopt_pair(ffmpeg_health.pair_in(final_dir_for(build) / "bin"), log,
                                               runner=runner)
            if adopted.pinned:
                log.line("  The installed FFmpeg build was proved again and pinned.")
                return adopted.pair
            if adopted.proved:
                return None  # runs; only the record failed -- keep it for the next attempt
        else:
            log.line(f"  The installed build at {final_dir_for(build)} is not usable: {problem}")
    stage = macos_staging_root(build) / f".act-stage-ffmpeg-{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        for file in build.files:
            archive = _mac_download(build, file, log, opener)
            if archive is None or not _mac_extract(archive, file, stage, log):
                return None
        problem = verify_macos_build(build, stage / "bin", log, owner=owner, runner=runner)
        if problem is not None:
            log.line(f"  ERROR: the downloaded FFmpeg was refused: {problem}")
            return None
        if promote(stage, log, destination=final_dir_for(build)) is None:
            return None
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    final_pair = ffmpeg_health.pair_in(final_dir_for(build) / "bin")
    if final_pair is None:
        log.line("  ERROR: the installed build has no ffmpeg + ffprobe pair.")
        return None
    adopted = ffmpeg_health.adopt_pair(final_pair, log, runner=runner)
    if adopted.pinned:
        for file in build.files:
            _mac_zip_path(build, file).unlink(missing_ok=True)
        return adopted.pair
    return None


def final_dir_for(build: MacBuild) -> Path:
    """``files/bin/ffmpeg/<version>`` for a macOS build (the same versioned home as Windows)."""
    return ffmpeg_health.portable_root() / build.version


def recover_macos_staging(build: MacBuild) -> list[Path]:
    """Remove this module's own leftovers of interrupted macOS acquisitions: ``.act-stage-ffmpeg-<pid>`` folders
    whose pid is not running and ``.part`` downloads. Only inside the build's staging folder. Returns what was
    removed."""
    root = macos_staging_root(build)
    removed: list[Path] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return removed
    for entry in entries:
        name = entry.name
        if name.startswith(".act-stage-ffmpeg-"):
            try:
                pid = int(name.rsplit("-", 1)[1])
            except ValueError:
                continue
            if pid != os.getpid() and _pid_alive(pid):
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
        elif name.endswith(".zip.part") and entry.is_file():
            entry.unlink(missing_ok=True)
            removed.append(entry)
    return removed


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
