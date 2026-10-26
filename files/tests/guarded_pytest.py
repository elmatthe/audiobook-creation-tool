"""Run a focused qualification with process-lifetime protection, through atexit.

Usage: python -I -B files/tests/guarded_pytest.py CONFIG REPORT pytest-arguments...
CONFIG version 1 pins reviewed subprocess callsites by file SHA-256 and function
name. It is evidence for a particular run, never a production capability. Child
and native isolation relies on the explicit profiles below and their disposable
paths, not on inheritance of this Python audit hook. Raw refusals are never lost.
"""

import atexit
import ast
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "files/tests"), str(ROOT / "scripts")]
import write_tripwire as tripwire


def production_roots():
    paths = (".venv", ".venv-qwen3", "files/runtime-data", "files/Cloned-Voice-Uploads",
             "files/Chatterbox-Voice-Uploads", "files/voice-previews", "files/dev-work/P04B q",
             "files/dev-work/P04C q", "files/dev-work/act070-remediation", "scripts/tts/data", "config.toml",
             "files/run-temp", ".ai", "scripts/project-status.py", "files/bin")
    roots = [ROOT / path for path in paths]
    roots += list(ROOT.glob(".venv*act67-preserved-*"))
    roots += list((ROOT / "files").glob("runtime-data.act67-preserved-*"))
    # Every earlier checkpoint is read-only. The current run is deliberately elsewhere.
    roots += [path for path in (ROOT / "files/dev-work").glob("p05b-stage*") if path.name != "p05b-stage4c"]
    return roots


def windows_argv(command):
    if not isinstance(command, str):
        return [str(arg) for arg in command]
    argc = ctypes.c_int()
    split = ctypes.WinDLL("shell32").CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = split(command, ctypes.byref(argc))
    try:
        return [pointer[i] for i in range(argc.value)]
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(pointer)


class ProcessPolicy:
    """Approve reviewed test callsites AND bounded command/path profiles.

    A source pin alone is insufficient: arbitrary executables, online pip, shell
    commands and writable destinations outside the proved test tree are refused.
    These are honest fixed test programs, not an OS sandbox for hostile native code.
    """

    def __init__(self, config, temp, process_temp=None):
        if config["version"] != 1:
            raise ValueError("unknown process qualification configuration")
        self.sites = config["process_sites"]
        self.temp = temp
        self.disposable_roots = (temp,) if process_temp is None else (temp, process_temp)
        self.tools = config["tools"]
        self.allowed = []
        self.refused = []
        for rel, entry in self.sites.items():
            path = ROOT / rel
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("changed reviewed process source: " + rel)

    def disposable(self, text):
        path = Path(text)
        return path.is_absolute() and any(path.is_relative_to(root) and path.resolve().is_relative_to(root.resolve())
                                          for root in self.disposable_roots)

    def caller(self):
        frame = sys._getframe(1)
        while frame:
            path = Path(frame.f_code.co_filename)
            if path.is_absolute() and path.is_relative_to(ROOT):
                rel = path.relative_to(ROOT).as_posix()
                entry = self.sites.get(rel)
                if entry and frame.f_code.co_name in entry["functions"]:
                    if hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
                        return rel + ":" + frame.f_code.co_name
            frame = frame.f_back
        return None

    def git_profile(self, argv, cwd):
        args = argv[1:]
        if args[:1] != ["-C"]:
            if args and args[0] in ("check-ignore", "ls-files") and \
                    (cwd is None or Path(cwd).resolve() == ROOT or self.disposable(cwd)):
                return "read-only-git"
            return None
        if len(args) < 3:
            return None
        root, args = Path(args[1]), args[2:]
        fixture_config = ["-c", "user.name=packager-test", "-c", "user.email=packager-test@example.invalid",
                          "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false"]
        configured = args[:len(fixture_config)] == fixture_config
        if configured:
            args = args[len(fixture_config):]
        if not args:
            return None
        if args[0] in ("ls-files", "status", "rev-parse") and \
                (root.resolve() == ROOT or self.disposable(root)):
            return "read-only-git"
        # The existing packaging fixtures initialize/commit ONLY their own test
        # repositories. A gitdir file or junction cannot redirect those writes.
        if not configured or not self.disposable(root) or not self.disposable(root / ".git"):
            return None
        gitdir = root / ".git"
        if gitdir.exists() and not gitdir.is_dir():
            return None
        if args in (["init", "-q"], ["add", "-A", "-f"]) or \
                (len(args) == 4 and args[:3] == ["commit", "-q", "-m"]):
            return "disposable-packaging-git"
        return None

    def approve(self, command, cwd):
        argv = windows_argv(command)
        if not argv:
            return None
        exe = Path(argv[0])
        name = exe.name.lower().removesuffix(".exe")
        caller = self.caller()
        if not caller:
            return None
        if name in ("git", "powershell", "cmd", "tasklist", "taskkill"):
            tool = self.tools.get(name)
            resolved = Path(shutil.which(str(exe)) or exe).resolve()
            if not tool or resolved != Path(tool["path"]).resolve() or \
                    hashlib.sha256(resolved.read_bytes()).hexdigest() != tool["sha256"]:
                return None
        if argv == ["lscpu"] and caller == ".venv/Lib/site-packages/numpy/testing/_private/utils.py:check_support_sve" \
                and os.name == "nt":
            return ("refused-numpy-sve-platform-probe", caller)
        if name == "git":
            profile = self.git_profile(argv, cwd)
            return (profile, caller) if profile else None
        # Link fixtures must prove BOTH sides lie in the current disposable tree.
        if argv[:4] == ["cmd", "/c", "mklink", "/J"] and len(argv) == 6 \
                and all(self.disposable(p) for p in argv[4:]):
            return ("disposable-junction", caller)
        if name == "tasklist" and len(argv) == 4 and argv[1] == "/FI" \
                and re.fullmatch(r"PID eq [1-9][0-9]*", argv[2]) and argv[3] == "/NH":
            return ("pid-read", caller)
        if name == "taskkill" and len(argv) == 5 and argv[1] == "/PID" and argv[2].isdigit() \
                and argv[3:] == ["/T", "/F"]:
            return ("reviewed-child-tree-stop", caller)
        if name == "powershell" and argv[1:6] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                                              str(ROOT / "scripts/shared/bootstrap_host.ps1")]:
            # Existing process-local flag only; never a machine policy change.
            rest = argv[6:]
            if "-OutFile" not in rest or not self.disposable(rest[rest.index("-OutFile") + 1]):
                return None
            if "-AssumeNo" in rest:
                return ("bootstrap-no-install", caller)
            if "-InstallerPath" in rest and "-NoWinget" in rest and "-IgnoreInstalled" in rest:
                path = Path(rest[rest.index("-InstallerPath") + 1])
                if self.disposable(path) and path.read_bytes() == b"MZ not the python.org installer":
                    return ("bootstrap-rejected-synthetic-installer", caller)
            return None
        tool = self.tools.get(name)
        resolved_exe = Path(shutil.which(str(exe)) or exe).resolve()
        if tool and resolved_exe == Path(tool["path"]).resolve() \
                and hashlib.sha256(resolved_exe.read_bytes()).hexdigest() == tool["sha256"]:
            if name == "ffprobe" and self.disposable(argv[-1]):
                return ("disposable-media-probe", caller)
            if name == "ffmpeg" and (self.disposable(argv[-1]) or (argv[-1] == "-" and "-i" in argv and
                    self.disposable(argv[argv.index("-i") + 1]))) and \
                    not any("://" in arg for arg in argv) and \
                    all(self.disposable(arg) for arg in argv[1:] if Path(arg).is_absolute()):
                return ("disposable-media-output", caller)
            if argv[1:] == ["-version"]:
                return ("media-version", caller)
        # Generated encoder wrappers and deliberately missing executables never
        # gain permission outside the proved pytest tree.
        if self.disposable(exe) and exe.name in ("fake_ffmpeg.cmd", "no-such-program.exe"):
            return ("disposable-test-executable", caller)
        if name != "python" and name != "python3":
            return None
        trusted_python = {Path(sys.executable).resolve(), Path(sys._base_executable).resolve()}
        if exe.resolve() not in trusted_python and not self.disposable(exe):
            # The calm selfcheck uses the installed engine only to inspect fixed
            # library methods/config, without constructing or loading a model.
            engine_pythons = {ROOT / ".venv/engines/qwen3/Scripts/python.exe", ROOT / ".venv-qwen3/Scripts/python.exe"}
            if exe.resolve() not in {path.resolve() for path in engine_pythons} or "selfcheck" not in argv:
                return None
        if "-m" in argv:
            at = argv.index("-m")
            if argv[at + 1:at + 3] == ["venv", "--without-pip"] and self.disposable(argv[-1]):
                return ("disposable-pipless-venv", caller)
            if argv[1:5] == ["-E", "-s", "-m", "tts.optional_setup_worker"] and len(argv) == 11 \
                    and argv[5::2] == ["--request", "--result", "--session"] and cwd and self.disposable(cwd):
                scripts = Path(cwd)
                request, result = Path(argv[6]), Path(argv[8])
                worker = scripts / "tts/optional_setup_worker.py"
                if self.disposable(request) and self.disposable(result) and result.parent == request.parent \
                        and request.name == "request.json" and result.name == "result.json" \
                        and worker.read_bytes() == (ROOT / "scripts/tts/optional_setup_worker.py").read_bytes():
                    return ("disposable-disabled-setup-worker", caller)
            return None
        if "-c" in argv:
            code_at = argv.index("-c") + 1
            code = argv[code_at]
            from tts import qwen3_packages
            if code == qwen3_packages.OFFLINE_BOOTSTRAP:
                if not self.disposable(exe) or exe.parts[-3:] != ("disposable-env", "Scripts", "python.exe"):
                    return None
                if argv[1:4] != ["-I", "-B", "-c"] or len(argv) != 20 or not cwd or not self.disposable(cwd):
                    return None
                wheels, lock = Path(argv[10]), Path(argv[18])
                if not self.disposable(wheels) or not self.disposable(lock) or Path(cwd) != wheels or \
                        wheels.parent != exe.parents[2] or lock.parent != exe.parents[2]:
                    return None
                if argv[5:19] != ["install", "--isolated", "--require-virtualenv", "--no-index", "--find-links",
                    str(wheels), "--require-hashes", "--no-deps", "--only-binary=:all:", "--no-cache-dir", "--no-input",
                    "--disable-pip-version-check", "-r", str(lock)] or not re.fullmatch(
                        r"file:\./act_disposable_proof-1\.0-py3-none-any\.whl#sha256=[0-9a-f]{64}", argv[19]):
                    return None
                return ("child-guarded-offline-tiny-pip", caller)
            # Absolute path literals and positional paths in these fixed probes
            # may name the read-only scripts import root or this run's test tree.
            for node in ast.walk(ast.parse(code)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    path = Path(node.value)
                    if path.is_absolute() and not self.disposable(path) and not path.is_relative_to(ROOT / "scripts"):
                        return None
            for arg in argv[code_at + 1:]:
                path = Path(arg)
                if path.is_absolute() and not self.disposable(path) and path != ROOT / "scripts":
                    return None
            if cwd and Path(cwd).resolve() != ROOT and not self.disposable(cwd):
                return None
            return ("reviewed-python-probe-or-worker", caller)
        # Script workers must run only against disposable jobs / app copies.
        scripts = [Path(arg) for arg in argv[1:] if arg.endswith(".py")]
        if scripts and self.disposable(scripts[0]) and scripts[0].name == "guarded_pytest.py" and \
                scripts[0].read_bytes() == Path(__file__).read_bytes() and \
                all(self.disposable(arg.split("=", 1)[-1]) for arg in argv[1:]
                    if Path(arg.split("=", 1)[-1]).is_absolute()):
            return ("synthetic-process-lifetime-negative-control", caller)
        if len(scripts) == 1:
            script = scripts[0]
            if self.disposable(script) or script == ROOT / "scripts/tts/qwen3_worker.py":
                if any(self.disposable(arg) for arg in argv[1:] if Path(arg).is_absolute()):
                    return ("disposable-script-worker", caller)
            if script == ROOT / "files/dev-tools/qwen3_calm_venv_tools.py" and \
                    len(argv) == 6 and argv[1:3] == ["-I", "-B"] and argv[4] == "selfcheck" and \
                    Path(argv[5]).resolve().is_relative_to((ROOT / "files/runtime-data/models").resolve()):
                return ("read-only-calm-library-selfcheck", caller)
        return None

    def audit(self, event, args):
        if event == "subprocess.Popen":
            profile = self.approve(args[1], args[2])
            if profile and profile[0] == "read-only-calm-library-selfcheck":
                env = args[3] or {}
                if not all(name in env and self.disposable(env[name]) for name in
                           ("TEMP", "TMP", "TMPDIR", "HF_HOME", "TORCH_HOME", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME")) \
                        or env.get("HF_HUB_OFFLINE") != "1":
                    profile = None
            record = {"event": event, "argv": windows_argv(args[1]), "cwd": str(args[2]),
                      "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session"), "profile": profile,
                      "stack": traceback.format_stack(limit=20)}
            (self.allowed if profile else self.refused).append(record)
            if not profile:
                raise PermissionError("unqualified child process: " + repr(record["argv"][:4]))
            if profile[0] == "refused-numpy-sve-platform-probe":
                record["launched"] = False
                raise FileNotFoundError("lscpu is an unavailable optional NumPy SVE probe on Windows")
        elif event in ("os.system", "os.startfile", "os.posix_spawn", "os.spawn", "os.exec"):
            self.refused.append({"event": event, "args": repr(args)})
            raise PermissionError("unqualified process mechanism: " + event)


def main(*, plugins=()):
    config_path, report_path = map(Path, sys.argv[1:3])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    arguments = sys.argv[3:]
    temp_args = [arg.split("=", 1)[1] for arg in arguments if arg.startswith("--basetemp=")]
    if len(temp_args) != 1:
        raise ValueError("one explicit disposable --basetemp= is required")
    temp = Path(temp_args[0]).absolute()
    owned = ROOT / "files/dev-work/p05b-stage4c"
    if not temp.is_relative_to(owned) or not temp.resolve().is_relative_to(owned.resolve()):
        raise ValueError("basetemp must be in this checkpoint's disposable tree")
    report_path = report_path.absolute()
    if not report_path.is_relative_to(owned) or not report_path.resolve().is_relative_to(owned.resolve()):
        raise ValueError("report must stay in the checkpoint's owned tree")
    process_temp = report_path.with_name(report_path.stem + "-process-temp")
    process_temp.mkdir(exist_ok=False)
    policy = ProcessPolicy(config, temp, process_temp)
    protected = production_roots()
    roots = tuple(tripwire._norm(str(p)) for p in protected)
    boundary = tripwire.armed(protected)
    boundary.__enter__()
    code = 1
    blocked = []
    expected_blocked = []
    sys.dont_write_bytecode = True
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Native Git fixtures must not inherit a production gitdir/index, hooks,
    # signing or fsmonitor configuration. This changes only this test process.
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            del os.environ[name]
    os.environ.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0",
                       "GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull,
                       "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
                       "GIT_CONFIG_KEY_2": "core.longpaths", "GIT_CONFIG_VALUE_2": "true"})
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(process_temp)
    tempfile.tempdir = str(process_temp)
    os.environ.pop("PYTEST_CURRENT_TEST", None)  # independent children must not inherit the parent's test phase

    class Counts:
        config = None

        def pytest_configure(self, config):
            self.config = config

    counter = Counts()

    def finish(boundary=boundary):
        # Retain the generator context until shutdown; otherwise returning from
        # main finalizes it and silently disarms protection before atexit.
        raw = tripwire.refusal_details
        real = [item for item in raw if tripwire._inside(item["lexical"], roots) or
                tripwire._inside(item["resolved"], roots)]
        accidental = [item for item in real if not item["bytecode"]]
        report = {"version": 1, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                  "runner_sha256": runner_sha256,
                  "disposable_process_roots": [str(path) for path in policy.disposable_roots],
                  "pytest_exit": int(code), "raw_refusals": raw, "production_refusals": real,
                  "unintended_production_refusals": accidental, "allowed_processes": policy.allowed,
                  "unexpected_processes": policy.refused, "network_model_refusals": blocked}
        report["expected_negative_import_refusals"] = expected_blocked
        if counter.config:
            terminal = counter.config.pluginmanager.get_plugin("terminalreporter")
            report["counts"] = {key: len(value) for key, value in terminal.stats.items() if key in
                                ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected")}
        status = 1 if accidental or policy.refused or blocked else int(code)
        report["outer_exit"] = status
        try:
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except BaseException:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
        print("LIFETIME GUARD:", len(accidental), "unintended writes;", len(policy.refused), "unexpected processes;",
              len(blocked), "network/model refusals; exit", status)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)  # atexit exceptions cannot change the process exit status

    # Registered before pytest: all later teardown/atexit callbacks run protected
    # before this final accounting. No context exit disarms the boundary early.
    atexit.register(finish)
    sys.addaudithook(policy.audit)

    def network_model_guard(event, args):
        if event in ("socket.connect", "socket.bind", "socket.getaddrinfo"):
            address = args[1] if event != "socket.getaddrinfo" else (args[0],)
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1", "localhost", None):
                blocked.append({"event": event, "target": repr(address),
                                "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session"),
                                "stack": traceback.format_stack(limit=20)})
                raise PermissionError("external network refused")
        if event == "import" and args[0].split(".")[0] in ("torch", "kokoro", "spacy", "chatterbox", "qwen_tts"):
            record = {"event": event, "target": args[0],
                      "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session"),
                      "stack": traceback.format_stack(limit=20)}
            if args[0] == "torch" and "torch" in sys.modules and sys.modules["torch"] is None and \
                    policy.caller() == "files/tests/test_qwen3_worker.py:test_probe_reports_a_broken_install_as_an_import_failure":
                expected_blocked.append(record)
                raise ModuleNotFoundError("synthetic broken-install control: torch is explicitly unavailable")
            blocked.append(record)
            raise PermissionError("real model import refused in pytest parent")

    sys.addaudithook(network_model_guard)
    import pytest
    code = pytest.main(arguments, plugins=[counter, *plugins])
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
