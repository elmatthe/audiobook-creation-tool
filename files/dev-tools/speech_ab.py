"""Plan 01B checkpoint A4: the bounded A/B listening corpus for speech preparation (section 7.2). Development only.

For each class snippet and each engine's representative voice (decision D13) the tool makes two clips through the
app's own entry points: **A** = the text as the engine reads it today (speech preparation off) and **B** = the same text
with only that class's cell set to ``expand``. Every other setting is identical on both sides. A pair is made only
where B differs from A. Clips get neutral, shuffled names in ``listen/``; which clip is A or B lives only in
``key/manifest.json``, outside the listening folder.

Commands (run from the repository root with the root ``.venv``):

  plan      write ``key/plan.json`` (texts, edits, source offsets, integrity proof); no audio
  probe     Kokoro's misaki G2P on cue / no-cue four-digit numbers (evidence for decision D8); no audio
  generate  synthesize every planned clip that is missing or stale (Edge needs the network; Qwen3 its own venv)
  asr       advisory Whisper read-back of every clip (the evaluation harness's small.en snapshot)
  report    mechanical checks, ``key/manifest.json``, ``key/VERDICT-TABLE.md`` (and ``listen/REVIEW-SHEET.md`` once)
  export-ordered  copy the clips, unchanged, into ``listen-ordered/NNN-Engine-CLASS-A|B.wav`` with its own review sheet;
            the private filename mapping goes to ``key/ordered-mapping.json``
  edge-smoke      one fixed sentence through every registered Edge voice (``edge-voice-smoke/``)

Nothing here touches recordings outside ``files/dev-work/speech-ab/``; nothing is installed or downloaded.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
DEV_TOOLS = Path(__file__).resolve().parent
OUT = REPO_ROOT / "files" / "dev-work" / "speech-ab" / "a4"
LISTEN, KEY = OUT / "listen", OUT / "key"
for _path in (str(SCRIPTS), str(DEV_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tts.speech import classes, profiles  # noqa: E402
from tts.speech.integrity import reconstruct_source  # noqa: E402
from tts.speech.normalize import normalize  # noqa: E402
from tts.speech.pipeline import SETTING_V1, SpeechPrepSnapshot, prepare  # noqa: E402

SHUFFLE_SEED = 20261020
SEED_BASE = 20261020
#: The closing silence of every clip (both sides): the production 3 s end pause only lengthens listening.
END_SILENCE_MS = 400
SAMPLE_RATE_CHECK = (8000, 48000)

#: One representative voice per engine (decision D13): each engine's default/first approved row.
VOICES = {"edge_direct": "en-US-SteffanNeural", "kokoro": "af_heart", "chatterbox": "chatterbox-female-1",
          "qwen3": "qwen3-aiden"}
ROUTE_ENGINE = {route: profiles.PROFILES[route].engine for route in VOICES}

#: One snippet per audible class. TIME, DEC and TITLE reuse sentences of the approved DIFFICULT_SHORT passage so the
#: change to previously approved audio is heard directly. HYG is a mechanical-only class (Plan 01B 4.3) and has none.
SNIPPETS = {
    "CARD": "The ledger listed 1,250 pages, 12 chapters and 1,000,000 words. The fort held 1500 people and 5000 men.",
    "DEC": "The beam's rotation had slowed by 2.5 degrees per second. The margin was 0.07, and it rose to 3.25 by evening.",
    "ORD": "She finished 1st, he came 2nd, and the 21st runner crossed the line on the 103rd lap.",
    "PCT": "Turnout rose 12.5% this year, nearly 100% of seats were filled, and 3% stayed home.",
    "CUR": "The ticket cost $12.50, the meal was $5, and the toll was £2.75. They raised $1.5 million and spent €200.",
    "YEAR": "Built in 1905, restored by 1999 and reopened in 2024, the lighthouse saw its busiest years in the 1990s.",
    "TIME": "The ferry would not arrive before 7:15. The first boat left at 6:05, the next at 10:30 a.m., and the last at 9pm.",
    "RATIO": "They won 3:1 at home, the odds were 100:1 against, and the mortar was a 2:1 ratio of sand to clay.",
    "DATE": "The letter was dated March 5, 2024, the reply came on July 4th, and the log entry read 2024-03-05.",
    "RANGE": "Read pages 12-15 tonight. Children aged 8-12 may attend, and the war ran from 1939–1945.",
    "FRAC": "Add 1/2 cup of flour, 3/4 teaspoon of salt, and 1 1/2 cups of milk.",
    "UNIT": "They hiked 5 km at 72°F, carried a 10 kg pack, and drove home at 60 mph.",
    "TITLE": "Dr. Elena Marsh checked the logbook one last time. Mr. Okafor and Mrs. Yates both blamed the storm; "
             "Prof. Whitfield's theory kept circling back to her.",
    "ROMAN": "Chapter IV opens in the court of Henry VIII, years before World War II reshaped the coast.",
    "SYM": "Smith & Wesson made the lock, and the grid was 3 × 4 squares.",
}

#: Plan 01B 7.2: does a change in this cell touch previously approved audio, and on what evidence.
APPROVED_DS = "approved evaluation recordings of DIFFICULT_SHORT (Decision B roster, 2026-10-19)"
IMPACT = {
    "TITLE": (["pronunciation", "pacing"], APPROVED_DS + ": Dr./Mr./Mrs./Prof. were read natively; removing the stop "
                                                         "can also change where an engine splits or pauses"),
    "TIME": (["pronunciation"], APPROVED_DS + ": 'before 7:15' was read natively"),
    "DEC": (["pronunciation"], APPROVED_DS + ": '2.5 degrees' was read natively"),
}
CHATTERBOX_COLON = ("Chatterbox structural-colon patch, Decisions 2026-09-21 iterations 5/6: times and ratios judged "
                    "'B PASS natively with the patch'")


def impact(route: str, cls: str) -> dict:
    labels, evidence = IMPACT.get(cls, ([], ""))
    labels = list(labels)
    if route == "chatterbox" and cls in ("TIME", "RATIO"):
        labels = sorted(set(labels) | {"pronunciation", "pacing"})
        evidence = "; ".join(e for e in (evidence, CHATTERBOX_COLON) if e)
    return {"affects_previously_approved": labels or ["none"], "evidence": evidence or "no approved recording contains it"}


#: The A4 baseline: every cell native (the rollout table A4 was planned against), whatever production ships today.
A4_BASE_TABLE = {engine: {c: "native" for c in classes.RULE_CLASSES} for engine in sorted(set(ROUTE_ENGINE.values()))}


def snapshot_for(route: str, cls: str | None) -> SpeechPrepSnapshot | None:
    """A: None (off). B: v1 with only ``cls`` expanded for this engine; every other cell native, no glossary."""
    if cls is None:
        return None
    return SpeechPrepSnapshot(setting=SETTING_V1,
                              cells=profiles.effective_cells(A4_BASE_TABLE, ((ROUTE_ENGINE[route], cls, "expand"),)),
                              mode_table_hash=profiles.table_hash(A4_BASE_TABLE))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- plan

def build_plan() -> dict:
    pairs = []
    for cls, text in SNIPPETS.items():
        for route in VOICES:
            a = prepare(text, None, route)
            b = prepare(text, snapshot_for(route, cls), route)
            a_text = a.spoken_source if a.document is None else a.text
            b_text = b.spoken_source if b.document is None else b.text
            if a_text == b_text:
                continue
            edits = b.normalized.edits
            proof = reconstruct_source(b.normalized.spoken, edits) == text and {e.cls for e in edits} == {cls}
            pairs.append({
                "pair": f"{route}:{cls}", "route": route, "engine": ROUTE_ENGINE[route], "voice": VOICES[route], "class": cls,
                "tier": classes.TIERS[cls], "source": text, "a_text": a_text, "b_text": b_text,
                "edits": [{"source_start": e.source_start, "source_end": e.source_end, "original": e.original,
                           "spoken": e.spoken, "rule": e.rule_id} for e in edits],
                "ambiguous_left_unchanged": [{"text": t.text, "reason": t.reason} for t in b.normalized.ambiguities],
                "integrity_proof": proof, **impact(route, cls)})
    clips = [(p["pair"], side) for p in pairs for side in ("A", "B")]
    order = list(range(len(clips)))
    random.Random(SHUFFLE_SEED).shuffle(order)
    names = {clips[i]: f"clip-{n + 1:03d}" for n, i in enumerate(order)}
    for index, p in enumerate(pairs):
        p["seed"] = SEED_BASE + index
        p["clips"] = {side: names[(p["pair"], side)] for side in ("A", "B")}
    return {"voices": VOICES, "end_silence_ms": END_SILENCE_MS, "shuffle_seed": SHUFFLE_SEED, "pairs": pairs}


def load_plan() -> dict:
    return json.loads((KEY / "plan.json").read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- Kokoro probe (D8)

PROBE_NUMBERS = (1250, 1500, 2024, 1999, 2500, 5000)
PROBE_FRAMES = {"count cue": "It held {n} pages.", "year cue": "It happened in {n}.", "no cue": "The figure was {n}.",
                "no cue, lower-case word": "About {n} came back."}


def kokoro_probe() -> dict:
    from misaki import en

    from tts.speech import numbers_en as num

    g2p = en.G2P(trf=False, british=False, fallback=None)
    rows = []
    for n in PROBE_NUMBERS:
        for frame_name, frame in PROBE_FRAMES.items():
            sentence = frame.format(n=n)
            native = g2p(sentence)[0]
            year_reading = g2p(frame.format(n=num.year(n)))[0]
            cardinal_reading = g2p(frame.format(n=num.cardinal(n)))[0]
            result = normalize(sentence)
            decision = ([f"{e.cls}: {e.spoken}" for e in result.edits]
                        or [f"left unchanged ({a.reason})" for a in result.ambiguities] or ["no rule"])
            rows.append({"number": n, "frame": frame_name, "sentence": sentence, "misaki_phonemes": native,
                         "misaki_reads_as": ("same either way" if year_reading == cardinal_reading
                                             else "year" if native == year_reading
                                             else "cardinal" if native == cardinal_reading else "other"),
                         "year_reading": num.year(n), "cardinal_reading": num.cardinal(n), "act_rule": decision[0]})
    import misaki

    return {"misaki_version": getattr(misaki, "__version__", "unknown"), "rows": rows}


# --------------------------------------------------------------------------- generation

def _edge_kwargs(voice_id: str) -> dict:
    from tts.voice_registry import VOICES as REGISTRY

    preset = next(v for v in REGISTRY if v.voice_id == voice_id).timing_preset
    return {"sentencepause": int(preset["sentencepause"]), "paragraphpause": int(preset["paragraphpause"]),
            "title_trailing_pause": int(preset["title_ms"]), "chapter_trailing_pause": int(preset["chapter_ms"]),
            "end_of_book_pause": END_SILENCE_MS, "trim_tts_padding": bool(preset["trim_edge_chunks"]),
            "trim_silence_db": float(preset["trim_dbfs"])}


def _local_preset(voice_id: str) -> dict:
    from tts.voice_registry import VOICES as REGISTRY

    return next(v for v in REGISTRY if v.voice_id == voice_id).timing_preset


def _seed_everything(seed: int) -> None:
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    with contextlib.suppress(ImportError):
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def synthesize(route: str, voice: str, source_text: str, snapshot, out_wav: Path, seed: int, log) -> None:
    import numpy as np
    import soundfile as sf

    kwargs = {} if snapshot is None else {"speech_prep": snapshot}
    with tempfile.TemporaryDirectory(prefix="speech_ab_") as work:
        src = Path(work) / "snippet.txt"
        src.write_text(source_text, encoding="utf-8")
        if route == "edge_direct":
            from shared import ffmpeg_utils
            from tts.epub2tts_edge import epub2tts_edge, runner

            ffmpeg_utils.configure_pydub()
            epub2tts_edge.ensure_punkt()
            produced = runner.run_conversion_job(str(src), output_dir=work, speaker=voice, audio_format="mp3",
                                                 mp3_bitrate="192k", cover=None, overwrite=True, **_edge_kwargs(voice),
                                                 **kwargs)
            from pydub import AudioSegment

            AudioSegment.from_file(produced).set_channels(1).export(str(out_wav), format="wav")
            return
        preset = _local_preset(voice)

        def to_wav(arr, rate, output, bitrate=None):
            sf.write(str(output), np.asarray(arr, dtype="float32"), rate, subtype="PCM_16")

        if route == "kokoro":
            from tts import kokoro_synth as ks

            with _patched(ks, "_export_mp3", to_wav):
                ks.kokoro_file_to_mp3(str(src), str(out_wav), voice, speed=float(preset["kokoro_speed"]),
                                      end_silence_ms=END_SILENCE_MS, chunk_pause_ms=int(preset["paragraphpause"]), log=log,
                                      **kwargs)
        elif route == "chatterbox":
            from tts import chatterbox_synth as cb

            _seed_everything(seed)  # A and B of one pair share a seed; production stays unseeded
            with _patched(cb, "_export_mp3", to_wav):
                cb.chatterbox_file_to_mp3(str(src), str(out_wav), voice, end_silence_ms=END_SILENCE_MS,
                                          chunk_pause_ms=int(preset["paragraphpause"]), log=log, **kwargs)
        elif route == "qwen3":
            from tts import qwen3_synth as qs

            def wav_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
                shutil.copyfile(wav, mp3)

            qs.qwen3_file_to_mp3(str(src), str(out_wav), voice, end_silence_ms=END_SILENCE_MS,
                                 chunk_pause_ms=int(preset["paragraphpause"]), log=log, encoder=wav_encoder, **kwargs)
        else:
            raise ValueError(route)


@contextlib.contextmanager
def _patched(module, name, value):
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def clip_identity(pair: dict, side: str) -> str:
    return sha(json.dumps({"route": pair["route"], "voice": pair["voice"], "side": side, "seed": pair["seed"],
                           "text": pair["a_text" if side == "A" else "b_text"], "end_ms": END_SILENCE_MS}, sort_keys=True))


def generate(routes: list[str] | None = None) -> int:
    plan = load_plan()
    LISTEN.mkdir(parents=True, exist_ok=True)
    state_path = KEY / "generated.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    log_file = (KEY / "generate.log").open("a", encoding="utf-8")

    def log(message: str) -> None:
        log_file.write(str(message) + "\n")
        log_file.flush()

    made = failed = 0
    for pair in plan["pairs"]:
        if routes and pair["route"] not in routes:
            continue
        for side in ("A", "B"):
            name = pair["clips"][side]
            target = LISTEN / f"{name}.wav"
            identity = clip_identity(pair, side)
            if target.is_file() and state.get(name) == identity:
                continue
            print(f"{name}  {pair['pair']}", flush=True)
            snapshot = snapshot_for(pair["route"], pair["class"]) if side == "B" else None
            partial = target.with_suffix(".partial.wav")
            try:
                with contextlib.redirect_stdout(log_file):
                    synthesize(pair["route"], pair["voice"], pair["source"], snapshot, partial, pair["seed"], log)
                partial.replace(target)
                state[name] = identity
                write_json(state_path, state)
                made += 1
            except Exception as exc:  # noqa: BLE001 - one clip must not stop the rest
                failed += 1
                log(f"FAILED {name} {pair['pair']} {side}: {type(exc).__name__}: {exc}")
                print(f"  FAILED: {type(exc).__name__}: {exc}", flush=True)
                partial.unlink(missing_ok=True)
    log_file.close()
    print(f"generated {made}, failed {failed}")
    return 1 if failed else 0


# --------------------------------------------------------------------------- ASR read-back (advisory)

def asr() -> int:
    import qwen_eval_assets as assets
    import qwen_eval_core as core

    plan = load_plan()
    rows = [{"row_id": p["clips"][s], "wav": str(LISTEN / f"{p['clips'][s]}.wav")}
            for p in plan["pairs"] for s in ("A", "B") if (LISTEN / f"{p['clips'][s]}.wav").is_file()]
    job = {"kind": "asr-check", "model_dir": str(assets.snapshot_dir("whisper-small-en")), "rows": rows}
    job_path = KEY / "asr-job.json"
    write_json(job_path, job)
    # The evaluation venv first; the production Qwen3 venv (same torch/transformers family) only if that one cannot
    # start. Either is only *run*: nothing is installed or changed in it.
    interpreters = [core.eval_python(), REPO_ROOT / ".venv-qwen3" / ("Scripts" if sys.platform == "win32" else "bin")
                    / ("python.exe" if sys.platform == "win32" else "python")]
    results: dict = {}
    for python in interpreters:
        proc = subprocess.run([str(python), str(DEV_TOOLS / "qwen_eval_worker.py"), str(job_path)],
                              env=core.child_env("qwen", offline=True), capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        (KEY / f"asr-worker-{Path(python).parents[1].name}.err").write_text(proc.stderr, encoding="utf-8")
        for line in proc.stdout.splitlines():
            event = core.parse_event(line)
            if event and event.get("event") == "asr_row":
                results[event["row_id"]] = event["text"]
            elif event and event.get("event") == "asr_failed":
                results[event["row_id"]] = None
        if results:
            break
    write_json(KEY / "asr.json", {"method": core.ASR_METHOD, "interpreter": str(Path(python).relative_to(REPO_ROOT)),
                                  "results": results})
    print(f"ASR: {len(results)} of {len(rows)} clips with {Path(python).relative_to(REPO_ROOT)} (exit {proc.returncode})")
    return 0 if proc.returncode == 0 and len(results) == len(rows) else 1


def _words(text: str) -> list[str]:
    spoken = normalize(text).spoken.lower()
    return re.findall(r"[a-z']+", spoken.replace("-", " "))


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = _words(reference), _words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return round(row[-1] / max(1, len(ref)), 3)


# --------------------------------------------------------------------------- mechanical checks and report

def audio_check(path: Path, text: str) -> dict:
    import numpy as np
    import soundfile as sf

    try:
        data, rate = sf.read(str(path), dtype="float32")
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "problems": [f"unreadable ({exc})"]}
    problems = []
    if data.ndim != 1:
        problems.append("not mono")
        data = data.mean(axis=1)
    seconds = data.size / rate
    speech_chars = len(re.sub(r"\s", "", text))
    if not SAMPLE_RATE_CHECK[0] <= rate <= SAMPLE_RATE_CHECK[1]:
        problems.append(f"sample rate {rate}")
    if not np.isfinite(data).all():
        problems.append("non-finite samples")
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    rms_db = 20 * np.log10(max(float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0, 1e-9))
    if peak >= 0.999:
        problems.append("clips at full scale")
    if rms_db < -45:
        problems.append(f"nearly silent ({rms_db:.0f} dBFS)")
    rate_cps = speech_chars / max(seconds, 1e-6)
    if not 5 <= rate_cps <= 30:
        problems.append(f"{rate_cps:.1f} characters per second is implausible for {seconds:.1f} s")
    if seconds > 30:
        problems.append(f"{seconds:.1f} s is over the 25 s snippet budget")
    return {"pass": not problems, "problems": problems, "seconds": round(seconds, 2), "rms_dbfs": round(rms_db, 1),
            "peak": round(peak, 3)}


def report() -> int:
    plan = load_plan()
    asr_path = KEY / "asr.json"
    asr_results = json.loads(asr_path.read_text(encoding="utf-8"))["results"] if asr_path.is_file() else {}
    manifest = {"note": "THE KEY. Do not open before listening. A = speech preparation off (today); B = only this class "
                        "expanded for this engine.", **{k: plan[k] for k in ("voices", "end_silence_ms", "shuffle_seed")},
                "pairs": []}
    total_seconds = 0.0
    for pair in plan["pairs"]:
        record = dict(pair)
        record["mechanical"] = {}
        for side in ("A", "B"):
            name = pair["clips"][side]
            text = pair["a_text" if side == "A" else "b_text"]
            check = audio_check(LISTEN / f"{name}.wav", text) if (LISTEN / f"{name}.wav").is_file() else \
                {"pass": False, "problems": ["missing"]}
            heard = asr_results.get(name)
            check["asr_text"] = heard
            check["asr_wer_vs_intended_reading"] = None if heard is None else word_error_rate(pair["b_text"], heard)
            check["asr_flag"] = check["asr_wer_vs_intended_reading"] is not None and check["asr_wer_vs_intended_reading"] > 0.25
            total_seconds += check.get("seconds", 0.0)
            record["mechanical"][side] = check
        record["mechanical_pass"] = (pair["integrity_proof"] and record["mechanical"]["A"]["pass"]
                                     and record["mechanical"]["B"]["pass"])
        manifest["pairs"].append(record)
    manifest["total_audio_seconds"] = round(total_seconds, 1)
    write_json(KEY / "manifest.json", manifest)
    legacy_sheet = LISTEN / "REVIEW-SHEET.md"
    if not legacy_sheet.exists():  # the first sheet is kept as issued; listen-ordered/ carries the current one
        legacy_sheet.write_text(review_sheet(manifest), encoding="utf-8")
    (KEY / "VERDICT-TABLE.md").write_text(verdict_table(manifest), encoding="utf-8")
    failing = [p["pair"] for p in manifest["pairs"] if not p["mechanical_pass"]]
    print(f"{len(manifest['pairs'])} pairs, {total_seconds / 60:.1f} min of audio, mechanical failures: {failing or 'none'}")
    return 1 if failing else 0


ENGINE_NAMES = {"edge_direct": "Edge (Steffan)", "kokoro": "Kokoro (Heart)", "chatterbox": "Chatterbox (Female 1)",
                "qwen3": "Qwen3 (Aiden)"}


def review_sheet(manifest: dict) -> str:
    lines = ["# Speech preparation A/B listening (Plan 01B A4, gate G1)", "",
             "Each row is one engine and one class: two clips of the same sentence that differ only in how the marked "
             "items are prepared. The clips are numbered at random; nothing here says which one is today's behaviour.",
             "", "For each row, write **first**, **second**, **same** (no audible difference) or **neither** (both wrong), "
             "plus a word if something is mispronounced or the pacing is off. Listen for the items named in *Listen for*.",
             "", "| # | Engine | Class | Listen for | First | Second | Verdict |", "|---|---|---|---|---|---|---|"]
    missing = []
    index = 0
    for pair in sorted(manifest["pairs"], key=lambda p: (p["route"], p["class"])):
        if not all((LISTEN / f"{name}.wav").is_file() for name in pair["clips"].values()):
            missing.append(pair)
            continue
        index += 1
        first, second = listening_order(pair)
        items = ", ".join(sorted({e["original"] for e in pair["edits"]}, key=pair["source"].find))
        flag = " (touches approved audio)" if pair["affects_previously_approved"] != ["none"] else ""
        lines.append(f"| {index} | {ENGINE_NAMES[pair['route']]} | {pair['class']}{flag} | {items} | {first} | {second} | |")
    if missing:
        routes = sorted({ENGINE_NAMES[p["route"]] for p in missing})
        lines += ["", f"**Not available to listen to:** {len(missing)} pairs ({', '.join(routes)}) could not be generated; "
                      "see the report that came with this sheet."]
    lines += ["", "Sentences:", ""]
    for cls, text in SNIPPETS.items():
        lines.append(f"* **{cls}**: {text}")
    return "\n".join(lines) + "\n"


def verdict_table(manifest: dict) -> str:
    routes = list(VOICES)
    by = {(p["route"], p["class"]): p for p in manifest["pairs"]}
    lines = ["# A4 key: engine x class (do not open before listening)", "",
             f"Total audio: {manifest['total_audio_seconds'] / 60:.1f} min in {len(manifest['pairs']) * 2} clips. "
             "Cell: B clip / A clip; mech = integrity proof + audio checks; ASR = advisory Whisper word error rate of each "
             "side against the intended spoken reading; `!` = touches previously approved audio.", "",
             "| Class | " + " | ".join(ENGINE_NAMES[r] for r in routes) + " |", "|---|" + "---|" * len(routes)]
    for cls in SNIPPETS:
        cells = []
        for route in routes:
            pair = by.get((route, cls))
            if pair is None:
                cells.append("no change")
                continue
            if pair["mechanical"]["A"].get("problems") == ["missing"] or pair["mechanical"]["B"].get("problems") == ["missing"]:
                cells.append("NOT GENERATED")
                continue
            mech = "mech ok" if pair["mechanical_pass"] else "MECH FAIL"
            wer = "/".join("-" if pair["mechanical"][s]["asr_wer_vs_intended_reading"] is None
                           else f"{pair['mechanical'][s]['asr_wer_vs_intended_reading']:.2f}" for s in ("B", "A"))
            mark = "!" if pair["affects_previously_approved"] != ["none"] else ""
            cells.append(f"B={pair['clips']['B']} A={pair['clips']['A']}; {mech}; ASR B/A {wer}{mark}")
        lines.append(f"| {cls} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- ordered listening export

ORDERED = OUT / "listen-ordered"
ORDERED_MAPPING = "ordered-mapping.json"
ENGINE_ORDER = ("chatterbox", "kokoro", "qwen3", "edge_direct")
ENGINE_SHORT = {"chatterbox": "Chatterbox", "kokoro": "Kokoro", "qwen3": "Qwen3", "edge_direct": "Edge"}
CLASS_ORDER = tuple(sorted(SNIPPETS))


def listening_order(pair: dict) -> tuple[str, str]:
    """(first, second) exactly as the blind review sheet lists a pair: by clip number, never by preparation side."""
    first, second = sorted(pair["clips"].values())
    return first, second


def ordered_rows(plan: dict) -> list[dict]:
    """The 60 comparisons in owner order: engine blocks, classes alphabetical; A = first clip, B = second clip."""
    by_pair = {(p["route"], p["class"]): p for p in plan["pairs"]}
    rows = []
    for route in ENGINE_ORDER:
        for cls in CLASS_ORDER:
            pair = by_pair[(route, cls)]
            first, second = listening_order(pair)
            stem = f"{len(rows) + 1:03d}-{ENGINE_SHORT[route]}-{cls}"
            rows.append({"number": len(rows) + 1, "pair": pair["pair"], "route": route, "class": cls,
                         "A": {"file": f"{stem}-A.wav", "source_clip": first},
                         "B": {"file": f"{stem}-B.wav", "source_clip": second}})
    return rows


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: Listening-copy hygiene (owner, G1): a clip ends 120 ms after its last sample above -60 dBFS. -60 dBFS is far below quiet
#: speech, so the cut can only fall in silence; the kept 120 ms holds the final word's decay. Production timing is unchanged.
TRIM_THRESHOLD_DBFS = -60.0
TRIM_KEEP_MS = 120
TRIM_MIN_MS = 50


def trimmed_listening_copy(source: Path) -> tuple[bytes, dict]:
    """The listening copy of ``source``: identical samples, minus terminal silence. Lossless (the source's own PCM)."""
    import io

    import numpy as np
    import soundfile as sf

    info = sf.info(str(source))
    if info.subtype != "PCM_16":
        raise ValueError(f"{source.name}: expected 16-bit PCM, found {info.subtype}")
    samples, rate = sf.read(str(source), dtype="int16", always_2d=True)
    level = np.abs(samples.astype(np.int32)).max(axis=1)
    limit = int(round(32768 * 10 ** (TRIM_THRESHOLD_DBFS / 20)))
    above = np.flatnonzero(level > limit)
    keep = len(samples)
    if above.size:
        candidate = min(len(samples), int(above[-1]) + 1 + int(rate * TRIM_KEEP_MS / 1000))
        if (len(samples) - candidate) * 1000 / rate >= TRIM_MIN_MS and level[candidate:].max(initial=0) <= limit:
            keep = candidate
    buffer = io.BytesIO()
    sf.write(buffer, samples[:keep], rate, subtype="PCM_16", format="WAV")
    return buffer.getvalue(), {"source_seconds": round(len(samples) / rate, 3), "export_seconds": round(keep / rate, 3),
                               "trimmed_ms": round((len(samples) - keep) * 1000 / rate), "kept_samples": keep}


def export_ordered(plan: dict | None = None, listen: Path = LISTEN, out: Path = ORDERED, key: Path = KEY) -> int:
    """Copy the blind clips into one flat, numbered folder, each minus its terminal silence.

    Always made from the untouched clip in ``listen/`` (never from an earlier export), so it never degrades; a copy that
    already holds exactly the expected bytes is left alone. Never synthesizes. An existing review sheet is never replaced:
    it may hold the owner's verdicts.
    """
    plan = load_plan() if plan is None else plan
    rows = ordered_rows(plan)
    pairs = {p["pair"]: p for p in plan["pairs"]}
    sources = [listen / f"{row[s]['source_clip']}.wav" for row in rows for s in ("A", "B")]
    missing = [p.name for p in sources if not p.is_file() or p.stat().st_size == 0]
    if missing:
        print(f"refusing to export: {len(missing)} source clip(s) missing or empty: {missing[:5]}")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    expected = {row[s]["file"] for row in rows for s in ("A", "B")}
    stray = sorted(p.name for p in out.glob("*.wav") if p.name not in expected)
    if stray:
        print(f"refusing to export: {out} holds WAVs this export does not own: {stray[:5]}")
        return 1
    mapping, copied = [], 0
    for row in rows:
        pair = pairs[row["pair"]]
        for slot in ("A", "B"):
            source = listen / f"{row[slot]['source_clip']}.wav"
            target = out / row[slot]["file"]
            data, trim = trimmed_listening_copy(source)
            digest = hashlib.sha256(data).hexdigest()
            if not target.is_file() or _file_sha(target) != digest:
                target.write_bytes(data)
                copied += 1
            problem = verify_listening_copy(source, target, trim["kept_samples"])
            if problem:
                print(problem)
                return 1
            preparation = "off (today)" if row[slot]["source_clip"] == pair["clips"]["A"] else f"{row['class']} expanded"
            mapping.append({"file": row[slot]["file"], "number": row["number"], "listening_slot": slot,
                            "source_clip": row[slot]["source_clip"], "source_sha256": _file_sha(source),
                            "sha256": digest, "pair": row["pair"], "preparation": preparation, **trim})
    write_json(key / ORDERED_MAPPING, {"note": "THE KEY for listen-ordered/. Do not open before listening.",
                                       "trim": {"threshold_dbfs": TRIM_THRESHOLD_DBFS, "keep_ms": TRIM_KEEP_MS,
                                                "min_ms": TRIM_MIN_MS},
                                       "files": mapping})
    sheet = out / "REVIEW-SHEET.md"
    if not sheet.exists():
        sheet.write_text(ordered_review_sheet(plan, rows), encoding="utf-8")
    trimmed = sum(1 for m in mapping if m["trimmed_ms"])
    print(f"{len(rows)} comparisons, {len(mapping)} files ({copied} written, {len(mapping) - copied} already identical); "
          f"{trimmed} trimmed, {len(mapping) - trimmed} kept whole")
    return 0


def verify_listening_copy(source: Path, target: Path, kept: int) -> str | None:
    """The copy must be exactly the source's first ``kept`` samples, and everything removed must be below the threshold."""
    import numpy as np
    import soundfile as sf

    original, rate = sf.read(str(source), dtype="int16", always_2d=True)
    copy, copy_rate = sf.read(str(target), dtype="int16", always_2d=True)
    limit = int(round(32768 * 10 ** (TRIM_THRESHOLD_DBFS / 20)))
    if copy_rate != rate or copy.shape[1] != original.shape[1] or len(copy) != kept:
        return f"{target.name}: format or length differs from its source"
    if not np.array_equal(copy, original[:kept]):
        return f"{target.name}: samples differ from its source"
    if kept < len(original) and int(np.abs(original[kept:].astype(np.int32)).max()) > limit:
        return f"{target.name}: the removed tail of {source.name} was not silent"
    return None


def ordered_review_sheet(plan: dict, rows: list[dict]) -> str:
    pairs = {p["pair"]: p for p in plan["pairs"]}
    lines = ["# Speech preparation listening review (Plan 01B A4, gate G1)", "",
             "Each numbered comparison is the same sentence read twice by the same voice, in two files named "
             "`NNN-...-A.wav` and `NNN-...-B.wav`. The two differ only in how the items under *Listen for* were prepared.",
             "",
             "* Listen to **A** first, then **B**.",
             "* Choose which pronunciation and pacing you prefer and write **A** or **B** under *My verdict*.",
             "* **Same** means both are acceptable; **Neither** means both are unacceptable.",
             "* Use *Notes* for anything mispronounced, skipped, or paced badly.",
             "* Do not open the answer key (`../key/`) before you have finished.",
             "",
             "Comparisons marked *(touches approved audio)* change a reading or pause that was heard and approved before.",
             "",
             "| # | Engine | Class | Listen for | Clip A | Clip B | My verdict | Notes |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        pair = pairs[row["pair"]]
        items = ", ".join(sorted({e["original"] for e in pair["edits"]}, key=pair["source"].find))
        flag = " *(touches approved audio)*" if pair["affects_previously_approved"] != ["none"] else ""
        lines.append(f"| {row['number']:03d} | {ENGINE_NAMES[row['route']]} | {row['class']}{flag} | {items} | "
                     f"{row['A']['file']} | {row['B']['file']} | | |")
    lines += ["", "## The test sentences", "", "Every engine reads the same sentence for a class.", ""]
    for cls in CLASS_ORDER:
        lines.append(f"* **{cls}**: {SNIPPETS[cls]}")
    return "\n".join(lines) + "\n"


EDGE_SMOKE_DIR = OUT / "edge-voice-smoke"
EDGE_SMOKE_SENTENCE = "The lighthouse keeper climbed the stairs and checked the lamp one last time."


def edge_smoke() -> int:
    """Every registered Edge voice through ACT's production Edge entry point (``runner.run_conversion_job``)."""
    import edge_tts

    from tts.voice_registry import VOICES as REGISTRY

    EDGE_SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    version = getattr(edge_tts, "__version__", "unknown")
    results = []
    for entry in (v for v in REGISTRY if v.backend == "edge"):
        target = EDGE_SMOKE_DIR / f"{entry.voice_id}.wav"
        try:
            synthesize("edge_direct", entry.voice_id, EDGE_SMOKE_SENTENCE, None, target, 0, print)
            check = audio_check(target, EDGE_SMOKE_SENTENCE)
        except Exception as exc:  # noqa: BLE001 - every voice is reported
            check = {"pass": False, "problems": [f"{type(exc).__name__}: {exc}"]}
        results.append({"voice_id": entry.voice_id, "label": entry.display_label, "wav": target.name,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None, **check})
        print(f"{entry.voice_id:<24} {'PASS' if check['pass'] else 'FAIL'} {check.get('seconds', '-')} s "
              f"{'; '.join(check['problems'])}")
    write_json(EDGE_SMOKE_DIR / "results.json", {"edge_tts": version, "sentence": EDGE_SMOKE_SENTENCE,
                                                 "entry_point": "tts.epub2tts_edge.runner.run_conversion_job",
                                                 "voices": results})
    return 0 if results and all(r["pass"] for r in results) else 1


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "plan"
    if command == "edge-smoke":
        return edge_smoke()
    if command == "export-ordered":
        return export_ordered()
    if command == "plan":
        plan = build_plan()
        write_json(KEY / "plan.json", plan)
        bad = [p["pair"] for p in plan["pairs"] if not p["integrity_proof"]]
        print(f"{len(plan['pairs'])} pairs ({len(plan['pairs']) * 2} clips); integrity failures: {bad or 'none'}")
        return 1 if bad else 0
    if command == "probe":
        data = kokoro_probe()
        write_json(KEY / "kokoro-probe.json", data)
        for row in data["rows"]:
            print(f"{row['number']:>5} {row['frame']:<26} misaki: {row['misaki_reads_as']:<8} ACT: {row['act_rule']}")
        return 0
    if command == "generate":
        return generate(argv[1:] or None)
    if command == "asr":
        return asr()
    if command == "report":
        return report()
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
