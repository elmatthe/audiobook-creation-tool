"""qwen3_runtime.py — what the Qwen3-TTS voices need on this computer, and whether it is there.

Qwen3-TTS cannot live in the application's own environment: its package pins ``transformers==4.57.3`` while the
application pins 5.2.0. It therefore runs in a **second, isolated environment** (``.venv-qwen3`` at the repository
root) inside a worker subprocess (``qwen3_worker.py``), one subprocess per source file. This module is the GUI-side
half of that arrangement that only *asks questions*: where things live, whether they are present and intact, and
what a person should be told when they are not. It imports nothing heavy (no torch, no numpy, no network) so it is
safe to call from a GUI build on a machine with nothing installed, and it never raises for a missing asset — a
missing asset is a status, with a sentence fit for a non-technical user.

Owner rulings it implements (``md-instructions/Decisions.md``, 2026-10-19, CP6):

* Q2 — the two models install independently (CustomVoice enables Aiden and Ryan; Base enables the six clones).
* Q3/Q4 — Windows first: CPU fallback is stated honestly, and every other platform reports "not yet available".
* Q8 (v0.7.0 P03C, supersedes the v0.6.7 Q5 local-only rule) — the six owner-approved clone transcripts ship with the
  app as curated data (``tts/data/bundled_clone_transcripts.json``). Narration uses only that verified bundle, bound to
  each registered recording's hash; a local store or ``ACT_QWEN3_TRANSCRIPTS`` never shadows it. The local store is
  maintainer tooling, read only when a caller passes it explicitly.

Nothing here downloads, installs or loads a model. That is ``qwen3_setup.py`` (explicit user action) and
``qwen3_synth.py`` (a conversion run).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# --------------------------------------------------------------------------- #
# Identity of the eight voices
# --------------------------------------------------------------------------- #
#: The voice ids are the owner's (Decision B, 2026-10-19). ``voice_registry`` owns what people see (each voice's label
#: is read from it by stable id, so a renamed row renames every message); this table owns what the engine needs.
KIND_PRESET = "custom_voice"
KIND_CLONE = "clone"

MODEL_CUSTOMVOICE = "customvoice"
MODEL_BASE = "base"
MODEL_KEYS = (MODEL_CUSTOMVOICE, MODEL_BASE)
#: The local speech recognizer that drafts the six clones' reference transcripts once (``tts.qwen3_clone_setup``). It is
#: pinned and verified exactly like the two voice models, but it is not a voice model: it is never installed by "Install
#: Both" and no voice needs it at narration time.
TRANSCRIBER = "transcriber"


@dataclass(frozen=True)
class Qwen3Voice:
    voice_id: str
    kind: str  # KIND_PRESET | KIND_CLONE
    model_key: str  # MODEL_CUSTOMVOICE | MODEL_BASE
    speaker: str = ""  # the model's own preset speaker name (presets only)
    reference_name: str = ""  # stable key of a clone's reference (transcripts are stored under it), e.g. "Female-1"
    reference_sha256: str = ""  # the recording this clone was approved against (clones only)

    @property
    def label(self) -> str:
        """The name shown to people: this voice's *current* registry label (v0.7.0 P02A), looked up when asked.

        Imported here rather than at module level so the registry never depends on an engine module.
        """
        from tts.voice_registry import label_for

        return label_for("qwen3", self.voice_id)


#: Same bytes as ``chatterbox_synth.REFERENCE_VOICES`` (a test pins that they agree). They are repeated here, not
#: imported, because a Qwen clone is independent of its Chatterbox counterpart: it shares only the recording.
QWEN3_VOICES: tuple[Qwen3Voice, ...] = (
    Qwen3Voice("qwen3-aiden", KIND_PRESET, MODEL_CUSTOMVOICE, speaker="Aiden"),
    Qwen3Voice("qwen3-ryan", KIND_PRESET, MODEL_CUSTOMVOICE, speaker="Ryan"),
    Qwen3Voice("qwen3-female-1", KIND_CLONE, MODEL_BASE, reference_name="Female-1",
               reference_sha256="b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4"),
    Qwen3Voice("qwen3-female-2", KIND_CLONE, MODEL_BASE, reference_name="Female-2",
               reference_sha256="428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205"),
    Qwen3Voice("qwen3-male-1", KIND_CLONE, MODEL_BASE, reference_name="Male-1",
               reference_sha256="45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58"),
    Qwen3Voice("qwen3-male-2", KIND_CLONE, MODEL_BASE, reference_name="Male-2",
               reference_sha256="592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355"),
    Qwen3Voice("qwen3-male-3", KIND_CLONE, MODEL_BASE, reference_name="Male-3",
               reference_sha256="4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80"),
    Qwen3Voice("qwen3-male-4", KIND_CLONE, MODEL_BASE, reference_name="Male-4",
               reference_sha256="47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad"),
)
_VOICE_BY_ID = {v.voice_id: v for v in QWEN3_VOICES}


class Qwen3Unavailable(RuntimeError):
    """The Qwen3 engine, a model, or a clone's reference/transcript is not usable right now.

    Always carries a message fit to show a non-technical user. Raised instead of falling back to another voice,
    another engine, another model or a transcript-free clone, so no substituted voice is ever produced.
    """


def get_voice(voice_id: str) -> Qwen3Voice:
    try:
        return _VOICE_BY_ID[voice_id]
    except KeyError:
        raise Qwen3Unavailable(
            f"Unknown Qwen3 voice '{voice_id}'. Known voices: {', '.join(sorted(_VOICE_BY_ID))}.") from None


# --------------------------------------------------------------------------- #
# Locations — everything lives inside the repository tree (AI-WORKSPACE containment)
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    """The folder containing both ``scripts/`` and ``files/``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts").is_dir() and (parent / "files").is_dir():
            return parent
    return Path(__file__).resolve().parents[2]


def runtime_dir() -> Path:
    """``files/runtime-data/qwen3/`` — gitignored scratch: state, cache, job folders, local transcripts."""
    return repo_root() / "files" / "runtime-data" / "qwen3"


def venv_dir() -> Path:
    """The isolated environment. Beside, never inside, the application's own ``.venv``."""
    return repo_root() / ".venv-qwen3"


def venv_python() -> Path:
    sub = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    return venv_dir().joinpath(*sub)


def models_root() -> Path:
    """``files/runtime-data/models/qwen3-tts/`` — a sibling of the Kokoro Hugging Face cache, never inside it."""
    return repo_root() / "files" / "runtime-data" / "models" / "qwen3-tts"


def requirements_path() -> Path:
    return repo_root() / "scripts" / "qwen3-requirements.txt"


def state_path() -> Path:
    return runtime_dir() / "state.json"


def jobs_root() -> Path:
    return runtime_dir() / "jobs"


def cache_root() -> Path:
    return runtime_dir() / "cache"


def tmp_root() -> Path:
    """Scratch space for the worker and the installer, inside the repository tree.

    pip stages a 2.9 GB wheel and builds source packages in the temp folder; left to the system default that lands in the
    user's profile and outlives a crash. Pointing ``TEMP``/``TMP`` here keeps it contained and removable.
    """
    return runtime_dir() / "tmp"


def inference_lock_path() -> Path:
    return runtime_dir() / "inference.lock"


def setup_lock_path() -> Path:
    return runtime_dir() / "setup.lock"


def worker_script() -> Path:
    return Path(__file__).resolve().with_name("qwen3_worker.py")


TRANSCRIPTS_ENV = "ACT_QWEN3_TRANSCRIPTS"


def local_transcripts_path() -> Path:
    return runtime_dir() / "transcripts.json"


def local_store_path() -> Path:
    """The maintainer's local transcript store: the ``ACT_QWEN3_TRANSCRIPTS`` file when set, else the local file.

    Only the maintainer tools write or read it, and only through an explicit ``load_transcript(..., override=...)``;
    narration never reads it (v0.7.0 P03C).
    """
    override = os.environ.get(TRANSCRIPTS_ENV)
    return Path(override) if override else local_transcripts_path()


def bundled_transcripts_path() -> Path:
    """The six reference transcripts shipped with the app (tracked under ``scripts/``, so every archive carries it)."""
    return Path(__file__).resolve().parent / "data" / "bundled_clone_transcripts.json"


def reference_path(voice: Qwen3Voice) -> Path:
    """The ONE bundled copy of the recording, shared with the Chatterbox voice of the same speaker.

    Its folder and file name come from the registry (``REFERENCE_DIRECTORY`` and the explicit reference table, by stable
    id), never from a display label.
    """
    from tts.voice_registry import REFERENCE_DIRECTORY, reference_recording_filename

    return repo_root().joinpath(*REFERENCE_DIRECTORY) / reference_recording_filename("qwen3", voice.voice_id)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def sha256_file(path: Path, progress: Optional[Callable[[int], None]] = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
            if progress is not None:
                progress(len(block))
    return digest.hexdigest()


def format_bytes(count: int) -> str:
    """'4.5 GB' / '686 MB' — decimal units, the way download sizes are normally quoted."""
    if count >= 10**9:
        return f"{count / 10**9:.1f} GB"
    if count >= 10**6:
        return f"{count / 10**6:.0f} MB"
    return f"{max(count, 0) / 10**3:.0f} KB"


def refuse_link(folder: Path) -> None:
    """Refuse a folder that is a link or junction: state, locks and job text must land where the app put them."""
    if is_link(folder):
        raise Qwen3Unavailable(f"The Qwen3 data folder {Path(folder).name!r} is a link to another folder; the app "
                               "refuses to use it. Remove the link (not its target).")


def ensure_runtime_dir(path: Path) -> Path:
    """Create a folder inside the Qwen3 runtime folder, proving neither it nor the runtime folder is a link.

    (The models folder may be a link -- moving the models to another drive is a legitimate choice -- but state, locks,
    job text and scratch are small and local, and a link there could only ever be a redirect.)
    """
    path = Path(path)
    chain = [path]
    try:
        path.relative_to(runtime_dir())
        while chain[-1] != runtime_dir():
            chain.append(chain[-1].parent)  # every folder from here up to the runtime folder
    except ValueError:
        chain.append(runtime_dir())
    for folder in chain:  # nothing is created behind a link that is already there...
        if folder.exists() or folder.is_symlink():
            refuse_link(folder)
    path.mkdir(parents=True, exist_ok=True)
    for folder in chain:  # ...and what was created is checked again
        refuse_link(folder)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    """Publish ``text`` at ``path`` through a fresh temporary file, so a planted link at ``path`` is replaced, not written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    refuse_link(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    remove_entry(tmp)  # a leftover (or planted) link here must never be written through
    try:
        with open(tmp, "x", encoding="utf-8") as handle:  # exclusive create: never opens an existing file or link
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        # The destination is untouched until os.replace succeeds; only this call's own partial file is cleaned up.
        try:
            if tmp.is_file() and not tmp.is_symlink():
                tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True))


def requirements_sha256() -> str:
    """Hash of the pinned requirements, line endings normalised so a CRLF checkout matches an LF one."""
    path = requirements_path()
    if not path.is_file():
        return ""
    text = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()


# --------------------------------------------------------------------------- #
# The pinned model manifest (tracked data: public facts about public Apache-2.0 models)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    repo: str
    revision: str
    license: str
    dir_name: str
    voices: tuple[str, ...]
    files: dict  # relative path -> {"size": int, "sha256": str}

    @property
    def total_bytes(self) -> int:
        return sum(f["size"] for f in self.files.values())

    @property
    def directory(self) -> Path:
        return models_root() / self.dir_name

    def manifest_sha256(self) -> str:
        blob = json.dumps({"repo": self.repo, "revision": self.revision, "files": self.files},
                          sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _manifest_path() -> Path:
    return Path(__file__).resolve().with_name("qwen3_models.json")


_MANIFEST_CACHE: dict = {}


def load_manifest() -> dict:
    path = _manifest_path()
    stamp = (path.stat().st_size, path.stat().st_mtime_ns)
    if _MANIFEST_CACHE.get("stamp") != stamp:
        _MANIFEST_CACHE["stamp"] = stamp
        _MANIFEST_CACHE["data"] = json.loads(path.read_text(encoding="utf-8"))
    return _MANIFEST_CACHE["data"]


_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$")
_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                               *(f"lpt{n}" for n in range(1, 10))})


def check_relative_name(name: object, *, what: str = "file name") -> str:
    """A manifest name that can only ever mean a plain relative path below its own folder.

    Rejects (with the manifest named as the cause): non-strings, empty or oversized names, absolute paths, drive letters,
    backslashes, ``.``/``..``/empty segments, anything outside a conservative character set, Windows device names
    (``con``, ``nul``...), and segments ending in a dot or space (which Windows silently strips, aliasing another file).
    """
    if not isinstance(name, str) or not name or len(name) > 200:
        raise Qwen3Unavailable(f"The Qwen3 model list is invalid: a {what} is missing or too long.")
    if name.startswith("/") or "\\" in name or ":" in name:
        raise Qwen3Unavailable(f"The Qwen3 model list is invalid: {what} {name!r} is not a plain relative path.")
    for part in name.split("/"):
        if part in ("", ".", "..") or not _SEGMENT.match(part) or part != part.rstrip(". ") \
                or part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise Qwen3Unavailable(f"The Qwen3 model list is invalid: {what} {name!r} is not allowed.")
    return name


def _validate_model_entry(key: str, raw: dict) -> None:
    check_relative_name(raw.get("dir"), what="model folder")
    if "/" in raw["dir"]:
        raise Qwen3Unavailable(f"The Qwen3 model list is invalid: model folder {raw['dir']!r} must be one folder name.")
    if not re.fullmatch(r"[0-9a-f]{40}", str(raw.get("revision", ""))):
        raise Qwen3Unavailable("The Qwen3 model list is invalid: a revision is not a commit hash.")
    files = raw.get("files")
    if not isinstance(files, dict) or not files:
        raise Qwen3Unavailable("The Qwen3 model list is invalid: a model has no files.")
    seen: set[str] = set()
    for name, info in files.items():
        check_relative_name(name)
        if name.lower() in seen:
            raise Qwen3Unavailable(f"The Qwen3 model list is invalid: {name!r} appears twice (names differ only by case).")
        seen.add(name.lower())
        if not (isinstance(info, dict) and isinstance(info.get("size"), int) and info["size"] >= 0
                and re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256", "")))):
            raise Qwen3Unavailable(f"The Qwen3 model list is invalid: {name!r} has no valid size and SHA-256.")


def model_spec(key: str) -> ModelSpec:
    if key not in MODEL_KEYS and key != TRANSCRIBER:
        raise Qwen3Unavailable(f"Unknown Qwen3 model '{key}'.")
    raw = load_manifest()["models"][key] if key in MODEL_KEYS else load_manifest()["transcriber"]
    _validate_model_entry(key, raw)
    return ModelSpec(key=key, label=raw["label"], repo=raw["repo"], revision=raw["revision"], license=raw["license"],
                     dir_name=raw["dir"], voices=tuple(raw.get("voices", ())), files=dict(raw["files"]))


def transcriber_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the speech recognizer that drafts the clone transcripts. Cheap: never hashes or loads."""
    spec = model_spec(TRANSCRIBER)
    size = format_bytes(spec.total_bytes)
    marker = marker_path(TRANSCRIBER)
    if not marker.is_file():
        if spec.directory.is_dir():
            return False, f"The speech recognizer ({size}) is only partly installed."
        return False, f"The speech recognizer ({size}) is not installed."
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recorded = None
    if not isinstance(recorded, dict) or recorded.get("manifest_sha256") != spec.manifest_sha256():
        return False, "The speech recognizer is a different or unreadable version; install it again."
    problems = model_file_problems(TRANSCRIBER)
    if problems:
        return False, f"The speech recognizer is damaged ({problems[0]}); install it again."
    return True, "ok"


def is_link(path: Path) -> bool:
    """A symbolic link or (on Windows) a junction: something that can make a path lead somewhere else."""
    try:
        return path.is_symlink() or bool(getattr(os.path, "isjunction", lambda p: False)(path))
    except OSError:
        return True


def remove_entry(path: Path) -> None:
    """Remove a leftover file, or a link itself, without ever following a link (a junction goes as a directory).

    A real directory is refused rather than deleted. Nothing happens if the path does not exist.
    """
    if is_link(path):
        try:
            os.unlink(path)
        except OSError:
            os.rmdir(path)
    elif path.exists():
        path.unlink()


def scratch_is_unsafe(path: Path) -> bool:
    """A leftover scratch file that is a link, or that other names share (a hard link to a file elsewhere).

    Appending to such a file would write through to its target, outside the model folder, so it is never resumed.
    """
    if is_link(path):
        return True
    try:
        return path.is_file() and path.stat().st_nlink > 1
    except OSError:
        return True


def safe_model_path(spec: ModelSpec, name: str) -> Path:
    """The on-disk path of one manifest file, proved to stay inside that model's own folder.

    The manifest names are validated (:func:`check_relative_name`); this adds the filesystem half: no component from the
    model's folder down may be a link, and the resolved path must lie inside the resolved model folder. (The models root
    itself may be a link -- moving the models to another drive is a legitimate choice -- but nothing beneath it may be.)
    """
    check_relative_name(name)
    folder = spec.directory
    current = folder
    for part in ("", *name.split("/")):
        current = current / part if part else current
        if (current.exists() or current.is_symlink()) and is_link(current):
            raise Qwen3Unavailable(f"The Qwen3 model folder contains a link ({current.name}); refusing to use it.")
    candidate = folder.joinpath(*name.split("/"))
    real_folder = os.path.realpath(folder)
    if os.path.commonpath([real_folder, os.path.realpath(candidate)]) != real_folder:
        raise Qwen3Unavailable(f"The Qwen3 model file {name!r} resolves outside its model folder; refusing to use it.")
    return candidate


def shared_file_bytes() -> int:
    """Bytes of files that are identical (same path, size and hash) in both models — downloaded only once."""
    a, b = model_spec(MODEL_CUSTOMVOICE).files, model_spec(MODEL_BASE).files
    return sum(f["size"] for name, f in a.items() if b.get(name) == f)


def environment_download_bytes() -> int:
    return int(load_manifest()["environment"]["approx_download_bytes"])


def environment_installed_bytes() -> int:
    return int(load_manifest()["environment"]["approx_installed_bytes"])


# --------------------------------------------------------------------------- #
# Verified-model marker and file checks
# --------------------------------------------------------------------------- #
MARKER_NAME = "ACT-VERIFIED.json"


def marker_path(key: str) -> Path:
    return model_spec(key).directory / MARKER_NAME


def write_model_marker(key: str) -> None:
    """Record that every file of this model was verified by size and SHA-256 (called by the installer only)."""
    spec = model_spec(key)
    safe_model_path(spec, MARKER_NAME)  # the model folder must not be a link before anything is written into it
    atomic_write_json(marker_path(key), {
        "schema": 1, "model": key, "repo": spec.repo, "revision": spec.revision,
        "manifest_sha256": spec.manifest_sha256(), "files": {n: f["size"] for n, f in spec.files.items()},
        "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


BAD_MISSING, BAD_SIZE, BAD_HASH = "is missing", "has the wrong size", "does not match its expected SHA-256"


def model_bad_files(key: str, *, full: bool = False,
                    progress: Optional[Callable[[int], None]] = None) -> list[tuple[str, str]]:
    """``(file name, what is wrong)`` for every manifest file of a model that is not present and correct.

    Cheap form (default): presence and exact size. ``full=True`` also hashes every file -- minutes for a 4.5 GB model --
    and is reserved for install and repair. A model folder that does not exist reports every file missing.
    """
    spec = model_spec(key)
    if not spec.directory.is_dir():
        return [(name, BAD_MISSING) for name in spec.files]
    bad: list[tuple[str, str]] = []
    for name, want in spec.files.items():
        path = safe_model_path(spec, name)
        if not path.is_file():
            bad.append((name, BAD_MISSING))
        elif path.stat().st_size != want["size"]:
            bad.append((name, BAD_SIZE))
        elif full and sha256_file(path, progress) != want["sha256"]:
            bad.append((name, BAD_HASH))
    return bad


def model_file_problems(key: str, *, full: bool = False,
                        progress: Optional[Callable[[int], None]] = None) -> list[str]:
    """What is wrong with the files of one model, as sentences. ``[]`` means every file is present and correct."""
    spec = model_spec(key)
    if not spec.directory.is_dir():
        return [f"the {spec.label} model folder is missing"]
    return [f"{name} {reason}" for name, reason in model_bad_files(key, full=full, progress=progress)]


def model_status(key: str) -> tuple[bool, str]:
    """``(ok, reason)`` for one model's files. Cheap: never hashes, never loads, never touches the network."""
    spec = model_spec(key)
    marker = marker_path(key)
    if not marker.is_file():
        if spec.directory.is_dir():
            return False, (f"The Qwen3 {spec.label} model ({format_bytes(spec.total_bytes)}) is only partly "
                           "installed. Choose \"Install / repair Qwen3 voices\" to finish or repair it.")
        return False, (f"The Qwen3 {spec.label} model ({format_bytes(spec.total_bytes)}) is not installed. "
                       "Choose \"Install / repair Qwen3 voices\" to install it; nothing is downloaded until you ask.")
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recorded = None
    if not isinstance(recorded, dict):  # unreadable, or valid JSON of the wrong shape (null, a list, a string)
        return False, f"The Qwen3 {spec.label} model's verification record is unreadable. Choose \"Install / repair Qwen3 voices\"."
    if recorded.get("manifest_sha256") != spec.manifest_sha256():
        return False, (f"The installed Qwen3 {spec.label} model is a different version from the one this app "
                       "expects. Choose \"Install / repair Qwen3 voices\" to update it.")
    problems = model_file_problems(key)
    if problems:
        return False, (f"The Qwen3 {spec.label} model is damaged ({problems[0]}). "
                       "Choose \"Install / repair Qwen3 voices\" to repair it.")
    return True, "ok"


# --------------------------------------------------------------------------- #
# Environment (the second venv) state
# --------------------------------------------------------------------------- #
def read_state() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_environment_state(probe: dict) -> None:
    """Record a successful install: the requirements it was built from and what the load probe reported."""
    state = read_state()
    state["schema"] = 1
    state["environment"] = {
        "requirements_sha256": requirements_sha256(), "probe": probe, "probe_ok": True,
        "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_json(state_path(), state)


def clear_environment_state() -> None:
    state = read_state()
    if "environment" in state:
        del state["environment"]
        atomic_write_json(state_path(), state)


def _venv_home_exists() -> bool:
    """A venv is only as good as the interpreter it was created from; ``pyvenv.cfg`` names that interpreter."""
    cfg = venv_dir() / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home":
                return Path(value.strip()).is_dir()
    except OSError:
        return False
    return False


def environment_location_problem() -> str:
    """Why the environment folder cannot be trusted as the app's own, or ``""``.

    ``.venv-qwen3`` must be a real folder inside the repository tree. A link or junction to somewhere else would make
    the installer run pip in, and the worker run code from, an environment this app did not create.
    """
    folder = venv_dir()
    if not (folder.exists() or folder.is_symlink()):
        return ""
    if is_link(folder):
        return (".venv-qwen3 is a link to another folder. Remove the link (not its target) so the app can create its "
                "own environment.")
    real_root = os.path.realpath(repo_root())
    try:
        inside = os.path.commonpath([real_root, os.path.realpath(folder)]) == real_root
    except ValueError:
        inside = False
    return "" if inside else ".venv-qwen3 resolves outside this app's folder; refusing to use it."


def environment_status() -> tuple[bool, str]:
    problem = environment_location_problem()
    if problem:
        return False, f"The Qwen3 voice engine cannot be used: {problem}"
    if not venv_python().is_file():
        return False, (f"The Qwen3 voice engine is not installed on this computer (about "
                       f"{format_bytes(environment_download_bytes())} to download). Choose \"Install / repair "
                       "Qwen3 voices\" to install it; nothing is downloaded until you ask.")
    if not _venv_home_exists():
        return False, ("The Qwen3 voice engine's Python environment is broken (the Python it was built from is "
                       "gone). Choose \"Install / repair Qwen3 voices\" to rebuild it.")
    env = read_state().get("environment") or {}
    if not env.get("probe_ok"):
        return False, ("The Qwen3 voice engine was not installed completely. "
                       "Choose \"Install / repair Qwen3 voices\" to finish it.")
    if env.get("requirements_sha256") != requirements_sha256():
        return False, ("The installed Qwen3 voice engine is out of date for this version of the app. "
                       "Choose \"Install / repair Qwen3 voices\" to update it.")
    return True, "ok"


def installed_probe() -> dict:
    """What the install-time load probe reported (torch/CUDA/device), or ``{}``."""
    return (read_state().get("environment") or {}).get("probe") or {}


# --------------------------------------------------------------------------- #
# Locks that the operating system owns (so a crash can never leave one stale)
# --------------------------------------------------------------------------- #
class FileLock:
    """A non-blocking exclusive lock on a file, held for as long as this object holds it open.

    The operating system drops the lock when the process ends, however it ends, so there is no stale-lock case and no
    process-id bookkeeping. Two holders in the same process conflict too (separate handles), which is what keeps a
    conversion and an install apart even inside one app.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        refuse_link(self.path.parent)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            os.close(fd)


#: The shared name every copy of the app uses for its cross-installation Qwen3 guard (see ``MachineGuard``). Versioned
#: so a future, incompatible guard can never be confused with this one.
MACHINE_GUARD_NAME = "AudiobookCreationTool-Qwen3-ModelGuard-v1"

_WAIT_OBJECT_0, _WAIT_ABANDONED, _WAIT_TIMEOUT = 0x0, 0x80, 0x102
_ERROR_ACCESS_DENIED = 5


class MachineGuard:
    """One heavy Qwen3 model operation at a time across EVERY copy of the app on this computer (audit ACT67-AUD-003).

    ``FileLock`` lives in each installation's own runtime folder, so two extracted copies of the app lock two different
    files and could each load a multi-gigabyte model at once. This guard is a Windows named mutex instead: a kernel
    object every copy finds by name, with no file anywhere. It lives in the ``Global\\`` namespace only -- the whole
    machine, across Windows users and logon sessions (one GPU, one RAM) -- and it **fails closed**: a ``Local\\``
    mutex covers one logon session, so quietly falling back to it would drop the one-operation-per-computer guarantee
    (closure review ACT67-CLR-002). If the machine-wide mutex cannot be had, nothing is protected and the operation is
    refused, with ``failure`` saying which of three things happened:

    * ``"busy"``   -- another owner genuinely holds it right now (``acquire`` returns False);
    * ``"denied"`` -- Windows would not let this user open the existing mutex (``acquire`` returns False). Another Windows
      user's copy having it open is the usual cause, but that is not proven, so the message does not claim it;
    * creation or wait failed outright -- ``acquire`` raises ``Qwen3Unavailable`` carrying the Windows error number.

    Acquisition never waits: it succeeds at once or refuses, so nothing can hang on it. The kernel releases the mutex
    when its owner dies however it dies (the next owner sees WAIT_ABANDONED and simply takes it), so a crash cannot
    strand it. It belongs to the acquiring thread, which is why it is only ever used as a ``with`` block. Qwen3 runs on
    Windows only; elsewhere this is a no-op with ``scope`` "none".
    """

    DENIED_MESSAGE = ("Windows did not give this user permission to open the lock that keeps copies of this app from "
                      "loading Qwen3 models at the same time. Another Windows user's copy may have it open, or this may "
                      "be a permission problem. Qwen3 was not started, so two models cannot load at once. If no one else "
                      "is using Qwen3, restart the computer or ask an administrator.")

    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name or MACHINE_GUARD_NAME
        self.scope: Optional[str] = None
        self.failure: Optional[str] = None
        self._handle = None

    @property
    def refusal_message(self) -> str:
        """What to tell the user after ``acquire`` returned False."""
        return self.DENIED_MESSAGE if self.failure == "denied" else MACHINE_BUSY_MESSAGE

    @property
    def held(self) -> bool:
        return self._handle is not None or self.scope == "none"

    @staticmethod
    def _kernel32():
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        return k, ctypes

    def acquire(self) -> bool:
        if self.held:
            return True
        if sys.platform != "win32":
            self.scope = "none"
            return True
        k, ctypes = self._kernel32()
        self.failure = None
        handle = k.CreateMutexW(None, False, "Global\\" + self.name)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_ACCESS_DENIED:
                self.failure = "denied"
                return False
            raise Qwen3Unavailable("Windows could not create the lock that keeps two copies of this app from loading "
                                   f"Qwen3 models at the same time (error {error}), so Qwen3 was not started.")
        result = k.WaitForSingleObject(handle, 0)
        if result in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            self._handle = handle
            self.scope = "machine"
            return True
        error = ctypes.get_last_error()
        k.CloseHandle(handle)
        if result == _WAIT_TIMEOUT:
            self.failure = "busy"
            return False
        raise Qwen3Unavailable("Windows could not check the lock that keeps two copies of this app from loading Qwen3 "
                               f"models at the same time (error {error}), so Qwen3 was not started.")

    def release(self) -> None:
        if self.scope == "none":
            self.scope = None
            return
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        k, _ctypes = self._kernel32()
        try:
            k.ReleaseMutex(handle)
        finally:
            k.CloseHandle(handle)
            self.scope = None


MACHINE_BUSY_MESSAGE = ("Another copy of this app (possibly another Windows user's) is running a Qwen3 conversion, model "
                        "check or transcription right now, and only one can use the models at a time. Try again when "
                        "it has finished.")


class inference_lease:
    """Held while a conversion uses the Qwen3 environment and models, so an install or repair cannot change them under it.

    Two locks, two scopes. This installation's ``inference.lock`` keeps an install or repair of THIS copy from changing
    its files under a running worker. ``MachineGuard`` keeps every copy of the app on the computer to one heavy Qwen3
    model operation at a time -- the right limit for one GPU holding a multi-gigabyte model. Both are released when the
    block ends, by an exception too, and by the operating system if the process dies.
    """

    def __init__(self) -> None:
        self._lock = FileLock(inference_lock_path())
        self._guard = MachineGuard()

    def __enter__(self) -> "inference_lease":
        if not self._lock.acquire():
            raise Qwen3Unavailable(
                "The Qwen3 voices are being installed or repaired, or another conversion is using them right now. "
                "Try again when that has finished.")
        try:
            if not self._guard.acquire():
                raise Qwen3Unavailable(self._guard.refusal_message)
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._guard.release()
        finally:
            self._lock.release()


# --------------------------------------------------------------------------- #
# Platform and hardware
# --------------------------------------------------------------------------- #
def platform_supported() -> bool:
    """Windows only for now (owner ruling Q4). macOS is not claimed until it has been tested on a Mac."""
    return sys.platform == "win32"


def platform_reason() -> str:
    return ("The Qwen3 voices are not yet available on this platform. They currently need Windows; "
            "every other voice works as before.")


@dataclass(frozen=True)
class GpuInfo:
    name: str
    memory_mb: int


_GPU_CACHE: dict = {}


def _query_nvidia_smi() -> Optional[GpuInfo]:
    from shared import subprocess_utils

    try:
        result = subprocess_utils.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
    except Exception:  # noqa: BLE001 - no NVIDIA driver is an answer, not an error
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    name, _, memory = result.stdout.strip().splitlines()[0].partition(",")
    try:
        return GpuInfo(name.strip(), int(float(memory.strip())))
    except ValueError:
        return GpuInfo(name.strip(), 0)


#: Replaceable by tests; production always asks the driver.
gpu_probe: Callable[[], Optional[GpuInfo]] = _query_nvidia_smi


def detect_gpu(refresh: bool = False) -> Optional[GpuInfo]:
    """The first NVIDIA GPU the driver reports, or ``None``. Asked once per process."""
    if refresh or "gpu" not in _GPU_CACHE:
        _GPU_CACHE["gpu"] = gpu_probe()
    return _GPU_CACHE["gpu"]


def hardware_summary() -> str:
    """One sentence about where Qwen3 will run and how fast to expect it. Honest, never a promise.

    Empty on a platform where the voices are "not yet available": saying where Qwen3 *will run* there would claim a
    support that has not been tested (owner ruling Q4).
    """
    if not platform_supported():
        return ""
    gpu = detect_gpu()
    if gpu is not None:
        memory = f", {round(gpu.memory_mb / 1024)} GB" if gpu.memory_mb else ""
        return (f"Runs on your NVIDIA GPU ({gpu.name}{memory}). Speed depends on the computer: on the "
                "RTX 5070 it was tested on, narration took about 1.4 to 1.9 times as long as the audio it produced.")
    return ("No NVIDIA GPU was detected, so Qwen3 will run on the CPU, which is much slower and uses about 6 GB "
            "of memory. On the tested Ryzen 7 9800X3D it took about 2.2 times as long as the audio; "
            "your computer may be slower.")


# --------------------------------------------------------------------------- #
# Reference recording and transcript
# --------------------------------------------------------------------------- #
def reference_status(voice: Qwen3Voice) -> tuple[bool, str]:
    path = reference_path(voice)
    if not path.is_file():
        return False, (f"Setup required for {voice.label}: its reference recording '{reference_path(voice).name}' is "
                       "not present on this computer. This voice is unavailable here; every other voice is unaffected.")
    if sha256_file(path) != voice.reference_sha256:
        return False, (f"The reference recording '{reference_path(voice).name}' does not match the one {voice.label} "
                       "was approved against, so it will not be used. Restore the original file to use this voice.")
    return True, "ok"


@dataclass(frozen=True)
class Transcript:
    ok: bool
    text: str
    reason: str
    source: Optional[Path] = None


MAX_TRANSCRIPT_CHARS = 2000

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_TOP_KEYS = frozenset({"schema_version", "bundle_revision", "entries"})
BUNDLE_ENTRY_KEYS = frozenset({"reference_id", "voice_id", "wav_sha256", "text", "text_sha256"})
BUNDLE_MAX_BYTES = 64 * 1024  # six short transcripts; anything larger is not the file the app shipped
_HEX64 = re.compile(r"[0-9a-f]{64}")


class TranscriptBundleError(ValueError):
    """The shipped transcript bundle is missing or not exactly what was approved. The message is a fixed sentence."""


def _reject_duplicate_keys(pairs: list) -> dict:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise TranscriptBundleError("the reference transcripts shipped with the app are damaged (a repeated field)")
    return dict(pairs)


def _bundle_text_problem(text: str) -> Optional[str]:
    import unicodedata

    if not text.strip():
        return "a blank transcript"
    if len(text) > MAX_TRANSCRIPT_CHARS:
        return "an implausibly long transcript"
    if text != text.strip():
        return "a transcript with leading or trailing spaces"
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return "a transcript with control characters"
    return None


def load_bundle(path: Optional[Path] = None) -> dict[str, str]:
    """``reference_id -> exact text`` for the six clones, after checking the WHOLE shipped bundle.

    The file must be exactly the approved shape: ``schema_version`` 1, an integer ``bundle_revision`` and exactly six
    ``entries``, each with exactly ``reference_id``, ``voice_id``, ``wav_sha256``, ``text`` and ``text_sha256``; the six
    reference ids are the registered clones, each with its registered voice id and recording hash, and each text is
    non-blank, within the production limit, without outer spaces or control characters, and hashes (UTF-8) to its
    ``text_sha256``. Anything else raises :class:`TranscriptBundleError` and no clone uses any of it: a damaged shipped
    file is not trusted in part. The text is returned exactly as stored (no strip, no normalisation). Hashing binds the
    texts to the recordings; it is integrity, not a publisher signature.
    """
    source = Path(path) if path is not None else bundled_transcripts_path()
    damaged = "the reference transcripts shipped with the app are damaged ({})".format
    try:
        if not source.is_file():
            raise TranscriptBundleError("the reference transcripts shipped with the app are missing")
        if source.stat().st_size > BUNDLE_MAX_BYTES:
            raise TranscriptBundleError(damaged("the file is too large"))
        raw = source.read_bytes()
    except OSError as exc:
        raise TranscriptBundleError("the reference transcripts shipped with the app could not be read") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise TranscriptBundleError(damaged("a byte-order mark"))
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, TranscriptBundleError):
            raise
        raise TranscriptBundleError(damaged("not valid JSON")) from exc
    if not isinstance(data, dict) or set(data) != BUNDLE_TOP_KEYS:
        raise TranscriptBundleError(damaged("unexpected top-level fields"))
    if type(data["schema_version"]) is not int or data["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise TranscriptBundleError(damaged("an unknown schema version"))
    if type(data["bundle_revision"]) is not int or data["bundle_revision"] < 1:
        raise TranscriptBundleError(damaged("an invalid bundle revision"))
    entries = data["entries"]
    clones = {v.reference_name: get_voice(v.voice_id) for v in QWEN3_VOICES if v.kind == KIND_CLONE}
    if not isinstance(entries, list) or len(entries) != len(clones):
        raise TranscriptBundleError(damaged(f"it must hold exactly {len(clones)} entries"))
    texts: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != BUNDLE_ENTRY_KEYS:
            raise TranscriptBundleError(damaged("an entry with unexpected fields"))
        if not all(isinstance(entry[key], str) for key in BUNDLE_ENTRY_KEYS):
            raise TranscriptBundleError(damaged("an entry field that is not text"))
        voice = clones.get(entry["reference_id"])
        if voice is None:
            raise TranscriptBundleError(damaged("an entry for an unknown recording"))
        if entry["reference_id"] in texts:
            raise TranscriptBundleError(damaged(f"two entries for {entry['reference_id']}"))
        if entry["voice_id"] != voice.voice_id:
            raise TranscriptBundleError(damaged(f"the wrong voice for {entry['reference_id']}"))
        if entry["wav_sha256"] != voice.reference_sha256:
            raise TranscriptBundleError(damaged(f"{entry['reference_id']} is bound to a different recording"))
        problem = _bundle_text_problem(entry["text"])
        if problem:
            raise TranscriptBundleError(damaged(f"{problem} for {entry['reference_id']}"))
        if not _HEX64.fullmatch(entry["text_sha256"]) or entry["text_sha256"] != transcript_sha256(entry["text"]):
            raise TranscriptBundleError(damaged(f"the transcript for {entry['reference_id']} fails its checksum"))
        texts[entry["reference_id"]] = entry["text"]
    return texts


def bundle_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the shipped bundle as a whole. Cheap (one small file), never raises."""
    try:
        load_bundle()
    except TranscriptBundleError as exc:
        return False, str(exc)
    return True, "ok"


def load_transcript(voice_id: str, *, override: Optional[Path] = None) -> Transcript:
    """The approved reference transcript for one clone, or why there is none. Never approves anything.

    Normal use (no ``override``): the verified bundle shipped with the app, and nothing else — a local store or
    ``ACT_QWEN3_TRANSCRIPTS`` is never consulted, so stale local state cannot shadow the shipped texts. There is no
    transcript-free fallback.

    ``override`` is a maintainer's explicit choice of one local store (the clone-setup / transcript-review shape:
    ``{"Female-1": {"text": ..., "approved": true, "wav_sha256": ...}}``). An entry there counts only when ``approved``
    is the literal ``true`` and it was recorded against exactly the registered recording.
    """
    voice = get_voice(voice_id)
    if voice.kind != KIND_CLONE:
        return Transcript(True, "", "not needed")
    if override is None:
        source = bundled_transcripts_path()
        try:
            return Transcript(True, load_bundle(source)[voice.reference_name], "ok", source)
        except TranscriptBundleError as exc:
            return Transcript(False, "", str(exc), source)
    source = Path(override)
    if not source.is_file():
        return Transcript(False, "", "no approved reference transcript is available in the chosen file", source)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Transcript(False, "", "the transcript file could not be read", source)
    entry = data.get(voice.reference_name) if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return Transcript(False, "", f"the transcript file has no entry for {voice.reference_name}", source)
    if entry.get("approved") is not True:
        return Transcript(False, "", "the reference transcript has not been approved yet", source)
    if entry.get("wav_sha256") != voice.reference_sha256:
        return Transcript(False, "", "the approved transcript is not bound to the current reference recording", source)
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return Transcript(False, "", "the approved transcript is empty", source)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        return Transcript(False, "", "the approved transcript is implausibly long", source)
    return Transcript(True, text.strip(), "ok", source)


def transcript_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# The one question callers ask
# --------------------------------------------------------------------------- #
def voice_availability(voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` — can this Qwen3 voice run right now? Cheap, never raises, never touches the network.

    Order matters: the platform first (a Mac is told "not yet available", not "install it"), then the engine, then
    the model this voice needs, then — for clones — the reference recording and its approved transcript. Every
    reason names the single next step.
    """
    try:
        voice = get_voice(voice_id)
    except Qwen3Unavailable as exc:
        return False, str(exc)
    if not platform_supported():
        return False, platform_reason()
    try:
        ok, reason = environment_status()
        if not ok:
            return False, reason
        ok, reason = model_status(voice.model_key)
        if not ok:
            return False, reason
        if voice.kind == KIND_CLONE:
            ok, reason = reference_status(voice)
            if not ok:
                return False, reason
            transcript = load_transcript(voice_id)
            if not transcript.ok:
                return False, (f"Setup required for {voice.label}: {transcript.reason}. Extract a fresh copy of the "
                               "app to restore the files it ships with. The Qwen3 preset voices, Edge, Kokoro and "
                               "Chatterbox are unaffected.")
    except Exception as exc:  # noqa: BLE001 - report it, never crash a panel
        return False, f"This voice could not be checked on this computer ({exc})."
    return True, "ok"


def worker_environment(base: Optional[dict] = None) -> dict:
    """The environment a Qwen3 worker or installer subprocess runs in.

    Isolated from the application's interpreter settings, offline for model loading, and with every cache pointed
    inside the repository tree so nothing is written to the user's profile.
    """
    env = dict(os.environ if base is None else base)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"):
        env.pop(name, None)
    cache, scratch = cache_root(), ensure_runtime_dir(tmp_root())
    for name in ("hf", "torch", "numba", "xdg", "pip"):
        ensure_runtime_dir(cache / name)  # every cache destination handed to a subprocess is proved local first
    env.update({
        "TEMP": str(scratch), "TMP": str(scratch), "TMPDIR": str(scratch),
        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "HF_HOME": str(cache / "hf"), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TORCH_HOME": str(cache / "torch"), "NUMBA_CACHE_DIR": str(cache / "numba"),
        "XDG_CACHE_HOME": str(cache / "xdg"), "XDG_CONFIG_HOME": str(cache / "xdg"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
        "GRADIO_ANALYTICS_ENABLED": "False", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    })
    return env
