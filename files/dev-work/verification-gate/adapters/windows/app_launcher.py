"""The REAL launcher and panels, in an isolated instance, with the observation channel beside them. Test-only; never shipped.

Runs ``launcher.main()`` itself, so what starts, what closes and how the process ends are production's. It differs from a user's launch
in exactly these places, each named in the journey's evidence:

  * settings, logs and runtime data point into this run's scratch, through the same module constants the test suite's isolation sets,
    so the real ``files/runtime-data`` is never written. The proved FFmpeg record is copied in so the pinned pair is the one used.
  * the output base is set in that isolated settings file, the way Preferences & Data would.
  * when a journey asks, the Edge service is replaced at ``edge_tts.Communicate`` by a local stand-in that hands back REAL MP3 frames and
    records each request. Everything after that point (requests, pacing, assembly, encoding, publication) is the production code. It is
    labelled replayed speech in the evidence, never engine qualification.
  * when a journey asks, a garbage collection is forced onto a worker thread after the window has gone (see ``_force_worker_collection``).
  * revealing a folder in Explorer is recorded instead of performed. A finished Converter run reveals its folder, and a journey must not
    leave Explorer windows on the owner's desktop or hand them the foreground. Whether the application asked, and for which folder, is
    what the journey checks.
  * a journey that runs real Kokoro reads the installed model through the real cache, offline: ``HF_HUB_OFFLINE`` makes a missing file an
    error instead of a download, and the gate compares the real runtime data before and after.

Usage: python app_launcher.py <config.json>
"""

from __future__ import annotations

import faulthandler
import gc
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import weakref
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(HERE))


def _load_config() -> dict:
    return json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))


def _isolate(config: dict) -> None:
    """Point the application at this run's folders before anything reads them."""
    from shared import ffmpeg_health, paths

    runtime = Path(config["runtime_dir"])
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "logs").mkdir(exist_ok=True)
    paths.RESOURCES_DIR = runtime
    paths.LOGS_DIR = runtime / "logs"
    paths.SETTINGS_FILE = runtime / "settings.json"
    ffmpeg_health.RESOURCES_DIR = runtime
    state = REPO_ROOT / "files" / "runtime-data" / ffmpeg_health.HEALTH_STATE_NAME
    shutil.copyfile(state, runtime / ffmpeg_health.HEALTH_STATE_NAME)
    settings = {"output_base_directory": config["output_base"], "last_tool": config.get("last_tool", "tts"),
                **config.get("settings", {})}
    (runtime / "settings.json").write_text(json.dumps(settings, indent=1), encoding="utf-8")


class _ReplayService:
    """Stands where Microsoft's service stands. A request gets the recorded clip of real MP3 frames its text selects, so the same words
    always make the same sound and the oracle can check order whatever order requests were made in. Nothing downstream is altered."""

    def __init__(self, config: dict) -> None:
        self.clips = [Path(path) for path in config["clips"]]
        self.log = Path(config["log"])
        self.delay = float(config.get("delay_seconds", 0))
        self.fail_flag = Path(config["fail_flag"]) if config.get("fail_flag") else None
        self.lock = threading.Lock()
        self.count = 0

    def clip_for(self, text: str) -> int:
        return int(hashlib.sha256(str(text).encode("utf-8")).hexdigest(), 16) % len(self.clips)

    def request(self, text: str, voice, rate) -> Path:
        clip = self.clip_for(text)
        with self.lock:
            index = self.count
            self.count += 1
            with open(self.log, "a", encoding="utf-8") as sink:
                sink.write(json.dumps({"index": index, "text": text, "voice": voice, "rate": rate, "clip": clip, "at": time.monotonic()}) + "\n")
        return self.clips[clip]


def _install_replay(config: dict) -> None:
    import asyncio

    import edge_tts

    service = _ReplayService(config)

    class Communicate:
        """Every shape the production callers use: ``Communicate(text, voice)`` and ``Communicate(text=, voice=, rate=)``."""

        def __init__(self, text=None, voice=None, rate=None, **_other) -> None:
            self.clip = service.request(text, voice, rate)

        async def save(self, path, *_other) -> None:
            if service.delay:
                await asyncio.sleep(service.delay)
            if service.fail_flag is not None and service.fail_flag.exists():
                raise ConnectionResetError("the replayed service was told to fail while this flag file exists")
            shutil.copyfile(self.clip, path)

    edge_tts.Communicate = Communicate


def _record_reveals(log: Path) -> None:
    from shared import subprocess_utils

    def record(path) -> None:
        with open(log, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"path": str(path), "at": time.monotonic()}) + "\n")

    subprocess_utils.reveal_in_file_manager = record


def _holder_chain(root) -> list[str]:
    """What keeps a closed root reachable: the shortest route up the referrers to something a collection never frees, a module's globals or
    a running thread's frame. Reported in the evidence so "it did not crash" comes with its reason."""
    import types

    start = id(root)
    seen = {start}
    queue = [(root, [])]
    skip = {id(queue), id(seen)}
    while queue:
        item, path = queue.pop(0)
        for holder in gc.get_referrers(item):
            if id(holder) in seen or id(holder) in skip or len(path) > 14:
                continue
            seen.add(id(holder))
            if isinstance(holder, types.FrameType):
                if holder.f_code.co_filename == __file__:
                    continue
                return [*path, f"frame {Path(holder.f_code.co_filename).name}:{holder.f_code.co_name}"]
            if isinstance(holder, types.ModuleType):
                return [*path, f"module {holder.__name__}"]
            name = type(holder).__name__
            if isinstance(holder, dict):
                owner = next((module for module in list(sys.modules.values()) if getattr(module, "__dict__", None) is holder), None)
                if owner is not None:
                    return [*path, f"globals of {owner.__name__}"]
            queue.append((holder, [*path, name]))
            skip.add(id(queue[-1]))
    return ["no route found"]


def _force_worker_collection(root_gone: threading.Event, done: threading.Event, record: Path, roots: list) -> None:
    """Plan: a collection that lands on a worker after the window closed is what crashes Tk (Decisions.md, Phase 2 closeout). Where one
    lands normally follows allocation history, so a clean exit proves little; forcing it answers yes or no. Waits for the window to go,
    then collects on this daemon thread, as any worker's allocation could. If Tk finalises here the process dies in that call."""
    root_gone.wait()
    began = time.monotonic()
    me = threading.current_thread()
    passes: list[int] = []

    def watch(phase: str, info: dict) -> None:
        if phase == "stop" and info["generation"] == 2 and threading.current_thread() is me:
            passes.append(info["collected"])

    gc.callbacks.append(watch)
    # gc.collect returns 0 at once while another collection is running, so one call is no proof a pass happened here. Count real passes.
    collected = 0
    with open(record.with_suffix(".stacks.txt"), "w", encoding="utf-8") as stacks:
        faulthandler.dump_traceback_later(8, file=stacks)
        while not passes and time.monotonic() - began < 20:
            collected = gc.collect()
            if not passes:
                time.sleep(0.02)
        faulthandler.cancel_dump_traceback_later()
    gc.callbacks.remove(watch)
    alive = [ref() for ref in roots]
    still = [item for item in alive if item is not None]
    chain = _holder_chain(still[0]) if still else []
    del alive, still
    record.write_text(json.dumps({"collected_on_worker": collected, "full_passes_on_worker": len(passes), "seconds": round(time.monotonic() - began, 3),
                                  "root_still_reachable": any(ref() is not None for ref in roots), "root_holder_chain": chain}), encoding="utf-8")
    done.set()


def main() -> int:
    config = _load_config()
    _isolate(config)
    if config.get("replay"):
        _install_replay(config["replay"])

    _record_reveals(Path(config["runtime_dir"]) / "reveals.jsonl")

    import launcher
    from channel import Channel

    if config.get("real_model_cache"):
        launcher._configure_hf_cache = lambda: os.environ.update(HF_HOME=config["real_model_cache"], HF_HUB_OFFLINE="1")

    root_gone, collected = threading.Event(), threading.Event()
    force = config.get("force_worker_collection")
    roots: list = []
    if force:
        threading.Thread(target=_force_worker_collection, args=(root_gone, collected, Path(force), roots),
                         name="forced-landing", daemon=True).start()
    real_app = launcher.LauncherApp

    def app_with_channel(root):
        roots.append(weakref.ref(root))
        app = real_app(root)

        def scoped(scope):
            if scope is None:
                return app
            container = app.containers[scope]
            children = container.winfo_children()
            return children[0] if children else container

        channel = Channel(root, channel_file=config["channel_file"], resolve=scoped)
        root._acceptance_channel = channel
        return app

    if config.get("control_no_stop_children"):
        launcher.sp.stop_media_children = lambda: []  # a negative control: the orphan this line exists to prevent must then be seen
    launcher.LauncherApp = app_with_channel
    exit_code = launcher.main()
    # main() has returned, so nothing on the main thread still holds the closed window.
    if force:
        if config.get("control_release_root"):
            # A negative control: what stands between the real application and the Phase 2 crash, taken away.
            from shared import appearance, output_paths

            output_paths.forget_destination_hints()
            appearance._listeners.clear()
        root_gone.set()
        collected.wait(30)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
