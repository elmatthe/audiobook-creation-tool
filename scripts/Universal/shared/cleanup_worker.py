"""The post-exit cleanup coordinator — the only code that deletes an asset.

Started as a *separate process* by ``shared.cleanup_state.start_cleanup`` using
a Python interpreter outside the project folder, because the first thing it may
be asked to remove is the virtual environment the application itself is running
from. It is standard-library only through its entire path (plus
``shared.maintenance`` and ``shared.cleanup_state``, which are themselves
standard-library only), so it keeps working while ``.venv`` is being deleted.

What it will not do, by construction:

* it does not read a path, a root, a command or a filename out of the request —
  every one of those comes from its own ``__file__`` and the compiled catalog;
* it does not trust the inventory the user saw. Every target is re-derived from
  its enumerated asset id and re-checked for containment, protection, type and
  links *immediately* before anything is removed;
* it does not follow a directory link. A link that turns up inside a target is
  removed as a link; whatever it points at is never walked and never touched;
* it does not run twice. The request is moved aside before the first deletion,
  so a replay finds nothing to execute;
* it does not retry, relaunch or loop. One attempt, one result, then exit.

Sequence: load the request named on the command line, validate it, verify the
repository root and the state folder, open a handle to the requesting process,
acknowledge, wait for that process to exit, consume the request, delete only
what was selected, write one result atomically, exit.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run as a script by an interpreter that knows nothing about this project: put
# the application's import root (``scripts/Universal``) on the path first, the
# same root the launcher uses. Derived from this file's own location, never from
# the current working directory.
_THIS = Path(__file__).resolve()
IMPORT_ROOT = _THIS.parent.parent
if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))

from shared import cleanup_state, maintenance  # noqa: E402

#: How many individual problems a per-asset message quotes before summarising.
MAX_REPORTED_PROBLEMS = 3


class CoordinatorRefusal(Exception):
    """The run stops before anything is deleted, and says why."""


# --------------------------------------------------------------------------- #
# Trusted location
# --------------------------------------------------------------------------- #


def repository_root() -> Path:
    """The project folder this file lives in, proven by finding itself again.

    ``<root>/scripts/Universal/shared/cleanup_worker.py``. The current working
    directory is never consulted, and no value from the request participates.
    """
    root = _THIS.parent.parent.parent.parent
    marker = root / "scripts" / "Universal" / "shared" / _THIS.name
    if not marker.is_file():
        raise CoordinatorRefusal(
            "the cleanup helper could not confirm which project folder it belongs to"
        )
    if not maintenance.same_path(marker, _THIS):
        raise CoordinatorRefusal("the cleanup helper resolved to a different file")
    return root


# --------------------------------------------------------------------------- #
# Logging — into the state folder, which is never a cleanup target
# --------------------------------------------------------------------------- #


class CoordinatorLog:
    """Append-only technical log. Never inside anything that may be removed."""

    def __init__(self, repo_root=None) -> None:
        self._stream = None
        if repo_root is None:
            return
        try:
            directory = cleanup_state.ensure_state_dir(repo_root)
            self._stream = open(directory / cleanup_state.COORDINATOR_LOG_NAME,
                                "a", encoding="utf-8")
        except (OSError, cleanup_state.StateError):
            self._stream = None
        self.line(f"===== cleanup helper {datetime.now():%Y-%m-%d %H:%M:%S} "
                  f"(pid {os.getpid()}) =====")

    def line(self, message: str) -> None:
        if self._stream is None:
            return
        try:
            self._stream.write(message + "\n")
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.close()
        except (OSError, ValueError):
            pass
        self._stream = None


# --------------------------------------------------------------------------- #
# Deletion primitives — link-safe, and only ever handed an authorized target
# --------------------------------------------------------------------------- #


def _relative_name(base: Path, path: Path) -> str:
    """A short, root-free label for a message the user may read."""
    try:
        return Path(path).relative_to(base).as_posix()
    except ValueError:
        return Path(path).name


def _force_writable(path: Path) -> bool:
    """Clear a read-only bit so a file that is only *marked* undeletable goes."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        return True
    except OSError:
        return False


def _remove_file(path: Path) -> None:
    """Remove one regular file, retrying once past a read-only attribute."""
    try:
        os.unlink(path)
    except PermissionError:
        if not _force_writable(path):
            raise
        os.unlink(path)


def _remove_link(path: Path) -> None:
    """Remove a link itself. Its destination is neither walked nor removed.

    ``unlink`` covers POSIX symlinks (including the ones a venv puts in
    ``bin/``); a Windows junction or directory symlink refuses ``unlink`` and is
    removed with ``rmdir``, which likewise detaches the link without touching
    anything behind it.
    """
    try:
        os.unlink(path)
    except (PermissionError, IsADirectoryError, OSError):
        os.rmdir(path)


def remove_directory_contents(target: Path) -> tuple[int, list[str]]:
    """Empty *target*, leaving *target* itself in place. Returns bytes and problems.

    Post-order and iterative, using ``scandir``/``lstat`` with
    ``follow_symlinks=False`` throughout, so no link is ever descended into and
    no error stops the pass — every failure is collected and the rest of the
    tree still goes.
    """
    freed = 0
    problems: list[str] = []
    stack: list[tuple[Path, bool]] = [(target, False)]

    while stack:
        current, children_done = stack.pop()
        if children_done:
            if not maintenance.same_path(current, target):
                try:
                    os.rmdir(current)
                except OSError as exc:
                    problems.append(f"{_relative_name(target, current)}: "
                                    f"{exc.strerror or exc}")
            continue

        try:
            entries = list(os.scandir(current))
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append(f"{_relative_name(target, current)}: {exc.strerror or exc}")
            continue

        stack.append((current, True))
        for entry in entries:
            path = Path(entry.path)
            try:
                linked = entry.is_symlink() or maintenance.is_link(path)
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                problems.append(f"{_relative_name(target, path)}: {exc.strerror or exc}")
                continue

            if linked:
                try:
                    _remove_link(path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    problems.append(f"{_relative_name(target, path)}: "
                                    f"{exc.strerror or exc}")
                continue

            if stat.S_ISDIR(info.st_mode):
                stack.append((path, False))
                continue

            size = int(info.st_size) if stat.S_ISREG(info.st_mode) else 0
            try:
                _remove_file(path)
                freed += size
            except FileNotFoundError:
                continue
            except OSError as exc:
                problems.append(f"{_relative_name(target, path)}: {exc.strerror or exc}")
    return freed, problems


def remove_directory_tree(target: Path) -> tuple[int, list[str]]:
    """Empty *target* and then remove *target* itself."""
    freed, problems = remove_directory_contents(target)
    if not problems:
        try:
            os.rmdir(target)
        except OSError as exc:
            problems.append(f"{target.name}: {exc.strerror or exc}")
    return freed, problems


# --------------------------------------------------------------------------- #
# One asset
# --------------------------------------------------------------------------- #


def _problem_message(problems: list[str]) -> str:
    shown = problems[:MAX_REPORTED_PROBLEMS]
    text = "; ".join(shown)
    remaining = len(problems) - len(shown)
    if remaining > 0:
        text += f"; and {remaining} more"
    return text


def process_asset(asset_id: str, repo_root, log=None) -> maintenance.AssetOutcome:
    """Re-authorize, then remove exactly what this id is allowed to name.

    The inventory the user saw is not authorization: everything is proven again
    here, a moment before acting, so a target that was swapped for a link (or
    made to reach a protected location) in between is refused rather than
    removed.
    """
    definition = maintenance.asset(asset_id)

    def note(message: str) -> None:
        if log is not None:
            log.line(f"  {asset_id}: {message}")

    try:
        target = maintenance.authorized_target(asset_id, repo_root)
        maintenance.assert_authorized(asset_id, repo_root, target)
    except maintenance.MaintenanceError as exc:
        note(f"refused — {exc}")
        return maintenance.AssetOutcome(asset_id, "refused", 0, str(exc))

    if not os.path.lexists(target):
        note("nothing there")
        return maintenance.AssetOutcome(asset_id, "missing", 0, "")

    try:
        info = os.lstat(target)
    except OSError as exc:
        note(f"could not be inspected — {exc}")
        return maintenance.AssetOutcome(asset_id, "failed", 0,
                                        f"{exc.strerror or exc}")
    if not stat.S_ISDIR(info.st_mode):
        note("refused — not a folder")
        return maintenance.AssetOutcome(asset_id, "refused", 0,
                                        maintenance.NOT_A_FOLDER_PROBLEM)

    if definition.removes_target_itself:
        freed, problems = remove_directory_tree(Path(target))
    else:
        freed, problems = remove_directory_contents(Path(target))

    if problems:
        note(f"partly removed ({freed} bytes) — {_problem_message(problems)}")
        return maintenance.AssetOutcome(asset_id, "failed", freed,
                                        _problem_message(problems))
    note(f"removed ({freed} bytes)")
    return maintenance.AssetOutcome(asset_id, "removed", freed, "")


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def load_and_validate(repo_root, request_id: str, log=None):
    """The stored request, proven to be the one this process was started for."""
    request = cleanup_state.load_request(repo_root)
    if request is None:
        raise CoordinatorRefusal("there is no valid cleanup request to run")
    if request_id and request.request_id != request_id:
        raise CoordinatorRefusal("the stored request is not the one this helper was given")
    if cleanup_state.request_is_stale(request):
        raise CoordinatorRefusal("the cleanup request is too old to run")
    if request.process_id == os.getpid():
        raise CoordinatorRefusal("the cleanup request names this helper as its requester")
    return request


def run(repo_root, request_id: str, log=None, *,
        exit_timeout: float = cleanup_state.EXIT_TIMEOUT_SECONDS,
        wait=None, clock=None):
    """Accept, wait, delete once, and record. Returns the result, or ``None``.

    ``None`` means nothing was deleted: either the run was refused before the
    handshake, or the request was withdrawn while the requester was still alive.
    """
    now = clock or (lambda: datetime.now(timezone.utc))
    root = maintenance.absolute(repo_root)
    cleanup_state.state_dir(root)          # validates the state folder location
    request = load_and_validate(root, request_id, log)

    # Bound to the exact process instance *before* acknowledging, so a recycled
    # process id can never satisfy the wait on Windows.
    handle = cleanup_state.open_process_handle(request.process_id)
    try:
        cleanup_state.write_acceptance(root, request)
        if log is not None:
            log.line(f"accepted request {request.request_id} "
                     f"for {', '.join(request.asset_ids)}")

        waiter = wait if wait is not None else cleanup_state.wait_for_process_exit
        exited = waiter(request.process_id, handle=handle, timeout=exit_timeout)
    finally:
        cleanup_state.close_process_handle(handle)

    started_at = now()
    if not exited:
        if log is not None:
            log.line("the application did not close in time; nothing was removed")
        cleanup_state.consume_request(root, request)
        result = maintenance.CleanupResult(
            schema_version=maintenance.SCHEMA_VERSION,
            request_id=request.request_id,
            started_at=started_at,
            completed_at=now(),
            outcomes=tuple(
                maintenance.AssetOutcome(
                    asset_id, "refused", 0,
                    "Audiobook Creation Tool was still running, so nothing was removed.",
                )
                for asset_id in request.asset_ids
            ),
        )
        cleanup_state.store_result(result, root)
        return result

    # Consume before the first deletion: a crash mid-pass can never replay.
    if not cleanup_state.consume_request(root, request):
        if log is not None:
            log.line("the request was withdrawn before cleanup started; nothing was removed")
        return None

    outcomes = tuple(process_asset(asset_id, root, log) for asset_id in request.asset_ids)
    result = maintenance.CleanupResult(
        schema_version=maintenance.SCHEMA_VERSION,
        request_id=request.request_id,
        started_at=started_at,
        completed_at=now(),
        outcomes=outcomes,
    )
    cleanup_state.store_result(result, root)
    if log is not None:
        log.line("result recorded; exiting without retrying")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Audiobook Creation Tool post-exit cleanup helper",
    )
    parser.add_argument("--run", action="store_true", required=True,
                        help="Execute the stored cleanup request, then exit.")
    parser.add_argument("--request-id", default="",
                        help="The identifier of the request this helper was started for.")
    args = parser.parse_args(argv)

    log = None
    try:
        root = repository_root()
        log = CoordinatorLog(root)
        run(root, args.request_id, log)
        return 0
    except CoordinatorRefusal as exc:
        if log is not None:
            log.line(f"refused: {exc}")
        return 1
    except Exception as exc:                       # never a traceback into the void
        if log is not None:
            log.line(f"stopped: {type(exc).__name__}: {exc}")
        return 2
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
