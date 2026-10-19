"""Permanent 10-second voice previews for the 28-voice roster (v0.6.7). Dev-only: never shipped, never imported by the app.

Owner ruling Q8 (``md-instructions/Decisions.md``, 2026-10-19): the previews stay in scope, but a preview is generated
or published **only** for a voice whose output rights and underlying source permissions are confirmed. A per-voice
rights/status manifest (``files/voice-previews/previews.json``) is the single record; this tool refuses to generate for
a voice whose rights are not ``confirmed``, validates every preview it finds, regenerates the folder's README from the
manifest, and states plainly -- never silently -- how many of the 28 are still blocked.

    python files/dev-tools/voice_previews.py status              # counts and the blocked list
    python files/dev-tools/voice_previews.py check               # validate manifest + files + README (exit 1 on a problem)
    python files/dev-tools/voice_previews.py sync                # add registry voices missing from the manifest as blocked
    python files/dev-tools/voice_previews.py generate [VOICE_ID ...]   # make previews for confirmed voices that lack one
    python files/dev-tools/voice_previews.py readme              # rewrite the folder README from the manifest

Previews are made through the PRODUCTION engine entry points (Kokoro and Qwen3 file-to-MP3), with the pauses set to
zero and the encode replaced by a lossless 16-bit WAV, so a preview is what the app would say, not a different path.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "Universal"
PREVIEW_DIR = ROOT / "files" / "voice-previews"
MANIFEST = PREVIEW_DIR / "previews.json"
README = PREVIEW_DIR / "README.md"

SAMPLE_TEXT = ("Welcome. This is a short sample of my voice, reading a calm passage at an even pace, "
               "so that you can decide whether it suits the story you want to hear, today or tomorrow.")
SAMPLE_RATE = 24000
MIN_SECONDS, MAX_SECONDS = 8.0, 13.0  # "about 10 seconds": one sentence read by every voice, so natural pace sets the length
EDGE_SILENCE_MS = 120  # leading/trailing silence is trimmed to this
SILENCE_DB = -50.0
PEAK_LIMIT = 0.999
MIN_RMS_DB = -45.0

RIGHTS_CONFIRMED, RIGHTS_UNRESOLVED = "confirmed", "unresolved"
PREVIEW_GENERATED, PREVIEW_BLOCKED, PREVIEW_PENDING = "generated", "blocked", "pending"

KOKORO_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_BASIS = (
    "Local Kokoro-82M engine. The pinned model card declares license: apache-2.0 for the weights and says the model was "
    "trained on permissive / non-copyrighted audio (audio licensed Apache or MIT, synthetic audio from closed TTS models "
    "of large providers, and CC BY audio it credits); that provenance is the model author's claim, not something this "
    "project has audited. ACT supplies no reference recording to a preset voice, and the Apache-2.0 license places no "
    "restriction on the audio the weights produce.")
KOKORO_EVIDENCE = [{
    "what": "Kokoro-82M model card at the pinned revision (front matter: license: apache-2.0; Training Details)",
    "url": f"https://huggingface.co/hexgrad/Kokoro-82M/resolve/{KOKORO_REVISION}/README.md",
    "sha256": "91dcabced89db6f109b8786642f50402d3ee87450e8189589b6f85520e7f4d78"}]
QWEN3_PRESET_BASIS = (
    "Local Qwen3-TTS CustomVoice preset speaker, one of the model's own built-in speakers. The pinned model card "
    "declares license: apache-2.0; it does not document the provenance of the training audio, which this project has "
    "not audited. ACT supplies no reference recording to a preset voice, and the Apache-2.0 license places no "
    "restriction on the audio the weights produce.")
QWEN3_PRESET_EVIDENCE = [{
    "what": "Qwen3-TTS-12Hz-1.7B-CustomVoice model card at the pinned revision (front matter: license: apache-2.0)",
    "url": "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/resolve/"
           "0c0e3051f131929182e2c023b9537f8b1c68adfe/README.md",
    "sha256": "64f65e809b51cc0c35f393fbbfcc2d735c0cb3fdbbc6f3fdc4a5e6ce55e9d088"}]
EDGE_BASIS = ("Microsoft's online Edge TTS service, reached over the network. Its terms govern redistribution of the "
              "audio and have not been reviewed or confirmed. Blocked until the owner decides.")
CLONE_BASIS = ("A synthetic voice derived from a bundled reference recording of another person. The rights to that "
               "original recording (and so to audio cloned from it) have not been audited or confirmed. "
               "Blocked until the owner confirms redistribution rights.")


class PreviewError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def registry_voices() -> list:
    sys.path.insert(0, str(SCRIPTS))
    from tts import voice_registry

    return list(voice_registry.VOICES)


def rights_for(entry) -> dict:
    """The rights record a registry voice starts with. Only a voice whose basis is documented is ever ``confirmed``."""
    if entry.backend == "kokoro":
        return {"status": RIGHTS_CONFIRMED, "basis": KOKORO_BASIS, "evidence": KOKORO_EVIDENCE,
                "confirmed_on": "2026-10-19", "confirmed_by": "license review (Claude Code); the owner may withdraw it"}
    if entry.backend == "qwen3" and entry.voice_id in ("qwen3-aiden", "qwen3-ryan"):
        return {"status": RIGHTS_CONFIRMED, "basis": QWEN3_PRESET_BASIS, "evidence": QWEN3_PRESET_EVIDENCE,
                "confirmed_on": "2026-10-19", "confirmed_by": "license review (Claude Code); the owner may withdraw it"}
    if entry.backend == "edge":
        return {"status": RIGHTS_UNRESOLVED, "basis": EDGE_BASIS, "evidence": []}
    return {"status": RIGHTS_UNRESOLVED, "basis": CLONE_BASIS, "evidence": []}


def new_entry(entry) -> dict:
    rights = rights_for(entry)
    return {"voice_id": entry.voice_id, "label": entry.display_label, "backend": entry.backend, "rights": rights,
            "preview": {"status": PREVIEW_PENDING if rights["status"] == RIGHTS_CONFIRMED else PREVIEW_BLOCKED,
                        "file": None}}


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        return {"schema": 1, "sample_text": SAMPLE_TEXT, "voices": []}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` in one step, so a failed write can never leave a truncated record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)  # a failed write leaves the old file in place and no stray temporary
        raise


def save_manifest(data: dict) -> None:
    clean = {k: v for k, v in data.items() if not k.startswith("_")}  # run-time notes such as _failures are not data
    write_atomic(MANIFEST, json.dumps(clean, indent=2, ensure_ascii=False) + "\n")


def write_readme(data: dict) -> None:
    write_atomic(README, render_readme(data))


def sync(data: dict) -> dict:
    """Make the manifest list exactly the registry's voices, in registry order, keeping what is already recorded.

    A voice whose rights are already ``confirmed`` here and in the tool gets the tool's current basis and evidence text;
    a voice the owner has withdrawn (``unresolved`` in the manifest) is never re-confirmed by a sync.
    """
    by_id = {v["voice_id"]: v for v in data.get("voices", [])}
    voices = []
    for entry in registry_voices():
        record = by_id.get(entry.voice_id) or new_entry(entry)
        record["label"], record["backend"] = entry.display_label, entry.backend
        fresh = rights_for(entry)
        if record["rights"]["status"] == RIGHTS_CONFIRMED and fresh["status"] == RIGHTS_CONFIRMED:
            record["rights"]["basis"], record["rights"]["evidence"] = fresh["basis"], fresh["evidence"]
        voices.append(record)
    data["voices"], data["sample_text"], data["schema"] = voices, SAMPLE_TEXT, 1
    return data


# --------------------------------------------------------------------------- #
# Audio checks and trimming
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def trim_edges(audio: np.ndarray, rate: int, keep_ms: int = EDGE_SILENCE_MS, threshold_db: float = SILENCE_DB) -> np.ndarray:
    """Trim leading/trailing silence down to ``keep_ms`` each side. Never touches the speech itself."""
    amplitude = np.abs(audio)
    limit = 10 ** (threshold_db / 20)
    loud = np.flatnonzero(amplitude > limit)
    if loud.size == 0:
        return audio
    keep = int(rate * keep_ms / 1000)
    start, end = max(0, loud[0] - keep), min(audio.size, loud[-1] + 1 + keep)
    return audio[start:end]


def audio_problems(path: Path) -> list[str]:
    """Everything wrong with one preview file, as sentences. ``[]`` means it is a valid preview."""
    try:
        info = sf.info(str(path))
        data, rate = sf.read(str(path), dtype="float32")
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable audio ({exc})"]
    problems = []
    if info.format != "WAV" or info.subtype != "PCM_16":
        problems.append(f"must be a 16-bit PCM WAV (found {info.format}/{info.subtype})")
    if rate != SAMPLE_RATE:
        problems.append(f"sample rate {rate} is not {SAMPLE_RATE}")
    if data.ndim != 1:
        problems.append("must be mono")
        return problems
    seconds = data.size / rate
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        problems.append(f"duration {seconds:.1f} s is outside {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} s")
    if not np.isfinite(data).all():
        problems.append("contains non-finite samples")
    elif float(np.max(np.abs(data))) > PEAK_LIMIT:
        problems.append("clips (peak at full scale)")
    rms_db = 20 * np.log10(max(float(np.sqrt(np.mean(np.square(data)))), 1e-9))
    if rms_db < MIN_RMS_DB:
        problems.append(f"is nearly silent (RMS {rms_db:.0f} dBFS)")
    return problems


# --------------------------------------------------------------------------- #
# Validation of the whole folder
# --------------------------------------------------------------------------- #
def manifest_problems(data: dict) -> list[str]:
    """Every way the manifest contradicts itself or the owner's rights rule, judged from the manifest alone."""
    problems: list[str] = []
    ids = [v["voice_id"] for v in data.get("voices", [])]
    if len(set(ids)) != len(ids):
        problems.append("a voice id appears twice")
    for record in data.get("voices", []):
        vid, rights, preview = record["voice_id"], record["rights"], record["preview"]
        if rights["status"] not in (RIGHTS_CONFIRMED, RIGHTS_UNRESOLVED):
            problems.append(f"{vid}: unknown rights status {rights['status']!r}")
        if preview["status"] not in (PREVIEW_GENERATED, PREVIEW_PENDING, PREVIEW_BLOCKED):
            problems.append(f"{vid}: unknown preview status {preview['status']!r}")
        if not rights.get("basis"):
            problems.append(f"{vid}: no recorded basis for its rights status")
        if rights["status"] == RIGHTS_CONFIRMED and not rights.get("evidence"):
            problems.append(f"{vid}: rights are marked confirmed with no evidence")
        if rights["status"] == RIGHTS_UNRESOLVED and preview["status"] != PREVIEW_BLOCKED:
            problems.append(f"{vid}: rights are unresolved but the preview is {preview['status']!r}, not blocked")
        if preview["status"] == PREVIEW_BLOCKED and preview.get("file"):
            problems.append(f"{vid}: a blocked voice must have no preview file")
        if preview["status"] == PREVIEW_GENERATED:
            if rights["status"] != RIGHTS_CONFIRMED:
                problems.append(f"{vid}: a preview exists for a voice whose rights are not confirmed")
            if not preview.get("file") or not preview.get("sha256"):
                problems.append(f"{vid}: a generated preview must name its file and SHA-256")
    return problems


def check(data: dict | None = None, preview_dir: Path = PREVIEW_DIR) -> list[str]:
    """Every problem with the manifest, the files and the README. ``[]`` means the folder is consistent."""
    data = load_manifest() if data is None else data
    registry = registry_voices()
    ids = [v["voice_id"] for v in data.get("voices", [])]
    problems = manifest_problems(data)
    if ids != [e.voice_id for e in registry]:
        problems.append("the manifest does not list exactly the registry's voices in registry order (run sync)")
    if data.get("sample_text") != SAMPLE_TEXT:
        problems.append("the manifest's sample text differs from the tool's")
    wanted_files = set()
    for record in data.get("voices", []):
        vid, preview = record["voice_id"], record["preview"]
        if preview["status"] == PREVIEW_BLOCKED and (preview_dir / f"{vid}.wav").exists():
            problems.append(f"{vid}: a blocked voice must have no preview file")
        if preview["status"] == PREVIEW_GENERATED:
            path = preview_dir / (preview.get("file") or "")
            wanted_files.add(path.name)
            if not preview.get("file") or not path.is_file():
                problems.append(f"{vid}: the preview file is missing")
                continue
            if sha256_file(path) != preview.get("sha256"):
                problems.append(f"{vid}: the preview file does not match its recorded SHA-256")
            problems.extend(f"{vid}: {p}" for p in audio_problems(path))
    stray = sorted(p.name for p in preview_dir.glob("*") if p.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg")
                   and p.name not in wanted_files)
    if stray:
        problems.append(f"files in the folder that the manifest does not list: {', '.join(stray)}")
    if not manifest_problems(data) and README.is_file() and preview_dir == PREVIEW_DIR \
            and README.read_text(encoding="utf-8") != render_readme(data):
        problems.append("README.md is out of date with the manifest (run readme)")
    return problems


def is_available(record: dict) -> bool:
    """A preview counts as available only when its rights are confirmed AND a generated file is recorded for it."""
    return (record["rights"]["status"] == RIGHTS_CONFIRMED and record["preview"]["status"] == PREVIEW_GENERATED
            and bool(record["preview"].get("file")))


def counts(data: dict) -> dict:
    """Available / pending / blocked, derived from rights and preview together so a status can never over-claim."""
    voices = data["voices"]
    generated = sum(is_available(v) for v in voices)
    pending = sum(v["rights"]["status"] == RIGHTS_CONFIRMED and v["preview"]["status"] == PREVIEW_PENDING for v in voices)
    return {"total": len(voices), "generated": generated, "pending": pending, "blocked": len(voices) - generated - pending}


def render_readme(data: dict) -> str:
    problems = manifest_problems(data)
    if problems:  # never publish, or claim completeness for, a manifest that contradicts the rights rule
        raise PreviewError("the manifest is inconsistent, so no README is written: " + "; ".join(problems[:3]))
    c = counts(data)
    complete = c["generated"] == c["total"]
    lines = [
        "# Voice previews", "",
        "Short (about 10 second) samples of the voices in the Audiobook Creation Tool, all reading the same sentence so "
        "they can be compared.", "",
        f"> **{c['generated']} of {c['total']} previews are available.** "
        + ("" if complete else f"The other {c['total'] - c['generated']} are **blocked**, not forgotten: a preview is "
           "only made for a voice whose output rights and source permissions are confirmed (see the table). "
           "This folder is not a complete set until every row is available."), "",
        f"The sentence: *{data['sample_text']}*", "",
        "| Voice | Engine | Preview | Rights |", "|---|---|---|---|"]
    for v in data["voices"]:
        preview = v["preview"]
        link = f"[{preview['file']}]({preview['file']})" if is_available(v) else \
            ("pending" if preview["status"] == PREVIEW_PENDING else "blocked")
        rights = "confirmed" if v["rights"]["status"] == RIGHTS_CONFIRMED else "unresolved"
        lines.append(f"| {v['label']} | {v['backend']} | {link} | {rights} |")
    lines += [
        "", "## Why some previews are blocked", "",
        "- **Edge voices** come from Microsoft's online service; its terms govern redistributing the audio and have not "
        "been confirmed.",
        "- **Chatterbox and Qwen3 cloned voices** are synthetic voices made from bundled reference recordings of other "
        "people. Redistribution rights to those recordings, and so to audio cloned from them, have not been audited.",
        "- **Kokoro and Qwen3 preset voices** are generated by local models whose license is Apache-2.0 (evidence recorded "
        "per voice in `previews.json`).", "",
        "## How they are made", "",
        "Each preview is produced by the app's own engine for that voice (not a separate path), with leading and trailing "
        f"silence trimmed to {EDGE_SILENCE_MS} ms, saved as 24 kHz mono 16-bit WAV, and checked for length "
        f"({MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} s), clipping and silence. `previews.json` records every voice's rights "
        "status and basis, and each preview's SHA-256 and duration. Regenerate or validate with "
        "`python files/dev-tools/voice_previews.py generate | check | status`.", "",
        "These files live in the repository only. They are not part of the release archives, and no preview is rendered "
        "for the voices the maintainer excluded from the app.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Generation through the production engines
# --------------------------------------------------------------------------- #
def synthesize(entry, text_path: Path, out_wav: Path) -> None:
    """Run the app's own entry point for this voice, capturing PCM instead of encoding an MP3."""
    sys.path.insert(0, str(SCRIPTS))
    if entry.backend == "kokoro":
        from tts import kokoro_synth

        original = kokoro_synth._export_mp3
        kokoro_synth._export_mp3 = lambda arr, rate, output, bitrate=None: sf.write(
            output, np.asarray(arr, dtype="float32"), rate, subtype="PCM_16")
        try:
            kokoro_synth.kokoro_file_to_mp3(str(text_path), str(out_wav), voice_id=entry.voice_id,
                                            end_silence_ms=0, chunk_pause_ms=0)
        finally:
            kokoro_synth._export_mp3 = original
    elif entry.backend == "qwen3":
        import shutil

        from tts import qwen3_synth

        def wav_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
            shutil.copyfile(wav, mp3)  # keep the lossless WAV; the "mp3" name is only the hand-off path

        qwen3_synth.qwen3_file_to_mp3(str(text_path), str(out_wav), entry.voice_id, end_silence_ms=0,
                                      chunk_pause_ms=0, encoder=wav_encoder)
    else:
        raise PreviewError(f"{entry.voice_id}: no preview path exists for backend {entry.backend!r}")


class RollbackError(PreviewError):
    """A publish failed AND could not be undone; the recovery files are kept in the scratch folder."""


def _back_up(path: Path, backup: Path) -> bool:
    """Copy ``path`` to ``backup`` BEFORE anything is changed (so a full disk stops the publish, not its rollback)."""
    if path.is_file():
        shutil.copyfile(path, backup)
        return True
    return False


def _put_back(path: Path, backup: Path, existed: bool) -> None:
    """Restore by renaming: needs no new disk space, unlike writing the old bytes out again."""
    if existed:
        os.replace(backup, path)
    else:
        path.unlink(missing_ok=True)


def publish(record: dict, meta: dict, candidate: Path, target: Path, data: dict, scratch: Path) -> None:
    """Make one validated take the published preview, all-or-nothing.

    The previous audio, manifest and README are first set aside in ``scratch`` (copies for the two documents, a rename
    for the audio); then the new audio is moved in and the manifest and README rewritten atomically. If any step fails,
    everything is put back by renaming, so the folder never holds new audio under an old hash (or the reverse), even when
    the disk is full. If even that fails, :class:`RollbackError` names the recovery files, which are kept.
    """
    previous = record["preview"]
    audio_backup = scratch / f"{target.stem}.previous.wav"
    manifest_backup, readme_backup = scratch / "previews.json.bak", scratch / "README.md.bak"
    had_audio = target.exists()
    had_manifest = _back_up(MANIFEST, manifest_backup)  # a failure here changes nothing
    had_readme = _back_up(README, readme_backup)
    moved = False
    try:
        if had_audio:
            os.replace(target, audio_backup)
            moved = True
        os.replace(candidate, target)
        record["preview"] = meta
        save_manifest(data)
        write_readme(data)
    except BaseException as failure:
        record["preview"] = previous
        try:
            if moved or not had_audio:
                _put_back(target, audio_backup, had_audio)
            _put_back(MANIFEST, manifest_backup, had_manifest)
            _put_back(README, readme_backup, had_readme)
        except OSError as problem:
            raise RollbackError(f"{target.name} could not be rolled back after: {failure}. Recovery files are in "
                                f"{scratch}; put back whichever of previews.json.bak, README.md.bak and {audio_backup.name} "
                                "is still there.") from problem
        raise


def generate(voice_ids: list[str] | None = None, log=print) -> dict:
    """Make previews for confirmed voices. A voice that fails is reported and skipped; the others are kept.

    A failed take never touches the previous good preview: the new audio is validated and its metadata computed in the
    scratch folder first, and only then published with :func:`publish`.
    """
    data = sync(load_manifest())
    problems = manifest_problems(data)
    if problems:
        raise PreviewError("the manifest is inconsistent; fix it before generating: " + "; ".join(problems[:3]))
    failures: list[str] = []
    registry = {e.voice_id: e for e in registry_voices()}
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scratch = PREVIEW_DIR / ".scratch"
    recovery = sorted(p.name for pattern in ("*.bak", "*.previous.wav") for p in scratch.glob(pattern))
    if recovery:  # left by a publish that could not be undone: the only copy of what was there, never to be cleaned up silently
        raise PreviewError(f"{scratch} still holds recovery files from a failed publish ({', '.join(recovery)}). Put "
                           "them back by hand (or delete the folder once the previews are as you want them), then run again.")
    scratch.mkdir(exist_ok=True)
    text_path = scratch / "sample.txt"
    text_path.write_text(SAMPLE_TEXT, encoding="utf-8")
    keep_scratch = False
    try:
        for record in data["voices"]:
            vid = record["voice_id"]
            if voice_ids and vid not in voice_ids:
                continue
            if record["rights"]["status"] != RIGHTS_CONFIRMED:
                log(f"BLOCKED  {vid}: rights not confirmed; no preview is made")
                continue
            if is_available(record) and not voice_ids:
                continue
            target = PREVIEW_DIR / f"{vid}.wav"
            candidate = scratch / f"{vid}.candidate.wav"
            try:
                raw = scratch / f"{vid}.wav"
                synthesize(registry[vid], text_path, raw)
                audio, rate = sf.read(str(raw), dtype="float32")
                if audio.ndim != 1:
                    raise PreviewError(f"{vid}: the engine returned a non-mono waveform")
                sf.write(str(candidate), trim_edges(audio, rate), rate, subtype="PCM_16")
                issues = audio_problems(candidate)
                if issues:
                    raise PreviewError(f"{vid}: the generated preview is not valid: {'; '.join(issues)}")
                meta = {"status": PREVIEW_GENERATED, "file": target.name, "sha256": sha256_file(candidate),
                        "duration_s": round(sf.info(str(candidate)).duration, 2), "sample_rate": rate,
                        "generated_on": datetime.date.today().isoformat()}
            except Exception as exc:  # noqa: BLE001 - one voice failing must not lose the others
                failures.append(f"{vid}: {exc}")  # nothing was published, so the previous good preview is untouched
                log(f"FAILED   {vid}: {exc}")
                continue
            publish(record, meta, candidate, target, data, scratch)
            log(f"GENERATED {vid}: {meta['duration_s']} s")
    except RollbackError:
        keep_scratch = True  # the recovery files are the only copy of what was there before
        raise
    finally:
        if not keep_scratch:
            for leftover in scratch.glob("*"):
                leftover.unlink(missing_ok=True)
            scratch.rmdir()
    data["_failures"] = failures
    return data


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # the engines print arrows and quotes that a legacy console cannot encode
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    command = argv[0] if argv else "status"
    try:
        if command == "sync":
            data = sync(load_manifest())
            save_manifest(data)
            write_readme(data)
            print(json.dumps(counts(data)))
            return 0
        if command == "generate":
            data = generate(argv[1:] or None)
            print(json.dumps(counts(data)))
            return 1 if data.get("_failures") else 0
        if command == "readme":
            write_readme(load_manifest())
            return 0
        data = load_manifest()
        if command == "check":
            problems = check(data)
            for problem in problems:
                print("PROBLEM:", problem)
            print("OK" if not problems else f"{len(problems)} problem(s)")
            return 1 if problems else 0
        problems = manifest_problems(data)
        if problems:  # a status that contradicts the rights rule must not read as a count
            for problem in problems:
                print("PROBLEM:", problem)
            return 3
        c = counts(data)
        print(f"{c['generated']} of {c['total']} previews available; {c['blocked']} blocked, {c['pending']} pending.")
        for v in data["voices"]:
            if not is_available(v):
                print(f"  {v['preview']['status']:8} {v['voice_id']:24} {v['rights']['status']}")
        return 0 if c["generated"] == c["total"] else 2
    except PreviewError as exc:
        print("ERROR:", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
