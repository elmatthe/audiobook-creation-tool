"""model_assets.py — the exact upstream files the Kokoro and Chatterbox Turbo voices may use, and their verified copies.

v0.7.0 P05B Stage 2 (plan Revision 2 §5.4). One table of pinned identities, read by three callers that must agree:

* the optional-setup planner (what is ready, missing or damaged on this computer),
* the consented acquirer (what it may fetch, from where, and what a fetched file must be), and
* inference (``kokoro_synth`` / ``chatterbox_synth``), which loads **only** these verified local files and refuses
  -- rather than letting an upstream library download something nobody agreed to -- when one is missing or wrong.

Each Hugging Face file is pinned by repository, **commit** (never a moving branch such as ``main``), size and SHA-256.
LFS files carry their SHA-256 upstream; the few small non-LFS files are pinned upstream by git blob SHA-1, and their
SHA-256 was derived from cached copies whose git blob SHA-1 was rechecked against those pins (P05B Stage 2 evidence,
``derived-sha256.txt``). The files live in the in-tree Hugging Face cache layout, in the folder of the pinned commit.

A copy is verified by hashing it. After a consented acquisition hashed every file, a small record of what was proved
(``files/runtime-data/models/verified/``) lets later checks trust an unchanged file (same size and modification time)
without hashing gigabytes again; only the acquirer writes it. Planning and inference never write anything.

The approved spaCy English model (owner ruling, 2026-10-25) is pinned here too: one official wheel, by URL, size and
SHA-256, installable only into a compatible spaCy, never through ``spacy.cli.download``.

Standard library only (plus ``shared.venv_layout`` and ``tts.qwen3_runtime`` for the repository root): it is imported
by the pre-venv estimate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from shared import venv_layout
from tts import qwen3_runtime as rt

READY = "ready"
MISSING = "missing"
DAMAGED = "damaged"
UNVERIFIED = "unverified"


class AssetsUnavailable(Exception):
    """A model file inference needs is not here as approved. Never a ``RuntimeError``/``OSError``: it says nothing
    about whether the engine's packages work, so nothing that handles those (a retry, forgetting a dependency proof)
    may catch it. Nothing was downloaded."""


@dataclass(frozen=True)
class AssetSet:
    """Files of one Hugging Face repository at one commit: ``{relative name: (size, sha256)}``."""

    repo: str
    revision: str
    files: Mapping[str, tuple[int, str]]

    def size(self, names: Iterable[str]) -> int:
        return sum(self.files[name][0] for name in names)


# --------------------------------------------------------------------------- #
# The pinned identities
# --------------------------------------------------------------------------- #
#: hexgrad/Kokoro-82M at the commit measured in P05B Stage 1 (its ``main`` on 2026-10-25). ``kokoro`` 0.9.4 would fetch
#: these from ``main``; the app loads them from this commit's folder only.
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_MODEL_NAMES = ("config.json", "kokoro-v1_0.pth")
KOKORO_FILES: dict[str, tuple[int, str]] = {
    "config.json": (2_351, "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"),
    "kokoro-v1_0.pth": (327_212_226, "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"),
    "voices/af_bella.pt": (523_425, "8cb64e02fcc8de0327a8e13817e49c76c945ecf0052ceac97d3081480e8e48d6"),
    "voices/af_heart.pt": (523_425, "0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff"),
    "voices/am_fenrir.pt": (523_430, "98e507eca1db08230ae3b6232d59c10aec9630022d19accac4f5d12fcec3c37a"),
    "voices/am_michael.pt": (523_435, "9a443b79a4b22489a5b0ab7c651a0bcd1a30bef675c28333f06971abbd47bd37"),
    "voices/am_onyx.pt": (523_420, "e8452be16cd0f6da7b4579eaf7b1e4506e92524882053d86d72b96b9a7fed584"),
    "voices/am_puck.pt": (523_420, "dd1d8973f4ce4b7d8ae407c77a435f485dabc052081b80ea75c4f30b84f36223"),
    "voices/bf_emma.pt": (523_420, "d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701"),
    "voices/bm_daniel.pt": (523_430, "fc3fce4e9c12ed4dbc8fa9680cfe51ee190a96444ce7c3ad647549a30823fc5d"),
    "voices/bm_george.pt": (523_430, "f1bc812213dc59774769e5c80004b13eeb79bd78130b11b2d7f934542dab811b"),
}

#: ResembleAI/chatterbox-turbo at the commit measured in P05B Stage 1. Exactly the nine files
#: ``ChatterboxTurboTTS.from_local`` reads. ``s3gen.safetensors`` (1,056,484,620 B, SHA-256 2b78103c…1d4e) is in the
#: repository and ``from_pretrained``'s patterns would fetch it, but Turbo never loads it, so it is not acquired.
CHATTERBOX_REPO = "ResembleAI/chatterbox-turbo"
CHATTERBOX_REVISION = "749d1c1a46eb10492095d68fbcf55691ccf137cd"
CHATTERBOX_FILES: dict[str, tuple[int, str]] = {
    "added_tokens.json": (418, "72e4ab6acb0d9309ac3df4b526ae5fd80a2da5bc5ab7bb02d85096a374f69193"),
    "conds.pt": (169_454, "b1852099306fd6a7814eb9d0bd10186caba7249596cc23868f78a0eefbfa5033"),
    "merges.txt": (456_318, "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5"),
    "s3gen_meanflow.safetensors": (1_064_875_036, "d65cb687a2ed581ee6cc297e919ffefa63386944f42364ae13b78a594945514f"),
    "special_tokens_map.json": (470, "92ba8063bf40aa163eadebbfe0de07c2aebe44cf0d4a9e8726580b0781fd2640"),
    "t3_turbo_v1.safetensors": (1_915_480_052, "fcf1f8c1d651bb7e3acd69ee5be269b4ac10c02980b7708213d598bc9f7cdf87"),
    "tokenizer_config.json": (3_878, "bca16a2ac1ddbd78b8d6228f0031884cc74b6ea54b967d6f6d2ebae9ccde23e6"),
    "ve.safetensors": (5_695_784, "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c"),
    "vocab.json": (999_186, "f6bd25a65e4e63ca31360e9fb11c7e4f9a391a78385d640acd814092dd6eee4f"),
}

#: The owner-approved spaCy English model (ruling 2026-10-25): this wheel only, size- and hash-verified before pip sees
#: it, installed with ``--no-deps`` and hash enforcement into a spaCy ``>=3.8.0,<3.9.0`` that is never upgraded for it.
SPACY_ENGLISH = "en_core_web_sm"
SPACY_ENGLISH_VERSION = "3.8.0"
SPACY_WHEEL_NAME = "en_core_web_sm-3.8.0-py3-none-any.whl"
SPACY_WHEEL_URL = ("https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/"
                   + SPACY_WHEEL_NAME)
SPACY_WHEEL_SIZE = 12_806_118
SPACY_WHEEL_SHA256 = "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
SPACY_COMPATIBLE = ((3, 8, 0), (3, 9, 0))  # >= first, < second


def kokoro_set() -> AssetSet:
    return AssetSet(KOKORO_REPO, KOKORO_REVISION, KOKORO_FILES)


def chatterbox_set() -> AssetSet:
    return AssetSet(CHATTERBOX_REPO, CHATTERBOX_REVISION, CHATTERBOX_FILES)


def kokoro_voice_name(voice_id: str) -> str:
    return f"voices/{voice_id}.pt"


def spacy_source() -> str:
    """The spaCy wheel as a plan source: its URL and the SHA-256 that is its real identity (a release asset's URL can
    be re-pointed; its hash cannot)."""
    return f"wheel:{SPACY_WHEEL_URL}#sha256:{SPACY_WHEEL_SHA256}"


# --------------------------------------------------------------------------- #
# Where the copies live
# --------------------------------------------------------------------------- #
def hf_hub_root() -> Path:
    """The in-tree Hugging Face cache the app always points Kokoro and Chatterbox at (``bootstrap._configure_hf_cache``)."""
    return rt.repo_root() / "files" / "runtime-data" / "models" / "huggingface" / "hub"


def snapshot_dir(assets: AssetSet) -> Path:
    """The folder of the pinned commit -- never the one a ``refs/main`` happens to name."""
    return hf_hub_root() / ("models--" + assets.repo.replace("/", "--")) / "snapshots" / assets.revision


def record_dir() -> Path:
    return rt.repo_root() / "files" / "runtime-data" / "models" / "verified"


def record_path(assets: AssetSet) -> Path:
    return record_dir() / f"{assets.repo.replace('/', '--')}@{assets.revision}.json"


def link_problem(path: Path) -> str:
    """Why *path* cannot be vouched for (a link or junction between the repository and it), or ``""``."""
    unsafe = venv_layout.unsafe_component(rt.repo_root(), path)
    if unsafe is None:
        return ""
    return f"the model cache is reached through a link ({unsafe.name}), so its contents cannot be vouched for"


# --------------------------------------------------------------------------- #
# Verifying copies
# --------------------------------------------------------------------------- #
#: SHA-256 already computed in this process, by (path, size, mtime_ns): a plan made before and after an acquisition,
#: or a second load, does not hash the same unchanged gigabytes twice.
_HASHED: dict[tuple[str, int, int], str] = {}


def _sha256(path: Path, size: int, mtime_ns: int) -> str:
    key = (os.path.normcase(os.path.abspath(path)), size, mtime_ns)
    digest = _HASHED.get(key)
    if digest is None:
        digest = rt.sha256_file(path)
        _HASHED[key] = digest
    return digest


def _record(assets: AssetSet) -> dict:
    """The proved-good files of the record for *assets*, or ``{}`` (absent, unreadable, a link, another revision)."""
    path = record_path(assets)
    if link_problem(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("repo") != assets.repo or data.get("revision") != assets.revision:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def file_state(assets: AssetSet, name: str, *, record: Optional[dict] = None) -> tuple[str, str]:
    """``(state, detail)`` for one pinned file: ready (exactly the approved bytes), missing, damaged (another size or
    content), or unverified (reached through a link, or unreadable)."""
    size, sha256 = assets.files[name]
    folder = snapshot_dir(assets)
    path = folder.joinpath(*name.split("/"))
    problem = link_problem(path)
    if problem:
        return UNVERIFIED, problem
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return MISSING, f"{name} is not on this computer"
    except OSError as exc:
        return UNVERIFIED, f"{name} cannot be read ({exc.strerror or exc})"
    if not os.path.isfile(path):
        return DAMAGED, f"{name} is not a file"
    if info.st_size != size:
        return DAMAGED, f"{name} has {info.st_size} bytes, not the approved {size}"
    proved = (record or {}).get(name)
    if isinstance(proved, dict) and proved.get("sha256") == sha256 and proved.get("size") == size \
            and proved.get("mtime_ns") == info.st_mtime_ns:
        return READY, ""
    try:
        actual = _sha256(path, info.st_size, info.st_mtime_ns)
    except OSError as exc:
        return UNVERIFIED, f"{name} cannot be read ({exc.strerror or exc})"
    if actual != sha256:
        return DAMAGED, f"{name} is not the approved file (its SHA-256 differs)"
    return READY, ""


def assess(assets: AssetSet, names: Iterable[str]) -> dict[str, tuple[str, str]]:
    """``{name: (state, detail)}`` for *names*. Read-only."""
    record = _record(assets)
    return {name: file_state(assets, name, record=record) for name in names}


def record_verified(assets: AssetSet, names: Iterable[str]) -> None:
    """Hash *names* afresh from disk and record the ones that are exactly the approved bytes. Only the consented
    acquirer calls this; the record is a cache of proof, never a substitute for it (a changed file is hashed again)."""
    folder = snapshot_dir(assets)
    entries = dict(_record(assets))
    for name in names:
        size, sha256 = assets.files[name]
        path = folder.joinpath(*name.split("/"))
        if link_problem(path):
            entries.pop(name, None)
            continue
        info = os.stat(path)
        if info.st_size == size and rt.sha256_file(path) == sha256:
            _HASHED[(os.path.normcase(os.path.abspath(path)), info.st_size, info.st_mtime_ns)] = sha256
            entries[name] = {"size": size, "sha256": sha256, "mtime_ns": info.st_mtime_ns}
        else:
            entries.pop(name, None)
    target = record_path(assets)
    target.parent.mkdir(parents=True, exist_ok=True)
    problem = link_problem(target)
    if problem:
        raise OSError(problem)
    temporary = target.with_name(target.name + ".tmp")
    rt.remove_entry(temporary)
    temporary.write_text(json.dumps({"repo": assets.repo, "revision": assets.revision, "files": entries},
                                    indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)


def require(assets: AssetSet, names: Iterable[str], what: str) -> dict[str, Path]:
    """The verified local path of every name, or :class:`AssetsUnavailable` naming what is wrong. Never downloads."""
    names = tuple(names)
    states = assess(assets, names)
    wrong = [(name, state, detail) for name, (state, detail) in states.items() if state != READY]
    if wrong:
        name, state, detail = wrong[0]
        more = f" (and {len(wrong) - 1} more)" if len(wrong) > 1 else ""
        raise AssetsUnavailable(
            f"{what} cannot be used: {detail}{more}. Nothing was downloaded. Install or repair it from the optional "
            "voice setup (it asks before downloading anything).")
    folder = snapshot_dir(assets)
    return {name: folder.joinpath(*name.split("/")) for name in names}


# --------------------------------------------------------------------------- #
# What inference may load
# --------------------------------------------------------------------------- #
def kokoro_model_paths() -> tuple[Path, Path]:
    """``(config.json, weights)`` of the pinned Kokoro model, verified."""
    paths = require(kokoro_set(), KOKORO_MODEL_NAMES, "The Kokoro model")
    return paths["config.json"], paths["kokoro-v1_0.pth"]


def kokoro_voice_path(voice_id: str) -> Path:
    """The verified ``.pt`` of one Kokoro roster voice. A voice with no pinned file is refused, not fetched."""
    name = kokoro_voice_name(voice_id)
    if name not in KOKORO_FILES:
        raise AssetsUnavailable(f"The Kokoro voice {voice_id!r} is not one of the app's approved voices, so it is not "
                                "downloaded or used. Nothing was downloaded.")
    return require(kokoro_set(), (name,), f"The Kokoro voice {voice_id}")[name]


def chatterbox_model_dir() -> Path:
    """The verified Chatterbox Turbo folder (every file ``from_local`` reads)."""
    require(chatterbox_set(), CHATTERBOX_FILES, "The Chatterbox Turbo model")
    return snapshot_dir(chatterbox_set())


# --------------------------------------------------------------------------- #
# The spaCy English model
# --------------------------------------------------------------------------- #
def installed_version(distribution: str) -> Optional[str]:
    """The installed version of *distribution* in this interpreter's environment, or ``None``. Reads metadata only."""
    import importlib
    import importlib.metadata

    importlib.invalidate_caches()  # a package installed a moment ago by this process's own pip must be seen
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def parse_version(text: Optional[str]) -> Optional[tuple[int, int, int]]:
    """``"3.8.16"`` -> ``(3, 8, 16)``; anything else (a pre-release, a local build, garbage) -> ``None``."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def spacy_problem(version_of: Callable[[str], Optional[str]] = installed_version) -> str:
    """Why the approved English model cannot be installed into this environment's spaCy, or ``""``."""
    text = version_of("spacy")
    version = parse_version(text)
    low, high = SPACY_COMPATIBLE
    if text is None:
        return "spaCy is not installed in the app's environment"
    if version is None or not low <= version < high:
        return (f"the app's spaCy is {text}; the approved English model needs spaCy >=3.8.0,<3.9.0, and spaCy is never "
                "changed to make it fit")
    return ""


def spacy_english_state(version_of: Callable[[str], Optional[str]] = installed_version) -> tuple[str, str]:
    """``(state, detail)`` of the English model: ready (the approved version, in a compatible spaCy), missing
    (installable), or unverified (another version is installed, or spaCy is incompatible -- never changed for it)."""
    installed = version_of(SPACY_ENGLISH)
    problem = spacy_problem(version_of)
    if installed is None:
        return (UNVERIFIED, problem) if problem else (MISSING, "the spaCy English model is not installed")
    if installed != SPACY_ENGLISH_VERSION:
        return UNVERIFIED, (f"spaCy English model {installed} is installed, not the approved {SPACY_ENGLISH_VERSION}; it "
                            "is not replaced automatically")
    return (UNVERIFIED, problem) if problem else (READY, "")


def require_spacy_english(version_of: Optional[Callable[[str], Optional[str]]] = None) -> None:
    """Refuse before misaki's English G2P is built if it would run ``spacy.cli.download`` -- an unpinned pip install
    that misaki starts exactly when the model is absent. An installed model of another version is used as before
    (misaki would not download then); the planner still reports it unverified rather than approved."""
    if (version_of or installed_version)(SPACY_ENGLISH) is None:
        raise AssetsUnavailable("Kokoro's English pronunciation model (spaCy en_core_web_sm) is not installed. Nothing "
                                "was downloaded. Install it from the optional voice setup (it asks first).")
