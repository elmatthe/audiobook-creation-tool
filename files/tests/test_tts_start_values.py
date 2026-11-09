"""What the TTS panel tells the person at Start about the values it is given — v0.7.2 Phase 6, ACT72-021 and ACT72-047.

**ACT72-021.** Every voice family makes 24 kHz speech, and an MP3 at 24 kHz (MPEG-2 Layer III) can be at most 160 kbit/s:
asked for 192k or 320k the encoder writes 160k, and nobody was told. Measured on the app's real output of every engine
(evidence in the Phase 6 work folder) and here on a real encode. The options and the encoding are unchanged; the run's
Summary now says what the files get.

**ACT72-047.** The Kokoro speed spinbox limits only its arrows: a typed 0, negative, ``nan`` or ``inf`` reached the engine,
and a word silently became 1.0. Start now refuses anything but a finite number from 0.5 to 2.0, before anything is frozen
or reserved, as it already does for the Edge speech rate.
"""

from __future__ import annotations

import subprocess

import pytest

tk = pytest.importorskip("tkinter")

from shared import ffmpeg_utils  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import voice_registry  # noqa: E402

from test_tts_jobs import direct_panel, run_attempt  # noqa: E402
from test_tts_importing import make_panel, output_base, stubs, tk_root  # noqa: E402,F401

KOKORO = next(entry.display_label for entry in voice_registry.VOICES if entry.backend == "kokoro")


# --------------------------------------------------------------------------- ACT72-021


@pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")
@pytest.mark.parametrize("asked, written", [("128k", 128000), ("192k", 160000), ("320k", 160000)])
def test_a_24_khz_mp3_is_written_at_most_at_160_kbit(tmp_path, asked, written):
    """The ceiling itself, on a real encode by the app's own FFmpeg and LAME, at the rate every voice makes."""
    out = tmp_path / f"tone-{asked}.mp3"
    subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2", "-ac", "1", "-ar", str(panel_module.SPEECH_SAMPLE_RATE),
                    "-c:a", "libmp3lame", "-b:a", asked, str(out)], check=True, capture_output=True)
    probed = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                             "stream=bit_rate", "-of", "default=nw=1:nk=1", str(out)],
                            check=True, capture_output=True, text=True).stdout.strip()
    assert int(probed) == written
    assert min(int(asked[:-1]), panel_module.mp3_bitrate_ceiling_kbps(panel_module.SPEECH_SAMPLE_RATE)) * 1000 == written


@pytest.mark.parametrize("rate, ceiling", [(48000, 320), (44100, 320), (32000, 320), (24000, 160), (22050, 160),
                                           (16000, 160), (12000, 64), (8000, 64)])
def test_the_mp3_ceiling_follows_the_mpeg_version_of_the_sample_rate(rate, ceiling):
    assert panel_module.mp3_bitrate_ceiling_kbps(rate) == ceiling


def test_only_a_bitrate_above_the_ceiling_is_explained():
    assert panel_module.mp3_bitrate_note("128k") == ""
    for asked in ("192k", "320k"):
        note = panel_module.mp3_bitrate_note(asked)
        assert asked in note and "24 kHz" in note and "160k" in note, note
    assert panel_module.mp3_bitrate_note("192k", 44100) == "", "honoured at 44.1 kHz, so nothing to explain"


@pytest.mark.parametrize("asked, explained", [("192k", True), ("320k", True), ("128k", False)])
def test_the_runs_summary_says_what_bitrate_the_files_get(make_panel, output_base, tmp_path, stubs, asked, explained):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    panel.bitrate_var.set(asked)
    params = run_attempt(panel)
    assert params["bitrate"] == asked, "the request itself is frozen unchanged; nothing is resampled or re-chosen"
    notes = [line for line in panel.log.summary if line.startswith("MP3 bitrate")]
    assert bool(notes) is explained, panel.log.summary
    if explained:
        assert "160k" in notes[0]


# --------------------------------------------------------------------------- ACT72-047


@pytest.mark.parametrize("typed", ["0", "-1", "0.49", "2.01", "nan", "inf", "-inf", "abc", "", "1,5"])
def test_a_kokoro_speed_outside_half_to_double_or_not_a_number_starts_nothing(
        make_panel, output_base, tmp_path, monkeypatch, typed):
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    panel.selected_voice_label.set(KOKORO)
    panel._on_voice_selected()
    panel.kokoro_speed_var.set(typed)
    warnings: list = []
    monkeypatch.setattr(panel_module.messagebox, "showwarning", lambda title, text, **k: warnings.append((title, text)))
    monkeypatch.setattr(panel, "_refresh_voice_status", lambda entry: pytest.fail("checked before the voice"))
    panel.run_job()
    assert warnings and warnings[0][0] == "Kokoro speed", warnings
    assert "0.5" in warnings[0][1] and "2.0" in warnings[0][1]
    assert not panel._busy.is_set() and not output_base.exists(), "nothing was frozen, reserved or started"


@pytest.mark.parametrize("typed", ["0.5", "2.0", "1.25", " 1 "])
def test_a_kokoro_speed_in_range_is_accepted(typed):
    assert panel_module.kokoro_speed_problem(typed) == ""


def test_the_speed_check_is_kokoros_alone(make_panel, output_base, tmp_path, monkeypatch, stubs):
    """An Edge run never reads the Kokoro speed, so a leftover bad value there stops nothing."""
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    panel.kokoro_speed_var.set("nan")
    params = run_attempt(panel)
    assert params["backend"] == "edge"
