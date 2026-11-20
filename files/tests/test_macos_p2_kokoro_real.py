"""v0.8.x P2 -- Kokoro-82M on macOS, for real: the model in the local-engine worker (plan 11.2.1, 11.2.3, 12.B).

Opt-in: ``ACT_KOKORO_P2_REAL=1`` on a Mac where Kokoro is installed in this checkout (the pinned model, its nine voices
and spaCy's English model, each verified by ``tts.model_assets``); the routine gate never sets it, and an opted-in run
without the files FAILS rather than skips. Every Cancel here interrupts real inference -- never a sleeping stand-in.

* E-B1 (in the worker): the model loads on the CPU in float32, offline, from the verified files, with the pinned
  packages; eSpeak NG's data path is reported (MAC-035).
* Parity (11.2.1): for texts A, B and C, prepared once in the parent (``v1``) and chunked as production chunks them, the
  worker's phoneme stream equals the in-process pipeline's, chunk by chunk; with one seed, the PCM is identical too.
* CX-1: Cancel while a real 3,000-character chunk is mid-inference, after its "started" event: the worker's group is
  gone and reaped within 2 s, the run is cancelled, nothing is published, the conversion's work-area folder is gone.
* CX-7: Cancel, then a new run with the same voice: it succeeds, in a new worker that cold-loads and says so.
* CX-6 (the real panel, real threads): Pause during file 1's chunk lets file 1 finish and publish and starts nothing
  of file 2 while the worker stays loaded; Cancel while paused is acknowledged (CANCEL_REQUESTED, "Cancelling…") within
  0.5 s, the run is CANCELLED and the idle worker ended within 2 s, file 1 untouched, file 2 never published.
* CX-8: Cancel in the publication window, both orders: nothing published, or the whole file published and reported.
* KX-1(a), KX-2(a), KX-3(a): the REAL window (``macos_gui_driver.py``) killed with SIGKILL, SIGSEGV or SIGABRT, or
  ended by SIGTERM or Quit, during real inference: the worker is gone within 3 s (5 s for an orderly end), by pid and
  start time and by its group; no output under a final name. KX-7: without the lifeline the orphan IS seen.
"""

from __future__ import annotations

import hashlib
import os
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

NATIVE_P2 = "native macOS only (P2): the local-engine worker, POSIX containment and real Kokoro"
OPT_IN = "loads the Kokoro model; set ACT_KOKORO_P2_REAL=1 where it is installed"
pytestmark = [pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_P2),
              pytest.mark.skipif(os.environ.get("ACT_KOKORO_P2_REAL") != "1", reason=OPT_IN)]

from shared import child_ownership  # noqa: E402
from shared.cancellation import ConversionCancelled  # noqa: E402
from tts import local_engine_host as hosts  # noqa: E402

CANCEL_BOUND_S = 2.0      # the local-engine worker's T_stop (11.2.1)
ACK_BOUND_S = 1.0         # C1 (owner decision 2026-11-20: about one second; was 0.5 s)
ORPHAN_BOUND_S = 3.0      # KX-1/KX-2
ORDERLY_BOUND_S = 5.0     # KX-3


@pytest.fixture(scope="module", autouse=True)
def _kokoro_installed():
    from tts import model_assets

    kokoro = model_assets.kokoro_set()
    wrong = {name: state for name, (state, _d) in model_assets.assess(kokoro, kokoro.files).items()
             if state != model_assets.READY}
    if wrong or model_assets.installed_version(model_assets.SPACY_ENGLISH) != model_assets.SPACY_ENGLISH_VERSION:
        pytest.fail(f"opted in, but Kokoro is not installed here as approved: {wrong or 'spaCy English model'}")
    yield
    hosts.release("tests over")


@pytest.fixture
def fresh_host(monkeypatch):
    """A host of this process's own (a private owner: no app window here), released afterwards."""
    hosts.release("a fresh host")
    yield
    hosts.release("test over")


def _gone(pid: int, start) -> bool:
    return child_ownership.process_start_time(pid) != start


def _group_empty(pgid: int) -> bool:
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _measured(case: str, **values) -> None:
    """The measured figures, appended to ``$ACT_P2_EVIDENCE/measurements.jsonl`` when that folder is named (the P2
    evidence runs name it); otherwise nothing. The assertions never depend on it."""
    folder = os.environ.get("ACT_P2_EVIDENCE")
    if folder:
        import json

        Path(folder).mkdir(parents=True, exist_ok=True)
        with open(Path(folder) / "measurements.jsonl", "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"case": case, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **values},
                                  default=str) + "\n")


def _params(voice: str = "af_heart") -> dict:
    """The panel's frozen Kokoro parameters for ``voice``: its preset's speed and pauses, 192k, v1, no overwrite."""
    from tts.speech.pipeline import build_snapshot
    from tts.voice_registry import VOICES

    entry = next(v for v in VOICES if v.voice_id == voice)
    preset = entry.timing_preset
    return {"voice_id": voice, "kokoro_speed": float(preset["kokoro_speed"]),
            "end_pause": int(preset.get("end_pause", 0)), "paragraph_pause": int(preset.get("paragraph_pause", 50)),
            "bitrate": "192k", "overwrite": False, "speech_prep": build_snapshot("v1", user_dir=None)}


def _one_full_chunk() -> str:
    """Prose that prepares and chunks to exactly one chunk of at least 2,900 characters (production's ceiling 3,000)."""
    from tts import kokoro_synth as ks
    from tts.quality_corpus import LONGER_STRESS
    from tts.speech.pipeline import build_snapshot, prepare
    from tts.speech.profiles import KOKORO

    import re

    snapshot = build_snapshot("v1", user_dir=None)
    sentences = re.split(r"(?<=[.!?])\s+", LONGER_STRESS.text.replace("\n\n", " "))
    text = ""
    for sentence in sentences:  # whole sentences, greedily, as long as the prepared text stays one chunk
        trial = (text + " " + sentence).strip()
        if len(prepare(trial, snapshot, KOKORO).text) <= 2995:
            text = trial
    chunks = ks.split_into_chunks(prepare(text, build_snapshot("v1", user_dir=None), KOKORO).text)
    assert len(chunks) == 1 and len(chunks[0]) >= 2900, [len(c) for c in chunks]
    return text


def _latch_after_started(delay: float = 0.3):
    """A Cancel latch that closes ``delay`` s after the worker reports a chunk started (synchronised on the event)."""
    state = {"set": False, "at": None, "started_at": None}

    def watch() -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            host = hosts.current_host()
            if host is not None and any(e.name == "started" for e in host.history):
                state["started_at"] = time.monotonic()
                time.sleep(delay)
                state["at"] = time.monotonic()
                state["set"] = True
                return
            time.sleep(0.01)

    threading.Thread(target=watch, daemon=True).start()
    return state, (lambda: state["set"])


# --------------------------------------------------------------------------- E-B1 in the worker
def test_eb1_the_worker_loads_kokoro_on_the_cpu_in_float32_offline_with_the_pinned_packages(fresh_host):
    host = hosts.host_for("kokoro", sample_rate=24000, log=lambda s: None)
    american = host.load({"lang_code": "a"})
    british = host.load({"lang_code": "b"})
    for info in (american, british):
        assert info["device"] == "cpu" and info["dtype"] == "float32", info
    versions = host.hello["versions"]
    assert versions["torch"] == "2.6.0" and versions["kokoro"] == "0.9.4" and versions["misaki"] == "0.9.4", versions
    assert versions["en_core_web_sm"] == "3.8.0", versions
    assert american["espeak"]["data_path_chars"], american
    pcm = host.synthesize({"text": "Zxqorvian brindlewhisk gloamtide.", "voice": "af_heart", "speed": 1.0,
                           "split_pattern": r"\n+", "seed": None}).pcm
    assert pcm.size > 24000 * 0.5 and np.isfinite(pcm).all()


# --------------------------------------------------------------------------- parity (11.2.1)
def _texts() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev-tools"))
    import omnivoice_p4_acceptance as p4  # the v0.8.0 tracks A and B, read from the tracked sources verbatim
    from tts.quality_corpus import SUSTAINED_NARRATION

    return {"A": p4.track_a_source(), "B": p4.track_b_source(p4.track_b_items()), "C": SUSTAINED_NARRATION.text}


def test_parity_the_worker_and_the_in_process_pipeline_give_the_same_phonemes_and_seeded_pcm(fresh_host):
    from tts import kokoro_synth as ks
    from tts.speech.pipeline import build_snapshot, prepare
    from tts.speech.profiles import KOKORO

    host = hosts.host_for("kokoro", sample_rate=24000, log=lambda s: None)
    host.load({"lang_code": "a"})
    pipeline = ks._get_pipeline("a")  # the in-process route, in this process
    snapshot = build_snapshot("v1", user_dir=None)
    compared = 0
    for name, text in _texts().items():
        for chunk in ks.split_into_chunks(prepare(text, snapshot, KOKORO).text):
            via_worker = host.synthesize({"text": chunk, "voice": "af_heart", "speed": 1.0, "split_pattern": r"\n+",
                                          "seed": None})
            in_process = [phonemes for _g, phonemes, _a in pipeline(chunk, voice="af_heart", speed=1.0,
                                                                     split_pattern=r"\n+")]
            assert via_worker.phonemes == in_process, f"text {name}: the phoneme streams differ"
            compared += 1
    assert compared >= 4
    short = ks.split_into_chunks(prepare(_texts()["A"], snapshot, KOKORO).text)[0]
    seeded = host.synthesize({"text": short, "voice": "af_heart", "speed": 1.0, "split_pattern": r"\n+",
                              "seed": 1234}).pcm
    import torch

    torch.manual_seed(1234)
    local = np.concatenate([a.numpy() for _g, _p, a in pipeline(short, voice="af_heart", speed=1.0,
                                                                split_pattern=r"\n+") if a is not None])
    assert seeded.dtype == local.dtype and seeded.shape == local.shape
    assert np.array_equal(seeded, local), f"seeded PCM differs: max {float(np.max(np.abs(seeded - local)))}"


# --------------------------------------------------------------------------- CX-1 and CX-7 (the panel's own per-file route)
def test_cx1_cancel_mid_inference_of_a_3000_character_chunk_stops_within_2s_and_cx7_the_next_run_cold_loads(
        fresh_host, tmp_path):
    from shared import work_area
    from tts import epub2tts_gui as panel_module

    source = tmp_path / "long.txt"
    source.write_text(_one_full_chunk(), encoding="utf-8")
    destination = tmp_path / "out" / "long-Kokoro.mp3"
    destination.parent.mkdir()
    folders: list[Path] = []
    real_folder = work_area.conversion_folder

    def recorded(kind):
        context = real_folder(kind)

        class Recorded:
            def __enter__(self):
                path = context.__enter__()
                folders.append(Path(path))
                return path

            def __exit__(self, *exc):
                return context.__exit__(*exc)

        return Recorded()

    latch, cancelled = _latch_after_started(0.5)
    logged: list[str] = []
    panel_module.work_area.conversion_folder, saved = recorded, panel_module.work_area.conversion_folder
    try:
        with pytest.raises(ConversionCancelled):
            panel_module.convert_with_kokoro({"source": source, "destination": destination}, _params(), None,
                                             logged.append, cancelled)
    finally:
        panel_module.work_area.conversion_folder = saved
    stopped = time.monotonic()
    host = hosts.current_host()
    killed = [e for e in host.history if e.name == "killed"]
    spawned = [e for e in host.history if e.name == "ready"]
    assert latch["at"] is not None and killed, [e.name for e in host.history]
    assert killed[-1].at - latch["at"] <= CANCEL_BOUND_S, f"worker ended {killed[-1].at - latch['at']:.3f} s after"
    assert stopped - latch["at"] <= CANCEL_BOUND_S, f"the run ended {stopped - latch['at']:.3f} s after the latch"
    pid = int(spawned[-1].detail["pid"])
    assert child_ownership.process_start_time(pid) is None, "the worker is gone and reaped"
    assert _group_empty(pid), "its whole group is gone"
    assert not destination.exists(), "nothing published"
    assert folders and not any(folder.exists() for folder in folders), "the conversion's work-area folder is gone"
    chunk_seconds = latch["at"] - latch["started_at"]
    assert chunk_seconds >= 0.5, "Cancel landed while the chunk was in flight"
    _measured("CX-1", chunk_chars=len(source.read_text(encoding="utf-8")), latch_after_started_s=chunk_seconds,
              worker_ended_after_latch_s=killed[-1].at - latch["at"], run_ended_after_latch_s=stopped - latch["at"],
              kill_and_reap_s=killed[-1].detail.get("seconds"), returncode=killed[-1].detail.get("returncode"))

    # CX-7: the same voice again -- a new worker, a cold load said in the log, a published file.
    short = tmp_path / "short.txt"
    short.write_text("The keeper climbed the stairs. The light was steady again.", encoding="utf-8")
    again = tmp_path / "out" / "short-Kokoro.mp3"
    logged.clear()
    panel_module.convert_with_kokoro({"source": short, "destination": again}, _params(), None, logged.append,
                                     lambda: False)
    assert again.is_file() and again.stat().st_size > 4000
    assert host.starts == 2 and int(host.hello["pid"]) != pid
    assert any("model loaded in its worker process (cold start #2" in line for line in logged), logged
    _measured("CX-7", restarted_pid=host.hello["pid"], load_line=[line for line in logged if "model loaded" in line])


# --------------------------------------------------------------------------- CX-8 (the publication window)
@pytest.mark.parametrize("order", ["cancel-then-rename", "rename-then-cancel"])
def test_cx8_cancel_in_the_publication_window(fresh_host, tmp_path, monkeypatch, order):
    from shared import output_paths
    from tts import epub2tts_gui as panel_module

    source = tmp_path / "pub.txt"
    source.write_text("The ferry would not arrive before evening.", encoding="utf-8")
    destination = tmp_path / "out" / "pub-Kokoro.mp3"
    destination.parent.mkdir()
    pressed = {"set": False}
    moves: list[tuple[Path, str]] = []
    real = output_paths.move_without_replacing

    def move(staged, final):
        digest = _sha(staged)
        if order == "cancel-then-rename":
            pressed["set"] = True
        real(staged, final)
        moves.append((Path(final), digest))
        if order == "rename-then-cancel":
            pressed["set"] = True

    monkeypatch.setattr(output_paths, "move_without_replacing", move)
    try:
        panel_module.convert_with_kokoro({"source": source, "destination": destination}, _params(), None,
                                         lambda s: None, lambda: pressed["set"])
        outcome = "published"
    except ConversionCancelled:
        outcome = "cancelled"
    if outcome == "cancelled":
        assert not destination.exists() or (moves and _sha(destination) == moves[-1][1]), "never a part"
    else:
        assert moves and destination.is_file() and _sha(destination) == moves[-1][1], "the whole file, reported"
    assert [p.name for p in destination.parent.iterdir() if p != destination] == [], "nothing else under a name"
    _measured("CX-8", order=order, outcome=outcome, published=destination.exists())


# --------------------------------------------------------------------------- CX-6 (the real panel, real threads)
@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk

    import tk_gate

    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def isolated_outputs(tmp_path, monkeypatch):
    from shared import config as shared_config
    from shared import output_paths
    from shared import settings as app_settings

    base = tmp_path / "outputs"
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    shared_config.invalidate()
    monkeypatch.setattr(output_paths, "resolve_output_base", lambda effective=None: base)
    try:
        yield base
    finally:
        app_settings.use_path(None)
        shared_config.invalidate()


def test_cx6_pause_at_the_file_boundary_then_cancel_while_paused(fresh_host, tk_root, isolated_outputs, tmp_path,
                                                                 monkeypatch):
    from shared.job_control import JobState
    from tts import epub2tts_gui as panel_module
    from tts.voice_registry import VOICES

    first, second = tmp_path / "First Story.txt", tmp_path / "Second Story.txt"
    first.write_text(_one_full_chunk(), encoding="utf-8")
    second.write_text("Mrs. Yates called from the stairs below. The second file must never be read.", encoding="utf-8")
    sent: list[str] = []
    real_synthesize = hosts.WorkerHost.synthesize

    def recording(self, request, *args, **kwargs):
        sent.append(request["text"])
        return real_synthesize(self, request, *args, **kwargs)

    hosts.WorkerHost.synthesize = recording
    for name in ("showwarning", "showinfo", "showerror"):  # a refusal fails here, with the panel's own words
        monkeypatch.setattr(panel_module.messagebox, name,
                            lambda title=None, message=None, **_k: pytest.fail(f"the panel said: {title}: {message}"))
    panel = panel_module.TtsPanel(tk_root, choose_files=lambda: (str(first), str(second)))
    def pump_until(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            panel._pump.tick()
            tk_root.update()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    try:
        panel.importer.add_files()
        assert pump_until(lambda: len(panel._manager.snapshot().files) == 2, 30), "both sources listed"
        heart = next(v for v in VOICES if v.voice_id == "af_heart")
        panel.selected_voice_label.set(heart.display_label)
        panel._on_voice_selected()
        panel.workers_var.set("1")
        panel.run_job()
        worker = panel._worker  # the run's thread (run_job itself returns nothing)
        assert worker is not None, "the panel did not start the run"

        assert pump_until(lambda: (hosts.current_host() is not None
                                   and any(e.name == "started" for e in hosts.current_host().history)), 120)
        panel.pause()  # Pause during file 1's chunk
        assert pump_until(lambda: panel._controller.state is JobState.PAUSED, 300), panel._controller.state
        published = sorted(isolated_outputs.rglob("*.mp3"))
        assert [p.name.split("-")[0] for p in published] == ["First Story"], published
        digest = _sha(published[0])
        assert not any("Second Story" in t or "never be read" in t for t in sent), "file 2 was not started"
        host = hosts.current_host()
        assert host.alive(), "paused: the worker stays loaded and idle"
        pid, start = host.pid, child_ownership.process_start_time(host.pid)
        clicked = time.monotonic()
        panel.cancel_job()
        acknowledged = None
        while time.monotonic() - clicked < 5:
            panel._pump.tick()
            tk_root.update()
            if (panel._controller.state in (JobState.CANCEL_REQUESTED, JobState.CANCELLED)
                    and acknowledged is None and "Cancel" in panel.jobs.status.status_text):
                acknowledged = time.monotonic() - clicked
            if panel._controller.state is JobState.CANCELLED and _gone(pid, start):
                break
            time.sleep(0.01)
        ended = time.monotonic() - clicked
        assert acknowledged is not None and acknowledged <= ACK_BOUND_S, acknowledged
        assert panel._controller.state is JobState.CANCELLED and ended <= CANCEL_BOUND_S, (panel._controller.state,
                                                                                         ended)
        assert _gone(pid, start), "Cancel while paused ended the idle worker"
        _measured("CX-6", c1_ack_s=acknowledged, c2_cancelled_and_worker_gone_s=ended,
                  first_published=published[0].name, sent_chunks=len(sent))
        assert _sha(published[0]) == digest and sorted(isolated_outputs.rglob("*.mp3")) == published
        worker.join(10)
    finally:
        hosts.WorkerHost.synthesize = real_synthesize
        panel.close()


# --------------------------------------------------------------------------- KX-1(a), KX-2(a), KX-3(a), KX-7 (the real window)
@pytest.fixture
def window(tmp_path):
    import test_macos_p1b_gui_containment as gui

    made: list = []

    def start(**options):
        app = gui.App(tmp_path / f"app{len(made)}", "kokoro", last_tool="tts",
                      kokoro_text=_one_full_chunk(), **options)
        made.append(app)
        return app

    (tmp_path / "app0").mkdir()
    for index in range(1, 4):
        (tmp_path / f"app{index}").mkdir()
    yield start
    for app in made:
        app.close()


def _worker_in_flight(app) -> tuple[int, int, tuple]:
    words = app.wait_for("KWORKER", timeout=120)
    pid, pgid = int(words[1]), int(words[2])
    assert pid > 1 and pgid == pid, f"a real worker leading its own group: {words}"
    start = child_ownership.process_start_time(pid)
    assert start is not None
    app.wait_for("KCHUNK", timeout=180)
    time.sleep(0.5)  # inference is under way
    assert child_ownership.process_start_time(pid) == start, "the worker is running its chunk"
    return pid, pgid, start


def _wait_gone(pid, start, pgid, bound) -> float:
    began = time.monotonic()
    while time.monotonic() - began < bound + 2:
        if _gone(pid, start) and _group_empty(pgid):
            return time.monotonic() - began
        time.sleep(0.02)
    return float("inf")


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGSEGV, signal.SIGABRT],
                         ids=["kx1a-sigkill", "kx2a-sigsegv", "kx2a-sigabrt"])
def test_kx1a_kx2a_the_window_ends_abnormally_during_real_inference(window, sig):
    app = window()
    pid, pgid, start = _worker_in_flight(app)
    os.kill(app.proc.pid, sig)
    seconds = _wait_gone(pid, start, pgid, ORPHAN_BOUND_S)
    _measured("KX-1/2(a)", signal=signal.Signals(sig).name, worker_gone_after_s=seconds)
    assert seconds <= ORPHAN_BOUND_S, f"the worker outlived the window by {seconds} s"
    scratch = Path(app.wait_for("KSCRATCH")[1])
    assert not (scratch / "output.mp3").exists(), "nothing was encoded, nothing under a name"


@pytest.mark.parametrize("how", ["sigterm", "quit"])
def test_kx3a_an_orderly_end_during_real_inference_completes_within_5s(window, how):
    app = window()
    pid, pgid, start = _worker_in_flight(app)
    began = time.monotonic()
    if how == "sigterm":
        os.kill(app.proc.pid, signal.SIGTERM)
    else:
        app.ask("quit")
    app.proc.wait(timeout=ORDERLY_BOUND_S + 5)
    seconds = _wait_gone(pid, start, pgid, ORDERLY_BOUND_S)
    _measured("KX-3(a)", how=how, window_and_worker_gone_s=time.monotonic() - began, worker_gone_after_exit_s=seconds)
    assert time.monotonic() - began <= ORDERLY_BOUND_S + 0.5 and seconds <= ORDERLY_BOUND_S


def test_kx7_without_the_lifeline_the_workers_orphan_is_seen(window):
    """The negative control: an owner whose class-A children get no lifeline. SIGKILL of the window then leaves the
    worker running -- so the KX tests above can fail -- and it is ended here, by identity."""
    app = window(lifeline=False)
    pid, pgid, start = _worker_in_flight(app)
    os.kill(app.proc.pid, signal.SIGKILL)
    seconds = _wait_gone(pid, start, pgid, ORPHAN_BOUND_S)
    _measured("KX-7", orphan_seen=seconds == float("inf") and not _gone(pid, start))
    try:
        assert seconds == float("inf") and not _gone(pid, start), "the orphan is seen"
    finally:
        child_ownership.signal_if_same(pid, start, signal.SIGKILL, group=True)
        _wait_gone(pid, start, pgid, ORPHAN_BOUND_S)
