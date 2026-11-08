"""``voice_install.models_status`` on real files -- v0.7.2 Phase 5, ACT72-057 (its models_status half).

The TTS panel asks this one function whether a Kokoro or Chatterbox voice's model files are installed, and every
panel test replaces it with a stand-in, so its own branches had no test. Here it runs unreplaced, through the real
``model_assets.assess``, against real files: the pinned identities are swapped for tiny stand-in files carrying their
own sizes and SHA-256 under a temporary hub folder (the real models are hundreds of megabytes and are never needed to
judge presence). The spaCy English model's state comes from the same version reader the app uses, answered here.

Each state gives exactly one answer and one next step, Install & Continue is offered exactly when installing can help,
and nothing is downloaded, imported or written. These are asset-health checks, not engine qualification.
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest

from tts import model_assets as assets
from tts import voice_install

KOKORO_VOICE = "af_heart"


def _files(folder: Path, names) -> dict[str, tuple[int, str]]:
    """Write a small, distinct stand-in for every pinned name and pin it by its own bytes."""
    pins = {}
    for index, name in enumerate(names):
        data = f"stand-in {index} for {name}\n".encode()
        path = folder.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        pins[name] = (len(data), hashlib.sha256(data).hexdigest())
    return pins


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """Tiny pinned sets under a temporary hub; no network reachable while the status is asked."""
    root = tmp_path / "hub"
    # The cache is vouched for only inside the app's own folder (no link on the way), so that folder is this one.
    monkeypatch.setattr(assets.rt, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(assets, "hf_hub_root", lambda: root)
    monkeypatch.setattr(assets, "record_dir", lambda: tmp_path / "verified")
    kokoro_names = assets.KOKORO_MODEL_NAMES + (assets.kokoro_voice_name(KOKORO_VOICE),)
    kokoro = assets.AssetSet(assets.KOKORO_REPO, assets.KOKORO_REVISION, {})
    chatterbox = assets.AssetSet(assets.CHATTERBOX_REPO, assets.CHATTERBOX_REVISION, {})
    kokoro = assets.AssetSet(kokoro.repo, kokoro.revision, _files(assets.snapshot_dir(kokoro), kokoro_names))
    chatterbox = assets.AssetSet(chatterbox.repo, chatterbox.revision,
                                 _files(assets.snapshot_dir(chatterbox), tuple(assets.CHATTERBOX_FILES)))
    monkeypatch.setattr(assets, "kokoro_set", lambda: kokoro)
    monkeypatch.setattr(assets, "chatterbox_set", lambda: chatterbox)
    versions = {"spacy": "3.8.7", assets.SPACY_ENGLISH: assets.SPACY_ENGLISH_VERSION}
    # The real state function, reading these versions rather than this machine's (its reader is a bound default).
    english_state = assets.spacy_english_state
    monkeypatch.setattr(assets, "spacy_english_state", lambda: english_state(lambda name: versions.get(name)))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("models_status reached for the network"))
    return {"root": root, "kokoro": kokoro, "chatterbox": chatterbox, "versions": versions, "tmp": tmp_path}


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _status(backend: str, voice_id: str) -> tuple[bool, str]:
    return voice_install.models_status(backend, voice_id)


def test_installed_voices_are_ready_and_asking_writes_nothing(hub):
    before = _tree(hub["tmp"])
    assert _status("kokoro", KOKORO_VOICE) == (True, "")
    assert _status("chatterbox", "chatterbox-female-1") == (True, "")
    assert _status("edge", "en-US-AriaNeural") == (True, "") and _status("qwen3", "qwen3-aiden") == (True, "")
    assert _tree(hub["tmp"]) == before, "a status check is read-only"


@pytest.mark.parametrize("damage", ("missing", "wrong-size", "wrong-content"))
@pytest.mark.parametrize("backend", ("kokoro", "chatterbox"))
def test_a_missing_or_damaged_model_file_is_not_installed_and_offers_install_and_continue(hub, damage, backend):
    pinned = hub[backend]
    name = next(iter(pinned.files))
    path = assets.snapshot_dir(pinned).joinpath(*name.split("/"))
    if damage == "missing":
        path.unlink()
    elif damage == "wrong-size":
        path.write_bytes(path.read_bytes() + b"x")
    else:
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])  # same size, other bytes
    voice = KOKORO_VOICE if backend == "kokoro" else "chatterbox-female-1"
    ok, reason = _status(backend, voice)
    assert ok is False and voice_install.NOT_INSTALLED in reason and "Install & Continue" in reason
    assert voice_install.installable(backend, voice, reason) == voice_install.component_for(backend, voice)


def test_a_kokoro_voice_file_of_its_own_is_needed(hub):
    """The Kokoro check covers the selected voice's own file, not only the shared model."""
    voice_file = assets.snapshot_dir(hub["kokoro"]) / "voices" / f"{KOKORO_VOICE}.pt"
    voice_file.unlink()
    ok, reason = _status("kokoro", KOKORO_VOICE)
    assert ok is False and voice_install.NOT_INSTALLED in reason


def test_kokoro_without_its_english_pronunciation_model_says_so_and_offers_the_install(hub):
    del hub["versions"][assets.SPACY_ENGLISH]
    ok, reason = _status("kokoro", KOKORO_VOICE)
    assert ok is False and "pronunciation model" in reason and voice_install.NOT_INSTALLED in reason
    assert voice_install.installable("kokoro", KOKORO_VOICE, reason) == voice_install.component_for("kokoro", KOKORO_VOICE)


@pytest.mark.parametrize("versions, said", (
    ({"spacy": "3.8.7", "en_core_web_sm": "3.7.1"}, "is installed, not the approved"),
    ({"spacy": "3.9.0", "en_core_web_sm": None}, "spaCy is never changed"),
), ids=("another-english-model", "incompatible-spacy"))
def test_a_pronunciation_model_installing_cannot_fix_is_reported_and_not_offered(hub, versions, said):
    hub["versions"].clear()
    hub["versions"].update({key if key != "en_core_web_sm" else assets.SPACY_ENGLISH: value
                            for key, value in versions.items() if value is not None})
    ok, reason = _status("kokoro", KOKORO_VOICE)
    assert ok is False and reason.startswith("Kokoro cannot run here:") and said in reason
    assert voice_install.installable("kokoro", KOKORO_VOICE, reason) is None, "installing would not help"


def test_a_check_that_cannot_run_is_an_answer_not_a_crash(hub, monkeypatch):
    def broken(*_args, **_kwargs):
        raise PermissionError("access is denied")

    monkeypatch.setattr(assets, "assess", broken)
    ok, reason = _status("chatterbox", "chatterbox-female-1")
    assert ok is False and "could not be checked" in reason and "access is denied" in reason
    assert voice_install.installable("chatterbox", "chatterbox-female-1", reason) is None
