"""The application owns its Tk root for the life of the process (v0.7.2 Phase 3 acceptance closeout, Task B).

**The defect.** A closed Tk root freed by a collection on a worker thread deletes the Tcl interpreter on that thread: ``Tcl_AsyncDelete:
async handler deleted by the wrong thread``, exit ``0x80000003`` (Phase 2 closeout). The real application did not crash only because two
module lists happened to keep the closed root reachable, ``shared.output_paths._HINT_DISPLAYS`` and ``shared.appearance._listeners``.
Emptying both and forcing one collection onto a worker crashed real ACT (Phase 3, ``control.act-crash-seen-with-the-root-released``).

**The fix.** ``launcher.main`` keeps the root in ``launcher._ROOT``, the application's own deliberate holder. The interpreter is then only
deleted when Python itself shuts down, on the main thread, once it has stopped running daemon workers.

Each arm runs the real ``launcher.main()`` in a bounded child, with its settings in ``tmp_path``, and closes through the real close handler.
After ``main()`` returns the accidental holders are emptied and a full collection is forced onto a worker, proven by ``gc.callbacks``,
because where a collection lands otherwise follows allocation history and a clean exit would prove little. The negative control also takes
the application's holder away, and must crash: that shows the forced collection can see this crash, and that the holder is what prevents it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the measured crash and its exit status are Windows'")

REPO_ROOT = Path(__file__).resolve().parents[2]
EXIT_TCL_CRASH = 0x80000003
BOUND = 90

_CHILD = textwrap.dedent(
    r'''
    import faulthandler, gc, json, shutil, sys, threading, time, weakref
    from pathlib import Path

    sys.path.insert(0, {scripts!r})
    work, mode = Path({work!r}), {mode!r}
    from shared import appearance, ffmpeg_health, output_paths, paths

    runtime = work / "runtime"
    (runtime / "logs").mkdir(parents=True)
    paths.RESOURCES_DIR, paths.LOGS_DIR, paths.SETTINGS_FILE = runtime, runtime / "logs", runtime / "settings.json"
    ffmpeg_health.RESOURCES_DIR = runtime
    shutil.copyfile(Path({repo!r}) / "files" / "runtime-data" / ffmpeg_health.HEALTH_STATE_NAME, runtime / ffmpeg_health.HEALTH_STATE_NAME)
    (runtime / "settings.json").write_text(json.dumps({{"output_base_directory": str(work / "out"), "last_tool": "cover"}}), encoding="utf-8")

    import launcher

    roots = []
    real_app = launcher.LauncherApp

    def app_that_closes_itself(root):
        roots.append(weakref.ref(root))
        app = real_app(root)
        root.after(600, app._on_close)  # the window manager's close, through the application's own handler
        return app

    launcher.LauncherApp = app_that_closes_itself
    began = time.monotonic()
    code = launcher.main()
    record = {{"main_returned": code, "close_seconds": round(time.monotonic() - began, 3), "holder_set": launcher._ROOT is not None
               if hasattr(launcher, "_ROOT") else "absent"}}

    # What happened to hold the closed root until now, besides the application's own holder.
    output_paths.forget_destination_hints()
    appearance._listeners.clear()
    record["accidental_holders_left"] = len(output_paths._HINT_DISPLAYS) + len(appearance._listeners)
    if mode == "release-everything":
        launcher._ROOT = None  # the negative control

    passes = []

    def worker():
        me = threading.current_thread()

        def watch(phase, info):
            if phase == "stop" and info["generation"] == 2 and threading.current_thread() is me:
                passes.append(info["collected"])

        gc.callbacks.append(watch)
        faulthandler.dump_traceback_later(20, exit=False)
        deadline = time.monotonic() + 20
        while not passes and time.monotonic() < deadline:
            gc.collect()
            if not passes:
                time.sleep(0.02)
        faulthandler.cancel_dump_traceback_later()
        gc.callbacks.remove(watch)

    thread = threading.Thread(target=worker, name="forced-landing", daemon=True)
    thread.start()
    thread.join(30)
    alive = roots[0]()
    record.update(full_passes_on_worker=len(passes), root_still_reachable=alive is not None,
                  held_by_application=alive is not None and getattr(launcher, "_ROOT", None) is alive)
    del alive
    print("RECORD " + json.dumps(record), flush=True)
    sys.exit(code)
    '''
)


def _run(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess, dict | None]:
    work = tmp_path / mode
    work.mkdir()
    source = _CHILD.format(scripts=str(REPO_ROOT / "scripts"), work=str(work), mode=mode, repo=str(REPO_ROOT))
    env = {key: value for key, value in __import__("os").environ.items() if key not in ("PYTHONPATH", "PYTHONSTARTUP")}
    env.update(TEMP=str(work), TMP=str(work), APPDATA=str(work / "appdata"), LOCALAPPDATA=str(work / "localappdata"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", source], capture_output=True, text=True, timeout=BOUND, cwd=work, env=env)
    lines = [line for line in result.stdout.splitlines() if line.startswith("RECORD ")]
    return result, (json.loads(lines[-1][len("RECORD "):]) if lines else None)


@pytest.fixture(scope="module")
def both_arms(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("root-lifetime")
    return {mode: _run(tmp, mode) for mode in ("accidental-holders-emptied", "release-everything")}


def test_with_the_accidental_holders_emptied_the_application_still_holds_its_root(both_arms):
    result, record = both_arms["accidental-holders-emptied"]
    assert record is not None, result.stderr[-2000:]
    assert record["accidental_holders_left"] == 0
    assert record["full_passes_on_worker"] >= 1, "no full collection ran on the worker, so this arm proves nothing"
    assert record["root_still_reachable"] and record["held_by_application"], record
    assert "Tcl_AsyncDelete" not in result.stderr and "Fatal Python error" not in result.stderr, result.stderr[-2000:]
    assert result.returncode == 0, (hex(result.returncode & 0xFFFFFFFF), result.stderr[-2000:])


def test_the_negative_control_crashes_once_the_application_holder_is_gone_too(both_arms):
    result, record = both_arms["release-everything"]
    assert (result.returncode & 0xFFFFFFFF) == EXIT_TCL_CRASH, (hex(result.returncode & 0xFFFFFFFF), result.stderr[-2000:])
    assert "Tcl_AsyncDelete" in result.stderr, result.stderr[-2000:]
    assert record is None, "the process outlived a collection that freed its root on a worker"


def test_the_holder_is_the_launchers_own_and_set_before_the_window_is_built():
    """Read from the source: main() takes the root into the module global in the same statement that creates it."""
    import ast

    tree = ast.parse((REPO_ROOT / "scripts" / "launcher.py").read_text(encoding="utf-8"))
    module_names = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
    assert "_ROOT" in module_names
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    assert any(isinstance(node, ast.Global) and "_ROOT" in node.names for node in ast.walk(main))
    creation = [node for node in ast.walk(main) if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == "tk.Tk"]
    assert len(creation) == 1 and "_ROOT" in {ast.unparse(target) for target in creation[0].targets}
