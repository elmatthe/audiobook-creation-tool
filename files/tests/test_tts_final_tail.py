"""ACT v0.7.0 P01A -- the end of every narration MP3 (owner decisions Q1-Q3).

Policy under test (plan Section 5.1): no deliberate closing pause, at most 300 ms of trailing near-silence, the
pacing *between* rendered content unchanged, and no final phoneme, breath, decay or transient cut.

Every route is driven through its real production boundary with synthetic PCM, offline and deterministically:

* the GUI's own engine converters (``convert_with_kokoro`` / ``_chatterbox`` / ``_qwen3`` / ``_edge_engine``) with
  the timing values the panel freezes from the voice registry;
* the Edge folder worker exactly as the panel calls it (``batch_convert.convert_single_pdf``);
* the shipped voice-sample helper (``generate_voice_samples._synthesize_for_voice``), the engines' own defaults
  and the Edge command line.

Only the model or network call is replaced. The PCM is captured at the last in-process hand-off to the one final
MP3 encode (pydub's ``export`` for Kokoro, Chatterbox and both Edge routes; the documented ``encoder`` seam for
Qwen3), so prefixes and internal gaps are compared sample for sample. Two tests also decode a real encode with the
pinned FFmpeg.

The trailing-silence measurement is this module's own oracle, not production code: 10 ms windows, every channel
separately, a window counts as sound when its RMS **or** its peak reaches -60 dBFS, and the latest channel wins. The
P01A calibration (``files/dev-work/act070-remediation/audio/``) chose it; the -50 dBFS candidate cut real sounds.

Tests that encode the new policy failed on the v0.6.6 code; P01A ledgered them with the plan's narrow strict marker
(``files/dev-work/act070-remediation/audio/red-ledger.json``), P01B removed the 23 local-engine markers and P01C the
14 Edge ones. No temporary marker is left: every node here must pass normally.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled

RATE = 24000
WINDOW_MS = 10
THRESHOLD_DBFS = -60.0
BUDGET_MS = 300  # Q1: at most this much trailing near-silence
KEEP_MS = 150  # Section 5.1: never keep less than this after the last sound when a long suffix is shortened

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair")


def _punkt_available() -> bool:
    import nltk

    try:
        nltk.data.find("tokenizers/punkt")
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        return False
    return True


# Never downloads: a machine without the tokenizer data skips the Edge direct cases instead.
needs_edge_direct = pytest.mark.skipif(not (ffmpeg_utils.have_ffmpeg() and _punkt_available()),
                                       reason="requires ffmpeg and the installed NLTK Punkt data")


# --------------------------------------------------------------------------- #
# The measurement oracle
# --------------------------------------------------------------------------- #
def _frames(pcm) -> np.ndarray:
    arr = np.asarray(pcm)
    if arr.dtype == np.int16:
        arr = arr.astype(np.float64) / 32768.0
    return arr.reshape(len(arr), -1).astype(np.float64)


def last_sound(pcm, rate: int = RATE, threshold_dbfs: float = THRESHOLD_DBFS, *, use_peak: bool = True) -> int:
    """Sample index just after the last window on *any* channel whose RMS or peak reaches the threshold (0: none)."""
    x = _frames(pcm)
    n = len(x)
    if n == 0:
        return 0
    win = max(1, int(round(rate * WINDOW_MS / 1000)))
    starts = np.arange(0, n, win)
    counts = np.diff(np.append(starts, n))
    level = 10 ** (threshold_dbfs / 20)
    latest = 0
    for ch in range(x.shape[1]):  # every channel on its own: a downmix can cancel a quiet channel
        col = x[:, ch]
        active = np.sqrt(np.add.reduceat(col * col, starts) / counts) >= level
        if use_peak:
            active |= np.maximum.reduceat(np.abs(col), starts) >= level
        hits = np.nonzero(active)[0]
        if hits.size:
            latest = max(latest, int(starts[hits[-1]] + counts[hits[-1]]))
    return latest


def trailing_quiet_ms(pcm, rate: int = RATE, **kw) -> float:
    return (len(_frames(pcm)) - last_sound(pcm, rate, **kw)) * 1000.0 / rate


def _assert_bounded_tail(pcm, rate: int, case: str) -> None:
    tail = trailing_quiet_ms(pcm, rate)
    assert tail <= BUDGET_MS, f"closing tail is {tail:.1f} ms, over the {BUDGET_MS} ms budget ({case})"


def _assert_nothing_added(out: np.ndarray, expected: np.ndarray, case: str) -> None:
    extra = len(out) - len(expected)
    assert extra == 0, f"{extra * 1000 / RATE:.1f} ms of closing pause was added after the last sound ({case})"


# --------------------------------------------------------------------------- #
# Synthetic sound
# --------------------------------------------------------------------------- #
def _samples(seconds: float) -> int:
    return int(round(RATE * seconds))


def _tone(seconds: float, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(_samples(seconds)) / RATE)).astype(np.float32)


def _noise(seconds: float, rms_dbfs: float, seed: int, *, highpass=False, lowpass=False) -> np.ndarray:
    x = np.random.default_rng(seed).standard_normal(_samples(seconds))
    if highpass:  # fricative-like
        x = np.diff(x, prepend=0.0)
    if lowpass:  # breath-like
        x = np.convolve(x, np.ones(24) / 24, mode="same")
    return (x / np.sqrt(np.mean(x * x)) * 10 ** (rms_dbfs / 20)).astype(np.float32)


def _fade(x: np.ndarray, fraction: float) -> np.ndarray:
    n = int(len(x) * fraction)
    out = x.copy()
    if n:
        out[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return out


def _zeros(seconds: float) -> np.ndarray:
    return np.zeros(_samples(seconds), dtype=np.float32)


def _final_sound(name: str) -> tuple[np.ndarray, int]:
    """(what follows the last word, how many of its samples a fix must keep) for one kind of ending."""
    if name == "quiet_fricative":  # 180 ms at -62 dBFS, the last 40 % fading to nothing
        sound = _fade(_noise(0.18, -62, seed=1, highpass=True), 0.4)
        return np.concatenate([sound, _zeros(1.0)]), len(sound)
    if name == "breath":  # 80 ms after the word, 250 ms at -58 dBFS
        sound = np.concatenate([_zeros(0.08), _fade(_noise(0.25, -58, seed=2, lowpass=True), 0.3)])
        return np.concatenate([sound, _zeros(1.0)]), len(sound)
    if name == "transient":  # a 2 ms click peaking at -55 dBFS, 200 ms after the word (RMS alone misses it)
        click = np.zeros(_samples(0.002), dtype=np.float32)
        click[0], click[1] = 10 ** (-55 / 20), -0.6 * 10 ** (-55 / 20)
        sound = np.concatenate([_zeros(0.2), click])
        return np.concatenate([sound, _zeros(1.0)]), len(sound)
    if name == "reverb":  # room decay from -20 dBFS, 60 dB per 400 ms
        t = np.arange(_samples(0.4)) / RATE
        sound = (0.1 * np.sin(2 * np.pi * 220 * t) * 10 ** (-3 * t / 0.4)).astype(np.float32)
        return np.concatenate([sound, _zeros(1.0)]), len(sound)
    if name == "natural_tail":  # an engine's own inaudible 500 ms floor: shorten it, but keep KEEP_MS of it
        return _noise(0.5, -85, seed=5), _samples(KEEP_MS / 1000)
    if name == "internal_silence":  # a long pause *inside* the final chunk, then the real last word
        sound = np.concatenate([_zeros(1.5), _tone(0.4, freq=330.0)])
        return sound, len(sound)
    raise ValueError(name)


SOUNDS = ["quiet_fricative", "breath", "transient", "reverb", "natural_tail", "internal_silence"]


def _q16(x: np.ndarray) -> np.ndarray:
    """float -> 16-bit exactly as soundfile writes the WAV every route hands to its encoder."""
    buf = io.BytesIO()
    sf.write(buf, x, RATE, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return sf.read(buf, dtype="int16", always_2d=True)[0]


def _assert_keeps(out: np.ndarray, expected: np.ndarray) -> None:
    """``out`` begins with exactly ``expected``: every speech sample, internal gap and final sound, unaltered."""
    exp = expected if expected.dtype == np.int16 else _q16(expected)
    exp = exp.reshape(len(exp), -1)
    assert out.shape[1] == exp.shape[1], f"channels changed: {out.shape[1]} != {exp.shape[1]}"
    assert len(out) >= len(exp), f"audio was cut: {len(out)} samples kept of {len(exp)}"
    np.testing.assert_array_equal(out[:len(exp)], exp)


def _only_encode(captures: list) -> SimpleNamespace:
    # Not an assert: a route that encodes twice (an extra lossy generation) must fail, never pass as an xfail.
    if len(captures) != 1:
        raise RuntimeError(f"expected exactly one final MP3 encode, saw {len(captures)}")
    return captures[0]


def _decode(path: Path) -> np.ndarray:
    """The finished MP3 decoded by ACT's own FFmpeg, every channel kept."""
    channels = int(subprocess.run(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-show_entries", "stream=channels", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()[0])
    raw = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-i", str(path), "-f", "f32le", "-acodec",
                          "pcm_f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, channels)


# --------------------------------------------------------------------------- #
# Fixtures shared by every route
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _contained_temp(monkeypatch, tmp_path):
    """Engines make scratch files with tempfile; keep them inside the test's own folder."""
    scratch = tmp_path / "sys-tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))


@pytest.fixture
def mp3_encodes(monkeypatch):
    """Every final MP3 encode a pydub route performs, as the exact PCM it was handed.

    Other formats (Edge direct's lossless FLAC intermediates) run for real. ``real_encode = True`` also performs
    the real MP3 encode, for the tests that decode the finished file.
    """
    from pydub import AudioSegment

    ffmpeg_utils.configure_pydub()
    real_export = AudioSegment.export

    class Captures(list):
        real_encode = False

    captures = Captures()

    def capture(self, out_f=None, format="mp3", **kwargs):
        if format != "mp3":
            return real_export(self, out_f, format=format, **kwargs)
        pcm = np.frombuffer(self.raw_data, dtype=np.int16).reshape(-1, self.channels).copy()
        captures.append(SimpleNamespace(pcm=pcm, rate=self.frame_rate, kwargs=kwargs))
        if captures.real_encode:
            return real_export(self, out_f, format=format, **kwargs)
        Path(out_f).write_bytes(b"ID3 placeholder")
        return None

    monkeypatch.setattr(AudioSegment, "export", capture)
    return captures


def _text_for(splitter, n: int) -> str:
    """Plain sentences that the engine's own splitter turns into exactly ``n`` chunks."""
    for k in range(1, 4000):
        text = " ".join(f"Narration sentence number {i} goes right here." for i in range(k))
        got = len(splitter(text))
        if got == n:
            return text
        if got > n:
            break
    raise RuntimeError(f"could not build text for {n} chunks")


def _frozen_params(voice_id: str, run_directory: Path | None = None) -> dict:
    """The run options the TTS panel freezes when Create is pressed (``epub2tts_gui``, start of a run)."""
    from tts import epub2tts_gui as gui
    from tts import voice_registry as vr

    entry = next(v for v in vr.VOICES if v.voice_id == voice_id)
    preset = entry.timing_preset
    pause_kw: dict = {}
    if entry.backend == "edge":
        pause_kw = {
            "sentencepause": int(preset["sentencepause"]),
            "paragraphpause": int(preset["paragraphpause"]),
            "title_trailing_pause": int(preset["title_ms"]),
            "chapter_trailing_pause": int(preset["chapter_ms"]),
            "end_of_book_pause": int(preset["end_pause"]),
            "trim_tts_padding": bool(preset["trim_edge_chunks"]),
            "trim_silence_db": float(preset["trim_dbfs"]),
        }
    params = gui.freeze_tts_options(
        speaker=voice_id, backend=entry.backend, voice_id=voice_id, label=entry.display_label, rate="+0%",
        resume=False, overwrite=False,
        bitrate="192k", workers=1, kokoro_speed=1.0, end_pause=int(preset["end_pause"]),
        paragraph_pause=int(preset["paragraphpause"]), pause_kw=pause_kw)
    params["run_directory"] = run_directory
    return params


# --------------------------------------------------------------------------- #
# Local-engine harness (the model call is the only thing replaced)
# --------------------------------------------------------------------------- #
LOCAL_VOICES = {"kokoro": "af_heart", "chatterbox": "chatterbox-male-1", "qwen3": "qwen3-aiden"}


@pytest.fixture
def local_engine(monkeypatch, tmp_path, mp3_encodes):
    import tts.chatterbox_synth as cbx
    import tts.kokoro_synth as ks
    from tts import epub2tts_gui as gui
    from tts import qwen3_runtime as rt
    from tts import qwen3_synth as qs

    pending: list[np.ndarray] = []
    qwen_encodes: list = []
    state = {"rendered": 0, "worker_done": False, "fail_worker": False}

    def take() -> np.ndarray:
        if not pending:
            raise RuntimeError("the engine asked for more chunks than the test planned")
        state["rendered"] += 1
        return pending.pop(0)

    # Kokoro: the pipeline is the model.
    class _Pipeline:
        def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
            arr = take()
            if arr.size:
                yield ("graphemes", "phonemes", arr)

    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: _Pipeline())

    # Chatterbox: the model and its conditioning; one rendered chunk per call.
    monkeypatch.setattr(cbx, "_runtime_root", lambda: tmp_path / "runtime-data")
    monkeypatch.setattr(cbx, "_get_model", lambda device=None: SimpleNamespace(sr=RATE))
    monkeypatch.setattr(cbx, "load_conditionals", lambda model, voice_id, log=print, device=None: None)
    monkeypatch.setattr(cbx, "_synthesize_chunk", lambda model, chunk, cancel_check=None, log=print: take())

    # Qwen3: the worker process writes chunk WAVs where the real one does; the real collector reads them back.
    monkeypatch.setattr(rt, "runtime_dir", lambda: tmp_path / "qwen-runtime")

    def run_worker(job, job_dir, *, on_chunk=None, **_kw):
        if state["fail_worker"]:
            return qs.WorkerRun(terminal={"event": "failed", "stage": "generate", "index": 0,
                                          "message": "synthetic failure", "oom": False},
                                chunk_events=[], loaded={}, returncode=2)
        out = Path(job_dir) / "chunks"
        out.mkdir(parents=True, exist_ok=True)
        events = []
        for i, _chunk in enumerate(job["chunks"]):
            name = f"chunk-{i + 1:04d}.wav"
            sf.write(str(out / name), take(), RATE, subtype="FLOAT")
            events.append({"event": "chunk", "index": i, "wav": name, "sample_rate": RATE})
            if on_chunk is not None:
                on_chunk(i + 1, len(job["chunks"]))
        state["worker_done"] = True
        return qs.WorkerRun(terminal={"event": "done"}, chunk_events=events, loaded={}, returncode=0)

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        data, rate = sf.read(str(wav), dtype="int16", always_2d=True)
        qwen_encodes.append(SimpleNamespace(pcm=data, rate=rate, kwargs={"bitrate": bitrate}))
        Path(mp3).write_bytes(b"ID3 placeholder")

    def snapshot(voice, job_dir):  # the bundled recording itself is never read here
        path = Path(job_dir) / "reference.wav"
        sf.write(str(path), _tone(0.5), RATE)
        return path

    monkeypatch.setattr(qs, "run_worker", run_worker)
    monkeypatch.setattr(qs, "snapshot_reference", snapshot)
    monkeypatch.setattr(rt, "load_transcript",
                        lambda voice_id, **_k: rt.Transcript(ok=True, text="Synthetic reference words.", reason=""))
    defaults = qs.qwen3_file_to_mp3.__kwdefaults__  # the existing offline seams, applied for every caller
    monkeypatch.setitem(defaults, "availability", lambda v: (True, "ok"))
    monkeypatch.setitem(defaults, "python", Path(sys.executable))
    monkeypatch.setitem(defaults, "script", tmp_path / "unused-worker.py")
    monkeypatch.setitem(defaults, "jobs_root", tmp_path / "qwen-jobs")
    monkeypatch.setitem(defaults, "env", {})
    monkeypatch.setitem(defaults, "encoder", encoder)

    splitters = {"kokoro": ks.split_into_chunks, "chatterbox": cbx.split_for_chatterbox, "qwen3": qs.plan_chunks}
    converters = {"kokoro": gui.convert_with_kokoro, "chatterbox": gui.convert_with_chatterbox,
                  "qwen3": gui.convert_with_qwen3}

    class Harness:
        encodes = mp3_encodes
        root = tmp_path

        @staticmethod
        def text(engine: str, n: int) -> str:
            return _text_for(splitters[engine], n)

        @staticmethod
        def queue(renders: list[np.ndarray]) -> None:
            pending[:] = [np.asarray(r, dtype=np.float32) for r in renders]

        @staticmethod
        def drained() -> None:
            if pending:
                raise RuntimeError(f"the engine left {len(pending)} planned chunk(s) unrendered")

        @staticmethod
        def encode_for(engine: str) -> SimpleNamespace:
            return _only_encode(qwen_encodes if engine == "qwen3" else mp3_encodes)

        @staticmethod
        def any_encode() -> bool:
            return bool(mp3_encodes or qwen_encodes)

        state_ = state

        def destination(self, name: str = "book.mp3") -> Path:
            folder = tmp_path / "out"
            folder.mkdir(exist_ok=True)  # the panel's converters create it; direct callers find it existing
            return folder / name

        def run(self, engine: str, renders: list[np.ndarray], *, voice_id: str | None = None, cancel_check=None):
            source = tmp_path / "book.txt"
            source.write_text(self.text(engine, len(renders)), encoding="utf-8")
            self.queue(renders)
            params = _frozen_params(voice_id or LOCAL_VOICES[engine])
            item = {"source": source, "destination": self.destination(), "item_id": "item-1"}
            converters[engine](item, params, None, lambda _m: None, cancel_check or (lambda: False))
            self.drained()
            capture = self.encode_for(engine)
            return capture.pcm, capture.rate, params, capture

    return Harness()


def _local_case(engine: str, case: str, gap_ms: int):
    """(renders, expected kept prefix, exact) for one closing-tail case; ``exact``: nothing may follow it."""
    gap = _zeros(gap_ms / 1000)
    t1, t2, t3 = _tone(0.9, 220.0), _tone(0.7, 262.0), _tone(0.6, 294.0)
    if case == "single":  # a 40 ms natural ending is already short: keep it, add nothing
        only = np.concatenate([_tone(1.2), _zeros(0.04)])
        return [only], only, True
    if case in ("multiple", "clone"):
        return [t1, t2, t3], np.concatenate([t1, gap, t2, gap, t3]), True
    if case == "skipped_final":  # the last planned chunk renders nothing: the last *rendered* one ends the book
        return [t1, t2, np.zeros(0, dtype=np.float32)], np.concatenate([t1, gap, t2]), True
    sound, keep = _final_sound(case)
    return [t1, np.concatenate([t2, sound])], np.concatenate([t1, gap, t2, sound[:keep]]), False


# --------------------------------------------------------------------------- #
# A. The oracle itself (it decides every verdict below, so it is proved first)
# --------------------------------------------------------------------------- #
def test_the_oracle_measures_digital_silence_to_the_window():
    assert trailing_quiet_ms(np.concatenate([_tone(1.0), _zeros(0.25)])) == pytest.approx(250.0, abs=WINDOW_MS)
    assert trailing_quiet_ms(_tone(1.0)) == 0.0
    assert trailing_quiet_ms(_zeros(0.5)) == pytest.approx(500.0)


def test_the_oracle_takes_the_latest_channel_and_never_downmixes():
    speech = _tone(1.0)
    right_tail = _fade(_noise(0.25, -58, seed=3, highpass=True), 0.3)
    stereo = np.stack([np.concatenate([speech, _zeros(1.25)]),
                       np.concatenate([speech, right_tail, _zeros(1.0)])], axis=1)
    assert trailing_quiet_ms(stereo) <= 1000.0 + 5 * WINDOW_MS  # the right channel's tail counts (fade-out aside)
    tail = _noise(0.25, -55, seed=4, highpass=True)
    antiphase = np.stack([np.concatenate([speech, tail, _zeros(1.0)]),
                          np.concatenate([speech, -tail, _zeros(1.0)])], axis=1)
    assert trailing_quiet_ms(antiphase) <= 1000.0 + WINDOW_MS
    assert trailing_quiet_ms(antiphase.mean(axis=1)) >= 1240.0  # what a mono downmix would wrongly report


def test_the_oracle_peak_guard_sees_a_click_that_rms_alone_misses():
    sound, _keep = _final_sound("transient")
    pcm = np.concatenate([_tone(1.0), sound])
    assert trailing_quiet_ms(pcm) <= 1000.0 + WINDOW_MS
    assert trailing_quiet_ms(pcm, use_peak=False) >= 1190.0


@needs_ffmpeg
def test_the_final_encode_is_gapless_so_codec_padding_cannot_spend_the_budget(tmp_path):
    """Section 5.1 codec facts with the production encode contract, at every bitrate the panel offers."""
    import tts.kokoro_synth as ks

    ffmpeg_utils.configure_pydub()
    speech = _tone(2.0)
    for bitrate in ("128k", "192k", "320k"):
        out = tmp_path / f"enc-{bitrate}.mp3"
        ks._export_mp3(speech, RATE, str(out), bitrate)
        decoded = _decode(out)
        assert abs(len(decoded) - len(speech)) <= 2 * 576, (bitrate, len(decoded))  # within two MPEG-2 frames
        assert trailing_quiet_ms(decoded) <= 50.0, bitrate


# --------------------------------------------------------------------------- #
# B. Timing values: registry presets, the panel's fallback and the Edge command line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", [
    "edge",  # P01C fixed the Edge routes; with P01B's local engines no ACT070 marker is left
    "kokoro",
    "chatterbox",
    "qwen3",
])
def test_no_registry_voice_carries_a_closing_pause(backend):
    from tts import voice_registry as vr

    voices = [v for v in vr.VOICES if v.backend == backend]
    if not voices:
        raise RuntimeError(f"no {backend} voices registered")
    offenders = {v.voice_id: v.timing_preset.get("end_pause") for v in voices
                 if int(v.timing_preset.get("end_pause", "0")) != 0}
    assert not offenders, f"{backend} voices still freeze a closing pause: {offenders}"


def test_the_panels_fallback_preset_carries_no_closing_pause():
    from tts import epub2tts_gui as gui

    assert int(gui._default_timing_preset().get("end_pause", "0")) == 0


def test_the_edge_command_line_default_carries_no_closing_pause(monkeypatch):
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    seen: dict = {}
    monkeypatch.setattr(sys, "argv", ["epub2tts-edge", "book.txt", "--format", "mp3"])
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(runner, "run_conversion_job", lambda *a, **kw: seen.update(kw))
    engine.main()
    if not seen:
        raise RuntimeError("the command line never reached run_conversion_job")
    assert seen.get("end_of_book_pause", 0) == 0


# --------------------------------------------------------------------------- #
# C. Local engines through the panel's converters
# --------------------------------------------------------------------------- #
_LOCAL_TAIL_CASES = (
    [pytest.param("kokoro", c, id=f"kokoro-{c}")
     for c in ("single", "multiple", "skipped_final", "natural_tail",
               "quiet_fricative", "breath", "transient", "reverb")]
    + [pytest.param("chatterbox", c, id=f"chatterbox-{c}")
       for c in ("single", "multiple", "skipped_final", "natural_tail")]
    + [pytest.param("qwen3", c, id=f"qwen3-{c}")
       for c in ("single", "multiple", "clone", "natural_tail")]
)


@pytest.mark.parametrize("engine, case", _LOCAL_TAIL_CASES)
def test_a_local_engine_ends_without_a_closing_pause(local_engine, engine, case):
    voice = "qwen3-male-2" if case == "clone" else None
    params = _frozen_params(voice or LOCAL_VOICES[engine])
    renders, expected, exact = _local_case(engine, case, int(params["paragraph_pause"]))
    out, rate, _params, _cap = local_engine.run(engine, renders, voice_id=voice)
    _assert_keeps(out, expected)
    if exact:
        _assert_nothing_added(out, _q16(expected), f"{engine}-{case}")
    _assert_bounded_tail(out, rate, f"{engine}-{case}")


@pytest.mark.parametrize("engine", ["kokoro", "chatterbox", "qwen3"])
@pytest.mark.parametrize("sound", SOUNDS)
def test_a_local_engine_keeps_every_final_sound_and_internal_pause(local_engine, engine, sound):
    """Passes today; a trimmer that cuts a quiet ending or an internal pause must fail here."""
    params = _frozen_params(LOCAL_VOICES[engine])
    renders, expected, _exact = _local_case(engine, sound, int(params["paragraph_pause"]))
    out, rate, _params, capture = local_engine.run(engine, renders)
    _assert_keeps(out, expected)
    assert rate == RATE and out.shape[1] == 1
    assert capture.kwargs.get("bitrate") == params["bitrate"]  # the run's own bitrate reaches the one encode


@pytest.mark.parametrize("engine", ["kokoro", "chatterbox", "qwen3"])
def test_a_local_engine_keeps_the_exact_pause_between_rendered_chunks(local_engine, engine):
    params = _frozen_params(LOCAL_VOICES[engine])
    renders, expected, _exact = _local_case(engine, "multiple", int(params["paragraph_pause"]))
    out, _rate, _params, _cap = local_engine.run(engine, renders)
    _assert_keeps(out, expected)  # chunk 1, the exact gap, chunk 2, the exact gap, chunk 3


@pytest.mark.parametrize("engine, exc", [("kokoro", RuntimeError), ("chatterbox", "ChatterboxUnavailable")])
def test_a_local_engine_with_no_rendered_audio_publishes_nothing(local_engine, engine, exc):
    import tts.chatterbox_synth as cbx

    expected_exc = getattr(cbx, exc) if isinstance(exc, str) else exc
    with pytest.raises(expected_exc):
        local_engine.run(engine, [np.zeros(0, dtype=np.float32)])
    assert not local_engine.any_encode() and not local_engine.destination().exists()


def test_a_failed_qwen3_worker_publishes_nothing(local_engine):
    from tts import qwen3_synth as qs

    local_engine.state_["fail_worker"] = True
    with pytest.raises(qs.Qwen3Failed):
        local_engine.run("qwen3", [_tone(0.5)])
    assert not local_engine.any_encode() and not local_engine.destination().exists()


@pytest.mark.parametrize("engine", ["kokoro", "chatterbox"])
def test_cancelling_before_the_final_chunk_publishes_nothing(local_engine, engine):
    with pytest.raises(ConversionCancelled):
        local_engine.run(engine, [_tone(0.5), _tone(0.5, 330.0)],
                         cancel_check=lambda: local_engine.state_["rendered"] >= 1)
    assert not local_engine.any_encode() and not local_engine.destination().exists()


def test_cancelling_a_finished_qwen3_run_leaves_the_existing_file_untouched(local_engine):
    destination = local_engine.destination()
    destination.write_bytes(b"OLD GOOD FILE")
    with pytest.raises(ConversionCancelled):
        local_engine.run("qwen3", [_tone(0.5)], cancel_check=lambda: local_engine.state_["worker_done"])
    assert destination.read_bytes() == b"OLD GOOD FILE" and not local_engine.any_encode()


# --------------------------------------------------------------------------- #
# D. Direct callers: engine defaults and the shipped voice-sample helper
# --------------------------------------------------------------------------- #
def test_kokoro_called_with_its_own_defaults_adds_no_closing_pause(local_engine):
    """A caller that passes no timing at all (``kokoro_file_to_mp3``'s own defaults) gets the product policy too."""
    import tts.kokoro_synth as ks

    source = local_engine.root / "direct.txt"
    source.write_text(local_engine.text("kokoro", 2), encoding="utf-8")
    t1, t2 = _tone(0.8), _tone(0.6, 330.0)
    local_engine.queue([t1, t2])
    ks.kokoro_file_to_mp3(str(source), str(local_engine.destination()), voice_id="af_heart", log=lambda _m: None)
    local_engine.drained()
    out = local_engine.encode_for("kokoro").pcm
    expected = np.concatenate([t1, _zeros(0.05), t2])  # the default 50 ms between chunks is internal pacing (Q2)
    _assert_keeps(out, expected)
    _assert_nothing_added(out, _q16(expected), "kokoro-default-args")


def _sample_voice(voice_id: str):
    from tts import voice_registry as vr

    return next(v for v in vr.VOICES if v.voice_id == voice_id)


def test_the_sample_helpers_kokoro_route_adds_nothing(local_engine):
    from tts import generate_voice_samples as gvs

    speech = _tone(1.1)
    local_engine.queue([speech])
    gvs._synthesize_for_voice(_sample_voice("af_heart"), "A short sample line.", local_engine.destination())
    local_engine.drained()
    out = local_engine.encode_for("kokoro").pcm
    _assert_keeps(out, speech)
    _assert_nothing_added(out, _q16(speech), "sample-helper-kokoro")


@pytest.mark.parametrize("voice_id, chunks", [
    pytest.param("chatterbox-female-1", 2, id="chatterbox_long_text"),
    pytest.param("qwen3-ryan", 1, id="qwen3"),
])
def test_the_sample_helpers_local_routes_add_no_closing_pause(local_engine, voice_id, chunks):
    """``generate_voice_samples`` calls the file converters with their own defaults (3000 ms end at v0.6.6)."""
    from tts import generate_voice_samples as gvs

    engine = _sample_voice(voice_id).backend
    text = local_engine.text(engine, chunks)
    if engine == "chatterbox":
        from tts.chatterbox_synth import CHATTERBOX_MAX_CHUNK_CHARS

        if len(text) <= CHATTERBOX_MAX_CHUNK_CHARS:
            raise RuntimeError("the long-text sample route needs text past the one-shot ceiling")
    renders = [_tone(0.8), _tone(0.6, 330.0)][:chunks]
    local_engine.queue(renders)
    gvs._synthesize_for_voice(_sample_voice(voice_id), text, local_engine.destination(), log=lambda _m: None)
    local_engine.drained()
    out = local_engine.encode_for(engine).pcm
    gap = _zeros(0.05 if engine == "chatterbox" else 0.7)  # each converter's own default between-chunk pause
    expected = renders[0] if chunks == 1 else np.concatenate([renders[0], gap, renders[1]])
    _assert_keeps(out, expected)
    _assert_nothing_added(out, _q16(expected), f"sample-helper-{engine}")


@needs_ffmpeg
def test_the_published_kokoro_mp3_decodes_with_a_bounded_tail(local_engine):
    """The acceptance measurement itself: re-decode the real finished MP3 with the pinned FFmpeg."""
    local_engine.encodes.real_encode = True
    sound, _keep = _final_sound("natural_tail")
    out, _rate, _params, _cap = local_engine.run("kokoro", [_tone(0.9), np.concatenate([_tone(0.7, 330.0), sound])])
    decoded = _decode(local_engine.destination())
    assert abs(len(decoded) - len(out)) <= 2 * 576
    _assert_bounded_tail(decoded, RATE, "kokoro-decoded-mp3")


# --------------------------------------------------------------------------- #
# E. Edge direct (rich chapter/paragraph/sentence assembly) through the panel
# --------------------------------------------------------------------------- #
@pytest.fixture
def edge_direct(monkeypatch, tmp_path, mp3_encodes):
    from tts import epub2tts_gui as gui
    from tts.epub2tts_edge import epub2tts_edge as engine
    from tts.epub2tts_edge import runner

    lines: dict[str, np.ndarray] = {}
    failing: set[str] = set()
    spoken: list[str] = []

    def write(text: str, filename: str) -> None:
        if text in failing:
            raise ConnectionError("synthetic network failure")
        if text not in lines:
            raise LookupError(f"the test has no audio for Edge text {text!r}")
        spoken.append(text)
        sf.write(filename, lines[text], RATE, format="WAV", subtype="PCM_16")  # decoded losslessly by ffmpeg

    async def parallel(sentences, speakers, filenames):
        for text, filename in zip(sentences, filenames):
            write(text, filename)

    monkeypatch.setattr(engine, "run_edgespeak", lambda sentence, speaker, filename: write(sentence, filename))
    monkeypatch.setattr(engine, "parallel_edgespeak", parallel)
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)

    class Harness:
        encodes = mp3_encodes

        @staticmethod
        def destination() -> Path:
            return tmp_path / "TTS-Audiobook-1" / "book.mp3"

        def run(self, text: str, audio: dict[str, np.ndarray], *, voice_id="en-US-SteffanNeural",
                cancel_check=None, fail: tuple[str, ...] = (), defaults: bool = False,
                pause_kw: dict | None = None):
            lines.clear()
            lines.update(audio)
            failing.clear()
            failing.update(fail)
            source = tmp_path / "book.txt"
            source.write_text(text, encoding="utf-8")
            params = _frozen_params(voice_id, tmp_path / "TTS-Audiobook-1")
            params["pause_kw"].update(pause_kw or {})  # a run whose frozen values differ from the voice preset
            if defaults:  # a direct caller of the engine's runner that passes no pause values at all
                out_dir = tmp_path / "runner-out"
                runner.run_conversion_job(str(source), output_dir=str(out_dir), speaker=voice_id, audio_format="mp3")
            else:
                gui.convert_with_edge_engine({"source": source, "destination": self.destination()}, params, None,
                                             cancel_check or (lambda: False))
            capture = _only_encode(mp3_encodes)
            return capture.pcm, capture.rate, params

        spoken_ = spoken

    return Harness()


def _seg(x: np.ndarray):
    from pydub import AudioSegment

    pcm = _q16(x)
    return AudioSegment(data=pcm.tobytes(), sample_width=2, frame_rate=RATE, channels=pcm.shape[1])


def _edge_direct_expected(book: list[dict], audio: dict[str, np.ndarray], pk: dict) -> np.ndarray:
    """The panel's Edge assembly up to the end of the last word, rebuilt with pydub's own arithmetic.

    Every sentence pause, paragraph pause, title pause and *between*-chapter pause is in here; only what follows
    the final word is left out, because that is the part Q1 changes.
    """
    from pydub import AudioSegment

    chapters = []
    for ci, chapter in enumerate(book):
        last_chapter = ci == len(book) - 1
        parts = []
        for pi, paragraph in enumerate(chapter["paragraphs"]):
            combined = AudioSegment.empty()
            if pi == 0 and chapter["title"]:
                combined += _seg(audio[chapter["title"]])
                if pk["title_trailing_pause"] > 0:
                    combined += AudioSegment.silent(pk["title_trailing_pause"])
            for si, sentence in enumerate(paragraph):
                final_word = last_chapter and pi == len(chapter["paragraphs"]) - 1 and si == len(paragraph) - 1
                pause = pk["sentencepause"] if si < len(paragraph) - 1 else pk["paragraphpause"]
                merged = AudioSegment.empty()
                merged += _seg(audio[sentence])
                combined += merged if final_word else merged + AudioSegment.silent(duration=pause)
            parts.append(combined)
        if not last_chapter and pk["chapter_trailing_pause"] > 0:
            parts[-1] = parts[-1] + AudioSegment.silent(pk["chapter_trailing_pause"])
        joined = AudioSegment.empty()
        for part in parts:
            joined += part
        chapters.append(joined)
    whole = AudioSegment.empty()
    for joined in chapters:
        whole += joined
    return np.frombuffer(whole.raw_data, dtype=np.int16).reshape(-1, 1).copy()


def _edge_book(case: str):
    """(source text, parsed structure, audio for every spoken text) for one Edge direct case."""
    a1, a2 = "Alpha one is here.", "Alpha two follows."
    b1, b2, c1 = "Bravo one is here.", "Bravo two follows.", "Charlie one ends the book."
    audio = {a1: _tone(0.5, 220.0), a2: _tone(0.45, 247.0), b1: _tone(0.4, 262.0), b2: _tone(0.35, 294.0),
             c1: _tone(0.6, 330.0), "One": _tone(0.3, 392.0), "Two": _tone(0.25, 440.0)}
    if case == "single_paragraph":
        return f"{a1}\n", [{"title": None, "paragraphs": [[a1]]}], audio
    if case == "multi_chapter":
        text = f"# One\n{a1} {a2}\n{b1} {b2}\n# Two\n{c1}\n"
        return text, [{"title": "One", "paragraphs": [[a1, a2], [b1, b2]]},
                      {"title": "Two", "paragraphs": [[c1]]}], audio
    if case == "trailing_heading":  # a heading with nothing after it is not the end of the narration
        return f"# One\n{a1}\n# Two\n", [{"title": "One", "paragraphs": [[a1]]}], audio
    if case == "quiet_final_sound":  # above the existing -58 dBFS per-chunk trim, so it survives today
        audio[a1] = np.concatenate([_tone(0.5), _noise(0.18, -50, seed=6, highpass=True)])
        return f"{a1}\n", [{"title": None, "paragraphs": [[a1]]}], audio
    raise ValueError(case)


@needs_edge_direct
@pytest.mark.parametrize("case", ["single_paragraph", "multi_chapter", "trailing_heading", "quiet_final_sound"])
def test_an_edge_direct_book_ends_without_a_closing_pause(edge_direct, case):
    text, book, audio = _edge_book(case)
    out, rate, params = edge_direct.run(text, audio)
    expected = _edge_direct_expected(book, audio, params["pause_kw"])
    _assert_keeps(out, expected)
    _assert_nothing_added(out, expected, f"edge-direct-{case}")
    _assert_bounded_tail(out, rate, f"edge-direct-{case}")


@needs_edge_direct
@pytest.mark.parametrize("case", ["multi_chapter", "quiet_final_sound"])
def test_an_edge_direct_book_keeps_every_internal_pause_and_final_sound(edge_direct, case):
    """Passes today: sentence, paragraph, title and between-chapter pauses are exact, and the last sound is whole."""
    text, book, audio = _edge_book(case)
    out, rate, params = edge_direct.run(text, audio)
    _assert_keeps(out, _edge_direct_expected(book, audio, params["pause_kw"]))
    assert rate == RATE


@needs_edge_direct
def test_the_edge_runner_called_with_its_own_defaults_adds_no_closing_pause(edge_direct):
    from tts.epub2tts_edge import epub2tts_edge as engine

    text, book, audio = _edge_book("multi_chapter")
    out, rate, _params = edge_direct.run(text, audio, defaults=True)
    defaults = {"sentencepause": engine.DEFAULT_SENTENCE_PAUSE_MS, "paragraphpause": engine.DEFAULT_PARAGRAPH_PAUSE_MS,
                "title_trailing_pause": engine.DEFAULT_TITLE_PAUSE_MS,
                "chapter_trailing_pause": engine.DEFAULT_CHAPTER_PAUSE_MS}
    expected = _edge_direct_expected(book, audio, defaults)
    _assert_keeps(out, expected)
    _assert_nothing_added(out, expected, "edge-runner-default-args")


@needs_edge_direct
def test_an_explicit_end_of_book_pause_adds_nothing(edge_direct):
    """``end_of_book_pause`` is still accepted (panel, runner, command line) for compatibility; it adds no pause."""
    text, book, audio = _edge_book("multi_chapter")
    out, _rate, params = edge_direct.run(text, audio, pause_kw={"end_of_book_pause": 3000})
    expected = _edge_direct_expected(book, audio, params["pause_kw"])
    _assert_keeps(out, expected)
    _assert_nothing_added(out, expected, "edge-direct-explicit-end-pause")


@needs_edge_direct
def test_untrimmed_edge_padding_after_the_final_word_is_shortened_by_the_policy(edge_direct, capsys):
    """With per-sentence trimming off, the last sentence's own network padding reaches ``make_mp3``: the final-tail
    policy keeps 150 ms of it there. The same padding after every earlier sentence is pacing and stays whole."""
    padding = _noise(0.8, -85, seed=7)  # Edge's own near-silence closing each network chunk
    text, book, audio = _edge_book("multi_chapter")
    padded = {spoken: np.concatenate([pcm, padding]) for spoken, pcm in audio.items()}
    out, rate, params = edge_direct.run(text, padded, pause_kw={"trim_tts_padding": False})
    whole = _edge_direct_expected(book, padded, params["pause_kw"])  # ends with the final sentence's full padding
    last_word_end = len(whole) - len(padding)
    _assert_keeps(out, whole[:last_word_end + _samples(KEEP_MS / 1000)])
    assert len(out) <= last_word_end + _samples((KEEP_MS + WINDOW_MS) / 1000), "more than the policy keeps"
    _assert_bounded_tail(out, rate, "edge-direct-untrimmed")
    assert "of trailing near-silence shortened to 0.15 s" in capsys.readouterr().out  # the run log says so


@needs_edge_direct
@pytest.mark.parametrize("case, raises", [("heading_only", ValueError), ("final_sentence_fails", ConnectionError)])
def test_an_edge_direct_book_with_no_ending_publishes_nothing(edge_direct, case, raises):
    text, _book, audio = _edge_book("multi_chapter")
    fail: tuple[str, ...] = ()
    if case == "heading_only":
        text = "# Only a heading\n"
    else:
        fail = ("Charlie one ends the book.",)
    with pytest.raises(raises):
        edge_direct.run(text, audio, fail=fail)
    assert not edge_direct.encodes and not edge_direct.destination().exists()


@needs_edge_direct
def test_cancelling_an_edge_direct_book_publishes_nothing(edge_direct):
    text, _book, audio = _edge_book("multi_chapter")
    with pytest.raises(ConversionCancelled):
        edge_direct.run(text, audio, cancel_check=lambda: len(edge_direct.spoken_) >= 2)
    assert not edge_direct.encodes and not edge_direct.destination().exists()


# --------------------------------------------------------------------------- #
# F. Edge folder/batch: fixed module constants, merge_mp3s, untrimmed network chunks
# --------------------------------------------------------------------------- #
@pytest.fixture
def edge_folder(monkeypatch, tmp_path, mp3_encodes):
    """``convert_single_pdf`` exactly as the panel's worker calls it; each "network" chunk is exact PCM."""
    from pydub import AudioSegment

    from tts import batch_convert as bc

    pending: list[np.ndarray] = []

    def synthesize(text, path, voice, rate):
        if not pending:
            raise RuntimeError("the folder worker asked for more chunks than the test planned")
        sf.write(path, pending.pop(0), RATE, format="WAV", subtype="PCM_16")

    monkeypatch.setattr(bc, "synthesize_chunk_mp3", synthesize)
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)  # the network politeness delay, irrelevant offline
    monkeypatch.setattr(AudioSegment, "from_mp3", classmethod(lambda cls, file, parameters=None: cls.from_wav(file)))

    class Harness:
        encodes = mp3_encodes
        run_dir = tmp_path / "TTS-Audiobook-1"
        logs: list[str] = []

        def destination(self) -> Path:
            return self.run_dir / "Folder" / "book.mp3"

        def run(self, renders: list[np.ndarray], *, text: str | None = None, cancel_check=None):
            source = tmp_path / "Sources" / "Folder" / "book.txt"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(text if text is not None else _text_for(bc.split_into_chunks, len(renders)),
                              encoding="utf-8")
            pending[:] = [np.asarray(r, dtype=np.float32) for r in renders]
            params = _frozen_params("en-US-SteffanNeural", self.run_dir)
            status, _path, message = bc.convert_single_pdf(
                source, self.run_dir, params["speaker"], params["rate"], self.logs.append, None,
                cancel_check or (lambda: False), self.destination(), bitrate=params["bitrate"])
            return status, message, params

    return Harness()


def _folder_expected(chunks: list[np.ndarray], keep_last: int):
    """``merge_mp3s`` up to ``keep_last`` samples of the final chunk, rebuilt with pydub's own arithmetic."""
    from pydub import AudioSegment

    from tts import batch_convert as bc

    silence = AudioSegment.silent(duration=bc.CHUNK_PAUSE_MS)
    combined = AudioSegment.empty()
    for chunk in chunks[:-1]:
        combined += _seg(chunk) + silence
    combined += _seg(chunks[-1][:keep_last])
    return np.frombuffer(combined.raw_data, dtype=np.int16).reshape(-1, combined.channels).copy()


def _folder_case(case: str):
    """(chunks, samples of the final chunk a fix must keep, exact)."""
    t1, t2, t3 = _tone(0.9, 220.0), _tone(0.7, 262.0), _tone(0.6, 294.0)
    padding = _noise(0.8, -85, seed=7)  # Edge's own ~800 ms of near-silence closing every network chunk
    if case == "single":
        return [_tone(1.2)], _samples(1.2), True
    if case == "multiple":
        return [t1, t2, t3], len(t3), True
    if case == "raw_padding":
        chunks = [np.concatenate([t, padding]) for t in (t1, t2, t3)]
        return chunks, len(t3) + _samples(KEEP_MS / 1000), False
    if case == "quiet_final_sound":
        fricative = _fade(_noise(0.18, -62, seed=1, highpass=True), 0.4)
        return [np.concatenate([t1, padding]), np.concatenate([t2, fricative, padding])], len(t2) + len(fricative), False
    if case in ("stereo_right_tail", "antiphase_tail"):
        tail = _fade(_noise(0.25, -58, seed=3, highpass=True), 0.3)
        first = np.stack([t1, t1], axis=1)
        rest = _zeros(1.0)
        left = np.concatenate([t2, np.zeros_like(tail), rest])
        right = np.concatenate([t2, tail, rest])
        if case == "antiphase_tail":
            left = np.concatenate([t2, -tail, rest])
        return [first, np.stack([left, right], axis=1)], len(t2) + len(tail), False
    raise ValueError(case)


@pytest.mark.parametrize("case", ["single", "multiple", "raw_padding", "quiet_final_sound", "stereo_right_tail"])
def test_an_edge_folder_file_ends_without_a_closing_pause(edge_folder, case):
    chunks, keep, exact = _folder_case(case)
    status, message, _params = edge_folder.run(chunks)
    if status != "success":
        raise RuntimeError(f"the folder worker reported {status}: {message}")
    capture = _only_encode(edge_folder.encodes)
    expected = _folder_expected(chunks, keep)
    _assert_keeps(capture.pcm, expected)
    if exact:
        _assert_nothing_added(capture.pcm, expected, f"edge-folder-{case}")
    _assert_bounded_tail(capture.pcm, capture.rate, f"edge-folder-{case}")


@pytest.mark.parametrize("case", ["multiple", "raw_padding", "quiet_final_sound", "stereo_right_tail",
                                  "antiphase_tail"])
def test_an_edge_folder_file_keeps_internal_chunk_padding_and_final_sounds(edge_folder, case):
    """Passes today: the 50 ms joins, the network padding *between* chunks and both channels' endings survive."""
    chunks, keep, _exact = _folder_case(case)
    status, message, params = edge_folder.run(chunks)
    if status != "success":
        raise RuntimeError(f"the folder worker reported {status}: {message}")
    capture = _only_encode(edge_folder.encodes)
    _assert_keeps(capture.pcm, _folder_expected(chunks, keep))
    assert capture.kwargs.get("bitrate") == params["bitrate"]


def test_a_blank_edge_folder_file_publishes_nothing(edge_folder):
    status, _message, _params = edge_folder.run([], text="   \n\n")
    assert status == "failed" and not edge_folder.encodes and not edge_folder.destination().exists()


def test_cancelling_an_edge_folder_file_publishes_nothing(edge_folder):
    calls = {"n": 0}

    def cancel_after_first_chunk() -> bool:
        calls["n"] += 1
        return calls["n"] > 2  # look 1: before the file; look 2: before chunk 1; look 3: before chunk 2

    status, _message, _params = edge_folder.run([_tone(0.5), _tone(0.5, 330.0)],
                                                cancel_check=cancel_after_first_chunk)
    assert status == "cancelled" and not edge_folder.encodes and not edge_folder.destination().exists()


@needs_ffmpeg
def test_the_published_edge_folder_mp3_decodes_with_a_bounded_tail(edge_folder):
    edge_folder.encodes.real_encode = True
    chunks, _keep, _exact = _folder_case("raw_padding")
    status, message, _params = edge_folder.run(chunks)
    if status != "success":
        raise RuntimeError(f"the folder worker reported {status}: {message}")
    decoded = _decode(edge_folder.destination())
    assert abs(len(decoded) - len(_only_encode(edge_folder.encodes).pcm)) <= 2 * 576
    _assert_bounded_tail(decoded, RATE, "edge-folder-decoded-mp3")


def test_the_edge_folder_run_log_reports_the_final_tail(edge_folder):
    chunks, _keep, _exact = _folder_case("raw_padding")
    status, message, _params = edge_folder.run(chunks)
    if status != "success":
        raise RuntimeError(f"the folder worker reported {status}: {message}")
    assert any(line.startswith("  book.txt: Final tail:") and "shortened to 0.15 s" in line
               for line in edge_folder.logs), edge_folder.logs


# --------------------------------------------------------------------------- #
# G. The production final-tail policy itself (P01B, ``tts.audio_tail``)
# --------------------------------------------------------------------------- #
def _sine(seconds: float, dbfs_peak: float, freq: float = 220.0) -> np.ndarray:
    return (10 ** (dbfs_peak / 20) * np.sin(2 * np.pi * freq * np.arange(_samples(seconds)) / RATE)).astype(np.float32)


def test_the_policy_constants_are_the_calibrated_ones():
    """P01A calibration; a change needs a new calibration and listening, never a quiet edit."""
    from tts import audio_tail

    assert (audio_tail.WINDOW_MS, audio_tail.NOMINAL_THRESHOLD_DBFS, audio_tail.CONSERVATIVE_THRESHOLD_DBFS,
            audio_tail.KEEP_MS, audio_tail.BUDGET_MS) == (10, -60.0, -70.0, 150, 300)


@pytest.mark.parametrize("sound", SOUNDS)
def test_the_policy_finds_the_same_end_as_the_independent_oracle(sound):
    from tts import audio_tail

    tail, _keep = _final_sound(sound)
    pcm = np.concatenate([_zeros(0.3), _tone(0.7), tail])
    for threshold in (-70.0, -60.0, -50.0):
        assert audio_tail.last_sound(pcm, RATE, threshold) == last_sound(pcm, threshold_dbfs=threshold), threshold
    assert audio_tail.last_sound(_q16(pcm), RATE) == last_sound(_q16(pcm))  # 16-bit input measures the same


def test_the_policy_only_ever_shortens_the_terminal_suffix():
    """Leading and internal silence are untouched: the result is an exact prefix of the input, same dtype/shape."""
    from tts import audio_tail

    pcm = np.concatenate([_zeros(1.0), _tone(0.5), _zeros(2.0), _tone(0.5, 330.0), _zeros(3.0)])
    result = audio_tail.apply_final_tail_policy(pcm, RATE)
    assert result.pcm.dtype == pcm.dtype and result.pcm.ndim == 1
    np.testing.assert_array_equal(result.pcm, pcm[:len(result.pcm)])
    assert len(result.pcm) == _samples(1.0 + 0.5 + 2.0 + 0.5) + _samples(KEEP_MS / 1000)
    assert result.tail_ms == pytest.approx(KEEP_MS) and not result.uncertain
    assert "shortened to 0.15 s" in result.summary()


def test_a_short_natural_tail_is_left_exactly_as_it_is():
    from tts import audio_tail

    pcm = np.concatenate([_tone(1.0), _zeros(0.04)])
    result = audio_tail.apply_final_tail_policy(pcm, RATE)
    assert len(result.pcm) == len(pcm) and result.removed_samples == 0  # never padded, never shortened further
    assert "nothing removed" in result.summary()


def test_a_quiet_decay_that_only_the_conservative_threshold_sees_is_kept():
    """A -65 dBpk decay lasting 250 ms: -60 dBFS no longer sees it, so 150 ms alone would cut 100 ms of it."""
    from tts import audio_tail

    decay = _sine(0.25, -65.0)
    pcm = np.concatenate([_tone(1.0), decay, _zeros(1.0)])
    result = audio_tail.apply_final_tail_policy(pcm, RATE)
    assert len(result.pcm) >= _samples(1.25), "the -65 dB decay was cut"
    assert len(result.pcm) <= _samples(1.25) + _samples(WINDOW_MS / 1000)
    assert not result.uncertain


def test_quiet_sound_past_the_budget_is_kept_in_full_and_reported_never_clipped():
    """Section 5.1: if the conservative end cannot meet 300 ms, keep it and say so rather than cut audio."""
    from tts import audio_tail

    pcm = np.concatenate([_tone(1.0), _sine(0.6, -65.0), _zeros(1.0)])
    result = audio_tail.apply_final_tail_policy(pcm, RATE)
    assert len(result.pcm) >= _samples(1.6)
    assert result.uncertain and result.tail_ms > BUDGET_MS
    assert "please listen" in result.summary()


def test_audio_with_no_sound_at_all_is_left_unchanged_and_reported():
    from tts import audio_tail

    pcm = _noise(2.0, -90, seed=9)
    result = audio_tail.apply_final_tail_policy(pcm, RATE)
    assert len(result.pcm) == len(pcm) and result.uncertain and result.nominal_end == 0
    assert "left unchanged" in result.summary()


def test_every_channel_counts_on_its_own():
    """A quiet right-channel tail and an antiphase tail (which a downmix cancels) both survive."""
    from tts import audio_tail

    speech = _tone(1.0)
    right = _fade(_noise(0.25, -58, seed=3, highpass=True), 0.3)
    stereo = np.stack([np.concatenate([speech, _zeros(1.25)]), np.concatenate([speech, right, _zeros(1.0)])], axis=1)
    kept = audio_tail.apply_final_tail_policy(stereo, RATE).pcm
    assert kept.shape[1] == 2 and len(kept) >= _samples(1.25)
    tail = _noise(0.25, -55, seed=4, highpass=True)
    antiphase = np.stack([np.concatenate([speech, tail, _zeros(1.0)]), np.concatenate([speech, -tail, _zeros(1.0)])],
                         axis=1)
    assert len(audio_tail.apply_final_tail_policy(antiphase, RATE).pcm) >= _samples(1.25)


def test_16_bit_frames_first_pcm_is_handled_like_float():
    from tts import audio_tail

    pcm = np.concatenate([_tone(1.0), _final_sound("breath")[0]])
    as_float = audio_tail.apply_final_tail_policy(pcm, RATE)
    as_int = audio_tail.apply_final_tail_policy(_q16(pcm), RATE)
    assert as_int.pcm.dtype == np.int16 and as_int.pcm.shape[1] == 1
    assert abs(len(as_int.pcm) - len(as_float.pcm)) <= _samples(WINDOW_MS / 1000)


def test_a_long_silent_suffix_is_searched_back_across_blocks():
    """The tail is scanned backwards in 30 s blocks; a sound 65 s before the end is still found exactly."""
    from tts import audio_tail

    rate = 8000
    pcm = np.concatenate([(0.3 * np.sin(np.arange(rate) / 3)).astype(np.float32), np.zeros(rate * 65, np.float32)])
    result = audio_tail.apply_final_tail_policy(pcm, rate)
    assert len(result.pcm) == rate + int(rate * KEEP_MS / 1000)


def test_the_policy_rejects_shapes_and_types_it_cannot_measure():
    from tts import audio_tail

    with pytest.raises(ValueError):
        audio_tail.apply_final_tail_policy(np.zeros((2, 3, 4), np.float32), RATE)
    with pytest.raises(ValueError):
        audio_tail.apply_final_tail_policy(np.zeros(10, dtype=bool), RATE)
    assert len(audio_tail.apply_final_tail_policy(np.zeros(0, np.float32), RATE).pcm) == 0


@pytest.mark.parametrize("width", [1, 2, 4])
@pytest.mark.parametrize("channels", [1, 2])
def test_a_pydub_segment_is_cut_exactly_where_its_pcm_would_be(width, channels):
    """P01C: the Edge routes assemble in pydub; the segment form is the same rule, an exact sample prefix."""
    from tts import audio_tail

    pcm = np.concatenate([_tone(0.5), _zeros(0.8)])  # digital silence stays silence at every width
    segment = _seg(np.stack([pcm] * channels, axis=1)).set_sample_width(width)
    kept, tail = audio_tail.apply_final_tail_policy_to_segment(segment)
    reference = audio_tail.apply_final_tail_policy(_q16(pcm), RATE)
    assert int(kept.frame_count()) == len(reference.pcm) == len(tail.pcm) < len(pcm)
    assert (kept.frame_rate, kept.channels, kept.sample_width) == (RATE, channels, width)
    assert kept.raw_data == segment.raw_data[:len(kept.raw_data)]
    untouched, _tail = audio_tail.apply_final_tail_policy_to_segment(kept)
    assert untouched is kept  # nothing more to remove: the very same segment comes back


def test_a_pydub_segment_of_an_unknown_sample_width_is_refused():
    from tts import audio_tail

    with pytest.raises(ValueError):
        audio_tail.apply_final_tail_policy_to_segment(SimpleNamespace(sample_width=3, raw_data=b"", channels=1,
                                                                      frame_rate=RATE))


@pytest.mark.parametrize("engine", ["kokoro", "chatterbox", "qwen3"])
def test_the_run_log_reports_the_final_tail(local_engine, engine):
    """The owner can see in the run log what the policy did (and when an ending needs listening)."""
    from tts import epub2tts_gui as gui

    converter = {"kokoro": gui.convert_with_kokoro, "chatterbox": gui.convert_with_chatterbox,
                 "qwen3": gui.convert_with_qwen3}[engine]
    source = local_engine.root / "logged.txt"
    source.write_text(local_engine.text(engine, 2), encoding="utf-8")
    local_engine.queue([_tone(0.9), np.concatenate([_tone(0.7, 330.0), _zeros(2.0)])])
    logs: list[str] = []
    item = {"source": source, "destination": local_engine.destination(), "item_id": "item-1"}
    converter(item, _frozen_params(LOCAL_VOICES[engine]), None, logs.append, lambda: False)
    local_engine.drained()
    assert any("Final tail: 2.00 s of trailing near-silence shortened to 0.15 s." in line for line in logs), logs
