"""Proving one coherent ffmpeg + ffprobe pair, and remembering which one.

**Why this module exists.** v0.6.2 Plan 5 Phase 15's Windows manual matrix was
blocked before a single book converted. The machine had two FFmpeg
installations: an older one at ``C:\\ffmpeg`` that Windows Smart App Control
refuses to execute (``VerifiedAndReputableDesktop``, policy
``{0283ac0f-fff1-49ae-ada1-8a933130cad6}``; ``WinError 4551`` for ffprobe and
``0xC0E90002`` for ffmpeg's DLL load), and a stable WinGet ``Gyan.FFmpeg`` build
that runs perfectly. ``C:\\ffmpeg\\bin`` came first on PATH, so that is what the
application selected -- and ``have_ffmpeg()`` said yes, because the old contract
was *"FFmpeg is available if a path can be found"*. Setup said ready, the GUI
said "FFmpeg detected", and the first thing that ever actually **ran** ffprobe
was the preflight of a real conversion, in front of the user.

The replacement contract is:

    FFmpeg capability exists only through one coherent ffmpeg + ffprobe pair
    that setup or repair has established as usable.

Four things follow from it, and they are the whole design:

**Pairs, not binaries.** ffmpeg and ffprobe are discovered together as siblings
of one installation directory. Independently resolving each one is how a run
could get ffmpeg from a working build and ffprobe from a blocked one -- two
different answers to "which FFmpeg is this?" -- so it is not possible here.

**Execution, not existence.** A candidate is proven by running ``-version`` on
*both* halves, bounded, through the shared no-window wrappers. Resolving a path
proves nothing: every binary in this incident resolved perfectly.

**One proven pair, remembered.** The winner is pinned in a small local state
file. Runtime consults that rather than re-deriving an answer from PATH order,
so a blocked directory that happens to sort first can never win again.

**Never re-poke a known-bad candidate.** Attempting to execute a blocked binary
is itself what raises the Windows Security toast, so every candidate that failed
is recorded with its identity and skipped on later repairs. The user sees that
notification at most once per broken installation, during setup -- not
mid-audiobook.

Steady-state validation is deliberately cheap: path, size and mtime, no hashing,
because the pinned ffmpeg here is 222 MB and a launch may not spend a second on
it. The SHA-256 is recorded as durable evidence and re-derived on repair. What
identity cannot detect is a pair that was fine yesterday and is refused today --
nothing about the bytes changes when a policy does -- so :func:`ensure_ready`
re-proves the *pinned pair only* on each launch. That is two bounded ``-version``
calls of a known-good pair, and it is what stops the app presenting itself as
ready when it is no longer able to decode anything.

Stdlib only, and free of intra-package imports beyond the subprocess wrappers,
because ``bootstrap.py`` imports this file directly in the fragile pre-venv
environment where ``shared`` is not an importable package.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Optional

try:  # normal application import, as ``shared.ffmpeg_health``
    from . import subprocess_utils as _sp
except ImportError:  # pragma: no cover - bootstrap imports this file directly
    import subprocess_utils as _sp  # type: ignore[no-redef]

# --- Path resolution -------------------------------------------------------
# Derived from __file__ rather than imported from shared.paths, for the same
# reason bootstrap.py does it: this module has to work before the venv exists.
# (Keep in sync with shared/paths.py.)
_THIS = Path(__file__).resolve()
SHARED_DIR = _THIS.parent
SCRIPTS_DIR = SHARED_DIR.parent
REPO_ROOT = SCRIPTS_DIR.parent.parent

FILES_DIR = REPO_ROOT / "files"
RESOURCES_DIR = FILES_DIR / "runtime-data"
BIN_DIR = FILES_DIR / "bin"

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WINDOWS else ""

#: Where the proven pair is remembered. Local, disposable, never tracked --
#: ``files/runtime-data/`` is already gitignored in full. Deleting it costs one
#: re-proof, which is why nothing here treats a missing file as an error.
HEALTH_STATE_NAME = "ffmpeg-state.json"

#: Bumped whenever what counts as *proven* changes, so a state written by an
#: older contract is re-established rather than trusted.
PROOF_VERSION = 1

#: A healthy ``-version`` answers in milliseconds; this only has to be short
#: enough that a hung binary cannot hold the GUI shut.
PROBE_TIMEOUT = 20.0

#: Kept short on purpose: this text can reach a log and, trimmed further, a
#: user-facing status line.
MAX_DETAIL = 300


def state_path() -> Path:
    return RESOURCES_DIR / HEALTH_STATE_NAME


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Binary:
    """One executable, identified well enough to notice it changed.

    ``sha256`` is durable evidence recorded when the pair was proven; it is
    **not** what a launch compares, because hashing a 222 MB static build on
    every start would be a visible cost for no extra safety that ``size`` plus
    ``mtime_ns`` does not already give against accidental change.
    """

    path: str
    size: int = -1
    mtime_ns: int = -1
    sha256: str = ""

    @property
    def as_path(self) -> Path:
        return Path(self.path)

    def identity(self) -> tuple:
        """What a cheap comparison uses. Deliberately excludes the hash."""
        return (os.path.normcase(self.path), self.size, self.mtime_ns)

    def still_matches(self) -> bool:
        current = describe(self.as_path)
        return current is not None and current.identity() == self.identity()


def describe(path, *, digest: bool = False) -> Optional[Binary]:
    """Identify an executable, or ``None`` when it cannot be read at all."""
    try:
        resolved = Path(path).resolve()
        info = resolved.stat()
    except OSError:
        return None
    if not resolved.is_file():
        return None
    return Binary(
        path=str(resolved),
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        sha256=sha256_of(resolved) if digest else "",
    )


def sha256_of(path) -> str:
    """SHA-256 of a file, or ``""`` if it cannot be read.

    Streamed, because these binaries can be hundreds of megabytes.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


@dataclass(frozen=True)
class Pair:
    """One coherent installation: both halves, from one directory."""

    ffmpeg: Binary
    ffprobe: Binary
    #: Where this candidate came from, for the setup log only.
    origin: str = ""
    #: First line of ``ffmpeg -version``, recorded when proven.
    version_text: str = ""
    proven_at: str = ""

    @property
    def directory(self) -> Path:
        return self.ffmpeg.as_path.parent

    def is_coherent(self) -> bool:
        """Both halves really are siblings of one installation directory."""
        return (os.path.normcase(str(self.ffmpeg.as_path.parent))
                == os.path.normcase(str(self.ffprobe.as_path.parent)))

    def still_matches(self) -> bool:
        return self.ffmpeg.still_matches() and self.ffprobe.still_matches()


@dataclass(frozen=True)
class Proof:
    """The outcome of actually running a candidate pair."""

    ok: bool
    detail: str = ""
    version_text: str = ""
    #: Which half failed, when one did. Purely for the log.
    failed: str = ""


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _winget_package_dirs() -> list[Path]:
    """Gyan.FFmpeg WinGet installs, newest-looking last-resort ordering.

    Globbed rather than hard-coded: a ``winget upgrade`` changes the versioned
    folder name (``ffmpeg-9.0-full_build`` today), and pinning today's string
    would break silently at the next upgrade -- which is precisely the class of
    failure this module exists to stop.
    """
    if not IS_WINDOWS:
        return []
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    root = Path(local) / "Microsoft" / "WinGet" / "Packages"
    try:
        packages = sorted(root.glob("Gyan.FFmpeg*"))
    except OSError:
        return []
    found: list[Path] = []
    for package in packages:
        try:
            found.extend(sorted(package.glob("ffmpeg-*/bin")))
        except OSError:
            continue
    # Later-sorting build directories are the newer ones, and a newer build is
    # the better default when nothing else distinguishes them.
    return list(reversed(found))


#: Repo-local portable installs live under ``files/bin/ffmpeg/<version>/bin``.
#: A dedicated subtree, not ``files/bin`` itself, so the generic bin directory
#: is never owned or replaced by one dependency.
PORTABLE_ROOT_NAME = "ffmpeg"


def portable_root() -> Path:
    return BIN_DIR / PORTABLE_ROOT_NAME


def _portable_dirs() -> list[Path]:
    """Repo-local versioned portable builds, newest-looking first.

    Bounded on purpose: exactly one level of version directories under
    ``files/bin/ffmpeg``, each contributing only its own ``bin``. It never
    recurses into ``files/bin`` generally and never walks a drive — enumeration
    is not discovery, and nothing here executes anything. Sorted for a
    deterministic order, reversed so a newer version wins a tie.
    """
    try:
        versions = sorted(p for p in portable_root().iterdir() if p.is_dir())
    except OSError:
        return []
    return [v / "bin" for v in reversed(versions) if (v / "bin").is_dir()]


def _brew_dirs() -> list[Path]:
    return [Path(p) for p in ("/opt/homebrew/bin", "/usr/local/bin")] if IS_MAC else []


def _path_dirs() -> list[Path]:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    return [Path(entry) for entry in entries if entry.strip()]


def candidate_directories() -> list[Path]:
    """Every directory that might hold a pair, in preference order, deduped.

    ``files/bin`` first because a bundled build is the one setup controls; then
    PATH in its own order; then the package locations a normal install uses even
    when it never reached PATH -- which is a real case, because a fresh
    ``winget install`` does not update the PATH of an already-running process.
    """
    ordered = [BIN_DIR, *_portable_dirs(), *_path_dirs(),
               *_winget_package_dirs(), *_brew_dirs()]
    seen: set[str] = set()
    unique: list[Path] = []
    for directory in ordered:
        key = os.path.normcase(str(directory))
        if key in seen:
            continue
        seen.add(key)
        unique.append(directory)
    return unique


def pair_in(directory) -> Optional[Pair]:
    """A coherent pair from one directory, or ``None`` if it is not complete.

    A directory holding only ffmpeg -- or only ffprobe -- yields nothing at all.
    Half an installation is not a candidate, because the missing half would then
    be filled in from somewhere else.
    """
    directory = Path(directory)
    ffmpeg = describe(directory / f"ffmpeg{EXE}")
    ffprobe = describe(directory / f"ffprobe{EXE}")
    if ffmpeg is None or ffprobe is None:
        return None
    return Pair(ffmpeg=ffmpeg, ffprobe=ffprobe, origin=str(directory))


def discover_pairs() -> list[Pair]:
    """Every coherent candidate pair on this machine, in preference order."""
    found: list[Pair] = []
    seen: set[str] = set()
    for directory in candidate_directories():
        pair = pair_in(directory)
        if pair is None:
            continue
        key = os.path.normcase(str(pair.directory))
        if key in seen:
            continue
        seen.add(key)
        found.append(pair)
    return found


# --------------------------------------------------------------------------- #
# Proof
# --------------------------------------------------------------------------- #


def _run_version(executable) -> tuple[bool, str]:
    """Run ``<exe> -version`` once, bounded, hidden. Never raises.

    Routed through :mod:`shared.subprocess_utils` so no console window flashes
    under ``pythonw.exe`` -- the same wrapper every other binary call uses.
    """
    try:
        completed = _sp.run(
            [str(executable), "-version"],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        # The Smart App Control refusal arrives here, as WinError 4551 at
        # process creation. Reported rather than swallowed: "blocked" and
        # "missing" must never look the same to the caller.
        return False, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a probe may not take the app down
        return False, f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "").strip()
        return False, f"exit {completed.returncode}: {error[:MAX_DETAIL]}"
    return True, (completed.stdout or "").strip().splitlines()[0] if completed.stdout else ""


def prove_pair(pair: Pair, *, runner: Callable[[Path], tuple] | None = None) -> Proof:
    """Run **both** halves. Either one failing means the pair is unusable.

    *runner* is the seam the tests drive; production passes nothing.
    """
    run = runner or _run_version
    ok, detail = run(pair.ffmpeg.as_path)
    if not ok:
        return Proof(ok=False, detail=detail[:MAX_DETAIL], failed="ffmpeg")
    version_text = detail
    ok, detail = run(pair.ffprobe.as_path)
    if not ok:
        return Proof(ok=False, detail=detail[:MAX_DETAIL], failed="ffprobe")
    return Proof(ok=True, version_text=version_text)


# --------------------------------------------------------------------------- #
# The remembered state
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthState:
    pair: Optional[Pair] = None
    #: Candidates already proven unusable, so repair never pokes them twice.
    rejected: tuple[tuple, ...] = ()

    def rejects(self, pair: Pair) -> bool:
        identity = (pair.ffmpeg.identity(), pair.ffprobe.identity())
        return identity in set(self.rejected)


def _binary_payload(binary: Binary) -> dict:
    return {"path": binary.path, "size": binary.size,
            "mtime_ns": binary.mtime_ns, "sha256": binary.sha256}


def _binary_from(payload) -> Optional[Binary]:
    if not isinstance(payload, dict) or not payload.get("path"):
        return None
    try:
        return Binary(path=str(payload["path"]),
                      size=int(payload.get("size", -1)),
                      mtime_ns=int(payload.get("mtime_ns", -1)),
                      sha256=str(payload.get("sha256", "")))
    except (TypeError, ValueError):
        return None


def load_state() -> HealthState:
    """Read the remembered state. Any damage reads as "nothing remembered".

    A missing, unreadable, malformed or out-of-contract file all mean the same
    thing -- establish once -- because none of them is evidence of success.
    """
    try:
        payload = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return HealthState()
    if not isinstance(payload, dict):
        return HealthState()
    if payload.get("proof_version") != PROOF_VERSION:
        return HealthState()

    pair = None
    block = payload.get("pair")
    if isinstance(block, dict):
        ffmpeg = _binary_from(block.get("ffmpeg"))
        ffprobe = _binary_from(block.get("ffprobe"))
        if ffmpeg is not None and ffprobe is not None:
            pair = Pair(ffmpeg=ffmpeg, ffprobe=ffprobe,
                        origin=str(block.get("origin", "")),
                        version_text=str(block.get("version_text", "")),
                        proven_at=str(block.get("proven_at", "")))
            if not pair.is_coherent():
                pair = None  # a hand-edited or corrupt mixed pair is not a pair

    rejected: list[tuple] = []
    for entry in payload.get("rejected") or ():
        ffmpeg = _binary_from((entry or {}).get("ffmpeg"))
        ffprobe = _binary_from((entry or {}).get("ffprobe"))
        if ffmpeg is not None and ffprobe is not None:
            rejected.append((ffmpeg.identity(), ffprobe.identity()))
    return HealthState(pair=pair, rejected=tuple(rejected))


def save_state(state: HealthState) -> None:
    """Persist the state. Failing to write is never fatal -- it costs a re-proof."""
    payload: dict = {
        "proof_version": PROOF_VERSION,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rejected": [],
    }
    if state.pair is not None:
        payload["pair"] = {
            "ffmpeg": _binary_payload(state.pair.ffmpeg),
            "ffprobe": _binary_payload(state.pair.ffprobe),
            "origin": state.pair.origin,
            "version_text": state.pair.version_text,
            "proven_at": state.pair.proven_at,
        }
    for ffmpeg_identity, ffprobe_identity in state.rejected:
        payload["rejected"].append({
            "ffmpeg": {"path": ffmpeg_identity[0], "size": ffmpeg_identity[1],
                       "mtime_ns": ffmpeg_identity[2]},
            "ffprobe": {"path": ffprobe_identity[0], "size": ffprobe_identity[1],
                        "mtime_ns": ffprobe_identity[2]},
        })
    try:
        state_path().parent.mkdir(parents=True, exist_ok=True)
        state_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def pinned_pair() -> Optional[Pair]:
    """The proven pair, but only while both files are still exactly as proven.

    This is the one function the runtime calls on the hot path, so it does no
    I/O beyond one small read and two ``stat`` calls.
    """
    pair = load_state().pair
    if pair is None or not pair.still_matches():
        return None
    return pair


# --------------------------------------------------------------------------- #
# Establishing / repairing
# --------------------------------------------------------------------------- #


class _NullLog:
    def line(self, text: str) -> None:  # noqa: D401 - trivial sink
        pass


def establish(log=None, *, runner=None, candidates: Iterable[Pair] | None = None
              ) -> Optional[Pair]:
    """Find a pair that actually runs, pin it, and remember what did not.

    Candidates already recorded as rejected are skipped **without executing
    them**: running a blocked binary is what raises the Windows Security
    notification, so the user sees it once per broken installation rather than
    on every repair.
    """
    log = log or _NullLog()
    state = load_state()
    rejected = list(state.rejected)
    pairs = list(candidates) if candidates is not None else discover_pairs()

    for pair in pairs:
        if not pair.is_coherent():
            continue
        if state.rejects(pair):
            log.line(f"  Skipping {pair.directory} — already known not to run here.")
            continue
        log.line(f"  Checking {pair.directory}…")
        proof = prove_pair(pair, runner=runner)
        if proof.ok:
            proven = replace(
                pair,
                ffmpeg=replace(pair.ffmpeg, sha256=sha256_of(pair.ffmpeg.as_path)),
                ffprobe=replace(pair.ffprobe, sha256=sha256_of(pair.ffprobe.as_path)),
                version_text=proof.version_text,
                proven_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            save_state(HealthState(pair=proven, rejected=tuple(rejected)))
            log.line(f"  Verified: {proof.version_text or pair.directory}")
            return proven
        identity = (pair.ffmpeg.identity(), pair.ffprobe.identity())
        if identity not in rejected:
            rejected.append(identity)
        log.line(f"  Not usable ({proof.failed}): {proof.detail}")

    save_state(HealthState(pair=None, rejected=tuple(rejected)))
    return None


def adopt_pair(pair: Pair, log=None, *, runner=None) -> Optional[Pair]:
    """Prove **one** coherent candidate and pin it only if it actually runs.

    ``establish`` is the wrong primitive for adopting a single known candidate.
    It is a discovery loop, and when nothing proves it ends by writing
    ``pair=None`` — so handing it one candidate that fails would erase a pinned
    pair that is working perfectly well. A replacement that cannot be proved
    must cost nothing but the attempt.

    So this is deliberately narrow:

    * the candidate must be coherent — one sibling pair, as everywhere else;
    * both halves are **executed** here, by this module. A caller cannot assert
      a pair is good and have it pinned on its word;
    * on success the active pin becomes this pair, with the usual durable
      evidence: absolute paths, size/mtime identity, SHA-256 of both binaries,
      and the ``-version`` text;
    * on failure the previous active pair is left exactly as it was. The
      candidate is remembered as rejected, which is what stops a blocked binary
      being re-executed later, but remembering a rejection never costs the pin.

    Returns the proven pair, or None.
    """
    log = log or _NullLog()
    if not pair.is_coherent():
        log.line("  Refusing to adopt a pair whose halves are not siblings.")
        return None

    state = load_state()
    proof = prove_pair(pair, runner=runner)
    if not proof.ok:
        identity = (pair.ffmpeg.identity(), pair.ffprobe.identity())
        rejected = list(state.rejected)
        if identity not in rejected:
            rejected.append(identity)
        # Keep whatever was already pinned. This is the whole point of the
        # helper: a failed replacement is not evidence against the incumbent.
        save_state(HealthState(pair=state.pair, rejected=tuple(rejected)))
        log.line(f"  Not usable ({proof.failed}): {proof.detail}")
        return None

    proven = replace(
        pair,
        ffmpeg=replace(pair.ffmpeg, sha256=sha256_of(pair.ffmpeg.as_path)),
        ffprobe=replace(pair.ffprobe, sha256=sha256_of(pair.ffprobe.as_path)),
        version_text=proof.version_text,
        proven_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    save_state(HealthState(pair=proven, rejected=state.rejected))
    log.line(f"  Verified: {proof.version_text or pair.directory}")
    return proven


def ensure_ready(log=None, *, runner=None) -> Optional[Pair]:
    """The one entry point setup and every launch use.

    Re-proves the **pinned pair only** when its identity still matches. That is
    two bounded ``-version`` calls of a build already known to work, never a
    sweep of arbitrary PATH entries -- so a launch cannot provoke a security
    notification by poking a blocked stranger, but also cannot keep claiming
    readiness for a pair the machine has since been told to refuse.
    """
    log = log or _NullLog()
    pair = pinned_pair()
    if pair is not None:
        proof = prove_pair(pair, runner=runner)
        if proof.ok:
            return pair
        log.line(f"  The verified FFmpeg no longer runs ({proof.failed}): "
                 f"{proof.detail}")
    return establish(log, runner=runner)


def describe_failure() -> str:
    """What to tell a person when nothing on this machine will run.

    Names no security product to disable, because disabling one is never the
    answer: on a managed machine the honest ask is an administrator allowlisting
    the binary, and on an unmanaged one a reinstall through setup is.
    """
    return (
        "FFmpeg could not be verified on this computer. The audio tools need "
        "both ffmpeg and ffprobe to run, and every copy found here either could "
        "not start or was refused by a Windows security policy.\n\n"
        "Run Setup_and_Run again to install a known-good copy. If this computer "
        "is managed by an organisation, its policy may need to allow FFmpeg — "
        "ask your IT administrator to allow it rather than turning protection off."
    )
