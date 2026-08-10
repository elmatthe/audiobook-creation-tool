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
PLAN3_MODULES = ("importing.py", "job_control.py", "import_coordination.py")
PLAN3_MODULE_NAMES = ("importing", "job_control", "import_coordination", "job_ui")

#: The module that is pure *vocabulary and synchronous behaviour*. Phase 4 put its
#: thread and its queue in ``import_coordination.py``, and Phase 5 put its condition
#: in ``job_control.py``, precisely so this one keeps its approved proof that it
#: constructs no concurrency primitive at all — see the guards below.
PURE_VOCABULARY_MODULES = ("importing.py",)

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


@pytest.mark.parametrize("name", PURE_VOCABULARY_MODULES)
def test_a_plan3_module_starts_no_worker_and_owns_no_queue(plan3_trees, name):
    """Threads, queues and polling live in the coordinator, never in the vocabulary.

    Phase 4 could have folded its worker into ``importing.py``. Keeping it out is what
    lets this guard survive unchanged: the value objects, the traversal core and the
    imported-file manager are still provably free of concurrency, so anything that
    later grows a thread has to do it somewhere this test is watching.
    """
    tree = plan3_trees[name]
    for module in imported_names(tree):
        assert module.split(".")[0] not in {"queue", "asyncio", "concurrent", "multiprocessing"}, (
            name, module)
    constructed = called_attributes(tree) | called_bare_names(tree)
    for primitive in _CONCURRENCY_CONSTRUCTORS:
        assert primitive not in constructed, (name, primitive)


def test_the_only_threading_use_in_the_vocabulary_is_a_lock_for_identifiers():
    """``IdFactory`` needs a lock. A lock is not concurrency; a thread is."""
    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    assert "threading.Lock()" in text
    assert text.count("threading.") == 1, "threading is used for exactly one lock"


def test_the_job_controller_owns_one_condition_and_starts_nothing():
    """Phase 5's whole concurrency budget, pinned so it cannot quietly grow.

    A controller coordinates a worker; it never *is* one. One condition guards its
    own state and there is nothing else — no thread, no queue, no executor, no
    timer, and no second lock that could give two acquisition orders a chance to
    disagree.
    """
    tree = parse(SHARED / "job_control.py")
    modules = imported_names(tree)
    for forbidden in ("asyncio", "concurrent", "multiprocessing", "queue", "sched"):
        assert forbidden not in {entry.split(".")[0] for entry in modules}, forbidden

    constructed = called_attributes(tree) | called_bare_names(tree)
    for primitive in ("Thread", "Timer", "Queue", "SimpleQueue", "LifoQueue",
                      "PriorityQueue", "Semaphore", "BoundedSemaphore", "Barrier",
                      "ThreadPoolExecutor", "ProcessPoolExecutor", "Pool", "Process",
                      "Event"):
        assert primitive not in constructed, primitive

    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert text.count("threading.Condition(") == 1, "exactly one condition"
    assert text.count("threading.Lock()") == 1, "and exactly one lock, inside it"
    # A plain ``Lock``, not the default ``RLock``: re-entering from a listener must
    # deadlock a test rather than quietly succeed.
    assert "threading.Condition(threading.Lock())" in text


def test_the_pause_wait_is_a_condition_wait_and_never_a_sleep():
    """§6.10: "waits on a condition without busy-spinning" — checked in the source."""
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert "self._condition.wait()" in text
    assert "notify_all()" in text

    tree = parse(SHARED / "job_control.py")
    # Checked as *calls*, not as substrings: the prose is entitled to say the word
    # "sleep" while explaining that nothing here does it.
    called = called_attributes(tree) | called_bare_names(tree)
    for busy in ("sleep", "monotonic", "perf_counter", "time"):
        assert busy not in called, busy
    assert "time" not in {entry.split(".")[0] for entry in imported_names(tree)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "wait"):
            assert not node.args and not node.keywords, (
                "a timeout on the pause wait would be a poll wearing a condition's hat")


#: Calls that would either change something or follow a link. Neither Plan 3 module
#: may make any of these, in any phase.
_FORBIDDEN_FILESYSTEM_CALLS = (
    # writing, in any form
    "mkdir", "makedirs", "touch", "unlink", "rmdir", "rmtree", "remove",
    "write_text", "write_bytes", "copy", "copy2", "copytree", "move", "rename",
    "chmod", "chown", "utime", "truncate", "symlink", "link", "mkfifo",
    # reading contents rather than metadata
    "read_text", "read_bytes",
    # following, or asking a question that follows
    "resolve", "realpath", "samefile", "readlink",
    "stat", "exists", "is_file", "is_dir", "is_symlink", "is_mount",
    # bulk traversal helpers this drop deliberately does not use
    "walk", "iterdir", "glob", "rglob", "listdir",
)


def test_the_coordinator_owns_exactly_one_worker_and_one_queue():
    """Phase 4's whole concurrency budget, pinned so it cannot quietly grow.

    One thread factory, one queue, and the locks behind the cancellation flag and the
    progress gate. No executor, no pool, no second queue, no timer, and no ``asyncio``
    loop hiding behind an import.
    """
    tree = parse(SHARED / "import_coordination.py")
    modules = imported_names(tree)
    for forbidden in ("asyncio", "concurrent", "multiprocessing", "subprocess", "sched"):
        assert forbidden not in {entry.split(".")[0] for entry in modules}, forbidden

    constructed = called_attributes(tree) | called_bare_names(tree)
    for primitive in ("Timer", "ThreadPoolExecutor", "ProcessPoolExecutor", "Pool",
                      "Process", "Queue", "LifoQueue", "PriorityQueue", "Semaphore",
                      "BoundedSemaphore", "Barrier", "Condition"):
        assert primitive not in constructed, primitive

    text = (SHARED / "import_coordination.py").read_text(encoding="utf-8")
    assert text.count("threading.Thread(") == 1, "exactly one place creates a worker"
    assert text.count("queue.SimpleQueue()") == 1, "exactly one queue"
    assert ".daemon = " not in text, "the daemon flag is set at construction or not at all"


def test_the_coordinator_touches_no_filesystem_at_all():
    """It coordinates the scanner; it never becomes one.

    Every filesystem verb in this drop belongs to ``importing.py``, where the fail-
    closed rules live. ``Path.home()`` is the single exception and reads an
    environment variable rather than a disk — it classifies a broad root without
    scanning to decide, exactly as §6.7 requires.
    """
    tree = parse(SHARED / "import_coordination.py")
    attributes = called_attributes(tree)
    for forbidden in _FORBIDDEN_FILESYSTEM_CALLS + ("scandir", "lstat"):
        assert forbidden not in attributes, forbidden
    assert "open" not in called_bare_names(tree)
    assert attributes & {"home"} == {"home"}, "the one lexical exception is still there"


def test_import_cancellation_cannot_reach_the_processing_controller():
    """The mandatory Phase 4 isolation gate, proved structurally.

    ``Cancel Import`` may not invoke, share, mutate, wrap or replace the processing
    job's controller. The coordinator does not import that module at all, so there is
    nothing for it to reach — and the module it would have had to touch is byte-for-
    byte the one Plan 2 approved.
    """
    tree = parse(SHARED / "import_coordination.py")
    modules = imported_names(tree)
    assert not any("cancellation" in entry for entry in modules), modules

    assert not any(entry.startswith("shared.job_control") for entry in modules), modules

    text = (SHARED / "import_coordination.py").read_text(encoding="utf-8")
    for processing_concept in (
        "ConversionCancelled", "raise_if_cancelled", "JobState(", "JobController",
    ):
        assert processing_concept not in text, processing_concept

    # And the import-scoped primitive is genuinely its own: a plain Event, created per
    # operation, with no reset that could let a stale cancellation stop a fresh import.
    from shared.import_coordination import ImportCancellation

    first, second = ImportCancellation(), ImportCancellation()
    first.request()
    assert first.requested and not second.requested
    assert not hasattr(first, "reset")


def test_the_worker_never_had_a_manager_to_mutate():
    """Ownership as a property of the code, not a rule someone has to remember.

    ``_run_scan`` is a module-level function: everything it can see is a parameter,
    none of those parameters is the manager, and nothing in its body calls a mutation.
    """
    tree = parse(SHARED / "import_coordination.py")
    worker = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_scan")

    parameters = {
        argument.arg
        for group in (worker.args.args, worker.args.kwonlyargs, worker.args.posonlyargs)
        for argument in group
    }
    assert "manager" not in parameters
    assert not any("manager" in name for name in parameters), parameters

    called = {
        node.func.attr for node in ast.walk(worker)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for mutation in ("commit", "plan", "recompute", "remove_selected", "clear",
                     "move_selected_up", "move_selected_down", "select",
                     "clear_selection", "advance", "pump", "confirm_pending",
                     "decline_pending", "close"):
        assert mutation not in called, mutation

    for name in ast.walk(worker):
        if isinstance(name, ast.Name):
            assert "manager" not in name.id.lower(), name.id


def test_only_the_commit_helper_appends_to_the_manager():
    """One door into the list, so every unhappy path is one that never reaches it."""
    text = (SHARED / "import_coordination.py").read_text(encoding="utf-8")
    assert text.count("self._manager.commit(") == 2, (
        "the first attempt and the single recomputed retry, and nothing else")
    assert text.count("self._manager.plan(") == 1
    assert text.count("self._manager.recompute(") == 1
    tree = parse(SHARED / "import_coordination.py")
    committing = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "commit"
            for call in ast.walk(node))
    }
    assert committing == {"_commit"}, committing


def test_the_coordinator_depends_on_importing_and_not_the_other_way_round():
    coordination = imported_names(parse(SHARED / "import_coordination.py"))
    importing = imported_names(parse(SHARED / "importing.py"))
    job_control = imported_names(parse(SHARED / "job_control.py"))
    assert any(entry.startswith("shared.importing") for entry in coordination)
    for consumer in (importing, job_control):
        assert not any("import_coordination" in entry for entry in consumer)


def test_job_control_touches_no_filesystem_at_all():
    """The job vocabulary never had a reason to look at a disk, and still has none."""
    tree = parse(SHARED / "job_control.py")
    attributes = called_attributes(tree)
    for forbidden in _FORBIDDEN_FILESYSTEM_CALLS + ("scandir", "lstat"):
        assert forbidden not in attributes, forbidden
    assert "open" not in called_bare_names(tree)


def test_the_scanner_reads_metadata_and_can_never_write_or_follow():
    """Phase 2 gave ``importing`` exactly two filesystem verbs, and no more.

    ``scandir`` and ``lstat`` are the whole budget: both are read-only and neither
    follows a link. Every write, every content read and every following call stays
    forbidden — ``resolve`` and ``stat`` especially, because those are the two that
    would quietly walk through a junction.
    """
    tree = parse(SHARED / "importing.py")
    attributes = called_attributes(tree)
    for forbidden in _FORBIDDEN_FILESYSTEM_CALLS:
        assert forbidden not in attributes, forbidden
    assert "open" not in called_bare_names(tree)

    filesystem_verbs = {"scandir", "lstat"} & attributes
    assert filesystem_verbs == {"scandir", "lstat"}, \
        "the traversal core is expected to use exactly these two"

    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    assert "follow_symlinks=True" not in text
    assert ".resolve()" not in text


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_a_plan3_module_reimplements_no_plan2_service(plan3_trees, name):
    """§5.2: extend the existing services, never grow a parallel one."""
    tree = plan3_trees[name]
    modules = imported_names(tree)
    forbidden_modules = [
        "tomllib", "subprocess", "logging", "shutil", "socket", "urllib", "http",
        "shared.output_paths", "shared.settings", "shared.preferences_ui",
        "shared.cleanup_state", "shared.cleanup_worker",
        "shared.release", "shared.logging_setup", "shared.subprocess_utils",
        "shared.ui_theme", "shared.ffmpeg_utils", "shared.metadata", "shared.bootstrap",
    ]
    if name != "importing.py":
        # Phase 2 gave the scanner one narrow, sanctioned edge to maintenance; the
        # test below pins it to exactly ``is_link``.
        forbidden_modules.append("shared.maintenance")
    for forbidden in forbidden_modules:
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


def test_the_scanner_borrows_exactly_one_name_from_maintenance():
    """The sanctioned edge, and nothing wider.

    The active drop directs Phase 2 to reuse ``maintenance.is_link`` rather than grow
    a second link classifier — a junction reports ``is_symlink() == False``, so a
    naive check would fail open on the exact case that matters most. What must not
    follow is the rest of the cleanup module leaking into the importer, so this pins
    the edge to one function and proves nothing was refactored to make it fit.
    """
    tree = parse(SHARED / "importing.py")
    borrowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("maintenance"):
            borrowed |= {alias.name for alias in node.names}
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.endswith("maintenance"), \
                    "import the one function, not the whole cleanup module"
    assert borrowed == {"is_link"}, borrowed

    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    for cleanup_concept in (
        "authorized_target", "compiled_target", "inventory", "estimate_size",
        "PROTECTED_RELATIVE", "ASSET_IDS", "CleanupRequest", "asset(",
    ):
        assert cleanup_concept not in text, cleanup_concept


def test_maintenance_itself_was_not_refactored_for_the_importer():
    """Reuse, not rearrangement. ``is_link`` keeps its shape and its one caller set."""
    tree = parse(SHARED / "maintenance.py")
    defined = defined_names(tree)
    for name in ("is_link", "_is_link", "authorized_target", "inventory", "estimate_size"):
        assert name in defined, name
    modules = imported_names(tree)
    for plan3 in PLAN3_MODULE_NAMES:
        assert not any(entry.endswith(plan3) for entry in modules), plan3
    # Its own standing guarantee, checked from this side too: the module that the
    # importer now borrows from still imports nothing that could delete anything.
    # (``test_maintenance.py`` owns the full version of this contract.)
    for destructive in ("shutil", "subprocess"):
        assert destructive not in modules, destructive


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
    """The Phase 5 compatibility gate, checked in code rather than promised.

    Phase 5 was authorized to extend this module. What it was not authorized to do
    is change what was already there, so both original names keep their exact
    signature and their exact observable behaviour — including the default message
    — and the only growth is one additive predicate beside them.
    """
    import inspect

    from shared import cancellation

    assert issubclass(cancellation.ConversionCancelled, Exception)
    assert cancellation.ConversionCancelled.__mro__[1] is Exception
    assert str(inspect.signature(cancellation.raise_if_cancelled)) == (
        "(cancel_check: 'CancelCheck', message: 'str' = 'Cancelled.') -> 'None'")
    assert cancellation.raise_if_cancelled(None) is None
    assert cancellation.raise_if_cancelled(lambda: False) is None
    with pytest.raises(cancellation.ConversionCancelled) as excinfo:
        cancellation.raise_if_cancelled(lambda: True)
    assert str(excinfo.value) == "Cancelled."
    with pytest.raises(cancellation.ConversionCancelled) as excinfo:
        cancellation.raise_if_cancelled(lambda: True, "Stopped.")
    assert "Stopped." in str(excinfo.value)

    # Additive only: the non-raising counterpart follows the same ``None`` rule.
    assert cancellation.is_cancelled(None) is False
    assert cancellation.is_cancelled(lambda: True) is True

    tree = parse(SHARED / "cancellation.py")
    assert defined_names(tree) == {
        "ConversionCancelled", "raise_if_cancelled", "is_cancelled"}
    assert imported_names(tree) == {"__future__", "__future__.annotations",
                                    "typing", "typing.Callable", "typing.Optional"}


def test_every_pre_existing_caller_of_the_cancellation_api_still_resolves():
    """The six production modules and two tests that already import these names."""
    callers = {
        "mp3_tools/m4b_maker.py": ("ConversionCancelled", "raise_if_cancelled"),
        "mp3_tools/m4b_metadata_editor.py": ("ConversionCancelled", "raise_if_cancelled"),
        "mp3_tools/mp3_tool.py": ("ConversionCancelled", "raise_if_cancelled"),
        "tts/epub2tts_gui.py": ("ConversionCancelled",),
        "tts/epub2tts_edge/epub2tts_edge.py": ("ConversionCancelled",),
        "tts/kokoro_synth.py": ("ConversionCancelled",),
    }
    from shared import cancellation

    for relative, names in callers.items():
        text = (UNIVERSAL / relative).read_text(encoding="utf-8")
        for name in names:
            assert f"from shared.cancellation import" in text, relative
            assert name in text, (relative, name)
            assert hasattr(cancellation, name), name


def test_only_the_job_controller_may_raise_the_conversion_exception():
    """Phase 5 extends the cooperative pattern; the importer stays out of it.

    ``job_control.py`` is now authorized to raise ``ConversionCancelled`` at its
    checkpoint — that *is* the compatible extension. The importing modules are not,
    and must keep their own unrelated cancellation, which is what stops a Cancel
    Import button from ever reaching a conversion.
    """
    authorized = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert "ConversionCancelled" in authorized
    assert "from shared.cancellation import ConversionCancelled" in authorized

    for name in ("importing.py", "import_coordination.py"):
        text = (SHARED / name).read_text(encoding="utf-8")
        assert "ConversionCancelled" not in text, name
        assert "raise_if_cancelled" not in text, name
        assert "is_cancelled" not in text, name
        modules = imported_names(parse(SHARED / name))
        assert not any("cancellation" in entry for entry in modules), (name, modules)


# --------------------------------------------------------------------------- #
# No later-phase behaviour has leaked in
# --------------------------------------------------------------------------- #


#: Phase 3 landed the imported-file manager in ``importing.py``. These names stay
#: forbidden in ``job_control.py``, which owns no list, no selection and no
#: transaction — a job runs what the manager already decided.
_PHASE_THREE_NAMES = (
    "ImportedFileManager", "ImportTransaction", "CommitResult", "MutationResult",
    "add_files", "add_folder", "move_up", "move_down", "remove_selected",
    "clear_all", "commit", "deduplicate", "allow_duplicates",
)

#: Phase 4 landed coordination in ``import_coordination.py``. These names stay
#: forbidden in the two vocabulary modules, which own no thread and no lifecycle.
#: ``request_cancel`` sits here rather than under Phase 5 because the *import*
#: cancellation now owns that name; Phase 5's controller will define its own on
#: ``job_control.py``, and this list moves again then — exactly as it did now.
_PHASE_FOUR_NAMES = (
    "ImportCoordinator", "ImportPoller", "ImportCancellation", "ImportEvent",
    "ImportOutcome", "StartReport", "CloseReport", "request_cancel", "pump",
    "confirm_pending", "decline_pending", "import_files",
)

#: Phase 5 landed the cooperative controller in ``job_control.py``. These names stay
#: forbidden in the importing modules, which run no job and own no run state.
#: ``request_cancel`` is deliberately absent: both the import coordinator and the job
#: controller legitimately own that name now, each for its own subsystem, which is
#: exactly the separation Phase 4's isolation gate exists to keep.
_PHASE_FIVE_NAMES = (
    "JobController", "JobSnapshot", "request_pause", "resume", "checkpoint",
    "succeed", "complete_with_failures", "finish_cancelled",
)

#: Still owned by a later phase, in every module this drop has so far.
_LATER_PHASE_NAMES = (
    # Phase 7 ETA / projection
    "EtaEstimator", "estimate_remaining", "summary_lines", "detail_lines",
    # Phase 8 adapters
    "ImportedFileList", "JobControlBar", "build_ui",
)

#: What each module is forbidden from defining, now that Phase 5 has landed.
_FORBIDDEN_BY_MODULE = {
    "importing.py": (
        _LATER_PHASE_NAMES + _PHASE_FOUR_NAMES + _PHASE_FIVE_NAMES
        + ("request_cancel",)),
    "job_control.py": _LATER_PHASE_NAMES + _PHASE_THREE_NAMES + tuple(
        name for name in _PHASE_FOUR_NAMES if name != "request_cancel"),
    # The coordinator drives the manager; it must never grow a second one, and it
    # runs no processing job either.
    "import_coordination.py": (
        _LATER_PHASE_NAMES + _PHASE_THREE_NAMES + _PHASE_FIVE_NAMES),
}


@pytest.mark.parametrize("name", PLAN3_MODULES)
def test_no_phase_six_to_eight_behaviour_exists_yet(plan3_trees, name):
    """Each phase's own names move off this list as they are implemented.

    Phase 2's traversal core and Phase 3's manager live in ``importing.py``; Phase 4's
    import lifecycle lives in ``import_coordination.py``; Phase 5's run controller
    lives in ``job_control.py``. Everything below still belongs to a later phase, and
    each module stays out of the other two's business: the job module owns no
    imported-file list, and the importing modules run no job.
    """
    defined = defined_names(plan3_trees[name])
    for later_phase in _FORBIDDEN_BY_MODULE[name]:
        assert later_phase not in defined, (name, later_phase)


def test_phase_six_delivered_its_own_names_and_no_more():
    """Capture, locking, outcomes and retry exist; Phase 7's reporting does not."""
    from shared import job_control

    for delivered in (
        "capture_run", "ControlKind", "LOCK_MATRIX", "is_locked",
        "JobAction", "is_available", "ItemStatus", "ItemOutcome", "RunResult",
    ):
        assert hasattr(job_control, delivered), delivered

    for later in ("EtaEstimator", "estimate_remaining", "summary_lines",
                  "detail_lines", "ProgressReport", "JobEventStream"):
        assert not hasattr(job_control, later), later


def test_phase_six_added_no_output_descriptor():
    """§8's Phase 6 risk gate, honoured by omission and checked here.

    A generic "where did this item go" field would duplicate Plan 2 and contradict
    it the first time the two disagreed. Nothing in the outcome, the result or the
    retry names a destination, and the module still imports no output service.
    """
    from shared.job_control import ItemOutcome, RetryRequest, RunResult

    for owner in (ItemOutcome, RunResult, RetryRequest):
        fields = set(getattr(owner, "__slots__", ()))
        for forbidden in ("output", "output_path", "destination", "output_base",
                          "run_directory", "reservation", "planned", "plan"):
            assert forbidden not in fields, (owner.__name__, forbidden)

    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for owned_by_output_paths in (
        "numbered_variant", "sanitize_component", "sanitize_relative",
        "reserve_run_directory", "release_if_empty", "assert_contained",
        "atomic_replace", "temporary_sibling", "MAX_COLLISION_ATTEMPTS",
        "TOOL_OUTPUT_PARENTS", "OutputPlan", "PlannedOutput", "DestinationPlanner",
    ):
        assert owned_by_output_paths not in text, owned_by_output_paths


def test_the_lock_matrix_is_derived_and_exhaustive():
    """Every kind classified in every state, from the Phase 1 frozen set alone."""
    from shared.job_control import (
        INPUT_LOCKED_STATES, LOCK_MATRIX, ControlKind, JobState, is_locked)

    assert set(LOCK_MATRIX) == set(ControlKind), "no kind may be silently absent"
    for kind in ControlKind:
        for state in JobState:
            assert isinstance(is_locked(kind, state), bool), (kind, state)
    locked_states = {
        state for kind in ControlKind for state in JobState if is_locked(kind, state)}
    assert locked_states == set(INPUT_LOCKED_STATES), (
        "the matrix locks exactly the states Phase 1 froze, and derives them")


def test_an_item_failure_cannot_force_a_job_level_failure():
    """§6.14: a run that lost items still completed; only a fatal record fails it."""
    tree = parse(SHARED / "job_control.py")
    result_class = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "RunResult")
    called = {
        node.func.attr for node in ast.walk(result_class)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for controller_call in ("fail", "succeed", "complete_with_failures",
                            "finish_cancelled", "request_cancel", "checkpoint"):
        assert controller_call not in called, controller_call
    # And no instance of the controller is constructed anywhere near the result.
    assert "JobController(" not in ast.get_source_segment(
        (SHARED / "job_control.py").read_text(encoding="utf-8"), result_class)


def test_phase_five_delivered_its_own_names_and_no_more():
    """The run controller exists, in the job module, and nothing beyond it does."""
    from shared import import_coordination, importing, job_control

    for delivered in (
        # Phase 1 vocabulary
        "JobState", "LEGAL_TRANSITIONS", "TERMINAL_STATES", "freeze_options",
        "RunSnapshot", "FailureRecord", "FailureLog", "RetryRequest", "JobEvent",
        # Phase 5
        "JobController", "JobSnapshot", "MAX_FAILURE_DETAIL",
    ):
        assert hasattr(job_control, delivered), delivered

    for later in ("EtaEstimator", "estimate_remaining", "JobControlBar",
                  "ImportedFileList", "build_ui"):
        assert not hasattr(job_control, later), later
    # The controller runs a job; it does not own an imported list or an import.
    for foreign in ("ImportedFileManager", "ImportCoordinator", "ImportPoller"):
        assert not hasattr(job_control, foreign), foreign
    for foreign in ("JobController", "JobSnapshot"):
        assert not hasattr(importing, foreign), foreign
        assert not hasattr(import_coordination, foreign), foreign


def test_phase_four_delivered_its_own_names_and_no_more():
    """The coordinator exists, in its own module, and nothing beyond it does."""
    from shared import import_coordination, importing

    for delivered in (
        # Phase 2
        "scan_roots", "natural_key", "classify_root_breadth", "is_broad_root",
        "is_hidden_name", "has_hidden_attribute", "capture_identity", "RootBreadth",
        # Phase 3
        "ImportedFileManager", "ImportTransaction", "CommitResult", "MutationResult",
        "CommitStatus", "ManagerOperation", "PlanningGroups",
        "validate_direct_files", "plan_transaction", "planning_groups",
    ):
        assert hasattr(importing, delivered), delivered

    for delivered in (
        "ImportCoordinator", "ImportPoller", "ImportCancellation", "ImportEvent",
        "ImportEventKind", "ImportOutcome", "OutcomeStatus", "ImportPhase",
        "StartOutcome", "StartReport", "CloseReport", "ImportCoordinationError",
    ):
        assert hasattr(import_coordination, delivered), delivered

    for later in ("EtaEstimator", "JobController", "ImportedFileList", "JobControlBar"):
        assert not hasattr(importing, later), later
        assert not hasattr(import_coordination, later), later
    # The vocabulary module gained nothing from Phase 4.
    assert not hasattr(importing, "ImportCoordinator")


def test_the_manager_neither_plans_nor_creates_an_output_path():
    """§6.8: the importer *retains* root and relative data; Plan 2 turns it into paths.

    ``planning_groups`` is a regrouping and nothing more. If collision numbering,
    sanitising or run reservation ever appeared here, two services would be deciding
    where a file lands and they would eventually disagree.
    """
    text = (SHARED / "importing.py").read_text(encoding="utf-8")
    for owned_by_output_paths in (
        "numbered_variant", "sanitize_component", "sanitize_relative",
        "reserve_run_directory", "release_if_empty", "assert_contained",
        "atomic_replace", "temporary_sibling", "MAX_COLLISION_ATTEMPTS",
        "TOOL_OUTPUT_PARENTS", "OutputPlan", "PlannedOutput",
    ):
        assert owned_by_output_paths not in text, owned_by_output_paths

    tree = parse(SHARED / "importing.py")
    modules = imported_names(tree)
    assert not any(entry.startswith("shared.output_paths") for entry in modules)


def test_output_paths_was_not_changed_for_the_importer():
    """Reuse, not rearrangement — the Phase 3 compatibility gate, checked in code."""
    tree = parse(SHARED / "output_paths.py")
    defined = defined_names(tree)
    for planner in ("plan_flat", "plan_mirrored", "plan_multi_root",
                    "DestinationPlanner", "RunReservation", "reserve_run_directory"):
        assert planner in defined, planner
    modules = imported_names(tree)
    for plan3 in PLAN3_MODULE_NAMES:
        assert not any(entry.endswith(plan3) for entry in modules), plan3


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
    for name in ("test_importing.py", "test_job_control.py", "test_plan3_boundaries.py",
                 "test_import_traversal.py", "test_import_manager.py",
                 "test_import_coordination.py", "test_job_controller.py",
                 "test_job_run_results.py"):
        assert (TESTS / name).is_file()
        assert not (UNIVERSAL / name).exists()
