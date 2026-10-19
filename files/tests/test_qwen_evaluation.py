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


def test_candidates_are_not_registered_and_existing_voices_are():
    from tts.voice_registry import VOICES

    kokoro = [v.voice_id for v in VOICES if v.backend == "kokoro"]
    for candidate in ("am_fenrir", "am_puck", "am_onyx", "bm_daniel"):
        assert candidate not in kokoro
    assert "am_michael" in kokoro and "bm_george" in kokoro
    chatterbox = [v.voice_id for v in VOICES if v.backend == "chatterbox"]
    assert chatterbox == [voice_id for _, voice_id in core.REFERENCE_VOICE_IDS]
    assert not any("qwen" in v.voice_id.lower() for v in VOICES)


def test_kokoro_inventory_reports_registry_status_without_loading_anything():
    inventory = cli.kokoro_inventory()
    assert [v for v, i in inventory.items() if i["registered"]] == ["am_michael", "bm_george"]
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
    (run.dir / "transcripts" / "verified.json").write_text(json.dumps({
        "Female-1": {"text": "The approved words.", "approved": True},
        "Female-2": {"text": "Draft only.", "approved": False}}), encoding="utf-8")
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
                       profile=cli.load_profile(run), manifest=run.manifest, snapshot=cli.reference_snapshot(),
                       label="t-clone")
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
    cli.run_qwen_group(run, [row], profile={**cli.load_profile(run), "max_chars": 300}, **kw)
    assert calls == [1, 1] and run.manifest.get(rows[0]["row_id"])["attempts"][0]["status"] == "succeeded"


def test_identity_follows_the_pipeline_revision_not_unrelated_source_edits(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    row = next(r for r in core.short_rows() if r["row_id"] == "kokoro-am_michael")
    profile = cli.load_profile(run)
    before = cli.current_identity(run, row, profile, {})
    assert before == cli.current_identity(run, row, profile, {})
    monkeypatch.setattr(core, "PIPELINE_REVISION", core.PIPELINE_REVISION + 1)
    assert cli.current_identity(run, row, profile, {}) != before  # an output-affecting revision makes rows stale


def test_rebase_only_touches_succeeded_intact_rows_and_keeps_the_old_identity(tmp_path):
    run = make_run(tmp_path)
    run.manifest.declare(core.short_rows())
    wav = run.dir / "kokoro" / "am_michael.wav"
    wav.parent.mkdir(exist_ok=True)
    wav.write_bytes(b"x")
    run.manifest.update("kokoro-am_michael", status="succeeded", identity="old", outputs={
        "wav": {"path": "kokoro/am_michael.wav", "bytes": 1, "sha256": core.sha256_file(wav)}})
    run.manifest.update("kokoro-bm_george", status="succeeded", identity="old2", outputs={
        "wav": {"path": "kokoro/missing.wav", "bytes": 1, "sha256": "0" * 64}})
    run.manifest.update("kokoro-am_fenrir", status="failed", identity="old3")
    profile = cli.load_profile(run)
    assert cli.rebase_identities(run, profile, {}, "output-neutral edit") == ["kokoro-am_michael"]
    row = run.manifest.get("kokoro-am_michael")
    assert row["identity"] != "old" and row["identity_history"][0]["identity"] == "old"
    assert row["identity_history"][0]["reason"] == "output-neutral edit"
    assert core.can_resume(row, cli.current_identity(run, row, profile, {}), run.dir)
    assert run.manifest.get("kokoro-bm_george")["identity"] == "old2"  # files missing: never rebased
    assert run.manifest.get("kokoro-am_fenrir")["identity"] == "old3"  # failed: never rebased


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


def test_long_stage_refuses_to_run_without_the_owners_selection(tmp_path):
    run = make_run(tmp_path)
    assert cli.stage_long(run) == 2
    (run.dir / "long-selection.json").write_text(json.dumps({"female_preset": "Aiden", "clone": "Male-1"}), encoding="utf-8")
    assert cli.stage_long(run) == 2  # Aiden is already required; a female preset must be a different voice
    (run.dir / "long-selection.json").write_text(json.dumps({"female_preset": "Serena", "clone": "Nobody"}), encoding="utf-8")
    assert cli.stage_long(run) == 2
    (run.dir / "long-selection.json").write_text(json.dumps({"female_preset": "Ryan", "clone": "Male-1"}), encoding="utf-8")
    assert cli.stage_long(run) == 2  # Ryan is a male preset per the model card
    (run.dir / "long-selection.json").write_text(json.dumps({"female_preset": "Serena", "clone": "Male-1"}), encoding="utf-8")
    assert cli.stage_long(run) == 2  # valid names, but Male-1's transcript is not owner-approved
    assert not [r for r in run.manifest.rows.values() if r["suite"] == "long"]


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
    assert "NEW candidate" in text and "existing (baseline)" in text
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
