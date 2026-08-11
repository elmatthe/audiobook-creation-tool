#!/usr/bin/env python3
"""Developer-only harness for the Plan 3 importing and job-control foundation.

**This is not part of the product and not part of the test suite.**

- pytest never collects it: the filename is not ``test_*`` and it declares no test
  functions.
- The launcher cannot reach it: it is not registered in ``launcher.TOOLS``, it lives
  under ``files/`` (the developer tree) rather than ``scripts/`` (the shipped tree),
  the release packager builds its archives from an explicit ``scripts/`` scope, and
  nothing in the product imports it.
- It adds no behaviour. Every widget below is a *production* adapter from
  ``shared/job_ui.py``, driven by the *production* manager, coordinator, controller,
  reporter, event stream and estimator. Nothing is patched, stubbed or bypassed.

Why it exists
-------------
Phase 9's Windows manual matrix has to exercise things a unit test cannot photograph:
a real file dialog, a real NTFS junction being refused, a scan of more than a thousand
generated files, a pause that a human watches arrive, and a window closed while a
worker is still running. Building that by hand during Phase 9 would mean writing code
in a verification phase. This is that code, written in Phase 8 and disposable.

What it will not do
-------------------
It creates one **disposable fixture root**, refuses to run against anything else, and
scans nothing but that root. It runs no conversion, no ffmpeg, no TTS engine, no model
download, no network call and no subprocess. It reserves, creates, inspects and
validates no output. It writes no setting, touches no runtime data, and never modifies
a file it imported. The "work" a job does here is a timed no-op whose only purpose is
to be slow enough for a person to press Pause during.

The one deliberate sleep
------------------------
:func:`_FakeWork.run` sleeps between simulated units. This is a manual harness, not a
test: a job that finishes in a microsecond cannot have Pause pressed during it. The
automated suites contain no sleep at all.

Usage, from the repository root with the repository virtual environment::

    .venv\\Scripts\\python.exe files/tests/manual_plan3_harness.py
    .venv\\Scripts\\python.exe files/tests/manual_plan3_harness.py --large 1200
    .venv\\Scripts\\python.exe files/tests/manual_plan3_harness.py --step 0.4
    .venv\\Scripts\\python.exe files/tests/manual_plan3_harness.py --cleanup

``--cleanup`` removes the generated fixture root on exit, and only ever the root this
process created under the system temporary directory. The default is to keep it, so
the before/after source check can be repeated after the window is gone.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from queue import SimpleQueue
from tkinter import ttk

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_ROOT = REPO_ROOT / "scripts" / "Universal"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from shared import job_ui, ui_theme  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from shared.config import get_effective  # noqa: E402
from shared.importing import (  # noqa: E402
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
    is_broad_root,
)
from shared.job_control import (  # noqa: E402
    EtaEstimator,
    FailureLog,
    FailureRecord,
    JobController,
    JobReporter,
    RunResult,
    capture_run,
)

#: The only file types this harness pretends to understand.
CATALOG = SupportedTypeCatalog((
    SupportedType("mp3", "MP3 audio", (".mp3",)),
    SupportedType("m4b", "M4B audiobook", (".m4b", ".m4a")),
    SupportedType("txt", "Text", (".txt",)),
))

#: Every generated file is this small. Nothing here is real audio.
FILLER = b"not audio - Plan 3 manual harness fixture\n"

#: How many simulated units the first stage refuses to be interrupted for. Pressing
#: Pause during it must show "Pause requested." and keep going, which is §6.10's whole
#: point and the hardest thing in the matrix to see any other way.
INDIVISIBLE_UNITS = 4


# --------------------------------------------------------------------------- #
# The disposable fixture root
# --------------------------------------------------------------------------- #


def refuse_unless_disposable(root: Path) -> Path:
    """Fail loudly rather than let this point at anything that matters."""
    resolved = Path(os.path.abspath(root))
    home = Path.home()
    forbidden = {
        home, home / "Downloads", home / "Documents", home / "Desktop",
        REPO_ROOT, Path(REPO_ROOT.anchor),
    }
    if resolved in forbidden:
        raise SystemExit(f"refusing to use {resolved} as a fixture root")
    if is_broad_root(resolved, home=home):
        raise SystemExit(f"refusing to use the broad root {resolved}")
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise SystemExit("refusing to use a path inside the repository")
    return resolved


def build_fixture(root: Path, *, large: int = 0) -> Path:
    """Generate the tree the Phase 9 matrix needs. Only under *root*."""
    root.mkdir(parents=True, exist_ok=True)

    book = root / "Book One"
    _write(book / "01.mp3")
    _write(book / "02.mp3")
    _write(book / "10.mp3")
    _write(book / "cover.jpg")            # unsupported, must be reported not imported
    _write(book / "notes.txt")
    _write(book / "Disc 1" / "01.mp3")
    _write(book / "Disc 1" / "02.mp3")
    _write(book / "Disc 2" / "01.mp3")
    _write(book / ".hidden" / "secret.mp3")   # only with "Include hidden folders"

    # A second root with a repeated child name, so multi-root ordering is visible.
    other = root / "Book Two"
    _write(other / "01.mp3")
    _write(other / "Disc 1" / "01.mp3")

    # A same-named root elsewhere, for the "several roots, same name" case.
    _write(root / "Elsewhere" / "Book One" / "01.mp3")

    _make_junction(root / "Junction To Book One", book)

    if large:
        bulk = root / f"Large {large}"
        bulk.mkdir(parents=True, exist_ok=True)
        for index in range(large):
            _write(bulk / f"{index:05d}.mp3")

    return root


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FILLER)
    return path


def _make_junction(link: Path, target: Path) -> bool:
    """A real NTFS junction inside the fixtures, created without elevation."""
    if sys.platform != "win32":
        try:
            link.symlink_to(target, target_is_directory=True)
            return True
        except OSError:
            return False
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return True
    except (ImportError, OSError):
        return False


def tree_digest(root: Path) -> tuple[int, str]:
    """A stable fingerprint of every path under *root*: name, size, mtime, content."""
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        digest.update(str(path.relative_to(root)).encode("utf-8", "replace"))
        digest.update(f"|{info.st_mode}|{info.st_size}|{info.st_mtime_ns}|".encode())
        count += 1
    return count, digest.hexdigest()


# --------------------------------------------------------------------------- #
# Fake work
# --------------------------------------------------------------------------- #


class _FakeWork:
    """A job that does nothing, slowly, and truthfully.

    It obeys the real controller: it pauses at real checkpoints, it stays in
    ``PAUSE_REQUESTED`` through an indivisible stage, it raises the real cancellation
    exception, and it reports through the real reporter. What it never does is touch a
    file, start a process, or produce an output.
    """

    def __init__(
        self,
        *,
        controller: JobController,
        reporter: JobReporter,
        estimator: EtaEstimator,
        snapshot,
        step: float,
        failing: frozenset[str],
    ) -> None:
        self.controller = controller
        self.reporter = reporter
        self.estimator = estimator
        self.snapshot = snapshot
        self.step = step
        self.failing = failing
        self.result: RunResult | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="harness-job", daemon=True)
        self.thread.start()

    def run(self) -> None:
        items = self.snapshot.item_ids
        records: list[FailureRecord] = []
        completed: list[str] = []
        try:
            self.reporter.stage_changed(
                "Preparing",
                detail=("this stage is indivisible; a pause request is honoured at "
                        "the next checkpoint, not inside it"))
            for _ in range(INDIVISIBLE_UNITS):
                time.sleep(self.step)          # deliberate: see the module docstring
            self.controller.checkpoint()

            self.reporter.stage_changed("Converting")
            total = len(items)
            for position, item_id in enumerate(items, start=1):
                self.controller.checkpoint()
                self.reporter.current_item(item_id)
                self.estimator.begin("convert")
                time.sleep(self.step)
                if item_id in self.failing:
                    self.estimator.discard()
                    records.append(FailureRecord(
                        item_id=item_id,
                        stage="Converting",
                        display_message=f"{item_id} could not be converted.",
                        technical_detail="simulated failure - no process ran",
                        retryable=True,
                        snapshot_id=self.snapshot.snapshot_id,
                    ))
                    self.reporter.failure(
                        f"{item_id} could not be converted.",
                        "simulated failure - no process ran", item_id=item_id,
                        stage="Converting")
                else:
                    self.estimator.complete()
                    completed.append(item_id)
                    self.reporter.technical(
                        f"pretended to convert {item_id} in {self.step:.2f}s")
                self.reporter.progress(position, total, item_id=item_id)
        except ConversionCancelled:
            self.controller.finish_cancelled()
            self.result = RunResult.settle(
                self.snapshot, FailureLog(snapshot_id=self.snapshot.snapshot_id,
                                          records=tuple(records)),
                completed_ids=tuple(completed), cancelled=True)
            self.reporter.cancelled(
                self.controller.snapshot(),
                f"Cancelled after {len(completed)} of {len(items)} items.")
            return

        failures = FailureLog(snapshot_id=self.snapshot.snapshot_id,
                              records=tuple(records))
        self.result = RunResult.settle(
            self.snapshot, failures, completed_ids=tuple(completed))
        if records:
            self.controller.complete_with_failures()
        else:
            self.controller.succeed()
        self.reporter.completed(
            self.controller.snapshot(),
            f"{len(completed)} of {len(items)} items finished.")


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #


class Harness:
    """One window holding the real adapters, wired to the real foundation."""

    def __init__(self, root: tk.Tk, fixture: Path, *, step: float) -> None:
        self.root = root
        self.fixture = fixture
        self.step = step
        self.baseline: tuple[int, str] | None = None
        self.work: _FakeWork | None = None
        self.controller: JobController | None = None
        self.runs = 0

        self.theme = ui_theme.apply_theme(root, ttk.Style(root))
        root.title("Plan 3 manual harness — developer only")
        root.geometry(self.theme.get("geometry", "1024x720"))
        root.minsize(*self.theme.get("min_size", (920, 600)))

        shell = ttk.Frame(root, style=job_ui.style_name(self.theme, "window"))
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        shell.rowconfigure(3, weight=1)

        banner = ttk.Label(
            shell, style=job_ui.style_name(self.theme, "warning_label"),
            text=("DEVELOPER HARNESS — not a tool, not shipped. Fixture root:\n"
                  f"{fixture}"))
        banner.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.pump = job_ui.MainThreadPump(root)
        self.manager = ImportedFileManager()
        self.importer = job_ui.ImportAdapter(
            shell,
            catalog=CATALOG,
            effective_config=get_effective(),
            pump=self.pump,
            manager=self.manager,
            theme=self.theme,
            clock=time.monotonic,
            choose_files=self._choose_files,
            choose_folder=self._choose_folder,
            confirm_broad_root=self._confirm_broad_root,
            confirm_large_result=self._confirm_large_result,
        )
        self.importer.frame.grid(row=1, column=0, sticky="nsew")

        tools = ttk.Frame(shell, style=job_ui.style_name(self.theme, "card"))
        tools.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.button_start = ttk.Button(
            tools, text="Start fake job", command=self.start_job,
            style=job_ui.style_name(self.theme, "primary_button"))
        self.button_start.grid(row=0, column=0)
        ttk.Button(tools, text="Record source tree", command=self.record_tree,
                   style=job_ui.style_name(self.theme, "button")
                   ).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(tools, text="Compare source tree", command=self.compare_tree,
                   style=job_ui.style_name(self.theme, "button")
                   ).grid(row=0, column=2, padx=(6, 0))
        self.var_tree = tk.StringVar(master=tools, value="No source snapshot recorded.")
        ttk.Label(tools, textvariable=self.var_tree,
                  style=job_ui.style_name(self.theme, "secondary_label")
                  ).grid(row=0, column=3, padx=(12, 0))

        self.job_host = ttk.Frame(shell, style=job_ui.style_name(self.theme, "surface"))
        self.job_host.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.job_host.rowconfigure(0, weight=1)
        self.job_host.columnconfigure(0, weight=1)
        self.job: job_ui.JobAdapter | None = None
        self._build_job_adapter()

        self.pump.start()
        root.protocol("WM_DELETE_WINDOW", self.close)

    # -- dialogs, all on the main thread ----------------------------------- #

    def _choose_files(self) -> tuple[str, ...]:
        return job_ui.ask_files(
            self.root, "Add files (fixture root only)",
            (("Supported", "*.mp3 *.m4b *.m4a *.txt"), ("All files", "*.*")))

    def _choose_folder(self) -> tuple[str, ...]:
        return job_ui.ask_folder(self.root, "Add folder (fixture root only)")

    def _confirm_broad_root(self, roots) -> bool:
        listed = "\n".join(str(entry) for entry in roots)
        return job_ui.ask_confirm(
            self.root, "Scan a very broad folder?",
            f"This covers a whole drive or your home folder:\n\n{listed}\n\n"
            "Scan it anyway?")

    def _confirm_large_result(self, outcome) -> bool:
        return job_ui.ask_confirm(
            self.root, "Add a large number of files?",
            f"{outcome.proposed_count:,} files are ready to be added.\n\nAdd them?")

    # -- the fake job ------------------------------------------------------ #

    def _build_job_adapter(self, **kwargs) -> None:
        if self.job is not None:
            self.job.close()
            self.job.frame.destroy()
        kwargs.setdefault("run_id", f"harness-idle-{self.runs}")
        self.job = job_ui.JobAdapter(
            self.job_host, pump=self.pump, theme=self.theme,
            on_pause=self._pause, on_resume=self._resume, on_cancel=self._cancel,
            on_retry=self._retry, on_terminal=self._settled, **kwargs)
        self.job.frame.grid(row=0, column=0, sticky="nsew")
        self.job.register_inputs(self.importer.list)
        self.job.register_options(self.importer.options)

    def start_job(self) -> None:
        if self.manager.count == 0:
            self.importer.status.set_message("Import something before starting a job.")
            return
        if self.controller is not None and not self.controller.is_terminal:
            return

        self.runs += 1
        run_id = f"harness-run-{self.runs}"
        snapshot = capture_run(
            snapshot_id=run_id,
            files=self.manager.snapshot(),
            catalog=CATALOG,
            import_options=self.importer.options.options(),
            effective_config=get_effective(),
            tool_options={"pretend": True},
            created_at=time.monotonic(),
        )
        events: SimpleQueue = SimpleQueue()
        reporter = JobReporter.for_run(snapshot, clock=time.monotonic,
                                       publish=events.put)
        # The listener is what makes an acknowledged pause visible: the worker is
        # parked inside the controller, so the transition is reported by whoever
        # caused it rather than by a thread that is not running.
        self.controller = JobController(run_id, listener=reporter.state_changed)
        estimator = EtaEstimator(run_id, clock=time.monotonic)
        self._build_job_adapter(
            run_id=run_id, pull=job_ui.queue_pull(events), estimator=estimator,
            item_ids=snapshot.item_ids)

        # Every third item fails, so failure collection and Retry Failed are reachable.
        failing = frozenset(snapshot.item_ids[2::3])
        self.work = _FakeWork(
            controller=self.controller, reporter=reporter, estimator=estimator,
            snapshot=snapshot, step=self.step, failing=failing)
        self.controller.start()
        self.work.start()
        self.button_start.configure(state="disabled")

    def _pause(self) -> None:
        if self.controller is not None:
            self.controller.request_pause()

    def _resume(self) -> None:
        if self.controller is not None:
            self.controller.resume()

    def _cancel(self) -> None:
        if self.controller is not None:
            self.controller.request_cancel()

    def _retry(self) -> None:
        """Build the retry *request* and say what it holds. It reruns nothing."""
        job = self.job
        if job is None or job.result is None:
            return
        request = job.result.retry()
        job.status.set_status(
            f"Retry Failed would resubmit {request.count} item(s) against snapshot "
            f"{request.snapshot_id} — this harness reruns nothing.")

    def _settled(self, _entry) -> None:
        work = self.work
        if work is not None and work.result is not None and self.job is not None:
            self.job.set_result(work.result)
        self.button_start.configure(state="normal")

    # -- source-tree evidence ---------------------------------------------- #

    def record_tree(self) -> None:
        self.baseline = tree_digest(self.fixture)
        self.var_tree.set(f"Recorded {self.baseline[0]} paths.")

    def compare_tree(self) -> None:
        if self.baseline is None:
            self.var_tree.set("Record the source tree first.")
            return
        current = tree_digest(self.fixture)
        if current == self.baseline:
            self.var_tree.set(f"UNCHANGED — {current[0]} paths, identical digest.")
        else:
            self.var_tree.set(
                f"CHANGED — was {self.baseline[0]} paths, now {current[0]}.")

    # -- teardown ---------------------------------------------------------- #

    def close(self) -> None:
        """Close while anything is still running, and leave nothing behind."""
        if self.controller is not None and not self.controller.is_terminal:
            self.controller.request_cancel()
        if self.job is not None:
            self.job.close()
        self.importer.close()
        self.pump.close()
        self.root.destroy()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=None,
                        help="fixture root to generate into (default: a new temp dir)")
    parser.add_argument("--large", type=int, default=0,
                        help="also generate this many files in one folder")
    parser.add_argument("--step", type=float, default=0.35,
                        help="seconds of pretend work per simulated unit")
    parser.add_argument("--cleanup", action="store_true",
                        help="delete the generated fixture root on exit")
    args = parser.parse_args(argv)

    created_here = args.root is None
    root_path = Path(tempfile.mkdtemp(prefix="act-plan3-harness-")) \
        if created_here else Path(args.root)
    fixture = refuse_unless_disposable(root_path)
    build_fixture(fixture, large=max(0, args.large))
    print(f"fixture root: {fixture}")
    print(f"paths generated: {tree_digest(fixture)[0]}")

    window = tk.Tk()
    Harness(window, fixture, step=max(0.0, args.step))
    window.mainloop()

    if args.cleanup and created_here:
        import shutil

        shutil.rmtree(fixture, ignore_errors=True)
        print(f"removed {fixture}")
    else:
        print(f"fixture kept at {fixture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
