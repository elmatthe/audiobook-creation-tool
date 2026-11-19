"""Subprocess wrappers that suppress console windows on Windows.

Every external-binary call in the application (ffmpeg, ffprobe, etc.) must go
through :func:`run` or :func:`popen` so that no console window flashes when the
app is launched from the GUI (under ``pythonw.exe``). :func:`run_supervised`
starts its child through :func:`popen` too, and lets Cancel stop it (v0.7.2).

On non-Windows platforms these are thin pass-throughs to ``subprocess``, with one addition (v0.8.x P1B, plan section
11.2.2): once a process has made itself the *owner* of its media children (:func:`enable_containment`; the app window does
so at start), every FFmpeg and ffprobe started through this module joins that owner's guardian group (class B of
:mod:`shared.child_ownership`), so it ends with the app however the app ends -- SIGKILL, a crash, Force Quit -- and
:func:`stop_media_children` ends it by identity on an orderly close. Windows is unchanged: Job Objects and the Toolhelp
``stop_media_children``.
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


def _hidden_kwargs() -> dict[str, Any]:
    """Return kwargs that hide the console window on Windows; empty elsewhere."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


# --------------------------------------------------------------------------- #
# POSIX containment of the media children (v0.8.x P1B, plan section 11.2.2)
# --------------------------------------------------------------------------- #

#: The programs this module starts as class B once an owner exists. This only decides how a child is *started*; nothing
#: is ever found or ended by its name (ending reads the owner's registry, pid and start time).
MEDIA_PROGRAMS = frozenset({"ffmpeg", "ffprobe"})

_owner = None


def enable_containment(log: Optional[Callable[[str], None]] = None):
    """Make this process the owner of the FFmpeg and ffprobe it starts through this module, and return the owner.

    POSIX only (``None`` on Windows, which keeps its Job Objects and Toolhelp path unchanged). Called by the app window
    at start; a process that never calls it -- setup, the optional-setup workers, every test that does not ask --
    spawns exactly as before. Imported here, never at the top: this module must import alone (ffmpeg_health imports it
    bare before the venv exists, and the planning worker's reviewed source closure carries it without
    ``child_ownership.py``), and only an owner ever needs it.
    """
    global _owner
    if sys.platform == "win32":
        return None
    try:
        from . import child_ownership
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        try:
            import child_ownership  # type: ignore[no-redef]
        except ImportError:  # a reviewed source closure without it: nothing here can own a child
            return None
    if not child_ownership.supported():
        return None
    _owner = child_ownership.owner(log)
    return _owner


def containment_owner():
    """The owner :func:`enable_containment` made, or ``None`` (always ``None`` on Windows)."""
    return _owner


#: v0.8.x P5-I-R3: the whole orderly end -- from the close request to the guardian reaped -- on POSIX with an owner.
ORDERLY_END_S = 5.0
#: ... of which the containment's own end (every child retired, the lifeline closed, the guardian reaped) keeps this
#: much for itself: the panels' worker joins and the window's teardown get only what is left before it.
CONTAINMENT_RESERVE_S = 2.5
_closing_deadline: Optional[tuple] = None  # (the owner that began closing, its deadline)


def _closing_by() -> Optional[float]:
    """The orderly end's deadline, while the owner that started it is still this process's owner."""
    closing = _closing_deadline
    if closing is None or _owner is None or closing[0] is not _owner:
        return None
    return closing[1]


def begin_closing() -> None:
    """The app is closing: from now on no FFmpeg, ffprobe or setup worker starts (a request raises, nothing runs).
    POSIX with an owner only; nothing on Windows. Never raises.

    v0.8.x P5-I-R3: it also starts the orderly end's one deadline (:data:`ORDERLY_END_S` from the first call): the
    panels' bounded joins (:func:`close_budget`) and :func:`shutdown_containment` all wait against it, so the end as a
    whole never takes longer, however many panels are open."""
    global _closing_deadline
    owner = _owner
    if owner is not None:
        if _closing_by() is None:
            _closing_deadline = (owner, time.monotonic() + ORDERLY_END_S)
        with contextlib.suppress(Exception):
            owner.begin_closing()


def close_budget(timeout: float) -> float:
    """How long a panel closing now may wait for its worker: *timeout*, except while the app is closing (POSIX with an
    owner, :func:`begin_closing`), when it is never past the orderly end's deadline less what the containment keeps for
    itself (:data:`CONTAINMENT_RESERVE_S`). Unchanged on Windows and whenever the app is not closing."""
    deadline = _closing_by()
    if deadline is None:
        return timeout
    return max(0.0, min(timeout, deadline - CONTAINMENT_RESERVE_S - time.monotonic()))


def shutdown_containment() -> None:
    """The rest of the orderly end (plan section 11.2.2): every child still owned, then the lifeline -- which retires
    the guardian -- then the guardian is reaped; bounded, and never past the deadline :func:`begin_closing` started
    (v0.8.x P5-I-R3). POSIX with an owner only; never raises. The containment after SIGKILL or a crash never depends
    on this."""
    owner = _owner
    if owner is not None:
        with contextlib.suppress(Exception):
            owner.shutdown(deadline=_closing_by())


def _media_owner(cmd, kwargs: dict):
    """The owner to start ``cmd`` under as class B, or ``None`` to start it exactly as before."""
    owner = _owner
    if owner is None or sys.platform == "win32" or isinstance(cmd, (str, bytes, os.PathLike)):
        return None
    if "start_new_session" in kwargs or "process_group" in kwargs or kwargs.get("shell"):
        return None
    try:
        program = os.path.basename(os.fsdecode(list(cmd)[0]))
    except (IndexError, TypeError, ValueError):
        return None
    return owner if program in MEDIA_PROGRAMS else None


def _contained_popen(owner, cmd, **kwargs) -> subprocess.Popen:
    argv = [os.fspath(part) for part in cmd]
    return owner.popen_external(argv, label=os.path.basename(argv[0]), **kwargs)


#: v0.8.x P5-I-R3: after a contained child of :func:`run`/:func:`check_output` has been told to stop, how long its
#: remaining output is collected before the pipes are given up (the owner keeps the child until its end is confirmed).
_DRAIN_AFTER_STOP_S = 1.0
_LOST_NOTE = "[lost containment: its guardian ended, so it was stopped]"


def _close_streams(process: subprocess.Popen) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with contextlib.suppress(OSError, ValueError):
                stream.close()


def _contained_run(owner, cmd, *, input=None, capture_output: bool = False, timeout=None, check: bool = False,
                   **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run`` with the child started as class B: the same arguments and the same results (a timeout
    kills the child -- by identity -- and raises ``TimeoutExpired``; ``check`` raises ``CalledProcessError``).

    v0.8.x P5-I-R3: every wait is bounded once the child has been told to stop (never ``Popen.__exit__``'s or a bare
    ``communicate``'s unbounded wait); inside a :func:`cancellable` block the start is ordered against the run's Cancel and
    a Cancel stops the child (identity-checked) and raises; a child whose guardian was lost, or whose end could not be
    confirmed, is never a success (a non-zero status with a note, ``CalledProcessError`` under ``check``)."""
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    supervision = _supervision.get()
    if _asked_to_cancel(supervision):
        _cancelled(supervision, None, True, 0.0)
    process = _start_acknowledged(supervision, lambda: _contained_popen(owner, cmd, **_context_launch(), **kwargs))
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    stdout = stderr = None
    try:
        while True:
            step = SUPERVISED_POLL_SECONDS if deadline is None else max(0.0, min(SUPERVISED_POLL_SECONDS,
                                                                                 deadline - time.monotonic()))
            try:
                stdout, stderr = owner.communicate(process, input, step)
                break
            except subprocess.TimeoutExpired:
                input = None  # sent once
            if _asked_to_cancel(supervision):
                stopped = _stop_contained(owner, process, 0.0)
                _close_streams(process)
                if not stopped:
                    raise ChildNotStopped(f"{os.path.basename(str(process.args[0]))} (pid {process.pid}) was told to "
                                          "stop and could not be confirmed ended; it is still owned")
                _cancelled(supervision, process, stopped, 0.0)
            if deadline is not None and time.monotonic() >= deadline:
                stopped = _stop_contained(owner, process, 0.0)
                out = err = None
                with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
                    out, err = owner.communicate(process, None, _DRAIN_AFTER_STOP_S)
                _close_streams(process)
                expired = subprocess.TimeoutExpired(process.args, timeout, output=out, stderr=err)
                if not stopped:
                    expired.add_note(f"process {process.pid} was told to stop and is not confirmed ended")
                raise expired
    except BaseException:
        if process.returncode is None:
            _stop_contained(owner, process, 0.0)
        _close_streams(process)
        raise
    finally:
        owner.forget(process)
    retcode = process.returncode
    if not owner.containment_held(process):
        stderr = _with_note(stderr, _LOST_NOTE)
        retcode = retcode if retcode else -15
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(process.args, retcode, stdout, stderr)


def _with_note(stream, note: str):
    if isinstance(stream, bytes):
        return stream + b"\n" + note.encode("utf-8", "replace") if stream else note.encode("utf-8", "replace")
    if isinstance(stream, str):
        return f"{stream}\n{note}" if stream else note
    return stream


def _stop_contained(owner, process: subprocess.Popen, grace_seconds: float) -> bool:
    """End a contained child through its owner (identity-checked SIGTERM, *grace_seconds*, SIGKILL, confirmed reaped by
    the owner's shared deadline). True once it was reaped; False when its end is not confirmed (it stays owned)."""
    if process.returncode is not None:
        return True
    with contextlib.suppress(Exception):  # noqa: BLE001 - a stop that fails proves nothing; the answer below is read
        owner.end(process, grace=grace_seconds)
    return process.returncode is not None


def _launch_kwargs(cancel_check) -> dict:
    """v0.8.x P5-I-R3: what orders a contained start against the run of *cancel_check*: its counted start
    (``JobController.starting``) when the check is a controller's, the Cancel that may be pending while it waits, the
    error a revoked start raises, the run it belongs to, and a checkpoint that lets the caller leave on a latched Cancel."""
    if cancel_check is None:
        return {}
    controller = getattr(cancel_check, "__self__", None)
    out = {"owner_run": cancel_check}

    def checkpoint() -> None:
        if cancel_check():
            raise _cancellation_error()

    out["checkpoint"] = checkpoint
    out["cancel_error"] = _cancellation_error
    if hasattr(controller, "starting") and hasattr(controller, "cancel_pending"):
        out["ordering"] = lambda: controller.starting("Cancelled.")
        out["pending"] = lambda: controller.cancel_pending
    else:
        out["pending"] = cancel_check
    return out


def _cancellation_error() -> BaseException:
    try:
        from .cancellation import ConversionCancelled
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        from cancellation import ConversionCancelled  # type: ignore[no-redef]
    return ConversionCancelled("Cancelled.")


def contained(cmd, **kwargs) -> bool:
    """v0.8.x P5-I-R3: True when :func:`popen` of these arguments starts a contained class-B child (macOS, with an
    owner): its start is then ordered by :func:`popen` itself. False on Windows and wherever it starts as released."""
    return _media_owner(cmd, kwargs) is not None


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    """Drop-in replacement for ``subprocess.run`` with hidden console on Windows.

    Caller-supplied kwargs win over the hidden-window defaults so that explicit
    ``startupinfo``/``creationflags`` are still honoured if ever needed.
    """
    owner = _media_owner(cmd, kwargs)
    if owner is not None:
        return _contained_run(owner, cmd, **kwargs)
    return subprocess.run(cmd, **{**_hidden_kwargs(), **kwargs})


class ChildNotStopped(RuntimeError):
    """v0.8.x P5-I-R3: a contained child was told to stop (a Cancel, a deadline) and its end could not be confirmed
    within its bound. A failure, never a clean Cancel: the run must not be reported CANCELLED or finished, and the owner
    keeps the child (and keeps ending it) until its end is confirmed."""


_LAUNCH_KEYS = ("owner_run", "ordering", "checkpoint", "pending", "cancel_error")


_run_context: contextvars.ContextVar = contextvars.ContextVar("subprocess_run_context", default=None)


@contextlib.contextmanager
def run_context(cancel_check):
    """v0.8.x P5-I-R3: every contained start this thread makes inside the block belongs to the run of *cancel_check*
    (a ``JobController.cancel_check``): ordered against its Cancel, accounted for by its settlement
    (:func:`containment_problem`). A start a Cancel revoked raises ``ConversionCancelled``. Nothing changes on Windows
    or where nothing is contained."""
    token = _run_context.set(cancel_check)
    try:
        yield
    finally:
        _run_context.reset(token)


def _context_launch() -> dict:
    """The launch arguments of the innermost :func:`cancellable` or :func:`run_context` of this thread, if any."""
    supervision = _supervision.get()
    if supervision is not None:
        return _launch_kwargs(supervision.cancel_check)
    run = _run_context.get()
    return _launch_kwargs(run) if run is not None else {}


def stop_child(process, grace_seconds: float) -> bool:
    """v0.8.x P5-I-R3: stop *process* -- through the owner when it is a contained child (identity-checked SIGTERM,
    *grace_seconds*, SIGKILL, confirmed by the owner's shared deadline; the owner keeps ending it if not), else through
    its own handle as released (terminate, kill). True once it was reaped (or had already exited)."""
    owner = _owner
    if owner is not None and owner.child(process) is not None:
        return _stop_contained(owner, process, grace_seconds)
    if process.poll() is not None:
        return True
    return _stop(process, grace_seconds)


def kill_child(process) -> None:
    """v0.8.x P5-I-R3: SIGKILL *process* -- through the owner (proved identity) when contained, else its own handle."""
    owner = _owner
    if owner is not None and owner.child(process) is not None:
        with contextlib.suppress(Exception):
            owner.kill_now(process)
        return
    with contextlib.suppress(OSError):
        process.kill()


def popen(cmd, **kwargs) -> subprocess.Popen:
    """Drop-in replacement for ``subprocess.Popen`` with hidden console on Windows.

    v0.8.x P5-I-R3 (macOS, contained children only; ignored -- the start made as released -- on Windows and wherever
    nothing is contained): ``owner_run`` (the run the child belongs to, accounted for by :func:`settle_owned`),
    ``ordering`` (a zero-argument callable giving the run's Cancel ordering, e.g. ``controller.starting``), ``checkpoint``
    (raises to make the caller leave a start in progress), ``pending`` (a Cancel is waiting to latch) and
    ``cancel_error`` (what a start revoked by it raises): see ``child_ownership.Owner.popen_external``. The program begins
    executing only inside ``ordering``, through a one-time permit revoked before that ordering ends."""
    launch = {key: kwargs.pop(key) for key in _LAUNCH_KEYS if key in kwargs}
    owner = _media_owner(cmd, kwargs)
    if owner is not None:
        if not launch:
            launch = _context_launch()
        return _contained_popen(owner, cmd, **{k: v for k, v in launch.items() if v is not None}, **kwargs)
    return subprocess.Popen(cmd, **{**_hidden_kwargs(), **kwargs})


def settle_owned(run, bound_s: Optional[float] = None) -> list[int]:
    """v0.8.x P5-I: the process ids of *run*'s contained children (macOS) whose end is not confirmed once the owner has
    retired what the run left (bounded; see ``child_ownership.Owner.settle_run``). A run with any must not be reported as
    finished or cleanly cancelled (``-1`` stands for a start still in progress, or an answer that could not be had). ``[]``
    on Windows, without an owner, or for no run."""
    owner = _owner
    if owner is None or run is None:
        return []
    try:
        return owner.settle_run(run) if bound_s is None else owner.settle_run(run, bound_s)
    except Exception:  # noqa: BLE001 - settlement must not raise; an answer that could not be had is no clean end
        return [-1]


#: v0.8.x P5-I-R3: the stopping bound of a cancelled run's contained FFmpeg steps, measured from the Cancel click
#: (plan section 11.2.1, C2: one FFmpeg step, terminate -> 2 s -> kill -> 2 s).
FFMPEG_STOP_S = 4.0
#: What a run whose contained programs could not all be confirmed ended says instead of finished or cancelled.
CONTAINMENT_FAILED_MESSAGE = ("A program this run started could not be confirmed stopped, so the run did not finish "
                              "cleanly. Nothing unfinished was saved. Close and reopen the app before trying again.")


_unresolved: dict = {}  # pid -> (kernel start time, what) (v0.8.x P5-I-R3)
_unresolved_lock = threading.Lock()


def note_unresolved(pid: int, start_time, what: str) -> None:
    """v0.8.x P5-I-R3: a process this app owns (a voice-engine worker, say) was told to stop and could not be confirmed
    ended. Until it is seen gone, no run is reported finished or cleanly cancelled (:func:`containment_problem`,
    ``ffmpeg_watch.settle_children``). POSIX only; never raises."""
    if not pid or pid <= 0:
        return
    with _unresolved_lock:
        _unresolved[int(pid)] = (start_time, what)


def unresolved_children() -> list[int]:
    """The pids recorded by :func:`note_unresolved` that may still be running (the recorded process is still there,
    with its recorded kernel start time; a process whose identity cannot be read is kept). Those seen gone are dropped."""
    with _unresolved_lock:
        items = list(_unresolved.items())
    if not items:
        return []
    try:
        from . import child_ownership
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        import child_ownership  # type: ignore[no-redef]
    left = []
    for pid, (start, _what) in items:
        now = child_ownership.process_start_time(pid)
        # P5-I-R3 remediation 5: gone only once reaped (or another process holds the id); a zombie still needs reaping
        # -- its id and, for a group leader, its group are still reserved.
        gone = now is None or (start is not None and now != start)
        if gone:
            with _unresolved_lock:
                if _unresolved.get(pid, (None,))[0] == start:
                    _unresolved.pop(pid, None)
        else:
            left.append(pid)
    return left


def settle_bound(cancel_check, stop_s: float = FFMPEG_STOP_S) -> float:
    """v0.8.x P5-I-R3: how long a run's settlement may still wait: what is left of *stop_s* after the Cancel click --
    nothing once it has passed (the settlement then takes one look: a process still running is not confirmed ended
    inside the bound) --, all of *stop_s* for a cancelled run whose click instant is unknown (no clock injected), or
    one second for a run that was not cancelled."""
    controller = getattr(cancel_check, "__self__", None) or getattr(cancel_check, "controller", None)
    clicked = getattr(controller, "cancel_clicked_at", None)
    if clicked is not None:
        return max(0.0, clicked + stop_s - time.monotonic())
    try:
        cancelled = bool(cancel_check())
    except Exception:  # noqa: BLE001 - a question that cannot be answered: the longer, cancelled bound
        cancelled = True
    return stop_s if cancelled else 1.0


def run_faults(cancel_check) -> list:
    """v0.8.x P5-I-R3: what the containment owner recorded as not kept contained for the run of *cancel_check* (a start
    that could not be withdrawn); kept after the processes are gone. A run with any is FAILED, never CANCELLED or a
    success. ``[]`` on Windows and without an owner. Never raises."""
    owner = _owner
    if owner is None or cancel_check is None:
        return []
    try:
        return list(owner.faults(cancel_check))
    except Exception:  # noqa: BLE001 - an answer that could not be had is no clean end
        return ["the containment owner could not say whether every start of this run was kept contained"]


def containment_problem(cancel_check, *, stop_s: float = FFMPEG_STOP_S) -> Optional[str]:
    """v0.8.x P5-I-R3: why the run of *cancel_check* may NOT be reported finished or cleanly cancelled, or ``None``.

    Asked by every tool's terminal path before it chooses its terminal event (and before it removes staging for a
    retry). macOS with an owner: the owner retires whatever contained process the run still owes and waits for each end
    to be confirmed -- never past *stop_s* after the Cancel click (``JobController.cancel_clicked_at``), or one second
    when the run was not cancelled. A process not confirmed ended stays owned and keeps being ended; the run must then
    end FAILED with this text as its detail (never CANCELLED, never a success). ``None`` on Windows, without an owner,
    and for a run that left nothing."""
    owner = _owner
    if cancel_check is None:
        return None
    pids = settle_owned(cancel_check, settle_bound(cancel_check, stop_s)) if owner is not None else []
    pids = sorted(set(pids) | set(unresolved_children()))
    faults = run_faults(cancel_check)  # P5-I-R3 remediation 1: uncontained starts stay reported
    if not pids and not faults:
        return None
    parts = []
    if pids:
        named = ", ".join("a start still in progress" if pid == -1 else f"pid {pid}" for pid in pids)
        parts.append(f"contained process(es) of this run not confirmed ended ({named}); still owned and still being "
                     "ended")
    parts.extend(faults)
    return "; ".join(parts)


def containment_lost(process) -> bool:
    """v0.8.x P5-I: True when *process* is a contained child (macOS) whose guardian was lost while it ran, or is found
    gone now (the loss is then recorded). Its work is never reported as a success. False on Windows or without an
    owner."""
    owner = _owner
    if owner is None:
        return False
    try:
        return not owner.containment_held(process)
    except Exception:  # noqa: BLE001 - a check that cannot be made is no proof of containment
        return True


def check_output(cmd, **kwargs) -> bytes | str:
    """Drop-in replacement for ``subprocess.check_output`` with hidden console."""
    owner = _media_owner(cmd, kwargs)
    if owner is not None:
        if "stdout" in kwargs:
            raise ValueError("stdout argument not allowed, it will be overridden.")
        return _contained_run(owner, cmd, stdout=subprocess.PIPE, check=True, **kwargs).stdout
    return subprocess.check_output(cmd, **{**_hidden_kwargs(), **kwargs})


# --------------------------------------------------------------------------- #
# Supervised FFmpeg steps that Cancel can stop (v0.7.2 Phase 6C, ACT72-023)
# --------------------------------------------------------------------------- #

#: How often a supervised child and its Cancel are looked at. Short enough that Cancel feels immediate.
SUPERVISED_POLL_SECONDS = 0.05
#: How long a stopped child is given to exit after ``terminate`` and again after ``kill``, so stopping is bounded.
SUPERVISED_GRACE_SECONDS = 2.0
#: The most of each stream kept. A duration probe prints a few kilobytes; a failure's reason is at the end of stderr.
SUPERVISED_TAIL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _Supervision:
    cancel_check: Callable[[], bool]
    acknowledge: Optional[Callable[[], None]]


_supervision: contextvars.ContextVar[Optional[_Supervision]] = contextvars.ContextVar(
    "subprocess_supervision", default=None)


@contextlib.contextmanager
def cancellable(cancel_check: Callable[[], bool], acknowledge: Optional[Callable[[], None]] = None):
    """Every :func:`run_supervised` this thread makes inside the block answers to ``cancel_check``.

    ``cancel_check`` must not block: it is asked while FFmpeg runs, so it is the controller's ``cancel_check``, never its
    ``checkpoint`` (which waits while paused). Pause therefore never touches a running step; it is honoured at the
    caller's next checkpoint. ``acknowledge`` is called once a Cancel has stopped or prevented a child, before
    :class:`ConversionCancelled` is raised: the controller's ``checkpoint``, which records that the worker observed the
    Cancel (and raises it), so the run can be settled as cancelled.
    """
    token = _supervision.set(_Supervision(cancel_check, acknowledge))
    try:
        yield
    finally:
        _supervision.reset(token)


def _asked_to_cancel(supervision: Optional[_Supervision]) -> bool:
    return supervision is not None and bool(supervision.cancel_check())


def _stop(child: subprocess.Popen, grace_seconds: float) -> bool:
    """Terminate, then kill if it will not go, through this ``Popen``'s own handle and nothing else; wait after each
    step, never for ever. True when the child was reaped. (On Windows both steps are ``TerminateProcess``.)"""
    for step in (child.terminate, child.kill):
        with contextlib.suppress(OSError):
            step()
        try:
            child.wait(timeout=grace_seconds)
            return True
        except subprocess.TimeoutExpired:
            continue
    return False


def _forget(child: subprocess.Popen) -> None:
    """Drop a reaped child from the owner's registry (POSIX containment); nothing to do anywhere else."""
    owner = _owner
    if owner is not None and child.returncode is not None:
        owner.forget(child)


def _tail(stream, limit: int) -> bytes:
    """At most the last ``limit`` bytes of what the child wrote: one seek and one read, whatever it wrote."""
    stream.flush()
    size = stream.seek(0, os.SEEK_END)
    stream.seek(max(0, size - limit))
    return stream.read()


def _start_acknowledged(supervision: Optional["_Supervision"], start: Callable[[], subprocess.Popen]) -> subprocess.Popen:
    """Run *start*; a start the run's Cancel refused (its counted start latched first: ``ConversionCancelled`` from the
    ordering, P5-I-R3) is acknowledged through the block like every other Cancel before it is raised (remediation 2,
    finding 6: the tools' Cancel handlers rely on that acknowledgement)."""
    try:
        return start()
    except Exception as exc:  # noqa: BLE001 - only a cancellation is handled; anything else is re-raised as it is
        if supervision is None or type(exc).__name__ != "ConversionCancelled":
            raise
        _cancelled(supervision, None, True, 0.0)
        raise  # pragma: no cover - _cancelled always raises


def _cancelled(supervision: _Supervision, child: Optional[subprocess.Popen], reaped: bool,
               grace_seconds: float) -> None:
    """Acknowledge a Cancel that stopped (or prevented) a child and raise it. Never a failure code."""
    # Imported here, never at the top: this module must import alone. ffmpeg_health imports it bare off scripts/shared
    # before the venv exists, and the optional-setup planning worker's reviewed source closure
    # (optional_setup_planning_bridge_v3.SOURCES) carries it without shared/cancellation.py. Neither ever cancels.
    try:
        from .cancellation import ConversionCancelled
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        from cancellation import ConversionCancelled  # type: ignore[no-redef]
    try:
        if supervision.acknowledge is not None:
            supervision.acknowledge()
        raise ConversionCancelled("Cancelled.")
    except ConversionCancelled as exc:
        if child is not None and not reaped:
            exc.add_note(f"process {child.pid} did not exit within {2 * grace_seconds:g} s of being stopped")
        raise


def run_supervised(args, *, poll_seconds: float = SUPERVISED_POLL_SECONDS,
                   grace_seconds: float = SUPERVISED_GRACE_SECONDS,
                   tail_bytes: int = SUPERVISED_TAIL_BYTES,
                   deadline_seconds: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run one FFmpeg or ffprobe to its end, or stop it on Cancel or at its deadline, and always reap it.

    Returns ``CompletedProcess(args, returncode, stdout, stderr)`` with bytes, each at most its last ``tail_bytes``; a
    non-zero exit is the caller's to judge, exactly as with ``run``. Inside a :func:`cancellable` block:

    * Cancel already requested: nothing is started.
    * Cancel requested while it runs: seen within ``poll_seconds``; this very child is terminated, then killed, through
      its own handle (never by a name or a bare process id, so nothing else is touched), and waited on for at most
      ``grace_seconds`` after each step.

    Either way :class:`ConversionCancelled` is raised after the block's ``acknowledge``, never a return code, so no
    caller can mistake a Cancel for a failed or retryable step. Outside a block it simply runs to the end.

    ``deadline_seconds`` (v0.7.2 Phase 6E, ACT72-010; ``None``, the default, is no deadline, as for every caller before):
    a child still running that long after it started is stopped and reaped the same way, and
    :class:`subprocess.TimeoutExpired` is raised (``timeout`` the deadline, ``output``/``stderr`` the tails), as
    ``subprocess.run(timeout=...)`` does: never a return code, and never a Cancel. A Cancel seen at the same look wins.

    The child's output goes to two temporary files rather than pipes, so it can never block on a full pipe and there is no
    reader thread to wait on (v0.7.1's ``tts.ffmpeg_watch`` lesson); they are deleted when closed, which on Windows
    also happens if this program is killed. Its stdin is the null device and it gets no console window.
    """
    argv = list(args)
    supervision = _supervision.get()
    if _asked_to_cancel(supervision):
        _cancelled(supervision, None, True, grace_seconds)
    owner = _media_owner(argv, {})
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        launch = _launch_kwargs(supervision.cancel_check) if owner is not None and supervision is not None else {}
        child = _start_acknowledged(supervision, lambda: popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                                               **launch))
        started = time.monotonic()
        stopped = timed_out = False
        reaped = True
        try:
            while True:
                try:
                    child.wait(timeout=poll_seconds)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if _asked_to_cancel(supervision):
                    stopped = True
                    break
                if deadline_seconds is not None and time.monotonic() - started >= deadline_seconds:
                    timed_out = True
                    break
        finally:
            # Every route out, an exception in the loop included: a child started here is stopped and collected here.
            if child.returncode is None:
                reaped = (_stop_contained(owner, child, grace_seconds) if owner is not None
                          else _stop(child, grace_seconds))
        _forget(child)
        if owner is not None and not reaped:
            # v0.8.x P5-I-R3: never a clean Cancel (or a deadline) with the child not confirmed ended: a failure.
            raise ChildNotStopped(f"{os.path.basename(argv[0])} (pid {child.pid}) was told to stop and could not be "
                                  "confirmed ended; it is still owned and still being ended")
        if stopped:
            _cancelled(supervision, child, reaped, grace_seconds)
        if timed_out:
            expired = subprocess.TimeoutExpired(argv, deadline_seconds, _tail(out, tail_bytes), _tail(err, tail_bytes))
            if not reaped:
                expired.add_note(f"process {child.pid} did not exit within {2 * grace_seconds:g} s of being stopped")
            raise expired
        code, stderr_tail = child.returncode, _tail(err, tail_bytes)
        if owner is not None and not owner.containment_held(child):
            code, stderr_tail = (code if code else -15), _with_note(stderr_tail, _LOST_NOTE)
        return subprocess.CompletedProcess(argv, code, _tail(out, tail_bytes), stderr_tail)


#: What :func:`stop_media_children` may end. Never a detached helper: repair and cleanup deliberately outlive the window that started them.
_MEDIA_CHILDREN = frozenset({"ffmpeg.exe", "ffprobe.exe"})


def stop_media_children() -> list[int]:
    """End FFmpeg and ffprobe processes this process itself started, and return their pids. Never raises.

    POSIX (v0.8.x P1B): the owner's own registry of the class-B children it started (pid and kernel start time), ended
    together -- SIGTERM, at most a second, SIGKILL, reaped -- and nothing else: never a process listing, never a name on
    the system. Without an owner (:func:`enable_containment` was never called) there is nothing to end.

    Windows (unchanged):

    A tool's worker blocks in :func:`run` while FFmpeg works. It is a daemon thread, so it dies with the interpreter, and FFmpeg does not
    notice: closing the window during an M4B Maker build left FFmpeg encoding with nobody to publish the result (measured, v0.7.2 Phase 3).
    A process is ended only if its parent is this very process and its image is one of the media tools, so a sentinel FFmpeg started by
    anyone else is untouched and a name alone is never enough.
    """
    if sys.platform != "win32":
        owner = _owner
        if owner is None:
            return []
        if _closing_by() is not None:
            # v0.8.x P5-I-R3: the app is closing. :func:`shutdown_containment`, next, retires them with every other
            # child in one batch inside the orderly end's one deadline; a separate wait here would come on top of it.
            return []
        try:
            return owner.stop_external(MEDIA_PROGRAMS)
        except Exception:  # noqa: BLE001 - closing the application is never the moment to raise
            return []
    stopped: list[int] = []
    try:
        import ctypes
        import ctypes.wintypes as w

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG),
                        ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel32.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.OpenProcess.restype = w.HANDLE
        kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        kernel32.CloseHandle.argtypes = [w.HANDLE]
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot == w.HANDLE(-1).value:
            return stopped
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            mine = os.getpid()
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32ParentProcessID == mine and entry.szExeFile.lower() in _MEDIA_CHILDREN:
                    handle = kernel32.OpenProcess(0x0001, False, entry.th32ProcessID)  # PROCESS_TERMINATE
                    if handle:
                        if kernel32.TerminateProcess(handle, 1):
                            stopped.append(int(entry.th32ProcessID))
                        kernel32.CloseHandle(handle)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:  # noqa: BLE001 - closing the application is never the moment to raise
        return stopped
    return stopped


_POPEN_PATCHED = False


def install_no_window_guard() -> None:
    """Force *every* child process on Windows to spawn without a console window.

    The app's own ffmpeg/ffprobe calls already go through :func:`run` /
    :func:`popen`, but pydub and edge-tts spawn ffmpeg through their *own*
    internal ``subprocess.Popen`` calls, which bypass those wrappers. During the
    TTS combine stage pydub exports/concatenates dozens of segments, flashing a
    console window for each one. This wraps ``subprocess.Popen`` itself so those
    internal spawns also inherit the hidden-window flags from
    :func:`_hidden_kwargs` — the one chokepoint every child process passes
    through, regardless of who calls it.

    No-op on non-Windows. Idempotent. Must be called once at startup, *before*
    pydub/edge-tts are imported, so a ``from subprocess import Popen`` inside
    those libraries binds to the wrapped class.
    """
    global _POPEN_PATCHED
    if _POPEN_PATCHED or sys.platform != "win32":
        return

    _original_popen = subprocess.Popen

    class _NoWindowPopen(_original_popen):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            hidden = _hidden_kwargs()
            # OR our hidden-window creationflags into anything the caller passed
            # so an explicit flag is preserved rather than clobbered.
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | hidden["creationflags"]
            )
            # Only inject the hidden STARTUPINFO when the caller supplied none;
            # our own wrappers already pass one.
            if kwargs.get("startupinfo") is None:
                kwargs["startupinfo"] = hidden["startupinfo"]
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen  # type: ignore[misc]
    _POPEN_PATCHED = True


# --------------------------------------------------------------------------- #
# Showing a folder in the file manager without waiting for it (v0.7.2 Phase 8, ACT72-062)
# --------------------------------------------------------------------------- #

#: The most folders that may be waiting for the file manager at once. A person asks for one or two; more than this
#: means the file manager has stopped answering, so a further request is refused at once instead of piling up.
REVEAL_LIMIT = 4
#: How long the macOS or Linux opener is waited for before it is left to finish by itself.
REVEAL_OPENER_SECONDS = 10.0


class RevealRequest:
    """One request to show a folder in the file manager, and how it ended.

    ``reason`` is ``None`` while the request is waiting and after it was handed over; otherwise it says why the file
    manager could not be asked. :meth:`on_failure` is told that reason exactly once, on whichever thread learns it, so
    the callable must be safe on any thread and must hold no Tk object: put a line on a queue, never touch a widget
    (a Tk object released on a thread that is not Tk's own ends the program).
    """

    __slots__ = ("target", "_lock", "_done", "_reason", "_callbacks")

    def __init__(self, target: str) -> None:
        self.target = target
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._reason: Optional[str] = None
        self._callbacks: list[Callable[[str], None]] = []

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def wait(self, timeout: Optional[float] = None) -> bool:
        """True once the request has ended either way. Nothing in the application waits; a test may."""
        return self._done.wait(timeout)

    def on_failure(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if not self._done.is_set():
                self._callbacks.append(callback)
                return
            reason = self._reason
        if reason is not None:
            _tell(callback, reason)

    def _finish(self, reason: Optional[str]) -> None:
        with self._lock:
            self._reason = reason
            self._done.set()
            callbacks, self._callbacks = self._callbacks, []
        if reason is not None:
            for callback in callbacks:
                _tell(callback, reason)


def _tell(callback: Callable[[str], None], reason: str) -> None:
    """A listener that raises must not stop the requests waiting behind this one."""
    with contextlib.suppress(Exception):
        callback(reason)


_reveal_lock = threading.Lock()
#: Requests not yet ended, oldest first; the first is the one the file manager is being asked for now.
_reveal_queue: collections.deque = collections.deque()
_reveal_thread: Optional[threading.Thread] = None
#: The thread class as it was when this module loaded, so replacing ``threading.Thread`` elsewhere changes nothing here.
_Thread = threading.Thread


def reveal_in_file_manager(path) -> RevealRequest:
    """Ask the OS file manager to show ``path``, and return at once. Never raises.

    The operating system's own call can take many seconds while Explorer is busy or restarting (36.9 s measured in
    v0.7.2 Phase 7B), and it used to be made by the caller: a window's own thread, which froze for that long when the
    M4B Converter showed its output folder at the end of a run (ACT72-062). It is now made on one background thread,
    one request at a time, so no window waits for it. That thread is a daemon and nothing joins it, so closing the
    application never waits for the file manager either; it starts no process of its own on Windows.

    A folder that is already waiting is not asked for twice (the same request comes back), and at most
    :data:`REVEAL_LIMIT` different folders wait: past that the file manager has stopped answering, and the new request
    ends at once with that reason. Opening a folder stays a convenience, so a failure is never raised; the returned
    :class:`RevealRequest` tells a caller that wants to say so.
    """
    global _reveal_thread
    request = RevealRequest(str(Path(path)))
    with _reveal_lock:
        for waiting in _reveal_queue:
            if waiting.target == request.target:
                return waiting
        if len(_reveal_queue) < REVEAL_LIMIT:
            _reveal_queue.append(request)
            # A thread seen here has not yet decided to end (it decides under this lock), so it will take this request.
            if _reveal_thread is not None and _reveal_thread.is_alive():
                return request
            try:
                _reveal_thread = _Thread(target=_reveal_waiting, name="reveal-in-file-manager", daemon=True)
                _reveal_thread.start()
                return request
            except Exception as exc:  # noqa: BLE001 - no thread to be had; say so instead of asking on the caller's
                _reveal_thread = None
                _reveal_queue.remove(request)
                reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = f"the file manager has not answered {REVEAL_LIMIT} earlier requests yet"
    request._finish(reason)
    return request


def _reveal_waiting() -> None:
    """The background thread: ask for each waiting folder in turn, then end. Holds no lock while the system works."""
    global _reveal_thread
    while True:
        with _reveal_lock:
            if not _reveal_queue:
                _reveal_thread = None
                return
            request = _reveal_queue[0]
        reason = _ask_file_manager(request.target)
        with _reveal_lock:
            _reveal_queue.popleft()
        request._finish(reason)


def _ask_file_manager(target: str, platform: Optional[str] = None) -> Optional[str]:
    """Make the operating system's own call and wait for it: the one place a folder is really opened.

    ``None`` when the request was handed over, otherwise why it could not be. Never raises. ``os.startfile`` on Windows
    (no console window, no process of ours), ``open`` on macOS and ``xdg-open`` on Linux; the two openers are waited for
    briefly so they are reaped, and one still running after :data:`REVEAL_OPENER_SECONDS` is the system's to finish.
    """
    platform = sys.platform if platform is None else platform
    try:
        if platform == "win32":
            with _shell_apartment():
                os.startfile(target)  # type: ignore[attr-defined]
            return None
        opener = "open" if platform == "darwin" else "xdg-open"
        # Class D (deliberately not owned, plan section 11.2.2): the opener hands the folder to Finder and exits.
        child = popen([opener, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL)
        try:
            code = child.wait(timeout=REVEAL_OPENER_SECONDS)
        except subprocess.TimeoutExpired:
            return None
        return None if code == 0 else f"{opener} ended with code {code}"
    except Exception as exc:  # noqa: BLE001 - reported to whoever asked, never raised into a window
        return f"{type(exc).__name__}: {exc}"


@contextlib.contextmanager
def _shell_apartment():
    """Give the calling thread the COM apartment Windows asks of a thread that calls the shell.

    ``os.startfile`` is ``ShellExecute``, whose documentation asks its caller to initialise COM single-threaded with
    OLE1 DDE disabled, because the shell may hand the request to a COM extension. A window's thread usually had that
    already; the background thread above has nothing until this gives it. A failure to initialise is not an error: the
    call is then made exactly as it always was.
    """
    release = None
    try:
        import ctypes

        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        # COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE. S_OK (0) and S_FALSE (1) must both be balanced.
        if ole32.CoInitializeEx(None, 0x2 | 0x4) in (0, 1):
            release = ole32.CoUninitialize
    except Exception:  # noqa: BLE001 - no COM to be had; the shell call still works for a plain folder
        release = None
    try:
        yield
    finally:
        if release is not None:
            with contextlib.suppress(Exception):
                release()
