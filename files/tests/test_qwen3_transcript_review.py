"""v0.6.7 — the owner's Qwen3 clone transcript review package (``files/dev-tools/qwen3_transcript_review.py``).

Offline: synthetic draft text, a scratch target file. What is pinned:

* the page embeds the six ORIGINAL recordings byte for byte (and refuses to be built if any is not the registered one);
* nothing is approved by building the page, by a dry run, by NEEDS CORRECTION, by an undecided voice or by a stale/foreign file;
* only an explicit ``--write`` of an owner PASS (with "I listened") produces ``approved: true``, bound to the recording's SHA-256,
  in the local untracked transcripts file that the app's own loader then accepts;
* the Whisper drafts, the recordings and every tracked file are never modified, and no transcript text is echoed in a report.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "files" / "dev-tools"))

import qwen3_transcript_review as review  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402

SECRET = "zanzibar marmalade quokka"  # synthetic draft words: must never appear in a report


@pytest.fixture()
def drafts(tmp_path):
    path = tmp_path / "verified.json"
    data = {v.reference_name: {"text": f"{SECRET} for {v.reference_name}.", "approved": False, "wav_sha256": v.reference_sha256}
            for v in review.clone_voices()}
    data["_instructions"] = "synthetic"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def decisions_file(tmp_path, drafts, *, decisions=None, name="decisions.json", **overrides):
    """What the page would download, built from the same package so it is not stale."""
    items = []
    for voice in review.clone_voices():
        items.append({"voice_id": voice.voice_id, "reference_name": voice.reference_name, "wav_sha256": voice.reference_sha256,
                      "decision": review.PASS, "listened": True, "text": f"Corrected words for {voice.reference_name}."})
    for voice_id, change in (decisions or {}).items():
        next(i for i in items if i["voice_id"] == voice_id).update(change)
    data = {"schema": review.SCHEMA, "kind": "qwen3-transcript-review", "review_id": review.review_id(review.load_drafts(drafts)),
            "decided_at": "2026-10-21T10:00:00Z", "decisions": items, **overrides}
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #
@pytest.fixture()
def page(tmp_path, drafts):
    out = review.build(drafts, tmp_path / "out" / "review.html")
    return out.read_text(encoding="utf-8")


def test_the_page_embeds_the_six_original_recordings_byte_for_byte(page):
    embedded = re.findall(r'src="data:audio/wav;base64,([A-Za-z0-9+/=]+)"', page)
    assert len(embedded) == 6
    hashes = sorted(hashlib.sha256(base64.b64decode(b)).hexdigest() for b in embedded)
    assert hashes == sorted(v.reference_sha256 for v in review.clone_voices())  # the registered originals, nothing re-encoded


def test_the_page_offers_exactly_what_the_owner_needs(page):
    assert page.count('class="card"') == 6 and page.count("<audio") == 6
    assert page.count("<textarea id=\"t-") == 6 and page.count('value="PASS"') == 6 and page.count('value="NEEDS_CORRECTION"') == 6
    assert page.count('class="listened"') == 6 and "Download decisions file" in page and "Copy decisions" in page
    for label in ("Qwen3 - Female 1", "Qwen3 - Male 4"):
        assert label in page
    assert SECRET in page  # the Whisper draft is shown beside each recording
    # a decision is never pre-selected: nothing is approved just by opening the page
    assert not re.search(r"<input[^>]*checked", page.split("<script")[0])


def test_the_pages_download_has_the_shape_apply_accepts(page):
    for key in ("kind: 'qwen3-transcript-review'", "schema: DATA.schema", "review_id: DATA.review_id", "voice_id:", "reference_name:",
                "wav_sha256:", "decision:", "listened:", "text:"):
        assert key in page
    assert review.DECISIONS_NAME in page and "approved" not in page.split("<script")[0].lower().replace("approved until", "")


def test_the_page_is_private_and_self_contained(page):
    assert "http://" not in page and "https://" not in page.replace("https://keepachangelog", "")  # no network, no CDN
    assert "<script src" not in page and "<link " not in page


def test_building_refuses_a_draft_made_for_another_recording(tmp_path, drafts):
    data = json.loads(drafts.read_text("utf-8"))
    data["Female-1"]["wav_sha256"] = "0" * 64
    drafts.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(review.ReviewError, match="different recording"):
        review.build(drafts, tmp_path / "x.html")
    assert not (tmp_path / "x.html").exists()


def test_building_refuses_a_recording_that_is_not_the_registered_one(tmp_path, drafts, monkeypatch):
    fake = tmp_path / "Chatterbox - Female 1.wav"
    fake.write_bytes(b"RIFF....not the approved recording")
    real = rt.reference_path
    monkeypatch.setattr(rt, "reference_path", lambda voice: fake if voice.reference_name == "Female-1" else real(voice))
    with pytest.raises(review.ReviewError, match="not the recording the app registered"):
        review.build(drafts, tmp_path / "x.html")


def test_building_never_modifies_the_recordings_or_the_drafts(tmp_path, drafts):
    watched = [rt.reference_path(v) for v in review.clone_voices()] + [drafts]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
    review.build(drafts, tmp_path / "r.html")
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched} == before


def test_the_package_id_changes_when_a_draft_changes(drafts):
    first = review.review_id(review.load_drafts(drafts))
    data = json.loads(drafts.read_text("utf-8"))
    data["Male-2"]["text"] += " changed"
    drafts.write_text(json.dumps(data), encoding="utf-8")
    assert review.review_id(review.load_drafts(drafts)) != first


# --------------------------------------------------------------------------- #
# Turning decisions into approvals
# --------------------------------------------------------------------------- #
def test_a_dry_run_changes_nothing_and_does_not_sound_like_an_approval(tmp_path, drafts):
    target = tmp_path / "transcripts.json"
    report = review.apply(decisions_file(tmp_path, drafts), drafts_path=drafts, target=target)
    assert not target.exists()
    assert report[0].startswith("DRY RUN") and all("would be" in line for line in report[1:])


def test_write_records_only_owner_passes_bound_to_the_recording_and_the_app_then_accepts_them(tmp_path, drafts):
    target = tmp_path / "transcripts.json"
    path = decisions_file(tmp_path, drafts, decisions={
        "qwen3-male-4": {"decision": review.NEEDS_CORRECTION, "text": "still unsure"},
        "qwen3-male-3": {"decision": None}})
    report = review.apply(path, write=True, drafts_path=drafts, target=target, today="2026-10-21")
    saved = json.loads(target.read_text("utf-8"))
    for voice in review.clone_voices():
        loaded = rt.load_transcript(voice.voice_id, paths=[target])
        if voice.voice_id == "qwen3-male-4":
            assert saved[voice.reference_name]["approved"] is False and not loaded.ok  # a correction request is not an approval
        elif voice.voice_id == "qwen3-male-3":
            assert voice.reference_name not in saved and not loaded.ok  # undecided: nothing recorded at all
        else:
            entry = saved[voice.reference_name]
            assert entry["approved"] is True and entry["wav_sha256"] == voice.reference_sha256
            assert entry["approved_by"] == "owner (review page)" and entry["approved_on"] == "2026-10-21"
            assert loaded.ok and loaded.text == f"Corrected words for {voice.reference_name}."
    assert sum("APPROVED" in line for line in report) == 4
    assert not list(tmp_path.glob("*.tmp"))


def test_text_is_normalised_but_the_words_are_untouched(tmp_path, drafts):
    target = tmp_path / "t.json"
    path = decisions_file(tmp_path, drafts, decisions={"qwen3-female-1": {"text": "  Line one.\n\nLine   two. \t"}})
    review.apply(path, write=True, drafts_path=drafts, target=target)
    assert json.loads(target.read_text("utf-8"))["Female-1"]["text"] == "Line one. Line two."


def test_a_report_never_echoes_a_transcript(tmp_path, drafts):
    path = decisions_file(tmp_path, drafts, decisions={"qwen3-female-1": {"text": SECRET}})
    for write in (False, True):
        report = "\n".join(review.apply(path, write=write, drafts_path=drafts, target=tmp_path / "t.json"))
        assert SECRET not in report and "Corrected words" not in report


@pytest.mark.parametrize("change, message", [
    ({"listened": False}, "without 'I listened"),
    ({"listened": None}, "without 'I listened"),
    ({"text": "   "}, "1-2000 characters"),
    ({"text": "x" * 2001}, "1-2000 characters"),
    ({"wav_sha256": "0" * 64}, "different recording"),
    ({"reference_name": "Male-1"}, "different recording"),
    ({"decision": "APPROVED"}, "unknown decision"),
    ({"text": 5}, "text is missing")])
def test_an_unsafe_or_malformed_pass_is_refused_and_nothing_is_written(tmp_path, drafts, change, message):
    target = tmp_path / "t.json"
    path = decisions_file(tmp_path, drafts, decisions={"qwen3-female-2": change})
    with pytest.raises(review.ReviewError, match=message):
        review.apply(path, write=True, drafts_path=drafts, target=target)
    assert not target.exists()


def test_a_stale_foreign_or_incomplete_file_is_refused(tmp_path, drafts):
    target = tmp_path / "t.json"
    good = decisions_file(tmp_path, drafts)
    stale = decisions_file(tmp_path, drafts, name="stale.json", review_id="deadbeefdeadbeef")
    with pytest.raises(review.ReviewError, match="different version"):
        review.apply(stale, write=True, drafts_path=drafts, target=target)
    for mutate, message in ((lambda d: d.update(kind="something-else"), "not a decisions file"),
                            (lambda d: d.update(schema=99), "not a decisions file"),
                            (lambda d: d["decisions"].pop(), "exactly the six"),
                            (lambda d: d["decisions"].append(dict(d["decisions"][0])), "exactly the six"),
                            (lambda d: d["decisions"][0].update(voice_id="qwen3-aiden"), "exactly the six")):
        data = json.loads(good.read_text("utf-8"))
        mutate(data)
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(review.ReviewError, match=message):
            review.apply(bad, write=True, drafts_path=drafts, target=target)
    (tmp_path / "junk.json").write_text("not json", encoding="utf-8")
    with pytest.raises(review.ReviewError, match="could not be read"):
        review.apply(tmp_path / "junk.json", write=True, drafts_path=drafts, target=target)
    assert not target.exists()


def test_other_entries_survive_and_the_previous_file_is_kept(tmp_path, drafts):
    target = tmp_path / "t.json"
    target.write_text(json.dumps({"Male-3": {"text": "earlier", "approved": True, "wav_sha256": "x"}, "Other": 1}), encoding="utf-8")
    original = target.read_bytes()
    path = decisions_file(tmp_path, drafts, decisions={"qwen3-male-3": {"decision": None}})
    review.apply(path, write=True, drafts_path=drafts, target=target)
    saved = json.loads(target.read_text("utf-8"))
    assert saved["Male-3"]["text"] == "earlier" and saved["Other"] == 1  # an undecided voice keeps what it had
    assert (tmp_path / "t.json.previous").read_bytes() == original


def test_apply_never_touches_the_drafts_or_the_recordings(tmp_path, drafts):
    watched = [rt.reference_path(v) for v in review.clone_voices()] + [drafts]
    before = {p: p.read_bytes() for p in watched}
    review.apply(decisions_file(tmp_path, drafts), write=True, drafts_path=drafts, target=tmp_path / "t.json")
    assert {p: p.read_bytes() for p in watched} == before
    assert all(json.loads(drafts.read_text("utf-8"))[v.reference_name]["approved"] is False for v in review.clone_voices())


def test_the_real_destination_is_the_local_untracked_file_the_app_reads():
    target = rt.local_transcripts_path()
    assert target.name == "transcripts.json" and "runtime-data" in target.parts
    assert subprocess.run(["git", "check-ignore", "-q", str(target)], cwd=REPO_ROOT).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", str(review.PAGE)], cwd=REPO_ROOT).returncode == 0  # the page holds drafts: ignored too
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert "transcripts.json" not in tracked and "review.html" not in tracked


def test_status_reports_without_printing_text(tmp_path, drafts):
    target = tmp_path / "t.json"
    review.apply(decisions_file(tmp_path, drafts, decisions={"qwen3-male-1": {"decision": review.NEEDS_CORRECTION}}),
                 write=True, drafts_path=drafts, target=target)
    lines = review.status(target)
    assert len(lines) == 6 and lines[2].startswith("Qwen3 - Male 1: NOT approved") and lines[0].endswith("approved")
    assert not any("Corrected words" in line for line in lines)
