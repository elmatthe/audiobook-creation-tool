"""The clone reference recordings live in ``files/Cloned-Voice-Uploads/<Engine>/`` and nowhere else.

v0.7.0 P03A moved the six shared WAVs here from ``files/Chatterbox-Voice-Uploads/``. v0.8.0 (owner decision 2026-11-13)
gave every cloned engine its own six recordings in its own folder, named for the engine: the six original recordings
became Qwen3's alone (a scoped ``git mv``; bytes and hashes unchanged), and Chatterbox and OmniVoice got the owner's new
recordings. Resolution is canonical-only: no engine looks in the pre-v0.7.0 folder, at a loose file in the reference
folder's root, or in another engine's folder. A missing canonical file is "setup required"; a canonical file with the
wrong bytes fails closed -- a good copy elsewhere is never used to hide either.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from source_probe import application_python_files  # noqa: E402
from tts import chatterbox_synth as cbx  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

CANONICAL = ("files", "Cloned-Voice-Uploads")
LEGACY = ("files", "Chatterbox-Voice-Uploads")
VOICES = ("Female 1", "Female 2", "Male 1", "Male 2", "Male 3", "Male 4")

#: Written out literally (recomputed from the files, never copied from the code under test): engine folder, voice,
#: content SHA-256. Qwen3's six are plan Revision 2 Appendix A -- the ORIGINAL recordings, unchanged.
HASHES = {
    "Qwen3": ("b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4",
              "428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205",
              "45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58",
              "592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355",
              "4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80",
              "47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad"),
    "Chatterbox": ("994b700eb4fa65fff22da7af6c69517afa637921a79e356b43ef414f2b096374",
                   "a1a6530fb06d8199a25e18224218c2d893b3c9a17f6c20738058a4da7947466e",
                   "8f1999ded53fefd80a5659cd75ac6d016a0cfbd6031e79dcface454c7b1d875c",
                   "d8939ad19dc90718efb2fb27251a5aa665c3cc76efa2ed161e6cac739400f69c",
                   "152b8aa13fbf23d5ce73beee1ba348009f9b7b01b6fc838b0ea94ea834f22b8b",
                   "9eb5722dee8fc186bcccdfef5b837160a8658374ac3d74106bb969184a96ca42"),
    "OmniVoice": ("438329e6c39917b55a6833b0a1244c7375bf17a61580c3dc07b6098743d13249",
                  "909a0ea7935385792075771291fd1aa922c22e3a0756fb6210f0b69830141861",
                  "7753385380675913f0b97c5a03ca6d63702dec13c4905d7f014dc45ef7b1ccf7",
                  "0b2918438b877bbe35ff38d590adca2af00e213219588bbc39ad5505f4c5b678",
                  "5dc34276f15cb42b9a3a04dc67c6bc1fba1f3511c979c0ea81bc6751aa885b89",
                  "31d7305ce0257a56599607e575679763c49ce3ecd5541d81c6e6b877002d1d3d"),
}
BACKEND_OF = {"Chatterbox": "chatterbox", "OmniVoice": "omnivoice", "Qwen3": "qwen3"}
#: (engine folder, voice id, basename, sha) for all 18.
ROWS = [(folder, f"{BACKEND_OF[folder]}-{voice.lower().replace(' ', '-')}", f"{folder} - {voice}.wav", HASHES[folder][i])
        for folder in ("Chatterbox", "OmniVoice", "Qwen3") for i, voice in enumerate(VOICES)]
IDS = [row[1] for row in ROWS]
SUFFIXES = [v.lower().replace(" ", "-") for v in VOICES]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(folder: str, voice_id: str) -> Path:
    """Where the engine itself says this voice's recording is."""
    if folder == "Chatterbox":
        return cbx.reference_source_path(voice_id)
    if folder == "Qwen3":
        return rt.reference_path(rt.get_voice(voice_id))
    return ov.reference_path(ov.get_voice(voice_id))


def status(folder: str, voice_id: str) -> tuple[bool, str]:
    if folder == "Chatterbox":
        return cbx.reference_status(voice_id)
    if folder == "Qwen3":
        return rt.reference_status(rt.get_voice(voice_id))
    return ov.reference_status(ov.get_voice(voice_id))


# --------------------------------------------------------------------------- #
# The real checkout
# --------------------------------------------------------------------------- #
def test_the_registry_names_the_canonical_folder_and_one_folder_per_cloned_engine():
    assert vr.REFERENCE_DIRECTORY == CANONICAL
    assert vr.REFERENCE_FOLDERS == {"chatterbox": "Chatterbox", "omnivoice": "OmniVoice", "qwen3": "Qwen3"}


@pytest.mark.parametrize("folder, voice_id, name, sha", ROWS, ids=IDS)
def test_each_engine_resolves_its_own_canonical_recording_with_the_approved_hash(folder, voice_id, name, sha):
    expected = REPO_ROOT.joinpath(*CANONICAL, folder, name)
    assert resolve(folder, voice_id) == expected
    assert vr.reference_recording_parts(BACKEND_OF[folder], voice_id) == (*CANONICAL, folder, name)
    assert _sha(expected) == sha
    assert status(folder, voice_id) == (True, "ok")


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_no_two_engines_share_a_recording(suffix):
    """The Chatterbox, Qwen3 and OmniVoice clones of one speaker read three different files with three hashes."""
    paths = {resolve(folder, f"{BACKEND_OF[folder]}-{suffix}") for folder in ("Chatterbox", "OmniVoice", "Qwen3")}
    assert len(paths) == 3 and len({_sha(p) for p in paths}) == 3
    assert cbx.REFERENCE_VOICES[f"chatterbox-{suffix}"].source_sha256 != rt.get_voice(f"qwen3-{suffix}").reference_sha256


def test_the_canonical_folder_holds_exactly_the_three_engine_folders_and_the_18_wavs():
    root = REPO_ROOT.joinpath(*CANONICAL)
    assert sorted(p.name for p in root.iterdir()) == ["Chatterbox", "OmniVoice", "Qwen3"], "nothing loose at the root"
    found = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.wav"))
    assert found == sorted(f"{folder}/{name}" for folder, _v, name, _s in ROWS)
    assert len({_sha(root / f) for f in found}) == 18


def test_no_reference_wav_remains_at_the_pre_v070_path_or_the_old_shared_names():
    """The old folder may still hold the owner's ignored MP3 originals; it must hold none of the WAVs."""
    legacy = REPO_ROOT.joinpath(*LEGACY)
    if legacy.is_dir():
        assert not any((legacy / row[2]).exists() for row in ROWS)
    root = REPO_ROOT.joinpath(*CANONICAL)
    assert not any((root / f"Chatterbox - {voice}.wav").exists() for voice in VOICES), "the shared v0.7 names are gone"


# --------------------------------------------------------------------------- #
# Canonical-only resolution, on a fake root (negative controls)
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A fake repository root for all three engines, with no recordings in it yet."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "files").mkdir()
    monkeypatch.setattr(cbx, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(rt, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(ov, "repo_root", lambda: tmp_path)
    return tmp_path


def _real(row) -> bytes:
    return REPO_ROOT.joinpath(*CANONICAL, row[0], row[2]).read_bytes()


def _plant(root: Path, where, data_for) -> None:
    """Write every row's file at ``where(row)`` (a tuple of parts under *root*)."""
    for row in ROWS:
        target = root.joinpath(*where(row))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data_for(row))


def canonical(row):
    return (*CANONICAL, row[0], row[2])


def legacy(row):
    return (*LEGACY, row[2])


def loose(row):
    """At the reference folder's root, as the v0.7 shared copies were."""
    return (*CANONICAL, row[2])


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_a_good_copy_elsewhere_is_never_used_when_the_canonical_recording_is_missing(fake_root, row):
    _plant(fake_root, legacy, _real)
    _plant(fake_root, loose, _real)
    folder, voice_id, _name, _sha256 = row
    ok, reason = status(folder, voice_id)
    assert not ok and ("not present" in reason or reason.startswith("Setup required"))
    if folder == "Chatterbox":
        with pytest.raises(cbx.ChatterboxUnavailable, match="Setup required"):
            cbx.resolve_reference(voice_id)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_a_corrupt_canonical_recording_fails_closed_despite_good_copies_elsewhere(fake_root, row):
    _plant(fake_root, legacy, _real)
    _plant(fake_root, loose, _real)
    _plant(fake_root, canonical, lambda r: _real(r)[:-1] + bytes([_real(r)[-1] ^ 0xFF]))
    folder, voice_id, _name, _sha256 = row
    ok, reason = status(folder, voice_id)
    assert not ok and "does not match" in reason
    if folder == "Chatterbox":
        with pytest.raises(cbx.ChatterboxUnavailable, match="does not match"):
            cbx.resolve_reference(voice_id)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_another_engines_recording_is_never_accepted_in_place_of_its_own(fake_root, row):
    """Planting the same speaker's OTHER engine file under this engine's name fails closed (hash), never clones it."""
    folder, voice_id, name, _sha256 = row
    suffix = voice_id.split("-", 1)[1]
    other = next(r for r in ROWS if r[0] != folder and r[1].endswith(suffix))
    _plant(fake_root, canonical, _real)
    fake_root.joinpath(*CANONICAL, folder, name).write_bytes(_real(other))
    ok, reason = status(folder, voice_id)
    assert not ok and "does not match" in reason


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_the_canonical_copy_resolves_and_no_other_location_is_opened(fake_root, monkeypatch, row):
    _plant(fake_root, legacy, lambda r: b"stale")
    _plant(fake_root, loose, lambda r: b"stale")
    _plant(fake_root, canonical, _real)
    opened: list[str] = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    folder, voice_id, name, _sha256 = row
    assert resolve(folder, voice_id) == fake_root.joinpath(*CANONICAL, folder, name)
    assert status(folder, voice_id) == (True, "ok")
    monkeypatch.setattr(builtins, "open", real_open)
    recordings = [p for p in opened if p.endswith(".wav")]
    assert recordings and all(Path(p) == fake_root.joinpath(*CANONICAL, folder, name) for p in recordings)


def test_an_arbitrary_extra_upload_is_never_discovered(fake_root):
    _plant(fake_root, canonical, _real)
    root = fake_root.joinpath(*CANONICAL)
    (root / "Chatterbox" / "Chatterbox - Female 1 (copy).wav").write_bytes(_real(ROWS[0]))
    (root / "Qwen3" / "Female-1.mp3").write_bytes(b"mp3")
    (root / "Extra.wav").write_bytes(b"x")
    for folder in ("Chatterbox", "OmniVoice", "Qwen3"):
        names = {resolve(folder, row[1]).name for row in ROWS if row[0] == folder}
        assert names == {row[2] for row in ROWS if row[0] == folder}


# --------------------------------------------------------------------------- #
# One authority in the application source (AST, not substrings)
# --------------------------------------------------------------------------- #
def _docstring_nodes(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _code_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_nodes(tree)
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs]


def test_no_application_code_names_the_pre_v070_folder():
    offenders = [p.relative_to(REPO_ROOT).as_posix() for p in application_python_files()
                 if any("Chatterbox-Voice-Uploads" in s for s in _code_strings(p))]
    assert offenders == []


def test_only_the_registry_and_the_packager_name_the_canonical_folder():
    """Every engine reads ``voice_registry``'s tables; the packager keeps its own literal closed allowlist."""
    naming = {p.relative_to(REPO_ROOT).as_posix() for p in application_python_files()
              if any("Cloned-Voice-Uploads" in s for s in _code_strings(p))}
    registry_literal = {p.relative_to(REPO_ROOT).as_posix() for p in application_python_files()
                        if "Cloned-Voice-Uploads" in _code_strings(p)}
    assert naming == {"scripts/shared/release.py", "scripts/tts/voice_registry.py"}
    assert registry_literal == {"scripts/tts/voice_registry.py"}
