"""v0.8.0 Phase 2 correction -- the 18 engine-specific clone references and their transcripts (owner decision 2026-11-13).

Every cloned engine has its own six recordings: Qwen3 the original v0.7.x files (renamed only, bytes unchanged, its
transcripts still the unchanged bundle), Chatterbox and OmniVoice the owner's new recordings with owner-written
transcripts. ``tts/data/clone_references.json`` lists all 18 and ``tts/clone_references.load`` refuses the whole list on
any problem. The owner's texts are written out literally below (from the owner's document, never derived from the code
under test or from a speech recognizer). Nothing here loads a model or writes a recording.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from pathlib import Path

import pytest

from tts import chatterbox_synth as cbx
from tts import clone_references as cr
from tts import omnivoice_runtime as ov
from tts import qwen3_runtime as rt
from tts import voice_registry as vr

pytestmark = pytest.mark.usefixtures("production_writes_refused")

REPO = Path(__file__).resolve().parents[2]

#: The owner's own words, verbatim from "Cloned-Voice-Transcripts-Personally-written-and-owner-approved.md" (2026-11-13).
OWNER_TEXTS = {
    "chatterbox-female-1": ("It had already been several weeks since I'd gone to town. After we came home, Tanya and the "
                            "rest of the servants were quite cross with me, but the trip had been incredibly beneficial."),
    "chatterbox-female-2": ("His direct superior, the Lord Chancellor Marquess Joric Reclentos, and his new subordinate, "
                            "Count Hughes Rudelberg, stood to the side of the dance floor chatting amicably."),
    "chatterbox-male-1": ("Zeth, Sun Sun, Balano, truthless of Shinovar, sat atop the highest tower in the world and "
                          "contemplated the end of all things."),
    "chatterbox-male-2": ("This was the Worm's Whiskers, a forest that separated the kingdom of Asura's northern border "
                          "from the valley known as the Red Worm's Upper Jaw."),
    "chatterbox-male-3": "Klein didn't stand on ceremony and said directly, I wish to borrow the magic wishing lamp for a day.",
    "chatterbox-male-4": ("The voice drifted to me through a haze, distant and ethereal but familiar. I was drowsing, "
                          "nestled deep within a cozy blanket of thoughtless fatigue."),
    "omnivoice-female-1": ("It had already been several weeks since I'd gone to town. After we came home, Tanya and the "
                           "rest of the servants were quite cross with me."),
    "omnivoice-female-2": "Vice Chancellor Cloud Legan Barth, his direct superior, the Lord Chancellor Marquess Joric Reclentos",
    "omnivoice-male-1": ("Zeth, Sun Sun, Balano, truthless of Shinovar, sat atop the highest tower in the world and "
                         "contemplated the end of all things."),
    "omnivoice-male-2": ("This was the Worm's Whiskers, a forest that separated the kingdom of Asura's northern border "
                         "from the valley known as the Red Worm's Upper Jaw."),
    "omnivoice-male-3": "Klein didn't stand on ceremony and said directly, I wish to borrow the magic wishing lamp for a day.",
    "omnivoice-male-4": "The voice drifted to me through a haze, distant and ethereal but familiar.",
}
#: The shipped Qwen3 transcript bundle, byte for byte, as released (v0.7.0 P03C .. v0.8.0 Phase 2 d5d1c6c).
BUNDLE_FILE_SHA256 = "dd9535236ca2d09012ffdc1946de78115176dc95902da47e9ae7cdbb51cd7429"
#: The six original recordings (plan Revision 2 Appendix A): now Qwen3's alone.
QWEN3_ORIGINALS = {
    "qwen3-female-1": "b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4",
    "qwen3-female-2": "428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205",
    "qwen3-male-1": "45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58",
    "qwen3-male-2": "592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355",
    "qwen3-male-3": "4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80",
    "qwen3-male-4": "47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad",
}
#: The 12 new recordings, by the SHA-256 of the owner's supplied files (Cloned-Voice-Uploads.zip, 2026-11-13).
OWNER_RECORDINGS = {
    "chatterbox-female-1": "994b700eb4fa65fff22da7af6c69517afa637921a79e356b43ef414f2b096374",
    "chatterbox-female-2": "a1a6530fb06d8199a25e18224218c2d893b3c9a17f6c20738058a4da7947466e",
    "chatterbox-male-1": "8f1999ded53fefd80a5659cd75ac6d016a0cfbd6031e79dcface454c7b1d875c",
    "chatterbox-male-2": "d8939ad19dc90718efb2fb27251a5aa665c3cc76efa2ed161e6cac739400f69c",
    "chatterbox-male-3": "152b8aa13fbf23d5ce73beee1ba348009f9b7b01b6fc838b0ea94ea834f22b8b",
    "chatterbox-male-4": "9eb5722dee8fc186bcccdfef5b837160a8658374ac3d74106bb969184a96ca42",
    "omnivoice-female-1": "438329e6c39917b55a6833b0a1244c7375bf17a61580c3dc07b6098743d13249",
    "omnivoice-female-2": "909a0ea7935385792075771291fd1aa922c22e3a0756fb6210f0b69830141861",
    "omnivoice-male-1": "7753385380675913f0b97c5a03ca6d63702dec13c4905d7f014dc45ef7b1ccf7",
    "omnivoice-male-2": "0b2918438b877bbe35ff38d590adca2af00e213219588bbc39ad5505f4c5b678",
    "omnivoice-male-3": "5dc34276f15cb42b9a3a04dc67c6bc1fba1f3511c979c0ea81bc6751aa885b89",
    "omnivoice-male-4": "31d7305ce0257a56599607e575679763c49ce3ecd5541d81c6e6b877002d1d3d",
}
ENGINE = {"chatterbox": "Chatterbox", "omnivoice": "OmniVoice", "qwen3": "Qwen3"}


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def real_path(asset: cr.ReferenceAsset) -> Path:
    return REPO.joinpath(*asset.parts)


# --------------------------------------------------------------------------- #
# The list against the real files and the registry
# --------------------------------------------------------------------------- #
def test_the_list_covers_exactly_the_18_registered_clones_each_in_its_own_engine_folder():
    assets = cr.load()
    assert set(assets) == set(vr.VOICE_REFERENCES) and len(assets) == 18
    for (backend, voice_id), asset in assets.items():
        voice = voice_id.split("-", 1)[1].replace("-", " ").title()
        assert asset.file == f"{ENGINE[backend]}/{ENGINE[backend]} - {voice}.wav"
        assert asset.parts == vr.reference_recording_parts(backend, voice_id)
        assert asset.reference_id == vr.reference_id(backend, voice_id)
    assert len({a.wav_sha256 for a in assets.values()}) == 18, "18 distinct recordings, none shared between engines"


@pytest.mark.parametrize("key", sorted(vr.VOICE_REFERENCES), ids=lambda k: k[1])
def test_each_entry_is_the_real_file_byte_for_byte(key):
    asset = cr.load()[key]
    path = real_path(asset)
    with wave.open(str(path), "rb") as w:
        assert (w.getcomptype(), w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (
            "NONE", asset.sample_rate, asset.channels, asset.sample_width_bytes, asset.frames)
    assert sha_file(path) == asset.wav_sha256 == {**QWEN3_ORIGINALS, **OWNER_RECORDINGS}[key[1]]


def test_qwen3_keeps_the_six_original_recordings_and_its_unchanged_transcript_bundle():
    assets = cr.load()
    assert rt.bundled_transcripts_path().read_bytes() and sha_file(rt.bundled_transcripts_path()) == BUNDLE_FILE_SHA256
    bundle = json.loads(rt.bundled_transcripts_path().read_text(encoding="utf-8"))
    for voice in (v for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE):
        asset = assets[("qwen3", voice.voice_id)]
        assert asset.wav_sha256 == voice.reference_sha256 == QWEN3_ORIGINALS[voice.voice_id]
        assert asset.text is None and asset.text_sha256 is None, "Qwen3's texts stay in the bundle, not duplicated here"
        assert (asset.sample_rate, asset.frames) == (24000, 360000)
        entry = next(e for e in bundle["entries"] if e["voice_id"] == voice.voice_id)
        assert entry["wav_sha256"] == voice.reference_sha256 and entry["reference_id"] == voice.reference_name
        assert rt.reference_status(voice) == (True, "ok")
    assert set(rt.load_bundle()) == {"Female-1", "Female-2", "Male-1", "Male-2", "Male-3", "Male-4"}


def test_the_qwen3_originals_were_moved_by_git_not_rewritten():
    """In the index, each Qwen3 file is the very blob the shared v0.7 recording was (content-addressed, same bytes)."""
    names = {f"files/Cloned-Voice-Uploads/Qwen3/Qwen3 - {v}.wav": v for v in
             ("Female 1", "Female 2", "Male 1", "Male 2", "Male 3", "Male 4")}
    blobs = subprocess.run(["git", "ls-files", "-s", "--", *names], cwd=REPO, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    assert len(blobs) == 6
    for line in blobs:
        blob, path = line.split()[1], line.split("\t", 1)[1]
        data = subprocess.run(["git", "cat-file", "blob", blob], cwd=REPO, capture_output=True, check=True).stdout
        voice_id = "qwen3-" + names[path].lower().replace(" ", "-")
        assert hashlib.sha256(data).hexdigest() == QWEN3_ORIGINALS[voice_id]


@pytest.mark.parametrize("voice_id", sorted(OWNER_TEXTS))
def test_chatterbox_and_omnivoice_carry_the_owner_written_transcript_of_their_own_recording(voice_id):
    backend = voice_id.split("-", 1)[0]
    asset = cr.load()[(backend, voice_id)]
    assert asset.text == OWNER_TEXTS[voice_id]
    assert asset.text_sha256 == hashlib.sha256(OWNER_TEXTS[voice_id].encode("utf-8")).hexdigest()
    assert asset.wav_sha256 == OWNER_RECORDINGS[voice_id] and (asset.sample_rate, asset.channels) == (44100, 1)
    if backend == "chatterbox":
        assert cbx.REFERENCE_VOICES[voice_id].source_sha256 == asset.wav_sha256
        assert cbx.reference_status(voice_id) == (True, "ok")
    else:
        voice = ov.get_voice(voice_id)
        assert (voice.reference_sha256, voice.text_sha256) == (asset.wav_sha256, asset.text_sha256)


def test_the_two_female_2_recordings_open_differently_and_so_do_their_transcripts():
    """The owner's Chatterbox Female 2 starts at "His direct superior"; OmniVoice's at "Vice Chancellor"."""
    assert OWNER_TEXTS["chatterbox-female-2"].startswith("His direct superior")
    assert OWNER_TEXTS["omnivoice-female-2"].startswith("Vice Chancellor")
    assert not OWNER_TEXTS["omnivoice-female-2"].startswith(rt.load_bundle()["Female-2"]), "no prefix rule any more"


def test_chatterbox_is_never_given_a_transcript():
    """Chatterbox Turbo conditions on audio only: its owner texts are checked metadata and its engine never reads them."""
    import ast

    source = Path(cbx.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(isinstance(n, ast.Name) and n.id == "clone_references" for n in ast.walk(tree))
    assert "ref_text" not in source and "clone_references.json" in source  # documented, never loaded


# --------------------------------------------------------------------------- #
# A damaged or mismatched list is refused whole
# --------------------------------------------------------------------------- #
def edited(tmp_path: Path, change) -> Path:
    data = json.loads(cr.manifest_path().read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "clone_references.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def entry(data: dict, voice_id: str) -> dict:
    return next(e for e in data["entries"] if e["voice_id"] == voice_id)


def _set(target: str, **fields):
    return lambda data: entry(data, target).update(fields)


def _swap_hashes(a: str, b: str):
    def change(data):
        ea, eb = entry(data, a), entry(data, b)
        ea["wav_sha256"], eb["wav_sha256"] = eb["wav_sha256"], ea["wav_sha256"]
    return change


@pytest.mark.parametrize("change, message", [
    (_set("omnivoice-male-4", text="The voice drifted to me through a haze."), "checksum"),
    (_set("chatterbox-female-2", text=""), "blank"),
    (_set("qwen3-male-2", text="Three carriages rattled down a narrow road."), "own transcript bundle"),
    (_set("omnivoice-female-1", file="Chatterbox/Chatterbox - Female 1.wav"), "not the registry's"),
    (_set("omnivoice-female-1", file="OmniVoice - Female 1.wav"), "not the registry's"),
    (_set("chatterbox-male-3", reference_id="Male-4"), "clones it from Male-3"),
    (_set("chatterbox-male-3", voice_id="chatterbox-male-9"), "not a registered cloned voice"),
    (_set("qwen3-female-1", channels=2), "16-bit mono"),
    (_set("qwen3-female-1", wav_sha256="Z" * 64), "not a SHA-256"),
    (_set("omnivoice-male-2", frames="391826"), "wrong type"),
    (_set("omnivoice-male-1", wav_sha256=OWNER_RECORDINGS["chatterbox-male-1"]), "same recording bytes"),
    (lambda data: data["entries"].pop(), "exactly 18"),
    (lambda data: data["entries"].append(dict(data["entries"][0])), "exactly 18"),
    (lambda data: data.update(schema_version=2), "schema version 1"),
    (lambda data: data["entries"][3].update(extra=1), "unexpected fields"),
])
def test_a_damaged_list_is_refused_whole(tmp_path, change, message):
    with pytest.raises(cr.ReferenceManifestError, match=message):
        cr.load(edited(tmp_path, change))


def test_the_shipped_list_and_its_omnivoice_view_load_cleanly():
    assert len(cr.load()) == 18 and set(ov.load_references()) == {v.voice_id for v in ov.OMNIVOICE_VOICES}


@pytest.mark.parametrize("change, message", [
    # an edited transcript with a matching checksum still is not the owner's approved text for that recording
    (lambda data: entry(data, "omnivoice-male-4").update(
        text="The voice drifted to me through a haze.",
        text_sha256=hashlib.sha256(b"The voice drifted to me through a haze.").hexdigest()), "owner-approved"),
    # two voices' transcripts exchanged, each with its own checksum
    (lambda data: (lambda a, b: (a.update(text=b["text"], text_sha256=b["text_sha256"]),
                                 b.update(text=OWNER_TEXTS["omnivoice-female-1"],
                                          text_sha256=hashlib.sha256(OWNER_TEXTS["omnivoice-female-1"].encode()).hexdigest())))(
        entry(data, "omnivoice-female-1"), entry(data, "omnivoice-female-2")), "owner-approved"),
    # two voices' recordings exchanged
    (_swap_hashes("omnivoice-male-2", "omnivoice-male-3"), "different recording"),
])
def test_omnivoice_refuses_a_transcript_or_recording_that_is_not_the_approved_pair(tmp_path, change, message):
    path = edited(tmp_path, change)
    cr.load(path)  # a well-formed list...
    with pytest.raises(ov.ReferenceAssetError, match=message):
        ov.load_references(path)  # ...that is not what OmniVoice was approved with
