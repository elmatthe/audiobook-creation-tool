"""Offline, deterministic tests for the v0.6.7 Plan 01 voice-evaluation tooling.

Nothing here loads a model, touches a GPU, downloads anything or synthesises audio. Fake workers and
fake audio stand in for the engines. The tooling is dev-only (``files/dev-tools/``), so these tests also
prove it can be imported in the root interpreter without Qwen/torch installed and that the production
registry, corpus and sample-generator modes are unchanged.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = REPO_ROOT / "files" / "dev-tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import qwen_eval_assets as assets  # noqa: E402
import qwen_eval_baseline_worker as baseline  # noqa: E402
import qwen_eval_cli as cli  # noqa: E402
import qwen_eval_core as core  # noqa: E402
import qwen_eval_corpus as corpus  # noqa: E402

SR = 24000


def tone(seconds: float, level: float = 0.2, rate: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * 220 * t)).astype("float32")


# --------------------------------------------------------------------------- #
# Inventory: exactly 27 short rows; the production registry is untouched
# --------------------------------------------------------------------------- #
def test_short_inventory_is_exactly_the_requested_twenty_seven():
    rows = core.short_rows()
    assert len(rows) == 27 == len({r["row_id"] for r in rows})
    by_group = {g: [r["display"] for r in rows if r["group"] == g] for g in core.GROUPS}
    assert by_group[core.GROUP_QWEN_PRESET] == ["Aiden", "Dylan", "Eric", "Ono_Anna", "Ryan", "Serena", "Sohee",
                                                "Uncle_Fu", "Vivian"]
    assert by_group[core.GROUP_QWEN_CLONE] == ["Female-1", "Female-2", "Male-1", "Male-2", "Male-3", "Male-4"]
    assert by_group[core.GROUP_CHATTERBOX] == by_group[core.GROUP_QWEN_CLONE]
    assert by_group[core.GROUP_KOKORO] == ["am_michael", "bm_george", "am_fenrir", "am_puck", "am_onyx", "bm_daniel"]
    assert all(r["status"] == "pending" and r["human_review"] == "needs-listening" for r in rows)


def test_every_clone_is_paired_with_its_chatterbox_baseline():
    rows = {r["row_id"]: r for r in core.short_rows()}
    for display, voice_id in core.REFERENCE_VOICE_IDS:
        clone, baseline_row = rows[core.clone_row_id(display)], rows[voice_id]
        assert baseline_row["paired_with"] == clone["row_id"]
        assert clone["paired_with"] == voice_id
        assert clone["language"] == "English"


def test_kokoro_rows_route_languages_like_the_engine_and_flag_candidates():
    from tts import kokoro_synth

    for row in (r for r in core.short_rows() if r["group"] == core.GROUP_KOKORO):
        assert kokoro_synth._lang_code_for_voice(row["voice_id"]) == row["lang_code"]
        assert row["speed"] == 1.0
    status = {v: s for v, s, _ in core.KOKORO_VOICES}
    assert [v for v, s in status.items() if s == "existing"] == ["am_michael", "bm_george"]
    assert [v for v, s in status.items() if s == "candidate"] == ["am_fenrir", "am_puck", "am_onyx", "bm_daniel"]


def test_the_decision_b_kokoro_voices_are_registered_and_qwen_is_not_yet():
    from tts.voice_registry import VOICES

    kokoro = [v.voice_id for v in VOICES if v.backend == "kokoro"]
    # Evaluation candidates until the owner's 2026-10-19 Decision B, registered since; the existing five are untouched.
    for voice_id in ("af_heart", "af_bella", "am_michael", "bf_emma", "bm_george",
                     "am_fenrir", "am_puck", "am_onyx", "bm_daniel"):
        assert voice_id in kokoro
    assert len(kokoro) == 9
    chatterbox = [v.voice_id for v in VOICES if v.backend == "chatterbox"]
    assert chatterbox == [voice_id for _, voice_id in core.REFERENCE_VOICE_IDS]
    assert not any("qwen" in v.voice_id.lower() for v in VOICES)


def test_kokoro_inventory_reports_registry_status_without_loading_anything():
    inventory = cli.kokoro_inventory()
    assert set(inventory) == {"am_michael", "bm_george", "am_fenrir", "am_puck", "am_onyx", "bm_daniel"}
    assert all(i["registered"] for i in inventory.values())  # all six evaluation voices are ACT voices now
    assert all(i["lang_code"] == ("b" if v.startswith("bm_") else "a") for v, i in inventory.items())


def test_long_rows_exist_only_for_known_presets_and_clones():
    assert core.long_row(core.GROUP_QWEN_PRESET, "Aiden")["row_id"] == "long-qwen-preset-aiden"
    assert core.long_row(core.GROUP_QWEN_CLONE, "Male-2")["row_id"] == "long-qwen-clone-male-2"
    with pytest.raises(ValueError):
        core.long_row(core.GROUP_QWEN_PRESET, "Nobody")
    with pytest.raises(ValueError):
        core.long_row(core.GROUP_KOKORO, "am_michael")


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
def test_production_corpus_identity_is_unchanged():
    from tts import quality_corpus

    assert quality_corpus.corpus_identity() == "407fa95d7c524c64"


@pytest.mark.parametrize("name", ["eval_short", "eval_long"])
def test_evaluation_passages_meet_their_word_targets_and_have_no_metadata_lines(name):
    passage = corpus.PASSAGES[name]
    low, high = corpus.WORD_TARGETS[name]
    assert low <= passage.word_count <= high
    assert corpus.reserved_prefix_lines(passage.text) == []
    assert passage.text == passage.text.strip() and "\r" not in passage.text
    assert len(passage.sha256) == 64


def test_passages_contain_the_required_stress_features():
    text = corpus.EVAL_LONG.text + corpus.EVAL_SHORT.text
    for needle in ("Dr. ", "Mr. ", "Mrs. ", "Prof. ", "St. ", "A. M. ", "e.g.", "vs.", "4:50", "2.5", "3:1", "...",
                   "14th", "Kaerthellin", "Ysolde", "\"", "\n\n"):
        assert needle in text, needle
    assert corpus.EVAL_LONG.text.count("Kaerthellin") >= 4


# --------------------------------------------------------------------------- #
# Chunk plan: ordered source spans, no loss, no duplication
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["eval_short", "eval_long"])
@pytest.mark.parametrize("ceiling", [120, 300, 600, 900])
def test_plan_preserves_the_source_at_any_reasonable_ceiling(name, ceiling):
    text = corpus.PASSAGES[name].text
    chunks = core.plan_chunks(text, ceiling)
    core.verify_plan(text, chunks)
    assert all(len(c.text) <= ceiling for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(a.end <= b.start for a, b in zip(chunks, chunks[1:]))
    assert "".join("".join(c.text.split()) for c in chunks) == "".join(text.split())


def test_no_chunk_crosses_a_paragraph_or_title_boundary():
    text = corpus.EVAL_LONG.text
    chunks = core.plan_chunks(text, 900)
    for chunk in chunks:
        assert "\n\n" not in text[chunk.start:chunk.end]
    assert chunks[0].text == "The Ninth Bell of Kaerthellin"
    assert chunks[0].boundary == "paragraph" and chunks[-1].boundary == "end"
    assert len({c.paragraph for c in chunks}) == text.count("\n\n") + 1


def test_abbreviations_initials_decimals_and_times_never_end_a_chunk():
    text = ("Dr. Elena Marsh and J. R. Alvarez met Mr. Okafor at 6:45. The ratio was 3:1, i.e. close, e.g. 2.5 "
            "degrees per second. Prof. Whitfield disagreed, vs. the rest. It ended. And so on.")
    for ceiling in range(50, 120, 7):
        for chunk in core.plan_chunks(text, ceiling):
            tail = chunk.text.rstrip()
            for abbreviation in ("Dr.", "Mr.", "Prof.", "J.", "R.", "i.e.", "e.g.", "vs."):
                assert not tail.endswith(abbreviation) or chunk.boundary in ("clause", "word"), (ceiling, tail)


def test_oversized_sentences_split_at_clauses_then_words_and_keep_every_word():
    sentence = ("one two three, " * 12 + "four five six; " * 6 + "seven eight nine " * 9).strip() + "."
    chunks = core.plan_chunks(sentence, 80)
    core.verify_plan(sentence, chunks)
    assert len(chunks) > 3 and all(len(c.text) <= 80 for c in chunks)
    assert {c.boundary for c in chunks[:-1]} <= {"clause", "word", "sentence"}
    assert " ".join(c.text for c in chunks).split() == sentence.split()


def test_an_unbreakable_token_longer_than_the_ceiling_is_refused_not_cut():
    with pytest.raises(core.ChunkPlanError):
        core.plan_chunks("short " + "x" * 400 + " tail.", 100)


def test_empty_text_has_no_plan_and_tiny_ceilings_are_refused():
    with pytest.raises(core.ChunkPlanError):
        core.verify_plan("", [])
    with pytest.raises(ValueError):
        core.plan_chunks("Hello world.", 10)


def test_a_tampered_plan_is_rejected():
    text = corpus.EVAL_SHORT.text
    chunks = core.plan_chunks(text, 300)
    with pytest.raises(core.ChunkPlanError):  # dropped chunk
        core.verify_plan(text, chunks[:-1])
    with pytest.raises(core.ChunkPlanError):  # duplicated chunk
        core.verify_plan(text, chunks + chunks[-1:])
    with pytest.raises(core.ChunkPlanError):  # reordered
        core.verify_plan(text, [chunks[1], chunks[0], *chunks[2:]])
    bad = core.Chunk(0, chunks[0].start, chunks[0].end, chunks[0].text.replace("Captain", "Kaptain"),
                     chunks[0].boundary, 0)
    with pytest.raises(core.ChunkPlanError):  # wording changed
        core.verify_plan(text, [bad, *chunks[1:]])


def test_plan_hash_changes_with_ceiling_and_is_stable():
    text = corpus.EVAL_LONG.text
    assert core.plan_hash(core.plan_chunks(text, 600)) == core.plan_hash(core.plan_chunks(text, 600))
    assert core.plan_hash(core.plan_chunks(text, 300)) != core.plan_hash(core.plan_chunks(text, 600))


# --------------------------------------------------------------------------- #
# Assembly and measurement
# --------------------------------------------------------------------------- #
def test_assembly_adds_exactly_the_configured_silences_and_reports_every_join():
    parts = [tone(1.0), tone(0.5), tone(2.0)]
    out, report = core.assemble(parts, SR, ["sentence", "paragraph", "end"])
    gap, end = int(SR * 0.05), int(SR * 3.0)
    assert out.size == sum(p.size for p in parts) + 3 * gap + end == report["total_samples"]
    assert report["speech_samples"] == sum(p.size for p in parts)
    assert report["inserted_samples"] == 3 * gap + end
    first, second = report["joins"][0], report["joins"][1]
    assert first["start_sample"] == 0 and first["end_sample"] == parts[0].size
    assert second["start_sample"] == parts[0].size + gap
    assert np.array_equal(out[: parts[0].size], parts[0])
    assert not out[parts[0].size: parts[0].size + gap].any() and not out[-end:].any()
    assert [j["boundary"] for j in report["joins"]] == ["sentence", "paragraph", "end"]


def test_assembly_never_normalises_trims_or_crossfades():
    loud = np.full(1000, 0.9, dtype="float32")
    out, _ = core.assemble([loud, loud], SR, gap_ms=0, end_silence_ms=0)
    assert np.array_equal(out, np.concatenate([loud, loud]))


@pytest.mark.parametrize("bad", [np.zeros(0, "float32"), np.zeros((2, 10), "float32"),
                                 np.array([0.1, np.nan], "float32"), np.array([np.inf], "float32")])
def test_assembly_stops_on_empty_multichannel_or_non_finite_chunks(bad):
    with pytest.raises(core.AssemblyError):
        core.assemble([tone(0.2), bad], SR)
    with pytest.raises(core.AssemblyError):
        core.assemble([], SR)


def test_assembly_verification_catches_a_wrong_sample_count():
    _, report = core.assemble([tone(0.3)], SR)
    report["total_samples"] += 1
    with pytest.raises(core.AssemblyError):
        core.verify_assembly(report, [int(SR * 0.3)])


def test_measurements_flag_clipping_silence_and_implausible_pacing():
    clipped = np.concatenate([tone(1.0), np.full(10, 1.0, "float32")])
    assert core.measure_samples(clipped, SR)["clipped_samples"] >= 10
    assert core.measure_samples(np.full(100, 1.5, "float32"), SR)["over_full_scale_samples"] == 100
    gappy = np.concatenate([tone(1.0), np.zeros(SR * 5, "float32"), tone(1.0)])
    seconds, at = core.longest_silence(gappy, SR)
    assert 4.9 <= seconds <= 5.1 and 0.9 <= at <= 1.1
    chunk = core.Chunk(0, 0, 10, "x" * 10, "end", 0)  # 10 characters spread over 7 seconds
    warnings = core.mechanical_warnings([chunk], [gappy], SR, (45, 90))
    assert any("near-silence" in w for w in warnings)
    assert any("chars/s" in w for w in warnings)
    assert any("outside the 45-90s target" in w for w in warnings)
    assert core.mechanical_warnings([chunk], [], SR, completed_chunks=0)[0].startswith("incomplete")


def test_a_clean_chunk_has_no_mechanical_warnings():
    text = "word " * 60
    chunk = core.Chunk(0, 0, len(text), text.strip(), "end", 0)
    assert core.mechanical_warnings([chunk], [tone(20.0)], SR, (10, 30)) == []


def test_wav_writer_keeps_pcm16_for_normal_audio_and_float_when_it_would_clip(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    ok = core.write_wav(tmp_path / "ok.wav", tone(0.2), SR, base=tmp_path)
    assert ok["subtype"] == "PCM_16" and ok["path"] == "ok.wav"
    hot = core.write_wav(tmp_path / "hot.wav", np.full(100, 1.4, "float32"), SR, base=tmp_path)
    assert hot["subtype"] == "FLOAT"
    data, rate = core.read_wav(tmp_path / "hot.wav")
    assert rate == SR and abs(float(data.max()) - 1.4) < 1e-6  # not normalised, not clipped
    chunk = core.write_wav(tmp_path / "c.wav", tone(0.1), SR, float_chunk=True, base=tmp_path)
    assert chunk["subtype"] == "FLOAT"
    assert soundfile.info(str(tmp_path / "ok.wav")).samplerate == SR


# --------------------------------------------------------------------------- #
# Seeds, manifest, resume
# --------------------------------------------------------------------------- #
def test_seed_derivation_is_stable_distinct_and_bounded():
    a = core.derive_seed("qwen-preset-aiden", 0)
    assert a == core.derive_seed("qwen-preset-aiden", 0)
    assert len({core.derive_seed("qwen-preset-aiden", i) for i in range(50)}) == 50
    assert core.derive_seed("qwen-preset-aiden", 0, attempt=2) != a
    assert core.derive_seed("qwen-preset-dylan", 0) != a
    assert 0 <= a <= 0x7FFFFFFF


def test_manifest_is_written_atomically_and_never_clobbers_recorded_state(tmp_path):
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    manifest.update("kokoro-am_michael", status="succeeded", outputs={"wav": {"path": "k.wav"}})
    assert not (tmp_path / "m.jsonl.tmp").exists()
    fresh = core.Manifest(tmp_path / "m.jsonl")
    assert len(fresh.rows) == 27 and fresh.get("kokoro-am_michael")["status"] == "succeeded"
    fresh.declare(core.short_rows())  # redeclaring must not reset a recorded row
    assert fresh.get("kokoro-am_michael")["status"] == "succeeded"
    with pytest.raises(ValueError):
        fresh.update("kokoro-am_michael", status="approved")


def test_a_rerun_retires_the_old_attempt_instead_of_overwriting_it(tmp_path):
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    manifest.update("chatterbox-female-1" if False else "chatterbox-female-1", status="failed",
                    status_reason="boom", identity="abc", outputs={"mp3": {"path": "x.mp3"}})
    manifest.retire_attempt("chatterbox-female-1", "rerun")
    row = manifest.get("chatterbox-female-1")
    assert row["status"] == "pending" and "outputs" not in row
    assert row["attempts"][0]["status"] == "failed" and row["attempts"][0]["status_reason"] == "boom"
    assert row["attempts"][0]["retired_because"] == "rerun"


def test_resume_requires_matching_identity_and_intact_files(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"audio")
    row = {"status": "succeeded", "identity": "id1", "outputs": {"wav": {
        "path": "a.wav", "bytes": 5, "sha256": core.sha256_file(wav)}}}
    assert core.can_resume(row, "id1", tmp_path)
    assert not core.can_resume(row, "id2", tmp_path)  # source/profile/transcript changed
    wav.write_bytes(b"audiO")
    assert not core.can_resume(row, "id1", tmp_path)  # same size, different bytes
    wav.unlink()
    assert not core.can_resume(row, "id1", tmp_path)
    assert not core.can_resume({**row, "status": "failed"}, "id1", tmp_path)
    assert not core.can_resume({"status": "succeeded", "identity": "id1"}, "id1", tmp_path)


def test_identity_hash_is_order_independent_and_sensitive():
    assert core.identity_hash({"a": 1, "b": 2}) == core.identity_hash({"b": 2, "a": 1})
    assert core.identity_hash({"a": 1}) != core.identity_hash({"a": 2})


# --------------------------------------------------------------------------- #
# Worker protocol, interpreters and child environments
# --------------------------------------------------------------------------- #
def test_event_lines_round_trip_and_garbage_is_ignored(capsys):
    core.emit({"event": "chunk_done", "row_id": "r", "chunk": 3})
    line = capsys.readouterr().out.strip()
    assert core.parse_event(line) == {"event": "chunk_done", "row_id": "r", "chunk": 3}
    for junk in ("", "warning: something", "@@EVENT not-json", '@@EVENT {"no_event_key": 1}', '@@EVENT [1, 2]'):
        assert core.parse_event(junk) is None


def test_interpreters_are_absolute_venv_paths(tmp_path):
    root = core.root_python(tmp_path)
    work = core.eval_python(tmp_path / "work")
    assert root.is_absolute() and ".venv" in root.parts and root.name.startswith("python")
    assert work.is_absolute() and ".venv" in work.parts
    assert root != work


def test_qwen_child_env_keeps_every_cache_inside_the_work_area(tmp_path):
    base = {"HF_HOME": "C:/Users/someone/.cache/huggingface", "HUGGINGFACE_HUB_CACHE": "C:/elsewhere",
            "TRANSFORMERS_CACHE": "C:/elsewhere2", "TEMP": "C:/Windows/Temp", "PATH": "x"}
    env = core.child_env("qwen", base, tmp_path, offline=True)
    for key in ("HF_HOME", "TORCH_HOME", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME", "TEMP", "TMP", "TMPDIR"):
        assert Path(env[key]).is_relative_to(tmp_path), key
    assert "HUGGINGFACE_HUB_CACHE" not in env and "TRANSFORMERS_CACHE" not in env
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["GRADIO_ANALYTICS_ENABLED"] == "False"
    assert base["HF_HOME"] == "C:/Users/someone/.cache/huggingface"  # caller's mapping untouched


def test_root_child_env_keeps_the_existing_model_cache_and_can_go_offline(tmp_path):
    env = core.child_env("root", {"HF_HOME": "keep-me"}, tmp_path)
    assert env["HF_HOME"] == "keep-me" and "HF_HUB_OFFLINE" not in env
    assert Path(env["TEMP"]).is_relative_to(tmp_path)
    assert core.child_env("root", {}, tmp_path, offline=True)["HF_HUB_OFFLINE"] == "1"
    with pytest.raises(ValueError):
        core.child_env("other", {}, tmp_path)


# --------------------------------------------------------------------------- #
# Pinned assets
# --------------------------------------------------------------------------- #
def test_every_pinned_asset_is_an_immutable_revision_with_a_licence():
    for key, spec in assets.ASSETS.items():
        assert len(spec["revision"]) == 40 and set(spec["revision"]) <= set("0123456789abcdef"), key
        assert spec["license"] == "apache-2.0"
    assert assets.ASSETS["whisper-small-en"]["allow"] and "model.safetensors" in assets.ASSETS["whisper-small-en"]["allow"]
    assert not any(n.endswith((".msgpack", ".h5", ".bin")) for n in assets.ASSETS["whisper-small-en"]["allow"])


def test_file_selection_refuses_an_allow_list_that_names_a_missing_file():
    assert assets.select_files(["b", "a"], None) == ["a", "b"]
    assert assets.select_files(["a", "b", "c"], ["c", "a"]) == ["a", "c"]
    with pytest.raises(ValueError):
        assets.select_files(["a"], ["a", "ghost"])


def test_snapshot_verification_detects_missing_truncated_and_altered_files(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "MODELS_DIR", tmp_path)
    snap = assets.snapshot_dir("qwen-customvoice")
    snap.mkdir(parents=True)
    (snap / "a.bin").write_bytes(b"hello")
    expected = {"a.bin": {"size": 5, "sha256": assets.sha256_file(snap / "a.bin")},
                "b.bin": {"size": 1, "sha256": "0" * 64}}
    assert any("missing b.bin" in p for p in assets.snapshot_problems("qwen-customvoice", expected))
    (snap / "b.bin").write_bytes(b"xy")
    assert any("size" in p for p in assets.snapshot_problems("qwen-customvoice", expected))
    (snap / "b.bin").write_bytes(b"z")
    assert any("sha256 mismatch" in p for p in assets.snapshot_problems("qwen-customvoice", expected))
    assert assets.snapshot_problems("qwen-customvoice", expected, verify_hash=False) == []
    assert assets.snapshot_problems("qwen-base") == ["qwen-base: snapshot directory is missing"]


# --------------------------------------------------------------------------- #
# Reference integrity
# --------------------------------------------------------------------------- #
def test_the_six_bundled_references_are_read_only_inputs_that_match_their_hashes():
    snapshot = cli.reference_snapshot()
    assert list(snapshot) == [d for d, _ in core.REFERENCE_VOICE_IDS]
    for name, info in snapshot.items():
        assert info["ok"], name
        assert info["sha256"] == info["registered_sha256"]
        assert (info["subtype"], info["channels"], info["samplerate"]) == ("PCM_16", 1, 24000)
    assert cli.compare_references(snapshot, cli.reference_snapshot()) == []


def test_reference_comparison_reports_missing_changed_and_mismatched_files():
    good = {"sha256": "a", "mtime_ns": 1, "ok": True}
    before = {"Female-1": good, "Male-1": good}
    assert cli.compare_references(before, dict(before)) == []
    changed = {**before, "Male-1": {**good, "sha256": "b"}}
    assert any("changed" in p for p in cli.compare_references(before, changed))
    bad = {**before, "Male-1": {**good, "ok": False}}
    assert any("does not match" in p for p in cli.compare_references(before, bad))
    assert any("disappeared" in p for p in cli.compare_references(before, {"Female-1": good}))


# --------------------------------------------------------------------------- #
# Transcript gate
# --------------------------------------------------------------------------- #
def make_run(tmp_path) -> "cli.Run":
    return cli.Run("t", work_dir=tmp_path)


def test_a_whisper_draft_never_counts_as_a_verified_transcript(tmp_path):
    run = make_run(tmp_path)
    assert cli.approved_transcript(run, "Female-1")[0] is None
    path = run.dir / "transcripts" / "verified.json"
    path.write_text(json.dumps({"Female-1": {"text": "hello there", "approved": False}}), encoding="utf-8")
    text, why = cli.approved_transcript(run, "Female-1")
    assert text is None and "awaiting owner verification" in why
    path.write_text(json.dumps({"Female-1": {"text": "hello there", "approved": "yes"}}), encoding="utf-8")
    assert cli.approved_transcript(run, "Female-1")[0] is None  # only a literal true approves
    path.write_text(json.dumps({"Female-1": {"text": "  ", "approved": True}}), encoding="utf-8")
    assert cli.approved_transcript(run, "Female-1")[0] is None
    path.write_text(json.dumps({"Female-1": {"text": " corrected text. ", "approved": True}}), encoding="utf-8")
    assert cli.approved_transcript(run, "Female-1") == ("corrected text.", "ok")
    assert cli.approved_transcript(run, "Male-1")[0] is None


def test_transcript_states_feed_the_listening_index(tmp_path):
    run = make_run(tmp_path)
    (run.dir / "transcripts" / "verified.json").write_text(json.dumps({
        "Female-1": {"text": "a", "approved": True}, "Female-2": {"text": "b", "approved": False}}), encoding="utf-8")
    states = cli.transcript_states(run)
    assert states["Female-1"] == "approved"
    assert states["Female-2"] == "draft awaiting your verification"
    assert states["Male-4"] == "not drafted"


# --------------------------------------------------------------------------- #
# Orchestration with fake workers: gating, failure isolation, interruption
# --------------------------------------------------------------------------- #
FAKE_WORKER = textwrap.dedent('''
    import json, sys
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    open(job["run_dir"] + "/seen-job.json", "w", encoding="utf-8").write(json.dumps(job))
    def ev(**e): print("@@EVENT " + json.dumps(e), flush=True)
    script = job.get("script", "")
    for row in job["rows"]:
        ev(event="row_start", row_id=row["row_id"], chunks=1)
        if script == "crash":
            sys.exit(7)
        if script == "fail":
            ev(event="row_failed", row_id=row["row_id"], reason="synthetic failure")
            continue
        ev(event="row_done", row_id=row["row_id"], wav={"path": "x.wav"})
    ev(event="worker_done")
''')


@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    """A Run in a temp work area with a stand-in 'evaluation interpreter' and worker."""
    run = make_run(tmp_path)
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    py = core.eval_python(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"")
    monkeypatch.setattr(cli, "WORKER", worker)
    monkeypatch.setattr(cli, "BASELINE_WORKER", worker)
    monkeypatch.setattr(assets, "load_record", lambda: {"qwen-customvoice": {"files": {}, "snapshot": "s"},
                                                        "qwen-base": {"files": {}, "snapshot": "s"}})
    monkeypatch.setattr(assets, "snapshot_problems", lambda *a, **k: [])
    # run_worker launches ``python <script> <job>``; use the real interpreter for the fake worker script
    real_run_worker = cli.run_worker
    monkeypatch.setattr(cli, "run_worker", lambda r, python, script, job, label, env, on_event:
                        real_run_worker(r, Path(sys.executable), script, job, label, env, on_event))
    return run


def test_unapproved_transcripts_block_clone_rows_and_no_worker_is_started(fake_env, monkeypatch):
    run = fake_env
    started = []
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: started.append(a) or 0)
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_CLONE]
    run.manifest.declare(rows)
    cli.run_qwen_group(run, [run.manifest.get(r["row_id"]) for r in rows], mode="clone", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot=cli.reference_snapshot(),
                       label="t-clone")
    assert started == []
    for row in rows:
        live = run.manifest.get(row["row_id"])
        assert live["status"] == "blocked" and "transcript not verified" in live["status_reason"]


def test_only_approved_clones_run_and_they_get_the_exact_approved_text(fake_env, monkeypatch):
    run = fake_env
    snapshot = cli.reference_snapshot()
    (run.dir / "transcripts" / "verified.json").write_text(json.dumps({
        "Female-1": {"text": "The approved words.", "approved": True, "wav_sha256": snapshot["Female-1"]["sha256"]},
        "Female-2": {"text": "Draft only.", "approved": False, "wav_sha256": snapshot["Female-2"]["sha256"]}}),
        encoding="utf-8")
    monkeypatch.setattr(cli, "encode_mp3", lambda *a, **k: [])
    seen = []
    real = cli.Tracker.__call__

    def spy(self, ev):
        seen.append(ev["event"])
        return real(self, ev)

    monkeypatch.setattr(cli.Tracker, "__call__", spy)
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_CLONE][:2]
    run.manifest.declare(rows)
    cli.run_qwen_group(run, [run.manifest.get(r["row_id"]) for r in rows], mode="clone", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot=snapshot, label="t-clone")
    job = json.loads((run.dir / "seen-job.json").read_text(encoding="utf-8"))
    assert [r["row_id"] for r in job["rows"]] == ["qwen-clone-female-1"]
    assert job["mode"] == "clone" and job["rows"][0]["reference_text"] == "The approved words."
    assert job["rows"][0]["reference_wav"].endswith("Female-1.wav")
    assert "x_vector" not in json.dumps(job)
    assert run.manifest.get("qwen-clone-female-2")["status"] == "blocked"


def test_a_crashing_worker_marks_open_rows_failed_but_keeps_other_rows(fake_env):
    run = fake_env
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_PRESET][:3]
    run.manifest.declare(core.short_rows())
    run.manifest.update("kokoro-am_michael", status="succeeded", outputs={"wav": {"path": "k.wav"}})
    job_rows = {r["row_id"]: run.manifest.get(r["row_id"]) for r in rows}
    tracker = cli.Tracker(run, run.manifest, job_rows, lambda t, e: None)
    job = {"script": "crash", "run_dir": str(run.dir), "rows": [{"row_id": r["row_id"]} for r in rows]}
    code = cli.run_worker(run, Path(sys.executable), cli.WORKER, job, "crash", core.child_env("qwen", work_dir=run.work),
                          tracker)
    tracker.settle(code)
    assert code == 7
    first = run.manifest.get(rows[0]["row_id"])
    assert first["status"] == "failed" and "exited with code 7" in first["status_reason"]
    assert run.manifest.get(rows[1]["row_id"])["status"] == "pending"  # never started: not claimed failed
    assert run.manifest.get("kokoro-am_michael")["status"] == "succeeded"  # unrelated evidence survives


def test_a_failing_row_does_not_stop_the_rows_after_it(fake_env):
    run = fake_env
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_KOKORO][:3]
    run.manifest.declare(core.short_rows())
    live = {r["row_id"]: run.manifest.get(r["row_id"]) for r in rows}
    done = []
    tracker = cli.Tracker(run, run.manifest, live, lambda t, e: done.append(e["row_id"]))
    job = {"script": "fail", "run_dir": str(run.dir), "rows": [{"row_id": r["row_id"]} for r in rows]}
    cli.run_worker(run, Path(sys.executable), cli.WORKER, job, "fail", core.child_env("root", work_dir=run.work), tracker)
    assert all(run.manifest.get(r["row_id"])["status"] == "failed" for r in rows)
    assert run.manifest.get(rows[0]["row_id"])["status_reason"] == "synthetic failure"


def test_a_missing_environment_blocks_qwen_rows_instead_of_raising(tmp_path):
    run = make_run(tmp_path)  # no .venv under this work area
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_PRESET][:2]
    run.manifest.declare(rows)
    cli.run_qwen_group(run, [run.manifest.get(r["row_id"]) for r in rows], mode="custom_voice", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot={}, label="t")
    for row in rows:
        assert run.manifest.get(row["row_id"])["status"] == "blocked"
        assert "environment is missing" in run.manifest.get(row["row_id"])["status_reason"]


def test_a_missing_worker_interpreter_is_reported_clearly(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(FileNotFoundError):
        cli.run_worker(run, tmp_path / "nope" / "python.exe", cli.WORKER, {"rows": []}, "x", {}, lambda e: None)


def test_a_completed_identical_row_is_reused_and_a_changed_one_is_retired(fake_env, monkeypatch):
    run = fake_env
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_PRESET][:1]
    run.manifest.declare(rows)
    calls = []
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: calls.append(1) or 0)
    monkeypatch.setattr(cli, "installed_packages", lambda py: {})
    monkeypatch.setattr(cli, "qwen_runtime_problems", lambda *a, **k: [])
    kw = dict(mode="custom_voice", suite_text="short", manifest=run.manifest, snapshot={}, label="t")
    cli.run_qwen_group(run, [run.manifest.get(rows[0]["row_id"])], profile=cli.load_profile(run), **kw)
    row = run.manifest.get(rows[0]["row_id"])
    assert calls == [1] and row["status"] == "pending"
    wav = run.dir / "presets" / "Aiden.wav"
    wav.write_bytes(b"w")
    row.update(status="succeeded", outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 1,
                                                    "sha256": core.sha256_file(wav)}})
    run.manifest.save()
    cli.run_qwen_group(run, [row], profile=cli.load_profile(run), **kw)
    assert calls == [1]  # identical identity and intact files: reused, worker not started
    changed = {**cli.load_profile(run), "max_chars": 300}
    cli.run_qwen_group(run, [row], profile=changed, **kw)
    assert calls == [1]  # stale but complete: kept, not regenerated, unless explicitly asked
    assert run.manifest.get(rows[0]["row_id"])["status"] == "succeeded" and wav.read_bytes() == b"w"
    run.dry_run = True
    cli.run_qwen_group(run, [row], profile=changed, **kw)
    assert calls == [1] and run.manifest.get(rows[0]["row_id"])["status"] == "succeeded"  # a dry run changes nothing
    run.dry_run, run.rerun_stale = False, True
    cli.run_qwen_group(run, [row], profile=changed, **kw)
    assert calls == [1, 1] and run.manifest.get(rows[0]["row_id"])["attempts"][0]["status"] == "succeeded"
    assert (run.dir / run.manifest.get(rows[0]["row_id"])["attempts"][0]["outputs"]["wav"]["path"]).read_bytes() == b"w"


def test_identity_follows_the_pipeline_revision_and_ignores_reporting_code(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    row = next(r for r in core.short_rows() if r["row_id"] == "kokoro-am_michael")
    profile = cli.load_profile(run)
    before = cli.current_identity(run, row, profile, {})
    assert before == cli.current_identity(run, row, profile, {})
    monkeypatch.setattr(cli, "render_listening_index", lambda *a, **k: "edited reporting code")
    monkeypatch.setattr(core, "asr_compare", lambda *a, **k: {"edited": True})
    assert cli.current_identity(run, row, profile, {}) == before  # reporting/ASR edits cannot make rows stale
    monkeypatch.setattr(core, "PIPELINE_REVISION", core.PIPELINE_REVISION + 1)
    assert cli.current_identity(run, row, profile, {}) != before  # an output-affecting revision does


def test_a_good_result_is_never_demoted_because_a_prerequisite_is_temporarily_missing(tmp_path):
    run = make_run(tmp_path)  # no isolated environment here, so Qwen rows are "blocked" for everything else
    run.manifest.declare(core.short_rows())
    wav = run.dir / "presets" / "Aiden.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"audio")
    run.manifest.update("qwen-preset-aiden", status="succeeded", identity="keep-me", outputs={
        "wav": {"path": "presets/Aiden.wav", "bytes": 5, "sha256": core.sha256_file(wav)}})
    row = run.manifest.get("qwen-preset-aiden")
    cli.run_qwen_group(run, [row], mode="custom_voice", suite_text="short", profile=cli.load_profile(run),
                       manifest=run.manifest, snapshot={}, label="t")
    kept = run.manifest.get("qwen-preset-aiden")
    assert kept["status"] == "succeeded" and kept["identity"] == "keep-me" and not kept["attempts"]
    assert wav.read_bytes() == b"audio"


def test_runtime_evidence_drift_makes_a_finished_qwen_row_stale():
    profile = {"dtype": "bfloat16", "attn": "sdpa", "device": "cuda:0", "language": "English", "max_chars": 600,
               "gap_ms": 50, "end_silence_ms": 3000, "seed_base": 1}
    key = "qwen-customvoice"
    want = cli.model_identity(key)
    row = {"row_id": "r", "display": "Aiden", "provenance": {
        "packages": {"python": "3.12.10", "torch": "2.10.0+cu128", "qwen-tts": "0.1.1"},
        "model": {"revision": want["revision"], "generation_config_sha256": want["generation_config_sha256"]},
        "profile": profile}, "chunk_plan": {"plan_sha256": "plan"}}
    freeze = {"torch": "2.10.0+cu128", "qwen-tts": "0.1.1"}

    def check(**override):
        args = dict(profile=profile, key=key, mode="custom_voice", snapshot={}, freeze=freeze, plan_sha="plan")
        args.update(override)
        return cli.qwen_runtime_problems(None, row, **args)

    assert check() == []
    assert any("torch" in p for p in check(freeze={**freeze, "torch": "2.11.0"}))  # a package was upgraded
    assert any("gap_ms" in p for p in check(profile={**profile, "gap_ms": 99}))  # the join profile changed
    assert any("chunk plan" in p for p in check(plan_sha="other"))
    assert any("revision" in p for p in check(key="qwen-base"))  # a different model
    assert cli.qwen_runtime_problems(None, {"row_id": "x"}, profile=profile, key=key, mode="custom_voice",
                                     snapshot={}, freeze=freeze, plan_sha="plan") == ["no recorded provenance"]


def test_runtime_evidence_for_baselines_covers_model_revision_assets_and_device(tmp_path, monkeypatch):
    hub = tmp_path / "hub" / "models--hexgrad--Kokoro-82M"
    (hub / "refs").mkdir(parents=True)
    (hub / "refs" / "main").write_text("rev1", encoding="utf-8")
    voice = hub / "snapshots" / "rev1" / "voices" / "am_michael.pt"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"voice")
    row = {"voice_id": "am_michael", "provenance": {
        "worker_engine_info": {"model": {"revision": "rev1"}, "torch": cli.torch_runtime_version()},
        "asset": {"sha256": core.sha256_file(voice)}}}
    assert cli.root_runtime_problems(row, engine="kokoro", snapshot={}, hf_home=tmp_path) == []
    voice.write_bytes(b"changed voice")
    assert any("voice asset" in p for p in cli.root_runtime_problems(row, engine="kokoro", snapshot={}, hf_home=tmp_path))
    (hub / "refs" / "main").write_text("rev2", encoding="utf-8")
    assert any("model revision" in p for p in cli.root_runtime_problems(row, engine="kokoro", snapshot={}, hf_home=tmp_path))
    assert cli.kokoro_voice_path("am_michael", tmp_path) is None  # refs/main now points at a snapshot without it
    assert cli.root_runtime_problems({"voice_id": "x"}, engine="kokoro", snapshot={}, hf_home=tmp_path) == \
        ["no recorded engine information"]


def test_retiring_an_attempt_moves_its_files_so_a_rerun_cannot_overwrite_them(tmp_path):
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    (tmp_path / "presets").mkdir()
    (tmp_path / "chunks" / "qwen-preset-aiden").mkdir(parents=True)
    wav, chunk = tmp_path / "presets" / "Aiden.wav", tmp_path / "chunks" / "qwen-preset-aiden" / "chunk-001.wav"
    wav.write_bytes(b"first take")
    chunk.write_bytes(b"first chunk")
    manifest.update("qwen-preset-aiden", status="succeeded", identity="old", timing={"audible_s": 70},
                    outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 10, "sha256": core.sha256_file(wav)}})
    manifest.retire_attempt("qwen-preset-aiden", "profile changed", tmp_path)
    row = manifest.get("qwen-preset-aiden")
    attempt = row["attempts"][0]
    assert row["status"] == "pending" and "outputs" not in row and "timing" not in row  # no stale numbers
    assert not wav.exists() and not chunk.exists()  # the rerun's target paths are free
    archived = tmp_path / attempt["outputs"]["wav"]["path"]
    assert archived.read_bytes() == b"first take" and attempt["archive"].startswith("attempts/qwen-preset-aiden/")
    assert (tmp_path / attempt["archive"] / "chunks" / "qwen-preset-aiden" / "chunk-001.wav").read_bytes() == b"first chunk"
    wav.write_bytes(b"second take")  # the rerun writes a new file; the first take is untouched
    assert archived.read_bytes() == b"first take"
    manifest.update("qwen-preset-aiden", status="succeeded", outputs={
        "wav": {"path": "presets/Aiden.wav", "bytes": 11, "sha256": core.sha256_file(wav)}})
    manifest.retire_attempt("qwen-preset-aiden", "again", tmp_path)
    second = manifest.get("qwen-preset-aiden")["attempts"][1]
    assert second["archive"].endswith("attempt-02")
    assert (tmp_path / second["outputs"]["wav"]["path"]).read_bytes() == b"second take"
    assert archived.read_bytes() == b"first take"  # the first attempt's evidence is still intact


def test_evaluation_run_ids_cannot_escape_the_work_area(tmp_path):
    for bad in ("../outside", "..", "a/b", "a\\b", "C:\\temp\\x", "/etc", "", ".hidden", "x" * 80, "a..b",
                "CON", "con.txt", "NUL", "com1", "LPT9.log", "name.", "ok\n"):
        with pytest.raises(ValueError):
            core.validate_run_id(bad)
        with pytest.raises(ValueError):
            cli.Run(bad, work_dir=tmp_path)
    assert not (tmp_path / "outside").exists() and not list(tmp_path.glob("*"))  # nothing was created
    assert cli.Run("qwen3-initial.v2", work_dir=tmp_path).dir == tmp_path / "runs" / "qwen3-initial.v2"


def test_generated_audio_must_be_mono_with_one_consistent_sample_rate():
    good = core.validate_chunk_audio(np.zeros(100, "float64"), 24000, None)
    assert good.dtype == np.float32 and good.shape == (100,)
    assert core.validate_chunk_audio(good, 24000, 24000) is not None
    with pytest.raises(core.AssemblyError, match="shape"):
        core.validate_chunk_audio(np.zeros((2, 100), "float32"), 24000, None)  # never flattened
    with pytest.raises(core.AssemblyError, match="shape"):
        core.validate_chunk_audio(np.zeros((1, 100), "float32"), 24000, None)
    with pytest.raises(core.AssemblyError, match="changed"):
        core.validate_chunk_audio(np.zeros(100, "float32"), 48000, 24000)
    for bad in (0, -1, None, 2.5):
        with pytest.raises(core.AssemblyError, match="invalid sample rate"):
            core.validate_chunk_audio(np.zeros(10, "float32"), bad, None)


def test_a_transcript_approval_is_bound_to_the_recording_it_was_made_for(tmp_path):
    run = make_run(tmp_path)
    path = run.dir / "transcripts" / "verified.json"
    path.write_text(json.dumps({"Male-1": {"text": "words", "approved": True, "wav_sha256": "AAA"}}), encoding="utf-8")
    assert cli.approved_transcript(run, "Male-1", "AAA") == ("words", "ok")
    text, why = cli.approved_transcript(run, "Male-1", "BBB")  # the reference recording was replaced
    assert text is None and "not bound to the current reference recording" in why
    path.write_text(json.dumps({"Male-1": {"text": "words", "approved": True}}), encoding="utf-8")
    assert cli.approved_transcript(run, "Male-1", "AAA")[0] is None  # an unbound approval is not used
    states = cli.transcript_states(run, {"Male-1": {"sha256": "AAA"}})
    assert states["Male-1"] == "approval does not match the current recording"


def test_clone_rows_use_the_hash_bound_approval(fake_env):
    run = fake_env
    snapshot = cli.reference_snapshot()
    (run.dir / "transcripts" / "verified.json").write_text(json.dumps({
        "Female-1": {"text": "approved for some other recording", "approved": True, "wav_sha256": "0" * 64}}),
        encoding="utf-8")
    row = next(r for r in core.short_rows() if r["row_id"] == "qwen-clone-female-1")
    run.manifest.declare([row])
    cli.run_qwen_group(run, [run.manifest.get(row["row_id"])], mode="clone", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot=snapshot, label="t")
    assert run.manifest.get(row["row_id"])["status"] == "blocked"
    assert "not bound" in run.manifest.get(row["row_id"])["status_reason"]


def test_every_worker_invocation_keeps_its_own_job_and_log(fake_env):
    run = fake_env
    for _ in range(2):
        job = {"script": "fail", "run_dir": str(run.dir), "rows": []}
        cli.run_worker(run, Path(sys.executable), cli.WORKER, job, "same-label", core.child_env("root", work_dir=run.work),
                       lambda ev: None)
    assert len(list((run.dir / "jobs").glob("same-label-*.json"))) == 2
    assert len(list((run.dir / "logs").glob("same-label-*.log"))) == 2


def test_root_children_get_the_existing_model_cache_and_no_inherited_overrides(tmp_path):
    base = {"HF_HOME": "C:/elsewhere", "HF_HUB_CACHE": "C:/x", "HUGGINGFACE_HUB_CACHE": "C:/y",
            "TRANSFORMERS_CACHE": "C:/z", "TORCH_HOME": "C:/t", "XDG_CACHE_HOME": "C:/xdg", "NUMBA_CACHE_DIR": "C:/n"}
    cache = tmp_path / "models" / "huggingface"
    for kind in ("root", "qwen"):
        env = core.child_env(kind, base, tmp_path, hf_home=cache if kind == "root" else None)
        assert "HF_HUB_CACHE" not in env and "TRANSFORMERS_CACHE" not in env
        for key in ("TORCH_HOME", "XDG_CACHE_HOME", "NUMBA_CACHE_DIR", "XDG_CONFIG_HOME", "TEMP"):
            assert Path(env[key]).is_relative_to(tmp_path), (kind, key)
    root_env = core.child_env("root", base, tmp_path, hf_home=cache)
    assert Path(root_env["HF_HOME"]) == cache and Path(root_env["HUGGINGFACE_HUB_CACHE"]) == cache / "hub"


def test_torch_local_version_tags_are_kept_so_cpu_builds_are_not_called_changed(tmp_path, monkeypatch):
    version_py = tmp_path / "version.py"
    version_py.write_text("__version__ = '2.6.0+cpu'\ngit_version = 'abc'\n", encoding="utf-8")
    assert cli.read_version_file(version_py) == "2.6.0+cpu"
    assert cli.read_version_file(tmp_path / "missing.py") is None
    version_py.write_text("nothing here\n", encoding="utf-8")
    assert cli.read_version_file(version_py) is None
    # The real defect: package metadata says "2.6.0" while the worker recorded the runtime "2.6.0+cpu".
    monkeypatch.setattr(cli, "installed_version", lambda name: "2.6.0")
    monkeypatch.setattr(cli, "torch_runtime_version", lambda: "2.6.0+cpu")
    monkeypatch.setattr(cli, "hub_main_revision", lambda repo, hf_home=None: "rev")
    kokoro = {"voice_id": "am_michael", "provenance": {"worker_engine_info": {
        "model": {"revision": "rev"}, "torch": "2.6.0+cpu"}, "asset": {"sha256": None}}}
    monkeypatch.setattr(cli, "kokoro_voice_path", lambda voice, hf_home=None: None)
    assert cli.root_runtime_problems(kokoro, engine="kokoro", snapshot={}) == []
    chatterbox = {"voice_id": "chatterbox-female-1", "display": "Female-1", "provenance": {
        "worker_engine_info": {"model": {"revision": "rev"}, "package": "chatterbox-tts==0.1.7", "device": "cpu"},
        "reference": {"sha256": "r"}}}
    monkeypatch.setattr(cli, "installed_version", lambda name: "0.1.7" if name == "chatterbox-tts" else "2.6.0")
    assert cli.root_runtime_problems(chatterbox, engine="chatterbox", snapshot={"Female-1": {"sha256": "r"}}) == []
    monkeypatch.setattr(cli, "torch_runtime_version", lambda: "2.10.0+cu128")  # a CUDA build could now pick the GPU
    assert any("torch build" in p for p in
               cli.root_runtime_problems(chatterbox, engine="chatterbox", snapshot={"Female-1": {"sha256": "r"}}))


def test_the_real_torch_version_reader_keeps_the_local_tag_without_importing_torch(tmp_path):
    fake = tmp_path / "site" / "torch"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("raise ImportError('must never be imported')\n", encoding="utf-8")
    (fake / "version.py").write_text("__version__ = '9.9.9+fake'\n", encoding="utf-8")
    code = ("import sys; sys.path[:0] = [r'%s', r'%s', r'%s']; import qwen_eval_cli as c; "
            "print(c.torch_runtime_version(), 'torch' in sys.modules)") % (tmp_path / "site", TOOLS,
                                                                            REPO_ROOT / "scripts" / "Universal")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["9.9.9+fake", "False"]  # tag kept (metadata would drop it); torch never imported


def test_a_dry_run_reports_decisions_and_changes_nothing(fake_env, monkeypatch):
    run = fake_env
    started = []
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: started.append(a) or 0)
    rows = [r for r in core.short_rows() if r["group"] == core.GROUP_QWEN_PRESET][:2]
    run.manifest.declare(rows)
    before = (run.dir / "manifest.jsonl").read_bytes()
    run.dry_run = True
    cli.run_qwen_group(run, [run.manifest.get(r["row_id"]) for r in rows], mode="custom_voice", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot={}, label="t")
    assert started == [] and (run.dir / "manifest.jsonl").read_bytes() == before
    run.dry_run = False
    cli.run_qwen_group(run, [run.manifest.get(r["row_id"]) for r in rows], mode="custom_voice", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot={}, label="t")
    assert len(started) == 1  # the same call without --eval-dry-run does start the worker


def test_the_cli_flags_reach_the_stage_entry_point(monkeypatch):
    from tts import generate_voice_samples as gvs

    seen = {}
    monkeypatch.setattr(cli, "run", lambda stage, **kw: seen.update(stage=stage, **kw) or 0)
    monkeypatch.setattr(sys, "argv", ["generate_voice_samples.py", "--qwen-eval", "short", "--eval-dry-run",
                                      "--eval-rerun-stale", "--eval-group", "kokoro"])
    assert gvs.main() == 0
    assert seen == {"stage": "short", "run_id": "qwen3-initial", "group": "kokoro", "dry_run": True, "rerun_stale": True}
    default = gvs._build_parser().parse_args(["--qwen-eval", "short"])
    assert default.eval_dry_run is False and default.eval_rerun_stale is False


def test_restoring_a_retired_attempt_brings_back_the_original_files_and_keeps_the_replacement(tmp_path):
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    (tmp_path / "kokoro").mkdir()
    wav = tmp_path / "kokoro" / "am_michael.wav"
    wav.write_bytes(b"original")
    sha = core.sha256_file(wav)
    manifest.update("kokoro-am_michael", status="succeeded", identity="i", timing={"audible_s": 63.7},
                    outputs={"wav": {"path": "kokoro/am_michael.wav", "bytes": 8, "sha256": sha}})
    manifest.retire_attempt("kokoro-am_michael", "spurious rerun", tmp_path)
    wav.write_bytes(b"replacement take")  # what a regeneration would have written
    manifest.update("kokoro-am_michael", status="succeeded", identity="i2",
                    outputs={"wav": {"path": "kokoro/am_michael.wav", "bytes": 16,
                                     "sha256": core.sha256_file(wav)}})
    manifest.restore_attempt("kokoro-am_michael", 0, tmp_path, "undo the spurious rerun")
    row = manifest.get("kokoro-am_michael")
    assert wav.read_bytes() == b"original" and row["identity"] == "i" and row["timing"] == {"audible_s": 63.7}
    assert core.outputs_intact(row, tmp_path) and row["status"] == "succeeded"
    assert len(row["attempts"]) == 1 and row["restorations"][0]["reason"] == "undo the spurious rerun"
    kept = row["attempts"][0]
    assert (tmp_path / kept["outputs"]["wav"]["path"]).read_bytes() == b"replacement take"  # nothing was lost
    with pytest.raises(ValueError):  # an attempt with no archived files cannot be restored
        row["attempts"].append({"status": "failed"})
        manifest.restore_attempt("kokoro-am_michael", 1, tmp_path, "x")


def test_restore_refuses_to_overwrite_an_existing_file(tmp_path):
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    (tmp_path / "kokoro").mkdir()
    wav = tmp_path / "kokoro" / "am_michael.wav"
    wav.write_bytes(b"first")
    manifest.update("kokoro-am_michael", status="succeeded", outputs={
        "wav": {"path": "kokoro/am_michael.wav", "bytes": 5, "sha256": core.sha256_file(wav)}})
    manifest.retire_attempt("kokoro-am_michael", "r", tmp_path)
    wav.write_bytes(b"someone else's file")
    row = manifest.get("kokoro-am_michael")
    with pytest.raises(FileExistsError):
        manifest.restore_attempt("kokoro-am_michael", 0, tmp_path, "undo")
    assert wav.read_bytes() == b"someone else's file"
    assert (tmp_path / row["attempts"][0]["outputs"]["wav"]["path"]).read_bytes() == b"first"


def _tracked_row(tmp_path, name="Aiden", **extra):
    """A manifest row with a real recording, raw chunk, join file and the stored paths that point at them."""
    manifest = core.Manifest(tmp_path / "m.jsonl")
    manifest.declare(core.short_rows())
    (tmp_path / "presets").mkdir(exist_ok=True)
    chunk_dir = tmp_path / "chunks" / f"qwen-preset-{name.lower()}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    wav, mp3 = tmp_path / "presets" / f"{name}.wav", tmp_path / "presets" / f"{name}.mp3"
    wav.write_bytes(b"wav " + name.encode())
    mp3.write_bytes(b"mp3 " + name.encode())
    (chunk_dir / "chunk-001.wav").write_bytes(b"chunk")
    (chunk_dir / "joins.json").write_text("{}", encoding="utf-8")
    manifest.update(f"qwen-preset-{name.lower()}", status="succeeded", identity="i", **extra, outputs={
        "wav": {"path": f"presets/{name}.wav", "bytes": wav.stat().st_size, "sha256": core.sha256_file(wav)},
        "mp3": {"path": f"presets/{name}.mp3", "bytes": mp3.stat().st_size, "sha256": core.sha256_file(mp3)}},
        chunk_results=[{"index": 0, "wav": {"path": f"chunks/qwen-preset-{name.lower()}/chunk-001.wav"}}],
        chunk_plan={"count": 1, "join_file": f"chunks/qwen-preset-{name.lower()}/joins.json"})
    return manifest, f"qwen-preset-{name.lower()}", wav


def test_archive_numbers_are_never_reused_even_after_a_restore(tmp_path):
    manifest, row_id, wav = _tracked_row(tmp_path)
    manifest.retire_attempt(row_id, "first", tmp_path)  # attempt-01
    wav.write_bytes(b"second take")
    manifest.update(row_id, status="succeeded", outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 11,
                                                                 "sha256": core.sha256_file(wav)}})
    manifest.retire_attempt(row_id, "second", tmp_path)  # attempt-02
    manifest.restore_attempt(row_id, 0, tmp_path, "undo first")  # the list is now shorter than the folders are numerous
    wav.write_bytes(b"third take")
    manifest.update(row_id, status="succeeded", outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 10,
                                                                 "sha256": core.sha256_file(wav)}})
    manifest.retire_attempt(row_id, "third", tmp_path)
    archives = sorted(a["archive"] for a in manifest.get(row_id)["attempts"] if a.get("archive"))
    assert len(archives) == len(set(archives)) == 2 and archives[-1].endswith("attempt-03")
    contents = {(tmp_path / a["outputs"]["wav"]["path"]).read_bytes() for a in manifest.get(row_id)["attempts"]
                if a.get("outputs")}
    assert contents == {b"second take", b"third take"}  # no archived take was overwritten


def test_a_move_that_fails_part_way_is_rolled_back_and_the_row_is_unchanged(tmp_path, monkeypatch):
    manifest, row_id, wav = _tracked_row(tmp_path)
    mp3 = tmp_path / "presets" / "Aiden.mp3"
    real, calls = core.os.replace, {"n": 0}

    def flaky(src, dest):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError("sharing violation")
        return real(src, dest)

    monkeypatch.setattr(core.os, "replace", flaky)
    with pytest.raises(PermissionError):
        manifest.retire_attempt(row_id, "retire", tmp_path)
    monkeypatch.setattr(core.os, "replace", real)
    assert wav.read_bytes() == b"wav Aiden" and mp3.read_bytes() == b"mp3 Aiden"  # the first move was put back
    assert (tmp_path / "chunks" / row_id / "chunk-001.wav").is_file()
    row = manifest.get(row_id)
    assert row["status"] == "succeeded" and row["attempts"] == [] and core.outputs_intact(row, tmp_path)


def test_retirement_and_restoration_remap_every_stored_artifact_path(tmp_path):
    manifest, row_id, wav = _tracked_row(tmp_path)
    manifest.retire_attempt(row_id, "regenerate", tmp_path)
    attempt = manifest.get(row_id)["attempts"][0]
    prefix = attempt["archive"] + "/"
    stored = [attempt["outputs"]["wav"]["path"], attempt["outputs"]["mp3"]["path"],
              attempt["chunk_results"][0]["wav"]["path"], attempt["chunk_plan"]["join_file"]]
    assert all(path.startswith(prefix) and (tmp_path / path).exists() for path in stored), stored
    assert not (tmp_path / "chunks" / row_id).exists()  # the active chunk folder is free for the rerun
    manifest.restore_attempt(row_id, 0, tmp_path, "undo")
    row = manifest.get(row_id)
    assert row["chunk_results"][0]["wav"]["path"] == f"chunks/{row_id}/chunk-001.wav"
    assert row["chunk_plan"]["join_file"] == f"chunks/{row_id}/joins.json"
    assert (tmp_path / row["chunk_plan"]["join_file"]).is_file() and core.outputs_intact(row, tmp_path)


def test_a_blocked_row_that_kept_diagnostics_is_archived_before_it_is_regenerated(fake_env, monkeypatch):
    run = fake_env
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: 0)
    row = next(r for r in core.short_rows() if r["row_id"] == "qwen-preset-aiden")
    run.manifest.declare([row])
    (run.dir / "presets").mkdir(exist_ok=True)
    partial = run.dir / "presets" / "Aiden.wav"
    partial.write_bytes(b"partial audio kept as evidence")
    run.manifest.update(row["row_id"], status="blocked", status_reason="environment briefly unavailable",
                        diagnostic_outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 30,
                                                    "sha256": core.sha256_file(partial)}})
    cli.run_qwen_group(run, [run.manifest.get(row["row_id"])], mode="custom_voice", suite_text="short",
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot={}, label="t")
    attempt = run.manifest.get(row["row_id"])["attempts"][0]
    assert not partial.exists()  # the regeneration target is free
    assert (run.dir / attempt["diagnostic_outputs"]["wav"]["path"]).read_bytes() == b"partial audio kept as evidence"


def test_a_finalisation_failure_leaves_the_received_recording_tracked(tmp_path):
    run = make_run(tmp_path)
    run.manifest.declare(core.short_rows())
    wav = run.dir / "presets" / "Aiden.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"received")
    row = run.manifest.get("qwen-preset-aiden")

    def explode(tracker, ev):
        raise RuntimeError("MP3 encoder failed")

    tracker = cli.Tracker(run, run.manifest, {"qwen-preset-aiden": row}, explode)
    tracker({"event": "row_done", "row_id": "qwen-preset-aiden",
             "wav": {"path": "presets/Aiden.wav", "bytes": 8, "sha256": core.sha256_file(wav)}})
    live = run.manifest.get("qwen-preset-aiden")
    assert live["status"] == "failed" and "MP3 encoder failed" in live["status_reason"]
    assert live["diagnostic_outputs"]["wav"]["path"] == "presets/Aiden.wav"
    run.manifest.retire_attempt("qwen-preset-aiden", "retry", run.dir)  # ...so a rerun archives it, not overwrites it
    assert not wav.exists() and run.manifest.get("qwen-preset-aiden")["attempts"][0]["archive"]


def test_runtime_evidence_also_covers_gpu_interpreter_and_recorded_engine_versions(tmp_path, monkeypatch):
    profile = {"dtype": "bfloat16", "attn": "sdpa", "device": "cuda:0", "language": "English", "max_chars": 600,
               "gap_ms": 50, "end_silence_ms": 3000, "seed_base": 1}
    want = cli.model_identity("qwen-customvoice")
    row = {"row_id": "r", "display": "Aiden", "provenance": {
        "packages": {"python": "3.12.10"}, "gpu": {"device": "NVIDIA GeForce RTX 5070"},
        "model": {"revision": want["revision"], "generation_config_sha256": want["generation_config_sha256"]},
        "profile": profile}, "chunk_plan": {"plan_sha256": "plan"}}
    run = make_run(tmp_path)
    (run.work / ".venv").mkdir()
    (run.work / ".venv" / "pyvenv.cfg").write_text("version = 3.12.10\n", encoding="utf-8")
    monkeypatch.setattr(cli, "current_gpu", lambda: ("NVIDIA GeForce RTX 5070", "12.0"))
    args = dict(profile=profile, key="qwen-customvoice", mode="custom_voice", snapshot={}, freeze={}, plan_sha="plan")
    assert cli.qwen_runtime_problems(run, row, **args) == []
    monkeypatch.setattr(cli, "current_gpu", lambda: ("NVIDIA GeForce RTX 9090", "13.0"))
    assert any("GPU" in p for p in cli.qwen_runtime_problems(run, row, **args))
    monkeypatch.setattr(cli, "current_gpu", lambda: None)  # cannot ask: no false alarm
    (run.work / ".venv" / "pyvenv.cfg").write_text("version = 3.13.0\n", encoding="utf-8")
    assert any("interpreter" in p for p in cli.qwen_runtime_problems(run, row, **args))

    monkeypatch.setattr(cli, "torch_runtime_version", lambda: "2.6.0+cpu")
    monkeypatch.setattr(cli, "hub_main_revision", lambda repo, hf_home=None: "rev")
    monkeypatch.setattr(cli, "kokoro_voice_path", lambda voice, hf_home=None: None)
    monkeypatch.setattr(cli, "installed_version", lambda name: {"kokoro": "0.9.4", "misaki": "0.9.4"}.get(name))
    kokoro = {"voice_id": "am_michael", "provenance": {"worker_engine_info": {
        "model": {"revision": "rev"}, "torch": "2.6.0+cpu", "kokoro": "0.9.4", "misaki": "0.9.4"},
        "asset": {"sha256": None}}}
    assert cli.root_runtime_problems(kokoro, engine="kokoro", snapshot={}) == []
    kokoro["provenance"]["worker_engine_info"]["kokoro"] = "0.9.0"
    assert any("kokoro 0.9.0" in p for p in cli.root_runtime_problems(kokoro, engine="kokoro", snapshot={}))
    chatterbox = {"voice_id": "chatterbox-male-1", "display": "Male-1", "provenance": {
        "worker_engine_info": {"model": {"revision": "rev"}, "package": "chatterbox-tts==None", "torch": "2.5.0+cpu",
                               "device": "cpu"}, "reference": {"sha256": "r"}}}
    problems = cli.root_runtime_problems(chatterbox, engine="chatterbox", snapshot={"Male-1": {"sha256": "r"}})
    assert any("torch 2.5.0+cpu -> 2.6.0+cpu" in p for p in problems)  # a different CPU build is a change too


def test_child_env_clears_every_known_library_cache_override(tmp_path):
    names = ["HF_MODULES_CACHE", "HF_XET_CACHE", "HUGGINGFACE_ASSETS_CACHE", "PYTORCH_TRANSFORMERS_CACHE",
             "PYTORCH_PRETRAINED_BERT_CACHE", "TORCHINDUCTOR_CACHE_DIR", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH",
             "TORCH_EXTENSIONS_DIR"]
    base = {name: "C:/outside/" + name for name in names}
    for kind in ("qwen", "root"):
        env = core.child_env(kind, base, tmp_path, hf_home=tmp_path / "hf" if kind == "root" else None)
        for name in names:
            assert name not in env or Path(env[name]).is_relative_to(tmp_path), (kind, name, env.get(name))


def test_empty_or_non_finite_chunks_are_chunk_failures_not_assembly_crashes():
    for bad in (np.zeros(0, "float32"), np.array([0.1, np.nan], "float32"), np.array([np.inf, 0.0], "float32")):
        with pytest.raises(core.AssemblyError):
            core.validate_chunk_audio(bad, 24000, None)


def test_the_qwen_worker_isolates_one_rows_assembly_and_output_failure():
    import ast

    tree = ast.parse((TOOLS / "qwen_eval_worker.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_synth")
    parents = {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}

    def guarded(node) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
                                                 for h in node.handlers):
                return True
        return False

    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("assemble", "write_wav", "measure_samples", "mechanical_warnings")]
    assert len(calls) >= 4 and all(guarded(c) for c in calls)  # one bad row cannot end the worker for the rest


def test_a_dry_run_on_a_fresh_run_creates_no_files_and_no_directories(tmp_path):
    run = cli.Run("fresh", work_dir=tmp_path, dry_run=True)
    cli.stage_short(run, "all")
    assert list(tmp_path.rglob("*")) == []  # not even the run folder


def test_run_construction_creates_the_folders_only_when_not_a_dry_run(tmp_path):
    assert not list(cli.Run("a", work_dir=tmp_path / "x", dry_run=True).dir.parents[1].glob("*"))
    assert (cli.Run("b", work_dir=tmp_path / "y").dir / "kokoro").is_dir()


def test_a_failed_restore_changes_nothing_not_even_the_present_result(tmp_path):
    manifest, row_id, wav = _tracked_row(tmp_path)
    manifest.retire_attempt(row_id, "first", tmp_path)
    wav.write_bytes(b"current take")
    manifest.update(row_id, status="succeeded", outputs={"wav": {"path": "presets/Aiden.wav", "bytes": 12,
                                                                 "sha256": core.sha256_file(wav)}})
    archived = tmp_path / manifest.get(row_id)["attempts"][0]["outputs"]["wav"]["path"]
    archived.unlink()  # the archived take has gone missing
    before = (tmp_path / "m.jsonl").read_bytes()
    with pytest.raises(FileNotFoundError, match="nothing was changed"):
        manifest.restore_attempt(row_id, 0, tmp_path, "undo")
    row = manifest.get(row_id)
    assert row["status"] == "succeeded" and wav.read_bytes() == b"current take" and len(row["attempts"]) == 1
    assert (tmp_path / "m.jsonl").read_bytes() == before and core.outputs_intact(row, tmp_path)


def test_a_failing_manifest_save_puts_the_moved_files_back(tmp_path, monkeypatch):
    manifest, row_id, wav = _tracked_row(tmp_path)
    monkeypatch.setattr(manifest, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        manifest.retire_attempt(row_id, "retire", tmp_path)
    assert wav.read_bytes() == b"wav Aiden" and (tmp_path / "chunks" / row_id / "chunk-001.wav").is_file()
    row = manifest.get(row_id)
    assert row["status"] == "succeeded" and row["attempts"] == [] and core.outputs_intact(row, tmp_path)
    assert not any((tmp_path / "attempts" / row_id).glob("*/presets/*"))  # nothing stranded in the archive


def test_an_incomplete_rollback_is_reported_with_the_files_it_could_not_return(tmp_path, monkeypatch):
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    real, calls = core.os.replace, {"n": 0}

    def flaky(src, dest):
        calls["n"] += 1
        if calls["n"] in (2, 3):  # the second forward move fails, and so does putting the first one back
            raise PermissionError("locked")
        return real(src, dest)

    monkeypatch.setattr(core.os, "replace", flaky)
    with pytest.raises(RuntimeError, match="rollback was incomplete") as caught:
        core._move_all([(first, tmp_path / "moved" / "a.txt"), (second, tmp_path / "moved" / "b.txt")])
    assert "a.txt" in str(caught.value) and isinstance(caught.value.__cause__, PermissionError)


def test_a_file_inside_a_chunk_folder_moves_with_its_folder_not_separately(tmp_path):
    manifest, row_id, _ = _tracked_row(tmp_path)
    inside = tmp_path / "chunks" / row_id / "chunk-001.wav"
    manifest.update(row_id, diagnostic_outputs={"chunk": {"path": f"chunks/{row_id}/chunk-001.wav",
                                                          "bytes": 5, "sha256": core.sha256_file(inside)}})
    manifest.retire_attempt(row_id, "overlap", tmp_path)  # used to try to move the file and then its parent
    attempt = manifest.get(row_id)["attempts"][0]
    assert attempt["diagnostic_outputs"]["chunk"]["path"].startswith(attempt["archive"] + "/chunks/")
    assert (tmp_path / attempt["diagnostic_outputs"]["chunk"]["path"]).read_bytes() == b"chunk"
    assert not (tmp_path / "chunks" / row_id).exists()


def test_a_successful_row_is_committed_with_a_single_save(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    run.manifest.declare(core.short_rows())
    mp3 = run.dir / "presets" / "Aiden.mp3"
    mp3.parent.mkdir(exist_ok=True)
    mp3.write_bytes(b"mp3")
    row = run.manifest.get("qwen-preset-aiden")
    row.update(identity="id", text={"chars": 10})
    row["diagnostic_outputs"] = {"wav": {"path": "presets/Aiden.wav"}}
    monkeypatch.setattr(cli, "final_checks", lambda path, chars: ({"decode_ok": True, "decode_errors": ""}, [], {}))
    saves = []
    real_save = run.manifest.save
    monkeypatch.setattr(run.manifest, "save", lambda: saves.append(1) or real_save())
    tracker = cli.Tracker(run, run.manifest, {"qwen-preset-aiden": row}, lambda t, e: None)
    cli.record_success(tracker, {"row_id": "qwen-preset-aiden"}, outputs={"mp3": {"path": "presets/Aiden.mp3"}},
                       provenance={}, timing={}, warnings=[], extras={})
    assert len(saves) == 1 and run.manifest.get("qwen-preset-aiden")["status"] == "succeeded"
    assert "diagnostic_outputs" not in run.manifest.get("qwen-preset-aiden")  # cleared before that one save


def test_a_late_baseline_failure_still_reports_the_recording_it_already_wrote(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(baseline.core, "measure_samples", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    source = tmp_path / "text.txt"
    source.write_text("one", encoding="utf-8")
    module = fake_engine([tone(1.0)])
    row = {"row_id": "chatterbox-female-1", "voice_id": "chatterbox-female-1", "out_dir": "out", "stem": "Female-1"}
    baseline._run_one(row, tmp_path, source, module, 1, lambda log, mp3: module.chatterbox_file_to_mp3(
        str(source), str(mp3), voice_id="v", log=log), chunk_wrapper=True)
    events = [e for e in (core.parse_event(ln) for ln in capsys.readouterr().out.splitlines()) if e]
    failed = next(e for e in events if e["event"] == "row_failed")
    assert failed["outputs"]["wav"]["path"].endswith("Female-1.wav") and failed["diagnostic"]
    assert (tmp_path / failed["outputs"]["wav"]["path"]).is_file()


def test_the_qwen_worker_reports_the_wav_it_already_wrote_when_a_later_step_fails():
    import ast

    tree = ast.parse((TOOLS / "qwen_eval_worker.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_synth")
    handlers = [h for t in ast.walk(fn) if isinstance(t, ast.Try) for h in t.handlers
                if any(isinstance(c, ast.Constant) and "assembly or output writing failed" in str(c.value)
                       for c in ast.walk(h))]
    assert handlers, "assembly failure handler not found"
    keys = {c.value for h in handlers for c in ast.walk(h) if isinstance(c, ast.Constant)}
    assert "outputs" in keys  # the failure event carries the already-written WAV so a retry archives it


def test_chatterbox_runtime_evidence_uses_the_recorded_version_and_interpreter(monkeypatch):
    monkeypatch.setattr(cli, "torch_runtime_version", lambda: "2.6.0+cpu")
    monkeypatch.setattr(cli, "hub_main_revision", lambda repo, hf_home=None: "rev")
    monkeypatch.setattr(cli, "installed_version", lambda name: "0.1.7" if name == "chatterbox-tts" else None)
    monkeypatch.setattr(cli.platform, "python_version", lambda: "3.12.10")
    info = {"model": {"revision": "rev"}, "package": "chatterbox-tts==0.1.7", "chatterbox_tts": "0.1.7",
            "torch": "2.6.0+cpu", "device": "cpu", "python": "3.12.10"}
    row = {"voice_id": "chatterbox-male-1", "display": "Male-1", "provenance": {
        "worker_engine_info": info, "reference": {"sha256": "r"}}}
    snapshot = {"Male-1": {"sha256": "r"}}
    assert cli.root_runtime_problems(row, engine="chatterbox", snapshot=snapshot) == []
    info["chatterbox_tts"] = "0.1.8"  # the requirement string alone ("==0.1.7") used to hide this
    assert any("chatterbox-tts 0.1.8 -> 0.1.7" in p for p in cli.root_runtime_problems(row, engine="chatterbox",
                                                                                       snapshot=snapshot))
    info["chatterbox_tts"], info["python"] = "0.1.7", "3.11.9"
    assert any("interpreter 3.11.9 -> 3.12.10" in p for p in cli.root_runtime_problems(row, engine="chatterbox",
                                                                                       snapshot=snapshot))
    del info["chatterbox_tts"], info["python"]  # a row from before these were recorded still uses the requirement
    assert cli.root_runtime_problems(row, engine="chatterbox", snapshot=snapshot) == []


def test_frozen_text_cannot_silently_change(tmp_path):
    run = make_run(tmp_path)
    profile = cli.load_profile(run)
    frozen = cli.freeze_corpus(run, profile)
    assert frozen["passages"]["eval_short"]["sha256"] == corpus.EVAL_SHORT.sha256
    assert (run.dir / "corpus" / "short.txt").read_bytes() == corpus.EVAL_SHORT.text.encode("utf-8")
    assert cli.freeze_corpus(run, profile)["frozen"] == frozen["frozen"]  # re-freezing is a no-op
    data = json.loads((run.dir / "corpus" / "frozen.json").read_text(encoding="utf-8"))
    data["passages"]["eval_long"]["sha256"] = "0" * 64
    (run.dir / "corpus" / "frozen.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="no longer matches"):
        cli.freeze_corpus(run, profile)
    with pytest.raises(RuntimeError, match="chunk ceiling"):
        run2 = make_run(tmp_path / "other")
        cli.freeze_corpus(run2, profile)
        cli.freeze_corpus(run2, {**profile, "max_chars": 300})


def test_the_roster_is_the_owners_decision_b_selection():
    assert core.QWEN_ROSTER_PRESETS == ("Aiden", "Ryan")
    assert core.QWEN_ROSTER_CLONES == ("Female-1", "Female-2", "Male-1", "Male-2", "Male-3", "Male-4")
    assert len(core.QWEN_ROSTER_PRESETS) + len(core.QWEN_ROSTER_CLONES) == 8  # the Qwen3 share of the 28 voices
    excluded = {n for n, _ in core.QWEN_PRESETS} - set(core.QWEN_ROSTER_PRESETS)
    assert excluded == {"Dylan", "Eric", "Ono_Anna", "Serena", "Sohee", "Uncle_Fu", "Vivian"}


def test_a_long_selection_may_only_name_roster_voices_once_each():
    ok = core.validate_long_selection
    assert ok(["Aiden", "Ryan"], list(core.QWEN_ROSTER_CLONES)) is None
    assert ok(["Aiden"], []) is None and ok([], ["Male-2"]) is None
    for rejected in ("Dylan", "Eric", "Ono_Anna", "Serena", "Sohee", "Uncle_Fu", "Vivian", "Nobody"):
        assert "not in the owner's roster" in ok(["Aiden", rejected], [])
    assert "not among the six roster clones" in ok(["Aiden"], ["Male-9"])
    assert "twice" in ok(["Aiden", "Aiden"], []) and "twice" in ok([], ["Male-1", "Male-1"])
    assert "names no voices" in ok([], [])
    for malformed in (None, "Aiden", {"a": 1}):
        assert "needs list fields" in ok(malformed, [])
        assert "needs list fields" in ok([], malformed)
    assert "needs list fields" in ok([1], [])


def test_long_stage_refuses_to_run_without_a_valid_recorded_roster_selection(tmp_path):
    run = make_run(tmp_path)
    assert cli.stage_long(run) == 2  # no long-selection.json
    path = run.dir / "long-selection.json"
    for bad in ({"female_preset": "Serena", "clone": "Male-1"},  # the superseded format
                {"presets": ["Aiden", "Dylan"], "clones": []},  # Dylan was rejected
                {"presets": ["Serena"], "clones": []},
                {"presets": ["Aiden"], "clones": ["Male-9"]},
                {"presets": [], "clones": []}):
        path.write_text(json.dumps(bad), encoding="utf-8")
        assert cli.stage_long(run) == 2, bad
    path.write_text(json.dumps({"presets": ["Aiden"], "clones": []}), encoding="utf-8")
    assert cli.stage_long(run, "kokoro") == 2  # sustained recordings exist only for the Qwen groups
    assert not [r for r in run.manifest.rows.values() if r["suite"] == "long"]


def test_a_dry_run_of_the_long_stage_declares_the_roster_rows_in_memory_only(tmp_path):
    run = cli.Run("fresh", work_dir=tmp_path, dry_run=True)
    selection = {"presets": ["Aiden", "Ryan"], "clones": list(core.QWEN_ROSTER_CLONES)}
    path = tmp_path / "runs" / "fresh" / "long-selection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(selection), encoding="utf-8")
    assert cli.stage_long(run, "qwen-preset") == 0
    assert sorted(r for r in run.manifest.rows if r.startswith("long-")) == sorted(
        ["long-qwen-preset-aiden", "long-qwen-preset-ryan",
         *[f"long-qwen-clone-{c.lower()}" for c in core.QWEN_ROSTER_CLONES]])
    assert not (tmp_path / "runs" / "fresh" / "manifest.jsonl").exists()  # nothing persisted


def test_a_long_clone_waits_for_its_approved_transcript_and_its_short_clone_recording(fake_env, monkeypatch):
    run = fake_env
    snapshot = cli.reference_snapshot()
    started = []
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: started.append(a) or 0)
    row = core.long_row(core.GROUP_QWEN_CLONE, "Male-2")
    run.manifest.declare([row, *[r for r in core.short_rows() if r["row_id"] == "qwen-clone-male-2"]])
    args = dict(mode="clone", suite_text="long", profile=cli.load_profile(run), manifest=run.manifest,
                snapshot=snapshot, label="t")
    live = lambda: run.manifest.get(row["row_id"])  # noqa: E731

    cli.run_qwen_group(run, [live()], **args)  # no approved transcript at all
    assert live()["status"] == "blocked" and "transcript not verified" in live()["status_reason"]

    (run.dir / "transcripts" / "verified.json").write_text(json.dumps({"Male-2": {
        "text": "approved words", "approved": True, "wav_sha256": snapshot["Male-2"]["sha256"]}}), encoding="utf-8")
    cli.run_qwen_group(run, [live()], **args)  # approved, but no short clone recording yet
    assert live()["status"] == "blocked" and "short clone recording for Male-2 has not succeeded" in live()["status_reason"]
    assert started == []

    wav = run.dir / "qwen-clones" / "Male-2.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"short clone")
    monkeypatch.setattr(cli, "installed_packages", lambda py: {})
    monkeypatch.setattr(cli, "qwen_runtime_problems", lambda *a, **k: [])
    short_row = run.manifest.get("qwen-clone-male-2")
    run.manifest.update("qwen-clone-male-2", status="succeeded", outputs={"wav": {
        "path": "qwen-clones/Male-2.wav", "bytes": 11, "sha256": core.sha256_file(wav)}},
        identity=cli.current_identity(run, short_row, cli.load_profile(run), snapshot))
    cli.run_qwen_group(run, [live()], **args)  # both prerequisites met and current: the worker starts
    assert len(started) == 1 and live()["status"] == "pending"


def test_a_stale_or_drifted_short_clone_does_not_unlock_its_long_recording(fake_env, monkeypatch):
    run = fake_env
    snapshot = cli.reference_snapshot()
    started = []
    monkeypatch.setattr(cli, "run_worker", lambda *a, **k: started.append(a) or 0)
    monkeypatch.setattr(cli, "installed_packages", lambda py: {})
    verified = run.dir / "transcripts" / "verified.json"
    sha = snapshot["Male-2"]["sha256"]
    verified.write_text(json.dumps({"Male-2": {"text": "the words as first approved", "approved": True,
                                               "wav_sha256": sha}}), encoding="utf-8")
    long_row = core.long_row(core.GROUP_QWEN_CLONE, "Male-2")
    run.manifest.declare([long_row, *[r for r in core.short_rows() if r["row_id"] == "qwen-clone-male-2"]])
    wav = run.dir / "qwen-clones" / "Male-2.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"short clone")
    short = run.manifest.get("qwen-clone-male-2")
    profile = cli.load_profile(run)
    run.manifest.update("qwen-clone-male-2", status="succeeded", outputs={"wav": {
        "path": "qwen-clones/Male-2.wav", "bytes": 11, "sha256": core.sha256_file(wav)}},
        identity=cli.current_identity(run, short, profile, snapshot))
    args = dict(mode="clone", suite_text="long", profile=profile, manifest=run.manifest, snapshot=snapshot, label="t")
    live = lambda: run.manifest.get(long_row["row_id"])  # noqa: E731

    monkeypatch.setattr(cli, "qwen_runtime_problems", lambda *a, **k: ["package torch 2.10 -> 2.11"])
    cli.run_qwen_group(run, [live()], **args)  # the short recording's recorded runtime no longer matches
    assert live()["status"] == "blocked" and "no longer matches its recorded runtime" in live()["status_reason"]
    assert started == []

    monkeypatch.setattr(cli, "qwen_runtime_problems", lambda *a, **k: [])
    verified.write_text(json.dumps({"Male-2": {"text": "the words after a correction", "approved": True,
                                               "wav_sha256": sha}}), encoding="utf-8")
    cli.run_qwen_group(run, [live()], **args)  # the approved transcript changed, so the short clone is stale
    assert live()["status"] == "blocked" and "is stale" in live()["status_reason"] and started == []


def test_female_presets_come_from_the_model_card_wording():
    assert [n for n, _ in core.QWEN_PRESETS if core.is_female_preset(n)] == ["Ono_Anna", "Serena", "Sohee", "Vivian"]
    assert not any(core.is_female_preset(n) for n in ("Aiden", "Dylan", "Eric", "Ryan", "Uncle_Fu", "nobody"))
    assert set(core.QWEN_PRESET_DESCRIPTIONS) == {n for n, _ in core.QWEN_PRESETS}


def test_group_selector_never_widens_beyond_the_requested_group():
    assert cli.selected_groups("kokoro") == [core.GROUP_KOKORO]
    assert cli.selected_groups("qwen") == [core.GROUP_QWEN_PRESET, core.GROUP_QWEN_CLONE]
    assert set(cli.selected_groups("all")) == set(core.GROUPS)


# --------------------------------------------------------------------------- #
# Harness-only PCM capture
# --------------------------------------------------------------------------- #
class FakeEngine:
    calls: list = []

    @staticmethod
    def _export_mp3(arr, sample_rate, output_path, bitrate=None):
        FakeEngine.calls.append((arr.copy(), sample_rate, output_path, bitrate))


def test_pcm_capture_keeps_a_copy_calls_the_original_and_always_restores():
    original = FakeEngine._export_mp3
    FakeEngine.calls.clear()
    data = tone(0.1)
    with baseline.PcmCapture(FakeEngine) as capture:
        FakeEngine._export_mp3(data, SR, "out.mp3", None)
        data[:] = 0  # later mutation must not alter the captured evidence
    assert FakeEngine._export_mp3 is original
    assert len(capture.arrays) == 1 and capture.arrays[0][0].any() and capture.arrays[0][1] == SR
    assert FakeEngine.calls and FakeEngine.calls[0][2] == "out.mp3"
    with pytest.raises(RuntimeError):
        with baseline.PcmCapture(FakeEngine):
            raise RuntimeError("engine failed")
    assert FakeEngine._export_mp3 is original  # restored even on failure


# --------------------------------------------------------------------------- #
# Baseline worker against a fake production engine
# --------------------------------------------------------------------------- #
PARA = "\n\n"


def fake_engine(scripts):
    """A stand-in for chatterbox_synth with production's quirks: an empty colon segment is dropped silently."""
    import types

    from shared.cancellation import ConversionCancelled

    mod = types.ModuleType("fake_chatterbox")
    state = {"i": 0}

    def _generate_checked(model, text, log=print):
        arr = scripts[state["i"]]
        state["i"] += 1
        return arr

    def _synthesize_chunk(model, chunk, cancel_check=None, log=print):
        pieces = [mod._generate_checked(model, seg, log) for seg in chunk.split(": ")]
        pieces = [x for x in pieces if x.size]  # production: `if piece.size == 0: continue`, no log line
        return np.concatenate(pieces) if pieces else np.zeros(0, "float32")

    def _export_mp3(arr, sample_rate, output_path, bitrate=None):
        Path(output_path).write_bytes(b"mp3-bytes")

    def chatterbox_file_to_mp3(source_path, output_mp3_path, voice_id, end_silence_ms=3000, chunk_pause_ms=50,
                               log=print, cancel_check=None, device=None, bitrate=None):
        rendered = []
        for chunk in Path(source_path).read_text(encoding="utf-8").split(PARA):
            if cancel_check is not None and cancel_check():
                raise ConversionCancelled("canceled")
            arr = mod._synthesize_chunk(None, chunk, cancel_check, log=log)
            if arr.size == 0:
                log("  Warning: chunk produced no audio, skipping.")
                continue
            rendered.append(arr)
        gap = np.zeros(int(24000 * chunk_pause_ms / 1000), 'float32')
        pieces = [x for r in rendered for x in (r, gap)]  # production: a pause after every chunk
        pieces.append(np.zeros(int(24000 * end_silence_ms / 1000), 'float32'))
        mod._export_mp3(np.concatenate(pieces), 24000, output_mp3_path)

    for fn in (_generate_checked, _synthesize_chunk, _export_mp3, chatterbox_file_to_mp3):
        setattr(mod, fn.__name__, fn)
    return mod


def run_fake_baseline(tmp_path, capsys, text, scripts, cancel=None):
    module = fake_engine(scripts)
    source = tmp_path / "text.txt"
    source.write_text(text, encoding="utf-8")
    row = {"row_id": "chatterbox-female-1", "voice_id": "chatterbox-female-1", "out_dir": "out", "stem": "Female-1"}
    original = (module._generate_checked, module._synthesize_chunk, module._export_mp3)
    chunks = len(text.split(PARA))
    canceled = baseline._run_one(
        row, tmp_path, source, module, chunks,
        lambda log, mp3: module.chatterbox_file_to_mp3(str(source), str(mp3), voice_id="v", log=log, cancel_check=cancel),
        chunk_wrapper=True)
    assert (module._generate_checked, module._synthesize_chunk, module._export_mp3) == original  # always restored
    events = [e for e in (core.parse_event(ln) for ln in capsys.readouterr().out.splitlines()) if e]
    return canceled, [e for e in events if e["event"] != "log"]


def test_baseline_row_succeeds_only_when_every_planned_chunk_rendered(tmp_path, capsys):
    canceled, events = run_fake_baseline(tmp_path, capsys, "one" + PARA + "two", [tone(2.0), tone(3.0)])
    done = next(e for e in events if e["event"] == "row_done")
    assert canceled is False and done["expected_chunks"] == 2 and len(done["chunk_results"]) == 2
    assert done["audible_s"] == pytest.approx(5.0, abs=0.01)  # engine pauses (2 x 50 ms + 3 s) are excluded
    assert (tmp_path / "out" / "Female-1.wav").is_file() and (tmp_path / "out" / "Female-1.mp3").is_file()


def test_a_silently_dropped_colon_segment_fails_the_row_instead_of_publishing_partial_audio(tmp_path, capsys):
    empty = np.zeros(0, "float32")
    _, events = run_fake_baseline(tmp_path, capsys, "intro: the rest of it", [empty, tone(2.0)])
    assert not any(e["event"] == "row_done" for e in events)
    failed = next(e for e in events if e["event"] == "row_failed")
    assert "silently dropped" in failed["reason"] and failed["diagnostic"] and failed["outputs"]["wav"]["path"]


def test_a_skipped_chunk_fails_the_row_and_keeps_the_partial_audio_as_diagnostics(tmp_path, capsys):
    _, events = run_fake_baseline(tmp_path, capsys, "one" + PARA + "two", [tone(2.0), np.zeros(0, "float32")])
    assert not any(e["event"] == "row_done" for e in events)
    failed = next(e for e in events if e["event"] == "row_failed")
    assert "produced no audio" in failed["reason"] and failed["diagnostic"]


def test_cancellation_stops_a_baseline_row_between_chunks(tmp_path, capsys):
    seen = {"n": 0}

    def cancel():
        seen["n"] += 1
        return seen["n"] > 1  # let the first chunk render, stop before the second

    canceled, events = run_fake_baseline(tmp_path, capsys, PARA.join(["one", "two", "three"]), [tone(1.0)] * 3,
                                         cancel=cancel)
    assert canceled is True
    assert [e["event"] for e in events] == ["row_start", "row_canceled"]
    assert not (tmp_path / "out" / "Female-1.mp3").exists()  # a canceled row publishes nothing


def test_the_cancel_flag_is_the_job_file_and_defaults_to_not_canceled(tmp_path):
    flag = tmp_path / "x.cancel"
    check = baseline._cancel_check({"cancel_file": str(flag)})
    assert check() is False
    flag.write_text("cancel", encoding="utf-8")
    assert check() is True
    assert baseline._cancel_check({})() is False


def test_baseline_rows_fail_closed_when_the_instrumentation_contract_changes(tmp_path, capsys):
    module = fake_engine([tone(1.0)])
    del module._generate_checked  # production renamed a hook: omissions could no longer be observed
    source = tmp_path / "text.txt"
    source.write_text("one", encoding="utf-8")
    row = {"row_id": "chatterbox-female-1", "voice_id": "chatterbox-female-1", "out_dir": "out", "stem": "Female-1"}
    baseline._run_one(row, tmp_path, source, module, 1, lambda log, mp3: module.chatterbox_file_to_mp3(
        str(source), str(mp3), voice_id="v", log=log), chunk_wrapper=True)
    events = [e for e in (core.parse_event(ln) for ln in capsys.readouterr().out.splitlines()) if e]
    failed = next(e for e in events if e["event"] == "row_failed")
    assert "instrumentation contract" in failed["reason"] and not any(e["event"] == "row_done" for e in events)
    assert not (tmp_path / "out" / "Female-1.mp3").exists()  # the engine was never even called


def test_baseline_rows_fail_when_fewer_generations_were_observed_than_chunks_planned(tmp_path, capsys):
    module = fake_engine([tone(1.0), tone(1.0)])
    module._synthesize_chunk = lambda model, chunk, cancel_check=None, log=print: tone(1.0)  # never calls the hook
    source = tmp_path / "text.txt"
    source.write_text("one" + PARA + "two", encoding="utf-8")
    row = {"row_id": "chatterbox-female-1", "voice_id": "chatterbox-female-1", "out_dir": "out", "stem": "Female-1"}
    baseline._run_one(row, tmp_path, source, module, 2, lambda log, mp3: module.chatterbox_file_to_mp3(
        str(source), str(mp3), voice_id="v", log=log), chunk_wrapper=True)
    events = [e for e in (core.parse_event(ln) for ln in capsys.readouterr().out.splitlines()) if e]
    failed = next(e for e in events if e["event"] == "row_failed")
    assert "generations were observed" in failed["reason"] and failed["diagnostic"]


# --------------------------------------------------------------------------- #
# Listening index
# --------------------------------------------------------------------------- #
def test_listening_index_lists_every_row_with_relative_links_and_honest_states():
    rows = core.short_rows()
    for row in rows:
        row["status"] = "blocked" if row["group"] == core.GROUP_QWEN_CLONE else "pending"
        row["status_reason"] = "reference transcript not verified" if row["status"] == "blocked" else ""
    done = next(r for r in rows if r["row_id"] == "kokoro-am_fenrir")
    done.update(status="succeeded", outputs={"wav": {"path": "kokoro/am_fenrir.wav"}, "mp3": {"path": "kokoro/am_fenrir.mp3"}},
                timing={"audible_s": 61.2}, warnings=["audible duration 61.2s outside the 45-90s target"])
    text = cli.render_listening_index(rows, "run-x", None, {"Female-1": "draft awaiting your verification"})
    assert "[WAV](kokoro/am_fenrir.wav)" in text and "[MP3](kokoro/am_fenrir.mp3)" in text
    assert "NEW (retained by owner)" in text and "existing (baseline)" in text
    assert text.count("**blocked**") == 6 and "reference transcript not verified" in text
    for display in ("Aiden", "Ono_Anna", "Uncle_Fu", "Female-2", "Male-4", "bm_daniel"):
        assert display in text
    assert "Mechanical warnings" in text and "Listening rubric" in text
    states = [ln.rsplit("|", 2)[-2].strip().lower() for ln in text.splitlines()
             if ln.startswith("| ") and ("[WAV]" in ln or "**blocked**" in ln or "**pending**" in ln)]
    assert states and all("approved" not in st and "pass" not in st for st in states)  # no recording is called approved
    assert "C:\\" not in text and "/Users/" not in text  # relative paths only


def test_engine_retries_are_surfaced_to_the_listener_not_buried():
    rows = core.short_rows()
    row = next(r for r in rows if r["row_id"] == "chatterbox-male-1")
    row.update(status="succeeded", outputs={"wav": {"path": "c/Male-1.wav"}, "mp3": {"path": "c/Male-1.mp3"}},
               engine_retries=["attempt 1 produced a pathological internal silence", "attempt 2 ..."], warnings=[])
    text = cli.render_listening_index(rows, "run-x", None, {})
    assert "retried 2 generation draw(s)" in text
    assert "needs listening (1 warning(s))" in text
    assert "retried 2" in cli.row_warnings(row)[-1]


def test_manifest_digest_has_one_line_per_row():
    digest = cli.render_manifest_digest(core.short_rows(), "run-x")
    assert digest.count("\n| ") == 27 + 1  # header row + 27 rows


# --------------------------------------------------------------------------- #
# Isolation from the production CLI and from Qwen/torch
# --------------------------------------------------------------------------- #
def test_existing_sample_generator_modes_are_unchanged_by_the_new_flags():
    from tts import generate_voice_samples as gvs

    parser = gvs._build_parser()
    default = parser.parse_args([])
    assert default.qwen_eval is None and default.eval_run == "qwen3-initial" and default.eval_group == "all"
    assert default.patterns == [] and not (default.chatterbox_eval or default.final_acceptance or default.quality_suite
                                           or default.chatterbox_candidates)
    assert parser.parse_args(["--quality-suite", "Jenny"]).patterns == ["Jenny"]
    parsed = parser.parse_args(["--qwen-eval", "short", "--eval-group", "kokoro", "--eval-run", "r1"])
    assert (parsed.qwen_eval, parsed.eval_group, parsed.eval_run) == ("short", "kokoro", "r1")
    with pytest.raises(SystemExit):
        parser.parse_args(["--qwen-eval", "all"])  # there is deliberately no all-in-one stage
    with pytest.raises(SystemExit):
        parser.parse_args(["--eval-group", "edge"])


def test_the_qwen_flag_dispatches_without_touching_voice_selection(monkeypatch):
    from tts import generate_voice_samples as gvs

    seen = {}
    monkeypatch.setattr(gvs, "_run_qwen_eval", lambda a: seen.update(stage=a.qwen_eval, group=a.eval_group) or 0)
    monkeypatch.setattr(sys, "argv", ["generate_voice_samples.py", "--qwen-eval", "report", "--eval-group", "qwen"])
    assert gvs.main() == 0 and seen == {"stage": "report", "group": "qwen"}


def test_dev_tooling_imports_without_qwen_or_torch():
    code = ("import sys; sys.path[:0]=[r'%s', r'%s'];"
            "import qwen_eval_core, qwen_eval_corpus, qwen_eval_assets, qwen_eval_cli, qwen_eval_pilot, "
            "qwen_eval_worker, qwen_eval_baseline_worker;"
            "from tts import generate_voice_samples;"
            "bad=[m for m in ('torch','qwen_tts','transformers','gradio','huggingface_hub','kokoro','chatterbox') if m in sys.modules];"
            "print(bad)") % (TOOLS, REPO_ROOT / "scripts" / "Universal")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "[]"


def test_production_requirements_and_release_packaging_ignore_the_evaluation_tooling():
    import re

    lines = (REPO_ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    names = {re.split(r"[=<>!~\[ ;]", ln.strip())[0].lower().replace("_", "-")
             for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}
    assert not names & {"qwen-tts", "gradio", "openai-whisper", "onnxruntime", "sox", "accelerate"}
    assert "torch" in names and "transformers" in names  # the production stack the evaluation must not disturb
    constraints = (TOOLS / "qwen_eval_constraints.txt").read_text(encoding="utf-8")
    assert "qwen-tts==0.1.1" in constraints and "torch==2.10.0+cu128" in constraints
    assert not (REPO_ROOT / "scripts" / "Universal" / "tts" / "qwen_eval_core.py").exists()


# --------------------------------------------------------------------------- #
# Advisory ASR read-back
# --------------------------------------------------------------------------- #
def test_asr_readback_tolerates_name_variants_but_flags_dropped_spans_and_endings():
    text = corpus.EVAL_SHORT.text
    exact = core.asr_compare(text, text)
    assert exact["coverage"] == 1.0 and not exact["flagged"] and exact["missing_spans"] == []
    heard = (text.replace("Kaerthellin", "Care Helen").replace("Ysolde", "Isald")
             .replace("Thornquill-Vaarwen", "Thornquill Varwen"))
    assert not core.asr_compare(text, heard)["flagged"]  # invented names are not omissions
    words = text.split()
    dropped_middle = " ".join(words[:60] + words[110:])
    result = core.asr_compare(text, dropped_middle)
    assert result["flagged"] and result["coverage"] < core.ASR_MIN_COVERAGE and result["missing_spans"]
    truncated = " ".join(words[:-8])
    assert core.asr_compare(text, truncated)["tail_ok"] is False
    assert core.asr_compare(text, " ".join(words[8:]))["head_ok"] is False
    assert core.asr_compare("", "anything")["coverage"] == 0.0


def test_silence_split_cuts_inside_pauses_never_inside_speech_and_covers_everything():
    rate = 16000
    burst = tone(1.9, 0.3, rate)
    pause = np.zeros(int(0.1 * rate), "float32")
    audio = np.concatenate([np.concatenate([burst, pause]) for _ in range(40)])  # 80 s, a pause every 2 s
    spans = core.silence_split(audio, rate)
    assert spans[0][0] == 0 and spans[-1][1] == audio.size
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))  # contiguous: nothing dropped or repeated
    assert all(b - a <= core.ASR_SEGMENT_S * rate for a, b in spans) and len(spans) >= 3
    for _, cut in spans[:-1]:
        assert abs(audio[max(0, cut - 40): cut + 40]).max() == 0.0, "cut landed inside speech"
    short = np.ones(rate * 5, "float32")
    assert core.silence_split(short, rate) == [(0, short.size)]


def test_the_asr_stage_is_a_separate_explicit_stage_that_never_approves():
    from tts import generate_voice_samples as gvs

    assert "asr-check" in cli.STAGES
    assert gvs._build_parser().parse_args(["--qwen-eval", "asr-check"]).qwen_eval == "asr-check"
    result = core.asr_compare(corpus.EVAL_SHORT.text, corpus.EVAL_SHORT.text)
    assert "approved" not in result and "pass" not in result
