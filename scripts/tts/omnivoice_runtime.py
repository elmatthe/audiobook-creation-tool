"""omnivoice_runtime.py — what the six OmniVoice voices need on this computer, and whether it is there.

OmniVoice 0.2.1 needs ``transformers>=5.3.0``, which neither the app's ``.venv`` nor the Qwen3 engine can hold, so it runs
in its own independent environment inside a supervised worker process (``omnivoice_worker.py``); ``omnivoice_synth.py``
is the application-side half. This module only *asks questions*: where things live, whether they are present and
intact, and what a person should be told when they are not. It imports nothing heavy (no numpy, torch or OmniVoice),
never downloads, and never raises for a missing asset -- a missing asset is a status with a sentence fit for a
non-technical user.

**Where the environment is (v0.8.2 Phase 5B, approved A1).** New installs go to ``.venv-engines/omnivoice``
(:func:`engine_venv_dir`), an independent environment beside the app's ``.venv``, built by uv on this copy's managed
CPython 3.12.15 from the engine's locked project ``scripts/tts/engines/omnivoice`` (``shared.engine_env`` through
``shared.uv_runner``; ``tts.omnivoice_setup``). From v0.8.0 to v0.8.1 the engine lived inside the app's ``.venv``, at
``.venv/engines/omnivoice`` (:func:`nested_venv_dir`, pip-built from the base Python, carried through the parent's
repairs by ``shared.venv_layout``/``shared.engine_lease``): such an engine keeps working, untouched, until a new one has
been installed and proved, and is then moved whole to ``files/runtime-data/omnivoice/set-aside/`` (never deleted).
:func:`venv_dir` names the engine in use. The earlier sibling ``.venv-omnivoice`` (:func:`legacy_venv_dir`) is only
*recognised* (:func:`assess_legacy`): never a runtime target, never adopted and never moved to a new path -- a Windows
environment cannot be relocated -- and retired, whole, once a new engine is proved
(``tts.omnivoice_setup.retire_legacy``). Each place has its own receipt file (:func:`receipt_path`,
:func:`nested_receipt_path`, :func:`legacy_receipt_path`), so a receipt can never vouch for another place's engine.

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

**Platforms (macOS P4B).** Windows runs the engine exactly as released: an NVIDIA GPU, CUDA, float16, the 88 packages
of the Windows set (torch 2.8.0+cu128). An Apple Silicon Mac runs the same pinned engine and model in the configurations
the owner accepted after the P4A experiment (Decisions, 2026-11-16): the Apple GPU (MPS) in float32 by default, or the
CPU in float32 when ``config.toml`` says so (``[tts] omnivoice_device = "cpu"``); MPS float16 is never offered. Its
packages are the ``darwin_arm64`` set (the same upstream lock, 86 PyPI wheels). Both sets are one ``uv.lock`` since
v0.8.2 Phase 5B; ``omnivoice_packages.json`` keeps the v0.8.1 lists as its parity reference and download sizes, and
``omnivoice_manifest.json`` holds the model and its licences only. :func:`device_policy` is the one answer to "which
device and dtype", and nothing ever falls back from one device to another on its own.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform as host_platform
import re
import stat
import sys
import tempfile
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
    """The application's own environment, ``.venv`` (which held the engine from v0.8.0 to v0.8.1)."""
    return repo_root() / ".venv"


#: The engine's key in the engine registry (``tts.engines.registry``) and ``shared.engine_env``.
ENGINE_KEY = "omnivoice"


def engine_venv_dir() -> Path:
    """``.venv-engines/omnivoice`` (v0.8.2 Phase 5B, approved A1): where the engine is installed, always, by uv. An
    independent environment beside the app's ``.venv``, never inside it."""
    return repo_root().joinpath(*venv_layout.ENGINE_OMNIVOICE.split("/"))


def project_dir() -> Path:
    """``scripts/tts/engines/omnivoice``: the engine's dependency project (``pyproject.toml`` + ``uv.lock``)."""
    from tts.engines import registry

    return repo_root().joinpath(*registry.OMNIVOICE.project.split("/"))


def nested_venv_dir() -> Path:
    """``.venv/engines/omnivoice``: where v0.8.0 to v0.8.1 installed the engine (pip, inside the app's ``.venv``). Used
    while no newer engine is installed; never installed into by this version's installer. Once a new engine has passed
    its checks it is moved, whole, to ``files/runtime-data/omnivoice/set-aside/`` (kept for the owner to delete)."""
    return repo_root().joinpath(*venv_layout.NESTED_OMNIVOICE.split("/"))


def legacy_venv_dir() -> Path:
    """``.venv-omnivoice``: where the first v0.8.0 development builds installed the engine. Never used, never installed
    into, never deleted; only recognised (:func:`assess_legacy`) and, once a new engine is proved, retired."""
    return repo_root() / venv_layout.LEGACY_OMNIVOICE


def engine_installed() -> bool:
    """Whether the receipt says ``.venv-engines/omnivoice`` finished installing (its last step, after every check)."""
    return read_receipt().get("stage") == STAGE_INSTALLED


def venv_dir() -> Path:
    """The engine environment the app uses.

    * ``.venv-engines/omnivoice`` once its install has finished (its receipt says so) -- whatever state it is in later,
      so a damaged engine is reported as damaged instead of being hidden behind an older one -- and whenever no earlier
      engine is at ``.venv/engines/omnivoice``;
    * otherwise that earlier engine: a working engine keeps working while its replacement is being built, and when that
      build fails or is interrupted.

    The sibling ``.venv-omnivoice`` is never chosen."""
    canonical, nested = engine_venv_dir(), nested_venv_dir()
    try:
        earlier = os.path.lexists(nested)
        present = os.path.lexists(canonical)
    except OSError:
        return canonical
    if not earlier or (present and engine_installed()):
        return canonical
    return nested


def is_canonical(folder: Optional[Path] = None) -> bool:
    """Whether *folder* (default: the one in use) is the engine's own place, ``.venv-engines/omnivoice``."""
    return venv_layout.same_path(venv_dir() if folder is None else folder, engine_venv_dir())


def judges_nested() -> bool:
    """Whether :func:`assess_install` is judging an earlier nested engine: one is in use and nothing of this version's
    own (no folder, no receipt) is in ``.venv-engines/omnivoice`` yet."""
    return not is_canonical() and _assess_canonical().state == ENGINE_ABSENT


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
    """``.venv-engines/omnivoice``'s install receipt (version 3, v0.8.2 Phase 5B): ``creating`` before the environment
    is made, ``installed`` only after the installer proved it (and the model) work, ``rejected`` once proved not to.
    Outside the environment, so an interrupted build is always known to be this app's own."""
    return runtime_dir() / "uv-engine-receipt.json"


def nested_receipt_path() -> Path:
    """The receipt v0.8.0 to v0.8.1 wrote for the nested engine ``.venv/engines/omnivoice`` (version 2). Read to judge
    that engine while it is still the one in use; written only to record that it was proved broken."""
    return runtime_dir() / "engine-receipt.json"


def legacy_receipt_path() -> Path:
    """The receipt the earlier sibling ``.venv-omnivoice`` was recorded with (receipt version 1). Only ever read, to say
    what that folder was; it is retired together with the folder and never vouches for the nested engine."""
    return runtime_dir() / "install-receipt.json"


def wheel_cache_dir() -> Path:
    """Where the v0.8.0-v0.8.1 installer kept its verified wheels while it installed. Not used since v0.8.2 Phase 5B
    (uv downloads the locked packages itself, keeping none); a leftover of an interrupted earlier install is removed once
    a new engine is proved (``tts.omnivoice_setup.discard_wheels``)."""
    return runtime_dir() / "cache" / "wheels"


def set_aside_root() -> Path:
    """Where a repair moves an environment it replaces, and where a retired ``.venv-omnivoice`` is kept -- never
    deleted, for the owner to remove. Nothing is ever run from here: an environment moved off its own path is not an
    environment any more (``venv_layout.assess_child``)."""
    return runtime_dir() / "set-aside"


def worker_script() -> Path:
    return Path(__file__).resolve().with_name("omnivoice_worker.py")


def manifest_path() -> Path:
    """The model-integrity manifest: the engine version, the pinned model snapshot and its licences."""
    return Path(__file__).resolve().with_name("omnivoice_manifest.json")


def packages_path() -> Path:
    """The v0.8.1 package sets, kept as ``uv.lock``'s parity reference and for their download sizes (v0.8.2 Phase 5B)."""
    return Path(__file__).resolve().with_name("omnivoice_packages.json")


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


_PACKAGES_CACHE: dict = {}


def _load_validated(path: Path, cache: dict, check: Callable[[object], list[str]]) -> dict:
    try:
        stamp = (path.stat().st_size, path.stat().st_mtime_ns)
        if cache.get("stamp") != stamp:
            data = json.loads(path.read_text(encoding="utf-8"))
            problems = check(data)
            if problems:
                raise OmniVoiceUnavailable(f"The OmniVoice engine list shipped with the app is damaged ({problems[0]}).")
            cache.update(stamp=stamp, data=data)
    except (OSError, ValueError) as exc:
        raise OmniVoiceUnavailable(f"The OmniVoice engine list shipped with the app could not be read ({exc}).") from exc
    return cache["data"]


def load_manifest() -> dict:
    """The model-integrity manifest (``tts/omnivoice_manifest.json``), validated. ``OmniVoiceUnavailable`` if it is not
    usable."""
    return _load_validated(manifest_path(), _MANIFEST_CACHE, manifest_problems)


def load_packages() -> dict:
    """The v0.8.1 package sets (``tts/omnivoice_packages.json``), validated: ``uv.lock``'s parity reference and download
    sizes, and the pinned set an earlier version's engine is judged by. Nothing is installed from it."""
    return _load_validated(packages_path(), _PACKAGES_CACHE, packages_problems)


def manifest_problems(data: object) -> list[str]:
    """Why *data* is not the model-integrity manifest (version 2: the model and its licences, no packages)."""
    problems: list[str] = []
    if not isinstance(data, dict) or data.get("schema") != "act-omnivoice-engine" or data.get("version") != 2:
        return ["not an act-omnivoice-engine manifest, version 2"]
    if any(key in data for key in ("packages", "wheels", DARWIN_SET)):
        problems.append("the model manifest lists packages (they belong in omnivoice_packages.json)")
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
    if (data.get("engine") or {}).get("omnivoice") != "0.2.1":
        problems.append("the engine is not omnivoice 0.2.1")
    if model.get("url_template") != HUB_URL_TEMPLATE:
        problems.append("the model is not fetched from its pinned revision on the Hugging Face Hub")
    return problems


def packages_problems(data: object) -> list[str]:
    """Why *data* is not the package reference: each platform's set exactly pinned, every wheel by name, file, host,
    size and SHA-256 (Windows: PyPI and PyTorch's CUDA 12.8 index; the Mac: PyPI alone)."""
    problems: list[str] = []
    if not isinstance(data, dict) or data.get("schema") != "act-omnivoice-packages" or data.get("version") != 1:
        return ["not an act-omnivoice-packages list, version 1"]
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages or not all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) and x for x in p) for p in packages):
        problems.append("the package set is not a list of [name, version] pins")
    elif len({canonical_name(p[0]) for p in packages}) != len(packages):
        problems.append("a package is pinned twice")
    problems += _wheel_problems(data)
    darwin = data.get(DARWIN_SET)
    if darwin is not None:  # macOS P4B: the Mac's own package set, from PyPI only
        if not isinstance(darwin, dict) or darwin.get("platform") != "macosx_arm64":
            problems.append("the Mac package set is not for macOS arm64")
        else:
            packages = darwin.get("packages")
            if not isinstance(packages, list) or not packages or not all(
                    isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) and x for x in p) for p in packages):
                problems.append("the Mac package set is not a list of [name, version] pins")
            elif len({canonical_name(p[0]) for p in packages}) != len(packages):
                problems.append("a Mac package is pinned twice")
            problems += [f"the Mac package set: {p}" for p in _wheel_problems(darwin, hosts=PYPI_HOSTS)]
    return problems


#: The only form a model file is ever fetched in: the pinned repository at the pinned commit.
HUB_URL_TEMPLATE = "https://huggingface.co/{repo}/resolve/{revision}/{path}"
#: Where a wheel may come from: PyPI's file host, or PyTorch's own index for its CUDA 12.8 builds.
WHEEL_HOSTS = ("https://files.pythonhosted.org/packages/", "https://download-r2.pytorch.org/whl/cu128/")
#: The Mac set comes from PyPI alone: PyTorch's CUDA index has nothing for a Mac and must never be used there.
PYPI_HOSTS = ("https://files.pythonhosted.org/packages/",)
#: The manifest key of the Apple Silicon package set (macOS P4B). The top-level ``packages``/``wheels`` stay Windows'.
DARWIN_SET = "darwin_arm64"
_WHEEL_NAME = re.compile(r"[A-Za-z0-9_.+-]+\.whl")


def _wheel_problems(data: dict, *, hosts: tuple = WHEEL_HOSTS) -> list[str]:
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
                and isinstance(entry.get("url"), str) and entry["url"].startswith(hosts)
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


def package_set() -> dict:
    """The v0.8.1 package set of THIS platform (``omnivoice_packages.json``): its top level on Windows, its
    ``darwin_arm64`` set on a Mac. ``packages`` and ``wheels`` are read from here, never from the other platform's."""
    data = load_packages()
    if _system() == "darwin":
        darwin = data.get(DARWIN_SET)
        if not isinstance(darwin, dict):
            raise OmniVoiceUnavailable("The OmniVoice engine list shipped with the app has no package set for a Mac.")
        return darwin
    return data


def pinned_packages() -> dict[str, str]:
    """``{canonical name: version}`` of this platform's pinned set: what ``uv.lock`` installs here (the parity test
    holds the two equal) and what an engine is judged by, by its folder listing and in the worker's own check."""
    return {canonical_name(name): version for name, version in package_set()["packages"]}


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str


def wheels() -> tuple[Wheel, ...]:
    """The pinned wheels of the environment on this platform (88 on Windows, 86 on a Mac), in list order. uv installs
    exactly these files from the lock; their sizes are the download a person is shown (``uv.lock`` records none for the
    PyTorch index's wheels)."""
    return tuple(Wheel(w["name"], w["version"], w["filename"], w["url"], w["size"], w["sha256"])
                 for w in package_set()["wheels"])


def wheels_total_bytes() -> int:
    """What installing the engine downloads on this platform: every pinned wheel (no package cache is kept)."""
    return sum(w.size for w in wheels())


#: The v0.8.0-v0.8.1 installer's record of the wheels it verified (removed with them, ``omnivoice_setup.discard_wheels``).
WHEEL_RECORD_NAME = "verified.json"


def regular_file_stat(path: Path) -> Optional[os.stat_result]:
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def packages_sha256() -> str:
    """The identity of the v0.8.1 pinned package set: every wheel's name, version, file name, size and SHA-256. What a
    nested engine's (version 2) receipt was bound to; unchanged by the move of the list to its own file."""
    rows = [[w.name, w.version, w.filename, w.size, w.sha256] for w in wheels()]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def lock_identity() -> Optional[dict]:
    """The engine project's definition and lock (line endings normalised): what a new engine's receipts are bound to,
    and the engine unit's source (``shared.engine_env.lock_identity``). ``None`` when either file is missing."""
    from shared import engine_env

    return engine_env.lock_identity(repo_root(), ENGINE_KEY)


def model_total_bytes() -> int:
    return sum(f["size"] for f in model_spec()["files"].values())


def model_url(name: str) -> str:
    spec = model_spec()
    return spec["url_template"].format(repo=spec["repo"], revision=spec["revision"], path=name)


#: The environment once built from the 88 wheels, measured on HOME-PC (2026-11-13): an estimate, never a promise.
ENGINE_INSTALLED_BYTES_FALLBACK = 8_346_271_361


def engine_installed_bytes() -> int:
    """The environment's size on disk once installed (measured; an estimate, never a promise)."""
    try:
        value = (package_set().get("installed_bytes") or {}).get("environment")
    except OmniVoiceUnavailable:
        value = None
    return value if type(value) is int and value > 0 else ENGINE_INSTALLED_BYTES_FALLBACK


def install_temp_bytes() -> int:
    """The extra space an install needs while it runs (v0.8.2 Phase 5B): uv unpacks every downloaded package in its own
    temporary folder (``files/runtime-data/uv/t``) before copying it into the environment, so about the environment's
    own size is needed twice until the install ends."""
    return engine_installed_bytes()


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
#: The same promise for an Apple Silicon Mac (macOS P4B), from the P4A measurements on the one Mac it was qualified on
#: (Decisions, 2026-11-16 P4A results: wall RTF 0.914-1.190 and a 9.54 GiB peak on MPS; 1.31-1.66 and 4.05 GiB on the
#: CPU). Never a promise for another Mac.
MAC_HARDWARE_DISCLOSURE = (
    "On a Mac, OmniVoice needs Apple Silicon (M1 or later). It runs on the Mac's GPU (Metal, float32), or on its "
    "processor (float32) if you choose that in config.toml ([tts] omnivoice_device = \"cpu\"); it never switches "
    "between them on its own. It was qualified on one Mac, an Apple M4 Pro with 24 GB of memory: narration took about "
    "0.9 to 1.2 times as long as the audio on the GPU (using up to about 10 GB of memory) and about 1.3 to 1.7 times "
    "as long on the processor (about 4.5 GB). Its speed and memory use on other Macs are not promised.")


def hardware_disclosure() -> str:
    """The hardware sentence for this platform: Windows' as released, the Mac's on an Apple Silicon Mac."""
    return MAC_HARDWARE_DISCLOSURE if _system() == "darwin" else HARDWARE_DISCLOSURE


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
            "documents": license_documents(), "hardware": hardware_disclosure()}


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
def _system() -> str:
    """``sys.platform``, asked through one seam so a test can ask every question as Windows or as a Mac."""
    return sys.platform


def _machine() -> str:
    """The processor architecture this interpreter runs as (``arm64`` natively on Apple Silicon, ``x86_64`` under
    Rosetta, where the Mac wheels would not load)."""
    return host_platform.machine().lower()


def platform_supported() -> bool:
    """Windows, qualified on Windows 11 x64 with an NVIDIA GPU (v0.8.0); and, since macOS P4B, a Mac with Apple Silicon
    running this interpreter natively (P4A owner-accepted, 2026-11-16). Nothing else."""
    system = _system()
    return system == "win32" or (system == "darwin" and _machine() == "arm64")


def platform_reason() -> str:
    return ("The OmniVoice voices are not available on this platform. They need Windows with an NVIDIA graphics card, "
            "or a Mac with Apple Silicon; every other voice works as before.")


_APPLE_GPU_CACHE: dict = {}


def _sysctl(name: str, kind: str):
    """One ``sysctlbyname`` value (``kind`` ``"int"`` or ``"text"``), or ``None``. macOS only; stdlib ctypes."""
    import ctypes
    import ctypes.util

    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        size = ctypes.c_size_t(0)
        if libc.sysctlbyname(name.encode(), None, ctypes.byref(size), None, 0) != 0 or not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctlbyname(name.encode(), buffer, ctypes.byref(size), None, 0) != 0:
            return None
        if kind == "text":
            return buffer.raw[:size.value].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        return int.from_bytes(buffer.raw[:size.value], sys.byteorder)
    except (OSError, AttributeError, ValueError):
        return None


def apple_gpu(refresh: bool = False) -> Optional["_qwen3.GpuInfo"]:
    """This Mac's Apple Silicon chip as a GPU description (its name, and its unified memory, which the GPU shares), or
    ``None`` when it is not Apple Silicon. Read from ``sysctl``; nothing is loaded and no process is started. Whether
    PyTorch can really use the GPU (MPS) is proved by the engine itself, which never falls back to the CPU."""
    if refresh or "gpu" not in _APPLE_GPU_CACHE:
        found = None
        if _sysctl("hw.optional.arm64", "int") == 1:
            name = _sysctl("machdep.cpu.brand_string", "text") or "Apple Silicon"
            memory = _sysctl("hw.memsize", "int") or 0
            found = _qwen3.GpuInfo(name, memory // 2**20)
        _APPLE_GPU_CACHE["gpu"] = found
    return _APPLE_GPU_CACHE["gpu"]


def detect_gpu() -> Optional["_qwen3.GpuInfo"]:
    """The GPU OmniVoice can use here, or ``None``: on Windows the first NVIDIA GPU the driver reports (asked once per
    process; the Qwen3 probe, shared); on a Mac its Apple Silicon chip (:func:`apple_gpu`)."""
    if _system() == "darwin":
        return apple_gpu()
    return _qwen3.detect_gpu()


NO_GPU_MESSAGE = ("The OmniVoice voices need an NVIDIA graphics card (GPU) with a current driver, and none was found on "
                  "this computer. They were not qualified to run on the processor alone. Every other voice is "
                  "unaffected.")
MAC_NO_GPU_MESSAGE = ("The OmniVoice voices need a Mac with Apple Silicon (M1 or later), and this Mac does not report "
                      "one. Every other voice is unaffected.")
#: The engine found the Mac's GPU unusable when it was asked to run there. Never answered by a silent switch to the CPU.
MPS_UNAVAILABLE_MESSAGE = ("PyTorch reports that this Mac's GPU (Metal) cannot be used right now, so OmniVoice did not "
                           "start; it never moves to the processor on its own. Restart the Mac and try again, or choose "
                           "the processor for OmniVoice in config.toml ([tts] omnivoice_device = \"cpu\"). Every other "
                           "voice is unaffected.")


def no_gpu_message() -> str:
    """What to say when the GPU this platform's OmniVoice needs is not there."""
    return MAC_NO_GPU_MESSAGE if _system() == "darwin" else NO_GPU_MESSAGE


# --------------------------------------------------------------------------- #
# Device and dtype: one answer per platform (macOS P4B)
# --------------------------------------------------------------------------- #
DEVICE_CUDA, DEVICE_MPS, DEVICE_CPU = "cuda", "mps", "cpu"
#: Windows, exactly as released (v0.8.0): the NVIDIA GPU in float16.
WINDOWS_DEVICE, WINDOWS_DTYPE = DEVICE_CUDA, "float16"
#: The configurations the owner accepted for an Apple Silicon Mac after P4A (2026-11-16): the Apple GPU (MPS) in
#: float32 -- preferred, the default -- and the CPU in float32 by explicit choice. MPS float16 was a bounded experiment
#: only and is never offered (a job asking for it is refused by the worker).
MAC_DEVICES = (DEVICE_MPS, DEVICE_CPU)
MAC_DEFAULT_DEVICE = DEVICE_MPS
MAC_DTYPE = "float32"
#: The ``config.toml`` key that chooses the Mac's device (``shared.config``); ignored on Windows.
DEVICE_SETTING = "tts.omnivoice_device"


@dataclass(frozen=True)
class DevicePolicy:
    """Where one OmniVoice run executes and in which precision, and where that choice came from."""
    device: str  # "cuda" | "mps" | "cpu"
    dtype: str  # "float16" (Windows) | "float32" (a Mac)
    source: str  # "windows", or the config layer that chose the Mac's device ("default", "config.toml", ...)

    @property
    def label(self) -> str:
        return {DEVICE_CUDA: "the NVIDIA GPU (CUDA, float16)", DEVICE_MPS: "the Mac's GPU (MPS, float32)",
                DEVICE_CPU: "the processor (CPU, float32)"}.get(self.device, f"{self.device} ({self.dtype})")


def configured_mac_device() -> tuple[str, str]:
    """``(device, source)`` the person chose for OmniVoice on a Mac (``[tts] omnivoice_device``), read from the app's
    validated configuration at the moment of asking; the default (MPS) if it cannot be read. An invalid value never
    reaches here: ``shared.config`` reports it and keeps the default."""
    try:
        from shared import config

        effective = config.get_effective()
        device = str(getattr(effective.tts, "omnivoice_device", MAC_DEFAULT_DEVICE))
        return device, effective.source_of(DEVICE_SETTING)
    except Exception:  # noqa: BLE001 - a configuration that cannot be read keeps the accepted default
        return MAC_DEFAULT_DEVICE, "default"


def device_policy(*, system: Optional[str] = None, choice: Optional[str] = None) -> DevicePolicy:
    """The one device and dtype OmniVoice runs with here. Windows: CUDA float16, as released (the Mac setting is
    ignored). A Mac: the accepted device -- *choice*, else the configured one -- always float32. Raises
    ``OmniVoiceUnavailable`` for anything else (never a guess, never a fallback)."""
    system = _system() if system is None else system
    if system != "darwin":
        return DevicePolicy(WINDOWS_DEVICE, WINDOWS_DTYPE, "windows")
    device, source = (choice, "caller") if choice is not None else configured_mac_device()
    if device not in MAC_DEVICES:
        raise OmniVoiceUnavailable(f"OmniVoice on a Mac runs only on {' or '.join(MAC_DEVICES)} (float32), not "
                                   f"{device!r}. Check [tts] omnivoice_device in config.toml.")
    return DevicePolicy(device, MAC_DTYPE, source)
INSTALL_ACTION = "Install it from the app's optional voice setup (Install & Continue)"
NOT_INSTALLED_MESSAGE = ("The OmniVoice voice engine is not installed on this computer. " + INSTALL_ACTION
                         + "; every other voice is unaffected.")
UNCHECKED_MESSAGE = ("An OmniVoice voice engine is on this computer, but this version of the app has not checked it "
                     "yet, so it is not used. Install & Continue checks it and adopts it; nothing is downloaded or "
                     "replaced when it is complete.")
INCOMPLETE_MESSAGE = "The OmniVoice voice engine was not installed completely. " + INSTALL_ACTION + " to repair it."
#: An engine at the v0.8.0-v0.8.1 place that no receipt of that version vouches for: this version never adopts one there.
NESTED_UNPROVED_MESSAGE = ("The OmniVoice voice engine in .venv\\engines\\omnivoice was never checked by this app, so it is "
                           "not used. " + INSTALL_ACTION + ": a new engine is built in .venv-engines\\omnivoice and "
                           "checked; the old folder is then moved to files\\runtime-data\\omnivoice\\set-aside -- kept, "
                           "never deleted.")
LINKED_MESSAGE = ("The OmniVoice environment is reached through a link to another folder, so the app will not use it. "
                  "Remove the link (not its target).")
#: Nothing installed by this version, an earlier environment beside the app's: said instead of "not installed", because
#: the person did install it. Installing builds it again where it now belongs; nothing of the old one is reused or
#: deleted.
LEGACY_MOVE_MESSAGE = ("The OmniVoice voice engine on this computer is in a folder this version of the app no longer "
                       "uses (.venv-omnivoice). " + INSTALL_ACTION + ": it is built again in its own environment "
                       "(.venv-engines\\omnivoice) from its locked packages and checked there; a model that is already on "
                       "this computer is reused. Only once the new engine works is the old folder moved to "
                       "files\\runtime-data\\omnivoice\\set-aside -- kept, never deleted.")
#: Appended when the engine in use is present but not usable and the earlier sibling is still there: it is said, never
#: silently preferred and never silently ignored.
LEGACY_NOT_USED_NOTE = (" (The earlier environment in .venv-omnivoice is not used in its place; it is kept as it is "
                        "until the new one works.)")
#: A sibling still beside an engine that is ready (it could not be moved when the engine was proved, or it was put
#: back by hand). It promises only what is true: nothing moves it while the engine stays ready -- the acquirer runs
#: only when something has to be installed or repaired, and tries the move again then.
LEGACY_LEFTOVER_NOTE = ("The earlier OmniVoice environment in .venv-omnivoice is no longer used by the app and is still "
                        "in the app's folder (about 8 GB). You may move or delete that folder yourself; the app will "
                        "not use it, and moves it to files\\runtime-data\\omnivoice\\set-aside itself only if "
                        "OmniVoice ever has to be installed or repaired again.")
#: The v0.8.0-v0.8.1 engine inside .venv still there beside a new engine that is ready (it could not be moved aside when
#: the new one was proved: a file in it was open). Same promise as above.
NESTED_LEFTOVER_NOTE = ("The earlier OmniVoice environment in .venv\\engines\\omnivoice is no longer used by the app (the "
                        "engine now lives in .venv-engines\\omnivoice) and is still in the app's folder (about 8 GB). "
                        "The app moves it to files\\runtime-data\\omnivoice\\set-aside the next time OmniVoice is "
                        "installed or repaired; it never deletes it.")


# --------------------------------------------------------------------------- #
# How deep the app's folder may be for this engine (Windows path limits)
# --------------------------------------------------------------------------- #
#: The longest path Windows' loader accepts for a native library, long-path support or not.
WINDOWS_MAX_PATH = 259
#: The deepest native library (.dll/.pyd) of the engine's environment, below the app's folder with its separator (135 +
#: 1: scikit-learn's deepest extension; measured on HOME-PC 2026-11-13 at ``.venv/engines/omnivoice``, whose name is
#: exactly as long as ``.venv-engines/omnivoice``'s, v0.8.2 Phase 5B), plus a margin.
DEEPEST_NATIVE_LIBRARY_CHARS = 140
#: The deepest file of any kind there (168 + 1) plus a margin: the limit for every file while Windows long-path
#: support is off, when the installer could not even write it. (uv's own temporary download folder under
#: ``files/runtime-data/uv/t`` is deeper, but only uv, which switches to long paths by itself, touches it: the rule
#: ``shared.bootstrap`` applies to the repair cache.)
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

    The engine's environment (``.venv-engines/omnivoice``) sits deeper than the app's own and needs a shorter app folder
    than ``bootstrap.install_path_problem`` asks for. Checked before anything is downloaded,
    so a too-deep copy is told once, plainly, instead of getting an engine whose libraries Windows refuses to load.
    Only this engine's install is refused; the app and every other voice are unaffected."""
    if sys.platform != "win32":
        return ""
    root = Path(repo_root() if root is None else root)
    # Imported here, not at the top: this module is on the pre-venv planning path, which must stay free of process and
    # thread modules (test_optional_tts_setup), and shared.long_paths brings both. The pre-venv estimate never asks
    # for a depth; whoever does is past that point.
    from shared.long_paths import windows_length

    length = windows_length(str(root))  # UTF-16 units, as Windows counts (independent review R2)
    enabled = windows_long_paths_enabled() if long_paths is None else long_paths
    limit = WINDOWS_MAX_PATH - (DEEPEST_NATIVE_LIBRARY_CHARS if enabled else DEEPEST_FILE_CHARS)
    if length <= limit:
        return ""
    with_long_paths = WINDOWS_MAX_PATH - DEEPEST_NATIVE_LIBRARY_CHARS
    other_way = ""
    if not enabled and length <= with_long_paths:
        # Windows long paths are off (or could not be read) and would be enough here. The first-run window offers the
        # change itself (shared.long_paths); everywhere else the person is pointed at the manual way.
        other_way = (" Or switch on Windows long paths (README.md: \"Important: Windows Installation Path Length\"), "
                     f"restart Windows and install OmniVoice again: this folder is then within its limit of "
                     f"{with_long_paths}.")
    return (f"The OmniVoice voice engine cannot be installed in this copy of the app: the app's folder path is "
            f"{length} characters long and OmniVoice needs {limit} or fewer here, or Windows could not load its files. "
            "Nothing was installed. Move the whole app folder somewhere shorter (for example C:\\AudiobookTool), "
            "start it from there, and install OmniVoice again." + other_way + " Every other voice is unaffected.")


# --------------------------------------------------------------------------- #
# The install receipts: what makes an environment this app's own, proved -- one file per place
# --------------------------------------------------------------------------- #
RECEIPT_SCHEMA = "act-omnivoice-install-receipt"
#: Version 3 (v0.8.2 Phase 5B) names ``.venv-engines/omnivoice`` and lives in :func:`receipt_path`; it binds the engine
#: to its project's lock. Version 2 was written for the nested ``.venv/engines/omnivoice`` into
#: :func:`nested_receipt_path`, version 1 for the sibling ``.venv-omnivoice`` into :func:`legacy_receipt_path`. Another
#: file, another version and another path each: no receipt can make another place's engine ready.
RECEIPT_VERSION = 3
NESTED_RECEIPT_VERSION = 2
LEGACY_RECEIPT_VERSION = 1
#: ``creating`` is written before the installer makes the environment and ``created`` once uv made it at its place, so
#: an interruption is known to be the app's own, unfinished; ``installed`` only after a proof succeeded (the only stage
#: that makes the engine ready, and the step after which it is the engine in use); ``rejected`` after an existing
#: environment was checked and proved not to work (so the next plan offers a repair instead of the same check again).
STAGE_CREATING = "creating"
STAGE_CREATED = "created"
STAGE_INSTALLED = "installed"
STAGE_REJECTED = "rejected"
STAGES = (STAGE_CREATING, STAGE_CREATED, STAGE_INSTALLED, STAGE_REJECTED)
ORIGIN_INSTALLED = "installed"  # built by this app's installer from the locked packages
ORIGIN_ADOPTED = "adopted"  # found already holding exactly the locked set, then RECORD-checked and proved the same way


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
    """The receipt for ``.venv-engines/omnivoice``, or ``{}``: absent, unreadable, a link, of another schema or version,
    or written for another folder (a copied or stale receipt never vouches for an environment it was not written for --
    a receipt of an earlier place, or of another copy of the app, least of all)."""
    return _read_receipt_file(receipt_path(), RECEIPT_VERSION, engine_venv_dir())


def read_nested_receipt() -> dict:
    """What the nested engine ``.venv/engines/omnivoice`` was recorded with (version 2), or ``{}``."""
    return _read_receipt_file(nested_receipt_path(), NESTED_RECEIPT_VERSION, nested_venv_dir())


def read_legacy_receipt() -> dict:
    """What the earlier sibling ``.venv-omnivoice`` was recorded with, or ``{}``. Evidence about that folder only."""
    return _read_receipt_file(legacy_receipt_path(), LEGACY_RECEIPT_VERSION, legacy_venv_dir())


def write_receipt(stage: str, **fields) -> dict:
    """Publish ``.venv-engines/omnivoice``'s receipt at *stage* (atomically, never through a link), bound to the engine
    project's current lock."""
    if stage not in STAGES:
        raise ValueError(f"unknown receipt stage {stage!r}")
    record = {"schema": RECEIPT_SCHEMA, "version": RECEIPT_VERSION, "stage": stage,
              "path": os.path.normpath(os.path.abspath(engine_venv_dir())), "lock": lock_identity(),
              "omnivoice": load_manifest()["engine"]["omnivoice"],
              "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    atomic_write_json(receipt_path(), record)
    return record


def write_nested_receipt(stage: str, **fields) -> dict:
    """Publish the nested engine's (version 2) receipt -- since v0.8.2 Phase 5B only ever to record that the engine in
    use there was proved broken (:func:`reject_ready_engine`); nothing is installed there any more."""
    if stage != STAGE_REJECTED:
        raise ValueError("the nested engine is never installed into any more; only its rejection is recorded")
    record = {"schema": RECEIPT_SCHEMA, "version": NESTED_RECEIPT_VERSION, "stage": stage,
              "path": os.path.normpath(os.path.abspath(nested_venv_dir())), "packages_sha256": packages_sha256(),
              "omnivoice": load_manifest()["engine"]["omnivoice"],
              "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    atomic_write_json(nested_receipt_path(), record)
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
#: its memory, the computer's memory -- stage ``memory`` --, the model or the job.)
REBUILD_STAGES = frozenset({"versions", "import"})


def failure_needs_rebuild(terminal: dict) -> bool:
    """Whether a worker's ``failed`` event says the engine's installed files are damaged, so only a rebuild can help.

    Since the v0.8.0 independent review (R1) a conversion's startup imports are classified by the worker itself, as the
    probe's are (``omnivoice_worker.import_failure``): whatever they raise -- ``ImportError``, ``ModuleNotFoundError``,
    or the ``OSError`` with which Windows refuses a damaged native library -- arrives as stage ``import``; running out of
    memory there arrives as stage ``memory`` and condemns nothing. Before that, such a failure reached the worker's
    last-resort handler as stage ``worker`` with the exception's own name first (measured on the real engine:
    ``ImportError: cannot import name 'OmniVoice' from 'omnivoice' (unknown location)``), which is still recognised;
    an ``OSError`` there is not, because outside the imports it can mean anything."""
    message = str(terminal.get("message") or "")
    if APPLICATION_CONTROL_MARK in message:
        return False
    stage = terminal.get("stage")
    return stage in REBUILD_STAGES or (stage == "worker" and message.startswith(("ImportError", "ModuleNotFoundError")))


def reject_ready_engine(reason: str) -> bool:
    """Record that the engine in use, which its receipt calls ready, failed at use in a way only a rebuild can mend.
    True if recorded.

    Found on the real nested engine (2026-11-13): with one package file deleted, the folder listing and the receipt
    still said "ready", every conversion failed, and nothing offered a repair. The conversion that meets such a failure
    (:func:`failure_needs_rebuild`) records it here -- it holds ``inference.lock``, so no installer is changing the
    engine -- and the next look therefore says *broken*, the voices say why, and Install & Continue offers the repair
    (a fresh engine is built in ``.venv-engines/omnivoice`` and proved). Only a READY engine is ever rejected this way;
    never raises. An installed ``.venv-engines/omnivoice`` keeps its ``installed`` stage (it stays the engine in use, so
    a damaged engine is never hidden behind an older one) and gains the rejection."""
    try:
        if is_canonical():
            if _assess_canonical().state != ENGINE_READY:
                return False
            kept = {k: v for k, v in read_receipt().items()
                    if k not in ("schema", "version", "stage", "path", "lock", "omnivoice", "recorded_utc")}
            write_receipt(STAGE_INSTALLED, **{**kept, "rejected": str(reason)[:300], "rejected_at": "conversion"})
            return True
        if _assess_nested().state != ENGINE_READY:
            return False
        write_nested_receipt(STAGE_REJECTED, base=venv_layout.base_identity(nested_venv_dir()), reason=str(reason)[:300],
                             rejected_at="conversion")
        return True
    except (OSError, ValueError, OmniVoiceUnavailable):
        return False


# --------------------------------------------------------------------------- #
# The environment: assessed cheaply (a folder listing and two small files; no process, no import)
# --------------------------------------------------------------------------- #
ENGINE_READY = "ready"  # proved and recorded by this app's installer, unchanged since
ENGINE_ABSENT = "absent"  # nothing installed (whatever is, or is not, at the earlier sibling)
ENGINE_UNCHECKED = "unchecked"  # .venv-engines/omnivoice built by uv here, exactly the pinned set, no receipt vouches
ENGINE_INCOMPLETE = "incomplete"  # this app's own install of it did not finish
ENGINE_BROKEN = "broken"  # present, and provably not the pinned engine (or checked and proved not to work)
ENGINE_UNVERIFIED = "unverified"  # reached through a link, or unreadable: nothing here can vouch for it, or change it
ENGINE_STATES = (ENGINE_READY, ENGINE_ABSENT, ENGINE_UNCHECKED, ENGINE_INCOMPLETE, ENGINE_BROKEN, ENGINE_UNVERIFIED)


@dataclass(frozen=True)
class EngineAssessment:
    state: str
    reason: str  # a sentence fit for a person; "ok" when ready


def engine_identity_problem(folder: Optional[Path] = None) -> str:
    """Why ``.venv-engines/omnivoice`` (or *folder*) is not provably this copy's own uv-built environment on its managed
    CPython, or ``""`` (``shared.engine_env.identity_problem``; the worker's own check is still needed)."""
    from shared import engine_env

    return engine_env.identity_problem(repo_root(), ENGINE_KEY, engine_venv_dir() if folder is None else folder)


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
    """What to say about an earlier environment still present beside an engine that is ready, or ``""``."""
    if assess_legacy().retirable:
        return LEGACY_LEFTOVER_NOTE
    try:
        if is_canonical() and os.path.lexists(nested_venv_dir()):
            return NESTED_LEFTOVER_NOTE
    except OSError:
        pass
    return ""


def assess_engine() -> EngineAssessment:
    """What the engine in use (:func:`venv_dir`) is, from the folder and its receipt alone. Read-only; never raises.

    ``.venv-engines/omnivoice`` is ready only with a receipt of a proved install for this folder and this version's lock,
    this copy's own uv-built environment on its managed CPython, exactly the pinned packages, and a current
    ``shared.engine_env`` receipt inside it (:func:`_assess_canonical`). An earlier nested engine keeps its own v0.8.1
    checks (:func:`_assess_nested`). An earlier sibling ``.venv-omnivoice`` changes the *words* -- it is named, so a
    damaged engine is never quietly preferred over, or hidden behind, a healthy one there -- and never the state.
    """
    assessment = _assess_canonical() if is_canonical() else _assess_nested()
    if assessment.state == ENGINE_READY:
        return assessment
    return _with_sibling(assessment)


def assess_install() -> EngineAssessment:
    """What an install or repair has to do (the planner's and the acquirer's question): the state of
    ``.venv-engines/omnivoice`` -- every install and repair builds or proves the engine there -- except that, while
    nothing is there, an earlier nested engine that is ready needs nothing and one that is not needs a repair."""
    canonical = _assess_canonical()
    if canonical.state != ENGINE_ABSENT or is_canonical():
        return canonical if canonical.state == ENGINE_READY else _with_sibling(canonical)
    earlier = _assess_nested()  # nothing installed by this version, an earlier engine in use
    if earlier.state in (ENGINE_READY, ENGINE_UNVERIFIED):
        return earlier
    return _with_sibling(EngineAssessment(ENGINE_INCOMPLETE if earlier.state == ENGINE_INCOMPLETE else ENGINE_BROKEN,
                                          earlier.reason))


def _with_sibling(assessment: EngineAssessment) -> EngineAssessment:
    try:
        legacy = assess_legacy()
    except Exception:  # noqa: BLE001 - the sibling is commentary; it never stops the engine being judged
        return assessment
    if not legacy.retirable:  # nothing there, or a link or a stray entry this app says nothing about and never touches
        return assessment
    if assessment.state == ENGINE_ABSENT:
        if assessment.reason == NOT_INSTALLED_MESSAGE:
            return EngineAssessment(ENGINE_ABSENT, LEGACY_MOVE_MESSAGE)
        return assessment
    return EngineAssessment(assessment.state, assessment.reason + LEGACY_NOT_USED_NOTE)


def _assess_canonical() -> EngineAssessment:
    """``.venv-engines/omnivoice``: absent, unfinished (this app's own receipt says it was being made), broken, unchecked
    (uv-built here on the managed CPython and exactly the pinned set, but no current receipt: adopted after a RECORD
    check and a proof, never downloaded again), or ready."""
    folder = engine_venv_dir()
    try:
        if venv_layout.unsafe_component(repo_root(), folder) is not None:
            return EngineAssessment(ENGINE_UNVERIFIED, LINKED_MESSAGE)
        if not os.path.lexists(folder):
            return EngineAssessment(ENGINE_ABSENT, install_depth_problem() or NOT_INSTALLED_MESSAGE)
        receipt = read_receipt()
        stage = receipt.get("stage")
        if stage in (STAGE_CREATING, STAGE_CREATED):
            return EngineAssessment(ENGINE_INCOMPLETE, INCOMPLETE_MESSAGE)
        problem = engine_identity_problem(folder)
        if problem:
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment cannot be used: {problem}. "
                                                   + INSTALL_ACTION + " to repair it.")
        listing = listing_problem(folder)
        if listing:
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment does not hold its pinned packages "
                                                   f"({listing}). " + INSTALL_ACTION + " to repair it.")
        same_lock = receipt.get("lock") is not None and receipt.get("lock") == lock_identity()
        why = receipt.get("rejected") if stage == STAGE_INSTALLED else receipt.get("reason")
        if same_lock and (stage == STAGE_REJECTED or (stage == STAGE_INSTALLED and receipt.get("rejected"))):
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment was checked and does not work "
                                                   f"({str(why or 'it did not start')[:300]}). " + INSTALL_ACTION
                                                   + " to repair it.")
        if same_lock and stage == STAGE_INSTALLED and receipt.get("probe_ok") is True:
            from shared import engine_env

            problem = engine_env.receipt_problem(repo_root(), ENGINE_KEY)
            if problem:
                return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice voice engine's installation cannot be confirmed "
                                                       f"({problem}). " + INSTALL_ACTION + " to repair it.")
            return EngineAssessment(ENGINE_READY, "ok")
        return EngineAssessment(ENGINE_UNCHECKED, UNCHECKED_MESSAGE)
    except OmniVoiceUnavailable as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, str(exc))
    except OSError as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, f"The OmniVoice environment could not be read ({exc.strerror or exc}).")


def _assess_nested() -> EngineAssessment:
    """The v0.8.0-v0.8.1 engine at ``.venv/engines/omnivoice``, judged as v0.8.1 judged it: ready only with its own
    (version 2) receipt of a proved install for this folder, the pinned set and the base Python it is still built from.
    It is never adopted or installed into any more: anything else there is unfinished or broken, and a repair builds a
    new engine in ``.venv-engines/omnivoice``."""
    folder = nested_venv_dir()
    try:
        if venv_layout.unsafe_component(repo_root(), folder) is not None:
            return EngineAssessment(ENGINE_UNVERIFIED, LINKED_MESSAGE)
        if not os.path.lexists(folder):
            return EngineAssessment(ENGINE_ABSENT, install_depth_problem() or NOT_INSTALLED_MESSAGE)
        receipt = read_nested_receipt()
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
        same = receipt.get("packages_sha256") == packages_sha256() and \
            receipt.get("base") == venv_layout.base_identity(folder)
        if stage == STAGE_INSTALLED and receipt.get("probe_ok") is True and same:
            return EngineAssessment(ENGINE_READY, "ok")
        if stage == STAGE_REJECTED and same:
            why = str(receipt.get("reason") or "it did not start")[:300]
            return EngineAssessment(ENGINE_BROKEN, f"The OmniVoice environment was checked and does not work ({why}). "
                                                   + INSTALL_ACTION + " to repair it.")
        return EngineAssessment(ENGINE_BROKEN, NESTED_UNPROVED_MESSAGE)
    except OmniVoiceUnavailable as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, str(exc))
    except OSError as exc:
        return EngineAssessment(ENGINE_UNVERIFIED, f"The OmniVoice environment could not be read ({exc.strerror or exc}).")


def environment_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the engine in use: ready only when this app's installer proved it and recorded that proof
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
                    dtype: str, device: Optional[str] = None) -> tuple[str, dict]:
    """The key a reusable clone prompt is filed under: every input that shapes it, so any change misses the cache.

    Bound: the recording's SHA-256, its frame count and rate, the preprocessing version, the transcript's SHA-256, the
    model revision, the engine version, the prompt format, the prompt preprocessing flag and the dtype the tokenizer ran
    in. A changed recording or transcript therefore never reuses a prompt made from the old one.

    macOS P4B: the device the prompt was made on is bound too, so a prompt made on the Mac's GPU, its CPU or a CUDA GPU
    is never reused on another (plan section 13 item 6). The CUDA identity is the released one, unchanged: it carries no
    device field (CUDA was the only device), so every Windows prompt already cached keeps its key; every other device
    adds the field, so it can never collide with a CUDA prompt.
    """
    fields = {
        "schema": PROMPT_IDENTITY_SCHEMA, "voice_id": spec.voice_id, "wav_sha256": spec.wav_sha256,
        "reference": [spec.frames, spec.sample_rate], "preprocessing_version": PREPROCESSING_VERSION,
        "text_sha256": spec.text_sha256, "model_revision": model_revision, "omnivoice": omnivoice_version,
        "prompt_format_version": PROMPT_FORMAT_VERSION, "preprocess_prompt": bool(preprocess_prompt), "dtype": dtype,
    }
    if device not in (None, DEVICE_CUDA):
        fields["device"] = device
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
            return False, no_gpu_message()
        device_policy()  # a Mac: the configured device is one the owner accepted (raises with the reason otherwise)
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


MAC_MACHINE_BUSY_MESSAGE = ("Another copy of this app is running an OmniVoice conversion right now, and only one can use "
                            "the model at a time. Try again when it has finished.")
#: macOS P4B (plan section 11.2 and D13): where every copy of the app run by this user finds the one OmniVoice model
#: lock -- the user's own temporary folder as macOS defines it (``confstr(_CS_DARWIN_USER_TEMP_DIR)``), which does not
#: follow a ``TMPDIR`` that a setup worker points elsewhere, so a conversion and an install proof in two copies always
#: meet the same file.
_CS_DARWIN_USER_TEMP_DIR = 65537
MACHINE_LOCK_FOLDER = "ACT-locks"
MACHINE_LOCK_NAME = "omnivoice.lock"


def machine_lock_path() -> Path:
    try:
        base = os.confstr(_CS_DARWIN_USER_TEMP_DIR) if _system() == "darwin" else None
    except (OSError, ValueError):
        base = None
    return Path(base or tempfile.gettempdir()) / MACHINE_LOCK_FOLDER / MACHINE_LOCK_NAME


class MachineGuard(_qwen3.MachineGuard):
    """One OmniVoice model at a time across every copy of the app: on Windows the Qwen3 machine-wide named mutex under
    OmniVoice's own name and words, exactly as released; on a Mac (macOS P4B, D13) an exclusive ``flock`` on
    :func:`machine_lock_path`, which the kernel releases when its holder dies however it dies, so it is never stale.
    Like the mutex it never waits: it is taken at once or refused."""

    DENIED_MESSAGE = MACHINE_DENIED_MESSAGE

    def __init__(self) -> None:
        super().__init__(MACHINE_GUARD_NAME)
        self._fd: Optional[int] = None

    @property
    def refusal_message(self) -> str:
        if _system() == "darwin":
            return MAC_MACHINE_BUSY_MESSAGE
        return MACHINE_DENIED_MESSAGE if self.failure == "denied" else MACHINE_BUSY_MESSAGE

    @property
    def held(self) -> bool:
        return self._fd is not None or super().held

    def acquire(self) -> bool:
        if _system() == "darwin":
            return self._acquire_posix()
        try:
            return super().acquire()
        except _qwen3.Qwen3Unavailable as exc:  # the parent's words name Qwen3; the failure itself is the same
            raise OmniVoiceUnavailable("Windows could not take the lock that keeps two copies of this app from loading "
                                       "the OmniVoice model at once, so OmniVoice was not started.") from exc

    def _acquire_posix(self) -> bool:
        if self._fd is not None:
            return True
        import fcntl

        self.failure = None
        path = machine_lock_path()
        try:
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if path.parent.is_symlink() or not path.parent.is_dir():
                raise OSError(f"{path.parent} is not a plain folder")
            # O_NOFOLLOW: a link planted in the shared folder is never written through; non-inheritable (PEP 446),
            # so no worker or other child ever holds the lock after this process has gone.
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise OmniVoiceUnavailable(f"The lock that keeps two copies of this app from loading the OmniVoice model at "
                                       f"once could not be opened ({exc}), so OmniVoice was not started.") from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            self.failure = "busy"
            return False
        self._fd, self.scope = fd, "user"
        return True

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd, self.scope = self._fd, None, None
            try:
                os.close(fd)  # closing the only descriptor releases the flock
            except OSError:
                pass
            return
        super().release()


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
                            "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "NUMBA_CACHE_DIR",
                            # macOS P4B: an unsupported operation must fail loudly, never run quietly on the CPU, and
                            # the Mac's GPU memory limits are PyTorch's own defaults (the P4A-accepted behaviour). CUDA
                            # reads neither, so Windows runs exactly as before.
                            "PYTORCH_ENABLE_MPS_FALLBACK", "PYTORCH_MPS_HIGH_WATERMARK_RATIO",
                            "PYTORCH_MPS_LOW_WATERMARK_RATIO", "PYTORCH_MPS_PREFER_METAL"})
#: The worker refuses to start unless these are exactly so: the model and its tokenizer load from local files only.
OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}


def worker_environment(base: Optional[dict] = None, own: Optional[Path] = None) -> dict:
    """Offline, isolated from the app's interpreter settings, every cache inside the runtime folder, ``PATH`` without any
    other Python environment's folders (the app's ``.venv`` and the Qwen3 engine included). *own* is the engine the
    worker runs in (default: the one in use; the installer's proof names the new one before it is in use)."""
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(_DROPPED_PREFIXES) or upper in _DROPPED_NAMES:
            del env[name]
        elif upper == "PATH":
            env[name] = _qwen3.scrubbed_path(env[name], venv_dir() if own is None else own)
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
