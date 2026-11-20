"""macos_p4a_omnivoice_run.py -- ACT v0.8.x macOS P4A: build the disposable OmniVoice environment and run stages S0-S4.

Developer only: never shipped, never imported by the application, no product code changed. Run it with the app's own
interpreter (it uses ACT's production text path): ``.venv/bin/python -I files/dev-tools/macos_p4a_omnivoice_run.py <cmd>``.

* ``verify-files``  re-hash every acquired file against the consented manifest (per-file receipt).
* ``create-env``    ``files/dev-work/omnivoice-feasibility/venv`` from the app-owned CPython 3.12 (``files/runtime-data/
                    python``), then pip installs the 86 verified wheels OFFLINE: ``--no-index --no-deps --require-hashes
                    --only-binary :all: --isolated``, from the local wheel folder only.
* ``verify-env``    ``pip check``, the installed set equal to the manifest, and isolation as the interpreter itself sees it.
* ``s0`` .. ``s4``  the stages of plan section 12.E (Revision 2a), for configurations C1 (cpu/float32), C2 (mps/float32)
                    and C3 (mps/float16).

The text path is ACT's own: the production ``v1`` speech-preparation snapshot (``generate_voice_samples.
omnivoice_speech_prep``), ``omnivoice_synth.plan_chunks``/``derive_seed``/``GENERATION``/``build_job``, and for the
listening pack the production source-to-MP3 entry point (``omnivoice_file_to_mp3`` through ``generate_voice_samples.
_synthesize_omnivoice``: supervisor, chunk reader, assembly, final tail, one encode, atomic publication). The only
differences from production are the device/dtype under test and where things live: in this process only, the module
values ``omnivoice_synth.DEVICE``/``DTYPE``, ``omnivoice_runtime.model_dir``/``engine_lock_path`` and the inference lease
are pointed at the experiment, so nothing is written to ``files/runtime-data``. Everything goes to
``files/dev-work/omnivoice-feasibility/`` (ignored).
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import platform
import queue
import random
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

import macos_p4a_omnivoice as acq  # noqa: E402  (the consented manifest and its locations; acquisition code untouched)
from tts import omnivoice_runtime as ov  # noqa: E402
from tts import omnivoice_synth as osy  # noqa: E402
from tts import qwen3_synth as _local  # noqa: E402
from tts.speech.document import read_source_text  # noqa: E402,F401
from tts.speech.pipeline import prepare  # noqa: E402
from tts.speech.profiles import OMNIVOICE as OMNIVOICE_ROUTE  # noqa: E402

AREA = acq.AREA
VENV = AREA / "venv"
VENV_PY = VENV / "bin" / "python"
WORKER = HERE / "macos_p4a_omnivoice_worker.py"
BASE_PY = REPO / "files" / "runtime-data" / "python" / "bin" / "python3.12"
RUNS = AREA / "runs"
PACK = AREA / "listening-pack"
CONFIGS = {"C1": ("cpu", "float32"), "C2": ("mps", "float32"), "C3": ("mps", "float16")}
#: A crossing of this physical footprint ends a run at once as unsafe (24 GiB machine; the D6-O TARGET is 10 GiB).
SAFETY_FOOTPRINT = 16 * 2**30
GIB = 2**30

#: S1: written for this project. One item per paragraph, so ACT's planner gives one chunk each (never across a
#: paragraph): one word up to one sentence near the 300-character chunk limit.
LADDER = [
    "Morning.",
    "The rain had stopped.",
    "She closed the old book and listened to the wind moving through the pines.",
    "The ferry left at dawn. By noon, the island was only a grey line on the horizon behind them.",
    "Captain Ilsa Moreno counted the crates twice, then a third time, because the ledger said forty-two and her eyes "
    "kept finding forty-one.",
    "When the lanterns finally went out along the harbor wall, the old keeper climbed the stairs one last time, pausing "
    "at every landing to catch his breath and look back at the sleeping town below.",
    "Nobody in the valley could remember who had planted the first orchard, but every spring the blossoms returned, the "
    "bees found them, and the children who ran between the rows grew up to tend the same crooked trees their "
    "grandparents had known.",
    "Long after the travelers had gone to sleep, the innkeeper sat alone beside the fading fire, turning a small brass "
    "key over in her fingers and trying to remember which of the many locked doors in that rambling old house it had "
    "been made to open, and why her mother had hidden it so carefully.",
]
NEUTRAL_TEXT = ("The quiet library opened early, and the first visitors walked softly between the tall wooden "
                "shelves.")
SOAK_TEXT = ("The river was wide and slow that summer, and the boatman sang the same quiet song each morning as he "
             "carried the villagers, their baskets and their news from one green bank to the other.")
HOLD_TEXT = "\n\n".join(LADDER[5:8] * 2)
B_VOICES = ("omnivoice-female-1", "omnivoice-male-1")
C3_PACK_VOICES = ("omnivoice-female-2", "omnivoice-male-2")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def sysctl(name: str) -> str:
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip()


def system_memory() -> dict:
    """Pressure level (1 normal, 2 warning, 4 critical), swap in use, and free+inactive+speculative pages."""
    swap = sysctl("vm.swapusage")  # "total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)"
    used = 0.0
    with contextlib.suppress(ValueError, IndexError):
        used = float(swap.split("used = ")[1].split("M")[0])
    pages = {}
    for line in subprocess.run(["vm_stat"], capture_output=True, text=True).stdout.splitlines()[1:]:
        key, _, value = line.partition(":")
        with contextlib.suppress(ValueError):
            pages[key.strip()] = int(value.strip().rstrip("."))
    page = 16384
    available = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative")) * page
    return {"pressure_level": int(sysctl("kern.memorystatus_vm_pressure_level") or 0), "swap_used_mib": used,
            "available_bytes": available}


_libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)


def footprint_of(pid: int) -> int | None:
    buffer = ctypes.create_string_buffer(512)
    if _libproc.proc_pid_rusage(pid, 4, buffer) != 0:
        return None
    return int(struct.unpack_from("=Q", buffer.raw, 16 + 7 * 8)[0])


def group_members(pgid: int) -> list[str]:
    out = subprocess.run(["ps", "-axo", "pid=,pgid=,command="], capture_output=True, text=True).stdout.splitlines()
    return [line.strip() for line in out if len(line.split()) > 1 and line.split()[1] == str(pgid)]


def leftovers() -> list[str]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout.splitlines()
    return [line.strip() for line in out if WORKER.name in line or str(VENV_PY) in line]


# --------------------------------------------------------------------------- #
# Files and the environment
# --------------------------------------------------------------------------- #
def cmd_verify_files(_args) -> int:
    manifest = acq.load_manifest()
    rows = []
    for kind, url, path, size, sha in acq.acquisition_items(manifest):
        actual = sha256_file(path) if path.is_file() else None
        rows.append({"kind": kind, "file": str(path.relative_to(REPO)), "source": url, "size": size,
                     "size_on_disk": path.stat().st_size if path.is_file() else None, "sha256": sha,
                     "ok": actual == sha and path.stat().st_size == size, "is_link": path.is_symlink()})
    extra = sorted(str(p.relative_to(REPO)) for root in (acq.area()["wheels"], acq.area()["model"])
                   for p in root.rglob("*") if p.is_file() and str(p.relative_to(REPO)) not in {r["file"] for r in rows})
    record = {"when": now(), "consent_token": acq.consent_token(), "files": len(rows),
              "ok": sum(r["ok"] for r in rows), "bytes": sum(r["size"] for r in rows), "unexpected_files": extra,
              "rows": rows}
    write_json(acq.area()["receipts"] / "files-verified.json", record)
    print(json.dumps({k: v for k, v in record.items() if k != "rows"}, indent=1))
    return 0 if record["ok"] == record["files"] and not extra else 1


def pip_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "PIP_", "VIRTUAL_ENV", "CONDA"))}
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PYTHONNOUSERSITE": "1", "TMPDIR": str(ensure(AREA / "tmp"))})
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                  if p and not p.startswith(str(REPO / ".venv")))
    return env


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def cmd_create_env(_args) -> int:
    if VENV.exists():
        print(f"REFUSED: {VENV} already exists; nothing is repaired or replaced")
        return 2
    manifest = acq.load_manifest()
    lock = AREA / "receipts" / "requirements-darwin.txt"
    lock.write_text("".join(f"{w['name']}=={w['version']} --hash=sha256:{w['sha256']}\n" for w in manifest["wheels"]),
                    encoding="utf-8")
    env = pip_env()
    log = AREA / "logs" / "create-env.log"
    ensure(log.parent)
    started = time.monotonic()
    with open(log, "w", encoding="utf-8") as out:
        for cmd in ([str(BASE_PY), "-I", "-m", "venv", str(VENV)],
                    [str(VENV_PY), "-I", "-m", "pip", "install", "--isolated", "--no-index", "--no-deps",
                     "--require-hashes", "--only-binary", ":all:", "--no-cache-dir", "--find-links",
                     str(acq.area()["wheels"]), "-r", str(lock)]):
            out.write(f"$ {' '.join(cmd)}\n")
            out.flush()
            rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, env=env, cwd=str(AREA)).returncode
            out.write(f"exit {rc}\n")
            if rc != 0:
                print(f"FAILED ({rc}); see {log}")
                return 1
    print(f"environment built in {time.monotonic() - started:.0f} s; log {log}")
    return 0


ISOLATION_PROBE = r"""
import json, site, sys, sysconfig, importlib.metadata as md
print(json.dumps({"prefix": sys.prefix, "base_prefix": sys.base_prefix, "executable": sys.executable,
  "path": sys.path, "user_site_enabled": site.ENABLE_USER_SITE, "purelib": sysconfig.get_paths()["purelib"],
  "dists": sorted({(d.metadata["Name"] or "").lower().replace("_", "-").replace(".", "-") + "==" + d.version
                   for d in md.distributions()})}))
"""


def cmd_verify_env(_args) -> int:
    manifest = acq.load_manifest()
    env = pip_env()
    check = subprocess.run([str(VENV_PY), "-I", "-m", "pip", "check"], capture_output=True, text=True, env=env)
    probe = json.loads(subprocess.run([str(VENV_PY), "-I", "-c", ISOLATION_PROBE], capture_output=True, text=True,
                                      env=env, check=True).stdout)
    wanted = {f"{w['name']}=={w['version']}" for w in manifest["wheels"]}
    installed = set(probe["dists"])
    extra = sorted(d for d in installed - wanted if not d.startswith("pip=="))
    venv_main = str(REPO / ".venv")
    leaks = [p for p in probe["path"] if p and (p.startswith(venv_main + os.sep) or p == venv_main
                                                or ("site-packages" in p and not p.startswith(str(VENV))))]
    torch_probe = subprocess.run([str(VENV_PY), "-I", "-c",
                                  "import torch,json;print(json.dumps({'torch':torch.__version__,"
                                  "'mps_built':torch.backends.mps.is_built(),'mps_available':torch.backends.mps."
                                  "is_available(),'threads':torch.get_num_threads()}))"],
                                 capture_output=True, text=True, env=env)
    record = {"when": now(), "pip_check": {"rc": check.returncode, "out": check.stdout.strip()[-800:]},
              "installed": len(installed), "missing": sorted(wanted - installed), "unexpected": extra,
              "pip_bootstrap": sorted(d for d in installed if d.startswith("pip==")),
              "sys_path_leaks": leaks, "user_site_enabled": probe["user_site_enabled"], "prefix": probe["prefix"],
              "base_prefix": probe["base_prefix"], "torch": json.loads(torch_probe.stdout or "{}"),
              "torch_stderr": torch_probe.stderr[-400:], "machine": platform.machine(),
              "venv_bytes": sum(p.stat().st_size for p in VENV.rglob("*") if p.is_file() and not p.is_symlink())}
    write_json(AREA / "receipts" / "env-verified.json", record)
    print(json.dumps(record, indent=1))
    ok = (check.returncode == 0 and not record["missing"] and not extra and not leaks and not probe["user_site_enabled"]
          and Path(probe["base_prefix"]).resolve() == (REPO / "files/runtime-data/python").resolve())
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Pointing ACT's production path at the experiment (this process only)
# --------------------------------------------------------------------------- #
class _NoLease:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def configure(cfg: str) -> None:
    device, dtype = CONFIGS[cfg]
    osy.DEVICE, osy.DTYPE = device, dtype
    model = acq.model_dir(acq.load_manifest())
    ov.model_dir = lambda: model
    ov.engine_lock_path = lambda: AREA / "engine.lock.unused"
    ov.inference_lease = _NoLease


def worker_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(ov._DROPPED_PREFIXES) and k.upper() not in ov._DROPPED_NAMES
           and k.upper() not in ("PYTORCH_ENABLE_MPS_FALLBACK", "PYTORCH_MPS_HIGH_WATERMARK_RATIO")}
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                  if p and not p.startswith(str(REPO / ".venv")))
    cache = ensure(AREA / "cache")
    for name in ("hf/hub", "torch", "numba", "xdg"):
        ensure(cache / name)
    env.update({"TEMP": str(ensure(AREA / "tmp")), "TMP": str(AREA / "tmp"), "TMPDIR": str(AREA / "tmp"),
                "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "HF_HOME": str(cache / "hf"), "HF_HUB_CACHE": str(cache / "hf" / "hub"), **ov.OFFLINE,
                "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1",
                "TORCH_HOME": str(cache / "torch"), "NUMBA_CACHE_DIR": str(cache / "numba"),
                "XDG_CACHE_HOME": str(cache / "xdg"), "XDG_CONFIG_HOME": str(cache / "xdg"),
                "MPLCONFIGDIR": str(cache / "xdg"), "PIP_NO_INDEX": "1"})
    return env


def snapshot():
    from tts import generate_voice_samples as gvs

    return gvs.omnivoice_speech_prep()


def prepared_chunks(text: str, snap) -> list:
    prepared = prepare(text, snap, OMNIVOICE_ROUTE)
    chunks = osy.plan_chunks(prepared.text)
    if prepared.enabled:
        _local.chunk_source_spans(prepared, chunks)
    return chunks


class Neutral:
    """The S1 neutral reference: a macOS built-in voice with a known transcript (no owner recording, no licence)."""
    voice_id = "p4a-neutral-say"


def neutral_reference() -> tuple[object, dict]:
    folder = ensure(RUNS / "neutral-reference")
    aiff, raw, wav = folder / "neutral.aiff", folder / "neutral-afconvert.wav", folder / "neutral.wav"
    if not wav.is_file():
        subprocess.run(["say", "-o", str(aiff), NEUTRAL_TEXT], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(aiff), str(raw)], check=True)
        import wave

        with wave.open(str(raw), "rb") as src:
            params, frames = src.getparams(), src.readframes(src.getnframes())
        with wave.open(str(wav), "wb") as dst:  # a plain PCM WAV (afconvert adds a FLLR padding chunk)
            dst.setnchannels(1), dst.setsampwidth(2), dst.setframerate(params.framerate), dst.writeframes(frames)
    import wave

    with wave.open(str(wav), "rb") as src:
        frames, rate = src.getnframes(), src.getframerate()
    spec = ov.ReferenceSpec("p4a-neutral-say", "neutral-say", sha256_file(wav), rate, 1, 2, frames, NEUTRAL_TEXT,
                            ov.text_sha256(NEUTRAL_TEXT))
    return spec, ov.verify_reference(spec, wav)


def voice_reference(voice_id: str) -> tuple[object, object, dict]:
    voice = ov.get_voice(voice_id)
    spec = ov.reference_spec(voice_id)
    return voice, spec, ov.verify_reference(spec, ov.reference_path(voice))


# --------------------------------------------------------------------------- #
# The direct supervisor (S0, S1, S3, S4): every event kept, footprint watched from outside, group always reaped
# --------------------------------------------------------------------------- #
def supervise(job: dict, job_dir: Path, *, on_event=None, stall_s: float = 1800.0) -> dict:
    ensure(job_dir)
    job_path = job_dir / "job.json"
    write_json(job_path, job)
    stderr_path = job_dir / "stderr.txt"
    events: list[dict] = []
    lines: "queue.Queue" = queue.Queue()
    mem_before = system_memory()
    started = time.monotonic()
    external_peak = 0
    unsafe = None
    with open(stderr_path, "w", encoding="utf-8") as err:
        proc = subprocess.Popen([str(VENV_PY), "-I", str(WORKER), str(job_path)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=err, text=True, env=worker_env(), cwd=str(job_dir),
                                start_new_session=True)

        def pump():
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        last = time.monotonic()
        next_sample = 0.0
        try:
            while True:
                t = time.monotonic()
                if t >= next_sample:
                    next_sample = t + 1.0
                    fp = footprint_of(proc.pid)
                    if fp:
                        external_peak = max(external_peak, fp)
                    pressure = int(sysctl("kern.memorystatus_vm_pressure_level") or 0)
                    if (fp and fp > SAFETY_FOOTPRINT) or pressure >= 4:
                        unsafe = {"footprint": fp, "pressure_level": pressure, "at_s": round(t - started, 2)}
                        os.killpg(proc.pid, signal.SIGKILL)
                        break
                if t - last > stall_s:
                    unsafe = {"stalled_s": round(t - last, 1)}
                    os.killpg(proc.pid, signal.SIGKILL)
                    break
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                event = _local.parse_event(line)
                if event is None:
                    continue
                last = time.monotonic()
                event["_t"] = round(last - started, 3)
                events.append(event)
                if on_event is not None:
                    on_event(event, proc)
        finally:
            with contextlib.suppress(ProcessLookupError):
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=10)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)  # nothing of the group may outlive the run
    terminal = next((e for e in reversed(events) if e["event"] in ("done", "failed", "canceled")), None)
    return {"returncode": proc.returncode, "events": events, "terminal": terminal,
            "loaded": next((e for e in events if e["event"] == "loaded"), None),
            "wall_s": round(time.monotonic() - started, 3), "external_peak_footprint": external_peak or None,
            "unsafe": unsafe, "stderr_tail": stderr_path.read_text(encoding="utf-8", errors="replace")[-1500:],
            "memory_before": mem_before, "memory_after": system_memory(), "group_left": group_members(proc.pid)}


def job_for(cfg: str, voice, spec, reference: dict, chunks: list, job_dir: Path, **p4a) -> dict:
    configure(cfg)
    manifest = ov.load_manifest()
    job = osy.build_job(voice, spec, chunks, job_dir=job_dir, reference=reference, model_dir=ov.model_dir(),
                        omnivoice_version=manifest["engine"]["omnivoice"], prompt_cache=None)
    job["p4a"] = {"safety_footprint_bytes": SAFETY_FOOTPRINT, **p4a}
    return job


# --------------------------------------------------------------------------- #
# Screening (automated integrity only; never a listening verdict)
# --------------------------------------------------------------------------- #
def screen(wav: np.ndarray, rate: int, text: str) -> dict:
    wav = np.asarray(wav, dtype=np.float32)
    finite = bool(np.isfinite(wav).all())
    if not finite or wav.size == 0:
        return {"finite": finite, "samples": int(wav.size)}
    hop = int(rate * 0.01)
    frames = wav[: len(wav) // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-12)
    voiced = db > -50
    first = int(np.argmax(voiced)) if voiced.any() else len(db)
    last = len(db) - int(np.argmax(voiced[::-1])) if voiced.any() else 0
    longest, run = 0, 0
    for v in voiced[first:last]:
        run = 0 if v else run + 1
        longest = max(longest, run)
    win = int(rate * 0.05)
    env = np.sqrt((wav[: len(wav) // win * win].reshape(-1, win) ** 2).mean(axis=1))
    env_v = env[env > 10 ** (-50 / 20)]
    cv = float(env_v.std() / env_v.mean()) if env_v.size > 2 else None
    n = 1024
    if len(wav) >= n:
        segs = wav[: len(wav) // n * n].reshape(-1, n) * np.hanning(n)
        mag = np.abs(np.fft.rfft(segs, axis=1)) + 1e-12
        flat = np.exp(np.log(mag).mean(axis=1)) / mag.mean(axis=1)
        loud = np.sqrt((segs ** 2).mean(axis=1)) > 10 ** (-45 / 20)
        flatness = float(flat[loud].mean()) if loud.any() else None
    else:
        flatness = None
    seconds = wav.size / rate
    speech_s = max((last - first) * 0.01, 1e-6)
    return {"finite": True, "seconds": round(seconds, 3), "peak": round(float(np.abs(wav).max()), 5),
            "clipped": int(np.count_nonzero(np.abs(wav) >= 0.999)), "lead_silence_s": round(first * 0.01, 2),
            "tail_silence_s": round((len(db) - last) * 0.01, 2), "longest_internal_silence_s": round(longest * 0.01, 2),
            "chars": len(text), "chars_per_s": round(len(text) / speech_s, 2), "envelope_cv": cv,
            "spectral_flatness": flatness}


def flags(m: dict, ref: dict | None) -> list[str]:
    out = []
    if not m.get("finite", False):
        return ["NON-FINITE"]
    if m["clipped"]:
        out.append(f"{m['clipped']} clipped samples")
    if m["longest_internal_silence_s"] > 2.0:
        out.append(f"internal silence {m['longest_internal_silence_s']} s")
    if m["chars"] >= 20 and not 8 <= m["chars_per_s"] <= 20:
        out.append(f"{m['chars_per_s']} characters/s outside 8-20")
    if ref and ref.get("finite") and m["envelope_cv"] and ref.get("envelope_cv"):
        ratio = m["envelope_cv"] / ref["envelope_cv"]
        if not 0.5 <= ratio <= 2.0:
            out.append(f"envelope variation {ratio:.2f}x C1")
    if ref and ref.get("finite") and m["spectral_flatness"] and ref.get("spectral_flatness"):
        ratio = m["spectral_flatness"] / ref["spectral_flatness"]
        if ratio > 2.0:
            out.append(f"spectral flatness {ratio:.2f}x C1 (noise signature)")
    return out


def chunk_audio(job_dir: Path, events: list[dict]) -> dict[int, np.ndarray]:
    found = {}
    for e in events:
        if e["event"] == "chunk":
            data, _ = sf.read(str(job_dir / "chunks" / e["wav"]), dtype="float32")
            found[int(e["index"])] = data
    return found


# --------------------------------------------------------------------------- #
# S0: offline load on each configuration (+ a one-line smoke generation for unsupported ops)
# --------------------------------------------------------------------------- #
def cmd_s0(args) -> int:
    voice, spec, reference = voice_reference("omnivoice-female-1")
    chunks = prepared_chunks("Hello there.", snapshot())
    results = {}
    for cfg in args.configs:
        job_dir = RUNS / "s0" / cfg
        job = job_for(cfg, voice, spec, reference, chunks, job_dir, mode="probe", smoke_text=chunks[0].text)
        r = supervise(job, job_dir, stall_s=900)
        results[cfg] = {k: r[k] for k in ("returncode", "terminal", "loaded", "wall_s", "external_peak_footprint",
                                            "unsafe", "group_left", "memory_before", "memory_after", "stderr_tail")}
        print(cfg, json.dumps({"terminal": r["terminal"], "loaded": {k: (r["loaded"] or {}).get(k) for k in (
            "parameter_devices", "parameter_dtypes", "tokenizer_device", "tokenizer_dtype", "load_s", "prompt_s",
            "footprint", "mps_driver")}}, default=str), flush=True)
    write_json(RUNS / "s0" / "s0.json", {"when": now(), "results": results, "leftovers": leftovers()})
    return 0


# --------------------------------------------------------------------------- #
# S1: the ladder (neutral reference, then Female 1), then same-device repeatability
# --------------------------------------------------------------------------- #
def run_ladder(cfg: str, who: str, texts: list[str], tag: str) -> dict:
    snap = snapshot()
    chunks = prepared_chunks("\n\n".join(texts), snap)
    if who == "neutral":
        spec, reference = neutral_reference()
        voice = Neutral()
    else:
        voice, spec, reference = voice_reference(who)
    job_dir = RUNS / "s1" / f"{tag}-{who}-{cfg}"
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job = job_for(cfg, voice, spec, reference, chunks, job_dir)
    r = supervise(job, job_dir)
    audio = chunk_audio(job_dir, r["events"])
    rate = (r["terminal"] or {}).get("sample_rate") or 24000
    items = []
    for c in chunks:
        ev = next((e for e in r["events"] if e["event"] == "chunk" and e["index"] == c.index), {})
        m = screen(audio[c.index], rate, c.text) if c.index in audio else {"finite": False, "missing": True}
        items.append({"index": c.index, "text": c.text, "seed": job["chunks"][c.index]["seed"], "gen_s": ev.get("gen_s"),
                      "rtf": round(ev["gen_s"] / ev["audio_s"], 3) if ev.get("audio_s") else None,
                      "sha256": hashlib.sha256(audio[c.index].tobytes()).hexdigest() if c.index in audio else None,
                      "footprint": ev.get("footprint"), "mps_driver": ev.get("mps_driver"), **m})
    return {"cfg": cfg, "who": who, "tag": tag, "job_dir": str(job_dir.relative_to(REPO)), "terminal": r["terminal"],
            "loaded": r["loaded"], "wall_s": r["wall_s"], "unsafe": r["unsafe"], "group_left": r["group_left"],
            "returncode": r["returncode"], "external_peak_footprint": r["external_peak_footprint"],
            "memory_after": r["memory_after"], "stderr_tail": r["stderr_tail"] if r["returncode"] else "",
            "items": items}


def cmd_s1(args) -> int:
    out = RUNS / "s1" / "s1.json"
    record = read_json(out) if out.is_file() else {"runs": {}}
    for cfg in args.configs:
        for who in ("neutral", "omnivoice-female-1"):
            key = f"ladder-{who}-{cfg}"
            if key in record["runs"] and not args.redo:
                continue
            record["runs"][key] = run_ladder(cfg, who, LADDER, "ladder")
            t = record["runs"][key]
            print(key, t["terminal"] and t["terminal"]["event"], t["wall_s"], flush=True)
            write_json(out, record)
        key = f"repeat-omnivoice-female-1-{cfg}"
        if key not in record["runs"] or args.redo:
            record["runs"][key] = run_ladder(cfg, "omnivoice-female-1", LADDER[:3], "repeat")
            write_json(out, record)
    # flags against C1 on the same item and same reference
    for key, run in record["runs"].items():
        ref_key = key.rsplit("-", 1)[0] + "-C1"
        ref = record["runs"].get(ref_key)
        for item in run["items"]:
            base = next((i for i in (ref or {}).get("items", []) if i["index"] == item["index"]), None)
            item["flags"] = flags(item, base if run["cfg"] != "C1" else None)
        if run["tag"] == "repeat":
            first = record["runs"].get(f"ladder-omnivoice-female-1-{run['cfg']}")
            if first:
                run["repeat_identical"] = [i["sha256"] == f["sha256"] for i, f in zip(run["items"], first["items"])]
    record["leftovers"] = leftovers()
    write_json(out, record)
    for key, run in record["runs"].items():
        print(key, run["terminal"] and run["terminal"]["event"],
              [(i["index"], i.get("seconds"), i.get("rtf"), i["flags"]) for i in run["items"]],
              run.get("repeat_identical", ""))
    return 0


# --------------------------------------------------------------------------- #
# S2: the owner listening pack through the production source-to-MP3 path
# --------------------------------------------------------------------------- #
def production_sample(cfg: str, voice_id: str, text: str, dest: Path, snap) -> dict:
    from tts import generate_voice_samples as gvs

    configure(cfg)
    voice = next(v for v in gvs.VOICES if v.backend == "omnivoice" and v.voice_id == voice_id)
    seen: dict = {"runs": [], "chunks": None, "encoder_input": None}
    original_run, original_collect = osy.run_worker, osy.collect_chunks

    def watched_run(*a, **k):
        run = original_run(*a, **k)
        seen["runs"].append({"terminal": run.terminal, "loaded": run.loaded, "chunk_events": run.chunk_events})
        return run

    def watched_collect(*a, **k):
        audio, rate = original_collect(*a, **k)
        seen["chunks"], seen["rate"] = [np.array(x) for x in audio], rate
        return audio, rate

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        pcm, rate = sf.read(str(wav), dtype="int16", always_2d=False)
        seen["encoder_input"] = {"rate": int(rate), "seconds": round(pcm.size / rate, 3),
                                 "full_scale_samples": int(np.count_nonzero((pcm == 32767) | (pcm == -32768)))}
        osy._encoder(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)

    work = ensure(RUNS / "s2" / "work")
    jobs, prompts = ensure(RUNS / "s2" / "jobs"), ensure(RUNS / "s2" / "prompts-unused")
    osy.run_worker, osy.collect_chunks = watched_run, watched_collect
    lines: list[str] = []
    started = time.monotonic()
    try:
        gvs._synthesize_omnivoice(voice, text, work / dest.name, log=lines.append, speech_prep=snap,
                                  availability=lambda _v: (True, ""), python=VENV_PY, script=WORKER, jobs_root=jobs,
                                  prompts_root=prompts, env=worker_env(), encoder=encoder)
        result = "PASS"
    except BaseException as exc:  # noqa: BLE001 - recorded
        result = f"{type(exc).__name__}: {exc}"
    finally:
        osy.run_worker, osy.collect_chunks = original_run, original_collect
    wall = time.monotonic() - started
    facts = {"cfg": cfg, "voice_id": voice_id, "result": result, "wall_s": round(wall, 2), "log": lines}
    if result == "PASS":
        shutil.move(str(work / dest.name), dest)
        seconds = seen["encoder_input"]["seconds"]
        events = [e for r in seen["runs"] for e in r["chunk_events"]]
        chunk_texts = [c.text for c in prepared_chunks(text, snap)]
        screens = [screen(a, seen["rate"], t) for a, t in zip(seen["chunks"], chunk_texts)]
        facts.update({
            "mp3": dest.name, "mp3_sha256": sha256_file(dest), "mp3_bytes": dest.stat().st_size,
            "audio_s": seconds, "rtf_wall": round(wall / seconds, 3),
            "rtf_inference": round(sum(e["gen_s"] for e in events) / sum(e["audio_s"] for e in events), 3),
            "chunks": len(events), "load_s": [r["loaded"].get("load_s") for r in seen["runs"]],
            "prompt_s": [r["loaded"].get("prompt_s") for r in seen["runs"]],
            "peak_footprint": max(r["terminal"].get("peak_footprint") or 0 for r in seen["runs"]),
            "mps_driver_max": max((e.get("mps_driver") or 0) for e in events) or None,
            "encoder_input": seen["encoder_input"], "chunk_screens": screens,
            "loaded": {k: seen["runs"][0]["loaded"].get(k) for k in ("parameter_devices", "parameter_dtypes",
                                                                    "tokenizer_device", "versions")},
            "network_attempts": [r["terminal"].get("network_attempts") for r in seen["runs"]],
        })
    return facts


def cmd_s2(args) -> int:
    from omnivoice_p4_acceptance import track_a_source, track_b_items, track_b_source  # the Windows-approved texts

    snap = snapshot()
    texts = {"A": track_a_source(), "B": track_b_source(track_b_items())}
    out = RUNS / "s2" / "s2.json"
    record = read_json(out) if out.is_file() else {"samples": {}}
    record["texts"] = {k: {"sha256": hashlib.sha256(v.encode()).hexdigest(), "chars": len(v)} for k, v in texts.items()}
    ensure(PACK)
    plan = [("A", v.voice_id, cfg) for v in ov.OMNIVOICE_VOICES for cfg in ("C1", args.mps)]
    plan += [("B", vid, args.mps) for vid in B_VOICES]
    if args.with_c3:
        plan += [("A", vid, "C3") for vid in C3_PACK_VOICES]
    for track, vid, cfg in plan:
        key = f"{track}-{vid}-{cfg}"
        if key in record["samples"] and record["samples"][key]["result"] == "PASS" and not args.redo:
            continue
        dest = PACK / "_unlabelled" / f"{key}.mp3"
        ensure(dest.parent)
        record["samples"][key] = {"track": track, **production_sample(cfg, vid, texts[track], dest, snap)}
        s = record["samples"][key]
        print(key, s["result"], s.get("audio_s"), s.get("rtf_wall"), s.get("peak_footprint"), flush=True)
        write_json(out, record)
    record["leftovers"] = leftovers()
    write_json(out, record)
    return 0


# --------------------------------------------------------------------------- #
# S3: stability (back-to-back generations in one process)
# --------------------------------------------------------------------------- #
def cmd_s3(args) -> int:
    voice, spec, reference = voice_reference("omnivoice-female-1")
    chunks = prepared_chunks(SOAK_TEXT, snapshot())
    out = RUNS / "s3" / "s3.json"
    record = read_json(out) if out.is_file() else {"runs": {}}
    for cfg, calls in ((args.mps, args.calls), ("C1", args.cpu_calls)):
        job_dir = RUNS / "s3" / cfg
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job = job_for(cfg, voice, spec, reference, chunks[:1], job_dir, mode="soak", calls=calls)
        r = supervise(job, job_dir)
        rows = [e for e in r["events"] if e["event"] == "call"]
        warm = rows[5:] if len(rows) > 6 else rows
        feet = [e["footprint"] for e in warm if e.get("footprint")]
        drv = [e["mps_driver"] for e in warm if e.get("mps_driver")]

        def growth(xs):
            if len(xs) < 2:
                return None
            slope = np.polyfit(np.arange(len(xs)), np.array(xs, dtype=float), 1)[0]
            return {"first": xs[0], "max": max(xs), "last": xs[-1], "max_vs_first_pct": round(100 * (max(xs) - xs[0])
                    / xs[0], 2), "trend_pct_over_run": round(100 * slope * (len(xs) - 1) / xs[0], 2)}

        rtf = [round(e["gen_s"] / e["audio_s"], 3) for e in rows if e.get("audio_s")]
        record["runs"][cfg] = {
            "calls_asked": calls, "calls_done": len(rows), "terminal": r["terminal"], "unsafe": r["unsafe"],
            "returncode": r["returncode"], "wall_s": r["wall_s"], "loaded": r["loaded"],
            "all_finite": all(e["finite"] for e in rows), "distinct_outputs": len({e["sha256"] for e in rows}),
            "rtf_first5": rtf[:5], "rtf_last5": rtf[-5:], "rtf_mean": round(float(np.mean(rtf)), 3) if rtf else None,
            "footprint_growth": growth(feet), "mps_driver_growth": growth(drv),
            "peak_footprint": max((e.get("peak_footprint") or 0) for e in rows) if rows else None,
            "external_peak_footprint": r["external_peak_footprint"], "memory_before": r["memory_before"],
            "memory_after": r["memory_after"], "group_left": r["group_left"],
            "calls": [{k: e.get(k) for k in ("index", "gen_s", "audio_s", "footprint", "mps_current", "mps_driver",
                                             "finite", "sha256")} for e in rows]}
        print(cfg, json.dumps({k: record["runs"][cfg][k] for k in ("calls_done", "all_finite", "distinct_outputs",
                                                                   "rtf_mean", "footprint_growth", "mps_driver_growth",
                                                                   "unsafe")}, default=str), flush=True)
        write_json(out, record)
    record["leftovers"] = leftovers()
    write_json(out, record)
    return 0


# --------------------------------------------------------------------------- #
# S4: termination while generation is active
# --------------------------------------------------------------------------- #
def cmd_s4(args) -> int:
    voice, spec, reference = voice_reference("omnivoice-female-1")
    chunks = prepared_chunks(HOLD_TEXT, snapshot())
    out = RUNS / "s4" / "s4.json"
    record = {"cases": {}}
    for cfg in args.configs:
        # (a) the raw signal path: SIGTERM to the group 3 s into the second chunk, SIGKILL if still there after 2 s
        job_dir = RUNS / "s4" / f"signal-{cfg}"
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job = job_for(cfg, voice, spec, reference, chunks, job_dir)
        state: dict = {}

        def on_event(event, proc, state=state):
            if event["event"] == "generating" and event.get("index") == 1 and "armed" not in state:
                state["armed"] = True

                def strike():
                    time.sleep(3.0)
                    state["memory_at_signal"] = system_memory()
                    state["footprint_at_signal"] = footprint_of(proc.pid)
                    state["sent"] = time.monotonic()
                    os.killpg(proc.pid, signal.SIGTERM)
                    deadline = state["sent"] + 2.0
                    while time.monotonic() < deadline and proc.poll() is None:
                        time.sleep(0.01)
                    if proc.poll() is None:
                        state["sigkill"] = True
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)
                    state["gone_s"] = round(time.monotonic() - state["sent"], 4)

                threading.Thread(target=strike, daemon=True).start()

        r = supervise(job, job_dir, on_event=on_event)
        time.sleep(3.0)
        chunk_files = sorted(p.name for p in (job_dir / "chunks").glob("*")) if (job_dir / "chunks").is_dir() else []
        record["cases"][f"signal-{cfg}"] = {
            "returncode": r["returncode"], "gone_s": state.get("gone_s"), "sigkill_needed": state.get("sigkill", False),
            "terminal": r["terminal"], "group_left": r["group_left"], "chunk_files": chunk_files,
            "partial_files": [n for n in chunk_files if n.endswith(".part")],
            "footprint_at_signal": state.get("footprint_at_signal"), "memory_at_signal": state.get("memory_at_signal"),
            "memory_3s_after": system_memory(), "memory_before": r["memory_before"], "leftovers": leftovers()}
        print(f"signal-{cfg}", json.dumps(record["cases"][f"signal-{cfg}"], default=str)[:600], flush=True)
        # (b) ACT's own supervisor: Cancel requested during the second chunk (flag, 2 s grace, then the group is killed)
        configure(cfg)
        job_dir = RUNS / "s4" / f"cancel-{cfg}"
        if job_dir.exists():
            shutil.rmtree(job_dir)
        ensure(job_dir)
        job = job_for(cfg, voice, spec, reference, chunks, job_dir)
        flag = {"t": None, "seen": 0}

        def on_chunk(_event):
            flag["seen"] += 1
            if flag["t"] is None:
                flag["t"] = time.monotonic() + 3.0  # request Cancel 3 s into the next chunk

        def cancel_check():
            return flag["t"] is not None and time.monotonic() >= flag["t"]

        started = time.monotonic()
        try:
            osy.run_worker(job, job_dir, name="job-001", python=VENV_PY, script=WORKER, env=worker_env(),
                           cancel_check=cancel_check, log=lambda _l: None, on_chunk=on_chunk)
            outcome = "finished (Cancel not honoured)"
        except BaseException as exc:  # noqa: BLE001
            outcome = type(exc).__name__
        ended = time.monotonic()
        record["cases"][f"cancel-{cfg}"] = {
            "outcome": outcome, "cancel_to_return_s": round(ended - flag["t"], 3) if flag["t"] else None,
            "chunks_before_cancel": flag["seen"], "wall_s": round(ended - started, 2),
            "chunk_files": sorted(p.name for p in (job_dir / "chunks").glob("*")) if (job_dir / "chunks").is_dir()
            else [], "leftovers": leftovers()}
        print(f"cancel-{cfg}", json.dumps(record["cases"][f"cancel-{cfg}"], default=str)[:600], flush=True)
        write_json(out, record)
    write_json(out, record)
    return 0


# --------------------------------------------------------------------------- #
# The blind-labelled pack and its index
# --------------------------------------------------------------------------- #
def cmd_pack(_args) -> int:
    s2 = read_json(RUNS / "s2" / "s2.json")
    rng = random.Random(20261116)
    rows, key = [], {}
    by_voice: dict = {}
    for k, s in s2["samples"].items():
        if s["result"] == "PASS":
            by_voice.setdefault((s["track"], s["voice_id"]), []).append(s)
    for (track, vid), samples in sorted(by_voice.items()):
        label = ov.get_voice(vid).label.replace("/", "-")
        letters = ["X", "Y", "Z"][: len(samples)]
        if track == "A":
            rng.shuffle(letters)
        for letter, s in zip(letters, samples):
            name = f"P4A-{track}-{label}-{letter}.mp3" if track == "A" else f"P4A-{track}-{label}.mp3"
            src = PACK / "_unlabelled" / s["mp3"]
            shutil.copy2(src, PACK / name)
            device, dtype = CONFIGS[s["cfg"]]
            # Everything that would reveal the device (speed, memory) lives only in the key, opened after listening.
            key[name] = {"configuration": s["cfg"], "device": device, "dtype": dtype, "rtf_wall": s["rtf_wall"],
                         "rtf_inference": s["rtf_inference"], "peak_footprint_gib": round(s["peak_footprint"] / GIB, 2),
                         "mps_driver_max_gib": round(s["mps_driver_max"] / GIB, 2) if s["mps_driver_max"] else None,
                         "chunks": s["chunks"], "full_scale_samples": s["encoder_input"]["full_scale_samples"]}
            rows.append({"file": name, "track": track, "voice_id": vid, "voice": ov.get_voice(vid).label,
                         "pair": f"{track}-{label}" if track == "A" else None, "sha256": sha256_file(PACK / name),
                         "bytes": (PACK / name).stat().st_size, "audio_s": s["audio_s"],
                         "screen_flags": sorted({f for c in s["chunk_screens"] for f in flags(c, None)}),
                         "owner_listening": "NOT YET REVIEWED"})
    rows.sort(key=lambda r: r["file"])
    key = dict(sorted(key.items()))
    write_json(PACK / "index.json", {"made": now(), "texts": s2["texts"], "generation": osy.GENERATION,
                                     "samples": rows})
    write_json(PACK / "key.json", key)
    lines = [
        "# ACT v0.8.x macOS P4A: OmniVoice listening pack",
        "",
        "Every verdict here is the owner's. **NOT YET REVIEWED** means nobody has listened yet. The automated screen checks "
        "only integrity (finite samples, clipping, silences, speaking rate, envelope and noise signatures); it is not a "
        "quality verdict. **WER: NOT RUN (no authorized ASR model; D15 deferred).**",
        "",
        "Engine: OmniVoice 0.2.1, model `k2-fsa/OmniVoice@c5fdb5cc`, torch 2.8.0, CPython 3.12.15, Apple M4 Pro, macOS "
        "27.0.1. ACT's production path: `v1` speech preparation, whole-sentence chunks of at most 300 characters, ACT's "
        "per-chunk seeds, the voice's own paragraph pause, one encode by ACT's production encoder (24 kHz mono MP3 at "
        "160 kbit/s: the sample route asks for 192k, which MPEG-2 Layer III caps at 160k at 24 kHz). Generation "
        "settings (unchanged): "
        + ", ".join(f"`{k}={v}`" for k, v in osy.GENERATION.items()) + ".",
        "",
        "**Blind comparison (track A):** each voice has files lettered `-X`, `-Y` (and `-Z` for Female 2 and Male 2). "
        "Every voice has one made on the CPU (fp32, the correctness reference) and one on the Apple GPU (MPS fp32); "
        "Female 2 and Male 2 also have one on the Apple GPU in half precision (MPS fp16). The letters are shuffled per "
        "voice. Listen first, then open `key.json`, which names each file's configuration with its speed and memory "
        "figures. Track B files are single multi-chunk samples (configuration in `key.json`).",
        "",
        "Texts (ACT's tracked quality corpus; the Windows-approved OmniVoice tracks use the same texts): "
        + "; ".join(f"{k}: {v['chars']} characters, SHA-256 `{v['sha256']}`" for k, v in s2["texts"].items()) + ".",
        "",
        "| File | Voice | Track | Compare with | Seconds | Screen | Owner listening |",
        "|---|---|---|---|--:|---|---|",
    ]
    for r in rows:
        screen_text = "; ".join(r["screen_flags"]) or "clean"
        lines.append(f"| `{r['file']}` | {r['voice']} | {r['track']} | {r['pair'] or '-'} | {r['audio_s']} | "
                     f"{screen_text} | {r['owner_listening']} |")
    lines += ["", "SHA-256 of each file:", ""] + [f"- `{r['file']}`: `{r['sha256']}`" for r in rows] + [
        "", "Licences: OmniVoice model weights CC-BY-NC (non-commercial; model card). Audio tokenizer: Boson Higgs Audio "
        "2 Community License. " + ov.TOKENIZER_ATTRIBUTION + " These samples are for the owner's listening review only.", ""]
    (PACK / "index.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(rows)} labelled MP3s in {PACK}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-files")
    sub.add_parser("create-env")
    sub.add_parser("verify-env")
    for name in ("s0", "s1", "s4"):
        p = sub.add_parser(name)
        p.add_argument("--configs", nargs="+", default=["C1", "C2", "C3"], choices=sorted(CONFIGS))
        p.add_argument("--redo", action="store_true")
    s2 = sub.add_parser("s2")
    s2.add_argument("--mps", default="C2", choices=("C2", "C3"))
    s2.add_argument("--with-c3", action="store_true")
    s2.add_argument("--redo", action="store_true")
    s3 = sub.add_parser("s3")
    s3.add_argument("--mps", default="C2", choices=("C2", "C3"))
    s3.add_argument("--calls", type=int, default=50)
    s3.add_argument("--cpu-calls", type=int, default=10)
    sub.add_parser("pack")
    args = parser.parse_args(argv)
    return {"verify-files": cmd_verify_files, "create-env": cmd_create_env, "verify-env": cmd_verify_env,
            "s0": cmd_s0, "s1": cmd_s1, "s2": cmd_s2, "s3": cmd_s3, "s4": cmd_s4, "pack": cmd_pack}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
