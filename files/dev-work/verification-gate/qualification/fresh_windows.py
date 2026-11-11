"""The ``fresh-windows`` qualification: the committed application packaged, extracted and set up as a new user would (v0.7.2 Phase 8).

    verify.py --mode qualification --scenario fresh-windows --network online-setup

What it does, all of it in disposable folders in the gate's own scratch:

  package    the real packager's writer and validator build a candidate archive from the commit; every member is compared with the
             commit, and anything that is not the application (an environment, a model, a cache, a test, a plan, evidence, a private
             file) fails it. It is written into this run's evidence, never into ``dist/``, and is not a release.
  extract A  stage 0 as the launcher runs it (the app's own Python, downloaded and proved), then the REAL first-run base setup
             (``bootstrap.run_setup``): environment, hash-locked packages, portable FFmpeg, sentence data. Then: the environment
             check, every optional voice reported absent with no connection attempted, all six tools built by the real launcher,
             and the real window started and closed.
  repair     a package is deleted from A's environment; the real repair restores it with the network blocked, from the package
             files A kept.
  extract B  seeded only with what A downloaded (its Python, its package files, its FFmpeg, its sentence data), network blocked:
             setup is stopped while pip runs (everything it started must be gone), then run again to completion. That is reuse of
             valid assets, offline, and recovery after a stop.
  extract C  nothing seeded but Python, network blocked: setup must fail cleanly, say so, and leave no usable-looking environment.

**What this is and is not.** It is a fresh *extraction* on this Windows 11 computer under this user account, with PATH reduced to
Windows' own folders and an empty LOCALAPPDATA, so no Python, FFmpeg or pip cache already on the machine can be found. It is not a
new Windows installation, not Windows 10, and not another computer; this account's Windows settings still apply. No optional voice
is downloaded: their absent state is what is checked. It needs the network for extract A (about 2.9 GB: Python 46 MB, packages
2.5 GB, FFmpeg 251 MB, sentence data 4 MB), so it runs only with ``--network online-setup``; without it, it is BLOCKED.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

REPO = common.REPO_ROOT
BAT = "Setup_and_Run-audiobook-creation-tool.bat"
FORBIDDEN = re.compile(r"(^|/)(\.venv[^/]*|engines|supply|runtime-data|dev-work|dev-tools|tests|test-files|voice-previews|run-temp|temp|"
                       r"Archives|release-history|plans|md-instructions|__pycache__|\.git|\.ai|\.claude|\.codex|test-logs|"
                       r"test-for-manual-listen[^/]*|UI-Tool-Screenshots|Chatterbox-Voice-Uploads)(/|$)", re.IGNORECASE)
OFFLINE = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""}
SEEDS = ("files/runtime-data/python", "files/runtime-data/python-packages", "files/bin", "files/runtime-data/nltk_data")


def clean_environment(local: Path, temp: Path, **more) -> dict:
    """What a computer with nothing installed offers a first run: Windows' own folders on PATH, an empty LOCALAPPDATA and its own TEMP."""
    system = os.environ.get("SystemRoot", r"C:\Windows")
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV", "PIP_CACHE_DIR", "PSMODULEPATH", "HF_HOME")}
    for folder in (local, temp):
        folder.mkdir(parents=True, exist_ok=True)
    env.update(PATH=f"{system}\\System32;{system};{system}\\System32\\Wbem;{system}\\System32\\WindowsPowerShell\\v1.0",
               LOCALAPPDATA=str(local), APPDATA=str(local / "roaming"), TEMP=str(temp), TMP=str(temp), **more)
    return env


def long_paths_enabled() -> bool | None:
    """Whether this Windows lets a program use paths past 260 characters: it decides how deep a folder the app can be set up in."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return None


def tree_size(root: Path) -> tuple[int, int]:
    count = total = 0
    for folder, _folders, files in os.walk(root):
        for name in files:
            count += 1
            try:
                total += (Path(folder) / name).stat().st_size
            except OSError:
                pass
    return count, total


class Fresh:
    def __init__(self, run: common.Scenario, scratch: Path) -> None:
        self.run = run
        self.scratch = scratch

    # ------------------------------------------------------------------ the package
    def package(self) -> Path:
        run = self.run
        sys.path.insert(0, str(common.SCRIPTS / "shared"))
        import release

        dirty = release._uncommitted_changes()
        if dirty and not run.args.smoke:
            raise common.Blocked(f"packaged paths have uncommitted changes, so no archive can stand for a commit: {dirty[:6]}")
        head = common.git("rev-parse", "HEAD")
        folder = run.root / "package"
        folder.mkdir()
        archive = folder / f"AudiobookTool-Windows-candidate-{head[:12]}.zip"
        written, left_behind = release._write_archive("Windows", archive)
        release._validate_archive(archive, written, release.ENTRY_FILES["Windows"])
        problems: list[str] = []
        members: list[str] = []
        with zipfile.ZipFile(archive) as bundle:
            for name in (item for item in bundle.namelist() if not item.endswith("/")):
                members.append(name)
                data = bundle.read(name)
                committed = subprocess.run(["git", "-C", str(REPO), "show", f"{head}:{name}"], capture_output=True)
                if committed.returncode != 0:
                    problems.append(f"not in the commit: {name}")
                elif committed.stdout != data and committed.stdout.replace(b"\r\n", b"\n") != data.replace(b"\r\n", b"\n") and not dirty:
                    problems.append(f"differs from the commit: {name}")
                top = name.split("/")[0]
                if FORBIDDEN.search(name) and not name.startswith("files/Cloned-Voice-Uploads/"):
                    problems.append(f"must never ship: {name}")
                if top not in ("scripts", "files") and name not in ("README.md", "config.toml", BAT):
                    problems.append(f"unexpected at the top: {name}")
                if top == "files" and not (name.startswith("files/Cloned-Voice-Uploads/") and name.endswith(".wav")):
                    problems.append(f"unexpected under files/: {name}")
                if name.endswith((".command", ".pyc", ".pyd", ".env", ".log", ".m4b", ".mp3", ".epub", ".pdf")):
                    problems.append(f"a kind of file that must not ship: {name}")
            config = tomllib.loads(bundle.read("config.toml").decode("utf-8"))
            version_py = re.search(r'VERSION\s*=\s*"([^"]+)"', bundle.read("scripts/shared/version.py").decode("utf-8")).group(1)
            wavs = {name: hashlib.sha256(bundle.read(name)).hexdigest() for name in members if name.startswith("files/")}
        committed_wavs = {name: hashlib.sha256(subprocess.run(["git", "-C", str(REPO), "show", f"{head}:{name}"],
                                                              capture_output=True).stdout).hexdigest() for name in release.REFERENCE_ASSETS}
        facts = {"archive": archive.name, "sha256": common.sha256(archive), "bytes": archive.stat().st_size, "members": len(members),
                 "version_py": version_py, "config_version": config.get("project", {}).get("version"),
                 "developer_mode": config.get("development", {}).get("developer_mode"), "untracked_left_behind": left_behind,
                 "reference_wavs": wavs, "commit": head}
        (folder / "package.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
        run.check("package: every member is the commit's own file and nothing else is inside", not problems, problems[:8] or
                  f"{len(members)} members, {archive.stat().st_size} bytes, sha256 {facts['sha256'][:16]}", **facts)
        run.check("package: the version is one version, and it is this release's", version_py == facts["config_version"] == "0.7.2",
                  f"version.py {version_py}, config.toml {facts['config_version']}")
        run.check("package: developer mode ships off", facts["developer_mode"] is False, facts["developer_mode"])
        run.check("package: exactly the six approved reference recordings, byte for byte", wavs == committed_wavs and len(wavs) == 6,
                  sorted(Path(name).name for name in wavs))
        for needed in (BAT, "README.md", "config.toml", "scripts/launcher.py", "scripts/requirements.txt",
                       "scripts/shared/bootstrap.py", "scripts/shared/bootstrap_host.ps1", "scripts/tts/data/bundled_clone_transcripts.json"):
            if needed not in members:
                run.check(f"package: {needed} is present", False, "missing")
        return archive

    def extract(self, archive: Path, name: str) -> Path:
        copy = self.scratch / name / "Audiobook Creation Tool"
        copy.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(copy)
        self.run.log(f"extract {name}: {copy} ({len(str(copy))} characters)")
        return copy

    # ------------------------------------------------------------------ steps inside a copy
    def env(self, name: str, *, offline: bool) -> dict:
        return clean_environment(self.scratch / name / "localappdata", self.scratch / name / "t", **(OFFLINE if offline else {}))

    def stage_zero(self, copy: Path, name: str) -> str | None:
        target = copy / "files" / "temp" / "bootstrap" / "selected-python.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        began = time.monotonic()
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(copy / "scripts" / "shared" / "bootstrap_host.ps1"),
                               "-OutFile", str(target), "-AssumeYes"], cwd=copy, env=self.env(name, offline=False), capture_output=True,
                              text=True, timeout=1200, creationflags=0x08000000)
        (self.run.root / f"{name}-stage0.log").write_text(done.stdout + "\n--- stderr\n" + done.stderr, encoding="utf-8")
        chosen = target.read_text(encoding="utf-8").strip() if target.is_file() else ""
        inside = bool(chosen) and Path(chosen).resolve().is_relative_to(copy)
        self.run.check(f"{name}: stage 0 gave the app its own Python, inside its folder", done.returncode == 0 and inside,
                       f"exit {done.returncode} in {time.monotonic() - began:.0f} s; {chosen or done.stdout[-300:]}")
        return chosen if done.returncode == 0 and inside else None

    def act(self, label: str, copy: Path, python: str, mode: str, *, offline: bool, name: str, timeout: float, extra=()) -> dict | None:
        record = self.run.child(label, HERE / "fresh_copy.py", ["--copy", str(copy), "--mode", mode, *extra], timeout=timeout,
                                env=self.env(name, offline=offline), python=python, exact_env=True)
        result = record["result"]
        if result is None or not result.get("finished"):
            self.run.check(f"{label}: the step ran and left a record", False,
                           (result or {}).get("error") or (result or {}).get("refused") or record.get("no_result") or f"exit {record['exit']}")
            return None
        return result

    def venv_check(self, copy: Path, name: str) -> int | None:
        python = copy / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            return None
        return subprocess.run([str(python), str(copy / "scripts" / "shared" / "bootstrap.py"), "--venv-check"], cwd=copy,
                              env=self.env(name, offline=True), capture_output=True, timeout=300, creationflags=0x08000000).returncode

    def launch_and_close(self, copy: Path, name: str) -> None:
        """The real window, started as the launcher starts it, seen on the desktop, closed, and gone with exit status 0."""
        from panel_run import Sampler

        sys.path.insert(0, str(common.GATE_DIR))
        from adapters.windows import native_input as native

        env = self.env(name, offline=True)
        env["PATH"] = f"{copy / 'files' / 'bin'}{os.pathsep}{env['PATH']}"  # as bootstrap.launch_gui hands the app its own FFmpeg
        child = subprocess.Popen([str(copy / ".venv" / "Scripts" / "pythonw.exe"), str(copy / "scripts" / "launcher.py")],
                                 cwd=copy / "scripts", env=env, creationflags=0x08000000)
        window = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and child.poll() is None and window is None:
            for pid in Sampler(False).tree():
                if pid != os.getpid():
                    window = next((item for item in native.windows_of(pid) if item["class"] == "TkTopLevel" and not item["owner"]), window)
            time.sleep(0.25)
        self.run.check(f"{name}: the application's window opened", window is not None, window or f"exit {child.poll()}")
        if window is not None:
            time.sleep(2.0)
            ctypes.windll.user32.PostMessageW(window["hwnd"], 0x0010, 0, 0)  # WM_CLOSE, as the window's own close button sends
        try:
            code = child.wait(60)
        except subprocess.TimeoutExpired:
            child.kill()
            code = "killed after 60 s"
        self.run.check(f"{name}: it closed and exited cleanly", code == 0, f"exit {code}; window {window and window['title']!r}")

    # ------------------------------------------------------------------ the three extractions
    def first(self, archive: Path) -> tuple[Path, str] | None:
        run, name = self.run, "A"
        copy = self.extract(archive, name)
        before = {item.name for item in copy.iterdir()}
        run.check("A: a fresh extraction holds the application and nothing set up", before == {"scripts", "files", "README.md", "config.toml", BAT}
                  and not (copy / ".venv").exists(), sorted(before))
        python = self.stage_zero(copy, name)
        if python is None:
            return None
        result = self.act("A-install", copy, python, "install", offline=False, name=name, timeout=5400)
        if result is None:
            return None
        run.check("A: the real first-run base setup completed", result["ok"] and result["final"].startswith("Setup"),
                  f"{result['final']} in {result['seconds']} s; steps {[step[1] for step in result['steps']]}")
        run.check("A: it went through its five steps in order", [step[0] for step in result["steps"]] == [0, 1, 2, 3, 4, 5],
                  [step[:2] for step in result["steps"]])
        run.check("A: the environment check now says it can launch", self.venv_check(copy, name) == 0, self.venv_check(copy, name))
        store = tree_size(copy / "files" / "runtime-data" / "python-packages")
        run.check("A: the package files were kept for an offline repair", store[0] > 20, f"{store[0]} files, {store[1] // 2**20} MB")
        run.check("A: FFmpeg is the app's own, inside its folder", (copy / "files" / "bin" / "ffmpeg.exe").is_file()
                  and (copy / "files" / "bin" / "ffprobe.exe").is_file(), sorted(p.name for p in (copy / "files" / "bin").glob("*.exe")))
        venv = str(copy / ".venv" / "Scripts" / "python.exe")
        status = self.act("A-status", copy, venv, "status", offline=True, name=name, timeout=600)
        if status is not None:
            run.check("A: the installed environment imports what the app needs", all(value is True for value in status["imports"].values())
                      and status["venv_python"], status["imports"])
            run.check("A: FFmpeg is proved and the sentence data is in place", status["ffmpeg_verified"] and not status["sentence_data_problem"]
                      and Path(status["ffmpeg"]).resolve().is_relative_to(copy), [status["ffmpeg"], status["sentence_data_problem"]])
            voices, counts = status["voices"], status["voice_counts"]
            optional = {key: value for key, value in voices.items() if not key.startswith("edge:")}
            run.check("A: every engine's voices are listed, and the Edge voices need nothing installed", all(counts.get(backend, 0) > 0
                      for backend in ("edge", "kokoro", "chatterbox", "qwen3")) and all(value["usable"] is True for key, value in
                                                                                         voices.items() if key.startswith("edge:")), counts)
            wrong = {key: value for key, value in optional.items() if value["usable"] is not False or not value["reason"].strip()}
            run.check("A: every optional voice says it is not installed, with a reason, and asking made no connection",
                      bool(optional) and not wrong and not status["network_attempts"] and not any(status["optional_folders"].values()),
                      wrong or {"voices": len(optional), "attempts": status["network_attempts"], "folders": status["optional_folders"],
                                "reasons": sorted({value["reason"] for value in optional.values()})})
            unoffered = sorted(key for key, value in optional.items() if not value["offered"])
            run.check("A: the app would offer Install & Continue for each of them, and installs none by itself", not unoffered,
                      unoffered or sorted({str(value["offered"]) for value in optional.values()}))
        tools = self.act("A-tools", copy, venv, "tools", offline=True, name=name, timeout=600)
        contained = False
        if tools is not None:
            contained = (Path(tools["output_base"]).is_relative_to(run.root) and Path(tools["settings_file"]).is_relative_to(copy)
                         and not tools["reveals"])
            run.check("A: the copy's settings are its own, its output base is inside this run, and no folder window was asked for",
                      contained, {key: tools[key] for key in ("settings_file", "output_base", "reveals")})
            run.check("A: the real launcher builds all six tools with no error and writes no output", len(tools["offered"]) == 6
                      and all(shown for _key, shown in tools["visited"]) and not tools["errors"] and not tools["output_created"],
                      {"offered": tools["offered"], "errors": tools["errors"][:2], "boxes": tools["message_boxes"][:3]})
        if contained:
            self.launch_and_close(copy, name)
        else:
            run.check("A: the application's window opened", False, "not started: the copy's output base and settings were not proved to be its own")
        run.check("A: nothing was installed outside the app's folder", tree_size(self.scratch / name / "localappdata")[0] == 0
                  or not any((self.scratch / name / "localappdata").rglob("python*.exe")),
                  f"{tree_size(self.scratch / name / 'localappdata')[0]} files under the stand-in LOCALAPPDATA")
        return copy, python

    def repair(self, copy: Path, python: str) -> None:
        run, name = self.run, "A"
        victim = copy / ".venv" / "Lib" / "site-packages" / "mutagen"
        if not run.check("repair: the package to damage is installed", victim.is_dir(), victim):
            return
        shutil.rmtree(victim)
        damaged = self.venv_check(copy, name)
        result = self.act("A-repair", copy, python, "repair", offline=True, name=name, timeout=3600)
        if result is None:
            return
        run.check("repair: the real repair restored the environment with the network blocked", result["ok"] and victim.is_dir(),
                  f"{result['final']} in {result['seconds']} s (the check before it answered {damaged})")
        run.check("repair: the environment check says it can launch again", self.venv_check(copy, name) == 0, self.venv_check(copy, name))

    def second(self, archive: Path, first: Path) -> None:
        run, name = self.run, "B"
        copy = self.extract(archive, name)
        for seed in SEEDS:
            shutil.copytree(first / seed, copy / seed)
        python = str(copy / "files" / "runtime-data" / "python" / "python.exe")
        stopped = self.act("B-stop", copy, python, "install", offline=True, name=name, timeout=1800, extra=["--stop-after-pip", "4"])
        if stopped is not None:
            stop = stopped["stop"]
            run.check("B: setup was stopped while pip was running", bool(stop.get("asked")) and stop.get("told_a_running_pip") is True, stop)
            run.check("B: it then ended as stopped, promptly, and said so", stopped["ok"] is False and stopped["final"] == stopped.get("stopped_message")
                      and stopped["seconds"] - stop.get("at", 0) <= 20, f"{stopped['final'][:80]} {stopped['seconds'] - stop.get('at', 0):.1f} s after the stop")
            run.check("B: nothing the stopped setup started was left running", not stopped.get("children_three_seconds_later"),
                      {"at once": stopped.get("children_when_setup_returned"), "after 3 s": stopped.get("children_three_seconds_later")})
        again = self.act("B-install", copy, python, "install", offline=True, name=name, timeout=3600)
        if again is not None:
            run.check("B: run again, setup completed with the network blocked, from the files already here", again["ok"],
                      f"{again['final']} in {again['seconds']} s")
            run.check("B: the environment check says it can launch", self.venv_check(copy, name) == 0, self.venv_check(copy, name))

    def third(self, archive: Path, first: Path) -> None:
        run, name = self.run, "C"
        copy = self.extract(archive, name)
        shutil.copytree(first / SEEDS[0], copy / SEEDS[0])
        python = str(copy / "files" / "runtime-data" / "python" / "python.exe")
        failed = self.act("C-offline", copy, python, "install", offline=True, name=name, timeout=1800)
        if failed is None:
            return
        run.check("C: with no network and nothing to reuse, setup fails and says so", failed["ok"] is False and bool(failed["final"].strip()),
                  f"{failed['final'][:160]} after {failed['seconds']} s")
        check = self.venv_check(copy, name)
        run.check("C: what it left behind is not taken for a working environment", check != 0, f"--venv-check answered {check}")
        run.check("C: the setup log is there to read", any((copy / "files" / "runtime-data" / "logs").glob("setup_*.log")), "")


def body(run: common.Scenario) -> None:
    if run.args.network != "online-setup":
        raise common.Blocked("a first-run setup downloads the app's Python, packages and FFmpeg (about 2.9 GB) and this run was not given "
                             "--network online-setup; nothing was downloaded")
    if sys.platform != "win32":
        raise common.Blocked("this scenario is Windows'")
    needed = ("scripts/shared/release.py", "scripts/launcher.py", "scripts/requirements.txt", "scripts/tts/epub2tts_gui.py", "README.md", BAT)
    missing = [name for name in needed if not (REPO / name).is_file()]
    if missing:
        raise common.Blocked(f"the application is not complete here, so there is nothing to package: missing {missing}")
    temp = Path(os.environ["TEMP"]).resolve()
    if "act-gate" not in temp.parts:
        raise common.Blocked(f"TEMP is {temp}, not the gate's own scratch: run this through verify.py so its folders are owned and removed by the gate")
    scratch = temp.parent / "fw"
    scratch.mkdir()
    identity = run.identity(elevated=bool(ctypes.windll.shell32.IsUserAnAdmin()), scratch=str(scratch), long_paths=long_paths_enabled())
    run.log(f"identity: HEAD {identity['head']}, elevated {identity['elevated']}, scratch {scratch}")
    run.check("this run is not elevated: setup needs no administrator rights", not identity["elevated"], identity["elevated"])
    fresh = Fresh(run, scratch)
    archive = fresh.package()
    if run.args.smoke:
        return
    first = fresh.first(archive)
    if first is None:
        return
    copy, python = first
    fresh.repair(copy, python)
    fresh.second(archive, copy)
    fresh.third(archive, copy)
    sizes = {name: tree_size(scratch / name)[1] // 2**20 for name in ("A", "B", "C") if (scratch / name).is_dir()}
    run.log(f"scratch used (MB): {sizes}; the gate removes it when this run passes and keeps it when it does not")


def main(argv=None) -> int:
    run = common.start("fresh-windows", argv, network=("online-setup",))
    return run if isinstance(run, int) else run.finish(body)


if __name__ == "__main__":
    raise SystemExit(main())
