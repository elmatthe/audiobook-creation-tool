"""optional_setup.py — what the five optional voice components need on this computer, and what acquiring them costs.

v0.7.0 P05A (plan Revision 2 §5.4; owner rulings Q14-Q20, Q32). One planner for the first-run wizard and the in-app
Install & Continue, GUI-independent and acquisition-free. It answers, before anything is downloaded: which of Kokoro,
Chatterbox Turbo, Qwen3 CustomVoice, Qwen3 Cloned Voices / Base and (v0.8.0) OmniVoice are ready, missing, damaged,
unsupported, busy,
blocked by a bad bundled reference/transcript, or unproved; what each selection would download, reuse, copy, occupy and
need as temporary headroom; what the always-installed base packages cost on top; and how each figure is known.

Two contexts, matching the approved execution home:

* :func:`estimate` -- **pre-venv** (the first-run wizard, a base interpreter, before the app's environment exists).
  Manifest-derived upper bounds only: it reads the tracked Qwen3 manifest and the pinned tables, stats no model,
  probes nothing and proves nothing, so every supported component is ``unverified`` and every figure is the most that
  selection could cost. Imports nothing beyond the standard library, ``shared.optional_setup_protocol``,
  ``shared.venv_layout``, ``tts.model_assets``, ``tts.qwen3_runtime`` and ``tts.voice_registry`` (a test proves this in
  a bare interpreter).
* :func:`plan` -- **main** (the setup worker or the app, in the verified ``.venv``). Reads the real state through the
  existing authorities: ``qwen3_runtime`` for the engine path, statuses, bundle and references, and
  ``qwen3_setup.plan_install`` for the exact per-file Qwen3 plan (reused, shared and downloaded bytes, the shared
  files counted once). Kokoro and Chatterbox files are checked against their pinned identities (``tts.model_assets``:
  repository, commit, size, SHA-256) in the in-tree Hugging Face cache without importing either library. Engine health
  that only a probe can prove is a fact the caller supplies; without it the component is ``unverified``, never assumed
  healthy.

Nothing here downloads, installs, loads a model, opens a socket or starts a process -- except the optional, bounded
``nvidia-smi`` query when a caller asks for hardware facts (``probe_hardware=True``). Acquisition is P05B.

P05B Stage 1: every unit names the exact *source* it would be acquired from (a Hugging Face repository at a commit, the
Qwen3 manifest, the hash-locked Qwen3 requirements) or ``None`` when no exact source is pinned yet -- the spaCy English
model, pending the owner's ruling -- and a plan carries the fingerprint of its acquisition terms, which a consent is
bound to (``shared.optional_setup_protocol.consent_covers``).

P05B Stage 2: the Kokoro, Chatterbox Turbo and spaCy sources are pinned (``tts.model_assets``), so their sizes are
exact identities (``manifest``), a present file of another size or content is ``damaged`` (repairable), and the plan
looks in the pinned commit's folder only -- a moved upstream ``main`` can never change what it reports. Chatterbox's
``s3gen.safetensors``, which Turbo never loads, is no longer counted or acquired.

v0.8.0 Phase 3: the fifth component, OmniVoice, is two units -- ``omnivoice-engine`` (the engine's own environment
``.venv/engines/omnivoice``, built offline from the 88 wheels pinned in ``tts/omnivoice_manifest.json``) and
``omnivoice-model`` (the pinned snapshot, its audio tokenizer included). The engine's readiness is the installer's own
receipt (``tts.omnivoice_runtime.assess_engine``), judged the way Qwen3's is, never probed by a plan. An environment
there that already holds exactly the pinned set but that no receipt vouches for is planned as an install that
downloads nothing: the installer proves it and adopts it. The GPU an OmniVoice install needs is a caller fact
(``Facts.gpu``), and the licence and hardware terms travel with the plan (``disclosures``) so they are shown before
anyone agrees.

Unified ``.venv`` layout (owner decision 2026-11-13): only the nested path is ever planned. An earlier sibling
``.venv-omnivoice`` is never adopted and never counted as installed; the engine unit says it is built again at the
nested path and that the sibling is moved aside (kept) only after the new engine is proved
(``omnivoice_runtime.LEGACY_MOVE_MESSAGE``). A copy of the app too deep for Windows to load the nested engine is
unsupported for this component alone (``omnivoice_runtime.install_depth_problem``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from shared import optional_setup_protocol as proto
from shared import venv_layout
from shared.optional_setup_protocol import (APPROXIMATE, BAD_BUNDLE, CHATTERBOX, DAMAGED, EXACT, KOKORO, MANIFEST,
                                            MISSING, NOT_KNOWN, OMNIVOICE, QWEN3_BASE, QWEN3_CUSTOMVOICE, READY,
                                            UNSUPPORTED, UNVERIFIED, ZERO, Figure)
from tts import model_assets as assets
from tts import omnivoice_runtime as ov
from tts import qwen3_runtime as rt
from tts import voice_registry

CONTEXT_PRE_VENV = proto.CONTEXT_PRE_VENV
CONTEXT_MAIN = proto.CONTEXT_MAIN
#: 1 = P05A; 2 = P05B Stage 1 (units name their source; the plan carries its acquisition fingerprint); 3 = P05B
#: Stage 2 (each local engine's component says whether its packages were proved to load: ``engine``).
PLAN_SCHEMA = 3

# --------------------------------------------------------------------------- #
# What the libraries would fetch on first use -- now pinned (``tts.model_assets``)
# --------------------------------------------------------------------------- #
#: kokoro 0.9.4 would download ``config.json``, the weights and one ``voices/<id>.pt`` per voice from
#: ``hexgrad/Kokoro-82M`` at whatever ``main`` names; chatterbox-tts 0.1.7 ``from_pretrained`` would snapshot
#: ``ResembleAI/chatterbox-turbo`` at ``main``; misaki would pip-install ``en_core_web_sm`` from outside any pinned set.
#: Since P05B Stage 2 every one of those is a pinned identity in ``tts.model_assets`` (repository, commit, size, SHA-256;
#: the spaCy wheel by URL, size and SHA-256), acquired only under consent, and the only thing inference loads.
KOKORO_REPO = assets.KOKORO_REPO
CHATTERBOX_REPO = assets.CHATTERBOX_REPO
SPACY_ENGLISH = assets.SPACY_ENGLISH
#: The English model's installed size, measured on HOME-PC (3.8.0): the disk figure (pip unpacks the wheel).
SPACY_ENGLISH_INSTALLED_BYTES = 15_248_495

#: The app's own ``.venv`` (main requirements, Kokoro and Chatterbox packages included; the Qwen3 engine under
#: ``engines/`` excluded), measured on HOME-PC 2026-10-25: 53,417 files. What pip downloads to build it is not recorded
#: anywhere local, so that figure is unknown rather than guessed.
BASE_PACKAGES_INSTALLED_BYTES = 2_494_787_313

#: ``qwen3_setup.DISK_MARGIN_BYTES``: the free space the Qwen3 installer insists on beyond what it writes (a test pins
#: that they agree; repeated so the pre-venv estimate need not import the installer).
QWEN3_DISK_MARGIN_BYTES = 2 * 10**9

#: Kokoro and Chatterbox run in the app's own environment; their pinned wheels need CPython 3.11 or 3.12 (64-bit).
LOCAL_ENGINE_PYTHON = ((3, 11), (3, 12))

#: v0.8.0 Phase 3: the two OmniVoice units, and the free space kept in reserve beyond what installing them writes (the
#: same margin the Qwen3 installer keeps; counted once, and only when something is written).
OMNIVOICE_ENGINE_UNIT = "omnivoice-engine"
OMNIVOICE_MODEL_UNIT = "omnivoice-model"
OMNIVOICE_DISK_MARGIN_BYTES = 2 * 10**9


def hf_hub_root() -> Path:
    """The in-tree Hugging Face cache the app always points Kokoro and Chatterbox at (``bootstrap._configure_hf_cache``)."""
    return assets.hf_hub_root()


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
    source: Optional[str] = None  # the exact thing it would be acquired from; None = not pinned (cannot be acquired)

    def to_json(self) -> dict:
        return {"id": self.id, "label": self.label, "components": list(self.components), "state": self.state,
                "source": self.source, "download": self.download.to_json(), "reused": self.reused.to_json(),
                "local_copy": self.local_copy.to_json(), "disk": self.disk.to_json(), "temp": self.temp.to_json(),
                "note": self.note}


def hf_source(repo_id: str, revision: str) -> str:
    """A Hugging Face repository at one commit: the only form of upstream model source a consent can be bound to."""
    return f"hf:{repo_id}@{revision}"


def kokoro_source() -> str:
    return hf_source(assets.KOKORO_REPO, assets.KOKORO_REVISION)


def chatterbox_source() -> str:
    return hf_source(assets.CHATTERBOX_REPO, assets.CHATTERBOX_REVISION)


def qwen_engine_source() -> Optional[str]:
    """The hash-locked Qwen3 requirements (pip ``--require-hashes``), by the hash of the lock itself."""
    digest = rt.requirements_sha256()
    return f"pip-lock:qwen3-requirements.txt@sha256:{digest}" if digest else None


def qwen_model_source(spec: "rt.ModelSpec") -> str:
    """A Qwen3 model: its repository at the manifest's commit, and the manifest entry that lists every file's hash."""
    return f"{hf_source(spec.repo, spec.revision)}#manifest-sha256:{spec.manifest_sha256()}"


def omnivoice_engine_source() -> str:
    """The OmniVoice environment: the 88 wheels of ``omnivoice_manifest.json``, by the hash of their pins (URL-free:
    each wheel's URL, size and SHA-256 are in the shipped manifest that hash names)."""
    return f"wheels:omnivoice_manifest.json@sha256:{ov.packages_sha256()}"


def omnivoice_model_source() -> str:
    """The OmniVoice model: its repository at the pinned commit, and the manifest entry that lists every file's hash
    (the model card and the tokenizer's licence among them, so a changed licence file is a different source)."""
    spec = ov.model_spec()
    return f"{hf_source(spec['repo'], spec['revision'])}#manifest-sha256:{ov.model_manifest_sha256()}"


@dataclass
class ComponentPlan:
    id: str
    selected: bool
    readiness: str
    reason: str
    units: list[str] = field(default_factory=list)
    #: Kokoro/Chatterbox only: "proved" (its packages load), "broken" (proved not to), "unproved"; None otherwise.
    engine: Optional[str] = None

    @property
    def consent_scope(self) -> Optional[str]:
        return proto.acquisition_scope(self.readiness)


_UNIT_STATES = (READY, MISSING, DAMAGED, UNVERIFIED)


def _asset_unit(unit_id: str, label: str, component: str, files: assets.AssetSet, names: Iterable[str]) -> Unit:
    """A unit of pinned upstream files (``tts.model_assets``): ready (every file is exactly the approved bytes), missing,
    damaged (a file of another size or content -- the identity is pinned, so that is not "maybe newer"), or unverified
    (reached through a link, or unreadable: nothing here can vouch for it, so nothing is acquired over it)."""
    names = tuple(names)
    source = hf_source(files.repo, files.revision)
    states = assets.assess(files, names)
    unverified = [detail for state, detail in states.values() if state == UNVERIFIED]
    if unverified:
        return Unit(unit_id, label, [component], UNVERIFIED, note=unverified[0], source=source)
    damaged = [name for name in names if states[name][0] == DAMAGED]
    missing = [name for name in names if states[name][0] == MISSING]
    present = files.size(name for name in names if states[name][0] == READY)
    if not damaged and not missing:
        return Unit(unit_id, label, [component], READY, reused=Figure(present, EXACT), source=source)
    # A damaged file is replaced in place once its download is verified: its old copy stays until then (temporary
    # space), while a missing file's partial download simply becomes the file (new disk space).
    note = f"{len(damaged) + len(missing)} of {len(names)} files to download (approved sizes)"
    if damaged:
        note = f"{states[damaged[0]][1]}; " + note
    return Unit(unit_id, label, [component], DAMAGED if damaged else MISSING,
                download=Figure(files.size(damaged + missing), MANIFEST), reused=Figure(present, EXACT),
                disk=Figure(files.size(missing), MANIFEST), temp=Figure(files.size(damaged), MANIFEST),
                source=source, note=note)


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
    #: The installed version of a distribution in the app's environment, or ``None`` (metadata only, never imported).
    package_version: Callable[[str], Optional[str]] = assets.installed_version
    #: v0.8.0: whether an NVIDIA GPU was found (``True``), proved absent (``False``) or not asked (``None``). OmniVoice
    #: needs one; without the answer it is unverified, never installable.
    gpu: Optional[bool] = None


def _health_state(facts: Facts, component: str) -> tuple[str, str]:
    proved = facts.health.get(component)
    if proved is True:
        return READY, ""
    if proved is False:
        return DAMAGED, (f"the {proto.LABELS[component]} engine's packages were proved not to load in the app's "
                         "environment; the app's own repair (restart it through Setup_and_Run) fixes them -- "
                         "downloading models cannot")
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
    files = assets.kokoro_set()
    units = [_asset_unit("kokoro-model", "Kokoro model", KOKORO, files, assets.KOKORO_MODEL_NAMES)]
    for voice in kokoro_roster():
        unit_id, name = f"kokoro-voice:{voice}", assets.kokoro_voice_name(voice)
        if name not in files.files:  # a roster voice with no approved identity: never acquired, never vouched for
            present = (assets.snapshot_dir(files) / name).is_file()
            units.append(Unit(unit_id, f"Kokoro voice {voice}", [KOKORO], UNVERIFIED if present else MISSING,
                              download=ZERO if present else NOT_KNOWN, disk=ZERO if present else NOT_KNOWN,
                              note="no approved identity for this voice", source=None))
            continue
        units.append(_asset_unit(unit_id, f"Kokoro voice {voice}", KOKORO, files, (name,)))
    state, detail = assets.spacy_english_state(facts.package_version)
    if state == MISSING:
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], MISSING,
                          download=Figure(assets.SPACY_WHEEL_SIZE, MANIFEST),
                          disk=Figure(SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE),
                          temp=Figure(assets.SPACY_WHEEL_SIZE + SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE),
                          source=assets.spacy_source(),
                          note="the approved wheel, installed with pip (no dependencies, hash checked)"))
    else:
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], state, note=detail,
                          source=assets.spacy_source()))
    return units


def _chatterbox_units() -> list[Unit]:
    return [_asset_unit("chatterbox-model", "Chatterbox Turbo model", CHATTERBOX, assets.chatterbox_set(),
                        assets.CHATTERBOX_FILES)]


def _qwen_engine_unit() -> tuple[Unit, str]:
    """The shared engine as a unit, with the reason when it is not ready. Judged by ``qwen3_runtime`` alone."""
    unit_id, label = "qwen3-engine", "Qwen3 voice engine (shared)"
    folder = rt.venv_dir()
    source = qwen_engine_source()
    ok, reason = rt.environment_status()
    if ok:
        return Unit(unit_id, label, [], READY, source=source), ""
    # v0.7.0: the engine's packages are the reviewed manifest's exact wheels (``tts.qwen3_wheels``), so the download
    # is known exactly: the wheels not already verified in the app's wheel cache.
    from tts import qwen3_wheels
    try:
        fetch = qwen3_wheels.missing_bytes()
    except Exception as exc:  # noqa: BLE001 - a manifest this build cannot vouch for: nothing can be installed from it
        return Unit(unit_id, label, [], UNVERIFIED, note=f"the Qwen3 package manifest could not be verified ({exc})",
                    source=source), reason
    install = dict(download=Figure(fetch, MANIFEST),
                   disk=Figure(rt.environment_installed_bytes(), APPROXIMATE),
                   temp=Figure(fetch, MANIFEST),
                   note="the reviewed package wheels, each checked by size and SHA-256, then installed offline; "
                        "they are kept until the install succeeds", source=source)
    problem = rt.environment_location_problem(folder)
    if problem:  # a link or an outside location: no install can fix that, and nothing here can vouch for it
        return Unit(unit_id, label, [], UNVERIFIED, note=problem, source=source), reason
    if not os.path.lexists(folder):
        return Unit(unit_id, label, [], MISSING, **install), reason
    if rt.is_nested(folder) and rt.environment_record(folder).get("stage") not in (rt.STAGE_CREATING,
                                                                                    rt.STAGE_REMOVING):
        assessment = rt.nested_assessment(folder)
        if assessment.state == venv_layout.UNVERIFIED:
            return Unit(unit_id, label, [], UNVERIFIED, note=assessment.reason, source=source), reason
    return Unit(unit_id, label, [], DAMAGED, **install), reason


def _qwen_model_units(selected: tuple[str, ...]) -> list[Unit]:
    """One unit per selected Qwen3 model, from the installer's own plan (``qwen3_setup.plan_install``)."""
    from tts import qwen3_setup

    keys = tuple(proto.QWEN3_MODEL_KEYS[c] for c in selected)
    install_plan = qwen3_setup.plan_install(keys)
    units = []
    for component, model in zip(selected, install_plan.models):
        unit_id, label = f"qwen3-model:{model.key}", f"Qwen3 {model.label} model"
        source = qwen_model_source(rt.model_spec(model.key))
        ok, reason = rt.model_status(model.key)
        if ok:
            units.append(Unit(unit_id, label, [component], READY, reused=Figure(model.total_bytes, MANIFEST),
                              source=source))
            continue
        if rt.marker_path(model.key).is_file():
            units.append(Unit(unit_id, label, [component], DAMAGED, download=NOT_KNOWN, disk=NOT_KNOWN, source=source,
                              note=reason + " A full check decides what is fetched again (at most the whole model)."))
            continue
        have = sum(f.size for f in model.files if f.action == "have")
        units.append(Unit(unit_id, label, [component], MISSING, download=Figure(model.download_bytes, MANIFEST),
                          reused=Figure(have, MANIFEST), local_copy=Figure(model.shared_bytes, MANIFEST),
                          disk=Figure(model.download_bytes + model.shared_bytes, MANIFEST), source=source,
                          note="shared files are linked from the other model where possible, otherwise copied"))
    return units


# --------------------------------------------------------------------------- #
# OmniVoice (v0.8.0 Phase 3): the engine by its receipt, the model by its record or its hashes
# --------------------------------------------------------------------------- #
OMNIVOICE_ENGINE_LABEL = "OmniVoice voice engine (its own Python packages)"
OMNIVOICE_MODEL_LABEL = "OmniVoice model and audio tokenizer"
ADOPT_NOTE = ("An OmniVoice environment holding exactly the pinned packages is already on this computer, but this "
              "version of the app has not checked it. Installing checks it -- its packages, its isolation, the GPU and "
              "a model load -- and adopts it: nothing is downloaded, replaced or removed.")
REBUILD_NOTE = ("Repairing builds a fresh environment from the verified packages. The current folder is not deleted: "
                "it is moved to files\\runtime-data\\omnivoice\\set-aside for you to remove once the new one works.")
UNFINISHED_NOTE = ("This app's own earlier install of it did not finish; repairing removes that unfinished environment "
                   "and builds it again from the verified packages.")
#: Nothing at the nested path, an earlier environment beside the app's (``.venv-omnivoice``): built again where it now
#: belongs, the old folder moved aside -- kept -- only once the new engine is proved.
MOVE_NOTE = ("OmniVoice was installed in a folder this version no longer uses (.venv-omnivoice). Installing builds its "
             "environment again inside the app's own (.venv\\engines\\omnivoice) from the pinned packages, each checked "
             "by size and SHA-256 and installed offline, and proves it there. Only then is the old folder moved to "
             "files\\runtime-data\\omnivoice\\set-aside -- kept, never deleted; if anything fails, it stays exactly "
             "where it is.")
LEGACY_KEPT_NOTE = (" The earlier environment in .venv-omnivoice is not used; it is moved to files\\runtime-data\\"
                    "omnivoice\\set-aside (kept, never deleted) only once the new one is proved.")


def _omnivoice_engine_unit() -> Unit:
    """The environment as a unit, judged by ``omnivoice_runtime.assess_engine`` (the receipt), never by a probe.

    Only the nested path is planned. An earlier sibling is never adopted: it changes the note, never the state."""
    source = omnivoice_engine_source()
    assessment = ov.assess_engine()
    environment = Figure(ov.engine_installed_bytes(), APPROXIMATE)
    if assessment.state == ov.ENGINE_READY:
        return Unit(OMNIVOICE_ENGINE_UNIT, OMNIVOICE_ENGINE_LABEL, [OMNIVOICE], READY, reused=environment,
                    note=ov.legacy_leftover_note(), source=source)
    if assessment.state == ov.ENGINE_UNVERIFIED:
        return Unit(OMNIVOICE_ENGINE_UNIT, OMNIVOICE_ENGINE_LABEL, [OMNIVOICE], UNVERIFIED, note=assessment.reason,
                    source=source)
    legacy = ov.assess_legacy().retirable
    if assessment.state == ov.ENGINE_UNCHECKED:  # adopted after a proof: an install that downloads nothing
        return Unit(OMNIVOICE_ENGINE_UNIT, OMNIVOICE_ENGINE_LABEL, [OMNIVOICE], MISSING, reused=environment,
                    note=ADOPT_NOTE + (LEGACY_KEPT_NOTE if legacy else ""), source=source)
    fetch, have = ov.wheel_bytes()  # the wheel cache, read (and hashed where unrecorded); never the installer
    fresh = (f"{len(ov.wheels())} pinned packages, each checked by size and SHA-256, then installed offline; the "
             "downloads are removed once the engine is proved to work")
    if assessment.state == ov.ENGINE_ABSENT:
        note = MOVE_NOTE if legacy else fresh
    elif assessment.state == ov.ENGINE_INCOMPLETE:
        note = UNFINISHED_NOTE + (LEGACY_KEPT_NOTE if legacy else "")
    else:  # the reason already names an earlier sibling that is not used (omnivoice_runtime.LEGACY_NOT_USED_NOTE)
        note = f"{assessment.reason} {REBUILD_NOTE}"
    return Unit(OMNIVOICE_ENGINE_UNIT, OMNIVOICE_ENGINE_LABEL, [OMNIVOICE],
                MISSING if assessment.state == ov.ENGINE_ABSENT else DAMAGED,
                download=Figure(fetch, MANIFEST), reused=Figure(have, EXACT), disk=environment,
                temp=Figure(fetch, MANIFEST), note=note, source=source)


def _omnivoice_model_unit() -> Unit:
    """The pinned snapshot as a unit: ready only when the verification record vouches for every file; otherwise the
    present files are hashed, so a complete but unrecorded snapshot downloads nothing and is only recorded."""
    source = omnivoice_model_source()
    files = ov.model_spec()["files"]
    states = ov.model_file_states()
    unverified = [detail for state, detail in states.values() if state == ov.FILE_UNVERIFIED]
    if unverified:
        return Unit(OMNIVOICE_MODEL_UNIT, OMNIVOICE_MODEL_LABEL, [OMNIVOICE], UNVERIFIED, note=unverified[0],
                    source=source)

    def size(names) -> int:
        return sum(files[name]["size"] for name in names)

    ready = [name for name, (state, _) in states.items() if state == ov.FILE_READY]
    damaged = [name for name, (state, _) in states.items() if state == ov.FILE_DAMAGED]
    missing = [name for name, (state, _) in states.items() if state == ov.FILE_MISSING]
    if not damaged and not missing:
        if ov.model_recorded():
            return Unit(OMNIVOICE_MODEL_UNIT, OMNIVOICE_MODEL_LABEL, [OMNIVOICE], READY,
                        reused=Figure(size(ready), EXACT), source=source)
        return Unit(OMNIVOICE_MODEL_UNIT, OMNIVOICE_MODEL_LABEL, [OMNIVOICE], MISSING, download=Figure(0, EXACT),
                    reused=Figure(size(ready), EXACT), source=source,
                    note="every file is already here and matches its SHA-256; installing records that check "
                         "(nothing is downloaded)")
    note = f"{len(damaged) + len(missing)} of {len(files)} files to download (approved sizes)"
    if damaged:
        note = f"{states[damaged[0]][1]}; " + note
    return Unit(OMNIVOICE_MODEL_UNIT, OMNIVOICE_MODEL_LABEL, [OMNIVOICE], DAMAGED if damaged else MISSING,
                download=Figure(size(damaged + missing), MANIFEST), reused=Figure(size(ready), EXACT),
                disk=Figure(size(missing), MANIFEST), temp=Figure(size(damaged), MANIFEST), source=source, note=note)


def _omnivoice_reference_problem() -> str:
    """The first problem with the six OmniVoice recordings or their reference list, or ``""`` (hashes six small files).
    A problem here makes the component a bad bundle: nothing is downloaded or repaired for it, since installing cannot
    restore a recording."""
    for voice in ov.OMNIVOICE_VOICES:
        ok, reason = ov.reference_status(voice)
        if not ok:
            return reason
    return ""


def _omnivoice_plan(facts: Facts) -> tuple[tuple[str, str], list[Unit]]:
    """``((readiness, reason), units)`` for the OmniVoice component, from the real state and the caller's facts."""
    if not ov.platform_supported():
        return (UNSUPPORTED, ov.platform_reason()), []
    if not facts.is_64bit:
        return (UNSUPPORTED, "OmniVoice needs 64-bit Windows and Python"), []
    if facts.gpu is False:
        return (UNSUPPORTED, ov.NO_GPU_MESSAGE), []
    if ov.assess_engine().state != ov.ENGINE_READY:
        too_deep = ov.install_depth_problem()  # only an engine not yet proved here: one that works is never refused
        if too_deep:
            return (UNSUPPORTED, too_deep), []
    units = [_omnivoice_engine_unit(), _omnivoice_model_unit()]
    parts = [u.state for u in units]
    gpu_reason = ""
    if facts.gpu is None:
        parts.append(UNVERIFIED)
        gpu_reason = ("this computer's graphics card has not been checked yet (OmniVoice needs an NVIDIA GPU); it is "
                      "checked before anything is downloaded")
    references = _omnivoice_reference_problem()
    if references:
        parts.append(BAD_BUNDLE)
    if OMNIVOICE in facts.busy:
        parts.append(proto.BUSY)
    readiness = proto.combine_readiness(parts)
    if readiness == BAD_BUNDLE:
        reason = references
    elif readiness == proto.BUSY:
        reason = ("another task is installing OmniVoice or using it for a conversion right now; try again when it has "
                  "finished")
    else:
        reason = next((u.note for u in units if u.state == readiness and u.note), "") or gpu_reason
    return (readiness, reason), units


# --------------------------------------------------------------------------- #
# The pre-venv units, from manifests and measurements only
# --------------------------------------------------------------------------- #
def _estimated_units(selected: tuple[str, ...]) -> list[Unit]:
    units: list[Unit] = []
    if KOKORO in selected:
        kokoro = assets.kokoro_set()
        model = kokoro.size(assets.KOKORO_MODEL_NAMES)
        units.append(Unit("kokoro-model", "Kokoro model", [KOKORO], MISSING, download=Figure(model, MANIFEST),
                          disk=Figure(model, MANIFEST), source=kokoro_source()))
        for voice in kokoro_roster():
            name = assets.kokoro_voice_name(voice)
            pinned = name in kokoro.files
            figure = Figure(kokoro.files[name][0], MANIFEST) if pinned else NOT_KNOWN
            units.append(Unit(f"kokoro-voice:{voice}", f"Kokoro voice {voice}", [KOKORO], MISSING, download=figure,
                              disk=figure, source=kokoro_source() if pinned else None))
        units.append(Unit("spacy-english", "spaCy English model", [KOKORO], MISSING,
                          download=Figure(assets.SPACY_WHEEL_SIZE, MANIFEST),
                          disk=Figure(SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE),
                          temp=Figure(assets.SPACY_WHEEL_SIZE + SPACY_ENGLISH_INSTALLED_BYTES, APPROXIMATE),
                          source=assets.spacy_source()))
    if CHATTERBOX in selected:
        total = assets.chatterbox_set().size(assets.CHATTERBOX_FILES)
        units.append(Unit("chatterbox-model", "Chatterbox Turbo model", [CHATTERBOX], MISSING,
                          download=Figure(total, MANIFEST), disk=Figure(total, MANIFEST), source=chatterbox_source()))
    qwen = [c for c in (QWEN3_CUSTOMVOICE, QWEN3_BASE) if c in selected]
    if qwen and rt.platform_supported():
        download = rt.environment_download_bytes()
        units.append(Unit("qwen3-engine", "Qwen3 voice engine (shared)", qwen, MISSING,
                          download=Figure(download, APPROXIMATE), disk=Figure(rt.environment_installed_bytes(),
                                                                                 APPROXIMATE),
                          temp=Figure(download, APPROXIMATE), source=qwen_engine_source()))
        shared = rt.shared_file_bytes()
        for index, component in enumerate(qwen):
            spec = rt.model_spec(proto.QWEN3_MODEL_KEYS[component])
            copy = shared if index else 0  # the second model takes the shared files from the first, locally
            units.append(Unit(f"qwen3-model:{spec.key}", f"Qwen3 {spec.label} model", [component], MISSING,
                              download=Figure(spec.total_bytes - copy, MANIFEST), local_copy=Figure(copy, MANIFEST),
                              disk=Figure(spec.total_bytes, MANIFEST), source=qwen_model_source(spec)))
    if OMNIVOICE in selected and ov.platform_supported():
        wheels, model = ov.wheels_total_bytes(), ov.model_total_bytes()
        units.append(Unit(OMNIVOICE_ENGINE_UNIT, OMNIVOICE_ENGINE_LABEL, [OMNIVOICE], MISSING,
                          download=Figure(wheels, MANIFEST), disk=Figure(ov.engine_installed_bytes(), APPROXIMATE),
                          temp=Figure(wheels, MANIFEST), source=omnivoice_engine_source()))
        units.append(Unit(OMNIVOICE_MODEL_UNIT, OMNIVOICE_MODEL_LABEL, [OMNIVOICE], MISSING,
                          download=Figure(model, MANIFEST), disk=Figure(model, MANIFEST),
                          source=omnivoice_model_source()))
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
        if name == "temp" and any(u.id.startswith("omnivoice-") and _writes(u) for u in self.units if u.id in wanted):
            figures.append(Figure(OMNIVOICE_DISK_MARGIN_BYTES, EXACT))  # once, and only when something is written
        return proto.add_figures(figures)


def _writes(unit: Unit) -> bool:
    """Whether acquiring *unit* writes anything large (an adoption or a record-only model writes a small file)."""
    return any(figure.bytes is None or figure.bytes > 0 for figure in (unit.download, unit.disk, unit.temp))


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
            "No speed is promised: Kokoro, Chatterbox and Qwen3 also run on the CPU, more slowly.",
            "OmniVoice is Windows-only and needs an NVIDIA GPU; it does not run on the CPU alone.",
        ],
        "omnivoice": _omnivoice_hardware(facts, context),
    }


def _omnivoice_hardware(facts: Facts, context: str) -> str:
    if not ov.platform_supported():
        return ov.platform_reason()
    found = {True: "An NVIDIA GPU was found on this computer.",
             False: "No NVIDIA GPU was found on this computer, so OmniVoice cannot be installed here."}
    checked = found.get(facts.gpu) if context == CONTEXT_MAIN else None
    return ov.HARDWARE_DISCLOSURE + " " + (checked or "This computer's GPU is checked before anything is downloaded.")


_ENGINE = {True: "proved", False: "broken", None: "unproved"}


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
        engine = _ENGINE[facts.health.get(name)] if context == CONTEXT_MAIN and name in (KOKORO, CHATTERBOX) \
            and name in selected else None
        components.append(ComponentPlan(name, name in selected, readiness, reason,
                                        [u.id for u in merged.values() if name in u.components], engine))
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
        elif name == OMNIVOICE and not ov.platform_supported():
            states[name] = (UNSUPPORTED, ov.platform_reason())
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

    if OMNIVOICE in selected:
        states[OMNIVOICE], own = _omnivoice_plan(facts)
        units.extend(own)
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
                        "consent_scope": c.consent_scope, "units": list(c.units), "engine": c.engine,
                        "download": plan_.total("download", c.units).to_json()} for c in plan_.components],
        "units": [u.to_json() for u in plan_.units],
        "acquire_units": acquire,
        "pending_units": pending,
        "totals": {name: plan_.total(name, acquire).to_json() for name in _TOTALS},
        "pending": {"download": plan_.total("download", pending).to_json()},
        "base_packages": _base_packages(),
        "hardware": plan_.hardware,
        "notes": list(plan_.notes),
        # v0.8.0 Phase 3: the terms a person reads before agreeing (wording, not acquisition terms: the licence files
        # themselves are pinned by hash in the model's source, so a changed licence is a different source).
        "disclosures": {OMNIVOICE: ov.disclosure()} if OMNIVOICE in plan_.selected else {},
    }
    data["acquisition_fingerprint"] = proto.acquisition_fingerprint(data)
    data["fingerprint"] = fingerprint(data)
    return data


def fingerprint(data: dict) -> str:
    """SHA-256 of a plan's canonical JSON, without its own fingerprint: what a consent is bound to."""
    body = {k: v for k, v in data.items() if k != "fingerprint"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def consent_for(data: dict) -> proto.Consent:
    """The consent a person gives by confirming *data* (a :func:`plan_to_json` plan), with a fresh id.

    Its terms are derived from the plan by the same function that later checks them (``proto.consent_fields``): each
    chosen component's scope, every unit, the units whose size is unknown (listed, never counted as zero), the known
    download, and the acquisition fingerprint. A plan with a chosen component that cannot be acquired (unverified,
    busy, unsupported, bad bundle) has no consent: ``ProtocolError`` (``not-acquirable``).
    """
    fields = proto.consent_fields(data)
    return proto.Consent(proto.new_token(), fields["plan_context"], tuple(fields["components"]), fields["scopes"],
                         tuple(fields["units"]), tuple(fields["unknown_units"]), fields["download_bytes"],
                         fields["acquisition_fingerprint"])


def format_bytes(figure: Figure) -> str:
    """A figure for people: ``"about 4.5 GB"``, ``"at least 12 MB"``, ``"unknown"`` -- never more precise than known."""
    if figure.bytes is None:
        return "unknown"
    text = rt.format_bytes(figure.bytes)
    return {APPROXIMATE: f"about {text}", proto.AT_LEAST: f"at least {text}"}.get(figure.basis, text)
