"""Routine verification restrictions, enforced at the operation (v0.8.2 Phase 1A-1; plan Revision 5).

Every pytest process of this repository is a routine verification process: ``conftest.py`` installs this module at its own
import (raw targeted pytest included), and the gate's bootstrap ``routine_pytest.py`` installs it before pytest, its plugins,
``conftest.py`` or any test module is imported. Nothing here ever grants a heavyweight effect -- not an environment variable,
not running under pytest, not a flag. Admission of real heavyweight work is Phase 1A-2's; until then :func:`admitted` is
always False and :func:`require` always refuses.

What is enforced:

* **Opt-ins and overrides are scrubbed** (:func:`scrub`): ``ACT_*_REAL`` real-engine opt-ins and the destination or executable
  overrides in ``OVERRIDES`` never reach a test or a child. A test gated on an opt-in also asks :func:`admitted`.
* **Declared boundaries refuse** (:func:`require`): a test that reaches a real heavyweight boundary (``ACT_EFFECTS`` in its
  module, read statically by ``helpers/effects.py``) calls ``require(effect, detail)`` before the real operation.
* **Launches are classified** (:func:`classify_launch`, an audit hook on ``subprocess.Popen``, ``os.system``,
  ``os.startfile``, ``os.spawn*``, ``os.exec*`` and ``os.posix_spawn``): starting a classified heavyweight entrypoint of this
  checkout by its real path (the gate's acceptance runner, qualification, scaling and adapters; ``files/dev-tools``; the real
  test drivers; the real launcher, setup, bootstrap and release builder), any interpreter of a real engine environment, a
  package manager or installer, an online ``pip install``, or ``os.startfile`` is refused. Data-only invocations (``--help``,
  ``--list``, the gate's readers) and the reviewed bounded fixtures of ``verification.json`` ``entrypoints`` are not.
* **A refusal cannot be swallowed**: every refusal is recorded, in this process and in the ledger file named by
  ``ACT_EFFECT_LEDGER`` (inherited by children); ``conftest.py`` fails the test and the session for any refusal not declared
  expected (:func:`expected_refusals`, for the synthetic negative controls of these mechanisms), and the gate fails the stage.
* **Children inherit the context** (``ACT_VERIFY_CONTEXT=routine``). A child Python does not inherit an audit hook, so the
  maintained heavyweight roots refuse to start under that marker themselves (:func:`refuse_under_routine` here, and
  ``helpers/routine_context.py`` for the gate's roots). The marker only ever restricts; its absence grants nothing new.

This makes accidental heavyweight execution from supported routine paths fail closed. It is not an OS sandbox: a child given a
replacement environment, or arbitrary code in an unrestricted shell, is outside what a cooperating test process can enforce.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EFFECTS = frozenset({"native-desktop", "real-app-launch", "real-engine", "external-network", "install", "scaling",
                     "release-build"})
CONTEXT_ENV = "ACT_VERIFY_CONTEXT"
#: The checkout whose heavyweight roots refuse under the marker (helpers/routine_context.py). A copy elsewhere is the test's own.
ROOT_ENV = "ACT_VERIFY_ROOT"
LEDGER_ENV = "ACT_EFFECT_LEDGER"
ROUTINE = "routine"
REFUSED_EXIT = 2
OPT_IN = re.compile(r"^ACT_[A-Z0-9_]*_REAL(_[A-Z0-9_]+)?$")
#: Ambient destination and executable overrides a test must never inherit (v0.8.x P2 and P1A tools).
OVERRIDES = frozenset({"ACT_P2_EVIDENCE", "ACT_XHE_PROOF_APPLE_CAF", "ACT_MAC_FFMPEG"})
POLICY_FILE = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "verification.json"
#: A Python file name is spelled as a stem plus ``_PY`` on purpose: the evidence ledger's static closure
#: (helpers/evidence_ledger.Closures) reads a literal ``"....py"`` string as a dependency edge, and conftest.py loads this
#: module into every test's closure -- literal names here would make every test depend on the launcher and every tool.
_PY = ".py"
#: Where a classified entrypoint lives; anything below these roots that the reviewed table does not call bounded or
#: data-only is refused, so a new or unreadable entry fails closed.
HEAVY_ROOTS = {
    "files/dev-work/verification-gate/acceptance_runner" + _PY: "native-desktop",
    "files/dev-work/verification-gate/verify" + _PY: "native-desktop",
    "files/dev-work/verification-gate/qualification/": "real-app-launch",
    "files/dev-work/verification-gate/scaling/": "scaling",
    "files/dev-work/verification-gate/adapters/": "native-desktop",
    "files/dev-tools/": "real-engine",
    "files/tests/macos_gui_driver" + _PY: "real-app-launch",
    "files/tests/manual_plan3_harness" + _PY: "native-desktop",
    "files/tests/manual_plan6_harness" + _PY: "native-desktop",
    "files/tests/manual_windows_ui_prototype" + _PY: "native-desktop",
    # The production application, setup and release builder, started from this checkout's real files (a disposable copy a
    # test makes elsewhere is the test's own and is judged by the test's declarations instead).
    "scripts/launcher" + _PY: "real-app-launch",
    "scripts/shared/bootstrap" + _PY: "install",
    "scripts/shared/release" + _PY: "release-build",
    "Setup_and_Run-audiobook-creation-tool.bat": "install",
    "Setup_and_Run-audiobook-creation-tool.command": "install",
}
DATA_ONLY = frozenset({"--help", "-h"})
ENGINE_ENVIRONMENTS = (".venv/engines/", ".venv-qwen3/", ".venv-omnivoice/", "files/dev-work/qwen3-eval/.venv/")
#: The one reviewed engine-interpreter launch (the guarded runner's "read-only-calm-library-selfcheck" profile): fixed
#: library methods and configuration are inspected, no model is constructed or loaded.
ENGINE_EXCEPTIONS = (("files/dev-tools/qwen3_calm_venv_tools" + _PY, "selfcheck"),)
INSTALLERS = frozenset({"winget", "brew", "msiexec", "choco", "apt", "apt-get", "port"})
_SCRIPT = re.compile(r"\.(py|pyw|bat|cmd|command|ps1|sh)$", re.IGNORECASE)
#: Only an interpreter or a shell runs a script named in its arguments; ``git check-ignore x.py`` runs nothing.
_PYTHON = re.compile(r"^(python|pythonw|py)(\d+(\.\d+)*)?w?$")
_SHELLS = frozenset({"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "dash"})
#: Hand a file or an application to the desktop, as os.startfile does.
_DESKTOP = frozenset({"explorer", "xdg-open", "open"})
_WATCHED = frozenset({"subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec", "os.posix_spawn"})


class EffectRefused(PermissionError):
    """A heavyweight effect asked for in routine verification. Refused before the operation; recorded either way."""


_lock = threading.RLock()
_refusals: list[dict] = []
_expected_depth = 0
_installed = False
_table: dict | None = None


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
    row = {"effect": effect, "detail": str(detail)[:500], "origin": origin, "pid": os.getpid(),
           "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session")}
    _record(row)
    raise EffectRefused(f"refused in routine verification: {effect}: {detail} (needs a Phase 1A-2 admission; GATE.md)")


def _check(effect: str) -> None:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}; the vocabulary is {sorted(EFFECTS)}")


def _record(row: dict) -> None:
    with _lock:
        row["expected"] = _expected_depth > 0
        _refusals.append(row)
    path = os.environ.get(LEDGER_ENV)
    if path:
        try:
            with open(path, "a", encoding="utf-8") as sink:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass  # the refusal itself still stands, and this process's record still has it


def refusals() -> list[dict]:
    with _lock:
        return [dict(row) for row in _refusals]


def unexpected() -> list[dict]:
    return [row for row in refusals() if not row.get("expected")]


@contextlib.contextmanager
def expected_refusals():
    """For the synthetic negative controls of these mechanisms only: refusals inside the block are recorded as expected.
    It grants nothing -- the operation is still refused -- and it is never a way to run real work."""
    global _expected_depth
    with _lock:
        _expected_depth += 1
    try:
        yield
    finally:
        with _lock:
            _expected_depth -= 1


def read_ledger(path) -> list[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append({"effect": "unknown", "detail": f"unreadable ledger line {line[:120]!r}", "expected": False})
    return rows


# --------------------------------------------------------------------------- #
#  Launches
# --------------------------------------------------------------------------- #
def _load_table() -> dict:
    global _table
    if _table is None:
        try:
            table = json.loads(POLICY_FILE.read_text(encoding="utf-8")).get("entrypoints", {})
            _table = {key: value for key, value in table.items() if key != "about" and isinstance(value, dict)}
        except (OSError, ValueError, AttributeError):
            _table = {}  # fail closed: every path below a heavy root is refused
    return _table


def _argv(command) -> list[str]:
    if isinstance(command, (bytes, bytearray)):
        command = command.decode("utf-8", "replace")
    if isinstance(command, str):
        try:
            return shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return command.split()
    if isinstance(command, os.PathLike):
        return [os.fspath(command)]
    return [os.fsdecode(part) if isinstance(part, (bytes, os.PathLike)) else str(part) for part in command]


def _inside(path: str, cwd) -> str | None:
    """``path`` relative to this checkout's real root, ``/``-separated, or None when it lies elsewhere."""
    text = path.strip("\"'")
    try:
        candidate = Path(text) if os.path.isabs(text) else Path(os.fspath(cwd) if cwd else os.getcwd()) / text
        real, root = os.path.realpath(candidate), os.path.realpath(REPO_ROOT)
    except (OSError, ValueError, TypeError):
        return None
    folded, folded_root = os.path.normcase(real), os.path.normcase(root)
    if folded != folded_root and not folded.startswith(folded_root.rstrip(os.sep) + os.sep):
        return None
    return Path(os.path.relpath(real, root)).as_posix()


def _rule(relative: str) -> tuple[str, str] | None:
    """(heavy root, its effect) for a checkout-relative path, matching case-insensitively (NTFS/APFS default)."""
    lowered = relative.lower()
    for root, effect in HEAVY_ROOTS.items():
        key = root.lower()
        if lowered == key or (key.endswith("/") and lowered.startswith(key)):
            return root, effect
    return None


def _script_of(argv: list[str], name: str) -> str | None:
    """The script an interpreter or shell would run: Python's first operand (none after ``-c`` or ``-m``), a shell's first
    script-named argument. Any other program's arguments are data, never a script."""
    args = argv[1:]
    if _PYTHON.match(name):
        skip = False
        for arg in args:
            if skip:
                skip = False
            elif arg in ("-c", "-m"):
                return None
            elif arg in ("-X", "-W", "-Q"):
                skip = True
            elif not arg.startswith("-"):
                return arg
        return None
    if name in _SHELLS:
        return next((arg for arg in args if _SCRIPT.search(arg.strip("\"'"))), None)
    return None


def classify_launch(command, cwd=None) -> tuple[str, str] | None:
    """``(effect, why)`` when routine verification may not start this command, else None. Pure apart from path resolution."""
    argv = _argv(command)
    if not argv:
        return None
    head = os.path.basename(argv[0].strip("\"'")).lower()
    name = head.rsplit(".", 1)[0] if head.endswith((".exe", ".cmd", ".bat")) else head
    if name in INSTALLERS:
        return "install", f"a package manager or installer: {' '.join(argv[:4])}"
    tokens = [token.lower() for token in argv]
    pip = name in ("pip", "pip3") or ("-m" in tokens and tokens[tokens.index("-m") + 1:tokens.index("-m") + 2] == ["pip"])
    if pip and "install" in tokens and "--no-index" not in tokens:
        return "external-network", "an online pip install (no --no-index)"
    if name in _DESKTOP:
        return "native-desktop", f"a desktop hand-off: {' '.join(argv[:3])}"
    interpreter = _inside(argv[0], cwd)
    script = _script_of(argv, name)
    script_relative = _inside(script, cwd) if script else None
    if interpreter and any(interpreter.lower().startswith(env.lower()) for env in ENGINE_ENVIRONMENTS):
        if not any(script_relative == path and word in argv for path, word in ENGINE_EXCEPTIONS):
            return "real-engine", f"an interpreter of a real engine environment ({interpreter})"
    targets = [relative for relative in (script_relative, interpreter if _SCRIPT.search(argv[0].strip("\"'")) else None)
               if relative]
    for relative in targets:
        rule = _rule(relative)
        if rule is None:
            continue
        entry = {key.lower(): value for key, value in _load_table().items()}.get(relative.lower()) or {}
        disposition = entry.get("routine", "refused")
        if disposition == "bounded":
            return None
        allowed = DATA_ONLY | set(entry.get("data_only", []))
        if disposition == "data-only" and allowed & set(argv[1:]):
            return None
        if disposition == "refused" and DATA_ONLY & set(argv[1:]):
            return None
        effects = entry.get("effects") or [rule[1]]
        return effects[0], f"a heavyweight entrypoint of this checkout ({relative}; {entry.get('class', 'unclassified')})"
    return None


def _audit(event: str, args) -> None:
    if event not in _WATCHED:
        return
    if event == "os.startfile":
        refuse("native-desktop", f"os.startfile({str(args[0])[:200]!r}) hands a file to the desktop", origin=event)
    if event == "subprocess.Popen":
        command, cwd = args[1], args[2]
    elif event == "os.system":
        command, cwd = args[0], None
    else:
        command, cwd = (args[1] if len(args) > 1 else args[0]), None
    verdict = classify_launch(command, cwd)
    if verdict is not None:
        refuse(verdict[0], verdict[1], origin=event)


def install() -> None:
    """Make this process a routine verification process. Idempotent. Called before tests can be imported."""
    global _installed
    scrub()
    os.environ[CONTEXT_ENV] = ROUTINE
    os.environ[ROOT_ENV] = os.path.realpath(REPO_ROOT)
    with _lock:
        if _installed:
            return
        _installed = True
    _load_table()
    sys.addaudithook(_audit)


def in_routine_context(environ=None) -> bool:
    return (os.environ if environ is None else environ).get(CONTEXT_ENV) == ROUTINE


def within_marked_root(origin) -> bool:
    """Whether ``origin`` lies in the checkout that set the routine marker (``ROOT_ENV``). Unknown means yes (fail closed)."""
    root = os.environ.get(ROOT_ENV)
    if not root or not origin or str(origin) in ("-c", "-m", "-"):
        return True
    try:
        real = os.path.normcase(os.path.realpath(origin))
        base = os.path.normcase(os.path.realpath(root))
    except (OSError, ValueError, TypeError):
        return True
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def refuse_under_routine(entry: str, argv=None, *, data_only=frozenset(), origin=None) -> None:
    """For a real test driver's ``__main__``: refuse to start inside routine verification (the marker is inherited by every
    child of a routine pytest process). Data-only flags (``--help``) stay usable. Exits ``REFUSED_EXIT``. A copy of the
    driver outside the marked checkout is the launching test's own (see ``within_marked_root``)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not in_routine_context() or (DATA_ONLY | set(data_only)) & set(argv):
        return
    if not within_marked_root(sys.argv[0] if origin is None else origin):
        return
    row = {"effect": "real-app-launch", "detail": f"{entry} refused to start under {CONTEXT_ENV}={ROUTINE}",
           "origin": "entrypoint", "pid": os.getpid(), "test": os.environ.get("PYTEST_CURRENT_TEST", "child")}
    _record(row)
    sys.stderr.write(f"{entry}: refused: a heavyweight entrypoint does not start inside routine verification (GATE.md)\n")
    raise SystemExit(REFUSED_EXIT)
