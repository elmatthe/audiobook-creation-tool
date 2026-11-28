"""v0.8.2 Phase 5A (OmniVoice placement since 5B) — the engine registry (``scripts/tts/engines/registry.py``) and every table derived from it.

The app's engine tables used to be parallel literals in seven modules. They are now derived from one explicit list of
:class:`EngineDefinition` objects. These tests pin that the derived tables are exactly the released ones (so nothing a
person sees or a record holds changed), that every consumer really reads the registry rather than a copy, that the
registry stays standard-library only (the first-run setup reaches it before the app's environment exists), and -- on a
disposable list, never the real one -- what adding or removing an engine produces.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared import bootstrap, engine_policy, optional_setup_protocol as proto, release, venv_layout
from tts import local_engine_host, voice_registry
from tts.engines import registry

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

# The tables exactly as v0.8.1 released them (literals in their own modules until v0.8.2 Phase 5A).
RELEASED_ENGINES = ("edge", "kokoro", "chatterbox", "qwen3", "omnivoice")
RELEASED_MACOS_ENGINES = ("edge", "kokoro", "omnivoice")
RELEASED_NAMES = {"edge": "Microsoft Edge TTS", "kokoro": "Kokoro", "chatterbox": "Chatterbox Turbo",
                  "qwen3": "Qwen3-TTS", "omnivoice": "OmniVoice"}
RELEASED_COMPONENT_ENGINES = {"kokoro": "kokoro", "chatterbox": "chatterbox", "qwen3-customvoice": "qwen3",
                              "qwen3-base": "qwen3", "omnivoice": "omnivoice"}
RELEASED_LABELS = {"kokoro": "Kokoro", "chatterbox": "Chatterbox Turbo", "qwen3-customvoice": "Qwen3 CustomVoice",
                   "qwen3-base": "Qwen3 Cloned Voices / Base", "omnivoice": "OmniVoice — Six Cloned Voices"}
RELEASED_DEFAULTS = {"kokoro": True, "chatterbox": False, "qwen3-customvoice": False, "qwen3-base": False,
                     "omnivoice": False}
RELEASED_CHOICES = (
    ("kokoro", "Kokoro voices", True,
     "Natural English voices that run on this computer (CPU or GPU)."),
    ("chatterbox", "Chatterbox Turbo voices", False,
     "Expressive local voices; a large model, best with an NVIDIA GPU."),
    ("qwen3-customvoice", "Qwen3 CustomVoice voices (Aiden, Ryan)", False,
     "High-quality preset voices. Windows only; an NVIDIA GPU is strongly recommended."),
    ("qwen3-base", "Qwen3 Cloned Voices (six bundled voices)", False,
     "The six cloned voices that ship with the app - no recording or transcription needed. "
     "Windows only; an NVIDIA GPU is strongly recommended."),
    ("omnivoice", "OmniVoice — Six Cloned Voices", False,
     "Six more cloned voices from a separate engine. Windows with an NVIDIA GPU only. NON-COMMERCIAL: the model "
     "weights are CC-BY-NC and its audio tokenizer has its own licence; the full terms are shown before anything is "
     "downloaded."),
)


# --------------------------------------------------------------------------- #
# The derived tables are exactly the released ones, and every consumer reads them
# --------------------------------------------------------------------------- #
def test_every_derived_table_is_exactly_what_v0_8_1_released():
    t = registry.TABLES
    assert t.engines == RELEASED_ENGINES and t.macos_engines == RELEASED_MACOS_ENGINES
    assert t.names == RELEASED_NAMES and t.component_engines == RELEASED_COMPONENT_ENGINES
    assert t.components == tuple(RELEASED_LABELS) and t.component_labels == RELEASED_LABELS
    assert t.wizard_defaults == RELEASED_DEFAULTS and t.optional_choices == RELEASED_CHOICES
    assert t.component_models == {"qwen3-customvoice": "customvoice", "qwen3-base": "base"}
    assert t.local_host_names == {"kokoro": "Kokoro", "chatterbox": "Chatterbox"}
    # v0.8.2 Phase 5B: OmniVoice has its own uv project and environment too.
    assert t.engine_projects == {"qwen3": "scripts/tts/engines/qwen3", "omnivoice": "scripts/tts/engines/omnivoice"}
    assert t.environment_folders == {".venv", ".venv-engines", ".venv-qwen3", ".venv-omnivoice"}


def test_every_consumer_holds_the_registry_s_table_not_a_copy_of_its_own():
    t = registry.TABLES
    assert engine_policy.ENGINES == t.engines and engine_policy.MACOS_ENGINES == t.macos_engines
    assert engine_policy.ENGINE_NAMES == t.names and engine_policy.COMPONENT_ENGINES == t.component_engines
    assert voice_registry.BACKENDS == t.engines
    assert proto.COMPONENTS == t.components and proto.LABELS == t.component_labels
    assert proto.WIZARD_DEFAULTS == t.wizard_defaults and proto.QWEN3_MODEL_KEYS == t.component_models
    assert bootstrap.WINDOWS_OPTIONAL_CHOICES == t.optional_choices
    assert local_engine_host.ENGINE_NAMES == t.local_host_names
    assert venv_layout.ENGINE_QWEN3 == ".venv-engines/qwen3" == registry.QWEN3.environment
    assert venv_layout.NESTED_QWEN3 == ".venv/engines/qwen3" and venv_layout.LEGACY_QWEN3 == ".venv-qwen3"
    assert venv_layout.ENGINE_OMNIVOICE == ".venv-engines/omnivoice" == registry.OMNIVOICE.environment
    assert venv_layout.NESTED_OMNIVOICE == ".venv/engines/omnivoice" == registry.OMNIVOICE.nested_environment
    assert venv_layout.LEGACY_OMNIVOICE == ".venv-omnivoice"
    assert t.environment_folders <= release.EXCLUDED_DIR_NAMES
    assert release.ENGINE_PROJECT_FILES == ("scripts/tts/engines/qwen3/pyproject.toml",
                                            "scripts/tts/engines/qwen3/uv.lock",
                                            "scripts/tts/engines/omnivoice/pyproject.toml",
                                            "scripts/tts/engines/omnivoice/uv.lock")


_TABLE_NAMES = {
    "shared/engine_policy.py": {"ENGINES", "MACOS_ENGINES", "ENGINE_NAMES", "COMPONENT_ENGINES"},
    "tts/voice_registry.py": {"BACKENDS"},
    "shared/optional_setup_protocol.py": {"COMPONENTS", "LABELS", "WIZARD_DEFAULTS", "QWEN3_MODEL_KEYS"},
    "shared/bootstrap.py": {"WINDOWS_OPTIONAL_CHOICES"},
    "tts/local_engine_host.py": {"ENGINE_NAMES"},
}


@pytest.mark.parametrize("module", sorted(_TABLE_NAMES))
def test_no_consumer_writes_an_engine_table_as_a_literal_again(module):
    """A parallel literal would drift from the registry the first time an engine changes (AST, not substrings)."""
    tree = ast.parse((SCRIPTS / module).read_text(encoding="utf-8"))
    literal = (ast.Tuple, ast.List, ast.Dict, ast.Set, ast.Constant)
    found = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in _TABLE_NAMES[module]:
                found.append(target.id)
                assert not isinstance(node.value, literal), f"{module}: {target.id} is a literal again"
    assert set(found) == _TABLE_NAMES[module]


def test_the_qwen3_definition_names_files_that_exist():
    q = registry.definition("qwen3")
    for relative in (q.project + "/pyproject.toml", q.project + "/uv.lock", q.model_manifest):
        assert (REPO / relative).is_file(), relative
    for module in (q.installer, q.worker):
        assert (SCRIPTS / (module.replace(".", "/") + ".py")).is_file(), module
    assert q.legacy_environments == (".venv/engines/qwen3", ".venv-qwen3") and q.platforms == ("win32",)
    assert registry.get("nothing") is None
    with pytest.raises(KeyError):
        registry.definition("nothing")


def test_the_registry_is_standard_library_only_and_imports_no_app_module():
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    probe = (f"import json, sys; sys.path.insert(0, {str(SCRIPTS)!r}); from tts.engines import registry; "
             "print(json.dumps(sorted(sys.modules)))")
    done = subprocess.run([str(base), "-I", "-S", "-c", probe], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    modules = json.loads(done.stdout.strip().splitlines()[-1])
    app = {m for m in modules if m.split(".")[0] in ("tts", "shared")}
    assert app == {"tts", "tts.engines", "tts.engines.registry"}
    assert [m for m in modules if m.split(".")[0] not in (*sys.stdlib_module_names, "tts", "__main__")] == []


# --------------------------------------------------------------------------- #
# Adding or removing an engine, on a disposable list (the real registry is never changed)
# --------------------------------------------------------------------------- #
DEMO = registry.EngineDefinition(
    key="demo", name="Demo Engine", platforms=(registry.WINDOWS, registry.MACOS), placement=registry.PLACEMENT_ENGINE,
    project="scripts/tts/engines/demo", installer="tts.demo_setup", worker="tts.demo_worker",
    components=(registry.Component("demo-voices", "Demo voices", "Demo voices (two voices)", "A test engine.",
                                   model="small"),),
)


def test_adding_an_engine_is_one_definition_and_every_table_follows():
    t = registry.tables(registry.DEFINITIONS + (DEMO,))
    assert t.engines == RELEASED_ENGINES + ("demo",) and t.macos_engines == RELEASED_MACOS_ENGINES + ("demo",)
    assert t.names["demo"] == "Demo Engine" and t.component_engines["demo-voices"] == "demo"
    assert t.components[-1] == "demo-voices" and t.component_labels["demo-voices"] == "Demo voices"
    assert t.wizard_defaults["demo-voices"] is False and t.component_models["demo-voices"] == "small"
    assert t.optional_choices[-1] == ("demo-voices", "Demo voices (two voices)", False, "A test engine.")
    assert t.engine_projects["demo"] == "scripts/tts/engines/demo" and DEMO.environment == ".venv-engines/demo"
    assert "demo" not in t.local_host_names and t.environment_folders == registry.TABLES.environment_folders
    assert registry.TABLES.engines == RELEASED_ENGINES  # the real registry is untouched


def test_removing_an_engine_is_deleting_its_definition_and_nothing_refers_to_it_any_more():
    t = registry.tables(d for d in registry.DEFINITIONS if d.key != "chatterbox")
    assert "chatterbox" not in t.engines and "chatterbox" not in t.names and "chatterbox" not in t.local_host_names
    assert "chatterbox" not in t.components and "chatterbox" not in t.component_engines.values()
    assert [c[0] for c in t.optional_choices] == ["kokoro", "qwen3-customvoice", "qwen3-base", "omnivoice"]
    without_qwen3 = registry.tables(d for d in registry.DEFINITIONS if d.key != "qwen3")
    assert without_qwen3.engine_projects == {"omnivoice": "scripts/tts/engines/omnivoice"}
    assert ".venv-qwen3" not in without_qwen3.environment_folders and ".venv-engines" in without_qwen3.environment_folders
    neither = registry.tables(d for d in registry.DEFINITIONS if d.key not in ("qwen3", "omnivoice"))
    assert neither.engine_projects == {} and ".venv-engines" not in neither.environment_folders
    assert registry.TABLES.engines == RELEASED_ENGINES


@pytest.mark.parametrize("change, words", [
    (dict(placement="elsewhere"), "unknown placement"),
    (dict(project=""), "dependency project"),
    (dict(placement=registry.PLACEMENT_BASE), "dependency project"),
    (dict(placement=registry.PLACEMENT_NESTED, project="", nested_environment=""), "nested environment"),
])
def test_a_definition_that_contradicts_itself_is_refused(change, words):
    fields = dict(key="demo", name="Demo", platforms=(registry.WINDOWS,), placement=registry.PLACEMENT_ENGINE,
                  project="scripts/tts/engines/demo")
    fields.update(change)
    with pytest.raises(ValueError, match=words):
        registry.EngineDefinition(**fields)


def test_duplicate_engines_or_choices_are_refused():
    with pytest.raises(ValueError, match="engine keys"):
        registry.tables(registry.DEFINITIONS + (registry.QWEN3,))
    twin = registry.EngineDefinition(key="twin", name="Twin", platforms=(registry.WINDOWS,),
                                     placement=registry.PLACEMENT_BASE, components=registry.KOKORO.components)
    with pytest.raises(ValueError, match="component ids"):
        registry.tables(registry.DEFINITIONS + (twin,))
