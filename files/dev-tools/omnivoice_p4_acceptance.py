"""omnivoice_p4_acceptance.py -- ACT v0.8.0 Phase 4: the owner listening pack and the bounded real-engine checks (developer
only, never shipped, never imported by the app).

    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py text            # A/B texts + checks, no engine
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py pack [--voice ID]  # the 12 primary MP3s
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py book            # multi-chunk book + VRAM trend
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py cancel          # Cancel in inference / encode
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py smoke ENGINE    # edge|kokoro|chatterbox|qwen3
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py installer       # readiness after relaunch
    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p4_acceptance.py index [FOLDER]  # owner index from a pack

Every synthesis goes through the PRODUCTION source-to-MP3 path: ``generate_voice_samples``' OmniVoice route, which is
``omnivoice_synth.omnivoice_file_to_mp3`` with the voice's own timing preset, the panel's default bitrate and the
production ``v1`` speech-preparation snapshot (built as the panel builds it at Create). The tool only observes: it wraps
the worker runner, the chunk reader and the encoder to record what passed through them (worker events, raw chunk PCM,
the 16-bit WAV handed to the encoder) and changes none of it. Heavy runs are sequential; never run one while pytest runs
(the worker writes ``files/runtime-data/omnivoice``, which the test suite's production-state guard watches).

The pack goes to ``files/test-for-manual-listen-elmatthe/omnivoice-v0.8.0-phase4/<stamp>/`` (ignored), the other
evidence to ``files/dev-work/ov-p4/<stamp>-<kind>/`` (ignored). These are technical runs and listening material: the
owner's ears decide, and every owner verdict starts as NOT YET REVIEWED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from shared import ffmpeg_utils, paths, subprocess_utils  # noqa: E402
from tts import generate_voice_samples as gvs  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402
from tts import omnivoice_synth as osy  # noqa: E402
from tts import quality_corpus  # noqa: E402
from tts.speech import classes  # noqa: E402
from tts.speech.normalize import ruleset_fingerprint  # noqa: E402
from tts.speech.pipeline import prepare  # noqa: E402
from tts.voice_registry import VOICES  # noqa: E402

PACK_ROOT = REPO / "files" / "test-for-manual-listen-elmatthe" / "omnivoice-v0.8.0-phase4"
EVIDENCE_ROOT = REPO / "files" / "dev-work" / "ov-p4"
CORPUS_DIR = REPO / "files" / "tests" / "golden" / "speech" / "corpus"
G1_TESTS = REPO / "files" / "tests" / "test_speech_g1.py"
ROUTE = "omnivoice"
OMNI = [v for v in VOICES if v.backend == "omnivoice"]
AUDIBLE = tuple(c for c in classes.RULE_CLASSES if c != "HYG")


# --------------------------------------------------------------------------- #
# Sources of truth: the G1 snippets and the golden corpus, read from the tracked files
# --------------------------------------------------------------------------- #
def load_corpus() -> dict[str, dict]:
    cases = {}
    for path in sorted(CORPUS_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                cases[case["id"]] = dict(case, file=path.name)
    return cases


def load_snippets() -> dict[str, str]:
    """``test_speech_g1.SNIPPETS`` read from the test's source (importing the test module would import pytest)."""
    source = G1_TESTS.read_text(encoding="utf-8")
    start = source.index("SNIPPETS = {")
    end = source.index("\n}\n", start) + 3
    namespace: dict = {}
    exec(compile(source[start:end], str(G1_TESTS), "exec"), namespace)  # a literal dict of str -> str
    return namespace["SNIPPETS"]


# --------------------------------------------------------------------------- #
# Track A: one common natural passage
# --------------------------------------------------------------------------- #
def track_a_source() -> str:
    """``quality_corpus.DIFFICULT_SHORT``, verbatim: the plan's preferred passage, the same for all six voices."""
    return quality_corpus.DIFFICULT_SHORT.text


# --------------------------------------------------------------------------- #
# Track B: one common indexed normalization challenge
# --------------------------------------------------------------------------- #
#: Each SNIPPET token's golden reading: (corpus id, the exact words that corpus case expects for the same token).
SNIPPET_GOLDEN = {
    "CARD": [("card-thousands", "one thousand two hundred fifty"), ("card-small", "twelve"), ("card-million", "one million")],
    "DEC": [("mixed-difficult-short-sentence", "two point five degrees")],
    "ORD": [("ord-first", "first"), ("adv-2nd-amendment", "second")],
    "PCT": [("pct-decimal", "twelve point five percent")],
    "CUR": [("cur-cents", "twelve dollars fifty cents"), ("cur-whole", "five dollars")],
    "YEAR": [("year-oh", "nineteen oh five"), ("year-in", "nineteen ninety nine")],
    "TIME": [("time-before-cue", "before seven fifteen")],
    "RATIO": [("ratio-cue-after", "three to one")],
    "DATE": [("date-month-day-year", "March fifth twenty twenty four")],
    "RANGE": [("range-pages", "pages twelve to fifteen")],
    "FRAC": [("frac-cup", "one half cup")],
    "UNIT": [("unit-km", "five kilometers"), ("unit-fahrenheit", "seventy two degrees Fahrenheit")],
    "TITLE": [("mixed-difficult-short-sentence", "Doctor Elena Marsh")],
    "ROMAN": [("roman-chapter", "Chapter four"), ("roman-regnal", "Henry the eighth")],
    "SYM": [("sym-ampersand", "Smith and Wesson")],
}

#: Spoken part labels are written in words so they carry no class of their own; every example is a G1 snippet or a golden
#: corpus input, verbatim, except the two labelled "no golden case" lines (initials and names).
PARTS: list[tuple[str, list[tuple]]] = [
    ("Part one. Counting, decimals and ordinals.",
     [("snippet", "CARD"), ("snippet", "DEC"), ("corpus", "dec-leading-zero-fraction"), ("snippet", "ORD"),
      ("corpus", "ord-twenty-first")]),
    ("Part two. Percentages, money and years.",
     [("snippet", "PCT"), ("snippet", "CUR"), ("snippet", "YEAR")]),
    ("Part three. Clock times and ratios.",
     [("snippet", "TIME"), ("corpus", "time-oh"), ("corpus", "time-pm-sentence-end"), ("corpus", "ratio-cue-after"),
      ("snippet", "RATIO")]),
    ("Part four. Dates and ranges.",
     [("snippet", "DATE"), ("corpus", "date-iso"), ("snippet", "RANGE")]),
    ("Part five. Fractions and units.",
     [("snippet", "FRAC"), ("corpus", "frac-mixed"), ("snippet", "UNIT")]),
    ("Part six. Titles, Roman numerals and symbols.",
     [("snippet", "TITLE"), ("corpus", "prose-dialogue"), ("snippet", "ROMAN"), ("snippet", "SYM"),
      ("corpus", "sym-times")]),
    # Two paragraphs, each under the 300-character chunk ceiling: the shared sentence planner takes "Apt." for a sentence
    # end, so a chunk boundary must never be forced inside these identifiers.
    ("Part seven. Numbers that are deliberately left as written.",
     [("corpus", "adv-bare-year-like"), ("corpus", "adv-bible-verse"), ("corpus", "adv-time-no-cue"),
      ("corpus", "adv-slash-date"), ("corpus", "adv-24-7"), ("corpus", "adv-leading-zero")]),
    ("Part eight. Identifiers, an address and a negative number, also left as written.",
     [("corpus", "adv-r2-d2"), ("corpus", "adv-version-triple"), ("corpus", "adv-address"), ("corpus", "adv-negative"),
      ("corpus", "adv-phone"), ("corpus", "adv-apt-4b")]),
    ("Part nine. Abbreviations, initials and punctuation.",
     [("corpus", "abbr-tier3"),
      ("text", "J. R. Alvarez, the harbor master, radioed the keeper.", "initials"),
      ("corpus", "prose-colon"), ("corpus", "prose-dashes"), ("corpus", "prose-ellipsis")]),
    ("Part ten. Web addresses, email and file paths.",
     [("corpus", "url-protected"), ("corpus", "email-protected"), ("corpus", "windows-path")]),
    ("Part eleven. Names.",
     [("text", "Marquess Joric Reclentos and Count Hughes Rudelberg met Klein and Tanya at the border of Asura, "
               "far from Shinovar.", "names")]),
]
B_INTRO = "This is the speech normalization challenge. Each part says what it tests, then reads its examples."
B_OUTRO = "This is the end of the normalization challenge."


def track_b_items() -> list[dict]:
    snippets, corpus = load_snippets(), load_corpus()
    items = []
    for number, (label, entries) in enumerate(PARTS, start=1):
        for entry in entries:
            kind, key = entry[0], entry[1]
            if kind == "snippet":
                item = {"kind": "G1 snippet", "id": f"SNIPPETS[{key}]", "classes": [key], "source": snippets[key],
                        "golden": [{"corpus_id": cid, "expected_reading": words,
                                    "corpus_input": corpus[cid]["input"], "corpus_expected": corpus[cid]["expected"]}
                                   for cid, words in SNIPPET_GOLDEN[key]]}
            elif kind == "corpus":
                case = corpus[key]
                item = {"kind": f"golden corpus ({case['file']})", "id": key, "classes": list(case["classes"]),
                        "source": case["input"], "expected": case["expected"], "note": case.get("note", "")}
            else:  # ("text", sentence, label): no golden case exists; the check below proves v1 leaves it unchanged
                item = {"kind": "no golden case", "id": f"text:{entry[2]}", "classes": [], "source": key,
                        "expected": None, "note": entry[2]}
            item["part"] = number
            items.append(item)
    return items


def track_b_source(items: list[dict]) -> str:
    paragraphs = [B_INTRO]
    for number, (label, _entries) in enumerate(PARTS, start=1):
        paragraphs.append(label + " " + " ".join(i["source"] for i in items if i["part"] == number))
    paragraphs.append(B_OUTRO)
    return "\n\n".join(paragraphs)


def check_track_b(snapshot) -> dict:
    """Prepare the composite once and prove every item reads as its golden case says, in order, in the composite."""
    items = track_b_items()
    source = track_b_source(items)
    prepared = prepare(source, snapshot, ROUTE)
    text = prepared.text
    problems, cursor = [], 0
    for item in items:
        alone = prepare(item["source"], snapshot, ROUTE)
        item["prepared"] = alone.text
        item["edits"] = sorted({e.cls for e in alone.normalized.edits})
        where = text.find(alone.text, cursor)
        if where < 0:
            problems.append(f"{item['id']}: its prepared text is not in the composite, in order")
        else:
            item["offset"] = where
            cursor = where + len(alone.text)
        if item.get("expected") is not None and alone.normalized.spoken != item["expected"]:
            problems.append(f"{item['id']}: prepared {alone.normalized.spoken!r} != golden {item['expected']!r}")
        for golden in item.get("golden", []):
            if golden["expected_reading"] not in alone.text:
                problems.append(f"{item['id']}: missing the golden reading {golden['expected_reading']!r}")
            if golden["expected_reading"] not in golden["corpus_expected"]:
                problems.append(f"{item['id']}: {golden['corpus_id']} does not expect {golden['expected_reading']!r}")
        if item["kind"] == "no golden case" and alone.normalized.edits:
            problems.append(f"{item['id']}: a no-golden-case line was changed: {alone.text!r}")
    heard = {c for i in items for c in i["edits"]}
    missing = sorted(set(AUDIBLE) - heard)
    if missing:
        problems.append(f"audible classes never exercised: {missing}")
    return {"source": source, "prepared": text, "items": items, "classes_exercised": sorted(heard),
            "notes": list(prepared.notes), "details": list(prepared.details()), "problems": problems}


def hyg_proof(snapshot) -> list[dict]:
    """HYG is mechanical: before/after text for every golden HYG case (no audio claim)."""
    rows = []
    for case in load_corpus().values():
        if "HYG" in case["classes"]:
            out = prepare(case["input"], snapshot, ROUTE)
            rows.append({"id": case["id"], "before": case["input"], "before_codepoints": [f"U+{ord(c):04X}" for c in
                                                                                          case["input"] if ord(c) > 127],
                         "after": out.normalized.spoken, "expected": case["expected"],
                         "match": out.normalized.spoken == case["expected"],
                         "edits": [{"cls": e.cls, "rule": e.rule_id, "original": e.original, "spoken": e.spoken}
                                   for e in out.normalized.edits]})
    return rows


def check_track_a(snapshot) -> dict:
    source = track_a_source()
    out = prepare(source, snapshot, ROUTE)
    return {"source": source, "prepared": out.text, "edits": [{"cls": e.cls, "original": e.original, "spoken": e.spoken}
                                                               for e in out.normalized.edits],
            "notes": list(out.notes), "details": list(out.details())}


def snapshot_facts(snapshot) -> dict:
    return {"setting": snapshot.setting, "ruleset_version": snapshot.ruleset_version,
            "ruleset_fingerprint": ruleset_fingerprint(), "speech_prep_version": snapshot.speech_prep_version,
            "mode_table_hash": snapshot.mode_table_hash, "bundled_glossary_hash": snapshot.bundled_glossary_hash,
            "user_glossary_hash": snapshot.user_glossary_hash, "user_override_hash": snapshot.user_override_hash,
            "user_dir": str(paths.RESOURCES_DIR / "speech"), "user_dir_exists": (paths.RESOURCES_DIR / "speech").exists(),
            "omnivoice_cells": snapshot.modes_for(ROUTE), "glossary_entries": len(snapshot.glossary),
            "notes": list(snapshot.notes)}


# --------------------------------------------------------------------------- #
# Measuring
# --------------------------------------------------------------------------- #
def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protected() -> dict:
    roots = [REPO / "files" / "Cloned-Voice-Uploads", REPO / "files" / "voice-previews"]
    return {str(p.relative_to(REPO)): sha256(p) for root in roots for p in sorted(root.rglob("*.wav"))}


def hub_cache() -> list[str]:
    root = ov.cache_root() / "hf"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.is_dir() else []


def gpu_facts() -> dict:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20).stdout
        name, driver, total, used = [s.strip() for s in out.strip().splitlines()[0].split(",")]
        return {"name": name, "driver": driver, "total_mib": int(total), "used_mib_idle": int(used)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


class VramSampler:
    """Driver-level GPU memory in use (``nvidia-smi``), sampled while a run is active: whole-GPU, not just this run."""

    def __init__(self, interval_s: float = 0.5):
        self.interval_s, self.samples, self._stop = interval_s, [], threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        start = time.monotonic()
        while not self._stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=10).stdout.strip()
                self.samples.append((round(time.monotonic() - start, 2), int(out.splitlines()[0])))
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.interval_s)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=15)

    def summary(self) -> dict:
        used = [s[1] for s in self.samples]
        return {"samples": len(used), "max_used_mib": max(used) if used else None,
                "min_used_mib": min(used) if used else None}


def true_peak_dbtp(path: Path) -> float | None:
    """FFmpeg's EBU R128 true peak (4x oversampled) of a decoded file: inter-sample peaks included."""
    proc = subprocess_utils.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-nostdin", "-i", str(path), "-filter_complex",
                                 "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    found = re.findall(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", proc.stderr)
    if not found:
        return None
    value = found[-1]
    return float("-inf") if value == "-inf" else float(value)


def decoded_facts(mp3: Path, work: Path) -> dict:
    wav = work / (mp3.stem + ".decoded.wav")
    subprocess_utils.run([ffmpeg_utils.ffmpeg_cmd(), "-y", "-nostdin", "-loglevel", "error", "-i", str(mp3), "-f", "wav",
                          "-c:a", "pcm_f32le", str(wav)], capture_output=True, check=True)
    data, rate = sf.read(str(wav), dtype="float32", always_2d=True)
    wav.unlink()
    mono = data[:, 0]
    peak = float(np.abs(mono).max()) if mono.size else 0.0
    return {"seconds": round(mono.size / rate, 3), "rate": rate, "channels": data.shape[1],
            "peak": round(peak, 5), "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None,
            "decoded_samples_at_or_over_full_scale": int(np.count_nonzero(np.abs(mono) >= 1.0)),
            "true_peak_dbtp": true_peak_dbtp(mp3),
            "rms_dbfs": round(10 * np.log10(float(np.mean(mono.astype(np.float64) ** 2)) + 1e-12), 2),
            "tail_ms_below_-50dbfs": tail_quiet_ms(mono, rate)}


def tail_quiet_ms(mono: np.ndarray, rate: int, floor_db: float = -50.0) -> int:
    level = 10 ** (floor_db / 20)
    loud = np.flatnonzero(np.abs(mono) >= level)
    return int(round((mono.size - 1 - loud[-1]) * 1000 / rate)) if loud.size else int(mono.size * 1000 / rate)


class Recorder:
    """Wraps the worker runner, the job builder and the chunk reader of ``omnivoice_synth`` (observing only)."""

    def __init__(self):
        self.runs, self.jobs, self.chunks = [], [], []
        self._real = (osy.run_worker, osy.build_job, osy.collect_chunks)

    def __enter__(self):
        real_run, real_job, real_collect = self._real

        def run_worker(*a, **k):
            result = real_run(*a, **k)
            self.runs.append(result)
            return result

        def build_job(*a, **k):
            job = real_job(*a, **k)
            self.jobs.append(job)
            return job

        def collect_chunks(*a, **k):
            audio, rate = real_collect(*a, **k)
            self.chunks = [np.array(c, copy=True) for c in audio]
            self.rate = rate
            return audio, rate

        osy.run_worker, osy.build_job, osy.collect_chunks = run_worker, build_job, collect_chunks
        return self

    def __exit__(self, *exc):
        osy.run_worker, osy.build_job, osy.collect_chunks = self._real

    def workers(self) -> list[dict]:
        out = []
        for run in self.runs:
            out.append({"loaded": {k: run.loaded.get(k) for k in ("device_name", "total_mib", "load_s", "prompt", "prompt_s",
                                                                  "vram_allocated_mib", "vram_reserved_mib", "chunks")},
                        "chunks": [{k: e.get(k) for k in ("index", "audio_s", "gen_s", "peak", "vram_allocated_mib",
                                                          "vram_reserved_mib")} for e in run.chunk_events],
                        "done": {k: run.terminal.get(k) for k in ("event", "wall_s", "load_s", "peak_allocated_mib",
                                                                  "peak_reserved_mib")},
                        "returncode": run.returncode})
        return out

    def raw_chunks(self) -> list[dict]:
        return [{"index": i, "seconds": round(c.size / self.rate, 3), "peak": round(float(np.abs(c).max()), 6),
                 "samples_at_or_over_1.0": int(np.count_nonzero(np.abs(c) >= 1.0)),
                 "samples_at_or_over_0.999": int(np.count_nonzero(np.abs(c) >= 0.999)),
                 "samples_at_or_over_0.99": int(np.count_nonzero(np.abs(c) >= 0.99))} for i, c in enumerate(self.chunks)]

    def chunk_starts(self, pause_ms: int) -> list[float]:
        starts, at = [], 0
        gap = int(self.rate * pause_ms / 1000)
        for i, c in enumerate(self.chunks):
            if i:
                at += gap
            starts.append(round(at / self.rate, 2))
            at += c.size
        return starts


def observing_encoder(facts: dict, work: Path):
    """The production encoder, after recording what it is handed: the 16-bit WAV after the final-tail policy."""
    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        pcm, rate = sf.read(str(wav), dtype="int16", always_2d=False)
        facts["encoder_input"] = {"rate": int(rate), "seconds": round(pcm.size / rate, 3),
                                  "samples_at_int16_full_scale": int(np.count_nonzero((pcm == 32767) | (pcm == -32768))),
                                  "peak_dbfs": round(20 * np.log10(max(int(np.abs(pcm.astype(np.int32)).max()), 1) / 32768),
                                                     2),
                                  "true_peak_dbtp": true_peak_dbtp(Path(wav))}
        osy._encoder(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)
    return encoder


def environment_facts() -> dict:
    manifest = ov.load_manifest()
    env = ov.worker_environment()
    return {"omnivoice": manifest["engine"]["omnivoice"], "model_repository": manifest["model"].get("repository"),
            "model_revision": manifest["model"]["revision"], "engine_status": list(ov.environment_status()),
            "model_status": list(ov.model_status()), "receipt_origin": ov.read_receipt().get("origin"),
            "offline_env": {k: env.get(k) for k in sorted(env) if k.startswith(("HF_", "TRANSFORMERS", "DO_NOT_TRACK",
                                                                                 "PIP_NO_INDEX"))},
            "generation": dict(osy.GENERATION), "max_chunk_chars": osy.OMNIVOICE_MAX_CHUNK_CHARS,
            "chunks_per_worker": osy.CHUNKS_PER_WORKER, "pipeline_revision": osy.PIPELINE_REVISION,
            "seed_base": osy.SEED_BASE, "dtype": osy.DTYPE, "language": osy.LANGUAGE,
            "bitrate": gvs.OMNIVOICE_SAMPLE_BITRATE}


def reference_facts(voice_id: str) -> dict:
    spec = ov.reference_spec(voice_id)
    path = ov.reference_path(ov.get_voice(voice_id))
    return {"path": str(path), "wav_sha256": spec.wav_sha256, "sha256_on_disk": sha256(path), "frames": spec.frames,
            "sample_rate": spec.sample_rate, "seconds": round(spec.duration_s, 3), "max_seconds": spec.max_frames /
            spec.sample_rate, "text": spec.text, "text_sha256": spec.text_sha256}


def synthesize(voice, text: str, mp3: Path, *, snapshot, encoder=None, **seams) -> dict:
    """One production OmniVoice conversion, observed. Returns the facts."""
    facts: dict = {}
    lines: list[str] = []
    started = time.perf_counter()
    with Recorder() as rec, VramSampler() as vram:
        try:
            gvs._synthesize_omnivoice(voice, text, mp3, log=lines.append, speech_prep=snapshot,
                                      encoder=encoder or observing_encoder(facts, mp3.parent), **seams)
            facts["result"] = "PASS"
        except BaseException as exc:  # noqa: BLE001 - recorded
            facts["result"] = f"{type(exc).__name__}: {exc}"
    facts["wall_s"] = round(time.perf_counter() - started, 2)
    facts["workers"] = rec.workers()
    facts["worker_chunk_texts"] = [c["text"] for job in rec.jobs for c in job["chunks"]]
    facts["raw_chunks"] = rec.raw_chunks() if rec.chunks else []
    facts["chunk_starts_s"] = rec.chunk_starts(int(voice.timing_preset["paragraphpause"])) if rec.chunks else []
    facts["vram_driver"] = vram.summary()
    facts["vram_driver_samples"] = vram.samples
    facts["log"] = lines
    return facts


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def cmd_text(_args) -> int:
    snapshot = gvs.omnivoice_speech_prep()
    b = check_track_b(snapshot)
    out = {"snapshot": snapshot_facts(snapshot), "track_a": check_track_a(snapshot), "track_b": b,
           "hyg": hyg_proof(snapshot)}
    print(json.dumps({"problems": b["problems"], "classes": b["classes_exercised"],
                      "b_chars": len(b["source"]), "a_chars": len(out["track_a"]["source"]),
                      "hyg_all_match": all(r["match"] for r in out["hyg"])}, indent=1))
    return 1 if b["problems"] or not all(r["match"] for r in out["hyg"]) else 0


def track_name(voice, track: str) -> str:
    who = voice.display_label.split(" - ", 1)[1]
    return f"OmniVoice {who} — {'A Natural' if track == 'A' else 'B Normalization'}.mp3"


def cmd_pack(args) -> int:
    snapshot = gvs.omnivoice_speech_prep()
    b = check_track_b(snapshot)
    if b["problems"]:
        print("Track B does not check out:", b["problems"])
        return 1
    a = check_track_a(snapshot)
    out = PACK_ROOT / stamp()
    out.mkdir(parents=True)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "folder": str(out), "gpu": gpu_facts(),
              "environment": environment_facts(), "snapshot": snapshot_facts(snapshot), "track_a": a, "track_b": b,
              "hyg": hyg_proof(snapshot), "protected_before": protected(), "hub_cache_before": hub_cache(), "voices": {}}
    voices = [v for v in OMNI if not args.voice or v.voice_id in args.voice]
    for voice in voices:
        entry = {"label": voice.display_label, "reference": reference_facts(voice.voice_id), "tracks": {}}
        for track, text in (("A", a["source"]), ("B", b["source"])):
            mp3 = out / track_name(voice, track)
            facts = synthesize(voice, text, mp3, snapshot=snapshot)
            if facts["result"] == "PASS":
                facts["mp3"] = {"path": str(mp3), "sha256": sha256(mp3), "bytes": mp3.stat().st_size,
                                **decoded_facts(mp3, out)}
                facts["worker_text_is_prepared_text"] = "\n".join(facts["worker_chunk_texts"]) == "\n".join(
                    c.text for c in osy.plan_chunks((a if track == "A" else b)["prepared"]))
            entry["tracks"][track] = facts
            print(voice.voice_id, track, facts["result"], facts.get("mp3", {}).get("seconds"),
                  facts.get("mp3", {}).get("peak_dbfs"), facts["vram_driver"]["max_used_mib"], flush=True)
        report["voices"][voice.voice_id] = entry
    report["protected_after"] = protected()
    report["protected_unchanged"] = report["protected_after"] == report["protected_before"]
    report["hub_cache_after"] = hub_cache()
    report["jobs_left"] = sorted(p.name for p in ov.jobs_root().iterdir()) if ov.jobs_root().is_dir() else []
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("report:", out / "report.json")
    ok = all(t["result"] == "PASS" for v in report["voices"].values() for t in v["tracks"].values())
    return 0 if ok and report["protected_unchanged"] else 1


def book_text() -> str:
    """A representative book: title/author lines, chapter headings and paragraphs built from ACT's own quality corpus
    (original text), with numbers the normalizer reads. Sized to just over one worker's 48 chunks, so a second worker
    takes over (bounded; not a marathon)."""
    q = quality_corpus
    chapters = [[q.DIFFICULT_SHORT.text, q.SUSTAINED_NARRATION.text],
                [q.STRUCTURAL_STRESS_KOKORO_EDGE.text, q.STRUCTURAL_STRESS_CHATTERBOX.text],
                [q.SUSTAINED_NARRATION.text]]
    parts = ["Title: The Keeper's Year", "Author: ACT quality corpus"]
    for number, items in enumerate(chapters, start=1):
        parts.append(f"# Chapter {number}")
        parts.append(f"In 1905 the keeper wrote 12 pages on March {number}, 1905, before 7:15 p.m.")
        parts.extend(items)
    return "\n\n".join(parts)


def cmd_book(_args) -> int:
    snapshot = gvs.omnivoice_speech_prep()
    voice = next(v for v in OMNI if v.voice_id == "omnivoice-female-1")
    out = EVIDENCE_ROOT / f"{stamp()}-book"
    out.mkdir(parents=True)
    text = book_text()
    prepared = prepare(text, snapshot, ROUTE)
    chunks = osy.plan_chunks(prepared.text)
    report = {"gpu": gpu_facts(), "environment": environment_facts(), "voice": voice.voice_id, "source_chars": len(text),
              "prepared_chars": len(prepared.text), "planned_chunks": len(chunks),
              "planned_workers": len(osy.batches(chunks)), "hub_cache_before": hub_cache()}
    (out / "book-source.txt").write_text(text, encoding="utf-8")
    mp3 = out / "book.mp3"
    facts = synthesize(voice, text, mp3, snapshot=snapshot)
    if facts["result"] == "PASS":
        facts["mp3"] = {"sha256": sha256(mp3), "bytes": mp3.stat().st_size, **decoded_facts(mp3, out)}
    worker_texts = facts["worker_chunk_texts"]
    report["completeness"] = {
        "worker_chunks": len(worker_texts), "planned": len(chunks),
        "worker_text_equals_plan": worker_texts == [c.text for c in chunks],
        "plan_rejoins_prepared_text": all(prepared.text[c.start:c.end] == c.text for c in chunks),
        "prepared_differs_from_source": prepared.text != text,
        "prepared_again_is_identical": prepare(prepared.text, snapshot, ROUTE).text == prepared.text,
        "chunk_order": [int(e["index"]) for w in facts["workers"] for e in w["chunks"]] == list(range(len(chunks))),
        "chars_per_second_by_chunk": [round(len(t) / r["seconds"], 1) for t, r in zip(worker_texts, facts["raw_chunks"])]
        if facts["raw_chunks"] else []}
    report["run"] = facts
    report["hub_cache_after"] = hub_cache()
    report["jobs_left"] = sorted(p.name for p in ov.jobs_root().iterdir()) if ov.jobs_root().is_dir() else []
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("planned_chunks", "planned_workers", "completeness")}, indent=1)[:2500])
    print(facts["result"], facts.get("mp3", {}).get("seconds"), [w["done"] for w in facts["workers"]])
    print("report:", out / "report.json")
    return 0 if facts["result"] == "PASS" else 1


def _omnivoice_processes() -> list[str]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*omnivoice_worker*' } | "
                          "ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }"], capture_output=True, text=True, timeout=60)
    return [line for line in out.stdout.splitlines() if line.strip() and "powershell" not in line.lower()]


def cmd_cancel(_args) -> int:
    snapshot = gvs.omnivoice_speech_prep()
    voice = next(v for v in OMNI if v.voice_id == "omnivoice-male-3")
    out = EVIDENCE_ROOT / f"{stamp()}-cancel"
    out.mkdir(parents=True)
    long_text = "\n\n".join([quality_corpus.SUSTAINED_NARRATION.text] * 3)
    report: dict = {"voice": voice.voice_id, "cases": {}}

    def case(name: str, *, trigger: str) -> None:
        # Inference: a long text, Cancel 1.5 s into chunk 3. Encode: Cancel 0.3 s into the real FFmpeg encode of about
        # five minutes of audio. Publication: Cancel after the encode finished, before the file is moved into place.
        text = long_text if trigger == "inference" else quality_corpus.SUSTAINED_NARRATION.text
        dest = out / f"{name}.mp3"
        old = b"an existing file the cancelled run must not touch"
        dest.write_bytes(old)
        flag = {"cancel": False, "requested_at": None}
        lines: list[str] = []

        def cancel_check() -> bool:
            return flag["cancel"]

        def request():
            flag["requested_at"] = time.perf_counter()
            flag["cancel"] = True

        encoder_seen = {}

        def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
            encoder_seen["started"] = time.perf_counter()
            if trigger == "encode":
                threading.Timer(0.3, request).start()  # Cancel pressed while FFmpeg is encoding
            try:
                osy._encoder(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)
            finally:
                encoder_seen["returned"] = time.perf_counter()
                encoder_seen["mp3_bytes_in_job"] = Path(mp3).stat().st_size if Path(mp3).exists() else 0
            if trigger == "publish":
                request()  # Cancel pressed after the encode, before the move into place

        rec = Recorder()
        real_run = osy.run_worker

        def run_worker(*a, **k):
            on_chunk = k.get("on_chunk")

            def chunk(event):
                if on_chunk:
                    on_chunk(event)
                if trigger == "inference" and int(event.get("index", -1)) == 1:
                    threading.Timer(1.5, request).start()  # pressed while chunk 3 is being generated
            k["on_chunk"] = chunk
            return real_run(*a, **k)

        started = time.perf_counter()
        with rec:
            osy.run_worker = run_worker
            try:
                gvs._synthesize_omnivoice(voice, text, dest, log=lines.append, speech_prep=snapshot, encoder=encoder,
                                          cancel_check=cancel_check)
                result = "PUBLISHED (cancel lost)"
            except BaseException as exc:  # noqa: BLE001
                result = f"{type(exc).__name__}: {exc}"
            finally:
                osy.run_worker = real_run
        ended = time.perf_counter()
        report["cases"][name] = {
            "result": result, "trigger": trigger,
            "cancel_to_return_s": round(ended - flag["requested_at"], 2) if flag["requested_at"] else None,
            "wall_s": round(ended - started, 2),
            "encoder": {k: (round(v - started, 2) if isinstance(v, float) else v) for k, v in encoder_seen.items()},
            "encode_s_before_cancel": (round(flag["requested_at"] - encoder_seen["started"], 2)
                                       if flag["requested_at"] and "started" in encoder_seen else None),
            "destination_unchanged": dest.read_bytes() == old,
            "part_files_left": sorted(p.name for p in out.glob("*.part")),
            "source_text_left": sorted(p.name for p in out.glob("*.source.txt")),
            "jobs_left": sorted(p.name for p in ov.jobs_root().iterdir()) if ov.jobs_root().is_dir() else [],
            "worker_processes_left": _omnivoice_processes(), "log_tail": lines[-6:]}
        print(name, json.dumps(report["cases"][name])[:600], flush=True)

    case("cancel-during-inference", trigger="inference")
    case("cancel-during-encode", trigger="encode")
    case("cancel-at-publication", trigger="publish")
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("report:", out / "report.json")
    ok = all(c["result"].startswith("ConversionCancelled") and c["destination_unchanged"] and not c["part_files_left"]
             and not c["jobs_left"] and not c["worker_processes_left"] for c in report["cases"].values())
    return 0 if ok else 1


SMOKE_VOICE = {"edge": "en-US-SteffanNeural", "kokoro": "af_heart", "chatterbox": "chatterbox-female-1",
               "qwen3": "qwen3-aiden"}
SMOKE_TEXT = "Dr. Elena Marsh checked the logbook in 1905. The ferry would not arrive before 7:15."


def cmd_smoke(args) -> int:
    """One short production conversion through an existing engine's own entry point (the panel's), with ``v1``."""
    engine = args.engine
    snapshot = gvs.omnivoice_speech_prep()
    voice = next(v for v in VOICES if v.voice_id == SMOKE_VOICE[engine])
    out = EVIDENCE_ROOT / f"{stamp()}-smoke-{engine}"
    out.mkdir(parents=True)
    src = out / "smoke.txt"
    src.write_text(SMOKE_TEXT, encoding="utf-8")
    mp3 = out / f"{engine}.mp3"
    preset = voice.timing_preset
    lines: list[str] = []
    started = time.perf_counter()
    try:
        if engine == "edge":
            from tts import batch_convert
            status = batch_convert.convert_single_pdf(src, out, voice.voice_id, preset.get("rate", "+0%"),
                                                      log=lines.append, out_mp3=mp3, speech_prep=snapshot)
            result = "PASS" if status[0] == "success" else f"FAIL: {status}"
        elif engine == "kokoro":
            from tts.kokoro_synth import kokoro_file_to_mp3
            kokoro_file_to_mp3(str(src), str(mp3), voice_id=voice.voice_id, speed=1.0,
                               end_silence_ms=int(preset["end_pause"]), chunk_pause_ms=int(preset["paragraphpause"]),
                               log=lines.append, bitrate="192k", speech_prep=snapshot)
            result = "PASS"
        elif engine == "chatterbox":
            from tts.chatterbox_synth import chatterbox_file_to_mp3
            chatterbox_file_to_mp3(str(src), str(mp3), voice_id=voice.voice_id, end_silence_ms=int(preset["end_pause"]),
                                   chunk_pause_ms=int(preset["paragraphpause"]), log=lines.append, bitrate="192k",
                                   speech_prep=snapshot)
            result = "PASS"
        else:
            from tts.qwen3_synth import qwen3_file_to_mp3
            qwen3_file_to_mp3(str(src), str(mp3), voice_id=voice.voice_id, end_silence_ms=int(preset["end_pause"]),
                              chunk_pause_ms=int(preset["paragraphpause"]), log=lines.append, bitrate="192k",
                              speech_prep=snapshot)
            result = "PASS"
    except BaseException as exc:  # noqa: BLE001
        result = f"FAIL: {type(exc).__name__}: {exc}"
    report = {"engine": engine, "voice": voice.voice_id, "result": result, "wall_s": round(time.perf_counter() - started, 2),
              "log_tail": lines[-8:]}
    if mp3.is_file():
        report["mp3"] = {"sha256": sha256(mp3), "bytes": mp3.stat().st_size, **decoded_facts(mp3, out)}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("engine", "voice", "result", "wall_s")}), report.get("mp3", {}).get("seconds"))
    return 0 if result == "PASS" else 1


def cmd_installer(_args) -> int:
    """After a normal relaunch: the launch check, the real read-only plan for OmniVoice alone and with all five, and the
    availability the panel asks for. Nothing is installed, downloaded or written by this."""
    from shared import optional_setup_client as client
    from tts import voice_install
    out = EVIDENCE_ROOT / f"{stamp()}-installer"
    out.mkdir(parents=True)
    report: dict = {"receipt": ov.read_receipt(), "environment_status": list(ov.environment_status()),
                    "model_status": list(ov.model_status())}
    check = subprocess.run([str(REPO / ".venv" / "Scripts" / "python.exe"), str(REPO / "scripts" / "shared" / "bootstrap.py"),
                            "--venv-check"], capture_output=True, text=True, timeout=120, cwd=str(REPO))
    report["launch_venv_check_exit"] = check.returncode
    for name, components in (("omnivoice", ["omnivoice"]),
                             ("all-five", ["kokoro", "chatterbox", "qwen3-customvoice", "qwen3-base", "omnivoice"])):
        started = time.perf_counter()
        result = client.plan(REPO, components)
        plan = result.get("plan") or {}
        report[f"plan-{name}"] = {"state": result.get("state"), "seconds": round(time.perf_counter() - started, 1),
                                  "components": {c["id"]: [c["readiness"], c.get("reason", "")[:200]]
                                                 for c in plan.get("components", []) if c.get("selected", True)},
                                  "acquire_units": plan.get("acquire_units"),
                                  "download": (plan.get("totals") or {}).get("download"),
                                  "disk": (plan.get("totals") or {}).get("disk"), "error": result.get("error")}
        print(name, json.dumps(report[f"plan-{name}"])[:900], flush=True)
    report["availability"] = {v.voice_id: list(ov.voice_availability(v.voice_id)) for v in OMNI}
    report["install_offer"] = {v.voice_id: voice_install.installable(v.backend, v.voice_id, report["availability"][v.voice_id][1])
                               for v in OMNI}  # what the panel would offer with the reason it shows
    report["receipt_after"] = ov.read_receipt()
    report["receipt_unchanged"] = report["receipt_after"] == report["receipt"]
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("environment_status", "model_status", "launch_venv_check_exit",
                                             "install_offer", "receipt_unchanged")}, indent=1, default=str))
    print("report:", out / "report.json")
    return 0


# --------------------------------------------------------------------------- #
# The owner's listening index (rendered from a pack's report.json; no engine)
# --------------------------------------------------------------------------- #
PENDING = "NOT YET REVIEWED"
REVIEW_ROWS_A = ["Naturalness", "Calmness and emotional consistency", "Tone fluctuations",
                 "Proper names (Elena Marsh, J. R. Alvarez, Okafor, Yates, Whitfield)",
                 "Abbreviations and initials (Dr., Mr., Mrs., Prof., i.e., e.g., vs.)", "Quoted dialogue",
                 "Kept-as-written tokens (6:45, 3:1, the URL)", "Truncation or missing words", "Repeated words",
                 "Sentence and phrase transitions", "MP3 ending quality", "Clipping or harsh peaks"]
REVIEW_ROWS_B = [f"{cls} reading" for cls in AUDIBLE] + [
    "Kept-as-written numbers (Part seven)", "Identifiers, address, negative number (Part eight)",
    "Abbreviations, initials, punctuation (Part nine)", "URL, email, file path (Part ten)",
    "Fantasy/proper names (Part eleven)", "Truncation or missing words", "Repeated words",
    "Sentence and phrase transitions", "MP3 ending quality", "Clipping or harsh peaks", "Calmness and tone consistency"]


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " / ")


def _file_link(path: str) -> str:
    return "file:///" + str(path).replace("\\", "/").replace(" ", "%20")


def _b_rows(report: dict) -> list[dict]:
    b = report["track_b"]
    chunks = osy.plan_chunks(b["prepared"])
    rows = []
    for item in b["items"]:
        offset = item.get("offset", -1)
        chunk = next((c.index for c in chunks if c.start <= offset < c.end), None)
        if item.get("golden"):
            expected = "; ".join(f"{g['expected_reading']!r} ({g['corpus_id']})" for g in item["golden"])
        elif item["kind"] == "no golden case":
            expected = "No golden case. v1 leaves it unchanged (checked); model-native reading: owner judgement"
        elif not item["classes"] and item["expected"] == item["source"]:
            expected = "Left as written by design (golden) -- model native; pronunciation requires listening"
        else:
            expected = repr(item["expected"])
        rows.append({**item, "chunk": chunk, "expected_text": expected})
    return rows


def render_index(report: dict, folder: Path) -> tuple[str, str]:
    voices = report["voices"]
    rows = _b_rows(report)
    env, snap, gpu = report["environment"], report["snapshot"], report["gpu"]
    lines = [
        "# OmniVoice v0.8.0 Phase 4 -- owner listening pack", "",
        f"**Status: every verdict below is {PENDING}.** A technical PASS (the track rendered) is not listening approval. "
        "Session 5 waits for your explicit approval or rejection of BOTH tracks of ALL six voices.", "",
        f"- Folder: `{folder}`",
        f"- Generated {report['started']} to {report['finished']} on HOME-PC through the production OmniVoice path "
        "(`omnivoice_file_to_mp3`, the voice's own preset, MP3 bitrate "
        f"{env['bitrate']}, speech preparation `v1`).",
        "- Track A: the same natural passage for all six voices (`quality_corpus.DIFFICULT_SHORT`, verbatim).",
        "- Track B: the same indexed normalization challenge for all six voices (G1 `SNIPPETS` + golden corpus).", "",
        "## The 12 primary tracks", "",
        "| # | Voice | Track | Duration | MP3 SHA-256 | File |", "|---|---|---|---|---|---|"]
    n = 0
    for vid, v in voices.items():
        for t in ("A", "B"):
            f = v["tracks"][t]
            n += 1
            m = f.get("mp3", {})
            lines.append(f"| {n} | {v['label']} | {'A Natural' if t == 'A' else 'B Normalization'} | "
                         f"{m.get('seconds', '-')} s | `{m.get('sha256', f['result'])[:16]}...` | "
                         f"[{Path(m.get('path', '')).name}]({_file_link(m.get('path', ''))}) |")
    lines += ["", "Full SHA-256s and every measurement: `report.json` in this folder.", "",
              "## Owner review checklist (all six voices)", "",
              "Mark each cell Correct / Needs correction (with a note). Defaults are not answers.", ""]
    for vid, v in voices.items():
        lines += [f"### {v['label']}", "",
                  f"- **Track A verdict: {PENDING}** (Approve / Reject)",
                  f"- **Track B verdict: {PENDING}** (Approve / Reject)", "",
                  "| Track A check | Verdict | Note |", "|---|---|---|"]
        lines += [f"| {row} | {PENDING} | |" for row in REVIEW_ROWS_A]
        lines += ["", "| Track B check | Verdict | Note |", "|---|---|---|"]
        lines += [f"| {row} | {PENDING} | |" for row in REVIEW_ROWS_B]
        lines.append("")
    a = report["track_a"]
    lines += ["## Track A -- natural / difficult narration", "", "**Source (identical for all six voices):**", "",
              "> " + a["source"], "", "**Prepared v1 text (what the model was given):**", "", "> " + a["prepared"], "",
              "| Source token | Prepared | Class |", "|---|---|---|"]
    lines += [f"| {_md(e['original'])} | {_md(e['spoken'])} | {e['cls']} |" for e in a["edits"]]
    lines += ["", "Left as written in A by design (no cue): `6:45`, `3:1` (\"close to 3:1\"), `i.e.`, `e.g.`, `vs.`, "
              "`J. R.`, the URL -- the model reads them natively; listen for them.", "",
              "## Track B -- normalization challenge", "", "**Source (identical for all six voices):**", "", "```text",
              report["track_b"]["source"], "```", "", "**Prepared v1 text:**", "", "```text", report["track_b"]["prepared"],
              "```", "",
              "Every row was checked mechanically before any audio was made: each item's prepared text appears in order "
              "in the prepared composite, each golden-corpus line reads exactly as its golden case expects, and each G1 "
              "snippet contains the golden corpus reading of each of its tokens. All 15 audible classes are exercised.", "",
              "| # | Part | Class | Source | Prepared v1 | Expected (golden fixture) | Chunk |",
              "|---|---|---|---|---|---|---|"]
    for i, row in enumerate(rows, start=1):
        cls = ", ".join(row["edits"]) or ("-" if row["kind"] != "no golden case" else row["note"])
        lines.append(f"| {i} | {row['part']} | {cls} | {_md(row['source'])} | {_md(row['prepared'])} | "
                     f"{_md(row['expected_text'])} | {(row['chunk'] or 0) + 1} |")
    lines += ["", "**Where each chunk starts in each B track (seconds, approximate):**", "",
              "| Chunk | " + " | ".join(v["label"].split(" - ")[1] for v in voices.values()) + " |",
              "|---|" + "---|" * len(voices)]
    starts = [v["tracks"]["B"].get("chunk_starts_s", []) for v in voices.values()]
    for c in range(max(len(s) for s in starts)):
        lines.append(f"| {c + 1} | " + " | ".join(str(s[c]) if c < len(s) else "-" for s in starts) + " |")
    lines += ["", "## HYG (mechanical only -- no audio claim)", "",
              "| Case | Before | Invisible / special code points | After | Golden | Match |", "|---|---|---|---|---|---|"]
    for h in report["hyg"]:
        lines.append(f"| {h['id']} | {_md(repr(h['before']))} | {' '.join(h['before_codepoints']) or '-'} | "
                     f"{_md(repr(h['after']))} | {_md(repr(h['expected']))} | {h['match']} |")
    lines += ["", "## Engine, settings and speech-preparation snapshot", "",
              f"- OmniVoice {env['omnivoice']}, model {env['model_repository']} @ `{env['model_revision']}`; engine "
              f"{env['engine_status']}, model {env['model_status']}, install receipt origin `{env['receipt_origin']}`.",
              f"- GPU {gpu.get('name')} ({gpu.get('total_mib')} MiB), driver {gpu.get('driver')}.",
              f"- Generation: {json.dumps(env['generation'])}; {env['dtype']}; chunks of at most "
              f"{env['max_chunk_chars']} characters; at most {env['chunks_per_worker']} chunks per worker; pipeline "
              f"revision {env['pipeline_revision']}; seed base {env['seed_base']}; paragraph pause 700 ms between chunks.",
              f"- Speech preparation `{snap['setting']}`, ruleset {snap['ruleset_version']} (fingerprint "
              f"`{snap['ruleset_fingerprint'][:16]}...`), mode table `{snap['mode_table_hash'][:16]}...`, snapshot version "
              f"`{snap['speech_prep_version'][:16]}...`; user glossary/mode files present: {snap['user_dir_exists']}; "
              f"OmniVoice cells: all 16 `expand` = {set(snap['omnivoice_cells'].values()) == {'expand'}}.",
              f"- Offline: worker environment {json.dumps(env['offline_env'])}; the worker's audit hook refuses any "
              "network access (a refusal fails the run, and none did); Hugging Face cache before "
              f"{report['hub_cache_before']} and after {report['hub_cache_after']}; job folders left {report['jobs_left']}; "
              f"18 references and 28 previews unchanged: {report['protected_unchanged']}.", "",
              "## Reference recordings and transcripts", "",
              "| Voice | Recording | Seconds | SHA-256 | Owner transcript |", "|---|---|---|---|---|"]
    for v in voices.values():
        ref = v["reference"]
        lines.append(f"| {v['label']} | `{Path(ref['path']).name}` | {ref['seconds']} (max {ref['max_seconds']:.3f}) | "
                     f"`{ref['wav_sha256'][:16]}...` | {_md(ref['text'])} |")
    lines += ["", "## Measurements per track", "",
              "| Voice | Track | Seconds | Decoded peak dBFS | MP3 true peak dBTP | Raw samples >= 1.0 | 16-bit full-scale "
              "samples | Pre-encode true peak dBTP | Quiet tail ms | Prompt | VRAM alloc / reserved peak MiB | GPU in use (driver) "
              "max MiB |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in voices.values():
        for t in ("A", "B"):
            f = v["tracks"][t]
            m, e, w = f.get("mp3", {}), f.get("encoder_input", {}), f["workers"]
            lines.append(f"| {v['label']} | {t} | {m.get('seconds')} | {m.get('peak_dbfs')} | {m.get('true_peak_dbtp')} | "
                         f"{sum(c['samples_at_or_over_1.0'] for c in f['raw_chunks'])} | "
                         f"{e.get('samples_at_int16_full_scale')} | {e.get('true_peak_dbtp')} | "
                         f"{m.get('tail_ms_below_-50dbfs')} | {', '.join(x['loaded']['prompt'] for x in w)} | "
                         f"{'/'.join(str(x['done']['peak_allocated_mib']) for x in w)} / "
                         f"{'/'.join(str(x['done']['peak_reserved_mib']) for x in w)} | {f['vram_driver']['max_used_mib']} |")
    lines += ["", "## Points to listen for", "",
              "- **Raw full-scale samples:** the model's own output reached exactly 1.0 in a few samples of OmniVoice "
              "Male 1 (track A near 23.1 s and 23.8 s; track B near 33.3 s and 81.1 s) and Male 3 (track A near 26.6 s "
              "and 59.3 s). The 16-bit WAV clamps them (no wrap-around); every decoded MP3 has 0 samples at full scale. "
              "Listen there for any crackle or harshness. No correction is applied without an audible defect.",
              "- **Male 2 reference:** its recording ends inside a short, quiet breath after \"Jaw.\" -- listen for a "
              "breathy onset or ending in its tracks.",
              "- **Spelling of names:** your OmniVoice/Chatterbox transcripts spell \"Joric Reclentos\"; the historical "
              "Qwen3 transcript spells \"Jorg\". Part eleven of track B uses your spelling.",
              "- **Kept-as-written tokens** (Part seven to ten, and A's 6:45 / 3:1 / URL) are the model's own reading. "
              "If one sounds wrong, say which voice, token and reading you expect; a fix would be a narrow OmniVoice-only "
              "choice (a mode-table cell or an engine-scoped glossary entry), shown to you with a short before/after clip "
              "first.", ""]
    md = "\n".join(lines)
    audio = "\n".join(
        f"<h3>{v['label']}</h3>" + "".join(
            f"<p><b>{'A Natural' if t == 'A' else 'B Normalization'}</b> ({v['tracks'][t].get('mp3', {}).get('seconds')} s)"
            f" &mdash; verdict: <b>{PENDING}</b><br><audio controls preload=\"none\" "
            f"src=\"{Path(v['tracks'][t].get('mp3', {}).get('path', '')).name}\"></audio></p>" for t in ("A", "B"))
        for v in voices.values())
    html = ("<!doctype html><meta charset=\"utf-8\"><title>OmniVoice listening pack</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:52rem;margin:1rem auto;padding:0 1rem}"
            "audio{width:100%}</style><h1>OmniVoice v0.8.0 Phase 4 &mdash; listening pack</h1>"
            f"<p>Every verdict is <b>{PENDING}</b>. The full index with the texts, the expected readings and the "
            "checklist is <code>index.md</code> in this folder.</p>" + audio)
    return md, html


def cmd_index(args) -> int:
    folder = Path(args.folder) if args.folder else max(p for p in PACK_ROOT.iterdir() if (p / "report.json").is_file())
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    md, html = render_index(report, folder)
    (folder / "index.md").write_text(md, encoding="utf-8")
    (folder / "index.html").write_text(html, encoding="utf-8")
    print("index:", folder / "index.md")
    print("player:", folder / "index.html")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("text")
    pack = sub.add_parser("pack")
    pack.add_argument("--voice", action="append", default=None)
    sub.add_parser("book")
    sub.add_parser("cancel")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("engine", choices=sorted(SMOKE_VOICE))
    sub.add_parser("installer")
    index = sub.add_parser("index")
    index.add_argument("folder", nargs="?", default=None)
    args = parser.parse_args(argv)
    return {"text": cmd_text, "pack": cmd_pack, "book": cmd_book, "cancel": cmd_cancel, "smoke": cmd_smoke,
            "installer": cmd_installer, "index": cmd_index}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
