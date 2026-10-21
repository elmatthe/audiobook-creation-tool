"""v0.6.7 CP6 — the permanent 10-second voice previews, their publication record, and the tool that guards both.

Owner ruling Q8 (2026-10-19) made a preview publishable only for a voice whose rights were confirmed. The owner's decision
of 2026-10-20 supersedes that for preview audio: short generated previews of all 28 registered voices are authorized. It is a
publication decision, not a third-party legal finding, and it covers generated audio only. These tests pin what remains
true: every authorized voice is generated or *pending with an exact reason* (never silently blocked or faked), a withdrawn
voice is still never generated, a Qwen3 clone is only made from its approved transcript, the 28-preview deliverable is
never declared complete while any preview is missing, and the audio that is committed is valid and distinct per voice.
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


EDGE_IDS = ["en-US-SteffanNeural", "en-US-AndrewNeural", "en-US-AriaNeural", "en-US-AvaNeural", "en-US-JennyNeural"]
CHATTERBOX_IDS = [f"chatterbox-{g}-{n}" for g, n in (("female", 1), ("female", 2), ("male", 1), ("male", 2), ("male", 3),
                                                      ("male", 4))]
CLONE_IDS = [f"qwen3-{g}-{n}" for g, n in (("female", 1), ("female", 2), ("male", 1), ("male", 2), ("male", 3), ("male", 4))]
KOKORO_IDS = ["af_heart", "af_bella", "am_michael", "am_fenrir", "am_puck", "am_onyx", "bf_emma", "bm_george", "bm_daniel"]
PRESET_IDS = ["qwen3-aiden", "qwen3-ryan"]


def record_of(voice_id, data=None):
    return next(v for v in (data or manifest())["voices"] if v["voice_id"] == voice_id)


def test_every_voice_is_authorized_and_each_record_is_internally_consistent():
    assert vp.manifest_problems(manifest()) == []
    for record in manifest()["voices"]:
        rights, preview = record["rights"], record["preview"]
        assert rights["basis"] and rights["status"] in vp.AUTHORIZED, record["voice_id"]  # nothing is blocked any more
        assert preview["status"] in (vp.PREVIEW_GENERATED, vp.PREVIEW_PENDING), record["voice_id"]
        if preview["status"] == vp.PREVIEW_GENERATED:
            assert preview["file"] and re.fullmatch(r"[0-9a-f]{64}", preview["sha256"]), record["voice_id"]
        else:
            assert preview["file"] is None and preview["pending_reason"], record["voice_id"]
        if rights["status"] == vp.RIGHTS_CONFIRMED:
            assert rights["evidence"], record["voice_id"]  # a license a reader can check


def test_the_owner_decision_is_recorded_as_a_publication_decision_not_a_legal_finding():
    data = manifest()
    decision = data["owner_decision"]
    assert decision == vp.OWNER_DECISION and data["schema"] == vp.SCHEMA == 2
    assert decision["date"] == "2026-10-20" and "28" in decision["decision"]
    assert "supersedes" in decision and "2026-10-19" in decision["supersedes"]  # the old rule is history, not erased
    assert "did not independently verify" in decision["verification"]  # no invented third-party legal opinion
    assert any("reference recordings" in item for item in decision["not_covered"])
    assert any("transcript" in item for item in decision["not_covered"])
    owner = sorted(v["voice_id"] for v in data["voices"] if v["rights"]["status"] == vp.RIGHTS_OWNER)
    assert owner == sorted(EDGE_IDS + CHATTERBOX_IDS + CLONE_IDS) == sorted(vp.OWNER_AUTHORIZED_VOICES)
    for voice_id in owner:
        basis = record_of(voice_id)["rights"]["basis"]
        assert "owner" in basis and "makes no claim" in basis and "independently" in basis, voice_id
        assert record_of(voice_id)["rights"]["authorized_on"] == "2026-10-20"
    for voice_id in KOKORO_IDS + PRESET_IDS:
        assert record_of(voice_id)["rights"]["status"] == vp.RIGHTS_CONFIRMED  # license evidence is untouched


def test_edge_and_chatterbox_previews_are_generated_and_the_clones_are_pending_with_an_exact_reason():
    for voice_id in EDGE_IDS + CHATTERBOX_IDS + KOKORO_IDS + PRESET_IDS:
        record = record_of(voice_id)
        assert record["preview"]["status"] == vp.PREVIEW_GENERATED, voice_id
        assert (vp.PREVIEW_DIR / record["preview"]["file"]).is_file(), voice_id
    for record in manifest()["voices"]:
        if record["preview"]["status"] == vp.PREVIEW_PENDING:  # whatever is still missing must be a clone, and say why
            assert record["voice_id"] in CLONE_IDS, record["voice_id"]
            reason = record["preview"]["pending_reason"]
            assert "transcript" in reason and "SHA-256" in reason and "not generated yet" in reason
            assert not (vp.PREVIEW_DIR / f"{record['voice_id']}.wav").exists()  # and no stand-in file exists for it


def test_no_two_previews_are_the_same_recording_so_none_is_a_copy_under_another_name():
    hashes = {}
    for record in manifest()["voices"]:
        if record["preview"]["status"] == vp.PREVIEW_GENERATED:
            digest = vp.sha256_file(vp.PREVIEW_DIR / record["preview"]["file"])
            assert digest == record["preview"]["sha256"]
            assert hashes.setdefault(digest, record["voice_id"]) == record["voice_id"], (digest, record["voice_id"])
            assert record["preview"]["file"] == f"{record['voice_id']}.wav"


def test_the_counts_add_up_and_nothing_is_blocked():
    c = vp.counts(manifest())
    generated = [v for v in manifest()["voices"] if v["preview"]["status"] == vp.PREVIEW_GENERATED]
    assert c == {"total": 28, "generated": len(generated), "pending": 28 - len(generated), "blocked": 0}
    assert c["generated"] >= 22  # nine Kokoro, two Qwen3 presets, five Edge, six Chatterbox


def test_the_confirmed_voices_carry_evidence_a_reader_can_check():
    for record in manifest()["voices"]:
        if record["rights"]["status"] != vp.RIGHTS_CONFIRMED:
            continue
        for item in record["rights"]["evidence"]:
            assert item["url"].startswith("https://huggingface.co/") and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert "Apache-2.0" in record["rights"]["basis"] or "apache-2.0" in record["rights"]["basis"].lower()


def complete_set(data):
    """A manifest in which every voice is authorized and has a generated preview (what a finished set would be)."""
    for record in data["voices"]:
        if record["rights"]["status"] == vp.RIGHTS_UNRESOLVED:
            record["rights"] = {"status": vp.RIGHTS_CONFIRMED, "basis": "test", "evidence": [{"url": "https://example.test"}]}
        record["preview"] = {"status": vp.PREVIEW_GENERATED, "file": f"{record['voice_id']}.wav", "sha256": "0" * 64}
        if vp.is_clone(record):
            record["preview"]["generation_profile"] = vp.current_clone_profile()
            record["preview"]["transcript"] = {"status": vp.TRANSCRIPT_APPROVED, "text_sha256": "1" * 64}
            record["preview"]["seed_take"] = 0
            record["preview"]["leading_fragment_trimmed_ms"] = 0
    return data


def reset_clones_to_pending(folder):
    """Put the six Qwen3 clones back to pending in the scratch copy, so these tests do not depend on how complete the real folder is."""
    registry = {e.voice_id: e for e in vp.registry_voices()}
    data = manifest()
    for voice_id in CLONE_IDS:
        record_of(voice_id, data)["preview"] = {"status": vp.PREVIEW_PENDING, "file": None,
                                                 "pending_reason": vp.pending_reason_for(registry[voice_id])}
        (folder / f"{voice_id}.wav").unlink(missing_ok=True)
    vp.MANIFEST.write_text(json.dumps(data), encoding="utf-8")
    vp.write_readme(data)



def withdraw(record):
    """What the owner withdrawing a voice looks like in the record."""
    record["rights"] = {"status": vp.RIGHTS_UNRESOLVED, "basis": "owner withdrew this", "evidence": []}
    record["preview"] = {"status": vp.PREVIEW_BLOCKED, "file": None}


def test_the_readme_never_calls_an_incomplete_set_complete():
    text = vp.README.read_text("utf-8")
    c = vp.counts(manifest())
    assert text == vp.render_readme(manifest())
    assert f"**{c['generated']} of 28 previews are available.**" in text
    if c["generated"] < 28:
        assert "not a complete set until every row is available" in text and "pending generation" in text
        assert "Pending previews" in text and "transcript" in text
    complete = vp.render_readme(complete_set(manifest()))  # only when every row has authorization AND a preview
    assert "**28 of 28 previews are available.**" in complete and "not a complete set" not in complete
    assert "Pending previews" not in complete


def test_the_owner_listening_review_is_stated_only_for_a_complete_set_and_approves_no_transcript():
    """The 2026-10-20 review covered all 28 files; an incomplete set cannot claim it, and it is not a transcript approval."""
    complete = vp.render_readme(complete_set(manifest()))
    assert "## Owner listening review" in complete and "approved their audio quality" in complete
    assert "temperature 0.70 and sub-talker temperature 0.80" in complete
    assert "does not approve any reference transcript" in complete
    incomplete = manifest()
    incomplete["voices"][-1]["preview"] = {"status": vp.PREVIEW_PENDING, "file": None, "sha256": None,
                                           "pending_reason": "regenerating"}
    assert "Owner listening review" not in vp.render_readme(incomplete)


def test_the_readme_states_the_owner_decision_its_scope_and_that_no_third_party_terms_were_verified():
    text = vp.README.read_text("utf-8")
    assert "## Publication decision" in text and "2026-10-20" in text and "supersedes" in text
    assert "did not independently verify" in text and "makes no claim" in text
    assert "Generated preview audio only." in text and "reference recordings" in text
    assert "Separate gate" in text and "owner-approved transcript" in text
    assert "blocked" not in text.lower()  # the old "17 blocked" story is gone


def test_a_preview_for_a_withdrawn_voice_is_never_published_counted_or_claimed():
    data = manifest()
    steffan = record_of("en-US-SteffanNeural", data)
    before = vp.counts(data)["generated"]
    withdraw(steffan)
    steffan["preview"] = {"status": vp.PREVIEW_GENERATED, "file": "en-US-SteffanNeural.wav", "sha256": "0" * 64}
    assert not vp.is_available(steffan) and vp.counts(data)["generated"] == before - 1  # never over-claims
    with pytest.raises(vp.PreviewError, match="inconsistent"):
        vp.render_readme(data)
    complete = complete_set(manifest())
    withdraw(complete["voices"][0])  # one withdrawn voice out of 28
    assert vp.counts(complete)["generated"] == 27 and vp.counts(complete)["blocked"] == 1
    assert any("not authorized" in p for p in vp.manifest_problems(data))


def test_the_old_blanket_block_is_gone_but_a_withdrawal_still_blocks():
    data = manifest()
    assert vp.counts(data)["blocked"] == 0
    withdraw(record_of("chatterbox-male-2", data))
    assert vp.counts(data)["blocked"] == 1 and vp.manifest_problems(data) == []
    assert "withdrawn" in vp.render_readme(data)
    authorized_but_blocked = manifest()
    authorized_but_blocked["voices"][0]["preview"] = {"status": vp.PREVIEW_BLOCKED, "file": None}
    assert any("never blocked" in p for p in vp.manifest_problems(authorized_but_blocked))
    no_reason = manifest()
    record_of("qwen3-male-1", no_reason)["preview"] = {"status": vp.PREVIEW_PENDING, "file": None}
    assert any("exactly why" in p for p in vp.manifest_problems(no_reason))


def test_status_and_generate_refuse_a_manifest_that_contradicts_the_publication_rule(folder, capsys, monkeypatch):
    data = manifest()
    withdraw(data["voices"][0])
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
    heart["preview"] = {"status": vp.PREVIEW_PENDING, "file": None, "pending_reason": vp.GENERIC_PENDING}
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
    sizes = [p.stat().st_size for p in vp.PREVIEW_DIR.iterdir()]
    assert max(sizes) < 10**6  # a ten-second 24 kHz mono clip is about 0.5 MB; far below any hosting limit
    assert sum(sizes) < 16 * 10**6  # about 13.5 MB for all 28: a public repo is not a media store


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
def write_wav(path, seconds=10.0, rate=24000, amplitude=0.2, subtype="PCM_16", channels=1, lead=0.15):
    """A test tone that, like a real preview, begins from silence (``lead`` seconds of it); ``lead=0`` starts mid-sound."""
    t = np.arange(int(rate * seconds)) / rate
    wave = (amplitude * np.sin(2 * np.pi * 220 * t)).astype("float32")
    wave[:int(rate * lead)] = 0
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
def test_generate_refuses_a_voice_the_owner_has_withdrawn(folder, monkeypatch):
    def forbidden(entry, text_path, out_wav):
        pytest.fail(f"an engine was run for {entry.voice_id}, whose publication is withdrawn")

    data = manifest()
    for voice_id in ("en-US-SteffanNeural", "chatterbox-female-1", "qwen3-male-1"):
        withdraw(record_of(voice_id, data))
    (folder / "en-US-SteffanNeural.wav").unlink(missing_ok=True)
    (folder / "chatterbox-female-1.wav").unlink(missing_ok=True)
    vp.MANIFEST.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(vp, "synthesize", forbidden)
    logs = []
    before = vp.counts(manifest())
    result = vp.generate(["en-US-SteffanNeural", "chatterbox-female-1", "qwen3-male-1"], log=logs.append)
    assert [l for l in logs if l.startswith("BLOCKED")] == [
        "BLOCKED  en-US-SteffanNeural: publication is not authorized; no preview is made",
        "BLOCKED  chatterbox-female-1: publication is not authorized; no preview is made",
        "BLOCKED  qwen3-male-1: publication is not authorized; no preview is made"]
    assert vp.counts(result) == before and not (folder / "en-US-SteffanNeural.wav").exists()


def test_an_authorized_voice_the_machine_cannot_make_stays_pending_with_the_apps_own_reason(folder, monkeypatch):
    reset_clones_to_pending(folder)
    """No transcript, model or reference: reported, never faked, never counted as a failure, nothing written."""
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("an engine ran for a voice that is unavailable"))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: f"{entry.voice_id} needs its approved transcript")
    before = folder_state(folder)
    logs = []
    data = vp.generate(["qwen3-female-1", "qwen3-male-4"], log=logs.append)
    assert logs == ["PENDING  qwen3-female-1: qwen3-female-1 needs its approved transcript",
                    "PENDING  qwen3-male-4: qwen3-male-4 needs its approved transcript"]
    assert data["_failures"] == [] and folder_state(folder) == before
    assert not (folder / "qwen3-female-1.wav").exists() and not (folder / ".scratch").exists()
    assert record_of("qwen3-female-1", data)["preview"]["status"] == vp.PREVIEW_PENDING


def test_an_unavailable_voice_that_already_has_a_good_preview_keeps_it(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("an engine ran for a voice that is unavailable"))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: "the model is not installed here")
    before = folder_state(folder)
    logs = []
    vp.generate(["chatterbox-male-1"], log=logs.append)
    assert logs == ["PENDING  chatterbox-male-1: the model is not installed here; the existing preview is kept"]
    assert folder_state(folder) == before


def test_unavailable_reason_asks_the_apps_own_availability_and_never_substitutes(monkeypatch):
    from tts import chatterbox_synth, qwen3_runtime, voice_registry

    by_id = {e.voice_id: e for e in voice_registry.VOICES}
    asked = []
    monkeypatch.setattr(qwen3_runtime, "voice_availability", lambda vid: (asked.append(("qwen3", vid)), (False, "no transcript"))[1])
    monkeypatch.setattr(chatterbox_synth, "voice_availability", lambda vid: (asked.append(("cbx", vid)), (True, "ok"))[1])
    assert vp.unavailable_reason(by_id["qwen3-male-2"]) == "no transcript"
    assert vp.unavailable_reason(by_id["chatterbox-male-3"]) is None
    assert vp.unavailable_reason(by_id["en-US-AriaNeural"]) is None and vp.unavailable_reason(by_id["af_heart"]) is None
    assert asked == [("qwen3", "qwen3-male-2"), ("cbx", "chatterbox-male-3")]  # each asks only its own engine, for its own voice


def test_a_clone_preview_cannot_be_made_without_an_approved_reference_bound_transcript(tmp_path):
    """The real availability rule the generator relies on: an unapproved or unbound draft is not a transcript."""
    from tts import qwen3_runtime as rt

    voice = rt.get_voice("qwen3-female-1")
    path = tmp_path / "transcripts.json"

    def load(entry):
        path.write_text(json.dumps({voice.reference_name: entry}), encoding="utf-8")
        return rt.load_transcript("qwen3-female-1", paths=[path])

    draft = {"text": "draft words", "approved": False, "wav_sha256": voice.reference_sha256}
    assert not load(draft).ok and "not been approved" in load(draft).reason
    assert not load({**draft, "approved": True, "wav_sha256": "0" * 64}).ok  # approved, but for a different recording
    assert not load({**draft, "approved": "true"}).ok  # only the literal true counts
    assert load({**draft, "approved": True}).ok  # the owner's approval, bound to this exact recording
    assert not rt.load_transcript("qwen3-female-1", paths=[tmp_path / "missing.json"]).ok


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


def manifest_problems_of(mutate):
    """The manifest-only judgement (no files involved) of the committed manifest after one mutation."""
    data = manifest()
    mutate(data)
    return vp.manifest_problems(data)


def test_the_checker_catches_each_kind_of_inconsistency(folder):
    reset_clones_to_pending(folder)
    base = manifest()

    def problems(mutate):
        data = json.loads(json.dumps(base))
        mutate(data)
        return vp.check(data, folder)

    assert any("registry" in p for p in problems(lambda d: d["voices"].pop()))
    assert any("registry" in p for p in problems(lambda d: d["voices"].reverse()))
    assert any("publication is not authorized" in p for p in problems(
        lambda d: (withdraw(d["voices"][0]),
                   d["voices"][0]["preview"].update(status="generated", file="en-US-SteffanNeural.wav", sha256="0" * 64))))
    assert any("unresolved but the preview" in p for p in problems(
        lambda d: (withdraw(d["voices"][0]), d["voices"][0]["preview"].update(status="pending"))))
    assert any("must name its file and SHA-256" in p or "preview file is missing" in p for p in problems(
        lambda d: record_of("qwen3-female-1", d)["preview"].update(status="generated", file="qwen3-female-1.wav")))
    assert any("not named" in p or "does not name this voice" in p for p in problems(
        lambda d: record_of("af_heart", d)["rights"].update(status=vp.RIGHTS_OWNER, authorized_on="2026-10-20",
                                                            authorized_by="owner")))
    assert any("date and who gave it" in p for p in problems(
        lambda d: record_of("en-US-AriaNeural", d)["rights"].update(authorized_on="2020-01-01")))
    assert any("pending voice must have no preview file" in p for p in manifest_problems_of(
        lambda d: record_of("qwen3-male-2", d)["preview"].update(file="qwen3-male-2.wav", sha256="0" * 64)))
    assert any("schema 1" in p for p in problems(lambda d: d.update(schema=1)))
    assert any("owner's publication decision" in p for p in problems(lambda d: d.update(owner_decision={})))
    assert any("no evidence" in p for p in problems(lambda d: d["voices"][5]["rights"].update(evidence=[])))
    assert any("no recorded basis" in p for p in problems(lambda d: d["voices"][5]["rights"].update(basis="")))
    assert any("does not match its recorded SHA-256" in p for p in problems(
        lambda d: d["voices"][5]["preview"].update(sha256="0" * 64)))
    assert any("sample text differs" in p for p in problems(lambda d: d.update(sample_text="another sentence")))
    (folder / "af_heart.wav").write_bytes(b"x")
    assert any("af_heart" in p and ("SHA-256" in p or "unreadable" in p) for p in vp.check(base, folder))


def test_the_checker_flags_stray_audio_a_pending_voices_file_and_a_stale_readme(folder):
    reset_clones_to_pending(folder)
    pending = next(v["voice_id"] for v in manifest()["voices"] if v["preview"]["status"] == vp.PREVIEW_PENDING)
    shutil.copy(folder / "af_heart.wav", folder / "extra-take.wav")
    shutil.copy(folder / "af_heart.wav", folder / f"{pending}.wav")  # a stand-in under a pending voice's name
    (folder / "README.md").write_text("old", encoding="utf-8")
    found = " | ".join(vp.check(None, folder))
    assert "extra-take.wav" in found and f"{pending}: a pending voice must have no preview file" in found
    assert "README.md is out of date" in found


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
    # the owner's decision names the 28 registered voices; a voice added later is blocked until someone decides about it
    assert new["rights"]["status"] == vp.RIGHTS_UNRESOLVED


def old_schema_manifest():
    """The committed manifest as the 2026-10-19 rule left it: 17 voices unresolved and blocked, schema 1."""
    data = manifest()
    data["schema"] = 1
    data.pop("owner_decision")
    for voice_id in EDGE_IDS + CHATTERBOX_IDS + CLONE_IDS:
        record = record_of(voice_id, data)
        record["rights"] = {"status": vp.RIGHTS_UNRESOLVED, "basis": "old blanket block", "evidence": []}
        record["preview"] = {"status": vp.PREVIEW_BLOCKED, "file": None}
    return data


def test_sync_migrates_the_old_blanket_block_once_into_authorized_and_pending():
    old = old_schema_manifest()
    assert vp.counts(old)["blocked"] == 17
    migrated = vp.sync(old)
    assert migrated["schema"] == 2 and migrated["owner_decision"] == vp.OWNER_DECISION
    assert vp.counts(migrated) == {"total": 28, "generated": 11, "pending": 17, "blocked": 0}
    for voice_id in EDGE_IDS + CHATTERBOX_IDS + CLONE_IDS:
        record = record_of(voice_id, migrated)
        assert record["rights"]["status"] == vp.RIGHTS_OWNER and record["preview"]["status"] == vp.PREVIEW_PENDING
        assert record["preview"]["pending_reason"] and record["preview"]["file"] is None
    assert vp.manifest_problems(migrated) == []


def test_after_the_migration_an_unresolved_voice_means_withdrawn_and_a_sync_keeps_it_withdrawn():
    data = manifest()
    withdraw(record_of("en-US-AndrewNeural", data))
    synced = vp.sync(data)  # schema 2 already: this is the owner's withdrawal, not the old block
    assert record_of("en-US-AndrewNeural", synced)["rights"]["status"] == vp.RIGHTS_UNRESOLVED
    assert record_of("en-US-AndrewNeural", synced)["preview"]["status"] == vp.PREVIEW_BLOCKED


def test_status_reports_what_is_missing_and_why_and_exits_nonzero_until_all_28_exist(capsys):
    c = vp.counts(manifest())
    expected = 0 if c["generated"] == 28 else 2
    assert vp.main(["status"]) == expected
    out = capsys.readouterr().out
    assert f"{c['generated']} of 28 previews available; {c['pending']} pending generation, 0 withdrawn." in out
    if c["pending"]:
        assert "transcript" in out and "qwen3-female-1" in out


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


# --------------------------------------------------------------------------- #
# Edge and Chatterbox previews go through the production routes, with no substitution
# --------------------------------------------------------------------------- #
class FakeCommunicate:
    """Replaces ``edge_tts.Communicate`` (the one network boundary). Arguments are bound against the real signature."""

    outcome = None  # an exception to raise from save(), or None to write a valid mono 24 kHz clip
    calls: list = []

    def __init__(self, *args, **kwargs):
        import inspect

        import edge_tts

        inspect.signature(edge_tts.Communicate.__init__).bind(None, *args, **kwargs)  # a call the real class would reject fails
        type(self).calls.append((args, kwargs))

    async def save(self, path, *_):
        if type(self).outcome is not None:
            raise type(self).outcome
        write_content_as(path, seconds=10.5, amplitude=0.1)


def write_content_as(path, **kwargs):
    """Audio content under the ".mp3" name the service's file would have; libsndfile reads by content, not by name."""
    wav = write_wav(Path(path).with_suffix(".tmp.wav"), **kwargs)
    Path(path).unlink(missing_ok=True)
    wav.rename(path)


@pytest.fixture()
def fake_edge(monkeypatch):
    import tts.batch_convert as bc

    FakeCommunicate.outcome, FakeCommunicate.calls = None, []
    monkeypatch.setattr(bc.edge_tts, "Communicate", FakeCommunicate)
    return FakeCommunicate


def handshake_error(status):
    import aiohttp
    from multidict import CIMultiDict, CIMultiDictProxy
    from yarl import URL

    url = URL("wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=SECRET")
    info = aiohttp.RequestInfo(url=url, method="GET", headers=CIMultiDictProxy(CIMultiDict()), real_url=url)
    return aiohttp.WSServerHandshakeError(info, (), status=status, message="Invalid response status")


@pytest.mark.parametrize("voice_id", EDGE_IDS)
def test_an_edge_preview_is_the_folder_routes_own_request_for_exactly_that_voice(fake_edge, tmp_path, voice_id):
    from tts import voice_registry

    entry = next(e for e in voice_registry.VOICES if e.voice_id == voice_id)
    text_path = tmp_path / "sample.txt"
    text_path.write_text(vp.SAMPLE_TEXT, encoding="utf-8")
    vp.synthesize(entry, text_path, tmp_path / "out.wav")
    assert fake_edge.calls == [((), {"text": vp.SAMPLE_TEXT, "voice": voice_id, "rate": entry.timing_preset["rate"]})]
    assert vp.audio_problems(tmp_path / "out.wav") == []
    assert sf.info(str(tmp_path / "out.wav")).subtype == "PCM_16"


def test_an_edge_refusal_leaves_the_voice_pending_with_advice_and_substitutes_nothing(folder, fake_edge, monkeypatch):
    from tts import chatterbox_synth, kokoro_synth, qwen3_synth

    for module, name in ((kokoro_synth, "kokoro_file_to_mp3"), (chatterbox_synth, "chatterbox_file_to_mp3"),
                         (qwen3_synth, "qwen3_file_to_mp3")):
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail("another engine was used in place of Edge"))
    data = manifest()
    record = record_of("en-US-AriaNeural", data)
    (folder / "en-US-AriaNeural.wav").unlink()
    record["preview"] = {"status": vp.PREVIEW_PENDING, "file": None, "pending_reason": vp.GENERIC_PENDING}
    vp.MANIFEST.write_text(json.dumps(data), encoding="utf-8")
    fake_edge.outcome = handshake_error(403)
    logs = []
    result = vp.generate(["en-US-AriaNeural"], log=logs.append)
    assert len(fake_edge.calls) == 1  # a refusal is final: one request, no retry storm, no second voice
    assert any(l.startswith("FAILED   en-US-AriaNeural") and "refused the connection" in l for l in logs)
    assert not any("SECRET" in l for l in logs)  # the handshake token never reaches the log
    assert not (folder / "en-US-AriaNeural.wav").exists()
    assert record_of("en-US-AriaNeural", result)["preview"]["status"] == vp.PREVIEW_PENDING and result["_failures"]


def test_an_edge_clip_that_comes_back_stereo_or_wrong_is_rejected_not_published(folder, fake_edge, monkeypatch):
    monkeypatch.setattr(FakeCommunicate, "save", lambda self, path, *_: _write_stereo(path))
    before = folder_state(folder)
    result = vp.generate(["en-US-SteffanNeural"], log=lambda m: None)
    assert result["_failures"] and folder_state(folder) == before  # the previous good preview is untouched


async def _write_stereo(path):
    write_content_as(path, seconds=10.5, channels=2)


def test_a_chatterbox_preview_runs_the_production_entry_with_zero_pauses_and_writes_a_pcm16_wav(tmp_path, monkeypatch):
    from tts import chatterbox_synth, voice_registry

    entry = next(e for e in voice_registry.VOICES if e.voice_id == "chatterbox-male-3")
    original = chatterbox_synth._export_mp3
    seen = {}

    def fake_entry(source, output, voice_id, **kwargs):
        seen.update(source=Path(source).read_text("utf-8"), voice_id=voice_id, kwargs=kwargs)
        chatterbox_synth._export_mp3(np.full(24000 * 10, 0.1, dtype="float32"), 24000, output)

    monkeypatch.setattr(chatterbox_synth, "chatterbox_file_to_mp3", fake_entry)
    text_path = tmp_path / "sample.txt"
    text_path.write_text(vp.SAMPLE_TEXT, encoding="utf-8")
    vp.synthesize(entry, text_path, tmp_path / "out.wav")
    assert seen == {"source": vp.SAMPLE_TEXT, "voice_id": "chatterbox-male-3",
                    "kwargs": {"end_silence_ms": 0, "chunk_pause_ms": 0}}  # the registered voice, the shared text, no pauses
    assert sf.info(str(tmp_path / "out.wav")).subtype == "PCM_16" and sf.info(str(tmp_path / "out.wav")).samplerate == 24000
    assert chatterbox_synth._export_mp3 is original  # the production encoder is put back


def test_the_chatterbox_encoder_swap_is_undone_even_when_the_engine_fails(tmp_path, monkeypatch):
    from tts import chatterbox_synth, voice_registry

    entry = next(e for e in voice_registry.VOICES if e.voice_id == "chatterbox-female-1")
    original = chatterbox_synth._export_mp3

    def explode(*args, **kwargs):
        raise RuntimeError("the model fell over")

    monkeypatch.setattr(chatterbox_synth, "chatterbox_file_to_mp3", explode)
    text_path = tmp_path / "sample.txt"
    text_path.write_text(vp.SAMPLE_TEXT, encoding="utf-8")
    with pytest.raises(RuntimeError, match="fell over"):
        vp.synthesize(entry, text_path, tmp_path / "out.wav")
    assert chatterbox_synth._export_mp3 is original  # a failed take must not leave the app's encoder replaced


def test_a_backend_with_no_preview_path_is_refused_not_guessed(tmp_path):
    entry = type("Entry", (), {"backend": "mystery", "voice_id": "x"})()
    with pytest.raises(vp.PreviewError, match="no preview path"):
        vp.synthesize(entry, tmp_path / "s.txt", tmp_path / "o.wav")


# --------------------------------------------------------------------------- #
# Direct raw links, and the clone previews reflect the application's own clone profile
# --------------------------------------------------------------------------- #
def test_every_available_preview_has_a_direct_raw_wav_link_to_a_file_that_exists():
    text = vp.README.read_text("utf-8")
    links = re.findall(r"\[([^\]]+\.wav)\]\((https://[^)]+)\)", text)
    available = [v["preview"]["file"] for v in manifest()["voices"] if v["preview"]["status"] == vp.PREVIEW_GENERATED]
    assert [name for name, _ in links] == available  # one link per available preview, in registry order
    for name, url in links:
        assert url == vp.RAW_BASE + name and (vp.PREVIEW_DIR / name).is_file()
    assert vp.RAW_BASE.startswith("https://github.com/elmatthe/audiobook-creation-tool/raw/") and vp.RAW_BASE.endswith("/files/voice-previews/")
    assert "not an approval of its audio quality" in text and "saves the file" in text  # honest about downloads and about quality


def test_the_clone_profile_is_recorded_for_every_clone_preview_and_only_for_those():
    profile = vp.current_clone_profile()
    assert profile == {"revision": 1, "temperature": 0.7, "subtalker_temperature": 0.8, "reference_tail_silence_s": 0.6}
    for record in manifest()["voices"]:
        if record["preview"]["status"] != vp.PREVIEW_GENERATED:
            continue
        if vp.is_clone(record):
            assert record["preview"]["generation_profile"] == profile, record["voice_id"]
        else:
            assert "generation_profile" not in record["preview"], record["voice_id"]


def test_a_clone_preview_made_under_another_profile_or_none_is_a_problem_and_blocks_the_readme():
    data = complete_set(manifest())
    assert vp.manifest_problems(data) == [] and "## The Qwen3 clone narration profile" in vp.render_readme(data)
    clone = record_of("qwen3-male-2", data)
    for bad in (None, {**vp.current_clone_profile(), "temperature": 0.9}, {**vp.current_clone_profile(), "revision": 0}):
        if bad is None:
            clone["preview"].pop("generation_profile")
        else:
            clone["preview"]["generation_profile"] = bad
        assert any("not made under the application's current clone generation profile" in p for p in vp.manifest_problems(data))
        with pytest.raises(vp.PreviewError):
            vp.render_readme(data)
    clone["preview"]["generation_profile"] = vp.current_clone_profile()
    record_of("af_heart", data)["preview"]["generation_profile"] = vp.current_clone_profile()
    assert any("only a Qwen3 clone preview records" in p for p in vp.manifest_problems(data))


def test_generating_a_clone_records_the_profile_and_the_approved_transcript_hash_and_other_voices_do_not(folder, monkeypatch):
    from tts import qwen3_runtime as rt

    monkeypatch.setattr(vp, "synthesize", succeed)
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    data = vp.generate(["qwen3-female-1", "af_heart"], log=lambda m: None)
    assert not data["_failures"]
    clone = record_of("qwen3-female-1", data)["preview"]
    assert clone["generation_profile"] == vp.current_clone_profile()
    assert clone["transcript"] == {"status": "owner-approved", "text_sha256": rt.transcript_sha256("approved words")}
    assert clone["seed_take"] == 0 and clone["leading_fragment_trimmed_ms"] == 0 and "read_back_checked" not in clone  # no recognizer was supplied, and the record says so
    assert "approved words" not in json.dumps(data)  # a hash is recorded, never the text
    other = record_of("af_heart", data)["preview"]
    assert not {"generation_profile", "transcript", "seed_take", "leading_fragment_trimmed_ms"} & set(other)
    assert vp.check({k: v for k, v in data.items() if k != "_failures"}, folder) == []


# --------------------------------------------------------------------------- #
# Provisional transcripts (owner authorization: listening samples only; production approval untouched)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def drafts_file(tmp_path):
    from tts import qwen3_runtime as rt

    data = {v.reference_name: {"text": f"Provisional words for {v.reference_name}.", "approved": False,
                               "wav_sha256": v.reference_sha256} for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE}
    path = tmp_path / "verified.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_provisional_drafts_must_be_bound_to_the_registered_recordings(drafts_file):
    texts = vp.provisional_transcripts(drafts_file)
    assert sorted(texts) == sorted(CLONE_IDS) and texts["qwen3-male-2"] == "Provisional words for Male-2."
    data = json.loads(drafts_file.read_text("utf-8"))
    for mutate, message in ((lambda d: d["Male-1"].update(wav_sha256="0" * 64), "different recording"),
                            (lambda d: d["Male-1"].update(text="  "), "no usable draft"),
                            (lambda d: d["Male-1"].update(text="x" * 2001), "no usable draft"),
                            (lambda d: d.pop("Female-2"), "no usable draft")):
        bad = json.loads(json.dumps(data))
        mutate(bad)
        drafts_file.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(vp.PreviewError, match=message):
            vp.provisional_transcripts(drafts_file)
    with pytest.raises(vp.PreviewError, match="could not be read"):
        vp.provisional_transcripts(drafts_file.with_name("missing.json"))


def test_the_provisional_loader_answers_only_for_its_voices_and_only_inside_the_with(tmp_path):
    from tts import qwen3_runtime as rt

    original = rt.load_transcript
    none = tmp_path / "none.json"  # no approved transcripts anywhere
    with vp.provisional_loader({"qwen3-male-1": "draft words"}):
        got = rt.load_transcript("qwen3-male-1")
        assert got.ok and got.text == "draft words" and "NOT owner-approved" in got.reason
        assert not rt.load_transcript("qwen3-male-2", paths=[none]).ok  # every other clone still needs a real approval
        assert rt.load_transcript("qwen3-aiden").ok  # presets need none, as always
    assert rt.load_transcript is original  # restored
    assert not rt.load_transcript("qwen3-male-1", paths=[none]).ok  # and production approval is exactly as strict as before
    with pytest.raises(RuntimeError):
        with vp.provisional_loader({"qwen3-male-1": "x"}):
            raise RuntimeError("synthesis failed")
    assert rt.load_transcript is original  # restored even when the synthesis fails


def test_a_provisional_run_makes_clones_labels_them_and_never_writes_an_approval(folder, monkeypatch, drafts_file, tmp_path):
    from tts import qwen3_runtime as rt

    seen = []

    def synth(entry, text_path, out_wav):
        seen.append(rt.load_transcript(entry.voice_id).text)  # what the production path would read at this moment
        write_wav(out_wav, seconds=10.0, amplitude=0.1)

    approved_file = tmp_path / "approved" / "transcripts.json"
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(approved_file))
    monkeypatch.setattr(vp, "PROVISIONAL_DRAFTS", drafts_file)
    monkeypatch.setattr(vp, "synthesize", synth)
    monkeypatch.setattr(vp, "provisional_reason", lambda entry: None)
    logs = []
    data = vp.generate(["qwen3-female-1", "qwen3-male-4"], log=logs.append, provisional=True)
    assert not data["_failures"] and seen == ["Provisional words for Female-1.", "Provisional words for Male-4."]
    for voice_id in ("qwen3-female-1", "qwen3-male-4"):
        preview = record_of(voice_id, data)["preview"]
        assert preview["transcript"]["status"] == "provisional" and "not owner-approved" in preview["transcript"]["source"]
        assert preview["transcript"]["text_sha256"] == rt.transcript_sha256(seen[0 if voice_id.endswith("1") else 1])
        assert preview["generation_profile"] == vp.current_clone_profile()
    assert not approved_file.exists() and not approved_file.parent.exists()  # nothing was ever written as an approval
    assert "Provisional words" not in json.dumps(data) and "Provisional words" not in vp.README.read_text("utf-8")
    readme = vp.README.read_text("utf-8")
    assert "(provisional transcript)" in readme and "use a provisional reference transcript" in readme
    assert "still refuses to make a clone without an approved" in readme
    assert vp.check({k: v for k, v in data.items() if k != "_failures"}, folder) == []


def test_without_the_flag_a_clone_still_needs_a_real_approval_and_stays_pending(folder, monkeypatch, drafts_file, tmp_path):
    reset_clones_to_pending(folder)
    from tts import qwen3_runtime as rt

    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(tmp_path / "none.json"))
    monkeypatch.setattr(vp, "PROVISIONAL_DRAFTS", drafts_file)
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("a clone was made without an approved transcript"))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: "no approved reference transcript is available")
    logs = []
    data = vp.generate(["qwen3-female-2"], log=logs.append)
    assert logs == ["PENDING  qwen3-female-2: no approved reference transcript is available"]
    assert record_of("qwen3-female-2", data)["preview"]["status"] == vp.PREVIEW_PENDING


def test_a_provisional_run_still_refuses_what_the_machine_cannot_make(folder, monkeypatch, drafts_file):
    reset_clones_to_pending(folder)
    monkeypatch.setattr(vp, "PROVISIONAL_DRAFTS", drafts_file)
    monkeypatch.setattr(vp, "synthesize", lambda *a: pytest.fail("an engine ran"))
    monkeypatch.setattr(vp, "provisional_reason", lambda entry: "the Base model is not installed")
    logs = []
    data = vp.generate(["qwen3-male-3"], log=logs.append, provisional=True)
    assert logs == ["PENDING  qwen3-male-3: the Base model is not installed"]  # model, environment and reference are still required
    assert record_of("qwen3-male-3", data)["preview"]["status"] == vp.PREVIEW_PENDING


def test_a_clone_preview_must_say_whose_transcript_it_used():
    data = complete_set(manifest())
    clone = record_of("qwen3-male-2", data)["preview"]
    assert vp.manifest_problems(data) == []
    for bad in ({"status": "approved"}, {"status": "provisional", "text_sha256": "1" * 64}, {"status": "owner-approved", "text_sha256": "zz"}):
        clone["transcript"] = bad
        assert any("transcript" in p for p in vp.manifest_problems(data)), bad
    clone.pop("transcript")
    assert any("whether its transcript is owner-approved or provisional" in p for p in vp.manifest_problems(data))
    record_of("af_heart", data)["preview"]["transcript"] = {"status": "owner-approved", "text_sha256": "1" * 64}
    assert any("only a Qwen3 clone preview" in p for p in vp.manifest_problems(data))


def test_the_command_line_flag_reaches_generate(monkeypatch):
    seen = {}
    monkeypatch.setattr(vp, "generate", lambda ids, provisional=False, **k: seen.update(ids=ids, provisional=provisional) or {"voices": [], "_failures": []})
    monkeypatch.setattr(vp, "counts", lambda d: {})
    assert vp.main(["generate", "--provisional-transcripts", "qwen3-male-1", "qwen3-male-2"]) == 0
    assert seen == {"ids": ["qwen3-male-1", "qwen3-male-2"], "provisional": True}
    vp.main(["generate", "qwen3-male-1"])
    assert seen == {"ids": ["qwen3-male-1"], "provisional": False}


# --------------------------------------------------------------------------- #
# A clone must open from silence and say the whole sentence; a failed take is re-rendered with the next seed take
# --------------------------------------------------------------------------- #
def test_a_clip_that_begins_mid_sound_is_rejected_and_one_that_begins_from_silence_is_not(tmp_path):
    assert vp.audio_problems(write_wav(tmp_path / "ok.wav")) == []
    problems = vp.audio_problems(write_wav(tmp_path / "abrupt.wav", lead=0))
    assert any("begins mid-sound" in p for p in problems), problems
    # a quiet fragment is tolerated only below the threshold: -50 dBFS in the first 10 ms
    faint = write_wav(tmp_path / "faint.wav", amplitude=0.2, lead=0.15)
    data, rate = sf.read(str(faint), dtype="float32")
    data[:240] = 10 ** (-60 / 20)
    sf.write(str(faint), data, rate, subtype="PCM_16")
    assert vp.audio_problems(faint) == []


def test_the_published_previews_all_begin_from_silence():
    for record in manifest()["voices"]:
        if record["preview"]["status"] == vp.PREVIEW_GENERATED:
            assert not any("begins mid-sound" in p for p in vp.audio_problems(vp.PREVIEW_DIR / record["preview"]["file"])), record["voice_id"]


def test_a_seed_take_shifts_the_seed_base_for_one_render_only_and_always_restores_it():
    from tts import qwen3_synth

    base = qwen3_synth.SEED_BASE
    with vp.seed_take(0):
        assert qwen3_synth.SEED_BASE == base  # take 0 is the application's own seeds
    with vp.seed_take(2):
        assert qwen3_synth.SEED_BASE == base + 2 * vp.TAKE_SEED_STEP
    assert qwen3_synth.SEED_BASE == base
    with pytest.raises(RuntimeError):
        with vp.seed_take(1):
            raise RuntimeError("synthesis failed")
    assert qwen3_synth.SEED_BASE == base


def clone_synth(good_from_take, seen):
    """A fake engine whose output is unusable (starts mid-sound) until the given seed take."""
    from tts import qwen3_synth

    def synth(entry, text_path, out_wav):
        take = (qwen3_synth.SEED_BASE - 20261019) // vp.TAKE_SEED_STEP
        seen.append(take)
        write_wav(out_wav, seconds=10.0, amplitude=0.1, lead=0.15 if take >= good_from_take else 0)

    return synth


def test_a_clone_whose_first_take_fails_is_re_rendered_with_the_next_seed_take_and_the_take_is_recorded(folder, monkeypatch):
    from tts import qwen3_runtime as rt

    seen, logs = [], []
    monkeypatch.setattr(vp, "synthesize", clone_synth(2, seen))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    data = vp.generate(["qwen3-male-4"], log=logs.append, takes=6)
    assert seen == [0, 1, 2] and not data["_failures"]  # stops at the first take that validates
    assert record_of("qwen3-male-4", data)["preview"]["seed_take"] == 2
    assert [l for l in logs if l.startswith("REJECTED")][0].startswith("REJECTED qwen3-male-4: take 0: begins mid-sound")
    assert "1 of the clone previews were therefore re-rendered with the next seed take" in vp.README.read_text("utf-8")
    from tts import qwen3_synth

    assert qwen3_synth.SEED_BASE == 20261019  # the application's seed base is untouched afterwards
    assert vp.check({k: v for k, v in data.items() if k != "_failures"}, folder) == []


def test_when_every_take_fails_nothing_is_published_and_the_previous_state_is_kept(folder, monkeypatch):
    reset_clones_to_pending(folder)
    from tts import qwen3_runtime as rt

    seen = []
    monkeypatch.setattr(vp, "synthesize", clone_synth(99, seen))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    before = folder_state(folder)
    data = vp.generate(["qwen3-male-4"], log=lambda m: None, takes=3)
    assert seen == [0, 1, 2] and "take 0" in data["_failures"][0] and "take 2" in data["_failures"][0]
    assert folder_state(folder) == before and record_of("qwen3-male-4", data)["preview"]["status"] == vp.PREVIEW_PENDING


def test_only_clones_get_more_than_one_take_and_the_read_back_gates_clones_only(folder, monkeypatch):
    from tts import qwen3_runtime as rt

    seen, heard = [], []
    monkeypatch.setattr(vp, "synthesize", clone_synth(99, seen))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    vp.generate(["af_heart"], log=lambda m: None, takes=6, readback=lambda path: heard.append(path) or [])
    assert seen == [0] and heard == []  # a Kokoro voice is rendered once, and no recognizer is run for it


def test_a_clone_take_that_reads_back_wrongly_is_rejected_then_the_next_take_is_used(folder, monkeypatch):
    from tts import qwen3_runtime as rt

    outcomes = iter([["the first word is not spoken (heard 'this is', expected 'welcome')"], []])
    monkeypatch.setattr(vp, "synthesize", lambda entry, text_path, out_wav: write_wav(out_wav, seconds=10.0, amplitude=0.1))
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    data = vp.generate(["qwen3-male-4"], log=lambda m: None, takes=4, readback=lambda path: next(outcomes))
    preview = record_of("qwen3-male-4", data)["preview"]
    assert preview["seed_take"] == 1 and preview["read_back_checked"] is True


class FakeRecognizer:
    """Stands in for the .venv-qwen3 whisper call: writes the JSON the real tool writes."""

    def __init__(self, monkeypatch, text, tmp_path):
        self.text = text
        venv = tmp_path / "python.exe"
        venv.write_text("", encoding="utf-8")
        from tts import qwen3_runtime as rt
        import qwen3_calm_experiment as exp

        whisper = tmp_path / "whisper"
        whisper.mkdir()
        monkeypatch.setattr(rt, "venv_python", lambda: venv)
        monkeypatch.setattr(exp, "WHISPER_DIR", whisper)
        monkeypatch.setattr(vp.subprocess, "run", self.run)

    def run(self, command, **kwargs):
        out, wav = Path(command[-2]), command[-1]
        out.write_text(json.dumps({wav: self.text}), encoding="utf-8")
        return type("R", (), {"returncode": 0, "stderr": ""})()


@pytest.mark.parametrize("heard, expected_fragment", [
    (None, None),
    ("This is a short sample of my voice, reading a calm passage at an even pace, so that you can decide whether it suits the story "
     "you want to hear, today or tomorrow.", "the first word is not spoken"),
    ("Welcome. This is a short sample of my voice, reading a calm passage at an even pace, so that you can decide whether it suits "
     "the story you want to hear, today or", "the last word is not spoken"),
    ("Welcome. Something else entirely was said here by a different speaker, nothing alike, tomorrow", "word error rate")])
def test_the_read_back_check_names_what_is_wrong_with_the_speech(monkeypatch, tmp_path, heard, expected_fragment):
    FakeRecognizer(monkeypatch, heard or vp.SAMPLE_TEXT, tmp_path)
    wav = write_wav(tmp_path / "clip.wav")
    problems = vp.read_back_problems(wav)
    if expected_fragment is None:
        assert problems == []
    else:
        assert any(expected_fragment in p for p in problems), problems
    assert not list(tmp_path.glob("*.readback.json"))  # nothing is left behind


def test_the_read_back_check_cannot_pass_silently_when_the_recognizer_is_missing(monkeypatch, tmp_path):
    import qwen3_calm_experiment as exp

    monkeypatch.setattr(exp, "WHISPER_DIR", tmp_path / "nowhere")
    problems = vp.read_back_problems(write_wav(tmp_path / "clip.wav"))
    assert problems and "cannot run here" in problems[0]


def test_a_clone_preview_must_record_its_seed_take_and_only_a_clone_does():
    data = complete_set(manifest())
    clone = record_of("qwen3-male-2", data)["preview"]
    for bad in (None, -1, "0", 1.5):
        if bad is None:
            clone.pop("seed_take")
        else:
            clone["seed_take"] = bad
        assert any("which seed take" in p for p in vp.manifest_problems(data)), bad
    clone["seed_take"] = 3
    assert vp.manifest_problems(data) == [] and "re-rendered with the next seed take" in vp.render_readme(data)
    record_of("af_heart", data)["preview"]["seed_take"] = 0
    assert any("only a Qwen3 clone preview" in p for p in vp.manifest_problems(data))


def test_the_command_line_takes_option_reaches_generate(monkeypatch):
    seen = {}
    monkeypatch.setattr(vp, "generate", lambda ids, provisional=False, takes=None, readback=None, **k: seen.update(
        ids=ids, takes=takes, readback=readback) or {"voices": [], "_failures": []})
    monkeypatch.setattr(vp, "counts", lambda d: {})
    vp.main(["generate", "--provisional-transcripts", "--takes", "3", "qwen3-male-1"])
    assert seen == {"ids": ["qwen3-male-1"], "takes": 3, "readback": vp.read_back_problems}
    vp.main(["generate", "qwen3-male-1"])
    assert seen["takes"] == vp.MAX_TAKES


# --------------------------------------------------------------------------- #
# A clone's opening leftover from its reference recording
# --------------------------------------------------------------------------- #
RATE = 24000


def burst(seconds, hz=200, amplitude=0.2):
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype("float32")


def silence(seconds):
    return np.zeros(int(RATE * seconds), dtype="float32")


def test_a_short_leftover_followed_by_a_clear_pause_is_removed_and_the_clip_then_opens_from_silence():
    audio = np.concatenate([burst(0.24), silence(0.45), burst(3.0)])
    out, removed = vp.strip_leading_fragment(audio, RATE)
    assert 240 <= removed <= 700 and out.size == audio.size - int(RATE * removed / 1000)
    assert out.size / RATE >= 3.1  # all of the real speech is kept, with its pause in front
    assert np.array_equal(out[-int(RATE * 3.0):], audio[-int(RATE * 3.0):])  # the speech itself is untouched
    trimmed = vp.trim_edges(out, RATE)
    head = trimmed[:int(RATE * 0.01)]
    assert 20 * np.log10(max(float(np.sqrt(np.mean(head ** 2))), 1e-9)) < vp.ONSET_DB


def test_nothing_is_removed_when_the_clip_already_opens_from_silence_or_has_no_safe_boundary():
    clean = np.concatenate([silence(0.2), burst(3.0)])
    out, removed = vp.strip_leading_fragment(clean, RATE)
    assert removed == 0 and np.array_equal(out, clean)
    for audio in (np.concatenate([burst(0.9), silence(0.45), burst(3.0)]),          # opening too long to be a leftover: it is speech
                  np.concatenate([burst(0.2), silence(0.06), burst(3.0)]),          # no clear pause after it: cannot be separated
                  burst(3.0)):                                                      # no pause at all
        out, removed = vp.strip_leading_fragment(audio, RATE)
        assert removed == 0 and np.array_equal(out, audio)  # left for validation to reject, never silently cut into the speech


def test_the_strip_cannot_hide_a_swallowed_word_because_the_read_back_still_decides(folder, monkeypatch):
    reset_clones_to_pending(folder)
    from tts import qwen3_runtime as rt

    def synth(entry, text_path, out_wav):
        sf.write(str(out_wav), np.concatenate([burst(0.24), silence(0.45), burst(10.0, amplitude=0.1)]), RATE, subtype="PCM_16")

    monkeypatch.setattr(vp, "synthesize", synth)
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    heard = ["the first word is not spoken (heard 'this is', expected 'welcome')"]
    data = vp.generate(["qwen3-male-4"], log=lambda m: None, takes=2, readback=lambda path: heard)
    assert data["_failures"] and "first word is not spoken" in data["_failures"][0]  # the leftover was removed, the missing word still fails
    assert record_of("qwen3-male-4", data)["preview"]["status"] == vp.PREVIEW_PENDING


def test_a_clone_with_a_removed_leftover_is_published_and_the_amount_is_recorded_and_explained(folder, monkeypatch):
    from tts import qwen3_runtime as rt

    def synth(entry, text_path, out_wav):
        sf.write(str(out_wav), np.concatenate([burst(0.24), silence(0.45), burst(10.0, amplitude=0.1)]), RATE, subtype="PCM_16")

    monkeypatch.setattr(vp, "synthesize", synth)
    monkeypatch.setattr(vp, "unavailable_reason", lambda entry: None)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id, **k: rt.Transcript(True, "approved words", "ok"))
    data = vp.generate(["qwen3-female-1"], log=lambda m: None, takes=1, readback=lambda path: [])
    preview = record_of("qwen3-female-1", data)["preview"]
    assert not data["_failures"] and preview["leading_fragment_trimmed_ms"] >= 240 and preview["seed_take"] == 0
    assert vp.audio_problems(vp.PREVIEW_DIR / "qwen3-female-1.wav") == []
    complete = complete_set(vp.sync(json.loads(vp.MANIFEST.read_text("utf-8"))))
    record_of("qwen3-female-1", complete)["preview"]["leading_fragment_trimmed_ms"] = 300
    assert "opened with a short leftover of the end of their reference recording" in vp.render_readme(complete)


def test_a_non_clone_is_never_trimmed_and_an_abrupt_start_still_fails_for_it(folder, monkeypatch):
    monkeypatch.setattr(vp, "synthesize", lambda entry, text_path, out_wav: sf.write(
        str(out_wav), np.concatenate([burst(0.24), silence(0.45), burst(10.0, amplitude=0.1)]), RATE, subtype="PCM_16"))
    data = vp.generate(["af_heart"], log=lambda m: None)
    assert data["_failures"] and "begins mid-sound" in data["_failures"][0]


def test_a_clone_preview_must_record_the_removed_leftover_and_only_a_clone_does():
    data = complete_set(manifest())
    clone = record_of("qwen3-male-2", data)["preview"]
    for bad in (None, -5, "0", 2.5):
        if bad is None:
            clone.pop("leading_fragment_trimmed_ms")
        else:
            clone["leading_fragment_trimmed_ms"] = bad
        assert any("how much leading leftover was removed" in p for p in vp.manifest_problems(data)), bad
    clone["leading_fragment_trimmed_ms"] = 0
    record_of("af_heart", data)["preview"]["leading_fragment_trimmed_ms"] = 0
    assert any("only a Qwen3 clone preview" in p for p in vp.manifest_problems(data))
