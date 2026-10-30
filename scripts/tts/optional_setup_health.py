"""optional_setup_health.py — the facts only a probe or a lock can tell, for the optional-setup planner.

v0.7.0 P05B Stage 2 (plan Revision 2 §5.4). Runs in the setup worker, before and after an acquisition:

* **Engine health** of Kokoro and Chatterbox Turbo -- do their *packages* load in the app's environment? Each is the
  launcher's own proof (``shared.bootstrap``: the Kokoro dependency proof, which also builds the English G2P when the
  spaCy model is installed, and the Chatterbox import probe), run in a fresh interpreter with the Hugging Face hub
  offline, so a probe can never download anything. A probe is bounded: it runs as a contained child
  (``qwen3_setup.run_command``: a Job Object, ended with its whole tree on cancel or timeout) and gets a time limit. A
  probe that times out, is cancelled or cannot start proves nothing: that component is ``None`` (unverified) -- never
  healthy, and never "broken" (which would invite a repair). Nothing is recorded: the launcher's proof records are its
  own business, and a plan must not write.
* **Busy** -- held locks, read without creating a lock file: ``setup.lock`` (an install/repair of this copy, or a repair
  of the app's own environment) makes every chosen component busy; ``inference.lock`` / ``engine.lock`` (a Qwen3
  conversion, or a Qwen3 engine still running) make the Qwen3 components busy. A lock whose state cannot be read is
  treated as held.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import optional_setup
from tts import qwen3_runtime as rt

KOKORO_PROBE_TIMEOUT_S = 300.0  # bootstrap.KOKORO_PROOF_TIMEOUT_S: a first torch import in a cold venv is slow
CHATTERBOX_PROBE_TIMEOUT_S = 180.0  # bootstrap.chatterbox_is_healthy's bound
OUTPUT_TAIL = 40

Runner = Callable[..., int]
CancelCheck = Callable[[], bool]

_QWEN = (proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE)


def _default_runner(cmd, **kwargs) -> int:
    from tts import qwen3_setup

    return qwen3_setup.run_command(cmd, **kwargs)  # looked up at call time: the test suite closes this door


# --------------------------------------------------------------------------- #
# Locks, read without being created
# --------------------------------------------------------------------------- #
def lock_held(path: Path) -> Optional[bool]:
    """``True`` when someone holds *path* locked, ``False`` when it is free or absent, ``None`` when it cannot be told.
    An absent lock file is never created (``O_CREAT`` is not used)."""
    if not os.path.lexists(path):
        return False
    if venv_layout.is_link(path):
        return None
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def busy_components(components: Iterable[str]) -> frozenset:
    """The chosen components something else is changing or using right now."""
    chosen = set(components)
    busy: set = set()
    if lock_held(rt.setup_lock_path()) is not False:
        busy |= chosen
    if lock_held(rt.inference_lock_path()) is not False or lock_held(rt.engine_lock_path()) is not False:
        busy |= chosen & set(_QWEN)
    return frozenset(busy)


# --------------------------------------------------------------------------- #
# Bounded, offline engine probes
# --------------------------------------------------------------------------- #
def probe_environment(root: Path) -> dict:
    """The probe's environment: no ambient Python/pip steering, the in-tree Hugging Face cache, the hub offline."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "PIP_")) and k.upper() not in ("VIRTUAL_ENV", "CONDA_PREFIX",
                                                                                  "CONDA_DEFAULT_ENV")}
    hf = Path(root) / "files" / "runtime-data" / "models" / "huggingface"
    env.update({"HF_HOME": str(hf), "HUGGINGFACE_HUB_CACHE": str(hf / "hub"), "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    return env


def run_probe(root: Path, source: str, *, timeout_s: float, cancel_check: CancelCheck,
              runner: Optional[Runner] = None) -> tuple[Optional[int], list[str], str]:
    """``(exit code, last output lines, why there is no code)``. Contained, bounded, cancellable; never raises."""
    from tts import qwen3_setup

    deadline = time.monotonic() + timeout_s
    expired = False

    def stop() -> bool:
        nonlocal expired
        if cancel_check():
            return True
        if time.monotonic() > deadline:
            expired = True
            return True
        return False

    lines: list[str] = []

    def keep(line: str) -> None:
        lines.append(line)
        del lines[:-OUTPUT_TAIL]

    argv = [str(proto.main_console_python(root)), "-E", "-s", "-c", source]
    try:
        code = (runner or _default_runner)(argv, env=probe_environment(root), cwd=Path(root) / "scripts",
                                           on_line=keep, cancel_check=stop)
    except qwen3_setup.SetupCancelled:
        return None, lines, (f"the check did not finish within {int(timeout_s)} s" if expired else "cancelled")
    except Exception as exc:  # noqa: BLE001 - a check that could not run proves nothing either way
        return None, lines, f"the check could not run ({type(exc).__name__}: {exc})"
    return code, lines, ""


#: Windows Smart App Control refuses the FIRST load of each new unsigned native file while it evaluates it, then allows
#: it ("An Application Control policy has blocked this file"; reproduced 2026-10-30 in fresh QA copies: two retries
#: let the Qwen3 engine start, every later start succeeded). A freshly installed engine is therefore proved again, a
#: bounded number of times, while that is the only failure -- Windows decides each time; nothing is bypassed. A
#: refusal that persists is reported as the failure it is.
APPLICATION_CONTROL_MARK = "Application Control policy"
APPLICATION_CONTROL_ATTEMPTS = 8


def retry_application_control(probe: Callable[[], tuple[Optional[bool], str]],
                              cancel_check: CancelCheck) -> tuple[Optional[bool], str]:
    ok, why = probe()
    for _attempt in range(APPLICATION_CONTROL_ATTEMPTS - 1):
        if ok is not False or APPLICATION_CONTROL_MARK not in why or cancel_check():
            break
        ok, why = probe()
    return ok, why


def kokoro_health(root: Path, *, cancel_check: CancelCheck, runner: Optional[Runner] = None,
                  timeout_s: float = KOKORO_PROBE_TIMEOUT_S) -> tuple[Optional[bool], str]:
    """The launcher's Kokoro dependency proof, offline: ``True`` / ``False`` (proved broken) / ``None`` (unproved)."""
    return retry_application_control(
        lambda: _kokoro_health_once(root, cancel_check=cancel_check, runner=runner, timeout_s=timeout_s), cancel_check)


def _kokoro_health_once(root: Path, *, cancel_check: CancelCheck, runner: Optional[Runner],
                        timeout_s: float) -> tuple[Optional[bool], str]:
    from shared import bootstrap

    code, lines, why = run_probe(root, bootstrap._KOKORO_PROOF, timeout_s=timeout_s, cancel_check=cancel_check,
                                 runner=runner)
    if code is None:
        return None, why
    last = lines[-1] if lines else ""
    if code == 0 and last.startswith("OK:"):
        return True, "ok"
    if last.startswith("BROKEN:"):
        return False, last[len("BROKEN:"):]
    return False, f"exit {code}: {last or 'no output'}"  # a native crash is still a failure to start the engine


def chatterbox_health(root: Path, *, cancel_check: CancelCheck, runner: Optional[Runner] = None,
                      timeout_s: float = CHATTERBOX_PROBE_TIMEOUT_S) -> tuple[Optional[bool], str]:
    """The launcher's Chatterbox Turbo import probe (no model, no weights): ``True`` / ``False`` / ``None``."""
    return retry_application_control(
        lambda: _chatterbox_health_once(root, cancel_check=cancel_check, runner=runner, timeout_s=timeout_s),
        cancel_check)


def _chatterbox_health_once(root: Path, *, cancel_check: CancelCheck, runner: Optional[Runner],
                            timeout_s: float) -> tuple[Optional[bool], str]:
    from shared import bootstrap

    code, lines, why = run_probe(root, bootstrap._CHATTERBOX_PROBE, timeout_s=timeout_s, cancel_check=cancel_check,
                                 runner=runner)
    if code is None:
        return None, why
    last = lines[-1] if lines else ""
    if code == 0 and last == "OK":
        return True, "ok"
    return False, last or f"exit {code}"


def local_health(root: Path, components: Iterable[str], *, cancel_check: CancelCheck,
                 runner: Optional[Runner] = None) -> dict[str, Optional[bool]]:
    """Probe each chosen local engine once. Qwen3 health is judged by the planner from the engine's own record."""
    chosen = set(components)
    health: dict[str, Optional[bool]] = {}
    if proto.KOKORO in chosen:
        health[proto.KOKORO] = kokoro_health(root, cancel_check=cancel_check, runner=runner)[0]
    if proto.CHATTERBOX in chosen and not cancel_check():
        health[proto.CHATTERBOX] = chatterbox_health(root, cancel_check=cancel_check, runner=runner)[0]
    return health


def facts(root: Path, components: Iterable[str], *, probe_hardware: bool, cancel_check: CancelCheck,
          runner: Optional[Runner] = None,
          health: Optional[Mapping[str, Optional[bool]]] = None) -> optional_setup.Facts:
    """Everything the planner needs from this computer now: engine health (probed unless given) and busy locks."""
    components = tuple(components)
    if health is None:
        health = local_health(root, components, cancel_check=cancel_check, runner=runner)
    return optional_setup.Facts(health=dict(health), busy=busy_components(components), probe_hardware=probe_hardware)
