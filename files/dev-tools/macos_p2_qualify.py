"""Dev-only (v0.8.x P2): Edge E-A1..E-A4 and Kokoro E-B1..E-B3 qualification on macOS through ACT's production paths.

    <app python> files/dev-tools/macos_p2_qualify.py <command> --out <folder> [--pack <listening folder>]

Run from the checkout under test (P2: the disposable worktree holding the verified Kokoro files). Every synthesis goes
through the REAL ``TtsPanel`` and its Start path (``run_job``: the frozen run, the file workers, the engine route,
assembly, the one encode, publication), exactly as ``generate_voice_samples._run_voice_through_production`` does; on
macOS Kokoro therefore runs in the local-engine worker, under this process's containment owner (enabled as the app
window enables it). Settings, logs, runtime data and outputs point into ``--out`` (the app's module constants, as the
gate's drivers set them); the owner's Downloads output folder is fingerprinted before and after and must not change.

Commands:
  eb1          E-B1: one process imports torch, sklearn, numba, spaCy, kokoro and misaki.en, loads en_core_web_sm,
               runs each library once (an OpenMP clash would abort it) and the eSpeak NG fallback on 20 words no
               dictionary holds; then the eSpeak short-root logic from an app folder deep enough to overflow its
               160-byte buffer (and the negative control without it: the process is killed by the library).
  eb2          E-B2: KPipeline(model=False) phonemes for texts A, B and C, prepared (v1) and chunked as production
               does, American and British; text hashes and package identities. Writes the comparison file a
               Windows run of this same command is diffed against (``eb2-compare``).
  eb2-compare  Diff two eb2 records (Mac and Windows): identical phonemes, chunk by chunk, or the differences.
  voices       E-A2/E-B3: text A for all 14 Edge and Kokoro voices; Kokoro's short multi-chunk text for its nine; the B
               track for af_heart and en-US-SteffanNeural. RTF, load, memory, the automated correctness screen.
  chapter      E-B3: one >=30-minute real-book chapter with af_heart: RTF, cold/warm load, peak footprint and its
               growth after warm-up, output integrity. P5 (v0.8.0 closeout) options: ``--voice`` (any Kokoro or Edge
               voice), ``--whole`` (the whole book: text D), ``--chars`` (the excerpt's minimum length), ``--timeout``,
               ``--visible`` (the window is shown and raised instead of withdrawn: the plan's control; without it the
               window stays hidden), ``--hide-app`` (the application hides itself as Cmd+H does, so it is neither
               visible nor in front: the App Nap case), ``--label`` (the record's name). The 1 Hz sampler also reads
               this process's and the worker's CPU and scheduling priority, and whether the application is in front;
               the record gives each chunk's overhead (time between the worker's results less its inference time).
  edge-load    E-A1 and E-A3: the live voice list; 2 and 8 files at once with bounded inputs: requests, retries,
               403s, NoAudioReceived, throughput.
  edge-cancel  E-A4: Cancel with requests in flight (8 files), Cancel during finalization, Pause then Cancel:
               acknowledgement (C1 <= 0.5 s), stop (<= 2.5 s), no request after the latch, nothing unfinished published.
Never shipped. Outputs, audio and logs stay in the ignored folders named on the command line.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

EDGE = ["en-US-SteffanNeural", "en-US-AndrewNeural", "en-US-AriaNeural", "en-US-AvaNeural", "en-US-JennyNeural"]
KOKORO = ["af_heart", "af_bella", "am_michael", "am_fenrir", "am_puck", "am_onyx", "bf_emma", "bm_george", "bm_daniel"]
DOWNLOADS_OUTPUTS = Path.home() / "Downloads" / "Audiobook-Creation-Tool-Outputs"
OOD_WORDS = ["Zxqorvian", "brindlewhisk", "gloamtide", "Vexmorrow", "quillanthe", "Thaddrel", "skorvane", "mirrowend",
             "Ulbrecht", "fennimoor", "Kaerythos", "drelmspire", "Oszwalde", "plinthcrow", "Yrsenna", "hobbleknap",
             "Grautheim", "sylphrine", "Ccraeg", "wenderloft"]


# --------------------------------------------------------------------------- shared
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def downloads_fingerprint() -> dict:
    """The owner's default output folder: count and a digest of (path, size, mtime) -- must not change."""
    if not DOWNLOADS_OUTPUTS.exists():
        return {"exists": False}
    rows = []
    for path in sorted(DOWNLOADS_OUTPUTS.rglob("*")):
        with contextlib.suppress(OSError):
            st = path.lstat()
            rows.append(f"{path.relative_to(DOWNLOADS_OUTPUTS)}|{st.st_size}|{st.st_mtime_ns}")
    return {"exists": True, "entries": len(rows), "digest": sha256_text("\n".join(rows))}


def isolate(out: Path) -> Path:
    """The app's settings, logs and runtime data into ``out/runtime``; outputs into ``out/outputs`` (as the gate's
    drivers do). The checkout's proved FFmpeg record is copied in, so the pinned pair is the one used."""
    from shared import config as shared_config
    from shared import ffmpeg_health, output_paths, paths
    from shared import settings as app_settings

    runtime, outputs = out / "runtime", out / "outputs"
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    paths.RESOURCES_DIR = runtime
    paths.LOGS_DIR = runtime / "logs"
    paths.SETTINGS_FILE = runtime / "settings.json"
    ffmpeg_health.RESOURCES_DIR = runtime
    state = ROOT / "files" / "runtime-data" / ffmpeg_health.HEALTH_STATE_NAME
    if state.is_file():
        shutil.copyfile(state, runtime / ffmpeg_health.HEALTH_STATE_NAME)
    (runtime / "settings.json").write_text(json.dumps({"output_base_directory": str(outputs), "last_tool": "tts"}),
                                           encoding="utf-8")
    app_settings.use_path(runtime / "settings.json")
    shared_config.invalidate()
    output_paths.resolve_output_base = lambda effective=None: outputs  # belt and braces: never the owner's folder
    return outputs


def contain():
    """This process becomes a containment owner, as the app window does at start (``launcher``)."""
    from shared import subprocess_utils

    return subprocess_utils.enable_containment()


def environment_facts() -> dict:
    from importlib import metadata

    facts = {"python": sys.version.split()[0], "executable": sys.executable, "root": str(ROOT)}
    for name in ("torch", "kokoro", "misaki", "spacy", "en_core_web_sm", "scikit-learn", "numba", "llvmlite",
                 "numpy", "espeakng-loader", "phonemizer-fork", "edge-tts", "aiohttp"):
        try:
            facts[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            facts[name] = None
    with contextlib.suppress(Exception):
        facts["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                           text=True).stdout.strip()
    with contextlib.suppress(Exception):
        facts["macos"] = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip()
        facts["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                      text=True).stdout.strip()
        facts["memory_bytes"] = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                                   text=True).stdout.strip())
        facts["power"] = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout.strip()[:200]
    return facts


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- texts
def texts() -> dict:
    import omnivoice_p4_acceptance as p4  # tracks A and B of v0.8.0, read from the tracked sources verbatim
    from tts import quality_corpus

    return {"A": p4.track_a_source(), "B": p4.track_b_source(p4.track_b_items()),
            "C": quality_corpus.SUSTAINED_NARRATION.text}


def chapter_text(minimum_chars: int | None = 33000) -> tuple[str, dict]:
    """A real book's opening, cut at a paragraph end once it holds ``minimum_chars`` (at Kokoro's measured pace, more
    than 30 minutes): Re:Monster volume 1 through ACT's own PDF extractor. Local only; never committed.
    ``minimum_chars=None``: the whole book (P5's text D)."""
    from tts.pdf_extractor import pdf_to_txt

    source = ROOT / "files" / "test-files" / "Re_Monster - Volume 01.pdf"
    if not source.is_file():
        source = Path(__file__).resolve().parents[1] / "test-files" / "Re_Monster - Volume 01.pdf"
    scratch = Path(os.environ.get("TMPDIR", "/tmp")) / f"act-p2-chapter-{os.getpid()}.txt"
    pdf_to_txt(str(source), str(scratch))
    whole = scratch.read_text(encoding="utf-8")
    scratch.unlink()
    paragraphs, total, kept = whole.split("\n\n"), 0, []
    for paragraph in paragraphs:
        kept.append(paragraph)
        total += len(paragraph) + 2
        if minimum_chars is not None and total >= minimum_chars:
            break
    text = "\n\n".join(kept).strip()
    return text, {"source": str(source), "source_sha256": sha256_file(source), "chars": len(text),
                  "text_sha256": sha256_text(text), "paragraphs": len(kept), "whole_book": minimum_chars is None,
                  "book_chars": len(whole.strip()), "book_paragraphs": len(paragraphs)}


# --------------------------------------------------------------------------- the real panel
class PanelRun:
    """One run of the real TTS panel, as the GUI performs it (``generate_voice_samples`` precedent)."""

    def __init__(self, root, voice_id: str, sources: list[Path], *, workers: int | None = None):
        from tts import epub2tts_gui as panel_module
        from tts.voice_registry import VOICES

        self.root = root
        self.voice = next(v for v in VOICES if v.voice_id == voice_id)
        chosen = tuple(str(p) for p in sources)
        self.panel = panel_module.TtsPanel(root, choose_files=lambda: chosen)
        self.transcript: list[str] = []
        show = self.panel._append_engine_output

        def recording(payload, *args, **kwargs):
            self.transcript.extend(str(payload).splitlines())
            return show(payload, *args, **kwargs)

        self.panel._append_engine_output = recording
        self.panel.importer.add_files()
        if not self.pump_until(lambda: len(self.panel._manager.snapshot().files) == len(sources), 30):
            raise RuntimeError("the sources were not listed")
        self.panel.selected_voice_label.set(self.voice.display_label)
        self.panel._on_voice_selected()
        if workers is not None:
            self.panel.workers_var.set(str(workers))
        self.worker = None
        self.started = None

    def tick(self) -> None:
        self.panel._pump.tick()
        self.root.update()

    def pump_until(self, predicate, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.tick()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def start(self) -> None:
        self.started = time.monotonic()
        self.panel.run_job()
        self.worker = self.panel._worker  # the run's thread (run_job itself returns nothing)
        if self.worker is None:
            raise RuntimeError("the Start button refused the run")

    def state(self):
        controller = self.panel._controller
        return None if controller is None else controller.state

    def finish(self, timeout: float) -> dict:
        done = self.pump_until(lambda: not self.worker.is_alive(), timeout)
        for _ in range(40):
            self.tick()
        result = self.panel._result
        return {"finished": done, "state": result.state.value if result is not None else str(self.state()),
                "wall_s": round(time.monotonic() - self.started, 2),
                "destinations": {str(e.source): str(e.destination) for e in self.panel.destinations().values()},
                "options": {k: v for k, v in self.panel._snapshot.tool_options.items()
                            if k in ("backend", "voice_id", "rate", "bitrate", "workers", "kokoro_speed",
                                     "end_pause", "paragraph_pause")}}

    def close(self) -> None:
        self.panel.close()


def hide_application() -> dict:
    """What Cmd+H does: the application hides itself (``[NSApp hide:nil]``, on the Tk thread, through the Objective-C
    runtime; no permission is involved and nothing outside this process is touched). A withdrawn window alone can leave
    the process the frontmost application, which App Nap never naps."""
    import ctypes
    import ctypes.util

    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    send.restype = ctypes.c_void_p
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    app = send(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"), None)
    send(app, objc.sel_registerName(b"hide:"), None)
    send.restype = ctypes.c_bool
    hidden = bool(send(app, objc.sel_registerName(b"isHidden"), None))
    active = bool(send(app, objc.sel_registerName(b"isActive"), None))
    return {"isHidden": hidden, "isActive": active}


def app_state(pid: int) -> str:
    """``lsappinfo``'s line for this process (front or not, type), read-only."""
    text = subprocess.run(["lsappinfo", "info", "-all", str(pid)], capture_output=True, text=True).stdout
    for block in text.split("\n\n"):
        if f"pid = {pid} " in block:
            return " ".join(line.strip() for line in block.splitlines()[:1] + [l for l in block.splitlines() if "pid =" in l])
    return ""


def tk_root(visible: bool = False):
    """The harness's root. Hidden (withdrawn) by default; ``visible``: shown at a normal size and raised, as a person's
    window is during a run (the plan's control for the long-form runs; hidden is the App Nap case)."""
    import tkinter as tk

    root = tk.Tk()
    if visible:
        root.geometry("1120x800")
        root.deiconify()
        root.lift()
        root.update()
    else:
        root.withdraw()
    return root


def host_events(since: float = 0.0) -> list:
    """The current worker host's events seen at or after ``since`` (monotonic). By time, never by index: a new panel
    whose first voice belongs to another engine releases the warm worker, so a run may be served by a new host."""
    from tts import local_engine_host as hosts

    host = hosts.current_host()
    return [] if host is None else [event for event in list(host.history) if event.at >= since]


def screen(path: Path, chars: int) -> dict:
    """ACT's automated correctness screen for one produced file (decode, durations, loudness, clipping, silences)."""
    from tts import generate_voice_samples as gvs

    measured = gvs.measure_final_artifact(path)
    problems, derived = gvs.judge_final_artifact(measured, chars)
    return {"measured": measured, "derived": derived, "problems": problems, "sha256": sha256_file(path)}


# --------------------------------------------------------------------------- E-B1
EB1_IMPORTS = r"""
import ctypes, json, sys, time
began = time.monotonic()
import torch, sklearn, numba, spacy, kokoro
import misaki.en
from sklearn.linear_model import LinearRegression
import numpy as np
LinearRegression().fit(np.arange(10.0).reshape(-1, 1), np.arange(10.0))
@numba.njit
def add(a, b):
    return a + b
add(1, 2)
torch.ones(4, 4) @ torch.ones(4, 4)
nlp = spacy.load("en_core_web_sm")
doc = nlp("Dr. Smith read 3 pages.")
libc = ctypes.CDLL(None)
libc._dyld_image_count.restype = ctypes.c_uint32
libc._dyld_get_image_name.restype = ctypes.c_char_p
images = [libc._dyld_get_image_name(i).decode() for i in range(libc._dyld_image_count())]
omp = sorted({p for p in images if "omp" in p.rsplit("/", 1)[-1].lower()})
g2p = misaki.en.G2P(trf=False, british=False, fallback=None)
from misaki import espeak
fallback = espeak.EspeakFallback(british=False)
words = json.loads(sys.argv[1])
rows = []
for word in words:
    phonemes, tokens = g2p(word)
    via_dictionary = all(t.phonemes for t in tokens)
    spoken, rating = fallback(tokens[0]) if tokens else (None, None)
    rows.append({"word": word, "dictionary": phonemes if via_dictionary else None, "espeak": spoken, "rating": rating})
print(json.dumps({"seconds": round(time.monotonic() - began, 2), "torch": torch.__version__, "omp": omp,
                  "torch_threads": torch.get_num_threads(), "spacy_doc": [t.text for t in doc], "words": rows}))
"""

EB1_DEEP = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
deep_data, use_fix = sys.argv[2], sys.argv[3] == "1"
import espeakng_loader
espeakng_loader.get_data_path = lambda: deep_data      # the deep app folder's own copy of the bundled data
from shared import espeak_data, paths
from pathlib import Path
paths.RESOURCES_DIR = Path(sys.argv[4])
root = espeak_data.configure() if use_fix else None
from misaki import espeak
from phonemizer.backend.espeak.wrapper import EspeakWrapper
reported = str(EspeakWrapper().data_path)
fallback = espeak.EspeakFallback(british=False)
from misaki.en import MToken
token = MToken(text="Zxqorvian", tag="NNP", whitespace="")
print(json.dumps({"deep_data_chars": len(deep_data), "configured_root": root, "espeak_reported_path": reported,
                  "phonemes": fallback(token)[0]}))
"""


EB1_OPENMP = r"""
import json, sys, ctypes
order = sys.argv[1]
import numpy as np
def sk():
    from sklearn.cluster import KMeans
    KMeans(n_clusters=8, n_init=1, random_state=0).fit(np.random.RandomState(0).rand(20000, 8))
def th():
    import torch
    a = torch.randn(1500, 1500)
    (a @ a).sum()
    torch.nn.functional.conv1d(torch.randn(4, 64, 24000), torch.randn(64, 64, 9))
    return torch.get_num_threads()
def nb():
    import numba
    @numba.njit(parallel=True)
    def total(x):
        s = 0.0
        for i in numba.prange(x.shape[0]):
            s += x[i]
        return s
    total(np.arange(1_000_000.0))
    return numba.threading_layer()
steps = {"sklearn-then-torch": (sk, th, nb), "torch-then-sklearn": (th, sk, nb)}[order]
results = [step() for step in steps]
import threadpoolctl
libc = ctypes.CDLL(None)
libc._dyld_image_count.restype = ctypes.c_uint32
libc._dyld_get_image_name.restype = ctypes.c_char_p
images = [libc._dyld_get_image_name(i).decode() for i in range(libc._dyld_image_count())]
print(json.dumps({"order": order, "libomp_images": sorted(p for p in images if p.endswith("libomp.dylib")),
                  "threadpools": [{k: v for k, v in info.items() if k in ("user_api", "internal_api", "prefix",
                                   "filepath", "num_threads", "version")} for info in threadpoolctl.threadpool_info()],
                  "numba_threading_layer": results[-1]}))
"""


def cmd_eb1(out: Path) -> dict:
    record: dict = {"environment": environment_facts()}
    proc = subprocess.run([sys.executable, "-I", "-c", EB1_IMPORTS, json.dumps(OOD_WORDS)], capture_output=True,
                          text=True, timeout=600, cwd=str(SCRIPTS))
    record["imports"] = {"returncode": proc.returncode, "stderr_tail": proc.stderr[-1500:]}
    if proc.returncode == 0:
        record["imports"].update(json.loads(proc.stdout.strip().splitlines()[-1]))
    words = record["imports"].get("words", [])
    record["espeak_fallback"] = {"words": len(words), "all_spoken": all(w.get("espeak") for w in words),
                                 "none_in_dictionary": all(not w.get("dictionary") for w in words)}
    # The deep app folder: a path to the same bundled data, through a directory chain long enough that eSpeak NG's
    # 160-byte buffer cannot hold it. A link to the wheel's own data (never a copy), as espeak_data itself makes.
    import espeakng_loader

    real = Path(espeakng_loader.get_data_path())
    deep_parent = out / "deep" / ("a-deep-application-folder-" * 4) / ("nested-" * 6)
    deep_parent.mkdir(parents=True, exist_ok=True)
    deep_data = deep_parent / "espeak-ng-data"
    # A physical copy (19 MB, in this ignored scratch): phonemizer resolves links, so only a real deep folder is a deep
    # install's view. The wheel's own data stays the only source the app ever uses.
    if deep_data.is_symlink():
        deep_data.unlink()
    if not deep_data.exists():
        shutil.copytree(real, deep_data)
    runs = {}
    for label, use_fix, resources in (("with the short root", "1", out / "deep-runtime"),
                                      ("runtime data too deep as well (temp root)", "1",
                                       deep_parent / ("runtime-" * 10)),
                                      ("negative control: no short root", "0", out / "deep-runtime-nc")):
        Path(resources).mkdir(parents=True, exist_ok=True)
        private_temp = out / "deep-temp"  # the temp-root case links here, never in the shared system temp folder
        private_temp.mkdir(exist_ok=True)
        run = subprocess.run([sys.executable, "-I", "-c", EB1_DEEP, str(SCRIPTS), str(deep_data), use_fix,
                              str(resources)], capture_output=True, text=True, timeout=300, cwd=str(SCRIPTS),
                             env={**os.environ, "TMPDIR": str(private_temp)})
        row = {"returncode": run.returncode, "stderr_tail": run.stderr[-600:], "resources_chars": len(str(resources))}
        if run.returncode == 0 and run.stdout.strip():
            row.update(json.loads(run.stdout.strip().splitlines()[-1]))
        runs[label] = row
    record["deep_path"] = {"real_data_path_chars": len(str(real)), "deep_data_path_chars": len(str(deep_data)),
                           "runs": runs}
    record["openmp"] = []
    for order in ("sklearn-then-torch", "torch-then-sklearn"):
        run = subprocess.run([sys.executable, "-I", "-c", EB1_OPENMP, order], capture_output=True, text=True,
                             timeout=600, cwd=str(SCRIPTS))
        row = {"order": order, "returncode": run.returncode, "stderr_tail": run.stderr[-800:]}
        if run.returncode == 0 and run.stdout.strip():
            row.update(json.loads(run.stdout.strip().splitlines()[-1]))
        record["openmp"].append(row)
    # The real worker: what it loads once the model is built and a chunk is spoken (lsof of its mapped files).
    from tts import local_engine_host as hosts

    host = hosts.WorkerHost("kokoro", sample_rate=24000, log=lambda s: None)
    try:
        began = time.monotonic()
        loaded = host.load({"lang_code": "a"})
        cold = time.monotonic() - began
        pcm = host.synthesize({"text": "Zxqorvian brindlewhisk gloamtide, said Dr. Marsh at 6:45.", "voice": "af_heart",
                               "speed": 1.0, "split_pattern": r"\n+", "seed": None}).pcm
        mapped = subprocess.run(["lsof", "-p", str(host.pid)], capture_output=True, text=True).stdout
        record["worker"] = {"hello": host.hello, "loaded": loaded, "cold_start_to_loaded_s": round(cold, 3),
                            "samples": int(pcm.size), "finite": bool(np.isfinite(pcm).all()),
                            "libomp_mapped": sorted({line.split()[-1] for line in mapped.splitlines()
                                                     if line.rstrip().endswith("libomp.dylib")}),
                            "sklearn_mapped": any("/sklearn/" in line for line in mapped.splitlines()),
                            "numba_mapped": any("/numba/" in line for line in mapped.splitlines())}
    finally:
        host.close("eb1 over")
    return record


# --------------------------------------------------------------------------- E-B2
def cmd_eb2(out: Path) -> dict:
    from importlib import metadata

    from kokoro import KPipeline
    from tts import kokoro_synth as ks
    from tts.speech.pipeline import build_snapshot, prepare
    from tts.speech.profiles import KOKORO

    from shared import espeak_data

    snapshot = build_snapshot("v1", user_dir=None)
    espeak_data.configure()
    record: dict = {"environment": environment_facts(), "speech_prep": snapshot.speech_prep_version,
                    "packages": {}, "texts": {}}
    for name in ("kokoro", "misaki", "spacy", "en_core_web_sm", "espeakng-loader", "phonemizer-fork", "torch"):
        try:
            dist = metadata.distribution(name)
            record_text = dist.read_text("RECORD") or ""
            record["packages"][name] = {"version": dist.version, "record_sha256": sha256_text(record_text)}
        except metadata.PackageNotFoundError:
            record["packages"][name] = None
    for lang in ("a", "b"):
        pipeline = KPipeline(lang_code=lang, model=False)
        for name, text in texts().items():
            prepared = prepare(text, snapshot, KOKORO).text
            chunks = ks.split_into_chunks(prepared)
            rows = []
            for chunk in chunks:
                rows.append({"chunk_sha256": sha256_text(chunk), "chars": len(chunk),
                             "segments": [{"graphemes": g, "phonemes": p}
                                          for g, p, _a in pipeline(chunk, split_pattern=ks.SPLIT_PATTERN)]})
            record["texts"][f"{name}-{lang}"] = {"source_sha256": sha256_text(text),
                                                 "prepared_sha256": sha256_text(prepared), "chunks": rows,
                                                 "phonemes_sha256": sha256_text(json.dumps(
                                                     [[s["phonemes"] for s in r["segments"]] for r in rows]))}
    return record


def cmd_eb2_compare(first: Path, second: Path) -> dict:
    a, b = json.loads(first.read_text(encoding="utf-8")), json.loads(second.read_text(encoding="utf-8"))
    result = {"first": str(first), "second": str(second), "packages": {}, "texts": {}}
    for name in sorted(set(a["packages"]) | set(b["packages"])):
        pa, pb = a["packages"].get(name) or {}, b["packages"].get(name) or {}
        result["packages"][name] = {"first": pa.get("version"), "second": pb.get("version"),
                                    "same_version": pa.get("version") == pb.get("version")}
    for key in sorted(set(a["texts"]) | set(b["texts"])):
        ta, tb = a["texts"].get(key), b["texts"].get(key)
        if ta is None or tb is None:
            result["texts"][key] = "missing on one side"
            continue
        same_input = ta["prepared_sha256"] == tb["prepared_sha256"]
        diffs = []
        for index, (ca, cb) in enumerate(zip(ta["chunks"], tb["chunks"])):
            for s_index, (sa, sb) in enumerate(zip(ca["segments"], cb["segments"])):
                if sa["phonemes"] != sb["phonemes"]:
                    diffs.append({"chunk": index, "segment": s_index, "graphemes": sa["graphemes"][:80],
                                  "first": sa["phonemes"], "second": sb["phonemes"]})
        result["texts"][key] = {"same_prepared_input": same_input, "identical": ta["phonemes_sha256"] ==
                                tb["phonemes_sha256"], "differences": diffs[:50]}
    result["verdict"] = ("IDENTICAL" if all(isinstance(v, dict) and v["identical"] for v in result["texts"].values())
                         else "DIFFERENT")
    return result


# --------------------------------------------------------------------------- E-A2 / E-B3: voices
def _kokoro_metrics(events: list, decoded_s: float) -> dict:
    results = [e for e in events if e.name == "result"]
    loads = [e for e in events if e.name == "loaded"]
    gen = sum(float(e.detail.get("gen_s") or 0) for e in results)
    peaks = [int(e.detail["peak_footprint"]) for e in results + loads if e.detail.get("peak_footprint")]
    feet = [int(e.detail["footprint"]) for e in results if e.detail.get("footprint")]
    return {"chunks": len(results), "inference_s": round(gen, 3),
            "rtf_inference": round(gen / decoded_s, 4) if decoded_s else None,
            "loads": [{"load_s": e.detail.get("load_s"), "cached": e.detail.get("cached")} for e in loads],
            "peak_footprint_bytes": max(peaks) if peaks else None, "footprints_bytes": feet,
            # P5: the worker's lifetime peak after each chunk (where a long run's peak was reached)
            "peak_footprints_bytes": [int(e.detail["peak_footprint"]) for e in results if e.detail.get("peak_footprint")]}


def run_voice(root, voice_id: str, name: str, text: str, folder: Path, *, timeout: float = 3600) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / f"{name}.txt"
    source.write_text(text, encoding="utf-8")
    since = time.monotonic()
    run = PanelRun(root, voice_id, [source], workers=1)
    try:
        run.start()
        result = run.finish(timeout)
    finally:
        run.close()
    produced = Path(result["destinations"][str(source)])
    row = {"voice": voice_id, "text": name, "text_sha256": sha256_text(text), "chars": len(text), **result,
           "output": str(produced), "transcript_tail": run.transcript[-12:]}
    if produced.is_file():
        row["screen"] = screen(produced, len(text))
        decoded = row["screen"]["measured"].get("decoded_s") or 0.0
        row["rtf_wall"] = round(result["wall_s"] / decoded, 4) if decoded else None
        if voice_id in KOKORO:
            row["kokoro"] = _kokoro_metrics(host_events(since), decoded)
    return row


def cmd_voices(out: Path, pack: Path | None, only: list[str] | None) -> dict:
    isolate(out)
    owner = contain()
    root = tk_root()
    corpus = texts()
    rows = []
    plan = [(v, "A") for v in EDGE + KOKORO] + [(v, "C") for v in KOKORO] + [("af_heart", "B"),
                                                                           ("en-US-SteffanNeural", "B")]
    if only:
        plan = [(v, t) for v, t in plan if v in only or f"{v}:{t}" in only]
    try:
        for voice, track in plan:
            print(f"[voices] {voice} {track}", flush=True)
            rows.append(run_voice(root, voice, f"{track}-{voice}", corpus[track], out / "sources"))
            write(out / "voices.json", {"environment": environment_facts(), "texts": {
                k: {"sha256": sha256_text(v), "chars": len(v)} for k, v in corpus.items()}, "rows": rows})
    finally:
        root.destroy()
        from tts import local_engine_host as hosts

        hosts.release("qualification over")
        if owner is not None:
            owner.shutdown()
    if pack is not None:
        pack.mkdir(parents=True, exist_ok=True)
        for row in rows:
            if Path(row["output"]).is_file():
                target = pack / f"{row['text'][:1]}-{row['voice']}.mp3"
                shutil.copyfile(row["output"], target)
                row["pack_file"] = str(target)
    # The final record keeps what the running one held (the run's packages and machine, and each text's identity).
    return {"environment": environment_facts(), "texts": {k: {"sha256": sha256_text(v), "chars": len(v)}
                                                          for k, v in corpus.items()}, "rows": rows}


# --------------------------------------------------------------------------- E-B3: the chapter
def _chunk_overheads(events: list) -> dict:
    """Per chunk: the time between one result and the next less the next chunk's inference time (the parent's share:
    the request, the hand-back, the pump). App Nap would stretch this, not the worker's inference."""
    results = [e for e in events if e.name == "result"]
    gaps = [round((b.at - a.at) - float(b.detail.get("gen_s") or 0), 4) for a, b in zip(results, results[1:])]
    if not gaps:
        return {"count": 0}
    ordered = sorted(gaps)
    return {"count": len(gaps), "median_s": ordered[len(ordered) // 2], "max_s": ordered[-1], "total_s": round(sum(gaps), 3),
            "p90_s": ordered[int(0.9 * (len(ordered) - 1))]}


def cmd_chapter(out: Path, *, voice: str = "af_heart", whole: bool = False, chars: int = 33000,
                timeout: float = 7200, visible: bool = False, label: str | None = None, hide_app: bool = False) -> dict:
    isolate(out)
    owner = contain()
    root = tk_root(visible)
    hidden = None
    if hide_app:
        root.update()
        hidden = hide_application()
        root.update()
    text, identity = chapter_text(None if whole else chars)
    from tts import local_engine_host as hosts

    hosts.release("a cold start for the chapter")
    sampler_stop = threading.Event()
    samples: list[dict] = []
    me = os.getpid()

    def sample() -> None:  # 1 Hz: the worker's and this process's footprint from outside, swap and thermal state
        from tts import worker_limits

        while not sampler_stop.is_set():
            host = hosts.current_host()
            row = {"t": time.monotonic()}
            if host is not None and host.pid:
                with contextlib.suppress(Exception):
                    row["rss_kb"] = int(subprocess.run(["ps", "-o", "rss=", "-p", str(host.pid)], capture_output=True,
                                                       text=True).stdout.strip() or 0)
            with contextlib.suppress(Exception):
                rss, cpu, pri = subprocess.run(["ps", "-o", "rss=,pcpu=,pri=", "-p", str(me)], capture_output=True,
                                               text=True).stdout.split()
                row["parent_rss_kb"], row["parent_cpu"], row["parent_pri"] = int(rss), float(cpu), int(pri)
            if host is not None and host.pid:
                with contextlib.suppress(Exception):
                    cpu, pri = subprocess.run(["ps", "-o", "pcpu=,pri=", "-p", str(host.pid)], capture_output=True,
                                              text=True).stdout.split()
                    row["worker_cpu"], row["worker_pri"] = float(cpu), int(pri)
            if len(samples) % 30 == 0:  # every 30 s: is this application in front, as App Nap sees it
                with contextlib.suppress(Exception):
                    row["app_state"] = app_state(me)
            with contextlib.suppress(Exception):
                row["swap"] = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True,
                                             text=True).stdout.strip()
            with contextlib.suppress(Exception):
                info = worker_limits.memory_info()
                row["available_bytes"] = info.available if info else None
            samples.append(row)
            sampler_stop.wait(1.0)

    threading.Thread(target=sample, daemon=True).start()
    name = label or f"chapter-{voice}"
    since = time.monotonic()
    row: dict = {}
    recorder = EdgeRecorder() if voice in EDGE else None  # every Edge request: count, outcome, 403, NoAudioReceived
    try:
        row = run_voice(root, voice, name, text, out / "sources", timeout=timeout)
        if recorder is not None:
            row["edge_requests"] = recorder.summary()
            spans = [r["end"] - r["start"] for r in recorder.rows if "end" in r]
            row["edge_requests"]["request_s"] = {"median": round(sorted(spans)[len(spans) // 2], 3),
                                                 "max": round(max(spans), 3), "total": round(sum(spans), 1)} if spans else None
        row["chunk_overheads"] = _chunk_overheads(host_events(since)) if voice in KOKORO else None
        row["window"] = {"visible_requested": visible, "viewable_at_end": bool(root.winfo_viewable()),
                         "state_at_end": str(root.state()), "hide_app": hide_app, "hidden_at_start": hidden,
                         "app_state_at_end": app_state(me)}
    finally:
        if recorder is not None:
            recorder.restore()
        sampler_stop.set()
        root.destroy()
        with contextlib.suppress(Exception):
            row["thermal"] = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True).stdout[-400:]
        hosts.release("chapter over")
        if owner is not None:
            owner.shutdown()
    feet = row.get("kokoro", {}).get("footprints_bytes") or []
    if len(feet) >= 4:
        warm = feet[1]  # after the first chunk (the warm-up)
        row["growth_after_warmup"] = round((max(feet[1:]) - warm) / warm, 4)
        row["last_vs_warm"] = round((feet[-1] - warm) / warm, 4)
        if len(feet) >= 3:  # the least-squares trend over the post-warm-up chunks, as a fraction of the warm figure
            xs = list(range(len(feet) - 1))
            ys = feet[1:]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1)
            row["fitted_trend_over_run"] = round(slope * (len(feet) - 2) / warm, 4)
    parents = [s["parent_rss_kb"] for s in samples if s.get("parent_rss_kb")]
    row["parent_peak_rss_kb"] = max(parents) if parents else None
    return {"environment": environment_facts(), "chapter": identity, "row": row, "samples": samples}


# --------------------------------------------------------------------------- Edge: instrumentation
class EdgeRecorder:
    """Every request ACT's Edge route makes (``epub2tts_edge.run_save``): when, how long, and how it ended."""

    def __init__(self) -> None:
        from tts.epub2tts_edge import epub2tts_edge as engine

        self.engine = engine
        self.real = engine.run_save
        self.rows: list[dict] = []
        self.lock = threading.Lock()

        def run_save(communicate, filename, cancel_check=None):
            row = {"start": time.monotonic(), "thread": threading.current_thread().name}
            with self.lock:
                self.rows.append(row)
            try:
                self.real(communicate, filename, cancel_check)
                row["outcome"] = "ok"
            except BaseException as exc:
                row["outcome"] = type(exc).__name__
                row["detail"] = str(exc)[:200]
                raise
            finally:
                row["end"] = time.monotonic()

        engine.run_save = run_save

    def restore(self) -> None:
        self.engine.run_save = self.real

    def summary(self, since: float | None = None) -> dict:
        rows = [r for r in self.rows if since is None or r["start"] >= since]
        outcomes: dict = {}
        for row in rows:
            outcomes[row.get("outcome", "running")] = outcomes.get(row.get("outcome", "running"), 0) + 1
        details = " ".join(r.get("detail", "") for r in rows)
        return {"requests": len(rows), "outcomes": outcomes, "http_403": details.count("403"),
                "no_audio_received": sum(1 for r in rows if r.get("outcome") == "NoAudioReceived")}


def edge_sources(folder: Path, count: int, chars: int = 600) -> list[Path]:
    """Bounded inputs: ``count`` files of about ``chars`` characters of the quality corpus, each distinct."""
    from tts import quality_corpus

    sentences = re.split(r"(?<=[.!?])\s+", quality_corpus.LONGER_STRESS.text.replace("\n\n", " "))
    folder.mkdir(parents=True, exist_ok=True)
    made, cursor = [], 0
    for number in range(1, count + 1):
        body = []
        while sum(len(s) + 1 for s in body) < chars:
            body.append(sentences[cursor % len(sentences)])
            cursor += 1
        path = folder / f"Edge File {number:02d}.txt"
        path.write_text(" ".join(body), encoding="utf-8")
        made.append(path)
    return made


def edge_voice_list() -> dict:
    import asyncio

    import edge_tts

    began = time.monotonic()
    voices = asyncio.run(edge_tts.list_voices())
    names = {v.get("ShortName") for v in voices}
    return {"seconds": round(time.monotonic() - began, 2), "listed": len(voices),
            "registered_present": {v: v in names for v in EDGE}, "all_present": all(v in names for v in EDGE)}


def cmd_edge_load(out: Path) -> dict:
    isolate(out)
    owner = contain()
    record: dict = {"environment": environment_facts()}
    try:
        record["E-A1"] = edge_voice_list()
    except Exception as exc:  # noqa: BLE001 - a service that cannot be reached is BLOCKED, not a defect
        record["E-A1"] = {"blocked": f"{type(exc).__name__}: {exc}"}
    root = tk_root()
    recorder = EdgeRecorder()
    try:
        for count in (2, 8):
            sources = edge_sources(out / f"in-{count}", count)
            since = time.monotonic()
            run = PanelRun(root, "en-US-SteffanNeural", sources, workers=count)
            try:
                run.start()
                result = run.finish(900)
            finally:
                run.close()
            outputs = [Path(result["destinations"][str(s)]) for s in sources]
            audio_s = 0.0
            screens = {}
            for path in outputs:
                if path.is_file():
                    screened = screen(path, len(Path(sources[outputs.index(path)]).read_text()))
                    screens[path.name] = {"problems": screened["problems"],
                                          "decoded_s": screened["measured"]["decoded_s"]}
                    audio_s += screened["measured"]["decoded_s"] or 0.0
            transcript = "\n".join(run.transcript)
            record[f"E-A3-{count}"] = {
                **result, "published": sum(1 for p in outputs if p.is_file()), "files": count,
                "requests": recorder.summary(since), "retries_logged": len(re.findall(r"Attempt \d/3 failed",
                                                                                      transcript)),
                "workers_line": [line for line in run.transcript if "worker" in line.lower()][:4],
                "audio_s": round(audio_s, 2), "throughput_audio_s_per_s": round(audio_s / result["wall_s"], 3),
                "screens": screens}
            write(out / "edge-load.json", record)
    finally:
        recorder.restore()
        root.destroy()
        if owner is not None:
            owner.shutdown()
    return record


# --------------------------------------------------------------------------- E-A4: Edge Cancel
def _cancel_and_time(run: PanelRun, *, bound: float = 2.5) -> dict:
    from shared.job_control import JobState

    clicked = time.monotonic()
    run.panel.cancel_job()
    latched = run.state() in (JobState.CANCEL_REQUESTED, JobState.CANCELLED)
    acknowledged = None
    while time.monotonic() - clicked < 30:
        run.tick()
        if acknowledged is None and run.state() in (JobState.CANCEL_REQUESTED, JobState.CANCELLED) \
                and "Cancel" in run.panel.jobs.status.status_text:
            acknowledged = time.monotonic() - clicked
        if run.state() is JobState.CANCELLED and not run.worker.is_alive():
            break
        time.sleep(0.005)
    stopped = time.monotonic() - clicked
    return {"clicked": clicked, "latched_at_click": latched, "c1_ack_s": None if acknowledged is None else round(
        acknowledged, 4), "c2_stop_s": round(stopped, 4), "state": str(run.state()),
        "c1_pass": acknowledged is not None and acknowledged <= 0.5, "c2_pass": stopped <= bound}


def cmd_edge_cancel(out: Path) -> dict:
    from shared.job_control import JobState

    outputs = isolate(out)
    owner = contain()
    root = tk_root()
    recorder = EdgeRecorder()
    record: dict = {"environment": environment_facts()}
    try:
        # 1. Cancel with requests in flight: 8 files, 8 workers, longer inputs.
        sources = edge_sources(out / "in-flight", 8, chars=2400)
        before = set(outputs.rglob("*.mp3"))
        run = PanelRun(root, "en-US-SteffanNeural", sources, workers=8)
        try:
            run.start()
            run.pump_until(lambda: sum(1 for r in recorder.rows if "end" not in r) >= 2, 120)
            in_flight = sum(1 for r in recorder.rows if "end" not in r)
            timing = _cancel_and_time(run)
            settled = len(recorder.rows)
            time.sleep(2.0)
            after_latch = [r for r in recorder.rows if r["start"] > timing["clicked"]]
            record["in-flight"] = {**timing, "in_flight_at_click": in_flight, "requests_total": settled,
                                   "requests_after_latch": len(after_latch),
                                   "requests_after_settle": len(recorder.rows) - settled,
                                   "published": sorted(str(p) for p in set(outputs.rglob("*.mp3")) - before)}
        finally:
            run.close()
        # 2. Cancel during finalization: pressed the moment a file's publication starts.
        from tts import publication

        real_publish = publication.publish_file
        pressed = {}

        sources = edge_sources(out / "finalize", 1, chars=600)
        before = set(outputs.rglob("*.mp3"))
        run = PanelRun(root, "en-US-SteffanNeural", sources, workers=1)

        def publish(finished, destination, **kwargs):
            # The file is finished and its publication begins: the worker waits here until Cancel is pressed (by the
            # main thread, as a click is), then publication runs under the latch.
            if not pressed:
                pressed["at"] = time.monotonic()
                deadline = time.monotonic() + 10.0
                while run.state() is not JobState.CANCEL_REQUESTED and time.monotonic() < deadline:
                    time.sleep(0.005)
            return real_publish(finished, destination, **kwargs)

        publication.publish_file = publish
        try:
            run.start()
            run.pump_until(lambda: "at" in pressed or not run.worker.is_alive(), 300)
            if "at" in pressed:
                pressed["timing"] = _cancel_and_time(run)
            run.pump_until(lambda: not run.worker.is_alive(), 30)
            published = sorted(str(p) for p in set(outputs.rglob("*.mp3")) - before)
            record["finalization"] = {**pressed.get("timing", {"note": "publication never began"}),
                                      "published": published,
                                      "whole_if_published": [screen(Path(p), 600)["problems"] for p in published]}
        finally:
            publication.publish_file = real_publish
            run.close()
        # 3. Pause, then Cancel: one worker, two files.
        sources = edge_sources(out / "pause", 2, chars=1500)
        before = set(outputs.rglob("*.mp3"))
        run = PanelRun(root, "en-US-SteffanNeural", sources, workers=1)
        try:
            since = time.monotonic()
            run.start()
            run.pump_until(lambda: any(r["start"] >= since for r in recorder.rows), 60)
            run.panel.pause()
            paused = run.pump_until(lambda: run.state() is JobState.PAUSED, 300)
            first = sorted(set(outputs.rglob("*.mp3")) - before)
            digests = {str(p): sha256_file(p) for p in first}
            requests_while_paused = len(recorder.rows)
            time.sleep(1.5)
            idle = len(recorder.rows) - requests_while_paused
            timing = _cancel_and_time(run)
            after = sorted(set(outputs.rglob("*.mp3")) - before)
            record["pause-then-cancel"] = {**timing, "paused": paused, "published_before_cancel": [str(p) for p in first],
                                           "requests_while_paused": idle, "published_after": [str(p) for p in after],
                                           "first_intact": all(sha256_file(Path(p)) == d for p, d in digests.items())}
        finally:
            run.close()
    finally:
        recorder.restore()
        root.destroy()
        if owner is not None:
            owner.shutdown()
    return record


# --------------------------------------------------------------------------- main
def _row_problems(label: str, row: dict) -> list[str]:
    """What, in one produced file's row, means it is not a good result: the job, the file, or the screen."""
    problems = []
    if not row.get("finished", False):
        problems.append(f"{label}: the run did not finish")
    if row.get("state") != "succeeded":
        problems.append(f"{label}: the job ended {row.get('state')!r}, not 'succeeded'")
    output = row.get("output")
    if not output or not Path(output).is_file():
        problems.append(f"{label}: no output file")
    screened = row.get("screen")
    if not isinstance(screened, dict):
        problems.append(f"{label}: the output was not screened")
    elif screened.get("problems"):
        problems.append(f"{label}: the screen found {screened['problems']}")
    return problems


def command_problems(command: str, record: dict) -> list[str]:
    """v0.8.x P5-H-R1 (Codex MEDIUM 1): what in the command's own record means it did not pass. ``main`` used to return 0 on
    the Downloads guard alone, so a failed chapter or a DIFFERENT E-B2 comparison exited 0. ``eb2`` and ``edge-cancel`` are
    captures read by a person or by ``eb2-compare``: a capture that completes has nothing of its own to fail on."""
    if command == "eb2-compare":
        return [] if record.get("verdict") == "IDENTICAL" else [f"E-B2 comparison verdict {record.get('verdict')!r}"]
    if command == "chapter":
        return _row_problems("chapter", record.get("row") or {})
    if command == "voices":
        rows = record.get("rows") or []
        return [problem for row in rows for problem in _row_problems(f"{row.get('voice')} {row.get('text')}", row)] or (
            [] if rows else ["no voice was run"])
    if command == "edge-load":
        problems = []
        for key, value in record.items():
            if not key.startswith("E-A3-") or not isinstance(value, dict):
                continue
            if not value.get("finished") or value.get("state") != "succeeded":
                problems.append(f"{key}: the job ended {value.get('state')!r}")
            if value.get("published") != value.get("files"):
                problems.append(f"{key}: {value.get('published')} of {value.get('files')} files published")
            problems += [f"{key} {name}: the screen found {screened['problems']}"
                         for name, screened in (value.get("screens") or {}).items() if screened.get("problems")]
        return problems
    if command == "eb1":
        imports = record.get("imports") or {}
        problems = [] if imports.get("returncode") == 0 else [f"eb1: the imports exited {imports.get('returncode')}"]
        if not (record.get("espeak_fallback") or {}).get("all_spoken"):
            problems.append("eb1: not every out-of-dictionary word was spoken")
        if "worker" in record and not record["worker"].get("finite"):
            problems.append("eb1: the worker's audio is not finite")
        return problems
    return []


def exit_status(record_run: dict) -> int:
    """0: passed. 3: Downloads changed (the guard, as before, whatever else happened). 4: the command's own result failed."""
    if not record_run["downloads_unchanged"]:
        return 3
    return 0 if not record_run["problems"] else 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["eb1", "eb2", "eb2-compare", "voices", "chapter", "edge-load",
                                            "edge-cancel"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--first", type=Path)
    parser.add_argument("--second", type=Path)
    parser.add_argument("--voice", default="af_heart", help="chapter: the voice (Kokoro or Edge)")
    parser.add_argument("--whole", action="store_true", help="chapter: the whole book (text D)")
    parser.add_argument("--chars", type=int, default=33000, help="chapter: the excerpt's minimum length")
    parser.add_argument("--timeout", type=float, default=7200, help="chapter: seconds before the run is abandoned")
    parser.add_argument("--visible", action="store_true", help="chapter: show the window (default: hidden)")
    parser.add_argument("--label", help="chapter: the source/record name")
    parser.add_argument("--hide-app", action="store_true", help="chapter: the application hides itself (Cmd+H) at start")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    downloads_before = downloads_fingerprint()
    began = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.command == "eb1":
        record = cmd_eb1(out)
    elif args.command == "eb2":
        record = cmd_eb2(out)
    elif args.command == "eb2-compare":
        record = cmd_eb2_compare(args.first, args.second)
    elif args.command == "voices":
        record = cmd_voices(out, args.pack, args.only)
    elif args.command == "chapter":
        record = cmd_chapter(out, voice=args.voice, whole=args.whole, chars=args.chars, timeout=args.timeout,
                             visible=args.visible, label=args.label, hide_app=args.hide_app)
    elif args.command == "edge-load":
        record = cmd_edge_load(out)
    else:
        record = cmd_edge_cancel(out)
    downloads_after = downloads_fingerprint()
    record["run"] = {"command": args.command, "began": began, "ended": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "downloads_before": downloads_before, "downloads_after": downloads_after,
                     "downloads_unchanged": downloads_before == downloads_after}
    record["run"]["problems"] = command_problems(args.command, record)
    record["run"]["outcome"] = "PASS" if not record["run"]["problems"] else "FAIL"
    write(out / f"{args.command}.json", record)
    print(json.dumps(record["run"], indent=1))
    return exit_status(record["run"])


if __name__ == "__main__":
    sys.exit(main())
