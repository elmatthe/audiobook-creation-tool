"""v0.6.4 Phase 11 — one authority per shared concern, mechanically.

The Plan 3/6 boundary suites pin *who may adopt* the shared foundation and
that no adopter re-implements it. With both M4B tools adopted, this file asks
the complementary question across the whole shipped tree: for each shared
concern there is still **exactly one** module that defines it, every consumer
reaches it there, the two tools keep their own business modules apart with no
generic M4B controller between them, the production panels are thin Tk
adapters, and the workers are handed frozen data only. Everything is read as
AST — a docstring can neither pass nor fail a guard here.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"

PRODUCTION = sorted(
    path for path in UNIVERSAL.rglob("*.py")
    if "__pycache__" not in path.parts and "epub2tts_edge" not in path.parts)


def relative(path: Path) -> str:
    return path.relative_to(UNIVERSAL).as_posix()


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


TREES = {relative(path): parse(path) for path in PRODUCTION}


def top_level_definitions(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


def imported_modules(tree: ast.Module) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.add(module)
            found |= {f"{module}.{alias.name}" for alias in node.names}
    return found


def call_names(tree: ast.Module) -> set[str]:
    return {node.func.attr if isinstance(node.func, ast.Attribute) else ast.unparse(node.func)
            for node in ast.walk(tree) if isinstance(node, ast.Call)}


def defined_in(name: str) -> list[str]:
    return sorted(module for module, tree in TREES.items() if name in top_level_definitions(tree))


#: Each shared concern, its one authority, and the names that prove it.
AUTHORITIES = {
    "Book model": ("shared/book_workspace.py", (
        "BookJob", "WorkspaceSnapshot", "SharedMetadata", "capture_workspace_run",
        "WorkspaceRunResult", "retry_failed_books", "disabled_fields", "has_meaningful_work",
        "select_book", "next_book", "previous_book", "remove_book", "duplicate_book")),
    "Book navigation and Shared surface": ("shared/book_workspace_ui.py", (
        "BookNavigator", "SharedMetadataSurface")),
    "importing": ("shared/importing.py", (
        "ImportedFileManager", "ImportedFile", "ImportedFileSnapshot", "SupportedTypeCatalog",
        "IdFactory")),
    "import coordination": ("shared/import_coordination.py", (
        "ImportCoordinator", "ImportPoller")),
    "job control": ("shared/job_control.py", (
        "JobController", "JobReporter", "JobEventStream", "RunResult", "FailureRecord",
        "FailureLog", "RetryRequest", "LoggerBridge", "EtaEstimator")),
    "job UI": ("shared/job_ui.py", (
        "JobAdapter", "LockGroup", "MainThreadPump", "MainThreadGuard", "SummaryDetailsView",
        "JobControlBar", "JobStatusView")),
    "output naming and reservation": ("shared/output_paths.py", (
        "reserve_run_directory", "RunReservation", "DestinationPlanner", "sanitize_component",
        "assert_not_input", "assert_contained", "assert_no_link_in",
        "validate_custom_destination", "temporary_sibling", "atomic_replace")),
    "M4B staging and publication": ("mp3_tools/m4b_staging.py", (
        "publish_staged", "require_owned", "prune_work_root", "StagingError")),
    "image capability": ("shared/image_capabilities.py", (
        "can_decode", "decodable_suffixes", "heif_capability", "FormatCapability")),
    "metadata reading and writing": ("shared/metadata.py", (
        "read_m4b_tags", "read_chapter_titles", "read_chapter_structure", "ChapterStructure",
        "ChapterRemuxError", "write_m4b_tags", "clear_metadata_keep_chapters",
        "clear_series_numbering", "apply_chapter_titles", "ffmetadata_header_lines",
        "ffmetadata_escape")),
    "success numbering": ("shared/numbering.py", ("SuccessNumbers",)),
    "M4B artwork service": ("mp3_tools/m4b_artwork.py", (
        "load_cover", "cover_for", "apply_cover", "embed_cover", "M4BCover")),
    "artwork preview and chooser filter": ("mp3_tools/mp3_artwork.py", (
        "preview_image", "artwork_filetypes", "Artwork", "ArtworkError")),
}

MAKER_FAMILY = ("mp3_tools/m4b_maker_workflow.py", "mp3_tools/m4b_maker_plan.py",
                "mp3_tools/m4b_maker_processing.py", "mp3_tools/m4b_maker_batch.py")
EDITOR_FAMILY = ("mp3_tools/m4b_metadata_workflow.py", "mp3_tools/m4b_metadata_plan.py",
                 "mp3_tools/m4b_metadata_processing.py", "mp3_tools/m4b_metadata_batch.py")
PANELS = ("mp3_tools/m4b_maker.py", "mp3_tools/m4b_metadata_editor.py")


# --------------------------------------------------------------------------- #
# Exactly one authority per concern
# --------------------------------------------------------------------------- #


def test_every_shared_concern_is_defined_in_exactly_one_module():
    for concern, (module, names) in AUTHORITIES.items():
        for name in names:
            assert defined_in(name) == [module], (concern, name, defined_in(name))


def referenced_attributes(tree: ast.Module) -> set[str]:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def test_the_metadata_writers_are_reached_only_by_the_two_engines_and_two_runners():
    """Called, or handed to a guarded step runner -- either way, only these four."""
    writers = {"write_m4b_tags", "clear_metadata_keep_chapters", "clear_series_numbering",
               "apply_chapter_titles"}
    users = {module for module, tree in TREES.items()
             if module != "shared/metadata.py" and referenced_attributes(tree) & writers}
    assert users == {"mp3_tools/m4b_maker_processing.py", "mp3_tools/m4b_maker_batch.py",
                     "mp3_tools/m4b_metadata_processing.py", "mp3_tools/m4b_metadata_batch.py"}


def test_the_staging_pattern_is_reached_only_through_the_two_engines():
    """Both engines delegate to it; the runners reach staging through their engine
    (the Editor's runner prunes the empty work root through the pattern itself)."""
    importers = {module for module, tree in TREES.items()
                 if module != "mp3_tools/m4b_staging.py"
                 and "mp3_tools.m4b_staging" in imported_modules(tree)}
    assert importers == {"mp3_tools/m4b_maker_processing.py",
                         "mp3_tools/m4b_metadata_processing.py",
                         "mp3_tools/m4b_metadata_batch.py"}
    for runner in ("mp3_tools/m4b_maker_batch.py", "mp3_tools/m4b_metadata_batch.py"):
        calls = {ast.unparse(node.func) for node in ast.walk(TREES[runner])
                 if isinstance(node, ast.Call)}
        assert {"proc.stage_book", "proc.publish_book", "proc.discard_staging"} <= calls, runner
        assert not any(name.startswith("m4b_staging.") and name != "m4b_staging.prune_work_root"
                       for name in calls), runner


def test_the_success_allocator_is_constructed_only_by_the_two_runners():
    builders = {module for module, tree in TREES.items()
                if module != "shared/numbering.py" and "SuccessNumbers" in {
                    ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}}
    assert builders == {"mp3_tools/m4b_maker_batch.py", "mp3_tools/m4b_metadata_batch.py"}
    for module in builders:
        calls = call_names(TREES[module])
        assert {"propose", "commit"} <= calls, module


def test_reservations_are_taken_only_by_tool_panels_through_the_shared_service():
    reservers = {module for module, tree in TREES.items()
                 if module != "shared/output_paths.py" and "reserve_run_directory" in call_names(tree)}
    assert reservers == {"mp3_tools/cover_resizer.py", "mp3_tools/m4b_converter.py",
                         "mp3_tools/m4b_maker.py", "mp3_tools/m4b_metadata_editor.py",
                         "mp3_tools/mp3_tool.py", "tts/epub2tts_gui.py"}


def test_image_capability_is_asked_only_where_the_probe_belongs():
    askers = {module for module, tree in TREES.items()
              if module != "shared/image_capabilities.py"
              and call_names(tree) & {"can_decode", "decodable_suffixes", "heif_capability"}}
    for panel in PANELS:
        assert panel not in askers, "a panel asks the artwork service, never the probe"
    assert "mp3_tools/m4b_artwork.py" in askers or "mp3_tools/mp3_artwork.py" in askers


# --------------------------------------------------------------------------- #
# No second framework, no generic M4B controller, separate business families
# --------------------------------------------------------------------------- #


def test_no_second_workspace_job_or_output_framework_exists():
    suspicious = {
        "Workspace": {"shared/book_workspace.py"},
        "Controller": {"shared/job_control.py"},
        # ``cleanup_worker`` keeps the Preferences cleanup coordinator's log, a
        # v0.6.2 module with no import, job or workspace role.
        "Coordinator": {"shared/import_coordination.py", "shared/cleanup_worker.py"},
        "Reservation": {"shared/output_paths.py"},
        "Planner": {"shared/output_paths.py"},
        "EventStream": {"shared/job_control.py"},
        "Reporter": {"shared/job_control.py"},
        "LockGroup": {"shared/job_ui.py"},
        "Pump": {"shared/job_ui.py"},
    }
    for fragment, allowed in suspicious.items():
        found = {module for module, tree in TREES.items()
                 if any(isinstance(node, ast.ClassDef) and fragment in node.name
                        and not node.name.endswith("Error")
                        for node in ast.walk(tree))}
        assert found <= allowed, (fragment, found - allowed)


def test_maker_and_editor_keep_separate_business_modules_with_no_shared_m4b_controller():
    for family, other in ((MAKER_FAMILY, "mp3_tools.m4b_metadata"),
                          (EDITOR_FAMILY, "mp3_tools.m4b_maker")):
        for module in family:
            assert module in TREES, module
            imports = imported_modules(TREES[module])
            assert not any(name.startswith(other) for name in imports), (module, other)
    for panel, other in (("mp3_tools/m4b_maker.py", "mp3_tools.m4b_metadata"),
                         ("mp3_tools/m4b_metadata_editor.py", "mp3_tools.m4b_maker")):
        imports = imported_modules(TREES[panel])
        assert not any(name.startswith(other) for name in imports), (panel, other)
    # The two runners share the shared framework and nothing tool-specific: each
    # defines its own Attempt and run class, each constructs the controller once.
    for runner, run_class in (("mp3_tools/m4b_maker_batch.py", "MakerRun"),
                              ("mp3_tools/m4b_metadata_batch.py", "EditorRun")):
        tree = TREES[runner]
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        assert {"Attempt", run_class, "BookRecord", "BatchError"} <= set(classes)
        assert all(not cls.bases for cls in (classes["Attempt"], classes[run_class])), \
            "no shared M4B base class: the shared framework is composed, not inherited"
        sites = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and ast.unparse(node.func).endswith("JobController")]
        assert len(sites) == 1, runner
    shared_m4b = {module for module in TREES if module.startswith("mp3_tools/m4b_")
                  and module not in MAKER_FAMILY + EDITOR_FAMILY + PANELS
                  and not module.startswith("mp3_tools/m4b_converter")}
    # The only modules both tools share below ``shared/``: the artwork service,
    # its Tk control and the staging pattern -- none of them runs a Book.
    m4b_shared = {m for m in shared_m4b if m in (
        "mp3_tools/m4b_artwork.py", "mp3_tools/m4b_artwork_ui.py", "mp3_tools/m4b_staging.py")}
    for module in m4b_shared:
        names = top_level_definitions(TREES[module])
        assert not any("Run" in n or "Attempt" in n or "Controller" in n for n in names), module
        built = {ast.unparse(node.func) for node in ast.walk(TREES[module])
                 if isinstance(node, ast.Call)}
        assert not any(name.endswith(("JobController", "JobReporter", "SuccessNumbers"))
                       for name in built), module


# --------------------------------------------------------------------------- #
# Thin panels, frozen data for workers
# --------------------------------------------------------------------------- #


def test_the_production_panels_are_thin_tk_adapters():
    for panel in PANELS:
        tree = TREES[panel]
        imports = imported_modules(tree)
        for banned in ("subprocess", "shared.ffmpeg_utils", "shared.metadata", "mutagen", "PIL",
                       "pillow_heif", "shared.image_capabilities", "shared.numbering",
                       "shared.cancellation", "shutil", "tempfile.NamedTemporaryFile"):
            assert not any(name == banned or name.startswith(banned + ".") for name in imports), (
                panel, banned)
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for suffix in (".jpg", ".jpeg", ".png", ".heic", ".heif", "image/"):
            assert not any(suffix in value.lower() for value in literals), (panel, suffix)
        calls = call_names(tree)
        for write in ("write_m4b_tags", "clear_metadata_keep_chapters", "clear_series_numbering",
                      "apply_chapter_titles", "copy2", "copyfile", "rmtree", "replace", "unlink",
                      "run", "Popen", "check_output", "propose", "commit", "plan"):
            assert write not in calls, (panel, write)
        for required in ("shared.book_workspace", "shared.book_workspace_ui", "shared.job_ui",
                         "shared.job_control", "shared.import_coordination", "shared.importing",
                         "mp3_tools.m4b_artwork_ui"):
            assert required in imports, (panel, required)


def test_the_workers_are_handed_frozen_plans_and_name_nothing_live():
    for runner in ("mp3_tools/m4b_maker_batch.py", "mp3_tools/m4b_metadata_batch.py"):
        tree = TREES[runner]
        attempt = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "Attempt")
        names = {node.id for node in ast.walk(attempt) if isinstance(node, ast.Name)}
        names |= {node.attr for node in ast.walk(attempt) if isinstance(node, ast.Attribute)}
        for live in ("WorkspaceSnapshot", "BookJob", "workspace", "StringVar", "BooleanVar",
                     "current", "configuration", "shared", "store", "get_effective", "settings"):
            assert live not in names, (runner, live)
        init = next(node for node in attempt.body
                    if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        params = {arg.arg for arg in init.args.args + init.args.kwonlyargs}
        assert {"books", "controller", "reporter"} <= params, runner
        imports = imported_modules(tree)
        assert "tkinter" not in imports and "threading" not in imports, runner


def test_the_launcher_registry_and_tool_families_are_exactly_as_expected():
    launcher = TREES["launcher.py"]
    tools = next(node for node in ast.walk(launcher)
                 if isinstance(node, (ast.Assign, ast.AnnAssign))
                 and any(isinstance(t, ast.Name) and t.id == "TOOLS"
                         for t in (node.targets if isinstance(node, ast.Assign)
                                   else [node.target])))
    assert len(tools.value.elts) == 6
    for module in MAKER_FAMILY + EDITOR_FAMILY + PANELS:
        assert module in TREES, module
    assert "mp3_tools/m4b_staging.py" in TREES and "mp3_tools/m4b_artwork.py" in TREES
    generic = [module for module in TREES if module.startswith("mp3_tools/m4b_")
               and module not in MAKER_FAMILY + EDITOR_FAMILY + PANELS
               and not module.startswith("mp3_tools/m4b_converter")
               and module not in ("mp3_tools/m4b_artwork.py", "mp3_tools/m4b_artwork_ui.py",
                                  "mp3_tools/m4b_staging.py")]
    converter_own = {"mp3_tools/m4b_execution.py", "mp3_tools/m4b_numbering.py",
                     "mp3_tools/m4b_probe.py", "mp3_tools/m4b_commands.py",
                     "mp3_tools/m4b_metadata.py", "mp3_tools/m4b_chapters.py",
                     "mp3_tools/m4b_destinations.py", "mp3_tools/m4b_plan.py",
                     "mp3_tools/m4b_naming.py", "mp3_tools/m4b_winaudio.py"}
    assert set(generic) <= converter_own, sorted(set(generic) - converter_own)
