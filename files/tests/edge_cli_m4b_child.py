"""The Edge command line's ``--format m4b`` run in a console of its own, so a real Ctrl+C can reach it (v0.7.2 Phase 6E,
ACT72-010). Not a test: its callers are.

Three roles in one file, all standard library at import time:

* the **parent** (:class:`CliChild`, used by the tests) starts the child with ``CREATE_NO_WINDOW``, which gives it a console
  of its own that has no window and that no other program shares, inside a kill-on-close job (``low_memory_probe.OwnedTree``),
  so "every process this run left" is an exact list from the operating system, not a guess from names;
* the **child** (:func:`child_main`) runs the real ``epub2tts_edge.main()``: the real argument parsing, runner, work area,
  ``generate_metadata``, ``make_m4b``, ``add_cover`` and publication, and real FFmpeg. Only the source parsing and the
  narration (``get_book``, ``read_book``: Edge's network voice) are replaced, by chapters whose audio is the FLAC parts the
  test made. Every child process it starts is seen at the operating-system boundary (``subprocess.Popen``), which is also
  where a test may slow a step down (``-re``), stand a controlled program in for it, make it ignore ``terminate`` or suspend
  it. The production code is not edited;
* the **sender** (:func:`send_ctrl_c`) is a separate base-interpreter process with no console at all. It attaches to the
  child's console only, ignores the event itself, and generates CTRL_C_EVENT there: what pressing Ctrl+C in that window
  would do. The test's own process never generates a console event, so the console the tests were started from (an
  editor's terminal, the gate's) can never receive one.

The child writes one JSON object per line to its event log; the parent reads it to know when to press Ctrl+C.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_PYTHON = Path(getattr(sys, "_base_executable", "") or sys.executable)
#: What Python itself exits with on Windows when a KeyboardInterrupt is never caught (STATUS_CONTROL_C_EXIT).
UNCAUGHT_CTRL_C = 0xC000013A
CTRL_C_EVENT = 0
DETACHED_PROCESS = 0x00000008


def _kernel32():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wt.BOOL]
    kernel.AttachConsole.argtypes = [wt.DWORD]
    kernel.GenerateConsoleCtrlEvent.argtypes = [wt.DWORD, wt.DWORD]
    return kernel


def creation_time(handle) -> int:
    """A process's creation time (100 ns units): with its id, its identity. 0 when it cannot be read."""
    kernel = _kernel32()
    times = [wt.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(wt.HANDLE(int(handle)), *(ctypes.byref(t) for t in times)):
        return 0
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def alive(pid: int, created: int) -> bool:
    """True only if the very process that had ``pid`` and ``created`` is still running. Read-only."""
    kernel = _kernel32()
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wt.DWORD()
        return (creation_time(handle) == created and bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                and code.value == 259)  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def end(pid: int, created: int) -> None:
    """Stop that very process, if it is still the one with that identity: test clean-up only."""
    kernel = _kernel32()
    handle = kernel.OpenProcess(0x1001, False, pid)  # PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        try:
            if creation_time(handle) == created:
                kernel.TerminateProcess(handle, 9)
        finally:
            kernel.CloseHandle(handle)


def media_children(of_pid: int) -> list[int]:
    """Process ids of every ffmpeg.exe / ffprobe.exe whose parent is ``of_pid``. Read-only."""

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260)]

    kernel = _kernel32()
    kernel.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    kernel.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(ENTRY)]
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    found = []
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == of_pid and entry.szExeFile.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                found.append(int(entry.th32ProcessID))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return found


# --------------------------------------------------------------------------- the sender


def send_ctrl_c(target_pid: int, timeout: float = 30.0) -> int:
    """Press Ctrl+C in ``target_pid``'s console, from a process with no console of its own. 0 when the event was sent."""
    done = subprocess.run([str(BASE_PYTHON), "-I", str(Path(__file__).resolve()), "--ctrl-c", str(target_pid)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=DETACHED_PROCESS, timeout=timeout)
    return done.returncode


def _ctrl_c_main(target_pid: int) -> int:
    kernel = _kernel32()
    kernel.FreeConsole()  # started detached, so there is none; this only makes certain of it
    if not kernel.AttachConsole(target_pid):
        return 2  # not attached anywhere: nothing may be sent
    kernel.SetConsoleCtrlHandler(None, True)  # this process ignores the event it is about to generate
    sent = kernel.GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0)  # every process on THAT console: the child's tree only
    kernel.FreeConsole()
    return 0 if sent else 3


# --------------------------------------------------------------------------- the parent


class CliChild:
    """One run of the command line in its own console and job. ``close`` always leaves nothing running."""

    def __init__(self, work: Path, config: dict, *, scripts: Path, python: str = sys.executable) -> None:
        import low_memory_probe

        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.log = self.work / "events.jsonl"
        self.output = self.work / "child-output.txt"
        self.temp = self.work / "temp"
        self.temp.mkdir(exist_ok=True)
        config = dict(config, log=str(self.log), scripts=str(scripts), temp=str(self.temp))
        config_file = self.work / "config.json"
        config_file.write_text(json.dumps(config, indent=1), encoding="utf-8")
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TEMP=str(self.temp),
                           TMP=str(self.temp))
        self.tree = low_memory_probe.OwnedTree()
        with open(self.output, "wb") as output:
            self.process = subprocess.Popen([python, "-I", str(Path(__file__).resolve()), str(config_file)],
                                            stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        self.tree.adopt(self.process)
        self.survivors: list[int] | None = None

    def events(self) -> list[dict]:
        try:
            text = self.log.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip().endswith("}")]

    def wait_for(self, predicate, timeout: float = 60.0, what: str = "the event") -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.events():
                if predicate(event):
                    return event
            if self.process.poll() is not None:
                break
            time.sleep(0.02)
        raise AssertionError(f"no {what}; child exit {self.process.poll()}; events {self.events()}; "
                             f"output {self.output_text()[-2000:]}")

    def spawned(self, step: int) -> dict:
        return self.wait_for(lambda e: e.get("event") == "spawn" and e.get("step") == step,
                             what=f"FFmpeg step {step}")

    @property
    def interpreter_pid(self) -> int:
        return self.wait_for(lambda e: e.get("event") == "ready", what="ready")["pid"]

    def ctrl_c(self) -> float:
        """Press Ctrl+C in the child's console; returns the moment it was sent."""
        pid = self.interpreter_pid
        code = send_ctrl_c(pid)
        assert code == 0, f"the console event could not be sent (sender exit {code})"
        return time.monotonic()

    def wait(self, timeout: float) -> int | None:
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def output_text(self) -> str:
        try:
            return self.output.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def close(self) -> list[int]:
        """Whatever the run left in its job (the venv launcher and the interpreter go one after the other, so a moment is
        allowed), then end all of it. Returns those survivors' ids; a second call returns the first one's answer."""
        if self.survivors is not None:
            return self.survivors
        if self.process.poll() is None:
            self.tree.kill()
            self.process.wait(timeout=30)
        settle = time.monotonic() + 5
        survivors = self.tree.alive()
        while survivors and time.monotonic() < settle:
            time.sleep(0.05)
            survivors = self.tree.alive()
        for event in self.events():  # anything it reported starting, by identity, whether or not the job caught it
            if event.get("event") in ("spawn", "sentinel") and alive(event["pid"], event["created"]):
                survivors = sorted(set(survivors) | {event["pid"]})
                end(event["pid"], event["created"])
        self.tree.kill()
        self.tree.close()
        self.survivors = survivors
        return survivors


# --------------------------------------------------------------------------- the child


class _Log:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()

    def write(self, **event) -> None:
        event["t"] = time.monotonic()
        with self._lock, open(self._path, "a", encoding="utf-8") as log:
            log.write(json.dumps(event) + "\n")


def _step_of(argv) -> int:
    """1 for make_m4b's concat into FLAC-in-MP4, 2 for its AAC encode with the chapters; 0 for anything else."""
    if not isinstance(argv, (list, tuple)):
        return 0
    words = [str(a) for a in argv]
    if "concat" in words and "-f" in words and words[-1].endswith(".m4a"):
        return 1
    if "-map_metadata" in words and "aac" in words and words[-1].endswith(".m4b"):
        return 2
    return 0


def _suspend(pid: int) -> None:
    """A real stall: the operating system stops the process, as a hung drive or scanner would."""
    kernel = _kernel32()
    handle = kernel.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if handle:
        ctypes.WinDLL("ntdll").NtSuspendProcess(ctypes.c_void_p(handle))
        kernel.CloseHandle(handle)


def child_main(config_path: str) -> int:
    import faulthandler
    import signal
    import tempfile
    import traceback

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    log = _Log(config["log"])
    kernel = _kernel32()
    # As in a console a person opened: Ctrl+C processed normally (an "ignore" inherited from whoever started the tests is
    # undone; it applies to this process and what it starts, nothing else).
    kernel.SetConsoleCtrlHandler(None, False)
    in_job = wt.BOOL()
    kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(in_job))
    stacks = open(Path(config["log"]).with_name("stacks.txt"), "w")
    faulthandler.dump_traceback_later(config.get("stacks_after", 240), exit=False, file=stacks)
    tempfile.tempdir = config["temp"]
    sys.path.insert(0, config["scripts"])

    from tts.epub2tts_edge import epub2tts_edge as edge
    from tts.epub2tts_edge import runner

    prepare = config.get("prepare")  # a negative control only: [module file, argument]; its apply() plants one defect here
    if prepare:
        import importlib.util

        spec = importlib.util.spec_from_file_location("edge_cli_prepare", prepare[0])
        planted = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(planted)
        planted.apply(prepare[1])
        log.write(event="prepared", argument=prepare[1])

    chapters = config["chapters"]  # [[title, flac part], ...]

    def get_book(sourcefile, speech_prep=None):
        contents = [{"title": title, "narrate_title": True, "paragraphs": ["x"]} for title, _ in chapters]
        return contents, config["title"], config["author"], [title for title, _ in chapters]

    def read_book(book_contents, speaker, *_args, workdir=None, **_kwargs):
        parts = []
        for index, (_, part) in enumerate(chapters):
            target = os.path.join(workdir, f"part{index}.flac")
            shutil.copyfile(part, target)
            parts.append(target)
        log.write(event="parts", parts=parts, workdir=workdir)
        return parts

    edge.ensure_punkt = lambda: None
    runner.get_book = get_book
    runner.read_book = read_book
    for name, value in (config.get("deadline") or {}).items():
        if hasattr(edge, name):
            setattr(edge, name, value)
        else:
            log.write(event="no-such-setting", name=name)

    pause = config.get("pause_after_step")  # [step, seconds]: this process waits there, as if busy
    if pause:
        real_run = edge._run_ffmpeg
        finished = [0]

        def run_ffmpeg(cmd, *args, **kwargs):
            result = real_run(cmd, *args, **kwargs)
            finished[0] += 1
            if finished[0] == pause[0]:
                log.write(event="after-step", step=finished[0])
                until = time.monotonic() + pause[1]
                while time.monotonic() < until:
                    time.sleep(0.02)
            return result

        edge._run_ffmpeg = run_ffmpeg

    real_popen = subprocess.Popen
    sentinel = None
    if config.get("sentinel"):
        # An FFmpeg-named program this very process started that no step owns: it must outlive everything.
        sentinel = real_popen([config["sentinel"], "-n", "600", "127.0.0.1"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        log.write(event="sentinel", pid=sentinel.pid, created=creation_time(sentinel._handle))
    stand_in = config.get("stand_in") or {}  # {"<step>": [image, seconds]}
    slow = set(config.get("slow_steps") or [])
    stubborn = set(config.get("ignore_terminate") or [])
    suspend = config.get("suspend_step")  # [step, after seconds]

    class Spy(real_popen):  # type: ignore[valid-type, misc]
        def __init__(self, args, *rest, **kwargs):
            step = _step_of(args)
            original = [str(a) for a in args] if step else None
            if step and str(step) in stand_in:
                image, seconds = stand_in[str(step)]
                args = [image, "-n", str(seconds), "127.0.0.1"]
            elif step in slow:
                args = [args[0], "-re", *args[1:]]
            super().__init__(args, *rest, **kwargs)
            if not step:
                return
            log.write(event="spawn", step=step, pid=self.pid, created=creation_time(self._handle),
                      argv=[str(a) for a in args], original=original, creationflags=kwargs.get("creationflags"),
                      stdin_devnull=kwargs.get("stdin") is subprocess.DEVNULL)
            if step in stubborn:
                self.terminate = lambda: log.write(event="terminate-ignored", step=step)
            if suspend and suspend[0] == step:
                threading.Timer(suspend[1], lambda pid=self.pid: (_suspend(pid), log.write(event="suspended",
                                                                                           step=step))).start()

    subprocess.Popen = Spy
    log.write(event="ready", pid=os.getpid(), in_job=bool(in_job.value), handler=repr(signal.getsignal(signal.SIGINT)))
    code: object = 0
    uncaught = None
    try:
        sys.argv = ["epub2tts-edge", *config["argv"]]
        edge.main()
    except SystemExit as exc:
        code = exc.code
    except KeyboardInterrupt:  # what Python does with one nobody catches, recorded first
        traceback.print_exc()
        uncaught, code = "KeyboardInterrupt", UNCAUGHT_CTRL_C
    except BaseException as exc:  # noqa: BLE001 - an uncaught failure, as Python would report it
        traceback.print_exc()
        uncaught, code = type(exc).__name__, 1
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a press after the run cannot interrupt this report
        subprocess.Popen = real_popen
        left = [pid for pid in media_children(os.getpid()) if sentinel is None or pid != sentinel.pid]
        sentinel_alive = sentinel is not None and sentinel.poll() is None
        if code is None:
            code = 0
        log.write(event="end", code=code if isinstance(code, int) else 1, message=None if isinstance(code, int) else code,
                  uncaught=uncaught, media_children_left=left, sentinel_alive=sentinel_alive)
        if sentinel is not None:
            sentinel.kill()
            sentinel.wait(10)
        faulthandler.cancel_dump_traceback_later()
    sys.stdout.flush()
    if not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    return code - 2 ** 32 if code > 0x7FFFFFFF else code  # an NTSTATUS such as 0xC000013A, as the signed int exit takes


if __name__ == "__main__":
    if sys.argv[1:2] == ["--ctrl-c"]:
        raise SystemExit(_ctrl_c_main(int(sys.argv[2])))
    raise SystemExit(child_main(sys.argv[1]))
