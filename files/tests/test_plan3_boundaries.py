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

#: The Tk-free core this drop owns. ``job_ui.py`` is deliberately **not** here: Phase 8
#: made it the one module allowed to import Tk, and every guard below that says "no Tk"
#: is precisely the guarantee the adapter exists to keep true of everything else.
PLAN3_MODULES = ("importing.py", "job_control.py", "import_coordination.py")

#: Phase 8's adapter module. One module, per §6.15.
ADAPTER_MODULE = "job_ui.py"

#: Every module this drop owns, adapter included.
ALL_PLAN3_MODULES = PLAN3_MODULES + (ADAPTER_MODULE,)

PLAN3_MODULE_NAMES = ("importing", "job_control", "import_coordination", "job_ui")

#: The module that is pure *vocabulary and synchronous behaviour*. Phase 4 put its
#: thread and its queue in ``import_coordination.py``, and Phase 5 put its condition
#: in ``job_control.py``, precisely so this one keeps its approved proof that it
#: constructs no concurrency primitive at all — see the guards below.
PURE_VOCABULARY_MODULES = ("importing.py",)

#: Every production module that must remain unaware of Plan 3. The adapter is excluded
#: because composing the foundation is the one thing it is *for*; that it is still
#: adopted by nothing is proved separately, from the launcher and panel side.
PRODUCTION_SOURCES = tuple(
    path for path in sorted(UNIVERSAL.rglob("*.py"))
    if path.name not in ALL_PLAN3_MODULES and "__pycache__" not in path.parts
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

#: The production modules that have **adopted** the Plan 3 foundation, and are
#: therefore excluded from the two no-adoption guards below.
#:
#: Plan 3 shipped the foundation adopted by nothing, and these guards proved it.
#: Plan 4 adopts it, one panel at a time, so the guards are **narrowed** to the
#: modules that have not adopted yet rather than deleted or weakened — every
#: other panel and every other module in ``scripts/Universal/`` is still held to
#: exactly the boundary Plan 3 approved.
#:
#: v0.6.1 Plan 4 Phase 2 added the Cover panel. Plan 4 Phase 11 owns the rest of
#: this migration — the TTS panel, and replacing the substring mechanism in
#: ``test_tool_output_integration`` — so nothing else belongs here yet. Adding a
#: name to this tuple is the only way a module can start using the foundation,
#: and ``test_exactly_these_production_modules_have_adopted_the_foundation``
#: pins the tuple against the tree so it cannot drift.
ADOPTED = ("mp3_tools/cover_resizer.py",)


def relative_name(path: Path) -> str:
    return str(path.relative_to(UNIVERSAL)).replace(os.sep, "/")


#: Everything still required to know nothing of Plan 3.
UNADOPTED_SOURCES = tuple(
    path for path in PRODUCTION_SOURCES if relative_name(path) not in set(ADOPTED))
UNADOPTED_PANELS = tuple(entry for entry in PANELS if entry not in set(ADOPTED))


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

    Phase 7 added exactly one more lock to the module, and it belongs to
    ``JobReporter``'s sequence counter rather than to the controller. The counts
    below are therefore checked *per class*, which is a stronger statement than the
    module-wide count it replaces: the controller's budget is still one condition and
    the one lock inside it, and the reporter's is one plain lock over an integer.
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
    sources = {
        node.name: ast.get_source_segment(text, node)
        for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    controller = sources["JobController"]
    assert controller.count("threading.Condition(") == 1, "exactly one condition"
    assert controller.count("threading.Lock()") == 1, "and exactly one lock, inside it"
    # A plain ``Lock``, not the default ``RLock``: re-entering from a listener must
    # deadlock a test rather than quietly succeed.
    assert "threading.Condition(threading.Lock())" in controller

    reporter = sources["JobReporter"]
    assert reporter.count("threading.Lock()") == 1, "one lock, over the counter"
    assert "Condition" not in reporter, "numbering needs no one to wait on it"

    holders = {
        name for name, source in sources.items() if "threading.Lock()" in source}
    assert holders == {"JobController", "JobReporter"}, holders


def test_the_reporter_calls_no_user_code_while_holding_its_lock():
    """§5.4, checked where Phase 7 could most easily have broken it.

    The clock and the publisher both belong to the caller. Neither may be invoked
    inside the ``with self._lock`` block, because a lock held across somebody else's
    code is how a reporting call ends up deadlocking a conversion.
    """
    tree = parse(SHARED / "job_control.py")
    emit = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_emit")
    guarded = [node for node in ast.walk(emit) if isinstance(node, ast.With)]
    assert len(guarded) == 1, "one guarded region"
    inside = {
        call.func.attr for call in ast.walk(guarded[0])
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    for user_code in ("_clock", "_publish"):
        assert user_code not in inside, user_code


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
        "shared.release", "shared.subprocess_utils",
        "shared.ui_theme", "shared.ffmpeg_utils", "shared.metadata", "shared.bootstrap",
    ]
    if name != "job_control.py":
        # §8's Phase 7 task 2 directs the job module to bridge technical events into
        # ``logging_setup.get_logger()``. *Using* the one session logger is the
        # opposite of reimplementing it — which is why the stdlib ``logging`` import
        # stays forbidden above for every module including this one, and why the
        # guard below pins what the bridge is allowed to do with it.
        forbidden_modules.append("shared.logging_setup")
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


@pytest.mark.parametrize("path", UNADOPTED_SOURCES, ids=relative_name)
def test_no_production_module_imports_the_plan3_foundation(path):
    """The whole shipped tree, minus the modules in ``ADOPTED``.

    Unchanged in mechanism and in strictness; only the parametrization narrowed,
    so every module that has not adopted is held to the same boundary.
    """
    modules = imported_names(parse(path))
    for plan3 in PLAN3_MODULE_NAMES:
        assert f"shared.{plan3}" not in modules, (path.name, plan3)
        assert not any(entry.startswith(f"shared.{plan3}.") for entry in modules), path.name
        assert f"shared.{plan3}" not in modules


@pytest.mark.parametrize("relative", UNADOPTED_PANELS)
def test_the_launcher_and_every_panel_still_names_nothing_from_plan3(relative):
    text = (UNIVERSAL / relative).read_text(encoding="utf-8")
    for plan3 in PLAN3_MODULE_NAMES:
        assert f"shared.{plan3}" not in text, (relative, plan3)
        assert f"import {plan3}" not in text, (relative, plan3)
    for vocabulary in ("RunSnapshot", "RetryRequest", "FailureLog", "JobState",
                       "ImportedFileSnapshot", "SupportedTypeCatalog", "ScanRequest"):
        assert vocabulary not in text, (relative, vocabulary)


def test_exactly_these_production_modules_have_adopted_the_foundation():
    """``ADOPTED`` is measured against the tree, not trusted.

    This is what keeps narrowing the two guards above honest: a module that
    starts importing the foundation without being listed fails here, and a
    module listed here that does *not* import it fails here too. So the
    exclusion list can neither grow silently nor be padded to make a guard pass.
    """
    importers = set()
    for path in PRODUCTION_SOURCES:
        modules = imported_names(parse(path))
        if any(f"shared.{plan3}" in modules or
               any(entry.startswith(f"shared.{plan3}.") for entry in modules)
               for plan3 in PLAN3_MODULE_NAMES):
            importers.add(relative_name(path))
    assert importers == set(ADOPTED), importers


def test_the_adopting_panel_composes_the_foundation_and_reimplements_none_of_it():
    """Adoption means *using* the shared services, not copying them.

    Cover may name the foundation; what it may not do is define its own manager,
    coordinator, poller, adapter or pump beside it. Checked by AST over the
    panel's own class and function definitions rather than by substring, so a
    comment or a docstring cannot pass or fail it.
    """
    forbidden = {
        "ImportedFileManager", "ImportCoordinator", "ImportPoller",
        "ImportAdapter", "MainThreadPump", "ImportedFileList", "ImportOptionsBar",
        "ImportStatusBar", "JobController", "JobAdapter",
    }
    for relative in ADOPTED:
        tree = parse(UNIVERSAL / relative)
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not (defined & forbidden), (relative, defined & forbidden)
        modules = imported_names(tree)
        assert "shared.importing" in modules, relative
        assert "shared.import_coordination" in modules, relative
        assert "shared.job_ui" in modules, relative


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

#: Phase 7 landed reporting in ``job_control.py``. These names stay forbidden in the
#: importing modules, which report no job. ``pump`` is deliberately absent for the
#: same reason ``request_cancel`` is: the import coordinator and the job event stream
#: each legitimately drain their own subsystem's queue, and one name owned by two
#: subsystems is exactly the separation Phase 4's isolation gate exists to keep.
_PHASE_SEVEN_NAMES = (
    "JobReporter", "JobEventStream", "EventVerdict", "LoggerBridge", "EtaEstimator",
    "ProgressTracker", "ProgressView", "ProgressMode", "SummaryView",
    "summary_lines", "detail_lines", "project_summary", "state_message",
    "format_duration",
)

#: Phase 8 landed the adapters in ``job_ui.py``. These names stay forbidden in all three
#: Tk-free modules, which draw nothing. ``build_ui``, ``JobPanel`` and ``ImportPanel``
#: are forbidden **everywhere including the adapter**: §6.15 asks for composition and
#: callbacks rather than a universal base panel a later tool would have to fight, and
#: those three were the shapes that would have been one.
_LATER_PHASE_NAMES = (
    "ImportedFileList", "JobControlBar", "build_ui", "JobPanel", "ImportPanel",
)

#: What no module in this drop may define, in any phase — the base-panel shapes above.
_FORBIDDEN_EVERYWHERE = ("build_ui", "JobPanel", "ImportPanel", "BasePanel", "ToolPanel")

#: What Phase 8 delivered, in the one module §6.15 puts it in.
_PHASE_EIGHT_NAMES = (
    "MainThreadGuard", "MainThreadError", "MainThreadPump", "LockGroup",
    "ImportedFileList", "ImportOptionsBar", "ImportStatusBar", "ImportAdapter",
    "JobControlBar", "JobStatusView", "SummaryDetailsView", "JobAdapter",
    "style_name", "queue_pull", "ask_files", "ask_folder", "ask_confirm",
)

#: What each module is forbidden from defining, now that Phase 7 has landed.
_FORBIDDEN_BY_MODULE = {
    "importing.py": (
        _LATER_PHASE_NAMES + _PHASE_FOUR_NAMES + _PHASE_FIVE_NAMES
        + _PHASE_SEVEN_NAMES + ("request_cancel",)),
    "job_control.py": _LATER_PHASE_NAMES + _PHASE_THREE_NAMES + tuple(
        name for name in _PHASE_FOUR_NAMES
        if name not in ("request_cancel", "pump")),
    # The coordinator drives the manager; it must never grow a second one, and it
    # runs no processing job either.
    "import_coordination.py": (
        _LATER_PHASE_NAMES + _PHASE_THREE_NAMES + _PHASE_FIVE_NAMES
        + _PHASE_SEVEN_NAMES),
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
    """Capture, locking, outcomes and retry exist, and still do."""
    from shared import job_control

    for delivered in (
        "capture_run", "ControlKind", "LOCK_MATRIX", "is_locked",
        "JobAction", "is_available", "ItemStatus", "ItemOutcome", "RunResult",
    ):
        assert hasattr(job_control, delivered), delivered


def test_phase_seven_delivered_its_own_names_and_no_more():
    """Reporting exists, in the job module, and Phase 8's adapters still do not."""
    from shared import import_coordination, importing, job_control

    for delivered in _PHASE_SEVEN_NAMES + (
        "SUMMARY_KINDS", "CALCULATING", "DEFAULT_MINIMUM_SAMPLES",
        "DEFAULT_SAMPLE_WINDOW", "IDLE_PROGRESS",
    ):
        assert hasattr(job_control, delivered), delivered

    for later in _LATER_PHASE_NAMES:
        assert not hasattr(job_control, later), later
    # Reporting a job is not importing files: neither importing module gained any
    # of it, and the job module still owns no imported list and no import lifecycle.
    for module in (importing, import_coordination):
        for foreign in _PHASE_SEVEN_NAMES:
            assert not hasattr(module, foreign), (module.__name__, foreign)
    for foreign in ("ImportedFileManager", "ImportCoordinator", "ImportPoller"):
        assert not hasattr(job_control, foreign), foreign


def test_the_phase_seven_surface_is_pure_and_owns_no_lifecycle():
    """It reports a run. It does not run one, render one, or store one."""
    from shared import job_control

    assert job_control.SUMMARY_KINDS.isdisjoint({
        job_control.JobEventKind.PROGRESS,
        job_control.JobEventKind.CURRENT_ITEM,
        job_control.JobEventKind.TECHNICAL_DETAIL,
    }), "per-item churn and diagnostics never become Summary lines"

    # The event vocabulary Phase 1 froze was extended by nothing.
    assert len(job_control.JobEventKind) == 11
    assert job_control.JobEvent.__slots__ == (
        "kind", "run_id", "sequence", "timestamp", "message", "detail", "state",
        "stage", "item_id", "completed", "total", "count", "location")

    # And no severity, lineage or output field arrived on the new types either.
    for owner in (job_control.ProgressView, job_control.SummaryView):
        fields = set(getattr(owner, "__slots__", ()))
        for forbidden in ("severity", "level", "lineage", "parent_run", "output",
                          "output_path", "destination", "run_directory",
                          "reservation"):
            assert forbidden not in fields, (owner.__name__, forbidden)


def test_no_second_progress_or_logging_implementation_exists():
    """§5.2: reuse ``ProgressIndicator`` and the session logger; build neither again."""
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for owned_by_ui_theme in ("Progressbar", "ProgressIndicator(", "ttk.", "apply_theme"):
        assert owned_by_ui_theme not in text, owned_by_ui_theme
    for owned_by_logging_setup in (
        "FileHandler", "StreamHandler", "basicConfig", "addHandler", "setFormatter",
        "Formatter", "setLevel", "getLogger", "max_sessions", "_prune_old_logs",
        "LOGS_DIR", "logs_dir",
    ):
        assert owned_by_logging_setup not in text, owned_by_logging_setup
    assert "logging_setup.get_logger()" in text, "it uses the one that already exists"

    # The two reused services are themselves untouched by this drop.
    for reused in ("logging_setup.py", "ui_theme.py"):
        modules = imported_names(parse(SHARED / reused))
        for plan3 in PLAN3_MODULE_NAMES:
            assert not any(entry.endswith(plan3) for entry in modules), (reused, plan3)
    theme = defined_names(parse(SHARED / "ui_theme.py"))
    assert "ProgressIndicator" in theme
    assert defined_names(parse(SHARED / "logging_setup.py")) == {
        "configured_max_sessions", "_prune_old_logs", "get_logger"}


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

    for later in _LATER_PHASE_NAMES:
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


def test_no_module_in_the_foundation_reads_a_clock_of_its_own():
    """Every timestamp and every duration arrives through an injected clock.

    Phase 7 gave ``job_control.py`` the estimator, so it now subtracts timestamps —
    but it still may not *read* one. That is what keeps the whole of §6.13 testable
    with a fake clock and without a single sleep. Phase 8's adapter is held to the same
    rule for the same reason: an adapter that read a clock could produce a timestamp
    nobody injected, and the boundary test would have nothing to pin.
    """
    for name in ALL_PLAN3_MODULES:
        tree = plan3_trees_for(name)
        top_level = {entry.split(".")[0] for entry in imported_names(tree)}
        for clock_module in ("time", "datetime", "calendar"):
            assert clock_module not in top_level, (name, clock_module)
        called = called_attributes(tree) | called_bare_names(tree)
        for clock in ("monotonic", "perf_counter", "time", "now", "utcnow"):
            assert clock not in called, (name, clock)


def test_the_importing_modules_still_do_no_eta_arithmetic():
    """The estimate belongs to the job, not to the import that filled its list.

    Checked as *defined names*, not as substrings: the coordinator's prose is
    entitled to say that its live count is "never an estimate" while defining
    nothing that produces one.
    """
    for name in ("importing.py", "import_coordination.py"):
        assert "Calculating" not in (SHARED / name).read_text(encoding="utf-8"), name
        defined = defined_names(plan3_trees_for(name))
        for symbol in defined:
            lowered = symbol.lower()
            for estimator_concept in ("eta", "estimate", "remaining", "duration"):
                assert estimator_concept not in lowered, (name, symbol)


def test_the_estimate_lives_in_exactly_one_place():
    """One estimator, one reliability policy, one place that formats a duration."""
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert text.count("class EtaEstimator") == 1
    assert text.count("def format_duration") == 1
    assert text.count('CALCULATING = "Calculating…"') == 1

    tree = parse(SHARED / "job_control.py")
    formatting = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "format_duration"
            for call in ast.walk(node))
    }
    assert formatting == {"display"}, formatting


def plan3_trees_for(name: str) -> ast.Module:
    return parse(SHARED / name)


# --------------------------------------------------------------------------- #
# Phase 8 — the Tk boundary
# --------------------------------------------------------------------------- #


def test_the_adapter_is_the_only_new_reusable_tk_module():
    """§6.15 puts every adapter in one module, and Phase 8 added exactly that one."""
    assert (SHARED / ADAPTER_MODULE).is_file()
    added = {
        path.name for path in SHARED.glob("*.py")
        if "job_ui" in path.name or "import_ui" in path.name
    }
    assert added == {ADAPTER_MODULE}, added


def test_the_single_intended_ui_test_module_is_the_one_that_exists():
    """§6.15 puts every adapter in one ``shared/job_ui.py``.

    The plan's "likely new tests" list names both ``test_import_ui.py`` and
    ``test_job_ui.py``. One adapter module needs one Tk-boundary test module, so
    ``files/tests/test_job_ui.py`` is the intended name — recorded as a decision in
    Phase 1, honoured in Phase 8, and ``test_import_ui.py`` was never created.
    """
    assert (TESTS / "test_job_ui.py").is_file()
    assert not (TESTS / "test_import_ui.py").exists()


def test_the_tk_free_core_is_still_tk_free_now_that_tk_exists_next_door():
    """The adapter's whole reason for being: three modules that still know no Tk."""
    for name in PLAN3_MODULES:
        tree = parse(SHARED / name)
        for module in imported_names(tree):
            assert "tkinter" not in module.lower(), (name, module)
    adapter = imported_names(parse(SHARED / ADAPTER_MODULE))
    assert "tkinter" in adapter, "the adapter is where Tk is allowed to be"


def test_the_adapter_composes_the_foundation_and_duplicates_none_of_it():
    """It draws the answers. It never becomes a second place that decides them."""
    tree = parse(SHARED / ADAPTER_MODULE)
    modules = imported_names(tree)
    for required in ("shared.importing", "shared.import_coordination",
                     "shared.job_control", "shared.ui_theme"):
        assert any(entry == required or entry.startswith(required + ".")
                   for entry in modules), required

    defined = defined_names(tree)
    for owned_elsewhere in (
        # Phase 3-4: the list and its lifecycle
        "ImportedFileManager", "ImportTransaction", "ImportCoordinator", "ImportPoller",
        "ImportCancellation", "plan_transaction", "validate_direct_files", "scan_roots",
        # Phase 5-7: the run and its reporting
        "JobController", "JobSnapshot", "JobEventStream", "JobReporter", "LoggerBridge",
        "EtaEstimator", "ProgressTracker", "ProgressView", "SummaryView", "RunResult",
        "RetryRequest", "FailureLog", "project_summary", "summary_lines", "detail_lines",
        "format_duration", "is_locked", "is_available", "state_message",
        # Elsewhere entirely
        "ProgressIndicator", "apply_theme", "get_logger", "get_effective",
        "plan_flat", "plan_mirrored", "plan_multi_root", "reserve_run_directory",
        "ConversionCancelled", "raise_if_cancelled",
    ):
        assert owned_elsewhere not in defined, owned_elsewhere


def test_the_adapter_owns_no_state_machine_and_no_second_estimator():
    """No enum of job states, no lock matrix, no duration arithmetic of its own."""
    tree = parse(SHARED / ADAPTER_MODULE)
    text = (SHARED / ADAPTER_MODULE).read_text(encoding="utf-8")

    enums = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Enum" for base in node.bases)
    }
    assert not enums, f"the vocabulary is Phase 1's, not the adapter's: {enums}"

    assert "LOCK_MATRIX = " not in text and "LEGAL_TRANSITIONS = " not in text
    assert 'CALCULATING = "' not in text, "the fallback string has one owner"
    called = called_attributes(tree) | called_bare_names(tree)
    for estimator_verb in ("format_duration", "estimate"):
        assert estimator_verb not in called, estimator_verb
    assert "display" in called, "the ETA text comes from the approved estimator"


def test_the_adapter_reuses_the_shared_progress_indicator():
    """§5.2: reuse it. A second progressbar here would be a second implementation."""
    text = (SHARED / ADAPTER_MODULE).read_text(encoding="utf-8")
    assert "ui_theme.ProgressIndicator(" in text
    tree = parse(SHARED / ADAPTER_MODULE)
    constructed = called_attributes(tree) | called_bare_names(tree)
    assert "Progressbar" not in constructed, "no second bar"
    assert text.count("ui_theme.ProgressIndicator(") == 1, "and only one of the first"


def test_the_adapter_creates_no_thread_and_no_queue_of_its_own():
    """It drains what a worker publishes; it never becomes the worker."""
    tree = parse(SHARED / ADAPTER_MODULE)
    constructed = called_attributes(tree) | called_bare_names(tree)
    for primitive in ("Thread", "Timer", "Queue", "SimpleQueue", "LifoQueue",
                      "PriorityQueue", "Condition", "Event", "Semaphore", "Barrier",
                      "Lock", "RLock", "ThreadPoolExecutor", "ProcessPoolExecutor",
                      "Pool", "Process"):
        assert primitive not in constructed, primitive
    threading_uses = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "threading"
    }
    assert threading_uses == {"get_ident"}, threading_uses
    assert "qsize" not in {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def test_every_tk_reaching_method_asks_the_guard_first():
    """The main-thread rule, checked as a property of the code.

    A public method that mutates or reads a widget must open with
    ``self._guard.require(...)``. Anything that only *reads* adapter state is a
    property and is deliberately not on this list — a property that raised would make
    a repr unprintable from a debugger thread.

    Three methods are named exemptions, each because it provably reaches no Tk object:
    ``MainThreadPump.cancel`` flips a flag on its own token and must survive being
    handed a stale one, ``LockGroup.registered`` reads a dictionary, and
    ``JobControlBar.availability`` is arithmetic over :func:`is_available`. The four
    list/reorder actions delegate to ``_mutate``, whose own first statement is the
    guard, so they are checked through that delegation rather than exempted.
    """
    tree = parse(SHARED / ADAPTER_MODULE)
    exempt = {"MainThreadPump.cancel", "LockGroup.registered",
              "JobControlBar.availability"}
    unguarded = []
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name == "MainThreadGuard":
            continue
        for member in node.body:
            if not isinstance(member, ast.FunctionDef):
                continue
            if member.name.startswith("_"):
                continue
            if any(isinstance(decorator, ast.Name) and decorator.id in
                   ("property", "classmethod", "staticmethod")
                   for decorator in member.decorator_list):
                continue
            body = [
                statement for statement in member.body
                if not (isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str))
            ]
            qualified = f"{node.name}.{member.name}"
            if qualified in exempt:
                continue
            checked += 1
            first = body[0] if body else None
            guarded = (
                isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Attribute)
                and first.value.func.attr == "require")
            delegated = (
                len(body) == 1 and isinstance(first, ast.Return)
                and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Attribute)
                and first.value.func.attr == "_mutate")
            if not (guarded or delegated):
                unguarded.append(qualified)
    assert unguarded == [], unguarded
    assert checked >= 40, f"only {checked} methods were examined"

    # And the helper those four delegate to guards before it touches anything.
    mutate = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_mutate")
    opening = mutate.body[0]
    assert (isinstance(opening, ast.Expr) and isinstance(opening.value, ast.Call)
            and opening.value.func.attr == "require")


def test_the_adapter_neither_creates_nor_inspects_an_output():
    """An output-location event may be displayed. It may not be acted on."""
    tree = parse(SHARED / ADAPTER_MODULE)
    attributes = called_attributes(tree)
    # ``remove`` is the one name on the shared list that a list also answers to — the
    # pump removes a *drain*. The import check below is what actually closes it: with
    # no ``os`` and no ``shutil`` in the module, ``os.remove`` is unreachable.
    for forbidden in tuple(
            verb for verb in _FORBIDDEN_FILESYSTEM_CALLS if verb != "remove"
    ) + ("scandir", "lstat"):
        assert forbidden not in attributes, forbidden
    assert "open" not in called_bare_names(tree)
    modules = imported_names(tree)
    assert "os" not in {entry.split(".")[0] for entry in modules}
    for service in ("shared.output_paths", "shared.settings", "shared.maintenance",
                    "shared.subprocess_utils", "shared.cleanup_worker",
                    "shared.cleanup_state", "shared.release", "shared.config",
                    "shared.logging_setup", "subprocess", "logging", "shutil"):
        assert not any(entry == service or entry.startswith(service + ".")
                       for entry in modules), service


def test_the_adapter_does_not_log_what_the_bridge_already_logged():
    """Phase 7's LoggerBridge owns forwarding; a second call would double every line."""
    tree = parse(SHARED / ADAPTER_MODULE)
    called = called_attributes(tree)
    for level in ("debug", "info", "warning", "error", "exception", "critical",
                  "getLogger", "get_logger", "forward"):
        assert level not in called, level
    text = (SHARED / ADAPTER_MODULE).read_text(encoding="utf-8")
    assert "LoggerBridge" in text, "it accepts one, and hands it to the stream"


@pytest.mark.parametrize("name", ALL_PLAN3_MODULES)
def test_no_module_in_this_drop_grows_a_universal_base_panel(name):
    defined = defined_names(parse(SHARED / name))
    for shape in _FORBIDDEN_EVERYWHERE:
        assert shape not in defined, (name, shape)


def test_phase_eight_delivered_its_own_names_and_no_more():
    from shared import import_coordination, importing, job_control, job_ui

    for delivered in _PHASE_EIGHT_NAMES:
        assert hasattr(job_ui, delivered), delivered
    assert set(job_ui.__all__) >= set(_PHASE_EIGHT_NAMES)

    # Drawing a job is not running one: the Tk-free modules gained none of it.
    for module in (importing, import_coordination, job_control):
        for foreign in ("MainThreadPump", "ImportAdapter", "JobAdapter", "LockGroup",
                        "ImportedFileList", "JobControlBar"):
            assert not hasattr(module, foreign), (module.__name__, foreign)


def test_the_adapter_uses_only_namespaced_or_native_styles():
    """Every style name it can ask for comes from the theme bundle, never a literal."""
    tree = parse(SHARED / ADAPTER_MODULE)
    text = (SHARED / ADAPTER_MODULE).read_text(encoding="utf-8")
    for generic in ('style="TButton"', 'style="TFrame"', 'style="TLabel"',
                    'ttk.Style(', 'style.configure(', 'style.map(', 'style.layout(',
                    'theme_use('):
        assert generic not in text, generic

    styled = {
        keyword.value for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords if keyword.arg == "style"
    }
    for value in styled:
        assert not isinstance(value, ast.Constant), (
            f"a literal style name {value.value!r} bypasses the theme bundle")

    # And the one helper that resolves them is the only reader of the bundle.
    resolvers = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(sub, ast.Constant) and sub.value == "styles"
                for sub in ast.walk(node))
    }
    assert resolvers == {"style_name"}, resolvers


def test_the_theme_and_the_progress_indicator_were_not_changed_for_the_adapter():
    """Reuse, not rearrangement — checked from the other side too."""
    tree = parse(SHARED / "ui_theme.py")
    defined = defined_names(tree)
    for name in ("ProgressIndicator", "apply_theme", "style_tk_widget",
                 "enable_mousewheel"):
        assert name in defined, name
    for plan3 in PLAN3_MODULE_NAMES:
        assert not any(entry.endswith(plan3) for entry in imported_names(tree)), plan3


# --------------------------------------------------------------------------- #
# The developer harness
# --------------------------------------------------------------------------- #


def test_the_manual_harness_lives_in_the_developer_tree_only():
    harness = TESTS / "manual_plan3_harness.py"
    assert harness.is_file()
    assert not any(path.name == harness.name for path in UNIVERSAL.rglob("*.py"))
    assert not harness.name.startswith("test_"), "pytest must not collect it"


def test_the_manual_harness_is_registered_nowhere():
    """No launcher entry, no seventh tool, and no production import."""
    harness_name = "manual_plan3_harness"
    for path in UNIVERSAL.rglob("*.py"):
        assert harness_name not in path.read_text(encoding="utf-8"), path
    launcher = (UNIVERSAL / "launcher.py").read_text(encoding="utf-8")
    assert "job_ui" not in launcher and harness_name not in launcher


# --------------------------------------------------------------------------- #
# Repository invariants
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ALL_PLAN3_MODULES)
def test_the_foundation_added_no_runtime_dependency(name):
    """Standard library and this project's own shared modules. Nothing else.

    A structural version of the pinned-requirements check: a third-party import here
    would ship in ``scripts/`` and would have to be installed on a fresh machine, and
    the drop is not authorized to add one.
    """
    import sys

    for module in imported_names(parse(SHARED / name)):
        head = module.split(".")[0]
        if not head or head == "shared" or head == "__future__":
            continue
        assert head in sys.stdlib_module_names, (name, module)


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
    for name in ALL_PLAN3_MODULES:
        assert (SHARED / name).is_file()
    for name in ("test_importing.py", "test_job_control.py", "test_plan3_boundaries.py",
                 "test_import_traversal.py", "test_import_manager.py",
                 "test_import_coordination.py", "test_job_controller.py",
                 "test_job_run_results.py", "test_job_events_eta.py",
                 "test_job_ui.py", "manual_plan3_harness.py"):
        assert (TESTS / name).is_file()
        assert not (UNIVERSAL / name).exists()
