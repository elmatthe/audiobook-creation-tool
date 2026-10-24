"""v0.7.0 P03C — the six clone transcripts shipped with the app, and the loader that trusts only them.

Owner ruling Q8 (plan Revision 2 §5.3): the six owner-approved texts ship as ``scripts/tts/data/bundled_clone_transcripts.json``
with exactly ``schema_version``, ``bundle_revision`` and six entries of ``reference_id``, ``voice_id``, ``wav_sha256``,
``text`` and ``text_sha256``. Normal narration uses that verified bundle only: a local store or ``ACT_QWEN3_TRANSCRIPTS``
never shadows it, a damaged bundle is trusted in no part, and a changed recording blocks only its own clone.

The committed file is checked against the owner's approval (2026-10-24: review file SHA-256 48f5dbef…c236, whose six text
digests are pinned below). Every damaged-bundle case uses a synthetic copy in ``tmp_path``.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tts import qwen3_runtime as rt
from tts import voice_registry

from test_qwen3_runtime import install_environment, install_model, sandbox  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_REL = "scripts/tts/data/bundled_clone_transcripts.json"
#: The UTF-8 SHA-256 of each text the owner approved (P03B validation, approved 2026-10-24 by artifact hash). Any change
#: to a shipped text must come with a new owner approval and a new pin here.
APPROVED_TEXT_SHA256 = {
    "Female-1": "74b8174dc59272c09e70e4c3f5404eeb16a5552adde8e91333c23a97d616c09c",
    "Female-2": "dd7cbd39f94e746b2554cb48710ea0afa8e75eb17514989e33d2c327125680b8",
    "Male-1": "5afea1f7de940a148339dc84e69965348a16f8a28a8c5c054522b0c25eae3f59",
    "Male-2": "3589fb60ebd9d2f6d4e15e981a2700be3994fabfbf3e1677c6d86f57eb2a887d",
    "Male-3": "7be44794203b1952805a11d35d36fa65b1deccc9dd7c29a405ca5a9a376996ce",
    "Male-4": "a66dcfeae9e9df2a3da66b5967725073b1ada28b9d2fb02309458f6517ed7a0d",
}
CLONES = [v for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE]
PRESETS = [v for v in rt.QWEN3_VOICES if v.kind != rt.KIND_CLONE]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def shipped() -> dict:
    return json.loads((REPO_ROOT / BUNDLE_REL).read_bytes().decode("utf-8"))


def synthetic_doc(texts: dict[str, str] | None = None) -> dict:
    """A valid bundle for the CURRENT runtime table (so a test that patches a recording hash gets a matching bundle)."""
    texts = texts or {v.reference_name: f"Synthetic words for {v.reference_name}." for v in CLONES}
    return {"schema_version": 1, "bundle_revision": 1,
            "entries": [{"reference_id": v.reference_name, "voice_id": v.voice_id,
                         "wav_sha256": rt.get_voice(v.voice_id).reference_sha256, "text": texts[v.reference_name],
                         "text_sha256": _sha(texts[v.reference_name].encode("utf-8"))} for v in CLONES]}


@pytest.fixture
def bundle_file(tmp_path, monkeypatch):
    """Point the runtime at a synthetic bundle; returns a writer (dict or raw bytes)."""
    path = tmp_path / "bundle" / "bundled_clone_transcripts.json"
    path.parent.mkdir()
    monkeypatch.setattr(rt, "bundled_transcripts_path", lambda: path)

    def write(doc=None) -> Path:
        path.write_bytes(doc if isinstance(doc, bytes) else json.dumps(doc or synthetic_doc()).encode("utf-8"))
        return path

    return write


# --------------------------------------------------------------------------- #
# A. The committed bundle is exactly what the owner approved
# --------------------------------------------------------------------------- #
def test_the_bundle_is_tracked_not_ignored_and_where_the_runtime_reads_it():
    assert rt.bundled_transcripts_path() == REPO_ROOT / BUNDLE_REL
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", BUNDLE_REL], cwd=REPO_ROOT, capture_output=True)
    assert tracked.returncode == 0, "the bundle must be committed to ship"
    assert subprocess.run(["git", "check-ignore", "-q", BUNDLE_REL], cwd=REPO_ROOT).returncode == 1


def test_the_bundle_has_exactly_the_approved_fields_and_six_registry_entries():
    doc = shipped()
    assert list(doc) == ["schema_version", "bundle_revision", "entries"]
    assert doc["schema_version"] == rt.BUNDLE_SCHEMA_VERSION == 1 and doc["bundle_revision"] == 1
    assert [e["reference_id"] for e in doc["entries"]] == [v.reference_name for v in CLONES]
    for entry, voice in zip(doc["entries"], CLONES):
        assert list(entry) == ["reference_id", "voice_id", "wav_sha256", "text", "text_sha256"]
        assert entry["voice_id"] == voice.voice_id
        assert entry["wav_sha256"] == voice.reference_sha256  # the registered recording (Appendix A)


def test_each_shipped_text_is_the_owner_approved_text():
    for entry in shipped()["entries"]:
        digest = _sha(entry["text"].encode("utf-8"))
        assert entry["text_sha256"] == digest == APPROVED_TEXT_SHA256[entry["reference_id"]], entry["reference_id"]
    male4 = next(e for e in shipped()["entries"] if e["reference_id"] == "Male-4")
    assert male4["text"].startswith("Hello Arthur.")


def test_the_bundle_bytes_are_plain_utf8_lf_and_carry_no_private_record():
    raw = (REPO_ROOT / BUNDLE_REL).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"}\n")
    text = raw.decode("utf-8")
    for private in ("approved", "approved_by", "approved_on", "review_status", "original_text", "manifest_tag",
                    "source_store", "notice", "drafted_on", "UNAPPROVED", "runtime-data", "dev-work"):
        assert private not in text, private
    assert not re.search(r"[A-Za-z]:\\\\|/Users/|/home/|\\\\Users\\\\", text), "a local path in the bundle"


def test_the_runtime_returns_each_shipped_text_exactly():
    texts = rt.load_bundle()
    assert texts == {e["reference_id"]: e["text"] for e in shipped()["entries"]}
    for voice in CLONES:
        result = rt.load_transcript(voice.voice_id)
        assert result.ok and result.text == texts[voice.reference_name] and result.source == REPO_ROOT / BUNDLE_REL
    for voice in PRESETS:
        assert rt.load_transcript(voice.voice_id) == rt.Transcript(True, "", "not needed")
    assert rt.bundle_status() == (True, "ok")


def test_the_bundle_text_is_never_stripped_or_normalised(bundle_file):
    texts = {v.reference_name: f"Café  “{v.reference_name}”." for v in CLONES}
    bundle_file(synthetic_doc(texts))
    assert rt.load_transcript("qwen3-female-2").text == texts["Female-2"]


# --------------------------------------------------------------------------- #
# B. A damaged bundle is trusted in no part
# --------------------------------------------------------------------------- #
def _mutate(mutate):
    doc = synthetic_doc()
    mutate(doc)
    return doc


DAMAGED = [
    (lambda d: d.update(extra="x"), "unexpected top-level fields"),
    (lambda d: d.pop("bundle_revision"), "unexpected top-level fields"),
    (lambda d: d.update(schema_version=2), "unknown schema version"),
    (lambda d: d.update(schema_version="1"), "unknown schema version"),
    (lambda d: d.update(schema_version=True), "unknown schema version"),
    (lambda d: d.update(bundle_revision=0), "invalid bundle revision"),
    (lambda d: d.update(bundle_revision="1"), "invalid bundle revision"),
    (lambda d: d.update(bundle_revision=True), "invalid bundle revision"),
    (lambda d: d.update(bundle_revision=1.0), "invalid bundle revision"),
    (lambda d: d.update(entries={}), "exactly 6 entries"),
    (lambda d: d["entries"].pop(), "exactly 6 entries"),
    (lambda d: d["entries"].append(dict(d["entries"][0])), "exactly 6 entries"),
    (lambda d: d["entries"].__setitem__(5, dict(d["entries"][0])), "two entries for Female-1"),
    (lambda d: d["entries"][2].update(reference_id="Male-9"), "unknown recording"),
    (lambda d: d["entries"][0].update(approved=True), "unexpected fields"),
    (lambda d: d["entries"][0].pop("text_sha256"), "unexpected fields"),
    (lambda d: d["entries"].__setitem__(0, ["not", "an", "entry"]), "unexpected fields"),
    (lambda d: d["entries"][1].update(text=None), "not text"),
    (lambda d: d["entries"][1].update(wav_sha256=7), "not text"),
    (lambda d: d["entries"][3].update(voice_id="qwen3-male-1"), "wrong voice for Male-2"),
    (lambda d: d["entries"][3].update(wav_sha256="0" * 64), "Male-2 is bound to a different recording"),
]


def _text_case(text: str) -> dict:
    doc = synthetic_doc()
    doc["entries"][4].update(text=text, text_sha256=_sha(text.encode("utf-8")))
    return doc


TEXT_CASES = [
    ("   ", "a blank transcript for Male-3"),
    ("x" * (rt.MAX_TRANSCRIPT_CHARS + 1), "an implausibly long transcript"),
    (" Leading space.", "leading or trailing spaces"),
    ("Trailing newline.\n", "leading or trailing spaces"),
    ("A tab\there.", "control characters"),
    ("A C1 control\x85here.", "control characters"),
]


@pytest.mark.parametrize("mutate,why", DAMAGED)
def test_a_bundle_that_is_not_exactly_the_approved_shape_blocks_all_six_clones(bundle_file, mutate, why):
    bundle_file(_mutate(mutate))
    _assert_all_clones_refused(why)


@pytest.mark.parametrize("text,why", TEXT_CASES)
def test_an_unusable_text_blocks_all_six_clones(bundle_file, text, why):
    bundle_file(_text_case(text))
    _assert_all_clones_refused(why)


def test_a_text_that_no_longer_matches_its_digest_is_refused(bundle_file):
    doc = synthetic_doc()
    doc["entries"][0]["text"] += " One extra word."  # edited, digest left stale
    bundle_file(doc)
    _assert_all_clones_refused("the transcript for Female-1 fails its checksum")
    doc = synthetic_doc()
    doc["entries"][0]["text_sha256"] = doc["entries"][0]["text_sha256"].upper()  # same value, not the canonical form
    bundle_file(doc)
    _assert_all_clones_refused("fails its checksum")


@pytest.mark.parametrize("raw,why", [
    (b"\xef\xbb\xbf" + json.dumps(synthetic_doc()).encode(), "byte-order mark"),
    (b"{not json", "not valid JSON"),
    (b"\xff\xfe\x00", "not valid JSON"),
    (b"[]", "unexpected top-level fields"),
    (b'{"schema_version": 1, "schema_version": 1, "bundle_revision": 1, "entries": []}', "a repeated field"),
    (json.dumps(synthetic_doc()).replace('"voice_id"', '"voice_id": "x", "voice_id"', 1).encode(), "a repeated field"),
])
def test_a_bundle_that_is_not_clean_json_is_refused(bundle_file, raw, why):
    bundle_file(raw)
    _assert_all_clones_refused(why)


def test_a_missing_or_oversized_bundle_is_refused(bundle_file):
    path = bundle_file()
    path.unlink()
    _assert_all_clones_refused("the reference transcripts shipped with the app are missing")
    path.write_bytes(b" " * (rt.BUNDLE_MAX_BYTES + 1))
    _assert_all_clones_refused("too large")
    path.unlink()
    path.mkdir()
    _assert_all_clones_refused("missing")


def _assert_all_clones_refused(why: str) -> None:
    for voice in CLONES:
        result = rt.load_transcript(voice.voice_id)
        assert not result.ok and result.text == "" and why in result.reason, (voice.voice_id, result.reason)
        assert result.reason.startswith("the reference transcripts shipped with the app")
    ok, reason = rt.bundle_status()
    assert not ok and why in reason
    for voice in PRESETS:
        assert rt.load_transcript(voice.voice_id).ok  # a preset never needs a transcript


# --------------------------------------------------------------------------- #
# C. Normal mode: the bundle is the only authority
# --------------------------------------------------------------------------- #
def _write_store(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({v.reference_name: {"text": text, "approved": True, "wav_sha256": v.reference_sha256}
                                for v in CLONES}), encoding="utf-8")


def test_a_local_store_and_the_environment_override_never_shadow_the_bundle(sandbox, monkeypatch, tmp_path):  # noqa: F811
    _write_store(rt.local_transcripts_path(), "stale local words")
    ambient = tmp_path / "ambient" / "transcripts.json"
    _write_store(ambient, "ambient override words")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(ambient))
    texts = {e["reference_id"]: e["text"] for e in shipped()["entries"]}
    for voice in CLONES:
        assert rt.load_transcript(voice.voice_id).text == texts[voice.reference_name]
    # ... and normal resolution never even asks where a local store is.
    monkeypatch.setattr(rt, "local_transcripts_path", lambda: (_ for _ in ()).throw(AssertionError("local read")))
    monkeypatch.setattr(rt, "local_store_path", lambda: (_ for _ in ()).throw(AssertionError("local read")))
    assert all(rt.load_transcript(v.voice_id).ok for v in CLONES)


def test_a_malformed_local_store_is_irrelevant(sandbox, monkeypatch):  # noqa: F811
    store = rt.local_transcripts_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{definitely not json", encoding="utf-8")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(store))
    assert all(rt.load_transcript(v.voice_id).ok for v in CLONES)


def test_a_damaged_bundle_never_falls_back_to_a_valid_local_store(sandbox, bundle_file, monkeypatch):  # noqa: F811
    _write_store(rt.local_transcripts_path(), "valid local words")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(rt.local_transcripts_path()))
    bundle_file(_mutate(lambda d: d["entries"].pop()))
    _assert_all_clones_refused("exactly 6 entries")


def test_an_explicit_override_is_the_only_way_to_read_a_local_store(sandbox, monkeypatch, developer_mode):  # noqa: F811
    """Developer mode (v0.7.0 P03D); in normal mode the same call is refused (``test_developer_mode``)."""
    store = rt.local_transcripts_path()
    _write_store(store, "maintainer words")
    voice = CLONES[0]
    assert rt.load_transcript(voice.voice_id, override=store).text == "maintainer words"
    assert rt.load_transcript(voice.voice_id).text != "maintainer words"
    missing = rt.load_transcript(voice.voice_id, override=store.with_name("absent.json"))
    assert not missing.ok and "chosen file" in missing.reason  # an explicit choice never falls through to the bundle


# --------------------------------------------------------------------------- #
# D. Zero touch: a fresh install with the Base model has six ready clones
# --------------------------------------------------------------------------- #
@pytest.fixture
def fresh_base_install(sandbox):  # noqa: F811
    """Empty runtime data, the engine and the Base model, and the six real recordings at the canonical path."""
    install_environment(sandbox)
    install_model(sandbox, "base")
    refs = sandbox.joinpath(*voice_registry.REFERENCE_DIRECTORY)
    refs.mkdir(parents=True)
    for voice in CLONES:
        shutil.copyfile(REPO_ROOT.joinpath(*voice_registry.REFERENCE_DIRECTORY) / rt.reference_path(voice).name,
                        refs / rt.reference_path(voice).name)
    return sandbox


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_a_fresh_install_has_six_ready_clones_without_approval_recognizer_or_writes(fresh_base_install, monkeypatch):
    assert not rt.local_transcripts_path().exists()
    monkeypatch.setattr(rt, "transcriber_status", lambda: (_ for _ in ()).throw(AssertionError("recognizer needed")))
    before = _tree(fresh_base_install)
    for voice in CLONES:
        assert rt.voice_availability(voice.voice_id) == (True, "ok"), voice.voice_id
    assert _tree(fresh_base_install) == before, "checking availability wrote something"
    assert not rt.local_transcripts_path().exists()


def test_a_changed_recording_blocks_only_its_own_clone(fresh_base_install):
    victim = rt.get_voice("qwen3-male-3")
    rt.reference_path(victim).write_bytes(b"a different recording")
    for voice in CLONES:
        ok, reason = rt.voice_availability(voice.voice_id)
        if voice.voice_id == victim.voice_id:
            assert not ok and "does not match" in reason
        else:
            assert ok, (voice.voice_id, reason)


def test_a_damaged_bundle_makes_the_clones_unavailable_with_repair_guidance(fresh_base_install, bundle_file):
    bundle_file(_mutate(lambda d: d["entries"][2].update(text_sha256="0" * 64)))
    for voice in CLONES:
        ok, reason = rt.voice_availability(voice.voice_id)
        assert not ok and f"Setup required for {voice.label}" in reason and "fails its checksum" in reason
        assert "Extract a fresh copy of the app" in reason and "Set up cloned voices" not in reason
    install_model(fresh_base_install, "customvoice")
    assert all(rt.voice_availability(v.voice_id) == (True, "ok") for v in PRESETS)
