"""v0.8.x P1B -- macOS filesystems under the five tools' publication (plan sections 11.3 and 19 P1B).

Real volumes, made and removed by the tests themselves: an exFAT disk image and a nearly full APFS disk image, each
created in pytest's temporary folder with ``hdiutil`` and attached ``-nobrowse`` (macOS mounts a user's image only under
``/Volumes``; it is detached in the fixture's teardown, and the image file goes with the temporary folder). Then:

* exFAT, measured (P1B, macOS 27 FSKit): no hard link, no ``renamex_np(RENAME_EXCL)``, and ``rename`` replaces. A new
  output therefore cannot be published there without risking a file already at its name: it is refused with a clear
  message, the temporary is still the caller's, and nothing appears under the final name. ``O_EXCL`` creation and NFD
  names behave as on APFS.
* Disk full: a real MP3 Tool run whose output is on a full volume fails as a retryable failure; nothing is published,
  no staged or temporary file is left in the run folder, and the sources are untouched.
* A read-only output folder: publication is refused, nothing is left behind.
* Permissions: a new output gets the mode any new file of the user gets (the umask decides; ``mkstemp``'s private
  0o600 made every Converter MP3 owner-only), and a file replaced in place keeps its own permission bits.
* NFD and NFC names: on APFS the two spellings are one name, so a no-clobber publication to the other spelling of a
  taken name is refused (never a replacement); an imported NFD source is read and published under the planned name.
* Two copies of the app reserving runs in one output folder at once never get the same run folder.
* The Edge-like 8-way open-file stress: eight workers, each with an FFmpeg pipe, its temporary files and an open
  socket, under the soft limit of 256 a Finder or Terminal launch inherits, with the peak number of descriptors measured.
"""

from __future__ import annotations

import errno
import json
import os
import plistlib
import secrets
import socket
import subprocess
import sys
import textwrap
import threading
import unicodedata
from pathlib import Path

import pytest

from shared import ffmpeg_utils, output_paths

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _volume(tmp_path: Path, filesystem: str, megabytes: int):
    """A disk image of *filesystem*, attached without showing in Finder; yields its mount point, detaches after."""
    name = f"ACT{secrets.token_hex(3).upper()}"  # an exFAT label holds at most 11 characters
    image = tmp_path / f"{name}.dmg"
    subprocess.run(["/usr/bin/hdiutil", "create", "-size", f"{megabytes}m", "-fs", filesystem, "-volname", name, str(image)],
                   check=True, capture_output=True, timeout=120)
    attached = subprocess.run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-plist", str(image)], check=True,
                              capture_output=True, timeout=120)
    entities = plistlib.loads(attached.stdout)["system-entities"]
    mount = next(Path(item["mount-point"]) for item in entities if item.get("mount-point"))
    device = next(item["dev-entry"] for item in entities if item.get("mount-point"))
    try:
        yield mount
    finally:
        subprocess.run(["/usr/bin/hdiutil", "detach", device, "-force"], capture_output=True, timeout=120)


@pytest.fixture
def exfat(tmp_path):
    yield from _volume(tmp_path, "ExFAT", 64)


@pytest.fixture
def small_apfs(tmp_path):
    yield from _volume(tmp_path, "APFS", 40)


def _temporary(folder: Path, data: bytes = b"finished output") -> Path:
    path = output_paths.temporary_sibling(folder / "out.mp3")
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- #
#  exFAT
# --------------------------------------------------------------------------- #
def test_on_exfat_a_new_output_is_refused_clearly_and_nothing_takes_its_name(exfat):
    folder = exfat / "Run-1"
    folder.mkdir()
    temporary = _temporary(folder)
    destination = folder / "Book.mp3"
    with pytest.raises(output_paths.OutputPathError) as caught:
        output_paths.publish_new(temporary, destination)
    detail = caught.value.detail
    assert "neither" in detail and "risking" in detail, detail
    assert not destination.exists(), "nothing under the final name"
    assert temporary.read_bytes() == b"finished output", "the temporary is still the caller's, whole"


def test_on_exfat_an_existing_file_is_never_replaced_even_by_the_fallback(exfat):
    folder = exfat / "Run-2"
    folder.mkdir()
    destination = folder / "Book.mp3"
    destination.write_bytes(b"another writer's file")
    temporary = _temporary(folder)
    with pytest.raises(output_paths.OutputPathError):
        output_paths.publish_new(temporary, destination)
    assert destination.read_bytes() == b"another writer's file"


def test_exfat_keeps_exclusive_creation_and_finds_nfd_names_by_nfc(exfat):
    nfd = unicodedata.normalize("NFD", "Café Ünïcode.mp3")
    path = exfat / nfd
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(fd)
    with pytest.raises(FileExistsError):
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    assert (exfat / unicodedata.normalize("NFC", nfd)).exists(), "the NFC spelling finds the NFD name"


# --------------------------------------------------------------------------- #
#  APFS: no-clobber, NFD/NFC, read-only, disk full
# --------------------------------------------------------------------------- #
def test_on_apfs_the_other_unicode_spelling_of_a_taken_name_is_refused_not_replaced(tmp_path):
    taken = tmp_path / unicodedata.normalize("NFC", "Café.mp3")
    taken.write_bytes(b"first")
    temporary = _temporary(tmp_path, b"second")
    with pytest.raises(output_paths.DestinationOccupied):
        output_paths.publish_new(temporary, tmp_path / unicodedata.normalize("NFD", "Café.mp3"))
    assert taken.read_bytes() == b"first"
    assert temporary.exists()


def _mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def test_a_new_output_gets_the_mode_any_new_file_of_the_user_gets(tmp_path):
    ordinary = tmp_path / "ordinary.mp3"
    ordinary.write_bytes(b"made the ordinary way")
    temporary = output_paths.temporary_sibling(tmp_path / "Book.mp3")
    assert temporary.name.startswith(output_paths.TEMP_SIBLING_PREFIX) and temporary.suffix == ".mp3"
    temporary.write_bytes(b"\xff\xfb an output")
    output_paths.publish_new(temporary, tmp_path / "Book.mp3")
    assert _mode(tmp_path / "Book.mp3") == _mode(ordinary), "the umask decides, as for any new file"
    assert _mode(tmp_path / "Book.mp3") & 0o044, "readable beyond its owner under the usual umask"


def test_a_file_replaced_in_place_keeps_its_own_permission_bits(tmp_path):
    original = tmp_path / "cover.jpg"
    original.write_bytes(b"the original")
    original.chmod(0o640)
    temporary = output_paths.temporary_sibling(original)
    temporary.write_bytes(b"the replacement")
    output_paths.atomic_replace(temporary, original)
    assert original.read_bytes() == b"the replacement" and _mode(original) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["cover.jpg"]


def test_a_read_only_output_folder_refuses_publication_and_keeps_nothing(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    temporary = _temporary(staging)
    folder.chmod(0o555)
    try:
        with pytest.raises(output_paths.OutputPathError):
            output_paths.publish_new(temporary, folder / "Book.mp3")
        assert list(folder.iterdir()) == []
    finally:
        folder.chmod(0o755)


def test_a_real_mp3_run_on_a_full_volume_fails_retryably_and_publishes_nothing(small_apfs, tmp_path):
    import test_ffmpeg_cancel as cx
    from mp3 import mp3_processing as proc
    from shared.job_control import JobController

    if not ffmpeg_utils.ffmpeg_path():
        pytest.fail("the adopted FFmpeg is not pinned in this checkout; set the app up before P1B's filesystem tests")
    sources = tmp_path / "Sources"
    made = cx._mp3_plan(sources, _reserve_on(small_apfs), seconds=20.0)
    before = cx.hashes(sources)
    filler = small_apfs / "filler.bin"
    with open(filler, "wb") as sink:  # the volume, full to within a few blocks
        try:
            while True:
                sink.write(b"\0" * (1 << 20))
        except OSError as exc:
            assert exc.errno == errno.ENOSPC
    controller = JobController("p1b-full")
    controller.start()
    result = proc.write_id3_run(made, checkpoint=controller.checkpoint, cancel_check=controller.cancel_check)
    book = made.books[0]
    published = [p for p in book.published_dir.rglob("*") if p.is_file()] if book.published_dir.exists() else []
    assert published == [], "nothing was published"
    report = result.books[0]
    assert not report.succeeded and report.published == ()
    failures = report.result.failures.records
    assert failures and all(record.retryable for record in failures), failures
    run = book.published_dir.parent
    left = [p.name for p in run.rglob("*") if p.is_file() and p.name.startswith(output_paths.TEMP_SIBLING_PREFIX)]
    assert left == [], f"temporary files left in the run folder: {left}"
    assert cx.hashes(sources) == before


def _reserve_on(base: Path):
    counter = {"n": 0}

    def make(tool_key="mp3_tool", **_kw):
        counter["n"] += 1
        directory = base / "Outputs" / f"MP3-Tool-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(tool_key=tool_key, base_directory=base / "Outputs",
                                           tool_directory=base / "Outputs", run_directory=directory,
                                           run_number=counter["n"])
    return make


# --------------------------------------------------------------------------- #
#  Two copies of the app
# --------------------------------------------------------------------------- #
def test_two_app_copies_reserving_runs_at_once_never_share_a_run_folder(tmp_path):
    base = tmp_path / "Outputs"
    base.mkdir()
    code = textwrap.dedent(f"""
        import json, sys, time
        sys.path.insert(0, {str(SCRIPTS)!r})
        from pathlib import Path
        from shared import output_paths
        start = float(sys.argv[1])
        while time.time() < start:
            pass
        got = [output_paths.reserve_run_directory("mp3_tool", base=Path({str(base)!r})).run_number for _ in range(20)]
        print(json.dumps(got))
    """)
    start = f"{__import__('time').time() + 2.0}"
    copies = [subprocess.Popen([sys.executable, "-c", code, start], stdout=subprocess.PIPE, text=True) for _ in range(2)]
    numbers = []
    for copy in copies:
        out, _ = copy.communicate(timeout=120)
        assert copy.returncode == 0
        numbers += json.loads(out)
    assert len(numbers) == 40 and len(set(numbers)) == 40, "every reservation is its own folder"
    assert sorted(numbers) == list(range(1, 41))


# --------------------------------------------------------------------------- #
#  RLIMIT_NOFILE: the Edge-like 8-way stress under the inherited 256
# --------------------------------------------------------------------------- #
def test_eight_workers_with_ffmpeg_pipes_files_and_sockets_fit_under_256_and_the_peak_is_measured(tmp_path):
    if not ffmpeg_utils.ffmpeg_path():
        pytest.fail("the adopted FFmpeg is not pinned in this checkout; set the app up before P1B's filesystem tests")
    probe = textwrap.dedent(f"""
        import json, os, resource, socket, sys, tempfile, threading
        sys.path.insert(0, {str(SCRIPTS)!r})
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
        from shared import ffmpeg_utils
        from tts import ffmpeg_watch
        ffmpeg = ffmpeg_utils.ffmpeg_path()
        peak = [len(os.listdir("/dev/fd"))]
        errors = []
        lock = threading.Lock()
        barrier = threading.Barrier(8)
        def worker(index):
            try:
                server = socket.socket()                      # an Edge worker holds an HTTPS connection
                scratch = [tempfile.TemporaryFile() for _ in range(3)]   # its chunk and staging files
                out = os.path.join({str(tmp_path)!r}, f"w{{index}}.mp3")
                barrier.wait()
                child = ffmpeg_watch.Supervised([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
                                                 "-i", "sine=d=2", "-c:a", "libmp3lame", "-f", "mp3", "pipe:1"],
                                                stdin=None, stdout=-1, stderr=-1)
                with lock:
                    peak.append(len(os.listdir("/dev/fd")))
                data = b"".join(child.blocks())
                child.finish(60)
                child.abandon()
                with open(out, "wb") as sink:
                    sink.write(data)
                with lock:
                    peak.append(len(os.listdir("/dev/fd")))
                for item in scratch:
                    item.close()
                server.close()
            except OSError as exc:
                errors.append(f"{{type(exc).__name__}}: {{exc}}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(120)
        print(json.dumps({{"soft": resource.getrlimit(resource.RLIMIT_NOFILE)[0], "peak": max(peak), "errors": errors}}))
    """)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-2000:]
    facts = json.loads(done.stdout.strip().splitlines()[-1])
    print("P1B-RLIMIT-MEASUREMENT", json.dumps(facts))
    assert facts["soft"] == 256
    assert facts["errors"] == [], "no EMFILE (or any OSError) at 8-way under 256"
    assert all((tmp_path / f"w{i}.mp3").stat().st_size > 0 for i in range(8))
    assert facts["peak"] < 256
