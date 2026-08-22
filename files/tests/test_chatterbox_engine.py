"""v0.6.1 Plan 4 Phase 8 — the Chatterbox engine module.

Phase 8 builds the machinery only. Nothing here loads real weights, reads a real
maintainer recording, or reaches the network: the model is stubbed at the seams
the module exposes, and every audio fixture is generated into ``tmp_path``.

The safety rules under test come from the drop's §4.3: the four raw MP3s are
read-only inputs verified by SHA-256 before use, and every derivative or cached
conditional lands under the ignored ``files/runtime-data/`` tree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "Universal"

from shared import ffmpeg_utils  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from tts import chatterbox_synth as cbx  # noqa: E402
from tts.kokoro_synth import split_into_chunks  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(),
    reason="ffmpeg/ffprobe unavailable — audio preparation cannot be exercised",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _write_source_audio(path: Path, seconds: int = 30, rate: int = 44100,
                        channels: int = 2, with_cover: bool = False) -> Path:
    """Synthesize a disposable source recording (optionally with attached cover art)."""
    cmd = [ffmpeg_utils.ffmpeg_cmd(), "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate={rate}:duration={seconds}"]
    if with_cover:
        # A one-frame image *file*, the way real recordings carry cover art. A
        # lavfi video source with -frames:v 1 would truncate the whole output.
        art = path.with_name(path.stem + "-art.jpg")
        subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1",
                        "-frames:v", "1", str(art)], check=True, capture_output=True)
        cmd += ["-i", str(art)]
    # Every option below is an OUTPUT option and must follow all -i inputs.
    cmd += ["-map", "0:a:0", "-ac", str(channels), "-ar", str(rate)]
    if with_cover:
        cmd += ["-map", "1:v:0", "-c:v", "copy", "-disposition:v", "attached_pic"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wav_facts(path: Path) -> tuple[int, int, float]:
    with wave.open(str(path), "rb") as w:
        return w.getnchannels(), w.getframerate(), w.getnframes() / w.getframerate()


class _StubConds:
    """Stands in for chatterbox's ``Conditionals`` dataclass."""

    def __init__(self, tag: str = "stub") -> None:
        self.tag = tag

    def to(self, device):  # noqa: D102 - mirrors the real signature
        self.device = device
        return self

    def save(self, fpath) -> None:
        Path(fpath).write_bytes(b"STUBCONDS:" + self.tag.encode("utf-8"))


class _StubConditionalsClass:
    loaded: list[tuple[Path, object]] = []

    @classmethod
    def load(cls, fpath, map_location="cpu"):
        cls.loaded.append((Path(fpath), map_location))
        return _StubConds(Path(fpath).read_bytes().decode("utf-8").split(":", 1)[1])


class _StubModel:
    """Minimum surface ``chatterbox_synth`` is allowed to rely on."""

    def __init__(self, sr: int = 24000, seconds: float = 1.0) -> None:
        self.sr = sr
        self.seconds = seconds
        self.conds = None
        self.device = "cpu"
        self.generated: list[str] = []
        self.prepared: list[str] = []

    def prepare_conditionals(self, wav_fpath, **kwargs):
        self.prepared.append(str(wav_fpath))
        self.conds = _StubConds("prepared")

    def generate(self, text, **kwargs):
        import numpy as np

        self.generated.append(text)
        n = int(self.sr * self.seconds)
        return np.zeros((1, n), dtype="float32")


@pytest.fixture
def stub_engine(monkeypatch, tmp_path):
    """Redirect every derivative/cache root into tmp_path and stub the model."""
    monkeypatch.setattr(cbx, "_runtime_root", lambda: tmp_path / "runtime-data")
    model = _StubModel()
    monkeypatch.setattr(cbx, "_get_model", lambda device=None: model)
    monkeypatch.setattr(cbx, "_conditionals_class", lambda: _StubConditionalsClass)
    _StubConditionalsClass.loaded = []
    return model


# --------------------------------------------------------------------------- #
# B. Importing the module is cheap and side-effect free
# --------------------------------------------------------------------------- #
def test_importing_the_engine_pulls_in_neither_torch_nor_chatterbox():
    """Run in a fresh interpreter — this session has already imported plenty."""
    probe = (
        "import sys, json;"
        "sys.path.insert(0, r'%s');"
        "import tts.chatterbox_synth;"
        "print(json.dumps(sorted(m for m in sys.modules"
        " if m.split('.')[0] in {'torch','chatterbox','transformers','librosa','perth','gradio'})))"
        % SCRIPTS_ROOT
    )
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip()) == []


def test_importing_the_engine_creates_no_directories_and_reads_no_reference():
    probe = (
        "import sys, os;"
        "sys.path.insert(0, r'%s');"
        "opened = [];"
        "import builtins;"
        "_real = builtins.open;"
        "builtins.open = lambda f, *a, **k: (opened.append(str(f)), _real(f, *a, **k))[1];"
        "import tts.chatterbox_synth;"
        "builtins.open = _real;"
        "print('|'.join(o for o in opened if 'Chatterbox-Voice-Uploads' in o))"
        % SCRIPTS_ROOT
    )
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_the_module_sets_the_project_huggingface_cache_before_any_model_import():
    probe = (
        "import sys, os;"
        "sys.path.insert(0, r'%s');"
        "os.environ.pop('HF_HOME', None);"
        "import tts.chatterbox_synth;"
        "print(os.environ.get('HF_HOME', ''))" % SCRIPTS_ROOT
    )
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    hf = Path(r.stdout.strip())
    assert hf == REPO_ROOT / "files" / "runtime-data" / "models" / "huggingface"


def test_the_engine_reuses_the_kokoro_cache_rather_than_inventing_a_second_one():
    from tts import kokoro_synth

    src_kokoro = Path(kokoro_synth.__file__).read_text(encoding="utf-8")
    src_cbx = Path(cbx.__file__).read_text(encoding="utf-8")
    for module_src in (src_kokoro, src_cbx):
        assert 'os.environ["HF_HOME"]' in module_src
    assert "runtime-data" in src_cbx and "huggingface" in src_cbx


# --------------------------------------------------------------------------- #
# C. A missing package degrades truthfully
# --------------------------------------------------------------------------- #
def test_package_status_is_truthful_when_chatterbox_is_absent(monkeypatch):
    monkeypatch.setattr(cbx, "_find_spec", lambda name: None)
    ok, reason = cbx.package_status()
    assert ok is False
    assert "chatterbox" in reason.lower()


def test_package_status_names_the_exact_pinned_requirement_when_absent(monkeypatch):
    monkeypatch.setattr(cbx, "_find_spec", lambda name: None)
    _ok, reason = cbx.package_status()
    assert cbx.PACKAGE_REQUIREMENT in reason


def test_package_status_reports_ok_when_every_module_resolves(monkeypatch):
    monkeypatch.setattr(cbx, "_find_spec", lambda name: object())
    ok, reason = cbx.package_status()
    assert ok is True and reason == "ok"


def test_engine_status_never_raises_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(cbx, "_find_spec", lambda name: None)
    ok, reason = cbx.engine_status("chatterbox-female-1")
    assert ok is False and reason


def test_a_missing_package_breaks_neither_the_launcher_nor_the_other_engines():
    """The lazy engine import must not be reachable from startup imports."""
    probe = (
        "import sys;"
        "sys.path.insert(0, r'%s');"
        "import launcher, tts.epub2tts_gui, tts.kokoro_synth;"
        "print('chatterbox' in {m.split('.')[0] for m in sys.modules})" % SCRIPTS_ROOT
    )
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


# --------------------------------------------------------------------------- #
# D/E. Reference resolution — presence and hash
# --------------------------------------------------------------------------- #
def test_the_four_reference_voices_are_declared_and_closed():
    assert sorted(cbx.REFERENCE_VOICES) == [
        "chatterbox-female-1", "chatterbox-female-2",
        "chatterbox-male-1", "chatterbox-male-2",
    ]


@pytest.mark.parametrize("voice_id,name,sha", [
    ("chatterbox-female-1", "Female-1.mp3",
     "a047d77fe191c1a957d36b1e9f9af8e67756a63672686c55731b30534bb8bde2"),
    ("chatterbox-female-2", "Female-2.mp3",
     "4bad0d3845199eae723aceb7a864b419fe553cd9d23799ee6390f54df08d3140"),
    ("chatterbox-male-1", "Male-1.mp3",
     "6258dde294a91b0c2e965e8579aafde10e9cff48957c2138432be4c6c80165ae"),
    ("chatterbox-male-2", "Male-2.mp3",
     "7b8fd74dfb262740476fba8317c0b7483a9f8b290e58c1d7e496e48b048d6ab2"),
])
def test_each_voice_maps_to_its_exact_source_and_hash(voice_id, name, sha):
    voice = cbx.REFERENCE_VOICES[voice_id]
    assert voice.source_name == name
    assert voice.source_sha256 == sha
    assert cbx.reference_source_path(voice_id).parent == cbx.protected_uploads_dir()


def test_a_missing_reference_reports_setup_required_and_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: tmp_path / "empty")
    ok, reason = cbx.reference_status("chatterbox-male-1")
    assert ok is False
    assert "Male-1.mp3" in reason


def test_a_missing_reference_never_substitutes_another_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: tmp_path / "empty")
    with pytest.raises(cbx.ChatterboxUnavailable) as exc:
        cbx.resolve_reference("chatterbox-male-1")
    assert "Male-1.mp3" in str(exc.value)


def test_a_wrong_hash_is_rejected_and_the_expected_hash_is_named(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "Male-1.mp3").write_bytes(b"not the maintainer's recording")
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    with pytest.raises(cbx.ChatterboxUnavailable) as exc:
        cbx.resolve_reference("chatterbox-male-1")
    message = str(exc.value)
    assert "sha256" in message.lower()
    assert cbx.REFERENCE_VOICES["chatterbox-male-1"].source_sha256 in message


def test_a_correct_hash_is_accepted(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    payload = b"pretend recording"
    target = uploads / "Male-1.mp3"
    target.write_bytes(payload)
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    # ReferenceVoice is frozen — swap the whole entry instead of mutating it
    voice = cbx.ReferenceVoice(
        voice_id="chatterbox-male-1", label="Chatterbox — Male 1",
        source_name="Male-1.mp3", source_sha256=hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setitem(cbx.REFERENCE_VOICES, "chatterbox-male-1", voice)
    assert cbx.resolve_reference("chatterbox-male-1") == target


def test_an_unknown_voice_id_is_rejected_rather_than_guessed():
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx.resolve_reference("chatterbox-male-9")


def _engine_executable_source() -> str:
    """The engine with comments and docstrings stripped.

    Strengthened by the v0.6.1 Plan 4 Phase 12 tuning pass. The guard below used
    to scan the raw file, which meant documentation *about* URLs tripped it: the
    prose-colon rule has to name "https://" as an example of a colon form that
    must NOT receive a pause. Parsing to an AST keeps the guard catching a real
    ``urlopen(...)`` while letting the module explain itself.
    """
    import ast

    tree = ast.parse(Path(cbx.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def test_nothing_is_ever_downloaded_to_replace_a_missing_reference():
    src = _engine_executable_source()
    for token in ("urllib", "requests", "urlopen", "http://", "https://"):
        assert token not in src, f"engine reaches the network via {token!r}"


# --------------------------------------------------------------------------- #
# F/G. Write safety and derivative roots
# --------------------------------------------------------------------------- #
def test_the_derivative_root_is_inside_the_ignored_runtime_tree():
    assert cbx.reference_clips_dir() == (
        REPO_ROOT / "files" / "runtime-data" / "chatterbox" / "reference-clips")


def test_the_conditionals_root_is_inside_the_ignored_runtime_tree():
    assert cbx.conditionals_dir() == (
        REPO_ROOT / "files" / "runtime-data" / "chatterbox" / "conditionals")


def test_a_destination_inside_the_protected_uploads_folder_is_refused():
    target = cbx.protected_uploads_dir() / "Male-1.mp3"
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx._assert_writable_destination(target)


def test_a_destination_below_the_protected_uploads_folder_is_refused():
    target = cbx.protected_uploads_dir() / "derived" / "clip.wav"
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx._assert_writable_destination(target)


def test_a_destination_under_runtime_data_is_allowed():
    cbx._assert_writable_destination(cbx.reference_clips_dir() / "clip.wav")


@needs_ffmpeg
def test_the_engine_writes_only_beneath_runtime_data(stub_engine, tmp_path):
    source = _write_source_audio(tmp_path / "src.wav", seconds=20)
    out = cbx.build_reference_clip(source, tmp_path / "runtime-data" / "clip.wav")
    assert (tmp_path / "runtime-data") in out.parents


# --------------------------------------------------------------------------- #
# H. Derivative identity — enough to prevent stale reuse
# --------------------------------------------------------------------------- #
def test_the_derivative_filename_carries_the_voice_and_the_source_hash(stub_engine):
    voice = cbx.REFERENCE_VOICES["chatterbox-female-1"]
    path = cbx.derivative_path("chatterbox-female-1", voice.source_sha256)
    assert "female-1" in path.name
    assert voice.source_sha256[:16] in path.name
    assert path.suffix == ".wav"


def test_a_changed_source_hash_yields_a_different_derivative(stub_engine):
    a = cbx.derivative_path("chatterbox-female-1", "a" * 64)
    b = cbx.derivative_path("chatterbox-female-1", "b" * 64)
    assert a != b


def test_the_conditional_identity_binds_source_model_and_derivative_spec(stub_engine):
    voice = cbx.REFERENCE_VOICES["chatterbox-male-1"]
    path = cbx.conditionals_path("chatterbox-male-1", voice.source_sha256)
    assert "male-1" in path.name
    assert voice.source_sha256[:16] in path.name
    assert cbx.identity_digest(voice.source_sha256)[:12] in path.name


def test_a_changed_package_identity_invalidates_the_cached_conditional(monkeypatch, stub_engine):
    before = cbx.conditionals_path("chatterbox-male-1", "c" * 64)
    monkeypatch.setattr(cbx, "PACKAGE_REQUIREMENT", "chatterbox-tts==9.9.9")
    after = cbx.conditionals_path("chatterbox-male-1", "c" * 64)
    assert before != after


def test_a_changed_derivative_spec_invalidates_the_cached_conditional(monkeypatch, stub_engine):
    before = cbx.conditionals_path("chatterbox-male-1", "c" * 64)
    monkeypatch.setattr(cbx, "REFERENCE_WINDOW_SECONDS", 11)
    after = cbx.conditionals_path("chatterbox-male-1", "c" * 64)
    assert before != after


def test_the_derivative_spec_records_the_wheel_proven_window():
    spec = cbx.derivative_spec()
    assert spec["window_seconds"] == 15          # ENC_COND_LEN = 15 * 16000
    assert spec["sample_rate"] == 24000          # S3GEN_SR
    assert spec["channels"] == 1
    assert spec["window_position"] == "leading"  # wav[:LEN] — a plain leading slice
    assert spec["loudness_normalized_by_caller"] is False


# --------------------------------------------------------------------------- #
# I. Audio preparation
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_the_derivative_is_mono_24k_and_capped_to_the_conditioning_window(tmp_path):
    source = _write_source_audio(tmp_path / "src.mp3", seconds=40, rate=44100, channels=2)
    out = cbx.build_reference_clip(source, tmp_path / "clip.wav")
    channels, rate, seconds = _wav_facts(out)
    assert channels == 1
    assert rate == 24000
    assert seconds == pytest.approx(15.0, abs=0.15)


@needs_ffmpeg
def test_a_short_source_is_not_padded_to_the_window(tmp_path):
    source = _write_source_audio(tmp_path / "short.wav", seconds=8, rate=22050, channels=1)
    out = cbx.build_reference_clip(source, tmp_path / "clip.wav")
    _channels, _rate, seconds = _wav_facts(out)
    assert seconds == pytest.approx(8.0, abs=0.15)


@needs_ffmpeg
def test_a_source_below_the_models_five_second_floor_is_refused(tmp_path):
    source = _write_source_audio(tmp_path / "tiny.wav", seconds=3, rate=22050, channels=1)
    with pytest.raises(cbx.ChatterboxUnavailable) as exc:
        cbx.build_reference_clip(source, tmp_path / "clip.wav")
    assert "5" in str(exc.value)


@needs_ffmpeg
def test_an_embedded_cover_art_stream_is_never_chosen_as_the_audio(tmp_path):
    source = _write_source_audio(tmp_path / "cover.mp3", seconds=20, with_cover=True)
    out = cbx.build_reference_clip(source, tmp_path / "clip.wav")
    channels, rate, seconds = _wav_facts(out)
    assert channels == 1 and rate == 24000
    assert seconds == pytest.approx(15.0, abs=0.2)


@needs_ffmpeg
def test_preparing_a_derivative_leaves_the_source_byte_identical(tmp_path):
    source = _write_source_audio(tmp_path / "src.mp3", seconds=25, with_cover=True)
    before = _sha(source)
    cbx.build_reference_clip(source, tmp_path / "clip.wav")
    assert _sha(source) == before


@needs_ffmpeg
def test_the_derivative_is_deterministic_across_two_runs(tmp_path):
    source = _write_source_audio(tmp_path / "src.mp3", seconds=25)
    first = cbx.build_reference_clip(source, tmp_path / "a.wav")
    second = cbx.build_reference_clip(source, tmp_path / "b.wav")
    assert _sha(first) == _sha(second)


def test_the_engine_applies_no_loudness_normalisation_of_its_own():
    """The model normalises to about -27 LUFS itself; doing it twice would be wrong."""
    src = Path(cbx.__file__).read_text(encoding="utf-8")
    for token in ("loudnorm", "dynaudnorm", "normalize(", "apply_gain"):
        assert token not in src, f"caller-side normalisation via {token!r}"


@needs_ffmpeg
def test_preparing_a_reference_writes_a_manifest_tracing_it_to_its_source(
        monkeypatch, stub_engine, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = _write_source_audio(uploads / "Male-1.mp3", seconds=25)
    voice = cbx.ReferenceVoice(
        voice_id="chatterbox-male-1", label="Chatterbox — Male 1",
        source_name="Male-1.mp3", source_sha256=_sha(source),
    )
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    monkeypatch.setitem(cbx.REFERENCE_VOICES, "chatterbox-male-1", voice)

    clip = cbx.prepare_reference_clip("chatterbox-male-1", log=lambda _m: None)
    manifest = json.loads((clip.parent / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["chatterbox-male-1"]
    assert entry["source_sha256"] == _sha(source)
    assert entry["source_path"].endswith("Male-1.mp3")
    assert Path(entry["derivative_path"]).name == clip.name
    assert entry["parameters"] == cbx.derivative_spec()


@needs_ffmpeg
def test_a_prepared_derivative_is_reused_rather_than_rebuilt(
        monkeypatch, stub_engine, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = _write_source_audio(uploads / "Male-1.mp3", seconds=25)
    voice = cbx.ReferenceVoice(
        voice_id="chatterbox-male-1", label="Chatterbox — Male 1",
        source_name="Male-1.mp3", source_sha256=_sha(source),
    )
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    monkeypatch.setitem(cbx.REFERENCE_VOICES, "chatterbox-male-1", voice)

    first = cbx.prepare_reference_clip("chatterbox-male-1", log=lambda _m: None)
    stamp = first.stat().st_mtime_ns
    second = cbx.prepare_reference_clip("chatterbox-male-1", log=lambda _m: None)
    assert first == second
    assert second.stat().st_mtime_ns == stamp


# --------------------------------------------------------------------------- #
# J. Conditional cache
# --------------------------------------------------------------------------- #
def _prepared_voice(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = _write_source_audio(uploads / "Male-1.mp3", seconds=25)
    voice = cbx.ReferenceVoice(
        voice_id="chatterbox-male-1", label="Chatterbox — Male 1",
        source_name="Male-1.mp3", source_sha256=_sha(source),
    )
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: uploads)
    monkeypatch.setitem(cbx.REFERENCE_VOICES, "chatterbox-male-1", voice)
    return voice


@needs_ffmpeg
def test_conditionals_are_computed_once_and_cached_under_runtime_data(
        monkeypatch, stub_engine, tmp_path):
    voice = _prepared_voice(monkeypatch, tmp_path)
    model = stub_engine
    cbx.load_conditionals(model, "chatterbox-male-1", log=lambda _m: None)
    assert len(model.prepared) == 1
    cached = cbx.conditionals_path("chatterbox-male-1", voice.source_sha256)
    assert cached.exists()
    assert (tmp_path / "runtime-data") in cached.parents


@needs_ffmpeg
def test_a_second_use_loads_the_cached_conditional_instead_of_recomputing(
        monkeypatch, stub_engine, tmp_path):
    _prepared_voice(monkeypatch, tmp_path)
    model = stub_engine
    cbx.load_conditionals(model, "chatterbox-male-1", log=lambda _m: None)
    fresh = _StubModel()
    cbx.load_conditionals(fresh, "chatterbox-male-1", log=lambda _m: None)
    assert fresh.prepared == []
    assert fresh.conds is not None
    assert _StubConditionalsClass.loaded


@needs_ffmpeg
def test_the_cached_conditional_is_loaded_with_an_explicit_map_location(
        monkeypatch, stub_engine, tmp_path):
    _prepared_voice(monkeypatch, tmp_path)
    cbx.load_conditionals(stub_engine, "chatterbox-male-1", log=lambda _m: None)
    fresh = _StubModel()
    cbx.load_conditionals(fresh, "chatterbox-male-1", log=lambda _m: None)
    _path, map_location = _StubConditionalsClass.loaded[-1]
    assert map_location == fresh.device


@needs_ffmpeg
def test_a_source_hash_change_makes_the_cached_conditional_stale(
        monkeypatch, stub_engine, tmp_path):
    voice = _prepared_voice(monkeypatch, tmp_path)
    cbx.load_conditionals(stub_engine, "chatterbox-male-1", log=lambda _m: None)
    stale = cbx.conditionals_path("chatterbox-male-1", voice.source_sha256)

    changed = cbx.ReferenceVoice(
        voice_id=voice.voice_id, label=voice.label,
        source_name=voice.source_name, source_sha256="d" * 64,
    )
    monkeypatch.setitem(cbx.REFERENCE_VOICES, "chatterbox-male-1", changed)
    assert cbx.conditionals_path("chatterbox-male-1", "d" * 64) != stale


@needs_ffmpeg
def test_a_corrupt_cached_conditional_is_recomputed_not_trusted(
        monkeypatch, stub_engine, tmp_path):
    voice = _prepared_voice(monkeypatch, tmp_path)
    cbx.load_conditionals(stub_engine, "chatterbox-male-1", log=lambda _m: None)
    cached = cbx.conditionals_path("chatterbox-male-1", voice.source_sha256)
    cached.write_bytes(b"\x00\x01 truncated")

    fresh = _StubModel()
    cbx.load_conditionals(fresh, "chatterbox-male-1", log=lambda _m: None)
    assert fresh.prepared, "a corrupt cache must fall back to recomputation"


# --------------------------------------------------------------------------- #
# K. Device selection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cuda,mps,expected", [
    (True, True, "cuda"),
    (True, False, "cuda"),
    (False, True, "mps"),
    (False, False, "cpu"),
])
def test_device_selection_resolves_cuda_then_mps_then_cpu(monkeypatch, cuda, mps, expected):
    monkeypatch.setattr(cbx, "_torch_capabilities", lambda: (cuda, mps))
    assert cbx.select_device() == expected


def test_device_selection_falls_back_to_cpu_when_torch_cannot_be_probed(monkeypatch):
    def boom():
        raise RuntimeError("torch is not installed")

    monkeypatch.setattr(cbx, "_torch_capabilities", boom)
    assert cbx.select_device() == "cpu"


def test_the_engine_pins_no_cuda_specific_behaviour():
    src = Path(cbx.__file__).read_text(encoding="utf-8")
    for token in ("cuda_amp", "half()", "autocast", "device_map", "torch.cuda.set_device"):
        assert token not in src, f"CUDA-specific behaviour via {token!r}"


# --------------------------------------------------------------------------- #
# L. First-load retry — narrow, and only once
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch):
    monkeypatch.setattr(cbx, "_first_model_load_attempted", False, raising=False)
    monkeypatch.setattr(cbx, "_MODEL_CACHE", {}, raising=False)


def test_the_first_native_library_block_is_retried_once(monkeypatch):
    calls = {"n": 0}

    def loader(device):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("An Application Control policy has blocked this file")
        return _StubModel()

    monkeypatch.setattr(cbx, "_instantiate_model", loader)
    monkeypatch.setattr(cbx.time, "sleep", lambda _s: None)
    assert isinstance(cbx._get_model("cpu"), _StubModel)
    assert calls["n"] == 2


def test_a_second_failure_on_the_first_load_propagates(monkeypatch):
    def loader(device):
        raise ImportError("DLL load failed while importing _C")

    monkeypatch.setattr(cbx, "_instantiate_model", loader)
    monkeypatch.setattr(cbx.time, "sleep", lambda _s: None)
    with pytest.raises(ImportError):
        cbx._get_model("cpu")


def test_a_later_load_failure_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def loader(device):
        calls["n"] += 1
        raise OSError("blocked")

    monkeypatch.setattr(cbx, "_first_model_load_attempted", True, raising=False)
    monkeypatch.setattr(cbx, "_instantiate_model", loader)
    monkeypatch.setattr(cbx.time, "sleep", lambda _s: None)
    with pytest.raises(OSError):
        cbx._get_model("cpu")
    assert calls["n"] == 1


def test_generation_failures_are_never_retried():
    """Only the first model load retries; the synthesis loop must not."""
    import ast

    src = Path(cbx.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "chatterbox_file_to_mp3")
    assert "retry" not in ast.get_source_segment(src, body).lower()


def test_the_loaded_model_is_cached_per_device(monkeypatch):
    made: list[str] = []

    def loader(device):
        made.append(device)
        return _StubModel()

    monkeypatch.setattr(cbx, "_instantiate_model", loader)
    first = cbx._get_model("cpu")
    second = cbx._get_model("cpu")
    assert first is second
    assert made == ["cpu"]


# --------------------------------------------------------------------------- #
# M. File synthesis — the worker-facing contract
# --------------------------------------------------------------------------- #
@pytest.fixture
def synth_ready(monkeypatch, stub_engine, tmp_path):
    monkeypatch.setattr(cbx, "load_conditionals",
                        lambda model, voice_id, log=print, device=None: None)
    return stub_engine


def _source_text(tmp_path: Path, sentences: int = 40) -> Path:
    body = " ".join(f"This is sentence number {i} of the sample text." for i in range(sentences))
    path = tmp_path / "source.txt"
    path.write_text(f"Title: Sample\nAuthor: Nobody\n{body}\n", encoding="utf-8")
    return path


def test_file_synthesis_uses_the_chatterbox_chunker_not_kokoros(synth_ready, tmp_path):
    """Retargeted by the v0.6.1 Plan 4 Phase 12 remediation — the assertion is
    inverted, deliberately, because it used to encode the defect.

    Phase 8 wrote this as ``test_file_synthesis_reuses_the_existing_chunker`` and
    asserted the Chatterbox path produced *exactly* Kokoro's chunk count. The
    Phase 12 manual matrix proved that reuse is the bug: Kokoro's 3,000-character
    default is ten times Chatterbox Turbo's supported input, and three real
    chapters converted that way reported success while producing ~2% of their
    audio. The engine now owns ``split_for_chatterbox``; this test is the guard
    that it is never wired back to Kokoro's. Nothing is weakened — the contract
    asserted here is strictly stronger, and the full ceiling contract lives in
    ``test_chatterbox_longform.py``.
    """
    body = " ".join(f"This is sentence number {i} of the sample text." for i in range(400))
    source = _source_text(tmp_path, sentences=400)
    out = tmp_path / "out.mp3"
    cbx.chatterbox_file_to_mp3(str(source), str(out), "chatterbox-male-1",
                              log=lambda _m: None)
    kokoro_would_make = len(split_into_chunks(body))
    assert len(synth_ready.generated) > kokoro_would_make > 1
    assert max(len(t) for t in synth_ready.generated) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS


def test_file_synthesis_writes_the_requested_mp3(synth_ready, tmp_path):
    out = tmp_path / "nested" / "out.mp3"
    out.parent.mkdir()
    cbx.chatterbox_file_to_mp3(str(_source_text(tmp_path)), str(out),
                               "chatterbox-male-1", log=lambda _m: None)
    assert out.exists() and out.stat().st_size > 0


def test_progress_is_reported_as_done_over_total(synth_ready, tmp_path):
    seen: list[tuple[int, int]] = []
    cbx.chatterbox_file_to_mp3(
        str(_source_text(tmp_path, sentences=400)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None,
        progress_callback=lambda done, total: seen.append((done, total)),
    )
    assert seen, "progress_callback was never invoked"
    total = seen[0][1]
    assert [d for d, _t in seen] == list(range(1, total + 1))
    assert all(t == total for _d, t in seen)


def test_cancellation_between_chunks_raises_conversion_cancelled(synth_ready, tmp_path):
    out = tmp_path / "out.mp3"
    with pytest.raises(ConversionCancelled):
        cbx.chatterbox_file_to_mp3(
            str(_source_text(tmp_path, sentences=400)), str(out),
            "chatterbox-male-1", log=lambda _m: None, cancel_check=lambda: True,
        )
    assert not out.exists()


def test_cancellation_is_checked_between_chunks_not_mid_generation(synth_ready, tmp_path):
    calls = {"n": 0}

    def cancel_after_one() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(ConversionCancelled):
        cbx.chatterbox_file_to_mp3(
            str(_source_text(tmp_path, sentences=400)), str(tmp_path / "out.mp3"),
            "chatterbox-male-1", log=lambda _m: None, cancel_check=cancel_after_one,
        )
    assert len(synth_ready.generated) == 1


def test_the_end_silence_and_chunk_pause_contract_is_honoured(synth_ready, tmp_path):
    from pydub import AudioSegment

    source = _source_text(tmp_path, sentences=400)
    short = tmp_path / "short.mp3"
    long = tmp_path / "long.mp3"
    cbx.chatterbox_file_to_mp3(str(source), str(short), "chatterbox-male-1",
                               end_silence_ms=0, chunk_pause_ms=0, log=lambda _m: None)
    cbx.chatterbox_file_to_mp3(str(source), str(long), "chatterbox-male-1",
                               end_silence_ms=3000, chunk_pause_ms=50, log=lambda _m: None)
    assert len(AudioSegment.from_mp3(long)) > len(AudioSegment.from_mp3(short)) + 2500


def test_the_worker_facing_signature_matches_the_kokoro_shape():
    import inspect

    from tts.kokoro_synth import kokoro_file_to_mp3

    shared = {"source_path", "output_mp3_path", "voice_id", "end_silence_ms",
              "chunk_pause_ms", "log", "cancel_check", "progress_callback"}
    kokoro = set(inspect.signature(kokoro_file_to_mp3).parameters)
    chatter = set(inspect.signature(cbx.chatterbox_file_to_mp3).parameters)
    assert shared <= kokoro
    assert shared <= chatter


def test_text_synthesis_writes_an_mp3_at_the_requested_path(synth_ready, tmp_path):
    out = tmp_path / "line.mp3"
    cbx.synthesize_text_to_mp3("A single line of narration.", str(out),
                               "chatterbox-male-1", log=lambda _m: None)
    assert out.exists() and out.stat().st_size > 0


def test_synthesis_uses_the_models_own_sample_rate(monkeypatch, synth_ready, tmp_path):
    from pydub import AudioSegment

    synth_ready.sr = 24000
    synth_ready.seconds = 2.0
    out = tmp_path / "line.mp3"
    cbx.synthesize_text_to_mp3("Narration.", str(out), "chatterbox-male-1",
                               log=lambda _m: None)
    assert len(AudioSegment.from_mp3(out)) == pytest.approx(2000, abs=150)


def test_an_empty_source_is_refused_rather_than_producing_silence(synth_ready, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("Title: Nothing\nAuthor: Nobody\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cbx.chatterbox_file_to_mp3(str(empty), str(tmp_path / "out.mp3"),
                                   "chatterbox-male-1", log=lambda _m: None)


def test_a_missing_source_file_is_reported_clearly(synth_ready, tmp_path):
    with pytest.raises(FileNotFoundError):
        cbx.chatterbox_file_to_mp3(str(tmp_path / "nope.txt"), str(tmp_path / "out.mp3"),
                                   "chatterbox-male-1", log=lambda _m: None)


# --------------------------------------------------------------------------- #
# Watermark — preserved, never bypassed
# --------------------------------------------------------------------------- #
def test_the_engine_neither_disables_nor_strips_the_perth_watermark():
    src = Path(cbx.__file__).read_text(encoding="utf-8")
    for token in ("watermarker", "apply_watermark", "PerthImplicitWatermarker",
                  "DummyWatermarker", "perth."):
        assert token not in src, f"the engine touches the watermark path via {token!r}"
