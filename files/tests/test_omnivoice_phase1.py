"""ACT v0.8.0 Phase 1: the OmniVoice qualification tools (``files/dev-tools/omnivoice_p1*.py``) and their pins.

Offline and model-free: synthetic WAVs, fake folders, the audit hook driven by ``sys.audit`` (no packet is ever sent).
The one real clone, ``test_real_clone_proof``, runs only with ``ACT_OMNIVOICE_P1_REAL=1`` on a computer where
``.venv-omnivoice`` and the pinned model are installed; it loads the multi-gigabyte model once.
"""

from __future__ import annotations

import array
import copy
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_TOOLS = REPO_ROOT / "files" / "dev-tools"


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DEV_TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


p1 = _load("omnivoice_p1")
worker = _load("omnivoice_p1_worker")
H64 = "a" * 64


def _write_wav(path: Path, seconds: float, *, rate: int = 24000, channels: int = 1, tone_db: float = None) -> bytes:
    frames = int(round(seconds * rate))
    samples = array.array("h")
    for i in range(frames * channels):
        if tone_db is None:
            samples.append(((i * 7919) % 65536) - 32768)  # every frame different: a crop error cannot hide
        else:
            amp = 32767 * 10 ** (tone_db / 20)
            samples.append(int(amp * math.sin(2 * math.pi * 440 * (i // channels) / rate)))
    data = samples.tobytes()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data)
    return data


def _frames(path: Path) -> tuple[wave._wave_params, bytes]:
    with wave.open(str(path), "rb") as source:
        return source.getparams(), source.readframes(source.getnframes())


# --------------------------------------------------------------------------- #
# The pins
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def manifest() -> dict:
    return p1.load_manifest()


def test_manifest_and_lock_agree_exactly(manifest):
    assert p1.manifest_problems(manifest, p1.LOCK_PATH.read_text(encoding="utf-8")) == []


def test_the_lock_pins_one_exact_hashed_wheel_per_package(manifest):
    pins = {name: (version, sha) for name, version, sha in p1.parse_lock(p1.LOCK_PATH.read_text(encoding="utf-8"))}
    assert len(pins) == len(manifest["wheels"]) == 88
    assert pins["omnivoice"][0] == "0.2.1"
    assert pins["transformers"][0] == "5.3.0"  # upstream's tested version; omnivoice needs >= 5.3.0
    assert pins["torch"][0] == "2.8.0+cu128" and pins["torchaudio"][0] == "2.8.0+cu128"


@pytest.mark.parametrize("line", [
    "torch>=2.4", "torch==2.8.0", "torch==2.8.0 --hash=sha256:abc", "omnivoice @ https://example.invalid/o.whl",
    "-e .", "--index-url https://pypi.org/simple", f"numpy==2.4.3 --hash=sha256:{H64} --hash=sha256:{H64}",
    f"numpy[extra]==2.4.3 --hash=sha256:{H64}", f"numpy==2.4.3; sys_platform=='win32' --hash=sha256:{H64}",
])
def test_the_lock_parser_refuses_anything_but_an_exact_hashed_pin(line):
    with pytest.raises(p1.Phase1Error):
        p1.parse_lock(line)


def test_the_lock_parser_refuses_a_package_pinned_twice():
    with pytest.raises(p1.Phase1Error, match="more than once"):
        p1.parse_lock(f"numpy==2.4.3 --hash=sha256:{H64}\nnumpy==2.4.2 --hash=sha256:{'b' * 64}")


@pytest.mark.parametrize("damage, expected", [
    (lambda m: m["wheels"][0].update(sha256="b" * 64), "the lock pins"),
    (lambda m: next(w for w in m["wheels"] if w["name"] == "torch").update(index="pypi"), "torch: not the PyTorch cu128"),
    (lambda m: m["wheels"][0].update(filename=m["wheels"][0]["filename"].replace("py3-none-any", "cp312-cp312-manylinux_x86_64")),
     "not a Windows x64"),
    (lambda m: m["model"]["files"].pop("audio_tokenizer/model.safetensors"), "misses files the load needs"),
    (lambda m: m["audio_tokenizer"]["same_bytes_as"]["files"]["model.safetensors"].update(sha256="c" * 64),
     "not the pinned Higgs tokenizer"),
    (lambda m: m["model"].update(revision="main"), "pinned commit"),
])
def test_manifest_problems_name_each_disagreement(manifest, damage, expected):
    damaged = copy.deepcopy(manifest)
    damage(damaged)
    problems = p1.manifest_problems(damaged, p1.LOCK_PATH.read_text(encoding="utf-8"))
    assert any(expected in problem for problem in problems), problems


def test_the_app_and_qwen3_locks_are_not_where_omnivoice_lives(manifest):
    """Why the sibling environment: each existing environment pins a transformers OmniVoice cannot use."""
    def pinned(text: str, name: str) -> str:
        line = next(l for l in text.splitlines() if l.lower().startswith(name + "=="))
        return line.split("==", 1)[1].split()[0]

    app = (REPO_ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8")
    qwen = (REPO_ROOT / "scripts" / "qwen3-requirements.txt").read_text(encoding="utf-8")
    assert "omnivoice" not in app.lower() and "omnivoice" not in qwen.lower()
    ours = {w["name"]: w["version"] for w in manifest["wheels"]}["transformers"]
    assert {pinned(app, "transformers"), pinned(qwen, "transformers")}.isdisjoint({ours})
    assert manifest["lock"]["path"] == "files/dev-tools/omnivoice_p1_requirements.txt"


def test_the_model_pins_cover_an_offline_load_including_the_audio_tokenizer(manifest):
    model = manifest["model"]
    assert len(model["revision"]) == 40 and model["repo"] == "k2-fsa/OmniVoice"
    assert {"audio_tokenizer/config.json", "audio_tokenizer/model.safetensors",
            "audio_tokenizer/preprocessor_config.json", "config.json", "model.safetensors",
            "tokenizer.json"} <= set(model["load_required"]) <= set(model["files"])
    assert sum(e["size"] for e in model["files"].values()) == 3_267_470_260
    assert all(e["lfs"] == ("git_blob_sha1" not in e) for e in model["files"].values())


# --------------------------------------------------------------------------- #
# Model completeness
# --------------------------------------------------------------------------- #
def _fake_model(tmp_path: Path) -> tuple[dict, "p1.Layout"]:
    layout = p1.Layout(tmp_path)
    contents = {"config.json": b"{}", "audio_tokenizer/model.safetensors": b"weights" * 10}
    manifest = {"model": {"repo": "k2-fsa/OmniVoice", "revision": "f" * 40, "files": {
        rel: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for rel, data in contents.items()}}}
    folder = layout.model_dir(manifest)
    for rel, data in contents.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    return manifest, layout


def test_a_complete_snapshot_is_ready(tmp_path):
    manifest, layout = _fake_model(tmp_path)
    assert p1.model_state(manifest, layout)["ready"] is True


@pytest.mark.parametrize("harm, state", [
    (lambda f: (f / "config.json").unlink(), p1.MISSING),
    (lambda f: (f / "config.json").write_bytes(b"[]"), p1.DAMAGED),          # same size, other bytes
    (lambda f: (f / "config.json").write_bytes(b"{ }"), p1.DAMAGED),         # other size
])
def test_a_missing_or_wrong_file_makes_the_snapshot_not_ready(tmp_path, harm, state):
    manifest, layout = _fake_model(tmp_path)
    harm(layout.model_dir(manifest))
    result = p1.model_state(manifest, layout)
    assert result["ready"] is False and result["files"]["config.json"][0] == state


def test_no_audio_tokenizer_folder_is_not_ready(tmp_path):
    manifest, layout = _fake_model(tmp_path)
    folder = layout.model_dir(manifest) / "audio_tokenizer"
    (folder / "model.safetensors").unlink()
    folder.rmdir()
    result = p1.model_state(manifest, layout)
    assert result["ready"] is False and result["audio_tokenizer_folder"] is False


# --------------------------------------------------------------------------- #
# The excerpt
# --------------------------------------------------------------------------- #
def test_the_excerpt_is_exactly_the_first_ten_seconds_of_frames(tmp_path):
    data = _write_wav(tmp_path / "src.wav", 15.0)
    identity = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "out" / "excerpt.wav")
    params, frames = _frames(tmp_path / "out" / "excerpt.wav")
    assert (params.nchannels, params.sampwidth, params.framerate, params.nframes) == (1, 2, 24000, 240000)
    assert frames == data[:480000]
    assert identity["crop_end_frame"] == 240000 and identity["excerpt_duration_s"] == 10.0
    assert identity["excerpt_pcm_sha256"] == hashlib.sha256(data[:480000]).hexdigest()
    assert identity["crop_rule"] == "first-10s" and identity["short_source_defect"] is False


def test_the_crop_counts_frames_not_bytes(tmp_path):
    data = _write_wav(tmp_path / "src.wav", 12.0, rate=44100, channels=2)
    identity = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "excerpt.wav")
    params, frames = _frames(tmp_path / "excerpt.wav")
    assert params.nframes == identity["crop_end_frame"] == 441000
    assert frames == data[:441000 * 2 * 2]


def test_the_excerpt_is_deterministic(tmp_path):
    _write_wav(tmp_path / "src.wav", 15.0)
    first = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "a.wav")
    second = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "b.wav")
    assert first["excerpt_wav_sha256"] == second["excerpt_wav_sha256"]
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()


def test_the_original_is_never_modified_or_overwritten(tmp_path):
    _write_wav(tmp_path / "src.wav", 15.0)
    before = ((tmp_path / "src.wav").read_bytes(), os.stat(tmp_path / "src.wav").st_mtime_ns)
    with pytest.raises(p1.Phase1Error, match="never be written over"):
        p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "src.wav")
    (tmp_path / "taken.wav").write_bytes(b"somebody else's file")
    with pytest.raises(p1.Phase1Error, match="already exists"):
        p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "taken.wav")
    p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "new.wav")
    assert (tmp_path / "taken.wav").read_bytes() == b"somebody else's file"
    assert ((tmp_path / "src.wav").read_bytes(), os.stat(tmp_path / "src.wav").st_mtime_ns) == before


def test_a_source_shorter_than_ten_seconds_is_a_defect(tmp_path):
    _write_wav(tmp_path / "src.wav", 8.0)
    with pytest.raises(p1.Phase1Error, match="shorter than"):
        p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "a.wav")
    identity = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "b.wav", allow_short=True)
    assert identity["short_source_defect"] is True and identity["crop_end_frame"] == 192000


@pytest.mark.parametrize("end_frame", [0, -1, 240001, 360000, 9.615])
def test_a_shorter_crop_never_reaches_past_ten_seconds(tmp_path, end_frame):
    _write_wav(tmp_path / "src.wav", 15.0)
    with pytest.raises(p1.Phase1Error, match="inside the first"):
        p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "a.wav", end_frame=end_frame)


def test_an_owner_accepted_shorter_crop_is_exact_and_labelled(tmp_path):
    data = _write_wav(tmp_path / "src.wav", 15.0)
    identity = p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "a.wav", end_frame=230760)
    assert _frames(tmp_path / "a.wav")[1] == data[:230760 * 2]
    assert identity["crop_rule"] == "owner-accepted-shorter-whole-word" and identity["excerpt_duration_s"] == 9.615
    assert p1.derive_excerpt(tmp_path / "src.wav", tmp_path / "b.wav", end_frame=240000)["crop_rule"] == "first-10s"


def test_the_proof_excerpt_comes_from_the_registered_recording_untouched(tmp_path, manifest):
    proof = manifest["proof"]
    reference = p1.canonical_reference(proof["reference_id"])
    assert reference["wav_sha256"] == proof["original_wav_sha256"]
    identity = p1.derive_excerpt(reference["path"], tmp_path / "e.wav", end_frame=proof["crop_end_frame"])
    assert identity["original_sha256"] == proof["original_wav_sha256"]
    assert p1.rt.sha256_file(reference["path"]) == proof["original_wav_sha256"]
    assert identity["crop_end_frame"] == proof["crop_end_frame"] <= 10 * identity["sample_rate"]


# --------------------------------------------------------------------------- #
# The excerpt transcript
# --------------------------------------------------------------------------- #
FULL = "It had already been several weeks since I'd gone to town. After we came home, Tanya smiled."


@pytest.mark.parametrize("excerpt", [
    "It had already been several weeks since I'd gone to town.",
    "It had already been several weeks since I'd gone to town",
    "It had already been several weeks since I'd gone to town. After we came home",
    "It had",
])
def test_an_excerpt_transcript_is_the_approved_opening_words(excerpt):
    p1.validate_excerpt_transcript(FULL, excerpt, p1.rt.transcript_sha256(excerpt))


@pytest.mark.parametrize("excerpt, why", [
    (FULL, "as long as the full-length"),
    (FULL + " Extra", "as long as the full-length"),
    ("It had already been many weeks", "word 5"),
    ("It had already been several weeks since I gone to town.", "word 8"),
    ("It had already been several weeks since I'd gone to the", "last word"),
    (" It had", "spaces"),
    ("", "blank"),
    ("It had\x07 already", "control"),
])
def test_an_excerpt_transcript_that_is_not_the_approved_words_is_refused(excerpt, why):
    with pytest.raises(p1.Phase1Error, match=why):
        p1.validate_excerpt_transcript(FULL, excerpt)


def test_an_excerpt_transcript_must_match_its_recorded_hash():
    with pytest.raises(p1.Phase1Error, match="SHA-256"):
        p1.validate_excerpt_transcript(FULL, "It had", "0" * 64)


def test_the_proof_transcript_is_male_1s_approved_opening_words(manifest):
    proof = manifest["proof"]
    full = p1.rt.load_bundle()[proof["reference_id"]]
    p1.validate_excerpt_transcript(full, proof["excerpt_transcript"], proof["excerpt_transcript_sha256"])
    assert proof["excerpt_transcript"] != full


def test_the_prompt_identity_changes_with_every_bound_input():
    excerpt = {"original_sha256": "1" * 64, "excerpt_wav_sha256": "2" * 64, "crop_start_frame": 0,
               "crop_end_frame": 230760, "sample_rate": 24000, "preprocessing_version": "v1"}
    model = {"repo": "k2-fsa/OmniVoice", "revision": "3" * 40}

    def key(excerpt=excerpt, transcript="4" * 64, model=model, version="0.2.1", pre=True):
        return p1.prompt_identity(excerpt=excerpt, transcript_sha256=transcript, model=model,
                                  omnivoice_version=version, preprocess_prompt=pre)[0]

    base = key()
    assert key() == base
    changed = [key(excerpt={**excerpt, field: value}) for field, value in (
        ("original_sha256", "9" * 64), ("excerpt_wav_sha256", "9" * 64), ("crop_end_frame", 240000),
        ("sample_rate", 48000), ("preprocessing_version", "v2"))]
    changed += [key(transcript="9" * 64), key(model={**model, "revision": "9" * 40}), key(version="0.2.2"),
                key(pre=False)]
    assert base not in changed and len(set(changed)) == len(changed)


# --------------------------------------------------------------------------- #
# The environment
# --------------------------------------------------------------------------- #
def test_the_child_environment_is_offline_contained_and_unsteered(tmp_path):
    foreign = tmp_path / "other-venv"
    (foreign / "Scripts").mkdir(parents=True)
    (foreign / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    plain = tmp_path / "plain-bin"
    plain.mkdir()
    base = {"PATH": os.pathsep.join([str(foreign / "Scripts"), str(plain)]), "PIP_INDEX_URL": "https://evil.invalid",
            "PYTHONPATH": "x", "HF_ENDPOINT": "https://evil.invalid", "HF_HUB_OFFLINE": "0", "HTTPS_PROXY": "http://p",
            "VIRTUAL_ENV": str(foreign), "TORCH_HOME": "C:\\elsewhere", "SYSTEMROOT": "C:\\Windows"}
    env = p1.child_environment(p1.Layout(tmp_path), tmp_path / "scratch", base=base)
    for name in ("PIP_INDEX_URL", "PYTHONPATH", "HF_ENDPOINT", "HTTPS_PROXY", "VIRTUAL_ENV"):
        assert name not in env, name
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    for name in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME", "TEMP", "TMP", "NUMBA_CACHE_DIR"):
        assert Path(env[name]).is_relative_to(tmp_path / "scratch"), name
    assert env["PATH"].split(os.pathsep) == [str(plain)] and env["SYSTEMROOT"] == "C:\\Windows"


def test_pip_installs_only_the_verified_local_wheels(tmp_path):
    command = p1.pip_install_command(tmp_path / "py.exe", tmp_path / "wheels", tmp_path / "lock.txt")
    assert command[0] == str(tmp_path / "py.exe")
    for flag in ("--no-index", "--require-hashes", "--no-deps", "--only-binary=:all:", "--no-cache-dir", "--isolated",
                 "--require-virtualenv"):
        assert flag in command
    assert command[command.index("--find-links") + 1] == str(tmp_path / "wheels")
    assert command[-2:] == ["-r", str(tmp_path / "lock.txt")]
    assert not any("index-url" in part for part in command)


def test_isolation_problems_name_a_reach_into_another_environment(tmp_path):
    layout = p1.Layout(tmp_path)
    good = {"prefix": str(layout.env_dir), "base_prefix": "C:\\Python312", "user_site_enabled": False,
            "path": ["C:\\Python312\\Lib", str(layout.env_dir / "Lib" / "site-packages")]}
    assert p1.isolation_problems(layout, good) == []
    bad = {**good, "path": good["path"] + [str(tmp_path / ".venv" / "Lib" / "site-packages"), "D:\\x\\site-packages"]}
    problems = p1.isolation_problems(layout, bad)
    assert any("another environment" in p for p in problems) and any("outside" in p for p in problems)
    assert p1.isolation_problems(layout, {**good, "prefix": "C:\\Python312", "user_site_enabled": True})


def test_an_unverified_environment_is_not_used(tmp_path):
    layout = p1.Layout(tmp_path)
    assert p1.environment_assessment(layout).state == p1.venv_layout.ABSENT
    (layout.env_dir / "Scripts").mkdir(parents=True)
    (layout.env_dir / "Scripts" / "python.exe").write_bytes(b"")
    (layout.env_dir / "pyvenv.cfg").write_text("home = C:\\x\ninclude-system-site-packages = true\n", encoding="utf-8")
    assessment = p1.environment_assessment(layout)
    assert not assessment.identity_ok and "not isolated" in assessment.reason


def test_create_env_never_replaces_an_existing_folder(tmp_path, manifest):
    layout = p1.Layout(tmp_path)
    layout.env_dir.mkdir()
    (layout.env_dir / "keep.txt").write_text("owner's", encoding="utf-8")
    with pytest.raises(p1.Phase1Error, match="never repaired, replaced or deleted"):
        p1.create_env(manifest, layout, out=lambda _: None)
    assert (layout.env_dir / "keep.txt").read_text(encoding="utf-8") == "owner's"


def test_create_env_refuses_without_every_verified_wheel(tmp_path, manifest):
    with pytest.raises(p1.Phase1Error, match="not every pinned wheel"):
        p1.create_env(manifest, p1.Layout(tmp_path), out=lambda _: None)
    assert not p1.Layout(tmp_path).env_dir.exists()


def test_the_base_python_is_never_an_environment_or_the_app_folder(tmp_path):
    assert "inside the app folder" in p1.base_problem(REPO_ROOT / ".venv" / "Scripts" / "python.exe", root=REPO_ROOT)
    app = tmp_path / "app"  # the scratch folder may itself sit inside the repository, so the app is another folder
    fake = tmp_path / "py" / "python.exe"
    fake.parent.mkdir()
    fake.write_bytes(b"")
    assert p1.base_problem(fake, root=app) == ""
    (tmp_path / "py" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    assert "virtual environment" in p1.base_problem(fake, root=app)
    assert "not there" in p1.base_problem(tmp_path / "missing.exe", root=app)
    portable = app / "files" / "runtime-data" / "python" / "python.exe"  # the app's own base Python is the one exception
    portable.parent.mkdir(parents=True)
    portable.write_bytes(b"")
    assert p1.base_problem(portable, root=app) == ""


def test_the_installed_set_is_compared_to_the_lock_exactly():
    pins = [("numpy", "2.4.3", H64), ("torch", "2.8.0+cu128", H64)]
    assert p1.lock_difference({"numpy": "2.4.3", "torch": "2.8.0+cu128", "pip": "25.0"}, pins) == []
    assert p1.lock_difference({"numpy": "2.4.2", "extra-pkg": "1"}, pins) == [
        "missing torch==2.8.0+cu128", "extra extra-pkg==1", "numpy is 2.4.2, not 2.4.3"]


# --------------------------------------------------------------------------- #
# The worker
# --------------------------------------------------------------------------- #
def _run_python(code: str, *, env: dict = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120,
                          env=env, cwd=str(DEV_TOOLS.parent))


_LOAD_WORKER = (f"import importlib.util, sys; spec = importlib.util.spec_from_file_location('w', {str(DEV_TOOLS / 'omnivoice_p1_worker.py')!r}); "
                "w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)\n")


def test_the_worker_imports_nothing_heavy():
    done = _run_python(_LOAD_WORKER + "import json; print(json.dumps(sorted(m for m in ('torch', 'numpy', 'omnivoice', "
                                      "'transformers', 'soundfile', 'socket', 'urllib.request') if m in sys.modules)))")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == []


def test_the_network_guard_refuses_remote_access_and_keeps_loopback():
    """Driven through ``sys.audit`` itself, so nothing is resolved or sent even if the guard were broken."""
    code = _LOAD_WORKER + """
import json, socket
log = []
w.install_network_guard(log)
results = {}
for name, event, args in [
        ("lookup", "socket.getaddrinfo", ("huggingface.co", 443, 0, 0, 0, 0)),
        ("connect", "socket.connect", (None, ("192.0.2.10", 443))),
        ("byname", "socket.gethostbyname", ("cdn-lfs.huggingface.co",)),
        ("urllib", "urllib.Request", ("https://huggingface.co/x", None, {}, "GET")),
        ("unknown", "socket.connect", (None, None)),
        ("loopback", "socket.connect", (None, ("127.0.0.1", 5))),
        ("loopback6", "socket.getaddrinfo", ("::1", 5, 0, 0, 0, 0))]:
    try:
        sys.audit(event, *args)
        results[name] = "allowed"
    except w.NetworkRefused:
        results[name] = "refused"
a, b = socket.socketpair()
a.sendall(b"x"); results["socketpair"] = b.recv(1).decode()
print(json.dumps({"results": results, "logged": len(log)}))
"""
    done = _run_python(code)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["results"] == {"lookup": "refused", "connect": "refused", "byname": "refused", "urllib": "refused",
                              "unknown": "refused", "loopback": "allowed", "loopback6": "allowed", "socketpair": "x"}
    assert out["logged"] == 5


def _good_job(tmp_path: Path) -> dict:
    model = tmp_path / "model"
    (model / "audio_tokenizer").mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "audio_tokenizer" / "config.json").write_text("{}", encoding="utf-8")
    _write_wav(tmp_path / "e.wav", 1.0)
    return {"mode": "clone", "model_dir": str(model), "excerpt_wav": str(tmp_path / "e.wav"), "excerpt_frames": 230760,
            "sample_rate": 24000, "ref_text": "words", "text": "narration", "language": "English",
            "generation": dict(p1.GENERATION), "dtype": "float16", "device": "cuda:0", "seed": 1,
            "output_wav": str(tmp_path / "o.wav"), "prompt_path": str(tmp_path / "p.pt"), "prompt_identity": {},
            "report": str(tmp_path / "r.json")}


OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HOME": "x"}


def test_a_well_formed_clone_job_passes_the_worker_checks(tmp_path):
    assert worker.job_problems(_good_job(tmp_path), OFFLINE) == []
    assert set(p1.GENERATION) == worker.GENERATION_KEYS


@pytest.mark.parametrize("harm, why", [
    (lambda j, e: e.pop("HF_HUB_OFFLINE"), "HF_HUB_OFFLINE"),
    (lambda j, e: e.pop("HF_HOME"), "HF_HOME"),
    (lambda j, e: (Path(j["model_dir"]) / "audio_tokenizer" / "config.json").unlink(), "audio_tokenizer"),
    (lambda j, e: j.update(ref_text="  "), "Whisper"),
    (lambda j, e: j.update(excerpt_frames=240001), "first 10 seconds"),
    (lambda j, e: j["generation"].update(speed=1.2), "OmniVoiceGenerationConfig"),
    (lambda j, e: j.update(device="cpu"), "GPU"),
    (lambda j, e: j.pop("seed"), "missing seed"),
])
def test_the_worker_refuses_a_job_that_could_reach_the_hub_or_whisper(tmp_path, harm, why):
    job, environ = _good_job(tmp_path), dict(OFFLINE)
    harm(job, environ)
    assert any(why in problem for problem in worker.job_problems(job, environ))


def test_a_refused_job_ends_with_one_failed_event_and_a_report(tmp_path):
    job = _good_job(tmp_path)
    (Path(job["model_dir"]) / "audio_tokenizer" / "config.json").unlink()
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")
    env = {**os.environ, **OFFLINE}
    done = subprocess.run([sys.executable, "-I", str(DEV_TOOLS / "omnivoice_p1_worker.py"), str(tmp_path / "job.json")],
                          capture_output=True, text=True, timeout=120, env=env)
    events = [json.loads(l[len("@@EVENT "):]) for l in done.stdout.splitlines() if l.startswith("@@EVENT ")]
    assert done.returncode == worker.EXIT_FAILED
    assert [e["event"] for e in events] == ["failed"]
    report = json.loads(Path(job["report"]).read_text(encoding="utf-8"))
    assert report["status"] == "failed" and "audio_tokenizer" in report["error"] and report["network_attempts"] == []


# --------------------------------------------------------------------------- #
# The output
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seconds, tone_db, audible", [(5.0, -12.0, True), (5.0, None, True), (1.0, -12.0, False)])
def test_audibility(tmp_path, seconds, tone_db, audible):
    _write_wav(tmp_path / "a.wav", seconds, tone_db=tone_db)
    assert (p1.audible_problems(p1.wav_facts(tmp_path / "a.wav")) == []) is audible


def test_silence_is_not_audible(tmp_path):
    with wave.open(str(tmp_path / "s.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        out.writeframes(b"\0\0" * 24000 * 5)
    problems = p1.audible_problems(p1.wav_facts(tmp_path / "s.wav"))
    assert any("quiet" in p for p in problems) and any("silence" in p for p in problems)


# --------------------------------------------------------------------------- #
# The one real clone (opt-in: loads the model once)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.environ.get("ACT_OMNIVOICE_P1_REAL") != "1",
                    reason="loads the multi-gigabyte model; set ACT_OMNIVOICE_P1_REAL=1 where it is installed")
def test_real_clone_proof(manifest):
    layout = p1.Layout(REPO_ROOT)
    evidence = layout.evidence_root / f"{time.strftime('%Y%m%d-%H%M%S')}-pytest-prove"
    report = p1.prove(manifest, layout, evidence, timeout_s=1800, out=lambda _: None)
    assert report["checks"] == {name: True for name in report["checks"]}, report["checks"]
    assert report["verdict"] == "PASS"
    assert report["excerpt"]["crop_end_frame"] == manifest["proof"]["crop_end_frame"]
    assert report["output"]["sample_rate"] == 24000 and report["output"]["duration_s"] > 3
