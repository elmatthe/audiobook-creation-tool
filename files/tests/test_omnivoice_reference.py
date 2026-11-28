"""v0.8.0 Phase 2 -- the six OmniVoice voices: identity, their own owner-curated reference recordings, readiness.

Owner decision 2026-11-13 (the Phase 2 reference correction): each OmniVoice voice is conditioned on its OWN recording,
``files/Cloned-Voice-Uploads/OmniVoice/OmniVoice - <Voice>.wav``, used whole (no further crop), with the owner-written
transcript as reference text. Ten seconds stays the maximum; the ONE exception is OmniVoice - Male 1 (about 10.227 s),
bound to that exact file and frame count. These tests hold the real recordings to that rule, try to widen the
exception, prove the recordings are only read, and prove the 60 historical listening verdicts and Qwen3's full-length
transcripts are untouched. Nothing here loads a model.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from tts import omnivoice_runtime as ov
from tts import qwen3_runtime as rt
from tts import voice_install
from tts import voice_registry as vr

#: A macOS simulation runs code that takes a real ``fcntl`` lock; Windows has no such module, and faking one would hide the
#: lock the test is about (Checkpoint D). These run for real on a Mac; the Windows gate names the skip in its policy.
needs_fcntl = pytest.mark.skipif(importlib.util.find_spec("fcntl") is None,
                                 reason="this macOS simulation imports fcntl, which only POSIX has")

pytestmark = pytest.mark.usefixtures("production_writes_refused")

REPO = Path(__file__).resolve().parents[2]
RATE = 44100
#: The six owner recordings: decoded frame count at 44.1 kHz (exact; the seconds are rounded for people).
FRAMES = {
    "omnivoice-female-1": 354241,  # 8.033 s
    "omnivoice-female-2": 320414,  # 7.266 s
    "omnivoice-male-1": 451022,    # 10.227 s -- the one owner exception
    "omnivoice-male-2": 391826,    # 8.885 s
    "omnivoice-male-3": 327931,    # 7.436 s
    "omnivoice-male-4": 217055,    # 4.922 s
}
MALE1_SHA256 = "7753385380675913f0b97c5a03ca6d63702dec13c4905d7f014dc45ef7b1ccf7"
#: Canonical-JSON hashes of records that must never change: the six approved full-length (Qwen3) transcripts (v0.7.0
#: P03C) and the owner's 60 historical G1 listening verdicts (Plan 01B A4/A5).
BUNDLE_CANONICAL_SHA256 = "0923858f9c5fc6aaff466f15bdd941e5bbd553c8e0a6b0dfbef232f0a9df5053"
G1_CANONICAL_SHA256 = "d1148f7275e4f3e5e6393d45138f91d249473c3a51fcdec1f4c2ac5de593a7ef"


def canonical_sha256(path: Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def real_reference(voice_id: str) -> Path:
    return REPO.joinpath(*vr.reference_recording_parts("omnivoice", voice_id))


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
def test_each_voice_is_cloned_from_its_own_omnivoice_recording(voice):
    suffix = voice.voice_id.removeprefix("omnivoice-")
    name = f"OmniVoice - {suffix.replace('-', ' ').title()}.wav"
    assert vr.reference_recording_filename("omnivoice", voice.voice_id) == name
    assert ov.reference_path(voice) == REPO / "files" / "Cloned-Voice-Uploads" / "OmniVoice" / name
    others = {REPO.joinpath(*vr.reference_recording_parts(b, f"{b}-{suffix}")) for b in ("chatterbox", "qwen3")}
    assert ov.reference_path(voice) not in others
    assert rt.sha256_file(ov.reference_path(voice)) == voice.reference_sha256
    assert voice.reference_sha256 not in {rt.sha256_file(p) for p in others}, "never another engine's recording"
    assert vr.reference_id("omnivoice", voice.voice_id) == voice.reference_id


def test_a_registry_row_for_an_omnivoice_clone_without_a_recording_is_refused():
    stray = vr.VoiceEntry("omnivoice", "omnivoice-male-9", "OmniVoice - Male 9", vr.OMNIVOICE_GROUP_LABEL, {})
    assert any("no reference recording is mapped" in p for p in vr.registry_problems([*vr.VOICES, stray]))


def test_install_and_continue_names_the_component_and_offers_it_only_when_installing_can_help(monkeypatch):
    assert voice_install.component_for("omnivoice", "omnivoice-male-2") == ov.COMPONENT == "omnivoice"
    assert voice_install.component_for("omnivoice", "omnivoice-unknown") is None
    assert ov.COMPONENT == proto.OMNIVOICE and ov.COMPONENT in proto.COMPONENTS  # v0.8.0 Phase 3: the fifth component
    asked: list = []
    monkeypatch.setattr(ov, "install_would_help", lambda voice_id=None: asked.append(voice_id) or True)
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "anything") == "omnivoice"
    assert asked == ["omnivoice-male-2"], "the voice's own recording is part of the question"
    monkeypatch.setattr(ov, "install_would_help", lambda voice_id=None: False)  # no GPU, a bad recording, or ready
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "anything") is None
    monkeypatch.setattr(proto, "COMPONENTS", tuple(c for c in proto.COMPONENTS if c != ov.COMPONENT))
    monkeypatch.setattr(ov, "install_would_help", lambda voice_id=None: True)
    assert voice_install.installable("omnivoice", "omnivoice-male-2", "anything") is None, "unknown to setup: never"


# --------------------------------------------------------------------------- #
# The duration rule: at most 10 s, one owner exception bound to one exact file
# --------------------------------------------------------------------------- #
def test_the_maximum_is_still_ten_seconds_and_there_is_exactly_one_exception():
    assert ov.MAX_REFERENCE_SECONDS == 10
    assert ov.DURATION_EXCEPTIONS == {"omnivoice-male-1": (MALE1_SHA256, FRAMES["omnivoice-male-1"], RATE)}


@pytest.mark.parametrize("voice_id", sorted(FRAMES))
def test_the_real_references_respect_the_rule(voice_id):
    spec = ov.load_references()[voice_id]
    assert (spec.frames, spec.sample_rate, spec.channels, spec.sample_width_bytes) == (FRAMES[voice_id], RATE, 1, 2)
    with wave.open(str(real_reference(voice_id)), "rb") as w:
        assert (w.getnframes(), w.getframerate()) == (spec.frames, spec.sample_rate)  # recomputed from the file
    if voice_id == "omnivoice-male-1":
        assert spec.frames > 10 * RATE and spec.max_frames == spec.frames == 451022
        assert round(spec.duration_s, 3) == 10.227
    else:
        assert spec.frames <= 10 * RATE and spec.max_frames == 10 * RATE
    assert ov.duration_problem(spec) is None


def test_the_male1_exception_widens_nothing_else():
    specs = ov.load_references()
    male1, female1 = specs["omnivoice-male-1"], specs["omnivoice-female-1"]
    too_long = [
        replace(male1, wav_sha256="0" * 64),            # another recording for Male 1
        replace(male1, frames=male1.frames + 1),        # the same file claimed one frame longer
        replace(female1, frames=male1.frames),          # another voice as long as Male 1
        replace(female1, frames=male1.frames, wav_sha256=MALE1_SHA256),  # ...even with Male 1's file hash
        replace(female1, frames=10 * RATE + 1),         # anything a frame over ten seconds
    ]
    for spec in too_long:
        assert spec.frames > spec.max_frames == 10 * spec.sample_rate
        assert "at most 10 s" in ov.duration_problem(spec), spec
    assert ov.duration_problem(replace(female1, frames=10 * RATE)) is None, "exactly ten seconds is allowed"


def _edited_list(tmp_path: Path, voice_id: str, **fields) -> Path:
    from tts import clone_references as cr

    data = json.loads(cr.manifest_path().read_text(encoding="utf-8"))
    next(e for e in data["entries"] if e["voice_id"] == voice_id).update(fields)
    path = tmp_path / "clone_references.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_list_claiming_more_than_ten_seconds_is_refused(tmp_path):
    with pytest.raises(ov.ReferenceAssetError, match="at most 10 s"):
        ov.load_references(_edited_list(tmp_path, "omnivoice-female-2", frames=10 * RATE + 1))
    with pytest.raises(ov.ReferenceAssetError, match="at most 10 s"):
        ov.load_references(_edited_list(tmp_path, "omnivoice-male-1", frames=451023))


def test_a_damaged_list_makes_the_voice_unavailable_not_substituted(tmp_path, monkeypatch):
    from tts import clone_references as cr

    damaged = _edited_list(tmp_path, "omnivoice-male-3", text="Klein said directly.")
    monkeypatch.setattr(cr, "manifest_path", lambda: damaged)
    with pytest.raises(ov.OmniVoiceUnavailable, match="reference list shipped with the app is damaged"):
        ov.reference_spec("omnivoice-male-3")
    ok, reason = ov.reference_status(ov.get_voice("omnivoice-male-3"))
    assert not ok and reason.startswith("Setup required for OmniVoice - Male 3")


# --------------------------------------------------------------------------- #
# The recordings are verified, never changed, and reach the worker whole
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("voice_id", sorted(FRAMES))
def test_verifying_a_reference_reads_it_and_never_changes_it(voice_id):
    voice = ov.get_voice(voice_id)
    spec = ov.load_references()[voice_id]
    original = ov.reference_path(voice)
    before = (original.read_bytes(), os.stat(original).st_mtime_ns)
    facts = ov.verify_reference(spec, original)
    assert (original.read_bytes(), os.stat(original).st_mtime_ns) == before
    assert facts == {"wav": str(original), "wav_sha256": voice.reference_sha256, "frames": FRAMES[voice_id],
                     "sample_rate": RATE, "max_frames": spec.max_frames}
    assert hashlib.sha256(before[0]).hexdigest() == spec.wav_sha256


def test_a_changed_recording_or_a_wrong_format_is_refused(tmp_path):
    spec = ov.load_references()["omnivoice-male-3"]
    copy = tmp_path / "copy.wav"
    shutil.copyfile(real_reference("omnivoice-male-3"), copy)
    assert ov.verify_reference(spec, copy)["frames"] == spec.frames
    with pytest.raises(ov.ReferenceAssetError, match="not in the approved format"):
        ov.verify_reference(replace(spec, frames=spec.frames - 1), copy)
    with pytest.raises(ov.ReferenceAssetError, match="not in the approved format"):
        ov.verify_reference(replace(spec, sample_rate=24000), copy)
    data = bytearray(copy.read_bytes())
    data[-10] ^= 0xFF
    copy.write_bytes(bytes(data))
    with pytest.raises(ov.ReferenceAssetError, match="not the recording"):
        ov.verify_reference(spec, copy)
    with pytest.raises(ov.ReferenceAssetError, match="could not be read"):
        ov.verify_reference(spec, tmp_path / "missing.wav")
    other = real_reference("omnivoice-male-4")  # a real, approved recording -- of another voice
    with pytest.raises(ov.ReferenceAssetError, match="not the recording"):
        ov.verify_reference(spec, other)


def test_the_full_length_transcripts_and_the_sixty_historical_verdicts_are_untouched():
    assert canonical_sha256(rt.bundled_transcripts_path()) == BUNDLE_CANONICAL_SHA256
    g1 = REPO / "files" / "tests" / "golden" / "speech" / "g1-verdicts.json"
    assert canonical_sha256(g1) == G1_CANONICAL_SHA256
    verdicts = json.loads(g1.read_text(encoding="utf-8"))["verdicts"]
    assert len(verdicts) == 60 and not any(v["engine"] == "omnivoice" for v in verdicts)


def test_the_phase2_excerpt_machinery_is_gone():
    """The derived-excerpt crop (Phase 2's first design) was replaced by the owner-curated recordings."""
    for name in ("derive_excerpt", "load_excerpts", "excerpt_spec", "latest_safe_endpoint", "validate_excerpt_transcript"):
        assert not hasattr(ov, name), name
    assert not (REPO / "scripts" / "tts" / "data" / "omnivoice_excerpts.json").exists()


# --------------------------------------------------------------------------- #
# The prompt cache identity
# --------------------------------------------------------------------------- #
def test_the_prompt_cache_key_moves_with_every_input_that_shapes_the_prompt():
    spec = ov.load_references()["omnivoice-female-1"]
    base = dict(model_revision="c5fdb5ccb189668d56333f77ba2629f4cd7535f4", omnivoice_version="0.2.1",
                preprocess_prompt=True, dtype="float16")
    key, fields = ov.prompt_identity(spec, **base)
    assert key == ov.prompt_identity(spec, **base)[0] and len(key) == 64
    variants = [
        ov.prompt_identity(replace(spec, wav_sha256="3" * 64), **base),       # another recording
        ov.prompt_identity(replace(spec, text_sha256="2" * 64), **base),      # another transcript
        ov.prompt_identity(replace(spec, frames=spec.frames - 1), **base),
        ov.prompt_identity(replace(spec, sample_rate=24000), **base),
        ov.prompt_identity(replace(spec, voice_id="omnivoice-female-2"), **base),
        ov.prompt_identity(spec, **{**base, "model_revision": "0" * 40}),
        ov.prompt_identity(spec, **{**base, "omnivoice_version": "0.2.2"}),
        ov.prompt_identity(spec, **{**base, "preprocess_prompt": False}),
        ov.prompt_identity(spec, **{**base, "dtype": "float32"}),
    ]
    assert len({key, *(k for k, _ in variants)}) == len(variants) + 1
    assert fields["schema"] == 2 and fields["reference"] == [spec.frames, RATE]
    assert fields["preprocessing_version"] == ov.PREPROCESSING_VERSION == "act-omnivoice-reference-v3"
    assert fields["wav_sha256"] == spec.wav_sha256 and fields["text_sha256"] == spec.text_sha256
    assert ov.prompt_cache_path(spec.voice_id, key).name == f"omnivoice-female-1__{key[:24]}.pt"


def test_a_phase2_excerpt_prompt_can_never_be_reused():
    """A schema-1 (excerpt) identity has other fields and another schema: no new key can equal an old one."""
    spec = ov.load_references()["omnivoice-male-1"]
    _key, fields = ov.prompt_identity(spec, model_revision="c" * 40, omnivoice_version="0.2.1", preprocess_prompt=True,
                                      dtype="float16")
    assert fields["schema"] != 1 and not {"crop", "excerpt_pcm_sha256", "silence_rule", "original_wav_sha256"} & set(fields)


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
    # The one environment path is derived from the root (.venv/engines/omnivoice, the unified layout); a too-deep
    # temporary folder must not turn "not installed" into "this folder is too deep" (that rule has its own tests).
    monkeypatch.setattr(ov, "install_depth_problem", lambda *a, **k: "")
    assert ov.venv_dir() == root / ".venv" / "engines" / "omnivoice"
    files = {"config.json": b'{"a": 1}', "audio_tokenizer/config.json": b'{"b": 2}'}
    pins = [["omnivoice", "0.2.1"], ["torch", "2.8.0+cu128"], ["huggingface_hub", "1.7.2"]]
    manifest = {
        "schema": "act-omnivoice-engine", "version": 1, "engine": {"omnivoice": "0.2.1"},
        "model": {"repo": "k2-fsa/OmniVoice", "revision": "c" * 40, "url_template": ov.HUB_URL_TEMPLATE,
                  "load_required": sorted(files),
                  "files": {n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()}},
        "packages": pins,
        # v0.8.0 Phase 3: every pinned package is also a pinned wheel (URL, size, SHA-256) the installer may fetch.
        "wheels": [{"name": n, "version": v, "filename": f"{n}-{v}-py3-none-any.whl",
                    "url": f"https://files.pythonhosted.org/packages/00/{n}-{v}-py3-none-any.whl", "size": 7,
                    "sha256": hashlib.sha256(n.encode()).hexdigest()} for n, v in pins],
    }
    assert ov.manifest_problems(manifest) == []
    monkeypatch.setattr(ov, "load_manifest", lambda: manifest)
    base_dir = tmp_path / "base-python"
    base_dir.mkdir()
    (base_dir / "python.exe").write_bytes(b"MZ")
    monkeypatch.setattr(ov, "app_base_python", lambda: base_dir / "python.exe")

    class Sandbox:
        def make_env(self, packages=(("omnivoice", "0.2.1"), ("torch", "2.8.0+cu128"), ("huggingface-hub", "1.7.2"),
                                     ("pip", "25.0"))):
            env = ov.venv_dir()
            (env / "Scripts").mkdir(parents=True, exist_ok=True)
            (env / "Scripts" / "python.exe").write_bytes(b"")
            (env / "bin").mkdir(exist_ok=True)
            (env / "bin" / "python").write_bytes(b"")
            (env / "pyvenv.cfg").write_text(
                f"home = {base_dir}\ninclude-system-site-packages = false\nversion = 3.12.10\n"
                f"executable = {base_dir / 'python.exe'}\ncommand = {base_dir / 'python.exe'} -m venv {env}\n",
                encoding="utf-8")
            site = ov.site_packages(env)
            if site.exists():
                shutil.rmtree(site)
            site.mkdir(parents=True)
            for name, version in packages:
                (site / f"{name.replace('-', '_')}-{version}.dist-info").mkdir()

        def prove(self):
            """What the installer writes once its proof passed (tts.omnivoice_setup.record_proved)."""
            from shared import venv_layout

            ov.write_receipt(ov.STAGE_INSTALLED, origin=ov.ORIGIN_INSTALLED,
                             base=venv_layout.base_identity(ov.venv_dir()), probe={}, probe_ok=True)

        def make_model(self):
            for name, data in files.items():
                path = ov.model_dir().joinpath(*name.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    return Sandbox()


def test_the_environment_must_hold_exactly_the_pinned_packages(sandbox, monkeypatch):
    monkeypatch.setattr(ov, "_system", lambda: "win32")  # Windows' 88-wheel set (torch +cu128), asked on any host
    assert ov.environment_status() == (False, ov.NOT_INSTALLED_MESSAGE)
    sandbox.make_env()
    # v0.8.0 Phase 3: exactly the pinned set is not enough on its own -- it is unchecked until the installer proves it
    assert ov.environment_status() == (False, ov.UNCHECKED_MESSAGE)
    sandbox.prove()
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
    monkeypatch.setattr(ov, "_system", lambda: "win32")  # Windows' order and words, asked on any host (macOS P4B seam)
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
    monkeypatch.setattr(ov, "reference_path", lambda voice: real_reference(voice.voice_id))
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.UNCHECKED_MESSAGE)
    assert ov.install_would_help("omnivoice-male-1") is True, "an unchecked engine is offered: installing adopts it"
    sandbox.prove()
    assert ov.voice_availability("omnivoice-male-1") == (True, "ok")
    assert ov.install_would_help() is False
    assert ov.voice_availability("omnivoice-nobody")[0] is False


def test_on_a_mac_the_package_set_is_the_mac_s_own_and_only_apple_silicon_is_supported(monkeypatch):
    """macOS P4B: an Apple Silicon Mac reads the manifest's darwin_arm64 set -- the same upstream lock, 86 PyPI wheels,
    plain torch 2.8.0, no Windows-only packages -- while Windows keeps its 88 exactly as released. Rosetta (x86_64) and
    any other platform are not supported."""
    monkeypatch.setattr(ov, "_system", lambda: "win32")
    windows = {w.name: w for w in ov.wheels()}
    windows_digest = ov.packages_sha256()
    assert len(windows) == 88 and windows["torch"].version == "2.8.0+cu128" and "colorama" in windows
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    mac = {w.name: w for w in ov.wheels()}
    assert len(mac) == 86 and set(windows) - set(mac) == {"colorama", "tzdata"}
    assert mac["torch"].version == mac["torchaudio"].version == "2.8.0" and mac["omnivoice"].version == "0.2.1"
    assert all(w.url.startswith(ov.PYPI_HOSTS) for w in mac.values()), "never PyTorch's CUDA index on a Mac"
    assert ov.pinned_packages()["torch"] == "2.8.0" and ov.packages_sha256() != windows_digest
    assert ov.engine_installed_bytes() == ov.load_manifest()[ov.DARWIN_SET]["installed_bytes"]["environment"]
    monkeypatch.setattr(ov, "_machine", lambda: "arm64")
    assert ov.platform_supported() is True
    monkeypatch.setattr(ov, "_machine", lambda: "x86_64")
    assert ov.platform_supported() is False, "an Intel Mac or Rosetta cannot load the arm64 wheels"
    monkeypatch.setattr(ov, "_system", lambda: "linux")
    assert ov.platform_supported() is False and "Apple Silicon" in ov.platform_reason()


def test_the_manifest_refuses_a_mac_set_that_could_come_from_anywhere_but_pypi():
    import copy

    data = copy.deepcopy(ov.load_manifest())
    assert ov.manifest_problems(data) == []
    data[ov.DARWIN_SET]["wheels"][0]["url"] = "https://download-r2.pytorch.org/whl/cu128/x.whl"
    assert any("Mac package set" in p for p in ov.manifest_problems(data))
    data = copy.deepcopy(ov.load_manifest())
    data[ov.DARWIN_SET]["platform"] = "win_amd64"
    assert any("not for macOS arm64" in p for p in ov.manifest_problems(data))
    data = copy.deepcopy(ov.load_manifest())
    data[ov.DARWIN_SET]["packages"].append(["torch", "2.8.0"])
    assert any("pinned twice" in p or "exactly the pinned packages" in p for p in ov.manifest_problems(data))


def test_on_a_mac_availability_and_the_device_policy_say_why_without_a_fallback(sandbox, monkeypatch):
    """macOS P4B: the device comes from the accepted policy only (MPS float32 by default, the CPU float32 by choice),
    Windows' answer never changes, and a Mac's reasons name the Mac's hardware -- never NVIDIA."""
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    monkeypatch.setattr(ov, "platform_supported", lambda: True)
    monkeypatch.setattr(ov, "configured_mac_device", lambda: ("mps", "default"))
    assert ov.device_policy() == ov.DevicePolicy("mps", "float32", "default")
    assert ov.device_policy(choice="cpu") == ov.DevicePolicy("cpu", "float32", "caller")
    assert ov.device_policy(system="win32", choice="cpu") == ov.DevicePolicy("cuda", "float16", "windows")
    for refused in ("cuda", "mps-fp16", "float16", "auto"):
        with pytest.raises(ov.OmniVoiceUnavailable, match="runs only on mps or cpu"):
            ov.device_policy(choice=refused)
    monkeypatch.setattr(ov, "detect_gpu", lambda: None)
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.MAC_NO_GPU_MESSAGE)
    monkeypatch.setattr(ov, "detect_gpu", lambda: rt.GpuInfo("Apple M4 Pro", 24576))
    assert ov.voice_availability("omnivoice-male-1") == (False, ov.NOT_INSTALLED_MESSAGE)
    monkeypatch.setattr(ov, "configured_mac_device", lambda: ("tpu", "config.toml"))
    ok, reason = ov.voice_availability("omnivoice-male-1")
    assert ok is False and "runs only on mps or cpu" in reason
    assert "NVIDIA" not in ov.hardware_disclosure() and "Apple Silicon" in ov.disclosure()["hardware"]
    monkeypatch.setattr(ov, "_system", lambda: "win32")
    assert ov.hardware_disclosure() == ov.HARDWARE_DISCLOSURE and ov.no_gpu_message() == ov.NO_GPU_MESSAGE


def test_a_prompt_identity_binds_the_device_off_cuda_and_keeps_every_cuda_key_as_released():
    """macOS P4B: a Windows (CUDA) prompt keeps exactly its released key, so no cached Windows prompt is lost; the Mac's
    GPU and processor each file theirs under a key no other device can produce."""
    spec = ov.load_references()["omnivoice-male-2"]
    common = dict(model_revision="c" * 40, omnivoice_version="0.2.1", preprocess_prompt=True)
    released, released_fields = ov.prompt_identity(spec, dtype="float16", **common)
    assert ov.prompt_identity(spec, dtype="float16", device="cuda", **common) == (released, released_fields)
    assert "device" not in released_fields
    mps, mps_fields = ov.prompt_identity(spec, dtype="float32", device="mps", **common)
    cpu, cpu_fields = ov.prompt_identity(spec, dtype="float32", device="cpu", **common)
    assert mps_fields["device"] == "mps" and cpu_fields["device"] == "cpu"
    assert len({released, mps, cpu, ov.prompt_identity(spec, dtype="float32", **common)[0]}) == 4


@needs_fcntl
def test_the_model_guard_is_one_per_user_on_a_mac_and_never_stale(monkeypatch, tmp_path):
    """macOS P4B (D13): every copy of the app run by this user meets one flock in the user's own temporary folder, which
    a setup worker's TMPDIR does not move; it is taken at once or refused, freed on release, and the kernel frees it when
    its holder dies (it is a descriptor). A link planted in its place is never followed."""
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    monkeypatch.setattr(ov, "machine_lock_path", lambda: tmp_path / "ACT-locks" / "omnivoice.lock")
    first, second = ov.MachineGuard(), ov.MachineGuard()
    assert first.acquire() and first.held and first.scope == "user"
    assert second.acquire() is False and second.failure == "busy"
    assert "Another copy of this app" in second.refusal_message and "Windows" not in second.refusal_message
    first.release()
    assert not first.held and second.acquire()
    second.release()
    target = tmp_path / "elsewhere.txt"
    target.write_text("not a lock")
    (tmp_path / "ACT-locks" / "omnivoice.lock").unlink()
    os.symlink(target, tmp_path / "ACT-locks" / "omnivoice.lock")
    with pytest.raises(ov.OmniVoiceUnavailable, match="could not be opened"):
        ov.MachineGuard().acquire()
    assert target.read_text() == "not a lock"


def test_on_a_mac_the_configured_device_is_validated_and_reaches_the_policy(tmp_path, monkeypatch):
    """macOS P4B: ``[tts] omnivoice_device`` accepts exactly the policy's two Mac devices, defaults to MPS, and a wrong
    value falls back to the default with a diagnostic -- it never reaches the worker as some third device."""
    from shared import config as shared_config

    assert shared_config.OMNIVOICE_DEVICE_VALUES == ov.MAC_DEVICES
    assert shared_config.DEFAULT_OMNIVOICE_DEVICE == ov.MAC_DEFAULT_DEVICE == "mps"
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "launcher.py").write_text("", encoding="utf-8")

    def load(toml: str):
        path = root / "config.toml"
        path.write_text(toml, encoding="utf-8")
        return shared_config.load(config_path=path, settings_data={}, repo_root=root, home=tmp_path)

    assert load("").tts.omnivoice_device == "mps"
    # The committed config.toml's own instructions ("remove the '# ' in front of the two lines") give a valid choice.
    shipped = (Path(__file__).resolve().parents[2] / "config.toml").read_text(encoding="utf-8")
    assert load(shipped).tts.omnivoice_device == "mps"
    followed = load(shipped.replace('# [tts]\n# omnivoice_device = "cpu"\n', '[tts]\nomnivoice_device = "cpu"\n', 1))
    assert followed.tts.omnivoice_device == "cpu"
    assert not any(d.key.startswith("tts") or "unrecognised" in d.detail for d in followed.diagnostics)
    chosen = load('[tts]\nomnivoice_device = "CPU"\n')
    assert chosen.tts.omnivoice_device == "cpu" and chosen.diagnostics == ()
    for wrong in ('"cuda"', '"mps-fp16"', "1", "true"):
        bad = load(f"[tts]\nomnivoice_device = {wrong}\n")
        assert bad.tts.omnivoice_device == "mps"
        assert any(d.key == "tts.omnivoice_device" for d in bad.diagnostics)
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    monkeypatch.setattr(shared_config, "get_effective", lambda: chosen)
    device, source = ov.configured_mac_device()
    assert device == "cpu" and source == chosen.source_of(ov.DEVICE_SETTING)
    assert (ov.device_policy().device, ov.device_policy().dtype) == ("cpu", "float32")


def test_on_a_mac_the_installer_builds_from_the_app_s_own_python_and_no_other_inside_the_app(sandbox, monkeypatch):
    """macOS P4B: setup places the app's base CPython inside the app's folder. The installer must accept exactly that
    interpreter there -- the first real Mac install found it refused -- and still refuse anything else inside the
    folder (an environment's python). Windows' rule is as released.

    v0.8.2 Phase 4: that interpreter is uv's managed CPython (``files/runtime-data/uv/python/<key>/bin/python3.12``),
    or the legacy ``files/runtime-data/python/bin/python3.12`` while ``.venv`` still runs on it (one resolver)."""
    from tts import omnivoice_setup as osu

    root = ov.repo_root()
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    legacy = root / "files" / "runtime-data" / "python" / "bin" / "python3.12"
    venv_cfg = root / ".venv" / "pyvenv.cfg"
    venv_cfg.parent.mkdir(parents=True, exist_ok=True)
    venv_cfg.write_text(f"home = {legacy.parent}\n", encoding="utf-8")
    assert ov.app_owned_python() == legacy, "an environment from v0.8.1 keeps building engines on its own base"
    venv_cfg.unlink()
    owned = root / "files" / "runtime-data" / "uv" / "python" / "cpython-3.12.15-macos-aarch64-none" / "bin" / "python3.12"
    assert ov.app_owned_python() == owned
    other = root / ".venv" / "bin" / "python3.12"
    for path in (owned, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    asked = []

    def runner(cmd, *, env, cwd, on_line, cancel_check=None):
        asked.append(cmd[0])
        home = str(Path(cmd[0]).parent.parent)
        on_line(osu._BASE_PROBE_MARK + json.dumps({"version": [3, 12, 10], "implementation": "cpython",
                                                   "prefix": home, "base_prefix": home, "executable": cmd[0]}))
        return 0

    monkeypatch.setattr(osu.su, "installer_environment", lambda: {"PATH": "/usr/bin"})  # no real runtime folders
    monkeypatch.setattr(ov, "app_base_python", lambda: owned)
    assert osu.verified_base_python(runner=runner) == owned and asked == [str(owned)]
    monkeypatch.setattr(ov, "app_base_python", lambda: other)
    with pytest.raises(osu.OmniVoiceSetupError, match="inside this app's folder"):
        osu.verified_base_python(runner=runner)
    assert asked == [str(owned)], "a refused interpreter is never started"
    monkeypatch.setattr(ov, "_system", lambda: "win32")
    # v0.8.2 Phase 4: Windows asks the same resolver (it was the running interpreter's base, which is the same file
    # whenever the app runs from its own .venv).
    assert ov.app_owned_python() == root / "files" / "runtime-data" / "uv" / "python" / \
        "cpython-3.12.15-windows-x86_64-none" / "python.exe"


def test_the_worker_environment_never_carries_the_mps_fallback_switch(sandbox):
    env = ov.worker_environment({"PATH": "/usr/bin", "PYTORCH_ENABLE_MPS_FALLBACK": "1",
                                 "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.0", "PYTORCH_CUDA_ALLOC_CONF": "x"})
    assert "PYTORCH_ENABLE_MPS_FALLBACK" not in env and "PYTORCH_MPS_HIGH_WATERMARK_RATIO" not in env
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "x", "what CUDA reads on Windows is left exactly as it was"


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
