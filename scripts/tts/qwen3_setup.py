"""qwen3_setup.py — install, verify and repair the Qwen3 voices. Runs only when the user asks for it.

Owner rulings it implements (``Decisions.md``, 2026-10-19, CP6):

* Q1/Q2 — one isolated environment shared by two independently installable models: CustomVoice (Aiden, Ryan) and
  Base (the six clones), plus "install both". Since v0.7.0 P04C it is always installed at ``.venv/engines/qwen3``,
  created there directly from the verified base CPython 3.12 (never from the app's own interpreter); an older
  ``.venv-qwen3`` is used while it is the only engine and is never installed into, rebuilt or deleted here.
* Sizes are stated BEFORE anything is acquired (:func:`plan_install` / :func:`describe_plan`), files that are already
  present and intact are reused, bytes both models share are fetched once, and nothing is ever downloaded on ordinary
  launch: the only caller is the in-app "Install / repair Qwen3 voices" dialog.
* Windows only for now (Q4): other platforms are refused with the same "not yet available" sentence the status uses.

Everything is blocking and written for a worker thread; progress and cancellation are callbacks. Nothing here touches
Tk. Network, subprocess and clock seams are parameters so every branch is testable offline.

The three things that can go wrong on a user's machine each have an explicit, bounded answer:

* an interrupted download keeps a ``.part`` file and resumes from it (HTTP ``Range``) up to a bounded number of
  attempts; a finished file is accepted only when its size AND SHA-256 match the tracked manifest;
* an interrupted or cancelled environment install is simply reported as incomplete, and the next attempt continues
  (pip's own download cache is kept until a full success, then removed to give the disk space back);
* a corrupt file is found by the full check, deleted, and fetched again; nothing else is touched.
"""

from __future__ import annotations

import contextlib
import contextvars
import http.client
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from shared import venv_layout
from tts import qwen3_process
from tts import qwen3_runtime as rt
from tts.qwen3_runtime import MODEL_BASE, MODEL_CUSTOMVOICE, MODEL_KEYS, Qwen3Unavailable

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: The evaluated stack is built for exactly this interpreter (every pin was resolved and tested on CPython 3.12).
SUPPORTED_PYTHON = (3, 12)
PYTORCH_INDEX = "https://download.pytorch.org/whl/cu128"
PYPI_INDEX = "https://pypi.org/simple"
HUB_URL = "https://huggingface.co/{repo}/resolve/{revision}/{path}"

DOWNLOAD_BLOCK = 1 << 20
READ_TIMEOUT_S = 20.0  # also bounds how long a Cancel can wait on a stalled connection
MAX_ATTEMPTS = 5
BACKOFF_S = (2.0, 5.0, 15.0, 30.0)
#: Free space kept in reserve beyond the bytes an install itself needs (temp files, hashing, the OS).
DISK_MARGIN_BYTES = 2 * 10**9
PIP_SUMMARY_LINES = 4


class SetupError(RuntimeError):
    """An install, verify or repair step failed. The message is fit to show a non-technical user."""


class SetupCancelled(Exception):
    """The user cancelled. Whatever was completed is kept; the next attempt continues from it."""


@dataclass(frozen=True)
class Progress:
    step: str  # environment | model:customvoice | model:base | verify
    message: str
    done_bytes: int = 0
    total_bytes: int = 0  # 0 = not a byte-counted step

    @property
    def fraction(self) -> Optional[float]:
        return min(1.0, self.done_bytes / self.total_bytes) if self.total_bytes else None


ProgressCallback = Callable[[Progress], None]
CancelCheck = Callable[[], bool]


def _noop_progress(_: Progress) -> None:
    pass


def _check_cancel(cancel_check: Optional[CancelCheck]) -> None:
    if cancel_check is not None and cancel_check():
        raise SetupCancelled()


# --------------------------------------------------------------------------- #
# The plan: what would be acquired, in bytes, before anything is
# --------------------------------------------------------------------------- #
@dataclass
class FilePlan:
    name: str
    size: int
    sha256: str
    action: str  # "have" (size/hash verified) | "share" (copy from the other model) | "download"
    source_dir: Optional[Path] = None  # for "share"


@dataclass
class ModelPlan:
    key: str
    label: str
    total_bytes: int
    files: list[FilePlan]
    installed: bool  # verified marker present and intact

    @property
    def download_bytes(self) -> int:
        return sum(f.size for f in self.files if f.action == "download")

    @property
    def shared_bytes(self) -> int:
        return sum(f.size for f in self.files if f.action == "share")


@dataclass
class InstallPlan:
    components: tuple[str, ...]
    needs_environment: bool
    environment_download_bytes: int
    environment_installed_bytes: int
    models: list[ModelPlan]

    @property
    def download_bytes(self) -> int:
        return (self.environment_download_bytes if self.needs_environment else 0) + sum(
            m.download_bytes for m in self.models)

    @property
    def disk_bytes(self) -> int:
        """Space the install will occupy: the new environment plus every model file it still has to write."""
        models = sum(f.size for m in self.models for f in m.files if f.action in ("download", "share"))
        return (self.environment_installed_bytes if self.needs_environment else 0) + models

    @property
    def nothing_to_do(self) -> bool:
        return not self.needs_environment and all(m.installed for m in self.models)


def normalize_components(components: Iterable[str], *, allow_empty: bool = False) -> tuple[str, ...]:
    """Validate and order the request: any of ``customvoice``/``base``/``both``."""
    wanted: list[str] = []
    for component in components:
        names = list(MODEL_KEYS) if component == "both" else [component]
        for name in names:
            if name not in MODEL_KEYS:
                raise SetupError(f"Unknown Qwen3 component '{component}'.")
            if name not in wanted:
                wanted.append(name)
    if not wanted and not allow_empty:
        raise SetupError("Choose at least one Qwen3 model to install.")
    return tuple(k for k in MODEL_KEYS if k in wanted)


def _present_and_verified(spec: rt.ModelSpec, name: str, want: dict) -> bool:
    path = rt.safe_model_path(spec, name)
    return path.is_file() and path.stat().st_size == want["size"] and rt.sha256_file(path) == want["sha256"]


def plan_install(components: Iterable[str]) -> InstallPlan:
    """What an install of ``components`` would have to acquire. Read-only full content proof; no network.

    A file counts as ``have`` when its size AND hash match (installation rechecks before trusting it), as
    ``share`` when the other model — installed or being installed in the same request — holds an identical file, and
    as ``download`` otherwise.
    """
    keys = normalize_components(components)
    env_ok, _ = rt.environment_status()
    specs = {k: rt.model_spec(k) for k in MODEL_KEYS}
    plans: list[ModelPlan] = []
    for key in keys:
        spec = specs[key]
        ok, _ = rt.model_status(key)
        other = specs[MODEL_BASE if key == MODEL_CUSTOMVOICE else MODEL_CUSTOMVOICE]
        files: list[FilePlan] = []
        for name, want in spec.files.items():
            if _present_and_verified(spec, name, want):
                files.append(FilePlan(name, want["size"], want["sha256"], "have"))
                continue
            identical_in_other = other.files.get(name) == want
            on_disk = identical_in_other and _present_and_verified(other, name, want)
            installed_earlier_in_this_request = (
                identical_in_other and other.key in keys and keys.index(other.key) < keys.index(key))
            if on_disk or installed_earlier_in_this_request:
                files.append(FilePlan(name, want["size"], want["sha256"], "share", other.directory))
            else:
                files.append(FilePlan(name, want["size"], want["sha256"], "download"))
        plans.append(ModelPlan(key, spec.label, spec.total_bytes, files,
                               installed=ok and all(f.action == 'have' for f in files)))
    return InstallPlan(
        components=keys, needs_environment=not env_ok,
        environment_download_bytes=rt.environment_download_bytes(),
        environment_installed_bytes=rt.environment_installed_bytes(), models=plans)


def describe_plan(plan: InstallPlan) -> list[str]:
    """The lines shown to the user before they confirm: what, how big, what is reused, what is needed on disk."""
    lines: list[str] = []
    if plan.nothing_to_do:
        return ["Everything you selected is already installed."]
    if plan.needs_environment:
        lines.append(f"Qwen3 voice engine: about {rt.format_bytes(plan.environment_download_bytes)} to download "
                     f"(about {rt.format_bytes(plan.environment_installed_bytes)} on disk).")
        lines.extend(legacy_engine_note())
    else:
        lines.append("Qwen3 voice engine: already installed.")
    for model in plan.models:
        if model.installed:
            lines.append(f"{model.label} model: already installed.")
            continue
        text = f"{model.label} model: {rt.format_bytes(model.total_bytes)}"
        notes = []
        reused = sum(f.size for f in model.files if f.action == "have")
        if reused:
            notes.append(f"{rt.format_bytes(reused)} already on this computer")
        if model.shared_bytes:
            notes.append(f"{rt.format_bytes(model.shared_bytes)} shared with the other model, not downloaded again")
        lines.append(text + (f" ({'; '.join(notes)})" if notes else "") + f" - download {rt.format_bytes(model.download_bytes)}.")
    lines.append(f"Total to download: {rt.format_bytes(plan.download_bytes)}. "
                 f"Disk space needed: about {rt.format_bytes(plan.disk_bytes + DISK_MARGIN_BYTES)}.")
    return lines


def legacy_engine_note() -> list[str]:
    """Said before the engine is installed or rebuilt on a computer that still has an older ``.venv-qwen3``: the install
    goes to the canonical place and leaves that folder exactly as it is (never a silent move, rebuild or delete)."""
    if not os.path.lexists(rt.legacy_venv_dir()):
        return []
    return [f"The voice engine is installed in its new place ({rt.shown_path(rt.nested_venv_dir())}). The older "
            f"{venv_layout.LEGACY_QWEN3} folder from an earlier version is not changed or deleted, and is no longer "
            "used once the new engine works; it stays until you remove it."]


def both_total_download_bytes() -> int:
    """What 'Install Both' downloads for the two models (the shared files counted once), without the environment."""
    return rt.model_spec(MODEL_CUSTOMVOICE).total_bytes + rt.model_spec(MODEL_BASE).total_bytes - rt.shared_file_bytes()


# --------------------------------------------------------------------------- #
# Locking: one installer at a time, and never while a conversion is using the voices
# --------------------------------------------------------------------------- #
_PROCESS_LOCK = threading.Lock()
_HOLDER: Optional[int] = None  # the thread holding the process's InstallLock, while one does


class InstallLock:
    """Exclusive right to change the Qwen3 installation.

    Two operating-system file locks plus an in-process lock: ``setup.lock`` keeps two installs/repairs of THIS copy apart
    -- and keeps a repair of the app's own environment (``shared.engine_lease``, which takes ``setup.lock`` first) from
    setting aside the folder an engine is being created in -- and ``inference.lock`` -- the same lock every Qwen3
    conversion of this copy holds while it runs -- keeps an install from replacing files a worker has open. Both live in
    this installation's own runtime folder, so they protect its files, not the machine: a separate copy of the app has
    its own files and its own locks. The GPU/RAM side -- one model loaded at a time across every copy -- is
    ``rt.MachineGuard``, taken by ``probe_environment`` and by every conversion and transcription. The operating system
    drops all of them when a process ends however it ends, so a crash can never leave a stale lock behind.

    ``engine.lock`` (held by a running worker itself) is checked, not kept: a worker whose app has gone holds nothing
    else, and installing under it would change files it is running. It is released at once because every worker this
    copy starts is started under ``inference.lock``, which this lock holds -- so none can start meanwhile except the
    installer's own probe, which must be able to take it.
    """

    def __init__(self) -> None:
        self._setup = rt.FileLock(rt.setup_lock_path())
        self._inference = rt.FileLock(rt.inference_lock_path())
        self._held = False

    @staticmethod
    def held_by_this_thread() -> bool:
        return _HOLDER == threading.get_ident()

    def acquire(self) -> None:
        global _HOLDER
        if not _PROCESS_LOCK.acquire(blocking=False):
            raise SetupError("The Qwen3 voices are already being installed or repaired. Wait for that to finish.")
        try:
            if not self._setup.acquire():
                raise SetupError("The Qwen3 voices of this copy of the app are already being installed or "
                                 "repaired, or the app's own environment is being repaired. Wait for that to finish.")
            if not self._inference.acquire():
                self._setup.release()
                raise SetupError("The Qwen3 voices are being used by a conversion right now. Let it finish, or cancel "
                                 "it, before installing or repairing.")
            engine = rt.FileLock(rt.engine_lock_path())
            try:
                free = engine.acquire()
            finally:
                engine.release()
            if not free:
                self._inference.release()
                self._setup.release()
                raise SetupError("The Qwen3 voice engine is still running (a conversion that has not stopped yet). "
                                 "Close the app and try again. Nothing was changed.")
            self._held = True
            _HOLDER = threading.get_ident()
        except BaseException:
            if not self._held:
                self._inference.release()
                self._setup.release()
            _PROCESS_LOCK.release()
            raise

    def release(self) -> None:
        global _HOLDER
        if self._held:
            self._inference.release()
            self._setup.release()
            self._held = False
            _HOLDER = None
            _PROCESS_LOCK.release()

    def __enter__(self) -> "InstallLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# --------------------------------------------------------------------------- #
# Downloading one file: resumable, bounded, verified
# --------------------------------------------------------------------------- #
Opener = Callable[[urllib.request.Request], object]


def _default_opener(request: urllib.request.Request):
    # ``urllib.request.urlopen`` on purpose: it is the one network door the test suite closes (conftest), so a test that
    # forgets to inject an opener fails loudly instead of downloading gigabytes.
    return urllib.request.urlopen(request, timeout=READ_TIMEOUT_S)


def hub_url(spec: rt.ModelSpec, name: str) -> str:
    return HUB_URL.format(repo=spec.repo, revision=spec.revision, path=name)


def download_file(url: str, destination: Path, size: int, sha256: str, *, opener: Optional[Opener] = None,
                  progress: Optional[Callable[[int], None]] = None, cancel_check: Optional[CancelCheck] = None,
                  sleep: Callable[[float], None] = time.sleep, attempts: int = MAX_ATTEMPTS) -> None:
    """Fetch ``url`` to ``destination``, resuming a ``.part`` file, and accept it only if size and SHA-256 match.

    ``progress(n)`` reports the bytes written by each block (including the bytes a resumed ``.part`` already held,
    reported once at the start). A cancel keeps the ``.part`` so the next attempt resumes. A file that downloads in
    full but fails its hash is deleted (resuming it would only reproduce the corruption) and fetched afresh, once per
    attempt, so a flaky link cannot loop forever.
    """
    open_url = opener or _default_opener
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    last_error = "unknown error"
    for attempt in range(max(attempts, 1)):
        _check_cancel(cancel_check)
        if rt.scratch_is_unsafe(part):
            rt.remove_entry(part)  # a link (or shared file) here would send the appended bytes somewhere else
        have = part.stat().st_size if part.is_file() else 0
        if have > size:
            part.unlink()
            have = 0
        if progress is not None and have and attempt == 0:
            progress(have)
        try:
            if have < size:
                _fetch_into(open_url, url, part, have, size, progress, cancel_check)
            if part.stat().st_size != size:
                raise SetupError(f"the downloaded file has {part.stat().st_size} bytes, expected {size}")
            if rt.sha256_file(part) != sha256:
                part.unlink()
                raise SetupError("the downloaded file does not match its expected SHA-256")
            os.replace(part, destination)
            return
        except SetupCancelled:
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, SetupError,
                ConnectionError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
                raise SetupError(f"The download was refused by the server (HTTP {exc.code}) for {destination.name}. "
                                 "Check your internet connection and try again later.") from exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 416:
                part.unlink(missing_ok=True)  # the partial file no longer fits what the server has: start that file over
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                _backoff(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)], sleep, cancel_check)
    raise SetupError(f"Could not download {destination.name} after {attempts} attempts ({last_error}). "
                     "Your progress is kept; run Install / repair again to continue.")


BACKOFF_SLICE_S = 0.5


def _backoff(delay: float, sleep: Callable[[float], None], cancel_check: Optional[CancelCheck]) -> None:
    """Wait out a retry delay in short slices so a Cancel is honoured within half a second, not after 30 seconds."""
    if cancel_check is None:
        sleep(delay)
        return
    remaining = delay
    while remaining > 0:
        _check_cancel(cancel_check)
        step = min(BACKOFF_SLICE_S, remaining)
        sleep(step)
        remaining -= step
    _check_cancel(cancel_check)


def _check_response(status: int, headers, have: int, size: int) -> None:
    """Refuse a response that cannot be the bytes the manifest describes, before writing any of them."""
    encoding = (headers.get("Content-Encoding") if headers is not None else None) or "identity"
    if encoding.lower() != "identity":
        raise SetupError(f"the server sent {encoding}-encoded data instead of the file")
    length = headers.get("Content-Length") if headers is not None else None
    if status == 206:
        expected = f"bytes {have}-{size - 1}/{size}"
        if headers is None or headers.get("Content-Range") != expected:
            raise SetupError("the server answered a different part of the file than was asked for")
    elif status == 200:
        if length is not None and int(length) != size:
            raise SetupError(f"the server's file is {length} bytes but {size} were expected")
    else:
        raise SetupError(f"unexpected HTTP status {status}")


def _fetch_into(open_url: Opener, url: str, part: Path, have: int, size: int,
                progress: Optional[Callable[[int], None]], cancel_check: Optional[CancelCheck]) -> None:
    """Append the rest of the file to ``part``, never writing more than the manifest says the file holds."""
    request = urllib.request.Request(url, headers={"User-Agent": "ACT-Qwen3-Setup", "Accept-Encoding": "identity"})
    if have:
        request.add_header("Range", f"bytes={have}-")
    with open_url(request) as response:
        status = getattr(response, "status", None) or response.getcode()
        _check_response(status, getattr(response, "headers", None), have, size)
        mode = "ab"
        if have and status == 200:  # the server ignored Range and is sending the whole file: start over
            mode, have = "wb", 0
        read = getattr(response, "read1", None) or response.read  # return what has arrived: a Cancel is not stuck on a stall
        with open(part, mode) as handle:
            written = have
            while True:
                _check_cancel(cancel_check)
                remaining = size - written
                block = read(min(DOWNLOAD_BLOCK, remaining + 1))  # one byte of slack: enough to notice a body that is too long
                if not block:
                    break
                if len(block) > remaining:
                    handle.write(block[:remaining])
                    raise SetupError(f"the server sent more data than the {size} bytes expected")
                handle.write(block)
                written += len(block)
                if progress is not None:
                    progress(len(block))
        if written != size:
            raise SetupError(f"the connection ended after {written} of {size} bytes")


# --------------------------------------------------------------------------- #
# Installing a model
# --------------------------------------------------------------------------- #
def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    rt.remove_entry(tmp)  # never write through a leftover link
    try:
        os.link(source, tmp)  # same volume: instant, no extra disk space
    except OSError:
        shutil.copyfile(source, tmp)
    os.replace(tmp, target)


def install_model(key: str, *, progress: ProgressCallback = _noop_progress, cancel_check: Optional[CancelCheck] = None,
                  opener: Optional[Opener] = None, seed_dirs: Iterable[Path] = (),
                  sleep: Callable[[float], None] = time.sleep, total_for_progress: Optional[int] = None,
                  base_done: int = 0, trusted: Optional[dict] = None) -> None:
    """Make one model's folder complete and verified, fetching only what is missing or wrong.

    Per file: an existing file with the right size is hashed and kept if it matches (and deleted if not); otherwise an
    identical verified file from the other model or from ``seed_dirs`` is linked/copied in; otherwise it is downloaded.
    The verified marker is written last, so a model is never reported installed while any file is unchecked.
    ``trusted`` maps file names to ``(size, mtime_ns)`` for files a full check has just proved good: those are not
    hashed again if they are unchanged. Every target path is proved to lie inside this model's own folder first.
    """
    authority = _MODEL_ACQUISITION.get()
    if authority is not None:
        authority.before_model(key)  # before marker deletion or any file/package mutation
    spec = rt.model_spec(key)
    other = rt.model_spec(MODEL_BASE if key == MODEL_CUSTOMVOICE else MODEL_CUSTOMVOICE)
    step = f"model:{key}"
    total = total_for_progress if total_for_progress is not None else spec.total_bytes
    done = base_done
    marker = rt.safe_model_path(spec, rt.MARKER_NAME)  # proves the model folder is not a link BEFORE anything is deleted
    marker.unlink(missing_ok=True)  # until every file is verified again, this model is not "installed"

    def report(message: str, delta: int = 0) -> None:
        nonlocal done
        done += delta
        progress(Progress(step, message, done, total))

    for name, want in spec.files.items():
        _check_cancel(cancel_check)
        target = rt.safe_model_path(spec, name)
        if authority is not None:
            authority.ensure_file(key, name, target)
            report(f"{name}: verified under v3 authority.", want["size"])
            continue  # no legacy downloader, twin fallback or implicit retries in the scoped path
        if target.is_file() and target.stat().st_size == want["size"]:
            stat = target.stat()
            if trusted and trusted.get(name) == (stat.st_size, stat.st_mtime_ns):
                report(f"{name}: already checked.", want["size"])
                continue
            report(f"Checking {name}...")
            if rt.sha256_file(target) == want["sha256"]:
                report(f"{name}: already installed.", want["size"])
                continue
            target.unlink()  # same size, wrong content: never keep it
        elif target.is_file():
            target.unlink()
        twin = _find_local_twin(name, want, [rt.safe_model_path(other, name), *(Path(d) / name for d in seed_dirs)])
        if twin is not None:
            report(f"Reusing {name} from this computer...")
            _link_or_copy(twin, target)
            report(f"{name}: reused, not downloaded again.", want["size"])
            continue
        report(f"Downloading {name} ({rt.format_bytes(want['size'])})...")
        download_file(hub_url(spec, name), target, want["size"], want["sha256"], opener=opener,
                      progress=lambda n: report(f"Downloading {name} ({rt.format_bytes(want['size'])})...", n),
                      cancel_check=cancel_check, sleep=sleep)  # reports a resumed .part's bytes on its first call
    problems = rt.model_file_problems(key, full=authority is not None)
    if problems:
        raise SetupError(f"The {spec.label} model is incomplete after installing ({problems[0]}).")
    rt.write_model_marker(key)
    report(f"{spec.label} model installed.")


def _find_local_twin(name: str, want: dict, candidates: Iterable[Path]) -> Optional[Path]:
    """The first candidate file that is present with exactly this size AND SHA-256 (another model's copy, or a seed)."""
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size == want["size"] and \
                    rt.sha256_file(candidate) == want["sha256"]:
                return candidate
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------- #
# The isolated environment
# --------------------------------------------------------------------------- #
CommandRunner = Callable[..., int]


def run_command(cmd: list[str], *, env: dict, cwd: Path, on_line: Callable[[str], None],
                cancel_check: Optional[CancelCheck] = None) -> int:
    """Run a command to completion, streaming its combined output line by line; stop it if the user cancels."""
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    try:
        proc = qwen3_process.spawn(cmd, require_job=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   env=env, cwd=str(cwd))
    except qwen3_process.ContainmentUnavailable as exc:
        raise SetupError("Windows would not let this app keep control of the install, so it was not started "
                         f"(it could not be stopped safely if you cancelled). ({exc})") from exc

    def pump() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                lines.put(line.rstrip("\r\n"))
        finally:
            lines.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while True:
            if cancel_check is not None and cancel_check():
                qwen3_process.kill_tree(proc)
                raise SetupCancelled()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if line:
                on_line(line)
        proc.wait(timeout=30)
        return proc.returncode if proc.returncode is not None else -1
    except BaseException:
        qwen3_process.kill_tree(proc)
        raise
    finally:
        reader.join(timeout=5)
        if not reader.is_alive() and proc.stdout is not None:
            proc.stdout.close()
        qwen3_process.release(proc)


def installer_environment() -> dict:
    """The environment pip and the probe run in: isolated, with caches inside the repository tree."""
    env = rt.worker_environment()
    for name in [k for k in env if k.upper().startswith("PIP_")]:
        del env[name]  # ambient pip settings (PIP_TARGET, PIP_INDEX_URL, ...) must never steer this install
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
    env.pop("HF_HUB_OFFLINE", None)  # pip does not use it; kept off the installer for clarity
    return env


def clear_scratch() -> None:
    """Remove the installer's scratch folder (partial downloads and build leftovers). Best effort."""
    shutil.rmtree(rt.tmp_root(), ignore_errors=True)


def pip_cache_dir() -> Path:
    return rt.cache_root() / "pip"


def base_python_candidate() -> Path:
    """The base interpreter this app's environment was built from (``sys._base_executable``), as ``python.exe``.

    Never the app's own ``.venv`` interpreter: an environment built from another environment's interpreter depends on
    it (``pyvenv.cfg`` records it), and the engine must not depend on the environment that holds it. ``pythonw.exe``
    has no output, so ``python.exe`` beside it is used.
    """
    exe = Path(getattr(sys, "_base_executable", "") or sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.with_name("python.exe")).is_file():
        return exe.with_name("python.exe")
    return exe


#: Run with ``-I`` by :func:`verified_base_python`: what the candidate interpreter really is, asked of itself.
_BASE_PROBE_MARK = "@@BASE "
_BASE_PROBE = ("import json, sys; print('" + _BASE_PROBE_MARK + "' + json.dumps({'version': list(sys.version_info[:3]), "
               "'implementation': sys.implementation.name, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
               "'executable': sys.executable}))")


def _base_refusal(candidate: Path, why: str) -> SetupError:
    return SetupError(f"The Qwen3 voice engine is built with the Python {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]} "
                      f"this app was installed with, and {candidate} cannot be used for it: {why}. Run the app's "
                      "Setup_and_Run to repair its Python, then try again. Nothing was installed.")


def verified_base_python(*, runner: CommandRunner, cancel_check: Optional[CancelCheck] = None) -> Path:
    """:func:`base_python_candidate`, proved to be a base CPython 3.12 that no environment owns, or :class:`SetupError`.

    Checked on disk (a file, not a link, outside this app's folder, no ``pyvenv.cfg`` beside or above it) and then by
    running it in isolated mode: it must report CPython 3.12, ``sys.prefix == sys.base_prefix`` (not an environment)
    and itself as its executable.
    """
    import json

    candidate = base_python_candidate()
    if not candidate.is_absolute() or not candidate.is_file():
        raise _base_refusal(candidate, "it is not there")
    if venv_layout.is_link(candidate):
        raise _base_refusal(candidate, "it is a link")
    if venv_layout.is_within(rt.repo_root(), candidate):
        raise _base_refusal(candidate, "it is inside this app's folder, so it belongs to an environment")
    if any((folder / "pyvenv.cfg").is_file() for folder in (candidate.parent, candidate.parent.parent)):
        raise _base_refusal(candidate, "it belongs to a virtual environment")
    lines: list[str] = []
    code = runner([str(candidate), "-I", "-c", _BASE_PROBE], env=installer_environment(), cwd=rt.repo_root(),
                  on_line=lines.append, cancel_check=cancel_check)
    report = None
    for line in lines:
        if line.startswith(_BASE_PROBE_MARK):
            try:
                report = json.loads(line[len(_BASE_PROBE_MARK):])
            except ValueError:
                report = None
    if code != 0 or not isinstance(report, dict):
        raise _base_refusal(candidate, "it did not start")
    if report.get("implementation") != "cpython" or list(report.get("version") or [])[:2] != list(SUPPORTED_PYTHON):
        shown = ".".join(str(part) for part in report.get("version") or []) or "an unknown version"
        raise _base_refusal(candidate, f"it is {report.get('implementation')} {shown}")
    if not venv_layout.same_path(report.get("prefix", ""), report.get("base_prefix", "")):
        raise _base_refusal(candidate, "it is a virtual environment's interpreter")
    if not venv_layout.same_path(report.get("executable", ""), candidate):
        raise _base_refusal(candidate, "it reports a different interpreter")
    return candidate


def check_python() -> None:
    """The evaluated wheels are cp312 builds; refuse early and clearly on any other interpreter."""
    if sys.version_info[:2] != SUPPORTED_PYTHON:
        raise SetupError(
            f"The Qwen3 voices need Python {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]}, but this app is running on "
            f"Python {sys.version_info[0]}.{sys.version_info[1]}. Nothing was installed.")


def parent_problem() -> str:
    """Why the canonical engine cannot be created inside the app's ``.venv`` right now, or ``""``.

    The parent must be a real environment at its own path, and no repair of it may be pending: a set-aside
    ``.venv.replaced`` means the last repair did not finish, and only the app's own setup/repair resolves it.
    """
    parent = rt.parent_venv_dir()
    if venv_layout.unsafe_component(rt.repo_root(), parent) is not None:
        return ("The app's own environment (.venv) is reached through a link, so the Qwen3 voice engine is not "
                "installed inside it. Nothing was installed.")
    if not (parent / "pyvenv.cfg").is_file():
        return ("The app's own environment (.venv) is missing or incomplete, so the Qwen3 voice engine cannot be "
                "installed inside it. Run the app's Setup_and_Run first. Nothing was installed.")
    try:
        pending = sorted(entry.name for entry in os.scandir(parent.parent)
                         if entry.name.startswith(parent.name + ".replaced"))
    except OSError:
        pending = [".venv.replaced"]
    if pending:
        return (f"A repair of the app's own environment did not finish ({pending[0]} is still there). Run the app's "
                "Setup_and_Run to finish it, then install the Qwen3 voices. Nothing was installed.")
    return ""


def safe_to_remove_environment(path: Path) -> bool:
    """Only the canonical engine folder ``.venv/engines/qwen3``, only inside the repo and reached through no link, and only
    if it really is a virtual environment -- or one this app's own install record says it was creating or removing
    there (an interrupted step leaves no ``pyvenv.cfg`` behind). The legacy ``.venv-qwen3`` is never removable here."""
    try:
        path = Path(path)
        if not venv_layout.same_path(path, rt.nested_venv_dir()):
            return False
        if rt.is_link(path) or rt.link_below_root(path) is not None:
            return False  # deleting through a link/junction, here or in any folder above it, could remove somebody else's
        resolved = path.resolve()
        if not (resolved.is_dir() and resolved.is_relative_to(rt.repo_root().resolve())):
            return False
        if (resolved / "pyvenv.cfg").is_file():
            return True
        return rt.environment_record(path).get("stage") in (rt.STAGE_CREATING, rt.STAGE_REMOVING)
    except OSError:
        return False


_PIP_DOWNLOADING = re.compile(r"^Downloading (\S+) \(([\d.]+) ?([kKMG]?B)\)")
_PIP_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)$")
_UNITS = {"B": 1, "kB": 10**3, "KB": 10**3, "MB": 10**6, "GB": 10**9}
PIP_PROGRESS_STEP = 8 * 1024 * 1024  # report a download at most every 8 MiB


class PipProgress:
    """Turns pip's ``--progress-bar raw`` lines into byte-counted :class:`Progress` events.

    pip prints nothing incremental when its output is a pipe, so a 2.9 GB wheel would look frozen. In raw mode it prints
    ``Progress <done> of <total>`` per block; this keeps a running total over every wheel (against the manifest's
    approximate download size) and a per-wheel message, and throttles to one event per few MiB. Lines it does not
    recognise are left to the caller.
    """

    def __init__(self, emit: ProgressCallback, total_bytes: int, step: str = "environment") -> None:
        self._emit, self._total, self._step = emit, total_bytes, step
        self._finished = 0  # bytes of wheels already complete
        self._name, self._size = "", 0
        self._last = -PIP_PROGRESS_STEP

    def feed(self, line: str) -> bool:
        line = line.strip()  # pip indents its download line under --require-hashes
        match = _PIP_DOWNLOADING.match(line)
        if match:
            if match.group(1).endswith(".metadata"):
                return False  # a tiny metadata fetch before the real download: neither a wheel nor progress
            self._finished += self._size  # the previous wheel (if any) is now complete
            self._name = match.group(1).rsplit("/", 1)[-1].split("%2B")[0]
            self._size = int(float(match.group(2)) * _UNITS.get(match.group(3), 1))
            self._last = -PIP_PROGRESS_STEP
            return False  # the caller still shows the "Downloading ..." line itself
        match = _PIP_PROGRESS.match(line)
        if match is None:
            return False
        done, size = int(match.group(1)), int(match.group(2))
        self._size = size
        if done - self._last >= PIP_PROGRESS_STEP or done >= size:
            self._last = done
            self._emit(Progress(self._step, f"Downloading {self._name}: {rt.format_bytes(done)} of "
                                            f"{rt.format_bytes(size)}", self._finished + done, self._total))
        return True


@contextlib.contextmanager
def install_lock_held():
    """:class:`InstallLock` for the block: taken here, or the one this thread already holds (never taken twice, which
    would refuse itself: two handles on one lock conflict even inside one process)."""
    if InstallLock.held_by_this_thread():
        yield
        return
    with InstallLock():
        yield


_MODEL_ACQUISITION = contextvars.ContextVar('qwen3_model_acquisition', default=None)


@contextlib.contextmanager
def scoped_model_acquisition(authority):
    """Internal 4B-3A contract: caller holds InstallLock, native model files use its authority.

    CLI/manual callers retain their existing contract outside this scope. Environment
    execution is deliberately forbidden here until 4B-3B, including explicit rebuild terms.
    """
    if not InstallLock.held_by_this_thread() or _MODEL_ACQUISITION.get() is not None:
        raise SetupError('Scoped model acquisition requires one already-held InstallLock.')
    token = _MODEL_ACQUISITION.set(authority)
    try:
        yield
    finally:
        _MODEL_ACQUISITION.reset(token)


def install_environment(*, progress: ProgressCallback = _noop_progress, cancel_check: Optional[CancelCheck] = None,
                        runner: Optional[CommandRunner] = None, rebuild: bool = False) -> dict:
    """Create the canonical ``.venv/engines/qwen3``, install the pinned stack, prove it imports, and record the result.

    Returns the probe report. A failure raises :class:`SetupError` carrying the tail of pip's own output. With
    ``rebuild`` an existing canonical environment is removed first (only ever that folder — see
    :func:`safe_to_remove_environment`; the legacy ``.venv-qwen3`` is never touched). pip's download cache is kept
    after a failure or cancel (so a retry does not start over) and removed after a full success.

    :class:`InstallLock` is held from the first check to the last record (taken here if the caller does not hold it),
    so a repair of the app's environment -- which needs ``setup.lock`` first -- can never set the parent aside between
    the checks and the creation of the folder inside it. The environment is created at its final path, directly from
    the verified base interpreter, and the identity of that interpreter is recorded outside the parent.
    """
    with install_lock_held():
        return _install_environment(progress, cancel_check, runner or run_command, rebuild)


def _install_environment(progress: ProgressCallback, cancel_check: Optional[CancelCheck], runner: CommandRunner,
                         rebuild: bool) -> dict:
    if _MODEL_ACQUISITION.get() is not None:
        raise SetupError('Environment mutation is not authorized in Stage 4B-3A model acquisition.')
    check_python()
    requirements = rt.requirements_path()
    if not requirements.is_file():
        raise SetupError("The Qwen3 requirements file is missing from this copy of the app; reinstall the app.")
    venv = rt.nested_venv_dir()
    problem = rt.environment_location_problem(venv) or parent_problem()
    if problem:
        raise SetupError(problem)  # never run pip in, create or delete an environment that is not provably the app's own
    step = "environment"
    tail: list[str] = []

    pip_progress = PipProgress(progress, rt.environment_download_bytes())

    def on_line(line: str) -> None:
        if pip_progress.feed(line):
            return  # a byte-counted progress line: shown as progress, not kept as log text
        tail.append(line)
        del tail[:-40]
        shown = line.strip()
        if shown.startswith(("Collecting", "Downloading", "Installing collected", "Successfully", "Building", "Using cached")):
            progress(Progress(step, shown[:140]))

    unfinished = rt.environment_record(venv).get("stage") in (rt.STAGE_CREATING, rt.STAGE_REMOVING)
    if os.path.lexists(venv) and (rebuild or unfinished):
        if not safe_to_remove_environment(venv):
            raise SetupError(f"Refusing to delete {venv}: it is not the Qwen3 environment this app created. Move it out "
                             "of the app's folder yourself, then run Install / repair again.")
        progress(Progress(step, "Clearing an install that did not finish..." if unfinished and not rebuild
                          else "Removing the old Qwen3 environment..."))
        rt.record_environment_stage(venv, rt.STAGE_REMOVING)
        shutil.rmtree(venv)
        rt.clear_environment_state(venv)
    elif os.path.lexists(venv):
        assessment = rt.nested_assessment(venv)
        if not assessment.identity_ok:  # pip is never run into an environment that cannot be shown to be the app's own
            raise SetupError(f"The Qwen3 voice engine in {rt.shown_path(venv)} cannot be verified ({assessment.reason}), "
                             "so it was left as it is. Choose \"Check and repair\" to rebuild it.")
    env = installer_environment()
    cwd = rt.repo_root()
    python = venv_layout.interpreter(venv)
    if not os.path.lexists(venv):
        base = verified_base_python(runner=runner, cancel_check=cancel_check)
        progress(Progress(step, "Creating the isolated Python environment..."))
        rt.record_environment_stage(venv, rt.STAGE_CREATING)
        code = runner([str(base), "-I", "-m", "venv", str(venv)], env=env, cwd=cwd, on_line=on_line,
                      cancel_check=cancel_check)
        if code != 0 or not python.is_file():
            raise SetupError("The isolated Python environment could not be created. " + _tail_text(tail))
        built = venv_layout.read_pyvenv_cfg(venv) or {}
        if not venv_layout.same_path(built.get("home", ""), base.parent) or \
                not venv_layout.same_path(built.get("executable") or base, base):
            raise SetupError("The isolated Python environment was not built from the Python it was created with, so it "
                             "is not used. Choose \"Check and repair\" to rebuild it.")
        rt.record_environment_stage(venv, rt.STAGE_CREATED)
        assessment = rt.nested_assessment(venv)
        if not assessment.identity_ok:
            raise SetupError(f"The isolated Python environment could not be verified ({assessment.reason}). Choose "
                             "\"Check and repair\" to rebuild it.")
    _check_cancel(cancel_check)
    progress(Progress(step, f"Installing the Qwen3 packages (about {rt.format_bytes(rt.environment_download_bytes())})..."))
    # --isolated ignores pip configuration files and PIP_* variables; --require-virtualenv refuses to touch anything but a
    # virtual environment; --require-hashes installs only the exact artifacts whose SHA-256 the requirements file lists.
    code = runner([str(python), "-m", "pip", "install", "--isolated", "--require-virtualenv",
                   "--require-hashes", "--no-input", "--disable-pip-version-check", "--cache-dir",
                   str(pip_cache_dir()), "--progress-bar", "raw", "--no-deps", "--index-url", PYTORCH_INDEX,
                   "--extra-index-url", PYPI_INDEX, "-r", str(requirements)],
                  env=env, cwd=cwd, on_line=on_line, cancel_check=cancel_check)
    if code != 0:
        raise SetupError("Installing the Qwen3 packages failed (check your internet connection, then run "
                         "Install / repair again; your progress is kept). " + _tail_text(tail))
    probe = probe_environment(runner=runner, progress=progress, cancel_check=cancel_check)
    rt.write_environment_state(probe, venv)
    shutil.rmtree(pip_cache_dir(), ignore_errors=True)  # a full success gives the download cache's disk space back
    clear_scratch()
    progress(Progress(step, "The Qwen3 voice engine is installed."))
    return probe


def _tail_text(tail: list[str], count: int = PIP_SUMMARY_LINES) -> str:
    return " ".join(line.strip() for line in tail[-count:] if line.strip())


def probe_environment(*, model_dir: Optional[Path] = None, runner: Optional[CommandRunner] = None,
                      progress: ProgressCallback = _noop_progress, cancel_check: Optional[CancelCheck] = None) -> dict:
    """Run the worker's ``probe`` job: import the whole stack, report GPU/CPU and versions; optionally load a model."""
    import json

    runner = runner or run_command

    step = "verify"
    jobs = rt.ensure_runtime_dir(rt.runtime_dir() / "probe")
    job_path = jobs / f"probe-job-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"  # unique: two probes never share a job file
    job = {"kind": "probe", "device": "auto", "dtype": "bfloat16", "attn": "sdpa",
           "engine_lock": str(rt.engine_lock_path())}
    if model_dir is not None:
        job["model_dir"] = str(model_dir)
    job_path.write_text(json.dumps(job), encoding="utf-8")
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

    progress(Progress(step, "Checking that the Qwen3 voice engine starts..." if model_dir is None
                      else "Checking that the model loads..."))
    # The probe starts CUDA and may load a whole model, so it takes the same machine-wide guard as a conversion: another
    # copy of the app cannot be loading a model at the same moment. (Downloads do not need it and do not hold it.)
    guard = rt.MachineGuard()
    try:
        if not guard.acquire():
            raise SetupError(guard.refusal_message + " Everything downloaded so far is kept.")
        code = runner([str(rt.venv_python()), str(rt.worker_script()), str(job_path)],
                      env=rt.worker_environment(), cwd=jobs, on_line=on_line, cancel_check=cancel_check)
    finally:
        guard.release()
        job_path.unlink(missing_ok=True)
    failed = next((e for e in events if e.get("event") == "failed"), None)
    report = next((e for e in events if e.get("event") == "probe"), None)
    if failed is not None or report is None or code != 0:
        detail = (failed or {}).get("message") or _tail_text(other)
        raise SetupError(f"The Qwen3 voice engine did not start correctly: {detail}".strip())
    return {k: v for k, v in report.items() if k != "event"}


# --------------------------------------------------------------------------- #
# The top-level operations the dialog calls
# --------------------------------------------------------------------------- #
@dataclass
class SetupResult:
    ok: bool
    message: str
    cancelled: bool = False
    steps: list[str] = field(default_factory=list)


def refuse_if_unsupported() -> None:
    if not rt.platform_supported():
        raise SetupError(rt.platform_reason())


def free_bytes(path: Path) -> int:
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def install(components: Iterable[str], *, progress: ProgressCallback = _noop_progress,
            cancel_check: Optional[CancelCheck] = None, opener: Optional[Opener] = None,
            runner: Optional[CommandRunner] = None, seed_dirs: Iterable[Path] = (),
            disk_free: Callable[[Path], int] = free_bytes, sleep: Callable[[float], None] = time.sleep,
            load_check: bool = True) -> SetupResult:
    """Install the selected models (and the environment if it is missing), verifying every step.

    Never raises for an expected problem: the result carries a sentence for the user. A cancel returns a result with
    ``cancelled=True`` after keeping everything completed so far.
    """
    steps: list[str] = []
    try:
        refuse_if_unsupported()
        plan = plan_install(components)
        if plan.nothing_to_do:
            return SetupResult(True, "Everything you selected is already installed.", steps=steps)
        needed = plan.disk_bytes + DISK_MARGIN_BYTES
        available = disk_free(rt.repo_root())
        if available < needed:
            return SetupResult(False, f"Not enough free disk space: this install needs about {rt.format_bytes(needed)} "
                                      f"and {rt.format_bytes(available)} is free. Nothing was downloaded.")
        with InstallLock():
            if plan.needs_environment:
                install_environment(progress=progress, cancel_check=cancel_check, runner=runner)
                steps.append("environment")
            model_total = sum(m.total_bytes for m in plan.models if not m.installed)
            base = 0
            for model in plan.models:
                if model.installed:
                    continue
                install_model(model.key, progress=progress, cancel_check=cancel_check, opener=opener,
                              seed_dirs=seed_dirs, sleep=sleep, total_for_progress=model_total, base_done=base)
                base += model.total_bytes
                steps.append(f"model:{model.key}")
                if load_check:
                    probe_environment(model_dir=rt.model_spec(model.key).directory, runner=runner,
                                      progress=progress, cancel_check=cancel_check)
                    steps.append(f"verified:{model.key}")
        return SetupResult(True, "The Qwen3 voices you selected are installed.", steps=steps)
    except SetupCancelled:
        return SetupResult(False, "Cancelled. What was completed is kept; run Install / repair again to continue.",
                           cancelled=True, steps=steps)
    except (SetupError, Qwen3Unavailable) as exc:
        return SetupResult(False, str(exc), steps=steps)
    except OSError as exc:
        return SetupResult(False, f"The install stopped because of a file or disk problem: {exc}", steps=steps)


def verify(components: Iterable[str], *, progress: ProgressCallback = _noop_progress,
           cancel_check: Optional[CancelCheck] = None) -> dict[str, list[str]]:
    """Fully check (size and SHA-256 of every file) the selected installed models. Returns ``{model: [problems]}``."""
    result: dict[str, list[str]] = {}
    for key in normalize_components(components):
        spec = rt.model_spec(key)
        done = 0

        def count(n: int, label=spec.label) -> None:
            nonlocal done
            done += n
            progress(Progress(f"model:{key}", f"Checking the {label} model...", done, spec.total_bytes))
            _check_cancel(cancel_check)

        result[key] = rt.model_file_problems(key, full=True, progress=count)
    return result


@dataclass
class RepairPlan:
    """What a full check found, and so what a repair would have to do. Built read-only; nothing is changed by it."""

    components: tuple[str, ...]
    rebuild_environment: bool
    environment_reason: str
    bad_files: dict[str, list[tuple[str, str]]]  # model key -> [(file, what is wrong)]
    verified: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)  # files proved good: (size, mtime_ns)
    unmarked: list[str] = field(default_factory=list)  # models whose files are all good but whose verified marker is not

    @property
    def model_download_bytes(self) -> int:
        return sum(rt.model_spec(key).files[name]["size"] for key, bad in self.bad_files.items() for name, _ in bad)

    @property
    def download_bytes(self) -> int:
        return (rt.environment_download_bytes() if self.rebuild_environment else 0) + self.model_download_bytes

    @property
    def nothing_to_do(self) -> bool:
        return not self.rebuild_environment and not any(self.bad_files.values()) and not self.unmarked


def analyze_repair(components: Iterable[str], *, progress: ProgressCallback = _noop_progress,
                   cancel_check: Optional[CancelCheck] = None, runner: Optional[CommandRunner] = None) -> RepairPlan:
    """Check everything that is installed -- the engine (does it actually start?) and every model file (SHA-256) --
    without changing a thing, so the user can be told what a repair would download before anything is.

    The engine is probed even when its files and install record look intact: an antivirus that removed one DLL leaves
    every record valid and the voices broken. ``components`` may be empty (an engine with no models yet).
    """
    runner = runner or run_command
    refuse_if_unsupported()
    keys = normalize_components(components, allow_empty=True)
    # The probe starts the engine and the check reads every model file: neither may overlap an install, a repair in
    # another copy of the app, or a conversion that has the engine and the GPU.
    with InstallLock():
        return _analyze(keys, progress, cancel_check, runner)


def _analyze(keys: tuple[str, ...], progress: ProgressCallback, cancel_check: Optional[CancelCheck],
             runner: CommandRunner) -> RepairPlan:
    rebuild, reason = False, ""
    env_ok, env_reason = rt.environment_status()
    if not env_ok:
        rebuild, reason = True, env_reason
    else:
        try:
            probe_environment(runner=runner, progress=progress, cancel_check=cancel_check)
        except SetupError as exc:
            rebuild, reason = True, str(exc)
    bad: dict[str, list[tuple[str, str]]] = {}
    verified: dict[str, dict[str, tuple[int, int]]] = {}
    unmarked: list[str] = []
    for key in keys:
        spec = rt.model_spec(key)
        done = 0

        def count(n: int, label: str = spec.label, key: str = key, total: int = spec.total_bytes) -> None:
            nonlocal done
            done += n
            progress(Progress(f"model:{key}", f"Checking the {label} model...", done, total))
            _check_cancel(cancel_check)

        bad[key] = rt.model_bad_files(key, full=True, progress=count)
        bad_names = {name for name, _ in bad[key]}
        verified[key] = {}
        for name in spec.files:
            if name not in bad_names:
                stat = rt.safe_model_path(spec, name).stat()
                verified[key][name] = (stat.st_size, stat.st_mtime_ns)
        if not bad[key] and not rt.model_status(key)[0]:
            unmarked.append(key)  # every file is right, but the verified record is missing, unreadable or for another version
    return RepairPlan(keys, rebuild, reason, bad, verified, unmarked)


def describe_repair(plan: RepairPlan) -> list[str]:
    """The lines shown before a repair is confirmed: what is wrong and what it would download."""
    if plan.nothing_to_do:
        return ["Everything checks out. Nothing needs repair."]
    lines = []
    if plan.rebuild_environment:
        lines.append(f"Qwen3 voice engine: needs to be rebuilt ({_first_sentence(plan.environment_reason)}) - about "
                     f"{rt.format_bytes(rt.environment_download_bytes())} to download.")
        lines.extend(legacy_engine_note())
    for key, bad in plan.bad_files.items():
        if bad:
            spec = rt.model_spec(key)
            size = sum(spec.files[name]["size"] for name, _ in bad)
            lines.append(f"{spec.label} model: {len(bad)} of {len(spec.files)} files are missing or damaged "
                         f"({', '.join(name for name, _ in bad[:3])}{'...' if len(bad) > 3 else ''}) - "
                         f"download {rt.format_bytes(size)}.")
    for key in plan.unmarked:
        lines.append(f"{rt.model_spec(key).label} model: every file is intact, but it is not recorded as verified - it "
                     "will be marked again (nothing to download).")
    lines.append(f"Total to download: {rt.format_bytes(plan.download_bytes)}.")
    return lines


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".")


def repair(components: Iterable[str], *, plan: Optional[RepairPlan] = None, progress: ProgressCallback = _noop_progress,
           cancel_check: Optional[CancelCheck] = None, opener: Optional[Opener] = None,
           runner: Optional[CommandRunner] = None, seed_dirs: Iterable[Path] = (),
           disk_free: Callable[[Path], int] = free_bytes, sleep: Callable[[float], None] = time.sleep,
           load_check: bool = True) -> SetupResult:
    """Repair what a full check found wrong: rebuild a broken engine, re-fetch only the files that fail.

    Pass the ``plan`` the user has already seen and confirmed (:func:`analyze_repair`); without one a plan is made first,
    so a repair never acts on less than a full check. A healthy installation is left exactly as it is.
    """
    runner = runner or run_command
    try:
        refuse_if_unsupported()
        plan = plan or analyze_repair(components, progress=progress, cancel_check=cancel_check, runner=runner)
        if plan.nothing_to_do:
            return SetupResult(True, "Everything checks out. Nothing needed repair.")
        needed = (rt.environment_installed_bytes() if plan.rebuild_environment else 0) + plan.model_download_bytes \
            + DISK_MARGIN_BYTES
        available = disk_free(rt.repo_root())
        if available < needed:
            return SetupResult(False, f"Not enough free disk space to repair: about {rt.format_bytes(needed)} is needed "
                                      f"and {rt.format_bytes(available)} is free. Nothing was changed.")
        steps: list[str] = []
        with InstallLock():
            if plan.rebuild_environment:
                install_environment(progress=progress, cancel_check=cancel_check, runner=runner,
                                    rebuild=os.path.lexists(rt.nested_venv_dir()))
                steps.append("environment")
            for key, bad in plan.bad_files.items():
                if not bad and key not in plan.unmarked:
                    continue
                install_model(key, progress=progress, cancel_check=cancel_check, opener=opener, seed_dirs=seed_dirs,
                              sleep=sleep, trusted=plan.verified.get(key))
                steps.append(f"model:{key}")
                if load_check:
                    probe_environment(model_dir=rt.model_spec(key).directory, runner=runner, progress=progress,
                                      cancel_check=cancel_check)
                    steps.append(f"verified:{key}")
        return SetupResult(True, "The Qwen3 voices are repaired.", steps=steps)
    except SetupCancelled:
        return SetupResult(False, "Cancelled. What was completed is kept.", cancelled=True)
    except (SetupError, Qwen3Unavailable) as exc:
        return SetupResult(False, str(exc))
    except OSError as exc:
        return SetupResult(False, f"The repair stopped because of a file or disk problem: {exc}")
