"""Stage 0 on macOS (``scripts/shared/bootstrap_host_macos.sh``), run for real under bash 3.2.

v0.8.x P1A introduced it; v0.8.2 Phase 4 made it provide the app's own pinned uv 0.13.10
(``files/runtime-data/uv/uv``) and let that uv install the pinned CPython 3.12.15 (python-build-standalone 20261009) from
ACT's own verified copy of the archive (``files/runtime-data/uv/mirror``), through ACT's own download metadata.

The states held here, against fixture archives in scratch app folders: the healthy fast path, declined consent, a
verified install, size and hash mismatches, every unsafe member of the uv archive, stale leftovers of a dead process,
both watchdog cases (a hung proof and one that ignores SIGTERM), a moved copy whose interpreter is reinstalled, the
earlier version's Python left alone, and KX-5: SIGHUP (the Terminal window closing) during curl and during the proof.

The uv in most tests is a stand-in (a small bash program accepted through the ``--qualify-uv-*`` switches) that records
its arguments and environment and "installs" an APFS clone of the test interpreter's own python-build-standalone tree;
the proof then runs that interpreter for real. Those tests need the suite to run on exactly the pinned build (the
developer profile's environment does: it is built on the managed CPython 3.12.15). One test runs the real uv on the
real pinned archives when they are present in ``files/temp/bootstrap``.

Nothing here touches the checkout's own files/runtime-data or files/temp, needs the network, or calls Homebrew: each
test copies the script into its own scratch tree and runs it with a clean environment (PATH = /usr/bin:/bin:...).
"""

from __future__ import annotations

import hashlib
import http.server
import io
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE0 = REPO_ROOT / "scripts" / "shared" / "bootstrap_host_macos.sh"
DOWNLOADS_JSON = REPO_ROOT / "scripts" / "shared" / "python-downloads.json"
NATIVE_MACOS = "native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_MACOS)

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from shared import uv_runner  # noqa: E402  (standard library only)

PINS = uv_runner.MACOS
PY_KEY = PINS.python_key
UV_TOP = "uv-aarch64-apple-darwin"
PINNED_UV_ARCHIVE = REPO_ROOT / "files" / "temp" / "bootstrap" / PINS.uv_archive
PINNED_ARCHIVE = REPO_ROOT / "files" / "temp" / "bootstrap" / PINS.python_archive


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pinned_base_tree() -> Path:
    """The test interpreter's own tree, when it is exactly the pinned build (the proof compares sys.version)."""
    base = Path(sys.base_prefix).resolve()
    if sys.version != PINS.python_sys_version or platform.machine() != "arm64":
        pytest.skip(f"the suite runs on {sys.version!r}, not the pinned build: run it in the developer profile")
    if not (base / "bin" / "python3.12").is_file():
        pytest.skip("the test interpreter is not a python-build-standalone 3.12 tree (bin/python3.12)")
    return base


def _clone_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["/bin/cp", "-cR", str(source), str(destination)], capture_output=True)
    if done.returncode != 0:  # not APFS: a plain copy keeps the links
        shutil.copytree(source, destination, symlinks=True)


class App:
    def __init__(self, root: Path):
        self.root = root
        self.script = root / "scripts" / "shared" / STAGE0.name
        self.runtime = root / "files" / "runtime-data"
        self.uv_home = self.runtime / "uv"
        self.uv = self.uv_home / "uv"
        self.python_home = self.uv_home / "python" / PY_KEY
        self.python = self.python_home / "bin" / "python3.12"
        self.minor_link = self.uv_home / "python" / PINS.python_minor_key
        self.mirror_archive = self.uv_home / "mirror" / uv_runner.PYTHON_BUILD / PINS.python_archive
        self.downloads = root / "files" / "temp" / "bootstrap"
        self.home = root.parent / "home"
        self.tmp = root.parent / "tmp"
        self.uv_log = root.parent / "fake-uv.log"
        self.uv_switches: list = []

    def env(self) -> dict:
        self.home.mkdir(exist_ok=True)
        self.tmp.mkdir(exist_ok=True)
        # Settings a developer's shell may carry: stage 0 must hand none of them to uv.
        return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home), "TMPDIR": str(self.tmp) + "/",
                "LANG": "en_US.UTF-8", "UV_INDEX_URL": "https://egress.invalid/simple", "PIP_INDEX_URL": "x",
                "PYTHONPATH": "/nowhere", "VIRTUAL_ENV": "/nowhere"}

    def run(self, *args, timeout: float = 180, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(self.script), *map(str, self.uv_switches), *map(str, args)],
                              capture_output=True, text=True, timeout=timeout, env=self.env(),
                              stdin=subprocess.DEVNULL, **kwargs)

    def popen(self, *args) -> subprocess.Popen:
        return subprocess.Popen(["/bin/bash", str(self.script), *map(str, self.uv_switches), *map(str, args)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env(),
                                stdin=subprocess.DEVNULL, start_new_session=True)

    def leftovers(self) -> list[str]:
        names = []
        if self.uv_home.is_dir():
            names += [p.name for p in self.uv_home.iterdir() if p.name.startswith(".act-stage")]
        if (self.uv_home / "t").is_dir():
            names += [f"t/{p.name}" for p in (self.uv_home / "t").iterdir()]
        if self.downloads.is_dir():
            names += [p.name for p in self.downloads.iterdir() if p.name.startswith((".probe", ".listing"))
                      or ".part" in p.name]
        return names

    def uv_calls(self) -> list[str]:
        return self.uv_log.read_text(encoding="utf-8").splitlines() if self.uv_log.exists() else []


@pytest.fixture
def app(tmp_path) -> App:
    root = tmp_path / "My Apps" / "ACT C1"
    (root / "scripts" / "shared").mkdir(parents=True)
    shutil.copy2(STAGE0, root / "scripts" / "shared" / STAGE0.name)
    shutil.copy2(DOWNLOADS_JSON, root / "scripts" / "shared" / DOWNLOADS_JSON.name)
    return App(root)


def _fake_uv_program(app: App, base: Path | None) -> bytes:
    """A stand-in uv: records its arguments and uv-related environment, and on ``python install`` clones ``base`` to
    where the real uv would put the pinned build (with uv's BUILD stamp and its minor-version link)."""
    log = shlex.quote(str(app.uv_log))
    lines = [
        "#!/bin/bash",
        f"{{ printf 'ARGS'; printf ' %s' \"$@\"; printf '\\n'; /usr/bin/env | /usr/bin/grep -E "
        f"'^(UV_|PIP_|PYTHON|VIRTUAL_ENV|TMPDIR=|NO_COLOR=)' | /usr/bin/sort | /usr/bin/sed 's/^/ENV /'; }} >> {log}",
        '[ "$1" = python ] && [ "$2" = install ] || exit 9',
    ]
    if base is None:
        lines.append("exit 7")
    else:
        lines += [
            f'home="$UV_PYTHON_INSTALL_DIR/{PY_KEY}"',
            '/bin/rm -rf "$home"; /bin/mkdir -p "$UV_PYTHON_INSTALL_DIR"',
            f'/bin/cp -cR {shlex.quote(str(base))} "$home" 2>/dev/null || /bin/cp -R {shlex.quote(str(base))} "$home"',
            '/bin/rm -rf "$home/lib/python3.12/site-packages"; /bin/mkdir "$home/lib/python3.12/site-packages"',
            f"printf '%s\\n' {uv_runner.PYTHON_BUILD} > \"$home/BUILD\"",
            f'/bin/ln -sfn "$home" "$UV_PYTHON_INSTALL_DIR/{PINS.python_minor_key}"',
            "exit 0",
        ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _uv_archive(tmp_path: Path, program: bytes, extra: tarfile.TarInfo | None = None,
                payload: bytes = b"") -> tuple[Path, int, str]:
    path = tmp_path / f"uv-{_sha(program)[:8]}-{(extra.name if extra else 'ok').replace('/', '_')}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        top = tarfile.TarInfo(UV_TOP)
        top.type, top.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(top)
        for name in ("uv", "uvx"):
            info = tarfile.TarInfo(f"{UV_TOP}/{name}")
            info.size, info.mode = len(program), 0o755
            tar.addfile(info, io.BytesIO(program))
        if extra is not None:
            tar.addfile(extra, io.BytesIO(payload) if extra.isfile() else None)
    data = path.read_bytes()
    return path, len(data), _sha(data)


@pytest.fixture
def fake_uv(app, tmp_path):
    """A verified stand-in uv archive; ``app.uv_switches`` make stage 0 accept it (and the installed program) as pinned."""
    program = _fake_uv_program(app, _pinned_base_tree())
    archive, size, digest = _uv_archive(tmp_path, program)
    app.uv_switches = ["--qualify-uv-size", size, "--qualify-uv-sha256", digest,
                       "--qualify-uv-exe-sha256", _sha(program)]
    return archive


@pytest.fixture
def py_archive(tmp_path) -> list:
    """A stand-in for the Python archive (the stand-in uv does not read it): its switches, verified and kept."""
    data = b"stand-in python-build-standalone archive\n" * 64
    path = tmp_path / "python-fixture.tar.gz"
    path.write_bytes(data)
    return ["--archive-path", path, "--qualify-size", len(data), "--qualify-sha256", _sha(data)]


def _kept(py_archive: list) -> list:
    """The switches that make a later run accept the stand-in archive already kept in the mirror."""
    return py_archive[2:]


def _installed(app: App, fake_uv: Path, py_archive: list) -> None:
    """The state after a successful first run."""
    done = app.run("--assume-yes", "--uv-archive-path", fake_uv, *py_archive)
    assert done.returncode == 0, done.stdout + done.stderr


def _sitecustomize(app: App, text: str) -> None:
    (app.python_home / "lib" / "python3.12" / "site-packages" / "sitecustomize.py").write_text(text, encoding="utf-8")


def _group_gone(pgid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _pid_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------- #
#  Shape: bash 3.2, LF, the tools it may use
# --------------------------------------------------------------------------- #
def test_stage0_runs_on_the_bash_macos_ships_and_uses_no_bash4_constructs():
    version = subprocess.run(["/bin/bash", "--version"], capture_output=True, text=True).stdout
    assert "version 3.2" in version, version.splitlines()[0]
    assert subprocess.run(["/bin/bash", "-n", str(STAGE0)]).returncode == 0
    text = STAGE0.read_text(encoding="utf-8")
    for construct in ("declare -A", "mapfile", "readarray", ",,}", "^^}", "|&", ";;&", "coproc", "${!", "&>>"):
        assert construct not in text, construct
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for tool in (r"\blipo\b", r"\botool\b", r"\bbrew\b", r"\bxcrun\b", r"\bpython3\b(?!\.12)", r"(^|[;&|(]\s*)timeout\s",
                 r"astral\.sh/uv/install", r"\bsudo\b"):
        assert not re.search(tool, code, re.MULTILINE), tool


# --------------------------------------------------------------------------- #
#  The states
# --------------------------------------------------------------------------- #
def test_declined_consent_downloads_nothing_and_exits_2(app):
    done = app.run("--assume-no")
    assert done.returncode == 2, done.stdout
    assert "Nothing was downloaded" in done.stdout
    assert "has not been downloaded yet" in done.stdout and "has not been installed yet" in done.stdout
    assert not app.uv_home.exists() and app.leftovers() == []


def test_no_terminal_means_no_consent(app):
    done = app.run()  # stdin is not a terminal: nothing can be answered, so nothing is downloaded
    assert done.returncode == 2
    assert "No answer can be typed here" in done.stdout


def test_a_verified_uv_installs_the_pinned_python_from_the_kept_archive_contained(app, fake_uv, py_archive):
    done = app.run("--assume-yes", "--uv-archive-path", fake_uv, *py_archive, "--out-file", app.root / "out.txt")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (app.root / "out.txt").read_text() == str(app.python)
    assert app.uv.is_file() and os.access(app.uv, os.X_OK) and not app.uv.is_symlink()
    assert app.mirror_archive.is_file(), "the verified archive is kept for offline repairs"
    assert Path(py_archive[1]).exists(), "an archive given with --archive-path is the caller's and is kept"
    calls = app.uv_calls()
    args = next(line for line in calls if line.startswith("ARGS"))
    mirror = "file://" + str(app.uv_home / "mirror").replace(" ", "%20")
    assert args.startswith(f"ARGS python install {uv_runner.PYTHON_VERSION} --mirror {mirror} "
                           f"--python-downloads-json-url {app.root / 'scripts' / 'shared' / DOWNLOADS_JSON.name}")
    for flag in ("--no-bin", "--no-registry", "--no-config"):
        assert flag in args, flag
    assert "--reinstall" not in args
    env = {line[4:].split("=", 1)[0]: line[4:].split("=", 1)[1] for line in calls if line.startswith("ENV ")}
    assert env["UV_NO_CONFIG"] == "1" and env["UV_PYTHON_PREFERENCE"] == "only-managed"
    assert env["UV_PYTHON_DOWNLOADS"] == "manual" and env["UV_PYTHON_INSTALL_BIN"] == "0"
    assert env["UV_PYTHON_INSTALL_DIR"] == str(app.uv_home / "python")
    assert env["UV_CACHE_DIR"] == str(app.runtime / "uvc")
    assert env["UV_PYTHON_CACHE_DIR"].startswith(str(app.uv_home / "t" / "m")), "a scratch folder of its own"
    assert "UV_INDEX_URL" not in env and "PIP_INDEX_URL" not in env and "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    assert app.leftovers() == [], "staging, listing, probe and scratch are gone"
    # And the next run is the healthy fast path: no question, no uv.
    app.uv_log.unlink()
    started = time.monotonic()
    again = app.run("--assume-no", "--out-file", app.root / "again.txt")
    assert again.returncode == 0, again.stdout
    assert time.monotonic() - started < 20 and app.uv_calls() == []
    assert "Download them now" not in again.stdout


@pytest.mark.parametrize("damage", ["truncated", "one-byte-changed"])
def test_a_wrong_uv_archive_is_rejected_and_nothing_is_installed(app, fake_uv, py_archive, tmp_path, damage):
    bad = tmp_path / "bad.tar.gz"
    data = bytearray(fake_uv.read_bytes())
    if damage == "truncated":
        data = data[: len(data) // 2]
    else:
        data[len(data) // 3] ^= 0xFF
    bad.write_bytes(bytes(data))
    done = app.run("--assume-yes", "--uv-archive-path", bad, *py_archive)
    assert done.returncode == 3
    assert "rejected" in done.stdout
    assert ("bytes, not" if damage == "truncated" else "SHA-256") in done.stdout
    assert not app.uv.exists() and not app.python_home.exists() and app.leftovers() == []


def _member(name: str, kind=tarfile.REGTYPE, *, mode: int = 0o644, link: str = "", size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.linkname, info.size = kind, mode, link, size
    return info


UNSAFE = {
    "absolute path": (_member("/tmp/act-evil"), "an absolute path"),
    "parent traversal": (_member(f"{UV_TOP}/../act-evil"), "parent-directory"),
    "outside the top folder": (_member("other/act-evil"), f"outside the {UV_TOP}/ folder"),
    "link": (_member(f"{UV_TOP}/evil", tarfile.SYMTYPE, link="../../../etc/passwd"), "not a file or folder"),
    "absolute link target": (_member(f"{UV_TOP}/evil", tarfile.SYMTYPE, link="/etc/passwd"), "not a file or folder"),
    "set-user-ID file": (_member(f"{UV_TOP}/suid", mode=0o4755), "set-user-ID"),
    "set-group-ID file": (_member(f"{UV_TOP}/sgid", mode=0o2755), "set-user-ID or set-group-ID"),
    "character device": (_member(f"{UV_TOP}/dev-null", tarfile.CHRTYPE), "not a file or folder"),
    "fifo": (_member(f"{UV_TOP}/fifo", tarfile.FIFOTYPE), "not a file or folder"),
    "hard link": (_member(f"{UV_TOP}/hard", tarfile.LNKTYPE, link=f"{UV_TOP}/uv"), "hard link"),
    "space in a name": (_member(f"{UV_TOP}/a b"), "space"),
}


@pytest.mark.parametrize("case", sorted(UNSAFE))
def test_an_unsafe_member_refuses_the_whole_uv_archive_before_anything_is_extracted(app, py_archive, tmp_path, case):
    member, expected = UNSAFE[case]
    program = _fake_uv_program(app, None)
    archive, size, digest = _uv_archive(tmp_path, program, member)
    done = app.run("--assume-yes", "--uv-archive-path", archive, "--qualify-uv-size", size, "--qualify-uv-sha256",
                   digest, "--qualify-uv-exe-sha256", _sha(program), *py_archive)
    assert done.returncode == 3, done.stdout
    assert "refused and nothing was unpacked" in done.stdout and expected in done.stdout, done.stdout
    assert not app.uv.exists() and not app.python_home.exists()
    assert app.leftovers() == []
    assert not Path("/tmp/act-evil").exists()


def test_an_unpacked_uv_that_is_not_the_pinned_program_is_not_used(app, py_archive, tmp_path):
    program = _fake_uv_program(app, None)
    archive, size, digest = _uv_archive(tmp_path, program)
    done = app.run("--assume-yes", "--uv-archive-path", archive, "--qualify-uv-size", size, "--qualify-uv-sha256",
                   digest, "--qualify-uv-exe-sha256", "0" * 64, *py_archive)
    assert done.returncode == 3 and "not the pinned program" in done.stdout
    assert not app.uv.exists() and app.leftovers() == []


def test_a_failed_uv_install_reports_and_keeps_nothing_unfinished(app, py_archive, tmp_path):
    program = _fake_uv_program(app, None)  # exits 7 on python install
    archive, size, digest = _uv_archive(tmp_path, program)
    done = app.run("--assume-yes", "--uv-archive-path", archive, "--qualify-uv-size", size, "--qualify-uv-sha256",
                   digest, "--qualify-uv-exe-sha256", _sha(program), *py_archive)
    assert done.returncode == 3 and "uv could not install the app's Python (exit 7)" in done.stdout
    assert app.leftovers() == []


def test_leftovers_of_a_dead_run_are_removed_and_a_live_runs_are_kept(app):
    app.uv_home.mkdir(parents=True)
    app.downloads.mkdir(parents=True)
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    stale_stage = app.uv_home / f".act-stage-uv-{dead.pid}"
    (stale_stage / UV_TOP).mkdir(parents=True)
    stale_scratch = app.uv_home / "t" / f"m{dead.pid}"
    (stale_scratch / "pyc").mkdir(parents=True)
    stale_part = app.downloads / f"archive.tar.gz.part-{dead.pid}"
    stale_part.write_bytes(b"partial")
    live = app.uv_home / f".act-stage-uv-{os.getpid()}"
    live.mkdir()
    done = app.run("--assume-no")
    assert done.returncode == 2
    assert not stale_stage.exists() and not stale_part.exists() and not stale_scratch.exists()
    assert live.exists(), "a staging folder whose process is alive is never touched"
    assert "interrupted earlier setup" in done.stdout


def test_a_moved_copy_has_its_python_installed_again_for_the_new_folder(app, fake_uv, py_archive, tmp_path):
    """uv's minor-version link (and its install-time patches) still name the old folder: uv installs it again from
    the kept archive, offline, with --reinstall."""
    _installed(app, fake_uv, py_archive)
    app.minor_link.unlink()
    app.minor_link.symlink_to(tmp_path / "the original folder" / PY_KEY)
    app.uv_log.unlink()
    done = app.run("--assume-no", *_kept(py_archive))
    assert done.returncode == 0, done.stdout
    assert "was moved or copied" in done.stdout
    args = next(line for line in app.uv_calls() if line.startswith("ARGS"))
    assert args.endswith(" --reinstall"), args
    assert os.readlink(app.minor_link) == str(app.python_home)


def test_the_python_of_an_earlier_version_is_neither_used_nor_touched(app):
    legacy = app.runtime / "python" / "bin"
    legacy.mkdir(parents=True)
    (legacy / "python3.12").write_bytes(b"#!/bin/sh\nexit 0\n")
    before = (legacy / "python3.12").read_bytes()
    done = app.run("--assume-no", "--out-file", app.root / "out.txt")
    assert done.returncode == 2 and not (app.root / "out.txt").exists()
    assert (legacy / "python3.12").read_bytes() == before


def test_windows_origin_runtime_data_is_foreign_and_harmless(app):
    """MAC-029: a folder copied from Windows (uv.exe, a python.exe layout, Windows wheels) is never adopted."""
    (app.uv_home).mkdir(parents=True)
    (app.uv_home / "uv.exe").write_bytes(b"MZ")
    (app.python_home).mkdir(parents=True)
    (app.python_home / "python.exe").write_bytes(b"MZ")
    (app.runtime / "settings.json").write_text('{"m4b_converter": {"input_dir": "C:\\\\Users\\\\x\\\\Books"}}')
    done = app.run("--assume-no")
    assert done.returncode == 2
    assert "bin/python3.12 is missing" in done.stdout
    assert (app.python_home / "python.exe").exists(), "declined: nothing is moved or deleted"
    assert (app.runtime / "settings.json").exists()


# --------------------------------------------------------------------------- #
#  The watchdog (macOS has no `timeout`)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ignores_term", [False, True], ids=["hung", "ignores-SIGTERM"])
def test_a_proof_that_hangs_is_ended_by_the_watchdog_and_reaped(app, fake_uv, py_archive, tmp_path, ignores_term):
    _installed(app, fake_uv, py_archive)
    app.mirror_archive.unlink()  # so a replacement would need a download, which is declined below
    pidfile = tmp_path / "probe.pid"
    _sitecustomize(app, "import os, signal, time\n"
                        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignores_term else "")
                        + "time.sleep(600)\n")
    started = time.monotonic()
    done = app.run("--assume-no", "--probe-timeout", 2)
    elapsed = time.monotonic() - started
    assert done.returncode == 2, done.stdout  # the proof failed, then the replacement's download was declined
    assert "did not finish within 2 seconds" in done.stdout
    assert elapsed < (2 + 2 + 6), elapsed
    assert _pid_gone(int(pidfile.read_text()), 1.0), "the watchdog reaps what it started"
    assert app.python_home.exists(), "declined: the interpreter that failed is not touched"


def test_a_failed_tk_proof_is_replaced_from_the_kept_archive_without_a_download(app, fake_uv, py_archive):
    _installed(app, fake_uv, py_archive)
    _sitecustomize(app, "import sys\nsys.modules['tkinter'] = None\n")
    app.uv_log.unlink()
    done = app.run("--assume-no", *_kept(py_archive))  # the kept archive is enough: nothing to ask
    assert done.returncode == 0, done.stdout
    assert "did not pass its check" in done.stdout
    assert any(line.endswith(" --reinstall") for line in app.uv_calls() if line.startswith("ARGS"))


# --------------------------------------------------------------------------- #
#  KX-5: the Terminal window closes (SIGHUP to the foreground group)
# --------------------------------------------------------------------------- #
class _Trickle(http.server.BaseHTTPRequestHandler):
    payload = b""
    started = threading.Event()

    def do_GET(self):  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        try:
            for start in range(0, len(self.payload), 16384):
                self.wfile.write(self.payload[start:start + 16384])
                self.wfile.flush()
                self.started.set()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def trickle_server():
    _Trickle.payload = os.urandom(4 * 1024 * 1024)
    _Trickle.started = threading.Event()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield (f"http://127.0.0.1:{server.server_address[1]}/python.tar.gz", len(_Trickle.payload),
           _sha(_Trickle.payload))
    server.shutdown()
    server.server_close()


def _uv_in_place(app: App, fake_uv: Path) -> None:
    """Only the pinned (stand-in) uv is installed: the next run needs just the Python archive."""
    app.uv_home.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fake_uv) as tar:
        app.uv.write_bytes(tar.extractfile(f"{UV_TOP}/uv").read())
    app.uv.chmod(0o755)


def test_kx5_sighup_during_curl_ends_curl_and_removes_the_partial_download(app, fake_uv, trickle_server):
    url, size, digest = trickle_server
    _uv_in_place(app, fake_uv)
    proc = app.popen("--assume-yes", "--qualify-url", url, "--qualify-size", size, "--qualify-sha256", digest)
    assert _Trickle.started.wait(20), "the download never started"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not any(".part-" in n for n in app.leftovers()):
        time.sleep(0.05)
    assert any(".part-" in n for n in app.leftovers()), "curl is writing its .part file"
    os.killpg(proc.pid, signal.SIGHUP)
    out, _ = proc.communicate(timeout=15)
    assert _group_gone(proc.pid, 5.0), "stage 0 and curl are gone"
    assert app.leftovers() == [], out
    assert not app.python_home.exists() and not app.mirror_archive.exists()


def test_kx5_sighup_during_the_proof_ends_the_proof(app, fake_uv, py_archive, tmp_path):
    _installed(app, fake_uv, py_archive)
    pidfile = tmp_path / "probe.pid"
    _sitecustomize(app, f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(600)\n")
    proc = app.popen("--assume-no")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not pidfile.exists():
        time.sleep(0.05)
    assert pidfile.exists(), "the proof started"
    os.killpg(proc.pid, signal.SIGHUP)
    proc.communicate(timeout=15)
    assert _group_gone(proc.pid, 5.0)
    assert _pid_gone(int(pidfile.read_text()), 1.0)
    assert app.leftovers() == []


def test_a_completed_download_is_verified_then_kept_and_installed(app, fake_uv, trickle_server):
    url, size, digest = trickle_server
    _uv_in_place(app, fake_uv)
    done = app.run("--assume-yes", "--qualify-url", url, "--qualify-size", size, "--qualify-sha256", digest,
                   timeout=300)
    assert done.returncode == 0, done.stdout
    assert app.python.is_file()
    assert _sha(app.mirror_archive.read_bytes()) == digest, "the verified download is kept for offline repairs"
    assert not any(app.downloads.iterdir()), "nothing else is left in the download folder"


def test_the_qualification_url_switch_accepts_loopback_only(app):
    done = app.run("--assume-yes", "--qualify-url", "https://example.com/python.tar.gz")
    assert done.returncode == 3 and "127.0.0.1" in done.stdout


# --------------------------------------------------------------------------- #
#  The real thing, when the pinned archives are on this Mac
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (PINNED_ARCHIVE.is_file() and PINNED_UV_ARCHIVE.is_file()),
                    # The reason the skip policy names (macos-pinned-archives-not-downloaded); it now covers both archives.
                    reason="the pinned archive has not been downloaded here")
def test_the_real_uv_installs_the_real_pinned_python_offline_and_it_works(app):
    done = app.run("--assume-yes", "--uv-archive-path", PINNED_UV_ARCHIVE, "--archive-path", PINNED_ARCHIVE,
                   timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    proof = subprocess.run([str(app.python), "-I", "-c",
                            "import tkinter, platform, sys; r = tkinter.Tk(); r.withdraw(); "
                            "print(r.tk.call('info', 'patchlevel'), r.tk.call('tk', 'windowingsystem'), "
                            "platform.machine(), '%d.%d.%d' % sys.version_info[:3]); r.destroy()"],
                           capture_output=True, text=True, timeout=60)
    assert proof.stdout.split()[1:] == ["aqua", "arm64", "3.12.15"], proof.stdout + proof.stderr
    assert (app.python_home / "BUILD").read_text().strip() == uv_runner.PYTHON_BUILD
    assert app.leftovers() == []


# --------------------------------------------------------------------------- #
#  The launcher's route for a moved copy (v0.8.2 Phase 4, found natively)
# --------------------------------------------------------------------------- #
LAUNCHER = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command"


def _launcher_sandbox(root: Path, venv_python_link: str | None) -> Path:
    """The real launcher beside a stand-in stage 0 (it names a stand-in app Python) and that Python, which records the
    arguments it was started with. Nothing real is set up or launched."""
    shared = root / "scripts" / "shared"
    shared.mkdir(parents=True)
    shutil.copy2(LAUNCHER, root / LAUNCHER.name)
    record = root.parent / "app-python.args"
    fake_python = root.parent / "fake python3.12"
    fake_python.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$*\" >> {shlex.quote(str(record))}\nexit 0\n")
    fake_python.chmod(0o755)
    (shared / STAGE0.name).write_text(
        "#!/bin/bash\n"
        '[ "$1" = --out-file ] || exit 3\n'
        'mkdir -p "$(dirname "$2")" && printf \'%s\' ' + shlex.quote(str(fake_python)) + ' > "$2"\n')
    if venv_python_link is not None:
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").symlink_to(venv_python_link)
    return record


def test_a_moved_copy_whose_environment_python_link_dangles_is_repaired_not_set_up_again(tmp_path):
    """uv's macOS environment links .venv/bin/python to the app Python's absolute path. After the folder is moved that
    link dangles, so both [ -x ] and [ -e ] are false and the launcher used to run first-time setup on an installed
    copy. It must take the bounded --repair-venv route; a copy with no environment at all still gets first-time setup."""
    moved = tmp_path / "moved" / "ACT été"
    moved_record = _launcher_sandbox(moved, str(tmp_path / "old place" / "python3.12"))
    fresh = tmp_path / "fresh" / "ACT"
    fresh_record = _launcher_sandbox(fresh, None)
    for root in (moved, fresh):
        done = subprocess.run(["/bin/bash", str(root / LAUNCHER.name)], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        assert done.returncode == 0, done.stdout + done.stderr
    assert moved_record.read_text().splitlines() == ["scripts/shared/bootstrap.py --repair-venv"]
    assert fresh_record.read_text().splitlines() == ["scripts/shared/bootstrap.py"]
