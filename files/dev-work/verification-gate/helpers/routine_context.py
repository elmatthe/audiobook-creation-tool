"""The routine verification contract's one authoritative home (v0.8.2 Phase 1A-1, corrected in R1).

Every process a routine pytest run starts inherits ``ACT_VERIFY_CONTEXT=routine`` (``files/tests/routine_effects.py`` sets
it, with the checkout it marks, the session's effect ledger and the session's owned disposable root). A child Python does not
inherit the parent's audit hook, so the maintained heavyweight roots -- the gate, the acceptance runner, the qualification
scenarios (through ``qualification/common.start``), the scaling programs, the gate's native adapters and the real test
drivers -- check the marker themselves, and refuse. Since R1 the refusal does not depend on where the root lies: a root in
another checkout, a copy in a disposable tree or a renamed copy refuses exactly as the original does. Location is never
evidence that an execution is synthetic.

The one exception is a **reviewed synthetic gate fixture** (:func:`synthetic_fixture`): a disposable tree that a test built
inside its own session's owned disposable root and declared in ``act-synthetic-fixture.json`` at the tree's root. The
declaration names the tree and the exact bytes (SHA-256) of each synthetic stand-in the tree's gate may start in place of a
real runner. Inside such a tree the gate's own orchestration may run (its pytest stages run inside the routine envelope
themselves), and its acceptance and qualification launches start only a declared stand-in whose bytes differ from the real
runner of the marked checkout. A real runner -- copied, renamed or foreign -- is never a stand-in, and the declaration grants
nothing outside its own tree, outside the session's disposable root, or without the routine session that owns that root.

This module also holds what both sides share: the marker names, the launch roots (:data:`LAUNCH_ROOTS`), the data-only
argument shapes (:func:`data_only_shape`), the operation check for imported callables (:func:`check_operation`) and the
effect ledger (one directory per stage or session, one file per cooperating process, a header written by its owner before
anything runs, and :func:`read_ledger`, which never treats a missing, empty, incomplete or malformed ledger as clean).

The marker only restricts. Its absence grants nothing beyond today's interim policy (owner authorization for every
heavyweight run, GATE.md); Phase 1A-2 replaces that with an admission delegated from a live coordinator. Standard library
only; a root without ``helpers`` on its import path loads it by file path, so it never changes what that root imports. It is
a cooperating-verification control, not an operating-system sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import threading
import time
from pathlib import Path

#: The os-level calls the ledger uses, bound once: a test that patches ``os.scandir`` or ``os.stat`` for its own purpose must
#: not change what a ledger records or says.
_os_open, _os_write, _os_close, _scandir, _stat, _lstat = os.open, os.write, os.close, os.scandir, os.stat, os.lstat

CONTEXT_ENV = "ACT_VERIFY_CONTEXT"
#: The checkout the routine session marks: the outermost routine session's own. Synthetic fixtures are judged against it.
ROOT_ENV = "ACT_VERIFY_ROOT"
#: The effect ledger directory of the routine session or gate stage (see :func:`init_ledger`).
LEDGER_ENV = "ACT_EFFECT_LEDGER"
#: The routine session's owned disposable root (its pytest basetemp). It only narrows where a synthetic fixture may lie.
DISPOSABLE_ENV = "ACT_VERIFY_DISPOSABLE"
ROUTINE = "routine"
REFUSED_EXIT = 2
DATA_ONLY = frozenset({"--help", "-h"})
EFFECTS = frozenset({"native-desktop", "real-app-launch", "real-engine", "external-network", "install", "scaling",
                     "release-build"})
LEDGER_FORMAT = "act-effect-ledger/2"
LEDGER_HEADER = "ledger.json"
SYNTHETIC_DECLARATION = "act-synthetic-fixture.json"
SYNTHETIC_FORMAT = "act-synthetic-fixture/1"
GATE = "files/dev-work/verification-gate/"
#: A Python file name is spelled as a stem plus ``_PY`` on purpose: the evidence ledger's static closure reads a literal
#: ``"....py"`` string as a dependency edge, and every test's closure reaches this module through routine_effects.
_PY = ".py"
ORCHESTRATOR = GATE + "verify" + _PY
#: Where a classified heavyweight entrypoint lives, relative to any checkout. A file key matches that file; a key ending in
#: ``/`` matches everything below it. Anything here that ``verification.json`` ``entrypoints`` does not call bounded or
#: data-only refuses, so a new, unknown or unreadable entry fails closed. Matched case-insensitively (NTFS/APFS default) and
#: at a path-component boundary, wherever the checkout is.
LAUNCH_ROOTS = {
    GATE + "acceptance_runner" + _PY: "native-desktop",
    ORCHESTRATOR: "native-desktop",
    GATE + "qualification/": "real-app-launch",
    GATE + "scaling/": "scaling",
    GATE + "adapters/": "native-desktop",
    "files/dev-tools/": "real-engine",
    "files/tests/macos_gui_driver" + _PY: "real-app-launch",
    "files/tests/manual_plan3_harness" + _PY: "native-desktop",
    "files/tests/manual_plan6_harness" + _PY: "native-desktop",
    "files/tests/manual_windows_ui_prototype" + _PY: "native-desktop",
    # The production application, setup, stage-0 hosts and release builder (no __main__ table rows: they are not verification
    # entrypoints, so their routine disposition is fixed here; the stage-0 hosts have reviewed bounded shapes in routine_effects).
    "scripts/launcher" + _PY: "real-app-launch",
    "scripts/shared/bootstrap" + _PY: "install",
    "scripts/shared/bootstrap_host.ps1": "install",
    "scripts/shared/bootstrap_host_macos.sh": "install",
    "scripts/shared/release" + _PY: "release-build",
    "Setup_and_Run-audiobook-creation-tool.bat": "install",
    "Setup_and_Run-audiobook-creation-tool.command": "install",
}


def in_routine(environ=None) -> bool:
    return (os.environ if environ is None else environ).get(CONTEXT_ENV) == ROUTINE


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _within(path, base) -> bool:
    real, root = _norm(path), _norm(base)
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def launch_role(relative_or_path: str) -> tuple[str, str, str] | None:
    """``(launch root, its effect, the path relative to that checkout)`` when a path names a heavyweight entrypoint of any
    checkout: matched by its trailing path components, never by where the checkout lies. None otherwise."""
    text = os.fspath(relative_or_path).replace("\\", "/")
    lowered = "/" + text.lower().lstrip("/")
    for root, effect in LAUNCH_ROOTS.items():
        key = "/" + root.lower()
        if root.endswith("/"):
            at = lowered.rfind(key)
            if at >= 0:
                return root, effect, (root + lowered[at + len(key):]) if lowered[at + len(key):] else root
        elif lowered.endswith(key):
            return root, effect, root
    return None


def data_only_shape(args, data_only=(), anywhere=()) -> bool:
    """Whether the arguments after an entrypoint's script are a data-only invocation. ``--help``/``-h`` count only as the sole
    argument; a reviewed data-only flag of that entrypoint (``data_only``) only as the first argument; an ``anywhere`` flag (a
    store-true flag the entrypoint's own parser acts on before any effect, such as the gate's ``--plan``) as a standalone
    token. A data-only token elsewhere -- the value of another option, a later argument -- is not a data-only invocation."""
    args = [str(arg) for arg in args]
    if len(args) == 1 and args[0] in DATA_ONLY:
        return True
    if args and args[0] in set(data_only):
        return True
    return bool(set(anywhere) & set(args))


# --------------------------------------------------------------------------- #
#  The effect ledger
# --------------------------------------------------------------------------- #
class LedgerError(OSError):
    """The ledger could not be written: accounting failed, so nothing the process did can be called clean."""


def init_ledger(path, *, owner: str, stage: str = "", token: str = "") -> Path:
    """Create a ledger directory and its header before anything that records into it runs. The directory must not exist yet:
    a ledger belongs to the one stage or session that created it."""
    path = Path(path)
    path.mkdir(parents=False, exist_ok=False)
    header = {"format": LEDGER_FORMAT, "owner": owner, "stage": stage, "token": token, "created": time.time()}
    (path / LEDGER_HEADER).write_text(json.dumps(header), encoding="utf-8")
    return path


class ProcessRecord:
    """One process's own ledger file (``p<pid>-<random>.jsonl``): ``start`` first, its refusals, ``end`` last. A file per
    process, so concurrent writers never share a file; a lock per process, so its threads never interleave a line."""

    def __init__(self, ledger, role: str) -> None:
        self.ledger = Path(ledger)
        self.role = role
        self.path: Path | None = None
        self.failed: list[str] = []
        self.ended = False
        self.lock = threading.RLock()

    def _write(self, row: dict) -> None:
        line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            try:
                if not _is_regular(os.path.join(self.ledger, LEDGER_HEADER)):
                    raise LedgerError(f"the effect ledger {self.ledger} was not initialized by its owner")
                if self.path is None:
                    self.path = self.ledger / f"p{os.getpid()}-{secrets.token_hex(4)}.jsonl"
                    fd = _os_open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
                    first = {"kind": "start", "pid": os.getpid(), "ppid": os.getppid(), "role": self.role,
                             "argv0": str(sys.argv[0] if sys.argv else "")[-200:]}
                    _os_write(fd, (json.dumps(first, ensure_ascii=False) + "\n").encode("utf-8"))
                    _os_close(fd)
                fd = _os_open(self.path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0))
                try:
                    if _os_write(fd, line) != len(line):
                        raise LedgerError("a short write to the effect ledger")
                finally:
                    _os_close(fd)
            except OSError as exc:
                self.failed.append(f"{type(exc).__name__}: {exc}"[:300])
                raise LedgerError(f"effect ledger write failed: {exc}") from exc

    def start(self) -> None:
        self._write({"kind": "mark", "event": "accounting-initialized"})

    def refusal(self, row: dict) -> None:
        self._write({"kind": "refusal", **row})

    def end(self, *, exit_status, refusals: int, unexpected: int) -> None:
        with self.lock:
            if self.ended:
                return
            self._write({"kind": "end", "exit": exit_status, "refusals": refusals, "unexpected": unexpected,
                         "accounting": "failed" if self.failed else "ok"})
            self.ended = True


def _is_regular(path) -> bool:
    """A plain file, not a link (os-level calls only: a test that patches pathlib must not change what a ledger says)."""
    try:
        return stat.S_ISREG(_lstat(path).st_mode)
    except OSError:
        return False


def _read_text(path) -> str:
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


_KINDS = {"start": {"pid": int, "role": str}, "mark": {"event": str}, "end": {"refusals": int, "accounting": str},
          "refusal": {"effect": str, "detail": str, "origin": str, "pid": int, "expected": bool}}


def read_ledger(path, *, token: str | None = None, require_role: str | None = None) -> dict:
    """The verdict of a ledger directory. ``status`` is ``PASS`` only for an initialized ledger whose every process file is
    complete and well formed, with no unexpected refusal, no accounting failure and (``require_role``) a completed session of
    that role. Missing, uninitialized, unreadable, empty, incomplete or malformed is never clean."""
    path = Path(path)
    verdict = {"status": "FAIL", "problems": [], "refusals": [], "unexpected": [], "processes": 0, "complete": 0,
               "roles": []}
    problems = verdict["problems"]
    try:
        directory = stat.S_ISDIR(_stat(path).st_mode)
    except OSError:
        directory = False
    if not directory:
        problems.append("missing: the ledger was never created")
        return verdict
    try:
        header = json.loads(_read_text(os.path.join(path, LEDGER_HEADER)))
    except (OSError, ValueError) as exc:
        problems.append(f"uninitialized or unreadable header ({type(exc).__name__})")
        return verdict
    if not isinstance(header, dict) or header.get("format") != LEDGER_FORMAT:
        problems.append(f"header of unknown format {header.get('format') if isinstance(header, dict) else type(header).__name__}")
        return verdict
    if token is not None and header.get("token") != token:
        problems.append("the header belongs to another stage")
    try:
        with _scandir(path) as entries:
            files = sorted(Path(entry.path) for entry in entries if entry.name != LEDGER_HEADER)
    except OSError as exc:
        problems.append(f"unreadable ({type(exc).__name__})")
        return verdict
    for item in files:
        if not (item.name.startswith("p") and item.name.endswith(".jsonl")) or not _is_regular(item):
            problems.append(f"{item.name}: not a process record")
            continue
        verdict["processes"] += 1
        try:
            lines = _read_text(item).splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{item.name}: unreadable ({type(exc).__name__})")
            continue
        rows = []
        for number, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
            except ValueError:
                problems.append(f"{item.name}:{number}: not JSON")
                continue
            kind = row.get("kind") if isinstance(row, dict) else None
            shape = _KINDS.get(kind)
            if shape is None or any(not isinstance(row.get(key), kind_type) or isinstance(row.get(key), bool) != (kind_type is bool)
                                    for key, kind_type in shape.items()):
                problems.append(f"{item.name}:{number}: a record of the wrong shape")
                continue
            rows.append(row)
        if not rows or rows[0]["kind"] != "start":
            problems.append(f"{item.name}: no start record")
            continue
        verdict["roles"].append(rows[0]["role"])
        ends = [index for index, row in enumerate(rows) if row["kind"] == "end"]
        if not ends:
            problems.append(f"{item.name}: {rows[0]['role']} pid {rows[0]['pid']} never completed its accounting (interrupted, "
                            "or its ledger writes failed)")
        elif ends != [len(rows) - 1]:
            problems.append(f"{item.name}: records after its end")
        else:
            verdict["complete"] += 1
            if rows[-1]["accounting"] != "ok":
                problems.append(f"{item.name}: its accounting failed")
            if require_role and rows[0]["role"] == require_role:
                verdict.setdefault("sessions", 0)
                verdict["sessions"] += 1
        for row in rows:
            if row["kind"] == "refusal":
                verdict["refusals"].append(row)
                if not row["expected"]:
                    verdict["unexpected"].append(row)
    if require_role and not verdict.get("sessions"):
        problems.append(f"no completed {require_role} session recorded (an empty or incomplete ledger is not clean)")
    if not problems and not verdict["unexpected"]:
        verdict["status"] = "PASS"
    return verdict


_process_record: ProcessRecord | None = None


def _child_record(role: str) -> ProcessRecord | None:
    global _process_record
    ledger = os.environ.get(LEDGER_ENV)
    if not ledger:
        return None
    if _process_record is None or _process_record.ledger != Path(ledger):
        _process_record = ProcessRecord(ledger, role)
    return _process_record


# --------------------------------------------------------------------------- #
#  The reviewed synthetic gate fixture
# --------------------------------------------------------------------------- #
def _sha256(path) -> str | None:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return None
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def synthetic_fixture(root, environ=None) -> dict | None:
    """The validated declaration of a synthetic gate fixture tree, or None. Valid only inside routine verification, for a tree
    inside the routine session's owned disposable root, that neither is nor contains the marked checkout, whose
    declaration (a plain file, not a link) names this tree, and whose gate orchestrator is byte-identical to the marked
    checkout's (so the operation boundaries it enforces are the current ones)."""
    environ = os.environ if environ is None else environ
    disposable, marked = environ.get(DISPOSABLE_ENV), environ.get(ROOT_ENV)
    if not in_routine(environ) or not disposable or not marked or not root:
        return None
    try:
        tree = Path(root)
        if not _within(tree, disposable) or _within(marked, tree):  # never the marked checkout, nor a tree containing it
            return None
        declaration = tree / SYNTHETIC_DECLARATION
        if _sha256(declaration) is None:
            return None
        data = json.loads(declaration.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("format") != SYNTHETIC_FORMAT or _norm(data.get("root", "")) != _norm(tree):
        return None
    synthetic = data.get("synthetic", {})
    if not isinstance(synthetic, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in synthetic.items()):
        return None
    real = _sha256(Path(marked) / ORCHESTRATOR)
    if real is None or _sha256(tree / ORCHESTRATOR) != real:
        return None
    return data


def synthetic_stand_in(root, relative: str, environ=None) -> bool:
    """Whether ``relative`` in a valid synthetic fixture tree is a declared stand-in: its bytes are the declared ones and are
    not the marked checkout's real file at that place (a real runner, copied in, is never a stand-in)."""
    environ = os.environ if environ is None else environ
    data = synthetic_fixture(root, environ)
    if data is None:
        return False
    key = relative.replace("\\", "/")
    declared = {k.replace("\\", "/").lower(): v for k, v in data["synthetic"].items()}.get(key.lower())
    actual = _sha256(Path(root) / key)
    if not declared or actual is None or actual != declared:
        return False
    return actual != _sha256(Path(environ[ROOT_ENV]) / key)


# --------------------------------------------------------------------------- #
#  The child side: refusing roots and operation checks
# --------------------------------------------------------------------------- #
def _own_root() -> Path:
    return Path(__file__).resolve().parents[4]


def record_refusal(effect: str, detail: str, *, origin: str, role: str = "entrypoint") -> bool:
    """Record a refusal in this process's own ledger file, start and end included. False when it could not be recorded (the
    refusal stands either way, and a missing or unwritable ledger is itself never clean for the stage that owns it)."""
    envelope = sys.modules.get("routine_effects")
    if envelope is not None and getattr(envelope, "_installed", False):
        # Inside a routine pytest process: its own accounting (expected-refusal scope, session ledger record) takes it.
        envelope.refuse(effect, detail, origin=origin)  # raises EffectRefused, a PermissionError
    record = _child_record(role)
    row = {"effect": effect, "detail": str(detail)[:500], "origin": origin, "pid": os.getpid(), "expected": False,
           "test": os.environ.get("PYTEST_CURRENT_TEST", "child")}
    if record is None:
        return False
    try:
        record.refusal(row)
        record.end(exit_status=REFUSED_EXIT, refusals=1, unexpected=1)
        return True
    except LedgerError:
        return False


def _refuse(entry: str, effect: str, detail: str) -> None:
    recorded = record_refusal(effect, f"{entry} {detail}", origin="entrypoint")
    sys.stderr.write(f"{entry}: refused: {detail} inside routine verification (GATE.md)"
                     + ("" if recorded else "; the refusal could not be recorded in an effect ledger") + "\n")
    sys.stderr.flush()
    raise SystemExit(REFUSED_EXIT)


def refuse_under_routine(entry: str, effect: str, argv=None, *, data_only=frozenset(), anywhere=frozenset(), origin=None,
                         root=None) -> None:
    """For a maintained heavyweight root, first thing: refuse to start inside routine verification, wherever the root lies.
    A data-only invocation (:func:`data_only_shape`) stays usable. Inside a reviewed synthetic fixture tree, the gate's
    orchestrator may run (its own operation boundaries apply) and a declared synthetic stand-in may run in place of a runner;
    nothing else does. Exits ``REFUSED_EXIT`` after recording the refusal."""
    if not in_routine():
        return
    argv = list(sys.argv[1:] if argv is None else argv)
    if data_only_shape(argv, data_only, anywhere):
        return
    origin = os.fspath(origin if origin is not None else (sys.argv[0] if sys.argv else ""))
    tree = Path(root) if root is not None else _own_root()
    if origin and origin not in ("-c", "-m", "-"):
        try:
            relative = Path(os.path.realpath(origin)).relative_to(Path(os.path.realpath(tree))).as_posix()
        except ValueError:
            relative = None
        if relative == ORCHESTRATOR and synthetic_fixture(tree) is not None:
            return
        if relative and synthetic_stand_in(tree, relative):
            return
    _refuse(entry, effect, "a heavyweight verification entrypoint does not start")


def check_operation(effect: str, detail: str, *, root=None, stand_in: str | None = None) -> None:
    """At a heavyweight operation inside an imported callable (not only a ``__main__`` block): refuse inside routine
    verification, recording the refusal and raising PermissionError. ``stand_in`` names the file (relative to the checkout)
    whose declared synthetic stand-in, in a reviewed synthetic fixture tree, the operation would start instead of real work."""
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}")
    if not in_routine():
        return
    tree = Path(root) if root is not None else _own_root()
    if stand_in and synthetic_stand_in(tree, stand_in):
        return
    recorded = record_refusal(effect, detail, origin="operation")
    raise PermissionError(f"refused in routine verification: {effect}: {detail}"
                          + ("" if recorded else " (and the refusal could not be recorded in an effect ledger)"))
