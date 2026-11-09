"""ACT72-009: the TTS routes' temporary files are owned, and only what is provably this tool's and finished is removed (v0.7.2).

Until v0.7.2 a conversion's ``epub2tts_*``, ``tts_direct_*`` and ``tts_local_*`` folders, pydub's temporaries and the local
engines' encode WAV lay loose in the system temp folder. A killed program left them there, and nothing could tell whose they
were. :mod:`shared.work_area` makes each conversion's folders entries of one process's workspace, listed in a manifest that names
the owner by process id and creation time, and :func:`shared.work_area.recover` removes a workspace only when that manifest is
intact and its owner provably gone.

Every fixture lives under ``tmp_path``, which each test makes the temp folder. Killed and live owners are real child processes
started here, stopped only by their own handles, and reaped before the test ends; another program holding a file is one too.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from shared.cancellation import ConversionCancelled
from tts import epub2tts_gui as panel_module  # module top: test_epub_retirement leaves fresh copies in sys.modules
from tts import ffmpeg_watch
from shared import work_area
from tts.epub2tts_edge import runner

WINDOWS = os.name == "nt"
windows_only = pytest.mark.skipif(not WINDOWS, reason="recovering another process's files is proved on Windows only")
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
WAIT = 60.0
NO_WINDOW = 0x08000000 if WINDOWS else 0

#: Each child says who it really is at its barrier: the venv's ``python.exe`` is a launcher, and the interpreter that owns
#: the work is its child, with another process id (the application runs the same way).
_IDENTIFY = r"""
import json, os, sys
from pathlib import Path
def identify(barrier, scripts):
    sys.path.insert(0, scripts)
    from shared import work_area
    staged = Path(barrier + ".new")
    staged.write_text(json.dumps({"pid": os.getpid(), "created": work_area._own_creation_time()}), encoding="utf-8")
    os.replace(staged, barrier)
"""

#: A child that converts into the work area through the production hooks, holds its temporaries and waits to be killed.
CONVERTING_CHILD = _IDENTIFY + r"""
import tempfile, time
temp, barrier, scripts = sys.argv[1:4]
tempfile.tempdir = temp
sys.path.insert(0, scripts)
from tts import ffmpeg_watch
from shared import work_area
with ffmpeg_watch.controlled(None):
    with work_area.conversion_folder("edge") as folder:
        (folder / "part0.flac").write_bytes(b"F" * 4096)
        (folder / "nested").mkdir()
        (folder / "nested" / "clip.mp3").write_bytes(b"M" * 512)
        handle = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)
        handle.write(b"W" * 8192)
        handle.flush()
        identify(barrier, scripts)
        while True:
            time.sleep(60)
"""

#: Another program holding one file open without delete sharing (Python's own open), as an orphaned encoder would.
HOLDING_CHILD = _IDENTIFY + r"""
import time
path, barrier, scripts = sys.argv[1:4]
stream = open(path, "ab")
identify(barrier, scripts)
while True:
    time.sleep(60)
"""


# --------------------------------------------------------------------------- fixtures and helpers


@pytest.fixture
def temp(tmp_path, monkeypatch) -> Path:
    """This test's temp folder: everything the work area does happens here."""
    folder = tmp_path / "temp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


class Child:
    """A child started here: the launcher's ``Popen`` and the identity of the interpreter it runs."""

    def __init__(self, popen: subprocess.Popen) -> None:
        self.popen = popen
        self.owner: dict | None = None


def _terminate_exactly(owner: dict) -> None:
    """Stop the one process with this id **and** creation time, if it still runs; never another that reused the id."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    handle = kernel.OpenProcess(0x0001 | 0x1000, False, owner["pid"])
    if not handle:
        return
    try:
        if work_area._creation_time(handle) == owner["created"]:
            kernel.TerminateProcess(wintypes.HANDLE(handle), 1)
    finally:
        work_area._close(handle)


def stop(child: Child) -> None:
    """Stop it by its own handle (the launcher's job ends its interpreter too) and prove the interpreter is gone."""
    if child.popen.poll() is None:
        child.popen.kill()
    child.popen.wait(30)
    if child.owner is None or not WINDOWS:
        return
    deadline = time.monotonic() + 10
    while work_area.owner_state(child.owner) == work_area.ALIVE:
        if time.monotonic() > deadline:
            _terminate_exactly(child.owner)
            break
        time.sleep(0.05)
    deadline = time.monotonic() + 10
    while work_area.owner_state(child.owner) == work_area.ALIVE and time.monotonic() < deadline:
        time.sleep(0.05)
    assert work_area.owner_state(child.owner) != work_area.ALIVE, "no process of this test outlives it"


@pytest.fixture
def children():
    """Child processes this test starts. Each is stopped by its own handle and reaped, however the test ends."""
    started: list[Child] = []

    def start(code: str, *args: str) -> Child:
        child = Child(subprocess.Popen([sys.executable, "-c", code, *args], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=NO_WINDOW))
        started.append(child)
        return child

    yield start
    for child in started:
        stop(child)


def wait_ready(child: Child, barrier: Path) -> None:
    deadline = time.monotonic() + WAIT
    while not barrier.exists():
        assert child.popen.poll() is None, f"the child ended early with {child.popen.returncode}"
        assert time.monotonic() < deadline, "the child never reached its barrier"
        time.sleep(0.05)
    child.owner = json.loads(barrier.read_text(encoding="utf-8"))


def converting_child(children, temp: Path, name: str = "child") -> Child:
    barrier = temp.parent / f"barrier-{name}"
    child = children(CONVERTING_CHILD, str(temp), str(barrier), str(SCRIPTS))
    wait_ready(child, barrier)
    return child


def holding_child(children, path: Path, where: Path, name: str = "holder") -> Child:
    """Another program holding *path* open; its barrier is written in *where*, outside the temp folder."""
    barrier = where / f"barrier-{name}"
    child = children(HOLDING_CHILD, str(path), str(barrier), str(SCRIPTS))
    wait_ready(child, barrier)
    return child


def workspace_of(temp: Path, child: Child) -> Path:
    for folder in (temp / work_area.ROOT_NAME).iterdir():
        manifest = folder / work_area.MANIFEST_NAME
        if manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8"))["owner"] == child.owner:
            return folder
    raise AssertionError(f"no workspace of {child.owner}")


def kill(child: Child) -> None:
    """An abrupt end: TerminateProcess, no ``finally`` block of the child runs."""
    stop(child)


def tree(root: Path) -> dict[str, str]:
    """Every file and folder below *root*, links reported as links and never followed, files by content."""
    found: dict[str, str] = {}
    for folder, subfolders, names in os.walk(root, followlinks=False):
        for name in list(subfolders):
            path = Path(folder) / name
            if work_area._is_real_folder(path):
                found[path.relative_to(root).as_posix() + "/"] = "folder"
            else:
                found[path.relative_to(root).as_posix() + "/"] = "link"
                subfolders.remove(name)
        for name in names:
            path = Path(folder) / name
            found[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def own_creation() -> int:
    return work_area._own_creation_time()


#: This process's id with a creation time that is not its own: the owner that wrote it has ended and its id was reused.
REUSED_ID_OWNER = {"pid": os.getpid(), "created": 1}


def fabricate(temp: Path, *, owner=None, entries=None, token=None, data=None, raw: bytes | None = None,
              files: bool = True) -> Path:
    """A workspace as a process of this tool leaves it, with *owner* (by default one whose id was reused)."""
    token = token or secrets.token_hex(8)
    folder = temp / work_area.ROOT_NAME / token
    folder.mkdir(parents=True)
    entries = {"1": {"kind": "edge", "retention": "disposable", "state": "active"}} if entries is None else entries
    manifest = {"schema": work_area.SCHEMA, "version": work_area.VERSION, "token": token, "workspace": str(folder),
                "owner": REUSED_ID_OWNER if owner is None else owner, "entries": entries}
    if data is not None:
        manifest.update(data)
    if raw is not None:
        (folder / work_area.MANIFEST_NAME).write_bytes(raw)
    elif data != {"_no_manifest": True}:
        (folder / work_area.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    if files:
        for name in entries:
            if not isinstance(name, str) or not work_area._ENTRY_NAME.fullmatch(name):
                continue
            entry = folder / name
            entry.mkdir()
            (entry / "part0.flac").write_bytes(b"F" * 100)
            (entry / "deep").mkdir()
            (entry / "deep" / "assembly.wav").write_bytes(b"W" * 100)
    return folder


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junction(link: Path, target: Path) -> None:
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    assert made.returncode == 0 and os.path.lexists(link), made.stdout + made.stderr


def victim(tmp_path: Path) -> Path:
    """A folder of the person's, outside the temp folder, that nothing here may ever touch."""
    folder = tmp_path / "Person's books"
    folder.mkdir()
    (folder / "chapter 1.txt").write_text("my own words", encoding="utf-8")
    (folder / "Published.mp3").write_bytes(b"ID3" + b"\x00" * 200)
    return folder


def assert_no_workspace(temp: Path) -> None:
    root = temp / work_area.ROOT_NAME
    assert not root.exists() or not any(root.iterdir()), f"left in the work area: {sorted(tree(root))}"


def local_item(tmp_path: Path, name: str = "book.txt") -> dict:
    source = tmp_path / "in" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Title: Book\nAuthor: Someone\n\n# One\n\nA sentence to narrate.\n", encoding="utf-8")
    return {"source": source, "destination": tmp_path / "out" / f"{source.stem}-Heart.mp3"}


# --------------------------------------------------------------------------- A. what a conversion makes is listed and owned


def test_a_folder_is_listed_with_its_owner_before_it_exists(temp, monkeypatch):
    seen = {}
    real_mkdir = work_area.os.mkdir

    def mkdir(path, *args, **kwargs):
        path = Path(path)
        if path.parent.parent.name == work_area.ROOT_NAME:  # an entry, not the workspace
            seen["listed"] = json.loads((path.parent / work_area.MANIFEST_NAME).read_text(encoding="utf-8"))["entries"]
            seen["exists"] = path.exists()
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(work_area.os, "mkdir", mkdir)
    folder = work_area.new_folder("edge")
    try:
        assert seen["listed"] == {folder.name: {"kind": "edge", "retention": "disposable", "state": "active"}}
        assert seen["exists"] is False, "the manifest names the entry before the folder is made"
        manifest = json.loads((folder.path.parent / work_area.MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["token"] == folder.path.parent.name and len(manifest["token"]) == 16
        assert Path(manifest["workspace"]) == folder.path.parent
        if WINDOWS:
            assert manifest["owner"] == {"pid": os.getpid(), "created": own_creation()}
            assert work_area.owner_state(manifest["owner"]) == work_area.ALIVE
    finally:
        assert folder.close()
    assert_no_workspace(temp)


def test_workspace_names_are_unpredictable_and_never_reused(temp):
    tokens = set()
    for _ in range(20):
        folder = work_area.new_folder("local")
        tokens.add(folder.path.parent.name)
        folder.close()
    assert len(tokens) == 20 and all(len(token) == 16 for token in tokens)


def test_every_temporary_of_a_local_engine_conversion_lies_in_a_listed_entry(temp, tmp_path, monkeypatch):
    """The real panel route, the real Kokoro encode WAV and pydub's own temporaries, caught at the moment of the encode."""
    from tts import kokoro_synth
    import numpy as np
    import pydub.audio_segment

    assert ffmpeg_watch.installed()
    item = local_item(tmp_path)
    source_hash = sha(item["source"])
    published_before = tmp_path / "out" / "earlier-Heart.mp3"
    published_before.parent.mkdir(parents=True)
    published_before.write_bytes(b"ID3earlier")
    during = {}

    class Encoder:
        @classmethod
        def from_wav(cls, path):
            return cls()

        def export(self, out_f, **kwargs):
            temporary = pydub.audio_segment.NamedTemporaryFile(mode="wb", delete=False)  # pydub's own first step
            temporary.write(b"W" * 64)
            temporary.close()
            during["tree"] = tree(temp)
            during["manifests"] = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
                                   for p in (temp / work_area.ROOT_NAME).glob("*/" + work_area.MANIFEST_NAME)}
            os.unlink(temporary.name)  # pydub removes them itself when nothing fails
            Path(out_f).write_bytes(b"ID3" + b"\x00" * 100)

    def kokoro_file_to_mp3(text_path, output_path, **kwargs):
        kokoro_synth._export_mp3(np.full(2400, 0.1, dtype="float32"), 24000, output_path)

    monkeypatch.setattr(kokoro_synth, "AudioSegment", Encoder)
    monkeypatch.setattr(kokoro_synth, "kokoro_file_to_mp3", kokoro_file_to_mp3)
    params = {"voice_id": "af_heart", "kokoro_speed": 1.0, "end_pause": 0, "paragraph_pause": 0, "bitrate": "192k",
              "overwrite": False}
    panel_module.convert_with_kokoro(item, params, None, lambda line: None, lambda: False)

    files = [path for path, kind in during["tree"].items() if not path.endswith("/")]
    assert any(path.endswith(".wav") for path in files), "the engine's encode WAV was there"
    assert len(files) >= 3, files  # the encode WAV, pydub's temporary and the manifest
    (token, manifest), = during["manifests"].items()
    kinds = {name: facts["kind"] for name, facts in manifest["entries"].items()}
    assert sorted(kinds.values()) == ["local", "pydub"]
    for path in files:
        parts = path.split("/")
        assert parts[0] == work_area.ROOT_NAME and parts[1] == token, f"{path} is loose in the temp folder"
        assert parts[2] == work_area.MANIFEST_NAME or parts[2] in manifest["entries"], f"{path} is in no listed entry"
    assert_no_workspace(temp)
    assert item["destination"].is_file() and sha(item["source"]) == source_hash
    assert published_before.read_bytes() == b"ID3earlier"


# --------------------------------------------------------------------------- B. completion, Cancel and failure leave nothing


def _local_conversion_in_thread(tmp_path, synthesize, cancel_check):
    item = local_item(tmp_path)
    outcome = {}

    def run():
        try:
            with ffmpeg_watch.controlled(cancel_check):
                panel_module._convert_with_local_engine(item, {"overwrite": False}, lambda line: None, synthesize,
                                                        cancel_check)
            outcome["result"] = "done"
        except BaseException as exc:  # noqa: BLE001 - the assertion reads it
            outcome["result"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return item, outcome, thread


def test_cancel_while_temporaries_are_open_stops_promptly_and_leaves_nothing(temp, tmp_path):
    inside, cancelled = threading.Event(), threading.Event()

    def synthesize(text_path, output):
        work = work_area.current_folder()
        (work / "chunk-0001.wav").write_bytes(b"C" * 1024)
        held = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)  # left open, as a failed export leaves it
        held.write(b"W" * 1024)
        Path(output).write_bytes(b"partial")
        inside.set()
        while not cancelled.is_set():
            time.sleep(0.01)
        raise ConversionCancelled("Conversion cancelled by user.")

    item, outcome, thread = _local_conversion_in_thread(tmp_path, synthesize, cancelled.is_set)
    assert inside.wait(WAIT)
    assert len(list((temp / work_area.ROOT_NAME).glob("*/*/*"))) >= 3, "the conversion's files were in its entries"
    source_hash = sha(item["source"])
    started = time.monotonic()
    cancelled.set()
    thread.join(10)
    assert not thread.is_alive() and time.monotonic() - started < 5, "Cancel ended the conversion and its cleanup promptly"
    assert isinstance(outcome["result"], ConversionCancelled)
    assert not item["destination"].exists(), "nothing of a cancelled conversion is published"
    assert sha(item["source"]) == source_hash
    assert_no_workspace(temp)


def test_a_conversion_cancelled_before_it_starts_makes_no_workspace(temp, tmp_path):
    item = local_item(tmp_path)
    with pytest.raises(ConversionCancelled):
        runner.run_conversion_job(str(item["source"]), output_dir=str(tmp_path / "out"), audio_format="mp3",
                                  cancel_check=lambda: True)
    assert not (temp / work_area.ROOT_NAME).exists()


@pytest.mark.parametrize("stage", ["synthesis", "encoding"])
def test_a_failure_during_synthesis_or_encoding_leaves_nothing(stage, temp, tmp_path):
    def synthesize(text_path, output):
        (work_area.current_folder() / "chunk-0001.wav").write_bytes(b"C" * 1024)
        if stage == "encoding":
            held = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)
            held.write(b"W" * 1024)
            Path(output).write_bytes(b"half an mp3")
        raise RuntimeError(f"simulated {stage} failure")

    item, outcome, thread = _local_conversion_in_thread(tmp_path, synthesize, lambda: False)
    thread.join(WAIT)
    assert isinstance(outcome["result"], RuntimeError)
    assert not item["destination"].exists()
    assert_no_workspace(temp)


@windows_only
def test_a_folder_another_program_holds_is_left_finished_and_removed_later(temp, children):
    folder = work_area.new_folder("edge")
    held = folder.path / "assembly.wav"
    held.write_bytes(b"W" * 100)
    holder = holding_child(children, held, temp.parent)
    started = time.monotonic()
    assert folder.close() is False, "a file another program holds open is never forced"
    assert time.monotonic() - started < 3, "the attempt is bounded"
    manifest = json.loads((folder.path.parent / work_area.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["entries"][folder.name]["state"] == "finished"
    assert held.read_bytes() == b"W" * 100
    kill(holder)
    report = work_area.recover()
    assert report.removed == [str(folder.path)] and not report.left
    assert_no_workspace(temp)


# --------------------------------------------------------------------------- C. a killed program, a live one, a restart


@windows_only
def test_a_killed_conversion_is_removed_at_the_next_start_and_nothing_else_is(temp, tmp_path, children):
    legacy = temp / "epub2tts_k3x9q1ab"
    legacy.mkdir()
    (legacy / "part0.flac").write_bytes(b"old")
    for name in ("tts_direct_abc", "tts_local_def"):
        (temp / name).mkdir()
    (temp / "tmpq1w2e3r4").write_bytes(b"someone else's")
    books = victim(tmp_path)
    loose_before, books_before = {k: v for k, v in tree(temp).items() if not k.startswith(work_area.ROOT_NAME)}, tree(books)

    child = converting_child(children, temp)
    workspace = workspace_of(temp, child)
    assert len(list(workspace.glob("*/*"))) >= 3, "the child's clips, nested folder and pydub temporary"
    kill(child)
    assert workspace.exists(), "a killed program removes nothing itself"

    report = work_area.recover()
    assert sorted(Path(p).name for p in report.removed) == ["1", "2"], report
    assert not report.left and not report.deferred and report.running == 0
    assert not workspace.exists()
    assert {k: v for k, v in tree(temp).items() if not k.startswith(work_area.ROOT_NAME)} == loose_before
    assert tree(books) == books_before

    again = work_area.recover()
    assert again.as_dict() == {"removed": [], "left": [], "running": 0, "deferred": False}, "recovery is idempotent"
    assert {k: v for k, v in tree(temp).items() if not k.startswith(work_area.ROOT_NAME)} == loose_before


@windows_only
def test_a_running_owner_is_never_disturbed(temp, children):
    live = converting_child(children, temp, "live")
    killed = converting_child(children, temp, "killed")
    live_space, killed_space = workspace_of(temp, live), workspace_of(temp, killed)
    kill(killed)
    before = tree(live_space)

    report = work_area.recover()
    assert report.running == 1 and not report.left
    assert tree(live_space) == before, "not a byte of a running owner's work changes"
    assert not killed_space.exists()

    kill(live)
    report = work_area.recover()
    assert len(report.removed) == 2 and not live_space.exists()


@windows_only
def test_a_reused_process_id_is_not_the_owner(temp, children):
    child = converting_child(children, temp)
    workspace = workspace_of(temp, child)
    manifest = workspace / work_area.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    kill(child)
    # The child's id now belongs to a running process (this one): only its creation time can tell them apart.
    data["owner"]["pid"] = os.getpid()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert work_area.owner_state(data["owner"]) == work_area.GONE
    assert work_area.owner_state({"pid": os.getpid(), "created": own_creation()}) == work_area.ALIVE

    report = work_area.recover()
    assert len(report.removed) == 2 and not workspace.exists()


@windows_only
def test_owner_identity_states(children, temp):
    assert work_area.owner_state({"pid": 0x7FFFFFFC, "created": 1}) == work_area.GONE  # no such process
    assert work_area.owner_state({"pid": os.getpid(), "created": own_creation()}) == work_area.ALIVE
    assert work_area.owner_state({"pid": os.getpid(), "created": own_creation() + 1}) == work_area.GONE
    for broken in (None, {}, {"pid": True, "created": 5}, {"pid": 5, "created": "5"}, {"pid": -1, "created": 5},
                   {"pid": 5, "created": 0}):
        assert work_area.owner_state(broken) == work_area.UNKNOWN


@windows_only
def test_an_owner_that_cannot_be_checked_keeps_everything(temp):
    workspace = fabricate(temp)
    before = tree(workspace)
    report = work_area.recover(is_owner_gone=lambda owner: work_area.UNKNOWN)
    assert report.left == [(str(workspace), "its owner cannot be checked")]
    assert tree(workspace) == before


# --------------------------------------------------------------------------- D. a manifest that proves nothing proves nothing

DAMAGE = {
    "truncated": {"raw": b'{"schema": "act-tts-work", "version": 1, "tok'},
    "not-json": {"raw": b"\x00\x01binary"},
    "empty": {"raw": b""},
    "wrong-schema": {"data": {"schema": "someone-else"}},
    "wrong-version": {"data": {"version": 2}},
    "another-token": {"data": {"token": "0" * 16}},
    "another-place": {"data": {"workspace": "C:\\Somewhere\\else"}},
    "no-owner": {"data": {"owner": None}},
    "owner-without-creation-time": {"owner": {"pid": os.getpid()}},
    "entries-not-a-map": {"data": {"entries": ["1"]}},
    "traversal-entry": {"entries": {"..": {"kind": "edge", "retention": "disposable", "state": "active"}}},
    "nested-traversal-entry": {"entries": {"1\\..\\..": {"kind": "edge", "retention": "disposable", "state": "active"}}},
    "absolute-entry": {"entries": {"C:\\Users": {"kind": "edge", "retention": "disposable", "state": "active"}}},
    "unknown-state": {"entries": {"1": {"kind": "edge", "retention": "disposable", "state": "paused"}}},
    "too-large": {"raw": b"{" + b" " * (work_area.MANIFEST_MAX_BYTES + 10) + b"}"},
}


@windows_only
@pytest.mark.parametrize("damage", sorted(DAMAGE))
def test_a_damaged_or_foreign_manifest_leaves_the_workspace_exactly_as_it_is(damage, temp, tmp_path):
    books = victim(tmp_path)
    books_before = tree(books)
    workspace = fabricate(temp, **DAMAGE[damage])
    if damage.endswith("traversal-entry") or damage == "absolute-entry":
        (workspace / "1").mkdir()
        (workspace / "1" / "part0.flac").write_bytes(b"F")
    old = time.time() - 3600
    os.utime(workspace, (old, old))
    before = tree(temp)
    report = work_area.recover()
    assert not report.removed
    assert [path for path, _why in report.left] == [str(workspace)], report
    assert tree(temp) == before and tree(books) == books_before


@windows_only
def test_the_same_workspace_with_an_intact_manifest_is_removed(temp):
    """The control for the damaged cases: their fixture is removed whenever its manifest proves it."""
    workspace = fabricate(temp)
    report = work_area.recover()
    assert report.removed == [str(workspace / "1")] and not workspace.exists()


@windows_only
def test_a_workspace_without_a_manifest_is_left_and_explained_once_it_has_settled(temp):
    workspace = fabricate(temp, data={"_no_manifest": True})
    report = work_area.recover()
    assert report.running == 1 and not report.left, "a young one is a process making or retiring it"
    old = time.time() - work_area.SETTLING_SECONDS - 60
    os.utime(workspace, (old, old))
    before = tree(workspace)
    report = work_area.recover()
    assert report.left == [(str(workspace), "it has no manifest, so its owner is unknown")]
    assert tree(workspace) == before


@windows_only
def test_a_dead_owners_half_written_manifest_goes_with_it_but_one_alone_proves_nothing(temp):
    workspace = fabricate(temp)
    (workspace / f"{work_area.MANIFEST_NAME}.0a1b2c3d.new").write_bytes(b'{"schema": "act-tts')
    assert work_area.recover().removed and not workspace.exists()

    alone = fabricate(temp, files=False, data={"_no_manifest": True})
    (alone / f"{work_area.MANIFEST_NAME}.0a1b2c3d.new").write_bytes(b'{"schema": "act-tts')
    old = time.time() - 3600
    os.utime(alone, (old, old))
    report = work_area.recover()
    assert report.left == [(str(alone), "it has no manifest, so its owner is unknown")] and alone.exists()


@windows_only
def test_an_entry_kept_for_resuming_is_never_removed(temp):
    workspace = fabricate(temp, entries={"1": {"kind": "edge", "retention": "disposable", "state": "active"},
                                         "2": {"kind": "edge", "retention": "resumable", "state": "finished"}})
    report = work_area.recover()
    assert report.removed == [str(workspace / "1")]
    assert report.left == [(str(workspace / "2"), "kept as 'resumable', never removed by recovery")]
    assert (workspace / "2" / "part0.flac").exists() and (workspace / work_area.MANIFEST_NAME).exists()


# --------------------------------------------------------------------------- E. names this tool does not make


@windows_only
def test_names_this_tool_does_not_make_are_never_touched(temp):
    root = temp / work_area.ROOT_NAME
    root.mkdir()
    foreign = {"notours": "folder", "0123456789abcdeg": "folder", "0123456789ABCDEF": "folder",
               "0123456789abcdef0": "folder", "fedcba9876543210": "file"}
    for name, kind in foreign.items():
        if kind == "folder":
            (root / name).mkdir()
            (root / name / "data.bin").write_bytes(b"theirs")
        else:
            (root / name).write_bytes(b"theirs")
    workspace = fabricate(temp)
    (workspace / "extra").mkdir()
    (workspace / "extra" / "theirs.txt").write_text("not listed", encoding="utf-8")
    report = work_area.recover()
    left = dict(report.left)
    for name in ("notours", "0123456789abcdeg", "0123456789ABCDEF", "0123456789abcdef0"):
        assert left[str(root / name)] == "not a name this tool makes"
        assert (root / name / "data.bin").read_bytes() == b"theirs"
    assert (root / "fedcba9876543210").read_bytes() == b"theirs"
    assert report.removed == [str(workspace / "1")], "its listed entry goes"
    assert left[str(workspace / "extra")] == "not listed in its workspace's manifest"
    assert (workspace / "extra" / "theirs.txt").exists() and (workspace / work_area.MANIFEST_NAME).exists()


# --------------------------------------------------------------------------- F. links, hard links and swaps


def _count_passes(monkeypatch) -> list:
    passes = []
    real = work_area._remove_entry_win

    def remove_entry_win(*args):
        passes.append(args[2])
        return real(*args)

    monkeypatch.setattr(work_area, "_remove_entry_win", remove_entry_win)
    return passes


@windows_only
def test_a_junction_inside_an_entry_is_neither_followed_nor_removed(temp, tmp_path, monkeypatch):
    books = victim(tmp_path)
    before = tree(books)
    workspace = fabricate(temp)
    junction(workspace / "1" / "deep" / "into-books", books)
    passes = _count_passes(monkeypatch)
    report = work_area.recover()
    assert tree(books) == before, "nothing behind the link was touched"
    assert (str(workspace / "1" / "deep" / "into-books"), "a link, which is never followed or removed") in report.left
    assert os.path.lexists(workspace / "1" / "deep" / "into-books")
    assert not (workspace / "1" / "part0.flac").exists(), "what is this tool's around it still goes"
    assert passes == ["1"], "no wait changes a link, so it is not waited for"


@windows_only
def test_a_hard_link_loses_only_this_folders_name(temp, tmp_path):
    books = victim(tmp_path)
    before = tree(books)
    workspace = fabricate(temp)
    os.link(books / "Published.mp3", workspace / "1" / "linked.mp3")
    report = work_area.recover()
    assert report.removed == [str(workspace / "1")] and not workspace.exists()
    assert tree(books) == before and os.stat(books / "Published.mp3").st_nlink == 1


@windows_only
def test_a_workspace_or_root_that_is_a_junction_is_refused(temp, tmp_path):
    books = victim(tmp_path)
    before = tree(books)
    root = temp / work_area.ROOT_NAME
    root.mkdir()
    junction(root / "0123456789abcdef", books)
    report = work_area.recover()
    assert report.left == [(str(root / "0123456789abcdef"), "a link or not a folder")]
    os.rmdir(root / "0123456789abcdef")  # the junction itself, as the person would
    os.rmdir(root)
    junction(root, books)
    report = work_area.recover()
    assert report.left == [(str(root), "a link or not a folder")]
    with pytest.raises(work_area.WorkAreaError):
        work_area.new_folder("edge")
    assert tree(books) == before


@windows_only
def test_a_folder_swapped_for_a_junction_while_it_is_being_removed_is_left(temp, tmp_path, monkeypatch):
    """The swap lands at the worst instant: after the folder was listed, before it is opened."""
    books = victim(tmp_path)
    before = tree(books)
    workspace = fabricate(temp)
    target = workspace / "1" / "deep"
    real_open = work_area._open
    swapped = []

    def open_(path, *args, **kwargs):
        if Path(path) == target and not swapped:
            os.rename(target, workspace / "1" / "deep-moved")
            junction(target, books)
            swapped.append(True)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(work_area, "_open", open_)
    report = work_area.recover()
    assert swapped and tree(books) == before, "the swap redirected nothing"
    assert (str(target), "a link, which is never followed or removed") in report.left
    again = work_area.recover()  # the real folder, moved aside inside the entry after it was listed, goes next time
    assert not (workspace / "1" / "deep-moved").exists() and os.path.lexists(target)
    assert (str(target), "a link, which is never followed or removed") in again.left and tree(books) == before


@windows_only
def test_folders_being_emptied_cannot_be_renamed_or_replaced(temp, monkeypatch):
    """A swap needs a rename. Tried at the two instants that matter: when only the pins hold the workspace and ROOT (the
    entry is about to be opened), and while the entry itself is being emptied."""
    workspace = fabricate(temp)
    entry = workspace / "1"
    real_open, real_delete = work_area._open, work_area._delete_by_handle
    attempts = {}

    def rename(name, path):
        try:
            os.rename(path, path.with_name(path.name + "-swapped"))
            attempts[name] = "renamed"
        except PermissionError:
            attempts[name] = "refused"

    def open_(path, access, share, *, follow=False):
        if Path(path) == entry and "workspace" not in attempts:
            rename("workspace", workspace)
            rename("root", workspace.parent)
        return real_open(path, access, share, follow=follow)

    def delete(handle):
        if "entry" not in attempts:
            rename("entry", entry)
        return real_delete(handle)

    monkeypatch.setattr(work_area, "_open", open_)
    monkeypatch.setattr(work_area, "_delete_by_handle", delete)
    report = work_area.recover()
    assert attempts == {"workspace": "refused", "root": "refused", "entry": "refused"}
    assert report.removed == [str(entry)] and not workspace.exists()


# --------------------------------------------------------------------------- G. bounded, cancellable, never stuck


@windows_only
def test_recovery_stops_at_its_time_limit_and_finishes_at_a_later_start(temp, monkeypatch):
    workspaces = [fabricate(temp, entries={str(n): {"kind": "edge", "retention": "disposable", "state": "active"}
                                           for n in (1, 2, 3)}) for _ in range(3)]
    now = [0.0]
    real_remove = work_area._remove_entry

    def remove_entry(*args, **kwargs):
        now[0] += 1  # each entry takes "a second"
        return real_remove(*args, **kwargs)

    monkeypatch.setattr(work_area, "_remove_entry", remove_entry)
    report = work_area.recover(seconds=2.5, clock=lambda: now[0])
    assert report.deferred and len(report.removed) == 2, report
    assert "the rest is removed at a later start" in report.log_lines()[-1]
    report = work_area.recover()
    assert not report.deferred and not any(workspace.exists() for workspace in workspaces)


@windows_only
def test_cancel_stops_recovery_at_once(temp):
    workspace = fabricate(temp)
    before = tree(workspace)
    started = time.monotonic()
    report = work_area.recover(cancel_check=lambda: True)
    assert report.deferred and not report.removed and time.monotonic() - started < 1
    assert tree(workspace) == before


@windows_only
def test_a_dead_owners_file_another_program_still_holds_is_left_and_removed_once_free(temp, children, monkeypatch):
    workspace = fabricate(temp)
    held = workspace / "1" / "deep" / "assembly.wav"
    orphan = holding_child(children, held, temp.parent, "orphan")  # an encoder that outlived the program that started it
    passes = _count_passes(monkeypatch)
    started = time.monotonic()
    report = work_area.recover()
    assert time.monotonic() - started < 3, "a held file is never waited for without bound"
    assert passes == ["1"] * (len(work_area._IN_USE_RETRY_DELAYS) + 1), "a held file gets a few bounded looks"
    assert (str(held), "in use by another program") in report.left and held.exists()
    assert work_area.owner_state(orphan.owner) == work_area.ALIVE, "recovery never stops another process"
    kill(orphan)
    assert work_area.recover().removed and not workspace.exists()


# --------------------------------------------------------------------------- H. the routes never make loose temporaries


def _calls(path: Path) -> list[tuple[str, int, set[str]]]:
    tree_ = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree_):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "tempfile":
                found.append((node.func.attr, node.lineno, {k.arg for k in node.keywords}))
    return found


def test_no_tts_conversion_route_makes_a_temporary_outside_the_work_area():
    for name in ("tts/epub2tts_gui.py", "tts/epub2tts_edge/runner.py"):
        assert _calls(SCRIPTS / name) == [], f"{name} makes its own temporaries again"
    for name in ("tts/kokoro_synth.py", "tts/chatterbox_synth.py"):
        made = [call for call in _calls(SCRIPTS / name) if call[0] in ("NamedTemporaryFile", "mkstemp", "mkdtemp",
                                                                         "TemporaryDirectory")]
        assert made and all("dir" in keywords for _attr, _line, keywords in made), f"{name}: {made}"


def test_pydubs_temporaries_are_made_in_the_blocks_own_entry_and_removed_with_it(temp):
    with ffmpeg_watch.controlled(None):
        first = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)
        second = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)
        assert Path(first.name).parent == Path(second.name).parent
        folder = Path(first.name).parent
        manifest = json.loads((folder.parent / work_area.MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["entries"][folder.name]["kind"] == "pydub"
    assert not folder.exists()
    assert_no_workspace(temp)
    outside = ffmpeg_watch._named_temporary_file(mode="wb", delete=False)  # outside a block: as before
    outside.close()
    try:
        assert Path(outside.name).parent == temp
    finally:
        os.unlink(outside.name)
