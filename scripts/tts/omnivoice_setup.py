"""omnivoice_setup.py — install, adopt or repair the OmniVoice engine and model (v0.8.0 Phase 3; uv since v0.8.2 5B).

The OmniVoice part of the app's ONE optional-voice installer. It is called only by
``tts.optional_setup_acquire.RealAcquirer``, in the setup worker, after the fresh plan was made, the person's consent
was proved to cover it and was spent; nothing here asks, plans or decides scope on its own, and nothing here runs at
import (the first-run window never imports it).

* **Packages (v0.8.2 Phase 5B).** The engine lives in ``.venv-engines/omnivoice``, an independent environment beside
  the app's ``.venv`` (approved A1), made by uv on this copy's managed CPython 3.12.15 (``uv venv``) and filled with
  exactly the hash-locked artifacts of ``scripts/tts/engines/omnivoice/uv.lock`` (``uv sync --locked --no-dev
  --no-cache``, bytecode compiled, Windows copy / macOS clone; ``shared.engine_env`` through ``shared.uv_runner``): 88
  packages on Windows (torch 2.8.0+cu128 only from the explicit CUDA 12.8 index), 86 on an Apple Silicon Mac (PyPI).
  No package cache is kept (approved A4/D-8): an interrupted or failed install keeps no packages, and the next one
  downloads them again. The v0.8.0-v0.8.1 route (verified wheels and offline pip into ``.venv/engines/omnivoice``) is
  gone; its package lists stay in ``omnivoice_packages.json`` only as the lock's parity reference and download sizes.
* **Model.** Exactly the shipped manifest's snapshot (``tts/omnivoice_manifest.json``), each file by size and SHA-256,
  fetched through the caller's opener (the acquirer's scoped, budgeted door) and ``qwen3_setup.download_file`` (resumes a
  ``.part``, accepts a file only at its exact size and hash). Package problems never re-download the model.
* **Proof before use.** An engine is accepted only after a direct RECORD check of every installed file
  (``shared.venv_integrity``: uv itself does not notice a modified or missing file) and the worker's own proof (pinned
  versions, isolation, imports, the GPU, an offline model load). Only then are the receipts written -- the one inside the
  environment (``shared.engine_env``) and, last, the install receipt (``omnivoice_runtime.receipt_path``) -- and only
  then is it the engine in use (``omnivoice_runtime.venv_dir``).
* **Adoption.** An environment at ``.venv-engines/omnivoice`` that uv built on this copy's managed CPython and that holds
  exactly the pinned set, but that no current receipt vouches for, is RECORD-checked and proved, never rebuilt or
  downloaded again (:func:`adopt_engine`). A check that shows it genuinely broken is recorded as rejected, so the next
  plan offers a repair -- under its own repair consent. A GPU, driver or memory problem rejects nothing.
* **Earlier engines.** An engine v0.8.0-v0.8.1 installed at ``.venv/engines/omnivoice`` keeps working, untouched, until
  the new one is proved and recorded; it is then moved whole to ``files/runtime-data/omnivoice/set-aside/`` with a note
  (:func:`retire_nested`, ``shared.engine_env.retire``). The early sibling ``.venv-omnivoice`` is retired the same way
  (:func:`retire_legacy`). Moved, never deleted, never copied; a folder that cannot be moved now stays where it is,
  unused. A Python environment cannot be relocated, so nothing is ever adopted from either place.
* **Repair.** An environment this app's own receipt says it built (unfinished, rejected or damaged) is removed and
  built again; an unfinished one whose environment uv already made is synced again in place (only what is missing is
  downloaded). Anything else at ``.venv-engines/omnivoice`` -- one it only adopted, or that no receipt names -- is moved
  aside whole, never deleted.
* **Locks.** ``setup.lock`` (every install and repair of this copy, and the repair of the app's own environment), then
  OmniVoice's ``inference.lock`` (every OmniVoice conversion holds it), and its ``engine.lock`` must be free (no worker
  left running), so no environment is changed while its worker is active. The proof also takes OmniVoice's machine-wide
  model guard, like a conversion.
* **Interruption.** A cancel stops the running download or child process with its whole tree (the caller's runner). A
  killed uv's partial downloads are cleared by the next install (``uv_runner.clear_stale_scratch``); an unfinished
  environment stays recorded as unfinished; nothing incomplete is ever ready.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from shared import venv_layout
from tts import omnivoice_runtime as ov
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

CancelCheck = Callable[[], bool]
Progress = Callable[[dict], None]

#: The v0.8.0-v0.8.1 installer's files in its wheel folder (removed by :func:`discard_wheels`).
RECORD_NAME = ov.WHEEL_RECORD_NAME
LOCK_NAME = "requirements.txt"
#: How long one proof may take: a first torch import in a cold environment, Smart App Control's first look at each
#: new native file, and a model load (Phase 1 measured about 1.7 s for the load itself).
PROOF_TIMEOUT_S = 900.0
#: ``tts.optional_setup_health.APPLICATION_CONTROL_*``: Windows refuses the first load of each new unsigned native file
#: while it evaluates it, then allows it; only that refusal is retried, a bounded number of times.
APPLICATION_CONTROL_MARK = "Application Control policy"
APPLICATION_CONTROL_ATTEMPTS = 8
#: A proof that failed at one of these stages shows the environment itself is wrong (rejected: a repair is offered).
#: Any other failure (no usable GPU, the model would not load into memory, a busy guard) says nothing against it.
DAMAGING_STAGES = frozenset({"versions", "isolation", "import"})
#: The lines of uv's own output worth showing as a step while the engine installs (uv 0.13.10 wording).
UV_STEPS = ("Using CPython", "Creating virtual environment", "Resolved", "Prepared", "Installed", "Uninstalled",
            "Downloading", "Downloaded", "Bytecode compiled", "Audited", "error:", "Caused by:")


class OmniVoiceSetupError(RuntimeError):
    """One OmniVoice install step failed; the message is fit for a person and says what was kept."""


class ProofFailed(OmniVoiceSetupError):
    def __init__(self, message: str, *, stage: str = ""):
        super().__init__(message)
        self.stage = stage


def _check_cancel(cancel_check: Optional[CancelCheck]) -> None:
    su._check_cancel(cancel_check)  # raises su.SetupCancelled


def _require_inside(folder: Path, path: Path) -> None:
    """The write boundary: *path* lies lexically inside *folder*, and nothing from the repository root down to it is a
    link or junction. Checked immediately before and after each write."""
    if not venv_layout.is_within(folder, path):
        raise OmniVoiceSetupError(f"Refused to write {path}: it is outside {folder}.")
    unsafe = venv_layout.unsafe_component(ov.repo_root(), path)
    if unsafe is not None:
        raise OmniVoiceSetupError(f"Refused to write {path}: {unsafe} is a link or lies outside the app's folder.")


def discard_wheels() -> None:
    """Give back the space of the v0.8.0-v0.8.1 installer's verified wheels, which an interrupted earlier install could
    leave behind (uv keeps none): only the pinned files, its lock and its record. Best effort; nothing else in the
    folder is touched, and nothing is followed through a link."""
    folder = ov.wheel_cache_dir()
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None or not folder.is_dir():
        return
    for name in [w.filename for w in ov.wheels()] + [LOCK_NAME, RECORD_NAME]:
        path = folder / name
        try:
            if ov.regular_file_stat(path) is not None:
                path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# The install lock
# --------------------------------------------------------------------------- #
class InstallLock:
    """Exclusive right to change the OmniVoice installation of this copy, in the order every installer here uses.

    ``setup.lock`` keeps two installs or repairs of this copy apart (and a repair of the app's own environment, which
    takes it first); OmniVoice's ``inference.lock`` -- held by every OmniVoice conversion of this copy -- keeps an
    install from changing files a conversion is using; ``engine.lock`` must be free, so no OmniVoice worker is still
    running. All three are operating-system locks: a crash never leaves one stale.
    """

    def __init__(self) -> None:
        self._setup = rt.FileLock(rt.setup_lock_path())
        self._inference = rt.FileLock(ov.inference_lock_path())
        self._held = False

    def acquire(self) -> None:
        ov.ensure_runtime_dir(ov.runtime_dir())
        if not self._setup.acquire():
            raise OmniVoiceSetupError("Another install or repair of this copy of the app is running (or the app's own "
                                      "environment is being repaired). Wait for it to finish; nothing was changed.")
        try:
            if not self._inference.acquire():
                raise OmniVoiceSetupError("The OmniVoice voices are being used by a conversion right now. Let it "
                                          "finish, or cancel it, before installing; nothing was changed.")
            engine = rt.FileLock(ov.engine_lock_path())
            try:
                free = engine.acquire()
            finally:
                engine.release()
            if not free:
                raise OmniVoiceSetupError("The OmniVoice voice engine is still running (a conversion that has not "
                                          "stopped yet). Close the app and try again; nothing was changed.")
        except BaseException:
            # Refused, or a lock file that could not even be opened: whatever was taken is given back, so a failed
            # acquisition never leaves this copy looking busy to the next install, repair or cleanup.
            self._inference.release()
            self._setup.release()
            raise
        self._held = True

    def release(self) -> None:
        if self._held:
            self._inference.release()
            self._setup.release()
            self._held = False

    def __enter__(self) -> "InstallLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# --------------------------------------------------------------------------- #
# The model: missing or damaged pinned files fetched, every file proved, the record written
# --------------------------------------------------------------------------- #
def acquire_model(*, opener, progress: Progress, cancel_check: CancelCheck, allow_replace: bool,
                  sleep=time.sleep) -> int:
    """Fetch the pinned model files that are missing (or, under repair consent, damaged), then hash every file and
    record the verification (``omnivoice_runtime.verify_model_files``). Returns the bytes fetched."""
    problem = ov.model_folder_problem()
    if problem:
        raise OmniVoiceSetupError(problem)
    files = ov.model_spec()["files"]
    states = ov.model_file_states()
    for state, detail in states.values():
        if state == ov.FILE_UNVERIFIED:
            raise OmniVoiceSetupError(f"The OmniVoice model cannot be changed safely: {detail}.")
    damaged = [name for name, (state, _) in states.items() if state == ov.FILE_DAMAGED]
    if damaged and not allow_replace:
        raise OmniVoiceSetupError(f"The OmniVoice model file {damaged[0]} is not the approved one; replacing it needs a "
                                  "repair, confirmed on its own. Nothing was changed.")
    fetch = [name for name, (state, _) in states.items() if state != ov.FILE_READY]
    total, done = sum(files[name]["size"] for name in fetch), 0
    folder = ov.model_dir()
    if fetch:
        ov.ensure_runtime_dir(folder)
    for name in fetch:
        _check_cancel(cancel_check)
        target = folder.joinpath(*name.split("/"))
        _require_inside(folder, target)
        shown = {"done": done}

        def on_bytes(count: int, name: str = name) -> None:
            shown["done"] += count
            progress({"unit": "omnivoice-model", "step": "download", "done": shown["done"], "total": total,
                      "message": f"Downloading the OmniVoice model ({name})"})

        su.download_file(ov.model_url(name), target, files[name]["size"], files[name]["sha256"], opener=opener,
                         progress=on_bytes, cancel_check=cancel_check, sleep=sleep)
        _require_inside(folder, target)
        done += files[name]["size"]
    progress({"unit": "omnivoice-model", "step": "verify", "done": 0, "total": 0,
              "message": "Checking every OmniVoice model file (SHA-256)"})
    _check_cancel(cancel_check)
    problems = ov.verify_model_files()
    if problems:
        raise OmniVoiceSetupError(f"The OmniVoice model is not the approved files after downloading ({problems[0]}).")
    return total


# --------------------------------------------------------------------------- #
# The engine: adopt, build, or (under repair consent) clear and build -- always at .venv-engines/omnivoice
# --------------------------------------------------------------------------- #
MODE_ADOPT, MODE_INSTALL, MODE_REPAIR = "adopt", "install", "repair"


def engine_mode(assessment: ov.EngineAssessment) -> Optional[str]:
    """What acquiring the engine unit means for *assessment* (``omnivoice_runtime.assess_install``): adopt, install,
    repair, or ``None`` (nothing may be done)."""
    return {ov.ENGINE_UNCHECKED: MODE_ADOPT, ov.ENGINE_ABSENT: MODE_INSTALL, ov.ENGINE_INCOMPLETE: MODE_REPAIR,
            ov.ENGINE_BROKEN: MODE_REPAIR}.get(assessment.state)


def _stamp() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"


#: Windows refusals worth one more try when a whole environment folder is renamed: access denied and sharing
#: violation, which a rename gets while an indexer or a scanner briefly has the folder open (``bootstrap`` measured
#: every such refusal gone within 16 ms). Anything still refused after the last delay is real, and is reported.
_RENAME_TRANSIENT_WINERRORS = (5, 32)
_RENAME_RETRY_DELAYS_S = (0.01, 0.02, 0.04, 0.08, 0.16)


def _rename_whole(source: Path, target: Path, *, sleep=time.sleep) -> None:
    """``os.rename`` of a folder to a path that does not exist yet, with the bounded Windows retry. Never overwrites."""
    for delay in (*_RENAME_RETRY_DELAYS_S, None):
        if os.path.lexists(target):
            raise FileExistsError(f"{target} already exists")
        try:
            os.rename(source, target)
            return
        except OSError as exc:
            if delay is None or getattr(exc, "winerror", None) not in _RENAME_TRANSIENT_WINERRORS:
                raise
        sleep(delay)


def set_aside_engine() -> Path:
    """Move whatever is at ``.venv-engines/omnivoice`` -- something no receipt of this app names -- whole to
    ``files/runtime-data/omnivoice/set-aside/``: kept, never deleted."""
    folder = ov.engine_venv_dir()
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None:
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    root = ov.ensure_runtime_dir(ov.set_aside_root())
    target = root / f"venv-engines-omnivoice-{_stamp()}"
    _require_inside(root, target)
    try:
        _rename_whole(folder, target)
    except OSError as exc:
        raise OmniVoiceSetupError(f"The existing OmniVoice environment could not be moved aside ({exc.strerror or exc}); "
                                  "a program may still be using it. Nothing was deleted; close it and try again.") from exc
    return target


def built_here(receipt: dict) -> bool:
    """Whether this app's receipt says it built the environment itself: an install it was making (``creating``,
    ``created``), or one it installed (origin ``installed``) -- never one it only found and adopted."""
    return receipt.get("stage") in (ov.STAGE_CREATING, ov.STAGE_CREATED) or (
        receipt.get("stage") in ov.STAGES and receipt.get("origin") == ov.ORIGIN_INSTALLED)


def remove_own_engine() -> None:
    """Remove ``.venv-engines/omnivoice`` only when this app's own receipt says it built it (an install it left
    unfinished, or an engine it built and that was proved damaged), it is reached through no link and it resolves
    inside the app's folder: what this app did not make is never deleted."""
    folder = ov.engine_venv_dir()
    if not built_here(ov.read_receipt()):
        raise OmniVoiceSetupError("Refused to remove the OmniVoice environment: this app did not build it.")
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None or venv_layout.is_link(folder):
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    real_root = os.path.realpath(ov.repo_root())
    if os.path.commonpath([real_root, os.path.realpath(folder)]) != real_root:
        raise OmniVoiceSetupError("Refused to remove the OmniVoice environment: it resolves outside the app's folder.")
    if os.path.lexists(folder):
        shutil.rmtree(folder)
    ov.clear_receipt()


def uv_problem() -> str:
    """Why the engine cannot be built by uv in this copy right now, or ``""``: the engine's project files, the pinned uv
    or this copy's managed CPython (stage 0 installs both) are missing or not the pinned ones."""
    from shared import uv_runner

    root = ov.repo_root()
    for name in ("pyproject.toml", "uv.lock"):
        if not (ov.project_dir() / name).is_file():
            return ("The OmniVoice engine's package lock is missing from this copy of the app; reinstall the app. "
                    "Nothing was installed.")
    if (uv_runner.uv_problem(root) or not uv_runner.managed_python(root).is_file()
            or uv_runner.interpreter_build(root) != uv_runner.PYTHON_BUILD):
        return ("The app's own Python or its package tool (uv) is missing or is not the pinned one, so the OmniVoice "
                "voice engine cannot be installed. Start the app with Setup_and_Run to repair it, then try again. "
                "Nothing was installed.")
    return ""


def build_problem() -> str:
    """Why the engine cannot be built in this copy of the app right now, or ``""``: the copy is too deep for it
    (``omnivoice_runtime.install_depth_problem``), or uv or its project is not ready (:func:`uv_problem`). Asked before
    anything is downloaded for a build, and again by :func:`build_engine` itself."""
    return ov.install_depth_problem() or uv_problem()


def _tail(lines: list[str], count: int = 4) -> str:
    return " ".join(line.strip() for line in lines[-count:] if line.strip())


def _record_problem(folder: Path) -> str:
    """The first installed file that does not match its distribution's RECORD (presence, size, SHA-256), or ``""``."""
    from shared import engine_env

    damaged = engine_env.record_damage(ov.repo_root(), ov.ENGINE_KEY)
    return "; ".join(f"{name}: {why}" for name, why in list(damaged.items())[:3])


def _verify_installed(folder: Path, progress: Progress, *, built: bool) -> None:
    """The listing is exactly the pinned set and every installed file matches its RECORD; otherwise the environment is
    recorded as rejected (so the next plan rebuilds it instead of syncing it again) and the reason raised."""
    progress({"unit": "omnivoice-engine", "step": "verify", "done": 0, "total": 0,
              "message": "Checking every installed OmniVoice file against its record..."})
    problem = ov.listing_problem(folder)
    if problem:
        problem = f"it does not hold exactly its pinned packages ({problem})"
    else:
        damaged = _record_problem(folder)
        problem = f"its installed files do not match their records ({damaged})" if damaged else ""
    if problem:
        record_rejected(problem, built=built)
        raise OmniVoiceSetupError(f"The new OmniVoice environment is not the locked one: {problem}. Install & Continue "
                                  "offers to rebuild it.")


def build_engine(*, runner, progress: Progress, cancel_check: CancelCheck) -> None:
    """Make ``.venv-engines/omnivoice`` with uv from the engine's locked project and check every installed file.

    Created at its final path on this copy's managed CPython (``uv venv``), then ``uv sync --locked --no-dev
    --no-cache`` installs exactly the locked artifacts, downloading them. An unfinished install this app recorded after
    uv made the environment (``created``) is synced again in place; any other install this app's receipt names is
    removed first, and anything else there is moved aside whole (:func:`set_aside_engine`). Under :class:`InstallLock`
    from start to end.

    The receipt says ``creating`` from before the folder exists, ``created`` once uv made it at its place, and stays
    ``created`` -- a complete but unproved environment -- when this returns: only :func:`record_proved` makes it ready.
    An interruption therefore always leaves something the next plan can name. A listing or RECORD mismatch after the sync
    records the environment as rejected (:func:`_verify_installed`).
    """
    from shared import engine_env, uv_runner

    root, key, folder = ov.repo_root(), ov.ENGINE_KEY, ov.engine_venv_dir()
    if venv_layout.unsafe_component(root, folder) is not None:
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    problem = build_problem()
    if problem:
        raise OmniVoiceSetupError(problem)
    try:
        engine_env.check(root, key)
    except uv_runner.TargetRefused as exc:
        raise OmniVoiceSetupError(f"The OmniVoice voice engine cannot be installed here ({exc}). Nothing was "
                                  "installed.") from None
    uv_runner.clear_stale_scratch(root)  # an earlier install that was killed left its partial downloads: none are kept
    tail: list[str] = []

    def on_line(line: str) -> None:
        tail.append(line)
        del tail[:-40]
        shown = line.strip()
        if shown.startswith(UV_STEPS):
            progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0, "message": shown[:160]})

    resync = False
    if os.path.lexists(folder):
        stage = ov.read_receipt().get("stage")
        if stage == ov.STAGE_CREATED and not ov.engine_identity_problem(folder):
            resync = True  # uv made it here and the sync did not finish: synced again, only what is missing downloaded
        elif built_here(ov.read_receipt()):
            progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
                      "message": "Removing the OmniVoice environment this app could not finish or prove..."})
            remove_own_engine()
        else:
            moved = set_aside_engine()
            progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
                      "message": f"The existing OmniVoice environment was kept at {rt.shown_path(moved)}"})
    _check_cancel(cancel_check)
    cwd = ov.repo_root()
    with uv_runner.Operation(root) as operation:
        env = engine_env.environment(root, operation, key)
        if not resync:
            ov.write_receipt(ov.STAGE_CREATING)
            progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
                      "message": "Creating OmniVoice's own Python environment..."})
            code = runner(engine_env.venv_command(root, key), env=env, cwd=cwd, on_line=on_line,
                          cancel_check=cancel_check)
            if code != 0 or not venv_layout.interpreter(folder).is_file():
                raise OmniVoiceSetupError("OmniVoice's Python environment could not be created. " + _tail(tail))
            problem = ov.engine_identity_problem(folder)
            if problem:
                raise OmniVoiceSetupError(f"OmniVoice's Python environment could not be verified ({problem}), so it is "
                                          "not used.")
            ov.write_receipt(ov.STAGE_CREATED)
        _check_cancel(cancel_check)
        engine_env.invalidate_receipt(root, key)
        progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
                  "message": "Downloading and installing the OmniVoice packages (about "
                             f"{rt.format_bytes(ov.wheels_total_bytes())}, each checked against the app's lock)..."})
        code = runner(engine_env.sync_command(root, key), env=env, cwd=cwd, on_line=on_line, cancel_check=cancel_check)
        if code != 0:
            raise OmniVoiceSetupError("Installing the OmniVoice packages failed. No package files are kept, so trying "
                                      "again downloads them again. " + _tail(tail))
    _verify_installed(folder, progress, built=True)


def adopt_engine(*, progress: Progress) -> None:
    """An environment uv built here on the managed CPython, holding exactly the pinned set, that no current receipt
    vouches for: every installed file is checked against its RECORD (nothing is downloaded, built or changed); the
    proof and :func:`record_proved` follow."""
    _verify_installed(ov.engine_venv_dir(), progress, built=False)


# --------------------------------------------------------------------------- #
# Earlier engines: retired only after the new engine is proved, and never deleted
# --------------------------------------------------------------------------- #
#: The note left beside the v0.8.0-v0.8.1 nested engine once a new one has passed its checks.
RETIRED_NESTED_NOTE = (
    "This is the OmniVoice voice engine an earlier version of the Audiobook Creation Tool installed in "
    ".venv\\engines\\omnivoice.\nSince v0.8.2 the engine is installed in .venv-engines\\omnivoice, and the new one passed "
    "its checks before this folder was moved here,\nwhole and unchanged. The app no longer uses it and never runs anything "
    "from here. It is kept so nothing is lost;\nyou may delete this folder to give its disk space back (about 8 GB). If "
    "Windows says a path is too long, first move\nthe folder to the top of the drive and give it a short name, then delete "
    "it there.\n")


def retire_nested(progress: Progress) -> Optional[Path]:
    """Once ``.venv-engines/omnivoice`` is the engine in use, move the engine v0.8.0-v0.8.1 installed at
    ``.venv/engines/omnivoice`` -- only that exact folder, a real environment reached through no link -- whole into
    ``files/runtime-data/omnivoice/set-aside/`` with a note (``shared.engine_env.retire``: a rename, nothing copied,
    nothing deleted). Under :class:`InstallLock`, so no worker runs from it. A folder that cannot be moved now (a file in
    use) stays where it is, unused, and is said; nothing fails because of it."""
    from shared import engine_env

    nested = ov.nested_venv_dir()
    if not ov.is_canonical() or ov.assess_engine().state != ov.ENGINE_READY or not os.path.lexists(nested):
        return None
    if venv_layout.unsafe_component(ov.repo_root(), nested) is not None or not (nested / "pyvenv.cfg").is_file():
        return None
    try:
        moved = engine_env.retire(ov.repo_root(), ov.ENGINE_KEY, nested, label="nested-omnivoice",
                                  note=RETIRED_NESTED_NOTE)
    except OSError as exc:
        progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
                  "message": f"The earlier engine in {rt.shown_path(nested)} is no longer used; it could not be moved "
                             f"aside now ({exc}), and is left where it is."})
        return None
    receipt = ov.nested_receipt_path()
    try:
        if ov.regular_file_stat(receipt) is not None and venv_layout.unsafe_component(ov.repo_root(), receipt) is None:
            os.replace(receipt, moved.parent / receipt.name)  # its receipt goes with it; it vouches for nothing here
    except OSError:
        pass
    progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
              "message": f"The earlier engine is no longer used; it was moved, unchanged, to {rt.shown_path(moved.parent)}."})
    return moved


#: The folder a retired sibling is kept in, under ``set-aside/``: ``legacy-venv-omnivoice-<UTC>-<id>``.
RETIRED_PREFIX = "legacy-venv-omnivoice-"
#: Inside it: the environment under its own old name, its old receipt, and this note.
RETIRED_NOTE_NAME = "RETIRED-READ-ME.txt"
RETIRED_RECORD_NAME = "retired.json"
RETIRED_NOTE = """This folder holds an OmniVoice environment that the Audiobook Creation Tool no longer uses.

It was installed beside the app's own environment, as  {original}
The app now keeps the OmniVoice engine in its own environment, at  {engine}
That engine was built again there from its locked packages and proved to work before this folder was moved here
({moved_utc}). Nothing was deleted, and the app never runs anything from this folder.

A Python environment cannot be used from another place than the one it was created in, so the folder
"{name}" in here is NOT a working environment while it is here. It is kept only so nothing of yours is lost.

You may delete this whole folder to give its disk space back (about {size}).
Some files in it have very long names. If Windows says a path is too long when you delete it, first move the folder
"{name}" to the top of the drive and give it a short name (for example "x"), then delete it there.
To put it back exactly as it was, move "{name}" back to the app's folder (and "install-receipt.json", if present,
back to files\\runtime-data\\omnivoice\\); the app still will not use it.
"""


def retire_legacy() -> Optional[Path]:
    """Move the earlier sibling ``.venv-omnivoice`` -- whole, with its own old receipt -- to a labelled folder under
    ``files/runtime-data/omnivoice/set-aside/``. Returns that folder, or ``None`` when there was nothing to retire.

    Only ever called under :class:`InstallLock`, and only once the engine in use is ready (proved, and recorded as
    proved): otherwise it refuses, so no failure before that point can cost the earlier environment its place. Moved,
    never deleted and never copied; a link, or anything there that is not an environment folder, is left exactly as it
    is (``None``). One rename on one volume, so the environment is whole in exactly one of the two places at every
    instant; if it cannot be moved it stays where it was and the reason is raised."""
    if ov.assess_engine().state != ov.ENGINE_READY:
        raise OmniVoiceSetupError("Refused to move the earlier OmniVoice environment aside: the new one is not proved "
                                  "yet. Nothing was changed.")
    legacy = ov.assess_legacy()
    if not legacy.retirable:
        return None
    folder = ov.legacy_venv_dir()
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None or venv_layout.is_link(folder):
        return None
    try:
        root = ov.ensure_runtime_dir(ov.set_aside_root())
        container = root / f"{RETIRED_PREFIX}{_stamp()}"
        _require_inside(root, container)
        ov.ensure_runtime_dir(container)
    except ov.OmniVoiceUnavailable as exc:  # the set-aside folder is a link, or cannot be made
        raise OmniVoiceSetupError(f"The earlier OmniVoice environment ({venv_layout.LEGACY_OMNIVOICE}) was not moved "
                                  f"aside: {exc} It was left where it is, it is not used, and nothing was "
                                  "deleted.") from exc
    target = container / folder.name
    _require_inside(container, target)
    size = _tree_bytes(folder)
    try:
        _rename_whole(folder, target)
    except OSError as exc:
        try:
            container.rmdir()  # empty: nothing was moved into it
        except OSError:
            pass
        raise OmniVoiceSetupError(f"The earlier OmniVoice environment ({venv_layout.LEGACY_OMNIVOICE}) could not be "
                                  f"moved aside ({exc.strerror or exc}); a program may still have a file in it open. "
                                  "It was left where it is, it is not used, and nothing was deleted.") from exc
    moved_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    receipt = ov.legacy_receipt_path()
    kept_receipt = False
    try:
        if ov.regular_file_stat(receipt) is not None and venv_layout.unsafe_component(ov.repo_root(), receipt) is None:
            os.replace(receipt, container / receipt.name)
            kept_receipt = True
    except OSError:
        pass  # the old receipt stays where it was; it names a folder that is gone, so it vouches for nothing
    engine = ov.venv_dir()
    record = {"schema": "act-omnivoice-retired-environment", "version": 1, "moved_utc": moved_utc,
              "original_path": os.path.normpath(os.path.abspath(folder)),
              "kept_as": os.path.normpath(os.path.abspath(target)), "state_when_moved": legacy.state,
              "old_receipt_kept": kept_receipt, "bytes": size,
              "replaced_by": os.path.normpath(os.path.abspath(engine)), "runnable_here": False}
    try:
        ov.atomic_write_json(container / RETIRED_RECORD_NAME, record)
        (container / RETIRED_NOTE_NAME).write_text(RETIRED_NOTE.format(
            original=record["original_path"], engine=record["replaced_by"], moved_utc=moved_utc, name=folder.name,
            size=rt.format_bytes(size)), encoding="utf-8")
    except (OSError, ov.OmniVoiceUnavailable):
        pass  # the label is a courtesy; the environment is already safely kept
    return container


def _tree_bytes(folder: Path) -> int:
    total = 0
    try:
        for top, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    total += os.lstat(os.path.join(top, name)).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


# --------------------------------------------------------------------------- #
# The proof: the engine imports, is isolated, holds the pinned versions, sees the GPU and loads the model, offline
# --------------------------------------------------------------------------- #
def foreign_environments() -> list[str]:
    """Every other environment of this copy the engine must stay apart from: the app's ``.venv`` (whose packages are
    never its own; the v0.8.0-v0.8.1 nested engine lies inside it), every Qwen3 location and the earlier OmniVoice
    sibling. The worker treats what lies inside its own environment as its own, so an earlier nested engine still in use
    is not refused for lying inside the first of these."""
    root = ov.repo_root()
    return [str(ov.parent_venv_dir()), str(root.joinpath(*venv_layout.NESTED_QWEN3.split("/"))),
            str(root / venv_layout.LEGACY_QWEN3), str(ov.legacy_venv_dir()),
            str(root.joinpath(*venv_layout.ENGINE_QWEN3.split("/")))]


def proof_job(folder: Optional[Path] = None) -> dict:
    """The installer's proof job for the engine at *folder* (default: the one in use): on Windows CUDA float16, as
    released; on a Mac the device the person runs OmniVoice on (``omnivoice_runtime.device_policy``: the GPU by default,
    the CPU by choice), in float32."""
    manifest = ov.load_manifest()
    policy = ov.device_policy()
    return {"schema": 1, "kind": "probe", "model_dir": str(ov.model_dir()),
            "omnivoice_version": manifest["engine"]["omnivoice"], "dtype": policy.dtype, "device": policy.device,
            "engine_lock": str(ov.engine_lock_path()), "packages": ov.pinned_packages(),
            "environment": str(ov.venv_dir() if folder is None else folder), "foreign": foreign_environments()}


def _prove_once(*, runner, cancel_check: CancelCheck, timeout_s: float, folder: Path) -> dict:
    deadline = time.monotonic() + timeout_s
    expired = {"value": False}

    def stop() -> bool:
        if cancel_check():
            return True
        if time.monotonic() > deadline:
            expired["value"] = True
            return True
        return False

    jobs = ov.ensure_runtime_dir(ov.runtime_dir() / "probe")
    job_path = jobs / f"probe-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    job_path.write_text(json.dumps(proof_job(folder)), encoding="utf-8")
    events: list[dict] = []
    other: list[str] = []

    def on_line(line: str) -> None:
        if line.startswith("@@EVENT "):
            try:
                events.append(json.loads(line[len("@@EVENT "):]))
            except ValueError:
                pass
        else:
            other.append(line)
            del other[:-40]

    guard = ov.MachineGuard()
    try:
        if not guard.acquire():
            raise ProofFailed(guard.refusal_message, stage="guard")
        try:
            code = runner([str(venv_layout.interpreter(folder)), "-I", str(ov.worker_script()), str(job_path)],
                          env=ov.worker_environment(own=folder), cwd=jobs, on_line=on_line, cancel_check=stop)
        except su.SetupCancelled:
            if expired["value"]:
                raise ProofFailed(f"The OmniVoice check did not finish within {int(timeout_s)} s.", stage="timeout")
            raise
    finally:
        guard.release()
        job_path.unlink(missing_ok=True)
    failed = next((e for e in events if e.get("event") == "failed"), None)
    report = next((e for e in events if e.get("event") == "probe"), None)
    if failed is not None or report is None or code != 0:
        detail = (failed or {}).get("message") or _tail(other) or f"exit {code}"
        raise ProofFailed(f"The OmniVoice voice engine did not pass its check: {detail}",
                          stage=str((failed or {}).get("stage") or "worker"))
    return {k: v for k, v in report.items() if k != "event"}


def prove(*, runner, progress: Progress, cancel_check: CancelCheck, folder: Optional[Path] = None,
          timeout_s: float = PROOF_TIMEOUT_S) -> dict:
    """Run the worker's ``probe`` job in the engine at *folder* (default: the one in use; an install proves the new one
    before it is in use), offline, under the model guard, retrying only Smart App Control's first-load refusal. Returns
    its report, or raises :class:`ProofFailed` (``stage`` says whether it speaks against the environment) or
    ``qwen3_setup.SetupCancelled``."""
    folder = ov.venv_dir() if folder is None else Path(folder)
    where = {ov.DEVICE_MPS: "this Mac's GPU", ov.DEVICE_CPU: "this Mac's processor"}.get(
        ov.device_policy().device, "this computer's GPU")
    progress({"unit": "omnivoice-engine", "step": "verify", "done": 0, "total": 0,
              "message": f"Checking that OmniVoice starts on {where} and loads its model (offline)..."})
    for attempt in range(APPLICATION_CONTROL_ATTEMPTS):
        try:
            return _prove_once(runner=runner, cancel_check=cancel_check, timeout_s=timeout_s, folder=folder)
        except ProofFailed as exc:
            if APPLICATION_CONTROL_MARK not in str(exc) or attempt + 1 == APPLICATION_CONTROL_ATTEMPTS:
                raise
            _check_cancel(cancel_check)
            progress({"unit": "omnivoice-engine", "step": "verify", "done": 0, "total": 0,
                      "message": "Windows is checking the new engine files (Smart App Control); trying again..."})
    raise AssertionError("unreachable")  # pragma: no cover


def speaks_against_environment(exc: ProofFailed) -> bool:
    """Whether a failed proof shows the environment itself is wrong (its packages, isolation or imports), rather than
    the GPU, its memory, a busy guard, a timeout -- or Windows' application control, which a rebuild cannot change."""
    return exc.stage in DAMAGING_STAGES and APPLICATION_CONTROL_MARK not in str(exc)


def _probe_summary(probe: dict) -> dict:
    summary = {key: probe.get(key) for key in ("versions", "device_name", "total_mib", "load_s", "vram_allocated_mib",
                                                "vram_reserved_mib", "network_attempts", "isolation")}
    if probe.get("device") is not None:  # a Mac: which device and dtype were proved, and the memory the proof used
        summary.update({key: probe.get(key) for key in ("device", "dtype", "footprint_mib", "peak_footprint_mib",
                                                        "mps_allocated_mib", "mps_driver_mib") if key in probe})
    return summary


def record_proved(origin: str, probe: dict) -> dict:
    """Make ``.venv-engines/omnivoice`` ready: only after its RECORD check (:func:`build_engine`, :func:`adopt_engine`)
    and a successful :func:`prove`. Writes the receipt inside the environment (``shared.engine_env``: lock,
    interpreter, profile, installed distributions, this proof) and then, last, the install receipt -- from that moment
    it is the engine in use (``omnivoice_runtime.venv_dir``)."""
    from shared import engine_env

    if ov.engine_identity_problem():
        raise OmniVoiceSetupError("The OmniVoice environment is not this app's own uv-built engine, so it was not "
                                  "recorded as ready.")
    summary = _probe_summary(probe)
    engine_env.write_receipt(ov.repo_root(), ov.ENGINE_KEY,
                             health={"record": "ok", "probe": summary, "proved_at": time.time()})
    return ov.write_receipt(ov.STAGE_INSTALLED, origin=origin, probe=summary, probe_ok=True,
                            model_manifest_sha256=ov.model_manifest_sha256())


def record_rejected(reason: str, *, built: bool) -> dict:
    """Record that ``.venv-engines/omnivoice`` was checked and does not work, so the next plan offers a repair. *built*
    says whether this app built it (its repair removes it) or only found it (its repair moves it aside, kept)."""
    return ov.write_receipt(ov.STAGE_REJECTED, reason=str(reason)[:300],
                            origin=ov.ORIGIN_INSTALLED if built else ov.ORIGIN_ADOPTED)
