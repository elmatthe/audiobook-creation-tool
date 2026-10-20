"""Permanent 10-second voice previews for the 28-voice roster (v0.6.7). Dev-only: never shipped, never imported by the app.

Publication. Owner ruling Q8 (``md-instructions/Decisions.md``, 2026-10-19) made a preview publishable only for a voice
whose output rights were confirmed. The **owner's decision of 2026-10-20 supersedes that for preview audio**: short
generated previews of all 28 registered voices are authorized (``OWNER_DECISION``). It is a publication decision, not a
third-party legal finding, and it covers generated preview audio only -- never a reference recording or transcript.
A per-voice record (``files/voice-previews/previews.json``) is the single source: a voice is *authorized* (license
evidence or the owner decision), a preview is *generated* (a validated WAV with its SHA-256) or *pending* (authorized, not
yet generated, with the exact reason), and only a voice the owner withdraws is *blocked*. This tool validates every
preview it finds, regenerates the folder's README from the manifest, and states plainly how many of the 28 exist.

    python files/dev-tools/voice_previews.py status              # counts, and why each missing preview is missing
    python files/dev-tools/voice_previews.py check               # validate manifest + files + README (exit 1 on a problem)
    python files/dev-tools/voice_previews.py sync                # list exactly the registry's voices; migrate the old block
    python files/dev-tools/voice_previews.py generate [VOICE_ID ...]   # make previews for authorized voices that lack one
    python files/dev-tools/voice_previews.py readme              # rewrite the folder README from the manifest

Previews are made through the PRODUCTION engine entry points (Kokoro, Chatterbox and Qwen3 file-to-MP3, and the Edge folder
route's own request), with the pauses set to zero and the encode replaced by a lossless 16-bit WAV, so a preview is what
the app would say, not a different path. A voice's engine is never substituted, and a Qwen3 clone is only generated from
its owner-approved, reference-bound transcript.
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
SCRIPTS = ROOT / "scripts"
PREVIEW_DIR = ROOT / "files" / "voice-previews"
MANIFEST = PREVIEW_DIR / "previews.json"
README = PREVIEW_DIR / "README.md"
#: Direct links to the raw WAVs on the feature branch, so each row of the README is one click from the audio. GitHub serves a raw
#: file as a download, so a click saves the WAV and opens it in the default audio player.
RAW_BASE = "https://github.com/elmatthe/audiobook-creation-tool/raw/feature/0.6.7-speech-pipeline-and-layout/files/voice-previews/"

SAMPLE_TEXT = ("Welcome. This is a short sample of my voice, reading a calm passage at an even pace, "
               "so that you can decide whether it suits the story you want to hear, today or tomorrow.")
SAMPLE_RATE = 24000
MIN_SECONDS, MAX_SECONDS = 8.0, 13.0  # "about 10 seconds": one sentence read by every voice, so natural pace sets the length
EDGE_SILENCE_MS = 120  # leading/trailing silence is trimmed to this
SILENCE_DB = -50.0
PEAK_LIMIT = 0.999
MIN_RMS_DB = -45.0

SCHEMA = 2  # 1 = the 2026-10-19 rights gate (17 voices blocked); 2 = the owner's 2026-10-20 publication decision

#: ``confirmed`` = a license a reader can check; ``owner_authorized`` = the owner's publication decision, with no
#: license review behind it; ``unresolved`` = withdrawn (or never decided): nothing is generated or published.
RIGHTS_CONFIRMED, RIGHTS_OWNER, RIGHTS_UNRESOLVED = "confirmed", "owner_authorized", "unresolved"
AUTHORIZED = (RIGHTS_CONFIRMED, RIGHTS_OWNER)
PREVIEW_GENERATED, PREVIEW_BLOCKED, PREVIEW_PENDING = "generated", "blocked", "pending"

OWNER_DECISION_DATE = "2026-10-20"
#: Exactly the voices the owner's decision named (the registered roster minus the 11 already cleared by license review).
#: A voice added to the registry later is NOT in this set, so it starts blocked until someone decides.
OWNER_AUTHORIZED_VOICES = frozenset({
    "en-US-SteffanNeural", "en-US-AndrewNeural", "en-US-AriaNeural", "en-US-AvaNeural", "en-US-JennyNeural",
    "chatterbox-female-1", "chatterbox-female-2", "chatterbox-male-1", "chatterbox-male-2", "chatterbox-male-3",
    "chatterbox-male-4",
    "qwen3-female-1", "qwen3-female-2", "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"})
QWEN3_PRESETS = frozenset({"qwen3-aiden", "qwen3-ryan"})
OWNER_DECISION = {
    "date": OWNER_DECISION_DATE,
    "decided_by": "owner",
    "decision": "Short generated preview audio for all 28 registered ACT voices may be published in files/voice-previews/.",
    "supersedes": "The 2026-10-19 Q5/Q8 restriction on preview audio for the Edge, Chatterbox and Qwen3 clone voices "
                  "(kept as history in md-instructions/Decisions.md).",
    "scope": "Generated preview audio only.",
    "not_covered": ["private reference transcripts", "the reference recordings", "any untracked or private asset",
                    "any voice that is not one of the 28 registered voices"],
    "verification": "An owner publication decision. This project did not independently verify any third-party license "
                    "or service terms for the Edge, Chatterbox or Qwen3 clone voices, and makes no claim about them.",
    "separate_gates": ["A Qwen3 clone preview is only generated from an owner-approved transcript bound to its reference "
                       "recording's SHA-256.",
                       "Qwen3 production-clone qualification (S5) is unchanged by this decision."]}

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
EDGE_BASIS = ("Microsoft's online Edge Read Aloud service, reached over the network. Publishing the short generated "
              "preview is authorized by the owner's decision of 2026-10-20. Microsoft's service terms have not been "
              "independently reviewed by this project, and this record makes no claim about them.")
CLONE_BASIS = ("A synthetic voice derived from a bundled reference recording of another person. Publishing the short "
               "generated preview is authorized by the owner's decision of 2026-10-20. The rights to that recording have "
               "not been independently audited by this project, and this record makes no claim about them. The decision "
               "covers the generated preview only, never the reference recording or its transcript.")
CLONE_PENDING = ("Publication is authorized, but the preview is not generated yet: a Qwen3 clone is only made from its "
                 "owner-approved transcript bound to the reference recording's SHA-256, and none is approved on the "
                 "computer that holds the models (the draft transcript is unapproved). Supply the approved transcript "
                 "(see the folder README), then run generate.")
GENERIC_PENDING = "Publication is authorized; the preview has not been generated yet."


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
    """The publication record a registry voice starts with.

    ``confirmed`` only where a license a reader can check is recorded; ``owner_authorized`` only for a voice the owner's
    2026-10-20 decision names; anything else starts ``unresolved`` (blocked) until someone decides.
    """
    reviewed = {"confirmed_on": "2026-10-19", "confirmed_by": "license review (Claude Code); the owner may withdraw it"}
    if entry.backend == "kokoro":
        return {"status": RIGHTS_CONFIRMED, "basis": KOKORO_BASIS, "evidence": KOKORO_EVIDENCE, **reviewed}
    if entry.backend == "qwen3" and entry.voice_id in QWEN3_PRESETS:
        return {"status": RIGHTS_CONFIRMED, "basis": QWEN3_PRESET_BASIS, "evidence": QWEN3_PRESET_EVIDENCE, **reviewed}
    if entry.voice_id in OWNER_AUTHORIZED_VOICES:
        basis = EDGE_BASIS if entry.backend == "edge" else CLONE_BASIS
        return {"status": RIGHTS_OWNER, "basis": basis, "evidence": [], "authorized_on": OWNER_DECISION_DATE,
                "authorized_by": "owner (md-instructions/Decisions.md, 2026-10-20)"}
    return {"status": RIGHTS_UNRESOLVED, "basis": "No publication decision is recorded for this voice, so no preview is "
            "generated or published until the owner decides.", "evidence": []}


def pending_reason_for(entry) -> str:
    """The standing, machine-independent reason an authorized voice has no preview yet."""
    return CLONE_PENDING if entry.backend == "qwen3" and entry.voice_id not in QWEN3_PRESETS else GENERIC_PENDING


def new_entry(entry) -> dict:
    rights = rights_for(entry)
    preview = ({"status": PREVIEW_PENDING, "file": None, "pending_reason": pending_reason_for(entry)}
               if rights["status"] in AUTHORIZED else {"status": PREVIEW_BLOCKED, "file": None})
    return {"voice_id": entry.voice_id, "label": entry.display_label, "backend": entry.backend, "rights": rights,
            "preview": preview}


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        return {"schema": SCHEMA, "owner_decision": OWNER_DECISION, "sample_text": SAMPLE_TEXT, "voices": []}
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

    A voice already authorized here and in the tool gets the tool's current basis text. A **schema-1** record that is
    ``unresolved`` was blocked by the 2026-10-19 rule, not withdrawn: if the owner's decision now authorizes it, it is
    migrated once to ``owner_authorized`` / ``pending``. From schema 2 on, ``unresolved`` means the owner withdrew it, and a
    sync never re-authorizes it.
    """
    old_schema = int(data.get("schema", 1))
    by_id = {v["voice_id"]: v for v in data.get("voices", [])}
    voices = []
    for entry in registry_voices():
        record = by_id.get(entry.voice_id) or new_entry(entry)
        record["label"], record["backend"] = entry.display_label, entry.backend
        fresh = rights_for(entry)
        if record["rights"]["status"] == RIGHTS_UNRESOLVED and old_schema < SCHEMA and fresh["status"] in AUTHORIZED:
            record["rights"], record["preview"] = fresh, {"status": PREVIEW_PENDING, "file": None,
                                                          "pending_reason": pending_reason_for(entry)}
        elif record["rights"]["status"] in AUTHORIZED and record["rights"]["status"] == fresh["status"]:
            record["rights"] = {**record["rights"], "basis": fresh["basis"], "evidence": fresh["evidence"]}
        if record["preview"]["status"] == PREVIEW_PENDING:
            record["preview"]["pending_reason"] = pending_reason_for(entry)
        voices.append(record)
    data["voices"], data["sample_text"], data["schema"], data["owner_decision"] = voices, SAMPLE_TEXT, SCHEMA, OWNER_DECISION
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
    if data.get("owner_decision") != OWNER_DECISION:  # the README states it, so a damaged one must stop the README
        problems.append("the manifest does not carry the owner's publication decision as the tool states it (run sync)")
    ids = [v["voice_id"] for v in data.get("voices", [])]
    if len(set(ids)) != len(ids):
        problems.append("a voice id appears twice")
    for record in data.get("voices", []):
        vid, rights, preview = record["voice_id"], record["rights"], record["preview"]
        if rights["status"] not in (*AUTHORIZED, RIGHTS_UNRESOLVED):
            problems.append(f"{vid}: unknown rights status {rights['status']!r}")
        if preview["status"] not in (PREVIEW_GENERATED, PREVIEW_PENDING, PREVIEW_BLOCKED):
            problems.append(f"{vid}: unknown preview status {preview['status']!r}")
        if not rights.get("basis"):
            problems.append(f"{vid}: no recorded basis for its rights status")
        if rights["status"] == RIGHTS_CONFIRMED and not rights.get("evidence"):
            problems.append(f"{vid}: rights are marked confirmed with no evidence")
        if rights["status"] == RIGHTS_OWNER:
            if vid not in OWNER_AUTHORIZED_VOICES:
                problems.append(f"{vid}: marked owner-authorized but the owner's decision does not name this voice")
            if rights.get("authorized_on") != OWNER_DECISION_DATE or not rights.get("authorized_by"):
                problems.append(f"{vid}: an owner authorization must record its date and who gave it")
        if rights["status"] == RIGHTS_UNRESOLVED and preview["status"] != PREVIEW_BLOCKED:
            problems.append(f"{vid}: rights are unresolved but the preview is {preview['status']!r}, not blocked")
        if rights["status"] in AUTHORIZED and preview["status"] == PREVIEW_BLOCKED:
            problems.append(f"{vid}: publication is authorized, so the preview is pending or generated, never blocked")
        if preview["status"] == PREVIEW_BLOCKED and preview.get("file"):
            problems.append(f"{vid}: a blocked voice must have no preview file")
        if preview["status"] == PREVIEW_PENDING:
            if preview.get("file") or preview.get("sha256"):
                problems.append(f"{vid}: a pending voice must have no preview file")
            if not preview.get("pending_reason"):
                problems.append(f"{vid}: a pending preview must say exactly why it is not generated yet")
        if preview["status"] == PREVIEW_GENERATED:
            if rights["status"] not in AUTHORIZED:
                problems.append(f"{vid}: a preview exists for a voice whose publication is not authorized")
            if not preview.get("file") or not preview.get("sha256"):
                problems.append(f"{vid}: a generated preview must name its file and SHA-256")
            if is_clone(record) and preview.get("generation_profile") != current_clone_profile():
                problems.append(f"{vid}: this clone preview was not made under the application's current clone generation profile "
                                "(regenerate it)")
            if not is_clone(record) and "generation_profile" in preview:
                problems.append(f"{vid}: only a Qwen3 clone preview records a clone generation profile")
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
    if data.get("schema") != SCHEMA:
        problems.append(f"the manifest is schema {data.get('schema')!r}, not {SCHEMA} (run sync to migrate it)")
    wanted_files = set()
    for record in data.get("voices", []):
        vid, preview = record["voice_id"], record["preview"]
        if preview["status"] in (PREVIEW_BLOCKED, PREVIEW_PENDING) and (preview_dir / f"{vid}.wav").exists():
            problems.append(f"{vid}: a {preview['status']} voice must have no preview file")
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


def is_clone(record: dict) -> bool:
    return record["backend"] == "qwen3" and record["voice_id"] not in QWEN3_PRESETS


def current_clone_profile() -> dict:
    """The generation profile the application gives a Qwen3 clone right now (the audio a clone preview must reflect)."""
    sys.path.insert(0, str(SCRIPTS))
    from tts import qwen3_synth

    return {"revision": qwen3_synth.CLONE_GENERATION_REVISION, **qwen3_synth.CLONE_GENERATION}


def is_available(record: dict) -> bool:
    """A preview counts as available only when publication is authorized AND a generated file is recorded for it."""
    return (record["rights"]["status"] in AUTHORIZED and record["preview"]["status"] == PREVIEW_GENERATED
            and bool(record["preview"].get("file")))


def counts(data: dict) -> dict:
    """Available / pending / blocked, derived from rights and preview together so a status can never over-claim."""
    voices = data["voices"]
    generated = sum(is_available(v) for v in voices)
    pending = sum(v["rights"]["status"] in AUTHORIZED and v["preview"]["status"] == PREVIEW_PENDING for v in voices)
    return {"total": len(voices), "generated": generated, "pending": pending, "blocked": len(voices) - generated - pending}


def render_readme(data: dict) -> str:
    problems = manifest_problems(data)
    if problems:  # never publish, or claim completeness for, a manifest that contradicts the rights rule
        raise PreviewError("the manifest is inconsistent, so no README is written: " + "; ".join(problems[:3]))
    c = counts(data)
    complete = c["generated"] == c["total"]
    decision = data["owner_decision"]
    lines = [
        "# Voice previews", "",
        "Short (about 10 second) samples of the voices in the Audiobook Creation Tool, all reading the same sentence so "
        "they can be compared.", "",
        f"> **{c['generated']} of {c['total']} previews are available.** "
        + ("" if complete else f"The other {c['total'] - c['generated']} are **pending generation**"
           + (f" and {c['blocked']} are **withdrawn**" if c["blocked"] else "")
           + ": publication is authorized, but the audio cannot be made yet (see \"Pending previews\"). "
           "This folder is not a complete set until every row is available."), "",
        f"The sentence: *{data['sample_text']}*", "",
        "Each link below is the raw WAV. GitHub serves raw files as downloads, so a click saves the file and your audio player opens it. "
        "Publishing a sample is not an approval of its audio quality.", "",
        "| Voice | Engine | Preview (raw WAV) | Publication |", "|---|---|---|---|"]
    publication = {RIGHTS_CONFIRMED: "license reviewed", RIGHTS_OWNER: "owner-authorized", RIGHTS_UNRESOLVED: "not authorized"}
    for v in data["voices"]:
        preview = v["preview"]
        link = f"[{preview['file']}]({RAW_BASE}{preview['file']})" if is_available(v) else \
            ("pending generation" if preview["status"] == PREVIEW_PENDING else "withdrawn")
        lines.append(f"| {v['label']} | {v['backend']} | {link} | {publication[v['rights']['status']]} |")
    lines += [
        "", "## Publication decision", "",
        f"On {decision['date']} the owner decided: {decision['decision']} This supersedes the earlier restriction: "
        f"{decision['supersedes']}", "",
        f"- **Scope:** {decision['scope']} Not covered: {', '.join(decision['not_covered'])}.",
        f"- **What this is:** {decision['verification']}",
        "- **Kokoro and the two Qwen3 preset voices** are generated by local models whose license is Apache-2.0 (the "
        "evidence is recorded per voice in `previews.json`).",
        *(f"- **Separate gate:** {gate}" for gate in decision["separate_gates"]), ""]
    clones = [v for v in data["voices"] if is_clone(v) and is_available(v)]
    if clones:
        profile = clones[0]["preview"]["generation_profile"]
        lines += ["## The Qwen3 clone narration profile", "",
                  "The six Qwen3 cloned voices are meant to narrate calmly and evenly, with less pitch, intensity and pace variation than the "
                  f"model's own sampling gives. They are generated at temperature {profile['temperature']:.2f} (the Base model's default is 0.90) "
                  f"and sub-talker temperature {profile['subtalker_temperature']:.2f} (also 0.90 by default); top_p, top_k, the repetition "
                  "penalty and each chunk's seed are unchanged. The previews are made by the application's own clone path with that profile "
                  f"(profile revision {profile['revision']}), each from its original reference recording and an owner-approved transcript. "
                  "Neither the recordings nor the transcripts are published here.", ""]
    pending = [v for v in data["voices"] if v["preview"]["status"] == PREVIEW_PENDING and v["rights"]["status"] in AUTHORIZED]
    if pending:
        lines += ["## Pending previews", ""]
        lines += [f"- **{v['label']}**: {v['preview']['pending_reason']}" for v in pending]
        clones = [v["voice_id"] for v in pending if v["backend"] == "qwen3"]
        if clones:
            lines += [
                "", "To finish the pending Qwen3 clones: listen to each reference recording, correct its draft transcript so "
                "it matches exactly what is spoken, set that entry's `approved` to `true` (with the recording's `wav_sha256`), "
                "and keep the file at `files/runtime-data/qwen3/transcripts.json` (untracked; or point "
                "`ACT_QWEN3_TRANSCRIPTS` at it). Then run "
                f"`python files/dev-tools/voice_previews.py generate {' '.join(clones)}` and commit the new files. "
                "The transcript itself is never committed.", ""]
        else:
            lines.append("")
    lines += [
        "## How they are made", "",
        "Each preview is produced by the app's own engine for that voice (not a separate path), with leading and trailing "
        f"silence trimmed to {EDGE_SILENCE_MS} ms, saved as 24 kHz mono 16-bit WAV, and checked for length "
        f"({MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} s), clipping and silence. The Edge previews are a snapshot of Microsoft's "
        "online service on the date recorded in `previews.json`. That file records every voice's publication basis, and "
        "each preview's SHA-256, duration and date. Regenerate or validate with "
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
    elif entry.backend == "chatterbox":
        from tts import chatterbox_synth

        original = chatterbox_synth._export_mp3
        chatterbox_synth._export_mp3 = lambda arr, rate, output, bitrate=None: sf.write(
            output, np.asarray(arr, dtype="float32"), rate, subtype="PCM_16")
        try:
            chatterbox_synth.chatterbox_file_to_mp3(str(text_path), str(out_wav), entry.voice_id,
                                                    end_silence_ms=0, chunk_pause_ms=0)
        finally:
            chatterbox_synth._export_mp3 = original
    elif entry.backend == "edge":
        _synthesize_edge(entry, text_path, out_wav)
    elif entry.backend == "qwen3":
        from tts import qwen3_synth

        def wav_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
            shutil.copyfile(wav, mp3)  # keep the lossless WAV; the "mp3" name is only the hand-off path

        qwen3_synth.qwen3_file_to_mp3(str(text_path), str(out_wav), entry.voice_id, end_silence_ms=0,
                                      chunk_pause_ms=0, encoder=wav_encoder)
    else:
        raise PreviewError(f"{entry.voice_id}: no preview path exists for backend {entry.backend!r}")


def _synthesize_edge(entry, text_path: Path, out_wav: Path) -> None:
    """The Edge folder route's own request for this voice: its chunker, its ``synthesize_chunk_mp3`` and the voice's rate.

    Nothing is re-encoded to MP3: the service's MP3 is decoded straight to a WAV. There is no retry, fallback voice or
    other engine here -- a refusal or outage is reported (in ``edge_failures`` wording) and the voice stays pending.
    """
    from tts import batch_convert, edge_failures

    text = text_path.read_text(encoding="utf-8")
    chunks = batch_convert.split_into_chunks(text)
    if len(chunks) != 1:
        raise PreviewError(f"{entry.voice_id}: the sample text must be a single Edge chunk (found {len(chunks)})")
    mp3 = out_wav.with_suffix(".mp3")
    try:
        batch_convert.synthesize_chunk_mp3(chunks[0], str(mp3), entry.voice_id, entry.timing_preset["rate"])
    except Exception as exc:  # noqa: BLE001
        final = edge_failures.final_error(exc, 1)
        if final is exc:
            raise
        raise final from exc
    audio, rate = sf.read(str(mp3), dtype="float32")
    sf.write(str(out_wav), audio, rate, subtype="PCM_16")


def unavailable_reason(entry) -> str | None:
    """Why this machine cannot make this voice right now, or ``None``. Uses the app's own availability answer."""
    sys.path.insert(0, str(SCRIPTS))
    if entry.backend == "chatterbox":
        from tts import chatterbox_synth

        ok, reason = chatterbox_synth.voice_availability(entry.voice_id)
    elif entry.backend == "qwen3":
        from tts import qwen3_runtime

        ok, reason = qwen3_runtime.voice_availability(entry.voice_id)
    else:
        return None
    return None if ok else reason


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
            if record["rights"]["status"] not in AUTHORIZED:
                log(f"BLOCKED  {vid}: publication is not authorized; no preview is made")
                continue
            if is_available(record) and not voice_ids:
                continue
            reason = unavailable_reason(registry[vid])  # the app's own answer: a missing model, reference or transcript
            if reason:
                log(f"PENDING  {vid}: {reason}" + ("; the existing preview is kept" if is_available(record) else ""))
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
                if is_clone(record):  # the clone is made by the application's own profile; record exactly which
                    meta["generation_profile"] = current_clone_profile()
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
        print(f"{c['generated']} of {c['total']} previews available; {c['pending']} pending generation, {c['blocked']} withdrawn.")
        for v in data["voices"]:
            if not is_available(v):
                print(f"  {v['preview']['status']:8} {v['voice_id']:24} {v['rights']['status']}: "
                      f"{v['preview'].get('pending_reason') or 'publication not authorized'}")
        return 0 if c["generated"] == c["total"] else 2
    except PreviewError as exc:
        print("ERROR:", exc)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
