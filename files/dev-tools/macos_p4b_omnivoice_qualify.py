"""Dev-only (macOS P4B): qualify the INSTALLED production OmniVoice engine on this Mac. Never shipped.

    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py voices [--device mps|cpu] [--track A|B]
                                                                              [--voice <id> ...]
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_qualify.py long [--chunks 60] [--voice <id>]
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
  warm-up, and the hand-over to a fresh worker at the bound.
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


def convert(voice_id: str, text: str, dest: Path, *, cancel_check=None) -> dict:
    """One production conversion, watched. Returns the facts."""
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
                                      encoder=watch.encoder, cancel_check=cancel_check)
        except ConversionCancelled:
            result = "CANCELLED"
        except BaseException as exc:  # noqa: BLE001 - recorded
            result = f"{type(exc).__name__}: {exc}"
    wall = time.monotonic() - started
    facts = {"voice_id": voice_id, "result": result, "wall_s": round(wall, 2), "log": lines,
             "spawned": watch.spawned, "published": dest.exists()}
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


def cmd_long(args) -> int:
    choose(args.device)
    dest = OUT / "long" / f"long-{args.chunks}-{args.voice}-{args.device}.mp3"
    facts = convert(args.voice, long_text(args.chunks), dest)
    first = [m for m in facts["chunk_memory"]][:osy.CHUNKS_PER_WORKER]
    after = [m for m in first[5:] if m.get("footprint_mib")]
    trend = {}
    if len(after) >= 2:
        for key in ("footprint_mib", "mps_driver_mib", "mps_allocated_mib"):
            values = [m.get(key) for m in after if m.get(key) is not None]
            if values:
                trend[key] = {"after_warmup": values[0], "last": values[-1], "max": max(values),
                              "growth_pct": round(100.0 * (values[-1] - values[0]) / values[0], 2) if values[0] else None}
    facts["first_worker_trend"] = trend
    facts["workers_used"] = len(facts["workers"])
    out = OUT / "long" / f"long-{args.chunks}-{args.voice}-{args.device}.json"
    facts["processes_after"] = act_processes()
    write_json(out, facts)
    print(json.dumps({k: facts.get(k) for k in ("result", "chunks", "workers_used", "audio_s", "rtf_wall",
                                                 "peak_footprint_mib", "max_mps_driver_mib", "first_worker_trend",
                                                 "flags")}, indent=1), flush=True)
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
from shared import subprocess_utils
subprocess_utils.enable_containment()  # exactly what the app window does at start
from tts import generate_voice_samples as gvs, omnivoice_synth as osy
report = Path(sys.argv[2])
original_spawn, original_run = osy.spawn_worker, osy.run_worker
def spawn(cmd, **kwargs):
    proc = original_spawn(cmd, **kwargs)
    report.write_text(json.dumps({"worker_pid": proc.pid, "worker_pgid": os.getpgid(proc.pid)}))
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
    killed_at = time.monotonic()
    os.kill(owner.pid, signal.SIGKILL)
    owner.wait()
    gone_at = None
    while time.monotonic() - killed_at < 10:
        if group_gone(data["worker_pgid"]):
            gone_at = time.monotonic()
            break
        time.sleep(0.01)
    result = {"worker_pid": data["worker_pid"], "worker_pgid": data["worker_pgid"], "chunks_before_kill": data["chunks"],
              "owner_signal": "SIGKILL", "worker_group_gone_s": None if gone_at is None else round(gone_at - killed_at, 3),
              "bound_s": 3.0, "published": dest.exists(),
              "job_folders_left": sorted(p.name for p in ov.jobs_root().glob("*") if p.is_dir()),
              "processes_after": act_processes()}
    write_json(folder / "kx1.json", result)
    print(json.dumps(result, indent=1), flush=True)
    return 0 if gone_at is not None and gone_at - killed_at <= 3.0 and not dest.exists() else 1


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
