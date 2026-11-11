"""What the Phase 8 qualification scenarios share: where a run may write, how a verdict is written, how one contained case is run.

Each scenario is a script the gate supervises (``verify.py --mode qualification --scenario <name>``) under its own job and budgets.
The contract is the one ``scaling/qualify.py`` set: the runner is given ``--out <run>/qualification``, appends to ``progress.log``
so a stall can be told from work, and leaves ``verdict.json`` with a status its own exit code agrees with (0 PASS, 1 FAIL,
2 BLOCKED). PASS means every check passed; a prerequisite that is not here is BLOCKED, never a pass and never a product failure.

A scenario that needs the network says so in ``verification.json`` and is run with ``--network <policy>``; the gate hands the
grant on and the runner refuses (BLOCKED) without it. A scenario that needs none makes its children prove it: ``no_network()`` is
an audit hook that refuses every non-loopback connection for the life of the process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_DIR = HERE.parent
REPO_ROOT = GATE_DIR.parents[2]
SCRIPTS = REPO_ROOT / "scripts"
OUTPUTS = GATE_DIR / "outputs"
_NO_WINDOW = 0x08000000


class Blocked(Exception):
    """A prerequisite of the scenario is not available here. Never a pass, and never a failure of the application."""


def parse(argv=None, *, network: tuple[str, ...] = ()) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--network", default="", choices=("", *network))
    parser.add_argument("--smoke", action="store_true",
                        help="development only: a reduced set of cases; the verdict is SMOKE, never PASS")
    return parser.parse_args(argv)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                          creationflags=_NO_WINDOW).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_digest(*extra: str) -> str:
    """The tracked and untracked bytes of the application and of this folder, as Git would store them, so a result names its code."""
    digest = hashlib.sha256()
    roots = ("scripts", "files/dev-work/verification-gate/qualification", *extra)
    listed = git("ls-files", *roots).splitlines() + git("ls-files", "--others", "--exclude-standard", *roots).splitlines()
    for relative in sorted(set(listed)):
        path = REPO_ROOT / relative
        if path.is_file():
            digest.update(relative.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def downloads_outputs() -> dict:
    """The owner's default output tree, by name and size: a run must leave it exactly as it found it."""
    root = Path.home() / "Downloads" / "Audiobook-Creation-Tool-Outputs"
    found: dict = {}
    if root.is_dir():
        for folder, _folders, files in os.walk(root):
            for name in files:
                path = Path(folder) / name
                try:
                    found[str(path.relative_to(root))] = path.stat().st_size
                except OSError:
                    found[str(path.relative_to(root))] = -1
    return found


def runtime_data_digest() -> str:
    """This checkout's own settings and logs by name, size and time: what a contained run must never write."""
    digest = hashlib.sha256()
    root = REPO_ROOT / "files" / "runtime-data"
    for name in ("settings.json", "ffmpeg-state.json"):
        path = root / name
        digest.update(name.encode() + (path.read_bytes() if path.is_file() else b"<absent>"))
    logs = root / "logs"
    for path in sorted(logs.iterdir()) if logs.is_dir() else []:
        stat = path.stat()
        digest.update(f"{path.name}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def shell_windows() -> int:
    """How many file-manager windows are open (top-level CabinetWClass). A run must open none."""
    if sys.platform != "win32":
        return 0
    import ctypes
    import ctypes.wintypes as w

    user32 = ctypes.WinDLL("user32")
    count = 0

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def each(hwnd, _lparam):
        nonlocal count
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value == "CabinetWClass" and user32.IsWindowVisible(hwnd):
            count += 1
        return True

    user32.EnumWindows(each, 0)
    return count


class Scenario:
    """One qualification run: its folder, its progress line, its checks and its verdict."""

    def __init__(self, name: str, args: argparse.Namespace) -> None:
        self.name = name
        self.args = args
        self.root = args.out.resolve()
        self.checks: list[dict] = []
        self.runs: list[dict] = []
        self.started = time.time()
        self.root.relative_to(OUTPUTS.resolve())  # ValueError: refused, nothing is written anywhere else
        self.root.mkdir(parents=True, exist_ok=False)

    def log(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        with open(self.root / "progress.log", "a", encoding="utf-8") as sink:
            sink.write(line + "\n")
        print(line, flush=True)

    def check(self, name: str, ok: bool, detail: str = "", **facts) -> bool:
        self.checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": str(detail)[:1200], **facts})
        self.log(f"{'PASS' if ok else 'FAIL'} {name}: {str(detail)[:300]}")
        return bool(ok)

    def identity(self, **more) -> dict:
        record = {"scenario": self.name, "head": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                  "dirty": git("status", "--porcelain=v1", "--", "scripts", "files/dev-work/verification-gate", "config.toml"),
                  "code_digest": code_digest(), "python": sys.version.split()[0], "platform": sys.platform,
                  "windows": " ".join(os.popen("ver").read().split()) if sys.platform == "win32" else "", "network": self.args.network, **more}
        (self.root / "identity.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
        return record

    def child(self, label: str, script: Path, arguments: list[str], *, timeout: float, env: dict | None = None,
              python: str | None = None, exact_env: bool = False) -> dict:
        """One contained case in a process of its own. Its ``result.json`` is the answer; its output is kept beside it.

        ``env`` is laid over this process's environment, or with ``exact_env`` is the child's whole environment, so a variable the
        caller left out on purpose is really absent."""
        folder = self.root / "runs" / label
        folder.mkdir(parents=True, exist_ok=False)
        environment = {key: value for key, value in os.environ.items() if key.upper() not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
        if exact_env:
            environment = dict(env or {})
        else:
            environment.update(env or {})
        self.log(f"run {label}: start")
        began = time.monotonic()
        with open(folder / "output.log", "wb") as output:
            try:
                done = subprocess.run([python or sys.executable, "-I", "-B", "-u", str(script), "--out", str(folder), *arguments],
                                      stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout,
                                      env=environment, cwd=str(folder), creationflags=_NO_WINDOW)
                code, ended = done.returncode, "exited"
            except subprocess.TimeoutExpired:
                code, ended = None, "timeout"
        record = {"label": label, "exit": code, "ended": ended, "seconds": round(time.monotonic() - began, 1), "folder": label}
        try:
            record["result"] = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            record["result"] = None
            record["no_result"] = f"{type(exc).__name__}: {exc}"
        self.runs.append({key: value for key, value in record.items() if key != "result"})
        self.log(f"run {label}: {ended}, exit {code}, {record['seconds']} s")
        return record

    def finish(self, body) -> int:
        """Run ``body(self)`` and always leave a verdict the exit code agrees with."""
        status, reason = "FAIL", ""
        before = downloads_outputs(), runtime_data_digest(), shell_windows()
        try:
            body(self)
            after = downloads_outputs(), runtime_data_digest(), shell_windows()
            self.check("containment: the owner's default output tree is unchanged", before[0] == after[0],
                       f"{len(before[0])} files before, {len(after[0])} after")
            self.check("containment: this checkout's settings and logs are unchanged", before[1] == after[1], "")
            self.check("containment: no file-manager window was opened", after[2] <= before[2], f"{before[2]} before, {after[2]} after")
            failing = [item["name"] for item in self.checks if item["status"] != "PASS"]
            if self.args.smoke:
                status, reason = "SMOKE", f"smoke only, never a qualification; {len(failing)} failing check(s): {failing[:8]}"
                return 3
            status = "FAIL" if failing or not self.checks else "PASS"
            reason = f"{len(failing)} failing check(s): {failing[:8]}" if failing else "every case passed"
            return 0 if status == "PASS" else 1
        except Blocked as exc:
            status, reason = "BLOCKED", str(exc)
            return 2
        except Exception:  # noqa: BLE001 - recorded as the result, never swallowed
            status, reason = "FAIL", traceback.format_exc()[-3000:]
            return 1
        finally:
            verdict = {"scenario": self.name, "status": status, "reason": reason,
                       "elapsed_seconds": round(time.time() - self.started, 1), "checks": self.checks, "runs": len(self.runs)}
            (self.root / "runs.json").write_text(json.dumps(self.runs, indent=1), encoding="utf-8")
            (self.root / "verdict.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
            print(json.dumps({"status": status, "reason": reason[:500]}), flush=True)


def start(name: str, argv=None, *, network: tuple[str, ...] = ()) -> Scenario | int:
    """The scenario, or the exit code of a refusal: an ``--out`` outside the gate's outputs is refused with nothing written."""
    args = parse(argv, network=network)
    try:
        return Scenario(name, args)
    except ValueError:
        print(f"refused: {args.out} is not inside {OUTPUTS}", file=sys.stderr)
        return 3


# --------------------------------------------------------------------------- #
# For the children: containment before any application import
# --------------------------------------------------------------------------- #
def no_network(log: list | None = None) -> None:
    """Refuse every non-loopback connection for the life of this process, and record each attempt. An audit hook cannot be removed."""
    def hook(event: str, arguments) -> None:
        if event in ("socket.connect", "socket.bind", "socket.sendto"):
            address = arguments[1] if len(arguments) > 1 else None
            host = address[0] if isinstance(address, tuple) and address else address
            if isinstance(host, (bytes, bytearray)):
                host = host.decode("ascii", "replace")
            if event == "socket.bind" or str(host) in ("127.0.0.1", "::1", "localhost", "", "0.0.0.0", "None"):
                return
            if log is not None:
                log.append({"event": event, "address": str(address)[:120]})
            raise PermissionError(f"this qualification run is offline: {event} to {address!r} refused")
        if event == "socket.getaddrinfo":
            host = arguments[0]
            if host not in (None, "", "localhost", "127.0.0.1", "::1") and log is not None:
                log.append({"event": event, "address": str(host)[:120]})
            if host not in (None, "", "localhost", "127.0.0.1", "::1"):
                raise PermissionError(f"this qualification run is offline: name lookup of {host!r} refused")

    sys.addaudithook(hook)


def contain_application(out: Path) -> dict:
    """Point the application at this run's own folders before it is imported, and prove the output base. Returns the proof.

    Also takes away both ways of opening the file manager, and refuses unless that held (Phase 7B: an unneutralized reveal opened
    hundreds of Explorer windows on the owner's desktop)."""
    import shutil
    import tempfile

    temp = out / "tmp"
    temp.mkdir(exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(temp)
    tempfile.tempdir = str(temp)
    sys.path.insert(0, str(SCRIPTS))
    from shared import ffmpeg_health, paths

    runtime = out / "runtime-data"
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    real_runtime = Path(paths.RESOURCES_DIR)
    paths.RESOURCES_DIR, paths.LOGS_DIR, paths.SETTINGS_FILE = runtime, runtime / "logs", runtime / "settings.json"
    ffmpeg_health.RESOURCES_DIR = runtime
    shutil.copyfile(real_runtime / ffmpeg_health.HEALTH_STATE_NAME, runtime / ffmpeg_health.HEALTH_STATE_NAME)
    from shared import config as shared_config
    from shared import output_paths
    from shared import subprocess_utils as sp

    base = out / "output-base"
    base.mkdir(exist_ok=True)
    shared_config.set_output_base(str(base))
    resolved = Path(output_paths.resolve_output_base(shared_config.get_effective())).resolve()
    if resolved != base.resolve() or Path(paths.SETTINGS_FILE).resolve() != (runtime / "settings.json").resolve():
        raise SystemExit(f"refused: the application would write to {resolved}, not this run's {base}")
    reveals: list = []
    sp.reveal_in_file_manager = lambda path, *a, **k: reveals.append(str(path))
    os.startfile = lambda *a, **k: reveals.append(str(a[:1]))
    if getattr(os, "startfile").__name__ != "<lambda>":
        raise SystemExit("refused: the file manager could still be opened from this run")
    return {"settings_file": str(paths.SETTINGS_FILE), "output_base": str(resolved), "temp": str(temp), "real_runtime": str(real_runtime),
            "shell_reveal_neutralized": True, "reveals": reveals}
