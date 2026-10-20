"""Plan 01B checkpoint A3 through the real TTS panel: the speech-preparation snapshot is taken once at run start,
frozen into the run, handed to the engine, and re-used unchanged by Retry Failed whatever happens to the user files.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

tk = pytest.importorskip("tkinter")

from shared import config as shared_config  # noqa: E402
from shared.job_control import JobState  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
from tts.speech import pipeline  # noqa: E402

from test_tts_importing import make_config, make_panel, output_base, stubs, tk_root  # noqa: E402,F401
from test_tts_jobs import direct_panel, failing_stubs, run_attempt  # noqa: E402,F401


def v1_config():
    return dataclasses.replace(make_config(), tts=shared_config.TtsConfig(speech_prep="v1"))


def write_glossary(directory, spoken: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "glossary.user.json").write_text(json.dumps(
        {"version": 1, "entries": [{"id": "t", "written": "Tamar", "spoken": spoken}]}), encoding="utf-8")


@pytest.fixture()
def user_dir(tmp_path, monkeypatch):
    directory = tmp_path / "runtime-data" / "speech"
    monkeypatch.setattr(panel_module, "SPEECH_USER_DIR", directory)
    return directory


def test_an_off_run_hands_no_snapshot_to_the_engine_and_says_nothing(
    make_panel, output_base, tmp_path, failing_stubs, user_dir, monkeypatch
):
    panel, _ = direct_panel(make_panel, tmp_path, "good.txt")
    params = run_attempt(panel)
    details = panel.log.details
    assert params["snapshot"].tool_options["speech_prep"] is pipeline.OFF
    assert "speech_prep" not in failing_stubs.conversion_jobs[0]
    assert not [d for d in details if "Speech preparation" in str(d)]


def test_retry_failed_uses_the_original_snapshot_whatever_the_files_now_say(
    make_panel, output_base, tmp_path, failing_stubs, user_dir, monkeypatch
):
    write_glossary(user_dir, "tay mar")
    panel, _ = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt", effective_config=v1_config())
    first = run_attempt(panel)
    details = panel.log.details
    original = first["snapshot"].tool_options["speech_prep"]
    assert original.enabled and original.glossary[0].spoken == "tay mar"
    assert first["speech_prep"] is original
    assert all(job["speech_prep"] is original for job in failing_stubs.conversion_jobs)
    assert any(str(d).startswith("Speech preparation v1") for d in details)
    assert panel._result.state is JobState.COMPLETED_WITH_FAILURES

    write_glossary(user_dir, "tah mar")                                      # edited before the retry
    (user_dir / "modes.user.json").write_text("{corrupt", encoding="utf-8")  # and a broken file beside it
    second = run_attempt(panel, panel.retry_failed)
    assert second["speech_prep"] is original
    assert failing_stubs.conversion_jobs[-1]["speech_prep"] is original
    assert original.glossary[0].spoken == "tay mar"

    third = run_attempt(panel)                                               # a NEW run reads the files again
    fresh = third["speech_prep"]
    assert fresh is not original and fresh.glossary[0].spoken == "tah mar"
    assert any("user mode overrides ignored" in note for note in fresh.notes)


def test_a_corrupt_user_file_never_fails_the_run(make_panel, output_base, tmp_path, failing_stubs, user_dir):
    user_dir.mkdir(parents=True)
    (user_dir / "glossary.user.json").write_bytes(b"\xff\xfe not json")
    panel, _ = direct_panel(make_panel, tmp_path, "good.txt", effective_config=v1_config())
    params = run_attempt(panel)
    snapshot = params["speech_prep"]
    assert snapshot.enabled and snapshot.glossary == () and "user glossary ignored" in snapshot.notes[0]
    assert panel._result.state is JobState.SUCCEEDED
