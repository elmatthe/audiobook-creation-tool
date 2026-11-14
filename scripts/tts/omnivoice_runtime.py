"""omnivoice_runtime.py — what the six OmniVoice voices need on this computer, and whether it is there.

OmniVoice 0.2.1 needs ``transformers>=5.3.0``, which neither the app's ``.venv`` nor the Qwen3 engine can hold, so it runs
in its own independent environment inside a supervised worker process (``omnivoice_worker.py``); ``omnivoice_synth.py``
is the application-side half. This module only *asks questions*: where things live, whether they are present and
intact, and what a person should be told when they are not. It imports nothing heavy (no numpy, torch or OmniVoice),
never downloads, and never raises for a missing asset -- a missing asset is a status with a sentence fit for a
non-technical user.

**Where the environment is (owner decision 2026-11-13, unified ``.venv`` layout; it supersedes the sibling of plan
section 4).** One place only: ``.venv/engines/omnivoice`` (:func:`venv_dir`), an environment of its own -- its own
interpreter, built directly from the app's base Python, never from the parent's -- held inside the app's ``.venv``
beside Qwen3's, and protected through the parent's repairs by the same mechanism (``shared.venv_layout``,
``shared.engine_lease``). Nothing is ever installed into or run from anywhere else. The earlier sibling
``.venv-omnivoice`` (:func:`legacy_venv_dir`) is only *recognised* (:func:`assess_legacy`): it is never a runtime
target, never adopted and never moved to the new path -- a Windows environment cannot be relocated -- so the engine is
built again at the nested path from the pinned wheels, proved, and only then is the sibling retired, whole, to a
set-aside folder (``tts.omnivoice_setup.retire_legacy``). Its old receipt (:func:`legacy_receipt_path`) is another file
than the nested engine's (:func:`receipt_path`) and is never rewritten, so it can never vouch for the new one.

The six voices are conditioned on **their own** owner-curated recordings, ``files/Cloned-Voice-Uploads/OmniVoice/
OmniVoice - <Voice>.wav``, used whole -- never cropped again -- with the owner-written transcripts as reference text
(owner decision 2026-11-13; it replaced the Phase 2 derived excerpts). Each recording is pinned here by SHA-256 and
listed, with its format, exact frame count and transcript, in ``tts/data/clone_references.json``
(``tts/clone_references``). A reference is at most 10.000 s, except the one owner-approved, hash-bound Male 1 recording
(:data:`DURATION_EXCEPTIONS`). The recordings are only ever read; the Chatterbox and Qwen3 clones have their own.

Nothing here installs anything. The optional installer (``tts.omnivoice_setup``, plan Phase 3) places the environment
and the model, calls :func:`verify_model_files`, proves the engine loads, and only then writes the install receipt
(:func:`receipt_path`) that :func:`environment_status` requires; a conversion (``omnivoice_synth``) is the only thing
that loads the model for narration.

**Readiness of the environment (v0.8.0 Phase 3).** The environment is used only when this app's installer has
proved it and recorded that proof: the exact pinned package set, its own isolated interpreter, the base Python it was
built from unchanged since, and an install-time load proof. An environment at the nested path holding exactly the
pinned set that no receipt vouches for -- one whose proof was interrupted -- is *unchecked*, never ready and never
broken: the installer adopts it after the same proof, without downloading or replacing anything
(:func:`assess_engine`).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from shared import venv_layout
from tts import clone_references
from tts import qwen3_runtime as _qwen3  # the shared, light helpers: hashing, OS-owned locks, GPU probe, PATH scrub

BACKEND = "omnivoice"
#: The optional-setup component that installs these voices. Install & Continue offers it only once the setup protocol
#: knows it (plan Phase 3); until then an uninstalled OmniVoice voice is reported, not offered.
COMPONENT = "omnivoice"
ENGINE_NAME = "OmniVoice"


class OmniVoiceUnavailable(RuntimeError):
    """The OmniVoice engine, its model, or a voice's reference recording is not usable right now.

    Always carries a message fit to show a non-technical user. Raised instead of falling back to another voice, another
    engine, another engine's recording, or a transcript-free clone, so no substituted voice is ever produced.
    """


# --------------------------------------------------------------------------- #
# Identity of the six voices
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OmniVoiceVoice:
    voice_id: str
    reference_id: str  # the stable reference id (voice_registry.VOICE_REFERENCES)
    reference_sha256: str  # the voice's OWN recording, as the owner approved it (2026-11-13)
    text_sha256: str  # the owner-written transcript of that recording (UTF-8), its reference text

    @property
    def label(self) -> str:
        """This voice's current registry label, looked up when asked (the registry never depends on an engine)."""
        from tts.voice_registry import label_for

        return label_for(BACKEND, self.voice_id)


#: Plan section 3: six new, distinct stable ids. Owner decision 2026-11-13: each is cloned from its own owner-curated
#: recording (44.1 kHz mono 16-bit) with its owner-written transcript, both pinned here by SHA-256 (so neither can change
#: by editing the reference list alone); the Chatterbox and Qwen3 recordings are other files.
OMNIVOICE_VOICES: tuple[OmniVoiceVoice, ...] = (
    OmniVoiceVoice("omnivoice-female-1", "Female-1",
                   reference_sha256="438329e6c39917b55a6833b0a1244c7375bf17a61580c3dc07b6098743d13249",
                   text_sha256="a08d518bc256bebaa16be69ab673ec454ffc26e8298e6243e5a4e03617b4bd1b"),
    OmniVoiceVoice("omnivoice-female-2", "Female-2",
                   reference_sha256="909a0ea7935385792075771291fd1aa922c22e3a0756fb6210f0b69830141861",
                   text_sha256="927d8f7e5825034d8e9a04d009176012b682fb9d3da3c42b5372a3f1918ad13f"),
    OmniVoiceVoice("omnivoice-male-1", "Male-1",
                   reference_sha256="7753385380675913f0b97c5a03ca6d63702dec13c4905d7f014dc45ef7b1ccf7",
                   text_sha256="93cb79177664e36fc78babc1ec00a7a00fbb51c7fadd2da647463681f49e69de"),
    OmniVoiceVoice("omnivoice-male-2", "Male-2",
                   reference_sha256="0b2918438b877bbe35ff38d590adca2af00e213219588bbc39ad5505f4c5b678",
                   text_sha256="79d1806d7cf7608f68c614be1661937bba63dae40c36b4829fb4a748d46d0cac"),
    OmniVoiceVoice("omnivoice-male-3", "Male-3",
                   reference_sha256="5dc34276f15cb42b9a3a04dc67c6bc1fba1f3511c979c0ea81bc6751aa885b89",
                   text_sha256="acd64ab91990b19960be28011596368b30f305bc7a08cb9bb9b571e9b598084e"),
    OmniVoiceVoice("omnivoice-male-4", "Male-4",
                   reference_sha256="31d7305ce0257a56599607e575679763c49ce3ecd5541d81c6e6b877002d1d3d",
                   text_sha256="89413cea1f002d79de9ff5811abc893296ba53b6379c06d804cfef7209a7f8c7"),
)
_VOICE_BY_ID = {v.voice_id: v for v in OMNIVOICE_VOICES}


def get_voice(voice_id: str) -> OmniVoiceVoice:
    try:
        return _VOICE_BY_ID[voice_id]
    except KeyError:
        raise OmniVoiceUnavailable(
            f"Unknown OmniVoice voice '{voice_id}'. Known voices: {', '.join(sorted(_VOICE_BY_ID))}.") from None


def reference_path(voice: OmniVoiceVoice) -> Path:
    """The voice's own recording, ``files/Cloned-Voice-Uploads/OmniVoice/OmniVoice - <Voice>.wav`` (named by the registry)."""
    from tts.voice_registry import reference_recording_parts

    return repo_root().joinpath(*reference_recording_parts(BACKEND, voice.voice_id))


# --------------------------------------------------------------------------- #
# Locations -- everything inside the repository tree (AI-WORKSPACE containment)
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    return _qwen3.repo_root()


def runtime_dir() -> Path:
    """``files/runtime-data/omnivoice/`` -- ignored, app-owned: models, verification record, locks, jobs, prompt cache."""
    return repo_root() / "files" / "runtime-data" / "omnivoice"


def parent_venv_dir() -> Path:
    """The application's own environment, ``.venv``, which holds the engine's (and Qwen3's)."""
    return repo_root() / ".venv"


def nested_venv_dir() -> Path:
    """``.venv/engines/omnivoice``: where the engine is installed, always. An independent environment of its own."""
    return repo_root().joinpath(*venv_layout.NESTED_OMNIVOICE.split("/"))


def legacy_venv_dir() -> Path:
    """``.venv-omnivoice``: where the first v0.8.0 development builds installed the engine. Never used, never installed
    into, never deleted; only recognised (:func:`assess_legacy`) and, once the nested engine is proved, retired."""
    return repo_root() / venv_layout.LEGACY_OMNIVOICE


def venv_dir() -> Path:
    """The engine environment the app uses: ``.venv/engines/omnivoice``, whatever state it is in.

    The one runtime path. Nothing chooses between it and the earlier sibling: a damaged engine here is reported as
    damaged, never hidden behind (or replaced at run time by) ``.venv-omnivoice``."""
    return nested_venv_dir()


def shown_path(folder: Path) -> str:
    """*folder* relative to the app's folder, the way a person would type it (``.venv\\engines\\omnivoice``)."""
    return _qwen3.shown_path(folder)


def venv_python() -> Path:
    return venv_layout.interpreter(venv_dir())


def models_root() -> Path:
    return runtime_dir() / "models"


def jobs_root() -> Path:
    return runtime_dir() / "jobs"


def prompts_root() -> Path:
    """Reusable clone prompts this app's own worker made, each filed under its full identity (:func:`prompt_identity`)."""
    return runtime_dir() / "prompts"


def cache_root() -> Path:
    return runtime_dir() / "cache"


def tmp_root() -> Path:
    return runtime_dir() / "tmp"


def model_record_path() -> Path:
    """The record that every model file was verified by size and SHA-256. Kept beside, never inside, the model folder."""
    return runtime_dir() / "model-verified.json"


def inference_lock_path() -> Path:
    return runtime_dir() / "inference.lock"


def engine_lock_path() -> Path:
    """Held by the worker process itself for as long as it runs, so an install or repair sees an engine still in use."""
    return runtime_dir() / "engine.lock"


def receipt_path() -> Path:
    """The nested engine's install receipt: written only after the installer proved the environment (and model) work.
    Outside the parent ``.venv``, so a repair that replaces the parent neither loses it nor carries a stale one in."""
    return runtime_dir() / "engine-receipt.json"


def legacy_receipt_path() -> Path:
    """The receipt the earlier sibling ``.venv-omnivoice`` was recorded with (receipt version 1). Only ever read, to say
    what that folder was; it is retired together with the folder and never vouches for the nested engine."""
    return runtime_dir() / "install-receipt.json"


def wheel_cache_dir() -> Path:
    """Where the installer keeps the verified wheels while it installs (removed after a proved install)."""
    return runtime_dir() / "cache" / "wheels"


def set_aside_root() -> Path:
    """Where a repair moves an environment it replaces, and where a retired ``.venv-omnivoice`` is kept -- never
    deleted, for the owner to remove. Nothing is ever run from here: an environment moved off its own path is not an
    environment any more (``venv_layout.assess_child``)."""
    return runtime_dir() / "set-aside"


def worker_script() -> Path:
    return Path(__file__).resolve().with_name("omnivoice_worker.py")


def manifest_path() -> Path:
    return Path(__file__).resolve().with_name("omnivoice_manifest.json")


def refuse_link(folder: Path) -> None:
    if _qwen3.is_link(folder):
        raise OmniVoiceUnavailable(f"The OmniVoice data folder {Path(folder).name!r} is a link to another folder; the "
                                   "app refuses to use it. Remove the link (not its target).")


def ensure_runtime_dir(path: Path) -> Path:
    """Create a folder inside the OmniVoice runtime folder, proving neither it nor any folder up to it is a link."""
    path = Path(path)
    chain = [path]
    try:
        path.relative_to(runtime_dir())
        while chain[-1] != runtime_dir():
            chain.append(chain[-1].parent)
    except ValueError:
        chain.append(runtime_dir())
    for folder in chain:
        if folder.exists() or folder.is_symlink():
            refuse_link(folder)
    path.mkdir(parents=True, exist_ok=True)
    for folder in chain:
        refuse_link(folder)
    return path


def atomic_write_json(path: Path, data: dict) -> None:
    """Publish *data* at *path* through a fresh exclusive temporary file, never writing through a planted link."""
    path = Path(path)
    if _is_under(path, runtime_dir()):
        ensure_runtime_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    _qwen3.remove_entry(tmp)
    try:
        with open(tmp, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, path)
    finally:
        if tmp.is_file() and not tmp.is_symlink():
            tmp.unlink()


def _is_under(path: Path, root: Path) -> bool:
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# The pinned engine: package set and model snapshot
# --------------------------------------------------------------------------- #
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_CACHE: dict = {}


def load_manifest() -> dict:
    """The tracked manifest (``tts/omnivoice_manifest.json``), validated. ``OmniVoiceUnavailable`` if it is not usable."""
    path = manifest_path()
    try:
        stamp = (path.stat().st_size, path.stat().st_mtime_ns)
        if _MANIFEST_CACHE.get("stamp") != stamp:
            data = json.loads(path.read_text(encoding="utf-8"))
            problems = manifest_problems(data)
            if problems:
                raise OmniVoiceUnavailable(f"The OmniVoice engine list shipped with the app is damaged ({problems[0]}).")
            _MANIFEST_CACHE.update(stamp=stamp, data=data)
    except (OSError, ValueError) as exc:
        raise OmniVoiceUnavailable(f"The OmniVoice engine list shipped with the app could not be read ({exc}).") from exc
    return _MANIFEST_CACHE["data"]


def manifest_problems(data: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, dict) or data.get("schema") != "act-omnivoice-engine" or data.get("version") != 1:
        return ["not an act-omnivoice-engine manifest, version 1"]
    model = data.get("model") or {}
    if model.get("repo") != "k2-fsa/OmniVoice" or not _HEX40.fullmatch(str(model.get("revision", ""))):
        problems.append("the model is not k2-fsa/OmniVoice at a pinned commit")
    files = model.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("the model has no files")
        files = {}
    for name, entry in files.items():
        try:
            _qwen3.check_relative_name(name)
        except _qwen3.Qwen3Unavailable:
            problems.append(f"model file {name!r} is not a plain relative path")
        if not (isinstance(entry, dict) and type(entry.get("size")) is int and entry["size"] > 0
                and _HEX64.fullmatch(str(entry.get("sha256", "")))):
            problems.append(f"model file {name!r} has no size and SHA-256")
    required = model.get("load_required") or []
    if not required or any(name not in files for name in required) \
            or not any(name.startswith("audio_tokenizer/") for name in required):
        problems.append("the files the load needs (the audio tokenizer included) are not all pinned")
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) and x for x in p) for p in packages):
        problems.append("the package set is not a list of [name, version] pins")
    elif len({canonical_name(p[0]) for p in packages}) != len(packages):
        problems.append("a package is pinned twice")
    if (data.get("engine") or {}).get("omnivoice") != "0.2.1":
        problems.append("the engine is not omnivoice 0.2.1")
    problems += _wheel_problems(data)
    if model.get("url_template") != HUB_URL_TEMPLATE:
        problems.append("the model is not fetched from its pinned revision on the Hugging Face Hub")
    return problems


#: The only form a model file is ever fetched in: the pinned repository at the pinned commit.
HUB_URL_TEMPLATE = "https://huggingface.co/{repo}/resolve/{revision}/{path}"
#: Where a wheel may come from: PyPI's file host, or PyTorch's own index for its CUDA 12.8 builds.
WHEEL_HOSTS = ("https://files.pythonhosted.org/packages/", "https://download-r2.pytorch.org/whl/cu128/")
_WHEEL_NAME = re.compile(r"[A-Za-z0-9_.+-]+\.whl")


def _wheel_problems(data: dict) -> list[str]:
    """The wheels must be exactly the pinned packages, each by name, file name, host, size and SHA-256 (v0.8.0 Phase 3:
    the installer fetches these and nothing else, so the application never re-resolves a dependency)."""
    wheels = data.get("wheels")
    packages = data.get("packages")
    if not isinstance(wheels, list) or not wheels:
        return ["the package set has no pinned wheels"]
    problems: list[str] = []
    names: set[str] = set()
    for entry in wheels:
        if not (isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("version"), str)
                and isinstance(entry.get("filename"), str) and _WHEEL_NAME.fullmatch(entry["filename"])
                and isinstance(entry.get("url"), str) and entry["url"].startswith(WHEEL_HOSTS)
                and type(entry.get("size")) is int and entry["size"] > 0
                and _HEX64.fullmatch(str(entry.get("sha256", "")))):
            problems.append(f"wheel {entry!r:.80} is not a pinned file (name, file, host, size, SHA-256)")
            continue
        names.add(entry["filename"].lower())
    if len(names) != len(wheels):
        problems.append("a wheel file is pinned twice")
    if isinstance(packages, list) and [[w.get("name"), w.get("version")] for w in wheels if isinstance(w, dict)] != \
            [list(p) for p in packages]:
        problems.append("the wheels are not exactly the pinned packages, in order")
    return problems


def model_spec() -> dict:
    return load_manifest()["model"]


def model_dir() -> Path:
    spec = model_spec()
    return models_root() / spec["repo"].replace("/", "--") / spec["revision"]


def model_manifest_sha256() -> str:
    spec = model_spec()
    blob = json.dumps({"repo": spec["repo"], "revision": spec["revision"], "files": spec["files"]},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_name(name: str) -> str:
    """A distribution name as pip compares them (PEP 503): lower case, runs of ``-_.`` as one ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_packages() -> dict[str, str]:
    return {canonical_name(name): version for name, version in load_manifest()["packages"]}


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str


def wheels() -> tuple[Wheel, ...]:
    """The 88 pinned wheels of the environment, in manifest order, each with the one URL it may come from."""
    return tuple(Wheel(w["name"], w["version"], w["filename"], w["url"], w["size"], w["sha256"])
                 for w in load_manifest()["wheels"])


def wheels_total_bytes() -> int:
    return sum(w.size for w in wheels())


#: The installer's record of the wheels it verified here (``tts.omnivoice_setup`` writes it; reading it is planning).
WHEEL_RECORD_NAME = "verified.json"


def wheel_record_path() -> Path:
    return wheel_cache_dir() / WHEEL_RECORD_NAME


def wheel_record() -> dict:
    try:
        data = json.loads(wheel_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def regular_file_stat(path: Path) -> Optional[os.stat_result]:
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def wheel_recorded(wheel: "Wheel", record: dict) -> bool:
    info = regular_file_stat(wheel_cache_dir() / wheel.filename)
    return info is not None and info.st_size == wheel.size and \
        record.get(wheel.filename) == [wheel.size, info.st_mtime_ns, wheel.sha256]


def wheel_verified(wheel: "Wheel", record: Optional[dict] = None) -> bool:
    """Whether *wheel* is here and exactly the pinned file: by the installer's record, or else by hashing a file of the
    right size (the stronger check only where no record vouches). A link or a folder on the way is never trusted."""
    record = wheel_record() if record is None else record
    if venv_layout.unsafe_component(repo_root(), wheel_cache_dir()) is not None:
        return False
    if wheel_recorded(wheel, record):
        return True
    path = wheel_cache_dir() / wheel.filename
    info = regular_file_stat(path)
    if info is None or info.st_size != wheel.size:
        return False
    try:
        return _qwen3.sha256_file(path) == wheel.sha256
    except OSError:
        return False


def wheel_bytes() -> tuple[int, int]:
    """``(bytes to download, bytes already verified here)`` for the pinned wheels. Reads, never writes."""
    record = wheel_record()
    fetch = have = 0
    for wheel in wheels():
        if wheel_verified(wheel, record):
            have += wheel.size
        else:
            fetch += wheel.size
    return fetch, have


def packages_sha256() -> str:
    """The identity of the pinned package set: every wheel's name, version, file name, size and SHA-256."""
    rows = [[w.name, w.version, w.filename, w.size, w.sha256] for w in wheels()]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def model_total_bytes() -> int:
    return sum(f["size"] for f in model_spec()["files"].values())


def model_url(name: str) -> str:
    spec = model_spec()
    return spec["url_template"].format(repo=spec["repo"], revision=spec["revision"], path=name)


#: The environment once built from the 88 wheels, measured on HOME-PC (2026-11-13): an estimate, never a promise.
ENGINE_INSTALLED_BYTES_FALLBACK = 8_346_271_361


def engine_installed_bytes() -> int:
    try:
        value = (load_manifest().get("installed_bytes") or {}).get("environment")
    except OmniVoiceUnavailable:
        value = None
    return value if type(value) is int and value > 0 else ENGINE_INSTALLED_BYTES_FALLBACK


# --------------------------------------------------------------------------- #
# What a person agrees to: the licences and the hardware (shown before anything is downloaded)
# --------------------------------------------------------------------------- #
#: The attribution the audio tokenizer's licence (Boson Higgs Audio 2 Community License, section 1.b.i) asks a product
#: that uses it to display in its user interface or documentation; reproduced as the licence words it.
TOKENIZER_ATTRIBUTION = ("Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All "
                         "Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright "
                         "Meta Platforms, Inc., All Rights Reserved.")

LICENSE_SUMMARY: tuple[str, ...] = (
    "The OmniVoice program code (omnivoice 0.2.1) is licensed Apache-2.0.",
    "The pre-trained OmniVoice model weights are licensed CC-BY-NC: NON-COMMERCIAL use only. The model card does not "
    "say which version of CC-BY-NC applies. Installing OmniVoice does not give you the right to make commercial "
    "audiobooks, or to sell or monetise audio made with these voices.",
    "The audio tokenizer OmniVoice needs is licensed separately, under the Boson Higgs Audio 2 Community License "
    "(based on the Meta Llama 3 Community License). Among its terms: the Llama 3 Acceptable Use Policy applies; you may "
    "not use its outputs to improve any other large language model; a product or service with more than 100,000 "
    "annual active users in the preceding calendar year needs an expanded licence from Boson AI; and distributing it "
    "requires a copy of the agreement, a Notice file and the attribution below.",
    "The model card also forbids using the model for unauthorised voice cloning, voice impersonation, fraud or any "
    "other illegal or unethical purpose.",
    "This summary is not legal advice and does not replace the licence texts; read them before you install.",
)

HARDWARE_DISCLOSURE = (
    "OmniVoice needs Windows and an NVIDIA graphics card (GPU) with a current driver; it does not run on the processor "
    "alone. It was qualified on one computer: an NVIDIA RTX 5070 with the CUDA 12.8 build of PyTorch, CPython 3.12 and "
    "its own separate environment. Its speed and the graphics memory it needs on other cards are not promised.")


def license_documents() -> list[dict]:
    """Where each licence can be read (pinned revisions), and the copy kept with the model once it is installed."""
    try:
        documents = load_manifest().get("license_documents") or []
    except OmniVoiceUnavailable:
        documents = []
    out = []
    for doc in documents:
        if isinstance(doc, dict) and isinstance(doc.get("title"), str) and isinstance(doc.get("url"), str) \
                and doc["url"].startswith("https://"):
            local = doc.get("local")
            out.append({"id": str(doc.get("id", "")), "title": doc["title"], "url": doc["url"],
                        "local": str(model_dir().joinpath(*local.split("/"))) if isinstance(local, str) else None})
    return out


def disclosure() -> dict:
    """The licence and hardware terms shown before consent (plan data: wording, never acquisition terms)."""
    return {"title": "OmniVoice licence terms", "summary": list(LICENSE_SUMMARY), "attribution": TOKENIZER_ATTRIBUTION,
            "documents": license_documents(), "hardware": HARDWARE_DISCLOSURE}


#: Installed by ``python -m venv`` itself, not by the lock; its presence or version says nothing about the engine.
VENV_BOOTSTRAP = frozenset({"pip"})


def site_packages(folder: Path) -> Path:
    if sys.platform == "win32":
        return Path(folder) / "Lib" / "site-packages"
    found = sorted(Path(folder).glob("lib/python3.*/site-packages"))
    return found[0] if found else Path(folder) / "lib" / "site-packages"


def installed_distributions(folder: Path) -> dict[str, str]:
    """``{canonical name: version}`` of every ``*.dist-info`` in the environment's site-packages. A listing, no import."""
    found: dict[str, str] = {}
    root = site_packages(folder)
    if not root.is_dir():
        return found
    for entry in root.iterdir():
        if entry.name.endswith(".dist-info") and entry.is_dir():
            name, _, version = entry.name[: -len(".dist-info")].rpartition("-")
            if name:
                found[canonical_name(name)] = version
    return found


# --------------------------------------------------------------------------- #
# Readiness: platform, GPU, environment, model
# --------------------------------------------------------------------------- #
def platform_supported() -> bool:
    """Windows only: the engine was qualified on Windows 11 x64 (plan non-goal: no Mac support claim)."""
    return sys.platform == "win32"


def platform_reason() -> str:
    return ("The OmniVoice voices are not available on this platform. They currently need Windows; every other voice "
            "works as before.")


def detect_gpu() -> Optional["_qwen3.GpuInfo"]:
    """The first NVIDIA GPU the driver reports, or ``None`` (asked once per process; the Qwen3 probe, shared)."""
    return _qwen3.detect_gpu()


NO_GPU_MESSAGE = ("The OmniVoice voices need an NVIDIA graphics card (GPU) with a current driver, and none was found on "
                  "this computer. They were not qualified to run on the processor alone. Every other voice is "
                  "unaffected.")
INSTALL_ACTION = "Install it from the app's optional voice setup (Install & Continue)"
NOT_INSTALLED_MESSAGE = ("The OmniVoice voice engine is not installed on this computer. " + INSTALL_ACTION
                         + "; every other voice is unaffected.")
UNCHECKED_MESSAGE = ("An OmniVoice voice engine is on this computer, but this version of the app has not checked it "
                     "yet, so it is not used. Install & Continue checks it and adopts it; nothing is downloaded or "
                     "replaced when it is complete.")
INCOMPLETE_MESSAGE = "The OmniVoice voice engine was not installed completely. " + INSTALL_ACTION + " to repair it."
LINKED_MESSAGE = ("The OmniVoice environment is reached through a link to another folder, so the app will not use it. "
                  "Remove the link (not its target).")
#: Nothing at the nested path, an earlier environment beside the app's: said instead of "not installed", because the
#: person did install it. Installing builds it again where it now belongs; nothing of the old one is reused or deleted.
LEGACY_MOVE_MESSAGE = ("The OmniVoice voice engine on this computer is in a folder this version of the app no longer "
                       "uses (.venv-omnivoice). " + INSTALL_ACTION + ": it is built again inside the app's own "
                       "environment (.venv\\engines\\omnivoice) from its pinned packages and checked there; a model "
                       "that is already on this computer is reused. Only once the new engine works is the old folder "
                       "moved to files\\runtime-data\\omnivoice\\set-aside -- kept, never deleted.")
#: Appended when the nested engine is present but not usable and the earlier sibling is still there: it is said, never
#: silently preferred and never silently ignored.
LEGACY_NOT_USED_NOTE = (" (The earlier environment in .venv-omnivoice is not used in its place; it is kept as it is "
                        "until the new one works.)")
#: A sibling still beside a nested engine that is ready (it could not be moved when the engine was proved, or it was put
#: back by hand). It promises only what is true: nothing moves it while the engine stays ready -- the acquirer runs
#: only when something has to be installed or repaired, and tries the move again then.
LEGACY_LEFTOVER_NOTE = ("The earlier OmniVoice environment in .venv-omnivoice is no longer used by the app and is still "
                        "in the app's folder (about 8 GB). You may move or delete that folder yourself; the app will "
                        "not use it, and moves it to files\\runtime-data\\omnivoice\\set-aside itself only if "
                        "OmniVoice ever has to be installed or repaired again.")


# --------------------------------------------------------------------------- #
# How deep the app's folder may be for this engine (Windows path limits)
# --------------------------------------------------------------------------- #
#: The longest path Windows' loader accepts for a native library, long-path support or not.
WINDOWS_MAX_PATH = 259
#: The deepest native library (.dll/.pyd) of the environment at ``.venv/engines/omnivoice``, below the app's folder
#: with its separator (135 + 1: scikit-learn's deepest extension; measured on HOME-PC 2026-11-13), plus a margin.
DEEPEST_NATIVE_LIBRARY_CHARS = 140
#: The deepest file of any kind there (168 + 1) plus a margin: the limit for every file while Windows long-path
#: support is off, when pip could not even write it.
DEEPEST_FILE_CHARS = 176


def windows_long_paths_enabled() -> Optional[bool]:
    """Whether Windows long-path support is on (``None``: not Windows, or it could not be read). Never changes it."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return None


def install_depth_problem(root: Optional[Path] = None, *, long_paths: Optional[bool] = None) -> str:
    """Why the OmniVoice engine cannot be installed in a copy of the app this deep, or ``""``.

    The engine is held inside ``.venv`` (``.venv/engines/omnivoice``), so its files sit deeper than the app's own and
    need a shorter app folder than ``bootstrap.install_path_problem`` asks for. Checked before anything is downloaded,
    so a too-deep copy is told once, plainly, instead of getting an engine whose libraries Windows refuses to load.
    Only this engine's install is refused; the app and every other voice are unaffected."""
    if sys.platform != "win32":
        return ""
    root = Path(repo_root() if root is None else root)
    length = len(str(root))
    enabled = windows_long_paths_enabled() if long_paths is None else long_paths
    limit = WINDOWS_MAX_PATH - (DEEPEST_NATIVE_LIBRARY_CHARS if enabled else DEEPEST_FILE_CHARS)
    if length <= limit:
        return ""
    return (f"The OmniVoice voice engine cannot be installed in this copy of the app: the app's folder path is "
            f"{length} characters long and OmniVoice needs {limit} or fewer here, or Windows could not load its files. "
            "Nothing was installed. Move the whole app folder somewhere shorter (for example C:\\Audiobook Creation "
            "Tool), start it from there, and install OmniVoice again. Every other voice is unaffected.")


# --------------------------------------------------------------------------- #
# The install receipt (v0.8.0 Phase 3): what makes the environment this app's own, proved
# --------------------------------------------------------------------------- #
RECEIPT_SCHEMA = "act-omnivoice-install-receipt"
#: Version 2 names the nested path (``.venv/engines/omnivoice``) and lives in :func:`receipt_path`. Version 1 was
#: written for the sibling ``.venv-omnivoice`` into :func:`legacy_receipt_path`; it is read only by
#: :func:`read_legacy_receipt` and can never make the nested engine ready (another file, another version, another path).
RECEIPT_VERSION = 2
LEGACY_RECEIPT_VERSION = 1
#: Written before the installer creates an environment (so an interruption is known to be the app's own, unfinished),
#: after a proof succeeded (the only stage that makes the engine ready), or after an existing environment was checked
#: and proved not to work (so the next plan offers a repair instead of the same check again).
STAGE_CREATING = "creating"
STAGE_INSTALLED = "installed"
STAGE_REJECTED = "rejected"
ORIGIN_INSTALLED = "installed"  # built by this app's installer from the pinned wheels
ORIGIN_ADOPTED = "adopted"  # found already holding exactly the pinned set, then proved the same way


def _read_receipt_file(path: Path, version: int, folder: Path) -> dict:
    if venv_layout.unsafe_component(repo_root(), path) is not None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != RECEIPT_SCHEMA or data.get("version") != version:
        return {}
    if not isinstance(data.get("path"), str) or not venv_layout.same_path(data["path"], folder):
        return {}
    return data


def read_receipt() -> dict:
    """The receipt for the nested engine, or ``{}``: absent, unreadable, a link, of another schema or version, or
    written for another folder (a copied or stale receipt never vouches for an environment it was not written for --
    a receipt of the earlier sibling, or of another copy of the app, least of all)."""
    return _read_receipt_file(receipt_path(), RECEIPT_VERSION, nested_venv_dir())


def read_legacy_receipt() -> dict:
    """What the earlier sibling ``.venv-omnivoice`` was recorded with, or ``{}``. Evidence about that folder only."""
    return _read_receipt_file(legacy_receipt_path(), LEGACY_RECEIPT_VERSION, legacy_venv_dir())


def write_receipt(stage: str, **fields) -> dict:
    """Publish the receipt for the nested engine at *stage* (atomically, never through a link)."""
    if stage not in (STAGE_CREATING, STAGE_INSTALLED, STAGE_REJECTED):
        raise ValueError(f"unknown receipt stage {stage!r}")
    record = {"schema": RECEIPT_SCHEMA, "version": RECEIPT_VERSION, "stage": stage,
              "path": os.path.normpath(os.path.abspath(venv_dir())), "packages_sha256": packages_sha256(),
              "omnivoice": load_manifest()["engine"]["omnivoice"],
              "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    atomic_write_json(receipt_path(), record)
    return record


def clear_receipt() -> None:
    path = receipt_path()
    if os.path.lexists(path):
        _qwen3.remove_entry(path)


#: Windows' Smart App Control refuses the first load of a new native library with this phrase; a rebuild cannot change
#: that, so it never counts against the environment (the same mark the installer's own proof excludes).
APPLICATION_CONTROL_MARK = "Application Control policy"
#: Worker failure stages that mean the environment's own files are wrong: it does not hold its pinned packages, or they
#: do not import. (Not ``isolation``, which the launching process's surroundings can cause, nor anything about the GPU,
#: its memory, the model or the job.)
REBUILD_STAGES = frozenset({"versions", "import"})


def failure_needs_rebuild(terminal: dict) -> bool:
    """Whether a worker's ``failed`` event says the engine's installed files are damaged, so only a rebuild can help.

    A conversion imports the engine's packages outside the probe's guarded import, so a package that does not import
    arrives from the worker's last-resort handler as stage ``worker`` with the exception's own name first (measured on
    the real engine: ``ImportError: cannot import name 'OmniVoice' from 'omnivoice' (unknown location)``)."""
    message = str(terminal.get("message") or "")
    if APPLICATION_CONTROL_MARK in message:
        return False
    stage = terminal.get("stage")
    return stage in REBUILD_STAGES or (stage == "worker" and message.startswith(("ImportError", "ModuleNotFoundError")))


def reject_ready_engine(reason: str) -> bool:
    """Record that the engine the receipt calls ready failed at use in a way only a rebuild can mend. True if recorded.

    Found on the real nested engine (2026-11-13): with one package file deleted, the folder listing and the receipt
    still said "ready", every conversion failed, and nothing offered a repair. The conversion that meets such a failure
    (:func:`failure_needs_rebuild`) records it here -- it holds ``inference.lock``, so no installer is changing the
    engine -- and the next look therefore says *broken*, the voices say why, and Install & Continue offers the repair
    (the damaged environment is set aside whole, never deleted, and a fresh one is built and proved). Only a READY
    engine is ever rejected this way; never raises."""
    try:
        if _assess_nested(None).state != ENGINE_READY:
            return False
        write_receipt(STAGE_REJECTED, base=venv_layout.base_identity(venv_dir()), reason=str(reason)[:300],
                      rejected_at="conversion")
        return True
    except (OSError, ValueError, OmniVoiceUnavailable):
        return False


# --------------------------------------------------------------------------- #
# The environment: assessed cheaply (a folder listing and two small files; no process, no import)
# --------------------------------------------------------------------------- #
ENGINE_READY = "ready"  # proved and recorded by this app's installer, unchanged since
ENGINE_ABSENT = "absent"  # nothing at .venv/engines/omnivoice (whatever is, or is not, at the earlier sibling)
ENGINE_UNCHECKED = "unchecked"  # exactly the pinned set, built from the app's Python, but no receipt vouches for it
ENGINE_INCOMPLETE = "incomplete"  # this app's own install of it did not finish
ENGINE_BROKEN = "broken"  # present, and provably not the pinned engine (or checked and proved not to work)
ENGINE_UNVERIFIED = "unverified"  # reached through a link, or unreadable: nothing here can vouch for it, or change it
ENGINE_STATES = (ENGINE_READY, ENGINE_ABSENT, ENGINE_UNCHECKED, ENGINE_INCOMPLETE, ENGINE_BROKEN, ENGINE_UNVERIFIED)


@dataclass(frozen=True)
class EngineAssessment:
    state: str
    reason: str  # a sentence fit for a person; "ok" when ready


def app_base_python() -> Path:
    """The base interpreter the app's own ``.venv`` was built from (``sys._base_executable``), as ``python.exe``: the
    one Python an OmniVoice environment may be built from (the rule ``tts.qwen3_setup`` applies to Qwen3)."""
    exe = Path(getattr(sys, "_base_executable", "") or sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return exe.with_name("python.exe")
    return exe


def structure_problem(folder: Path, *, parent: Optional[Path] = None) -> str:
    """Why *folder* is not an isolated CPython 3.12 environment at its own place, or ``""``.

    *parent* is the environment it is held in, when there is one: an engine built from that environment's interpreter
    is not independent (the parent's repair would break it), so it is refused."""
    folder = Path(folder)
    if not folder.is_dir():
        return "it is not a folder"
    config = venv_layout.read_pyvenv_cfg(folder)
    if config is None:
        return "it has no readable pyvenv.cfg"
    if config.get("include-system-site-packages", "").lower() != "false":
        return "it is not isolated from the system's packages"
    if not venv_layout.interpreter(folder).is_file():
        return "its Python interpreter is missing"
    if parent is not None and any(config.get(key) and venv_layout.is_within(parent, config[key])
                                  for key in ("home", "executable")):
        return "it was built from the app's own environment instead of the app's base Python"
    command = config.get("command")
    if command and not os.path.normcase(command.rstrip().rstrip("\\/")).endswith(os.path.normcase(os.path.abspath(folder))):
        return "it was created in another folder and moved (environments cannot be moved)"
    if not str(config.get("version", config.get("version_info", ""))).startswith("3.12."):
        return "it was not made with Python 3.12, the version it is pinned to"
    if venv_layout.base_identity(folder) is None:
        return "the Python it was built from is missing"
    return ""


def listing_problem(folder: Path) -> str:
    """Why the environment's installed distributions are not exactly the pinned set (pip aside), or ``""``."""
    pins = pinned_packages()
    installed = installed_distributions(folder)
    missing = sorted(name for name in pins if name not in installed)
    wrong = sorted(name for name in pins if name in installed and installed[name] != pins[name])
    extra = sorted(set(installed) - set(pins) - VENV_BOOTSTRAP)
    if not (missing or wrong or extra):
        return ""
    detail = (f"{len(missing)} missing" if missing else f"{len(wrong)} at another version" if wrong
              else f"{len(extra)} not part of it")
    return f"{detail}: {', '.join((missing or wrong or extra)[:3])}"


LEGACY_ABSENT = "absent"  # nothing at .venv-omnivoice
LEGACY_LINK = "link"  # a link or junction, or reached through one: never read into, never moved
LEGACY_OCCUPIED = "occupied"  # something is there that is not an environment folder: never touched
LEGACY_HEALTHY = "healthy"  # the pinned engine, as the earlier build's own receipt recorded it
LEGACY_UNVERIFIED = "unverified"  # the pinned engine by its listing, but no receipt vouches for it
LEGACY_BROKEN = "broken"  # an environment folder that is not the pinned engine
LEGACY_STATES = (LEGACY_ABSENT, LEGACY_LINK, LEGACY_OCCUPIED, LEGACY_HEALTHY, LEGACY_UNVERIFIED, LEGACY_BROKEN)


@dataclass(frozen=True)
class LegacyAssessment:
    """What is at the earlier sibling ``.venv-omnivoice``. It is never used in any state; the state only decides what is
    said about it and whether it is something this app may move aside once the nested engine is proved."""
    state: str
    reason: str

    @property
    def present(self) -> bool:
        return self.state != LEGACY_ABSENT

    @property
    def retirable(self) -> bool:
        """A real environment folder at exactly that path, reached through no link: the only thing ever moved aside."""
        return self.state in (LEGACY_HEALTHY, LEGACY_UNVERIFIED, LEGACY_BROKEN)


def assess_legacy() -> LegacyAssessment:
    """What the earlier sibling ``.venv-omnivoice`` is, from the folder and its own old receipt. Read-only; never
    raises; never the answer to "can OmniVoice run" (:func:`assess_engine` is, about the nested path alone)."""
    folder = legacy_venv_dir()
    try:
        linked = venv_layout.unsafe_component(repo_root(), folder)
        if linked is not None:
            return LegacyAssessment(LEGACY_LINK, f"{venv_layout.LEGACY_OMNIVOICE} is a link, or is reached through "
                                                 "one; it is left exactly as it is")
        if not os.path.lexists(folder):
            return LegacyAssessment(LEGACY_ABSENT, "there is no earlier environment")
        if not folder.is_dir() or venv_layout.read_pyvenv_cfg(folder) is None:
            return LegacyAssessment(LEGACY_OCCUPIED, f"{venv_layout.LEGACY_OMNIVOICE} is not a Python environment; it "
                                                     "is left exactly as it is")
        problem = structure_problem(folder) or listing_problem(folder)
        if problem:
            return LegacyAssessment(LEGACY_BROKEN, f"the earlier environment is not the pinned engine ({problem})")
        receipt = read_legacy_receipt()
        if receipt.get("stage") == STAGE_INSTALLED and receipt.get("probe_ok") is True \
                and receipt.get("packages_sha256") == packages_sha256() \
                and receipt.get("base") == venv_layout.base_identity(folder):
            return LegacyAssessment(LEGACY_HEALTHY, "the earlier environment is complete and was proved where it is")
        return LegacyAssessment(LEGACY_UNVERIFIED, "the earlier environment holds the pinned packages, but nothing "
                                                   "records that it was proved")
    except OmniVoiceUnavailable as exc:
        return LegacyAssessment(LEGACY_OCCUPIED, str(exc))
    except OSError as exc:
        return LegacyAssessment(LEGACY_LINK, f"{venv_layout.LEGACY_OMNIVOICE} could not be read "
                                             f"({exc.strerror or exc}); it is left exactly as it is")


def legacy_leftover_note() -> str:
    """What to say about an earlier sibling still present beside a nested engine that is ready, or ``""``."""
    return LEGACY_LEFTOVER_NOTE if assess_legacy().retirable else ""


def assess_engine(*, app_base: Optional[Path] = None) -> EngineAssessment:
    """What ``.venv/engines/omnivoice`` is, from the folder and the receipt alone. Read-only; never raises.

    Ready only with a receipt of a proved install for this folder, for the current pinned set, and for the base Python
    it is still built from. An environment holding exactly the pinned set without such a receipt is *unchecked*
    (adoptable after a proof), never ready and never broken -- but only when it was built from the app's own base
    Python (*app_base*, default :func:`app_base_python`). Everything else present is broken (a repair builds a fresh
    one and keeps this folder), or unverified when reached through a link.

    Only the nested path is judged. An earlier sibling ``.venv-omnivoice`` changes the *words* -- it is named, so a
    damaged engine here is never quietly preferred over, or hidden behind, a healthy one there -- and never the state.
    """
    assessment = _assess_nested(app_base)
    if assessment.state == ENGINE_READY:
        return assessment
    try:
        legacy = assess_legacy()
    except Exception:  # noqa: BLE001 - the sibling is commentary; it never stops the nested engine being judged
        return assessment
    if not legacy.retirable:  # nothing there, or a link or a stray entry this app says nothing about and never touches
        return assessment
    if assessment.state == ENGINE_ABSENT:
        if assessment.reason == NOT_INSTALLED_MESSAGE:
            return EngineAssessment(ENGINE_ABSENT, LEGACY_MOVE_MESSAGE)
        return assessment
    return EngineAssessment(assessment.state, assessment.reason + LEGACY_NOT_USED_NOTE)


def _assess_nested(app_base: Optional[Path]) -> EngineAssessment:
    folder = nested_venv_dir()
    try:
        if venv_layout.unsafe_component(repo_root(), folder) is not None:
            return EngineAssessment(ENGINE_UNVERIFIED, LINKED_MESSAGE)
        if not os.path.lexists(folder):
            return EngineAssessment(ENGINE_ABSENT, install_depth_problem() or NOT_INSTALLED_MESSAGE)
        receipt = read_receipt()
        stage = receipt.get("stage")
        if stage == STAGE_CREATING:
            return EngineAssessment(ENGINE_INCOMPLETE, INCOMPLETE_MESSAGE)
        problem = structure_problem(folder, parent=parent_venv_dir())
        if problem:
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment cannot be used: {problem}. "
                                                   + INSTALL_ACTION + " to repair it.")
        listing = listing_problem(folder)
        if listing:
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment does not hold its pinned packages "
                                                   f"({listing}). " + INSTALL_ACTION + " to repair it.")
        base = venv_layout.base_identity(folder)
        digest = packages_sha256()
        same = receipt.get("packages_sha256") == digest and receipt.get("base") == base
        if stage == STAGE_INSTALLED and receipt.get("probe_ok") is True and same:
            return EngineAssessment(ENGINE_READY, "ok")
        if stage == STAGE_REJECTED and same:
            why = str(receipt.get("reason") or "it did not start")[:300]
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment was checked and does not work ({why}). "
                                                   + INSTALL_ACTION + " to repair it.")
        expected = app_base_python() if app_base is None else Path(app_base)
        if not venv_layout.same_path(base["executable"], expected):
            return EngineAssessment(ENGINE_BROKEN, "The OmniVoice environment was built from another Python than the "
                                                   "app's own, so it is not used. " + INSTALL_ACTION + " to repair it.")
        return EngineAssessment(ENGINE_UNCHECKED, UNCHECKED_MESSAGE)
    except OmniVoiceUnavailable as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, str(exc))
    except OSError as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, f"The OmniVoice environment could not be read ({exc.strerror or exc}).")


def environment_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the nested engine: ready only when this app's installer proved it and recorded that proof
    (:func:`assess_engine`). Cheap: a folder listing and two small files, no subprocess, no import of the engine."""
    assessment = assess_engine()
    if assessment.state == ENGINE_READY:
        return True, "ok"
    return False, assessment.reason


BAD_MISSING, BAD_SIZE, BAD_HASH, BAD_CHANGED = ("is missing", "has the wrong size", "does not match its SHA-256",
                                                 "changed after it was verified")


def _model_file(name: str) -> Path:
    folder = model_dir()
    if venv_layout.unsafe_component(repo_root(), folder) is not None and _is_under(folder, repo_root()):
        raise OmniVoiceUnavailable("The OmniVoice model folder is reached through a link; the app refuses to use it.")
    return folder.joinpath(*name.split("/"))


def model_bad_files(*, full: bool = False, progress: Optional[Callable[[int], None]] = None) -> list[tuple[str, str]]:
    """``(file, what is wrong)`` for every pinned model file that is not present and correct. Cheap by default
    (presence, size); ``full=True`` also hashes every file -- tens of seconds for 3.3 GB -- for install and repair."""
    files = model_spec()["files"]
    if not model_dir().is_dir():
        return [(name, BAD_MISSING) for name in files]
    bad: list[tuple[str, str]] = []
    for name, want in files.items():
        path = _model_file(name)
        if not path.is_file() or _qwen3.is_link(path):
            bad.append((name, BAD_MISSING))
        elif path.stat().st_size != want["size"]:
            bad.append((name, BAD_SIZE))
        elif full and _qwen3.sha256_file(path, progress) != want["sha256"]:
            bad.append((name, BAD_HASH))
    return bad


def verify_model_files(*, progress: Optional[Callable[[int], None]] = None) -> list[str]:
    """Hash every pinned model file and, only when all of them are exactly the pinned bytes, record that (beside the
    model folder, never in it). Returns the problems, ``[]`` when recorded. Reads the model; changes none of it."""
    bad = model_bad_files(full=True, progress=progress)
    if bad:
        return [f"{name} {reason}" for name, reason in bad]
    files = model_spec()["files"]
    stamps = {}
    for name in files:
        info = _model_file(name).stat()
        stamps[name] = [info.st_size, info.st_mtime_ns]
    atomic_write_json(model_record_path(), {
        "schema": 1, "repo": model_spec()["repo"], "revision": model_spec()["revision"],
        "manifest_sha256": model_manifest_sha256(), "files": stamps,
        "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return []


FILE_READY, FILE_MISSING, FILE_DAMAGED, FILE_UNVERIFIED = "ready", "missing", "damaged", "unverified"


def model_folder_problem() -> str:
    """Why the model folder cannot be trusted at all (a link on the way to it), or ``""``."""
    folder = model_dir()
    if venv_layout.unsafe_component(repo_root(), folder) is not None:
        return "The OmniVoice model folder is reached through a link; the app refuses to use it or write through it."
    return ""


def model_recorded() -> bool:
    """Whether the verification record vouches for every pinned model file, unchanged since it was hashed."""
    return model_status()[0]


def model_file_states(*, progress: Optional[Callable[[int], None]] = None) -> dict[str, tuple[str, str]]:
    """``{file: (state, detail)}`` for every pinned model file: ready, missing, damaged (another size or content) or
    unverified (a link, or unreadable). A valid verification record vouches for every file without hashing; otherwise
    each present file of the right size is hashed -- the stronger local check, made only where no record vouches."""
    files = model_spec()["files"]
    problem = model_folder_problem()
    if problem:
        return {name: (FILE_UNVERIFIED, problem) for name in files}
    if model_recorded():
        return {name: (FILE_READY, "") for name in files}
    states: dict[str, tuple[str, str]] = {}
    for name, want in files.items():
        path = _model_file(name)
        if venv_layout.unsafe_component(repo_root(), path) is not None:
            states[name] = (FILE_UNVERIFIED, f"{name} is reached through a link")
            continue
        try:
            info = os.stat(path)
        except FileNotFoundError:
            states[name] = (FILE_MISSING, f"{name} {BAD_MISSING}")
            continue
        except OSError as exc:
            states[name] = (FILE_UNVERIFIED, f"{name} cannot be read ({exc.strerror or exc})")
            continue
        if not path.is_file() or info.st_size != want["size"]:
            states[name] = (FILE_DAMAGED, f"{name} {BAD_SIZE}")
            continue
        try:
            digest = _qwen3.sha256_file(path, progress)
        except OSError as exc:
            states[name] = (FILE_UNVERIFIED, f"{name} cannot be read ({exc.strerror or exc})")
            continue
        states[name] = (FILE_READY, "") if digest == want["sha256"] else (FILE_DAMAGED, f"{name} {BAD_HASH}")
    return states


def model_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the model snapshot. Cheap: sizes and modification times against the verification record
    written by :func:`verify_model_files`; never hashes, never loads, never touches the network."""
    try:
        files = model_spec()["files"]
    except OmniVoiceUnavailable as exc:
        return False, str(exc)
    size = _qwen3.format_bytes(sum(f["size"] for f in files.values()))
    if not model_dir().is_dir():
        return False, f"The OmniVoice model ({size}) is not installed on this computer. " + INSTALL_ACTION + "."
    try:
        bad = model_bad_files()
    except OmniVoiceUnavailable as exc:
        return False, str(exc)
    if bad:
        return False, (f"The OmniVoice model is incomplete or damaged ({bad[0][0]} {bad[0][1]}). "
                       + INSTALL_ACTION + " to repair it.")
    try:
        record = json.loads(model_record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("manifest_sha256") != model_manifest_sha256():
        return False, ("The OmniVoice model files are present but have not been verified for this version of the app. "
                       + INSTALL_ACTION + " to check them.")
    stamps = record.get("files") if isinstance(record.get("files"), dict) else {}
    for name in files:
        info = _model_file(name).stat()
        if stamps.get(name) != [info.st_size, info.st_mtime_ns]:
            return False, (f"The OmniVoice model file {name} {BAD_CHANGED}. " + INSTALL_ACTION + " to check it again.")
    return True, "ok"


# --------------------------------------------------------------------------- #
# The reference recordings: owner-curated, used whole, at most 10 s (one owner exception)
# --------------------------------------------------------------------------- #
#: Ten seconds is the normal MAXIMUM for an OmniVoice reference (owner decisions 2026-11-13). Nothing longer is ever
#: conditioned on, except the one recording in :data:`DURATION_EXCEPTIONS`.
MAX_REFERENCE_SECONDS = 10
#: The ONE explicit owner exception (2026-11-13): OmniVoice - Male 1 keeps its whole recording, about 10.227 s, so its
#: last word ("things.") and the natural quiet after it are not cut. It is bound to that exact file -- its SHA-256, its
#: decoded frame count and its rate -- and widens nothing else: another file for this voice, or any other voice, is held
#: to 10 s.
DURATION_EXCEPTIONS: dict[str, tuple[str, int, int]] = {
    "omnivoice-male-1": ("7753385380675913f0b97c5a03ca6d63702dec13c4905d7f014dc45ef7b1ccf7", 451022, 44100),
}
#: How a reference reaches the model: the verified recording's own frames at its own rate (44.1 kHz for the six owner
#: recordings), unchanged and uncropped. OmniVoice's ``create_voice_clone_prompt`` resamples it to the model's rate in
#: memory and, with ``preprocess_prompt``, trims its silences; the file itself is only ever read.
PREPROCESSING_VERSION = "act-omnivoice-reference-v3"


class ReferenceAssetError(ValueError):
    """A reference recording, the reference list or a transcript is not exactly what was approved. The message says what."""


@dataclass(frozen=True)
class ReferenceSpec:
    """What one OmniVoice voice is conditioned on: its own approved recording and its owner-written transcript."""
    voice_id: str
    reference_id: str
    wav_sha256: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frames: int
    text: str
    text_sha256: str

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate

    @property
    def max_frames(self) -> int:
        """The most frames this reference may have: 10 s, or exactly the excepted recording's own length."""
        if DURATION_EXCEPTIONS.get(self.voice_id) == (self.wav_sha256, self.frames, self.sample_rate):
            return self.frames
        return MAX_REFERENCE_SECONDS * self.sample_rate


def text_sha256(text: str) -> str:
    return clone_references.text_sha256(text)


def duration_problem(spec: ReferenceSpec) -> Optional[str]:
    """Why *spec* is too long to condition on, or ``None``."""
    if 0 < spec.frames <= spec.max_frames:
        return None
    return (f"{spec.voice_id}: the recording is {spec.duration_s:.3f} s; an OmniVoice reference is at most "
            f"{MAX_REFERENCE_SECONDS} s")


def load_references(path: Optional[Path] = None) -> dict[str, ReferenceSpec]:
    """``voice_id -> ReferenceSpec`` for all six voices, from the WHOLE checked reference list (``clone_references``).

    Each entry must name the voice's own pinned recording (:attr:`OmniVoiceVoice.reference_sha256`) and its pinned
    owner-written transcript (:attr:`OmniVoiceVoice.text_sha256`; text conditioning needs the exact words), and respect
    the 10-second maximum (or the one exception, exactly). Nothing here reads a recording; :func:`verify_reference`
    does, at use.
    """
    try:
        assets = clone_references.load(path)
    except clone_references.ReferenceManifestError as exc:
        raise ReferenceAssetError(str(exc)) from exc
    specs: dict[str, ReferenceSpec] = {}
    for voice in OMNIVOICE_VOICES:
        asset = assets[(BACKEND, voice.voice_id)]  # load() proved that every registered clone has exactly one entry
        if asset.wav_sha256 != voice.reference_sha256:
            raise ReferenceAssetError(f"{voice.voice_id}: bound to a different recording than the approved one")
        if asset.text_sha256 != voice.text_sha256:
            raise ReferenceAssetError(f"{voice.voice_id}: the transcript is not the owner-approved one for its recording")
        spec = ReferenceSpec(voice.voice_id, asset.reference_id, asset.wav_sha256, asset.sample_rate, asset.channels,
                             asset.sample_width_bytes, asset.frames, asset.text, asset.text_sha256)
        problem = duration_problem(spec)
        if problem:
            raise ReferenceAssetError(problem)
        specs[voice.voice_id] = spec
    return specs


def reference_spec(voice_id: str) -> ReferenceSpec:
    get_voice(voice_id)
    try:
        return load_references()[voice_id]
    except ReferenceAssetError as exc:
        raise OmniVoiceUnavailable(f"The OmniVoice reference list shipped with the app is damaged ({exc}). "
                                   "Extract a fresh copy of the app to restore it.") from exc


def verify_reference(spec: ReferenceSpec, path: Path) -> dict:
    """Read the recording once and prove it is exactly the approved one; return what the worker is given.

    Its bytes must hash to the approved SHA-256, and those same bytes must be a plain PCM WAV in the approved format and
    length, within the duration rule. Nothing is written, cropped or converted: the worker reads the same file and
    proves the same thing before it builds a prompt.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceAssetError(f"{path.name} could not be read ({exc.strerror or exc})") from exc
    if hashlib.sha256(data).hexdigest() != spec.wav_sha256:
        raise ReferenceAssetError(f"{path.name} is not the recording {spec.voice_id} was approved with")
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            params = source.getparams()
    except (wave.Error, EOFError) as exc:
        raise ReferenceAssetError(f"{path.name} is not a plain PCM WAV ({exc})") from exc
    if params.comptype != "NONE" or (params.framerate, params.nchannels, params.sampwidth, params.nframes) != (
            spec.sample_rate, spec.channels, spec.sample_width_bytes, spec.frames):
        raise ReferenceAssetError(f"{path.name} is not in the approved format")
    problem = duration_problem(spec)
    if problem:
        raise ReferenceAssetError(problem)
    return {"wav": str(path), "wav_sha256": spec.wav_sha256, "frames": spec.frames, "sample_rate": spec.sample_rate,
            "max_frames": spec.max_frames}


# --------------------------------------------------------------------------- #
# The reusable clone prompt's identity
# --------------------------------------------------------------------------- #
#: OmniVoice's own ``VoiceClonePrompt`` file format (``omnivoice.models.omnivoice._VOICE_CLONE_PROMPT_FORMAT_VERSION``).
PROMPT_FORMAT_VERSION = 1
#: Schema 2 (v0.8.0 reference correction): whole owner recordings. No schema-1 (excerpt) prompt can match it.
PROMPT_IDENTITY_SCHEMA = 2


def prompt_identity(spec: ReferenceSpec, *, model_revision: str, omnivoice_version: str, preprocess_prompt: bool,
                    dtype: str) -> tuple[str, dict]:
    """The key a reusable clone prompt is filed under: every input that shapes it, so any change misses the cache.

    Bound: the recording's SHA-256, its frame count and rate, the preprocessing version, the transcript's SHA-256, the
    model revision, the engine version, the prompt format, the prompt preprocessing flag and the dtype the tokenizer ran
    in. A changed recording or transcript therefore never reuses a prompt made from the old one.
    """
    fields = {
        "schema": PROMPT_IDENTITY_SCHEMA, "voice_id": spec.voice_id, "wav_sha256": spec.wav_sha256,
        "reference": [spec.frames, spec.sample_rate], "preprocessing_version": PREPROCESSING_VERSION,
        "text_sha256": spec.text_sha256, "model_revision": model_revision, "omnivoice": omnivoice_version,
        "prompt_format_version": PROMPT_FORMAT_VERSION, "preprocess_prompt": bool(preprocess_prompt), "dtype": dtype,
    }
    key = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return key, fields


def prompt_cache_path(voice_id: str, key: str) -> Path:
    return prompts_root() / f"{voice_id}__{key[:24]}.pt"


# --------------------------------------------------------------------------- #
# Reference status and the one question callers ask
# --------------------------------------------------------------------------- #
def reference_status(voice: OmniVoiceVoice) -> tuple[bool, str]:
    """The voice's own recording is present and is the approved one, and the reference list holding it is intact."""
    path = reference_path(voice)
    if not path.is_file():
        return False, (f"Setup required for {voice.label}: its reference recording '{path.name}' is not present on this "
                       "computer. This voice is unavailable here; every other voice is unaffected.")
    try:
        spec = reference_spec(voice.voice_id)
    except OmniVoiceUnavailable as exc:
        return False, f"Setup required for {voice.label}: {exc}"
    if _qwen3.sha256_file(path) != spec.wav_sha256:
        return False, (f"The reference recording '{path.name}' does not match the one {voice.label} was approved "
                       "against, so it will not be used. Restore the original file to use this voice.")
    return True, "ok"


def voice_availability(voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` -- can this OmniVoice voice run right now? Cheap, never raises, never touches the network.

    Order: the platform, the GPU (installing cannot help a computer without one), the environment, the model, then the
    voice's own approved recording and transcript. Every reason names the single next step.
    """
    try:
        voice = get_voice(voice_id)
    except OmniVoiceUnavailable as exc:
        return False, str(exc)
    if not platform_supported():
        return False, platform_reason()
    try:
        if detect_gpu() is None:
            return False, NO_GPU_MESSAGE
        for check in (environment_status, model_status):
            ok, reason = check()
            if not ok:
                return False, reason
        return reference_status(voice)
    except Exception as exc:  # noqa: BLE001 - report it, never crash a panel
        return False, f"This voice could not be checked on this computer ({exc})."


def install_would_help(voice_id: Optional[str] = None) -> bool:
    """Whether installing the component could make an unavailable OmniVoice voice usable (Install & Continue).

    Never on another platform or a computer without an NVIDIA GPU; never for a voice whose own approved recording is
    missing or changed (installing cannot restore a recording); never through a link (installing cannot remove one);
    and not once the engine and the model are both ready. An unchecked existing engine counts: installing adopts it."""
    if not platform_supported() or detect_gpu() is None:
        return False
    if voice_id is not None:
        try:
            if not reference_status(get_voice(voice_id))[0]:
                return False
        except OmniVoiceUnavailable:
            return False
    assessment = assess_engine()
    if assessment.state == ENGINE_UNVERIFIED or model_folder_problem():
        return False
    if assessment.state != ENGINE_READY and install_depth_problem():
        return False  # the app's folder is too deep for this engine: installing cannot help until it is moved
    return not (assessment.state == ENGINE_READY and model_status()[0])


# --------------------------------------------------------------------------- #
# Locks: this installation's files, and one OmniVoice model on the GPU per computer
# --------------------------------------------------------------------------- #
MACHINE_GUARD_NAME = "AudiobookCreationTool-OmniVoice-ModelGuard-v1"
MACHINE_BUSY_MESSAGE = ("Another copy of this app (possibly another Windows user's) is running an OmniVoice conversion "
                        "right now, and only one can use the model at a time. Try again when it has finished.")
MACHINE_DENIED_MESSAGE = ("Windows did not give this user permission to open the lock that keeps copies of this app from "
                          "loading the OmniVoice model at the same time, so OmniVoice was not started. If no one else is "
                          "using it, restart the computer or ask an administrator.")
BUSY_MESSAGE = ("The OmniVoice voices are being installed or repaired, or another conversion is using them right now. "
                "Try again when that has finished.")


class MachineGuard(_qwen3.MachineGuard):
    """The Qwen3 machine-wide named mutex, under OmniVoice's own name and words (one OmniVoice model per computer)."""

    DENIED_MESSAGE = MACHINE_DENIED_MESSAGE

    def __init__(self) -> None:
        super().__init__(MACHINE_GUARD_NAME)

    @property
    def refusal_message(self) -> str:
        return MACHINE_DENIED_MESSAGE if self.failure == "denied" else MACHINE_BUSY_MESSAGE

    def acquire(self) -> bool:
        try:
            return super().acquire()
        except _qwen3.Qwen3Unavailable as exc:  # the parent's words name Qwen3; the failure itself is the same
            raise OmniVoiceUnavailable("Windows could not take the lock that keeps two copies of this app from loading "
                                       "the OmniVoice model at once, so OmniVoice was not started.") from exc


class inference_lease:
    """Held for a whole conversion: this copy's ``inference.lock`` (an install or repair cannot change the environment
    or model under a running worker) and the machine-wide guard. Both are released when the block ends, by an
    exception too, and by the operating system if the process dies."""

    def __init__(self) -> None:
        self._lock: Optional[_qwen3.FileLock] = None
        self._guard = MachineGuard()

    def __enter__(self) -> "inference_lease":
        ensure_runtime_dir(runtime_dir())
        self._lock = _qwen3.FileLock(inference_lock_path())
        if not self._lock.acquire():
            raise OmniVoiceUnavailable(BUSY_MESSAGE)
        try:
            if not self._guard.acquire():
                raise OmniVoiceUnavailable(self._guard.refusal_message)
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._guard.release()
        finally:
            if self._lock is not None:
                self._lock.release()


# --------------------------------------------------------------------------- #
# The worker's environment
# --------------------------------------------------------------------------- #
#: Removed from the worker's environment: nothing the app was started with may steer which Python runs, what it
#: imports, or where (or whether) the Hub, Transformers, Torch or pip look for anything.
_DROPPED_PREFIXES = ("PYTHON", "PIP_", "HF_", "HUGGINGFACE_", "TRANSFORMERS_", "TORCH_")
_DROPPED_NAMES = frozenset({"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__", "CONDA_PREFIX",
                            "CONDA_DEFAULT_ENV", "CONDA_PYTHON_EXE", "CONDA_EXE", "CONDA_SHLVL", "CONDA_PROMPT_MODIFIER",
                            "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "NUMBA_CACHE_DIR"})
#: The worker refuses to start unless these are exactly so: the model and its tokenizer load from local files only.
OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}


def worker_environment(base: Optional[dict] = None) -> dict:
    """Offline, isolated from the app's interpreter settings, every cache inside the runtime folder, ``PATH`` without any
    other Python environment's folders (the app's ``.venv`` and the Qwen3 engine included)."""
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(_DROPPED_PREFIXES) or upper in _DROPPED_NAMES:
            del env[name]
        elif upper == "PATH":
            env[name] = _qwen3.scrubbed_path(env[name], venv_dir())
    cache, scratch = cache_root(), ensure_runtime_dir(tmp_root())
    for name in ("hf", "torch", "numba", "xdg"):
        ensure_runtime_dir(cache / name)
    env.update({
        "TEMP": str(scratch), "TMP": str(scratch), "TMPDIR": str(scratch),
        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "HF_HOME": str(cache / "hf"), "HF_HUB_CACHE": str(cache / "hf" / "hub"), **OFFLINE,
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1",
        "TORCH_HOME": str(cache / "torch"), "NUMBA_CACHE_DIR": str(cache / "numba"),
        "XDG_CACHE_HOME": str(cache / "xdg"), "XDG_CONFIG_HOME": str(cache / "xdg"),
        "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    })
    return env
