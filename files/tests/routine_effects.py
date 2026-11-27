"""Routine verification restrictions, enforced at the operation (v0.8.2 Phase 1A-1, corrected in R1 and R2; plan Revision 5).

Every pytest process of this repository is a routine verification process. The supported invocation is the repository's
bootstrap -- ``routine_pytest.py`` for ordinary pytest, ``guarded_pytest.py`` for the guarded groups -- which calls
:func:`bootstrap` before pytest, its plugins, ``conftest.py`` or any test module is imported. A raw ``python -m pytest`` gets
the restrictions from ``conftest.py`` only after its plugins load, and is not verification evidence (GATE.md). Nothing here
ever grants a heavyweight effect -- not an environment variable, not running under pytest, not a flag. Admission of real
heavyweight work is Phase 1A-2's; until then :func:`admitted` is always False.

What is enforced (the shared contract -- names, launch roots, the Python command-line reading, the synthetic fixture and the
ledger -- lives in ``helpers/routine_context.py``; the reviewed bounded fixture and measurement families live in
``routine_fixtures.py``; both are loaded here by path from the marked checkout):

* **Opt-ins and overrides are scrubbed** (:func:`scrub`).
* **Operations refuse** where a Python audit event exists: external network, a model library reading real weights,
  resolving a native-input function outside the gate's adapter, desktop hand-offs (``os.startfile``), and every process
  mechanism that cannot take part in launch preparation (``os.system``, ``os.exec*``, ``os.spawn*``, a direct
  ``os.posix_spawn`` or ``_winapi.CreateProcess`` that is not the inside of an admitted ``Popen``).
* **One launch decision** (:func:`decide_launch`, side-effect free) judges the program actually started (its resolved
  executable, by the platform's own search, not ``argv[0]``), its arguments, working directory and effective environment,
  and returns exactly one of three outcomes: refuse; run through the verification-owned child bootstrap
  (``routine_child.py``: the same interpreter and options, the envelope installed before the program, its imports or a
  package initializer run); or run unchanged under an exact reviewed bounded profile. The same decision is the
  preparation (``subprocess.Popen._execute_child``, verification processes only: it reserves the child's accounting
  obligation before the process exists and rewrites a bootstrapped launch) and, through the audit hook, the final
  admission of the actual ``subprocess.Popen`` event, which must be the prepared one.
* **Accounting obligations** (ledger format 3): a launch that owes accounting is reserved before it exists; its child
  records ``start`` and its initialization before any target work and ``end`` last; this process records the spawn, any
  intentional stop it makes (``Popen.kill``/``terminate``, ``os.kill``, a reviewed ``taskkill`` of an owned pid, and the
  kernel32 job and process terminations reached through ctypes) and the observed end. A participant that ended without
  its own end record is accounted only by an explained stop the launch was reserved to expect (D-R2-1).
* **A refusal cannot be swallowed, and accounting fails closed**: ``conftest.py`` fails the test and the session for an
  unexpected refusal or an accounting failure, the bootstrap fails the process, and the gate reads every stage's ledger.

This makes accidental heavyweight execution from supported routine paths fail closed. It is a cooperating-verification
control, not an operating-system sandbox: native code, a process the envelope never prepared, or a hostile child is outside
what Python audit hooks see.
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import importlib.util
import json
import io as _io  # the original open: a test patching builtins.open never reaches it
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PY = ".py"
TESTS_DIR = REPO_ROOT / "files" / "tests"
#: This envelope's own copy of the child bootstrap (see _marked_bootstrap for the one a prepared child starts).
CHILD_BOOTSTRAP = TESTS_DIR / ("routine_child" + _PY)


def _marked_bootstrap() -> str:
    """The child bootstrap a prepared child starts: always the marked checkout's (``ACT_ROUTINE_ROOT``), by absolute path.
    A nested session in a synthetic tree runs a byte-identical copy of this envelope (its runner and envelope must be the
    marked checkout's to start at all), but its children still bind through the marked checkout's own bootstrap, whose
    envelope is the one the marker names."""
    marked = os.environ.get(ROOT_ENV)
    if marked:
        return str(Path(marked) / CHILD_BOOTSTRAP.relative_to(REPO_ROOT))
    return str(CHILD_BOOTSTRAP)


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_context():
    return _load("act_routine_context", REPO_ROOT / "files" / "dev-work" / "verification-gate" / "helpers"
                 / ("routine_context" + _PY))


context = _load_context()
_fixture_module = None


def fixtures():
    """The reviewed bounded fixture and measurement families (``routine_fixtures.py`` of the marked checkout)."""
    global _fixture_module
    if _fixture_module is None:
        _fixture_module = _load("act_routine_fixtures", TESTS_DIR / ("routine_fixtures" + _PY))
    return _fixture_module


EFFECTS = context.EFFECTS
CONTEXT_ENV, ROOT_ENV, LEDGER_ENV, DISPOSABLE_ENV = (context.CONTEXT_ENV, context.ROOT_ENV, context.LEDGER_ENV,
                                                     context.DISPOSABLE_ENV)
LAUNCH_ENV, PYTHONPATH_ENV = context.LAUNCH_ENV, context.PYTHONPATH_ENV
ROUTINE, REFUSED_EXIT, DATA_ONLY = context.ROUTINE, context.REFUSED_EXIT, context.DATA_ONLY
OPT_IN = re.compile(r"^ACT_[A-Z0-9_]*_REAL(_[A-Z0-9_]+)?$")
#: Ambient destination and executable overrides a test must never inherit (v0.8.x P2 and P1A tools).
OVERRIDES = frozenset({"ACT_P2_EVIDENCE", "ACT_XHE_PROOF_APPLE_CAF", "ACT_MAC_FFMPEG"})
POLICY_FILE = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "verification.json"
#: Data-only flags a gate entrypoint's own parser acts on before any effect, wherever they appear as a standalone token.
ANYWHERE = {context.ORCHESTRATOR: frozenset({"--plan"})}
ENGINE_ENVIRONMENTS = (".venv/engines/", ".venv-qwen3/", ".venv-omnivoice/", "files/dev-work/qwen3-eval/.venv/")
INSTALLERS = frozenset({"winget", "brew", "msiexec", "choco", "apt", "apt-get", "port", "dnf", "yum", "snap", "npm",
                        "uv", "conda", "mamba", "softwareupdate", "installer", "pip", "pip3"})
NETWORK_TOOLS = frozenset({"curl", "wget", "bitsadmin", "certutil", "ftp", "tftp", "ssh", "scp", "sftp", "nc", "ncat",
                           "telnet", "invoke-webrequest", "ping"})
DESKTOP = frozenset({"explorer", "xdg-open", "open", "rundll32", "start", "osascript", "cliclick", "shortcuts"})
MACHINE = frozenset({"reg", "setx", "schtasks", "sc", "net", "netsh", "bcdedit", "diskpart", "format", "launchctl",
                     "systemsetup", "defaults", "tccutil", "diskutil", "csrutil", "spctl", "pmset", "shutdown", "sudo"})
SHELLS = frozenset({"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "dash"})
RUNNERS = {"routine_pytest" + _PY: "routine-pytest", "guarded_pytest" + _PY: "guarded-pytest"}
#: The files a nested runner in another tree (a synthetic gate fixture's copy) must hold byte-identical to the marked
#: checkout for its own envelope to be the reviewed one.
RUNNER_SUPPORT = ("files/tests/routine_effects" + _PY, "files/tests/routine_child" + _PY,
                  "files/tests/routine_fixtures" + _PY,
                  "files/dev-work/verification-gate/helpers/routine_context" + _PY)
_PYTHON = re.compile(r"^(python|pythonw)(\d+(\.\d+)*)?w?$")
_SCRIPT = re.compile(r"\.(py|pyw|bat|cmd|command|ps1|sh)$", re.IGNORECASE)
WEIGHTS = (".pt", ".pth", ".safetensors", ".onnx", ".ckpt", ".gguf")
#: Libraries whose reading of a weight file is model initialization (their Python-level reads).
MODEL_LIBRARIES = ("torch", "transformers", "huggingface_hub", "safetensors", "onnxruntime", "kokoro", "chatterbox",
                   "diffusers", "accelerate", "qwen_tts", "omnivoice", "spacy", "thinc", "librosa")
NATIVE_INPUT = frozenset({"SendInput", "keybd_event", "mouse_event", "SetCursorPos", "CGEventPost", "CGEventPostToPid",
                          "BlockInput"})
#: The gate's own native-input adapter checks its operation itself (routine_context.check_operation) before it sends input.
NATIVE_INPUT_OWNER = "files/dev-work/verification-gate/adapters/windows/native_input" + _PY
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", None, ""})
#: Startup customization a child's environment may not carry into a bootstrapped launch (unless -E/-I make the
#: interpreter ignore it). PYTHONPATH is moved past the envelope instead (PYTHONPATH_ENV); PYTHONSTARTUP is read only by
#: an interactive interpreter, which is never prepared, and is admitted only naming a disposable path.
STARTUP_REFUSED = ("PYTHONHOME", "PYTHONINSPECT", "PYTHONEXECUTABLE", "PYTHONPLATLIBDIR", "PYTHONUSERBASE",
                   "PYTHONSAFEPATH_UNSUPPORTED")
#: The pinned CPython 3.12 ``Popen._execute_child`` parameters the preparation boundary is written against.
_EXECUTE_CHILD = ("self", "args", "executable", "preexec_fn", "close_fds", "pass_fds", "cwd", "env", "startupinfo",
                  "creationflags", "shell", "p2cread", "p2cwrite", "c2pread", "c2pwrite", "errread", "errwrite")
_EXECUTE_TAIL = ("restore_signals", "gid", "gids", "uid", "umask", "start_new_session", "process_group")


class EffectRefused(PermissionError):
    """A heavyweight effect asked for in routine verification. Refused before the operation; recorded either way."""


_lock = threading.RLock()
_local = threading.local()
_refusals: list[dict] = []
_accounting_failures: list[str] = []
_disposable_roots: list[str] = []
_installed = False
_bootstrapped: str | None = None
_record = None
_table: dict | None = None
_real_digests: dict[str, str] | None = None
_profile_authority = None
_boundary_problem: str | None = None
#: launch -> _Launch, for this process's own prepared launches.
_launches: dict[str, "_Launch"] = {}
#: Process-wide termination expectations (a test's marker): launches prepared while one is open are reserved with it.
_stop_scopes: list[dict] = []
#: Report-mode adopted ledgers a test must examine; an unexamined unclean one is an accounting failure.
_pending_reports: list = []
#: The runner that created this process's ledger (a direct run), or None when the ledger belongs to the gate or a parent.
ledger_owner: str | None = None


# --------------------------------------------------------------------------- #
#  The environment and the operation checks
# --------------------------------------------------------------------------- #
def scrub(environ=None) -> list[str]:
    """Remove ambient real-engine opt-ins and destination/executable overrides. Returns the names removed."""
    environ = os.environ if environ is None else environ
    removed = sorted(name for name in list(environ) if OPT_IN.match(name.upper()) or name.upper() in OVERRIDES)
    for name in removed:
        environ.pop(name, None)
    return removed


def admitted(effect: str) -> bool:
    """Whether this process may perform ``effect`` for real. Always False in Phase 1A-1: admission is Phase 1A-2's."""
    _check(effect)
    return False


def require(effect: str, detail: str):
    """Call immediately before a real heavyweight operation. Refuses (and records the refusal) unless admitted."""
    _check(effect)
    if admitted(effect):  # pragma: no cover - unreachable until Phase 1A-2
        return
    refuse(effect, detail, origin="declared boundary")


def refuse(effect: str, detail: str, *, origin: str):
    _record_refusal({"effect": effect, "detail": str(detail)[:500], "origin": origin, "pid": os.getpid(),
                     "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session")})
    raise EffectRefused(f"refused in routine verification: {effect}: {detail} (needs a Phase 1A-2 admission; GATE.md)")


def _check(effect: str) -> None:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}; the vocabulary is {sorted(EFFECTS)}")


def _scopes() -> list:
    if not hasattr(_local, "scopes"):
        _local.scopes = []
    return _local.scopes


def _record_refusal(row: dict) -> None:
    scopes = _scopes()
    row["expected"] = bool(scopes) and scopes[-1].allows(row["effect"])
    with _lock:
        _refusals.append(row)
        record = _record
    if record is None:
        _accounting_failure(f"a refusal ({row['effect']}) with no effect ledger to record it in")
        return
    try:
        record.refusal(row)
    except context.LedgerError as exc:
        _accounting_failure(str(exc))


def _accounting_failure(problem: str) -> None:
    with _lock:
        _accounting_failures.append(problem[:300])
        record = _record
    if record is not None:
        record.failed.append(problem[:300])


def refusals() -> list[dict]:
    with _lock:
        return [dict(row) for row in _refusals]


def unexpected() -> list[dict]:
    return [row for row in refusals() if not row.get("expected")]


def accounting_failures() -> list[str]:
    with _lock:
        return list(_accounting_failures)


# --------------------------------------------------------------------------- #
#  Scopes: expected refusals with private ledgers, adoption, and expected termination
# --------------------------------------------------------------------------- #
class _Examined(dict):
    """The verdicts of a report-mode scope's adopted ledgers. Reading one marks it examined; an unclean verdict nobody read
    is an accounting failure when the test ends (accounting="report" never turns unexamined evidence into success)."""

    def __init__(self) -> None:
        super().__init__()
        self.examined = False

    def _mark(self):
        self.examined = True

    def __getitem__(self, key):
        self._mark()
        return super().__getitem__(key)

    def get(self, *args):
        self._mark()
        return super().get(*args)

    def values(self):
        self._mark()
        return super().values()

    def items(self):
        self._mark()
        return super().items()

    def __iter__(self):
        self._mark()
        return super().__iter__()


class _Scope:
    def __init__(self, effects, accounting: str) -> None:
        self.effects = frozenset(effects)
        self.accounting = accounting
        self.adopted: list[str] = []
        self.ledgers = _Examined()

    def allows(self, effect: str) -> bool:
        return not self.effects or effect in self.effects


@contextlib.contextmanager
def expected_refusals(*effects: str, accounting: str = "strict"):
    """For the synthetic negative controls of these mechanisms only: refusals of ``effects`` (any effect when none is named)
    made on this thread inside the block are recorded as expected. It grants nothing -- the operation is still refused --
    and a refusal on another thread, or of another effect, stays unexpected.

    A child started on this thread inside the block may be given a private ledger (initialized with :func:`new_ledger`,
    inside the session's disposable root): the launch is linked to it before it exists, and when the block ends the ledger
    is adopted -- read, its refusals of the named effects counted as expected and anything else recorded here as
    unexpected. An unclean private ledger is an accounting failure; ``accounting="report"`` hands the verdict to the test
    (``scope.ledgers``), which must examine it."""
    for effect in effects:
        _check(effect)
    if accounting not in ("strict", "report"):
        raise ValueError("accounting is 'strict' or 'report'")
    scope = _Scope(effects, accounting)
    _scopes().append(scope)
    try:
        yield scope
    finally:
        _scopes().remove(scope)
        observe_children()
        _adopt(scope, escalate=lambda row: not scope.allows(row.get("effect")))


def _adopt(scope: _Scope, *, escalate) -> None:
    for path in scope.adopted:
        verdict = context.read_ledger(path)
        dict.__setitem__(scope.ledgers, path, verdict)
        for row in verdict["refusals"]:
            if not row.get("expected") and escalate(row):
                escalated = {key: row.get(key) for key in ("effect", "detail", "origin", "pid")}
                escalated["origin"] = f"adopted ledger: {escalated.get('origin')}"
                _record_refusal(escalated)
        try:
            if _record is not None:
                # The adoption judges the ledger's accounting; its refusals were escalated into this record above.
                _record.adopted(path, status="FAIL" if verdict["problems"] else "PASS", accounting=scope.accounting)
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
        # Refusals were escalated above; whether the adopted ledger is clean is judged by its accounting problems.
        if verdict["problems"]:
            if scope.accounting == "strict":
                _accounting_failure(f"an adopted child ledger is not clean: {'; '.join(verdict['problems'][:3])}")
            else:
                with _lock:
                    _pending_reports.append((scope.ledgers, path))


def check_reports() -> list[str]:
    """Report-mode verdicts no test examined (called when a test ends): each is an accounting failure."""
    with _lock:
        pending, _pending_reports[:] = list(_pending_reports), []
    problems = [f"an unclean adopted ledger was never examined by its test ({os.path.basename(path)})"
                for ledgers, path in pending if not ledgers.examined]
    for problem in problems:
        _accounting_failure(problem)
    return problems


@contextlib.contextmanager
def adopting_ledgers():
    """For a test that drives the gate in-process against a synthetic fixture on this thread: the gate owns and judges its
    stages' own ledgers (delegated stage launches made on this thread are adopted when the block ends), and any unexpected
    refusal recorded in them still counts here. No refusal is expected; completeness is the gate's own verdict."""
    scope = _Scope({"<none>"}, "report")
    scope.delegating = True
    _scopes().append(scope)
    try:
        yield scope
    finally:
        _scopes().remove(scope)
        observe_children()
        _adopt(scope, escalate=lambda row: True)
        scope.ledgers.examined = True  # the gate judged completeness itself


@contextlib.contextmanager
def expected_termination(*stops: str, codes=()):
    """The lifecycle a test's launches are reserved to expect (D-R2-1): launches prepared while this is open (on any thread:
    production code starts its workers from its own threads) may end by one of ``stops`` -- recorded by their owner as an
    intent and action and then observed with the outcome the mechanism leaves -- instead of a normal end of their own. A
    crash fixture names ``native-crash`` and the exit ``codes`` it may end with. It explains nothing by itself, after the
    fact or for a launch made before it opened, and never waives a refusal or an accounting failure."""
    lifecycle = {"stops": sorted(set(stops)), "codes": sorted({int(code) for code in codes})}
    context._lifecycle(lifecycle)  # validates the vocabulary
    with _lock:
        _stop_scopes.append(lifecycle)
    try:
        yield lifecycle
    finally:
        observe_children()
        with _lock:
            _stop_scopes.remove(lifecycle)


def new_ledger(path, owner: str = "test") -> Path:
    """Initialize a private ledger directory for a synthetic control's child (see :func:`expected_refusals`)."""
    return context.init_ledger(path, owner=owner)


def read_ledger(path, **kwargs) -> dict:
    return context.read_ledger(path, **kwargs)


def ledger_refusals(path) -> list[dict]:
    """The refusal rows of a ledger directory (for tests); its verdict is :func:`read_ledger`."""
    return context.read_ledger(path)["refusals"]


# --------------------------------------------------------------------------- #
#  Launch facts: the program actually started
# --------------------------------------------------------------------------- #
def _load_table() -> dict:
    global _table
    if _table is None:
        try:
            table = json.loads(POLICY_FILE.read_text(encoding="utf-8")).get("entrypoints", {})
            _table = {key.lower(): value for key, value in table.items() if key != "about" and isinstance(value, dict)}
        except (OSError, ValueError, AttributeError):
            _table = {}  # fail closed: every launch-root entry is refused
    return _table


def _digest(path) -> str | None:
    try:
        with _io.open(path, "rb") as handle:
            data = handle.read(32 << 20)
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


def _real_entrypoints() -> dict[str, str]:
    """The SHA-256 of every launch-root file of this checkout -> its relative path: a renamed copy is still that entrypoint."""
    global _real_digests
    if _real_digests is None:
        found: dict[str, str] = {}
        for root in context.LAUNCH_ROOTS:
            base = REPO_ROOT / root
            paths = [base] if not root.endswith("/") else [p for p in base.rglob("*") if p.is_file() and _SCRIPT.search(p.name)]
            for path in paths:
                if "__pycache__" in path.parts or not path.is_file():
                    continue
                digest = _digest(path)
                if digest:
                    found.setdefault(digest, path.relative_to(REPO_ROOT).as_posix())
        _real_digests = found
    return _real_digests


def _argv(command) -> list[str]:
    if isinstance(command, (bytes, bytearray)):
        command = command.decode("utf-8", "replace")
    if isinstance(command, str):
        if os.name == "nt":
            return _windows_split(command)
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()
    if isinstance(command, os.PathLike):
        return [os.fspath(command)]
    return [os.fsdecode(part) if isinstance(part, (bytes, os.PathLike)) else str(part) for part in command]


def _windows_split(command: str) -> list[str]:
    """CommandLineToArgvW's reading of a command line, as the started program sees it."""
    import ctypes

    argc = ctypes.c_int()
    split = ctypes.WinDLL("shell32").CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = split(command, ctypes.byref(argc))
    if not pointer:
        return command.split()
    try:
        return [pointer[i] for i in range(argc.value)]
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(pointer)


def _windows_dirs() -> list[str]:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return [os.path.join(root, "System32"), os.path.join(root, "System"), root]


def _search(text: str, *, cwd, env) -> str | None:
    """The file the platform starts for ``text`` (``argv[0]`` or ``executable=``), by its own search, or None.

    Windows (CreateProcess with no application name): a name with a directory is taken relative to this process's own
    working directory; a bare name is searched in the starting program's folder, this process's working directory, the
    system folders and then this process's PATH; ``.exe`` is appended when the name has no extension. POSIX: a name
    without ``/`` is searched on the child's PATH (``os.get_exec_path``), as ``_posixsubprocess`` does."""
    text = text.strip('"')
    if not text:
        return None
    if os.name == "nt":
        name = text if os.path.splitext(text)[1] else text + ".exe"
        if os.path.dirname(text) or os.path.isabs(text):
            candidate = name if os.path.isabs(name) else os.path.join(os.getcwd(), name)
            return os.path.abspath(candidate) if os.path.lexists(candidate) else None
        starts = [os.path.dirname(getattr(sys, "_base_executable", sys.executable) or sys.executable),
                  os.path.dirname(sys.executable), os.getcwd(), *_windows_dirs()]
        starts += [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
        for folder in starts:
            candidate = os.path.join(folder.strip('"'), name)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return None
    if "/" in text:
        base = os.fspath(cwd) if cwd else os.getcwd()
        candidate = text if os.path.isabs(text) else os.path.join(base, text)
        return os.path.abspath(candidate) if os.path.lexists(candidate) else None
    path_value = None
    if env is not None:
        path_value = next((value for key, value in env.items() if str(key) == "PATH"), None)
    found = shutil.which(text, path=path_value if path_value is not None else os.environ.get("PATH"))
    return os.path.abspath(found) if found else None


def _stem(path_or_name: str) -> str:
    base = os.path.basename(path_or_name).lower()
    for suffix in (".exe", ".com"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _resolve(text: str, cwd) -> str:
    text = text.strip("\"'")
    base = os.fspath(cwd) if cwd else os.getcwd()
    path = text if os.path.isabs(text) else os.path.join(base, text)
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return path


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def disposable(path) -> bool:
    """Whether ``path`` lies inside this session's owned disposable roots (its basetemp, and the roots a reserved launch
    was given)."""
    try:
        folded = _norm(path)
    except (OSError, ValueError, TypeError):
        return False
    with _lock:
        roots = list(_disposable_roots)
    return any(folded == root or folded.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _inside_repo(path: str) -> bool:
    return _norm(path).startswith(_norm(REPO_ROOT) + os.sep)


def _same_bytes(path, reference) -> bool:
    a, b = _digest(path), _digest(reference)
    return a is not None and a == b


def trusted_interpreters() -> set[str]:
    found = set()
    for path in (sys.executable, getattr(sys, "_base_executable", "")):
        if path:
            found.add(_norm(path))
            folder, name = os.path.split(path)
            if name.lower() == "python.exe":
                found.add(_norm(os.path.join(folder, "pythonw.exe")))
    return found


def interpreter_kind(program: str) -> str | None:
    """``trusted`` (this session's interpreter, its base, their pythonw), ``copy`` (a disposable venv made from the trusted
    base, or a disposable copy of a trusted interpreter's bytes), ``engine`` (an engine environment's interpreter) or None
    (not an interpreter this session may run)."""
    if not program:
        return None
    folded = _norm(program)
    if folded in trusted_interpreters():
        return "trusted"
    slashed = folded.replace("\\", "/")
    if any("/" + environment in slashed for environment in ENGINE_ENVIRONMENTS) and not disposable(program):
        return "engine"
    if not disposable(program) or not os.path.isfile(program):
        return None
    references = [path for path in (sys.executable, getattr(sys, "_base_executable", "")) if path]
    if any(_same_bytes(program, reference) for reference in references):
        config = Path(program).parent.parent / "pyvenv.cfg"
        if not config.exists():
            config = Path(program).parent / "pyvenv.cfg"
        if config.exists():
            try:
                home = next((line.split("=", 1)[1].strip() for line in config.read_text(encoding="utf-8").splitlines()
                             if line.split("=", 1)[0].strip().lower() == "home"), "")
            except OSError:
                return None
            base = os.path.dirname(getattr(sys, "_base_executable", "") or sys.executable)
            return "copy" if home and _norm(home) == _norm(base) else None
        return "copy"
    return None


def is_redirector(program: str) -> bool:
    """A Windows venv ``python.exe``: a launcher whose interpreter is its direct child (``pyvenv.cfg`` one folder up)."""
    if os.name != "nt" or not program:
        return False
    path = Path(program)
    base = getattr(sys, "_base_executable", "") or ""
    return (path.parent.parent / "pyvenv.cfg").is_file() and _norm(program) != _norm(base) and \
        path.name.lower() in ("python.exe", "pythonw.exe")


# --------------------------------------------------------------------------- #
#  The launch decision
# --------------------------------------------------------------------------- #
REFUSE, BOOTSTRAP, PROFILE = "refuse", "bootstrap", "profile"


@dataclass(frozen=True)
class LaunchDecision:
    """One launch, decided. ``outcome`` is refuse, bootstrap (through ``routine_child.py``) or profile (unchanged, under the
    exact reviewed profile ``profile``). ``expect`` is the accounting obligation the launch owes (a participant role a
    reservation expects) or None; ``ledger`` a linked private ledger; ``delegated`` a gate-bound stage launch."""

    outcome: str
    reason: str
    effect: str | None = None
    profile: str | None = None
    expect: str | None = None
    program: str = ""
    argv: tuple = ()
    cwd: str = ""
    python: object = None
    ledger: str | None = None
    delegated: str | None = None
    redirector: bool = False
    via: str = "direct"
    keep_pythonpath: bool = False
    stops: tuple = ()
    lifecycle: dict | None = None
    env_patch: tuple = ()
    #: "network-guard" for a reviewed worker network-guard measurement (D-R2-7): recorded in the reservation, so the child's
    #: envelope defers its network refusal behind the program's own guard (it still refuses whatever that guard lets by).
    measurement: str | None = None

    @property
    def refused(self) -> bool:
        return self.outcome == REFUSE


_MP_DECISION = None


def _refusal(effect: str, reason: str, **facts) -> LaunchDecision:
    return LaunchDecision(REFUSE, reason, effect=effect, **facts)


def _env_view(env) -> dict:
    source = os.environ if env is None else env
    view = {}
    for key, value in source.items():
        key = os.fsdecode(key) if isinstance(key, bytes) else str(key)
        view[key.upper() if os.name == "nt" else key] = os.fsdecode(value) if isinstance(value, bytes) else str(value)
    return view


def _thread_scope():
    scopes = _scopes()
    return scopes[-1] if scopes else None


def _ledger_problem(view: dict) -> tuple[str | None, str | None, str | None]:
    """(problem, linked private ledger, delegated launch) of a child environment's ledger and launch identity."""
    ours, theirs = os.environ.get(LEDGER_ENV), view.get(LEDGER_ENV)
    launch = view.get(LAUNCH_ENV)
    delegated = getattr(_local, "delegated", {})
    if launch:
        bound = delegated.get(launch)
        if bound is None or os.path.normcase(bound) != os.path.normcase(theirs or ""):
            return "its environment carries a launch identity this process never bound to it", None, None
        return None, None, launch
    if ours and theirs == ours:
        return None, None, None
    if not ours:
        return "this process has no effect ledger to account for the child in", None, None
    scope = _thread_scope()
    if theirs and scope is not None and not getattr(scope, "delegating", False) and disposable(theirs) \
            and os.path.isfile(os.path.join(theirs, context.LEDGER_HEADER)):
        return None, theirs, None
    return "its environment replaces or drops the effect ledger", None, None


def _context_problem(view: dict) -> str | None:
    if view.get(CONTEXT_ENV) != ROUTINE:
        return "its environment drops the routine marker"
    if os.path.normcase(view.get(ROOT_ENV, "")) != os.path.normcase(os.environ.get(ROOT_ENV, "")):
        return "its environment changes the marked checkout"
    if any(OPT_IN.match(key.upper()) or key.upper() in OVERRIDES for key in view):
        return "its environment re-adds a real-engine opt-in or override"
    theirs = view.get(DISPOSABLE_ENV)
    if theirs and any(not disposable(part) for part in theirs.split(os.pathsep) if part):
        return "its environment widens the disposable roots"
    return None


def _startup_problem(view: dict, command) -> str | None:
    """Unreviewed startup customization a bootstrapped child would run before its envelope."""
    if command.ignores_environment:
        return None
    for name in STARTUP_REFUSED:
        if view.get(name):
            return f"its environment sets {name} (startup customization)"
    # PYTHONSTARTUP is read only by an interactive interpreter; a prepared launch never is one (-i, stdin programs and
    # interactive forms are refused as unsupported), so it is inert here and stays as the caller set it.
    for entry in (view.get("PYTHONPATH") or "").split(os.pathsep):
        if entry and any(os.path.exists(os.path.join(entry, name)) for name in ("sitecustomize.py", "usercustomize.py")):
            return "its PYTHONPATH holds a sitecustomize or usercustomize that would run before the envelope"
    return None


def _module_file(module: str, cwd, view) -> str | None:
    """Where ``python -m module`` finds ``module`` among the working directory and the child's PYTHONPATH."""
    if not module or not re.fullmatch(r"[A-Za-z_][\w.]*", module):
        return None
    roots = [os.fspath(cwd) if cwd else os.getcwd()]
    roots += [part for part in str(view.get("PYTHONPATH", "")).split(os.pathsep) if part]
    relative = module.replace(".", os.sep)
    for root in roots:
        for candidate in (os.path.join(root, relative + _PY), os.path.join(root, relative, "__main__" + _PY)):
            if os.path.isfile(candidate):
                return os.path.realpath(candidate)
    return None


def _code_targets(code: str) -> str | None:
    """A launch-root file named by a path literal in inline code (``runpy.run_path(".../acceptance_runner.py")``)."""
    text = code.replace("\\\\", "/").replace("\\", "/")
    for root in context.LAUNCH_ROOTS:
        if not root.endswith("/") and root.split("/")[-1] and re.search(re.escape(root) + r"\b", text, re.IGNORECASE):
            return root
    return None


def _target(path: str, args, *, command=None, argv=(), program="") -> LaunchDecision | None:
    """The verdict on starting the launch-root script ``path`` (resolved); None when it is no launch root."""
    role = context.launch_role(path)
    relative = role[2] if role else None
    if role is None:
        known = _real_entrypoints().get(_digest(path) or "")
        if known and context.launch_role(known) is not None:
            return _refusal(context.launch_role(known)[1], f"a renamed copy of the heavyweight entrypoint {known}")
        return None
    entry = _load_table().get(relative.lower()) or {}
    disposition = entry.get("routine", "refused")
    if disposition == "bounded":
        return LaunchDecision(BOOTSTRAP, f"a reviewed bounded entrypoint ({relative})", expect="routine-child")
    data_only = entry.get("data_only", []) if disposition == "data-only" else ()
    if context.data_only_shape(list(args), data_only, ANYWHERE.get(relative, ())):
        return LaunchDecision(BOOTSTRAP, f"a data-only invocation of {relative}", expect="routine-child")
    tree = _tree_of(path, relative)
    if relative == context.ORCHESTRATOR and tree is not None:
        if disposable(tree) and context.synthetic_fixture(tree) is not None:
            return LaunchDecision(BOOTSTRAP, "the orchestrator of a reviewed synthetic gate fixture", expect="routine-child")
    if tree is not None and disposable(tree) and context.synthetic_stand_in(tree, relative):
        return LaunchDecision(BOOTSTRAP, f"a reviewed synthetic stand-in ({relative})", expect="routine-child")
    effects = entry.get("effects") or [role[1]]
    where = "this checkout" if _inside_repo(path) else "another checkout or a copy"
    return _refusal(effects[0], f"a heavyweight entrypoint ({relative}, in {where}; {entry.get('class', 'unclassified')})")


def _tree_of(path: str, relative: str) -> Path | None:
    """The checkout a launch-root file lies in: its path with the root's relative path removed."""
    real = Path(os.path.realpath(path))
    depth = len(Path(relative).parts)
    if len(real.parts) <= depth or [part.lower() for part in real.parts[-depth:]] != \
            [part.lower() for part in Path(relative).parts]:
        return None
    return real.parents[depth - 1]


def _caller_facts(caller) -> dict:
    if not caller:
        return {"file": "", "function": ""}
    return {"file": os.path.normcase(os.path.abspath(caller[0])), "function": caller[1]}


def facts_for(argv, program, cwd, view, caller, command=None) -> dict:
    """What a reviewed fixture family recognizer is shown: the launch as it would actually start, and (in a bootstrapped
    child) the program this child itself runs."""
    return {"argv": list(argv), "program": program, "name": _stem(program or (argv[0] if argv else "")),
            "cwd": os.fspath(cwd) if cwd else os.getcwd(), "env": view, "caller": _caller_facts(caller),
            "python": command, "marked": REPO_ROOT, "disposable": disposable, "interpreter_kind": interpreter_kind,
            "owned_pids": owned_pids(), "same_bytes": _same_bytes, "child": _child_target}


#: The guarded runner's profiles that are not exact: a Python child they approve still runs through the bootstrap.
GENERIC_GUARDED_PROFILES = frozenset({"reviewed-python-probe-or-worker", "disposable-script-worker",
                                      "synthetic-process-lifetime-negative-control"})
_child_target: tuple | None = None
_MP_DECISION = LaunchDecision(BOOTSTRAP, "a multiprocessing spawn child", expect="routine-child", via="multiprocessing")


def owned_pids() -> dict[int, str]:
    with _lock:
        return {launch.pid: launch.launch for launch in _launches.values() if launch.pid}


def decide_launch(command, cwd=None, *, executable=None, env=None, shell: bool = False, caller=None) -> LaunchDecision:
    """The one launch decision (side-effect free). ``executable`` is the program actually started when given; ``env`` a
    replacement environment (None: inherited); ``caller`` the (file, function) that asked for the launch."""
    argv = _argv(command)
    if shell:
        text = command if isinstance(command, str) else " ".join(argv)
        if os.name == "nt":
            comspec = os.environ.get("ComSpec") or os.path.join(_windows_dirs()[0], "cmd.exe")
            argv, executable = [comspec, "/c", text], executable or comspec
        else:
            argv = [executable or "/bin/sh", "-c", text]
    if not argv:
        return _refusal("install", "an empty command")
    program = _search(os.fspath(executable) if executable else argv[0], cwd=cwd, env=env) or ""
    name = _stem(program or argv[0])
    cwd_text = os.fspath(cwd) if cwd else os.getcwd()
    view = _env_view(env)
    common = {"program": program, "argv": tuple(argv), "cwd": cwd_text}
    requested = os.fspath(executable) if executable else argv[0]
    if name in ("pip", "pip3") and "install" in argv[1:] and "--no-index" not in argv[1:]:
        return _refusal("external-network", f"an online pip install: {' '.join(argv[:4])}", **common)
    if name in INSTALLERS:
        return _refusal("install", f"a package manager or installer: {' '.join(argv[:4])}", **common)
    if name in NETWORK_TOOLS and not disposable(program or ""):
        return _refusal("external-network", f"a network tool: {' '.join(argv[:3])}", **common)
    if name in DESKTOP:
        return _refusal("native-desktop", f"a desktop hand-off: {' '.join(argv[:3])}", **common)
    if name in MACHINE:
        return _refusal("install", f"a machine configuration program: {' '.join(argv[:3])}", **common)
    command_line = context.parse_python(argv[1:]) if _PYTHON.match(name) else None
    reviewed = fixtures().recognize(facts_for(argv, program, cwd_text, view, caller, command_line))
    if reviewed is not None and reviewed.get("outcome", PROFILE) != BOOTSTRAP and env is not None \
            and not reviewed.get("leaf") and not reviewed.get("scrubbed"):
        # A replacement environment must keep the envelope for a profiled program too (it carries the marker, the
        # marked checkout and the ledger into whatever the program starts). A "scrubbed" profile is an exact reviewed
        # worker whose own six-name environment is its production contract (D-R2-9): its family checked it exactly.
        problem = _context_problem(view) or _ledger_problem(view)[0]
        if problem:
            return _refusal("real-app-launch", f"a reviewed program ({reviewed['profile']}): {problem}", **common)
    if reviewed is not None:
        if reviewed.get("outcome", PROFILE) == BOOTSTRAP:
            return _decide_python(argv, program, cwd_text, view, command_line, common, reviewed=reviewed,
                                  requested=requested)
        return LaunchDecision(PROFILE, reviewed["reason"], profile=reviewed["profile"], expect=reviewed.get("expect"),
                              lifecycle=reviewed.get("lifecycle"), stops=tuple(reviewed.get("stops", ())),
                              env_patch=tuple(sorted((reviewed.get("env_patch") or {}).items())),
                              python=command_line, redirector=is_redirector(program), **common)
    authority = _profile_authority
    if authority is not None:
        granted = authority(list(argv), cwd_text, view)
        if granted and granted not in GENERIC_GUARDED_PROFILES:
            return LaunchDecision(PROFILE, f"the guarded runner's reviewed profile {granted}", profile=str(granted),
                                  python=command_line, redirector=is_redirector(program), **common)
    if command_line is not None:
        return _decide_python(argv, program, cwd_text, view, command_line, common, requested=requested)
    if name in SHELLS:
        return _refusal("install", f"an unreviewed {name} invocation ({' '.join(argv[:4])[:160]}); shells run only in "
                                   "reviewed fixture forms", **common)
    if _SCRIPT.search(program or argv[0]):
        role = context.launch_role(program or argv[0])
        if role is not None:
            return _refusal(role[1], f"a heavyweight entrypoint started as a program ({role[2]})", **common)
        return _refusal("install", f"an unreviewed script program ({os.path.basename(program or argv[0])})", **common)
    role = context.launch_role(program) if program else None
    if role is not None:
        return _refusal(role[1], f"a heavyweight entrypoint started as a program ({role[2]})", **common)
    if not program:
        return LaunchDecision(PROFILE, "a program that does not exist: starting it fails, as the control expects",
                              profile="missing-program", **common)
    return _refusal("install", f"an unclassified native program ({program}); only reviewed bounded families run", **common)


def _engine_text(text: str) -> bool:
    """Whether a path, as written or resolved, names an interpreter of a real engine environment."""
    folded = "/" + re.sub(r"^(\./)+", "", os.fspath(text).replace("\\", "/").lower()).lstrip("/")
    return any("/" + environment in folded for environment in ENGINE_ENVIRONMENTS)


def _decide_python(argv, program, cwd, view, command, common, *, reviewed=None, requested=None) -> LaunchDecision:
    kind = interpreter_kind(program)
    requested = requested or argv[0]
    if kind is None and _engine_text(requested) and not disposable(program or requested):
        kind = "engine"
    if kind is None and not program:
        return LaunchDecision(PROFILE, "an interpreter that does not exist: starting it fails, as the control expects",
                              profile="missing-program", **common)
    common = {**common, "python": command, "redirector": is_redirector(program)}
    if kind == "engine":
        return _refusal("real-engine", f"an interpreter of a real engine environment ({program})", **common)
    if kind is None:
        return _refusal("install", f"an interpreter this session does not trust ({program or argv[0]})", **common)
    if command.mode == "info":
        return LaunchDecision(PROFILE, "a version or help request: runs nothing", profile="python-info", **common)
    if command.mode in ("stdin", "unsupported"):
        return _refusal("real-app-launch", f"a Python child in an unsupported form ({command.problem or 'a program read '
                                                                                      'from standard input'})", **common)
    lowered = [token.lower() for token in argv]
    if command.mode == "module" and command.target in ("pip", "pip3") and "install" in lowered and "--no-index" not in lowered:
        return _refusal("external-network", "an online pip install (no --no-index)", **common)
    if command.mode == "module" and command.target in ("pytest", "py.test"):
        return _refusal("real-app-launch", "a nested pytest outside the routine bootstrap (use routine_pytest.py)", **common)
    if command.mode == "code" and "pytest.main(" in command.target:
        return _refusal("real-app-launch", "a nested pytest outside the routine bootstrap (use routine_pytest.py)", **common)
    target = None
    if command.mode == "script":
        script = _resolve(command.target, cwd)
        base = os.path.basename(script).lower()
        if base in RUNNERS:
            return _nested_runner(script, base, common, view)
        if base in ("pytest", "py.test"):
            return _refusal("real-app-launch", "a nested pytest outside the routine bootstrap", **common)
        target = _target(script, command.rest, command=command, argv=argv, program=program)
    elif command.mode == "module":
        found = _module_file(command.target, cwd, view)
        if found:
            target = _target(found, command.rest, command=command, argv=argv, program=program)
    else:
        named = _code_targets(command.target)
        if named:
            return _refusal(context.LAUNCH_ROOTS[named], f"inline code that runs the heavyweight entrypoint {named}", **common)
    if target is not None and target.refused:
        return LaunchDecision(REFUSE, target.reason, effect=target.effect, **common)
    problem = _context_problem(view) or (None if reviewed and reviewed.get("keep_pythonpath")
                                         else _startup_problem(view, command))
    if problem:
        return _refusal("real-app-launch", f"a Python child: {problem}", **common)
    problem, ledger, delegated = _ledger_problem(view)
    if problem:
        return _refusal("real-app-launch", f"a Python child: {problem}", **common)
    reason = target.reason if target is not None else "an effect-capable Python child"
    if reviewed is not None:
        return LaunchDecision(BOOTSTRAP, reviewed["reason"], profile=reviewed["profile"], expect="routine-child",
                              ledger=ledger, delegated=delegated, keep_pythonpath=bool(reviewed.get("keep_pythonpath")),
                              measurement=reviewed.get("measurement"), **common)
    return LaunchDecision(BOOTSTRAP, reason, expect="routine-child", ledger=ledger, delegated=delegated, **common)


def _nested_runner(script: str, base: str, common, view: dict) -> LaunchDecision:
    """A genuine nested verification session: its own early bootstrap, one participant, one terminal writer. Genuine only
    when the runner and the envelope it loads are byte-identical to the marked checkout's."""
    tree = Path(script).parents[2]
    relative = "files/tests/" + base
    files = [relative, *RUNNER_SUPPORT] + (["files/tests/write_tripwire" + _PY] if base == "guarded_pytest" + _PY else [])
    for item in files:
        if not _same_bytes(tree / item, REPO_ROOT / item):
            return _refusal("real-app-launch", f"a nested {base} whose runner or envelope ({item}) is not the marked "
                                               "checkout's", **common)
    problem = _context_problem(view)
    ledger = delegated = None
    if problem is None:
        problem, ledger, delegated = _ledger_problem(view)
    if problem:
        return _refusal("real-app-launch", f"a nested {base}: {problem}", **common)
    return LaunchDecision(PROFILE, f"a nested verification session ({base})", profile="nested-verification",
                          expect=RUNNERS[base], ledger=ledger, delegated=delegated, **common)


def classify_launch(command, cwd=None, *, executable=None, env=None, caller=None) -> tuple[str, str] | None:
    """``(effect, why)`` when routine verification refuses this launch, else None (it bootstraps or runs under a reviewed
    profile). A view of :func:`decide_launch` for callers and controls that only need the refusal."""
    decision = decide_launch(command, cwd, executable=executable, env=env, caller=caller)
    return (decision.effect, decision.reason) if decision.refused else None


# --------------------------------------------------------------------------- #
#  Preparation: subprocess.Popen._execute_child (verification processes only)
# --------------------------------------------------------------------------- #
@dataclass
class _Launch:
    launch: str
    decision: LaunchDecision
    record: object
    pid: int | None = None
    handle: int | None = None
    popen: object = None
    done: bool = False
    stopped: bool = False
    #: A stop was recorded whose descendants are still to be observed (set by every stop, also one recorded after the
    #: launch had ended: the worker exited first and its Job then ended what it left behind).
    descendants_pending: bool = False


@dataclass
class _Prepared:
    decision: LaunchDecision
    launch: str | None
    args: object
    executable: object
    env: object
    shell: bool
    admitted: bool = False
    extra: dict = field(default_factory=dict)


def prepared_original():
    """``(args, cwd, env)`` as the caller asked for the launch being prepared on this thread, or None. The guarded runner
    judges its reviewed callsite profiles on these, not on the bootstrap form the launch is rewritten to."""
    pending = getattr(_local, "pending", None)
    return None if pending is None else pending.extra.get("original")


def _caller() -> tuple[str, str] | None:
    frame = sys._getframe(2)
    skip = {os.path.normcase(os.path.abspath(__file__)), os.path.normcase(getattr(__import__("subprocess"), "__file__", ""))}
    while frame is not None:
        filename = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
        if filename not in skip:
            return frame.f_code.co_filename, frame.f_code.co_name
        frame = frame.f_back
    return None


def _child_env(env, decision: LaunchDecision, launch: str | None) -> dict:
    view = dict(os.environ) if env is None else {os.fsdecode(k) if isinstance(k, bytes) else str(k):
                                                  os.fsdecode(v) if isinstance(v, bytes) else str(v) for k, v in env.items()}

    def setvar(name: str, value: str | None) -> None:
        for key in [key for key in view if key.upper() == name.upper()] if os.name == "nt" else [name]:
            view.pop(key, None)
        if value is not None:
            view[name] = value

    if launch is not None:
        setvar(LAUNCH_ENV, launch)
    with _lock:
        roots = list(_disposable_roots)
    if decision.outcome == BOOTSTRAP:
        setvar(DISPOSABLE_ENV, os.pathsep.join(roots) if roots else None)
        if not decision.python.ignores_environment and not decision.keep_pythonpath:
            current = next((value for key, value in view.items()
                            if (key.upper() if os.name == "nt" else key) == "PYTHONPATH"), None)
            setvar("PYTHONPATH", None)
            setvar(PYTHONPATH_ENV, current)
    return view


def _bootstrap_argv(decision: LaunchDecision) -> list[str]:
    command = decision.python
    return [decision.argv[0], *command.flags, _marked_bootstrap(), command.mode, command.target, *command.rest]


def _lifecycle_now(decision: LaunchDecision) -> dict | None:
    if decision.lifecycle:
        return decision.lifecycle
    with _lock:
        scopes = list(_stop_scopes)
    if not scopes:
        return None
    stops = sorted({stop for scope in scopes for stop in scope["stops"]})
    codes = sorted({code for scope in scopes for code in scope["codes"]})
    return {"stops": stops, "codes": codes}


def _identity_of(decision: LaunchDecision) -> str:
    return context.launch_identity(decision.argv[1:])


def _prepare(decision: LaunchDecision, args, executable, env, shell: bool) -> _Prepared:
    """Reserve the obligation (before the process exists) and build the launch actually made."""
    launch = None
    if decision.outcome == PROFILE and decision.expect is None:
        record = _record
        if record is not None:
            launch = context.new_launch()
            record.profiled(launch, profile=decision.profile or "profile", identity=_identity_of(decision))
        final_env = env
        if decision.env_patch:
            final_env = _child_env(env, decision, None)
            for key, value in decision.env_patch:
                for existing in [name for name in final_env if name.upper() == key.upper()]:
                    final_env.pop(existing)
                final_env[key] = value
        return _Prepared(decision, launch, args, executable, final_env, shell)
    if decision.expect is not None:
        record = _record
        if record is None:
            raise context.LedgerError("this process has no effect ledger in which to reserve its child's accounting")
        if decision.delegated is not None:
            launch = decision.delegated
            record.delegate(launch, os.environ.get(LEDGER_ENV) if decision.ledger is None else decision.ledger)
        else:
            launch = context.new_launch()
            with _lock:
                roots = list(_disposable_roots)
            record.reserve(launch, expect=decision.expect, identity=_identity_of(decision),
                           target_ledger=decision.ledger, roots=roots, lifecycle=_lifecycle_now(decision),
                           note=decision.reason, measurement=decision.measurement or "")
            if decision.ledger is not None:
                scope = _thread_scope()
                if scope is not None and decision.ledger not in scope.adopted:
                    scope.adopted.append(decision.ledger)
    elif decision.delegated is not None:
        launch = decision.delegated
    if decision.delegated is not None:
        scope = _thread_scope()
        ledger = _env_view(env).get(LEDGER_ENV)
        if scope is not None and getattr(scope, "delegating", False) and ledger and ledger not in scope.adopted:
            scope.adopted.append(ledger)
    if decision.outcome == BOOTSTRAP:
        final_args = _bootstrap_argv(decision)
        final_env = _child_env(env, decision, launch)
        return _Prepared(decision, launch, final_args, executable, final_env, False)
    final_env = env if launch is None else _child_env(env, decision, launch)
    return _Prepared(decision, launch, args, executable, final_env, shell)


def _record_stop_intents(decision: LaunchDecision) -> None:
    for pid, tree in decision.stops:
        _stop_pid(pid, mechanism="taskkill", code=1, tree=tree, ok=True)


def _prepared_execute_child(self, args, executable, preexec_fn, close_fds, pass_fds, cwd, env, startupinfo, creationflags,
                            shell, *rest):
    if _boundary_problem:
        refuse("real-app-launch", f"the launch boundary is unavailable: {_boundary_problem}", origin="subprocess.Popen")
    decision = decide_launch(args, cwd, executable=executable, env=env, shell=bool(shell), caller=_caller())
    if decision.refused:
        refuse(decision.effect, decision.reason, origin="subprocess.Popen")
    try:
        prepared = _prepare(decision, args, executable, env, bool(shell))
    except (context.LedgerError, OSError) as exc:
        _accounting_failure(f"a launch could not be reserved, so it was not started: {exc}")
        refuse("real-app-launch", f"its accounting obligation could not be established ({exc})", origin="subprocess.Popen")
    _record_stop_intents(decision)
    prepared.extra["original"] = (args, cwd, env)
    _local.pending = prepared
    try:
        _original_execute_child(self, prepared.args, prepared.executable, preexec_fn, close_fds, pass_fds, cwd,
                                prepared.env, startupinfo, creationflags, prepared.shell, *rest)
    except BaseException as exc:
        if prepared.launch is not None and _record is not None and decision.delegated is None:
            created = getattr(self, "_child_created", False)
            try:
                if created and getattr(self, "pid", None):
                    _record.spawned(prepared.launch, self.pid, executable=decision.program,
                                    redirector=decision.redirector, via=decision.via)
                elif isinstance(exc, OSError) or not created:
                    _record.not_spawned(prepared.launch, f"{type(exc).__name__}: {exc}")
            except context.LedgerError as error:
                _accounting_failure(str(error))
        raise
    finally:
        _local.pending = None
    _after_spawn(self, prepared)


def _after_spawn(popen, prepared: _Prepared) -> None:
    decision = prepared.decision
    if prepared.launch is None:
        return
    handle = _duplicate(popen)
    created = context.process_created(popen.pid) if os.name == "nt" else None
    entry = _Launch(prepared.launch, decision, _record, pid=popen.pid, handle=handle, popen=weakref.ref(popen))
    with _lock:
        _launches[prepared.launch] = entry
    try:
        popen._act_launch = prepared.launch
    except AttributeError:
        pass
    if decision.delegated is not None:
        return  # the gate that reserved the stage launch records its spawn and outcome in the stage ledger
    try:
        _record.spawned(prepared.launch, popen.pid, executable=decision.program, redirector=decision.redirector,
                        via=decision.via, created=created)
    except context.LedgerError as exc:
        # The process exists: the obligation stays (an unresolved launch is never clean) and its owner keeps it.
        _accounting_failure(f"the spawn of a reserved launch could not be recorded: {exc}")


def _duplicate(popen) -> int | None:
    if os.name != "nt":
        return None
    try:
        import _winapi

        current = _winapi.GetCurrentProcess()
        return _winapi.DuplicateHandle(current, int(popen._handle), current, 0x00100000 | 0x1000, False, 0)
    except (OSError, AttributeError, TypeError):
        return None


_original_execute_child = None
_original_methods: dict = {}


def _install_boundary() -> None:
    """Wrap ``subprocess.Popen._execute_child`` (and the termination methods, to record intentional stops) in this
    verification process, after checking that the pinned CPython interface is the one this was written against. A different
    interface fails closed: every launch is then refused."""
    global _original_execute_child, _boundary_problem
    import inspect
    import subprocess

    if _original_execute_child is not None:
        return
    original = subprocess.Popen._execute_child
    try:
        names = tuple(inspect.signature(original).parameters)
    except (TypeError, ValueError):
        names = ()
    tail = tuple(name.removeprefix("unused_") for name in names[len(_EXECUTE_CHILD):])
    if names[:len(_EXECUTE_CHILD)] != _EXECUTE_CHILD or tail != _EXECUTE_TAIL:
        _boundary_problem = f"subprocess.Popen._execute_child has an unreviewed interface {names}"
    _original_execute_child = original
    subprocess.Popen._execute_child = _prepared_execute_child
    for method in ("kill", "terminate", "send_signal"):
        _original_methods[method] = getattr(subprocess.Popen, method)
    subprocess.Popen.kill = _stopping("kill")
    subprocess.Popen.terminate = _stopping("terminate")
    subprocess.Popen.send_signal = _stopping("send_signal")
    _install_native_stops()
    _install_multiprocessing()


def _install_multiprocessing() -> None:
    """Multiprocessing ``spawn`` children start through the bootstrap too (D-R2-4), preserving spawn semantics: the same
    interpreter and options, ``spawn_main`` run as ``-c`` in the child's ``__main__``, the parent's main module prepared as
    ``__mp_main__``. ``Popen.__init__`` copies the environment itself, so the launch identity travels on the command line
    (``@<launch>`` before the bootstrap's program); everything else is the reservation's, as for any launch."""
    # Lazily (R2 recovery): importing multiprocessing.spawn pulls in socket, select, selectors and multiprocessing itself, so
    # an eager import would change the module set of every bootstrapped child (an import-footprint measurement sees it).
    # The wrapper is applied when the program itself loads those modules (now, if it already has), through a meta-path
    # finder that patches each module right after it executes. A launch that escaped it would still be refused: its
    # process creation is not a prepared one.
    for name in _MP_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            _mp_loaded(name, module)
    if not any(isinstance(finder, _MultiprocessingFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _MultiprocessingFinder())


_MP_POPEN = ("multiprocessing.popen_spawn_win32",) if os.name == "nt" else \
    ("multiprocessing.popen_spawn_posix", "multiprocessing.popen_forkserver")
_MP_MODULES = ("multiprocessing.spawn", *_MP_POPEN)


class _MultiprocessingFinder:
    """Finds nothing itself: for the multiprocessing modules the wrapper patches, it returns the spec the other finders
    give, with a loader that patches the module right after it executes."""

    def find_spec(self, name, path=None, target=None):
        if name not in _MP_MODULES:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                break
        else:
            return None
        if spec.loader is not None and hasattr(spec.loader, "exec_module"):
            spec.loader = _PatchingLoader(spec.loader, name)
        return spec


class _PatchingLoader:
    def __init__(self, loader, name: str) -> None:
        self._loader, self._name = loader, name

    def create_module(self, spec):
        return self._loader.create_module(spec)

    def exec_module(self, module) -> None:
        self._loader.exec_module(module)
        _mp_loaded(self._name, module)

    def __getattr__(self, attribute):
        return getattr(self._loader, attribute)


def _mp_loaded(name: str, module) -> None:
    if name == "multiprocessing.spawn":
        _patch_spawn(module)
    elif name in _MP_POPEN and hasattr(module, "Popen"):
        _wrap_mp_popen(module.Popen)


def _patch_spawn(spawn) -> None:
    if getattr(spawn.get_command_line, "_act_prepared", False):
        return
    original_command = spawn.get_command_line

    def get_command_line(**kwds):
        command = original_command(**kwds)
        launch = getattr(_local, "mp_launch", None)
        if launch is None:
            return command
        prepared = [command[0], *[item for item in command[1:command.index("-c")]], _marked_bootstrap(), "@" + launch,
                    "code", *command[command.index("-c") + 1:]]
        reserve = getattr(_local, "mp_reserve", None)
        try:
            reserve(context.launch_identity(command[1:]))
        except (context.LedgerError, OSError) as exc:
            _accounting_failure(f"a multiprocessing launch could not be reserved, so it was not started: {exc}")
            refuse("real-app-launch", f"its accounting obligation could not be established ({exc})",
                   origin="multiprocessing")
        _local.mp_reserved = True
        return prepared

    get_command_line._act_prepared = True
    spawn.get_command_line = get_command_line


def _wrap_mp_popen(cls) -> None:
    method = "__init__" if os.name == "nt" else "_launch"
    original = getattr(cls, method)
    if getattr(original, "_act_prepared", False):
        return

    def launch(self, process_obj):
        record = _record
        if record is None:
            refuse("real-app-launch", "a multiprocessing child with no effect ledger to account for it in",
                   origin="multiprocessing")
        token = context.new_launch()
        with _lock:
            roots = list(_disposable_roots)
        _local.mp_launch, _local.mp_identity = token, None
        _local.native_pending = {"used": False}
        reserved = False
        try:
            # The identity is the unprepared command line; it is known only once get_command_line ran, so the reservation
            # is written from inside it -- before the process exists (see reserve_mp below).
            _local.mp_reserve = lambda identity: record.reserve(token, expect="routine-child", identity=identity,
                                                                roots=roots, lifecycle=_lifecycle_now(_MP_DECISION),
                                                                note="a multiprocessing spawn child")
            original(self, process_obj)
            reserved = True
        except BaseException as exc:
            if getattr(_local, "mp_reserved", False):
                try:
                    if getattr(self, "pid", None):
                        record.spawned(token, self.pid, executable=_norm(sys.executable), via="multiprocessing")
                    else:
                        record.not_spawned(token, f"{type(exc).__name__}: {exc}")
                except context.LedgerError as error:
                    _accounting_failure(str(error))
            raise
        finally:
            _local.mp_launch = _local.mp_reserve = None
            _local.native_pending = None
            was_reserved, _local.mp_reserved = getattr(_local, "mp_reserved", False), False
        if reserved and was_reserved:
            created = context.process_created(self.pid) if os.name == "nt" else None
            try:
                record.spawned(token, self.pid, executable=_norm(getattr(sys, "_base_executable", sys.executable)),
                               via="multiprocessing", created=created)
            except context.LedgerError as exc:
                _accounting_failure(f"the spawn of a reserved launch could not be recorded: {exc}")
            handle = None
            if os.name == "nt":
                try:
                    import _winapi

                    current = _winapi.GetCurrentProcess()
                    handle = _winapi.DuplicateHandle(current, int(self._handle), current, 0x00100000 | 0x1000, False, 0)
                except (OSError, AttributeError, TypeError):
                    handle = None
            with _lock:
                _launches[token] = _Launch(token, _MP_DECISION, record, pid=self.pid, handle=handle)

    launch._act_prepared = True
    setattr(cls, method, launch)


def _stopping(method: str):
    original = _original_methods[method]

    def stop(self, *args):
        launch = getattr(self, "_act_launch", None)
        running = self.returncode is None
        ok = True
        try:
            return original(self, *args)
        except BaseException:
            ok = False
            raise
        finally:
            if launch is not None and running:
                if os.name == "nt":
                    code = 1
                else:
                    import signal

                    number = {"kill": signal.SIGKILL, "terminate": signal.SIGTERM}.get(method) or int(args[0])
                    code = -int(number)
                if method == "send_signal" and args and os.name == "nt":
                    import signal

                    code = None if int(args[0]) in (getattr(signal, "CTRL_C_EVENT", -1),
                                                    getattr(signal, "CTRL_BREAK_EVENT", -1)) else 1
                if not (method == "send_signal" and code is None):
                    _stop_launch(launch, mechanism="terminate-process", code=code, tree=False, ok=ok)

    stop.__name__ = method
    stop.__qualname__ = f"Popen.{method}"
    return stop


def _stop_launch(launch: str, *, mechanism: str, code, tree: bool, ok: bool) -> None:
    with _lock:
        entry = _launches.get(launch)
    if entry is None or entry.record is None or entry.pid is None:
        return
    try:
        entry.record.stop(launch, mechanism=mechanism, pid=entry.pid, code=code, tree=tree, ok=ok)
        entry.stopped = True
        entry.descendants_pending = True
    except context.LedgerError as exc:
        _accounting_failure(str(exc))


def _stop_pid(pid: int, *, mechanism: str, code, tree: bool, ok: bool) -> None:
    launch = owned_pids().get(int(pid))
    if launch is not None:
        _stop_launch(launch, mechanism=mechanism, code=code, tree=tree, ok=ok)


# --------------------------------------------------------------------------- #
#  Intentional stops through ctypes kernel32 (verification processes only)
# --------------------------------------------------------------------------- #
_WATCHED_NATIVE = frozenset({"TerminateJobObject", "TerminateProcess", "CloseHandle", "AssignProcessToJobObject"})
_jobs: dict[int, set[str]] = {}


class _NativeStop:
    """A kernel32 function a verification process calls through ctypes, recording the intentional stops it makes of this
    process's own launches. Attributes (argtypes, restype, errcheck) pass through to the real function."""

    __slots__ = ("_function", "_name")

    def __init__(self, function, name: str) -> None:
        object.__setattr__(self, "_function", function)
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attribute):
        return getattr(self._function, attribute)

    def __setattr__(self, attribute, value):
        setattr(self._function, attribute, value)

    def __call__(self, *args):
        name = self._name
        if name == "CloseHandle" and args:
            members = _job_members(args[0], closing=True)
            result = self._function(*args)
            if members:
                for launch in members:
                    _stop_launch(launch, mechanism="close-job", code=None, tree=True, ok=bool(result))
            return result
        result = self._function(*args)
        try:
            if name == "AssignProcessToJobObject" and len(args) >= 2 and result:
                pid = _pid_of(args[1])
                launch = owned_pids().get(pid) if pid else None
                if launch is not None:
                    with _lock:
                        _jobs.setdefault(_handle_value(args[0]), set()).add(launch)
                        entry = _launches.get(launch)
                    if entry is not None and entry.record is not None and _kill_on_close(_handle_value(args[0])):
                        try:
                            entry.record.contained(launch)  # this process's end now ends that launch's tree (D-R2-1)
                        except context.LedgerError as exc:
                            _accounting_failure(str(exc))  # never absorbed by the recording guard below
            elif name == "TerminateJobObject" and len(args) >= 2:
                with _lock:
                    members = set(_jobs.get(_handle_value(args[0]), ()))
                for launch in members:
                    _stop_launch(launch, mechanism="terminate-job", code=_int(args[1]), tree=True, ok=bool(result))
            elif name == "TerminateProcess" and len(args) >= 2:
                pid = _pid_of(args[0])
                if pid:
                    _stop_pid(pid, mechanism="terminate-process", code=_int(args[1]), tree=False, ok=bool(result))
        except Exception:  # noqa: BLE001 - recording never changes what the real call did
            pass
        return result


def _int(value):
    try:
        return int(getattr(value, "value", value)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def _handle_value(handle) -> int:
    value = getattr(handle, "value", handle)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pid_of(handle) -> int | None:
    try:
        import ctypes

        get = ctypes.WinDLL("kernel32").GetProcessId
        get.argtypes = [ctypes.c_void_p]
        get.restype = ctypes.c_ulong
        return int(get(_handle_value(handle))) or None
    except (OSError, AttributeError):
        return None


def _job_members(handle, *, closing: bool) -> set[str]:
    value = _handle_value(handle)
    with _lock:
        members = _jobs.pop(value, set()) if closing else set(_jobs.get(value, ()))
    if not members or not closing:
        return members
    return members if _kill_on_close(value) else set()  # only a kill-on-close job ends its processes when its handle closes


def _kill_on_close(value: int) -> bool:
    """Whether the Job behind this handle ends its members when its last handle closes (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)."""
    try:
        import ctypes

        class Basic(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION, exactly: a larger buffer is ERROR_BAD_LENGTH
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        query = ctypes.WinDLL("kernel32").QueryInformationJobObject
        query.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        info = Basic()
        return bool(query(value, 2, ctypes.byref(info), ctypes.sizeof(info), None) and info.LimitFlags & 0x2000)
    except (OSError, AttributeError):
        return False


class _NativeLaunch:
    """``CreateProcessAsUserW`` in a verification process (D-R2-4): only the reviewed Low-integrity launches of
    ``containment.spawn_low`` (routine_fixtures.native_launch_reviewed) start, each recorded as a profiled launch with its
    spawn and, through its process handle, its observed end. Labels and ledger permissions are never widened: a Low child
    cannot write the ledger, so it owes no participant -- its evidence is this parent's."""

    __slots__ = ("_function",)

    def __init__(self, function) -> None:
        object.__setattr__(self, "_function", function)

    def __getattr__(self, attribute):
        return getattr(self._function, attribute)

    def __setattr__(self, attribute, value):
        setattr(self._function, attribute, value)

    def __call__(self, *args):
        frames = _caller_frames()
        command = getattr(args[2], "value", None) if len(args) > 2 else None
        cwd = args[8] if len(args) > 8 else None
        argv = _windows_split(command) if isinstance(command, str) else []
        profile = fixtures().native_launch_reviewed(argv, cwd, frames, disposable) if cwd else None
        if profile is None:
            refuse("real-app-launch", "a native process launch outside the reviewed Low-integrity profile",
                   origin="CreateProcessAsUserW")
        launch, record = context.new_launch(), _record
        if record is None:
            refuse("real-app-launch", "a native launch with no effect ledger to record it in", origin="CreateProcessAsUserW")
        try:
            record.profiled(launch, profile=profile, identity=context.launch_identity(argv[1:]))
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
            refuse("real-app-launch", f"its evidence could not be recorded ({exc})", origin="CreateProcessAsUserW")
        result = self._function(*args)
        info = getattr(args[-1], "_obj", None)
        pid = int(getattr(info, "dwProcessId", 0) or 0)
        try:
            if result and pid:
                created = context.process_created(pid)
                record.spawned(launch, pid, executable=_norm(argv[0]) if argv else "", via="native", created=created)
                entry = _Launch(launch, LaunchDecision(PROFILE, "low-integrity", profile=profile), record, pid=pid,
                                handle=_open_process(pid))
                with _lock:
                    _launches[launch] = entry
            else:
                record.not_spawned(launch, "CreateProcessAsUserW failed")
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
        return result


def _open_process(pid: int):
    try:
        import _winapi

        return _winapi.OpenProcess(0x00100000 | 0x1000, False, pid)
    except OSError:
        return None


def _install_native_stops() -> None:
    if os.name != "nt":
        return
    import ctypes

    if getattr(ctypes.CDLL.__getitem__, "_act_watched", False):
        return
    original = ctypes.CDLL.__getitem__

    def getitem(self, name_or_ordinal):
        function = original(self, name_or_ordinal)
        library = os.path.basename(str(getattr(self, "_name", "") or "")).lower()
        if name_or_ordinal in _WATCHED_NATIVE and library in ("kernel32", "kernel32.dll"):
            return _NativeStop(function, name_or_ordinal)
        if name_or_ordinal == "CreateProcessAsUserW" and library in ("advapi32", "advapi32.dll"):
            return _NativeLaunch(function)
        return function

    getitem._act_watched = True
    ctypes.CDLL.__getitem__ = getitem


# --------------------------------------------------------------------------- #
#  Observation of this process's own launches (no extra threads)
# --------------------------------------------------------------------------- #
def observe_children(*, wait: float = 0.0) -> None:
    """Record the actual end of every launch this process prepared that has ended, independently of whether its caller read
    its return code, and release the handle kept for it. ``wait`` bounds a final wait for launches still running."""
    import time

    deadline = time.monotonic() + wait
    with _lock:
        pending = [entry for entry in _launches.values() if not entry.done]
    for entry in pending:
        status = _poll(entry, max(0.0, deadline - time.monotonic()) if wait else 0.0)
        if status is None and not wait:
            continue
        exit_status, how = status if status is not None else (None, "running")
        if how == "running" and not wait:
            continue
        entry.done = how != "running"
        if entry.decision.delegated is None and entry.record is not None:
            try:
                entry.record.observed(entry.launch, exit_status=exit_status, how=how, pid=entry.pid)
            except context.LedgerError as exc:
                _accounting_failure(str(exc))
        _release(entry)
    with _lock:
        tree_stops = [entry for entry in _launches.values() if entry.done and entry.descendants_pending]
    if tree_stops and _observe_descendants(tree_stops) or wait:
        for entry in tree_stops:
            entry.descendants_pending = False  # all seen gone (or this is the final look): not looked at again


def _poll(entry: _Launch, wait: float):
    """(exit status, how) of a launch, or None while it runs."""
    if os.name == "nt":
        if entry.handle is None:
            popen = entry.popen() if entry.popen else None
            if popen is not None and popen.returncode is not None:
                return popen.returncode, "exited"
            return (None, "unobservable") if popen is None else None
        import _winapi

        result = _winapi.WaitForSingleObject(entry.handle, int(wait * 1000))
        if result != _winapi.WAIT_OBJECT_0:
            return None
        return _winapi.GetExitCodeProcess(entry.handle), "exited"
    try:
        info = os.waitid(os.P_PID, entry.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        popen = entry.popen() if entry.popen else None
        code = popen.returncode if popen is not None else None
        return (code, "exited") if code is not None else (None, "reaped-by-owner")
    if info is None:
        return None
    code = info.si_status if info.si_code == os.CLD_EXITED else -info.si_status
    return code, "exited"


def _release(entry: _Launch) -> None:
    if entry.done and entry.handle is not None:
        try:
            import _winapi

            _winapi.CloseHandle(entry.handle)
        except OSError:
            pass
        entry.handle = None


def _observe_descendants(stopped) -> bool:
    """After a stop of an owned launch: each initialized descendant participant that never ended, and each profiled leaf of
    that tree its parent never observed, is observed gone (its recorded pid and creation time no longer name a live
    process) or still running. True when none was still running."""
    ledger = os.environ.get(LEDGER_ENV)
    if not ledger or _record is None:
        return True
    all_gone = True
    verdict = context.read_ledger(ledger, live=True)
    participants = verdict["participants"]
    roots = {key for key, entry in participants.items() if entry.get("launch") in {item.launch for item in stopped}}
    frontier = set(roots)
    while frontier:
        found = {key for key, entry in participants.items() if entry.get("parent") in frontier and key not in roots}
        roots |= found
        frontier = found
    for key in roots:
        entry = participants[key]
        if entry.get("end") is not None or entry.get("launch") in {item.launch for item in stopped}:
            continue
        created = context.process_created(entry["pid"]) if os.name == "nt" else None
        alive = created is not None and created == entry.get("created")
        all_gone = all_gone and not alive
        try:
            _record.observed(entry["launch"], exit_status=None, how="running" if alive else "gone", pid=entry["pid"])
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
    # The profiled leaves those participants made and never observed (they were stopped first, or ended and left the leaf
    # to the Job): each is observed by its own spawned pid and creation time, gone or still running.
    for launch, state in verdict["launches"].items():
        if not state.get("profile") or state.get("parent") not in roots or state.get("state") != "running" \
                or "pid" not in state:
            continue
        created = context.process_created(state["pid"]) if os.name == "nt" else None
        alive = created is not None and (state.get("created") is None or created == state.get("created"))
        all_gone = all_gone and not alive
        try:
            _record.observed(launch, exit_status=None, how="running" if alive else "gone", pid=state["pid"])
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
    return all_gone


# --------------------------------------------------------------------------- #
#  The audit hook: operations, and the final admission of every launch
# --------------------------------------------------------------------------- #
#: D-R2-7: whether this bootstrapped child runs a reviewed network-guard measurement (from its reservation), and whether its
#: deferred network hook has been appended yet.
_network = {"deferred": False, "late": False}


def _defer_network() -> None:
    _network["deferred"] = True


def _late_network(event: str, args) -> None:
    """The envelope's network refusal, deferred behind the measured program's own guard (D-R2-7)."""
    if event.startswith("socket."):
        target = _external(event, args)
        if target is not None:
            refuse("external-network", f"{event} to {target[:120]} (not refused by the measured guard)", origin=event)


def _external(event: str, args) -> str | None:
    """The non-loopback network target of a socket audit event, or None."""
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event in ("socket.connect", "socket.sendto", "socket.bind"):
        address = args[1]
        if not isinstance(address, tuple):
            return None  # an AF_UNIX path or a raw address family the hook cannot judge
        host = address[0] if address else None
    else:
        return None
    if isinstance(host, (bytes, bytearray)):
        host = host.decode("ascii", "replace")
    return None if host in LOOPBACK else str(host)


def _model_loader() -> str | None:
    frame = sys._getframe(2)
    while frame is not None:
        folded = frame.f_code.co_filename.replace("\\", "/").lower()
        for library in MODEL_LIBRARIES:
            if f"/site-packages/{library}/" in folded:
                return library
        frame = frame.f_back
    return None


def _caller_is(relative: str) -> bool:
    frame = sys._getframe(2)
    target = os.path.normcase(str(REPO_ROOT / relative))
    while frame is not None:
        if os.path.normcase(frame.f_code.co_filename) == target:
            return True
        frame = frame.f_back
    return False


def _admit_popen(args) -> None:
    """The final admission of a ``subprocess.Popen`` event: it must be the launch this thread prepared, exactly."""
    executable, command, cwd, env = args[0], args[1], args[2], args[3]
    pending = getattr(_local, "pending", None)
    if pending is None:
        decision = decide_launch(command, cwd, executable=executable, env=env)
        if decision.outcome == PROFILE and decision.expect is None and not decision.stops:
            return  # a reviewed bounded program that owes nothing, reached without the wrapper
        refuse(decision.effect or "real-app-launch", "a launch that did not pass the preparation boundary: "
               + (decision.reason if decision.refused else "it owes accounting it never reserved"), origin="subprocess.Popen")
    if pending.admitted:
        refuse("real-app-launch", "a second launch inside one prepared invocation", origin="subprocess.Popen")
    if pending.env is not None and env is not pending.env:
        refuse("real-app-launch", "the launch is not the prepared one (its environment differs)", origin="subprocess.Popen")
    if _argv(command)[1:] != [str(part) for part in _argv(pending.args)][1:] and not pending.shell:
        refuse("real-app-launch", "the launch is not the prepared one (its arguments differ)", origin="subprocess.Popen")
    pending.admitted = True


def _audit(event: str, args) -> None:
    if event == "open":
        path = args[0]
        if isinstance(path, str) and path.lower().endswith(WEIGHTS):
            mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
            if not any(flag in mode for flag in "wax+") and not disposable(path) and _model_loader():
                refuse("real-engine", f"a model library reading real weights ({os.path.basename(path)})", origin=event)
        return
    if event.startswith("socket."):
        target = _external(event, args)
        if target is not None:
            if _network["deferred"]:
                # D-R2-7: a reviewed worker network-guard measurement. Appended now, the last hook runs for this event
                # (and every later one) after every hook the program installed before it, its guard included; it refuses
                # whatever that guard let through, before anything resolves or connects.
                if not _network["late"]:
                    _network["late"] = True
                    sys.addaudithook(_late_network)
                return
            refuse("external-network", f"{event} to {target[:120]}", origin=event)
        return
    if event == "ctypes.dlsym":
        name = args[1] if len(args) > 1 else None
        if isinstance(name, str) and name in NATIVE_INPUT and not _caller_is(NATIVE_INPUT_OWNER):
            refuse("native-desktop", f"resolving the native input function {name}", origin=event)
        if isinstance(name, str) and name.startswith(("CreateProcessAsUser", "CreateProcessWithToken", "CreateProcessW",
                                                      "CreateProcessA", "CreateProcessInternal", "NtCreateUserProcess",
                                                      "ShellExecute", "WinExec")):
            if not fixtures().native_resolution_reviewed(name, _caller_frames()):
                refuse("real-app-launch", f"resolving the native process launch {name} outside a reviewed boundary",
                       origin=event)
        return
    if event == "os.kill":
        pid, signal_number = (int(args[0]), int(args[1])) if len(args) >= 2 else (0, 0)
        if pid == os.getpid() and signal_number:
            launch = getattr(_record, "launch", None)
            if launch and _record is not None:
                try:
                    _record.stop(launch, mechanism="self", pid=pid, code=signal_number if os.name == "nt" else None,
                                 tree=False, ok=True)
                except context.LedgerError as exc:
                    _accounting_failure(str(exc))
        elif signal_number:
            _stop_pid(pid, mechanism="terminate-process", code=signal_number if os.name == "nt" else None, tree=False,
                      ok=True)
        return
    if event == "subprocess.Popen":
        _admit_popen(args)
        return
    if event in ("_winapi.CreateProcess", "os.posix_spawn"):
        pending = getattr(_local, "pending", None)
        if pending is not None and pending.admitted:
            return  # the platform launch implementing the admitted Popen: one invocation, one obligation
        helper = getattr(_local, "native_pending", None)
        if helper is not None and not helper.get("used"):
            helper["used"] = True
            return  # a reviewed helper prepared exactly this launch (routine_fixtures)
        refuse("real-app-launch", f"{event} outside a prepared launch (a process mechanism that cannot take part in "
                                  "launch preparation)", origin=event)
    if event in ("os.fork", "os.forkpty"):
        refuse("real-app-launch", f"{event}: a forked copy of a verification process cannot keep its own accounting",
               origin=event)
    if event == "os.startfile":
        refuse("native-desktop", f"os.startfile({str(args[0])[:200]!r}) hands a file to the desktop", origin=event)
    if event in ("os.system", "os.exec", "os.spawn"):
        effect = "real-app-launch"
        try:
            words = _argv(args[0]) if event == "os.system" else [os.fsdecode(args[0])]
            first = _stem(words[0]) if words else ""
            effect = ("install" if first in INSTALLERS else "external-network" if first in NETWORK_TOOLS
                      else "native-desktop" if first in DESKTOP else effect)
        except (TypeError, ValueError, IndexError):
            pass
        refuse(effect, f"{event}: a process mechanism that cannot take part in launch preparation", origin=event)


def _caller_frames() -> list[tuple[str, str]]:
    frames, frame = [], sys._getframe(2)
    while frame is not None and len(frames) < 12:
        frames.append((os.path.normcase(os.path.abspath(frame.f_code.co_filename)), frame.f_code.co_name))
        frame = frame.f_back
    return frames


_AUDITED = frozenset({"open", "ctypes.dlsym", "socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind",
                      "os.kill", "subprocess.Popen", "_winapi.CreateProcess", "os.posix_spawn", "os.startfile", "os.system",
                      "os.exec", "os.spawn", "os.fork", "os.forkpty"})


def _hook(event: str, args) -> None:
    if event in _AUDITED:
        _audit(event, args)


# --------------------------------------------------------------------------- #
#  Installing the envelope
# --------------------------------------------------------------------------- #
def set_profile_authority(approve) -> None:
    """The guarded runner hands in its reviewed ProcessPolicy (see ``guarded_pytest.py``): ``approve(facts)`` returns a
    profile for an exact reviewed launch it constrains itself, judged on the effective executable, arguments, working
    directory and environment."""
    global _profile_authority
    _profile_authority = approve


def own_disposable(path) -> None:
    """A disposable root of this session (its basetemp; a reserved launch's own roots): synthetic fixtures, adopted ledgers
    and fixture backends must lie inside one. Exported to bootstrapped children."""
    folded = _norm(path)
    with _lock:
        if folded not in _disposable_roots:
            _disposable_roots.append(folded)
        value = os.pathsep.join(_disposable_roots)
    os.environ[DISPOSABLE_ENV] = value


def disposable_roots() -> list[str]:
    """This session's owned disposable roots (a copy): what a launch it reserves itself passes on to its child."""
    with _lock:
        return list(_disposable_roots)


def bind_stage_launch(launch: str, ledger) -> None:
    """For the gate driving a stage on this thread (an in-process gate, or a synthetic gate fixture): the next launch on
    this thread whose environment carries ``launch`` and ``ledger`` is the gate's reserved stage launch, delegated to it."""
    if not hasattr(_local, "delegated"):
        _local.delegated = {}
    _local.delegated[launch] = os.fspath(ledger)


def install(*, launch: str | None = None, parent: str | None = None, role: str | None = None) -> None:
    """Make this process a routine verification process. Idempotent. Called before tests can be imported."""
    global _installed, _record
    scrub()
    inherited = os.environ.get(CONTEXT_ENV) == ROUTINE and os.environ.get(ROOT_ENV)
    os.environ[CONTEXT_ENV] = ROUTINE
    if not inherited:  # a nested session keeps the outermost marked checkout as its reference
        os.environ[ROOT_ENV] = os.path.realpath(REPO_ROOT)
    with _lock:
        if _installed:
            return
        _installed = True
        if role != "routine-child":
            os.environ.pop(DISPOSABLE_ENV, None)  # a session's own basetemp (own_disposable) is its disposable root
        ledger = os.environ.get(LEDGER_ENV)
        _record = context.ProcessRecord(ledger, role or _bootstrapped or "routine-process", launch=launch,
                                        parent=parent) if ledger else None
    _load_table()
    sys.modules.setdefault("routine_effects", sys.modules.get(__name__))
    _install_boundary()
    sys.addaudithook(_hook)
    if _record is not None:
        try:
            _record.start()
        except context.LedgerError as exc:
            _accounting_failure(str(exc))


def attach_ledger(path) -> None:
    """Give an installed process a ledger it did not have at install (a raw run's conftest, before collection)."""
    global _record
    with _lock:
        if _record is not None:
            return
        os.environ[LEDGER_ENV] = os.fspath(path)
        _record = context.ProcessRecord(path, _bootstrapped or "raw-pytest")
    try:
        _record.start()
    except context.LedgerError as exc:
        _accounting_failure(str(exc))


class BindingError(OSError):
    """A launch identity in the environment that does not name a valid reservation for this very launch."""


def _binding(role: str, argv) -> tuple[str | None, str | None]:
    """(launch, parent) of this process from its reservation, popped from the environment; (None, None) when it was started
    without one. Raises BindingError when a launch identity is present but does not bind."""
    launch = os.environ.pop(LAUNCH_ENV, None)
    if not launch:
        return None, None
    ledger = os.environ.get(LEDGER_ENV)
    reservation = context.read_reservation(ledger, launch) if ledger else None
    if reservation is None:
        raise BindingError(f"launch {launch} has no reservation in its ledger")
    if role not in context.EXPECTATIONS.get(reservation["expect"], ()):
        raise BindingError(f"launch {launch} was reserved for a {reservation['expect']}, not a {role}")
    if reservation["identity"] != context.launch_identity(argv):
        raise BindingError(f"launch {launch} was reserved for another command line")
    return launch, reservation["parent"]


def bootstrap(runner: str, argv: list[str], *, ledger=None) -> None:
    """The common early setup of both supported pytest runners, before pytest is imported: plugin autoload off, opt-ins and
    overrides scrubbed, the envelope installed, and this session's accounting established -- bound to the gate's or the
    parent's reservation of this launch, or, for a direct run, in a new ledger beside the requested basetemp."""
    global _bootstrapped, ledger_owner
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if _installed and _bootstrapped == "routine-child":
        # A runner started in-process by a bootstrapped child (``python -c ... runpy.run_path(routine_pytest.py)``): the
        # child's own participant, already bound to its reservation, is this session's; only the scrub is repeated.
        scrub()
        return
    _bootstrapped = runner
    identity = list(getattr(sys, "orig_argv", sys.argv)[1:])
    if ledger is not None:  # the runner initialized its own ledger (the guarded runner's report sibling): it owns it
        if os.environ.get(LEDGER_ENV) or os.environ.get(LAUNCH_ENV):
            raise BindingError("a runner-created ledger where an inherited one exists")
        os.environ[LEDGER_ENV] = str(ledger)
        ledger_owner = runner
        install(role=runner)
        return
    launch, parent = _binding(runner, identity)
    if not os.environ.get(LEDGER_ENV):
        basetemp = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--basetemp=")), None)
        if basetemp is None and "--basetemp" in argv and argv.index("--basetemp") + 1 < len(argv):
            basetemp = argv[argv.index("--basetemp") + 1]
        if basetemp:
            target = Path(os.path.abspath(basetemp)).with_name(Path(basetemp).name + "-effects")
            if target.exists():
                shutil.rmtree(target)  # this run's own sibling of its own basetemp, recreated like the basetemp itself
            ledger = context.init_ledger(target, owner=runner)
        else:
            ledger = context.init_ledger(Path(tempfile.mkdtemp(prefix="act-effects-")) / "l", owner=runner)
        os.environ[LEDGER_ENV] = str(ledger)
        ledger_owner = runner
    elif launch is None:
        raise BindingError("an inherited effect ledger with no reserved launch: a nested session must be prepared by its "
                           "parent's launch boundary")
    install(launch=launch, parent=parent, role=runner)
    if launch is not None:
        # The roots its reserving parent gave this launch (the gate: the stage's own temporary folder; a parent session:
        # its own roots), as a bootstrapped child takes them.
        reservation = context.read_reservation(os.environ[LEDGER_ENV], launch) or {}
        for root in reservation.get("roots", []):
            own_disposable(root)


def finish(exit_status: int) -> int:
    """This session's end record. Returns the exit status, made non-zero when an unexpected refusal or an accounting failure
    happened (a clean session that could not record its own end is not clean either)."""
    try:
        observe_children(wait=3.0)
        check_reports()
    except Exception as exc:  # noqa: BLE001 - finishing must still write the end
        _accounting_failure(f"observing this session's children failed: {type(exc).__name__}: {exc}")
    unexpected_rows, failures = unexpected(), accounting_failures()
    status = exit_status
    if (unexpected_rows or failures) and status == 0:
        status = 1
    if _record is not None:
        try:
            _record.end(exit_status=status, refusals=len(refusals()), unexpected=len(unexpected_rows))
        except context.LedgerError as exc:
            _accounting_failure(str(exc))
            status = status or 1
    else:
        status = status or 1
    return status


def in_routine_context(environ=None) -> bool:
    return context.in_routine(environ)


def refuse_under_routine(entry: str, argv=None, *, data_only=frozenset(), origin=None) -> None:
    """For a real test driver's ``__main__``: refuse to start inside routine verification, wherever it lies (see
    ``routine_context.refuse_under_routine``). Data-only shapes stay usable. Exits ``REFUSED_EXIT``."""
    origin = sys.argv[0] if origin is None else origin
    role = context.launch_role(origin) if origin else None
    context.refuse_under_routine(entry, role[1] if role else "real-app-launch", argv, data_only=data_only, origin=origin,
                                 root=REPO_ROOT)


# --------------------------------------------------------------------------- #
#  The child bootstrap (routine_child.py)
# --------------------------------------------------------------------------- #
_child_state = {"exit": None}


def _exit_code(code) -> int:
    if code is None:
        return 0
    if isinstance(code, bool) or not isinstance(code, int):
        return 1
    return code & 0xFFFFFFFF if os.name == "nt" else code & 0xFF


def _child_fail(message: str) -> None:
    try:
        sys.stderr.write(f"routine_child: refused: {message} (GATE.md)\n")
        sys.stderr.flush()
    finally:
        os._exit(REFUSED_EXIT)


def child_main() -> None:
    """The bootstrapped child: bind to the reservation, initialize accounting, install the envelope, then run the program in
    this same process exactly as the unprepared command line would have run it."""
    global _bootstrapped, _child_target
    args = sys.argv[1:]
    carried = None
    if args and args[0].startswith("@"):
        carried, args = args[0][1:], args[1:]
        if not context.valid_launch(carried) or os.environ.get(LAUNCH_ENV):
            _child_fail("a malformed launch argument")
        os.environ[LAUNCH_ENV] = carried
    if len(args) < 2 or args[0] not in ("script", "module", "code"):
        _child_fail("the bootstrap was started without a program")
    mode, target, rest = args[0], args[1], args[2:]
    _child_target = (mode, target)
    if os.environ.get(CONTEXT_ENV) != ROUTINE or os.path.normcase(os.environ.get(ROOT_ENV, "")) != \
            os.path.normcase(os.path.realpath(REPO_ROOT)):
        _child_fail("the bootstrap is not the marked checkout's, or the child is outside routine verification")
    if not os.environ.get(LEDGER_ENV):
        _child_fail("no effect ledger")
    flags = _flags_of(sys.orig_argv)
    # A script has no option of its own; an empty argument the program was given stays (``--test ""`` is an argument).
    original = [*flags, *({"module": ["-m"], "code": ["-c"]}.get(mode, [])), target, *rest]
    # A free-standing reviewed recipe (the stand-in for pytest) accounts in the role its recipe declares; anything else is a
    # routine child.
    role = (context.recipe_role(os.path.abspath(target)) if mode == "script" else None) or "routine-child"
    try:
        launch, parent = _binding(role, original)
    except BindingError as exc:
        _child_fail(str(exc))
    if launch is None:
        _child_fail("started without a reserved launch")
    reservation = context.read_reservation(os.environ[LEDGER_ENV], launch)
    for root in reservation.get("roots", []):
        own_disposable(root)
    if reservation.get("measurement") == "network-guard":
        _defer_network()
    _bootstrapped = role
    install(launch=launch, parent=parent, role=role)
    if accounting_failures():
        _child_fail("its accounting could not be initialized: " + "; ".join(accounting_failures()[:2]))
    # Registered first, so it runs last. An os._exit skips it: an abrupt exit gets no end record (it is accounted only by an
    # explained crash or stop its reservation expected; R2 section 9 forbids disguising it).
    atexit.register(_child_end)
    _restore_paths(mode, target)
    import __main__

    try:
        _dispatch(__main__, mode, target, rest)
        _child_state["exit"] = 0
    except SystemExit as exc:
        _child_state["exit"] = _exit_code(exc.code)
        raise
    except KeyboardInterrupt:
        _child_state["exit"] = 0xC000013A if os.name == "nt" else -2
        raise
    except BaseException:
        _child_state["exit"] = 1
        raise


def _flags_of(orig_argv) -> list[str]:
    """The interpreter options before the bootstrap in this process's own command line."""
    bootstrap = os.path.normcase(str(CHILD_BOOTSTRAP))
    items = list(orig_argv[1:])
    for index, item in enumerate(items):
        if os.path.normcase(os.path.abspath(item)) == bootstrap:
            return items[:index]
    return []


def _restore_paths(mode: str, target: str) -> None:
    """``sys.path`` as the unprepared command would have had it: the bootstrap's own folder out, the program's first entry
    in (unless -P/-I), and the child's PYTHONPATH (moved past the envelope) back in front of the standard library."""
    here = os.path.dirname(os.path.abspath(str(CHILD_BOOTSTRAP)))
    if not sys.flags.safe_path and sys.path and os.path.normcase(os.path.abspath(sys.path[0] or os.curdir)) == \
            os.path.normcase(here):
        del sys.path[0]
    moved = os.environ.pop(PYTHONPATH_ENV, None)
    if moved is not None:
        os.environ["PYTHONPATH"] = moved
        if not sys.flags.ignore_environment:
            sys.path[0:0] = [part for part in moved.split(os.pathsep) if part]
    if not sys.flags.safe_path:
        first = {"module": os.getcwd(), "code": ""}.get(mode)
        if mode == "script":
            first = os.path.dirname(os.path.abspath(target))
        sys.path.insert(0, first)


def _dispatch(main, mode: str, target: str, rest: list[str]) -> None:
    import runpy

    builtins = main.__dict__.get("__builtins__")
    main.__dict__.clear()
    main.__dict__.update({"__name__": "__main__", "__doc__": None, "__package__": None, "__spec__": None,
                          "__builtins__": builtins})
    if mode == "module":
        sys.argv = ["-m", *rest]
        runpy._run_module_as_main(target, alter_argv=True)
        return
    if mode == "code":
        sys.argv = ["-c", *rest]
        exec(compile(target, "<string>", "exec"), main.__dict__)  # noqa: S102 - the code `python -c` would run
        return
    sys.argv = [target, *rest]
    path = os.path.abspath(target)
    if not os.path.isfile(path):
        if os.path.isdir(path) or path.lower().endswith((".zip", ".pyz", ".whl")):
            runpy.run_path(target, run_name="__main__")
            return
        sys.stderr.write(f"{sys.executable}: can't open file {path!r}: [Errno 2] No such file or directory\n")
        raise SystemExit(2)
    from importlib.machinery import SourceFileLoader

    with _io.open(path, "rb") as handle:
        source = handle.read()
    main.__dict__.update({"__file__": path, "__cached__": None, "__loader__": SourceFileLoader("__main__", path)})
    exec(compile(source, path, "exec"), main.__dict__)  # noqa: S102 - the program `python <path>` would run


def _child_end() -> None:
    record = _record
    if record is None or record.ended:
        return
    try:
        observe_children()
    except Exception as exc:  # noqa: BLE001
        _accounting_failure(f"observing this child's children failed: {type(exc).__name__}")
    status = _child_state["exit"]
    if status is None:
        status = 1
    try:
        record.end(exit_status=status, refusals=len(refusals()), unexpected=len(unexpected()))
    except context.LedgerError:
        pass
