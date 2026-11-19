"""v0.8.x P1B -- the app window as a containment owner (plan section 11.2.2): FFmpeg and ffprobe as class B, the
optional-setup worker as class A, the POSIX ``stop_media_children``, and the closing latch.

Unit level, in this process, with a real :class:`shared.child_ownership.Owner` and real child processes. The programs
are stand-ins named ``ffmpeg`` and ``ffprobe`` (only the name decides how a child is *started*; nothing is ever found
or ended by name). The process-level tests -- the real launcher killed, crashed, quit and force-closed -- are
``test_macos_p1b_gui_containment.py`` (KX-1, KX-2, KX-3, KX-6, KX-7).

KX-8 here: a registry entry whose pid is still running but whose recorded start time is not that process's (a reused
pid) is never signalled by the orderly stop. Windows controls: with ``sys.platform`` reported as win32 nothing is
contained and every spawn is the plain ``subprocess`` call it always was.
"""

from __future__ import annotations

import ast
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shared import child_ownership, subprocess_utils as sp

NATIVE_P1B = "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks"
native = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P1B)


def _program(folder: Path, name: str, body: str) -> Path:
    """A shell script called *name*: a stand-in for a third-party executable."""
    path = folder / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _alive(pid: int, start) -> bool:
    return start is not None and child_ownership.process_start_time(pid) == start


@pytest.fixture
def owner(monkeypatch):
    """A real owner installed as this module's, as the app window installs it; shut down afterwards."""
    instance = child_ownership.Owner()
    monkeypatch.setattr(sp, "_owner", instance)
    yield instance
    instance.shutdown()


@pytest.fixture
def bin_dir(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    return folder


# --------------------------------------------------------------------------- #
#  Every platform: the opt-in, and Windows unchanged
# --------------------------------------------------------------------------- #
def test_without_an_owner_nothing_is_routed(monkeypatch):
    monkeypatch.setattr(sp, "_owner", None)
    assert sp._media_owner(["/x/ffmpeg", "-version"], {}) is None


def test_windows_never_enables_and_never_routes(monkeypatch):
    monkeypatch.setattr(sp.sys, "platform", "win32")
    assert sp.enable_containment() is None
    monkeypatch.setattr(sp, "_owner", object())
    assert sp._media_owner(["C:/ffmpeg/bin/ffmpeg.exe"], {}) is None
    assert sp._media_owner(["/x/ffmpeg"], {}) is None


def test_only_the_media_programs_started_as_lists_without_a_session_are_routed(monkeypatch):
    marker = object()
    monkeypatch.setattr(sp, "_owner", marker)
    monkeypatch.setattr(sp.sys, "platform", "darwin")
    assert sp._media_owner(["/app/files/bin/ffmpeg/9.0.1/bin/ffmpeg", "-i", "x"], {}) is marker
    assert sp._media_owner([Path("/app/bin/ffprobe")], {}) is marker
    assert sp._media_owner(["/usr/bin/open", "/tmp"], {}) is None, "the Finder opener is class D"
    assert sp._media_owner("ffmpeg -version", {}) is None, "a shell string is never routed"
    assert sp._media_owner(["/x/ffmpeg"], {"start_new_session": True}) is None
    assert sp._media_owner(["/x/ffmpeg"], {"process_group": 0}) is None
    assert sp.MEDIA_PROGRAMS == frozenset({"ffmpeg", "ffprobe"})


def test_the_windows_stop_is_still_the_toolhelp_walk():
    source = (Path(sp.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    stop = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "stop_media_children")
    text = ast.unparse(stop)
    assert "CreateToolhelp32Snapshot" in text and "TerminateProcess" in text
    assert "_MEDIA_CHILDREN" in text and sp._MEDIA_CHILDREN == frozenset({"ffmpeg.exe", "ffprobe.exe"})


# --------------------------------------------------------------------------- #
#  macOS: class B for the media programs
# --------------------------------------------------------------------------- #
@native
def test_ffmpeg_joins_the_guardians_group_and_other_programs_do_not(owner, bin_dir):
    ffmpeg = _program(bin_dir, "ffmpeg", "sleep 30")
    child = sp.popen([str(ffmpeg)], stdin=subprocess.DEVNULL)
    plain = sp.popen(["/bin/sleep", "30"])
    try:
        guardian = owner.guardian_pid()
        assert guardian is not None and os.getpgid(guardian) == guardian
        assert os.getpgid(child.pid) == guardian, "ffmpeg is in the guardian's group"
        assert owner.child(child).kind == child_ownership.CLASS_B and owner.child(child).label == "ffmpeg"
        assert os.getpgid(plain.pid) == os.getpgrp(), "a program that is not a media tool starts as before"
        assert owner.child(plain) is None
    finally:
        for proc in (child, plain):
            proc.kill()
            proc.wait()


@native
def test_run_and_check_output_keep_subprocess_semantics_when_contained(owner, bin_dir):
    ffprobe = _program(bin_dir, "ffprobe", 'echo "duration=4.5"; echo "warn" >&2; exit 0')
    failing = _program(bin_dir, "ffmpeg", 'echo "bad input" >&2; exit 3')
    done = sp.run([str(ffprobe)], capture_output=True, text=True)
    assert (done.returncode, done.stdout, done.stderr) == (0, "duration=4.5\n", "warn\n")
    assert sp.check_output([str(ffprobe)], text=True) == "duration=4.5\n"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        sp.check_output([str(failing)], stderr=subprocess.PIPE)
    assert caught.value.returncode == 3 and b"bad input" in caught.value.stderr
    assert sp.run([str(failing)]).returncode == 3
    assert owner.children() == [], "every contained run is forgotten once reaped"


@native
def test_a_contained_run_that_times_out_is_killed_by_identity(owner, bin_dir):
    slow = _program(bin_dir, "ffmpeg", "echo started; exec sleep 30")
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        sp.run([str(slow)], capture_output=True, timeout=0.5)
    assert time.monotonic() - began < 5
    assert owner.children() == []


@native
def test_a_supervised_step_cancelled_is_stopped_reaped_and_forgotten(owner, bin_dir):
    from shared.cancellation import ConversionCancelled

    slow = _program(bin_dir, "ffmpeg", "exec sleep 30")
    asked = {"cancel": False}
    started = []

    def cancel_check():
        children = owner.children()
        if children and not started:
            started.append((children[0].pid, children[0].start_time))
            asked["cancel"] = True
        return asked["cancel"]

    began = time.monotonic()
    with sp.cancellable(cancel_check), pytest.raises(ConversionCancelled):
        sp.run_supervised([str(slow)])
    assert time.monotonic() - began < 4, "CX-5's bound for one FFmpeg step"
    pid, start = started[0]
    assert not _alive(pid, start)
    assert owner.children() == []


@native
def test_the_posix_stop_ends_the_media_children_together_by_identity(owner, bin_dir):
    stubborn = _program(bin_dir, "ffmpeg", "trap '' TERM; while :; do sleep 1; done")
    children = [sp.popen([str(stubborn)], stdin=subprocess.DEVNULL) for _ in range(3)]
    identities = [(c.pid, child_ownership.process_start_time(c.pid)) for c in children]
    time.sleep(0.2)
    began = time.monotonic()
    stopped = sp.stop_media_children()
    took = time.monotonic() - began
    assert sorted(stopped) == sorted(c.pid for c in children)
    assert all(not _alive(pid, start) for pid, start in identities)
    assert took < 3.5, f"three children that ignore SIGTERM, ended together in {took:.2f} s"


@native
def test_kx8_the_orderly_stop_never_signals_a_pid_whose_start_time_is_not_the_recorded_one(owner, bin_dir):
    ffmpeg = _program(bin_dir, "ffmpeg", "exec sleep 30")
    child = sp.popen([str(ffmpeg)], stdin=subprocess.DEVNULL)
    try:
        entry = owner.child(child)
        real = entry.start_time
        entry.start_time = (real[0] - 1000, real[1])  # as if the pid now belonged to another process
        sp.stop_media_children()
        time.sleep(0.2)
        assert child.poll() is None, "the process with that pid is untouched"
        assert child_ownership.process_start_time(child.pid) == real
    finally:
        child.kill()
        child.wait()


@native
def test_once_the_app_is_closing_no_media_program_starts(owner, bin_dir):
    ffmpeg = _program(bin_dir, "ffmpeg", "exit 0")
    sp.begin_closing()
    with pytest.raises(child_ownership.ContainmentUnavailable):
        sp.popen([str(ffmpeg)])
    with pytest.raises(child_ownership.ContainmentUnavailable):
        owner.popen_python([sys.executable, "-c", "pass"])
    assert owner.children() == []


@native
def test_the_registry_holds_what_is_running_not_every_step_ever_run(owner, bin_dir):
    quick = _program(bin_dir, "ffprobe", "exit 0")
    for _ in range(25):
        child = sp.popen([str(quick)])
        child.wait()
    last = sp.popen([str(quick)])
    last.wait()
    assert len(owner.children()) <= 1


@native
def test_the_shutdown_ends_children_together_within_its_bound(owner, bin_dir):
    stubborn = _program(bin_dir, "ffmpeg", "trap '' TERM; while :; do sleep 1; done")
    media = [sp.popen([str(stubborn)], stdin=subprocess.DEVNULL) for _ in range(3)]
    workers = [owner.popen_python([sys.executable, "-c",
                                   "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
               for _ in range(2)]
    guardian = owner.guardian_pid()
    identities = [(p.pid, child_ownership.process_start_time(p.pid)) for p in media + workers]
    time.sleep(0.3)
    began = time.monotonic()
    owner.shutdown()
    took = time.monotonic() - began
    assert took <= child_ownership.SHUTDOWN_BOUND_S
    assert all(not _alive(pid, start) for pid, start in identities)
    with pytest.raises(ProcessLookupError):
        os.killpg(guardian, 0)


# --------------------------------------------------------------------------- #
#  macOS: class A for the optional-setup worker, and the TTS encode's FFmpeg
# --------------------------------------------------------------------------- #
@native
def test_the_setup_worker_route_is_class_a_with_the_lifeline_when_the_app_owns_it(owner, tmp_path):
    from tts import qwen3_process

    script = tmp_path / "worker.py"
    script.write_text("import os, sys; print(os.getpid(), os.getpgrp(), os.environ.get('ACT_LIFELINE_FD'), "
                      "any(a.endswith('child_entry.py') for a in sys.orig_argv), flush=True)", encoding="utf-8")
    proc = qwen3_process.spawn([sys.executable, "-I", str(script)], require_job=True, stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(timeout=30)
    pid, group, lifeline, through_entry = out.split()
    assert int(pid) == int(group) == proc.pid, "it leads its own group"
    assert lifeline == "None", "the entry took the descriptor before the program ran"
    assert through_entry == "True"
    assert proc.act_job is None


@native
def test_without_an_owner_the_setup_worker_route_is_unchanged(monkeypatch, tmp_path):
    from tts import qwen3_process

    monkeypatch.setattr(sp, "_owner", None)
    proc = qwen3_process.spawn([sys.executable, "-c", "import os, sys; print(os.getpgrp(), "
                                "any(a.endswith('child_entry.py') for a in sys.orig_argv))"], stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(timeout=30)
    group, through_entry = out.split()
    assert int(group) == proc.pid and through_entry == "False"


@native
def test_a_setup_worker_refused_while_the_window_closes_is_the_setup_protocols_containment_failure(owner):
    """WorkerRun maps qwen3_process.ContainmentUnavailable to CONTAINMENT_UNAVAILABLE; the owner's refusal is that."""
    from tts import qwen3_process

    owner.begin_closing()
    with pytest.raises(qwen3_process.ContainmentUnavailable, match="closing"):
        qwen3_process.spawn([sys.executable, "-c", "pass"], require_job=True)
    assert owner.children() == []


@native
def test_a_program_that_is_not_python_keeps_its_own_group_and_is_never_given_the_entry(owner, bin_dir):
    from tts import qwen3_process

    tool = _program(bin_dir, "helper", 'echo "$0 $1"')
    proc = qwen3_process.spawn([str(tool), "arg"], stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(timeout=30)
    assert out.split() == [str(tool), "arg"] and owner.children() == []


@native
def test_a_class_a_child_owns_the_python_children_it_starts(tmp_path):
    """The nested link KX-1(e) relies on: in a process watching a lifeline, qwen3_process.spawn makes that process an
    owner, so its child is class A of it (its own group, through the entry) rather than a new session nobody watches."""
    owner = child_ownership.Owner()
    try:
        script = tmp_path / "inner.py"
        script.write_text(
            "import os, subprocess, sys, threading\n"
            f"sys.path.insert(0, {str(Path(sp.__file__).resolve().parents[1])!r})\n"
            "from shared import subprocess_utils\n"
            "from tts import qwen3_process\n"
            "child = qwen3_process.spawn([sys.executable, '-c', 'import os, sys; "
            "print(os.getpgrp(), any(a.endswith(\"child_entry.py\") for a in sys.orig_argv))'], "
            "stdout=subprocess.PIPE, text=True)\n"
            "out, _ = child.communicate(timeout=30)\n"
            "print(child.pid, out.strip(), subprocess_utils.containment_owner() is not None)\n",
            encoding="utf-8")
        proc = owner.popen_python([sys.executable, "-I", str(script)], stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate(timeout=60)
        pid, group, through_entry, owns = out.split()
        assert int(group) == int(pid) != proc.pid and through_entry == "True" and owns == "True"
    finally:
        owner.shutdown()


@native
def test_the_tts_encodes_ffmpeg_is_class_b_too(owner, bin_dir):
    from tts import ffmpeg_watch

    ffmpeg = _program(bin_dir, "ffmpeg", "exec sleep 30")
    child = ffmpeg_watch.Supervised([str(ffmpeg)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
    try:
        assert os.getpgid(child.pid) == owner.guardian_pid()
        assert owner.child(child.process).kind == child_ownership.CLASS_B
    finally:
        child.abandon()


def test_the_tts_encode_still_makes_the_same_popen_call_on_windows(monkeypatch):
    from tts import ffmpeg_watch

    calls = []

    class Fake:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))
            self.stdin = self.stdout = None
            self.pid = 1

    monkeypatch.setattr(sp.sys, "platform", "win32")
    monkeypatch.setattr(sp, "_hidden_kwargs", lambda: {"creationflags": 0x08000000})
    monkeypatch.setattr(sp.subprocess, "Popen", Fake)
    monkeypatch.setattr(ffmpeg_watch, "_ensure_watchdog", lambda: None)
    watched = ffmpeg_watch.Supervised(["ffmpeg.exe", "-i", "x", "out.mp3"], stdin=None, stdout=None, stderr=None)
    watched._stop_watching()
    assert calls == [(["ffmpeg.exe", "-i", "x", "out.mp3"],
                      {"creationflags": 0x08000000, "stdin": None, "stdout": None, "stderr": None})]


# --------------------------------------------------------------------------- #
#  KX-9: the spawn-site guard over the app window, the five tools and the shared layer
# --------------------------------------------------------------------------- #
_SPAWNS = {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
_OS_SPAWNS = {"system", "popen", "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnl", "spawnle", "execv",
              "execve", "execvp", "execvpe", "execl", "execle", "execlp", "startfile", "fork", "forkpty"}

#: Every direct ``subprocess``/``os`` spawn in the application, with why it is not (or not yet) a P1B-owned child.
#: The guard fails on a site that is not here and on an entry whose site is gone, so the list stays exact.
KX9_ALLOWED = {
    # v0.8.x P5-I: class A, class B and the guardian all spawn through the one admitted spawn of the ownership helper.
    ("shared/child_ownership.py", "_spawn"): "the ownership helper itself (class A, class B and the guardian)",
    ("shared/child_launch.py", "main"): "v0.8.x P5-I-R3: the launch gate; it executes only the one-time permit its "
                                        "owner created inside the run's counted start",
    ("shared/subprocess_utils.py", "run"): "the wrapper: FFmpeg/ffprobe routed to class B when the window owns them",
    ("shared/subprocess_utils.py", "popen"): "the wrapper: FFmpeg/ffprobe routed to class B when the window owns them",
    ("shared/subprocess_utils.py", "check_output"): "the wrapper: FFmpeg/ffprobe routed to class B when owned",
    ("shared/subprocess_utils.py", "_ask_file_manager"): "Windows branch only (os.startfile); macOS `open` is class D",
    ("shared/bootstrap.py", "relaunch_setup"): "setup side (P1A; test_child_ownership's KX-9 guard)",
    ("shared/bootstrap.py", "_child_run"): "setup side (P1A; Windows branch, contained on macOS)",
    ("shared/bootstrap.py", "_run"): "setup side (P1A; Windows branch, contained on macOS)",
    ("shared/bootstrap.py", "_pip"): "setup side (P1A; Windows branch, contained on macOS)",
    ("shared/bootstrap.py", "launch_gui"): "class D: the app window started by setup",
    ("shared/bootstrap.py", "hand_off_launch_only"): "Windows only: --launch-only restarted with a hidden console",
    ("shared/bootstrap.py", "_open_folder"): "class D: the setup log's folder opened in Finder/Explorer",
    ("shared/cleanup_state.py", "spawn_coordinator"): "class D: the cleanup coordinator must outlive the window",
    ("shared/cleanup_state.py", "_probe_is_non_venv"): "a bounded 30 s probe of a candidate Python (cleanup)",
    ("shared/close_terminal.py", "main"): "class D: closes the launch Terminal window (P1A)",
    ("shared/long_paths.py", "_spawn_probe"): "Windows only: the long-path probe",
    ("shared/long_paths.py", "_probe"): "Windows only: the long-path probe",
    ("shared/release.py", "_git"): "developer packaging; never run by the app",
    ("tts/chatterbox_synth.py", "build_reference_clip"): "TTS: P3A (Chatterbox) owns this FFmpeg call",
    ("tts/generate_voice_samples.py", "measure_final_artifact"): "TTS sample generation (P2/P3A); developer tool",
    ("tts/generate_voice_samples.py", "_git_commit_sha"): "TTS sample generation; developer tool",
}

#: Keyword arguments that would make a wrapper start FFmpeg outside the guardian's group.
_BYPASS = {"start_new_session", "process_group", "preexec_fn", "shell"}


def _direct_spawn_sites():
    from source_probe import UNIVERSAL, application_python_files

    sites: dict = {}
    for path in application_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)):
                continue
            module, name = node.func.value.id, node.func.attr
            if (module == "subprocess" and name in _SPAWNS) or (module == "os" and name in _OS_SPAWNS):
                cursor, function = node, "<module>"
                while cursor in parents:
                    cursor = parents[cursor]
                    if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        function = cursor.name
                        break
                key = (path.relative_to(UNIVERSAL).as_posix(), function)
                sites.setdefault(key, []).append(node.lineno)
    return sites


def test_kx9_every_direct_spawn_is_the_ownership_helper_a_routed_wrapper_or_named():
    sites = _direct_spawn_sites()
    unknown = {key: lines for key, lines in sites.items() if key not in KX9_ALLOWED}
    assert unknown == {}, f"a direct spawn that neither the window owns nor this list names: {unknown}"
    gone = sorted(set(KX9_ALLOWED) - set(sites))
    assert gone == [], f"allow-list entries whose spawn is gone (remove them): {gone}"


def test_kx9_no_media_spawn_in_the_window_or_the_five_tools_bypasses_the_guardian():
    """A wrapper call that names its own session, group or shell is started exactly as asked -- outside class B -- so
    none of the GUI's or the five tools' calls may pass one."""
    from source_probe import UNIVERSAL, application_python_files

    wrappers = {"run", "popen", "check_output", "run_supervised"}
    roots = ("launcher.py", "m4b/", "mp3/", "artwork/", "shared/metadata.py", "shared/ffmpeg_utils.py",
             "shared/ffmpeg_health.py", "tts/ffmpeg_watch.py")
    offenders = []
    for path in application_python_files():
        relative = path.relative_to(UNIVERSAL).as_posix()
        if not relative.startswith(roots):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in wrappers \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in ("sp", "_sp", "subprocess_utils"):
                passed = {k.arg for k in node.keywords} & _BYPASS
                if passed:
                    offenders.append(f"{relative}:{node.lineno} {sorted(passed)}")
    assert offenders == []
