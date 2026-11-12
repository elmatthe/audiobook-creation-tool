"""One contained run of the REAL TTS panel for a qualification scenario (a child of edge_low_memory.py / optional_engines.py).

The panel, its importer, its worker pool, its engines, its assembly, its encoder and its publication are production's. This file
only chooses what a person would choose (files, voice, workers, when to press Pause or Cancel), watches from the side, and
measures what was published. Settings, logs, TEMP and the output base are this run's own folders, proved before Start; both ways
of opening the file manager are recorded instead of performed.

    python panel_run.py --out <folder> --case <json file>

The case file says what to do; ``result.json`` says what happened. Nothing here decides PASS: the scenario's runner does.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

T0 = time.perf_counter()


def now() -> float:
    return round(time.perf_counter() - T0, 3)


# --------------------------------------------------------------------------- process tree and GPU, sampled from the side
class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


class _ENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class Sampler(threading.Thread):
    """This process and everything below it: private bytes and working set, which images ran, and the GPU's memory."""

    def __init__(self, gpu: bool) -> None:
        super().__init__(daemon=True, name="qualification-sampler")
        self.stop = threading.Event()
        self.gpu = gpu
        self.peak_private = self.peak_working_set = 0
        self.images: dict[str, int] = {}
        self.gpu_samples: list[int] = []
        self.gpu_ours: int = 0
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.restype = wt.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_ENTRY)]
        k.OpenProcess.restype = wt.HANDLE
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
        self.k = k

    def tree(self) -> dict[int, str]:
        snapshot = self.k.CreateToolhelp32Snapshot(2, 0)
        parents: dict[int, tuple[int, str]] = {}
        entry = _ENTRY()
        entry.dwSize = ctypes.sizeof(_ENTRY)
        more = self.k.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            more = self.k.Process32NextW(snapshot, ctypes.byref(entry))
        self.k.CloseHandle(snapshot)
        mine = {os.getpid(): "python.exe (this run)"}
        grew = True
        while grew:
            grew = False
            for pid, (parent, image) in parents.items():
                if parent in mine and pid not in mine:
                    mine[pid] = image
                    grew = True
        return mine

    def run(self) -> None:
        turn = 0
        while not self.stop.wait(0.5):
            private = working = 0
            pids = self.tree()
            for pid, image in pids.items():
                handle = self.k.OpenProcess(0x1010, False, pid)
                if not handle:
                    continue
                counters = _PMC()
                counters.cb = ctypes.sizeof(_PMC)
                if self.k.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    private += counters.PrivateUsage
                    working += counters.WorkingSetSize
                self.k.CloseHandle(handle)
                if pid != os.getpid():
                    self.images[image.lower()] = self.images.get(image.lower(), 0) + 1
            self.peak_private, self.peak_working_set = max(self.peak_private, private), max(self.peak_working_set, working)
            turn += 1
            if self.gpu and turn % 2 == 0:
                try:
                    used = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                          capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout.split()
                    self.gpu_samples.append(int(used[0]))
                    apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                                          capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout
                    ours = sum(int(line.split(",")[1]) for line in apps.splitlines()
                               if line.strip() and line.split(",")[1].strip().isdigit() and int(line.split(",")[0]) in pids)
                    self.gpu_ours = max(self.gpu_ours, ours)
                except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                    pass

    def report(self) -> dict:
        return {"peak_private_mb": round(self.peak_private / 2**20), "peak_working_set_mb": round(self.peak_working_set / 2**20),
                "child_images_seen": sorted(self.images), "gpu_used_mb_min": min(self.gpu_samples, default=None),
                "gpu_used_mb_max": max(self.gpu_samples, default=None), "gpu_mb_attributed_to_this_tree": self.gpu_ours}


# --------------------------------------------------------------------------- what was published, read back independently
def inspect_audio(path: Path, ffmpeg: str, ffprobe: str) -> dict:
    import numpy as np

    facts: dict = {"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
                            "-of", "json", str(path)], capture_output=True, creationflags=0x08000000)
    facts["probe"] = json.loads(probe.stdout or b"{}")
    raw = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "24000",
                          "-f", "s16le", "-"], capture_output=True, creationflags=0x08000000)
    facts["decode_errors"] = raw.stderr.decode("utf-8", "replace").strip()[:300]
    facts["decode_exit"] = raw.returncode
    pcm = np.frombuffer(raw.stdout, dtype="<i2").astype(np.float64) / 32768.0
    rate = 24000
    facts["decoded_seconds"] = round(pcm.size / rate, 3)
    if pcm.size:
        window = rate // 50  # 20 ms
        frames = pcm[: pcm.size // window * window].reshape(-1, window)
        level = np.sqrt((frames ** 2).mean(axis=1))
        loud = np.nonzero(level > 10 ** (-45 / 20))[0]  # louder than -45 dBFS: speech, not the noise floor
        facts.update(peak_dbfs=round(float(20 * np.log10(max(1e-9, np.abs(pcm).max()))), 1),
                     rms_dbfs=round(float(20 * np.log10(max(1e-9, np.sqrt((pcm ** 2).mean())))), 1),
                     voiced_fraction=round(float(loud.size / max(1, level.size)), 3),
                     leading_silence_s=round(float(loud[0] * 0.02), 2) if loud.size else None,
                     trailing_silence_s=round(float((level.size - 1 - loud[-1]) * 0.02), 2) if loud.size else None,
                     # The very last 20 ms: a narration cut off mid-word ends loud; one that ended ends quiet.
                     last_frame_dbfs=round(float(20 * np.log10(max(1e-9, level[-1]))), 1),
                     longest_inner_silence_s=_longest_gap(loud))
    return facts


def _longest_gap(loud) -> float:
    import numpy as np

    if loud.size < 2:
        return 0.0
    return round(float(np.diff(loud).max() * 0.02), 2)


# --------------------------------------------------------------------------- the run
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    attempts: list = []
    if not case.get("online"):
        common.no_network(attempts)
    containment = common.contain_application(out)

    from shared import ffmpeg_utils
    from shared import subprocess_utils as sp

    sp.install_no_window_guard()
    import tkinter as tk

    from shared import job_control as jc  # noqa: F401
    from tts import batch_convert
    from tts import epub2tts_gui as gui
    from tts import worker_limits
    from tts.epub2tts_edge import epub2tts_edge as engine

    ffmpeg, ffprobe = ffmpeg_utils.ffmpeg_cmd(), ffmpeg_utils.ffprobe_cmd()
    lock = threading.Lock()
    files: list[dict] = []
    requests: list[dict] = []
    current = threading.local()

    def wrap_file(kind, real, source_of):
        def wrapper(*a, **k):
            record = {"source": Path(str(source_of(*a, **k))).name, "kind": kind, "start": now()}
            with lock:
                files.append(record)
            current.source = record["source"]
            try:
                result = real(*a, **k)
                record["outcome"] = result[0] if isinstance(result, tuple) else "returned"
                return result
            except BaseException as exc:
                record["outcome"] = f"raised {type(exc).__name__}"
                raise
            finally:
                record["end"] = now()
        return wrapper

    def wrap_request(kind, real, text_of, path_of):
        def wrapper(*a, **k):
            record = {"kind": kind, "source": getattr(current, "source", None), "chars": len(str(text_of(*a, **k))), "start": now()}
            with lock:
                requests.append(record)
            try:
                result = real(*a, **k)
                target = Path(str(path_of(*a, **k)))
                record.update(ok=True, bytes=target.stat().st_size if target.exists() else None)
                return result
            except BaseException as exc:
                record.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
                raise
            finally:
                record["end"] = now()
        return wrapper

    assemblies: list[dict] = []
    if case.get("observe_edge"):
        real_assemble = worker_limits.assemble

        def assemble(*a, **k):
            record = {"source": getattr(current, "source", None), "start": now()}
            with lock:
                assemblies.append(record)
            try:
                result = real_assemble(*a, **k)
                record["outcome"] = "returned"
                return result
            except BaseException as exc:
                record["outcome"] = f"raised {type(exc).__name__}"
                raise
            finally:
                record["end"] = now()

        worker_limits.assemble = assemble
        gui.convert_with_edge_engine = wrap_file("direct", gui.convert_with_edge_engine, lambda item, *a, **k: item["source"])
        batch_convert.convert_single_pdf = wrap_file("folder", batch_convert.convert_single_pdf, lambda path, *a, **k: path)
        engine.run_edgespeak = wrap_request("direct", engine.run_edgespeak, lambda s, v, f: s, lambda s, v, f: f)
        batch_convert.synthesize_chunk_mp3 = wrap_request("folder", batch_convert.synthesize_chunk_mp3,
                                                          lambda t, p, v, r: t, lambda t, p, v, r: p)

    messages: list = []
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(gui.messagebox, name, lambda title, message=None, _n=name, **k: messages.append([_n, str(title), str(message)[:300]]))
    gui.messagebox.askyesno = lambda *a, **k: messages.append(["askyesno", str(a[:1]), ""]) or True

    def no_install(panel, component, reason):
        messages.append(["install-dialog", str(component), str(reason)[:200]])
        return {"state": "skipped"}

    direct = [str(Path(p)) for p in case.get("direct", [])]
    folders = [str(Path(p)) for p in case.get("folders", [])]
    hashes_before = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in direct}
    for folder in folders:
        hashes_before.update({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).rglob("*")) if p.is_file()})

    root = tk.Tk()
    root.title(f"ACT qualification: {case['label']}")
    root.geometry("1000x760")
    panel = gui.TtsPanel(root, choose_files=lambda: tuple(direct), choose_folder=lambda: tuple(folders), install_dialog=no_install)
    panel.pack(fill="both", expand=True)

    def pump(done, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            if done():
                return True
            time.sleep(0.02)
        return False

    wanted = len(hashes_before)
    if direct:
        panel.importer.add_files()
    if folders:
        panel.importer.add_folder()
    imported = pump(lambda: len(panel.manager.snapshot().files) >= wanted, 120)
    panel.selected_voice_label.set(case["voice"])
    panel._on_voice_selected()
    panel.workers_var.set(str(case.get("workers", 1)))
    root.update()

    limit_note = None
    if case.get("job_memory_headroom_mb"):
        limit_note = _limit_own_memory(int(case["job_memory_headroom_mb"]))
    sampler = Sampler(gpu=bool(case.get("gpu")))
    sampler.start()
    output_base = Path(containment["output_base"])
    actions: list[dict] = []
    started = now()
    panel.run_job()
    plan = case.get("action") or {}
    state = {"done": False}

    def published() -> list[str]:
        return sorted(str(p.relative_to(output_base)) for p in output_base.rglob("*.mp3"))

    def settled() -> bool:
        if plan and not state["done"]:
            trigger = plan["when"]
            with lock:
                finished_requests = sum(1 for r in requests if "end" in r and r.get("ok"))
                finished_files = sum(1 for f in files if "end" in f)
            if ((trigger.get("after_requests") is not None and finished_requests >= trigger["after_requests"])
                    or (trigger.get("after_assemblies") is not None and len(assemblies) >= trigger["after_assemblies"])
                    or (trigger.get("after_files") is not None and finished_files >= trigger["after_files"])
                    or (trigger.get("after_seconds") is not None and now() - started >= trigger["after_seconds"])):
                state["done"] = True
                record = {"action": plan["do"], "at": now(), "published_at_action": published(),
                          "requests_started_before": len(requests), "files_started_before": len(files)}
                actions.append(record)
                if plan["do"] == "cancel":
                    panel.cancel_job()
                elif plan["do"] == "pause":
                    panel.pause()
                    state["paused_at"] = time.monotonic()
        if plan.get("do") == "pause" and state.get("paused_at") and not state.get("cancelled_after_pause"):
            # Pause lets the files in flight finish and starts nothing new; once it has gone quiet the paused run is cancelled.
            with lock:
                in_flight = sum(1 for f in files if "end" not in f)
            if in_flight == 0 and time.monotonic() - state["paused_at"] >= plan.get("hold_seconds", 6):
                state["cancelled_after_pause"] = True
                actions.append({"action": "cancel-while-paused", "at": now(), "published_at_action": published(),
                                "requests_started_before": len(requests), "files_started_before": len(files)})
                panel.cancel_job()
        return panel._result is not None and not panel._busy.is_set()

    finished = pump(settled, float(case.get("timeout", 1800)))
    ended = now()
    published_at_settle = published()
    pump(lambda: False, 2.0)   # anything late would land here: a publication or a request after the run said it had ended
    sampler.stop.set()
    sampler.join(5)
    result = panel._result
    outputs = [inspect_audio(output_base / name, ffmpeg, ffprobe) for name in published()]
    leftovers = sorted(str(p.relative_to(output_base)) for p in output_base.rglob("*") if p.is_file() and p.suffix.lower() != ".mp3")
    details = list(panel.log.details)
    record = {
        "label": case["label"], "voice": case["voice"], "requested_workers": case.get("workers", 1), "imported": imported,
        "wanted_files": wanted, "finished": finished, "run_seconds": round(ended - started, 2), "containment": containment,
        "state": None if result is None else result.state.name,
        "succeeded": None if result is None else getattr(result, "succeeded_count", None),
        "failed": None if result is None else getattr(result, "failed_count", None),
        "cancelled": None if result is None else bool(getattr(result, "cancelled", False)),
        "worker_lines": [line for line in details if "worker" in line.lower()][:12],
        "chunk_lines": [line for line in details if "chunk" in line.lower() or "segment" in line.lower()][:60],
        "files": files, "requests": requests, "assemblies": assemblies, "actions": actions, "outputs": outputs,
        "leftovers_in_output": leftovers, "settled_at": ended, "published_at_settle": published_at_settle,
        "published_at_end": published(), "messages": messages, "network_attempts": attempts,
        # Files, and folders below the application's own empty root: the root itself (act-tts) is kept by design.
        "temp_left": sorted(str(p.relative_to(out / "tmp")) for p in (out / "tmp").rglob("*")
                            if p.is_file() or len(p.relative_to(out / "tmp").parts) > 1)[:40],
        "memory_lines": [line for line in details if "memory" in line.lower()][:20],
        "sources_unchanged": all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in hashes_before.items()),
        "assembly_reservation_after": getattr(worker_limits.ASSEMBLY_GATE, "_in_use", None), "memory_limit": limit_note,
        "sampler": sampler.report(), "summary_tail": list(panel.log.summary)[-8:], "details_tail": details[-25:],
        "failure_messages": [str(getattr(item, "message", item))[:300] for item in getattr(getattr(result, "failures", None), "records", [])][:8],
        "identity": _identity(case),
    }
    (out / "result.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    panel.close()
    root.destroy()
    return 0 if finished else 1


def _limit_own_memory(headroom_mb: int) -> dict:
    """A real per-process commit limit on this run alone: a Job Object, expressed as headroom above what is committed now
    (an absolute limit below the start-up commit is refused by Windows rather than applied)."""
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wt.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class IOC(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("a", "b", "c", "d", "e", "f")]

    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wt.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.GetCurrentProcess.restype = wt.HANDLE
    k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    k.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
    counters = _PMC()
    counters.cb = ctypes.sizeof(_PMC)
    k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    base_mb = counters.PrivateUsage // 2**20
    job = k.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.ProcessMemoryLimit = (base_mb + headroom_mb) * 2**20
    applied = bool(k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                   and k.AssignProcessToJobObject(job, k.GetCurrentProcess()))
    return {"base_private_mb": int(base_mb), "headroom_mb": headroom_mb, "limit_mb": int(base_mb + headroom_mb), "applied": applied,
            "error": None if applied else ctypes.get_last_error()}


def _identity(case: dict) -> dict:
    facts: dict = {"python": sys.version.split()[0]}
    if case.get("gpu"):
        try:
            import torch

            facts.update(torch=torch.__version__, cuda_available=bool(torch.cuda.is_available()),
                         cuda_device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal to the record
            facts["torch_error"] = f"{type(exc).__name__}: {exc}"[:200]
        from importlib import metadata

        for package in ("kokoro", "chatterbox-tts", "numpy", "transformers"):
            try:
                facts[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                facts[package] = None
    return facts


if __name__ == "__main__":
    raise SystemExit(main())
