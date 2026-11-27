"""The reviewed bounded fixture and measurement families of routine verification (v0.8.2 Phase 1A-1 R2, D-R2-2..4).

A launch the general rules of ``routine_effects.decide_launch`` would refuse -- a shell, a native helper, a startup
measurement that must run before any envelope, a native process creation -- may still run when it is *positively*
identified here as one of a small number of reviewed families: the exact program (resolved, by its bytes where it is a
fixture), the exact arguments, the working directory, the environment that matters and the disposable paths it touches.
Fixture sources are pinned by the SHA-256 of their text (line endings normalized, as ``write_text`` writes them on
Windows); a modified source, target or environment is not the reviewed family and falls back to the general rules
(normally a refusal). Recognition is side-effect free: it reads the files it identifies and nothing else.

Standard library only; loaded by path in every routine verification process, so it imports nothing of the application.
"""

from __future__ import annotations

import ast
import hashlib
import io as _io  # the original open: a test patching builtins.open never reaches it
import os
import re
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PY = ".py"
STAGE_ZERO = REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1"
SETUP_BAT = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
MACOS_LAUNCHER = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command"
CONTAINMENT = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "adapters" / "windows" / ("containment" + _PY)
GATE_SCALING = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "scaling"
BOOTSTRAP_MODULE = REPO_ROOT / "scripts" / "shared" / ("bootstrap" + _PY)
CLONE_TRANSCRIPT_EXTRACT = REPO_ROOT / "files" / "dev-tools" / ("clone_transcript_extract" + _PY)

#: SHA-256 of each reviewed fixture source (text, LF line endings). The value is the exact text the named test writes.
PINNED = {
    # test_tk_proof.BREAK_TK: a sitecustomize that fails Tk() the way a missing tk.tcl does; Tcl() keeps working.
    "tk-break-tk": "6efba300f52204afdf28c6e57bfaaf4f695df417d7cc4995fcd789e61b16bd54",
    # test_tk_proof.HANG: a sitecustomize that records its pid and never returns (a hung Tk, bounded by the production
    # timeout, which is what the tests measure).
    "tk-hang": "ff53d3af719c563e56ab40872d9190b4478df1a95210d5fcee13f566a7ed5237",
    # test_optional_tts_setup.SITECUSTOMIZE: the tripwire of the disposable app copy's own venv.
    "optional-tts-tripwire": "345732fdee341ce74f5d9972290f9b486cb83199f05dda9dfe3e358e9b460cc8",
    # test_qwen3_synth.FAKE_FFMPEG: the stand-in encoder behind fake_ffmpeg.cmd.
    "fake-ffmpeg": "e49f3d673e94b8bdff8883d53055651f4d94988e34f0cb6a541050edfefd8371",
}

#: test_optional_tts_setup.PRE_VENV_PROBE, the import-footprint measurement (D-R2-3). It must run in a bare ``-I -S``
#: interpreter with nothing loaded before it, so it runs unchanged; these are its only two reviewed forms.
PRE_VENV_PROBE = '''\
import json, sys
sys.path.insert(0, {scripts!r})
from shared import optional_setup_protocol
from tts import optional_setup
{extra}
optional_setup.plan_to_json(optional_setup.estimate(optional_setup_protocol.COMPONENTS))
print(json.dumps(sorted(sys.modules)))
'''
PRE_VENV_EXTRAS = ("", "from tts import qwen3_setup")

#: test_dialog_containment._low_python's probe (D-R2-4: the Low-integrity native profile).
LOW_PROBE = "import sys; sys.path.insert(0, {source!r}); import containment as c; print(hex(c.integrity_of()))"
#: test_dialog_containment.test_a_low_process_writes_its_labelled_scratch_and_nothing_beside_it: the Low child tries one
#: append to each of four fixed paths (three in its labelled scratch, one beside it, which integrity must refuse).
LOW_SCRATCH_PROBE = ("import json, sys\nfrom pathlib import Path\nresult = {{}}\n"
                     "for name, path in (('earlier', {earlier!r}), ('later', {later!r}), ('new', {new!r}),"
                     " ('beside', {beside!r})):\n"
                     "    try:\n        open(path, 'a').write('low'); result[name] = 'written'\n"
                     "    except OSError as exc:\n        result[name] = f'refused {{type(exc).__name__}}'\n"
                     "print(json.dumps(result))\n")

#: test_verification_gate_contract.test_the_decoders_console_host_is_found_among_the_jobs_processes: its child's program.
CONSOLE_HOST = '''
import json, subprocess, sys
sys.path.insert(0, {scaling!r})
import winjob
job = winjob.Job()
child = subprocess.Popen(["cmd.exe", "/d", "/k"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    child.stdin.write(b"rem\\r\\n")
    child.stdin.flush()
    found = []
    for _ in range(200):
        found = job.children_of(child.pid)
        if found:
            break
        import time; time.sleep(0.05)
    facts = [dict(image=c["image"], peak=winjob.process_facts(c["handle"]).get("peak_commit")) for c in found]
    for c in found:
        winjob.close_handle(c["handle"])
    print(json.dumps({{"ids": len(job.process_ids()), "found": facts, "strangers": job.children_of(0)}}))
finally:
    child.stdin.close()
    child.wait(30)
'''

#: test_venv_recovery._sandbox's stub bootstrap: it logs its arguments and exits with the codes the test chose.
SETUP_STUB = re.compile(
    r"import sys, pathlib\n"
    r"log = pathlib\.Path\(__file__\)\.resolve\(\)\.parents\[2\] / 'calls\.log'\n"
    r"with log\.open\('a', encoding='utf-8'\) as fh:\n"
    r"    fh\.write\(' '\.join\(sys\.argv\[1:\]\) \+ '\\n'\)\n"
    r"sys\.exit\(-?\d{1,3} if '--launch-only' in sys\.argv else -?\d{1,3}\)\n\Z")

#: test_release_packaging's interpreter shim and stage-0 stand-in for the packaged macOS launcher.
BASH_SHIM = ('#!/bin/bash\n'
             'printf "%s %s\\n" "$0" "$*" >> "$RC_CALLS"\n'
             'case "$*" in\n'
             '  *--launch-only*) exit "$RC_LAUNCH_EXIT" ;;\n'
             '  --version) echo "Python 3.12 shim" ;;\n'
             'esac\n'
             'exit 0\n')
BASH_STAGE0 = '#!/bin/bash\nprintf "stage0 %s\\n" "$*" >> "$RC_CALLS"\nexit 0\n'
BASH_SHIM_PATHS = (".venv/bin/python", "files/runtime-data/python/bin/python3.12", "shim-bin/python3.12")

#: The largest file that is certainly not a runnable program (a PE or Mach-O image is far larger): a deliberately invalid
#: stub a control expects to fail to start.
INERT_STUB_MAX = 64
#: The product's one NVIDIA query (scripts/tts/qwen3_runtime.py ``_query_nvidia_smi``): read-only, exact.
NVIDIA_QUERY = ["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
#: The reviewed exact NVIDIA queries: the product's (above) and files/dev-tools/qwen_eval_cli.py ``current_gpu`` (name and
#: compute capability, 30 s timeout), which test_qwen_evaluation reaches. Nothing else, no sampling loop, no stress.
NVIDIA_QUERIES = (NVIDIA_QUERY, ["--query-gpu=name,compute_cap", "--format=csv,noheader"])
#: Git subcommands that only read (anywhere); every other subcommand runs only on a repository in the disposable roots.
GIT_READ = frozenset({"status", "rev-parse", "ls-files", "log", "show", "diff", "cat-file", "check-ignore", "ls-tree",
                      "describe", "merge-base", "for-each-ref", "rev-list", "blame", "grep", "var", "version",
                      "symbolic-ref", "show-ref", "diff-tree", "diff-index", "diff-files", "check-attr", "name-rev",
                      "count-objects", "verify-commit", "--version", "help", "config", "hash-object", "shortlog",
                      "whatchanged", "cherry", "range-diff", "ls-remote-local"})
GIT_NETWORK = frozenset({"fetch", "pull", "push", "ls-remote", "remote", "submodule", "credential", "daemon",
                         "send-email", "request-pull", "http-fetch", "http-push", "upload-pack", "receive-pack",
                         "archive", "bundle", "svn", "p4", "instaweb", "fsmonitor--daemon", "maintenance", "gc", "lfs"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"})
_WIN = os.name == "nt"


def _text_digest(path) -> str | None:
    try:
        with _io.open(path, "rb") as handle:
            data = handle.read(1 << 20)
    except OSError:
        return None
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _pinned(path, family: str) -> bool:
    return _text_digest(path) == PINNED[family]


def _text(path) -> str | None:
    try:
        with _io.open(path, "rb") as handle:
            return handle.read(1 << 20).decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None


def _same(a, b) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError, TypeError):
        return False


def _bytes_equal(a, b) -> bool:
    try:
        with _io.open(a, "rb") as one, _io.open(b, "rb") as two:
            return one.read() == two.read()
    except OSError:
        return False


_constants: dict | None = None


def _production_constants() -> dict:
    """The production probe texts of ``scripts/shared/bootstrap.py`` of the marked checkout (read, never imported)."""
    global _constants
    if _constants is None:
        found = {}
        try:
            tree = ast.parse(BOOTSTRAP_MODULE.read_text(encoding="utf-8"))
            for node in tree.body:  # _TK_PROOF_LINES first: _VENV_PROBE is built from it
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                        and node.targets[0].id in ("_VENV_PROBE", "_TK_PROOF_LINES"):
                    # Only string arithmetic over these two constants, evaluated with no builtins at all.
                    expression = compile(ast.Expression(node.value), str(BOOTSTRAP_MODULE), "eval")
                    found[node.targets[0].id] = eval(expression, {"__builtins__": {}}, dict(found))  # noqa: S307
        except (OSError, SyntaxError, ValueError):
            pass
        codes = set()
        if isinstance(found.get("_VENV_PROBE"), str):
            codes.add(found["_VENV_PROBE"])
        if isinstance(found.get("_TK_PROOF_LINES"), tuple):
            codes.add("\n".join(found["_TK_PROOF_LINES"]))
        _constants = {"tk_codes": frozenset(codes)}
    return _constants


def _pythonpath_shim(env: dict, family: str, disposable) -> bool:
    """The child's PYTHONPATH is exactly one disposable folder holding exactly the pinned sitecustomize of ``family``."""
    entries = [entry for entry in (env.get("PYTHONPATH") or "").split(os.pathsep) if entry]
    if len(entries) != 1 or not disposable(entries[0]) or not os.path.isdir(entries[0]):
        return False
    names = {name for name in os.listdir(entries[0]) if name != "__pycache__"}
    return names == {"sitecustomize.py"} and _pinned(os.path.join(entries[0], "sitecustomize.py"), family)


def _python_c(facts, *flags) -> str | None:
    """The code of ``<trusted interpreter> <flags> -c <code>`` exactly, or None."""
    command = facts["python"]
    if command is None or command.mode != "code" or command.rest or list(command.flags) != list(flags):
        return None
    if facts["interpreter_kind"](facts["program"]) != "trusted":
        return None
    return command.target


def _profile(name: str, reason: str, **extra) -> dict:
    return {"outcome": "profile", "profile": name, "reason": reason, **extra}


def _leaf(name: str, reason: str, **extra) -> dict:
    """A reviewed program that starts nothing further: the environment it is given cannot carry anything onward."""
    return _profile(name, reason, leaf=True, **extra)


# --------------------------------------------------------------------------- #
#  The families
# --------------------------------------------------------------------------- #
def _tk_proof(facts) -> dict | None:
    """D-R2-2: the tk_proof startup faults. BREAK_TK runs through the bootstrap with its PYTHONPATH kept (the fault is
    loaded at startup and the program is the ordinary probe); HANG never reaches a program, so it runs unchanged as a
    bounded startup measurement whose end is the production timeout's kill, with parent-side evidence only."""
    env, disposable = facts["env"], facts["disposable"]
    if not env.get("PYTHONPATH"):
        return None
    code = _python_c(facts)
    if code is None:
        return None
    if _pythonpath_shim(env, "tk-break-tk", disposable):
        return {"outcome": "bootstrap", "profile": "tk-proof-break-tk", "expect": "routine-child", "keep_pythonpath": True,
                "reason": "the reviewed tk_proof fault (BREAK_TK) on this interpreter"}
    if _pythonpath_shim(env, "tk-hang", disposable) and code in _production_constants()["tk_codes"] \
            and env.get("ACT_HANG_PID_FILE") and disposable(env["ACT_HANG_PID_FILE"]):
        return _profile("tk-proof-hang", "the reviewed tk_proof hang (HANG) under a production Tk probe and its bound")
    return None


def _footprint(facts) -> dict | None:
    """D-R2-3: the pre-venv import-footprint probe, in the base interpreter with ``-I -S``, unchanged."""
    command = facts["python"]
    if command is None or command.mode != "code" or command.rest or list(command.flags) != ["-I", "-S"]:
        return None
    base = getattr(sys, "_base_executable", "") or sys.executable
    if not _same(facts["program"], base) or not facts["disposable"](facts["cwd"]):
        return None
    scripts = str(REPO_ROOT / "scripts")
    if command.target in {PRE_VENV_PROBE.format(scripts=scripts, extra=extra) for extra in PRE_VENV_EXTRAS}:
        return _profile("pre-venv-import-footprint", "the reviewed pre-venv import-footprint measurement")
    return None


def _powershell(facts) -> dict | None:
    argv, disposable = facts["argv"], facts["disposable"]
    if facts["name"] != "powershell" or not _same(facts["program"], _system32("WindowsPowerShell", "v1.0",
                                                                             "powershell.exe")):
        return None
    if argv[1:4] == ["-NoProfile", "-NonInteractive", "-Command"] and len(argv) == 5 \
            and argv[4] == _module_string(CLONE_TRANSCRIPT_EXTRACT, "_OWNER_ONLY_PS"):
        # files/dev-tools/clone_transcript_extract.py ``_restrict_to_owner``: the fixed owner-only DACL script (.NET ACL calls
        # on the one file its environment names, which must be disposable; it starts nothing).
        target = facts["env"].get("CTE_PRIVATE_TARGET", "")
        if target and os.path.isabs(target) and disposable(target):
            return _leaf("owner-only-acl", "the reviewed owner-only access restriction of a disposable artifact")
        return None
    if argv[1:5] != ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"] or len(argv) < 6:
        return None
    script, rest = argv[5], argv[6:]
    if os.path.basename(script).lower() == "bootstrap_host.ps1" and _bytes_equal(script, STAGE_ZERO):
        return _stage_zero(script, rest, disposable, facts["env"])
    if os.path.basename(script).lower() == "harness.ps1" and not rest and disposable(script):
        return _tk_harness(script, disposable)
    return None


def _stage_zero(script, rest, disposable, env=None) -> dict | None:
    """Stage 0, never downloading: declined (-AssumeNo), or offline with a disposable archive or installer to judge.

    R3-02: only a disposable copy, in a disposable app folder that holds no interpreter stage 0 would prove before it asks
    (its ``files/runtime-data/python/python.exe`` absent or a small inert stub, never a link), started by Windows
    PowerShell with no profile and no module path a test could have planted. The checkout's own stage 0 is never run: its
    first act is to run this checkout's real interpreter with a Tk proof, before any consent."""
    if _same(script, STAGE_ZERO) or not disposable(script):
        return None
    app = Path(script).parents[2]
    if not disposable(app) or not _unlinked(app, Path(script)):
        return None
    existing = app / "files" / "runtime-data" / "python" / "python.exe"
    if os.path.lexists(existing):
        if not _unlinked(app, existing) or not os.path.isfile(existing):
            return None
        if os.path.getsize(existing) > INERT_STUB_MAX and not _trusted_base_copy(existing):
            return None
    if not _module_path_reviewed((env or {}).get("PSMODULEPATH"), disposable):
        return None
    copy = True
    options, index = {}, 0
    switches = {"-AssumeNo", "-AssumeYes", "-NoWinget", "-IgnoreInstalled"}
    valued = {"-OutFile", "-ArchivePath", "-InstallerPath"}
    while index < len(rest):
        token = rest[index]
        if token in switches:
            options[token] = True
            index += 1
        elif token in valued and index + 1 < len(rest) and disposable(rest[index + 1]):
            options[token] = rest[index + 1]
            index += 2
        else:
            return None
    if "-OutFile" not in options or ("-AssumeNo" in options) == ("-AssumeYes" in options):
        return None
    if "-AssumeYes" in options and not ({"-ArchivePath", "-InstallerPath"} & set(options)):
        return None  # an accepted download is never routine
    if not copy and "-AssumeYes" in options and "-ArchivePath" in options:
        return None  # an offline unpack only ever into a disposable copy
    return _profile("stage-zero-offline", "stage 0, declined or judging a disposable offline archive")


def _trusted_base_copy(python: Path) -> bool:
    """A disposable copy of this session's own base interpreter that stage 0's proof may run (D-R2-2's stage-0 Tk
    measurement): its executable is byte-identical to the base interpreter's, its site-packages holds no startup code but
    the base's own ``.pth`` files (identical bytes) and, at most, the pinned BREAK_TK fault as ``sitecustomize.py``."""
    base = Path(sys.base_prefix)
    if not _bytes_equal(python, base / "python.exe"):
        return False
    site, base_site = python.parent / "Lib" / "site-packages", base / "Lib" / "site-packages"
    custom = site / "sitecustomize.py"
    if os.path.lexists(custom) and not _pinned(custom, "tk-break-tk"):
        return False
    if os.path.lexists(site / "usercustomize.py"):
        return False
    try:
        names = os.listdir(site)
    except OSError:
        return not os.path.lexists(site)
    return all(_bytes_equal(site / name, base_site / name) for name in names if name.lower().endswith(".pth"))


def _native(part: str) -> str:
    """A Git-for-Windows bash path (``/c/Users/...``) as the Windows path it names; any other path unchanged."""
    match = re.match(r"^/([A-Za-z])(/.*)?$", part) if os.name == "nt" else None
    return f"{match.group(1)}:{match.group(2) or '/'}" if match else part


def _unlinked(root: Path, path: Path) -> bool:
    """``path`` lies inside ``root`` with no component from ``root`` down a link or junction (never followed)."""
    try:
        relative = Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
    except ValueError:
        return False
    current = Path(os.path.abspath(root))
    for part in ("", *relative.parts):
        current = current / part if part else current
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return False
    return True


def _module_path_reviewed(value, disposable) -> bool:
    """A child PowerShell's PSModulePath names only folders this session inherited, or the system's and Program Files'
    own module folders: never one a test made (a planted module would shadow a cmdlet stage 0 calls)."""
    if not value:
        return True
    inherited = {os.path.normcase(part) for part in os.environ.get("PSModulePath", "").split(os.pathsep) if part}
    trusted = [os.path.normcase(folder) for folder in (os.environ.get("SystemRoot", r"C:\Windows"),
                                                       os.environ.get("ProgramFiles", r"C:\Program Files"),
                                                       os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))]
    for part in value.split(os.pathsep):
        if not part:
            continue
        folded = os.path.normcase(part)
        if disposable(part) or not os.path.isabs(part):
            return False
        if folded not in inherited and not any(folded == root or folded.startswith(root.rstrip("\\") + "\\")
                                               for root in trusted):
            return False
    return True


def _tk_harness(script, disposable) -> dict | None:
    """test_tk_proof's harness: the production Test-Candidate with a 1 s bound and an accelerated sleeper probe."""
    text = _text(script)
    stage = _text(STAGE_ZERO)
    if text is None or stage is None:
        return None
    match = re.search(r"function Test-Candidate\(.*?(?=^function )", stage, re.DOTALL | re.MULTILINE)
    head = re.match(r'\$ProbeTimeoutMs = 1000\n\$Probe = "import os,time;open\(r\'(?P<pid>[^\'\n]+)\',\'w\'\)\.write\('
                    r'str\(os\.getpid\(\)\)\);time\.sleep\(600\)"\n', text)
    if not match or not head or not disposable(head.group("pid")):
        return None
    tail = ("$sw = [Diagnostics.Stopwatch]::StartNew()\n"
            f"$r = Test-Candidate @('{sys.executable}')\n"
            "Write-Output ('RESULT=' + [string]($null -eq $r) + ' ELAPSED=' + [int]$sw.Elapsed.TotalSeconds)\n")
    if text != head.group(0) + match.group(0) + "\n" + tail:
        return None
    return _profile("tk-proof-stage-zero-harness", "the production Test-Candidate with an accelerated sleeper probe")


def _cmd_autorun() -> bool:
    """Whether cmd.exe runs an AutoRun command at startup (HKCU or HKLM ``Software\\Microsoft\\Command Processor``), which
    ``/d`` skips. Read-only; an unreadable key is treated as set (fail closed)."""
    global _autorun
    if _autorun is None:
        found = False
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Command Processor") as key:
                        value, _kind = winreg.QueryValueEx(key, "AutoRun")
                        found = found or bool(str(value).strip())
                except FileNotFoundError:
                    continue
        except (ImportError, OSError):
            found = True
        _autorun = found
    return _autorun


_autorun: bool | None = None


def _cmd(facts) -> dict | None:
    argv, disposable = facts["argv"], facts["disposable"]
    if facts["name"] != "cmd" or not _same(facts["program"], _system32("cmd.exe")):
        return None
    args = argv[1:]
    if (not args or args[0].lower() != "/d") and _cmd_autorun():
        return None  # R3-02: cmd's own startup would run an AutoRun command first
    if args == ["/c", "rem"]:
        return _profile("cmd-rem", "cmd /c rem (an empty console program)")
    if len(args) == 5 and args[:3] == ["/c", "mklink", "/J"] and all(disposable(path) for path in args[3:]):
        return _profile("disposable-junction", "a junction between two disposable paths")
    if args == ["/d", "/k"] and facts.get("child") == ("code", CONSOLE_HOST.format(scaling=str(GATE_SCALING))):
        return _profile("console-host-helper", "the gate contract's console-host helper (commands on stdin are fixed)")
    if len(args) == 2 and args[0] == "/c" and os.path.basename(args[1]) == SETUP_BAT.name:
        return _setup_bat(Path(args[1]), facts)
    return None


def _setup_bat(bat: Path, facts) -> dict | None:
    """test_venv_recovery's sandbox: the real launcher's bytes beside a stub bootstrap. Every fallback the launcher can
    reach is reviewed: the sandbox venv (a pip-less venv of this interpreter, or a deliberately unrunnable file), stage 0
    (absent from the sandbox, so PowerShell fails without running anything), and a Python on PATH -- which this recipe
    pins to the system folders and this session's base interpreter, so it can only ever run the stub."""
    root, disposable = bat.parent, facts["disposable"]
    if not disposable(root) or not _same(facts["cwd"], root) or not _bytes_equal(bat, SETUP_BAT):
        return None
    stub = _text(root / "scripts" / "shared" / ("bootstrap" + _PY))
    if stub is None or not SETUP_STUB.match(stub):
        return None
    if (root / "scripts" / "shared" / "bootstrap_host.ps1").exists() or (root / "files").exists():
        return None
    # R3-02: cmd searches the working directory (this sandbox) before PATH for every program the launcher names: nothing
    # runnable may stand there but the launcher itself, and nothing in the sandbox may be a link.
    runnable = {ext.lower() for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if ext} | {".ps1"}
    try:
        names = os.listdir(root)
    except OSError:
        return None
    if any(os.path.splitext(name)[1].lower() in runnable and name != SETUP_BAT.name for name in names):
        return None
    if not all(_unlinked(root, root / name) for name in names):
        return None
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        small = venv.stat().st_size <= INERT_STUB_MAX
        if not small and facts["interpreter_kind"](str(venv)) != "copy":
            return None
    base = os.path.dirname(getattr(sys, "_base_executable", "") or sys.executable)
    path = os.pathsep.join([_system32(), _system32("WindowsPowerShell", "v1.0"), base])
    return _profile("setup-bat-sandbox", "the setup launcher's sandbox recipe, every fallback pinned",
                    env_patch={"PATH": path})


def _fake_ffmpeg(facts) -> dict | None:
    program, disposable = facts["program"], facts["disposable"]
    if not program or os.path.basename(program).lower() != "fake_ffmpeg.cmd" or not disposable(program):
        return None
    script = os.path.join(os.path.dirname(program), "fake_ffmpeg" + _PY)
    if not _pinned(script, "fake-ffmpeg"):
        return None
    text = _text(program)
    if text is None or text.rstrip("\r\n") != f'@"{sys.executable}" "{script}" %*':  # written as text: \r\r\n endings
        return None
    return _profile("fake-ffmpeg-wrapper", "the reviewed stand-in encoder (a .cmd around the pinned fake script)")


_trusted_git: list = []


def _git_program() -> str | None:
    """The Git this session found on its own PATH the first time it asked (never a later test's changed PATH)."""
    if not _trusted_git:
        import shutil

        _trusted_git.append(shutil.which("git"))
        # The PATH's bash, kept only when it is Git for Windows' own (its root has cmd\git.exe): test_release_packaging
        # falls back to it when its Git candidates do not exist (git resolving to Git's mingw64\bin, as from Git Bash).
        found, own = shutil.which("bash"), None
        if found:
            found_path = Path(found).resolve()
            for root in (found_path.parent.parent, found_path.parent.parent.parent):
                if found_path in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe") \
                        and (root / "cmd" / "git.exe").is_file():
                    own = str(found_path)
        _trusted_git.append(own)
    return _trusted_git[0]


_git_program()  # once, at import: before any test can change PATH


def _git(facts) -> dict | None:
    if facts["name"] != "git":
        return None
    trusted = _git_program()
    if not trusted or not _same(facts["program"], trusted):
        return None
    args, repo = list(facts["argv"][1:]), facts["cwd"]
    while args and args[0].startswith("-"):
        option = args.pop(0)
        if option in _GIT_VALUE_OPTIONS:
            if not args:
                return None
            value = args.pop(0)
            if option == "-C":
                repo = value if os.path.isabs(value) else os.path.join(repo, value)
            elif option in ("--git-dir", "--work-tree"):
                repo = value
            elif option == "-c" and re.match(r"(?i)(core\.(sshcommand|gitproxy|fsmonitor|hookspath)|"
                                              r"credential\.|http\.|url\.|remote\.|protocol\.)", value) \
                    and value.lower() not in ("core.fsmonitor=false",) and not value.lower().startswith("core.hookspath="):
                return None
        elif option.startswith(("--git-dir=", "--work-tree=")):
            repo = option.split("=", 1)[1]
        elif option not in ("--no-pager", "--literal-pathspecs", "--no-optional-locks", "--bare", "--version", "-P"):
            return None
    if not args:
        return _leaf("git-read", "git with no subcommand")
    command = args[0]
    if command in GIT_NETWORK or any("://" in arg or re.match(r"^[\w.-]+@[\w.-]+:", arg) for arg in args):
        return None
    if command == "clone":
        sources = [arg for arg in args[1:] if not arg.startswith("-")]
        if len(sources) != 2 or not os.path.isdir(sources[0]) or not facts["disposable"](sources[1]):
            return None
        return _leaf("git-local-clone", "a local clone into a disposable path")
    if command == "init":
        # ``git init [-q] [--template=<dir>] [<directory>]``: the repository it creates is its directory argument (else the
        # working directory). A template's hooks would run later, so only no template or a disposable one is reviewed.
        rest, options, targets = list(args[1:]), [], []
        while rest:
            arg = rest.pop(0)
            if arg in ("-b", "--initial-branch"):  # the initial branch's name: a value, never a target
                if not rest or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", rest[0]):
                    return None
                rest.pop(0)
            elif arg.startswith("--initial-branch="):
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", arg.split("=", 1)[1]):
                    return None
            elif arg.startswith("-"):
                options.append(arg)
            else:
                targets.append(arg)
        if len(targets) > 1 or any(option not in ("-q", "--quiet", "--bare") and not option.startswith("--template=")
                                   for option in options):
            return None
        template = next((option.split("=", 1)[1] for option in options if option.startswith("--template=")), "")
        if template and not facts["disposable"](template if os.path.isabs(template) else os.path.join(repo, template)):
            return None
        target = targets[0] if targets else repo
        if not facts["disposable"](target if os.path.isabs(target) else os.path.join(repo, target)):
            return None
        return _leaf("git-disposable-repository", "git init of a disposable repository")
    if command == "hash-object" and "-w" in args and not facts["disposable"](repo):
        return None
    if command == "config" and not facts["disposable"](repo) and \
            not any(arg in ("--get", "--get-all", "-l", "--list", "--get-regexp", "--show-origin") for arg in args):
        return None
    if command in GIT_READ:
        return _leaf("git-read", f"git {command} (read-only)")
    if facts["disposable"](repo):
        return _leaf("git-disposable-repository", f"git {command} on a disposable repository")
    return None


def _media(facts) -> dict | None:
    """An installed ffmpeg/ffprobe (never a disposable file of that name) on disposable outputs; no network URL. An input
    outside the disposable roots is only ever read (it must exist and is never the output)."""
    name, program, argv, disposable = facts["name"], facts["program"], facts["argv"], facts["disposable"]
    if name not in ("ffmpeg", "ffprobe") or not program or disposable(program) or not os.path.isfile(program):
        return None
    if any("://" in arg or arg.lower().startswith(("http:", "https:", "rtmp:", "tcp:", "udp:")) for arg in argv[1:]):
        return None
    if argv[1:] in (["-version"], ["-hide_banner", "-version"]):
        return _leaf("media-version", f"{name} -version")
    for arg in argv[1:]:
        if os.path.isabs(arg) and not disposable(arg) and not (os.path.exists(arg) and name == "ffprobe"):
            if not os.path.exists(arg) or arg == argv[-1]:
                return None  # a new or overwritten file outside the disposable roots
    if name == "ffmpeg" and not (disposable(argv[-1]) or argv[-1] in ("-", "pipe:1", "pipe:", "NUL", os.devnull)):
        return None
    return _leaf("media-disposable", f"{name} on disposable files")


def _windows_tools(facts) -> dict | None:
    name, argv = facts["name"], facts["argv"]
    if name == "tasklist" and _same(facts["program"], _system32("tasklist.exe")) and len(argv) == 4 \
            and argv[1] == "/FI" and re.fullmatch(r"PID eq [1-9][0-9]*", argv[2]) and argv[3] == "/NH":
        return _leaf("pid-read", "tasklist of one pid")
    if name == "taskkill" and _same(facts["program"], _system32("taskkill.exe")):
        args = argv[1:]
        flags = {arg.upper() for arg in args if arg.upper() in ("/F", "/T")}
        if "/PID" not in [arg.upper() for arg in args]:
            return None
        at = [arg.upper() for arg in args].index("/PID")
        if at + 1 >= len(args) or not args[at + 1].isdigit() or len(args) != 2 + len(flags) or "/F" not in flags:
            return None
        pid = int(args[at + 1])
        if pid not in facts["owned_pids"]:
            return None  # only a process this session started and still owns
        return _leaf("owned-stop", "taskkill of a launch this process owns", stops=((pid, "/T" in flags),))
    if name == "nvidia-smi" and list(argv[1:]) in NVIDIA_QUERIES and _same(facts["program"], _system32("nvidia-smi.exe")):
        # Each reviewed query is read-only and bounded by its caller's own timeout; R1 admitted any nvidia-smi command line,
        # R2 only these exact ones from the driver's installed copy.
        return _leaf("gpu-query", "a reviewed read-only NVIDIA GPU query")
    program, disposable = facts["program"], facts["disposable"]
    if program and disposable(program) and _bytes_equal(program, _system32("PING.EXE")):
        args = argv[1:]
        if len(args) == 3 and args[0] == "-n" and args[1].isdigit() and args[2] in ("127.0.0.1", "::1", "localhost"):
            return _leaf("loopback-sleeper", "a disposable copy of PING on loopback (a controlled sleeper)")
    return None


def _inert(facts) -> dict | None:
    program, disposable = facts["program"], facts["disposable"]
    if program and disposable(program) and os.path.isfile(program) and not re.search(
            r"\.(py|pyw|bat|cmd|ps1|sh|command|vbs|js)$", program, re.IGNORECASE):
        try:
            small = os.path.getsize(program) <= INERT_STUB_MAX
        except OSError:
            small = False
        if small:
            return _leaf("inert-stub", "a deliberately invalid program stub (it cannot start)")
    return None


def _bash(facts) -> dict | None:
    """test_release_packaging: Git for Windows' bash (or /bin/bash) for ``-c "exit 0"``, ``-n`` on the packaged launcher,
    and the packaged launcher itself run against the reviewed interpreter shims."""
    if facts["name"] != "bash" or not facts["program"]:
        return None
    allowed = {"/bin/bash", "/usr/bin/bash"}
    git = _git_program()
    if git:
        install = Path(git).resolve().parent.parent
        allowed |= {str(install / "bin" / "bash.exe"), str(install / "usr" / "bin" / "bash.exe")}
    if _trusted_git[1]:
        allowed.add(_trusted_git[1])  # Git for Windows' bash found on the session's PATH (see _git_program)
    if not any(_same(facts["program"], path) for path in allowed if os.path.exists(path)):
        return None
    args, disposable = facts["argv"][1:], facts["disposable"]
    env = facts["env"]
    if any(env.get(name) for name in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "PS4")) or \
            any(key.startswith("BASH_FUNC_") for key in env):
        return None  # R3-02: startup code or exported functions a non-interactive bash runs or imports first
    if args == ["-c", "exit 0"]:
        return _profile("bash-probe", "bash -c 'exit 0'")
    if len(args) == 2 and args[0] == "-n" and _bytes_equal(os.path.join(facts["cwd"], args[1]), MACOS_LAUNCHER):
        return _leaf("bash-parse-only", "bash -n over the launcher's exact bytes (parsed, never run)")
    if len(args) == 1 and disposable(args[0]) and os.path.basename(args[0]) == MACOS_LAUNCHER.name \
            and _bytes_equal(args[0], MACOS_LAUNCHER):
        root = Path(args[0]).parent
        if not all(_text(root / relative) == BASH_SHIM for relative in BASH_SHIM_PATHS):
            return None
        if _text(root / "scripts" / "shared" / "bootstrap_host_macos.sh") != BASH_STAGE0:
            return None
        parts = env.get("PATH", "").split(":")
        first = parts[0]
        if not first.endswith("/shim-bin") or not env.get("RC_CALLS") or not disposable(env["RC_CALLS"]):
            return None
        if not disposable(_native(first)) or any(disposable(_native(part)) or not part.startswith("/")
                                                 for part in parts[1:] if part):
            return None  # R3-02: helpers resolve to the reviewed shims, then only to system folders
        return _profile("packaged-launcher-shims", "the packaged macOS launcher against the reviewed shims")
    return None


#: The v3 optional-setup planning workers (D-R2-9): each production launcher gives its worker exactly this replacement
#: environment (six names; the temporary folders are the run's own root), and the tests assert it.
V3_ENVIRONMENT = frozenset({"SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"})
V3_SUPERVISOR = REPO_ROOT / "scripts" / "shared" / ("optional_setup_supervisor_v3" + _PY)
V3_BRIDGE = REPO_ROOT / "scripts" / "shared" / ("optional_setup_planning_bridge_v3" + _PY)
V3_READONLY = REPO_ROOT / "scripts" / "shared" / ("optional_setup_readonly_context_v3" + _PY)
V3_ADAPTER = "_planning_fixture" + _PY
#: Every v3 planning test adapter is ``FIXTURE_ADAPTER + "\n" + extra``: the reviewed prefix installs an irremovable audit
#: hook first (no socket, no os.system, only its one exact child, no heavy imports, reads in the run root or the standard
#: library, writes in the run root) and disables every install and acquisition path.
V3_ADAPTER_SOURCE = REPO_ROOT / "files" / "tests" / ("test_optional_setup_planning_worker_v3" + _PY)
_V3_TOKEN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_V3_SCENARIO = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_V3_MAX_FILES = 400
_strings: dict = {}


def _module_string(path: Path, name: str) -> str | None:
    """A module-level string constant of a marked-checkout source, read (never imported)."""
    key = (str(path), name)
    if key not in _strings:
        found = None
        try:
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                        and node.targets[0].id == name and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str):
                    found = node.value.value
        except (OSError, SyntaxError, ValueError):
            found = None
        _strings[key] = found
    return _strings[key]


_windows: list = []


def _windows_directory() -> str:
    """The real Windows directory, from the operating system (as production's ``system_directory`` takes it): never from
    this process's environment, which a test may have pointed elsewhere."""
    if not _windows:
        found = ""
        if _WIN:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemWindowsDirectoryW(buffer, len(buffer))
            found = buffer.value if 0 < length < len(buffer) else ""
        _windows.append(found)
    return _windows[0]


def _v3_environment(env: dict, root: str, disposable) -> bool:
    """Exactly the six-name worker environment, its temporary folders the disposable run root, offline, the real SystemRoot."""
    folded = {(key.upper() if _WIN else key): value for key, value in env.items()}
    folded.pop("__PYVENV_LAUNCHER__", None)
    if set(folded) != V3_ENVIRONMENT or not disposable(root) or not _windows_directory():
        return False
    return _same(folded["SYSTEMROOT"], _windows_directory()) and folded["HF_HUB_OFFLINE"] == "1" and \
        folded["TRANSFORMERS_OFFLINE"] == "1" and all(_same(folded[name], root) and os.path.normcase(folded[name]) ==
                                                      os.path.normcase(root) for name in ("TEMP", "TMP", "TMPDIR"))


#: test_optional_setup_readonly_context_v3's read-only worker launches: production's ``_BOOTSTRAP``, plus its negative
#: controls, whose code is assembled only from literals of the marked test module (never imported).
V3_READONLY_TESTS = REPO_ROOT / "files" / "tests" / ("test_optional_setup_readonly_context_v3" + _PY)
#: The one inert file a launch-boundary control adds beside the sources (never imported by the worker).
V3_INERT = {"unreviewed" + _PY: b"raise AssertionError"}
#: test_optional_setup_planning_worker_v3.test_changed_code_identity_refuses_before_launch('module'): the worker copy with
#: one comment line appended (behaviour unchanged). Production's pin must refuse it; the module-pin mutation control
#: disables that pin to prove it is the pin that refuses, so the envelope must not refuse this exact inert form first.
V3_COMMENTED = {os.path.join("tts", "optional_setup_planning_worker_v3" + _PY): b"\n# replaced\n"}
_readonly_codes: list = []


def _function_body(tree, name: str):
    return next((node.body for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)


def _v3_readonly_codes() -> frozenset:
    """Every reviewed ``-c`` program of a read-only worker launch: production's, the live-grandchild control's fixed program,
    and each worker refusal control: ``prefix + change + "\\n" [+ trace] [+ mutation block] + tail`` from that test's own
    literals (its fixed prefix, one of its ``changes`` values, its trace block, its mutation block with either of its two
    replacements, its fixed tail). Read from the marked checkout's source; a changed test changes the set."""
    if _readonly_codes:
        return _readonly_codes[0]
    codes = set()
    production = _module_string(V3_READONLY, "_BOOTSTRAP")
    if production:
        codes.add(production)
    try:
        tree = ast.parse(V3_READONLY_TESTS.read_text(encoding="utf-8"))
        body = _function_body(tree, "test_new_run_live_grandchild_is_rejected_and_reaped") or []
        for node in body:
            if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["code"] \
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                codes.add(node.value.value)
        body = _function_body(tree, "test_native_worker_refusal_controls") or []
        prefix = changes = trace = template = tail = None
        replacements = ()
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["changes"]:
                changes = ast.literal_eval(node.value)
            elif isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["code"] \
                    and isinstance(node.value, ast.Constant):
                prefix = node.value.value
            elif isinstance(node, ast.AugAssign) and getattr(node.target, "id", None) == "code":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if value.value.startswith("sys.exit("):
                        tail = value.value
                    else:
                        trace = value.value
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and \
                        value.func.attr == "replace" and isinstance(value.func.value, ast.Constant) and \
                        len(value.args) == 2 and isinstance(value.args[1], ast.IfExp):
                    template = value.func.value.value
                    replacements = (ast.literal_eval(value.args[1].body), ast.literal_eval(value.args[1].orelse))
                    marker = ast.literal_eval(value.args[0])
        if isinstance(changes, dict) and isinstance(prefix, str) and isinstance(trace, str) and isinstance(tail, str) \
                and isinstance(template, str) and len(replacements) == 2:
            mutations = [""] + [template.replace(marker, item) for item in replacements]
            for change in changes.values():
                for traced in ("", trace):
                    for mutation in mutations:
                        codes.add(prefix + change + "\n" + traced + mutation + tail)
    except (OSError, SyntaxError, ValueError, TypeError, UnboundLocalError, NameError):
        pass
    _readonly_codes.append(frozenset(codes))
    return _readonly_codes[0]


def _v3_copy_is_marked(scripts: str, allowed_extra: frozenset, inert: dict | None = None,
                       suffixed: dict | None = None) -> bool:
    """Every file of the worker's import root is byte-identical to the marked checkout's ``scripts/`` file of the same
    relative path (no link, no unknown file), except the reviewed test adapter names in ``allowed_extra``, the reviewed
    inert control files of ``inert`` (exact bytes) and the files of ``suffixed``, which may also be the marked bytes plus
    exactly that inert suffix."""
    base = REPO_ROOT / "scripts"
    count = 0
    for folder, directories, files in os.walk(scripts, followlinks=False):
        for name in directories:
            if os.path.islink(os.path.join(folder, name)):
                return False
        for name in files:
            count += 1
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, scripts)
            if count > _V3_MAX_FILES or os.path.islink(path):
                return False
            if relative in allowed_extra:
                continue
            if inert and relative in inert:
                try:
                    with _io.open(path, "rb") as handle:
                        if handle.read(len(inert[relative]) + 1) == inert[relative]:
                            continue
                except OSError:
                    pass
                return False
            if suffixed and relative in suffixed:
                try:
                    with _io.open(path, "rb") as one, _io.open(base / relative, "rb") as two:
                        actual, marked = one.read(), two.read()
                except OSError:
                    return False
                if actual in (marked, marked + suffixed[relative]):
                    continue
                return False
            if not _bytes_equal(path, base / relative):
                return False
    return count > 0


def _v3_workers(facts) -> dict | None:
    """D-R2-9: the reviewed v3 planning workers, each with its production six-name environment preserved exactly.

    - the supervisor's fixed fake worker (``optional_setup_supervisor_v3._FAKE_PROGRAM``, stdlib only, a closed scenario
      argument): an exact bounded worker, run unchanged under its Job with parent-side evidence;
    - the read-only context worker: the real reviewed worker over a byte-identical copy of the marked sources, which
      installs its own stricter isolation (no writes, sockets, subprocesses or unpinned imports), run unchanged;
    - the planning bridge worker: the real worker over a byte-identical copy of the marked sources plus the test's adapter,
      whose reviewed prefix installs its own stricter isolation first (see ``V3_ADAPTER_SOURCE``), run unchanged.

    The envelope cannot run inside these workers (their own audit hooks refuse its ledger writes), and their six-name
    environment is the production contract the tests assert, so each runs unchanged under its exact profile: the parent's
    Job owns it, the parent records its launch, pid and observed exit, and nothing else is admitted in that environment."""
    command, env, disposable = facts["python"], facts["env"], facts["disposable"]
    if command is None or list(command.flags) != ["-I", "-B", "-S"] or not _same(facts["program"], sys.executable):
        return None
    cwd = facts["cwd"]
    if command.mode == "script":
        script = command.target
        if os.path.basename(script) != "fake_worker" + _PY or not _same(os.path.dirname(script), cwd) \
                or len(command.rest) != 1 or not _V3_SCENARIO.fullmatch(command.rest[0]):
            return None
        program = _module_string(V3_SUPERVISOR, "_FAKE_PROGRAM")
        if program is None or _text(script) != program or not _v3_environment(env, cwd, disposable):
            return None
        return _profile("v3-supervisor-fake-worker", "the v3 supervisor's fixed fake worker, in its six-name environment",
                        scrubbed=True)
    if command.mode != "code" or len(command.rest) != 2 or not all(_V3_TOKEN.fullmatch(arg) for arg in command.rest):
        return None
    if os.path.basename(os.path.normpath(cwd)).lower() != "scripts" or not disposable(cwd):
        return None
    root = env.get("TEMP") or env.get("Temp") or ""
    if not _v3_environment(env, root, disposable):
        return None
    if command.target in _v3_readonly_codes():
        if not _v3_copy_is_marked(cwd, frozenset(), inert=V3_INERT):
            return None
        return _profile("v3-readonly-planning-worker", "the v3 read-only planning worker over the marked sources (its own "
                                                       "isolation), in its six-name environment", scrubbed=True)
    if command.target == _module_string(V3_BRIDGE, "_BOOTSTRAP"):
        adapter = os.path.join(cwd, V3_ADAPTER)
        prefix = _module_string(V3_ADAPTER_SOURCE, "FIXTURE_ADAPTER")
        if prefix is None or not os.path.isfile(adapter) or os.path.islink(adapter) \
                or os.path.getsize(adapter) > 64 * 1024 \
                or not _v3_copy_is_marked(cwd, frozenset({V3_ADAPTER}), suffixed=V3_COMMENTED):
            return None
        text = _text(adapter)
        if text is None or not text.startswith(prefix) or text[len(prefix):][:1] not in ("", "\n"):
            return None
        return _profile("v3-planning-worker", "the v3 planning worker over the marked sources, its test adapter opening "
                                              "with the reviewed containment prefix, in its six-name environment",
                        scrubbed=True)
    return None


#: D-R2-7: the OmniVoice worker network-guard measurements. In each, the real worker installs its own network guard and the
#: test proves that guard refuses (its NetworkRefused, its log). The envelope's network refusal must then be the last word,
#: not the first: these launches run through the bootstrap with the envelope's network hook deferred behind every hook the
#: program installs (``measurement: network-guard``), and that deferred hook still refuses any non-loopback event the
#: worker's guard let through, so no real network access happens and the test fails if the worker's guard is broken.
OV_SYNTH_TESTS = REPO_ROOT / "files" / "tests" / ("test_omnivoice_synth" + _PY)
OV_PHASE1_TESTS = REPO_ROOT / "files" / "tests" / ("test_omnivoice_phase1" + _PY)
OV_WORKER = REPO_ROOT / "scripts" / "tts" / ("omnivoice_worker" + _PY)
OV_P1_WORKER = REPO_ROOT / "files" / "dev-tools" / ("omnivoice_p1_worker" + _PY)
#: test_omnivoice_reference.test_the_worker_closes_the_network_before_anything_heavy_loads: its probe, around the worker's
#: folder (real lookups of two remote hosts and loopback, each refused by the worker's guard or allowed as loopback).
OV_REFERENCE_HEAD = "import json, socket, sys\nsys.path.insert(0, "
OV_REFERENCE_TAIL = (")\nimport omnivoice_worker as w\nlog = []\nw.install_network_guard(log)\nrefused = []\n"
                     "for host in ('huggingface.co', '8.8.8.8'):\n    try:\n        socket.getaddrinfo(host, 443)\n"
                     "    except w.NetworkRefused:\n        refused.append(host)\nsocket.getaddrinfo('127.0.0.1', 80)\n"
                     "print(json.dumps({'refused': refused, 'log': log}))\n")
#: test_omnivoice_phase1's ``_LOAD_WORKER`` around the dev-tools worker's path.
OV_P1_LOAD = ("import importlib.util, sys; spec = importlib.util.spec_from_file_location('w', {path!r}); "
              "w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)\n")
_OV_MEASUREMENT = {"measurement": "network-guard"}


def _function_code_literal(path: Path, function: str) -> str | None:
    """The string literal ``X`` of ``code = <name> + X`` in a test function of a marked-checkout source (never imported)."""
    try:
        body = _function_body(ast.parse(path.read_text(encoding="utf-8")), function) or []
    except (OSError, SyntaxError, ValueError):
        return None
    for node in body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["code"] \
                and isinstance(node.value, ast.BinOp) and isinstance(node.value.right, ast.Constant) \
                and isinstance(node.value.right.value, str):
            return node.value.right.value
    return None


def _ov_stack(launcher: str, rest, cwd: str, disposable) -> bool:
    """test_omnivoice_synth.stack_worker: the real worker, byte for byte, beside the reviewed stand-in torch and omnivoice
    (nothing else in the stack), started by the reviewed launcher on one job whose every output lies in its folder."""
    folder = os.path.dirname(launcher)
    if os.path.basename(launcher) != "launch_worker" + _PY or not disposable(folder) or len(rest) != 1:
        return False
    # The job's own folder is the working directory (the test's runner and the product's conversion both start it so).
    run = os.path.dirname(rest[0])
    if not _same(run, cwd) or not disposable(run) or not rest[0].lower().endswith(".json"):
        return False
    if _text(launcher) != _module_string(OV_SYNTH_TESTS, "STACK_LAUNCHER"):
        return False
    stack = os.path.join(folder, "stack")
    expected = {"omnivoice_worker" + _PY, "torch", "omnivoice", "__pycache__"}
    if not set(os.listdir(stack)) <= expected or not _bytes_equal(os.path.join(stack, "omnivoice_worker" + _PY), OV_WORKER):
        return False
    for name, constant in (("torch", "FAKE_TORCH"), ("omnivoice", "FAKE_OMNIVOICE")):
        if not set(os.listdir(os.path.join(stack, name))) <= {"__init__" + _PY, "__pycache__"} or \
                _text(os.path.join(stack, name, "__init__" + _PY)) != _module_string(OV_SYNTH_TESTS, constant):
            return False
    import json

    with _io.open(rest[0], "rb") as handle:
        job = json.loads(handle.read(1 << 20).decode("utf-8"))
    # Every place the worker writes (its chunks, its cancel flag, its engine lock) lies in this session's disposable roots.
    outputs = [job[key] for key in ("out_dir", "cancel_file", "engine_lock") if key in job]
    return all(isinstance(path, str) and os.path.isabs(path) and disposable(path) for path in outputs)


def _omnivoice(facts) -> dict | None:
    command, disposable = facts["python"], facts["disposable"]
    if command is None or facts["interpreter_kind"](facts["program"]) != "trusted" or list(command.flags) != ["-I"]:
        return None
    reason = None
    if command.mode == "script" and _ov_stack(command.target, command.rest, facts["cwd"], disposable):
        reason = "the real OmniVoice worker on the reviewed stand-in stack"
    elif command.mode == "script" and not command.rest and os.path.basename(command.target) == "probe" + _PY \
            and disposable(command.target) and _text(command.target) == \
            OV_REFERENCE_HEAD + repr(str(OV_WORKER.parent)) + OV_REFERENCE_TAIL:
        reason = "the reviewed probe of the real OmniVoice worker's network guard"
    elif command.mode == "code" and not command.rest and _same(facts["cwd"], REPO_ROOT / "files"):
        literal = _function_code_literal(OV_PHASE1_TESTS, "test_the_network_guard_refuses_remote_access_and_keeps_loopback")
        if literal is not None and command.target == OV_P1_LOAD.format(path=str(OV_P1_WORKER)) + literal:
            reason = "the reviewed inert-event measurement of the dev-tools worker's network guard"
    if reason is None:
        return None
    return {"outcome": "bootstrap", "profile": "omnivoice-network-guard", "expect": "routine-child", "reason": reason,
            **_OV_MEASUREMENT}


#: D-R2-8: the calls an inert stand-in may make (dotted names), each with constant arguments only.
_INERT_CALLS = frozenset({"time.sleep", "sys.exit", "print", "sys.stdout.write", "sys.stdout.flush",
                          "sys.stdout.buffer.write", "sys.stdout.buffer.flush", "sys.stderr.write", "sys.stderr.flush",
                          "sys.stderr.buffer.write", "sys.stderr.buffer.flush", "signal.signal"})
_INERT_MODULES = frozenset({"time", "sys", "signal"})
_INERT_SIGNALS = frozenset({"signal.SIGTERM", "signal.SIGINT", "signal.SIGBREAK", "signal.SIG_IGN", "signal.SIG_DFL"})
_INERT_FLAGS = frozenset({"-I", "-B", "-S", "-E", "-s", "-u"})
_INERT_MAX = 4096


def _dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _inert_value(node) -> bool:
    """A constant, or arithmetic over constants (``b'x' * (1 << 20)``), or a reviewed signal name."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, str, bytes, bool)) or node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.LShift)):
        return _inert_value(node.left) and _inert_value(node.right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _inert_value(node.operand)
    return _dotted(node) in _INERT_SIGNALS


def _inert_statement(node) -> bool:
    if isinstance(node, ast.Pass):
        return True
    if isinstance(node, ast.Import):
        return all(alias.name in _INERT_MODULES and alias.asname is None for alias in node.names)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if _dotted(call.func) not in _INERT_CALLS:
            return False
        return all(_inert_value(arg) for arg in call.args) and \
            all(keyword.arg == "flush" and _inert_value(keyword.value) for keyword in call.keywords)
    if isinstance(node, ast.For):
        iterator = node.iter
        return isinstance(node.target, ast.Name) and not node.orelse and isinstance(iterator, ast.Call) and \
            _dotted(iterator.func) == "range" and not iterator.keywords and len(iterator.args) <= 3 and \
            all(isinstance(arg, ast.Constant) and isinstance(arg.value, int) for arg in iterator.args) and \
            all(_inert_statement(statement) for statement in node.body)
    if isinstance(node, ast.While):
        return isinstance(node.test, ast.Constant) and node.test.value is True and not node.orelse and \
            all(_inert_statement(statement) for statement in node.body)
    return False


def _inert_python(facts) -> dict | None:
    """D-R2-8: a ``-c`` stand-in that can reach no effect -- it only sleeps, writes constants to its standard streams,
    prints, exits or ignores a signal (judged on its syntax tree; every argument a constant) -- on this session's own
    interpreter. It runs unchanged and owes no participant: its startup and cancellation timing are exactly the program's,
    and the parent's spawn, stop and exit rows are its evidence. Anything else is effect-capable and is bootstrapped."""
    command = facts["python"]
    if command is None or command.mode != "code" or command.rest or not set(command.flags) <= _INERT_FLAGS:
        return None
    if facts["interpreter_kind"](facts["program"]) != "trusted" or len(command.target) > _INERT_MAX:
        return None
    # Startup customization that could run code before (or after) the stand-in makes it not inert. PYTHONSTARTUP is
    # read only by an interactive session, which a -c program is not unless PYTHONINSPECT (or -i, refused by the flag
    # set) makes it one; so PYTHONINSPECT is refused and PYTHONSTARTUP alone (an editor's own setting) is not.
    if not command.ignores_environment and any(facts["env"].get(name) for name in (
            "PYTHONPATH", "PYTHONHOME", "PYTHONINSPECT", "PYTHONUSERBASE", "PYTHONEXECUTABLE")):
        return None
    try:
        tree = ast.parse(command.target)
    except (SyntaxError, ValueError):
        return None
    if not tree.body or not all(_inert_statement(statement) for statement in tree.body):
        return None
    # R3-01: the syntax alone does not establish what an import binds. A module that is not built into the interpreter is
    # found on the path, whose first entry for -c is the working directory unless -I/-P (or an honoured PYTHONSAFEPATH)
    # removes it: none of them may be shadowed there. The user site's startup code is judged as for every Python child.
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    loaded = sorted(name for name in imported if name not in sys.builtin_module_names)
    safe = command.safe_path or (not command.ignores_environment and facts["env"].get("PYTHONSAFEPATH"))
    if loaded and not safe and facts["shadowed"](facts["cwd"], loaded):
        return None
    if facts["startup_problem"](facts["env"], command, facts["program"]):
        return None
    return _leaf("inert-python-stand-in", "an inert Python stand-in (sleeps and writes constants only)")


QWEN3_TOOLS = REPO_ROOT / "files" / "dev-tools" / ("qwen3_calm_venv_tools" + _PY)
QWEN3_INTERPRETER = REPO_ROOT / ".venv" / "engines" / "qwen3" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
QWEN3_MODELS = REPO_ROOT / "files" / "runtime-data" / "models"
#: The worker environment's cache and scratch destinations (qwen3_runtime.worker_environment): all must be disposable.
QWEN3_WRITABLE = ("TEMP", "TMP", "TMPDIR", "HF_HOME", "TORCH_HOME", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME")


def _qwen3_selfcheck(facts) -> dict | None:
    """R3-05: the one reviewed engine-interpreter launch -- ``<this checkout's Qwen3 interpreter> -I -B
    <this checkout's files/dev-tools/qwen3_calm_venv_tools.py> selfcheck <a model folder of this checkout>``, exactly, with
    the worker environment offline and every cache and scratch destination disposable (verification.json classifies
    qwen3_calm_venv_tools.py bounded for this selfcheck; the guarded runner's "read-only-calm-library-selfcheck" profile is
    the same contract). It imports the pinned library and reads the model folder's fixed generation configuration; it
    loads no model, makes no audio and starts nothing. Every other use of an engine interpreter stays refused."""
    argv, env, disposable = facts["argv"], facts["env"], facts["disposable"]
    if len(argv) != 6 or argv[1:3] != ["-I", "-B"] or argv[4] != "selfcheck":
        return None
    if not facts["program"] or os.path.normcase(os.path.abspath(facts["program"])) != \
            os.path.normcase(str(QWEN3_INTERPRETER)):
        return None
    script = argv[3] if os.path.isabs(argv[3]) else os.path.join(facts["cwd"], argv[3])
    if os.path.normcase(os.path.abspath(script)) != os.path.normcase(str(QWEN3_TOOLS)) or not _unlinked(REPO_ROOT, Path(script)):
        return None
    model = argv[5] if os.path.isabs(argv[5]) else os.path.join(facts["cwd"], argv[5])
    if not _unlinked(QWEN3_MODELS, Path(model)) or os.path.normcase(os.path.abspath(model)) == \
            os.path.normcase(str(QWEN3_MODELS)):
        return None
    if env.get("HF_HUB_OFFLINE") != "1" or not all(env.get(name) and disposable(env[name]) for name in QWEN3_WRITABLE):
        return None
    return _leaf("qwen3-calm-selfcheck", "the reviewed read-only Qwen3 calm-library selfcheck (no model loads)")


FAMILIES = (_tk_proof, _footprint, _powershell, _cmd, _fake_ffmpeg, _git, _media, _windows_tools, _bash, _v3_workers,
            _omnivoice, _qwen3_selfcheck, _inert_python, _inert)


def recognize(facts: dict) -> dict | None:
    """The reviewed family this launch positively is, or None. Side-effect free."""
    for family in FAMILIES:
        try:
            found = family(facts)
        except (OSError, ValueError, TypeError, IndexError, AttributeError):
            found = None
        if found is not None:
            found.setdefault("expect", None)
            return found
    return None


def _system32(*parts) -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return os.path.join(root, "System32", *parts)


# --------------------------------------------------------------------------- #
#  Native process creation (D-R2-4): the Low-integrity containment profile
# --------------------------------------------------------------------------- #
def native_resolution_reviewed(name: str, frames) -> bool:
    """Whether resolving a native process-creation function is the reviewed containment module doing it (at its import)."""
    if name != "CreateProcessAsUserW":
        return False
    return any(_same(file, CONTAINMENT) and function == "<module>" for file, function in frames) and \
        _bytes_equal(CONTAINMENT, CONTAINMENT)


def native_launch_reviewed(argv: list[str], cwd, frames, disposable) -> str | None:
    """The reviewed Low-integrity launch, or None: ``containment.spawn_low`` of the marked checkout, called by its own
    preflight (``-I -B containment.py --probe <disposable>``) or by test_dialog_containment's probe, on this interpreter."""
    files = [(os.path.normcase(file), function) for file, function in frames]
    if not files or not _same(files[0][0], CONTAINMENT) or files[0][1] != "spawn_low":
        return None
    trusted = {os.path.normcase(os.path.realpath(sys.executable))}
    if not argv or os.path.normcase(os.path.realpath(argv[0])) not in trusted or argv[1:3] != ["-I", "-B"]:
        return None
    if not disposable(cwd):
        return None
    caller = files[1] if len(files) > 1 else ("", "")
    if len(argv) == 6 and _same(argv[3], CONTAINMENT) and argv[4] == "--probe" and disposable(argv[5]) \
            and _same(caller[0], CONTAINMENT) and caller[1] == "preflight":
        return "low-integrity-preflight"
    from_test = os.path.basename(caller[0]) == "test_dialog_containment" + _PY and caller[1] == "_low_python"
    if len(argv) == 5 and argv[3] == "-c" and argv[4] == LOW_PROBE.format(source=str(CONTAINMENT.parent)) and from_test:
        return "low-integrity-probe"
    scratch = os.fspath(cwd)
    paths = {"earlier": os.path.join(scratch, "in", "made-before-the-label.txt"),
             "later": os.path.join(scratch, "in", "made-after-the-label.txt"), "new": os.path.join(scratch, "new.txt"),
             "beside": os.path.join(os.path.dirname(scratch), "beside", "x.txt")}
    if len(argv) == 5 and argv[3] == "-c" and from_test and all(disposable(path) for path in paths.values()) \
            and argv[4] == LOW_SCRATCH_PROBE.format(**paths):
        return "low-integrity-scratch-probe"
    return None
