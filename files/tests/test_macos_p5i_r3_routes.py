"""v0.8.x P5-I-R3: routes that used to start FFmpeg outside the containment.

* The local engines' (Qwen3, OmniVoice) one MP3 encode, ``qwen3_synth.encode_mp3``, started FFmpeg in a session of
  its own (``qwen3_process.spawn`` -> ``start_new_session``): nothing contained it, so it outlived its owner and was
  not ordered against Cancel. With an owner it is now a contained class-B child: in the guardian's group, stopped by a
  Cancel inside the bound, a stop that cannot be confirmed a failure. Without an owner (and on Windows) it runs as
  released.

Real processes: a stand-in ``ffmpeg`` for Cancel and exit codes, the real FFmpeg on a synthetic one-second WAV for the
normal path (no audiobook file, no model). macOS only.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

from shared import child_ownership
from shared import ffmpeg_utils
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController
from tts import qwen3_synth

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")


@pytest.fixture()
def owner(monkeypatch):
    made = child_ownership.Owner(lifeline=False)
    monkeypatch.setattr(sp, "_owner", made)
    yield made
    monkeypatch.undo()
    made.shutdown()


def _stand_in(folder: Path, body: str) -> Path:
    folder.mkdir(exist_ok=True)
    path = folder / "ffmpeg"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _until(predicate, seconds: float = 10.0) -> bool:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _wav(path: Path, seconds: float = 1.0, rate: int = 24000) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def test_the_local_engines_encode_is_a_contained_child_and_a_cancel_stops_it(owner, tmp_path):
    ffmpeg = _stand_in(tmp_path / "bin", "trap '' TERM\nsleep 60 &\nwait")
    work = tmp_path / "job"
    work.mkdir()
    controller = JobController("r3-encode", cancel_clock=time.monotonic)
    controller.start()
    box: dict = {}

    def encode():
        try:
            qwen3_synth.encode_mp3(work / "encode.wav", work / "encode.mp3", None, work_dir=work,
                                   cancel_check=controller.cancel_check, ffmpeg=str(ffmpeg))
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            box["error"] = exc

    thread = threading.Thread(target=encode, daemon=True)
    thread.start()
    assert _until(lambda: any(c.state == child_ownership.LIVE for c in owner.outstanding(controller.cancel_check)))
    child = next(c for c in owner.outstanding(controller.cancel_check))
    assert child.kind == child_ownership.CLASS_B
    assert os.getpgid(child.pid) == owner.guardian_pid(), "in the guardian's group: it ends with its owner"
    clicked = time.monotonic()
    controller.request_cancel()
    thread.join(10)
    assert not thread.is_alive() and isinstance(box.get("error"), ConversionCancelled), box
    assert time.monotonic() - clicked < sp.FFMPEG_STOP_S
    assert sp.containment_problem(controller.cancel_check) is None


def test_the_local_engines_encode_reports_a_failed_ffmpeg_with_its_last_words(owner, tmp_path):
    ffmpeg = _stand_in(tmp_path / "bin", "echo 'Invalid data found' >&2\nexit 3")
    work = tmp_path / "job"
    work.mkdir()
    with pytest.raises(qwen3_synth.Qwen3Failed, match=r"exit code 3\).*Invalid data found"):
        qwen3_synth.encode_mp3(work / "encode.wav", work / "encode.mp3", None, work_dir=work, ffmpeg=str(ffmpeg))


@pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires the app's verified FFmpeg")
def test_the_local_engines_encode_still_makes_the_mp3_contained(owner, tmp_path):
    work = tmp_path / "job"
    work.mkdir()
    wav = _wav(work / "encode.wav")
    qwen3_synth.encode_mp3(wav, work / "encode.mp3", None, work_dir=work)
    made = work / "encode.mp3"
    assert made.exists() and made.stat().st_size > 1000
    assert owner.outstanding() == [] or all(c.kind == child_ownership.GUARDIAN_KIND for c in owner.outstanding())


def test_without_an_owner_the_encode_runs_as_released(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_owner", None)
    ffmpeg = _stand_in(tmp_path / "bin", 'for last; do :; done\necho made > "$last"')
    work = tmp_path / "job"
    work.mkdir()
    qwen3_synth.encode_mp3(work / "encode.wav", work / "encode.mp3", None, work_dir=work, ffmpeg=str(ffmpeg))
    assert (work / "encode.mp3").read_text().strip() == "made"
