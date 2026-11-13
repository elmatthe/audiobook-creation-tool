"""omnivoice_runtime.py — what the six OmniVoice voices need on this computer, and whether it is there.

OmniVoice 0.2.1 needs ``transformers>=5.3.0``, which neither the app's ``.venv`` nor the Qwen3 engine can hold, so it runs
in its own sibling environment ``.venv-omnivoice`` (plan section 4, Decisions 2026-11-13) inside a supervised worker
process (``omnivoice_worker.py``); ``omnivoice_synth.py`` is the application-side half. This module only *asks
questions*: where things live, whether they are present and intact, and what a person should be told when they are not.
It imports nothing heavy (numpy only inside the silence check), never downloads, and never raises for a missing asset --
a missing asset is a status with a sentence fit for a non-technical user.

The six voices clone the six bundled recordings the Chatterbox and Qwen3 clones use, but OmniVoice alone is conditioned
on a **derived excerpt**: the first part of each recording, never more than 10.000 s, ending inside a natural pause
after a complete word (owner decision 2026-11-13, "maximum-10-second, silence-safe"). The excerpt's crop, its exact PCM
and its own excerpt-matched transcript are tracked data (``tts/data/omnivoice_excerpts.json``), bound to the
recording's SHA-256 and to the approved full-length transcript it must be a word-prefix of. The recordings and the full
transcripts are never changed; the excerpt is made again, from the verified recording, inside each run's own job folder.

Nothing here installs anything. The optional installer (plan Phase 3) will place the environment and the model and
call :func:`verify_model_files`; a conversion (``omnivoice_synth``) is the only thing that loads the model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from shared import venv_layout
from tts import qwen3_runtime as _qwen3  # the shared, light helpers: hashing, OS-owned locks, GPU probe, PATH scrub

BACKEND = "omnivoice"
#: The optional-setup component that installs these voices. Install & Continue offers it only once the setup protocol
#: knows it (plan Phase 3); until then an uninstalled OmniVoice voice is reported, not offered.
COMPONENT = "omnivoice"
ENGINE_NAME = "OmniVoice"


class OmniVoiceUnavailable(RuntimeError):
    """The OmniVoice engine, its model, or a voice's reference excerpt is not usable right now.

    Always carries a message fit to show a non-technical user. Raised instead of falling back to another voice, another
    engine, the full-length recording, or a transcript-free clone, so no substituted voice is ever produced.
    """


# --------------------------------------------------------------------------- #
# Identity of the six voices
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OmniVoiceVoice:
    voice_id: str
    reference_id: str  # the stable reference id of the bundled recording (voice_registry.REFERENCE_RECORDINGS)

    @property
    def label(self) -> str:
        """This voice's current registry label, looked up when asked (the registry never depends on an engine)."""
        from tts.voice_registry import label_for

        return label_for(BACKEND, self.voice_id)


#: Plan section 3: six new, distinct stable ids, each cloned from the unchanged recording of the same reference id.
OMNIVOICE_VOICES: tuple[OmniVoiceVoice, ...] = (
    OmniVoiceVoice("omnivoice-female-1", "Female-1"),
    OmniVoiceVoice("omnivoice-female-2", "Female-2"),
    OmniVoiceVoice("omnivoice-male-1", "Male-1"),
    OmniVoiceVoice("omnivoice-male-2", "Male-2"),
    OmniVoiceVoice("omnivoice-male-3", "Male-3"),
    OmniVoiceVoice("omnivoice-male-4", "Male-4"),
)
_VOICE_BY_ID = {v.voice_id: v for v in OMNIVOICE_VOICES}


def get_voice(voice_id: str) -> OmniVoiceVoice:
    try:
        return _VOICE_BY_ID[voice_id]
    except KeyError:
        raise OmniVoiceUnavailable(
            f"Unknown OmniVoice voice '{voice_id}'. Known voices: {', '.join(sorted(_VOICE_BY_ID))}.") from None


def recording_sha256(reference_id: str) -> str:
    """The SHA-256 the bundled recording of *reference_id* was approved at (the registered clone's, one source of it)."""
    for voice in _qwen3.QWEN3_VOICES:
        if voice.kind == _qwen3.KIND_CLONE and voice.reference_name == reference_id:
            return voice.reference_sha256
    raise OmniVoiceUnavailable(f"{reference_id} is not one of the six bundled reference recordings.")


def reference_path(voice: OmniVoiceVoice) -> Path:
    """The ONE bundled copy of the recording, shared with the Chatterbox and Qwen3 clones (named by the registry)."""
    from tts.voice_registry import REFERENCE_DIRECTORY, reference_recording_filename

    return repo_root().joinpath(*REFERENCE_DIRECTORY) / reference_recording_filename(BACKEND, voice.voice_id)


# --------------------------------------------------------------------------- #
# Locations -- everything inside the repository tree (AI-WORKSPACE containment)
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    return _qwen3.repo_root()


def runtime_dir() -> Path:
    """``files/runtime-data/omnivoice/`` -- ignored, app-owned: models, verification record, locks, jobs, prompt cache."""
    return repo_root() / "files" / "runtime-data" / "omnivoice"


def venv_dir() -> Path:
    """``.venv-omnivoice``: the sibling environment (never inside ``.venv``, so the app's repair never moves it)."""
    return repo_root() / ".venv-omnivoice"


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


def worker_script() -> Path:
    return Path(__file__).resolve().with_name("omnivoice_worker.py")


def manifest_path() -> Path:
    return Path(__file__).resolve().with_name("omnivoice_manifest.json")


def excerpts_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "omnivoice_excerpts.json"


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


def environment_status() -> tuple[bool, str]:
    """``(ok, reason)`` for ``.venv-omnivoice``: present, not reached through a link, CPython 3.12, and holding exactly
    the pinned package set. Cheap: a folder listing, no subprocess, no import of the engine."""
    folder = venv_dir()
    if not (folder.exists() or folder.is_symlink()):
        return False, NOT_INSTALLED_MESSAGE
    if venv_layout.unsafe_component(repo_root(), folder) is not None:
        return False, ("The OmniVoice environment is reached through a link to another folder, so the app will not "
                       "use it. Remove the link (not its target).")
    if not venv_python().is_file():
        return False, "The OmniVoice voice engine was not installed completely. " + INSTALL_ACTION + " to repair it."
    config = venv_layout.read_pyvenv_cfg(folder) or {}
    if not str(config.get("version", config.get("version_info", ""))).startswith("3.12."):
        return False, ("The OmniVoice environment was not made with Python 3.12, the version it is pinned to. "
                       + INSTALL_ACTION + " to repair it.")
    try:
        pins = pinned_packages()
    except OmniVoiceUnavailable as exc:
        return False, str(exc)
    installed = installed_distributions(folder)
    missing = sorted(name for name in pins if name not in installed)
    wrong = sorted(name for name in pins if name in installed and installed[name] != pins[name])
    extra = sorted(set(installed) - set(pins) - VENV_BOOTSTRAP)
    if missing or wrong or extra:
        detail = (f"{len(missing)} missing" if missing else f"{len(wrong)} at another version" if wrong
                  else f"{len(extra)} not part of it")
        return False, (f"The OmniVoice environment does not hold its pinned packages ({detail}: "
                       f"{', '.join((missing or wrong or extra)[:3])}). " + INSTALL_ACTION + " to repair it.")
    return True, "ok"


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
# The reference excerpts: the maximum-10-second, silence-safe rule
# --------------------------------------------------------------------------- #
#: Ten seconds is a MAXIMUM (owner decision 2026-11-13). Nothing after it is ever conditioned on.
MAX_EXCERPT_SECONDS = 10
#: How an excerpt is made: the recording's own decoded frames [0, end), unchanged, in a new canonical PCM WAV.
PREPROCESSING_VERSION = "act-omnivoice-excerpt-v2"
SILENCE_RULE_VERSION = "act-omnivoice-silence-v1"
#: The silence rule, fixed and versioned. Energy is the mean square of 20 ms frames every 5 ms. The quiet threshold
#: adapts to each recording: ``floor + max(6 dB, 20% of (speech - floor))``, where floor and speech are the 5th and 95th
#: percentiles of its frame energies. A quiet run must last at least 150 ms to count as a natural pause (an English stop
#: closure is shorter, so a closure inside or between words is never mistaken for one). The cut keeps at least 100 ms of
#: that pause after the last word, and at least 50 ms of it before whatever sound comes next.
FRAME_S, HOP_S = 0.020, 0.005
FLOOR_PERCENTILE, SPEECH_PERCENTILE = 5, 95
MIN_MARGIN_DB, MARGIN_FRACTION = 6.0, 0.20
MIN_PAUSE_S, MIN_TAIL_S, GUARD_S = 0.150, 0.100, 0.050

EXCERPT_STATUSES = ("provisional", "approved")
EXCERPT_TOP_KEYS = frozenset({"schema_version", "rule", "silence_rule", "preprocessing_version", "entries"})
EXCERPT_ENTRY_KEYS = frozenset({
    "voice_id", "reference_id", "original_wav_sha256", "sample_rate", "channels", "sample_width_bytes",
    "original_frames", "crop_start_frame", "crop_end_frame", "excerpt_pcm_sha256", "excerpt_wav_sha256",
    "pause_start_frame", "pause_end_frame", "last_word", "text", "text_sha256", "status", "note"})
EXCERPT_MAX_BYTES = 64 * 1024
_TRAILING_MARKS = ".,;:!?\"'’”)]"


class ExcerptError(ValueError):
    """The excerpt authority, an excerpt or its transcript is not exactly what was reviewed. The message says what."""


@dataclass(frozen=True)
class ExcerptSpec:
    voice_id: str
    reference_id: str
    original_wav_sha256: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    original_frames: int
    crop_start_frame: int
    crop_end_frame: int
    excerpt_pcm_sha256: str
    excerpt_wav_sha256: str
    pause_start_frame: int
    pause_end_frame: int
    last_word: str
    text: str
    text_sha256: str
    status: str
    note: str

    @property
    def duration_s(self) -> float:
        return (self.crop_end_frame - self.crop_start_frame) / self.sample_rate


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transcript_problem(text: object) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return "it is blank"
    if text != text.strip():
        return "it has leading or trailing spaces"
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return "it has control characters"
    return None


def validate_excerpt_transcript(full_text: str, excerpt_text: str) -> None:
    """Refuse an excerpt transcript that is not the approved full transcript's own opening words.

    Every word but the last must equal the approved transcript's word at that place exactly; the last may differ only in
    trailing punctuation. Nothing may be added, changed or left out, and the full-length transcript itself is refused:
    an excerpt of at most 10 seconds of a 15-second recording cannot be all of it.
    """
    problem = transcript_problem(excerpt_text)
    if problem:
        raise ExcerptError(f"the excerpt transcript is unusable: {problem}")
    full, words = full_text.split(), excerpt_text.split()
    if len(words) >= len(full):
        raise ExcerptError("the excerpt transcript is as long as the full-length transcript")
    for index, word in enumerate(words[:-1]):
        if word != full[index]:
            raise ExcerptError(f"word {index + 1} ({word!r}) is not the approved transcript's ({full[index]!r})")
    last, expected = words[-1], full[len(words) - 1]
    if last != expected and (not last.rstrip(_TRAILING_MARKS)
                             or last.rstrip(_TRAILING_MARKS) != expected.rstrip(_TRAILING_MARKS)):
        raise ExcerptError(f"the last word ({last!r}) is not the approved transcript's ({expected!r})")


def _entry(raw: dict, full_texts: dict[str, str]) -> ExcerptSpec:
    if not isinstance(raw, dict) or set(raw) != EXCERPT_ENTRY_KEYS:
        raise ExcerptError("an entry has unexpected fields")
    ints = ("sample_rate", "channels", "sample_width_bytes", "original_frames", "crop_start_frame", "crop_end_frame",
            "pause_start_frame", "pause_end_frame")
    if any(type(raw[key]) is not int for key in ints) or any(
            not isinstance(raw[key], str) for key in EXCERPT_ENTRY_KEYS - set(ints)):
        raise ExcerptError("an entry field has the wrong type")
    spec = ExcerptSpec(**raw)
    voice = _VOICE_BY_ID.get(spec.voice_id)
    if voice is None or voice.reference_id != spec.reference_id:
        raise ExcerptError(f"{spec.voice_id}: not one of the six OmniVoice voices with that recording")
    if spec.original_wav_sha256 != recording_sha256(spec.reference_id):
        raise ExcerptError(f"{spec.voice_id}: bound to a different recording")
    for key in ("excerpt_pcm_sha256", "excerpt_wav_sha256", "text_sha256", "original_wav_sha256"):
        if not _HEX64.fullmatch(getattr(spec, key)):
            raise ExcerptError(f"{spec.voice_id}: {key} is not a SHA-256")
    rate = spec.sample_rate
    if rate <= 0 or spec.channels != 1 or spec.sample_width_bytes != 2:
        raise ExcerptError(f"{spec.voice_id}: the recording is not the 16-bit mono PCM it was reviewed as")
    if spec.crop_start_frame != 0:
        raise ExcerptError(f"{spec.voice_id}: an excerpt starts at 0.000 s")
    if not 0 < spec.crop_end_frame <= min(MAX_EXCERPT_SECONDS * rate, spec.original_frames):
        raise ExcerptError(f"{spec.voice_id}: the excerpt must end inside the first {MAX_EXCERPT_SECONDS} seconds")
    if not (spec.pause_start_frame + int(round(MIN_TAIL_S * rate)) <= spec.crop_end_frame
            and spec.crop_end_frame + int(round(GUARD_S * rate)) <= spec.pause_end_frame
            and spec.pause_end_frame - spec.pause_start_frame >= int(round(MIN_PAUSE_S * rate))):
        raise ExcerptError(f"{spec.voice_id}: the recorded crop does not sit inside its recorded natural pause")
    problem = transcript_problem(spec.text)
    if problem:
        raise ExcerptError(f"{spec.voice_id}: the excerpt transcript is unusable: {problem}")
    if text_sha256(spec.text) != spec.text_sha256:
        raise ExcerptError(f"{spec.voice_id}: the excerpt transcript fails its checksum")
    if spec.text.split()[-1] != spec.last_word:
        raise ExcerptError(f"{spec.voice_id}: the recorded last word is not the transcript's last word")
    if spec.reference_id not in full_texts:
        raise ExcerptError(f"{spec.voice_id}: no approved full-length transcript for {spec.reference_id}")
    try:
        validate_excerpt_transcript(full_texts[spec.reference_id], spec.text)
    except ExcerptError as exc:
        raise ExcerptError(f"{spec.voice_id}: {exc}") from None
    if spec.status not in EXCERPT_STATUSES:
        raise ExcerptError(f"{spec.voice_id}: unknown status {spec.status!r}")
    return spec


def load_excerpts(path: Optional[Path] = None, *, full_texts: Optional[dict[str, str]] = None) -> dict[str, ExcerptSpec]:
    """``voice_id -> ExcerptSpec`` for all six voices, after checking the WHOLE authority (a damaged file is not trusted
    in part). Each entry is bound to its recording's hash and to the approved full-length transcript it must open."""
    source = Path(path) if path is not None else excerpts_path()
    try:
        if source.stat().st_size > EXCERPT_MAX_BYTES:
            raise ExcerptError("the excerpt list is too large")
        data = json.loads(source.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ExcerptError):
            raise
        raise ExcerptError(f"the excerpt list shipped with the app could not be read ({exc})") from exc
    if not isinstance(data, dict) or set(data) != EXCERPT_TOP_KEYS or data.get("schema_version") != 1:
        raise ExcerptError("the excerpt list is not schema version 1")
    if (data["rule"], data["silence_rule"], data["preprocessing_version"]) != (
            "maximum-10s-silence-safe", SILENCE_RULE_VERSION, PREPROCESSING_VERSION):
        raise ExcerptError("the excerpt list was made under another rule")
    if full_texts is None:
        try:
            full_texts = _qwen3.load_bundle()
        except _qwen3.TranscriptBundleError as exc:
            raise ExcerptError(str(exc)) from exc
    entries = data["entries"]
    if not isinstance(entries, list) or len(entries) != len(OMNIVOICE_VOICES):
        raise ExcerptError(f"the excerpt list must hold exactly {len(OMNIVOICE_VOICES)} entries")
    specs: dict[str, ExcerptSpec] = {}
    for raw in entries:
        spec = _entry(raw, full_texts)
        if spec.voice_id in specs:
            raise ExcerptError(f"two entries for {spec.voice_id}")
        specs[spec.voice_id] = spec
    return specs


def excerpt_spec(voice_id: str) -> ExcerptSpec:
    get_voice(voice_id)
    try:
        return load_excerpts()[voice_id]
    except ExcerptError as exc:
        raise OmniVoiceUnavailable(f"The OmniVoice reference excerpts shipped with the app are damaged ({exc}). "
                                   "Extract a fresh copy of the app to restore them.") from exc


def read_pcm(path: Path) -> tuple[bytes, "wave._wave_params"]:
    """Every frame of a plain PCM WAV, as bytes, and its parameters (stdlib ``wave``: nothing resampled or converted)."""
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        if params.comptype != "NONE":
            raise ExcerptError(f"{Path(path).name} is not plain PCM")
        frames = source.readframes(params.nframes)
    if len(frames) != params.nframes * params.nchannels * params.sampwidth:
        raise ExcerptError(f"{Path(path).name} ended before its header said it would")
    return frames, params


def derive_excerpt(spec: ExcerptSpec, original: Path, destination: Path) -> dict:
    """Write the reviewed excerpt of *original* -- its own frames [0, crop_end) -- into the NEW file *destination*.

    The original is only opened for reading and must hash to the approved recording before and after; the frames taken
    must hash to the reviewed excerpt. Anything else is refused and no excerpt is left behind.
    """
    original, destination = Path(original), Path(destination)
    if venv_layout.same_path(original, destination):
        raise ExcerptError("an excerpt is never written over its original")
    if os.path.lexists(destination):
        raise ExcerptError(f"{destination.name} already exists; an excerpt is only ever written to a new file")
    if _qwen3.sha256_file(original) != spec.original_wav_sha256:
        raise ExcerptError(f"{original.name} is not the recording {spec.voice_id} was reviewed against")
    frames, params = read_pcm(original)
    if (params.framerate, params.nchannels, params.sampwidth, params.nframes) != (
            spec.sample_rate, spec.channels, spec.sample_width_bytes, spec.original_frames):
        raise ExcerptError(f"{original.name} is not in the format it was reviewed in")
    width = params.nchannels * params.sampwidth
    pcm = frames[spec.crop_start_frame * width: spec.crop_end_frame * width]
    if hashlib.sha256(pcm).hexdigest() != spec.excerpt_pcm_sha256:
        raise ExcerptError(f"the excerpt of {original.name} is not the reviewed audio")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    try:
        with open(part, "xb") as handle:
            with wave.open(handle, "wb") as target:
                target.setnchannels(params.nchannels)
                target.setsampwidth(params.sampwidth)
                target.setframerate(params.framerate)
                target.writeframes(pcm)
        os.replace(part, destination)
    finally:
        part.unlink(missing_ok=True)
    if _qwen3.sha256_file(original) != spec.original_wav_sha256:
        raise ExcerptError(f"{original.name} changed while its excerpt was taken")
    if _qwen3.sha256_file(destination) != spec.excerpt_wav_sha256:
        destination.unlink(missing_ok=True)
        raise ExcerptError(f"the excerpt WAV of {original.name} is not the reviewed file")
    return {"path": str(destination), "frames": spec.crop_end_frame - spec.crop_start_frame,
            "sample_rate": spec.sample_rate, "pcm_sha256": spec.excerpt_pcm_sha256,
            "wav_sha256": spec.excerpt_wav_sha256}


@dataclass(frozen=True)
class QuietAnalysis:
    floor_db: float
    speech_db: float
    threshold_db: float
    pauses: tuple[tuple[int, int], ...]  # every natural pause, [start, end) in sample frames, in time order


def analyse_quiet(pcm: bytes, sample_rate: int) -> QuietAnalysis:
    """The silence rule applied to 16-bit mono PCM: its adaptive threshold and every natural pause (>= 150 ms).

    A pause runs from the first sample after the last sounding frame to the last sample of the last quiet frame.
    """
    import numpy as np

    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    frame, hop = int(round(FRAME_S * sample_rate)), int(round(HOP_S * sample_rate))
    if x.size < frame:
        return QuietAnalysis(0.0, 0.0, 0.0, ())
    count = 1 + (x.size - frame) // hop
    index = np.arange(frame)[None, :] + hop * np.arange(count)[:, None]
    energy = 10 * np.log10(np.mean(x[index] ** 2, axis=1) + 1e-12)
    floor = float(np.percentile(energy, FLOOR_PERCENTILE))
    speech = float(np.percentile(energy, SPEECH_PERCENTILE))
    threshold = floor + max(MIN_MARGIN_DB, MARGIN_FRACTION * (speech - floor))
    quiet = energy < threshold
    pauses: list[tuple[int, int]] = []
    start: Optional[int] = None
    minimum = int(round(MIN_PAUSE_S * sample_rate))
    for i in range(count + 1):
        is_quiet = bool(quiet[i]) if i < count else False
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            first = start * hop
            last = x.size if i == count else (i - 1) * hop + frame
            if last - first >= minimum:
                pauses.append((first, last))
            start = None
    return QuietAnalysis(floor, speech, threshold, tuple(pauses))


def endpoint_problems(pcm: bytes, sample_rate: int, end_frame: int, *, analysis: Optional[QuietAnalysis] = None) -> list[str]:
    """Why *end_frame* is not a silence-safe end for an excerpt of this recording; ``[]`` when it is.

    Safe means: within the first 10 seconds, inside a natural pause (>= 150 ms) of the recording, at least 100 ms after
    the last word ends and at least 50 ms before the next sound (or at the recording's own quiet end). Acoustics only:
    whether the word before the pause is the transcript's last word is checked separately, against the transcript.
    """
    analysis = analysis or analyse_quiet(pcm, sample_rate)
    problems: list[str] = []
    if not 0 < end_frame <= MAX_EXCERPT_SECONDS * sample_rate:
        problems.append(f"the end ({end_frame / sample_rate:.3f} s) is not inside the first {MAX_EXCERPT_SECONDS} s")
    total = len(pcm) // 2
    pause = next(((a, b) for a, b in analysis.pauses if a < end_frame <= b), None)
    if pause is None:
        problems.append(f"the end ({end_frame / sample_rate:.3f} s) is not inside a natural pause")
        return problems
    start, end = pause
    if end_frame - start < int(round(MIN_TAIL_S * sample_rate)):
        problems.append(f"only {(end_frame - start) / sample_rate * 1000:.0f} ms of quiet follows the last word")
    if end != total and end - end_frame < int(round(GUARD_S * sample_rate)):
        problems.append(f"the end is only {(end - end_frame) / sample_rate * 1000:.0f} ms before the next sound")
    return problems


def latest_safe_endpoint(pcm: bytes, sample_rate: int) -> Optional[tuple[int, tuple[int, int]]]:
    """The latest silence-safe end within the first 10 seconds and its pause, or ``None`` when there is none.

    Deterministic: inside the latest natural pause that starts at least 100 ms before 10.000 s, the end is 50 ms before
    the next sound, or 10.000 s itself when the pause runs past it. (Which word ends there is not decided here.)
    """
    analysis = analyse_quiet(pcm, sample_rate)
    limit = MAX_EXCERPT_SECONDS * sample_rate
    tail, guard = int(round(MIN_TAIL_S * sample_rate)), int(round(GUARD_S * sample_rate))
    total = len(pcm) // 2
    for start, end in reversed(analysis.pauses):
        if start == 0 or start + tail > limit:
            continue
        cut = min(end if end == total else end - guard, limit)
        if not endpoint_problems(pcm, sample_rate, cut, analysis=analysis):
            return cut, (start, end)
    return None


# --------------------------------------------------------------------------- #
# The reusable clone prompt's identity
# --------------------------------------------------------------------------- #
#: OmniVoice's own ``VoiceClonePrompt`` file format (``omnivoice.models.omnivoice._VOICE_CLONE_PROMPT_FORMAT_VERSION``).
PROMPT_FORMAT_VERSION = 1


def prompt_identity(spec: ExcerptSpec, *, model_revision: str, omnivoice_version: str, preprocess_prompt: bool,
                    dtype: str) -> tuple[str, dict]:
    """The key a reusable clone prompt is filed under: every input that shapes it, so any change misses the cache.

    Bound: the recording's hash, the excerpt's PCM hash and crop, the preprocessing and silence-rule versions, the
    excerpt transcript's hash, the model revision, the engine version, the prompt format, the prompt preprocessing
    flag and the dtype the tokenizer ran in.
    """
    fields = {
        "schema": 1, "voice_id": spec.voice_id, "original_wav_sha256": spec.original_wav_sha256,
        "excerpt_pcm_sha256": spec.excerpt_pcm_sha256,
        "crop": [spec.crop_start_frame, spec.crop_end_frame, spec.sample_rate],
        "preprocessing_version": PREPROCESSING_VERSION, "silence_rule": SILENCE_RULE_VERSION,
        "excerpt_text_sha256": spec.text_sha256, "model_revision": model_revision, "omnivoice": omnivoice_version,
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
    """The bundled recording is present and approved, and its excerpt and excerpt transcript are the reviewed ones."""
    path = reference_path(voice)
    if not path.is_file():
        return False, (f"Setup required for {voice.label}: its reference recording '{path.name}' is not present on this "
                       "computer. This voice is unavailable here; every other voice is unaffected.")
    try:
        spec = excerpt_spec(voice.voice_id)
    except OmniVoiceUnavailable as exc:
        return False, f"Setup required for {voice.label}: {exc}"
    if _qwen3.sha256_file(path) != spec.original_wav_sha256:
        return False, (f"The reference recording '{path.name}' does not match the one {voice.label} was approved "
                       "against, so it will not be used. Restore the original file to use this voice.")
    return True, "ok"


def voice_availability(voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` -- can this OmniVoice voice run right now? Cheap, never raises, never touches the network.

    Order: the platform, the GPU (installing cannot help a computer without one), the environment, the model, then the
    voice's recording and reviewed excerpt. Every reason names the single next step.
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


def install_would_help() -> bool:
    """Whether installing the component could make an unavailable OmniVoice voice usable (Install & Continue)."""
    if not platform_supported() or detect_gpu() is None:
        return False
    return not (environment_status()[0] and model_status()[0])


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
