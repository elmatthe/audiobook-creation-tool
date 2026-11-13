"""omnivoice_setup.py — install, adopt or repair the OmniVoice engine and model (v0.8.0 Phase 3).

The OmniVoice part of the app's ONE optional-voice installer. It is called only by
``tts.optional_setup_acquire.RealAcquirer``, in the setup worker, after the fresh plan was made, the person's consent
was proved to cover it and was spent; nothing here asks, plans or decides scope on its own, and nothing here runs at
import (the first-run window never imports it).

* **Sources.** Exactly the shipped manifest (``tts/omnivoice_manifest.json``): the 88 wheels of upstream's own lock at
  0.2.1, each by URL, size and SHA-256, and the model snapshot at its pinned commit, each file by size and SHA-256. Every
  download goes through the caller's opener (the acquirer's scoped, budgeted door) and ``qwen3_setup.download_file``
  (resumes a ``.part``, accepts a file only at its exact size and hash). pip installs only those local wheels, offline
  (``--no-index --require-hashes --no-deps --only-binary=:all:``) behind an audit hook that refuses any network or
  process start inside pip, so nothing is ever re-resolved against an index.
* **Adoption.** An environment that already holds exactly the pinned set, built from the app's own base Python, is
  never rebuilt and never downloaded again: it is proved (:func:`prove`) and only then recorded
  (``omnivoice_runtime.write_receipt``). A proof that shows it genuinely broken (its packages do not import, or it is
  not isolated) is recorded as rejected, so the next plan offers a repair -- under its own repair consent -- instead of
  the same check again. A GPU, driver or memory problem rejects nothing: it is reported and the environment is kept.
* **Repair never deletes what it did not make.** A broken environment is moved aside, whole, to
  ``files/runtime-data/omnivoice/set-aside/`` for the owner to delete; only an environment this app's own receipt says
  it was still creating is removed. The model folder is the app's own pinned snapshot: a damaged pinned file is replaced
  only under repair consent, and only by its verified download.
* **Locks.** ``setup.lock`` (every install and repair of this copy, and the repair of the app's own environment), then
  OmniVoice's ``inference.lock`` (every OmniVoice conversion holds it), and its ``engine.lock`` must be free (no worker
  left running). The proof also takes OmniVoice's machine-wide model guard, like a conversion.
* **Interruption.** A cancel stops the running download or child process with its whole tree. Verified wheels and model
  files are kept (a retry resumes, never re-downloads them); an unfinished environment stays recorded as unfinished; a
  receipt is written only after a proof succeeded, so nothing incomplete is ever ready.
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

#: pip run offline: the audit hook refuses every socket and every process start inside pip (an install of local wheels
#: needs neither), and reports what it refused. Distinct from the Qwen3 installer's own bootstrap on purpose.
OFFLINE_PIP = '''import atexit, json, runpy, sys
refused = []
def offline(event, args):
    if (event.startswith('socket.') and event != 'socket.gethostname') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        refused.append(event)
        raise PermissionError('offline pip refused network/process: ' + event)
sys.addaudithook(offline)
atexit.register(lambda: print('@@OMNIVOICE-OFFLINE ' + json.dumps(refused)))
sys.argv = ['pip', *sys.argv[1:]]
runpy.run_module('pip', run_name='__main__')
'''


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


# --------------------------------------------------------------------------- #
# The wheel cache: verified wheels, recorded by size, modification time and hash
# --------------------------------------------------------------------------- #
# The read-only side (the record, "is this wheel verified here", the plan's figures) lives in omnivoice_runtime, so the
# planner never imports this installer; only writing the record is here.
_load_record = ov.wheel_record
_stat_regular = ov.regular_file_stat
_recorded = ov.wheel_recorded
wheel_verified = ov.wheel_verified
wheel_bytes = ov.wheel_bytes


def _record_path() -> Path:
    return ov.wheel_record_path()


def _save_record(record: dict) -> None:
    path = _record_path()
    _require_inside(ov.wheel_cache_dir(), path)
    ov.atomic_write_json(path, record)


def fetch_wheels(*, opener, progress: Progress, cancel_check: CancelCheck, sleep=time.sleep) -> int:
    """Download every pinned wheel not already verified here, through *opener*. Returns the bytes fetched."""
    folder = ov.ensure_runtime_dir(ov.wheel_cache_dir())
    record = _load_record()
    todo = [w for w in ov.wheels() if not wheel_verified(w, record)]
    total, done = sum(w.size for w in todo), 0
    last = {"shown": -8 * 1024 * 1024}
    for wheel in ov.wheels():
        _check_cancel(cancel_check)
        target = folder / wheel.filename
        _require_inside(folder, target)
        if wheel in todo:
            if os.path.lexists(target):
                rt.remove_entry(target)  # the wrong bytes under this name (a complete download replaces them below)

            def on_bytes(count: int, name: str = wheel.filename) -> None:
                last["done"] = last.get("done", done) + count
                if last["done"] - last["shown"] >= 8 * 1024 * 1024 or last["done"] >= total:
                    last["shown"] = last["done"]
                    progress({"unit": "omnivoice-engine", "step": "download", "done": last["done"], "total": total,
                              "message": f"Downloading {name}"})

            last["done"] = done
            su.download_file(wheel.url, target, wheel.size, wheel.sha256, opener=opener, progress=on_bytes,
                             cancel_check=cancel_check, sleep=sleep)
            _require_inside(folder, target)
            done += wheel.size
        info = _stat_regular(target)
        if info is None:
            raise OmniVoiceSetupError(f"{wheel.filename} disappeared after it was verified.")
        record[wheel.filename] = [wheel.size, info.st_mtime_ns, wheel.sha256]
        _save_record(record)
    return total


def lock_text() -> str:
    """The hash lock pip installs from: every pinned wheel, by exact version and SHA-256."""
    return "".join(f"{w.name}=={w.version} --hash=sha256:{w.sha256}\n" for w in ov.wheels())


def pip_command(python: Path) -> tuple[list[str], Path]:
    """pip in *python*, reading only the verified local wheels by their hashes. Every wheel must be verified here."""
    folder = ov.wheel_cache_dir()
    record = _load_record()
    unverified = [w.filename for w in ov.wheels() if not _recorded(w, record)]
    if unverified:
        raise OmniVoiceSetupError(f"{len(unverified)} OmniVoice packages are not downloaded and verified yet (for "
                                  f"example {unverified[0]}); nothing was installed.")
    lock = folder / LOCK_NAME
    _require_inside(folder, lock)
    rt.remove_entry(lock)
    lock.write_text(lock_text(), encoding="utf-8")
    command = [str(python), "-I", "-B", "-c", OFFLINE_PIP, "install", "--isolated", "--require-virtualenv",
               "--no-index", "--find-links", str(folder), "--require-hashes", "--no-deps", "--only-binary=:all:",
               "--no-cache-dir", "--no-input", "--disable-pip-version-check", "--progress-bar", "off", "-r", str(lock)]
    return command, folder


def discard_wheels() -> None:
    """Give the wheels' space back once the engine is proved: only the pinned files, the lock and the record. Best
    effort; nothing else in the folder is touched."""
    folder = ov.wheel_cache_dir()
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None or not folder.is_dir():
        return
    for name in [w.filename for w in ov.wheels()] + [LOCK_NAME, RECORD_NAME]:
        path = folder / name
        try:
            if _stat_regular(path) is not None:
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
        if not self._inference.acquire():
            self._setup.release()
            raise OmniVoiceSetupError("The OmniVoice voices are being used by a conversion right now. Let it finish, or "
                                      "cancel it, before installing; nothing was changed.")
        engine = rt.FileLock(ov.engine_lock_path())
        try:
            free = engine.acquire()
        finally:
            engine.release()
        if not free:
            self._inference.release()
            self._setup.release()
            raise OmniVoiceSetupError("The OmniVoice voice engine is still running (a conversion that has not stopped "
                                      "yet). Close the app and try again; nothing was changed.")
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
# The engine: adopt, build, or (under repair consent) set aside and build
# --------------------------------------------------------------------------- #
MODE_ADOPT, MODE_INSTALL, MODE_REPAIR = "adopt", "install", "repair"


def engine_mode(assessment: ov.EngineAssessment) -> Optional[str]:
    """What acquiring the engine unit means for *assessment*: adopt, install, repair, or ``None`` (nothing may be done)."""
    return {ov.ENGINE_UNCHECKED: MODE_ADOPT, ov.ENGINE_ABSENT: MODE_INSTALL, ov.ENGINE_INCOMPLETE: MODE_REPAIR,
            ov.ENGINE_BROKEN: MODE_REPAIR}.get(assessment.state)


def set_aside_engine() -> Path:
    """Move the whole ``.venv-omnivoice`` to ``files/runtime-data/omnivoice/set-aside/`` -- kept, never deleted."""
    folder = ov.venv_dir()
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None:
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    root = ov.ensure_runtime_dir(ov.set_aside_root())
    target = root / f"venv-omnivoice-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"
    _require_inside(root, target)
    try:
        os.rename(folder, target)
    except OSError as exc:
        raise OmniVoiceSetupError(f"The existing OmniVoice environment could not be moved aside ({exc.strerror or exc}); "
                                  "a program may still be using it. Nothing was deleted; close it and try again.") from exc
    return target


def remove_unfinished_engine() -> None:
    """Remove ``.venv-omnivoice`` only when this app's own receipt says it was still creating it, here, and nothing on
    the way is a link: what this app did not make, or made completely, is never deleted."""
    folder = ov.venv_dir()
    if ov.read_receipt().get("stage") != ov.STAGE_CREATING:
        raise OmniVoiceSetupError("Refused to remove the OmniVoice environment: this app did not leave it unfinished.")
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None or venv_layout.is_link(folder):
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    real_root = os.path.realpath(ov.repo_root())
    if os.path.commonpath([real_root, os.path.realpath(folder)]) != real_root:
        raise OmniVoiceSetupError("Refused to remove the OmniVoice environment: it resolves outside the app's folder.")
    if os.path.lexists(folder):
        shutil.rmtree(folder)


_BASE_PROBE_MARK = su._BASE_PROBE_MARK
_BASE_PROBE = su._BASE_PROBE


def verified_base_python(*, runner, cancel_check: Optional[CancelCheck] = None) -> Path:
    """The app's own base CPython 3.12 (``omnivoice_runtime.app_base_python``), proved to be one: the same rule the
    Qwen3 engine's installer applies (``qwen3_setup.verified_base_python``), in OmniVoice's own words."""
    candidate = ov.app_base_python()

    def refuse(why: str) -> OmniVoiceSetupError:
        return OmniVoiceSetupError(f"The OmniVoice voice engine is built with the Python 3.12 this app was installed "
                                   f"with, and {candidate} cannot be used for it: {why}. Run the app's Setup_and_Run "
                                   "to repair its Python, then try again. Nothing was installed.")

    if not candidate.is_absolute() or not candidate.is_file():
        raise refuse("it is not there")
    if venv_layout.is_link(candidate):
        raise refuse("it is a link")
    if venv_layout.is_within(ov.repo_root(), candidate) and not venv_layout.same_path(candidate, rt.app_base_python()):
        raise refuse("it is inside this app's folder, so it belongs to an environment")
    if any((folder / "pyvenv.cfg").is_file() for folder in (candidate.parent, candidate.parent.parent)):
        raise refuse("it belongs to a virtual environment")
    lines: list[str] = []
    code = runner([str(candidate), "-I", "-c", _BASE_PROBE], env=su.installer_environment(), cwd=ov.repo_root(),
                  on_line=lines.append, cancel_check=cancel_check)
    report = None
    for line in lines:
        if line.startswith(_BASE_PROBE_MARK):
            try:
                report = json.loads(line[len(_BASE_PROBE_MARK):])
            except ValueError:
                report = None
    if code != 0 or not isinstance(report, dict):
        raise refuse("it did not start")
    if report.get("implementation") != "cpython" or list(report.get("version") or [])[:2] != [3, 12]:
        raise refuse(f"it is {report.get('implementation')} {report.get('version')}")
    if not venv_layout.same_path(report.get("prefix", ""), report.get("base_prefix", "")):
        raise refuse("it is a virtual environment's interpreter")
    if not venv_layout.same_path(report.get("executable", ""), candidate):
        raise refuse("it reports a different interpreter")
    return candidate


def _pip_environment() -> dict:
    """pip's environment: nothing ambient steering it, every temporary file inside the OmniVoice runtime folder."""
    env = ov.worker_environment()
    for name in [k for k in env if k.upper().startswith("PIP_")]:
        del env[name]
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
    return env


def _tail(lines: list[str], count: int = 4) -> str:
    return " ".join(line.strip() for line in lines[-count:] if line.strip())


def build_engine(*, runner, progress: Progress, cancel_check: CancelCheck) -> None:
    """Create ``.venv-omnivoice`` from the app's base Python and install the verified wheels into it, offline.

    The receipt says ``creating`` from before the folder exists until pip has finished and the installed set is proved
    to be exactly the pinned one; then it is cleared, leaving a complete but unproved environment (which :func:`prove`
    records, or the next plan adopts). An interruption therefore always leaves something the next plan can name.
    """
    folder = ov.venv_dir()
    if os.path.lexists(folder):
        raise OmniVoiceSetupError("An OmniVoice environment appeared while installing; nothing was changed.")
    if venv_layout.unsafe_component(ov.repo_root(), folder) is not None:
        raise OmniVoiceSetupError(ov.LINKED_MESSAGE)
    base = verified_base_python(runner=runner, cancel_check=cancel_check)
    tail: list[str] = []

    def on_line(line: str) -> None:
        tail.append(line)
        del tail[:-40]
        shown = line.strip()
        if shown.startswith(("Processing", "Installing collected", "Successfully")):
            progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0, "message": shown[:160]})

    _check_cancel(cancel_check)
    ov.write_receipt(ov.STAGE_CREATING, base_python=str(base))
    progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
              "message": "Creating OmniVoice's own Python environment..."})
    env = _pip_environment()
    code = runner([str(base), "-I", "-m", "venv", str(folder)], env=env, cwd=ov.repo_root(), on_line=on_line,
                  cancel_check=cancel_check)
    if code != 0 or not ov.venv_python().is_file():
        raise OmniVoiceSetupError("OmniVoice's Python environment could not be created. " + _tail(tail))
    built = venv_layout.read_pyvenv_cfg(folder) or {}
    if not venv_layout.same_path(built.get("home", ""), base.parent):
        raise OmniVoiceSetupError("OmniVoice's Python environment was not built from the app's own Python, so it is not "
                                  "used.")
    _check_cancel(cancel_check)
    progress({"unit": "omnivoice-engine", "step": "install", "done": 0, "total": 0,
              "message": "Installing the OmniVoice packages from the verified downloads (offline)..."})
    command, cwd = pip_command(ov.venv_python())
    code = runner(command, env=env, cwd=cwd, on_line=on_line, cancel_check=cancel_check)
    if code != 0:
        raise OmniVoiceSetupError("Installing the OmniVoice packages failed (the verified downloads are kept, so trying "
                                  "again downloads nothing). " + _tail(tail))
    problem = ov.structure_problem(folder) or ov.listing_problem(folder)
    if problem:
        raise OmniVoiceSetupError(f"The new OmniVoice environment is not the pinned one ({problem}).")
    ov.clear_receipt()  # complete, not yet proved: never ready until prove() records it


# --------------------------------------------------------------------------- #
# The proof: the engine imports, is isolated, holds the pinned versions, sees the GPU and loads the model, offline
# --------------------------------------------------------------------------- #
def proof_job() -> dict:
    manifest = ov.load_manifest()
    root = ov.repo_root()
    return {"schema": 1, "kind": "probe", "model_dir": str(ov.model_dir()),
            "omnivoice_version": manifest["engine"]["omnivoice"], "dtype": "float16", "device": "cuda",
            "engine_lock": str(ov.engine_lock_path()), "packages": ov.pinned_packages(),
            "environment": str(ov.venv_dir()), "foreign": [str(root / ".venv"), str(root / ".venv-qwen3")]}


def _prove_once(*, runner, cancel_check: CancelCheck, timeout_s: float) -> dict:
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
    job_path.write_text(json.dumps(proof_job()), encoding="utf-8")
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
            code = runner([str(ov.venv_python()), "-I", str(ov.worker_script()), str(job_path)],
                          env=ov.worker_environment(), cwd=jobs, on_line=on_line, cancel_check=stop)
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


def prove(*, runner, progress: Progress, cancel_check: CancelCheck, timeout_s: float = PROOF_TIMEOUT_S) -> dict:
    """Run the worker's ``probe`` job (offline, under the model guard), retrying only Smart App Control's first-load
    refusal. Returns its report, or raises :class:`ProofFailed` (``stage`` says whether it speaks against the
    environment) or ``qwen3_setup.SetupCancelled``."""
    progress({"unit": "omnivoice-engine", "step": "verify", "done": 0, "total": 0,
              "message": "Checking that OmniVoice starts on this computer's GPU and loads its model (offline)..."})
    for attempt in range(APPLICATION_CONTROL_ATTEMPTS):
        try:
            return _prove_once(runner=runner, cancel_check=cancel_check, timeout_s=timeout_s)
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


def record_proved(origin: str, probe: dict) -> dict:
    """Write the receipt that makes the engine ready: only after :func:`prove` succeeded."""
    folder = ov.venv_dir()
    base = venv_layout.base_identity(folder)
    if base is None:
        raise OmniVoiceSetupError("The Python the OmniVoice environment was built from is missing.")
    summary = {key: probe.get(key) for key in ("versions", "device_name", "total_mib", "load_s", "vram_allocated_mib",
                                                "vram_reserved_mib", "network_attempts", "isolation")}
    return ov.write_receipt(ov.STAGE_INSTALLED, origin=origin, base=base, probe=summary, probe_ok=True,
                            model_manifest_sha256=ov.model_manifest_sha256())


def record_rejected(reason: str) -> dict:
    """Record that the existing environment was checked and does not work, so the next plan offers a repair."""
    return ov.write_receipt(ov.STAGE_REJECTED, base=venv_layout.base_identity(ov.venv_dir()), reason=str(reason)[:300])
