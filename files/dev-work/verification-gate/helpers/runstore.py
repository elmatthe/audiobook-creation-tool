"""One run's evidence: reserving its directory, writing it atomically, and reading it back without trusting appearances.

Each invocation owns exactly one new child of ``outputs/`` and never touches another's. Nothing here deletes a run. A run
reads PASS only through ``read_run_status``, which checks its schema, its identity against its own directory, every
artifact it lists and the consistency of the claim itself. The seal is tamper evidence for a copied or hand-edited run,
not a defence against someone who recomputes it; ``compare_identity`` is what stops an old run standing in for the current
source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
RESULTS_NAME = "results.json"
START_NAME = "start.json"
MARKER_NAME = "INCOMPLETE.json"
LOG_NAME = "logs/verify.log"
SUMMARY_NAME = "summary.md"
RESULTS = ("PASS", "FAIL", "BLOCKED", "NOT RUN", "NOT APPLICABLE")
LIFECYCLE = ("created", "preflight", "collecting", "running", "finalizing", "completed", "interrupted")
EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_NOT_RUN, EXIT_INVALID, EXIT_INTERRUPTED = 0, 1, 2, 3, 64, 130
EXIT_FOR_STATUS = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED, "NOT RUN": EXIT_NOT_RUN}
RESERVE_ATTEMPTS = 16
_SETTLE_DELAYS = (0.02, 0.05, 0.1, 0.25, 0.5)

# Portable, no spaces, no trailing dot (Windows silently drops it, which would alias an existing name).
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?<!\.)$")
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
# Digests whose change means the recorded execution no longer describes this source. "docs" is the one class that can
# change while the execution evidence still applies (plan §13.3), and only if none of these moved.
EXECUTION_DIGESTS = ("source_digest", "test_digest", "policy_digest", "locks_digest", "other_digest")
# What "the same environment" means to a later reader (plan §13.3): properties of the installation. The error mode and the
# desktop are recorded too, but they describe whichever session is reading, so comparing them could only cry wolf.
COMPARED_ENVIRONMENT = ("os_build", "machine", "python", "executable", "prefix", "base_prefix", "sys_platform", "tk",
                        "pytest", "ffmpeg_sha256")


class RunRefused(ValueError):
    """The run directory would be unsafe: a link in its path, an invalid label, or no free name."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def validate_label(label: str) -> str:
    if not label or not _COMPONENT.match(label) or _WINDOWS_RESERVED.match(label) or len(label) > 80:
        raise RunRefused(f"label {label!r} is not allowed (letters, digits, '.', '_', '-'; no leading or trailing "
                         "punctuation, no reserved device name, at most 80 characters)")
    return label


def is_link(path: Path) -> bool:
    """A symlink or any other reparse point, junctions included. A missing path is not a link."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def refuse_links(path: Path, base: Path) -> None:
    """``path`` must be lexically inside ``base`` and pass through no link on the way down from it."""
    target, root = Path(os.path.abspath(path)), Path(os.path.abspath(base))
    try:
        relative = Path(os.path.normcase(target)).relative_to(Path(os.path.normcase(root)))
    except ValueError:
        raise RunRefused(f"{target} is not inside {root}") from None
    probe = root
    for part in target.parts[len(root.parts):len(root.parts) + len(relative.parts)]:
        probe = probe / part
        if is_link(probe):
            raise RunRefused(f"{probe} is a link or junction; a run directory never passes through one")


def reserve_run_dir(outputs_root: Path, base: Path, mode: str) -> Path:
    """Atomically take a new ``<timestamp>_<mode>_<random>`` child of ``outputs_root``, recreating the root if absent.

    The mkdir has no ``exist_ok``, so a collision means another run owns that name and a fresh random is drawn: nothing
    that exists is reused. A timestamp alone is not collision-safe, and the random part is not the only guard.
    """
    root = Path(os.path.abspath(outputs_root))
    try:
        refuse_links(root, base)
        root.mkdir(parents=True, exist_ok=True)
        refuse_links(root, base)
    except OSError as exc:
        raise RunRefused(f"cannot create {root}: {exc}") from None
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    for _ in range(RESERVE_ATTEMPTS):
        target = root / f"{stamp}_{mode}_{secrets.token_hex(2)}"
        try:
            target.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise RunRefused(f"cannot create {target}: {exc}") from None
        if os.path.normcase(str(target.resolve())) != os.path.normcase(str(target)):
            target.rmdir()
            raise RunRefused(f"{target} resolved through a link or junction after creation")
        return target
    raise RunRefused(f"no free run name below {root} after {RESERVE_ATTEMPTS} attempts")


def reserve_scratch_dir(scratch_root: Path, base: Path) -> Path:
    """A new short-named child of ``scratch_root``. The same rule as a run directory: nothing that exists is reused."""
    root = Path(os.path.abspath(scratch_root))
    try:
        refuse_links(root, base)
        root.mkdir(parents=True, exist_ok=True)
        refuse_links(root, base)
    except OSError as exc:
        raise RunRefused(f"cannot create {root}: {exc}") from None
    for _ in range(RESERVE_ATTEMPTS):
        target = root / secrets.token_hex(2)
        try:
            target.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise RunRefused(f"cannot create {target}: {exc}") from None
        return target
    raise RunRefused(f"no free scratch name below {root} after {RESERVE_ATTEMPTS} attempts")


def settled(operation, *args):
    """Run a filesystem call that something outside this process may hold up for a moment.

    On Windows a watcher, indexer or scanner can hold a file or folder just created under the repository for about a
    millisecond, and the call then fails with Access Denied. That must not end a run that has otherwise finished, so this
    tries again for about a second. A real refusal still raises. Only the gate's own records use this: it never wraps code
    under test, whose handling of the same failure is exactly what those tests are for.
    """
    for delay in _SETTLE_DELAYS:
        try:
            return operation(*args)
        except PermissionError:
            time.sleep(delay)
    return operation(*args)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write to a fresh temporary file, fsync, then rename into place: a reader sees the old file or the whole new one."""
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    settled(os.replace, temporary, path)


def seal_of(results: dict) -> str:
    body = {key: value for key, value in results.items() if key != "seal"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunRecord:
    """The files of one run directory. The log is flushed line by line; a killed run leaves its marker behind."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.run_id = directory.name
        self.nonce = secrets.token_hex(16)
        (directory / "logs").mkdir()
        self._log = open(directory / LOG_NAME, "x", encoding="utf-8", newline="\n")

    def log(self, message: str) -> None:
        if self._log.closed:  # finalizing failed after the log was finished; the marker still says so
            return
        for line in message.splitlines() or [""]:
            self._log.write(f"{now_utc()} {line}\n")
        self._log.flush()

    def close(self) -> None:
        self._log.close()

    def write_start(self, data: dict) -> None:
        with open(self.directory / START_NAME, "x", encoding="utf-8", newline="\n") as handle:
            json.dump({"schema_version": SCHEMA_VERSION, "run_id": self.run_id, "nonce": self.nonce, **data}, handle,
                      indent=2, ensure_ascii=False)
            handle.write("\n")

    def mark(self, lifecycle: str, **details) -> None:
        if lifecycle not in LIFECYCLE:
            raise ValueError(f"unknown lifecycle {lifecycle!r}")
        write_json_atomic(self.directory / MARKER_NAME, {"schema_version": SCHEMA_VERSION, "status": "INCOMPLETE",
                                                         "run_id": self.run_id, "lifecycle": lifecycle, **details})

    def finalize(self, results: dict) -> dict:
        """results.json first, then the marker goes: a crash between the two still reads INCOMPLETE."""
        if (self.directory / RESULTS_NAME).exists():
            raise RunRefused(f"{RESULTS_NAME} already exists")
        results = {**results, "artifacts": artifact_manifest(self.directory)}
        results["seal"] = seal_of(results)
        write_json_atomic(self.directory / RESULTS_NAME, results)
        settled((self.directory / MARKER_NAME).unlink)
        return results


def artifact_manifest(directory: Path) -> list[dict]:
    """Every file of the run but the two that describe it, by size and SHA-256. A link is listed, never followed."""
    manifest = []
    stack = [directory]
    skip = {directory / RESULTS_NAME, directory / MARKER_NAME, directory / f".{RESULTS_NAME}.tmp"}
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path)
                relative = path.relative_to(directory).as_posix()
                if is_link(path):
                    manifest.append({"path": relative, "link": True})
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif path not in skip:
                    manifest.append({"path": relative, "size": entry.stat(follow_symlinks=False).st_size,
                                     "sha256": sha256_file(path)})
    return sorted(manifest, key=lambda item: item["path"])


def safe_remove_tree(target: Path, *, within: Path) -> list[str]:
    """Remove a disposable tree the run owns. Never follows a link: a junction in it is removed, not walked into.

    Refused outright unless ``target`` is strictly below ``within`` with no link on the way. Returns what could not be
    removed, for the record; a leftover in the run's own temp is reported rather than chased.
    """
    target, within = Path(os.path.abspath(target)), Path(os.path.abspath(within))
    target_case, within_case = Path(os.path.normcase(target)), Path(os.path.normcase(within))
    if target_case == within_case or not target_case.is_relative_to(within_case):
        raise RunRefused(f"{target} is not strictly below {within}")
    refuse_links(target, within)
    if not os.path.lexists(target):
        return []
    problems: list[str] = []
    _remove_entry(target, problems)
    return problems


def _remove_entry(path: Path, problems: list[str]) -> None:
    try:
        if is_link(path):
            # rmdir on a junction or directory link removes the link alone; unlink handles the file kind.
            try:
                os.rmdir(path)
            except OSError:
                os.unlink(path)
            return
        if path.is_dir():
            with os.scandir(path) as entries:
                children = [Path(entry.path) for entry in entries]
            for child in children:
                _remove_entry(child, problems)
            settled(os.rmdir, path)
            return
        try:
            os.unlink(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.unlink(path)
    except OSError as exc:
        if len(problems) < 50:
            problems.append(f"{path}: {type(exc).__name__}: {exc}")


def compare_environment(recorded: dict | None, current: dict | None) -> list[str]:
    """The compared fields that differ, as ``environment.<field>``. A side with no record at all is never the same."""
    if not recorded or not current:
        return ["environment unavailable"]

    def comparable(value):
        return os.path.normcase(value) if isinstance(value, str) else value  # C:\X and c:\x are one interpreter on Windows

    return [f"environment.{key}" for key in COMPARED_ENVIRONMENT if comparable(recorded.get(key)) != comparable(current.get(key))]


def compare_identity(recorded: dict, current: dict, recorded_environment: dict | None = None,
                     current_environment: dict | None = None) -> tuple[str, list[str]]:
    """``exact``, ``docs-only`` (the execution evidence carries, the docs checks must be rerun) or ``stale``.

    Evidence carries only where the environment matches as well, so a reader that brings no environment gets ``stale``.
    """
    if not recorded or not current:
        return "stale", ["identity unavailable"]
    moved = [key for key in EXECUTION_DIGESTS if not recorded.get(key) or recorded.get(key) != current.get(key)]
    moved += compare_environment(recorded_environment, current_environment)
    if moved:
        return "stale", moved
    if recorded.get("docs_digest") != current.get("docs_digest"):
        return "docs-only", ["docs_digest"]
    return "exact", []


def read_run_status(directory: Path, current_identity: dict | None = None, current_environment: dict | None = None) -> dict:
    """What a run directory may honestly be taken to say, as ``{"status", "valid", "problems", "current", "results"}``.

    ``status`` is one of the recorded results, or INCOMPLETE, or INVALID when the directory does not hold up. Only a
    finalized, self-consistent record with no marker can say PASS. ``current`` compares the run's source identity and
    environment with ``current_identity`` and ``current_environment`` when an identity is given; a PASS that is not current
    must not be taken as acceptance of this source on this installation.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return _status("INVALID", ["not a directory"])
    if (directory / MARKER_NAME).exists() or not (directory / RESULTS_NAME).is_file():
        return _status("INCOMPLETE", ["no finalized result, or the marker is still present"])
    try:
        results = json.loads((directory / RESULTS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _status("INVALID", [f"{RESULTS_NAME} is unreadable: {type(exc).__name__}"])
    if not isinstance(results, dict):
        return _status("INVALID", [f"{RESULTS_NAME} is not an object"])
    problems = _record_problems(directory, results)
    status = results.get("status")
    if problems or status not in RESULTS:
        return _status("INVALID", problems or [f"unknown status {status!r}"], results)
    outcome = _status(status, [], results)
    outcome["valid"] = True
    if current_identity is not None:
        outcome["current"], outcome["identity_differences"] = compare_identity(
            results.get("identity", {}).get("start"), current_identity, results.get("environment"), current_environment)
    return outcome


def _status(status: str, problems: list[str], results: dict | None = None) -> dict:
    return {"status": status, "valid": False, "problems": problems, "current": None, "results": results}


def _record_problems(directory: Path, results: dict) -> list[str]:
    problems: list[str] = []
    if results.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version {results.get('schema_version')!r} is not {SCHEMA_VERSION}")
    if results.get("run_id") != directory.name:
        problems.append(f"run_id {results.get('run_id')!r} is not this directory ({directory.name}): copied or renamed")
    if results.get("lifecycle") != "completed":
        problems.append(f"lifecycle {results.get('lifecycle')!r} is not completed")
    if results.get("seal") != seal_of(results):
        problems.append("the seal does not match: results.json was edited after it was finalized")
    try:
        start = json.loads((directory / START_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        problems.append(f"{START_NAME} is missing or unreadable")
    else:
        if start.get("run_id") != results.get("run_id"):
            problems.append(f"{START_NAME} names another run ({start.get('run_id')!r})")
        if not start.get("nonce") or start.get("nonce") != results.get("nonce"):
            problems.append(f"{START_NAME} and {RESULTS_NAME} are not from the same run (nonce)")
    problems += _artifact_problems(directory, results.get("artifacts"), results)
    if results.get("mode") == "qualification":
        problems += _scenario_problems(directory, results)
    if results.get("status") == "PASS":
        problems += _pass_problems(results)
    return problems


def _artifact_problems(directory: Path, artifacts, results: dict) -> list[str]:
    if not isinstance(artifacts, list) or not artifacts:
        return ["no artifact manifest"]
    problems = []
    listed = set()
    root = Path(os.path.abspath(directory))
    for item in artifacts:
        relative = item.get("path") if isinstance(item, dict) else None
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            problems.append(f"unsafe artifact path {relative!r}")
            continue
        listed.add(relative)
        if item.get("link"):
            problems.append(f"artifact {relative} is a link")
            continue
        path = root / relative
        # A link further up serves the same bytes from somewhere else, so the hashes below would still match.
        if any(is_link(root.joinpath(*Path(relative).parts[:depth])) for depth in range(1, len(Path(relative).parts))):
            problems.append(f"artifact {relative} is below a link")
        elif is_link(path) or not path.is_file():
            problems.append(f"artifact {relative} is missing")
        elif path.stat().st_size != item.get("size") or sha256_file(path) != item.get("sha256"):
            problems.append(f"artifact {relative} changed after the run")
    required = {START_NAME, LOG_NAME, SUMMARY_NAME}
    for stage in results.get("stages", []):
        required.update(value for key, value in stage.items() if key in ("log", "junit", "probe", "report") and value)
    problems += [f"required artifact {name} is not listed" for name in sorted(required - listed)]
    return problems


def _pass_problems(results: dict) -> list[str]:
    problems = []
    if results.get("exit_code") != EXIT_PASS:
        problems.append(f"PASS with exit code {results.get('exit_code')!r}")
    checks = results.get("checks")
    if not checks:
        problems.append("PASS with no checks")
    else:
        bad = [c.get("name") for c in checks if c.get("required", True) and c.get("status") not in ("PASS", "NOT APPLICABLE")]
        if bad:
            problems.append(f"PASS with required checks not passed: {bad}")
    if results.get("identity", {}).get("start_end_match") is not True:
        problems.append("PASS without a matching start and end identity")
    if results.get("cleanup", {}).get("owned_children_remaining") != 0:
        problems.append("PASS without a clean process cleanup")
    counts = results.get("counts") or {}
    if results.get("mode") == "qualification":
        # A qualification collects no test and runs no journey: what it executed is one scenario, and the scenario's own
        # verdict is its evidence. Until v0.7.2 Phase 8 the rule below was applied here as well, so every true
        # qualification PASS read INVALID. What stands in its place is checked by _scenario_problems.
        ran = (results.get("qualification") or {}).get("ran") or {}
        if list(ran.values()) != ["PASS"]:
            problems.append(f"a qualification PASS whose scenarios ended {ran}")
        elif (results.get("qualification") or {}).get("satisfied") != list(ran):
            problems.append(f"a qualification PASS that does not name {list(ran)} as satisfied")
    elif not (counts.get("executed") or counts.get("journeys_passed")):
        problems.append("PASS with no executed tests")
    return problems


#: What a scenario's runner must exit with for its verdict to stand (verify.py, check_scenario).
_SCENARIO_EXIT = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED}
SCENARIO_VERDICT = "qualification/verdict.json"


def _scenario_problems(directory: Path, results: dict) -> list[str]:
    """Whether a qualification run's sealed scenario result follows from the scenario's own verdict and its runner's exit.

    The gate seals PASS for a scenario only when its runner exited 0 having written a PASS verdict; FAIL or BLOCKED when
    the verdict says so; FAIL when a PASS verdict came with any other exit. A reader takes none of that on trust: the
    verdict must be part of the sealed evidence (so its bytes are the ones the run wrote), readable, about this scenario,
    and it and the recorded exit must lead to the sealed result. A PASS must also have run something: checks, every one
    passed, and at least one run. A run whose scenario never reached a verdict has nothing to compare and is left as
    sealed: it can only be FAIL, BLOCKED or NOT RUN, because a PASS needs a scenario that ended PASS.
    """
    ran = (results.get("qualification") or {}).get("ran")
    if not isinstance(ran, dict) or not ran:
        return []
    if len(ran) != 1:
        return [f"a qualification run that recorded {len(ran)} scenarios"]
    (name, sealed), = ran.items()
    problems: list[str] = []
    checks = [c for c in results.get("checks") or [] if isinstance(c, dict) and c.get("name") == f"scenario:{name}"]
    if len(checks) != 1 or checks[0].get("status") != sealed or checks[0].get("required", True) is not True:
        problems.append(f"scenario {name} is recorded as {sealed} but its check says "
                        f"{[c.get('status') for c in checks] or 'nothing'}")
    stages = [s for s in results.get("stages") or [] if isinstance(s, dict) and s.get("name") == f"qualification:{name}"]
    if len(stages) != 1:
        return problems + [f"scenario {name} has {len(stages)} recorded runs of its runner"]
    ended, code = stages[0].get("ended"), stages[0].get("returncode")
    listed = {item.get("path") for item in results.get("artifacts") or [] if isinstance(item, dict)}
    if SCENARIO_VERDICT not in listed:
        return problems + [f"scenario {name}'s verdict is not part of the sealed evidence"]
    try:
        verdict = json.loads((Path(directory) / SCENARIO_VERDICT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return problems + [f"scenario {name}'s verdict is missing or unreadable: {type(exc).__name__}"]
    if not isinstance(verdict, dict) or verdict.get("scenario") != name:
        return problems + [f"{SCENARIO_VERDICT} is not the verdict of scenario {name}"]
    said = verdict.get("status") if verdict.get("status") in _SCENARIO_EXIT else "FAIL"
    follows = said if said != "PASS" or (ended == "exited" and code == EXIT_PASS) else "FAIL"
    if follows != sealed:
        problems.append(f"scenario {name} is sealed {sealed}, but its verdict says {verdict.get('status')!r} and its "
                        f"runner {ended} with exit {code!r}: that makes {follows}")
    if sealed == "PASS":
        judged = verdict.get("checks")
        if not isinstance(judged, list) or not judged:
            problems.append(f"scenario {name} passed with no checks in its verdict")
        else:
            bad = [c.get("name") if isinstance(c, dict) else repr(c) for c in judged
                   if not isinstance(c, dict) or c.get("status") != "PASS"]
            if bad:
                problems.append(f"scenario {name} passed with checks not passed in its verdict: {bad[:8]}")
        runs = verdict.get("runs")
        if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
            problems.append(f"scenario {name} passed having made no run ({runs!r})")
    return problems


def read_legacy_evidence_status(directory: Path) -> str:
    """PASS, FAIL, INCOMPLETE or INVALID for an evidence directory written before the v0.7.2 migration.

    Read-only and for the record: these directories stay where they are, under their old schema, and are historical facts
    about their own source. A legacy PASS is never current acceptance of anything, which is why ``--status`` reports it as
    legacy. Only a finalized ``result.json`` with no marker beside it can say PASS.
    """
    directory = Path(directory)
    if (directory / MARKER_NAME).exists() or not (directory / "result.json").is_file():
        return "INCOMPLETE"
    try:
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "INVALID"
    if not isinstance(result, dict) or result.get("status") != "COMPLETE" or result.get("result") not in ("PASS", "FAIL"):
        return "INVALID"
    return result["result"]
