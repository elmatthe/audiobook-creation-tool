"""One headless run of the real M4B Converter panel, contained and measured (m4b-scaling qualification, v0.7.2 Phase 7B).

Promoted from Phase 7A's evidence harness. One process per measurement:

* **Containment first, before any media process starts.** The run folder must be new and inside ``--root``. Settings,
  logs and TEMP are redirected into it; the output base is set the way a person sets it, through the application's own
  preference in the redirected settings file, then read back from the live configuration the panel captures at Start
  and resolved by the application's own resolver. Any answer outside the run folder stops the run with exit 3 before
  anything is converted, and every reservation is checked again as it happens. (A Phase 7A smoke run once wrote into the
  owner's Downloads because the panel reads the base from settings, not from the environment.)
* A new Windows Job Object (KILL_ON_JOB_CLOSE) holds this process, so every child is counted and none can outlive it.
* The real ``M4BConverterUI`` on a withdrawn Tk root: sources added through its importer, options set on its variables,
  Start pressed, so the production worker, plan, routes, commands, validation and publication all run unchanged.
  ``--route`` only moves the minimum saving (legacy: never continuous; continuous: whenever otherwise eligible; auto:
  the frozen production value). Nothing else in the application is changed; the wrappers below only time and record.
* Measured: per output wall time and passes, each child's CPU and peak memory, the job's processes, CPU, I/O and peak
  commit, staged temporary bytes (sampled), the UI heartbeat (Tk loop lateness every 50 ms), the continuous decoder's
  peak buffered audio, time the feed spent waiting on the decoder and on the encoder, and the route each book took.
* **Stall diagnostics:** a watchdog thread notices when the Tk loop is more than a second late and records, once per
  stall, every thread's stack, this process's CPU time, the machine's load and the live children, so a pause can be
  attributed (decoder pipe, encoder, supervision, thread synchronisation, scheduling, or the machine) instead of guessed.
* Fault injection: Cancel after N finished outputs or N seconds into the K-th audio pass; kill the K-th encoder or the
  continuous decoder at the K-th chapter, then Retry Failed; Pause after N outputs and Resume after S seconds.

Writes ``results.json`` into ``--out``. Exit 0 when the run completed as asked (whatever the run's own state), 3 when
containment refused it, 4 when the harness itself failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import winjob  # noqa: E402

EXIT_CONTAINMENT = 3
EXIT_HARNESS = 4


class Refused(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(EXIT_CONTAINMENT)
        self.message = message


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(argv) -> str:
    argv = [str(part) for part in argv]
    if "pipe:1" in argv:
        return "decoder"
    if "pipe:0" in argv:
        return "pcm"
    if "-ss" in argv:
        return "segment"
    if "-show_entries" in argv:
        return "scan"
    if argv.count("-i") == 2 and "copy" in argv and "-map_chapters" in argv and "-c" in argv:
        return "attach"
    if Path(argv[0]).stem.lower().startswith("ffprobe"):
        return "probe"
    return "whole"


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, type=Path, help="the scripts folder of the code under test")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--root", required=True, type=Path, help="the qualification run's own folder; --out must be inside")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--mode", choices=("split", "whole"), default="split")
    parser.add_argument("--metadata", choices=("preserve", "replace", "strip"), default="preserve")
    parser.add_argument("--quality", type=int, default=2)
    parser.add_argument("--route", choices=("auto", "legacy", "continuous"), default="auto")
    parser.add_argument("--label", default="")
    parser.add_argument("--cancel-after", type=int, default=0, help="press Cancel after this many finished outputs")
    parser.add_argument("--cancel-in-pass", type=int, default=0, help="press Cancel while the K-th audio pass runs")
    parser.add_argument("--cancel-delay", type=float, default=0.5)
    parser.add_argument("--kill", choices=("", "encoder", "decoder"), default="")
    parser.add_argument("--kill-at", type=int, default=0, help="the K-th audio pass (encoder) or chapter (decoder)")
    parser.add_argument("--kill-delay", type=float, default=0.3)
    parser.add_argument("--pause-after", type=int, default=0)
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--hash-outputs", action="store_true")
    return parser.parse_args(argv)


def instrument_continuous(m4b_continuous, decisions, decoders, current, args, killed) -> None:
    """Timers and records around the continuous route; the decoder kill when asked. Behaviour is unchanged."""
    real_qualify = m4b_continuous.qualify

    def qualify(source, report, **k):
        t0 = time.perf_counter()
        decision = real_qualify(source, report, **k)
        decisions.append({"source": Path(source).name, "continuous": decision.continuous, "reason": decision.reason,
                          "scan_s": decision.scan_seconds, "wall_s": time.perf_counter() - t0})
        return decision

    m4b_continuous.qualify = qualify

    Decoder = m4b_continuous.ContinuousDecoder
    real_read, real_feed, real_close = Decoder._read, Decoder.feed, Decoder.close
    feed_calls = {"n": 0}

    def timed_read(self, size):
        t0 = time.perf_counter()
        try:
            return real_read(self, size)
        finally:
            spent = time.perf_counter() - t0
            seg = current["seg"]
            if seg is not None:
                seg["decoder_wait_s"] = seg.get("decoder_wait_s", 0.0) + spent

    def timed_feed(self, write, first, count, *, last):
        feed_calls["n"] += 1
        if args.kill == "decoder" and feed_calls["n"] == args.kill_at and not killed:
            self._proc.kill()
            self._proc.wait(30)
            killed.append({"pid": self._proc.pid, "what": "decoder", "at": time.perf_counter()})

        def timed_write(data):
            t0 = time.perf_counter()
            try:
                write(data)
            finally:
                seg = current["seg"]
                if seg is not None:
                    seg["encoder_wait_s"] = seg.get("encoder_wait_s", 0.0) + time.perf_counter() - t0

        return real_feed(self, timed_write, first, count, last=last)

    def recorded_close(self):
        reaped = real_close(self)
        if not getattr(self, "_bench_recorded", False) and self._proc is not None:
            self._bench_recorded = True
            decoders.append({"source": self._source.name, "peak_buffered": self.peak_buffered,
                             "position": self.position, "total": self.route.total_samples,
                             "returncode": self.returncode, "reaped": reaped,
                             **winjob.process_facts(int(self._proc._handle))})
        return reaped

    Decoder._read, Decoder.feed, Decoder.close = timed_read, timed_feed, recorded_close


def main(argv=None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    out = args.out.resolve()
    if not root.is_dir():
        raise Refused(f"the qualification folder {root} does not exist")
    if not inside(out, root) or out == root:
        raise Refused(f"{out} is not inside the qualification folder {root}")
    out.mkdir(parents=True, exist_ok=False)
    job = winjob.Job()
    job_at_start = job.snapshot()

    # ------------------------------------------------------------------ containment, before any application import
    temp = out / "tmp"
    temp.mkdir()
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(temp)
    import tempfile  # noqa: E402,PLC0415
    tempfile.tempdir = str(temp)
    code = args.code.resolve()
    sys.path.insert(0, str(code))
    from shared import paths  # noqa: E402  (first application import: redirect before anything reads it)
    runtime = out / "runtime-data"
    runtime.mkdir()
    paths.RESOURCES_DIR = runtime
    paths.LOGS_DIR = runtime / "logs"
    paths.SETTINGS_FILE = runtime / "settings.json"
    from shared import ffmpeg_utils  # noqa: E402
    ffmpeg = str(Path(args.ffmpeg).resolve())
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe"))
    ffmpeg_utils._executable_pair = lambda: (ffmpeg, ffprobe)
    ffmpeg_utils.ffmpeg_path.cache_clear()
    ffmpeg_utils.ffprobe_path.cache_clear()

    import tkinter as tk  # noqa: E402
    from shared import config as shared_config  # noqa: E402
    from shared import output_paths  # noqa: E402
    from shared import subprocess_utils as sp  # noqa: E402
    from m4b import m4b_execution, m4b_probe  # noqa: E402
    try:
        from m4b import m4b_continuous  # noqa: E402
    except ImportError:  # the v0.7.1 reference tree (204c33b) has only the seeking route
        m4b_continuous = None
    from m4b.converter import m4b_converter  # noqa: E402
    from m4b.converter.m4b_metadata import MetadataMode  # noqa: E402
    from m4b.converter.m4b_plan import ConversionMode  # noqa: E402

    output_base = out / "output-base"
    output_base.mkdir()
    if Path(paths.SETTINGS_FILE).resolve() != (runtime / "settings.json").resolve():
        raise Refused(f"settings file {paths.SETTINGS_FILE} is not this run's")
    shared_config.set_output_base(str(output_base))
    effective = shared_config.get_effective()
    resolved = Path(output_paths.resolve_output_base(effective)).resolve()
    if resolved != output_base.resolve() or not inside(resolved, out):
        raise Refused(f"the application would write to {resolved}, not this run's {output_base}")
    containment = {"settings_file": str(paths.SETTINGS_FILE), "output_base": str(resolved), "temp": str(temp),
                   "checked_before_start": True}
    real_reserve = output_paths.reserve_run_directory
    refused: list[str] = []

    def reserve_run_directory(tool_key, *a, **k):
        base = Path(output_paths.resolve_output_base(k.get("effective"))).resolve()
        if base != output_base.resolve():
            refused.append(str(base))
            raise RuntimeError(f"reservation outside the run folder refused: {base}")
        return real_reserve(tool_key, *a, **k)

    output_paths.reserve_run_directory = reserve_run_directory
    if m4b_continuous is None and args.route != "legacy":
        raise SystemExit("this code tree has only the seeking route: use --route legacy")
    production_threshold = None if m4b_continuous is None else m4b_continuous.MIN_SAVED_PREFIX_SECONDS
    threshold = {"auto": production_threshold, "legacy": float("inf"), "continuous": float("-inf")}[args.route]
    if m4b_continuous is not None:
        m4b_continuous.MIN_SAVED_PREFIX_SECONDS = threshold

    # ------------------------------------------------------------------ instruments (timers only)
    segments: list[dict] = []
    probes: list[dict] = []
    decisions: list[dict] = []
    decoders: list[dict] = []
    current: dict = {"seg": None, "attempt": 0}
    children: list = []           # (kind, proc, started) of every child this run started
    audio_passes = {"n": 0}
    killed: list[dict] = []
    wants: dict = {"cancel_at": None}
    lock = threading.Lock()
    real_popen = sp.popen

    def popen(cmd, **kwargs):
        proc = real_popen(cmd, **kwargs)
        kind = classify(cmd)
        with lock:
            children.append((kind, proc, time.perf_counter()))
        if kind in ("segment", "pcm", "whole"):
            audio_passes["n"] += 1
            if args.kill == "encoder" and audio_passes["n"] == args.kill_at:
                def kill_later(target=proc):
                    time.sleep(args.kill_delay)
                    if target.poll() is None:
                        target.kill()
                        killed.append({"pid": target.pid, "what": "encoder", "at": time.perf_counter()})
                threading.Thread(target=kill_later, daemon=True).start()
            if args.cancel_in_pass and audio_passes["n"] == args.cancel_in_pass:
                wants["cancel_at"] = time.perf_counter() + args.cancel_delay
        return proc

    sp.popen = popen

    real_probe = m4b_probe.probe_source

    def probe_source(path, *a, **k):
        t0 = time.perf_counter()
        try:
            return real_probe(path, *a, **k)
        finally:
            probes.append({"source": Path(path).name, "wall_s": time.perf_counter() - t0})

    m4b_probe.probe_source = probe_source
    if m4b_continuous is not None:
        instrument_continuous(m4b_continuous, decisions, decoders, current, args, killed)
    real_run_argv, real_streaming = m4b_execution.run_argv, m4b_execution.run_argv_streaming


    def record_pass(argv, result, t0):
        record = {"kind": classify(argv), "wall_s": time.perf_counter() - t0, "rc": result.returncode,
                  "cancelled": result.cancelled, "producer_failed": getattr(result, "producer_failed", False)}
        with lock:
            match = next((proc for kind, proc, _t in reversed(children) if kind == record["kind"]), None)
        if match is not None:
            record.update(winjob.process_facts(int(match._handle)))
        if current["seg"] is not None:
            current["seg"]["passes"].append(record)

    def run_argv(argv, **k):
        t0 = time.perf_counter()
        result = real_run_argv(argv, **k)
        record_pass(argv, result, t0)
        return result

    def run_argv_streaming(argv, **k):
        t0 = time.perf_counter()
        result = real_streaming(argv, **k)
        record_pass(argv, result, t0)
        return result

    m4b_execution.run_argv, m4b_execution.run_argv_streaming = run_argv, run_argv_streaming
    real_measure = m4b_converter.measured_duration

    def measured_duration(path):
        t0 = time.perf_counter()
        try:
            return real_measure(path)
        finally:
            if current["seg"] is not None:
                current["seg"]["measure_s"] = time.perf_counter() - t0

    m4b_converter.measured_duration = measured_duration
    real_convert = m4b_execution.convert_segment

    def convert_segment(work, **k):
        record = {"attempt": current["attempt"], "index": len(segments), "dest": work.destination.name,
                  "start": work.span[0] if work.span else 0.0, "end": work.span[1] if work.span else None,
                  "expected": work.expected_duration, "continuous": getattr(work, "continuous_decode", False), "passes": [],
                  "measure_s": None, "t_begin": time.perf_counter()}
        current["seg"] = record
        try:
            outcome = real_convert(work, **k)
        finally:
            record["wall_s"] = time.perf_counter() - record["t_begin"]
            current["seg"] = None
            segments.append(record)
        record.update(finalised=outcome.finalised, cancelled=outcome.cancelled, message=outcome.message,
                      measured=outcome.measured)
        return outcome

    m4b_execution.convert_segment = convert_segment

    # ------------------------------------------------------------------ the panel
    tk_root = tk.Tk()
    tk_root.withdraw()
    sources = tuple(str(s.resolve()) for s in args.source)
    source_hashes_before = {s: sha256(Path(s)) for s in sources}
    panel = m4b_converter.M4BConverterUI(
        tk_root, effective_config=effective, choose_files=lambda: sources,
        confirm_large_result=lambda outcome: True, confirm_broad_root=lambda roots: False)
    panel.pack(fill="both", expand=True)
    transcript: list[str] = []
    real_log_write = panel.log_write

    def log_write(text, *, summary=False):
        transcript.append(text)
        return real_log_write(text, summary=summary)

    panel.log_write = log_write
    panel.importer.add_files()
    imported = [str(p) for p in panel.imported_files()]
    if imported != list(sources):
        raise SystemExit(f"import changed the sources: {imported}")
    panel.var_mode.set(ConversionMode.SPLIT.value if args.mode == "split" else ConversionMode.WHOLE.value)
    panel.var_metadata_mode.set(MetadataMode(args.metadata).value)
    panel.var_quality.set(args.quality)
    tk_root.update()
    if Path(output_paths.resolve_output_base(shared_config.get_effective())).resolve() != output_base.resolve():
        raise Refused("the output base changed before Start")

    heartbeat: list[float] = []
    stalls: list[dict] = []
    stall_dumps: list[dict] = []
    disk = {"peak_staged": 0, "samples": 0}
    state = {"phase": "first", "t_start": None, "t_settled": None, "t_cancel": None, "cancel_settled": None,
             "retry_start": None, "retry_settled": None, "timed_out": False, "results": [], "paused_at": None,
             "resumed_at": None, "alive_at_settle": None}
    stop = threading.Event()
    last_tick = {"t": time.perf_counter()}

    def sample_disk():
        while not stop.is_set():
            staged = 0
            for folder, _subs, names in os.walk(output_base):
                for name in names:
                    if name.startswith(".act-tmp-"):
                        try:
                            staged += os.path.getsize(os.path.join(folder, name))
                        except OSError:
                            pass
            disk["peak_staged"] = max(disk["peak_staged"], staged)
            disk["samples"] += 1
            stop.wait(0.5)

    def watchdog():
        """Record the whole process's state once per stall of the Tk loop longer than a second."""
        dumped_for = None
        load_mark = winjob.system_times()
        while not stop.wait(0.25):
            now = time.perf_counter()
            late = now - last_tick["t"]
            if late < 1.0:
                dumped_for = None
                load_mark = winjob.system_times()
                continue
            if dumped_for == last_tick["t"]:
                continue
            dumped_for = last_tick["t"]
            frames = sys._current_frames()
            names = {thread.ident: thread.name for thread in threading.enumerate()}
            with lock:
                live = [{"kind": kind, "pid": proc.pid, "running": proc.poll() is None}
                        for kind, proc, _t in children if proc.poll() is None]
            stall_dumps.append({
                "at_s": round(now - (state["t_start"] or now), 3), "late_s": round(late, 3),
                "segments_done": len(segments), "machine_load_pct_since_last_tick": winjob.load_between(
                    load_mark, winjob.system_times()),
                "self": winjob.self_facts(), "job": job.snapshot(), "live_children": live,
                "threads": {names.get(ident, str(ident)): "".join(traceback.format_stack(frame)[-6:])
                            for ident, frame in frames.items()},
            })

    def settled() -> bool:
        return not panel._busy.is_set() and panel.run_result is not None

    expected_tick = {"t": None}

    def live_children() -> list:
        with lock:
            return [{"kind": kind, "pid": proc.pid} for kind, proc, _t in children if proc.poll() is None]

    def tick():
        now = time.perf_counter()
        last_tick["t"] = now
        if expected_tick["t"] is not None:
            heartbeat.append(max(0.0, now - expected_tick["t"]))
            if heartbeat[-1] > 0.25:
                stalls.append({"at_s": round(expected_tick["t"] - state["t_start"], 3),
                               "late_s": round(heartbeat[-1], 3), "segments_done": len(segments)})
        expected_tick["t"] = now + 0.05
        done = sum(1 for s in segments if s.get("finalised"))
        if now - state["t_start"] > args.timeout and not state["timed_out"]:
            state["timed_out"] = True
            panel.cancel()
        if state["t_cancel"] is None and (
                (args.cancel_after and done >= args.cancel_after)
                or (wants["cancel_at"] is not None and now >= wants["cancel_at"])):
            state["t_cancel"] = time.perf_counter()
            state["cancel_in_segment"] = len(segments)
            panel.cancel()
        if args.pause_after and state["paused_at"] is None and done >= args.pause_after:
            state["paused_at"] = now
            panel.pause()
        if state["paused_at"] is not None and state["resumed_at"] is None \
                and now - state["paused_at"] >= args.pause_seconds:
            state["resumed_at"] = now
            state["outputs_while_paused"] = sum(1 for s in segments if s.get("finalised")) - args.pause_after
            panel.resume()
        if not panel._busy.is_set() and panel.run_result is None and now - state["t_start"] > 5.0:
            # The worker ended without settling a result: a harness or application fault, never a measurement.
            state["results"].append("NO RESULT")
            state["t_settled"] = now
            tk_root.quit()
            return
        if settled():
            if state["phase"] == "first":
                state["t_settled"] = now
                state["alive_at_settle"] = live_children()
                state["results"].append(panel.run_result.state.name)
                if state["t_cancel"] is not None:
                    state["cancel_settled"] = now
                if args.kill and panel.run_result.has_retryable:
                    state["phase"] = "retry"
                    current["attempt"] = 1
                    state["retry_start"] = time.perf_counter()
                    panel.retry_failed()
                    tk_root.after(50, tick)
                    return
                tk_root.quit()
                return
            if state["phase"] == "retry":
                state["retry_settled"] = now
                state["alive_at_settle_retry"] = live_children()
                state["results"].append(panel.run_result.state.name)
                tk_root.quit()
                return
        tk_root.after(50, tick)

    threads = [threading.Thread(target=sample_disk, daemon=True, name="bench-disk"),
               threading.Thread(target=watchdog, daemon=True, name="bench-watchdog")]
    job_before = job.snapshot()
    self_before = winjob.self_facts()
    load_before = winjob.system_times()
    state["t_start"] = time.perf_counter()
    last_tick["t"] = state["t_start"]
    for thread in threads:
        thread.start()
    panel.start_convert()
    tk_root.after(50, tick)
    tk_root.mainloop()
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    load_during = winjob.load_between(load_before, winjob.system_times())
    job_after = job.snapshot()
    self_after = winjob.self_facts()

    plan = panel.run_plan
    run_dir = Path(plan.run_directory) if plan is not None and plan.run_directory else None
    files, folders = [], []
    if run_dir is not None and run_dir.exists():
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                entry = {"path": path.relative_to(run_dir).as_posix(), "bytes": path.stat().st_size}
                if args.hash_outputs:
                    entry["sha256"] = sha256(path)
                files.append(entry)
            elif path.is_dir():
                folders.append(path.relative_to(run_dir).as_posix())
    escaped = [str(p) for p in output_base.parent.iterdir()
               if p.name not in {"tmp", "runtime-data", "output-base"}] if output_base.parent.exists() else []

    walls = [s["wall_s"] for s in segments if s["attempt"] == 0]
    with lock:
        child_kinds: dict = {}
        for kind, _proc, _t in children:
            child_kinds[kind] = child_kinds.get(kind, 0) + 1
    results = {
        "label": args.label, "code": str(code), "argv": sys.argv,
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "cpu": platform.processor(), "cpu_count": os.cpu_count(),
                        "ffmpeg": ffmpeg, "ffmpeg_sha256": sha256(Path(ffmpeg)),
                        "ffprobe_sha256": sha256(Path(ffprobe))},
        "containment": {**containment, "reservations_refused": refused, "unexpected_entries": escaped},
        "route": {"asked": args.route, "threshold_used": str(threshold), "production_threshold": production_threshold,
                  "prefix_per_book_second": None if m4b_continuous is None else m4b_continuous.PREFIX_PER_BOOK_SECOND,
                  "decisions": decisions},
        "sources": [{"path": s, "sha256_before": source_hashes_before[s], "sha256": sha256(Path(s)),
                     "bytes": Path(s).stat().st_size} for s in sources],
        "settings": {"mode": args.mode, "metadata": args.metadata, "quality": args.quality},
        "outcome": {"states": state["results"], "timed_out": state["timed_out"], "killed": killed,
                    "run_dir": str(run_dir) if run_dir else None, "files": len(files), "folders": folders,
                    "alive_at_settle": state["alive_at_settle"], "alive_at_settle_retry": state.get("alive_at_settle_retry"),
                    "failures": [{"message": r.display_message, "detail": r.technical_detail[-600:]}
                                 for r in getattr(getattr(panel.run_result, "failures", None), "records", ())]},
        "timing": {
            "first_attempt_s": (state["t_settled"] - state["t_start"]) if state["t_settled"] else None,
            "retry_s": (state["retry_settled"] - state["retry_start"]) if state["retry_settled"] else None,
            "cancel_to_settled_s": (state["cancel_settled"] - state["t_cancel"]) if state["cancel_settled"] else None,
            "cancel_in_segment": state.get("cancel_in_segment"),
            "paused_at_s": (state["paused_at"] - state["t_start"]) if state["paused_at"] else None,
            "resumed_at_s": (state["resumed_at"] - state["t_start"]) if state["resumed_at"] else None,
            "outputs_while_paused": state.get("outputs_while_paused"),
            "segments": len(walls), "segment_sum_s": sum(walls),
            "segment_median_s": statistics.median(walls) if walls else None,
            "probe_s": sum(p["wall_s"] for p in probes),
            "scan_s": sum(d["scan_s"] for d in decisions),
            "machine_load_pct_during": load_during,
        },
        "children": child_kinds,
        "job": {"before_run": job_before, "after_run": job_after, "at_start": job_at_start,
                "run_processes": job_after["processes"] - job_before["processes"],
                "active_after": job_after["active"],
                "run_user_s": job_after["user_s"] - job_before["user_s"],
                "run_kernel_s": job_after["kernel_s"] - job_before["kernel_s"],
                "run_read_bytes": job_after["read_bytes"] - job_before["read_bytes"],
                "run_write_bytes": job_after["write_bytes"] - job_before["write_bytes"]},
        "harness_self": {"before": self_before, "after": self_after},
        "heartbeat": {"ticks": len(heartbeat), "p50_s": percentile(heartbeat, 0.5),
                      "p99_s": percentile(heartbeat, 0.99), "max_s": max(heartbeat) if heartbeat else None,
                      "over_250ms": sum(1 for v in heartbeat if v > 0.25),
                      "over_2s": sum(1 for v in heartbeat if v > 2.0)},
        "stalls": stalls,
        "stall_diagnostics": stall_dumps,
        "decoders": decoders,
        "disk": {"peak_staged_bytes": disk["peak_staged"], "samples": disk["samples"],
                 "output_bytes": sum(f["bytes"] for f in files)},
        "probes": probes,
        "segments": [{**{k: v for k, v in s.items() if k != "t_begin"},
                      "begin_offset_s": round(s["t_begin"] - state["t_start"], 3)} for s in segments],
        "files": files,
        "transcript": "".join(transcript),
    }
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    t = results["timing"]
    print(json.dumps({"label": args.label, "states": state["results"], "first_attempt_s": t["first_attempt_s"],
                      "segments": t["segments"], "routes": [d["continuous"] for d in decisions],
                      "processes": results["job"]["run_processes"],
                      "peak_job_commit_MB": round(job_after["peak_job_commit"] / 1e6, 1),
                      "hb_max_s": results["heartbeat"]["max_s"], "files": len(files)}), flush=True)
    try:
        panel.close()
        panel.destroy()
        tk_root.destroy()
    except Exception:  # noqa: BLE001 - teardown only
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as refusal:
        print(json.dumps({"refused": refusal.message}), flush=True)
        sys.exit(EXIT_CONTAINMENT)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - a harness failure is reported, never mistaken for a measurement
        traceback.print_exc()
        sys.exit(EXIT_HARNESS)
