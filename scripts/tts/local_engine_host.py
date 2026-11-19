"""local_engine_host.py -- the parent side of the macOS local-engine worker (v0.8.x P2, plan 11.2.1, MAC-043, D17).

**Why it exists.** "Cancel means stop, at once, everywhere" (Decisions, 2026-11-05). A local model call in flight
cannot be stopped from Python: a thread cannot be killed and an asynchronous exception is not delivered inside a native
torch operation. On a Mac CPU one Kokoro chunk of up to 3,000 characters can take tens of seconds, so a Cancel checked
between chunks is not a stop. On macOS the model therefore runs in a separate process, and Cancel ends that process's
whole group at once (SIGKILL) and reaps it; the worker holds nothing worth saving.

**What moves, and what does not.** Only the model load and the per-chunk model call run in the worker
(:mod:`tts.local_engine_worker`). Speech preparation, chunking, the Cancel checks, PCM assembly, the one encode,
publication and every report stay in the parent, in the same functions as before. Each request carries the prepared
text of one chunk, the voice, the settings and (for an engine that uses one) the seed. The PCM comes back through a
run-private file in the parent's own work area, which the parent validates (dtype, sample rate, sample count,
finiteness) and removes.

**Lifecycle.** One worker at a time, started on first use and kept warm across files and runs while the same engine is
used, so Pause leaves it loaded and idle. It ends on Cancel (SIGKILL to its group, reaped, within
:data:`CANCEL_BOUND_S`), on an engine switch (:func:`engine_selected`), and when the app closes (the containment
owner's orderly end, or -- however the app ends -- the lifeline). The next request after any of those starts a new
worker, which cold-loads the model and says so in the log. A worker that dies on its own, sends something unreadable or
stops answering is ended and reported as the file's failure with its own last words (stderr); nothing waits forever.

**Containment.** The worker is a class-A child (:mod:`shared.child_ownership`): its own process group, started through
``child_entry.py``, whose first statements watch the owner's lifeline. The owner is the app window's
(:func:`shared.subprocess_utils.containment_owner`); a process without one (a command-line tool, a test) gets a private
owner here. Every signal is identity-checked by the owner: only this worker's group, only while it is this process's
unreaped child.

**A worker's exit proves nothing about its group** (v0.8.x P5-D). However the worker ends -- Cancel, a crash, an engine
switch, an exit of its own -- it is never reaped before its whole group has been ended
(``child_ownership.end_led_group``: under the ``Popen``'s waitpid lock, unreaped, same kernel start time, signalled
until the kernel says nothing is left), so nothing it left in that group outlives it; nothing here ``poll()``s or
``wait()``s it first. Its exit is seen without reaping it, so a leftover holding its output cannot keep a request
waiting for an unrelated timeout, and a pipe is never closed under a reader still blocked on it. A group that cannot be
confirmed ended is reported: a Cancel then fails the file instead of claiming a clean stop.

**Where.** :func:`isolation_enabled` is true on macOS only. Windows keeps Kokoro and Chatterbox in-process exactly as
released (D17); nothing here runs there.
"""

from __future__ import annotations

import collections
import contextlib
import itertools
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

WORKER = Path(__file__).resolve().with_name("local_engine_worker.py")
EVENT_PREFIX = "@@EVENT "
PROTOCOL_VERSION = 1

#: How often a waiting request looks at the run's Cancel latch. Cancel's stop bound is this plus a SIGKILL and a reap.
CANCEL_POLL_S = 0.05
#: The local-engine worker's stop bound after Cancel (plan section 11.2.1, D17).
CANCEL_BOUND_S = 2.0
#: How long a new worker has to say ``hello`` (an interpreter start, before torch is imported).
HELLO_TIMEOUT_S = 60.0
#: How long a model load may take before the worker counts as hung.
LOAD_TIMEOUT_S = 600.0
#: How long one chunk's model call may take. A 3,000-character Kokoro chunk on a Mac CPU takes well under a minute; this
#: is a watchdog against a worker that stopped answering, never a pace.
CHUNK_TIMEOUT_S = 1800.0
#: How much of the worker's standard error is kept for a failure message.
STDERR_TAIL_CHARS = 2000
#: v0.8.x P5-D: ending the worker's group (SIGKILL, then the kernel's word that nothing is left) may take this long; a
#: SIGKILLed group is empty within milliseconds. With :data:`REAP_BOUND_S` and :data:`OUTPUT_EOF_S` it keeps even the
#: worst case inside :data:`CANCEL_BOUND_S` -- and anything slower is reported, never claimed.
GROUP_END_BOUND_S = 1.0
#: How long reaping the worker may take once its group has ended (it is a zombie by then).
REAP_BOUND_S = 0.5
#: Once its group has ended every writer is gone, so the worker's output reaches its end at once; output still open
#: after this is held by something outside that group.
OUTPUT_EOF_S = 0.4
#: After the worker has exited on its own (seen without reaping it), how long what it wrote before exiting may take to
#: arrive before its exit is acted on.
EXIT_DRAIN_S = 0.5


#: How each engine is named in a message.
ENGINE_NAMES = {"kokoro": "Kokoro", "chatterbox": "Chatterbox"}


def engine_name(engine: str) -> str:
    return ENGINE_NAMES.get(engine, engine)


class LocalEngineFailed(RuntimeError):
    """The local-engine worker failed this request: it could not start, died, stopped answering, broke the protocol
    or returned audio that did not check out. The message says which, with the worker's own last words."""


class WorkerError(RuntimeError):
    """The worker answered a request with an error of ``kind`` (``assets``, ``pipeline``, ``synthesis``)."""

    def __init__(self, kind: str, message: str, type_name: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.type_name = type_name


def isolation_enabled(platform: Optional[str] = None) -> bool:
    """True where local-engine inference runs in the preemptible worker: macOS only (D17). Windows keeps the released
    in-process route."""
    return (sys.platform if platform is None else platform) == "darwin"


def parse_event(line: str) -> Optional[dict]:
    """A worker event, ``None`` for any other line, or ``{"event": "_malformed"}`` for a broken one."""
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
    except ValueError:
        return {"event": "_malformed", "raw": line[:200]}
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        return {"event": "_malformed", "raw": line[:200]}
    return event


def validate_pcm(path: Optional[str], *, samples: int, sample_rate: int, expected_rate: int, dtype: str):
    """The chunk's PCM from the worker's file, or :class:`LocalEngineFailed` if it is not exactly what was reported:
    float32, one channel, ``samples`` long, every value finite, at the engine's own rate."""
    import numpy as np

    if int(sample_rate) != int(expected_rate):
        raise LocalEngineFailed(f"the voice engine returned audio at {sample_rate} Hz, not {expected_rate} Hz")
    if dtype != "float32":
        raise LocalEngineFailed(f"the voice engine returned {dtype} audio, not float32")
    if int(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    if not path:
        raise LocalEngineFailed("the voice engine reported audio but handed none back")
    try:
        pcm = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise LocalEngineFailed(f"the voice engine's audio could not be read ({exc})") from exc
    if pcm.dtype != np.float32 or pcm.ndim != 1:
        raise LocalEngineFailed(f"the voice engine's audio is {pcm.dtype} with shape {pcm.shape}, not mono float32")
    if pcm.size != int(samples):
        raise LocalEngineFailed(f"the voice engine's audio has {pcm.size} samples, not the {samples} it reported")
    if not bool(np.isfinite(pcm).all()):
        raise LocalEngineFailed("the voice engine's audio contains values that are not finite")
    return pcm


@dataclass
class ChunkResult:
    pcm: object  # numpy float32, possibly empty
    phonemes: list = field(default_factory=list)
    gen_s: float = 0.0
    event: dict = field(default_factory=dict)


#: What the host keeps of each event (no text, no phonemes): enough to time a Cancel and follow the worker's memory.
_NOTED = frozenset({"id", "pid", "pgid", "chars", "samples", "gen_s", "load_s", "cached", "kind", "footprint",
                    "peak_footprint"})


@dataclass
class HostEvent:
    """What the host saw, with the monotonic time it saw it: the evidence the Cancel tests synchronise on."""

    at: float
    name: str
    detail: dict


class WorkerHost:
    """One worker for one engine. Requests are made one at a time (each engine's ceiling is one file at a time)."""

    def __init__(self, engine: str, *, sample_rate: int, log: Callable[[str], None] = print,
                 python: Optional[str] = None, argv: Optional[list] = None, env: Optional[dict] = None,
                 owner=None, hello_timeout_s: float = HELLO_TIMEOUT_S, load_timeout_s: float = LOAD_TIMEOUT_S,
                 chunk_timeout_s: float = CHUNK_TIMEOUT_S, label: str = "") -> None:
        self.engine = engine
        self.sample_rate = sample_rate
        self.log = log
        self._python = python or sys.executable
        self._argv = argv  # tests start a stand-in worker; production always runs WORKER
        self._env = env
        self._owner = owner
        self.hello_timeout_s = hello_timeout_s
        self.load_timeout_s = load_timeout_s
        self.chunk_timeout_s = chunk_timeout_s
        self.label = label or f"{engine}-worker"
        self._lock = threading.RLock()  # one request at a time
        self._proc: Optional[subprocess.Popen] = None
        self._events: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr: collections.deque = collections.deque(maxlen=200)
        self._readers: list[threading.Thread] = []
        self._ids = itertools.count(1)
        self._scratch: Optional[Path] = None
        self.hello: dict = {}
        self.loaded: dict[str, dict] = {}
        self.starts = 0
        self.history: list[HostEvent] = []
        self.release_when_idle = False
        self._in_use = 0  # requests being made now, from any thread
        self._start_time: Optional[tuple[int, int]] = None  # the worker's kernel start time, recorded at spawn
        self._end_lock = threading.Lock()  # one end of a worker at a time (a Cancel and a run's own end can meet)
        #: How the last worker this host ended was retired (``child_ownership.Retired``), or None.
        self.last_end = None

    # -- state ----------------------------------------------------------------------------------------------------
    def _note(self, name: str, **detail) -> None:
        self.history.append(HostEvent(time.monotonic(), name, detail))

    def _exited(self) -> bool:
        """True once the worker has exited -- seen WITHOUT reaping it, so its id and its group's stay reserved until its
        group has been ended (v0.8.x P5-D)."""
        from shared import child_ownership

        proc = self._proc
        return proc is None or child_ownership.has_exited(proc, self._start_time)

    def alive(self) -> bool:
        return self._proc is not None and not self._exited()

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    def busy(self) -> bool:
        """True while a request is being made, whichever thread asks."""
        return self._in_use > 0

    @contextlib.contextmanager
    def _request(self):
        with self._lock:
            self._in_use += 1
            try:
                yield
            finally:
                self._in_use -= 1

    def _containment(self):
        if self._owner is None:
            from shared import subprocess_utils

            self._owner = subprocess_utils.containment_owner()
            if self._owner is None:
                from shared import child_ownership

                self._owner = child_ownership.Owner(self.log)  # this process's own: a tool or test without the app
        return self._owner

    def _stderr_tail(self) -> str:
        text = "\n".join(self._stderr).strip()
        return text[-STDERR_TAIL_CHARS:]

    # -- start --------------------------------------------------------------------------------------------------------
    def _worker_argv(self) -> list:
        if self._argv is not None:
            return [str(part) for part in self._argv]
        # -I: no user site, no PYTHON* variables, no script folder on the path; -B: never writes bytecode into scripts/.
        return [self._python, "-I", "-B", str(WORKER), self.engine]

    def _start(self, cancel_check: Optional[Callable[[], bool]] = None) -> None:
        owner = self._containment()
        env = dict(os.environ if self._env is None else self._env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self._events = queue.Queue()
        self._stderr.clear()
        began = time.monotonic()
        try:
            proc = owner.popen_python(self._worker_argv(), label=self.label, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                      cwd=str(WORKER.parent))
        except RuntimeError as exc:  # ContainmentUnavailable (the app is closing, or no guardian): nothing started
            raise LocalEngineFailed(f"The voice engine could not be started under the app's control ({exc}).") from exc
        from shared import child_ownership

        child = owner.child(proc) if hasattr(owner, "child") else None
        self._start_time = (child.start_time if child is not None and child.start_time is not None
                            else child_ownership.process_start_time(proc.pid))  # just started: still its own id
        if self._start_time is None and sys.platform != "win32":
            # v0.8.x P5-D-R1: a worker whose identity could not be recorded is never admitted -- its group could be
            # neither ended on Cancel nor retired before it is reaped. Its group is not signalled (no proof); the leader
            # alone is ended through Popen's own guarded kill, before it has run anything of the worker.
            from tts import qwen3_process

            qwen3_process.end_unadmitted(proc)
            with contextlib.suppress(Exception):
                owner.forget(proc)
            raise LocalEngineFailed("The voice engine could not be started under the app's control (its identity "
                                    "could not be recorded when it started, so it was stopped before it could run).")
        self._proc = proc
        self.starts += 1
        self._note("spawned", pid=proc.pid)
        events, tail = self._events, self._stderr

        def pump_out() -> None:
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    events.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
            except (OSError, ValueError):
                pass
            finally:
                events.put(None)

        def pump_err() -> None:
            try:
                for raw in proc.stderr:  # type: ignore[union-attr]
                    tail.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
            except (OSError, ValueError):
                pass

        self._readers = [threading.Thread(target=pump_out, name=f"{self.label}-out", daemon=True),
                         threading.Thread(target=pump_err, name=f"{self.label}-err", daemon=True)]
        for reader in self._readers:
            reader.start()
        hello = self._await(lambda e: e["event"] == "hello", self.hello_timeout_s, cancel_check, request_id=None)
        if hello.get("protocol") != PROTOCOL_VERSION or hello.get("engine") != self.engine:
            self.kill("protocol mismatch")
            raise LocalEngineFailed(f"The voice engine's worker is not the one this app expects ({hello}).")
        self.hello = hello
        self._note("ready", pid=hello.get("pid"), pgid=hello.get("pgid"), seconds=round(time.monotonic() - began, 3))

    def ensure_started(self, cancel_check: Optional[Callable[[], bool]] = None) -> None:
        with self._lock:
            if not self.alive():
                if self._proc is not None:
                    self._reap_quietly()
                self._start(cancel_check)

    # -- requests -----------------------------------------------------------------------------------------------------
    def _send(self, request: dict) -> None:
        try:
            self._proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]
        except (OSError, ValueError) as exc:
            self._died(f"it could not be sent the request ({exc})")

    def _died(self, how: str, worker: Optional[subprocess.Popen] = None):
        from shared import child_ownership

        proc = self._proc if worker is None else worker  # read once: a Cancel hook may retire it meanwhile
        if proc is not None:  # its exit is waited for (bounded) WITHOUT reaping it: its group is ended first
            child_ownership.wait_exited(proc, 2.0, self._start_time)
        _seconds, retired = self._end("died", worker)
        returncode = retired.returncode if retired is not None else None
        tail = self._stderr_tail()  # complete: its group has ended, so its standard error has reached its end
        self._note("died", how=how, returncode=returncode)
        detail = f" (exit code {returncode})" if returncode is not None else ""
        problem = retired.problem() if retired is not None else None
        raise LocalEngineFailed(f"The {engine_name(self.engine)} voice engine stopped unexpectedly: {how}{detail}."
                                + (f" It could not be confirmed stopped: {problem}." if problem else "")
                                + (f" {tail}" if tail else ""))

    def _await(self, wanted: Callable[[dict], bool], timeout_s: float,
               cancel_check: Optional[Callable[[], bool]], *, request_id) -> dict:
        """The next event that ``wanted`` accepts. Cancel (seen within :data:`CANCEL_POLL_S`) ends the worker's group at
        once and raises ``ConversionCancelled``; an exit, a broken message or ``timeout_s`` without an event ends it and
        raises :class:`LocalEngineFailed`; the worker's ``error`` for this request raises :class:`WorkerError`."""
        deadline = time.monotonic() + timeout_s
        exited_at: Optional[float] = None
        worker = self._proc  # v0.8.x P5-D-R2: the worker this request is using; its own end is asked for by name
        while True:
            if cancel_check is not None and cancel_check():
                self._cancel(worker)
            now = time.monotonic()
            if now >= deadline:
                self._note("timeout", seconds=timeout_s)
                self.kill("no answer")
                tail = self._stderr_tail()
                raise LocalEngineFailed(f"The {engine_name(self.engine)} voice engine stopped answering for "
                                        f"{int(timeout_s)} s and was stopped." + (f" {tail}" if tail else ""))
            try:
                line = self._events.get(timeout=min(CANCEL_POLL_S, max(0.0, deadline - now)))
            except queue.Empty:
                # v0.8.x P5-D: the worker's exit, seen without reaping it, ends the wait as its end of output does --
                # something left in its group can hold that output open. What it wrote first is still read.
                if self._exited():
                    exited_at = now if exited_at is None else exited_at
                    if now - exited_at >= EXIT_DRAIN_S:
                        self._died("it exited", worker)
                continue
            if line is None:
                self._died("it exited", worker)
            event = parse_event(line)
            if event is None:
                self._stderr.append(line[:300])  # nothing else is written to the protocol channel; kept, not trusted
                continue
            if event["event"] == "_malformed":
                self.kill("malformed")
                raise LocalEngineFailed(f"The {engine_name(self.engine)} voice engine sent an unreadable message "
                                        "and was stopped.")
            self._note(event["event"], **{k: v for k, v in event.items() if k in _NOTED})
            if event["event"] == "error" and event.get("id") in (request_id, None):
                raise WorkerError(str(event.get("kind", "")), str(event.get("message", "")), str(event.get("type", "")))
            if wanted(event):
                return event

    def _cancel(self, worker: Optional[subprocess.Popen] = None):
        """Cancel: the worker's group ends now (SIGKILL), is reaped, and the run is told it was cancelled. *worker*: the
        one a request in flight is using (v0.8.x P5-D-R2) -- if another caller has already retired it, its answer."""
        from shared.cancellation import ConversionCancelled

        self._note("cancel-seen")
        seconds, retired = self._end("cancel", worker)
        self._note("cancel-stopped", seconds=round(seconds, 4))
        problem = retired.problem() if retired is not None else None
        if problem:  # never a clean Cancel (v0.8.x P5-D): the file fails and says why
            raise LocalEngineFailed(f"The {engine_name(self.engine)} voice engine was asked to stop, but it could not "
                                    f"be confirmed stopped: {problem}.")
        raise ConversionCancelled("Conversion cancelled by user.")

    def load(self, request: dict, cancel_check: Optional[Callable[[], bool]] = None) -> dict:
        """Load the model the request names (``loaded`` is cached per worker: a warm worker answers at once)."""
        with self._request():
            key = json.dumps(request, sort_keys=True)
            if self.alive() and key in self.loaded:
                return {**self.loaded[key], "reused": True}
            if cancel_check is not None and cancel_check():
                self._cancel()
            self.ensure_started(cancel_check)
            rid = next(self._ids)
            self._send({"op": "load", "id": rid, **request})
            event = self._await(lambda e: e["event"] == "loaded" and e.get("id") == rid, self.load_timeout_s,
                                cancel_check, request_id=rid)
            self.loaded[key] = event
            return {**event, "reused": False, "worker_start": self.starts}

    def synthesize(self, request: dict, cancel_check: Optional[Callable[[], bool]] = None,
                   folder: Optional[Path] = None) -> ChunkResult:
        """One chunk through the model. Nothing is sent once Cancel is latched; Cancel while it runs ends the worker."""
        with self._request():
            if cancel_check is not None and cancel_check():
                self._cancel()
            if not self.alive():
                raise LocalEngineFailed(f"The {engine_name(self.engine)} voice engine is not running.")
            rid = next(self._ids)
            out = self._result_path(folder, rid)
            self._send({"op": "synth", "id": rid, "out": str(out), **request})
            try:
                event = self._await(lambda e: e["event"] == "result" and e.get("id") == rid, self.chunk_timeout_s,
                                    cancel_check, request_id=rid)
                pcm = validate_pcm(event.get("out"), samples=int(event.get("samples", -1)),
                                   sample_rate=int(event.get("sample_rate", 0)), expected_rate=self.sample_rate,
                                   dtype=str(event.get("dtype", "")))
            except LocalEngineFailed:
                if self.alive():
                    self.kill("bad result")
                raise
            finally:
                for leftover in (out, Path(str(out) + ".part")):
                    with contextlib.suppress(OSError):
                        leftover.unlink()
            return ChunkResult(pcm=pcm, phonemes=list(event.get("phonemes") or []),
                               gen_s=float(event.get("gen_s") or 0.0), event=event)

    def _result_path(self, folder: Optional[Path], rid: int) -> Path:
        if folder is None:
            from shared import work_area

            folder = work_area.current_folder()
        if folder is None:  # a tool or test outside a conversion: a private folder this host removes when it ends
            if self._scratch is None:
                self._scratch = Path(tempfile.mkdtemp(prefix=f"act-{self.engine}-worker-"))
            folder = self._scratch
        return Path(folder) / f"{self.engine}-chunk-{os.getpid()}-{self.starts}-{rid}.npy"

    # -- end ----------------------------------------------------------------------------------------------------------
    def _reap_quietly(self, expected: Optional[subprocess.Popen] = None):
        """Retire the worker (v0.8.x P5-D): its whole group ended while its id is proved its own -- running or already
        exited -- then its output read to its end, and only then is it reaped. Returns ``child_ownership.Retired`` (None
        when there was no worker, or it is not *expected*), also kept on that worker as ``act_retired``. Bounded by
        :data:`GROUP_END_BOUND_S` + :data:`REAP_BOUND_S` + :data:`OUTPUT_EOF_S`; never raises. A stream is closed only
        once its reader has finished: closing it under a reader still blocked on it would wait for that read -- for as
        long as whatever holds the pipe runs."""
        from shared import child_ownership

        with self._end_lock:  # a second caller finds the worker already retired
            proc = self._proc
            if proc is None or (expected is not None and proc is not expected):
                return None
            group = child_ownership.end_led_group(proc, self._start_time, bound_s=GROUP_END_BOUND_S)
            with contextlib.suppress(OSError, ValueError, AttributeError):
                proc.stdin.close()  # type: ignore[union-attr]  # only this host writes to it
            if group not in (child_ownership.GROUP_ENDED, child_ownership.GROUP_SIGNALLED) and proc.returncode is None:
                # v0.8.x P5-I-R3 remediation 2: never reaped with its group not confirmed ended -- its id keeps the group
                # reserved; the owner (``forget`` below) keeps ending the group and reaps it once the group is gone.
                returncode = None
            else:
                try:
                    returncode = proc.wait(timeout=REAP_BOUND_S)
                except subprocess.TimeoutExpired:
                    returncode = None
                except ChildProcessError:
                    returncode = proc.returncode
            until = time.monotonic() + OUTPUT_EOF_S
            for reader in self._readers:
                reader.join(timeout=max(0.0, until - time.monotonic()))
            output_open = any(reader.is_alive() for reader in self._readers)
            for stream, reader in ((proc.stdout, self._readers[0] if self._readers else None),
                                   (proc.stderr, self._readers[1] if len(self._readers) > 1 else None)):
                if reader is None or not reader.is_alive():
                    with contextlib.suppress(OSError, ValueError, AttributeError):
                        stream.close()  # type: ignore[union-attr]
            with contextlib.suppress(Exception):
                self._containment().forget(proc)
            self._proc = None
            self.loaded.clear()
            retired = child_ownership.Retired(returncode=returncode, group=group, output_open=output_open)
            self.last_end = retired
            proc.act_retired = retired  # type: ignore[attr-defined]  # v0.8.x P5-D-R2: this worker's own answer
            problem = retired.problem()
            if problem:
                self._note("unconfirmed", pid=proc.pid, group=group, output_open=output_open)
                with contextlib.suppress(Exception):  # v0.8.x P5-I-R3: no run settles clean while it may still run
                    from shared import subprocess_utils

                    subprocess_utils.note_unresolved(proc.pid, self._start_time,
                                                     f"{engine_name(self.engine)} voice engine worker")
                with contextlib.suppress(Exception):
                    self.log(f"The {engine_name(self.engine)} voice engine (pid {proc.pid}) could not be confirmed "
                             f"stopped: {problem}.")
            return retired

    def _end(self, reason: str, worker: Optional[subprocess.Popen] = None):
        """:meth:`kill`, also returning how the worker was retired (``child_ownership.Retired``, or None when there was
        none to end). *worker*: the one a request in flight is using (v0.8.x P5-D-R2); without it, the current one."""
        began = time.monotonic()
        proc = self._proc if worker is None else worker
        if proc is None:
            return 0.0, None
        retired = self._reap_quietly(proc)
        if retired is None:  # v0.8.x P5-D-R1/R2: another caller retired this very worker -- while this end waited, or
            # before it began -- so that worker's own answer stands (never another's): an end it could not confirm never
            # turns into a clean Cancel here.
            retired = getattr(proc, "act_retired", None)
        seconds = time.monotonic() - began
        self._note("killed", reason=reason, seconds=round(seconds, 4), returncode=proc.returncode)
        return seconds, retired

    def kill(self, reason: str = "") -> float:
        """End the worker's whole group at once (SIGKILL, identity-checked: only while it is this process's unreaped
        child with its recorded start time) and only then reap it. Returns the seconds it took. Never raises; nothing
        is waited for beyond its bounds. How it went is :attr:`last_end`."""
        return self._end(reason)[0]

    def close(self, reason: str = "") -> None:
        """An orderly end (engine switch, tool or test done): ask the worker to exit, give it a second (its exit is
        waited for without reaping it), then end its group and reap it."""
        from shared import child_ownership

        proc = self._proc
        if proc is not None and not self._exited():
            with contextlib.suppress(OSError, ValueError, AttributeError):
                proc.stdin.write(b'{"op": "exit"}\n')  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]
            child_ownership.wait_exited(proc, 1.0, self._start_time)
        self.kill(reason or "closed")
        if self._scratch is not None:
            import shutil

            shutil.rmtree(self._scratch, ignore_errors=True)
            self._scratch = None


# --------------------------------------------------------------------------- the one worker of this process
_HOST: Optional[WorkerHost] = None
_HOST_LOCK = threading.Lock()


def host_for(engine: str, *, sample_rate: int, log: Callable[[str], None] = print) -> WorkerHost:
    """This process's worker host for ``engine``. A host for another engine is closed first (one worker at a time)."""
    global _HOST
    with _HOST_LOCK:
        previous = _HOST
        if previous is not None and previous.engine != engine:
            _HOST = None
            previous.close(f"engine switched to {engine}")
        if _HOST is None:
            _HOST = WorkerHost(engine, sample_rate=sample_rate, log=log)
        _HOST.log = log
        return _HOST


def current_host() -> Optional[WorkerHost]:
    return _HOST


def release(reason: str = "released") -> None:
    """Close this process's worker now, whatever its engine. Never raises."""
    global _HOST
    with _HOST_LOCK:
        host, _HOST = _HOST, None
    if host is not None:
        with contextlib.suppress(Exception):
            host.close(reason)


def cancel_requested(backend: str) -> None:
    """A run of ``backend`` was cancelled: its worker ends now even when it is not answering a request -- paused
    between files, or the run finishing a file -- so the next run starts a new one, as after a Cancel mid-chunk. A
    worker answering a request is ended by that request's own Cancel poll (within :data:`CANCEL_POLL_S`), so this
    never races it: it acts only if it can take the request lock at once. Off the caller's thread; never raises. A worker
    that has already exited on its own is retired too (v0.8.x P5-D): its group is ended before it is reaped."""
    host = _HOST
    if host is None or host.engine != backend or host._proc is None:
        return

    def end_if_idle() -> None:
        if host._lock.acquire(blocking=False):
            try:
                host.kill("cancel")
            finally:
                host._lock.release()

    global _CANCEL_RETIREMENT
    thread = threading.Thread(target=end_if_idle, name="local-engine-cancel", daemon=True)
    _CANCEL_RETIREMENT = thread
    thread.start()


#: v0.8.x P5-I-R3 remediation 3 (finding 4): the retirement a Cancel began (:func:`cancel_requested`), so the run's
#: settlement can wait for it before it reports anything.
_CANCEL_RETIREMENT: Optional[threading.Thread] = None


def cancel_retirement_pending(timeout: float) -> bool:
    """Wait at most *timeout* for the idle-worker retirement a Cancel began; True when it is still running then (the
    worker may still be at work: no run may be reported cancelled or finished). A worker it could not confirm ended is
    recorded as unresolved by the retirement itself. False when there was none. Never raises."""
    thread = _CANCEL_RETIREMENT
    if thread is None:
        return False
    thread.join(max(0.0, timeout))
    return thread.is_alive()


def engine_selected(backend: str) -> None:
    """The panel's voice now belongs to ``backend``: a warm worker of another engine is released (off the caller's
    thread, so the panel never waits on it). A worker that is serving a run is left to it and released when the next
    run that does not use it begins (:func:`host_for`). macOS only; nothing happens where there is no worker. A worker
    that has already exited on its own is released too (v0.8.x P5-D-R1): its exit is no proof that what it left in its
    group has ended, so its group is ended before it is reaped -- now, not at the next run of its engine."""
    host = _HOST
    if host is None or host.engine == backend or host._proc is None:
        return
    if host.busy():
        host.release_when_idle = True
        return
    threading.Thread(target=release, args=(f"engine switched to {backend}",), name="local-engine-release",
                     daemon=True).start()
