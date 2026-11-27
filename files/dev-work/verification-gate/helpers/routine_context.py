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
import io as _io  # the original open: a test patching builtins.open never reaches it
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
#: Captured at import: a test that replaces secrets.token_hex (to force a name collision) never reaches launch identities.
_urandom = os.urandom


def _token_hex(size: int) -> str:
    return _urandom(size).hex()

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
LEDGER_FORMAT = "act-effect-ledger/3"
#: Earlier formats are read back as history only: they never satisfy the current participant contract (R2).
HISTORICAL_LEDGER_FORMATS = frozenset({"act-effect-ledger/2"})
RESERVATION_FORMAT = "act-launch/1"
#: The launch identity a reserved child is started with (its parent reserved it before the launch existed).
LAUNCH_ENV = "ACT_ROUTINE_LAUNCH"
#: Where the child bootstrap finds the child's PYTHONPATH: moved out of PYTHONPATH so that nothing on it (a sitecustomize, a
#: shadowing module) runs before the envelope; restored by the bootstrap before the target starts.
PYTHONPATH_ENV = "ACT_ROUTINE_PYTHONPATH"
LEDGER_HEADER = "ledger.json"
SYNTHETIC_DECLARATION = "act-synthetic-fixture.json"
SYNTHETIC_FORMAT = "act-synthetic-fixture/2"
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


# --------------------------------------------------------------------------- #
#  A Python command line (R2): one parser, shared by the parent's launch decision and the child bootstrap
# --------------------------------------------------------------------------- #
#: Interpreter options without a value that a prepared child keeps, in front of the bootstrap.
PYTHON_FLAGS = frozenset("bBdEIOPqsSuv")
#: Options that print and exit without running a program.
PYTHON_INFO = frozenset({"-V", "--version", "-h", "-?", "--help", "--help-env", "--help-xoptions", "--help-all"})


class PythonCommand:
    """The interpreter options, the program (``script``, ``module`` or ``code``) and its arguments of a Python command line
    (everything after the interpreter). ``mode`` is ``info`` for a version or help request that runs nothing, ``stdin`` when
    the program would be read from standard input, and ``unsupported`` (with ``problem``) for a form a prepared child cannot
    reproduce faithfully (``-i``, ``-x``, an unknown or incomplete option)."""

    __slots__ = ("flags", "letters", "mode", "target", "rest", "problem")

    def __init__(self, flags, letters, mode, target, rest, problem=None) -> None:
        self.flags, self.letters, self.mode, self.target, self.rest, self.problem = (
            tuple(flags), frozenset(letters), mode, target, tuple(rest), problem)

    @property
    def isolated(self) -> bool:
        return "I" in self.letters

    @property
    def ignores_environment(self) -> bool:
        return bool({"I", "E"} & self.letters)

    @property
    def safe_path(self) -> bool:
        return bool({"I", "P"} & self.letters)

    def identity(self) -> str:
        """The launch identity of this program and its arguments: what a reservation records and the started child checks.
        Normalized (options as tokens, the program by mode), so ``-c CODE`` and ``-cCODE`` are the same launch."""
        return argv_digest([*self.flags, f"<{self.mode}>", self.target or "", *self.rest])


def parse_python(args) -> PythonCommand:
    """Read a Python command line (the arguments after the interpreter) as CPython 3.12 reads it."""
    args = [str(arg) for arg in args]
    flags: list[str] = []
    letters: set[str] = set()
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            if index + 1 < len(args):
                return PythonCommand(flags, letters, "script", args[index + 1], args[index + 2:])
            return PythonCommand(flags, letters, "stdin", None, [])
        if arg == "-":
            return PythonCommand(flags, letters, "stdin", None, args[index + 1:])
        if arg.startswith("--"):
            if arg in PYTHON_INFO:
                return PythonCommand(flags, letters, "info", arg, args[index + 1:])
            if arg == "--check-hash-based-pycs" and index + 1 < len(args):
                flags += [arg, args[index + 1]]
                index += 2
                continue
            return PythonCommand(flags, letters, "unsupported", None, [], f"the option {arg[:40]}")
        if arg.startswith("-") and len(arg) > 1:
            position, kept = 1, ""
            while position < len(arg):
                letter = arg[position]
                if letter in "cm":
                    if kept:
                        flags.append("-" + kept)
                    value = arg[position + 1:]
                    if value:
                        rest = args[index + 1:]
                    elif index + 1 < len(args):
                        value, rest = args[index + 1], args[index + 2:]
                    else:
                        return PythonCommand(flags, letters, "unsupported", None, [], f"-{letter} without a value")
                    if letter == "m" and not value:
                        return PythonCommand(flags, letters, "unsupported", None, [], "-m without a module")
                    return PythonCommand(flags, letters, "code" if letter == "c" else "module", value, rest)
                if letter in "WX":
                    if kept:
                        flags.append("-" + kept)
                        kept = ""
                    value = arg[position + 1:]
                    if value:
                        flags.append(f"-{letter}{value}")
                    elif index + 1 < len(args):
                        flags += [f"-{letter}", args[index + 1]]
                        index += 1
                    else:
                        return PythonCommand(flags, letters, "unsupported", None, [], f"-{letter} without a value")
                    position = len(arg)
                    break
                if letter in PYTHON_FLAGS:
                    letters.add(letter)
                    kept += letter
                    position += 1
                    continue
                if letter in "hV?":
                    return PythonCommand(flags, letters, "info", "-" + letter, args[index + 1:])
                if letter == "i":
                    return PythonCommand(flags, letters, "unsupported", None, [], "-i (interactive)")
                return PythonCommand(flags, letters, "unsupported", None, [], f"the option -{letter}")
            if kept:
                flags.append("-" + kept)
            index += 1
            continue
        return PythonCommand(flags, letters, "script", arg, args[index + 1:])
    return PythonCommand(flags, letters, "stdin", None, [])


def launch_identity(args) -> str:
    """The identity a reservation records for a launch's arguments (everything after the program): the normalized Python
    command line when it is one, the raw arguments otherwise."""
    command = parse_python(args)
    if command.mode in ("script", "module", "code"):
        return command.identity()
    return argv_digest(args)


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
#  The effect ledger (format 3, Phase 1A-1 R2: accounting obligations)
# --------------------------------------------------------------------------- #
#: The roles a participant may record. A reservation names the role it expects; a participant of another role does not
#: satisfy it.
ROLES = frozenset({"gate", "routine-pytest", "guarded-pytest", "raw-pytest", "routine-child", "synthetic-gate", "test",
                   "entrypoint", "operation", "routine-process"})
#: What a reservation may expect, and the participant roles that satisfy each expectation.
EXPECTATIONS = {"routine-child": frozenset({"routine-child"}), "routine-pytest": frozenset({"routine-pytest"}),
                "guarded-pytest": frozenset({"guarded-pytest"}), "synthetic-gate": frozenset({"routine-child"}),
                "entrypoint": frozenset({"entrypoint", "operation"})}
_MAX_RECORD_BYTES = 16 << 20
_MAX_PROBLEMS = 200
_LAUNCH_TEXT = frozenset("0123456789abcdef")


class LedgerError(OSError):
    """The ledger could not be written: accounting failed, so nothing the process did can be called clean."""


def new_launch() -> str:
    """A launch identity: unique for every reserved launch of every participant."""
    return _token_hex(10)


def valid_launch(value) -> bool:
    return isinstance(value, str) and len(value) == 20 and set(value) <= _LAUNCH_TEXT


def _exclusive_write(path, data: bytes) -> None:
    """Create ``path`` (never an existing one) and write ``data`` whole: a short write is a failure, not a smaller record."""
    fd = _os_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    try:
        if _os_write(fd, data) != len(data):
            raise LedgerError(f"a short write to {os.path.basename(path)}")
    finally:
        _os_close(fd)


def init_ledger(path, *, owner: str, stage: str = "", token: str = "") -> Path:
    """Create a ledger directory and its header before anything that records into it runs. The directory must not exist yet:
    a ledger belongs to the one stage or session that created it."""
    path = Path(path)
    path.mkdir(parents=False, exist_ok=False)
    header = {"format": LEDGER_FORMAT, "owner": owner, "stage": stage, "token": token, "created": time.time()}
    _exclusive_write(path / LEDGER_HEADER, json.dumps(header).encode("utf-8"))
    return path


def reservation_path(ledger, launch: str) -> Path:
    return Path(ledger) / f"r-{launch}.json"


def read_reservation(ledger, launch: str) -> dict | None:
    """A launch's reservation in ``ledger`` (a plain file, never a link), or None."""
    if not valid_launch(launch):
        return None
    path = reservation_path(ledger, launch)
    if not _is_regular(path):
        return None
    try:
        data = json.loads(_read_bytes(path).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("format") == RESERVATION_FORMAT and data.get("launch") == launch \
        else None


def argv_digest(argv) -> str:
    """The identity of a launch's command line, as the reservation records it and the child checks it."""
    return hashlib.sha256("\0".join(str(part) for part in argv).encode("utf-8", "surrogatepass")).hexdigest()


class ProcessRecord:
    """One participant's own ledger file (``p<participant>.jsonl``): ``start`` first, ``end`` last, everything it records in
    between. A file per process, so concurrent writers never share a file; a lock per process, so its threads never
    interleave a line. A child started for a reserved launch carries that launch and its reserving parent in its start row."""

    def __init__(self, ledger, role: str, *, launch: str | None = None, parent: str | None = None) -> None:
        self.ledger = Path(ledger)
        self.role = role
        self.launch = launch
        self.parent = parent
        self.participant: str | None = None
        self.path: Path | None = None
        self.failed: list[str] = []
        self.ended = False
        self.lock = threading.RLock()
        #: launch -> reservation facts this participant reserved (reconciled in its own process as well as by the reader).
        self.reserved: dict[str, dict] = {}

    def _write(self, row: dict) -> None:
        line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            try:
                if self.ended:
                    raise LedgerError("a record after this participant's end")
                if not _is_regular(os.path.join(self.ledger, LEDGER_HEADER)):
                    raise LedgerError(f"the effect ledger {self.ledger} was not initialized by its owner")
                if self.path is None:
                    participant = f"{os.getpid()}-{_token_hex(4)}"
                    path = self.ledger / f"p{participant}.jsonl"
                    first = {"kind": "start", "pid": os.getpid(), "ppid": os.getppid(), "role": self.role,
                             "participant": participant, "launch": self.launch, "parent": self.parent,
                             "executable": os.path.normcase(os.path.abspath(sys.executable or "")),
                             "created": process_created(os.getpid()),
                             "argv0": str(sys.argv[0] if sys.argv else "")[-200:]}
                    _exclusive_write(path, (json.dumps(first, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.path, self.participant = path, participant
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

    def ensure_started(self) -> str:
        """This participant's identity, writing its start record first if nothing was written yet."""
        if self.participant is None:
            self.start()
        return self.participant

    def reserve(self, launch: str, *, expect: str, identity: str, target_ledger=None, roots=(), stage: str = "",
                note: str = "", lifecycle: dict | None = None, measurement: str = "") -> None:
        """Establish a launch's accounting obligation before the launch exists: the reservation file (exclusive) in the ledger
        the child will record in, then the reserving row in this participant's own record. Any failure raises LedgerError and
        the launch must not happen. ``measurement`` names a reviewed measurement the child's envelope runs in (only
        "network-guard", D-R2-7); the child takes it from this reservation, never from its own environment."""
        if measurement not in MEASUREMENTS:
            raise ValueError(f"unknown measurement {measurement!r}")
        if expect not in EXPECTATIONS:
            raise ValueError(f"unknown expectation {expect!r}")
        with self.lock:
            participant = self.ensure_started()
            target = Path(target_ledger) if target_ledger is not None else self.ledger
            linked = os.path.normcase(os.path.abspath(target)) != os.path.normcase(os.path.abspath(self.ledger))
            data = {"format": RESERVATION_FORMAT, "launch": launch, "parent": participant, "parent_pid": os.getpid(),
                    "expect": expect, "stage": stage, "identity": identity, "roots": [str(root) for root in roots],
                    "lifecycle": _lifecycle(lifecycle), "created": time.time(), "note": note[:200],
                    # Diagnostic only: the test whose launch this is (never part of any decision).
                    "test": os.environ.get("PYTEST_CURRENT_TEST", "")[:300]}
            if measurement:
                data["measurement"] = measurement
            try:
                if not _is_regular(os.path.join(target, LEDGER_HEADER)):
                    raise LedgerError(f"the launch's ledger {target} was not initialized by its owner")
                _exclusive_write(reservation_path(target, launch), json.dumps(data).encode("utf-8"))
            except OSError as exc:
                self.failed.append(f"reservation: {type(exc).__name__}: {exc}"[:300])
                raise LedgerError(f"a launch reservation could not be written: {exc}") from exc
            self._write({"kind": "reserve", "launch": launch, "expect": expect, "ledger": str(target) if linked else ""})
            self.reserved[launch] = {"expect": expect, "ledger": str(target), "linked": linked, "state": "reserved"}

    def spawned(self, launch: str, pid: int, *, executable: str = "", redirector: bool = False, via: str = "direct",
                created: int | None = None) -> None:
        """The launch exists: its actual process (pid and creation time), the program actually started and whether that
        program is a Windows venv redirector (whose interpreter is then its direct child with the same executable)."""
        self._write({"kind": "spawned", "launch": launch, "pid": int(pid), "executable": os.path.normcase(executable),
                     "redirector": bool(redirector), "via": via, "created": created})
        if launch in self.reserved:
            self.reserved[launch]["state"] = "spawned"

    def stop(self, launch: str, *, mechanism: str, pid: int, code: int | None, tree: bool, ok: bool) -> None:
        """The intent and the action of an intentional termination of an owned launch, written before its effect is
        observed. Its explanation holds only with the lifecycle the launch was reserved with and the observed outcome."""
        self._write({"kind": "stop", "launch": launch, "mechanism": mechanism, "pid": int(pid), "code": code,
                     "tree": bool(tree), "ok": bool(ok)})

    def not_spawned(self, launch: str, error: str) -> None:
        self._write({"kind": "not-spawned", "launch": launch, "error": str(error)[:300]})
        if launch in self.reserved:
            self.reserved[launch]["state"] = "not-spawned"

    def observed(self, launch: str, *, exit_status, how: str, pid: int | None = None) -> None:
        self._write({"kind": "observed", "launch": launch, "exit": exit_status, "how": how, "pid": pid})

    def adopted(self, ledger, *, status: str, accounting: str) -> None:
        self._write({"kind": "adopted", "ledger": str(ledger), "status": status, "accounting": accounting})

    def profiled(self, launch: str, *, profile: str, identity: str) -> None:
        """A launch run unchanged under an exact reviewed profile (it owes no participant): recorded before it exists, then
        its spawn and its observed end, by this participant -- the parent-side evidence of a bounded measurement."""
        self._write({"kind": "profiled", "launch": launch, "profile": profile, "identity": identity})

    def contained(self, launch: str) -> None:
        """This participant placed its own launch in a kill-on-close Job it holds: when this participant's process ends, the
        kernel ends that launch's tree with it (the evidence an explained stop of this participant extends to them)."""
        self._write({"kind": "contained", "launch": launch})

    def delegate(self, launch: str, ledger) -> None:
        self._write({"kind": "delegate", "launch": launch, "ledger": str(ledger)})

    def end(self, *, exit_status, refusals: int, unexpected: int, how: str = "exit") -> None:
        """This participant's own end. ``how`` says which exit path wrote it: ``exit`` (the interpreter's normal exit, with
        the status the program left) or ``os._exit`` (the program's own immediate exit). Nobody else writes it."""
        with self.lock:
            if self.ended:
                return
            self._write({"kind": "end", "exit": exit_status, "refusals": refusals, "unexpected": unexpected,
                         "accounting": "failed" if self.failed else "ok", "how": how})
            self.ended = True


#: The intentional terminations a launch may be reserved to expect (D-R2-1). ``self`` is the participant ending itself
#: (os.kill of its own pid); ``native-crash`` a reviewed fixture whose purpose is a crash with a declared exit code;
#: ``abrupt-exit`` a reviewed fixture that ends itself with ``os._exit`` and a declared exit code (no end record is ever
#: written for it; the same rule as a crash: only an observed exit among the declared codes explains it).
#: The reviewed measurements a reservation may put its child's envelope in ("" is none).
MEASUREMENTS = frozenset({"", "network-guard"})
STOP_MECHANISMS = frozenset({"terminate-process", "terminate-job", "close-job", "taskkill", "self", "native-crash",
                             "abrupt-exit"})
_CODE_ENDS = frozenset({"native-crash", "abrupt-exit"})


def _lifecycle(value) -> dict:
    """A reservation's expected lifecycle: the stop mechanisms established before the launch existed, and for a crash
    fixture the exit codes it may end with. Empty means a normal end is required."""
    if not value:
        return {"stops": [], "codes": []}
    stops = sorted(set(value.get("stops", ())))
    unknown = set(stops) - STOP_MECHANISMS
    if unknown:
        raise ValueError(f"unknown stop mechanism(s) {sorted(unknown)}")
    return {"stops": stops, "codes": sorted({int(code) for code in value.get("codes", ())})}


def process_created(pid: int) -> int | None:
    """A process's creation time (Windows FILETIME ticks), which with its pid identifies it; None off Windows or when it
    cannot be read. Opens and closes one limited query handle."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return None


def _is_regular(path) -> bool:
    """A plain file, not a link or reparse point (os-level calls only: a test that patches pathlib must not change what a
    ledger says)."""
    try:
        info = _lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400


def _read_bytes(path, limit: int = _MAX_RECORD_BYTES) -> bytes:
    with _io.open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise LedgerError(f"{os.path.basename(path)} is larger than any record this ledger writes")
    return data


def _read_text(path) -> str:
    return _read_bytes(path).decode("utf-8")


def _is_pid(value) -> bool:
    return type(value) is int and value > 0


def _is_int(value) -> bool:
    return type(value) is int


def _opt(check):
    return lambda value: value is None or check(value)


def _is_str(value) -> bool:
    return type(value) is str


def _is_bool(value) -> bool:
    return type(value) is bool


#: Every row kind a participant writes, with the exact type of each required field. Anything else is malformed.
_ROWS = {
    "start": {"pid": _is_pid, "ppid": _is_int, "role": _is_str, "participant": _is_str, "launch": _opt(valid_launch),
              "parent": _opt(_is_str), "executable": _is_str, "created": _opt(_is_int)},
    "mark": {"event": _is_str},
    "refusal": {"effect": _is_str, "detail": _is_str, "origin": _is_str, "pid": _is_pid, "expected": _is_bool},
    "reserve": {"launch": valid_launch, "expect": _is_str, "ledger": _is_str},
    "spawned": {"launch": valid_launch, "pid": _is_pid, "executable": _is_str, "redirector": _is_bool, "via": _is_str,
                "created": _opt(_is_int)},
    "stop": {"launch": valid_launch, "mechanism": _is_str, "pid": _is_pid, "code": _opt(_is_int), "tree": _is_bool,
             "ok": _is_bool},
    "not-spawned": {"launch": valid_launch, "error": _is_str},
    "observed": {"launch": valid_launch, "exit": _opt(_is_int), "how": _is_str, "pid": _opt(_is_pid)},
    "adopted": {"ledger": _is_str, "status": _is_str, "accounting": _is_str},
    "delegate": {"launch": valid_launch, "ledger": _is_str},
    "profiled": {"launch": valid_launch, "profile": _is_str, "identity": _is_str},
    "contained": {"launch": valid_launch},
    "end": {"exit": _is_int, "refusals": _is_int, "unexpected": _is_int, "accounting": _is_str, "how": _is_str},
}
_RESERVATION = {"format": _is_str, "launch": valid_launch, "parent": _is_str, "parent_pid": _is_pid, "expect": _is_str,
                "stage": _is_str, "identity": _is_str,
                "roots": lambda value: type(value) is list and all(type(item) is str for item in value),
                "lifecycle": lambda value: type(value) is dict and type(value.get("stops")) is list
                and set(value["stops"]) <= STOP_MECHANISMS and type(value.get("codes")) is list
                and all(type(code) is int for code in value["codes"])}
#: Observations that are not exits a participant could have reported (the child was still running, or someone else reaped it).
_NO_EXIT = frozenset({"running", "reaped-by-owner", "unobservable", "gone"})


def _row_problem(row) -> str | None:
    """Why a decoded line is not a well-formed row of a known kind, or None. Never raises, whatever JSON it is given."""
    if not isinstance(row, dict):
        return f"a record of the wrong shape (a {type(row).__name__} where a record object belongs)"
    kind = row.get("kind")
    if type(kind) is not str:
        return f"a record whose kind is a {type(kind).__name__}, not a string"
    shape = _ROWS.get(kind)
    if shape is None:
        return f"a record of unknown kind {kind[:40]!r}"
    for key, check in shape.items():
        if key not in row or not check(row[key]):
            return f"a {kind} record whose {key} is missing or of the wrong type"
    return None


def _parse_participant(name: str, data: bytes) -> tuple[list[dict], list[str]]:
    """Rows and problems of one participant file. A partial last line, a bad line, a missing or repeated start, two
    initializations, two ends or anything after the end is a problem; counts in the end are recomputed from the rows."""
    problems: list[str] = []
    rows: list[dict] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [], [f"{name}: not UTF-8"]
    if text and not text.endswith("\n"):
        problems.append(f"{name}: a truncated last record (a short or interrupted write)")
        text = text[: text.rfind("\n") + 1]
    for number, line in enumerate(text.splitlines(), 1):
        try:
            row = json.loads(line)
        except ValueError:
            problems.append(f"{name}:{number}: not JSON")
            continue
        problem = _row_problem(row)
        if problem:
            problems.append(f"{name}:{number}: {problem}")
            continue
        rows.append(row)
    if not rows or rows[0]["kind"] != "start":
        problems.append(f"{name}: no start record")
        return [], problems
    start = rows[0]
    if f"p{start['participant']}.jsonl" != name:
        problems.append(f"{name}: its start record names another participant")
    if sum(row["kind"] == "start" for row in rows) != 1:
        problems.append(f"{name}: more than one start record")
    marks = [row for row in rows if row["kind"] == "mark" and row["event"] == "accounting-initialized"]
    if len(marks) > 1:
        problems.append(f"{name}: initialized more than once")
    ends = [index for index, row in enumerate(rows) if row["kind"] == "end"]
    if len(ends) > 1:
        problems.append(f"{name}: more than one end record")
    elif ends and ends[0] != len(rows) - 1:
        problems.append(f"{name}: records after its end")
    if ends:
        end = rows[ends[0]]
        refusals = [row for row in rows if row["kind"] == "refusal"]
        unexpected = [row for row in refusals if not row["expected"]]
        if end["refusals"] != len(refusals) or end["unexpected"] != len(unexpected):
            problems.append(f"{name}: its end counts ({end['refusals']} refusal(s), {end['unexpected']} unexpected) disagree "
                            f"with its records ({len(refusals)}, {len(unexpected)})")
        if end["accounting"] not in ("ok", "failed"):
            problems.append(f"{name}: an end record with an unknown accounting status")
        if not marks:
            problems.append(f"{name}: it ended without ever initializing its accounting")
    return rows, problems


def read_ledger(path, *, token: str | None = None, require_role: str | None = None, open_roles=(),
                live: bool = False, cache: dict | None = None) -> dict:
    """The verdict of a ledger directory. Total: whatever the directory holds, this returns a verdict and never raises.

    ``status`` is ``PASS`` only for an initialized ledger of the current format whose every participant is complete and well
    formed, whose every reserved launch is reconciled exactly once (spawned and accounted for by exactly one participant of the
    expected role, or confirmed not spawned), with no orphan, duplicate or foreign participant, no unexpected refusal, no
    accounting failure and (``require_role``) a completed session of that role. ``open_roles`` names participants that may still
    be running (the gate's own record while its stage is judged from inside); ``live`` tolerates every participant and launch
    still in progress (a mid-session reader), never a malformed one. ``cache`` (a dict the caller keeps) holds participant
    files already parsed, by name, size and modification time, so a frequent reader does not parse an unchanged file again."""
    verdict = {"status": "FAIL", "format": None, "problems": [], "refusals": [], "unexpected": [], "processes": 0,
               "complete": 0, "roles": [], "participants": {}, "launches": {}}
    problems = verdict["problems"]
    try:
        _read_ledger(Path(path), verdict, token=token, require_role=require_role, open_roles=frozenset(open_roles),
                     live=live, cache=cache)
    except Exception as exc:  # noqa: BLE001 - a reader of untrusted records must answer, never raise
        problems.append(f"the ledger could not be reconciled ({type(exc).__name__})")
    del problems[_MAX_PROBLEMS:]
    if not problems and not verdict["unexpected"]:
        verdict["status"] = "PASS"
    return verdict


def _read_ledger(path: Path, verdict: dict, *, token, require_role, open_roles, live, cache=None) -> None:
    problems = verdict["problems"]
    try:
        info = _lstat(path)
        directory = stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400
    except OSError:
        directory = False
    if not directory:
        problems.append("missing: the ledger was never created" if not os.path.lexists(path) else
                        "not a plain directory (a link or a file): never followed")
        return
    if not _is_regular(path / LEDGER_HEADER):
        problems.append("uninitialized: no plain header file")
        return
    try:
        header = json.loads(_read_text(path / LEDGER_HEADER))
    except (OSError, ValueError) as exc:
        problems.append(f"an unreadable header ({type(exc).__name__})")
        return
    form = header.get("format") if isinstance(header, dict) else None
    verdict["format"] = form if isinstance(form, str) else None
    if form in HISTORICAL_LEDGER_FORMATS:
        problems.append(f"a historical ledger ({form}): read back only as history; it cannot satisfy the current participant "
                        "contract")
        return
    if form != LEDGER_FORMAT:
        problems.append("a header of unknown format")
        return
    for key in ("owner", "stage", "token"):
        if type(header.get(key)) is not str:
            problems.append(f"a header whose {key} is missing or not a string")
            return
    verdict["owner"] = header["owner"]
    if token is not None and header["token"] != token:
        problems.append("the header belongs to another stage")
    try:
        with _scandir(path) as entries:
            names = sorted(entry.name for entry in entries if entry.name != LEDGER_HEADER)
    except OSError as exc:
        problems.append(f"unreadable ({type(exc).__name__})")
        return
    participants: dict[str, dict] = {}
    reservations: dict[str, dict] = {}
    for name in names:
        item = path / name
        if not _is_regular(item):
            problems.append(f"{name}: not a plain file (a link, a directory or a device): never followed")
            continue
        if name.startswith("r-") and name.endswith(".json"):
            launch = name[2:-5]
            try:
                data = json.loads(_read_text(item))
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                problems.append(f"{name}: an unreadable reservation ({type(exc).__name__})")
                continue
            bad = not isinstance(data, dict) or any(key not in data or not check(data[key]) for key, check in _RESERVATION.items())
            if bad or data["launch"] != launch or data["format"] != RESERVATION_FORMAT or data["expect"] not in EXPECTATIONS:
                problems.append(f"{name}: a malformed reservation")
                continue
            reservations[launch] = data
            continue
        if not (name.startswith("p") and name.endswith(".jsonl")):
            problems.append(f"{name}: not a ledger record")
            continue
        verdict["processes"] += 1
        key = None
        if cache is not None:
            try:
                info = _lstat(item)
                key = (str(item), info.st_size, info.st_mtime_ns)
            except OSError:
                key = None
        if key is not None and key in cache:
            rows, found = cache[key]
        else:
            try:
                data = _read_bytes(item)
            except OSError as exc:
                problems.append(f"{name}: unreadable ({type(exc).__name__})")
                continue
            rows, found = _parse_participant(name, data)
            if key is not None and len(data) == key[1]:
                cache[key] = (rows, found)
        problems.extend(found)
        if not rows:
            continue
        start = rows[0]
        entry = {"rows": rows, "start": start, "role": start["role"], "pid": start["pid"], "ppid": start["ppid"],
                 "launch": start["launch"], "parent": start["parent"], "executable": start["executable"],
                 "created": start["created"], "participant": start["participant"],
                 "end": rows[-1] if rows[-1]["kind"] == "end" else None,
                 "initialized": any(row["kind"] == "mark" and row["event"] == "accounting-initialized" for row in rows)}
        participants[start["participant"]] = entry
        verdict["roles"].append(start["role"])
        if start["role"] not in ROLES:
            problems.append(f"{name}: an unknown role {start['role'][:40]!r}")
        for row in rows:
            if row["kind"] == "refusal":
                verdict["refusals"].append(row)
                if not row["expected"]:
                    verdict["unexpected"].append(row)
        if entry["end"] is None:
            # Judged with its launch (an explained stop, D-R2-1) or as the owner (_reconcile); never clean by itself.
            continue
        verdict["complete"] += 1
        if entry["end"]["accounting"] != "ok":
            problems.append(f"{name}: its accounting failed")
        if require_role and start["role"] == require_role:
            verdict["sessions"] = verdict.get("sessions", 0) + 1
    verdict["participants"] = {key: {k: v for k, v in value.items() if k != "rows"} for key, value in participants.items()}
    _reconcile(verdict, header, participants, reservations, live=live, open_roles=open_roles)
    if require_role and not verdict.get("sessions") and not live:
        problems.append(f"no completed {require_role} session recorded (an empty or incomplete ledger is not clean)")


def _reconcile(verdict: dict, header: dict, participants: dict, reservations: dict, *, live: bool, open_roles) -> None:
    """Every reserved launch exactly once; every launched participant reserved; the owner's own root session alone unreserved.

    The reservation file is the obligation (it exists before the launch and is written whole or not at all); the parent's
    ``reserve`` row corroborates it from the parent's own record, and a disagreement between the two is a problem, never a
    choice of one. A participant that ended without its own end record is accounted only by an explained stop
    (:func:`_explained_stop`)."""
    problems = verdict["problems"]
    by_launch: dict[str, list[str]] = {}
    unreserved = []
    for key, entry in participants.items():
        if entry["launch"] is None:
            unreserved.append(key)
        else:
            by_launch.setdefault(entry["launch"], []).append(key)
    # The ledger's owner is its one unreserved participant: the gate in a gate stage ledger, the direct runner in its own.
    owners = [key for key in unreserved if participants[key]["role"] == header["owner"]]
    for key in unreserved:
        entry = participants[key]
        if key not in owners[:1]:
            problems.append(f"participant {key} ({entry['role']}) recorded into this ledger with no reserved launch: a "
                            "foreign or unaccounted participant")
        elif entry["end"] is None and not (live or entry["role"] in open_roles):
            problems.append(f"participant {key}: the {entry['role']} owner pid {entry['pid']} never completed its "
                            "accounting (killed, interrupted, or its ledger writes failed)")
    if len(owners) > 1:
        problems.append(f"{len(owners)} unreserved owner participants: one ledger has one owner")
    # Parent-side rows, by launch, in the order each writer wrote them.
    reserving: dict[str, tuple[str, dict]] = {}
    outcome: dict[str, dict] = {}
    for key, entry in participants.items():
        for position, row in enumerate(entry["rows"]):
            kind = row["kind"]
            if kind == "reserve":
                if row["launch"] in reserving:
                    problems.append(f"launch {row['launch']} reserved twice")
                reserving[row["launch"]] = (key, row)
            elif kind in ("spawned", "not-spawned"):
                if outcome.get(row["launch"], {}).get("kind") in ("spawned", "not-spawned"):
                    problems.append(f"launch {row['launch']}: more than one spawn outcome")
                outcome.setdefault(row["launch"], {}).update(kind=kind, row=row, by=key)
            elif kind == "observed":
                outcome.setdefault(row["launch"], {}).setdefault("observed", []).append((key, position, row))
            elif kind == "stop":
                outcome.setdefault(row["launch"], {}).setdefault("stops", []).append((key, position, row))
            elif kind == "contained":
                outcome.setdefault(row["launch"], {}).setdefault("contained", set()).add(key)
    adopted = {(key, row["ledger"]): row for key, entry in participants.items() for row in entry["rows"]
               if row["kind"] == "adopted"}
    launches = verdict["launches"]
    explained: set[str] = set()
    unended: list[tuple[str, dict, dict]] = []
    for launch, data in reservations.items():
        state = launches.setdefault(launch, {"expect": data["expect"], "parent": data["parent"], "participants": []})
        parent = participants.get(data["parent"])
        local = reserving.get(launch)
        if parent is not None:
            if local is None or local[0] != data["parent"] or local[1]["expect"] != data["expect"]:
                problems.append(f"launch {launch}: its reservation names parent {data['parent']}, whose record does not "
                                "reserve it so")
            if parent["pid"] != data["parent_pid"]:
                problems.append(f"launch {launch}: its reservation names a parent process other than the one recorded")
        elif header["owner"] in ("gate", "routine-pytest", "guarded-pytest", "raw-pytest"):
            problems.append(f"launch {launch}: reserved by {data['parent']}, which never recorded into this ledger")
        found = by_launch.get(launch, [])
        state["participants"] = found
        result = outcome.get(launch, {})
        spawn_kind = result.get("kind")
        if spawn_kind == "not-spawned":
            state["state"] = "not-spawned"
            if found:
                problems.append(f"launch {launch}: recorded as not spawned, yet {len(found)} participant(s) claim it")
            continue
        if len(found) > 1:
            problems.append(f"launch {launch}: {len(found)} participants claim one launch (a duplicate)")
        if not found:
            parent_open = parent is not None and parent["end"] is None
            if live or (parent_open and parent["role"] in open_roles and spawn_kind is None):
                state["state"] = "pending"
                continue
            if spawn_kind is None and parent is not None:
                problems.append(f"launch {launch}: reserved, but never recorded as spawned or not spawned (unresolved)")
            else:
                problems.append(f"launch {launch} ({data['expect']}): the required child never recorded its accounting "
                                "(it failed before its first record, or never initialized)")
            state["state"] = "missing"
            continue
        child = participants[found[0]]
        state["state"] = "accounted" if child["end"] is not None else "open"
        if child["role"] not in EXPECTATIONS[data["expect"]]:
            problems.append(f"launch {launch}: expected a {data['expect']} participant, found a {child['role']}")
        if child["parent"] != data["parent"]:
            problems.append(f"launch {launch}: its participant names another parent")
        spawned = result.get("row")
        if spawn_kind == "spawned":
            problem = _identity_problem(child, spawned)
            if problem:
                problems.append(f"launch {launch}: {problem}")
        if child["end"] is not None:
            for _key, _position, row in result.get("observed", ()):
                if row["how"] not in _NO_EXIT and row["exit"] is not None and row["exit"] != child["end"]["exit"] \
                        and not _stop_explains_exit(data, child, result, _key, _position, row):
                    problems.append(f"launch {launch}: observed exit {row['exit']} but its participant reported "
                                    f"{child['end']['exit']}")
            continue
        if live or child["role"] in open_roles:
            continue
        unended.append((launch, data, child))
    # An ancestor that ended with its own end record and whose reserving parent then made a declared, successful tree stop
    # of it (the worker exited first; its Job then ended what it left behind) explains its descendants as an explained
    # stop does; it is itself accounted by its end record, never listed as an explained stop.
    ended_tree_stopped: set[str] = set()
    for launch, data in reservations.items():
        found, result = by_launch.get(launch, []), outcome.get(launch, {})
        if len(found) != 1 or participants[found[0]]["end"] is None or result.get("row") is None:
            continue
        declared = (data.get("lifecycle") or {}).get("stops", ())
        if any(writer == data["parent"] and stop["tree"] and stop["ok"] and stop["mechanism"] in declared
               and stop["pid"] in (result["row"]["pid"], participants[found[0]]["pid"])
               for writer, _position, stop in result.get("stops", ())):
            ended_tree_stopped.add(launch)
    # A descendant is explained through its ancestor's tree stop, so settle ancestors first: repeat until nothing changes.
    progressed = True
    while progressed and unended:
        progressed = False
        for item in list(unended):
            if _explained_stop(item[0], item[1], item[2], outcome, participants, explained | ended_tree_stopped) is None:
                explained.add(item[0])
                launches[item[0]]["state"] = "explained-stop"
                unended.remove(item)
                progressed = True
    for launch, data, child in unended:
        reason = _explained_stop(launch, data, child, outcome, participants, explained | ended_tree_stopped)
        launches[launch]["state"] = "unexplained-end"
        problems.append(f"launch {launch}: {child['role']} pid {child['pid']} never completed its accounting: it ended "
                        f"without its own end record, and not by an explained stop ({reason})")
    verdict["explained_stops"] = sorted(explained)
    for launch, keys in by_launch.items():
        if launch not in reservations:
            for key in keys:
                problems.append(f"participant {key} ({participants[key]['role']}) claims launch {launch}, which no reservation "
                                "in this ledger names (an orphan or foreign participant)")
    for launch, (key, row) in reserving.items():
        if row["ledger"]:
            result = outcome.get(launch, {})
            if result.get("kind") == "not-spawned":
                continue
            seen = adopted.get((key, row["ledger"]))
            if seen is None:
                if not live and participants[key]["end"] is not None:
                    problems.append(f"launch {launch}: its linked private ledger was never adopted by its parent")
            elif seen["status"] != "PASS" and seen["accounting"] == "strict":
                problems.append(f"launch {launch}: its linked private ledger is not clean")
        elif launch not in reservations:
            problems.append(f"launch {launch}: reserved in {key}'s record, with no reservation file in this ledger")
    delegated = {row["launch"] for entry in participants.values() for row in entry["rows"] if row["kind"] == "delegate"}
    profiled = {row["launch"]: (key, row) for key, entry in participants.items() for row in entry["rows"]
                if row["kind"] == "profiled"}
    for launch, (key, row) in profiled.items():
        # An exact reviewed profile runs unchanged and owes no participant: its evidence is its parent's own rows.
        if launch in reserving or launch in by_launch:
            problems.append(f"launch {launch}: a profiled launch that is also reserved or claimed by a participant")
        result = outcome.get(launch, {})
        state = launches.setdefault(launch, {"expect": None, "parent": key, "participants": [], "profile": row["profile"]})
        if result.get("kind") == "spawned":
            state["pid"], state["created"] = result["row"]["pid"], result["row"].get("created")
        if result.get("kind") == "not-spawned":
            state["state"] = "not-spawned"
        elif result.get("kind") != "spawned":
            if not live and participants[key]["end"] is not None:
                problems.append(f"launch {launch} ({row['profile']}): profiled, but never recorded as spawned or not")
            state["state"] = "unresolved"
        elif not any(observer == key for observer, _p, _r in result.get("observed", ())):
            if _leaf_gone_after_tree_stop(key, result, participants, outcome, explained):
                state["state"] = "profiled"
                continue
            parent_open = participants[key]["end"] is None
            if not live and not (parent_open and participants[key]["role"] in open_roles):
                problems.append(f"launch {launch} ({row['profile']}): its end was never observed by its parent, nor "
                                "observed gone after a tree stop of its parent's tree")
            state["state"] = "running"
        else:
            state["state"] = "profiled"
    for launch, result in outcome.items():
        if result.get("kind") and launch not in reserving and launch not in delegated and launch not in profiled:
            problems.append(f"launch {launch}: a spawn outcome for a launch nobody reserved or delegated")


def _identity_problem(child: dict, spawned: dict) -> str | None:
    """Whether the participant is the process its parent started. The same pid (and creation time where both were read)
    is the direct case. Otherwise only a Windows venv redirector stands between them: the spawned program must have been
    recorded as a redirector, the participant must be its direct child, and both must name the same venv interpreter. A
    child started through a reviewed shell form is bound by its launch and its interpreter (its parent is the shell)."""
    if child["pid"] == spawned["pid"]:
        if spawned["created"] is not None and child["created"] is not None and spawned["created"] != child["created"]:
            return f"pid {child['pid']} was reused: its creation time is not the spawned process's"
        return None
    same_program = os.path.normcase(child["executable"]) == spawned["executable"]
    if spawned["via"] == "shell":
        return None if same_program else "its participant is not the interpreter the reviewed shell form named"
    if spawned["redirector"] and child["ppid"] == spawned["pid"] and same_program:
        return None
    return (f"its participant pid {child['pid']} (ppid {child['ppid']}) is neither the spawned process {spawned['pid']} nor "
            "the interpreter of a recorded venv redirector")


#: The exit an intentional stop leaves when the stop names no code of its own (Popen.kill and taskkill /F end a Windows
#: process with 1).
_STOP_DEFAULT_CODE = {"terminate-process": 1, "taskkill": 1}


def _leaf_gone_after_tree_stop(parent: str, result: dict, participants: dict, outcome: dict, explained: set) -> bool:
    """A profiled leaf its parent never observed (the parent was stopped, or ended first and left it to its owner's Job) is
    accounted only when an ancestor of that parent observed this leaf's own process gone after the same ancestor recorded a
    successful tree stop of the parent's launch or of a launch above it on the same chain (D-R2-1's descendant rule), or --
    when the parent itself ended by an explained stop, before it could observe the leaf -- after any successful stop that
    ancestor recorded on the chain."""
    spawned = result.get("row")
    if spawned is None:
        return False
    chain, seen, key = [], set(), parent
    while key is not None and key in participants and key not in seen:
        seen.add(key)
        chain.append(key)
        key = participants[key]["parent"]
    stopped_launches = {participants[key]["launch"] for key in chain if participants[key]["launch"]}
    for observer, position, row in result.get("observed", ()):
        if observer not in chain or observer == parent or row["how"] != "gone" or row.get("pid") != spawned["pid"]:
            continue
        for launch in stopped_launches:
            for writer, stop_position, stop in outcome.get(launch, {}).get("stops", ()):
                if writer == observer and stop["ok"] and stop_position < position \
                        and (stop["tree"] or participants[parent]["launch"] in explained):
                    return True
    return False


def _stop_explains_exit(data: dict, child: dict, result: dict, observer: str, after: int, row: dict) -> bool:
    """True when an observed exit that differs from the exit a participant reported in its own end record is the code of
    an explained stop (D-R2-1) that landed after that record, before the process ended: its reservation expected the
    mechanism, its reserving parent recorded the stop for this launch's own process, successfully, before this
    observation, and the observed exit is the code that stop leaves. Everything the participant did is in its record."""
    lifecycle = data.get("lifecycle") or {"stops": [], "codes": []}
    spawned = result.get("row")
    if spawned is None:
        return False
    for writer, position, stop in result.get("stops", []):
        if stop["mechanism"] not in lifecycle["stops"] or stop["mechanism"] in _CODE_ENDS or stop["mechanism"] == "self":
            continue
        if writer != data["parent"] or not stop["ok"] or stop["pid"] not in (spawned["pid"], child["pid"]):
            continue
        if observer == writer and after <= position:
            continue  # observed before the stop was recorded: the stop explains nothing about it
        expected = stop["code"] if stop["code"] is not None else _STOP_DEFAULT_CODE.get(stop["mechanism"])
        if expected is None or row["exit"] == expected:
            return True
    return False


def _explained_stop(launch: str, data: dict, child: dict, outcome: dict, participants: dict, explained: set) -> str | None:
    """None when a participant that ended without its own end record is accounted by an explained stop (D-R2-1), else why
    not. All of: its launch was reserved, before it existed, with a lifecycle expecting this mechanism; it initialized its
    accounting; the stop's intent and action were recorded for this launch's own process, successfully, by its reserving
    parent (or, for ``self``, by itself), before the outcome was observed; the observed outcome agrees with the mechanism;
    and every required descendant is itself accounted (ended, explained, or observed gone after this tree's stop). A crash
    fixture is explained only by an observed exit among the codes its reservation declared. Nothing here waives an
    unexpected refusal or a failed accounting write: those are judged separately and stay failures."""
    lifecycle = data.get("lifecycle") or {"stops": [], "codes": []}
    ancestor = participants.get(child["parent"]) if child["parent"] else None
    if ancestor is not None and ancestor.get("launch") in explained and child["initialized"]:
        # A descendant of an explained stop: accounted when it was then observed gone (its pid and creation time no longer
        # name a live process) and that stop ended it -- a tree stop of its ancestor, or the end of an explained participant
        # whose kill-on-close Job holds it (it, or a launch above it, was placed there by that participant).
        ancestor_stops = outcome.get(ancestor["launch"], {}).get("stops", [])
        if (any(stop["tree"] and stop["ok"] for _w, _p, stop in ancestor_stops)
                or _held_by_an_ended_job(child["participant"], outcome, participants, explained)) and \
                any(row["how"] == "gone" for _k, _p, row in outcome.get(launch, {}).get("observed", ())):
            return None
    if not lifecycle["stops"]:
        return "its reservation expected a normal end"
    if not child["initialized"]:
        return "it never initialized its accounting"
    result = outcome.get(launch, {})
    spawned = result.get("row")
    if spawned is None:
        return "its spawn was never recorded"
    observed = result.get("observed", [])
    stops = result.get("stops", [])
    how = None
    if _CODE_ENDS & set(lifecycle["stops"]) and any(row["how"] == "exited" and row["exit"] in lifecycle["codes"]
                                                    for _k, _p, row in observed):
        how = "crash"
    for writer, position, stop in stops:
        if stop["mechanism"] not in lifecycle["stops"] or stop["mechanism"] in _CODE_ENDS:
            continue
        owner = child["participant"] if stop["mechanism"] == "self" else data["parent"]
        if writer != owner or not stop["ok"] or stop["pid"] not in (spawned["pid"], child["pid"]):
            continue
        expected = stop["code"] if stop["code"] is not None else _STOP_DEFAULT_CODE.get(stop["mechanism"])
        for observer, after, row in observed:
            if observer == writer and after <= position:
                continue  # written before the stop: it explains nothing (post hoc)
            if row["how"] == "exited" and (expected is None or row["exit"] == expected):
                how = "stop"
                break
        if how:
            break
    if how is None:
        if stops:
            return ("a stop was recorded, but not one its reservation expected, by its owner, for its process, successful, "
                    "and then observed with the outcome its mechanism leaves")
        return "no expected stop intent and action was recorded for it before its end was observed"
    tree = any(stop["tree"] for _w, _p, stop in stops)
    for key, entry in participants.items():
        if entry["parent"] != child["participant"] or entry["end"] is not None or entry["launch"] is None:
            continue
        if entry["launch"] in explained:
            continue
        gone = any(row["how"] == "gone" for _k, _p, row in outcome.get(entry["launch"], {}).get("observed", ()))
        held = child["participant"] in outcome.get(entry["launch"], {}).get("contained", ())
        if not ((tree or held) and gone and entry["initialized"]):
            return f"its descendant {key} is not accounted"
    return None


def _held_by_an_ended_job(key: str, outcome: dict, participants: dict, explained: set) -> bool:
    """True when this participant, or a participant above it, was placed by one of its own ancestors in that ancestor's
    kill-on-close Job (a ``contained`` row) and that ancestor ended by an explained stop: the kernel ended the Job's
    members, and children inherit membership, with it."""
    chain, seen = [], set()
    while key is not None and key in participants and key not in seen:
        seen.add(key)
        chain.append(key)
        key = participants[key]["parent"]
    for index, member in enumerate(chain):
        for holder in outcome.get(participants[member]["launch"], {}).get("contained", ()):
            if holder in chain[index + 1:] and participants[holder]["launch"] in explained:
                return True
    return False


_process_record: ProcessRecord | None = None


def _child_record(role: str) -> ProcessRecord | None:
    """The record of a process that has no routine envelope of its own (a heavyweight root refusing, an operation check). It
    carries the launch it was started for, if any; an unreserved one is a foreign participant the reader never calls clean."""
    global _process_record
    ledger = os.environ.get(LEDGER_ENV)
    if not ledger:
        return None
    if _process_record is None or _process_record.ledger != Path(ledger):
        launch = os.environ.get(LAUNCH_ENV)
        reservation = read_reservation(ledger, launch) if launch else None
        _process_record = ProcessRecord(ledger, role, launch=launch if reservation else None,
                                        parent=reservation["parent"] if reservation else None)
    return _process_record


# --------------------------------------------------------------------------- #
#  The reviewed synthetic gate fixture (format 2, Phase 1A-1 R2: positive recipes)
# --------------------------------------------------------------------------- #
#: The reviewed synthetic stand-ins. A stand-in is valid only when its bytes are exactly the recipe's source in the marked
#: checkout (never "anything that differs from the real runner": a modified or historical real backend is not a recipe), it
#: stands where the recipe may stand, and its data file validates. ``role`` is the accounting role its bootstrapped process
#: takes (a stand-in for pytest accounts as the routine pytest session its stage expects).
SYNTHETIC_RECIPES = {
    "scripted-acceptance-runner": {"source": "files/tests/routine_recipes/scripted_acceptance_runner" + _PY,
                                   "targets": (GATE + "acceptance_runner" + _PY,), "data": "scripted.json",
                                   "role": "routine-child"},
    "scenario-runner": {"source": "files/tests/routine_recipes/scenario_runner" + _PY,
                        "targets": (GATE + "scaling/qualify" + _PY,), "data": "scenario.json", "role": "routine-child"},
    "fake-pytest": {"source": "files/tests/routine_recipes/fake_pytest" + _PY, "targets": None, "data": None,
                    "role": "routine-pytest"},
}
#: The files of a synthetic tree that must be the marked checkout's own bytes wherever the tree carries them: the gate's
#: orchestrator always; its runners and the envelope they load whenever present.
SYNTHETIC_PINNED = (ORCHESTRATOR, "files/tests/routine_pytest" + _PY, "files/tests/guarded_pytest" + _PY,
                    "files/tests/routine_effects" + _PY, "files/tests/routine_child" + _PY,
                    "files/tests/routine_fixtures" + _PY, GATE + "helpers/routine_context" + _PY)


def _sha256(path) -> str | None:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return None
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _is_json_object(value) -> bool:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _valid_scripted(data, tree: Path) -> bool:
    shape = {"hang": _is_bool, "no_report": _is_bool, "exit": _is_int, "token": _is_str, "entry": _is_json_object,
             "report": _is_json_object, "after": _is_json_object,
             "registered": lambda value: type(value) is list and all(type(item) is str for item in value)}
    return _is_json_object(data) and all(key in shape and shape[key](value) for key, value in data.items())


def _valid_scenario(data, tree: Path) -> bool:
    if not _is_json_object(data) or set(data) != {"runs", "verdict", "code", "before"}:
        return False
    if not _is_int(data["runs"]) or not _is_int(data["code"]) or type(data["before"]) is not list:
        return False
    if not (data["verdict"] is None or type(data["verdict"]) is str or _is_json_object(data["verdict"])):
        return False
    outputs = {"identity.json", "runs.json", "verdict.json"}

    def inside(value) -> bool:
        return type(value) is str and os.path.isabs(value) and _within(value, tree) and not _within(tree / ".git", value) \
            and not _within(value, tree / ".git")

    for operation in data["before"]:
        if type(operation) is not list or not operation or type(operation[0]) is not str:
            return False
        kind, args = operation[0], operation[1:]
        checks = {"unlink": [lambda v: v in outputs], "write": [lambda v: v in outputs, _is_str],
                  "write-identity": [_is_str, lambda v: v is None or _is_str(v)], "write-verdict": [_is_json_object],
                  "touch": [inside], "write-path": [inside, _is_str],
                  "sleep": [lambda v: type(v) in (int, float) and 0 <= v <= 300], "sleeper": [inside]}.get(kind)
        if checks is None or len(args) != len(checks) or not all(check(arg) for check, arg in zip(checks, args)):
            return False
    return True


_RECIPE_DATA = {"scripted.json": _valid_scripted, "scenario.json": _valid_scenario}


def _marked_root(environ) -> Path | None:
    marked = environ.get(ROOT_ENV)
    return Path(marked) if marked else None


def synthetic_fixture(root, environ=None) -> dict | None:
    """The validated declaration of a synthetic gate fixture tree, or None. Valid only inside routine verification, for a tree
    inside the routine session's owned disposable roots, that neither is nor contains the marked checkout, whose declaration
    (format 2, a plain file) names this tree and only reviewed recipes at the places they may stand, and whose orchestrator,
    runners and envelope are the marked checkout's own bytes (so the boundaries it enforces are the current ones)."""
    environ = os.environ if environ is None else environ
    disposable, marked = environ.get(DISPOSABLE_ENV), _marked_root(environ)
    if not in_routine(environ) or not disposable or marked is None or not root:
        return None
    try:
        tree = Path(root)
        if not any(_within(tree, part) for part in disposable.split(os.pathsep) if part) or _within(marked, tree):
            return None
        declaration = tree / SYNTHETIC_DECLARATION
        if _sha256(declaration) is None:
            return None
        data = json.loads(declaration.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("format") != SYNTHETIC_FORMAT or _norm(data.get("root", "")) != _norm(tree):
        return None
    recipes = data.get("recipes")
    if not _is_json_object(recipes):
        return None
    for target, recipe in recipes.items():
        known = SYNTHETIC_RECIPES.get(recipe) if type(recipe) is str else None
        if known is None or known["targets"] is None or target.replace("\\", "/") not in known["targets"]:
            return None
    for relative in SYNTHETIC_PINNED:
        present = os.path.lexists(tree / relative)
        if relative == ORCHESTRATOR and not present:
            return None
        if present and (_sha256(tree / relative) is None or _sha256(tree / relative) != _sha256(marked / relative)):
            return None
    return data


def synthetic_stand_in(root, relative: str, environ=None) -> bool:
    """Whether ``relative`` in a valid synthetic fixture tree is a declared stand-in: declared there as a reviewed recipe that
    may stand at that place, byte-identical to the recipe's source in the marked checkout, with a valid data file."""
    environ = os.environ if environ is None else environ
    data = synthetic_fixture(root, environ)
    if data is None:
        return False
    key = relative.replace("\\", "/")
    recipe = {k.replace("\\", "/"): v for k, v in data["recipes"].items()}.get(key)
    known = SYNTHETIC_RECIPES.get(recipe)
    if known is None or key not in (known["targets"] or ()):
        return False
    actual = _sha256(Path(root) / key)
    if actual is None or actual != _sha256(_marked_root(environ) / known["source"]):
        return False
    if known["data"]:
        try:
            values = json.loads((Path(root) / key).with_name(known["data"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not _RECIPE_DATA[known["data"]](values, Path(root)):
            return False
    return True


def recipe_role(path, environ=None) -> str | None:
    """The accounting role of a free-standing reviewed recipe (one that stands anywhere disposable, such as the stand-in for
    pytest): its bytes are exactly the recipe's source in the marked checkout. None for anything else."""
    environ = os.environ if environ is None else environ
    marked, disposable = _marked_root(environ), environ.get(DISPOSABLE_ENV)
    if marked is None or not disposable or not in_routine(environ):
        return None
    if not any(_within(path, part) for part in disposable.split(os.pathsep) if part):
        return None
    actual = _sha256(path)
    for recipe in SYNTHETIC_RECIPES.values():
        if recipe["targets"] is None and actual is not None and actual == _sha256(marked / recipe["source"]):
            return recipe["role"]
    return None


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
        # Inside a routine verification process its own accounting (expected-refusal scope, its participant record) takes it.
        # A pytest session gets the refusal as an exception; a bootstrapped child that is itself the refusing root records it
        # and then exits like any refusing root (its end record is written at exit).
        if getattr(envelope, "_bootstrapped", None) != "routine-child":
            envelope.refuse(effect, detail, origin=origin)  # raises EffectRefused, a PermissionError
        try:
            envelope.refuse(effect, detail, origin=origin)
        except PermissionError:
            return True
    record = _child_record(role)
    row = {"effect": effect, "detail": str(detail)[:500], "origin": origin, "pid": os.getpid(), "expected": False,
           "test": os.environ.get("PYTEST_CURRENT_TEST", "child")}
    if record is None:
        return False
    try:
        record.ensure_started()
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
