"""v0.6.7 CP6 — Qwen3 runtime facts: where things live, what is installed, and what a person is told when it is not.

Everything here runs offline against temporary directories. ``qwen3_runtime`` derives every location from
``repo_root()``, so redirecting that one function sandboxes the environment, the model folders, the install record
and the transcripts; the conftest isolation guard proves no test touched the developer's real ones.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tts import qwen3_runtime as rt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


TINY_FILES = {  # a two-file stand-in for each model; the tokenizer file is shared, exactly like the real pair
    "config.json": b'{"model": true}',
    "speech_tokenizer/model.safetensors": b"shared tokenizer weights",
}
CUSTOM_ONLY = {"model.safetensors": b"customvoice weights"}
BASE_ONLY = {"model.safetensors": b"base weights are longer"}


def _entry(files: dict[str, bytes], label: str, revision: str, voices: list[str]) -> dict:
    return {"label": label, "repo": f"Qwen/Qwen3-TTS-12Hz-1.7B-{label}", "revision": revision, "license": "apache-2.0",
            "voices": voices, "dir": f"{label}-{revision[:8]}",
            "files": {n: {"size": len(b), "sha256": _sha(b)} for n, b in files.items()}}


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A fake repository root with a tiny model manifest, so installs can be built from a few bytes."""
    monkeypatch.setattr(rt, "repo_root", lambda: tmp_path)
    (tmp_path / "scripts").mkdir()
    manifest = {
        "schema": 1,
        "models": {
            "customvoice": _entry({**TINY_FILES, **CUSTOM_ONLY}, "CustomVoice", "a" * 40, ["qwen3-aiden", "qwen3-ryan"]),
            "base": _entry({**TINY_FILES, **BASE_ONLY}, "Base", "b" * 40,
                           [v.voice_id for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE]),
        },
        "environment": {"approx_download_bytes": 3_100_000_000, "approx_installed_bytes": 5_300_000_000},
    }
    monkeypatch.setattr(rt, "load_manifest", lambda: manifest)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(rt, "gpu_probe", lambda: None)
    rt._GPU_CACHE.clear()
    return tmp_path


def install_model(root: Path, key: str, *, corrupt: str | None = None, marker: bool = True) -> Path:
    spec = rt.model_spec(key)
    files = {**TINY_FILES, **(CUSTOM_ONLY if key == "customvoice" else BASE_ONLY)}
    for name, data in files.items():
        path = spec.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if corrupt:
        (spec.directory / corrupt).write_bytes(b"x" * len(files[corrupt]))  # same size, wrong content
    if marker:
        rt.write_model_marker(key)
    return spec.directory


def install_environment(root: Path, *, requirements: str = "torch==1.0\n") -> None:
    # bytes, not write_text: on Windows write_text would silently turn these LFs into CRLFs
    (root / "scripts" / "qwen3-requirements.txt").write_bytes(requirements.encode("utf-8"))
    python = rt.venv_python()
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"")
    base = root / "base-python"
    base.mkdir(exist_ok=True)
    (rt.venv_dir() / "pyvenv.cfg").write_text(f"home = {base}\nversion = 3.12.10\n", encoding="utf-8")
    rt.write_environment_state({"torch": "2.10.0+cu128", "cuda_available": True})


def install_clone_fixture(root: Path, monkeypatch, voice_id: str = "qwen3-male-1") -> rt.Qwen3Voice:
    """A fake reference recording whose hash the (patched) voice was 'approved' against."""
    voice = rt.get_voice(voice_id)
    data = b"RIFF fake reference recording for " + voice_id.encode()
    patched = replace(voice, reference_sha256=_sha(data))
    monkeypatch.setitem(rt._VOICE_BY_ID, voice_id, patched)
    path = rt.reference_path(patched)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return patched


def write_transcripts(path: Path, voice: rt.Qwen3Voice, **overrides) -> None:
    entry = {"text": "synthetic fixture words", "approved": True, "wav_sha256": voice.reference_sha256,
             "approved_by": "unit test"}
    entry.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({voice.reference_name: entry}), encoding="utf-8")


# --------------------------------------------------------------------------- #
# The tracked manifest and the voice table
# --------------------------------------------------------------------------- #
def test_the_tracked_manifest_pins_two_models_by_immutable_revision_and_hash():
    manifest = json.loads((REPO_ROOT / "scripts" / "tts" / "qwen3_models.json").read_text("utf-8"))
    assert set(manifest["models"]) == {"customvoice", "base"}
    for key, model in manifest["models"].items():
        assert re.fullmatch(r"[0-9a-f]{40}", model["revision"]), key  # a commit SHA, never a branch name
        assert model["license"] == "apache-2.0"
        assert model["dir"].endswith(model["revision"][:8])
        assert len(model["files"]) == 11 and "model.safetensors" in model["files"]
        assert "README.md" not in model["files"]  # only what loading needs
        for name, info in model["files"].items():
            assert re.fullmatch(r"[0-9a-f]{64}", info["sha256"]) and info["size"] > 0, name
        assert model["total_bytes"] == sum(f["size"] for f in model["files"].values())
    assert manifest["models"]["customvoice"]["revision"] != manifest["models"]["base"]["revision"]


def test_real_manifest_sizes_match_what_the_owner_is_told():
    assert rt.format_bytes(rt.model_spec("customvoice").total_bytes) == "4.5 GB"
    assert rt.format_bytes(rt.model_spec("base").total_bytes) == "4.5 GB"
    # the speech tokenizer and tokenizer files are byte-identical in both models, so "Install Both" downloads them once
    assert rt.shared_file_bytes() == 686_752_126
    both = rt.model_spec("customvoice").total_bytes + rt.model_spec("base").total_bytes - rt.shared_file_bytes()
    assert rt.format_bytes(both) == "8.4 GB"
    assert rt.format_bytes(rt.environment_download_bytes()) == "3.1 GB"


def test_exactly_eight_voices_with_the_owners_labels_and_model_split():
    assert [v.label for v in rt.QWEN3_VOICES] == [
        "Qwen3 - Aiden", "Qwen3 - Ryan", "Qwen3 - Female 1", "Qwen3 - Female 2",
        "Qwen3 - Male 1", "Qwen3 - Male 2", "Qwen3 - Male 3", "Qwen3 - Male 4"]
    assert [v.voice_id for v in rt.QWEN3_VOICES if v.model_key == rt.MODEL_CUSTOMVOICE] == ["qwen3-aiden", "qwen3-ryan"]
    assert {v.kind for v in rt.QWEN3_VOICES if v.model_key == rt.MODEL_BASE} == {rt.KIND_CLONE}
    assert len({v.voice_id for v in rt.QWEN3_VOICES}) == 8
    manifest_voices = {m: set(rt.model_spec(m).voices) for m in rt.MODEL_KEYS}
    assert manifest_voices["customvoice"] | manifest_voices["base"] == {v.voice_id for v in rt.QWEN3_VOICES}


def test_clone_reference_hashes_agree_with_the_chatterbox_registry_without_importing_it():
    from tts import chatterbox_synth as cs

    for voice in rt.QWEN3_VOICES:
        if voice.kind != rt.KIND_CLONE:
            continue
        twin = cs.REFERENCE_VOICES["chatterbox-" + voice.voice_id.removeprefix("qwen3-")]
        # one bundled copy, named after the Chatterbox label, bound to the same hash
        assert (rt.reference_path(voice).name, voice.reference_sha256) == (twin.source_name, twin.source_sha256)
    source = (REPO_ROOT / "scripts" / "tts" / "qwen3_runtime.py").read_text("utf-8")
    assert "chatterbox_synth" not in source.replace("``chatterbox_synth.REFERENCE_VOICES``", "")  # independent


def test_unknown_voice_is_refused_with_a_message():
    with pytest.raises(rt.Qwen3Unavailable, match="Unknown Qwen3 voice"):
        rt.get_voice("qwen3-dylan")


# --------------------------------------------------------------------------- #
# Environment status
# --------------------------------------------------------------------------- #
def test_environment_missing_says_how_to_install_and_that_nothing_downloads_unasked(sandbox):
    ok, reason = rt.environment_status()
    assert not ok and "not installed" in reason and "3.1 GB" in reason and "nothing is downloaded until you ask" in reason


def test_environment_ready_only_with_interpreter_a_live_base_python_a_probe_and_matching_requirements(sandbox):
    install_environment(sandbox)
    assert rt.environment_status() == (True, "ok")

    (sandbox / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==2.0\n")  # pins moved on
    ok, reason = rt.environment_status()
    assert not ok and "out of date" in reason

    (sandbox / "scripts" / "qwen3-requirements.txt").write_bytes(b"torch==1.0\r\n")  # same pins, CRLF endings
    assert rt.environment_status() == (True, "ok")  # line endings must not look like a version change

    rt.clear_environment_state()
    ok, reason = rt.environment_status()
    assert not ok and "not installed completely" in reason

    install_environment(sandbox)
    (sandbox / "base-python").rmdir()
    ok, reason = rt.environment_status()
    assert not ok and "broken" in reason and "rebuild" in reason


# --------------------------------------------------------------------------- #
# Model status
# --------------------------------------------------------------------------- #
def test_model_states_are_distinct_sentences_with_one_next_step(sandbox):
    ok, reason = rt.model_status("customvoice")
    assert not ok and "is not installed" in reason
    assert f"({rt.format_bytes(rt.model_spec('customvoice').total_bytes)})" in reason  # the size is stated up front
    assert "Install / repair Qwen3 voices" in reason and "nothing is downloaded until you ask" in reason

    directory = install_model(sandbox, "customvoice", marker=False)
    ok, reason = rt.model_status("customvoice")
    assert not ok and "only partly installed" in reason

    rt.write_model_marker("customvoice")
    assert rt.model_status("customvoice") == (True, "ok")

    (directory / "model.safetensors").write_bytes(b"short")
    ok, reason = rt.model_status("customvoice")
    assert not ok and "damaged" in reason and "model.safetensors has the wrong size" in reason

    (directory / "model.safetensors").unlink()
    ok, reason = rt.model_status("customvoice")
    assert not ok and "model.safetensors is missing" in reason


def test_a_model_from_a_different_manifest_is_reported_as_the_wrong_version(sandbox, monkeypatch):
    install_model(sandbox, "customvoice")
    manifest = rt.load_manifest()
    other = json.loads(json.dumps(manifest))
    other["models"]["customvoice"]["files"]["config.json"]["sha256"] = "0" * 64  # an updated pin
    monkeypatch.setattr(rt, "load_manifest", lambda: other)
    ok, reason = rt.model_status("customvoice")
    assert not ok and "different version" in reason


def test_full_verification_catches_same_size_corruption_that_the_cheap_check_cannot(sandbox):
    install_model(sandbox, "base", corrupt="model.safetensors")
    assert rt.model_status("base") == (True, "ok")  # the cheap check is size-only by design
    problems = rt.model_file_problems("base", full=True)
    assert problems == ["model.safetensors does not match its expected SHA-256"]


def test_the_cheap_status_never_hashes(sandbox, monkeypatch):
    install_model(sandbox, "customvoice")
    monkeypatch.setattr(rt, "sha256_file", lambda *a, **k: pytest.fail("status must not hash model files"))
    assert rt.model_status("customvoice") == (True, "ok")


def test_the_two_models_install_independently(sandbox):
    install_model(sandbox, "customvoice")
    assert rt.model_status("customvoice")[0] is True
    assert rt.model_status("base")[0] is False
    install_model(sandbox, "base")
    assert rt.model_status("base")[0] is True and rt.model_status("customvoice")[0] is True


# --------------------------------------------------------------------------- #
# Platform, hardware
# --------------------------------------------------------------------------- #
def test_non_windows_platforms_are_not_yet_available_whatever_is_installed(sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "customvoice")
    assert rt.voice_availability("qwen3-aiden") == (True, "ok")
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        ok, reason = rt.voice_availability("qwen3-aiden")
        assert not ok and "not yet available" in reason and "Windows" in reason
        assert "install" not in reason.lower()  # a Mac is told "not yet", never "install it"


def test_hardware_summary_is_explicit_about_gpu_cpu_and_the_single_tested_machine(sandbox, monkeypatch):
    assert "No NVIDIA GPU" in rt.hardware_summary() and "Ryzen 7 9800X3D" in rt.hardware_summary()
    assert "much slower" in rt.hardware_summary()
    rt._GPU_CACHE.clear()
    monkeypatch.setattr(rt, "gpu_probe", lambda: rt.GpuInfo("NVIDIA GeForce RTX 5070", 12227))
    text = rt.hardware_summary()
    assert "RTX 5070, 12 GB" in text and "Speed depends on the computer" in text and "1.4 to 1.9" in text
    assert "guarantee" not in text.lower()


def test_gpu_detection_asks_the_driver_once_and_treats_a_failure_as_no_gpu(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(rt, "gpu_probe", lambda: calls.append(1) or rt.GpuInfo("X", 1024))
    rt._GPU_CACHE.clear()
    assert rt.detect_gpu() == rt.detect_gpu() == rt.GpuInfo("X", 1024) and len(calls) == 1

    class Boom:
        returncode = 9
        stdout = ""

    monkeypatch.setattr("shared.subprocess_utils.run", lambda *a, **k: Boom())
    assert rt._query_nvidia_smi() is None

    def missing(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr("shared.subprocess_utils.run", missing)
    assert rt._query_nvidia_smi() is None


def test_nvidia_smi_output_is_parsed(monkeypatch):
    class Ok:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 5070, 12227\n"

    monkeypatch.setattr("shared.subprocess_utils.run", lambda *a, **k: Ok())
    assert rt._query_nvidia_smi() == rt.GpuInfo("NVIDIA GeForce RTX 5070", 12227)


# --------------------------------------------------------------------------- #
# Reference recording and the transcript interface (Q5)
# --------------------------------------------------------------------------- #
def test_a_missing_or_changed_reference_blocks_a_clone_with_its_own_message(sandbox, monkeypatch):
    voice = rt.get_voice("qwen3-male-1")
    ok, reason = rt.reference_status(voice)
    assert not ok and "not present" in reason and "every other voice is unaffected" in reason

    voice = install_clone_fixture(sandbox, monkeypatch)
    assert rt.reference_status(voice) == (True, "ok")
    rt.reference_path(voice).write_bytes(b"a different recording")
    ok, reason = rt.reference_status(voice)
    assert not ok and "does not match" in reason


def test_transcript_is_accepted_only_when_approved_literally_and_bound_to_the_recording(sandbox, monkeypatch):
    voice = install_clone_fixture(sandbox, monkeypatch)
    path = rt.local_transcripts_path()

    assert not rt.load_transcript(voice.voice_id).ok  # no file at all
    assert "no approved reference transcript" in rt.load_transcript(voice.voice_id).reason

    write_transcripts(path, voice)
    ok = rt.load_transcript(voice.voice_id)
    assert ok.ok and ok.text == "synthetic fixture words" and ok.source == path

    for bad, why in [({"approved": False}, "not been approved"),
                     ({"approved": "yes"}, "not been approved"),      # truthy is not enough: the literal true
                     ({"approved": 1}, "not been approved"),
                     ({"wav_sha256": "0" * 64}, "not bound to the current reference"),
                     ({"wav_sha256": None}, "not bound to the current reference"),
                     ({"text": "   "}, "empty"),
                     ({"text": None}, "empty"),
                     ({"text": "x" * (rt.MAX_TRANSCRIPT_CHARS + 1)}, "implausibly long")]:
        write_transcripts(path, voice, **bad)
        result = rt.load_transcript(voice.voice_id)
        assert not result.ok and why in result.reason, (bad, result)

    path.write_text("{not json", encoding="utf-8")
    assert "could not be read" in rt.load_transcript(voice.voice_id).reason
    path.write_text(json.dumps({"Female-2": {}}), encoding="utf-8")
    assert "no entry for Male-1" in rt.load_transcript(voice.voice_id).reason
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert not rt.load_transcript(voice.voice_id).ok


def test_the_environment_override_wins_and_a_preset_never_needs_a_transcript(sandbox, monkeypatch, tmp_path):
    voice = install_clone_fixture(sandbox, monkeypatch)
    write_transcripts(rt.local_transcripts_path(), voice, text="from the local file")
    override = tmp_path / "elsewhere" / "dev-transcripts.json"
    write_transcripts(override, voice, text="from the override")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(override))
    assert rt.load_transcript(voice.voice_id).text == "from the override"
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(tmp_path / "does-not-exist.json"))
    assert rt.load_transcript(voice.voice_id).text == "from the local file"  # a missing override falls through
    assert rt.load_transcript("qwen3-aiden") == rt.Transcript(True, "", "not needed")


def test_no_transcript_text_is_tracked_in_the_repository():
    """Q5: the six verified transcripts are not cleared for public redistribution, so none may be committed."""
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    offenders = [line for line in tracked.splitlines()
                 if re.search(r"transcript", line, re.IGNORECASE) and line.startswith(("scripts/", "files/runtime-data"))]
    assert offenders == []
    ignored = subprocess.run(["git", "check-ignore", "files/runtime-data/qwen3/transcripts.json"], cwd=REPO_ROOT,
                             capture_output=True, text=True)
    assert ignored.returncode == 0  # the default local location can never be staged by accident


# --------------------------------------------------------------------------- #
# The one question callers ask
# --------------------------------------------------------------------------- #
def test_voice_availability_walks_engine_then_model_then_reference_then_transcript(sandbox, monkeypatch):
    ok, reason = rt.voice_availability("qwen3-male-1")
    assert not ok and "voice engine is not installed" in reason

    install_environment(sandbox)
    ok, reason = rt.voice_availability("qwen3-male-1")
    assert not ok and "Base model" in reason and "not installed" in reason
    assert rt.voice_availability("qwen3-aiden")[1].startswith("The Qwen3 CustomVoice model")

    install_model(sandbox, "base")
    ok, reason = rt.voice_availability("qwen3-male-1")
    assert not ok and "reference recording" in reason

    install_clone_fixture(sandbox, monkeypatch)
    ok, reason = rt.voice_availability("qwen3-male-1")
    assert not ok and "approved reference transcript" in reason and "Setup required for Qwen3 - Male 1" in reason
    assert "Edge, Kokoro and Chatterbox are unaffected" in reason

    write_transcripts(rt.local_transcripts_path(), rt.get_voice("qwen3-male-1"))
    assert rt.voice_availability("qwen3-male-1") == (True, "ok")

    install_model(sandbox, "customvoice")
    assert rt.voice_availability("qwen3-aiden") == (True, "ok")  # presets need no reference and no transcript


def test_voice_availability_never_raises(sandbox, monkeypatch):
    install_environment(sandbox)
    install_model(sandbox, "base")
    monkeypatch.setattr(rt, "reference_status", lambda voice: (_ for _ in ()).throw(OSError("disk on fire")))
    ok, reason = rt.voice_availability("qwen3-male-2")
    assert not ok and "could not be checked" in reason and "disk on fire" in reason
    assert rt.voice_availability("not-a-voice")[0] is False


# --------------------------------------------------------------------------- #
# Worker environment
# --------------------------------------------------------------------------- #
def test_worker_environment_is_isolated_offline_and_inside_the_repository(sandbox):
    base = {"PATH": "p", "PYTHONPATH": "evil", "PYTHONHOME": "evil", "VIRTUAL_ENV": "root", "KEEP": "1"}
    env = rt.worker_environment(base)
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env and "VIRTUAL_ENV" not in env
    assert env["KEEP"] == "1" and env["PATH"] == "p"
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1" and env["PYTHONNOUSERSITE"] == "1"
    for name in ("HF_HOME", "TORCH_HOME", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
        assert Path(env[name]).is_relative_to(sandbox), name  # nothing lands in the user's profile


def test_atomic_json_write_leaves_no_temp_file(tmp_path):
    target = tmp_path / "a" / "state.json"
    rt.atomic_write_json(target, {"b": 1})
    assert json.loads(target.read_text("utf-8")) == {"b": 1}
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


def test_requirements_file_is_exactly_pinned_and_covers_the_stack():
    lines = [l.strip() for l in (REPO_ROOT / "scripts" / "qwen3-requirements.txt").read_text("utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert len(lines) == 89
    # every line pins one exact artifact: name==version plus the SHA-256 of that wheel (pip runs with --require-hashes)
    assert all(re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.+\-]+ --hash=sha256:[0-9a-f]{64}", l) for l in lines), \
        [l for l in lines if "--hash=sha256:" not in l]
    hashes = [l.rsplit("sha256:", 1)[1] for l in lines]
    assert len(set(hashes)) == len(hashes)  # no two pins share an artifact
    pins = dict(l.split(" ")[0].split("==") for l in lines)
    assert pins["qwen-tts"] == "0.1.1" and pins["transformers"] == "4.57.3" and pins["torch"] == "2.10.0+cu128"
    root = (REPO_ROOT / "scripts" / "requirements.txt").read_text("utf-8")
    assert "transformers==5.2.0" in root and "qwen-tts" not in root  # the reason the second environment exists


def test_no_hardware_claim_is_made_where_the_voices_are_not_yet_available(sandbox, monkeypatch):
    """Codex finding: macOS showed 'Qwen3 will run on the CPU' beside 'not yet available'."""
    assert "No NVIDIA GPU" in rt.hardware_summary()
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        assert rt.hardware_summary() == ""
        assert not rt.voice_availability("qwen3-aiden")[0]


# --------------------------------------------------------------------------- #
# Hostile manifests, links, environment location, locks (Codex S3 findings)
# --------------------------------------------------------------------------- #
import os  # noqa: E402


def with_manifest(monkeypatch, mutate, base=None):
    manifest = json.loads(json.dumps(base if base is not None else rt.load_manifest()))
    mutate(manifest)
    monkeypatch.setattr(rt, "load_manifest", lambda: manifest)


@pytest.mark.parametrize("bad", [
    "../outside.txt", "a/../../outside.txt", "/etc/passwd", "C:/Windows/x", "C:x", "a\\b", "a/./b", "a//b", "",
    "con", "nul.txt", "aux/x", "trailing.", "trailing ", "sp ace.txt", ".hidden", "-dash", "x" * 300, "a/b/",
    "name\x00null",
])
def test_a_hostile_file_name_in_the_manifest_is_refused_before_anything_is_touched(sandbox, monkeypatch, bad):
    def add(manifest):
        manifest["models"]["customvoice"]["files"][bad] = {"size": 1, "sha256": "0" * 64}

    with_manifest(monkeypatch, add)
    with pytest.raises(rt.Qwen3Unavailable, match="model list is invalid"):
        rt.model_spec("customvoice")
    assert rt.voice_availability("qwen3-aiden")[0] is False  # status answers, it does not raise


def test_names_that_differ_only_by_case_or_a_bad_folder_or_revision_or_hash_are_refused_too(sandbox, monkeypatch):
    def twice(manifest):
        manifest["models"]["customvoice"]["files"]["Config.json"] = {"size": 1, "sha256": "0" * 64}
        manifest["models"]["customvoice"]["files"]["config.json"] = {"size": 1, "sha256": "0" * 64}

    original = json.loads(json.dumps(rt.load_manifest()))
    with_manifest(monkeypatch, twice, original)
    with pytest.raises(rt.Qwen3Unavailable, match="differ only by case"):
        rt.model_spec("customvoice")

    for field, value, message in [("dir", "../escape", "model folder"), ("dir", "a/b", "one folder name"),
                                  ("revision", "main", "commit hash")]:
        with_manifest(monkeypatch, lambda m, f=field, v=value: m["models"]["base"].__setitem__(f, v), original)
        with pytest.raises(rt.Qwen3Unavailable, match=message):
            rt.model_spec("base")

    with_manifest(monkeypatch, lambda m: m["models"]["base"]["files"]["config.json"].update(sha256="xyz"), original)
    with pytest.raises(rt.Qwen3Unavailable, match="no valid size and SHA-256"):
        rt.model_spec("base")


def test_every_name_in_the_real_manifest_passes_the_same_validation():
    for key in rt.MODEL_KEYS:
        spec = rt.model_spec(key)
        for name in spec.files:
            assert rt.check_relative_name(name) == name


def make_junction(link: Path, target: Path) -> None:
    import subprocess

    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"cannot create a junction here: {result.stdout} {result.stderr}")


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")


@windows_only
def test_a_junction_inside_a_model_folder_is_refused_and_nothing_is_written_through_it(sandbox, tmp_path):
    spec = rt.model_spec("customvoice")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.safetensors").write_bytes(b"somebody else's file")
    spec.directory.mkdir(parents=True)
    make_junction(spec.directory / "speech_tokenizer", outside)
    with pytest.raises(rt.Qwen3Unavailable, match="contains a link"):
        rt.safe_model_path(spec, "speech_tokenizer/model.safetensors")
    assert rt.model_status("customvoice")[0] is False
    assert (outside / "model.safetensors").read_bytes() == b"somebody else's file"


@windows_only
def test_the_models_root_itself_may_be_a_link_so_the_models_can_live_on_another_drive(sandbox, tmp_path):
    elsewhere = tmp_path / "bigger-drive"
    elsewhere.mkdir()
    rt.models_root().parent.mkdir(parents=True)
    make_junction(rt.models_root(), elsewhere)
    install_model(sandbox, "customvoice")
    assert rt.model_status("customvoice") == (True, "ok")
    assert (elsewhere / rt.model_spec("customvoice").dir_name / "config.json").is_file()


def test_a_path_that_resolves_outside_its_folder_is_refused(sandbox, monkeypatch, tmp_path):
    spec = rt.model_spec("customvoice")
    spec.directory.mkdir(parents=True)
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda p: str(tmp_path / "elsewhere") if "config.json" in str(p) else real(p))
    with pytest.raises(rt.Qwen3Unavailable, match="resolves outside its model folder"):
        rt.safe_model_path(spec, "config.json")


@windows_only
def test_an_environment_folder_that_is_a_link_is_never_used_or_modified(sandbox, tmp_path):
    other = tmp_path / "somebody-elses-venv"
    (other / "Scripts").mkdir(parents=True)
    (other / "Scripts" / "python.exe").write_bytes(b"")
    (other / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    make_junction(rt.venv_dir(), other)
    assert "link" in rt.environment_location_problem()
    ok, reason = rt.environment_status()
    assert not ok and "is a link to another folder" in reason
    ok, reason = rt.voice_availability("qwen3-aiden")
    assert not ok and "link" in reason


def test_a_missing_environment_folder_has_no_location_problem(sandbox):
    assert rt.environment_location_problem() == ""


def test_a_real_environment_folder_inside_the_repository_is_fine(sandbox):
    install_environment(sandbox)
    assert rt.environment_location_problem() == ""


def test_an_environment_that_resolves_outside_the_repository_is_refused(sandbox, monkeypatch, tmp_path):
    install_environment(sandbox)
    real = os.path.realpath
    elsewhere = tmp_path.parent / "elsewhere"  # (the sandbox repository IS tmp_path, so this is genuinely outside it)
    monkeypatch.setattr(os.path, "realpath", lambda p: str(elsewhere) if str(p).endswith(".venv-qwen3") else real(p))
    assert "outside this app's folder" in rt.environment_location_problem()


# ---- the operating-system lock -------------------------------------------------------------------------------------
HOLDER = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tts import qwen3_runtime as rt
lock = rt.FileLock(Path(sys.argv[2]))
assert lock.acquire()
print("held", flush=True)
time.sleep(120)
"""


def hold_in_another_process(path: Path):
    """Another process holding the lock. Started through the job-object spawner, so killing it kills the whole tree
    (a Windows venv python is a launcher with a child, and the CHILD is what holds the lock)."""
    from tts import qwen3_process as qp

    import subprocess

    proc = qp.spawn([sys.executable, "-c", HOLDER, str(Path(rt.__file__).resolve().parents[1]), str(path)],
                    stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def stop_holder(proc, path: Path | None = None) -> None:
    """Kill the holder's whole tree. With ``path``, also wait (bounded) until the operating system has freed its lock:
    the kernel closes a dead process's handles a moment after the tree is torn down, so a check made in the same
    instant can race it. The tests' own assertions still decide whether the lock really became free."""
    import time

    from tts import qwen3_process as qp

    qp.kill_tree(proc)
    qp.release(proc)
    if path is not None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            probe = rt.FileLock(path)
            if probe.acquire():
                probe.release()
                return
            time.sleep(0.05)


def test_the_file_lock_excludes_every_other_holder_and_frees_on_release(tmp_path):
    a, b = rt.FileLock(tmp_path / "x.lock"), rt.FileLock(tmp_path / "x.lock")
    assert a.acquire() and a.held and a.acquire()  # re-acquiring your own is a no-op
    assert b.acquire() is False and not b.held
    a.release()
    a.release()  # idempotent
    assert b.acquire() is True
    b.release()


def test_a_lock_held_by_another_process_blocks_us_and_dies_with_that_process(tmp_path):
    path = tmp_path / "other.lock"
    holder = hold_in_another_process(path)
    try:
        assert rt.FileLock(path).acquire() is False
    finally:
        stop_holder(holder, path)
    mine = rt.FileLock(path)
    assert mine.acquire() is True, "the operating system freed the lock when the holder died: nothing is ever stale"
    mine.release()


def test_the_inference_lease_is_exclusive_and_released_even_when_the_work_fails(sandbox):
    with rt.inference_lease():
        with pytest.raises(rt.Qwen3Unavailable, match="being installed or repaired, or another conversion"):
            rt.inference_lease().__enter__()
    with pytest.raises(RuntimeError):
        with rt.inference_lease():
            raise RuntimeError("the conversion failed")
    with rt.inference_lease():  # free again
        pass
