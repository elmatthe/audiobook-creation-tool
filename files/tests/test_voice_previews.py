"""v0.6.7 CP6 (owner ruling Q8) — the permanent 10-second voice previews, their rights record, and the tool that guards both.

The ruling: previews stay in scope, but a preview is generated or published only for a voice whose output rights and source
permissions are confirmed; Edge and cloned-voice previews stay unpublished while rights are unresolved; a per-voice
rights/status manifest is kept; and the 28-preview deliverable is never declared complete while any preview is blocked.
These tests pin each of those, and prove the audio that is committed is valid (the tool's own validator, re-run here).
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "files" / "dev-tools"))

import voice_previews as vp  # noqa: E402


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    """A scratch copy of the previews folder; the tool is pointed at it so nothing real is modified."""
    target = tmp_path / "voice-previews"
    shutil.copytree(vp.PREVIEW_DIR, target)
    monkeypatch.setattr(vp, "PREVIEW_DIR", target)
    monkeypatch.setattr(vp, "MANIFEST", target / "previews.json")
    monkeypatch.setattr(vp, "README", target / "README.md")
    return target


def manifest():
    return json.loads(vp.MANIFEST.read_text("utf-8"))


# --------------------------------------------------------------------------- #
# The committed folder
# --------------------------------------------------------------------------- #
def test_the_committed_folder_is_consistent_with_the_registry_the_files_and_the_readme():
    assert vp.check() == []


def test_the_manifest_lists_exactly_the_28_roster_voices_in_registry_order():
    from tts import voice_registry

    ids = [v["voice_id"] for v in manifest()["voices"]]
    assert ids == [e.voice_id for e in voice_registry.VOICES] and len(ids) == 28
    excluded = ("dylan", "eric", "ono", "serena", "sohee", "uncle", "vivian")
    assert not any(any(name in voice_id for name in excluded) for voice_id in ids)  # rejected presets never appear


def test_rights_gate_every_preview_and_the_recorded_basis_is_never_empty():
    for record in manifest()["voices"]:
        rights, preview = record["rights"], record["preview"]
        assert rights["basis"] and rights["status"] in (vp.RIGHTS_CONFIRMED, vp.RIGHTS_UNRESOLVED), record["voice_id"]
        if preview["status"] == vp.PREVIEW_GENERATED:
            assert rights["status"] == vp.RIGHTS_CONFIRMED and rights["evidence"], record["voice_id"]
        if rights["status"] == vp.RIGHTS_UNRESOLVED:
            assert preview["status"] == vp.PREVIEW_BLOCKED and preview["file"] is None, record["voice_id"]


def test_edge_chatterbox_and_all_cloned_voices_are_blocked_and_their_reasons_say_why():
    by_backend: dict[str, list] = {}
    for record in manifest()["voices"]:
        by_backend.setdefault(record["backend"], []).append(record)
    for record in by_backend["edge"]:
        assert record["preview"]["status"] == vp.PREVIEW_BLOCKED and "Microsoft" in record["rights"]["basis"]
    for record in by_backend["chatterbox"]:
        assert record["preview"]["status"] == vp.PREVIEW_BLOCKED and "reference recording" in record["rights"]["basis"]
    clones = [r for r in by_backend["qwen3"] if r["voice_id"] not in ("qwen3-aiden", "qwen3-ryan")]
    assert len(clones) == 6 and all(r["preview"]["status"] == vp.PREVIEW_BLOCKED for r in clones)
    assert all("reference recording" in r["rights"]["basis"] for r in clones)
    assert not any(p.stem.startswith(("en-US", "chatterbox", "qwen3-female", "qwen3-male"))
                   for p in vp.PREVIEW_DIR.glob("*.wav"))  # not a single blocked voice has a file


def test_the_available_set_is_the_nine_kokoro_voices_and_the_two_qwen3_presets():
    available = sorted(v["voice_id"] for v in manifest()["voices"] if v["preview"]["status"] == vp.PREVIEW_GENERATED)
    assert available == sorted(["af_heart", "af_bella", "am_michael", "am_fenrir", "am_puck", "am_onyx", "bf_emma",
                                "bm_george", "bm_daniel", "qwen3-aiden", "qwen3-ryan"])
    assert vp.counts(manifest()) == {"total": 28, "generated": 11, "pending": 0, "blocked": 17}


def test_the_confirmed_voices_carry_evidence_a_reader_can_check():
    for record in manifest()["voices"]:
        if record["rights"]["status"] != vp.RIGHTS_CONFIRMED:
            continue
        for item in record["rights"]["evidence"]:
            assert item["url"].startswith("https://huggingface.co/") and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert "Apache-2.0" in record["rights"]["basis"] or "apache-2.0" in record["rights"]["basis"].lower()


def confirm_everything(data):
    """A manifest in which every voice has confirmed rights and a generated preview (what a finished set would be)."""
    for record in data["voices"]:
        record["rights"] = {"status": vp.RIGHTS_CONFIRMED, "basis": "test", "evidence": [{"url": "https://example.test"}]}
        record["preview"] = {"status": vp.PREVIEW_GENERATED, "file": f"{record['voice_id']}.wav", "sha256": "0" * 64}
    return data


def test_the_readme_never_calls_an_incomplete_set_complete():
    text = vp.README.read_text("utf-8")
    assert "**11 of 28 previews are available.**" in text and "not a complete set until every row is available" in text
    assert text == vp.render_readme(manifest())
    complete = vp.render_readme(confirm_everything(manifest()))  # only when every row has rights AND a preview
    assert "**28 of 28 previews are available.**" in complete and "not a complete set" not in complete


def test_a_preview_marked_generated_without_confirmed_rights_is_never_published_counted_or_claimed():
    data = manifest()
    steffan = data["voices"][0]
    assert steffan["rights"]["status"] == vp.RIGHTS_UNRESOLVED
    steffan["preview"] = {"status": vp.PREVIEW_GENERATED, "file": "en-US-SteffanNeural.wav", "sha256": "0" * 64}
    assert not vp.is_available(steffan) and vp.counts(data)["generated"] == 11  # never over-claims
    with pytest.raises(vp.PreviewError, match="inconsistent"):
        vp.render_readme(data)
    complete = confirm_everything(manifest())
    complete["voices"][0]["rights"]["status"] = vp.RIGHTS_UNRESOLVED  # one withdrawn right out of 28
    with pytest.raises(vp.PreviewError):
        vp.render_readme(complete)
    assert any("rights are not confirmed" in p for p in vp.manifest_problems(data))


def test_status_and_generate_refuse_a_manifest_that_contradicts_the_rights_rule(folder, capsys, monkeypatch):
    data = manifest()
    data["voices"][0]["preview"] = {"status": vp.PREVIEW_GENERATED, "file": "x.wav", "sha256": "0" * 64}
    vp.MANIFEST.write_text(json.dumps(data), encoding="utf-8")
    assert vp.main(["status"]) == 3 and "PROBLEM" in capsys.readouterr().out

    def forbidden(*args):
        pytest.fail("an engine ran against an inconsistent manifest")

    monkeypatch.setattr(vp, "synthesize", forbidden)
    with pytest.raises(vp.PreviewError, match="inconsistent"):
        vp.generate(["af_heart"], log=lambda m: None)


def test_sync_refreshes_a_confirmed_basis_but_never_reconfirms_a_withdrawn_voice(folder):
    data = manifest()
    kokoro = next(v for v in data["voices"] if v["voice_id"] == "af_heart")
    kokoro["rights"]["basis"] = "stale text"
    bella = next(v for v in data["voices"] if v["voice_id"] == "af_bella")
    bella["rights"] = {"status": vp.RIGHTS_UNRESOLVED, "basis": "owner withdrew this", "evidence": []}
    bella["preview"] = {"status": vp.PREVIEW_BLOCKED, "file": None}
    fresh = vp.sync(data)
    by_id = {v["voice_id"]: v for v in fresh["voices"]}
    assert by_id["af_heart"]["rights"]["basis"] == vp.KOKORO_BASIS
    assert by_id["af_bella"]["rights"] == {"status": vp.RIGHTS_UNRESOLVED, "basis": "owner withdrew this", "evidence": []}


def test_the_recorded_basis_does_not_repeat_the_claim_the_kokoro_card_contradicts():
    """The pinned card says synthetic audio from closed TTS providers was part of the training data."""
    for text in (vp.KOKORO_BASIS, vp.QWEN3_PRESET_BASIS):
        assert "no synthetic audio" not in text.lower() and "involved" not in text.lower()
        assert "ACT supplies no reference recording" in text
    assert "synthetic audio from closed TTS models" in vp.KOKORO_BASIS


def test_writes_are_atomic_and_leave_no_temporary_file(folder):
    vp.write_atomic(folder / "x.txt", "one")
    vp.write_atomic(folder / "x.txt", "two")
    assert (folder / "x.txt").read_text("utf-8") == "two" and not list(folder.glob("*.tmp"))
    vp.save_manifest({**manifest(), "_failures": ["not data"]})
    assert "_failures" not in manifest() and not list(folder.glob("*.tmp"))


def folder_state(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def succeed(entry, text_path, out_wav):
    write_wav(out_wav, seconds=10.0, amplitude=0.1)


def boom(*args, **kwargs):
    raise OSError("disk full")


def test_a_failure_while_reading_the_new_takes_metadata_leaves_everything_as_it_was(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", succeed)
    before = folder_state(folder)
    real_sha = vp.sha256_file
    calls = []

    def fail_on_the_candidate(path):
        calls.append(path.name)
        if path.name.endswith(".candidate.wav"):
            raise OSError("antivirus has the file open")
        return real_sha(path)

    monkeypatch.setattr(vp, "sha256_file", fail_on_the_candidate)
    data = vp.generate(["af_heart"], log=lambda m: None)
    monkeypatch.setattr(vp, "sha256_file", real_sha)
    assert "af_heart.candidate.wav" in calls and "antivirus" in data["_failures"][0]
    assert folder_state(folder) == before  # old audio, old manifest, old README: nothing changed, no strays
    assert vp.check(None, folder) == []


@pytest.mark.parametrize("failing", ["save_manifest", "write_readme"])
def test_a_failure_while_publishing_rolls_the_audio_manifest_and_readme_back(folder, monkeypatch, failing):
    monkeypatch.setattr(vp, "synthesize", succeed)
    before = folder_state(folder)
    monkeypatch.setattr(vp, failing, boom)
    with pytest.raises(OSError, match="disk full"):
        vp.generate(["af_heart"], log=lambda m: None)
    assert folder_state(folder) == before and not (folder / ".scratch").exists()


def test_a_failure_while_publishing_a_first_preview_removes_it_again(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", succeed)
    (folder / "af_heart.wav").unlink()
    data = manifest()
    heart = next(v for v in data["voices"] if v["voice_id"] == "af_heart")
    heart["preview"] = {"status": vp.PREVIEW_PENDING, "file": None}
    vp.MANIFEST.write_text(json.dumps(data), encoding="utf-8")
    vp.write_readme(data)
    before = folder_state(folder)
    monkeypatch.setattr(vp, "write_readme", boom)
    with pytest.raises(OSError):
        vp.generate(["af_heart"], log=lambda m: None)
    assert folder_state(folder) == before and not (folder / "af_heart.wav").exists()


def test_a_successful_take_replaces_the_file_and_the_record_together(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", succeed)
    old_hash = next(v for v in manifest()["voices"] if v["voice_id"] == "af_heart")["preview"]["sha256"]
    logs = []
    data = vp.generate(["af_heart"], log=logs.append)
    heart = next(v for v in data["voices"] if v["voice_id"] == "af_heart")
    assert heart["preview"]["sha256"] != old_hash and heart["preview"]["sha256"] == vp.sha256_file(folder / "af_heart.wav")
    assert heart["preview"]["generated_on"] == datetime.date.today().isoformat() and not data["_failures"]
    assert vp.check(None, folder) == [] and not (folder / ".scratch").exists()
    assert any(line.startswith("GENERATED af_heart") for line in logs)


def test_the_folder_holds_only_audio_the_manifest_lists_plus_its_two_documents_and_stays_small():
    names = sorted(p.name for p in vp.PREVIEW_DIR.iterdir())
    listed = sorted(v["preview"]["file"] for v in manifest()["voices"] if v["preview"]["file"])
    assert names == sorted(listed + ["previews.json", "README.md"])
    assert sum(p.stat().st_size for p in vp.PREVIEW_DIR.iterdir()) < 6 * 10**6  # about 4.7 MB: a public repo is not a media store


def test_no_private_path_or_account_name_is_in_the_published_record():
    text = (vp.PREVIEW_DIR / "previews.json").read_text("utf-8") + vp.README.read_text("utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)[\\/]", text)  # a drive path into a home folder
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)  # an e-mail address
    assert "AppData" not in text and "/home/" not in text


def test_the_previews_are_not_part_of_the_release_archive_or_bundled_anywhere():
    from shared import release

    assert not any("voice-previews" in asset for asset in release.REFERENCE_ASSETS)
    assert "voice-previews" not in " ".join(release.ROOT_FILES)
    tracked = subprocess.run(["git", "ls-files", "scripts"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert "voice-previews" not in tracked


# --------------------------------------------------------------------------- #
# The validator
# --------------------------------------------------------------------------- #
def write_wav(path, seconds=10.0, rate=24000, amplitude=0.2, subtype="PCM_16", channels=1):
    t = np.arange(int(rate * seconds)) / rate
    wave = (amplitude * np.sin(2 * np.pi * 220 * t)).astype("float32")
    if channels == 2:
        wave = np.stack([wave, wave], axis=1)
    sf.write(str(path), wave, rate, subtype=subtype)
    return path


def test_a_good_preview_has_no_problems(tmp_path):
    assert vp.audio_problems(write_wav(tmp_path / "ok.wav")) == []


@pytest.mark.parametrize("kwargs, expected", [
    ({"seconds": 3}, "outside 8-13 s"),
    ({"seconds": 25}, "outside 8-13 s"),
    ({"amplitude": 1.0}, "clips"),
    ({"amplitude": 0.0001}, "nearly silent"),
    ({"channels": 2}, "must be mono"),
    ({"rate": 16000}, "sample rate 16000"),
    ({"subtype": "PCM_24"}, "16-bit PCM WAV"),
    ({"subtype": "FLOAT"}, "16-bit PCM WAV"),
])
def test_every_way_a_preview_can_be_unusable_is_named(tmp_path, kwargs, expected):
    problems = vp.audio_problems(write_wav(tmp_path / "bad.wav", **kwargs))
    assert any(expected in p for p in problems), problems


def test_an_unreadable_file_is_a_problem_not_an_exception(tmp_path):
    (tmp_path / "junk.wav").write_bytes(b"not audio")
    assert "unreadable audio" in vp.audio_problems(tmp_path / "junk.wav")[0]


def test_trimming_keeps_a_short_margin_and_never_touches_the_speech():
    rate = 24000
    speech = (0.3 * np.cos(2 * np.pi * 300 * np.arange(rate) / rate)).astype("float32")  # loud from the very first sample
    padded = np.concatenate([np.zeros(rate * 2, dtype="float32"), speech, np.zeros(rate * 3, dtype="float32")])
    trimmed = vp.trim_edges(padded, rate)
    margin = int(rate * vp.EDGE_SILENCE_MS / 1000)
    assert abs(trimmed.size - (speech.size + 2 * margin)) <= 2
    assert np.array_equal(trimmed[margin:margin + speech.size], speech)
    assert vp.trim_edges(np.zeros(100, dtype="float32"), rate).size == 100  # all silence: returned unchanged


# --------------------------------------------------------------------------- #
# The tool refuses what the rights record forbids, and the checker catches every inconsistency
# --------------------------------------------------------------------------- #
def test_generate_refuses_a_voice_whose_rights_are_not_confirmed(folder, monkeypatch):
    def forbidden(entry, text_path, out_wav):
        pytest.fail(f"an engine was run for {entry.voice_id}, whose rights are unresolved")

    monkeypatch.setattr(vp, "synthesize", forbidden)
    logs = []
    before = manifest()
    data = vp.generate(["en-US-SteffanNeural", "chatterbox-female-1", "qwen3-male-1"], log=logs.append)
    assert [l for l in logs if l.startswith("BLOCKED")] == [
        "BLOCKED  en-US-SteffanNeural: rights not confirmed; no preview is made",
        "BLOCKED  chatterbox-female-1: rights not confirmed; no preview is made",
        "BLOCKED  qwen3-male-1: rights not confirmed; no preview is made"]
    assert vp.counts(data) == vp.counts(before) and not (folder / "en-US-SteffanNeural.wav").exists()


def test_a_voice_that_fails_is_reported_and_does_not_lose_the_others(folder, monkeypatch):
    def flaky(entry, text_path, out_wav):
        if entry.voice_id == "af_heart":
            raise RuntimeError("the engine fell over")
        write_wav(out_wav, seconds=10.0)

    monkeypatch.setattr(vp, "synthesize", flaky)
    before = (folder / "af_heart.wav").read_bytes()
    logs = []
    data = vp.generate(["af_heart", "af_bella"], log=logs.append)
    assert any(l.startswith("FAILED   af_heart") and "fell over" in l for l in logs)
    by_id = {v["voice_id"]: v for v in data["voices"]}
    assert by_id["af_bella"]["preview"]["status"] == vp.PREVIEW_GENERATED
    assert (folder / "af_heart.wav").read_bytes() == before  # the failed voice keeps its previous good preview
    assert data["_failures"] and vp.check({k: v for k, v in data.items() if k != "_failures"}, folder) == []


def test_a_take_that_fails_validation_never_replaces_the_published_file(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", lambda entry, text_path, out_wav: write_wav(out_wav, seconds=2.0))
    before = (folder / "af_heart.wav").read_bytes()
    data = vp.generate(["af_heart"], log=lambda m: None)
    assert "outside 8-13 s" in data["_failures"][0]
    assert (folder / "af_heart.wav").read_bytes() == before
    assert not (folder / ".scratch").exists() and not list(folder.glob("*.candidate.wav"))  # no scratch left behind
    assert vp.check({k: v for k, v in data.items() if k != "_failures"}, folder) == []


def test_the_checker_catches_each_kind_of_inconsistency(folder):
    base = manifest()

    def problems(mutate):
        data = json.loads(json.dumps(base))
        mutate(data)
        return vp.check(data, folder)

    assert any("registry" in p for p in problems(lambda d: d["voices"].pop()))
    assert any("registry" in p for p in problems(lambda d: d["voices"].reverse()))
    assert any("not a preview for a voice" in p or "rights are not confirmed" in p for p in problems(
        lambda d: d["voices"][0]["preview"].update(status="generated", file="en-US-SteffanNeural.wav")))
    assert any("unresolved but the preview" in p for p in problems(
        lambda d: d["voices"][0]["preview"].update(status="pending")))
    assert any("no evidence" in p for p in problems(lambda d: d["voices"][5]["rights"].update(evidence=[])))
    assert any("no recorded basis" in p for p in problems(lambda d: d["voices"][5]["rights"].update(basis="")))
    assert any("does not match its recorded SHA-256" in p for p in problems(
        lambda d: d["voices"][5]["preview"].update(sha256="0" * 64)))
    assert any("sample text differs" in p for p in problems(lambda d: d.update(sample_text="another sentence")))
    (folder / "af_heart.wav").write_bytes(b"x")
    assert any("af_heart" in p and ("SHA-256" in p or "unreadable" in p) for p in vp.check(base, folder))


def test_the_checker_flags_stray_audio_a_blocked_voices_file_and_a_stale_readme(folder):
    shutil.copy(folder / "af_heart.wav", folder / "extra-take.wav")
    shutil.copy(folder / "af_heart.wav", folder / "en-US-SteffanNeural.wav")
    (folder / "README.md").write_text("old", encoding="utf-8")
    found = " | ".join(vp.check(None, folder))
    assert "extra-take.wav" in found and "en-US-SteffanNeural" in found and "README.md is out of date" in found


def test_the_checker_flags_a_missing_preview_file(folder):
    (folder / "bm_daniel.wav").unlink()
    assert any("bm_daniel: the preview file is missing" in p for p in vp.check(None, folder))


def test_sync_adds_a_new_registry_voice_as_blocked_or_pending_never_as_available(folder, monkeypatch):
    from tts import voice_registry

    extra = voice_registry.VoiceEntry(backend="qwen3", voice_id="qwen3-new-one", display_label="Qwen3 - New One",
                                      group_label=voice_registry.QWEN3_GROUP_LABEL,
                                      timing_preset=voice_registry._qwen3_preset())
    monkeypatch.setattr(vp, "registry_voices", lambda: [*voice_registry.VOICES, extra])
    data = vp.sync(manifest())
    new = data["voices"][-1]
    assert new["voice_id"] == "qwen3-new-one" and new["preview"]["status"] == vp.PREVIEW_BLOCKED
    assert new["rights"]["status"] == vp.RIGHTS_UNRESOLVED  # a new voice is blocked until someone confirms its rights


def test_status_reports_how_many_are_blocked_and_exits_nonzero_while_any_are(capsys):
    assert vp.main(["status"]) == 2
    out = capsys.readouterr().out
    assert "11 of 28 previews available; 17 blocked, 0 pending." in out


def test_a_failed_publish_gives_back_the_record_and_a_readme_that_was_already_rewritten(folder, monkeypatch):
    data = manifest()
    heart = next(v for v in data["voices"] if v["voice_id"] == "af_heart")
    previous = dict(heart["preview"])
    candidate = folder / "candidate.wav"
    write_wav(candidate, seconds=10.0, amplitude=0.1)
    meta = {**previous, "sha256": vp.sha256_file(candidate)}
    scratch = folder / ".scratch"
    scratch.mkdir()
    before = folder_state(folder)

    def write_then_fail(d):
        vp.README.write_text("half-written garbage", encoding="utf-8")  # a README that did change before the failure
        raise OSError("disk full")

    monkeypatch.setattr(vp, "write_readme", write_then_fail)
    with pytest.raises(OSError):
        vp.publish(heart, meta, candidate, folder / "af_heart.wav", data, scratch)
    assert heart["preview"] == previous  # the in-memory record is not left describing a take that was not published
    after = folder_state(folder)
    assert after["README.md"] == before["README.md"] and after["af_heart.wav"] == before["af_heart.wav"]
    assert after["previews.json"] == before["previews.json"]


def test_a_write_that_fails_part_way_leaves_the_previous_bytes_and_no_temporary_file(folder, monkeypatch):
    vp.write_atomic(folder / "x.txt", "published")
    monkeypatch.setattr(vp.os, "replace", boom)  # the step that makes the new text visible fails
    with pytest.raises(OSError):
        vp.write_atomic(folder / "x.txt", "new text that must not appear")
    monkeypatch.undo()
    assert (folder / "x.txt").read_text("utf-8") == "published" and not list(folder.glob("*.tmp"))


def test_a_rollback_needs_no_free_disk_space_because_it_renames(folder, monkeypatch):
    """The manifest was published, then the README write found the disk full; nothing new may be written to undo it."""
    monkeypatch.setattr(vp, "synthesize", succeed)
    before = folder_state(folder)
    no_space_message = "no space left on device"

    def disk_fills_up(data):
        def refuse(*args, **kwargs):
            raise OSError(no_space_message)

        for owner, name in ((Path, "write_bytes"), (Path, "write_text"), (vp.shutil, "copyfile")):
            monkeypatch.setattr(owner, name, refuse)
        raise OSError(no_space_message)

    monkeypatch.setattr(vp, "write_readme", disk_fills_up)
    with pytest.raises(OSError, match=no_space_message):
        vp.generate(["af_heart"], log=lambda m: None)
    monkeypatch.undo()
    assert folder_state(folder) == before and not (folder / ".scratch").exists()


def test_a_publish_that_cannot_be_undone_says_where_the_recovery_files_are_and_keeps_them(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", succeed)
    before = folder_state(folder)
    real_replace = vp.os.replace
    state = {"publishing": False}

    def replace(src, dst):
        if state["publishing"] and Path(dst).name == "README.md":
            raise OSError("antivirus holds README.md")  # the rollback's own rename fails
        return real_replace(src, dst)

    def readme_fails(data):
        state["publishing"] = True
        raise OSError("disk full")

    monkeypatch.setattr(vp, "write_readme", readme_fails)
    monkeypatch.setattr(vp.os, "replace", replace)
    with pytest.raises(vp.RollbackError, match="Recovery files are in"):
        vp.generate(["af_heart"], log=lambda m: None)
    monkeypatch.undo()
    scratch = folder / ".scratch"
    assert (scratch / "README.md.bak").is_file()  # the one document that could not be put back is still on disk
    assert (folder / "af_heart.wav").read_bytes() == before["af_heart.wav"]  # what could be restored, was
    assert (folder / "previews.json").read_bytes() == before["previews.json"]


@pytest.mark.parametrize("argv", [["af_heart"], None])
@pytest.mark.parametrize("recovery_file", ["README.md.bak", "previews.json.bak", "af_heart.previous.wav"])
def test_a_run_never_cleans_up_recovery_files_a_failed_rollback_left_behind(folder, monkeypatch, argv, recovery_file):
    """Each recovery format alone must stop the run (removing either pattern from the guard fails a case here)."""
    scratch = folder / ".scratch"
    scratch.mkdir()
    (scratch / recovery_file).write_bytes(b"the only copy")
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("a take was made over unresolved recovery files"))
    with pytest.raises(vp.PreviewError, match="recovery files"):
        vp.generate(argv, log=lambda m: None)
    assert (scratch / recovery_file).read_bytes() == b"the only copy"


def test_ordinary_leftovers_in_the_scratch_folder_are_cleaned_up_by_the_next_run(folder, monkeypatch):
    scratch = folder / ".scratch"
    scratch.mkdir()
    (scratch / "af_heart.candidate.wav").write_bytes(b"debris from an interrupted run")
    monkeypatch.setattr(vp, "synthesize", succeed)
    vp.generate(["af_heart"], log=lambda m: None)
    assert not scratch.exists()
