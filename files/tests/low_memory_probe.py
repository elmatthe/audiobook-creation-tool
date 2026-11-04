"""Real allocation pressure on real conversions, in a process of its own (v0.7.1, R2 remediation). Not a test: its callers are.

A Windows Job Object gives one child process a real per-process commit limit, so an allocation really fails, in that process
only, with no effect on the machine. The runner, the folder worker, the gate and FFmpeg are all real; only the network request
is replaced, by a copy of one deterministic real-format clip.

Two processes, because a hang is what is being tested and a hung process cannot report itself:

* :func:`supervise` (the parent, never limited) starts the child inside a kill-on-close job of its own, so that "this child's
  whole tree" is an exact list from the operating system and not a guess from process names. It waits a bounded time, then
  kills only that job. ``hung`` in its report means the child did not finish by itself.
* :func:`child_main` (the limited process) measures its own committed memory *after* everything is imported, limits itself to
  that plus the requested headroom, proves it can still start FFmpeg, and refuses to report anything if it cannot: a limit below
  what the process needs to start proves nothing about assembly (``invalid``).

Standard library at import time; the code under test is imported by the child, from the tree it is given.
"""

from __future__ import annotations

import contextlib
import ctypes as C
import faulthandler
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from ctypes import wintypes as WT
from pathlib import Path

MIB = 1024 ** 2
GIB = 1024 ** 3
SPEAKER = "en-US-AndrewNeural"
PROCESS_MEMORY_LIMIT = 0x100
JOB_MEMORY_LIMIT = 0x200
KILL_ON_JOB_CLOSE = 0x2000
EXTENDED_LIMIT_INFORMATION = 9
BASIC_PROCESS_ID_LIST = 3


class _Basic(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_longlong), ("PerJobUserTimeLimit", C.c_longlong), ("LimitFlags", WT.DWORD),
                ("MinimumWorkingSetSize", C.c_size_t), ("MaximumWorkingSetSize", C.c_size_t), ("ActiveProcessLimit", WT.DWORD),
                ("Affinity", C.c_size_t), ("PriorityClass", WT.DWORD), ("SchedulingClass", WT.DWORD)]


class _Io(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ("a", "b", "c", "d", "e", "f")]


class _Extended(C.Structure):
    _fields_ = [("Basic", _Basic), ("Io", _Io), ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]


class _Counters(C.Structure):
    _fields_ = [("cb", WT.DWORD), ("PageFaultCount", WT.DWORD), ("PeakWorkingSetSize", C.c_size_t),
                ("WorkingSetSize", C.c_size_t), ("QuotaPeakPagedPoolUsage", C.c_size_t), ("QuotaPagedPoolUsage", C.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", C.c_size_t), ("QuotaNonPagedPoolUsage", C.c_size_t),
                ("PagefileUsage", C.c_size_t), ("PeakPagefileUsage", C.c_size_t), ("PrivateUsage", C.c_size_t)]


def _kernel32():
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = WT.HANDLE
    kernel.CreateJobObjectW.argtypes = [C.c_void_p, C.c_wchar_p]
    kernel.GetCurrentProcess.restype = WT.HANDLE
    kernel.OpenProcess.restype = WT.HANDLE
    kernel.OpenProcess.argtypes = [WT.DWORD, WT.BOOL, WT.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [WT.HANDLE, WT.HANDLE]
    kernel.SetInformationJobObject.argtypes = [WT.HANDLE, C.c_int, C.c_void_p, WT.DWORD]
    kernel.QueryInformationJobObject.argtypes = [WT.HANDLE, C.c_int, C.c_void_p, WT.DWORD, C.c_void_p]
    kernel.TerminateJobObject.argtypes = [WT.HANDLE, WT.UINT]
    kernel.CloseHandle.argtypes = [WT.HANDLE]
    kernel.K32GetProcessMemoryInfo.argtypes = [WT.HANDLE, C.POINTER(_Counters), WT.DWORD]
    return kernel


def committed_bytes() -> int:
    """This process's private commit, from the operating system."""
    kernel = _kernel32()
    counters = _Counters()
    counters.cb = C.sizeof(counters)
    if not kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), C.byref(counters), C.sizeof(counters)):
        raise C.WinError(C.get_last_error())
    return int(counters.PrivateUsage)


def limit_this_process(limit_bytes: int, *, whole_job: bool = False) -> None:
    kernel = _kernel32()
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise C.WinError(C.get_last_error())
    info = _Extended()
    info.Basic.LimitFlags = JOB_MEMORY_LIMIT if whole_job else PROCESS_MEMORY_LIMIT
    if whole_job:
        info.JobMemoryLimit = limit_bytes
    else:
        info.ProcessMemoryLimit = limit_bytes
    if not kernel.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION, C.byref(info), C.sizeof(info)):
        raise C.WinError(C.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise C.WinError(C.get_last_error())
    # The handle stays open for the life of the process, which is what keeps the limit.


class OwnedTree:
    """A kill-on-close job holding one started child and everything it starts: exactly the processes this probe owns."""

    def __init__(self) -> None:
        self.kernel = _kernel32()
        self.job = self.kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise C.WinError(C.get_last_error())
        info = _Extended()
        info.Basic.LimitFlags = KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.job, EXTENDED_LIMIT_INFORMATION, C.byref(info), C.sizeof(info)):
            raise C.WinError(C.get_last_error())

    def adopt(self, process: subprocess.Popen) -> None:
        handle = self.kernel.OpenProcess(0x1F0FFF, False, process.pid)
        try:
            if not self.kernel.AssignProcessToJobObject(self.job, handle):
                raise C.WinError(C.get_last_error())
        finally:
            self.kernel.CloseHandle(handle)

    def alive(self) -> list[int]:
        class List(C.Structure):
            _fields_ = [("Assigned", WT.DWORD), ("Listed", WT.DWORD), ("Ids", C.c_size_t * 512)]

        listing = List()
        if not self.kernel.QueryInformationJobObject(self.job, BASIC_PROCESS_ID_LIST, C.byref(listing), C.sizeof(listing), None):
            raise C.WinError(C.get_last_error())
        return [int(listing.Ids[index]) for index in range(listing.Listed)]

    def kill(self) -> None:
        self.kernel.TerminateJobObject(self.job, 9)

    def close(self) -> None:
        self.kernel.CloseHandle(self.job)


# --------------------------------------------------------------------------- the parent


def supervise(scenario: dict, *, code_root, python: str, deadline_seconds: float, work_dir) -> dict:
    """Run one scenario in a child, for at most ``deadline_seconds``. Always returns; never leaves a process it started."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    scenario_file = work_dir / "scenario.json"
    report_file = work_dir / "report.json"
    stacks_file = work_dir / "stacks.txt"
    report_file.unlink(missing_ok=True)
    scenario_file.write_text(json.dumps(dict(scenario, report=str(report_file), stacks=str(stacks_file),
                                             work=str(work_dir), code=str(code_root),
                                             stacks_after=max(1.0, deadline_seconds - 3))), encoding="utf-8")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    tree = OwnedTree()
    started = time.monotonic()
    with open(work_dir / "child-output.txt", "wb") as output:
        process = subprocess.Popen([python, "-I", str(Path(__file__).resolve()), str(scenario_file)], stdout=output,
                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        tree.adopt(process)
        hung = False
        try:
            process.wait(timeout=deadline_seconds)
        except subprocess.TimeoutExpired:
            hung = True
    if hung:
        tree.kill()
        process.wait(timeout=30)
    # After a normal exit the job empties by itself, unless the child left something behind, which is a failure in its own right. A
    # venv's python.exe is a launcher for the real interpreter, and they go one after the other: a moment is allowed for that.
    settle = time.monotonic() + 5
    survivors = tree.alive()
    while survivors and time.monotonic() < settle:
        time.sleep(0.05)
        survivors = tree.alive()
    if survivors:
        tree.kill()
    tree.close()
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    report["child_output_tail"] = (work_dir / "child-output.txt").read_text(encoding="utf-8", errors="replace")[-4000:]
    report.update(hung=hung, supervised_seconds=round(time.monotonic() - started, 1), exit_code=process.returncode,
                  survivors=survivors, stacks=stacks_file.read_text(errors="replace")[:6000] if stacks_file.exists() else "")
    if not report_file.exists():
        report["child_output"] = (work_dir / "child-output.txt").read_text(errors="replace")[-1500:]
    return report


# --------------------------------------------------------------------------- the child


def _suspend_process(pid: int) -> None:
    """A real stall: the operating system stops the process, as a hung drive or scanner would."""
    kernel = _kernel32()
    handle = kernel.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if handle:
        C.WinDLL("ntdll").NtSuspendProcess(C.c_void_p(handle))
        kernel.CloseHandle(handle)


def _is_valid_mp3(path: Path, expected_seconds: float | None) -> dict:
    from mutagen.mp3 import MP3

    info = MP3(path).info
    return dict(length=round(info.length, 2), size=path.stat().st_size,
                length_ok=None if expected_seconds is None else abs(info.length - expected_seconds) < max(1.0, 0.02 * expected_seconds))


def child_main(scenario_path: str) -> int:
    scenario = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    faulthandler.dump_traceback_later(scenario["stacks_after"], exit=False, file=open(scenario["stacks"], "w"))
    code = Path(scenario["code"])
    sys.path.insert(0, str(code / "scripts"))
    work = Path(scenario["work"])
    scratch = work / "scratch"
    scratch.mkdir(exist_ok=True)
    tempfile.tempdir = str(scratch)
    report = dict(scenario=scenario["name"], route=scenario["route"], headroom_mb=scenario["headroom_mb"])

    def write_report():
        Path(scenario["report"]).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")

    from pydub import AudioSegment  # noqa: F401
    from shared import ffmpeg_utils
    from shared.cancellation import ConversionCancelled

    ffmpeg_utils.configure_pydub()
    from tts import batch_convert, publication, worker_limits as w
    from tts.epub2tts_edge import epub2tts_edge as engine, runner

    report["code_file"] = w.__file__
    clip = Path(scenario["clip"])
    requests = [0]
    request_lock = threading.Lock()

    def speak(_text, _voice, path):
        with request_lock:
            requests[0] += 1
        shutil.copyfile(clip, path)

    async def parallel(texts, voices, paths):
        for text, voice, path in zip(texts, voices, paths):
            speak(text, voice, path)

    async def chunk(text, path, voice, _rate):
        speak(text, voice, path)

    engine.run_edgespeak = speak
    engine.parallel_edgespeak = parallel
    batch_convert.chunk_to_mp3 = chunk
    batch_convert.INTER_CHUNK_DELAY_SEC = 0

    gate_mode = scenario.get("gate", "real")
    wait_seconds = scenario.get("gate_wait_seconds")
    roomy = w.MemoryInfo(64 * GIB, 64 * GIB)
    if gate_mode == "roomy":  # the gate is told everything fits, so the in-memory route really runs into the limit
        w.ASSEMBLY_GATE = w.AssemblyGate(memory_reader=lambda: roomy, wait_seconds=wait_seconds)
    elif gate_mode == "starved":  # the gate is told nothing is free at all
        w.ASSEMBLY_GATE = w.AssemblyGate(memory_reader=lambda: w.MemoryInfo(0, 8 * GIB), wait_seconds=wait_seconds)
    elif gate_mode == "one-fits":  # room for one narration of this size in memory, and the others wait for it
        w.ASSEMBLY_GATE = w.AssemblyGate(memory_reader=lambda: w.MemoryInfo(int(scenario.get("one_fits_gb", 2.8) * GIB), 8 * GIB), wait_seconds=wait_seconds)
    elif gate_mode == "real" and wait_seconds is not None:
        w.ASSEMBLY_GATE = w.AssemblyGate(wait_seconds=wait_seconds)
    if scenario.get("gate_min_pcm") is not None:
        w.ASSEMBLY_GATE_MIN_PCM_BYTES = scenario["gate_min_pcm"]
    gate = w.ASSEMBLY_GATE

    if scenario.get("unsupervised"):  # the negative control: pydub back on the raw subprocess module
        from tts import ffmpeg_watch

        ffmpeg_watch.uninstall()

    for name, value in scenario.get("constants", {}).items():
        module_name, _, attribute = name.rpartition(".")
        setattr(sys.modules[module_name], attribute, value)

    sources_dir = work / "sources"
    sources_dir.mkdir(exist_ok=True)
    out = work / "out"
    out.mkdir(exist_ok=True)
    jobs = []
    paragraphs = "\n\n".join(["Para one reads here."] * scenario["clips_per_file"]) + "\n"
    if scenario.get("chapters"):  # with a heading of their own, so that this is not yet the last chapter when it stalls
        paragraphs = "".join(f"# Chapter {n}\n\n{paragraphs}\n" for n in range(scenario["chapters"]))
    chunks = "\n\n".join(["Plain words that are read aloud here to fill a chunk of text properly. " * 45] * scenario["clips_per_file"]) + "\n"
    for index in range(scenario["files"]):
        route = scenario["route"]
        if route == "mixed":
            route = "direct" if index % 2 == 0 else "folder"
        source = sources_dir / f"Book{index}.txt"
        source.write_text(paragraphs if route == "direct" else chunks, encoding="utf-8")
        jobs.append((route, source, out / f"Book{index}-V.mp3"))

    cancelled = threading.Event()
    results: dict = {}
    lock = threading.Lock()

    def convert(job):
        route, source, destination = job
        started = time.monotonic()
        stdout = io.StringIO()
        status, message = None, None
        try:
            if route == "direct":
                # What the panel does: a private stage, then publication.
                with tempfile.TemporaryDirectory(prefix="tts_direct_", ignore_cleanup_errors=True) as stage:
                    produced = runner.run_conversion_job(str(source), output_dir=stage, speaker=SPEAKER, audio_format="mp3",
                                                         trim_tts_padding=False, cancel_check=cancelled.is_set)
                    publication.publish_file(produced, destination)
                status = "success"
            else:
                status, _path, message = batch_convert.convert_single_pdf(
                    source, out, SPEAKER, "+0%", log=print, cancel_check=cancelled.is_set,
                    out_mp3=destination, bitrate="192k")
        except ConversionCancelled as exc:
            status, message = "cancelled", f"{type(exc).__name__}: {exc}"
        except BaseException as exc:  # noqa: BLE001 - what the panel records
            status, message = "failed", f"{type(exc).__name__}: {exc}"
        with lock:
            results[source.name] = dict(route=route, status=status, message=(message or "").strip().splitlines()[0][:300] if message else "",
                                        seconds=round(time.monotonic() - started, 2))

    # Everything imported and warmed: only now is "what this process needs to start" a real number.
    import asyncio

    asyncio.run(asyncio.sleep(0))
    threading.Thread(target=lambda: None).start()
    startup = committed_bytes()
    headroom = scenario["headroom_mb"] * MIB
    report.update(startup_commit_mb=round(startup / MIB, 1))
    if headroom:
        if headroom < 16 * MIB:
            report["invalid"] = "a headroom below 16 MB cannot even run the interpreter's own work"
            write_report()
            return 3
        limit_this_process(startup + headroom, whole_job=bool(scenario.get("whole_job")))
        report["limit_mb"] = round((startup + headroom) / MIB, 1)
        try:
            proof = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-version"], capture_output=True, timeout=30)
            if proof.returncode != 0:
                raise RuntimeError(f"FFmpeg exit {proof.returncode}")
            asyncio.run(asyncio.sleep(0))
        except Exception as exc:  # noqa: BLE001
            report["invalid"] = f"this limit does not leave room to start FFmpeg or an event loop: {exc}"
            write_report()
            return 3
    report["memory_reading_under_limit"] = str(w.memory_info())

    # ---- what happens to the run, while it runs
    ffmpeg_seen: list = []
    real_popen = subprocess.Popen

    class Watched(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            ffmpeg_seen.append((self.pid, " ".join(map(str, args[0] if args else kwargs.get("args", [])))))

    subprocess.Popen = Watched
    stall = scenario.get("stall")  # "encode" or "decode": really suspend that FFmpeg when it starts
    if stall:
        def staller():
            seen = 0
            while True:
                for pid, command in list(ffmpeg_seen)[seen:]:
                    seen += 1
                    if stall == "final":  # the one MP3 encode: all that is left of a finished narration
                        wanted = "-f wav -i" in command and "-f mp3" in command
                    elif stall == "encode":
                        wanted = "-f wav -i" in command
                    else:
                        wanted = "-f wav -" in command and "pcm_s16le" in command
                    if wanted and "ffprobe" not in command.split(" ", 1)[0]:
                        time.sleep(scenario.get("stall_after", 0.05))
                        _suspend_process(pid)
                        report["stalled"] = dict(pid=pid, at=round(time.monotonic() - t0, 2))
                        return
                time.sleep(0.01)

        threading.Thread(target=staller, daemon=True).start()
    pressure = scenario.get("pressure")  # memory disappears after admission, and stays gone
    ballast: list = []
    if pressure == "after_admission":
        def press():
            while gate._in_memory == 0:
                time.sleep(0.002)
            report["pressure_started_with_in_memory"] = gate._in_memory
            keep = scenario.get("pressure_keep_mb", 0) * MIB
            with contextlib.suppress(MemoryError):
                while committed_bytes() + 4 * MIB + keep < startup + headroom:
                    ballast.append(bytearray(4 * MIB))
            report["ballast_mb"] = 4 * len(ballast)

        threading.Thread(target=press, daemon=True).start()
    samples = []

    def gate_sampler():
        while not finished.is_set():
            samples.append((gate._in_use, gate._in_memory, len(gate._queue)))
            finished.wait(0.05)

    finished = threading.Event()
    threading.Thread(target=gate_sampler, daemon=True).start()
    cancel_after = scenario.get("cancel_after")
    cancel_when = scenario.get("cancel_when")  # "stalled": as soon as the stall has happened
    t0 = time.monotonic()
    threads = [threading.Thread(target=convert, args=(job,), name=f"file-{index}", daemon=True) for index, job in enumerate(jobs)]
    if scenario.get("workers") and scenario["workers"] < len(threads):
        report["note"] = "one thread per file; workers is the file count here"
    for thread in threads:
        thread.start()

    def canceller():
        if cancel_when == "stalled":
            while "stalled" not in report:
                time.sleep(0.01)
            time.sleep(scenario.get("cancel_delay", 0.2))
        elif cancel_when == "waiting":  # as soon as a file is really waiting behind one assembling in memory
            while not (gate._in_memory and gate._queue) and any(thread.is_alive() for thread in threads):
                time.sleep(0.001)
            report["cancelled_with_waiting"] = dict(in_memory=gate._in_memory, queued=len(gate._queue))
        elif cancel_after is not None:
            time.sleep(cancel_after)
        else:
            return
        report["cancel_at"] = round(time.monotonic() - t0, 2)
        cancelled.set()

    threading.Thread(target=canceller, daemon=True).start()
    for thread in threads:
        thread.join()
    report["run_seconds"] = round(time.monotonic() - t0, 2)
    finished.set()
    if "cancel_at" in report:
        report["cancel_to_end_seconds"] = round(report["run_seconds"] - report["cancel_at"], 2)
    del ballast[:]
    subprocess.Popen = real_popen

    expected = scenario.get("expected_seconds")
    published = {}
    for _route, _source, destination in jobs:
        if destination.exists():
            published[destination.name] = _is_valid_mp3(destination, expected)
            published[destination.name]["sha256"] = _sha256(destination)
    report.update(
        results=results, requests=requests[0], published=published,
        peak_gate=dict(in_use_mb=max((s[0] for s in samples), default=0) // MIB, in_memory=max((s[1] for s in samples), default=0),
                       queued=max((s[2] for s in samples), default=0)),
        gate_after=dict(in_use=gate._in_use, in_memory=gate._in_memory, queued=len(gate._queue)),
        ffmpeg_started=len(ffmpeg_seen),
        leftovers=sorted(str(path.relative_to(work)) for folder in (out, scratch) for path in folder.rglob("*")
                         if path.is_file() and path.name not in published),
    )
    write_report()
    return 0


def _sha256(path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    try:
        code = child_main(sys.argv[1])
    except BaseException:  # noqa: BLE001 - it must say what happened, in the only place the parent can read
        traceback.print_exc()
        code = 4
    sys.stdout.flush()
    os._exit(code)  # a daemon thread stuck on a real hang must not keep this process alive past its report


if __name__ == "__main__":
    raise SystemExit(main())
