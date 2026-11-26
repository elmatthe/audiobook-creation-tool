"""Routine verification restrictions, enforced at the operation (v0.8.2 Phase 1A-1, corrected in R1; plan Revision 5).

Every pytest process of this repository is a routine verification process. The supported invocation is the repository's
bootstrap -- ``routine_pytest.py`` for ordinary pytest, ``guarded_pytest.py`` for the guarded groups -- which calls
:func:`bootstrap` before pytest, its plugins, ``conftest.py`` or any test module is imported. A raw ``python -m pytest`` still
gets the restrictions from ``conftest.py``, but its accounting starts later and it is not a supported verification invocation
(GATE.md). Nothing here ever grants a heavyweight effect -- not an environment variable, not running under pytest, not a
flag. Admission of real heavyweight work is Phase 1A-2's; until then :func:`admitted` is always False.

What is enforced (the shared contract -- names, launch roots, data-only shapes, the synthetic fixture and the ledger format --
lives in ``helpers/routine_context.py``, loaded here by path):

* **Opt-ins and overrides are scrubbed** (:func:`scrub`): ``ACT_*_REAL`` real-engine opt-ins, the destination or executable
  overrides in ``OVERRIDES`` and an inherited disposable-root marker never reach a test or a child.
* **Declared boundaries refuse** (:func:`require`), and so do the operations themselves where a Python audit event exists:
  external network (``socket.connect``/``getaddrinfo``/``sendto``/``bind`` beyond loopback), a model library reading real
  weights (``open`` of a weight file outside the session's disposable roots, from a model library's frame), resolving a native-input function (``ctypes.dlsym``
  of ``SendInput`` and its kin outside the gate's own adapter, which checks its operation itself) and desktop hand-offs
  (``os.startfile``).
* **Launches are classified** (:func:`classify_launch`, on ``subprocess.Popen``, ``os.system``, ``os.exec*``, ``os.spawn*`` and
  ``os.posix_spawn``) by the program actually started (an ``executable=`` override, not ``argv[0]``), its arguments, working
  directory and environment. A heavyweight entrypoint is recognized wherever it lies -- this checkout, another checkout, a
  copy, a renamed copy (by its bytes) -- and refused unless the invocation has a reviewed data-only shape, the entry is
  reviewed as bounded, or it is the gate orchestrator of a reviewed synthetic fixture tree (``routine_context``). Shells
  are judged by the command they run; Python by its script, module or inline code; nested pytest must use the bootstrap; a
  Python or shell child whose replacement environment drops the routine marker, the marked checkout or the ledger is
  refused (a reviewed profile of the stronger guarded runner may vouch for a child it constrains itself); installers,
  online pip, network tools, desktop hand-offs, engine interpreters and unreviewed native programs are refused.
* **A refusal cannot be swallowed, and accounting fails closed**: each process records into its own file of the effect
  ledger directory (``ACT_EFFECT_LEDGER``), which its owner initialized before anything ran. A write failure is an
  accounting failure, never silently absorbed. ``conftest.py`` fails the test and the session for any unexpected refusal or
  accounting failure; the bootstrap fails the process for one after the session ended; the gate reads every stage's ledger
  and accepts only a complete, well-formed one. :func:`expected_refusals` marks refusals of named effects as expected for the
  synthetic negative control running on this thread only; it grants nothing.

This makes accidental heavyweight execution from supported routine paths fail closed. It is not an OS sandbox: a cooperating
child Python inherits the marker, the ledger and the disposable scope (so every maintained root refuses in it and accounts
for it) but not this process's audit hook, and native code or an unrestricted shell is outside what Python audit hooks see.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PY = ".py"


def _load_context():
    path = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "helpers" / ("routine_context" + _PY)
    name = "act_routine_context"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


context = _load_context()
EFFECTS = context.EFFECTS
CONTEXT_ENV, ROOT_ENV, LEDGER_ENV, DISPOSABLE_ENV = (context.CONTEXT_ENV, context.ROOT_ENV, context.LEDGER_ENV,
                                                     context.DISPOSABLE_ENV)
ROUTINE, REFUSED_EXIT, DATA_ONLY = context.ROUTINE, context.REFUSED_EXIT, context.DATA_ONLY
OPT_IN = re.compile(r"^ACT_[A-Z0-9_]*_REAL(_[A-Z0-9_]+)?$")
#: Ambient destination and executable overrides a test must never inherit (v0.8.x P2 and P1A tools).
OVERRIDES = frozenset({"ACT_P2_EVIDENCE", "ACT_XHE_PROOF_APPLE_CAF", "ACT_MAC_FFMPEG"})
POLICY_FILE = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "verification.json"
#: Data-only flags a gate entrypoint's own parser acts on before any effect, wherever they appear as a standalone token.
ANYWHERE = {context.ORCHESTRATOR: frozenset({"--plan"})}
ENGINE_ENVIRONMENTS = (".venv/engines/", ".venv-qwen3/", ".venv-omnivoice/", "files/dev-work/qwen3-eval/.venv/")
#: The one reviewed engine-interpreter launch, mirrored from the guarded runner's "read-only-calm-library-selfcheck" profile
#: (a contract test keeps the two equal): fixed library methods and configuration are inspected, no model is loaded.
ENGINE_EXCEPTIONS = (("files/dev-tools/qwen3_calm_venv_tools" + _PY, "selfcheck"),)
INSTALLERS = frozenset({"winget", "brew", "msiexec", "choco", "apt", "apt-get", "port", "dnf", "yum", "snap", "npm",
                        "uv", "conda", "mamba", "softwareupdate", "installer"})
NETWORK_TOOLS = frozenset({"curl", "wget", "bitsadmin", "certutil", "ftp", "tftp", "ssh", "scp", "sftp", "nc", "ncat",
                           "telnet", "invoke-webrequest"})
#: Hand a file or an application to the desktop, or drive it, as os.startfile does.
DESKTOP = frozenset({"explorer", "xdg-open", "open", "rundll32", "start", "osascript", "cliclick", "shortcuts"})
MACHINE = frozenset({"reg", "setx", "schtasks", "sc", "net", "netsh", "bcdedit", "diskpart", "format", "launchctl",
                     "systemsetup", "defaults", "tccutil", "diskutil", "csrutil", "spctl", "pmset", "shutdown", "sudo"})
#: Reviewed native programs routine tests start: read-only probes, bounded media and Git work on test-owned paths, short
#: process fixtures. Anything else that is not Python, a shell, or a program the test made in its own disposable folder is
#: refused as unclassified (extend this list only by review).
NATIVE_BOUNDED = frozenset({"git", "ffmpeg", "ffprobe", "tasklist", "taskkill", "nvidia-smi", "sleep", "cp", "hdiutil",
                            "afconvert", "afinfo", "where", "whoami", "icacls", "attrib", "timeout", "codesign", "xattr",
                            "sw_vers", "uname", "sysctl", "plutil", "otool", "lipo", "file", "true", "false", "echo",
                            "tar", "ditto", "mdls", "sips", "id", "ps", "kill", "pgrep", "ls", "cat", "rm", "mkdir"})
SHELLS = frozenset({"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "dash"})
_PYTHON = re.compile(r"^(python|pythonw|py)(\d+(\.\d+)*)?w?$")
_SCRIPT = re.compile(r"\.(py|pyw|bat|cmd|command|ps1|sh)$", re.IGNORECASE)
#: Python options that take a value as the next argument.
_PY_VALUE_OPTIONS = frozenset({"-X", "-W", "-Q", "--check-hash-based-pycs"})
WEIGHTS = (".pt", ".pth", ".safetensors", ".onnx", ".ckpt", ".gguf")
#: Libraries whose reading of a weight file is model initialization (their Python-level reads; a native reader -- the
#: safetensors Rust core, onnxruntime -- is not visible to an audit hook).
MODEL_LIBRARIES = ("torch", "transformers", "huggingface_hub", "safetensors", "onnxruntime", "kokoro", "chatterbox",
                   "diffusers", "accelerate", "qwen_tts", "omnivoice", "spacy", "thinc", "librosa")
NATIVE_INPUT = frozenset({"SendInput", "keybd_event", "mouse_event", "SetCursorPos", "CGEventPost", "CGEventPostToPid",
                          "BlockInput"})
#: The gate's own native-input adapter checks its operation itself (routine_context.check_operation) before it sends input.
NATIVE_INPUT_OWNER = "files/dev-work/verification-gate/adapters/windows/native_input" + _PY
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", None, ""})
_LAUNCH_EVENTS = frozenset({"subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec", "os.posix_spawn"})


class EffectRefused(PermissionError):
    """A heavyweight effect asked for in routine verification. Refused before the operation; recorded either way."""


_lock = threading.RLock()
_local = threading.local()
_refusals: list[dict] = []
_accounting_failures: list[str] = []
_disposable_roots: list[str] = []
_installed = False
_bootstrapped: str | None = None
_record: object | None = None
_table: dict | None = None
_real_digests: dict[str, str] | None = None
_profile_authority = None
_adopting: list = []
#: The runner that created this process's ledger (a direct run), or None when the ledger belongs to the gate or a parent.
ledger_owner: str | None = None


# --------------------------------------------------------------------------- #
#  The environment
# --------------------------------------------------------------------------- #
def scrub(environ=None) -> list[str]:
    """Remove ambient real-engine opt-ins and destination/executable overrides. Returns the names removed."""
    environ = os.environ if environ is None else environ
    removed = sorted(name for name in list(environ) if OPT_IN.match(name.upper()) or name.upper() in OVERRIDES)
    for name in removed:
        environ.pop(name, None)
    return removed


def admitted(effect: str) -> bool:
    """Whether this process may perform ``effect`` for real. Always False in Phase 1A-1: admission (an owner grant claimed
    by a live coordinator and delegated to this process) is Phase 1A-2's, and nothing ambient can stand in for it."""
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


def refusals() -> list[dict]:
    with _lock:
        return [dict(row) for row in _refusals]


def unexpected() -> list[dict]:
    return [row for row in refusals() if not row.get("expected")]


def accounting_failures() -> list[str]:
    with _lock:
        return list(_accounting_failures)


class _Scope:
    def __init__(self, effects, accounting: str) -> None:
        self.effects = frozenset(effects)
        self.accounting = accounting
        self.adopted: list[str] = []
        self.ledgers: dict[str, dict] = {}

    def allows(self, effect: str) -> bool:
        return not self.effects or effect in self.effects


@contextlib.contextmanager
def expected_refusals(*effects: str, accounting: str = "strict"):
    """For the synthetic negative controls of these mechanisms only: refusals of ``effects`` (any effect when none is named)
    made on this thread inside the block are recorded as expected. It grants nothing -- the operation is still refused --
    and a refusal on another thread, or of another effect, stays unexpected.

    A child started inside the block may be given a private ledger (initialized with :func:`new_ledger`, inside the
    session's disposable root). It is adopted: when the block ends it is read, refusals of the named effects count as
    expected, anything else is recorded here as unexpected, and an incomplete or malformed private ledger is an accounting
    failure (``accounting="report"`` leaves that to the test, through the yielded scope's ``ledgers``)."""
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
        for path in scope.adopted:
            verdict = context.read_ledger(path)
            scope.ledgers[path] = verdict
            for row in verdict["refusals"]:
                if not scope.allows(row.get("effect")):
                    escalated = {key: row.get(key) for key in ("effect", "detail", "origin", "pid")}
                    escalated["origin"] = f"adopted ledger: {escalated.get('origin')}"
                    _record_refusal(escalated)
            if scope.accounting == "strict" and verdict["problems"]:
                _accounting_failure(f"an adopted child ledger is not clean: {'; '.join(verdict['problems'][:3])}")


@contextlib.contextmanager
def adopting_ledgers():
    """For a test that drives the gate in-process against a synthetic fixture: the gate owns and judges its stages' own
    ledgers (a replacement ledger inside this session's disposable root is adopted, not refused), and every refusal recorded
    in them is still counted here as unexpected. No refusal is expected; completeness is the gate's own verdict."""
    scope = _Scope({"<none>"}, "report")
    with _lock:
        _adopting.append(scope)  # process-wide: adoption expects nothing, so a gate driven on another thread is covered too
    try:
        yield scope
    finally:
        with _lock:
            _adopting.remove(scope)
        for path in scope.adopted:
            verdict = context.read_ledger(path)
            scope.ledgers[path] = verdict
            for row in verdict["refusals"]:
                escalated = {key: row.get(key) for key in ("effect", "detail", "origin", "pid")}
                escalated["origin"] = f"adopted ledger: {escalated.get('origin')}"
                _record_refusal(escalated)


def new_ledger(path, owner: str = "test") -> Path:
    """Initialize a private ledger directory for a synthetic control's child (see :func:`expected_refusals`)."""
    return context.init_ledger(path, owner=owner)


def read_ledger(path, **kwargs) -> dict:
    return context.read_ledger(path, **kwargs)


def ledger_refusals(path) -> list[dict]:
    """The refusal rows of a ledger directory (for tests); its verdict is :func:`read_ledger`."""
    return context.read_ledger(path)["refusals"]


# --------------------------------------------------------------------------- #
#  Launches
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
        with open(path, "rb") as handle:
            data = handle.read(4 << 20)
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


def _resolve(text: str, cwd) -> str:
    text = text.strip("\"'")
    base = os.fspath(cwd) if cwd else os.getcwd()
    path = text if os.path.isabs(text) else os.path.join(base, text)
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return path


def _program(program: str, cwd, env) -> tuple[str, str]:
    """(name, resolved path) of the program actually started."""
    text = program.strip("\"'")
    found = None
    if not os.path.dirname(text):
        path_value = None
        if env is not None:
            path_value = next((value for key, value in env.items() if str(key).upper() == "PATH"), None)
        found = shutil.which(text, path=path_value)
    resolved = os.path.realpath(found) if found else _resolve(text, cwd)
    base = os.path.basename(resolved if found else text).lower()
    for suffix in (".exe", ".com"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base, resolved


def _disposable(path: str) -> bool:
    folded = os.path.normcase(os.path.realpath(path))
    with _lock:
        roots = list(_disposable_roots)
    return any(folded == root or folded.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _env_problem(env) -> str | None:
    """Why the child's environment -- a replacement, or this process's own when it inherits -- would start it outside the
    routine envelope, or None."""
    if env is None:
        env = os.environ
    upper = {str(key).upper() if os.name == "nt" else str(key): os.fsdecode(value) if isinstance(value, bytes) else str(value)
             for key, value in env.items()}
    get = upper.get
    if get(CONTEXT_ENV) != ROUTINE:
        return "its replacement environment drops the routine marker"
    if os.path.normcase(get(ROOT_ENV, "")) != os.path.normcase(os.environ.get(ROOT_ENV, "")):
        return "its replacement environment changes the marked checkout"
    ours, theirs = os.environ.get(LEDGER_ENV), get(LEDGER_ENV)
    if ours and theirs != ours:
        scopes = _scopes()
        with _lock:
            adopting = list(_adopting)
        scope = scopes[-1] if scopes else (adopting[-1] if adopting else None)
        if not (theirs and scope is not None and _disposable(theirs)):
            return "its replacement environment replaces or drops the effect ledger"
        if theirs not in scope.adopted:
            scope.adopted.append(theirs)
    if any(OPT_IN.match(key.upper()) or key.upper() in OVERRIDES for key in upper):
        return "its replacement environment re-adds a real-engine opt-in or override"
    return None


def _python_parts(args: list[str]) -> tuple[str | None, str | None, str | None, list[str]]:
    """(script, module, code, arguments after it) of a Python command line's own arguments."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-c":
            return None, None, args[index + 1] if index + 1 < len(args) else "", args[index + 2:]
        if arg == "-m":
            return None, args[index + 1] if index + 1 < len(args) else "", None, args[index + 2:]
        if arg.startswith("-c") and len(arg) > 2:
            return None, None, arg[2:], args[index + 1:]
        if arg.startswith("-m") and len(arg) > 2:
            return None, arg[2:], None, args[index + 1:]
        if arg in _PY_VALUE_OPTIONS:
            index += 2
            continue
        if arg == "-" or not arg.startswith("-"):
            return (None if arg == "-" else arg), None, None, args[index + 1:]
        index += 1
    return None, None, None, []


def _module_file(module: str, cwd, env) -> str | None:
    """Where ``python -m module`` finds ``module`` among the working directory and the child's PYTHONPATH."""
    if not module or not re.fullmatch(r"[A-Za-z_][\w.]*", module):
        return None
    roots = [os.fspath(cwd) if cwd else os.getcwd()]
    source = env if env is not None else os.environ
    extra = next((value for key, value in source.items() if str(key).upper() == "PYTHONPATH"), "")
    roots += [part for part in str(extra).split(os.pathsep) if part]
    relative = module.replace(".", os.sep)
    for root in roots:
        for candidate in (os.path.join(root, relative + _PY), os.path.join(root, relative, "__main__" + _PY)):
            if os.path.isfile(candidate):
                return os.path.realpath(candidate)
    return None


def _target(path: str, args: list[str], *, cwd, env, interpreter: str | None) -> tuple[str, str] | None:
    """The verdict on starting the script ``path`` (resolved) with ``args``."""
    role = context.launch_role(path)
    relative = role[2] if role else None
    if role is None:
        known = _real_entrypoints().get(_digest(path) or "")
        if known:
            role = context.launch_role(known)
            relative = known
            if role is not None:
                return role[1], f"a renamed copy of the heavyweight entrypoint {known}"
        return None
    entry = _load_table().get(relative.lower()) or {}
    disposition = entry.get("routine", "refused")
    if disposition == "bounded":
        return None
    if relative in ("scripts/shared/bootstrap_host.ps1", "scripts/shared/bootstrap_host_macos.sh"):
        if _stage_zero_bounded(args, path):
            return None
        return "install", f"stage 0 ({relative}) in a shape that could install or download"
    if relative in _LAUNCHER_BACKENDS:
        if _launcher_bounded(path, relative):
            return None
        return "install", f"a copy of {relative} whose own backends are not all stand-ins (it could set up or launch the app)"
    data_only = entry.get("data_only", []) if disposition == "data-only" else ()
    if context.data_only_shape(args, data_only, ANYWHERE.get(relative, ())):
        return None
    if relative == context.ORCHESTRATOR and interpreter is not None and _synthetic_orchestrator(path, interpreter):
        return None
    effects = entry.get("effects") or [role[1]]
    where = "this checkout" if _inside_repo(path) else "another checkout or a copy"
    return effects[0], f"a heavyweight entrypoint ({relative}, in {where}; {entry.get('class', 'unclassified')})"


def _inside_repo(path: str) -> bool:
    return os.path.normcase(os.path.realpath(path)).startswith(os.path.normcase(os.path.realpath(REPO_ROOT)) + os.sep)


def _stage_zero_bounded(args: list[str], script: str) -> bool:
    """The reviewed routine shapes of stage 0 (mirroring the guarded runner's bootstrap profiles): it never installs or
    downloads. Either it is told to assume "no", or it is a copy in this session's disposable tree handed a local archive or
    synthetic installer that also lies there, with every online source disabled -- so whatever it unpacks lands in the copy.
    Nothing in it names a URL."""
    lowered = [arg.lower() for arg in args]
    if any("://" in arg for arg in args):
        return False
    if "-assumeno" in lowered or "--assume-no" in lowered:
        return True
    if not _disposable(script):
        return False
    for flag in ("-archivepath", "-installerpath", "--archive-path"):
        if flag in lowered:
            at = lowered.index(flag)
            local = at + 1 < len(args) and _disposable(args[at + 1])
            if local and (flag != "-installerpath" or "-nowinget" in lowered):
                return True
    return False


#: The setup launchers' reviewed bounded shape. Each one first enters its own folder (``cd /d "%~dp0"``; ``cd "$HERE"``)
#: and starts only the programs below, by paths relative to that folder (the Windows one also falls back to a ``python``
#: on PATH, which runs the same relative ``bootstrap.py``). A copy is bounded when it lies in this session's disposable
#: tree and every (interpreter, script) pair it can start has a stand-in side: a script that is absent or not the marked
#: checkout's bytes, or an interpreter that is absent or a text shim (``#!``), never a real binary or a venv link.
_LAUNCHER_BACKENDS = {
    "Setup_and_Run-audiobook-creation-tool.bat": {
        "stage0": "scripts/shared/bootstrap_host.ps1",
        "pairs": [((".venv/Scripts/python.exe", None), ("scripts/shared/bootstrap.py",))],
    },
    "Setup_and_Run-audiobook-creation-tool.command": {
        "stage0": "scripts/shared/bootstrap_host_macos.sh",
        "pairs": [((".venv/bin/python", "files/runtime-data/python/bin/python3.12"),
                   ("scripts/shared/bootstrap.py", "scripts/shared/close_terminal.py"))],
    },
}


def _launcher_bounded(path: str, relative: str) -> bool:
    if not _disposable(path):
        return False
    root = Path(path).parent
    shape = _LAUNCHER_BACKENDS[relative]

    def regular(candidate: Path) -> bool | None:
        """None when absent; False for a link or anything not a regular file."""
        if not os.path.lexists(candidate):
            return None
        return not os.path.islink(candidate) and candidate.is_file()

    def stand_in_script(rel: str) -> bool:
        kind = regular(root / rel)
        if kind is None:
            return True
        real = _digest(REPO_ROOT / rel)
        return bool(kind) and real is not None and _digest(root / rel) != real

    def shim(rel) -> bool:
        if rel is None:
            return False  # an interpreter the launcher finds outside its folder is always real
        kind = regular(root / rel)
        if kind is None:
            return True
        if not kind:
            return False
        try:
            with open(root / rel, "rb") as handle:
                return handle.read(2) == b"#!"
        except OSError:
            return False

    if not stand_in_script(shape["stage0"]):
        return False
    for interpreters, scripts in shape["pairs"]:
        if not (all(shim(rel) for rel in interpreters) or all(stand_in_script(rel) for rel in scripts)):
            return False
    return True


def _trusted_interpreter(path: str) -> bool:
    trusted = {os.path.normcase(os.path.realpath(p)) for p in (sys.executable, getattr(sys, "_base_executable", ""),) if p}
    return os.path.normcase(os.path.realpath(path)) in trusted


def _synthetic_orchestrator(script: str, interpreter: str) -> bool:
    """The reviewed synthetic exception: this session's own interpreter starting the gate orchestrator of a synthetic fixture
    tree that lies in this session's owned disposable root (routine_context.synthetic_fixture checks the declaration, and that
    the orchestrator's bytes are the marked checkout's, so its operation boundaries hold in the child)."""
    if not _trusted_interpreter(interpreter):
        return False
    tree = Path(os.path.realpath(script)).parents[3]
    if not _disposable(str(tree)):
        return False
    with _lock:
        roots = [root for root in _disposable_roots if os.path.normcase(str(tree)).startswith(root)]
    view = {CONTEXT_ENV: ROUTINE, ROOT_ENV: os.environ.get(ROOT_ENV, ""), DISPOSABLE_ENV: roots[0] if roots else ""}
    return context.synthetic_fixture(tree, view) is not None


def _code_targets(code: str) -> str | None:
    """A launch-root file named by a path literal in inline code (``runpy.run_path(".../acceptance_runner.py")``)."""
    text = code.replace("\\\\", "/").replace("\\", "/")
    for root in context.LAUNCH_ROOTS:
        if not root.endswith("/") and root.split("/")[-1] and re.search(re.escape(root) + r"\b", text, re.IGNORECASE):
            return root
    return None


def classify_launch(command, cwd=None, *, executable=None, env=None, _depth: int = 0) -> tuple[str, str] | None:
    """``(effect, why)`` when routine verification may not start this command, else None. ``executable`` is the program
    actually started when it is given (``argv[0]`` is then only the name the child sees); ``env`` is a replacement
    environment (None: inherited)."""
    argv = _argv(command)
    if not argv or _depth > 4:
        return ("install", "an unparseable or too deeply nested command") if _depth > 4 else None
    name, program = _program(os.fspath(executable) if executable else argv[0], cwd, env)
    args = argv[1:]
    stem = name.rsplit(".", 1)[0] if name.endswith((".cmd", ".bat")) else name
    if stem in INSTALLERS:
        return "install", f"a package manager or installer: {' '.join(argv[:4])}"
    if stem in NETWORK_TOOLS:
        return "external-network", f"a network tool: {' '.join(argv[:3])}"
    if stem in DESKTOP:
        return "native-desktop", f"a desktop hand-off: {' '.join(argv[:3])}"
    if stem in MACHINE:
        return "install", f"a machine configuration program: {' '.join(argv[:3])}"
    lowered = [token.lower() for token in argv]
    pip = stem in ("pip", "pip3") or ("-m" in lowered and lowered[lowered.index("-m") + 1:lowered.index("-m") + 2] == ["pip"])
    if pip and "install" in lowered and "--no-index" not in lowered:
        return "external-network", "an online pip install (no --no-index)"
    engine = context.launch_role(program)
    folded = program.replace("\\", "/").lower()
    if any("/" + environment.lower() in folded for environment in ENGINE_ENVIRONMENTS) and not _disposable(program):
        # An engine environment's interpreter, in any checkout. One the test made (an empty venv in its own disposable
        # folder, under an engine-shaped name) holds no engine and is the test's own.
        script, _module, _code, _rest = _python_parts(args)
        relative = context.launch_role(_resolve(script, cwd))[2] if script and context.launch_role(_resolve(script, cwd)) else None
        if not any(relative == path and word in args for path, word in ENGINE_EXCEPTIONS):
            return "real-engine", f"an interpreter of a real engine environment ({program})"
    if _PYTHON.match(stem):
        problem = _env_problem(env)
        script, module, code, rest = _python_parts(args)
        if module in ("pytest", "py.test") or (code is not None and "pytest.main(" in code) or \
                (script and os.path.basename(script).lower() in ("pytest", "py.test")):
            return "real-app-launch", "a nested pytest outside the routine bootstrap (use files/tests/routine_pytest.py)"
        if module:
            found = _module_file(module, cwd, env)
            if found:
                verdict = _target(found, rest, cwd=cwd, env=env, interpreter=program)
                if verdict:
                    return verdict[0], f"python -m {module}: {verdict[1]}"
        if code is not None:
            named = _code_targets(code)
            if named:
                return context.LAUNCH_ROOTS[named], f"inline code that runs the heavyweight entrypoint {named}"
        if script:
            verdict = _target(_resolve(script, cwd), rest, cwd=cwd, env=env, interpreter=program)
            if verdict:
                return verdict
        if problem:
            return "real-app-launch", f"a Python child: {problem}"
        return None
    script_program = bool(_SCRIPT.search(program)) and not _PYTHON.match(stem)
    if stem in SHELLS or script_program:
        problem = _env_problem(env)
        if script_program:
            verdict = _target(program, args, cwd=cwd, env=env, interpreter=None)
            if verdict:
                return verdict
        else:
            kind, value = _shell_inner(stem, args)
            if kind == "script":
                verdict = _target(_resolve(value, cwd), _shell_script_args(stem, args, value), cwd=cwd, env=env,
                                  interpreter=None)
                if verdict:
                    return verdict
            elif kind == "command":
                verdict = classify_launch(value, cwd, env=env, _depth=_depth + 1)
                if verdict:
                    return verdict[0], f"{stem}: {verdict[1]}"
            elif kind == "unknown":
                return "install", f"an unclassified {stem} command ({' '.join(argv[:4])[:120]})"
            # kind "parse" (``sh -n script``) and "interactive" run nothing of their own
        if problem:
            return "real-app-launch", f"a shell child: {problem}"
        return None
    if engine is not None:
        return engine[1], f"a heavyweight entrypoint started as a program ({engine[2]})"
    if stem in NATIVE_BOUNDED or _disposable(program) or not os.path.lexists(program):
        return None  # a reviewed native program, one the test made in its own folder, or one that does not exist
    return "install", f"an unclassified native program ({program}); review it into NATIVE_BOUNDED or refuse it"


def _shell_inner(stem: str, args: list[str]) -> tuple[str, str | None]:
    """What a shell would run: ("script", path), ("parse", path), ("command", text), ("interactive", None) or ("unknown", None)."""
    lowered = [arg.lower() for arg in args]
    if stem == "cmd":
        for index, arg in enumerate(lowered):
            if arg in ("/c", "/k", "/r"):
                text = " ".join(args[index + 1:]).strip()
                if len(text) > 1 and text[0] == text[-1] == '"' and text.count('"') == 2:
                    text = text[1:-1]
                if text.lower().startswith("call "):
                    text = text[5:].strip()
                return ("command", text) if text else ("interactive", None)
        return "interactive", None
    if stem in ("powershell", "pwsh"):
        for index, arg in enumerate(lowered):
            if arg in ("-file", "-f") and index + 1 < len(args):
                return "script", args[index + 1]
            if arg in ("-command", "-c", "-encodedcommand", "-ec", "-e"):
                return "unknown", None
        return ("unknown", None) if any(not arg.startswith("-") for arg in args) else ("interactive", None)
    # POSIX shells. ``-n`` (noexec) before the script makes it a syntax check that runs nothing.
    noexec = False
    for index, arg in enumerate(args):
        if arg == "-c" or (arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]):
            return ("command", args[index + 1]) if index + 1 < len(args) else ("interactive", None)
        if arg.startswith("-") and not arg.startswith("--") and "n" in arg[1:]:
            noexec = True
        if not arg.startswith("-"):
            return ("parse", arg) if noexec else ("script", arg)
    return "interactive", None


def _shell_script_args(stem: str, args: list[str], script: str) -> list[str]:
    try:
        return args[args.index(script) + 1:]
    except ValueError:
        return []


def _launch(event: str, args) -> tuple:
    """(command, cwd, executable, env) of a launch audit event."""
    if event == "subprocess.Popen":
        return args[1], args[2], args[0], args[3]
    if event == "os.system":
        command = args[0]
        if isinstance(command, (bytes, bytearray)):
            command = command.decode("utf-8", "replace")
        shell = ["cmd", "/c", command] if os.name == "nt" else ["/bin/sh", "-c", command]
        return shell, None, None, None
    if event == "os.exec":
        return args[1], None, args[0], args[2] if len(args) > 2 else None
    if event == "os.spawn":
        return args[2], None, args[1], args[3] if len(args) > 3 else None
    if event == "os.posix_spawn":
        return args[1], None, args[0], args[2] if len(args) > 2 else None
    return (), None, None, None


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
    """The model library (``MODEL_LIBRARIES``) on the current stack, if a frame of one is there: reading a weight file to
    hash or copy it is ordinary; a model library reading it is model initialization."""
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


def _audit(event: str, args) -> None:
    if event == "open":
        path = args[0]
        if isinstance(path, str) and path.lower().endswith(WEIGHTS):
            mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
            if not any(flag in mode for flag in "wax+") and not _disposable(path) and _model_loader():
                refuse("real-engine", f"a model library reading real weights ({os.path.basename(path)})", origin=event)
        return
    if event.startswith("socket."):
        target = _external(event, args)
        if target is not None:
            refuse("external-network", f"{event} to {target[:120]}", origin=event)
        return
    if event == "ctypes.dlsym":
        name = args[1] if len(args) > 1 else None
        if isinstance(name, str) and name in NATIVE_INPUT and not _caller_is(NATIVE_INPUT_OWNER):
            refuse("native-desktop", f"resolving the native input function {name}", origin=event)
        return
    if event not in _LAUNCH_EVENTS:
        return
    if event == "os.startfile":
        refuse("native-desktop", f"os.startfile({str(args[0])[:200]!r}) hands a file to the desktop", origin=event)
    command, cwd, executable, env = _launch(event, args)
    verdict = classify_launch(command, cwd, executable=executable, env=env)
    if verdict is not None and verdict[1].startswith(("a Python child: ", "a shell child: ")) and _profile_authority:
        if _profile_authority(command, cwd):
            return  # the stronger guarded runner's reviewed profile constrains this child itself
    if verdict is not None:
        refuse(verdict[0], verdict[1], origin=event)


_AUDITED = _LAUNCH_EVENTS | {"open", "ctypes.dlsym", "socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}


def _hook(event: str, args) -> None:
    if event in _AUDITED:
        _audit(event, args)


# --------------------------------------------------------------------------- #
#  Installing the envelope
# --------------------------------------------------------------------------- #
def set_profile_authority(approve) -> None:
    """The guarded runner hands in its reviewed ProcessPolicy: a child it approves by profile is constrained by that profile
    (fixed module, disposable request and result, scrubbed environment), so a replacement environment there is reviewed."""
    global _profile_authority
    _profile_authority = approve


def own_disposable(path) -> None:
    """The session's owned disposable root (its basetemp): synthetic fixtures and adopted ledgers must lie inside it, and a
    file the test made there is the test's own. Exported to children only to narrow where a synthetic fixture may lie."""
    folded = os.path.normcase(os.path.realpath(os.fspath(path)))
    with _lock:
        if folded not in _disposable_roots:
            _disposable_roots.append(folded)
    os.environ[DISPOSABLE_ENV] = os.fspath(path)


def install() -> None:
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
        os.environ.pop(DISPOSABLE_ENV, None)  # only this session's own basetemp (own_disposable) is ever a disposable root
        ledger = os.environ.get(LEDGER_ENV)
        _record = context.ProcessRecord(ledger, _bootstrapped or "routine-process") if ledger else None
    _load_table()
    sys.modules.setdefault("routine_effects", sys.modules.get(__name__))
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


def bootstrap(runner: str, argv: list[str]) -> None:
    """The common early setup of both supported pytest runners, before pytest is imported: plugin autoload off, opt-ins and
    overrides scrubbed, the envelope installed, and this session's accounting established -- in the gate stage's own ledger
    (initialized by the gate), or, for a direct run, in a new ledger beside the requested basetemp."""
    global _bootstrapped
    _bootstrapped = runner
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
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
        global ledger_owner
        ledger_owner = runner
    install()


def finish(exit_status: int) -> int:
    """This session's end record. Returns the exit status, made non-zero when an unexpected refusal or an accounting failure
    happened (a clean session that could not record its own end is not clean either)."""
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
