"""omnivoice_p1.py -- ACT v0.8.0 Phase 1: the isolated OmniVoice environment and ONE real 10-second clone proof.

Developer only: never shipped, never imported by the application, and not the production installer (that is Phase 3).
It qualifies, on this computer, what ``files/dev-tools/omnivoice_p1_manifest.json`` pins:

* ``plan``        what would be downloaded, from where, to where, and the disk it needs. No network.
* ``fetch``       after the owner's consent only: every pinned wheel and model file, each accepted only at its exact size
                  and SHA-256 (``tts.qwen3_setup.download_file``: resumable, bounded, verified) into
                  ``files/runtime-data/omnivoice/``. Nothing goes to a Hugging Face or pip cache in the user profile.
* ``create-env``  ``.venv-omnivoice`` from the verified base CPython 3.12 (the one the app's ``.venv`` was built from), then
                  pip installs the hash lock offline, from the verified wheels only. An existing folder there is never
                  repaired, replaced or deleted.
* ``verify-env``  identity and isolation (``shared.venv_layout.assess_child``), ``pip check``, the installed set equal to
                  the lock, and an import/GPU probe in the worker -- no model loaded.
* ``excerpt``     the first 10.000 s of one canonical reference, as exact decoded frames, into a new file. The original
                  is read only and hashed before and after.
* ``prove``       one real clone: model and audio tokenizer from the verified local snapshot with every network door
                  closed, the 10-second excerpt with its excerpt transcript (never the full-length one, never Whisper),
                  a fixed short narration, one WAV. Everything it writes goes to one ignored evidence folder.

Run it with the app's own interpreter (``.venv\\Scripts\\python.exe files/dev-tools/omnivoice_p1.py ...``).

Superseded location (owner decision 2026-11-13, unified ``.venv`` layout): the application's OmniVoice engine now lives
at ``.venv/engines/omnivoice``, built by the production installer (``tts.omnivoice_setup``), and the app never uses,
adopts or repairs a ``.venv-omnivoice`` beside ``.venv``. This tool is kept unchanged as the Phase 1 qualification
record: it still names the sibling it qualified, which the app only ever sets aside.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from shared import venv_layout  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402

MANIFEST_PATH = HERE / "omnivoice_p1_manifest.json"
LOCK_PATH = HERE / "omnivoice_p1_requirements.txt"
WORKER_PATH = HERE / "omnivoice_p1_worker.py"

MANIFEST_SCHEMA = "act-omnivoice-phase1"
EXCERPT_SECONDS = 10
#: The excerpt is the source's own decoded frames [0, 10 x rate), written unchanged into a canonical PCM WAV.
PREPROCESSING_VERSION = "act-omnivoice-excerpt-v1"
#: OmniVoice's own ``VoiceClonePrompt`` file format (``omnivoice.models.omnivoice._VOICE_CLONE_PROMPT_FORMAT_VERSION``).
PROMPT_FORMAT_VERSION = 1

#: The fixed narration of the proof: written for this project, so nobody else's text is read aloud.
NARRATION = ("The lighthouse keeper climbed the spiral stairs at dusk, counting each step while the wind pressed against "
             "the old glass. Below him, the harbor lights came on one by one, and far across the water a ferry answered "
             "with a long, low horn.")
LANGUAGE = "English"
DTYPE = "float16"
DEVICE = "cuda:0"
SEED = 20261113
#: OmniVoiceGenerationConfig's own defaults in omnivoice 0.2.1, written out so the proof states exactly what it used
#: (``num_step`` 32 is the plan's baseline). ``preprocess_prompt`` trims silences inside the excerpt; it never adds audio.
GENERATION = {
    "num_step": 32, "guidance_scale": 2.0, "t_shift": 0.1, "layer_penalty_factor": 5.0, "position_temperature": 5.0,
    "class_temperature": 0.0, "denoise": True, "preprocess_prompt": True, "postprocess_output": True,
    "audio_chunk_duration": 15.0, "audio_chunk_threshold": 30.0, "pad_duration": 0.1, "fade_duration": 0.1,
}

READY, MISSING, DAMAGED, UNVERIFIED = "ready", "missing", "damaged", "unverified"
APPLICATION_CONTROL_MARK = "Application Control policy"
APPLICATION_CONTROL_ATTEMPTS = 8
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_LOCK_LINE = re.compile(r"([a-z0-9][a-z0-9._-]*)==([^\s=;@]+) --hash=sha256:([0-9a-f]{64})")
_WHEEL_TAG = re.compile(r"-(cp312-cp312|cp3\d+-abi3|py3-none|py2\.py3-none)-(win_amd64|any)\.whl")
_PYPI = "https://files.pythonhosted.org/packages/"
_PYTORCH = "https://download-r2.pytorch.org/whl/cu128/"
_WHEEL_KEYS = {"name", "version", "filename", "url", "size", "sha256", "index", "license"}
#: Removed from every child's environment: it must not be steered by the caller's interpreter, pip, proxy or Hub settings.
_DROPPED_PREFIXES = ("PYTHON", "PIP_", "HF_", "HUGGINGFACE_", "TRANSFORMERS_", "TORCH_", "CUDA_VISIBLE_DEVICES")
_DROPPED_NAMES = frozenset({"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
                            "CONDA_PYTHON_EXE", "CONDA_EXE", "CONDA_SHLVL", "CONDA_PROMPT_MODIFIER", "HTTP_PROXY",
                            "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                            "SSL_CERT_FILE", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "NUMBA_CACHE_DIR", "TORCH_HOME"})
_TRAILING_MARKS = ".,;:!?\"'’”)]"


class Phase1Error(RuntimeError):
    """Something the proof depends on is not exactly as pinned. The message says what; nothing was repaired."""


# --------------------------------------------------------------------------- #
# Where things live
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def env_dir(self) -> Path:
        return self.root / ".venv-omnivoice"

    @property
    def runtime(self) -> Path:
        return self.root / "files" / "runtime-data" / "omnivoice"

    @property
    def wheels(self) -> Path:
        return self.runtime / "wheels"

    @property
    def models(self) -> Path:
        return self.runtime / "models"

    @property
    def receipts(self) -> Path:
        return self.runtime / "receipts"

    @property
    def evidence_root(self) -> Path:
        return self.root / "files" / "dev-work" / "ov-p1"

    def model_dir(self, manifest: dict) -> Path:
        model = manifest["model"]
        return self.models / model["repo"].replace("/", "--") / model["revision"]

    def env_python(self) -> Path:
        return venv_layout.interpreter(self.env_dir)


# --------------------------------------------------------------------------- #
# The manifest and the lock
# --------------------------------------------------------------------------- #
def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_lock(text: str) -> list[tuple[str, str, str]]:
    """``[(name, version, sha256)]``: every non-comment line must be exactly one hash-pinned wheel, each name once."""
    pins: list[tuple[str, str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise Phase1Error(f"the lock line {line!r} is not one exact name==version pin with one SHA-256")
        pins.append((match.group(1), match.group(2), match.group(3)))
    names = [name for name, _, _ in pins]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise Phase1Error(f"the lock pins {', '.join(repeated)} more than once")
    return pins


def manifest_problems(manifest: dict, lock_text: str) -> list[str]:
    """Everything that makes the manifest and the lock disagree with each other or with what Phase 1 pinned."""
    problems: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("version") != 1:
        problems.append("unknown manifest schema or version")
    wheels = manifest.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return problems + ["the manifest lists no wheels"]
    seen: set[str] = set()
    for wheel in wheels:
        name = wheel.get("name", "?")
        if set(wheel) != _WHEEL_KEYS:
            problems.append(f"{name}: unexpected wheel fields")
            continue
        if name in seen:
            problems.append(f"{name}: listed twice")
        seen.add(name)
        if not _WHEEL_TAG.search(wheel["filename"]) or not wheel["filename"].endswith(".whl"):
            problems.append(f"{name}: {wheel['filename']} is not a Windows x64 / CPython 3.12 wheel")
        host = _PYTORCH if wheel["index"] == "pytorch-cu128" else _PYPI if wheel["index"] == "pypi" else None
        if host is None or not wheel["url"].startswith(host):
            problems.append(f"{name}: comes from an unexpected place")
        if wheel["url"].rsplit("/", 1)[-1].replace("%2B", "+") != wheel["filename"]:
            problems.append(f"{name}: its URL does not name its file")
        if type(wheel["size"]) is not int or wheel["size"] <= 0:
            problems.append(f"{name}: no size")
        if not _HEX64.fullmatch(str(wheel["sha256"])):
            problems.append(f"{name}: no SHA-256")
    by_name = {wheel.get("name"): wheel for wheel in wheels}
    for name in ("torch", "torchaudio"):
        wheel = by_name.get(name)
        if wheel is None or not str(wheel.get("version", "")).endswith("+cu128") or wheel.get("index") != "pytorch-cu128":
            problems.append(f"{name}: not the PyTorch cu128 build")
    if (by_name.get("omnivoice") or {}).get("version") != "0.2.1":
        problems.append("omnivoice: not the 0.2.1 candidate")
    try:
        pins = set(parse_lock(lock_text))
    except Phase1Error as exc:
        problems.append(str(exc))
    else:
        listed = {(w.get("name"), w.get("version"), w.get("sha256")) for w in wheels}
        problems += [f"the lock pins {pin[0]}=={pin[1]} the manifest does not list" for pin in sorted(pins - listed)]
        problems += [f"the manifest lists {pin[0]}=={pin[1]} the lock does not pin" for pin in sorted(listed - pins)]
    problems += _model_problems(manifest)
    return problems


def _model_problems(manifest: dict) -> list[str]:
    problems: list[str] = []
    model = manifest.get("model") or {}
    files = model.get("files") or {}
    if model.get("repo") != "k2-fsa/OmniVoice" or not _HEX40.fullmatch(str(model.get("revision", ""))):
        problems.append("the model is not k2-fsa/OmniVoice at a pinned commit")
    for rel, entry in files.items():
        if type(entry.get("size")) is not int or entry["size"] <= 0 or not _HEX64.fullmatch(str(entry.get("sha256"))):
            problems.append(f"model file {rel}: no size or SHA-256")
        if "\\" in rel or ":" in rel or rel.startswith("/") or any(part in ("", ".", "..") for part in rel.split("/")):
            problems.append(f"model file {rel!r}: not a plain relative path inside the snapshot")
    missing = [rel for rel in model.get("load_required", []) if rel not in files]
    if missing or not model.get("load_required"):
        problems.append(f"the model manifest misses files the load needs: {missing}")
    if not any(rel.startswith("audio_tokenizer/") for rel in model.get("load_required", [])):
        problems.append("the audio tokenizer is not part of the pinned load")
    same = ((manifest.get("audio_tokenizer") or {}).get("same_bytes_as") or {}).get("files") or {}
    for name, entry in same.items():
        ours = files.get(f"audio_tokenizer/{name}") or {}
        if entry.get("size") != ours.get("size"):
            problems.append(f"audio_tokenizer/{name} is not the pinned Higgs tokenizer file (size)")
        for key in ("sha256", "git_blob_sha1"):
            if key in entry and entry[key] != ours.get(key):
                problems.append(f"audio_tokenizer/{name} is not the pinned Higgs tokenizer file ({key})")
    return problems


def require_valid_manifest(manifest: dict) -> None:
    problems = manifest_problems(manifest, LOCK_PATH.read_text(encoding="utf-8"))
    if problems:
        raise Phase1Error("the Phase 1 manifest is not consistent: " + "; ".join(problems[:5]))


# --------------------------------------------------------------------------- #
# Verifying files
# --------------------------------------------------------------------------- #
def file_state(path: Path, size: int, sha256: str, *, root: Path) -> tuple[str, str]:
    """``(state, detail)``: ready (exactly the pinned bytes), missing, damaged, or unverified (a link, or unreadable)."""
    path = Path(path)
    if venv_layout.unsafe_component(root, path) is not None:
        return UNVERIFIED, f"{path.name} is reached through a link or lies outside the app folder"
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return MISSING, f"{path.name} is not here"
    except OSError as exc:
        return UNVERIFIED, f"{path.name} cannot be read ({exc.strerror or exc})"
    if not path.is_file():
        return DAMAGED, f"{path.name} is not a file"
    if info.st_size != size:
        return DAMAGED, f"{path.name} has {info.st_size} bytes, not {size}"
    try:
        actual = rt.sha256_file(path)
    except OSError as exc:
        return UNVERIFIED, f"{path.name} cannot be read ({exc.strerror or exc})"
    if actual != sha256:
        return DAMAGED, f"{path.name} is not the pinned file (its SHA-256 differs)"
    return READY, ""


def model_state(manifest: dict, layout: Layout) -> dict:
    """Whether the pinned snapshot is complete, file by file, and whether its audio tokenizer folder is really there."""
    folder = layout.model_dir(manifest)
    files = {rel: file_state(folder.joinpath(*rel.split("/")), entry["size"], entry["sha256"], root=layout.root)
             for rel, entry in manifest["model"]["files"].items()}
    tokenizer_dir = folder / "audio_tokenizer"
    tokenizer_ok = tokenizer_dir.is_dir() and not venv_layout.is_link(tokenizer_dir)
    ready = tokenizer_ok and all(state == READY for state, _ in files.values())
    return {"ready": ready, "folder": str(folder), "audio_tokenizer_folder": tokenizer_ok,
            "files": {rel: list(value) for rel, value in files.items()}}


def wheel_state(manifest: dict, layout: Layout) -> dict:
    files = {w["filename"]: file_state(layout.wheels / w["filename"], w["size"], w["sha256"], root=layout.root)
             for w in manifest["wheels"]}
    return {"ready": all(state == READY for state, _ in files.values()),
            "files": {name: list(value) for name, value in files.items()}}


# --------------------------------------------------------------------------- #
# Acquisition (only after the owner's consent)
# --------------------------------------------------------------------------- #
def download_plan(manifest: dict, layout: Layout) -> dict:
    """What ``fetch`` would transfer, by size only (no hashing, no network), and where it would land."""
    def todo(path: Path, size: int) -> bool:
        try:
            return os.stat(path).st_size != size
        except OSError:
            return True
    wheels = [w for w in manifest["wheels"] if todo(layout.wheels / w["filename"], w["size"])]
    folder = layout.model_dir(manifest)
    model = [rel for rel, e in manifest["model"]["files"].items() if todo(folder.joinpath(*rel.split("/")), e["size"])]
    usage = shutil.disk_usage(layout.root)
    return {
        "wheels": {"count": len(wheels), "bytes": sum(w["size"] for w in wheels), "destination": str(layout.wheels),
                   "total_pinned_bytes": sum(w["size"] for w in manifest["wheels"])},
        "model": {"count": len(model), "bytes": sum(manifest["model"]["files"][rel]["size"] for rel in model),
                  "destination": str(folder), "total_pinned_bytes": sum(e["size"] for e in manifest["model"]["files"].values())},
        "environment": str(layout.env_dir),
        "free_bytes": usage.free,
    }


def fetch(manifest: dict, layout: Layout, *, wheels: bool = True, model: bool = True,
          out: Callable[[str], None] = print, opener=None) -> dict:
    """Download every pinned file that is not already exactly here, then record what was verified."""
    from tts import qwen3_setup  # the app's verified downloader: resumes, refuses a wrong size or hash

    require_valid_manifest(manifest)
    items: list[tuple[str, str, Path, int, str]] = []
    if wheels:
        items += [("wheel", w["url"], layout.wheels / w["filename"], w["size"], w["sha256"]) for w in manifest["wheels"]]
    if model:
        m = manifest["model"]
        folder = layout.model_dir(manifest)
        items += [("model", m["url_template"].format(repo=m["repo"], revision=m["revision"], path=rel),
                   folder.joinpath(*rel.split("/")), e["size"], e["sha256"]) for rel, e in m["files"].items()]
    downloaded = skipped = 0
    for kind, url, path, size, sha256 in items:
        if venv_layout.unsafe_component(layout.root, path.parent) is not None:
            raise Phase1Error(f"{path.parent} is reached through a link; nothing is downloaded there")
        if file_state(path, size, sha256, root=layout.root)[0] == READY:
            skipped += size
            continue
        out(f"[fetch] {kind}: {path.name} ({size:,} bytes)")
        started = time.monotonic()
        qwen3_setup.download_file(url, path, size, sha256, opener=opener)
        downloaded += size
        out(f"[fetch]   verified in {time.monotonic() - started:.0f} s")
    record = {"wheels_ready": wheel_state(manifest, layout)["ready"] if wheels else None,
              "model_ready": model_state(manifest, layout)["ready"] if model else None,
              "downloaded_bytes": downloaded, "already_present_bytes": skipped, "finished": _utc_now()}
    _write_json(layout.receipts / f"fetch-{'wheels' if wheels and not model else 'model' if model and not wheels else 'all'}.json",
                record)
    return record


# --------------------------------------------------------------------------- #
# The base interpreter and the environment
# --------------------------------------------------------------------------- #
def base_python_candidate() -> Path:
    """The base interpreter this process's environment was built from, as ``python.exe`` (never a venv's launcher)."""
    exe = Path(getattr(sys, "_base_executable", "") or sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return exe.with_name("python.exe")
    return exe


_BASE_PROBE = ("import json, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'implementation': "
               "sys.implementation.name, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'executable': sys.executable}))")


def base_problem(candidate: Path, *, root: Path) -> str:
    """Why *candidate* may not be the base of ``.venv-omnivoice`` (on disk only), or ``""``."""
    candidate = Path(candidate)
    if not candidate.is_absolute() or not candidate.is_file():
        return f"{candidate} is not there"
    if venv_layout.is_link(candidate):
        return f"{candidate} is a link"
    app_base = Path(root) / "files" / "runtime-data" / "python" / "python.exe"
    if venv_layout.is_within(root, candidate) and not venv_layout.same_path(candidate, app_base):
        return f"{candidate} is inside the app folder, so it belongs to an environment"
    if any((folder / "pyvenv.cfg").is_file() for folder in (candidate.parent, candidate.parent.parent)):
        return f"{candidate} belongs to a virtual environment"
    return ""


def verify_base_python(candidate: Path, *, root: Path) -> dict:
    problem = base_problem(candidate, root=root)
    if problem:
        raise Phase1Error(f"the base Python cannot be used: {problem}")
    done = subprocess.run([str(candidate), "-I", "-c", _BASE_PROBE], capture_output=True, text=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Phase1Error(f"the base Python {candidate} did not start") from None
    if report["implementation"] != "cpython" or report["version"][:2] != [3, 12]:
        raise Phase1Error(f"the base Python is {report['implementation']} {report['version']}, not CPython 3.12")
    if not venv_layout.same_path(report["prefix"], report["base_prefix"]):
        raise Phase1Error("the base Python is itself a virtual environment's interpreter")
    if not venv_layout.same_path(report["executable"], candidate):
        raise Phase1Error("the base Python reports a different interpreter")
    return {"path": str(candidate), **report}


def pip_install_command(env_python: Path, wheels_dir: Path, lock_path: Path) -> list[str]:
    """pip reading only the verified local wheels, each by its hash: no index, no build, no dependency resolution."""
    return [str(env_python), "-I", "-m", "pip", "install", "--isolated", "--require-virtualenv", "--no-index",
            "--find-links", str(wheels_dir), "--require-hashes", "--no-deps", "--only-binary=:all:", "--no-cache-dir",
            "--progress-bar", "off", "-r", str(lock_path)]


def child_environment(layout: Layout, scratch: Path, *, base: Optional[dict] = None) -> dict:
    """The environment pip and the worker run in: offline, every cache inside *scratch*, nothing steering it.

    Caller settings for Python, pip, proxies and the Hub are dropped; ``PATH`` loses every other Python environment's
    folders (``tts.qwen3_runtime.scrubbed_path``), so the app's ``.venv`` and the Qwen3 engine cannot leak in.
    """
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(_DROPPED_PREFIXES) or upper in _DROPPED_NAMES:
            del env[name]
    for name in [k for k in env if k.upper() == "PATH"]:
        env[name] = rt.scrubbed_path(env[name], layout.env_dir)
    cache = Path(scratch) / "cache"
    env.update({
        "TEMP": str(Path(scratch) / "tmp"), "TMP": str(Path(scratch) / "tmp"), "TMPDIR": str(Path(scratch) / "tmp"),
        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "HF_HOME": str(cache / "hf"), "HF_HUB_CACHE": str(cache / "hf" / "hub"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "DO_NOT_TRACK": "1",
        "GRADIO_ANALYTICS_ENABLED": "False", "TORCH_HOME": str(cache / "torch"),
        "NUMBA_CACHE_DIR": str(cache / "numba"), "XDG_CACHE_HOME": str(cache / "xdg"),
        "XDG_CONFIG_HOME": str(cache / "xdg"),
        "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
    })
    return env


def prepare_scratch(scratch: Path) -> Path:
    for sub in ("tmp", "cache/hf/hub", "cache/torch", "cache/numba", "cache/xdg"):
        (Path(scratch) / sub).mkdir(parents=True, exist_ok=True)
    return Path(scratch)


def run_logged(cmd: list[str], *, env: dict, cwd: Path, log_path: Path, timeout_s: float,
               on_line: Optional[Callable[[str], None]] = None) -> int:
    """Run *cmd* contained in a Windows Job Object (``tts.qwen3_process``), every output line to *log_path*.

    A run past *timeout_s* has its whole process tree stopped and counts as a failure.
    """
    from tts import qwen3_process

    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = qwen3_process.spawn(cmd, require_job=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
                               cwd=str(cwd))
    expired = threading.Event()

    def expire() -> None:
        expired.set()
        qwen3_process.kill_tree(proc, wait_s=0)

    timer = threading.Timer(timeout_s, expire)
    timer.daemon = True
    timer.start()
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\r\n")
                log.write(line + "\n")
                if on_line is not None:
                    on_line(line)
        proc.wait(timeout=60)
        if expired.is_set():
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[run_logged] stopped after the {timeout_s:.0f} s limit\n")
            return -1
        return int(proc.returncode)
    finally:
        timer.cancel()
        qwen3_process.kill_tree(proc, wait_s=5)
        qwen3_process.release(proc)


def create_env(manifest: dict, layout: Layout, *, out: Callable[[str], None] = print) -> dict:
    """Build ``.venv-omnivoice`` and install the lock offline. Refuses if anything is already at that path."""
    require_valid_manifest(manifest)
    if os.path.lexists(layout.env_dir):
        raise Phase1Error(f"{layout.env_dir} already exists. It is never repaired, replaced or deleted automatically; "
                          "remove it yourself (or say so) before creating it again.")
    if venv_layout.unsafe_component(layout.root, layout.env_dir.parent) is not None:
        raise Phase1Error("the app folder is reached through a link here; nothing is created")
    if not wheel_state(manifest, layout)["ready"]:
        raise Phase1Error("not every pinned wheel is here and verified; run fetch first")
    base = verify_base_python(base_python_candidate(), root=layout.root)
    scratch = prepare_scratch(layout.runtime / "setup")
    env = child_environment(layout, scratch)
    log = layout.receipts / "create-env.log"
    out(f"[env] creating {layout.env_dir} from {base['path']} (CPython {'.'.join(map(str, base['version']))})")
    code = run_logged([base["path"], "-I", "-m", "venv", str(layout.env_dir)], env=env, cwd=layout.root, log_path=log,
                      timeout_s=600)
    cfg = venv_layout.read_pyvenv_cfg(layout.env_dir) or {}
    if code != 0 or not layout.env_python().is_file():
        raise Phase1Error(f"the environment could not be created (exit {code}); see {log}")
    if not venv_layout.same_path(cfg.get("home", ""), Path(base["path"]).parent):
        raise Phase1Error("the environment was not built from the verified base Python")
    identity = venv_layout.base_identity(layout.env_dir)
    _write_json(layout.receipts / "environment.json", {"env": str(layout.env_dir), "base": base,
                                                         "base_identity": identity, "created": _utc_now()})
    out("[env] installing the pinned wheels offline (pip --no-index --require-hashes --no-deps)")
    started = time.monotonic()
    code = run_logged(pip_install_command(layout.env_python(), layout.wheels, LOCK_PATH), env=env, cwd=layout.wheels,
                      log_path=log, timeout_s=3600)
    if code != 0:
        raise Phase1Error(f"pip could not install the lock (exit {code}); see {log}")
    out(f"[env] installed in {time.monotonic() - started:.0f} s")
    shutil.rmtree(scratch / "tmp", ignore_errors=True)
    return {"base": base, "base_identity": identity, "log": str(log)}


def environment_assessment(layout: Layout) -> venv_layout.ChildAssessment:
    try:
        recorded = json.loads((layout.receipts / "environment.json").read_text(encoding="utf-8"))["base_identity"]
    except (OSError, ValueError, KeyError):
        recorded = None
    return venv_layout.assess_child(layout.env_dir, final_path=layout.env_dir, root=layout.root, parent=None,
                                    recorded_base=recorded)


def isolation_problems(layout: Layout, report: dict) -> list[str]:
    """What, in the environment's own report of itself, shows it reaching the app's ``.venv`` or a Qwen3 engine."""
    problems = []
    if not venv_layout.same_path(report.get("prefix", ""), layout.env_dir):
        problems.append("sys.prefix is not .venv-omnivoice")
    if venv_layout.same_path(report.get("prefix", ""), report.get("base_prefix", "")):
        problems.append("it is not a virtual environment")
    foreign = [layout.root / ".venv", layout.root / ".venv-qwen3"]
    for entry in report.get("path", []):
        if any(venv_layout.is_within(other, entry) for other in foreign):
            problems.append(f"sys.path reaches another environment: {entry}")
        if "site-packages" in entry.lower() and not venv_layout.is_within(layout.env_dir, entry):
            problems.append(f"sys.path holds a site-packages outside .venv-omnivoice: {entry}")
    if report.get("user_site_enabled"):
        problems.append("the user site-packages is enabled")
    return problems


_SELF_REPORT = ("import json, site, sys; print(json.dumps({'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
                "'executable': sys.executable, 'path': sys.path, 'user_site_enabled': bool(site.ENABLE_USER_SITE), "
                "'version': sys.version}))")


def installed_distributions(env_python: Path, env: dict) -> dict[str, str]:
    done = subprocess.run([str(env_python), "-I", "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                          capture_output=True, text=True, env=env, timeout=300,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0:
        raise Phase1Error(f"pip list failed: {done.stderr.strip()[-300:]}")
    return {re.sub(r"[-_.]+", "-", d["name"]).lower(): d["version"] for d in json.loads(done.stdout)}


def lock_difference(installed: dict[str, str], pins: list[tuple[str, str, str]]) -> list[str]:
    """Differences between what is installed (``pip`` itself excepted) and the lock, by name and version."""
    wanted = {name: version for name, version, _ in pins}
    have = {name: version for name, version in installed.items() if name != "pip"}
    diff = [f"missing {name}=={wanted[name]}" for name in sorted(set(wanted) - set(have))]
    diff += [f"extra {name}=={have[name]}" for name in sorted(set(have) - set(wanted))]
    diff += [f"{name} is {have[name]}, not {wanted[name]}" for name in sorted(set(wanted) & set(have))
             if have[name] != wanted[name]]
    return diff


def verify_env(manifest: dict, layout: Layout, evidence: Path, *, out: Callable[[str], None] = print) -> dict:
    """Identity, isolation, ``pip check``, installed == lock, and the worker's import/GPU probe (no model)."""
    assessment = environment_assessment(layout)
    if not assessment.identity_ok:
        raise Phase1Error(f".venv-omnivoice cannot be verified: {assessment.reason}")
    scratch = prepare_scratch(evidence / "scratch-verify")
    env = child_environment(layout, scratch)
    python = layout.env_python()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    me = subprocess.run([str(python), "-I", "-c", _SELF_REPORT], capture_output=True, text=True, env=env, timeout=120,
                        creationflags=flags)
    report = json.loads(me.stdout.strip().splitlines()[-1])
    check = subprocess.run([str(python), "-I", "-m", "pip", "check", "--disable-pip-version-check"], capture_output=True,
                           text=True, env=env, timeout=300, creationflags=flags)
    pins = parse_lock(LOCK_PATH.read_text(encoding="utf-8"))
    difference = lock_difference(installed_distributions(python, env), pins)
    # Smart App Control refuses the first load of each new unsigned native file while it evaluates it, then allows it
    # (the app's own engine probes retry the same way: tts.qwen3_setup.APPLICATION_CONTROL_ATTEMPTS). Only that refusal
    # is retried; every attempt's report is kept.
    attempts = []
    for attempt in range(1, APPLICATION_CONTROL_ATTEMPTS + 1):
        probe = run_worker({"mode": "probe", "report": str(evidence / f"probe-report-{attempt}.json")}, layout,
                           evidence, env=env, name=f"probe-{attempt}", timeout_s=900, out=out)
        attempts.append({"attempt": attempt, "status": probe.get("status"), "error": probe.get("error")})
        if probe.get("status") == "done" or APPLICATION_CONTROL_MARK not in str(probe.get("error", "")):
            break
    probe["attempts"] = attempts
    result = {"assessment": assessment.reason, "self_report": report, "isolation_problems": isolation_problems(layout, report),
              "pip_check": {"exit": check.returncode, "output": (check.stdout + check.stderr).strip()[-2000:]},
              "lock_difference": difference, "probe": probe,
              "hf_cache_files": _files_under(scratch / "cache" / "hf")}
    result["ok"] = (not result["isolation_problems"] and check.returncode == 0 and not difference
                    and probe.get("status") == "done" and (probe.get("gpu") or {}).get("kernel_ok") is True
                    and probe.get("network_attempts") == [] and not result["hf_cache_files"])
    _write_json(evidence / "verify-env.json", result)
    return result


# --------------------------------------------------------------------------- #
# The 10-second excerpt and its transcript
# --------------------------------------------------------------------------- #
def derive_excerpt(original: Path, destination: Path, *, seconds: int = EXCERPT_SECONDS,
                   end_frame: Optional[int] = None, allow_short: bool = False) -> dict:
    """Write the first *seconds* of *original* as its own decoded frames into a NEW file; return the excerpt's identity.

    The original is only ever opened for reading, and is hashed before and after: a change is an error. The crop is by
    whole sample frames (``seconds x sample rate``), never by bytes or by time rounding. A source shorter than that is a
    defect: refused, or (``allow_short``) taken whole and flagged. *end_frame* is an owner-accepted shorter whole-word
    crop (plan section 4): it starts at frame 0 too and may never reach past the first *seconds*.
    """
    original, destination = Path(original), Path(destination)
    if venv_layout.same_path(original, destination):
        raise Phase1Error("the excerpt may never be written over its original")
    if os.path.lexists(destination):
        raise Phase1Error(f"{destination.name} already exists; an excerpt is only ever written to a new file")
    before = (rt.sha256_file(original), os.stat(original).st_size, os.stat(original).st_mtime_ns)
    with wave.open(str(original), "rb") as source:
        params = source.getparams()
        if params.comptype != "NONE":
            raise Phase1Error(f"{original.name} is not plain PCM")
        end = seconds * params.framerate
        short = params.nframes < end
        if short and not allow_short:
            raise Phase1Error(f"{original.name} is only {params.nframes / params.framerate:.3f} s long, shorter than the "
                              f"{seconds} s the excerpt must be (a defect to report, not to work around)")
        take = min(end, params.nframes)
        if end_frame is not None:
            if type(end_frame) is not int or not 0 < end_frame <= take:
                raise Phase1Error(f"an excerpt must end inside the first {seconds} s (frame 1 to {take}), not at "
                                  f"{end_frame!r}")
            take = end_frame
        frames = source.readframes(take)
    if len(frames) != take * params.nchannels * params.sampwidth:
        raise Phase1Error(f"{original.name} ended before its header said it would")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    with open(part, "xb") as handle:
        with wave.open(handle, "wb") as target:
            target.setnchannels(params.nchannels)
            target.setsampwidth(params.sampwidth)
            target.setframerate(params.framerate)
            target.writeframes(frames)
    os.replace(part, destination)
    after = (rt.sha256_file(original), os.stat(original).st_size, os.stat(original).st_mtime_ns)
    if after != before:
        raise Phase1Error(f"{original.name} changed while its excerpt was taken")
    return {
        "preprocessing_version": PREPROCESSING_VERSION, "original": original.name, "original_sha256": before[0],
        "original_frames": params.nframes, "sample_rate": params.framerate, "channels": params.nchannels,
        "sample_width_bytes": params.sampwidth, "crop_start_frame": 0, "crop_end_frame": take,
        "crop_seconds": [0.0, take / params.framerate], "excerpt_duration_s": take / params.framerate,
        "excerpt_wav_sha256": rt.sha256_file(destination), "excerpt_pcm_sha256": hashlib.sha256(frames).hexdigest(),
        "short_source_defect": short,
        "crop_rule": "first-10s" if end_frame is None or end_frame == end else "owner-accepted-shorter-whole-word",
    }


def transcript_problem(text: str) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return "it is blank"
    if text != text.strip():
        return "it has leading or trailing spaces"
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return "it has control characters"
    return None


def validate_excerpt_transcript(full_text: str, excerpt_text: str, excerpt_sha256: Optional[str] = None) -> None:
    """Refuse an excerpt transcript that is not the approved full transcript's own opening words.

    Every word but the last must equal the approved transcript's word at that place exactly; the last may differ only in
    trailing punctuation (where the excerpt ends a sentence the full text continues). Nothing may be added, changed or
    left out in the middle, and the full-length transcript itself is refused: 10 seconds of a 15-second recording
    cannot be all of it.
    """
    problem = transcript_problem(excerpt_text)
    if problem:
        raise Phase1Error(f"the excerpt transcript is unusable: {problem}")
    if excerpt_sha256 is not None and rt.transcript_sha256(excerpt_text) != excerpt_sha256:
        raise Phase1Error("the excerpt transcript does not match its recorded SHA-256")
    full, words = full_text.split(), excerpt_text.split()
    if len(words) >= len(full):
        raise Phase1Error("the excerpt transcript is as long as the full-length transcript, which a 10-second excerpt "
                          "may never use")
    for index, word in enumerate(words[:-1]):
        if word != full[index]:
            raise Phase1Error(f"word {index + 1} ({word!r}) is not the approved transcript's ({full[index]!r})")
    last, expected = words[-1], full[len(words) - 1]
    if last != expected and (not last.rstrip(_TRAILING_MARKS) or last.rstrip(_TRAILING_MARKS) != expected.rstrip(_TRAILING_MARKS)):
        raise Phase1Error(f"the last word ({last!r}) is not the approved transcript's ({expected!r})")


def prompt_identity(*, excerpt: dict, transcript_sha256: str, model: dict, omnivoice_version: str,
                    preprocess_prompt: bool) -> tuple[str, dict]:
    """The key a reusable clone prompt is filed under: every input that shapes it, so a change never reuses an old one."""
    fields = {
        "schema": 1, "original_wav_sha256": excerpt["original_sha256"], "excerpt_wav_sha256": excerpt["excerpt_wav_sha256"],
        "crop": [excerpt["crop_start_frame"], excerpt["crop_end_frame"], excerpt["sample_rate"]],
        "preprocessing_version": excerpt["preprocessing_version"], "excerpt_transcript_sha256": transcript_sha256,
        "model": f"{model['repo']}@{model['revision']}", "omnivoice": omnivoice_version,
        "prompt_format_version": PROMPT_FORMAT_VERSION, "preprocess_prompt": bool(preprocess_prompt),
    }
    key = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return key, fields


def canonical_reference(reference_id: str) -> dict:
    """The registered recording and the approved full-length transcript of one clone, verified against each other."""
    voice = rt.get_voice("qwen3-" + reference_id.lower())
    if voice.kind != rt.KIND_CLONE or voice.reference_name != reference_id:
        raise Phase1Error(f"{reference_id} is not one of the six canonical clone references")
    path = rt.reference_path(voice)
    if rt.sha256_file(path) != voice.reference_sha256:
        raise Phase1Error(f"{path.name} is not the registered recording (SHA-256 differs)")
    full = rt.load_bundle()[reference_id]
    return {"reference_id": reference_id, "path": path, "wav_sha256": voice.reference_sha256, "full_text": full,
            "full_text_sha256": rt.transcript_sha256(full)}


# --------------------------------------------------------------------------- #
# The proof
# --------------------------------------------------------------------------- #
def run_worker(job: dict, layout: Layout, evidence: Path, *, env: dict, name: str, timeout_s: float,
               out: Callable[[str], None] = print, sample_gpu: bool = False) -> dict:
    """Run the worker in ``.venv-omnivoice`` on *job*; return its report (status ``done`` or ``failed``)."""
    job_path = evidence / f"{name}-job.json"
    _write_json(job_path, job)
    events: list[dict] = []
    sampler = _GpuSampler() if sample_gpu else None

    def on_line(line: str) -> None:
        if line.startswith("@@EVENT "):
            try:
                event = json.loads(line[len("@@EVENT "):])
            except ValueError:
                return
            events.append(event)
            if event.get("stage"):
                out(f"[{name}] {event.get('stage')}: {event.get('message', '')}")

    if sampler:
        sampler.start()
    started = time.monotonic()
    try:
        code = run_logged([str(layout.env_python()), "-I", str(WORKER_PATH), str(job_path)], env=env, cwd=evidence,
                          log_path=evidence / f"{name}-worker.log", timeout_s=timeout_s, on_line=on_line)
    finally:
        if sampler:
            sampler.stop()
    try:
        report = json.loads(Path(job["report"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {"status": "failed", "error": "the worker wrote no report"}
    terminal = [e for e in events if e.get("event") in ("done", "failed")]
    report.update({"exit_code": code, "wall_s": round(time.monotonic() - started, 2),
                   "terminal_events": [e.get("event") for e in terminal]})
    if code != 0 or len(terminal) != 1 or terminal[0].get("event") != "done":
        report["status"] = "failed"
    if sampler:
        report["nvidia_smi"] = sampler.summary()
    return report


class _GpuSampler:
    """``nvidia-smi`` memory in use on GPU 0, every half second, to see the worker's real peak beside PyTorch's own count."""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self.baseline = self._read()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _read() -> Optional[int]:
        try:
            done = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                                  capture_output=True, text=True, timeout=10,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return int(done.stdout.strip().splitlines()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            value = self._read()
            if value is not None:
                self.samples.append(value)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=15)

    def summary(self) -> dict:
        peak = max(self.samples) if self.samples else None
        return {"baseline_mib": self.baseline, "peak_mib": peak, "samples": len(self.samples),
                "peak_over_baseline_mib": (peak - self.baseline) if peak is not None and self.baseline is not None else None}


def wav_facts(path: Path) -> dict:
    """Duration, level and how much of it is sound: enough to call a WAV valid and audible, read with the stdlib only."""
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        raw = source.readframes(params.nframes)
    if params.sampwidth != 2:
        raise Phase1Error(f"{path.name} is not 16-bit PCM")
    samples = array.array("h")
    samples.frombytes(raw)
    peak = max((abs(s) for s in samples), default=0)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
    window = max(1, params.framerate // 100) * params.nchannels
    active = 0
    windows = 0
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window]
        windows += 1
        if math.sqrt(sum(s * s for s in chunk) / len(chunk)) >= 32768 * 10 ** (-45 / 20):
            active += 1

    def dbfs(value: float) -> Optional[float]:
        return round(20 * math.log10(value / 32768), 1) if value > 0 else None

    return {"sample_rate": params.framerate, "channels": params.nchannels, "frames": params.nframes,
            "duration_s": round(params.nframes / params.framerate, 3), "peak_dbfs": dbfs(peak), "rms_dbfs": dbfs(rms),
            "active_fraction": round(active / windows, 3) if windows else 0.0, "sha256": rt.sha256_file(path)}


def audible_problems(facts: dict) -> list[str]:
    problems = []
    if facts["duration_s"] < 3.0:
        problems.append(f"only {facts['duration_s']} s long")
    if facts["rms_dbfs"] is None or facts["rms_dbfs"] < -40:
        problems.append(f"too quiet to be speech (RMS {facts['rms_dbfs']} dBFS)")
    if facts["active_fraction"] < 0.3:
        problems.append(f"mostly silence ({facts['active_fraction']:.0%} of 10 ms windows above -45 dBFS)")
    return problems


def protected_state(root: Path) -> dict:
    """Fingerprints of what Phase 1 must never change: the app's and the Qwen3 environments, the six recordings, the
    full-length transcripts and the two existing dependency locks."""
    def fingerprint(env: Path) -> Optional[dict]:
        cfg = env / "pyvenv.cfg"
        if not cfg.is_file():
            return None
        site = env / "Lib" / "site-packages"
        names = sorted(p.name for p in site.iterdir()) if site.is_dir() else []
        scripts = sorted(p.name for p in (env / "Scripts").iterdir()) if (env / "Scripts").is_dir() else []
        return {"pyvenv_cfg": rt.sha256_file(cfg),
                "site_packages": hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest(),
                "scripts": hashlib.sha256("\n".join(scripts).encode("utf-8")).hexdigest()}

    refs = root / "files" / "Cloned-Voice-Uploads"
    return {
        ".venv": fingerprint(root / ".venv"), ".venv/engines/qwen3": fingerprint(root / ".venv" / "engines" / "qwen3"),
        ".venv-qwen3": fingerprint(root / ".venv-qwen3"),
        # v0.8.0 reference correction: every engine's own recordings, in their engine folders (Phase 1 ran when the six
        # shared WAVs sat at this folder's root; its recorded evidence is unchanged).
        "references": {p.relative_to(refs).as_posix(): rt.sha256_file(p) for p in sorted(refs.rglob("*.wav"))},
        "bundled_transcripts": rt.sha256_file(root / "scripts" / "tts" / "data" / "bundled_clone_transcripts.json"),
        "requirements": {name: rt.sha256_file(root / "scripts" / name)
                         for name in ("requirements.txt", "qwen3-requirements.txt")},
    }


def proof_settings(manifest: dict) -> dict:
    proof = manifest.get("proof") or {}
    for key in ("reference_id", "crop_end_frame", "excerpt_transcript", "excerpt_transcript_sha256"):
        if not proof.get(key):
            raise Phase1Error(f"the manifest's proof block has no {key}")
    if type(proof["crop_end_frame"]) is not int or proof["crop_end_frame"] <= 0:
        raise Phase1Error("the manifest's proof crop is not a whole number of frames")
    return proof


def prove(manifest: dict, layout: Layout, evidence: Path, *, timeout_s: float = 1800,
          out: Callable[[str], None] = print) -> dict:
    """One real 10-second clone, offline, end to end; the report says PASS only if every check holds."""
    require_valid_manifest(manifest)
    evidence.mkdir(parents=True, exist_ok=False)
    before = protected_state(layout.root)
    assessment = environment_assessment(layout)
    if not assessment.identity_ok:
        raise Phase1Error(f".venv-omnivoice cannot be verified: {assessment.reason}")
    out("[prove] hashing the pinned model snapshot")
    models = model_state(manifest, layout)
    if not models["ready"]:
        wrong = {rel: s for rel, s in models["files"].items() if s[0] != READY}
        raise Phase1Error(f"the model snapshot is NOT READY: {wrong or 'no audio_tokenizer folder'}")
    proof = proof_settings(manifest)
    reference = canonical_reference(proof["reference_id"])
    validate_excerpt_transcript(reference["full_text"], proof["excerpt_transcript"], proof["excerpt_transcript_sha256"])
    excerpt = derive_excerpt(reference["path"], evidence / "excerpt.wav", end_frame=proof["crop_end_frame"])
    key, identity = prompt_identity(excerpt=excerpt, transcript_sha256=proof["excerpt_transcript_sha256"],
                                    model=manifest["model"], omnivoice_version=manifest["upstream"]["version"],
                                    preprocess_prompt=GENERATION["preprocess_prompt"])
    scratch = prepare_scratch(evidence / "scratch")
    env = child_environment(layout, scratch)
    job = {
        "mode": "clone", "model_dir": str(layout.model_dir(manifest)), "excerpt_wav": str(evidence / "excerpt.wav"),
        "excerpt_frames": excerpt["crop_end_frame"], "sample_rate": excerpt["sample_rate"],
        "ref_text": proof["excerpt_transcript"], "text": NARRATION, "language": LANGUAGE, "generation": GENERATION,
        "dtype": DTYPE, "device": DEVICE, "seed": SEED, "output_wav": str(evidence / "clone.wav"),
        "prompt_path": str(scratch / "prompts" / f"{key}.pt"), "prompt_identity": identity,
        "report": str(evidence / "clone-report.json"),
    }
    out(f"[prove] cloning {reference['reference_id']} from its first {EXCERPT_SECONDS} s")
    worker = run_worker(job, layout, evidence, env=env, name="clone", timeout_s=timeout_s, out=out, sample_gpu=True)
    facts = wav_facts(evidence / "clone.wav") if (evidence / "clone.wav").is_file() else None
    after = protected_state(layout.root)
    checks = {
        "worker_done": worker.get("status") == "done",
        "network_attempts_none": worker.get("network_attempts") == [],
        "whisper_not_loaded": worker.get("asr_loaded") is False,
        "local_tokenizer_used": worker.get("audio_tokenizer_from_snapshot") is True,
        "hf_cache_empty": _files_under(scratch / "cache" / "hf") == [],
        "output_audible": facts is not None and not audible_problems(facts),
        "protected_state_unchanged": before == after,
        "excerpt_within_first_10s": excerpt["crop_start_frame"] == 0
        and excerpt["crop_end_frame"] == proof["crop_end_frame"] <= EXCERPT_SECONDS * excerpt["sample_rate"]
        and not excerpt["short_source_defect"],
    }
    report = {
        "verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "finished": _utc_now(),
        "reference": {k: (str(v) if isinstance(v, Path) else v) for k, v in reference.items() if k != "path"},
        "excerpt": excerpt, "excerpt_transcript": proof["excerpt_transcript"],
        "excerpt_transcript_sha256": proof["excerpt_transcript_sha256"], "excerpt_boundary": proof.get("boundary"),
        "prompt_cache": {"key": key, "identity": identity},
        "model": {"repo": manifest["model"]["repo"], "revision": manifest["model"]["revision"]},
        "narration": NARRATION, "generation": GENERATION, "dtype": DTYPE, "device": DEVICE, "seed": SEED,
        "output": facts, "output_problems": audible_problems(facts) if facts else ["no output WAV"],
        "worker": worker, "protected_before": before, "protected_after": after,
    }
    _write_json(evidence / "report.json", report)
    return report


# --------------------------------------------------------------------------- #
# Small helpers and the command line
# --------------------------------------------------------------------------- #
def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _files_under(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*") if p.is_file()) if Path(folder).is_dir() else []


def _new_evidence(layout: Layout, what: str) -> Path:
    return layout.evidence_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{what}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    fetch_p = sub.add_parser("fetch")
    fetch_p.add_argument("--only", choices=("wheels", "model"))
    sub.add_parser("create-env")
    sub.add_parser("verify-env")
    excerpt_p = sub.add_parser("excerpt")
    excerpt_p.add_argument("reference_id")
    sub.add_parser("prove")
    args = parser.parse_args(argv)
    layout = Layout(REPO_ROOT)
    manifest = load_manifest()
    try:
        if args.command == "plan":
            require_valid_manifest(manifest)
            print(json.dumps(download_plan(manifest, layout), indent=1))
        elif args.command == "fetch":
            print(json.dumps(fetch(manifest, layout, wheels=args.only != "model", model=args.only != "wheels"), indent=1))
        elif args.command == "create-env":
            print(json.dumps(create_env(manifest, layout), indent=1, default=str))
        elif args.command == "verify-env":
            result = verify_env(manifest, layout, _new_evidence(layout, "verify"))
            print(json.dumps({k: result[k] for k in ("ok", "assessment", "isolation_problems", "lock_difference",
                                                      "pip_check", "hf_cache_files")}, indent=1))
            return 0 if result["ok"] else 1
        elif args.command == "excerpt":
            reference = canonical_reference(args.reference_id)
            evidence = _new_evidence(layout, f"excerpt-{args.reference_id}")
            identity = derive_excerpt(reference["path"], evidence / f"{args.reference_id}-first-10s.wav")
            _write_json(evidence / "excerpt.json", identity)
            print(json.dumps({"folder": str(evidence), **identity}, indent=1))
        elif args.command == "prove":
            report = prove(manifest, layout, _new_evidence(layout, "prove"))
            print(json.dumps({"verdict": report["verdict"], "checks": report["checks"], "output": report["output"]},
                             indent=1))
            return 0 if report["verdict"] == "PASS" else 1
    except Phase1Error as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
