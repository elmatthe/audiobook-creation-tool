"""v0.7.0 P03A — the six clone reference recordings live in ``files/Cloned-Voice-Uploads/`` and nowhere else.

Plan Revision 2 §5.3: the six tracked WAVs moved from ``files/Chatterbox-Voice-Uploads/`` by a scoped ``git mv`` (bytes and
basenames unchanged). Resolution is canonical-only: no supported install leaves the recordings at the old path (a fresh
archive and a git checkout both bring them to the new one, and no cache records a reference path), so neither engine
looks there. A missing canonical file is "setup required"; a canonical file with the wrong bytes fails closed — an old
copy beside it is never used to hide either.
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
from tts import qwen3_runtime as rt  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

CANONICAL = ("files", "Cloned-Voice-Uploads")
LEGACY = ("files", "Chatterbox-Voice-Uploads")

#: Plan Revision 2 Appendix A, literally: stable reference id, Chatterbox id, Qwen3 id, basename, content SHA-256.
APPENDIX_A = [
    ("Female-1", "chatterbox-female-1", "qwen3-female-1", "Chatterbox - Female 1.wav",
     "b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4"),
    ("Female-2", "chatterbox-female-2", "qwen3-female-2", "Chatterbox - Female 2.wav",
     "428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205"),
    ("Male-1", "chatterbox-male-1", "qwen3-male-1", "Chatterbox - Male 1.wav",
     "45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58"),
    ("Male-2", "chatterbox-male-2", "qwen3-male-2", "Chatterbox - Male 2.wav",
     "592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355"),
    ("Male-3", "chatterbox-male-3", "qwen3-male-3", "Chatterbox - Male 3.wav",
     "4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80"),
    ("Male-4", "chatterbox-male-4", "qwen3-male-4", "Chatterbox - Male 4.wav",
     "47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad"),
]
IDS = [row[0] for row in APPENDIX_A]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# The real checkout
# --------------------------------------------------------------------------- #
def test_the_registry_names_the_canonical_folder():
    assert vr.REFERENCE_DIRECTORY == CANONICAL


@pytest.mark.parametrize("ref_id, cbx_id, qwen_id, name, sha", APPENDIX_A, ids=IDS)
def test_both_engines_resolve_the_one_canonical_copy_with_the_appendix_a_hash(ref_id, cbx_id, qwen_id, name, sha):
    expected = REPO_ROOT.joinpath(*CANONICAL) / name
    assert cbx.reference_source_path(cbx_id) == expected
    assert rt.reference_path(rt.get_voice(qwen_id)) == expected
    assert vr.REFERENCE_RECORDINGS[ref_id] == name
    assert cbx.REFERENCE_VOICES[cbx_id].source_sha256 == rt.get_voice(qwen_id).reference_sha256 == sha
    assert _sha(expected) == sha


def test_the_canonical_folder_holds_exactly_the_six_wavs():
    folder = REPO_ROOT.joinpath(*CANONICAL)
    assert sorted(p.name for p in folder.glob("*.wav")) == sorted(row[3] for row in APPENDIX_A)


def test_no_reference_wav_remains_at_the_pre_v070_path():
    """The old folder may still hold the owner's ignored MP3 originals; it must hold none of the six WAVs."""
    legacy = REPO_ROOT.joinpath(*LEGACY)
    if legacy.is_dir():
        assert not any((legacy / row[3]).exists() for row in APPENDIX_A)


# --------------------------------------------------------------------------- #
# Canonical-only resolution, on a fake root (negative controls)
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A fake repository root for both engines, with no recordings in it yet."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "files").mkdir()
    monkeypatch.setattr(cbx, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(rt, "repo_root", lambda: tmp_path)
    return tmp_path


def _plant(root: Path, folder: tuple[str, ...], data_for) -> Path:
    target = root.joinpath(*folder)
    target.mkdir(parents=True, exist_ok=True)
    for row in APPENDIX_A:
        (target / row[3]).write_bytes(data_for(row))
    return target


def _real(row) -> bytes:
    return (REPO_ROOT.joinpath(*CANONICAL) / row[3]).read_bytes()


@pytest.mark.parametrize("row", APPENDIX_A, ids=IDS)
def test_a_good_legacy_copy_is_never_used_when_the_canonical_recording_is_missing(fake_root, row):
    _plant(fake_root, LEGACY, _real)
    _ref_id, cbx_id, qwen_id, name, _sha256 = row
    with pytest.raises(cbx.ChatterboxUnavailable, match="Setup required"):
        cbx.resolve_reference(cbx_id)
    ok, reason = cbx.reference_status(cbx_id)
    assert not ok and "not present" in reason
    ok, reason = rt.reference_status(rt.get_voice(qwen_id))
    assert not ok and reason.startswith("Setup required")


@pytest.mark.parametrize("row", APPENDIX_A, ids=IDS)
def test_a_corrupt_canonical_recording_fails_closed_despite_a_good_legacy_copy(fake_root, row):
    _plant(fake_root, LEGACY, _real)
    _plant(fake_root, CANONICAL, lambda r: _real(r)[:-1] + bytes([_real(r)[-1] ^ 0xFF]))
    _ref_id, cbx_id, qwen_id, _name, _sha256 = row
    with pytest.raises(cbx.ChatterboxUnavailable, match="does not match"):
        cbx.resolve_reference(cbx_id)
    ok, reason = rt.reference_status(rt.get_voice(qwen_id))
    assert not ok and "does not match" in reason


@pytest.mark.parametrize("row", APPENDIX_A, ids=IDS)
def test_the_canonical_copy_resolves_and_the_legacy_folder_is_never_opened(fake_root, monkeypatch, row):
    legacy = _plant(fake_root, LEGACY, lambda r: b"stale")
    canonical = _plant(fake_root, CANONICAL, _real)
    before = {p.name: p.read_bytes() for p in legacy.iterdir()}
    opened: list[str] = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    _ref_id, cbx_id, qwen_id, name, _sha256 = row
    assert cbx.resolve_reference(cbx_id) == canonical / name
    assert rt.reference_status(rt.get_voice(qwen_id)) == (True, "ok")
    monkeypatch.setattr(builtins, "open", real_open)
    assert opened and not any("Chatterbox-Voice-Uploads" in path for path in opened)
    assert {p.name: p.read_bytes() for p in legacy.iterdir()} == before


def test_an_arbitrary_extra_upload_is_never_discovered(fake_root):
    folder = _plant(fake_root, CANONICAL, _real)
    (folder / "Chatterbox - Female 1 (copy).wav").write_bytes(_real(APPENDIX_A[0]))
    (folder / "Female-1.mp3").write_bytes(b"mp3")
    assert {cbx.reference_source_path(row[1]).name for row in APPENDIX_A} == {row[3] for row in APPENDIX_A}
    assert {rt.reference_path(rt.get_voice(row[2])).name for row in APPENDIX_A} == {row[3] for row in APPENDIX_A}


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
    """Both engines read ``voice_registry.REFERENCE_DIRECTORY``; the packager keeps its own literal closed allowlist."""
    naming = {p.relative_to(REPO_ROOT).as_posix() for p in application_python_files()
              if any("Cloned-Voice-Uploads" in s for s in _code_strings(p))}
    registry_literal = {p.relative_to(REPO_ROOT).as_posix() for p in application_python_files()
                        if "Cloned-Voice-Uploads" in _code_strings(p)}
    assert naming == {"scripts/shared/release.py", "scripts/tts/voice_registry.py"}
    assert registry_literal == {"scripts/tts/voice_registry.py"}
