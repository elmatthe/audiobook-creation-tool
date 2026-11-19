"""Dev-only (macOS P4B): qualify the INSTALLED production OmniVoice engine on this Mac. Never shipped.

    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py voices [--device mps|cpu] [--track A|B]
                                                                              [--voice <id> ...]
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py long [--chunks 60] [--voice <id>]
                     [--text short|paragraphs|book] [--book-chars N] [--chunks-per-worker N] [--footprint-at I ...]
                     [--ceiling-mib M]
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py cancel [--device mps|cpu]
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py kx1
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py assets

Unlike the P4A harness nothing is redirected: the engine is the installed ``.venv/engines/omnivoice`` (its receipt says
ready), the model is the recorded one, the worker is ``scripts/tts/omnivoice_worker.py`` started through the production
supervisor (``omnivoice_synth.run_worker`` / ``spawn_worker``), the clone prompts are the production cache and the job
folders the production ones. Each run goes through ``omnivoice_file_to_mp3`` -- speech preparation once, the chunk plan,
bounded workers, assembly, the final tail, one encode and the atomic publication -- via
``generate_voice_samples._synthesize_omnivoice`` (the production sample path, v1 speech preparation). Only the watching
is added: the worker's events, the chunk audio and the encoder's input are recorded as they pass.

``--device cpu`` asks the production device policy for the CPU through its configured-device seam
(``omnivoice_runtime.configured_mac_device``), i.e. what ``[tts] omnivoice_device = "cpu"`` in config.toml yields; the
config file itself is not edited (its parsing has its own tests). Outputs, records and logs go to
``files/dev-work/macos-p4b/q/`` (ignored). Texts A and B are the Windows-approved OmniVoice tracks
(``files/dev-tools/omnivoice_p4_acceptance.py``).

* ``voices``  six voices (or ``--voice``) on text A, or text B (multi-chunk), each one MP3 with RTF, memory, device and
  the per-chunk integrity screen.
* ``long``    one voice on a text of ``--chunks`` one-sentence paragraphs (each its own chunk), so more than
  ``CHUNKS_PER_WORKER`` (48) chunks run: the per-chunk memory trend inside the first worker, its growth after a 5-chunk
  warm-up, and the hand-over to a fresh worker at the bound. The memory checkpoint (after P4B) adds the
  ``chunks_per_worker`` seam (``--chunks-per-worker``), a stress text of long, all-different paragraphs
  (``--text paragraphs``), per-worker growth and start-up, per-chunk SHA-256 of the audio, swap and memory-pressure
  readings, ``footprint -p`` by category at chosen chunks, and a safety ceiling that cancels a run whose worker passes
  ``--ceiling-mib`` (default 14 GiB on this 24 GB Mac). Its records go to ``q/memory/``. P5 (v0.8.0 closeout) adds
  ``--text book``: the opening of Re:Monster volume 1 cut at a paragraph end past ``--book-chars`` (the P2 chapter's
  own cut, through ACT's PDF extractor; local only), the >=30-minute real-book run the plan asks of each engine.
* ``cancel``  CX-3: Cancel 1 s after the first chunk finished (the next chunk is being generated): the time to
  ``ConversionCancelled``, the worker's group empty, nothing published, the job folder gone.
* ``kx1``     KX-1(c): an owner process (containment enabled exactly as the app window enables it) runs a conversion;
  once its worker is generating, the owner is SIGKILLed (what Force Quit sends): the worker's group must be gone within
  3 s, with nothing published.
* ``assets``  the 18 references, both transcript files and the 28 previews re-verified (read-only).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from shared import child_ownership  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from tts import generate_voice_samples as gvs  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402
from tts import omnivoice_synth as osy  # noqa: E402

OUT = REPO / "files" / "dev-work" / "macos-p4b" / "q"
GIB = 2**30


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def choose(device: str) -> None:
    """The production policy, asked for *device* the way a config.toml choice reaches it."""
    if device not in ov.MAC_DEVICES:
        raise SystemExit(f"--device must be one of {ov.MAC_DEVICES}")
    ov.configured_mac_device = lambda: (device, "config.toml (qualification: --device)")  # type: ignore[assignment]


def texts() -> dict:
    from omnivoice_p4_acceptance import track_a_source, track_b_items, track_b_source

    return {"A": track_a_source(), "B": track_b_source(track_b_items())}


def voice_entry(voice_id: str):
    return next(v for v in gvs.VOICES if v.backend == "omnivoice" and v.voice_id == voice_id)


def group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def worker_is_live(pid: int, pgid: int, birth) -> bool:
    """The worker recorded at spawn, by its kernel start time, is still running (not exited, not a zombie, not an id reused)
    and still leads the group it was recorded in."""
    if birth is None or child_ownership.process_start_time(pid) != tuple(birth):
        return False
    if child_ownership._has_exited(pid):  # macOS reads the kernel's state for any pid: a zombie has exited
        return False
    try:
        return os.getpgid(pid) == pgid and not group_gone(pgid)
    except OSError:
        return False


def kill_boundary(owner: subprocess.Popen, owner_birth, worker: dict) -> list[str]:
    """v0.8.x P5-H-R1 (Codex MEDIUM 2): why the owner may NOT be killed now as a KX-1 drill (empty: it may). The drill times
    the retirement of a worker that is live when its owner dies; a worker or group already gone, or an owner already ended
    (or reaped, its id free for reuse), would make the timing and the absence checks prove nothing."""
    problems = []
    if owner.returncode is not None or owner_birth is None or child_ownership.process_start_time(owner.pid) != owner_birth:
        problems.append("the owner is no longer the process started for this drill")
    if not worker_is_live(worker.get("worker_pid", -1), worker.get("worker_pgid", -1), worker.get("worker_start")):
        problems.append("the worker recorded at spawn is not live in its group at the kill boundary")
    return problems


def attributable(rows: list[str], worker: dict, owner_pid: int) -> list[str]:
    """``act_processes`` rows that belong to this drill: its owner, its worker, or the worker's group."""
    mine = []
    for row in rows:
        fields = row.split(None, 2)
        try:
            pid, pgid = int(fields[0]), int(fields[1])
        except (IndexError, ValueError):
            continue
        if pid in (owner_pid, worker.get("worker_pid")) or pgid == worker.get("worker_pgid"):
            mine.append(row)
    return mine


def act_processes() -> list[str]:
    """Every process whose command line names this checkout's OmniVoice engine or worker (read-only)."""
    rows = subprocess.run(["ps", "-axo", "pid,pgid,command"], capture_output=True, text=True).stdout.splitlines()
    return [r for r in rows if ("omnivoice_worker.py" in r or "engines/omnivoice" in r) and "ps -axo" not in r]


class Watch:
    """Records what passes through the production supervisor, chunk reader and encoder of one conversion."""

    def __init__(self):
        self.runs: list[dict] = []
        self.chunks = None
        self.rate = None
        self.encoder_input = None
        self.spawned: list[dict] = []

    def __enter__(self):
        self._run, self._collect, self._spawn = osy.run_worker, osy.collect_chunks, osy.spawn_worker
        watch = self

        def run_worker(*a, **k):
            run = watch._run(*a, **k)
            watch.runs.append({"terminal": run.terminal, "loaded": run.loaded, "chunk_events": run.chunk_events,
                               "returncode": run.returncode})
            return run

        def collect(*a, **k):
            audio, rate = watch._collect(*a, **k)
            watch.chunks, watch.rate = [np.array(x) for x in audio], rate
            return audio, rate

        def spawn(cmd, **kwargs):
            proc = watch._spawn(cmd, **kwargs)
            watch.spawned.append({"pid": proc.pid, "pgid": os.getpgid(proc.pid), "at": time.monotonic()})
            return proc

        osy.run_worker, osy.collect_chunks, osy.spawn_worker = run_worker, collect, spawn
        return self

    def __exit__(self, *exc):
        osy.run_worker, osy.collect_chunks, osy.spawn_worker = self._run, self._collect, self._spawn

    def encoder(self, wav, mp3, bitrate, *, work_dir, cancel_check=None):
        pcm, rate = sf.read(str(wav), dtype="int16", always_2d=False)
        self.encoder_input = {"rate": int(rate), "seconds": round(pcm.size / rate, 3),
                              "full_scale_samples": int(np.count_nonzero((pcm == 32767) | (pcm == -32768)))}
        osy._encoder(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)


def convert(voice_id: str, text: str, dest: Path, *, cancel_check=None, seams: dict | None = None) -> dict:
    """One production conversion, watched. Returns the facts. *seams* go to ``omnivoice_file_to_mp3`` unchanged (the
    memory checkpoint passes its ``chunks_per_worker`` test seam)."""
    from macos_p4a_omnivoice_run import flags, screen  # the P4A integrity screen (pure functions)

    snap = gvs.omnivoice_speech_prep()
    lines: list[str] = []
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    started = time.monotonic()
    result = "PASS"
    with Watch() as watch:
        try:
            gvs._synthesize_omnivoice(voice_entry(voice_id), text, dest, log=lines.append, speech_prep=snap,
                                      encoder=watch.encoder, cancel_check=cancel_check, **(seams or {}))
        except ConversionCancelled:
            result = "CANCELLED"
        except BaseException as exc:  # noqa: BLE001 - recorded
            result = f"{type(exc).__name__}: {exc}"
    wall = time.monotonic() - started
    facts = {"voice_id": voice_id, "result": result, "wall_s": round(wall, 2), "log": lines,
             "spawned": watch.spawned, "published": dest.exists()}
    if watch.chunks is not None:  # each chunk's exact float32 samples, for the determinism comparison
        import hashlib

        facts["chunk_sha256"] = [hashlib.sha256(np.ascontiguousarray(a, dtype=np.float32).tobytes()).hexdigest()
                                 for a in watch.chunks]
    events = [e for r in watch.runs for e in r["chunk_events"]]
    facts["workers"] = [{"loaded": {k: r["loaded"].get(k) for k in ("device", "device_name", "dtype", "load_s",
                                                                     "prompt", "prompt_s", "versions")},
                         "terminal": r["terminal"], "returncode": r["returncode"], "chunks": len(r["chunk_events"])}
                        for r in watch.runs]
    facts["chunk_memory"] = [{k: e.get(k) for k in ("index", "gen_s", "audio_s", "footprint_mib", "mps_allocated_mib",
                                                     "mps_driver_mib")} for e in events]
    if result == "PASS":
        prepared_texts = [c.text for c in osy.plan_chunks(osy.prepare(text, snap, osy.OMNIVOICE_ROUTE).text)]
        screens = [screen(a, watch.rate, t) for a, t in zip(watch.chunks, prepared_texts)]
        seconds = watch.encoder_input["seconds"]
        facts.update({
            "mp3": str(dest.relative_to(REPO)), "mp3_sha256": sha256_file(dest), "mp3_bytes": dest.stat().st_size,
            "audio_s": seconds, "rtf_wall": round(wall / seconds, 3),
            "rtf_inference": round(sum(e["gen_s"] for e in events) / sum(e["audio_s"] for e in events), 3),
            "chunks": len(events), "encoder_input": watch.encoder_input,
            "peak_footprint_mib": max((r["terminal"].get("peak_footprint_mib") or 0) for r in watch.runs),
            "max_mps_driver_mib": max((e.get("mps_driver_mib") or 0) for e in events) or None,
            "chunk_screens": screens, "flags": sorted({f for s in screens for f in flags(s, None)}),
            "devices": sorted({str(r["loaded"].get("device")) for r in watch.runs}),
        })
    return facts


def cmd_voices(args) -> int:
    choose(args.device)
    all_texts = texts()
    out = OUT / "voices" / f"{args.device}-{args.track}.json"
    record = read_json(out) or {"samples": {}}
    record["text"] = {"track": args.track, "chars": len(all_texts[args.track])}
    voices = args.voice or [v.voice_id for v in ov.OMNIVOICE_VOICES]
    for voice_id in voices:
        dest = OUT / "voices" / f"{args.track}-{voice_id}-{args.device}.mp3"
        facts = convert(voice_id, all_texts[args.track], dest)
        record["samples"][voice_id] = facts
        print(voice_id, facts["result"], facts.get("audio_s"), facts.get("rtf_wall"), facts.get("peak_footprint_mib"),
              facts.get("devices"), facts.get("flags"), flush=True)
        write_json(out, record)
    record["processes_after"] = act_processes()
    write_json(out, record)
    return 0 if all(s["result"] == "PASS" for s in record["samples"].values()) else 1


SENTENCES = [
    "The lantern swung gently above the narrow doorway.", "Rain tapped a slow rhythm on the old tin roof.",
    "She folded the letter twice before slipping it away.", "A cart rolled past, its wheels creaking in the mud.",
    "The baker set the first loaves to cool by the window.", "Far off, a bell rang the hour across the valley.",
    "He counted the coins once more and sighed quietly.", "Smoke curled from the chimney into the grey morning.",
    "The river carried leaves toward the sleeping town.", "Somewhere a dog barked, then settled back to rest.",
]


def long_text(count: int) -> str:
    return "\n\n".join(f"{SENTENCES[i % len(SENTENCES)]} This is passage number {i + 1}." for i in range(count))


def paragraph_text(count: int) -> str:
    """*count* distinct paragraphs of four or five sentences (about 230-290 characters after speech preparation), each
    one whole chunk: a book-like load of long, all-different chunks (the memory checkpoint's stress text)."""
    rows = []
    for i in range(count):
        take = 4 + (i % 2)
        picked = [SENTENCES[(i * 3 + k) % len(SENTENCES)] for k in range(take)]
        rows.append(" ".join(picked) + f" This is passage number {i + 1}.")
    return "\n\n".join(rows)


WARMUP = 5  # chunks: the P4B growth measure starts after a worker's fifth chunk


def growth(rows: list[dict]) -> dict:
    """Footprint / MPS figures over one worker's chunks: first, after the warm-up, last, max and the growth after it."""
    found = {}
    for key in ("footprint_mib", "mps_driver_mib", "mps_allocated_mib"):
        values = [r.get(key) for r in rows if r.get(key) is not None]
        if not values:
            continue
        entry = {"first": values[0], "last": values[-1], "max": max(values)}
        after = values[WARMUP:]
        if len(after) >= 2 and after[0]:
            entry.update({"after_warmup": after[0], "growth_pct": round(100.0 * (after[-1] - after[0]) / after[0], 2),
                          "per_chunk_mib": round((after[-1] - after[0]) / (len(after) - 1), 1)})
        found[key] = entry
    return found


def sysctl(name: str) -> str:
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip()


def swapouts() -> int:
    for line in subprocess.run(["vm_stat"], capture_output=True, text=True).stdout.splitlines():
        if line.startswith("Swapouts:"):
            return int(line.split(":")[1].strip().rstrip("."))
    return -1


def footprint_categories(pid: int) -> dict:
    """``footprint -p``: the process's footprint by category (dirty KB), read-only."""
    text = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True).stdout
    rows: dict = {}
    total = None
    for line in text.splitlines():
        parts = line.split()
        if "Footprint:" in line:
            total = line.split("Footprint:")[1].strip()
        if len(parts) >= 5 and parts[1] in ("KB", "MB", "GB", "B") and parts[3] in ("KB", "MB", "GB", "B"):
            scale = {"B": 1 / 1024, "KB": 1, "MB": 1024, "GB": 1024 * 1024}[parts[1]]
            name = " ".join(parts[7:]) if len(parts) > 7 else " ".join(parts[6:])
            if name and name != "TOTAL":
                rows[name] = round(float(parts[0]) * scale / 1024, 1)  # MiB dirty
    return {"footprint": total, "dirty_mib": dict(sorted(rows.items(), key=lambda kv: -kv[1])[:12])}


def heap_classes(pid: int, raw: Path) -> list[dict]:
    """``heap --sortBySize``: the largest malloc'd classes and types of a live process (read-only), raw text kept."""
    text = subprocess.run(["heap", "--sortBySize", str(pid)], capture_output=True, text=True).stdout
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(text, encoding="utf-8")
    rows, table = [], False
    for line in text.splitlines():
        if line.strip().startswith("COUNT") and "BYTES" in line:
            table = True
            continue
        parts = line.split()
        if table and len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit():
            rows.append({"count": int(parts[0]), "bytes": int(parts[1]), "name": " ".join(parts[3:])})
        if len(rows) >= 30:
            break
    return rows


def cmd_long(args) -> int:
    choose(args.device)
    bound = args.chunks_per_worker or "default"
    label = args.label or f"long-{args.text}-{args.chunks}-{args.voice}-{args.device}-w{bound}"
    folder = OUT / "memory" if args.label or args.chunks_per_worker or args.text != "short" else OUT / "long"
    dest = folder / f"{label}.mp3"
    book = None
    if args.text == "book":  # P5: a real book's opening (the P2 chapter's own cut: same extractor, same text hash)
        from macos_p2_qualify import chapter_text

        text, book = chapter_text(args.book_chars)
    else:
        text = long_text(args.chunks) if args.text == "short" else paragraph_text(args.chunks)
    planned = osy.plan_chunks(osy.prepare(text, gvs.omnivoice_speech_prep(), osy.OMNIVOICE_ROUTE).text)
    state: dict = {"times": [], "pids": [], "pressure": [], "categories": {}, "ceiling_hit": None}
    sample_at = set(args.footprint_at or [])
    heap_at = set(args.heap_at or [])
    state["heaps"] = {}
    original_spawn, original_run = osy.spawn_worker, osy.run_worker

    def spawn(cmd, **kwargs):
        proc = original_spawn(cmd, **kwargs)
        state["pids"].append({"pid": proc.pid, "at": time.monotonic()})
        return proc

    def run_worker(*a, **k):
        on_chunk = k.get("on_chunk")

        def chunk(event):
            now = time.monotonic()
            state["times"].append({"index": event.get("index"), "at": now, "worker": len(state["pids"])})
            state["pressure"].append(int(sysctl("kern.memorystatus_vm_pressure_level") or 0))
            state["times"][-1]["pressure"], state["times"][-1]["swapouts"] = state["pressure"][-1], swapouts()
            index = int(event.get("index", -1))
            if index in heap_at and state["pids"]:
                state["heaps"][str(index)] = heap_classes(state["pids"][-1]["pid"],
                                                          folder / f"{label}.heap-{index}.txt")
            if index in sample_at and state["pids"]:
                state["categories"][str(index)] = footprint_categories(state["pids"][-1]["pid"])
            if args.ceiling_mib and (event.get("footprint_mib") or 0) > args.ceiling_mib:
                state["ceiling_hit"] = {"index": index, "footprint_mib": event.get("footprint_mib")}
            if on_chunk is not None:
                on_chunk(event)
        k["on_chunk"] = chunk
        return original_run(*a, **k)

    osy.spawn_worker, osy.run_worker = spawn, run_worker
    system_before = {"swapusage": sysctl("vm.swapusage"), "swapouts": swapouts(),
                     "pressure_level": sysctl("kern.memorystatus_vm_pressure_level")}
    try:
        seams = {} if args.chunks_per_worker is None else {"chunks_per_worker": args.chunks_per_worker}
        facts = convert(args.voice, text, dest, cancel_check=lambda: state["ceiling_hit"] is not None, seams=seams)
    finally:
        osy.spawn_worker, osy.run_worker = original_spawn, original_run
    facts["system"] = {"before": system_before,
                       "after": {"swapusage": sysctl("vm.swapusage"), "swapouts": swapouts(),
                                 "pressure_level": sysctl("kern.memorystatus_vm_pressure_level")},
                       "max_pressure_level_during": max(state["pressure"] or [0]),
                       "pressure_levels_seen": sorted(set(state["pressure"]))}
    facts["system"]["swapouts_delta"] = facts["system"]["after"]["swapouts"] - system_before["swapouts"]
    facts["ceiling"] = {"mib": args.ceiling_mib, "hit": state["ceiling_hit"]}
    facts["footprint_categories"] = state["categories"]
    facts["heap_classes"] = state["heaps"]
    facts["chunk_system"] = [{k: t.get(k) for k in ("index", "worker", "pressure", "swapouts")} for t in state["times"]]
    facts["text"] = {"kind": args.text, "paragraphs": args.chunks, "planned_chunks": len(planned),
                     "chunk_chars": [len(c.text) for c in planned]}
    if book is not None:
        facts["text"].update({"paragraphs": book["paragraphs"], "book": book})
    facts["chunks_per_worker"] = args.chunks_per_worker or "production default"
    # One row per worker: its chunks, memory over its life, and its start-up (spawn -> first chunk, less that chunk).
    per_worker, rows = [], facts["chunk_memory"]
    gen = {m["index"]: m["gen_s"] for m in rows}
    for number, spawned in enumerate(state["pids"], start=1):
        mine = [m for m, t in zip(rows, state["times"]) if t["worker"] == number]
        first_t = next((t for t in state["times"] if t["worker"] == number), None)
        entry = {"worker": number, "chunks": [mine[0]["index"], mine[-1]["index"]] if mine else None,
                 "count": len(mine), "memory": growth(mine)}
        if first_t is not None:
            entry["startup_s"] = round(first_t["at"] - spawned["at"] - gen[first_t["index"]], 2)
        if number <= len(facts["workers"]):
            entry["load_s"] = facts["workers"][number - 1]["loaded"].get("load_s")
            entry["terminal_peak_footprint_mib"] = facts["workers"][number - 1]["terminal"].get("peak_footprint_mib")
        per_worker.append(entry)
    for prev, nxt in zip(per_worker, per_worker[1:]):  # what a restart gives back
        if prev["memory"].get("footprint_mib") and nxt["memory"].get("footprint_mib"):
            nxt["after_restart"] = {"previous_last": prev["memory"]["footprint_mib"]["last"],
                                    "this_first": nxt["memory"]["footprint_mib"]["first"]}
    facts["per_worker"] = per_worker
    facts["workers_used"] = len(facts["workers"])
    facts["first_worker_trend"] = per_worker[0]["memory"] if per_worker else {}
    facts["max_worker_growth_pct"] = max((w["memory"].get("footprint_mib", {}).get("growth_pct") or 0)
                                         for w in per_worker) if per_worker else None
    facts["startup_total_s"] = round(sum(w.get("startup_s") or 0 for w in per_worker), 2)
    facts["processes_after"] = act_processes()
    write_json(folder / f"{label}.json", facts)
    print(json.dumps({k: facts.get(k) for k in ("result", "chunks", "workers_used", "audio_s", "rtf_wall",
                                                 "rtf_inference", "peak_footprint_mib", "max_mps_driver_mib",
                                                 "max_worker_growth_pct", "startup_total_s", "system", "ceiling",
                                                 "mp3_sha256", "flags", "processes_after")}, indent=1), flush=True)
    for w in per_worker:
        print(json.dumps(w), flush=True)
    return 0 if facts["result"] == "PASS" else 1


def cmd_cancel(args) -> int:
    choose(args.device)
    text = texts()["B"]
    dest = OUT / "cancel" / f"cx3-{args.device}.mp3"
    state: dict = {}

    def cancel_check() -> bool:
        now = time.monotonic()
        chunks = sum(len(r) for r in [state.get("events", [])])
        if "first_chunk_at" not in state and chunks:
            state["first_chunk_at"] = now
        if "latched_at" not in state and "first_chunk_at" in state and now - state["first_chunk_at"] >= 1.0:
            state["latched_at"] = now
        return "latched_at" in state

    original = osy.run_worker

    def run_worker(*a, **k):
        on_chunk = k.get("on_chunk")

        def chunk(event):
            state.setdefault("events", []).append(event)
            if on_chunk is not None:
                on_chunk(event)
        k["on_chunk"] = chunk
        return original(*a, **k)

    osy.run_worker = run_worker
    try:
        facts = convert("omnivoice-female-1", text, dest, cancel_check=cancel_check)
    finally:
        osy.run_worker = original
    ended = time.monotonic()
    worker = facts["spawned"][-1] if facts["spawned"] else None
    facts["cx3"] = {
        "device": args.device, "chunks_done_before_cancel": len(state.get("events", [])),
        "stop_s": round(ended - state["latched_at"], 3) if "latched_at" in state else None,
        "worker_group_empty": group_gone(worker["pgid"]) if worker else None,
        "published": dest.exists(), "job_folders_left": sorted(p.name for p in ov.jobs_root().glob("*") if p.is_dir()),
        "bound_s": 4.0,
    }
    facts["processes_after"] = act_processes()
    write_json(OUT / "cancel" / f"cx3-{args.device}.json", facts)
    print(json.dumps({"result": facts["result"], **facts["cx3"]}, indent=1), flush=True)
    ok = (facts["result"] == "CANCELLED" and facts["cx3"]["stop_s"] is not None and facts["cx3"]["stop_s"] <= 4.0
          and facts["cx3"]["worker_group_empty"] and not facts["cx3"]["published"])
    return 0 if ok else 1


OWNER = r'''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/scripts")
sys.path.insert(0, sys.argv[1] + "/files/dev-tools")
from shared import child_ownership, subprocess_utils
subprocess_utils.enable_containment()  # exactly what the app window does at start
from tts import generate_voice_samples as gvs, omnivoice_synth as osy
report = Path(sys.argv[2])
original_spawn, original_run = osy.spawn_worker, osy.run_worker
def spawn(cmd, **kwargs):
    proc = original_spawn(cmd, **kwargs)
    report.write_text(json.dumps({"worker_pid": proc.pid, "worker_pgid": os.getpgid(proc.pid),
                                  "worker_start": child_ownership.process_start_time(proc.pid)}))
    return proc
def run_worker(*a, **k):
    on_chunk = k.get("on_chunk")
    def chunk(event):
        data = json.loads(report.read_text()); data["chunks"] = data.get("chunks", 0) + 1
        report.write_text(json.dumps(data))
        if on_chunk: on_chunk(event)
    k["on_chunk"] = chunk
    return original_run(*a, **k)
osy.spawn_worker, osy.run_worker = spawn, run_worker
voice = next(v for v in gvs.VOICES if v.voice_id == "omnivoice-male-1")
gvs._synthesize_omnivoice(voice, sys.argv[3], Path(sys.argv[4]), speech_prep=gvs.omnivoice_speech_prep())
'''


def cmd_kx1(args) -> int:
    folder = OUT / "kx1"
    folder.mkdir(parents=True, exist_ok=True)
    report, dest = folder / "owner-report.json", folder / "kx1.mp3"
    for path in (report, dest):
        if path.exists():
            path.unlink()
    owner = subprocess.Popen([sys.executable, "-I", "-B", "-c", OWNER, str(REPO), str(report), texts()["B"], str(dest)],
                             cwd=str(REPO), start_new_session=True)
    owner_birth = child_ownership.process_start_time(owner.pid)
    deadline = time.monotonic() + 600
    data: dict = {}
    while time.monotonic() < deadline and owner.poll() is None:
        try:
            data = json.loads(report.read_text())
        except (OSError, ValueError):
            data = {}
        if data.get("chunks", 0) >= 1:
            break
        time.sleep(0.05)
    if not data.get("worker_pgid"):
        owner.kill()
        raise SystemExit("the owner never reported a running worker")
    time.sleep(1.0)  # the next chunk is being generated
    status, result = drill(owner, owner_birth, data, dest)
    write_json(folder / "kx1.json", result)
    print(json.dumps(result, indent=1), flush=True)
    return status


def worker_present(worker: dict) -> bool:
    """The worker recorded at spawn still exists as that process and has not exited (not a zombie, not a reused id)."""
    birth = worker.get("worker_start")
    pid = worker.get("worker_pid", -1)
    return birth is not None and child_ownership.process_start_time(pid) == tuple(birth) and not child_ownership._has_exited(pid)


def drill(owner: subprocess.Popen, owner_birth, worker: dict, dest: Path, *, bound_s: float = 3.0) -> tuple[int, dict]:
    """KX-1 (v0.8.x P5-H-R1, Codex MEDIUM 2 and its re-review): kill the owner by SIGKILL while its worker is live, and time
    the worker group's retirement. Live at the signal is shown on both sides of it: the same live worker in its group just
    before (``kill_boundary``), and still present just after, before its retirement could have begun. The owner must be
    the process started for the drill and must die of that SIGKILL. Status 0 only for a drill that shows all of it."""
    base = {"worker_pid": worker.get("worker_pid"), "worker_pgid": worker.get("worker_pgid"),
            "worker_start": worker.get("worker_start"), "chunks_before_kill": worker.get("chunks"), "owner_signal": "SIGKILL"}
    refused = kill_boundary(owner, owner_birth, worker)
    killed_at = time.monotonic()
    signalled = not refused and child_ownership.signal_if_same(owner.pid, owner_birth, signal.SIGKILL)
    present_after = signalled and worker_present(worker)
    if not refused and not signalled:
        refused = ["the owner could not be signalled as the process started for this drill"]
    if not refused and not present_after:
        refused = ["the worker was not present just after the signal: live at the signal is not shown"]
    if refused:
        child_ownership.signal_if_same(owner.pid, owner_birth, signal.SIGKILL)
        owner.wait()
        result = {**base, "refused": refused, "live_at_kill": False, "processes_after": act_processes()}
        result["survivors"] = attributable(result["processes_after"], worker, owner.pid)
        return 1, result
    owner.wait()
    gone_at = None
    while time.monotonic() - killed_at < 10:
        if group_gone(worker["worker_pgid"]):
            gone_at = time.monotonic()
            break
        time.sleep(0.01)
    result = {**base, "live_at_kill": True, "owner_returncode": owner.returncode,
              "worker_group_gone_s": None if gone_at is None else round(gone_at - killed_at, 3), "bound_s": bound_s,
              "published": dest.exists(),
              "job_folders_left": sorted(p.name for p in ov.jobs_root().glob("*") if p.is_dir()),
              "processes_after": act_processes()}
    result["survivors"] = attributable(result["processes_after"], worker, owner.pid)
    ok = (owner.returncode == -signal.SIGKILL and gone_at is not None and gone_at - killed_at <= bound_s
          and not dest.exists() and not result["survivors"])
    return (0 if ok else 1), result


def cmd_assets(args) -> int:
    done = subprocess.run([sys.executable, "-I", "-B", str(REPO / "files/dev-work/macos-p2/check_protected.py"),
                           str(REPO)], capture_output=True, text=True, check=True)
    data = json.loads(done.stdout)
    write_json(OUT / f"protected-{args.label}.json", data)
    print({k: data[k] for k in ("head", "references_ok", "transcript_files_ok", "previews_ok", "bad")})
    return 0 if data["references_ok"] == 18 and data["previews_ok"] == 28 and not data["bad"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("voices")
    p.add_argument("--device", default="mps")
    p.add_argument("--track", default="A", choices=("A", "B"))
    p.add_argument("--voice", action="append")
    p = sub.add_parser("long")
    p.add_argument("--device", default="mps")
    p.add_argument("--chunks", type=int, default=60)
    p.add_argument("--voice", default="omnivoice-female-2")
    p.add_argument("--text", default="short", choices=("short", "paragraphs", "book"))
    p.add_argument("--book-chars", type=int, default=33000, help="--text book: the real book's excerpt, minimum length")
    p.add_argument("--chunks-per-worker", type=int, help="the test seam; omitted: the production default")
    p.add_argument("--heap-at", type=int, action="append", help="chunk index at which to read heap --sortBySize")
    p.add_argument("--footprint-at", type=int, action="append", help="chunk index at which to read footprint -p")
    p.add_argument("--ceiling-mib", type=int, default=14336, help="cancel the run if a worker passes this footprint")
    p.add_argument("--label")
    p = sub.add_parser("cancel")
    p.add_argument("--device", default="mps")
    sub.add_parser("kx1")
    p = sub.add_parser("assets")
    p.add_argument("--label", default="now")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or ov.assess_engine().state != ov.ENGINE_READY:
        if args.command != "assets":
            raise SystemExit("needs an Apple Silicon Mac with the OmniVoice engine installed (receipt: ready)")
    return {"voices": cmd_voices, "long": cmd_long, "cancel": cmd_cancel, "kx1": cmd_kx1,
            "assets": cmd_assets}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
