"""registry.py — the voice engines ACT knows, in one small explicit list (v0.8.2 Phase 5A).

Each :class:`EngineDefinition` says what an engine *is*: its identity and names, the platforms that offer it, where
its Python environment lives, its dependency project, its model manifest, its worker and its installer, and the
optional-setup choices that install it. The app's scattered engine tables are **derived** from this list by
:func:`tables`, never kept as parallel copies:

* ``shared.engine_policy`` -- ``ENGINES``, ``MACOS_ENGINES``, ``ENGINE_NAMES``, ``COMPONENT_ENGINES``;
* ``tts.voice_registry.BACKENDS``;
* ``shared.optional_setup_protocol`` -- ``COMPONENTS``, ``LABELS``, ``WIZARD_DEFAULTS``, ``QWEN3_MODEL_KEYS``;
* ``shared.bootstrap.WINDOWS_OPTIONAL_CHOICES`` (the first-run wizard's choices, Windows wording);
* ``tts.local_engine_host.ENGINE_NAMES`` (the engines served by the local worker);
* ``shared.venv_layout``'s engine locations and ``shared.release``'s excluded environment folders and required
  engine projects.

Adding an engine is one :class:`EngineDefinition` here plus its own modules (installer, worker, synthesis); removing
one is deleting its definition (``files/tests/test_engine_registry.py`` proves both on a disposable list). The steps
are in ``scripts/tts/README.md``.

What this is not: no plugin discovery, no imports of engine modules, no service container, no worker server and no
synthesis. The engine-specific modules keep their own behaviour; this list only names them.

Standard library only and free of every app import: the first-run setup reaches it (through
``shared.engine_policy`` and ``shared.venv_layout``) in the base interpreter before the app's environment exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

#: Where an engine's Python packages live.
PLACEMENT_BASE = "base"  # in the app's own environment ``.venv`` (Edge; Kokoro until 5C; Chatterbox until 5D)
PLACEMENT_NESTED = "nested"  # an independent environment held at ``.venv/engines/<key>`` (OmniVoice until 5B)
PLACEMENT_ENGINE = "engine"  # its own uv project and environment at ``.venv-engines/<key>`` (Qwen3 since 5A)
PLACEMENTS = (PLACEMENT_BASE, PLACEMENT_NESTED, PLACEMENT_ENGINE)

#: The folder every independent engine environment is a child of (approved A1, owner 2026-11-27).
ENGINE_ENVS_DIR = ".venv-engines"
#: The app's own environment (fixed requirement: always directly inside the application root).
BASE_ENV_DIR = ".venv"

WINDOWS = "win32"
MACOS = "darwin"


@dataclass(frozen=True)
class Component:
    """One optional-setup choice: what the first-run window and Install & Continue offer."""

    id: str
    label: str  # the protocol's name for it
    choice_label: str  # the first-run window's line
    choice_note: str  # the first-run window's note (Windows wording)
    default: bool = False  # owner-approved first-run default (Q15)
    model: str = ""  # the engine model it installs, when the engine has several


@dataclass(frozen=True)
class EngineDefinition:
    key: str
    name: str  # what a person reads
    platforms: tuple[str, ...]  # ``sys.platform`` values that offer it (any other platform: see :func:`offered`)
    placement: str
    components: tuple[Component, ...] = ()
    short_name: str = ""  # the local worker's shorter name, where it differs
    project: str = ""  # repo-relative folder of its uv project (``pyproject.toml`` + ``uv.lock``), engine placement
    nested_environment: str = ""  # repo-relative ``.venv/engines/<key>`` (current for nested, legacy for engine)
    sibling_environment: str = ""  # repo-relative ``.venv-<key>`` an earlier version used (never installed into)
    model_manifest: str = ""  # repo-relative model integrity manifest, when it has one of its own
    installer: str = ""  # the module that provisions it
    worker: str = ""  # the module its worker process runs
    local_host: bool = False  # served by ``tts.local_engine_host`` (in process on Windows, a worker on macOS)

    def __post_init__(self) -> None:
        if self.placement not in PLACEMENTS:
            raise ValueError(f"{self.key}: unknown placement {self.placement!r}")
        if (self.placement == PLACEMENT_ENGINE) != bool(self.project):
            raise ValueError(f"{self.key}: a dependency project is named exactly when the engine has its own uv "
                             "environment")
        if self.placement == PLACEMENT_NESTED and not self.nested_environment:
            raise ValueError(f"{self.key}: a nested engine names its nested environment")

    @property
    def environment(self) -> str:
        """Repo-relative folder of the environment new installs use, or ``""`` (the base environment)."""
        if self.placement == PLACEMENT_ENGINE:
            return f"{ENGINE_ENVS_DIR}/{self.key}"
        if self.placement == PLACEMENT_NESTED:
            return self.nested_environment
        return ""

    @property
    def legacy_environments(self) -> tuple[str, ...]:
        """Repo-relative folders earlier versions put this engine's environment in (never the current one)."""
        found = [self.nested_environment] if self.placement == PLACEMENT_ENGINE and self.nested_environment else []
        return tuple(found + ([self.sibling_environment] if self.sibling_environment else []))


# --------------------------------------------------------------------------------------------------------------------
#  The engines, in registry order (the order of voice_registry.BACKENDS and of the first-run choices)
# --------------------------------------------------------------------------------------------------------------------
EDGE = EngineDefinition(
    key="edge", name="Microsoft Edge TTS", platforms=(WINDOWS, MACOS), placement=PLACEMENT_BASE,
)
KOKORO = EngineDefinition(
    key="kokoro", name="Kokoro", platforms=(WINDOWS, MACOS), placement=PLACEMENT_BASE, local_host=True,
    installer="shared.bootstrap", worker="tts.local_engine_worker",
    components=(Component("kokoro", "Kokoro", "Kokoro voices",
                          "Natural English voices that run on this computer (CPU or GPU).", default=True),),
)
CHATTERBOX = EngineDefinition(
    key="chatterbox", name="Chatterbox Turbo", short_name="Chatterbox", platforms=(WINDOWS,),
    placement=PLACEMENT_BASE, local_host=True, installer="shared.bootstrap", worker="tts.local_engine_worker",
    components=(Component("chatterbox", "Chatterbox Turbo", "Chatterbox Turbo voices",
                          "Expressive local voices; a large model, best with an NVIDIA GPU."),),
)
QWEN3 = EngineDefinition(
    key="qwen3", name="Qwen3-TTS", platforms=(WINDOWS,), placement=PLACEMENT_ENGINE,
    project="scripts/tts/engines/qwen3", nested_environment=".venv/engines/qwen3",
    sibling_environment=".venv-qwen3", model_manifest="scripts/tts/qwen3_models.json",
    installer="tts.qwen3_setup", worker="tts.qwen3_worker",
    components=(
        Component("qwen3-customvoice", "Qwen3 CustomVoice", "Qwen3 CustomVoice voices (Aiden, Ryan)",
                  "High-quality preset voices. Windows only; an NVIDIA GPU is strongly recommended.",
                  model="customvoice"),
        Component("qwen3-base", "Qwen3 Cloned Voices / Base", "Qwen3 Cloned Voices (six bundled voices)",
                  "The six cloned voices that ship with the app - no recording or transcription needed. "
                  "Windows only; an NVIDIA GPU is strongly recommended.", model="base"),
    ),
)
OMNIVOICE = EngineDefinition(
    key="omnivoice", name="OmniVoice", platforms=(WINDOWS, MACOS), placement=PLACEMENT_NESTED,
    nested_environment=".venv/engines/omnivoice", sibling_environment=".venv-omnivoice",
    model_manifest="scripts/tts/omnivoice_manifest.json", installer="tts.omnivoice_setup",
    worker="tts.omnivoice_worker",
    components=(Component("omnivoice", "OmniVoice — Six Cloned Voices", "OmniVoice — Six Cloned Voices",
                          "Six more cloned voices from a separate engine. Windows with an NVIDIA GPU only. "
                          "NON-COMMERCIAL: the model weights are CC-BY-NC and its audio tokenizer has its own "
                          "licence; the full terms are shown before anything is downloaded."),),
)

DEFINITIONS: tuple[EngineDefinition, ...] = (EDGE, KOKORO, CHATTERBOX, QWEN3, OMNIVOICE)


# --------------------------------------------------------------------------------------------------------------------
#  The tables every consumer derives from the list
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Tables:
    engines: tuple[str, ...]
    names: dict
    macos_engines: tuple[str, ...]
    components: tuple[str, ...]
    component_engines: dict
    component_labels: dict
    component_models: dict
    wizard_defaults: dict
    optional_choices: tuple
    local_host_names: dict
    engine_projects: dict
    environment_folders: frozenset = field(default_factory=frozenset)


def tables(definitions: Iterable[EngineDefinition] = DEFINITIONS) -> Tables:
    """Everything the app's engine tables hold, derived from *definitions* (default: the registry). A disposable list
    gives the tables an added or removed engine would produce, without touching any consumer."""
    defs = tuple(definitions)
    keys = [d.key for d in defs]
    if len(set(keys)) != len(keys):
        raise ValueError("engine keys must be unique")
    components = [(d, c) for d in defs for c in d.components]
    ids = [c.id for _, c in components]
    if len(set(ids)) != len(ids):
        raise ValueError("component ids must be unique")
    folders = {BASE_ENV_DIR}
    for d in defs:
        for path in (d.environment, *d.legacy_environments):
            if path:
                folders.add(path.split("/", 1)[0])
    return Tables(
        engines=tuple(keys),
        names={d.key: d.name for d in defs},
        macos_engines=tuple(d.key for d in defs if MACOS in d.platforms),
        components=tuple(ids),
        component_engines={c.id: d.key for d, c in components},
        component_labels={c.id: c.label for _, c in components},
        component_models={c.id: c.model for _, c in components if c.model},
        wizard_defaults={c.id: c.default for _, c in components},
        optional_choices=tuple((c.id, c.choice_label, c.default, c.choice_note) for _, c in components),
        local_host_names={d.key: d.short_name or d.name for d in defs if d.local_host},
        engine_projects={d.key: d.project for d in defs if d.placement == PLACEMENT_ENGINE},
        environment_folders=frozenset(folders),
    )


TABLES = tables()


def definition(key: str) -> EngineDefinition:
    for item in DEFINITIONS:
        if item.key == key:
            return item
    raise KeyError(key)


def get(key: str) -> Optional[EngineDefinition]:
    try:
        return definition(key)
    except KeyError:
        return None
