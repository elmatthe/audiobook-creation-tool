"""v0.6.1 Plan 4 Phase 9 — the Chatterbox listening-evaluation mode.

Phase 9 produces **exactly four** WAV files, one per maintainer-supplied reference
recording, and then stops for a human to listen. Nothing here loads real weights,
reads a real recording, or reaches the network: the engine is stubbed at the seams
``chatterbox_synth`` already exposes, and every audio fixture is generated into
``tmp_path``.

The rules under test are the drop's Phase 9 stop conditions: four sources in, four
outputs out, under the already-ignored manual-listen folder, with the raw MP3s
untouched, no ``VoiceEntry`` registered, and no GUI dispatch — the last two belong
to Phase 10, which has not started.
"""

from __future__ import annotations

import ast
import wave
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TTS_DIR = REPO_ROOT / "scripts" / "Universal" / "tts"

from tts import chatterbox_synth as cbx  # noqa: E402
from tts import generate_voice_samples as gvs  # noqa: E402
from tts import voice_registry  # noqa: E402

#: The sentence the maintainer approved, byte for byte. Written out here rather
#: than imported, so the test fails if the production constant ever drifts.
APPROVED_TEXT = (
    "Welcome to the audiobook creation tool. This is a sample test evaluating "
    "Chatterbox for clarity, pacing, and emotional depth."
)

APPROVED_VOICE_IDS = (
    "chatterbox-female-1",
    "chatterbox-female-2",
    "chatterbox-male-1",
    "chatterbox-male-2",
)

APPROVED_OUTPUT_NAMES = (
    "chatterbox-female-1.wav",
    "chatterbox-female-2.wav",
    "chatterbox-male-1.wav",
    "chatterbox-male-2.wav",
)


# --------------------------------------------------------------------------- #
# Harness — the engine stubbed at exactly the seams the evaluation may use
# --------------------------------------------------------------------------- #
class _StubModel:
    """Minimum model surface ``synthesize_text_to_wav`` is allowed to rely on."""

    def __init__(self, sr: int = 24000, seconds: float = 1.5) -> None:
        self.sr = sr
        self.seconds = seconds
        self.conds = None
        self.device = "cpu"
        self.generated: list[str] = []

    def generate(self, text, **kwargs):
        self.generated.append(text)
        return np.zeros((1, int(self.sr * self.seconds)), dtype="float32")


def _write_wav(path: Path, seconds: float = 1.5, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


class _Engine:
    """Records every call the evaluation makes into the engine."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.resolved: list[str] = []
        self.prepared: list[str] = []
        self.generated: list[tuple[str, str, str]] = []  # (voice, text, out)
        self.conditionals_computed: list[str] = []
        self.audio_seconds = 1.5
        self.sample_rate = 24000
        self.fail_hash_for: str | None = None
        self.fail_generation_for: str | None = None
        self.cached_conditionals: set[str] = set()

    # --- reference resolution -------------------------------------------- #
    def resolve_reference(self, voice_id: str) -> Path:
        if voice_id == self.fail_hash_for:
            raise cbx.ChatterboxUnavailable(
                f"The reference recording for {voice_id} does not match the "
                "expected sha256. Refusing to use it."
            )
        self.resolved.append(voice_id)
        source = self.tmp_path / "uploads" / cbx.REFERENCE_VOICES[voice_id].source_name
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            source.write_bytes(b"protected maintainer recording for " + voice_id.encode())
        return source

    def prepare_reference_clip(self, voice_id: str, log=print) -> Path:
        self.prepared.append(voice_id)
        clip = self.tmp_path / "runtime-data" / "reference-clips" / f"{voice_id}.wav"
        _write_wav(clip, seconds=15.0)
        return clip

    def conditionals_path(self, voice_id: str, source_sha256: str) -> Path:
        path = self.tmp_path / "runtime-data" / "conditionals" / f"{voice_id}.pt"
        path.parent.mkdir(parents=True, exist_ok=True)
        if voice_id in self.cached_conditionals and not path.exists():
            path.write_bytes(b"cached conditionals")
        return path

    def load_conditionals(self, model, voice_id, log=print, device=None) -> None:
        cache = self.conditionals_path(voice_id, "0" * 64)
        if cache.is_file():
            return
        self.conditionals_computed.append(voice_id)
        cache.write_bytes(b"freshly computed conditionals")

    # --- synthesis --------------------------------------------------------- #
    def synthesize_text_to_wav(self, text, output_path, voice_id, log=print,
                               device=None) -> int:
        if voice_id == self.fail_generation_for:
            raise cbx.ChatterboxUnavailable(
                f"Chatterbox produced no audio for voice '{voice_id}'.")
        # The real helper attaches the voice identity before generating; mirror
        # that here so cache reuse is genuinely exercised rather than assumed.
        self.load_conditionals(None, voice_id)
        self.generated.append((voice_id, text, str(output_path)))
        _write_wav(Path(output_path), seconds=self.audio_seconds, rate=self.sample_rate)
        return self.sample_rate

    def generation_defaults(self) -> dict:
        return {"temperature": 0.8, "repetition_penalty": 2.0, "top_p": 1.0}


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """Point the evaluation at a stub engine and a throwaway output tree."""
    stub = _Engine(tmp_path)
    for name in ("resolve_reference", "prepare_reference_clip", "conditionals_path",
                 "load_conditionals", "synthesize_text_to_wav", "generation_defaults"):
        monkeypatch.setattr(cbx, name, getattr(stub, name), raising=False)
    monkeypatch.setattr(cbx, "select_device", lambda: "cpu")
    monkeypatch.setattr(cbx, "protected_uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(gvs, "_out_dir", lambda: _made(tmp_path / "manual-listen"))
    return stub


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(log=None) -> list:
    return gvs.run_chatterbox_evaluation(log=log or (lambda _m: None))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --------------------------------------------------------------------------- #
# A. A dedicated mode — ordinary sample generation is unchanged
# --------------------------------------------------------------------------- #
def test_the_generator_exposes_a_dedicated_chatterbox_evaluation_entry_point():
    assert callable(gvs.run_chatterbox_evaluation)


def test_the_evaluation_requires_an_explicit_command_line_flag():
    parser = gvs._build_parser()
    assert parser.parse_args([]).chatterbox_eval is False
    assert parser.parse_args(["--chatterbox-eval"]).chatterbox_eval is True


def test_an_ordinary_sample_run_never_reaches_the_chatterbox_evaluation(monkeypatch):
    """Chatterbox synthesis is expensive; a plain invocation must not trigger it."""
    called: list[str] = []
    monkeypatch.setattr(gvs, "run_chatterbox_evaluation",
                        lambda *a, **k: called.append("ran") or [])
    monkeypatch.setattr("sys.argv", ["generate_voice_samples.py", "no-such-voice"])
    gvs.main()
    assert called == []


def test_the_ordinary_sample_text_is_untouched_by_phase_nine():
    assert gvs.SAMPLE_TEXT == (
        "The quick brown fox jumps over the lazy dog. "
        "This is a short sample of this voice reading two sentences aloud."
    )


def test_the_ordinary_selection_still_covers_every_registered_voice():
    assert len(gvs._select([])) == len(voice_registry.VOICES) == 12


def test_the_ordinary_backend_filters_still_work():
    assert {v.backend for v in gvs._select(["kokoro"])} == {"kokoro"}
    assert {v.backend for v in gvs._select(["edge"])} == {"edge"}


# --------------------------------------------------------------------------- #
# B. Exactly the four approved sources
# --------------------------------------------------------------------------- #
def test_the_evaluation_covers_exactly_the_four_approved_voices():
    assert tuple(gvs.CHATTERBOX_EVAL_VOICE_IDS) == APPROVED_VOICE_IDS


def test_the_evaluation_ids_are_exactly_the_engines_reference_voices():
    assert sorted(gvs.CHATTERBOX_EVAL_VOICE_IDS) == sorted(cbx.REFERENCE_VOICES)


def test_no_fifth_speaker_can_be_smuggled_in(engine):
    results = _run()
    assert len(results) == 4
    assert [r.voice_id for r in results] == list(APPROVED_VOICE_IDS)


# --------------------------------------------------------------------------- #
# C. The exact sample text
# --------------------------------------------------------------------------- #
def test_the_evaluation_text_is_the_approved_sentence_byte_for_byte():
    assert gvs.CHATTERBOX_EVAL_TEXT == APPROVED_TEXT


def test_every_output_is_generated_from_that_identical_text(engine):
    _run()
    assert {text for _voice, text, _out in engine.generated} == {APPROVED_TEXT}


def test_the_evaluation_text_is_not_the_ordinary_sample_text():
    assert gvs.CHATTERBOX_EVAL_TEXT != gvs.SAMPLE_TEXT


# --------------------------------------------------------------------------- #
# D/E. Exact output names, under exactly one root
# --------------------------------------------------------------------------- #
def test_the_four_outputs_carry_exactly_the_approved_filenames(engine):
    results = _run()
    assert [Path(r.output_path).name for r in results] == list(APPROVED_OUTPUT_NAMES)


def test_the_outputs_land_only_in_the_chatterbox_eval_folder(engine, tmp_path):
    results = _run()
    expected = tmp_path / "manual-listen" / "chatterbox-eval"
    for r in results:
        assert Path(r.output_path).parent == expected
    assert sorted(p.name for p in expected.iterdir()) == sorted(APPROVED_OUTPUT_NAMES)


def test_the_eval_folder_sits_inside_the_already_ignored_manual_listen_folder():
    assert gvs.CHATTERBOX_EVAL_SUBDIR == "chatterbox-eval"
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "files/test-for-manual-listen-elmatthe/" in ignore


def test_the_real_output_root_is_the_approved_repository_path(monkeypatch):
    assert gvs._chatterbox_eval_dir.__doc__  # documented, not incidental
    expected = (REPO_ROOT / "files" / "test-for-manual-listen-elmatthe"
                / "chatterbox-eval")
    monkeypatch.setattr(gvs, "_out_dir", lambda: expected.parent)
    assert gvs._chatterbox_eval_dir(create=False) == expected


# --------------------------------------------------------------------------- #
# F. The rejected tracked sample directory is never used
# --------------------------------------------------------------------------- #
def test_the_generator_never_names_the_rejected_tracked_sample_directory():
    src = (TTS_DIR / "generate_voice_samples.py").read_text(encoding="utf-8")
    assert "voice_eval" not in src


def test_no_tests_samples_directory_is_created_by_the_evaluation(engine, tmp_path):
    _run()
    assert not (tmp_path / "tests").exists()
    assert not (REPO_ROOT / "tests").exists()


# --------------------------------------------------------------------------- #
# G. Four generations — no sweeps, no variants, no retries
# --------------------------------------------------------------------------- #
def test_exactly_four_generations_happen(engine):
    _run()
    assert len(engine.generated) == 4


def test_each_voice_is_generated_exactly_once(engine):
    _run()
    assert [voice for voice, _t, _o in engine.generated] == list(APPROVED_VOICE_IDS)


def test_exactly_four_files_exist_afterwards(engine, tmp_path):
    _run()
    produced = list((tmp_path / "manual-listen" / "chatterbox-eval").glob("*"))
    assert len(produced) == 4


def test_a_poor_sounding_result_is_never_regenerated(engine):
    """No quality heuristic may exist: four calls, whatever comes back."""
    engine.audio_seconds = 0.2  # implausibly short, but still valid audio
    _run()
    assert len(engine.generated) == 4


# --------------------------------------------------------------------------- #
# H. A source hash mismatch is a hard stop
# --------------------------------------------------------------------------- #
def test_a_source_hash_mismatch_stops_before_any_generation(engine):
    engine.fail_hash_for = "chatterbox-male-1"
    _run()
    assert engine.generated == []


def test_a_source_hash_mismatch_still_reports_all_four_rows(engine):
    engine.fail_hash_for = "chatterbox-female-2"
    results = _run()
    assert [r.voice_id for r in results] == list(APPROVED_VOICE_IDS)


def test_a_source_hash_mismatch_names_the_failing_voice(engine):
    engine.fail_hash_for = "chatterbox-female-2"
    results = _run()
    failed = next(r for r in results if r.voice_id == "chatterbox-female-2")
    assert failed.ok is False
    assert "sha256" in failed.detail.lower()


def test_the_other_three_voices_are_not_quietly_declared_successful(engine):
    engine.fail_hash_for = "chatterbox-female-2"
    results = _run()
    assert all(r.ok is False for r in results)


def test_a_source_hash_mismatch_never_substitutes_another_source(engine):
    engine.fail_hash_for = "chatterbox-male-2"
    results = _run()
    sources = {Path(r.source_path).name for r in results if r.source_path}
    assert "Male-2.mp3" not in sources or all(not r.ok for r in results)
    assert engine.generated == []


# --------------------------------------------------------------------------- #
# I. Reference preparation is delegated, never re-implemented
# --------------------------------------------------------------------------- #
def test_the_evaluation_verifies_every_source_hash_through_the_engine(engine):
    _run()
    assert engine.resolved == list(APPROVED_VOICE_IDS)


def test_the_evaluation_delegates_derivative_preparation_to_the_engine(engine):
    _run()
    assert engine.prepared == list(APPROVED_VOICE_IDS)


def test_the_generator_contains_no_audio_slicing_logic_of_its_own():
    """The 15-second window belongs to the engine; duplicating it would drift.

    ``ffmpeg_utils.configure_pydub()`` is deliberately not in this list — it is the
    pre-existing Edge/Kokoro setup call, not reference decoding.
    """
    src = (TTS_DIR / "generate_voice_samples.py").read_text(encoding="utf-8")
    for token in ("subprocess", "pcm_s16le", "0:a:0", "map_metadata", "librosa"):
        assert token not in src, f"generate_voice_samples re-implements decoding via {token!r}"


def test_the_generator_defines_no_reference_window_of_its_own():
    tree = _tree(TTS_DIR / "generate_voice_samples.py")
    assigned = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "REFERENCE_WINDOW_SECONDS" not in assigned
    assert "REFERENCE_SAMPLE_RATE" not in assigned


def test_each_result_records_the_engine_prepared_derivative(engine):
    for r in _run():
        assert r.derivative_path
        assert Path(r.derivative_path).name.endswith(".wav")


# --------------------------------------------------------------------------- #
# J. Cached conditionals are reused, not recomputed
# --------------------------------------------------------------------------- #
def test_a_valid_cached_conditional_is_not_recomputed(engine):
    engine.cached_conditionals = set(APPROVED_VOICE_IDS)
    _run()
    assert engine.conditionals_computed == []


def test_a_missing_conditional_is_computed_once(engine):
    results = _run()
    assert all(r.conditional_state == "computed" for r in results)
    assert engine.conditionals_computed == list(APPROVED_VOICE_IDS)


def test_the_result_reports_a_reused_conditional_as_reused(engine):
    engine.cached_conditionals = set(APPROVED_VOICE_IDS)
    results = _run()
    assert all(r.conditional_state == "reused" for r in results)


def test_each_result_names_the_conditional_cache_path(engine):
    for r in _run():
        assert r.conditional_path.endswith(".pt")


# --------------------------------------------------------------------------- #
# K. WAV writing — the engine helper, at the model's own rate
# --------------------------------------------------------------------------- #
@pytest.fixture
def wav_ready(monkeypatch):
    model = _StubModel()
    monkeypatch.setattr(cbx, "_get_model", lambda device=None: model)
    monkeypatch.setattr(cbx, "load_conditionals",
                        lambda m, v, log=print, device=None: None)
    return model


def test_the_engine_writes_a_readable_non_empty_wav(wav_ready, tmp_path):
    out = tmp_path / "sample.wav"
    cbx.synthesize_text_to_wav(APPROVED_TEXT, str(out), "chatterbox-male-1",
                               log=lambda _m: None)
    assert out.exists() and out.stat().st_size > 0
    with wave.open(str(out), "rb") as w:
        assert w.getnframes() > 0


def test_the_wav_carries_the_models_own_sample_rate(wav_ready, tmp_path):
    wav_ready.sr = 22050
    out = tmp_path / "sample.wav"
    rate = cbx.synthesize_text_to_wav(APPROVED_TEXT, str(out), "chatterbox-male-1",
                                      log=lambda _m: None)
    assert rate == 22050
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 22050


def test_the_wav_duration_matches_the_generated_waveform(wav_ready, tmp_path):
    wav_ready.seconds = 3.0
    out = tmp_path / "sample.wav"
    cbx.synthesize_text_to_wav("Narration.", str(out), "chatterbox-male-1",
                               log=lambda _m: None)
    with wave.open(str(out), "rb") as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(3.0, abs=0.05)


def test_an_empty_waveform_is_refused_rather_than_written(wav_ready, tmp_path):
    wav_ready.seconds = 0.0
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx.synthesize_text_to_wav("Narration.", str(tmp_path / "empty.wav"),
                                   "chatterbox-male-1", log=lambda _m: None)


def test_the_wav_helper_refuses_a_destination_inside_the_protected_folder(wav_ready):
    target = cbx.protected_uploads_dir() / "leaked.wav"
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx.synthesize_text_to_wav("Narration.", str(target), "chatterbox-male-1",
                                   log=lambda _m: None)


def test_the_evaluation_writes_wav_not_mp3(engine):
    for r in _run():
        assert r.output_path.endswith(".wav")


# --------------------------------------------------------------------------- #
# L. Reporting — four rows, failures included
# --------------------------------------------------------------------------- #
def test_the_summary_table_has_the_approved_header(engine):
    table = gvs.format_chatterbox_table(_run())
    lines = table.strip().splitlines()
    assert lines[0] == (
        "| Voice | Reference source | Output path | Duration | Parameters | Result |")
    assert lines[1] == "|---|---|---|---|---|---|"


def test_the_summary_table_has_exactly_four_data_rows(engine):
    table = gvs.format_chatterbox_table(_run())
    rows = [ln for ln in table.strip().splitlines()[2:] if ln.startswith("|")]
    assert len(rows) == 4


def test_the_summary_table_names_every_voice(engine):
    table = gvs.format_chatterbox_table(_run())
    for voice_id in APPROVED_VOICE_IDS:
        assert voice_id in table


def test_a_failed_voice_still_appears_in_the_table(engine):
    engine.fail_generation_for = "chatterbox-male-2"
    results = _run()
    table = gvs.format_chatterbox_table(results)
    assert "chatterbox-male-2" in table
    assert "FAIL" in table


def test_a_generation_failure_is_recorded_not_dropped(engine):
    engine.fail_generation_for = "chatterbox-male-2"
    results = _run()
    assert len(results) == 4
    failed = next(r for r in results if r.voice_id == "chatterbox-male-2")
    assert failed.ok is False and failed.detail


def test_a_generation_failure_does_not_stop_the_remaining_voices(engine):
    engine.fail_generation_for = "chatterbox-female-1"
    results = _run()
    assert [r.ok for r in results] == [False, True, True, True]


def test_a_generation_failure_is_never_retried(engine):
    engine.fail_generation_for = "chatterbox-female-1"
    _run()
    assert [v for v, _t, _o in engine.generated] == list(APPROVED_VOICE_IDS[1:])


def test_the_table_reports_the_effective_parameters(engine):
    table = gvs.format_chatterbox_table(_run())
    assert "temperature=0.8" in table


def test_every_result_carries_the_engine_and_model_identity(engine):
    for r in _run():
        assert r.parameters["package"] == cbx.PACKAGE_REQUIREMENT
        assert r.parameters["model"] == cbx.MODEL_REPO_ID


def test_every_result_carries_the_reference_window_spec(engine):
    for r in _run():
        assert r.parameters["reference"] == cbx.derivative_spec()


# --------------------------------------------------------------------------- #
# M. Performance is measured per voice, never aggregated away
# --------------------------------------------------------------------------- #
def test_each_result_records_wall_time_audio_duration_and_rtf(engine):
    for r in _run():
        assert r.wall_seconds is not None and r.wall_seconds >= 0
        assert r.audio_seconds == pytest.approx(1.5, abs=0.05)
        assert r.rtf == pytest.approx(r.wall_seconds / r.audio_seconds, rel=1e-6)


def test_the_audio_duration_is_read_back_from_the_written_file(engine):
    engine.audio_seconds = 4.0
    for r in _run():
        assert r.audio_seconds == pytest.approx(4.0, abs=0.05)


def test_a_failed_voice_reports_no_invented_performance_figures(engine):
    engine.fail_generation_for = "chatterbox-male-1"
    failed = next(r for r in _run() if r.voice_id == "chatterbox-male-1")
    assert failed.audio_seconds is None
    assert failed.rtf is None


def test_every_result_names_the_device_actually_used(engine):
    assert {r.device for r in _run()} == {"cpu"}


# --------------------------------------------------------------------------- #
# N. The protected uploads folder is never written to
# --------------------------------------------------------------------------- #
def test_the_evaluation_leaves_the_protected_sources_byte_identical(engine, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    for voice in cbx.REFERENCE_VOICES.values():
        (uploads / voice.source_name).write_bytes(b"protected " + voice.voice_id.encode())
    before = {p.name: p.read_bytes() for p in uploads.iterdir()}
    _run()
    after = {p.name: p.read_bytes() for p in uploads.iterdir()}
    assert after == before


def test_the_evaluation_adds_no_file_to_the_protected_folder(engine, tmp_path):
    uploads = _made(tmp_path / "uploads")
    _run()
    assert all(p.suffix == ".mp3" for p in uploads.iterdir())


def test_the_generator_names_no_write_target_inside_the_protected_folder():
    src = (TTS_DIR / "generate_voice_samples.py").read_text(encoding="utf-8")
    assert "Chatterbox-Voice-Uploads" not in src
    assert "protected_uploads_dir" not in src


# --------------------------------------------------------------------------- #
# O. No voice is registered — the maintainer has not listened yet
# --------------------------------------------------------------------------- #
def test_phase_nine_registers_no_chatterbox_voice():
    assert [v for v in voice_registry.VOICES if v.backend == "chatterbox"] == []
    assert len(voice_registry.VOICES) == 12


def test_running_the_evaluation_registers_nothing(engine):
    before = list(voice_registry.VOICES)
    _run()
    assert list(voice_registry.VOICES) == before


def test_the_default_voice_is_untouched_by_phase_nine():
    assert voice_registry.DEFAULT_VOICE_LABEL == "Steffan — en-US Male (default)"


# --------------------------------------------------------------------------- #
# P/Q. Phase 10 has not started
# --------------------------------------------------------------------------- #
PHASE_TEN_MODULES = (
    "epub2tts_gui.py",
    "batch_convert.py",
    "kokoro_synth.py",
    "epub2tts_edge/runner.py",
)


@pytest.mark.parametrize("filename", PHASE_TEN_MODULES)
def test_no_chatterbox_dispatch_reached_an_integration_module(filename):
    tree = _tree(TTS_DIR / filename)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    assert not any("chatterbox" in str(n).lower() for n in names), \
        f"{filename} references Chatterbox — that is Phase 10"


def test_the_gui_voice_dropdown_still_offers_only_the_twelve_labels():
    assert len(voice_registry.display_labels()) == 12


def test_the_generator_is_the_only_production_file_phase_nine_widened():
    """The evaluation is a dev-only path: nothing the app runs may import it."""
    offenders = []
    for path in (REPO_ROOT / "scripts").rglob("*.py"):
        if path.name == "generate_voice_samples.py":
            continue
        if "generate_voice_samples" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == []


# --------------------------------------------------------------------------- #
# The manifest — one manifest, extended, not a second competing one
# --------------------------------------------------------------------------- #
def test_the_manifest_records_the_conditional_cache_path():
    import inspect

    src = inspect.getsource(cbx._record_manifest)
    assert "conditionals_path" in src


def test_the_manifest_lives_under_the_ignored_runtime_tree():
    assert cbx.reference_clips_dir().is_relative_to(
        REPO_ROOT / "files" / "runtime-data")


def test_the_evaluation_writes_no_manifest_of_its_own():
    """Phase 8 already established one; a second would compete with it."""
    src = (TTS_DIR / "generate_voice_samples.py").read_text(encoding="utf-8")
    assert "manifest" not in src.lower()
