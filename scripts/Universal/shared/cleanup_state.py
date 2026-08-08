"""Maintenance state: where a cleanup request lives and how it is handed off.

This is the *client* half of the post-exit cleanup boundary. It persists a
validated :class:`~shared.maintenance.CleanupRequest`, starts the separate
non-venv coordinator, waits for that coordinator to positively acknowledge the
request, and later reads back the result the coordinator wrote. It is Tk-free
and standard-library only, so both the GUI (running inside ``.venv``) and the
coordinator (running outside it, from a base interpreter) import the same code.

**Nothing here deletes a catalog asset.** The only things this module removes
are files it owns itself, inside the maintenance-state folder, matched by exact
name: its own request when a handoff failed, its own temporary write files, and
its own stale acknowledgement. Removing a downloaded asset happens only in
``shared.cleanup_worker``, which the GUI never imports.

The state folder is ``files/runtime-data/maintenance/`` under the repository
root. It is chosen, not configurable: it cannot be supplied through a request,
it is derived from a root the caller had to prove, and it is validated on every
use to be inside the repository and outside all four selectable targets — so
cleanup can never delete the record of what it was asked to do. It is already
covered by the ``files/runtime-data/`` ignore rule and is never packaged, since
release archives contain only ``scripts/`` plus the root launcher and README.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import maintenance

# --------------------------------------------------------------------------- #
# Names — narrow, fixed, and never derived from anything a request carries
# --------------------------------------------------------------------------- #

#: The one project-owned maintenance-state location, relative to the repo root.
STATE_DIR_PARTS: tuple[str, ...] = ("files", "runtime-data", "maintenance")

REQUEST_NAME = "cleanup-request.json"
CONSUMED_NAME = "cleanup-request.consumed.json"
UNUSABLE_REQUEST_NAME = "cleanup-request.unusable.json"
ACCEPTED_NAME = "cleanup-accepted.json"
RESULT_NAME = "cleanup-result.json"
PRESENTED_NAME = "cleanup-result.presented.json"
UNREADABLE_RESULT_NAME = "cleanup-result.unreadable.json"
COORDINATOR_LOG_NAME = "cleanup-coordinator.log"

#: Prefix for this module's own temporary write files. Nothing without it is
#: ever removed by the temp sweep.
TEMP_PREFIX = ".act-maint-"

#: Everything this module is allowed to create in the state folder. A file whose
#: name is not here is never written, replaced or removed by this module.
STATE_FILENAMES: frozenset[str] = frozenset({
    REQUEST_NAME, CONSUMED_NAME, UNUSABLE_REQUEST_NAME, ACCEPTED_NAME,
    RESULT_NAME, PRESENTED_NAME, UNREADABLE_RESULT_NAME, COORDINATOR_LOG_NAME,
})

ACCEPT_SCHEMA_VERSION = maintenance.SCHEMA_VERSION
ACCEPT_FIELDS: tuple[str, ...] = (
    "schema_version", "request_id", "coordinator_process_id", "accepted_at",
)

#: A request older than this is never executed. It protects against a machine
#: that was powered off mid-handoff and booted days later, and it bounds how
#: long a recycled process id could possibly matter.
MAX_REQUEST_AGE = timedelta(hours=6)
#: Tolerance for a clock that is slightly ahead; beyond it the request is bogus.
MAX_CLOCK_SKEW = timedelta(minutes=5)

#: How long the GUI waits for a positive acknowledgement before giving up and
#: withdrawing the request. Acknowledgement normally arrives in well under a
#: second; this only bounds the pathological case.
ACCEPT_TIMEOUT_SECONDS = 20.0
ACCEPT_POLL_SECONDS = 0.05

#: How long the coordinator waits for the requesting GUI to exit. Bounded, so a
#: window the user never closes can never leave a process waiting forever.
EXIT_TIMEOUT_SECONDS = 900.0
EXIT_POLL_SECONDS = 0.25

#: Temporary write files older than this are someone else's abandoned crash.
TEMP_SWEEP_AGE_SECONDS = 3600.0


class StateError(Exception):
    """The maintenance state could not be used safely."""


class ActiveRequestError(StateError):
    """A live cleanup request already exists and is never silently replaced."""


# --------------------------------------------------------------------------- #
# The state folder
# --------------------------------------------------------------------------- #


def default_repo_root() -> Path:
    """The repository root implied by this file's own location.

    ``<root>/scripts/Universal/shared/cleanup_state.py`` — derived from
    ``__file__`` so it never depends on the current working directory, and never
    on anything a request carries.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def state_dir(repo_root) -> Path:
    """The validated maintenance-state folder under *repo_root*.

    Re-checked on every call rather than computed once: it must be inside the
    repository, must not be the repository root, must not be any catalog target
    or live inside one, must not be or contain a protected location, and must
    not be reached through a link at any level.
    """
    root = maintenance.absolute(repo_root)
    directory = root.joinpath(*STATE_DIR_PARTS)

    if maintenance.same_path(directory, root) or not maintenance.is_within(root, directory):
        raise StateError("the maintenance folder must live inside the project folder")

    for asset_id in maintenance.ASSET_IDS:
        target = maintenance.compiled_target(asset_id, root)
        if maintenance.same_path(directory, target) or maintenance.is_within(target, directory):
            raise StateError(
                "the maintenance folder must not live inside anything cleanup removes"
            )

    for relative in maintenance.PROTECTED_RELATIVE:
        protected = root.joinpath(*relative.split("/"))
        if maintenance.same_path(directory, protected) or maintenance.is_within(
            directory, protected
        ):
            raise StateError(f"{relative} is protected and is never used for state")

    if maintenance.is_link(root):
        raise StateError("the project folder is a shortcut or link, which is not followed")
    walked = root
    for part in STATE_DIR_PARTS:
        walked = walked / part
        if maintenance.is_link(walked):
            raise StateError(
                "the maintenance folder is a shortcut or link, which is not followed"
            )
    return directory


def ensure_state_dir(repo_root) -> Path:
    """Validate the state folder and create it if it is not there yet."""
    directory = state_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def state_file(repo_root, name: str) -> Path:
    """One named file inside the state folder. An unknown name is refused."""
    if name not in STATE_FILENAMES:
        raise StateError(f"{name!r} is not a maintenance state file")
    return state_dir(repo_root) / name


# --------------------------------------------------------------------------- #
# Atomic reads and writes
# --------------------------------------------------------------------------- #


def _discard_own_file(path: Path) -> bool:
    """Remove a file this module owns. Anything else is refused, not removed."""
    name = path.name
    if not (name in STATE_FILENAMES or name.startswith(TEMP_PREFIX)):
        raise StateError(f"{name!r} is not a file this module may remove")
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def write_json(path: Path, payload: dict) -> Path:
    """Write *payload* atomically: temp file in the same folder, then replace.

    The temporary file is flushed and closed before the replace, so a crash
    leaves either the previous file or the new one — never a half-written
    request that a coordinator could read as authorization.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".json",
                                         dir=str(directory))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        _discard_own_file(temp_path)
        raise
    return path


def read_json(path: Path):
    """Parse *path*, or ``None`` when it is absent, unreadable or not an object."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sweep_temporary_files(repo_root, *, older_than: float = TEMP_SWEEP_AGE_SECONDS,
                          now: float | None = None) -> int:
    """Remove this module's own abandoned temp files. Returns how many went.

    Strictly name-matched to :data:`TEMP_PREFIX` inside the state folder, and
    only once they are old enough that they cannot belong to an operation still
    in flight.
    """
    try:
        directory = state_dir(repo_root)
    except StateError:
        return 0
    if not directory.is_dir():
        return 0
    moment = time.time() if now is None else now
    removed = 0
    for entry in directory.iterdir():
        if not entry.name.startswith(TEMP_PREFIX):
            continue
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            if moment - entry.stat().st_mtime < older_than:
                continue
        except OSError:
            continue
        if _discard_own_file(entry):
            removed += 1
    return removed


# --------------------------------------------------------------------------- #
# Process inspection — shared by both sides so the rules cannot drift
# --------------------------------------------------------------------------- #

_IS_WINDOWS = os.name == "nt"


def open_process_handle(process_id: int):
    """A Windows handle bound to the exact running process, or ``None``.

    This is the strongest available answer to process-id reuse: the handle
    refers to the process *object*, so once it is open, a recycled id cannot
    make the wait finish against a different program. It is opened while the
    requesting GUI is still alive, before cleanup is acknowledged. ``None``
    means the process is already gone or cannot be opened, which callers treat
    as "not running".
    """
    if not _IS_WINDOWS:
        return None
    import ctypes

    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(process_id)
    )
    return handle or None


def close_process_handle(handle) -> None:
    if handle is None or not _IS_WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))  # type: ignore[attr-defined]
    except Exception:
        pass


def process_is_running(process_id: int) -> bool:
    """Best-effort liveness for *process_id* using platform primitives only."""
    try:
        pid = int(process_id)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if _IS_WINDOWS:
        handle = open_process_handle(pid)
        if handle is None:
            return False
        close_process_handle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wait_for_process_exit(process_id: int, *, handle=None,
                          timeout: float = EXIT_TIMEOUT_SECONDS,
                          poll: float = EXIT_POLL_SECONDS,
                          sleep=time.sleep, monotonic=time.monotonic) -> bool:
    """Block until *process_id* exits. Returns False if the timeout ran out.

    Bounded by construction, and never a busy loop: Windows blocks inside
    ``WaitForSingleObject`` on the handle opened earlier, and elsewhere it sleeps
    between liveness probes.
    """
    if _IS_WINDOWS and handle is not None:
        import ctypes

        WAIT_OBJECT_0 = 0x0
        WAIT_TIMEOUT = 0x102
        milliseconds = int(max(0.0, timeout) * 1000)
        outcome = ctypes.windll.kernel32.WaitForSingleObject(  # type: ignore[attr-defined]
            ctypes.c_void_p(handle), milliseconds
        )
        if outcome == WAIT_OBJECT_0:
            return True
        if outcome == WAIT_TIMEOUT:
            return False
        # Any other status means the handle is unusable; fall through to polling
        # rather than treating an error as "the process exited".
    deadline = monotonic() + max(0.0, timeout)
    while process_is_running(process_id):
        if monotonic() >= deadline:
            return False
        sleep(poll)
    return True


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


def request_path(repo_root) -> Path:
    return state_file(repo_root, REQUEST_NAME)


def request_is_stale(request, *, now=None) -> bool:
    """True when a request is too old, or timestamped implausibly far ahead."""
    moment = now or datetime.now(timezone.utc)
    age = moment - request.created_at
    if age > MAX_REQUEST_AGE:
        return True
    return -age > MAX_CLOCK_SKEW


def load_request(repo_root, *, path=None):
    """The stored request, or ``None`` when absent, corrupt or not schema-valid.

    Deliberately forgiving about *reading* and strict about *accepting*: an
    unusable file is reported as nothing rather than raising, and the caller
    decides what to say about it.
    """
    target = Path(path) if path is not None else request_path(repo_root)
    data = read_json(target)
    if data is None:
        return None
    try:
        return maintenance.request_from_dict(data)
    except maintenance.MaintenanceError:
        return None


def describe_existing_request(repo_root, *, now=None) -> tuple[str, object]:
    """Classify what is already on disk: ``("none"|"active"|"stale"|"unusable", request)``.

    "active" means a valid, recent request whose requesting process is still
    running — the one case that must never be overwritten.
    """
    target = request_path(repo_root)
    if not target.exists():
        return "none", None
    request = load_request(repo_root)
    if request is None:
        return "unusable", None
    if request_is_stale(request, now=now):
        return "stale", request
    if process_is_running(request.process_id):
        return "active", request
    return "stale", request


def store_request(request, repo_root, *, now=None) -> Path:
    """Persist *request* atomically, refusing to displace an active one.

    A previous request that is unusable or stale is moved aside to a differently
    named file first, so nothing is silently overwritten and the evidence
    survives for diagnosis.
    """
    if not isinstance(request, maintenance.CleanupRequest):
        raise maintenance.SchemaError("not a cleanup request")
    # Re-validate by round-tripping: what is written is exactly what a
    # coordinator will be able to read back and accept.
    payload = maintenance.request_to_dict(request)
    maintenance.request_from_dict(payload)

    ensure_state_dir(repo_root)
    state, existing = describe_existing_request(repo_root, now=now)
    if state == "active":
        raise ActiveRequestError(
            "a cleanup is already scheduled and has not run yet"
        )
    if state in ("stale", "unusable"):
        try:
            os.replace(request_path(repo_root),
                       state_file(repo_root, UNUSABLE_REQUEST_NAME))
        except OSError:
            _discard_own_file(request_path(repo_root))
    return write_json(request_path(repo_root), payload)


def discard_request(repo_root, request_id: str) -> bool:
    """Withdraw the stored request, but only when it is the one named.

    Used when a handoff failed: the operation removes its own request and
    nothing else, so a request written by another process cannot be dropped by
    someone else's failure.
    """
    stored = load_request(repo_root)
    if stored is None:
        target = request_path(repo_root)
        return _discard_own_file(target) if target.exists() else False
    if stored.request_id != request_id:
        return False
    return _discard_own_file(request_path(repo_root))


def consume_request(repo_root, request) -> bool:
    """Move the request aside so it can never be executed twice.

    Called immediately *before* the first deletion. If the file is already gone
    — the requester withdrew it, or another coordinator took it — this returns
    False and the caller must not delete anything.
    """
    source = request_path(repo_root)
    stored = load_request(repo_root)
    if stored is None or stored.request_id != request.request_id:
        return False
    try:
        os.replace(source, state_file(repo_root, CONSUMED_NAME))
    except OSError:
        return False
    return True


# --------------------------------------------------------------------------- #
# The acknowledgement handshake
# --------------------------------------------------------------------------- #


def accepted_path(repo_root) -> Path:
    return state_file(repo_root, ACCEPTED_NAME)


def clear_acceptance(repo_root) -> bool:
    """Drop any previous acknowledgement so a stale one cannot satisfy a new wait."""
    return _discard_own_file(accepted_path(repo_root))


def write_acceptance(repo_root, request, *, process_id=None, now=None) -> Path:
    """Record that this coordinator has accepted *request* and is ready to wait."""
    moment = now or datetime.now(timezone.utc)
    payload = {
        "schema_version": ACCEPT_SCHEMA_VERSION,
        "request_id": request.request_id,
        "coordinator_process_id": os.getpid() if process_id is None else int(process_id),
        "accepted_at": moment.isoformat(),
    }
    return write_json(accepted_path(repo_root), payload)


def read_acceptance(repo_root, request):
    """The acknowledgement for exactly *request*, or ``None``.

    A payload for a different request id, a wrong schema version, an extra field
    or a missing field is not an acknowledgement.
    """
    data = read_json(accepted_path(repo_root))
    if data is None:
        return None
    if set(data) != set(ACCEPT_FIELDS):
        return None
    if data.get("schema_version") != ACCEPT_SCHEMA_VERSION:
        return None
    if data.get("request_id") != request.request_id:
        return None
    process_id = data.get("coordinator_process_id")
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        return None
    return data


# --------------------------------------------------------------------------- #
# Starting the coordinator
# --------------------------------------------------------------------------- #


def coordinator_script() -> Path:
    """The coordinator's own file, resolved from this file's location."""
    return Path(__file__).resolve().parent / "cleanup_worker.py"


def _probe_is_non_venv(executable) -> bool:
    """Ask the candidate itself whether it is a virtual environment.

    Trusting ``sys.prefix == sys.base_prefix`` from the interpreter's own mouth
    is what makes "non-venv" verified rather than assumed.
    """
    try:
        finished = subprocess.run(
            [str(executable), "-c",
             "import sys; print('BASE' if sys.prefix == sys.base_prefix else 'VENV')"],
            capture_output=True, text=True, timeout=30, **_hidden_console(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return finished.returncode == 0 and (finished.stdout or "").strip() == "BASE"


def _hidden_console() -> dict:
    if not _IS_WINDOWS:
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": info, "creationflags": subprocess.CREATE_NO_WINDOW}


def interpreter_candidates() -> list[Path]:
    """Ordered base-interpreter candidates, best first, duplicates dropped."""
    candidates: list[Path] = []
    base_executable = getattr(sys, "_base_executable", None)
    if base_executable:
        candidates.append(Path(base_executable))
    base_prefix = Path(sys.base_prefix)
    if _IS_WINDOWS:
        candidates.append(base_prefix / "python.exe")
    else:
        candidates.append(base_prefix / "bin" / "python3")
        candidates.append(base_prefix / "bin" / "python")
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(candidate)
    return ordered


def find_non_venv_python(repo_root, *, candidates=None, probe=None):
    """A Python outside the project folder that says it is not a venv.

    Anything inside the repository is rejected outright — that is exactly the
    interpreter about to be deleted — before the candidate is even probed.
    """
    root = maintenance.absolute(repo_root)
    check = probe if probe is not None else _probe_is_non_venv
    for candidate in (interpreter_candidates() if candidates is None else candidates):
        path = maintenance.absolute(candidate)
        if maintenance.same_path(path, root) or maintenance.is_within(root, path):
            continue
        if not path.exists():
            continue
        if check(path):
            return path
    return None


def build_coordinator_command(python, request) -> list[str]:
    """The argument vector that starts the coordinator. Never a shell string.

    Only three things reach it: an interpreter this module verified, this
    module's own sibling file, and a UUID. No path, root or command from a
    request is ever part of it, so quoting cannot be got wrong and nothing can
    be injected — a folder name with spaces, an apostrophe or non-ASCII
    characters is simply one argv element.
    """
    return [
        str(python),
        str(coordinator_script()),
        "--run",
        "--request-id",
        str(request.request_id),
    ]


def spawn_coordinator(command: list[str]):
    """Start the coordinator detached, with no console and no shell."""
    options: dict = {
        "cwd": str(coordinator_script().parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if _IS_WINDOWS:
        options["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                    | subprocess.DETACHED_PROCESS)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, shell=False, **options)


def wait_for_acceptance(repo_root, request, process=None, *,
                        timeout: float = ACCEPT_TIMEOUT_SECONDS,
                        poll: float = ACCEPT_POLL_SECONDS,
                        sleep=time.sleep, monotonic=time.monotonic) -> bool:
    """Wait for a matching acknowledgement, bounded, and only a real one.

    Returns early and False if the coordinator process exits first: a helper
    that died before acknowledging is a failure, not something to keep waiting
    on.
    """
    deadline = monotonic() + max(0.0, timeout)
    while True:
        if read_acceptance(repo_root, request) is not None:
            return True
        if process is not None and process.poll() is not None:
            return read_acceptance(repo_root, request) is not None
        if monotonic() >= deadline:
            return False
        sleep(poll)


@dataclass(frozen=True)
class HandoffOutcome:
    """Whether cleanup was actually scheduled, plus one short honest detail."""

    started: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.started


def start_cleanup(request, repo_root=None, *, logger=None, python=None,
                  spawn=None, timeout: float = ACCEPT_TIMEOUT_SECONDS,
                  sleep=time.sleep, monotonic=time.monotonic) -> HandoffOutcome:
    """Persist, start, and wait for acknowledgement. Truthful either way.

    Nothing is deleted here and nothing is deleted by the caller: on success the
    coordinator is running and waiting for this process to exit; on any failure
    the request is withdrawn, every asset is untouched, and the caller keeps the
    application open.
    """
    root = maintenance.absolute(default_repo_root() if repo_root is None else repo_root)

    def note(message: str) -> None:
        if logger is not None:
            try:
                logger.warning("cleanup: %s", message)
            except Exception:
                pass

    try:
        ensure_state_dir(root)
        sweep_temporary_files(root)
        clear_acceptance(root)
        store_request(request, root)
    except ActiveRequestError as exc:
        note(str(exc))
        return HandoffOutcome(False, "A cleanup is already scheduled.")
    except (StateError, maintenance.MaintenanceError, OSError) as exc:
        note(f"the request could not be saved: {exc}")
        return HandoffOutcome(False, "The request could not be saved.")

    interpreter = python if python is not None else find_non_venv_python(root)
    if interpreter is None:
        note("no Python outside the project folder could be verified")
        discard_request(root, request.request_id)
        return HandoffOutcome(
            False, "No suitable Python outside the project folder was found."
        )

    command = build_coordinator_command(interpreter, request)
    starter = spawn if spawn is not None else spawn_coordinator
    try:
        process = starter(command)
    except (OSError, ValueError) as exc:
        note(f"the cleanup helper could not be started: {exc}")
        discard_request(root, request.request_id)
        return HandoffOutcome(False, "The cleanup helper could not be started.")

    accepted = wait_for_acceptance(root, request, process, timeout=timeout,
                                   sleep=sleep, monotonic=monotonic)
    if not accepted:
        # Withdraw first, then look once more: that ordering closes the race
        # where acknowledgement lands during the withdrawal. Either we see it
        # and report success, or the coordinator finds no request and refuses.
        discard_request(root, request.request_id)
        if read_acceptance(root, request) is not None:
            note("acknowledgement arrived as the request was being withdrawn")
            return HandoffOutcome(True)
        note("the cleanup helper did not acknowledge the request in time")
        return HandoffOutcome(
            False, "The cleanup helper did not confirm it was ready."
        )
    return HandoffOutcome(True)


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


def result_path(repo_root) -> Path:
    return state_file(repo_root, RESULT_NAME)


def store_result(result, repo_root) -> Path:
    """Write the finished result atomically, outside everything it removed."""
    if not isinstance(result, maintenance.CleanupResult):
        raise maintenance.SchemaError("not a cleanup result")
    payload = maintenance.result_to_dict(result)
    maintenance.result_from_dict(payload)
    ensure_state_dir(repo_root)
    return write_json(result_path(repo_root), payload)


def load_result(repo_root):
    """The unpresented result, or ``None``. Corrupt data is moved aside, not run.

    Reading a result can never execute anything: it is parsed through the strict
    schema and, if that fails, renamed out of the way so the next launch is not
    nagged by the same unusable file forever.
    """
    target = result_path(repo_root)
    if not target.exists():
        return None
    data = read_json(target)
    result = None
    if data is not None:
        try:
            result = maintenance.result_from_dict(data)
        except maintenance.MaintenanceError:
            result = None
    if result is None:
        try:
            os.replace(target, state_file(repo_root, UNREADABLE_RESULT_NAME))
        except OSError:
            _discard_own_file(target)
        return None
    return result


def mark_result_presented(repo_root, result) -> bool:
    """Retire the result once it has actually been shown, never before.

    Renamed rather than deleted, so the record of the last cleanup survives for
    support questions while never being shown twice.
    """
    stored = read_json(result_path(repo_root))
    if stored is None:
        return False
    if stored.get("request_id") != result.request_id:
        return False
    try:
        os.replace(result_path(repo_root), state_file(repo_root, PRESENTED_NAME))
    except OSError:
        return False
    return True
