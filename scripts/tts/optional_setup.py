"""optional_setup.py — what the four optional voice components need on this computer, and what acquiring them costs.

v0.7.0 P05A (plan Revision 2 §5.4; owner rulings Q14-Q20, Q32). One planner for the first-run wizard and the in-app
Install & Continue, GUI-independent and acquisition-free. It answers, before anything is downloaded: which of Kokoro,
Chatterbox Turbo, Qwen3 CustomVoice and Qwen3 Cloned Voices / Base are ready, missing, damaged, unsupported, busy,
blocked by a bad bundled reference/transcript, or unproved; what each selection would download, reuse, copy, occupy and
need as temporary headroom; what the always-installed base packages cost on top; and how each figure is known.

Two contexts, matching the approved execution home:

* :func:`estimate` -- **pre-venv** (the first-run wizard, a base interpreter, before the app's environment exists).
  Manifest-derived upper bounds only: it reads the tracked Qwen3 manifest and this module's measured tables, stats no
  model, probes nothing and proves nothing, so every supported component is ``unverified`` and every figure is the most
  that selection could cost. Imports nothing beyond the standard library, ``shared.optional_setup_protocol``,
  ``shared.venv_layout``, ``tts.qwen3_runtime`` and ``tts.voice_registry`` (a test proves this in a bare interpreter).
* :func:`plan` -- **main** (the setup worker or the app, in the verified ``.venv``). Reads the real state through the
  existing authorities: ``qwen3_runtime`` for the engine path, statuses, bundle and references, and
  ``qwen3_setup.plan_install`` for the exact per-file Qwen3 plan (reused, shared and downloaded bytes, the shared
  files counted once). Kokoro and Chatterbox files are looked up in the in-tree Hugging Face cache without importing
  either library. Engine health that only a probe can prove is a fact the caller supplies; without it the component is
  ``unverified``, never assumed healthy.

Nothing here downloads, installs, loads a model, opens a socket or starts a process -- except the optional, bounded
``nvidia-smi`` query when a caller asks for hardware facts (``probe_hardware=True``). Acquisition is P05B.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from shared import optional_setup_protocol as proto
from shared import venv_layout
from shared.optional_setup_protocol import (APPROXIMATE, BAD_BUNDLE, CHATTERBOX, DAMAGED, EXACT, KOKORO, MANIFEST,
                                            MISSING, NOT_KNOWN, QWEN3_BASE, QWEN3_CUSTOMVOICE, READY, UNSUPPORTED,
                                            UNVERIFIED, ZERO, Figure)
from tts import qwen3_runtime as rt
from tts import voice_registry

CONTEXT_PRE_VENV = "pre-venv"
CONTEXT_MAIN = "main"
PLAN_SCHEMA = 1

# --------------------------------------------------------------------------- #
# What the libraries fetch on first use, measured (the app pins none of these revisions)
# --------------------------------------------------------------------------- #
#: kokoro 0.9.4 downloads from ``hexgrad/Kokoro-82M`` at whatever revision ``main`` names, through ``hf_hub_download``:
#: ``config.json`` and the weights when a pipeline is built, one ``voices/<id>.pt`` the first time each voice speaks.
#: Sizes measured from the in-tree cache on HOME-PC, 2026-10-25, at the revision below. Approximate by definition: the
#: upstream repository can change, and nothing here can tell without asking the network.
KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_MEASURED_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_MODEL_FILES: dict[str, int] = {"config.json": 2_351, "kokoro-v1_0.pth": 327_212_226}
KOKORO_VOICE_FILES: dict[str, int] = {
    "af_bella": 523_425, "af_heart": 523_425, "am_fenrir": 523_430, "am_michael": 523_435, "am_onyx": 523_420,
    "am_puck": 523_420, "bf_emma": 523_420, "bm_daniel": 523_430, "bm_george": 523_430,
}
#: misaki's English G2P (both Kokoro English pipelines) runs ``spacy.cli.download("en_core_web_sm")`` -- a pip install
#: from outside PyPI's pinned set -- when the package is absent. Installed size measured on HOME-PC (3.8.0); its download
#: size is not recorded anywhere local.
SPACY_ENGLISH = "en_core_web_sm"
SPACY_ENGLISH_INSTALLED_BYTES = 15_248_495

#: chatterbox-tts 0.1.7 ``ChatterboxTurboTTS.from_pretrained`` (and the setup pre-download) fetch
#: ``ResembleAI/chatterbox-turbo`` at ``main`` with the patterns ``*.safetensors *.json *.txt *.pt *.model``. Measured
#: from the in-tree cache on HOME-PC, 2026-10-25. ``from_local`` loads every file but ``s3gen.safetensors``, which the
#: patterns still fetch (P05B may drop it).
CHATTERBOX_REPO = "ResembleAI/chatterbox-turbo"
CHATTERBOX_MEASURED_REVISION = "749d1c1a46eb10492095d68fbcf55691ccf137cd"
CHATTERBOX_FILES: dict[str, int] = {
    "added_tokens.json": 418, "conds.pt": 169_454, "merges.txt": 456_318, "s3gen.safetensors": 1_056_484_620,
    "s3gen_meanflow.safetensors": 1_064_875_036, "special_tokens_map.json": 470,
    "t3_turbo_v1.safetensors": 1_915_480_052, "tokenizer_config.json": 3_878, "ve.safetensors": 5_695_784,
    "vocab.json": 999_186,
}
CHATTERBOX_UNUSED_BY_TURBO = frozenset({"s3gen.safetensors"})

#: The app's own ``.venv`` (main requirements, Kokoro and Chatterbox packages included; the Qwen3 engine under
#: ``engines/`` excluded), measured on HOME-PC 2026-10-25: 53,417 files. What pip downloads to build it is not recorded
#: anywhere local, so that figure is unknown rather than guessed.
BASE_PACKAGES_INSTALLED_BYTES = 2_494_787_313

#: ``qwen3_setup.DISK_MARGIN_BYTES``: the free space the Qwen3 installer insists on beyond what it writes (a test pins
#: that they agree; repeated so the pre-venv estimate need not import the installer).
QWEN3_DISK_MARGIN_BYTES = 2 * 10**9

#: Kokoro and Chatterbox run in the app's own environment; their pinned wheels need CPython 3.11 or 3.12 (64-bit).
LOCAL_ENGINE_PYTHON = ((3, 11), (3, 12))


def hf_hub_root() -> Path:
    """The in-tree Hugging Face cache the app always points Kokoro and Chatterbox at (``bootstrap._configure_hf_cache``)."""
    return rt.repo_root() / "files" / "runtime-data" / "models" / "huggingface" / "hub"


def kokoro_roster() -> tuple[str, ...]:
    """The Kokoro voices the app offers, by voice id, in registry order."""
    return tuple(v.voice_id for v in voice_registry.VOICES if v.backend == "kokoro")


# --------------------------------------------------------------------------- #
# Plan units: one thing that is acquired once, however many components need it
# --------------------------------------------------------------------------- #
@dataclass
class Unit:
    id: str
    label: str
    components: list[str]
    state: str  # READY | MISSING | DAMAGED | UNVERIFIED
    download: Figure = ZERO  # fetched from the network
    reused: Figure = ZERO  # already on this computer and kept
    local_copy: Figure = ZERO  # copied or linked from another local file instead of downloaded
    disk: Figure = ZERO  # newly occupied once installed (an upper bound where a link would cost nothing)
    temp: Figure = ZERO  # extra free space needed while installing, released afterwards
    note: str = ""

    def to_json(self) -> dict:
        return {"id": self.id, "label": self.label, "components": list(self.components), "state": self.state,
                "download": self.download.to_json(), "reused": self.reused.to_json(),
                "local_copy": self.local_copy.to_json(), "disk": self.disk.to_json(), "temp": self.temp.to_json(),
                "note": self.note}


@dataclass
class ComponentPlan:
    id: str
    selected: bool
    readiness: str
    reason: str
    units: list[str] = field(default_factory=list)

    @property
    def consent_scope(self) -> Optional[str]:
        return proto.acquisition_scope(self.readiness)


_UNIT_STATES = (READY, MISSING, DAMAGED, UNVERIFIED)


def _files_unit(unit_id: str, label: str, component: str, folder: Optional[Path], files: Mapping[str, int],
                *, unreachable: str = "", optional: Iterable[str] = ()) -> Unit:
    """A unit of upstream files measured at one revision: missing, present at the measured size, or unverifiable.

    A file of another size is not called damaged -- the upstream repository is unpinned, so it may simply be newer --
    and is not called healthy either: the unit is unverified.
    """
    if unreachable:
        return Unit(unit_id, label, [component], UNVERIFIED, note=unreachable)
    optional = set(optional)
    missing, odd, present = [], [], 0
    for name, size in files.items():
        path = None if folder is None else folder.joinpath(*name.split("/"))
        try:
            actual = path.stat().st_size if path is not None and path.is_file() else None
        except OSError:
            actual = None
        if actual is None:
            missing.append((name, size))
        elif actual != size:
            odd.append(name)
        else:
            present += actual
    if odd:
        return Unit(unit_id, label, [component], UNVERIFIED,
                    note=f"{', '.join(odd)} differ from the size measured upstream, so they cannot be verified here")
    needed = [(n, s) for n, s in missing if n not in optional]
    if not needed:
        return Unit(unit_id, label, [component], READY, reused=Figure(present, EXACT))
    fetched = sum(s for _, s in missing)  # the library fetches the optional files too while it is at it
    return Unit(unit_id, label, [component], MISSING, download=Figure(fetched, APPROXIMATE),
                reused=Figure(present, EXACT), disk=Figure(fetched, APPROXIMATE), temp=Figure(0, APPROXIMATE),
                note=f"{len(needed)} of {len(files)} files to download (sizes measured upstream; not pinned)")


def _hf_snapshot(repo_id: str) -> tuple[Optional[Path], str]:
    """``(snapshot folder or None, unreachable reason)`` for *repo_id* in the in-tree cache. Reads two small things."""
    folder = hf_hub_root() / ("models--" + repo_id.replace("/", "--"))
    if venv_layout.unsafe_component(rt.repo_root(), folder) is not None:
        return None, "the model cache is reached through a link, so its contents cannot be vouched for"
    try:
        revision = (folder / "refs" / "main").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None, ""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return None, ""
    snapshot = folder / "snapshots" / revision
    if venv_layout.unsafe_component(rt.repo_root(), snapshot) is not None:
        return None, "the model cache is reached through a link, so its contents cannot be vouched for"
    return (snapshot if snapshot.is_dir() else None), ""


def _package_present(name: str) -> bool:
    """Whether a top-level package is installed in this interpreter's environment (found, not imported)."""
    import importlib.util

    return importlib.util.find_spec(name) is not None


# --------------------------------------------------------------------------- #
# Facts the caller supplies (what only a probe, a lock or a running process knows)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Facts:
    """Caller-supplied facts. ``health`` maps a component to ``True`` (its engine was proved to load), ``False``
    (proved broken) or ``None``/absent (not proved: unverified). ``busy`` names components something else holds now."""

    health: Mapping[str, Optional[bool]] = field(default_factory=dict)
    busy: frozenset = frozenset()
    python: tuple = tuple(sys.version_info[:2])
    is_64bit: bool = sys.maxsize > 2**32
    probe_hardware: bool = False
    package_present: Callable[[str], bool] = _package_present


def _health_state(facts: Facts, component: str) -> tuple[str, str]:
    proved = facts.health.get(component)
    if proved is True:
        return READY, ""
    if proved is False:
        return DAMAGED, f"the {proto.LABELS[component]} engine was proved not to load; it needs repair"
    return UNVERIFIED, f"the {proto.LABELS[component]} engine has not been proved to load on this computer yet"


def _local_engine_unsupported(facts: Facts) -> str:
    if not facts.is_64bit:
        return "it needs 64-bit Python"
    if tuple(facts.python[:2]) not in LOCAL_ENGINE_PYTHON:
        return (f"its packages need Python 3.11 or 3.12, and this app's environment uses "
                f"{facts.python[0]}.{facts.python[1]}")
    return ""


def _reference_problem() -> str:
    """The first problem with the six bundled reference recordings, or ``""`` (hashes six small files)."""
    for voice in rt.QWEN3_VOICES:
        if voice.kind == rt.KIND_CLONE:
            ok, reason = rt.reference_status(voice)
            if not ok:
                return reason
    return ""


# --------------------------------------------------------------------------- #
# The main-context units, from the real state
# --------------------------------------------------------------------------- #
def _kokoro_units(facts: Facts) -> list[Unit]:
    snapshot, unreachable = _hf_snapshot(KOKORO_REPO)
    units = [_files_unit("kokoro-model", "Kokoro model", KOKORO, snapshot, KOKORO_MODEL_FILES,
                         unreachable=unreachable)]
    for voice in kokoro_roster():
        unit_id = f"kokoro-voice:{voice}"
        if voice not in KOKORO_VOICE_FILES:
            present = snapshot is not None and (snapshot / "voices" / f"{voice}.pt").is_file()
            units.append(Unit(unit_id, f"Kokoro voice {voice}", [KOKORO], UNVERIFIED if present else MISSING,
                              download=ZERO if present else NOT_KNOWN, disk=ZERO if present else NOT_KNOWN,
                              note="no measured size for this voice"))
            continue
        units.append(_files_unit(unit_id, f"Kokoro voice {voice}", KOKORO, snapshot,
                                 {f"voices/{voice}.pt": KOKORO_VOICE_FILES[voice]}, unreachable=unreachable))
    if facts.package_present(SPACY_ENGLISH):
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], READY))
    else:
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], MISSING, download=NOT_KNOWN,
                          disk=Figure(SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE), temp=NOT_KNOWN,
                          note="a Python package misaki installs with pip on first use; download size not known locally"))
    return units


def _chatterbox_units() -> list[Unit]:
    snapshot, unreachable = _hf_snapshot(CHATTERBOX_REPO)
    return [_files_unit("chatterbox-model", "Chatterbox Turbo model", CHATTERBOX, snapshot, CHATTERBOX_FILES,
                        unreachable=unreachable, optional=CHATTERBOX_UNUSED_BY_TURBO)]


def _qwen_engine_unit() -> tuple[Unit, str]:
    """The shared engine as a unit, with the reason when it is not ready. Judged by ``qwen3_runtime`` alone."""
    unit_id, label = "qwen3-engine", "Qwen3 voice engine (shared)"
    folder = rt.venv_dir()
    ok, reason = rt.environment_status()
    if ok:
        return Unit(unit_id, label, [], READY), ""
    install = dict(download=Figure(rt.environment_download_bytes(), APPROXIMATE),
                   disk=Figure(rt.environment_installed_bytes(), APPROXIMATE),
                   temp=Figure(rt.environment_download_bytes(), APPROXIMATE),
                   note="the locked packages; pip's download cache is kept until the install succeeds")
    problem = rt.environment_location_problem(folder)
    if problem:  # a link or an outside location: no install can fix that, and nothing here can vouch for it
        return Unit(unit_id, label, [], UNVERIFIED, note=problem), reason
    if not os.path.lexists(folder):
        return Unit(unit_id, label, [], MISSING, **install), reason
    if rt.is_nested(folder) and rt.environment_record(folder).get("stage") not in (rt.STAGE_CREATING,
                                                                                    rt.STAGE_REMOVING):
        assessment = rt.nested_assessment(folder)
        if assessment.state == venv_layout.UNVERIFIED:
            return Unit(unit_id, label, [], UNVERIFIED, note=assessment.reason), reason
    return Unit(unit_id, label, [], DAMAGED, **install), reason


def _qwen_model_units(selected: tuple[str, ...]) -> list[Unit]:
    """One unit per selected Qwen3 model, from the installer's own plan (``qwen3_setup.plan_install``)."""
    from tts import qwen3_setup

    keys = tuple(proto.QWEN3_MODEL_KEYS[c] for c in selected)
    install_plan = qwen3_setup.plan_install(keys)
    units = []
    for component, model in zip(selected, install_plan.models):
        unit_id, label = f"qwen3-model:{model.key}", f"Qwen3 {model.label} model"
        ok, reason = rt.model_status(model.key)
        if ok:
            units.append(Unit(unit_id, label, [component], READY, reused=Figure(model.total_bytes, MANIFEST)))
            continue
        if rt.marker_path(model.key).is_file():
            units.append(Unit(unit_id, label, [component], DAMAGED, download=NOT_KNOWN, disk=NOT_KNOWN,
                              note=reason + " A full check decides what is fetched again (at most the whole model)."))
            continue
        have = sum(f.size for f in model.files if f.action == "have")
        units.append(Unit(unit_id, label, [component], MISSING, download=Figure(model.download_bytes, MANIFEST),
                          reused=Figure(have, MANIFEST), local_copy=Figure(model.shared_bytes, MANIFEST),
                          disk=Figure(model.download_bytes + model.shared_bytes, MANIFEST),
                          note="shared files are linked from the other model where possible, otherwise copied"))
    return units


# --------------------------------------------------------------------------- #
# The pre-venv units, from manifests and measurements only
# --------------------------------------------------------------------------- #
def _estimated_units(selected: tuple[str, ...]) -> list[Unit]:
    units: list[Unit] = []
    if KOKORO in selected:
        model = sum(KOKORO_MODEL_FILES.values())
        units.append(Unit("kokoro-model", "Kokoro model", [KOKORO], MISSING, download=Figure(model, APPROXIMATE),
                          disk=Figure(model, APPROXIMATE), temp=Figure(0, APPROXIMATE)))
        for voice in kokoro_roster():
            size = KOKORO_VOICE_FILES.get(voice)
            figure = NOT_KNOWN if size is None else Figure(size, APPROXIMATE)
            units.append(Unit(f"kokoro-voice:{voice}", f"Kokoro voice {voice}", [KOKORO], MISSING, download=figure,
                              disk=figure))
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], MISSING, download=NOT_KNOWN,
                          disk=Figure(SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE), temp=NOT_KNOWN))
    if CHATTERBOX in selected:
        total = sum(CHATTERBOX_FILES.values())
        units.append(Unit("chatterbox-model", "Chatterbox Turbo model", [CHATTERBOX], MISSING,
                          download=Figure(total, APPROXIMATE), disk=Figure(total, APPROXIMATE),
                          temp=Figure(0, APPROXIMATE)))
    qwen = [c for c in (QWEN3_CUSTOMVOICE, QWEN3_BASE) if c in selected]
    if qwen and rt.platform_supported():
        download = rt.environment_download_bytes()
        units.append(Unit("qwen3-engine", "Qwen3 voice engine (shared)", qwen, MISSING,
                          download=Figure(download, APPROXIMATE), disk=Figure(rt.environment_installed_bytes(),
                                                                                 APPROXIMATE),
                          temp=Figure(download, APPROXIMATE)))
        shared = rt.shared_file_bytes()
        for index, component in enumerate(qwen):
            spec = rt.model_spec(proto.QWEN3_MODEL_KEYS[component])
            copy = shared if index else 0  # the second model takes the shared files from the first, locally
            units.append(Unit(f"qwen3-model:{spec.key}", f"Qwen3 {spec.label} model", [component], MISSING,
                              download=Figure(spec.total_bytes - copy, MANIFEST), local_copy=Figure(copy, MANIFEST),
                              disk=Figure(spec.total_bytes, MANIFEST)))
    return units


# --------------------------------------------------------------------------- #
# Putting a plan together
# --------------------------------------------------------------------------- #
@dataclass
class Plan:
    context: str
    selected: tuple[str, ...]
    components: list[ComponentPlan]
    units: list[Unit]
    hardware: dict
    upper_bound: bool
    notes: list[str]

    def unit(self, unit_id: str) -> Unit:
        return next(u for u in self.units if u.id == unit_id)

    @property
    def acquire_units(self) -> list[str]:
        """Units fetched under the consent the selected components need now (each once)."""
        if self.upper_bound:
            return [u.id for u in self.units if u.state in (MISSING, DAMAGED)]
        chosen = {c.id for c in self.components if c.selected and c.consent_scope is not None}
        return [u.id for u in self.units if u.state in (MISSING, DAMAGED) and chosen & set(u.components)]

    @property
    def pending_units(self) -> list[str]:
        """Units an unverified component would need once it is proved: disclosed, not acquired."""
        acquire = set(self.acquire_units)
        waiting = {c.id for c in self.components if c.selected and c.readiness == UNVERIFIED}
        return [u.id for u in self.units
                if u.id not in acquire and u.state in (MISSING, DAMAGED) and waiting & set(u.components)]

    def total(self, name: str, unit_ids: Iterable[str]) -> Figure:
        wanted = set(unit_ids)
        figures = [getattr(u, name) for u in self.units if u.id in wanted]
        if name == "temp" and any(u.id.startswith("qwen3-") for u in self.units if u.id in wanted):
            figures.append(Figure(QWEN3_DISK_MARGIN_BYTES, EXACT))  # the installer's own margin, once
        return proto.add_figures(figures)


def _base_packages() -> dict:
    return {
        "download": NOT_KNOWN.to_json(),
        "installed": Figure(BASE_PACKAGES_INSTALLED_BYTES, APPROXIMATE).to_json(),
        "note": ("The app's Python packages are installed whatever is chosen here, and include the Kokoro and "
                 "Chatterbox engines' packages (torch among them) even when every optional model is skipped. The sizes "
                 "above for each choice are the models and the Qwen3 engine only, on top of these packages."),
    }


def _hardware(facts: Facts, context: str) -> dict:
    gpu: dict = {"probed": False, "name": None, "memory_mb": None}
    if not rt.platform_supported():
        qwen = rt.platform_reason()
    elif context == CONTEXT_MAIN and facts.probe_hardware:
        found = rt.detect_gpu()
        gpu = {"probed": True, "name": None if found is None else found.name,
               "memory_mb": None if found is None else found.memory_mb}
        qwen = rt.hardware_summary()
    else:
        qwen = ("Qwen3 runs on an NVIDIA GPU when one is found and otherwise on the CPU, much more slowly; this "
                "computer's GPU has not been checked yet.")
    return {
        "platform": sys.platform,
        "is_64bit": facts.is_64bit,
        "python": None if context == CONTEXT_PRE_VENV else ".".join(str(p) for p in facts.python[:2]),
        "gpu": gpu,
        "qwen3": qwen,
        "limits": [
            "Windows 10/11 x64 are qualification targets; other Windows builds and security policies are unproved.",
            "Qwen3 is Windows-only and needs the app's CPython 3.12 (its packages are locked for Windows x64).",
            "Kokoro and Chatterbox need the app's environment on CPython 3.11 or 3.12, 64-bit.",
            "No speed is promised: every engine also runs on the CPU, more slowly.",
        ],
    }


def _assemble(context: str, selected: tuple[str, ...], states: dict[str, tuple[str, str]], units: list[Unit],
              facts: Facts, upper_bound: bool) -> Plan:
    merged: dict[str, Unit] = {}
    for unit in units:  # a unit needed by two components (the Qwen3 engine) is one unit, counted once
        if unit.id in merged:
            merged[unit.id].components.extend(c for c in unit.components if c not in merged[unit.id].components)
        else:
            merged[unit.id] = unit
    components = []
    for name in proto.COMPONENTS:
        readiness, reason = states.get(name, (UNVERIFIED, "not selected, so not checked"))
        components.append(ComponentPlan(name, name in selected, readiness, reason,
                                        [u.id for u in merged.values() if name in u.components]))
    notes = ["Sizes use decimal units (1 GB = 1,000,000,000 bytes)."]
    if upper_bound:
        notes.append("These are the most each choice could cost. Files already on this computer are found and reused "
                     "once the app's environment is ready, before anything is downloaded.")
    if any(u.state in (MISSING, DAMAGED) and u.download.basis in (APPROXIMATE, proto.UNKNOWN) for u in merged.values()):
        notes.append("Some downloads come from upstream repositories this app does not pin; their sizes were measured "
                     "once and may change. A download larger than agreed needs a new confirmation.")
    return Plan(context, selected, components, list(merged.values()), _hardware(facts, context), upper_bound, notes)


def estimate(components: Iterable[str], *, facts: Optional[Facts] = None) -> Plan:
    """The pre-venv plan: manifest-derived upper bounds, nothing proved. Reads no model file, starts no process."""
    facts = facts or Facts()
    selected = proto.canonical_selection(components)
    states: dict[str, tuple[str, str]] = {}
    for name in selected:
        if name in proto.QWEN3_MODEL_KEYS and not rt.platform_supported():
            states[name] = (UNSUPPORTED, rt.platform_reason())
        elif not facts.is_64bit:
            states[name] = (UNSUPPORTED, f"{proto.LABELS[name]} needs 64-bit Windows and Python")
        else:
            states[name] = (UNVERIFIED, "checked once the app's environment is ready, before anything is downloaded")
    units = [u for u in _estimated_units(selected) if all(states[c][0] != UNSUPPORTED for c in u.components)]
    return _assemble(CONTEXT_PRE_VENV, selected, states, units, facts, upper_bound=True)


def plan(components: Iterable[str], *, facts: Optional[Facts] = None) -> Plan:
    """The main-context plan from the real state. Read-only; probes only what *facts* asks for."""
    facts = facts or Facts()
    selected = proto.canonical_selection(components)
    states: dict[str, tuple[str, str]] = {}
    units: list[Unit] = []
    local_unsupported = _local_engine_unsupported(facts)
    references = _reference_problem() if {CHATTERBOX, QWEN3_BASE} & set(selected) else ""

    for name in (KOKORO, CHATTERBOX):
        if name not in selected:
            continue
        if local_unsupported:
            states[name] = (UNSUPPORTED, f"{proto.LABELS[name]} cannot run here: {local_unsupported}.")
            continue
        own = _kokoro_units(facts) if name == KOKORO else _chatterbox_units()
        units.extend(own)
        health, health_reason = _health_state(facts, name)
        parts = [u.state for u in own] + [health]
        if name == CHATTERBOX and references:
            parts.append(BAD_BUNDLE)
        if name in facts.busy:
            parts.append(proto.BUSY)
        readiness = proto.combine_readiness(parts)
        reason = {BAD_BUNDLE: references, proto.BUSY: "another task is using it right now"}.get(readiness) \
            or health_reason or next((u.note for u in own if u.state == readiness), "")
        states[name] = (readiness, reason)

    qwen = tuple(c for c in (QWEN3_CUSTOMVOICE, QWEN3_BASE) if c in selected)
    if qwen and not rt.platform_supported():
        for name in qwen:
            states[name] = (UNSUPPORTED, rt.platform_reason())
    elif qwen:
        engine, engine_reason = _qwen_engine_unit()
        engine.components = list(qwen)
        units.append(engine)
        try:
            models = _qwen_model_units(qwen)
        except rt.Qwen3Unavailable as exc:
            models = [Unit(f"qwen3-model:{proto.QWEN3_MODEL_KEYS[c]}", f"Qwen3 {proto.LABELS[c]} model", [c],
                           UNVERIFIED, note=str(exc)) for c in qwen]
        units.extend(models)
        bundle_ok, bundle_reason = rt.bundle_status() if QWEN3_BASE in qwen else (True, "")
        for name, model in zip(qwen, models):
            parts = [engine.state, model.state]
            bad = (bundle_reason if not bundle_ok else references) if name == QWEN3_BASE else ""
            if bad:
                parts.append(BAD_BUNDLE)
            if name in facts.busy:
                parts.append(proto.BUSY)
            readiness = proto.combine_readiness(parts)
            if readiness == BAD_BUNDLE:
                reason = bad
            elif readiness == proto.BUSY:
                reason = "another task is using it right now"
            elif readiness == engine.state and readiness != READY:
                reason = engine_reason or engine.note
            else:
                reason = model.note
            states[name] = (readiness, reason)
    return _assemble(CONTEXT_MAIN, selected, states, units, facts, upper_bound=False)


# --------------------------------------------------------------------------- #
# The plan as data (what the worker reports and what consent is bound to)
# --------------------------------------------------------------------------- #
_TOTALS = ("download", "reused", "local_copy", "disk", "temp")


def plan_to_json(plan_: Plan) -> dict:
    acquire, pending = plan_.acquire_units, plan_.pending_units
    data = {
        "schema": PLAN_SCHEMA,
        "context": plan_.context,
        "upper_bound": plan_.upper_bound,
        "selected": list(plan_.selected),
        "defaults": dict(proto.WIZARD_DEFAULTS),
        "components": [{"id": c.id, "label": proto.LABELS[c.id], "selected": c.selected,
                        "default": proto.WIZARD_DEFAULTS[c.id], "readiness": c.readiness, "reason": c.reason,
                        "consent_scope": c.consent_scope, "units": list(c.units),
                        "download": plan_.total("download", c.units).to_json()} for c in plan_.components],
        "units": [u.to_json() for u in plan_.units],
        "acquire_units": acquire,
        "pending_units": pending,
        "totals": {name: plan_.total(name, acquire).to_json() for name in _TOTALS},
        "pending": {"download": plan_.total("download", pending).to_json()},
        "base_packages": _base_packages(),
        "hardware": plan_.hardware,
        "notes": list(plan_.notes),
    }
    data["fingerprint"] = fingerprint(data)
    return data


def fingerprint(data: dict) -> str:
    """SHA-256 of a plan's canonical JSON, without its own fingerprint: what a consent is bound to."""
    body = {k: v for k, v in data.items() if k != "fingerprint"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def consent_for(data: dict, scope: str = proto.SCOPE_INSTALL) -> proto.Consent:
    """The consent a person gives by confirming *data* (a :func:`plan_to_json` plan) for its selected components."""
    download = data["totals"]["download"]["bytes"]
    return proto.Consent(scope, tuple(data["selected"]), tuple(data["acquire_units"]),
                         0 if download is None else download, data["fingerprint"])


def format_bytes(figure: Figure) -> str:
    """A figure for people: ``"about 4.5 GB"``, ``"at least 12 MB"``, ``"unknown"`` -- never more precise than known."""
    if figure.bytes is None:
        return "unknown"
    text = rt.format_bytes(figure.bytes)
    return {APPROXIMATE: f"about {text}", proto.AT_LEAST: f"at least {text}"}.get(figure.basis, text)
