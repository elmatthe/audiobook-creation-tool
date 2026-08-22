"""v0.6.1 Plan 4 Phase 12 — the final MP3 encoding contract for TTS output.

**The defect these tests were written against.** Every local TTS engine finished a
file with ``AudioSegment.export(path, format="mp3")`` and nothing else. pydub's
``DEFAULT_CODECS`` has no ``mp3`` entry, so that runs ``ffmpeg -f wav -i … -f mp3``
with **no codec and no bitrate** — the encode contract was whatever the machine's
ffmpeg happened to default to. On this project's ffmpeg that is **32 kbps** for a
24 kHz mono stream.

That low bitrate is what broke player-reported duration, and the mechanism is
exact. A Xing/Info header carries a 100-byte seek table, which does not fit in a
32 kbps MPEG-2 frame (96 bytes), so ffmpeg is forced to emit the header frame at
**64 kbps** while every audio frame stays at 32 — and still tags the file ``Info``,
which *means* constant bitrate. A player that believes the CBR claim and reads the
bitrate from the first frame computes a duration **exactly half** the truth.
Measured on this machine: Windows Media Foundation read a real 6:54 Chatterbox
chapter as 6:34, and a 2:00 fixture as 1:54 at 32 kbps — with the error shrinking
monotonically to **zero at 64 kbps and above**, which is the point where the header
frame and the audio frames finally agree.

ffprobe and mutagen never showed it, because both read the Xing *frame count*
rather than the advertised bitrate. That is precisely why this survived every
automated check and had to be caught by an invariant about the file's own
internal consistency — which is what :func:`_frame_report` asserts here.

The fix is to stop leaving the contract to a default: encode once, explicitly,
through :func:`shared.ffmpeg_utils.mp3_export_options`, at the bitrate the user
already chose in the panel's existing "MP3 bitrate" control. That control offers
128k/192k/320k — all comfortably above the 64 kbps threshold — and until now only
the Edge *direct* path honoured it.

Nothing here loads a real model, reaches the network, or writes outside tmp_path.
"""

from __future__ import annotations

import ast
import collections
import json
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from shared import ffmpeg_utils

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts" / "Universal"

needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(),
    reason="ffmpeg/ffprobe unavailable — encoding cannot be exercised",
)

# --------------------------------------------------------------------------- #
# MP3 frame reading — deliberately hand-rolled
#
# The whole point is to check the file the way a *player* does, from the frame
# headers themselves. Asking ffprobe or mutagen would re-introduce exactly the
# blind spot that let this ship: both of them read the Xing frame count and so
# report the right answer even when the file is internally inconsistent.
# --------------------------------------------------------------------------- #
_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _frame_report(path: Path) -> dict:
    """Walk every MPEG audio frame and describe the file structurally."""
    data = Path(path).read_bytes()
    offset = 0
    if data[:3] == b"ID3":
        b = data[6:10]
        offset = ((b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]) + 10

    counts: collections.Counter = collections.Counter()
    first = None
    samples = 0
    while offset < len(data) - 4:
        if data[offset] != 0xFF or (data[offset + 1] & 0xE0) != 0xE0:
            offset += 1
            continue
        b1, b2 = data[offset + 1], data[offset + 2]
        version_id, layer = (b1 >> 3) & 0x03, (b1 >> 1) & 0x03
        bitrate_index, rate_index = (b2 >> 4) & 0x0F, (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01
        if version_id == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
            offset += 1
            continue
        kbps = (_V1L3 if version_id == 3 else _V2L3)[bitrate_index]
        rate = _RATES[version_id][rate_index]
        spf = 1152 if version_id == 3 else 576
        size = (spf // 8) * kbps * 1000 // rate + padding
        if first is None:
            first = {"kbps": kbps, "rate": rate, "spf": spf,
                     "mono": ((data[offset + 3] >> 6) & 0x03) == 3}
        counts[kbps] += 1
        samples += spf
        offset += size

    assert first is not None, f"no MPEG audio frame found in {path}"
    # The header frame is one frame; the audio is everything else. When they
    # disagree, a player reading the first frame's bitrate is misled.
    audio_only = collections.Counter(counts)
    audio_only[first["kbps"]] -= 1
    if audio_only[first["kbps"]] <= 0:
        del audio_only[first["kbps"]]
    return {
        "first_kbps": first["kbps"],
        "rate": first["rate"],
        "mono": first["mono"],
        "audio_bitrates": dict(audio_only) or {first["kbps"]: counts[first["kbps"]]},
        "frames": sum(counts.values()),
        "seconds": samples / first["rate"],
        "size": len(data),
    }


def assert_header_matches_audio(path: Path) -> dict:
    """The invariant the shipped defect violated.

    A file whose leading frame advertises one bitrate while its audio frames use
    another invites any first-frame-sampling parser to report a wrong duration.
    """
    report = _frame_report(path)
    audio = report["audio_bitrates"]
    assert len(audio) == 1, (
        f"{path.name}: audio frames are not a single bitrate: {audio}")
    audio_kbps = next(iter(audio))
    assert report["first_kbps"] == audio_kbps, (
        f"{path.name}: header frame is {report['first_kbps']} kbps but the "
        f"{report['frames'] - 1} audio frames are {audio_kbps} kbps. A player "
        f"that trusts the CBR tag and reads the first frame will report "
        f"{report['size'] * 8 / (report['first_kbps'] * 1000):.1f}s for a "
        f"{report['seconds']:.1f}s file.")
    return report


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-show_entries",
         "format=duration", "-print_format", "json", str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def decoded_duration(path: Path) -> float:
    """Ground truth: decode every sample and divide by the rate."""
    report = _frame_report(path)
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-i", str(path), "-f", "s16le",
         "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(report["rate"]), "-"],
        capture_output=True, check=True)
    return len(out.stdout) / 2.0 / report["rate"]


def mutagen_duration(path: Path) -> float:
    from mutagen.mp3 import MP3

    return MP3(str(path)).info.length


def assert_durations_agree(path: Path, tolerance: float = 0.10) -> float:
    """ffprobe, mutagen and a real decode must describe the same file.

    The tolerance is absolute seconds rather than a ratio because the sources of
    disagreement — encoder delay, padding to a whole frame — are fixed costs, not
    proportional ones. One MPEG-2 frame is 24 ms; 100 ms is a few frames of slack
    and still nowhere near the failures this guards against.
    """
    ff, mu, real = probe_duration(path), mutagen_duration(path), decoded_duration(path)
    assert abs(ff - real) < tolerance, f"{path.name}: ffprobe {ff} vs decoded {real}"
    assert abs(mu - real) < tolerance, f"{path.name}: mutagen {mu} vs decoded {real}"
    return real


def assert_decodes_cleanly(path: Path) -> None:
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-err_detect", "explode",
         "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    assert out.returncode == 0 and not out.stderr.strip(), (
        f"{path.name} did not decode cleanly: {out.stderr.strip()}")


def assert_seek_near_end_works(path: Path, back: float = 2.0) -> None:
    total = decoded_duration(path)
    start = max(0.0, total - back)
    out = subprocess.run(
        [ffmpeg_utils.ffmpeg_cmd(), "-v", "error", "-ss", str(start),
         "-i", str(path), "-f", "s16le", "-"], capture_output=True)
    assert out.returncode == 0, f"seek to {start:.1f}s failed for {path.name}"
    assert len(out.stdout) > 0, f"seek to {start:.1f}s decoded nothing in {path.name}"


# --------------------------------------------------------------------------- #
# A. The contract itself
# --------------------------------------------------------------------------- #
def test_the_shared_export_options_pin_an_explicit_encoder():
    options = ffmpeg_utils.mp3_export_options()
    assert options["format"] == "mp3"
    assert options["codec"] == "libmp3lame"
    assert options["bitrate"]


def test_the_default_bitrate_is_above_the_header_consistency_threshold():
    """Below 64 kbps the Xing frame cannot match the audio frames — see module docstring."""
    kbps = int(str(ffmpeg_utils.mp3_export_options()["bitrate"]).rstrip("k"))
    assert kbps >= 64


def test_a_caller_supplied_bitrate_is_honoured():
    assert ffmpeg_utils.mp3_export_options("128k")["bitrate"] == "128k"


def test_a_blank_or_missing_bitrate_falls_back_to_the_default():
    default = ffmpeg_utils.mp3_export_options()["bitrate"]
    assert ffmpeg_utils.mp3_export_options(None)["bitrate"] == default
    assert ffmpeg_utils.mp3_export_options("")["bitrate"] == default


def test_the_default_matches_the_panels_own_default_choice():
    """The contract must not silently disagree with what the GUI shows the user."""
    source = (SCRIPTS / "tts" / "epub2tts_gui.py").read_text(encoding="utf-8")
    assert 'self.bitrate_var = tk.StringVar(value="192k")' in source
    assert ffmpeg_utils.mp3_export_options()["bitrate"] == "192k"


# --------------------------------------------------------------------------- #
# B. Every TTS finalization goes through it
# --------------------------------------------------------------------------- #
ENGINE_SOURCES = ("tts/kokoro_synth.py", "tts/chatterbox_synth.py",
                  "tts/batch_convert.py")


def _export_calls(tree: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "export"]


@pytest.mark.parametrize("name", ENGINE_SOURCES)
def test_no_engine_exports_an_mp3_on_ffmpegs_defaults(name):
    """The regression guard: an ``export(..., format="mp3")`` with no contract."""
    tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
    for call in _export_calls(tree):
        keywords = {kw.arg for kw in call.keywords if kw.arg}
        literal = any(isinstance(kw.value, ast.Constant) and kw.value.value == "mp3"
                      for kw in call.keywords if kw.arg == "format")
        if literal:
            pytest.fail(
                f"{name}:{call.lineno} exports mp3 with a literal format= and no "
                "shared contract; use ffmpeg_utils.mp3_export_options()")
        assert keywords in ({"format", "codec", "bitrate"}, set()), (
            f"{name}:{call.lineno} exports with {sorted(keywords)}")


@pytest.mark.parametrize("name", ENGINE_SOURCES)
def test_every_engine_reaches_the_shared_contract(name):
    source = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "mp3_export_options" in source, (
        f"{name} does not use the shared final-encode contract")


# --------------------------------------------------------------------------- #
# C. One lossy generation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,function", [
    ("tts/kokoro_synth.py", "kokoro_file_to_mp3"),
    ("tts/chatterbox_synth.py", "chatterbox_file_to_mp3"),
])
def test_the_local_engines_never_encode_an_intermediate_mp3(name, function):
    """Local engines hold PCM, so a per-chunk MP3 is a pure quality loss.

    Measured on this machine: a second generation at 32 kbps costs **5.67 dB** of
    SNR against the source PCM. Nothing needs it — the chunks are numpy arrays
    until the moment the file is written.
    """
    source = (SCRIPTS / name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == function)
    segment = ast.get_source_segment(source, body) or ""
    assert "from_mp3" not in segment, (
        f"{function} still decodes intermediate MP3s — that is the second "
        "lossy generation this phase removed")
    assert ".mp3" not in segment.replace("output_mp3_path", "").replace(
        "_to_mp3", ""), f"{function} still names a per-chunk .mp3 artifact"


@pytest.mark.parametrize("name", ["tts/kokoro_synth.py", "tts/chatterbox_synth.py"])
def test_the_local_engines_assemble_before_they_encode(name):
    """Exactly one export call survives in each local engine module."""
    tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
    assert len(_export_calls(tree)) <= 1, (
        f"{name} still has more than one export call, so it encodes more than once")


# --------------------------------------------------------------------------- #
# D. Real files, real ffmpeg
# --------------------------------------------------------------------------- #
def _pcm(seconds: float, rate: int = 24000, seed: int = 3) -> np.ndarray:
    """Deterministic speech-shaped PCM. Cheap enough for a multi-minute case."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * rate)) / rate
    sig = sum((1.0 / h) * np.sin(2 * np.pi * 120 * h * t + rng.random() * 6.28)
              for h in range(1, 10))
    env = np.clip(0.5 * (1 + np.sin(2 * np.pi * 3.0 * t)) - 0.15, 0, None)
    sig = sig * env
    return (0.5 * sig / (np.max(np.abs(sig)) or 1.0)).astype("float32")


def _encode(pcm: np.ndarray, path: Path, rate: int = 24000,
            bitrate: str | None = None) -> Path:
    """Encode through the production contract, the way an engine now does."""
    import soundfile as sf
    from pydub import AudioSegment

    ffmpeg_utils.configure_pydub()
    wav = path.with_suffix(".wav")
    sf.write(wav, pcm, rate)
    AudioSegment.from_wav(str(wav)).export(
        str(path), **ffmpeg_utils.mp3_export_options(bitrate))
    wav.unlink()
    return path


@needs_ffmpeg
def test_a_short_file_is_internally_consistent(tmp_path):
    out = _encode(_pcm(8.0), tmp_path / "short.mp3")
    report = assert_header_matches_audio(out)
    assert report["rate"] == 24000 and report["mono"]
    real = assert_durations_agree(out)
    assert real == pytest.approx(8.0, abs=0.2)


@needs_ffmpeg
def test_a_multi_minute_file_is_internally_consistent(tmp_path):
    """The reported symptom was a long file; length must not change the answer."""
    out = _encode(_pcm(600.0), tmp_path / "long.mp3")
    assert_header_matches_audio(out)
    real = assert_durations_agree(out)
    assert real == pytest.approx(600.0, abs=0.3)


@needs_ffmpeg
def test_a_multi_minute_file_decodes_and_seeks_to_its_end(tmp_path):
    out = _encode(_pcm(600.0), tmp_path / "long.mp3")
    assert_decodes_cleanly(out)
    assert_seek_near_end_works(out)


@needs_ffmpeg
@pytest.mark.parametrize("bitrate", ["128k", "192k", "320k"])
def test_every_bitrate_the_panel_offers_produces_a_consistent_file(tmp_path, bitrate):
    """The three selectable values are the whole supported surface."""
    out = _encode(_pcm(12.0), tmp_path / f"b{bitrate}.mp3", bitrate=bitrate)
    assert_header_matches_audio(out)
    assert_durations_agree(out)


@needs_ffmpeg
def test_the_defaulted_export_this_phase_replaced_would_fail_the_invariant(tmp_path):
    """Characterize the defect itself, so the guard is proven to have teeth.

    This deliberately reproduces the *old* behaviour — a bare
    ``export(format="mp3")`` — and asserts it is exactly what the invariant
    rejects. If a future ffmpeg changes its default so this file becomes
    consistent, this test fails and tells us the threat model moved.
    """
    import soundfile as sf
    from pydub import AudioSegment

    ffmpeg_utils.configure_pydub()
    wav = tmp_path / "src.wav"
    sf.write(wav, _pcm(12.0), 24000)
    bad = tmp_path / "defaulted.mp3"
    AudioSegment.from_wav(str(wav)).export(str(bad), format="mp3")

    report = _frame_report(bad)
    audio_kbps = next(iter(report["audio_bitrates"]))
    assert report["first_kbps"] != audio_kbps, (
        "ffmpeg's default no longer produces the mismatch this phase fixed")
    with pytest.raises(AssertionError):
        assert_header_matches_audio(bad)


# --------------------------------------------------------------------------- #
# E. The engines end to end, with the model stubbed
# --------------------------------------------------------------------------- #
@pytest.fixture
def chatterbox_ready(monkeypatch, tmp_path):
    import tts.chatterbox_synth as cbx

    class _Model:
        sr = 24000
        device = "cpu"

        def __init__(self):
            self.generated: list[str] = []

        def generate(self, text, **kwargs):
            self.generated.append(text)
            return _pcm(1.0).reshape(1, -1)

    model = _Model()
    monkeypatch.setattr(cbx, "_runtime_root", lambda: tmp_path / "runtime-data")
    monkeypatch.setattr(cbx, "_get_model", lambda device=None: model)
    monkeypatch.setattr(cbx, "load_conditionals",
                        lambda m, v, log=print, device=None: None)
    return model


def _text(tmp_path: Path, sentences: int = 40) -> Path:
    body = " ".join(f"This is sentence number {i} of the sample text."
                    for i in range(sentences))
    path = tmp_path / "source.txt"
    path.write_text(f"Title: Sample\nAuthor: Nobody\n{body}\n", encoding="utf-8")
    return path


@needs_ffmpeg
def test_chatterbox_output_is_internally_consistent(chatterbox_ready, tmp_path):
    import tts.chatterbox_synth as cbx

    out = tmp_path / "cbx.mp3"
    cbx.chatterbox_file_to_mp3(str(_text(tmp_path)), str(out), "chatterbox-male-1",
                               log=lambda _m: None)
    report = assert_header_matches_audio(out)
    assert report["rate"] == 24000 and report["mono"], "engine rate/channels changed"
    assert_durations_agree(out)
    assert_decodes_cleanly(out)


@needs_ffmpeg
def test_chatterbox_honours_the_runs_chosen_bitrate(chatterbox_ready, tmp_path):
    import tts.chatterbox_synth as cbx

    out = tmp_path / "cbx128.mp3"
    cbx.chatterbox_file_to_mp3(str(_text(tmp_path)), str(out), "chatterbox-male-1",
                               log=lambda _m: None, bitrate="128k")
    assert next(iter(assert_header_matches_audio(out)["audio_bitrates"])) == 128


@needs_ffmpeg
def test_chatterbox_still_honours_its_pause_contract(chatterbox_ready, tmp_path):
    """Assembly moved to PCM; the configured silences must land unchanged."""
    import tts.chatterbox_synth as cbx

    source = _text(tmp_path)
    short, long = tmp_path / "s.mp3", tmp_path / "l.mp3"
    cbx.chatterbox_file_to_mp3(str(source), str(short), "chatterbox-male-1",
                               end_silence_ms=0, chunk_pause_ms=0,
                               log=lambda _m: None)
    cbx.chatterbox_file_to_mp3(str(source), str(long), "chatterbox-male-1",
                               end_silence_ms=3000, chunk_pause_ms=50,
                               log=lambda _m: None)
    added = decoded_duration(long) - decoded_duration(short)
    chunks = len(cbx.split_for_chatterbox(
        source.read_text(encoding="utf-8").split("Author: Nobody\n")[1].strip()))
    assert added == pytest.approx(3.0 + chunks * 0.05, abs=0.25)


@needs_ffmpeg
def test_chatterbox_progress_and_cancellation_are_unchanged(chatterbox_ready, tmp_path):
    import tts.chatterbox_synth as cbx
    from shared.cancellation import ConversionCancelled

    seen: list[tuple[int, int]] = []
    out = tmp_path / "p.mp3"
    cbx.chatterbox_file_to_mp3(str(_text(tmp_path)), str(out), "chatterbox-male-1",
                               log=lambda _m: None,
                               progress_callback=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1] == len(chatterbox_ready.generated)

    with pytest.raises(ConversionCancelled):
        cbx.chatterbox_file_to_mp3(str(_text(tmp_path)), str(tmp_path / "c.mp3"),
                                   "chatterbox-male-1", log=lambda _m: None,
                                   cancel_check=lambda: True)
    assert not (tmp_path / "c.mp3").exists()


@needs_ffmpeg
def test_kokoro_output_is_internally_consistent(monkeypatch, tmp_path):
    import tts.kokoro_synth as ks

    class _Pipeline:
        def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
            yield ("g", "p", _pcm(1.0))

    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: _Pipeline())
    source = tmp_path / "k.txt"
    source.write_text(("This is a sentence that fills the chunk. " * 90).strip(),
                      encoding="utf-8")
    out = tmp_path / "kokoro.mp3"
    ks.kokoro_file_to_mp3(str(source), str(out), voice_id="af_heart",
                          log=lambda _m: None)
    report = assert_header_matches_audio(out)
    assert report["rate"] == 24000 and report["mono"]
    assert_durations_agree(out)
    assert_decodes_cleanly(out)


@needs_ffmpeg
def test_the_edge_folder_merge_is_internally_consistent(tmp_path):
    """The Edge *folder* path cannot avoid a second generation — its chunks arrive
    from the service as MP3 — but its final contract must still be explicit."""
    from pydub import AudioSegment

    from tts import batch_convert

    ffmpeg_utils.configure_pydub()
    chunks = []
    for i in range(4):
        chunk = tmp_path / f"c{i}.mp3"
        _encode(_pcm(2.0, seed=i), chunk)
        chunks.append(str(chunk))
    out = tmp_path / "merged.mp3"
    batch_convert.merge_mp3s(chunks, str(out))
    assert_header_matches_audio(out)
    assert_durations_agree(out)


# --------------------------------------------------------------------------- #
# F. Nothing else moved
# --------------------------------------------------------------------------- #
def test_the_edge_direct_path_is_left_alone():
    """Measured clean at 160 kbps with a matching header frame — not this phase's
    business, and the plan protects Edge's own timing engine."""
    source = (SCRIPTS / "tts" / "epub2tts_edge" / "epub2tts_edge.py").read_text(
        encoding="utf-8")
    assert 'def make_mp3(files, sourcefile, speaker, bitrate="192k")' in source
    assert 'combined.export(outputmp3, format="mp3", bitrate=bitrate)' in source


def test_the_settled_chatterbox_values_are_untouched():
    import tts.chatterbox_synth as cbx

    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS == 300
    assert cbx.GENERATION_TEMPERATURE == 0.72
    assert cbx.PHASE9_EVALUATION_TEMPERATURE == 0.8
    assert cbx.COLON_PAUSE_MS == 75
    assert len(cbx.REFERENCE_VOICES) == 4


def test_the_version_and_tool_count_are_unchanged():
    import launcher
    from shared import version

    # v0.6.1 Plan 4 Phase 15 closeout: the bump from 0.5.1 happened here and
    # nowhere else. This guard now pins the approved closeout version.
    assert version.VERSION == "0.6.1"
    assert len(launcher.TOOLS) == 6
