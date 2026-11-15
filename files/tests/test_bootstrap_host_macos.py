"""v0.8.x P1A -- stage 0 on macOS (``scripts/shared/bootstrap_host_macos.sh``), run for real under bash 3.2.

Every state of plan section 8.2 / 14.1 against fixture archives in scratch app folders: the healthy fast path,
declined consent, a verified install, size and hash mismatches, every unsafe archive member, stale staging from a
dead process, both watchdog cases (a hung proof and one that ignores SIGTERM), a failed Tk proof that is set aside and
never deleted, Windows-origin state, and KX-5: SIGHUP (the Terminal window closing) during curl and during the proof.

Nothing here touches the checkout's own files/runtime-data or files/temp, needs the network, or calls Homebrew: each
test copies the script into its own scratch tree and runs it with a clean environment (PATH = /usr/bin:/bin:...).
The interpreter fixtures are APFS clones of the test interpreter's own python-build-standalone tree.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import os
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
NATIVE_MACOS = "native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_MACOS)

PINNED_ARCHIVE = REPO_ROOT / "files" / "temp" / "bootstrap" / \
    "cpython-3.12.15+20261009-aarch64-apple-darwin-install_only.tar.gz"
PINNED_SIZE = 25165569
PINNED_SHA256 = "83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8"


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
def _base_python_tree() -> Path:
    base = Path(sys.base_prefix)
    py = base / "bin" / "python3.12"
    if not py.is_file():
        pytest.skip("the test interpreter is not a python-build-standalone 3.12 tree (bin/python3.12)")
    return base


def _clone_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["/bin/cp", "-cR", str(source), str(destination)], capture_output=True)
    if done.returncode != 0:  # not APFS: a plain copy keeps the links
        shutil.copytree(source, destination, symlinks=True)


@pytest.fixture(scope="session")
def good_archive(tmp_path_factory) -> tuple[Path, int, str]:
    """A tar.gz with the test interpreter's whole tree under ``python/`` (the PBS layout)."""
    base = _base_python_tree()
    folder = tmp_path_factory.mktemp("stage0-archive")
    tree = folder / "python"
    _clone_tree(base, tree)
    shutil.rmtree(tree / "lib" / "python3.12" / "site-packages", ignore_errors=True)
    (tree / "lib" / "python3.12" / "site-packages").mkdir()
    archive = folder / "fixture-python.tar.gz"
    with tarfile.open(archive, "w:gz", compresslevel=1) as tar:
        tar.add(tree, arcname="python")
    data = archive.read_bytes()
    return archive, len(data), hashlib.sha256(data).hexdigest()


class App:
    def __init__(self, root: Path):
        self.root = root
        self.script = root / "scripts" / "shared" / "bootstrap_host_macos.sh"
        self.runtime = root / "files" / "runtime-data"
        self.python_home = self.runtime / "python"
        self.downloads = root / "files" / "temp" / "bootstrap"
        self.home = root.parent / "home"
        self.tmp = root.parent / "tmp"

    def env(self) -> dict:
        self.home.mkdir(exist_ok=True)
        self.tmp.mkdir(exist_ok=True)
        return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home), "TMPDIR": str(self.tmp) + "/",
                "LANG": "en_US.UTF-8"}

    def run(self, *args, timeout: float = 180, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(self.script), *map(str, args)], capture_output=True, text=True,
                              timeout=timeout, env=self.env(), stdin=subprocess.DEVNULL, **kwargs)

    def popen(self, *args) -> subprocess.Popen:
        return subprocess.Popen(["/bin/bash", str(self.script), *map(str, args)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=self.env(), stdin=subprocess.DEVNULL,
                                start_new_session=True)

    def leftovers(self) -> list[str]:
        names = []
        for folder in (self.runtime, self.downloads):
            if folder.is_dir():
                names += [p.name for p in folder.iterdir() if p.name.startswith((".act-stage", ".probe", ".listing"))
                          or ".part" in p.name]
        return names


@pytest.fixture
def app(tmp_path) -> App:
    root = tmp_path / "app"
    (root / "scripts" / "shared").mkdir(parents=True)
    shutil.copy2(STAGE0, root / "scripts" / "shared" / STAGE0.name)
    return App(root)


def _install_python(app: App, *, sitecustomize: str | None = None) -> None:
    _clone_tree(_base_python_tree(), app.python_home)
    site = app.python_home / "lib" / "python3.12" / "site-packages"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir()
    if sitecustomize is not None:
        (site / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")


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
#  Shape: bash 3.2, LF, the switches
# --------------------------------------------------------------------------- #
def test_stage0_runs_on_the_bash_macos_ships_and_uses_no_bash4_constructs():
    version = subprocess.run(["/bin/bash", "--version"], capture_output=True, text=True).stdout
    assert "version 3.2" in version, version.splitlines()[0]
    assert subprocess.run(["/bin/bash", "-n", str(STAGE0)]).returncode == 0
    text = STAGE0.read_text(encoding="utf-8")
    for construct in ("declare -A", "mapfile", "readarray", ",,}", "^^}", "|&", ";;&", "coproc", "${!", "&>>"):
        assert construct not in text, construct
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    import re

    for tool in (r"\blipo\b", r"\botool\b", r"\bbrew\b", r"\bxcrun\b", r"\bpython3\b(?!\.12)", r"(^|[;&|(]\s*)timeout\s"):
        assert not re.search(tool, code, re.MULTILINE), tool


# --------------------------------------------------------------------------- #
#  The states of section 8.2
# --------------------------------------------------------------------------- #
def test_healthy_interpreter_is_proved_and_used_without_asking(app):
    _install_python(app)
    out = app.root / "out.txt"
    started = time.monotonic()
    done = app.run("--assume-no", "--out-file", out)
    assert done.returncode == 0, done.stdout + done.stderr
    assert out.read_text() == str(app.python_home / "bin" / "python3.12")
    assert "Download Python" not in done.stdout
    assert time.monotonic() - started < 20
    assert not app.downloads.exists() or not any(app.downloads.iterdir())


def test_declined_consent_downloads_nothing_and_exits_2(app):
    done = app.run("--assume-no")
    assert done.returncode == 2, done.stdout
    assert "not downloaded" in done.stdout
    assert not app.python_home.exists()
    assert app.leftovers() == []


def test_no_terminal_means_no_consent(app):
    done = app.run()  # stdin is not a terminal: nothing can be answered, so nothing is downloaded
    assert done.returncode == 2
    assert "No answer can be typed here" in done.stdout


def test_verified_archive_is_unpacked_proved_and_moved_into_place_with_one_rename(app, good_archive):
    archive, size, digest = good_archive
    done = app.run("--assume-yes", "--archive-path", archive, "--qualify-size", size, "--qualify-sha256", digest)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (app.python_home / "bin" / "python3.12").is_file()
    assert app.leftovers() == [], "staging, listing and probe files are gone"
    assert archive.exists(), "an archive given with --archive-path is the caller's and is kept"
    # And the next run is the healthy fast path.
    assert app.run("--assume-no").returncode == 0


@pytest.mark.skipif(not PINNED_ARCHIVE.is_file(), reason="the pinned archive has not been downloaded here")
def test_the_pinned_archive_passes_size_hash_and_member_checks(app):
    done = app.run("--assume-yes", "--archive-path", PINNED_ARCHIVE)
    assert done.returncode == 0, done.stdout + done.stderr
    proof = subprocess.run([str(app.python_home / "bin" / "python3.12"), "-I", "-c",
                            "import tkinter, platform, sys; r = tkinter.Tk(); r.withdraw(); "
                            "print(r.tk.call('info', 'patchlevel'), r.tk.call('tk', 'windowingsystem'), "
                            "platform.machine(), '%d.%d.%d' % sys.version_info[:3]); r.destroy()"],
                           capture_output=True, text=True, timeout=60)
    assert proof.stdout.split() == ["9.0.4", "aqua", "arm64", "3.12.15"], proof.stdout + proof.stderr


@pytest.mark.parametrize("damage", ["truncated", "one-byte-changed"])
def test_a_wrong_archive_is_rejected_and_nothing_is_installed(app, good_archive, tmp_path, damage):
    archive, size, digest = good_archive
    bad = tmp_path / "bad.tar.gz"
    data = bytearray(archive.read_bytes())
    if damage == "truncated":
        data = data[: len(data) // 2]
    else:
        data[len(data) // 3] ^= 0xFF
    bad.write_bytes(bytes(data))
    done = app.run("--assume-yes", "--archive-path", bad, "--qualify-size", size, "--qualify-sha256", digest)
    assert done.returncode == 3
    assert "rejected" in done.stdout
    assert ("bytes, not" if damage == "truncated" else "SHA-256") in done.stdout
    assert not app.python_home.exists() and app.leftovers() == []


def _tar_with(tmp_path: Path, extra: tarfile.TarInfo, payload: bytes = b"") -> tuple[Path, int, str]:
    path = tmp_path / f"unsafe-{extra.name.replace('/', '_')}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        ok = tarfile.TarInfo("python/bin/python3.12")
        body = b"#!/bin/sh\n"
        ok.size, ok.mode = len(body), 0o755
        tar.addfile(ok, io.BytesIO(body))
        tar.addfile(extra, io.BytesIO(payload) if extra.isfile() else None)
    data = path.read_bytes()
    return path, len(data), hashlib.sha256(data).hexdigest()


def _member(name: str, kind=tarfile.REGTYPE, *, mode: int = 0o644, link: str = "", size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.linkname, info.size = kind, mode, link, size
    return info


UNSAFE = {
    "absolute path": (_member("/tmp/act-evil"), "absolute path"),
    "parent traversal": (_member("python/../act-evil"), "parent-directory"),
    "outside the top folder": (_member("other/act-evil"), "outside the python/ folder"),
    "link escaping the root": (_member("python/bin/evil", tarfile.SYMTYPE, link="../../../etc/passwd"),
                               "points outside"),
    "absolute link target": (_member("python/bin/evil", tarfile.SYMTYPE, link="/etc/passwd"), "points outside"),
    "set-user-ID file": (_member("python/bin/suid", mode=0o4755), "set-user-ID"),
    "set-group-ID file": (_member("python/bin/sgid", mode=0o2755), "set-user-ID or set-group-ID"),
    "character device": (_member("python/dev-null", tarfile.CHRTYPE), "not a file, folder or link"),
    "fifo": (_member("python/fifo", tarfile.FIFOTYPE), "not a file, folder or link"),
    "hard link": (_member("python/bin/hard", tarfile.LNKTYPE, link="python/bin/python3.12"), "hard link"),
    "space in a name": (_member("python/bin/a b"), "space"),
}


@pytest.mark.parametrize("case", sorted(UNSAFE))
def test_an_unsafe_member_refuses_the_whole_archive_before_anything_is_extracted(app, tmp_path, case):
    member, expected = UNSAFE[case]
    archive, size, digest = _tar_with(tmp_path, member)
    done = app.run("--assume-yes", "--archive-path", archive, "--qualify-size", size, "--qualify-sha256", digest)
    assert done.returncode == 3, done.stdout
    assert "refused and nothing was unpacked" in done.stdout and expected in done.stdout, done.stdout
    assert not app.python_home.exists()
    assert app.leftovers() == []
    assert not Path("/tmp/act-evil").exists()


def test_a_link_inside_the_folder_is_accepted(app, tmp_path):
    archive, size, digest = _tar_with(tmp_path, _member("python/bin/python3", tarfile.SYMTYPE, link="python3.12"))
    done = app.run("--assume-yes", "--archive-path", archive, "--qualify-size", size, "--qualify-sha256", digest)
    # The members pass; the fixture's python3.12 is a shell script, so the program check refuses it afterwards.
    assert "refused and nothing was unpacked" not in done.stdout
    assert "Apple Silicon" in done.stdout and done.returncode == 3
    assert not app.python_home.exists() and app.leftovers() == []


def test_leftovers_of_a_dead_run_are_removed_and_a_live_runs_are_kept(app):
    app.runtime.mkdir(parents=True)
    app.downloads.mkdir(parents=True)
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    stale_stage = app.runtime / f".act-stage-python-{dead.pid}"
    (stale_stage / "python").mkdir(parents=True)
    stale_part = app.downloads / f"archive.tar.gz.part-{dead.pid}"
    stale_part.write_bytes(b"partial")
    live = app.runtime / f".act-stage-python-{os.getpid()}"
    live.mkdir()
    done = app.run("--assume-no")
    assert done.returncode == 2
    assert not stale_stage.exists() and not stale_part.exists()
    assert live.exists(), "a staging folder whose process is alive is never touched"
    assert "interrupted earlier setup" in done.stdout


# --------------------------------------------------------------------------- #
#  The watchdog (macOS has no `timeout`)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ignores_term", [False, True], ids=["hung", "ignores-SIGTERM"])
def test_a_proof_that_hangs_is_ended_by_the_watchdog_and_reaped(app, tmp_path, ignores_term):
    pidfile = tmp_path / "probe.pid"
    _install_python(app, sitecustomize=(
        "import os, signal, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignores_term else "")
        + "time.sleep(600)\n"))
    started = time.monotonic()
    done = app.run("--assume-no", "--probe-timeout", 2)
    elapsed = time.monotonic() - started
    assert done.returncode == 2, done.stdout  # the proof failed, then the replacement was declined
    assert "did not finish within 2 seconds" in done.stdout
    assert elapsed < (2 + 2 + 6), elapsed
    assert _pid_gone(int(pidfile.read_text()), 1.0), "the watchdog reaps what it started"
    assert app.python_home.exists(), "declined: the interpreter that failed is not touched"


def test_a_failed_tk_proof_is_set_aside_never_deleted_and_replaced(app, good_archive):
    archive, size, digest = good_archive
    _install_python(app, sitecustomize="import sys\nsys.modules['tkinter'] = None\n")
    marker = app.python_home / "MARKER"
    marker.write_text("the copy that failed")
    done = app.run("--assume-yes", "--archive-path", archive, "--qualify-size", size, "--qualify-sha256", digest)
    assert done.returncode == 0, done.stdout
    assert "did not pass its check" in done.stdout
    kept = [p for p in app.runtime.iterdir() if p.name.startswith("python.unusable-")]
    assert len(kept) == 1 and (kept[0] / "MARKER").read_text() == "the copy that failed"
    assert not (app.python_home / "MARKER").exists()


def test_windows_origin_runtime_data_is_foreign_and_harmless(app):
    """MAC-029: a folder copied from Windows (python.exe layout, Windows wheels, Windows sessions) is never adopted."""
    (app.python_home).mkdir(parents=True)
    (app.python_home / "python.exe").write_bytes(b"MZ")
    (app.runtime / "python-packages").mkdir()
    (app.runtime / "python-packages" / "numpy-1.26.4-cp312-cp312-win_amd64.whl").write_bytes(b"PK")
    (app.runtime / "settings.json").write_text('{"m4b_converter": {"input_dir": "C:\\\\Users\\\\x\\\\Books"}}')
    done = app.run("--assume-no")
    assert done.returncode == 2
    assert "bin/python3.12 is missing" in done.stdout
    assert (app.python_home / "python.exe").exists(), "declined: nothing is moved or deleted"
    assert (app.runtime / "settings.json").exists()


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
def trickle_server(good_archive):
    archive, size, digest = good_archive
    _Trickle.payload = archive.read_bytes()
    _Trickle.started = threading.Event()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/python.tar.gz", size, digest
    server.shutdown()
    server.server_close()


def test_kx5_sighup_during_curl_ends_curl_and_removes_the_partial_download(app, trickle_server):
    url, size, digest = trickle_server
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
    assert not app.python_home.exists()


def test_kx5_sighup_during_the_proof_ends_the_proof(app, tmp_path):
    pidfile = tmp_path / "probe.pid"
    _install_python(app, sitecustomize=f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                                       "time.sleep(600)\n")
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


def test_a_completed_download_is_verified_then_installed(app, trickle_server):
    url, size, digest = trickle_server
    done = app.run("--assume-yes", "--qualify-url", url, "--qualify-size", size, "--qualify-sha256", digest,
                   timeout=300)
    assert done.returncode == 0, done.stdout
    assert (app.python_home / "bin" / "python3.12").is_file()
    assert not any(app.downloads.iterdir()), "the verified download is deleted once Python is proven"


def test_the_qualification_url_switch_accepts_loopback_only(app):
    done = app.run("--assume-yes", "--qualify-url", "https://example.com/python.tar.gz")
    assert done.returncode == 3 and "127.0.0.1" in done.stdout
