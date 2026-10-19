"""Stage orchestrator for the Plan 01 voice evaluation (dev-only; root interpreter).

Reached through the opt-in ``generate_voice_samples.py --qwen-eval <stage>`` mode; it is never
imported by the application. One explicit stage per invocation, so a missing listening decision
cannot be bypassed by an "all" mode:

    preflight  detect and report; installs, downloads and synthesis never happen
    prepare    isolated venv + pinned wheels + pinned model snapshots + missing Kokoro voice files
    transcribe local Whisper drafts and the owner review package for the six reference WAVs
    pilot      small, clearly labelled technical calibration (never part of the comparison)
    short      the 27-row short suite (``--eval-group`` limits it; unattempted groups stay pending)
    long       only the four voices in the owner's recorded ``long-selection.json``
    asr-check  optional Whisper read-back of finished recordings; flags suspect omissions, never approves
    report     rebuild the listening index and manifest digest without loading any model

Qwen runs in the isolated evaluation venv, Chatterbox and Kokoro through the ROOT interpreter, as
sequential subprocesses started from argument lists with absolute interpreters. A worker failure
leaves a truthful manifest row; it never erases other rows. Statuses are mechanical: success is
"needs-listening", never approval.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qwen_eval_assets as assets  # noqa: E402
import qwen_eval_core as core  # noqa: E402
import qwen_eval_corpus as corpus  # noqa: E402

UNIVERSAL = core.REPO_ROOT / "scripts" / "Universal"
if str(UNIVERSAL) not in sys.path:
    sys.path.insert(0, str(UNIVERSAL))

STAGES = ("preflight", "prepare", "transcribe", "pilot", "short", "long", "asr-check", "report")
GROUP_CHOICES = ("all", "qwen", "qwen-preset", "qwen-clone", "chatterbox", "kokoro")
SUBDIRS = ("corpus", "references", "transcripts", "presets", "qwen-clones", "chatterbox-baselines",
           "kokoro", "long-form", "chunks", "pilot", "logs", "jobs", "preflight")
GROUP_FOLDER = {core.GROUP_QWEN_PRESET: "presets", core.GROUP_QWEN_CLONE: "qwen-clones",
                core.GROUP_CHATTERBOX: "chatterbox-baselines", core.GROUP_KOKORO: "kokoro"}
CU128_INDEX = "https://download.pytorch.org/whl/cu128"
PYPI_INDEX = "https://pypi.org/simple"
PINNED_REQUIREMENTS = ("torch==2.10.0", "torchaudio==2.10.0", "qwen-tts==0.1.1")
CONSTRAINTS = HERE / "qwen_eval_constraints.txt"
WORKER = HERE / "qwen_eval_worker.py"
BASELINE_WORKER = HERE / "qwen_eval_baseline_worker.py"
KOKORO_REPO = "hexgrad/Kokoro-82M"

DEFAULT_PROFILE = {
    "dtype": "bfloat16", "attn": "sdpa", "device": "cuda:0", "language": "English",
    "gap_ms": core.GAP_MS, "end_silence_ms": core.END_SILENCE_MS, "seed_base": core.SEED_BASE,
    "max_chars": core.DEFAULT_MAX_CHARS,
}
TEXT_FILES = {"eval_short": "short.txt", "eval_long": "long.txt"}
SUITE_TEXT = {"short": "eval_short", "long": "eval_long", "pilot-short": "eval_short", "pilot-long": "eval_long"}


def say(message: str) -> None:
    print(f"[qwen-eval {time.strftime('%H:%M:%S')}] {message}", flush=True)


# --------------------------------------------------------------------------- #
# Run layout, profile and frozen corpus
# --------------------------------------------------------------------------- #
class Run:
    def __init__(self, run_id: str, work_dir: Path = core.WORK_DIR):
        self.id, self.work = run_id, Path(work_dir)
        self.dir = self.work / "runs" / run_id
        for sub in SUBDIRS:
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.manifest = core.Manifest(self.dir / "manifest.jsonl")

    def rel(self, path: Path | str) -> str:
        return Path(path).resolve().relative_to(self.dir.resolve()).as_posix()


def load_profile(run: Run) -> dict:
    path = run.dir / "profile.json"
    profile = dict(DEFAULT_PROFILE)
    if path.is_file():
        profile.update(json.loads(path.read_text(encoding="utf-8")).get("profile", {}))
    return profile


def save_profile(run: Run, profile: dict, calibration: dict | None = None) -> None:
    core.atomic_write_text(run.dir / "profile.json", json.dumps(
        {"profile": profile, "calibration": calibration or {}, "recorded": core.now_iso()}, indent=2))


def freeze_corpus(run: Run, profile: dict) -> dict:
    """Write the canonical texts once, byte-exact, and refuse to continue if they ever change."""
    frozen_path = run.dir / "corpus" / "frozen.json"
    current = corpus.corpus_manifest()
    if frozen_path.is_file():
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        for name, info in current.items():
            if frozen["passages"][name]["sha256"] != info["sha256"]:
                raise RuntimeError(f"frozen passage {name!r} no longer matches the corpus module; "
                                   "create a new run instead of changing frozen text")
        if frozen["max_chars"] != profile["max_chars"]:
            raise RuntimeError("frozen chunk ceiling differs from the active profile; start a new run")
        return frozen
    plans = {}
    for name, passage in corpus.PASSAGES.items():
        (run.dir / "corpus" / TEXT_FILES[name]).write_bytes(passage.text.encode("utf-8"))
        chunks = core.plan_chunks(passage.text, profile["max_chars"])
        plans[name] = {"chunks": len(chunks), "plan_sha256": core.plan_hash(chunks),
                       "boundaries": {b: sum(1 for c in chunks if c.boundary == b) for b in {c.boundary for c in chunks}}}
    frozen = {"frozen": core.now_iso(), "git_sha": git_head(), "max_chars": profile["max_chars"],
              "passages": current, "plans": plans, "files": TEXT_FILES}
    core.atomic_write_text(frozen_path, json.dumps(frozen, indent=2))
    return frozen


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(core.REPO_ROOT), capture_output=True,
                             text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# --------------------------------------------------------------------------- #
# References and transcripts
# --------------------------------------------------------------------------- #
def reference_snapshot() -> dict[str, dict]:
    """Path, registered and actual SHA-256, mtime and PCM properties of the six source WAVs."""
    import soundfile as sf

    from tts import chatterbox_synth as cs

    state: dict[str, dict] = {}
    for display, voice_id in core.REFERENCE_VOICE_IDS:
        voice, path = cs.get_reference_voice(voice_id), cs.reference_source_path(voice_id)
        info = {"voice_id": voice_id, "path": path.relative_to(core.REPO_ROOT).as_posix(),
                "registered_sha256": voice.source_sha256, "exists": path.is_file(), "ok": False}
        if info["exists"]:
            stat, meta = path.stat(), sf.info(str(path))
            info.update(sha256=core.sha256_file(path), mtime_ns=stat.st_mtime_ns, bytes=stat.st_size,
                        subtype=meta.subtype, channels=meta.channels, samplerate=meta.samplerate,
                        frames=meta.frames, duration_s=round(meta.duration, 6))
            info["ok"] = (info["sha256"] == voice.source_sha256 and meta.subtype == "PCM_16"
                          and meta.channels == 1 and meta.samplerate == 24000)
        state[display] = info
    return state


def compare_references(before: dict, after: dict) -> list[str]:
    problems = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if not a or not b:
            problems.append(f"{name}: reference appeared or disappeared during the run")
        elif not a["ok"]:
            problems.append(f"{name}: reference is missing or does not match its registered hash/properties")
        elif (b.get("sha256"), b.get("mtime_ns")) != (a.get("sha256"), a.get("mtime_ns")):
            problems.append(f"{name}: reference changed during the run")
    return problems


def transcripts_dir(run: Run) -> Path:
    return run.dir / "transcripts"


def approved_transcript(run: Run, display: str) -> tuple[str | None, str]:
    """The owner-approved transcript for one reference, or ``(None, why not)``. Never auto-approves."""
    path = transcripts_dir(run) / "verified.json"
    if not path.is_file():
        return None, "no transcript review package yet (run the transcribe stage)"
    entry = json.loads(path.read_text(encoding="utf-8")).get(display)
    if not isinstance(entry, dict):
        return None, "no transcript entry"
    if entry.get("approved") is not True:
        return None, "transcript is a Whisper draft awaiting owner verification"
    text = (entry.get("text") or "").strip()
    return (text, "ok") if text else (None, "approved transcript is empty")


# --------------------------------------------------------------------------- #
# Worker supervision
# --------------------------------------------------------------------------- #
def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a worker and anything it started (the Windows venv launcher spawns a child)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


def run_worker(run: Run, python: Path, script: Path, job: dict, label: str, env: dict, on_event) -> int:
    """Run one worker to completion, feeding its ``@@EVENT`` lines to ``on_event``."""
    if not Path(python).is_file():
        raise FileNotFoundError(f"interpreter not found: {python}")
    cancel = run.dir / "jobs" / f"{label}.cancel"
    cancel.unlink(missing_ok=True)
    job = dict(job, cancel_file=str(cancel))
    job_path = run.dir / "jobs" / f"{label}.json"
    core.atomic_write_text(job_path, json.dumps(job, indent=1))
    log_path = run.dir / "logs" / f"{label}.log"
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen([str(python), str(script), str(job_path)], cwd=str(core.REPO_ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
        try:
            for line in proc.stdout:
                log.write(line)
                event = core.parse_event(line.rstrip("\n"))
                if event:
                    on_event(event)
            return proc.wait()
        except KeyboardInterrupt:
            say("interrupt received: asking the worker to stop between chunks")
            cancel.write_text("cancel", encoding="utf-8")
            try:
                return proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                return 130
        finally:
            kill_tree(proc)


# --------------------------------------------------------------------------- #
# Row location, identity and recording
# --------------------------------------------------------------------------- #
def row_location(row: dict) -> tuple[str, str]:
    """(folder relative to the run, file stem) for a row's final recordings."""
    if row.get("out_folder"):
        return row["out_folder"], row["display"]
    if row["suite"] == "long":
        kind = "preset" if row["group"] == core.GROUP_QWEN_PRESET else "clone"
        return "long-form", f"{row['display']}-{kind}"
    return GROUP_FOLDER[row["group"]], row["display"]


def file_sha(*names: str) -> str:
    """Hash of tooling or engine source files, so a code change never reuses a stale result."""
    digest = core.identity_hash({n: core.sha256_file(p) for n, p in sorted(
        (n, (HERE / n) if (HERE / n).is_file() else (UNIVERSAL / "tts" / n)) for n in names)})
    return digest[:16]


def ref_name(row: dict) -> str:
    return row.get("reference_name") or row["display"]


def model_identity(key: str) -> dict:
    spec, record = assets.ASSETS[key], assets.load_record().get(key, {})
    gen = record.get("files", {}).get("generation_config.json", {})
    return {"repo": spec["repo"], "revision": spec["revision"], "generation_config_sha256": gen.get("sha256")}


def row_identity(row: dict, *, text: dict, plan_sha: str, profile: dict, extra: dict) -> str:
    return core.identity_hash({"engine": row["engine"], "voice": row["voice_id"], "text": text["sha256"],
                               "plan": plan_sha, "profile": profile, **extra})


def text_info(name: str) -> dict:
    p = corpus.PASSAGES[name]
    return {"name": name, "chars": p.char_count, "words": p.word_count, "sha256": p.sha256}


class Tracker:
    """Applies a worker's events to the manifest and finalises rows (MP3 + final-artifact checks)."""

    def __init__(self, run: Run, manifest: core.Manifest, rows: dict[str, dict], finalize):
        self.run, self.manifest, self.rows, self.finalize = run, manifest, rows, finalize
        self.job: dict = {}
        self.open: set[str] = set()

    def __call__(self, ev: dict) -> None:
        kind = ev["event"]
        if kind in ("model_loaded", "engine", "probe"):
            self.job.update({k: v for k, v in ev.items() if k != "event"})
        elif kind == "row_start" and ev["row_id"] in self.rows:
            self.open.add(ev["row_id"])
            self.manifest.update(ev["row_id"], status="running", started=core.now_iso(),
                                 progress={"chunks_done": 0, "chunks": ev.get("chunks")})
            say(f"{ev['row_id']}: started ({ev.get('chunks')} chunks)")
        elif kind == "chunk_done" and ev["row_id"] in self.rows:
            self.manifest.update(ev["row_id"], progress={"chunks_done": ev["chunk"] + 1, "chunks": ev["of"]})
            if ev["chunk"] % 5 == 4 or ev["chunk"] + 1 == ev["of"]:
                say(f"{ev['row_id']}: chunk {ev['chunk'] + 1}/{ev['of']} ({ev['audio_s']}s audio in {ev['gen_s']}s)")
        elif kind == "row_done" and ev["row_id"] in self.rows:
            self.open.discard(ev["row_id"])
            try:
                self.finalize(self, ev)
            except Exception as exc:  # noqa: BLE001 - a finalisation error is a row failure, not a crash
                self.manifest.update(ev["row_id"], status="failed", status_reason=f"finalisation failed: "
                                     f"{type(exc).__name__}: {exc}", finished=core.now_iso())
        elif kind in ("row_failed", "row_canceled") and ev["row_id"] in self.rows:
            self.open.discard(ev["row_id"])
            fields = {"status": "canceled" if kind == "row_canceled" else "failed", "status_reason": ev.get("reason", ""),
                      "finished": core.now_iso()}
            if ev.get("outputs"):
                fields["diagnostic_outputs"] = ev["outputs"]
            if ev.get("chunk_results"):
                fields["chunk_results"] = ev["chunk_results"]
            self.manifest.update(ev["row_id"], **fields)
            say(f"{ev['row_id']}: {fields['status']} - {fields['status_reason'][:160]}")
        elif kind in ("load_failed", "inventory_mismatch"):
            say(f"worker reported {kind}: {str(ev)[:300]}")

    def settle(self, returncode: int) -> None:
        """Rows still open when the worker exits never completed: record that, do not guess."""
        for row_id in sorted(self.open):
            self.manifest.update(row_id, status="failed", finished=core.now_iso(),
                                 status_reason=f"worker exited with code {returncode} before finishing this row")
        self.open.clear()


def encode_mp3(run: Run, wav: Path, mp3: Path) -> list[str]:
    """One MP3 encode per completed recording, from the lossless WAV, with the engines' own options."""
    import numpy as np
    import soundfile as sf
    from pydub import AudioSegment

    from shared import ffmpeg_utils

    ffmpeg_utils.configure_pydub()
    notes: list[str] = []
    source, temp = wav, None
    if sf.info(str(wav)).subtype != "PCM_16":
        data, rate = core.read_wav(wav)
        temp = run.work / "temp" / f"{wav.stem}-mp3-source.wav"
        temp.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(temp), np.clip(data, -1.0, 1.0), rate, subtype="PCM_16")
        source = temp
        notes.append("the WAV exceeds full scale and was left unclipped; only its MP3 copy was clipped")
    try:
        mp3.parent.mkdir(parents=True, exist_ok=True)
        AudioSegment.from_wav(str(source)).export(str(mp3), **ffmpeg_utils.mp3_export_options())
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return notes


def final_checks(mp3: Path, chars: int) -> tuple[dict, list[str], dict]:
    """Strict decode, container/decoded duration, peak, clipping and silences via the repo harness."""
    from tts import generate_voice_samples as gvs

    measured = gvs.measure_final_artifact(mp3)
    problems, derived = gvs.judge_final_artifact(measured, chars)
    return measured, problems, derived


def record_success(tracker: Tracker, ev: dict, *, outputs: dict, provenance: dict, timing: dict,
                   warnings: list[str], extras: dict) -> None:
    run, row_id = tracker.run, ev["row_id"]
    row = tracker.rows[row_id]
    mp3 = run.dir / outputs["mp3"]["path"]
    measured, problems, derived = final_checks(mp3, row["text"]["chars"])
    outputs["mp3"].update(bytes=mp3.stat().st_size, sha256=core.sha256_file(mp3))
    fields = dict(outputs=outputs, final_checks={**measured, **derived, "problems": problems},
                  warnings=warnings + [f"final-artifact: {p}" for p in problems], provenance=provenance,
                  timing=timing, finished=core.now_iso(), **extras)
    if not measured["decode_ok"]:
        tracker.manifest.update(row_id, status="failed", human_review="not-applicable",
                                status_reason=f"final MP3 failed its strict decode: {measured['decode_errors'][:200]}",
                                **fields)
        say(f"{row_id}: FAILED strict decode")
        return
    tracker.manifest.update(row_id, status="succeeded", status_reason="", human_review="needs-listening",
                            identity=row["identity"], **fields)
    say(f"{row_id}: succeeded ({timing.get('audible_s')}s audible, {len(fields['warnings'])} warning(s))")


# --------------------------------------------------------------------------- #
# Group execution
# --------------------------------------------------------------------------- #
def prepare_rows(run: Run, manifest: core.Manifest, rows: list[dict], *, text_name: str, plan_sha: str,
                 profile: dict, identity_extra, block_reason) -> list[dict]:
    """Decide for each row: reuse, block, or run. Returns the rows to hand to a worker."""
    todo = []
    info = text_info(text_name)
    for row in rows:
        live = manifest.get(row["row_id"])
        live.setdefault("text", info)
        reason = block_reason(live)
        if reason:
            manifest.update(row["row_id"], status="blocked", status_reason=reason, text=info)
            say(f"{row['row_id']}: blocked - {reason}")
            continue
        extra = identity_extra(live)
        identity = row_identity(live, text=info, plan_sha=plan_sha, profile=profile, extra=extra)
        if core.can_resume(live, identity, run.dir):
            say(f"{row['row_id']}: reusing identical completed result")
            continue
        if live["status"] != "pending":
            manifest.retire_attempt(row["row_id"], "rerun requested; identity changed or prior attempt incomplete")
        manifest.update(row["row_id"], identity=identity, text=info, status="pending", status_reason="",
                        attempt=len(manifest.get(row["row_id"])["attempts"]) + 1)
        todo.append(manifest.get(row["row_id"]))
    return todo


def reference_blocker(snapshot: dict):
    by_voice = {info["voice_id"]: (name, info) for name, info in snapshot.items()}

    def check(row: dict) -> str | None:
        if row["group"] in (core.GROUP_QWEN_CLONE, core.GROUP_CHATTERBOX):
            name, info = by_voice[row["voice_id"]]
            if not info["ok"]:
                return f"source-integrity failure for reference {name}: missing or not matching its registered hash"
        return None

    return check


def qwen_identity_extra(run: Run, row: dict, mode: str, key: str, snapshot: dict) -> dict:
    """Everything beyond text/plan/profile that must match for a Qwen result to be reusable."""
    data = {"model": model_identity(key), "pipeline": core.PIPELINE_REVISION,
            "packages": core.identity_hash(parse_constraints())}
    if mode == "clone":
        ref = snapshot[ref_name(row)]
        transcript, _ = approved_transcript(run, ref_name(row))
        data.update(reference_sha256=ref["sha256"], transcript_sha256=core.identity_hash({"t": transcript}))
    return data


def root_identity_extra(row: dict, engine: str, snapshot: dict) -> dict:
    """The same for Chatterbox/Kokoro: the production engine source and the reference recording."""
    data = {"engine_label": engine, "engine_source": file_sha(f"{engine}_synth.py"), "pipeline": core.PIPELINE_REVISION}
    if engine == "chatterbox":
        data["reference_sha256"] = snapshot[ref_name(row)]["sha256"]
    return data


def current_identity(run: Run, row: dict, profile: dict, snapshot: dict) -> str:
    """The identity a main-suite row would get if it were run now (used to rebase after output-neutral edits)."""
    name = SUITE_TEXT[row["suite"]]
    if row["group"] in (core.GROUP_QWEN_PRESET, core.GROUP_QWEN_CLONE):
        preset = row["group"] == core.GROUP_QWEN_PRESET
        mode, key = ("custom_voice", "qwen-customvoice") if preset else ("clone", "qwen-base")
        plan_sha = core.plan_hash(core.plan_chunks(corpus.PASSAGES[name].text, profile["max_chars"]))
        extra, used = qwen_identity_extra(run, row, mode, key, snapshot), profile
    else:
        plan_sha, extra, used = "engine-production-chunker", root_identity_extra(row, row["group"], snapshot), \
            {"root": row["group"]}
    return row_identity(row, text=text_info(name), plan_sha=plan_sha, profile=used, extra=extra)


def rebase_identities(run: Run, profile: dict, snapshot: dict, reason: str) -> list[str]:
    """Recompute stored identities after a deliberate, output-neutral tooling change.

    Only rows that are succeeded AND whose files are intact are rebased, and the old identity is kept in
    ``identity_history`` with the reason, so a stale result can never be passed off as a fresh one.
    """
    changed = []
    for row in run.manifest.rows.values():
        if row["status"] != "succeeded" or row["suite"] not in SUITE_TEXT or not core.outputs_intact(row, run.dir):
            continue
        new = current_identity(run, row, profile, snapshot)
        if new != row.get("identity"):
            history = list(row.get("identity_history") or []) + [
                {"identity": row.get("identity"), "rebased": core.now_iso(), "reason": reason}]
            run.manifest.update(row["row_id"], identity=new, identity_history=history)
            changed.append(row["row_id"])
    return changed


def run_qwen_group(run: Run, rows: list[dict], *, mode: str, suite_text: str, profile: dict, manifest: core.Manifest,
                   snapshot: dict, label: str, offline: bool = True) -> None:
    key = "qwen-customvoice" if mode == "custom_voice" else "qwen-base"
    py = core.eval_python(run.work)
    frozen_name = SUITE_TEXT.get(suite_text, suite_text)
    passage = corpus.PASSAGES[frozen_name]
    chunks = core.plan_chunks(passage.text, profile["max_chars"])
    record = assets.load_record().get(key)

    def blocker(row: dict) -> str | None:
        if not py.is_file():
            return "isolated evaluation environment is missing (run the prepare stage)"
        if not record:
            return f"model {key} was never acquired (run the prepare stage)"
        problems = assets.snapshot_problems(key, record["files"], verify_hash=False)
        if problems:
            return "model snapshot is incomplete: " + "; ".join(problems[:3])
        if mode == "clone":
            refs = reference_blocker(snapshot)(row)
            if refs:
                return refs
            text, why = approved_transcript(run, ref_name(row))
            if text is None:
                return f"reference transcript not verified: {why}"
        return None

    def extra(row: dict) -> dict:
        return qwen_identity_extra(run, row, mode, key, snapshot)

    todo = prepare_rows(run, manifest, rows, text_name=frozen_name, plan_sha=core.plan_hash(chunks),
                        profile=profile, identity_extra=extra, block_reason=blocker)
    if not todo:
        return
    job_rows, by_id = [], {r["row_id"]: r for r in todo}
    for row in todo:
        folder, stem = row_location(row)
        entry = {"row_id": row["row_id"], "out_dir": str(run.dir / folder), "file_name": stem + ".wav",
                 "attempt": row.get("attempt", 1), "chunks": [c.to_dict() for c in chunks],
                 "target_seconds": list(corpus.AUDIO_TARGET_SECONDS[frozen_name])}
        if mode == "custom_voice":
            entry["speaker"] = row["voice_id"]
        else:
            ref = snapshot[ref_name(row)]
            entry["reference_wav"] = str(core.REPO_ROOT / ref["path"])
            entry["reference_text"], _ = approved_transcript(run, ref_name(row))
        job_rows.append(entry)

    def finalize(tracker: Tracker, ev: dict) -> None:
        row = tracker.rows[ev["row_id"]]
        wav_info = ev["wav"]
        wav, mp3 = run.dir / wav_info["path"], (run.dir / wav_info["path"]).with_suffix(".mp3")
        notes = encode_mp3(run, wav, mp3)
        provenance = {
            "engine": "qwen3-tts", "model": {**model_identity(key), "license": assets.ASSETS[key]["license"],
                                              "snapshot": record["snapshot"]},
            "packages": tracker.job.get("versions"), "gpu": tracker.job.get("gpu"),
            "profile": {k: profile[k] for k in ("dtype", "attn", "device", "language", "max_chars", "gap_ms",
                                                "end_silence_ms", "seed_base")},
            "effective_generation": tracker.job.get("effective_generation"),
            "seed_policy": "sha256(seed_base|row_id|chunk_index|attempt)[:4] & 0x7fffffff, per chunk",
            "eos_capture": tracker.job.get("eos_capture"), "offline_flags": offline,
            "mode": ("custom voice preset, no style instruction" if mode == "custom_voice" else
                     "voice clone, transcript-conditioned (x_vector_only_mode=False)"),
            "speaker_api_id": row["voice_id"] if mode == "custom_voice" else None,
        }
        if mode == "clone":
            ref = snapshot[ref_name(row)]
            text, _ = approved_transcript(run, ref_name(row))
            provenance["reference"] = {"path": ref["path"], "sha256": ref["sha256"],
                                       "transcript_sha256": core.identity_hash({"t": text}),
                                       "transcript_state": "owner-approved"}
        join_stats = ev["joins"]
        timing = {"load_s": tracker.job.get("load_s"), "gen_s": ev["gen_s"], "wall_s": ev["wall_s"],
                  "audible_s": ev["audible_s"], "total_s": ev.get("total_s"),
                  "rtf": round(ev["gen_s"] / ev["audible_s"], 3) if ev["audible_s"] else None,
                  "peak_alloc_mib": ev.get("peak_alloc_mib"), "peak_reserved_mib": ev.get("peak_reserved_mib")}
        record_success(tracker, ev, outputs={"wav": wav_info, "mp3": {"path": run.rel(mp3), "bytes": 0, "sha256": ""}},
                       provenance=provenance, timing=timing, warnings=list(ev["warnings"]) + notes,
                       extras={"chunk_plan": {"count": len(chunks), "plan_sha256": core.plan_hash(chunks),
                                              "max_chars": profile["max_chars"], "join_file": ev["join_file"]},
                               "joins": join_stats, "chunk_results": ev["chunk_results"],
                               "measurements": ev["measurements"]})

    tracker = Tracker(run, manifest, by_id, finalize)
    env = core.child_env("qwen", work_dir=run.work, offline=offline)
    job = {"kind": "synth", "mode": mode, "model_dir": str(assets.snapshot_dir(key)), "run_dir": str(run.dir),
           "profile": profile, "rows": job_rows}
    say(f"starting Qwen worker ({mode}) for {len(job_rows)} row(s)")
    code = run_worker(run, py, WORKER, job, label, env, tracker)
    tracker.settle(code)


def run_root_group(run: Run, rows: list[dict], *, engine: str, suite_text: str, profile: dict, manifest: core.Manifest,
                   snapshot: dict, label: str) -> None:
    frozen_name = SUITE_TEXT.get(suite_text, suite_text)
    passage = corpus.PASSAGES[frozen_name]
    # Each engine uses its own production chunker; the expected chunk count is recorded by the worker.
    py = core.root_python()
    hf_home = str(core.REPO_ROOT / "files" / "runtime-data" / "models" / "huggingface")
    text_path = run.dir / "corpus" / TEXT_FILES[frozen_name] if suite_text in ("short", "long") else \
        run.dir / "pilot" / TEXT_FILES[frozen_name]
    text_path.write_bytes(passage.text.encode("utf-8"))

    def blocker(row: dict) -> str | None:
        if not py.is_file():
            return "root interpreter .venv is missing"
        if engine == "chatterbox":
            from tts import chatterbox_synth as cs

            ok, why = cs.engine_status(row["voice_id"])
            return None if ok else why
        asset = Path(hf_home) / "hub" / "models--hexgrad--Kokoro-82M" / "snapshots"
        if not any((s / "voices" / f"{row['voice_id']}.pt").is_file() for s in asset.glob("*")):
            return f"official voice asset voices/{row['voice_id']}.pt is not cached (run the prepare stage)"
        return None

    def extra(row: dict) -> dict:
        return root_identity_extra(row, engine, snapshot)

    todo = prepare_rows(run, manifest, rows, text_name=frozen_name, plan_sha="engine-production-chunker",
                        profile={"root": engine}, identity_extra=extra, block_reason=blocker)
    if not todo:
        return
    job_rows = []
    for row in todo:
        folder, stem = row_location(row)
        job_rows.append({"row_id": row["row_id"], "voice_id": row["voice_id"], "out_dir": folder, "stem": stem,
                         "lang_code": row.get("lang_code")})

    def finalize(tracker: Tracker, ev: dict) -> None:
        row = tracker.rows[ev["row_id"]]
        outputs = ev["outputs"]
        audible = max(0.0, ev["audible_s"])
        warnings = list(ev["warnings"])
        target = corpus.AUDIO_TARGET_SECONDS[frozen_name]
        if not target[0] <= audible <= target[1]:
            warnings.append(f"audible duration {audible:.1f}s (estimated) outside the {target[0]}-{target[1]}s target")
        provenance = {"engine": engine, "worker_engine_info": tracker.job, "chunk_policy": "engine production chunker",
                      "ordering": "production file path, unseeded (production behaviour)",
                      "asset": ev.get("asset"), "offline_flags": True,
                      "pcm_capture": "harness-only wrapper around _export_mp3, restored after each call"}
        if engine == "chatterbox":
            ref = snapshot[ref_name(row)]
            provenance["reference"] = {"path": ref["path"], "sha256": ref["sha256"]}
        else:
            provenance["speed"] = 1.0
            provenance["lang_code"] = row.get("lang_code")
            provenance["act_status"] = row.get("act_status")
        timing = {"wall_s": ev["wall_s"], "audible_s": round(audible, 3),
                  "rtf": round(ev["wall_s"] / audible, 3) if audible else None}
        record_success(tracker, ev, outputs=outputs, provenance=provenance, timing=timing, warnings=warnings,
                       extras={"chunk_plan": {"engine_expected_chunks": ev.get("expected_chunks")},
                               "measurements": ev["measurements"], "chunk_results": ev.get("chunk_results"),
                               "engine_retries": ev.get("engine_retries")})

    tracker = Tracker(run, manifest, {r["row_id"]: r for r in todo}, finalize)
    env = core.child_env("root", work_dir=run.work, offline=True)
    env["HF_HOME"] = hf_home
    env["HUGGINGFACE_HUB_CACHE"] = str(Path(hf_home) / "hub")
    job = {"engine": engine, "run_dir": str(run.dir), "text_file": str(text_path), "rows": job_rows}
    say(f"starting {engine} worker (root interpreter) for {len(job_rows)} row(s)")
    code = run_worker(run, py, BASELINE_WORKER, job, label, env, tracker)
    tracker.settle(code)


# --------------------------------------------------------------------------- #
# Listening index and manifest digest (no model is loaded)
# --------------------------------------------------------------------------- #
RUBRIC = ("Pleasantness", "Clarity", "Natural pacing", "Stable narrator identity", "Repeated-name pronunciation",
          "Dialogue", "Clone similarity (clones only)", "Joins / seams", "Long-session fatigue (sustained only)")


def _link(label: str, outputs: dict | None, key: str) -> str:
    if not outputs or key not in outputs:
        return "-"
    return f"[{label}]({outputs[key]['path']})"


def _dur(row: dict) -> str:
    audible = (row.get("timing") or {}).get("audible_s")
    return f"{audible:.0f}s" if audible else "-"


def row_warnings(row: dict) -> list[str]:
    """Recorded warnings plus any engine retries, which are evidence the listener should know about."""
    warnings = list(row.get("warnings") or [])
    retries = len(row.get("engine_retries") or [])
    if retries:
        warnings.append(f"the engine retried {retries} generation draw(s) after a pathological internal silence "
                        "(production retry policy; the audio is the accepted draw)")
    return warnings


def _state(row: dict) -> str:
    if row["status"] == "succeeded":
        count = len(row_warnings(row))
        return "needs listening" + (f" ({count} warning(s))" if count else "")
    reason = (row.get("status_reason") or "").replace("|", "/")[:110]
    return f"**{row['status']}**" + (f": {reason}" if reason else "")


def render_listening_index(rows: list[dict], run_id: str, frozen: dict | None, transcripts: dict) -> str:
    by_id = {r["row_id"]: r for r in rows}
    short = [r for r in rows if r["suite"] == "short"]
    counts = {g: {s: sum(1 for r in short if r["group"] == g and r["status"] == s) for s in core.STATUSES}
              for g in core.GROUPS}
    lines = [f"# Listening index - run `{run_id}`", "",
             "Local evidence (git-ignored). Audio opens straight from these links; nothing here is an approval.",
             "A row marked *needs listening* is only technically complete. Mechanical warnings are listed "
             "separately from your judgements.", "",
             "## How to listen", "",
             "1. Open this file in an editor or Markdown preview, or browse the folders next to it.",
             "2. **WAV** links are the lossless, play-ready evidence; **MP3** links are the convenient copies.",
             "3. On Windows, double-click a file (or Ctrl+click a link) to open it in your default player.",
             "4. Listen to each voice's passage once, score it with the rubric below, and note timestamps of "
             "omissions, repetitions or odd joins.", "",
             "Read-along text (identical for every voice): [short passage](corpus/short.txt), "
             "[long passage](corpus/long.txt). Reference-transcript review: [review sheet](transcripts/review-sheet.md).", "",
             "## Decisions needed from you", "",
             "1. **Reference transcripts** - verify or correct the six Whisper drafts in the "
             "[review sheet](transcripts/review-sheet.md); no clone is made from an unverified transcript.",
             "2. **Long-form comparison** - Aiden and Dylan are already fixed. Name **one female CustomVoice preset** "
             "(" + ", ".join(n for n, _ in core.QWEN_PRESETS if core.is_female_preset(n)) +
             ") and **one verified clone** (a reference whose transcript you approved).",
             "3. **Kokoro candidates** - for each of `am_fenrir`, `am_puck`, `am_onyx`, `bm_daniel`: retain, reject or "
             "defer (listening feedback alone changes no ACT code or voice list).", "",
             "## Inventory (short suite, 27 expected rows)", "",
             "| Group | Expected | Succeeded | Failed | Blocked | Pending / running |", "|---|---|---|---|---|---|"]
    names = {core.GROUP_QWEN_PRESET: "Qwen3-TTS CustomVoice presets", core.GROUP_QWEN_CLONE: "Qwen3-TTS Base clones",
             core.GROUP_CHATTERBOX: "Chatterbox baselines", core.GROUP_KOKORO: "Kokoro"}
    for g in core.GROUPS:
        c = counts[g]
        lines.append(f"| {names[g]} | {sum(c.values())} | {c['succeeded']} | {c['failed']} | {c['blocked']} | "
                     f"{c['pending'] + c['running'] + c['canceled']} |")
    if frozen:
        p = frozen["passages"]
        lines += ["", f"Frozen passages: short {p['eval_short']['words']} words (sha256 `{p['eval_short']['sha256'][:12]}`), "
                      f"long {p['eval_long']['words']} words (sha256 `{p['eval_long']['sha256'][:12]}`)."]

    lines += ["", "## 1. Qwen3-TTS CustomVoice presets (English, no style instruction)", "",
              "Upstream recommends each voice's native language; these are all English tests by design.", "",
              "| Voice | Model-card description | Native language | WAV | MP3 | Audible | State |",
              "|---|---|---|---|---|---|---|"]
    for r in short:
        if r["group"] == core.GROUP_QWEN_PRESET:
            o = r.get("outputs")
            lines.append(f"| {r['display']} | {core.QWEN_PRESET_DESCRIPTIONS.get(r['display'], '')} | "
                         f"{r.get('native_language', '')} | {_link('WAV', o, 'wav')} | "
                         f"{_link('MP3', o, 'mp3')} | {_dur(r)} | {_state(r)} |")

    lines += ["", "## 2. Qwen3-TTS clones paired with the current Chatterbox baselines", "",
              "Each reference is the same bundled 15-second recording. A clone is transcript-conditioned only "
              "after you approve that reference's transcript.", "",
              "| Reference | Transcript | Qwen clone WAV | Qwen MP3 | Chatterbox WAV | Chatterbox MP3 | Qwen state | "
              "Chatterbox state |", "|---|---|---|---|---|---|---|---|"]
    for display, voice_id in core.REFERENCE_VOICE_IDS:
        clone, base = by_id.get(core.clone_row_id(display)), by_id.get(voice_id)
        if not clone or not base:
            continue
        lines.append(f"| {display} | {transcripts.get(display, 'unknown')} | {_link('WAV', clone.get('outputs'), 'wav')} | "
                     f"{_link('MP3', clone.get('outputs'), 'mp3')} | {_link('WAV', base.get('outputs'), 'wav')} | "
                     f"{_link('MP3', base.get('outputs'), 'mp3')} | {_state(clone)} | {_state(base)} |")

    lines += ["", "## 3. Kokoro: existing ACT voices vs new candidates", "",
              "Evaluation only: none of the candidates is registered in ACT. Existing voices are the comparison "
              "baseline; each candidate needs your separate retain / reject / defer decision.", "",
              "| Voice | ACT status | Pipeline | WAV | MP3 | Audible | State |", "|---|---|---|---|---|---|---|"]
    for r in short:
        if r["group"] == core.GROUP_KOKORO:
            o = r.get("outputs")
            status = "existing (baseline)" if r.get("act_status") == "existing" else "NEW candidate"
            lines.append(f"| `{r['display']}` | {status} | {'American (a)' if r.get('lang_code') == 'a' else 'British (b)'} | "
                         f"{_link('WAV', o, 'wav')} | {_link('MP3', o, 'mp3')} | {_dur(r)} | {_state(r)} |")

    longs = [r for r in rows if r["suite"] == "long"]
    if longs:
        lines += ["", "## 4. Sustained narration (identical complete passage)", "",
                  "| Voice | Kind | WAV | MP3 | Audible | State |", "|---|---|---|---|---|---|"]
        for r in longs:
            o = r.get("outputs")
            lines.append(f"| {r['display']} | {'preset' if r['group'] == core.GROUP_QWEN_PRESET else 'clone'} | "
                         f"{_link('WAV', o, 'wav')} | {_link('MP3', o, 'mp3')} | {_dur(r)} | {_state(r)} |")

    warned = [r for r in rows if row_warnings(r)]
    lines += ["", "## Mechanical warnings (not judgements)", ""]
    if warned:
        for r in warned:
            lines.append(f"- **{r['row_id']}**: " + "; ".join(row_warnings(r)[:6]))
    else:
        lines.append("None recorded.")
    lines += ["", "## Listening rubric (score 1-5; note timestamps)", "", "| Criterion | Notes / score |", "|---|---|"]
    lines += [f"| {c} | |" for c in RUBRIC]
    lines += ["| Timestamped omissions / repetitions | |", ""]
    return "\n".join(lines)


def render_manifest_digest(rows: list[dict], run_id: str) -> str:
    lines = [f"# Manifest digest - run `{run_id}`", "",
             "| Row | Engine | Suite | Status | Audible | Gen/Wall (s) | RTF | Peak VRAM (MiB) | Warnings |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r.get("timing") or {}
        lines.append(f"| {r['row_id']} | {r['engine']} | {r['suite']} | {r['status']} | {t.get('audible_s', '-')} | "
                     f"{t.get('gen_s', t.get('wall_s', '-'))} | {t.get('rtf', '-')} | {t.get('peak_alloc_mib', '-')} | "
                     f"{len(row_warnings(r))} |")
    return "\n".join(lines) + "\n"


def transcript_states(run: Run) -> dict[str, str]:
    path = transcripts_dir(run) / "verified.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    states = {}
    for display, _ in core.REFERENCE_VOICE_IDS:
        entry = data.get(display)
        states[display] = ("approved" if isinstance(entry, dict) and entry.get("approved") is True
                           else "draft awaiting your verification" if entry else "not drafted")
    return states


def stage_report(run: Run) -> None:
    frozen_path = run.dir / "corpus" / "frozen.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8")) if frozen_path.is_file() else None
    rows = list(run.manifest.rows.values())
    core.atomic_write_text(run.dir / "README-listen-first.md",
                           render_listening_index(rows, run.id, frozen, transcript_states(run)))
    core.atomic_write_text(run.dir / "manifest.md", render_manifest_digest(rows, run.id))
    say(f"report written: {run.dir / 'README-listen-first.md'}")


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
def selected_groups(selector: str) -> list[str]:
    table = {"all": [core.GROUP_KOKORO, core.GROUP_CHATTERBOX, core.GROUP_QWEN_PRESET, core.GROUP_QWEN_CLONE],
             "qwen": [core.GROUP_QWEN_PRESET, core.GROUP_QWEN_CLONE], "qwen-preset": [core.GROUP_QWEN_PRESET],
             "qwen-clone": [core.GROUP_QWEN_CLONE], "chatterbox": [core.GROUP_CHATTERBOX], "kokoro": [core.GROUP_KOKORO]}
    return table[selector]


def run_groups(run: Run, rows: list[dict], groups: list[str], *, suite_text: str, profile: dict, label: str) -> list[str]:
    snapshot_before = reference_snapshot()
    for group in groups:
        subset = [run.manifest.get(r["row_id"]) for r in rows if r["group"] == group]
        if not subset:
            continue
        stamp = f"{label}-{group}"
        if group == core.GROUP_QWEN_PRESET:
            run_qwen_group(run, subset, mode="custom_voice", suite_text=suite_text, profile=profile,
                           manifest=run.manifest, snapshot=snapshot_before, label=stamp)
        elif group == core.GROUP_QWEN_CLONE:
            run_qwen_group(run, subset, mode="clone", suite_text=suite_text, profile=profile,
                           manifest=run.manifest, snapshot=snapshot_before, label=stamp)
        else:
            run_root_group(run, subset, engine=group, suite_text=suite_text, profile=profile,
                           manifest=run.manifest, snapshot=snapshot_before, label=stamp)
    problems = compare_references(snapshot_before, reference_snapshot())
    core.atomic_write_text(run.dir / "references" / "integrity.json", json.dumps(
        {"checked": core.now_iso(), "before": snapshot_before, "problems": problems}, indent=2))
    return problems


def stage_short(run: Run, selector: str) -> int:
    profile = load_profile(run)
    freeze_corpus(run, profile)
    run.manifest.declare(core.short_rows())
    problems = run_groups(run, core.short_rows(), selected_groups(selector), suite_text="short", profile=profile,
                          label="short")
    stage_report(run)
    for p in problems:
        say(f"REFERENCE INTEGRITY: {p}")
    return 1 if problems else 0


def stage_long(run: Run) -> int:
    path = run.dir / "long-selection.json"
    if not path.is_file():
        say("long-selection.json is missing: the owner's two Qwen selections are required before any long recording")
        return 2
    sel = json.loads(path.read_text(encoding="utf-8"))
    female, clone = sel.get("female_preset"), sel.get("clone")
    if not core.is_female_preset(female or "") or clone not in dict(core.REFERENCE_VOICE_IDS):
        say(f"invalid long-selection.json (female_preset={female!r}, clone={clone!r}): the female preset must be one of "
            f"{[n for n, _ in core.QWEN_PRESETS if core.is_female_preset(n)]} and the clone one of the six references")
        return 2
    approved, why = approved_transcript(run, clone)
    if approved is None:
        say(f"the selected clone {clone!r} has no owner-approved transcript ({why}); a long clone cannot be made")
        return 2
    profile = load_profile(run)
    freeze_corpus(run, profile)
    rows = [core.long_row(core.GROUP_QWEN_PRESET, n) for n in ("Aiden", "Dylan", female)] + \
           [core.long_row(core.GROUP_QWEN_CLONE, clone)]
    run.manifest.declare(rows)
    problems = run_groups(run, rows, [core.GROUP_QWEN_PRESET, core.GROUP_QWEN_CLONE], suite_text="long",
                          profile=profile, label="long")
    stage_report(run)
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# transcribe, preflight, prepare, pilot
# --------------------------------------------------------------------------- #
def english_ratio(text: str) -> float:
    words = [w.strip(".,!?;:\"'()").lower() for w in text.split()]
    common = {"the", "a", "an", "and", "of", "to", "in", "is", "it", "that", "was", "for", "on", "with", "as", "his",
              "her", "he", "she", "they", "you", "i", "at", "be", "this", "had", "by", "not", "but", "are", "from"}
    return round(sum(1 for w in words if w in common) / max(1, len(words)), 3)


def stage_transcribe(run: Run) -> int:
    key = "whisper-small-en"
    record = assets.load_record().get(key)
    problems = assets.snapshot_problems(key, record["files"]) if record else ["not acquired (run prepare)"]
    if problems:
        say("Whisper snapshot is not ready: " + "; ".join(problems[:3]))
        return 2
    snapshot = reference_snapshot()
    bad = [n for n, i in snapshot.items() if not i["ok"]]
    if bad:
        say(f"reference integrity failure, not transcribing: {bad}")
        return 2
    drafts = {}

    def handler(ev: dict) -> None:
        if ev["event"] == "draft":
            ref = snapshot[ev["name"]]
            drafts[ev["name"]] = {"text": ev["text"], "duration_s": ev["duration_s"], "source_rate": ev["source_rate"],
                                  "wav": ref["path"], "wav_sha256": ref["sha256"], "english_word_ratio": english_ratio(ev["text"]),
                                  "wall_s": ev["wall_s"]}
            say(f"draft {ev['name']}: {len(ev['text'].split())} words")
        elif ev["event"] == "draft_failed":
            say(f"draft FAILED for {ev['name']}: {ev['error']}")

    job = {"kind": "transcribe", "model_dir": str(assets.snapshot_dir(key)),
           "references": [{"name": n, "wav": str(core.REPO_ROOT / i["path"])} for n, i in snapshot.items()]}
    code = run_worker(run, core.eval_python(run.work), WORKER, job, "transcribe",
                      core.child_env("qwen", work_dir=run.work, offline=True), handler)
    after = reference_snapshot()
    ref_problems = compare_references(snapshot, after)
    out = transcripts_dir(run)
    core.atomic_write_text(out / "drafts.json", json.dumps(
        {"model": model_identity(key), "language_assumed": "English", "drafts": drafts}, indent=2, ensure_ascii=False))
    verified = out / "verified.json"
    existing = json.loads(verified.read_text(encoding="utf-8")) if verified.is_file() else {}
    for name, d in drafts.items():
        existing.setdefault(name, {"text": d["text"], "approved": False, "approved_by": None, "note": ""})
    existing["_instructions"] = (
        "Listen to each reference WAV, correct the draft text so it matches EXACTLY what is spoken (names, missing "
        "or extra words, clipped endings), then set approved to true. Only approved transcripts condition a clone.")
    core.atomic_write_text(verified, json.dumps(existing, indent=2, ensure_ascii=False))
    sheet = ["# Reference transcript review", "",
             "Whisper drafts for the six bundled 15-second references. **Drafts are not approved.** Language was assumed "
             "English; the English-word ratio below is a rough sanity signal only.", "",
             "To approve: edit `verified.json` in this folder (correct `text`, set `\"approved\": true`), or tell Claude "
             "the exact corrections and your approval in the session.", "",
             "| Reference | Listen (original WAV) | Seconds | English-word ratio | Draft |", "|---|---|---|---|---|"]
    for name, d in drafts.items():
        link = os.path.relpath(core.REPO_ROOT / d["wav"], out).replace("\\", "/")
        sheet.append(f"| {name} | [{name}.wav]({link}) | {d['duration_s']} | {d['english_word_ratio']} | "
                     f"{d['text'].replace('|', '/')} |")
    sheet += ["", "SHA-256 of each source WAV is recorded in `drafts.json`."]
    core.atomic_write_text(out / "review-sheet.md", "\n".join(sheet) + "\n")
    for p in ref_problems:
        say(f"REFERENCE INTEGRITY: {p}")
    say(f"transcript drafts: {len(drafts)}/6; review sheet: {out / 'review-sheet.md'}")
    return 0 if code == 0 and len(drafts) == 6 and not ref_problems else 1


def stage_asr_check(run: Run) -> int:
    """Advisory read-back: what a speech recogniser heard versus the canonical text, per recording."""
    key = "whisper-small-en"
    record = assets.load_record().get(key)
    problems = assets.snapshot_problems(key, record["files"], verify_hash=False) if record else ["not acquired"]
    if problems:
        say("Whisper snapshot is not ready: " + "; ".join(problems[:3]))
        return 2
    rows = [r for r in run.manifest.rows.values() if r["status"] == "succeeded" and r.get("outputs", {}).get("wav")
            and not (r.get("asr_check") and r["asr_check"].get("wav_sha256") == r["outputs"]["wav"]["sha256"]
                     and r["asr_check"].get("method") == core.ASR_METHOD)]
    if not rows:
        say("asr-check: nothing new to read back")
        return 0
    out = run.dir / "asr"
    out.mkdir(exist_ok=True)

    def handler(ev: dict) -> None:
        if ev["event"] == "asr_failed":
            say(f"asr-check FAILED for {ev['row_id']}: {ev['error']}")
            return
        if ev["event"] != "asr_row":
            return
        row = run.manifest.get(ev["row_id"])
        passage = corpus.PASSAGES[row["text"]["name"]]
        result = core.asr_compare(passage.text, ev["text"])
        (out / f"{ev['row_id']}.txt").write_text(ev["text"], encoding="utf-8")
        result.update(wav_sha256=row["outputs"]["wav"]["sha256"], model=model_identity(key), advisory=True,
                      method=core.ASR_METHOD, segments=ev.get("segments"))
        warnings = [w for w in row.get("warnings", []) if not w.startswith("asr read-back")]
        if result["flagged"]:
            warnings.append(f"asr read-back flagged: coverage {result['coverage']:.2f}, head_ok={result['head_ok']}, "
                            f"tail_ok={result['tail_ok']} (advisory; listen to confirm)")
        run.manifest.update(ev["row_id"], asr_check=result, warnings=warnings)
        say(f"asr-check {ev['row_id']}: coverage {result['coverage']:.2f}{' FLAGGED' if result['flagged'] else ''}")

    job = {"kind": "asr-check", "model_dir": str(assets.snapshot_dir(key)),
           "rows": [{"row_id": r["row_id"], "wav": str(run.dir / r["outputs"]["wav"]["path"])} for r in rows]}
    run_worker(run, core.eval_python(run.work), WORKER, job, "asr-check",
               core.child_env("qwen", work_dir=run.work, offline=True), handler)
    stage_report(run)
    return 0


def stage_preflight(run: Run) -> int:
    facts: dict = {"checked": core.now_iso(), "git": {"head": git_head()}}
    for name, cmd in (("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
                      ("status", ["git", "status", "--porcelain"])):
        out = subprocess.run(cmd, cwd=str(core.REPO_ROOT), capture_output=True, text=True)
        facts["git"][name] = out.stdout.strip().splitlines() if name == "status" else out.stdout.strip()
    facts["python"] = sys.version.split()[0]
    facts["disk_free_gb"] = round(shutil.disk_usage(run.work).free / 1e9, 1)
    facts["eval_python_present"] = core.eval_python(run.work).is_file()
    facts["references"] = {n: {k: i.get(k) for k in ("ok", "sha256", "samplerate", "channels", "duration_s")}
                           for n, i in reference_snapshot().items()}
    rec = assets.load_record()
    facts["models"] = {k: ("acquired" if k in rec and not assets.snapshot_problems(k, rec[k]["files"], verify_hash=False)
                           else "missing") for k in assets.ASSETS}
    facts["kokoro_voices"] = kokoro_inventory()
    facts["transcripts"] = transcript_states(run)
    out = run.dir / "preflight" / f"preflight-{time.strftime('%Y%m%d-%H%M%S')}.json"
    core.atomic_write_text(out, json.dumps(facts, indent=2))
    say(f"preflight evidence: {out}")
    return 0


def kokoro_inventory() -> dict:
    from tts.voice_registry import VOICES

    registered = {v.voice_id for v in VOICES if v.backend == "kokoro"}
    root = core.REPO_ROOT / "files" / "runtime-data" / "models" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M" / "snapshots"
    inv = {}
    for voice_id, act_status, lang in core.KOKORO_VOICES:
        cached = any((s / "voices" / f"{voice_id}.pt").is_file() for s in root.glob("*")) if root.is_dir() else False
        inv[voice_id] = {"registered": voice_id in registered, "expected_act_status": act_status,
                         "lang_code": lang, "cached": cached}
    return inv


def base_python() -> Path:
    cfg = core.REPO_ROOT / ".venv" / "pyvenv.cfg"
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("home"):
            return Path(line.split("=", 1)[1].strip()) / ("python.exe" if os.name == "nt" else "python3")
    raise FileNotFoundError("cannot determine the base interpreter from the root pyvenv.cfg")


def stage_prepare(run: Run, dry_run: bool = False) -> int:
    py = core.eval_python(run.work)
    env = core.child_env("qwen", work_dir=run.work)
    env.update(PIP_CACHE_DIR=str(run.work / "cache" / "pip"), PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    steps = []
    if not py.is_file():
        steps.append(("create the isolated venv", [str(base_python()), "-m", "venv", str(run.work / ".venv")]))
    pins = parse_constraints()
    installed = installed_packages(py) if py.is_file() else {}
    if installed != pins:
        steps.append(("install the pinned evaluation wheels", [
            str(py), "-m", "pip", "install", "--index-url", CU128_INDEX, "--extra-index-url", PYPI_INDEX,
            "-c", str(CONSTRAINTS), "--report", str(run.work / "environment" / "install-report.json"), *PINNED_REQUIREMENTS]))
    record = assets.load_record()
    for key in assets.ASSETS:
        if key not in record or assets.snapshot_problems(key, record[key]["files"], verify_hash=False):
            steps.append((f"acquire pinned model {key}", [str(py), str(HERE / "qwen_eval_assets.py"), key]))
    missing = [v for v, info in kokoro_inventory().items() if not info["cached"]]
    if missing:
        steps.append((f"fetch {len(missing)} official Kokoro voice file(s): {', '.join(missing)}", "kokoro-assets"))
    if not steps:
        say("prepare: everything is already in place")
        return 0
    for title, cmd in steps:
        say(("DRY RUN: would " if dry_run else "") + title)
        if dry_run:
            continue
        if cmd == "kokoro-assets":
            code = fetch_kokoro_assets(run, missing)
        else:
            code = subprocess.run(cmd, cwd=str(core.REPO_ROOT), env=env).returncode
        if code != 0:
            say(f"prepare step failed ({code}): {title}")
            return code
    return 0


def parse_constraints() -> dict[str, str]:
    pins = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.strip().split("==", 1)
            pins[name.lower().replace("_", "-")] = version
    return pins


def installed_packages(py: Path) -> dict[str, str]:
    out = subprocess.run([str(py), "-m", "pip", "freeze"], capture_output=True, text=True, cwd=str(core.REPO_ROOT))
    result = {}
    for line in out.stdout.splitlines():
        if "==" in line:
            name, version = line.strip().split("==", 1)
            result[name.lower().replace("_", "-")] = version
    return result


def fetch_kokoro_assets(run: Run, voice_ids: list[str]) -> int:
    job = {"engine": "kokoro-assets", "voices": voice_ids, "repo": KOKORO_REPO}
    seen: list[dict] = []
    env = core.child_env("root", work_dir=run.work)
    hf_home = core.REPO_ROOT / "files" / "runtime-data" / "models" / "huggingface"
    env["HF_HOME"], env["HUGGINGFACE_HUB_CACHE"] = str(hf_home), str(hf_home / "hub")
    code = run_worker(run, core.root_python(), BASELINE_WORKER, job, "kokoro-assets", env,
                      lambda ev: seen.append(ev) if ev["event"] in ("asset", "asset_failed") else None)
    core.atomic_write_text(run.work / "environment" / "kokoro-assets.json", json.dumps(seen, indent=2))
    return 0 if code == 0 and all(e["event"] == "asset" for e in seen) and len(seen) == len(voice_ids) else 1


def run(stage: str, run_id: str = core.DEFAULT_RUN_ID, group: str = "all", dry_run: bool = False) -> int:
    """Entry point used by ``generate_voice_samples.py --qwen-eval``."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    session = Run(run_id)
    if stage == "preflight":
        return stage_preflight(session)
    if stage == "prepare":
        return stage_prepare(session, dry_run)
    if stage == "transcribe":
        return stage_transcribe(session)
    if stage == "short":
        return stage_short(session, group)
    if stage == "long":
        return stage_long(session)
    if stage == "asr-check":
        return stage_asr_check(session)
    if stage == "report":
        stage_report(session)
        return 0
    from qwen_eval_pilot import stage_pilot  # imported lazily: the pilot is calibration only

    return stage_pilot(session, group)
