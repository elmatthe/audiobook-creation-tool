"""v0.8.0 Phase 2 -- the six OmniVoice voices: identity, the maximum-10-second silence-safe excerpts, readiness.

The excerpt rule is the owner's (2026-11-13): an excerpt starts at 0.000 s, ends no later than 10.000 s, inside a natural
quiet interval after a complete word, never inside a vowel, consonant or sibilant, and never padded or faded. These tests
hold the six reviewed crops to that rule on the real recordings, drive the rule with synthetic recordings that try to
break it (a cut-through word, a sibilant tail, a noisy floor, a stop closure, a zero crossing), and prove the originals,
the full-length transcripts and the 60 historical listening verdicts are untouched. Nothing here loads a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from shared import optional_setup_protocol as proto
from tts import omnivoice_runtime as ov
from tts import qwen3_runtime as rt
from tts import voice_install
from tts import voice_registry as vr

pytestmark = pytest.mark.usefixtures("production_writes_refused")

RATE = 24000
REPO = Path(__file__).resolve().parents[2]

#: The six reviewed crops: end frame (exclusive) at 24 kHz, and the excerpt transcript. Provisional until the owner's
#: Session 4 review; a change here is a change of a voice and must come with Decisions and Handoff entries.
REVIEWED = {
    "omnivoice-female-1": (199440, "It had already been several weeks since I'd gone to town. After we came home, Tanya "
                                   "and the rest of the servants were quite cross with me,"),
    "omnivoice-female-2": (176160, "Vice Chancellor Cloud Legan Barth, his direct superior, the Lord Chancellor Marquess "
                                   "Jorg Reclentos,"),
    "omnivoice-male-1": (117240, "Zeth, Sun Sun, Balano, truthless of Shinovar,"),
    "omnivoice-male-2": (198360, "Three carriages rattled down a narrow road, surrounded by a dense, dark wood. This was "
                                 "the Worm's Whiskers,"),
    "omnivoice-male-3": (196560, "Klein didn't stand on ceremony and said directly, I wish to borrow the magic wishing "
                                 "lamp for a day."),
    "omnivoice-male-4": (218280, "Hello Arthur. The voice drifted to me through a haze, distant and ethereal but "
                                 "familiar. I was drowsing,"),
}
#: Phase 1's owner-accepted proof crop for Male 1 (frame 230,760 = 9.615 s). Under the 2026-11-13 silence rule it is a
#: defect: it ends where "all" runs into the /th/ of "things", about 31 dB above the recording's floor.
PHASE1_MALE1_END = 230760
#: Canonical-JSON hashes of records that must never change: the six approved full-length transcripts (v0.7.0 P03C) and
#: the owner's 60 historical G1 listening verdicts (Plan 01B A4/A5).
BUNDLE_CANONICAL_SHA256 = "0923858f9c5fc6aaff466f15bdd941e5bbd553c8e0a6b0dfbef232f0a9df5053"
G1_CANONICAL_SHA256 = "d1148f7275e4f3e5e6393d45138f91d249473c3a51fcdec1f4c2ac5de593a7ef"


def canonical_sha256(path: Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def recording(voice_id: str) -> tuple[bytes, Path]:
    path = ov.reference_path(ov.get_voice(voice_id))
    pcm, _params = ov.read_pcm(path)
    return pcm, path


# --------------------------------------------------------------------------- #
# Six stable identities and their recordings
# --------------------------------------------------------------------------- #
def test_six_distinct_stable_voices_are_appended_after_the_unchanged_28():
    import test_voice_labels as shipped  # the 28 shipped identities, in order (v0.7.0 P02A)

    assert [v.key for v in vr.VOICES[:28]] == shipped.SHIPPED_KEYS
    added = vr.VOICES[28:]
    assert [(v.backend, v.voice_id, v.display_label) for v in added] == [
        ("omnivoice", f"omnivoice-{n.lower().replace(' ', '-')}", f"OmniVoice - {n}")
        for n in ("Female 1", "Female 2", "Male 1", "Male 2", "Male 3", "Male 4")]
    assert {v.group_label for v in added} == {vr.OMNIVOICE_GROUP_LABEL} != {vr.CHATTERBOX_GROUP_LABEL}
    assert all(v.timing_preset == vr._qwen3_preset() for v in added), "the normal local-engine policy, no new tuning"
    assert [v.voice_id for v in added] == [v.voice_id for v in ov.OMNIVOICE_VOICES]
    assert vr.DEFAULT_VOICE_KEY == ("edge", "en-US-SteffanNeural") and "omnivoice" in vr.BACKENDS


@pytest.mark.parametrize("voice", ov.OMNIVOICE_VOICES, ids=lambda v: v.voice_id)
def test_each_voice_is_cloned_from_the_same_recording_as_its_chatterbox_and_qwen3_namesakes(voice):
    suffix = voice.voice_id.removeprefix("omnivoice-")
    filename = vr.reference_recording_filename("omnivoice", voice.voice_id)
    assert filename == vr.reference_recording_filename("chatterbox", f"chatterbox-{suffix}") \
        == vr.reference_recording_filename("qwen3", f"qwen3-{suffix}") == f"Chatterbox - {suffix.replace('-', ' ').title()}.wav"
    assert vr.reference_id("omnivoice", voice.voice_id) == voice.reference_id
    assert rt.sha256_file(ov.reference_path(voice)) == ov.recording_sha256(voice.reference_id)


def test_a_registry_row_for_an_omnivoice_clone_without_a_recording_is_refused():
    stray = vr.VoiceEntry("omnivoice", "omnivoice-male-9", "OmniVoice - Male 9", vr.OMNIVOICE_GROUP_LABEL, {})
    assert any("no reference recording is mapped" in p for p in vr.registry_problems([*vr.VOICES, stray]))


def test_install_and_continue_names_the_component_but_offers_it_only_once_setup_knows_it(monkeypatch):
    assert voice_install.component_for("omnivoice", "omnivoice-male-2") == ov.COMPONENT == "omnivoice"
    assert voice_install.component_for("omnivoice", "omnivoice-unknown") is None
    monkeypatch.setattr(ov, "install_would_help", lambda: True)
    assert ov.COMPONENT not in proto.COMPONENTS  # plan Phase 3 adds it to the existing installer
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "not installed") is None
    monkeypatch.setattr(proto, "COMPONENTS", (*proto.COMPONENTS, ov.COMPONENT))
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "anything") == "omnivoice"
    monkeypatch.setattr(ov, "install_would_help", lambda: False)  # no GPU, or everything installed already
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "anything") is None


# --------------------------------------------------------------------------- #
# The six reviewed excerpts on the real recordings
# --------------------------------------------------------------------------- #
def test_the_authority_holds_exactly_the_six_reviewed_crops_and_transcripts():
    specs = ov.load_excerpts()
    assert set(specs) == set(REVIEWED)
    full = rt.load_bundle()
    for voice_id, (end, text) in REVIEWED.items():
        spec = specs[voice_id]
        assert (spec.crop_start_frame, spec.crop_end_frame, spec.sample_rate) == (0, end, RATE)
        assert spec.duration_s <= ov.MAX_EXCERPT_SECONDS
        assert spec.text == text and spec.text_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert full[spec.reference_id].startswith(text) and text != full[spec.reference_id]
        assert spec.last_word == text.split()[-1] and spec.status == "provisional"


@pytest.mark.parametrize("voice_id", sorted(REVIEWED))
def test_each_crop_is_the_latest_silence_safe_end_within_ten_seconds(voice_id):
    spec = ov.load_excerpts()[voice_id]
    pcm, path = recording(voice_id)
    assert hashlib.sha256(pcm[: spec.crop_end_frame * 2]).hexdigest() == spec.excerpt_pcm_sha256  # independent of derive
    assert ov.endpoint_problems(pcm, RATE, spec.crop_end_frame) == []
    end, pause = ov.latest_safe_endpoint(pcm, RATE)
    assert (end, pause) == (spec.crop_end_frame, (spec.pause_start_frame, spec.pause_end_frame)), "deterministic"
    # The natural quiet tail after the last word, and the guard before the next sound, both inside the pause.
    assert spec.crop_end_frame - spec.pause_start_frame >= int(ov.MIN_TAIL_S * RATE)
    assert spec.pause_end_frame - spec.crop_end_frame >= int(ov.GUARD_S * RATE)
    analysis = ov.analyse_quiet(pcm, RATE)
    tail = np.frombuffer(pcm[spec.pause_start_frame * 2: spec.crop_end_frame * 2], dtype="<i2").astype(float) / 32768
    assert 10 * np.log10(np.mean(tail ** 2) + 1e-12) < analysis.threshold_db


@pytest.mark.parametrize("voice_id", sorted(REVIEWED))
def test_a_strict_ten_second_cut_would_end_mid_speech_in_every_recording(voice_id):
    pcm, _ = recording(voice_id)
    assert ov.endpoint_problems(pcm, RATE, 10 * RATE) == ["the end (10.000 s) is not inside a natural pause"]


def test_the_phase1_male1_proof_crop_fails_the_silence_rule_and_was_replaced():
    pcm, _ = recording("omnivoice-male-1")
    assert ov.endpoint_problems(pcm, RATE, PHASE1_MALE1_END) == ["the end (9.615 s) is not inside a natural pause"]
    x = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
    level = 10 * np.log10(np.mean(x[PHASE1_MALE1_END - 480:PHASE1_MALE1_END] ** 2))
    assert level - ov.analyse_quiet(pcm, RATE).floor_db > 25, "speech, not a quiet interval"
    assert ov.load_excerpts()["omnivoice-male-1"].crop_end_frame == REVIEWED["omnivoice-male-1"][0] < PHASE1_MALE1_END


# --------------------------------------------------------------------------- #
# The rule against synthetic recordings
# --------------------------------------------------------------------------- #
def synth(segments: list[tuple[str, float]], *, floor: float = 0.0003, seed: int = 7) -> bytes:
    """16-bit mono PCM from ``(kind, seconds)`` pieces: ``speech`` (broadband, loud), ``sibilant`` (high band, softer),
    ``quiet`` (the recording's noise floor), ``zero`` (one exactly-zero sample, nothing else)."""
    rng = np.random.default_rng(seed)
    pieces = []
    for kind, seconds in segments:
        n = 1 if kind == "zero" else int(round(seconds * RATE))
        if kind == "speech":
            t = np.arange(n) / RATE
            piece = 0.25 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)) + rng.normal(0, 0.05, n)
        elif kind == "sibilant":
            noise = rng.normal(0, 1, n)
            piece = 0.06 * (noise - np.convolve(noise, np.ones(3) / 3, mode="same"))
        elif kind == "zero":
            piece = np.zeros(1)
        else:
            piece = rng.normal(0, floor, n)
        pieces.append(piece)
    x = np.clip(np.concatenate(pieces), -0.99, 0.99)
    return (x * 32767).astype("<i2").tobytes()


def at(seconds: float) -> int:
    return int(round(seconds * RATE))


def test_a_word_running_through_ten_seconds_is_never_cut_and_the_earlier_pause_is_used():
    pcm = synth([("quiet", 1.0), ("speech", 2.0), ("quiet", 0.4), ("speech", 9.6), ("quiet", 1.0)])
    assert ov.endpoint_problems(pcm, RATE, at(10.0)) == ["the end (10.000 s) is not inside a natural pause"]
    end, (start, stop) = ov.latest_safe_endpoint(pcm, RATE)
    assert at(2.99) <= start <= at(3.01) and end == stop - at(ov.GUARD_S) and end < at(3.4)


def test_a_sibilant_tail_is_part_of_the_word_and_the_cut_waits_for_the_quiet_after_it():
    pcm = synth([("quiet", 1.0), ("speech", 1.5), ("sibilant", 0.2), ("quiet", 0.5), ("speech", 8.0), ("quiet", 1.0)])
    problems = ov.endpoint_problems(pcm, RATE, at(2.65))  # inside the hiss
    assert problems == ["the end (2.650 s) is not inside a natural pause"]
    end, (start, _stop) = ov.latest_safe_endpoint(pcm, RATE)
    assert start >= at(2.69) and end > start


def test_background_noise_moves_the_threshold_so_a_real_pause_is_still_found():
    noisy = synth([("quiet", 1.0), ("speech", 3.0), ("quiet", 0.5), ("speech", 9.0), ("quiet", 1.0)], floor=0.01)
    analysis = ov.analyse_quiet(noisy, RATE)
    assert analysis.floor_db > -45, "a floor of about -40 dB, far above the -50 dB an absolute threshold would use"
    end, (start, _stop) = ov.latest_safe_endpoint(noisy, RATE)
    assert at(3.99) <= start <= at(4.01) and ov.endpoint_problems(noisy, RATE, end) == []


def test_a_stop_closure_or_a_zero_crossing_is_not_a_pause_and_an_earlier_real_pause_wins():
    pcm = synth([("quiet", 1.0), ("speech", 4.0), ("quiet", 0.5), ("speech", 2.5), ("quiet", 0.08), ("speech", 1.2),
                 ("zero", 0), ("speech", 4.72), ("quiet", 1.0)])
    closure, zero = at(8.04), at(1.0 + 4.0 + 0.5 + 2.5 + 0.08 + 1.2)
    assert ov.endpoint_problems(pcm, RATE, closure) == ["the end (8.040 s) is not inside a natural pause"]
    assert ov.endpoint_problems(pcm, RATE, zero + 1)[0].endswith("is not inside a natural pause")
    end, (start, _stop) = ov.latest_safe_endpoint(pcm, RATE)
    assert at(4.99) <= start <= at(5.01) and end < at(5.5)


def test_a_cut_needs_a_quiet_tail_after_the_word_and_a_guard_before_the_next_one():
    pcm = synth([("quiet", 1.0), ("speech", 3.0), ("quiet", 0.4), ("speech", 9.0), ("quiet", 1.0)])
    assert ov.endpoint_problems(pcm, RATE, at(4.04))[0].startswith("only ")  # 40 ms after the word
    assert ov.endpoint_problems(pcm, RATE, at(4.39))[0].startswith("the end is only ")  # 10 ms before the next


def test_continuous_speech_has_no_defensible_endpoint():
    assert ov.latest_safe_endpoint(synth([("quiet", 1.0), ("speech", 14.0)]), RATE) is None


# --------------------------------------------------------------------------- #
# Excerpt transcripts: refused unless they are the approved transcript's own opening words
# --------------------------------------------------------------------------- #
FULL = "Zeth, Sun Sun, Balano, truthless of Shinovar, sat atop the highest tower."


@pytest.mark.parametrize("excerpt, message", [
    ("Zeth, Sun Sun, Balano, truthful of Shinovar,", "word 5"),
    ("Zeth, Sun Sun, Balano, of Shinovar,", "word 5"),
    ("Zeth, Sun Sun, Balano, truthless of Shinovar, sat", None),
    ("Zeth, Sun Sun, Balano, truthless of Shinovar, sat atop the highest tower.", "as long as"),
    ("Zeth, Sun Sun, Balano, truthless of Shino", "last word"),
    (" Zeth,", "leading or trailing"),
    ("", "blank"),
])
def test_an_excerpt_transcript_must_be_the_approved_opening_words(excerpt, message):
    if message is None:
        ov.validate_excerpt_transcript(FULL, excerpt)
        ov.validate_excerpt_transcript(FULL, "Zeth, Sun Sun, Balano, truthless of Shinovar.")  # only punctuation moves
        return
    with pytest.raises(ov.ExcerptError, match=message):
        ov.validate_excerpt_transcript(FULL, excerpt)


def edited_authority(tmp_path: Path, change) -> Path:
    data = json.loads(ov.excerpts_path().read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "omnivoice_excerpts.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _set(index: int, **fields):
    return lambda data: data["entries"][index].update(fields)


@pytest.mark.parametrize("change, message", [
    (_set(2, crop_end_frame=240001), "inside the first 10 seconds"),
    (_set(2, crop_start_frame=1200), "starts at 0.000"),
    (_set(2, text="Zeth, Sun Sun, Balano, truthless of Shinovar, sat"), "checksum"),
    (_set(2, original_wav_sha256="0" * 64), "different recording"),
    (_set(2, reference_id="Male-2"), "not one of the six"),
    (_set(2, status="approved-by-claude"), "unknown status"),
    (_set(2, crop_end_frame=117240 + 1150), "natural pause"),
    (_set(0, last_word="town."), "last word"),
    (lambda data: data["entries"].pop(), "exactly 6"),
    (lambda data: data.update(rule="first-10s"), "another rule"),
    (lambda data: data["entries"][1].update(extra=1), "unexpected fields"),
])
def test_a_damaged_or_mismatched_authority_is_refused_whole(tmp_path, change, message):
    with pytest.raises(ov.ExcerptError, match=message):
        ov.load_excerpts(edited_authority(tmp_path, change))


def test_a_transcript_that_does_not_match_the_full_one_is_refused(tmp_path):
    text = "Zeth, Sun Sun, Balano, truthful of Shinovar,"
    path = edited_authority(tmp_path, _set(2, text=text, text_sha256=ov.text_sha256(text)))
    with pytest.raises(ov.ExcerptError, match="word 5"):
        ov.load_excerpts(path)


# --------------------------------------------------------------------------- #
# The originals, the full transcripts and the historical verdicts are never changed
# --------------------------------------------------------------------------- #
def test_the_full_length_transcripts_and_the_sixty_historical_verdicts_are_untouched():
    assert canonical_sha256(rt.bundled_transcripts_path()) == BUNDLE_CANONICAL_SHA256
    g1 = REPO / "files" / "tests" / "golden" / "speech" / "g1-verdicts.json"
    assert canonical_sha256(g1) == G1_CANONICAL_SHA256
    verdicts = json.loads(g1.read_text(encoding="utf-8"))["verdicts"]
    assert len(verdicts) == 60 and not any(v["engine"] == "omnivoice" for v in verdicts)


@pytest.mark.parametrize("voice_id", sorted(REVIEWED))
def test_deriving_an_excerpt_reads_the_original_and_never_changes_it(tmp_path, voice_id):
    spec = ov.load_excerpts()[voice_id]
    original = ov.reference_path(ov.get_voice(voice_id))
    before = (original.read_bytes(), os.stat(original).st_mtime_ns)
    facts = ov.derive_excerpt(spec, original, tmp_path / "excerpt.wav")  # writes refused anywhere but tmp
    assert (original.read_bytes(), os.stat(original).st_mtime_ns) == before
    assert rt.sha256_file(original) == spec.original_wav_sha256 == ov.recording_sha256(spec.reference_id)
    with wave.open(facts["path"], "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, RATE, spec.crop_end_frame)
        assert hashlib.sha256(w.readframes(w.getnframes())).hexdigest() == spec.excerpt_pcm_sha256
    assert rt.sha256_file(Path(facts["path"])) == spec.excerpt_wav_sha256
    assert facts["frames"] <= ov.MAX_EXCERPT_SECONDS * RATE


def test_an_excerpt_is_refused_over_its_original_an_existing_file_or_a_changed_recording(tmp_path):
    spec = ov.load_excerpts()["omnivoice-male-3"]
    copy = tmp_path / "copy.wav"
    shutil.copyfile(ov.reference_path(ov.get_voice("omnivoice-male-3")), copy)
    with pytest.raises(ov.ExcerptError, match="never written over"):
        ov.derive_excerpt(spec, copy, copy)
    (tmp_path / "taken.wav").write_bytes(b"x")
    with pytest.raises(ov.ExcerptError, match="already exists"):
        ov.derive_excerpt(spec, copy, tmp_path / "taken.wav")
    data = bytearray(copy.read_bytes())
    data[-10] ^= 0xFF
    copy.write_bytes(bytes(data))
    with pytest.raises(ov.ExcerptError, match="not the recording"):
        ov.derive_excerpt(spec, copy, tmp_path / "new.wav")
    assert not (tmp_path / "new.wav").exists() and not (tmp_path / "new.wav.part").exists()


# --------------------------------------------------------------------------- #
# The prompt cache identity
# --------------------------------------------------------------------------- #
def test_the_prompt_cache_key_moves_with_every_input_that_shapes_the_prompt():
    from dataclasses import replace

    spec = ov.load_excerpts()["omnivoice-female-1"]
    base = dict(model_revision="c5fdb5ccb189668d56333f77ba2629f4cd7535f4", omnivoice_version="0.2.1",
                preprocess_prompt=True, dtype="float16")
    key, fields = ov.prompt_identity(spec, **base)
    assert key == ov.prompt_identity(spec, **base)[0] and len(key) == 64
    variants = [
        ov.prompt_identity(replace(spec, crop_end_frame=spec.crop_end_frame - 120), **base),
        ov.prompt_identity(replace(spec, excerpt_pcm_sha256="1" * 64), **base),
        ov.prompt_identity(replace(spec, text_sha256="2" * 64), **base),
        ov.prompt_identity(replace(spec, original_wav_sha256="3" * 64), **base),
        ov.prompt_identity(spec, **{**base, "model_revision": "0" * 40}),
        ov.prompt_identity(spec, **{**base, "omnivoice_version": "0.2.2"}),
        ov.prompt_identity(spec, **{**base, "preprocess_prompt": False}),
        ov.prompt_identity(spec, **{**base, "dtype": "float32"}),
    ]
    assert len({key, *(k for k, _ in variants)}) == len(variants) + 1
    assert fields["crop"] == [0, spec.crop_end_frame, RATE] and fields["silence_rule"] == ov.SILENCE_RULE_VERSION
    assert ov.prompt_cache_path(spec.voice_id, key).name == f"omnivoice-female-1__{key[:24]}.pt"


# --------------------------------------------------------------------------- #
# Readiness, against sandboxed environments and models
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A repository root with its own runtime folder, environment and a two-file model manifest."""
    root = tmp_path / "repo"
    (root / "files").mkdir(parents=True)
    monkeypatch.setattr(ov, "repo_root", lambda: root)
    monkeypatch.setattr(ov, "runtime_dir", lambda: root / "files" / "runtime-data" / "omnivoice")
    monkeypatch.setattr(ov, "venv_dir", lambda: root / ".venv-omnivoice")
    files = {"config.json": b'{"a": 1}', "audio_tokenizer/config.json": b'{"b": 2}'}
    manifest = {
        "schema": "act-omnivoice-engine", "version": 1, "engine": {"omnivoice": "0.2.1"},
        "model": {"repo": "k2-fsa/OmniVoice", "revision": "c" * 40, "load_required": sorted(files),
                  "files": {n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()}},
        "packages": [["omnivoice", "0.2.1"], ["torch", "2.8.0+cu128"], ["huggingface_hub", "1.7.2"]],
    }
    assert ov.manifest_problems(manifest) == []
    monkeypatch.setattr(ov, "load_manifest", lambda: manifest)

    class Sandbox:
        def make_env(self, packages=(("omnivoice", "0.2.1"), ("torch", "2.8.0+cu128"), ("huggingface-hub", "1.7.2"),
                                     ("pip", "25.0"))):
            env = ov.venv_dir()
            (env / "Scripts").mkdir(parents=True, exist_ok=True)
            (env / "Scripts" / "python.exe").write_bytes(b"")
            (env / "bin").mkdir(exist_ok=True)
            (env / "bin" / "python").write_bytes(b"")
            (env / "pyvenv.cfg").write_text("home = x\nversion = 3.12.10\n", encoding="utf-8")
            site = ov.site_packages(env)
            if site.exists():
                shutil.rmtree(site)
            site.mkdir(parents=True)
            for name, version in packages:
                (site / f"{name.replace('-', '_')}-{version}.dist-info").mkdir()

        def make_model(self):
            for name, data in files.items():
                path = ov.model_dir().joinpath(*name.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    return Sandbox()


def test_the_environment_must_hold_exactly_the_pinned_packages(sandbox):
    assert ov.environment_status() == (False, ov.NOT_INSTALLED_MESSAGE)
    sandbox.make_env()
    assert ov.environment_status() == (True, "ok")
    sandbox.make_env(packages=(("omnivoice", "0.2.1"), ("torch", "2.10.0"), ("huggingface-hub", "1.7.2")))
    assert "1 at another version: torch" in ov.environment_status()[1]
    sandbox.make_env(packages=(("omnivoice", "0.2.1"), ("huggingface-hub", "1.7.2")))
    assert "1 missing: torch" in ov.environment_status()[1]
    sandbox.make_env(packages=(("omnivoice", "0.2.1"), ("torch", "2.8.0+cu128"), ("huggingface-hub", "1.7.2"),
                               ("openai-whisper", "1.0")))
    assert "not part of it: openai-whisper" in ov.environment_status()[1]


def test_the_model_is_ready_only_after_a_full_verification_and_stays_ready_until_a_file_changes(sandbox):
    assert "is not installed" in ov.model_status()[1]
    sandbox.make_model()
    assert "have not been verified" in ov.model_status()[1]
    assert ov.verify_model_files() == []
    assert ov.model_status() == (True, "ok")
    assert ov.model_record_path().parent == ov.runtime_dir() and not str(ov.model_record_path()).startswith(
        str(ov.model_dir())), "the record lives beside the snapshot, never inside it"
    target = ov.model_dir() / "config.json"
    target.write_bytes(b'{"a": 9}')  # same size, other bytes
    assert ov.BAD_CHANGED in ov.model_status()[1]
    assert ov.verify_model_files() == ["config.json does not match its SHA-256"]


def test_availability_says_why_in_order_and_never_offers_an_install_without_a_gpu(sandbox, monkeypatch):
    monkeypatch.setattr(ov, "platform_supported", lambda: False)
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.platform_reason())
    monkeypatch.setattr(ov, "platform_supported", lambda: True)
    monkeypatch.setattr(ov, "detect_gpu", lambda: None)
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.NO_GPU_MESSAGE)
    assert ov.install_would_help() is False
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("RTX", 12000))
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.NOT_INSTALLED_MESSAGE)
    assert ov.install_would_help() is True
    sandbox.make_env()
    sandbox.make_model()
    assert ov.verify_model_files() == []
    monkeypatch.setattr(ov, "reference_path", lambda voice: REPO / "files" / "Cloned-Voice-Uploads"
                        / vr.reference_recording_filename("omnivoice", voice.voice_id))
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")
    assert ov.install_would_help() is False
    assert ov.voice_availability("omnivoice-nobody")[0] is False


def test_a_changed_recording_makes_only_that_voice_unavailable(sandbox, monkeypatch, tmp_path):
    changed = tmp_path / "changed.wav"
    changed.write_bytes(b"RIFF....WAVE")
    monkeypatch.setattr(ov, "reference_path", lambda voice: changed)
    ok, reason = ov.reference_status(ov.get_voice("omnivoice-female-2"))
    assert not ok and "does not match the one OmniVoice - Female 2 was approved against" in reason


# --------------------------------------------------------------------------- #
# Local-only loading: no network, no Hub, no speech recognizer
# --------------------------------------------------------------------------- #
def test_the_worker_environment_is_offline_contained_and_unsteered(sandbox):
    base = {"PATH": os.environ.get("PATH", ""), "HF_ENDPOINT": "https://example.invalid", "HF_TOKEN": "secret",
            "HF_HOME": "C:/elsewhere", "TRANSFORMERS_CACHE": "C:/elsewhere", "PYTHONPATH": "C:/x", "PIP_INDEX_URL": "x",
            "VIRTUAL_ENV": "C:/other", "CUDA_VISIBLE_DEVICES": "0"}
    env = ov.worker_environment(base)
    for name in ("HF_ENDPOINT", "HF_TOKEN", "TRANSFORMERS_CACHE", "PYTHONPATH", "PIP_INDEX_URL", "VIRTUAL_ENV"):
        assert name not in env
    assert all(env[k] == v for k, v in ov.OFFLINE.items())
    assert Path(env["HF_HOME"]).is_relative_to(ov.runtime_dir()) and Path(env["TEMP"]).is_relative_to(ov.runtime_dir())
    assert env["CUDA_VISIBLE_DEVICES"] == "0", "the user's own GPU choice is kept"


def test_the_worker_closes_the_network_before_anything_heavy_loads(tmp_path):
    """Run in a child: an audit hook can never be removed from the process that installs it."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import json, socket, sys\n"
        f"sys.path.insert(0, {str(Path(ov.worker_script()).parent)!r})\n"
        "import omnivoice_worker as w\n"
        "log = []\n"
        "w.install_network_guard(log)\n"
        "refused = []\n"
        "for host in ('huggingface.co', '8.8.8.8'):\n"
        "    try:\n"
        "        socket.getaddrinfo(host, 443)\n"
        "    except w.NetworkRefused:\n"
        "        refused.append(host)\n"
        "socket.getaddrinfo('127.0.0.1', 80)\n"
        "print(json.dumps({'refused': refused, 'log': log}))\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["refused"] == ["huggingface.co", "8.8.8.8"] and len(out["log"]) == 2


def test_the_worker_never_asks_the_hub_never_loads_whisper_and_never_normalizes_again():
    import ast

    source = Path(ov.worker_script()).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {getattr(n.func, "attr", getattr(n.func, "id", "")): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    generate = calls["generate"]
    assert any(k.arg == "normalize_text" and isinstance(k.value, ast.Constant) and k.value.value is False
               for k in generate.keywords)
    assert "load_asr_model = _refuse_speech_recognizer" in source and "load_asr_model(" not in source
    assert "k2-fsa/" not in source and "hf_hub_download" not in source and "snapshot_download" not in source
    from tts import omnivoice_worker as w

    job = {"schema": 1, "kind": "synth"}
    assert any("HF_HUB_OFFLINE" in p for p in w.job_problems(job, {}))
    with pytest.raises(w.SpeechRecognizerRefused):
        w._refuse_speech_recognizer()
