"""The Plan 3 boundary guards — v0.6.0 Drop 3, Phase 1 onward.

Plan 3 builds a reusable importing and job-control foundation and **adopts it
nowhere**. Production tools get it in Plans 4–8; until then the strongest thing
this drop can offer is proof that nothing changed. These are structural tests: they
read source with ``ast`` rather than running behaviour, so they keep holding as the
foundation grows through Phases 2–8.

They live in their own module rather than inside ``test_repository_contract.py`` so
Plan 2's repository contract stays exactly as it was approved, and so every guard a
later Plan 3 phase has to move sits in one obvious place.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
SHARED = UNIVERSAL / "shared"
TESTS = REPO_ROOT / "files" / "tests"

#: The modules this drop owns. ``job_ui.py`` is Phase 8 and does not exist yet.
PLAN3_MODULES = ("importing.py", "job_control.py")
PLAN3_MODULE_NAMES = ("importing", "job_control", "job_ui")

#: Every production module that must remain unaware of Plan 3.
PRODUCTION_SOURCES = tuple(
    path for path in sorted(UNIVERSAL.rglob("*.py"))
    if path.name not in PLAN3_MODULES and "__pycache__" not in path.parts
)

PANELS = (
    "launcher.py",
    "tts/epub2tts_gui.py",
    "mp3_tools/m4b_converter.py",
    "mp3_tools/mp3_tool.py",
    "mp3_tools/m4b_maker.py",
    "mp3_tools/cover_resizer.py",
    "mp3_tools/m4b_metadata_editor.py",
)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_names(tree: ast.Module) -> set[str]:
    """Every module named by an ``import`` or ``from ... import`` statement."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


def called_attributes(tree: ast.Module) -> set[str]:
    return {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def called_bare_names(tree: ast.Module) -> set[str]:
    return {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def defined_names(tree: ast.Module) -> set[str]:
    return {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


@pytest.fixture(scope="module")
def plan3_trees() -> dict[str, ast.Module]:
    return {name: parse(SHARED / name) for name in PLAN3_MODULES}


# --------------------------------------------------------------------------- #
# The pure modules stay pure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_a_plan3_module_imports_no_tk(plan3_trees, name):
    """§5.1: the platform-neutral core must be testable with no display at all."""
    for module in imported_names(plan3_trees[name]):
        assert "tkinter" not in module.lower(), (name, module)
    text = (SHARED / name).read_text(encoding="utf-8")
    for forbidden in ("tkinter", "ttk.", "tk.Tk", "StringVar", "BooleanVar", ".after("):
        assert forbidden not in text, (name, forbidden)


#: Concurrency primitives a *vocabulary* module has no business constructing.
#: ``Lock`` is absent on purpose — see the test below it.
_CONCURRENCY_CONSTRUCTORS = (
    "Thread", "Timer", "Queue", "SimpleQueue", "LifoQueue", "PriorityQueue",
    "Condition", "Event", "Semaphore", "BoundedSemaphore", "Barrier",
    "ThreadPoolExecutor", "ProcessPoolExecutor", "Pool", "Process",
)


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_a_plan3_module_starts_no_worker_and_owns_no_queue(plan3_trees, name):
    """Threads, queues and polling arrive in Phases 4–8, not in the vocabulary."""
    tree = plan3_trees[name]
    for module in imported_names(tree):
        assert module.split(".")[0] not in {"queue", "asyncio", "concurrent", "multiprocessing"}, (
            name, module)
    constructed = called_attributes(tree) | called_bare_names(tree)
    for primitive in _CONCURRENCY_CONSTRUCTORS:
        assert primitive not in constructed, (name, primitive)


def test_the_only_threading_use_is_a_lock_for_identifier_allocation():
    """``IdFactory`` needs a lock. A lock is not concurrency; a thread is."""
    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    assert "threading.Lock()" in text
    assert text.count("threading.") == 1, "threading is used for exactly one lock"
    assert "threading" not in (SHARED / "job_control.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_a_plan3_module_touches_no_filesystem(plan3_trees, name):
    """Phase 1 is provably lexical. Phase 2 owns the first call that reads a disk."""
    tree = plan3_trees[name]
    attributes = called_attributes(tree)
    for forbidden in (
        "scandir", "walk", "iterdir", "glob", "rglob", "listdir",
        "stat", "lstat", "exists", "is_file", "is_dir", "is_symlink", "resolve",
        "mkdir", "makedirs", "touch", "unlink", "rmdir", "rmtree", "replace",
        "read_text", "read_bytes", "write_text", "write_bytes", "copy", "copy2",
    ):
        assert forbidden not in attributes, (name, forbidden)
    assert "open" not in called_bare_names(tree), name


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_a_plan3_module_reimplements_no_plan2_service(plan3_trees, name):
    """§5.2: extend the existing services, never grow a parallel one."""
    tree = plan3_trees[name]
    modules = imported_names(tree)
    for forbidden in (
        "tomllib", "subprocess", "logging", "shutil", "socket", "urllib", "http",
        "shared.output_paths", "shared.settings", "shared.preferences_ui",
        "shared.maintenance", "shared.cleanup_state", "shared.cleanup_worker",
        "shared.release", "shared.logging_setup", "shared.subprocess_utils",
        "shared.ui_theme", "shared.ffmpeg_utils", "shared.metadata", "shared.bootstrap",
    ):
        assert not any(entry == forbidden or entry.startswith(forbidden + ".")
                       for entry in modules), (name, forbidden)

    defined = defined_names(tree)
    for owned_elsewhere in (
        "load", "reload", "invalidate", "get_effective", "default_output_base",
        "reserve_run_directory", "ensure_output_base", "destination_hint",
        "plan_flat", "plan_mirrored", "plan_multi_root", "sanitize_component",
        "DestinationPlanner", "RunReservation", "get_logger", "run", "popen",
        "check_output", "is_link", "authorized_target", "ConversionCancelled",
        "raise_if_cancelled", "ProgressIndicator",
    ):
        assert owned_elsewhere not in defined, (name, owned_elsewhere)


def test_configuration_is_consumed_not_rebuilt():
    """A captured ``EffectiveConfig`` is carried; no second loader exists."""
    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    assert "from shared import config as _config" in text
    assert "EffectiveConfig" in text
    assert "tomllib" not in text


def test_the_dependency_between_config_and_importing_runs_one_way():
    """The same rule ``logging_setup`` follows: config must not learn about us."""
    config_modules = imported_names(parse(SHARED / "config.py"))
    for name in PLAN3_MODULE_NAMES:
        assert not any(entry.endswith(name) for entry in config_modules), name


def test_job_control_depends_on_importing_and_not_the_other_way_round():
    job = imported_names(parse(SHARED / "job_control.py"))
    imports = imported_names(parse(SHARED / "importing.py"))
    assert any(entry.startswith("shared.importing") for entry in job)
    assert not any("job_control" in entry for entry in imports)


# --------------------------------------------------------------------------- #
# Nothing in production adopts Plan 3
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path", PRODUCTION_SOURCES, ids=lambda p: str(p.relative_to(UNIVERSAL)).replace(os.sep, "/"))
def test_no_production_module_imports_the_plan3_foundation(path):
    """The whole shipped tree, not only the six panels."""
    modules = imported_names(parse(path))
    for plan3 in PLAN3_MODULE_NAMES:
        assert f"shared.{plan3}" not in modules, (path.name, plan3)
        assert not any(entry.startswith(f"shared.{plan3}.") for entry in modules), path.name
        assert f"shared.{plan3}" not in modules


@pytest.mark.parametrize("relative", PANELS)
def test_the_launcher_and_every_panel_still_names_nothing_from_plan3(relative):
    text = (UNIVERSAL / relative).read_text(encoding="utf-8")
    for plan3 in PLAN3_MODULE_NAMES:
        assert f"shared.{plan3}" not in text, (relative, plan3)
        assert f"import {plan3}" not in text, (relative, plan3)
    for vocabulary in ("RunSnapshot", "RetryRequest", "FailureLog", "JobState",
                       "ImportedFileSnapshot", "SupportedTypeCatalog", "ScanRequest"):
        assert vocabulary not in text, (relative, vocabulary)


def test_the_launcher_tool_registry_gained_no_seventh_entry():
    tree = parse(UNIVERSAL / "launcher.py")
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(target, ast.Name) and target.id == "TOOLS" for target in targets):
            assert isinstance(node.value, (ast.List, ast.Tuple))
            assert len(node.value.elts) == 6, "Plan 3 adds no tool"
            break
    else:  # pragma: no cover - the registry is expected to exist
        pytest.fail("launcher.TOOLS was not found")


# --------------------------------------------------------------------------- #
# The cancellation primitive is untouched
# --------------------------------------------------------------------------- #


def test_the_existing_cancellation_api_is_unchanged_and_unwrapped():
    from shared import cancellation

    assert issubclass(cancellation.ConversionCancelled, Exception)
    assert cancellation.raise_if_cancelled(None) is None
    assert cancellation.raise_if_cancelled(lambda: False) is None
    with pytest.raises(cancellation.ConversionCancelled):
        cancellation.raise_if_cancelled(lambda: True)
    with pytest.raises(cancellation.ConversionCancelled) as excinfo:
        cancellation.raise_if_cancelled(lambda: True, "Stopped.")
    assert "Stopped." in str(excinfo.value)

    tree = parse(SHARED / "cancellation.py")
    assert defined_names(tree) == {"ConversionCancelled", "raise_if_cancelled"}
    assert imported_names(tree) == {"__future__", "__future__.annotations",
                                    "typing", "typing.Callable", "typing.Optional"}


def test_plan3_neither_shadows_nor_re_exports_cancellation():
    for name in PLAN3_MODULES:
        text = (SHARED / name).read_text(encoding="utf-8")
        assert "ConversionCancelled" not in text, name
        assert "raise_if_cancelled" not in text, name


# --------------------------------------------------------------------------- #
# No later-phase behaviour has leaked in
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_no_phase_two_to_eight_behaviour_exists_yet(plan3_trees, name):
    defined = defined_names(plan3_trees[name])
    for later_phase in (
        # Phase 2 traversal
        "scan_roots", "natural_key", "is_hidden", "classify_root", "capture_identity",
        # Phase 3 manager
        "ImportedFileManager", "add_files", "add_folder", "move_up", "move_down",
        "remove_selected", "clear_all", "commit",
        # Phase 4 coordination
        "ImportCoordinator", "cancel_import", "start_scan",
        # Phase 5 controller
        "JobController", "request_pause", "request_cancel", "resume", "checkpoint",
        # Phase 7 ETA / projection
        "EtaEstimator", "estimate_remaining", "summary_lines", "detail_lines",
        # Phase 8 adapters
        "ImportedFileList", "JobControlBar", "build_ui",
    ):
        assert later_phase not in defined, (name, later_phase)


def test_no_eta_arithmetic_exists_anywhere_in_the_foundation():
    """Timestamps are *carried* from an injected clock; none is read or subtracted."""
    for name in PLAN3_MODULES:
        tree = plan3_trees_for(name)
        assert "time" not in {entry.split(".")[0] for entry in imported_names(tree)}, name
        called = called_attributes(tree) | called_bare_names(tree)
        for clock in ("monotonic", "perf_counter", "time", "now", "utcnow"):
            assert clock not in called, (name, clock)
        text = (SHARED / name).read_text(encoding="utf-8")
        assert "Calculating" not in text, name


def plan3_trees_for(name: str) -> ast.Module:
    return parse(SHARED / name)


def test_the_phase_eight_adapter_module_does_not_exist_yet():
    assert not (SHARED / "job_ui.py").exists()


def test_the_single_intended_ui_test_module_is_recorded_but_not_created():
    """§6.15 puts every adapter in one ``shared/job_ui.py``.

    The plan's "likely new tests" list names both ``test_import_ui.py`` and
    ``test_job_ui.py``. One adapter module needs one Tk-boundary test module, so
    **``files/tests/test_job_ui.py`` is the intended name** and ``test_import_ui.py``
    will not be created. Recorded here rather than satisfied by an empty file,
    because Phase 1 must add no Tk test at all.
    """
    assert not (TESTS / "test_import_ui.py").exists()
    assert not (TESTS / "test_job_ui.py").exists()


# --------------------------------------------------------------------------- #
# Repository invariants
# --------------------------------------------------------------------------- #


def test_the_version_is_untouched():
    from shared.version import VERSION

    assert VERSION == "0.5.1"


def test_the_root_config_template_remains_absent():
    """The v0.6.0 Drop 3 contract. ``os.listdir`` because NTFS lookups are case-blind."""
    entries = os.listdir(REPO_ROOT)
    assert "config.toml" in entries
    assert "config-template.toml" not in entries


def test_the_committed_configuration_and_requirements_are_unchanged_in_shape():
    text = (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
    for key in ("base_directory", "max_sessions", "large_result_warning_threshold"):
        assert key in text
    for line in (REPO_ROOT / "scripts" / "requirements.txt").read_text(
            encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            assert "==" in stripped.split(";", 1)[0], stripped


def test_both_root_launchers_are_still_present():
    for launcher in ("Setup_and_Run-audiobook-creation-tool.bat",
                     "Setup_and_Run-audiobook-creation-tool.command"):
        assert (REPO_ROOT / launcher).is_file()


def test_all_twenty_two_approved_screenshots_are_still_there():
    shots = REPO_ROOT / "files" / "UI-Prototype-Screenshots"
    drop1 = {
        "windows-100-launcher-overview.png",
        "windows-100-m4b-metadata-active-run.png",
        "windows-100-m4b-metadata-empty.png",
        "windows-100-m4b-metadata-populated.png",
        "windows-100-summary-details-specimen.png",
        "windows-125-launcher-overview.png",
        "windows-125-m4b-metadata-active-run.png",
        "windows-125-m4b-metadata-empty.png",
        "windows-125-m4b-metadata-populated.png",
        "windows-125-summary-details-specimen.png",
    }
    drop2 = {
        "windows-100-cleanup-confirmation.png",
        "windows-100-cleanup-inventory.png",
        "windows-100-cleanup-result.png",
        "windows-100-cleanup-selected.png",
        "windows-100-config-warning.png",
        "windows-100-cover-replace-confirmation.png",
        "windows-100-launcher-maximized.png",
        "windows-100-launcher-minimum-size.png",
        "windows-100-preferences-after-reset.png",
        "windows-100-preferences-custom-saved.png",
        "windows-100-preferences-default.png",
        "windows-100-preferences-invalid-path.png",
    }
    assert set(os.listdir(shots / "v0.6.0-drop1")) == drop1
    assert set(os.listdir(shots / "v0.6.0-drop2")) == drop2
    assert len(drop1) + len(drop2) == 22


def test_the_canonical_documents_and_protected_references_keep_their_exact_names():
    md = REPO_ROOT / "md-instructions"
    entries = set(os.listdir(md))
    for name in ("Briefing.md", "Changelog.md", "Decisions.md", "Handoff.md"):
        assert name in entries
    for alias in ("CHANGELOG.md", "DECISIONS.md", "handoff.md", "BRIEFING.md"):
        assert alias not in entries
    protected = set(os.listdir(md / "don't-delete"))
    assert protected == {
        "Audiobook-Creation-Tool-v0.6.x-Approved-Plan-Series-Map.md",
        "Audiobook-Creation-Tool-v0.6.x-Decision-Register-1-55.md",
        "Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md",
        "Audiobook-Creation-Tool-v0.6.x-Planning-Handoff-2026-07-31.md",
    }


def test_the_new_modules_ship_and_the_new_tests_do_not():
    """``scripts/`` ships; ``files/`` never does. The split must stay strict."""
    for name in PLAN3_MODULES:
        assert (SHARED / name).is_file()
    for name in ("test_importing.py", "test_job_control.py", "test_plan3_boundaries.py"):
        assert (TESTS / name).is_file()
        assert not (UNIVERSAL / name).exists()
